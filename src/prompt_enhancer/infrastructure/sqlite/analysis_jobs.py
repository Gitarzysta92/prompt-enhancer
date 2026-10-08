"""SQLite state machine for durable, content-free local analysis jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import sqlite3

from ...application.jobs import (
    ACTIVE_ANALYSIS_JOB_STATES,
    TERMINAL_ANALYSIS_JOB_STATES,
    AnalysisJobCancellationBatchResult,
    AnalysisJobDraft,
    AnalysisJobEnqueueResult,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobPage,
    AnalysisJobRecord,
    AnalysisJobRecoveryResult,
    AnalysisJobState,
    AnalysisPublicationDeadlineFailure,
    PowerSourceState,
)
from ...database import DatabaseInvariantError
from ...domain import Provider
from ._common import (
    ConnectionScope,
    from_iso,
    from_epoch_us,
    require_safe_id,
    require_safe_label,
    require_utc,
    to_iso,
    to_epoch_us,
)


_RETRY_BASE = timedelta(seconds=5)
_RETRY_MAX = timedelta(minutes=5)
_PUBLICATION_BUDGET = timedelta(minutes=30)
_PUBLICATION_COMPLETED_REASON = "local_analysis_completed"


class SqliteAnalysisJobRepository:
    """Transactional queue with expiring leases and bounded retry recovery."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        begin_publication_authorization: (
            Callable[[str, str], tuple[str, str]] | None
        ) = None,
        end_publication_authorization: (
            Callable[[str, str, str, str], None] | None
        ) = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._begin_publication_authorization = begin_publication_authorization
        self._end_publication_authorization = end_publication_authorization

    def _authorized_publication_write(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        action: str,
        callback: Callable[[], None],
    ) -> None:
        if (
            self._begin_publication_authorization is None
            or self._end_publication_authorization is None
        ):
            raise DatabaseInvariantError(
                "automation publication write is not authorized"
            )
        trusted_schema = int(
            connection.execute("PRAGMA trusted_schema").fetchone()[0]
        )
        operation_id, tag = self._begin_publication_authorization(job_id, action)
        try:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "INSERT INTO automation_publication_write_authorizations "
                "VALUES(?,?,?,?)",
                (operation_id, job_id, action, tag),
            )
            callback()
            connection.execute(
                "DELETE FROM automation_publication_write_authorizations "
                "WHERE operation_id=?",
                (operation_id,),
            )
        finally:
            connection.execute(
                f"PRAGMA trusted_schema={'ON' if trusted_schema else 'OFF'}"
            )
            self._end_publication_authorization(
                operation_id, job_id, action, tag
            )

    @staticmethod
    def _retry_delay(attempt_count: int) -> timedelta:
        seconds = _RETRY_BASE.total_seconds() * (2 ** max(0, attempt_count - 1))
        return timedelta(seconds=min(seconds, _RETRY_MAX.total_seconds()))

    @staticmethod
    def _metrics(
        connection: sqlite3.Connection,
        job_id: str,
    ) -> tuple[str, ...]:
        return tuple(
            row["metric_key"]
            for row in connection.execute(
                """
                SELECT metric_key FROM analysis_job_metrics
                WHERE job_id = ? ORDER BY ordinal
                """,
                (job_id,),
            ).fetchall()
        )

    @classmethod
    def _record(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> AnalysisJobRecord:
        publication = connection.execute(
            """SELECT first_claim_at_us,deadline_at_us,high_water_at_us
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (row["job_id"],),
        ).fetchone()
        return AnalysisJobRecord(
            job_id=row["job_id"],
            dedupe_key=row["dedupe_key"],
            identity=AnalysisJobIdentity(
                kind=AnalysisJobKind(row["kind"]),
                provider=Provider(row["provider"]),
                project_id=row["project_id"],
                session_id=row["session_id"],
                input_fingerprint=row["input_fingerprint"],
                provenance_fingerprint=row["provenance_fingerprint"],
                metric_keys=cls._metrics(connection, row["job_id"]),
                estimator_plan_version=row["estimator_plan_version"],
                redactor_version=row["redactor_version"],
                provider_schema_version=row["provider_schema_version"],
                automation_grant_id=row["automation_grant_id"],
                local_only=bool(row["local_only"]),
            ),
            state=AnalysisJobState(row["state"]),
            stage_number=row["stage_number"],
            progress_completed=row["progress_completed"],
            progress_total=row["progress_total"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            available_at=from_iso(row["available_at"]),
            cancel_requested=bool(row["cancel_requested"]),
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=from_iso(row["lease_expires_at"]),
            runtime_started_at=(
                None
                if publication is None
                else from_epoch_us(int(publication["first_claim_at_us"]))
            ),
            publication_deadline_at=(
                None
                if publication is None
                else from_epoch_us(int(publication["deadline_at_us"]))
            ),
            publication_high_water_at=(
                None
                if publication is None
                else from_epoch_us(int(publication["high_water_at_us"]))
            ),
            last_error_code=row["last_error_code"],
            terminal_reason_code=row["terminal_reason_code"],
            created_at=from_iso(row["created_at"]),
            updated_at=from_iso(row["updated_at"]),
            terminal_at=from_iso(row["terminal_at"]),
        )

    @classmethod
    def _get_locked(
        cls,
        connection: sqlite3.Connection,
        job_id: str,
    ) -> AnalysisJobRecord | None:
        row = connection.execute(
            "SELECT * FROM analysis_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return None if row is None else cls._record(connection, row)

    @staticmethod
    def _completed_publication_row(
        connection: sqlite3.Connection, job_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """SELECT published.published_at
               FROM automation_session_quality_publication_deadlines root
               JOIN automation_session_quality_publications published
                 ON published.job_id=root.job_id
               JOIN session_analysis_runs run ON run.run_id=root.analysis_run_id
               WHERE root.job_id=? AND run.status='completed'
                 AND published.analysis_run_id=run.run_id
                 AND NOT EXISTS (
                   SELECT 1
                   FROM automation_session_quality_publication_closures closure
                   WHERE closure.job_id=root.job_id
                 )""",
            (job_id,),
        ).fetchone()

    @classmethod
    def _reconcile_completed_publication_locked(
        cls,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        now: datetime,
    ) -> bool:
        published = cls._completed_publication_row(connection, job_id)
        if published is None:
            return False
        row = connection.execute(
            "SELECT state FROM analysis_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None or row["state"] in {
            "completed", "partial", "failed", "cancelled", "superseded"
        }:
            return row is not None and row["state"] == "completed"
        timestamp = str(published["published_at"])
        connection.execute(
            """UPDATE analysis_jobs SET
                   state='completed',stage_number=NULL,
                   progress_completed=progress_total,
                   cancel_requested=0,lease_owner=NULL,lease_token=NULL,
                   lease_expires_at=NULL,last_error_code=NULL,
                   terminal_reason_code=?,terminal_at=?,updated_at=?
               WHERE job_id=?""",
            (_PUBLICATION_COMPLETED_REASON, timestamp, timestamp, job_id),
        )
        return True

    @classmethod
    def _reconcile_all_completed_publications_locked(
        cls, connection: sqlite3.Connection, *, now: datetime
    ) -> None:
        job_ids = tuple(
            str(row["job_id"])
            for row in connection.execute(
                """SELECT published.job_id
                   FROM automation_session_quality_publications published
                   JOIN session_analysis_runs run
                     ON run.run_id=published.analysis_run_id
                   JOIN analysis_jobs job ON job.job_id=published.job_id
                   WHERE run.status='completed'
                     AND job.state NOT IN (
                       'completed','partial','failed','cancelled','superseded'
                     ) ORDER BY published.job_id"""
            ).fetchall()
        )
        for job_id in job_ids:
            cls._reconcile_completed_publication_locked(
                connection, job_id=job_id, now=now
            )

    @staticmethod
    def _reconcile_missing_publication_roots_locked(
        connection: sqlite3.Connection, *, now: datetime
    ) -> int:
        """Fail closed upgraded automation attempts that predate the v25 root."""

        timestamp = to_iso(now)
        expired_active = int(
            connection.execute(
                """SELECT COUNT(*) FROM analysis_jobs job
                   WHERE job.kind='session_quality'
                     AND job.automation_grant_id IS NOT NULL
                     AND job.attempt_count>0
                     AND job.state IN ('preprocessing','stage_n')
                     AND job.lease_expires_at<=?
                     AND NOT EXISTS (
                       SELECT 1
                       FROM automation_session_quality_publication_deadlines root
                       WHERE root.job_id=job.job_id)""",
                (timestamp,),
            ).fetchone()[0]
        )
        reason = AnalysisPublicationDeadlineFailure.DEADLINE_MISSING.value
        connection.execute(
            """UPDATE analysis_jobs SET state='failed',stage_number=NULL,
                   lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                   cancel_requested=0,last_error_code=?,terminal_reason_code=?,
                   terminal_at=?,updated_at=?
               WHERE kind='session_quality' AND automation_grant_id IS NOT NULL
                 AND attempt_count>0
                 AND state IN ('queued','preprocessing','stage_n','awaiting_approval')
                 AND NOT EXISTS (
                   SELECT 1
                   FROM automation_session_quality_publication_deadlines root
                   WHERE root.job_id=analysis_jobs.job_id)""",
            (reason, reason, timestamp, timestamp),
        )
        return expired_active

    def _insert_root_locked(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        now: datetime,
    ) -> None:
        grant = connection.execute(
            """SELECT grant.revision,job.automation_grant_id
               FROM analysis_jobs job
               JOIN automation_grants grant
                 ON grant.grant_id=job.automation_grant_id
               WHERE job.job_id=? AND job.kind='session_quality'
                 AND job.automation_grant_id IS NOT NULL""",
            (job_id,),
        ).fetchone()
        if grant is None:
            return
        first_us = to_epoch_us(now)
        deadline_us = to_epoch_us(now + _PUBLICATION_BUDGET)

        def insert() -> None:
            connection.execute(
                """INSERT INTO automation_session_quality_publication_deadlines(
                       job_id,automation_grant_id,grant_revision,
                       first_claim_at_us,deadline_at_us,high_water_at_us,
                       first_claim_at,deadline_at,high_water_at,analysis_run_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    job_id,
                    grant["automation_grant_id"],
                    grant["revision"],
                    first_us,
                    deadline_us,
                    first_us,
                    to_iso(now),
                    to_iso(now + _PUBLICATION_BUDGET),
                    to_iso(now),
                ),
            )

        self._authorized_publication_write(
            connection,
            job_id=job_id,
            action="root",
            callback=insert,
        )

    def _advance_high_water_locked(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        observed_us: int,
    ) -> None:
        root = connection.execute(
            """SELECT high_water_at_us,deadline_at_us
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (job_id,),
        ).fetchone()
        if root is None:
            return
        if not int(root["high_water_at_us"]) < observed_us < int(
            root["deadline_at_us"]
        ):
            return

        def update() -> None:
            connection.execute(
                """UPDATE automation_session_quality_publication_deadlines
                   SET high_water_at_us=?,high_water_at=? WHERE job_id=?""",
                (observed_us, to_iso(from_epoch_us(observed_us)), job_id),
            )

        self._authorized_publication_write(
            connection,
            job_id=job_id,
            action="high_water",
            callback=update,
        )

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset cannot be negative")

    @staticmethod
    def _validate_lease_duration(value: timedelta) -> timedelta:
        if not timedelta(seconds=5) <= value <= timedelta(minutes=10):
            raise ValueError("lease duration must be between five seconds and ten minutes")
        return value

    @staticmethod
    def _validate_progress(completed: int, total: int) -> None:
        if (
            isinstance(completed, bool)
            or not isinstance(completed, int)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or not 0 <= completed <= total <= 1_000_000
            or total < 1
        ):
            raise ValueError("job progress is outside the reviewed bound")

    def enqueue(self, draft: AnalysisJobDraft) -> AnalysisJobEnqueueResult:
        self._ensure_initialized()
        if draft.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
            raise DatabaseInvariantError(
                "estimator execution requires the atomic runtime launch boundary"
            )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing_row = connection.execute(
                    "SELECT * FROM analysis_jobs WHERE dedupe_key = ?",
                    (draft.dedupe_key,),
                ).fetchone()
                if existing_row is not None:
                    existing = self._record(connection, existing_row)
                    if (
                        existing.job_id != draft.job_id
                        or existing.identity != draft.identity
                        or existing.max_attempts != draft.max_attempts
                    ):
                        raise DatabaseInvariantError(
                            "analysis job deduplication identity conflicted"
                        )
                    connection.commit()
                    return AnalysisJobEnqueueResult(job=existing, created=False)

                target = connection.execute(
                    """
                    SELECT s.project_id, s.provider
                    FROM sessions s WHERE s.session_id = ?
                    """,
                    (draft.identity.session_id,),
                ).fetchone()
                if target is None:
                    raise DatabaseInvariantError("analysis job session does not exist")
                if (
                    target["project_id"] != draft.identity.project_id
                    or target["provider"] != draft.identity.provider.value
                ):
                    raise DatabaseInvariantError(
                        "analysis job target provenance does not match the safe index"
                    )
                identity = draft.identity
                timestamp = to_iso(draft.created_at)
                connection.execute(
                    """
                    INSERT INTO analysis_jobs(
                        job_id, dedupe_key, kind, provider, project_id, session_id,
                        input_fingerprint, provenance_fingerprint,
                        estimator_plan_version, redactor_version,
                        provider_schema_version, automation_grant_id, local_only,
                        state, stage_number,
                        progress_completed, progress_total, attempt_count,
                        max_attempts, available_at, cancel_requested, lease_owner,
                        lease_token, lease_expires_at, last_error_code,
                        terminal_reason_code, created_at, updated_at, terminal_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'queued', NULL,
                        0, 1, 0, ?, ?, 0, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL
                    )
                    """,
                    (
                        draft.job_id,
                        draft.dedupe_key,
                        identity.kind.value,
                        identity.provider.value,
                        identity.project_id,
                        identity.session_id,
                        identity.input_fingerprint,
                        identity.provenance_fingerprint,
                        identity.estimator_plan_version,
                        identity.redactor_version,
                        identity.provider_schema_version,
                        identity.automation_grant_id,
                        draft.max_attempts,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO analysis_job_metrics(job_id, metric_key, ordinal)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (draft.job_id, metric_key, ordinal)
                        for ordinal, metric_key in enumerate(identity.metric_keys)
                    ),
                )
                created = self._get_locked(connection, draft.job_id)
                if created is None:
                    raise DatabaseInvariantError("analysis job enqueue failed")
                connection.commit()
                return AnalysisJobEnqueueResult(job=created, created=True)
            except Exception:
                connection.rollback()
                raise

    def get(self, job_id: str) -> AnalysisJobRecord | None:
        self._ensure_initialized()
        require_safe_id(job_id)
        with self._connection_scope(readonly=True) as connection:
            return self._get_locked(connection, job_id)

    def list(
        self,
        *,
        state: AnalysisJobState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AnalysisJobPage:
        self._ensure_initialized()
        self._validate_page(limit, offset)
        with self._connection_scope(readonly=True) as connection:
            if state is None:
                rows = connection.execute(
                    """
                    SELECT * FROM analysis_jobs
                    ORDER BY created_at DESC, job_id DESC LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM analysis_jobs WHERE state = ?
                    ORDER BY created_at DESC, job_id DESC LIMIT ? OFFSET ?
                    """,
                    (state.value, limit, offset),
                ).fetchall()
            jobs = tuple(self._record(connection, row) for row in rows)
        return AnalysisJobPage(jobs=jobs, limit=limit, offset=offset)

    def list_active(self, *, limit: int = 100) -> AnalysisJobPage:
        self._ensure_initialized()
        self._validate_page(limit, 0)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM analysis_jobs
                WHERE state NOT IN (
                    'completed', 'partial', 'failed', 'cancelled', 'superseded'
                )
                ORDER BY created_at, job_id LIMIT ?
                """,
                (limit,),
            ).fetchall()
            jobs = tuple(self._record(connection, row) for row in rows)
        return AnalysisJobPage(jobs=jobs, limit=limit, offset=0)

    def get_latest_for_session(self, session_id: str) -> AnalysisJobRecord | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM analysis_jobs WHERE session_id = ?
                ORDER BY created_at DESC, job_id DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return None if row is None else self._record(connection, row)

    def _recover_expired_locked(
        self,
        connection: sqlite3.Connection,
        *,
        now: datetime,
    ) -> AnalysisJobRecoveryResult:
        self._reconcile_all_completed_publications_locked(connection, now=now)
        missing_failed = self._reconcile_missing_publication_roots_locked(
            connection, now=now
        )
        timestamp = to_iso(now)
        rows = connection.execute(
            """
            SELECT job_id, attempt_count, max_attempts, cancel_requested,
                   last_error_code
            FROM analysis_jobs
            WHERE state IN ('preprocessing', 'stage_n')
              AND kind <> 'estimator_execution'
              AND lease_expires_at <= ?
            ORDER BY lease_expires_at, job_id
            """,
            (timestamp,),
        ).fetchall()
        requeued = cancelled = superseded = 0
        failed = missing_failed
        for row in rows:
            if bool(row["cancel_requested"]):
                reason = row["last_error_code"] or "cancellation_requested"
                state = (
                    AnalysisJobState.SUPERSEDED
                    if reason in {"input_changed", "provenance_changed"}
                    else AnalysisJobState.CANCELLED
                )
                terminal_at = timestamp
                available_at = timestamp
                if state is AnalysisJobState.CANCELLED:
                    cancelled += 1
                else:
                    superseded += 1
            elif row["attempt_count"] >= row["max_attempts"]:
                state = AnalysisJobState.FAILED
                reason = "lease_expired"
                terminal_at = timestamp
                available_at = timestamp
                failed += 1
            else:
                state = AnalysisJobState.QUEUED
                reason = None
                terminal_at = None
                available_at = to_iso(
                    now + self._retry_delay(int(row["attempt_count"]))
                )
                requeued += 1
            connection.execute(
                """
                UPDATE analysis_jobs SET
                    state = ?, stage_number = NULL, available_at = ?,
                    lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, last_error_code = 'lease_expired',
                    terminal_reason_code = ?, terminal_at = ?, updated_at = ?
                WHERE job_id = ? AND state IN ('preprocessing', 'stage_n')
                """,
                (
                    state.value,
                    available_at,
                    reason,
                    terminal_at,
                    timestamp,
                    row["job_id"],
                ),
            )
        return AnalysisJobRecoveryResult(
            requeued=requeued,
            cancelled=cancelled,
            failed=failed,
            superseded=superseded,
        )

    @staticmethod
    def _reconcile_ineligible_automation_jobs_locked(
        connection: sqlite3.Connection,
        *,
        now: datetime,
    ) -> None:
        """Fail closed stale/unsupported non-runtime automation queue work.

        Estimator executions have a separate append-only runtime sealing
        boundary and are deliberately excluded from this generic maintenance.
        """

        SqliteAnalysisJobRepository._reconcile_all_completed_publications_locked(
            connection, now=now
        )
        timestamp = to_iso(now)
        metric_mismatch = """
            EXISTS (
              SELECT metric_key, ordinal FROM analysis_job_metrics
              WHERE job_id = analysis_jobs.job_id
              EXCEPT
              SELECT metric_key, ordinal FROM automation_grant_metrics
              WHERE grant_id = analysis_jobs.automation_grant_id
            )
            OR EXISTS (
              SELECT metric_key, ordinal FROM automation_grant_metrics
              WHERE grant_id = analysis_jobs.automation_grant_id
              EXCEPT
              SELECT metric_key, ordinal FROM analysis_job_metrics
              WHERE job_id = analysis_jobs.job_id
            )
        """
        reasons_and_conditions = (
            (
                "automation_grant_not_found",
                "NOT EXISTS (SELECT 1 FROM automation_grants AS grant "
                "WHERE grant.grant_id = analysis_jobs.automation_grant_id)",
                (),
            ),
            (
                "automation_grant_inactive",
                "EXISTS (SELECT 1 FROM automation_grants AS grant "
                "WHERE grant.grant_id = analysis_jobs.automation_grant_id "
                "AND grant.state = 'revoked')",
                (),
            ),
            (
                "automation_grant_expired",
                "EXISTS (SELECT 1 FROM automation_grants AS grant "
                "WHERE grant.grant_id = analysis_jobs.automation_grant_id "
                "AND (grant.state = 'expired' OR (grant.state = 'active' "
                "AND grant.expires_at <= ?)))",
                (timestamp,),
            ),
            (
                "automation_resource_policy_unsupported",
                "EXISTS (SELECT 1 FROM automation_grants AS grant "
                "WHERE grant.grant_id = analysis_jobs.automation_grant_id "
                "AND grant.state = 'active' AND grant.expires_at > ? AND ("
                "grant.route <> 'balanced' OR grant.max_gpu_workers <> 1 OR "
                "grant.max_cpu_workers <> 1 OR grant.pause_on_battery <> 1 OR "
                "grant.maximum_session_seconds <> 1800))",
                (timestamp,),
            ),
            (
                "automation_grant_scope_mismatch",
                "EXISTS (SELECT 1 FROM automation_grants AS grant "
                "WHERE grant.grant_id = analysis_jobs.automation_grant_id "
                "AND grant.state = 'active' AND grant.expires_at > ? "
                "AND grant.route = 'balanced' AND grant.max_gpu_workers = 1 "
                "AND grant.max_cpu_workers = 1 AND grant.pause_on_battery = 1 "
                "AND grant.maximum_session_seconds = 1800 AND ("
                "analysis_jobs.kind <> 'session_quality' OR "
                "grant.local_only <> 1 OR "
                "grant.remote_requires_fresh_approval <> 1 OR "
                "grant.provider <> analysis_jobs.provider OR "
                "grant.project_id <> analysis_jobs.project_id OR "
                f"{metric_mismatch}))",
                (timestamp,),
            ),
        )
        for reason, condition, parameters in reasons_and_conditions:
            connection.execute(
                f"""
                UPDATE analysis_jobs SET
                    state = 'cancelled', stage_number = NULL,
                    cancel_requested = 1, last_error_code = ?,
                    terminal_reason_code = ?, terminal_at = ?, updated_at = ?
                WHERE automation_grant_id IS NOT NULL
                  AND kind <> 'estimator_execution'
                  AND state IN ('queued', 'awaiting_approval')
                  AND ({condition})
                """,
                (reason, reason, timestamp, timestamp, *parameters),
            )
            connection.execute(
                f"""
                UPDATE analysis_jobs SET
                    cancel_requested = 1, last_error_code = ?, updated_at = ?
                WHERE automation_grant_id IS NOT NULL
                  AND kind <> 'estimator_execution'
                  AND state IN ('preprocessing', 'stage_n')
                  AND ({condition})
                """,
                (reason, timestamp, *parameters),
            )

    def recover_expired(self, *, now: datetime) -> AnalysisJobRecoveryResult:
        self._ensure_initialized()
        now = require_utc(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                result = self._recover_expired_locked(connection, now=now)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def claim_next(
        self,
        *,
        owner: str,
        token: str,
        now: datetime,
        lease_duration: timedelta,
        power_source: PowerSourceState = PowerSourceState.UNKNOWN,
    ) -> AnalysisJobRecord | None:
        self._ensure_initialized()
        require_safe_id(owner)
        require_safe_id(token)
        now = require_utc(now)
        lease_duration = self._validate_lease_duration(lease_duration)
        if not isinstance(power_source, PowerSourceState):
            raise ValueError("power source state is invalid")
        timestamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._recover_expired_locked(connection, now=now)
                self._reconcile_ineligible_automation_jobs_locked(
                    connection,
                    now=now,
                )
                row = connection.execute(
                    """
                    SELECT queued.job_id
                    FROM analysis_jobs AS queued
                    LEFT JOIN automation_grants AS grant
                      ON grant.grant_id = queued.automation_grant_id
                    WHERE queued.state = 'queued'
                      AND queued.cancel_requested = 0
                      AND queued.available_at <= ?
                      AND (
                        queued.automation_grant_id IS NULL
                        OR (
                          grant.state = 'active'
                          AND grant.expires_at > ?
                          AND grant.route = 'balanced'
                          AND grant.max_gpu_workers = 1
                          AND grant.max_cpu_workers = 1
                          AND grant.pause_on_battery = 1
                          AND grant.maximum_session_seconds = 1800
                          AND grant.local_only = 1
                          AND grant.remote_requires_fresh_approval = 1
                          AND queued.kind IN (
                            'session_quality', 'estimator_execution'
                          )
                          AND grant.provider = queued.provider
                          AND grant.project_id = queued.project_id
                          AND NOT EXISTS (
                            SELECT metric_key, ordinal
                            FROM analysis_job_metrics
                            WHERE job_id = queued.job_id
                            EXCEPT
                            SELECT metric_key, ordinal
                            FROM automation_grant_metrics
                            WHERE grant_id = grant.grant_id
                          )
                          AND NOT EXISTS (
                            SELECT metric_key, ordinal
                            FROM automation_grant_metrics
                            WHERE grant_id = grant.grant_id
                            EXCEPT
                            SELECT metric_key, ordinal
                            FROM analysis_job_metrics
                            WHERE job_id = queued.job_id
                          )
                          AND ? = 'external_power'
                        )
                      )
                      AND (
                        queued.automation_grant_id IS NULL
                        OR NOT EXISTS (
                          SELECT 1 FROM analysis_jobs AS active
                          WHERE active.automation_grant_id =
                                queued.automation_grant_id
                            AND active.state IN ('preprocessing', 'stage_n')
                            AND active.lease_expires_at > ?
                        )
                      )
                    ORDER BY queued.available_at, queued.created_at,
                             queued.job_id
                    LIMIT 1
                    """,
                    (timestamp, timestamp, power_source.value, timestamp),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                expires_at = now + lease_duration
                cursor = connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = 'preprocessing', stage_number = NULL,
                        attempt_count = attempt_count + 1,
                        lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                        updated_at = ?, terminal_reason_code = NULL,
                        terminal_at = NULL
                    WHERE job_id = ? AND state = 'queued'
                      AND cancel_requested = 0 AND available_at <= ?
                    """,
                    (
                        owner,
                        token,
                        to_iso(expires_at),
                        timestamp,
                        row["job_id"],
                        timestamp,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError("analysis job claim conflicted")
                claimed_row = connection.execute(
                    "SELECT kind,automation_grant_id,attempt_count FROM analysis_jobs "
                    "WHERE job_id=?",
                    (row["job_id"],),
                ).fetchone()
                if (
                    claimed_row is not None
                    and claimed_row["kind"] == "session_quality"
                    and claimed_row["automation_grant_id"] is not None
                ):
                    root = connection.execute(
                        """SELECT 1
                           FROM automation_session_quality_publication_deadlines
                           WHERE job_id=?""",
                        (row["job_id"],),
                    ).fetchone()
                    if root is None:
                        if int(claimed_row["attempt_count"]) != 1:
                            connection.execute(
                                """UPDATE analysis_jobs SET state='failed',
                                   stage_number=NULL,lease_owner=NULL,
                                   lease_token=NULL,lease_expires_at=NULL,
                                   last_error_code=?,terminal_reason_code=?,
                                   terminal_at=?,updated_at=? WHERE job_id=?""",
                                (
                                    AnalysisPublicationDeadlineFailure.DEADLINE_MISSING.value,
                                    AnalysisPublicationDeadlineFailure.DEADLINE_MISSING.value,
                                    timestamp,
                                    timestamp,
                                    row["job_id"],
                                ),
                            )
                        else:
                            self._insert_root_locked(
                                connection, job_id=row["job_id"], now=now
                            )
                    else:
                        checked = self._check_or_close_publication_locked(
                            connection,
                            job_id=row["job_id"],
                            now=now,
                        )
                        if checked:
                            connection.commit()
                            return self._get_locked(connection, row["job_id"])
                claimed = self._get_locked(connection, row["job_id"])
                if claimed is None:
                    raise DatabaseInvariantError("claimed analysis job disappeared")
                connection.commit()
                return claimed
            except Exception:
                connection.rollback()
                raise

    def _close_publication_locked(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        now: datetime,
        failure: AnalysisPublicationDeadlineFailure,
        monotonic: bool,
    ) -> None:
        if self._reconcile_completed_publication_locked(
            connection, job_id=job_id, now=now
        ):
            return
        root = connection.execute(
            """SELECT first_claim_at_us,deadline_at_us,high_water_at_us,
                      analysis_run_id
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (job_id,),
        ).fetchone()
        timestamp = to_iso(now)
        if root is None:
            if failure is not AnalysisPublicationDeadlineFailure.DEADLINE_MISSING:
                raise DatabaseInvariantError(
                    "automation publication deadline root is missing"
                )
            connection.execute(
                """UPDATE analysis_jobs SET state='failed',stage_number=NULL,
                   lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                   last_error_code=?,terminal_reason_code=?,terminal_at=?,updated_at=?
                   WHERE job_id=? AND kind='session_quality'
                     AND automation_grant_id IS NOT NULL
                     AND state IN ('queued','preprocessing','stage_n')""",
                (failure.value, failure.value, timestamp, timestamp, job_id),
            )
            return
        now_us = to_epoch_us(now)
        high_water_us = int(root["high_water_at_us"])
        deadline_us = int(root["deadline_at_us"])
        if failure is AnalysisPublicationDeadlineFailure.DEADLINE_MISSING:
            raise DatabaseInvariantError(
                "automation publication deadline root already exists"
            )
        if failure is AnalysisPublicationDeadlineFailure.DEADLINE_EXCEEDED:
            observation_kind = (
                "monotonic_deadline_exceeded"
                if monotonic
                else "wall_deadline_exceeded"
            )
            effective_us = max(now_us, deadline_us) if monotonic else now_us
            if not monotonic and now_us < deadline_us:
                raise DatabaseInvariantError(
                    "wall deadline failure was reported before its cutoff"
                )
        else:
            observation_kind = (
                "monotonic_clock_regressed"
                if monotonic
                else "wall_clock_regressed"
            )
            effective_us = high_water_us
            if not monotonic and now_us >= high_water_us:
                raise DatabaseInvariantError(
                    "wall clock regression was not observed"
                )
        terminal_timestamp = to_iso(from_epoch_us(effective_us))

        def close() -> None:
            connection.execute(
                """INSERT INTO automation_session_quality_publication_closures(
                       job_id,reason_code,observation_kind,observed_at_us,
                       effective_high_water_at_us
                   ) VALUES(?,?,?,?,?)""",
                (job_id, failure.value, observation_kind, now_us, effective_us),
            )

        self._authorized_publication_write(
            connection, job_id=job_id, action="close", callback=close
        )
        run_id = root["analysis_run_id"]
        if run_id is not None:
            run = connection.execute(
                "SELECT started_at FROM session_analysis_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            run_terminal_timestamp = terminal_timestamp
            if run is not None:
                started_at = from_iso(run["started_at"])
                if started_at is not None and to_epoch_us(started_at) > effective_us:
                    run_terminal_timestamp = to_iso(started_at)
            connection.execute(
                """UPDATE session_analysis_runs
                   SET finished_at=?,status='failed',failure_code=?
                   WHERE run_id=? AND status='running'
                     AND NOT EXISTS(
                       SELECT 1 FROM session_analysis_results WHERE run_id=?
                     )""",
                (run_terminal_timestamp, failure.value, run_id, run_id),
            )
        connection.execute(
            """UPDATE analysis_jobs SET state='failed',stage_number=NULL,
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
               last_error_code=?,terminal_reason_code=?,terminal_at=?,updated_at=?
               WHERE job_id=? AND state IN ('queued','preprocessing','stage_n')""",
            (
                failure.value,
                failure.value,
                terminal_timestamp,
                terminal_timestamp,
                job_id,
            ),
        )

    def _check_or_close_publication_locked(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        now: datetime,
    ) -> bool:
        if self._reconcile_completed_publication_locked(
            connection, job_id=job_id, now=now
        ):
            return True
        root = connection.execute(
            """SELECT deadline_at_us,high_water_at_us
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (job_id,),
        ).fetchone()
        if root is None:
            self._close_publication_locked(
                connection,
                job_id=job_id,
                now=now,
                failure=AnalysisPublicationDeadlineFailure.DEADLINE_MISSING,
                monotonic=False,
            )
            return True
        now_us = to_epoch_us(now)
        if now_us < int(root["high_water_at_us"]):
            self._close_publication_locked(
                connection,
                job_id=job_id,
                now=now,
                failure=AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED,
                monotonic=False,
            )
            return True
        if now_us >= int(root["deadline_at_us"]):
            self._close_publication_locked(
                connection,
                job_id=job_id,
                now=now,
                failure=AnalysisPublicationDeadlineFailure.DEADLINE_EXCEEDED,
                monotonic=False,
            )
            return True
        self._advance_high_water_locked(
            connection, job_id=job_id, observed_us=now_us
        )
        return False

    def check_publication_deadline(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                scope = connection.execute(
                    """SELECT 1 FROM analysis_jobs WHERE job_id=?
                       AND kind='session_quality'
                       AND automation_grant_id IS NOT NULL""",
                    (lease.job_id,),
                ).fetchone()
                if scope is None:
                    raise DatabaseInvariantError(
                        "analysis job has no automation publication deadline"
                    )
                row = connection.execute(
                    """SELECT * FROM analysis_jobs WHERE job_id=?
                       AND lease_owner=? AND lease_token=?
                       AND state IN ('preprocessing','stage_n')
                       AND lease_expires_at>?""",
                    (lease.job_id, lease.owner, lease.token, to_iso(now)),
                ).fetchone()
                if row is None:
                    terminal = self._get_locked(connection, lease.job_id)
                    if terminal is None or terminal.state not in (
                        TERMINAL_ANALYSIS_JOB_STATES
                    ):
                        raise DatabaseInvariantError(
                            "analysis job lease is unavailable"
                        )
                    connection.commit()
                    return terminal
                self._check_or_close_publication_locked(
                    connection, job_id=lease.job_id, now=now
                )
                result = self._get_locked(connection, lease.job_id)
                if result is None:
                    raise DatabaseInvariantError("analysis job disappeared")
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def fail_publication_deadline(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        failure: AnalysisPublicationDeadlineFailure,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        if not isinstance(failure, AnalysisPublicationDeadlineFailure):
            raise ValueError("publication deadline failure is invalid")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                scope = connection.execute(
                    """SELECT 1 FROM analysis_jobs WHERE job_id=?
                       AND kind='session_quality'
                       AND automation_grant_id IS NOT NULL""",
                    (lease.job_id,),
                ).fetchone()
                if scope is None:
                    raise DatabaseInvariantError(
                        "analysis job has no automation publication deadline"
                    )
                row = connection.execute(
                    """SELECT 1 FROM analysis_jobs WHERE job_id=?
                       AND lease_owner=? AND lease_token=?
                       AND state IN ('preprocessing','stage_n')
                       AND lease_expires_at>?""",
                    (lease.job_id, lease.owner, lease.token, to_iso(now)),
                ).fetchone()
                if row is None:
                    terminal = self._get_locked(connection, lease.job_id)
                    if terminal is None or terminal.state not in (
                        TERMINAL_ANALYSIS_JOB_STATES
                    ):
                        raise DatabaseInvariantError(
                            "analysis job lease is unavailable"
                        )
                    connection.commit()
                    return terminal
                self._close_publication_locked(
                    connection,
                    job_id=lease.job_id,
                    now=now,
                    failure=failure,
                    monotonic=(
                        failure is not AnalysisPublicationDeadlineFailure.DEADLINE_MISSING
                    ),
                )
                terminal = self._get_locked(connection, lease.job_id)
                if terminal is None:
                    raise DatabaseInvariantError("analysis job disappeared")
                connection.commit()
                return terminal
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _active_row_for_lease(
        connection: sqlite3.Connection,
        lease: AnalysisJobLease,
        now: datetime,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM analysis_jobs
            WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
              AND state IN ('preprocessing', 'stage_n')
              AND lease_expires_at > ?
            """,
            (lease.job_id, lease.owner, lease.token, to_iso(now)),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("analysis job lease is unavailable")
        return row

    def renew(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        lease_duration = self._validate_lease_duration(lease_duration)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if self._reconcile_completed_publication_locked(
                    connection, job_id=lease.job_id, now=now
                ):
                    completed = self._get_locked(connection, lease.job_id)
                    assert completed is not None
                    connection.commit()
                    return completed
                self._active_row_for_lease(connection, lease, now)
                connection.execute(
                    """
                    UPDATE analysis_jobs SET lease_expires_at = ?, updated_at = ?
                    WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                    """,
                    (
                        to_iso(now + lease_duration),
                        to_iso(now),
                        lease.job_id,
                        lease.owner,
                        lease.token,
                    ),
                )
                renewed = self._get_locked(connection, lease.job_id)
                if renewed is None:
                    raise DatabaseInvariantError("analysis job renewal failed")
                connection.commit()
                return renewed
            except Exception:
                connection.rollback()
                raise

    def advance_stage(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        stage_number: int,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        self._validate_progress(progress_completed, progress_total)
        if isinstance(stage_number, bool) or not isinstance(stage_number, int):
            raise ValueError("stage number is invalid")
        if not 1 <= stage_number <= 32:
            raise ValueError("stage number is outside the reviewed bound")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if self._reconcile_completed_publication_locked(
                    connection, job_id=lease.job_id, now=now
                ):
                    completed = self._get_locked(connection, lease.job_id)
                    assert completed is not None
                    connection.commit()
                    return completed
                row = self._active_row_for_lease(connection, lease, now)
                previous = row["stage_number"]
                if previous is not None and stage_number < previous:
                    raise DatabaseInvariantError("analysis job stage cannot move backward")
                connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = 'stage_n', stage_number = ?,
                        progress_completed = ?, progress_total = ?, updated_at = ?
                    WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                    """,
                    (
                        stage_number,
                        progress_completed,
                        progress_total,
                        to_iso(now),
                        lease.job_id,
                        lease.owner,
                        lease.token,
                    ),
                )
                updated = self._get_locked(connection, lease.job_id)
                if updated is None:
                    raise DatabaseInvariantError("analysis job stage update failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise

    def await_approval(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        reason_code: str,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        require_safe_label(reason_code)
        self._validate_progress(progress_completed, progress_total)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if self._reconcile_completed_publication_locked(
                    connection, job_id=lease.job_id, now=now
                ):
                    completed = self._get_locked(connection, lease.job_id)
                    assert completed is not None
                    connection.commit()
                    return completed
                self._active_row_for_lease(connection, lease, now)
                connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = 'awaiting_approval', stage_number = NULL,
                        progress_completed = ?, progress_total = ?,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, last_error_code = ?, updated_at = ?
                    WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                    """,
                    (
                        progress_completed,
                        progress_total,
                        reason_code,
                        to_iso(now),
                        lease.job_id,
                        lease.owner,
                        lease.token,
                    ),
                )
                updated = self._get_locked(connection, lease.job_id)
                if updated is None:
                    raise DatabaseInvariantError("analysis job approval wait failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise

    def resume_after_approval(
        self,
        job_id: str,
        *,
        now: datetime,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        require_safe_id(job_id)
        now = require_utc(now)
        timestamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if self._reconcile_completed_publication_locked(
                    connection, job_id=job_id, now=now
                ):
                    completed = self._get_locked(connection, job_id)
                    assert completed is not None
                    connection.commit()
                    return completed
                current = self._get_locked(connection, job_id)
                if current is None:
                    raise DatabaseInvariantError("analysis job does not exist")
                if current.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
                    raise DatabaseInvariantError(
                        "estimator execution approval requires its runtime boundary"
                    )
                cursor = connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = 'queued', available_at = ?,
                        last_error_code = NULL, updated_at = ?
                    WHERE job_id = ? AND state = 'awaiting_approval'
                      AND cancel_requested = 0
                    """,
                    (timestamp, timestamp, job_id),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError(
                        "analysis job is not awaiting approval"
                    )
                updated = self._get_locked(connection, job_id)
                if updated is None:
                    raise DatabaseInvariantError("analysis job approval resume failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise

    def request_cancel(self, job_id: str, *, now: datetime) -> AnalysisJobRecord:
        self._ensure_initialized()
        require_safe_id(job_id)
        now = require_utc(now)
        timestamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._reconcile_completed_publication_locked(
                    connection, job_id=job_id, now=now
                )
                current = self._get_locked(connection, job_id)
                if current is None:
                    raise DatabaseInvariantError("analysis job does not exist")
                if current.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
                    raise DatabaseInvariantError(
                        "estimator execution cancellation requires its runtime boundary"
                    )
                if current.state in TERMINAL_ANALYSIS_JOB_STATES:
                    connection.commit()
                    return current
                if current.state in {
                    AnalysisJobState.QUEUED,
                    AnalysisJobState.AWAITING_APPROVAL,
                }:
                    connection.execute(
                        """
                        UPDATE analysis_jobs SET
                            state = 'cancelled', stage_number = NULL,
                            cancel_requested = 1, terminal_reason_code = ?,
                            terminal_at = ?, updated_at = ?
                        WHERE job_id = ?
                        """,
                        ("cancellation_requested", timestamp, timestamp, job_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE analysis_jobs SET cancel_requested = 1,
                            last_error_code = 'cancellation_requested', updated_at = ?
                        WHERE job_id = ?
                        """,
                        (timestamp, job_id),
                    )
                updated = self._get_locked(connection, job_id)
                if updated is None:
                    raise DatabaseInvariantError("analysis job cancellation failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise

    def cancel_by_automation_grant(
        self,
        automation_grant_id: str,
        *,
        now: datetime,
    ) -> AnalysisJobCancellationBatchResult:
        self._ensure_initialized()
        require_safe_id(automation_grant_id)
        now = require_utc(now)
        reason_code = "automation_grant_revoked"
        timestamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._reconcile_all_completed_publications_locked(
                    connection, now=now
                )
                if connection.execute(
                    """
                    SELECT 1 FROM analysis_jobs
                    WHERE automation_grant_id=? AND kind='estimator_execution'
                      AND state NOT IN (
                          'completed','partial','failed','cancelled','superseded'
                      ) LIMIT 1
                    """,
                    (automation_grant_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError(
                        "estimator execution grant revocation requires its runtime boundary"
                    )
                cancelled = connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = 'cancelled', stage_number = NULL,
                        cancel_requested = 1,
                        last_error_code = ?,
                        terminal_reason_code = ?,
                        terminal_at = ?, updated_at = ?
                    WHERE automation_grant_id = ?
                      AND state IN ('queued', 'awaiting_approval')
                    """,
                    (
                        reason_code,
                        reason_code,
                        timestamp,
                        timestamp,
                        automation_grant_id,
                    ),
                ).rowcount
                requested = connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        cancel_requested = 1,
                        last_error_code = ?,
                        updated_at = ?
                    WHERE automation_grant_id = ?
                      AND state IN ('preprocessing', 'stage_n')
                    """,
                    (reason_code, timestamp, automation_grant_id),
                ).rowcount
                connection.commit()
                return AnalysisJobCancellationBatchResult(
                    cancelled=cancelled,
                    cancellation_requested=requested,
                )
            except Exception:
                connection.rollback()
                raise

    def supersede(
        self,
        job_id: str,
        *,
        now: datetime,
        reason_code: str,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        require_safe_id(job_id)
        now = require_utc(now)
        require_safe_label(reason_code)
        timestamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._reconcile_completed_publication_locked(
                    connection, job_id=job_id, now=now
                )
                current = self._get_locked(connection, job_id)
                if current is None:
                    raise DatabaseInvariantError("analysis job does not exist")
                if current.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
                    raise DatabaseInvariantError(
                        "estimator execution supersession requires its runtime boundary"
                    )
                if current.state in TERMINAL_ANALYSIS_JOB_STATES:
                    connection.commit()
                    return current
                if current.state in {
                    AnalysisJobState.QUEUED,
                    AnalysisJobState.AWAITING_APPROVAL,
                }:
                    connection.execute(
                        """
                        UPDATE analysis_jobs SET
                            state = 'superseded', stage_number = NULL,
                            cancel_requested = 1, last_error_code = ?,
                            terminal_reason_code = ?, terminal_at = ?, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (reason_code, reason_code, timestamp, timestamp, job_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE analysis_jobs SET cancel_requested = 1,
                            last_error_code = ?, updated_at = ? WHERE job_id = ?
                        """,
                        (reason_code, timestamp, job_id),
                    )
                updated = self._get_locked(connection, job_id)
                if updated is None:
                    raise DatabaseInvariantError("analysis job supersession failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise

    def finish(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        state: AnalysisJobState,
        reason_code: str,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        require_safe_label(reason_code)
        self._validate_progress(progress_completed, progress_total)
        if state not in TERMINAL_ANALYSIS_JOB_STATES:
            raise ValueError("analysis job finish requires a terminal state")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if self._reconcile_completed_publication_locked(
                    connection, job_id=lease.job_id, now=now
                ):
                    completed = self._get_locked(connection, lease.job_id)
                    assert completed is not None
                    connection.commit()
                    return completed
                row = self._active_row_for_lease(connection, lease, now)
                if bool(row["cancel_requested"]):
                    reason_code = row["last_error_code"] or "cancellation_requested"
                    state = (
                        AnalysisJobState.SUPERSEDED
                        if reason_code in {"input_changed", "provenance_changed"}
                        else AnalysisJobState.CANCELLED
                    )
                timestamp = to_iso(now)
                connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = ?, stage_number = NULL,
                        progress_completed = ?, progress_total = ?,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, terminal_reason_code = ?,
                        terminal_at = ?, updated_at = ?
                    WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                    """,
                    (
                        state.value,
                        progress_completed,
                        progress_total,
                        reason_code,
                        timestamp,
                        timestamp,
                        lease.job_id,
                        lease.owner,
                        lease.token,
                    ),
                )
                terminal = self._get_locked(connection, lease.job_id)
                if terminal is None:
                    raise DatabaseInvariantError("analysis job completion failed")
                connection.commit()
                return terminal
            except Exception:
                connection.rollback()
                raise

    def retry_or_fail(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        error_code: str,
        retryable: bool,
    ) -> AnalysisJobRecord:
        self._ensure_initialized()
        now = require_utc(now)
        require_safe_label(error_code)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if self._reconcile_completed_publication_locked(
                    connection, job_id=lease.job_id, now=now
                ):
                    completed = self._get_locked(connection, lease.job_id)
                    assert completed is not None
                    connection.commit()
                    return completed
                row = self._active_row_for_lease(connection, lease, now)
                timestamp = to_iso(now)
                if bool(row["cancel_requested"]):
                    reason = row["last_error_code"] or "cancellation_requested"
                    state = (
                        AnalysisJobState.SUPERSEDED
                        if reason in {"input_changed", "provenance_changed"}
                        else AnalysisJobState.CANCELLED
                    )
                    terminal_at = timestamp
                    available_at = timestamp
                elif retryable and row["attempt_count"] < row["max_attempts"]:
                    state = AnalysisJobState.QUEUED
                    reason = None
                    terminal_at = None
                    available_at = to_iso(
                        now + self._retry_delay(int(row["attempt_count"]))
                    )
                else:
                    state = AnalysisJobState.FAILED
                    reason = error_code
                    terminal_at = timestamp
                    available_at = timestamp
                connection.execute(
                    """
                    UPDATE analysis_jobs SET
                        state = ?, stage_number = NULL, available_at = ?,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, last_error_code = ?,
                        terminal_reason_code = ?, terminal_at = ?, updated_at = ?
                    WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                    """,
                    (
                        state.value,
                        available_at,
                        error_code,
                        reason,
                        terminal_at,
                        timestamp,
                        lease.job_id,
                        lease.owner,
                        lease.token,
                    ),
                )
                updated = self._get_locked(connection, lease.job_id)
                if updated is None:
                    raise DatabaseInvariantError("analysis job retry transition failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise
