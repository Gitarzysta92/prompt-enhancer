"""Focused regressions for the synthetic raw-aggregation trust boundary."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import math
from typing import Iterator
from unittest.mock import patch

import pytest

from prompt_enhancer.application.history.aggregation import (
    INTERVAL_METHOD_VERSION,
    LAST_N_ORDER_VERSION,
    QUANTILE_METHOD_VERSION,
    RAW_AGGREGATION_POLICY_VERSION,
    SYNTHETIC_RAW_AGGREGATION_VERSION,
    WINDOW_TIME_BASIS,
    WILSON_Z,
    RawAggregationPolicyIdentityV1,
    SyntheticRawAggregationDraftV1,
    _compatibility_dimensions,
    draft_synthetic_raw_aggregation,
)
from prompt_enhancer.application.history.contracts import (
    ArtifactIdentityState,
    CompatibilityDimension,
    EstimatorIdentityKind,
    EstimatorLifecycleState,
    EvidenceCoverageEligibility,
    EvidenceCoverageState,
    MetricComparisonIdentity,
    ModelProviderKind,
    ReasoningEffort,
    TemporalValueKind,
)
from tests import test_temporal_aggregation as fixtures


def _digest(label: str) -> str:
    return hashlib.sha256(
        f"reserved-aggregation-adversarial:{label}".encode("ascii")
    ).hexdigest()


def test_public_reducer_requires_explicit_keyword_arguments() -> None:
    stratum = fixtures._stratum("keyword-only", day=1)
    with pytest.raises(TypeError):
        draft_synthetic_raw_aggregation(  # type: ignore[misc]
            stratum.prepared_stratum.prepared_scope,
            fixtures.METRIC,
            fixtures._window(),
            fixtures.AS_OF,
            (stratum,),
        )


@contextmanager
def _coverage_observation_factory(
    *,
    eligibility: EvidenceCoverageEligibility,
    state: EvidenceCoverageState,
    numerator: int | None,
    denominator: int | None,
) -> Iterator[None]:
    """Override only the evidence axis while retaining fixture graph derivation."""

    original_factory = fixtures._observation_factory

    def coverage_factory(**factory_values: object):
        base_builder = original_factory(**factory_values)

        def build(**observation_values: object):
            base = base_builder(**observation_values)
            payload = base.model_dump(mode="python")
            payload.update(
                evidence_coverage_eligibility=eligibility,
                evidence_coverage_state=state,
                evidence_numerator=numerator,
                evidence_denominator=denominator,
            )
            return type(base).model_validate(payload)

        return build

    with patch.object(fixtures, "_observation_factory", coverage_factory):
        yield


def _coverage_stratum(
    label: str,
    *,
    day: int,
    eligibility: EvidenceCoverageEligibility,
    state: EvidenceCoverageState,
    numerator: int | None,
    denominator: int | None,
):
    with _coverage_observation_factory(
        eligibility=eligibility,
        state=state,
        numerator=numerator,
        denominator=denominator,
    ):
        return fixtures._stratum(label, day=day)


def test_evidence_coverage_keeps_known_zero_over_zero_unknown_and_na_distinct() -> None:
    known_empty = _coverage_stratum(
        "coverage-known-empty",
        day=1,
        eligibility=EvidenceCoverageEligibility.ELIGIBLE,
        state=EvidenceCoverageState.KNOWN,
        numerator=0,
        denominator=0,
    )
    unknown = _coverage_stratum(
        "coverage-unknown",
        day=2,
        eligibility=EvidenceCoverageEligibility.ELIGIBLE,
        state=EvidenceCoverageState.UNKNOWN,
        numerator=None,
        denominator=None,
    )
    not_applicable = _coverage_stratum(
        "coverage-na",
        day=3,
        eligibility=EvidenceCoverageEligibility.NOT_ELIGIBLE,
        state=EvidenceCoverageState.NOT_APPLICABLE,
        numerator=None,
        denominator=None,
    )

    result = fixtures._draft(known_empty, unknown, not_applicable)
    counts = result.state_counts
    assert counts.evidence_eligible_count == 2
    assert counts.evidence_not_eligible_count == 1
    assert counts.evidence_eligibility_unknown_count == 0
    assert counts.evidence_coverage_known_count == 1
    assert counts.evidence_coverage_unknown_count == 1
    assert counts.evidence_coverage_not_applicable_count == 1

    coverage = result.task_buckets[0].evidence_coverage
    assert coverage is not None
    assert coverage.known_eligible_observation_count == 1
    assert coverage.numerator_sum == 0
    assert coverage.denominator_sum == 0
    assert coverage.ratio is None


def test_full_supplied_manifest_changes_draft_id_even_when_output_window_does_not() -> None:
    included = fixtures._stratum("manifest-included", day=1, raw=(1, 2))
    late = fixtures._stratum("manifest-late", day=20, raw=(1, 1))

    without_late = fixtures._draft(included)
    with_late = fixtures._draft(included, late)

    assert without_late.ordered_included_stratum_fingerprints == (
        with_late.ordered_included_stratum_fingerprints
    )
    assert with_late.excluded_late_seal_count == 1
    assert len(with_late.ordered_supplied_stratum_manifest) == 2
    assert without_late.aggregation_draft_id != with_late.aggregation_draft_id


def test_sampled_proportion_retains_source_method_and_code_owned_aggregate_method() -> None:
    result = fixtures._draft(
        fixtures._stratum(
            "interval-method",
            day=1,
            kind=TemporalValueKind.SAMPLED_PROPORTION,
            raw=(1, 10),
        )
    )
    run = result.compatibility_runs[0]
    bucket = run.task_buckets[0]
    aggregate = bucket.aggregate_value
    assert aggregate is not None
    assert aggregate.source_interval_method_version == (
        run.comparison_identity.interval_method_version
    )
    assert aggregate.source_interval_method_version == "wilson-score-v1"
    assert aggregate.interval_method_version == INTERVAL_METHOD_VERSION
    assert aggregate.interval_method_version == result.policy_identity.interval_method_version

    forged_aggregate = aggregate.model_copy(
        update={"source_interval_method_version": "forged-source-method-v1"}
    )
    forged_bucket = bucket.model_copy(update={"aggregate_value": forged_aggregate})
    forged_run = run.model_copy(update={"task_buckets": (forged_bucket,)})
    forged_result = result.model_copy(update={"compatibility_runs": (forged_run,)})
    with pytest.raises(ValueError, match="interval|identity|source"):
        SyntheticRawAggregationDraftV1.revalidate_for_persistence(forged_result)


def test_wilson_endpoints_contain_exact_zero_and_one() -> None:
    zero_result = fixtures._draft(
        fixtures._stratum(
            "wilson-zero-endpoint",
            day=1,
            kind=TemporalValueKind.SAMPLED_PROPORTION,
            raw=(0, 3),
        )
    )
    _, zero_aggregate = fixtures._known_aggregate(zero_result)
    assert zero_aggregate.proportion == 0.0
    assert zero_aggregate.interval_lower == 0.0
    assert zero_aggregate.interval_lower <= zero_aggregate.proportion

    one_result = fixtures._draft(
        fixtures._stratum(
            "wilson-one-endpoint",
            day=1,
            kind=TemporalValueKind.SAMPLED_PROPORTION,
            raw=(10, 10),
        )
    )
    _, one_aggregate = fixtures._known_aggregate(one_result)
    assert one_aggregate.proportion == 1.0
    assert one_aggregate.interval_upper == 1.0
    assert one_aggregate.proportion <= one_aggregate.interval_upper


def test_policy_identity_freezes_every_numeric_window_and_segmentation_parameter() -> None:
    policy = RawAggregationPolicyIdentityV1()
    payload = policy.model_dump(mode="python")
    assert payload == {
        "contract_version": RAW_AGGREGATION_POLICY_VERSION,
        "window_time_basis": WINDOW_TIME_BASIS,
        "window_boundary_semantics": "half_open_start_inclusive_end_exclusive",
        "last_n_unit": "session_revision",
        "last_n_order_version": LAST_N_ORDER_VERSION,
        "quantile_method_version": QUANTILE_METHOD_VERSION,
        "interval_method_version": INTERVAL_METHOD_VERSION,
        "interval_confidence_level": 0.95,
        "compatibility_segmentation": "contiguous_full_identity_runs",
        "task_bucket_pooling_allowed": False,
        "missing_value_imputation_allowed": False,
        "code_owned": True,
        "caller_override_allowed": False,
        "quantile_probabilities": (0.25, 0.5, 0.75),
        "interval_two_sided": True,
        "interval_z": WILSON_Z,
        "finite_binary64_required": True,
        "float_summation_method": "math.fsum-v1",
        "safe_integer_max": 9_007_199_254_740_991,
        "noncontiguous_identity_rejoin_allowed": False,
        "population_completeness_inferred": False,
        "task_mix_policy_version": "visible-untrusted-task-buckets-v1",
    }
    expected_fingerprint = hashlib.sha256(
        json.dumps(
            policy.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert policy.fingerprint == expected_fingerprint

    mutations = {
        "window_time_basis": "forged-window-v1",
        "window_boundary_semantics": "closed",
        "last_n_unit": "session",
        "last_n_order_version": "forged-order-v1",
        "quantile_method_version": "forged-quantile-v1",
        "interval_method_version": "forged-interval-v1",
        "interval_confidence_level": 0.9,
        "compatibility_segmentation": "fingerprint-buckets",
        "task_bucket_pooling_allowed": True,
        "missing_value_imputation_allowed": True,
        "code_owned": False,
        "caller_override_allowed": True,
        "quantile_probabilities": (0.1, 0.5, 0.9),
        "interval_two_sided": False,
        "interval_z": 1.0,
        "finite_binary64_required": False,
        "float_summation_method": "sum-v1",
        "safe_integer_max": 10,
        "noncontiguous_identity_rejoin_allowed": True,
        "population_completeness_inferred": True,
        "task_mix_policy_version": "pooled-v1",
    }
    for field_name, value in mutations.items():
        forged = policy.model_copy(update={field_name: value})
        with pytest.raises(ValueError):
            RawAggregationPolicyIdentityV1.revalidate_for_persistence(forged)


def test_floor_censoring_and_last_n_shortfall_are_independent_axes() -> None:
    only = fixtures._stratum("independent-window-axes", day=1)
    clipped = fixtures._draft(
        only,
        window=fixtures._window(
            start=fixtures.FLOOR - timedelta(days=10),
            end=fixtures.AS_OF,
        ),
    )
    assert clipped.floor_left_censored is True
    assert clipped.last_n_shortfall is False
    assert clipped.last_n_shortfall_count == 0

    short = fixtures._draft(only, window=fixtures._window(last_n=3))
    assert short.floor_left_censored is False
    assert short.last_n_shortfall is True
    assert short.last_n_shortfall_count == 2

    empty_last_n = fixtures._draft_empty(
        only.prepared_stratum.prepared_scope,
        window=fixtures._window(last_n=3),
    )
    assert empty_last_n.floor_left_censored is False
    assert empty_last_n.last_n_shortfall is True
    assert empty_last_n.last_n_shortfall_count == 3

    pre_floor_empty = fixtures._draft(
        only,
        window=fixtures._window(
            start=fixtures.FLOOR - timedelta(days=3),
            end=fixtures.FLOOR - timedelta(days=1),
        ),
    )
    assert pre_floor_empty.included_revision_count == 0
    assert pre_floor_empty.floor_left_censored is True
    assert pre_floor_empty.last_n_shortfall is False


def test_every_trust_and_downstream_capability_flag_is_fixed_false() -> None:
    result = fixtures._draft(fixtures._stratum("all-false-flags", day=1))
    false_fields = (
        "repository_owned",
        "repository_verified",
        "collection_completeness_verified",
        "sealed",
        "source_authority_verified",
        "product_capture_allowed",
        "product_history_eligible",
        "comparison_allowed",
        "pair_matching_allowed",
        "aggregate_materialization_allowed",
        "snapshot_materialization_allowed",
        "recommendation_allowed",
        "recommendation_outcome_evaluation_allowed",
        "causal_claim_allowed",
        "activation_allowed",
        "legacy_inference_allowed",
        "backfill_allowed",
        "contains_local_content",
        "remote_processing_allowed",
        "private_export_allowed",
        "team_share_allowed",
    )
    payload = result.model_dump(mode="python")
    assert all(payload[field_name] is False for field_name in false_fields)
    assert payload["contract_version"] == SYNTHETIC_RAW_AGGREGATION_VERSION
    assert payload["structurally_constructible_not_capability"] is True
    assert payload["synthetic_test_only"] is True
    assert payload["supplied_set_only"] is True
    assert payload["repository_verification_required"] is True

    for field_name in false_fields:
        forged = result.model_copy(update={field_name: True})
        with pytest.raises(ValueError):
            SyntheticRawAggregationDraftV1.revalidate_for_persistence(forged)


def test_type7_extreme_symmetric_samples_remain_finite() -> None:
    result = fixtures._draft(
        fixtures._stratum(
            "extreme-negative",
            day=1,
            kind=TemporalValueKind.DISTRIBUTION_SAMPLE,
            raw=-1e308,
        ),
        fixtures._stratum(
            "extreme-positive",
            day=2,
            kind=TemporalValueKind.DISTRIBUTION_SAMPLE,
            raw=1e308,
        ),
    )
    _, aggregate = fixtures._known_aggregate(result)
    assert all(
        math.isfinite(value)
        for value in (aggregate.p25, aggregate.median, aggregate.p75)
    )
    assert aggregate.p25 == pytest.approx(-5e307)
    assert aggregate.median == 0.0
    assert aggregate.p75 == pytest.approx(5e307)


def test_frozen_supplied_manifest_entry_mutation_is_revalidated_and_rejected() -> None:
    result = fixtures._draft(fixtures._stratum("manifest-mutation", day=1))
    entry = result.ordered_supplied_stratum_manifest[0]
    forged_entry = entry.model_copy(update={"disposition": "outside_window"})
    forged = result.model_copy(
        update={"ordered_supplied_stratum_manifest": (forged_entry,)}
    )
    with pytest.raises(ValueError, match="manifest|count|input"):
        SyntheticRawAggregationDraftV1.revalidate_for_persistence(forged)


def _model_assisted_activated_identity() -> MetricComparisonIdentity:
    source = fixtures._stratum("identity-dimensions", day=1)
    identity = (
        source.sealed_batch.seal_draft.observation_batch.observations[
            0
        ].comparison_identity
    )
    payload = identity.model_dump(mode="python")
    payload.update(
        estimator_kind=EstimatorIdentityKind.MODEL_ASSISTED,
        estimator_lifecycle=EstimatorLifecycleState.ACTIVATED,
        activation_receipt_sha256=_digest("activation-a"),
        model_provider=ModelProviderKind.SYNTHETIC,
        requested_model_key="reserved-model",
        requested_model_revision="reserved-model-v1",
        served_model_key="reserved-model",
        served_model_revision="reserved-model-v1",
        served_model_fallback=False,
        model_weight_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
        model_weight_set_sha256=None,
        tokenizer_key="reserved-tokenizer",
        tokenizer_revision="reserved-tokenizer-v1",
        tokenizer_identity_state=ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
        tokenizer_sha256=None,
        model_license_code="reserved-license",
        reasoning_effort=ReasoningEffort.LOW,
        prompt_template_version="reserved-prompt-v1",
        prompt_template_sha256=_digest("prompt-template"),
        rubric_version="reserved-rubric-v1",
        rubric_sha256=_digest("rubric"),
    )
    return MetricComparisonIdentity.model_validate(payload)


def test_reasoning_effort_and_activation_receipt_are_estimator_configuration() -> None:
    identity = _model_assisted_activated_identity()
    reasoning_payload = identity.model_dump(mode="python")
    reasoning_payload["reasoning_effort"] = ReasoningEffort.HIGH
    reasoning_changed = MetricComparisonIdentity.model_validate(reasoning_payload)
    assert _compatibility_dimensions(identity, reasoning_changed) == (
        CompatibilityDimension.ESTIMATOR_CONFIGURATION,
    )

    activation_payload = identity.model_dump(mode="python")
    activation_payload["activation_receipt_sha256"] = _digest("activation-b")
    activation_changed = MetricComparisonIdentity.model_validate(activation_payload)
    assert _compatibility_dimensions(identity, activation_changed) == (
        CompatibilityDimension.ESTIMATOR_CONFIGURATION,
    )
