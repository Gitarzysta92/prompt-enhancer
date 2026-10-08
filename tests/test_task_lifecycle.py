from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.persistence import AnalysisRunDraft
from prompt_enhancer.application.task_lifecycle import (
    InvalidTaskLifecycleTransitionError,
    TaskLifecycleCorrectionCommand,
    TaskLifecycleIdempotencyError,
    TaskLifecycleNotFoundError,
    TaskLifecycleService,
    TaskLifecycleStaleHeadError,
    TaskLifecycleStaleRevisionError,
    TaskLifecycleState,
    TaskLifecycleTransitionCommand,
)
from prompt_enhancer.database import SCHEMA_VERSION, Database
from prompt_enhancer.domain import DataTier
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer
from prompt_enhancer.application.persistence import TaskRevisionRecord


NOW = datetime(2042, 1, 2, 9, 30, tzinfo=UTC)


def _fixture(tmp_path) -> tuple[Database, TaskRevisionRecord, TaskLifecycleService]:
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, pseudonymizer).ingest(SyntheticAdapter())
    session_id = database.list_sessions(limit=1)[0]["session_id"]
    session = database.get_session(session_id)
    assert session is not None
    revision = TaskRevisionRecord(
        task_id="a" * 64,
        revision=1,
        project_id=session.project_id,
        task_type="feature_implementation",
        lifecycle_state="confirmed",
        session_ids=(session_id,),
        input_fingerprint="b" * 64,
        created_at=NOW - timedelta(minutes=1),
    )
    database.task_repository().append_revision(revision)
    service = TaskLifecycleService(
        database.task_lifecycle_repository(),
        LocalArtifactIdFactory(pseudonymizer),
        clock=lambda: NOW,
    )
    return database, revision, service


def _transition(
    revision: TaskRevisionRecord,
    state: TaskLifecycleState,
    head: str | None,
) -> TaskLifecycleTransitionCommand:
    return TaskLifecycleTransitionCommand(
        task_id=revision.task_id,
        task_revision=revision.revision,
        expected_head_event_id=head,
        state=state,
    )


def test_legacy_revision_is_unknown_and_linear_transitions_are_authoritative(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    repository = database.task_lifecycle_repository()

    legacy = repository.get_snapshot(revision.task_id, revision.revision)
    assert legacy is not None
    assert legacy.current_state is None
    assert legacy.head_event_id is None
    assert legacy.events == ()

    backlog = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="lifecycle-backlog",
    )
    active = service.transition(
        _transition(revision, TaskLifecycleState.IN_PROGRESS, backlog.event.event_id),
        idempotency_key="lifecycle-start",
    )
    done = service.transition(
        _transition(revision, TaskLifecycleState.DONE, active.event.event_id),
        idempotency_key="lifecycle-done",
    )

    snapshot = repository.get_snapshot(revision.task_id, revision.revision)
    assert snapshot is not None
    assert snapshot.current_state is TaskLifecycleState.DONE
    assert snapshot.head_event_id == done.event.event_id
    assert tuple(event.resulting_state for event in snapshot.events) == (
        TaskLifecycleState.BACKLOG,
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.DONE,
    )
    assert tuple(event.sequence for event in snapshot.events) == (1, 2, 3)
    assert all(event.created_at == NOW for event in snapshot.events)
    assert all(event.source == "explicit_local_user" for event in snapshot.events)
    assert all(event.actor_scope == "local_user" for event in snapshot.events)
    assert all(
        event.task_input_fingerprint == revision.input_fingerprint
        for event in snapshot.events
    )
    sqlite_payload = database.path.read_bytes()
    for raw_key in ("lifecycle-backlog", "lifecycle-start", "lifecycle-done"):
        assert raw_key.encode("ascii") not in sqlite_payload
    assert backlog.event.idempotency_key_hash != "lifecycle-backlog"

    with pytest.raises(InvalidTaskLifecycleTransitionError):
        service.transition(
            _transition(revision, TaskLifecycleState.DONE, done.event.event_id),
            idempotency_key="lifecycle-done-again",
        )


def test_replay_precedes_head_checks_and_conflicting_key_is_rejected(tmp_path) -> None:
    _database, revision, service = _fixture(tmp_path)
    command = _transition(revision, TaskLifecycleState.BACKLOG, None)
    first = service.transition(command, idempotency_key="stable-replay")
    service.transition(
        _transition(revision, TaskLifecycleState.IN_PROGRESS, first.event.event_id),
        idempotency_key="advance-after-replay",
    )

    replay = service.transition(command, idempotency_key="stable-replay")
    assert replay.applied is False
    assert replay.event == first.event

    with pytest.raises(TaskLifecycleIdempotencyError):
        service.transition(
            _transition(
                revision,
                TaskLifecycleState.IN_PROGRESS,
                first.event.event_id,
            ),
            idempotency_key="stable-replay",
        )


def test_competing_writers_serialize_and_one_stale_head_loses(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    backlog = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="race-backlog",
    )

    def write(key: str) -> object:
        try:
            return service.transition(
                _transition(
                    revision,
                    TaskLifecycleState.IN_PROGRESS,
                    backlog.event.event_id,
                ),
                idempotency_key=key,
            ).applied
        except TaskLifecycleStaleHeadError as error:
            return type(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(write, ("race-one", "race-two")))

    assert outcomes.count(True) == 1
    assert outcomes.count(TaskLifecycleStaleHeadError) == 1
    snapshot = database.task_lifecycle_repository().get_snapshot(
        revision.task_id, revision.revision
    )
    assert snapshot is not None
    assert snapshot.event_count == 2
    assert snapshot.current_state is TaskLifecycleState.IN_PROGRESS


def test_foreign_head_is_invalid_and_bounded_audit_does_not_change_exact_head(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    session_id = revision.session_ids[0]
    foreign_revision = revision.model_copy(
        update={
            "task_id": "e" * 64,
            "input_fingerprint": "f" * 64,
        }
    )
    database.task_repository().append_revision(foreign_revision)
    foreign = service.transition(
        _transition(foreign_revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="foreign-backlog",
    )
    assert session_id in foreign_revision.session_ids

    with pytest.raises(InvalidTaskLifecycleTransitionError):
        service.transition(
            _transition(
                revision,
                TaskLifecycleState.BACKLOG,
                foreign.event.event_id,
            ),
            idempotency_key="foreign-head-target",
        )

    backlog = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="page-backlog",
    )
    active = service.transition(
        _transition(revision, TaskLifecycleState.IN_PROGRESS, backlog.event.event_id),
        idempotency_key="page-active",
    )
    done = service.transition(
        _transition(revision, TaskLifecycleState.DONE, active.event.event_id),
        idempotency_key="page-done",
    )
    page = database.task_lifecycle_repository().get_snapshot(
        revision.task_id,
        revision.revision,
        events_limit=1,
        events_offset=1,
    )
    assert page is not None
    assert page.events == (active.event,)
    assert page.event_count == 3
    assert page.current_state is TaskLifecycleState.DONE
    assert page.head_event_id == done.event.event_id


def test_unconfirmed_revision_cannot_be_laundered_into_authoritative_work_state(
    tmp_path,
) -> None:
    database, revision, service = _fixture(tmp_path)
    unconfirmed = revision.model_copy(
        update={
            "task_id": "8" * 64,
            "lifecycle_state": "proposal",
            "input_fingerprint": "9" * 64,
        }
    )
    database.task_repository().append_revision(unconfirmed)

    with pytest.raises(InvalidTaskLifecycleTransitionError):
        service.transition(
            _transition(unconfirmed, TaskLifecycleState.BACKLOG, None),
            idempotency_key="unconfirmed-backlog",
        )
    assert (
        database.task_lifecycle_repository().get_snapshot(
            unconfirmed.task_id, unconfirmed.revision
        )
        is None
    )

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="not confirmed"):
            connection.execute(
                """INSERT INTO task_lifecycle_events(
                       event_id,task_id,task_revision,sequence,event_kind,
                       prior_state,resulting_state,previous_event_id,
                       supersedes_event_id,task_input_fingerprint,
                       command_schema_version,source,actor_scope,
                       request_fingerprint,idempotency_key_hash,created_at
                   ) VALUES(?,?,1,1,'transition',NULL,'backlog',NULL,NULL,?,
                            'task-lifecycle-command-v1','explicit_local_user',
                            'local_user',?,?,?)""",
                (
                    "1" * 64,
                    unconfirmed.task_id,
                    unconfirmed.input_fingerprint,
                    "2" * 64,
                    "3" * 64,
                    NOW.isoformat(timespec="microseconds"),
                ),
            )


def test_correction_appends_an_undo_receipt_and_can_restore_unknown(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    backlog = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="correct-backlog",
    )
    corrected = service.correct(
        TaskLifecycleCorrectionCommand(
            task_id=revision.task_id,
            task_revision=revision.revision,
            expected_head_event_id=backlog.event.event_id,
            supersedes_event_id=backlog.event.event_id,
        ),
        idempotency_key="correct-undo-initial",
    )
    assert corrected.event.prior_state is TaskLifecycleState.BACKLOG
    assert corrected.event.resulting_state is None
    assert corrected.event.supersedes_event_id == backlog.event.event_id

    replacement = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, corrected.event.event_id),
        idempotency_key="correct-replacement",
    )
    active = service.transition(
        _transition(revision, TaskLifecycleState.IN_PROGRESS, replacement.event.event_id),
        idempotency_key="correct-start",
    )
    done = service.transition(
        _transition(revision, TaskLifecycleState.DONE, active.event.event_id),
        idempotency_key="correct-done",
    )
    undo_done = service.correct(
        TaskLifecycleCorrectionCommand(
            task_id=revision.task_id,
            task_revision=revision.revision,
            expected_head_event_id=done.event.event_id,
            supersedes_event_id=done.event.event_id,
        ),
        idempotency_key="correct-undo-done",
    )
    assert undo_done.event.resulting_state is TaskLifecycleState.IN_PROGRESS

    snapshot = database.task_lifecycle_repository().get_snapshot(
        revision.task_id, revision.revision
    )
    assert snapshot is not None
    assert snapshot.event_count == 6
    assert snapshot.current_state is TaskLifecycleState.IN_PROGRESS
    assert snapshot.events[0] == backlog.event

    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE task_lifecycle_events SET resulting_state='done' WHERE event_id=?",
                (backlog.event.event_id,),
            )


def test_new_revision_resets_current_state_and_old_revision_rejects_new_commands(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    backlog = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="revision-one-backlog",
    )
    second = revision.model_copy(
        update={
            "revision": 2,
            "input_fingerprint": "c" * 64,
            "created_at": NOW + timedelta(minutes=1),
        }
    )
    database.task_repository().append_revision(second)

    second_snapshot = database.task_lifecycle_repository().get_snapshot(
        second.task_id, second.revision
    )
    assert second_snapshot is not None
    assert second_snapshot.current_state is None
    assert second_snapshot.prior_revision_event_count == 1
    assert second_snapshot.is_current_revision is True

    with pytest.raises(TaskLifecycleStaleRevisionError):
        service.transition(
            _transition(
                revision,
                TaskLifecycleState.IN_PROGRESS,
                backlog.event.event_id,
            ),
            idempotency_key="stale-revision-command",
        )

    replay = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="revision-one-backlog",
    )
    assert replay.applied is False
    assert replay.event == backlog.event


def test_restart_preserves_head_and_analysis_completion_cannot_launder_state(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    backlog = service.transition(
        _transition(revision, TaskLifecycleState.BACKLOG, None),
        idempotency_key="restart-backlog",
    )
    analyses = database.analysis_run_repository()
    analyses.begin(
        AnalysisRunDraft(
            run_id="d" * 64,
            task_id=revision.task_id,
            task_revision=revision.revision,
            metric_pack_key="core",
            metric_pack_version=1,
            data_tier=DataTier.METADATA,
            input_fingerprint=revision.input_fingerprint,
            metric_engine_version="deterministic-v1",
            redactor_version="not-applicable",
            schema_version=SCHEMA_VERSION,
            started_at=NOW,
        )
    )
    analyses.complete("d" * 64, (), finished_at=NOW + timedelta(seconds=1))

    restarted = Database(database.path)
    restarted.initialize()
    snapshot = restarted.task_lifecycle_repository().get_snapshot(
        revision.task_id, revision.revision
    )
    assert snapshot is not None
    assert snapshot.current_state is TaskLifecycleState.BACKLOG
    assert snapshot.head_event_id == backlog.event.event_id
    assert snapshot.event_count == 1


def test_privacy_delete_cascades_ledger_and_prevents_replay_resurrection(tmp_path) -> None:
    database, revision, service = _fixture(tmp_path)
    command = _transition(revision, TaskLifecycleState.BACKLOG, None)
    event = service.transition(command, idempotency_key="privacy-backlog").event

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                "DELETE FROM task_lifecycle_events WHERE event_id=?",
                (event.event_id,),
            )

    assert database.task_repository().delete_task_for_privacy(revision.task_id) is True
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM task_lifecycle_events"
        ).fetchone()[0] == 0

    with pytest.raises(TaskLifecycleNotFoundError):
        service.transition(command, idempotency_key="privacy-backlog")
