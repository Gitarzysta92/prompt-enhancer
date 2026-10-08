from __future__ import annotations

import pytest

from test_metric_projection_v7 import IDS, _context, _plan_snapshot

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    MetricValueStateV2,
)
from prompt_enhancer.application.analysis.metric_projection_v8 import (
    METRIC_PROJECTION_V8_VERSION,
    project_metric_states_v8,
)
from prompt_enhancer.application.analysis.metric_projection_v7 import (
    project_metric_states_v7,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    project_objective_metric_overrides_v4,
)
from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    RequirementAcceptanceOutcome,
    RequirementVerificationMethod,
    RequirementVerificationOutcome,
    issue_explicit_requirement_acceptance,
    issue_requirement_verification_evidence_set,
    issue_requirement_verification_opportunities,
    issue_requirement_verification_result,
)


def _verified_state(states):  # type: ignore[no-untyped-def]
    return next(
        state
        for state in states
        if state.metric_key == "outcome.verified_requirement_coverage"
    )


def _project_verified(plan, evidence=None):  # type: ignore[no-untyped-def]
    context = _context()
    overrides = project_objective_metric_overrides_v4(
        None,
        None,
        requirement_plan_evidence=plan,
        requirement_verification_evidence=evidence,
        identifiers=IDS,
    )
    return _verified_state(
        project_metric_states_v8(
            context=context,
            reconciliation=None,
            id_factory=IDS,
            objective_overrides=overrides,
            requirement_plan_evidence=plan,
        )
    )


def test_r8_rejects_a_missing_verified_requirement_v4_override() -> None:
    context = _context()

    with pytest.raises(
        ValueError,
        match="requires the verified-requirement objective-v4 override",
    ):
        project_metric_states_v8(
            context=context,
            reconciliation=None,
            id_factory=IDS,
            objective_overrides={},
        )


def test_r8_truth_table_missing_empty_awaiting_and_overflow() -> None:
    context = _context()

    missing = _project_verified(None)
    assert missing.value_state is MetricValueStateV2.UNKNOWN
    assert missing.explanation_code == "reviewed_requirement_authority_unavailable"
    assert missing.statistics.eligible_count == 0
    assert missing.statistics.capability_available is False
    assert missing.statistics.source_complete is True

    empty = _project_verified(_plan_snapshot(context, (False,)))
    assert empty.value_state is MetricValueStateV2.NOT_APPLICABLE
    assert empty.explanation_code == "reviewed_requirement_set_empty"
    assert empty.statistics.eligible_count == 0
    assert empty.statistics.capability_available is True
    assert empty.statistics.source_complete is True

    awaiting = _project_verified(_plan_snapshot(context, (True, True)))
    assert awaiting.value_state is MetricValueStateV2.UNKNOWN
    assert awaiting.explanation_code == "requirement_verification_evidence_unavailable"
    assert awaiting.statistics.eligible_count == 2
    assert awaiting.statistics.unknown_count == 2
    assert awaiting.statistics.capability_available is True
    assert awaiting.statistics.source_complete is True
    assert (awaiting.censoring_lower_bound, awaiting.censoring_upper_bound) == (
        0.0,
        1.0,
    )

    overflow = _project_verified(_plan_snapshot(context, (True,) * 101))
    assert overflow.value_state is MetricValueStateV2.UNKNOWN
    assert overflow.explanation_code == (
        "typed_objective_opportunity_count_exceeds_receipt_bound"
    )
    assert overflow.statistics.eligible_count == 0
    assert overflow.statistics.capability_available is True
    assert overflow.statistics.source_complete is True


def test_r8_changes_only_verified_requirement_state_from_r7() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True))
    opportunities = issue_requirement_verification_opportunities(plan, IDS)
    first = opportunities.opportunities[0]
    result = issue_requirement_verification_result(
        opportunities,
        opportunity_id=first.opportunity_id,
        observed_sequence=1,
        method=RequirementVerificationMethod.TEST,
        outcome=RequirementVerificationOutcome.PASSED,
        receipt_reference_ids=(first.opportunity_id,),
        identifiers=IDS,
    )
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(result,),
        identifiers=IDS,
    )
    overrides = project_objective_metric_overrides_v4(
        None,
        None,
        requirement_plan_evidence=plan,
        requirement_verification_evidence=evidence,
        identifiers=IDS,
    )
    projection_arguments = {
        "context": context,
        "reconciliation": None,
        "id_factory": IDS,
        "objective_overrides": overrides,
        "requirement_plan_evidence": plan,
    }

    r7 = project_metric_states_v7(**projection_arguments)
    r8 = project_metric_states_v8(**projection_arguments)
    verified_key = "outcome.verified_requirement_coverage"
    r7_inherited = {
        state.metric_key: state.model_dump(
            mode="python", exclude={"projection_version"}
        )
        for state in r7
        if state.metric_key != verified_key
    }
    r8_inherited = {
        state.metric_key: state.model_dump(
            mode="python", exclude={"projection_version"}
        )
        for state in r8
        if state.metric_key != verified_key
    }

    assert len(r7_inherited) == 19
    assert r8_inherited == r7_inherited


def test_r8_projects_one_exact_mixed_authority_revision() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True))
    opportunities = issue_requirement_verification_opportunities(plan, IDS)
    first, second = opportunities.opportunities
    result = issue_requirement_verification_result(
        opportunities,
        opportunity_id=first.opportunity_id,
        observed_sequence=1,
        method=RequirementVerificationMethod.TEST,
        outcome=RequirementVerificationOutcome.PASSED,
        receipt_reference_ids=(first.opportunity_id,),
        identifiers=IDS,
    )
    acceptance = issue_explicit_requirement_acceptance(
        opportunities,
        opportunity_id=second.opportunity_id,
        confirmation_id=second.opportunity_id,
        outcome=RequirementAcceptanceOutcome.ACCEPTED,
        identifiers=IDS,
    )
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(result,),
        acceptance_authorities=(acceptance,),
        identifiers=IDS,
    )
    overrides = project_objective_metric_overrides_v4(
        None,
        None,
        requirement_plan_evidence=plan,
        requirement_verification_evidence=evidence,
        identifiers=IDS,
    )

    states = project_metric_states_v8(
        context=context,
        reconciliation=None,
        id_factory=IDS,
        objective_overrides=overrides,
        requirement_plan_evidence=plan,
    )

    assert len(states) == 20
    assert {state.projection_version for state in states} == {
        METRIC_PROJECTION_V8_VERSION
    }
    verified = _verified_state(states)
    assert verified.value_state is MetricValueStateV2.KNOWN
    assert (verified.numerator, verified.denominator) == (2, 2)
    assert verified.explanation_code == "app_issued_verified_requirement_coverage"


def test_r8_keeps_an_unresolved_persisted_revision_right_censored_unknown() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True))
    opportunities = issue_requirement_verification_opportunities(plan, IDS)
    first = opportunities.opportunities[0]
    result = issue_requirement_verification_result(
        opportunities,
        opportunity_id=first.opportunity_id,
        observed_sequence=1,
        method=RequirementVerificationMethod.STATIC_CHECK,
        outcome=RequirementVerificationOutcome.PASSED,
        receipt_reference_ids=(first.opportunity_id,),
        identifiers=IDS,
    )
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(result,),
        identifiers=IDS,
    )
    overrides = project_objective_metric_overrides_v4(
        None,
        None,
        requirement_plan_evidence=plan,
        requirement_verification_evidence=evidence,
        identifiers=IDS,
    )

    verified = _verified_state(
        project_metric_states_v8(
            context=context,
            reconciliation=None,
            id_factory=IDS,
            objective_overrides=overrides,
            requirement_plan_evidence=plan,
        )
    )

    assert verified.value_state is MetricValueStateV2.UNKNOWN
    assert verified.explanation_code == (
        "app_issued_requirement_verification_pending"
    )
    assert verified.statistics.eligible_count == 2
    assert verified.statistics.met_count == 1
    assert verified.statistics.unknown_count == 1
    assert verified.statistics.capability_available is True
    assert verified.statistics.source_complete is True
    assert (verified.censoring_lower_bound, verified.censoring_upper_bound) == (
        0.5,
        1.0,
    )


def test_r8_native_only_authority_can_resolve_the_exact_set() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True,))
    opportunities = issue_requirement_verification_opportunities(plan, IDS)
    opportunity = opportunities.opportunities[0]
    acceptance = issue_explicit_requirement_acceptance(
        opportunities,
        opportunity_id=opportunity.opportunity_id,
        confirmation_id=opportunity.opportunity_id,
        outcome=RequirementAcceptanceOutcome.ACCEPTED,
        identifiers=IDS,
    )
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        acceptance_authorities=(acceptance,),
        identifiers=IDS,
    )

    verified = _project_verified(plan, evidence)

    assert verified.value_state is MetricValueStateV2.KNOWN
    assert (verified.numerator, verified.denominator) == (1, 1)
    assert verified.statistics.capability_available is True
    assert verified.statistics.source_complete is True


def test_r8_foreign_or_tampered_evidence_fails_closed() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True,))
    foreign_plan = _plan_snapshot(context, (False, True))
    foreign_opportunities = issue_requirement_verification_opportunities(
        foreign_plan, IDS
    )
    foreign_evidence = issue_requirement_verification_evidence_set(
        foreign_opportunities,
        identifiers=IDS,
    )

    foreign = _project_verified(plan, foreign_evidence)
    tampered = _project_verified(
        plan,
        issue_requirement_verification_evidence_set(
            issue_requirement_verification_opportunities(plan, IDS),
            identifiers=IDS,
        ).model_copy(update={"evidence_set_fingerprint": "f" * 64}),
    )

    for state in (foreign, tampered):
        assert state.value_state is MetricValueStateV2.UNKNOWN
        assert state.explanation_code == "requirement_verification_authority_invalid"
        assert state.statistics.eligible_count == 1
        assert state.statistics.capability_available is True
        assert state.statistics.source_complete is False
