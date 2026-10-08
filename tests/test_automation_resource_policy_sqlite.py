from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest

from prompt_enhancer.application.automation import AutomationResourcePolicy
from prompt_enhancer.application.jobs import (
    AnalysisJobKind,
    AnalysisJobService,
    AnalysisJobState,
    PowerSourceState,
)
from prompt_enhancer.database import Database
from prompt_enhancer.infrastructure import power as power_module
from prompt_enhancer.infrastructure.power import LocalPowerSourceReader

from test_automation_resource_policy_enforcement import (
    GRANT_ID,
    NOW,
    _database,
    _identity,
    _persist_grant,
)
from test_analysis_job_queue import _lease


class _GetSystemPowerStatus:
    def __init__(self, *, result: int, ac_line_status: int) -> None:
        self.result = result
        self.ac_line_status = ac_line_status
        self.argtypes = None
        self.restype = None

    def __call__(self, status_pointer) -> int:  # type: ignore[no-untyped-def]
        status_pointer._obj.ac_line_status = self.ac_line_status
        return self.result


class _Kernel32:
    def __init__(self, get_status: _GetSystemPowerStatus) -> None:
        self.GetSystemPowerStatus = get_status


@pytest.mark.parametrize(
    ("result", "ac_line_status", "expected"),
    (
        (1, 1, PowerSourceState.EXTERNAL_POWER),
        (1, 0, PowerSourceState.BATTERY),
        (1, 255, PowerSourceState.UNKNOWN),
        (0, 1, PowerSourceState.UNKNOWN),
    ),
)
def test_windows_power_source_matrix(
    monkeypatch: pytest.MonkeyPatch,
    result: int,
    ac_line_status: int,
    expected: PowerSourceState,
) -> None:
    get_status = _GetSystemPowerStatus(
        result=result,
        ac_line_status=ac_line_status,
    )
    monkeypatch.setattr(
        power_module.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: _Kernel32(get_status),
        raising=False,
    )

    assert LocalPowerSourceReader._windows_current() is expected


def _linux_supply(
    root: Path,
    name: str,
    *,
    supply_type: str,
    status: str | None = None,
    online: str | None = None,
) -> None:
    supply = root / name
    supply.mkdir(parents=True)
    (supply / "type").write_text(supply_type, encoding="utf-8")
    if status is not None:
        (supply / "status").write_text(status, encoding="utf-8")
    if online is not None:
        (supply / "online").write_text(online, encoding="utf-8")


@pytest.mark.parametrize(
    ("supplies", "expected"),
    (
        (
            (("AC", "Mains", None, "1"), ("BAT0", "Battery", "Discharging", None)),
            PowerSourceState.EXTERNAL_POWER,
        ),
        ((("BAT0", "Battery", "Charging", None),), PowerSourceState.EXTERNAL_POWER),
        ((("BAT0", "Battery", "Full", None),), PowerSourceState.EXTERNAL_POWER),
        ((("BAT0", "Battery", "Discharging", None),), PowerSourceState.BATTERY),
        ((("BAT0", "Battery", "Unknown", None),), PowerSourceState.UNKNOWN),
        ((), PowerSourceState.UNKNOWN),
    ),
)
def test_linux_power_source_matrix(
    tmp_path: Path,
    supplies: tuple[tuple[str, str, str | None, str | None], ...],
    expected: PowerSourceState,
) -> None:
    root = tmp_path / "power_supply"
    root.mkdir()
    for name, supply_type, status, online in supplies:
        _linux_supply(
            root,
            name,
            supply_type=supply_type,
            status=status,
            online=online,
        )

    assert LocalPowerSourceReader._linux_current(root) is expected


def test_power_reader_returns_unknown_for_unsupported_platform_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = LocalPowerSourceReader()
    monkeypatch.setattr(power_module.sys, "platform", "example-os")
    assert reader.current() is PowerSourceState.UNKNOWN

    monkeypatch.setattr(power_module.sys, "platform", "win32")
    monkeypatch.setattr(
        reader,
        "_windows_current",
        lambda: (_ for _ in ()).throw(OSError("synthetic power read failure")),
    )
    assert reader.current() is PowerSourceState.UNKNOWN

    monkeypatch.setattr(power_module.sys, "platform", "linux")
    monkeypatch.setattr(
        reader,
        "_linux_current",
        lambda _root: (_ for _ in ()).throw(
            OSError("synthetic Linux power read failure")
        ),
    )
    assert reader.current() is PowerSourceState.UNKNOWN


@pytest.mark.parametrize(
    ("variant", "expected_reason"),
    (
        ("missing", "automation_grant_not_found"),
        ("revoked", "automation_grant_inactive"),
        ("expired", "automation_grant_expired"),
        ("unsupported", "automation_resource_policy_unsupported"),
        ("scope", "automation_grant_scope_mismatch"),
        ("kind", "automation_grant_scope_mismatch"),
        ("ordinal", "automation_grant_scope_mismatch"),
    ),
)
def test_claim_reconciles_ineligible_jobs_with_fixed_reason_and_no_starvation(
    tmp_path: Path,
    variant: str,
    expected_reason: str,
) -> None:
    database, session = _database(tmp_path)
    grant_id = GRANT_ID
    grant_metrics = (
        ("different.metric",)
        if variant == "scope"
        else ("prompt.context_sufficiency", "prompt.goal_cue_coverage")
        if variant == "ordinal"
        else ("prompt.context_sufficiency",)
    )
    job_metrics = (
        ("prompt.context_sufficiency", "prompt.goal_cue_coverage")
        if variant == "ordinal"
        else ("prompt.context_sufficiency",)
    )
    if variant != "missing":
        _persist_grant(
            database,
            session,
            policy=(
                AutomationResourcePolicy(max_cpu_workers=2)
                if variant == "unsupported"
                else None
            ),
            created_at=(NOW - timedelta(days=30) if variant == "expired" else NOW),
        )
        if variant == "revoked":
            database.automation_grant_repository().revoke(grant_id, now=NOW)
        if variant in {"scope", "ordinal"}:
            with database._connection() as connection:
                connection.execute(
                    "DELETE FROM automation_grant_metrics WHERE grant_id=?",
                    (grant_id,),
                )
                connection.executemany(
                    """
                    INSERT INTO automation_grant_metrics(
                        grant_id,metric_key,ordinal
                    ) VALUES (?,?,?)
                    """,
                    (
                        (grant_id, metric_key, ordinal)
                        for ordinal, metric_key in enumerate(
                            reversed(grant_metrics)
                            if variant == "ordinal"
                            else grant_metrics
                        )
                    ),
                )
                connection.commit()

    service = AnalysisJobService(
        database.analysis_job_repository(),
        clock=lambda: NOW,
    )
    invalid = service.enqueue(
        _identity(
            session,
            grant_id=grant_id,
            input_fingerprint="1" * 64,
            metric_keys=job_metrics,
            kind=(
                AnalysisJobKind.SYNTHETIC_VALIDATION
                if variant == "kind"
                else AnalysisJobKind.SESSION_QUALITY
            ),
        )
    ).job
    manual = service.enqueue(
        _identity(
            session,
            grant_id=None,
            input_fingerprint="2" * 64,
        )
    ).job

    claimed = Database(database.path).analysis_job_repository().claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )

    assert claimed is not None and claimed.job_id == manual.job_id
    reconciled = database.analysis_job_repository().get(invalid.job_id)
    assert reconciled is not None
    assert reconciled.state is AnalysisJobState.CANCELLED
    assert reconciled.cancel_requested is True
    assert reconciled.attempt_count == 0
    assert reconciled.lease_owner is None
    assert reconciled.last_error_code == expected_reason
    assert reconciled.terminal_reason_code == expected_reason


@pytest.mark.parametrize(
    "policy",
    (
        AutomationResourcePolicy(route="fast"),
        AutomationResourcePolicy(max_cpu_workers=4),
        AutomationResourcePolicy(pause_on_battery=False),
        AutomationResourcePolicy(maximum_session_seconds=14_400),
    ),
)
def test_historical_broad_resource_profiles_remain_exactly_hydratable(
    tmp_path: Path,
    policy: AutomationResourcePolicy,
) -> None:
    database, session = _database(tmp_path)
    _persist_grant(database, session, policy=policy)

    reopened = Database(database.path).automation_grant_repository()
    persisted = reopened.get(GRANT_ID)

    assert persisted is not None
    assert persisted.scope.resource_policy == policy
    assert reopened.list_due(now=NOW, limit=10) == (persisted,)


def _two_same_grant_jobs(database, session):  # type: ignore[no-untyped-def]
    _persist_grant(database, session)
    service = AnalysisJobService(
        database.analysis_job_repository(),
        clock=lambda: NOW,
    )
    return (
        service.enqueue(
            _identity(session, grant_id=GRANT_ID, input_fingerprint="5" * 64)
        ).job,
        service.enqueue(
            _identity(session, grant_id=GRANT_ID, input_fingerprint="6" * 64)
        ).job,
    )


def test_two_independent_sqlite_connections_race_same_grant_to_one_lease(
    tmp_path: Path,
) -> None:
    database, session = _database(tmp_path)
    jobs = _two_same_grant_jobs(database, session)
    first_database = Database(database.path)
    second_database = Database(database.path)
    first_database.initialize()
    second_database.initialize()
    repositories = (
        first_database.analysis_job_repository(),
        second_database.analysis_job_repository(),
    )
    barrier = Barrier(2)

    def claim(index: int):  # type: ignore[no-untyped-def]
        barrier.wait()
        return repositories[index].claim_next(
            owner=str(index + 7) * 64,
            token=str(index + 1) * 64,
            now=NOW,
            lease_duration=timedelta(seconds=30),
            power_source=PowerSourceState.EXTERNAL_POWER,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(claim, (0, 1)))

    leased = tuple(result for result in results if result is not None)
    assert len(leased) == 1
    assert leased[0].job_id in {job.job_id for job in jobs}
    persisted = tuple(
        database.analysis_job_repository().get(job.job_id) for job in jobs
    )
    assert sum(job.state is AnalysisJobState.PREPROCESSING for job in persisted) == 1
    assert sum(job.state is AnalysisJobState.QUEUED for job in persisted) == 1


def test_active_grant_blocks_only_its_sibling_while_other_grant_and_manual_proceed(
    tmp_path: Path,
) -> None:
    database, session = _database(tmp_path)
    first, second = _two_same_grant_jobs(database, session)
    repository = database.analysis_job_repository()
    active = repository.claim_next(
        owner="1" * 64,
        token="2" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert active is not None
    blocked_sibling = second if active.job_id == first.job_id else first

    other_project_id = "c" * 64
    other_session_id = "d" * 64
    with database._connection() as connection:
        installation_id = connection.execute(
            "SELECT installation_id FROM sessions WHERE session_id=?",
            (session["session_id"],),
        ).fetchone()[0]
        timestamp = NOW.isoformat(timespec="microseconds")
        connection.execute(
            """
            INSERT INTO projects(
                project_id,installation_id,provider,created_at
            ) VALUES (?,?,?,?)
            """,
            (other_project_id, installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id,installation_id,project_id,provider,provider_version,
                adapter_version,source_schema_version,started_at,ended_at,
                terminal_state,events_complete,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                other_session_id,
                installation_id,
                other_project_id,
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-schema-v1",
                timestamp,
                timestamp,
                "completed",
                1,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    other_session = {
        "project_id": other_project_id,
        "session_id": other_session_id,
    }
    other_grant_id = "e" * 64
    _persist_grant(
        database,
        other_session,
        grant_id=other_grant_id,
    )
    service = AnalysisJobService(repository, clock=lambda: NOW)
    other_grant_job = service.enqueue(
        _identity(
            other_session,
            grant_id=other_grant_id,
            input_fingerprint="3" * 64,
        )
    ).job
    manual = service.enqueue(
        _identity(
            session,
            grant_id=None,
            input_fingerprint="4" * 64,
        )
    ).job

    admitted = tuple(
        Database(database.path).analysis_job_repository().claim_next(
            owner=str(index + 3) * 64,
            token=str(index + 5) * 64,
            now=NOW,
            lease_duration=timedelta(seconds=30),
            power_source=PowerSourceState.EXTERNAL_POWER,
        )
        for index in range(2)
    )

    assert {job.job_id for job in admitted if job is not None} == {
        other_grant_job.job_id,
        manual.job_id,
    }
    persisted_sibling = repository.get(blocked_sibling.job_id)
    assert persisted_sibling is not None
    assert persisted_sibling.state is AnalysisJobState.QUEUED
    assert persisted_sibling.attempt_count == 0
    assert persisted_sibling.lease_owner is None


@pytest.mark.parametrize("inactive_state", ("backoff", "awaiting", "terminal"))
def test_non_active_same_grant_states_do_not_block_ready_sibling(
    tmp_path: Path,
    inactive_state: str,
) -> None:
    database, session = _database(tmp_path)
    first, second = _two_same_grant_jobs(database, session)
    repository = database.analysis_job_repository()
    claimed = repository.claim_next(
        owner="9" * 64,
        token="8" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    sibling = second if claimed.job_id == first.job_id else first
    if inactive_state == "backoff":
        transitioned = repository.retry_or_fail(
            _lease(claimed),
            now=NOW,
            error_code="synthetic_retry",
            retryable=True,
        )
        assert transitioned.state is AnalysisJobState.QUEUED
        assert transitioned.available_at > NOW
    elif inactive_state == "awaiting":
        transitioned = repository.await_approval(
            _lease(claimed),
            now=NOW,
            reason_code="synthetic_approval",
            progress_completed=0,
            progress_total=1,
        )
        assert transitioned.state is AnalysisJobState.AWAITING_APPROVAL
    else:
        transitioned = repository.finish(
            _lease(claimed),
            now=NOW,
            state=AnalysisJobState.FAILED,
            reason_code="synthetic_terminal_failure",
            progress_completed=0,
            progress_total=1,
        )
        assert transitioned.state is AnalysisJobState.FAILED

    next_claim = Database(database.path).analysis_job_repository().claim_next(
        owner="7" * 64,
        token="6" * 64,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert next_claim is not None and next_claim.job_id == sibling.job_id
