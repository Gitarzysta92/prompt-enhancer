from __future__ import annotations

import hashlib

import pytest

from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionEvidence,
    ActionFamily,
    ActionState,
    DecisionEvidence,
    DecisionState,
    EphemeralTypedEvidenceProjection,
    RationaleState,
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    TypedEvidenceProvenance,
    VerificationEvidence,
    VerificationMethod,
    VerificationOutcome,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES,
    project_objective_metric_overrides,
)
from prompt_enhancer.application.analysis.text_contracts import MetricValueState
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.domain import Provider


SESSION_ID = "f" * 64


def _id(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _descriptor(*capabilities: CapabilityKey) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key="codex"),
        surface=ProviderSurface.OPERATIONAL_EVENTS,
        adapter_version="example-adapter-v1",
        decoder_key="example-events",
        decoder_version="1",
        wire_schema_family="example-events-v1",
        canonical_schema_version="example-source-v1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="example-events",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=capabilities,
    )


#: A fully authoritative synthetic decoder: it may emit every evidence kind,
#: enumerate every denominator family, and link records into all four.
DESCRIPTOR = _descriptor(
    CapabilityKey.TOOL_EVENTS,
    CapabilityKey.DECISION_EVENTS,
    CapabilityKey.VERIFICATION_EVENTS,
    CapabilityKey.REQUIREMENT_OPPORTUNITIES,
    CapabilityKey.HYPOTHESIS_OPPORTUNITIES,
    CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
    CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
    CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
    CapabilityKey.HYPOTHESIS_EVIDENCE_LINKS,
    CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
    CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
)
EVENTS_ONLY_DESCRIPTOR = _descriptor(
    CapabilityKey.TOOL_EVENTS,
    CapabilityKey.DECISION_EVENTS,
    CapabilityKey.VERIFICATION_EVENTS,
)


def _projection(
    *records: ActionEvidence | DecisionEvidence | VerificationEvidence,
    complete: bool = True,
    requirements: tuple[str, ...] = (),
    hypotheses: tuple[str, ...] = (),
    claims: tuple[str, ...] = (),
    tasks: tuple[str, ...] = (),
    declared_kinds: frozenset[TypedEvidenceKind] | None = None,
    declared_opportunities: frozenset[TypedEvidenceOpportunityKind] | None = None,
) -> EphemeralTypedEvidenceProjection:
    if declared_opportunities is None:
        declared_opportunities = frozenset(
            kind
            for kind, values in (
                (TypedEvidenceOpportunityKind.REQUIREMENT, requirements),
                (TypedEvidenceOpportunityKind.HYPOTHESIS, hypotheses),
                (TypedEvidenceOpportunityKind.MATERIAL_CLAIM, claims),
                (TypedEvidenceOpportunityKind.VERIFICATION_TASK, tasks),
            )
            if values
        )
    if declared_kinds is None:
        declared_kinds = frozenset(
            {
                TypedEvidenceKind.ACTION,
                TypedEvidenceKind.DECISION,
                TypedEvidenceKind.VERIFICATION,
            }
        )
    return EphemeralTypedEvidenceProjection(
        session_id=SESSION_ID,
        provenance=TypedEvidenceProvenance(
            provider=Provider.CODEX,
            provider_version="example-provider-v1",
            adapter_version="example-adapter-v1",
            decoder_key="example-events",
            decoder_version="1",
            source_schema_version="example-source-v1",
            extraction_complete=complete,
        ),
        declared_kinds=declared_kinds,
        declared_opportunity_kinds=declared_opportunities,
        eligible_requirement_reference_ids=tuple(sorted(requirements)),
        eligible_hypothesis_reference_ids=tuple(sorted(hypotheses)),
        eligible_claim_reference_ids=tuple(sorted(claims)),
        eligible_verification_task_reference_ids=tuple(sorted(tasks)),
        records=tuple(records),
    )


def _verification(
    outcome: VerificationOutcome,
    *,
    sequence: int,
    requirement_ids: tuple[str, ...] = (),
    hypothesis_ids: tuple[str, ...] = (),
    claim_ids: tuple[str, ...] = (),
    task_ids: tuple[str, ...] = (),
) -> VerificationEvidence:
    return VerificationEvidence(
        evidence_id=_id(f"verification-{sequence}"),
        sequence=sequence,
        source_reference_id=_id(f"source-{sequence}"),
        method=VerificationMethod.TEST,
        outcome=outcome,
        receipt_reference_ids=(_id(f"receipt-{sequence}"),),
        requirement_reference_ids=requirement_ids,
        hypothesis_reference_ids=hypothesis_ids,
        claim_reference_ids=claim_ids,
        verification_task_reference_ids=task_ids,
    )


def test_all_five_evidence_lane_metrics_use_exact_authoritative_sets() -> None:
    requirement_a, requirement_b = _id("requirement-a"), _id("requirement-b")
    hypothesis = _id("hypothesis")
    claim = _id("claim")
    task = _id("verification-task")
    action = ActionEvidence(
        evidence_id=_id("action"),
        sequence=0,
        source_reference_id=_id("action-source"),
        family=ActionFamily.COMMAND,
        state=ActionState.COMPLETED,
        requirement_reference_ids=(requirement_a,),
        hypothesis_reference_ids=(hypothesis,),
    )
    verification = _verification(
        VerificationOutcome.PASSED,
        sequence=1,
        requirement_ids=(requirement_b,),
        hypothesis_ids=(hypothesis,),
        claim_ids=(claim,),
        task_ids=(task,),
    )
    decision = DecisionEvidence(
        evidence_id=_id("decision"),
        sequence=2,
        source_reference_id=_id("decision-source"),
        state=DecisionState.ACCEPTED,
        rationale_state=RationaleState.UNKNOWN,
        hypothesis_reference_ids=(hypothesis,),
    )

    result = project_objective_metric_overrides(
        _projection(
            action,
            verification,
            decision,
            requirements=(requirement_a, requirement_b),
            hypotheses=(hypothesis,),
            claims=(claim,),
            tasks=(task,),
        ),
        DESCRIPTOR,
    )

    assert set(result) == {
        "logic.hypothesis_test_linkage",
        "logic.requirement_action_traceability",
        "outcome.agent_claim_grounding",
        "outcome.first_pass_verification",
        "outcome.verified_requirement_coverage",
    }
    # A fully authoritative graph makes every objective algorithm numeric.
    assert all(
        item.value_state is MetricValueState.KNOWN for item in result.values()
    )
    assert (
        result["logic.hypothesis_test_linkage"].numerator,
        result["logic.hypothesis_test_linkage"].denominator,
    ) == (1, 1)
    assert (
        result["logic.requirement_action_traceability"].numerator,
        result["logic.requirement_action_traceability"].denominator,
    ) == (1, 2)
    assert (
        result["outcome.agent_claim_grounding"].numerator,
        result["outcome.agent_claim_grounding"].denominator,
    ) == (1, 1)
    assert (
        result["outcome.first_pass_verification"].numerator,
        result["outcome.first_pass_verification"].denominator,
    ) == (1, 1)
    assert (
        result["outcome.verified_requirement_coverage"].numerator,
        result["outcome.verified_requirement_coverage"].denominator,
    ) == (1, 2)


def test_unlinked_eligible_requirement_stays_in_both_denominators() -> None:
    linked, missing = _id("linked"), _id("missing")
    action = ActionEvidence(
        evidence_id=_id("one-action"),
        sequence=0,
        source_reference_id=_id("one-action-source"),
        family=ActionFamily.COMMAND,
        state=ActionState.COMPLETED,
        requirement_reference_ids=(linked,),
    )
    verification = _verification(
        VerificationOutcome.PASSED,
        sequence=1,
        requirement_ids=(linked,),
    )

    result = project_objective_metric_overrides(
        _projection(
            action,
            verification,
            requirements=(linked, missing),
        ),
        DESCRIPTOR,
    )

    assert (
        result["logic.requirement_action_traceability"].numerator,
        result["logic.requirement_action_traceability"].denominator,
    ) == (1, 2)
    assert (
        result["outcome.verified_requirement_coverage"].numerator,
        result["outcome.verified_requirement_coverage"].denominator,
    ) == (1, 2)


def test_first_pass_withholds_when_any_eligible_task_has_no_outcome() -> None:
    resolved, pending = _id("resolved-task"), _id("pending-task")
    result = project_objective_metric_overrides(
        _projection(
            _verification(
                VerificationOutcome.PASSED,
                sequence=0,
                task_ids=(resolved,),
            ),
            tasks=(resolved, pending),
        ),
        DESCRIPTOR,
    )

    first_pass = result["outcome.first_pass_verification"]
    assert first_pass.value_state is MetricValueState.UNKNOWN
    assert first_pass.numerator is first_pass.denominator is None
    assert (
        first_pass.resolved_opportunity_count,
        first_pass.eligible_opportunity_count,
    ) == (1, 2)


def test_empty_declared_set_is_not_applicable_but_undeclared_is_withheld() -> None:
    declared = project_objective_metric_overrides(
        _projection(
            declared_opportunities=frozenset(
                {TypedEvidenceOpportunityKind.REQUIREMENT}
            )
        ),
        DESCRIPTOR,
    )
    assert (
        declared["logic.requirement_action_traceability"].value_state
        is MetricValueState.NOT_APPLICABLE
    )
    withheld = project_objective_metric_overrides(_projection(), DESCRIPTOR)
    assert len(withheld) == 5
    assert all(
        item.value_state is MetricValueState.UNKNOWN for item in withheld.values()
    )


def test_incomplete_or_wrong_descriptor_never_creates_objective_metrics() -> None:
    incomplete = project_objective_metric_overrides(
        _projection(complete=False),
        DESCRIPTOR,
    )
    assert len(incomplete) == 5
    assert all(
        item.value_state is MetricValueState.UNKNOWN
        and item.numerator is None
        and item.denominator is None
        for item in incomplete.values()
    )
    with pytest.raises(ValueError, match="not declared"):
        project_objective_metric_overrides(
            _projection(),
            _descriptor(CapabilityKey.USER_MESSAGES),
        )


def test_latest_verification_controls_fresh_requirement_and_claim_state() -> None:
    requirement = _id("fresh-requirement")
    claim = _id("fresh-claim")
    task = _id("first-pass-task")
    result = project_objective_metric_overrides(
        _projection(
            _verification(
                VerificationOutcome.PASSED,
                sequence=0,
                requirement_ids=(requirement,),
                task_ids=(task,),
            ),
            _verification(
                VerificationOutcome.FAILED,
                sequence=1,
                claim_ids=(claim,),
            ),
            _verification(
                VerificationOutcome.FAILED,
                sequence=2,
                requirement_ids=(requirement,),
            ),
            _verification(
                VerificationOutcome.PASSED,
                sequence=3,
                claim_ids=(claim,),
            ),
            requirements=(requirement,),
            claims=(claim,),
            tasks=(task,),
        ),
        DESCRIPTOR,
    )

    assert result["outcome.verified_requirement_coverage"].numerator == 0
    assert result["outcome.agent_claim_grounding"].numerator == 1
    # This metric intentionally keeps first-valid-outcome semantics.
    assert result["outcome.first_pass_verification"].numerator == 1


def test_latest_hypothesis_verification_must_be_resolved() -> None:
    hypothesis = _id("fresh-hypothesis")
    action = ActionEvidence(
        evidence_id=_id("fresh-hypothesis-action"),
        sequence=0,
        source_reference_id=_id("fresh-hypothesis-action-source"),
        family=ActionFamily.COMMAND,
        state=ActionState.COMPLETED,
        hypothesis_reference_ids=(hypothesis,),
    )
    earlier_pass = _verification(
        VerificationOutcome.PASSED,
        sequence=1,
        hypothesis_ids=(hypothesis,),
    )
    later_inconclusive = _verification(
        VerificationOutcome.INCONCLUSIVE,
        sequence=2,
        hypothesis_ids=(hypothesis,),
    )
    decision = DecisionEvidence(
        evidence_id=_id("fresh-hypothesis-decision"),
        sequence=3,
        source_reference_id=_id("fresh-hypothesis-decision-source"),
        state=DecisionState.ACCEPTED,
        rationale_state=RationaleState.UNKNOWN,
        hypothesis_reference_ids=(hypothesis,),
    )

    result = project_objective_metric_overrides(
        _projection(
            action,
            earlier_pass,
            later_inconclusive,
            decision,
            hypotheses=(hypothesis,),
        ),
        DESCRIPTOR,
    )["logic.hypothesis_test_linkage"]

    assert result.value_state is MetricValueState.UNKNOWN
    assert result.explanation_code == "typed_hypothesis_links_unresolved"


def test_opportunity_enumeration_requires_an_explicit_decoder_capability() -> None:
    requirement = _id("undeclared-requirement")

    with pytest.raises(ValueError, match="opportunity enumeration"):
        project_objective_metric_overrides(
            _projection(requirements=(requirement,)),
            EVENTS_ONLY_DESCRIPTOR,
        )


def test_evidence_links_require_an_explicit_decoder_link_capability() -> None:
    requirement = _id("linked-without-authority")
    action = ActionEvidence(
        evidence_id=_id("link-authority-action"),
        sequence=0,
        source_reference_id=_id("link-authority-source"),
        family=ActionFamily.COMMAND,
        state=ActionState.COMPLETED,
        requirement_reference_ids=(requirement,),
    )
    enumeration_only = _descriptor(
        CapabilityKey.TOOL_EVENTS,
        CapabilityKey.DECISION_EVENTS,
        CapabilityKey.VERIFICATION_EVENTS,
        CapabilityKey.REQUIREMENT_OPPORTUNITIES,
    )

    with pytest.raises(ValueError, match="opportunity link"):
        project_objective_metric_overrides(
            _projection(action, requirements=(requirement,)),
            enumeration_only,
        )


def test_declared_denominator_requires_negative_link_observability() -> None:
    requirement = _id("enumerated-without-link-observability")
    enumeration_only = _descriptor(CapabilityKey.REQUIREMENT_OPPORTUNITIES)

    with pytest.raises(ValueError, match="link authority"):
        project_objective_metric_overrides(
            _projection(
                requirements=(requirement,),
                declared_kinds=frozenset(),
            ),
            enumeration_only,
        )


def test_denominator_and_link_authority_cannot_replace_outcome_capabilities() -> None:
    denominator_only = _descriptor(
        CapabilityKey.REQUIREMENT_OPPORTUNITIES,
        CapabilityKey.HYPOTHESIS_OPPORTUNITIES,
        CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
        CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
        CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
        CapabilityKey.HYPOTHESIS_EVIDENCE_LINKS,
        CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
        CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
    )
    result = project_objective_metric_overrides(
        _projection(
            requirements=(_id("capability-requirement"),),
            hypotheses=(_id("capability-hypothesis"),),
            claims=(_id("capability-claim"),),
            tasks=(_id("capability-task"),),
            declared_kinds=frozenset(),
        ),
        denominator_only,
    )

    expected = {
        "logic.hypothesis_test_linkage": (
            "typed_hypothesis_chain_capability_missing"
        ),
        "logic.requirement_action_traceability": (
            "typed_requirement_action_capability_missing"
        ),
        "outcome.agent_claim_grounding": (
            "typed_claim_verification_capability_missing"
        ),
        "outcome.first_pass_verification": (
            "typed_verification_outcome_capability_missing"
        ),
        "outcome.verified_requirement_coverage": (
            "typed_requirement_verification_capability_missing"
        ),
    }
    for metric_key, reason in expected.items():
        item = result[metric_key]
        assert item.value_state is MetricValueState.UNKNOWN
        assert item.numerator is item.denominator is None
        assert item.eligible_opportunity_count == 0
        assert item.explanation_code == reason


def test_unresolved_right_censored_opportunity_reports_bounds_not_zero() -> None:
    resolved, censored = _id("censored-a"), _id("censored-b")

    result = project_objective_metric_overrides(
        _projection(
            _verification(
                VerificationOutcome.PASSED,
                sequence=0,
                task_ids=(resolved,),
            ),
            tasks=(resolved, censored),
        ),
        DESCRIPTOR,
    )["outcome.first_pass_verification"]

    assert result.value_state is MetricValueState.UNKNOWN
    assert (
        result.met_opportunity_count,
        result.resolved_opportunity_count,
        result.eligible_opportunity_count,
    ) == (1, 1, 2)


def test_101_objective_opportunities_fail_closed_at_receipt_bound() -> None:
    requirements = tuple(
        _id(f"bounded-requirement-{index}")
        for index in range(MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES + 1)
    )
    result = project_objective_metric_overrides(
        _projection(requirements=requirements),
        DESCRIPTOR,
    )

    for metric_key in (
        "logic.requirement_action_traceability",
        "outcome.verified_requirement_coverage",
    ):
        item = result[metric_key]
        assert item.value_state is MetricValueState.UNKNOWN
        assert item.numerator is item.denominator is None
        assert item.resolved_opportunity_count == 0
        assert item.eligible_opportunity_count == 0
        assert (
            item.explanation_code
            == "typed_objective_opportunity_count_exceeds_receipt_bound"
        )
