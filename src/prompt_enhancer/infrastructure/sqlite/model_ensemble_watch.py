"""SQLite persistence for the content-free continuous ensemble watch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import hashlib

from ...application.analysis.model_ensemble_watch import (
    MODEL_ENSEMBLE_ATTEMPT_CONTRACT_VERSION,
    MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED,
    MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
    MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED,
    ModelEnsembleAttemptRecord,
    ModelEnsembleAttemptStageReceipt,
    ModelEnsembleAttemptState,
    ModelEnsembleCanonicalHead,
    ModelEnsembleStageState,
    ModelEnsembleWatchFailureClass,
    ModelEnsembleWatchFailurePolicy,
    ModelEnsembleWatchLease,
    ModelEnsembleWatchRecord,
    ModelEnsembleWatchRepository,
    ModelEnsembleWatchState,
    ModelEnsembleTrajectoryPage,
    ModelEnsembleTrajectoryPoint,
)
from ...application.analysis.model_ensemble import (
    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
    SessionModelEnsembleMetricReceipt,
    SessionModelEnsembleTypedMetricReceipt,
    SourceCoverageState,
)
from ...application.analysis.metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    MetricValueStateV2,
)
from ...application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
    MetricStateV2,
    OpportunityStatistics,
)
from ...application.analysis.session_model_ensemble import SessionModelEnsembleOutcome
from ...application.analysis.probabilistic_metrics import (
    PROBABILISTIC_METRIC_PROJECTION_VERSION,
    PredictiveMetricState,
    PredictiveMetricTarget,
    SessionPredictiveMetricSummary,
)
from ...application.persistence import MetricValueState
from ...database import DatabaseInvariantError
from ...domain import Provider
from ..identifiers import LocalArtifactIdFactory
from ._common import ConnectionScope, from_iso, require_safe_id, require_safe_label, to_iso
from .model_ensemble import (
    METRIC_V2_SIDECARS,
    SqliteSessionModelEnsembleRepository,
)


def _record(row: object) -> ModelEnsembleWatchRecord:
    return ModelEnsembleWatchRecord(
        watch_id=row["watch_id"],  # type: ignore[index]
        provider=Provider(row["provider"]),  # type: ignore[index]
        project_id=row["project_id"],  # type: ignore[index]
        session_id=row["session_id"],  # type: ignore[index]
        max_messages=int(row["max_messages"]),  # type: ignore[index]
        state=ModelEnsembleWatchState(row["state"]),  # type: ignore[index]
        generation=int(row["generation"]),  # type: ignore[index]
        progress_completed=int(row["progress_completed"]),  # type: ignore[index]
        progress_total=int(row["progress_total"]),  # type: ignore[index]
        latest_run_id=row["latest_run_id"],  # type: ignore[index]
        latest_input_fingerprint=row["latest_input_fingerprint"],  # type: ignore[index]
        last_error_code=row["last_error_code"],  # type: ignore[index]
        next_check_at=from_iso(row["next_check_at"]),  # type: ignore[index]
        lease_owner=row["lease_owner"],  # type: ignore[index]
        lease_token=row["lease_token"],  # type: ignore[index]
        lease_expires_at=(
            None
            if row["lease_expires_at"] is None  # type: ignore[index]
            else from_iso(row["lease_expires_at"])  # type: ignore[index]
        ),
        failure_streak=int(row["failure_streak"]),  # type: ignore[index]
        quarantined_at=(
            None
            if row["quarantined_at"] is None  # type: ignore[index]
            else from_iso(row["quarantined_at"])  # type: ignore[index]
        ),
        quarantine_reason_code=row["quarantine_reason_code"],  # type: ignore[index]
        created_at=from_iso(row["created_at"]),  # type: ignore[index]
        updated_at=from_iso(row["updated_at"]),  # type: ignore[index]
    )


def _attempt(row: object) -> ModelEnsembleAttemptRecord:
    return ModelEnsembleAttemptRecord(
        attempt_id=row["attempt_id"],  # type: ignore[index]
        watch_id=row["watch_id"],  # type: ignore[index]
        generation=int(row["generation"]),  # type: ignore[index]
        state=ModelEnsembleAttemptState(row["state"]),  # type: ignore[index]
        prior_head_run_id=row["prior_head_run_id"],  # type: ignore[index]
        published_run_id=row["published_run_id"],  # type: ignore[index]
        progress_completed=int(row["progress_completed"]),  # type: ignore[index]
        progress_total=int(row["progress_total"]),  # type: ignore[index]
        stage_count=int(row["stage_count"]),  # type: ignore[index]
        warning_count=int(row["warning_count"]),  # type: ignore[index]
        error_code=row["error_code"],  # type: ignore[index]
        requested_at=from_iso(row["requested_at"]),  # type: ignore[index]
        started_at=from_iso(row["started_at"]),  # type: ignore[index]
        completed_at=(
            None
            if row["completed_at"] is None  # type: ignore[index]
            else from_iso(row["completed_at"])  # type: ignore[index]
        ),
    )


def _attempt_stage(row: object) -> ModelEnsembleAttemptStageReceipt:
    unloaded = row["unloaded_after_stage"]  # type: ignore[index]
    return ModelEnsembleAttemptStageReceipt(
        attempt_id=row["attempt_id"],  # type: ignore[index]
        stage_ordinal=int(row["stage_ordinal"]),  # type: ignore[index]
        stage_key=row["stage_key"],  # type: ignore[index]
        state=ModelEnsembleStageState(row["state"]),  # type: ignore[index]
        model_key=row["model_key"],  # type: ignore[index]
        repository_id=row["repository_id"],  # type: ignore[index]
        revision=row["revision"],  # type: ignore[index]
        error_code=row["error_code"],  # type: ignore[index]
        device=row["device"],  # type: ignore[index]
        quantization=row["quantization"],  # type: ignore[index]
        inference_latency_ms=row["inference_latency_ms"],  # type: ignore[index]
        peak_accelerator_memory_mb=row["peak_accelerator_memory_mb"],  # type: ignore[index]
        process_rss_mb=row["process_rss_mb"],  # type: ignore[index]
        evaluated_case_count=row["evaluated_case_count"],  # type: ignore[index]
        contributed_case_count=row["contributed_case_count"],  # type: ignore[index]
        unloaded_after_stage=None if unloaded is None else bool(unloaded),
        completed_at=from_iso(row["completed_at"]),  # type: ignore[index]
    )


def _predictive_identity(connection, run_id: str | None) -> tuple[object, ...] | None:
    if run_id is None:
        return None
    seal = connection.execute(
        """SELECT projection_version,registry_version,model_set_version,sample_count
           FROM session_model_ensemble_predictive_metric_seals
           WHERE run_id=? AND projection_version=?""",
        (run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
    ).fetchone()
    if seal is None:
        return None
    metrics = tuple(
        (
            item["metric_key"],
            item["target"],
            item["model_set_version"],
            item["calibration_version"],
            item["contract_version"],
            item["contract_fingerprint"],
        )
        for item in connection.execute(
            """SELECT metric_key,target,model_set_version,calibration_version,
                      contract_version,contract_fingerprint
               FROM session_model_ensemble_predictive_metrics
               WHERE run_id=? AND projection_version=? ORDER BY metric_key""",
            (run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
        ).fetchall()
    )
    stages = tuple(
        (
            item["model_key"],
            item["revision"],
            item["quantization"],
        )
        for item in connection.execute(
            """SELECT model_key,revision,quantization
               FROM session_model_ensemble_predictive_model_stages
               WHERE run_id=? AND projection_version=? ORDER BY stage_ordinal""",
            (run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
        ).fetchall()
    )
    return (
        seal["projection_version"],
        seal["registry_version"],
        seal["model_set_version"],
        int(seal["sample_count"]),
        metrics,
        stages,
    )


def _metric_v2_seal(connection, run_id: str) -> tuple[object, str] | None:
    """Return one run's V2 seal and its states table, newest identity first.

    A run carries at most one sidecar identity, so the first hit is the whole
    answer.  Two runs sealed under different projection identities have
    different ``projection_version`` values and are therefore not comparable,
    which is exactly what ``_metric_v2_identity`` reports.
    """

    for version, states_table, seals_table in METRIC_V2_SIDECARS:
        profile_columns = (
            ",seal.profile_source,seal.profile_id,seal.profile_revision,"
            "seal.profile_fingerprint,seal.profile_schema_version,"
            "seal.profile_policy_version"
            if version in {
                METRIC_PROJECTION_V2_VERSION_5,
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
            else ""
        )
        evidence_columns = (
            ",seal.requirement_plan_source,"
            "seal.requirement_plan_confirmation_id,"
            "seal.requirement_plan_proposal_id,"
            "seal.requirement_plan_evidence_fingerprint,"
            "seal.requirement_plan_schema_version,"
            "seal.requirement_plan_policy_version"
            if version in {
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
            else ""
        )
        action_columns = (
            ",action_binding.session_id AS requirement_action_session_id,"
            "action_binding.source_window_fingerprint AS "
            "requirement_action_source_window_fingerprint,"
            "seal.requirement_action_source,"
            "seal.requirement_action_source_run_id,"
            "seal.requirement_action_requirement_plan_confirmation_id,"
            "seal.requirement_action_requirement_plan_evidence_fingerprint,"
            "seal.requirement_action_candidate_manifest_fingerprint,"
            "seal.requirement_action_reviewed_descriptor_set_fingerprint,"
            "seal.requirement_action_confirmation_id,"
            "seal.requirement_action_proposal_id,"
            "seal.requirement_action_evidence_fingerprint,"
            "seal.requirement_action_schema_version,"
            "seal.requirement_action_policy_version"
            if version in {
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
            else ""
        )
        action_join = (
            " JOIN session_model_ensemble_requirement_action_bindings "
            "AS action_binding ON action_binding.run_id=seal.run_id"
            if version in {
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
            else ""
        )
        verification_columns = (
            ",seal.requirement_verification_source,"
            "seal.requirement_verification_requirement_plan_confirmation_id,"
            "seal.requirement_verification_requirement_plan_evidence_fingerprint,"
            "seal.requirement_verification_opportunity_set_fingerprint,"
            "seal.requirement_verification_evidence_set_fingerprint,"
            "seal.requirement_verification_through_revision,"
            "seal.requirement_verification_binding_fingerprint"
            if version == METRIC_PROJECTION_V2_VERSION_8
            else ""
        )
        seal = connection.execute(
            f"""SELECT publication_key,publication_version,registry_version,
                       contract_set_fingerprint,projection_version,
                       guidance_contract_version,guidance_template_catalog_version,
                       source,canonical_live_snapshot,model_stage_consumed,
                       compatibility_preview{profile_columns}{evidence_columns}
                       {action_columns}{verification_columns}
                FROM {seals_table} AS seal{action_join} WHERE seal.run_id=?""",
            (run_id,),
        ).fetchone()
        if seal is not None:
            return seal, states_table
    return None


def _metric_v2_identity(connection, run_id: str | None) -> tuple[object, ...] | None:
    """Return the measured-contract identity used for trajectory comparability.

    Historical runs legitimately have no V2 seal.  Two such runs remain in the
    legacy comparison cohort; a legacy run and a canonical V2 run never do.
    R5 compares stable profile authority, r6 also compares reviewed
    requirement-plan authority, and r7 adds the complete stable
    requirement-action authority identity.  Binding and combined-publication
    fingerprints intentionally remain out because they seal per-run fields
    such as ``bound_at``; treating those receipt hashes as a cohort identity
    would make every fresh run incomparable under the same reviewed evidence.
    """

    if run_id is None:
        return None
    found = _metric_v2_seal(connection, run_id)
    if found is None:
        return None
    seal, _states_table = found
    identity = (
        seal["publication_key"],
        int(seal["publication_version"]),
        seal["registry_version"],
        seal["contract_set_fingerprint"],
        seal["projection_version"],
        seal["guidance_contract_version"],
        seal["guidance_template_catalog_version"],
        seal["source"],
        int(seal["canonical_live_snapshot"]),
        int(seal["model_stage_consumed"]),
        int(seal["compatibility_preview"]),
    )
    if seal["projection_version"] not in {
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }:
        return (*identity, *(None for _ in range(32)))
    profile_identity = (
        *identity,
        seal["profile_source"],
        seal["profile_id"],
        seal["profile_revision"],
        seal["profile_fingerprint"],
        seal["profile_schema_version"],
        seal["profile_policy_version"],
    )
    if seal["projection_version"] == METRIC_PROJECTION_V2_VERSION_5:
        return (*profile_identity, *(None for _ in range(26)))
    requirement_plan_identity = (
        *profile_identity,
        seal["requirement_plan_source"],
        seal["requirement_plan_confirmation_id"],
        seal["requirement_plan_proposal_id"],
        seal["requirement_plan_evidence_fingerprint"],
        seal["requirement_plan_schema_version"],
        seal["requirement_plan_policy_version"],
    )
    if seal["projection_version"] == METRIC_PROJECTION_V2_VERSION_6:
        return (*requirement_plan_identity, *(None for _ in range(20)))
    requirement_action_identity = (
        *requirement_plan_identity,
        seal["requirement_action_source"],
        seal["requirement_action_session_id"],
        seal["requirement_action_source_window_fingerprint"],
        seal["requirement_action_source_run_id"],
        seal["requirement_action_requirement_plan_confirmation_id"],
        seal["requirement_action_requirement_plan_evidence_fingerprint"],
        seal["requirement_action_candidate_manifest_fingerprint"],
        seal["requirement_action_reviewed_descriptor_set_fingerprint"],
        seal["requirement_action_confirmation_id"],
        seal["requirement_action_proposal_id"],
        seal["requirement_action_evidence_fingerprint"],
        seal["requirement_action_schema_version"],
        seal["requirement_action_policy_version"],
    )
    if seal["projection_version"] == METRIC_PROJECTION_V2_VERSION_7:
        return (*requirement_action_identity, *(None for _ in range(7)))
    return (
        *requirement_action_identity,
        seal["requirement_verification_source"],
        seal["requirement_verification_requirement_plan_confirmation_id"],
        seal["requirement_verification_requirement_plan_evidence_fingerprint"],
        seal["requirement_verification_opportunity_set_fingerprint"],
        seal["requirement_verification_evidence_set_fingerprint"],
        seal["requirement_verification_through_revision"],
        seal["requirement_verification_binding_fingerprint"],
    )


def _metric_v2_states(connection, run_id: str) -> tuple[MetricStateV2, ...]:
    found = _metric_v2_seal(connection, run_id)
    if found is None:
        return ()
    _seal, states_table = found
    return tuple(
        MetricStateV2(
            metric_key=item["metric_key"],
            registry_version=item["registry_version"],
            contract_version=item["contract_version"],
            contract_fingerprint=item["contract_fingerprint"],
            evidence_authority=EvidenceAuthority(item["evidence_authority"]),
            value_state=MetricValueStateV2(item["value_state"]),
            explanation_code=item["explanation_code"],
            numerator=item["numerator"],
            denominator=item["denominator"],
            numeric_value=item["numeric_value"],
            censoring_lower_bound=item["censoring_lower_bound"],
            censoring_upper_bound=item["censoring_upper_bound"],
            statistics=OpportunityStatistics(
                metric_key=item["metric_key"],
                denominator_basis=DenominatorBasis(item["denominator_basis"]),
                opportunity_unit_kind=item["opportunity_unit_kind"],
                capability_available=bool(item["capability_available"]),
                source_complete=bool(item["source_complete"]),
                eligible_count=item["eligible_count"],
                met_count=item["met_count"],
                not_met_count=item["not_met_count"],
                pending_count=item["pending_count"],
                unknown_count=item["unknown_count"],
                superseded_excluded_count=item["superseded_excluded_count"],
                distinct_owner_count=item["distinct_owner_count"],
            ),
            projection_version=item["projection_version"],
            product_metric_eligible=bool(item["product_metric_eligible"]),
        )
        for item in connection.execute(
            f"""SELECT * FROM {states_table}
                WHERE run_id=? ORDER BY metric_ordinal""",
            (run_id,),
        ).fetchall()
    )


class SqliteModelEnsembleWatchRepository(ModelEnsembleWatchRepository):
    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        identifiers: LocalArtifactIdFactory | None = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._run_authority = SqliteSessionModelEnsembleRepository(
            connection_scope,
            ensure_initialized,
            identifiers=identifiers,
        )

    def _validate_requirement_action_trajectory_authority(
        self,
        connection: object,
        run_id: str,
    ) -> None:
        """Fail closed unless an r7/r8 trajectory point has exact authority."""

        self._run_authority.validate_requirement_plan_run_authority(
            connection,
            run_id,
        )
        seal = None
        seal_version = None
        for version, table in (
            (
                METRIC_PROJECTION_V2_VERSION_8,
                "session_model_ensemble_metric_publication_v2_seals_r8",
            ),
            (
                METRIC_PROJECTION_V2_VERSION_7,
                "session_model_ensemble_metric_publication_v2_seals_r7",
            ),
        ):
            seal = connection.execute(  # type: ignore[attr-defined]
                f"""SELECT requirement_action_source,
                           requirement_action_source_run_id,
                           requirement_action_requirement_plan_confirmation_id,
                           requirement_action_requirement_plan_evidence_fingerprint,
                           requirement_action_candidate_manifest_fingerprint,
                           requirement_action_reviewed_descriptor_set_fingerprint,
                           requirement_action_confirmation_id,
                           requirement_action_proposal_id,
                           requirement_action_evidence_fingerprint,
                           requirement_action_schema_version,
                           requirement_action_policy_version
                    FROM {table} WHERE run_id=?""",
                (run_id,),
            ).fetchone()
            if seal is not None:
                seal_version = version
                break
        binding = self._run_authority.validate_requirement_action_run_authority(
            connection,
            run_id,
        )
        if seal is None and binding is None:
            return
        if seal is None or binding is None or (
            seal["requirement_action_source"] != binding.evidence_source.value
            or seal["requirement_action_source_run_id"] != binding.source_run_id
            or seal["requirement_action_requirement_plan_confirmation_id"]
            != binding.requirement_plan_confirmation_id
            or seal["requirement_action_requirement_plan_evidence_fingerprint"]
            != binding.requirement_plan_evidence_fingerprint
            or seal["requirement_action_candidate_manifest_fingerprint"]
            != binding.candidate_manifest_fingerprint
            or seal["requirement_action_reviewed_descriptor_set_fingerprint"]
            != binding.reviewed_descriptor_set_fingerprint
            or seal["requirement_action_confirmation_id"] != binding.confirmation_id
            or seal["requirement_action_proposal_id"] != binding.proposal_id
            or seal["requirement_action_evidence_fingerprint"]
            != binding.evidence_fingerprint
            or seal["requirement_action_schema_version"]
            != binding.evidence_schema_version
            or seal["requirement_action_policy_version"]
            != binding.evidence_policy_version
        ):
            raise DatabaseInvariantError(
                "trajectory requirement-action authority is invalid"
            )
        verification_binding = (
            self._run_authority.validate_requirement_verification_run_authority(
                connection,
                run_id,
            )
        )
        if seal_version != METRIC_PROJECTION_V2_VERSION_8:
            if verification_binding is not None:
                raise DatabaseInvariantError(
                    "trajectory requirement-verification authority is invalid"
                )
            return
        verification_seal = connection.execute(  # type: ignore[attr-defined]
            """SELECT requirement_verification_source,
                      requirement_verification_requirement_plan_confirmation_id,
                      requirement_verification_requirement_plan_evidence_fingerprint,
                      requirement_verification_opportunity_set_fingerprint,
                      requirement_verification_evidence_set_fingerprint,
                      requirement_verification_through_revision,
                      requirement_verification_binding_fingerprint
               FROM session_model_ensemble_metric_publication_v2_seals_r8
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if (
            verification_binding is None
            or verification_seal is None
            or verification_seal["requirement_verification_source"]
            != verification_binding.evidence_source.value
            or verification_seal[
                "requirement_verification_requirement_plan_confirmation_id"
            ]
            != verification_binding.requirement_plan_confirmation_id
            or verification_seal[
                "requirement_verification_requirement_plan_evidence_fingerprint"
            ]
            != verification_binding.requirement_plan_evidence_fingerprint
            or verification_seal[
                "requirement_verification_opportunity_set_fingerprint"
            ]
            != verification_binding.opportunity_set_fingerprint
            or verification_seal[
                "requirement_verification_evidence_set_fingerprint"
            ]
            != verification_binding.evidence_set_fingerprint
            or verification_seal["requirement_verification_through_revision"]
            != verification_binding.through_revision
            or verification_seal["requirement_verification_binding_fingerprint"]
            != verification_binding.binding_fingerprint
        ):
            raise DatabaseInvariantError(
                "trajectory requirement-verification authority is invalid"
            )

    @staticmethod
    def _row(connection: object, watch_id: str):
        return connection.execute(  # type: ignore[attr-defined]
            "SELECT * FROM session_model_ensemble_watches WHERE watch_id=?",
            (watch_id,),
        ).fetchone()

    @staticmethod
    def _seal_terminal_attempts(
        connection: object,
        attempt_ids: tuple[str, ...],
    ) -> None:
        """Seal complete terminal graphs without scanning the unbounded ledger."""

        if not attempt_ids:
            return
        placeholders = ",".join("?" for _ in attempt_ids)
        connection.execute(  # type: ignore[attr-defined]
            """INSERT INTO session_model_ensemble_analysis_attempt_seals(
                   attempt_id,contract_version,stage_count,warning_count,sealed_at,
                   local_only,content_persisted
               )
               SELECT attempt.attempt_id,'model-ensemble-attempt-stage-seal-v1',
                      attempt.stage_count,attempt.warning_count,attempt.completed_at,1,0
               FROM session_model_ensemble_analysis_attempts attempt
               WHERE attempt.attempt_id IN ("""
            + placeholders
            + """)
                 AND attempt.state<>'running' AND attempt.completed_at IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM session_model_ensemble_analysis_attempt_seals seal
                     WHERE seal.attempt_id=attempt.attempt_id
                 )
                 AND attempt.stage_count=(
                     SELECT COUNT(*)
                     FROM session_model_ensemble_analysis_attempt_stages stage
                     WHERE stage.attempt_id=attempt.attempt_id
                 )
                 AND attempt.warning_count=(
                     SELECT COUNT(*)
                     FROM session_model_ensemble_analysis_attempt_stages stage
                     WHERE stage.attempt_id=attempt.attempt_id
                       AND stage.state<>'completed'
                 )""",
            attempt_ids,
        )

    @classmethod
    def _recover_expired_leases(
        cls,
        connection: object,
        *,
        now: datetime,
        policy: ModelEnsembleWatchFailurePolicy,
    ) -> int:
        """Seal expired attempts and apply the durable failure policy.

        An unexpired lease may belong to another live process and is never
        stolen.  Recovery is performed in the caller's writer transaction so
        the attempt seal, streak, retry time, and quarantine marker cannot
        become torn.
        """

        stamp = to_iso(now)
        rows = connection.execute(  # type: ignore[attr-defined]
            """SELECT watch.watch_id,watch.failure_streak,attempt.attempt_id
               FROM session_model_ensemble_watches watch
               LEFT JOIN session_model_ensemble_analysis_attempts attempt
                 ON attempt.watch_id=watch.watch_id
                AND attempt.generation=watch.generation
                AND attempt.state='running'
               WHERE watch.state='running' AND watch.lease_expires_at<=?
                 AND (attempt.state='running' OR attempt.attempt_id IS NULL)
               ORDER BY watch.watch_id""",
            (stamp,),
        ).fetchall()
        for row in rows:
            streak = min(64, int(row["failure_streak"]) + 1)
            quarantined = policy.quarantines(streak)
            next_check_at = now if quarantined else now + policy.next_delay(streak)
            quarantine_code = (
                MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED if quarantined else None
            )
            if row["attempt_id"] is not None:
                attempt_result = connection.execute(  # type: ignore[attr-defined]
                    """UPDATE session_model_ensemble_analysis_attempts
                       SET state='failed',error_code=?,completed_at=?
                       WHERE attempt_id=? AND state='running'""",
                    (
                        MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED,
                        stamp,
                        row["attempt_id"],
                    ),
                )
                if attempt_result.rowcount != 1:
                    raise ValueError("expired watch attempt changed during recovery")
                cls._seal_terminal_attempts(connection, (row["attempt_id"],))
            watch_result = connection.execute(  # type: ignore[attr-defined]
                """UPDATE session_model_ensemble_watches
                   SET state='failed',lease_owner=NULL,lease_token=NULL,
                       lease_expires_at=NULL,last_error_code=?,failure_streak=?,
                       next_check_at=?,quarantined_at=?,quarantine_reason_code=?,
                       updated_at=?
                   WHERE watch_id=? AND state='running' AND lease_expires_at<=?""",
                (
                    MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED,
                    streak,
                    to_iso(next_check_at),
                    stamp if quarantined else None,
                    quarantine_code,
                    stamp,
                    row["watch_id"],
                    stamp,
                ),
            )
            if watch_result.rowcount != 1:
                raise ValueError("expired watch lease changed during recovery")
        return len(rows)

    def enable(
        self,
        *,
        watch_id: str,
        provider: Provider,
        project_id: str,
        session_id: str,
        max_messages: int = 100,
        now: datetime,
    ) -> ModelEnsembleWatchRecord:
        require_safe_id(watch_id)
        require_safe_id(project_id)
        require_safe_id(session_id)
        if (
            not isinstance(max_messages, int)
            or isinstance(max_messages, bool)
            or not 1 <= max_messages <= 100
        ):
            raise ValueError("watch message window is invalid")
        self._ensure_initialized()
        stamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                target = connection.execute(
                    """SELECT 1 FROM sessions s
                       JOIN projects p ON p.project_id=s.project_id
                       WHERE s.session_id=? AND s.project_id=?
                         AND s.provider=? AND p.provider=?""",
                    (session_id, project_id, provider.value, provider.value),
                ).fetchone()
                if target is None:
                    raise ValueError("watch target is outside the safe index")
                existing = self._row(connection, watch_id)
                if (
                    existing is not None
                    and existing["state"] != "disabled"
                    and int(existing["max_messages"]) == max_messages
                ):
                    connection.rollback()
                    return _record(existing)
                terminal_attempt_ids = tuple(
                    row["attempt_id"]
                    for row in connection.execute(
                        """SELECT attempt.attempt_id
                           FROM session_model_ensemble_analysis_attempts attempt
                           JOIN session_model_ensemble_watches watch
                             ON watch.watch_id=attempt.watch_id
                           WHERE attempt.state='running' AND watch.state<>'disabled'"""
                    ).fetchall()
                )
                connection.execute(
                    """UPDATE session_model_ensemble_analysis_attempts
                       SET state='cancelled',error_code='watch_reconfigured',completed_at=?
                       WHERE state='running' AND watch_id IN (
                           SELECT watch_id FROM session_model_ensemble_watches
                           WHERE state<>'disabled')""",
                    (stamp,),
                )
                self._seal_terminal_attempts(connection, terminal_attempt_ids)
                connection.execute(
                    """UPDATE session_model_ensemble_watches
                       SET state='disabled',lease_owner=NULL,lease_token=NULL,
                           lease_expires_at=NULL,updated_at=?
                       WHERE state<>'disabled' AND watch_id<>?""",
                    (stamp, watch_id),
                )
                if existing is None:
                    connection.execute(
                        """INSERT INTO session_model_ensemble_watches(
                           watch_id,provider,project_id,session_id,max_messages,state,generation,
                           progress_completed,progress_total,latest_run_id,
                           latest_input_fingerprint,last_error_code,next_check_at,
                           lease_owner,lease_token,lease_expires_at,failure_streak,
                           quarantined_at,quarantine_reason_code,created_at,updated_at
                           ) VALUES(?,?,?,?,?,'queued',0,0,?,NULL,NULL,NULL,?,NULL,NULL,NULL,
                                    0,NULL,NULL,?,?)""",
                        (
                            watch_id,
                            provider.value,
                            project_id,
                            session_id,
                            max_messages,
                            MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
                            stamp,
                            stamp,
                            stamp,
                        ),
                    )
                else:
                    if existing["state"] != "disabled":
                        connection.execute(
                            """UPDATE session_model_ensemble_watches
                               SET state='disabled',lease_owner=NULL,lease_token=NULL,
                                   lease_expires_at=NULL,updated_at=? WHERE watch_id=?""",
                            (stamp, watch_id),
                        )
                    same_scope = int(existing["max_messages"]) == max_messages
                    if same_scope:
                        connection.execute(
                            """UPDATE session_model_ensemble_watches
                               SET state='queued',max_messages=?,progress_completed=0,
                                   last_error_code=NULL,next_check_at=?,lease_owner=NULL,
                                   lease_token=NULL,lease_expires_at=NULL,
                                   failure_streak=0,quarantined_at=NULL,
                                   quarantine_reason_code=NULL,updated_at=?
                               WHERE watch_id=?""",
                            (max_messages, stamp, stamp, watch_id),
                        )
                    else:
                        connection.execute(
                            """UPDATE session_model_ensemble_watches
                               SET state='queued',max_messages=?,
                                   generation=generation+1,progress_completed=0,
                                   latest_run_id=NULL,latest_input_fingerprint=NULL,
                                   last_error_code=NULL,next_check_at=?,lease_owner=NULL,
                                   lease_token=NULL,lease_expires_at=NULL,
                                   failure_streak=0,quarantined_at=NULL,
                                   quarantine_reason_code=NULL,updated_at=?
                               WHERE watch_id=?""",
                            (max_messages, stamp, stamp, watch_id),
                        )
                row = self._row(connection, watch_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if row is None:
            raise RuntimeError("watch enable did not persist")
        return _record(row)

    def disable(self, watch_id: str, *, now: datetime) -> ModelEnsembleWatchRecord:
        require_safe_id(watch_id)
        self._ensure_initialized()
        stamp = to_iso(now)
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            terminal_attempt_ids = tuple(
                row["attempt_id"]
                for row in connection.execute(
                    """SELECT attempt_id
                       FROM session_model_ensemble_analysis_attempts
                       WHERE watch_id=? AND state='running'""",
                    (watch_id,),
                ).fetchall()
            )
            connection.execute(
                """UPDATE session_model_ensemble_analysis_attempts
                   SET state='cancelled',error_code='watch_disabled',completed_at=?
                   WHERE watch_id=? AND state='running'""",
                (stamp, watch_id),
            )
            self._seal_terminal_attempts(connection, terminal_attempt_ids)
            result = connection.execute(
                """UPDATE session_model_ensemble_watches
                   SET state='disabled',lease_owner=NULL,lease_token=NULL,
                       lease_expires_at=NULL,failure_streak=0,
                       quarantined_at=NULL,quarantine_reason_code=NULL,updated_at=?
                   WHERE watch_id=?""",
                (stamp, watch_id),
            )
            if result.rowcount != 1:
                connection.rollback()
                raise ValueError("watch does not exist")
            row = self._row(connection, watch_id)
            connection.commit()
        return _record(row)

    def get(self, watch_id: str) -> ModelEnsembleWatchRecord | None:
        require_safe_id(watch_id)
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            row = self._row(connection, watch_id)
        return None if row is None else _record(row)

    def get_active(self) -> ModelEnsembleWatchRecord | None:
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT * FROM session_model_ensemble_watches
                   WHERE state<>'disabled'
                   ORDER BY updated_at DESC,watch_id LIMIT 1"""
            ).fetchone()
        return None if row is None else _record(row)

    def get_for_session(self, session_id: str) -> ModelEnsembleWatchRecord | None:
        require_safe_id(session_id)
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT * FROM session_model_ensemble_watches
                   WHERE session_id=? LIMIT 1""",
                (session_id,),
            ).fetchone()
        return None if row is None else _record(row)

    def get_attempt(self, attempt_id: str) -> ModelEnsembleAttemptRecord | None:
        require_safe_id(attempt_id)
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT * FROM session_model_ensemble_analysis_attempts attempt
                   WHERE attempt_id=? AND (
                       attempt.state='running' OR EXISTS (
                           SELECT 1 FROM session_model_ensemble_analysis_attempt_seals seal
                           WHERE seal.attempt_id=attempt.attempt_id
                       )
                   )""",
                (attempt_id,),
            ).fetchone()
        return None if row is None else _attempt(row)

    def get_attempt_stages(
        self, attempt_id: str
    ) -> tuple[ModelEnsembleAttemptStageReceipt, ...]:
        require_safe_id(attempt_id)
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """SELECT stage.*
                   FROM session_model_ensemble_analysis_attempt_stages stage
                   JOIN session_model_ensemble_analysis_attempt_seals seal
                     ON seal.attempt_id=stage.attempt_id
                   WHERE stage.attempt_id=? ORDER BY stage.stage_ordinal""",
                (attempt_id,),
            ).fetchall()
        return tuple(_attempt_stage(row) for row in rows)

    def get_attempt_snapshot(
        self, attempt_id: str
    ) -> tuple[
        ModelEnsembleAttemptRecord,
        tuple[ModelEnsembleAttemptStageReceipt, ...],
    ] | None:
        require_safe_id(attempt_id)
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    """SELECT * FROM session_model_ensemble_analysis_attempts attempt
                       WHERE attempt_id=? AND (
                           attempt.state='running' OR EXISTS (
                               SELECT 1 FROM session_model_ensemble_analysis_attempt_seals seal
                               WHERE seal.attempt_id=attempt.attempt_id
                           )
                       )""",
                    (attempt_id,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                stages = ()
                if row["state"] != "running":
                    stages = tuple(
                        _attempt_stage(stage)
                        for stage in connection.execute(
                            """SELECT stage.*
                               FROM session_model_ensemble_analysis_attempt_stages stage
                               JOIN session_model_ensemble_analysis_attempt_seals seal
                                 ON seal.attempt_id=stage.attempt_id
                               WHERE stage.attempt_id=? ORDER BY stage.stage_ordinal""",
                            (attempt_id,),
                        ).fetchall()
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return _attempt(row), stages

    def list_attempts(
        self, watch_id: str, *, limit: int
    ) -> tuple[ModelEnsembleAttemptRecord, ...]:
        require_safe_id(watch_id)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 60
        ):
            raise ValueError("attempt page is invalid")
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """SELECT * FROM session_model_ensemble_analysis_attempts attempt
                   WHERE watch_id=? AND (
                       attempt.state='running' OR EXISTS (
                           SELECT 1 FROM session_model_ensemble_analysis_attempt_seals seal
                           WHERE seal.attempt_id=attempt.attempt_id
                       )
                   ) ORDER BY generation DESC LIMIT ?""",
                (watch_id, limit),
            ).fetchall()
        return tuple(_attempt(row) for row in rows)

    def canonical_head(self, watch_id: str) -> ModelEnsembleCanonicalHead:
        require_safe_id(watch_id)
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                watch_row = self._row(connection, watch_id)
                if watch_row is None:
                    raise ValueError("watch does not exist")
                publication = connection.execute(
                    """SELECT generation FROM session_model_ensemble_watch_publications
                       WHERE watch_id=? AND run_id=?""",
                    (watch_id, watch_row["latest_run_id"]),
                ).fetchone()
                effective_head_run_id = (
                    watch_row["latest_run_id"] if publication is not None else None
                )
                attempt_row = None
                if watch_row["state"] != "queued":
                    attempt_row = connection.execute(
                        """SELECT * FROM session_model_ensemble_analysis_attempts attempt
                           WHERE watch_id=? AND generation=? AND (
                               attempt.state='running' OR EXISTS (
                                   SELECT 1 FROM session_model_ensemble_analysis_attempt_seals seal
                                   WHERE seal.attempt_id=attempt.attempt_id
                               )
                           )
                             AND (
                               attempt.state NOT IN ('completed','partial')
                               OR attempt.published_run_id=?
                             )
                             AND (
                               ? IS NOT NULL
                               OR attempt.prior_head_run_id IS NULL
                             )
                           ORDER BY generation DESC LIMIT 1""",
                        (
                            watch_id,
                            int(watch_row["generation"]),
                            effective_head_run_id,
                            effective_head_run_id,
                        ),
                    ).fetchone()
                stages = ()
                if attempt_row is not None and attempt_row["state"] != "running":
                    stages = tuple(
                        _attempt_stage(row)
                        for row in connection.execute(
                            """SELECT stage.*
                               FROM session_model_ensemble_analysis_attempt_stages stage
                               JOIN session_model_ensemble_analysis_attempt_seals seal
                                 ON seal.attempt_id=stage.attempt_id
                               WHERE stage.attempt_id=? ORDER BY stage.stage_ordinal""",
                            (attempt_row["attempt_id"],),
                        ).fetchall()
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        watch_record = _record(watch_row)
        if publication is None and watch_record.latest_run_id is not None:
            # v30 intentionally did not invent publication lineage for legacy
            # watch heads.  Such a row is not a canonical v2 snapshot until a
            # fresh analysis publishes it through the sealed ledger.
            watch_record = watch_record.model_copy(
                update={
                    "latest_run_id": None,
                    "latest_input_fingerprint": None,
                }
            )
        return ModelEnsembleCanonicalHead(
            watch=watch_record,
            head_run_id=effective_head_run_id,
            head_generation=(
                None if publication is None else int(publication["generation"])
            ),
            latest_attempt=None if attempt_row is None else _attempt(attempt_row),
            stages=stages,
        )

    def request_refresh(
        self,
        watch_id: str,
        *,
        now: datetime,
    ) -> ModelEnsembleWatchRecord:
        require_safe_id(watch_id)
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = self._row(connection, watch_id)
                if current is None or current["state"] == "disabled":
                    raise ValueError("watch does not exist")
                # A refresh is an admission request, not cancellation.  Never
                # revoke an active model subprocess lease: the worker cannot
                # safely pre-empt an in-flight local inference call, and doing
                # so only turns a healthy run into a restart loop.
                if current["state"] == "running":
                    connection.rollback()
                    return _record(current)
                # An explicit user refresh is the reviewed exit from quarantine
                # and restarts the bounded failure budget.
                connection.execute(
                    """UPDATE session_model_ensemble_watches
                       SET state='queued',progress_completed=0,
                           last_error_code=CASE WHEN state='failed'
                               THEN last_error_code ELSE NULL END,next_check_at=?,
                           lease_owner=NULL,lease_token=NULL,
                           lease_expires_at=NULL,failure_streak=0,
                           quarantined_at=NULL,quarantine_reason_code=NULL,updated_at=?
                       WHERE watch_id=?""",
                    (to_iso(now), to_iso(now), watch_id),
                )
                row = self._row(connection, watch_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if row is None:
            raise ValueError("watch does not exist")
        return _record(row)

    def list_publications(
        self,
        watch_id: str,
        *,
        before_generation: int | None,
        limit: int,
    ) -> ModelEnsembleTrajectoryPage:
        require_safe_id(watch_id)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 60
            or (
                before_generation is not None
                and (
                    not isinstance(before_generation, int)
                    or isinstance(before_generation, bool)
                    or not 1 <= before_generation <= 1_000_000_000
                )
            )
        ):
            raise ValueError("trajectory page is invalid")
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            # One trajectory page compares every published point against the
            # current head identity.  Reading the head, the page rows, and the
            # per-run measured/predictive sidecars outside one transaction can
            # mix a head observed before a publication with points observed
            # after it, and report comparable runs as incomparable or the
            # reverse.  A deferred read transaction pins them to one snapshot;
            # ``query_only`` is on, so no writer is blocked.
            try:
                connection.execute("BEGIN")
                watch = connection.execute(
                    """SELECT w.latest_run_id,p.generation AS head_generation,
                              p.max_messages AS head_max_messages,
                              r.plan_fingerprint AS head_plan,
                              r.provider_version AS head_provider_version,
                              r.adapter_version AS head_adapter_version,
                              r.source_schema_version AS head_source_schema_version,
                              r.content_schema_version AS head_content_schema_version,
                              r.redactor_version AS head_redactor_version,
                              typed.projection_version AS head_projection_version,
                              predictive.projection_version AS head_predictive_version
                       FROM session_model_ensemble_watches w
                       LEFT JOIN session_model_ensemble_watch_publications p
                         ON p.watch_id=w.watch_id AND p.run_id=w.latest_run_id
                       LEFT JOIN session_model_ensemble_runs r ON r.run_id=p.run_id
                       LEFT JOIN session_model_ensemble_typed_metric_seals typed
                         ON typed.run_id=r.run_id
                        AND typed.projection_version=?
                       LEFT JOIN session_model_ensemble_predictive_metric_seals predictive
                         ON predictive.run_id=r.run_id
                        AND predictive.projection_version='local-probabilistic-radar-v1'
                       WHERE w.watch_id=?""",
                    (MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION, watch_id),
                ).fetchone()
                if watch is None:
                    raise ValueError("watch does not exist")
                parameters: list[object] = [watch_id]
                cursor = ""
                if before_generation is not None:
                    cursor = " AND p.generation<?"
                    parameters.append(before_generation)
                parameters.append(limit + 1)
                rows = connection.execute(
                    f"""SELECT p.generation,p.run_id,p.max_messages,p.published_at,
                               r.completed_at,r.source_coverage_state,r.chunk_count,
                               r.plan_fingerprint,r.provider_version,r.adapter_version,
                               r.source_schema_version,r.content_schema_version,
                               r.redactor_version,typed.projection_version,
                               typed.projected_at,
                               predictive.projection_version AS predictive_projection_version
                        FROM session_model_ensemble_watch_publications p
                        JOIN session_model_ensemble_runs r ON r.run_id=p.run_id
                        JOIN session_model_ensemble_seals s ON s.run_id=r.run_id
                        LEFT JOIN session_model_ensemble_typed_metric_seals typed
                          ON typed.run_id=r.run_id
                         AND typed.projection_version='{MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION}'
                        LEFT JOIN session_model_ensemble_predictive_metric_seals predictive
                          ON predictive.run_id=r.run_id
                         AND predictive.projection_version='{PROBABILISTIC_METRIC_PROJECTION_VERSION}'
                        WHERE p.watch_id=?{cursor}
                        ORDER BY p.generation DESC LIMIT ?""",
                    tuple(parameters),
                ).fetchall()
                has_more = len(rows) > limit
                rows = rows[:limit]
                authority_run_ids = dict.fromkeys(
                    (
                        watch["latest_run_id"],
                        *(row["run_id"] for row in rows),
                    )
                )
                for authority_run_id in authority_run_ids:
                    if authority_run_id is not None:
                        self._validate_requirement_action_trajectory_authority(
                            connection,
                            authority_run_id,
                        )
                points = []
                head_predictive_identity = _predictive_identity(
                    connection, watch["latest_run_id"]
                )
                head_metric_v2_identity = _metric_v2_identity(
                    connection, watch["latest_run_id"]
                )
                for row in rows:
                    metric_rows = connection.execute(
                        """SELECT * FROM session_model_ensemble_metrics
                           WHERE run_id=? ORDER BY metric_key""",
                        (row["run_id"],),
                    ).fetchall()
                    metrics = tuple(
                        SessionModelEnsembleMetricReceipt(
                            metric_key=item["metric_key"],
                            value_state=MetricValueState(item["value_state"]),
                            numerator=item["numerator"],
                            denominator=item["denominator"],
                            numeric_value=item["numeric_value"],
                            known_chunk_count=item["known_chunk_count"],
                            abstained_chunk_count=item["abstained_chunk_count"],
                            unsupported_chunk_count=item["unsupported_chunk_count"],
                            failed_chunk_count=item["failed_chunk_count"],
                            total_chunk_count=item["total_chunk_count"],
                            explanation_code=item["explanation_code"],
                        )
                        for item in metric_rows
                    )
                    typed_metrics = tuple(
                        SessionModelEnsembleTypedMetricReceipt(
                            metric_key=item["metric_key"],
                            metric_version=item["metric_version"],
                            value_state=MetricValueState(item["value_state"]),
                            numerator=item["numerator"],
                            denominator=item["denominator"],
                            numeric_value=item["numeric_value"],
                            observed_message_count=item["observed_message_count"],
                            eligible_message_count=item["eligible_message_count"],
                            coverage=item["coverage"],
                            explanation_code=item["explanation_code"],
                            error_code=item["error_code"],
                            projection_source=item["projection_source"],
                            metric_schema_version=item["metric_schema_version"],
                            engine_version=item["engine_version"],
                            algorithm_id=item["algorithm_id"],
                            algorithm_version=item["algorithm_version"],
                            rubric_version=item["rubric_version"],
                            calibration_state=item["calibration_state"],
                            product_metric_eligible=bool(
                                item["product_metric_eligible"]
                            ),
                        )
                        for item in connection.execute(
                            """SELECT * FROM session_model_ensemble_typed_metrics
                               WHERE run_id=? AND projection_version=?
                               ORDER BY metric_key""",
                            (
                                row["run_id"],
                                MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
                            ),
                        ).fetchall()
                    )
                    predictive_metrics = tuple(
                        SessionPredictiveMetricSummary(
                            metric_key=item["metric_key"],
                            target=PredictiveMetricTarget(item["target"]),
                            state=PredictiveMetricState(item["state"]),
                            mean=item["mean"],
                            median=item["median"],
                            q05=item["q05"],
                            q25=item["q25"],
                            q75=item["q75"],
                            q95=item["q95"],
                            applicability_probability=item[
                                "applicability_probability"
                            ],
                            pending_probability=item["pending_probability"],
                            model_disagreement=item["model_disagreement"],
                            effective_observation_count=item[
                                "effective_observation_count"
                            ],
                            model_set_version=item["model_set_version"],
                            calibration_version=item["calibration_version"],
                            contract_version=item["contract_version"],
                            contract_fingerprint=item["contract_fingerprint"],
                            product_metric_eligible=bool(
                                item["product_metric_eligible"]
                            ),
                        )
                        for item in connection.execute(
                            """SELECT * FROM session_model_ensemble_predictive_metrics
                               WHERE run_id=? AND projection_version=?
                               ORDER BY metric_key""",
                            (
                                row["run_id"],
                                PROBABILISTIC_METRIC_PROJECTION_VERSION,
                            ),
                        ).fetchall()
                    )
                    point_predictive_identity = _predictive_identity(
                        connection, row["run_id"]
                    )
                    metric_states_v2 = _metric_v2_states(connection, row["run_id"])
                    point_metric_v2_identity = _metric_v2_identity(
                        connection, row["run_id"]
                    )
                    points.append(
                        ModelEnsembleTrajectoryPoint(
                            generation=int(row["generation"]),
                            run_id=row["run_id"],
                            published_at=from_iso(row["published_at"]),
                            completed_at=from_iso(row["completed_at"]),
                            max_messages=int(row["max_messages"]),
                            source_coverage_state=SourceCoverageState(
                                row["source_coverage_state"]
                            ),
                            chunk_count=int(row["chunk_count"]),
                            comparable_to_head=(
                                watch["head_generation"] is not None
                                and row["plan_fingerprint"] == watch["head_plan"]
                                and int(row["max_messages"])
                                == int(watch["head_max_messages"])
                                and row["provider_version"]
                                == watch["head_provider_version"]
                                and row["adapter_version"]
                                == watch["head_adapter_version"]
                                and row["source_schema_version"]
                                == watch["head_source_schema_version"]
                                and row["content_schema_version"]
                                == watch["head_content_schema_version"]
                                and row["redactor_version"]
                                == watch["head_redactor_version"]
                                and row["projection_version"]
                                == watch["head_projection_version"]
                                and row["predictive_projection_version"]
                                == watch["head_predictive_version"]
                                and point_predictive_identity
                                == head_predictive_identity
                                and point_metric_v2_identity
                                == head_metric_v2_identity
                            ),
                            metrics=metrics,
                            metric_projection_version=row["projection_version"],
                            metric_projection_completed_at=(
                                None
                                if row["projected_at"] is None
                                else from_iso(row["projected_at"])
                            ),
                            typed_metrics=typed_metrics,
                            metric_states_v2=metric_states_v2,
                            predictive_projection_version=row[
                                "predictive_projection_version"
                            ],
                            predictive_metrics=predictive_metrics,
                        )
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        head_generation = (
            None
            if watch["head_generation"] is None
            else int(watch["head_generation"])
        )
        return ModelEnsembleTrajectoryPage(
            watch_id=watch_id,
            head_run_id=(
                None if head_generation is None else watch["latest_run_id"]
            ),
            head_generation=head_generation,
            points=tuple(points),
            next_before_generation=(
                points[-1].generation if has_more and points else None
            ),
        )

    def claim_due(
        self,
        *,
        owner: str,
        now: datetime,
        lease_duration: timedelta,
        policy: ModelEnsembleWatchFailurePolicy | None = None,
    ) -> tuple[ModelEnsembleWatchRecord, ModelEnsembleWatchLease] | None:
        require_safe_id(owner)
        active_policy = policy or ModelEnsembleWatchFailurePolicy()
        self._ensure_initialized()
        stamp = to_iso(now)
        expires = now + lease_duration
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._recover_expired_leases(
                    connection,
                    now=now,
                    policy=active_policy,
                )
                candidate = connection.execute(
                    """SELECT watch_id,generation,next_check_at
                       FROM session_model_ensemble_watches
                       WHERE state IN ('queued','idle','failed') AND next_check_at<=?
                         AND quarantined_at IS NULL
                       ORDER BY next_check_at,created_at,watch_id LIMIT 1""",
                    (stamp,),
                ).fetchone()
                if candidate is None:
                    connection.rollback()
                    return None
                generation = int(candidate["generation"]) + 1
                token = hashlib.sha256(
                    f"model-ensemble-watch-lease:{candidate['watch_id']}:{generation}:{stamp}".encode(
                        "ascii"
                    )
                ).hexdigest()
                connection.execute(
                    """UPDATE session_model_ensemble_watches
                       SET state='running',generation=?,progress_completed=0,
                           lease_owner=?,lease_token=?,
                           lease_expires_at=?,updated_at=? WHERE watch_id=?""",
                    (
                        generation,
                        owner,
                        token,
                        to_iso(expires),
                        stamp,
                        candidate["watch_id"],
                    ),
                )
                attempt_id = hashlib.sha256(
                    f"{MODEL_ENSEMBLE_ATTEMPT_CONTRACT_VERSION}:{candidate['watch_id']}:{generation}".encode(
                        "ascii"
                    )
                ).hexdigest()
                connection.execute(
                    """INSERT INTO session_model_ensemble_analysis_attempts(
                           attempt_id,contract_version,watch_id,generation,state,
                           prior_head_run_id,published_run_id,progress_completed,
                           progress_total,stage_count,warning_count,error_code,
                           requested_at,started_at,completed_at,local_only,content_persisted
                       ) SELECT ?,?,?,?,'running',latest_run_id,NULL,0,?,0,0,NULL,
                                ?,?,NULL,1,0
                         FROM session_model_ensemble_watches WHERE watch_id=?""",
                    (
                        attempt_id,
                        MODEL_ENSEMBLE_ATTEMPT_CONTRACT_VERSION,
                        candidate["watch_id"],
                        generation,
                        MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
                        candidate["next_check_at"],
                        stamp,
                        candidate["watch_id"],
                    ),
                )
                row = self._row(connection, candidate["watch_id"])
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        record = _record(row)
        return record, ModelEnsembleWatchLease(
            watch_id=record.watch_id,
            owner=owner,
            token=token,
            expires_at=expires,
        )

    def recover_orphaned_leases(
        self,
        *,
        owner: str,
        now: datetime,
        policy: ModelEnsembleWatchFailurePolicy,
    ) -> int:
        """Recover only expired leases; an unexpired lease may still be live."""

        require_safe_id(owner)
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                recovered = self._recover_expired_leases(
                    connection,
                    now=now,
                    policy=policy,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return recovered

    def quarantine_provider_watches(
        self,
        provider: Provider,
        *,
        now: datetime,
        reason_code: str,
    ) -> int:
        """Atomically stop every watch for a provider and retain sealed heads."""

        require_safe_label(reason_code)
        self._ensure_initialized()
        stamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                running = tuple(
                    connection.execute(
                        """SELECT attempt.attempt_id
                           FROM session_model_ensemble_analysis_attempts attempt
                           JOIN session_model_ensemble_watches watch
                             ON watch.watch_id=attempt.watch_id
                            AND watch.generation=attempt.generation
                           WHERE watch.provider=? AND watch.state='running'
                             AND attempt.state='running'""",
                        (provider.value,),
                    ).fetchall()
                )
                for row in running:
                    connection.execute(
                        """UPDATE session_model_ensemble_analysis_attempts
                           SET state='cancelled',stage_count=1,warning_count=1,
                               error_code=?,completed_at=?
                           WHERE attempt_id=? AND state='running'""",
                        (reason_code, stamp, row["attempt_id"]),
                    )
                    connection.execute(
                        """INSERT INTO session_model_ensemble_analysis_attempt_stages(
                               attempt_id,stage_ordinal,stage_key,state,error_code,
                               quantization,completed_at,local_only,content_persisted
                           ) VALUES(?,0,'analysis_pipeline','cancelled',?,'none',?,1,0)""",
                        (row["attempt_id"], reason_code, stamp),
                    )
                    self._seal_terminal_attempts(connection, (row["attempt_id"],))
                result = connection.execute(
                    """UPDATE session_model_ensemble_watches
                       SET state=CASE WHEN state='disabled' THEN 'disabled' ELSE 'failed' END,
                           progress_completed=0,last_error_code=?,next_check_at=?,
                           lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                           quarantined_at=?,quarantine_reason_code=?,updated_at=?
                       WHERE provider=? AND (
                           quarantined_at IS NULL OR quarantine_reason_code<>?
                       )""",
                    (
                        reason_code,
                        stamp,
                        stamp,
                        reason_code,
                        stamp,
                        provider.value,
                        reason_code,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return int(result.rowcount)

    def quarantine_stopped_attempt(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        generation: int,
        now: datetime,
        reason_code: str,
    ) -> ModelEnsembleWatchRecord:
        """Retain a late cleanup warning, never mutate a terminal receipt.

        A cancelled/expired claim has no live lease left to fail. Only its
        exact generation and original claim token can quarantine the stopped
        watch; a re-enabled or replacement job remains outside this authority.
        """

        require_safe_label(reason_code)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("watch generation invalid")
        self._ensure_initialized()
        stamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                attempt = connection.execute(
                    """SELECT attempt.started_at
                       FROM session_model_ensemble_analysis_attempts attempt
                       JOIN session_model_ensemble_watches watch
                         ON watch.watch_id=attempt.watch_id
                        AND watch.generation=attempt.generation
                       WHERE watch.watch_id=? AND watch.generation=?
                         AND watch.state IN ('idle','failed','disabled')
                         AND watch.lease_owner IS NULL AND watch.lease_token IS NULL
                         AND watch.lease_expires_at IS NULL
                         AND attempt.state IN ('cancelled','failed')""",
                    (lease.watch_id, generation),
                ).fetchone()
                if attempt is None:
                    raise ValueError("watch stopped claim unavailable")
                original_token = hashlib.sha256(
                    f"model-ensemble-watch-lease:{lease.watch_id}:{generation}:{attempt['started_at']}".encode("ascii")
                ).hexdigest()
                if original_token != lease.token:
                    raise ValueError("watch stopped claim mismatch")
                connection.execute(
                    """UPDATE session_model_ensemble_watches
                       SET state=CASE WHEN state='disabled' THEN 'disabled' ELSE 'failed' END,
                           progress_completed=0,last_error_code=?,next_check_at=?,
                           quarantined_at=?,quarantine_reason_code=?,updated_at=?
                       WHERE watch_id=? AND generation=?""",
                    (reason_code, stamp, stamp, reason_code, stamp, lease.watch_id, generation),
                )
                row = self._row(connection, lease.watch_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return _record(row)

    def heartbeat(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        now: datetime,
        lease_duration: timedelta,
        progress_completed: int,
    ) -> tuple[ModelEnsembleWatchRecord, ModelEnsembleWatchLease]:
        if not 0 <= progress_completed <= MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL:
            raise ValueError("watch progress is invalid")
        self._ensure_initialized()
        expires = now + lease_duration
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                """UPDATE session_model_ensemble_watches
                   SET progress_completed=?,lease_expires_at=?,updated_at=?
                   WHERE watch_id=? AND state='running' AND lease_owner=?
                     AND lease_token=? AND lease_expires_at>?""",
                (
                    progress_completed,
                    to_iso(expires),
                    to_iso(now),
                    lease.watch_id,
                    lease.owner,
                    lease.token,
                    to_iso(now),
                ),
            )
            if result.rowcount != 1:
                connection.rollback()
                raise ValueError("watch lease is no longer active")
            connection.execute(
                """UPDATE session_model_ensemble_analysis_attempts
                   SET progress_completed=?
                   WHERE watch_id=? AND generation=(
                       SELECT generation FROM session_model_ensemble_watches WHERE watch_id=?
                   ) AND state='running'""",
                (progress_completed, lease.watch_id, lease.watch_id),
            )
            row = self._row(connection, lease.watch_id)
            connection.commit()
        record = _record(row)
        return record, ModelEnsembleWatchLease(
            watch_id=lease.watch_id,
            owner=lease.owner,
            token=lease.token,
            expires_at=expires,
        )

    def complete(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        now: datetime,
        next_check_at: datetime,
        outcome: SessionModelEnsembleOutcome,
    ) -> ModelEnsembleWatchRecord:
        self._ensure_initialized()
        run = outcome.run
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO session_model_ensemble_watch_publications(
                       watch_id,generation,run_id,max_messages,published_at
                   )
                   SELECT watch_id,generation,?,?,?
                   FROM session_model_ensemble_watches
                   WHERE watch_id=? AND state='running' AND lease_owner=?
                     AND lease_token=? AND lease_expires_at>?
                   ON CONFLICT(watch_id,run_id) DO NOTHING""",
                (
                    run.run_id,
                    _record(self._row(connection, lease.watch_id)).max_messages,
                    to_iso(now),
                    lease.watch_id,
                    lease.owner,
                    lease.token,
                    to_iso(now),
                ),
            )
            result = connection.execute(
                """UPDATE session_model_ensemble_watches
                   SET state='idle',progress_completed=?,latest_run_id=?,
                       latest_input_fingerprint=?,last_error_code=NULL,next_check_at=?,
                       lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                       failure_streak=0,quarantined_at=NULL,
                       quarantine_reason_code=NULL,updated_at=?
                   WHERE watch_id=? AND state='running' AND lease_owner=?
                     AND lease_token=? AND lease_expires_at>? AND session_id=?""",
                (
                    MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
                    run.run_id,
                    run.input_fingerprint,
                    to_iso(next_check_at),
                    to_iso(now),
                    lease.watch_id,
                    lease.owner,
                    lease.token,
                    to_iso(now),
                    run.session_id,
                ),
            )
            if result.rowcount != 1:
                connection.rollback()
                raise ValueError("watch lease is no longer active")
            predictive = run.receipt.predictive_projection
            # A coalesced unchanged observation publishes no new execution.
            # Do not copy old stage telemetry into the new durable attempt.
            model_stages = (
                ()
                if predictive is None or not outcome.applied
                else predictive.model_stages
            )
            warnings = sum(item.status != "completed" for item in model_stages)
            attempt_state = "partial" if warnings else "completed"
            attempt_result = connection.execute(
                """UPDATE session_model_ensemble_analysis_attempts
                   SET state=?,published_run_id=?,progress_completed=?,progress_total=?,
                       stage_count=?,warning_count=?,completed_at=?
                   WHERE watch_id=? AND generation=(
                       SELECT generation FROM session_model_ensemble_watches WHERE watch_id=?
                   ) AND state='running'""",
                (
                    attempt_state,
                    run.run_id,
                    MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
                    MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
                    len(model_stages),
                    warnings,
                    to_iso(now),
                    lease.watch_id,
                    lease.watch_id,
                ),
            )
            if attempt_result.rowcount != 1:
                connection.rollback()
                raise ValueError("watch attempt is no longer active")
            attempt_row = connection.execute(
                """SELECT attempt_id FROM session_model_ensemble_analysis_attempts
                   WHERE watch_id=? AND generation=(
                       SELECT generation FROM session_model_ensemble_watches WHERE watch_id=?)""",
                (lease.watch_id, lease.watch_id),
            ).fetchone()
            if attempt_row is None:
                connection.rollback()
                raise ValueError("watch attempt is unavailable")
            connection.executemany(
                """INSERT INTO session_model_ensemble_analysis_attempt_stages(
                       attempt_id,stage_ordinal,stage_key,state,model_key,
                       repository_id,revision,error_code,device,quantization,
                       inference_latency_ms,peak_accelerator_memory_mb,process_rss_mb,
                       evaluated_case_count,contributed_case_count,unloaded_after_stage,
                       completed_at,local_only,content_persisted
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,1,0)""",
                tuple(
                    (
                        attempt_row["attempt_id"],
                        ordinal,
                        item.model_key,
                        item.status,
                        item.model_key,
                        item.repository_id,
                        item.revision,
                        item.error_code,
                        item.device,
                        item.quantization,
                        item.inference_latency_ms,
                        item.peak_accelerator_memory_mb,
                        item.process_rss_mb,
                        int(item.unloaded_after_stage),
                        to_iso(now),
                    )
                    for ordinal, item in enumerate(model_stages)
                ),
            )
            self._seal_terminal_attempts(
                connection,
                (attempt_row["attempt_id"],),
            )
            row = self._row(connection, lease.watch_id)
            connection.commit()
        return _record(row)

    def fail(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        now: datetime,
        reason_code: str,
        failure_class: ModelEnsembleWatchFailureClass | None = None,
        policy: ModelEnsembleWatchFailurePolicy | None = None,
        next_check_at: datetime | None = None,
    ) -> ModelEnsembleWatchRecord:
        require_safe_label(reason_code)
        active_policy = policy or ModelEnsembleWatchFailurePolicy()
        active_class = failure_class or ModelEnsembleWatchFailureClass.RETRYABLE
        self._ensure_initialized()
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._row(connection, lease.watch_id)
            if (
                current is None
                or current["state"] != "running"
                or current["lease_owner"] != lease.owner
                or current["lease_token"] != lease.token
                or from_iso(current["lease_expires_at"]) <= now
            ):
                connection.rollback()
                raise ValueError("watch lease is no longer active")
            failure_streak = min(64, int(current["failure_streak"]) + 1)
            quarantined = (
                active_class is ModelEnsembleWatchFailureClass.NONRETRYABLE
                or active_policy.quarantines(failure_streak)
            )
            scheduled_at = (
                now
                if quarantined
                else (
                    next_check_at
                    if next_check_at is not None
                    else now + active_policy.next_delay(failure_streak)
                )
            )
            quarantine_reason = (
                reason_code
                if active_class is ModelEnsembleWatchFailureClass.NONRETRYABLE
                else MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED
            ) if quarantined else None
            result = connection.execute(
                """UPDATE session_model_ensemble_watches
                   SET state='failed',last_error_code=?,next_check_at=?,
                       lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                       failure_streak=?,quarantined_at=?,quarantine_reason_code=?,
                       updated_at=?
                   WHERE watch_id=? AND state='running' AND lease_owner=?
                     AND lease_token=? AND lease_expires_at>?""",
                (
                    reason_code,
                    to_iso(scheduled_at),
                    failure_streak,
                    to_iso(now) if quarantined else None,
                    quarantine_reason,
                    to_iso(now),
                    lease.watch_id,
                    lease.owner,
                    lease.token,
                    to_iso(now),
                ),
            )
            if result.rowcount != 1:
                connection.rollback()
                raise ValueError("watch lease is no longer active")
            attempt_result = connection.execute(
                """UPDATE session_model_ensemble_analysis_attempts
                   SET state='failed',stage_count=1,warning_count=1,error_code=?,completed_at=?
                   WHERE watch_id=? AND generation=(
                       SELECT generation FROM session_model_ensemble_watches WHERE watch_id=?
                   ) AND state='running'""",
                (reason_code, to_iso(now), lease.watch_id, lease.watch_id),
            )
            if attempt_result.rowcount != 1:
                connection.rollback()
                raise ValueError("watch attempt is no longer active")
            attempt_row = connection.execute(
                """SELECT attempt_id FROM session_model_ensemble_analysis_attempts
                   WHERE watch_id=? AND generation=(
                       SELECT generation FROM session_model_ensemble_watches WHERE watch_id=?)""",
                (lease.watch_id, lease.watch_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO session_model_ensemble_analysis_attempt_stages(
                       attempt_id,stage_ordinal,stage_key,state,error_code,quantization,
                       completed_at,local_only,content_persisted
                   ) VALUES(?,0,'analysis_pipeline','failed',?,'none',?,1,0)""",
                (attempt_row["attempt_id"], reason_code, to_iso(now)),
            )
            self._seal_terminal_attempts(
                connection,
                (attempt_row["attempt_id"],),
            )
            row = self._row(connection, lease.watch_id)
            connection.commit()
        return _record(row)

    def cancel_attempt(
        self,
        watch_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        lease: ModelEnsembleWatchLease | None = None,
        reason_code: str = "analysis_cancelled",
    ) -> ModelEnsembleWatchRecord:
        require_safe_id(watch_id)
        if reason_code not in {"analysis_cancelled", "application_shutdown"} or (
            reason_code == "application_shutdown" and lease is None
        ):
            raise ValueError("watch cancellation reason invalid")
        self._ensure_initialized()
        stamp = to_iso(now)
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._row(connection, watch_id)
            if current is None or current["state"] != "running":
                connection.rollback()
                raise ValueError("watch has no active attempt")
            if lease is not None and (
                lease.watch_id != watch_id
                or current["lease_owner"] != lease.owner
                or current["lease_token"] != lease.token
                or current["lease_expires_at"] is None
                or current["lease_expires_at"] <= stamp
            ):
                connection.rollback()
                raise ValueError("watch cancellation lease lost")
            attempt_row = connection.execute(
                """SELECT attempt_id FROM session_model_ensemble_analysis_attempts
                   WHERE watch_id=? AND generation=? AND state='running'""",
                (watch_id, int(current["generation"])),
            ).fetchone()
            if attempt_row is None:
                connection.rollback()
                raise ValueError("watch attempt is unavailable")
            connection.execute(
                """UPDATE session_model_ensemble_analysis_attempts
                   SET state='cancelled',stage_count=1,warning_count=1,
                       error_code=?,completed_at=?
                   WHERE attempt_id=? AND state='running'""",
                (reason_code, stamp, attempt_row["attempt_id"]),
            )
            connection.execute(
                """INSERT INTO session_model_ensemble_analysis_attempt_stages(
                       attempt_id,stage_ordinal,stage_key,state,error_code,quantization,
                       completed_at,local_only,content_persisted
                   ) VALUES(?,0,'analysis_pipeline','cancelled',?,
                            'none',?,1,0)""",
                (attempt_row["attempt_id"], reason_code, stamp),
            )
            self._seal_terminal_attempts(
                connection,
                (attempt_row["attempt_id"],),
            )
            connection.execute(
                """UPDATE session_model_ensemble_watches
                   SET state='idle',progress_completed=0,last_error_code=NULL,next_check_at=?,
                       lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=?
                   WHERE watch_id=? AND state='running'""",
                (to_iso(next_check_at), stamp, watch_id),
            )
            row = self._row(connection, watch_id)
            connection.commit()
        return _record(row)


__all__ = ["SqliteModelEnsembleWatchRepository"]
