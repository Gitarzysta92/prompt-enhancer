"""Synthetic authority tests for verified requirement coverage foundation."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.objective_metric_projection import (
    OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
    ObjectiveWithholdingCause,
    project_objective_metric_overrides_v4,
    project_verified_requirement_coverage,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    requirement_plan_snapshot_fingerprint,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    ConfirmedRequirementEvidence,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanProducerReceipt,
)
from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    AppIssuedRequirementVerificationResult,
    ExplicitRequirementAcceptanceAuthority,
    MAX_REQUIREMENT_VERIFICATION_OBSERVED_SEQUENCE,
    MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES,
    REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
    REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
    REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
    REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
    REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
    REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
    RequirementAcceptanceOutcome,
    RequirementVerificationAuthorityKind,
    RequirementVerificationMethod,
    RequirementVerificationOutcome,
    issue_explicit_requirement_acceptance,
    issue_requirement_verification_evidence_set,
    issue_requirement_verification_opportunities,
    issue_requirement_verification_result,
    validate_requirement_verification_result,
)
from prompt_enhancer.application.analysis.text_contracts import MetricValueState


def _id(label: str) -> str:
    encoded = f"synthetic-requirement-verification:{label}".encode()
    return hashlib.sha256(encoded).hexdigest()


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()


IDS = _Ids()


def _snapshot(
    count: int,
    *,
    authority: str = "a",
) -> RequirementPlanEvidenceSnapshot:
    requirements = tuple(
        sorted(
            (
                ConfirmedRequirementEvidence(
                    requirement_id=_id(f"{authority}-requirement-{index:03}"),
                    coordinate=RequirementCoordinate(
                        message_sequence=1,
                        clause_index=index,
                    ),
                    disposition=RequirementDisposition.NOT_LINKED,
                )
                for index in range(count)
            ),
            key=lambda item: item.requirement_id,
        )
    )
    return RequirementPlanEvidenceSnapshot(
        session_id=_id(f"{authority}-session"),
        source_window_fingerprint=_id(f"{authority}-window"),
        confirmation_id=_id(f"{authority}-confirmation"),
        proposal_id=_id(f"{authority}-proposal"),
        producer_receipt=RequirementPlanProducerReceipt(
            claim_fingerprint=_id(f"{authority}-untrusted-producer-claim")
        ),
        review_rubric_version=REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        requirements=requirements,
        complete_user_clause_classification=True,
    )


def _result(
    opportunities,  # type: ignore[no-untyped-def]
    index: int,
    outcome: RequirementVerificationOutcome,
    *,
    sequence: int | None = None,
) -> AppIssuedRequirementVerificationResult:
    opportunity = opportunities.opportunities[index]
    return issue_requirement_verification_result(
        opportunities,
        opportunity_id=opportunity.opportunity_id,
        observed_sequence=index if sequence is None else sequence,
        method=RequirementVerificationMethod.TEST,
        outcome=outcome,
        receipt_reference_ids=(_id(f"receipt-{index}-{outcome.value}"),),
        identifiers=IDS,
    )


def _acceptance(
    opportunities,  # type: ignore[no-untyped-def]
    index: int,
    outcome: RequirementAcceptanceOutcome,
) -> ExplicitRequirementAcceptanceAuthority:
    opportunity = opportunities.opportunities[index]
    return issue_explicit_requirement_acceptance(
        opportunities,
        opportunity_id=opportunity.opportunity_id,
        confirmation_id=_id(f"acceptance-{index}-{outcome.value}"),
        outcome=outcome,
        identifiers=IDS,
    )


def _project(snapshot, evidence):  # type: ignore[no-untyped-def]
    return project_verified_requirement_coverage(
        requirement_plan_evidence=snapshot,
        verification_evidence=evidence,
        identifiers=IDS,
    )


def test_app_issuer_reuses_the_exact_complete_r6_active_requirement_identity() -> None:
    snapshot = _snapshot(3)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)

    assert opportunities.requirement_plan_evidence_fingerprint == (
        requirement_plan_snapshot_fingerprint(snapshot, IDS)
    )
    assert tuple(
        (item.requirement_index, item.requirement_id, item.coordinate)
        for item in opportunities.opportunities
    ) == tuple(
        (index, item.requirement_id, item.coordinate)
        for index, item in enumerate(snapshot.requirements)
    )
    assert opportunities.complete_active_requirement_enumeration is True
    assert opportunities.requirement_plan_confirmation_id == snapshot.confirmation_id
    assert opportunities.requirement_plan_proposal_id == snapshot.proposal_id


def test_typed_pass_fail_and_unknown_preserve_right_censoring() -> None:
    snapshot = _snapshot(3)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(
            _result(opportunities, 0, RequirementVerificationOutcome.PASSED),
            _result(opportunities, 1, RequirementVerificationOutcome.FAILED),
            _result(opportunities, 2, RequirementVerificationOutcome.UNKNOWN),
        ),
        identifiers=IDS,
    )

    projected = _project(snapshot, evidence)

    assert projected.value_state is MetricValueState.UNKNOWN
    assert projected.explanation_code == "app_issued_requirement_verification_pending"
    assert projected.numerator is projected.denominator is None
    assert (
        projected.met_opportunity_count,
        projected.resolved_opportunity_count,
        projected.eligible_opportunity_count,
    ) == (1, 2, 3)
    assert projected.withholding_cause is ObjectiveWithholdingCause.EVIDENCE_UNRESOLVED


def test_complete_objective_and_acceptance_authorities_publish_fraction() -> None:
    snapshot = _snapshot(3)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(
            _result(opportunities, 0, RequirementVerificationOutcome.PASSED),
            _result(opportunities, 1, RequirementVerificationOutcome.FAILED),
        ),
        acceptance_authorities=(
            _acceptance(opportunities, 2, RequirementAcceptanceOutcome.ACCEPTED),
        ),
        identifiers=IDS,
    )

    projected = _project(snapshot, evidence)

    assert projected.value_state is MetricValueState.KNOWN
    assert projected.explanation_code == "app_issued_verified_requirement_coverage"
    assert (projected.numerator, projected.denominator) == (2, 3)
    assert projected.withholding_cause is ObjectiveWithholdingCause.NOT_WITHHELD
    assert evidence.acceptance_authorities[0].authority_kind.value == (
        "native_user_acceptance"
    )


@pytest.mark.parametrize(
    ("outcome", "expected_state", "expected_numerator"),
    (
        (RequirementAcceptanceOutcome.ACCEPTED, MetricValueState.KNOWN, 1),
        (RequirementAcceptanceOutcome.REJECTED, MetricValueState.KNOWN, 0),
        (RequirementAcceptanceOutcome.UNKNOWN, MetricValueState.UNKNOWN, None),
    ),
)
def test_explicit_acceptance_outcomes_remain_typed(
    outcome: RequirementAcceptanceOutcome,
    expected_state: MetricValueState,
    expected_numerator: int | None,
) -> None:
    snapshot = _snapshot(1)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        acceptance_authorities=(_acceptance(opportunities, 0, outcome),),
        identifiers=IDS,
    )

    projected = _project(snapshot, evidence)

    assert projected.value_state is expected_state
    assert projected.numerator == expected_numerator
    assert projected.met_opportunity_count == (expected_numerator or 0)


def test_missing_result_is_pending_not_a_measured_failure() -> None:
    snapshot = _snapshot(2)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(
            _result(opportunities, 0, RequirementVerificationOutcome.PASSED),
        ),
        identifiers=IDS,
    )

    projected = _project(snapshot, evidence)

    assert projected.value_state is MetricValueState.UNKNOWN
    assert projected.met_opportunity_count == 1
    assert projected.resolved_opportunity_count == 1
    assert projected.eligible_opportunity_count == 2


def test_confirmed_zero_active_requirements_is_not_applicable_without_results() -> None:
    projected = _project(_snapshot(0), None)

    assert projected.value_state is MetricValueState.NOT_APPLICABLE
    assert projected.explanation_code == "reviewed_requirement_set_empty"
    assert projected.eligible_opportunity_count == 0
    assert projected.withholding_cause is ObjectiveWithholdingCause.NOT_WITHHELD


def test_active_set_above_receipt_bound_fails_closed_without_truncation() -> None:
    snapshot = _snapshot(MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES + 1)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    assert len(opportunities.opportunities) == 101

    projected = _project(
        snapshot,
        issue_requirement_verification_evidence_set(
            opportunities,
            identifiers=IDS,
        ),
    )

    assert projected.value_state is MetricValueState.UNKNOWN
    assert projected.explanation_code == (
        "typed_objective_opportunity_count_exceeds_receipt_bound"
    )
    assert projected.resolved_opportunity_count == 0
    assert projected.eligible_opportunity_count == 0
    assert projected.withholding_cause is (
        ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED
    )


@pytest.mark.parametrize("attack", ["missing", "duplicate"])
def test_missing_or_duplicate_issued_opportunities_fail_closed(attack: str) -> None:
    snapshot = _snapshot(2)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        identifiers=IDS,
    )
    attacked_items = (
        opportunities.opportunities[:1]
        if attack == "missing"
        else (opportunities.opportunities[0], opportunities.opportunities[0])
    )
    attacked_opportunities = opportunities.model_copy(
        update={"opportunities": attacked_items}
    )
    attacked_evidence = evidence.model_copy(
        update={"opportunities": attacked_opportunities}
    )

    projected = _project(snapshot, attacked_evidence)

    assert projected.value_state is MetricValueState.UNKNOWN
    assert projected.explanation_code == "requirement_verification_authority_invalid"
    assert projected.eligible_opportunity_count == 2


def test_foreign_opportunity_set_cannot_replace_exact_r6_identity() -> None:
    snapshot = _snapshot(2, authority="a")
    foreign_snapshot = _snapshot(2, authority="b")
    foreign_opportunities = issue_requirement_verification_opportunities(
        foreign_snapshot, IDS
    )
    foreign_evidence = issue_requirement_verification_evidence_set(
        foreign_opportunities,
        identifiers=IDS,
    )

    projected = _project(snapshot, foreign_evidence)

    assert projected.value_state is MetricValueState.UNKNOWN
    assert projected.explanation_code == "requirement_verification_authority_invalid"


def test_duplicate_or_foreign_results_fail_closed() -> None:
    snapshot = _snapshot(2, authority="a")
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    result = _result(opportunities, 0, RequirementVerificationOutcome.PASSED)
    valid = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(result,),
        identifiers=IDS,
    )
    duplicate = valid.model_copy(update={"verification_results": (result, result)})
    assert _project(snapshot, duplicate).explanation_code == (
        "requirement_verification_authority_invalid"
    )

    foreign_snapshot = _snapshot(1, authority="b")
    foreign_opportunities = issue_requirement_verification_opportunities(
        foreign_snapshot, IDS
    )
    foreign_result = _result(
        foreign_opportunities,
        0,
        RequirementVerificationOutcome.PASSED,
    )
    foreign = valid.model_copy(update={"verification_results": (foreign_result,)})
    assert _project(snapshot, foreign).explanation_code == (
        "requirement_verification_authority_invalid"
    )


def test_one_opportunity_cannot_use_both_result_and_acceptance_authority() -> None:
    snapshot = _snapshot(1)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    result = _result(opportunities, 0, RequirementVerificationOutcome.PASSED)
    acceptance = _acceptance(
        opportunities, 0, RequirementAcceptanceOutcome.ACCEPTED
    )

    with pytest.raises(ValueError, match="at most one result authority"):
        issue_requirement_verification_evidence_set(
            opportunities,
            verification_results=(result,),
            acceptance_authorities=(acceptance,),
            identifiers=IDS,
        )


def test_assistant_or_model_self_authorship_has_no_accepted_authority_type() -> None:
    snapshot = _snapshot(1)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    result = _result(opportunities, 0, RequirementVerificationOutcome.PASSED)
    acceptance = _acceptance(
        opportunities, 0, RequirementAcceptanceOutcome.ACCEPTED
    )

    with pytest.raises(ValidationError):
        AppIssuedRequirementVerificationResult.model_validate(
            {
                **result.model_dump(mode="python"),
                "authority_kind": "assistant_completion_claim",
            }
        )
    with pytest.raises(ValidationError):
        ExplicitRequirementAcceptanceAuthority.model_validate(
            {
                **acceptance.model_dump(mode="python"),
                "authority_kind": "model_acceptance_prediction",
            }
        )
    assert result.authority_kind is (
        RequirementVerificationAuthorityKind.APP_OBJECTIVE_VERIFIER
    )


def test_versions_and_keyed_fingerprints_are_exact_and_tamper_evident() -> None:
    snapshot = _snapshot(1)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    result = _result(opportunities, 0, RequirementVerificationOutcome.PASSED)
    acceptance = _acceptance(
        opportunities, 0, RequirementAcceptanceOutcome.ACCEPTED
    )
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(result,),
        identifiers=IDS,
    )

    assert OBJECTIVE_METRIC_PROJECTION_V4_VERSION == (
        REQUIREMENT_VERIFICATION_PROJECTION_VERSION
    )
    assert opportunities.issuer_version == (
        REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION
    )
    assert result.issuer_version == REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION
    assert acceptance.issuer_version == (
        REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION
    )
    assert evidence.evidence_schema_version == (
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    )
    assert evidence.evidence_policy_version == (
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    )
    assert all(
        len(value) == 64
        for value in (
            opportunities.requirement_plan_evidence_fingerprint,
            opportunities.opportunity_set_fingerprint,
            result.result_fingerprint,
            acceptance.acceptance_fingerprint,
            evidence.evidence_set_fingerprint,
        )
    )

    tampered_result = result.model_copy(update={"result_fingerprint": _id("tamper")})
    tampered = evidence.model_copy(
        update={"verification_results": (tampered_result,)}
    )
    assert _project(snapshot, tampered).explanation_code == (
        "requirement_verification_authority_invalid"
    )


def test_observed_sequence_has_exact_sqlite_safe_bound_and_keyed_revalidation() -> None:
    opportunities = issue_requirement_verification_opportunities(_snapshot(1), IDS)
    bounded = _result(
        opportunities,
        0,
        RequirementVerificationOutcome.PASSED,
        sequence=MAX_REQUIREMENT_VERIFICATION_OBSERVED_SEQUENCE,
    )
    assert (
        validate_requirement_verification_result(bounded, opportunities, IDS)
        == bounded
    )

    with pytest.raises(ValidationError):
        _result(
            opportunities,
            0,
            RequirementVerificationOutcome.PASSED,
            sequence=MAX_REQUIREMENT_VERIFICATION_OBSERVED_SEQUENCE + 1,
        )
    tampered = bounded.model_copy(update={"observed_sequence": 0})
    with pytest.raises(ValueError, match="lacks app-issued authority"):
        validate_requirement_verification_result(tampered, opportunities, IDS)


def test_v4_integration_replaces_only_verified_requirement_authority() -> None:
    snapshot = _snapshot(1)
    opportunities = issue_requirement_verification_opportunities(snapshot, IDS)
    evidence = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=(
            _result(opportunities, 0, RequirementVerificationOutcome.PASSED),
        ),
        identifiers=IDS,
    )

    projected = project_objective_metric_overrides_v4(
        None,
        None,
        requirement_plan_evidence=snapshot,
        requirement_verification_evidence=evidence,
        identifiers=IDS,
    )

    assert len(projected) == 5
    assert projected["outcome.verified_requirement_coverage"].value_state is (
        MetricValueState.KNOWN
    )
    assert (
        projected["outcome.verified_requirement_coverage"].numerator,
        projected["outcome.verified_requirement_coverage"].denominator,
    ) == (1, 1)
    assert all(
        item.value_state is MetricValueState.UNKNOWN
        for key, item in projected.items()
        if key != "outcome.verified_requirement_coverage"
    )
