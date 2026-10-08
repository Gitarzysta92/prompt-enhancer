from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3

import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.deterministic import (
    DEFAULT_METRIC_PACK,
    EVENT_COUNT_DEFINITION,
    METRIC_ENGINE_VERSION,
    TOTAL_TOKENS_DEFINITION,
)
from prompt_enhancer.application.discovery import SignalDirection
from prompt_enhancer.application.persistence import (
    AnalysisResultRecord,
    AnalysisRunDraft,
    AnalysisRunStatus,
    CandidateDecisionStatus,
    CandidateSignalRecord,
    DecisionAction,
    DecisionRevisionLink,
    DecisionRevisionRole,
    MetricValueState,
    TaskCandidateRecord,
    TaskDecisionRecord,
    TaskRevisionRecord,
)
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseInvariantError,
    _MIGRATION_1,
)
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    SessionState,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


EXAMPLE_TIME = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)


def _database_with_two_project_sessions(tmp_path) -> tuple[Database, tuple[str, str]]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    first_id = database.list_sessions(limit=1)[0]["session_id"]
    first = database.get_session(first_id)
    assert first is not None
    second = first.model_copy(
        update={
            "session_id": "f" * 64,
            "started_at": EXAMPLE_TIME + timedelta(hours=1),
            "ended_at": EXAMPLE_TIME + timedelta(hours=2),
            "terminal_state": SessionState.COMPLETED,
            "events_complete": True,
        }
    )
    database.persist_session(second, ())
    return database, (first.session_id, second.session_id)


def _candidate(
    database: Database,
    session_ids: tuple[str, str],
    identity: str,
    *,
    with_unknown_signal: bool = False,
) -> TaskCandidateRecord:
    session = database.get_session(session_ids[0])
    assert session is not None
    signals = ()
    if with_unknown_signal:
        signals = (
            CandidateSignalRecord(
                key="discovery.terminal_continuity",
                version=1,
                session_ids=session_ids,
                direction=SignalDirection.UNKNOWN,
                confidence=None,
                weight=1.0,
                evidence_code="terminal_state_unknown",
                observed_count=0,
                eligible_count=1,
                coverage=0.0,
            ),
        )
    return TaskCandidateRecord(
        candidate_id=identity * 64,
        provider=session.provider,
        installation_id=session.installation_id,
        project_id=session.project_id,
        session_ids=session_ids,
        signals=signals,
        confidence=None,
        observed_count=0,
        eligible_count=1,
        coverage=0.0,
        discovery_version="metadata-discovery-1",
        input_fingerprint="0" * 64,
        created_at=EXAMPLE_TIME,
    )


def _revision(
    database: Database,
    session_ids: tuple[str, str],
    identity: str,
    *,
    fingerprint: str = "1",
) -> TaskRevisionRecord:
    session = database.get_session(session_ids[0])
    assert session is not None
    return TaskRevisionRecord(
        task_id=identity * 64,
        revision=1,
        project_id=session.project_id,
        task_type="bug_fix",
        lifecycle_state="confirmed",
        session_ids=session_ids,
        input_fingerprint=fingerprint * 64,
        created_at=EXAMPLE_TIME + timedelta(minutes=1),
    )


def _accept(
    candidate_id: str,
    revision: TaskRevisionRecord,
    identity: str,
) -> TaskDecisionRecord:
    return TaskDecisionRecord(
        decision_id=identity * 64,
        action=DecisionAction.ACCEPT,
        candidate_ids=(candidate_id,),
        revision_links=(
            DecisionRevisionLink(
                task_id=revision.task_id,
                revision=revision.revision,
                role=DecisionRevisionRole.OUTPUT,
            ),
        ),
        decision_schema_version="review-1",
        decided_at=EXAMPLE_TIME + timedelta(minutes=2),
    )


def test_current_task_context_for_session_excludes_historical_revisions(
    tmp_path,
) -> None:
    database, session_ids = _database_with_two_project_sessions(tmp_path)
    repository = database.task_repository()
    first = _revision(database, session_ids, "7")
    repository.append_revision(first)

    assert repository.list_current_revisions_for_session(session_ids[0]) == (first,)

    second = first.model_copy(
        update={
            "revision": 2,
            "session_ids": (session_ids[1],),
            "input_fingerprint": "8" * 64,
            "created_at": first.created_at + timedelta(minutes=1),
        }
    )
    repository.append_revision(second)

    assert repository.list_current_revisions_for_session(session_ids[0]) == ()
    assert repository.list_current_revisions_for_session(session_ids[1]) == (second,)


def test_v1_database_upgrades_in_order_without_changing_v1_checksum(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    checksum = hashlib.sha256(_MIGRATION_1.encode("utf-8")).hexdigest()
    with sqlite3.connect(path) as connection:
        connection.executescript(_MIGRATION_1)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (1, ?, ?)",
            (checksum, EXAMPLE_TIME.isoformat()),
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        task_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_revisions'"
        ).fetchone()
    assert user_version == SCHEMA_VERSION == 61
    assert [row[0] for row in versions] == list(range(1, SCHEMA_VERSION + 1))
    assert versions[0][1] == checksum
    assert task_table is not None


def test_candidate_and_unknown_signal_round_trip_and_derived_status(tmp_path) -> None:
    database, session_ids = _database_with_two_project_sessions(tmp_path)
    repository = database.task_repository()
    candidate = _candidate(database, session_ids, "2", with_unknown_signal=True)

    repository.add_candidate(candidate)

    assert repository.get_candidate(candidate.candidate_id) == candidate
    pending = repository.list_candidates(status=CandidateDecisionStatus.UNDECIDED)
    assert len(pending) == 1
    assert pending[0].candidate == candidate
    assert pending[0].decision_id is None
    assert pending[0].candidate.signals[0].confidence is None
    assert pending[0].candidate.signals[0].direction is SignalDirection.UNKNOWN


def test_atomic_accept_is_versioned_idempotent_and_owns_candidate(tmp_path) -> None:
    database, session_ids = _database_with_two_project_sessions(tmp_path)
    repository = database.task_repository()
    candidate = _candidate(database, session_ids, "2")
    revision = _revision(database, session_ids, "a")
    decision = _accept(candidate.candidate_id, revision, "3")
    repository.add_candidate(candidate)

    assert repository.apply_review_decision(
        decision,
        (revision,),
        expected_discovery_version=candidate.discovery_version,
    ) is True
    retry = decision.model_copy(
        update={"decided_at": decision.decided_at + timedelta(minutes=5)}
    )
    retry_revision = revision.model_copy(
        update={"created_at": revision.created_at + timedelta(minutes=5)}
    )
    assert repository.apply_review_decision(
        retry,
        (retry_revision,),
        expected_discovery_version=candidate.discovery_version,
    ) is False
    conflict_revision = revision.model_copy(update={"input_fingerprint": "4" * 64})
    with pytest.raises(DatabaseInvariantError, match="conflicts"):
        repository.apply_review_decision(
            retry,
            (conflict_revision,),
            expected_discovery_version=candidate.discovery_version,
        )

    decided = repository.list_candidates(status=CandidateDecisionStatus.DECIDED)
    assert len(decided) == 1
    assert decided[0].decision_id == decision.decision_id
    assert decided[0].decision_action is DecisionAction.ACCEPT
    assert repository.list_task_revisions() == (revision,)

    losing_revision = _revision(database, session_ids, "b", fingerprint="5")
    losing_decision = _accept(candidate.candidate_id, losing_revision, "4")
    with pytest.raises(DatabaseInvariantError, match="already has a decision"):
        repository.apply_review_decision(
            losing_decision,
            (losing_revision,),
            expected_discovery_version=candidate.discovery_version,
        )
    assert repository.get_revision(losing_revision.task_id, 1) is None


def test_atomic_review_supports_reject_merge_and_split_shapes(tmp_path) -> None:
    database, session_ids = _database_with_two_project_sessions(tmp_path)
    repository = database.task_repository()
    candidates = {
        identity: _candidate(database, session_ids, identity)
        for identity in ("2", "3", "4", "5", "6")
    }
    for candidate in candidates.values():
        repository.add_candidate(candidate)

    rejected = TaskDecisionRecord(
        decision_id="7" * 64,
        action=DecisionAction.REJECT,
        candidate_ids=(candidates["2"].candidate_id,),
        revision_links=(),
        decision_schema_version="review-1",
        decision_code="wrong_grouping",
        decided_at=EXAMPLE_TIME + timedelta(minutes=2),
    )
    assert repository.apply_review_decision(
        rejected,
        (),
        expected_discovery_version="metadata-discovery-1",
    ) is True

    merged_revision = _revision(database, session_ids, "a", fingerprint="a")
    merged = TaskDecisionRecord(
        decision_id="8" * 64,
        action=DecisionAction.MERGE,
        candidate_ids=(candidates["3"].candidate_id, candidates["4"].candidate_id),
        revision_links=(
            DecisionRevisionLink(
                task_id=merged_revision.task_id,
                revision=1,
                role=DecisionRevisionRole.OUTPUT,
            ),
        ),
        decision_schema_version="review-1",
        decided_at=EXAMPLE_TIME + timedelta(minutes=2),
    )
    assert repository.apply_review_decision(
        merged,
        (merged_revision,),
        expected_discovery_version="metadata-discovery-1",
    ) is True

    split_revisions = (
        _revision(database, session_ids, "b", fingerprint="b"),
        _revision(database, session_ids, "c", fingerprint="c"),
    )
    split = TaskDecisionRecord(
        decision_id="9" * 64,
        action=DecisionAction.SPLIT,
        candidate_ids=(candidates["5"].candidate_id,),
        revision_links=tuple(
            DecisionRevisionLink(
                task_id=revision.task_id,
                revision=1,
                role=DecisionRevisionRole.OUTPUT,
            )
            for revision in split_revisions
        ),
        decision_schema_version="review-1",
        decided_at=EXAMPLE_TIME + timedelta(minutes=2),
    )
    assert repository.apply_review_decision(
        split,
        split_revisions,
        expected_discovery_version="metadata-discovery-1",
    ) is True

    assert len(repository.list_candidates(status=CandidateDecisionStatus.DECIDED)) == 4
    assert len(repository.list_candidates(status=CandidateDecisionStatus.UNDECIDED)) == 1
    assert len(repository.list_task_revisions(limit=2, offset=0)) == 2
    assert len(repository.list_task_revisions(limit=2, offset=2)) == 1


def test_competing_candidate_decisions_serialize_without_orphan_revision(tmp_path) -> None:
    database, session_ids = _database_with_two_project_sessions(tmp_path)
    repository = database.task_repository()
    candidate = _candidate(database, session_ids, "2")
    repository.add_candidate(candidate)
    revisions = (
        _revision(database, session_ids, "a", fingerprint="a"),
        _revision(database, session_ids, "b", fingerprint="b"),
    )
    decisions = (
        _accept(candidate.candidate_id, revisions[0], "3"),
        _accept(candidate.candidate_id, revisions[1], "4"),
    )

    def apply(index: int) -> object:
        try:
            return repository.apply_review_decision(
                decisions[index],
                (revisions[index],),
                expected_discovery_version=candidate.discovery_version,
            )
        except DatabaseInvariantError as error:
            return type(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(apply, (0, 1)))

    assert outcomes.count(True) == 1
    assert outcomes.count(DatabaseInvariantError) == 1
    assert len(repository.list_task_revisions()) == 1


def test_analysis_results_are_immutable_and_candidate_privacy_delete_cascades(
    tmp_path,
) -> None:
    database, session_ids = _database_with_two_project_sessions(tmp_path)
    tasks = database.task_repository()
    analyses = database.analysis_run_repository()
    candidate = _candidate(database, session_ids, "2")
    revision = _revision(database, session_ids, "a")
    decision = _accept(candidate.candidate_id, revision, "3")
    tasks.add_candidate(candidate)
    tasks.apply_review_decision(
        decision,
        (revision,),
        expected_discovery_version=candidate.discovery_version,
    )
    event_id = database.get_session_events(session_ids[0])[0].event_id
    draft = AnalysisRunDraft(
        run_id="4" * 64,
        task_id=revision.task_id,
        task_revision=1,
        metric_pack_key="core",
        metric_pack_version=DEFAULT_METRIC_PACK.version,
        data_tier=DataTier.METADATA,
        input_fingerprint="5" * 64,
        metric_engine_version=METRIC_ENGINE_VERSION,
        redactor_version="not-applicable",
        schema_version=SCHEMA_VERSION,
        started_at=EXAMPLE_TIME + timedelta(minutes=3),
    )
    known = AnalysisResultRecord(
        observation=MetricObservation(
            key="workflow.event_count",
            version=EVENT_COUNT_DEFINITION.version,
            numeric_value=1,
            unit="count",
            source=MetricSource.DETERMINISTIC,
            observed_count=1,
            eligible_count=1,
            coverage=1.0,
        ),
        value_state=MetricValueState.KNOWN,
        calculator_version=METRIC_ENGINE_VERSION,
        evidence_event_ids=(event_id,),
        computed_at=EXAMPLE_TIME + timedelta(minutes=4),
    )
    unknown = AnalysisResultRecord(
        observation=MetricObservation(
            key="usage.total_tokens",
            version=TOTAL_TOKENS_DEFINITION.version,
            numeric_value=None,
            unit="tokens",
            source=MetricSource.DETERMINISTIC,
            observed_count=0,
            eligible_count=1,
            coverage=0.0,
        ),
        value_state=MetricValueState.UNKNOWN,
        calculator_version=METRIC_ENGINE_VERSION,
        computed_at=EXAMPLE_TIME + timedelta(minutes=4),
    )
    analyses.begin(draft)
    analyses.complete(
        draft.run_id,
        (known, unknown),
        finished_at=EXAMPLE_TIME + timedelta(minutes=5),
    )

    stored = analyses.get(draft.run_id)
    assert stored is not None and stored.status is AnalysisRunStatus.COMPLETED
    assert analyses.get_results(draft.run_id) == (unknown, known)
    assert analyses.list_analysis_runs(task_id=revision.task_id) == (stored,)
    with pytest.raises(DatabaseInvariantError, match="terminal"):
        analyses.complete(
            draft.run_id,
            (),
            finished_at=EXAMPLE_TIME + timedelta(minutes=6),
        )
    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """
                UPDATE analysis_results SET numeric_value = 2
                WHERE run_id = ? AND key = ?
                """,
                (draft.run_id, "workflow.event_count"),
            )

    assert tasks.delete_candidate_for_privacy(candidate.candidate_id) is True
    assert tasks.get_candidate(candidate.candidate_id) is None
    assert tasks.get_revision(revision.task_id, 1) is None
    assert analyses.get(draft.run_id) is None
    with sqlite3.connect(database.path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "task_decisions",
                "task_revisions",
                "analysis_runs",
                "analysis_results",
                "analysis_result_evidence",
            )
        )
    assert counts == (0, 0, 0, 0, 0)
