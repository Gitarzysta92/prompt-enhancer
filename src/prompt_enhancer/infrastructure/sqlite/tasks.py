"""SQLite implementation of the task/discovery persistence port."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import sqlite3

from ...application.persistence import (
    CandidateDecisionStatus,
    CandidateListItem,
    CandidateSignalRecord,
    DecisionAction,
    DecisionRevisionLink,
    DecisionRevisionRole,
    TaskCandidateRecord,
    TaskDecisionRecord,
    TaskRevisionRecord,
)
from ...database import DatabaseInvariantError
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


class SqliteTaskRepository:
    """Persist immutable task artifacts through a parameterized API."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        begin_comparison_task_delete_authorization: (
            Callable[[str, str, str, str | None, str], tuple[str, str]] | None
        ) = None,
        end_comparison_task_delete_authorization: (
            Callable[[str, str, str], None] | None
        ) = None,
        begin_synthetic_aggregation_delete_authorization: (
            Callable[[str, str, str, str, str, str], str] | None
        ) = None,
        end_synthetic_aggregation_delete_authorization: (
            Callable[[str, str, str], None] | None
        ) = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._begin_comparison_task_delete_authorization = (
            begin_comparison_task_delete_authorization
        )
        self._end_comparison_task_delete_authorization = (
            end_comparison_task_delete_authorization
        )
        self._begin_synthetic_aggregation_delete_authorization = (
            begin_synthetic_aggregation_delete_authorization
        )
        self._end_synthetic_aggregation_delete_authorization = (
            end_synthetic_aggregation_delete_authorization
        )

    @staticmethod
    def _comparison_task_delete_fingerprint(
        *,
        task_id: str,
        prepared_stratum_id: str,
        expected_run_id: str,
        sealed_stratum_id: str | None,
    ) -> str:
        values = (
            "comparison-task-delete-authorization-v1",
            task_id,
            prepared_stratum_id,
            expected_run_id,
            sealed_stratum_id or "explicit-none",
        )
        return hashlib.sha256("\x1f".join(values).encode("ascii")).hexdigest()

    @staticmethod
    def _synthetic_aggregation_delete_fingerprint(
        *,
        operation_id: str,
        validation_receipt_id: str,
        task_id: str,
        validation_fingerprint: str,
    ) -> str:
        return hashlib.sha256(
            "\x1f".join(
                (
                    "synthetic-aggregation-delete-authorization-v1",
                    operation_id,
                    validation_receipt_id,
                    "task",
                    task_id,
                    validation_fingerprint,
                )
            ).encode("ascii")
        ).hexdigest()

    def _delete_synthetic_aggregation_for_task_authorization(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        task_id: str,
    ) -> None:
        rows = connection.execute(
            """SELECT DISTINCT root.validation_receipt_id,
                              root.validation_fingerprint
               FROM comparison_task_delete_authorizations upstream
               JOIN comparison_sealed_stratum_roots sealed
                 ON sealed.sealed_stratum_id=upstream.sealed_stratum_id
                AND sealed.prepared_stratum_id=upstream.prepared_stratum_id
                AND sealed.analysis_run_id=upstream.expected_analysis_run_id
               JOIN comparison_prepared_task_projections projection
                 ON projection.prepared_stratum_id=sealed.prepared_stratum_id
                AND projection.task_id=upstream.task_id
               JOIN synthetic_aggregation_validation_members member
                 ON member.sealed_stratum_id=sealed.sealed_stratum_id
               JOIN synthetic_aggregation_validation_roots root
                 ON root.validation_receipt_id=member.validation_receipt_id
               WHERE upstream.operation_id=? AND upstream.task_id=?
               ORDER BY root.validation_receipt_id""",
            (operation_id, task_id),
        ).fetchall()
        if rows and (
            self._begin_synthetic_aggregation_delete_authorization is None
            or self._end_synthetic_aggregation_delete_authorization is None
        ):
            raise DatabaseInvariantError(
                "synthetic aggregation task privacy deletion is not authorized"
            )
        for row in rows:
            validation_receipt_id = str(row["validation_receipt_id"])
            validation_fingerprint = str(row["validation_fingerprint"])
            authorization_fingerprint = (
                self._synthetic_aggregation_delete_fingerprint(
                    operation_id=operation_id,
                    validation_receipt_id=validation_receipt_id,
                    task_id=task_id,
                    validation_fingerprint=validation_fingerprint,
                )
            )
            assert self._begin_synthetic_aggregation_delete_authorization is not None
            assert self._end_synthetic_aggregation_delete_authorization is not None
            tag = self._begin_synthetic_aggregation_delete_authorization(
                operation_id,
                validation_receipt_id,
                "task",
                task_id,
                validation_fingerprint,
                authorization_fingerprint,
            )
            try:
                connection.execute(
                    """INSERT INTO synthetic_aggregation_delete_authorizations
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        operation_id,
                        validation_receipt_id,
                        "task",
                        task_id,
                        validation_fingerprint,
                        authorization_fingerprint,
                        tag,
                    ),
                )
                connection.execute(
                    """DELETE FROM synthetic_aggregation_validation_roots
                       WHERE validation_receipt_id=?""",
                    (validation_receipt_id,),
                )
                connection.execute(
                    """DELETE FROM synthetic_aggregation_delete_authorizations
                       WHERE operation_id=?""",
                    (operation_id,),
                )
            finally:
                self._end_synthetic_aggregation_delete_authorization(
                    operation_id,
                    authorization_fingerprint,
                    tag,
                )

    def _delete_comparison_graphs_for_tasks(
        self,
        connection: sqlite3.Connection,
        task_ids: set[str],
    ) -> list[tuple[str, str, str]]:
        if not task_ids:
            return []
        placeholders = ",".join("?" for _ in task_ids)
        rows = connection.execute(
            f"""SELECT MIN(projection.task_id) AS task_id,
                       prepared.prepared_stratum_id,
                       prepared.expected_analysis_run_id,
                       sealed.sealed_stratum_id
                FROM comparison_prepared_task_projections projection
                JOIN comparison_prepared_stratum_roots prepared
                  ON prepared.prepared_stratum_id=projection.prepared_stratum_id
                LEFT JOIN comparison_sealed_stratum_roots sealed
                  ON sealed.prepared_stratum_id=prepared.prepared_stratum_id
                WHERE projection.task_id IN ({placeholders})
                GROUP BY prepared.prepared_stratum_id,
                         prepared.expected_analysis_run_id,
                         sealed.sealed_stratum_id
                ORDER BY prepared.prepared_stratum_id""",
            tuple(sorted(task_ids)),
        ).fetchall()
        if rows and (
            self._begin_comparison_task_delete_authorization is None
            or self._end_comparison_task_delete_authorization is None
        ):
            raise DatabaseInvariantError(
                "comparison task privacy deletion is not authorized"
            )
        authorizations: list[tuple[str, str, str]] = []
        try:
            for row in rows:
                fingerprint = self._comparison_task_delete_fingerprint(
                    task_id=row["task_id"],
                    prepared_stratum_id=row["prepared_stratum_id"],
                    expected_run_id=row["expected_analysis_run_id"],
                    sealed_stratum_id=row["sealed_stratum_id"],
                )
                assert self._begin_comparison_task_delete_authorization is not None
                operation_id, tag = (
                    self._begin_comparison_task_delete_authorization(
                        row["task_id"],
                        row["prepared_stratum_id"],
                        row["expected_analysis_run_id"],
                        row["sealed_stratum_id"],
                        fingerprint,
                    )
                )
                authorizations.append((operation_id, fingerprint, tag))
                connection.execute(
                    """INSERT INTO comparison_task_delete_authorizations(
                           operation_id,task_id,prepared_stratum_id,
                           expected_analysis_run_id,sealed_stratum_id,
                           authorization_fingerprint,authorization_tag)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        operation_id,
                        row["task_id"],
                        row["prepared_stratum_id"],
                        row["expected_analysis_run_id"],
                        row["sealed_stratum_id"],
                        fingerprint,
                        tag,
                    ),
                )
                self._delete_synthetic_aggregation_for_task_authorization(
                    connection,
                    operation_id=operation_id,
                    task_id=str(row["task_id"]),
                )
            for prepared_stratum_id in dict.fromkeys(
                str(row["prepared_stratum_id"]) for row in rows
            ):
                connection.execute(
                    """DELETE FROM comparison_prepared_stratum_roots
                       WHERE prepared_stratum_id=?""",
                    (prepared_stratum_id,),
                )
            for operation_id, _, _ in authorizations:
                connection.execute(
                    """DELETE FROM comparison_task_delete_authorizations
                       WHERE operation_id=?""",
                    (operation_id,),
                )
            return authorizations
        except Exception:
            if self._end_comparison_task_delete_authorization is not None:
                for authorization in authorizations:
                    self._end_comparison_task_delete_authorization(*authorization)
            raise

    @staticmethod
    def _assert_sessions_in_project(
        connection: sqlite3.Connection,
        project_id: str,
        session_ids: tuple[str, ...],
    ) -> None:
        placeholders = ",".join("?" for _ in session_ids)
        rows = connection.execute(
            f"SELECT session_id, project_id FROM sessions WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchall()
        if len(rows) != len(session_ids):
            raise DatabaseInvariantError("one or more safe sessions do not exist")
        if any(row["project_id"] != project_id for row in rows):
            raise DatabaseInvariantError("task sessions must belong to one project")

    def add_candidate(self, candidate: TaskCandidateRecord) -> None:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM task_candidates WHERE candidate_id = ?",
                    (candidate.candidate_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError("task candidate already exists")
                project = connection.execute(
                    """
                    SELECT p.installation_id, p.provider,
                           i.provider AS installation_provider
                    FROM projects p
                    JOIN installations i ON i.installation_id = p.installation_id
                    WHERE p.project_id = ?
                    """,
                    (candidate.project_id,),
                ).fetchone()
                if project is None:
                    raise DatabaseInvariantError("safe project does not exist")
                if (
                    project["installation_id"] != candidate.installation_id
                    or project["provider"] != candidate.provider.value
                    or project["installation_provider"] != candidate.provider.value
                ):
                    raise DatabaseInvariantError("candidate provenance does not match project")
                self._assert_sessions_in_project(
                    connection, candidate.project_id, candidate.session_ids
                )
                connection.execute(
                    """
                    INSERT INTO task_candidates(
                        candidate_id, project_id, discovery_version,
                        input_fingerprint, confidence, observed_count,
                        eligible_count, coverage, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.candidate_id,
                        candidate.project_id,
                        candidate.discovery_version,
                        candidate.input_fingerprint,
                        candidate.confidence,
                        candidate.observed_count,
                        candidate.eligible_count,
                        candidate.coverage,
                        to_iso(candidate.created_at),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO task_candidate_sessions(candidate_id, session_id, ordinal)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (candidate.candidate_id, session_id, ordinal)
                        for ordinal, session_id in enumerate(candidate.session_ids)
                    ),
                )
                for signal_ordinal, signal in enumerate(candidate.signals):
                    connection.execute(
                        """
                        INSERT INTO task_candidate_signals(
                            candidate_id, ordinal, signal_key, signal_version,
                            direction, confidence, weight, evidence_code,
                            observed_count, eligible_count, coverage,
                            numeric_evidence, evidence_unit
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            candidate.candidate_id,
                            signal_ordinal,
                            signal.key,
                            signal.version,
                            signal.direction.value,
                            signal.confidence,
                            signal.weight,
                            signal.evidence_code,
                            signal.observed_count,
                            signal.eligible_count,
                            signal.coverage,
                            signal.numeric_evidence,
                            signal.evidence_unit,
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO task_candidate_signal_sessions(
                            candidate_id, signal_ordinal, session_id, ordinal
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            (candidate.candidate_id, signal_ordinal, session_id, ordinal)
                            for ordinal, session_id in enumerate(signal.session_ids)
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get_candidate(self, candidate_id: str) -> TaskCandidateRecord | None:
        self._ensure_initialized()
        require_safe_id(candidate_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT c.*, p.installation_id, p.provider
                FROM task_candidates c
                JOIN projects p ON p.project_id = c.project_id
                WHERE c.candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            session_rows = connection.execute(
                """
                SELECT session_id FROM task_candidate_sessions
                WHERE candidate_id = ? ORDER BY ordinal
                """,
                (candidate_id,),
            ).fetchall()
            signal_rows = connection.execute(
                """
                SELECT * FROM task_candidate_signals
                WHERE candidate_id = ? ORDER BY ordinal
                """,
                (candidate_id,),
            ).fetchall()
            signals: list[CandidateSignalRecord] = []
            for signal_row in signal_rows:
                signal_sessions = connection.execute(
                    """
                    SELECT session_id FROM task_candidate_signal_sessions
                    WHERE candidate_id = ? AND signal_ordinal = ? ORDER BY ordinal
                    """,
                    (candidate_id, signal_row["ordinal"]),
                ).fetchall()
                signals.append(
                    CandidateSignalRecord(
                        key=signal_row["signal_key"],
                        version=signal_row["signal_version"],
                        session_ids=tuple(item["session_id"] for item in signal_sessions),
                        direction=signal_row["direction"],
                        confidence=signal_row["confidence"],
                        weight=signal_row["weight"],
                        evidence_code=signal_row["evidence_code"],
                        observed_count=signal_row["observed_count"],
                        eligible_count=signal_row["eligible_count"],
                        coverage=signal_row["coverage"],
                        numeric_evidence=signal_row["numeric_evidence"],
                        evidence_unit=signal_row["evidence_unit"],
                    )
                )
        return TaskCandidateRecord(
            candidate_id=row["candidate_id"],
            provider=row["provider"],
            installation_id=row["installation_id"],
            project_id=row["project_id"],
            session_ids=tuple(item["session_id"] for item in session_rows),
            signals=tuple(signals),
            confidence=row["confidence"],
            observed_count=row["observed_count"],
            eligible_count=row["eligible_count"],
            coverage=row["coverage"],
            discovery_version=row["discovery_version"],
            input_fingerprint=row["input_fingerprint"],
            created_at=from_iso(row["created_at"]),
        )

    def list_candidates(
        self,
        *,
        status: CandidateDecisionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CandidateListItem, ...]:
        self._ensure_initialized()
        self._validate_page(limit, offset)
        if status is not None and not isinstance(status, CandidateDecisionStatus):
            raise ValueError("candidate status is invalid")
        predicates: list[str] = []
        parameters: list[object] = []
        if status is CandidateDecisionStatus.UNDECIDED:
            predicates.append("d.decision_id IS NULL")
        elif status is CandidateDecisionStatus.DECIDED:
            predicates.append("d.decision_id IS NOT NULL")
        where = "" if not predicates else "WHERE " + " AND ".join(predicates)
        parameters.extend((limit, offset))
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                f"""
                SELECT c.candidate_id, d.decision_id, d.action, d.decision_source
                FROM task_candidates c
                LEFT JOIN task_decision_candidates dc
                    ON dc.candidate_id = c.candidate_id
                LEFT JOIN task_decisions d ON d.decision_id = dc.decision_id
                {where}
                ORDER BY c.created_at DESC, c.candidate_id
                LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()
        items: list[CandidateListItem] = []
        for row in rows:
            candidate = self.get_candidate(row["candidate_id"])
            if candidate is not None:
                items.append(
                    CandidateListItem(
                        candidate=candidate,
                        decision_status=(
                            CandidateDecisionStatus.UNDECIDED
                            if row["decision_id"] is None
                            else CandidateDecisionStatus.DECIDED
                        ),
                        decision_id=row["decision_id"],
                        decision_action=row["action"],
                        decision_source=row["decision_source"],
                    )
                )
        return tuple(items)

    def append_revision(self, revision: TaskRevisionRecord) -> None:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                task = connection.execute(
                    "SELECT project_id FROM tasks WHERE task_id = ?", (revision.task_id,)
                ).fetchone()
                latest = None
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
                self._assert_sessions_in_project(
                    connection, revision.project_id, revision.session_ids
                )
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
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get_revision(
        self, task_id: str, revision: int
    ) -> TaskRevisionRecord | None:
        self._ensure_initialized()
        require_safe_id(task_id)
        if revision < 1:
            raise ValueError("revision must be positive")
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT r.*, t.project_id FROM task_revisions r
                JOIN tasks t ON t.task_id = r.task_id
                WHERE r.task_id = ? AND r.revision = ?
                """,
                (task_id, revision),
            ).fetchone()
            if row is None:
                return None
            session_rows = connection.execute(
                """
                SELECT session_id FROM task_revision_sessions
                WHERE task_id = ? AND revision = ? ORDER BY ordinal
                """,
                (task_id, revision),
            ).fetchall()
        return TaskRevisionRecord(
            task_id=row["task_id"],
            revision=row["revision"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            lifecycle_state=row["lifecycle_state"],
            session_ids=tuple(item["session_id"] for item in session_rows),
            input_fingerprint=row["input_fingerprint"],
            created_at=from_iso(row["created_at"]),
        )

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if isinstance(offset, bool) or offset < 0:
            raise ValueError("offset cannot be negative")

    def list_task_revisions(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[TaskRevisionRecord, ...]:
        self._ensure_initialized()
        self._validate_page(limit, offset)
        parameters: list[object] = []
        where = ""
        if task_id is not None:
            require_safe_id(task_id)
            where = "WHERE task_id = ?"
            parameters.append(task_id)
        parameters.extend((limit, offset))
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                f"""
                SELECT task_id, revision FROM task_revisions {where}
                ORDER BY created_at DESC, task_id, revision DESC
                LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()
        revisions = (
            self.get_revision(row["task_id"], row["revision"]) for row in rows
        )
        return tuple(revision for revision in revisions if revision is not None)

    def list_current_revisions_for_session(
        self,
        session_id: str,
    ) -> tuple[TaskRevisionRecord, ...]:
        """Return only latest immutable task revisions containing a safe session.

        Historical revisions are deliberately excluded.  More than one current
        revision is preserved so application services can abstain instead of
        guessing which reviewed task context is authoritative.
        """

        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                WITH latest_revisions AS (
                    SELECT task_id, MAX(revision) AS revision
                    FROM task_revisions
                    GROUP BY task_id
                )
                SELECT latest.task_id, latest.revision
                FROM latest_revisions AS latest
                JOIN task_revision_sessions AS members
                  ON members.task_id = latest.task_id
                 AND members.revision = latest.revision
                WHERE members.session_id = ?
                ORDER BY latest.task_id
                """,
                (session_id,),
            ).fetchall()
        records = (
            self.get_revision(row["task_id"], row["revision"])
            for row in rows
        )
        return tuple(record for record in records if record is not None)

    def list_current_revisions_for_project(
        self,
        project_id: str,
        *,
        limit: int = 500,
    ) -> tuple[TaskRevisionRecord, ...]:
        """Latest revision of every task in one project (newest first, bounded)."""

        self._ensure_initialized()
        require_safe_id(project_id)
        bounded = max(1, min(int(limit), 2_000))
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                WITH latest_revisions AS (
                    SELECT task_id, MAX(revision) AS revision
                    FROM task_revisions
                    GROUP BY task_id
                )
                SELECT latest.task_id, latest.revision
                FROM latest_revisions AS latest
                JOIN tasks ON tasks.task_id = latest.task_id
                WHERE tasks.project_id = ?
                ORDER BY tasks.created_at DESC, latest.task_id
                LIMIT ?
                """,
                (project_id, bounded),
            ).fetchall()
        records = (
            self.get_revision(row["task_id"], row["revision"])
            for row in rows
        )
        return tuple(record for record in records if record is not None)

    def record_decision(self, decision: TaskDecisionRecord) -> None:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM task_decisions WHERE decision_id = ?",
                    (decision.decision_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError("task decision already exists")
                project_ids: set[str] = set()
                for candidate_id in decision.candidate_ids:
                    row = connection.execute(
                        "SELECT project_id FROM task_candidates WHERE candidate_id = ?",
                        (candidate_id,),
                    ).fetchone()
                    if row is None:
                        raise DatabaseInvariantError("task candidate does not exist")
                    if connection.execute(
                        "SELECT 1 FROM task_decision_candidates WHERE candidate_id = ?",
                        (candidate_id,),
                    ).fetchone() is not None:
                        raise DatabaseInvariantError("task candidate already has a decision")
                    project_ids.add(row["project_id"])
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
                connection.execute(
                    """
                    INSERT INTO task_decisions(
                        decision_id, action, decision_schema_version,
                        decision_code, decided_at, decision_source
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
                    INSERT INTO task_decision_candidates(
                        decision_id, candidate_id, ordinal
                    ) VALUES (?, ?, ?)
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
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def apply_review_decision(
        self,
        decision: TaskDecisionRecord,
        output_revisions: tuple[TaskRevisionRecord, ...],
        *,
        expected_discovery_version: str,
    ) -> bool:
        """Apply one reviewed candidate command as a single transaction."""

        from .review_write import apply_review_decision

        return apply_review_decision(
            self._connection_scope,
            self._ensure_initialized,
            decision,
            output_revisions,
            expected_discovery_version=expected_discovery_version,
        )

    @staticmethod
    def _load_decision(
        connection: sqlite3.Connection, decision_id: str
    ) -> TaskDecisionRecord:
        row = connection.execute(
            "SELECT * FROM task_decisions WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        candidate_rows = connection.execute(
            """
            SELECT candidate_id FROM task_decision_candidates
            WHERE decision_id = ? ORDER BY ordinal
            """,
            (decision_id,),
        ).fetchall()
        revision_rows = connection.execute(
            """
            SELECT task_id, revision, role FROM task_decision_revisions
            WHERE decision_id = ?
            ORDER BY CASE role WHEN 'input' THEN 0 ELSE 1 END, ordinal
            """,
            (decision_id,),
        ).fetchall()
        return TaskDecisionRecord(
            decision_id=row["decision_id"],
            action=DecisionAction(row["action"]),
            candidate_ids=tuple(item["candidate_id"] for item in candidate_rows),
            revision_links=tuple(
                DecisionRevisionLink(
                    task_id=item["task_id"],
                    revision=item["revision"],
                    role=DecisionRevisionRole(item["role"]),
                )
                for item in revision_rows
            ),
            decision_schema_version=row["decision_schema_version"],
            decision_code=row["decision_code"],
            decided_at=from_iso(row["decided_at"]),
            decision_source=row["decision_source"] or "person",
        )

    def list_decisions(self, candidate_id: str) -> tuple[TaskDecisionRecord, ...]:
        self._ensure_initialized()
        require_safe_id(candidate_id)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT d.decision_id FROM task_decisions d
                JOIN task_decision_candidates c ON c.decision_id = d.decision_id
                WHERE c.candidate_id = ? ORDER BY d.decided_at, d.decision_id
                """,
                (candidate_id,),
            ).fetchall()
            return tuple(
                self._load_decision(connection, row["decision_id"]) for row in rows
            )

    @staticmethod
    def _privacy_component(
        connection: sqlite3.Connection,
        *,
        candidate_ids: set[str],
        task_ids: set[str],
    ) -> tuple[set[str], set[str], set[str]]:
        """Find all artifacts connected by a review decision.

        A confirmed task is derived from its candidate. Purging either side must
        therefore remove the whole connected component, including analysis runs.
        """

        decision_ids: set[str] = set()
        while True:
            discovered: set[str] = set()
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                discovered.update(
                    row["decision_id"]
                    for row in connection.execute(
                        f"SELECT decision_id FROM task_decision_candidates WHERE candidate_id IN ({placeholders})",
                        tuple(candidate_ids),
                    ).fetchall()
                )
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                discovered.update(
                    row["decision_id"]
                    for row in connection.execute(
                        f"SELECT decision_id FROM task_decision_revisions WHERE task_id IN ({placeholders})",
                        tuple(task_ids),
                    ).fetchall()
                )
            new_decisions = discovered - decision_ids
            if not new_decisions:
                return candidate_ids, task_ids, decision_ids
            decision_ids.update(new_decisions)
            placeholders = ",".join("?" for _ in new_decisions)
            candidate_ids.update(
                row["candidate_id"]
                for row in connection.execute(
                    f"SELECT candidate_id FROM task_decision_candidates WHERE decision_id IN ({placeholders})",
                    tuple(new_decisions),
                ).fetchall()
            )
            task_ids.update(
                row["task_id"]
                for row in connection.execute(
                    f"SELECT task_id FROM task_decision_revisions WHERE decision_id IN ({placeholders})",
                    tuple(new_decisions),
                ).fetchall()
            )

    @classmethod
    def _delete_privacy_component(
        cls,
        connection: sqlite3.Connection,
        *,
        candidate_ids: set[str],
        task_ids: set[str],
    ) -> None:
        candidate_ids, task_ids, decision_ids = cls._privacy_component(
            connection, candidate_ids=candidate_ids, task_ids=task_ids
        )
        for decision_id in decision_ids:
            connection.execute(
                "DELETE FROM task_decisions WHERE decision_id = ?", (decision_id,)
            )
        for task_id in task_ids:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        for candidate_id in candidate_ids:
            connection.execute(
                "DELETE FROM task_candidates WHERE candidate_id = ?", (candidate_id,)
            )

    def delete_candidate_for_privacy(self, candidate_id: str) -> bool:
        self._ensure_initialized()
        require_safe_id(candidate_id)
        authorizations: list[tuple[str, str, str]] = []
        with self._connection_scope() as connection:
            try:
                connection.execute("PRAGMA secure_delete=ON")
                if int(connection.execute("PRAGMA secure_delete").fetchone()[0]) != 1:
                    raise DatabaseInvariantError(
                        "task privacy deletion requires SQLite secure_delete"
                    )
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute("BEGIN IMMEDIATE")
                existed = connection.execute(
                    "SELECT 1 FROM task_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone() is not None
                _, component_task_ids, _ = self._privacy_component(
                    connection,
                    candidate_ids={candidate_id},
                    task_ids=set(),
                )
                authorizations = self._delete_comparison_graphs_for_tasks(
                    connection,
                    component_task_ids,
                )
                self._delete_privacy_component(
                    connection, candidate_ids={candidate_id}, task_ids=set()
                )
                connection.commit()
                connection.execute("PRAGMA trusted_schema=OFF")
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if checkpoint is None or tuple(
                    int(value) for value in checkpoint
                ) != (0, 0, 0):
                    raise DatabaseInvariantError(
                        "task privacy deletion committed; WAL purge pending"
                    )
                return existed
            except Exception:
                connection.rollback()
                connection.execute("PRAGMA trusted_schema=OFF")
                raise
            finally:
                if self._end_comparison_task_delete_authorization is not None:
                    for authorization in authorizations:
                        self._end_comparison_task_delete_authorization(
                            *authorization
                        )

    def delete_task_for_privacy(self, task_id: str) -> bool:
        self._ensure_initialized()
        require_safe_id(task_id)
        authorizations: list[tuple[str, str, str]] = []
        with self._connection_scope() as connection:
            try:
                connection.execute("PRAGMA secure_delete=ON")
                if int(connection.execute("PRAGMA secure_delete").fetchone()[0]) != 1:
                    raise DatabaseInvariantError(
                        "task privacy deletion requires SQLite secure_delete"
                    )
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute("BEGIN IMMEDIATE")
                existed = connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone() is not None
                _, component_task_ids, _ = self._privacy_component(
                    connection,
                    candidate_ids=set(),
                    task_ids={task_id},
                )
                authorizations = self._delete_comparison_graphs_for_tasks(
                    connection,
                    component_task_ids,
                )
                self._delete_privacy_component(
                    connection, candidate_ids=set(), task_ids={task_id}
                )
                connection.commit()
                connection.execute("PRAGMA trusted_schema=OFF")
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if checkpoint is None or tuple(
                    int(value) for value in checkpoint
                ) != (0, 0, 0):
                    raise DatabaseInvariantError(
                        "task privacy deletion committed; WAL purge pending"
                    )
                return existed
            except Exception:
                connection.rollback()
                connection.execute("PRAGMA trusted_schema=OFF")
                raise
            finally:
                if self._end_comparison_task_delete_authorization is not None:
                    for authorization in authorizations:
                        self._end_comparison_task_delete_authorization(
                            *authorization
                        )
