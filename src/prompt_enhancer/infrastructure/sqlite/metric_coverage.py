"""Read-only SQLite projection for identifier-free metric coverage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import sqlite3

from ...application.analysis.coaching_baselines import COACHING_METRIC_DEFINITIONS
from ...application.analysis.metric_coverage import (
    LatestProfileRunCounts,
    MetricCoverageProjectNotFoundError,
    MetricCoverageScope,
    MetricCoverageSelection,
    MetricCoverageSnapshot,
    MetricResultStateCounts,
    StoredMetricCoverage,
)
from ...application.analysis.text_analysis_presets import COACHING_PROFILE_V1
from ...application.analysis.text_contracts import TEXT_METRIC_SCHEMA_VERSION
from ._common import ConnectionScope, require_utc, to_iso


class SqliteMetricCoverageRepository:
    """Aggregate current Coaching-v1 result states in one read transaction."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    @staticmethod
    def _catalog_sql(parameters: dict[str, object]) -> str:
        rows: list[str] = []
        for ordinal, definition in enumerate(COACHING_METRIC_DEFINITIONS):
            parameters[f"catalog_ordinal_{ordinal}"] = ordinal
            parameters[f"catalog_key_{ordinal}"] = definition.key
            parameters[f"catalog_version_{ordinal}"] = definition.version
            parameters[f"catalog_unit_{ordinal}"] = definition.unit
            parameters[f"catalog_direction_{ordinal}"] = definition.direction.value
            parameters[f"catalog_aggregation_{ordinal}"] = (
                definition.aggregation_method.value
            )
            rows.append(
                f"(:catalog_ordinal_{ordinal}, :catalog_key_{ordinal}, "
                f":catalog_version_{ordinal}, :catalog_unit_{ordinal}, "
                f":catalog_direction_{ordinal}, :catalog_aggregation_{ordinal})"
            )
        return ",".join(rows)

    @classmethod
    def _rows(
        cls,
        connection: sqlite3.Connection,
        selection: MetricCoverageSelection,
        generated_at: datetime,
    ) -> tuple[sqlite3.Row, ...]:
        parameters: dict[str, object] = {
            "provider": selection.provider.value,
            "project_id": selection.project_id,
            "profile_key": COACHING_PROFILE_V1.analysis_profile_key,
            "profile_version": COACHING_PROFILE_V1.analysis_profile_version,
            "pack_key": COACHING_PROFILE_V1.metric_pack_key,
            "pack_version": COACHING_PROFILE_V1.metric_pack_version,
            "metric_schema_version": TEXT_METRIC_SCHEMA_VERSION,
            "generated_at": to_iso(generated_at),
        }
        catalog_sql = cls._catalog_sql(parameters)
        query = f"""
            WITH
            scope_projects AS (
                SELECT project_id
                FROM projects
                WHERE provider = :provider
                  AND (:project_id IS NULL OR project_id = :project_id)
            ),
            scope_sessions AS (
                SELECT session.session_id, session.project_id
                FROM sessions AS session
                JOIN scope_projects AS project
                  ON project.project_id = session.project_id
                WHERE session.provider = :provider
            ),
            ranked_attempt AS (
                SELECT run.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY run.session_id
                           ORDER BY run.started_at DESC, run.run_id
                       ) AS run_rank
                FROM session_analysis_runs AS run
                JOIN scope_sessions AS session
                  ON session.session_id = run.session_id
                WHERE run.provider = :provider
                  AND run.analysis_profile_key = :profile_key
                  AND run.analysis_profile_version = :profile_version
                  AND run.metric_pack_key = :pack_key
                  AND run.metric_pack_version = :pack_version
            ),
            latest_attempt AS (
                SELECT * FROM ranked_attempt WHERE run_rank = 1
            ),
            ranked_completed AS (
                SELECT run.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY run.session_id
                           ORDER BY run.started_at DESC, run.run_id
                       ) AS completed_rank
                FROM session_analysis_runs AS run
                JOIN scope_sessions AS session
                  ON session.session_id = run.session_id
                WHERE run.provider = :provider
                  AND run.status = 'completed'
                  AND run.analysis_profile_key = :profile_key
                  AND run.analysis_profile_version = :profile_version
                  AND run.metric_pack_key = :pack_key
                  AND run.metric_pack_version = :pack_version
            ),
            latest_completed AS (
                SELECT * FROM ranked_completed WHERE completed_rank = 1
            ),
            catalog(
                ordinal, metric_key, metric_version, metric_unit,
                metric_direction, aggregation_method
            ) AS (
                VALUES {catalog_sql}
            ),
            exact_selected AS (
                SELECT latest.run_id, latest.session_id, metric.metric_key
                FROM latest_completed AS latest
                JOIN session_analysis_run_metrics AS metric
                  ON metric.run_id = latest.run_id
                WHERE latest.metric_scope_state = 'exact'
            ),
            selected_result_records AS (
                SELECT
                    latest.run_id,
                    latest.session_id,
                    selected.metric_key,
                    result.version,
                    result.metric_schema_version,
                    result.value_state,
                    result.unit,
                    result.source,
                    result.direction,
                    result.aggregation_method,
                    result.algorithm_id,
                    result.algorithm_version,
                    result.model_id,
                    result.model_revision,
                    result.model_license,
                    result.tokenizer_id,
                    result.prompt_version,
                    result.rubric_version,
                    latest.data_tier,
                    latest.consent_policy_version,
                    latest.provider,
                    latest.provider_version,
                    latest.adapter_version,
                    latest.source_schema_version,
                    latest.content_schema_version,
                    latest.metric_engine_version,
                    latest.redactor_version,
                    latest.local_only,
                    CASE WHEN
                        result.version = catalog.metric_version
                        AND result.unit = catalog.metric_unit
                        AND result.direction = catalog.metric_direction
                        AND result.aggregation_method = catalog.aggregation_method
                        AND result.metric_schema_version = :metric_schema_version
                        AND latest.data_tier = 'redacted_content'
                        AND latest.local_only = 1
                    THEN 1 ELSE 0 END AS contract_compatible
                FROM exact_selected AS selected
                JOIN latest_completed AS latest
                  ON latest.run_id = selected.run_id
                JOIN catalog
                  ON catalog.metric_key = selected.metric_key
                JOIN session_analysis_results AS result
                  ON result.run_id = selected.run_id
                 AND result.key = selected.metric_key
            ),
            selected_result_summary AS (
                SELECT
                    run_id,
                    session_id,
                    metric_key,
                    COUNT(*) AS record_count,
                    SUM(contract_compatible) AS compatible_record_count
                FROM selected_result_records
                GROUP BY run_id, session_id, metric_key
            ),
            contract_compatible_results AS (
                SELECT record.*
                FROM selected_result_records AS record
                JOIN selected_result_summary AS summary
                  ON summary.run_id = record.run_id
                 AND summary.metric_key = record.metric_key
                WHERE summary.record_count = 1
                  AND summary.compatible_record_count = 1
            ),
            compatible_cohort_rows AS (
                SELECT metric_key
                FROM contract_compatible_results
                GROUP BY
                    metric_key,
                    data_tier,
                    consent_policy_version,
                    provider,
                    provider_version,
                    adapter_version,
                    source_schema_version,
                    content_schema_version,
                    metric_engine_version,
                    redactor_version,
                    local_only,
                    version,
                    unit,
                    source,
                    direction,
                    aggregation_method,
                    metric_schema_version,
                    algorithm_id,
                    algorithm_version,
                    model_id,
                    model_revision,
                    model_license,
                    tokenizer_id,
                    prompt_version,
                    rubric_version
            ),
            effective_grants AS (
                SELECT grant.grant_id, grant.project_id
                FROM automation_grants AS grant
                JOIN scope_projects AS project
                  ON project.project_id = grant.project_id
                WHERE grant.provider = :provider
                  AND grant.state = 'active'
                  AND grant.expires_at > :generated_at
            ),
            effective_grant_metrics AS (
                SELECT grant.project_id, metric.metric_key
                FROM effective_grants AS grant
                JOIN automation_grant_metrics AS metric
                  ON metric.grant_id = grant.grant_id
            )
            SELECT
                catalog.ordinal,
                catalog.metric_key,
                catalog.metric_version,
                (SELECT COUNT(*) FROM scope_projects) AS indexed_project_count,
                (SELECT COUNT(*) FROM scope_sessions) AS indexed_session_count,
                (SELECT COUNT(*) FROM latest_completed)
                    AS latest_completed_run_count,
                (SELECT COUNT(*) FROM latest_attempt WHERE status='completed')
                    AS completed_run_count,
                (SELECT COUNT(*) FROM latest_attempt WHERE status='running')
                    AS running_run_count,
                (SELECT COUNT(*) FROM latest_attempt WHERE status='failed')
                    AS failed_run_count,
                ((SELECT COUNT(*) FROM scope_sessions)
                  - (SELECT COUNT(*) FROM latest_attempt)) AS never_run_count,
                (SELECT COUNT(*) FROM latest_completed)
                    AS latest_completed_snapshot_count,
                (SELECT COUNT(*) FROM effective_grants)
                    AS effective_automation_grant_count,
                (SELECT COUNT(DISTINCT project_id) FROM effective_grants)
                    AS effective_automation_project_count,
                (
                    SELECT COUNT(*)
                    FROM latest_completed AS result_latest
                    JOIN session_analysis_results AS result
                      ON result.run_id = result_latest.run_id
                    WHERE result_latest.status = 'completed'
                      AND NOT EXISTS (
                          SELECT 1 FROM catalog AS known_catalog
                          WHERE known_catalog.metric_key = result.key
                      )
                ) AS unrecognized_result_record_count,
                (
                    SELECT COUNT(*) FROM exact_selected AS selected
                    WHERE selected.metric_key = catalog.metric_key
                ) AS selected_run_count,
                (
                    (SELECT COUNT(*) FROM latest_completed
                     WHERE metric_scope_state='exact')
                    -
                    (SELECT COUNT(*) FROM exact_selected AS selected
                     WHERE selected.metric_key = catalog.metric_key)
                ) AS not_selected_run_count,
                (SELECT COUNT(*) FROM latest_completed
                 WHERE metric_scope_state='legacy_unknown')
                    AS unknown_scope_run_count,
                (
                    SELECT COUNT(*)
                    FROM exact_selected AS selected
                    JOIN latest_completed AS completed
                      ON completed.run_id = selected.run_id
                    WHERE selected.metric_key = catalog.metric_key
                      AND completed.status = 'completed'
                ) AS completed_selected_run_count,
                (SELECT COUNT(*) FROM contract_compatible_results AS expected
                 WHERE expected.metric_key = catalog.metric_key
                   AND expected.value_state = 'known') AS known_count,
                (SELECT COUNT(*) FROM contract_compatible_results AS expected
                 WHERE expected.metric_key = catalog.metric_key
                   AND expected.value_state = 'unknown') AS unknown_count,
                (SELECT COUNT(*) FROM contract_compatible_results AS expected
                 WHERE expected.metric_key = catalog.metric_key
                   AND expected.value_state = 'not_applicable')
                    AS not_applicable_count,
                (SELECT COUNT(*) FROM contract_compatible_results AS expected
                 WHERE expected.metric_key = catalog.metric_key
                   AND expected.value_state = 'abstained') AS abstained_count,
                (SELECT COUNT(*) FROM contract_compatible_results AS expected
                 WHERE expected.metric_key = catalog.metric_key
                   AND expected.value_state = 'execution_error')
                    AS execution_error_count,
                (
                    (SELECT COUNT(*)
                     FROM exact_selected AS selected
                     JOIN latest_completed AS completed
                       ON completed.run_id = selected.run_id
                     WHERE selected.metric_key = catalog.metric_key
                       AND completed.status = 'completed')
                    -
                    (SELECT COUNT(*) FROM selected_result_summary AS summary
                     WHERE summary.metric_key = catalog.metric_key)
                ) AS expected_result_absent_count,
                (
                    SELECT COUNT(*)
                    FROM selected_result_summary AS summary
                    WHERE summary.metric_key = catalog.metric_key
                      AND NOT (
                          summary.record_count = 1
                          AND summary.compatible_record_count = 1
                      )
                ) AS contract_incompatible_result_count,
                (
                    SELECT COUNT(*)
                    FROM compatible_cohort_rows AS cohort
                    WHERE cohort.metric_key = catalog.metric_key
                ) AS compatible_provenance_cohort_count,
                (
                    SELECT COUNT(DISTINCT selected.project_id)
                    FROM effective_grant_metrics AS selected
                    WHERE selected.metric_key = catalog.metric_key
                ) AS effective_automation_selected_project_count
            FROM catalog
            ORDER BY catalog.ordinal
        """
        return tuple(connection.execute(query, parameters).fetchall())

    def snapshot(
        self,
        selection: MetricCoverageSelection,
        *,
        generated_at: datetime,
    ) -> MetricCoverageSnapshot:
        self._ensure_initialized()
        generated_at = require_utc(generated_at)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                if selection.scope is MetricCoverageScope.ONE_PROJECT:
                    found = connection.execute(
                        """
                        SELECT 1 FROM projects
                        WHERE project_id = ? AND provider = ?
                        """,
                        (selection.project_id, selection.provider.value),
                    ).fetchone()
                    if found is None:
                        raise MetricCoverageProjectNotFoundError(
                            "metric coverage project is unavailable"
                        )
                rows = self._rows(connection, selection, generated_at)
            finally:
                connection.rollback()
        if len(rows) != len(COACHING_METRIC_DEFINITIONS):
            raise RuntimeError("metric coverage catalog projection is incomplete")
        first = rows[0]
        latest = LatestProfileRunCounts(
            completed=int(first["completed_run_count"]),
            running=int(first["running_run_count"]),
            failed=int(first["failed_run_count"]),
            never_run=int(first["never_run_count"]),
        )
        metrics = tuple(
            StoredMetricCoverage(
                metric_key=str(row["metric_key"]),
                metric_version=int(row["metric_version"]),
                latest_completed_run_count=int(row["latest_completed_run_count"]),
                selected_run_count=int(row["selected_run_count"]),
                not_selected_run_count=int(row["not_selected_run_count"]),
                unknown_scope_run_count=int(row["unknown_scope_run_count"]),
                completed_selected_run_count=int(
                    row["completed_selected_run_count"]
                ),
                contract_compatible_result_states=MetricResultStateCounts(
                    known=int(row["known_count"]),
                    unknown=int(row["unknown_count"]),
                    not_applicable=int(row["not_applicable_count"]),
                    abstained=int(row["abstained_count"]),
                    execution_error=int(row["execution_error_count"]),
                ),
                contract_incompatible_result_count=int(
                    row["contract_incompatible_result_count"]
                ),
                expected_result_absent_count=int(
                    row["expected_result_absent_count"]
                ),
                compatible_provenance_cohort_count=int(
                    row["compatible_provenance_cohort_count"]
                ),
                effective_automation_selected_project_count=int(
                    row["effective_automation_selected_project_count"]
                ),
            )
            for row in rows
        )
        return MetricCoverageSnapshot(
            scope=selection.scope,
            provider=selection.provider,
            generated_at=generated_at,
            indexed_project_count=int(first["indexed_project_count"]),
            indexed_session_count=int(first["indexed_session_count"]),
            latest_profile_runs=latest,
            latest_completed_snapshot_count=int(
                first["latest_completed_snapshot_count"]
            ),
            effective_automation_grant_count=int(
                first["effective_automation_grant_count"]
            ),
            effective_automation_project_count=int(
                first["effective_automation_project_count"]
            ),
            unrecognized_result_record_count=int(
                first["unrecognized_result_record_count"]
            ),
            metrics=metrics,
        )


__all__ = ["SqliteMetricCoverageRepository"]
