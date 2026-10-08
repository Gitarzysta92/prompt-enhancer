"""Projection identity r3: the explicit-plan open loop and the r3 corrections.

Every fixture is synthetic: fictional identities, reserved example wording, and
no path, host, account, or transcript material of any kind.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.evidence_contracts import (
    EphemeralTypedEvidenceProjection,
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    TypedEvidenceProvenance,
    VerificationEvidence,
    VerificationMethod,
    VerificationOutcome,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
    metric_contract_v2,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    project_metric_states_v2,
)
from prompt_enhancer.application.analysis.metric_projection_v3 import (
    METRIC_PROJECTION_V3_ALGORITHM_VERSION,
    METRIC_PROJECTION_V3_VERSION,
    REASON_RUBRIC_OWNERSHIP_UNAVAILABLE,
    objective_metric_state_v3,
    project_metric_states_v3,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    MetricImplementationState,
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    ObjectiveMetricOverride,
    ObjectiveWithholdingCause,
    project_objective_metric_overrides,
    project_objective_metric_overrides_v3,
)
from prompt_enhancer.application.analysis.open_loop_lifecycle_v3 import (
    REASON_OPEN_LOOP_PLAN_CAPABILITY_ABSENT,
    REASON_OPEN_LOOP_PLAN_EPISODE_ABSENT,
    project_open_loop_lifecycle_v3,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.domain import Provider


OPEN_LOOP = "logic.open_loop_closure"
RUBRIC_METRIC_KEYS = (
    "prompt.task_definition_coverage",
    "prompt.problem_evidence_quality",
    "prompt.context_sufficiency",
)


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-v3:{label}".encode()).hexdigest()


class _SyntheticIdFactory:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        return hashlib.sha256(
            "\x1f".join((namespace, *values, secret.get_secret_value())).encode()
        ).hexdigest()


IDS = _SyntheticIdFactory()


def _message(
    label: str,
    sequence: int,
    role: TextRole,
    kind: TextMessageKind,
    text: str,
    *,
    supersedes: tuple[str, ...] = (),
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=_id(label),
        sequence=sequence,
        role=role,
        kind=kind,
        language=TextLanguage.ENGLISH,
        text=SecretStr(text),
        supersedes_message_ids=supersedes,
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    *,
    label: str,
    complete: bool = True,
    available_kinds: frozenset[TextMessageKind] | None = None,
) -> P1TextAnalysisInput:
    focus = next(
        message
        for message in reversed(messages)
        if message.role is TextRole.USER
        and message.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=complete,
        available_message_kinds=(
            available_kinds
            if available_kinds is not None
            else frozenset(message.kind for message in messages)
        ),
        analysis_window_fingerprint=_id(f"window:{label}"),
        focus_message_id=focus.message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages) if complete else len(messages) + 5,
        messages=messages,
        task_profile=TextTaskProfile(applicability=()),
    )


def _project(
    context: P1TextAnalysisInput,
    *,
    conversational: dict[str, Any] | None = None,
    objective: dict[str, ObjectiveMetricOverride] | None = None,
    with_reconciliation: bool = True,
):
    reconciliation = (
        SemanticUnitReconciler(IDS).reconcile(context).reconciliation
        if with_reconciliation
        else None
    )
    return project_metric_states_v3(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
        conversational_results=conversational,
        objective_overrides=objective,
    )


def _by_key(states: tuple[Any, ...]) -> dict[str, Any]:
    return {state.metric_key: state for state in states}


def _request(label: str = "request", sequence: int = 1) -> EphemeralRedactedMessage:
    return _message(
        label,
        sequence,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the fictional widget report.",
    )


# --------------------------------------------------------------------------
# logic.open_loop_closure: explicit plan episodes
# --------------------------------------------------------------------------


def test_one_plan_with_exact_link_is_known_one_of_one() -> None:
    plan = _message(
        "plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    context = _context(
        (
            _request(),
            plan,
            _message(
                "action",
                3,
                TextRole.AGENT,
                TextMessageKind.ACTION,
                "Exported the fictional widget rows.",
                supersedes=(plan.message_id,),
            ),
        ),
        label="closed-plan",
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (1, 1, 1.0)
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (1.0, 1.0)
    assert state.statistics.eligible_count == 1
    assert state.statistics.distinct_owner_count == 1
    assert state.product_metric_eligible is False


def test_one_plan_without_a_link_is_pending_between_zero_and_one() -> None:
    context = _context(
        (
            _request(),
            _message(
                "plan",
                2,
                TextRole.AGENT,
                TextMessageKind.PLAN,
                "Plan: export the fictional widget rows.",
            ),
        ),
        label="open-plan",
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.numeric_value is None
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (0.0, 1.0)
    assert state.statistics.pending_count == 1


def test_two_plans_with_one_link_are_pending_between_one_half_and_one() -> None:
    first = _message(
        "plan-a",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    second = _message(
        "plan-b",
        4,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: summarise the fictional widget rows.",
    )
    context = _context(
        (
            _request(),
            first,
            _message(
                "action",
                3,
                TextRole.AGENT,
                TextMessageKind.ACTION,
                "Exported the fictional widget rows.",
                supersedes=(first.message_id,),
            ),
            second,
        ),
        label="half-closed",
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.PENDING
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (0.5, 1.0)
    assert state.statistics.met_count == 1
    assert state.statistics.pending_count == 1
    assert state.statistics.not_met_count == 0


def test_an_unrelated_later_action_does_not_close_a_plan() -> None:
    other = _message(
        "other-plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    target = _message(
        "target-plan",
        3,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows and validate them.",
    )
    context = _context(
        (
            _request(),
            other,
            target,
            # Highly overlapping wording, and a link to a *different* plan.
            _message(
                "action",
                4,
                TextRole.AGENT,
                TextMessageKind.ACTION,
                "Exported the fictional widget rows and validated them.",
                supersedes=(other.message_id,),
            ),
        ),
        label="unrelated-action",
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.statistics.met_count == 1
    assert state.statistics.pending_count == 1
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (0.5, 1.0)


def test_a_response_message_cannot_close_a_plan() -> None:
    plan = _message(
        "plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    context = _context(
        (
            _request(),
            plan,
            _message(
                "response",
                3,
                TextRole.AGENT,
                TextMessageKind.RESPONSE,
                "Here is the fictional widget summary.",
                supersedes=(plan.message_id,),
            ),
        ),
        label="response-link",
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.statistics.pending_count == 1


def test_no_plan_returns_a_named_actionable_unknown_with_no_number() -> None:
    context = _context((_request(),), label="no-plan")

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.numeric_value is None
    assert state.numerator is None and state.denominator is None
    assert state.explanation_code == REASON_OPEN_LOOP_PLAN_CAPABILITY_ABSENT
    assert state.statistics.capability_available is False
    assert state.statistics.eligible_count == 0


def test_declared_plan_capability_with_no_plan_message_stays_unknown() -> None:
    context = _context(
        (_request(),),
        label="declared-no-plan",
        available_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.PLAN, TextMessageKind.ACTION}
        ),
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_OPEN_LOOP_PLAN_EPISODE_ABSENT
    assert state.value_state is not MetricValueStateV2.NOT_APPLICABLE


def test_incomplete_right_edge_keeps_a_trailing_plan_pending() -> None:
    context = _context(
        (
            _request(),
            _message(
                "plan",
                2,
                TextRole.AGENT,
                TextMessageKind.PLAN,
                "Plan: export the fictional widget rows.",
            ),
        ),
        label="right-edge",
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.statistics.pending_count == 1
    assert state.statistics.not_met_count == 0


def test_an_incomplete_window_withholds_rather_than_censoring_falsely() -> None:
    context = _context(
        (
            _request(),
            _message(
                "plan",
                2,
                TextRole.AGENT,
                TextMessageKind.PLAN,
                "Plan: export the fictional widget rows.",
            ),
        ),
        label="incomplete-window",
        complete=False,
    )

    state = _by_key(_project(context))[OPEN_LOOP]

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == "source_reconciliation_incomplete"


def test_episode_and_link_order_is_deterministic() -> None:
    plan = _message(
        "plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    messages = (
        _request(),
        plan,
        _message(
            "action-late",
            4,
            TextRole.AGENT,
            TextMessageKind.ACTION,
            "Exported again.",
            supersedes=(plan.message_id,),
        ),
        _message(
            "action-early",
            3,
            TextRole.AGENT,
            TextMessageKind.VERIFICATION,
            "Verified the export.",
            supersedes=(plan.message_id,),
        ),
    )
    context = _context(
        tuple(sorted(messages, key=lambda item: item.sequence)),
        label="deterministic",
    )

    lifecycle = project_open_loop_lifecycle_v3(context, IDS)
    repeated = project_open_loop_lifecycle_v3(context, IDS)

    assert lifecycle == repeated
    assert len(lifecycle.episodes) == 1
    # The earliest explicit link owns the closure, matching the reconciler's
    # (sequence, message_id) replacement order.
    assert lifecycle.episodes[0].closed_at_sequence == 3


def test_other_structural_collaboration_metrics_remain_actionable_unknown() -> None:
    context = _context(
        (
            _request(),
            _message(
                "plan",
                2,
                TextRole.AGENT,
                TextMessageKind.PLAN,
                "Plan: export the fictional widget rows.",
            ),
        ),
        label="only-open-loop",
    )

    by_key = _by_key(_project(context))

    for metric_key in (
        "collaboration.ambiguity_resolution",
        "collaboration.clarification_yield",
        "collaboration.exploration_conversion",
        "collaboration.scope_change_discipline",
        "logic.decomposition_coverage",
    ):
        assert by_key[metric_key].value_state is MetricValueStateV2.UNKNOWN
        assert by_key[metric_key].numeric_value is None


def test_open_loop_measurement_does_not_change_the_frozen_r2_projection() -> None:
    plan = _message(
        "plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    context = _context(
        (
            _request(),
            plan,
            _message(
                "action",
                3,
                TextRole.AGENT,
                TextMessageKind.ACTION,
                "Exported the fictional widget rows.",
                supersedes=(plan.message_id,),
            ),
        ),
        label="frozen-r2",
    )
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation

    legacy = _by_key(
        project_metric_states_v2(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )[OPEN_LOOP]

    assert legacy.value_state is MetricValueStateV2.UNKNOWN
    assert legacy.explanation_code == "opportunity_family_unobservable"
    assert legacy.projection_version == "metric-contract-v2-projection-2"


# --------------------------------------------------------------------------
# Projection identity
# --------------------------------------------------------------------------


def test_every_state_carries_the_r3_identity_consistently() -> None:
    context = _context((_request(),), label="identity")

    states = _project(context)
    publication = publish_metric_states_v2(states)

    assert METRIC_PROJECTION_V3_VERSION == "metric-contract-v2-projection-3"
    assert METRIC_PROJECTION_V3_ALGORITHM_VERSION == "3"
    assert len(states) == len(METRIC_CONTRACTS_V2) == 20
    assert all(
        state.projection_version == METRIC_PROJECTION_V3_VERSION for state in states
    )
    assert publication.projection_version == METRIC_PROJECTION_V3_VERSION
    assert publication.canonical_live_snapshot is True
    assert publication.product_metric_eligible is False


# --------------------------------------------------------------------------
# Rubric ownership without a reconciliation
# --------------------------------------------------------------------------


def test_a_direct_projection_without_reconciliation_reports_missing_ownership() -> None:
    context = _context((_request(),), label="no-reconciliation")

    by_key = _by_key(_project(context, with_reconciliation=False))

    for metric_key in RUBRIC_METRIC_KEYS:
        state = by_key[metric_key]
        assert state.value_state is MetricValueStateV2.UNKNOWN
        assert state.explanation_code == REASON_RUBRIC_OWNERSHIP_UNAVAILABLE
        assert state.statistics.capability_available is False


def test_r2_keeps_its_no_opportunity_answer_without_a_reconciliation() -> None:
    context = _context((_request(),), label="no-reconciliation-r2")

    by_key = _by_key(
        project_metric_states_v2(
            context=context,
            reconciliation=None,
            id_factory=IDS,
        )
    )

    assert (
        by_key["prompt.task_definition_coverage"].value_state
        is MetricValueStateV2.NOT_APPLICABLE
    )


# --------------------------------------------------------------------------
# Objective gates
# --------------------------------------------------------------------------


def _descriptor(*capabilities: CapabilityKey) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key="synthetic"),
        surface=ProviderSurface.OPERATIONAL_EVENTS,
        adapter_version="synthetic-adapter.1",
        decoder_key="safe-event-evidence",
        decoder_version="3",
        wire_schema_family="synthetic.safe-events",
        canonical_schema_version="synthetic-source.1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="synthetic.safe-event-index",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=capabilities,
    )


def _projection(
    *,
    declared_kinds: frozenset[TypedEvidenceKind],
    declared_opportunity_kinds: frozenset[TypedEvidenceOpportunityKind] = frozenset(),
    claims: tuple[str, ...] = (),
    tasks: tuple[str, ...] = (),
    records: tuple[Any, ...] = (),
    extraction_complete: bool = True,
) -> EphemeralTypedEvidenceProjection:
    return EphemeralTypedEvidenceProjection(
        session_id=_id("session"),
        provenance=TypedEvidenceProvenance(
            provider=Provider.SYNTHETIC,
            provider_version="synthetic.1",
            adapter_version="synthetic-adapter.1",
            decoder_key="safe-event-evidence",
            decoder_version="3",
            source_schema_version="synthetic-source.1",
            extraction_complete=extraction_complete,
        ),
        declared_kinds=declared_kinds,
        declared_opportunity_kinds=declared_opportunity_kinds,
        eligible_claim_reference_ids=claims,
        eligible_verification_task_reference_ids=tasks,
        records=records,
    )


def test_an_empty_claim_set_needs_outcome_authority_before_it_is_measurable() -> None:
    descriptor = _descriptor(
        CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
        CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
        CapabilityKey.TOOL_EVENTS,
    )
    projection = _projection(
        declared_kinds=frozenset({TypedEvidenceKind.ACTION}),
        declared_opportunity_kinds=frozenset(
            {TypedEvidenceOpportunityKind.MATERIAL_CLAIM}
        ),
    )

    legacy = project_objective_metric_overrides(projection, descriptor)
    corrected = project_objective_metric_overrides_v3(projection, descriptor)

    # r2 read the empty set as a proved absence even though it could not
    # observe a single verification outcome.
    assert (
        legacy["outcome.agent_claim_grounding"].value_state
        is MetricValueState.NOT_APPLICABLE
    )
    assert (
        corrected["outcome.agent_claim_grounding"].value_state
        is MetricValueState.UNKNOWN
    )
    assert corrected["outcome.agent_claim_grounding"].withholding_cause is (
        ObjectiveWithholdingCause.AUTHORITY_MISSING
    )
    assert corrected["outcome.agent_claim_grounding"].explanation_code == (
        "typed_claim_verification_capability_missing"
    )


def test_an_empty_claim_set_with_full_authority_stays_not_applicable() -> None:
    descriptor = _descriptor(
        CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
        CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
        CapabilityKey.VERIFICATION_EVENTS,
    )
    projection = _projection(
        declared_kinds=frozenset({TypedEvidenceKind.VERIFICATION}),
        declared_opportunity_kinds=frozenset(
            {TypedEvidenceOpportunityKind.MATERIAL_CLAIM}
        ),
    )

    corrected = project_objective_metric_overrides_v3(projection, descriptor)
    state = objective_metric_state_v3(
        metric_contract_v2("outcome.agent_claim_grounding"),
        corrected["outcome.agent_claim_grounding"],
    )

    assert (
        corrected["outcome.agent_claim_grounding"].value_state
        is MetricValueState.NOT_APPLICABLE
    )
    assert state.value_state is MetricValueStateV2.NOT_APPLICABLE


def test_withholding_causes_map_to_distinct_capability_and_completeness() -> None:
    contract = metric_contract_v2("outcome.agent_claim_grounding")

    authority_missing = objective_metric_state_v3(
        contract,
        ObjectiveMetricOverride(
            value_state=MetricValueState.UNKNOWN,
            explanation_code="typed_objective_authority_unavailable",
            withholding_cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        ),
    )
    extraction_incomplete = objective_metric_state_v3(
        contract,
        ObjectiveMetricOverride(
            value_state=MetricValueState.UNKNOWN,
            explanation_code="typed_objective_extraction_incomplete",
            withholding_cause=ObjectiveWithholdingCause.EXTRACTION_INCOMPLETE,
        ),
    )
    bound_exceeded = objective_metric_state_v3(
        contract,
        ObjectiveMetricOverride(
            value_state=MetricValueState.UNKNOWN,
            explanation_code=(
                "typed_objective_opportunity_count_exceeds_receipt_bound"
            ),
            withholding_cause=ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED,
        ),
    )

    assert all(
        state.value_state is MetricValueStateV2.UNKNOWN
        for state in (authority_missing, extraction_incomplete, bound_exceeded)
    )
    assert (
        authority_missing.statistics.capability_available,
        authority_missing.statistics.source_complete,
    ) == (False, False)
    assert (
        extraction_incomplete.statistics.capability_available,
        extraction_incomplete.statistics.source_complete,
    ) == (True, False)
    assert (
        bound_exceeded.statistics.capability_available,
        bound_exceeded.statistics.source_complete,
    ) == (True, True)
    # Never "no opportunity": an overflowing set is the opposite of empty.
    assert bound_exceeded.value_state is not MetricValueStateV2.NOT_APPLICABLE


def test_receipt_bound_is_published_as_unresolved_not_capability_missing() -> None:
    context = _context((_request(),), label="receipt-bound-publication")
    publication = publish_metric_states_v2(
        _project(
            context,
            objective={
                "outcome.agent_claim_grounding": ObjectiveMetricOverride(
                    value_state=MetricValueState.UNKNOWN,
                    explanation_code=(
                        "typed_objective_opportunity_count_exceeds_receipt_bound"
                    ),
                    withholding_cause=(
                        ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED
                    ),
                )
            },
        )
    )
    item = next(
        metric
        for metric in publication.metrics
        if metric.state.metric_key == "outcome.agent_claim_grounding"
    )

    assert item.state.value_state is MetricValueStateV2.UNKNOWN
    assert item.state.statistics.capability_available is True
    assert item.implementation_state is (
        MetricImplementationState.OBJECTIVE_EVIDENCE_UNRESOLVED
    )


def test_extraction_incomplete_without_declared_authority_stays_capability_missing() -> None:
    descriptor = _descriptor(CapabilityKey.TOOL_EVENTS)
    projection = _projection(
        declared_kinds=frozenset({TypedEvidenceKind.ACTION}),
        extraction_complete=False,
    )

    corrected = project_objective_metric_overrides_v3(projection, descriptor)

    assert all(
        item.withholding_cause is ObjectiveWithholdingCause.AUTHORITY_MISSING
        for item in corrected.values()
    )


def test_extraction_incomplete_with_declared_authority_reports_source_incomplete() -> None:
    descriptor = _descriptor(
        CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
        CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
        CapabilityKey.VERIFICATION_EVENTS,
    )
    projection = _projection(
        declared_kinds=frozenset({TypedEvidenceKind.VERIFICATION}),
        declared_opportunity_kinds=frozenset(
            {TypedEvidenceOpportunityKind.MATERIAL_CLAIM}
        ),
        extraction_complete=False,
    )

    corrected = project_objective_metric_overrides_v3(projection, descriptor)
    state = objective_metric_state_v3(
        metric_contract_v2("outcome.agent_claim_grounding"),
        corrected["outcome.agent_claim_grounding"],
    )

    assert corrected["outcome.agent_claim_grounding"].withholding_cause is (
        ObjectiveWithholdingCause.EXTRACTION_INCOMPLETE
    )
    assert state.statistics.capability_available is True
    assert state.statistics.source_complete is False


def test_first_pass_stays_unknown_without_a_verification_task_denominator() -> None:
    descriptor = _descriptor(CapabilityKey.VERIFICATION_EVENTS)
    projection = _projection(
        declared_kinds=frozenset({TypedEvidenceKind.VERIFICATION}),
        records=(
            VerificationEvidence(
                evidence_id=_id("verification"),
                sequence=1,
                source_reference_id=_id("event"),
                method=VerificationMethod.TEST,
                outcome=VerificationOutcome.PASSED,
                receipt_reference_ids=(_id("event"),),
            ),
        ),
    )

    corrected = project_objective_metric_overrides_v3(projection, descriptor)
    state = objective_metric_state_v3(
        metric_contract_v2("outcome.first_pass_verification"),
        corrected["outcome.first_pass_verification"],
    )

    assert (
        corrected["outcome.first_pass_verification"].value_state
        is MetricValueState.UNKNOWN
    )
    assert corrected["outcome.first_pass_verification"].explanation_code == (
        "typed_objective_opportunity_authority_missing"
    )
    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.statistics.capability_available is False


def test_an_r2_override_is_rejected_by_the_r3_objective_lane() -> None:
    contract = metric_contract_v2("outcome.agent_claim_grounding")
    legacy = ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code="typed_objective_authority_unavailable",
    )

    with pytest.raises(ValueError, match="r3 objective override"):
        objective_metric_state_v3(contract, legacy)


def test_a_withheld_objective_metric_must_name_its_cause() -> None:
    with pytest.raises(ValueError, match="withholding cause"):
        ObjectiveMetricOverride(
            value_state=MetricValueState.UNKNOWN,
            explanation_code="typed_objective_authority_unavailable",
            withholding_cause=ObjectiveWithholdingCause.NOT_WITHHELD,
        )
    with pytest.raises(ValueError, match="withholding cause"):
        ObjectiveMetricOverride(
            value_state=MetricValueState.NOT_APPLICABLE,
            explanation_code="typed_claim_set_empty",
            withholding_cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        )


def test_r3_publication_reports_no_content_and_no_identifiers() -> None:
    plan = _message(
        "plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan: export the fictional widget rows.",
    )
    context = _context(
        (
            _request(),
            plan,
            _message(
                "action",
                3,
                TextRole.AGENT,
                TextMessageKind.ACTION,
                "Exported the fictional widget rows.",
                supersedes=(plan.message_id,),
            ),
        ),
        label="privacy",
    )

    publication = publish_metric_states_v2(_project(context))
    payload = publication.model_dump_json()

    assert "fictional widget" not in payload
    assert plan.message_id not in payload
    assert context.session_id not in payload
