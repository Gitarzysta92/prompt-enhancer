"""SQLite append-only ledger for explicit task lifecycle receipts."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from ...application.task_lifecycle import (
    TaskLifecycleEventDraft,
    TaskLifecycleEventKind,
    TaskLifecycleEventRecord,
    TaskLifecycleIdempotencyConflict,
    TaskLifecycleIllegalTransition,
    TaskLifecycleParentNotFound,
    TaskLifecycleSnapshot,
    TaskLifecycleStaleHead,
    TaskLifecycleStaleRevision,
    TaskLifecycleState,
)
from ...database import DatabaseInvariantError
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


class SqliteTaskLifecycleRepository:
    """Serialize explicit lifecycle commands against one exact task head."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("lifecycle page limit must be between 1 and 100")
        if isinstance(offset, bool) or offset < 0:
            raise ValueError("lifecycle page offset cannot be negative")

    @staticmethod
    def _event(row: sqlite3.Row) -> TaskLifecycleEventRecord:
        created_at = from_iso(row["created_at"])
        if created_at is None:
            raise DatabaseInvariantError("lifecycle timestamp is missing")
        return TaskLifecycleEventRecord(
            event_id=row["event_id"],
            task_id=row["task_id"],
            task_revision=row["task_revision"],
            sequence=row["sequence"],
            event_kind=TaskLifecycleEventKind(row["event_kind"]),
            prior_state=(
                None
                if row["prior_state"] is None
                else TaskLifecycleState(row["prior_state"])
            ),
            resulting_state=(
                None
                if row["resulting_state"] is None
                else TaskLifecycleState(row["resulting_state"])
            ),
            previous_event_id=row["previous_event_id"],
            supersedes_event_id=row["supersedes_event_id"],
            task_input_fingerprint=row["task_input_fingerprint"],
            command_schema_version=row["command_schema_version"],
            source=row["source"],
            actor_scope=row["actor_scope"],
            request_fingerprint=row["request_fingerprint"],
            idempotency_key_hash=row["idempotency_key_hash"],
            created_at=created_at,
        )

    @classmethod
    def _snapshot(
        cls,
        connection: sqlite3.Connection,
        task_id: str,
        task_revision: int,
        *,
        events_limit: int,
        events_offset: int,
    ) -> TaskLifecycleSnapshot | None:
        parent = connection.execute(
            """
            SELECT revision,lifecycle_state,
                   (SELECT MAX(other.revision) FROM task_revisions other
                    WHERE other.task_id=revision.task_id) AS current_revision
            FROM task_revisions revision
            WHERE task_id=? AND revision=? AND lifecycle_state='confirmed'
            """,
            (task_id, task_revision),
        ).fetchone()
        if parent is None:
            return None
        head = connection.execute(
            """
            SELECT event_id,resulting_state FROM task_lifecycle_events
            WHERE task_id=? AND task_revision=?
            ORDER BY sequence DESC LIMIT 1
            """,
            (task_id, task_revision),
        ).fetchone()
        event_count = int(
            connection.execute(
                """SELECT COUNT(*) FROM task_lifecycle_events
                   WHERE task_id=? AND task_revision=?""",
                (task_id, task_revision),
            ).fetchone()[0]
        )
        prior_revision_event_count = int(
            connection.execute(
                """SELECT COUNT(*) FROM task_lifecycle_events
                   WHERE task_id=? AND task_revision<?""",
                (task_id, task_revision),
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT * FROM task_lifecycle_events
            WHERE task_id=? AND task_revision=?
            ORDER BY sequence
            LIMIT ? OFFSET ?
            """,
            (task_id, task_revision, events_limit, events_offset),
        ).fetchall()
        current_revision = int(parent["current_revision"])
        return TaskLifecycleSnapshot(
            task_id=task_id,
            task_revision=task_revision,
            current_task_revision=current_revision,
            is_current_revision=task_revision == current_revision,
            current_state=(
                None
                if head is None or head["resulting_state"] is None
                else TaskLifecycleState(head["resulting_state"])
            ),
            head_event_id=None if head is None else head["event_id"],
            event_count=event_count,
            prior_revision_event_count=prior_revision_event_count,
            events=tuple(cls._event(row) for row in rows),
            events_limit=events_limit,
            events_offset=events_offset,
        )

    def get_snapshot(
        self,
        task_id: str,
        task_revision: int,
        *,
        events_limit: int = 100,
        events_offset: int = 0,
    ) -> TaskLifecycleSnapshot | None:
        self._ensure_initialized()
        require_safe_id(task_id)
        if isinstance(task_revision, bool) or task_revision < 1:
            raise ValueError("task revision must be positive")
        self._validate_page(events_limit, events_offset)
        with self._connection_scope(readonly=True) as connection:
            return self._snapshot(
                connection,
                task_id,
                task_revision,
                events_limit=events_limit,
                events_offset=events_offset,
            )

    def list_current_snapshots(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        events_limit: int = 100,
    ) -> tuple[TaskLifecycleSnapshot, ...]:
        self._ensure_initialized()
        self._validate_page(limit, offset)
        self._validate_page(events_limit, 0)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                WITH current AS (
                    SELECT task_id,MAX(revision) AS revision
                    FROM task_revisions GROUP BY task_id
                )
                SELECT current.task_id,current.revision
                FROM current
                JOIN task_revisions revision
                  ON revision.task_id=current.task_id
                 AND revision.revision=current.revision
                ORDER BY revision.created_at DESC,current.task_id
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            snapshots = (
                self._snapshot(
                    connection,
                    row["task_id"],
                    row["revision"],
                    events_limit=events_limit,
                    events_offset=0,
                )
                for row in rows
            )
            return tuple(snapshot for snapshot in snapshots if snapshot is not None)

    def append_event(
        self, draft: TaskLifecycleEventDraft
    ) -> tuple[TaskLifecycleEventRecord, bool]:
        """Check replay first, then serialize parent/head/matrix and append."""

        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                replay = connection.execute(
                    """SELECT * FROM task_lifecycle_events
                       WHERE idempotency_key_hash=?""",
                    (draft.idempotency_key_hash,),
                ).fetchone()
                if replay is not None:
                    if replay["request_fingerprint"] != draft.request_fingerprint:
                        raise TaskLifecycleIdempotencyConflict(
                            "lifecycle idempotency fingerprint conflicts"
                        )
                    connection.rollback()
                    return self._event(replay), False

                parent = connection.execute(
                    """
                    SELECT revision.input_fingerprint,revision.lifecycle_state,
                           (SELECT MAX(other.revision) FROM task_revisions other
                            WHERE other.task_id=revision.task_id) AS current_revision
                    FROM task_revisions revision
                    WHERE revision.task_id=? AND revision.revision=?
                    """,
                    (draft.task_id, draft.task_revision),
                ).fetchone()
                if parent is None:
                    raise TaskLifecycleParentNotFound(
                        "task lifecycle parent does not exist"
                    )
                if parent["lifecycle_state"] != "confirmed":
                    raise TaskLifecycleIllegalTransition(
                        "task lifecycle parent is not confirmed"
                    )
                if int(parent["current_revision"]) != draft.task_revision:
                    raise TaskLifecycleStaleRevision(
                        "task lifecycle revision is not current"
                    )

                head = connection.execute(
                    """SELECT * FROM task_lifecycle_events
                       WHERE task_id=? AND task_revision=?
                       ORDER BY sequence DESC LIMIT 1""",
                    (draft.task_id, draft.task_revision),
                ).fetchone()
                head_id = None if head is None else str(head["event_id"])
                if draft.expected_head_event_id != head_id:
                    foreign_head = None
                    if draft.expected_head_event_id is not None:
                        foreign_head = connection.execute(
                            """SELECT task_id,task_revision
                               FROM task_lifecycle_events WHERE event_id=?""",
                            (draft.expected_head_event_id,),
                        ).fetchone()
                    if foreign_head is not None and (
                        foreign_head["task_id"] != draft.task_id
                        or int(foreign_head["task_revision"]) != draft.task_revision
                    ):
                        raise TaskLifecycleIllegalTransition(
                            "task lifecycle head belongs to another revision"
                        )
                    raise TaskLifecycleStaleHead("task lifecycle head changed")

                prior_state = None if head is None else head["resulting_state"]
                if draft.event_kind is TaskLifecycleEventKind.TRANSITION:
                    allowed = {
                        None: TaskLifecycleState.BACKLOG,
                        TaskLifecycleState.BACKLOG.value: TaskLifecycleState.IN_PROGRESS,
                        TaskLifecycleState.IN_PROGRESS.value: TaskLifecycleState.DONE,
                    }
                    expected_state = allowed.get(prior_state)
                    if expected_state is None or draft.requested_state != expected_state:
                        raise TaskLifecycleIllegalTransition(
                            "task lifecycle transition is not legal"
                        )
                    resulting_state: str | None = expected_state.value
                else:
                    if (
                        head is None
                        or draft.supersedes_event_id != head_id
                        or draft.expected_head_event_id != head_id
                    ):
                        raise TaskLifecycleStaleHead(
                            "task lifecycle correction target is stale"
                        )
                    resulting_state = head["prior_state"]

                sequence = 1 if head is None else int(head["sequence"]) + 1
                connection.execute(
                    """
                    INSERT INTO task_lifecycle_events(
                        event_id,task_id,task_revision,sequence,event_kind,
                        prior_state,resulting_state,previous_event_id,
                        supersedes_event_id,task_input_fingerprint,
                        command_schema_version,source,actor_scope,
                        request_fingerprint,idempotency_key_hash,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        draft.event_id,
                        draft.task_id,
                        draft.task_revision,
                        sequence,
                        draft.event_kind.value,
                        prior_state,
                        resulting_state,
                        head_id,
                        draft.supersedes_event_id,
                        parent["input_fingerprint"],
                        draft.command_schema_version,
                        draft.source,
                        draft.actor_scope,
                        draft.request_fingerprint,
                        draft.idempotency_key_hash,
                        to_iso(draft.created_at),
                    ),
                )
                stored = connection.execute(
                    "SELECT * FROM task_lifecycle_events WHERE event_id=?",
                    (draft.event_id,),
                ).fetchone()
                if stored is None:
                    raise DatabaseInvariantError(
                        "lifecycle receipt was not stored"
                    )
                event = self._event(stored)
                connection.commit()
                return event, True
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                message = str(exc).casefold()
                if "idempotency" in message or "request_fingerprint" in message:
                    raise TaskLifecycleIdempotencyConflict(
                        "lifecycle idempotency conflicts"
                    ) from exc
                if "revision is stale" in message:
                    raise TaskLifecycleStaleRevision(
                        "task lifecycle revision is not current"
                    ) from exc
                if "head is stale" in message:
                    raise TaskLifecycleStaleHead(
                        "task lifecycle head changed"
                    ) from exc
                if "transition is invalid" in message or "correction is invalid" in message:
                    raise TaskLifecycleIllegalTransition(
                        "task lifecycle change is invalid"
                    ) from exc
                raise DatabaseInvariantError(
                    "task lifecycle persistence invariant failed"
                ) from exc
            except Exception:
                connection.rollback()
                raise
