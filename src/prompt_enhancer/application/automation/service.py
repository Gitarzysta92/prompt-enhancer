"""Consent-aware scheduler for renewable local automation grants."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import Callable, Literal, Protocol

from pydantic import Field, model_validator

from ...domain import DataTier, Provider, StrictModel
from ..runtime_cancellation import (
    RuntimeCooperativeStop,
    raise_if_runtime_cancelled,
    runtime_request_scope,
)
from ..jobs import PowerSourceReader, PowerSourceState
from ..analysis.coaching_baselines import COACHING_METRIC_DEFINITIONS
from .contracts import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationCandidateSource,
    AutomationGrantDraft,
    AutomationGrantRecord,
    AutomationGrantRepository,
    AutomationGrantScope,
    AutomationGrantState,
    AutomationSessionCandidate,
    is_reviewed_automation_resource_policy,
)


AUTOMATION_POLL_LIMIT = 100
DEFAULT_AUTOMATION_WORKER_POLL_SECONDS = 60.0
_WORKER_START_FAILURE = "worker_start_failed"
_WORKER_STOP_IN_PROGRESS = "worker_stop_in_progress"
_WORKER_STOP_FAILURE = "worker_stop_failed"
_WORKER_STOP_TIMEOUT = "worker_stop_timeout"
COACHING_AUTOMATION_METRIC_KEYS = frozenset(
    definition.key for definition in COACHING_METRIC_DEFINITIONS
)


class AutomationGrantError(RuntimeError):
    """Base class whose messages are fixed, content-free reason codes."""

    def __init__(self, code: str) -> None:
        if not code.startswith("automation_"):
            raise ValueError("automation error code is invalid")
        self.code = code
        super().__init__(code)


class AutomationConsentError(AutomationGrantError):
    pass


class AutomationSelectionError(AutomationGrantError):
    pass


class AutomationGrantNotFoundError(AutomationGrantError):
    pass


class AutomationAccessPolicy(Protocol):
    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool: ...

    def project_is_indexed(self, provider: Provider, project_id: str) -> bool: ...


class AutomationIdFactory(Protocol):
    def new_id(self) -> str: ...


class AutomationCatalogRefresher(Protocol):
    def refresh(self, provider: Provider, *, max_sessions: int) -> None: ...


class AutomationScheduleResult(StrictModel):
    created: bool
    superseded: int = Field(default=0, ge=0)


class AutomationJobSink(Protocol):
    def schedule(
        self,
        grant: AutomationGrantRecord,
        candidate: AutomationSessionCandidate,
    ) -> AutomationScheduleResult: ...

    def cancel_for_grant(
        self,
        grant_id: str,
        *,
        now: datetime,
    ) -> int: ...


class AutomationPollResult(StrictModel):
    grants_checked: int = Field(ge=0)
    grants_revoked: int = Field(ge=0)
    grants_power_paused: int = Field(ge=0)
    grants_policy_unsupported: int = Field(ge=0)
    power_external_observations: int = Field(ge=0)
    power_battery_observations: int = Field(ge=0)
    power_unknown_observations: int = Field(ge=0)
    candidates_seen: int = Field(ge=0)
    jobs_created: int = Field(ge=0)
    jobs_reused: int = Field(ge=0)
    jobs_superseded: int = Field(ge=0)
    failures: int = Field(ge=0)
    maximum_session_runtime_deadline_enforced: Literal[False] = Field(
        default=False,
        description=(
            "The declared runtime budget is not a force-stopping wall-clock deadline."
        ),
    )
    session_quality_result_publication_deadline_enforced: Literal[True] = Field(
        default=True,
        description=(
            "Automated session-quality results cannot publish at or after the "
            "restart-durable first-claim cutoff."
        ),
    )
    blocking_execution_preemption_enforced: Literal[False] = Field(
        default=False,
        description=(
            "An in-flight blocking local read or calculation is not forcibly preempted."
        ),
    )

    @model_validator(mode="after")
    def coherent_receipt(self) -> AutomationPollResult:
        categorized = (
            self.grants_policy_unsupported
            + self.grants_revoked
            + self.power_external_observations
            + self.power_battery_observations
            + self.power_unknown_observations
        )
        if categorized != self.grants_checked:
            raise ValueError("every checked grant requires one admission outcome")
        if self.grants_power_paused != (
            self.power_battery_observations + self.power_unknown_observations
        ):
            raise ValueError("power pause count must match non-external observations")
        if self.grants_policy_unsupported > self.failures:
            raise ValueError("unsupported policies must be counted as failures")
        if self.jobs_created + self.jobs_reused > self.candidates_seen:
            raise ValueError("scheduled outcomes cannot exceed candidates")
        if self.jobs_superseded > self.jobs_created + self.jobs_reused:
            raise ValueError("superseded jobs require a scheduling outcome")
        return self


class AutomationGrantService:
    """Schedule only indexed, changed metadata under active local consent."""

    _TIER = DataTier.REDACTED_CONTENT

    def __init__(
        self,
        repository: AutomationGrantRepository,
        access: AutomationAccessPolicy,
        refresher: AutomationCatalogRefresher,
        candidates: AutomationCandidateSource,
        jobs: AutomationJobSink,
        id_factory: AutomationIdFactory,
        power_source: PowerSourceReader | None = None,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._access = access
        self._refresher = refresher
        self._candidates = candidates
        self._jobs = jobs
        self._id_factory = id_factory
        self._power_source = power_source
        self._clock = clock

    def create(self, scope: AutomationGrantScope) -> AutomationGrantRecord:
        self._require_reviewed_resource_policy(scope)
        self._require_access(scope)
        now = self._clock()
        return self._repository.create(
            AutomationGrantDraft(
                grant_id=self._id_factory.new_id(),
                scope=scope,
                created_at=now,
                expires_at=now + AUTOMATION_GRANT_LIFETIME,
            )
        )

    def get(self, grant_id: str) -> AutomationGrantRecord:
        return self._require_grant(grant_id)

    def list_for_provider(
        self,
        provider: Provider,
        *,
        active_only: bool = False,
    ) -> tuple[AutomationGrantRecord, ...]:
        records = self._repository.list_for_provider(
            provider,
            active_only=active_only,
        )
        if not active_only:
            return records
        now = self._clock()
        return tuple(
            record
            for record in records
            if record.effective_state(now) is AutomationGrantState.ACTIVE
        )

    def renew(self, grant_id: str) -> AutomationGrantRecord:
        current = self._require_grant(grant_id)
        self._require_reviewed_resource_policy(current.scope)
        self._require_access(current.scope)
        return self._repository.renew(grant_id, now=self._clock())

    def revoke(self, grant_id: str) -> AutomationGrantRecord:
        now = self._clock()
        self._require_grant(grant_id)
        revoked = self._repository.revoke(grant_id, now=now)
        self._jobs.cancel_for_grant(grant_id, now=now)
        return revoked

    def revoke_provider(self, provider: Provider) -> int:
        now = self._clock()
        grants = self._repository.list_for_provider(provider, active_only=True)
        for grant in grants:
            self._repository.revoke(grant.grant_id, now=now)
            self._jobs.cancel_for_grant(grant.grant_id, now=now)
        return len(grants)

    def ensure_default_grants(
        self,
        provider: Provider,
        project_ids: tuple[str, ...],
        *,
        max_new: int = 200,
    ) -> int:
        """Create the default local grant for each indexed project without one.

        Default-on analysis: the person consented to the provider once; every
        project they have indexed then gets the standard (reviewed, local-only,
        battery-aware) grant for the rubric metrics.  Projects that already
        hold an active grant are left alone, so this is idempotent and safe to
        call on every refresh.  Individual failures are counted, not raised.
        """

        active = {
            record.scope.project_id
            for record in self.list_for_provider(provider, active_only=True)
        }
        metric_keys = tuple(sorted(COACHING_AUTOMATION_METRIC_KEYS))
        created = 0
        for project_id in project_ids:
            if project_id in active or created >= max_new:
                continue
            try:
                self.create(
                    AutomationGrantScope(
                        provider=provider,
                        project_id=project_id,
                        metric_keys=metric_keys,
                    )
                )
            except (AutomationGrantError, ValueError):
                continue
            created += 1
        return created

    def poll_due(self, *, limit: int = AUTOMATION_POLL_LIMIT) -> AutomationPollResult:
        if limit < 1 or limit > AUTOMATION_POLL_LIMIT:
            raise ValueError("automation poll limit is out of bounds")
        raise_if_runtime_cancelled("automation_poll_cancelled")
        now = self._clock()
        self._repository.expire_due(now=now)
        checked = revoked = power_paused = policy_unsupported = 0
        power_external = power_battery = power_unknown = 0
        seen = created = reused = superseded = failures = 0
        for due_grant in self._repository.list_due(now=now, limit=limit):
            raise_if_runtime_cancelled("automation_poll_cancelled")
            grant_now = self._clock()
            grant = self._repository.get(due_grant.grant_id)
            if grant is None or not grant.is_due(grant_now):
                continue
            checked += 1
            next_check_at = grant_now + timedelta(
                seconds=grant.scope.check_interval_seconds
            )
            if not is_reviewed_automation_resource_policy(
                grant.scope.resource_policy
            ):
                policy_unsupported += 1
                failures += 1
                self._repository.record_check(
                    grant.grant_id,
                    now=grant_now,
                    next_check_at=next_check_at,
                    error_code="automation_resource_policy_unsupported",
                )
                continue
            if not self._access.has_active_consent(
                grant.scope.provider, self._TIER
            ):
                self._repository.revoke(grant.grant_id, now=grant_now)
                self._jobs.cancel_for_grant(grant.grant_id, now=grant_now)
                revoked += 1
                continue
            power_source = self._current_power_source()
            power_external += int(
                power_source is PowerSourceState.EXTERNAL_POWER
            )
            power_battery += int(power_source is PowerSourceState.BATTERY)
            power_unknown += int(power_source is PowerSourceState.UNKNOWN)
            if power_source is not PowerSourceState.EXTERNAL_POWER:
                power_paused += 1
                self._repository.record_check(
                    grant.grant_id,
                    now=grant_now,
                    next_check_at=next_check_at,
                    error_code="automation_paused_for_power_source",
                )
                continue
            try:
                self._refresher.refresh(
                    grant.scope.provider,
                    max_sessions=grant.scope.newest_session_limit,
                )
                candidates = self._candidates.newest_changed(
                    grant.scope,
                    limit=grant.scope.newest_session_limit,
                )
                seen += len(candidates)
                for candidate in candidates:
                    if (
                        candidate.provider is not grant.scope.provider
                        or candidate.project_id != grant.scope.project_id
                    ):
                        raise AutomationSelectionError(
                            "automation_candidate_scope_mismatch"
                        )
                    outcome = self._jobs.schedule(grant, candidate)
                    created += int(outcome.created)
                    reused += int(not outcome.created)
                    superseded += outcome.superseded
                self._repository.record_check(
                    grant.grant_id,
                    now=grant_now,
                    next_check_at=next_check_at,
                    error_code=None,
                )
            except RuntimeCooperativeStop:
                # Shutdown is control flow, not a provider failure.  Swallowing
                # it here makes the worker continue through every due grant and
                # can outlive the native owner's bounded cleanup deadline.
                raise
            except AutomationSelectionError:
                failures += 1
                self._repository.record_check(
                    grant.grant_id,
                    now=grant_now,
                    next_check_at=next_check_at,
                    error_code="candidate_scope_mismatch",
                )
            except Exception:
                # Provider/repository exception text may contain private details.
                failures += 1
                self._repository.record_check(
                    grant.grant_id,
                    now=grant_now,
                    next_check_at=next_check_at,
                    error_code="automation_check_failed",
                )
        return AutomationPollResult(
            grants_checked=checked,
            grants_revoked=revoked,
            grants_power_paused=power_paused,
            grants_policy_unsupported=policy_unsupported,
            power_external_observations=power_external,
            power_battery_observations=power_battery,
            power_unknown_observations=power_unknown,
            candidates_seen=seen,
            jobs_created=created,
            jobs_reused=reused,
            jobs_superseded=superseded,
            failures=failures,
            maximum_session_runtime_deadline_enforced=False,
            session_quality_result_publication_deadline_enforced=True,
            blocking_execution_preemption_enforced=False,
        )

    def _current_power_source(self) -> PowerSourceState:
        if self._power_source is None:
            return PowerSourceState.UNKNOWN
        try:
            state = self._power_source.current()
        except Exception:
            return PowerSourceState.UNKNOWN
        return state if isinstance(state, PowerSourceState) else PowerSourceState.UNKNOWN

    @staticmethod
    def _require_reviewed_resource_policy(scope: AutomationGrantScope) -> None:
        if not is_reviewed_automation_resource_policy(scope.resource_policy):
            raise AutomationSelectionError(
                "automation_resource_policy_unsupported"
            )

    def _require_access(self, scope: AutomationGrantScope) -> None:
        if not set(scope.metric_keys).issubset(COACHING_AUTOMATION_METRIC_KEYS):
            raise AutomationSelectionError("automation_metric_unsupported")
        if not self._access.has_active_consent(scope.provider, self._TIER):
            raise AutomationConsentError("automation_consent_required")
        if not self._access.project_is_indexed(scope.provider, scope.project_id):
            raise AutomationSelectionError("automation_project_not_indexed")

    def _require_grant(self, grant_id: str) -> AutomationGrantRecord:
        grant = self._repository.get(grant_id)
        if grant is None:
            raise AutomationGrantNotFoundError("automation_grant_not_found")
        return grant


class AutomationGrantWorker:
    """One local scheduler thread; job execution remains in the job worker."""

    def __init__(
        self,
        service: AutomationGrantService,
        *,
        poll_seconds: float = DEFAULT_AUTOMATION_WORKER_POLL_SECONDS,
    ) -> None:
        if not 1 <= poll_seconds <= 15 * 60:
            raise ValueError("automation worker poll interval is out of bounds")
        self._service = service
        self._poll_seconds = poll_seconds
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event.is_set():
                    raise RuntimeError(_WORKER_STOP_IN_PROGRESS)
                return
            self._thread = None
            start_failed = False
            try:
                self._stop_event.clear()
                thread = Thread(
                    target=self._run,
                    name="automation-grant-worker",
                    daemon=True,
                )
                thread.start()
            except Exception:
                self._stop_event.set()
                start_failed = True
            if start_failed:
                raise RuntimeError(_WORKER_START_FAILURE)
            self._thread = thread

    def is_alive(self) -> bool:
        """Return thread liveness without exposing scheduler details."""

        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
            stop_failed = False
            timed_out = False
            try:
                thread.join(timeout=timeout)
                timed_out = thread.is_alive()
            except Exception:
                stop_failed = True
            if stop_failed:
                raise RuntimeError(_WORKER_STOP_FAILURE)
            if timed_out:
                raise RuntimeError(_WORKER_STOP_TIMEOUT)
            if self._thread is thread:
                self._thread = None

    def run_once(self) -> AutomationPollResult:
        return self._service.poll_due()

    def _run(self) -> None:
        # Do not launch a provider refresh in the startup critical path.  A
        # desktop window can be opened, checked, and closed before the first
        # scheduled interval without creating a Codex helper or transcript
        # scan that immediately has to be cancelled again.
        while not self._stop_event.wait(self._poll_seconds):
            try:
                # Provider indexing can be longer than the worker's shutdown
                # deadline.  Propagate this worker's stop event through the
                # existing content-free cancellation context so ingestion and
                # local provider transports can leave at safe boundaries.
                with runtime_request_scope(self._stop_event):
                    self.run_once()
            except Exception:
                # Scheduler failures are retried; exception text is never logged.
                pass


__all__ = [
    "AUTOMATION_POLL_LIMIT",
    "COACHING_AUTOMATION_METRIC_KEYS",
    "AutomationAccessPolicy",
    "AutomationCatalogRefresher",
    "AutomationConsentError",
    "AutomationGrantError",
    "AutomationGrantNotFoundError",
    "AutomationGrantService",
    "AutomationGrantWorker",
    "AutomationIdFactory",
    "AutomationJobSink",
    "AutomationPollResult",
    "AutomationScheduleResult",
    "AutomationSelectionError",
    "DEFAULT_AUTOMATION_WORKER_POLL_SECONDS",
]
