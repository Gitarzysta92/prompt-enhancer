from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import hashlib
import math

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.history import (
    ArtifactIdentityState,
    CompatibilityBoundary,
    CompatibilityDimension,
    CountExposureObservationValue,
    DistributionSampleObservationValue,
    EstimatorIdentityKind,
    EstimatorLifecycleState,
    EvidenceTier,
    FractionObservationValue,
    HistoryCoverageState,
    MetricComparisonIdentity,
    MetricDirection,
    ModelProviderKind,
    ReasoningEffort,
    RevisionEffectiveTimeBasis,
    SampledProportionObservationValue,
    SessionRevisionProvenance,
    SessionRevisionRelation,
    SessionRevisionReceipt,
    SnapshotMetricCompatibilityState,
    TemporalAggregationSemantics,
    TemporalMetricObservation,
    TemporalObservationBatch,
    TemporalScopeState,
    TemporalSelectionState,
    TemporalSnapshotMaterializationRequest,
    TemporalSnapshotMetricReceipt,
    TemporalSnapshotReceipt,
    TemporalSnapshotSpec,
    TemporalSourceState,
    TemporalTrendMethod,
    TemporalTrendSpec,
    TemporalUncertainty,
    TemporalValueKind,
    TemporalValueState,
    TemporalWindowKind,
    TemporalWindowSpec,
)
from prompt_enhancer.domain import Provider


NOW = datetime(2044, 1, 2, 12, 0, tzinfo=UTC)
FLOOR = NOW - timedelta(days=30)


def _id(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _window() -> TemporalWindowSpec:
    return TemporalWindowSpec(kind=TemporalWindowKind.LAST_N, last_n=20)


def _identity(
    *,
    metric_key: str = "quality.requirement_coverage",
    value_kind: TemporalValueKind = TemporalValueKind.FRACTION,
    aggregation: TemporalAggregationSemantics = (
        TemporalAggregationSemantics.RATIO_OF_SUMS
    ),
    calibration_version: str = "calibration-v1",
    calibration_sha256: str | None = None,
    trend: TemporalTrendSpec | None = None,
    exposure_unit_code: str | None = None,
) -> MetricComparisonIdentity:
    return MetricComparisonIdentity(
        metric_key=metric_key,
        metric_definition_version="metric-v1",
        metric_definition_sha256=_id("metric-definition"),
        metric_question_version="question-v1",
        metric_question_sha256=_id("metric-question"),
        value_kind=value_kind,
        unit_code="ratio" if value_kind is TemporalValueKind.FRACTION else "events",
        direction=MetricDirection.HIGHER_IS_BETTER,
        aggregation_semantics=aggregation,
        exposure_unit_code=(
            exposure_unit_code
            if exposure_unit_code is not None
            else (
                "session_hours"
                if value_kind is TemporalValueKind.COUNT_WITH_EXPOSURE
                else None
            )
        ),
        trend=trend or TemporalTrendSpec(),
        interval_method_version=(
            "wilson-v1"
            if value_kind is TemporalValueKind.SAMPLED_PROPORTION
            else None
        ),
        evidence_tier=EvidenceTier.OBJECTIVE_ARTIFACT,
        evidence_contract_version="evidence-v1",
        estimator_kind=EstimatorIdentityKind.DETERMINISTIC,
        estimator_plan_version="plan-v1",
        estimator_plan_sha256=_id("estimator-plan"),
        estimator_lifecycle=EstimatorLifecycleState.PROVISIONAL,
        preprocessing_version="preprocess-v1",
        preprocessing_sha256=_id("preprocessing"),
        calibration_version=calibration_version,
        calibration_sha256=calibration_sha256 or _id(calibration_version),
        router_version="router-v1",
        router_sha256=_id("router"),
        redactor_version="redactor-v1",
        redactor_sha256=_id("redactor"),
        provider=Provider.SYNTHETIC,
        provider_adapter_version="adapter-v1",
        provider_schema_version="provider-schema-v1",
        source_schema_version="source-schema-v1",
        content_schema_version="content-schema-v1",
        privacy_policy_version="privacy-v1",
    )


def _model_identity(**overrides: object) -> MetricComparisonIdentity:
    values: dict[str, object] = {
        "metric_key": "quality.requirement_coverage",
        "metric_definition_version": "metric-v1",
        "metric_definition_sha256": _id("metric-definition"),
        "metric_question_version": "question-v1",
        "metric_question_sha256": _id("metric-question"),
        "value_kind": TemporalValueKind.FRACTION,
        "unit_code": "ratio",
        "direction": MetricDirection.HIGHER_IS_BETTER,
        "aggregation_semantics": TemporalAggregationSemantics.RATIO_OF_SUMS,
        "evidence_tier": EvidenceTier.REDACTED_CONTENT,
        "evidence_contract_version": "evidence-v1",
        "estimator_kind": EstimatorIdentityKind.MODEL_ASSISTED,
        "estimator_plan_version": "plan-v1",
        "estimator_plan_sha256": _id("estimator-plan"),
        "estimator_lifecycle": EstimatorLifecycleState.ACTIVATED,
        "activation_receipt_sha256": _id("activation-receipt"),
        "model_provider": ModelProviderKind.LOCAL,
        "requested_model_key": "example-model-a",
        "requested_model_revision": "revision-v1",
        "served_model_key": "example-model-a",
        "served_model_revision": "revision-v1",
        "served_model_fallback": False,
        "model_weight_identity_state": ArtifactIdentityState.PINNED_SHA256,
        "model_weight_set_sha256": _id("model-weights"),
        "tokenizer_key": "example-tokenizer-a",
        "tokenizer_revision": "revision-v1",
        "tokenizer_identity_state": ArtifactIdentityState.PINNED_SHA256,
        "tokenizer_sha256": _id("tokenizer"),
        "model_license_code": "example-license-v1",
        "reasoning_effort": ReasoningEffort.MEDIUM,
        "preprocessing_version": "preprocess-v1",
        "preprocessing_sha256": _id("preprocessing"),
        "prompt_template_version": "prompt-v1",
        "prompt_template_sha256": _id("prompt-template"),
        "rubric_version": "rubric-v1",
        "rubric_sha256": _id("rubric"),
        "calibration_version": "calibration-v1",
        "calibration_sha256": _id("calibration"),
        "router_version": "router-v1",
        "router_sha256": _id("router"),
        "redactor_version": "redactor-v1",
        "redactor_sha256": _id("redactor"),
        "provider": Provider.SYNTHETIC,
        "provider_adapter_version": "adapter-v1",
        "provider_schema_version": "provider-schema-v1",
        "source_schema_version": "source-schema-v1",
        "content_schema_version": "content-schema-v1",
        "privacy_policy_version": "privacy-v1",
    }
    values.update(overrides)
    return MetricComparisonIdentity(**values)


def _revision(*, ordinal: int = 1) -> SessionRevisionReceipt:
    captured = NOW - timedelta(hours=1)
    ended = captured - timedelta(minutes=1)
    return SessionRevisionReceipt(
        revision_id=_id(f"revision-{ordinal}"),
        root_receipt_id=_id("history-root"),
        root_receipt_fingerprint=_id("history-root-fingerprint"),
        project_id=_id("project"),
        session_id=_id("session"),
        revision_ordinal=ordinal,
        predecessor_revision_id=(
            _id(f"revision-{ordinal - 1}") if ordinal > 1 else None
        ),
        analysis_input_receipt_id=_id(f"analysis-input-{ordinal}"),
        analysis_input_receipt_fingerprint=_id(
            f"analysis-input-fingerprint-{ordinal}"
        ),
        input_provenance_fingerprint=_id("input-provenance"),
        relation=(
            SessionRevisionRelation.FIRST
            if ordinal == 1
            else SessionRevisionRelation.CHANGED_OR_REORDERED
        ),
        persisted_prefix_root=_id(f"source-manifest-{ordinal}"),
        persisted_prefix_event_count=4,
        analysis_window_fingerprint=_id(f"analysis-window-{ordinal}"),
        analysis_window_fingerprint_version="canonical-events-v1",
        analysis_window_started_at=ended - timedelta(hours=1),
        analysis_window_ended_at=ended,
        effective_at=ended,
        captured_at=captured,
        effective_time_basis=RevisionEffectiveTimeBasis.SESSION_ENDED_AT,
        provider=Provider.SYNTHETIC,
        provider_adapter_version="adapter-v1",
        provider_schema_version="provider-schema-v1",
        source_schema_version="source-schema-v1",
        content_schema_version="content-schema-v1",
        redactor_version="redactor-v1",
        event_count=4,
    )


def _known_observation(
    *, identity: MetricComparisonIdentity | None = None
) -> TemporalMetricObservation:
    comparison = identity or _identity()
    return TemporalMetricObservation(
        observation_id=_id("observation"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        comparison_identity=comparison,
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=FractionObservationValue(numerator=3, denominator=4),
        evidence_numerator=3,
        evidence_denominator=4,
        uncertainty=TemporalUncertainty(
            lower=0.4,
            upper=0.9,
            confidence_level=0.95,
            method_version="example-interval-v1",
        ),
        observed_at=NOW,
    )


def _materialization_request(
    *, window: TemporalWindowSpec | None = None
) -> TemporalSnapshotMaterializationRequest:
    return TemporalSnapshotMaterializationRequest(
        project_id=_id("project"),
        selection_revision_id=_id("selection"),
        selected_metric_keys=("quality.requirement_coverage",),
        window=window or _window(),
        task_mix_policy_version="unadjusted-v1",
    )


def _snapshot_spec() -> TemporalSnapshotSpec:
    return TemporalSnapshotSpec(
        request=_materialization_request(),
        as_of=NOW,
        history_floor_at=FLOOR,
        source_manifest_fingerprint=_id("source-manifest"),
        materializer_version="materializer-v1",
        aggregation_contract_version="aggregation-v1",
    )


def test_windows_support_last_n_exact_rolling_periods_and_custom_utc() -> None:
    assert _window().last_n == 20
    assert {
        TemporalWindowSpec(kind=TemporalWindowKind.ROLLING_DAYS, days=days).days
        for days in (7, 30, 90)
    } == {7, 30, 90}
    custom = TemporalWindowSpec(
        kind=TemporalWindowKind.CUSTOM,
        start_at=FLOOR,
        end_at=NOW,
    )
    assert custom.start_at == FLOOR
    assert (
        custom.window_boundary_semantics
        == "half_open_start_inclusive_end_exclusive"
    )

    with pytest.raises(ValidationError):
        TemporalWindowSpec(
            kind=TemporalWindowKind.LAST_N,
            last_n=20,
            window_boundary_semantics="closed",
        )


@pytest.mark.parametrize("days", [0, 1, 14, 365])
def test_rolling_windows_reject_every_non_product_period(days: int) -> None:
    with pytest.raises(ValidationError):
        TemporalWindowSpec(kind=TemporalWindowKind.ROLLING_DAYS, days=days)


def test_windows_reject_mixed_shapes_non_utc_and_unordered_custom_ranges() -> None:
    with pytest.raises(ValidationError):
        TemporalWindowSpec(
            kind=TemporalWindowKind.LAST_N,
            last_n=20,
            days=30,
        )
    with pytest.raises(ValidationError):
        TemporalWindowSpec(
            kind=TemporalWindowKind.CUSTOM,
            start_at=NOW.replace(tzinfo=None),
            end_at=NOW,
        )
    with pytest.raises(ValidationError):
        TemporalWindowSpec(
            kind=TemporalWindowKind.CUSTOM,
            start_at=NOW,
            end_at=NOW,
        )
    with pytest.raises(ValidationError):
        TemporalWindowSpec(
            kind=TemporalWindowKind.CUSTOM,
            start_at=FLOOR.astimezone(timezone(timedelta(hours=1))),
            end_at=NOW,
        )


def test_revision_receipt_is_direct_stable_and_never_legacy_inferred() -> None:
    first = _revision()
    second = _revision(ordinal=2)
    assert len(first.analysis_window_fingerprint) == 64
    assert second.predecessor_revision_id == first.revision_id
    assert first.provenance is SessionRevisionProvenance.DIRECT_ANALYSIS_WINDOW_RECEIPT
    assert first.legacy_inference_allowed is False
    assert first.contains_local_content is False
    assert first.remote_processing_allowed is False
    assert first.private_export_allowed is False
    assert first.team_share_allowed is False

    with pytest.raises(ValidationError):
        _revision().model_copy(update={"legacy_inference_allowed": True}).model_validate(
            {
                **_revision().model_dump(),
                "legacy_inference_allowed": True,
            }
        )


def test_revision_receipt_requires_ordinal_chain_and_matching_time_basis() -> None:
    values = _revision().model_dump()
    with pytest.raises(ValidationError):
        SessionRevisionReceipt(**{**values, "predecessor_revision_id": _id("prior")})
    with pytest.raises(ValidationError):
        SessionRevisionReceipt(
            **{
                **values,
                "revision_ordinal": 2,
                "predecessor_revision_id": None,
            }
        )
    with pytest.raises(ValidationError):
        SessionRevisionReceipt(
            **{
                **values,
                "effective_time_basis": RevisionEffectiveTimeBasis.REVISION_CAPTURED_AT,
            }
        )


def test_trend_contracts_distinguish_raw_values_from_rolling_and_ewma_views() -> None:
    assert TemporalTrendSpec().method is TemporalTrendMethod.NONE
    rolling = TemporalTrendSpec(
        method=TemporalTrendMethod.ROLLING_MEDIAN,
        rolling_observation_count=7,
    )
    ewma = TemporalTrendSpec(method=TemporalTrendMethod.EWMA, ewma_alpha=0.2)
    assert rolling.rolling_observation_count == 7
    assert ewma.ewma_alpha == 0.2

    for invalid in (0.0, -0.0, 1.1, math.inf, "0.2"):
        with pytest.raises(ValidationError):
            TemporalTrendSpec(method=TemporalTrendMethod.EWMA, ewma_alpha=invalid)


def test_comparison_identity_binds_every_deterministic_configuration_layer() -> None:
    identity = _identity()
    dumped = identity.model_dump(mode="json")
    assert identity.fingerprint == _identity().fingerprint
    assert len(identity.fingerprint) == 64
    for field in (
        "metric_definition_sha256",
        "metric_question_sha256",
        "estimator_plan_sha256",
        "preprocessing_sha256",
        "calibration_sha256",
        "router_sha256",
        "redactor_sha256",
        "provider_schema_version",
        "source_schema_version",
    ):
        assert dumped[field]


def test_model_comparison_identity_records_requested_and_served_artifacts() -> None:
    identity = _model_identity()
    assert identity.requested_model_key == "example-model-a"
    assert identity.served_model_key == "example-model-a"
    assert identity.model_weight_set_sha256 == _id("model-weights")
    assert identity.tokenizer_sha256 == _id("tokenizer")
    assert identity.activation_receipt_sha256 == _id("activation-receipt")

    with pytest.raises(ValidationError):
        _model_identity(tokenizer_sha256=None)
    with pytest.raises(ValidationError):
        _model_identity(reasoning_effort=ReasoningEffort.NONE)
    with pytest.raises(ValidationError):
        _model_identity(served_model_key=None)
    with pytest.raises(ValidationError):
        _model_identity(served_model_key="example-model-b", served_model_fallback=False)


def test_identity_rejects_semantic_mismatch_activation_forgery_and_model_leakage() -> None:
    values = _identity().model_dump()
    with pytest.raises(ValidationError):
        MetricComparisonIdentity(
            **{
                **values,
                "aggregation_semantics": (
                    TemporalAggregationSemantics.MEDIAN_AND_QUANTILES
                ),
            }
        )
    with pytest.raises(ValidationError):
        MetricComparisonIdentity(
            **{**values, "activation_receipt_sha256": _id("activation")}
        )
    with pytest.raises(ValidationError):
        MetricComparisonIdentity(
            **{**values, "requested_model_key": "example-model-a"}
        )


def test_count_identity_binds_exposure_unit_and_observation_must_match() -> None:
    identity = _identity(
        value_kind=TemporalValueKind.COUNT_WITH_EXPOSURE,
        aggregation=TemporalAggregationSemantics.COUNT_SUM_WITH_EXPOSURE,
        exposure_unit_code="session_hours",
    )
    observation = TemporalMetricObservation(
        observation_id=_id("count-observation"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        comparison_identity=identity,
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=CountExposureObservationValue(
            count=2,
            exposure=1.5,
            exposure_unit_code="session_hours",
        ),
        observed_at=NOW,
    )
    assert observation.value.exposure_unit_code == identity.exposure_unit_code

    with pytest.raises(ValidationError):
        MetricComparisonIdentity(
            **{**identity.model_dump(), "exposure_unit_code": None}
        )
    with pytest.raises(ValidationError):
        MetricComparisonIdentity(
            **{**_identity().model_dump(), "exposure_unit_code": "sessions"}
        )
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{
                **observation.model_dump(),
                "value": CountExposureObservationValue(
                    count=2,
                    exposure=1.5,
                    exposure_unit_code="sessions",
                ),
            }
        )


def test_sampled_proportion_uncertainty_uses_exact_identity_interval_method() -> None:
    identity = _identity(
        value_kind=TemporalValueKind.SAMPLED_PROPORTION,
        aggregation=TemporalAggregationSemantics.PROPORTION_INTERVAL_FROM_SUMS,
    )
    values = {
        "observation_id": _id("sampled-proportion-observation"),
        "revision_id": _id("revision-1"),
        "analysis_run_id": _id("analysis-run"),
        "analysis_input_receipt_id": _id("analysis-input"),
        "analysis_input_receipt_fingerprint": _id("analysis-input-fingerprint"),
        "comparison_identity": identity,
        "selection_state": TemporalSelectionState.SELECTED,
        "source_state": TemporalSourceState.PRESENT,
        "value_state": TemporalValueState.KNOWN,
        "value": SampledProportionObservationValue(successes=8, trials=10),
        "uncertainty": TemporalUncertainty(
            lower=0.49,
            upper=0.94,
            confidence_level=0.95,
            method_version="wilson-v1",
        ),
        "observed_at": NOW,
    }
    observation = TemporalMetricObservation(**values)
    assert (
        observation.uncertainty is not None
        and observation.uncertainty.method_version == identity.interval_method_version
    )

    with pytest.raises(ValidationError):
        TemporalMetricObservation(**{**values, "uncertainty": None})
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{
                **values,
                "uncertainty": TemporalUncertainty(
                    lower=0.49,
                    upper=0.94,
                    confidence_level=0.95,
                    method_version="jeffreys-v1",
                ),
            }
        )


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("metric_key", "../metric"),
        ("metric_key", "contains prose"),
        ("metric_key", "https://example.invalid"),
        ("provider_schema_version", "C:/reserved/example"),
        ("provider_schema_version", "file:example"),
    ],
)
def test_temporal_identifiers_are_path_uri_and_prose_free(
    field: str, unsafe: str
) -> None:
    values = _identity().model_dump()
    with pytest.raises(ValidationError):
        MetricComparisonIdentity(**{**values, field: unsafe})


def test_typed_observations_preserve_raw_aggregation_inputs() -> None:
    fraction = FractionObservationValue(numerator=3, denominator=5)
    count = CountExposureObservationValue(
        count=7,
        exposure=12.5,
        exposure_unit_code="session_hours",
    )
    sample = DistributionSampleObservationValue(sample=42.5)
    proportion = SampledProportionObservationValue(successes=8, trials=10)
    assert (fraction.numerator, fraction.denominator) == (3, 5)
    assert (count.count, count.exposure) == (7, 12.5)
    assert sample.sample == 42.5
    assert (proportion.successes, proportion.trials) == (8, 10)


def test_model_artifact_states_are_exactly_bound_to_provider_kind() -> None:
    remote = _model_identity(
        model_provider=ModelProviderKind.OPENAI,
        model_weight_identity_state=ArtifactIdentityState.PROVIDER_MANAGED_UNAVAILABLE,
        model_weight_set_sha256=None,
        tokenizer_identity_state=ArtifactIdentityState.PROVIDER_MANAGED_UNAVAILABLE,
        tokenizer_sha256=None,
    )
    synthetic = _model_identity(
        model_provider=ModelProviderKind.SYNTHETIC,
        model_weight_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
        model_weight_set_sha256=None,
        tokenizer_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
        tokenizer_sha256=None,
    )
    assert remote.model_weight_set_sha256 is None
    assert synthetic.tokenizer_identity_state is ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT

    with pytest.raises(ValidationError):
        _model_identity(
            model_provider=ModelProviderKind.LOCAL,
            model_weight_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
            model_weight_set_sha256=None,
            tokenizer_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
            tokenizer_sha256=None,
        )
    with pytest.raises(ValidationError):
        _model_identity(
            model_provider=ModelProviderKind.OPENAI,
            model_weight_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
            model_weight_set_sha256=None,
            tokenizer_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
            tokenizer_sha256=None,
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: FractionObservationValue(numerator=2, denominator=1),
        lambda: CountExposureObservationValue(
            count=1, exposure=-0.0, exposure_unit_code="sessions"
        ),
        lambda: CountExposureObservationValue(
            count=1, exposure="1", exposure_unit_code="sessions"
        ),
        lambda: DistributionSampleObservationValue(sample=-0.0),
        lambda: DistributionSampleObservationValue(sample=math.nan),
        lambda: SampledProportionObservationValue(successes=2, trials=1),
    ],
)
def test_typed_observations_reject_invented_or_noncanonical_numbers(factory: object) -> None:
    with pytest.raises(ValidationError):
        factory()  # type: ignore[operator]


def test_observation_keeps_selection_source_and_value_states_independent() -> None:
    known = _known_observation()
    assert known.selection_state is TemporalSelectionState.SELECTED
    assert known.source_state is TemporalSourceState.PRESENT
    assert known.value_state is TemporalValueState.KNOWN

    missing = TemporalMetricObservation(
        observation_id=_id("missing-observation"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        comparison_identity=_identity(),
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.SOURCE_MISSING,
        value_state=TemporalValueState.UNKNOWN,
        unavailable_reason_code="source_receipt_missing",
        observed_at=NOW,
    )
    not_selected = TemporalMetricObservation(
        observation_id=_id("not-selected-observation"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        comparison_identity=_identity(),
        selection_state=TemporalSelectionState.NOT_SELECTED,
        source_state=TemporalSourceState.NOT_REQUESTED,
        value_state=TemporalValueState.UNKNOWN,
        unavailable_reason_code="metric_not_selected",
        observed_at=NOW,
    )
    assert missing.selection_state is TemporalSelectionState.SELECTED
    assert not_selected.source_state is TemporalSourceState.NOT_REQUESTED


def test_observation_rejects_values_for_missing_sources_and_wrong_value_kinds() -> None:
    values = _known_observation().model_dump()
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{
                **values,
                "source_state": TemporalSourceState.SOURCE_MISSING,
                "value_state": TemporalValueState.UNKNOWN,
                "unavailable_reason_code": "source_missing",
            }
        )
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{
                **values,
                "source_state": TemporalSourceState.NOT_REQUESTED,
                "value_state": TemporalValueState.UNKNOWN,
                "value": None,
                "uncertainty": None,
                "evidence_numerator": None,
                "evidence_denominator": None,
                "unavailable_reason_code": "not_requested",
            }
        )
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{
                **values,
                "value": DistributionSampleObservationValue(sample=1.0),
            }
        )
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{
                **values,
                "source_state": TemporalSourceState.SOURCE_MISSING,
                "value_state": TemporalValueState.UNKNOWN,
                "value": None,
                "uncertainty": None,
                "unavailable_reason_code": "source_missing",
            }
        )


@pytest.mark.parametrize(
    ("source_state", "value_state"),
    [
        (TemporalSourceState.SOURCE_MISSING, TemporalValueState.ABSTAINED),
        (TemporalSourceState.SOURCE_MISSING, TemporalValueState.NOT_APPLICABLE),
        (TemporalSourceState.SOURCE_FAILED, TemporalValueState.UNKNOWN),
        (TemporalSourceState.SOURCE_INCOMPATIBLE, TemporalValueState.FAILED),
        (TemporalSourceState.PRESENT, TemporalValueState.FAILED),
    ],
)
def test_source_to_value_matrix_rejects_cross_axis_reclassification(
    source_state: TemporalSourceState,
    value_state: TemporalValueState,
) -> None:
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            observation_id=_id(f"invalid-{source_state}-{value_state}"),
            revision_id=_id("revision-1"),
            analysis_run_id=_id("analysis-run"),
            analysis_input_receipt_id=_id("analysis-input"),
            analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
            comparison_identity=_identity(),
            selection_state=TemporalSelectionState.SELECTED,
            source_state=source_state,
            value_state=value_state,
            unavailable_reason_code="invalid_cross_axis_state",
            observed_at=NOW,
        )


def test_observation_batch_binds_exact_selection_revision_and_source_state() -> None:
    observation = _known_observation()
    batch = TemporalObservationBatch(
        batch_id=_id("batch"),
        project_id=_id("project"),
        session_id=_id("session"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        selection_revision_id=_id("selection"),
        scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
        source_state=TemporalSourceState.PRESENT,
        selected_metric_keys=("quality.requirement_coverage",),
        observations=(observation,),
        recorded_at=NOW,
    )
    assert batch.direct_receipt_only is True
    assert batch.legacy_inference_allowed is False
    assert batch.contains_local_content is False
    assert batch.private_export_allowed is False
    assert batch.team_share_allowed is False
    later_batch = TemporalObservationBatch.revalidate_for_persistence(
        {**batch.model_dump(), "recorded_at": NOW + timedelta(seconds=1)}
    )
    assert len(batch.fingerprint) == 64
    assert later_batch.fingerprint != batch.fingerprint
    with pytest.raises(ValidationError):
        TemporalObservationBatch(
            **{**batch.model_dump(), "batch_fingerprint": _id("caller-batch")}
        )


def test_batch_preserves_per_metric_source_states_without_conflation() -> None:
    present = _known_observation()
    missing_identity = _identity(metric_key="quality.verification_coverage")
    missing = TemporalMetricObservation(
        observation_id=_id("missing-verification-observation"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        comparison_identity=missing_identity,
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.SOURCE_MISSING,
        value_state=TemporalValueState.UNKNOWN,
        unavailable_reason_code="source_receipt_missing",
        observed_at=NOW,
    )
    batch = TemporalObservationBatch(
        batch_id=_id("mixed-source-batch"),
        project_id=_id("project"),
        session_id=_id("session"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        selection_revision_id=_id("selection"),
        scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
        source_state=TemporalSourceState.PRESENT,
        selected_metric_keys=(
            "quality.requirement_coverage",
            "quality.verification_coverage",
        ),
        observations=(present, missing),
        recorded_at=NOW,
    )
    assert tuple(observation.source_state for observation in batch.observations) == (
        TemporalSourceState.PRESENT,
        TemporalSourceState.SOURCE_MISSING,
    )


def test_batch_can_record_unknown_scope_without_inventing_metric_omissions() -> None:
    batch = TemporalObservationBatch(
        batch_id=_id("unknown-scope-batch"),
        project_id=_id("project"),
        session_id=_id("session"),
        revision_id=_id("revision-1"),
        scope_state=TemporalScopeState.NO_SELECTION_RECEIPT,
        source_state=TemporalSourceState.NO_POST_FLOOR_SOURCE,
        recorded_at=NOW,
    )
    assert batch.selected_metric_keys == ()
    assert batch.observations == ()

    with pytest.raises(ValidationError):
        TemporalObservationBatch(
            **{
                **batch.model_dump(),
                "selected_metric_keys": ("quality.requirement_coverage",),
            }
        )


def test_batch_rejects_partial_selected_scope_and_revision_mismatch() -> None:
    observation = _known_observation()
    base = {
        "batch_id": _id("batch"),
        "project_id": _id("project"),
        "session_id": _id("session"),
        "revision_id": _id("revision-1"),
        "analysis_run_id": _id("analysis-run"),
        "analysis_input_receipt_id": _id("analysis-input"),
        "analysis_input_receipt_fingerprint": _id("analysis-input-fingerprint"),
        "selection_revision_id": _id("selection"),
        "scope_state": TemporalScopeState.EXACT_SELECTION_RECEIPT,
        "source_state": TemporalSourceState.PRESENT,
        "selected_metric_keys": (
            "quality.requirement_coverage",
            "quality.verification_coverage",
        ),
        "observations": (observation,),
        "recorded_at": NOW,
    }
    with pytest.raises(ValidationError):
        TemporalObservationBatch(**base)
    with pytest.raises(ValidationError):
        TemporalObservationBatch(
            **{
                **base,
                "selected_metric_keys": ("quality.requirement_coverage",),
                "revision_id": _id("different-revision"),
            }
        )


def test_batch_recording_never_precedes_an_observation() -> None:
    observation = _known_observation()
    with pytest.raises(ValidationError):
        TemporalObservationBatch(
            batch_id=_id("early-batch"),
            project_id=_id("project"),
            session_id=_id("session"),
            revision_id=_id("revision-1"),
            analysis_run_id=_id("analysis-run"),
            analysis_input_receipt_id=_id("analysis-input"),
            analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
            selection_revision_id=_id("selection"),
            scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
            source_state=TemporalSourceState.PRESENT,
            selected_metric_keys=("quality.requirement_coverage",),
            observations=(observation,),
            recorded_at=observation.observed_at - timedelta(microseconds=1),
        )


def test_materialization_request_has_no_client_authored_as_of_field() -> None:
    request = _materialization_request()
    assert "as_of" not in TemporalSnapshotMaterializationRequest.model_fields
    with pytest.raises(ValidationError):
        TemporalSnapshotMaterializationRequest(
            **{**request.model_dump(), "as_of": NOW}
        )


def test_snapshot_spec_binds_server_as_of_floor_manifest_and_custom_end() -> None:
    request = _materialization_request(
        window=TemporalWindowSpec(
            kind=TemporalWindowKind.CUSTOM,
            start_at=FLOOR,
            end_at=NOW,
        )
    )
    spec = TemporalSnapshotSpec(
        request=request,
        as_of=NOW,
        history_floor_at=FLOOR,
        source_manifest_fingerprint=_id("source-manifest"),
        materializer_version="materializer-v1",
        aggregation_contract_version="aggregation-v1",
    )
    assert len(spec.fingerprint) == 64
    assert spec.no_legacy_backfill is True
    assert spec.private_export_allowed is False

    with pytest.raises(ValidationError):
        TemporalSnapshotSpec(
            **{
                **spec.model_dump(),
                "request": _materialization_request(
                    window=TemporalWindowSpec(
                        kind=TemporalWindowKind.CUSTOM,
                        start_at=FLOOR,
                        end_at=NOW + timedelta(seconds=1),
                    )
                ),
            }
        )


def test_snapshot_receipt_is_reconstructed_and_disabled_until_repository_verified() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.COMPATIBLE,
        comparison_identity_fingerprints=(_identity().fingerprint,),
        eligible_revision_count=2,
        selected_revision_count=2,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=2,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=2,
        unknown_count=0,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    receipt = TemporalSnapshotReceipt.from_spec_and_children(
        snapshot_id=_id("snapshot"),
        spec=_snapshot_spec(),
        coverage_state=HistoryCoverageState.COMPLETE,
        effective_window_start_at=NOW - timedelta(days=1),
        effective_window_end_at=NOW,
        selected_session_count=2,
        eligible_revision_count=2,
        included_revision_count=2,
        omitted_revision_count=0,
        present_batch_revision_count=2,
        metric_receipts=(metric,),
        materialized_at=NOW,
    )
    assert receipt.spec_fingerprint == receipt.spec.fingerprint
    assert len(receipt.snapshot_fingerprint) == 64
    assert receipt.repository_verification_required is True
    assert receipt.sealed is False
    assert receipt.comparison_allowed is False
    assert receipt.activation_allowed is False
    assert receipt.legacy_backfill_performed is False
    assert receipt.contains_local_content is False
    assert receipt.remote_processing_allowed is False
    assert receipt.private_export_allowed is False
    assert receipt.team_share_allowed is False


def test_snapshot_receipt_keeps_missing_and_discontinuous_history_visible() -> None:
    discontinuity = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.DISCONTINUITY,
        comparison_identity_fingerprints=tuple(
            sorted((_identity().fingerprint, _model_identity().fingerprint))
        ),
        eligible_revision_count=3,
        selected_revision_count=3,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=2,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=1,
        known_count=2,
        unknown_count=0,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=1,
    )
    assert discontinuity.aggregate_values_omitted is True
    assert discontinuity.comparison_allowed is False

    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt(
            **{
                **discontinuity.model_dump(),
                "aggregate_fingerprint": _id("joined-across-boundary"),
            }
        )

    abstained_under_known_identity = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.COMPATIBLE,
        comparison_identity_fingerprints=(_identity().fingerprint,),
        eligible_revision_count=1,
        selected_revision_count=1,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=1,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=0,
        unknown_count=0,
        abstained_count=1,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    assert abstained_under_known_identity.aggregate_values_omitted is True

    empty_metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=(
            SnapshotMetricCompatibilityState.NO_COMPARABLE_OBSERVATIONS
        ),
        eligible_revision_count=1,
        selected_revision_count=0,
        not_selected_revision_count=0,
        selection_unknown_revision_count=1,
        present_source_count=0,
        not_requested_source_count=0,
        no_post_floor_source_count=1,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=0,
        unknown_count=1,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    empty = TemporalSnapshotReceipt(
        snapshot_id=_id("empty-snapshot"),
        spec=_snapshot_spec(),
        coverage_state=HistoryCoverageState.NO_POST_FLOOR_OBSERVATIONS,
        selected_session_count=1,
        eligible_revision_count=1,
        included_revision_count=0,
        omitted_revision_count=1,
        present_batch_revision_count=0,
        metric_receipts=(empty_metric,),
        materialized_at=NOW,
    )
    assert empty.effective_window_start_at is None


def test_snapshot_receipt_exposes_floor_clipping_and_partial_coverage_together() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.COMPATIBLE,
        comparison_identity_fingerprints=(_identity().fingerprint,),
        eligible_revision_count=2,
        selected_revision_count=1,
        not_selected_revision_count=0,
        selection_unknown_revision_count=1,
        present_source_count=1,
        not_requested_source_count=0,
        no_post_floor_source_count=1,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=1,
        unknown_count=1,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    receipt = TemporalSnapshotReceipt(
        snapshot_id=_id("left-censored-partial-snapshot"),
        spec=_snapshot_spec(),
        coverage_state=HistoryCoverageState.LEFT_CENSORED_PARTIAL,
        effective_window_start_at=FLOOR,
        effective_window_end_at=NOW,
        selected_session_count=2,
        eligible_revision_count=2,
        included_revision_count=1,
        omitted_revision_count=1,
        present_batch_revision_count=1,
        metric_receipts=(metric,),
        materialized_at=NOW,
    )
    assert receipt.coverage_state is HistoryCoverageState.LEFT_CENSORED_PARTIAL


def test_snapshot_receipt_rejects_false_complete_and_unclassified_counts() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=(
            SnapshotMetricCompatibilityState.NO_COMPARABLE_OBSERVATIONS
        ),
        eligible_revision_count=1,
        selected_revision_count=0,
        not_selected_revision_count=1,
        selection_unknown_revision_count=0,
        present_source_count=0,
        not_requested_source_count=1,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=0,
        unknown_count=1,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt(
            **{**metric.model_dump(), "selected_revision_count": 1}
        )
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(
            snapshot_id=_id("snapshot"),
            spec=_snapshot_spec(),
            coverage_state=HistoryCoverageState.COMPLETE,
            selected_session_count=2,
            eligible_revision_count=2,
            included_revision_count=1,
            omitted_revision_count=1,
            present_batch_revision_count=1,
            metric_receipts=(metric,),
            materialized_at=NOW,
        )


def test_snapshot_receipt_binds_global_metric_session_and_batch_counts() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.COMPATIBLE,
        comparison_identity_fingerprints=(_identity().fingerprint,),
        eligible_revision_count=2,
        selected_revision_count=2,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=2,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=2,
        unknown_count=0,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    base = {
        "snapshot_id": _id("count-bound-snapshot"),
        "spec": _snapshot_spec(),
        "coverage_state": HistoryCoverageState.COMPLETE,
        "effective_window_start_at": NOW - timedelta(days=1),
        "effective_window_end_at": NOW,
        "selected_session_count": 2,
        "eligible_revision_count": 2,
        "included_revision_count": 2,
        "omitted_revision_count": 0,
        "present_batch_revision_count": 2,
        "metric_receipts": (metric,),
        "materialized_at": NOW,
    }
    assert TemporalSnapshotReceipt(**base).selected_session_count == 2

    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(**{**base, "selected_session_count": 99})
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(**{**base, "present_batch_revision_count": 99})
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(**{**base, "present_batch_revision_count": 1})
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(
            **{
                **base,
                "eligible_revision_count": 3,
                "included_revision_count": 3,
                "present_batch_revision_count": 2,
            }
        )


def test_snapshot_fingerprints_are_derived_and_caller_values_are_rejected() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=(
            SnapshotMetricCompatibilityState.NO_COMPARABLE_OBSERVATIONS
        ),
        eligible_revision_count=0,
        selected_revision_count=0,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=0,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=0,
        unknown_count=0,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    values = {
        "snapshot_id": _id("derived-snapshot"),
        "spec": _snapshot_spec(),
        "coverage_state": HistoryCoverageState.NO_POST_FLOOR_OBSERVATIONS,
        "selected_session_count": 0,
        "eligible_revision_count": 0,
        "included_revision_count": 0,
        "omitted_revision_count": 0,
        "present_batch_revision_count": 0,
        "metric_receipts": (metric,),
        "materialized_at": NOW,
    }
    receipt = TemporalSnapshotReceipt(**values)
    assert receipt.spec_fingerprint == receipt.spec.fingerprint
    assert receipt.snapshot_fingerprint == TemporalSnapshotReceipt(**values).snapshot_fingerprint
    assert receipt.repository_verification_required is True
    assert receipt.comparison_allowed is False

    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(
            **{**values, "snapshot_fingerprint": _id("caller-snapshot-fingerprint")}
        )
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(
            **{**values, "spec_fingerprint": _id("caller-spec-fingerprint")}
        )
    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt(
            **{**metric.model_dump(), "aggregate_fingerprint": _id("caller-aggregate")}
        )


def test_recursive_persistence_revalidation_rejects_nested_model_copy_bypasses() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.COMPATIBLE,
        comparison_identity_fingerprints=(_identity().fingerprint,),
        eligible_revision_count=1,
        selected_revision_count=1,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=1,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=0,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=1,
        unknown_count=0,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    receipt_values = {
        "snapshot_id": _id("recursive-revalidation-snapshot"),
        "spec": _snapshot_spec(),
        "coverage_state": HistoryCoverageState.COMPLETE,
        "effective_window_start_at": NOW - timedelta(hours=1),
        "effective_window_end_at": NOW,
        "selected_session_count": 1,
        "eligible_revision_count": 1,
        "included_revision_count": 1,
        "omitted_revision_count": 0,
        "present_batch_revision_count": 1,
        "metric_receipts": (metric,),
        "materialized_at": NOW,
    }
    assert TemporalSnapshotReceipt.revalidate_for_persistence(receipt_values)

    forged_spec = _snapshot_spec().model_copy(update={"no_legacy_backfill": False})
    forged_aggregate = metric.model_copy(update={"aggregate_values_omitted": False})
    forged_comparison = metric.model_copy(update={"comparison_allowed": True})
    with pytest.raises(ValidationError):
        TemporalSnapshotSpec.revalidate_for_persistence(forged_spec)
    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt.revalidate_for_persistence(forged_aggregate)
    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt.revalidate_for_persistence(forged_comparison)
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt.revalidate_for_persistence(
            {**receipt_values, "spec": forged_spec}
        )
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt.revalidate_for_persistence(
            {**receipt_values, "metric_receipts": (forged_aggregate,)}
        )
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt.revalidate_for_persistence(
            {**receipt_values, "metric_receipts": (forged_comparison,)}
        )


def test_observation_batch_boundary_and_revision_revalidate_nested_copies() -> None:
    distribution_identity = _identity(
        value_kind=TemporalValueKind.DISTRIBUTION_SAMPLE,
        aggregation=TemporalAggregationSemantics.MEDIAN_AND_QUANTILES,
    )
    valid_value = DistributionSampleObservationValue(sample=1.0)
    forged_value = valid_value.model_copy(update={"sample": -0.0})
    observation = TemporalMetricObservation(
        observation_id=_id("distribution-observation"),
        revision_id=_id("revision-1"),
        analysis_run_id=_id("analysis-run"),
        analysis_input_receipt_id=_id("analysis-input"),
        analysis_input_receipt_fingerprint=_id("analysis-input-fingerprint"),
        comparison_identity=distribution_identity,
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=valid_value,
        observed_at=NOW,
    )
    forged_observation = observation.model_copy(update={"value": forged_value})
    with pytest.raises(ValidationError):
        TemporalMetricObservation.revalidate_for_persistence(forged_observation)
    with pytest.raises(ValidationError):
        TemporalMetricObservation(
            **{**observation.model_dump(), "value": forged_value}
        )

    batch_values = {
        "batch_id": _id("distribution-batch"),
        "project_id": _id("project"),
        "session_id": _id("session"),
        "revision_id": _id("revision-1"),
        "analysis_run_id": _id("analysis-run"),
        "analysis_input_receipt_id": _id("analysis-input"),
        "analysis_input_receipt_fingerprint": _id("analysis-input-fingerprint"),
        "selection_revision_id": _id("selection"),
        "scope_state": TemporalScopeState.EXACT_SELECTION_RECEIPT,
        "source_state": TemporalSourceState.PRESENT,
        "selected_metric_keys": ("quality.requirement_coverage",),
        "observations": (forged_observation,),
        "recorded_at": NOW,
    }
    with pytest.raises(ValidationError):
        TemporalObservationBatch.revalidate_for_persistence(batch_values)
    with pytest.raises(ValidationError):
        TemporalObservationBatch(**batch_values)

    revision = _revision()
    forged_revision = revision.model_copy(update={"legacy_inference_allowed": True})
    with pytest.raises(ValidationError):
        SessionRevisionReceipt.revalidate_for_persistence(forged_revision)

    before = _identity()
    after = _identity(
        calibration_version="calibration-v2",
        calibration_sha256=_id("calibration-v2"),
    )
    boundary_values = {
        "boundary_id": _id("recursive-boundary"),
        "project_id": _id("project"),
        "from_snapshot_id": _id("snapshot-1"),
        "to_snapshot_id": _id("snapshot-2"),
        "from_as_of": NOW - timedelta(days=1),
        "to_as_of": NOW,
        "from_identity": before,
        "to_identity": after.model_copy(update={"metric_key": "contains prose"}),
        "dimensions": (CompatibilityDimension.CALIBRATION,),
        "detected_at": NOW,
    }
    with pytest.raises(ValidationError):
        CompatibilityBoundary.revalidate_for_persistence(boundary_values)
    with pytest.raises(ValidationError):
        CompatibilityBoundary(**boundary_values)


def test_snapshot_metric_axis_counts_obey_the_observation_state_matrix() -> None:
    valid_missing = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=(
            SnapshotMetricCompatibilityState.NO_COMPARABLE_OBSERVATIONS
        ),
        eligible_revision_count=1,
        selected_revision_count=1,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=0,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=1,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=0,
        unknown_count=1,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    assert valid_missing.unknown_count == 1

    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt(
            **{
                **valid_missing.model_dump(),
                "unknown_count": 0,
                "abstained_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        TemporalSnapshotMetricReceipt(
            **{
                **valid_missing.model_dump(),
                "source_missing_count": 0,
                "source_failed_count": 1,
                "unknown_count": 1,
                "failed_count": 0,
            }
        )


def test_snapshot_rejects_selected_metric_scope_outside_included_revisions() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=SnapshotMetricCompatibilityState.COMPATIBLE,
        comparison_identity_fingerprints=(_identity().fingerprint,),
        eligible_revision_count=10,
        selected_revision_count=10,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=1,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=9,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=1,
        unknown_count=9,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(
            snapshot_id=_id("outside-included-snapshot"),
            spec=_snapshot_spec(),
            coverage_state=HistoryCoverageState.PARTIAL,
            effective_window_start_at=NOW - timedelta(days=1),
            effective_window_end_at=NOW,
            selected_session_count=9,
            eligible_revision_count=10,
            included_revision_count=9,
            omitted_revision_count=1,
            present_batch_revision_count=1,
            metric_receipts=(metric,),
            materialized_at=NOW,
        )


def test_snapshot_rejects_selected_scope_without_a_present_batch_revision() -> None:
    metric = TemporalSnapshotMetricReceipt(
        metric_key="quality.requirement_coverage",
        compatibility_state=(
            SnapshotMetricCompatibilityState.NO_COMPARABLE_OBSERVATIONS
        ),
        eligible_revision_count=2,
        selected_revision_count=2,
        not_selected_revision_count=0,
        selection_unknown_revision_count=0,
        present_source_count=0,
        not_requested_source_count=0,
        no_post_floor_source_count=0,
        source_missing_count=2,
        source_failed_count=0,
        source_incompatible_count=0,
        known_count=0,
        unknown_count=2,
        abstained_count=0,
        not_applicable_count=0,
        failed_count=0,
        incompatible_count=0,
    )
    with pytest.raises(ValidationError):
        TemporalSnapshotReceipt(
            snapshot_id=_id("missing-batch-selection-snapshot"),
            spec=_snapshot_spec(),
            coverage_state=HistoryCoverageState.COMPLETE,
            effective_window_start_at=NOW - timedelta(days=1),
            effective_window_end_at=NOW,
            selected_session_count=2,
            eligible_revision_count=2,
            included_revision_count=2,
            omitted_revision_count=0,
            present_batch_revision_count=1,
            metric_receipts=(metric,),
            materialized_at=NOW,
        )


def test_compatibility_boundary_derives_exact_version_dimension() -> None:
    before = _identity()
    after = _identity(
        calibration_version="calibration-v2",
        calibration_sha256=_id("calibration-v2"),
    )
    boundary = CompatibilityBoundary(
        boundary_id=_id("boundary"),
        project_id=_id("project"),
        from_snapshot_id=_id("snapshot-1"),
        to_snapshot_id=_id("snapshot-2"),
        from_as_of=NOW - timedelta(days=1),
        to_as_of=NOW,
        from_identity=before,
        to_identity=after,
        dimensions=(CompatibilityDimension.CALIBRATION,),
        detected_at=NOW,
    )
    assert boundary.dimensions == (CompatibilityDimension.CALIBRATION,)

    with pytest.raises(ValidationError):
        CompatibilityBoundary(
            **{
                **boundary.model_dump(),
                "dimensions": (CompatibilityDimension.MODEL_IDENTITY,),
            }
        )
    with pytest.raises(ValidationError):
        CompatibilityBoundary(
            **{
                **boundary.model_dump(),
                "to_identity": before,
            }
        )


def test_contract_serialization_contains_only_content_free_fields() -> None:
    serialized = _known_observation().model_dump_json()
    forbidden_field_fragments = (
        '"prompt"',
        '"evidence_text"',
        '"commentary"',
        '"source_path"',
        '"uri"',
        '"display_name"',
    )
    assert not any(fragment in serialized for fragment in forbidden_field_fragments)
