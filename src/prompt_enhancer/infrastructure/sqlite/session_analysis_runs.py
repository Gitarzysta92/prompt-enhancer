"""SQLite persistence for immutable, content-free session quality snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
from typing import TYPE_CHECKING

from ...application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisPublicationRejectedError,
    SessionAnalysisAggregationResultRecord,
    SessionAnalysisAggregationSnapshotRecord,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisSignalRecord,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricScopeState,
    SessionMetricSignalStatus,
)
from ...database import DatabaseInvariantError
from ...domain import DataTier, MetricObservation, MetricSource, Provider
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

if TYPE_CHECKING:
    from ...application.history.persistence import (
        RepositorySealedTemporalBatchV1,
        SyntheticTemporalCompletionRequestV1,
    )
    from .temporal_history import SqliteTemporalHistoryRepository
    from .temporal_comparison_strata import (
        SqliteTemporalComparisonStratumRepository,
    )


class SqliteSessionAnalysisRunRepository:
    """Append a selected-window profile once; expose explicit privacy deletion."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        temporal_history_repository: SqliteTemporalHistoryRepository | None = None,
        temporal_comparison_repository: (
            SqliteTemporalComparisonStratumRepository | None
        ) = None,
        begin_temporal_delete_authorization: (
            Callable[[str], tuple[str, str]] | None
        ) = None,
        end_temporal_delete_authorization: (
            Callable[[str, str, str], None] | None
        ) = None,
        begin_synthetic_aggregation_delete_authorization: (
            Callable[[str, str, str, str, str, str], str] | None
        ) = None,
        end_synthetic_aggregation_delete_authorization: (
            Callable[[str, str, str], None] | None
        ) = None,
        begin_publication_authorization: (
            Callable[[str, str], tuple[str, str]] | None
        ) = None,
        end_publication_authorization: (
            Callable[[str, str, str, str], None] | None
        ) = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._temporal_history_repository = temporal_history_repository
        self._temporal_comparison_repository = temporal_comparison_repository
        self._begin_temporal_delete_authorization = (
            begin_temporal_delete_authorization
        )
        self._end_temporal_delete_authorization = end_temporal_delete_authorization
        self._begin_synthetic_aggregation_delete_authorization = (
            begin_synthetic_aggregation_delete_authorization
        )
        self._end_synthetic_aggregation_delete_authorization = (
            end_synthetic_aggregation_delete_authorization
        )
        self._begin_publication_authorization = begin_publication_authorization
        self._end_publication_authorization = end_publication_authorization

    def _authorized_publication_write(
        self,
        connection,  # type: ignore[no-untyped-def]
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
    def _synthetic_aggregation_delete_fingerprint(
        *,
        operation_id: str,
        validation_receipt_id: str,
        run_id: str,
        validation_fingerprint: str,
    ) -> str:
        return hashlib.sha256(
            "\x1f".join(
                (
                    "synthetic-aggregation-delete-authorization-v1",
                    operation_id,
                    validation_receipt_id,
                    "run",
                    run_id,
                    validation_fingerprint,
                )
            ).encode("ascii")
        ).hexdigest()

    def _delete_synthetic_aggregation_for_run(
        self,
        connection,
        *,
        operation_id: str,
        run_id: str,
    ) -> None:
        rows = connection.execute(
            """SELECT DISTINCT root.validation_receipt_id,
                              root.validation_fingerprint
               FROM temporal_run_delete_authorizations upstream
               JOIN comparison_sealed_stratum_roots sealed
                 ON sealed.analysis_run_id=upstream.run_id
               JOIN synthetic_aggregation_validation_members member
                 ON member.sealed_stratum_id=sealed.sealed_stratum_id
               JOIN synthetic_aggregation_validation_roots root
                 ON root.validation_receipt_id=member.validation_receipt_id
               WHERE upstream.operation_id=? AND upstream.run_id=?
               ORDER BY root.validation_receipt_id""",
            (operation_id, run_id),
        ).fetchall()
        if rows and (
            self._begin_synthetic_aggregation_delete_authorization is None
            or self._end_synthetic_aggregation_delete_authorization is None
        ):
            raise DatabaseInvariantError(
                "synthetic aggregation run privacy deletion is not authorized"
            )
        for row in rows:
            validation_receipt_id = str(row["validation_receipt_id"])
            validation_fingerprint = str(row["validation_fingerprint"])
            authorization_fingerprint = (
                self._synthetic_aggregation_delete_fingerprint(
                    operation_id=operation_id,
                    validation_receipt_id=validation_receipt_id,
                    run_id=run_id,
                    validation_fingerprint=validation_fingerprint,
                )
            )
            assert self._begin_synthetic_aggregation_delete_authorization is not None
            assert self._end_synthetic_aggregation_delete_authorization is not None
            tag = self._begin_synthetic_aggregation_delete_authorization(
                operation_id,
                validation_receipt_id,
                "run",
                run_id,
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
                        "run",
                        run_id,
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

    def begin(
        self,
        draft: SessionAnalysisRunDraft,
        *,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None:
        self._ensure_initialized()
        if draft.schema_version != SESSION_ANALYSIS_RUN_SCHEMA_VERSION:
            raise DatabaseInvariantError(
                "session analysis schema version does not match storage"
            )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM session_analysis_runs WHERE run_id = ?",
                    (draft.run_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError("session analysis run already exists")
                session = connection.execute(
                    "SELECT provider FROM sessions WHERE session_id = ?",
                    (draft.session_id,),
                ).fetchone()
                if session is None:
                    raise DatabaseInvariantError("session analysis target does not exist")
                if session["provider"] != draft.provider.value:
                    raise DatabaseInvariantError(
                        "session analysis provider does not match the selected session"
                    )
                connection.execute(
                    """
                    INSERT INTO session_analysis_runs(
                        run_id, session_id, request_fingerprint,
                        input_fingerprint, analysis_profile_key,
                        analysis_profile_version, metric_pack_key,
                        metric_pack_version, metric_scope_state, data_tier, consent_purpose,
                        consent_policy_version, provider, provider_version,
                        adapter_version, source_schema_version,
                        content_schema_version, metric_engine_version,
                        redactor_version, model_plan_fingerprint,
                        schema_version, local_only, started_at, status
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                        ?, 'running'
                    )
                    """,
                    (
                        draft.run_id,
                        draft.session_id,
                        draft.request_fingerprint,
                        draft.input_fingerprint,
                        draft.analysis_profile_key,
                        draft.analysis_profile_version,
                        draft.metric_pack_key,
                        draft.metric_pack_version,
                        draft.metric_scope_state.value,
                        draft.data_tier.value,
                        draft.consent_purpose,
                        draft.consent_policy_version,
                        draft.provider.value,
                        draft.provider_version,
                        draft.adapter_version,
                        draft.source_schema_version,
                        draft.content_schema_version,
                        draft.metric_engine_version,
                        draft.redactor_version,
                        draft.model_plan_fingerprint,
                        draft.schema_version,
                        to_iso(draft.started_at),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO session_analysis_run_metrics(
                        run_id, metric_key, ordinal
                    ) VALUES (?, ?, ?)
                    """,
                    (
                        (draft.run_id, metric_key, ordinal)
                        for ordinal, metric_key in enumerate(
                            draft.selected_metric_keys
                        )
                    ),
                )
                if completion_authority is not None:
                    authority = completion_authority
                    root = connection.execute(
                        """SELECT root.job_id
                           FROM automation_session_quality_publication_deadlines root
                           JOIN analysis_jobs job ON job.job_id=root.job_id
                           WHERE root.job_id=?
                             AND root.automation_grant_id=?
                             AND root.analysis_run_id IS NULL
                             AND job.state IN ('preprocessing','stage_n')
                             AND job.cancel_requested=0
                             AND job.lease_owner=? AND job.lease_token=?
                             AND job.lease_expires_at>?
                             AND NOT EXISTS(
                               SELECT 1
                               FROM automation_session_quality_publication_closures c
                               WHERE c.job_id=root.job_id
                             )""",
                        (
                            authority.job_id,
                            authority.automation_grant_id,
                            authority.lease_owner,
                            authority.lease_token,
                            to_iso(draft.started_at),
                        ),
                    ).fetchone()
                    if root is None:
                        raise SessionAnalysisPublicationRejectedError(
                            "automation_publication_deadline_missing"
                        )

                    def bind() -> None:
                        connection.execute(
                            """UPDATE automation_session_quality_publication_deadlines
                               SET analysis_run_id=? WHERE job_id=?
                                 AND analysis_run_id IS NULL""",
                            (draft.run_id, authority.job_id),
                        )

                    self._authorized_publication_write(
                        connection,
                        job_id=authority.job_id,
                        action="bind",
                        callback=bind,
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def complete(
        self,
        run_id: str,
        results: tuple[SessionAnalysisResultRecord, ...],
        *,
        finished_at: datetime,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
        temporal_completion_request: SyntheticTemporalCompletionRequestV1 | None = None,
    ) -> RepositorySealedTemporalBatchV1 | None:
        self._ensure_initialized()
        require_safe_id(run_id)
        finished_at = require_utc(finished_at)
        if not results:
            raise DatabaseInvariantError("completed session analysis requires results")
        identities = {
            (result.observation.key, result.observation.version) for result in results
        }
        if len(identities) != len(results):
            raise DatabaseInvariantError("session analysis results contain duplicates")
        if temporal_completion_request is not None and (
            completion_authority is None or self._temporal_history_repository is None
        ):
            raise DatabaseInvariantError(
                "synthetic temporal completion requires live repository authority"
            )

        with self._connection_scope() as connection:
            sealed_batch = None
            pending_comparison_seal = None
            publication_authority: tuple[str, str, str, str] | None = None
            try:
                if temporal_completion_request is not None:
                    connection.execute("PRAGMA trusted_schema=ON")
                connection.execute("BEGIN IMMEDIATE")
                run = connection.execute(
                    """
                    SELECT started_at, finished_at, status, metric_scope_state
                    FROM session_analysis_runs
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                has_comparison_preparation = connection.execute(
                    """SELECT 1 FROM comparison_prepared_stratum_roots
                       WHERE expected_analysis_run_id=?""",
                    (run_id,),
                ).fetchone() is not None
                if has_comparison_preparation and (
                    temporal_completion_request is None
                    or completion_authority is None
                    or self._temporal_comparison_repository is None
                ):
                    raise DatabaseInvariantError(
                        "prepared comparison completion requires atomic temporal sealing"
                    )
                if (
                    run is not None
                    and run["status"] == AnalysisRunStatus.COMPLETED.value
                    and temporal_completion_request is not None
                ):
                    assert completion_authority is not None
                    assert self._temporal_history_repository is not None
                    sealed_batch = (
                        self._temporal_history_repository._replay_completed_locked(
                            connection,
                            request=temporal_completion_request,
                            results=results,
                            finished_at=finished_at,
                            completion_authority=completion_authority,
                        )
                    )
                    if self._temporal_comparison_repository is not None:
                        self._temporal_comparison_repository._replay_completed_locked(
                            connection,
                            sealed_batch=sealed_batch,
                        )
                    connection.commit()
                    return sealed_batch
                if run is None or run["status"] != AnalysisRunStatus.RUNNING.value:
                    raise DatabaseInvariantError(
                        "session analysis run is missing or already terminal"
                    )
                selected_metric_keys = tuple(
                    row["metric_key"]
                    for row in connection.execute(
                        """
                        SELECT metric_key FROM session_analysis_run_metrics
                        WHERE run_id = ? ORDER BY ordinal
                        """,
                        (run_id,),
                    ).fetchall()
                )
                if (
                    run["metric_scope_state"]
                    != SessionMetricScopeState.EXACT.value
                    or tuple(sorted(result.observation.key for result in results))
                    != selected_metric_keys
                ):
                    raise DatabaseInvariantError(
                        "session analysis results do not match selected metric scope"
                    )
                if completion_authority is not None:
                    root_binding = connection.execute(
                        """SELECT automation_grant_id,analysis_run_id
                           FROM automation_session_quality_publication_deadlines
                           WHERE job_id=?""",
                        (completion_authority.job_id,),
                    ).fetchone()
                    if root_binding is None:
                        connection.rollback()
                        self._reject_publication(
                            completion_authority,
                            run_id=run_id,
                            observed_at=finished_at,
                            reason_code="automation_publication_deadline_missing",
                        )
                    if (
                        root_binding["automation_grant_id"]
                        != completion_authority.automation_grant_id
                        or (
                            root_binding["analysis_run_id"] is not None
                            and root_binding["analysis_run_id"] != run_id
                        )
                    ):
                        raise DatabaseInvariantError(
                            "automation completion authority does not match the bound run"
                        )
                    unbound = connection.execute(
                        """SELECT 1
                           FROM automation_session_quality_publication_deadlines
                           WHERE job_id=? AND automation_grant_id=?
                             AND analysis_run_id IS NULL""",
                        (
                            completion_authority.job_id,
                            completion_authority.automation_grant_id,
                        ),
                    ).fetchone()
                    if unbound is not None:
                        self._authorized_publication_write(
                            connection,
                            job_id=completion_authority.job_id,
                            action="bind",
                            callback=lambda: connection.execute(
                                """UPDATE automation_session_quality_publication_deadlines
                                   SET analysis_run_id=? WHERE job_id=?
                                     AND analysis_run_id IS NULL""",
                                (run_id, completion_authority.job_id),
                            ),
                        )
                        bound = connection.execute(
                            """SELECT 1
                               FROM automation_session_quality_publication_deadlines
                               WHERE job_id=? AND automation_grant_id=?
                                 AND analysis_run_id=?""",
                            (
                                completion_authority.job_id,
                                completion_authority.automation_grant_id,
                                run_id,
                            ),
                        ).fetchone()
                        if bound is None:
                            raise DatabaseInvariantError(
                                "automation publication run binding was rejected"
                            )
                    authorized = connection.execute(
                        """
                        SELECT 1
                        FROM analysis_jobs AS job
                        JOIN automation_grants AS grant
                          ON grant.grant_id = job.automation_grant_id
                        JOIN automation_session_quality_publication_deadlines AS root
                          ON root.job_id=job.job_id
                         AND root.automation_grant_id=grant.grant_id
                        JOIN sessions AS target
                          ON target.session_id = job.session_id
                        JOIN session_analysis_runs AS analysis
                          ON analysis.run_id = ?
                        WHERE job.job_id = ?
                          AND job.automation_grant_id = ?
                          AND job.kind = 'session_quality'
                          AND job.state IN ('preprocessing', 'stage_n')
                          AND job.cancel_requested = 0
                          AND job.lease_owner = ?
                          AND job.lease_token = ?
                          AND job.lease_expires_at > ?
                          AND job.local_only = 1
                          AND grant.state = 'active'
                          AND grant.expires_at > ?
                          AND grant.local_only = 1
                          AND grant.remote_requires_fresh_approval = 1
                          AND analysis.status = 'running'
                          AND root.analysis_run_id=analysis.run_id
                          AND analysis.local_only = 1
                          AND analysis.session_id = job.session_id
                          AND analysis.provider = job.provider
                          AND target.project_id = job.project_id
                          AND target.provider = job.provider
                          AND grant.project_id = job.project_id
                          AND grant.provider = job.provider
                          AND NOT EXISTS (
                              SELECT metric_key
                              FROM session_analysis_run_metrics
                              WHERE run_id = analysis.run_id
                              EXCEPT
                              SELECT metric_key
                              FROM analysis_job_metrics
                              WHERE job_id = job.job_id
                          )
                          AND NOT EXISTS (
                              SELECT metric_key
                              FROM analysis_job_metrics
                              WHERE job_id = job.job_id
                              EXCEPT
                              SELECT metric_key
                              FROM session_analysis_run_metrics
                              WHERE run_id = analysis.run_id
                          )
                          AND NOT EXISTS (
                              SELECT metric_key
                              FROM session_analysis_run_metrics
                              WHERE run_id = analysis.run_id
                              EXCEPT
                              SELECT metric_key
                              FROM automation_grant_metrics
                              WHERE grant_id = grant.grant_id
                          )
                          AND NOT EXISTS (
                              SELECT metric_key
                              FROM automation_grant_metrics
                              WHERE grant_id = grant.grant_id
                              EXCEPT
                              SELECT metric_key
                              FROM session_analysis_run_metrics
                              WHERE run_id = analysis.run_id
                          )
                        """,
                        (
                            run_id,
                            completion_authority.job_id,
                            completion_authority.automation_grant_id,
                            completion_authority.lease_owner,
                            completion_authority.lease_token,
                            to_iso(finished_at),
                            to_iso(finished_at),
                        ),
                    ).fetchone()
                    if authorized is None:
                        raise DatabaseInvariantError(
                            "automation completion authority is no longer valid"
                        )
                    publication = connection.execute(
                        """SELECT root.first_claim_at_us,root.deadline_at_us,
                                  root.high_water_at_us
                           FROM automation_session_quality_publication_deadlines root
                           WHERE root.job_id=? AND root.analysis_run_id=?
                             AND root.automation_grant_id=?
                             AND NOT EXISTS(
                               SELECT 1
                               FROM automation_session_quality_publication_closures c
                               WHERE c.job_id=root.job_id
                             )""",
                        (
                            completion_authority.job_id,
                            run_id,
                            completion_authority.automation_grant_id,
                        ),
                    ).fetchone()
                    if publication is None:
                        connection.rollback()
                        self._reject_publication(
                            completion_authority,
                            run_id=run_id,
                            observed_at=finished_at,
                            reason_code="automation_publication_deadline_missing",
                        )
                    finished_us = to_epoch_us(finished_at)
                    if finished_us < int(publication["high_water_at_us"]):
                        connection.rollback()
                        self._reject_publication(
                            completion_authority,
                            run_id=run_id,
                            observed_at=finished_at,
                            reason_code="automation_publication_clock_regressed",
                        )
                    if finished_us >= int(publication["deadline_at_us"]):
                        connection.rollback()
                        self._reject_publication(
                            completion_authority,
                            run_id=run_id,
                            observed_at=finished_at,
                            reason_code="automation_publication_deadline_exceeded",
                        )
                    if (
                        self._begin_publication_authorization is None
                        or self._end_publication_authorization is None
                    ):
                        raise DatabaseInvariantError(
                            "automation publication write is not authorized"
                        )
                    operation_id, tag = self._begin_publication_authorization(
                        completion_authority.job_id, "publish"
                    )
                    publication_authority = (
                        operation_id,
                        completion_authority.job_id,
                        "publish",
                        tag,
                    )
                    connection.execute("PRAGMA trusted_schema=ON")
                    connection.execute(
                        "INSERT INTO automation_publication_write_authorizations "
                        "VALUES(?,?,?,?)",
                        publication_authority,
                    )
                    connection.execute(
                        """INSERT INTO automation_session_quality_publications(
                               job_id,analysis_run_id,published_at,
                               published_at_us,result_count
                           ) VALUES(?,?,?,?,?)""",
                        (
                            completion_authority.job_id,
                            run_id,
                            to_iso(finished_at),
                            to_epoch_us(finished_at),
                            len(results),
                        ),
                    )
                started_at = from_iso(run["started_at"])
                if started_at is None or finished_at < started_at:
                    raise DatabaseInvariantError(
                        "session analysis cannot finish before it starts"
                    )
                for result in results:
                    if not started_at <= result.computed_at <= finished_at:
                        raise DatabaseInvariantError(
                            "session result timestamp is outside the analysis window"
                        )
                    observation = result.observation
                    connection.execute(
                        """
                        INSERT INTO session_analysis_results(
                            run_id, key, version, metric_schema_version,
                            value_state, numeric_value, unit, source, direction,
                            applicability, aggregation_method, fraction_numerator,
                            fraction_denominator, observed_count, eligible_count,
                            coverage, confidence, evidence_data_tier,
                            explanation_code, error_code, algorithm_id,
                            algorithm_version, model_id, model_revision,
                            model_license, tokenizer_id, prompt_version,
                            rubric_version, computed_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            run_id,
                            observation.key,
                            observation.version,
                            result.metric_schema_version,
                            result.value_state.value,
                            observation.numeric_value,
                            observation.unit,
                            observation.source.value,
                            result.direction.value,
                            result.applicability.value,
                            result.aggregation_method.value,
                            result.fraction_numerator,
                            result.fraction_denominator,
                            observation.observed_count,
                            observation.eligible_count,
                            observation.coverage,
                            observation.confidence,
                            result.evidence_data_tier.value,
                            result.explanation_code,
                            result.error_code,
                            result.algorithm_id,
                            result.algorithm_version,
                            result.model_id,
                            result.model_revision,
                            result.model_license,
                            result.tokenizer_id,
                            result.prompt_version,
                            result.rubric_version,
                            to_iso(result.computed_at),
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO session_analysis_result_evidence(
                            run_id, key, version, message_id, origin, ordinal
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            (
                                run_id,
                                observation.key,
                                observation.version,
                                evidence.message_id,
                                evidence.origin.value,
                                ordinal,
                            )
                            for ordinal, evidence in enumerate(result.evidence)
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO session_analysis_result_signals(
                            run_id, key, version, code, status, signal_count, ordinal
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            (
                                run_id,
                                observation.key,
                                observation.version,
                                signal.code,
                                signal.status.value,
                                signal.count,
                                ordinal,
                            )
                            for ordinal, signal in enumerate(result.signals)
                        ),
                    )
                if temporal_completion_request is not None:
                    assert completion_authority is not None
                    assert self._temporal_history_repository is not None
                    sealed_batch = self._temporal_history_repository._complete_locked(
                        connection,
                        request=temporal_completion_request,
                        results=results,
                        finished_at=finished_at,
                        completion_authority=completion_authority,
                    )
                if has_comparison_preparation:
                    assert sealed_batch is not None
                    assert completion_authority is not None
                    assert self._temporal_comparison_repository is not None
                    pending_comparison_seal = (
                        self._temporal_comparison_repository
                        ._authorize_completion_seal_locked(
                            connection,
                            sealed_batch=sealed_batch,
                            completion_authority=completion_authority,
                            finished_at=finished_at,
                        )
                    )
                    if pending_comparison_seal is None:
                        raise DatabaseInvariantError(
                            "comparison preparation disappeared during completion"
                        )
                cursor = connection.execute(
                    """
                    UPDATE session_analysis_runs
                    SET finished_at = ?, status = 'completed'
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (to_iso(finished_at), run_id),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError(
                        "session analysis transition was rejected"
                    )
                if publication_authority is not None:
                    connection.execute(
                        "DELETE FROM automation_publication_write_authorizations "
                        "WHERE operation_id=?",
                        (publication_authority[0],),
                    )
                if has_comparison_preparation:
                    assert pending_comparison_seal is not None
                    assert self._temporal_comparison_repository is not None
                    self._temporal_comparison_repository._commit_completion_seal_locked(
                        connection,
                        pending_comparison_seal,
                    )
                if sealed_batch is not None:
                    assert self._temporal_history_repository is not None
                    verified = (
                        self._temporal_history_repository._hydrate_sealed_locked(
                            connection, sealed_batch.sealed_batch_id
                        )
                    )
                    if verified != sealed_batch:
                        raise DatabaseInvariantError(
                            "completed temporal graph did not rederive exactly"
                        )
                    sealed_batch = verified
                connection.commit()
                return sealed_batch
            except Exception:
                connection.rollback()
                if (
                    pending_comparison_seal is not None
                    and self._temporal_comparison_repository is not None
                ):
                    self._temporal_comparison_repository._cancel_completion_seal_authorization(
                        pending_comparison_seal
                    )
                raise
            finally:
                if (
                    publication_authority is not None
                    and self._end_publication_authorization is not None
                ):
                    self._end_publication_authorization(*publication_authority)
                if publication_authority is not None:
                    connection.execute("PRAGMA trusted_schema=OFF")
                if temporal_completion_request is not None:
                    connection.execute("PRAGMA trusted_schema=OFF")

    def _reject_publication(
        self,
        authority: SessionAnalysisCompletionAuthority,
        *,
        run_id: str,
        observed_at: datetime,
        reason_code: str,
    ) -> None:
        """Atomically close a late/regressed publication, then raise a typed stop."""

        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root = connection.execute(
                    """SELECT first_claim_at_us,deadline_at_us,high_water_at_us,
                              analysis_run_id
                       FROM automation_session_quality_publication_deadlines
                       WHERE job_id=? AND automation_grant_id=?""",
                    (authority.job_id, authority.automation_grant_id),
                ).fetchone()
                if root is None:
                    if reason_code != "automation_publication_deadline_missing":
                        raise DatabaseInvariantError(
                            "automation publication deadline root is missing"
                        )
                    self._fail_rejected_publication_locked(
                        connection,
                        authority=authority,
                        run_id=run_id,
                        reason_code=reason_code,
                        effective_us=to_epoch_us(observed_at),
                    )
                    connection.commit()
                    raise SessionAnalysisPublicationRejectedError(reason_code)
                completed = connection.execute(
                    """SELECT published.published_at
                       FROM automation_session_quality_publications published
                       JOIN session_analysis_runs run
                         ON run.run_id=published.analysis_run_id
                       WHERE published.job_id=? AND run.status='completed'""",
                    (authority.job_id,),
                ).fetchone()
                if completed is not None:
                    published_at = str(completed["published_at"])
                    connection.execute(
                        """UPDATE analysis_jobs SET state='completed',stage_number=NULL,
                           progress_completed=progress_total,cancel_requested=0,
                           lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                           last_error_code=NULL,terminal_reason_code='local_analysis_completed',
                           terminal_at=?,updated_at=? WHERE job_id=?
                             AND state NOT IN ('completed','partial','failed','cancelled','superseded')""",
                        (published_at, published_at, authority.job_id),
                    )
                    connection.commit()
                    raise SessionAnalysisPublicationRejectedError(
                        "local_analysis_completed"
                    )
                existing_closure = connection.execute(
                    """SELECT reason_code,effective_high_water_at_us
                       FROM automation_session_quality_publication_closures
                       WHERE job_id=?""",
                    (authority.job_id,),
                ).fetchone()
                if existing_closure is not None:
                    existing_reason = str(existing_closure["reason_code"])
                    effective_us = int(existing_closure["effective_high_water_at_us"])
                    self._fail_rejected_publication_locked(
                        connection,
                        authority=authority,
                        run_id=run_id,
                        reason_code=existing_reason,
                        effective_us=effective_us,
                    )
                    connection.commit()
                    raise SessionAnalysisPublicationRejectedError(existing_reason)

                observed_us = to_epoch_us(observed_at)
                high_water_us = int(root["high_water_at_us"])
                deadline_us = int(root["deadline_at_us"])
                if reason_code == "automation_publication_deadline_exceeded":
                    if observed_us < deadline_us:
                        raise DatabaseInvariantError(
                            "late publication was reported before its cutoff"
                        )
                    observation_kind = "wall_deadline_exceeded"
                    effective_us = observed_us
                elif reason_code == "automation_publication_clock_regressed":
                    if observed_us >= high_water_us:
                        raise DatabaseInvariantError(
                            "publication clock regression was not observed"
                        )
                    observation_kind = "wall_clock_regressed"
                    effective_us = high_water_us
                elif reason_code == "automation_publication_deadline_missing":
                    observation_kind = "publication_authority_missing"
                    effective_us = high_water_us
                else:
                    raise DatabaseInvariantError(
                        "automation publication rejection reason is invalid"
                    )
                if root["analysis_run_id"] != run_id:
                    raise DatabaseInvariantError(
                        "automation publication run binding changed"
                    )

                def close() -> None:
                    connection.execute(
                        """INSERT INTO automation_session_quality_publication_closures(
                               job_id,reason_code,observation_kind,observed_at_us,
                               effective_high_water_at_us
                           ) VALUES(?,?,?,?,?)""",
                        (
                            authority.job_id,
                            reason_code,
                            observation_kind,
                            observed_us,
                            effective_us,
                        ),
                    )

                self._authorized_publication_write(
                    connection,
                    job_id=authority.job_id,
                    action="close",
                    callback=close,
                )
                self._fail_rejected_publication_locked(
                    connection,
                    authority=authority,
                    run_id=run_id,
                    reason_code=reason_code,
                    effective_us=effective_us,
                )
                connection.commit()
            except SessionAnalysisPublicationRejectedError:
                raise
            except Exception:
                connection.rollback()
                raise
        raise SessionAnalysisPublicationRejectedError(reason_code)

    @staticmethod
    def _fail_rejected_publication_locked(
        connection,  # type: ignore[no-untyped-def]
        *,
        authority: SessionAnalysisCompletionAuthority,
        run_id: str,
        reason_code: str,
        effective_us: int,
    ) -> None:
        terminal_timestamp = to_iso(from_epoch_us(effective_us))
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
            """UPDATE session_analysis_runs SET finished_at=?,status='failed',
                   failure_code=? WHERE run_id=? AND status='running'
                 AND NOT EXISTS(
                   SELECT 1 FROM session_analysis_results WHERE run_id=?
                 )""",
            (run_terminal_timestamp, reason_code, run_id, run_id),
        )
        connection.execute(
            """UPDATE analysis_jobs SET state='failed',stage_number=NULL,
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
               last_error_code=?,terminal_reason_code=?,terminal_at=?,updated_at=?
               WHERE job_id=? AND lease_owner=? AND lease_token=?
                 AND kind='session_quality' AND automation_grant_id=?
                 AND state IN ('preprocessing','stage_n')""",
            (
                reason_code,
                reason_code,
                terminal_timestamp,
                terminal_timestamp,
                authority.job_id,
                authority.lease_owner,
                authority.lease_token,
                authority.automation_grant_id,
            ),
        )

    def fail(self, run_id: str, *, finished_at: datetime, failure_code: str) -> None:
        self._ensure_initialized()
        require_safe_id(run_id)
        finished_at = require_utc(finished_at)
        require_safe_label(failure_code)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT started_at, status FROM session_analysis_runs
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                if row is None or row["status"] != AnalysisRunStatus.RUNNING.value:
                    raise DatabaseInvariantError(
                        "session analysis run is missing or already terminal"
                    )
                started_at = from_iso(row["started_at"])
                if started_at is None or finished_at < started_at:
                    raise DatabaseInvariantError(
                        "session analysis cannot finish before it starts"
                    )
                cursor = connection.execute(
                    """
                    UPDATE session_analysis_runs
                    SET finished_at = ?, status = 'failed', failure_code = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (to_iso(finished_at), failure_code, run_id),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError(
                        "session analysis transition was rejected"
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _selected_metrics(connection, run_id: str) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
        return tuple(
            row["metric_key"]
            for row in connection.execute(
                """
                SELECT metric_key FROM session_analysis_run_metrics
                WHERE run_id = ? ORDER BY ordinal
                """,
                (run_id,),
            ).fetchall()
        )

    @classmethod
    def _record_from_row(
        cls,
        connection,  # type: ignore[no-untyped-def]
        row: object,
    ) -> SessionAnalysisRunRecord:
        draft = SessionAnalysisRunDraft(
            run_id=row["run_id"],
            session_id=row["session_id"],
            request_fingerprint=row["request_fingerprint"],
            input_fingerprint=row["input_fingerprint"],
            analysis_profile_key=row["analysis_profile_key"],
            analysis_profile_version=row["analysis_profile_version"],
            metric_pack_key=row["metric_pack_key"],
            metric_pack_version=row["metric_pack_version"],
            metric_scope_state=SessionMetricScopeState(
                row["metric_scope_state"]
            ),
            selected_metric_keys=cls._selected_metrics(
                connection,
                row["run_id"],
            ),
            data_tier=DataTier(row["data_tier"]),
            consent_purpose=row["consent_purpose"],
            consent_policy_version=row["consent_policy_version"],
            provider=Provider(row["provider"]),
            provider_version=row["provider_version"],
            adapter_version=row["adapter_version"],
            source_schema_version=row["source_schema_version"],
            content_schema_version=row["content_schema_version"],
            metric_engine_version=row["metric_engine_version"],
            redactor_version=row["redactor_version"],
            model_plan_fingerprint=row["model_plan_fingerprint"],
            schema_version=row["schema_version"],
            local_only=bool(row["local_only"]),
            started_at=from_iso(row["started_at"]),
        )
        return SessionAnalysisRunRecord(
            draft=draft,
            status=AnalysisRunStatus(row["status"]),
            finished_at=from_iso(row["finished_at"]),
            failure_code=row["failure_code"],
        )

    def get(self, run_id: str) -> SessionAnalysisRunRecord | None:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM session_analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return (
                None
                if row is None
                else self._record_from_row(connection, row)
            )

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset cannot be negative")

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[SessionAnalysisRunRecord, ...]:
        self._ensure_initialized()
        require_safe_id(session_id)
        self._validate_page(limit, offset)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM session_analysis_runs
                WHERE session_id = ?
                ORDER BY started_at DESC, run_id
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
            return tuple(
                self._record_from_row(connection, row) for row in rows
            )

    def get_latest_completed(
        self, session_id: str
    ) -> SessionAnalysisRunRecord | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM session_analysis_runs
                WHERE session_id = ? AND status = 'completed'
                ORDER BY started_at DESC, run_id LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._record_from_row(connection, row)
            )

    def get_latest_for_profile(
        self,
        session_id: str,
        *,
        analysis_profile_key: str,
        analysis_profile_version: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> SessionAnalysisRunRecord | None:
        """Load the latest run for one exact server-owned profile and pack."""

        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_label(analysis_profile_key)
        require_safe_label(metric_pack_key)
        if (
            isinstance(analysis_profile_version, bool)
            or not isinstance(analysis_profile_version, int)
            or analysis_profile_version < 1
            or isinstance(metric_pack_version, bool)
            or not isinstance(metric_pack_version, int)
            or metric_pack_version < 1
        ):
            raise ValueError("analysis profile and metric pack versions begin at one")
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM session_analysis_runs
                WHERE session_id = ?
                  AND analysis_profile_key = ?
                  AND analysis_profile_version = ?
                  AND metric_pack_key = ?
                  AND metric_pack_version = ?
                ORDER BY started_at DESC, run_id LIMIT 1
                """,
                (
                    session_id,
                    analysis_profile_key,
                    analysis_profile_version,
                    metric_pack_key,
                    metric_pack_version,
                ),
            ).fetchone()
            return (
                None
                if row is None
                else self._record_from_row(connection, row)
            )

    @staticmethod
    def _validate_aggregation_selection(session_ids: tuple[str, ...]) -> None:
        if not 1 <= len(session_ids) <= 100:
            raise ValueError("aggregation selection must contain 1 to 100 sessions")
        for session_id in session_ids:
            require_safe_id(session_id)
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("aggregation selection cannot contain duplicates")

    def get_latest_completed_for_aggregation(
        self,
        session_ids: tuple[str, ...],
        *,
        analysis_profile_key: str,
        analysis_profile_version: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> tuple[SessionAnalysisAggregationSnapshotRecord, ...]:
        """Load the latest matching profile/pack snapshots in one SQLite query."""

        self._ensure_initialized()
        self._validate_aggregation_selection(session_ids)
        require_safe_label(analysis_profile_key)
        require_safe_label(metric_pack_key)
        if analysis_profile_version < 1 or metric_pack_version < 1:
            raise ValueError("aggregation profile and pack versions begin at one")
        selected_values = ", ".join("(?, ?)" for _ in session_ids)
        parameters = tuple(
            value
            for ordinal, session_id in enumerate(session_ids)
            for value in (session_id, ordinal)
        ) + (
            analysis_profile_key,
            analysis_profile_version,
            metric_pack_key,
            metric_pack_version,
        )
        query = f"""
            WITH selected(session_id, selection_order) AS (
                VALUES {selected_values}
            ),
            scope AS (
                SELECT ordered.run_id,
                       GROUP_CONCAT(ordered.metric_key, '|') AS metric_keys
                FROM (
                    SELECT run_id, metric_key
                    FROM session_analysis_run_metrics
                    ORDER BY run_id, ordinal
                ) AS ordered
                GROUP BY ordered.run_id
            ),
            ranked AS (
                SELECT
                    selected.selection_order,
                    run.run_id,
                    run.session_id,
                    run.analysis_profile_key,
                    run.analysis_profile_version,
                    run.metric_pack_key,
                    run.metric_pack_version,
                    run.metric_scope_state,
                    COALESCE(scope.metric_keys, '') AS selected_metric_keys,
                    run.data_tier,
                    run.consent_policy_version,
                    run.provider,
                    run.provider_version,
                    run.adapter_version,
                    run.source_schema_version,
                    run.content_schema_version,
                    run.metric_engine_version,
                    run.redactor_version,
                    run.model_plan_fingerprint,
                    run.schema_version,
                    run.local_only,
                    ROW_NUMBER() OVER (
                        PARTITION BY run.session_id
                        ORDER BY run.started_at DESC, run.run_id
                    ) AS run_rank
                FROM selected
                JOIN session_analysis_runs AS run
                  ON run.session_id = selected.session_id
                 AND run.status = 'completed'
                 AND run.analysis_profile_key = ?
                 AND run.analysis_profile_version = ?
                 AND run.metric_pack_key = ?
                 AND run.metric_pack_version = ?
                LEFT JOIN scope ON scope.run_id = run.run_id
            )
            SELECT
                ranked.selection_order,
                ranked.session_id AS snapshot_session_id,
                ranked.analysis_profile_key,
                ranked.analysis_profile_version,
                ranked.metric_pack_key,
                ranked.metric_pack_version,
                ranked.metric_scope_state,
                ranked.selected_metric_keys,
                ranked.data_tier,
                ranked.consent_policy_version,
                ranked.provider,
                ranked.provider_version,
                ranked.adapter_version,
                ranked.source_schema_version,
                ranked.content_schema_version,
                ranked.metric_engine_version,
                ranked.redactor_version,
                ranked.model_plan_fingerprint,
                ranked.schema_version AS persistence_schema_version,
                ranked.local_only,
                result.key AS result_key,
                result.version AS result_version,
                result.metric_schema_version AS result_metric_schema_version,
                result.value_state AS result_value_state,
                result.numeric_value AS result_numeric_value,
                result.unit AS result_unit,
                result.source AS result_source,
                result.direction AS result_direction,
                result.applicability AS result_applicability,
                result.aggregation_method AS result_aggregation_method,
                result.fraction_numerator AS result_fraction_numerator,
                result.fraction_denominator AS result_fraction_denominator,
                result.observed_count AS result_observed_count,
                result.eligible_count AS result_eligible_count,
                result.coverage AS result_coverage,
                result.confidence AS result_confidence,
                result.algorithm_id AS result_algorithm_id,
                result.algorithm_version AS result_algorithm_version,
                result.model_id AS result_model_id,
                result.model_revision AS result_model_revision,
                result.model_license AS result_model_license,
                result.tokenizer_id AS result_tokenizer_id,
                result.prompt_version AS result_prompt_version,
                result.rubric_version AS result_rubric_version
            FROM ranked
            LEFT JOIN session_analysis_results AS result
              ON result.run_id = ranked.run_id
            WHERE ranked.run_rank = 1
            ORDER BY ranked.selection_order, result.key, result.version
        """
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(query, parameters).fetchall()

        provenance: dict[str, dict[str, object]] = {}
        projected_results: dict[
            str, list[SessionAnalysisAggregationResultRecord]
        ] = {}
        for row in rows:
            session_id = row["snapshot_session_id"]
            if session_id not in provenance:
                provenance[session_id] = {
                    "session_id": session_id,
                    "analysis_profile_key": row["analysis_profile_key"],
                    "analysis_profile_version": row["analysis_profile_version"],
                    "metric_pack_key": row["metric_pack_key"],
                    "metric_pack_version": row["metric_pack_version"],
                    "metric_scope_state": SessionMetricScopeState(
                        row["metric_scope_state"]
                    ),
                    "selected_metric_keys": tuple(
                        key
                        for key in row["selected_metric_keys"].split("|")
                        if key
                    ),
                    "data_tier": DataTier(row["data_tier"]),
                    "consent_policy_version": row["consent_policy_version"],
                    "provider": Provider(row["provider"]),
                    "provider_version": row["provider_version"],
                    "adapter_version": row["adapter_version"],
                    "source_schema_version": row["source_schema_version"],
                    "content_schema_version": row["content_schema_version"],
                    "metric_engine_version": row["metric_engine_version"],
                    "redactor_version": row["redactor_version"],
                    "model_plan_fingerprint": row["model_plan_fingerprint"],
                    "persistence_schema_version": row[
                        "persistence_schema_version"
                    ],
                    "local_only": bool(row["local_only"]),
                }
                projected_results[session_id] = []
            if row["result_key"] is None:
                continue
            observation = MetricObservation(
                key=row["result_key"],
                version=row["result_version"],
                numeric_value=row["result_numeric_value"],
                unit=row["result_unit"],
                source=MetricSource(row["result_source"]),
                observed_count=row["result_observed_count"],
                eligible_count=row["result_eligible_count"],
                coverage=row["result_coverage"],
                confidence=row["result_confidence"],
            )
            projected_results[session_id].append(
                SessionAnalysisAggregationResultRecord(
                    observation=observation,
                    value_state=MetricValueState(row["result_value_state"]),
                    direction=SessionMetricDirection(row["result_direction"]),
                    applicability=SessionMetricApplicability(
                        row["result_applicability"]
                    ),
                    aggregation_method=SessionMetricAggregation(
                        row["result_aggregation_method"]
                    ),
                    metric_schema_version=row["result_metric_schema_version"],
                    fraction_numerator=row["result_fraction_numerator"],
                    fraction_denominator=row["result_fraction_denominator"],
                    algorithm_id=row["result_algorithm_id"],
                    algorithm_version=row["result_algorithm_version"],
                    model_id=row["result_model_id"],
                    model_revision=row["result_model_revision"],
                    model_license=row["result_model_license"],
                    tokenizer_id=row["result_tokenizer_id"],
                    prompt_version=row["result_prompt_version"],
                    rubric_version=row["result_rubric_version"],
                )
            )

        return tuple(
            SessionAnalysisAggregationSnapshotRecord(
                **provenance[session_id],
                results=tuple(projected_results[session_id]),
            )
            for session_id in session_ids
            if session_id in provenance
        )

    def get_results(
        self, run_id: str
    ) -> tuple[SessionAnalysisResultRecord, ...]:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM session_analysis_results
                WHERE run_id = ? ORDER BY key, version
                """,
                (run_id,),
            ).fetchall()
            results: list[SessionAnalysisResultRecord] = []
            for row in rows:
                evidence_rows = connection.execute(
                    """
                    SELECT message_id, origin
                    FROM session_analysis_result_evidence
                    WHERE run_id = ? AND key = ? AND version = ?
                    ORDER BY ordinal
                    """,
                    (run_id, row["key"], row["version"]),
                ).fetchall()
                signal_rows = connection.execute(
                    """
                    SELECT code, status, signal_count
                    FROM session_analysis_result_signals
                    WHERE run_id = ? AND key = ? AND version = ?
                    ORDER BY ordinal
                    """,
                    (run_id, row["key"], row["version"]),
                ).fetchall()
                observation = MetricObservation(
                    key=row["key"],
                    version=row["version"],
                    numeric_value=row["numeric_value"],
                    unit=row["unit"],
                    source=MetricSource(row["source"]),
                    observed_count=row["observed_count"],
                    eligible_count=row["eligible_count"],
                    coverage=row["coverage"],
                    confidence=row["confidence"],
                )
                results.append(
                    SessionAnalysisResultRecord(
                        observation=observation,
                        value_state=MetricValueState(row["value_state"]),
                        direction=SessionMetricDirection(row["direction"]),
                        applicability=SessionMetricApplicability(
                            row["applicability"]
                        ),
                        aggregation_method=SessionMetricAggregation(
                            row["aggregation_method"]
                        ),
                        metric_schema_version=row["metric_schema_version"],
                        evidence_data_tier=DataTier(row["evidence_data_tier"]),
                        fraction_numerator=row["fraction_numerator"],
                        fraction_denominator=row["fraction_denominator"],
                        evidence=tuple(
                            SessionAnalysisEvidenceRecord(
                                message_id=evidence["message_id"],
                                origin=SessionEvidenceOrigin(evidence["origin"]),
                            )
                            for evidence in evidence_rows
                        ),
                        signals=tuple(
                            SessionAnalysisSignalRecord(
                                code=signal["code"],
                                status=SessionMetricSignalStatus(signal["status"]),
                                count=signal["signal_count"],
                            )
                            for signal in signal_rows
                        ),
                        explanation_code=row["explanation_code"],
                        error_code=row["error_code"],
                        algorithm_id=row["algorithm_id"],
                        algorithm_version=row["algorithm_version"],
                        model_id=row["model_id"],
                        model_revision=row["model_revision"],
                        model_license=row["model_license"],
                        tokenizer_id=row["tokenizer_id"],
                        prompt_version=row["prompt_version"],
                        rubric_version=row["rubric_version"],
                        computed_at=from_iso(row["computed_at"]),
                    )
                )
        return tuple(results)

    def delete_for_privacy(self, run_id: str) -> bool:
        self._ensure_initialized()
        require_safe_id(run_id)
        authorization: tuple[str, str] | None = None
        publication_authorization: tuple[str, str, str, str] | None = None
        if self._begin_temporal_delete_authorization is not None:
            authorization = self._begin_temporal_delete_authorization(run_id)
        try:
            with self._connection_scope() as connection:
                try:
                    connection.execute("PRAGMA secure_delete=ON")
                    if int(connection.execute("PRAGMA secure_delete").fetchone()[0]) != 1:
                        raise DatabaseInvariantError(
                            "temporal privacy deletion requires SQLite secure_delete"
                        )
                    connection.execute("PRAGMA trusted_schema=ON")
                    connection.execute("BEGIN IMMEDIATE")
                    publication = connection.execute(
                        """SELECT job_id
                           FROM automation_session_quality_publication_deadlines
                           WHERE analysis_run_id=?""",
                        (run_id,),
                    ).fetchone()
                    if publication is not None:
                        if (
                            self._begin_publication_authorization is None
                            or self._end_publication_authorization is None
                        ):
                            raise DatabaseInvariantError(
                                "automation publication privacy deletion is not authorized"
                            )
                        job_id = str(publication["job_id"])
                        operation_id, tag = self._begin_publication_authorization(
                            job_id, "privacy"
                        )
                        publication_authorization = (
                            operation_id, job_id, "privacy", tag
                        )
                        connection.execute(
                            "INSERT INTO automation_publication_write_authorizations "
                            "VALUES(?,?,?,?)",
                            publication_authorization,
                        )
                        connection.execute(
                            """DELETE FROM automation_session_quality_publications
                               WHERE job_id=?""",
                            (job_id,),
                        )
                        connection.execute(
                            """DELETE FROM automation_session_quality_publication_closures
                               WHERE job_id=?""",
                            (job_id,),
                        )
                        connection.execute(
                            """DELETE FROM automation_session_quality_publication_deadlines
                               WHERE job_id=?""",
                            (job_id,),
                        )
                        connection.execute(
                            """DELETE FROM automation_publication_write_authorizations
                               WHERE operation_id=?""",
                            (operation_id,),
                        )
                    has_temporal_history = connection.execute(
                        """SELECT 1 FROM temporal_completion_requests
                           WHERE analysis_run_id=?""",
                        (run_id,),
                    ).fetchone() is not None
                    has_comparison_history = connection.execute(
                        """SELECT 1 FROM comparison_prepared_stratum_roots
                           WHERE expected_analysis_run_id=?""",
                        (run_id,),
                    ).fetchone() is not None
                    if has_temporal_history or has_comparison_history:
                        if authorization is None:
                            raise DatabaseInvariantError(
                                "temporal run privacy deletion is not authorized"
                            )
                        connection.execute(
                            "INSERT INTO temporal_run_delete_authorizations VALUES (?,?,?)",
                            (authorization[0], run_id, authorization[1]),
                        )
                        self._delete_synthetic_aggregation_for_run(
                            connection,
                            operation_id=authorization[0],
                            run_id=run_id,
                        )
                    cursor = connection.execute(
                        "DELETE FROM session_analysis_runs WHERE run_id=?",
                        (run_id,),
                    )
                    if has_comparison_history:
                        connection.execute(
                            """DELETE FROM comparison_prepared_stratum_roots
                               WHERE expected_analysis_run_id=?""",
                            (run_id,),
                        )
                    if has_temporal_history or has_comparison_history:
                        connection.execute(
                            """DELETE FROM temporal_run_delete_authorizations
                               WHERE operation_id=? AND run_id=?""",
                            (authorization[0], run_id),
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
                            "temporal privacy deletion committed; WAL purge pending"
                        )
                    return cursor.rowcount == 1 or has_comparison_history
                except Exception:
                    connection.rollback()
                    connection.execute("PRAGMA trusted_schema=OFF")
                    raise
        finally:
            if (
                publication_authorization is not None
                and self._end_publication_authorization is not None
            ):
                self._end_publication_authorization(*publication_authorization)
            if (
                authorization is not None
                and self._end_temporal_delete_authorization is not None
            ):
                self._end_temporal_delete_authorization(
                    authorization[0], run_id, authorization[1]
                )
