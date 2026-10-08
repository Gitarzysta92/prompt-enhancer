"""Code-owned temporal comparison identities for deterministic Coaching v3.

Callers cannot submit comparison identities through this catalog.  The catalog
accepts only the closed synthetic completion request from the temporal
persistence contract, verifies the exact Coaching profile/pack/catalog, and
derives every identity field from committed code plus the already-bound input
comparison provenance.  Provider product releases, capture-receipt format, and
consent policy are operational or authorization lineage, not comparison
semantics: the exact input and repository seal retain them, while unchanged
adapter/provider/source/content schemas, transformation artifacts, privacy
policy, and evidence contract remain comparable.  The deterministic rules
remain provisional and explicitly not calibrated; this module does not activate
a model or make observations eligible for product comparison.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Final

from ...domain import DataTier, Provider
from ..analysis.coaching_baselines import (
    COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION,
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    COACHING_METRIC_RUBRIC_VERSION,
)
from ..analysis.text_analysis_presets import COACHING_PROFILE_V1
from ..analysis.text_contracts import MetricDirection as TextMetricDirection
from .contracts import (
    EstimatorIdentityKind,
    EstimatorLifecycleState,
    EvidenceTier,
    MetricComparisonIdentity,
    MetricDirection,
    TEMPORAL_HISTORY_CONTRACT_VERSION,
    TemporalAggregationSemantics,
    TemporalTrendSpec,
    TemporalValueKind,
)
from .persistence import SyntheticTemporalCompletionRequestV1


COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION = (
    "coaching-temporal-identity-catalog-v1"
)
COACHING_TEMPORAL_DEFINITION_NAMESPACE = "coaching-definition"
COACHING_TEMPORAL_QUESTION_NAMESPACE = "coaching-question"
COACHING_TEMPORAL_ESTIMATOR_PLAN_VERSION = "coaching-deterministic-plan-v1"
COACHING_TEMPORAL_CALIBRATION_VERSION = "not-calibrated-v1"
COACHING_TEMPORAL_PROFILE_KEY = COACHING_PROFILE_V1.analysis_profile_key
COACHING_TEMPORAL_PROFILE_VERSION = COACHING_PROFILE_V1.analysis_profile_version


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _CoachingMetricIdentitySpec:
    metric_key: str
    metric_definition_version: str
    metric_definition_sha256: str
    metric_question_version: str
    metric_question_sha256: str
    value_kind: TemporalValueKind
    unit_code: str
    direction: MetricDirection
    aggregation_semantics: TemporalAggregationSemantics
    evidence_tier: EvidenceTier
    evidence_contract_version: str
    estimator_plan_version: str
    estimator_plan_sha256: str
    calibration_version: str
    calibration_sha256: str


def _definition_payload(definition: Any) -> dict[str, Any]:
    return {
        "aggregation_method": definition.aggregation_method.value,
        "applicability_semantics": definition.applicability_semantics.value,
        "description": definition.description,
        "dimension": definition.dimension,
        "direction": definition.direction.value,
        "display_name": definition.display_name,
        "evidence_reference_kind": definition.evidence_reference_kind,
        "key": definition.key,
        "required_tier": definition.required_tier.value,
        "unit": definition.unit,
        "version": definition.version,
    }


def _make_spec(definition: Any) -> _CoachingMetricIdentitySpec:
    definition_payload = _definition_payload(definition)
    direction = {
        TextMetricDirection.HIGHER_IS_BETTER: MetricDirection.HIGHER_IS_BETTER,
        TextMetricDirection.LOWER_IS_BETTER: MetricDirection.LOWER_IS_BETTER,
    }[definition.direction]
    definition_version = (
        f"{COACHING_TEMPORAL_DEFINITION_NAMESPACE}-v{definition.version}"
    )
    question_version = (
        f"{COACHING_TEMPORAL_QUESTION_NAMESPACE}-v{definition.version}"
    )
    estimator_payload = {
        "algorithm_id": COACHING_METRIC_ALGORITHM_ID,
        "algorithm_version": COACHING_METRIC_ALGORITHM_VERSION,
        "engine_version": COACHING_METRIC_ENGINE_VERSION,
        "metric_definition": definition_payload,
        "plan_version": COACHING_TEMPORAL_ESTIMATOR_PLAN_VERSION,
        "rubric_version": COACHING_METRIC_RUBRIC_VERSION,
    }
    return _CoachingMetricIdentitySpec(
        metric_key=definition.key,
        metric_definition_version=definition_version,
        metric_definition_sha256=_digest(definition_payload),
        metric_question_version=question_version,
        metric_question_sha256=_digest(
            {
                "metric_key": definition.key,
                "question": definition.description,
                "question_version": question_version,
            }
        ),
        value_kind=TemporalValueKind.FRACTION,
        unit_code=definition.unit,
        direction=direction,
        aggregation_semantics=TemporalAggregationSemantics.RATIO_OF_SUMS,
        evidence_tier=EvidenceTier.REDACTED_CONTENT,
        evidence_contract_version=COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION,
        estimator_plan_version=COACHING_TEMPORAL_ESTIMATOR_PLAN_VERSION,
        estimator_plan_sha256=_digest(estimator_payload),
        calibration_version=COACHING_TEMPORAL_CALIBRATION_VERSION,
        calibration_sha256=_digest(
            {
                "metric_key": definition.key,
                "status": "not_calibrated",
                "version": COACHING_TEMPORAL_CALIBRATION_VERSION,
            }
        ),
    )


_SPECS: Final[tuple[_CoachingMetricIdentitySpec, ...]] = tuple(
    sorted(
        (_make_spec(definition) for definition in COACHING_METRIC_DEFINITIONS),
        key=lambda item: item.metric_key,
    )
)
COACHING_TEMPORAL_METRIC_KEYS: Final[tuple[str, ...]] = tuple(
    item.metric_key for item in _SPECS
)

if len(COACHING_TEMPORAL_METRIC_KEYS) != len(set(COACHING_TEMPORAL_METRIC_KEYS)):
    raise RuntimeError("the Coaching v3 registry contains duplicate metric keys")
if set(COACHING_TEMPORAL_METRIC_KEYS) != {
    definition.key for definition in COACHING_METRIC_DEFINITIONS
}:
    raise RuntimeError("the temporal catalog must exactly cover Coaching v3")

COACHING_TEMPORAL_ENGINE_SHA256: Final[str] = _digest(
    {
        "algorithm_id": COACHING_METRIC_ALGORITHM_ID,
        "algorithm_version": COACHING_METRIC_ALGORITHM_VERSION,
        "engine_version": COACHING_METRIC_ENGINE_VERSION,
        "rubric_version": COACHING_METRIC_RUBRIC_VERSION,
    }
)
COACHING_TEMPORAL_CATALOG_SHA256: Final[str] = _digest(
    {
        "catalog_version": COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
        "specs": [asdict(item) for item in _SPECS],
    }
)
COACHING_TEMPORAL_PACK_SHA256: Final[str] = _digest(
    {
        "catalog_sha256": COACHING_TEMPORAL_CATALOG_SHA256,
        "engine_sha256": COACHING_TEMPORAL_ENGINE_SHA256,
        "metric_keys": COACHING_TEMPORAL_METRIC_KEYS,
        "pack_key": COACHING_METRIC_PACK_KEY,
        "pack_version": COACHING_METRIC_PACK_VERSION,
    }
)
COACHING_TEMPORAL_PROFILE_SHA256: Final[str] = _digest(
    {
        "analysis_profile_key": COACHING_PROFILE_V1.analysis_profile_key,
        "analysis_profile_version": COACHING_PROFILE_V1.analysis_profile_version,
        "max_characters": COACHING_PROFILE_V1.max_characters,
        "max_messages": COACHING_PROFILE_V1.max_messages,
        "metric_pack_key": COACHING_PROFILE_V1.metric_pack_key,
        "metric_pack_version": COACHING_PROFILE_V1.metric_pack_version,
        "preset_id": COACHING_PROFILE_V1.preset_id.value,
        "task_profile": COACHING_PROFILE_V1.task_profile.model_dump(mode="json"),
    }
)
class CoachingTemporalIdentityCatalog:
    """Closed builder for the exact deterministic Coaching-v3 identity set."""

    __slots__ = ()

    @property
    def metric_keys(self) -> tuple[str, ...]:
        return COACHING_TEMPORAL_METRIC_KEYS

    @property
    def metric_pack_sha256(self) -> str:
        return COACHING_TEMPORAL_PACK_SHA256

    @property
    def metric_catalog_sha256(self) -> str:
        return COACHING_TEMPORAL_CATALOG_SHA256

    def build_for_synthetic_request(
        self, request: SyntheticTemporalCompletionRequestV1
    ) -> tuple[MetricComparisonIdentity, ...]:
        """Build selected identities from code-owned comparison semantics.

        The exact request still binds operational provider/capture and consent
        versions even though those three fields do not fragment an otherwise
        identical comparison identity.
        """

        checked = SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(
            request
        )
        scope = checked.prepared_scope
        selection = scope.selection_revision
        analysis_input = checked.analysis_input
        if analysis_input.provider is not Provider.SYNTHETIC:
            raise ValueError("the temporal Coaching catalog is synthetic-test-only")
        if analysis_input.data_tier is not DataTier.REDACTED_CONTENT:
            raise ValueError("Coaching identities require redacted-content evidence")
        selected_keys = selection.selected_metric_keys
        if (
            analysis_input.selected_metric_keys != selected_keys
            or not selected_keys
            or not set(selected_keys).issubset(COACHING_TEMPORAL_METRIC_KEYS)
        ):
            raise ValueError(
                "selection must be an exact nonempty subset of Coaching v3"
            )
        if (
            selection.metric_pack_key != COACHING_METRIC_PACK_KEY
            or selection.metric_pack_version != COACHING_METRIC_PACK_VERSION
            or selection.metric_pack_sha256 != COACHING_TEMPORAL_PACK_SHA256
            or selection.metric_catalog_version
            != COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION
            or selection.metric_catalog_sha256
            != COACHING_TEMPORAL_CATALOG_SHA256
        ):
            raise ValueError("selection must bind the code-owned Coaching v3 catalog")
        if (
            analysis_input.analysis_profile_key != COACHING_TEMPORAL_PROFILE_KEY
            or analysis_input.analysis_profile_version
            != COACHING_TEMPORAL_PROFILE_VERSION
            or analysis_input.analysis_profile_sha256
            != COACHING_TEMPORAL_PROFILE_SHA256
            or analysis_input.metric_engine_version
            != COACHING_METRIC_ENGINE_VERSION
            or analysis_input.metric_engine_sha256
            != COACHING_TEMPORAL_ENGINE_SHA256
        ):
            raise ValueError("analysis input must bind the deterministic Coaching profile")

        identities_by_key = {
            spec.metric_key: MetricComparisonIdentity(
                metric_key=spec.metric_key,
                metric_definition_version=spec.metric_definition_version,
                metric_definition_sha256=spec.metric_definition_sha256,
                metric_question_version=spec.metric_question_version,
                metric_question_sha256=spec.metric_question_sha256,
                value_kind=spec.value_kind,
                unit_code=spec.unit_code,
                direction=spec.direction,
                aggregation_semantics=spec.aggregation_semantics,
                exposure_unit_code=None,
                trend=TemporalTrendSpec(),
                interval_method_version=None,
                evidence_tier=spec.evidence_tier,
                evidence_contract_version=spec.evidence_contract_version,
                estimator_kind=EstimatorIdentityKind.DETERMINISTIC,
                estimator_plan_version=spec.estimator_plan_version,
                estimator_plan_sha256=spec.estimator_plan_sha256,
                estimator_lifecycle=EstimatorLifecycleState.PROVISIONAL,
                activation_receipt_sha256=None,
                model_provider=None,
                requested_model_key=None,
                requested_model_revision=None,
                served_model_key=None,
                served_model_revision=None,
                served_model_fallback=None,
                model_weight_identity_state=None,
                model_weight_set_sha256=None,
                tokenizer_key=None,
                tokenizer_revision=None,
                tokenizer_identity_state=None,
                tokenizer_sha256=None,
                model_license_code=None,
                reasoning_effort=None,
                preprocessing_version=analysis_input.preprocessing_version,
                preprocessing_sha256=analysis_input.preprocessing_sha256,
                prompt_template_version=None,
                prompt_template_sha256=None,
                rubric_version=None,
                rubric_sha256=None,
                calibration_version=spec.calibration_version,
                calibration_sha256=spec.calibration_sha256,
                router_version=analysis_input.router_version,
                router_sha256=analysis_input.router_sha256,
                redactor_version=analysis_input.redactor_version,
                redactor_sha256=analysis_input.redactor_sha256,
                provider=analysis_input.provider,
                provider_adapter_version=analysis_input.provider_adapter_version,
                provider_schema_version=analysis_input.provider_schema_version,
                source_schema_version=analysis_input.source_schema_version,
                content_schema_version=analysis_input.content_schema_version,
                privacy_policy_version=analysis_input.privacy_policy_version,
                observation_contract_version=TEMPORAL_HISTORY_CONTRACT_VERSION,
            )
            for spec in _SPECS
            if spec.metric_key in selected_keys
        }
        return tuple(identities_by_key[key] for key in selected_keys)


__all__ = [
    "COACHING_TEMPORAL_CALIBRATION_VERSION",
    "COACHING_TEMPORAL_CATALOG_SHA256",
    "COACHING_TEMPORAL_ENGINE_SHA256",
    "COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION",
    "COACHING_TEMPORAL_METRIC_KEYS",
    "COACHING_TEMPORAL_PACK_SHA256",
    "COACHING_TEMPORAL_PROFILE_KEY",
    "COACHING_TEMPORAL_PROFILE_SHA256",
    "COACHING_TEMPORAL_PROFILE_VERSION",
    "CoachingTemporalIdentityCatalog",
]
