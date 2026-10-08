from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationConsentError,
    AutomationGrantDraft,
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantService,
    AutomationGrantState,
    AutomationPollResult,
    AutomationScheduleResult,
    AutomationSessionCandidate,
)
from prompt_enhancer.application.jobs import PowerSourceState
from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCooperativeStop,
    runtime_request_scope,
)
from prompt_enhancer.domain import DataTier, Provider


NOW = datetime(2044, 1, 2, 3, 4, tzinfo=UTC)
GRANT = "a" * 64
PROJECT = "b" * 64
SESSION = "c" * 64
FINGERPRINT = "d" * 64
PROVENANCE = "e" * 64


def _scope() -> AutomationGrantScope:
    return AutomationGrantScope(
        provider=Provider.CODEX,
        project_id=PROJECT,
        metric_keys=("prompt.context_sufficiency",),
    )


def _record(scope: AutomationGrantScope | None = None) -> AutomationGrantRecord:
    return AutomationGrantRecord(
        grant_id=GRANT,
        revision=1,
        scope=scope or _scope(),
        state=AutomationGrantState.ACTIVE,
        created_at=NOW,
        renewed_at=NOW,
        expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        next_check_at=NOW,
    )


@dataclass
class Repository:
    record: AutomationGrantRecord | None = None

    def create(self, draft: AutomationGrantDraft) -> AutomationGrantRecord:
        self.record = _record(draft.scope)
        return self.record

    def get(self, grant_id: str) -> AutomationGrantRecord | None:
        return self.record if grant_id == GRANT else None

    def list_due(self, *, now: datetime, limit: int):
        if self.record is not None and self.record.is_due(now):
            return (self.record,)
        return ()

    def list_for_provider(self, provider: Provider, *, active_only: bool):
        if self.record is not None and self.record.scope.provider is provider:
            return (self.record,)
        return ()

    def expire_due(self, *, now: datetime) -> int:
        if (
            self.record is not None
            and self.record.state is AutomationGrantState.ACTIVE
            and now >= self.record.expires_at
        ):
            self.record = self.record.model_copy(
                update={"state": AutomationGrantState.EXPIRED}
            )
            return 1
        return 0

    def renew(self, grant_id: str, *, now: datetime):
        assert self.record is not None
        self.record = self.record.model_copy(
            update={
                "revision": self.record.revision + 1,
                "renewed_at": now,
                "expires_at": now + AUTOMATION_GRANT_LIFETIME,
                "state": AutomationGrantState.ACTIVE,
                "revoked_at": None,
            }
        )
        return self.record

    def revoke(self, grant_id: str, *, now: datetime):
        assert self.record is not None
        self.record = self.record.model_copy(
            update={"state": AutomationGrantState.REVOKED, "revoked_at": now}
        )
        return self.record

    def record_check(
        self,
        grant_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        error_code: str | None,
    ):
        assert self.record is not None
        self.record = self.record.model_copy(
            update={
                "last_checked_at": now,
                "next_check_at": next_check_at,
                "last_error_code": error_code,
            }
        )
        return self.record


@dataclass
class Access:
    consent: bool = True
    indexed: bool = True

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        return self.consent and tier is DataTier.REDACTED_CONTENT

    def project_is_indexed(self, provider: Provider, project_id: str) -> bool:
        return self.indexed and project_id == PROJECT


@dataclass
class Candidates:
    calls: int = 0

    def newest_changed(self, scope: AutomationGrantScope, *, limit: int):
        self.calls += 1
        return (
            AutomationSessionCandidate(
                provider=scope.provider,
                project_id=scope.project_id,
                session_id=SESSION,
                input_fingerprint=FINGERPRINT,
                provenance_fingerprint=PROVENANCE,
                provider_schema_version="schema-1",
                updated_at=NOW,
            ),
        )


@dataclass
class Refresher:
    calls: int = 0

    def refresh(self, provider: Provider, *, max_sessions: int) -> None:
        self.calls += 1


@dataclass
class Jobs:
    created: bool = True
    scheduled: int = 0
    cancelled: list[str] = field(default_factory=list)

    def schedule(self, grant, candidate):
        self.scheduled += 1
        return AutomationScheduleResult(created=self.created, superseded=1)

    def cancel_for_grant(self, grant_id: str, *, now: datetime) -> int:
        self.cancelled.append(grant_id)
        return 1


class Ids:
    def new_id(self) -> str:
        return GRANT


class ExternalPower:
    def current(self) -> PowerSourceState:
        return PowerSourceState.EXTERNAL_POWER


def _service(repository, access, candidates, jobs, refresher=None):
    return AutomationGrantService(
        repository,
        access,
        refresher or Refresher(),
        candidates,
        jobs,
        Ids(),
        ExternalPower(),
        clock=lambda: NOW,
    )


def test_create_requires_consent_and_indexed_project() -> None:
    repository = Repository()
    access = Access(consent=False)
    service = _service(repository, access, Candidates(), Jobs())

    with pytest.raises(AutomationConsentError):
        service.create(_scope())
    assert repository.record is None


def test_poll_schedules_changed_candidates_and_advances_interval() -> None:
    repository = Repository(record=_record())
    candidates = Candidates()
    jobs = Jobs()
    service = _service(repository, Access(), candidates, jobs)

    result = service.poll_due()

    assert result == AutomationPollResult(
        grants_checked=1,
        grants_revoked=0,
        grants_power_paused=0,
        grants_policy_unsupported=0,
        power_external_observations=1,
        power_battery_observations=0,
        power_unknown_observations=0,
        candidates_seen=1,
        jobs_created=1,
        jobs_reused=0,
        jobs_superseded=1,
        failures=0,
        maximum_session_runtime_deadline_enforced=False,
    )
    assert repository.record is not None
    assert repository.record.next_check_at == NOW + timedelta(minutes=15)


def test_poll_propagates_runtime_shutdown_without_recording_provider_failure() -> None:
    repository = Repository(record=_record())

    class CancelledRefresher:
        def refresh(self, provider: Provider, *, max_sessions: int) -> None:
            del provider, max_sessions
            raise RuntimeCooperativeStop("synthetic_automation_shutdown")

    service = _service(
        repository,
        Access(),
        Candidates(),
        Jobs(),
        refresher=CancelledRefresher(),
    )
    cancellation = Event()

    with runtime_request_scope(cancellation):
        with pytest.raises(
            RuntimeCooperativeStop,
            match="^synthetic_automation_shutdown$",
        ):
            service.poll_due()

    assert repository.record == _record()


def test_consent_revocation_cancels_jobs_without_reading_candidates() -> None:
    repository = Repository(record=_record())
    candidates = Candidates()
    jobs = Jobs()
    service = _service(repository, Access(consent=False), candidates, jobs)

    result = service.poll_due()

    assert result.grants_revoked == 1
    assert candidates.calls == 0
    assert jobs.cancelled == [GRANT]
    assert repository.record is not None
    assert repository.record.state is AutomationGrantState.REVOKED
