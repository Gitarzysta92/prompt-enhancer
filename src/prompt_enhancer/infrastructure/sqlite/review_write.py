"""Atomic SQLite write for reviewed discovery candidates.

This module is deliberately separate from discovery policy. It implements only
optimistic version checks, append-only task revisions, decision ownership, and
transactional persistence of an already-validated review command.
"""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from ...application.persistence import (
    DecisionRevisionRole,
    TaskDecisionRecord,
    TaskRevisionRecord,
)
from ...database import DatabaseInvariantError
from ...domain import SAFE_VERSION_PATTERN
from ._common import ConnectionScope, to_iso


def _assert_sessions_in_project(
    connection: sqlite3.Connection,
    revision: TaskRevisionRecord,
) -> None:
    placeholders = ",".join("?" for _ in revision.session_ids)
    rows = connection.execute(
        f"SELECT session_id, project_id FROM sessions WHERE session_id IN ({placeholders})",
        revision.session_ids,
    ).fetchall()
    if len(rows) != len(revision.session_ids):
        raise DatabaseInvariantError("one or more safe sessions do not exist")
    if any(row["project_id"] != revision.project_id for row in rows):
        raise DatabaseInvariantError("task sessions must belong to one project")


def _append_revision(
    connection: sqlite3.Connection,
    revision: TaskRevisionRecord,
) -> None:
    task = connection.execute(
        "SELECT project_id FROM tasks WHERE task_id = ?", (revision.task_id,)
    ).fetchone()
    if task is None:
        if revision.revision != 1:
            raise DatabaseInvariantError("first task revision must be revision one")
        connection.execute(
            "INSERT INTO tasks(task_id, project_id, created_at) VALUES (?, ?, ?)",
            (revision.task_id, revision.project_id, to_iso(revision.created_at)),
        )
    else:
        if task["project_id"] != revision.project_id:
            raise DatabaseInvariantError("task project cannot change")
        latest = connection.execute(
            "SELECT MAX(revision) FROM task_revisions WHERE task_id = ?",
            (revision.task_id,),
        ).fetchone()[0]
        if revision.revision != int(latest) + 1:
            raise DatabaseInvariantError("task revisions must be sequential")
    _assert_sessions_in_project(connection, revision)
    connection.execute(
        """
        INSERT INTO task_revisions(
            task_id, revision, task_type, lifecycle_state,
            input_fingerprint, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            revision.task_id,
            revision.revision,
            revision.task_type,
            revision.lifecycle_state,
            revision.input_fingerprint,
            to_iso(revision.created_at),
        ),
    )
    connection.executemany(
        """
        INSERT INTO task_revision_sessions(task_id, revision, session_id, ordinal)
        VALUES (?, ?, ?, ?)
        """,
        (
            (revision.task_id, revision.revision, session_id, ordinal)
            for ordinal, session_id in enumerate(revision.session_ids)
        ),
    )


def _revision_matches(
    connection: sqlite3.Connection,
    expected: TaskRevisionRecord,
) -> bool:
    row = connection.execute(
        """
        SELECT r.*, t.project_id FROM task_revisions r
        JOIN tasks t ON t.task_id = r.task_id
        WHERE r.task_id = ? AND r.revision = ?
        """,
        (expected.task_id, expected.revision),
    ).fetchone()
    if row is None:
        return False
    sessions = tuple(
        item["session_id"]
        for item in connection.execute(
            """
            SELECT session_id FROM task_revision_sessions
            WHERE task_id = ? AND revision = ? ORDER BY ordinal
            """,
            (expected.task_id, expected.revision),
        ).fetchall()
    )
    return (
        row["project_id"] == expected.project_id
        and row["task_type"] == expected.task_type
        and row["lifecycle_state"] == expected.lifecycle_state
        and row["input_fingerprint"] == expected.input_fingerprint
        and sessions == expected.session_ids
    )


def _decision_matches(
    connection: sqlite3.Connection,
    expected: TaskDecisionRecord,
) -> bool:
    row = connection.execute(
        "SELECT * FROM task_decisions WHERE decision_id = ?",
        (expected.decision_id,),
    ).fetchone()
    if row is None:
        return False
    candidates = tuple(
        item["candidate_id"]
        for item in connection.execute(
            """
            SELECT candidate_id FROM task_decision_candidates
            WHERE decision_id = ? ORDER BY ordinal
            """,
            (expected.decision_id,),
        ).fetchall()
    )
    links = {
        (item["task_id"], item["revision"], item["role"])
        for item in connection.execute(
            """
            SELECT task_id, revision, role FROM task_decision_revisions
            WHERE decision_id = ?
            """,
            (expected.decision_id,),
        ).fetchall()
    }
    expected_links = {
        (link.task_id, link.revision, link.role.value)
        for link in expected.revision_links
    }
    return (
        row["action"] == expected.action.value
        and row["decision_schema_version"] == expected.decision_schema_version
        and row["decision_code"] == expected.decision_code
        and candidates == expected.candidate_ids
        and links == expected_links
    )


def _insert_decision(
    connection: sqlite3.Connection,
    decision: TaskDecisionRecord,
) -> None:
    connection.execute(
        """
        INSERT INTO task_decisions(
            decision_id, action, decision_schema_version, decision_code, decided_at,
            decision_source
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            decision.decision_id,
            decision.action.value,
            decision.decision_schema_version,
            decision.decision_code,
            to_iso(decision.decided_at),
            decision.decision_source,
        ),
    )
    connection.executemany(
        """
        INSERT INTO task_decision_candidates(decision_id, candidate_id, ordinal)
        VALUES (?, ?, ?)
        """,
        (
            (decision.decision_id, candidate_id, ordinal)
            for ordinal, candidate_id in enumerate(decision.candidate_ids)
        ),
    )
    role_ordinals = {
        DecisionRevisionRole.INPUT: 0,
        DecisionRevisionRole.OUTPUT: 0,
    }
    for link in decision.revision_links:
        ordinal = role_ordinals[link.role]
        role_ordinals[link.role] += 1
        connection.execute(
            """
            INSERT INTO task_decision_revisions(
                decision_id, task_id, revision, role, ordinal
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                link.task_id,
                link.revision,
                link.role.value,
                ordinal,
            ),
        )


def apply_review_decision(
    connection_scope: ConnectionScope,
    ensure_initialized: Callable[[], None],
    decision: TaskDecisionRecord,
    output_revisions: tuple[TaskRevisionRecord, ...],
    *,
    expected_discovery_version: str,
) -> bool:
    """Atomically append output revisions and claim reviewed candidates.

    Returns ``True`` when applied and ``False`` only when the same decision ID,
    payload, and output revisions were already stored.
    """

    ensure_initialized()
    if (
        not isinstance(expected_discovery_version, str)
        or not SAFE_VERSION_PATTERN.fullmatch(expected_discovery_version)
    ):
        raise ValueError("expected discovery version is invalid")
    output_identities = {
        (revision.task_id, revision.revision) for revision in output_revisions
    }
    if len(output_identities) != len(output_revisions):
        raise DatabaseInvariantError("output task revisions contain duplicates")
    declared_outputs = {
        (link.task_id, link.revision)
        for link in decision.revision_links
        if link.role is DecisionRevisionRole.OUTPUT
    }
    if output_identities != declared_outputs:
        raise DatabaseInvariantError("output task revisions do not match the decision")

    with connection_scope() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM task_decisions WHERE decision_id = ?",
                (decision.decision_id,),
            ).fetchone()
            if existing is not None:
                if not _decision_matches(connection, decision) or any(
                    not _revision_matches(connection, revision)
                    for revision in output_revisions
                ):
                    raise DatabaseInvariantError(
                        "decision identifier conflicts with stored provenance"
                    )
                connection.commit()
                return False

            project_ids: set[str] = set()
            for candidate_id in decision.candidate_ids:
                row = connection.execute(
                    """
                    SELECT c.project_id, c.discovery_version, dc.decision_id
                    FROM task_candidates c
                    LEFT JOIN task_decision_candidates dc
                        ON dc.candidate_id = c.candidate_id
                    WHERE c.candidate_id = ?
                    """,
                    (candidate_id,),
                ).fetchone()
                if row is None:
                    raise DatabaseInvariantError("task candidate does not exist")
                if row["discovery_version"] != expected_discovery_version:
                    raise DatabaseInvariantError("task candidate version changed")
                if row["decision_id"] is not None:
                    raise DatabaseInvariantError("task candidate already has a decision")
                project_ids.add(row["project_id"])

            for revision in sorted(
                output_revisions, key=lambda item: (item.task_id, item.revision)
            ):
                _append_revision(connection, revision)

            for link in decision.revision_links:
                row = connection.execute(
                    """
                    SELECT t.project_id FROM task_revisions r
                    JOIN tasks t ON t.task_id = r.task_id
                    WHERE r.task_id = ? AND r.revision = ?
                    """,
                    (link.task_id, link.revision),
                ).fetchone()
                if row is None:
                    raise DatabaseInvariantError("task revision does not exist")
                project_ids.add(row["project_id"])
            if len(project_ids) != 1:
                raise DatabaseInvariantError("one decision cannot cross project boundaries")

            _insert_decision(connection, decision)
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
