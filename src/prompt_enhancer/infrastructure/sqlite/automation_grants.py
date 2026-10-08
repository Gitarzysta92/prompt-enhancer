"""SQLite persistence for renewable, content-free automation grants."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import sqlite3

from ...application.automation import (
    AutomationGrantDraft,
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantState,
    AutomationResourcePolicy,
    AutomationRoute,
)
from ...database import DatabaseInvariantError
from ...domain import Provider
from ._common import (
    ConnectionScope,
    from_iso,
    require_safe_id,
    require_safe_label,
    require_utc,
    to_iso,
)


class SqliteAutomationGrantRepository:
    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    @staticmethod
    def _metric_keys(
        connection: sqlite3.Connection,
        grant_id: str,
    ) -> tuple[str, ...]:
        return tuple(
            row["metric_key"]
            for row in connection.execute(
                """
                SELECT metric_key FROM automation_grant_metrics
                WHERE grant_id = ? ORDER BY ordinal
                """,
                (grant_id,),
            ).fetchall()
        )

    @classmethod
    def _record(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> AutomationGrantRecord:
        return AutomationGrantRecord(
            grant_id=row["grant_id"],
            revision=row["revision"],
            scope=AutomationGrantScope(
                provider=Provider(row["provider"]),
                project_id=row["project_id"],
                metric_keys=cls._metric_keys(connection, row["grant_id"]),
                newest_session_limit=row["newest_session_limit"],
                check_interval_seconds=row["check_interval_seconds"],
                resource_policy=AutomationResourcePolicy(
                    route=AutomationRoute(row["route"]),
                    max_gpu_workers=row["max_gpu_workers"],
                    max_cpu_workers=row["max_cpu_workers"],
                    pause_on_battery=bool(row["pause_on_battery"]),
                    maximum_session_seconds=row["maximum_session_seconds"],
                ),
                local_only=bool(row["local_only"]),
                remote_requires_fresh_approval=bool(
                    row["remote_requires_fresh_approval"]
                ),
            ),
            state=AutomationGrantState(row["state"]),
            created_at=from_iso(row["created_at"]),
            renewed_at=from_iso(row["renewed_at"]),
            expires_at=from_iso(row["expires_at"]),
            next_check_at=from_iso(row["next_check_at"]),
            last_checked_at=from_iso(row["last_checked_at"]),
            revoked_at=from_iso(row["revoked_at"]),
            last_error_code=row["last_error_code"],
        )

    @classmethod
    def _get_locked(
        cls,
        connection: sqlite3.Connection,
        grant_id: str,
    ) -> AutomationGrantRecord | None:
        row = connection.execute(
            "SELECT * FROM automation_grants WHERE grant_id = ?",
            (grant_id,),
        ).fetchone()
        return None if row is None else cls._record(connection, row)

    def create(self, draft: AutomationGrantDraft) -> AutomationGrantRecord:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE automation_grants
                    SET state = 'expired'
                    WHERE provider = ? AND project_id = ? AND state = 'active'
                      AND expires_at <= ?
                    """,
                    (
                        draft.scope.provider.value,
                        draft.scope.project_id,
                        to_iso(draft.created_at),
                    ),
                )
                project = connection.execute(
                    "SELECT provider FROM projects WHERE project_id = ?",
                    (draft.scope.project_id,),
                ).fetchone()
                if project is None:
                    raise DatabaseInvariantError(
                        "automation grant project does not exist"
                    )
                if project["provider"] != draft.scope.provider.value:
                    raise DatabaseInvariantError(
                        "automation grant provider does not match project"
                    )
                if self._get_locked(connection, draft.grant_id) is not None:
                    raise DatabaseInvariantError("automation grant already exists")
                scope = draft.scope
                resource = scope.resource_policy
                connection.execute(
                    """
                    INSERT INTO automation_grants(
                        grant_id, revision, provider, project_id,
                        newest_session_limit, check_interval_seconds, route,
                        max_gpu_workers, max_cpu_workers, pause_on_battery,
                        maximum_session_seconds, local_only,
                        remote_requires_fresh_approval, state, created_at,
                        renewed_at, expires_at, next_check_at, last_checked_at,
                        revoked_at, last_error_code
                    ) VALUES (
                        ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 'active',
                        ?, ?, ?, ?, NULL, NULL, NULL
                    )
                    """,
                    (
                        draft.grant_id,
                        scope.provider.value,
                        scope.project_id,
                        scope.newest_session_limit,
                        scope.check_interval_seconds,
                        resource.route.value,
                        resource.max_gpu_workers,
                        resource.max_cpu_workers,
                        int(resource.pause_on_battery),
                        resource.maximum_session_seconds,
                        to_iso(draft.created_at),
                        to_iso(draft.created_at),
                        to_iso(draft.expires_at),
                        to_iso(draft.created_at),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO automation_grant_metrics(
                        grant_id, metric_key, ordinal
                    ) VALUES (?, ?, ?)
                    """,
                    (
                        (draft.grant_id, metric_key, ordinal)
                        for ordinal, metric_key in enumerate(scope.metric_keys)
                    ),
                )
                record = self._get_locked(connection, draft.grant_id)
                if record is None:
                    raise DatabaseInvariantError("automation grant insert failed")
                connection.commit()
                return record
            except Exception:
                connection.rollback()
                raise

    def get(self, grant_id: str) -> AutomationGrantRecord | None:
        self._ensure_initialized()
        require_safe_id(grant_id)
        with self._connection_scope(readonly=True) as connection:
            return self._get_locked(connection, grant_id)

    def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[AutomationGrantRecord, ...]:
        self._ensure_initialized()
        now = require_utc(now)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("automation due limit must be between 1 and 100")
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM automation_grants
                WHERE state = 'active'
                  AND expires_at > ?
                  AND next_check_at <= ?
                ORDER BY next_check_at, grant_id
                LIMIT ?
                """,
                (to_iso(now), to_iso(now), limit),
            ).fetchall()
            return tuple(self._record(connection, row) for row in rows)

    def expire_due(self, *, now: datetime) -> int:
        self._ensure_initialized()
        now = require_utc(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    UPDATE automation_grants
                    SET state = 'expired'
                    WHERE state = 'active' AND expires_at <= ?
                    """,
                    (to_iso(now),),
                )
                connection.commit()
                return cursor.rowcount
            except Exception:
                connection.rollback()
                raise

    def list_for_provider(
        self,
        provider: Provider,
        *,
        active_only: bool,
    ) -> tuple[AutomationGrantRecord, ...]:
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            query = "SELECT * FROM automation_grants WHERE provider = ?"
            parameters: tuple[object, ...] = (provider.value,)
            if active_only:
                query += " AND state = 'active'"
            query += " ORDER BY created_at, grant_id"
            rows = connection.execute(query, parameters).fetchall()
            return tuple(self._record(connection, row) for row in rows)

    def renew(self, grant_id: str, *, now: datetime) -> AutomationGrantRecord:
        from ...application.automation import AUTOMATION_GRANT_LIFETIME

        self._ensure_initialized()
        require_safe_id(grant_id)
        now = require_utc(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = self._get_locked(connection, grant_id)
                if current is None:
                    raise DatabaseInvariantError("automation grant does not exist")
                connection.execute(
                    """
                    UPDATE automation_grants
                    SET revision = revision + 1, state = 'active',
                        renewed_at = ?, expires_at = ?, next_check_at = ?,
                        revoked_at = NULL, last_error_code = NULL
                    WHERE grant_id = ?
                    """,
                    (
                        to_iso(now),
                        to_iso(now + AUTOMATION_GRANT_LIFETIME),
                        to_iso(now),
                        grant_id,
                    ),
                )
                renewed = self._get_locked(connection, grant_id)
                if renewed is None:
                    raise DatabaseInvariantError("automation grant renewal failed")
                connection.commit()
                return renewed
            except Exception:
                connection.rollback()
                raise

    def revoke(self, grant_id: str, *, now: datetime) -> AutomationGrantRecord:
        self._ensure_initialized()
        require_safe_id(grant_id)
        now = require_utc(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = self._get_locked(connection, grant_id)
                if current is None:
                    raise DatabaseInvariantError("automation grant does not exist")
                if current.state is not AutomationGrantState.REVOKED:
                    connection.execute(
                        """
                        UPDATE automation_grants
                        SET state = 'revoked', revoked_at = ?,
                            last_error_code = NULL
                        WHERE grant_id = ?
                        """,
                        (to_iso(now), grant_id),
                    )
                revoked = self._get_locked(connection, grant_id)
                if revoked is None:
                    raise DatabaseInvariantError("automation grant revocation failed")
                connection.commit()
                return revoked
            except Exception:
                connection.rollback()
                raise

    def record_check(
        self,
        grant_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        error_code: str | None,
    ) -> AutomationGrantRecord:
        self._ensure_initialized()
        require_safe_id(grant_id)
        now = require_utc(now)
        next_check_at = require_utc(next_check_at)
        if next_check_at <= now:
            raise ValueError("next automation check must be in the future")
        if error_code is not None:
            require_safe_label(error_code)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = self._get_locked(connection, grant_id)
                if current is None or current.state is not AutomationGrantState.ACTIVE:
                    raise DatabaseInvariantError("automation grant is not active")
                connection.execute(
                    """
                    UPDATE automation_grants
                    SET last_checked_at = ?, next_check_at = ?,
                        last_error_code = ?
                    WHERE grant_id = ?
                    """,
                    (to_iso(now), to_iso(next_check_at), error_code, grant_id),
                )
                updated = self._get_locked(connection, grant_id)
                if updated is None:
                    raise DatabaseInvariantError("automation check update failed")
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise


__all__ = ["SqliteAutomationGrantRepository"]
