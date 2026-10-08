from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta
import inspect
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.history.aggregation import (
    MAX_SUPPLIED_STRATA,
    REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION,
    RawStratumDispositionV1,
    RepositoryBackedSyntheticRawAggregationDraftV2,
    draft_repository_sealed_synthetic_raw_aggregation,
)
from prompt_enhancer.application.history.contracts import (
    EvidenceCoverageEligibility,
    EvidenceCoverageState,
    TemporalSourceState,
    TemporalValueKind,
    TemporalValueState,
    TemporalWindowKind,
    TemporalWindowSpec,
)
from tests import test_temporal_aggregation as v1_aggregation
from tests import test_temporal_comparison_strata_contracts as base
from tests import test_temporal_comparison_strata_persistence_contracts as repo
from tests import test_temporal_comparison_strata_sqlite_persistence as sqlite_fixtures


AS_OF = base.PREPARED_AT + timedelta(minutes=10)


def _window(
    *,
    start=None,
    end=None,
    last_n: int | None = None,
) -> TemporalWindowSpec:
    if last_n is not None:
        return TemporalWindowSpec(kind=TemporalWindowKind.LAST_N, last_n=last_n)
    return TemporalWindowSpec(
        kind=TemporalWindowKind.CUSTOM,
        start_at=start or base.FLOOR,
        end_at=end or AS_OF,
    )


def _receipt(
    label: str,
    *,
    share_root: bool = True,
    share_installation: bool = True,
    varied_labels: frozenset[str] | None = None,
):
    original_id = base._id
    shared = {
        "metric-pack",
        "metric-catalog",
        "metric-definition",
        "metric-question",
        "estimator-plan",
        "not-calibrated",
        "preprocessing",
        "router",
        "redactor",
    }
    if share_root:
        shared.update({"history-root", "project"})
    if share_installation:
        shared.add("installation")

    def synthetic_id(role: str) -> str:
        if varied_labels is not None:
            return (
                original_id(f"{label}-{role}")
                if role in varied_labels
                else original_id(role)
            )
        return original_id(role) if role in shared else original_id(f"{label}-{role}")

    base._id = synthetic_id
    try:
        components = repo._prepared_components()
        components["expected_run_request"] = base._expected_run_request(
            components["analysis_job"],
            run_id=synthetic_id("analysis-run"),
        )
        prepared = repo._prepared_receipt(components=components)
        return repo._sealed_receipt(
            components=repo._sealed_components(prepared)
        )
    finally:
        base._id = original_id


def _typed_receipt(
    label: str,
    *,
    day: int,
    kind: TemporalValueKind,
    raw: tuple[int, int] | tuple[int, float] | float,
    identity_label: str = "parity",
    value_state: TemporalValueState = TemporalValueState.KNOWN,
    source_state: TemporalSourceState = TemporalSourceState.PRESENT,
    task_type: str | None = "bug_fix",
    evidence_eligibility: EvidenceCoverageEligibility | None = None,
    evidence_state: EvidenceCoverageState | None = None,
    evidence_numerator: int | None = None,
    evidence_denominator: int | None = None,
    selected_metric_key: str = base.METRIC,
):
    prepared_at = base.FLOOR + timedelta(days=day, minutes=2)
    original_id = base._id
    original_expected_run = base._expected_run_request

    def synthetic_id(role: str) -> str:
        if role in {"automation-grant", "prepared-scope", "selection"}:
            return v1_aggregation._digest(f"{role}:repository-v2-root")
        if role in {"history-root", "project"}:
            return v1_aggregation._digest(f"{role}:repository-v2-root")
        if role in v1_aggregation._SHARED_ID_ROLES:
            return original_id(role)
        return v1_aggregation._digest(f"repository-v2:{label}:{role}")

    def expected_run(job, *, run_id=None, issued_at=None):
        return original_expected_run(
            job,
            run_id=run_id or synthetic_id("analysis-run"),
            issued_at=issued_at or prepared_at,
        )

    observation_factory = v1_aggregation._observation_factory(
        kind=kind,
        raw=raw,
        value_state=value_state,
        source_state=source_state,
    )

    def observation_with_evidence(**values):
        observation = observation_factory(**values)
        if evidence_eligibility is None or evidence_state is None:
            return observation
        return type(observation).model_validate(
            observation.model_copy(
                update={
                    "evidence_coverage_eligibility": evidence_eligibility,
                    "evidence_coverage_state": evidence_state,
                    "evidence_numerator": evidence_numerator,
                    "evidence_denominator": evidence_denominator,
                }
            ).model_dump(mode="python")
        )

    with ExitStack() as stack:
        stack.enter_context(patch.object(base, "PREPARED_AT", prepared_at))
        stack.enter_context(patch.object(base, "METRIC", selected_metric_key))
        stack.enter_context(patch.object(base, "_id", synthetic_id))
        stack.enter_context(patch.object(base, "_expected_run_request", expected_run))
        stack.enter_context(
            patch.object(
                base,
                "_comparison_identity",
                v1_aggregation._identity_factory(
                    kind=kind, identity_label=identity_label
                ),
            )
        )
        stack.enter_context(
            patch.object(
                base,
                "TemporalMetricObservationV2",
                observation_with_evidence,
            )
        )
        components = repo._prepared_components(
            revisions=(
                ()
                if task_type is None
                else (base._task_revision(label, task_type=task_type),)
            )
        )
        prepared = repo._prepared_receipt(components=components)
        return repo._sealed_receipt(
            components=repo._sealed_components(prepared)
        )


def _draft(*strata, anchor=None, window=None, as_of=AS_OF):
    exact_anchor = anchor or strata[0].prepared_receipt
    return draft_repository_sealed_synthetic_raw_aggregation(
        anchor=exact_anchor,
        metric_key=base.METRIC,
        window=window or _window(),
        as_of=as_of,
        strata=tuple(strata),
    )


def _aggregate(result: RepositoryBackedSyntheticRawAggregationDraftV2):
    assert len(result.compatibility_runs) == 1
    run = result.compatibility_runs[0]
    assert len(run.task_buckets) == 1
    aggregate = run.task_buckets[0].aggregate_value
    assert aggregate is not None
    return aggregate


def test_public_api_is_keyword_only_and_truthfully_named() -> None:
    signature = inspect.signature(
        draft_repository_sealed_synthetic_raw_aggregation
    )
    assert tuple(signature.parameters) == (
        "anchor",
        "metric_key",
        "window",
        "as_of",
        "strata",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    assert (
        REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION
        == "repository-backed-synthetic-raw-aggregation-draft-v2"
    )
    assert "repository-sealed" not in (
        REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION
    )


def test_repository_receipts_produce_same_fraction_math_and_exact_manifest() -> None:
    first = _receipt("first")
    second = _receipt("second")
    result = _draft(second, first, anchor=first.prepared_receipt)

    aggregate = _aggregate(result)
    assert aggregate.numerator_sum == 2
    assert aggregate.denominator_sum == 2
    assert aggregate.ratio == 1.0
    assert result.included_revision_count == 2
    assert result.state_counts.value_known_count == 2
    assert tuple(
        item.supplied_ordinal for item in result.ordered_supplied_stratum_manifest
    ) == (0, 1)
    assert {
        item.sealed_stratum_id
        for item in result.ordered_supplied_stratum_manifest
    } == {first.sealed_stratum_id, second.sealed_stratum_id}
    for item in result.ordered_supplied_stratum_manifest:
        source = first if item.sealed_stratum_id == first.sealed_stratum_id else second
        revision = source.sealed_batch.seal_draft.session_revision
        assert item.prepared_stratum_id == source.prepared_receipt.prepared_stratum_id
        assert item.prepared_stratum_fingerprint == source.prepared_receipt.fingerprint
        assert item.sealed_stratum_fingerprint == source.fingerprint
        assert item.analysis_run_id == source.analysis_run.draft.run_id
        assert item.analysis_run_authority_sha256 == source.analysis_run_authority_sha256
        assert item.sealed_batch_id == source.sealed_batch.sealed_batch_id
        assert item.sealed_batch_sha256 == source.sealed_batch_sha256
        assert item.revision_id == revision.revision_id
        assert item.revision_fingerprint == revision.fingerprint


def test_actual_v22_repository_returned_receipt_reduces(tmp_path) -> None:
    context = sqlite_fixtures._comparison_completion(tmp_path)
    batch = context.runs.complete(
        context.prepared.expected_analysis_run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.temporal_request,
    )
    assert batch is not None
    sealed = context.comparison.get_sealed_stratum_for_run(
        context.prepared.expected_analysis_run_id
    )
    assert sealed is not None

    result = draft_repository_sealed_synthetic_raw_aggregation(
        anchor=context.prepared,
        metric_key=context.metric_key,
        window=TemporalWindowSpec(kind=TemporalWindowKind.LAST_N, last_n=1),
        as_of=sealed.sealed_at,
        strata=(sealed,),
    )

    aggregate = _aggregate(result)
    assert aggregate.numerator_sum == 1
    assert aggregate.denominator_sum == 2
    assert aggregate.ratio == 0.5
    assert result.ordered_supplied_stratum_manifest[0].sealed_stratum_id == (
        sealed.sealed_stratum_id
    )


@pytest.mark.parametrize(
    ("kind", "first_raw", "second_raw"),
    (
        (TemporalValueKind.FRACTION, (1, 2), (2, 8)),
        (TemporalValueKind.COUNT_WITH_EXPOSURE, (2, 4.0), (3, 6.0)),
        (TemporalValueKind.DISTRIBUTION_SAMPLE, 1.0, 3.0),
        (TemporalValueKind.SAMPLED_PROPORTION, (1, 2), (2, 4)),
    ),
)
def test_all_four_typed_math_paths_match_v1_kernel(
    kind: TemporalValueKind,
    first_raw: tuple[int, int] | tuple[int, float] | float,
    second_raw: tuple[int, int] | tuple[int, float] | float,
) -> None:
    first = _typed_receipt(
        f"{kind.value}-first", day=1, kind=kind, raw=first_raw
    )
    second = _typed_receipt(
        f"{kind.value}-second", day=2, kind=kind, raw=second_raw
    )
    v2 = _draft(
        first,
        second,
        anchor=first.prepared_receipt,
        as_of=v1_aggregation.AS_OF,
        window=v1_aggregation._window(),
    )
    v1 = v1_aggregation._draft(
        v1_aggregation._stratum(
            f"v1-{kind.value}-first", day=1, kind=kind, raw=first_raw,
            identity_label="parity",
        ),
        v1_aggregation._stratum(
            f"v1-{kind.value}-second", day=2, kind=kind, raw=second_raw,
            identity_label="parity",
        ),
    )

    assert _aggregate(v2).model_dump(mode="python") == (
        v1_aggregation._known_aggregate(v1)[1].model_dump(mode="python")
    )
    assert v2.state_counts == v1.state_counts


def test_supplied_order_is_canonical_and_input_permutation_invariant() -> None:
    first = _receipt("permutation-first")
    second = _receipt("permutation-second")
    left = _draft(first, second, anchor=first.prepared_receipt)
    right = _draft(second, first, anchor=first.prepared_receipt)

    assert left == right
    assert left.fingerprint == right.fingerprint
    assert left.aggregation_draft_id == right.aggregation_draft_id


def test_a_b_a_identities_remain_three_contiguous_runs() -> None:
    strata = tuple(
        _typed_receipt(
            f"identity-{identity}-{day}",
            day=day,
            kind=TemporalValueKind.FRACTION,
            raw=(1, 1),
            identity_label=identity,
        )
        for day, identity in ((1, "a"), (2, "b"), (3, "a"))
    )
    result = _draft(
        *strata,
        anchor=strata[0].prepared_receipt,
        as_of=v1_aggregation.AS_OF,
        window=v1_aggregation._window(),
    )

    assert len(result.compatibility_runs) == 3
    assert result.compatibility_runs[0].comparison_identity_fingerprint == (
        result.compatibility_runs[2].comparison_identity_fingerprint
    )
    assert result.compatibility_runs[0].comparison_identity_fingerprint != (
        result.compatibility_runs[1].comparison_identity_fingerprint
    )
    assert len(result.compatibility_transitions) == 2


def test_unselected_metric_keeps_missingness_and_identity_gap_visible() -> None:
    receipt = _receipt("identity-unavailable")
    result = draft_repository_sealed_synthetic_raw_aggregation(
        anchor=receipt.prepared_receipt,
        metric_key="reserved.absent.metric",
        window=_window(),
        as_of=AS_OF,
        strata=(receipt,),
    )

    assert result.state_counts.not_selected_count == 1
    assert result.state_counts.source_not_requested_count == 1
    assert result.state_counts.value_unknown_count == 1
    assert result.state_counts.identity_unavailable_count == 1
    assert result.leading_identity_unavailable_count == 1
    assert result.compatibility_runs == ()


def test_identity_unavailable_between_known_runs_is_an_exact_gap_transition() -> None:
    first = _typed_receipt(
        "gap-first",
        day=1,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 1),
        identity_label="same",
    )
    middle = _typed_receipt(
        "gap-middle",
        day=2,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 1),
        identity_label="same",
        selected_metric_key=COACHING_METRIC_DEFINITIONS[1].key,
    )
    last = _typed_receipt(
        "gap-last",
        day=3,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 1),
        identity_label="same",
    )
    result = draft_repository_sealed_synthetic_raw_aggregation(
        anchor=first.prepared_receipt,
        metric_key=base.METRIC,
        window=v1_aggregation._window(),
        as_of=v1_aggregation.AS_OF,
        strata=(first, middle, last),
    )
    assert len(result.compatibility_runs) == 2
    assert len(result.compatibility_transitions) == 1
    transition = result.compatibility_transitions[0]
    assert transition.kind.value == "identity_unavailable_gap"
    assert transition.identity_unavailable_gap_count == 1
    assert transition.dimensions == ()
    assert result.leading_identity_unavailable_count == 0
    assert result.trailing_identity_unavailable_count == 0


def test_every_missing_source_and_value_state_remains_distinct() -> None:
    specs = (
        ("known", TemporalSourceState.PRESENT, TemporalValueState.KNOWN),
        ("unknown", TemporalSourceState.PRESENT, TemporalValueState.UNKNOWN),
        ("abstained", TemporalSourceState.PRESENT, TemporalValueState.ABSTAINED),
        (
            "not-applicable",
            TemporalSourceState.PRESENT,
            TemporalValueState.NOT_APPLICABLE,
        ),
        (
            "missing",
            TemporalSourceState.SOURCE_MISSING,
            TemporalValueState.UNKNOWN,
        ),
        (
            "failed",
            TemporalSourceState.SOURCE_FAILED,
            TemporalValueState.FAILED,
        ),
        (
            "incompatible",
            TemporalSourceState.SOURCE_INCOMPATIBLE,
            TemporalValueState.INCOMPATIBLE,
        ),
    )
    strata = tuple(
        _typed_receipt(
            label,
            day=day,
            kind=TemporalValueKind.FRACTION,
            raw=(1, 2),
            value_state=value_state,
            source_state=source_state,
        )
        for day, (label, source_state, value_state) in enumerate(specs, start=1)
    )
    result = _draft(
        *strata,
        anchor=strata[0].prepared_receipt,
        as_of=v1_aggregation.AS_OF,
        window=v1_aggregation._window(),
    )
    counts = result.state_counts

    assert counts.value_known_count == 1
    assert counts.value_unknown_count == 2
    assert counts.value_abstained_count == 1
    assert counts.value_not_applicable_count == 1
    assert counts.value_failed_count == 1
    assert counts.value_incompatible_count == 1
    assert counts.source_missing_count == 1
    assert counts.source_failed_count == 1
    assert counts.source_incompatible_count == 1
    aggregate = _aggregate(result)
    assert aggregate.numerator_sum == 1
    assert aggregate.denominator_sum == 2


def test_evidence_zero_over_zero_unknown_and_not_applicable_stay_distinct() -> None:
    known = _typed_receipt(
        "evidence-known",
        day=1,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 1),
    )
    missing = _typed_receipt(
        "evidence-unknown",
        day=2,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 1),
        value_state=TemporalValueState.UNKNOWN,
        source_state=TemporalSourceState.SOURCE_MISSING,
    )
    not_applicable = _typed_receipt(
        "evidence-not-applicable",
        day=3,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 1),
        evidence_eligibility=EvidenceCoverageEligibility.NOT_ELIGIBLE,
        evidence_state=EvidenceCoverageState.NOT_APPLICABLE,
    )
    result = _draft(
        known,
        missing,
        not_applicable,
        anchor=known.prepared_receipt,
        as_of=v1_aggregation.AS_OF,
        window=v1_aggregation._window(),
    )

    coverage = result.compatibility_runs[0].task_buckets[0].evidence_coverage
    assert coverage.known_eligible_observation_count == 1
    assert coverage.numerator_sum == 0
    assert coverage.denominator_sum == 0
    assert coverage.ratio is None
    assert result.state_counts.evidence_coverage_known_count == 1
    assert result.state_counts.evidence_coverage_unknown_count == 1
    assert result.state_counts.evidence_coverage_not_applicable_count == 1
    assert result.state_counts.evidence_not_eligible_count == 1
    assert result.state_counts.evidence_eligibility_unknown_count == 1


def test_reviewed_and_unknown_task_buckets_never_pool() -> None:
    reviewed = _typed_receipt(
        "reviewed-task",
        day=1,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 2),
        task_type="bug_fix",
    )
    unknown = _typed_receipt(
        "unknown-task",
        day=2,
        kind=TemporalValueKind.FRACTION,
        raw=(1, 4),
        task_type=None,
    )
    result = _draft(
        reviewed,
        unknown,
        anchor=reviewed.prepared_receipt,
        as_of=v1_aggregation.AS_OF,
        window=v1_aggregation._window(),
    )

    assert len(result.task_buckets) == 2
    assert result.matched_estimate is None
    assert result.matched_pair_count is None


def test_empty_supplied_set_retains_exact_anchor_scope() -> None:
    anchor = _receipt("empty-anchor").prepared_receipt
    result = _draft(anchor=anchor)

    assert result.supplied_strata_count == 0
    assert result.included_revision_count == 0
    assert result.installation_id == anchor.dimensions.installation_id
    assert result.project_id == anchor.dimensions.project_id
    assert result.provider is anchor.dimensions.provider
    assert result.root_receipt_id == anchor.prepared_scope.history_root.root_receipt_id
    assert result.ordered_supplied_stratum_manifest == ()
    assert result.compatibility_runs == ()
    assert result.task_buckets == ()


def test_last_n_and_window_exclusions_remain_supplied_set_descriptives() -> None:
    first = _receipt("last-n-first")
    second = _receipt("last-n-second")
    result = _draft(
        first,
        second,
        anchor=first.prepared_receipt,
        window=_window(last_n=1),
    )

    assert result.included_revision_count == 1
    assert result.excluded_outside_window_count == 1
    assert result.excluded_late_seal_count == 0
    assert sorted(
        item.disposition for item in result.ordered_supplied_stratum_manifest
    ) == sorted(
        (
            RawStratumDispositionV1.INCLUDED,
            RawStratumDispositionV1.OUTSIDE_WINDOW,
        )
    )


def test_late_receipt_is_not_reclassified_as_future_or_outside() -> None:
    receipt = _receipt("late")
    result = _draft(
        receipt,
        as_of=receipt.sealed_at - timedelta(microseconds=1),
        window=_window(end=receipt.sealed_at - timedelta(microseconds=1)),
    )

    assert result.included_revision_count == 0
    assert result.excluded_late_seal_count == 1
    assert result.excluded_outside_window_count == 0
    assert result.ordered_supplied_stratum_manifest[0].disposition is (
        RawStratumDispositionV1.LATE_SEAL
    )


def test_cross_root_and_cross_installation_receipts_reject() -> None:
    anchor = _receipt("scope-anchor")
    cross_root = _receipt(
        "cross-root", share_root=False, share_installation=False
    )
    cross_installation = _receipt(
        "cross-installation", share_root=True, share_installation=False
    )

    with pytest.raises(ValueError, match="anchor root"):
        _draft(cross_root, anchor=anchor.prepared_receipt)
    with pytest.raises(ValueError, match="anchor source scope"):
        _draft(cross_installation, anchor=anchor.prepared_receipt)


def test_duplicate_repository_receipt_rejects_before_reduction() -> None:
    receipt = _receipt("duplicate-receipt")
    with pytest.raises(ValueError, match="duplicate prepared"):
        _draft(receipt, receipt)


@pytest.mark.parametrize(
    ("role", "field"),
    (
        ("prepared", "prepared_stratum_id"),
        ("sealed", "sealed_stratum_id"),
        ("run", "analysis_run_id"),
        ("batch", "sealed_batch_id"),
        ("revision", "revision_id"),
    ),
)
def test_persisted_manifest_rejects_each_duplicate_graph_role(
    role: str, field: str
) -> None:
    first = _receipt(f"manifest-{role}-first")
    second = _receipt(f"manifest-{role}-second")
    result = _draft(first, second, anchor=first.prepared_receipt)
    left, right = result.ordered_supplied_stratum_manifest
    duplicate = right.model_copy(update={field: getattr(left, field)})
    attack = result.model_copy(
        update={"ordered_supplied_stratum_manifest": (left, duplicate)}
    )
    with pytest.raises(ValidationError, match=f"duplicate {role}"):
        RepositoryBackedSyntheticRawAggregationDraftV2.revalidate_for_persistence(
            attack
        )


def test_persisted_manifest_rejects_duplicate_session_revision_coordinate() -> None:
    first = _receipt("coordinate-first")
    second = _receipt("coordinate-second")
    result = _draft(first, second, anchor=first.prepared_receipt)
    left, right = result.ordered_supplied_stratum_manifest
    duplicate = right.model_copy(
        update={
            "session_id": left.session_id,
            "revision_ordinal": left.revision_ordinal,
        }
    )
    attack = result.model_copy(
        update={"ordered_supplied_stratum_manifest": (left, duplicate)}
    )
    with pytest.raises(ValidationError, match="duplicate revision coordinate"):
        RepositoryBackedSyntheticRawAggregationDraftV2.revalidate_for_persistence(
            attack
        )


def test_non_repository_shapes_and_mutable_collections_reject() -> None:
    receipt = _receipt("shape")
    v1 = base._seal_draft()

    with pytest.raises(ValueError, match="immutable tuple"):
        draft_repository_sealed_synthetic_raw_aggregation(
            anchor=receipt.prepared_receipt,
            metric_key=base.METRIC,
            window=_window(),
            as_of=AS_OF,
            strata=[receipt],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="repository sealed receipts"):
        _draft(v1, anchor=receipt.prepared_receipt)
    with pytest.raises(ValueError, match="repository sealed receipts"):
        _draft(receipt.prepared_receipt, anchor=receipt.prepared_receipt)


def test_cardinality_fails_before_nested_receipt_access() -> None:
    class Poison:
        def __getattribute__(self, name: str):
            raise AssertionError("nested receipt was accessed")

    with pytest.raises(ValueError, match="too many supplied"):
        draft_repository_sealed_synthetic_raw_aggregation(
            anchor=Poison(),  # type: ignore[arg-type]
            metric_key=base.METRIC,
            window=_window(),
            as_of=AS_OF,
            strata=tuple(  # type: ignore[arg-type]
                Poison() for _ in range(MAX_SUPPLIED_STRATA + 1)
            ),
        )


def test_recursive_input_and_output_tampering_rejects() -> None:
    receipt = _receipt("tamper")
    forged_input = receipt.model_copy(update={"source_authority_verified": True})
    with pytest.raises(ValidationError):
        _draft(forged_input, anchor=receipt.prepared_receipt)
    altered_run_draft = receipt.analysis_run.draft.model_copy(
        update={"input_fingerprint": base._id("altered-run-input")}
    )
    altered_run = receipt.analysis_run.model_copy(
        update={"draft": altered_run_draft}
    )
    altered_lineage = receipt.model_copy(update={"analysis_run": altered_run})
    with pytest.raises(ValidationError):
        _draft(altered_lineage, anchor=receipt.prepared_receipt)

    result = _draft(receipt)
    forged_manifest = result.ordered_supplied_stratum_manifest[0].model_copy(
        update={"sealed_batch_sha256": base._id("forged-batch")}
    )
    attacks = (
        result.model_copy(update={"repository_owned": True}),
        result.model_copy(update={"sealed": True}),
        result.model_copy(update={"aggregation_draft_id": base._id("forged-result")}),
        result.model_copy(update={"ordered_supplied_stratum_manifest": (forged_manifest,)}),
    )
    for attack in attacks:
        with pytest.raises(ValidationError):
            RepositoryBackedSyntheticRawAggregationDraftV2.revalidate_for_persistence(
                attack
            )


def test_authority_only_graph_change_moves_identity_with_same_numeric_value() -> None:
    varied = frozenset(
        {
            "analysis-job",
            "analysis-job-dedupe",
            "lease-owner-base",
            "lease-token-base",
            "expected-run-receipt",
            "automation-revalidation-receipt",
            "repository-revalidation-authority",
        }
    )
    first = _receipt("authority-first", varied_labels=varied)
    second = _receipt("authority-second", varied_labels=varied)
    left = _draft(first)
    right = _draft(second, anchor=second.prepared_receipt)

    assert _aggregate(left).ratio == _aggregate(right).ratio == 1.0
    assert left.included_revision_count == right.included_revision_count == 1
    assert left.aggregation_draft_id != right.aggregation_draft_id
    assert left.fingerprint != right.fingerprint


def test_capability_ceiling_and_serialization_are_explicit() -> None:
    result = _draft(_receipt("capability"))
    true_flags = {
        "structurally_constructible_not_capability",
        "synthetic_test_only",
        "supplied_set_only",
        "input_receipt_structure_revalidated",
        "repository_verification_required",
    }
    for name in type(result).model_fields:
        if isinstance(getattr(result, name), bool):
            assert getattr(result, name) is (name in true_flags)
    assert result.matched_estimate is None
    assert result.matched_pair_count is None
    serialized = result.model_dump_json()
    for forbidden in (
        "lease_owner",
        "lease_token",
        "completion_request_id",
        "selected_window_manifest_root",
        "repository_path",
        "file://",
        "https://",
        "@example",
    ):
        assert forbidden not in serialized
    assert RepositoryBackedSyntheticRawAggregationDraftV2.revalidate_for_persistence(
        result
    ) == result
