"""Projection r8: exact persisted requirement-verification evidence.

Projection r7 remains frozen and readable. R8 preserves every r7 metric-state
rule and changes only the append-only projection identity; the caller supplies
the objective-v4 override that is bound to one persisted M58 revision.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..providers.contracts import DecoderDescriptor
from .metric_contract_v2 import METRIC_CONTRACTS_V2, MetricValueStateV2
from .metric_lifecycle_evidence import MetricLifecycleEvidenceSnapshot
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_8,
    LiveMetricStateProjectionV2,
    MetricStateV2,
    OpportunityStatistics,
    _issue_metric_state_projection,
)
from .metric_projection_v7 import project_metric_states_v7
from .objective_metric_projection import (
    ObjectiveMetricOverride,
    ObjectiveWithholdingCause,
)
from .requirement_action_evidence import RequirementActionEvidenceSnapshot
from .requirement_plan_evidence import RequirementPlanEvidenceSnapshot
from .requirement_verification_evidence import VERIFIED_REQUIREMENT_METRIC_KEY
from .semantic_units import SemanticUnitIdFactory, SemanticUnitReconciliation
from .text_contracts import P1TextAnalysisInput, TextMetricResult


METRIC_PROJECTION_V8_VERSION = METRIC_PROJECTION_V2_VERSION_8
METRIC_PROJECTION_V8_ALGORITHM_ID = (
    "persisted.requirement-verification.contract-v2-opportunities"
)
METRIC_PROJECTION_V8_ALGORITHM_VERSION = "8"


def _verified_requirement_state_v8(
    override: ObjectiveMetricOverride | None,
) -> MetricStateV2 | None:
    """Preserve the exact objective-v4 authority result in the r8 row."""

    if override is None:
        return None
    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == VERIFIED_REQUIREMENT_METRIC_KEY
    )
    eligible = override.eligible_opportunity_count
    resolved = override.resolved_opportunity_count
    met = override.met_opportunity_count
    invalid_authority = override.explanation_code in {
        "reviewed_requirement_authority_invalid",
        "requirement_verification_authority_invalid",
    }
    capability_available = override.explanation_code not in {
        "reviewed_requirement_authority_unavailable",
    }
    source_complete = not invalid_authority
    unresolved = eligible - resolved
    value_state = MetricValueStateV2(override.value_state.value)
    known = value_state is MetricValueStateV2.KNOWN
    bounds = (
        None
        if eligible == 0
        else (
            met / eligible,
            (met + unresolved) / eligible,
        )
    )
    # The pure v4 cause remains useful here as a defensive consistency check:
    # a supposedly published value may never carry a withholding cause.
    if known and override.withholding_cause is not ObjectiveWithholdingCause.NOT_WITHHELD:
        raise ValueError("known requirement verification carries a withholding cause")
    return MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=value_state,
        explanation_code=override.explanation_code,
        numerator=override.numerator if known else None,
        denominator=override.denominator if known else None,
        numeric_value=(
            None
            if not known
            else override.numerator / override.denominator  # type: ignore[operator]
        ),
        censoring_lower_bound=None if bounds is None else bounds[0],
        censoring_upper_bound=None if bounds is None else bounds[1],
        statistics=OpportunityStatistics(
            metric_key=contract.metric_key,
            denominator_basis=contract.denominator_basis,
            opportunity_unit_kind=contract.opportunity_unit_kind,
            capability_available=capability_available,
            source_complete=source_complete,
            eligible_count=eligible,
            met_count=met,
            not_met_count=resolved - met,
            pending_count=0,
            unknown_count=unresolved,
            superseded_excluded_count=0,
            distinct_owner_count=eligible,
        ),
        projection_version=METRIC_PROJECTION_V8_VERSION,
    )


def project_metric_states_v8(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
    conversational_results: Mapping[str, TextMetricResult] | None = None,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
    lifecycle_evidence: MetricLifecycleEvidenceSnapshot | None = None,
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None = None,
    requirement_action_evidence: RequirementActionEvidenceSnapshot | None = None,
    requirement_action_descriptor: DecoderDescriptor | None = None,
    candidate_manifest_overflow: bool = False,
    candidate_source_incomplete: bool = False,
    requirement_action_binding_invalid: bool = False,
) -> LiveMetricStateProjectionV2:
    """Project all twenty contracts under append-only identity r8."""

    if (
        objective_overrides is None
        or VERIFIED_REQUIREMENT_METRIC_KEY not in objective_overrides
    ):
        raise ValueError(
            "r8 projection requires the verified-requirement objective-v4 override"
        )

    inherited = project_metric_states_v7(
        context=context,
        reconciliation=reconciliation,
        id_factory=id_factory,
        conversational_results=conversational_results,
        objective_overrides=objective_overrides,
        lifecycle_evidence=lifecycle_evidence,
        requirement_plan_evidence=requirement_plan_evidence,
        requirement_action_evidence=requirement_action_evidence,
        requirement_action_descriptor=requirement_action_descriptor,
        candidate_manifest_overflow=candidate_manifest_overflow,
        candidate_source_incomplete=candidate_source_incomplete,
        requirement_action_binding_invalid=requirement_action_binding_invalid,
    )
    verified_requirement = _verified_requirement_state_v8(
        objective_overrides[VERIFIED_REQUIREMENT_METRIC_KEY]
    )
    if verified_requirement is None:  # pragma: no cover - guarded above
        raise AssertionError("r8 verified-requirement override was not projected")
    states = tuple(
        verified_requirement
        if state.metric_key == VERIFIED_REQUIREMENT_METRIC_KEY
        and verified_requirement is not None
        else state.model_copy(
            update={"projection_version": METRIC_PROJECTION_V8_VERSION}
        )
        for state in inherited
    )
    if len(states) != len(METRIC_CONTRACTS_V2) or any(
        state.projection_version != METRIC_PROJECTION_V8_VERSION
        for state in states
    ):
        raise AssertionError("r8 projection produced an incomplete identity")
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = (
    "METRIC_PROJECTION_V8_ALGORITHM_ID",
    "METRIC_PROJECTION_V8_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V8_VERSION",
    "project_metric_states_v8",
)
