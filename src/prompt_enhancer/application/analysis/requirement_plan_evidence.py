"""Reviewed, content-free requirement-to-plan evidence.

The canonical decomposition metric must not manufacture a denominator from a
lexical or model guess.  This module defines a narrow file and command boundary
where an agent may *propose* coordinates and classifications, but only a
native-confirmed local person can make one complete user-clause review
authoritative.  Every eligible user clause is classified; only clauses the
person confirms as active requirements enter the metric denominator.

Coordinates are bounded message-sequence/clause-index pairs.  The referenced
text is read ephemerally when a metric run validates the bundle; it is never
stored here.  Files have no prose field and cannot contain scores,
authoritative model-judgment claims, paths, or caller-issued evidence
identifiers.  Caller-supplied producer labels are preview-only and become an
application-keyed opaque claim receipt before persistence.  Structured
classifications remain explicitly untrusted until the owned-native review.
All durable identifiers and timestamps are issued by the application.
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
import re
from secrets import token_bytes, token_hex
from threading import Lock
from time import monotonic
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
)
from .text_contracts import P1TextAnalysisInput, TextMessageKind, TextRole


REQUIREMENT_PLAN_METRIC_KEY = "logic.decomposition_coverage"
REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION = "requirement-plan-evidence-v1"
REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION = "requirement-plan-evidence-file-v1"
REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION = "reviewed-requirement-plan-v1"
REQUIREMENT_PLAN_CLAUSE_ALGORITHM = "message-clause-coordinates-en-pl-v1"
REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION = (
    "active-requirement-plan-review-rubric-v1"
)
REQUIREMENT_PLAN_IMPORT_CONFIRMATION = (
    "import_requirement_plan_evidence_as_unconfirmed_proposal"
)
REQUIREMENT_PLAN_CANONICALIZATION = "json-sort-keys-compact-ensure-ascii-v1"
REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION = (
    "requirement-plan-file-constraints-v1"
)
REQUIREMENT_PLAN_SOURCE_MANIFEST_VERSION = "requirement-plan-source-manifest-v1"
REQUIREMENT_PLAN_DECISION_CONFIRMATION = (
    "apply_local_user_requirement_plan_evidence_decision"
)
REQUIREMENT_PLAN_REVIEW_CONFIRMATION = (
    "open_exact_local_requirement_plan_clause_review"
)
MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES = 64 * 1024
MAX_REQUIREMENT_PLAN_EVIDENCE_DEPTH = 8
MAX_REQUIREMENT_PLAN_EVIDENCE_ITEMS = 6_000
MAX_REQUIREMENT_PLAN_EVIDENCE_LIFETIME = timedelta(hours=24)
MAX_REQUIREMENT_PLAN_UNITS = 1_000
MAX_REQUIREMENT_PLAN_LINKS = 4_000
MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE = 128
MAX_REQUIREMENT_PLAN_PAGE_SIZE = 200
REQUIREMENT_PLAN_REVIEW_CONTEXT_TTL = timedelta(minutes=15)
REQUIREMENT_PLAN_REVIEW_RECEIPT_TTL = timedelta(minutes=10)
MAX_ACTIVE_REQUIREMENT_PLAN_REVIEW_CONTEXTS = 16
MAX_ACTIVE_REQUIREMENT_PLAN_REVIEW_RECEIPTS = 32
MAX_REQUIREMENT_PLAN_REVIEW_CANDIDATES = 100 * MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE

REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES = (
    "identifiers_match_current_contract",
    "producer_codes_match_safe_version_pattern",
    "expires_at_is_utc_after_validation_and_within_86400_seconds",
    "requirement_coordinates_are_sorted_unique",
    "plan_coordinates_are_sorted_unique",
    "plan_indexes_are_sorted_unique_non_negative",
    "linked_requires_nonempty_plan_indexes",
    "nonlinked_and_pending_require_empty_plan_indexes",
    "plan_indexes_reference_existing_plan_items",
    "total_plan_indexes_lte_4000",
    "requirement_coordinates_reference_user_request_or_feedback_clauses",
    "excluded_user_clause_coordinates_are_sorted_unique",
    "excluded_user_clause_reasons_use_closed_rubric",
    "exclusion_basis_coordinates_follow_reason_rules",
    "user_clauses_exactly_classified_as_active_or_excluded",
    "active_and_excluded_user_clause_coordinates_are_disjoint",
    "source_messages_fail_closed_above_128_normalized_clauses",
    "plan_coordinates_reference_agent_plan_clauses",
    "linked_plan_sequence_gte_requirement_sequence",
)

_CLAUSE_SPLIT = re.compile(r"(?:\r?\n)+|(?<=[.!?;])\s+")
_WHITESPACE = re.compile(r"\s+")


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be an installation-local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a short content-free identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


def reviewable_message_clauses(text: str) -> tuple[str, ...]:
    """Split one ephemeral message into stable review coordinates.

    The function deliberately performs no requirement/plan classification.
    It only normalizes whitespace and creates addressable clauses.  Callers
    must never persist the strings produced here.  The owned native review
    route may return them ephemerally with private/no-store headers.
    """

    normalized = text.replace("\x00", " ")
    clauses = tuple(
        item
        for item in (
            _WHITESPACE.sub(" ", part).strip()
            for part in _CLAUSE_SPLIT.split(normalized)
        )
        if item
    )
    if len(clauses) > MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE:
        raise ValueError("message exceeds the reviewable clause bound")
    return clauses


class RequirementDisposition(StrEnum):
    LINKED = "linked"
    NOT_LINKED = "not_linked"
    PENDING = "pending"


class RequirementPlanDecisionKind(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


class RequirementPlanExclusionReason(StrEnum):
    NOT_REQUIREMENT = "not_requirement"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"
    ALREADY_SATISFIED_OR_CLOSED = "already_satisfied_or_closed"


class RequirementPlanProposalStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RequirementCoordinate(StrictModel):
    message_sequence: int = Field(ge=0, le=1_000_000_000)
    clause_index: int = Field(ge=0, lt=MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE)


class PlanCoordinate(StrictModel):
    message_sequence: int = Field(ge=0, le=1_000_000_000)
    clause_index: int = Field(ge=0, lt=MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE)


class ExcludedRequirementClause(StrictModel):
    coordinate: RequirementCoordinate
    reason: RequirementPlanExclusionReason
    basis_coordinate: RequirementCoordinate | None = None

    @model_validator(mode="after")
    def exact_reason_basis(self) -> "ExcludedRequirementClause":
        requires_basis = self.reason in {
            RequirementPlanExclusionReason.SUPERSEDED,
            RequirementPlanExclusionReason.WITHDRAWN,
            RequirementPlanExclusionReason.DUPLICATE,
        }
        if requires_basis != (self.basis_coordinate is not None):
            raise ValueError("exclusion reason has the wrong basis-coordinate shape")
        if self.basis_coordinate == self.coordinate:
            raise ValueError("an excluded clause cannot be its own basis")
        return self


class RequirementPlanReviewRubric(StrictModel):
    """Closed operational meaning of the reviewed denominator and outcomes."""

    version: Literal[REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    )
    active_requirement_rule: Literal[
        "current_in_scope_user_owned_work_at_the_sealed_window"
    ] = "current_in_scope_user_owned_work_at_the_sealed_window"
    not_requirement_rule: Literal[
        "clause_does_not_express_work_to_be_performed"
    ] = "clause_does_not_express_work_to_be_performed"
    superseded_rule: Literal[
        "later_user_clause_explicitly_replaces_this_work"
    ] = "later_user_clause_explicitly_replaces_this_work"
    withdrawn_rule: Literal[
        "later_user_clause_explicitly_cancels_this_work"
    ] = "later_user_clause_explicitly_cancels_this_work"
    duplicate_rule: Literal[
        "same_active_work_is_owned_by_another_reviewed_clause"
    ] = "same_active_work_is_owned_by_another_reviewed_clause"
    out_of_scope_rule: Literal[
        "person_explicitly_excludes_this_work_from_the_current_scope"
    ] = "person_explicitly_excludes_this_work_from_the_current_scope"
    already_satisfied_or_closed_rule: Literal[
        "work_was_already_satisfied_or_explicitly_closed_before_this_snapshot"
    ] = "work_was_already_satisfied_or_explicitly_closed_before_this_snapshot"
    uncertain_policy: Literal["reject_or_leave_proposal_unconfirmed"] = (
        "reject_or_leave_proposal_unconfirmed"
    )
    exclusion_basis_policy: Literal[
        "superseded_and_withdrawn_point_to_a_later_user_clause_duplicate_points_to_its_active_owner"
    ] = "superseded_and_withdrawn_point_to_a_later_user_clause_duplicate_points_to_its_active_owner"
    linked_rule: Literal[
        "one_or_more_reviewed_concrete_plan_clauses_address_the_active_requirement"
    ] = "one_or_more_reviewed_concrete_plan_clauses_address_the_active_requirement"
    not_linked_rule: Literal[
        "no_reviewed_plan_clause_addresses_the_requirement_and_the_person_confirms_the_planning_horizon_closed"
    ] = "no_reviewed_plan_clause_addresses_the_requirement_and_the_person_confirms_the_planning_horizon_closed"
    pending_rule: Literal[
        "no_reviewed_plan_clause_yet_addresses_the_requirement_and_the_planning_horizon_is_not_confirmed_closed"
    ] = "no_reviewed_plan_clause_yet_addresses_the_requirement_and_the_planning_horizon_is_not_confirmed_closed"


class RequirementPlanSourceMessageManifest(StrictModel):
    """Content-free addressability for one message in the exact sealed window."""

    message_sequence: int = Field(ge=0, le=1_000_000_000)
    role: TextRole
    kind: TextMessageKind
    clause_count: int = Field(ge=0, le=MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE)


class RequirementPlanClauseAlgorithmContract(StrictModel):
    """Machine-readable reproduction recipe for source clause coordinates."""

    algorithm: Literal[REQUIREMENT_PLAN_CLAUSE_ALGORITHM] = (
        REQUIREMENT_PLAN_CLAUSE_ALGORITHM
    )
    implementation_semantics: Literal["python-3.12-re-unicode"] = (
        "python-3.12-re-unicode"
    )
    split_regex: Literal[r"(?:\r?\n)+|(?<=[.!?;])\s+"] = _CLAUSE_SPLIT.pattern
    split_regex_flags: Literal["unicode"] = "unicode"
    whitespace_regex: Literal[r"\s+"] = _WHITESPACE.pattern
    nul_replacement: Literal["ascii_space"] = "ascii_space"
    whitespace_replacement: Literal["ascii_space"] = "ascii_space"
    operation_order: tuple[
        Literal["replace_nul"],
        Literal["split"],
        Literal["normalize_whitespace"],
        Literal["trim"],
        Literal["omit_empty"],
        Literal["overflow_check"],
    ] = (
        "replace_nul",
        "split",
        "normalize_whitespace",
        "trim",
        "omit_empty",
        "overflow_check",
    )
    trim_each_part: Literal[True] = True
    omit_empty_parts: Literal[True] = True
    clause_indexes_are_zero_based: Literal[True] = True
    max_clauses_per_message: Literal[MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE] = (
        MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE
    )
    overflow_policy: Literal["fail_closed_above_128_normalized_clauses"] = (
        "fail_closed_above_128_normalized_clauses"
    )


class RequirementPlanSourceManifest(StrictModel):
    """Bounded content-free manifest used by external file producers."""

    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    schema_version: Literal[REQUIREMENT_PLAN_SOURCE_MANIFEST_VERSION] = (
        REQUIREMENT_PLAN_SOURCE_MANIFEST_VERSION
    )
    clause_algorithm: Literal[REQUIREMENT_PLAN_CLAUSE_ALGORITHM] = (
        REQUIREMENT_PLAN_CLAUSE_ALGORITHM
    )
    clause_algorithm_spec: RequirementPlanClauseAlgorithmContract
    review_rubric_version: Literal[REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    )
    review_rubric: RequirementPlanReviewRubric = Field(
        default_factory=RequirementPlanReviewRubric
    )
    messages: tuple[RequirementPlanSourceMessageManifest, ...] = Field(
        max_length=100
    )
    message_count: int = Field(ge=1, le=100)
    candidate_clause_count: int = Field(
        ge=0, le=MAX_REQUIREMENT_PLAN_REVIEW_CANDIDATES
    )
    manifest_fingerprint: str
    review_context_expires_at: datetime
    contains_text: Literal[False] = False
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
        "manifest_fingerprint",
    )(_pseudonym)
    _expiry = field_validator("review_context_expires_at")(_utc)

    @model_validator(mode="after")
    def exact_message_order(self) -> "RequirementPlanSourceManifest":
        sequences = tuple(item.message_sequence for item in self.messages)
        if sequences != tuple(sorted(set(sequences))):
            raise ValueError("source manifest messages must be unique and sorted")
        candidate_count = sum(
            item.clause_count
            for item in self.messages
            if (
                (item.role is TextRole.USER and item.kind in {
                    TextMessageKind.REQUEST,
                    TextMessageKind.FEEDBACK,
                })
                or (
                    item.role is TextRole.AGENT
                    and item.kind is TextMessageKind.PLAN
                )
            )
        )
        if (
            self.message_count != len(self.messages)
            or self.candidate_clause_count != candidate_count
            or self.manifest_fingerprint
            != _requirement_plan_source_manifest_core_fingerprint(
                session_id=self.session_id,
                source_run_id=self.source_run_id,
                source_window_fingerprint=self.source_window_fingerprint,
                messages=self.messages,
            )
        ):
            raise ValueError("source manifest count or fingerprint is invalid")
        return self


class RequirementPlanReviewClause(StrictModel):
    message_sequence: int = Field(ge=0, le=1_000_000_000)
    clause_index: int = Field(ge=0, lt=MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE)
    role: TextRole
    kind: TextMessageKind
    text: str = Field(min_length=1, repr=False)
    candidate_kind: Literal["user_clause", "plan"]
    included_in_proposal: bool
    classification: Literal[
        "active_requirement", "excluded_from_active_requirement_denominator"
    ] | None = None
    exclusion_reason: RequirementPlanExclusionReason | None = None
    basis_coordinate: RequirementCoordinate | None = None
    disposition: RequirementDisposition | None = None
    linked_plan_coordinates: tuple[PlanCoordinate, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS
    )

    @model_validator(mode="after")
    def exact_candidate_shape(self) -> "RequirementPlanReviewClause":
        linked_coordinates = tuple(
            (item.message_sequence, item.clause_index)
            for item in self.linked_plan_coordinates
        )
        if linked_coordinates != tuple(sorted(set(linked_coordinates))):
            raise ValueError("reviewed plan coordinates must be unique and sorted")
        if self.candidate_kind == "user_clause":
            if self.role is not TextRole.USER or self.kind not in {
                TextMessageKind.REQUEST,
                TextMessageKind.FEEDBACK,
            }:
                raise ValueError("requirement review candidate has the wrong source kind")
            if not self.included_in_proposal or self.classification is None:
                raise ValueError(
                    "every reviewed user clause must carry a classification"
                )
            if self.classification == "active_requirement":
                if self.exclusion_reason is not None or self.basis_coordinate is not None:
                    raise ValueError(
                        "active requirements cannot carry exclusion evidence"
                    )
                if self.disposition is None or (
                    self.disposition is RequirementDisposition.LINKED
                ) != bool(self.linked_plan_coordinates):
                    raise ValueError("active requirement review links are incoherent")
            else:
                if (
                    self.exclusion_reason is None
                    or self.disposition is not None
                    or self.linked_plan_coordinates
                ):
                    raise ValueError(
                        "excluded user clauses require one closed reason only"
                    )
                ExcludedRequirementClause(
                    coordinate=RequirementCoordinate(
                        message_sequence=self.message_sequence,
                        clause_index=self.clause_index,
                    ),
                    reason=self.exclusion_reason,
                    basis_coordinate=self.basis_coordinate,
                )
        elif (
            self.role is not TextRole.AGENT
            or self.kind is not TextMessageKind.PLAN
            or self.classification is not None
            or self.exclusion_reason is not None
            or self.basis_coordinate is not None
            or self.disposition is not None
            or self.linked_plan_coordinates
        ):
            raise ValueError("plan review candidate has the wrong source shape")
        return self


class RequirementPlanProposalReview(StrictModel):
    """Ephemeral clause text for a person reviewing one immutable proposal."""

    proposal_id: str
    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    review_receipt_id: str
    payload_sha256: str
    manifest_fingerprint: str
    reviewed_graph_fingerprint: str
    reviewed_candidate_set_fingerprint: str
    candidate_clauses: tuple[RequirementPlanReviewClause, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_REVIEW_CANDIDATES
    )
    review_context_expires_at: datetime
    review_receipt_expires_at: datetime
    all_coordinates_structurally_valid: Literal[True] = True
    raw_text_persisted: Literal[False] = False
    local_only: Literal[True] = True

    _ids = field_validator(
        "proposal_id",
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
        "review_receipt_id",
        "payload_sha256",
        "manifest_fingerprint",
        "reviewed_graph_fingerprint",
        "reviewed_candidate_set_fingerprint",
    )(_pseudonym)
    _expiry = field_validator(
        "review_context_expires_at", "review_receipt_expires_at"
    )(_utc)


@dataclass(frozen=True, slots=True)
class _RequirementPlanReviewReceiptEntry:
    proposal_id: str
    payload_sha256: str
    source_run_id: str
    source_window_fingerprint: str
    manifest_fingerprint: str
    reviewed_graph_fingerprint: str
    reviewed_candidate_set_fingerprint: str
    expires_at: datetime
    expires_monotonic: float


class RequirementEvidenceEntry(StrictModel):
    coordinate: RequirementCoordinate
    disposition: RequirementDisposition
    plan_indexes: tuple[int, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS
    )

    @field_validator("plan_indexes")
    @classmethod
    def sorted_unique_plan_indexes(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("plan indexes must be non-negative integers")
        if len(set(values)) != len(values) or values != tuple(sorted(values)):
            raise ValueError("plan indexes must be unique and sorted")
        return values

    @model_validator(mode="after")
    def closed_disposition_shape(self) -> "RequirementEvidenceEntry":
        if (self.disposition is RequirementDisposition.LINKED) != bool(
            self.plan_indexes
        ):
            raise ValueError("only linked requirements carry plan indexes")
        return self


class RequirementPlanProducer(StrictModel):
    """Ephemeral, explicitly untrusted producer claim from the submitted file."""

    kind: Literal["local_coding_agent"]
    producer_id: str
    producer_version: str
    model_id: str
    authority: Literal["untrusted_provenance_claim"]

    _codes = field_validator(
        "producer_id", "producer_version", "model_id"
    )(_safe_code)


class RequirementPlanProducerReceipt(StrictModel):
    """Content-free durable commitment to an ephemeral producer claim."""

    kind: Literal["local_coding_agent"] = "local_coding_agent"
    claim_fingerprint: str
    authority: Literal["untrusted_provenance_claim_commitment"] = (
        "untrusted_provenance_claim_commitment"
    )
    raw_claim_persisted: Literal[False] = False

    _claim = field_validator("claim_fingerprint")(_pseudonym)


class RequirementPlanEvidenceFileV1(StrictModel):
    schema_version: Literal[REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION]
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    expected_predecessor_confirmation_id: str | None = None
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2]
    contract_set_fingerprint: str
    metric_key: Literal[REQUIREMENT_PLAN_METRIC_KEY]
    metric_contract_fingerprint: str
    source_projection_version: Literal[
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    ]
    clause_algorithm: Literal[REQUIREMENT_PLAN_CLAUSE_ALGORITHM]
    review_rubric_version: Literal[REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION]
    nonce: str
    expires_at: datetime
    producer: RequirementPlanProducer
    contains_prose: Literal[False]
    contains_scores: Literal[False]
    contains_authoritative_model_judgment_claims: Literal[False]
    contains_untrusted_structured_proposals: Literal[True]
    contains_objective_receipt_claims: Literal[False]
    complete_user_clause_classification: Literal[True]
    requirements: tuple[RequirementEvidenceEntry, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    excluded_user_clauses: tuple[ExcludedRequirementClause, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    plan_items: tuple[PlanCoordinate, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
        "metric_contract_fingerprint",
        "nonce",
    )(_pseudonym)

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def predecessor_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_bundle_shape(self) -> "RequirementPlanEvidenceFileV1":
        contract = metric_contract_v2(REQUIREMENT_PLAN_METRIC_KEY)
        if self.contract_set_fingerprint != metric_contract_v2_set_fingerprint():
            raise ValueError("contract-set fingerprint does not match this application")
        if self.metric_contract_fingerprint != contract.fingerprint:
            raise ValueError("metric contract fingerprint does not match decomposition")
        requirement_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.requirements
        )
        excluded_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.excluded_user_clauses
        )
        plan_coordinates = tuple(
            (item.message_sequence, item.clause_index) for item in self.plan_items
        )
        if (
            len(set(requirement_coordinates)) != len(requirement_coordinates)
            or requirement_coordinates != tuple(sorted(requirement_coordinates))
        ):
            raise ValueError("requirement coordinates must be unique and sorted")
        if (
            len(set(excluded_coordinates)) != len(excluded_coordinates)
            or excluded_coordinates != tuple(sorted(excluded_coordinates))
            or set(excluded_coordinates) & set(requirement_coordinates)
            or len(requirement_coordinates) + len(excluded_coordinates)
            > MAX_REQUIREMENT_PLAN_UNITS
        ):
            raise ValueError(
                "excluded user-clause coordinates must be disjoint, unique, and sorted"
            )
        if (
            len(set(plan_coordinates)) != len(plan_coordinates)
            or plan_coordinates != tuple(sorted(plan_coordinates))
        ):
            raise ValueError("plan coordinates must be unique and sorted")
        total_links = sum(len(item.plan_indexes) for item in self.requirements)
        if total_links > MAX_REQUIREMENT_PLAN_LINKS:
            raise ValueError("requirement-plan links exceed their bound")
        if any(
            index >= len(self.plan_items)
            for item in self.requirements
            for index in item.plan_indexes
        ):
            raise ValueError("requirement link references an absent plan item")
        return self


def validate_requirement_plan_coordinates(
    *,
    requirements: tuple[RequirementEvidenceEntry, ...],
    excluded_user_clauses: tuple[ExcludedRequirementClause, ...],
    plan_items: tuple[PlanCoordinate, ...],
    manifest: RequirementPlanSourceManifest,
) -> None:
    """Validate every coordinate against the exact content-free source manifest."""

    messages = {item.message_sequence: item for item in manifest.messages}
    expected_requirement_coordinates = tuple(
        (message.message_sequence, clause_index)
        for message in manifest.messages
        if message.role is TextRole.USER
        and message.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
        for clause_index in range(message.clause_count)
    )
    active_requirement_coordinates = tuple(
        (item.coordinate.message_sequence, item.coordinate.clause_index)
        for item in requirements
    )
    excluded_coordinates = tuple(
        (item.coordinate.message_sequence, item.coordinate.clause_index)
        for item in excluded_user_clauses
    )
    classified_coordinates = tuple(
        sorted((*active_requirement_coordinates, *excluded_coordinates))
    )
    if (
        len(set(classified_coordinates)) != len(classified_coordinates)
        or classified_coordinates != expected_requirement_coordinates
    ):
        raise ValueError(
            "every reviewable user request or feedback clause must be exactly "
            "classified as an active requirement or excluded under the closed rubric"
        )
    for plan in plan_items:
        message = messages.get(plan.message_sequence)
        if (
            message is None
            or message.role is not TextRole.AGENT
            or message.kind is not TextMessageKind.PLAN
            or plan.clause_index >= message.clause_count
        ):
            raise ValueError("plan coordinate is absent from the sealed source manifest")
    for requirement in requirements:
        point = requirement.coordinate
        message = messages.get(point.message_sequence)
        if (
            message is None
            or message.role is not TextRole.USER
            or message.kind
            not in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
            or point.clause_index >= message.clause_count
        ):
            raise ValueError(
                "requirement coordinate is absent from the sealed source manifest"
            )
        if any(
            plan_items[index].message_sequence < point.message_sequence
            for index in requirement.plan_indexes
        ):
            raise ValueError("a linked plan precedes its requirement")
    for excluded in excluded_user_clauses:
        point = excluded.coordinate
        message = messages.get(point.message_sequence)
        if (
            message is None
            or message.role is not TextRole.USER
            or message.kind
            not in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
            or point.clause_index >= message.clause_count
        ):
            raise ValueError(
                "excluded user-clause coordinate is absent from the sealed source manifest"
            )
        basis = excluded.basis_coordinate
        if basis is None:
            continue
        basis_key = (basis.message_sequence, basis.clause_index)
        if basis_key not in set(expected_requirement_coordinates):
            raise ValueError("exclusion basis is absent from the sealed source manifest")
        point_key = (point.message_sequence, point.clause_index)
        if excluded.reason in {
            RequirementPlanExclusionReason.SUPERSEDED,
            RequirementPlanExclusionReason.WITHDRAWN,
        } and basis_key <= point_key:
            raise ValueError("supersession or withdrawal basis must be later")
        if (
            excluded.reason is RequirementPlanExclusionReason.DUPLICATE
            and basis_key not in set(active_requirement_coordinates)
        ):
            raise ValueError("duplicate exclusion basis must own an active requirement")


@dataclass(slots=True)
class _RequirementPlanReviewContextEntry:
    source_run_id: str
    context: P1TextAnalysisInput = field(repr=False)
    expires_at: datetime
    expires_monotonic: float


class InMemoryRequirementPlanReviewContextStore:
    """Bounded TTL-only redacted context used for explicit human review.

    The store never persists, serializes, or synchronizes the source window.
    Losing it on restart is intentional: the workflow then asks for a fresh
    sealed r6 run before accepting or reviewing coordinates.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic_clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] = lambda: token_hex(32),
        candidate_binding_key: bytes | None = None,
        max_active: int = MAX_ACTIVE_REQUIREMENT_PLAN_REVIEW_CONTEXTS,
        max_active_receipts: int = MAX_ACTIVE_REQUIREMENT_PLAN_REVIEW_RECEIPTS,
    ) -> None:
        if not 1 <= max_active <= MAX_ACTIVE_REQUIREMENT_PLAN_REVIEW_CONTEXTS:
            raise ValueError("review context capacity is outside its bound")
        if not 1 <= max_active_receipts <= MAX_ACTIVE_REQUIREMENT_PLAN_REVIEW_RECEIPTS:
            raise ValueError("review receipt capacity is outside its bound")
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._max_active = max_active
        self._max_active_receipts = max_active_receipts
        self._token_factory = token_factory
        self._candidate_binding_key = (
            token_bytes(32) if candidate_binding_key is None else candidate_binding_key
        )
        if (
            not isinstance(self._candidate_binding_key, bytes)
            or len(self._candidate_binding_key) != 32
        ):
            raise ValueError("review candidate binding key must contain 32 bytes")
        self._entries: OrderedDict[str, _RequirementPlanReviewContextEntry] = (
            OrderedDict()
        )
        self._lock = Lock()
        self._receipts: OrderedDict[
            str, _RequirementPlanReviewReceiptEntry
        ] = OrderedDict()
        self._receipt_tombstones: OrderedDict[str, str] = OrderedDict()

    def publish(self, source_run_id: str, context: P1TextAnalysisInput) -> None:
        _pseudonym(source_run_id)
        now = _utc(self._clock())
        monotonic_now = self._monotonic_clock()
        entry = _RequirementPlanReviewContextEntry(
            source_run_id=source_run_id,
            context=context,
            expires_at=now + REQUIREMENT_PLAN_REVIEW_CONTEXT_TTL,
            expires_monotonic=(
                monotonic_now + REQUIREMENT_PLAN_REVIEW_CONTEXT_TTL.total_seconds()
            ),
        )
        with self._lock:
            self._expire_locked(now, monotonic_now)
            self._entries[source_run_id] = entry
            self._entries.move_to_end(source_run_id)
            while len(self._entries) > self._max_active:
                self._entries.popitem(last=False)

    def manifest(
        self,
        *,
        session_id: str,
        source_run_id: str,
        source_window_fingerprint: str,
    ) -> RequirementPlanSourceManifest:
        entry = self._require(
            session_id=session_id,
            source_run_id=source_run_id,
            source_window_fingerprint=source_window_fingerprint,
        )
        return self._manifest(entry)

    def review(
        self, proposal: "RequirementPlanProposalView"
    ) -> RequirementPlanProposalReview:
        record = proposal.proposal
        entry = self._require(
            session_id=record.session_id,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
        )
        manifest = self._manifest(entry)
        validate_requirement_plan_coordinates(
            requirements=record.requirements,
            excluded_user_clauses=record.excluded_user_clauses,
            plan_items=record.plan_items,
            manifest=manifest,
        )
        manifest_fingerprint = requirement_plan_source_manifest_fingerprint(manifest)
        reviewed_graph_fingerprint = requirement_plan_graph_fingerprint(record)
        candidate_clauses = self._candidate_clauses(
            proposal=proposal, context=entry.context
        )
        reviewed_candidate_set_fingerprint = self._candidate_set_fingerprint(
            candidate_clauses
        )

        now = _utc(self._clock())
        monotonic_now = self._monotonic_clock()
        receipt_expires_at = min(
            entry.expires_at, now + REQUIREMENT_PLAN_REVIEW_RECEIPT_TTL
        )
        review_receipt_id = self._token_factory()
        _pseudonym(review_receipt_id)
        receipt = _RequirementPlanReviewReceiptEntry(
            proposal_id=record.proposal_id,
            payload_sha256=record.payload_sha256,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
            manifest_fingerprint=manifest_fingerprint,
            reviewed_graph_fingerprint=reviewed_graph_fingerprint,
            reviewed_candidate_set_fingerprint=(
                reviewed_candidate_set_fingerprint
            ),
            expires_at=receipt_expires_at,
            expires_monotonic=monotonic_now
            + min(
                REQUIREMENT_PLAN_REVIEW_RECEIPT_TTL.total_seconds(),
                max(0.0, (entry.expires_at - now).total_seconds()),
            ),
        )
        with self._lock:
            self._expire_locked(now, monotonic_now)
            if self._entries.get(record.source_run_id) is not entry:
                raise RequirementPlanConflictError(
                    "requirement-plan review context changed during review"
                )
            if (
                review_receipt_id in self._receipts
                or review_receipt_id in self._receipt_tombstones
            ):
                raise RequirementPlanConflictError(
                    "requirement-plan review receipt identity collided"
                )
            self._receipts[review_receipt_id] = receipt
            while len(self._receipts) > self._max_active_receipts:
                expired_id, _entry = self._receipts.popitem(last=False)
                self._tombstone_receipt_locked(expired_id, "expired")
        return RequirementPlanProposalReview(
            proposal_id=record.proposal_id,
            session_id=record.session_id,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
            review_receipt_id=review_receipt_id,
            payload_sha256=record.payload_sha256,
            manifest_fingerprint=manifest_fingerprint,
            reviewed_graph_fingerprint=reviewed_graph_fingerprint,
            reviewed_candidate_set_fingerprint=(
                reviewed_candidate_set_fingerprint
            ),
            candidate_clauses=candidate_clauses,
            review_context_expires_at=entry.expires_at,
            review_receipt_expires_at=receipt_expires_at,
        )

    def consume_review_receipt(
        self,
        *,
        review_receipt_id: str,
        proposal: "RequirementPlanProposalView",
        manifest_fingerprint: str,
        reviewed_graph_fingerprint: str,
        reviewed_candidate_set_fingerprint: str,
    ) -> None:
        _pseudonym(review_receipt_id)
        _pseudonym(manifest_fingerprint)
        _pseudonym(reviewed_graph_fingerprint)
        _pseudonym(reviewed_candidate_set_fingerprint)
        record = proposal.proposal
        now = _utc(self._clock())
        monotonic_now = self._monotonic_clock()
        with self._lock:
            self._expire_locked(now, monotonic_now)
            receipt = self._receipts.pop(review_receipt_id, None)
            self._tombstone_receipt_locked(review_receipt_id, "consumed")
            entry = self._entries.get(record.source_run_id)
            if receipt is None or entry is None:
                raise RequirementPlanConflictError(
                    "requirement-plan review receipt is unavailable"
                )
            if (
                entry.context.session_id != record.session_id
                or entry.context.analysis_window_fingerprint
                != record.source_window_fingerprint
            ):
                raise RequirementPlanConflictError(
                    "requirement-plan review context belongs to another source"
                )
            current_manifest = self._manifest(entry)
            validate_requirement_plan_coordinates(
                requirements=record.requirements,
                excluded_user_clauses=record.excluded_user_clauses,
                plan_items=record.plan_items,
                manifest=current_manifest,
            )
            current_manifest_fingerprint = (
                requirement_plan_source_manifest_fingerprint(current_manifest)
            )
            current_review = self._candidate_clauses(
                proposal=proposal, context=entry.context
            )
            current_candidate_fingerprint = self._candidate_set_fingerprint(
                current_review
            )
            exact_graph = requirement_plan_graph_fingerprint(record)
            exact = (
                receipt.expires_at > now
                and receipt.expires_monotonic > monotonic_now
                and receipt.proposal_id == record.proposal_id
                and receipt.payload_sha256 == record.payload_sha256
                and receipt.source_run_id == record.source_run_id
                and receipt.source_window_fingerprint
                == record.source_window_fingerprint
                and receipt.manifest_fingerprint == manifest_fingerprint
                and receipt.manifest_fingerprint == current_manifest_fingerprint
                and receipt.reviewed_graph_fingerprint
                == reviewed_graph_fingerprint
                and receipt.reviewed_graph_fingerprint == exact_graph
                and receipt.reviewed_candidate_set_fingerprint
                == reviewed_candidate_set_fingerprint
                and receipt.reviewed_candidate_set_fingerprint
                == current_candidate_fingerprint
            )
        if not exact:
            raise RequirementPlanConflictError(
                "requirement-plan review receipt binding changed"
            )

    @staticmethod
    def _candidate_clauses(
        *,
        proposal: "RequirementPlanProposalView",
        context: P1TextAnalysisInput,
    ) -> tuple[RequirementPlanReviewClause, ...]:
        record = proposal.proposal
        requirements = {
            (item.coordinate.message_sequence, item.coordinate.clause_index): item
            for item in record.requirements
        }
        exclusions = {
            (item.coordinate.message_sequence, item.coordinate.clause_index): item
            for item in record.excluded_user_clauses
        }
        plans = {
            (item.message_sequence, item.clause_index): index
            for index, item in enumerate(record.plan_items)
        }
        result: list[RequirementPlanReviewClause] = []
        for message in sorted(context.messages, key=lambda item: item.sequence):
            clauses = reviewable_message_clauses(message.text.get_secret_value())
            if message.role is TextRole.USER and message.kind in {
                TextMessageKind.REQUEST,
                TextMessageKind.FEEDBACK,
            }:
                for clause_index, text in enumerate(clauses):
                    requirement = requirements.get((message.sequence, clause_index))
                    exclusion = exclusions.get(
                        (message.sequence, clause_index)
                    )
                    result.append(
                        RequirementPlanReviewClause(
                            message_sequence=message.sequence,
                            clause_index=clause_index,
                            role=message.role,
                            kind=message.kind,
                            text=text,
                            candidate_kind="user_clause",
                            included_in_proposal=(
                                requirement is not None
                                or exclusion is not None
                            ),
                            classification=(
                                "active_requirement"
                                if requirement is not None
                                else "excluded_from_active_requirement_denominator"
                                if exclusion is not None
                                else None
                            ),
                            exclusion_reason=(
                                None if exclusion is None else exclusion.reason
                            ),
                            basis_coordinate=(
                                None if exclusion is None else exclusion.basis_coordinate
                            ),
                            disposition=None if requirement is None else requirement.disposition,
                            linked_plan_coordinates=(
                                ()
                                if requirement is None
                                else tuple(
                                    record.plan_items[index]
                                    for index in requirement.plan_indexes
                                )
                            ),
                        )
                    )
            elif message.role is TextRole.AGENT and message.kind is TextMessageKind.PLAN:
                result.extend(
                    RequirementPlanReviewClause(
                        message_sequence=message.sequence,
                        clause_index=clause_index,
                        role=message.role,
                        kind=message.kind,
                        text=text,
                        candidate_kind="plan",
                        included_in_proposal=(message.sequence, clause_index) in plans,
                    )
                    for clause_index, text in enumerate(clauses)
                )
        return tuple(result)

    def _candidate_set_fingerprint(
        self, candidates: tuple[RequirementPlanReviewClause, ...]
    ) -> str:
        """Return a process-keyed commitment without exposing a text hash."""

        payload = json.dumps(
            [item.model_dump(mode="json") for item in candidates],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hmac.new(
            self._candidate_binding_key,
            b"prompt-enhancer/requirement-plan-candidate-set/v1\0" + payload,
            hashlib.sha256,
        ).hexdigest()

    def _require(
        self,
        *,
        session_id: str,
        source_run_id: str,
        source_window_fingerprint: str,
    ) -> _RequirementPlanReviewContextEntry:
        _pseudonym(session_id)
        _pseudonym(source_run_id)
        _pseudonym(source_window_fingerprint)
        with self._lock:
            now = _utc(self._clock())
            monotonic_now = self._monotonic_clock()
            self._expire_locked(now, monotonic_now)
            entry = self._entries.get(source_run_id)
            if entry is None:
                raise RequirementPlanNotFoundError(
                    "fresh ephemeral requirement-plan review context is required"
                )
            context = entry.context
            if (
                context.session_id != session_id
                or context.analysis_window_fingerprint != source_window_fingerprint
            ):
                raise RequirementPlanConflictError(
                    "requirement-plan review context belongs to another source"
                )
            self._entries.move_to_end(source_run_id)
            return entry

    @staticmethod
    def _manifest(
        entry: _RequirementPlanReviewContextEntry,
    ) -> RequirementPlanSourceManifest:
        context = entry.context
        try:
            messages = tuple(
                RequirementPlanSourceMessageManifest(
                    message_sequence=message.sequence,
                    role=message.role,
                    kind=message.kind,
                    clause_count=len(
                        reviewable_message_clauses(message.text.get_secret_value())
                    ),
                )
                for message in context.messages
            )
        except ValueError:
            raise RequirementPlanInputError(
                "sealed source exceeds the reviewable clause bound"
            ) from None
        reviewable_user_clause_count = sum(
            item.clause_count
            for item in messages
            if item.role is TextRole.USER
            and item.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
        )
        candidate_clause_count = sum(
            item.clause_count
            for item in messages
            if (
                (
                    item.role is TextRole.USER
                    and item.kind
                    in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
                )
                or (
                    item.role is TextRole.AGENT
                    and item.kind is TextMessageKind.PLAN
                )
            )
        )
        if (
            reviewable_user_clause_count > MAX_REQUIREMENT_PLAN_UNITS
            or candidate_clause_count > MAX_REQUIREMENT_PLAN_REVIEW_CANDIDATES
        ):
            raise RequirementPlanInputError(
                "sealed source exceeds the bounded review candidate count"
            )
        return RequirementPlanSourceManifest(
            session_id=context.session_id,
            source_run_id=entry.source_run_id,
            source_window_fingerprint=context.analysis_window_fingerprint,
            clause_algorithm_spec=RequirementPlanClauseAlgorithmContract(),
            messages=messages,
            message_count=len(messages),
            candidate_clause_count=candidate_clause_count,
            manifest_fingerprint=_requirement_plan_source_manifest_core_fingerprint(
                session_id=context.session_id,
                source_run_id=entry.source_run_id,
                source_window_fingerprint=context.analysis_window_fingerprint,
                messages=messages,
            ),
            review_context_expires_at=entry.expires_at,
        )

    def _expire_locked(self, now: datetime, monotonic_now: float) -> None:
        expired = tuple(
            source_run_id
            for source_run_id, entry in self._entries.items()
            if now >= entry.expires_at or monotonic_now >= entry.expires_monotonic
        )
        for source_run_id in expired:
            del self._entries[source_run_id]
        expired_receipts = tuple(
            review_id
            for review_id, entry in self._receipts.items()
            if now >= entry.expires_at or monotonic_now >= entry.expires_monotonic
        )
        for review_id in expired_receipts:
            del self._receipts[review_id]
            self._tombstone_receipt_locked(review_id, "expired")

    def _tombstone_receipt_locked(self, review_id: str, state: str) -> None:
        self._receipt_tombstones[review_id] = state
        self._receipt_tombstones.move_to_end(review_id)
        while len(self._receipt_tombstones) > 64:
            self._receipt_tombstones.popitem(last=False)


def _requirement_plan_source_manifest_core_fingerprint(
    *,
    session_id: str,
    source_run_id: str,
    source_window_fingerprint: str,
    messages: tuple[RequirementPlanSourceMessageManifest, ...],
) -> str:
    payload = {
        "schema_version": REQUIREMENT_PLAN_SOURCE_MANIFEST_VERSION,
        "session_id": session_id,
        "source_run_id": source_run_id,
        "source_window_fingerprint": source_window_fingerprint,
        "clause_algorithm": REQUIREMENT_PLAN_CLAUSE_ALGORITHM,
        "clause_algorithm_spec": RequirementPlanClauseAlgorithmContract().model_dump(
            mode="json"
        ),
        "review_rubric_version": REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        "review_rubric": RequirementPlanReviewRubric().model_dump(mode="json"),
        "messages": [item.model_dump(mode="json") for item in messages],
        "message_count": len(messages),
        "candidate_clause_count": sum(
            item.clause_count
            for item in messages
            if (
                (item.role is TextRole.USER and item.kind in {
                    TextMessageKind.REQUEST,
                    TextMessageKind.FEEDBACK,
                })
                or (item.role is TextRole.AGENT and item.kind is TextMessageKind.PLAN)
            )
        ),
        "contains_text": False,
        "local_only": True,
        "content_persisted": False,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    ).hexdigest()


def requirement_plan_source_manifest_fingerprint(
    manifest: RequirementPlanSourceManifest,
) -> str:
    expected = _requirement_plan_source_manifest_core_fingerprint(
        session_id=manifest.session_id,
        source_run_id=manifest.source_run_id,
        source_window_fingerprint=manifest.source_window_fingerprint,
        messages=manifest.messages,
    )
    if manifest.manifest_fingerprint != expected:
        raise ValueError("source manifest fingerprint is invalid")
    return expected


def requirement_plan_graph_fingerprint(proposal: Any) -> str:
    payload = {
        "proposal_id": proposal.proposal_id,
        "session_id": proposal.session_id,
        "source_run_id": proposal.source_run_id,
        "source_window_fingerprint": proposal.source_window_fingerprint,
        "payload_sha256": proposal.payload_sha256,
        "producer_receipt": proposal.producer_receipt.model_dump(mode="json"),
        "review_rubric_version": proposal.review_rubric_version,
        "requirements": [
            item.model_dump(mode="json") for item in proposal.requirements
        ],
        "excluded_user_clauses": [
            item.model_dump(mode="json")
            for item in proposal.excluded_user_clauses
        ],
        "plan_items": [item.model_dump(mode="json") for item in proposal.plan_items],
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    ).hexdigest()


def requirement_plan_evidence_file_json_schema() -> dict[str, Any]:
    """Return the machine-readable file shape plus non-JSON-Schema invariants.

    Pydantic's generated JSON Schema cannot express ordering, cross-array
    references, current-source equality, or a validation-time-relative UTC
    bound.  Those constraints are therefore part of this same versioned
    machine contract under ``x-prompt-enhancer-constraints`` rather than
    being left as undocumented parser behavior.
    """

    schema = RequirementPlanEvidenceFileV1.model_json_schema(mode="validation")
    properties = schema["properties"]
    for key in (
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
        "metric_contract_fingerprint",
        "nonce",
    ):
        properties[key]["pattern"] = PSEUDONYM_PATTERN.pattern
    properties["expected_predecessor_confirmation_id"]["anyOf"][0][
        "pattern"
    ] = PSEUDONYM_PATTERN.pattern
    producer = schema["$defs"]["RequirementPlanProducer"]["properties"]
    for key in ("producer_id", "producer_version", "model_id"):
        producer[key]["pattern"] = SAFE_VERSION_PATTERN.pattern
    entry = schema["$defs"]["RequirementEvidenceEntry"]
    entry["properties"]["plan_indexes"]["uniqueItems"] = True
    entry["properties"]["plan_indexes"]["items"]["minimum"] = 0
    properties["excluded_user_clauses"]["uniqueItems"] = True
    schema["x-prompt-enhancer-constraint-contract"] = (
        REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION
    )
    schema["x-prompt-enhancer-constraints"] = [
        {"code": code, "required": True}
        for code in REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES
    ]
    return schema


def requirement_plan_evidence_file_json_schema_sha256() -> str:
    return hashlib.sha256(
        json.dumps(
            requirement_plan_evidence_file_json_schema(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


class RequirementPlanEvidencePreview(StrictModel):
    payload_sha256: str
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    expected_predecessor_confirmation_id: str | None = None
    reviewed_user_clause_count: int = Field(ge=0, le=MAX_REQUIREMENT_PLAN_UNITS)
    active_requirement_count: int = Field(ge=0, le=MAX_REQUIREMENT_PLAN_UNITS)
    excluded_user_clause_count: int = Field(ge=0, le=MAX_REQUIREMENT_PLAN_UNITS)
    plan_item_count: int = Field(ge=0, le=MAX_REQUIREMENT_PLAN_UNITS)
    linked_active_requirement_count: int = Field(
        ge=0, le=MAX_REQUIREMENT_PLAN_UNITS
    )
    not_linked_active_requirement_count: int = Field(
        ge=0, le=MAX_REQUIREMENT_PLAN_UNITS
    )
    pending_active_requirement_count: int = Field(
        ge=0, le=MAX_REQUIREMENT_PLAN_UNITS
    )
    link_count: int = Field(ge=0, le=MAX_REQUIREMENT_PLAN_LINKS)
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
    )(_pseudonym)
    _expiry = field_validator("expires_at")(_utc)

    @model_validator(mode="after")
    def exact_review_counts(self) -> "RequirementPlanEvidencePreview":
        if self.reviewed_user_clause_count != (
            self.active_requirement_count + self.excluded_user_clause_count
        ):
            raise ValueError("reviewed user-clause counts are incoherent")
        if self.active_requirement_count != (
            self.linked_active_requirement_count
            + self.not_linked_active_requirement_count
            + self.pending_active_requirement_count
        ):
            raise ValueError("active requirement disposition counts are incoherent")
        if self.linked_active_requirement_count > self.link_count:
            raise ValueError("linked requirements require at least one link each")
        if self.plan_item_count == 0 and self.link_count != 0:
            raise ValueError("links require at least one plan item")
        return self

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)


class RequirementPlanEvidenceContract(StrictModel):
    """Exact content-free recipe an agent may use to prepare one file."""

    schema_version: Literal[REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION] = (
        REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION
    )
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    expected_predecessor_confirmation_id: str | None = None
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    metric_key: Literal[REQUIREMENT_PLAN_METRIC_KEY] = REQUIREMENT_PLAN_METRIC_KEY
    metric_contract_fingerprint: str
    source_projection_version: Literal[
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    ]
    clause_algorithm: Literal[REQUIREMENT_PLAN_CLAUSE_ALGORITHM] = (
        REQUIREMENT_PLAN_CLAUSE_ALGORITHM
    )
    clause_algorithm_spec: RequirementPlanClauseAlgorithmContract
    review_rubric_version: Literal[REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    )
    review_rubric: RequirementPlanReviewRubric = Field(
        default_factory=RequirementPlanReviewRubric
    )
    allowed_dispositions: tuple[Literal["linked", "not_linked", "pending"], ...] = (
        "linked",
        "not_linked",
        "pending",
    )
    allowed_user_clause_classifications: tuple[
        Literal[
            "active_requirement",
            "excluded_from_active_requirement_denominator",
        ],
        ...,
    ] = (
        "active_requirement",
        "excluded_from_active_requirement_denominator",
    )
    allowed_exclusion_reasons: tuple[
        Literal[
            "not_requirement",
            "superseded",
            "withdrawn",
            "duplicate",
            "out_of_scope",
            "already_satisfied_or_closed",
        ],
        ...,
    ] = tuple(item.value for item in RequirementPlanExclusionReason)
    max_reviewed_user_clause_count: Literal[MAX_REQUIREMENT_PLAN_UNITS] = (
        MAX_REQUIREMENT_PLAN_UNITS
    )
    max_active_requirement_count: Literal[MAX_REQUIREMENT_PLAN_UNITS] = (
        MAX_REQUIREMENT_PLAN_UNITS
    )
    max_excluded_user_clause_count: Literal[MAX_REQUIREMENT_PLAN_UNITS] = (
        MAX_REQUIREMENT_PLAN_UNITS
    )
    max_plan_item_count: Literal[MAX_REQUIREMENT_PLAN_UNITS] = (
        MAX_REQUIREMENT_PLAN_UNITS
    )
    max_link_count: Literal[MAX_REQUIREMENT_PLAN_LINKS] = MAX_REQUIREMENT_PLAN_LINKS
    max_file_bytes: Literal[MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES] = (
        MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES
    )
    max_json_depth: Literal[MAX_REQUIREMENT_PLAN_EVIDENCE_DEPTH] = (
        MAX_REQUIREMENT_PLAN_EVIDENCE_DEPTH
    )
    max_json_items: Literal[MAX_REQUIREMENT_PLAN_EVIDENCE_ITEMS] = (
        MAX_REQUIREMENT_PLAN_EVIDENCE_ITEMS
    )
    max_clauses_per_message: Literal[MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE] = (
        MAX_REQUIREMENT_PLAN_CLAUSES_PER_MESSAGE
    )
    max_lifetime_seconds: Literal[86_400] = 86_400
    canonical_json_required: Literal[True] = True
    canonicalization: Literal[REQUIREMENT_PLAN_CANONICALIZATION] = (
        REQUIREMENT_PLAN_CANONICALIZATION
    )
    payload_digest: Literal["sha256"] = "sha256"
    utf8_without_bom_required: Literal[True] = True
    duplicate_keys_allowed: Literal[False] = False
    floating_point_values_allowed: Literal[False] = False
    candidate_unit: Literal["reviewable_user_request_or_feedback_clause"] = (
        "reviewable_user_request_or_feedback_clause"
    )
    opportunity_unit: Literal["reviewed_active_requirement_clause"] = (
        "reviewed_active_requirement_clause"
    )
    complete_user_clause_classification_required: Literal[True] = True
    compound_clause_coarsening_disclosed: Literal[True] = True
    one_active_requirement_coordinate_is_one_opportunity: Literal[True] = True
    excluded_user_clauses_are_excluded_from_metric: Literal[True] = True
    uncertain_classification_policy: Literal[
        "reject_or_leave_proposal_unconfirmed"
    ] = "reject_or_leave_proposal_unconfirmed"
    import_creates_unconfirmed_proposal_only: Literal[True] = True
    native_confirmation_required_for_metric_authority: Literal[True] = True
    raw_payload_persisted: Literal[False] = False
    prose_allowed: Literal[False] = False
    scores_allowed: Literal[False] = False
    untrusted_structured_classification_proposals_allowed: Literal[True] = True
    authoritative_model_judgment_claims_allowed: Literal[False] = False
    raw_producer_claim_persisted: Literal[False] = False
    durable_producer_claim_shape: Literal[
        "installation_keyed_opaque_commitment_only"
    ] = "installation_keyed_opaque_commitment_only"
    objective_receipt_claims_allowed: Literal[False] = False
    import_confirmation: Literal[REQUIREMENT_PLAN_IMPORT_CONFIRMATION] = (
        REQUIREMENT_PLAN_IMPORT_CONFIRMATION
    )
    file_json_schema_sha256: str
    file_json_schema: dict[str, Any]
    source_manifest: RequirementPlanSourceManifest
    file_constraint_contract_version: Literal[
        REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION
    ] = REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION
    file_constraint_codes: tuple[
        Literal[
            "identifiers_match_current_contract",
            "producer_codes_match_safe_version_pattern",
            "expires_at_is_utc_after_validation_and_within_86400_seconds",
            "requirement_coordinates_are_sorted_unique",
            "plan_coordinates_are_sorted_unique",
            "plan_indexes_are_sorted_unique_non_negative",
            "linked_requires_nonempty_plan_indexes",
            "nonlinked_and_pending_require_empty_plan_indexes",
            "plan_indexes_reference_existing_plan_items",
            "total_plan_indexes_lte_4000",
            "requirement_coordinates_reference_user_request_or_feedback_clauses",
            "excluded_user_clause_coordinates_are_sorted_unique",
            "excluded_user_clause_reasons_use_closed_rubric",
            "exclusion_basis_coordinates_follow_reason_rules",
            "user_clauses_exactly_classified_as_active_or_excluded",
            "active_and_excluded_user_clause_coordinates_are_disjoint",
            "source_messages_fail_closed_above_128_normalized_clauses",
            "plan_coordinates_reference_agent_plan_clauses",
            "linked_plan_sequence_gte_requirement_sequence",
        ],
        ...,
    ] = REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
        "metric_contract_fingerprint",
        "file_json_schema_sha256",
    )(_pseudonym)

    @field_validator("expected_predecessor_confirmation_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)


class RequirementPlanProposalRecord(StrictModel):
    proposal_id: str
    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    expected_predecessor_confirmation_id: str | None = None
    payload_sha256: str
    idempotency_key_digest: str
    command_fingerprint: str
    producer_receipt: RequirementPlanProducerReceipt
    review_rubric_version: Literal[REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION] = (
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    )
    requirements: tuple[RequirementEvidenceEntry, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    excluded_user_clauses: tuple[ExcludedRequirementClause, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    plan_items: tuple[PlanCoordinate, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    created_at: datetime
    schema_version: Literal[REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION] = (
        REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION
    )
    policy_version: Literal[REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION] = (
        REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "proposal_id",
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
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
    def validate_normalized_bundle(self) -> "RequirementPlanProposalRecord":
        # Reuse the file model's structural checks without accepting provenance.
        requirement_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.requirements
        )
        excluded_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.excluded_user_clauses
        )
        plan_coordinates = tuple(
            (item.message_sequence, item.clause_index) for item in self.plan_items
        )
        if requirement_coordinates != tuple(sorted(set(requirement_coordinates))):
            raise ValueError("stored requirement coordinates are invalid")
        if (
            excluded_coordinates != tuple(sorted(set(excluded_coordinates)))
            or set(excluded_coordinates) & set(requirement_coordinates)
            or len(requirement_coordinates) + len(excluded_coordinates)
            > MAX_REQUIREMENT_PLAN_UNITS
        ):
            raise ValueError("stored excluded user-clause coordinates are invalid")
        if plan_coordinates != tuple(sorted(set(plan_coordinates))):
            raise ValueError("stored plan coordinates are invalid")
        if any(
            index >= len(self.plan_items)
            for item in self.requirements
            for index in item.plan_indexes
        ):
            raise ValueError("stored plan link is invalid")
        if sum(len(item.plan_indexes) for item in self.requirements) > (
            MAX_REQUIREMENT_PLAN_LINKS
        ):
            raise ValueError("stored requirement-plan links exceed their bound")
        return self


class RequirementPlanDecisionCommand(StrictModel):
    expected_source_run_id: str
    decision: RequirementPlanDecisionKind
    confirmation: Literal[REQUIREMENT_PLAN_DECISION_CONFIRMATION]
    review_receipt_id: str | None = None
    manifest_fingerprint: str | None = None
    reviewed_graph_fingerprint: str | None = None
    reviewed_candidate_set_fingerprint: str | None = None
    complete_review_acknowledged: bool = False

    _run = field_validator("expected_source_run_id")(_pseudonym)

    @field_validator(
        "review_receipt_id",
        "manifest_fingerprint",
        "reviewed_graph_fingerprint",
        "reviewed_candidate_set_fingerprint",
    )
    @classmethod
    def optional_review_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_review_authority(self) -> "RequirementPlanDecisionCommand":
        fields = (
            self.review_receipt_id,
            self.manifest_fingerprint,
            self.reviewed_graph_fingerprint,
            self.reviewed_candidate_set_fingerprint,
        )
        if self.decision is RequirementPlanDecisionKind.CONFIRM:
            if any(value is None for value in fields) or not self.complete_review_acknowledged:
                raise ValueError("confirmation requires an exact completed review receipt")
        elif any(value is not None for value in fields) or self.complete_review_acknowledged:
            raise ValueError("rejection cannot carry a confirmation review receipt")
        return self


class RequirementPlanDecisionRecord(StrictModel):
    decision_id: str
    proposal_id: str
    session_id: str
    decision: RequirementPlanDecisionKind
    idempotency_key_digest: str
    command_fingerprint: str
    decided_at: datetime
    confirmation_authority: Literal["owned_native_user_presence"] = (
        "owned_native_user_presence"
    )
    schema_version: Literal[REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION] = (
        REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "decision_id",
        "proposal_id",
        "session_id",
        "idempotency_key_digest",
        "command_fingerprint",
    )(_pseudonym)
    _decided = field_validator("decided_at")(_utc)


class RequirementPlanProposalView(StrictModel):
    proposal: RequirementPlanProposalRecord
    decision: RequirementPlanDecisionRecord | None = None
    status: RequirementPlanProposalStatus

    @model_validator(mode="after")
    def decision_status_agrees(self) -> "RequirementPlanProposalView":
        expected = (
            RequirementPlanProposalStatus.PROPOSED
            if self.decision is None
            else RequirementPlanProposalStatus.CONFIRMED
            if self.decision.decision is RequirementPlanDecisionKind.CONFIRM
            else RequirementPlanProposalStatus.REJECTED
        )
        if self.status is not expected:
            raise ValueError("proposal status disagrees with its decision")
        return self


class RequirementPlanProposalPageSnapshot(StrictModel):
    """Server-issued high-water boundary for one stable multi-page listing."""

    snapshot_id: str
    total: int = Field(ge=0, le=1_000_000)
    decision_count: int = Field(ge=0, le=1_000_000)
    high_water_created_at: datetime | None = None
    high_water_proposal_id: str | None = None

    @field_validator("high_water_created_at")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @field_validator("high_water_proposal_id")
    @classmethod
    def optional_high_water_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    _snapshot_id = field_validator("snapshot_id")(_pseudonym)

    @model_validator(mode="after")
    def exact_empty_or_bounded(self) -> "RequirementPlanProposalPageSnapshot":
        has_boundary = (
            self.high_water_created_at is not None
            and self.high_water_proposal_id is not None
        )
        if has_boundary != (self.total > 0):
            raise ValueError("proposal page snapshot boundary is incomplete")
        if (self.high_water_created_at is None) != (
            self.high_water_proposal_id is None
        ):
            raise ValueError("proposal page snapshot fields must be paired")
        if self.decision_count > self.total:
            raise ValueError("proposal page snapshot has too many decisions")
        return self


class ConfirmedRequirementEvidence(StrictModel):
    requirement_id: str
    coordinate: RequirementCoordinate
    disposition: RequirementDisposition
    linked_plan_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_LINKS
    )

    _id = field_validator("requirement_id")(_pseudonym)

    @field_validator("linked_plan_ids")
    @classmethod
    def linked_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_pseudonym(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("linked plan identifiers must be unique and sorted")
        return checked

    @model_validator(mode="after")
    def disposition_agrees(self) -> "ConfirmedRequirementEvidence":
        if (self.disposition is RequirementDisposition.LINKED) != bool(
            self.linked_plan_ids
        ):
            raise ValueError("confirmed requirement links are incoherent")
        return self


class ConfirmedPlanEvidence(StrictModel):
    plan_id: str
    coordinate: PlanCoordinate

    _id = field_validator("plan_id")(_pseudonym)


class RequirementPlanEvidenceSnapshot(StrictModel):
    session_id: str
    source_window_fingerprint: str
    confirmation_id: str | None = None
    proposal_id: str | None = None
    producer_receipt: RequirementPlanProducerReceipt | None = None
    review_rubric_version: Literal[
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    ] | None = None
    requirements: tuple[ConfirmedRequirementEvidence, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    excluded_user_clauses: tuple[ExcludedRequirementClause, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    plan_items: tuple[ConfirmedPlanEvidence, ...] = Field(
        default=(), max_length=MAX_REQUIREMENT_PLAN_UNITS
    )
    complete_user_clause_classification: bool = False
    schema_version: Literal[REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION] = (
        REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION
    )
    policy_version: Literal[REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION] = (
        REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION
    )
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator("session_id", "source_window_fingerprint")(_pseudonym)

    @field_validator("confirmation_id", "proposal_id")
    @classmethod
    def optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def exact_authority_shape(self) -> "RequirementPlanEvidenceSnapshot":
        has_authority = self.confirmation_id is not None
        if has_authority != self.complete_user_clause_classification:
            raise ValueError("classification completeness requires confirmation authority")
        if has_authority != (self.proposal_id is not None):
            raise ValueError("confirmed snapshot requires its proposal")
        if has_authority != (self.producer_receipt is not None):
            raise ValueError("confirmed snapshot requires its producer claim receipt")
        if has_authority != (self.review_rubric_version is not None):
            raise ValueError("confirmed snapshot requires its review rubric")
        if not has_authority and (
            self.requirements or self.excluded_user_clauses or self.plan_items
        ):
            raise ValueError("unconfirmed evidence cannot enter the snapshot")
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        plan_ids = tuple(item.plan_id for item in self.plan_items)
        requirement_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.requirements
        )
        excluded_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.excluded_user_clauses
        )
        plan_coordinates = tuple(
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in self.plan_items
        )
        if requirement_ids != tuple(sorted(set(requirement_ids))):
            raise ValueError("snapshot requirements must be unique and sorted")
        if plan_ids != tuple(sorted(set(plan_ids))):
            raise ValueError("snapshot plan items must be unique and sorted")
        if len(set(requirement_coordinates)) != len(requirement_coordinates):
            raise ValueError("snapshot requirement coordinates must be unique")
        if (
            excluded_coordinates != tuple(sorted(set(excluded_coordinates)))
            or set(excluded_coordinates) & set(requirement_coordinates)
            or len(requirement_coordinates) + len(excluded_coordinates)
            > MAX_REQUIREMENT_PLAN_UNITS
        ):
            raise ValueError(
                "snapshot excluded user-clause coordinates must be disjoint and sorted"
            )
        if len(set(plan_coordinates)) != len(plan_coordinates):
            raise ValueError("snapshot plan coordinates must be unique")
        if any(
            link not in set(plan_ids)
            for item in self.requirements
            for link in item.linked_plan_ids
        ):
            raise ValueError("snapshot link references an absent plan")
        if sum(len(item.linked_plan_ids) for item in self.requirements) > (
            MAX_REQUIREMENT_PLAN_LINKS
        ):
            raise ValueError("snapshot requirement-plan links exceed their bound")
        return self

    def authority_identity(self) -> tuple[str, ...]:
        return (
            self.schema_version,
            self.policy_version,
            self.review_rubric_version or "none",
            self.confirmation_id or "none",
            self.proposal_id or "none",
        )


class RequirementPlanSourceContract(StrictModel):
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    projection_version: str
    contract_set_fingerprint: str
    source_manifest: RequirementPlanSourceManifest

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
    )(_pseudonym)
    _projection = field_validator("projection_version")(_safe_code)

    @model_validator(mode="after")
    def exact_manifest_binding(self) -> "RequirementPlanSourceContract":
        if (
            self.source_manifest.session_id != self.session_id
            or self.source_manifest.source_run_id != self.expected_source_run_id
            or self.source_manifest.source_window_fingerprint
            != self.source_window_fingerprint
        ):
            raise ValueError("source manifest is bound to another sealed run")
        return self


class RequirementPlanSourceAuthority(Protocol):
    def current_source_contract(self, session_id: str) -> RequirementPlanSourceContract: ...


class RequirementPlanSealedRunRepository(Protocol):
    def get_latest(self, session_id: str): ...


class SealedRunRequirementPlanSource:
    """Adapt the sealed model-ensemble repository to this file boundary."""

    def __init__(
        self,
        repository: RequirementPlanSealedRunRepository,
        review_contexts: InMemoryRequirementPlanReviewContextStore,
    ) -> None:
        self._repository = repository
        self._review_contexts = review_contexts

    def current_source_contract(self, session_id: str) -> RequirementPlanSourceContract:
        try:
            latest = self._repository.get_latest(session_id)
        except Exception:
            raise RequirementPlanPersistenceError(
                "sealed source publication could not be read"
            ) from None
        if latest is None or latest.receipt.metric_publication_v2 is None:
            raise RequirementPlanNotFoundError(
                "a sealed metric publication is required"
            )
        publication = latest.receipt.metric_publication_v2
        manifest = self._review_contexts.manifest(
            session_id=latest.session_id,
            source_run_id=latest.run_id,
            source_window_fingerprint=latest.input_fingerprint,
        )
        return RequirementPlanSourceContract(
            session_id=latest.session_id,
            expected_source_run_id=latest.run_id,
            source_window_fingerprint=latest.input_fingerprint,
            projection_version=publication.projection_version,
            contract_set_fingerprint=publication.contract_set_fingerprint,
            source_manifest=manifest,
        )


class RequirementPlanRepository(Protocol):
    def issue_proposal(
        self, proposal: RequirementPlanProposalRecord
    ) -> tuple[RequirementPlanProposalView, bool]: ...

    def decide(
        self, decision: RequirementPlanDecisionRecord
    ) -> tuple[RequirementPlanProposalView, bool]: ...

    def get_proposal(self, proposal_id: str) -> RequirementPlanProposalView | None: ...

    def list_proposals_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementPlanProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementPlanProposalView, ...],
        RequirementPlanProposalPageSnapshot,
    ]: ...

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementPlanEvidenceSnapshot: ...

    def latest_snapshot(self, session_id: str) -> RequirementPlanEvidenceSnapshot: ...


class RequirementPlanIdFactory(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class RequirementPlanEvidenceError(RuntimeError):
    code = "requirement_plan_evidence_failed"


class RequirementPlanInputError(RequirementPlanEvidenceError):
    code = "invalid_requirement_plan_evidence"


class RequirementPlanDefinitionsOutOfDateError(RequirementPlanInputError):
    code = "requirement_plan_evidence_definitions_out_of_date"


class RequirementPlanNotFoundError(RequirementPlanEvidenceError):
    code = "requirement_plan_evidence_not_found"


class RequirementPlanStaleWindowError(RequirementPlanEvidenceError):
    code = "requirement_plan_source_window_stale"


class RequirementPlanConflictError(RequirementPlanEvidenceError):
    code = "requirement_plan_evidence_conflict"


class RequirementPlanPersistenceError(RequirementPlanEvidenceError):
    code = "requirement_plan_evidence_persistence_failed"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _validate_json_budget(value: object, *, depth: int = 0) -> int:
    if depth > MAX_REQUIREMENT_PLAN_EVIDENCE_DEPTH:
        raise ValueError("requirement-plan evidence nesting exceeds its bound")
    if isinstance(value, float):
        raise ValueError("requirement-plan evidence rejects floating-point values")
    if isinstance(value, dict):
        return 1 + sum(
            _validate_json_budget(item, depth=depth + 1)
            for item in value.values()
        )
    if isinstance(value, list):
        return 1 + sum(
            _validate_json_budget(item, depth=depth + 1) for item in value
        )
    if value is None or isinstance(value, (str, int, bool)):
        return 1
    raise ValueError("requirement-plan evidence contains unsupported JSON")


def parse_requirement_plan_evidence_file(
    payload: bytes,
    *,
    now: datetime | None = None,
) -> tuple[RequirementPlanEvidenceFileV1, str]:
    if not payload or len(payload) > MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES:
        raise RequirementPlanInputError("requirement-plan file size is invalid")
    if payload.startswith(b"\xef\xbb\xbf") or b"\x00" in payload:
        raise RequirementPlanInputError("requirement-plan file encoding is invalid")
    try:
        data = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        if not isinstance(data, dict):
            raise ValueError("root must be an object")
        if _validate_json_budget(data) > MAX_REQUIREMENT_PLAN_EVIDENCE_ITEMS:
            raise ValueError("item count exceeds its bound")
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        if not hmac.compare_digest(payload, canonical):
            raise ValueError("JSON must use canonical encoding")
        projection = data.get("source_projection_version")
        if (
            isinstance(projection, str)
            and SAFE_VERSION_PATTERN.fullmatch(projection) is not None
            and projection
            not in {
                METRIC_PROJECTION_V2_VERSION_5,
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
        ):
            raise RequirementPlanDefinitionsOutOfDateError(
                "requirement-plan projection definitions are out of date"
            )
        parsed = RequirementPlanEvidenceFileV1.model_validate(data)
    except RequirementPlanDefinitionsOutOfDateError:
        raise
    except Exception as error:
        raise RequirementPlanInputError(
            "requirement-plan file failed strict validation"
        ) from error
    checked_at = datetime.now(UTC) if now is None else now
    try:
        checked_at = _utc(checked_at)
    except (TypeError, ValueError):
        raise RequirementPlanInputError("requirement-plan clock must be UTC") from None
    remaining = parsed.expires_at - checked_at
    if remaining <= timedelta(0) or remaining > MAX_REQUIREMENT_PLAN_EVIDENCE_LIFETIME:
        raise RequirementPlanInputError("requirement-plan expiry is outside policy")
    return parsed, hashlib.sha256(payload).hexdigest()


class RequirementPlanEvidenceService:
    """Import inert bundles and issue human-confirmed decomposition authority."""

    def __init__(
        self,
        repository: RequirementPlanRepository,
        source_authority: RequirementPlanSourceAuthority,
        identifiers: RequirementPlanIdFactory,
        *,
        review_contexts: InMemoryRequirementPlanReviewContextStore | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._source_authority = source_authority
        self._identifiers = identifiers
        self._review_contexts = review_contexts
        self._clock = clock

    def contract(self, session_id: str) -> RequirementPlanEvidenceContract:
        source = self._current_source(session_id)
        current = self._snapshot(session_id, source.source_window_fingerprint)
        return RequirementPlanEvidenceContract(
            session_id=session_id,
            expected_source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            expected_predecessor_confirmation_id=current.confirmation_id,
            contract_set_fingerprint=source.contract_set_fingerprint,
            metric_contract_fingerprint=(
                metric_contract_v2(REQUIREMENT_PLAN_METRIC_KEY).fingerprint
            ),
            source_projection_version=source.projection_version,
            clause_algorithm_spec=RequirementPlanClauseAlgorithmContract(),
            source_manifest=source.source_manifest,
            file_json_schema_sha256=(
                requirement_plan_evidence_file_json_schema_sha256()
            ),
            file_json_schema=requirement_plan_evidence_file_json_schema(),
        )

    def preview(
        self, *, session_id: str, payload: bytes, now: datetime | None = None
    ) -> RequirementPlanEvidencePreview:
        parsed, digest = parse_requirement_plan_evidence_file(payload, now=now)
        source = self._current_source(session_id)
        self._bind_file(parsed, source)
        current = self._snapshot(session_id, source.source_window_fingerprint)
        if parsed.expected_predecessor_confirmation_id != current.confirmation_id:
            raise RequirementPlanConflictError("requirement-plan predecessor changed")
        counts = self._counts(parsed)
        return RequirementPlanEvidencePreview(
            payload_sha256=digest,
            session_id=session_id,
            expected_source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            expected_predecessor_confirmation_id=(
                parsed.expected_predecessor_confirmation_id
            ),
            expires_at=parsed.expires_at,
            producer=parsed.producer,
            **counts,
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
    ) -> tuple[RequirementPlanProposalView, bool]:
        if confirmation != REQUIREMENT_PLAN_IMPORT_CONFIRMATION:
            raise RequirementPlanInputError("requirement-plan import confirmation is invalid")
        parsed, digest = parse_requirement_plan_evidence_file(payload, now=now)
        if (
            PSEUDONYM_PATTERN.fullmatch(expected_payload_sha256) is None
            or not hmac.compare_digest(digest, expected_payload_sha256)
        ):
            raise RequirementPlanInputError("requirement-plan preview binding changed")
        source = self._current_source(session_id)
        self._bind_file(parsed, source)
        current = self._snapshot(session_id, source.source_window_fingerprint)
        if parsed.expected_predecessor_confirmation_id != current.confirmation_id:
            raise RequirementPlanConflictError("requirement-plan predecessor changed")
        self._validate_idempotency(session_id, idempotency_key)
        idempotency_digest = self._identifiers.fingerprint(
            "requirement-plan-proposal-idempotency-v1",
            (session_id, idempotency_key),
        )
        proposal_id = self._identifiers.fingerprint(
            "requirement-plan-proposal-v1", (session_id, idempotency_digest)
        )
        command_fingerprint = self._identifiers.fingerprint(
            "requirement-plan-proposal-command-v1",
            (
                session_id,
                source.expected_source_run_id,
                source.source_window_fingerprint,
                parsed.expected_predecessor_confirmation_id or "none",
                digest,
            ),
        )
        record = RequirementPlanProposalRecord(
            proposal_id=proposal_id,
            session_id=session_id,
            source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            expected_predecessor_confirmation_id=(
                parsed.expected_predecessor_confirmation_id
            ),
            payload_sha256=digest,
            idempotency_key_digest=idempotency_digest,
            command_fingerprint=command_fingerprint,
            producer_receipt=RequirementPlanProducerReceipt(
                claim_fingerprint=self._identifiers.fingerprint(
                    "requirement-plan-producer-claim-v1",
                    (
                        parsed.producer.kind,
                        parsed.producer.producer_id,
                        parsed.producer.producer_version,
                        parsed.producer.model_id,
                        parsed.producer.authority,
                    ),
                )
            ),
            review_rubric_version=parsed.review_rubric_version,
            requirements=parsed.requirements,
            excluded_user_clauses=parsed.excluded_user_clauses,
            plan_items=parsed.plan_items,
            created_at=self._clock(),
        )
        try:
            return self._repository.issue_proposal(record)
        except RequirementPlanConflictError:
            raise
        except Exception:
            raise RequirementPlanPersistenceError(
                "requirement-plan proposal could not be stored"
            ) from None

    def decide(
        self,
        *,
        session_id: str,
        proposal_id: str,
        command: RequirementPlanDecisionCommand,
        idempotency_key: str,
    ) -> tuple[RequirementPlanProposalView, bool]:
        self._validate_idempotency(session_id, idempotency_key)
        try:
            _pseudonym(proposal_id)
            proposal = self._repository.get_proposal(proposal_id)
        except RequirementPlanEvidenceError:
            raise
        except Exception:
            raise RequirementPlanPersistenceError(
                "requirement-plan proposal could not be read"
            ) from None
        if proposal is None or proposal.proposal.session_id != session_id:
            raise RequirementPlanNotFoundError("requirement-plan proposal does not exist")
        if command.expected_source_run_id != proposal.proposal.source_run_id:
            raise RequirementPlanConflictError("requirement-plan proposal authority changed")
        idempotency_digest = self._identifiers.fingerprint(
            "requirement-plan-decision-idempotency-v1",
            (session_id, idempotency_key),
        )
        command_fingerprint = self._identifiers.fingerprint(
            "requirement-plan-decision-command-v1",
            (
                proposal_id,
                command.expected_source_run_id,
                command.decision.value,
                command.confirmation,
                command.review_receipt_id or "none",
                command.manifest_fingerprint or "none",
                command.reviewed_graph_fingerprint or "none",
                command.reviewed_candidate_set_fingerprint or "none",
                "acknowledged" if command.complete_review_acknowledged else "not-acknowledged",
            ),
        )
        decision_id = self._identifiers.fingerprint(
            "requirement-plan-decision-v1", (proposal_id, idempotency_digest)
        )
        if proposal.decision is not None:
            decision = proposal.decision
            if (
                decision.decision_id == decision_id
                and decision.idempotency_key_digest == idempotency_digest
                and decision.command_fingerprint == command_fingerprint
                and decision.decision is command.decision
            ):
                return proposal, False
            raise RequirementPlanConflictError("proposal already has another decision")
        source = self._current_source(session_id)
        if (
            source.expected_source_run_id != proposal.proposal.source_run_id
            or source.source_window_fingerprint
            != proposal.proposal.source_window_fingerprint
        ):
            raise RequirementPlanStaleWindowError("source authority changed")
        if command.decision is RequirementPlanDecisionKind.CONFIRM:
            if self._review_contexts is None:
                raise RequirementPlanPersistenceError(
                    "ephemeral requirement-plan review is unavailable"
                )
            assert command.review_receipt_id is not None
            assert command.manifest_fingerprint is not None
            assert command.reviewed_graph_fingerprint is not None
            assert command.reviewed_candidate_set_fingerprint is not None
            self._review_contexts.consume_review_receipt(
                review_receipt_id=command.review_receipt_id,
                proposal=proposal,
                manifest_fingerprint=command.manifest_fingerprint,
                reviewed_graph_fingerprint=command.reviewed_graph_fingerprint,
                reviewed_candidate_set_fingerprint=(
                    command.reviewed_candidate_set_fingerprint
                ),
            )
        current = self._snapshot(session_id, source.source_window_fingerprint)
        if (
            command.decision is RequirementPlanDecisionKind.CONFIRM
            and current.confirmation_id
            != proposal.proposal.expected_predecessor_confirmation_id
        ):
            raise RequirementPlanConflictError("requirement-plan predecessor changed")
        record = RequirementPlanDecisionRecord(
            decision_id=decision_id,
            proposal_id=proposal_id,
            session_id=session_id,
            decision=command.decision,
            idempotency_key_digest=idempotency_digest,
            command_fingerprint=command_fingerprint,
            decided_at=self._clock(),
        )
        try:
            return self._repository.decide(record)
        except RequirementPlanConflictError:
            raise
        except Exception:
            raise RequirementPlanPersistenceError(
                "requirement-plan decision could not be stored"
            ) from None

    def review_proposal(
        self,
        *,
        session_id: str,
        proposal_id: str,
        expected_source_run_id: str,
    ) -> RequirementPlanProposalReview:
        if self._review_contexts is None:
            raise RequirementPlanPersistenceError(
                "ephemeral requirement-plan review is unavailable"
            )
        try:
            _pseudonym(session_id)
            _pseudonym(proposal_id)
            _pseudonym(expected_source_run_id)
            proposal = self._repository.get_proposal(proposal_id)
        except RequirementPlanEvidenceError:
            raise
        except Exception:
            raise RequirementPlanPersistenceError(
                "requirement-plan proposal could not be read"
            ) from None
        if proposal is None or proposal.proposal.session_id != session_id:
            raise RequirementPlanNotFoundError(
                "requirement-plan proposal does not exist"
            )
        if proposal.proposal.source_run_id != expected_source_run_id:
            raise RequirementPlanConflictError(
                "requirement-plan review source changed"
            )
        if proposal.status is not RequirementPlanProposalStatus.PROPOSED:
            raise RequirementPlanConflictError(
                "only an undecided proposal can be reviewed"
            )
        source = self._current_source(session_id)
        if (
            proposal.proposal.source_run_id != source.expected_source_run_id
            or proposal.proposal.source_window_fingerprint
            != source.source_window_fingerprint
        ):
            raise RequirementPlanStaleWindowError(
                "requirement-plan proposal authority changed"
            )
        return self._review_contexts.review(proposal)

    def list_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementPlanProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementPlanProposalView, ...],
        RequirementPlanProposalPageSnapshot,
    ]:
        try:
            _pseudonym(session_id)
        except (TypeError, ValueError):
            raise RequirementPlanInputError("session identifier is invalid") from None
        if not 1 <= limit <= MAX_REQUIREMENT_PLAN_PAGE_SIZE or not 0 <= offset <= 1_000_000:
            raise RequirementPlanInputError("requirement-plan page is invalid")
        if snapshot is None and offset != 0:
            raise RequirementPlanInputError(
                "a stable requirement-plan page snapshot is required"
            )
        if snapshot is not None and offset > snapshot.total:
            raise RequirementPlanConflictError(
                "requirement-plan page offset exceeds its stable snapshot"
            )
        try:
            if snapshot is not None:
                expected_snapshot_id = self._proposal_page_snapshot_id(
                    session_id, snapshot
                )
                if not hmac.compare_digest(
                    snapshot.snapshot_id, expected_snapshot_id
                ):
                    raise RequirementPlanConflictError(
                        "requirement-plan page snapshot is invalid"
                    )
            proposals, resolved_snapshot = self._repository.list_proposals_page(
                session_id, limit=limit, offset=offset, snapshot=snapshot
            )
            signed_snapshot = resolved_snapshot.model_copy(
                update={
                    "snapshot_id": self._proposal_page_snapshot_id(
                        session_id, resolved_snapshot
                    )
                }
            )
            return proposals, signed_snapshot
        except RequirementPlanConflictError:
            raise
        except Exception:
            raise RequirementPlanPersistenceError(
                "requirement-plan proposals could not be read"
            ) from None

    def _proposal_page_snapshot_id(
        self,
        session_id: str,
        snapshot: RequirementPlanProposalPageSnapshot,
    ) -> str:
        return self._identifiers.fingerprint(
            "requirement-plan-proposal-page-snapshot-v1",
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

    def snapshot_for_window(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementPlanEvidenceSnapshot:
        try:
            _pseudonym(session_id)
            _pseudonym(source_window_fingerprint)
        except (TypeError, ValueError):
            raise RequirementPlanInputError("requirement-plan window is invalid") from None
        return self._snapshot(session_id, source_window_fingerprint)

    def _current_source(self, session_id: str) -> RequirementPlanSourceContract:
        try:
            _pseudonym(session_id)
            source = self._source_authority.current_source_contract(session_id)
        except RequirementPlanEvidenceError:
            raise
        except Exception:
            raise RequirementPlanPersistenceError(
                "sealed source publication could not be read"
            ) from None
        if source.session_id != session_id:
            raise RequirementPlanPersistenceError("sealed source belongs elsewhere")
        if (
            source.contract_set_fingerprint != metric_contract_v2_set_fingerprint()
            or source.projection_version
            not in {
                METRIC_PROJECTION_V2_VERSION_5,
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
        ):
            raise RequirementPlanDefinitionsOutOfDateError(
                "sealed source definitions are not supported"
            )
        return source

    def _snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementPlanEvidenceSnapshot:
        try:
            return self._repository.snapshot(session_id, source_window_fingerprint)
        except Exception:
            raise RequirementPlanPersistenceError(
                "requirement-plan snapshot could not be read"
            ) from None

    @staticmethod
    def _bind_file(
        parsed: RequirementPlanEvidenceFileV1,
        source: RequirementPlanSourceContract,
    ) -> None:
        if (
            parsed.session_id != source.session_id
            or parsed.expected_source_run_id != source.expected_source_run_id
            or parsed.source_window_fingerprint != source.source_window_fingerprint
            or parsed.source_projection_version != source.projection_version
        ):
            raise RequirementPlanStaleWindowError(
                "requirement-plan file is bound to another source"
            )
        try:
            validate_requirement_plan_coordinates(
                requirements=parsed.requirements,
                excluded_user_clauses=parsed.excluded_user_clauses,
                plan_items=parsed.plan_items,
                manifest=source.source_manifest,
            )
        except (KeyError, TypeError, ValueError):
            raise RequirementPlanInputError(
                "requirement-plan coordinates do not match the sealed source"
            ) from None

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
            raise RequirementPlanInputError(
                "idempotency key must be a content-free identifier"
            )

    @staticmethod
    def _counts(parsed: RequirementPlanEvidenceFileV1) -> dict[str, int]:
        return {
            "reviewed_user_clause_count": (
                len(parsed.requirements) + len(parsed.excluded_user_clauses)
            ),
            "active_requirement_count": len(parsed.requirements),
            "excluded_user_clause_count": len(
                parsed.excluded_user_clauses
            ),
            "plan_item_count": len(parsed.plan_items),
            "linked_active_requirement_count": sum(
                item.disposition is RequirementDisposition.LINKED
                for item in parsed.requirements
            ),
            "not_linked_active_requirement_count": sum(
                item.disposition is RequirementDisposition.NOT_LINKED
                for item in parsed.requirements
            ),
            "pending_active_requirement_count": sum(
                item.disposition is RequirementDisposition.PENDING
                for item in parsed.requirements
            ),
            "link_count": sum(len(item.plan_indexes) for item in parsed.requirements),
        }


__all__ = (
    "MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES",
    "MAX_REQUIREMENT_PLAN_PAGE_SIZE",
    "MAX_REQUIREMENT_PLAN_UNITS",
    "REQUIREMENT_PLAN_CLAUSE_ALGORITHM",
    "REQUIREMENT_PLAN_CANONICALIZATION",
    "REQUIREMENT_PLAN_DECISION_CONFIRMATION",
    "REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION",
    "REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION",
    "REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION",
    "REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES",
    "REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION",
    "REQUIREMENT_PLAN_IMPORT_CONFIRMATION",
    "REQUIREMENT_PLAN_METRIC_KEY",
    "REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION",
    "ConfirmedPlanEvidence",
    "ConfirmedRequirementEvidence",
    "ExcludedRequirementClause",
    "InMemoryRequirementPlanReviewContextStore",
    "PlanCoordinate",
    "RequirementCoordinate",
    "RequirementDisposition",
    "RequirementEvidenceEntry",
    "RequirementPlanConflictError",
    "RequirementPlanClauseAlgorithmContract",
    "RequirementPlanDecisionCommand",
    "RequirementPlanDecisionKind",
    "RequirementPlanDecisionRecord",
    "RequirementPlanDefinitionsOutOfDateError",
    "RequirementPlanEvidenceError",
    "RequirementPlanEvidenceContract",
    "RequirementPlanEvidenceFileV1",
    "RequirementPlanEvidencePreview",
    "RequirementPlanEvidenceService",
    "RequirementPlanEvidenceSnapshot",
    "RequirementPlanExclusionReason",
    "RequirementPlanIdFactory",
    "RequirementPlanInputError",
    "RequirementPlanNotFoundError",
    "RequirementPlanPersistenceError",
    "RequirementPlanProducer",
    "RequirementPlanProducerReceipt",
    "RequirementPlanReviewRubric",
    "RequirementPlanProposalRecord",
    "RequirementPlanProposalPageSnapshot",
    "RequirementPlanProposalReview",
    "RequirementPlanProposalStatus",
    "RequirementPlanProposalView",
    "RequirementPlanRepository",
    "RequirementPlanSourceAuthority",
    "RequirementPlanSourceContract",
    "RequirementPlanSourceManifest",
    "RequirementPlanStaleWindowError",
    "SealedRunRequirementPlanSource",
    "parse_requirement_plan_evidence_file",
    "requirement_plan_evidence_file_json_schema",
    "requirement_plan_evidence_file_json_schema_sha256",
    "requirement_plan_graph_fingerprint",
    "reviewable_message_clauses",
)
