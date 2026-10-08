"""Synthetic tests for the content-free V2 metric guidance contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
    metric_contract_v2,
)
from prompt_enhancer.application.analysis.metric_guidance import (
    METRIC_GUIDANCE_CONTRACT_VERSION,
    MAX_GUIDANCE_FOCUS_FACTOR_KEYS,
    METRIC_GUIDANCE_RETAIN_FLOOR,
    METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION,
    GuidanceAudience,
    GuidanceBasis,
    GuidanceRole,
    GuidanceFactorEvidence,
    GuidanceStateClass,
    MetricGuidanceReceipt,
    ValueOrigin,
    build_metric_guidance,
    metric_guidance_catalog,
    metric_guidance_template_set,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    MetricStateV2,
    OpportunityStatistics,
    resolve_metric_state,
)
from prompt_enhancer.application.analysis.text_contracts import MetricDirection


CANARY = "SYNTHETIC-PRIVATE-SESSION-TEXT-CANARY"
EXAMPLE_PSEUDONYM = "a" * 64


def _statistics(metric_key: str, **counts: int) -> OpportunityStatistics:
    contract = metric_contract_v2(metric_key)
    eligible = counts.get("eligible_count", 0)
    return OpportunityStatistics(
        metric_key=metric_key,
        denominator_basis=contract.denominator_basis,
        opportunity_unit_kind=contract.opportunity_unit_kind,
        capability_available=True,
        source_complete=True,
        eligible_count=eligible,
        met_count=counts.get("met_count", 0),
        not_met_count=counts.get("not_met_count", 0),
        pending_count=counts.get("pending_count", 0),
        unknown_count=counts.get("unknown_count", 0),
        # A semantic-unit denominator is exactly one owned opportunity per head.
        distinct_owner_count=(
            eligible
            if contract.denominator_basis
            is DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES
            else 0
        ),
    )


def _known_state(metric_key: str, *, met: int, eligible: int) -> MetricStateV2:
    contract = metric_contract_v2(metric_key)
    ratio = met / eligible
    return MetricStateV2(
        metric_key=metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.KNOWN,
        explanation_code="rubric_factors",
        numerator=met,
        denominator=eligible,
        numeric_value=ratio,
        censoring_lower_bound=ratio,
        censoring_upper_bound=ratio,
        statistics=_statistics(
            metric_key,
            eligible_count=eligible,
            met_count=met,
            not_met_count=eligible - met,
        ),
        projection_version="metric-contract-v2-projection-2",
    )


def test_guidance_catalog_covers_every_v2_metric_and_state_class() -> None:
    catalog = metric_guidance_catalog()

    assert len(catalog) == len(METRIC_CONTRACTS_V2) == 20
    assert tuple(entry.metric_key for entry in catalog) == tuple(
        contract.metric_key for contract in METRIC_CONTRACTS_V2
    )
    for entry in catalog:
        contract = metric_contract_v2(entry.metric_key)
        assert entry.contract_fingerprint == contract.fingerprint
        assert entry.contract_factor_keys == tuple(
            item.factor_key for item in contract.factors
        )
        assert {item.state_class for item in entry.templates} == set(
            GuidanceStateClass
        )
        # Template identities are catalog codes, never wording.
        for template in entry.templates:
            for identity in (
                template.diagnosis_template_id,
                template.action_template_id,
                template.verification_template_id,
            ):
                assert " " not in identity
                assert identity.endswith(".v1")


def test_catalog_roles_and_audiences_follow_the_contract_not_the_key_prefix() -> None:
    by_key = {entry.metric_key: entry for entry in metric_guidance_catalog()}

    assert by_key["collaboration.rework_candidate_rate"].role is (
        GuidanceRole.FRICTION_SIGNAL
    )
    assert by_key["collaboration.clarification_yield"].role is (
        GuidanceRole.COLLABORATION_SIGNAL
    )
    assert by_key["prompt.context_sufficiency"].audience is GuidanceAudience.USER
    assert by_key["logic.decision_rationale_coverage"].audience is (
        GuidanceAudience.AGENT
    )
    objective_keys = {
        contract.metric_key
        for contract in METRIC_CONTRACTS_V2
        if contract.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
    }
    assert len(objective_keys) == 5
    for metric_key in objective_keys:
        # No wording can satisfy a receipt, so the guidance is tooling-directed.
        assert by_key[metric_key].audience is GuidanceAudience.TOOLING


def test_deterministic_local_value_is_measured_not_experimental() -> None:
    guidance = build_metric_guidance(
        _known_state("prompt.task_definition_coverage", met=3, eligible=3)
    )

    assert guidance.value_state is MetricValueStateV2.KNOWN
    assert guidance.basis is GuidanceBasis.MEASURED
    assert guidance.value_origin is ValueOrigin.DETERMINISTIC_LOCAL
    assert guidance.state_class is GuidanceStateClass.KNOWN_RETAIN
    assert guidance.numerator == 3 and guidance.denominator == 3
    assert guidance.contract_version == METRIC_GUIDANCE_CONTRACT_VERSION
    assert guidance.template_catalog_version == (
        METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION
    )
    assert guidance.action_template_id == (
        "action.retain.prompt.task_definition_coverage.v1"
    )
    assert guidance.product_metric_eligible is False


def test_retain_floor_selects_retain_or_improve_by_oriented_value() -> None:
    strong = build_metric_guidance(
        _known_state("prompt.context_sufficiency", met=3, eligible=3)
    )
    weak = build_metric_guidance(
        _known_state("prompt.context_sufficiency", met=1, eligible=3)
    )

    assert 1 / 3 < METRIC_GUIDANCE_RETAIN_FLOOR <= 1.0
    assert strong.state_class is GuidanceStateClass.KNOWN_RETAIN
    assert weak.state_class is GuidanceStateClass.KNOWN_IMPROVE
    assert weak.action_template_id == (
        "action.improve.prompt.context_sufficiency.v1"
    )
    assert weak.focus_factor_keys == ()
    assert weak.contract_factor_count == len(
        metric_contract_v2("prompt.context_sufficiency").factors
    )


def test_exact_retain_floor_is_server_owned_and_inclusive() -> None:
    at_floor = build_metric_guidance(
        _known_state("prompt.context_sufficiency", met=3, eligible=4)
    )
    below_floor = build_metric_guidance(
        _known_state("prompt.context_sufficiency", met=2, eligible=3)
    )

    assert METRIC_GUIDANCE_RETAIN_FLOOR == 0.75
    assert (at_floor.numerator, at_floor.denominator) == (3, 4)
    assert at_floor.state_class is GuidanceStateClass.KNOWN_RETAIN
    assert below_floor.state_class is GuidanceStateClass.KNOWN_IMPROVE


def test_lower_is_better_metric_orients_before_choosing_a_template() -> None:
    definition = next(
        item
        for item in COACHING_METRIC_DEFINITIONS
        if item.key == "collaboration.rework_candidate_rate"
    )
    assert definition.direction is MetricDirection.LOWER_IS_BETTER

    low_rework = build_metric_guidance(
        _known_state("collaboration.rework_candidate_rate", met=0, eligible=4)
    )
    high_rework = build_metric_guidance(
        _known_state("collaboration.rework_candidate_rate", met=4, eligible=4)
    )

    assert low_rework.state_class is GuidanceStateClass.KNOWN_RETAIN
    assert high_rework.state_class is GuidanceStateClass.KNOWN_IMPROVE


def test_unknown_objective_metric_asks_for_a_receipt_not_for_better_prose() -> None:
    contract = metric_contract_v2("outcome.first_pass_verification")
    state = resolve_metric_state(
        contract,
        OpportunityStatistics(
            metric_key=contract.metric_key,
            denominator_basis=contract.denominator_basis,
            capability_available=False,
            source_complete=False,
            eligible_count=0,
        ),
        explanation_code="typed_objective_absent",
        unavailable_code="typed_objective_absent",
    )

    guidance = build_metric_guidance(state)

    assert guidance.value_state is MetricValueStateV2.UNKNOWN
    assert guidance.basis is GuidanceBasis.READINESS
    assert guidance.audience is GuidanceAudience.TOOLING
    assert guidance.state_class is (
        GuidanceStateClass.OBJECTIVE_EVIDENCE_MISSING
    )
    assert guidance.action_template_id == "action.collect_objective_receipt.v1"
    assert guidance.numerator is None and guidance.denominator is None
    # Missing evidence must never read as a measured zero.
    assert guidance.eligible_count == 0 and guidance.met_count == 0


def test_pending_and_not_applicable_states_are_distinct_readiness_guidance() -> None:
    contract = metric_contract_v2("collaboration.ambiguity_resolution")
    pending = resolve_metric_state(
        contract,
        OpportunityStatistics(
            metric_key=contract.metric_key,
            denominator_basis=contract.denominator_basis,
            opportunity_unit_kind=contract.opportunity_unit_kind,
            capability_available=True,
            source_complete=True,
            eligible_count=2,
            met_count=1,
            pending_count=1,
            distinct_owner_count=2,
        ),
        explanation_code="ambiguity_episodes",
    )
    empty = resolve_metric_state(
        contract,
        OpportunityStatistics(
            metric_key=contract.metric_key,
            denominator_basis=contract.denominator_basis,
            opportunity_unit_kind=contract.opportunity_unit_kind,
            capability_available=True,
            source_complete=True,
            eligible_count=0,
        ),
        explanation_code="ambiguity_episodes",
    )

    pending_guidance = build_metric_guidance(pending)
    empty_guidance = build_metric_guidance(empty)

    assert pending_guidance.state_class is GuidanceStateClass.PENDING_CLOSURE
    assert pending_guidance.pending_count == 1
    assert pending_guidance.censoring_lower_bound == 0.5
    assert pending_guidance.censoring_upper_bound == 1.0
    assert empty_guidance.state_class is GuidanceStateClass.NO_OPPORTUNITY
    assert empty_guidance.action_template_id == "action.no_change_required.v1"
    assert pending_guidance.action_template_id != (
        empty_guidance.action_template_id
    )


def test_execution_error_guidance_is_tooling_only_with_no_value_basis() -> None:
    contract = metric_contract_v2("prompt.problem_evidence_quality")
    state = MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.EXECUTION_ERROR,
        explanation_code="model_committee_nli_failed",
        statistics=OpportunityStatistics(
            metric_key=contract.metric_key,
            denominator_basis=contract.denominator_basis,
            opportunity_unit_kind=contract.opportunity_unit_kind,
            capability_available=False,
            source_complete=False,
            eligible_count=0,
        ),
        projection_version="metric-contract-v2-projection-2",
    )

    guidance = build_metric_guidance(state)

    assert guidance.state_class is GuidanceStateClass.ANALYSIS_FAILED
    assert guidance.audience is GuidanceAudience.TOOLING
    assert guidance.basis is GuidanceBasis.METHOD_ONLY
    # The optional local model's fixed reason code survives the projection.
    assert guidance.reason_code == "model_committee_nli_failed"
    assert guidance.action_template_id == (
        "action.repair_local_analysis_stage.v1"
    )


def test_guidance_is_deterministic_and_language_independent() -> None:
    first = build_metric_guidance(
        _known_state("prompt.task_definition_coverage", met=2, eligible=3)
    )
    second = build_metric_guidance(
        _known_state("prompt.task_definition_coverage", met=2, eligible=3)
    )

    assert first == second
    # The receipt has no language field at all, so an EN and a PL session with
    # the same typed state cannot produce different guidance identities.
    assert "language" not in first.model_dump()


def test_template_set_matches_the_receipt_for_every_metric_and_state() -> None:
    for contract in METRIC_CONTRACTS_V2:
        for state_class in GuidanceStateClass:
            template = metric_guidance_template_set(
                contract.metric_key, state_class
            )
            assert template.state_class is state_class
            assert template.diagnosis_template_id == (
                f"diagnosis.{contract.metric_key}.v1"
            )


def test_guidance_receipt_rejects_prose_identifiers_and_masked_zeroes() -> None:
    valid = build_metric_guidance(
        _known_state("prompt.task_definition_coverage", met=3, eligible=3)
    ).model_dump()

    with pytest.raises(ValidationError) as error:
        MetricGuidanceReceipt(**{**valid, "reason_code": CANARY})
    assert CANARY not in str(error.value)

    with pytest.raises(ValidationError, match="content-free"):
        MetricGuidanceReceipt(**{**valid, "reason_code": EXAMPLE_PSEUDONYM})

    with pytest.raises(ValidationError, match="content-free"):
        MetricGuidanceReceipt(
            **{**valid, "action_template_id": "Try adding a target next time."}
        )

    with pytest.raises(ValidationError, match="value-bearing basis"):
        MetricGuidanceReceipt(
            **{
                **valid,
                "value_state": MetricValueStateV2.UNKNOWN,
                "state_class": GuidanceStateClass.EVIDENCE_UNRESOLVED,
                "numerator": None,
                "denominator": None,
                "censoring_lower_bound": None,
                "censoring_upper_bound": None,
            }
        )

    # Only an uncalibrated neural estimate may claim the experimental basis.
    with pytest.raises(ValidationError, match="neural estimate"):
        MetricGuidanceReceipt(**{**valid, "basis": GuidanceBasis.EXPERIMENTAL})

    # A conversational contract can never claim a typed objective origin.
    with pytest.raises(ValidationError, match="evidence authority"):
        MetricGuidanceReceipt(
            **{**valid, "value_origin": ValueOrigin.TYPED_OBJECTIVE}
        )

    # Focus factors require measured per-factor statistics.
    with pytest.raises(ValidationError, match="per-factor statistics"):
        MetricGuidanceReceipt(**{**valid, "focus_factor_keys": ("action",)})

    with pytest.raises(ValidationError, match="partition"):
        MetricGuidanceReceipt(**{**valid, "not_met_count": 4})

    with pytest.raises(ValidationError):
        MetricGuidanceReceipt(**{**valid, "product_metric_eligible": True})


def test_guidance_rejects_a_state_whose_contract_fingerprint_drifted() -> None:
    state = _known_state("prompt.context_sufficiency", met=3, eligible=3)
    drifted = state.model_copy(update={"contract_fingerprint": "b" * 64})

    with pytest.raises(ValueError, match="contract fingerprint"):
        build_metric_guidance(drifted)


def test_guidance_serialization_carries_no_free_text_field() -> None:
    payload = build_metric_guidance(
        _known_state("prompt.task_definition_coverage", met=1, eligible=3)
    ).model_dump_json()

    lowered = payload.casefold()
    for prohibited in (
        "prompt_text",
        "excerpt",
        "filesystem_path",
        "raw_content",
        "rationale",
        "description",
    ):
        assert prohibited not in lowered


def test_focus_factors_are_bounded_and_require_per_factor_evidence() -> None:
    contract = metric_contract_v2("prompt.task_definition_coverage")
    keys = tuple(item.factor_key for item in contract.factors)
    state = _known_state("prompt.task_definition_coverage", met=1, eligible=3)

    guidance = build_metric_guidance(
        state,
        factor_evidence=GuidanceFactorEvidence.PER_FACTOR_MEASURED,
        focus_factor_keys=keys,
    )

    assert MAX_GUIDANCE_FOCUS_FACTOR_KEYS == 2
    assert guidance.focus_factor_keys == keys[:2]
    assert guidance.basis is GuidanceBasis.MEASURED

    aggregate = build_metric_guidance(
        state, factor_evidence=GuidanceFactorEvidence.AGGREGATE_ONLY
    )
    assert aggregate.focus_factor_keys == ()
    assert aggregate.basis is GuidanceBasis.METHOD_ONLY

    with pytest.raises(ValueError, match="contract factor list"):
        build_metric_guidance(
            state,
            factor_evidence=GuidanceFactorEvidence.PER_FACTOR_MEASURED,
            focus_factor_keys=("not_a_contract_factor",),
        )


def test_uncalibrated_neural_estimate_is_the_only_experimental_basis() -> None:
    state = _known_state("prompt.context_sufficiency", met=3, eligible=3)

    neural = build_metric_guidance(
        state, value_origin=ValueOrigin.NEURAL_UNCALIBRATED
    )
    deterministic = build_metric_guidance(state)

    assert neural.basis is GuidanceBasis.EXPERIMENTAL
    assert neural.value_origin is ValueOrigin.NEURAL_UNCALIBRATED
    assert deterministic.basis is GuidanceBasis.MEASURED
    assert deterministic.value_origin is ValueOrigin.DETERMINISTIC_LOCAL
