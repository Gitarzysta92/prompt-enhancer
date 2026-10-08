from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.analysis import (
    TaskAnalysisConflictError,
    TaskAnalysisService,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    TaskRevisionRecord,
)
from prompt_enhancer.database import SCHEMA_VERSION, Database
from prompt_enhancer.domain import (
    EventKind,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    UsageRecord,
    UsageCounterKind,
)
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)


def test_safe_evidence_drift_changes_fingerprint_and_conflicts_on_same_retry_key(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    identifiers = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    initial_session = SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="0" * 64,
        project_id="1" * 64,
        session_id="2" * 64,
        provider_version="synthetic-1",
        adapter_version="0.1.0",
        source_schema_version="synthetic-1",
        started_at=NOW,
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
    )
    initial_event = SafeEvent(
        session_id=initial_session.session_id,
        event_id="3" * 64,
        kind=EventKind.USAGE,
        sequence=0,
        occurred_at=NOW + timedelta(seconds=30),
        usage=UsageRecord(
            input_tokens=100,
            provider_reported=True,
            counter_kind=UsageCounterKind.DELTA,
        ),
    )
    database.persist_session(initial_session, (initial_event,))
    revision = TaskRevisionRecord(
        task_id="4" * 64,
        revision=1,
        project_id=initial_session.project_id,
        task_type="bug_fix",
        lifecycle_state="accepted",
        session_ids=(initial_session.session_id,),
        input_fingerprint="5" * 64,
        created_at=NOW,
    )
    database.task_repository().append_revision(revision)
    service = TaskAnalysisService(
        database.task_repository(),
        database.analysis_run_repository(),
        database,
        identifiers,
        schema_version=SCHEMA_VERSION,
        clock=lambda: NOW + timedelta(minutes=2),
    )

    first = service.run(
        revision.task_id,
        revision.revision,
        idempotency_key="example-evidence-snapshot-1",
    )
    first_record = database.analysis_run_repository().get(first.run_id)
    first_results = database.analysis_run_repository().get_results(first.run_id)
    first_by_key = {item.observation.key: item for item in first_results}
    assert first_record is not None
    assert first_record.status is AnalysisRunStatus.COMPLETED
    assert first_by_key["task.usage.total_tokens"].value_state is MetricValueState.UNKNOWN

    updated_session = initial_session.model_copy(
        update={
            "ended_at": NOW + timedelta(minutes=1),
            "terminal_state": SessionState.COMPLETED,
            "events_complete": True,
        }
    )
    updated_event = initial_event.model_copy(
        update={
            "usage": UsageRecord(
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                provider_reported=True,
                counter_kind=UsageCounterKind.DELTA,
            )
        }
    )
    persisted = database.persist_session(updated_session, (updated_event,))
    assert persisted.session_updated == 1
    assert persisted.events_updated == 1
    assert database.task_repository().get_revision(
        revision.task_id, revision.revision
    ) == revision

    with pytest.raises(TaskAnalysisConflictError, match="stored provenance"):
        service.run(
            revision.task_id,
            revision.revision,
            idempotency_key="example-evidence-snapshot-1",
        )

    assert database.analysis_run_repository().get(first.run_id) == first_record
    assert database.analysis_run_repository().get_results(first.run_id) == first_results

    second = service.run(
        revision.task_id,
        revision.revision,
        idempotency_key="example-evidence-snapshot-2",
    )
    second_record = database.analysis_run_repository().get(second.run_id)
    assert second_record is not None
    assert second_record.draft.input_fingerprint != first_record.draft.input_fingerprint
    second_by_key = {
        item.observation.key: item
        for item in database.analysis_run_repository().get_results(second.run_id)
    }
    assert second_by_key["task.usage.total_tokens"].value_state is MetricValueState.KNOWN
    assert second_by_key["task.usage.total_tokens"].observation.numeric_value == 120
    assert second_by_key["task.efficiency.cycle_time_ms"].observation.numeric_value == 60_000
