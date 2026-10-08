"""Strict contracts for reviewed requirement-to-action traceability.

An agent may propose links between application-issued requirement and action
identifiers.  The file cannot author action state, a metric value, or objective
proof.  A proposal remains inert until an owned native window displays the
complete requirement/action review set and records an exact one-shot decision.
Only content-free coordinates, safe event receipts, hashes, and provenance may
cross the durable boundary.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import hmac
import json
from secrets import token_bytes, token_hex
from threading import Lock
from time import monotonic
from typing import Any, Literal, Protocol
import unicodedata

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    EventKind,
    StrictModel,
    ToolCategory,
)
from .evidence_contracts import ActionFamily, ActionState, TypedEvidenceProvenance
from .requirement_plan_evidence import (
    RequirementCoordinate,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanProducer,
    RequirementPlanProducerReceipt,
    reviewable_message_clauses,
)
from .text_contracts import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
    EphemeralRedactedActionDescriptor,
    MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS,
    MAX_REDACTED_MESSAGE_CHARACTERS,
    P1TextAnalysisInput,
    TextMessageKind,
    TextRole,
)

# Transitional public alias used by the provider adapter while the r7 slice is
# assembled.  It is the existing closed evidence state enum, not a second
# source of truth.
RequirementActionCandidateState = ActionState


REQUIREMENT_ACTION_METRIC_KEY = "logic.requirement_action_traceability"
REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION = "requirement-action-evidence-v1"
REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION = "requirement-action-evidence-file-v1"
REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION = "reviewed-requirement-action-v1"
REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION = "requirement-action-review-rubric-v2"
REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION = (
    "requirement-action-review-visible-display-v1"
)
REQUIREMENT_ACTION_CANDIDATE_MANIFEST_VERSION = (
    "requirement-action-candidate-manifest-v1"
)
REQUIREMENT_ACTION_IMPORT_CONFIRMATION = (
    "import_requirement_action_proposal_without_metric_authority"
)
REQUIREMENT_ACTION_REVIEW_CONFIRMATION = (
    "open_exact_local_requirement_action_review"
)
REQUIREMENT_ACTION_DECISION_CONFIRMATION = (
    "decide_exact_reviewed_requirement_action_proposal"
)
REQUIREMENT_ACTION_CANONICALIZATION = "json-sort-keys-compact-ensure-ascii-v1"
MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES = 64 * 1024
MAX_REQUIREMENT_ACTION_EVIDENCE_DEPTH = 8
MAX_REQUIREMENT_ACTION_EVIDENCE_ITEMS = 8_000
MAX_REQUIREMENT_ACTION_EVIDENCE_LIFETIME = timedelta(hours=24)
MAX_REQUIREMENT_ACTION_REQUIREMENTS = 1_000
MAX_REQUIREMENT_ACTION_CANDIDATES = 4_000
MAX_REQUIREMENT_ACTION_LINKS = 8_000
MAX_REQUIREMENT_ACTION_PAGE_SIZE = 200
REQUIREMENT_ACTION_REVIEW_CONTEXT_TTL = timedelta(minutes=15)
REQUIREMENT_ACTION_REVIEW_RECEIPT_TTL = timedelta(minutes=10)
MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_CONTEXTS = 16
MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_RECEIPTS = 32

_BIDI_DISPLAY_CONTROL_CLASSES = frozenset(
    {
        "BN",
        "FSI",
        "LRE",
        "LRI",
        "LRO",
        "PDF",
        "PDI",
        "RLE",
        "RLI",
        "RLO",
    }
)
_LAYOUT_DISPLAY_CONTROL_CODEPOINTS = frozenset({0x2028, 0x2029})


def _is_forbidden_review_display_character(value: str) -> bool:
    return (
        unicodedata.category(value) in {"Cc", "Cf", "Cs"}
        or ord(value) in _LAYOUT_DISPLAY_CONTROL_CODEPOINTS
        or unicodedata.bidirectional(value) in _BIDI_DISPLAY_CONTROL_CLASSES
    )


def escape_requirement_action_review_display(value: str) -> str:
    """Return the frozen injective one-pass encoding for native review text.

    Printable Unicode remains readable.  Literal backslashes are doubled so
    an input spelling such as ``\\u202e`` cannot collide with an encoded U+202E.
    The caller must always apply this exactly once to raw process-only text.
    """

    escaped: list[str] = []
    for character in value:
        if character == "\\":
            escaped.append("\\\\")
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif _is_forbidden_review_display_character(character):
            codepoint = ord(character)
            escaped.append(
                f"\\u{codepoint:04x}"
                if codepoint <= 0xFFFF
                else f"\\U{codepoint:08x}"
            )
        else:
            escaped.append(character)
    return "".join(escaped)


def _visible_review_display(
    value: str,
    *,
    max_length: int,
) -> str:
    transformed = escape_requirement_action_review_display(value)
    if len(transformed) > max_length:
        raise RequirementActionConflictError(
            "visible requirement-action review text exceeds its bound"
        )
    return transformed


def _reject_forbidden_review_display(value: str | None) -> str | None:
    if value is not None and any(
        _is_forbidden_review_display_character(character) for character in value
    ):
        raise ValueError("review display contains a raw forbidden control")
    return value


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be an installation-local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("version identifier is invalid")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


class RequirementActionDecisionKind(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


class RequirementActionProposalStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RequirementActionCandidate(StrictModel):
    """One application-issued, content-free safe action receipt."""

    candidate_index: int = Field(ge=0, lt=MAX_REQUIREMENT_ACTION_CANDIDATES)
    action_id: str
    source_reference_id: str
    sequence: int = Field(ge=0, le=4_000_000_000)
    event_kind: EventKind
    tool_category: ToolCategory | None = None
    occurred_at: datetime
    duration_ms: int | None = Field(default=None, ge=0)
    family: ActionFamily
    state: ActionState

    _ids = field_validator("action_id", "source_reference_id")(_pseudonym)
    _occurred = field_validator("occurred_at")(_utc)

    @model_validator(mode="after")
    def exact_safe_event_shape(self) -> "RequirementActionCandidate":
        if self.event_kind not in {
            EventKind.TOOL_START,
            EventKind.TOOL_END,
            EventKind.ARTIFACT,
        }:
            raise ValueError("candidate is not a safe action event")
        return self


class RequirementActionCandidateManifest(StrictModel):
    """Exact provider-owned safe-action set for one sealed source run."""

    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    provenance: TypedEvidenceProvenance
    extraction_complete: bool
    enumeration_complete: bool
    actions: tuple[RequirementActionCandidate, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    manifest_fingerprint: str
    schema_version: Literal[REQUIREMENT_ACTION_CANDIDATE_MANIFEST_VERSION] = (
        REQUIREMENT_ACTION_CANDIDATE_MANIFEST_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
        "manifest_fingerprint",
    )(_pseudonym)

    @model_validator(mode="after")
    def exact_manifest(self) -> "RequirementActionCandidateManifest":
        indexes = tuple(item.candidate_index for item in self.actions)
        action_ids = tuple(item.action_id for item in self.actions)
        sequences = tuple(item.sequence for item in self.actions)
        if indexes != tuple(range(len(self.actions))):
            raise ValueError("action candidate indexes must be dense and ordered")
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action candidate identifiers must be unique")
        if sequences != tuple(sorted(set(sequences))):
            raise ValueError("action candidate sequences must be ordered and unique")
        if self.enumeration_complete and not self.extraction_complete:
            raise ValueError("complete enumeration requires complete extraction")
        if self.extraction_complete != self.provenance.extraction_complete:
            raise ValueError("manifest completeness disagrees with provider provenance")
        return self


def requirement_action_candidate_manifest_fingerprint(
    manifest: RequirementActionCandidateManifest,
) -> str:
    """Canonical content-free identity for one app-issued candidate set."""

    payload = manifest.model_dump(
        mode="json", exclude={"manifest_fingerprint"}
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def requirement_action_candidate_metadata_fingerprint(
    *,
    source_reference_id: str,
    sequence: int,
    event_kind: EventKind,
    tool_category: ToolCategory | None,
    occurred_at: datetime,
    duration_ms: int | None,
    family: ActionFamily,
    state: ActionState,
) -> str:
    """Canonical content-free identity of one same-snapshot action receipt."""

    _pseudonym(source_reference_id)
    _utc(occurred_at)
    if sequence < 0 or sequence > 4_000_000_000:
        raise ValueError("candidate sequence is outside its bound")
    if duration_ms is not None and duration_ms < 0:
        raise ValueError("candidate duration cannot be negative")
    success = (
        True
        if state is ActionState.COMPLETED
        else False
        if state is ActionState.FAILED
        else None
    )
    payload = {
        "version": ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
        "source_reference_id": source_reference_id,
        "sequence": sequence,
        "event_kind": event_kind.value,
        "tool_category": (
            None if tool_category is None else tool_category.value
        ),
        "occurred_at": occurred_at.isoformat(),
        "duration_ms": duration_ms,
        "family": family.value,
        "state": state.value,
        "success": success,
    }
    return hashlib.sha256(
        b"prompt-enhancer/requirement-action-candidate-metadata/v1\0"
        + json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def requirement_action_descriptor_matches_candidate_metadata(
    candidate: RequirementActionCandidate,
    descriptor: EphemeralRedactedActionDescriptor,
) -> bool:
    """Constant-time exact same-snapshot candidate/descriptor comparison."""

    if (
        descriptor.source_reference_id != candidate.source_reference_id
        or descriptor.event_kind is not candidate.event_kind
        or descriptor.candidate_metadata_fingerprint_version
        != ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
        or descriptor.candidate_metadata_fingerprint is None
    ):
        return False
    expected = requirement_action_candidate_metadata_fingerprint(
        source_reference_id=candidate.source_reference_id,
        sequence=candidate.sequence,
        event_kind=candidate.event_kind,
        tool_category=candidate.tool_category,
        occurred_at=candidate.occurred_at,
        duration_ms=candidate.duration_ms,
        family=candidate.family,
        state=candidate.state,
    )
    return hmac.compare_digest(
        descriptor.candidate_metadata_fingerprint,
        expected,
    )


class RequirementActionRequirement(StrictModel):
    requirement_index: int = Field(ge=0, lt=MAX_REQUIREMENT_ACTION_REQUIREMENTS)
    requirement_id: str
    coordinate: RequirementCoordinate

    _id = field_validator("requirement_id")(_pseudonym)


class RequirementActionLinkEntry(StrictModel):
    """File proposal for one exact requirement and zero or more actions."""

    requirement_index: int = Field(ge=0, lt=MAX_REQUIREMENT_ACTION_REQUIREMENTS)
    action_candidate_indexes: tuple[int, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )

    @field_validator("action_candidate_indexes")
    @classmethod
    def sorted_unique_indexes(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 or value >= MAX_REQUIREMENT_ACTION_CANDIDATES for value in values):
            raise ValueError("action candidate index is outside the bounded manifest")
        if values != tuple(sorted(set(values))):
            raise ValueError("action candidate indexes must be unique and sorted")
        return values


class RequirementActionEvidenceFileV1(StrictModel):
    """Portable untrusted proposal; it contains no action-state fields."""

    schema_version: Literal[REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION]
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    requirement_plan_confirmation_id: str
    requirement_plan_evidence_fingerprint: str
    candidate_manifest_fingerprint: str
    expected_predecessor_confirmation_id: str | None = None
    nonce: str
    created_at: datetime
    expires_at: datetime
    producer: RequirementPlanProducer
    complete_requirement_enumeration: Literal[True]
    complete_action_candidate_enumeration: Literal[True]
    complete_requirement_link_classification: Literal[True]
    links: tuple[RequirementActionLinkEntry, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    contains_action_state_claims: Literal[False]
    contains_objective_proof_claims: Literal[False]
    contains_metric_values: Literal[False]
    contains_prose: Literal[False]
    contains_paths: Literal[False]

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "candidate_manifest_fingerprint",
        "nonce",
    )(_pseudonym)
    _times = field_validator("created_at", "expires_at")(_utc)

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_bundle(self) -> "RequirementActionEvidenceFileV1":
        indexes = tuple(item.requirement_index for item in self.links)
        if indexes != tuple(range(len(self.links))):
            raise ValueError("every requirement must appear exactly once in order")
        if not self.created_at < self.expires_at:
            raise ValueError("evidence expiry must follow creation")
        if self.expires_at - self.created_at > MAX_REQUIREMENT_ACTION_EVIDENCE_LIFETIME:
            raise ValueError("evidence lifetime exceeds the local bound")
        if sum(len(item.action_candidate_indexes) for item in self.links) > (
            MAX_REQUIREMENT_ACTION_LINKS
        ):
            raise ValueError("requirement-action links exceed their bound")
        return self


class RequirementActionEvidencePreview(StrictModel):
    payload_sha256: str
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    requirement_plan_confirmation_id: str
    requirement_plan_evidence_fingerprint: str
    candidate_manifest_fingerprint: str
    expected_predecessor_confirmation_id: str | None = None
    requirement_count: int = Field(ge=0, le=MAX_REQUIREMENT_ACTION_REQUIREMENTS)
    candidate_count: int = Field(ge=0, le=MAX_REQUIREMENT_ACTION_CANDIDATES)
    linked_requirement_count: int = Field(ge=0, le=MAX_REQUIREMENT_ACTION_REQUIREMENTS)
    unlinked_requirement_count: int = Field(ge=0, le=MAX_REQUIREMENT_ACTION_REQUIREMENTS)
    link_count: int = Field(ge=0, le=MAX_REQUIREMENT_ACTION_LINKS)
    expires_at: datetime
    producer: RequirementPlanProducer
    creates_unconfirmed_proposal_only: Literal[True] = True
    native_confirmation_required_for_metric_authority: Literal[True] = True
    can_set_numeric_metric_on_import: Literal[False] = False
    raw_payload_persisted: Literal[False] = False
    raw_producer_claim_persisted: Literal[False] = False

    _ids = field_validator(
        "payload_sha256",
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "candidate_manifest_fingerprint",
    )(_pseudonym)
    _expiry = field_validator("expires_at")(_utc)

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_counts(self) -> "RequirementActionEvidencePreview":
        if self.requirement_count != (
            self.linked_requirement_count + self.unlinked_requirement_count
        ):
            raise ValueError("requirement-action preview counts are incoherent")
        if self.linked_requirement_count > self.link_count:
            raise ValueError("linked requirements require at least one action link")
        if self.candidate_count == 0 and self.link_count != 0:
            raise ValueError("action links require candidate actions")
        return self


class ConfirmedRequirementActionLink(StrictModel):
    requirement_id: str
    action_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )

    _requirement_id = field_validator("requirement_id")(_pseudonym)

    @field_validator("action_ids")
    @classmethod
    def sorted_unique_action_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_pseudonym(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("linked action identifiers must be unique and sorted")
        return checked


class RequirementActionProposalRecord(StrictModel):
    proposal_id: str
    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    requirement_plan_confirmation_id: str
    requirement_plan_evidence_fingerprint: str
    candidate_manifest_fingerprint: str
    candidate_provenance: TypedEvidenceProvenance
    candidate_extraction_complete: bool
    candidate_enumeration_complete: bool
    expected_predecessor_confirmation_id: str | None = None
    payload_sha256: str
    idempotency_key_digest: str
    command_fingerprint: str
    producer_receipt: RequirementPlanProducerReceipt
    requirements: tuple[RequirementActionRequirement, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    candidates: tuple[RequirementActionCandidate, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    links: tuple[ConfirmedRequirementActionLink, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    created_at: datetime
    schema_version: Literal[REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION] = (
        REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION
    )
    policy_version: Literal[REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION] = (
        REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION
    )
    review_rubric_version: Literal[REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "proposal_id",
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "candidate_manifest_fingerprint",
        "payload_sha256",
        "idempotency_key_digest",
        "command_fingerprint",
    )(_pseudonym)
    _created = field_validator("created_at")(_utc)

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_graph(self) -> "RequirementActionProposalRecord":
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        requirement_indexes = tuple(item.requirement_index for item in self.requirements)
        candidate_indexes = tuple(item.candidate_index for item in self.candidates)
        candidate_ids = tuple(item.action_id for item in self.candidates)
        link_requirement_ids = tuple(item.requirement_id for item in self.links)
        action_id_set = set(candidate_ids)
        if requirement_indexes != tuple(range(len(self.requirements))):
            raise ValueError("stored requirements must retain dense indexes")
        if requirement_ids != tuple(sorted(set(requirement_ids))):
            raise ValueError("stored requirement identifiers must be sorted and unique")
        if candidate_indexes != tuple(range(len(self.candidates))):
            raise ValueError("stored candidates must retain dense indexes")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("stored candidate identifiers must be unique")
        candidate_sequences = tuple(item.sequence for item in self.candidates)
        if candidate_sequences != tuple(sorted(set(candidate_sequences))):
            raise ValueError("stored candidate sequences must be ordered and unique")
        if link_requirement_ids != requirement_ids:
            raise ValueError("stored links must cover every requirement exactly once")
        if any(
            action_id not in action_id_set
            for item in self.links
            for action_id in item.action_ids
        ):
            raise ValueError("stored link references an absent candidate action")
        if sum(len(item.action_ids) for item in self.links) > MAX_REQUIREMENT_ACTION_LINKS:
            raise ValueError("stored requirement-action links exceed their bound")
        if self.candidate_enumeration_complete and not self.candidate_extraction_complete:
            raise ValueError("complete candidate enumeration requires complete extraction")
        return self


def requirement_action_graph_fingerprint(
    proposal: RequirementActionProposalRecord,
) -> str:
    payload = proposal.model_dump(
        mode="json",
        exclude={"proposal_id", "idempotency_key_digest", "command_fingerprint", "created_at"},
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
    ).hexdigest()


def requirement_action_decision_authority_fingerprint(
    identifiers: "RequirementActionIdFactory",
    *,
    proposal: RequirementActionProposalRecord,
    decision_id: str,
    decision: RequirementActionDecisionKind,
    idempotency_key_digest: str,
    command_fingerprint: str,
    reviewed_descriptor_set_fingerprint: str | None,
) -> str:
    """Installation-keyed proof that the application issued one decision."""

    return identifiers.fingerprint(
        "requirement-action-decision-authority-v1",
        (
            decision_id,
            proposal.proposal_id,
            proposal.session_id,
            decision.value,
            proposal.source_run_id,
            proposal.source_window_fingerprint,
            requirement_action_graph_fingerprint(proposal),
            proposal.payload_sha256,
            proposal.candidate_manifest_fingerprint,
            proposal.expected_predecessor_confirmation_id or "none",
            idempotency_key_digest,
            command_fingerprint,
            reviewed_descriptor_set_fingerprint or "none",
            REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION,
            REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION,
            REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION,
            "owned_native_user_presence",
        ),
    )


class RequirementActionDecisionCommand(StrictModel):
    expected_source_run_id: str
    decision: RequirementActionDecisionKind
    confirmation: Literal[REQUIREMENT_ACTION_DECISION_CONFIRMATION]
    review_receipt_id: str | None = None
    reviewed_graph_fingerprint: str | None = None
    candidate_manifest_fingerprint: str | None = None
    reviewed_candidate_set_fingerprint: str | None = None
    reviewed_descriptor_set_fingerprint: str | None = None
    complete_review_acknowledged: bool = False
    all_requirements_and_candidates_acknowledged: bool = False
    all_linked_action_semantics_reviewed: bool = False

    _run = field_validator("expected_source_run_id")(_pseudonym)

    @field_validator(
        "review_receipt_id",
        "reviewed_graph_fingerprint",
        "candidate_manifest_fingerprint",
        "reviewed_candidate_set_fingerprint",
        "reviewed_descriptor_set_fingerprint",
    )
    @classmethod
    def optional_review_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_review_authority(self) -> "RequirementActionDecisionCommand":
        receipt_fields = (
            self.review_receipt_id,
            self.reviewed_graph_fingerprint,
            self.candidate_manifest_fingerprint,
            self.reviewed_candidate_set_fingerprint,
            self.reviewed_descriptor_set_fingerprint,
        )
        if self.decision is RequirementActionDecisionKind.CONFIRM:
            if (
                any(item is None for item in receipt_fields)
                or not self.complete_review_acknowledged
                or not self.all_requirements_and_candidates_acknowledged
                or not self.all_linked_action_semantics_reviewed
            ):
                raise ValueError("confirmation requires an exact complete review receipt")
        elif (
            any(item is not None for item in receipt_fields)
            or self.complete_review_acknowledged
            or self.all_requirements_and_candidates_acknowledged
            or self.all_linked_action_semantics_reviewed
        ):
            raise ValueError("rejection cannot carry a confirmation review receipt")
        return self


class RequirementActionDecisionRecord(StrictModel):
    decision_id: str
    proposal_id: str
    session_id: str
    decision: RequirementActionDecisionKind
    idempotency_key_digest: str
    command_fingerprint: str
    reviewed_descriptor_set_fingerprint: str | None = None
    decision_authority_fingerprint: str
    decided_at: datetime
    confirmation_authority: Literal["owned_native_user_presence"] = (
        "owned_native_user_presence"
    )
    schema_version: Literal[REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION] = (
        REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "decision_id",
        "proposal_id",
        "session_id",
        "idempotency_key_digest",
        "command_fingerprint",
        "decision_authority_fingerprint",
    )(_pseudonym)
    _decided = field_validator("decided_at")(_utc)

    @field_validator("reviewed_descriptor_set_fingerprint")
    @classmethod
    def optional_descriptor_fingerprint(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_review_fingerprint(self) -> "RequirementActionDecisionRecord":
        if (
            self.decision is RequirementActionDecisionKind.CONFIRM
        ) != (self.reviewed_descriptor_set_fingerprint is not None):
            raise ValueError(
                "confirmed decisions alone require a descriptor-set fingerprint"
            )
        return self


class RequirementActionProposalView(StrictModel):
    proposal: RequirementActionProposalRecord
    decision: RequirementActionDecisionRecord | None = None
    status: RequirementActionProposalStatus

    @model_validator(mode="after")
    def decision_status_agrees(self) -> "RequirementActionProposalView":
        expected = (
            RequirementActionProposalStatus.PROPOSED
            if self.decision is None
            else RequirementActionProposalStatus.CONFIRMED
            if self.decision.decision is RequirementActionDecisionKind.CONFIRM
            else RequirementActionProposalStatus.REJECTED
        )
        if self.status is not expected:
            raise ValueError("requirement-action proposal status is incoherent")
        return self


class RequirementActionReviewRequirement(StrictModel):
    requirement_id: str
    coordinate: RequirementCoordinate
    text: str = Field(
        min_length=1,
        max_length=MAX_REDACTED_MESSAGE_CHARACTERS,
        repr=False,
    )
    linked_action_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )

    _id = field_validator("requirement_id")(_pseudonym)
    _visible_text = field_validator("text")(_reject_forbidden_review_display)

    @field_validator("linked_action_ids")
    @classmethod
    def linked_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_pseudonym(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("review action identifiers must be unique and sorted")
        return checked


class RequirementActionReviewCandidate(StrictModel):
    """Candidate, proposed memberships, and process-only semantic descriptor."""

    candidate: RequirementActionCandidate
    descriptor_algorithm_version: Literal[
        ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
    ] = ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
    candidate_metadata_fingerprint_version: Literal[
        ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
    ]
    candidate_metadata_fingerprint: str
    tool_name: str = Field(
        repr=False,
        min_length=1,
        max_length=MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS,
    )
    invocation_preview: str = Field(
        repr=False,
        min_length=1,
        max_length=MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    )
    result_or_effect_preview: str | None = Field(
        default=None,
        repr=False,
        min_length=1,
        max_length=MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    )
    invocation_truncated: Literal[False] = False
    result_or_effect_truncated: Literal[False] = False
    redactor_version: str
    linked_requirement_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )

    _redactor = field_validator("redactor_version")(_safe_code)
    _metadata_fingerprint = field_validator("candidate_metadata_fingerprint")(
        _pseudonym
    )

    _visible_descriptors = field_validator(
        "tool_name",
        "invocation_preview",
        "result_or_effect_preview",
    )(_reject_forbidden_review_display)

    @model_validator(mode="after")
    def completed_candidate_has_effect(self) -> "RequirementActionReviewCandidate":
        if (
            self.candidate.event_kind is not EventKind.TOOL_START
            and self.result_or_effect_preview is None
        ):
            raise ValueError("completed review candidate requires an effect")
        return self

    @field_validator("linked_requirement_ids")
    @classmethod
    def linked_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_pseudonym(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("candidate memberships must be unique and sorted")
        return checked


class RequirementActionProposalReview(StrictModel):
    proposal_id: str
    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    review_receipt_id: str
    payload_sha256: str
    requirement_plan_evidence_fingerprint: str
    candidate_manifest_fingerprint: str
    reviewed_graph_fingerprint: str
    reviewed_candidate_set_fingerprint: str
    reviewed_descriptor_set_fingerprint: str
    review_visible_display_algorithm_version: Literal[
        REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    ] = REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    requirements: tuple[RequirementActionReviewRequirement, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    candidates: tuple[RequirementActionCandidate, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    candidate_memberships: tuple[RequirementActionReviewCandidate, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    review_context_expires_at: datetime
    review_receipt_expires_at: datetime
    all_requirements_and_candidates_displayed: Literal[True] = True
    raw_text_persisted: Literal[False] = False
    local_only: Literal[True] = True

    _ids = field_validator(
        "proposal_id",
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
        "review_receipt_id",
        "payload_sha256",
        "requirement_plan_evidence_fingerprint",
        "candidate_manifest_fingerprint",
        "reviewed_graph_fingerprint",
        "reviewed_candidate_set_fingerprint",
        "reviewed_descriptor_set_fingerprint",
    )(_pseudonym)
    _times = field_validator("review_context_expires_at", "review_receipt_expires_at")(
        _utc
    )

    @model_validator(mode="after")
    def exact_complete_review_surface(self) -> "RequirementActionProposalReview":
        if tuple(item.candidate for item in self.candidate_memberships) != self.candidates:
            raise ValueError("candidate memberships must cover the displayed set")
        return self


class RequirementActionProposalPageSnapshot(StrictModel):
    snapshot_id: str
    total: int = Field(ge=0, le=1_000_000)
    decision_count: int = Field(ge=0, le=1_000_000)
    high_water_created_at: datetime | None = None
    high_water_proposal_id: str | None = None

    _snapshot_id = field_validator("snapshot_id")(_pseudonym)

    @field_validator("high_water_created_at")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @field_validator("high_water_proposal_id")
    @classmethod
    def optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_boundary(self) -> "RequirementActionProposalPageSnapshot":
        if (self.high_water_created_at is None) != (self.high_water_proposal_id is None):
            raise ValueError("page snapshot boundary fields must be paired")
        if (self.high_water_created_at is not None) != (self.total > 0):
            raise ValueError("nonempty page snapshot requires its high-water boundary")
        if self.decision_count > self.total:
            raise ValueError("page snapshot has too many decisions")
        return self


class RequirementActionEvidenceSnapshot(StrictModel):
    session_id: str
    source_run_id: str | None = None
    source_window_fingerprint: str
    requirement_plan_confirmation_id: str | None = None
    requirement_plan_evidence_fingerprint: str | None = None
    confirmation_id: str | None = None
    proposal_id: str | None = None
    reviewed_descriptor_set_fingerprint: str | None = None
    producer_receipt: RequirementPlanProducerReceipt | None = None
    candidate_manifest: RequirementActionCandidateManifest | None = None
    requirements: tuple[RequirementActionRequirement, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    links: tuple[ConfirmedRequirementActionLink, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    complete_requirement_enumeration: bool = False
    complete_action_candidate_enumeration: bool = False
    complete_requirement_link_classification: bool = False
    evidence_fingerprint: str | None = None
    schema_version: Literal[REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION] = (
        REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION
    )
    policy_version: Literal[REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION] = (
        REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION
    )
    review_rubric_version: Literal[REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _session_window = field_validator("session_id", "source_window_fingerprint")(
        _pseudonym
    )

    @field_validator(
        "source_run_id",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "confirmation_id",
        "proposal_id",
        "reviewed_descriptor_set_fingerprint",
        "evidence_fingerprint",
    )
    @classmethod
    def optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_authority(self) -> "RequirementActionEvidenceSnapshot":
        complete = (
            self.complete_requirement_enumeration
            and self.complete_action_candidate_enumeration
            and self.complete_requirement_link_classification
        )
        authority_fields = (
            self.source_run_id,
            self.requirement_plan_confirmation_id,
            self.requirement_plan_evidence_fingerprint,
            self.confirmation_id,
            self.proposal_id,
            self.reviewed_descriptor_set_fingerprint,
            self.producer_receipt,
            self.candidate_manifest,
            self.evidence_fingerprint,
        )
        if complete != all(value is not None for value in authority_fields):
            raise ValueError("complete requirement-action evidence needs exact authority")
        if not complete:
            if (
                any(value is not None for value in authority_fields)
                or self.requirements
                or self.links
            ):
                raise ValueError("incomplete evidence cannot carry reviewed graph authority")
            return self
        assert self.candidate_manifest is not None
        if (
            self.candidate_manifest.session_id != self.session_id
            or self.candidate_manifest.source_run_id != self.source_run_id
            or self.candidate_manifest.source_window_fingerprint
            != self.source_window_fingerprint
            or not self.candidate_manifest.enumeration_complete
        ):
            raise ValueError("candidate manifest belongs to another authority")
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        if requirement_ids != tuple(sorted(set(requirement_ids))):
            raise ValueError("snapshot requirement identifiers must be sorted and unique")
        if tuple(item.requirement_id for item in self.links) != requirement_ids:
            raise ValueError("snapshot links must classify every requirement exactly once")
        action_ids = {item.action_id for item in self.candidate_manifest.actions}
        if any(action not in action_ids for item in self.links for action in item.action_ids):
            raise ValueError("snapshot link references an absent safe action")
        return self

    def authority_identity(self) -> tuple[str, ...]:
        return (
            self.schema_version,
            self.policy_version,
            self.review_rubric_version,
            self.confirmation_id or "none",
            self.proposal_id or "none",
            self.reviewed_descriptor_set_fingerprint or "none",
            self.requirement_plan_evidence_fingerprint or "none",
            (
                "none"
                if self.candidate_manifest is None
                else self.candidate_manifest.manifest_fingerprint
            ),
            self.evidence_fingerprint or "none",
        )


def requirement_action_evidence_snapshot_fingerprint(
    snapshot: RequirementActionEvidenceSnapshot,
    identifiers: "RequirementActionIdFactory",
) -> str:
    """Return the installation-keyed identity of one complete reviewed graph."""

    if (
        snapshot.confirmation_id is None
        or snapshot.proposal_id is None
        or snapshot.source_run_id is None
        or snapshot.requirement_plan_confirmation_id is None
        or snapshot.requirement_plan_evidence_fingerprint is None
        or snapshot.reviewed_descriptor_set_fingerprint is None
        or snapshot.producer_receipt is None
        or snapshot.candidate_manifest is None
        or not snapshot.complete_requirement_enumeration
        or not snapshot.complete_action_candidate_enumeration
        or not snapshot.complete_requirement_link_classification
    ):
        raise ValueError("complete reviewed requirement-action evidence is required")
    payload = {
        "schema_version": snapshot.schema_version,
        "policy_version": snapshot.policy_version,
        "review_rubric_version": snapshot.review_rubric_version,
        "session_id": snapshot.session_id,
        "source_run_id": snapshot.source_run_id,
        "source_window_fingerprint": snapshot.source_window_fingerprint,
        "requirement_plan_confirmation_id": (
            snapshot.requirement_plan_confirmation_id
        ),
        "requirement_plan_evidence_fingerprint": (
            snapshot.requirement_plan_evidence_fingerprint
        ),
        "confirmation_id": snapshot.confirmation_id,
        "proposal_id": snapshot.proposal_id,
        "reviewed_descriptor_set_fingerprint": (
            snapshot.reviewed_descriptor_set_fingerprint
        ),
        "producer_receipt": snapshot.producer_receipt.model_dump(mode="json"),
        "candidate_manifest_fingerprint": (
            snapshot.candidate_manifest.manifest_fingerprint
        ),
        "requirements": [
            item.model_dump(mode="json") for item in snapshot.requirements
        ],
        "links": [item.model_dump(mode="json") for item in snapshot.links],
    }
    canonical_digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    ).hexdigest()
    return identifiers.fingerprint(
        "requirement-action-evidence-snapshot-v1", (canonical_digest,)
    )


class RequirementActionEvidenceContract(StrictModel):
    schema_version: Literal[REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION] = (
        REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION
    )
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    source_projection_version: Literal[
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
    ]
    requirement_plan_confirmation_id: str
    requirement_plan_evidence_fingerprint: str
    candidate_manifest: RequirementActionCandidateManifest
    requirements: tuple[RequirementActionRequirement, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    expected_predecessor_confirmation_id: str | None = None
    metric_key: Literal[REQUIREMENT_ACTION_METRIC_KEY] = REQUIREMENT_ACTION_METRIC_KEY
    max_requirement_count: Literal[MAX_REQUIREMENT_ACTION_REQUIREMENTS] = (
        MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    max_candidate_count: Literal[MAX_REQUIREMENT_ACTION_CANDIDATES] = (
        MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    max_link_count: Literal[MAX_REQUIREMENT_ACTION_LINKS] = MAX_REQUIREMENT_ACTION_LINKS
    max_file_bytes: Literal[MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES] = (
        MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES
    )
    max_json_depth: Literal[MAX_REQUIREMENT_ACTION_EVIDENCE_DEPTH] = (
        MAX_REQUIREMENT_ACTION_EVIDENCE_DEPTH
    )
    max_json_items: Literal[MAX_REQUIREMENT_ACTION_EVIDENCE_ITEMS] = (
        MAX_REQUIREMENT_ACTION_EVIDENCE_ITEMS
    )
    max_lifetime_seconds: Literal[86_400] = 86_400
    canonicalization: Literal[REQUIREMENT_ACTION_CANONICALIZATION] = (
        REQUIREMENT_ACTION_CANONICALIZATION
    )
    import_creates_unconfirmed_proposal_only: Literal[True] = True
    native_confirmation_required_for_metric_authority: Literal[True] = True
    every_requirement_requires_one_link_classification: Literal[True] = True
    empty_action_links_are_explicit_reviewed_negative_links: Literal[True] = True
    action_states_are_application_issued: Literal[True] = True
    review_rubric_version: Literal[REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION
    )
    action_descriptor_algorithm_version: Literal[
        ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
    ] = ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
    candidate_metadata_fingerprint_version: Literal[
        ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
    ] = ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
    review_visible_display_algorithm_version: Literal[
        REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    ] = REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    review_visible_display_is_injective_one_pass: Literal[True] = True
    review_visible_display_never_truncates: Literal[True] = True
    native_review_displays_every_redacted_invocation_and_effect: Literal[True] = True
    all_linked_action_semantics_acknowledgement_required: Literal[True] = True
    action_descriptor_content_persisted: Literal[False] = False
    action_state_claims_allowed_in_file: Literal[False] = False
    objective_proof_claims_allowed_in_file: Literal[False] = False
    metric_values_allowed_in_file: Literal[False] = False
    raw_payload_persisted: Literal[False] = False
    raw_producer_claim_persisted: Literal[False] = False
    durable_producer_claim_shape: Literal[
        "installation_keyed_opaque_commitment_only"
    ] = "installation_keyed_opaque_commitment_only"
    import_confirmation: Literal[REQUIREMENT_ACTION_IMPORT_CONFIRMATION] = (
        REQUIREMENT_ACTION_IMPORT_CONFIRMATION
    )
    file_json_schema_sha256: str
    file_json_schema: dict[str, Any]

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "file_json_schema_sha256",
    )(_pseudonym)

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_source_binding(self) -> "RequirementActionEvidenceContract":
        if (
            self.candidate_manifest.session_id != self.session_id
            or self.candidate_manifest.source_run_id != self.expected_source_run_id
            or self.candidate_manifest.source_window_fingerprint
            != self.source_window_fingerprint
        ):
            raise ValueError("action candidate manifest belongs to another sealed run")
        indexes = tuple(item.requirement_index for item in self.requirements)
        if indexes != tuple(range(len(self.requirements))):
            raise ValueError("contract requirements must have dense indexes")
        return self


class RequirementActionSourceContract(StrictModel):
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    projection_version: Literal[
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
    ]
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot
    candidate_manifest: RequirementActionCandidateManifest

    _ids = field_validator(
        "session_id", "expected_source_run_id", "source_window_fingerprint"
    )(_pseudonym)

    @model_validator(mode="after")
    def exact_source(self) -> "RequirementActionSourceContract":
        if (
            self.requirement_plan_evidence.session_id != self.session_id
            or self.requirement_plan_evidence.source_window_fingerprint
            != self.source_window_fingerprint
            or self.candidate_manifest.session_id != self.session_id
            or self.candidate_manifest.source_run_id != self.expected_source_run_id
            or self.candidate_manifest.source_window_fingerprint
            != self.source_window_fingerprint
        ):
            raise ValueError("requirement-action source authorities disagree")
        return self


class RequirementActionSourceAuthority(Protocol):
    def current_source_contract(self, session_id: str) -> RequirementActionSourceContract: ...


class RequirementActionRepository(Protocol):
    def issue_proposal(
        self, proposal: RequirementActionProposalRecord
    ) -> tuple[RequirementActionProposalView, bool]: ...

    def decide(
        self, decision: RequirementActionDecisionRecord
    ) -> tuple[RequirementActionProposalView, bool]: ...

    def get_proposal(self, proposal_id: str) -> RequirementActionProposalView | None: ...

    def list_proposals_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementActionProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementActionProposalView, ...],
        RequirementActionProposalPageSnapshot,
    ]: ...

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementActionEvidenceSnapshot: ...

    def latest_snapshot(self, session_id: str) -> RequirementActionEvidenceSnapshot: ...


class RequirementActionIdFactory(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


def requirement_plan_snapshot_fingerprint(
    snapshot: RequirementPlanEvidenceSnapshot,
    identifiers: RequirementActionIdFactory,
) -> str:
    """Reproduce the frozen r6 authority identity used by the session writer."""

    if (
        not snapshot.complete_user_clause_classification
        or snapshot.confirmation_id is None
        or snapshot.proposal_id is None
    ):
        raise ValueError("only a complete confirmed requirement plan has an identity")
    canonical_digest = hashlib.sha256(
        json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    return identifiers.fingerprint(
        "requirement-plan-evidence-snapshot-v1",
        (canonical_digest,),
    )


class RequirementActionEvidenceError(RuntimeError):
    code = "requirement_action_evidence_failed"


class RequirementActionInputError(RequirementActionEvidenceError):
    code = "invalid_requirement_action_evidence"


class RequirementActionDefinitionsOutOfDateError(RequirementActionInputError):
    code = "requirement_action_evidence_definitions_out_of_date"


class RequirementActionNotFoundError(RequirementActionEvidenceError):
    code = "requirement_action_evidence_not_found"


class RequirementActionStaleWindowError(RequirementActionEvidenceError):
    code = "requirement_action_source_window_stale"


class RequirementActionConflictError(RequirementActionEvidenceError):
    code = "requirement_action_evidence_conflict"


class RequirementActionPersistenceError(RequirementActionEvidenceError):
    code = "requirement_action_evidence_persistence_failed"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_float(_value: str) -> float:
    raise ValueError("floating-point JSON values are not allowed")


def _validate_json_budget(value: object, *, depth: int = 0) -> int:
    if depth > MAX_REQUIREMENT_ACTION_EVIDENCE_DEPTH:
        raise ValueError("JSON nesting exceeds the bounded depth")
    count = 1
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            count += _validate_json_budget(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            count += _validate_json_budget(child, depth=depth + 1)
    if count > MAX_REQUIREMENT_ACTION_EVIDENCE_ITEMS:
        raise ValueError("JSON item count exceeds the bounded budget")
    return count


def requirement_action_evidence_file_json_schema() -> dict[str, Any]:
    schema = RequirementActionEvidenceFileV1.model_json_schema(mode="validation")
    properties = schema["properties"]
    for key in (
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "candidate_manifest_fingerprint",
        "nonce",
    ):
        properties[key]["pattern"] = PSEUDONYM_PATTERN.pattern
    properties["expected_predecessor_confirmation_id"]["anyOf"][0][
        "pattern"
    ] = PSEUDONYM_PATTERN.pattern
    link_entry = schema["$defs"]["RequirementActionLinkEntry"]
    link_entry["properties"]["action_candidate_indexes"]["uniqueItems"] = True
    schema["x-prompt-enhancer-canonicalization"] = REQUIREMENT_ACTION_CANONICALIZATION
    schema["x-prompt-enhancer-complete-graph-required"] = True
    schema["x-prompt-enhancer-empty-indexes-mean-reviewed-no-link"] = True
    return schema


def requirement_action_evidence_file_json_schema_sha256() -> str:
    return hashlib.sha256(
        json.dumps(
            requirement_action_evidence_file_json_schema(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def parse_requirement_action_evidence_file(
    payload: bytes,
    *,
    now: datetime | None = None,
) -> tuple[RequirementActionEvidenceFileV1, str]:
    """Parse one exact canonical, bounded, untrusted proposal file."""

    if not isinstance(payload, bytes) or not payload:
        raise RequirementActionInputError("requirement-action payload is empty")
    if len(payload) > MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES:
        raise RequirementActionInputError("requirement-action payload is too large")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise RequirementActionInputError("requirement-action payload must not use a BOM")
    try:
        text = payload.decode("utf-8", errors="strict")
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON values are not allowed")
            ),
        )
        _validate_json_budget(raw)
        if not isinstance(raw, dict):
            raise ValueError("file root must be an object")
        parsed = RequirementActionEvidenceFileV1.model_validate(raw)
        canonical = json.dumps(
            parsed.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    except (TypeError, UnicodeDecodeError, ValueError):
        raise RequirementActionInputError(
            "requirement-action payload is not valid canonical JSON"
        ) from None
    if not hmac.compare_digest(payload, canonical):
        raise RequirementActionInputError(
            "requirement-action payload is not canonical JSON"
        )
    checked_at = datetime.now(UTC) if now is None else now
    try:
        checked_at = _utc(checked_at)
    except (TypeError, ValueError):
        raise RequirementActionInputError(
            "requirement-action validation clock must be UTC"
        ) from None
    remaining = parsed.expires_at - checked_at
    if (
        parsed.created_at > checked_at
        or remaining <= timedelta(0)
        or remaining > MAX_REQUIREMENT_ACTION_EVIDENCE_LIFETIME
    ):
        raise RequirementActionInputError(
            "requirement-action expiry is outside policy"
        )
    return parsed, hashlib.sha256(payload).hexdigest()


@dataclass(slots=True)
class _RequirementActionReviewContextEntry:
    source_run_id: str
    context: P1TextAnalysisInput = field(repr=False)
    requirement_plan_evidence: RequirementPlanEvidenceSnapshot
    requirement_plan_evidence_fingerprint: str
    candidate_manifest: RequirementActionCandidateManifest
    action_descriptors: tuple[EphemeralRedactedActionDescriptor, ...] = field(
        repr=False
    )
    expires_at: datetime
    expires_monotonic: float


@dataclass(frozen=True, slots=True)
class _RequirementActionReviewReceiptEntry:
    proposal_id: str
    payload_sha256: str
    source_run_id: str
    source_window_fingerprint: str
    requirement_plan_evidence_fingerprint: str
    candidate_manifest_fingerprint: str
    reviewed_graph_fingerprint: str
    reviewed_candidate_set_fingerprint: str
    reviewed_descriptor_set_fingerprint: str
    expires_at: datetime
    expires_monotonic: float


class InMemoryRequirementActionReviewContextStore:
    """TTL-only source text and exact one-shot native review receipts."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic_clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] = lambda: token_hex(32),
        candidate_binding_key: bytes | None = None,
        max_active: int = MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_CONTEXTS,
        max_active_receipts: int = MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_RECEIPTS,
    ) -> None:
        if not 1 <= max_active <= MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_CONTEXTS:
            raise ValueError("review context capacity is outside its bound")
        if not 1 <= max_active_receipts <= MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_RECEIPTS:
            raise ValueError("review receipt capacity is outside its bound")
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._token_factory = token_factory
        self._candidate_binding_key = (
            token_bytes(32) if candidate_binding_key is None else candidate_binding_key
        )
        if (
            not isinstance(self._candidate_binding_key, bytes)
            or len(self._candidate_binding_key) != 32
        ):
            raise ValueError("review candidate binding key must contain 32 bytes")
        self._max_active = max_active
        self._max_active_receipts = max_active_receipts
        self._entries: OrderedDict[str, _RequirementActionReviewContextEntry] = (
            OrderedDict()
        )
        self._receipts: OrderedDict[
            str, _RequirementActionReviewReceiptEntry
        ] = OrderedDict()
        self._receipt_tombstones: OrderedDict[str, str] = OrderedDict()
        self._lock = Lock()

    def publish(
        self,
        source_run_id: str,
        context: P1TextAnalysisInput,
        requirement_plan_evidence: RequirementPlanEvidenceSnapshot,
        requirement_plan_evidence_fingerprint: str,
        candidate_manifest: RequirementActionCandidateManifest,
    ) -> None:
        _pseudonym(source_run_id)
        _pseudonym(requirement_plan_evidence_fingerprint)
        if (
            context.session_id != requirement_plan_evidence.session_id
            or context.session_id != candidate_manifest.session_id
            or context.analysis_window_fingerprint
            != requirement_plan_evidence.source_window_fingerprint
            or context.analysis_window_fingerprint
            != candidate_manifest.source_window_fingerprint
            or source_run_id != candidate_manifest.source_run_id
        ):
            raise ValueError("review authorities belong to different source windows")
        if (
            requirement_plan_evidence.confirmation_id is None
            or not requirement_plan_evidence.complete_user_clause_classification
        ):
            raise ValueError("confirmed r6 requirement evidence is required")
        self._validate_manifest(candidate_manifest)
        action_descriptors = self._validate_action_descriptors(
            context,
            candidate_manifest,
        )
        now = _utc(self._clock())
        monotonic_now = self._monotonic_clock()
        entry = _RequirementActionReviewContextEntry(
            source_run_id=source_run_id,
            context=context,
            requirement_plan_evidence=requirement_plan_evidence,
            requirement_plan_evidence_fingerprint=(
                requirement_plan_evidence_fingerprint
            ),
            candidate_manifest=candidate_manifest,
            action_descriptors=action_descriptors,
            expires_at=now + REQUIREMENT_ACTION_REVIEW_CONTEXT_TTL,
            expires_monotonic=(
                monotonic_now
                + REQUIREMENT_ACTION_REVIEW_CONTEXT_TTL.total_seconds()
            ),
        )
        with self._lock:
            self._expire_locked(now, monotonic_now)
            self._entries[source_run_id] = entry
            self._entries.move_to_end(source_run_id)
            while len(self._entries) > self._max_active:
                self._entries.popitem(last=False)

    def source_contract(
        self,
        session_id: str,
        source_run_id: str,
        projection_version: Literal[
            "metric-contract-v2-projection-6",
            "metric-contract-v2-projection-7",
            "metric-contract-v2-projection-8",
        ],
    ) -> RequirementActionSourceContract:
        contract, _fingerprint = self._source_contract_with_binding(
            session_id, source_run_id, projection_version
        )
        return contract

    def _source_contract_with_binding(
        self,
        session_id: str,
        source_run_id: str,
        projection_version: Literal[
            "metric-contract-v2-projection-6",
            "metric-contract-v2-projection-7",
            "metric-contract-v2-projection-8",
        ],
    ) -> tuple[RequirementActionSourceContract, str]:
        _pseudonym(session_id)
        _pseudonym(source_run_id)
        with self._lock:
            now = _utc(self._clock())
            monotonic_now = self._monotonic_clock()
            self._expire_locked(now, monotonic_now)
            entry = self._entries.get(source_run_id)
            if entry is None:
                raise RequirementActionNotFoundError(
                    "fresh ephemeral requirement-action review context is required"
                )
            if entry.context.session_id != session_id:
                raise RequirementActionConflictError(
                    "requirement-action context belongs to another session"
                )
            self._entries.move_to_end(source_run_id)
            contract = RequirementActionSourceContract(
                session_id=session_id,
                expected_source_run_id=source_run_id,
                source_window_fingerprint=(
                    entry.context.analysis_window_fingerprint
                ),
                projection_version=projection_version,
                requirement_plan_evidence=entry.requirement_plan_evidence,
                candidate_manifest=entry.candidate_manifest,
            )
            return contract, entry.requirement_plan_evidence_fingerprint

    def requirement_plan_binding_fingerprint(
        self, session_id: str, source_run_id: str
    ) -> str:
        _pseudonym(session_id)
        _pseudonym(source_run_id)
        with self._lock:
            now = _utc(self._clock())
            monotonic_now = self._monotonic_clock()
            self._expire_locked(now, monotonic_now)
            entry = self._entries.get(source_run_id)
            if entry is None:
                raise RequirementActionNotFoundError(
                    "fresh ephemeral requirement-action review context is required"
                )
            if entry.context.session_id != session_id:
                raise RequirementActionConflictError(
                    "requirement-action context belongs to another session"
                )
            return entry.requirement_plan_evidence_fingerprint

    def review(
        self, proposal: RequirementActionProposalView
    ) -> RequirementActionProposalReview:
        record = proposal.proposal
        entry = self._require(record)
        requirements, memberships = self._review_surface(record, entry)
        reviewed_graph_fingerprint = requirement_action_graph_fingerprint(record)
        reviewed_candidate_set_fingerprint = self._candidate_set_fingerprint(
            requirements, memberships
        )
        reviewed_descriptor_set_fingerprint = self._descriptor_set_fingerprint(
            memberships
        )
        now = _utc(self._clock())
        monotonic_now = self._monotonic_clock()
        receipt_expires_at = min(
            entry.expires_at, now + REQUIREMENT_ACTION_REVIEW_RECEIPT_TTL
        )
        review_receipt_id = self._token_factory()
        _pseudonym(review_receipt_id)
        receipt = _RequirementActionReviewReceiptEntry(
            proposal_id=record.proposal_id,
            payload_sha256=record.payload_sha256,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
            requirement_plan_evidence_fingerprint=(
                record.requirement_plan_evidence_fingerprint
            ),
            candidate_manifest_fingerprint=record.candidate_manifest_fingerprint,
            reviewed_graph_fingerprint=reviewed_graph_fingerprint,
            reviewed_candidate_set_fingerprint=(
                reviewed_candidate_set_fingerprint
            ),
            reviewed_descriptor_set_fingerprint=(
                reviewed_descriptor_set_fingerprint
            ),
            expires_at=receipt_expires_at,
            expires_monotonic=(
                monotonic_now
                + min(
                    REQUIREMENT_ACTION_REVIEW_RECEIPT_TTL.total_seconds(),
                    max(0.0, (entry.expires_at - now).total_seconds()),
                )
            ),
        )
        with self._lock:
            self._expire_locked(now, monotonic_now)
            if self._entries.get(record.source_run_id) is not entry:
                raise RequirementActionConflictError(
                    "requirement-action review context changed during review"
                )
            if (
                review_receipt_id in self._receipts
                or review_receipt_id in self._receipt_tombstones
            ):
                raise RequirementActionConflictError(
                    "requirement-action review receipt identity collided"
                )
            self._receipts[review_receipt_id] = receipt
            while len(self._receipts) > self._max_active_receipts:
                expired_id, _expired = self._receipts.popitem(last=False)
                self._tombstone_receipt_locked(expired_id, "expired")
        return RequirementActionProposalReview(
            proposal_id=record.proposal_id,
            session_id=record.session_id,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
            review_receipt_id=review_receipt_id,
            payload_sha256=record.payload_sha256,
            requirement_plan_evidence_fingerprint=(
                record.requirement_plan_evidence_fingerprint
            ),
            candidate_manifest_fingerprint=record.candidate_manifest_fingerprint,
            reviewed_graph_fingerprint=reviewed_graph_fingerprint,
            reviewed_candidate_set_fingerprint=(
                reviewed_candidate_set_fingerprint
            ),
            reviewed_descriptor_set_fingerprint=(
                reviewed_descriptor_set_fingerprint
            ),
            requirements=requirements,
            candidates=record.candidates,
            candidate_memberships=memberships,
            review_context_expires_at=entry.expires_at,
            review_receipt_expires_at=receipt_expires_at,
        )

    def consume_review_receipt(
        self,
        *,
        review_receipt_id: str,
        proposal: RequirementActionProposalView,
        reviewed_graph_fingerprint: str,
        candidate_manifest_fingerprint: str,
        reviewed_candidate_set_fingerprint: str,
        reviewed_descriptor_set_fingerprint: str,
    ) -> None:
        for value in (
            review_receipt_id,
            reviewed_graph_fingerprint,
            candidate_manifest_fingerprint,
            reviewed_candidate_set_fingerprint,
            reviewed_descriptor_set_fingerprint,
        ):
            _pseudonym(value)
        record = proposal.proposal
        now = _utc(self._clock())
        monotonic_now = self._monotonic_clock()
        with self._lock:
            self._expire_locked(now, monotonic_now)
            receipt = self._receipts.pop(review_receipt_id, None)
            self._tombstone_receipt_locked(review_receipt_id, "consumed")
            entry = self._entries.get(record.source_run_id)
            if receipt is None or entry is None:
                raise RequirementActionConflictError(
                    "requirement-action review receipt is unavailable"
                )
            requirements, memberships = self._review_surface(record, entry)
            exact_graph = requirement_action_graph_fingerprint(record)
            exact_candidate_set = self._candidate_set_fingerprint(
                requirements, memberships
            )
            exact_descriptor_set = self._descriptor_set_fingerprint(memberships)
            exact = (
                receipt.expires_at > now
                and receipt.expires_monotonic > monotonic_now
                and receipt.proposal_id == record.proposal_id
                and receipt.payload_sha256 == record.payload_sha256
                and receipt.source_run_id == record.source_run_id
                and receipt.source_window_fingerprint
                == record.source_window_fingerprint
                and receipt.requirement_plan_evidence_fingerprint
                == record.requirement_plan_evidence_fingerprint
                and receipt.candidate_manifest_fingerprint
                == record.candidate_manifest_fingerprint
                and receipt.candidate_manifest_fingerprint
                == candidate_manifest_fingerprint
                and receipt.reviewed_graph_fingerprint
                == reviewed_graph_fingerprint
                and receipt.reviewed_graph_fingerprint == exact_graph
                and receipt.reviewed_candidate_set_fingerprint
                == reviewed_candidate_set_fingerprint
                and receipt.reviewed_candidate_set_fingerprint
                == exact_candidate_set
                and receipt.reviewed_descriptor_set_fingerprint
                == reviewed_descriptor_set_fingerprint
                and receipt.reviewed_descriptor_set_fingerprint
                == exact_descriptor_set
            )
        if not exact:
            raise RequirementActionConflictError(
                "requirement-action review receipt binding changed"
            )

    def _require(
        self, record: RequirementActionProposalRecord
    ) -> _RequirementActionReviewContextEntry:
        with self._lock:
            now = _utc(self._clock())
            monotonic_now = self._monotonic_clock()
            self._expire_locked(now, monotonic_now)
            entry = self._entries.get(record.source_run_id)
            if entry is None:
                raise RequirementActionNotFoundError(
                    "fresh ephemeral requirement-action review context is required"
                )
            self._validate_record_against_entry(record, entry)
            self._entries.move_to_end(record.source_run_id)
            return entry

    @staticmethod
    def _validate_manifest(manifest: RequirementActionCandidateManifest) -> None:
        expected = requirement_action_candidate_manifest_fingerprint(manifest)
        if not hmac.compare_digest(expected, manifest.manifest_fingerprint):
            raise ValueError("action candidate manifest fingerprint is invalid")
        if (
            not manifest.extraction_complete
            or not manifest.enumeration_complete
            or not manifest.provenance.extraction_complete
        ):
            raise ValueError("complete action candidate authority is required")

    @staticmethod
    def _validate_action_descriptors(
        context: P1TextAnalysisInput,
        manifest: RequirementActionCandidateManifest,
    ) -> tuple[EphemeralRedactedActionDescriptor, ...]:
        descriptors = context.action_descriptors
        if (
            context.action_descriptor_algorithm_version
            != ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
            or not context.action_descriptor_extraction_complete
            or len(descriptors) != len(manifest.actions)
        ):
            raise ValueError("complete action review descriptors are required")
        by_source = {item.source_reference_id: item for item in descriptors}
        if len(by_source) != len(descriptors):
            raise ValueError("action review descriptors must be unique")
        ordered: list[EphemeralRedactedActionDescriptor] = []
        for candidate in manifest.actions:
            descriptor = by_source.get(candidate.source_reference_id)
            if (
                descriptor is None
                or not requirement_action_descriptor_matches_candidate_metadata(
                    candidate,
                    descriptor,
                )
                or descriptor.redactor_version != context.redactor_version
                or descriptor.invocation_truncated
                or descriptor.result_or_effect_truncated
            ):
                raise ValueError("action review descriptor authority is incomplete")
            ordered.append(descriptor)
        return tuple(ordered)

    @classmethod
    def _validate_record_against_entry(
        cls,
        record: RequirementActionProposalRecord,
        entry: _RequirementActionReviewContextEntry,
    ) -> None:
        cls._validate_manifest(entry.candidate_manifest)
        if cls._validate_action_descriptors(
            entry.context,
            entry.candidate_manifest,
        ) != entry.action_descriptors:
            raise RequirementActionConflictError(
                "requirement-action review descriptors changed"
            )
        expected_requirements = tuple(
            RequirementActionRequirement(
                requirement_index=index,
                requirement_id=item.requirement_id,
                coordinate=item.coordinate,
            )
            for index, item in enumerate(
                entry.requirement_plan_evidence.requirements
            )
        )
        if (
            entry.context.session_id != record.session_id
            or entry.context.analysis_window_fingerprint
            != record.source_window_fingerprint
            or entry.requirement_plan_evidence.confirmation_id
            != record.requirement_plan_confirmation_id
            or expected_requirements != record.requirements
            or entry.candidate_manifest.manifest_fingerprint
            != record.candidate_manifest_fingerprint
            or entry.candidate_manifest.actions != record.candidates
            or entry.candidate_manifest.provenance != record.candidate_provenance
            or entry.candidate_manifest.extraction_complete
            != record.candidate_extraction_complete
            or entry.candidate_manifest.enumeration_complete
            != record.candidate_enumeration_complete
        ):
            raise RequirementActionConflictError(
                "requirement-action review source authority changed"
            )

    @classmethod
    def _review_surface(
        cls,
        record: RequirementActionProposalRecord,
        entry: _RequirementActionReviewContextEntry,
    ) -> tuple[
        tuple[RequirementActionReviewRequirement, ...],
        tuple[RequirementActionReviewCandidate, ...],
    ]:
        cls._validate_record_against_entry(record, entry)
        messages = {item.sequence: item for item in entry.context.messages}
        links = {item.requirement_id: item.action_ids for item in record.links}
        requirements: list[RequirementActionReviewRequirement] = []
        for requirement in record.requirements:
            message = messages.get(requirement.coordinate.message_sequence)
            if (
                message is None
                or message.role is not TextRole.USER
                or message.kind
                not in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
            ):
                raise RequirementActionConflictError(
                    "review requirement coordinate is unavailable"
                )
            try:
                clauses = reviewable_message_clauses(
                    message.text.get_secret_value()
                )
                text = clauses[requirement.coordinate.clause_index]
            except (IndexError, ValueError):
                raise RequirementActionConflictError(
                    "review requirement coordinate changed"
                ) from None
            requirements.append(
                RequirementActionReviewRequirement(
                    requirement_id=requirement.requirement_id,
                    coordinate=requirement.coordinate,
                    text=_visible_review_display(
                        text,
                        max_length=MAX_REDACTED_MESSAGE_CHARACTERS,
                    ),
                    linked_action_ids=links[requirement.requirement_id],
                )
            )
        action_memberships: dict[str, list[str]] = {
            item.action_id: [] for item in record.candidates
        }
        for link in record.links:
            for action_id in link.action_ids:
                action_memberships[action_id].append(link.requirement_id)
        memberships = tuple(
            RequirementActionReviewCandidate(
                candidate=candidate,
                candidate_metadata_fingerprint_version=(
                    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                ),
                candidate_metadata_fingerprint=(
                    descriptor.candidate_metadata_fingerprint
                ),
                tool_name=_visible_review_display(
                    descriptor.tool_name.get_secret_value(),
                    max_length=MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS,
                ),
                invocation_preview=_visible_review_display(
                    descriptor.invocation_preview.get_secret_value(),
                    max_length=MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
                ),
                result_or_effect_preview=(
                    None
                    if descriptor.result_or_effect_preview is None
                    else _visible_review_display(
                        descriptor.result_or_effect_preview.get_secret_value(),
                        max_length=MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
                    )
                ),
                redactor_version=descriptor.redactor_version,
                linked_requirement_ids=tuple(
                    sorted(action_memberships[candidate.action_id])
                ),
            )
            for candidate, descriptor in zip(
                record.candidates,
                entry.action_descriptors,
                strict=True,
            )
        )
        return tuple(requirements), memberships

    def _candidate_set_fingerprint(
        self,
        requirements: tuple[RequirementActionReviewRequirement, ...],
        memberships: tuple[RequirementActionReviewCandidate, ...],
    ) -> str:
        payload = json.dumps(
            {
                "review_visible_display_algorithm_version": (
                    REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
                ),
                "requirements": [item.model_dump(mode="json") for item in requirements],
                "candidate_memberships": [
                    item.model_dump(mode="json") for item in memberships
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hmac.new(
            self._candidate_binding_key,
            b"prompt-enhancer/requirement-action-review-set/v3\0" + payload,
            hashlib.sha256,
        ).hexdigest()

    def _descriptor_set_fingerprint(
        self,
        memberships: tuple[RequirementActionReviewCandidate, ...],
    ) -> str:
        payload = json.dumps(
            {
                "descriptor_algorithm_version": (
                    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
                ),
                "review_visible_display_algorithm_version": (
                    REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
                ),
                "descriptors": [
                    {
                        "action_id": item.candidate.action_id,
                        "source_reference_id": item.candidate.source_reference_id,
                        "event_kind": item.candidate.event_kind.value,
                        "candidate_metadata_fingerprint_version": (
                            item.candidate_metadata_fingerprint_version
                        ),
                        "candidate_metadata_fingerprint": (
                            item.candidate_metadata_fingerprint
                        ),
                        "tool_name": item.tool_name,
                        "invocation_preview": item.invocation_preview,
                        "result_or_effect_preview": item.result_or_effect_preview,
                        "invocation_truncated": item.invocation_truncated,
                        "result_or_effect_truncated": (
                            item.result_or_effect_truncated
                        ),
                        "redactor_version": item.redactor_version,
                    }
                    for item in memberships
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hmac.new(
            self._candidate_binding_key,
            b"prompt-enhancer/requirement-action-descriptor-set/v2\0" + payload,
            hashlib.sha256,
        ).hexdigest()

    def _expire_locked(self, now: datetime, monotonic_now: float) -> None:
        expired_contexts = tuple(
            key
            for key, entry in self._entries.items()
            if now >= entry.expires_at or monotonic_now >= entry.expires_monotonic
        )
        for key in expired_contexts:
            del self._entries[key]
        expired_receipts = tuple(
            key
            for key, entry in self._receipts.items()
            if now >= entry.expires_at or monotonic_now >= entry.expires_monotonic
        )
        for key in expired_receipts:
            del self._receipts[key]
            self._tombstone_receipt_locked(key, "expired")

    def _tombstone_receipt_locked(self, receipt_id: str, state: str) -> None:
        self._receipt_tombstones[receipt_id] = state
        self._receipt_tombstones.move_to_end(receipt_id)
        while len(self._receipt_tombstones) > 64:
            self._receipt_tombstones.popitem(last=False)


class RequirementActionSealedRunRepository(Protocol):
    def get_latest(self, session_id: str): ...


class SealedRunRequirementActionSource:
    """Cross-check a live review context against the latest sealed r6-r8 run."""

    def __init__(
        self,
        repository: RequirementActionSealedRunRepository,
        review_contexts: InMemoryRequirementActionReviewContextStore,
    ) -> None:
        self._repository = repository
        self._review_contexts = review_contexts

    def current_source_contract(
        self, session_id: str
    ) -> RequirementActionSourceContract:
        try:
            _pseudonym(session_id)
            latest = self._repository.get_latest(session_id)
        except RequirementActionEvidenceError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "sealed requirement-action source could not be read"
            ) from None
        if latest is None or latest.receipt.metric_publication_v2 is None:
            raise RequirementActionNotFoundError(
                "a sealed r6, r7, or r8 metric publication is required"
            )
        publication = latest.receipt.metric_publication_v2
        if publication.projection_version not in {
            "metric-contract-v2-projection-6",
            "metric-contract-v2-projection-7",
            "metric-contract-v2-projection-8",
        }:
            raise RequirementActionDefinitionsOutOfDateError(
                "latest sealed publication cannot source requirement actions"
            )
        binding = latest.requirement_plan_evidence_binding
        if (
            binding is None
            or getattr(binding.evidence_source, "value", None)
            != "reviewed_requirement_plan"
            or binding.confirmation_id is None
            or binding.proposal_id is None
        ):
            raise RequirementActionNotFoundError(
                "reviewed r6 requirement authority is required"
            )
        source, stored_fingerprint = (
            self._review_contexts._source_contract_with_binding(
            session_id,
            latest.run_id,
            publication.projection_version,
            )
        )
        snapshot = source.requirement_plan_evidence
        if (
            latest.session_id != session_id
            or latest.input_fingerprint != source.source_window_fingerprint
            or binding.session_id != session_id
            or binding.source_window_fingerprint
            != source.source_window_fingerprint
            or binding.confirmation_id != snapshot.confirmation_id
            or binding.proposal_id != snapshot.proposal_id
            or binding.evidence_fingerprint != stored_fingerprint
            or binding.evidence_schema_version != snapshot.schema_version
            or binding.evidence_policy_version != snapshot.policy_version
        ):
            raise RequirementActionConflictError(
                "sealed run and live requirement-action authority disagree"
            )
        return source


class RequirementActionEvidenceService:
    """Import inert link proposals and issue reviewed native authority."""

    def __init__(
        self,
        repository: RequirementActionRepository,
        source_authority: RequirementActionSourceAuthority,
        identifiers: RequirementActionIdFactory,
        *,
        review_contexts: InMemoryRequirementActionReviewContextStore | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._source_authority = source_authority
        self._identifiers = identifiers
        self._review_contexts = review_contexts
        self._clock = clock

    def contract(self, session_id: str) -> RequirementActionEvidenceContract:
        source = self._current_source(session_id)
        current = self._snapshot(session_id, source.source_window_fingerprint)
        requirement_fingerprint = requirement_plan_snapshot_fingerprint(
            source.requirement_plan_evidence, self._identifiers
        )
        return RequirementActionEvidenceContract(
            session_id=session_id,
            expected_source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            source_projection_version=source.projection_version,
            requirement_plan_confirmation_id=(
                source.requirement_plan_evidence.confirmation_id
            ),
            requirement_plan_evidence_fingerprint=requirement_fingerprint,
            candidate_manifest=source.candidate_manifest,
            requirements=self._source_requirements(source),
            expected_predecessor_confirmation_id=current.confirmation_id,
            file_json_schema_sha256=(
                requirement_action_evidence_file_json_schema_sha256()
            ),
            file_json_schema=requirement_action_evidence_file_json_schema(),
        )

    def preview(
        self,
        *,
        session_id: str,
        payload: bytes,
        now: datetime | None = None,
    ) -> RequirementActionEvidencePreview:
        parsed, digest = parse_requirement_action_evidence_file(payload, now=now)
        source = self._current_source(session_id)
        self._bind_file(parsed, source)
        current = self._snapshot(session_id, source.source_window_fingerprint)
        if parsed.expected_predecessor_confirmation_id != current.confirmation_id:
            raise RequirementActionConflictError(
                "requirement-action predecessor changed"
            )
        return RequirementActionEvidencePreview(
            payload_sha256=digest,
            session_id=session_id,
            expected_source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            requirement_plan_confirmation_id=(
                parsed.requirement_plan_confirmation_id
            ),
            requirement_plan_evidence_fingerprint=(
                parsed.requirement_plan_evidence_fingerprint
            ),
            candidate_manifest_fingerprint=(
                parsed.candidate_manifest_fingerprint
            ),
            expected_predecessor_confirmation_id=(
                parsed.expected_predecessor_confirmation_id
            ),
            requirement_count=len(parsed.links),
            candidate_count=len(source.candidate_manifest.actions),
            linked_requirement_count=sum(
                bool(item.action_candidate_indexes) for item in parsed.links
            ),
            unlinked_requirement_count=sum(
                not item.action_candidate_indexes for item in parsed.links
            ),
            link_count=sum(
                len(item.action_candidate_indexes) for item in parsed.links
            ),
            expires_at=parsed.expires_at,
            producer=parsed.producer,
        )

    def import_file(
        self,
        *,
        session_id: str,
        payload: bytes,
        expected_payload_sha256: str,
        confirmation: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> tuple[RequirementActionProposalView, bool]:
        if confirmation != REQUIREMENT_ACTION_IMPORT_CONFIRMATION:
            raise RequirementActionInputError(
                "requirement-action import confirmation is invalid"
            )
        parsed, digest = parse_requirement_action_evidence_file(payload, now=now)
        if (
            PSEUDONYM_PATTERN.fullmatch(expected_payload_sha256) is None
            or not hmac.compare_digest(digest, expected_payload_sha256)
        ):
            raise RequirementActionInputError(
                "requirement-action preview binding changed"
            )
        source = self._current_source(session_id)
        self._bind_file(parsed, source)
        current = self._snapshot(session_id, source.source_window_fingerprint)
        if parsed.expected_predecessor_confirmation_id != current.confirmation_id:
            raise RequirementActionConflictError(
                "requirement-action predecessor changed"
            )
        self._validate_idempotency(session_id, idempotency_key)
        idempotency_digest = self._identifiers.fingerprint(
            "requirement-action-proposal-idempotency-v1",
            (session_id, idempotency_key),
        )
        proposal_id = self._identifiers.fingerprint(
            "requirement-action-proposal-v1", (session_id, idempotency_digest)
        )
        command_fingerprint = self._identifiers.fingerprint(
            "requirement-action-proposal-command-v1",
            (
                session_id,
                source.expected_source_run_id,
                source.source_window_fingerprint,
                parsed.requirement_plan_confirmation_id,
                parsed.requirement_plan_evidence_fingerprint,
                parsed.candidate_manifest_fingerprint,
                parsed.expected_predecessor_confirmation_id or "none",
                digest,
            ),
        )
        requirements = self._source_requirements(source)
        candidates = source.candidate_manifest.actions
        links = tuple(
            ConfirmedRequirementActionLink(
                requirement_id=requirements[item.requirement_index].requirement_id,
                action_ids=tuple(
                    sorted(
                        candidates[index].action_id
                        for index in item.action_candidate_indexes
                    )
                ),
            )
            for item in parsed.links
        )
        record = RequirementActionProposalRecord(
            proposal_id=proposal_id,
            session_id=session_id,
            source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            requirement_plan_confirmation_id=(
                parsed.requirement_plan_confirmation_id
            ),
            requirement_plan_evidence_fingerprint=(
                parsed.requirement_plan_evidence_fingerprint
            ),
            candidate_manifest_fingerprint=(
                source.candidate_manifest.manifest_fingerprint
            ),
            candidate_provenance=source.candidate_manifest.provenance,
            candidate_extraction_complete=(
                source.candidate_manifest.extraction_complete
            ),
            candidate_enumeration_complete=(
                source.candidate_manifest.enumeration_complete
            ),
            expected_predecessor_confirmation_id=(
                parsed.expected_predecessor_confirmation_id
            ),
            payload_sha256=digest,
            idempotency_key_digest=idempotency_digest,
            command_fingerprint=command_fingerprint,
            producer_receipt=RequirementPlanProducerReceipt(
                claim_fingerprint=self._identifiers.fingerprint(
                    "requirement-action-producer-claim-v1",
                    (
                        parsed.producer.kind,
                        parsed.producer.producer_id,
                        parsed.producer.producer_version,
                        parsed.producer.model_id,
                        parsed.producer.authority,
                    ),
                )
            ),
            requirements=requirements,
            candidates=candidates,
            links=links,
            created_at=_utc(self._clock()),
        )
        try:
            return self._repository.issue_proposal(record)
        except RequirementActionConflictError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action proposal could not be stored"
            ) from None

    def review_proposal(
        self,
        *,
        session_id: str,
        proposal_id: str,
        expected_source_run_id: str,
    ) -> RequirementActionProposalReview:
        if self._review_contexts is None:
            raise RequirementActionPersistenceError(
                "ephemeral requirement-action review is unavailable"
            )
        proposal = self._get_owned_proposal(session_id, proposal_id)
        if proposal.proposal.source_run_id != expected_source_run_id:
            raise RequirementActionConflictError(
                "requirement-action review source changed"
            )
        if proposal.status is not RequirementActionProposalStatus.PROPOSED:
            raise RequirementActionConflictError(
                "only an undecided requirement-action proposal can be reviewed"
            )
        source = self._current_source(session_id)
        self._assert_proposal_source(proposal.proposal, source)
        return self._review_contexts.review(proposal)

    def decide(
        self,
        *,
        session_id: str,
        proposal_id: str,
        command: RequirementActionDecisionCommand,
        idempotency_key: str,
    ) -> tuple[RequirementActionProposalView, bool]:
        self._validate_idempotency(session_id, idempotency_key)
        proposal = self._get_owned_proposal(session_id, proposal_id)
        if command.expected_source_run_id != proposal.proposal.source_run_id:
            raise RequirementActionConflictError(
                "requirement-action proposal authority changed"
            )
        idempotency_digest = self._identifiers.fingerprint(
            "requirement-action-decision-idempotency-v1",
            (session_id, idempotency_key),
        )
        command_fingerprint = self._identifiers.fingerprint(
            "requirement-action-decision-command-v1",
            (
                proposal_id,
                command.expected_source_run_id,
                command.decision.value,
                command.confirmation,
                command.review_receipt_id or "none",
                command.reviewed_graph_fingerprint or "none",
                command.candidate_manifest_fingerprint or "none",
                command.reviewed_candidate_set_fingerprint or "none",
                command.reviewed_descriptor_set_fingerprint or "none",
                "complete" if command.complete_review_acknowledged else "incomplete",
                (
                    "all-items"
                    if command.all_requirements_and_candidates_acknowledged
                    else "not-all-items"
                ),
                (
                    "semantic-links-reviewed"
                    if command.all_linked_action_semantics_reviewed
                    else "semantic-links-not-reviewed"
                ),
            ),
        )
        decision_id = self._identifiers.fingerprint(
            "requirement-action-decision-v1", (proposal_id, idempotency_digest)
        )
        if proposal.decision is not None:
            existing = proposal.decision
            if (
                existing.decision_id == decision_id
                and existing.idempotency_key_digest == idempotency_digest
                and existing.command_fingerprint == command_fingerprint
                and existing.decision is command.decision
            ):
                return proposal, False
            raise RequirementActionConflictError(
                "requirement-action proposal already has another decision"
            )
        if command.decision is RequirementActionDecisionKind.CONFIRM:
            source = self._current_source(session_id)
            self._assert_proposal_source(proposal.proposal, source)
            if self._review_contexts is None:
                raise RequirementActionPersistenceError(
                    "ephemeral requirement-action review is unavailable"
                )
            assert command.review_receipt_id is not None
            assert command.reviewed_graph_fingerprint is not None
            assert command.candidate_manifest_fingerprint is not None
            assert command.reviewed_candidate_set_fingerprint is not None
            assert command.reviewed_descriptor_set_fingerprint is not None
            self._review_contexts.consume_review_receipt(
                review_receipt_id=command.review_receipt_id,
                proposal=proposal,
                reviewed_graph_fingerprint=command.reviewed_graph_fingerprint,
                candidate_manifest_fingerprint=(
                    command.candidate_manifest_fingerprint
                ),
                reviewed_candidate_set_fingerprint=(
                    command.reviewed_candidate_set_fingerprint
                ),
                reviewed_descriptor_set_fingerprint=(
                    command.reviewed_descriptor_set_fingerprint
                ),
            )
            current = self._snapshot(session_id, source.source_window_fingerprint)
            if (
                current.confirmation_id
                != proposal.proposal.expected_predecessor_confirmation_id
            ):
                raise RequirementActionConflictError(
                    "requirement-action predecessor changed"
                )
        decision_authority_fingerprint = (
            requirement_action_decision_authority_fingerprint(
                self._identifiers,
                proposal=proposal.proposal,
                decision_id=decision_id,
                decision=command.decision,
                idempotency_key_digest=idempotency_digest,
                command_fingerprint=command_fingerprint,
                reviewed_descriptor_set_fingerprint=(
                    command.reviewed_descriptor_set_fingerprint
                ),
            )
        )
        record = RequirementActionDecisionRecord(
            decision_id=decision_id,
            proposal_id=proposal_id,
            session_id=session_id,
            decision=command.decision,
            idempotency_key_digest=idempotency_digest,
            command_fingerprint=command_fingerprint,
            reviewed_descriptor_set_fingerprint=(
                command.reviewed_descriptor_set_fingerprint
            ),
            decision_authority_fingerprint=decision_authority_fingerprint,
            decided_at=_utc(self._clock()),
        )
        try:
            result = self._repository.decide(record)
            if command.decision is RequirementActionDecisionKind.CONFIRM:
                self._snapshot(session_id, source.source_window_fingerprint)
            return result
        except RequirementActionConflictError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action decision could not be stored"
            ) from None

    def list_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementActionProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementActionProposalView, ...],
        RequirementActionProposalPageSnapshot,
    ]:
        try:
            _pseudonym(session_id)
        except (TypeError, ValueError):
            raise RequirementActionInputError(
                "session identifier is invalid"
            ) from None
        if not 1 <= limit <= MAX_REQUIREMENT_ACTION_PAGE_SIZE or not 0 <= offset <= 1_000_000:
            raise RequirementActionInputError("requirement-action page is invalid")
        if snapshot is None and offset != 0:
            raise RequirementActionInputError(
                "a stable requirement-action page snapshot is required"
            )
        if snapshot is not None and offset > snapshot.total:
            raise RequirementActionConflictError(
                "requirement-action page offset exceeds its snapshot"
            )
        try:
            if snapshot is not None:
                expected_snapshot_id = self._proposal_page_snapshot_id(
                    session_id, snapshot
                )
                if not hmac.compare_digest(
                    snapshot.snapshot_id, expected_snapshot_id
                ):
                    raise RequirementActionConflictError(
                        "requirement-action page snapshot is invalid"
                    )
            proposals, resolved_snapshot = self._repository.list_proposals_page(
                session_id,
                limit=limit,
                offset=offset,
                snapshot=snapshot,
            )
            signed_snapshot = resolved_snapshot.model_copy(
                update={
                    "snapshot_id": self._proposal_page_snapshot_id(
                        session_id, resolved_snapshot
                    )
                }
            )
            return proposals, signed_snapshot
        except RequirementActionConflictError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action proposals could not be read"
            ) from None

    def snapshot_for_window(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementActionEvidenceSnapshot:
        try:
            _pseudonym(session_id)
            _pseudonym(source_window_fingerprint)
        except (TypeError, ValueError):
            raise RequirementActionInputError(
                "requirement-action window is invalid"
            ) from None
        return self._snapshot(session_id, source_window_fingerprint)

    def latest_snapshot(self, session_id: str) -> RequirementActionEvidenceSnapshot:
        try:
            _pseudonym(session_id)
            snapshot = self._repository.latest_snapshot(session_id)
            self._validate_snapshot_fingerprint(snapshot)
            return snapshot
        except RequirementActionEvidenceError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action snapshot could not be read"
            ) from None

    def _current_source(self, session_id: str) -> RequirementActionSourceContract:
        try:
            _pseudonym(session_id)
            source = self._source_authority.current_source_contract(session_id)
        except RequirementActionEvidenceError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action source authority could not be read"
            ) from None
        if source.session_id != session_id:
            raise RequirementActionPersistenceError(
                "requirement-action source belongs elsewhere"
            )
        try:
            requirement_plan_snapshot_fingerprint(
                source.requirement_plan_evidence, self._identifiers
            )
            expected_manifest = requirement_action_candidate_manifest_fingerprint(
                source.candidate_manifest
            )
        except ValueError:
            raise RequirementActionDefinitionsOutOfDateError(
                "requirement-action source authority is invalid"
            ) from None
        if (
            not hmac.compare_digest(
                expected_manifest, source.candidate_manifest.manifest_fingerprint
            )
            or not source.candidate_manifest.extraction_complete
            or not source.candidate_manifest.enumeration_complete
            or not source.candidate_manifest.provenance.extraction_complete
        ):
            raise RequirementActionDefinitionsOutOfDateError(
                "complete provider action enumeration is required"
            )
        self._source_requirements(source)
        return source

    @staticmethod
    def _source_requirements(
        source: RequirementActionSourceContract,
    ) -> tuple[RequirementActionRequirement, ...]:
        snapshot = source.requirement_plan_evidence
        if (
            snapshot.confirmation_id is None
            or not snapshot.complete_user_clause_classification
        ):
            raise RequirementActionDefinitionsOutOfDateError(
                "confirmed r6 active requirements are required"
            )
        if len(snapshot.requirements) > MAX_REQUIREMENT_ACTION_REQUIREMENTS:
            raise RequirementActionDefinitionsOutOfDateError(
                "active requirement set exceeds its bounded review surface"
            )
        return tuple(
            RequirementActionRequirement(
                requirement_index=index,
                requirement_id=item.requirement_id,
                coordinate=item.coordinate,
            )
            for index, item in enumerate(snapshot.requirements)
        )

    def _bind_file(
        self,
        parsed: RequirementActionEvidenceFileV1,
        source: RequirementActionSourceContract,
    ) -> None:
        requirement_fingerprint = requirement_plan_snapshot_fingerprint(
            source.requirement_plan_evidence, self._identifiers
        )
        manifest = source.candidate_manifest
        if (
            parsed.session_id != source.session_id
            or parsed.expected_source_run_id != source.expected_source_run_id
            or parsed.source_window_fingerprint
            != source.source_window_fingerprint
            or parsed.requirement_plan_confirmation_id
            != source.requirement_plan_evidence.confirmation_id
            or parsed.requirement_plan_evidence_fingerprint
            != requirement_fingerprint
            or parsed.candidate_manifest_fingerprint
            != manifest.manifest_fingerprint
        ):
            raise RequirementActionStaleWindowError(
                "requirement-action file is bound to another source"
            )
        requirements = self._source_requirements(source)
        if len(parsed.links) != len(requirements):
            raise RequirementActionInputError(
                "every active requirement must be classified exactly once"
            )
        if any(
            action_index >= len(manifest.actions)
            for link in parsed.links
            for action_index in link.action_candidate_indexes
        ):
            raise RequirementActionInputError(
                "requirement-action link references an absent candidate"
            )

    def _get_owned_proposal(
        self, session_id: str, proposal_id: str
    ) -> RequirementActionProposalView:
        try:
            _pseudonym(session_id)
            _pseudonym(proposal_id)
            proposal = self._repository.get_proposal(proposal_id)
        except RequirementActionEvidenceError:
            raise
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action proposal could not be read"
            ) from None
        if proposal is None or proposal.proposal.session_id != session_id:
            raise RequirementActionNotFoundError(
                "requirement-action proposal does not exist"
            )
        return proposal

    def _assert_proposal_source(
        self,
        proposal: RequirementActionProposalRecord,
        source: RequirementActionSourceContract,
    ) -> None:
        requirement_fingerprint = requirement_plan_snapshot_fingerprint(
            source.requirement_plan_evidence, self._identifiers
        )
        manifest = source.candidate_manifest
        if (
            proposal.source_run_id != source.expected_source_run_id
            or proposal.source_window_fingerprint
            != source.source_window_fingerprint
            or proposal.requirement_plan_confirmation_id
            != source.requirement_plan_evidence.confirmation_id
            or proposal.requirement_plan_evidence_fingerprint
            != requirement_fingerprint
            or proposal.candidate_manifest_fingerprint
            != manifest.manifest_fingerprint
            or proposal.candidate_provenance != manifest.provenance
            or proposal.candidate_extraction_complete != manifest.extraction_complete
            or proposal.candidate_enumeration_complete
            != manifest.enumeration_complete
            or proposal.requirements
            != self._source_requirements(source)
            or proposal.candidates != manifest.actions
        ):
            raise RequirementActionStaleWindowError(
                "requirement-action proposal authority changed"
            )

    def _snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementActionEvidenceSnapshot:
        try:
            snapshot = self._repository.snapshot(
                session_id, source_window_fingerprint
            )
            self._validate_snapshot_fingerprint(snapshot)
            return snapshot
        except Exception:
            raise RequirementActionPersistenceError(
                "requirement-action snapshot could not be read"
            ) from None

    def _validate_snapshot_fingerprint(
        self, snapshot: RequirementActionEvidenceSnapshot
    ) -> None:
        if snapshot.confirmation_id is None:
            return
        try:
            expected = requirement_action_evidence_snapshot_fingerprint(
                snapshot, self._identifiers
            )
        except ValueError:
            raise RequirementActionPersistenceError(
                "requirement-action snapshot authority is incomplete"
            ) from None
        assert snapshot.evidence_fingerprint is not None
        if not hmac.compare_digest(expected, snapshot.evidence_fingerprint):
            raise RequirementActionPersistenceError(
                "requirement-action snapshot fingerprint is invalid"
            )

    def _proposal_page_snapshot_id(
        self,
        session_id: str,
        snapshot: RequirementActionProposalPageSnapshot,
    ) -> str:
        return self._identifiers.fingerprint(
            "requirement-action-proposal-page-snapshot-v1",
            (
                session_id,
                str(snapshot.total),
                str(snapshot.decision_count),
                (
                    "none"
                    if snapshot.high_water_created_at is None
                    else snapshot.high_water_created_at.isoformat()
                ),
                snapshot.high_water_proposal_id or "none",
            ),
        )

    @staticmethod
    def _validate_idempotency(session_id: str, key: str) -> None:
        try:
            _pseudonym(session_id)
            valid = (
                isinstance(key, str)
                and len(key) >= 16
                and SAFE_VERSION_PATTERN.fullmatch(key) is not None
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise RequirementActionInputError(
                "idempotency key must be a content-free identifier"
            )


__all__ = [
    "ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION",
    "ConfirmedRequirementActionLink",
    "InMemoryRequirementActionReviewContextStore",
    "MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_CONTEXTS",
    "MAX_ACTIVE_REQUIREMENT_ACTION_REVIEW_RECEIPTS",
    "MAX_REQUIREMENT_ACTION_CANDIDATES",
    "MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES",
    "MAX_REQUIREMENT_ACTION_LINKS",
    "MAX_REQUIREMENT_ACTION_PAGE_SIZE",
    "MAX_REQUIREMENT_ACTION_REQUIREMENTS",
    "REQUIREMENT_ACTION_CANDIDATE_MANIFEST_VERSION",
    "REQUIREMENT_ACTION_DECISION_CONFIRMATION",
    "REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION",
    "REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION",
    "REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION",
    "REQUIREMENT_ACTION_IMPORT_CONFIRMATION",
    "REQUIREMENT_ACTION_METRIC_KEY",
    "REQUIREMENT_ACTION_REVIEW_CONFIRMATION",
    "REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION",
    "REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION",
    "RequirementActionCandidate",
    "RequirementActionCandidateState",
    "RequirementActionCandidateManifest",
    "RequirementActionConflictError",
    "RequirementActionDecisionCommand",
    "RequirementActionDecisionKind",
    "RequirementActionDecisionRecord",
    "RequirementActionDefinitionsOutOfDateError",
    "RequirementActionEvidenceContract",
    "RequirementActionEvidenceError",
    "RequirementActionEvidenceFileV1",
    "RequirementActionEvidencePreview",
    "RequirementActionEvidenceService",
    "RequirementActionEvidenceSnapshot",
    "RequirementActionIdFactory",
    "RequirementActionInputError",
    "RequirementActionLinkEntry",
    "RequirementActionNotFoundError",
    "RequirementActionPersistenceError",
    "RequirementActionProposalPageSnapshot",
    "RequirementActionProposalRecord",
    "RequirementActionProposalReview",
    "RequirementActionProposalStatus",
    "RequirementActionProposalView",
    "RequirementActionRepository",
    "RequirementActionRequirement",
    "RequirementActionReviewCandidate",
    "RequirementActionReviewRequirement",
    "RequirementActionSealedRunRepository",
    "RequirementActionSourceAuthority",
    "RequirementActionSourceContract",
    "RequirementActionStaleWindowError",
    "SealedRunRequirementActionSource",
    "requirement_action_candidate_manifest_fingerprint",
    "requirement_action_candidate_metadata_fingerprint",
    "requirement_action_descriptor_matches_candidate_metadata",
    "requirement_action_evidence_file_json_schema",
    "requirement_action_evidence_file_json_schema_sha256",
    "requirement_action_evidence_snapshot_fingerprint",
    "requirement_action_decision_authority_fingerprint",
    "requirement_action_graph_fingerprint",
    "escape_requirement_action_review_display",
    "parse_requirement_action_evidence_file",
    "requirement_plan_snapshot_fingerprint",
]
