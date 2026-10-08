"""Counterexample-oriented tests for pure synthetic temporal aggregation."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
import hashlib
from unittest.mock import patch

import pytest

from prompt_enhancer.application.history.contracts import (
    CountExposureObservationValue,
    DistributionSampleObservationValue,
    EvidenceCoverageEligibility,
    EvidenceCoverageState,
    FractionObservationValue,
    MetricComparisonIdentity,
    SampledProportionObservationValue,
    TemporalAggregationSemantics,
    TemporalSourceState,
    TemporalUncertainty,
    TemporalValueKind,
    TemporalValueState,
    TemporalWindowKind,
    TemporalWindowSpec,
)
from tests import test_temporal_comparison_strata_contracts as strata_fixtures


FLOOR = strata_fixtures.FLOOR
METRIC = strata_fixtures.METRIC
AS_OF = FLOOR + timedelta(days=20)


def _digest(label: str) -> str:
    return hashlib.sha256(f"reserved-aggregation:{label}".encode()).hexdigest()


# These roles belong to the shared prospective scope or comparison identity.
# Per-stratum record identities are namespaced by ``label`` below.
_SHARED_ID_ROLES = frozenset(
    {
        "analysis-profile",
        "consent",
        "consent-fingerprint",
        "estimator-plan",
        "installation",
        "metric-catalog",
        "metric-definition",
        "metric-engine",
        "metric-pack",
        "metric-question",
        "not-calibrated",
        "preprocessing",
        "redactor",
        "repository-verifier",
        "router",
    }
)


def _identity_factory(
    *,
    kind: TemporalValueKind,
    identity_label: str,
):
    base_factory = strata_fixtures._comparison_identity

    def build(analysis_input: object) -> MetricComparisonIdentity:
        base = base_factory(analysis_input)  # type: ignore[arg-type]
        semantics = {
            TemporalValueKind.FRACTION: TemporalAggregationSemantics.RATIO_OF_SUMS,
            TemporalValueKind.COUNT_WITH_EXPOSURE: (
                TemporalAggregationSemantics.COUNT_SUM_WITH_EXPOSURE
            ),
            TemporalValueKind.DISTRIBUTION_SAMPLE: (
                TemporalAggregationSemantics.MEDIAN_AND_QUANTILES
            ),
            TemporalValueKind.SAMPLED_PROPORTION: (
                TemporalAggregationSemantics.PROPORTION_INTERVAL_FROM_SUMS
            ),
        }[kind]
        return MetricComparisonIdentity.model_validate(
            {
                **base.model_dump(mode="python"),
                "metric_definition_version": (
                    f"reserved-definition-{identity_label}-v1"
                ),
                "metric_definition_sha256": _digest(
                    f"metric-definition:{identity_label}"
                ),
                "value_kind": kind,
                "aggregation_semantics": semantics,
                "unit_code": {
                    TemporalValueKind.FRACTION: "ratio",
                    TemporalValueKind.COUNT_WITH_EXPOSURE: "items",
                    TemporalValueKind.DISTRIBUTION_SAMPLE: "seconds",
                    TemporalValueKind.SAMPLED_PROPORTION: "ratio",
                }[kind],
                "exposure_unit_code": (
                    "minutes"
                    if kind is TemporalValueKind.COUNT_WITH_EXPOSURE
                    else None
                ),
                "interval_method_version": (
                    "wilson-score-v1"
                    if kind is TemporalValueKind.SAMPLED_PROPORTION
                    else None
                ),
            }
        )

    return build


def _known_value(
    kind: TemporalValueKind,
    raw: tuple[int, int] | tuple[int, float] | float,
) -> (
    FractionObservationValue
    | CountExposureObservationValue
    | DistributionSampleObservationValue
    | SampledProportionObservationValue
):
    if kind is TemporalValueKind.FRACTION:
        numerator, denominator = raw
        return FractionObservationValue(
            numerator=int(numerator), denominator=int(denominator)
        )
    if kind is TemporalValueKind.COUNT_WITH_EXPOSURE:
        count, exposure = raw
        return CountExposureObservationValue(
            count=int(count),
            exposure=float(exposure),
            exposure_unit_code="minutes",
        )
    if kind is TemporalValueKind.DISTRIBUTION_SAMPLE:
        return DistributionSampleObservationValue(sample=float(raw))
    successes, trials = raw
    return SampledProportionObservationValue(
        successes=int(successes), trials=int(trials)
    )


def _observation_factory(
    *,
    kind: TemporalValueKind,
    raw: tuple[int, int] | tuple[int, float] | float,
    value_state: TemporalValueState,
    source_state: TemporalSourceState,
):
    observation_type = strata_fixtures.TemporalMetricObservationV2

    def build(**values: object):
        values["source_state"] = source_state
        values["value_state"] = value_state
        if value_state is TemporalValueState.KNOWN:
            values["value"] = _known_value(kind, raw)
            values["unavailable_reason_code"] = None
            if kind is TemporalValueKind.SAMPLED_PROPORTION:
                values["uncertainty"] = TemporalUncertainty(
                    lower=0.0,
                    upper=1.0,
                    confidence_level=0.95,
                    method_version="wilson-score-v1",
                )
        else:
            values["value"] = None
            values["uncertainty"] = None
            values["unavailable_reason_code"] = "reserved-value-unavailable"
        if source_state is not TemporalSourceState.PRESENT:
            values.update(
                evidence_coverage_eligibility=EvidenceCoverageEligibility.UNKNOWN,
                evidence_coverage_state=EvidenceCoverageState.UNKNOWN,
                evidence_numerator=None,
                evidence_denominator=None,
            )
        return observation_type(**values)

    return build


def _stratum(
    label: str,
    *,
    day: int,
    kind: TemporalValueKind = TemporalValueKind.FRACTION,
    raw: tuple[int, int] | tuple[int, float] | float = (1, 1),
    identity_label: str = "a",
    value_state: TemporalValueState = TemporalValueState.KNOWN,
    source_state: TemporalSourceState = TemporalSourceState.PRESENT,
    task_type: str | None = "bug_fix",
    root_label: str = "main",
    selected_metric_key: str = METRIC,
):
    """Build one fully validated sealed draft using only reserved fixtures."""

    prepared_at = FLOOR + timedelta(days=day, minutes=2)
    original_id = strata_fixtures._id
    original_expected_run = strata_fixtures._expected_run_request

    def fixture_id(role: str) -> str:
        if role in {
            "automation-grant",
            "prepared-scope",
            "selection",
        }:
            return _digest(f"{role}:{root_label}:{selected_metric_key}")
        if role in {"history-root", "project"}:
            return _digest(f"{role}:{root_label}")
        if role in _SHARED_ID_ROLES:
            return original_id(role)
        return _digest(f"stratum:{label}:{role}")

    def expected_run(
        job: object,
        *,
        run_id: str | None = None,
        issued_at: datetime | None = None,
    ):
        return original_expected_run(
            job,  # type: ignore[arg-type]
            run_id=run_id or fixture_id("analysis-run"),
            issued_at=issued_at or prepared_at,
        )

    identity_factory = _identity_factory(kind=kind, identity_label=identity_label)
    observation_factory = _observation_factory(
        kind=kind,
        raw=raw,
        value_state=value_state,
        source_state=source_state,
    )

    with ExitStack() as stack:
        stack.enter_context(patch.object(strata_fixtures, "PREPARED_AT", prepared_at))
        stack.enter_context(patch.object(strata_fixtures, "METRIC", selected_metric_key))
        stack.enter_context(patch.object(strata_fixtures, "_id", fixture_id))
        stack.enter_context(
            patch.object(
                strata_fixtures,
                "_expected_run_request",
                expected_run,
            )
        )
        stack.enter_context(
            patch.object(
                strata_fixtures,
                "_comparison_identity",
                identity_factory,
            )
        )
        stack.enter_context(
            patch.object(
                strata_fixtures,
                "TemporalMetricObservationV2",
                observation_factory,
            )
        )
        revisions = (
            ()
            if task_type is None
            else (strata_fixtures._task_revision(label, task_type=task_type),)
        )
        return strata_fixtures._seal_draft(revisions)


def _window(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    last_n: int | None = None,
) -> TemporalWindowSpec:
    if last_n is not None:
        return TemporalWindowSpec(kind=TemporalWindowKind.LAST_N, last_n=last_n)
    return TemporalWindowSpec(
        kind=TemporalWindowKind.CUSTOM,
        start_at=start or FLOOR,
        end_at=end or AS_OF,
    )


def _draft(*strata: object, window: TemporalWindowSpec | None = None):
    from prompt_enhancer.application.history.aggregation import (
        draft_synthetic_raw_aggregation,
    )

    anchor = strata[0].prepared_stratum.prepared_scope  # type: ignore[attr-defined]
    return draft_synthetic_raw_aggregation(
        anchor_scope=anchor,
        metric_key=METRIC,
        window=window or _window(),
        as_of=AS_OF,
        strata=tuple(strata),  # type: ignore[arg-type]
    )


def _draft_empty(anchor: object, *, window: TemporalWindowSpec | None = None):
    from prompt_enhancer.application.history.aggregation import (
        draft_synthetic_raw_aggregation,
    )

    return draft_synthetic_raw_aggregation(
        anchor_scope=anchor,  # type: ignore[arg-type]
        metric_key=METRIC,
        window=window or _window(),
        as_of=AS_OF,
        strata=(),
    )

def _known_aggregate(result: object):
    """Locate the sole task bucket and its typed aggregate without aliases."""

    assert len(result.compatibility_runs) == 1  # type: ignore[attr-defined]
    run = result.compatibility_runs[0]  # type: ignore[attr-defined]
    assert len(run.task_buckets) == 1
    bucket = run.task_buckets[0]
    assert bucket.aggregate_value is not None
    return bucket, bucket.aggregate_value


def _field(value: object, *names: str):
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    raise AssertionError(f"none of the expected fields exist: {names!r}")


def test_fraction_uses_ratio_of_sums_and_keeps_state_counts() -> None:
    result = _draft(
        _stratum("fraction-a", day=1, raw=(1, 2)),
        _stratum("fraction-b", day=2, raw=(2, 8)),
        _stratum(
            "fraction-unknown",
            day=3,
            value_state=TemporalValueState.UNKNOWN,
        ),
    )

    bucket, aggregate = _known_aggregate(result)
    assert _field(aggregate, "numerator_sum", "numerator") == 3
    assert _field(aggregate, "denominator_sum", "denominator") == 10
    assert _field(aggregate, "ratio", "value") == pytest.approx(0.3)
    counts = _field(bucket, "state_counts", "counts")
    assert counts.value_known_count == 2
    assert counts.value_unknown_count == 1


def test_count_exposure_sums_both_axes_without_mean_of_rates() -> None:
    result = _draft(
        _stratum(
            "count-a",
            day=1,
            kind=TemporalValueKind.COUNT_WITH_EXPOSURE,
            raw=(2, 4.0),
        ),
        _stratum(
            "count-b",
            day=2,
            kind=TemporalValueKind.COUNT_WITH_EXPOSURE,
            raw=(6, 12.0),
        ),
    )
    _, aggregate = _known_aggregate(result)
    assert _field(aggregate, "count_sum", "count") == 8
    assert _field(aggregate, "exposure_sum", "exposure") == pytest.approx(16.0)
    assert _field(aggregate, "rate", "value") == pytest.approx(0.5)
    assert _field(aggregate, "exposure_unit_code") == "minutes"


def test_distribution_uses_hyndman_fan_type_7_quantiles() -> None:
    result = _draft(
        *(
            _stratum(
                f"sample-{index}",
                day=index,
                kind=TemporalValueKind.DISTRIBUTION_SAMPLE,
                raw=sample,
            )
            for index, sample in enumerate((1.0, 2.0, 3.0, 100.0), start=1)
        )
    )
    _, aggregate = _known_aggregate(result)
    assert aggregate.known_observation_count == 4
    assert aggregate.p25 == pytest.approx(1.75)
    assert _field(aggregate, "median", "p50") == pytest.approx(2.5)
    assert aggregate.p75 == pytest.approx(27.25)
    assert aggregate.quantile_method_version == (
        "hyndman-fan-type-7-p25-p50-p75-binary64-v1"
    )


def test_sampled_proportion_recomputes_wilson_interval_from_sums() -> None:
    result = _draft(
        _stratum(
            "proportion-a",
            day=1,
            kind=TemporalValueKind.SAMPLED_PROPORTION,
            raw=(1, 2),
        ),
        _stratum(
            "proportion-b",
            day=2,
            kind=TemporalValueKind.SAMPLED_PROPORTION,
            raw=(8, 10),
        ),
    )
    _, aggregate = _known_aggregate(result)
    assert _field(aggregate, "successes_sum", "successes") == 9
    assert _field(aggregate, "trials_sum", "trials") == 12
    assert _field(aggregate, "proportion", "value") == pytest.approx(0.75)
    assert aggregate.interval_method_version == "wilson-score-two-sided-95-v1"
    assert aggregate.interval_lower == pytest.approx(0.4677, abs=1e-4)
    assert aggregate.interval_upper == pytest.approx(0.9111, abs=1e-4)


def test_custom_window_is_half_open_and_history_floor_is_a_hard_bound() -> None:
    strata = (
        _stratum("at-start", day=1, raw=(1, 1)),
        _stratum("inside", day=2, raw=(1, 2)),
        _stratum("at-end", day=3, raw=(0, 1)),
    )
    start = strata[0].sealed_batch.seal_draft.session_revision.effective_at
    end = strata[2].sealed_batch.seal_draft.session_revision.effective_at
    result = _draft(*strata, window=_window(start=start, end=end))
    _, aggregate = _known_aggregate(result)
    assert _field(aggregate, "denominator_sum", "denominator") == 3
    assert result.effective_window_start_at >= FLOOR
    assert result.effective_window_end_at == end


def test_window_wholly_before_prospective_floor_is_empty_and_floor_clipped() -> None:
    result = _draft(
        _stratum("post-floor", day=1),
        window=_window(
            start=FLOOR - timedelta(days=3),
            end=FLOOR - timedelta(days=1),
        ),
    )
    assert result.included_revision_count == 0
    assert result.effective_window_start_at == FLOOR
    assert result.effective_window_end_at == FLOOR
    assert str(result.window_coverage_state) == "no_included_revisions"
    assert result.compatibility_runs == ()
    assert result.task_buckets == ()


def test_last_n_orders_by_effective_time_then_stable_identity() -> None:
    result = _draft(
        _stratum("first", day=1, raw=(1, 2)),
        _stratum("second", day=2, raw=(0, 4)),
        _stratum("third", day=3, raw=(3, 3)),
        window=_window(last_n=2),
    )
    _, aggregate = _known_aggregate(result)
    assert _field(aggregate, "numerator_sum", "numerator") == 3
    assert _field(aggregate, "denominator_sum", "denominator") == 7
    assert result.included_revision_count == 2


def test_last_n_tie_break_is_deterministic_and_input_order_independent() -> None:
    tied = (
        _stratum("tie-a", day=4, raw=(1, 2)),
        _stratum("tie-b", day=4, raw=(0, 3)),
        _stratum("tie-c", day=4, raw=(4, 4)),
    )
    forward = _draft(*tied, window=_window(last_n=2))
    reverse = _draft(*reversed(tied), window=_window(last_n=2))
    assert forward == reverse
    assert forward.fingerprint == reverse.fingerprint
    assert forward.included_revision_count == 2
    expected = tuple(
        item.fingerprint
        for item in sorted(
            tied,
            key=lambda item: (
                item.sealed_batch.seal_draft.session_revision.effective_at,
                item.sealed_batch.seal_draft.session_revision.session_id,
                item.sealed_batch.seal_draft.session_revision.revision_ordinal,
                item.sealed_batch.seal_draft.session_revision.revision_id,
            ),
        )[-2:]
    )
    assert forward.ordered_included_stratum_fingerprints == expected


def test_empty_input_remains_an_explicit_unknown_population() -> None:
    anchor = _stratum("anchor-only", day=1).prepared_stratum.prepared_scope
    result = _draft_empty(anchor)
    assert result.supplied_strata_count == 0
    assert result.included_revision_count == 0
    assert result.state_counts.supplied_revision_count == 0
    assert result.task_buckets == ()
    assert result.compatibility_runs == ()
    assert result.installation_id is None
    assert result.provider is None
    assert str(result.population_state) == "supplied_set_completeness_unknown"


def test_last_n_shortfall_and_rolling_floor_censoring_remain_explicit() -> None:
    only = _stratum("only-shortfall", day=1)
    shortfall = _draft(only, window=_window(last_n=3))
    assert shortfall.last_n_shortfall_count == 2
    assert str(shortfall.window_coverage_state) == "last_n_shortfall"

    rolling = _draft(
        only,
        window=TemporalWindowSpec(kind=TemporalWindowKind.ROLLING_DAYS, days=30),
    )
    assert rolling.effective_window_start_at == FLOOR
    assert rolling.effective_window_end_at == AS_OF
    assert str(rolling.window_coverage_state) == (
        "left_censored_by_prospective_floor"
    )


def test_identity_runs_preserve_a_to_b_to_a_as_three_contiguous_runs() -> None:
    result = _draft(
        _stratum("a1", day=1, identity_label="a"),
        _stratum("b", day=2, identity_label="b"),
        _stratum("a2", day=3, identity_label="a"),
    )
    runs = result.compatibility_runs
    transitions = result.compatibility_transitions
    assert len(runs) == 3
    assert [str(item.kind) for item in transitions] == [
        "identity_change",
        "identity_change",
    ]
    assert runs[0].comparison_identity_fingerprint == (
        runs[2].comparison_identity_fingerprint
    )
    assert runs[0].comparison_identity_fingerprint != (
        runs[1].comparison_identity_fingerprint
    )
    assert all(transition.dimensions for transition in transitions)


def test_identity_unavailable_metric_selection_gap_splits_runs() -> None:
    result = _draft(
        _stratum("a1-gap", day=1, identity_label="a"),
        _stratum(
            "gap",
            day=2,
            identity_label="a",
            selected_metric_key="reserved.alternate.metric",
        ),
        _stratum("a2-gap", day=3, identity_label="a"),
    )
    runs = _field(result, "compatibility_runs", "runs")
    transitions = _field(result, "compatibility_transitions", "transitions")
    assert len(runs) == 2
    assert [str(item.kind) for item in transitions] == [
        "identity_unavailable_gap"
    ]
    first_identity = runs[0].comparison_identity_fingerprint
    assert first_identity == _field(
        runs[-1], "comparison_identity_fingerprint"
    )
    assert transitions[-1].identity_unavailable_gap_count == 1
    assert transitions[-1].dimensions == ()
    assert result.state_counts.identity_unavailable_count == 1
    assert result.state_counts.not_selected_count == 1
    assert result.state_counts.source_not_requested_count == 1


def test_missing_states_are_counted_and_never_coerced_to_zero() -> None:
    result = _draft(
        _stratum("known", day=1, raw=(1, 2)),
        _stratum("unknown", day=2, value_state=TemporalValueState.UNKNOWN),
        _stratum("abstained", day=3, value_state=TemporalValueState.ABSTAINED),
        _stratum(
            "not-applicable",
            day=4,
            value_state=TemporalValueState.NOT_APPLICABLE,
        ),
        _stratum(
            "missing",
            day=5,
            source_state=TemporalSourceState.SOURCE_MISSING,
            value_state=TemporalValueState.UNKNOWN,
        ),
        _stratum(
            "failed",
            day=6,
            source_state=TemporalSourceState.SOURCE_FAILED,
            value_state=TemporalValueState.FAILED,
        ),
        _stratum(
            "incompatible",
            day=7,
            source_state=TemporalSourceState.SOURCE_INCOMPATIBLE,
            value_state=TemporalValueState.INCOMPATIBLE,
        ),
    )
    bucket, aggregate = _known_aggregate(result)
    assert _field(aggregate, "numerator_sum", "numerator") == 1
    assert _field(aggregate, "denominator_sum", "denominator") == 2
    counts = _field(bucket, "state_counts", "counts")
    assert counts.value_known_count == 1
    assert counts.value_unknown_count == 2
    assert counts.value_abstained_count == 1
    assert counts.value_not_applicable_count == 1
    assert counts.value_failed_count == 1
    assert counts.value_incompatible_count == 1
    assert counts.source_missing_count == 1
    assert counts.source_failed_count == 1
    assert counts.source_incompatible_count == 1


def test_task_buckets_are_never_pooled() -> None:
    result = _draft(
        _stratum("bug", day=1, raw=(1, 2), task_type="bug_fix"),
        _stratum("feature", day=2, raw=(1, 4), task_type="feature_implementation"),
    )
    buckets = result.task_buckets
    assert len(buckets) == 2
    assert {str(_field(item, "task_mix_bucket", "bucket")) for item in buckets} == {
        "bug_fix",
        "feature_implementation",
    }


def test_cross_root_and_duplicate_strata_fail_closed() -> None:
    first = _stratum("first", day=1)
    with pytest.raises(ValueError, match="root|scope"):
        _draft(first, _stratum("other-root", day=2, root_label="other"))
    with pytest.raises(ValueError, match="duplicate"):
        _draft(first, first)


def test_mixed_installation_scope_fails_closed() -> None:
    first = _stratum("installation-a", day=1)
    second = _stratum("installation-b", day=2)
    raw = second.model_dump(mode="python")
    prepared = raw["prepared_stratum"]
    dimensions = prepared["dimensions"]
    dimensions["installation_id"] = _digest("different-installation")
    # Rebuilding every dependent authority hash is deliberately unnecessary:
    # the persistence revalidation boundary must reject even this shallow
    # structurally forged cross-installation object before aggregation.
    forged = second.model_construct(**raw)
    with pytest.raises(ValueError):
        _draft(first, forged)


def test_cardinality_and_input_shape_fail_before_nested_access() -> None:
    from prompt_enhancer.application.history.aggregation import (
        MAX_SUPPLIED_STRATA,
        draft_synthetic_raw_aggregation,
    )

    first = _stratum("bounded", day=1)
    with pytest.raises(ValueError, match="immutable tuple"):
        draft_synthetic_raw_aggregation(
            anchor_scope=first.prepared_stratum.prepared_scope,
            metric_key=METRIC,
            window=_window(),
            as_of=AS_OF,
            strata=[first],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="too many"):
        _draft(*(first for _ in range(MAX_SUPPLIED_STRATA + 1)))


def test_nested_trust_flag_forgery_is_revalidated_and_rejected() -> None:
    first = _stratum("forged", day=1)
    forged = first.model_copy(update={"sealed": True})
    with pytest.raises(ValueError):
        _draft(forged)


def test_result_revalidation_rejects_manifest_and_derived_id_forgery() -> None:
    from prompt_enhancer.application.history.aggregation import (
        SyntheticRawAggregationDraftV1,
    )

    result = _draft(_stratum("manifest", day=1))
    forged_manifest = result.model_copy(
        update={"ordered_included_stratum_fingerprints": ()}
    )
    with pytest.raises(ValueError, match="manifest"):
        SyntheticRawAggregationDraftV1.revalidate_for_persistence(forged_manifest)
    forged_id = result.model_copy(update={"aggregation_draft_id": _digest("wrong")})
    with pytest.raises(ValueError, match="exact input manifest"):
        SyntheticRawAggregationDraftV1.revalidate_for_persistence(forged_id)


def test_future_seals_are_excluded_not_reinterpreted_as_missing() -> None:
    before = _stratum("visible", day=1, raw=(1, 2))
    after = _stratum("late", day=20, raw=(1, 1))
    result = _draft(before, after)
    assert result.supplied_strata_count == 2
    assert result.included_revision_count == 1
    assert result.excluded_late_seal_count == 1
    assert result.state_counts.supplied_revision_count == 1
    _, aggregate = _known_aggregate(result)
    assert aggregate.ratio == pytest.approx(0.5)


def test_custom_end_after_as_of_and_as_of_before_floor_fail_closed() -> None:
    first = _stratum("bad-time", day=1)
    with pytest.raises(ValueError, match="end.*as-of"):
        _draft(first, window=_window(start=FLOOR, end=AS_OF + timedelta(seconds=1)))
    from prompt_enhancer.application.history.aggregation import (
        draft_synthetic_raw_aggregation,
    )

    with pytest.raises(ValueError, match="as-of.*predate"):
        draft_synthetic_raw_aggregation(
            anchor_scope=first.prepared_stratum.prepared_scope,
            metric_key=METRIC,
            window=_window(),
            as_of=FLOOR - timedelta(microseconds=1),
            strata=(first,),
        )


def test_result_is_descriptive_untrusted_and_cannot_claim_a_match() -> None:
    result = _draft(_stratum("only", day=1))
    assert str(_field(result, "population_state")) == (
        "supplied_set_completeness_unknown"
    )
    assert all(
        str(bucket.match_readiness) == "insufficient_required_strata"
        for bucket in result.task_buckets
    )
    assert result.matched_estimate is None
    payload = result.model_dump(mode="python")
    authority_claims = (
        "repository_owned",
        "repository_verified",
        "source_authority_verified",
        "product_history_eligible",
        "pair_matching_allowed",
        "comparison_allowed",
        "aggregate_materialization_allowed",
        "snapshot_materialization_allowed",
        "recommendation_allowed",
        "causal_claim_allowed",
        "activation_allowed",
        "remote_processing_allowed",
        "private_export_allowed",
        "team_share_allowed",
    )
    assert all(payload[name] is False for name in authority_claims)
    assert payload["synthetic_test_only"] is True
