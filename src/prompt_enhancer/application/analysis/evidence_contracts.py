"""Versioned, ephemeral contracts for structured coaching evidence.

These are ingress contracts, not persistence records. A provider adapter may
construct them only from a documented, compatibility-checked surface. Text is
secret-bearing and objective verification requires a provider or artifact
receipt; an assistant completion claim is not verification evidence.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from ..providers import CapabilityKey, DecoderDescriptor
from .text_contracts import TextLanguage


TYPED_EVIDENCE_SCHEMA_VERSION = 2
MAX_TYPED_EVIDENCE_RECORDS = 5_000


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("evidence identifiers must be HMAC pseudonyms")
    return value


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("evidence provenance must use safe identifiers")
    return value


def _unique_pseudonyms(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(_pseudonym(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("evidence references cannot contain duplicates")
    return normalized


class TypedEvidenceKind(StrEnum):
    ACTION = "action"
    DECISION = "decision"
    FEEDBACK = "feedback"
    VERIFICATION = "verification"


class TypedEvidenceOpportunityKind(StrEnum):
    """Denominator families an adapter can authoritatively enumerate.

    Declaring a family is distinct from supplying a non-empty set.  This lets
    an adapter truthfully report an empty eligible set without making an
    absent/unsupported denominator look like not-applicable.
    """

    REQUIREMENT = "requirement"
    HYPOTHESIS = "hypothesis"
    MATERIAL_CLAIM = "material_claim"
    VERIFICATION_TASK = "verification_task"


class ActionFamily(StrEnum):
    TOOL = "tool"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    REVIEW = "review"
    OTHER_DOCUMENTED = "other_documented"


class ActionState(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class DecisionState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class RationaleState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class VerificationMethod(StrEnum):
    TEST = "test"
    STATIC_CHECK = "static_check"
    BUILD = "build"
    ARTIFACT_INSPECTION = "artifact_inspection"
    HUMAN_ACCEPTANCE = "human_acceptance"
    OTHER_DOCUMENTED = "other_documented"


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"


class _EvidenceBase(StrictModel):
    evidence_id: str
    sequence: int = Field(ge=0)
    source_reference_id: str

    _validate_evidence_id = field_validator("evidence_id")(_pseudonym)
    _validate_source_reference = field_validator("source_reference_id")(
        _pseudonym
    )


class ActionEvidence(_EvidenceBase):
    kind: Literal[TypedEvidenceKind.ACTION] = TypedEvidenceKind.ACTION
    family: ActionFamily
    state: ActionState
    requirement_reference_ids: tuple[str, ...] = ()
    hypothesis_reference_ids: tuple[str, ...] = ()

    _validate_links = field_validator(
        "requirement_reference_ids",
        "hypothesis_reference_ids",
    )(_unique_pseudonyms)


class DecisionEvidence(_EvidenceBase):
    kind: Literal[TypedEvidenceKind.DECISION] = TypedEvidenceKind.DECISION
    state: DecisionState
    rationale_state: RationaleState
    rationale_reference_id: str | None = None
    requirement_reference_ids: tuple[str, ...] = ()
    hypothesis_reference_ids: tuple[str, ...] = ()

    _validate_rationale_reference = field_validator("rationale_reference_id")(
        lambda value: None if value is None else _pseudonym(value)
    )
    _validate_links = field_validator(
        "requirement_reference_ids",
        "hypothesis_reference_ids",
    )(_unique_pseudonyms)

    @model_validator(mode="after")
    def rationale_reference_matches_state(self) -> DecisionEvidence:
        if (
            self.rationale_state is RationaleState.PRESENT
            and self.rationale_reference_id is None
        ):
            raise ValueError("present rationale requires a source reference")
        if (
            self.rationale_state is not RationaleState.PRESENT
            and self.rationale_reference_id is not None
        ):
            raise ValueError("non-present rationale cannot claim a source reference")
        return self


class FeedbackEvidence(_EvidenceBase):
    kind: Literal[TypedEvidenceKind.FEEDBACK] = TypedEvidenceKind.FEEDBACK
    language: TextLanguage
    text: SecretStr = Field(repr=False, min_length=1, max_length=32_000)
    supersedes_evidence_ids: tuple[str, ...] = ()

    _validate_superseded = field_validator("supersedes_evidence_ids")(
        _unique_pseudonyms
    )

    @field_validator("text")
    @classmethod
    def reject_nul(cls, value: SecretStr) -> SecretStr:
        if "\x00" in value.get_secret_value():
            raise ValueError("feedback evidence cannot contain NUL")
        return value


class VerificationEvidence(_EvidenceBase):
    kind: Literal[TypedEvidenceKind.VERIFICATION] = (
        TypedEvidenceKind.VERIFICATION
    )
    method: VerificationMethod
    outcome: VerificationOutcome
    objective: Literal[True] = True
    receipt_reference_ids: tuple[str, ...] = Field(min_length=1)
    requirement_reference_ids: tuple[str, ...] = ()
    hypothesis_reference_ids: tuple[str, ...] = ()
    claim_reference_ids: tuple[str, ...] = ()
    verification_task_reference_ids: tuple[str, ...] = ()

    _validate_receipts = field_validator("receipt_reference_ids")(
        _unique_pseudonyms
    )
    _validate_links = field_validator(
        "requirement_reference_ids",
        "hypothesis_reference_ids",
        "claim_reference_ids",
        "verification_task_reference_ids",
    )(_unique_pseudonyms)


TypedEvidenceRecord = Annotated[
    ActionEvidence | DecisionEvidence | FeedbackEvidence | VerificationEvidence,
    Field(discriminator="kind"),
]


class TypedEvidenceProvenance(StrictModel):
    provider: Provider
    provider_version: str
    adapter_version: str
    decoder_key: str
    decoder_version: str
    source_schema_version: str
    evidence_schema_version: int = TYPED_EVIDENCE_SCHEMA_VERSION
    extraction_complete: bool = False

    _validate_versions = field_validator(
        "provider_version",
        "adapter_version",
        "decoder_key",
        "decoder_version",
        "source_schema_version",
    )(_safe_version)


class EphemeralTypedEvidenceProjection(StrictModel):
    """Bounded secret-bearing projection that must never be persisted."""

    session_id: str
    provenance: TypedEvidenceProvenance
    declared_kinds: frozenset[TypedEvidenceKind]
    declared_opportunity_kinds: frozenset[TypedEvidenceOpportunityKind] = (
        frozenset()
    )
    eligible_requirement_reference_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_TYPED_EVIDENCE_RECORDS
    )
    eligible_hypothesis_reference_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_TYPED_EVIDENCE_RECORDS
    )
    eligible_claim_reference_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_TYPED_EVIDENCE_RECORDS
    )
    eligible_verification_task_reference_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_TYPED_EVIDENCE_RECORDS
    )
    records: tuple[TypedEvidenceRecord, ...] = Field(
        repr=False,
        max_length=MAX_TYPED_EVIDENCE_RECORDS,
    )

    _validate_opportunity_ids = field_validator(
        "eligible_requirement_reference_ids",
        "eligible_hypothesis_reference_ids",
        "eligible_claim_reference_ids",
        "eligible_verification_task_reference_ids",
    )(_unique_pseudonyms)
    _validate_session_id = field_validator("session_id")(_pseudonym)

    @model_validator(mode="after")
    def validate_projection(self) -> EphemeralTypedEvidenceProjection:
        identities = tuple(record.evidence_id for record in self.records)
        if len(set(identities)) != len(identities):
            raise ValueError("typed evidence records cannot share identifiers")
        sequences = tuple(record.sequence for record in self.records)
        if len(set(sequences)) != len(sequences):
            raise ValueError("typed evidence records cannot share a sequence")
        if sequences != tuple(sorted(sequences)):
            raise ValueError("typed evidence records must be chronological")
        observed = {record.kind for record in self.records}
        if not observed.issubset(self.declared_kinds):
            raise ValueError("observed evidence was not declared by the adapter")

        opportunity_sets = {
            TypedEvidenceOpportunityKind.REQUIREMENT: frozenset(
                self.eligible_requirement_reference_ids
            ),
            TypedEvidenceOpportunityKind.HYPOTHESIS: frozenset(
                self.eligible_hypothesis_reference_ids
            ),
            TypedEvidenceOpportunityKind.MATERIAL_CLAIM: frozenset(
                self.eligible_claim_reference_ids
            ),
            TypedEvidenceOpportunityKind.VERIFICATION_TASK: frozenset(
                self.eligible_verification_task_reference_ids
            ),
        }
        for kind, references in opportunity_sets.items():
            if references and kind not in self.declared_opportunity_kinds:
                raise ValueError(
                    "eligible evidence opportunities were not declared by the adapter"
                )

        linked_by_kind = {
            TypedEvidenceOpportunityKind.REQUIREMENT: frozenset(
                reference
                for record in self.records
                if isinstance(
                    record,
                    (ActionEvidence, DecisionEvidence, VerificationEvidence),
                )
                for reference in record.requirement_reference_ids
            ),
            TypedEvidenceOpportunityKind.HYPOTHESIS: frozenset(
                reference
                for record in self.records
                if isinstance(
                    record,
                    (ActionEvidence, DecisionEvidence, VerificationEvidence),
                )
                for reference in record.hypothesis_reference_ids
            ),
            TypedEvidenceOpportunityKind.MATERIAL_CLAIM: frozenset(
                reference
                for record in self.records
                if isinstance(record, VerificationEvidence)
                for reference in record.claim_reference_ids
            ),
            TypedEvidenceOpportunityKind.VERIFICATION_TASK: frozenset(
                reference
                for record in self.records
                if isinstance(record, VerificationEvidence)
                for reference in record.verification_task_reference_ids
            ),
        }
        for kind, linked in linked_by_kind.items():
            if linked and kind not in self.declared_opportunity_kinds:
                raise ValueError(
                    "evidence links require an authoritative opportunity declaration"
                )
            if not linked.issubset(opportunity_sets[kind]):
                raise ValueError(
                    "evidence links fall outside the authoritative eligible set"
                )
        return self


_CAPABILITY_FOR_KIND = {
    TypedEvidenceKind.ACTION: CapabilityKey.TOOL_EVENTS,
    TypedEvidenceKind.DECISION: CapabilityKey.DECISION_EVENTS,
    TypedEvidenceKind.FEEDBACK: CapabilityKey.FEEDBACK_MESSAGES,
    TypedEvidenceKind.VERIFICATION: CapabilityKey.VERIFICATION_EVENTS,
}
#: Authority to *enumerate* one denominator family.  Observing evidence of a
#: kind never implies knowing the complete eligible set that kind belongs to.
ENUMERATION_CAPABILITY_FOR_OPPORTUNITY = MappingProxyType(
    {
        TypedEvidenceOpportunityKind.REQUIREMENT: (
            CapabilityKey.REQUIREMENT_OPPORTUNITIES
        ),
        TypedEvidenceOpportunityKind.HYPOTHESIS: (
            CapabilityKey.HYPOTHESIS_OPPORTUNITIES
        ),
        TypedEvidenceOpportunityKind.MATERIAL_CLAIM: (
            CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES
        ),
        TypedEvidenceOpportunityKind.VERIFICATION_TASK: (
            CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES
        ),
    }
)
#: Authority to say which member of a denominator family a record belongs to.
LINK_CAPABILITY_FOR_OPPORTUNITY = MappingProxyType(
    {
        TypedEvidenceOpportunityKind.REQUIREMENT: (
            CapabilityKey.REQUIREMENT_EVIDENCE_LINKS
        ),
        TypedEvidenceOpportunityKind.HYPOTHESIS: (
            CapabilityKey.HYPOTHESIS_EVIDENCE_LINKS
        ),
        TypedEvidenceOpportunityKind.MATERIAL_CLAIM: (
            CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS
        ),
        TypedEvidenceOpportunityKind.VERIFICATION_TASK: (
            CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS
        ),
    }
)


def linked_opportunity_kinds(
    projection: EphemeralTypedEvidenceProjection,
) -> frozenset[TypedEvidenceOpportunityKind]:
    """Opportunity families this projection's records actually reference."""

    linked: set[TypedEvidenceOpportunityKind] = set()
    for record in projection.records:
        if isinstance(
            record, (ActionEvidence, DecisionEvidence, VerificationEvidence)
        ):
            if record.requirement_reference_ids:
                linked.add(TypedEvidenceOpportunityKind.REQUIREMENT)
            if record.hypothesis_reference_ids:
                linked.add(TypedEvidenceOpportunityKind.HYPOTHESIS)
        if isinstance(record, VerificationEvidence):
            if record.claim_reference_ids:
                linked.add(TypedEvidenceOpportunityKind.MATERIAL_CLAIM)
            if record.verification_task_reference_ids:
                linked.add(TypedEvidenceOpportunityKind.VERIFICATION_TASK)
    return frozenset(linked)


def validate_projection_descriptor(
    projection: EphemeralTypedEvidenceProjection,
    descriptor: DecoderDescriptor,
) -> None:
    """Reject a projection not covered by the exact decoder identity.

    Three separate authorities are checked, never inferred from one another:
    the evidence *kinds* the decoder may emit, the denominator families it may
    *enumerate*, and the families whose members it may *link* a record to.
    """

    provenance = projection.provenance
    if (
        descriptor.provider.key != provenance.provider.value
        or descriptor.adapter_version != provenance.adapter_version
        or descriptor.decoder_key != provenance.decoder_key
        or descriptor.decoder_version != provenance.decoder_version
        or descriptor.canonical_schema_version != provenance.source_schema_version
    ):
        raise ValueError("typed evidence provenance does not match the decoder")
    declared_capabilities = set(descriptor.capabilities)
    if any(
        _CAPABILITY_FOR_KIND[kind] not in declared_capabilities
        for kind in projection.declared_kinds
    ):
        raise ValueError("typed evidence kind was not declared by the decoder")
    if any(
        ENUMERATION_CAPABILITY_FOR_OPPORTUNITY[kind] not in declared_capabilities
        for kind in projection.declared_opportunity_kinds
    ):
        raise ValueError(
            "typed evidence opportunity enumeration was not declared by the decoder"
        )
    if any(
        LINK_CAPABILITY_FOR_OPPORTUNITY[kind] not in declared_capabilities
        for kind in projection.declared_opportunity_kinds
    ):
        # An authoritative denominator without authority to observe its links
        # could otherwise become a measured 0/N simply because the adapter was
        # unable to emit any relationship.  Declaring a family therefore
        # requires both enumeration and negative-link observability.
        raise ValueError(
            "typed evidence opportunity link authority was not declared by the decoder"
        )
    if any(
        LINK_CAPABILITY_FOR_OPPORTUNITY[kind] not in declared_capabilities
        for kind in linked_opportunity_kinds(projection)
    ):
        raise ValueError(
            "typed evidence opportunity link was not declared by the decoder"
        )


__all__ = [
    "ActionEvidence",
    "ActionFamily",
    "ActionState",
    "DecisionEvidence",
    "DecisionState",
    "ENUMERATION_CAPABILITY_FOR_OPPORTUNITY",
    "EphemeralTypedEvidenceProjection",
    "FeedbackEvidence",
    "LINK_CAPABILITY_FOR_OPPORTUNITY",
    "RationaleState",
    "TYPED_EVIDENCE_SCHEMA_VERSION",
    "TypedEvidenceKind",
    "TypedEvidenceOpportunityKind",
    "TypedEvidenceProvenance",
    "TypedEvidenceRecord",
    "VerificationEvidence",
    "VerificationMethod",
    "VerificationOutcome",
    "linked_opportunity_kinds",
    "validate_projection_descriptor",
]
