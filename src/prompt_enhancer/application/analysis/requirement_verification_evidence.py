"""App-issued, content-free evidence for verified requirement coverage.

The reviewed requirement-plan snapshot is the only denominator authority.  This
module issues an exact opportunity set from that frozen r6 identity and binds
either objective verifier results or separately explicit native-user acceptance
receipts to individual opportunities.  It does not inspect transcript text,
provider payloads, assistant claims, or requirement-action completion state.

These are pure application contracts.  They are intentionally not persistence
records and do not make the live r7 publication or release operability claims.
"""

from __future__ import annotations

import hmac
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .requirement_action_evidence import requirement_plan_snapshot_fingerprint
from .requirement_plan_evidence import (
    MAX_REQUIREMENT_PLAN_UNITS,
    REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION,
    REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    RequirementCoordinate,
    RequirementPlanEvidenceSnapshot,
)


VERIFIED_REQUIREMENT_METRIC_KEY = "outcome.verified_requirement_coverage"
REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION = (
    "requirement-verification-evidence-v1"
)
REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION = (
    "app-issued-reviewed-requirement-verification-v1"
)
REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION = (
    "reviewed-r6-requirement-opportunity-issuer-v1"
)
REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION = (
    "local-objective-verification-result-issuer-v1"
)
REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION = (
    "native-explicit-requirement-acceptance-issuer-v1"
)
REQUIREMENT_VERIFICATION_PROJECTION_VERSION = (
    "reviewed-requirement-verification-objective-projection-v1"
)
MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES = 100
MAX_REQUIREMENT_VERIFICATION_RECEIPTS_PER_RESULT = 16
MAX_REQUIREMENT_VERIFICATION_OBSERVED_SEQUENCE = (2**63) - 1


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("requirement verification identifiers must be pseudonyms")
    return value


def _sorted_unique_pseudonyms(values: tuple[str, ...]) -> tuple[str, ...]:
    checked = tuple(_pseudonym(value) for value in values)
    if checked != tuple(sorted(set(checked))):
        raise ValueError("verification receipt identifiers must be unique and sorted")
    return checked


class RequirementVerificationIdFactory(Protocol):
    """Installation-local keyed identity boundary."""

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class RequirementVerificationMethod(StrEnum):
    """Objective methods an app verifier may attest.

    Human acceptance is deliberately absent.  It has a separate authority
    contract so it cannot be smuggled in as an objective test receipt.
    """

    TEST = "test"
    STATIC_CHECK = "static_check"
    BUILD = "build"
    ARTIFACT_INSPECTION = "artifact_inspection"
    OTHER_DOCUMENTED = "other_documented"


class RequirementVerificationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RequirementAcceptanceOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class RequirementVerificationAuthorityKind(StrEnum):
    APP_OBJECTIVE_VERIFIER = "app_objective_verifier"


class RequirementAcceptanceAuthorityKind(StrEnum):
    NATIVE_USER_ACCEPTANCE = "native_user_acceptance"


class AppIssuedRequirementVerificationOpportunity(StrictModel):
    opportunity_id: str
    requirement_index: int = Field(ge=0, lt=MAX_REQUIREMENT_PLAN_UNITS)
    requirement_id: str
    coordinate: RequirementCoordinate

    _ids = field_validator("opportunity_id", "requirement_id")(_pseudonym)


class AppIssuedRequirementVerificationOpportunitySet(StrictModel):
    """Exact app-issued copy of one native-reviewed r6 active set."""

    session_id: str
    source_window_fingerprint: str
    requirement_plan_confirmation_id: str
    requirement_plan_proposal_id: str
    requirement_plan_evidence_fingerprint: str
    requirement_plan_schema_version: Literal[
        REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION
    ] = REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION
    requirement_plan_policy_version: Literal[
        REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION
    ] = REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION
    requirement_plan_review_rubric_version: Literal[
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    ] = REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    issuer_version: Literal[
        REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION
    ] = REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION
    evidence_schema_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    evidence_policy_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    complete_active_requirement_enumeration: Literal[True] = True
    opportunities: tuple[AppIssuedRequirementVerificationOpportunity, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    opportunity_set_fingerprint: str
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "session_id",
        "source_window_fingerprint",
        "requirement_plan_confirmation_id",
        "requirement_plan_proposal_id",
        "requirement_plan_evidence_fingerprint",
        "opportunity_set_fingerprint",
    )(_pseudonym)

    @model_validator(mode="after")
    def exact_set_shape(self) -> "AppIssuedRequirementVerificationOpportunitySet":
        indexes = tuple(item.requirement_index for item in self.opportunities)
        requirement_ids = tuple(item.requirement_id for item in self.opportunities)
        opportunity_ids = tuple(item.opportunity_id for item in self.opportunities)
        if indexes != tuple(range(len(self.opportunities))):
            raise ValueError("verification opportunities must preserve r6 order")
        if requirement_ids != tuple(sorted(set(requirement_ids))):
            raise ValueError("verification requirements must be unique and sorted")
        if len(set(opportunity_ids)) != len(opportunity_ids):
            raise ValueError("verification opportunities must be unique")
        return self


class AppIssuedRequirementVerificationResult(StrictModel):
    """One typed objective verifier result for one issued opportunity."""

    result_id: str
    opportunity_set_fingerprint: str
    opportunity_id: str
    requirement_id: str
    observed_sequence: int = Field(
        ge=0, le=MAX_REQUIREMENT_VERIFICATION_OBSERVED_SEQUENCE
    )
    method: RequirementVerificationMethod
    outcome: RequirementVerificationOutcome
    receipt_reference_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_REQUIREMENT_VERIFICATION_RECEIPTS_PER_RESULT,
    )
    authority_kind: Literal[
        RequirementVerificationAuthorityKind.APP_OBJECTIVE_VERIFIER
    ] = RequirementVerificationAuthorityKind.APP_OBJECTIVE_VERIFIER
    issuer_version: Literal[
        REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION
    ] = REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION
    evidence_schema_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    evidence_policy_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    result_fingerprint: str
    app_issued: Literal[True] = True
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "result_id",
        "opportunity_set_fingerprint",
        "opportunity_id",
        "requirement_id",
        "result_fingerprint",
    )(_pseudonym)
    _receipts = field_validator("receipt_reference_ids")(
        _sorted_unique_pseudonyms
    )


class ExplicitRequirementAcceptanceAuthority(StrictModel):
    """Separate owned-native user authority; never a verification result."""

    acceptance_id: str
    opportunity_set_fingerprint: str
    opportunity_id: str
    requirement_id: str
    confirmation_id: str
    outcome: RequirementAcceptanceOutcome
    authority_kind: Literal[
        RequirementAcceptanceAuthorityKind.NATIVE_USER_ACCEPTANCE
    ] = RequirementAcceptanceAuthorityKind.NATIVE_USER_ACCEPTANCE
    issuer_version: Literal[
        REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION
    ] = REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION
    evidence_schema_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    evidence_policy_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    acceptance_fingerprint: str
    owned_native_action: Literal[True] = True
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "acceptance_id",
        "opportunity_set_fingerprint",
        "opportunity_id",
        "requirement_id",
        "confirmation_id",
        "acceptance_fingerprint",
    )(_pseudonym)


class RequirementVerificationEvidenceSet(StrictModel):
    """One bounded, versioned projection input for the objective metric."""

    opportunities: AppIssuedRequirementVerificationOpportunitySet
    verification_results: tuple[AppIssuedRequirementVerificationResult, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    acceptance_authorities: tuple[
        ExplicitRequirementAcceptanceAuthority, ...
    ] = Field(default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS)
    projection_version: Literal[
        REQUIREMENT_VERIFICATION_PROJECTION_VERSION
    ] = REQUIREMENT_VERIFICATION_PROJECTION_VERSION
    evidence_schema_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
    evidence_policy_version: Literal[
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    ] = REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
    evidence_set_fingerprint: str
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _fingerprint = field_validator("evidence_set_fingerprint")(_pseudonym)

    @model_validator(mode="after")
    def exact_authority_partition(self) -> "RequirementVerificationEvidenceSet":
        results = self.verification_results
        acceptances = self.acceptance_authorities
        if tuple(item.opportunity_id for item in results) != tuple(
            sorted(item.opportunity_id for item in results)
        ):
            raise ValueError("verification results must use deterministic order")
        if tuple(item.opportunity_id for item in acceptances) != tuple(
            sorted(item.opportunity_id for item in acceptances)
        ):
            raise ValueError("acceptance authorities must use deterministic order")
        result_opportunities = tuple(item.opportunity_id for item in results)
        acceptance_opportunities = tuple(item.opportunity_id for item in acceptances)
        if (
            len(set(result_opportunities)) != len(result_opportunities)
            or len(set(acceptance_opportunities)) != len(acceptance_opportunities)
            or set(result_opportunities) & set(acceptance_opportunities)
        ):
            raise ValueError("each requirement may have at most one result authority")
        issued = {
            item.opportunity_id: item.requirement_id
            for item in self.opportunities.opportunities
        }
        for item in (*results, *acceptances):
            if (
                item.opportunity_set_fingerprint
                != self.opportunities.opportunity_set_fingerprint
                or issued.get(item.opportunity_id) != item.requirement_id
            ):
                raise ValueError(
                    "requirement result belongs to another opportunity set"
                )
        return self


def _opportunity_identity_values(
    *,
    requirement_plan_evidence_fingerprint: str,
    requirement_index: int,
    requirement_id: str,
    coordinate: RequirementCoordinate,
) -> tuple[str, ...]:
    return (
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
        requirement_plan_evidence_fingerprint,
        str(requirement_index),
        requirement_id,
        str(coordinate.message_sequence),
        str(coordinate.clause_index),
    )


def _opportunity_set_identity_values(
    *,
    session_id: str,
    source_window_fingerprint: str,
    requirement_plan_confirmation_id: str,
    requirement_plan_proposal_id: str,
    requirement_plan_evidence_fingerprint: str,
    opportunities: tuple[AppIssuedRequirementVerificationOpportunity, ...],
) -> tuple[str, ...]:
    values = [
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
        REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION,
        REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION,
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        session_id,
        source_window_fingerprint,
        requirement_plan_confirmation_id,
        requirement_plan_proposal_id,
        requirement_plan_evidence_fingerprint,
        str(len(opportunities)),
    ]
    for item in opportunities:
        values.extend(
            (
                item.opportunity_id,
                str(item.requirement_index),
                item.requirement_id,
                str(item.coordinate.message_sequence),
                str(item.coordinate.clause_index),
            )
        )
    return tuple(values)


def issue_requirement_verification_opportunities(
    snapshot: RequirementPlanEvidenceSnapshot,
    identifiers: RequirementVerificationIdFactory,
) -> AppIssuedRequirementVerificationOpportunitySet:
    """Issue the exact active set from a complete native-reviewed r6 snapshot."""

    validated = RequirementPlanEvidenceSnapshot.model_validate(
        snapshot.model_dump(mode="python")
    )
    if (
        not validated.complete_user_clause_classification
        or validated.confirmation_id is None
        or validated.proposal_id is None
        or validated.producer_receipt is None
        or validated.review_rubric_version
        != REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    ):
        raise ValueError("complete native-reviewed r6 authority is required")
    r6_fingerprint = requirement_plan_snapshot_fingerprint(validated, identifiers)
    opportunities = tuple(
        AppIssuedRequirementVerificationOpportunity(
            opportunity_id=identifiers.fingerprint(
                "requirement-verification-opportunity-v1",
                _opportunity_identity_values(
                    requirement_plan_evidence_fingerprint=r6_fingerprint,
                    requirement_index=index,
                    requirement_id=item.requirement_id,
                    coordinate=item.coordinate,
                ),
            ),
            requirement_index=index,
            requirement_id=item.requirement_id,
            coordinate=item.coordinate,
        )
        for index, item in enumerate(validated.requirements)
    )
    set_fingerprint = identifiers.fingerprint(
        "requirement-verification-opportunity-set-v1",
        _opportunity_set_identity_values(
            session_id=validated.session_id,
            source_window_fingerprint=validated.source_window_fingerprint,
            requirement_plan_confirmation_id=validated.confirmation_id,
            requirement_plan_proposal_id=validated.proposal_id,
            requirement_plan_evidence_fingerprint=r6_fingerprint,
            opportunities=opportunities,
        ),
    )
    return AppIssuedRequirementVerificationOpportunitySet(
        session_id=validated.session_id,
        source_window_fingerprint=validated.source_window_fingerprint,
        requirement_plan_confirmation_id=validated.confirmation_id,
        requirement_plan_proposal_id=validated.proposal_id,
        requirement_plan_evidence_fingerprint=r6_fingerprint,
        opportunities=opportunities,
        opportunity_set_fingerprint=set_fingerprint,
    )


def validate_requirement_verification_opportunities(
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    snapshot: RequirementPlanEvidenceSnapshot,
    identifiers: RequirementVerificationIdFactory,
) -> AppIssuedRequirementVerificationOpportunitySet:
    """Reparse and cross-check an opportunity set against its exact r6 source."""

    validated = AppIssuedRequirementVerificationOpportunitySet.model_validate(
        opportunities.model_dump(mode="python")
    )
    expected = issue_requirement_verification_opportunities(snapshot, identifiers)
    if validated != expected or not hmac.compare_digest(
        validated.opportunity_set_fingerprint,
        expected.opportunity_set_fingerprint,
    ):
        raise ValueError("verification opportunities disagree with r6 authority")
    return validated


def _verification_result_identity_values(
    *,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    opportunity: AppIssuedRequirementVerificationOpportunity,
    observed_sequence: int,
    method: RequirementVerificationMethod,
    outcome: RequirementVerificationOutcome,
    receipt_reference_ids: tuple[str, ...],
) -> tuple[str, ...]:
    return (
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
        RequirementVerificationAuthorityKind.APP_OBJECTIVE_VERIFIER.value,
        opportunities.opportunity_set_fingerprint,
        opportunity.opportunity_id,
        opportunity.requirement_id,
        str(observed_sequence),
        method.value,
        outcome.value,
        *receipt_reference_ids,
    )


def issue_requirement_verification_result(
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    *,
    opportunity_id: str,
    observed_sequence: int,
    method: RequirementVerificationMethod,
    outcome: RequirementVerificationOutcome,
    receipt_reference_ids: tuple[str, ...],
    identifiers: RequirementVerificationIdFactory,
) -> AppIssuedRequirementVerificationResult:
    """Issue one keyed objective result; assistant-authored evidence has no type."""

    opportunity = next(
        (
            item
            for item in opportunities.opportunities
            if item.opportunity_id == opportunity_id
        ),
        None,
    )
    if opportunity is None:
        raise ValueError("verification result references an absent opportunity")
    checked_receipts = _sorted_unique_pseudonyms(receipt_reference_ids)
    values = _verification_result_identity_values(
        opportunities=opportunities,
        opportunity=opportunity,
        observed_sequence=observed_sequence,
        method=method,
        outcome=outcome,
        receipt_reference_ids=checked_receipts,
    )
    return AppIssuedRequirementVerificationResult(
        result_id=identifiers.fingerprint(
            "requirement-verification-result-id-v1", values
        ),
        opportunity_set_fingerprint=opportunities.opportunity_set_fingerprint,
        opportunity_id=opportunity.opportunity_id,
        requirement_id=opportunity.requirement_id,
        observed_sequence=observed_sequence,
        method=method,
        outcome=outcome,
        receipt_reference_ids=checked_receipts,
        result_fingerprint=identifiers.fingerprint(
            "requirement-verification-result-authority-v1", values
        ),
    )


def _acceptance_identity_values(
    *,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    opportunity: AppIssuedRequirementVerificationOpportunity,
    confirmation_id: str,
    outcome: RequirementAcceptanceOutcome,
) -> tuple[str, ...]:
    return (
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
        RequirementAcceptanceAuthorityKind.NATIVE_USER_ACCEPTANCE.value,
        opportunities.opportunity_set_fingerprint,
        opportunity.opportunity_id,
        opportunity.requirement_id,
        confirmation_id,
        outcome.value,
    )


def issue_explicit_requirement_acceptance(
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    *,
    opportunity_id: str,
    confirmation_id: str,
    outcome: RequirementAcceptanceOutcome,
    identifiers: RequirementVerificationIdFactory,
) -> ExplicitRequirementAcceptanceAuthority:
    """Issue a separate keyed receipt for one owned-native user decision."""

    _pseudonym(confirmation_id)
    opportunity = next(
        (
            item
            for item in opportunities.opportunities
            if item.opportunity_id == opportunity_id
        ),
        None,
    )
    if opportunity is None:
        raise ValueError("acceptance references an absent opportunity")
    values = _acceptance_identity_values(
        opportunities=opportunities,
        opportunity=opportunity,
        confirmation_id=confirmation_id,
        outcome=outcome,
    )
    return ExplicitRequirementAcceptanceAuthority(
        acceptance_id=identifiers.fingerprint(
            "requirement-acceptance-id-v1", values
        ),
        opportunity_set_fingerprint=opportunities.opportunity_set_fingerprint,
        opportunity_id=opportunity.opportunity_id,
        requirement_id=opportunity.requirement_id,
        confirmation_id=confirmation_id,
        outcome=outcome,
        acceptance_fingerprint=identifiers.fingerprint(
            "requirement-acceptance-authority-v1", values
        ),
    )


def _validate_verification_result(
    result: AppIssuedRequirementVerificationResult,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    identifiers: RequirementVerificationIdFactory,
) -> AppIssuedRequirementVerificationResult:
    validated = AppIssuedRequirementVerificationResult.model_validate(
        result.model_dump(mode="python")
    )
    expected = issue_requirement_verification_result(
        opportunities,
        opportunity_id=validated.opportunity_id,
        observed_sequence=validated.observed_sequence,
        method=validated.method,
        outcome=validated.outcome,
        receipt_reference_ids=validated.receipt_reference_ids,
        identifiers=identifiers,
    )
    if validated != expected or not hmac.compare_digest(
        validated.result_fingerprint, expected.result_fingerprint
    ):
        raise ValueError("verification result lacks app-issued authority")
    return validated


def validate_requirement_verification_result(
    result: AppIssuedRequirementVerificationResult,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    identifiers: RequirementVerificationIdFactory,
) -> AppIssuedRequirementVerificationResult:
    """Validate one result at an app-issued persistence boundary."""

    return _validate_verification_result(result, opportunities, identifiers)


def _validate_acceptance_authority(
    acceptance: ExplicitRequirementAcceptanceAuthority,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    identifiers: RequirementVerificationIdFactory,
) -> ExplicitRequirementAcceptanceAuthority:
    validated = ExplicitRequirementAcceptanceAuthority.model_validate(
        acceptance.model_dump(mode="python")
    )
    expected = issue_explicit_requirement_acceptance(
        opportunities,
        opportunity_id=validated.opportunity_id,
        confirmation_id=validated.confirmation_id,
        outcome=validated.outcome,
        identifiers=identifiers,
    )
    if validated != expected or not hmac.compare_digest(
        validated.acceptance_fingerprint,
        expected.acceptance_fingerprint,
    ):
        raise ValueError("acceptance lacks owned-native authority")
    return validated


def validate_explicit_requirement_acceptance(
    acceptance: ExplicitRequirementAcceptanceAuthority,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    identifiers: RequirementVerificationIdFactory,
) -> ExplicitRequirementAcceptanceAuthority:
    """Validate one native acceptance at an append-only boundary."""

    return _validate_acceptance_authority(acceptance, opportunities, identifiers)


def _evidence_set_identity_values(
    *,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    verification_results: tuple[AppIssuedRequirementVerificationResult, ...],
    acceptance_authorities: tuple[ExplicitRequirementAcceptanceAuthority, ...],
) -> tuple[str, ...]:
    return (
        REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
        REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        opportunities.opportunity_set_fingerprint,
        str(len(verification_results)),
        *(item.result_fingerprint for item in verification_results),
        str(len(acceptance_authorities)),
        *(item.acceptance_fingerprint for item in acceptance_authorities),
    )


def issue_requirement_verification_evidence_set(
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    *,
    verification_results: tuple[AppIssuedRequirementVerificationResult, ...] = (),
    acceptance_authorities: tuple[
        ExplicitRequirementAcceptanceAuthority, ...
    ] = (),
    identifiers: RequirementVerificationIdFactory,
) -> RequirementVerificationEvidenceSet:
    """Issue a deterministic projection input from individually issued records."""

    results = tuple(sorted(verification_results, key=lambda item: item.opportunity_id))
    acceptances = tuple(
        sorted(acceptance_authorities, key=lambda item: item.opportunity_id)
    )
    validated_results = tuple(
        _validate_verification_result(item, opportunities, identifiers)
        for item in results
    )
    validated_acceptances = tuple(
        _validate_acceptance_authority(item, opportunities, identifiers)
        for item in acceptances
    )
    values = _evidence_set_identity_values(
        opportunities=opportunities,
        verification_results=validated_results,
        acceptance_authorities=validated_acceptances,
    )
    return RequirementVerificationEvidenceSet(
        opportunities=opportunities,
        verification_results=validated_results,
        acceptance_authorities=validated_acceptances,
        evidence_set_fingerprint=identifiers.fingerprint(
            "requirement-verification-evidence-set-v1", values
        ),
    )


def validate_requirement_verification_evidence_set(
    evidence: RequirementVerificationEvidenceSet,
    snapshot: RequirementPlanEvidenceSnapshot,
    identifiers: RequirementVerificationIdFactory,
) -> RequirementVerificationEvidenceSet:
    """Reparse every authority and bind the evidence set to one exact r6 set."""

    validated = RequirementVerificationEvidenceSet.model_validate(
        evidence.model_dump(mode="python")
    )
    opportunities = validate_requirement_verification_opportunities(
        validated.opportunities, snapshot, identifiers
    )
    expected = issue_requirement_verification_evidence_set(
        opportunities,
        verification_results=validated.verification_results,
        acceptance_authorities=validated.acceptance_authorities,
        identifiers=identifiers,
    )
    if validated != expected or not hmac.compare_digest(
        validated.evidence_set_fingerprint,
        expected.evidence_set_fingerprint,
    ):
        raise ValueError("requirement verification evidence set is invalid")
    return validated


__all__ = (
    "AppIssuedRequirementVerificationOpportunity",
    "AppIssuedRequirementVerificationOpportunitySet",
    "AppIssuedRequirementVerificationResult",
    "ExplicitRequirementAcceptanceAuthority",
    "MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES",
    "MAX_REQUIREMENT_VERIFICATION_OBSERVED_SEQUENCE",
    "MAX_REQUIREMENT_VERIFICATION_RECEIPTS_PER_RESULT",
    "REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION",
    "REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION",
    "REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION",
    "REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION",
    "REQUIREMENT_VERIFICATION_PROJECTION_VERSION",
    "REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION",
    "RequirementAcceptanceAuthorityKind",
    "RequirementAcceptanceOutcome",
    "RequirementVerificationAuthorityKind",
    "RequirementVerificationEvidenceSet",
    "RequirementVerificationIdFactory",
    "RequirementVerificationMethod",
    "RequirementVerificationOutcome",
    "VERIFIED_REQUIREMENT_METRIC_KEY",
    "issue_explicit_requirement_acceptance",
    "issue_requirement_verification_evidence_set",
    "issue_requirement_verification_opportunities",
    "issue_requirement_verification_result",
    "validate_requirement_verification_evidence_set",
    "validate_requirement_verification_opportunities",
    "validate_requirement_verification_result",
    "validate_explicit_requirement_acceptance",
)
