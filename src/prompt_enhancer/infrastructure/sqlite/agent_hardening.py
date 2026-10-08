"""Fixed-query, content-free diagnostics for the authored Agent catalog."""

from __future__ import annotations

from ...application.agent_hardening import (
    MAX_OBSERVED_INTEGRITY_VIOLATIONS,
    AgentCatalogProbeResult,
    AgentPersistenceCounts,
)
from .agent_catalog import AgentCatalogSqliteDatabase


_COUNTS_QUERY = """
WITH interrupted AS (
    SELECT session.session_id
    FROM agent_catalog_sessions AS session
    LEFT JOIN agent_conversation_events AS event
      ON event.session_id=session.session_id
    WHERE session.retention_policy='local_history'
    GROUP BY session.session_id
    HAVING MAX(CASE WHEN event.event_kind='user' THEN event.event_seq END) IS NOT NULL
       AND (
           MAX(CASE WHEN event.event_kind='done' THEN event.event_seq END) IS NULL
           OR MAX(CASE WHEN event.event_kind='user' THEN event.event_seq END)
              > MAX(CASE WHEN event.event_kind='done' THEN event.event_seq END)
       )
)
SELECT
    (SELECT COUNT(*) FROM agent_projects) AS projects,
    (SELECT COUNT(*) FROM agent_projects WHERE archived_at IS NOT NULL)
        AS archived_projects,
    (SELECT COUNT(*) FROM agent_catalog_sessions) AS sessions,
    (SELECT COUNT(*) FROM agent_catalog_sessions WHERE archived_at IS NOT NULL)
        AS archived_sessions,
    (SELECT COUNT(*) FROM agent_catalog_sessions
      WHERE retention_policy='metadata_only') AS metadata_only_sessions,
    (SELECT COUNT(*) FROM agent_catalog_sessions
      WHERE retention_policy='local_history') AS retained_sessions,
    (SELECT COUNT(*) FROM agent_conversation_events) AS history_events,
    (SELECT COUNT(*) FROM interrupted) AS interrupted_retained_sessions,
    (SELECT COUNT(*) FROM agent_artifacts) AS artifacts,
    (SELECT COUNT(*) FROM agent_artifact_versions) AS artifact_versions,
    (SELECT COUNT(*) FROM agent_attachments
      WHERE attachment_state='staged') AS staged_attachments,
    (SELECT COUNT(*) FROM agent_attachments
      WHERE attachment_state='attached') AS attached_attachments
"""


_PROJECTION_VIOLATIONS_QUERY = """
WITH projected AS (
    SELECT
        session.session_id,
        session.history_state,
        session.retention_policy,
        session.history_revision,
        session.last_event_seq,
        session.turn_count,
        COUNT(event.event_seq) AS observed_events,
        COALESCE(MAX(event.event_seq), 0) AS observed_last_seq,
        COALESCE(SUM(CASE WHEN event.event_kind='done' THEN 1 ELSE 0 END), 0)
            AS observed_turns
    FROM agent_catalog_sessions AS session
    LEFT JOIN agent_conversation_events AS event
      ON event.session_id=session.session_id
    GROUP BY session.session_id
)
SELECT COUNT(*)
FROM projected
WHERE history_revision != observed_events
   OR last_event_seq != observed_last_seq
   OR turn_count != observed_turns
   OR history_state!='memory_only'
   OR (retention_policy='metadata_only' AND observed_events != 0)
"""


class SqliteAgentHardeningProbe:
    """Inspect only schema and aggregates; never select sensitive columns."""

    def __init__(self, database: AgentCatalogSqliteDatabase) -> None:
        self._database = database

    def inspect(self) -> AgentCatalogProbeResult:
        schema_version = self._database.initialize()
        with self._database.connect() as connection:
            quick_row = connection.execute("PRAGMA quick_check(1)").fetchone()
            quick_check_passed = (
                quick_row is not None
                and len(quick_row) == 1
                and str(quick_row[0]).casefold() == "ok"
            )
            foreign_key_rows = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchmany(MAX_OBSERVED_INTEGRITY_VIOLATIONS + 1)
            foreign_key_scan_truncated = (
                len(foreign_key_rows) > MAX_OBSERVED_INTEGRITY_VIOLATIONS
            )
            foreign_key_violations = min(
                len(foreign_key_rows), MAX_OBSERVED_INTEGRITY_VIOLATIONS
            )
            row = connection.execute(_COUNTS_QUERY).fetchone()
            projection_row = connection.execute(
                _PROJECTION_VIOLATIONS_QUERY
            ).fetchone()

        if row is None or projection_row is None:
            # The database adapter maps this closed failure to the public
            # unavailable state; no SQLite or path detail is retained.
            from ...application.agent_catalog import AgentCatalogError

            raise AgentCatalogError("agent_catalog_storage_unavailable")
        counts = AgentPersistenceCounts(
            projects=int(row["projects"]),
            archived_projects=int(row["archived_projects"]),
            sessions=int(row["sessions"]),
            archived_sessions=int(row["archived_sessions"]),
            metadata_only_sessions=int(row["metadata_only_sessions"]),
            retained_sessions=int(row["retained_sessions"]),
            history_events=int(row["history_events"]),
            interrupted_retained_sessions=int(
                row["interrupted_retained_sessions"]
            ),
            artifacts=int(row["artifacts"]),
            artifact_versions=int(row["artifact_versions"]),
            staged_attachments=int(row["staged_attachments"]),
            attached_attachments=int(row["attached_attachments"]),
        )
        return AgentCatalogProbeResult(
            schema_version=schema_version,
            quick_check_passed=quick_check_passed,
            foreign_key_violations_observed=foreign_key_violations,
            foreign_key_scan_truncated=foreign_key_scan_truncated,
            projection_violations=int(projection_row[0]),
            counts=counts,
        )


__all__ = ("SqliteAgentHardeningProbe",)
