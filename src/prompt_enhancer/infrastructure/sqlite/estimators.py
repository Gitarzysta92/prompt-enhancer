"""Normalized SQLite storage for content-free P1 estimator provenance."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
import sqlite3
from typing import NoReturn

from ...application.estimators.contracts import (
    ArtifactAvailability,
    ArtifactDigest,
    CandidateFamilySelection,
    EstimateUncertainty,
    EstimatorExecution,
    EstimatorExecutionState,
    EstimatorPlan,
    EstimatorReasoningEffort,
    EstimatorRoute,
    EstimatorStage,
    EstimatorStageKind,
    EstimatorStageReceipt,
    EstimatorStageReceiptState,
    EvidencePacketReceipt,
    ExecutionDestination,
    ExecutionDisclosure,
    LabelProbability,
    MetricDirection,
    MetricEstimate,
    MetricEstimateSource,
    MetricEstimateState,
    MetricQuestionSpec,
    MetricValueKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelRun,
    ModelRunState,
    ModelSource,
    ModelVote,
    ProviderSchemaIdentity,
    RetentionClass,
    StageCondition,
    TokenizerIdentity,
    UncertaintyKind,
)
from ...application.estimators.persistence import (
    ActivationAttemptOutcome,
    CompletedSyntheticEstimatorBundle,
    EstimatorRepository,
    MAX_MODEL_LAB_PLANS,
    ModelLabInventory,
    ModelLabPlanSummary,
    ModelLabSummary,
    PrivacyDeleteOutcome,
    PreregisteredEstimatorCampaign,
    SyntheticEstimatorCase,
    StructuredEstimateVerifier,
    _v16_plan_has_unsafe_identifier,
)
from ...application.estimators.evidence_contracts import (
    AttemptApprovalKind,
    AttemptLaunchReceiptV1,
    AttemptTerminalOutcomeV1,
    AttemptTerminalState,
    AuthoritativeCandidateProjectionV2,
    AuthoritativeDeterministicBaselineProjectionV1,
    BlindAdjudicationResolution,
    BlindHumanAdjudicationInputV1,
    BlindHumanJudgmentInputV1,
    CalibrationEvidenceSubmissionV1,
    CalibrationValueState,
    CostProvenanceV1,
    ExpectedAttemptManifestV2,
    ExpectedAttemptV2,
    HoldoutAccessAuditV1,
    HoldoutAccessEventV1,
    HoldoutAccessGapV1,
    HoldoutAccessManifestV1,
    HoldoutAccessKind,
    HoldoutActorKind,
    HumanParticipantKind,
    MeasurementState,
    ObjectiveTruthKind,
    ObjectiveTruthProjectionV1,
    PrivacyFindingCategory,
    PrivacyFindingV1,
    PrivacyScanManifestV1,
    PrivacyScanReceiptV1,
    QueueProvenanceV1,
    ResourceUsageProvenanceV1,
    ServedIdentityState,
    ServedIdentityV1,
    StabilitySeriesManifestV1,
    StabilityTrialReceiptV1,
    StructuredEstimateReceiptV1,
    TokenUsageProvenanceV1,
    revalidate_calibration_evidence_submission_v1,
    revalidate_content_free_contract,
)
from ...application.estimators.gate_contracts import (
    CalibrationLanguage,
    CalibrationSplit,
    CalibrationTaskStratum,
    GatePolicy,
    GatePreregistration,
    HighRiskPrecisionRule,
    MetricGateSpec,
    MetricRiskTier,
    SubgroupDimension,
    StabilityCondition,
)
from ...application.estimators.gate_v2_contracts import (
    CaseAssignmentManifestV2,
    CaseAssignmentV2,
    ConstellationIdentityReceipt,
    ConstellationStageIdentity,
    GatePreregistrationV2,
)
from ...database import DatabaseInvariantError
from ...domain import Provider
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


def _required_time(value: str) -> datetime:
    parsed = from_iso(value)
    if parsed is None:  # Defensive: schema requires these timestamps.
        raise DatabaseInvariantError("estimator timestamp is missing")
    return parsed


def _campaign_revocation_key(campaign_id: str) -> str:
    return hashlib.sha256(
        f"estimator-campaign-revocation-v1:{campaign_id}".encode("ascii")
    ).hexdigest()


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _to_epoch_us(value: datetime) -> int:
    delta = value - _EPOCH
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def _from_epoch_us(value: int) -> datetime:
    return _EPOCH + timedelta(microseconds=int(value))


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _projection_columns(value) -> dict[str, object]:
    return {
        "value_kind": value.value_kind.value,
        "value_state": value.state.value,
        "numeric_value": value.numeric_value,
        "label_code": value.label_code,
        "reason_code": value.reason_code,
    }


def _contract_fingerprint(value) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SqliteEstimatorRepository(EstimatorRepository):
    """Append-only relational repository with an explicit privacy delete."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        clock: Callable[[], datetime] | None = None,
        structured_estimate_verifier: StructuredEstimateVerifier | None = None,
        begin_evidence_authorization: (
            Callable[[str, str], tuple[str, str]] | None
        ) = None,
        end_evidence_authorization: (
            Callable[[str, str, str, str], None] | None
        ) = None,
        begin_evidence_delete_authorization: (
            Callable[[str], tuple[str, str]] | None
        ) = None,
        end_evidence_delete_authorization: (
            Callable[[str, str, str], None] | None
        ) = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._clock = clock or (lambda: datetime.now(UTC))
        self._structured_estimate_verifier = structured_estimate_verifier
        self._begin_evidence_authorization = begin_evidence_authorization
        self._end_evidence_authorization = end_evidence_authorization
        self._begin_evidence_delete_authorization = (
            begin_evidence_delete_authorization
        )
        self._end_evidence_delete_authorization = end_evidence_delete_authorization

    @staticmethod
    def _conflict(message: str) -> NoReturn:
        raise DatabaseInvariantError(message)

    def register_plan(self, plan: EstimatorPlan) -> str:
        self._ensure_initialized()
        fingerprint = plan.canonical_fingerprint
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM estimator_plans WHERE plan_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if existing is not None:
                    if self._hydrate_plan(connection, fingerprint) != plan:
                        self._conflict("estimator plan fingerprint conflicts with storage")
                    connection.commit()
                    return fingerprint
                version_owner = connection.execute(
                    """
                    SELECT plan_fingerprint FROM estimator_plans
                    WHERE plan_key = ? AND plan_version = ?
                    """,
                    (plan.plan_key, plan.plan_version),
                ).fetchone()
                if version_owner is not None:
                    self._conflict(
                        "estimator plan key and version already identify another configuration"
                    )
                self._insert_plan(connection, plan)
                connection.commit()
                return fingerprint
            except Exception:
                connection.rollback()
                raise

    def get_plan(self, plan_fingerprint: str) -> EstimatorPlan | None:
        self._ensure_initialized()
        require_safe_id(plan_fingerprint)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM estimator_plans WHERE plan_fingerprint = ?",
                (plan_fingerprint,),
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_plan(connection, plan_fingerprint)

    def _insert_artifact(self, connection, artifact: ModelArtifactIdentity) -> str:
        fingerprint = artifact.canonical_fingerprint
        row = connection.execute(
            "SELECT 1 FROM estimator_model_artifacts WHERE artifact_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is not None:
            if self._hydrate_artifact(connection, fingerprint) != artifact:
                self._conflict("model artifact fingerprint conflicts with storage")
            return fingerprint
        connection.executemany(
            """
            INSERT INTO estimator_model_weight_files(
                artifact_fingerprint, ordinal, file_name, sha256
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (fingerprint, ordinal, item.file_name, item.sha256)
                for ordinal, item in enumerate(artifact.weight_artifacts)
            ),
        )
        connection.executemany(
            """
            INSERT INTO estimator_model_tokenizer_files(
                artifact_fingerprint, ordinal, file_name, sha256
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (fingerprint, ordinal, item.file_name, item.sha256)
                for ordinal, item in enumerate(artifact.tokenizer.artifacts)
            ),
        )
        connection.execute(
            """
            INSERT INTO estimator_model_artifacts(
                artifact_fingerprint, contract_version, source,
                requested_model_id, served_model_id, requested_revision,
                served_revision, requested_execution_mode, served_execution_mode,
                weight_availability, weight_file_count, tokenizer_id,
                tokenizer_revision, tokenizer_availability, tokenizer_file_count,
                license_id, trust_remote_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                fingerprint,
                artifact.contract_version,
                artifact.source.value,
                artifact.requested_model_id,
                artifact.served_model_id,
                artifact.requested_revision,
                artifact.served_revision,
                artifact.requested_execution_mode.value,
                artifact.served_execution_mode.value,
                artifact.weight_availability.value,
                len(artifact.weight_artifacts),
                artifact.tokenizer.tokenizer_id,
                artifact.tokenizer.revision,
                artifact.tokenizer.availability.value,
                len(artifact.tokenizer.artifacts),
                artifact.license_id,
            ),
        )
        return fingerprint

    def _insert_question(self, connection, question: MetricQuestionSpec) -> str:
        fingerprint = question.canonical_fingerprint
        row = connection.execute(
            "SELECT 1 FROM estimator_metric_questions WHERE question_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is not None:
            if self._hydrate_question(connection, fingerprint) != question:
                self._conflict("metric question fingerprint conflicts with storage")
            return fingerprint
        connection.execute(
            """
            INSERT INTO estimator_metric_questions(
                question_fingerprint, contract_version, metric_key,
                metric_definition_version, question_id, question_version,
                question_sha256, prompt_template_id, prompt_template_version,
                prompt_template_sha256, rubric_id, rubric_version, rubric_sha256,
                output_schema_version, value_kind, unit_code, direction,
                lower_bound, upper_bound
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                question.contract_version,
                question.metric_key,
                question.metric_definition_version,
                question.question_id,
                question.question_version,
                question.question_sha256,
                question.prompt_template_id,
                question.prompt_template_version,
                question.prompt_template_sha256,
                question.rubric_id,
                question.rubric_version,
                question.rubric_sha256,
                question.output_schema_version,
                question.value_kind.value,
                question.unit_code,
                question.direction.value,
                question.lower_bound,
                question.upper_bound,
            ),
        )
        return fingerprint

    def _insert_plan(self, connection, plan: EstimatorPlan) -> None:
        plan_fingerprint = plan.canonical_fingerprint
        artifacts = {
            artifact.canonical_fingerprint: artifact
            for artifact in (
                [
                    stage.model_artifact
                    for stage in plan.stages
                    if stage.model_artifact is not None
                ]
                + [
                    candidate
                    for family in plan.candidate_families
                    for candidate in family.screened_candidates
                ]
            )
        }
        for fingerprint in sorted(artifacts):
            self._insert_artifact(connection, artifacts[fingerprint])
        for question in plan.question_specs:
            self._insert_question(connection, question)

        connection.executemany(
            """
            INSERT INTO estimator_plan_questions(
                plan_fingerprint, ordinal, question_fingerprint
            ) VALUES (?, ?, ?)
            """,
            (
                (plan_fingerprint, ordinal, question.canonical_fingerprint)
                for ordinal, question in enumerate(plan.question_specs)
            ),
        )
        connection.executemany(
            """
            INSERT INTO estimator_plan_provider_schemas(
                plan_fingerprint, ordinal, provider, adapter_version,
                provider_schema_version
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    plan_fingerprint,
                    ordinal,
                    identity.provider.value,
                    identity.adapter_version,
                    identity.provider_schema_version,
                )
                for ordinal, identity in enumerate(plan.provider_schemas)
            ),
        )
        for family_ordinal, family in enumerate(plan.candidate_families):
            connection.executemany(
                """
                INSERT INTO estimator_candidate_models(
                    plan_fingerprint, family_key, ordinal, artifact_fingerprint
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (
                        plan_fingerprint,
                        family.family_key,
                        ordinal,
                        candidate.canonical_fingerprint,
                    )
                    for ordinal, candidate in enumerate(family.screened_candidates)
                ),
            )
            connection.executemany(
                """
                INSERT INTO estimator_candidate_promotions(
                    plan_fingerprint, family_key, ordinal, artifact_fingerprint
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (plan_fingerprint, family.family_key, ordinal, fingerprint)
                    for ordinal, fingerprint in enumerate(
                        family.promoted_artifact_fingerprints
                    )
                ),
            )
            connection.executemany(
                """
                INSERT INTO estimator_candidate_baselines(
                    plan_fingerprint, family_key, ordinal, baseline_id
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (plan_fingerprint, family.family_key, ordinal, baseline_id)
                    for ordinal, baseline_id in enumerate(
                        family.deterministic_baseline_ids
                    )
                ),
            )
            connection.execute(
                """
                INSERT INTO estimator_candidate_families(
                    plan_fingerprint, ordinal, family_key, candidate_count,
                    promotion_count, baseline_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_fingerprint,
                    family_ordinal,
                    family.family_key,
                    len(family.screened_candidates),
                    len(family.promoted_artifact_fingerprints),
                    len(family.deterministic_baseline_ids),
                ),
            )
        connection.executemany(
            """
            INSERT INTO estimator_plan_stages(
                plan_fingerprint, ordinal, kind, condition_code,
                component_version, configuration_sha256, output_schema_version,
                artifact_fingerprint, candidate_family_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    plan_fingerprint,
                    stage.ordinal,
                    stage.kind.value,
                    stage.condition.value,
                    stage.component_version,
                    stage.configuration_sha256,
                    stage.output_schema_version,
                    None
                    if stage.model_artifact is None
                    else stage.model_artifact.canonical_fingerprint,
                    stage.candidate_family_key,
                )
                for stage in plan.stages
            ),
        )
        connection.execute(
            """
            INSERT INTO estimator_plans(
                plan_fingerprint, contract_version, plan_key, plan_version, route,
                evidence_packet_schema_version, preprocessing_version,
                preprocessing_sha256, reasoning_effort, calibration_version,
                calibration_sha256, router_version, router_sha256,
                redactor_version, redactor_sha256, execution_mode,
                model_load_policy, max_loaded_models, question_count,
                provider_schema_count, candidate_family_count,
                uses_synthetic_model, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_fingerprint,
                plan.contract_version,
                plan.plan_key,
                plan.plan_version,
                plan.route.value,
                plan.evidence_packet_schema_version,
                plan.preprocessing_version,
                plan.preprocessing_sha256,
                plan.reasoning_effort.value,
                plan.calibration_version,
                plan.calibration_sha256,
                plan.router_version,
                plan.router_sha256,
                plan.redactor_version,
                plan.redactor_sha256,
                plan.execution_mode,
                plan.model_load_policy,
                plan.max_loaded_models,
                len(plan.question_specs),
                len(plan.provider_schemas),
                len(plan.candidate_families),
                int(plan.uses_synthetic_model),
                to_iso(self._clock()),
            ),
        )

    def _hydrate_artifact(self, connection, fingerprint: str) -> ModelArtifactIdentity:
        row = connection.execute(
            "SELECT * FROM estimator_model_artifacts WHERE artifact_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            self._conflict("registered model artifact is missing")
        weights = connection.execute(
            """
            SELECT file_name, sha256 FROM estimator_model_weight_files
            WHERE artifact_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        tokenizer_files = connection.execute(
            """
            SELECT file_name, sha256 FROM estimator_model_tokenizer_files
            WHERE artifact_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        artifact = ModelArtifactIdentity(
            contract_version=row["contract_version"],
            source=ModelSource(row["source"]),
            requested_model_id=row["requested_model_id"],
            served_model_id=row["served_model_id"],
            requested_revision=row["requested_revision"],
            served_revision=row["served_revision"],
            requested_execution_mode=ModelExecutionMode(
                row["requested_execution_mode"]
            ),
            served_execution_mode=ModelExecutionMode(row["served_execution_mode"]),
            weight_availability=ArtifactAvailability(row["weight_availability"]),
            weight_artifacts=tuple(
                ArtifactDigest(file_name=item["file_name"], sha256=item["sha256"])
                for item in weights
            ),
            tokenizer=TokenizerIdentity(
                tokenizer_id=row["tokenizer_id"],
                revision=row["tokenizer_revision"],
                availability=ArtifactAvailability(row["tokenizer_availability"]),
                artifacts=tuple(
                    ArtifactDigest(
                        file_name=item["file_name"], sha256=item["sha256"]
                    )
                    for item in tokenizer_files
                ),
            ),
            license_id=row["license_id"],
            trust_remote_code=False,
        )
        if artifact.canonical_fingerprint != fingerprint:
            self._conflict("stored model artifact fingerprint is not reproducible")
        return artifact

    @staticmethod
    def _hydrate_question(connection, fingerprint: str) -> MetricQuestionSpec:
        row = connection.execute(
            "SELECT * FROM estimator_metric_questions WHERE question_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("registered metric question is missing")
        question = MetricQuestionSpec(
            contract_version=row["contract_version"],
            metric_key=row["metric_key"],
            metric_definition_version=row["metric_definition_version"],
            question_id=row["question_id"],
            question_version=row["question_version"],
            question_sha256=row["question_sha256"],
            prompt_template_id=row["prompt_template_id"],
            prompt_template_version=row["prompt_template_version"],
            prompt_template_sha256=row["prompt_template_sha256"],
            rubric_id=row["rubric_id"],
            rubric_version=row["rubric_version"],
            rubric_sha256=row["rubric_sha256"],
            output_schema_version=row["output_schema_version"],
            value_kind=MetricValueKind(row["value_kind"]),
            unit_code=row["unit_code"],
            direction=MetricDirection(row["direction"]),
            lower_bound=row["lower_bound"],
            upper_bound=row["upper_bound"],
        )
        if question.canonical_fingerprint != fingerprint:
            raise DatabaseInvariantError(
                "stored metric question fingerprint is not reproducible"
            )
        return question

    def _hydrate_plan(self, connection, fingerprint: str) -> EstimatorPlan:
        row = connection.execute(
            "SELECT * FROM estimator_plans WHERE plan_fingerprint = ?", (fingerprint,)
        ).fetchone()
        if row is None:
            self._conflict("registered estimator plan is missing")
        question_rows = connection.execute(
            """
            SELECT question_fingerprint FROM estimator_plan_questions
            WHERE plan_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        provider_rows = connection.execute(
            """
            SELECT * FROM estimator_plan_provider_schemas
            WHERE plan_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        family_rows = connection.execute(
            """
            SELECT * FROM estimator_candidate_families
            WHERE plan_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        families: list[CandidateFamilySelection] = []
        for family_row in family_rows:
            family_key = family_row["family_key"]
            candidate_rows = connection.execute(
                """
                SELECT artifact_fingerprint FROM estimator_candidate_models
                WHERE plan_fingerprint = ? AND family_key = ? ORDER BY ordinal
                """,
                (fingerprint, family_key),
            ).fetchall()
            promotion_rows = connection.execute(
                """
                SELECT artifact_fingerprint FROM estimator_candidate_promotions
                WHERE plan_fingerprint = ? AND family_key = ? ORDER BY ordinal
                """,
                (fingerprint, family_key),
            ).fetchall()
            baseline_rows = connection.execute(
                """
                SELECT baseline_id FROM estimator_candidate_baselines
                WHERE plan_fingerprint = ? AND family_key = ? ORDER BY ordinal
                """,
                (fingerprint, family_key),
            ).fetchall()
            families.append(
                CandidateFamilySelection(
                    family_key=family_key,
                    screened_candidates=tuple(
                        self._hydrate_artifact(
                            connection, item["artifact_fingerprint"]
                        )
                        for item in candidate_rows
                    ),
                    promoted_artifact_fingerprints=tuple(
                        item["artifact_fingerprint"] for item in promotion_rows
                    ),
                    deterministic_baseline_ids=tuple(
                        item["baseline_id"] for item in baseline_rows
                    ),
                )
            )
        stage_rows = connection.execute(
            """
            SELECT * FROM estimator_plan_stages
            WHERE plan_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        stages = tuple(
            EstimatorStage(
                ordinal=item["ordinal"],
                kind=EstimatorStageKind(item["kind"]),
                condition=StageCondition(item["condition_code"]),
                component_version=item["component_version"],
                configuration_sha256=item["configuration_sha256"],
                output_schema_version=item["output_schema_version"],
                model_artifact=(
                    None
                    if item["artifact_fingerprint"] is None
                    else self._hydrate_artifact(
                        connection, item["artifact_fingerprint"]
                    )
                ),
                candidate_family_key=item["candidate_family_key"],
            )
            for item in stage_rows
        )
        plan = EstimatorPlan(
            contract_version=row["contract_version"],
            plan_key=row["plan_key"],
            plan_version=row["plan_version"],
            route=EstimatorRoute(row["route"]),
            question_specs=tuple(
                self._hydrate_question(connection, item["question_fingerprint"])
                for item in question_rows
            ),
            evidence_packet_schema_version=row["evidence_packet_schema_version"],
            provider_schemas=tuple(
                ProviderSchemaIdentity(
                    provider=Provider(item["provider"]),
                    adapter_version=item["adapter_version"],
                    provider_schema_version=item["provider_schema_version"],
                )
                for item in provider_rows
            ),
            preprocessing_version=row["preprocessing_version"],
            preprocessing_sha256=row["preprocessing_sha256"],
            reasoning_effort=EstimatorReasoningEffort(row["reasoning_effort"]),
            calibration_version=row["calibration_version"],
            calibration_sha256=row["calibration_sha256"],
            router_version=row["router_version"],
            router_sha256=row["router_sha256"],
            redactor_version=row["redactor_version"],
            redactor_sha256=row["redactor_sha256"],
            stages=stages,
            candidate_families=tuple(families),
            execution_mode=row["execution_mode"],
            model_load_policy=row["model_load_policy"],
            max_loaded_models=row["max_loaded_models"],
        )
        if plan.canonical_fingerprint != fingerprint:
            self._conflict("stored estimator plan fingerprint is not reproducible")
        return plan

    def save_completed_synthetic_bundle(
        self, bundle: CompletedSyntheticEstimatorBundle
    ) -> None:
        self._ensure_initialized()
        execution_id = bundle.execution.execution_id
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                stored_plan = connection.execute(
                    "SELECT 1 FROM estimator_plans WHERE plan_fingerprint = ?",
                    (bundle.plan.canonical_fingerprint,),
                ).fetchone()
                if stored_plan is None or self._hydrate_plan(
                    connection, bundle.plan.canonical_fingerprint
                ) != bundle.plan:
                    self._conflict("estimator bundle requires its exact registered plan")
                if connection.execute(
                    "SELECT 1 FROM estimator_executions WHERE execution_id = ?",
                    (execution_id,),
                ).fetchone() is not None:
                    if self._hydrate_bundle(connection, execution_id) != bundle:
                        self._conflict("estimator execution identifier conflicts")
                    connection.commit()
                    return
                case_row = connection.execute(
                    """
                    SELECT * FROM estimator_synthetic_cases
                    WHERE case_id = ? OR evidence_packet_fingerprint = ?
                    """,
                    (
                        bundle.test_case.case_id,
                        bundle.evidence_packet.canonical_fingerprint,
                    ),
                ).fetchone()
                if case_row is not None:
                    existing_case = SyntheticEstimatorCase(
                        case_id=case_row["case_id"],
                        case_schema_version=case_row["case_schema_version"],
                        plan_fingerprint=case_row["plan_fingerprint"],
                        evidence_packet_fingerprint=case_row[
                            "evidence_packet_fingerprint"
                        ],
                        created_at=_required_time(case_row["created_at"]),
                        source_kind=case_row["source_kind"],
                    )
                    if (
                        existing_case != bundle.test_case
                        or self._hydrate_packet(
                            connection, bundle.evidence_packet.canonical_fingerprint
                        )
                        != bundle.evidence_packet
                    ):
                        self._conflict(
                            "synthetic estimator case conflicts with immutable storage"
                        )
                self._insert_bundle(
                    connection,
                    bundle,
                    persist_case=case_row is None,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _insert_bundle(
        self,
        connection,
        bundle: CompletedSyntheticEstimatorBundle,
        *,
        persist_case: bool,
    ) -> None:
        test_case = bundle.test_case
        packet = bundle.evidence_packet
        packet_fingerprint = packet.canonical_fingerprint
        plan_fingerprint = bundle.plan.canonical_fingerprint
        execution = bundle.execution

        if persist_case:
            connection.executemany(
                """
                INSERT INTO estimator_evidence_refs(
                    packet_fingerprint, ordinal, evidence_ref
                ) VALUES (?, ?, ?)
                """,
                (
                    (packet_fingerprint, ordinal, reference)
                    for ordinal, reference in enumerate(packet.opaque_evidence_refs)
                ),
            )
            connection.execute(
                """
                INSERT INTO estimator_evidence_packets(
                    packet_fingerprint, case_id, contract_version,
                    packet_schema_version, packet_sha256, requirements_sha256,
                    chronology_sha256, retrieval_index_sha256, provider,
                    adapter_version, provider_schema_version,
                    preprocessing_version, preprocessing_sha256,
                    redactor_version, redactor_sha256,
                    source_record_count, requirement_count, action_count,
                    decision_count, feedback_count, verification_count,
                    evidence_ref_count, created_at, ephemeral_payload_retained
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    packet_fingerprint,
                    test_case.case_id,
                    packet.contract_version,
                    packet.packet_schema_version,
                    packet.packet_sha256,
                    packet.requirements_sha256,
                    packet.chronology_sha256,
                    packet.retrieval_index_sha256,
                    packet.provider.value,
                    packet.adapter_version,
                    packet.provider_schema_version,
                    packet.preprocessing_version,
                    packet.preprocessing_sha256,
                    packet.redactor_version,
                    packet.redactor_sha256,
                    packet.source_record_count,
                    packet.requirement_count,
                    packet.action_count,
                    packet.decision_count,
                    packet.feedback_count,
                    packet.verification_count,
                    len(packet.opaque_evidence_refs),
                    to_iso(packet.created_at),
                ),
            )
            connection.execute(
                """
                INSERT INTO estimator_synthetic_cases(
                    case_id, case_schema_version, plan_fingerprint,
                    evidence_packet_fingerprint, created_at, source_kind
                ) VALUES (?, ?, ?, ?, ?, 'synthetic')
                """,
                (
                    test_case.case_id,
                    test_case.case_schema_version,
                    plan_fingerprint,
                    packet_fingerprint,
                    to_iso(test_case.created_at),
                ),
            )
        connection.executemany(
            """
            INSERT INTO estimator_stage_receipts(
                execution_id, ordinal, kind, state, outcome_code,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    execution.execution_id,
                    receipt.ordinal,
                    receipt.kind.value,
                    receipt.state.value,
                    receipt.outcome_code,
                    None if receipt.started_at is None else to_iso(receipt.started_at),
                    None
                    if receipt.finished_at is None
                    else to_iso(receipt.finished_at),
                )
                for receipt in execution.stage_receipts
            ),
        )
        for run in bundle.model_runs:
            self._insert_run(connection, run)
        for vote in bundle.model_votes:
            self._insert_vote(connection, vote)
        for estimate in bundle.metric_estimates:
            self._insert_estimate(connection, estimate)
        connection.execute(
            """
            INSERT INTO estimator_executions(
                execution_id, case_id, contract_version, plan_fingerprint,
                evidence_packet_fingerprint, route, project_id, session_id,
                state, created_at, started_at, finished_at,
                cascade_stop_stage_ordinal, cascade_stop_stage_kind,
                cascade_stop_reason_code, stage_receipt_count, model_run_count,
                model_vote_count, metric_estimate_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution.execution_id,
                test_case.case_id,
                execution.contract_version,
                plan_fingerprint,
                packet_fingerprint,
                execution.route.value,
                execution.project_id,
                execution.session_id,
                execution.state.value,
                to_iso(execution.created_at),
                to_iso(execution.started_at),  # validated terminal execution
                to_iso(execution.finished_at),
                execution.cascade_stop_stage_ordinal,
                execution.cascade_stop_stage_kind.value,
                execution.cascade_stop_reason_code,
                len(execution.stage_receipts),
                len(bundle.model_runs),
                len(bundle.model_votes),
                len(bundle.metric_estimates),
            ),
        )

    @staticmethod
    def _insert_run(connection, run: ModelRun) -> None:
        disclosure = run.execution
        connection.execute(
            """
            INSERT INTO estimator_model_runs(
                run_id, execution_id, contract_version, plan_fingerprint,
                evidence_packet_fingerprint, route, stage_ordinal, stage_kind,
                artifact_fingerprint, destination, retention_class,
                retention_days, disclosure_version, approval_receipt_id,
                retention_acknowledged, state, started_at, finished_at,
                cold_start, queue_latency_ms, latency_ms, input_tokens,
                output_tokens, peak_ram_mib, peak_vram_mib, disk_mib,
                energy_mwh, api_cost_microusd, throughput_unit_code,
                measured_unit_count, throughput_window_ms,
                throughput_provenance_version, usage_provenance_version,
                response_schema_version, structured_output_valid, fallback_used,
                fallback_reason_code, refusal_code, failure_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.execution_id,
                run.contract_version,
                run.plan_fingerprint,
                run.evidence_packet_fingerprint,
                run.route.value,
                run.stage_ordinal,
                run.stage_kind.value,
                run.model_artifact.canonical_fingerprint,
                disclosure.destination.value,
                disclosure.retention_class.value,
                disclosure.retention_days,
                disclosure.disclosure_version,
                disclosure.approval_receipt_id,
                int(disclosure.retention_acknowledged),
                run.state.value,
                to_iso(run.started_at),
                to_iso(run.finished_at),
                int(run.cold_start),
                run.queue_latency_ms,
                run.latency_ms,
                run.input_tokens,
                run.output_tokens,
                run.peak_ram_mib,
                run.peak_vram_mib,
                run.disk_mib,
                run.energy_mwh,
                run.api_cost_microusd,
                run.throughput_unit_code,
                run.measured_unit_count,
                run.throughput_window_ms,
                run.throughput_provenance_version,
                run.usage_provenance_version,
                run.response_schema_version,
                int(run.structured_output_valid),
                int(run.fallback_used),
                run.fallback_reason_code,
                run.refusal_code,
                run.failure_code,
            ),
        )

    @staticmethod
    def _insert_vote(connection, vote: ModelVote) -> None:
        connection.executemany(
            """
            INSERT INTO estimator_vote_probabilities(
                vote_id, ordinal, label_code, probability
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (vote.vote_id, ordinal, item.label_code, item.probability)
                for ordinal, item in enumerate(vote.probabilities)
            ),
        )
        connection.executemany(
            """
            INSERT INTO estimator_vote_evidence_refs(
                vote_id, ordinal, evidence_ref
            ) VALUES (?, ?, ?)
            """,
            (
                (vote.vote_id, ordinal, reference)
                for ordinal, reference in enumerate(vote.opaque_evidence_refs)
            ),
        )
        connection.execute(
            """
            INSERT INTO estimator_model_votes(
                vote_id, execution_id, model_run_id, contract_version,
                plan_fingerprint, evidence_packet_fingerprint,
                metric_question_fingerprint, metric_key, state, value_kind,
                numeric_value, label_code, confidence, unknown_reason_code,
                abstention_reason_code, not_applicable_reason_code, failure_code,
                probability_count, evidence_ref_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vote.vote_id,
                vote.execution_id,
                vote.model_run_id,
                vote.contract_version,
                vote.plan_fingerprint,
                vote.evidence_packet_fingerprint,
                vote.metric_question_fingerprint,
                vote.metric_key,
                vote.state.value,
                vote.value_kind.value,
                vote.numeric_value,
                vote.label_code,
                vote.confidence,
                vote.unknown_reason_code,
                vote.abstention_reason_code,
                vote.not_applicable_reason_code,
                vote.failure_code,
                len(vote.probabilities),
                len(vote.opaque_evidence_refs),
            ),
        )

    @staticmethod
    def _insert_estimate(connection, estimate: MetricEstimate) -> None:
        connection.executemany(
            """
            INSERT INTO estimator_estimate_votes(estimate_id, ordinal, vote_id)
            VALUES (?, ?, ?)
            """,
            (
                (estimate.estimate_id, ordinal, vote_id)
                for ordinal, vote_id in enumerate(estimate.vote_ids)
            ),
        )
        uncertainty = estimate.uncertainty
        connection.execute(
            """
            INSERT INTO estimator_metric_estimates(
                estimate_id, execution_id, contract_version, plan_fingerprint,
                evidence_packet_fingerprint, metric_question_fingerprint,
                metric_key, source, state, value_kind, unit_code, numeric_value,
                label_code, numerator, denominator, uncertainty_kind,
                uncertainty_confidence, uncertainty_lower_bound,
                uncertainty_upper_bound, uncertainty_confidence_level,
                uncertainty_entropy, uncertainty_reason_code, evidence_coverage,
                adjudication_id, unknown_reason_code, abstention_reason_code,
                not_applicable_reason_code, failure_code, vote_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                estimate.estimate_id,
                estimate.execution_id,
                estimate.contract_version,
                estimate.plan_fingerprint,
                estimate.evidence_packet_fingerprint,
                estimate.metric_question_fingerprint,
                estimate.metric_key,
                estimate.source.value,
                estimate.state.value,
                estimate.value_kind.value,
                estimate.unit_code,
                estimate.numeric_value,
                estimate.label_code,
                estimate.numerator,
                estimate.denominator,
                None if uncertainty is None else uncertainty.kind.value,
                None if uncertainty is None else uncertainty.confidence,
                None if uncertainty is None else uncertainty.lower_bound,
                None if uncertainty is None else uncertainty.upper_bound,
                None if uncertainty is None else uncertainty.confidence_level,
                None if uncertainty is None else uncertainty.entropy,
                None if uncertainty is None else uncertainty.reason_code,
                estimate.evidence_coverage,
                estimate.adjudication_id,
                estimate.unknown_reason_code,
                estimate.abstention_reason_code,
                estimate.not_applicable_reason_code,
                estimate.failure_code,
                len(estimate.vote_ids),
                to_iso(estimate.created_at),
            ),
        )

    def get_completed_bundle(
        self, execution_id: str
    ) -> CompletedSyntheticEstimatorBundle | None:
        self._ensure_initialized()
        require_safe_id(execution_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM estimator_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_bundle(connection, execution_id)

    def _hydrate_bundle(
        self, connection, execution_id: str
    ) -> CompletedSyntheticEstimatorBundle:
            row = connection.execute(
                "SELECT * FROM estimator_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                self._conflict("estimator execution is missing")
            case_row = connection.execute(
                "SELECT * FROM estimator_synthetic_cases WHERE case_id = ?",
                (row["case_id"],),
            ).fetchone()
            if case_row is None:
                self._conflict("estimator case is missing")
            plan = self._hydrate_plan(connection, row["plan_fingerprint"])
            packet = self._hydrate_packet(
                connection, row["evidence_packet_fingerprint"]
            )
            test_case = SyntheticEstimatorCase(
                case_id=case_row["case_id"],
                case_schema_version=case_row["case_schema_version"],
                plan_fingerprint=case_row["plan_fingerprint"],
                evidence_packet_fingerprint=case_row["evidence_packet_fingerprint"],
                created_at=_required_time(case_row["created_at"]),
                source_kind=case_row["source_kind"],
            )
            receipt_rows = connection.execute(
                """
                SELECT * FROM estimator_stage_receipts
                WHERE execution_id = ? ORDER BY ordinal
                """,
                (execution_id,),
            ).fetchall()
            execution = EstimatorExecution(
                contract_version=row["contract_version"],
                execution_id=row["execution_id"],
                plan_fingerprint=row["plan_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                route=EstimatorRoute(row["route"]),
                project_id=row["project_id"],
                session_id=row["session_id"],
                state=EstimatorExecutionState(row["state"]),
                created_at=_required_time(row["created_at"]),
                started_at=_required_time(row["started_at"]),
                finished_at=_required_time(row["finished_at"]),
                stage_receipts=tuple(
                    EstimatorStageReceipt(
                        ordinal=item["ordinal"],
                        kind=EstimatorStageKind(item["kind"]),
                        state=EstimatorStageReceiptState(item["state"]),
                        outcome_code=item["outcome_code"],
                        started_at=from_iso(item["started_at"]),
                        finished_at=from_iso(item["finished_at"]),
                    )
                    for item in receipt_rows
                ),
                cascade_stop_stage_ordinal=row["cascade_stop_stage_ordinal"],
                cascade_stop_stage_kind=EstimatorStageKind(
                    row["cascade_stop_stage_kind"]
                ),
                cascade_stop_reason_code=row["cascade_stop_reason_code"],
            )
            run_rows = connection.execute(
                """
                SELECT * FROM estimator_model_runs
                WHERE execution_id = ?
                ORDER BY stage_ordinal, started_at, finished_at, run_id
                """,
                (execution_id,),
            ).fetchall()
            runs = tuple(self._hydrate_run(connection, item) for item in run_rows)
            vote_rows = connection.execute(
                """
                SELECT * FROM estimator_model_votes
                WHERE execution_id = ? ORDER BY metric_key, vote_id
                """,
                (execution_id,),
            ).fetchall()
            votes = tuple(self._hydrate_vote(connection, item) for item in vote_rows)
            estimate_rows = connection.execute(
                """
                SELECT * FROM estimator_metric_estimates
                WHERE execution_id = ? ORDER BY metric_key, estimate_id
                """,
                (execution_id,),
            ).fetchall()
            estimates = tuple(
                self._hydrate_estimate(connection, item) for item in estimate_rows
            )
            return CompletedSyntheticEstimatorBundle(
                test_case=test_case,
                plan=plan,
                evidence_packet=packet,
                execution=execution,
                model_runs=runs,
                model_votes=votes,
                metric_estimates=estimates,
            )

    @staticmethod
    def _hydrate_packet(connection, fingerprint: str) -> EvidencePacketReceipt:
        row = connection.execute(
            "SELECT * FROM estimator_evidence_packets WHERE packet_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("estimator evidence receipt is missing")
        refs = connection.execute(
            """
            SELECT evidence_ref FROM estimator_evidence_refs
            WHERE packet_fingerprint = ? ORDER BY ordinal
            """,
            (fingerprint,),
        ).fetchall()
        packet = EvidencePacketReceipt(
            contract_version=row["contract_version"],
            packet_schema_version=row["packet_schema_version"],
            packet_sha256=row["packet_sha256"],
            requirements_sha256=row["requirements_sha256"],
            chronology_sha256=row["chronology_sha256"],
            retrieval_index_sha256=row["retrieval_index_sha256"],
            provider=Provider(row["provider"]),
            adapter_version=row["adapter_version"],
            provider_schema_version=row["provider_schema_version"],
            preprocessing_version=row["preprocessing_version"],
            preprocessing_sha256=row["preprocessing_sha256"],
            redactor_version=row["redactor_version"],
            redactor_sha256=row["redactor_sha256"],
            source_record_count=row["source_record_count"],
            requirement_count=row["requirement_count"],
            action_count=row["action_count"],
            decision_count=row["decision_count"],
            feedback_count=row["feedback_count"],
            verification_count=row["verification_count"],
            opaque_evidence_refs=tuple(item["evidence_ref"] for item in refs),
            created_at=_required_time(row["created_at"]),
            ephemeral_payload_retained=False,
        )
        if packet.canonical_fingerprint != fingerprint:
            raise DatabaseInvariantError(
                "stored evidence receipt fingerprint is not reproducible"
            )
        return packet

    def _hydrate_run(self, connection, row) -> ModelRun:
        return ModelRun(
            contract_version=row["contract_version"],
            run_id=row["run_id"],
            execution_id=row["execution_id"],
            plan_fingerprint=row["plan_fingerprint"],
            evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
            route=EstimatorRoute(row["route"]),
            stage_ordinal=row["stage_ordinal"],
            stage_kind=EstimatorStageKind(row["stage_kind"]),
            model_artifact=self._hydrate_artifact(
                connection, row["artifact_fingerprint"]
            ),
            execution=ExecutionDisclosure(
                destination=ExecutionDestination(row["destination"]),
                retention_class=RetentionClass(row["retention_class"]),
                retention_days=row["retention_days"],
                disclosure_version=row["disclosure_version"],
                approval_receipt_id=row["approval_receipt_id"],
                retention_acknowledged=bool(row["retention_acknowledged"]),
            ),
            state=ModelRunState(row["state"]),
            started_at=_required_time(row["started_at"]),
            finished_at=_required_time(row["finished_at"]),
            cold_start=bool(row["cold_start"]),
            queue_latency_ms=row["queue_latency_ms"],
            latency_ms=row["latency_ms"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            peak_ram_mib=row["peak_ram_mib"],
            peak_vram_mib=row["peak_vram_mib"],
            disk_mib=row["disk_mib"],
            energy_mwh=row["energy_mwh"],
            api_cost_microusd=row["api_cost_microusd"],
            throughput_unit_code=row["throughput_unit_code"],
            measured_unit_count=row["measured_unit_count"],
            throughput_window_ms=row["throughput_window_ms"],
            throughput_provenance_version=row["throughput_provenance_version"],
            usage_provenance_version=row["usage_provenance_version"],
            response_schema_version=row["response_schema_version"],
            structured_output_valid=bool(row["structured_output_valid"]),
            fallback_used=bool(row["fallback_used"]),
            fallback_reason_code=row["fallback_reason_code"],
            refusal_code=row["refusal_code"],
            failure_code=row["failure_code"],
        )

    @staticmethod
    def _hydrate_vote(connection, row) -> ModelVote:
        probabilities = connection.execute(
            """
            SELECT label_code, probability FROM estimator_vote_probabilities
            WHERE vote_id = ? ORDER BY ordinal
            """,
            (row["vote_id"],),
        ).fetchall()
        refs = connection.execute(
            """
            SELECT evidence_ref FROM estimator_vote_evidence_refs
            WHERE vote_id = ? ORDER BY ordinal
            """,
            (row["vote_id"],),
        ).fetchall()
        return ModelVote(
            contract_version=row["contract_version"],
            vote_id=row["vote_id"],
            execution_id=row["execution_id"],
            model_run_id=row["model_run_id"],
            plan_fingerprint=row["plan_fingerprint"],
            evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
            metric_question_fingerprint=row["metric_question_fingerprint"],
            metric_key=row["metric_key"],
            state=MetricEstimateState(row["state"]),
            value_kind=MetricValueKind(row["value_kind"]),
            numeric_value=row["numeric_value"],
            label_code=row["label_code"],
            confidence=row["confidence"],
            probabilities=tuple(
                LabelProbability(
                    label_code=item["label_code"], probability=item["probability"]
                )
                for item in probabilities
            ),
            opaque_evidence_refs=tuple(item["evidence_ref"] for item in refs),
            unknown_reason_code=row["unknown_reason_code"],
            abstention_reason_code=row["abstention_reason_code"],
            not_applicable_reason_code=row["not_applicable_reason_code"],
            failure_code=row["failure_code"],
        )

    @staticmethod
    def _hydrate_estimate(connection, row) -> MetricEstimate:
        vote_rows = connection.execute(
            """
            SELECT vote_id FROM estimator_estimate_votes
            WHERE estimate_id = ? ORDER BY ordinal
            """,
            (row["estimate_id"],),
        ).fetchall()
        uncertainty = None
        if row["uncertainty_kind"] is not None:
            uncertainty = EstimateUncertainty(
                kind=UncertaintyKind(row["uncertainty_kind"]),
                confidence=row["uncertainty_confidence"],
                lower_bound=row["uncertainty_lower_bound"],
                upper_bound=row["uncertainty_upper_bound"],
                confidence_level=row["uncertainty_confidence_level"],
                entropy=row["uncertainty_entropy"],
                reason_code=row["uncertainty_reason_code"],
            )
        return MetricEstimate(
            contract_version=row["contract_version"],
            estimate_id=row["estimate_id"],
            execution_id=row["execution_id"],
            plan_fingerprint=row["plan_fingerprint"],
            evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
            metric_question_fingerprint=row["metric_question_fingerprint"],
            metric_key=row["metric_key"],
            source=MetricEstimateSource(row["source"]),
            state=MetricEstimateState(row["state"]),
            value_kind=MetricValueKind(row["value_kind"]),
            unit_code=row["unit_code"],
            numeric_value=row["numeric_value"],
            label_code=row["label_code"],
            numerator=row["numerator"],
            denominator=row["denominator"],
            uncertainty=uncertainty,
            evidence_coverage=row["evidence_coverage"],
            vote_ids=tuple(item["vote_id"] for item in vote_rows),
            adjudication_id=row["adjudication_id"],
            unknown_reason_code=row["unknown_reason_code"],
            abstention_reason_code=row["abstention_reason_code"],
            not_applicable_reason_code=row["not_applicable_reason_code"],
            failure_code=row["failure_code"],
            created_at=_required_time(row["created_at"]),
        )

    def model_lab_summary(self, plan_fingerprint: str) -> ModelLabSummary:
        self._ensure_initialized()
        require_safe_id(plan_fingerprint)
        with self._connection_scope(readonly=True) as connection:
            registered = connection.execute(
                "SELECT 1 FROM estimator_plans WHERE plan_fingerprint = ?",
                (plan_fingerprint,),
            ).fetchone() is not None
            counts = connection.execute(
                """
                SELECT COUNT(DISTINCT execution.execution_id) AS execution_count,
                       COUNT(estimate.estimate_id) AS estimate_count
                FROM estimator_executions AS execution
                LEFT JOIN estimator_metric_estimates AS estimate
                  ON estimate.execution_id = execution.execution_id
                WHERE execution.plan_fingerprint = ?
                """,
                (plan_fingerprint,),
            ).fetchone()
        return ModelLabSummary(
            plan_fingerprint=plan_fingerprint,
            registered=registered,
            synthetic_execution_count=counts["execution_count"],
            metric_estimate_count=counts["estimate_count"],
            activation_outcome=ActivationAttemptOutcome.SYNTHETIC_OR_INSUFFICIENT,
            activation_allowed=False,
        )

    def model_lab_inventory(self) -> ModelLabInventory:
        """Return bounded synthetic aggregates without hydrating private evidence."""

        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT plan.plan_fingerprint,
                       plan.plan_key,
                       plan.plan_version,
                       plan.route,
                       plan.question_count,
                       COUNT(execution.execution_id) AS execution_count,
                       COALESCE(SUM(execution.model_run_count), 0) AS run_count,
                       COALESCE(SUM(execution.model_vote_count), 0) AS vote_count,
                       COALESCE(SUM(execution.metric_estimate_count), 0)
                           AS estimate_count
                FROM estimator_plans AS plan
                LEFT JOIN estimator_executions AS execution
                  ON execution.plan_fingerprint = plan.plan_fingerprint
                WHERE plan.uses_synthetic_model = 1
                GROUP BY plan.plan_fingerprint,
                         plan.plan_key,
                         plan.plan_version,
                         plan.route,
                         plan.question_count
                ORDER BY plan.plan_key, plan.plan_version, plan.plan_fingerprint
                LIMIT ?
                """,
                (MAX_MODEL_LAB_PLANS + 1,),
            ).fetchall()
        if len(rows) > MAX_MODEL_LAB_PLANS:
            raise DatabaseInvariantError("model lab plan inventory exceeds its safe bound")
        plans = tuple(
            ModelLabPlanSummary(
                plan_fingerprint=row["plan_fingerprint"],
                plan_key=row["plan_key"],
                plan_version=row["plan_version"],
                route=EstimatorRoute(row["route"]),
                metric_question_count=row["question_count"],
                synthetic_execution_count=row["execution_count"],
                model_run_count=row["run_count"],
                model_vote_count=row["vote_count"],
                metric_estimate_count=row["estimate_count"],
                activation_outcome=(
                    ActivationAttemptOutcome.SYNTHETIC_OR_INSUFFICIENT
                ),
                activation_allowed=False,
            )
            for row in rows
        )
        return ModelLabInventory(
            registered_plan_count=len(plans),
            synthetic_execution_count=sum(
                plan.synthetic_execution_count for plan in plans
            ),
            model_run_count=sum(plan.model_run_count for plan in plans),
            model_vote_count=sum(plan.model_vote_count for plan in plans),
            metric_estimate_count=sum(plan.metric_estimate_count for plan in plans),
            activation_outcome=ActivationAttemptOutcome.SYNTHETIC_OR_INSUFFICIENT,
            activation_allowed=False,
            plans=plans,
        )

    def attempt_activation(self, plan_fingerprint: str) -> ModelLabSummary:
        """Fail closed; synthetic inventory can never create an activation row."""

        return self.model_lab_summary(plan_fingerprint)

    def register_preregistered_campaign(
        self, campaign: PreregisteredEstimatorCampaign
    ) -> str:
        """Atomically seal a non-synthetic campaign, writing its root last."""

        self._ensure_initialized()
        # ``model_copy(update=...)`` can bypass Pydantic validators. Rebuild the
        # complete nested value at the trust boundary before fingerprinting or
        # opening a write transaction.
        campaign = PreregisteredEstimatorCampaign.model_validate(
            campaign.model_dump(mode="python")
        )
        fingerprint = campaign.fingerprint
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                tombstone = connection.execute(
                    "SELECT 1 FROM estimator_gate_campaign_tombstones WHERE revocation_key = ?",
                    (_campaign_revocation_key(campaign.campaign_id),),
                ).fetchone()
                if tombstone is not None:
                    self._conflict(
                        "estimator campaign identifier was revoked by privacy deletion"
                    )
                existing = connection.execute(
                    "SELECT campaign_fingerprint FROM estimator_gate_campaigns WHERE campaign_id = ?",
                    (campaign.campaign_id,),
                ).fetchone()
                if existing is not None:
                    if existing["campaign_fingerprint"] != fingerprint:
                        self._conflict("estimator campaign identifier conflicts with storage")
                    hydrated = self._hydrate_preregistered_campaign(
                        connection, campaign.campaign_id
                    )
                    if hydrated != campaign:
                        self._conflict("estimator campaign fingerprint conflicts with storage")
                    connection.commit()
                    return fingerprint

                plan_fingerprint = campaign.stored_plan.canonical_fingerprint
                plan_row = connection.execute(
                    "SELECT uses_synthetic_model FROM estimator_plans WHERE plan_fingerprint = ?",
                    (plan_fingerprint,),
                ).fetchone()
                if plan_row is None:
                    self._conflict("estimator campaign requires a previously stored plan")
                if bool(plan_row["uses_synthetic_model"]):
                    self._conflict("estimator campaign plan must be non-synthetic")
                if self._hydrate_plan(connection, plan_fingerprint) != campaign.stored_plan:
                    self._conflict("stored estimator plan conflicts with campaign")
                if _v16_plan_has_unsafe_identifier(campaign.stored_plan):
                    self._conflict(
                        "stored estimator plan contains path or URI shaped identifiers"
                    )

                connection.execute(
                    "INSERT OR IGNORE INTO estimator_gate_safe_plan_audits(plan_fingerprint) VALUES (?)",
                    (plan_fingerprint,),
                )

                self._insert_gate_policy(connection, campaign.policy)
                self._insert_case_manifest(connection, campaign.assignment_manifest)
                self._insert_calibration_split(connection, campaign.split)
                self._insert_legacy_preregistration(
                    connection, campaign.legacy_preregistration
                )
                self._insert_constellation(
                    connection, campaign.constellation_identity
                )
                preregistration_v2 = campaign.preregistration_v2
                connection.execute(
                    """
                    INSERT INTO estimator_preregistrations_v2(
                        preregistration_fingerprint, contract_version,
                        preregistration_id, policy_fingerprint,
                        assignment_manifest_fingerprint, split_fingerprint,
                        stored_plan_fingerprint, constellation_fingerprint,
                        legacy_preregistration_fingerprint, registered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        preregistration_v2.fingerprint,
                        preregistration_v2.contract_version,
                        preregistration_v2.preregistration_id,
                        preregistration_v2.policy_fingerprint,
                        preregistration_v2.assignment_manifest_fingerprint,
                        preregistration_v2.split_fingerprint,
                        preregistration_v2.stored_plan_fingerprint,
                        preregistration_v2.constellation_fingerprint,
                        preregistration_v2.legacy_preregistration_fingerprint,
                        to_iso(preregistration_v2.registered_at),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO estimator_gate_campaigns(
                        campaign_id, campaign_fingerprint, contract_version,
                        stored_plan_fingerprint, policy_fingerprint,
                        assignment_manifest_fingerprint, split_fingerprint,
                        legacy_preregistration_fingerprint,
                        preregistration_v2_fingerprint,
                        constellation_fingerprint, registered_at,
                        activation_allowed, private_export_allowed,
                        team_share_allowed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                    """,
                    (
                        campaign.campaign_id,
                        fingerprint,
                        campaign.contract_version,
                        plan_fingerprint,
                        campaign.policy.fingerprint,
                        campaign.assignment_manifest.fingerprint,
                        campaign.split.fingerprint,
                        campaign.legacy_preregistration.fingerprint,
                        preregistration_v2.fingerprint,
                        campaign.constellation_identity.fingerprint,
                        to_iso(campaign.registered_at),
                    ),
                )
                connection.commit()
                return fingerprint
            except Exception:
                connection.rollback()
                raise

    def get_preregistered_campaign(
        self, campaign_id: str
    ) -> PreregisteredEstimatorCampaign | None:
        self._ensure_initialized()
        require_safe_id(campaign_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM estimator_gate_campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_preregistered_campaign(connection, campaign_id)

    @classmethod
    def _insert_exact(
        cls,
        connection,
        table: str,
        key: dict[str, object],
        values: dict[str, object],
    ) -> None:
        """Append one immutable row, accepting only byte-for-byte replay."""

        columns = tuple(values)
        where = " AND ".join(f"{column} = ?" for column in key)
        existing = connection.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE {where}",
            tuple(key.values()),
        ).fetchone()
        expected = tuple(values[column] for column in columns)
        if existing is not None:
            if tuple(existing[column] for column in columns) != expected:
                cls._conflict(f"{table} immutable identifier conflicts with storage")
            return
        placeholders = ", ".join("?" for _ in columns)
        try:
            connection.execute(
                f"INSERT INTO {table}({', '.join(columns)}) VALUES ({placeholders})",
                expected,
            )
        except sqlite3.IntegrityError:
            cls._conflict(f"{table} evidence conflicts with sealed storage")

    def append_calibration_evidence_submission(
        self,
        submission: CalibrationEvidenceSubmissionV1,
        *,
        seal: bool = True,
    ) -> str | None:
        """Append dynamic evidence and optionally write the final root last.

        ``seal=False`` is a durable restart checkpoint: every supplied leaf and
        component root is immutable, but readers still see no evidence set.
        Replaying the exact submission with ``seal=True`` writes only the final
        root. Conflicting replays fail atomically.
        """

        self._ensure_initialized()
        submission = revalidate_calibration_evidence_submission_v1(submission)
        require_safe_id(submission.submission_id)
        require_safe_id(submission.campaign_id)
        if (
            self._begin_evidence_authorization is None
            or self._end_evidence_authorization is None
        ):
            self._conflict("calibration evidence persistence is not authorized")
        authorization_id, authorization_tag = self._begin_evidence_authorization(
            submission.submission_id, submission.campaign_id
        )
        try:
            with self._connection_scope() as connection:
                try:
                    # Python's sqlite3 API cannot mark registered functions
                    # SQLITE_INNOCUOUS. Enable trusted-schema evaluation only
                    # on this private connection while the non-SQL-forgeable
                    # in-memory authorization is active, then disable it
                    # before returning the connection.
                    connection.execute("PRAGMA trusted_schema = ON")
                    connection.execute("BEGIN IMMEDIATE")
                    campaign = self._hydrate_preregistered_campaign(
                        connection, submission.campaign_id
                    )
                    self._validate_evidence_campaign_lineage(
                        campaign,
                        submission,
                        verifier=self._structured_estimate_verifier,
                    )
                    sealed = connection.execute(
                        "SELECT submission_fingerprint FROM estimator_evidence_submissions WHERE submission_id = ?",
                        (submission.submission_id,),
                    ).fetchone()
                    if sealed is not None:
                        if sealed["submission_fingerprint"] != submission.fingerprint:
                            self._conflict(
                                "calibration evidence submission conflicts with storage"
                            )
                        hydrated = self._hydrate_calibration_evidence_submission(
                            connection, submission.submission_id
                        )
                        if hydrated != submission:
                            self._conflict(
                                "calibration evidence fingerprint conflicts with storage"
                            )
                        connection.commit()
                        connection.execute("PRAGMA trusted_schema = OFF")
                        return submission.fingerprint if seal else None

                    connection.execute(
                        "INSERT INTO estimator_evidence_append_authorizations VALUES (?, ?, ?, ?)",
                        (
                            authorization_id,
                            submission.submission_id,
                            submission.campaign_id,
                            authorization_tag,
                        ),
                    )
                    self._append_calibration_evidence_rows(connection, submission)
                    if seal:
                        self._insert_evidence_submission_root(connection, submission)
                    connection.execute(
                        "DELETE FROM estimator_evidence_append_authorizations WHERE authorization_id = ?",
                        (authorization_id,),
                    )
                    connection.commit()
                    connection.execute("PRAGMA trusted_schema = OFF")
                    return submission.fingerprint if seal else None
                except Exception:
                    connection.rollback()
                    connection.execute("PRAGMA trusted_schema = OFF")
                    raise
        finally:
            self._end_evidence_authorization(
                authorization_id,
                submission.submission_id,
                submission.campaign_id,
                authorization_tag,
            )

    def get_calibration_evidence_submission(
        self, submission_id: str
    ) -> CalibrationEvidenceSubmissionV1 | None:
        self._ensure_initialized()
        require_safe_id(submission_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM estimator_evidence_submissions WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_calibration_evidence_submission(
                connection, submission_id
            )

    @classmethod
    def _validate_evidence_campaign_lineage(
        cls,
        campaign: PreregisteredEstimatorCampaign,
        submission: CalibrationEvidenceSubmissionV1,
        *,
        verifier: StructuredEstimateVerifier | None,
    ) -> None:
        cls._validate_evidence_campaign_static_lineage(campaign, submission)

        launches = {item.attempt_id: item for item in submission.attempt_launches}
        outcomes = {item.attempt_id: item for item in submission.attempt_outcomes}
        if submission.structured_estimate_receipts and verifier is None:
            cls._conflict(
                "structured estimates require an independent output verifier"
            )
        for caller_receipt in submission.structured_estimate_receipts:
            assert verifier is not None
            independently_decoded = verifier.verify_structured_estimate(
                launch=launches[caller_receipt.attempt_id],
                outcome=outcomes[caller_receipt.attempt_id],
            )
            verified = revalidate_content_free_contract(
                StructuredEstimateReceiptV1, independently_decoded
            )
            if verified != caller_receipt:
                cls._conflict(
                    "structured estimate does not match independent decoding"
                )

    @classmethod
    def _validate_evidence_campaign_static_lineage(
        cls,
        campaign: PreregisteredEstimatorCampaign,
        submission: CalibrationEvidenceSubmissionV1,
    ) -> None:
        """Recheck content-free campaign lineage without decoding model output.

        This check deliberately runs both before append and after hydration. The
        latter makes a stored evidence root fail closed if any retained v16
        plan, split, question, packet, constellation, or model identity is
        corrupted after sealing.
        """
        if submission.campaign_holdout_case_ids != campaign.split.holdout_case_ids:
            cls._conflict(
                "calibration evidence holdout does not match the sealed campaign"
            )
        if submission.expected_attempt_manifest.frozen_at < campaign.registered_at:
            cls._conflict(
                "expected attempts cannot freeze before campaign registration"
            )
        plan_fingerprint = campaign.stored_plan.canonical_fingerprint
        assignments = {
            item.case_id: item for item in campaign.assignment_manifest.assignments
        }
        constellation = {
            item.stage_fingerprint: item
            for item in campaign.constellation_identity.stages
        }
        artifacts = {
            stage.ordinal: stage.model_artifact
            for stage in campaign.stored_plan.stages
            if stage.model_artifact is not None
        }
        launches = {item.attempt_id: item for item in submission.attempt_launches}
        for expected in submission.expected_attempt_manifest.attempts:
            assignment = assignments.get(expected.case_id)
            stage = constellation.get(expected.constellation_stage_fingerprint)
            launch = launches[expected.attempt_id]
            artifact = artifacts.get(expected.stage_ordinal)
            if (
                assignment is None
                or expected.plan_fingerprint != plan_fingerprint
                or expected.metric_question_fingerprint
                != assignment.metric_question_fingerprint
                or expected.evidence_packet_fingerprint
                != assignment.evidence_packet_fingerprint
                or stage is None
                or stage.ordinal != expected.stage_ordinal
                or stage.kind is not expected.stage_kind
                or stage.stage_configuration_sha256
                != expected.stage_configuration_sha256
                or artifact is None
                or launch.model_artifact_fingerprint
                != stage.model_artifact_fingerprint
                or launch.requested_source is not artifact.source
                or launch.requested_model_id != artifact.requested_model_id
                or launch.requested_revision != artifact.requested_revision
                or launch.requested_execution_mode
                is not artifact.requested_execution_mode
                or launch.response_schema_version != stage.output_schema_version
            ):
                cls._conflict(
                    "calibration attempt does not match the sealed campaign lineage"
                )

    def _append_calibration_evidence_rows(
        self, connection, submission: CalibrationEvidenceSubmissionV1
    ) -> None:
        sid = submission.submission_id
        campaign_id = submission.campaign_id
        for launch in submission.attempt_launches:
            values = {
                "submission_id": sid,
                "launch_id": launch.launch_id,
                "campaign_id": campaign_id,
                "attempt_id": launch.attempt_id,
                "execution_id": launch.execution_id,
                "case_id": launch.case_id,
                "plan_fingerprint": launch.plan_fingerprint,
                "metric_question_fingerprint": launch.metric_question_fingerprint,
                "evidence_packet_fingerprint": launch.evidence_packet_fingerprint,
                "constellation_stage_fingerprint": launch.constellation_stage_fingerprint,
                "stage_ordinal": launch.stage_ordinal,
                "stage_kind": launch.stage_kind.value,
                "stage_configuration_sha256": launch.stage_configuration_sha256,
                "model_artifact_fingerprint": launch.model_artifact_fingerprint,
                "requested_source": launch.requested_source.value,
                "requested_model_id": launch.requested_model_id,
                "requested_revision": launch.requested_revision,
                "requested_execution_mode": launch.requested_execution_mode.value,
                "runner_adapter_key": launch.runner_adapter_key,
                "runner_adapter_version": launch.runner_adapter_version,
                "runner_configuration_sha256": launch.runner_configuration_sha256,
                "response_schema_version": launch.response_schema_version,
                "destination": launch.destination.value,
                "retention_class": launch.retention_class.value,
                "approval_kind": launch.approval_kind.value,
                "approval_id": launch.approval_id,
                "redaction_preview_fingerprint": launch.redaction_preview_fingerprint,
                "approved_at_us": (
                    None
                    if launch.approved_at is None
                    else _to_epoch_us(launch.approved_at)
                ),
                "launched_at_us": _to_epoch_us(launch.launched_at),
                "launch_fingerprint": launch.fingerprint,
            }
            self._insert_exact(
                connection,
                "estimator_evidence_attempt_launches",
                {"submission_id": sid, "attempt_id": launch.attempt_id},
                values,
            )

        for outcome in submission.attempt_outcomes:
            served = outcome.served_identity
            usage = outcome.usage
            resources = outcome.resources
            cost = outcome.cost
            queue = outcome.queue
            values = {
                "submission_id": sid,
                "outcome_id": outcome.outcome_id,
                "outcome_fingerprint": outcome.fingerprint,
                "campaign_id": campaign_id,
                "attempt_id": outcome.attempt_id,
                "execution_id": outcome.execution_id,
                "case_id": outcome.case_id,
                "plan_fingerprint": outcome.plan_fingerprint,
                "metric_question_fingerprint": outcome.metric_question_fingerprint,
                "evidence_packet_fingerprint": outcome.evidence_packet_fingerprint,
                "terminal_state": outcome.state.value,
                "structured_output_fingerprint": outcome.structured_output_fingerprint,
                "terminal_reason_code": outcome.reason_code,
                "served_state": served.state.value,
                "served_source": _enum_value(served.served_source),
                "served_model_id": served.served_model_id,
                "served_revision": served.served_revision,
                "served_execution_mode": _enum_value(served.served_execution_mode),
                "fallback_used": (
                    None if served.fallback_used is None else int(served.fallback_used)
                ),
                "fallback_reason_code": served.fallback_reason_code,
                "served_unavailable_reason_code": served.unavailable_reason_code,
                "token_state": usage.state.value,
                "token_collector_version": usage.collector_version,
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_output_tokens": usage.reasoning_output_tokens,
                "total_tokens": usage.total_tokens,
                "token_reason_code": usage.reason_code,
                "resource_state": resources.state.value,
                "resource_collector_version": resources.collector_version,
                "peak_ram_bytes": resources.peak_ram_bytes,
                "peak_vram_bytes": resources.peak_vram_bytes,
                "energy_millijoules": resources.energy_millijoules,
                "resource_reason_code": resources.reason_code,
                "cost_state": cost.state.value,
                "cost_collector_version": cost.collector_version,
                "amount_microusd": cost.amount_microusd,
                "cost_reason_code": cost.reason_code,
                "queue_key": queue.queue_key,
                "queue_version": queue.queue_version,
                "worker_id": queue.worker_id,
                "enqueued_at_us": _to_epoch_us(queue.enqueued_at),
                "dequeued_at_us": _to_epoch_us(queue.dequeued_at),
                "wait_ms": queue.wait_ms,
                "started_at_us": _to_epoch_us(outcome.started_at),
                "finished_at_us": _to_epoch_us(outcome.finished_at),
                "latency_ms": outcome.latency_ms,
            }
            self._insert_exact(
                connection,
                "estimator_evidence_attempt_outcomes",
                {"submission_id": sid, "attempt_id": outcome.attempt_id},
                values,
            )

        expected_manifest = submission.expected_attempt_manifest
        for ordinal, expected in enumerate(expected_manifest.attempts):
            values = {
                "submission_id": sid,
                "manifest_id": expected_manifest.manifest_id,
                "ordinal": ordinal,
                "attempt_id": expected.attempt_id,
                "execution_id": expected.execution_id,
                "case_id": expected.case_id,
                "plan_fingerprint": expected.plan_fingerprint,
                "metric_question_fingerprint": expected.metric_question_fingerprint,
                "evidence_packet_fingerprint": expected.evidence_packet_fingerprint,
                "constellation_stage_fingerprint": expected.constellation_stage_fingerprint,
                "stage_configuration_sha256": expected.stage_configuration_sha256,
                "stage_ordinal": expected.stage_ordinal,
                "stage_kind": expected.stage_kind.value,
                "attempt_fingerprint": _contract_fingerprint(expected),
                "campaign_id": campaign_id,
            }
            self._insert_exact(
                connection,
                "estimator_evidence_expected_attempts",
                {"submission_id": sid, "ordinal": ordinal},
                values,
            )
        self._insert_exact(
            connection,
            "estimator_evidence_expected_manifests",
            {"submission_id": sid},
            {
                "submission_id": sid,
                "manifest_id": expected_manifest.manifest_id,
                "manifest_fingerprint": expected_manifest.fingerprint,
                "execution_set_fingerprint": expected_manifest.execution_set_fingerprint,
                "campaign_id": campaign_id,
                "plan_fingerprint": expected_manifest.plan_fingerprint,
                "frozen_at_us": _to_epoch_us(expected_manifest.frozen_at),
                "attempt_count": len(expected_manifest.attempts),
            },
        )

        audit = submission.holdout_access_audit
        access_manifest = audit.manifest
        for ordinal, event in enumerate(access_manifest.events):
            self._insert_exact(
                connection,
                "estimator_evidence_access_events",
                {
                    "submission_id": sid,
                    "manifest_id": access_manifest.manifest_id,
                    "ordinal": ordinal,
                },
                {
                    "submission_id": sid,
                    "manifest_id": access_manifest.manifest_id,
                    "ordinal": ordinal,
                    "event_id": event.event_id,
                    "event_fingerprint": event.fingerprint,
                    "campaign_id": campaign_id,
                    "case_id": event.case_id,
                    "actor_id": event.actor_id,
                    "actor_kind": event.actor_kind.value,
                    "access_kind": event.access_kind.value,
                    "occurred_at_us": _to_epoch_us(event.occurred_at),
                },
            )
        for ordinal, gap in enumerate(access_manifest.gaps):
            self._insert_exact(
                connection,
                "estimator_evidence_access_gaps",
                {
                    "submission_id": sid,
                    "manifest_id": access_manifest.manifest_id,
                    "ordinal": ordinal,
                },
                {
                    "submission_id": sid,
                    "manifest_id": access_manifest.manifest_id,
                    "ordinal": ordinal,
                    "gap_id": gap.gap_id,
                    "campaign_id": campaign_id,
                    "reason_code": gap.reason_code,
                    "started_at_us": _to_epoch_us(gap.started_at),
                    "ended_at_us": _to_epoch_us(gap.ended_at),
                },
            )
        self._insert_exact(
            connection,
            "estimator_evidence_access_manifests",
            {"submission_id": sid},
            {
                "submission_id": sid,
                "manifest_id": access_manifest.manifest_id,
                "manifest_fingerprint": access_manifest.fingerprint,
                "event_set_fingerprint": access_manifest.event_set_fingerprint,
                "gap_set_fingerprint": access_manifest.gap_set_fingerprint,
                "campaign_id": campaign_id,
                "auditor_version": access_manifest.auditor_version,
                "coverage_started_at_us": _to_epoch_us(
                    access_manifest.coverage_started_at
                ),
                "coverage_ended_at_us": _to_epoch_us(
                    access_manifest.coverage_ended_at
                ),
                "frozen_at_us": _to_epoch_us(access_manifest.frozen_at),
                "event_count": len(access_manifest.events),
                "gap_count": len(access_manifest.gaps),
            },
        )
        for ordinal, case_id in enumerate(audit.holdout_case_ids):
            self._insert_exact(
                connection,
                "estimator_evidence_access_audit_cases",
                {"submission_id": sid, "ordinal": ordinal},
                {
                    "submission_id": sid,
                    "audit_id": audit.audit_id,
                    "ordinal": ordinal,
                    "case_id": case_id,
                    "campaign_id": campaign_id,
                },
            )
        self._insert_exact(
            connection,
            "estimator_evidence_access_audits",
            {"submission_id": sid},
            {
                "submission_id": sid,
                "audit_id": audit.audit_id,
                "audit_fingerprint": audit.fingerprint,
                "campaign_id": campaign_id,
                "manifest_id": access_manifest.manifest_id,
                "holdout_unsealed_at_us": _to_epoch_us(audit.holdout_unsealed_at),
                "completed_at_us": _to_epoch_us(audit.completed_at),
                "holdout_count": len(audit.holdout_case_ids),
            },
        )

        scan = submission.privacy_scan
        privacy_manifest = scan.manifest
        for set_kind, artifacts in (
            ("expected", privacy_manifest.expected_artifact_fingerprints),
            ("scanned", privacy_manifest.scanned_artifact_fingerprints),
        ):
            for ordinal, artifact_fingerprint in enumerate(artifacts):
                self._insert_exact(
                    connection,
                    "estimator_evidence_privacy_artifacts",
                    {
                        "submission_id": sid,
                        "set_kind": set_kind,
                        "ordinal": ordinal,
                    },
                    {
                        "submission_id": sid,
                        "manifest_id": privacy_manifest.manifest_id,
                        "set_kind": set_kind,
                        "ordinal": ordinal,
                        "artifact_fingerprint": artifact_fingerprint,
                        "campaign_id": campaign_id,
                    },
                )
        for ordinal, finding in enumerate(privacy_manifest.findings):
            self._insert_exact(
                connection,
                "estimator_evidence_privacy_findings",
                {
                    "submission_id": sid,
                    "manifest_id": privacy_manifest.manifest_id,
                    "ordinal": ordinal,
                },
                {
                    "submission_id": sid,
                    "manifest_id": privacy_manifest.manifest_id,
                    "ordinal": ordinal,
                    "finding_id": finding.finding_id,
                    "finding_fingerprint": finding.fingerprint,
                    "campaign_id": campaign_id,
                    "artifact_fingerprint": finding.artifact_fingerprint,
                    "detector_key": finding.detector_key,
                    "detector_version": finding.detector_version,
                    "category": finding.category.value,
                    "occurrence_count": finding.occurrence_count,
                    "detected_at_us": _to_epoch_us(finding.detected_at),
                },
            )
        self._insert_exact(
            connection,
            "estimator_evidence_privacy_manifests",
            {"submission_id": sid},
            {
                "submission_id": sid,
                "manifest_id": privacy_manifest.manifest_id,
                "manifest_fingerprint": privacy_manifest.fingerprint,
                "finding_set_fingerprint": privacy_manifest.finding_set_fingerprint,
                "campaign_id": campaign_id,
                "frozen_at_us": _to_epoch_us(privacy_manifest.frozen_at),
                "expected_count": len(
                    privacy_manifest.expected_artifact_fingerprints
                ),
                "scanned_count": len(
                    privacy_manifest.scanned_artifact_fingerprints
                ),
                "finding_row_count": len(privacy_manifest.findings),
                "finding_occurrence_count": privacy_manifest.finding_count,
            },
        )
        self._insert_exact(
            connection,
            "estimator_evidence_privacy_scans",
            {"submission_id": sid},
            {
                "submission_id": sid,
                "scan_id": scan.scan_id,
                "scan_fingerprint": scan.fingerprint,
                "campaign_id": campaign_id,
                "manifest_id": privacy_manifest.manifest_id,
                "scanner_version": scan.scanner_version,
                "started_at_us": _to_epoch_us(scan.started_at),
                "completed_at_us": _to_epoch_us(scan.completed_at),
            },
        )

        for estimate in submission.structured_estimate_receipts:
            self._insert_exact(
                connection,
                "estimator_evidence_structured_estimates",
                {"submission_id": sid, "receipt_id": estimate.receipt_id},
                {
                    "submission_id": sid,
                    "receipt_id": estimate.receipt_id,
                    "receipt_fingerprint": estimate.fingerprint,
                    "campaign_id": campaign_id,
                    "case_id": estimate.case_id,
                    "plan_fingerprint": estimate.plan_fingerprint,
                    "metric_question_fingerprint": estimate.metric_question_fingerprint,
                    "evidence_packet_fingerprint": estimate.evidence_packet_fingerprint,
                    "attempt_id": estimate.attempt_id,
                    "outcome_id": estimate.outcome_id,
                    "outcome_fingerprint": estimate.outcome_fingerprint,
                    "structured_output_fingerprint": estimate.structured_output_fingerprint,
                    "value_kind": estimate.value_kind.value,
                    "value_state": estimate.state.value,
                    "numeric_value": estimate.numeric_value,
                    "label_code": estimate.label_code,
                    "confidence": estimate.confidence,
                    "reason_code": estimate.reason_code,
                    "recorded_at_us": _to_epoch_us(estimate.recorded_at),
                },
            )

        self._append_projection_rows(connection, submission)

        for judgment in submission.blind_human_judgments:
            values = {
                "submission_id": sid,
                "judgment_id": judgment.judgment_id,
                "judgment_fingerprint": judgment.fingerprint,
                "campaign_id": campaign_id,
                "case_id": judgment.case_id,
                "plan_fingerprint": judgment.plan_fingerprint,
                "metric_question_fingerprint": judgment.metric_question_fingerprint,
                "evidence_packet_fingerprint": judgment.evidence_packet_fingerprint,
                "participant_id": judgment.participant_id,
                "participant_kind": judgment.participant_kind.value,
                "annotation_protocol_version": judgment.annotation_protocol_version,
                **_projection_columns(judgment),
                "created_at_us": _to_epoch_us(judgment.created_at),
            }
            self._insert_exact(
                connection,
                "estimator_evidence_blind_judgments",
                {"submission_id": sid, "judgment_id": judgment.judgment_id},
                values,
            )
        for adjudication in submission.blind_human_adjudications:
            for ordinal, judgment_id in enumerate(adjudication.judgment_ids):
                self._insert_exact(
                    connection,
                    "estimator_evidence_adjudication_judgments",
                    {
                        "submission_id": sid,
                        "adjudication_id": adjudication.adjudication_id,
                        "ordinal": ordinal,
                    },
                    {
                        "submission_id": sid,
                        "adjudication_id": adjudication.adjudication_id,
                        "ordinal": ordinal,
                        "judgment_id": judgment_id,
                        "campaign_id": campaign_id,
                    },
                )
            values = {
                "submission_id": sid,
                "adjudication_id": adjudication.adjudication_id,
                "adjudication_fingerprint": adjudication.fingerprint,
                "campaign_id": campaign_id,
                "case_id": adjudication.case_id,
                "plan_fingerprint": adjudication.plan_fingerprint,
                "metric_question_fingerprint": adjudication.metric_question_fingerprint,
                "evidence_packet_fingerprint": adjudication.evidence_packet_fingerprint,
                "resolver_id": adjudication.adjudicator_id,
                "resolution": adjudication.resolution.value,
                "annotation_protocol_version": adjudication.annotation_protocol_version,
                **_projection_columns(adjudication),
                "completed_at_us": _to_epoch_us(adjudication.completed_at),
                "judgment_count": len(adjudication.judgment_ids),
            }
            self._insert_exact(
                connection,
                "estimator_evidence_blind_adjudications",
                {
                    "submission_id": sid,
                    "adjudication_id": adjudication.adjudication_id,
                },
                values,
            )

        for series in submission.stability_series:
            for trial in series.trials:
                self._insert_exact(
                    connection,
                    "estimator_evidence_stability_trials",
                    {
                        "submission_id": sid,
                        "series_id": series.series_id,
                        "trial_ordinal": trial.trial_ordinal,
                    },
                    {
                        "submission_id": sid,
                        "series_id": series.series_id,
                        "trial_ordinal": trial.trial_ordinal,
                        "receipt_id": trial.receipt_id,
                        "receipt_fingerprint": trial.fingerprint,
                        "campaign_id": campaign_id,
                        "case_id": trial.case_id,
                        "plan_fingerprint": trial.plan_fingerprint,
                        "metric_question_fingerprint": trial.metric_question_fingerprint,
                        "evidence_packet_fingerprint": trial.evidence_packet_fingerprint,
                        "condition_code": trial.condition.value,
                        "attempt_id": trial.attempt_id,
                        "outcome_id": trial.outcome_id,
                        "outcome_fingerprint": trial.outcome_fingerprint,
                        "estimate_receipt_id": trial.estimate_receipt_id,
                        "estimate_receipt_fingerprint": trial.estimate_receipt_fingerprint,
                        "recorded_at_us": _to_epoch_us(trial.recorded_at),
                    },
                )
            self._insert_exact(
                connection,
                "estimator_evidence_stability_series",
                {"submission_id": sid, "series_id": series.series_id},
                {
                    "submission_id": sid,
                    "series_id": series.series_id,
                    "series_fingerprint": series.fingerprint,
                    "trial_set_fingerprint": series.trial_set_fingerprint,
                    "campaign_id": campaign_id,
                    "case_id": series.case_id,
                    "plan_fingerprint": series.plan_fingerprint,
                    "metric_question_fingerprint": series.metric_question_fingerprint,
                    "evidence_packet_fingerprint": series.evidence_packet_fingerprint,
                    "condition_code": series.condition.value,
                    "frozen_at_us": _to_epoch_us(series.frozen_at),
                    "trial_count": len(series.trials),
                },
            )

        for ordinal, case_id in enumerate(submission.campaign_holdout_case_ids):
            self._insert_exact(
                connection,
                "estimator_evidence_submission_holdout_cases",
                {"submission_id": sid, "ordinal": ordinal},
                {
                    "submission_id": sid,
                    "ordinal": ordinal,
                    "case_id": case_id,
                    "campaign_id": campaign_id,
                },
            )

    def _append_projection_rows(
        self, connection, submission: CalibrationEvidenceSubmissionV1
    ) -> None:
        sid = submission.submission_id
        campaign_id = submission.campaign_id
        for projection in submission.candidate_projections:
            self._insert_exact(
                connection,
                "estimator_evidence_candidate_projections",
                {"submission_id": sid, "projection_id": projection.projection_id},
                {
                    "submission_id": sid,
                    "projection_id": projection.projection_id,
                    "projection_fingerprint": projection.fingerprint,
                    "campaign_id": campaign_id,
                    "case_id": projection.case_id,
                    "plan_fingerprint": projection.plan_fingerprint,
                    "metric_question_fingerprint": projection.metric_question_fingerprint,
                    "evidence_packet_fingerprint": projection.evidence_packet_fingerprint,
                    "attempt_id": projection.attempt_id,
                    "outcome_id": projection.outcome_id,
                    "outcome_fingerprint": projection.outcome_fingerprint,
                    "estimate_receipt_id": projection.estimate_receipt_id,
                    "estimate_receipt_fingerprint": projection.estimate_receipt_fingerprint,
                    "stage_ordinal": projection.stage_ordinal,
                    "stage_kind": projection.stage_kind.value,
                    "selected_at_us": _to_epoch_us(projection.selected_at),
                },
            )
        for projection in submission.deterministic_baseline_projections:
            values = {
                "submission_id": sid,
                "projection_id": projection.projection_id,
                "projection_fingerprint": projection.fingerprint,
                "campaign_id": campaign_id,
                "case_id": projection.case_id,
                "plan_fingerprint": projection.plan_fingerprint,
                "metric_question_fingerprint": projection.metric_question_fingerprint,
                "evidence_packet_fingerprint": projection.evidence_packet_fingerprint,
                "baseline_id": projection.baseline_id,
                "baseline_version": projection.baseline_version,
                "baseline_configuration_sha256": projection.baseline_configuration_sha256,
                "final_estimate_fingerprint": projection.final_estimate_fingerprint,
                **_projection_columns(projection),
                "evaluated_at_us": _to_epoch_us(projection.evaluated_at),
            }
            self._insert_exact(
                connection,
                "estimator_evidence_baseline_projections",
                {"submission_id": sid, "projection_id": projection.projection_id},
                values,
            )
        for projection in submission.objective_truth_projections:
            values = {
                "submission_id": sid,
                "projection_id": projection.projection_id,
                "projection_fingerprint": projection.fingerprint,
                "campaign_id": campaign_id,
                "case_id": projection.case_id,
                "plan_fingerprint": projection.plan_fingerprint,
                "metric_question_fingerprint": projection.metric_question_fingerprint,
                "evidence_packet_fingerprint": projection.evidence_packet_fingerprint,
                "truth_kind": projection.truth_kind.value,
                "objective_evidence_fingerprint": projection.objective_evidence_fingerprint,
                "verification_adapter_version": projection.verification_adapter_version,
                **_projection_columns(projection),
                "observed_at_us": _to_epoch_us(projection.observed_at),
            }
            self._insert_exact(
                connection,
                "estimator_evidence_objective_projections",
                {"submission_id": sid, "projection_id": projection.projection_id},
                values,
            )

    def _insert_evidence_submission_root(
        self, connection, submission: CalibrationEvidenceSubmissionV1
    ) -> None:
        self._insert_exact(
            connection,
            "estimator_evidence_submissions",
            {"submission_id": submission.submission_id},
            {
                "submission_id": submission.submission_id,
                "submission_fingerprint": submission.fingerprint,
                "campaign_id": submission.campaign_id,
                "expected_manifest_id": submission.expected_attempt_manifest.manifest_id,
                "access_audit_id": submission.holdout_access_audit.audit_id,
                "privacy_scan_id": submission.privacy_scan.scan_id,
                "submitted_at_us": _to_epoch_us(submission.submitted_at),
                "holdout_count": len(submission.campaign_holdout_case_ids),
                "launch_count": len(submission.attempt_launches),
                "outcome_count": len(submission.attempt_outcomes),
                "structured_estimate_count": len(
                    submission.structured_estimate_receipts
                ),
                "candidate_projection_count": len(submission.candidate_projections),
                "baseline_projection_count": len(
                    submission.deterministic_baseline_projections
                ),
                "objective_projection_count": len(
                    submission.objective_truth_projections
                ),
                "judgment_count": len(submission.blind_human_judgments),
                "adjudication_count": len(submission.blind_human_adjudications),
                "stability_series_count": len(submission.stability_series),
                "activation_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )

    @staticmethod
    def _assert_stored_fingerprint(
        actual: str, stored: str, label: str
    ) -> None:
        if actual != stored:
            raise DatabaseInvariantError(f"{label} fingerprint is not reproducible")

    @staticmethod
    def _assert_stored_count(actual: int, stored: int, label: str) -> None:
        if actual != stored:
            raise DatabaseInvariantError(f"{label} count is not reproducible")

    def _hydrate_calibration_evidence_submission(
        self, connection, submission_id: str
    ) -> CalibrationEvidenceSubmissionV1:
        root = connection.execute(
            "SELECT * FROM estimator_evidence_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        if root is None:
            raise DatabaseInvariantError("calibration evidence submission is missing")

        launch_rows = connection.execute(
            "SELECT * FROM estimator_evidence_attempt_launches WHERE submission_id = ? ORDER BY attempt_id",
            (submission_id,),
        ).fetchall()
        launches = tuple(self._hydrate_evidence_launch(row) for row in launch_rows)
        for value, row in zip(launches, launch_rows, strict=True):
            self._assert_stored_fingerprint(
                value.fingerprint, row["launch_fingerprint"], "attempt launch"
            )

        outcome_rows = connection.execute(
            "SELECT * FROM estimator_evidence_attempt_outcomes WHERE submission_id = ? ORDER BY attempt_id",
            (submission_id,),
        ).fetchall()
        outcomes = tuple(self._hydrate_evidence_outcome(row) for row in outcome_rows)
        for value, row in zip(outcomes, outcome_rows, strict=True):
            self._assert_stored_fingerprint(
                value.fingerprint, row["outcome_fingerprint"], "attempt outcome"
            )

        expected_root = connection.execute(
            "SELECT * FROM estimator_evidence_expected_manifests WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        expected_rows = connection.execute(
            "SELECT * FROM estimator_evidence_expected_attempts WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        ).fetchall()
        expected_manifest = ExpectedAttemptManifestV2(
            manifest_id=expected_root["manifest_id"],
            campaign_id=expected_root["campaign_id"],
            attempts=tuple(
                ExpectedAttemptV2(
                    attempt_id=row["attempt_id"],
                    execution_id=row["execution_id"],
                    case_id=row["case_id"],
                    plan_fingerprint=row["plan_fingerprint"],
                    metric_question_fingerprint=row[
                        "metric_question_fingerprint"
                    ],
                    evidence_packet_fingerprint=row[
                        "evidence_packet_fingerprint"
                    ],
                    constellation_stage_fingerprint=row[
                        "constellation_stage_fingerprint"
                    ],
                    stage_configuration_sha256=row[
                        "stage_configuration_sha256"
                    ],
                    stage_ordinal=row["stage_ordinal"],
                    stage_kind=row["stage_kind"],
                )
                for row in expected_rows
            ),
            frozen_at=_from_epoch_us(expected_root["frozen_at_us"]),
        )
        for expected, row in zip(
            expected_manifest.attempts, expected_rows, strict=True
        ):
            self._assert_stored_fingerprint(
                _contract_fingerprint(expected),
                row["attempt_fingerprint"],
                "expected attempt",
            )
        self._assert_stored_count(
            len(expected_manifest.attempts),
            expected_root["attempt_count"],
            "expected attempt manifest",
        )
        self._assert_stored_fingerprint(
            expected_manifest.fingerprint,
            expected_root["manifest_fingerprint"],
            "expected attempt manifest",
        )
        self._assert_stored_fingerprint(
            expected_manifest.execution_set_fingerprint,
            expected_root["execution_set_fingerprint"],
            "expected execution set",
        )

        audit = self._hydrate_evidence_access_audit(connection, submission_id)
        scan = self._hydrate_evidence_privacy_scan(connection, submission_id)

        estimate_rows = connection.execute(
            "SELECT * FROM estimator_evidence_structured_estimates WHERE submission_id = ? ORDER BY recorded_at_us, receipt_id",
            (submission_id,),
        ).fetchall()
        estimates = tuple(
            StructuredEstimateReceiptV1(
                receipt_id=row["receipt_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                attempt_id=row["attempt_id"],
                outcome_id=row["outcome_id"],
                outcome_fingerprint=row["outcome_fingerprint"],
                structured_output_fingerprint=row[
                    "structured_output_fingerprint"
                ],
                value_kind=row["value_kind"],
                state=row["value_state"],
                numeric_value=row["numeric_value"],
                label_code=row["label_code"],
                confidence=row["confidence"],
                reason_code=row["reason_code"],
                recorded_at=_from_epoch_us(row["recorded_at_us"]),
            )
            for row in estimate_rows
        )
        for value, row in zip(estimates, estimate_rows, strict=True):
            self._assert_stored_fingerprint(
                value.fingerprint, row["receipt_fingerprint"], "structured estimate"
            )

        candidate_rows = connection.execute(
            "SELECT * FROM estimator_evidence_candidate_projections WHERE submission_id = ? ORDER BY case_id, metric_question_fingerprint",
            (submission_id,),
        ).fetchall()
        candidates = tuple(
            AuthoritativeCandidateProjectionV2(
                projection_id=row["projection_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                attempt_id=row["attempt_id"],
                outcome_id=row["outcome_id"],
                outcome_fingerprint=row["outcome_fingerprint"],
                estimate_receipt_id=row["estimate_receipt_id"],
                estimate_receipt_fingerprint=row[
                    "estimate_receipt_fingerprint"
                ],
                stage_ordinal=row["stage_ordinal"],
                stage_kind=row["stage_kind"],
                selected_at=_from_epoch_us(row["selected_at_us"]),
            )
            for row in candidate_rows
        )
        baseline_rows = connection.execute(
            "SELECT * FROM estimator_evidence_baseline_projections WHERE submission_id = ? ORDER BY case_id, metric_question_fingerprint",
            (submission_id,),
        ).fetchall()
        baselines = tuple(
            AuthoritativeDeterministicBaselineProjectionV1(
                projection_id=row["projection_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                baseline_id=row["baseline_id"],
                baseline_version=row["baseline_version"],
                baseline_configuration_sha256=row[
                    "baseline_configuration_sha256"
                ],
                final_estimate_fingerprint=row["final_estimate_fingerprint"],
                value_kind=row["value_kind"],
                state=row["value_state"],
                numeric_value=row["numeric_value"],
                label_code=row["label_code"],
                reason_code=row["reason_code"],
                evaluated_at=_from_epoch_us(row["evaluated_at_us"]),
            )
            for row in baseline_rows
        )
        objective_rows = connection.execute(
            "SELECT * FROM estimator_evidence_objective_projections WHERE submission_id = ? ORDER BY case_id, metric_question_fingerprint",
            (submission_id,),
        ).fetchall()
        objectives = tuple(
            ObjectiveTruthProjectionV1(
                projection_id=row["projection_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                truth_kind=row["truth_kind"],
                objective_evidence_fingerprint=row[
                    "objective_evidence_fingerprint"
                ],
                verification_adapter_version=row[
                    "verification_adapter_version"
                ],
                value_kind=row["value_kind"],
                state=row["value_state"],
                numeric_value=row["numeric_value"],
                label_code=row["label_code"],
                reason_code=row["reason_code"],
                observed_at=_from_epoch_us(row["observed_at_us"]),
            )
            for row in objective_rows
        )
        for values, rows, label in (
            (candidates, candidate_rows, "candidate projection"),
            (baselines, baseline_rows, "baseline projection"),
            (objectives, objective_rows, "objective projection"),
        ):
            for value, row in zip(values, rows, strict=True):
                self._assert_stored_fingerprint(
                    value.fingerprint, row["projection_fingerprint"], label
                )

        judgment_rows = connection.execute(
            "SELECT * FROM estimator_evidence_blind_judgments WHERE submission_id = ? ORDER BY created_at_us, judgment_id",
            (submission_id,),
        ).fetchall()
        judgments = tuple(
            BlindHumanJudgmentInputV1(
                judgment_id=row["judgment_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                participant_id=row["participant_id"],
                participant_kind=row["participant_kind"],
                annotation_protocol_version=row[
                    "annotation_protocol_version"
                ],
                value_kind=row["value_kind"],
                state=row["value_state"],
                numeric_value=row["numeric_value"],
                label_code=row["label_code"],
                reason_code=row["reason_code"],
                created_at=_from_epoch_us(row["created_at_us"]),
            )
            for row in judgment_rows
        )
        for value, row in zip(judgments, judgment_rows, strict=True):
            self._assert_stored_fingerprint(
                value.fingerprint, row["judgment_fingerprint"], "blind judgment"
            )

        adjudication_rows = connection.execute(
            "SELECT * FROM estimator_evidence_blind_adjudications WHERE submission_id = ? ORDER BY case_id, metric_question_fingerprint",
            (submission_id,),
        ).fetchall()
        adjudications = []
        for row in adjudication_rows:
            links = connection.execute(
                "SELECT judgment_id FROM estimator_evidence_adjudication_judgments WHERE submission_id = ? AND adjudication_id = ? ORDER BY ordinal",
                (submission_id, row["adjudication_id"]),
            ).fetchall()
            value = BlindHumanAdjudicationInputV1(
                adjudication_id=row["adjudication_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                adjudicator_id=row["resolver_id"],
                adjudicator_kind=HumanParticipantKind.ADJUDICATOR,
                resolution=row["resolution"],
                judgment_ids=tuple(item["judgment_id"] for item in links),
                annotation_protocol_version=row[
                    "annotation_protocol_version"
                ],
                value_kind=row["value_kind"],
                state=row["value_state"],
                numeric_value=row["numeric_value"],
                label_code=row["label_code"],
                reason_code=row["reason_code"],
                completed_at=_from_epoch_us(row["completed_at_us"]),
            )
            self._assert_stored_fingerprint(
                value.fingerprint,
                row["adjudication_fingerprint"],
                "blind adjudication",
            )
            self._assert_stored_count(
                len(value.judgment_ids),
                row["judgment_count"],
                "blind adjudication judgment",
            )
            adjudications.append(value)

        series_rows = connection.execute(
            "SELECT * FROM estimator_evidence_stability_series WHERE submission_id = ? ORDER BY case_id, condition_code, series_id",
            (submission_id,),
        ).fetchall()
        stability_series = []
        for row in series_rows:
            trial_rows = connection.execute(
                "SELECT * FROM estimator_evidence_stability_trials WHERE submission_id = ? AND series_id = ? ORDER BY trial_ordinal",
                (submission_id, row["series_id"]),
            ).fetchall()
            trials = tuple(
                StabilityTrialReceiptV1(
                    receipt_id=item["receipt_id"],
                    campaign_id=item["campaign_id"],
                    case_id=item["case_id"],
                    plan_fingerprint=item["plan_fingerprint"],
                    metric_question_fingerprint=item[
                        "metric_question_fingerprint"
                    ],
                    evidence_packet_fingerprint=item[
                        "evidence_packet_fingerprint"
                    ],
                    condition=item["condition_code"],
                    trial_ordinal=item["trial_ordinal"],
                    attempt_id=item["attempt_id"],
                    outcome_id=item["outcome_id"],
                    outcome_fingerprint=item["outcome_fingerprint"],
                    estimate_receipt_id=item["estimate_receipt_id"],
                    estimate_receipt_fingerprint=item[
                        "estimate_receipt_fingerprint"
                    ],
                    recorded_at=_from_epoch_us(item["recorded_at_us"]),
                )
                for item in trial_rows
            )
            for trial, trial_row in zip(trials, trial_rows, strict=True):
                self._assert_stored_fingerprint(
                    trial.fingerprint,
                    trial_row["receipt_fingerprint"],
                    "stability trial",
                )
            series = StabilitySeriesManifestV1(
                series_id=row["series_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                plan_fingerprint=row["plan_fingerprint"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                condition=row["condition_code"],
                trials=trials,
                frozen_at=_from_epoch_us(row["frozen_at_us"]),
            )
            self._assert_stored_fingerprint(
                series.fingerprint, row["series_fingerprint"], "stability series"
            )
            self._assert_stored_fingerprint(
                series.trial_set_fingerprint,
                row["trial_set_fingerprint"],
                "stability trial set",
            )
            self._assert_stored_count(
                len(series.trials), row["trial_count"], "stability trial"
            )
            stability_series.append(series)

        holdout_rows = connection.execute(
            "SELECT case_id FROM estimator_evidence_submission_holdout_cases WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        ).fetchall()
        submission = CalibrationEvidenceSubmissionV1(
            submission_id=root["submission_id"],
            campaign_id=root["campaign_id"],
            campaign_holdout_case_ids=tuple(row["case_id"] for row in holdout_rows),
            expected_attempt_manifest=expected_manifest,
            attempt_launches=launches,
            attempt_outcomes=outcomes,
            structured_estimate_receipts=estimates,
            holdout_access_audit=audit,
            privacy_scan=scan,
            candidate_projections=candidates,
            deterministic_baseline_projections=baselines,
            objective_truth_projections=objectives,
            blind_human_judgments=judgments,
            blind_human_adjudications=tuple(adjudications),
            stability_series=tuple(stability_series),
            submitted_at=_from_epoch_us(root["submitted_at_us"]),
            activation_allowed=bool(root["activation_allowed"]),
            private_export_allowed=bool(root["private_export_allowed"]),
            team_share_allowed=bool(root["team_share_allowed"]),
        )
        for actual, column, label in (
            (len(submission.campaign_holdout_case_ids), "holdout_count", "submission holdout"),
            (len(submission.attempt_launches), "launch_count", "submission launch"),
            (len(submission.attempt_outcomes), "outcome_count", "submission outcome"),
            (
                len(submission.structured_estimate_receipts),
                "structured_estimate_count",
                "submission structured estimate",
            ),
            (
                len(submission.candidate_projections),
                "candidate_projection_count",
                "submission candidate projection",
            ),
            (
                len(submission.deterministic_baseline_projections),
                "baseline_projection_count",
                "submission baseline projection",
            ),
            (
                len(submission.objective_truth_projections),
                "objective_projection_count",
                "submission objective projection",
            ),
            (
                len(submission.blind_human_judgments),
                "judgment_count",
                "submission blind judgment",
            ),
            (
                len(submission.blind_human_adjudications),
                "adjudication_count",
                "submission blind adjudication",
            ),
            (
                len(submission.stability_series),
                "stability_series_count",
                "submission stability series",
            ),
        ):
            self._assert_stored_count(actual, root[column], label)
        self._assert_stored_fingerprint(
            submission.fingerprint,
            root["submission_fingerprint"],
            "calibration evidence submission",
        )
        campaign = self._hydrate_preregistered_campaign(
            connection, submission.campaign_id
        )
        self._validate_evidence_campaign_static_lineage(campaign, submission)
        return submission

    @staticmethod
    def _hydrate_evidence_launch(row) -> AttemptLaunchReceiptV1:
        return AttemptLaunchReceiptV1(
            launch_id=row["launch_id"],
            campaign_id=row["campaign_id"],
            attempt_id=row["attempt_id"],
            execution_id=row["execution_id"],
            case_id=row["case_id"],
            plan_fingerprint=row["plan_fingerprint"],
            metric_question_fingerprint=row["metric_question_fingerprint"],
            evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
            constellation_stage_fingerprint=row[
                "constellation_stage_fingerprint"
            ],
            stage_ordinal=row["stage_ordinal"],
            stage_kind=row["stage_kind"],
            stage_configuration_sha256=row["stage_configuration_sha256"],
            model_artifact_fingerprint=row["model_artifact_fingerprint"],
            requested_source=row["requested_source"],
            requested_model_id=row["requested_model_id"],
            requested_revision=row["requested_revision"],
            requested_execution_mode=row["requested_execution_mode"],
            runner_adapter_key=row["runner_adapter_key"],
            runner_adapter_version=row["runner_adapter_version"],
            runner_configuration_sha256=row["runner_configuration_sha256"],
            response_schema_version=row["response_schema_version"],
            destination=row["destination"],
            retention_class=row["retention_class"],
            approval_kind=row["approval_kind"],
            approval_id=row["approval_id"],
            redaction_preview_fingerprint=row["redaction_preview_fingerprint"],
            approved_at=(
                None
                if row["approved_at_us"] is None
                else _from_epoch_us(row["approved_at_us"])
            ),
            launched_at=_from_epoch_us(row["launched_at_us"]),
        )

    @staticmethod
    def _hydrate_evidence_outcome(row) -> AttemptTerminalOutcomeV1:
        return AttemptTerminalOutcomeV1(
            outcome_id=row["outcome_id"],
            campaign_id=row["campaign_id"],
            attempt_id=row["attempt_id"],
            execution_id=row["execution_id"],
            case_id=row["case_id"],
            plan_fingerprint=row["plan_fingerprint"],
            metric_question_fingerprint=row["metric_question_fingerprint"],
            evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
            state=row["terminal_state"],
            served_identity=ServedIdentityV1(
                state=row["served_state"],
                served_source=row["served_source"],
                served_model_id=row["served_model_id"],
                served_revision=row["served_revision"],
                served_execution_mode=row["served_execution_mode"],
                fallback_used=(
                    None
                    if row["fallback_used"] is None
                    else bool(row["fallback_used"])
                ),
                fallback_reason_code=row["fallback_reason_code"],
                unavailable_reason_code=row["served_unavailable_reason_code"],
            ),
            structured_output_fingerprint=row["structured_output_fingerprint"],
            reason_code=row["terminal_reason_code"],
            usage=TokenUsageProvenanceV1(
                state=row["token_state"],
                collector_version=row["token_collector_version"],
                input_tokens=row["input_tokens"],
                cached_input_tokens=row["cached_input_tokens"],
                output_tokens=row["output_tokens"],
                reasoning_output_tokens=row["reasoning_output_tokens"],
                total_tokens=row["total_tokens"],
                reason_code=row["token_reason_code"],
            ),
            resources=ResourceUsageProvenanceV1(
                state=row["resource_state"],
                collector_version=row["resource_collector_version"],
                peak_ram_bytes=row["peak_ram_bytes"],
                peak_vram_bytes=row["peak_vram_bytes"],
                energy_millijoules=row["energy_millijoules"],
                reason_code=row["resource_reason_code"],
            ),
            cost=CostProvenanceV1(
                state=row["cost_state"],
                collector_version=row["cost_collector_version"],
                amount_microusd=row["amount_microusd"],
                reason_code=row["cost_reason_code"],
            ),
            queue=QueueProvenanceV1(
                queue_key=row["queue_key"],
                queue_version=row["queue_version"],
                worker_id=row["worker_id"],
                enqueued_at=_from_epoch_us(row["enqueued_at_us"]),
                dequeued_at=_from_epoch_us(row["dequeued_at_us"]),
                wait_ms=row["wait_ms"],
            ),
            started_at=_from_epoch_us(row["started_at_us"]),
            finished_at=_from_epoch_us(row["finished_at_us"]),
            latency_ms=row["latency_ms"],
        )

    def _hydrate_evidence_access_audit(
        self, connection, submission_id: str
    ) -> HoldoutAccessAuditV1:
        audit_row = connection.execute(
            "SELECT * FROM estimator_evidence_access_audits WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        manifest_row = connection.execute(
            "SELECT * FROM estimator_evidence_access_manifests WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        event_rows = connection.execute(
            "SELECT * FROM estimator_evidence_access_events WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        ).fetchall()
        gap_rows = connection.execute(
            "SELECT * FROM estimator_evidence_access_gaps WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        ).fetchall()
        events = tuple(
            HoldoutAccessEventV1(
                event_id=row["event_id"],
                campaign_id=row["campaign_id"],
                case_id=row["case_id"],
                actor_id=row["actor_id"],
                actor_kind=row["actor_kind"],
                access_kind=row["access_kind"],
                occurred_at=_from_epoch_us(row["occurred_at_us"]),
            )
            for row in event_rows
        )
        for event, row in zip(events, event_rows, strict=True):
            self._assert_stored_fingerprint(
                event.fingerprint, row["event_fingerprint"], "access event"
            )
        gaps = tuple(
            HoldoutAccessGapV1(
                gap_id=row["gap_id"],
                campaign_id=row["campaign_id"],
                reason_code=row["reason_code"],
                started_at=_from_epoch_us(row["started_at_us"]),
                ended_at=_from_epoch_us(row["ended_at_us"]),
            )
            for row in gap_rows
        )
        manifest = HoldoutAccessManifestV1(
            manifest_id=manifest_row["manifest_id"],
            campaign_id=manifest_row["campaign_id"],
            auditor_version=manifest_row["auditor_version"],
            coverage_started_at=_from_epoch_us(
                manifest_row["coverage_started_at_us"]
            ),
            coverage_ended_at=_from_epoch_us(
                manifest_row["coverage_ended_at_us"]
            ),
            events=events,
            gaps=gaps,
            frozen_at=_from_epoch_us(manifest_row["frozen_at_us"]),
        )
        self._assert_stored_count(
            len(manifest.events), manifest_row["event_count"], "access event"
        )
        self._assert_stored_count(
            len(manifest.gaps), manifest_row["gap_count"], "access gap"
        )
        self._assert_stored_fingerprint(
            manifest.fingerprint,
            manifest_row["manifest_fingerprint"],
            "access manifest",
        )
        self._assert_stored_fingerprint(
            manifest.event_set_fingerprint,
            manifest_row["event_set_fingerprint"],
            "access event set",
        )
        self._assert_stored_fingerprint(
            manifest.gap_set_fingerprint,
            manifest_row["gap_set_fingerprint"],
            "access gap set",
        )
        case_rows = connection.execute(
            "SELECT case_id FROM estimator_evidence_access_audit_cases WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        ).fetchall()
        audit = HoldoutAccessAuditV1(
            audit_id=audit_row["audit_id"],
            campaign_id=audit_row["campaign_id"],
            manifest=manifest,
            holdout_case_ids=tuple(row["case_id"] for row in case_rows),
            holdout_unsealed_at=_from_epoch_us(
                audit_row["holdout_unsealed_at_us"]
            ),
            completed_at=_from_epoch_us(audit_row["completed_at_us"]),
        )
        self._assert_stored_count(
            len(audit.holdout_case_ids),
            audit_row["holdout_count"],
            "access audit holdout",
        )
        self._assert_stored_fingerprint(
            audit.fingerprint, audit_row["audit_fingerprint"], "access audit"
        )
        return audit

    def _hydrate_evidence_privacy_scan(
        self, connection, submission_id: str
    ) -> PrivacyScanReceiptV1:
        scan_row = connection.execute(
            "SELECT * FROM estimator_evidence_privacy_scans WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        manifest_row = connection.execute(
            "SELECT * FROM estimator_evidence_privacy_manifests WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        artifacts = connection.execute(
            "SELECT set_kind, artifact_fingerprint FROM estimator_evidence_privacy_artifacts WHERE submission_id = ? ORDER BY set_kind, ordinal",
            (submission_id,),
        ).fetchall()
        finding_rows = connection.execute(
            "SELECT * FROM estimator_evidence_privacy_findings WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        ).fetchall()
        findings = tuple(
            PrivacyFindingV1(
                finding_id=row["finding_id"],
                campaign_id=row["campaign_id"],
                artifact_fingerprint=row["artifact_fingerprint"],
                detector_key=row["detector_key"],
                detector_version=row["detector_version"],
                category=row["category"],
                occurrence_count=row["occurrence_count"],
                detected_at=_from_epoch_us(row["detected_at_us"]),
            )
            for row in finding_rows
        )
        for finding, row in zip(findings, finding_rows, strict=True):
            self._assert_stored_fingerprint(
                finding.fingerprint,
                row["finding_fingerprint"],
                "privacy finding",
            )
        manifest = PrivacyScanManifestV1(
            manifest_id=manifest_row["manifest_id"],
            campaign_id=manifest_row["campaign_id"],
            expected_artifact_fingerprints=tuple(
                row["artifact_fingerprint"]
                for row in artifacts
                if row["set_kind"] == "expected"
            ),
            scanned_artifact_fingerprints=tuple(
                row["artifact_fingerprint"]
                for row in artifacts
                if row["set_kind"] == "scanned"
            ),
            findings=findings,
            frozen_at=_from_epoch_us(manifest_row["frozen_at_us"]),
        )
        self._assert_stored_count(
            len(manifest.expected_artifact_fingerprints),
            manifest_row["expected_count"],
            "privacy expected artifact",
        )
        self._assert_stored_count(
            len(manifest.scanned_artifact_fingerprints),
            manifest_row["scanned_count"],
            "privacy scanned artifact",
        )
        self._assert_stored_count(
            len(manifest.findings),
            manifest_row["finding_row_count"],
            "privacy finding row",
        )
        self._assert_stored_count(
            manifest.finding_count,
            manifest_row["finding_occurrence_count"],
            "privacy finding occurrence",
        )
        self._assert_stored_fingerprint(
            manifest.fingerprint,
            manifest_row["manifest_fingerprint"],
            "privacy manifest",
        )
        self._assert_stored_fingerprint(
            manifest.finding_set_fingerprint,
            manifest_row["finding_set_fingerprint"],
            "privacy finding set",
        )
        scan = PrivacyScanReceiptV1(
            scan_id=scan_row["scan_id"],
            campaign_id=scan_row["campaign_id"],
            scanner_version=scan_row["scanner_version"],
            manifest=manifest,
            started_at=_from_epoch_us(scan_row["started_at_us"]),
            completed_at=_from_epoch_us(scan_row["completed_at_us"]),
        )
        self._assert_stored_fingerprint(
            scan.fingerprint, scan_row["scan_fingerprint"], "privacy scan"
        )
        return scan

    def _insert_gate_policy(self, connection, policy: GatePolicy) -> None:
        fingerprint = policy.fingerprint
        existing = connection.execute(
            "SELECT 1 FROM estimator_gate_policies WHERE policy_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            if self._hydrate_gate_policy(connection, fingerprint) != policy:
                self._conflict("estimator gate policy fingerprint conflicts with storage")
            return
        connection.executemany(
            "INSERT INTO estimator_gate_policy_strata(policy_fingerprint, ordinal, task_stratum) VALUES (?, ?, ?)",
            ((fingerprint, index, item.value) for index, item in enumerate(policy.required_strata)),
        )
        connection.executemany(
            "INSERT INTO estimator_gate_policy_languages(policy_fingerprint, ordinal, language) VALUES (?, ?, ?)",
            ((fingerprint, index, item.value) for index, item in enumerate(policy.required_languages)),
        )
        connection.executemany(
            "INSERT INTO estimator_gate_policy_subgroups(policy_fingerprint, ordinal, dimension) VALUES (?, ?, ?)",
            ((fingerprint, index, item.value) for index, item in enumerate(policy.subgroup_dimensions)),
        )
        connection.executemany(
            """
            INSERT INTO estimator_gate_policy_high_risk_rules(
                policy_fingerprint, ordinal, metric_key, minimum_precision,
                minimum_positive_predictions
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    fingerprint,
                    index,
                    item.metric_key,
                    item.minimum_precision,
                    item.minimum_positive_predictions,
                )
                for index, item in enumerate(policy.high_risk_precision_rules)
            ),
        )
        connection.execute(
            """
            INSERT INTO estimator_gate_policies(
                policy_fingerprint, contract_version, policy_id,
                minimum_active_learning_count, maximum_active_learning_count,
                minimum_holdout_count, minimum_holdout_per_metric,
                minimum_holdout_per_stratum, minimum_holdout_per_language,
                minimum_operational_samples_per_latency_class,
                minimum_subgroup_size, minimum_baseline_margin,
                maximum_human_gap, maximum_ece, minimum_repeat_stability,
                minimum_selective_coverage, maximum_selective_risk,
                false_confidence_threshold,
                maximum_false_confident_error_rate,
                maximum_cold_p95_latency_ms, maximum_warm_p95_latency_ms,
                maximum_oom_rate, maximum_error_rate, maximum_refusal_rate,
                maximum_material_subgroup_regression, required_strata_count,
                required_language_count, subgroup_dimension_count,
                high_risk_rule_count
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                fingerprint,
                policy.contract_version,
                policy.policy_id,
                policy.minimum_active_learning_count,
                policy.maximum_active_learning_count,
                policy.minimum_holdout_count,
                policy.minimum_holdout_per_metric,
                policy.minimum_holdout_per_stratum,
                policy.minimum_holdout_per_language,
                policy.minimum_operational_samples_per_latency_class,
                policy.minimum_subgroup_size,
                policy.minimum_baseline_margin,
                policy.maximum_human_gap,
                policy.maximum_ece,
                policy.minimum_repeat_stability,
                policy.minimum_selective_coverage,
                policy.maximum_selective_risk,
                policy.false_confidence_threshold,
                policy.maximum_false_confident_error_rate,
                policy.maximum_cold_p95_latency_ms,
                policy.maximum_warm_p95_latency_ms,
                policy.maximum_oom_rate,
                policy.maximum_error_rate,
                policy.maximum_refusal_rate,
                policy.maximum_material_subgroup_regression,
                len(policy.required_strata),
                len(policy.required_languages),
                len(policy.subgroup_dimensions),
                len(policy.high_risk_precision_rules),
            ),
        )

    @staticmethod
    def _insert_case_manifest(connection, manifest: CaseAssignmentManifestV2) -> None:
        fingerprint = manifest.fingerprint
        connection.executemany(
            """
            INSERT INTO estimator_case_assignments_v2(
                manifest_fingerprint, ordinal, contract_version, case_id,
                project_id, session_revision_id, metric_key, provider, origin,
                task_stratum, language, evidence_tier, observed_at,
                plan_fingerprint, metric_question_fingerprint,
                evidence_packet_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    fingerprint,
                    index,
                    item.contract_version,
                    item.case_id,
                    item.project_id,
                    item.session_revision_id,
                    item.metric_key,
                    item.provider.value,
                    item.origin.value,
                    item.task_stratum.value,
                    item.language.value,
                    item.evidence_tier.value,
                    to_iso(item.observed_at),
                    item.plan_fingerprint,
                    item.metric_question_fingerprint,
                    item.evidence_packet_fingerprint,
                )
                for index, item in enumerate(manifest.assignments)
            ),
        )
        connection.execute(
            "INSERT INTO estimator_case_manifests_v2 VALUES (?, ?, ?, ?, ?, ?)",
            (
                fingerprint,
                manifest.contract_version,
                manifest.manifest_id,
                manifest.plan_fingerprint,
                to_iso(manifest.frozen_at),
                len(manifest.assignments),
            ),
        )

    @staticmethod
    def _insert_calibration_split(connection, split: CalibrationSplit) -> None:
        fingerprint = split.fingerprint
        for partition, case_ids in (
            ("development", split.development_case_ids),
            ("active_learning", split.active_learning_case_ids),
            ("holdout", split.holdout_case_ids),
        ):
            connection.executemany(
                "INSERT INTO estimator_calibration_split_cases VALUES (?, ?, ?, ?)",
                (
                    (fingerprint, partition, index, case_id)
                    for index, case_id in enumerate(case_ids)
                ),
            )
        connection.execute(
            "INSERT INTO estimator_calibration_splits VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fingerprint,
                split.contract_version,
                split.split_id,
                split.assignment_manifest_fingerprint,
                to_iso(split.frozen_at),
                len(split.development_case_ids),
                len(split.active_learning_case_ids),
                len(split.holdout_case_ids),
            ),
        )

    @staticmethod
    def _insert_legacy_preregistration(
        connection, preregistration: GatePreregistration
    ) -> None:
        fingerprint = preregistration.fingerprint
        for spec_index, spec in enumerate(preregistration.metric_specs):
            connection.executemany(
                "INSERT INTO estimator_legacy_metric_labels VALUES (?, ?, ?, ?)",
                (
                    (fingerprint, spec.metric_key, index, label)
                    for index, label in enumerate(spec.label_vocabulary)
                ),
            )
            connection.execute(
                "INSERT INTO estimator_legacy_metric_specs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fingerprint,
                    spec_index,
                    spec.metric_key,
                    spec.risk_tier.value,
                    spec.positive_label,
                    len(spec.label_vocabulary),
                ),
            )
        connection.execute(
            "INSERT INTO estimator_legacy_preregistrations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fingerprint,
                preregistration.contract_version,
                preregistration.preregistration_id,
                preregistration.policy_fingerprint,
                preregistration.assignment_manifest_fingerprint,
                preregistration.split_fingerprint,
                preregistration.estimator_identity_fingerprint,
                to_iso(preregistration.registered_at),
                len(preregistration.metric_specs),
            ),
        )

    @staticmethod
    def _insert_constellation(
        connection, constellation: ConstellationIdentityReceipt
    ) -> None:
        fingerprint = constellation.fingerprint
        connection.executemany(
            """
            INSERT INTO estimator_constellation_stages VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                (
                    fingerprint,
                    item.ordinal,
                    item.contract_version,
                    item.kind.value,
                    item.source.value,
                    item.stage_fingerprint,
                    item.model_artifact_fingerprint,
                    item.stage_configuration_sha256,
                    item.component_version,
                    item.output_schema_version,
                )
                for item in constellation.stages
            ),
        )
        connection.execute(
            "INSERT INTO estimator_constellations VALUES (?, ?, ?, ?, ?, ?)",
            (
                fingerprint,
                constellation.contract_version,
                constellation.constellation_id,
                constellation.plan_fingerprint,
                to_iso(constellation.frozen_at),
                len(constellation.stages),
            ),
        )

    @staticmethod
    def _hydrate_gate_policy(connection, fingerprint: str) -> GatePolicy:
        row = connection.execute(
            "SELECT * FROM estimator_gate_policies WHERE policy_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("estimator gate policy is missing")
        strata = connection.execute(
            "SELECT task_stratum FROM estimator_gate_policy_strata WHERE policy_fingerprint = ? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        languages = connection.execute(
            "SELECT language FROM estimator_gate_policy_languages WHERE policy_fingerprint = ? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        subgroups = connection.execute(
            "SELECT dimension FROM estimator_gate_policy_subgroups WHERE policy_fingerprint = ? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        rules = connection.execute(
            "SELECT * FROM estimator_gate_policy_high_risk_rules WHERE policy_fingerprint = ? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        policy = GatePolicy(
            contract_version=row["contract_version"],
            policy_id=row["policy_id"],
            minimum_active_learning_count=row["minimum_active_learning_count"],
            maximum_active_learning_count=row["maximum_active_learning_count"],
            minimum_holdout_count=row["minimum_holdout_count"],
            minimum_holdout_per_metric=row["minimum_holdout_per_metric"],
            minimum_holdout_per_stratum=row["minimum_holdout_per_stratum"],
            minimum_holdout_per_language=row["minimum_holdout_per_language"],
            minimum_operational_samples_per_latency_class=row["minimum_operational_samples_per_latency_class"],
            minimum_subgroup_size=row["minimum_subgroup_size"],
            minimum_baseline_margin=row["minimum_baseline_margin"],
            maximum_human_gap=row["maximum_human_gap"],
            maximum_ece=row["maximum_ece"],
            minimum_repeat_stability=row["minimum_repeat_stability"],
            minimum_selective_coverage=row["minimum_selective_coverage"],
            maximum_selective_risk=row["maximum_selective_risk"],
            false_confidence_threshold=row["false_confidence_threshold"],
            maximum_false_confident_error_rate=row["maximum_false_confident_error_rate"],
            maximum_cold_p95_latency_ms=row["maximum_cold_p95_latency_ms"],
            maximum_warm_p95_latency_ms=row["maximum_warm_p95_latency_ms"],
            maximum_oom_rate=row["maximum_oom_rate"],
            maximum_error_rate=row["maximum_error_rate"],
            maximum_refusal_rate=row["maximum_refusal_rate"],
            maximum_material_subgroup_regression=row["maximum_material_subgroup_regression"],
            required_strata=tuple(CalibrationTaskStratum(item["task_stratum"]) for item in strata),
            required_languages=tuple(CalibrationLanguage(item["language"]) for item in languages),
            subgroup_dimensions=tuple(SubgroupDimension(item["dimension"]) for item in subgroups),
            high_risk_precision_rules=tuple(
                HighRiskPrecisionRule(
                    metric_key=item["metric_key"],
                    minimum_precision=item["minimum_precision"],
                    minimum_positive_predictions=item["minimum_positive_predictions"],
                )
                for item in rules
            ),
        )
        if policy.fingerprint != fingerprint:
            raise DatabaseInvariantError("estimator gate policy fingerprint is not reproducible")
        return policy

    def _hydrate_preregistered_campaign(
        self, connection, campaign_id: str
    ) -> PreregisteredEstimatorCampaign:
        root = connection.execute(
            "SELECT * FROM estimator_gate_campaigns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if root is None:
            raise DatabaseInvariantError("estimator campaign is missing")
        manifest_row = connection.execute(
            "SELECT * FROM estimator_case_manifests_v2 WHERE manifest_fingerprint = ?",
            (root["assignment_manifest_fingerprint"],),
        ).fetchone()
        assignment_rows = connection.execute(
            "SELECT * FROM estimator_case_assignments_v2 WHERE manifest_fingerprint = ? ORDER BY ordinal",
            (root["assignment_manifest_fingerprint"],),
        ).fetchall()
        manifest = CaseAssignmentManifestV2(
            contract_version=manifest_row["contract_version"],
            manifest_id=manifest_row["manifest_id"],
            plan_fingerprint=manifest_row["plan_fingerprint"],
            frozen_at=_required_time(manifest_row["frozen_at"]),
            assignments=tuple(
                CaseAssignmentV2(
                    contract_version=item["contract_version"],
                    case_id=item["case_id"],
                    project_id=item["project_id"],
                    session_revision_id=item["session_revision_id"],
                    metric_key=item["metric_key"],
                    provider=Provider(item["provider"]),
                    origin=item["origin"],
                    task_stratum=item["task_stratum"],
                    language=item["language"],
                    evidence_tier=item["evidence_tier"],
                    observed_at=_required_time(item["observed_at"]),
                    plan_fingerprint=item["plan_fingerprint"],
                    metric_question_fingerprint=item["metric_question_fingerprint"],
                    evidence_packet_fingerprint=item["evidence_packet_fingerprint"],
                )
                for item in assignment_rows
            ),
        )
        split_row = connection.execute(
            "SELECT * FROM estimator_calibration_splits WHERE split_fingerprint = ?",
            (root["split_fingerprint"],),
        ).fetchone()
        split_cases = connection.execute(
            "SELECT partition_code, case_id FROM estimator_calibration_split_cases WHERE split_fingerprint = ? ORDER BY partition_code, ordinal",
            (root["split_fingerprint"],),
        ).fetchall()
        by_partition = {
            key: tuple(item["case_id"] for item in split_cases if item["partition_code"] == key)
            for key in ("development", "active_learning", "holdout")
        }
        split = CalibrationSplit(
            contract_version=split_row["contract_version"],
            split_id=split_row["split_id"],
            assignment_manifest_fingerprint=split_row["assignment_manifest_fingerprint"],
            frozen_at=_required_time(split_row["frozen_at"]),
            development_case_ids=by_partition["development"],
            active_learning_case_ids=by_partition["active_learning"],
            holdout_case_ids=by_partition["holdout"],
        )
        legacy_row = connection.execute(
            "SELECT * FROM estimator_legacy_preregistrations WHERE preregistration_fingerprint = ?",
            (root["legacy_preregistration_fingerprint"],),
        ).fetchone()
        spec_rows = connection.execute(
            "SELECT * FROM estimator_legacy_metric_specs WHERE preregistration_fingerprint = ? ORDER BY ordinal",
            (root["legacy_preregistration_fingerprint"],),
        ).fetchall()
        specs = []
        for item in spec_rows:
            labels = connection.execute(
                "SELECT label_code FROM estimator_legacy_metric_labels WHERE preregistration_fingerprint = ? AND metric_key = ? ORDER BY ordinal",
                (root["legacy_preregistration_fingerprint"], item["metric_key"]),
            ).fetchall()
            specs.append(
                MetricGateSpec(
                    metric_key=item["metric_key"],
                    label_vocabulary=tuple(label["label_code"] for label in labels),
                    risk_tier=MetricRiskTier(item["risk_tier"]),
                    positive_label=item["positive_label"],
                )
            )
        legacy = GatePreregistration(
            contract_version=legacy_row["contract_version"],
            preregistration_id=legacy_row["preregistration_id"],
            policy_fingerprint=legacy_row["policy_fingerprint"],
            assignment_manifest_fingerprint=legacy_row["assignment_manifest_fingerprint"],
            split_fingerprint=legacy_row["split_fingerprint"],
            estimator_identity_fingerprint=legacy_row["estimator_identity_fingerprint"],
            registered_at=_required_time(legacy_row["registered_at"]),
            metric_specs=tuple(specs),
        )
        constellation_row = connection.execute(
            "SELECT * FROM estimator_constellations WHERE constellation_fingerprint = ?",
            (root["constellation_fingerprint"],),
        ).fetchone()
        stage_rows = connection.execute(
            "SELECT * FROM estimator_constellation_stages WHERE constellation_fingerprint = ? ORDER BY ordinal",
            (root["constellation_fingerprint"],),
        ).fetchall()
        constellation = ConstellationIdentityReceipt(
            contract_version=constellation_row["contract_version"],
            constellation_id=constellation_row["constellation_id"],
            plan_fingerprint=constellation_row["plan_fingerprint"],
            frozen_at=_required_time(constellation_row["frozen_at"]),
            stages=tuple(
                ConstellationStageIdentity(
                    contract_version=item["contract_version"],
                    ordinal=item["ordinal"],
                    kind=item["kind"],
                    source=item["source"],
                    stage_fingerprint=item["stage_fingerprint"],
                    model_artifact_fingerprint=item["model_artifact_fingerprint"],
                    stage_configuration_sha256=item["stage_configuration_sha256"],
                    component_version=item["component_version"],
                    output_schema_version=item["output_schema_version"],
                )
                for item in stage_rows
            ),
        )
        preregistration_row = connection.execute(
            "SELECT * FROM estimator_preregistrations_v2 WHERE preregistration_fingerprint = ?",
            (root["preregistration_v2_fingerprint"],),
        ).fetchone()
        preregistration_v2 = GatePreregistrationV2(
            contract_version=preregistration_row["contract_version"],
            preregistration_id=preregistration_row["preregistration_id"],
            policy_fingerprint=preregistration_row["policy_fingerprint"],
            assignment_manifest_fingerprint=preregistration_row["assignment_manifest_fingerprint"],
            split_fingerprint=preregistration_row["split_fingerprint"],
            stored_plan_fingerprint=preregistration_row["stored_plan_fingerprint"],
            constellation_fingerprint=preregistration_row["constellation_fingerprint"],
            legacy_preregistration_fingerprint=preregistration_row["legacy_preregistration_fingerprint"],
            registered_at=_required_time(preregistration_row["registered_at"]),
        )
        campaign = PreregisteredEstimatorCampaign(
            contract_version=root["contract_version"],
            campaign_id=root["campaign_id"],
            stored_plan=self._hydrate_plan(connection, root["stored_plan_fingerprint"]),
            policy=self._hydrate_gate_policy(connection, root["policy_fingerprint"]),
            assignment_manifest=manifest,
            split=split,
            legacy_preregistration=legacy,
            preregistration_v2=preregistration_v2,
            constellation_identity=constellation,
            registered_at=_required_time(root["registered_at"]),
            activation_allowed=bool(root["activation_allowed"]),
            private_export_allowed=bool(root["private_export_allowed"]),
            team_share_allowed=bool(root["team_share_allowed"]),
        )
        if campaign.fingerprint != root["campaign_fingerprint"]:
            raise DatabaseInvariantError("estimator campaign fingerprint is not reproducible")
        return campaign

    def delete_preregistered_campaign_for_privacy(
        self, campaign_id: str
    ) -> PrivacyDeleteOutcome:
        self._ensure_initialized()
        require_safe_id(campaign_id)
        authorization: tuple[str, str] | None = None
        if self._begin_evidence_delete_authorization is not None:
            authorization = self._begin_evidence_delete_authorization(campaign_id)
        try:
            with self._connection_scope() as connection:
                try:
                    connection.execute("PRAGMA trusted_schema = ON")
                    connection.execute("PRAGMA secure_delete = ON")
                    if int(connection.execute("PRAGMA secure_delete").fetchone()[0]) != 1:
                        raise DatabaseInvariantError(
                            "privacy deletion requires SQLite secure_delete"
                        )
                    connection.execute("BEGIN IMMEDIATE")
                    root = connection.execute(
                        "SELECT * FROM estimator_gate_campaigns WHERE campaign_id = ?",
                        (campaign_id,),
                    ).fetchone()
                    deleted = root is not None
                    # Retain only a domain-separated revocation digest and the
                    # first deletion time. No original campaign ID, plan, project,
                    # session, case, metric, packet, or constellation lineage
                    # survives in this record.
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO estimator_gate_campaign_tombstones(
                            revocation_key, deleted_at
                        ) VALUES (?, ?)
                        """,
                        (_campaign_revocation_key(campaign_id), to_iso(self._clock())),
                    )
                    if root is not None:
                        if authorization is None:
                            self._conflict(
                                "estimator evidence privacy deletion is not authorized"
                            )
                        connection.execute(
                            "INSERT INTO estimator_evidence_delete_authorizations VALUES (?, ?, ?)",
                            (authorization[0], campaign_id, authorization[1]),
                        )
                        connection.execute(
                            "DELETE FROM estimator_gate_campaigns WHERE campaign_id = ?",
                            (campaign_id,),
                        )
                        connection.execute(
                            "DELETE FROM estimator_preregistrations_v2 WHERE preregistration_fingerprint = ?",
                            (root["preregistration_v2_fingerprint"],),
                        )
                        connection.execute(
                            "DELETE FROM estimator_constellations WHERE constellation_fingerprint = ?",
                            (root["constellation_fingerprint"],),
                        )
                        connection.execute(
                            "DELETE FROM estimator_legacy_preregistrations WHERE preregistration_fingerprint = ?",
                            (root["legacy_preregistration_fingerprint"],),
                        )
                        connection.execute(
                            "DELETE FROM estimator_calibration_splits WHERE split_fingerprint = ?",
                            (root["split_fingerprint"],),
                        )
                        connection.execute(
                            "DELETE FROM estimator_case_manifests_v2 WHERE manifest_fingerprint = ?",
                            (root["assignment_manifest_fingerprint"],),
                        )
                    connection.commit()
                    connection.execute("PRAGMA trusted_schema = OFF")
                    checkpoint = connection.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    ).fetchone()
                    if checkpoint is None or tuple(int(value) for value in checkpoint) != (
                        0,
                        0,
                        0,
                    ):
                        raise DatabaseInvariantError(
                            "privacy deletion committed but durable WAL purge is pending"
                        )
                    return (
                        PrivacyDeleteOutcome.DELETED_AND_PURGED
                        if deleted
                        else PrivacyDeleteOutcome.ALREADY_ABSENT_AND_PURGED
                    )
                except Exception:
                    connection.rollback()
                    connection.execute("PRAGMA trusted_schema = OFF")
                    raise
        finally:
            if (
                authorization is not None
                and self._end_evidence_delete_authorization is not None
            ):
                self._end_evidence_delete_authorization(
                    authorization[0], campaign_id, authorization[1]
                )

    def delete_synthetic_case_for_privacy(self, case_id: str) -> PrivacyDeleteOutcome:
        """Delete one case and prove its WAL frames were durably truncated.

        A logical cascade is not reported as a successful privacy erase while a
        reader pins older WAL frames.  A caller may retry the same case ID after
        readers close; the retry checkpoints even when the logical row is gone.
        """

        self._ensure_initialized()
        require_safe_id(case_id)
        with self._connection_scope() as connection:
            try:
                connection.execute("PRAGMA secure_delete = ON")
                if int(connection.execute("PRAGMA secure_delete").fetchone()[0]) != 1:
                    raise DatabaseInvariantError(
                        "privacy deletion requires SQLite secure_delete"
                    )
                connection.execute("BEGIN IMMEDIATE")
                deleted = connection.execute(
                    "DELETE FROM estimator_synthetic_cases WHERE case_id = ?",
                    (case_id,),
                ).rowcount
                connection.commit()
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if checkpoint is None or tuple(int(value) for value in checkpoint) != (
                    0,
                    0,
                    0,
                ):
                    raise DatabaseInvariantError(
                        "privacy deletion committed but durable WAL purge is pending"
                    )
                return (
                    PrivacyDeleteOutcome.DELETED_AND_PURGED
                    if deleted
                    else PrivacyDeleteOutcome.ALREADY_ABSENT_AND_PURGED
                )
            except Exception:
                connection.rollback()
                raise
