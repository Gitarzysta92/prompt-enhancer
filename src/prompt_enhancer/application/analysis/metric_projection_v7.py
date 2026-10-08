"""Projection r7: native-reviewed requirement-to-safe-action traceability.

Projection r6 remains frozen and readable.  R7 replaces exactly
``logic.requirement_action_traceability``.  Its denominator is the exact
native-confirmed active requirement set already validated by r6; its outcomes
come from a complete native review against one app-issued, content-free safe
action manifest.  Provider action state remains provider evidence and the
review supplies links only.  Neither an agent proposal nor an assistant claim
can become a metric value.
"""

from __future__ import annotations

from collections.abc import Mapping

from .evidence_contracts import ActionState
from .metric_contract_v2 import (
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
    OpportunityState,
)
from .metric_lifecycle_evidence import MetricLifecycleEvidenceSnapshot
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_7,
    LiveMetricStateProjectionV2,
    MetricStateV2,
    _issue_metric_state_projection,
    _Opportunity,
    _statistics,
    reviewed_requirement_plan_denominator_is_authoritative,
    resolve_metric_state,
)
from .metric_projection_v6 import project_metric_states_v6
from .objective_metric_projection import ObjectiveMetricOverride
from .provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SUPPORTED_SAFE_EVENT_EVIDENCE_DECODER_VERSIONS,
)
from .requirement_action_evidence import (
    MAX_REQUIREMENT_ACTION_CANDIDATES,
    MAX_REQUIREMENT_ACTION_LINKS,
    MAX_REQUIREMENT_ACTION_REQUIREMENTS,
    REQUIREMENT_ACTION_METRIC_KEY,
    RequirementActionEvidenceSnapshot,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_plan_snapshot_fingerprint,
)
from .requirement_plan_evidence import (
    REQUIREMENT_PLAN_METRIC_KEY,
    RequirementPlanEvidenceSnapshot,
)
from .semantic_units import SemanticUnitIdFactory, SemanticUnitReconciliation
from .text_contracts import P1TextAnalysisInput, TextMetricResult
from ..providers.contracts import CapabilityKey, DecoderDescriptor


METRIC_PROJECTION_V7_VERSION = METRIC_PROJECTION_V2_VERSION_7
METRIC_PROJECTION_V7_ALGORITHM_ID = (
    "reviewed.requirement-safe-action.contract-v2-opportunities"
)
METRIC_PROJECTION_V7_ALGORITHM_VERSION = "7"
REASON_REVIEWED_REQUIREMENT_ACTION_LINKS = "reviewed_requirement_action_links"
REASON_REQUIREMENT_ACTION_UNAVAILABLE = "requirement_action_evidence_unavailable"
REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED = (
    "requirement_action_evidence_confirmation_required"
)
REASON_REQUIREMENT_ACTION_INVALID = "requirement_action_evidence_invalid"
REASON_REQUIREMENT_ACTION_OVERFLOW = "requirement_action_evidence_overflow"
REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE = (
    "requirement_action_candidate_source_incomplete"
)


def _contract():
    return next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == REQUIREMENT_ACTION_METRIC_KEY
    )


def _unknown_state(
    *,
    code: str,
    opportunities: tuple[_Opportunity, ...] = (),
    capability_available: bool,
    source_complete: bool,
) -> MetricStateV2:
    contract = _contract()
    return MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.UNKNOWN,
        explanation_code=code,
        statistics=_statistics(
            contract,
            opportunities,
            capability_available=capability_available,
            source_complete=source_complete,
        ),
        projection_version=METRIC_PROJECTION_V7_VERSION,
    )


def _unresolved_requirements(
    context: P1TextAnalysisInput,
    evidence: RequirementPlanEvidenceSnapshot | None,
    r6_requirement_state: MetricStateV2,
) -> tuple[_Opportunity, ...]:
    if evidence is None:
        return ()
    try:
        # ``model_copy`` is deliberately not validation.  Re-parse at this
        # authority boundary so a shape-invalid in-memory snapshot cannot lend
        # its apparent requirement count to the r7 denominator.
        validated_evidence = RequirementPlanEvidenceSnapshot.model_validate(
            evidence.model_dump(mode="python")
        )
    except (TypeError, ValueError):
        return ()
    if (
        validated_evidence.session_id != context.session_id
        or validated_evidence.source_window_fingerprint
        != context.analysis_window_fingerprint
        or not reviewed_requirement_plan_denominator_is_authoritative(
            r6_requirement_state
        )
        or r6_requirement_state.statistics.eligible_count
        != len(validated_evidence.requirements)
    ):
        return ()
    return tuple(
        _Opportunity(
            unit_id=item.requirement_id,
            owner_source_digest=item.requirement_id,
            state=OpportunityState.UNKNOWN,
        )
        for item in validated_evidence.requirements
    )


def _validated_requirement_plan_snapshot(
    evidence: RequirementPlanEvidenceSnapshot | None,
) -> RequirementPlanEvidenceSnapshot | None:
    if evidence is None:
        return None
    try:
        return RequirementPlanEvidenceSnapshot.model_validate(
            evidence.model_dump(mode="python")
        )
    except (TypeError, ValueError):
        return None


def _requirement_action_state_v7(
    *,
    context: P1TextAnalysisInput,
    id_factory: SemanticUnitIdFactory,
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None,
    requirement_action_evidence: RequirementActionEvidenceSnapshot | None,
    requirement_action_descriptor: DecoderDescriptor | None,
    candidate_manifest_overflow: bool,
    candidate_source_incomplete: bool,
    requirement_action_binding_invalid: bool,
    r6_requirement_state: MetricStateV2,
) -> MetricStateV2:
    unresolved = _unresolved_requirements(
        context,
        requirement_plan_evidence,
        r6_requirement_state,
    )
    if candidate_manifest_overflow:
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_OVERFLOW,
            opportunities=unresolved,
            capability_available=True,
            source_complete=True,
        )
    if candidate_source_incomplete:
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE,
            opportunities=unresolved,
            capability_available=True,
            source_complete=False,
        )
    if requirement_action_binding_invalid:
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_INVALID,
            opportunities=unresolved,
            capability_available=True,
            source_complete=False,
        )
    if requirement_action_evidence is None:
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_UNAVAILABLE,
            opportunities=unresolved,
            # The reviewed r6 denominator remains known, but the separate
            # action-link evidence service is unavailable.  R7 alone permits
            # this exact unknown partition without calling it measurable.
            capability_available=False,
            source_complete=True,
        )
    if (
        requirement_action_evidence.session_id != context.session_id
        or requirement_action_evidence.source_window_fingerprint
        != context.analysis_window_fingerprint
    ):
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_INVALID,
            opportunities=unresolved,
            capability_available=True,
            source_complete=False,
        )
    if (
        requirement_plan_evidence is None
        or r6_requirement_state.value_state is MetricValueStateV2.UNKNOWN
    ):
        return _unknown_state(
            code=(
                REASON_REQUIREMENT_ACTION_UNAVAILABLE
                if requirement_plan_evidence is None
                else REASON_REQUIREMENT_ACTION_INVALID
            ),
            opportunities=unresolved,
            capability_available=requirement_plan_evidence is not None,
            source_complete=requirement_plan_evidence is None,
        )
    complete_review = (
        requirement_action_evidence.complete_requirement_enumeration
        and requirement_action_evidence.complete_action_candidate_enumeration
        and requirement_action_evidence.complete_requirement_link_classification
    )
    if not complete_review:
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
            opportunities=unresolved,
            capability_available=True,
            source_complete=True,
        )
    if (
        len(requirement_plan_evidence.requirements)
        > MAX_REQUIREMENT_ACTION_REQUIREMENTS
    ):
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_OVERFLOW,
            opportunities=unresolved,
            capability_available=True,
            source_complete=True,
        )

    snapshot = requirement_action_evidence
    manifest = snapshot.candidate_manifest
    try:
        if (
            requirement_plan_evidence.confirmation_id is None
            or requirement_plan_evidence.proposal_id is None
            or requirement_plan_evidence.producer_receipt is None
            or not requirement_plan_evidence.complete_user_clause_classification
            or snapshot.requirement_plan_confirmation_id
            != requirement_plan_evidence.confirmation_id
            or snapshot.requirement_plan_evidence_fingerprint
            != requirement_plan_snapshot_fingerprint(
                requirement_plan_evidence,
                id_factory,
            )
            or snapshot.confirmation_id is None
            or snapshot.proposal_id is None
            or snapshot.producer_receipt is None
            or snapshot.evidence_fingerprint is None
            or snapshot.evidence_fingerprint
            != requirement_action_evidence_snapshot_fingerprint(
                snapshot,
                id_factory,
            )
            or manifest is None
            or manifest.manifest_fingerprint
            != requirement_action_candidate_manifest_fingerprint(manifest)
            or manifest.session_id != context.session_id
            or manifest.source_window_fingerprint
            != context.analysis_window_fingerprint
            or manifest.provenance.provider is not context.provider
            or manifest.provenance.provider_version != context.provider_version
            or requirement_action_descriptor is None
            or requirement_action_descriptor.provider.key != context.provider.value
            or requirement_action_descriptor.adapter_version
            != manifest.provenance.adapter_version
            or requirement_action_descriptor.canonical_schema_version
            != manifest.provenance.source_schema_version
            or requirement_action_descriptor.decoder_key
            != manifest.provenance.decoder_key
            or requirement_action_descriptor.decoder_version
            != manifest.provenance.decoder_version
            or CapabilityKey.TOOL_EVENTS
            not in requirement_action_descriptor.capabilities
            or manifest.provenance.decoder_key != SAFE_EVENT_EVIDENCE_DECODER_KEY
            or manifest.provenance.decoder_version
            not in SUPPORTED_SAFE_EVENT_EVIDENCE_DECODER_VERSIONS
            or not manifest.extraction_complete
            or not manifest.enumeration_complete
        ):
            raise ValueError("requirement-action authority binding is invalid")
        if len(manifest.actions) > MAX_REQUIREMENT_ACTION_CANDIDATES:
            return _unknown_state(
                code=REASON_REQUIREMENT_ACTION_OVERFLOW,
                opportunities=unresolved,
                capability_available=True,
                source_complete=True,
            )
        if sum(len(item.action_ids) for item in snapshot.links) > (
            MAX_REQUIREMENT_ACTION_LINKS
        ):
            return _unknown_state(
                code=REASON_REQUIREMENT_ACTION_OVERFLOW,
                opportunities=unresolved,
                capability_available=True,
                source_complete=True,
            )

        expected_requirements = tuple(
            (
                index,
                item.requirement_id,
                item.coordinate,
            )
            for index, item in enumerate(requirement_plan_evidence.requirements)
        )
        observed_requirements = tuple(
            (item.requirement_index, item.requirement_id, item.coordinate)
            for item in snapshot.requirements
        )
        if observed_requirements != expected_requirements:
            raise ValueError("reviewed requirement set differs from r6")

        action_by_id = {item.action_id: item for item in manifest.actions}
        if len(action_by_id) != len(manifest.actions):
            raise ValueError("candidate manifest repeats an action")
        source_references = tuple(
            item.source_reference_id for item in manifest.actions
        )
        if len(set(source_references)) != len(source_references):
            raise ValueError("candidate manifest repeats a provider receipt")
        links_by_requirement = {
            item.requirement_id: item.action_ids for item in snapshot.links
        }
        expected_ids = tuple(item.requirement_id for item in snapshot.requirements)
        if (
            tuple(item.requirement_id for item in snapshot.links) != expected_ids
            or len(links_by_requirement) != len(expected_ids)
            or any(
                action_id not in action_by_id
                for action_ids in links_by_requirement.values()
                for action_id in action_ids
            )
        ):
            raise ValueError("reviewed links do not exactly cover the denominator")

        opportunities = []
        for requirement in snapshot.requirements:
            linked = tuple(
                action_by_id[action_id]
                for action_id in links_by_requirement[requirement.requirement_id]
            )
            states = {item.state for item in linked}
            if ActionState.COMPLETED in states:
                state = OpportunityState.MET
            elif states & {ActionState.STARTED, ActionState.UNKNOWN}:
                state = OpportunityState.PENDING
            else:
                # This is a measured negative only because extraction,
                # enumeration, and native exact-cover review were all proven
                # above.  Empty links and failed/cancelled-only links are not
                # negatives anywhere else.
                state = OpportunityState.NOT_MET
            opportunities.append(
                _Opportunity(
                    unit_id=requirement.requirement_id,
                    owner_source_digest=requirement.requirement_id,
                    state=state,
                )
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        return _unknown_state(
            code=REASON_REQUIREMENT_ACTION_INVALID,
            opportunities=unresolved,
            capability_available=True,
            source_complete=False,
        )

    contract = _contract()
    return resolve_metric_state(
        contract,
        _statistics(
            contract,
            tuple(opportunities),
            capability_available=True,
            source_complete=True,
        ),
        explanation_code=REASON_REVIEWED_REQUIREMENT_ACTION_LINKS,
        projection_version=METRIC_PROJECTION_V7_VERSION,
    )


def project_metric_states_v7(
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
    """Project all twenty contracts under append-only identity r7."""

    validated_requirement_plan = _validated_requirement_plan_snapshot(
        requirement_plan_evidence
    )
    inherited = project_metric_states_v6(
        context=context,
        reconciliation=reconciliation,
        id_factory=id_factory,
        conversational_results=conversational_results,
        objective_overrides=objective_overrides,
        lifecycle_evidence=lifecycle_evidence,
        requirement_plan_evidence=validated_requirement_plan,
    )
    r6_requirement_state = next(
        state
        for state in inherited
        if state.metric_key == REQUIREMENT_PLAN_METRIC_KEY
    )
    requirement_action = _requirement_action_state_v7(
        context=context,
        id_factory=id_factory,
        requirement_plan_evidence=validated_requirement_plan,
        requirement_action_evidence=requirement_action_evidence,
        requirement_action_descriptor=requirement_action_descriptor,
        candidate_manifest_overflow=candidate_manifest_overflow,
        candidate_source_incomplete=candidate_source_incomplete,
        requirement_action_binding_invalid=(
            requirement_action_binding_invalid
        ),
        r6_requirement_state=r6_requirement_state,
    )
    states = tuple(
        requirement_action
        if state.metric_key == REQUIREMENT_ACTION_METRIC_KEY
        else state.model_copy(
            update={"projection_version": METRIC_PROJECTION_V7_VERSION}
        )
        for state in inherited
    )
    if len(states) != len(METRIC_CONTRACTS_V2) or any(
        state.projection_version != METRIC_PROJECTION_V7_VERSION
        for state in states
    ):
        raise AssertionError("r7 projection produced an incomplete identity")
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = (
    "METRIC_PROJECTION_V7_ALGORITHM_ID",
    "METRIC_PROJECTION_V7_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V7_VERSION",
    "REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED",
    "REASON_REQUIREMENT_ACTION_INVALID",
    "REASON_REQUIREMENT_ACTION_OVERFLOW",
    "REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE",
    "REASON_REQUIREMENT_ACTION_UNAVAILABLE",
    "REASON_REVIEWED_REQUIREMENT_ACTION_LINKS",
    "project_metric_states_v7",
)
