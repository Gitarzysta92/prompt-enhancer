from __future__ import annotations

import hashlib

from pydantic import SecretStr

from prompt_enhancer.application.analysis.metric_contract_v2 import MetricValueStateV2
from prompt_enhancer.application.analysis.metric_projection_v6 import (
    METRIC_PROJECTION_V6_VERSION,
    REASON_REQUIREMENT_PLAN_INVALID,
    REASON_REQUIREMENT_PLAN_UNAVAILABLE,
    project_metric_states_v6,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_METRIC_KEY,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    ConfirmedPlanEvidence,
    ConfirmedRequirementEvidence,
    ExcludedRequirementClause,
    PlanCoordinate,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanExclusionReason,
    RequirementPlanProducerReceipt,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.domain import Provider


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-v6:{label}".encode()).hexdigest()


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()

    def fingerprint_secret(self, namespace, values, secret):  # type: ignore[no-untyped-def]
        return hashlib.sha256(
            "\x1f".join((namespace, *values, secret.get_secret_value())).encode()
        ).hexdigest()


IDS = _Ids()
PRODUCER_RECEIPT = RequirementPlanProducerReceipt(
    claim_fingerprint=_id("producer-claim"),
)


def _context() -> P1TextAnalysisInput:
    request = EphemeralRedactedMessage(
        message_id=_id("request"),
        sequence=1,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(
            "Create the fictional export. Add a bounded test. Document the result."
        ),
    )
    plan = EphemeralRedactedMessage(
        message_id=_id("plan"),
        sequence=2,
        role=TextRole.AGENT,
        kind=TextMessageKind.PLAN,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Implement the export. Run the bounded test."),
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.PLAN}
        ),
        analysis_window_fingerprint=_id("window"),
        focus_message_id=request.message_id,
        observed_message_count=2,
        eligible_message_count=2,
        messages=(request, plan),
        task_profile=TextTaskProfile(applicability=()),
    )


def _snapshot(
    context: P1TextAnalysisInput,
    classifications: tuple[RequirementDisposition | None, ...],
) -> RequirementPlanEvidenceSnapshot:
    plan_id = _id("plan-unit")
    requirements = tuple(
        ConfirmedRequirementEvidence(
            requirement_id=_id(f"requirement-{index}"),
            coordinate=RequirementCoordinate(
                message_sequence=1,
                clause_index=index,
            ),
            disposition=disposition,
            linked_plan_ids=(
                (plan_id,) if disposition is RequirementDisposition.LINKED else ()
            ),
        )
        for index, disposition in enumerate(classifications)
        if disposition is not None
    )
    excluded = tuple(
        ExcludedRequirementClause(
            coordinate=RequirementCoordinate(
                message_sequence=1, clause_index=index
            ),
            reason=RequirementPlanExclusionReason.NOT_REQUIREMENT,
        )
        for index, disposition in enumerate(classifications)
        if disposition is None
    )
    return RequirementPlanEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
        confirmation_id=_id("confirmation"),
        proposal_id=_id("proposal"),
        producer_receipt=PRODUCER_RECEIPT,
        review_rubric_version=REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        excluded_user_clauses=excluded,
        plan_items=(
            ConfirmedPlanEvidence(
                plan_id=plan_id,
                coordinate=PlanCoordinate(message_sequence=2, clause_index=0),
            ),
        ),
        complete_user_clause_classification=True,
    )


def _decomposition(context, evidence):  # type: ignore[no-untyped-def]
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    states = project_metric_states_v6(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
        requirement_plan_evidence=evidence,
    )
    assert len(states) == 20
    assert {state.projection_version for state in states} == {
        METRIC_PROJECTION_V6_VERSION
    }
    return next(state for state in states if state.metric_key == REQUIREMENT_PLAN_METRIC_KEY)


def test_unconfirmed_or_absent_bundle_stays_unknown_not_zero() -> None:
    state = _decomposition(_context(), None)
    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_PLAN_UNAVAILABLE
    assert state.numerator is state.denominator is state.numeric_value is None


def test_confirmed_empty_complete_clause_enumeration_is_not_applicable() -> None:
    original = _context()
    plan = original.messages[1]
    context = original.model_copy(
        update={
            "available_message_kinds": frozenset({TextMessageKind.PLAN}),
            "focus_message_id": plan.message_id,
            "observed_message_count": 1,
            "eligible_message_count": 1,
            "messages": (plan,),
        }
    )
    empty = RequirementPlanEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
        confirmation_id=_id("empty-confirmation"),
        proposal_id=_id("empty-proposal"),
        producer_receipt=PRODUCER_RECEIPT,
        review_rubric_version=REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        complete_user_clause_classification=True,
    )
    state = _decomposition(context, empty)
    assert state.value_state is MetricValueStateV2.NOT_APPLICABLE
    assert state.statistics.eligible_count == 0


def test_confirmed_empty_cannot_erase_visible_user_clause_opportunities() -> None:
    context = _context()
    empty = RequirementPlanEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
        confirmation_id=_id("forged-empty-confirmation"),
        proposal_id=_id("forged-empty-proposal"),
        producer_receipt=PRODUCER_RECEIPT,
        review_rubric_version=REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        complete_user_clause_classification=True,
    )

    state = _decomposition(context, empty)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_PLAN_INVALID


def test_confirmed_complete_classification_with_no_active_requirements_is_na() -> None:
    context = _context()
    state = _decomposition(context, _snapshot(context, (None, None, None)))

    assert state.value_state is MetricValueStateV2.NOT_APPLICABLE
    assert state.statistics.eligible_count == 0
    assert state.numerator is state.denominator is state.numeric_value is None


def test_reviewed_links_and_closed_horizon_produce_known_ratio() -> None:
    context = _context()
    state = _decomposition(
        context,
        _snapshot(
            context,
            (
                RequirementDisposition.LINKED,
                RequirementDisposition.NOT_LINKED,
                None,
            ),
        ),
    )
    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (
        1,
        2,
        1 / 2,
    )
    assert state.statistics.distinct_owner_count == 2


def test_clause_overflow_fails_closed_instead_of_truncating_the_denominator() -> None:
    context = _context()
    request, plan = context.messages
    overflowing = request.model_copy(
        update={
            "text": SecretStr(
                " ".join(f"Synthetic clause {index}." for index in range(129))
            )
        }
    )
    context = context.model_copy(update={"messages": (overflowing, plan)})

    state = _decomposition(context, None)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_PLAN_INVALID


def test_pending_requirement_is_right_censored_with_truthful_bounds() -> None:
    context = _context()
    state = _decomposition(
        context,
        _snapshot(
            context,
            (
                RequirementDisposition.LINKED,
                RequirementDisposition.PENDING,
                None,
            ),
        ),
    )
    assert state.value_state is MetricValueStateV2.PENDING
    assert state.numerator is state.denominator is None
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (1 / 2, 1.0)


def test_out_of_range_or_wrong_role_coordinates_fail_closed() -> None:
    context = _context()
    invalid = _snapshot(
        context,
        (RequirementDisposition.LINKED, None, None),
    ).model_copy(
        update={
            "requirements": (
                ConfirmedRequirementEvidence(
                    requirement_id=_id("invalid-requirement"),
                    coordinate=RequirementCoordinate(
                        message_sequence=2,
                        clause_index=0,
                    ),
                    disposition=RequirementDisposition.LINKED,
                    linked_plan_ids=(_id("plan-unit"),),
                ),
            )
        }
    )
    state = _decomposition(context, invalid)
    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_PLAN_INVALID


def test_exclusion_basis_is_revalidated_before_a_numeric_projection() -> None:
    context = _context()
    snapshot = _snapshot(
        context,
        (RequirementDisposition.LINKED, None, None),
    )
    forged = snapshot.model_copy(
        update={
            "excluded_user_clauses": (
                ExcludedRequirementClause(
                    coordinate=RequirementCoordinate(
                        message_sequence=1, clause_index=1
                    ),
                    reason=RequirementPlanExclusionReason.DUPLICATE,
                    basis_coordinate=RequirementCoordinate(
                        message_sequence=99, clause_index=0
                    ),
                ),
                snapshot.excluded_user_clauses[1],
            )
        }
    )

    state = _decomposition(context, forged)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_PLAN_INVALID
