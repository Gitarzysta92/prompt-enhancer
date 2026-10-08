"""First-run detection, one consent, first index, and periodic refresh."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
import prompt_enhancer.application.onboarding as onboarding_module
from prompt_enhancer.application.onboarding import (
    DetectionSignal,
    JSON_SAFE_INTEGER_MAX,
    LocalSourceRefreshWorker,
    OnboardingAccept,
    OnboardingError,
    OnboardingResult,
    OnboardingService,
    OnboardingStatus,
    ProviderDetection,
    count_transcripts,
    detect_codex,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.interfaces.http.onboarding_routes import create_onboarding_router


T0 = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _transcript(claude_home: Path, session: str) -> None:
    project = claude_home / "projects" / "-srv-example-onboard"
    project.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "Fix the onboarding demo"}, "timestamp": T0.isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": "/srv/example/onboard", "version": "2.1.0"}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5", "usage": {"input_tokens": 10, "output_tokens": 5}, "content": [{"type": "text", "text": "Done."}]}, "timestamp": (T0 + timedelta(seconds=5)).isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": "/srv/example/onboard", "version": "2.1.0"}),
    ]
    (project / f"{session}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_detection_reads_only_presence(tmp_path: Path) -> None:
    assert detect_codex(lambda name: None) is False
    assert detect_codex(lambda name: "/usr/local/bin/codex" if name == "codex" else None) is True
    assert count_transcripts(tmp_path) is None
    _transcript(tmp_path, "one")
    assert count_transcripts(tmp_path) == 1


class _CatalogRepository:
    def __init__(
        self,
        value: object,
        *,
        active: frozenset[Provider] = frozenset(),
    ) -> None:
        self.value = value
        self.active = set(active)

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        del tier
        return provider in self.active

    def grant_consent(self, provider: Provider, tier: DataTier) -> None:
        del tier
        self.active.add(provider)

    def provider_catalog_summary(self, provider: Provider) -> dict[str, object]:
        del provider
        if isinstance(self.value, Exception):
            raise self.value
        return {"sessions": self.value}


def _status_service(repository: _CatalogRepository, claude_home: Path) -> OnboardingService:
    return OnboardingService(
        repository,
        claude_home=lambda: claude_home,
        set_claude_home=None,
        index_codex=lambda: 0,
        index_claude=lambda: 0,
        which=lambda name: None,
        clock=lambda: T0,
    )


def test_status_preserves_known_zero_and_catalog_failure_as_unknown(tmp_path: Path) -> None:
    known = _status_service(_CatalogRepository(0), tmp_path / "absent")
    assert [provider.indexed_sessions for provider in known.status().providers] == [0, 0]
    assert [
        provider["indexed_sessions"]
        for provider in known.status().model_dump(mode="json")["providers"]
    ] == [0, 0]

    unavailable = _status_service(
        _CatalogRepository(RuntimeError("synthetic catalog unavailable")),
        tmp_path / "absent",
    )
    assert [provider.indexed_sessions for provider in unavailable.status().providers] == [None, None]
    assert [
        provider["indexed_sessions"]
        for provider in unavailable.status().model_dump(mode="json")["providers"]
    ] == [None, None]
    app = FastAPI()
    app.include_router(create_onboarding_router(lambda: None, unavailable))
    response = TestClient(app).get("/v1/onboarding")
    assert response.status_code == 200
    assert [provider["indexed_sessions"] for provider in response.json()["providers"]] == [None, None]


@pytest.mark.parametrize(
    "invalid",
    [True, -1, 1.5, "0", JSON_SAFE_INTEGER_MAX + 1],
)
def test_status_rejects_invalid_catalog_counts_as_unknown(tmp_path: Path, invalid: object) -> None:
    status = _status_service(_CatalogRepository(invalid), tmp_path / "absent").status()
    assert [provider.indexed_sessions for provider in status.providers] == [None, None]


def test_claude_root_presence_survives_enumeration_failure(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    projects = claude_home / "projects"
    projects.mkdir(parents=True)
    original_iterdir = Path.iterdir

    def unavailable_iterdir(path: Path):
        if path == projects:
            raise OSError("synthetic enumeration unavailable")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", unavailable_iterdir)
    claude = _status_service(_CatalogRepository(0), claude_home).status().providers[1]
    assert claude.installed is True
    assert claude.transcript_files is None
    assert claude.signal is DetectionSignal.CLAUDE_TRANSCRIPT_ENUMERATION_UNAVAILABLE


def test_claude_root_absence_and_known_empty_root_remain_distinct(tmp_path: Path) -> None:
    absent_home = tmp_path / "absent"
    absent = _status_service(_CatalogRepository(0), absent_home).status().providers[1]
    assert absent.installed is False
    assert absent.transcript_files is None
    assert absent.signal is DetectionSignal.NOT_FOUND

    empty_home = tmp_path / "empty"
    (empty_home / "projects").mkdir(parents=True)
    empty = _status_service(_CatalogRepository(0), empty_home).status().providers[1]
    assert empty.installed is True
    assert empty.transcript_files == 0
    assert empty.signal is DetectionSignal.CLAUDE_TRANSCRIPT_ROOT


def test_transcript_count_cap_is_explicitly_non_exact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(onboarding_module, "MAX_TRANSCRIPT_COUNT_SCAN", 2)
    claude_home = tmp_path / "claude-home"
    _transcript(claude_home, "one")
    _transcript(claude_home, "two")
    assert count_transcripts(claude_home) == 2
    at_limit = _status_service(_CatalogRepository(0), claude_home).status().providers[1]
    assert at_limit.transcript_files == 2
    assert at_limit.signal is DetectionSignal.CLAUDE_TRANSCRIPT_ROOT

    _transcript(claude_home, "three")
    assert count_transcripts(claude_home) is None
    capped = _status_service(_CatalogRepository(0), claude_home).status().providers[1]
    assert capped.installed is True
    assert capped.transcript_files is None
    assert capped.signal is DetectionSignal.CLAUDE_TRANSCRIPT_COUNT_CAPPED


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "0", JSON_SAFE_INTEGER_MAX + 1])
def test_wire_count_models_reject_non_strict_or_unsafe_values(
    tmp_path: Path,
    invalid: object,
) -> None:
    status = _status_service(_CatalogRepository(0), tmp_path / "absent").status()
    with pytest.raises(ValidationError):
        ProviderDetection(
            provider="codex",
            installed=False,
            signal=DetectionSignal.NOT_FOUND,
            consent_active=False,
            indexed_sessions=invalid,  # type: ignore[arg-type]
            transcript_files=None,
        )
    with pytest.raises(ValidationError):
        OnboardingResult(
            granted=(),
            indexed_sessions=invalid,  # type: ignore[arg-type]
            status=status,
        )


def test_status_model_rejects_reordered_or_inconsistent_summaries(tmp_path: Path) -> None:
    status = _status_service(_CatalogRepository(0), tmp_path / "absent").status()
    provider_payload = status.providers[0].model_dump(mode="python")
    provider_payload.pop("transcript_files")
    with pytest.raises(ValidationError):
        ProviderDetection.model_validate(provider_payload)

    missing_refresh_payload = status.model_dump(mode="python")
    missing_refresh_payload.pop("last_refresh_at")
    with pytest.raises(ValidationError):
        OnboardingStatus.model_validate(missing_refresh_payload)

    payload = status.model_dump(mode="python")
    payload["providers"] = tuple(reversed(payload["providers"]))
    with pytest.raises(ValidationError):
        OnboardingStatus.model_validate(payload)

    payload = status.model_dump(mode="python")
    payload["any_installed"] = True
    with pytest.raises(ValidationError):
        OnboardingStatus.model_validate(payload)


@pytest.mark.parametrize(
    "invalid",
    [True, 59, 600.0, "600", JSON_SAFE_INTEGER_MAX + 1],
)
def test_refresh_interval_is_strict_and_json_safe(
    tmp_path: Path,
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="^refresh interval is outside the supported range$"):
        OnboardingService(
            _CatalogRepository(0),
            claude_home=lambda: tmp_path / "absent",
            set_claude_home=None,
            index_codex=lambda: 0,
            index_claude=lambda: 0,
            refresh_interval_seconds=invalid,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("invalid", [True, -1, 60.1, float("inf")])
def test_command_refresh_lock_timeout_is_small_and_bounded(
    tmp_path: Path,
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="^command refresh lock timeout is invalid$"):
        OnboardingService(
            _CatalogRepository(0),
            claude_home=lambda: tmp_path / "absent",
            set_claude_home=None,
            index_codex=lambda: 0,
            index_claude=lambda: 0,
            command_refresh_lock_timeout_seconds=invalid,  # type: ignore[arg-type]
        )


def test_status_accept_and_refresh_flow(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    _transcript(claude_home, "s1")
    _transcript(claude_home, "s2")
    service = OnboardingService(
        application.database,
        claude_home=lambda: claude_home,
        set_claude_home=None,
        index_codex=lambda: 0,
        index_claude=lambda: int(application.create_claude_local_source_service().index(max_sessions=100).sessions_seen),
        which=lambda name: None,
        clock=lambda: T0,
    )
    status = service.status()
    codex, claude = status.providers
    assert codex.installed is False and claude.installed is True and claude.transcript_files == 2
    assert status.needs_onboarding is True and status.any_installed is True
    result = service.accept(OnboardingAccept(providers=frozenset({"claude_code"})))
    assert result.granted == ("claude_code",) and result.indexed_sessions == 2
    assert application.database.has_active_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    after = service.status()
    assert after.needs_onboarding is False and after.last_refresh_at == T0 and after.last_refresh_error is False
    assert after.providers[1].indexed_sessions == 2
    # A provider that is not installed cannot be accepted.
    try:
        service.accept(OnboardingAccept(providers=frozenset({"codex"})))
    except Exception as error:  # noqa: BLE001
        assert "codex_not_installed" in str(error)
    else:
        raise AssertionError("expected codex_not_installed")


def test_accept_validates_all_requested_providers_before_granting_consent(
    tmp_path: Path,
) -> None:
    claude_home = tmp_path / "claude-home"
    (claude_home / "projects").mkdir(parents=True)
    repository = _CatalogRepository(0)
    service = _status_service(repository, claude_home)

    with pytest.raises(OnboardingError, match="^codex_not_installed$") as failure:
        service.accept(
            OnboardingAccept(providers=frozenset({"claude_code", "codex"}))
        )

    assert failure.value.code == "codex_not_installed"
    assert repository.active == set()


def test_refresh_swallows_provider_errors(tmp_path: Path) -> None:
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    Database(settings.database_path).grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    calls = {"n": 0}

    def failing_codex() -> int:
        calls["n"] += 1
        raise RuntimeError("app server unavailable")

    service = OnboardingService(application.database, claude_home=lambda: tmp_path / "none", set_claude_home=None,
                                index_codex=failing_codex, index_claude=lambda: 0, which=lambda n: None,
                                refresh_interval_seconds=60, clock=lambda: T0)
    assert service.refresh() is None
    assert calls["n"] == 1 and service.status().last_refresh_error is True


def _codex_command_service(
    repository: _CatalogRepository,
    tmp_path: Path,
    *,
    index_codex,
    enable_automation=None,
) -> OnboardingService:
    return OnboardingService(
        repository,
        claude_home=lambda: tmp_path / "absent",
        set_claude_home=None,
        index_codex=index_codex,
        index_claude=lambda: 0,
        enable_automation=enable_automation,
        which=lambda name: "C:/example/codex.exe" if name == "codex" else None,
        refresh_interval_seconds=60,
        clock=lambda: T0,
    )


@pytest.mark.parametrize(
    ("returned", "expected"),
    [
        (0, 0),
        (True, None),
        (-1, None),
        (1.5, None),
        ("1", None),
        (JSON_SAFE_INTEGER_MAX + 1, None),
    ],
)
def test_accept_strictly_validates_indexer_counts(
    tmp_path: Path,
    returned: object,
    expected: int | None,
) -> None:
    repository = _CatalogRepository(0)
    service = _codex_command_service(
        repository,
        tmp_path,
        index_codex=lambda: returned,
    )
    result = service.accept(OnboardingAccept(providers=frozenset({"codex"})))
    assert result.indexed_sessions == expected
    assert result.status.last_refresh_error is (expected is None)


@pytest.mark.parametrize(
    "returned",
    [True, -1, 1.5, "1", JSON_SAFE_INTEGER_MAX + 1],
)
def test_refresh_strictly_validates_automation_counts(
    tmp_path: Path,
    returned: object,
) -> None:
    repository = _CatalogRepository(0)
    service = _codex_command_service(
        repository,
        tmp_path,
        index_codex=lambda: 0,
        enable_automation=lambda provider: returned,
    )
    result = service.accept(OnboardingAccept(providers=frozenset({"codex"})))
    assert result.indexed_sessions == 0
    assert result.status.last_refresh_error is True
    assert service.automation_grants_created is None


def test_refresh_rejects_json_unsafe_aggregate(tmp_path: Path) -> None:
    claude_home = tmp_path / "claude-home"
    (claude_home / "projects").mkdir(parents=True)
    repository = _CatalogRepository(
        0,
        active=frozenset({Provider.CODEX, Provider.CLAUDE_CODE}),
    )
    service = OnboardingService(
        repository,
        claude_home=lambda: claude_home,
        set_claude_home=None,
        index_codex=lambda: JSON_SAFE_INTEGER_MAX,
        index_claude=lambda: 1,
        which=lambda name: "C:/example/codex.exe" if name == "codex" else None,
        clock=lambda: T0,
    )
    assert service.refresh() is None
    assert service.status().last_refresh_error is True


def test_accept_waits_for_in_flight_periodic_refresh(tmp_path: Path) -> None:
    repository = _CatalogRepository(0, active=frozenset({Provider.CODEX}))
    first_index_entered = threading.Event()
    release_first_index = threading.Event()
    command_refresh_entered = threading.Event()
    calls_lock = threading.Lock()
    calls = 0

    def index_codex() -> int:
        nonlocal calls
        with calls_lock:
            calls += 1
            call = calls
        if call == 1:
            first_index_entered.set()
            assert release_first_index.wait(timeout=5)
        return 1

    class ObservedOnboardingService(OnboardingService):
        def refresh(
            self,
            only: frozenset[Provider] | None = None,
            *,
            wait_for_lock: bool = False,
        ) -> int | None:
            if wait_for_lock:
                command_refresh_entered.set()
            return super().refresh(only, wait_for_lock=wait_for_lock)

    service = ObservedOnboardingService(
        repository,
        claude_home=lambda: tmp_path / "absent",
        set_claude_home=None,
        index_codex=index_codex,
        index_claude=lambda: 0,
        which=lambda name: "C:/example/codex.exe" if name == "codex" else None,
        clock=lambda: T0,
    )
    periodic = threading.Thread(target=service.refresh)
    periodic.start()
    assert first_index_entered.wait(timeout=1)

    accepted: list[OnboardingResult] = []
    command = threading.Thread(
        target=lambda: accepted.append(
            service.accept(OnboardingAccept(providers=frozenset({"codex"})))
        )
    )
    command.start()
    assert command_refresh_entered.wait(timeout=1)
    assert command.is_alive() is True
    release_first_index.set()
    periodic.join(timeout=1)
    command.join(timeout=1)

    assert periodic.is_alive() is False
    assert command.is_alive() is False
    assert calls == 2
    assert accepted[0].indexed_sessions == 1


def test_accept_lock_wait_is_bounded_and_reports_unknown(tmp_path: Path) -> None:
    repository = _CatalogRepository(0, active=frozenset({Provider.CODEX}))
    periodic_entered = threading.Event()
    release_periodic = threading.Event()
    calls = 0

    def index_codex() -> int:
        nonlocal calls
        calls += 1
        periodic_entered.set()
        assert release_periodic.wait(timeout=5)
        return 1

    service = OnboardingService(
        repository,
        claude_home=lambda: tmp_path / "absent",
        set_claude_home=None,
        index_codex=index_codex,
        index_claude=lambda: 0,
        which=lambda name: "C:/example/codex.exe" if name == "codex" else None,
        command_refresh_lock_timeout_seconds=0.01,
        clock=lambda: T0,
    )
    periodic = threading.Thread(target=service.refresh)
    periodic.start()
    assert periodic_entered.wait(timeout=1)

    accepted: list[OnboardingResult] = []
    command = threading.Thread(
        target=lambda: accepted.append(
            service.accept(OnboardingAccept(providers=frozenset({"codex"})))
        )
    )
    command.start()
    command.join(timeout=1)
    returned_within_bound = not command.is_alive()
    release_periodic.set()
    periodic.join(timeout=1)
    command.join(timeout=1)

    assert returned_within_bound is True
    assert periodic.is_alive() is False
    assert command.is_alive() is False
    assert calls == 1
    assert accepted[0].indexed_sessions is None


class _RefreshProbe:
    refresh_interval_seconds = 60

    def __init__(self) -> None:
        self.calls = 0
        self.called = threading.Event()

    def refresh(self) -> int:
        self.calls += 1
        self.called.set()
        return 0


def test_refresh_worker_start_stop_and_restart_are_atomic() -> None:
    service = _RefreshProbe()
    worker = LocalSourceRefreshWorker(service, initial_delay_seconds=0)
    assert worker.is_alive() is False
    worker.start()
    assert service.called.wait(timeout=1)
    assert worker.is_alive() is True
    worker.start()
    assert service.calls == 1
    worker.stop()
    assert worker.is_alive() is False

    service.called.clear()
    worker.start()
    assert service.called.wait(timeout=1)
    assert service.calls == 2
    worker.stop()
    assert worker.is_alive() is False


def test_refresh_worker_start_failure_is_atomic_and_restartable(monkeypatch) -> None:
    service = _RefreshProbe()
    worker = LocalSourceRefreshWorker(service, initial_delay_seconds=0)
    original_start = threading.Thread.start

    def failing_start(thread: threading.Thread) -> None:
        del thread
        raise RuntimeError("synthetic private startup detail")

    monkeypatch.setattr(threading.Thread, "start", failing_start)
    with pytest.raises(
        RuntimeError,
        match="^local source refresh worker failed to start$",
    ) as failure:
        worker.start()
    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None
    assert worker.is_alive() is False

    monkeypatch.setattr(threading.Thread, "start", original_start)
    worker.start()
    assert service.called.wait(timeout=1)
    worker.stop()
    assert worker.is_alive() is False


class _BlockingRefreshProbe:
    refresh_interval_seconds = 60

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def refresh(self) -> int:
        self.entered.set()
        self.release.wait(timeout=5)
        return 0


def test_refresh_worker_stop_has_fixed_timeout_error() -> None:
    service = _BlockingRefreshProbe()
    worker = LocalSourceRefreshWorker(service, initial_delay_seconds=0)
    worker.start()
    assert service.entered.wait(timeout=1)
    with pytest.raises(
        RuntimeError,
        match="^local source refresh worker did not stop before timeout$",
    ):
        worker.stop(timeout=0.01)
    assert worker.is_alive() is True
    service.release.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False


def test_refresh_worker_rejects_start_while_stopping_then_restarts() -> None:
    service = _BlockingRefreshProbe()
    worker = LocalSourceRefreshWorker(service, initial_delay_seconds=0)
    worker.start()
    assert service.entered.wait(timeout=1)

    with pytest.raises(
        RuntimeError,
        match="^local source refresh worker did not stop before timeout$",
    ):
        worker.stop(timeout=0.01)
    with pytest.raises(RuntimeError, match="^worker_stop_in_progress$") as failure:
        worker.start()

    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None
    assert worker.is_alive() is True

    service.release.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False

    service.entered.clear()
    worker.start()
    assert service.entered.wait(timeout=1)
    assert worker.is_alive() is True
    worker.stop(timeout=1)
    assert worker.is_alive() is False


def test_refresh_worker_join_failure_is_content_free() -> None:
    service = _RefreshProbe()
    worker = LocalSourceRefreshWorker(service, initial_delay_seconds=0)

    class FailingJoinThread:
        def is_alive(self) -> bool:
            return True

        def join(self, *, timeout: float) -> None:
            del timeout
            raise RuntimeError("synthetic private join detail")

    worker._thread = FailingJoinThread()  # type: ignore[assignment]  # noqa: SLF001
    with pytest.raises(
        RuntimeError,
        match="^local source refresh worker failed to stop$",
    ) as failure:
        worker.stop(timeout=0.01)
    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None


def test_http_onboarding_routes_and_path_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PROMPT_ENHANCER_CLAUDE_HOME", raising=False)
    # Pin PATH detection: this machine may have the real Codex CLI installed.
    monkeypatch.setattr("prompt_enhancer.application.onboarding.shutil.which", lambda name: None)
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    assert client.get("/v1/onboarding").status_code == 401
    status = client.get("/v1/onboarding", headers=headers).json()
    assert {p["provider"] for p in status["providers"]} == {"codex", "claude_code"}
    # Point the app at a folder the person supplies.
    supplied = tmp_path / "supplied-claude-home"
    _transcript(supplied, "p1")
    bad = client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"], "claude_home": str(tmp_path / "nope")})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "claude_home_invalid"
    ok = client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"], "claude_home": str(supplied)})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["granted"] == ["claude_code"] and body["indexed_sessions"] == 1
    assert (settings.claude_home_override_path).read_text(encoding="utf-8").strip() == str(supplied)
    sessions = client.get("/v1/sessions?limit=50&offset=0", headers=headers).json()["sessions"]
    assert [s["provider"] for s in sessions] == ["claude_code"]
    assert sessions[0]["session_display_name"] == "Fix the onboarding demo"
    refreshed = client.post("/v1/onboarding/refresh", headers=headers)
    assert refreshed.status_code == 200 and refreshed.json()["needs_onboarding"] is False
    # Default-on analysis: the indexed project holds a standing local grant,
    # and refreshing again does not duplicate it.
    grants = client.get("/v1/automation-grants?provider=claude_code&active_only=true", headers=headers)
    assert grants.status_code == 200, grants.text
    records = grants.json()
    assert len(records) == 1
    assert records[0]["scope"]["provider"] == "claude_code"
    assert records[0]["scope"]["project_id"] == sessions[0]["project_id"]
    assert records[0]["scope"]["local_only"] is True
    client.post("/v1/onboarding/refresh", headers=headers)
    assert len(client.get("/v1/automation-grants?provider=claude_code&active_only=true", headers=headers).json()) == 1
    # Indexing also proposes task candidates, so the Discovery inbox is not empty.
    inbox = client.get("/v1/discovery/candidates?limit=50&offset=0", headers=headers)
    assert inbox.status_code == 200, inbox.text
    candidates = inbox.json()["candidates"]
    assert len(candidates) >= 1, inbox.text
    # Candidates carry the catalog names so the inbox shows titles, not hashes.
    assert candidates[0]["candidate"]["session_display_name"] == "Fix the onboarding demo"
    assert candidates[0]["candidate"]["project_display_name"]
    # The transcript text window is now the provider's primary compatibility surface.
    compat = client.post("/v1/providers/claude_code/compatibility/check", headers=headers).json()
    assert compat["capability"] == "session_text_analysis"
    assert compat["state"] == "compatible" and compat["provider_version"] == "2.1.0"
