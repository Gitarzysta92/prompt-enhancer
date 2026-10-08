"""Projection r4: confirmed structured evidence for collaboration lifecycles.

Projection r3 remains frozen and readable.  R4 inherits every r3 decision and
replaces exactly five collaboration rows with a content-free, authenticated
local-user evidence seam.  A proposal is never evidence by itself.  Only
confirmed opportunities in a confirmed complete family enumeration form the
denominator; unresolved confirmed opportunities are right-censored.
"""

from __future__ import annotations

from collections.abc import Mapping

from .metric_contract_v2 import METRIC_CONTRACTS_V2, MetricContractV2, MetricValueStateV2, OpportunityState
from .metric_lifecycle_evidence import (
    MET_OUTCOME_KINDS,
    MetricLifecycleEvidenceSnapshot,
    MetricLifecycleFamily,
    MetricLifecycleFamilyEvidence,
)
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_4,
    LiveMetricStateProjectionV2,
    MetricStateV2,
    _issue_metric_state_projection,
    _Opportunity,
    _statistics,
    resolve_metric_state,
)
from .metric_projection_v3 import project_metric_states_v3
from .objective_metric_projection import ObjectiveMetricOverride
from .semantic_units import SemanticUnitIdFactory, SemanticUnitReconciliation
from .text_contracts import P1TextAnalysisInput, TextMetricResult


METRIC_PROJECTION_V4_VERSION = METRIC_PROJECTION_V2_VERSION_4
METRIC_PROJECTION_V4_ALGORITHM_ID = "rules.confirmed-lifecycle.contract-v2-opportunities"
METRIC_PROJECTION_V4_ALGORITHM_VERSION = "4"
REASON_LIFECYCLE_SERVICE_UNAVAILABLE = "confirmed_lifecycle_service_unavailable"
REASON_LIFECYCLE_ENUMERATION_REQUIRED = "confirmed_lifecycle_enumeration_required"
REASON_CONFIRMED_LIFECYCLE_EVIDENCE = "confirmed_lifecycle_evidence"

LIFECYCLE_METRIC_FAMILIES = {
    family.value: family for family in MetricLifecycleFamily
}


def _lifecycle_opportunities(
    evidence: MetricLifecycleFamilyEvidence,
) -> tuple[_Opportunity, ...]:
    opportunities = []
    for item in evidence.opportunities:
        if item.outcome is None:
            state = OpportunityState.PENDING
        elif item.outcome.outcome_kind in MET_OUTCOME_KINDS:
            state = OpportunityState.MET
        else:
            state = OpportunityState.NOT_MET
        opportunities.append(
            _Opportunity(
                unit_id=item.opportunity_id,
                owner_source_digest=item.opportunity_id,
                state=state,
            )
        )
    return tuple(opportunities)


def lifecycle_metric_state_v4(
    contract: MetricContractV2,
    evidence: MetricLifecycleFamilyEvidence | None,
) -> MetricStateV2:
    """Resolve one collaboration metric from confirmation receipts only."""

    if contract.metric_key not in LIFECYCLE_METRIC_FAMILIES:
        raise ValueError("metric is not owned by the lifecycle receipt projector")
    if evidence is None:
        return resolve_metric_state(
            contract,
            _statistics(
                contract,
                (),
                capability_available=False,
                source_complete=False,
            ),
            explanation_code=REASON_LIFECYCLE_SERVICE_UNAVAILABLE,
            unavailable_code=REASON_LIFECYCLE_SERVICE_UNAVAILABLE,
            projection_version=METRIC_PROJECTION_V4_VERSION,
        )
    expected_family = LIFECYCLE_METRIC_FAMILIES[contract.metric_key]
    if evidence.family is not expected_family:
        raise ValueError("lifecycle evidence is bound to another metric family")
    opportunities = _lifecycle_opportunities(evidence)
    statistics = _statistics(
        contract,
        opportunities,
        capability_available=True,
        source_complete=evidence.enumeration_confirmed,
    )
    if not evidence.enumeration_confirmed:
        # A partial confirmed set is useful readiness evidence but not a valid
        # denominator.  Do not call the shared resolver here: its generic
        # source-reconciliation reason would hide the exact user action needed.
        return MetricStateV2(
            metric_key=contract.metric_key,
            contract_version=contract.contract_version,
            contract_fingerprint=contract.fingerprint,
            evidence_authority=contract.evidence_authority,
            value_state=MetricValueStateV2.UNKNOWN,
            explanation_code=REASON_LIFECYCLE_ENUMERATION_REQUIRED,
            statistics=statistics,
            projection_version=METRIC_PROJECTION_V4_VERSION,
        )
    return resolve_metric_state(
        contract,
        statistics,
        explanation_code=REASON_CONFIRMED_LIFECYCLE_EVIDENCE,
        projection_version=METRIC_PROJECTION_V4_VERSION,
    )


def project_metric_states_v4(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
    conversational_results: Mapping[str, TextMetricResult] | None = None,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
    lifecycle_evidence: MetricLifecycleEvidenceSnapshot | None = None,
) -> LiveMetricStateProjectionV2:
    """Project all twenty contracts under append-only identity r4."""

    if lifecycle_evidence is not None and (
        lifecycle_evidence.session_id != context.session_id
        or lifecycle_evidence.source_window_fingerprint
        != context.analysis_window_fingerprint
    ):
        raise ValueError("lifecycle evidence describes another analysis window")
    inherited = project_metric_states_v3(
        context=context,
        reconciliation=reconciliation,
        id_factory=id_factory,
        conversational_results=conversational_results,
        objective_overrides=objective_overrides,
    )
    inherited_by_key = {state.metric_key: state for state in inherited}
    evidence_by_family = (
        {}
        if lifecycle_evidence is None
        else {item.family: item for item in lifecycle_evidence.families}
    )
    states = []
    for contract in METRIC_CONTRACTS_V2:
        family = LIFECYCLE_METRIC_FAMILIES.get(contract.metric_key)
        if family is not None:
            states.append(
                lifecycle_metric_state_v4(
                    contract,
                    evidence_by_family.get(family),
                )
            )
        else:
            inherited_state = inherited_by_key[contract.metric_key]
            states.append(
                inherited_state.model_copy(
                    update={"projection_version": METRIC_PROJECTION_V4_VERSION}
                )
            )
    if len(states) != len(METRIC_CONTRACTS_V2) or any(
        state.projection_version != METRIC_PROJECTION_V4_VERSION
        for state in states
    ):
        raise AssertionError("r4 projection produced an incomplete identity")
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = [
    "LIFECYCLE_METRIC_FAMILIES",
    "METRIC_PROJECTION_V4_ALGORITHM_ID",
    "METRIC_PROJECTION_V4_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V4_VERSION",
    "REASON_CONFIRMED_LIFECYCLE_EVIDENCE",
    "REASON_LIFECYCLE_ENUMERATION_REQUIRED",
    "REASON_LIFECYCLE_SERVICE_UNAVAILABLE",
    "lifecycle_metric_state_v4",
    "project_metric_states_v4",
]
