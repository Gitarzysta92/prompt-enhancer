from __future__ import annotations

from datetime import UTC, datetime

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis import (
    TASK_METRIC_DEFINITIONS,
    TaskAnalysisService,
)
from prompt_enhancer.application.discovery import (
    AcceptCandidate,
    DiscoveryPersistenceService,
    TaskCategory,
    TaskDiscoveryEngine,
    TaskReviewService,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    CandidateDecisionStatus,
    MetricValueState,
)
from prompt_enhancer.database import SCHEMA_VERSION, Database
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2026, 5, 6, 9, 0, tzinfo=UTC)


def test_reviewed_synthetic_task_is_analyzed_and_retry_is_immutable(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    identifiers = LocalArtifactIdFactory(pseudonymizer)
    IngestionService(database, pseudonymizer).ingest(SyntheticAdapter())
    sessions = tuple(
        database.get_session(item["session_id"])
        for item in database.list_sessions()
    )
    assert all(session is not None for session in sessions)
    discovery = DiscoveryPersistenceService(
        TaskDiscoveryEngine(identifiers),
        database.task_repository(),
        identifiers,
        clock=lambda: NOW,
    ).discover_and_persist(sessions)
    candidate = discovery.batch.candidates[0]
    review = TaskReviewService(
        database.task_repository(), identifiers, clock=lambda: NOW
    ).apply(
        AcceptCandidate(
            candidate_id=candidate.candidate_id,
            expected_discovery_version=candidate.discovery_version,
            task_category=TaskCategory.BUG_FIX,
        ),
        idempotency_key="example-analysis-review-1",
    )
    task_id, revision = review.output_revisions[0]
    service = TaskAnalysisService(
        database.task_repository(),
        database.analysis_run_repository(),
        database,
        identifiers,
        schema_version=SCHEMA_VERSION,
        clock=lambda: NOW,
    )

    first = service.run(
        task_id,
        revision,
        idempotency_key="example-task-analysis-1",
    )
    retry = service.run(
        task_id,
        revision,
        idempotency_key="example-task-analysis-1",
    )

    assert first.applied is True
    assert retry.applied is False
    assert first.run_id == retry.run_id
    assert first.status is AnalysisRunStatus.COMPLETED
    assert first.result_count == retry.result_count == len(TASK_METRIC_DEFINITIONS)
    results = database.analysis_run_repository().get_results(first.run_id)
    by_key = {item.observation.key: item for item in results}
    assert by_key["task.workflow.session_count"].observation.numeric_value == 2
    assert by_key["task.usage.total_tokens"].observation.numeric_value == 1650
    assert by_key["task.usage.total_tokens"].value_state is MetricValueState.KNOWN
    assert by_key["task.verification.pass_rate"].observation.numeric_value == 1
    assert len(
        database.task_repository().list_candidates(
            status=CandidateDecisionStatus.DECIDED
        )
    ) == 1
