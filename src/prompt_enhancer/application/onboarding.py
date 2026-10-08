"""First-run detection, one consent, and automatic refresh for local sources.

The owner's direction: when Codex or Claude Code is present on this machine,
the app should ask once and then load every project and session - and keep
them current - without further clicks.  When neither is present it says so and
lets the person point at a transcript folder.

Detection reads nothing private: it asks whether the Codex CLI is on PATH and
whether a Claude Code transcript root directory exists (and how many transcript
files it holds).  Accepting grants the ordinary per-provider consent and runs
the first index; the refresh worker then re-indexes consented providers on a
timer, swallowing provider errors so a flaky source never takes the app down.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
import math
import shutil
import threading
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..domain import DataTier, Provider, StrictModel


ONBOARDING_CONTRACT_VERSION = "onboarding.v1"
DEFAULT_REFRESH_INTERVAL_SECONDS = 600
DEFAULT_COMMAND_REFRESH_LOCK_TIMEOUT_SECONDS = 5.0
MAX_COMMAND_REFRESH_LOCK_TIMEOUT_SECONDS = 60.0
MAX_TRANSCRIPT_COUNT_SCAN = 20_000
JSON_SAFE_INTEGER_MAX = 9_007_199_254_740_991
_WORKER_START_FAILURE = "local source refresh worker failed to start"
_WORKER_STOP_IN_PROGRESS = "worker_stop_in_progress"
_WORKER_STOP_FAILURE = "local source refresh worker failed to stop"
_WORKER_STOP_TIMEOUT = "local source refresh worker did not stop before timeout"


class DetectionSignal(StrEnum):
    CODEX_CLI_ON_PATH = "codex_cli_on_path"
    CLAUDE_TRANSCRIPT_ROOT = "claude_transcript_root"
    CLAUDE_TRANSCRIPT_ENUMERATION_UNAVAILABLE = (
        "claude_transcript_enumeration_unavailable"
    )
    CLAUDE_TRANSCRIPT_COUNT_CAPPED = "claude_transcript_count_capped"
    NOT_FOUND = "not_found"


class ProviderDetection(StrictModel):
    provider: Literal["codex", "claude_code"]
    installed: bool
    signal: DetectionSignal
    consent_active: bool
    indexed_sessions: int | None = Field(
        ge=0,
        le=JSON_SAFE_INTEGER_MAX,
        strict=True,
    )
    transcript_files: int | None = Field(
        ge=0,
        le=JSON_SAFE_INTEGER_MAX,
        strict=True,
    )

    @model_validator(mode="after")
    def validate_detection_truth(self) -> ProviderDetection:
        if self.provider == "codex":
            expected = (
                DetectionSignal.CODEX_CLI_ON_PATH
                if self.installed
                else DetectionSignal.NOT_FOUND
            )
            if self.signal is not expected or self.transcript_files is not None:
                raise ValueError("Codex detection fields are inconsistent")
            return self
        if not self.installed:
            if self.signal is not DetectionSignal.NOT_FOUND or self.transcript_files is not None:
                raise ValueError("absent Claude detection fields are inconsistent")
            return self
        if self.signal is DetectionSignal.CLAUDE_TRANSCRIPT_ROOT:
            if self.transcript_files is None:
                raise ValueError("enumerated Claude roots require a transcript count")
            return self
        if self.signal not in {
            DetectionSignal.CLAUDE_TRANSCRIPT_ENUMERATION_UNAVAILABLE,
            DetectionSignal.CLAUDE_TRANSCRIPT_COUNT_CAPPED,
        } or self.transcript_files is not None:
            raise ValueError("installed Claude detection fields are inconsistent")
        return self


class OnboardingStatus(StrictModel):
    contract_version: Literal[ONBOARDING_CONTRACT_VERSION] = ONBOARDING_CONTRACT_VERSION
    providers: tuple[ProviderDetection, ...]
    any_installed: bool
    needs_onboarding: bool
    refresh_interval_seconds: int = Field(
        ge=60,
        le=JSON_SAFE_INTEGER_MAX,
        strict=True,
    )
    last_refresh_at: datetime | None
    last_refresh_error: bool = False
    claude_home_override_supported: bool = True

    @model_validator(mode="after")
    def validate_summary_truth(self) -> OnboardingStatus:
        if tuple(provider.provider for provider in self.providers) != (
            "codex",
            "claude_code",
        ):
            raise ValueError("onboarding providers must use canonical order")
        any_installed = any(provider.installed for provider in self.providers)
        needs_onboarding = (
            any(
                provider.installed and not provider.consent_active
                for provider in self.providers
            )
            or not any_installed
        )
        if self.any_installed is not any_installed:
            raise ValueError("any_installed does not match provider detections")
        if self.needs_onboarding is not needs_onboarding:
            raise ValueError("needs_onboarding does not match provider detections")
        return self


class OnboardingAccept(StrictModel):
    providers: frozenset[Literal["codex", "claude_code"]] = Field(min_length=1)
    # Optional folder the person points at when Claude Code was not found.
    claude_home: str | None = Field(default=None, max_length=1024)


class OnboardingResult(StrictModel):
    granted: tuple[Literal["codex", "claude_code"], ...]
    indexed_sessions: int | None = Field(
        ge=0,
        le=JSON_SAFE_INTEGER_MAX,
        strict=True,
    )
    status: OnboardingStatus


class OnboardingError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def detect_codex(which: Callable[[str], str | None] = shutil.which) -> bool:
    return any(which(name) is not None for name in ("codex", "codex.cmd", "codex.exe"))


def _transcript_count(claude_home: Path) -> tuple[int | None, bool]:
    projects = claude_home / "projects"
    if not projects.is_dir():
        return None, False
    count = 0
    try:
        for project_dir in projects.iterdir():
            if not project_dir.is_dir() or project_dir.is_symlink():
                continue
            for candidate in project_dir.glob("*.jsonl"):
                if candidate.is_file() and not candidate.is_symlink():
                    count += 1
                    if count > MAX_TRANSCRIPT_COUNT_SCAN:
                        return None, True
    except OSError:
        return None, False
    return count, False


def count_transcripts(claude_home: Path) -> int | None:
    count, _capped = _transcript_count(claude_home)
    return count


def _known_count(value: object) -> int | None:
    if type(value) is not int or not 0 <= value <= JSON_SAFE_INTEGER_MAX:
        return None
    return value


class OnboardingService:
    """Detection, one consent, first index, and the periodic refresh."""

    _TIER = DataTier.REDACTED_CONTENT

    def __init__(
        self,
        repository,
        *,
        claude_home: Callable[[], Path],
        set_claude_home: Callable[[Path], None] | None,
        index_codex: Callable[[], int],
        index_claude: Callable[[], int],
        enable_automation: Callable[[Provider], int] | None = None,
        which: Callable[[str], str | None] | None = None,
        refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS,
        command_refresh_lock_timeout_seconds: float = (
            DEFAULT_COMMAND_REFRESH_LOCK_TIMEOUT_SECONDS
        ),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._claude_home = claude_home
        self._set_claude_home = set_claude_home
        self._index = {Provider.CODEX: index_codex, Provider.CLAUDE_CODE: index_claude}
        # Default-on analysis: after an index, every indexed project gets a
        # standing local automation grant so the single model lane analyses
        # new and changed sessions without further clicks.
        self._enable_automation = enable_automation
        self._last_automation_grants: int | None = 0
        # Resolved at call time so tests can pin PATH detection deterministically.
        self._which = which if which is not None else (lambda name: shutil.which(name))
        if (
            type(refresh_interval_seconds) is not int
            or not 60 <= refresh_interval_seconds <= JSON_SAFE_INTEGER_MAX
        ):
            raise ValueError("refresh interval is outside the supported range")
        if (
            isinstance(command_refresh_lock_timeout_seconds, bool)
            or not isinstance(command_refresh_lock_timeout_seconds, (int, float))
            or not math.isfinite(command_refresh_lock_timeout_seconds)
            or not 0 <= command_refresh_lock_timeout_seconds <= (
                MAX_COMMAND_REFRESH_LOCK_TIMEOUT_SECONDS
            )
        ):
            raise ValueError("command refresh lock timeout is invalid")
        self._interval = refresh_interval_seconds
        self._command_refresh_lock_timeout_seconds = float(
            command_refresh_lock_timeout_seconds
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._last_refresh_at: datetime | None = None
        self._last_refresh_error = False

    def _counts(self, provider: Provider) -> int | None:
        try:
            count = self._repository.provider_catalog_summary(provider)["sessions"]
        except Exception:
            return None
        return _known_count(count)

    def status(self) -> OnboardingStatus:
        codex_installed = detect_codex(self._which)
        claude_home = self._claude_home()
        claude_installed = (claude_home / "projects").is_dir()
        transcripts, transcripts_capped = (
            _transcript_count(claude_home) if claude_installed else (None, False)
        )
        if not claude_installed:
            claude_signal = DetectionSignal.NOT_FOUND
        elif transcripts_capped:
            claude_signal = DetectionSignal.CLAUDE_TRANSCRIPT_COUNT_CAPPED
        elif transcripts is None:
            claude_signal = DetectionSignal.CLAUDE_TRANSCRIPT_ENUMERATION_UNAVAILABLE
        else:
            claude_signal = DetectionSignal.CLAUDE_TRANSCRIPT_ROOT
        providers = (
            ProviderDetection(
                provider="codex",
                installed=codex_installed,
                signal=DetectionSignal.CODEX_CLI_ON_PATH if codex_installed else DetectionSignal.NOT_FOUND,
                consent_active=self._repository.has_active_consent(Provider.CODEX, self._TIER),
                indexed_sessions=self._counts(Provider.CODEX),
                transcript_files=None,
            ),
            ProviderDetection(
                provider="claude_code",
                installed=claude_installed,
                signal=claude_signal,
                consent_active=self._repository.has_active_consent(Provider.CLAUDE_CODE, self._TIER),
                indexed_sessions=self._counts(Provider.CLAUDE_CODE),
                transcript_files=transcripts,
            ),
        )
        any_installed = any(p.installed for p in providers)
        needs = any(p.installed and not p.consent_active for p in providers) or not any_installed
        return OnboardingStatus(
            providers=providers,
            any_installed=any_installed,
            needs_onboarding=needs,
            refresh_interval_seconds=self._interval,
            last_refresh_at=self._last_refresh_at,
            last_refresh_error=self._last_refresh_error,
            claude_home_override_supported=self._set_claude_home is not None,
        )

    def accept(self, request: OnboardingAccept) -> OnboardingResult:
        if request.claude_home is not None:
            if self._set_claude_home is None:
                raise OnboardingError("claude_home_override_unsupported")
            candidate = Path(request.claude_home).expanduser()
            if not candidate.is_dir() or not (candidate / "projects").is_dir():
                raise OnboardingError("claude_home_invalid")
            self._set_claude_home(candidate)
        status = self.status()
        installed = {p.provider for p in status.providers if p.installed}
        missing = set(request.providers).difference(installed)
        if missing:
            raise OnboardingError(f"{sorted(missing)[0]}_not_installed")
        granted: list[Literal["codex", "claude_code"]] = []
        for key in sorted(request.providers):
            self._repository.grant_consent(Provider(key), self._TIER)
            granted.append(key)
        indexed = self.refresh(
            only=frozenset(Provider(k) for k in granted),
            wait_for_lock=True,
        )
        return OnboardingResult(granted=tuple(granted), indexed_sessions=indexed, status=self.status())

    def refresh(
        self,
        only: frozenset[Provider] | None = None,
        *,
        wait_for_lock: bool = False,
    ) -> int | None:
        """Index every consented (or selected) provider; errors are swallowed per provider."""

        acquired = (
            self._lock.acquire(timeout=self._command_refresh_lock_timeout_seconds)
            if wait_for_lock
            else self._lock.acquire(blocking=False)
        )
        if not acquired:
            return None
        try:
            total = 0
            failed = False
            indexed_count_unknown = False
            for provider, index in self._index.items():
                if only is not None and provider not in only:
                    continue
                if not self._repository.has_active_consent(provider, self._TIER):
                    continue
                try:
                    indexed = _known_count(index())
                except Exception:
                    failed = True
                    indexed_count_unknown = True
                    continue
                if indexed is None or total > JSON_SAFE_INTEGER_MAX - indexed:
                    failed = True
                    indexed_count_unknown = True
                else:
                    total += indexed
                if self._enable_automation is not None:
                    try:
                        automation_grants = _known_count(self._enable_automation(provider))
                    except Exception:
                        failed = True
                        self._last_automation_grants = None
                        continue
                    if automation_grants is None:
                        failed = True
                        self._last_automation_grants = None
                    elif self._last_automation_grants is not None:
                        if (
                            self._last_automation_grants
                            > JSON_SAFE_INTEGER_MAX - automation_grants
                        ):
                            failed = True
                            self._last_automation_grants = None
                        else:
                            self._last_automation_grants += automation_grants
            self._last_refresh_at = self._clock()
            self._last_refresh_error = failed
            return None if indexed_count_unknown else total
        finally:
            self._lock.release()

    @property
    def refresh_interval_seconds(self) -> int:
        return self._interval

    @property
    def automation_grants_created(self) -> int | None:
        return self._last_automation_grants


class LocalSourceRefreshWorker:
    """Daemon thread: refresh at startup, then every interval; stops cleanly."""

    def __init__(self, service: OnboardingService, *, initial_delay_seconds: float = 5.0) -> None:
        self._service = service
        self._initial_delay = initial_delay_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError(_WORKER_STOP_IN_PROGRESS)
                return
            self._thread = None
            thread: threading.Thread | None = None
            start_failed = False
            try:
                self._stop.clear()
                thread = threading.Thread(
                    target=self._run,
                    name="local-source-refresh",
                    daemon=True,
                )
                thread.start()
            except Exception:
                self._stop.set()
                start_failed = True
            if start_failed or thread is None:
                raise RuntimeError(_WORKER_START_FAILURE)
            self._thread = thread

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop.set()
            if thread is threading.current_thread():
                raise RuntimeError(_WORKER_STOP_TIMEOUT)
            stop_failed = False
            try:
                thread.join(timeout=timeout)
            except Exception:
                stop_failed = True
            if stop_failed:
                raise RuntimeError(_WORKER_STOP_FAILURE)
            if thread.is_alive():
                raise RuntimeError(_WORKER_STOP_TIMEOUT)
            if self._thread is thread:
                self._thread = None

    def is_alive(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        if self._stop.wait(self._initial_delay):
            return
        while not self._stop.is_set():
            try:
                self._service.refresh()
            except Exception:
                pass
            if self._stop.wait(self._service.refresh_interval_seconds):
                return


__all__ = (
    "DEFAULT_COMMAND_REFRESH_LOCK_TIMEOUT_SECONDS",
    "DEFAULT_REFRESH_INTERVAL_SECONDS",
    "DetectionSignal",
    "JSON_SAFE_INTEGER_MAX",
    "LocalSourceRefreshWorker",
    "MAX_COMMAND_REFRESH_LOCK_TIMEOUT_SECONDS",
    "ONBOARDING_CONTRACT_VERSION",
    "OnboardingAccept",
    "OnboardingError",
    "OnboardingResult",
    "OnboardingService",
    "OnboardingStatus",
    "ProviderDetection",
    "count_transcripts",
    "detect_codex",
)
