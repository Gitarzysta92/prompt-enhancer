"""SQLite persistence for reproducible, immutable task analysis runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ...application.persistence import (
    AnalysisResultRecord,
    AnalysisRunDraft,
    AnalysisRunRecord,
    AnalysisRunStatus,
    MetricValueState,
)
from ...database import DatabaseInvariantError, SCHEMA_VERSION
from ...domain import DataTier, MetricObservation, MetricSource
from ._common import (
    ConnectionScope,
    from_iso,
    require_safe_id,
    require_safe_label,
    require_utc,
    to_iso,
)


class SqliteAnalysisRunRepository:
    """Append results once, then permit only explicit privacy deletion."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def begin(self, draft: AnalysisRunDraft) -> None:
        self._ensure_initialized()
        if draft.schema_version != SCHEMA_VERSION:
            raise DatabaseInvariantError("analysis run schema version does not match storage")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM analysis_runs WHERE run_id = ?", (draft.run_id,)
                ).fetchone() is not None:
                    raise DatabaseInvariantError("analysis run already exists")
                if connection.execute(
                    """
                    SELECT 1 FROM task_revisions
                    WHERE task_id = ? AND revision = ?
                    """,
                    (draft.task_id, draft.task_revision),
                ).fetchone() is None:
                    raise DatabaseInvariantError("task revision does not exist")
                connection.execute(
                    """
                    INSERT INTO analysis_runs(
                        run_id, task_id, task_revision, metric_pack_key,
                        metric_pack_version, data_tier, input_fingerprint,
                        metric_engine_version, redactor_version, schema_version,
                        started_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')
                    """,
                    (
                        draft.run_id,
                        draft.task_id,
                        draft.task_revision,
                        draft.metric_pack_key,
                        draft.metric_pack_version,
                        draft.data_tier.value,
                        draft.input_fingerprint,
                        draft.metric_engine_version,
                        draft.redactor_version,
                        draft.schema_version,
                        to_iso(draft.started_at),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def complete(
        self,
        run_id: str,
        results: tuple[AnalysisResultRecord, ...],
        *,
        finished_at: datetime,
    ) -> None:
        self._ensure_initialized()
        require_safe_id(run_id)
        finished_at = require_utc(finished_at)
        identities = {
            (result.observation.key, result.observation.version) for result in results
        }
        if len(identities) != len(results):
            raise DatabaseInvariantError("analysis results contain duplicate metrics")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                run = connection.execute(
                    """
                    SELECT task_id, task_revision, started_at, status
                    FROM analysis_runs WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                if run is None or run["status"] != AnalysisRunStatus.RUNNING.value:
                    raise DatabaseInvariantError("analysis run is missing or already terminal")
                if finished_at < from_iso(run["started_at"]):
                    raise DatabaseInvariantError("analysis cannot finish before it starts")
                allowed_events = {
                    row["event_id"]
                    for row in connection.execute(
                        """
                        SELECT e.event_id FROM task_revision_sessions trs
                        JOIN events e ON e.session_id = trs.session_id
                        WHERE trs.task_id = ? AND trs.revision = ?
                        """,
                        (run["task_id"], run["task_revision"]),
                    ).fetchall()
                }
                for result in results:
                    if not set(result.evidence_event_ids) <= allowed_events:
                        raise DatabaseInvariantError(
                            "analysis evidence must belong to the analyzed task revision"
                        )
                    observation = result.observation
                    connection.execute(
                        """
                        INSERT INTO analysis_results(
                            run_id, key, version, value_state, numeric_value,
                            text_value, unit, source, observed_count, eligible_count,
                            coverage, confidence, calculator_version, model_id,
                            model_revision, tokenizer_id, prompt_version, rubric_version,
                            error_code, computed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            observation.key,
                            observation.version,
                            result.value_state.value,
                            observation.numeric_value,
                            observation.text_value,
                            observation.unit,
                            observation.source.value,
                            observation.observed_count,
                            observation.eligible_count,
                            observation.coverage,
                            observation.confidence,
                            result.calculator_version,
                            result.model_id,
                            result.model_revision,
                            result.tokenizer_id,
                            result.prompt_version,
                            result.rubric_version,
                            result.error_code,
                            to_iso(result.computed_at),
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO analysis_result_evidence(
                            run_id, key, version, event_id, ordinal
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            (
                                run_id,
                                observation.key,
                                observation.version,
                                event_id,
                                ordinal,
                            )
                            for ordinal, event_id in enumerate(result.evidence_event_ids)
                        ),
                    )
                cursor = connection.execute(
                    """
                    UPDATE analysis_runs
                    SET finished_at = ?, status = 'completed'
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (to_iso(finished_at), run_id),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError("analysis run transition was rejected")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def fail(self, run_id: str, *, finished_at: datetime, failure_code: str) -> None:
        self._ensure_initialized()
        require_safe_id(run_id)
        finished_at = require_utc(finished_at)
        require_safe_label(failure_code)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT started_at, status FROM analysis_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if row is None or row["status"] != AnalysisRunStatus.RUNNING.value:
                    raise DatabaseInvariantError("analysis run is missing or already terminal")
                if finished_at < from_iso(row["started_at"]):
                    raise DatabaseInvariantError("analysis cannot finish before it starts")
                cursor = connection.execute(
                    """
                    UPDATE analysis_runs
                    SET finished_at = ?, status = 'failed', failure_code = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (to_iso(finished_at), failure_code, run_id),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError("analysis run transition was rejected")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get(self, run_id: str) -> AnalysisRunRecord | None:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        draft = AnalysisRunDraft(
            run_id=row["run_id"],
            task_id=row["task_id"],
            task_revision=row["task_revision"],
            metric_pack_key=row["metric_pack_key"],
            metric_pack_version=row["metric_pack_version"],
            data_tier=DataTier(row["data_tier"]),
            input_fingerprint=row["input_fingerprint"],
            metric_engine_version=row["metric_engine_version"],
            redactor_version=row["redactor_version"],
            schema_version=row["schema_version"],
            started_at=from_iso(row["started_at"]),
        )
        return AnalysisRunRecord(
            draft=draft,
            status=AnalysisRunStatus(row["status"]),
            finished_at=from_iso(row["finished_at"]),
            failure_code=row["failure_code"],
        )

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if isinstance(offset, bool) or offset < 0:
            raise ValueError("offset cannot be negative")

    def list_analysis_runs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[AnalysisRunRecord, ...]:
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
                SELECT run_id FROM analysis_runs {where}
                ORDER BY started_at DESC, run_id
                LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()
        runs = (self.get(row["run_id"]) for row in rows)
        return tuple(run for run in runs if run is not None)

    def get_results(self, run_id: str) -> tuple[AnalysisResultRecord, ...]:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM analysis_results
                WHERE run_id = ? ORDER BY key, version
                """,
                (run_id,),
            ).fetchall()
            results: list[AnalysisResultRecord] = []
            for row in rows:
                evidence_rows = connection.execute(
                    """
                    SELECT event_id FROM analysis_result_evidence
                    WHERE run_id = ? AND key = ? AND version = ? ORDER BY ordinal
                    """,
                    (run_id, row["key"], row["version"]),
                ).fetchall()
                observation = MetricObservation(
                    key=row["key"],
                    version=row["version"],
                    numeric_value=row["numeric_value"],
                    text_value=row["text_value"],
                    unit=row["unit"],
                    source=MetricSource(row["source"]),
                    observed_count=row["observed_count"],
                    eligible_count=row["eligible_count"],
                    coverage=row["coverage"],
                    confidence=row["confidence"],
                )
                results.append(
                    AnalysisResultRecord(
                        observation=observation,
                        value_state=MetricValueState(row["value_state"]),
                        calculator_version=row["calculator_version"],
                        evidence_event_ids=tuple(
                            item["event_id"] for item in evidence_rows
                        ),
                        model_id=row["model_id"],
                        model_revision=row["model_revision"],
                        tokenizer_id=row["tokenizer_id"],
                        prompt_version=row["prompt_version"],
                        rubric_version=row["rubric_version"],
                        error_code=row["error_code"],
                        computed_at=from_iso(row["computed_at"]),
                    )
                )
        return tuple(results)

    def delete_for_privacy(self, run_id: str) -> bool:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM analysis_runs WHERE run_id = ?", (run_id,)
                )
                connection.commit()
                return cursor.rowcount == 1
            except Exception:
                connection.rollback()
                raise
