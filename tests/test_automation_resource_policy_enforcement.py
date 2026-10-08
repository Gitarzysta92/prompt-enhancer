from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantService,
    AutomationGrantState,
    AutomationResourcePolicy,
    AutomationRoute,
    AutomationPollResult,
    AutomationScheduleResult,
    AutomationSelectionError,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobService,
    AnalysisJobState,
    PowerSourceState,
)
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer
from pydantic import ValidationError


NOW = datetime(2049, 1, 2, 3, 4, tzinfo=UTC)
GRANT_ID = "a" * 64
PROJECT_ID = "b" * 64


def _scope(
    *,
    policy: AutomationResourcePolicy | None = None,
) -> AutomationGrantScope:
    return AutomationGrantScope(
        provider=Provider.CODEX,
        project_id=PROJECT_ID,
        metric_keys=("prompt.context_sufficiency",),
        resource_policy=policy or AutomationResourcePolicy(),
    )


def _record(scope: AutomationGrantScope) -> AutomationGrantRecord:
    return AutomationGrantRecord(
        grant_id=GRANT_ID,
        revision=1,
        scope=scope,
        state=AutomationGrantState.ACTIVE,
        created_at=NOW,
        renewed_at=NOW,
        expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        next_check_at=NOW,
    )


@dataclass
class _Repository:
    record: AutomationGrantRecord | None = None
    mutations: list[str] = field(default_factory=list)

    def create(self, draft: AutomationGrantDraft) -> AutomationGrantRecord:
        self.mutations.append("create")
        self.record = _record(draft.scope)
        return self.record

    def get(self, grant_id: str) -> AutomationGrantRecord | None:
        return self.record if grant_id == GRANT_ID else None

    def list_due(self, *, now: datetime, limit: int):  # type: ignore[no-untyped-def]
        return (self.record,) if self.record is not None and self.record.is_due(now) else ()

    def list_for_provider(self, provider: Provider, *, active_only: bool):  # type: ignore[no-untyped-def]
        return () if self.record is None else (self.record,)

    def expire_due(self, *, now: datetime) -> int:
        return 0

    def renew(self, grant_id: str, *, now: datetime) -> AutomationGrantRecord:
        self.mutations.append("renew")
        assert self.record is not None
        return self.record

    def revoke(self, grant_id: str, *, now: datetime) -> AutomationGrantRecord:
        self.mutations.append("revoke")
        assert self.record is not None
        return self.record

    def record_check(
        self,
        grant_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        error_code: str | None,
    ) -> AutomationGrantRecord:
        self.mutations.append(f"check:{error_code}")
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
class _Access:
    calls: list[str]
    consent: bool = True

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        self.calls.append("consent")
        return self.consent

    def project_is_indexed(self, provider: Provider, project_id: str) -> bool:
        self.calls.append("project")
        return True


@dataclass
class _Refresher:
    calls: list[str]

    def refresh(self, provider: Provider, *, max_sessions: int) -> None:
        self.calls.append("refresh")


@dataclass
class _Candidates:
    calls: list[str]

    def newest_changed(self, scope: AutomationGrantScope, *, limit: int):  # type: ignore[no-untyped-def]
        self.calls.append("candidates")
        return ()


@dataclass
class _Jobs:
    calls: list[str]

    def schedule(self, grant, candidate):  # type: ignore[no-untyped-def]
        self.calls.append("schedule")
        return AutomationScheduleResult(created=True)

    def cancel_for_grant(
        self,
        grant_id: str,
        *,
        now: datetime,
    ) -> int:
        self.calls.append("cancel:automation_grant_revoked")
        return 0


class _Ids:
    def new_id(self) -> str:
        return GRANT_ID


@dataclass
class _Power:
    states: list[PowerSourceState]
    calls: list[str]

    def current(self) -> PowerSourceState:
        self.calls.append("power")
        return self.states.pop(0)


def _service(
    repository: _Repository,
    calls: list[str],
    *,
    consent: bool = True,
    power: list[PowerSourceState] | None = None,
) -> AutomationGrantService:
    return AutomationGrantService(
        repository,
        _Access(calls, consent=consent),
        _Refresher(calls),
        _Candidates(calls),
        _Jobs(calls),
        _Ids(),
        _Power(power or [PowerSourceState.EXTERNAL_POWER], calls),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize(
    "policy",
    (
        AutomationResourcePolicy(route=AutomationRoute.FAST),
        AutomationResourcePolicy(max_cpu_workers=2),
        AutomationResourcePolicy(pause_on_battery=False),
        AutomationResourcePolicy(maximum_session_seconds=3_600),
    ),
)
def test_create_and_renew_reject_historical_profiles_before_access_or_mutation(
    policy: AutomationResourcePolicy,
) -> None:
    scope = _scope(policy=policy)
    calls: list[str] = []
    repository = _Repository(record=_record(scope))
    service = _service(repository, calls)

    with pytest.raises(AutomationSelectionError) as create_error:
        service.create(scope)
    with pytest.raises(AutomationSelectionError) as renew_error:
        service.renew(GRANT_ID)

    assert create_error.value.code == "automation_resource_policy_unsupported"
    assert renew_error.value.code == "automation_resource_policy_unsupported"
    assert calls == []
    assert repository.mutations == []


def test_unsupported_poll_records_only_fixed_result_before_external_access() -> None:
    scope = _scope(policy=AutomationResourcePolicy(max_cpu_workers=2))
    calls: list[str] = []
    repository = _Repository(record=_record(scope))

    result = _service(repository, calls).poll_due()

    assert calls == []
    assert repository.mutations == [
        "check:automation_resource_policy_unsupported"
    ]
    assert result.grants_checked == 1
    assert result.grants_policy_unsupported == 1
    assert result.failures == 1
    assert result.maximum_session_runtime_deadline_enforced is False


@pytest.mark.parametrize(
    "state",
    (PowerSourceState.BATTERY, PowerSourceState.UNKNOWN),
)
def test_battery_and_unknown_pause_before_provider_candidate_or_job_access(
    state: PowerSourceState,
) -> None:
    calls: list[str] = []
    repository = _Repository(record=_record(_scope()))

    result = _service(repository, calls, power=[state]).poll_due()

    assert calls == ["consent", "power"]
    assert repository.mutations == ["check:automation_paused_for_power_source"]
    assert result.grants_power_paused == 1
    assert result.power_battery_observations == int(state is PowerSourceState.BATTERY)
    assert result.power_unknown_observations == int(state is PowerSourceState.UNKNOWN)


def test_consent_revocation_precedes_and_skips_power_observation() -> None:
    calls: list[str] = []
    repository = _Repository(record=_record(_scope()))

    result = _service(repository, calls, consent=False).poll_due()

    assert calls == ["consent", "cancel:automation_grant_revoked"]
    assert repository.mutations == ["revoke"]
    assert result.grants_revoked == 1
    assert result.power_external_observations == 0
    assert result.power_battery_observations == 0
    assert result.power_unknown_observations == 0


@dataclass
class _ManyRepository:
    records: dict[str, AutomationGrantRecord]
    mutations: list[str] = field(default_factory=list)

    def get(self, grant_id: str) -> AutomationGrantRecord | None:
        return self.records.get(grant_id)

    def list_due(self, *, now: datetime, limit: int):  # type: ignore[no-untyped-def]
        return tuple(
            record for record in self.records.values() if record.is_due(now)
        )[:limit]

    def list_for_provider(self, provider: Provider, *, active_only: bool):  # type: ignore[no-untyped-def]
        return tuple(self.records.values())

    def expire_due(self, *, now: datetime) -> int:
        return 0

    def record_check(
        self,
        grant_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        error_code: str | None,
    ) -> AutomationGrantRecord:
        self.mutations.append(f"{grant_id}:{error_code}")
        current = self.records[grant_id]
        updated = current.model_copy(
            update={
                "last_checked_at": now,
                "next_check_at": next_check_at,
                "last_error_code": error_code,
            }
        )
        self.records[grant_id] = updated
        return updated


def test_poll_samples_power_independently_for_each_reviewed_due_grant() -> None:
    second_id = "c" * 64
    first = _record(_scope())
    second = AutomationGrantRecord(
        grant_id=second_id,
        revision=1,
        scope=_scope(),
        state=AutomationGrantState.ACTIVE,
        created_at=NOW,
        renewed_at=NOW,
        expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        next_check_at=NOW,
    )
    calls: list[str] = []
    repository = _ManyRepository({GRANT_ID: first, second_id: second})
    service = AutomationGrantService(
        repository,  # type: ignore[arg-type]
        _Access(calls),
        _Refresher(calls),
        _Candidates(calls),
        _Jobs(calls),
        _Ids(),
        _Power(
            [PowerSourceState.BATTERY, PowerSourceState.EXTERNAL_POWER],
            calls,
        ),
        clock=lambda: NOW,
    )

    result = service.poll_due()

    assert calls == [
        "consent", "power",
        "consent", "power", "refresh", "candidates",
    ]
    assert result.grants_checked == 2
    assert result.grants_power_paused == 1
    assert result.power_battery_observations == 1
    assert result.power_external_observations == 1
    assert result.power_unknown_observations == 0


class _ExceptionalPower:
    def current(self) -> PowerSourceState:
        raise RuntimeError("SYNTHETIC-PRIVATE-POWER-CANARY")


class _InvalidPower:
    def current(self):  # type: ignore[no-untyped-def]
        return "external_power"


@pytest.mark.parametrize("reader", (_ExceptionalPower(), _InvalidPower()))
def test_invalid_or_failed_power_reader_fails_closed_as_unknown(reader) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    repository = _Repository(record=_record(_scope()))
    service = AutomationGrantService(
        repository,
        _Access(calls),
        _Refresher(calls),
        _Candidates(calls),
        _Jobs(calls),
        _Ids(),
        reader,
        clock=lambda: NOW,
    )

    result = service.poll_due()

    assert calls == ["consent"]
    assert result.grants_power_paused == 1
    assert result.power_unknown_observations == 1
    assert repository.record is not None
    assert repository.record.last_error_code == "automation_paused_for_power_source"


@pytest.mark.parametrize(
    "update",
    (
        {"grants_checked": 2},
        {"grants_power_paused": 1},
        {"grants_policy_unsupported": 1},
        {"jobs_created": 2},
        {"jobs_superseded": 2},
        {"maximum_session_runtime_deadline_enforced": True},
        {"session_quality_result_publication_deadline_enforced": False},
        {"blocking_execution_preemption_enforced": True},
    ),
)
def test_poll_receipt_rejects_serialized_cross_field_tampering(
    update: dict[str, object],
) -> None:
    valid = AutomationPollResult(
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
        jobs_superseded=0,
        failures=0,
        maximum_session_runtime_deadline_enforced=False,
        session_quality_result_publication_deadline_enforced=True,
        blocking_execution_preemption_enforced=False,
    )
    tampered = valid.model_copy(update=update)

    with pytest.raises(ValidationError):
        AutomationPollResult.model_validate(tampered.model_dump())


def _database(tmp_path) -> tuple[Database, dict[str, object]]:  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "automation-resource-policy.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    return database, database.list_sessions(limit=1)[0]


def _identity(
    session: dict[str, object],
    *,
    grant_id: str | None,
    input_fingerprint: str,
    metric_keys: tuple[str, ...] = ("prompt.context_sufficiency",),
    kind: AnalysisJobKind = AnalysisJobKind.SESSION_QUALITY,
) -> AnalysisJobIdentity:
    return AnalysisJobIdentity(
        kind=kind,
        provider=Provider.SYNTHETIC,
        project_id=str(session["project_id"]),
        session_id=str(session["session_id"]),
        input_fingerprint=input_fingerprint,
        provenance_fingerprint="d" * 64,
        metric_keys=metric_keys,
        estimator_plan_version="synthetic-plan-v1",
        redactor_version="synthetic-redactor-v1",
        provider_schema_version="synthetic-schema-v1",
        automation_grant_id=grant_id,
    )


def _persist_grant(
    database: Database,
    session: dict[str, object],
    *,
    grant_id: str = GRANT_ID,
    policy: AutomationResourcePolicy | None = None,
    created_at: datetime = NOW,
) -> None:
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id=grant_id,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=str(session["project_id"]),
                metric_keys=("prompt.context_sufficiency",),
                resource_policy=policy or AutomationResourcePolicy(),
            ),
            created_at=created_at,
            expires_at=created_at + AUTOMATION_GRANT_LIFETIME,
        )
    )


@pytest.mark.parametrize(
    "power_source",
    (PowerSourceState.BATTERY, PowerSourceState.UNKNOWN),
)
def test_paused_claim_leaves_automation_job_unchanged_and_claims_manual_job(
    tmp_path,
    power_source: PowerSourceState,
) -> None:
    database, session = _database(tmp_path)
    _persist_grant(database, session)
    service = AnalysisJobService(
        database.analysis_job_repository(), clock=lambda: NOW
    )
    automation = service.enqueue(
        _identity(
            session,
            grant_id=GRANT_ID,
            input_fingerprint="1" * 64,
        )
    ).job
    manual = service.enqueue(
        _identity(
            session,
            grant_id=None,
            input_fingerprint="2" * 64,
        )
    ).job
    repository = database.analysis_job_repository()

    claimed = repository.claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=power_source,
    )

    assert claimed is not None and claimed.job_id == manual.job_id
    assert repository.get(automation.job_id) == automation


def test_live_reviewed_grant_allows_only_one_same_grant_active_job(tmp_path) -> None:
    database, session = _database(tmp_path)
    _persist_grant(database, session)
    service = AnalysisJobService(
        database.analysis_job_repository(), clock=lambda: NOW
    )
    first = service.enqueue(
        _identity(session, grant_id=GRANT_ID, input_fingerprint="1" * 64)
    ).job
    second = service.enqueue(
        _identity(session, grant_id=GRANT_ID, input_fingerprint="2" * 64)
    ).job
    repository = database.analysis_job_repository()

    claimed = repository.claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    blocked = Database(database.path).analysis_job_repository().claim_next(
        owner="5" * 64,
        token="6" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )

    assert claimed is not None and claimed.job_id in {first.job_id, second.job_id}
    assert blocked is None
    unclaimed = second if claimed.job_id == first.job_id else first
    persisted = repository.get(unclaimed.job_id)
    assert persisted is not None
    assert persisted.state is AnalysisJobState.QUEUED
    assert persisted.attempt_count == 0
    assert persisted.lease_owner is None
