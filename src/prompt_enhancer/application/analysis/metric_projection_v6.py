"""Projection r6: reviewed requirement-to-plan decomposition coverage.

Projection r5 remains frozen and readable.  R6 replaces exactly
``logic.decomposition_coverage`` with a denominator supplied by a complete,
native-confirmed, content-free classification of reviewable user
request/feedback clauses.  Only clauses confirmed as active requirements enter
the denominator.  One active-requirement coordinate is one coarse opportunity;
compound clauses are deliberately not split by a model.  Agent/model proposals
never become values by themselves; classifications and coordinates are
revalidated against the exact ephemeral source window on every projection.
"""

from __future__ import annotations

from collections.abc import Mapping

from .metric_contract_v2 import (
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
    OpportunityState,
)
from .metric_lifecycle_evidence import MetricLifecycleEvidenceSnapshot
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_6,
    LiveMetricStateProjectionV2,
    MetricStateV2,
    _issue_metric_state_projection,
    _Opportunity,
    _statistics,
    resolve_metric_state,
)
from .metric_projection_v5 import project_metric_states_v5
from .objective_metric_projection import ObjectiveMetricOverride
from .requirement_plan_evidence import (
    MAX_REQUIREMENT_PLAN_UNITS,
    REQUIREMENT_PLAN_METRIC_KEY,
    RequirementDisposition,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanExclusionReason,
    reviewable_message_clauses,
)
from .semantic_units import SemanticUnitIdFactory, SemanticUnitReconciliation
from .text_contracts import (
    P1TextAnalysisInput,
    TextMessageKind,
    TextMetricResult,
    TextRole,
)


METRIC_PROJECTION_V6_VERSION = METRIC_PROJECTION_V2_VERSION_6
METRIC_PROJECTION_V6_ALGORITHM_ID = (
    "reviewed.requirement-plan.coordinates.contract-v2-opportunities"
)
METRIC_PROJECTION_V6_ALGORITHM_VERSION = "6"
REASON_REVIEWED_REQUIREMENT_PLAN_LINKS = "reviewed_requirement_plan_links"
REASON_REQUIREMENT_PLAN_UNAVAILABLE = "requirement_plan_evidence_unavailable"
REASON_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED = (
    "requirement_plan_evidence_confirmation_required"
)
REASON_REQUIREMENT_PLAN_INVALID = "requirement_plan_evidence_invalid"


def _unavailable_state(
    *,
    code: str,
    capability_available: bool = False,
    source_complete: bool = True,
):
    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == REQUIREMENT_PLAN_METRIC_KEY
    )
    return resolve_metric_state(
        contract,
        _statistics(
            contract,
            (),
            capability_available=capability_available,
            source_complete=source_complete,
        ),
        explanation_code=code,
        unavailable_code=code,
        projection_version=METRIC_PROJECTION_V6_VERSION,
    )


def _invalid_state() -> MetricStateV2:
    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == REQUIREMENT_PLAN_METRIC_KEY
    )
    return MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.UNKNOWN,
        explanation_code=REASON_REQUIREMENT_PLAN_INVALID,
        statistics=_statistics(
            contract,
            (),
            capability_available=True,
            source_complete=False,
        ),
        projection_version=METRIC_PROJECTION_V6_VERSION,
    )


def _awaiting_confirmation_state() -> MetricStateV2:
    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == REQUIREMENT_PLAN_METRIC_KEY
    )
    return MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.UNKNOWN,
        explanation_code=REASON_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED,
        statistics=_statistics(
            contract,
            (),
            capability_available=True,
            source_complete=True,
        ),
        projection_version=METRIC_PROJECTION_V6_VERSION,
    )


def _decomposition_state_v6(
    *,
    context: P1TextAnalysisInput,
    evidence: RequirementPlanEvidenceSnapshot | None,
):
    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == REQUIREMENT_PLAN_METRIC_KEY
    )
    try:
        expected_user_clause_coordinates = tuple(
            sorted(
                (message.sequence, clause_index)
                for message in context.messages
                if message.role is TextRole.USER
                and message.kind
                in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
                for clause_index in range(
                    len(
                        reviewable_message_clauses(
                            message.text.get_secret_value()
                        )
                    )
                )
            )
        )
    except ValueError:
        return _invalid_state()
    if len(expected_user_clause_coordinates) > MAX_REQUIREMENT_PLAN_UNITS:
        return _invalid_state()
    if evidence is None:
        return _unavailable_state(code=REASON_REQUIREMENT_PLAN_UNAVAILABLE)
    if not evidence.complete_user_clause_classification:
        return _awaiting_confirmation_state()
    if (
        evidence.session_id != context.session_id
        or evidence.source_window_fingerprint
        != context.analysis_window_fingerprint
        or evidence.confirmation_id is None
    ):
        return _invalid_state()

    messages = {message.sequence: message for message in context.messages}
    plans = {item.plan_id: item for item in evidence.plan_items}
    try:
        active_requirement_coordinates = tuple(
            sorted(
                (
                    item.coordinate.message_sequence,
                    item.coordinate.clause_index,
                )
                for item in evidence.requirements
            )
        )
        excluded_user_clause_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in evidence.excluded_user_clauses
        )
        classified_coordinates = tuple(
            sorted(
                (*active_requirement_coordinates, *excluded_user_clause_coordinates)
            )
        )
        if (
            len(set(classified_coordinates)) != len(classified_coordinates)
            or classified_coordinates != expected_user_clause_coordinates
        ):
            raise ValueError("requirement clause classification is incomplete")
        active_coordinate_set = set(active_requirement_coordinates)
        user_coordinate_set = set(expected_user_clause_coordinates)
        for excluded in evidence.excluded_user_clauses:
            basis = excluded.basis_coordinate
            if basis is None:
                continue
            excluded_key = (
                excluded.coordinate.message_sequence,
                excluded.coordinate.clause_index,
            )
            basis_key = (basis.message_sequence, basis.clause_index)
            if basis_key not in user_coordinate_set:
                raise ValueError("excluded requirement basis is absent")
            if excluded.reason in {
                RequirementPlanExclusionReason.SUPERSEDED,
                RequirementPlanExclusionReason.WITHDRAWN,
            } and basis_key <= excluded_key:
                raise ValueError("exclusion basis does not follow its requirement")
            if (
                excluded.reason is RequirementPlanExclusionReason.DUPLICATE
                and basis_key not in active_coordinate_set
            ):
                raise ValueError("duplicate exclusion lacks an active owner")
        for item in evidence.plan_items:
            message = messages[item.coordinate.message_sequence]
            if (
                message.role is not TextRole.AGENT
                or message.kind is not TextMessageKind.PLAN
                or item.coordinate.clause_index
                >= len(reviewable_message_clauses(message.text.get_secret_value()))
            ):
                raise ValueError("invalid plan coordinate")
        opportunities = []
        for item in evidence.requirements:
            message = messages[item.coordinate.message_sequence]
            if (
                message.role is not TextRole.USER
                or message.kind
                not in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
                or item.coordinate.clause_index
                >= len(reviewable_message_clauses(message.text.get_secret_value()))
            ):
                raise ValueError("invalid requirement coordinate")
            if any(
                plans[plan_id].coordinate.message_sequence
                < item.coordinate.message_sequence
                for plan_id in item.linked_plan_ids
            ):
                raise ValueError("a linked plan precedes its requirement")
            state = {
                RequirementDisposition.LINKED: OpportunityState.MET,
                RequirementDisposition.NOT_LINKED: OpportunityState.NOT_MET,
                RequirementDisposition.PENDING: OpportunityState.PENDING,
            }[item.disposition]
            opportunities.append(
                _Opportunity(
                    unit_id=item.requirement_id,
                    owner_source_digest=item.requirement_id,
                    state=state,
                )
            )
    except (KeyError, TypeError, ValueError):
        return _invalid_state()
    return resolve_metric_state(
        contract,
        _statistics(
            contract,
            tuple(opportunities),
            capability_available=True,
            source_complete=True,
        ),
        explanation_code=REASON_REVIEWED_REQUIREMENT_PLAN_LINKS,
        projection_version=METRIC_PROJECTION_V6_VERSION,
    )


def project_metric_states_v6(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
    conversational_results: Mapping[str, TextMetricResult] | None = None,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
    lifecycle_evidence: MetricLifecycleEvidenceSnapshot | None = None,
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None = None,
) -> LiveMetricStateProjectionV2:
    """Project all twenty contracts under append-only identity r6."""

    inherited = project_metric_states_v5(
        context=context,
        reconciliation=reconciliation,
        id_factory=id_factory,
        conversational_results=conversational_results,
        objective_overrides=objective_overrides,
        lifecycle_evidence=lifecycle_evidence,
    )
    decomposition = _decomposition_state_v6(
        context=context,
        evidence=requirement_plan_evidence,
    )
    states = tuple(
        decomposition
        if state.metric_key == REQUIREMENT_PLAN_METRIC_KEY
        else state.model_copy(
            update={"projection_version": METRIC_PROJECTION_V6_VERSION}
        )
        for state in inherited
    )
    if len(states) != len(METRIC_CONTRACTS_V2) or any(
        state.projection_version != METRIC_PROJECTION_V6_VERSION for state in states
    ):
        raise AssertionError("r6 projection produced an incomplete identity")
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = (
    "METRIC_PROJECTION_V6_ALGORITHM_ID",
    "METRIC_PROJECTION_V6_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V6_VERSION",
    "REASON_REQUIREMENT_PLAN_INVALID",
    "REASON_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED",
    "REASON_REQUIREMENT_PLAN_UNAVAILABLE",
    "REASON_REVIEWED_REQUIREMENT_PLAN_LINKS",
    "project_metric_states_v6",
)
