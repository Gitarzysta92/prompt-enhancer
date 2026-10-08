"""Per-metric evidence readiness derived from one sealed V2 publication.

This is a *derived* API projection, not a second measurement and not a second
persistence record.  Every field is either a closed enum, a count, or a bound
that already exists in the sealed ``MetricPublicationV2`` rows, plus the run's
own provider/adapter/source-schema provenance.  Because it introduces no
independent datum, it needs no schema of its own: it is recomputed from the
sealed v40/v41/v42/v44 sidecar on read and disappears with the run.

What it adds over the publication is the *reason a value is missing*, stated as
a requirement of that exact metric rather than a generic "unobservable":

* a rubric metric names the focus-owned request revision it needs;
* a profile-slot metric names the declared profile it needs;
* each conversational episode metric names the semantic-unit family whose
  extractor would have to exist before an empty set could mean anything;
* each objective metric names the exact enumeration, link, and outcome
  capabilities its adapter must jointly declare.

It never carries identifiers, message text, per-factor detail, or a ranking,
and it never converts a missing value into zero.  ``calibration_state`` stays
``not_assessed`` and ``product_metric_eligible`` stays ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from ...domain import Provider, SAFE_VERSION_PATTERN, StrictModel
from ..providers import CapabilityKey
from .metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    MetricValueStateV2,
)
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_1,
    METRIC_PROJECTION_V2_VERSION_3,
    METRIC_PROJECTION_V2_VERSION_4,
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
    MetricProjectionV2Version,
    MetricStateV2,
)
from .metric_projection_v7 import (
    REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
    REASON_REQUIREMENT_ACTION_INVALID,
    REASON_REQUIREMENT_ACTION_OVERFLOW,
    REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE,
    REASON_REQUIREMENT_ACTION_UNAVAILABLE,
)
from .metric_publication_v2 import (
    MetricPublicationSource,
    MetricPublicationV2,
    _validate_r7_requirement_action_denominator,
    metric_publication_v2_fingerprint,
)
from .semantic_units import SemanticUnitKind


METRIC_EVIDENCE_READINESS_V2_KEY = "metric.contract-v2.evidence-readiness"
METRIC_EVIDENCE_READINESS_V2_VERSION = 1
#: Catalog identity 1 named one requirement per metric and had no way to say
#: that a *sealed row* was produced under a superseded projection identity.
#: Identity 2 is additive: the projection shape, the enum members, and every
#: identity-1 reason keep their meaning, and the catalog gains a per-projection
#: requirement overlay plus the reasons r3 needs.
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_1 = "metric-evidence-readiness-v2-1"
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_2 = "metric-evidence-readiness-v2-2"
#: Identity 3 adds the explicit, user-confirmed lifecycle receipt vocabulary
#: used by projection r4.  Identities 1 and 2 remain readable and unchanged.
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_3 = "metric-evidence-readiness-v2-3"
#: Identity 4 teaches the readiness reader about append-only metric projection
#: r5.  R5 inherits the r4 confirmed-lifecycle contract and the r3 open-loop
#: contract.  Its reviewed task-profile rows also stop claiming a declared
#: profile contributor when the sealed denominator contains no profile slots.
#: Earlier projection identities retain their exact requirement routing.
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_4 = "metric-evidence-readiness-v2-4"
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_5 = "metric-evidence-readiness-v2-5"
#: Identity 6 adds r7's separately reviewed requirement/action links and exact
#: safe-action candidate enumeration. The four r7 UNKNOWN causes are a closed,
#: projection-gated vocabulary because awaiting an exact empty denominator and
#: bounded overflow are otherwise structurally indistinguishable.
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_6 = "metric-evidence-readiness-v2-6"
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7 = "metric-evidence-readiness-v2-7"
METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION = (
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7
)
SUPPORTED_METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSIONS = (
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_1,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_2,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_3,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_4,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_5,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_6,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7,
)


class MetricEvidenceContributor(StrEnum):
    """Evidence families one metric contract depends on, as a closed set.

    A contributor is a *kind of proof*, never a provider, a model, or a person.
    """

    FOCUS_OWNED_REQUEST_REVISION = "focus_owned_request_revision"
    CANONICAL_REQUEST_TEXT = "canonical_request_text"
    DECLARED_TASK_PROFILE = "declared_task_profile"
    RUBRIC_FACTOR_CALCULATOR = "rubric_factor_calculator"
    SEMANTIC_UNIT_HEADS = "semantic_unit_heads"
    AGENT_RESPONSE_TEXT = "agent_response_text"
    FEEDBACK_CLASSIFICATION = "feedback_classification"
    DECLARED_OBJECTIVE_OPPORTUNITY_SET = "declared_objective_opportunity_set"
    #: A documented ``AGENT`` ``PLAN`` message: the r3 open-loop denominator.
    DOCUMENTED_PLAN_MESSAGE = "documented_plan_message"
    #: A later message naming that exact plan in ``supersedes_message_ids``.
    EXPLICIT_PLAN_SUPERSESSION_LINK = "explicit_plan_supersession_link"
    #: An authenticated user confirmed the exact family opportunity set.
    CONFIRMED_LIFECYCLE_ENUMERATION = "confirmed_lifecycle_enumeration"
    #: An authenticated user confirmed one typed, content-free opportunity.
    CONFIRMED_LIFECYCLE_OPPORTUNITY = "confirmed_lifecycle_opportunity"
    #: An authenticated user confirmed a typed terminal outcome link.
    CONFIRMED_LIFECYCLE_OUTCOME_LINK = "confirmed_lifecycle_outcome_link"
    REVIEWED_REQUIREMENT_ENUMERATION = "reviewed_requirement_enumeration"
    REVIEWED_REQUIREMENT_PLAN_DISPOSITION = (
        "reviewed_requirement_plan_disposition"
    )
    REVIEWED_REQUIREMENT_ACTION_LINK = "reviewed_requirement_action_link"
    SAFE_ACTION_CANDIDATE_ENUMERATION = "safe_action_candidate_enumeration"
    TYPED_ACTION_EVIDENCE = "typed_action_evidence"
    TYPED_DECISION_EVIDENCE = "typed_decision_evidence"
    TYPED_VERIFICATION_RECEIPT = "typed_verification_receipt"


class MetricEvidenceAvailabilityState(StrEnum):
    """Why this metric does or does not carry a number, as a closed set."""

    MEASURED = "measured"
    PENDING_RIGHT_CENSORED = "pending_right_censored"
    NO_OPPORTUNITY = "no_opportunity"
    CAPABILITY_MISSING = "capability_missing"
    SOURCE_INCOMPLETE = "source_incomplete"
    EVIDENCE_UNRESOLVED = "evidence_unresolved"
    ABSTAINED = "abstained"
    EXECUTION_ERROR = "execution_error"


class MetricEvidenceReadinessReason(StrEnum):
    """Exact reason code.  Capability-missing reasons are metric-specific.

    A generic "this family is unobservable" tells a reader nothing actionable,
    so every metric that can report a missing capability names the concrete
    evidence contract that would have to exist first.
    """

    MEASURED_FROM_OWNED_OPPORTUNITIES = "measured_from_owned_opportunities"
    OPPORTUNITY_RIGHT_CENSORED = "opportunity_right_censored"
    NO_ELIGIBLE_OPPORTUNITY_OBSERVED = "no_eligible_opportunity_observed"
    OPPORTUNITY_SET_UNDETERMINED = "opportunity_set_undetermined"
    OPPORTUNITY_SET_EXCEEDS_RECEIPT_BOUND = (
        "opportunity_set_exceeds_receipt_bound"
    )
    DECLARED_PROFILE_SLOTS_ABSENT = "declared_profile_slots_absent"
    OPPORTUNITY_CLASSIFICATION_UNRESOLVED = "opportunity_classification_unresolved"
    SOURCE_RECONCILIATION_INCOMPLETE = "source_reconciliation_incomplete"
    CALCULATOR_ABSTAINED = "calculator_abstained"
    EXECUTION_ERROR_REPORTED = "execution_error_reported"
    #: The row carries a number, but the producer that computed it is no longer
    #: the one current code runs.  The value stays measured and readable; what
    #: it may *not* do is claim the corrected producer's evidence.
    MEASURED_UNDER_SUPERSEDED_PROJECTION_IDENTITY = (
        "measured_under_superseded_projection_identity"
    )
    # Metric-specific readiness requirements.
    FOCUS_OWNED_REQUEST_REVISION_REQUIRED = "focus_owned_request_revision_required"
    OWNED_CANONICAL_REQUEST_TEXT_REQUIRED = "owned_canonical_request_text_required"
    REQUEST_REVISION_UNIT_EXTRACTION_REQUIRED = (
        "request_revision_unit_extraction_required"
    )
    FEEDBACK_UNIT_EXTRACTION_REQUIRED = "feedback_unit_extraction_required"
    DECISION_UNIT_EXTRACTION_REQUIRED = "decision_unit_extraction_required"
    AMBIGUITY_EPISODE_EXTRACTION_REQUIRED = "ambiguity_episode_extraction_required"
    CLARIFICATION_EPISODE_EXTRACTION_REQUIRED = (
        "clarification_episode_extraction_required"
    )
    HYPOTHESIS_EPISODE_EXTRACTION_REQUIRED = "hypothesis_episode_extraction_required"
    SCOPE_CHANGE_EPISODE_EXTRACTION_REQUIRED = (
        "scope_change_episode_extraction_required"
    )
    REQUIREMENT_UNIT_EXTRACTION_REQUIRED = "requirement_unit_extraction_required"
    OPEN_LOOP_EPISODE_EXTRACTION_REQUIRED = "open_loop_episode_extraction_required"
    #: r3 open-loop: an explicit plan episode, or an explicit link to close it.
    EXPLICIT_PLAN_EPISODE_REQUIRED = "explicit_plan_episode_required"
    CONFIRMED_LIFECYCLE_SERVICE_REQUIRED = (
        "confirmed_lifecycle_service_required"
    )
    CONFIRMED_LIFECYCLE_ENUMERATION_REQUIRED = (
        "confirmed_lifecycle_enumeration_required"
    )
    REVIEWED_REQUIREMENT_PLAN_SERVICE_REQUIRED = (
        "reviewed_requirement_plan_service_required"
    )
    REVIEWED_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED = (
        "reviewed_requirement_plan_confirmation_required"
    )
    REVIEWED_REQUIREMENT_PLAN_BINDING_INVALID = (
        "reviewed_requirement_plan_binding_invalid"
    )
    REVIEWED_REQUIREMENT_ACTION_SERVICE_REQUIRED = (
        "reviewed_requirement_action_service_required"
    )
    REVIEWED_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED = (
        "reviewed_requirement_action_confirmation_required"
    )
    REVIEWED_REQUIREMENT_ACTION_BINDING_INVALID = (
        "reviewed_requirement_action_binding_invalid"
    )
    HYPOTHESIS_CHAIN_ADAPTER_CAPABILITIES_REQUIRED = (
        "hypothesis_chain_adapter_capabilities_required"
    )
    REQUIREMENT_ACTION_ADAPTER_CAPABILITIES_REQUIRED = (
        "requirement_action_adapter_capabilities_required"
    )
    MATERIAL_CLAIM_VERIFICATION_ADAPTER_CAPABILITIES_REQUIRED = (
        "material_claim_verification_adapter_capabilities_required"
    )
    VERIFICATION_TASK_OUTCOME_ADAPTER_CAPABILITIES_REQUIRED = (
        "verification_task_outcome_adapter_capabilities_required"
    )
    REQUIREMENT_VERIFICATION_ADAPTER_CAPABILITIES_REQUIRED = (
        "requirement_verification_adapter_capabilities_required"
    )


_R7_REQUIREMENT_ACTION_UNKNOWN_REASONS = MappingProxyType(
    {
        REASON_REQUIREMENT_ACTION_UNAVAILABLE: (
            MetricEvidenceAvailabilityState.CAPABILITY_MISSING,
            MetricEvidenceReadinessReason
            .REVIEWED_REQUIREMENT_ACTION_SERVICE_REQUIRED,
        ),
        REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED: (
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED,
            MetricEvidenceReadinessReason
            .REVIEWED_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
        ),
        REASON_REQUIREMENT_ACTION_INVALID: (
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE,
            MetricEvidenceReadinessReason.REVIEWED_REQUIREMENT_ACTION_BINDING_INVALID,
        ),
        REASON_REQUIREMENT_ACTION_OVERFLOW: (
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED,
            MetricEvidenceReadinessReason.OPPORTUNITY_SET_EXCEEDS_RECEIPT_BOUND,
        ),
        REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE: (
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE,
            MetricEvidenceReadinessReason
            .REQUIREMENT_ACTION_ADAPTER_CAPABILITIES_REQUIRED,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class _EvidenceRequirement:
    """What one metric needs, split by the role each contributor plays.

    ``denominator_contributor`` is what enumerates the opportunity set;
    ``outcome_contributors`` are what classify each enumerated opportunity.
    The split is what makes ``observed_contributors`` derivable from the sealed
    statistics instead of guessed.
    """

    denominator_contributor: MetricEvidenceContributor
    outcome_contributors: tuple[MetricEvidenceContributor, ...]
    capability_missing_reason: MetricEvidenceReadinessReason
    required_adapter_capabilities: tuple[CapabilityKey, ...] = ()

    @property
    def required_contributors(self) -> tuple[MetricEvidenceContributor, ...]:
        return (self.denominator_contributor, *self.outcome_contributors)


def _rubric() -> _EvidenceRequirement:
    return _EvidenceRequirement(
        denominator_contributor=(
            MetricEvidenceContributor.FOCUS_OWNED_REQUEST_REVISION
        ),
        outcome_contributors=(MetricEvidenceContributor.RUBRIC_FACTOR_CALCULATOR,),
        capability_missing_reason=(
            MetricEvidenceReadinessReason.FOCUS_OWNED_REQUEST_REVISION_REQUIRED
        ),
    )


def _profile_slots() -> _EvidenceRequirement:
    return _EvidenceRequirement(
        denominator_contributor=MetricEvidenceContributor.DECLARED_TASK_PROFILE,
        outcome_contributors=(MetricEvidenceContributor.CANONICAL_REQUEST_TEXT,),
        capability_missing_reason=(
            MetricEvidenceReadinessReason.OWNED_CANONICAL_REQUEST_TEXT_REQUIRED
        ),
    )


def _episode(
    reason: MetricEvidenceReadinessReason,
    *outcome_contributors: MetricEvidenceContributor,
) -> _EvidenceRequirement:
    return _EvidenceRequirement(
        denominator_contributor=MetricEvidenceContributor.SEMANTIC_UNIT_HEADS,
        outcome_contributors=outcome_contributors,
        capability_missing_reason=reason,
    )


def _objective(
    reason: MetricEvidenceReadinessReason,
    required_adapter_capabilities: tuple[CapabilityKey, ...],
    *outcome_contributors: MetricEvidenceContributor,
) -> _EvidenceRequirement:
    return _EvidenceRequirement(
        denominator_contributor=(
            MetricEvidenceContributor.DECLARED_OBJECTIVE_OPPORTUNITY_SET
        ),
        outcome_contributors=outcome_contributors,
        capability_missing_reason=reason,
        required_adapter_capabilities=required_adapter_capabilities,
    )


_REQUIREMENTS: dict[str, _EvidenceRequirement] = {
    "prompt.task_definition_coverage": _rubric(),
    "prompt.problem_evidence_quality": _rubric(),
    "prompt.context_sufficiency": _rubric(),
    "prompt.constraint_precision": _profile_slots(),
    "prompt.acceptance_testability": _profile_slots(),
    "prompt.deliverable_contract": _profile_slots(),
    "collaboration.ambiguity_resolution": _episode(
        MetricEvidenceReadinessReason.AMBIGUITY_EPISODE_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "collaboration.clarification_yield": _episode(
        MetricEvidenceReadinessReason.CLARIFICATION_EPISODE_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "collaboration.exploration_conversion": _episode(
        MetricEvidenceReadinessReason.HYPOTHESIS_EPISODE_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.TYPED_ACTION_EVIDENCE,
    ),
    "collaboration.scope_change_discipline": _episode(
        MetricEvidenceReadinessReason.SCOPE_CHANGE_EPISODE_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "collaboration.rework_candidate_rate": _episode(
        MetricEvidenceReadinessReason.FEEDBACK_UNIT_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.FEEDBACK_CLASSIFICATION,
    ),
    "logic.decomposition_coverage": _episode(
        MetricEvidenceReadinessReason.REQUIREMENT_UNIT_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "logic.hypothesis_test_linkage": _objective(
        MetricEvidenceReadinessReason
        .HYPOTHESIS_CHAIN_ADAPTER_CAPABILITIES_REQUIRED,
        (
            CapabilityKey.HYPOTHESIS_OPPORTUNITIES,
            CapabilityKey.HYPOTHESIS_EVIDENCE_LINKS,
            CapabilityKey.TOOL_EVENTS,
            CapabilityKey.DECISION_EVENTS,
            CapabilityKey.VERIFICATION_EVENTS,
        ),
        MetricEvidenceContributor.TYPED_ACTION_EVIDENCE,
        MetricEvidenceContributor.TYPED_DECISION_EVIDENCE,
        MetricEvidenceContributor.TYPED_VERIFICATION_RECEIPT,
    ),
    "logic.decision_rationale_coverage": _episode(
        MetricEvidenceReadinessReason.DECISION_UNIT_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "logic.requirement_action_traceability": _objective(
        MetricEvidenceReadinessReason
        .REQUIREMENT_ACTION_ADAPTER_CAPABILITIES_REQUIRED,
        (
            CapabilityKey.REQUIREMENT_OPPORTUNITIES,
            CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
            CapabilityKey.TOOL_EVENTS,
        ),
        MetricEvidenceContributor.TYPED_ACTION_EVIDENCE,
    ),
    "logic.open_loop_closure": _episode(
        MetricEvidenceReadinessReason.OPEN_LOOP_EPISODE_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "outcome.agent_claim_grounding": _objective(
        MetricEvidenceReadinessReason
        .MATERIAL_CLAIM_VERIFICATION_ADAPTER_CAPABILITIES_REQUIRED,
        (
            CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
            CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
            CapabilityKey.VERIFICATION_EVENTS,
        ),
        MetricEvidenceContributor.TYPED_VERIFICATION_RECEIPT,
    ),
    "outcome.verification_strategy_adequacy": _episode(
        MetricEvidenceReadinessReason.REQUEST_REVISION_UNIT_EXTRACTION_REQUIRED,
        MetricEvidenceContributor.AGENT_RESPONSE_TEXT,
    ),
    "outcome.first_pass_verification": _objective(
        MetricEvidenceReadinessReason
        .VERIFICATION_TASK_OUTCOME_ADAPTER_CAPABILITIES_REQUIRED,
        (
            CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
            CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
            CapabilityKey.VERIFICATION_EVENTS,
        ),
        MetricEvidenceContributor.TYPED_VERIFICATION_RECEIPT,
    ),
    "outcome.verified_requirement_coverage": _objective(
        MetricEvidenceReadinessReason
        .REQUIREMENT_VERIFICATION_ADAPTER_CAPABILITIES_REQUIRED,
        (
            CapabilityKey.REQUIREMENT_OPPORTUNITIES,
            CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
            CapabilityKey.VERIFICATION_EVENTS,
        ),
        MetricEvidenceContributor.TYPED_VERIFICATION_RECEIPT,
    ),
}

METRIC_EVIDENCE_REQUIREMENTS_V2 = MappingProxyType(_REQUIREMENTS)

#: r3 moved one metric onto different evidence.  ``logic.open_loop_closure`` no
#: longer waits for an ``open_loop`` semantic-unit extractor that does not
#: exist: its denominator is the documented plan message and its outcome is the
#: explicit supersession link that closes it.  The overlay is keyed by
#: projection identity so a sealed r1/r2 row keeps being described by the
#: evidence its own producer actually used.
_REQUIREMENTS_V3: dict[str, _EvidenceRequirement] = {
    "logic.open_loop_closure": _EvidenceRequirement(
        denominator_contributor=MetricEvidenceContributor.DOCUMENTED_PLAN_MESSAGE,
        outcome_contributors=(
            MetricEvidenceContributor.EXPLICIT_PLAN_SUPERSESSION_LINK,
        ),
        capability_missing_reason=(
            MetricEvidenceReadinessReason.EXPLICIT_PLAN_EPISODE_REQUIRED
        ),
    ),
}
METRIC_EVIDENCE_REQUIREMENTS_V2_R3 = MappingProxyType(_REQUIREMENTS_V3)

#: R4 changes exactly five collaboration rows.  Their denominator is not
#: extracted prose: it is a confirmed exact enumeration, and each classified
#: member is backed by a confirmed typed outcome link.
_REQUIREMENTS_V4: dict[str, _EvidenceRequirement] = {
    metric_key: _EvidenceRequirement(
        denominator_contributor=(
            MetricEvidenceContributor.CONFIRMED_LIFECYCLE_ENUMERATION
        ),
        outcome_contributors=(
            MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OPPORTUNITY,
            MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OUTCOME_LINK,
        ),
        capability_missing_reason=(
            MetricEvidenceReadinessReason.CONFIRMED_LIFECYCLE_SERVICE_REQUIRED
        ),
    )
    for metric_key in (
        "collaboration.ambiguity_resolution",
        "collaboration.clarification_yield",
        "collaboration.exploration_conversion",
        "collaboration.scope_change_discipline",
        "collaboration.rework_candidate_rate",
    )
}
METRIC_EVIDENCE_REQUIREMENTS_V2_R4 = MappingProxyType(_REQUIREMENTS_V4)

_REQUIREMENTS_V6: dict[str, _EvidenceRequirement] = {
    "logic.decomposition_coverage": _EvidenceRequirement(
        denominator_contributor=(
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION
        ),
        outcome_contributors=(
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_PLAN_DISPOSITION,
        ),
        capability_missing_reason=(
            MetricEvidenceReadinessReason
            .REVIEWED_REQUIREMENT_PLAN_SERVICE_REQUIRED
        ),
    ),
}
METRIC_EVIDENCE_REQUIREMENTS_V2_R6 = MappingProxyType(_REQUIREMENTS_V6)

_REQUIREMENTS_V7: dict[str, _EvidenceRequirement] = {
    "logic.requirement_action_traceability": _EvidenceRequirement(
        denominator_contributor=(
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION
        ),
        outcome_contributors=(
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_ACTION_LINK,
            MetricEvidenceContributor.SAFE_ACTION_CANDIDATE_ENUMERATION,
        ),
        capability_missing_reason=(
            MetricEvidenceReadinessReason
            .REVIEWED_REQUIREMENT_ACTION_SERVICE_REQUIRED
        ),
        required_adapter_capabilities=(
            CapabilityKey.REQUIREMENT_OPPORTUNITIES,
            CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
            CapabilityKey.TOOL_EVENTS,
        ),
    ),
}
METRIC_EVIDENCE_REQUIREMENTS_V2_R7 = MappingProxyType(_REQUIREMENTS_V7)

_R3_REQUIREMENT_PROJECTIONS = frozenset(
    {
        METRIC_PROJECTION_V2_VERSION_3,
        METRIC_PROJECTION_V2_VERSION_4,
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }
)
_R4_LIFECYCLE_PROJECTIONS = frozenset(
    {
        METRIC_PROJECTION_V2_VERSION_4,
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }
)

if set(METRIC_EVIDENCE_REQUIREMENTS_V2) != {
    contract.metric_key for contract in METRIC_CONTRACTS_V2
}:
    raise RuntimeError("metric evidence readiness catalog is incomplete")
if not set(METRIC_EVIDENCE_REQUIREMENTS_V2_R3) <= set(METRIC_EVIDENCE_REQUIREMENTS_V2):
    raise RuntimeError("the r3 readiness overlay must refine known metrics only")
if not set(METRIC_EVIDENCE_REQUIREMENTS_V2_R4) <= set(METRIC_EVIDENCE_REQUIREMENTS_V2):
    raise RuntimeError("the r4 readiness overlay must refine known metrics only")
if not set(METRIC_EVIDENCE_REQUIREMENTS_V2_R6) <= set(METRIC_EVIDENCE_REQUIREMENTS_V2):
    raise RuntimeError("the r6 readiness overlay must refine known metrics only")
if not set(METRIC_EVIDENCE_REQUIREMENTS_V2_R7) <= set(METRIC_EVIDENCE_REQUIREMENTS_V2):
    raise RuntimeError("the r7 readiness overlay must refine known metrics only")


def metric_evidence_requirement(
    metric_key: str,
    projection_version: str,
) -> _EvidenceRequirement:
    """The evidence one metric needed *under the identity that produced it*."""

    if projection_version in {
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }:
        overlay = METRIC_EVIDENCE_REQUIREMENTS_V2_R7.get(metric_key)
        if overlay is not None:
            return overlay

    if projection_version in {
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }:
        overlay = METRIC_EVIDENCE_REQUIREMENTS_V2_R6.get(metric_key)
        if overlay is not None:
            return overlay

    if projection_version in _R4_LIFECYCLE_PROJECTIONS:
        overlay = METRIC_EVIDENCE_REQUIREMENTS_V2_R4.get(metric_key)
        if overlay is not None:
            return overlay
    if projection_version in _R3_REQUIREMENT_PROJECTIONS:
        overlay = METRIC_EVIDENCE_REQUIREMENTS_V2_R3.get(metric_key)
        if overlay is not None:
            return overlay
    return METRIC_EVIDENCE_REQUIREMENTS_V2[metric_key]


def _availability(
    state: MetricStateV2,
    requirement: _EvidenceRequirement,
) -> tuple[MetricEvidenceAvailabilityState, MetricEvidenceReadinessReason]:
    """Derive the readiness verdict from the sealed row alone.

    The derivation is structural on purpose: it reads value state, capability,
    completeness, and the counts, never a producer-authored explanation string.
    A future projection identity therefore cannot silently change what a
    readiness reason means.
    """

    statistics = state.statistics
    if state.value_state is MetricValueStateV2.EXECUTION_ERROR:
        return (
            MetricEvidenceAvailabilityState.EXECUTION_ERROR,
            MetricEvidenceReadinessReason.EXECUTION_ERROR_REPORTED,
        )
    if state.value_state is MetricValueStateV2.ABSTAINED:
        return (
            MetricEvidenceAvailabilityState.ABSTAINED,
            MetricEvidenceReadinessReason.CALCULATOR_ABSTAINED,
        )
    if (
        state.projection_version
        in {METRIC_PROJECTION_V2_VERSION_7, METRIC_PROJECTION_V2_VERSION_8}
        and state.metric_key == "logic.requirement_action_traceability"
        and state.value_state is MetricValueStateV2.UNKNOWN
    ):
        refinement = _R7_REQUIREMENT_ACTION_UNKNOWN_REASONS.get(
            state.explanation_code
        )
        if refinement is None:
            raise ValueError(
                "r7/r8 requirement-action unknown has an unrecognized reason"
            )
        exact_shape = {
            REASON_REQUIREMENT_ACTION_UNAVAILABLE: (
                not statistics.capability_available
                and statistics.source_complete
                and statistics.unknown_count == statistics.eligible_count
            ),
            REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED: (
                statistics.capability_available
                and statistics.source_complete
                and statistics.unknown_count == statistics.eligible_count
            ),
            REASON_REQUIREMENT_ACTION_INVALID: (
                statistics.capability_available
                and not statistics.source_complete
                and statistics.unknown_count == statistics.eligible_count
            ),
            REASON_REQUIREMENT_ACTION_OVERFLOW: (
                statistics.capability_available
                and statistics.source_complete
                and statistics.unknown_count == statistics.eligible_count
            ),
            REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE: (
                statistics.capability_available
                and not statistics.source_complete
                and statistics.unknown_count == statistics.eligible_count
            ),
        }[state.explanation_code]
        if not exact_shape:
            raise ValueError(
                "r7/r8 requirement-action reason disagrees with its statistics"
            )
        return refinement
    if state.value_state is MetricValueStateV2.KNOWN:
        if _superseded_rubric_identity(state):
            # The number stays measured and readable: refusing to report a
            # stored value would be its own dishonesty.  What it may not do is
            # borrow the corrected producer's reason, because identity 1 could
            # anchor this fraction to a revision that did not own the scored
            # message.
            return (
                MetricEvidenceAvailabilityState.MEASURED,
                MetricEvidenceReadinessReason
                .MEASURED_UNDER_SUPERSEDED_PROJECTION_IDENTITY,
            )
        return (
            MetricEvidenceAvailabilityState.MEASURED,
            MetricEvidenceReadinessReason.MEASURED_FROM_OWNED_OPPORTUNITIES,
        )
    if state.value_state is MetricValueStateV2.PENDING:
        return (
            MetricEvidenceAvailabilityState.PENDING_RIGHT_CENSORED,
            MetricEvidenceReadinessReason.OPPORTUNITY_RIGHT_CENSORED,
        )
    if state.value_state is MetricValueStateV2.NOT_APPLICABLE:
        return (
            MetricEvidenceAvailabilityState.NO_OPPORTUNITY,
            MetricEvidenceReadinessReason.NO_ELIGIBLE_OPPORTUNITY_OBSERVED,
        )
    if (
        state.projection_version
        in _R3_REQUIREMENT_PROJECTIONS
        and statistics.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES
        and statistics.capability_available
        and statistics.source_complete
        and statistics.eligible_count == 0
    ):
        # Projection r3 is the first producer that preserves this cause, and
        # r4 inherits the objective-evidence contract unchanged.  The
        # family is observable and complete, but its authoritative set cannot
        # fit in the bounded receipt.  Calling that a missing adapter capability
        # or an empty set would point the reader at the wrong remediation.  R3
        # proves an authoritative empty set as NOT_APPLICABLE, so this UNKNOWN
        # structural combination uniquely represents the bounded overflow; no
        # producer-authored explanation string is parsed.
        return (
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED,
            MetricEvidenceReadinessReason.OPPORTUNITY_SET_EXCEEDS_RECEIPT_BOUND,
        )
    if not statistics.capability_available:
        return (
            MetricEvidenceAvailabilityState.CAPABILITY_MISSING,
            requirement.capability_missing_reason,
        )
    if (
        state.projection_version in {
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        and state.metric_key == "logic.decomposition_coverage"
        and statistics.capability_available
        and not statistics.source_complete
    ):
        return (
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE,
            MetricEvidenceReadinessReason.REVIEWED_REQUIREMENT_PLAN_BINDING_INVALID,
        )
    if (
        state.projection_version in {
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        and state.metric_key == "logic.decomposition_coverage"
        and statistics.capability_available
        and statistics.source_complete
        and statistics.eligible_count == 0
    ):
        return (
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED,
            MetricEvidenceReadinessReason
            .REVIEWED_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED,
        )
    if (
        state.projection_version in _R4_LIFECYCLE_PROJECTIONS
        and state.metric_key in METRIC_EVIDENCE_REQUIREMENTS_V2_R4
        and not statistics.source_complete
    ):
        return (
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE,
            MetricEvidenceReadinessReason
            .CONFIRMED_LIFECYCLE_ENUMERATION_REQUIRED,
        )
    if not statistics.source_complete:
        return (
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE,
            MetricEvidenceReadinessReason.SOURCE_RECONCILIATION_INCOMPLETE,
        )
    if statistics.eligible_count == 0:
        return (
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED,
            MetricEvidenceReadinessReason.DECLARED_PROFILE_SLOTS_ABSENT
            if statistics.denominator_basis
            is DenominatorBasis.DECLARED_PROFILE_SLOTS
            else MetricEvidenceReadinessReason.OPPORTUNITY_SET_UNDETERMINED,
        )
    return (
        MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED,
        MetricEvidenceReadinessReason.OPPORTUNITY_CLASSIFICATION_UNRESOLVED,
    )


def _superseded_rubric_identity(state: MetricStateV2) -> bool:
    """Whether this row is a rubric fraction from projection identity 1.

    Identity 1 scored the focus message against whichever request revision was
    latest, so its rubric rows never proved focus ownership.  Identity 2 fixed
    that and identity 3 inherits the fix, so only ``-1`` rubric rows carry the
    caveat.  Nothing else about the row changes.
    """

    return (
        state.projection_version == METRIC_PROJECTION_V2_VERSION_1
        and state.statistics.denominator_basis is DenominatorBasis.RUBRIC_FACTORS
    )


def _observed_contributors(
    state: MetricStateV2,
    requirement: _EvidenceRequirement,
) -> tuple[MetricEvidenceContributor, ...]:
    """Contributors the sealed row *proves* were available.

    Nothing here is inferred from the metric's value.  An unavailable family
    proves nothing at all; an available one proves the denominator contributor;
    and a resolved opportunity is the only proof that the outcome contributors
    were readable.

    One exception, and it only ever removes a claim: a rubric row sealed under
    projection identity 1 does not prove a focus-owned request revision, so
    that contributor is reported as still missing however many factors the row
    resolved.
    """

    statistics = state.statistics
    if not statistics.capability_available:
        return ()
    resolved = statistics.met_count + statistics.not_met_count
    if (
        state.projection_version
        in {METRIC_PROJECTION_V2_VERSION_7, METRIC_PROJECTION_V2_VERSION_8}
        and state.metric_key == "logic.requirement_action_traceability"
    ):
        if state.value_state not in {
            MetricValueStateV2.KNOWN,
            MetricValueStateV2.PENDING,
            MetricValueStateV2.NOT_APPLICABLE,
        } or not statistics.source_complete:
            return ()
        # A numeric, right-censored, or exact-empty r7/r8 row can only be issued
        # after all three authorities passed together.  This includes an empty
        # candidate set: completeness of the safe enumeration is the proof,
        # not the presence of at least one tool event.
        return (
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION,
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_ACTION_LINK,
            MetricEvidenceContributor.SAFE_ACTION_CANDIDATE_ENUMERATION,
        )
    if (
        state.projection_version == METRIC_PROJECTION_V2_VERSION_8
        and state.metric_key == "outcome.verified_requirement_coverage"
    ):
        # The sealed metric row cannot distinguish an app-issued objective
        # result from a separately owned native-acceptance authority. Preserve
        # only denominator provenance here; the run binding owns the exact
        # authority partition and readiness must not invent a verifier receipt.
        return (
            (requirement.denominator_contributor,)
            if statistics.source_complete
            and (
                statistics.eligible_count > 0
                or state.value_state is MetricValueStateV2.NOT_APPLICABLE
            )
            else ()
        )
    if (
        state.projection_version in {
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        and state.metric_key == "logic.decomposition_coverage"
    ):
        observed: list[MetricEvidenceContributor] = []
        if statistics.source_complete and (
            state.value_state is MetricValueStateV2.NOT_APPLICABLE
            or statistics.eligible_count > 0
        ):
            observed.append(
                MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION
            )
        if statistics.eligible_count:
            observed.append(
                MetricEvidenceContributor.REVIEWED_REQUIREMENT_PLAN_DISPOSITION
            )
        return tuple(observed)
    if (
        state.projection_version in _R4_LIFECYCLE_PROJECTIONS
        and state.metric_key in METRIC_EVIDENCE_REQUIREMENTS_V2_R4
    ):
        observed: list[MetricEvidenceContributor] = []
        if statistics.source_complete:
            observed.append(
                MetricEvidenceContributor.CONFIRMED_LIFECYCLE_ENUMERATION
            )
        if statistics.eligible_count:
            observed.append(
                MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OPPORTUNITY
            )
        if resolved:
            observed.append(
                MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OUTCOME_LINK
            )
        return tuple(observed)
    if (
        state.projection_version
        in {
            METRIC_PROJECTION_V2_VERSION_5,
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        and statistics.denominator_basis is DenominatorBasis.DECLARED_PROFILE_SLOTS
        and statistics.eligible_count == 0
    ):
        # R5 binds a reviewed task-profile revision (or the exact unconfigured
        # preset) to the source window.  A zero-slot sealed denominator does not
        # prove that this metric family was configured.  Keeping both
        # contributors missing is conservative: the row cannot distinguish an
        # unconfigured family from a configured family whose canonical request
        # was unavailable, and it must not invent either proof.
        return ()
    observed = (
        ()
        if resolved == 0 and not statistics.source_complete
        else (requirement.denominator_contributor,)
        if resolved == 0
        else requirement.required_contributors
    )
    if _superseded_rubric_identity(state):
        observed = tuple(
            item
            for item in observed
            if item is not MetricEvidenceContributor.FOCUS_OWNED_REQUEST_REVISION
        )
    return observed


class MetricEvidenceReadinessV2(StrictModel):
    """One metric's readiness, provenance, and sufficient statistics."""

    metric_key: str
    contract_version: str
    contract_fingerprint: str
    evidence_authority: EvidenceAuthority
    denominator_basis: DenominatorBasis
    opportunity_unit_kind: SemanticUnitKind | None = None
    value_state: MetricValueStateV2
    availability_state: MetricEvidenceAvailabilityState
    reason_code: MetricEvidenceReadinessReason
    required_contributors: tuple[MetricEvidenceContributor, ...] = Field(
        min_length=1, max_length=len(MetricEvidenceContributor)
    )
    observed_contributors: tuple[MetricEvidenceContributor, ...] = ()
    missing_contributors: tuple[MetricEvidenceContributor, ...] = ()
    #: Exact closed adapter authorities required by an objective metric.  The
    #: list is empty for conversational contracts; it states requirements, not
    #: a guessed per-run capability snapshot.
    required_adapter_capabilities: tuple[CapabilityKey, ...] = ()
    capability_available: bool
    source_complete: bool
    eligible_count: int = Field(ge=0, le=1_000_000)
    met_count: int = Field(ge=0, le=1_000_000)
    not_met_count: int = Field(ge=0, le=1_000_000)
    pending_count: int = Field(ge=0, le=1_000_000)
    unknown_count: int = Field(ge=0, le=1_000_000)
    resolved_count: int = Field(ge=0, le=1_000_000)
    censoring_lower_bound: float | None = Field(default=None, ge=0, le=1)
    censoring_upper_bound: float | None = Field(default=None, ge=0, le=1)
    calibration_state: Literal["not_assessed"] = "not_assessed"
    product_metric_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_readiness(self) -> MetricEvidenceReadinessV2:
        if SAFE_VERSION_PATTERN.fullmatch(self.metric_key) is None:
            raise ValueError("metric readiness keys must be content-free")
        if SAFE_VERSION_PATTERN.fullmatch(self.contract_version) is None:
            raise ValueError("metric readiness versions must be content-free")
        if len(self.contract_fingerprint) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.contract_fingerprint
        ):
            raise ValueError("contract fingerprint must be lowercase SHA-256")
        for values in (
            self.required_contributors,
            self.observed_contributors,
            self.missing_contributors,
            self.required_adapter_capabilities,
        ):
            if len(set(values)) != len(values):
                raise ValueError("evidence contributors cannot repeat")
        required = set(self.required_contributors)
        if not set(self.observed_contributors).issubset(required):
            raise ValueError("observed contributors must be required ones")
        if set(self.missing_contributors) != required - set(
            self.observed_contributors
        ):
            raise ValueError("missing contributors must complete the required set")
        if bool(self.required_adapter_capabilities) != (
            self.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
        ):
            raise ValueError(
                "only objective metrics carry adapter capability requirements"
            )
        if (
            self.met_count
            + self.not_met_count
            + self.pending_count
            + self.unknown_count
            != self.eligible_count
        ):
            raise ValueError("readiness counts must partition the eligible set")
        if self.resolved_count != self.met_count + self.not_met_count:
            raise ValueError("resolved opportunities are the classified ones")
        if not self.capability_available and self.eligible_count:
            r7_requirement_action_unavailable = (
                self.metric_key == "logic.requirement_action_traceability"
                and self.value_state is MetricValueStateV2.UNKNOWN
                and self.availability_state
                is MetricEvidenceAvailabilityState.CAPABILITY_MISSING
                and self.reason_code
                is MetricEvidenceReadinessReason
                .REVIEWED_REQUIREMENT_ACTION_SERVICE_REQUIRED
                and self.source_complete
                and self.unknown_count == self.eligible_count
                and self.met_count == 0
                and self.not_met_count == 0
                and self.pending_count == 0
                and self.resolved_count == 0
            )
            if not r7_requirement_action_unavailable:
                raise ValueError("an unavailable family cannot be eligible")
        if (self.censoring_lower_bound is None) != (
            self.censoring_upper_bound is None
        ):
            raise ValueError("censoring bounds are published as a pair")
        if (
            self.censoring_lower_bound is not None
            and self.censoring_upper_bound is not None
            and self.censoring_lower_bound > self.censoring_upper_bound
        ):
            raise ValueError("censoring bounds must be ordered")
        measured = (
            self.availability_state is MetricEvidenceAvailabilityState.MEASURED
        )
        if measured != (self.value_state is MetricValueStateV2.KNOWN):
            raise ValueError("only a known state may be reported as measured")
        return self


class MetricEvidenceReadinessProjectionV2(StrictModel):
    """The twenty readiness rows plus the identity they were derived from."""

    projection_key: Literal[METRIC_EVIDENCE_READINESS_V2_KEY] = (
        METRIC_EVIDENCE_READINESS_V2_KEY
    )
    projection_version: Literal[METRIC_EVIDENCE_READINESS_V2_VERSION] = (
        METRIC_EVIDENCE_READINESS_V2_VERSION
    )
    catalog_version: Literal[METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION] = (
        METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION
    )
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    #: Identity of the sealed publication this projection was derived from.
    publication_key: str
    publication_version: int = Field(ge=1)
    publication_source: MetricPublicationSource
    canonical_live_snapshot: bool
    compatibility_preview: bool
    contract_set_fingerprint: str
    #: The same commitment a persistence seal stores for this publication, so a
    #: reader can tie readiness back to the exact sealed bundle it describes.
    publication_fingerprint: str
    metric_projection_version: MetricProjectionV2Version
    #: Run provenance: which provider surface and adapter produced the window.
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    metrics: tuple[MetricEvidenceReadinessV2, ...] = Field(
        min_length=len(METRIC_CONTRACTS_V2), max_length=len(METRIC_CONTRACTS_V2)
    )
    measured_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    pending_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    no_opportunity_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    capability_missing_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    source_incomplete_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    evidence_unresolved_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    abstained_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    execution_error_count: int = Field(ge=0, le=len(METRIC_CONTRACTS_V2))
    objective_metric_count: Literal[5] = 5
    #: Objective contracts whose sealed state proves the adapter supplied the
    #: complete denominator/link/outcome authority set, whether the observed
    #: opportunity set was measured, pending, or authoritatively empty.
    objective_measurable_count: int = Field(ge=0, le=5)
    objective_measured_count: int = Field(ge=0, le=5)
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False
    calibration_state: Literal["not_assessed"] = "not_assessed"
    product_metric_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_projection(self) -> MetricEvidenceReadinessProjectionV2:
        expected = tuple(item.metric_key for item in METRIC_CONTRACTS_V2)
        if tuple(item.metric_key for item in self.metrics) != expected:
            raise ValueError("readiness must list every V2 metric in registry order")
        for fingerprint in (
            self.contract_set_fingerprint,
            self.publication_fingerprint,
        ):
            if len(fingerprint) != 64 or any(
                character not in "0123456789abcdef" for character in fingerprint
            ):
                raise ValueError("readiness fingerprints must be lowercase SHA-256")
        for value in (
            self.publication_key,
            self.provider_version,
            self.adapter_version,
            self.source_schema_version,
        ):
            if SAFE_VERSION_PATTERN.fullmatch(value) is None:
                raise ValueError("readiness provenance must be content-free")
        counts = {
            MetricEvidenceAvailabilityState.MEASURED: self.measured_count,
            MetricEvidenceAvailabilityState.PENDING_RIGHT_CENSORED: (
                self.pending_count
            ),
            MetricEvidenceAvailabilityState.NO_OPPORTUNITY: (
                self.no_opportunity_count
            ),
            MetricEvidenceAvailabilityState.CAPABILITY_MISSING: (
                self.capability_missing_count
            ),
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE: (
                self.source_incomplete_count
            ),
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED: (
                self.evidence_unresolved_count
            ),
            MetricEvidenceAvailabilityState.ABSTAINED: self.abstained_count,
            MetricEvidenceAvailabilityState.EXECUTION_ERROR: (
                self.execution_error_count
            ),
        }
        for availability, declared in counts.items():
            observed = sum(
                item.availability_state is availability for item in self.metrics
            )
            if observed != declared:
                raise ValueError("readiness availability counts are inconsistent")
        if sum(counts.values()) != len(METRIC_CONTRACTS_V2):
            raise ValueError("readiness states must partition the twenty metrics")
        if self.metric_projection_version not in {
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        } and any(
            not item.capability_available and item.eligible_count
            for item in self.metrics
        ):
            raise ValueError(
                "only r7/r8 requirement-action readiness preserves unavailable eligibility"
            )
        objective_rows = tuple(
            item
            for item in self.metrics
            if item.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
        )
        if len(objective_rows) != self.objective_metric_count:
            raise ValueError("readiness objective contract count is inconsistent")
        if sum(item.capability_available for item in objective_rows) != (
            self.objective_measurable_count
        ):
            raise ValueError("objective measurable count is inconsistent")
        if sum(
            item.availability_state is MetricEvidenceAvailabilityState.MEASURED
            for item in objective_rows
        ) != self.objective_measured_count:
            raise ValueError("objective measured count is inconsistent")
        if self.canonical_live_snapshot == self.compatibility_preview:
            raise ValueError("a publication is either canonical live or a preview")
        return self


def metric_evidence_readiness_row(
    state: MetricStateV2,
) -> MetricEvidenceReadinessV2:
    """Derive one readiness row from one sealed metric state."""

    requirement = metric_evidence_requirement(
        state.metric_key, state.projection_version
    )
    availability, reason = _availability(state, requirement)
    observed = _observed_contributors(state, requirement)
    required = requirement.required_contributors
    if (
        state.projection_version in {
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        and state.metric_key == "logic.decomposition_coverage"
        and state.value_state is MetricValueStateV2.NOT_APPLICABLE
    ):
        required = (
            MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION,
        )
    if (
        state.projection_version in _R4_LIFECYCLE_PROJECTIONS
        and state.metric_key in METRIC_EVIDENCE_REQUIREMENTS_V2_R4
        and state.value_state is MetricValueStateV2.NOT_APPLICABLE
    ):
        # An authoritative empty enumeration proves there are no episodes for
        # which opportunity or outcome receipts could exist.  Those
        # conditional contributors are not "missing" user work in this row.
        required = (
            MetricEvidenceContributor.CONFIRMED_LIFECYCLE_ENUMERATION,
        )
    statistics = state.statistics
    return MetricEvidenceReadinessV2(
        metric_key=state.metric_key,
        contract_version=state.contract_version,
        contract_fingerprint=state.contract_fingerprint,
        evidence_authority=state.evidence_authority,
        denominator_basis=statistics.denominator_basis,
        opportunity_unit_kind=statistics.opportunity_unit_kind,
        value_state=state.value_state,
        availability_state=availability,
        reason_code=reason,
        required_contributors=required,
        observed_contributors=observed,
        missing_contributors=tuple(
            item
            for item in required
            if item not in observed
        ),
        required_adapter_capabilities=requirement.required_adapter_capabilities,
        capability_available=statistics.capability_available,
        source_complete=statistics.source_complete,
        eligible_count=statistics.eligible_count,
        met_count=statistics.met_count,
        not_met_count=statistics.not_met_count,
        pending_count=statistics.pending_count,
        unknown_count=statistics.unknown_count,
        resolved_count=statistics.met_count + statistics.not_met_count,
        censoring_lower_bound=state.censoring_lower_bound,
        censoring_upper_bound=state.censoring_upper_bound,
    )


def project_metric_evidence_readiness_v2(
    publication: MetricPublicationV2,
    *,
    provider: Provider,
    provider_version: str,
    adapter_version: str,
    source_schema_version: str,
) -> MetricEvidenceReadinessProjectionV2:
    """Derive readiness for a whole sealed publication.

    ``publication`` must already be the sealed bundle; this function reads it
    and never recomputes a metric, so it cannot disagree with what was stored.
    """

    _validate_r7_requirement_action_denominator(
        projection_version=publication.projection_version,
        metrics=publication.metrics,
    )
    rows = tuple(
        metric_evidence_readiness_row(item.state) for item in publication.metrics
    )

    def _count(availability: MetricEvidenceAvailabilityState) -> int:
        return sum(item.availability_state is availability for item in rows)

    return MetricEvidenceReadinessProjectionV2(
        publication_key=publication.publication_key,
        publication_version=publication.publication_version,
        publication_source=publication.source,
        canonical_live_snapshot=publication.canonical_live_snapshot,
        compatibility_preview=publication.compatibility_preview,
        contract_set_fingerprint=publication.contract_set_fingerprint,
        publication_fingerprint=metric_publication_v2_fingerprint(publication),
        metric_projection_version=publication.projection_version,
        provider=provider,
        provider_version=provider_version,
        adapter_version=adapter_version,
        source_schema_version=source_schema_version,
        metrics=rows,
        measured_count=_count(MetricEvidenceAvailabilityState.MEASURED),
        pending_count=_count(
            MetricEvidenceAvailabilityState.PENDING_RIGHT_CENSORED
        ),
        no_opportunity_count=_count(
            MetricEvidenceAvailabilityState.NO_OPPORTUNITY
        ),
        capability_missing_count=_count(
            MetricEvidenceAvailabilityState.CAPABILITY_MISSING
        ),
        source_incomplete_count=_count(
            MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE
        ),
        evidence_unresolved_count=_count(
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
        ),
        abstained_count=_count(MetricEvidenceAvailabilityState.ABSTAINED),
        execution_error_count=_count(
            MetricEvidenceAvailabilityState.EXECUTION_ERROR
        ),
        objective_measurable_count=sum(
            row.capability_available
            for row in rows
            if row.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
        ),
        objective_measured_count=sum(
            row.availability_state is MetricEvidenceAvailabilityState.MEASURED
            for row in rows
            if row.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
        ),
    )


__all__ = [
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_1",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_2",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_3",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_4",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_5",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_6",
    "METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7",
    "METRIC_EVIDENCE_READINESS_V2_KEY",
    "METRIC_EVIDENCE_READINESS_V2_VERSION",
    "METRIC_EVIDENCE_REQUIREMENTS_V2",
    "METRIC_EVIDENCE_REQUIREMENTS_V2_R3",
    "METRIC_EVIDENCE_REQUIREMENTS_V2_R4",
    "METRIC_EVIDENCE_REQUIREMENTS_V2_R6",
    "METRIC_EVIDENCE_REQUIREMENTS_V2_R7",
    "SUPPORTED_METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSIONS",
    "metric_evidence_requirement",
    "MetricEvidenceAvailabilityState",
    "MetricEvidenceContributor",
    "MetricEvidenceReadinessProjectionV2",
    "MetricEvidenceReadinessReason",
    "MetricEvidenceReadinessV2",
    "metric_evidence_readiness_row",
    "project_metric_evidence_readiness_v2",
]
