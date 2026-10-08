"""Conservative measured projections from typed local evidence.

This module never inspects provider payloads and never infers a semantic link
that the adapter did not declare. It turns only descriptor-authorized,
content-free evidence relations into exact fractions for the measured layer.
Text models remain outside this authority boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ..providers import CapabilityKey, DecoderDescriptor
from .evidence_contracts import (
    ActionEvidence,
    ActionState,
    DecisionEvidence,
    DecisionState,
    ENUMERATION_CAPABILITY_FOR_OPPORTUNITY,
    EphemeralTypedEvidenceProjection,
    LINK_CAPABILITY_FOR_OPPORTUNITY,
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    VerificationEvidence,
    VerificationOutcome,
    validate_projection_descriptor,
)
from .text_contracts import MetricValueState

if TYPE_CHECKING:
    from .requirement_plan_evidence import RequirementPlanEvidenceSnapshot
    from .requirement_verification_evidence import (
        RequirementVerificationEvidenceSet,
        RequirementVerificationIdFactory,
    )


OBJECTIVE_EVIDENCE_METRIC_KEYS = (
    "logic.hypothesis_test_linkage",
    "logic.requirement_action_traceability",
    "outcome.agent_claim_grounding",
    "outcome.first_pass_verification",
    "outcome.verified_requirement_coverage",
)
# The current immutable typed-metric receipt still names these fields as
# message counts and bounds the observed side at 100. Larger authoritative
# opportunity sets must fail closed instead of overflowing or being truncated.
MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES = 100
OBJECTIVE_METRIC_PROJECTION_V4_VERSION = (
    "reviewed-requirement-verification-objective-projection-v1"
)


class ObjectiveWithholdingCause(StrEnum):
    """Closed reason one objective contract could not publish a value.

    The cause is deliberately separate from ``explanation_code``: the code
    names the exact evidence relation that was missing, while the cause names
    *which readiness dimension* that missing relation belongs to.  A downstream
    projector needs the second to tell "this adapter cannot see the family at
    all" from "the adapter can see it but the source window was not complete"
    from "the family is observable and complete, but its size overflows the
    receipt bound".  Collapsing all three into one unknown loses the only
    information a reader could act on.

    ``UNSPECIFIED`` exists because the frozen r2 producer predates the
    distinction and never declared one.  It is not a fourth cause; it means the
    producer did not state one, and an r3 consumer must not invent it.
    """

    UNSPECIFIED = "unspecified"
    NOT_WITHHELD = "not_withheld"
    #: No authorized adapter, or no declared enumeration/link/outcome authority.
    AUTHORITY_MISSING = "authority_missing"
    #: The family is declared, but the provider surface was not fully extracted.
    EXTRACTION_INCOMPLETE = "extraction_incomplete"
    #: The authoritative set is observable but larger than the receipt bound.
    OPPORTUNITY_BOUND_EXCEEDED = "opportunity_bound_exceeded"
    #: Individual opportunities exist but their evidence does not close them.
    EVIDENCE_UNRESOLVED = "evidence_unresolved"


@dataclass(frozen=True, slots=True)
class ObjectiveMetricOverride:
    """One exact, content-free replacement for a deterministic metric result."""

    value_state: MetricValueState
    explanation_code: str
    numerator: int | None = None
    denominator: int | None = None
    resolved_opportunity_count: int = 0
    eligible_opportunity_count: int = 0
    # Opportunities whose objective evidence already establishes the positive
    # outcome. Reporting it alongside the unresolved remainder lets a caller
    # bound a right-censored ratio instead of discarding the whole metric.
    met_opportunity_count: int = 0
    # Defaulted so the frozen r2 producer keeps producing exactly what it
    # produced before: it never declares a cause, and reading its overrides
    # must not look like it did.
    withholding_cause: ObjectiveWithholdingCause = (
        ObjectiveWithholdingCause.UNSPECIFIED
    )

    def __post_init__(self) -> None:
        known = self.value_state is MetricValueState.KNOWN
        if known != (self.numerator is not None and self.denominator is not None):
            raise ValueError("known objective metrics require an exact fraction")
        if known and (
            self.denominator is None
            or self.denominator < 1
            or self.numerator is None
            or not 0 <= self.numerator <= self.denominator
        ):
            raise ValueError("objective metric fraction is invalid")
        if not (
            0
            <= self.resolved_opportunity_count
            <= self.eligible_opportunity_count
        ):
            raise ValueError("objective opportunity coverage is invalid")
        if known and (
            self.denominator != self.eligible_opportunity_count
            or self.resolved_opportunity_count != self.eligible_opportunity_count
        ):
            raise ValueError("known objective metrics require complete opportunity coverage")
        if not 0 <= self.met_opportunity_count <= self.resolved_opportunity_count:
            raise ValueError("met objective opportunities exceed the resolved set")
        if known and self.met_opportunity_count != self.numerator:
            raise ValueError("known objective metrics must agree with their numerator")
        if (
            self.value_state is MetricValueState.NOT_APPLICABLE
            and self.eligible_opportunity_count != 0
        ):
            raise ValueError("not-applicable objective metrics require an empty set")
        withheld = self.value_state is MetricValueState.UNKNOWN
        if (
            withheld
            and self.withholding_cause is ObjectiveWithholdingCause.NOT_WITHHELD
        ):
            raise ValueError(
                "a withheld objective metric requires a withholding cause"
            )
        if not withheld and self.withholding_cause not in {
            ObjectiveWithholdingCause.UNSPECIFIED,
            ObjectiveWithholdingCause.NOT_WITHHELD,
        }:
            raise ValueError(
                "a published objective metric cannot declare a withholding cause"
            )


def _not_applicable(
    code: str,
    *,
    cause: ObjectiveWithholdingCause = ObjectiveWithholdingCause.UNSPECIFIED,
) -> ObjectiveMetricOverride:
    return ObjectiveMetricOverride(
        value_state=MetricValueState.NOT_APPLICABLE,
        explanation_code=code,
        withholding_cause=cause,
    )


def _unknown(
    code: str,
    *,
    resolved: int,
    eligible: int,
    met: int = 0,
    cause: ObjectiveWithholdingCause = ObjectiveWithholdingCause.UNSPECIFIED,
) -> ObjectiveMetricOverride:
    return ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code=code,
        resolved_opportunity_count=resolved,
        eligible_opportunity_count=eligible,
        met_opportunity_count=met,
        withholding_cause=cause,
    )


def _known(
    code: str,
    *,
    numerator: int,
    denominator: int,
    cause: ObjectiveWithholdingCause = ObjectiveWithholdingCause.UNSPECIFIED,
) -> ObjectiveMetricOverride:
    return ObjectiveMetricOverride(
        value_state=MetricValueState.KNOWN,
        explanation_code=code,
        numerator=numerator,
        denominator=denominator,
        resolved_opportunity_count=denominator,
        eligible_opportunity_count=denominator,
        met_opportunity_count=numerator,
        withholding_cause=cause,
    )


def _published_cause(
    unresolved_cause: ObjectiveWithholdingCause,
) -> ObjectiveWithholdingCause:
    """The cause a *published* value carries, derived from the caller identity.

    A producer that names a cause for its withheld values is an r3 producer, so
    its published values must positively declare that nothing was withheld.
    The frozen r2 producer names none and keeps stating none.
    """

    return (
        ObjectiveWithholdingCause.UNSPECIFIED
        if unresolved_cause is ObjectiveWithholdingCause.UNSPECIFIED
        else ObjectiveWithholdingCause.NOT_WITHHELD
    )


def _withheld_map(
    code: str,
    *,
    cause: ObjectiveWithholdingCause = ObjectiveWithholdingCause.UNSPECIFIED,
) -> dict[str, ObjectiveMetricOverride]:
    return {
        metric_key: _unknown(code, resolved=0, eligible=0, cause=cause)
        for metric_key in OBJECTIVE_EVIDENCE_METRIC_KEYS
    }


def _outcome_kinds_available(
    projection: EphemeralTypedEvidenceProjection,
    *required: TypedEvidenceKind,
) -> bool:
    """Whether the adapter declared every classifier input for a metric.

    Opportunity enumeration and link authority establish the denominator and
    relationship surface.  They do not establish that action, decision, or
    verification outcomes were observable.  Treating an undeclared outcome
    family as an empty one would manufacture a measured zero.
    """

    return set(required).issubset(projection.declared_kinds)


def _latest_verification_by_reference(
    records: tuple[VerificationEvidence, ...],
    reference_field: str,
) -> dict[str, VerificationEvidence]:
    latest: dict[str, VerificationEvidence] = {}
    for record in records:
        references = getattr(record, reference_field)
        for reference in references:
            previous = latest.get(reference)
            if previous is None or record.sequence > previous.sequence:
                latest[reference] = record
    return latest


def _receipt_bound_unknown(
    *,
    cause: ObjectiveWithholdingCause = ObjectiveWithholdingCause.UNSPECIFIED,
) -> ObjectiveMetricOverride:
    # Do not cap counts: that would fabricate both the denominator and coverage.
    return _unknown(
        "typed_objective_opportunity_count_exceeds_receipt_bound",
        resolved=0,
        eligible=0,
        cause=cause,
    )


def _hypothesis_chain_override(
    hypotheses: frozenset[str],
    actions: tuple[ActionEvidence, ...],
    decisions: tuple[DecisionEvidence, ...],
    verifications: tuple[VerificationEvidence, ...],
    *,
    unresolved_cause: ObjectiveWithholdingCause,
) -> ObjectiveMetricOverride:
    """Resolve hypothesis-action-verification-decision chains for one set."""

    linked = 0
    unresolved = 0
    for hypothesis_id in hypotheses:
        hypothesis_actions = tuple(
            item for item in actions if hypothesis_id in item.hypothesis_reference_ids
        )
        hypothesis_verifications = tuple(
            item
            for item in verifications
            if hypothesis_id in item.hypothesis_reference_ids
        )
        hypothesis_decisions = tuple(
            item
            for item in decisions
            if hypothesis_id in item.hypothesis_reference_ids
        )
        latest_verification = max(
            hypothesis_verifications,
            key=lambda item: item.sequence,
            default=None,
        )
        chain_found = latest_verification is not None and any(
            action.state is ActionState.COMPLETED
            and action.sequence < latest_verification.sequence < decision.sequence
            and latest_verification.outcome
            in {VerificationOutcome.PASSED, VerificationOutcome.FAILED}
            and decision.state
            in {DecisionState.ACCEPTED, DecisionState.SUPERSEDED}
            for action in hypothesis_actions
            for decision in hypothesis_decisions
        )
        if chain_found:
            linked += 1
        elif any(
            item.state in {ActionState.STARTED, ActionState.UNKNOWN}
            for item in hypothesis_actions
        ) or (
            latest_verification is not None
            and latest_verification.outcome
            in {VerificationOutcome.INCONCLUSIVE, VerificationOutcome.UNKNOWN}
        ) or any(
            item.state in {DecisionState.PROPOSED, DecisionState.UNKNOWN}
            for item in hypothesis_decisions
        ):
            unresolved += 1
    if unresolved:
        return _unknown(
            "typed_hypothesis_links_unresolved",
            resolved=len(hypotheses) - unresolved,
            eligible=len(hypotheses),
            met=linked,
            cause=unresolved_cause,
        )
    return _known(
        "typed_hypothesis_test_links",
        numerator=linked,
        denominator=len(hypotheses),
        cause=_published_cause(unresolved_cause),
    )


def _requirement_action_override(
    requirements: frozenset[str],
    actions: tuple[ActionEvidence, ...],
    *,
    unresolved_cause: ObjectiveWithholdingCause,
) -> ObjectiveMetricOverride:
    completed = frozenset(
        reference
        for record in actions
        if record.state is ActionState.COMPLETED
        for reference in record.requirement_reference_ids
    )
    unresolved_actions = frozenset(
        reference
        for record in actions
        if record.state in {ActionState.STARTED, ActionState.UNKNOWN}
        for reference in record.requirement_reference_ids
        if reference not in completed
    )
    if requirements & unresolved_actions:
        return _unknown(
            "typed_requirement_action_links_unresolved",
            resolved=len(requirements - unresolved_actions),
            eligible=len(requirements),
            met=len((requirements & completed) - unresolved_actions),
            cause=unresolved_cause,
        )
    return _known(
        "typed_requirement_action_links",
        numerator=len(requirements & completed),
        denominator=len(requirements),
        cause=_published_cause(unresolved_cause),
    )


def _requirement_verification_override(
    requirements: frozenset[str],
    verifications: tuple[VerificationEvidence, ...],
    *,
    unresolved_cause: ObjectiveWithholdingCause,
) -> ObjectiveMetricOverride:
    latest = _latest_verification_by_reference(
        verifications,
        "requirement_reference_ids",
    )
    passing = frozenset(
        reference
        for reference, record in latest.items()
        if record.outcome is VerificationOutcome.PASSED
    )
    unresolved_verifications = frozenset(
        reference
        for reference, record in latest.items()
        if record.outcome
        in {VerificationOutcome.INCONCLUSIVE, VerificationOutcome.UNKNOWN}
        if reference not in passing
    )
    if requirements & unresolved_verifications:
        return _unknown(
            "typed_requirement_verification_links_unresolved",
            resolved=len(requirements - unresolved_verifications),
            eligible=len(requirements),
            met=len((requirements & passing) - unresolved_verifications),
            cause=unresolved_cause,
        )
    return _known(
        "typed_requirement_verification_links",
        numerator=len(requirements & passing),
        denominator=len(requirements),
        cause=_published_cause(unresolved_cause),
    )


def _claim_grounding_override(
    claims: frozenset[str],
    verifications: tuple[VerificationEvidence, ...],
    *,
    unresolved_cause: ObjectiveWithholdingCause,
) -> ObjectiveMetricOverride:
    latest = _latest_verification_by_reference(verifications, "claim_reference_ids")
    grounded = 0
    unresolved = 0
    for claim_id in claims:
        evidence = latest.get(claim_id)
        if evidence is None or evidence.outcome is VerificationOutcome.FAILED:
            continue
        if evidence.outcome is VerificationOutcome.PASSED:
            grounded += 1
        elif evidence.outcome in {
            VerificationOutcome.INCONCLUSIVE,
            VerificationOutcome.UNKNOWN,
        }:
            unresolved += 1
    if unresolved:
        return _unknown(
            "typed_claim_grounding_unresolved",
            resolved=len(claims) - unresolved,
            eligible=len(claims),
            met=grounded,
            cause=unresolved_cause,
        )
    return _known(
        "typed_claim_grounding_links",
        numerator=grounded,
        denominator=len(claims),
        cause=_published_cause(unresolved_cause),
    )


def _first_pass_override(
    tasks: frozenset[str],
    verifications: tuple[VerificationEvidence, ...],
    *,
    unresolved_cause: ObjectiveWithholdingCause,
) -> ObjectiveMetricOverride:
    passed = 0
    resolved = 0
    for task_id in tasks:
        outcomes = tuple(
            sorted(
                (
                    item
                    for item in verifications
                    if task_id in item.verification_task_reference_ids
                    and item.outcome
                    in {VerificationOutcome.PASSED, VerificationOutcome.FAILED}
                ),
                key=lambda item: item.sequence,
            )
        )
        if not outcomes:
            continue
        resolved += 1
        if outcomes[0].outcome is VerificationOutcome.PASSED:
            passed += 1
    if resolved != len(tasks):
        return _unknown(
            "typed_first_verification_unresolved",
            resolved=resolved,
            eligible=len(tasks),
            met=passed,
            cause=unresolved_cause,
        )
    return _known(
        "typed_first_verification_outcomes",
        numerator=passed,
        denominator=len(tasks),
        cause=_published_cause(unresolved_cause),
    )


def _typed_records(
    projection: EphemeralTypedEvidenceProjection,
) -> tuple[
    tuple[ActionEvidence, ...],
    tuple[DecisionEvidence, ...],
    tuple[VerificationEvidence, ...],
]:
    return (
        tuple(
            record
            for record in projection.records
            if isinstance(record, ActionEvidence)
        ),
        tuple(
            record
            for record in projection.records
            if isinstance(record, DecisionEvidence)
        ),
        tuple(
            record
            for record in projection.records
            if isinstance(record, VerificationEvidence)
        ),
    )


def project_objective_metric_overrides(
    projection: EphemeralTypedEvidenceProjection | None,
    descriptor: DecoderDescriptor | None,
) -> dict[str, ObjectiveMetricOverride]:
    """Return only objective measurements justified by an authorized graph.

    Denominators come exclusively from explicitly declared opportunity sets.
    A linked action or receipt can therefore never erase eligible requirements
    that have no link. Missing or right-edge evidence remains unknown whenever
    the typed state does not mechanically close the opportunity.

    Frozen at projection identity r2.  It never declares a withholding cause
    and it decides an empty opportunity set before checking outcome authority.
    ``project_objective_metric_overrides_v3`` corrects both without changing a
    single value this producer would publish for the same input.
    """

    if projection is None or descriptor is None:
        return _withheld_map("typed_objective_authority_unavailable")
    validate_projection_descriptor(projection, descriptor)
    if not projection.provenance.extraction_complete:
        return _withheld_map("typed_objective_extraction_incomplete")

    actions, decisions, verifications = _typed_records(projection)
    declared = projection.declared_opportunity_kinds
    overrides = _withheld_map("typed_objective_opportunity_authority_missing")

    if TypedEvidenceOpportunityKind.HYPOTHESIS in declared:
        hypotheses = frozenset(projection.eligible_hypothesis_reference_ids)
        if not hypotheses:
            overrides["logic.hypothesis_test_linkage"] = _not_applicable(
                "typed_hypothesis_set_empty"
            )
        elif len(hypotheses) > MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES:
            overrides["logic.hypothesis_test_linkage"] = _receipt_bound_unknown()
        elif not _outcome_kinds_available(
            projection,
            TypedEvidenceKind.ACTION,
            TypedEvidenceKind.DECISION,
            TypedEvidenceKind.VERIFICATION,
        ):
            overrides["logic.hypothesis_test_linkage"] = _unknown(
                "typed_hypothesis_chain_capability_missing",
                resolved=0,
                eligible=0,
            )
        else:
            overrides["logic.hypothesis_test_linkage"] = _hypothesis_chain_override(
                hypotheses,
                actions,
                decisions,
                verifications,
                unresolved_cause=ObjectiveWithholdingCause.UNSPECIFIED,
            )

    if TypedEvidenceOpportunityKind.REQUIREMENT in declared:
        requirements = frozenset(projection.eligible_requirement_reference_ids)
        if not requirements:
            overrides["logic.requirement_action_traceability"] = _not_applicable(
                "typed_requirement_set_empty"
            )
            overrides["outcome.verified_requirement_coverage"] = _not_applicable(
                "typed_requirement_set_empty"
            )
        elif len(requirements) > MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES:
            overrides["logic.requirement_action_traceability"] = (
                _receipt_bound_unknown()
            )
            overrides["outcome.verified_requirement_coverage"] = (
                _receipt_bound_unknown()
            )
        else:
            if not _outcome_kinds_available(projection, TypedEvidenceKind.ACTION):
                overrides["logic.requirement_action_traceability"] = _unknown(
                    "typed_requirement_action_capability_missing",
                    resolved=0,
                    eligible=0,
                )
            else:
                overrides["logic.requirement_action_traceability"] = (
                    _requirement_action_override(
                        requirements,
                        actions,
                        unresolved_cause=ObjectiveWithholdingCause.UNSPECIFIED,
                    )
                )

            if not _outcome_kinds_available(
                projection, TypedEvidenceKind.VERIFICATION
            ):
                overrides["outcome.verified_requirement_coverage"] = _unknown(
                    "typed_requirement_verification_capability_missing",
                    resolved=0,
                    eligible=0,
                )
            else:
                overrides["outcome.verified_requirement_coverage"] = (
                    _requirement_verification_override(
                        requirements,
                        verifications,
                        unresolved_cause=ObjectiveWithholdingCause.UNSPECIFIED,
                    )
                )

    if TypedEvidenceOpportunityKind.MATERIAL_CLAIM in declared:
        claims = frozenset(projection.eligible_claim_reference_ids)
        if not claims:
            overrides["outcome.agent_claim_grounding"] = _not_applicable(
                "typed_claim_set_empty"
            )
        elif len(claims) > MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES:
            overrides["outcome.agent_claim_grounding"] = _receipt_bound_unknown()
        elif not _outcome_kinds_available(
            projection, TypedEvidenceKind.VERIFICATION
        ):
            overrides["outcome.agent_claim_grounding"] = _unknown(
                "typed_claim_verification_capability_missing",
                resolved=0,
                eligible=0,
            )
        else:
            overrides["outcome.agent_claim_grounding"] = _claim_grounding_override(
                claims,
                verifications,
                unresolved_cause=ObjectiveWithholdingCause.UNSPECIFIED,
            )

    if TypedEvidenceOpportunityKind.VERIFICATION_TASK in declared:
        tasks = frozenset(projection.eligible_verification_task_reference_ids)
        if not tasks:
            overrides["outcome.first_pass_verification"] = _not_applicable(
                "typed_verification_task_set_empty"
            )
        elif len(tasks) > MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES:
            overrides["outcome.first_pass_verification"] = _receipt_bound_unknown()
        elif not _outcome_kinds_available(
            projection, TypedEvidenceKind.VERIFICATION
        ):
            overrides["outcome.first_pass_verification"] = _unknown(
                "typed_verification_outcome_capability_missing",
                resolved=0,
                eligible=0,
            )
        else:
            overrides["outcome.first_pass_verification"] = _first_pass_override(
                tasks,
                verifications,
                unresolved_cause=ObjectiveWithholdingCause.UNSPECIFIED,
            )

    return overrides


#: What each objective contract needs before an *empty* eligible set may be
#: read as a proved "no opportunity" rather than as an unobservable family.
#: Enumeration and negative-link authority come from the descriptor; the outcome
#: kinds come from the decoder declared evidence kinds.  All three are required
#: together: an adapter that can list hypotheses but cannot observe verification
#: outcomes has not proved that zero hypotheses were tested.
_OBJECTIVE_FAMILY_REQUIREMENTS: tuple[
    tuple[str, TypedEvidenceOpportunityKind, tuple[TypedEvidenceKind, ...]], ...
] = (
    (
        "logic.hypothesis_test_linkage",
        TypedEvidenceOpportunityKind.HYPOTHESIS,
        (
            TypedEvidenceKind.ACTION,
            TypedEvidenceKind.DECISION,
            TypedEvidenceKind.VERIFICATION,
        ),
    ),
    (
        "logic.requirement_action_traceability",
        TypedEvidenceOpportunityKind.REQUIREMENT,
        (TypedEvidenceKind.ACTION,),
    ),
    (
        "outcome.verified_requirement_coverage",
        TypedEvidenceOpportunityKind.REQUIREMENT,
        (TypedEvidenceKind.VERIFICATION,),
    ),
    (
        "outcome.agent_claim_grounding",
        TypedEvidenceOpportunityKind.MATERIAL_CLAIM,
        (TypedEvidenceKind.VERIFICATION,),
    ),
    (
        "outcome.first_pass_verification",
        TypedEvidenceOpportunityKind.VERIFICATION_TASK,
        (TypedEvidenceKind.VERIFICATION,),
    ),
)
_OBJECTIVE_CAPABILITY_MISSING_CODE = {
    "logic.hypothesis_test_linkage": "typed_hypothesis_chain_capability_missing",
    "logic.requirement_action_traceability": (
        "typed_requirement_action_capability_missing"
    ),
    "outcome.verified_requirement_coverage": (
        "typed_requirement_verification_capability_missing"
    ),
    "outcome.agent_claim_grounding": "typed_claim_verification_capability_missing",
    "outcome.first_pass_verification": (
        "typed_verification_outcome_capability_missing"
    ),
}
_OBJECTIVE_EMPTY_SET_CODE = {
    "logic.hypothesis_test_linkage": "typed_hypothesis_set_empty",
    "logic.requirement_action_traceability": "typed_requirement_set_empty",
    "outcome.verified_requirement_coverage": "typed_requirement_set_empty",
    "outcome.agent_claim_grounding": "typed_claim_set_empty",
    "outcome.first_pass_verification": "typed_verification_task_set_empty",
}
if set(_OBJECTIVE_CAPABILITY_MISSING_CODE) != set(OBJECTIVE_EVIDENCE_METRIC_KEYS):
    raise RuntimeError("objective withholding codes must cover every objective metric")


def _family_measurable(
    projection: EphemeralTypedEvidenceProjection,
    descriptor: DecoderDescriptor,
    opportunity_kind: TypedEvidenceOpportunityKind,
    outcome_kinds: tuple[TypedEvidenceKind, ...],
) -> bool:
    """Whether every authority a *measurable* family needs was declared.

    ``validate_projection_descriptor`` already refuses a projection that
    declares an opportunity family without enumeration and link authority.
    Restating both here is deliberate: this predicate is what decides whether
    an empty set may become ``not_applicable``, and that decision must be
    readable on its own rather than inherited from a validator elsewhere.
    """

    if opportunity_kind not in projection.declared_opportunity_kinds:
        return False
    capabilities = frozenset(descriptor.capabilities)
    if ENUMERATION_CAPABILITY_FOR_OPPORTUNITY[opportunity_kind] not in capabilities:
        return False
    if LINK_CAPABILITY_FOR_OPPORTUNITY[opportunity_kind] not in capabilities:
        return False
    return _outcome_kinds_available(projection, *outcome_kinds)


def _eligible_references(
    projection: EphemeralTypedEvidenceProjection,
    opportunity_kind: TypedEvidenceOpportunityKind,
) -> frozenset[str]:
    if opportunity_kind is TypedEvidenceOpportunityKind.HYPOTHESIS:
        return frozenset(projection.eligible_hypothesis_reference_ids)
    if opportunity_kind is TypedEvidenceOpportunityKind.REQUIREMENT:
        return frozenset(projection.eligible_requirement_reference_ids)
    if opportunity_kind is TypedEvidenceOpportunityKind.MATERIAL_CLAIM:
        return frozenset(projection.eligible_claim_reference_ids)
    return frozenset(projection.eligible_verification_task_reference_ids)


def project_objective_metric_overrides_v3(
    projection: EphemeralTypedEvidenceProjection | None,
    descriptor: DecoderDescriptor | None,
) -> dict[str, ObjectiveMetricOverride]:
    """The r3 objective producer: same evidence rules, honest withholding.

    Two corrections over the frozen r2 producer, and nothing else:

    * every withheld contract declares *why* it was withheld, so a reader can
      tell a missing adapter authority from an incomplete source window from a
      family whose authoritative set overflows the receipt bound;
    * an empty eligible set becomes ``not_applicable`` only when the adapter
      declared enumeration authority, negative-link authority, *and* every
      outcome kind that contract classifier reads.  An adapter that can list a
      family but cannot observe its outcomes has proved nothing about an empty
      set, so the contract stays an actionable unknown instead.

    Every measured value this producer publishes is the value the r2 producer
    would have published from the same evidence.
    """

    if projection is None or descriptor is None:
        return _withheld_map(
            "typed_objective_authority_unavailable",
            cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        )
    validate_projection_descriptor(projection, descriptor)

    overrides: dict[str, ObjectiveMetricOverride] = {}
    measurable: dict[str, bool] = {}
    for metric_key, opportunity_kind, outcome_kinds in (
        _OBJECTIVE_FAMILY_REQUIREMENTS
    ):
        measurable[metric_key] = _family_measurable(
            projection, descriptor, opportunity_kind, outcome_kinds
        )
        if not measurable[metric_key]:
            overrides[metric_key] = _unknown(
                (
                    _OBJECTIVE_CAPABILITY_MISSING_CODE[metric_key]
                    if opportunity_kind in projection.declared_opportunity_kinds
                    else "typed_objective_opportunity_authority_missing"
                ),
                resolved=0,
                eligible=0,
                cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
            )

    if not projection.provenance.extraction_complete:
        # A declared family whose source window was not fully extracted is a
        # completeness problem, not a capability problem: the adapter can see
        # the family, so naming it "capability missing" would send a reader to
        # fix the wrong thing.
        for metric_key in OBJECTIVE_EVIDENCE_METRIC_KEYS:
            if measurable[metric_key]:
                overrides[metric_key] = _unknown(
                    "typed_objective_extraction_incomplete",
                    resolved=0,
                    eligible=0,
                    cause=ObjectiveWithholdingCause.EXTRACTION_INCOMPLETE,
                )
        return overrides

    actions, decisions, verifications = _typed_records(projection)
    for metric_key, opportunity_kind, _outcome_kinds in (
        _OBJECTIVE_FAMILY_REQUIREMENTS
    ):
        if not measurable[metric_key]:
            continue
        references = _eligible_references(projection, opportunity_kind)
        if not references:
            overrides[metric_key] = _not_applicable(
                _OBJECTIVE_EMPTY_SET_CODE[metric_key],
                cause=ObjectiveWithholdingCause.NOT_WITHHELD,
            )
            continue
        if len(references) > MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES:
            overrides[metric_key] = _receipt_bound_unknown(
                cause=ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED
            )
            continue
        unresolved_cause = ObjectiveWithholdingCause.EVIDENCE_UNRESOLVED
        if metric_key == "logic.hypothesis_test_linkage":
            overrides[metric_key] = _hypothesis_chain_override(
                references,
                actions,
                decisions,
                verifications,
                unresolved_cause=unresolved_cause,
            )
        elif metric_key == "logic.requirement_action_traceability":
            overrides[metric_key] = _requirement_action_override(
                references, actions, unresolved_cause=unresolved_cause
            )
        elif metric_key == "outcome.verified_requirement_coverage":
            overrides[metric_key] = _requirement_verification_override(
                references, verifications, unresolved_cause=unresolved_cause
            )
        elif metric_key == "outcome.agent_claim_grounding":
            overrides[metric_key] = _claim_grounding_override(
                references, verifications, unresolved_cause=unresolved_cause
            )
        else:
            overrides[metric_key] = _first_pass_override(
                references, verifications, unresolved_cause=unresolved_cause
            )
    return overrides


def project_verified_requirement_coverage(
    *,
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None,
    verification_evidence: RequirementVerificationEvidenceSet | None,
    identifiers: RequirementVerificationIdFactory,
) -> ObjectiveMetricOverride:
    """Resolve the verified-requirement metric from r6 plus app authority.

    The denominator is never re-enumerated from provider events.  A complete
    native-reviewed r6 snapshot owns it.  Objective verifier results and
    explicit native-user acceptance are separate keyed record types; neither
    an action completion nor any assistant/model statement is accepted here.
    """

    # Local imports keep the frozen r2/r3 module importable by
    # ``metric_projection_v2`` without introducing an r6 -> r2 cycle.
    from .requirement_action_evidence import requirement_plan_snapshot_fingerprint
    from .requirement_plan_evidence import RequirementPlanEvidenceSnapshot
    from .requirement_verification_evidence import (
        MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES,
        RequirementAcceptanceOutcome,
        RequirementVerificationOutcome,
        validate_requirement_verification_evidence_set,
    )

    if requirement_plan_evidence is None:
        return _unknown(
            "reviewed_requirement_authority_unavailable",
            resolved=0,
            eligible=0,
            cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        )
    try:
        reviewed = RequirementPlanEvidenceSnapshot.model_validate(
            requirement_plan_evidence.model_dump(mode="python")
        )
        if (
            not reviewed.complete_user_clause_classification
            or reviewed.confirmation_id is None
            or reviewed.proposal_id is None
            or reviewed.producer_receipt is None
        ):
            raise ValueError("reviewed requirement authority is incomplete")
        # Reuse the exact installation-keyed identity already frozen for r6.
        requirement_plan_snapshot_fingerprint(reviewed, identifiers)
    except (AttributeError, TypeError, ValueError):
        return _unknown(
            "reviewed_requirement_authority_invalid",
            resolved=0,
            eligible=0,
            cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        )

    eligible = len(reviewed.requirements)
    if eligible == 0:
        return _not_applicable(
            "reviewed_requirement_set_empty",
            cause=ObjectiveWithholdingCause.NOT_WITHHELD,
        )
    if eligible > MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES:
        return _receipt_bound_unknown(
            cause=ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED
        )
    if verification_evidence is None:
        return _unknown(
            "requirement_verification_evidence_unavailable",
            resolved=0,
            eligible=eligible,
            cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        )

    try:
        evidence = validate_requirement_verification_evidence_set(
            verification_evidence,
            reviewed,
            identifiers,
        )
    except (AttributeError, TypeError, ValueError):
        return _unknown(
            "requirement_verification_authority_invalid",
            resolved=0,
            eligible=eligible,
            cause=ObjectiveWithholdingCause.AUTHORITY_MISSING,
        )

    verification_by_opportunity = {
        item.opportunity_id: item for item in evidence.verification_results
    }
    acceptance_by_opportunity = {
        item.opportunity_id: item for item in evidence.acceptance_authorities
    }
    resolved = 0
    met = 0
    for opportunity in evidence.opportunities.opportunities:
        verification = verification_by_opportunity.get(opportunity.opportunity_id)
        acceptance = acceptance_by_opportunity.get(opportunity.opportunity_id)
        if verification is not None:
            if verification.outcome is RequirementVerificationOutcome.UNKNOWN:
                continue
            resolved += 1
            if verification.outcome is RequirementVerificationOutcome.PASSED:
                met += 1
            continue
        if acceptance is not None:
            if acceptance.outcome is RequirementAcceptanceOutcome.UNKNOWN:
                continue
            resolved += 1
            if acceptance.outcome is RequirementAcceptanceOutcome.ACCEPTED:
                met += 1

    if resolved != eligible:
        return _unknown(
            "app_issued_requirement_verification_pending",
            resolved=resolved,
            eligible=eligible,
            met=met,
            cause=ObjectiveWithholdingCause.EVIDENCE_UNRESOLVED,
        )
    return _known(
        "app_issued_verified_requirement_coverage",
        numerator=met,
        denominator=eligible,
        cause=ObjectiveWithholdingCause.NOT_WITHHELD,
    )


def project_objective_metric_overrides_v4(
    projection: EphemeralTypedEvidenceProjection | None,
    descriptor: DecoderDescriptor | None,
    *,
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None,
    requirement_verification_evidence: RequirementVerificationEvidenceSet | None,
    identifiers: RequirementVerificationIdFactory,
) -> dict[str, ObjectiveMetricOverride]:
    """Append-only objective integration using reviewed requirements for one key.

    V3 remains frozen.  V4 preserves its other four metric outputs and replaces
    only ``outcome.verified_requirement_coverage`` with the native-reviewed
    authority path.  This pure integration is not the live r8 issuer.
    """

    from .requirement_verification_evidence import VERIFIED_REQUIREMENT_METRIC_KEY

    overrides = project_objective_metric_overrides_v3(projection, descriptor)
    overrides[VERIFIED_REQUIREMENT_METRIC_KEY] = (
        project_verified_requirement_coverage(
            requirement_plan_evidence=requirement_plan_evidence,
            verification_evidence=requirement_verification_evidence,
            identifiers=identifiers,
        )
    )
    return overrides


__all__ = [
    "MAX_OBJECTIVE_RECEIPT_OPPORTUNITIES",
    "OBJECTIVE_METRIC_PROJECTION_V4_VERSION",
    "OBJECTIVE_EVIDENCE_METRIC_KEYS",
    "ObjectiveMetricOverride",
    "ObjectiveWithholdingCause",
    "project_objective_metric_overrides",
    "project_objective_metric_overrides_v3",
    "project_objective_metric_overrides_v4",
    "project_verified_requirement_coverage",
]
