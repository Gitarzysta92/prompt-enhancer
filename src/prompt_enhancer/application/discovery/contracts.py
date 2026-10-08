"""Privacy-safe application contracts for reviewable task discovery.

Discovery proposes groupings of already pseudonymized ``SafeSession`` metadata.
A candidate is not a task: it becomes one only through an explicit review
decision handled by a separate command boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import TYPE_CHECKING, Protocol, TypeAlias

from ...domain import (
    PSEUDONYM_PATTERN,
    SAFE_METRIC_TEXT_PATTERN,
    SAFE_VERSION_PATTERN,
    Provider,
    SignalDirection,
    SafeSession,
)

if TYPE_CHECKING:
    from .review import TaskReviewResult


def _require_pseudonym(value: str) -> None:
    if not isinstance(value, str) or not PSEUDONYM_PATTERN.fullmatch(value):
        raise ValueError("identifier must be a 64-character HMAC pseudonym")


def _require_safe_version(value: str) -> None:
    if not isinstance(value, str) or not SAFE_VERSION_PATTERN.fullmatch(value):
        raise ValueError("version must contain only safe identifier characters")


def _require_safe_code(value: str) -> None:
    if not isinstance(value, str) or not SAFE_METRIC_TEXT_PATTERN.fullmatch(value):
        raise ValueError("code must be a short content-free identifier")


def _require_probability(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between zero and one")


def _require_coverage(
    observed_count: int,
    eligible_count: int,
    coverage: float,
) -> None:
    if observed_count < 0 or eligible_count < 0:
        raise ValueError("evidence counts cannot be negative")
    if observed_count > eligible_count:
        raise ValueError("observed evidence cannot exceed eligible evidence")
    expected = 0.0 if eligible_count == 0 else observed_count / eligible_count
    if not math.isfinite(coverage) or abs(coverage - expected) > 1e-9:
        raise ValueError("coverage must equal observed evidence / eligible evidence")


@dataclass(frozen=True, slots=True)
class DiscoverySignal:
    """One content-free, versioned explanation for an adjacent-session relation.

    ``confidence`` is the deterministic strategy's directional strength, not a
    calibrated probability of task identity. Missing observations use ``None``;
    they are never silently represented as zero.
    """

    key: str
    version: int
    session_ids: tuple[str, str]
    direction: SignalDirection
    confidence: float | None
    weight: float
    evidence_code: str
    observed_count: int
    eligible_count: int
    coverage: float
    numeric_evidence: float | None = None
    evidence_unit: str | None = None

    def __post_init__(self) -> None:
        _require_safe_version(self.key)
        if self.version < 1:
            raise ValueError("signal version must be positive")
        if len(set(self.session_ids)) != 2:
            raise ValueError("a discovery signal must relate two distinct sessions")
        for session_id in self.session_ids:
            _require_pseudonym(session_id)
        if not isinstance(self.direction, SignalDirection):
            raise ValueError("signal direction is invalid")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("signal weight must be finite and positive")
        _require_safe_code(self.evidence_code)
        _require_coverage(self.observed_count, self.eligible_count, self.coverage)

        if self.direction is SignalDirection.UNKNOWN:
            if self.confidence is not None:
                raise ValueError("unknown signals cannot have confidence")
        elif self.confidence is None:
            raise ValueError("observed directional signals require confidence")
        else:
            _require_probability(self.confidence, "signal confidence")

        if self.confidence is not None and self.observed_count == 0:
            raise ValueError("confidence requires at least one observed item")
        if self.numeric_evidence is not None and not math.isfinite(
            self.numeric_evidence
        ):
            raise ValueError("numeric evidence must be finite")
        if self.evidence_unit is not None:
            _require_safe_version(self.evidence_unit)
        if (self.numeric_evidence is None) != (self.evidence_unit is None):
            raise ValueError("numeric evidence and its unit must be supplied together")


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """Canonical, safe input passed to a candidate pseudonym factory."""

    discovery_version: str
    provider: Provider
    installation_id: str
    project_id: str
    session_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_safe_version(self.discovery_version)
        if not isinstance(self.provider, Provider):
            raise ValueError("provider is invalid")
        _require_pseudonym(self.installation_id)
        _require_pseudonym(self.project_id)
        if not self.session_ids:
            raise ValueError("candidate identity requires at least one session")
        if self.session_ids != tuple(sorted(self.session_ids)):
            raise ValueError("candidate identity session IDs must be canonicalized")
        if len(set(self.session_ids)) != len(self.session_ids):
            raise ValueError("candidate identity cannot contain duplicate sessions")
        for session_id in self.session_ids:
            _require_pseudonym(session_id)


class CandidateIdFactory(Protocol):
    """Create a stable, domain-separated HMAC pseudonym for a candidate.

    Implementations receive only already-safe pseudonyms. Production factories
    must use a private local key; plain hashes and concatenated IDs are not valid
    production implementations.
    """

    def create(self, identity: CandidateIdentity) -> str:
        """Return a stable 64-character candidate pseudonym."""


class DiscoverySignalStrategy(Protocol):
    """Trusted deterministic strategy evaluated for adjacent safe sessions."""

    key: str
    version: int
    weight: float

    def evaluate(self, left: SafeSession, right: SafeSession) -> DiscoverySignal:
        """Return content-free evidence without reading provider state."""


@dataclass(frozen=True, slots=True)
class TaskCandidate:
    """Reviewable grouping proposal; deliberately distinct from a confirmed task."""

    candidate_id: str
    discovery_version: str
    provider: Provider
    installation_id: str
    project_id: str
    session_ids: tuple[str, ...]
    signals: tuple[DiscoverySignal, ...]
    confidence: float | None
    observed_count: int
    eligible_count: int
    coverage: float

    def __post_init__(self) -> None:
        _require_pseudonym(self.candidate_id)
        _require_safe_version(self.discovery_version)
        if not isinstance(self.provider, Provider):
            raise ValueError("provider is invalid")
        _require_pseudonym(self.installation_id)
        _require_pseudonym(self.project_id)
        if not self.session_ids:
            raise ValueError("a candidate requires at least one session")
        if len(set(self.session_ids)) != len(self.session_ids):
            raise ValueError("a candidate cannot contain duplicate sessions")
        for session_id in self.session_ids:
            _require_pseudonym(session_id)
        allowed_session_ids = set(self.session_ids)
        for signal in self.signals:
            if not set(signal.session_ids) <= allowed_session_ids:
                raise ValueError("candidate evidence references an external session")
        _require_coverage(self.observed_count, self.eligible_count, self.coverage)
        if self.confidence is not None:
            _require_probability(self.confidence, "candidate confidence")
        if self.observed_count == 0 and self.confidence is not None:
            raise ValueError("candidate confidence requires observed evidence")


@dataclass(frozen=True, slots=True)
class DiscoveryBoundary:
    """Reviewable evidence explaining a proposed split between two candidates."""

    left_candidate_id: str
    right_candidate_id: str
    left_session_id: str
    right_session_id: str
    signals: tuple[DiscoverySignal, ...]
    confidence: float | None
    observed_count: int
    eligible_count: int
    coverage: float

    def __post_init__(self) -> None:
        for value in (
            self.left_candidate_id,
            self.right_candidate_id,
            self.left_session_id,
            self.right_session_id,
        ):
            _require_pseudonym(value)
        if self.left_candidate_id == self.right_candidate_id:
            raise ValueError("a boundary must separate distinct candidates")
        _require_coverage(self.observed_count, self.eligible_count, self.coverage)
        if self.confidence is not None:
            _require_probability(self.confidence, "boundary confidence")
        if self.observed_count == 0 and self.confidence is not None:
            raise ValueError("boundary confidence requires observed evidence")


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    """Deterministically ordered candidates and within-project boundaries."""

    discovery_version: str
    candidates: tuple[TaskCandidate, ...]
    boundaries: tuple[DiscoveryBoundary, ...]

    def __post_init__(self) -> None:
        _require_safe_version(self.discovery_version)
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("a discovery batch cannot contain duplicate candidates")
        session_ids = tuple(
            session_id
            for candidate in self.candidates
            for session_id in candidate.session_ids
        )
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("a session cannot belong to multiple candidates")
        known_candidates = set(candidate_ids)
        for boundary in self.boundaries:
            if {
                boundary.left_candidate_id,
                boundary.right_candidate_id,
            } - known_candidates:
                raise ValueError("a boundary references an unknown candidate")


class TaskCategory(StrEnum):
    BUG_FIX = "bug_fix"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    RESEARCH_DESIGN = "research_design"
    UNKNOWN = "unknown"


class RejectionReason(StrEnum):
    NOT_A_TASK = "not_a_task"
    WRONG_GROUPING = "wrong_grouping"
    DUPLICATE = "duplicate"
    OTHER = "other"


class TaskDecisionKind(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MERGE = "merge"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class AcceptCandidate:
    candidate_id: str
    expected_discovery_version: str
    task_category: TaskCategory = TaskCategory.UNKNOWN

    def __post_init__(self) -> None:
        _require_pseudonym(self.candidate_id)
        _require_safe_version(self.expected_discovery_version)
        if not isinstance(self.task_category, TaskCategory):
            raise ValueError("task category is invalid")


@dataclass(frozen=True, slots=True)
class RejectCandidate:
    candidate_id: str
    expected_discovery_version: str
    reason: RejectionReason

    def __post_init__(self) -> None:
        _require_pseudonym(self.candidate_id)
        _require_safe_version(self.expected_discovery_version)
        if not isinstance(self.reason, RejectionReason):
            raise ValueError("rejection reason is invalid")


@dataclass(frozen=True, slots=True)
class MergeCandidates:
    candidate_ids: tuple[str, ...]
    expected_discovery_version: str
    task_category: TaskCategory = TaskCategory.UNKNOWN

    def __post_init__(self) -> None:
        if len(self.candidate_ids) < 2:
            raise ValueError("merge requires at least two candidates")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("merge cannot contain duplicate candidates")
        for candidate_id in self.candidate_ids:
            _require_pseudonym(candidate_id)
        _require_safe_version(self.expected_discovery_version)
        if not isinstance(self.task_category, TaskCategory):
            raise ValueError("task category is invalid")


@dataclass(frozen=True, slots=True)
class SplitCandidate:
    candidate_id: str
    partitions: tuple[tuple[str, ...], ...]
    expected_discovery_version: str
    task_categories: tuple[TaskCategory, ...] = ()

    def __post_init__(self) -> None:
        _require_pseudonym(self.candidate_id)
        _require_safe_version(self.expected_discovery_version)
        if len(self.partitions) < 2:
            raise ValueError("split requires at least two partitions")
        flattened: list[str] = []
        for partition in self.partitions:
            if not partition:
                raise ValueError("split partitions cannot be empty")
            for session_id in partition:
                _require_pseudonym(session_id)
                flattened.append(session_id)
        if len(flattened) != len(set(flattened)):
            raise ValueError("a session cannot appear in multiple split partitions")
        if self.task_categories and len(self.task_categories) != len(self.partitions):
            raise ValueError("split categories must align with partitions")
        if any(
            not isinstance(category, TaskCategory)
            for category in self.task_categories
        ):
            raise ValueError("task category is invalid")


TaskDecisionCommand: TypeAlias = (
    AcceptCandidate | RejectCandidate | MergeCandidates | SplitCandidate
)


class TaskDecisionService(Protocol):
    """Command boundary implemented by the transactional task-review service.

    Implementations must re-read candidates, enforce optimistic discovery-version
    checks, validate merge scopes and exact split membership, create immutable task
    revisions, and never mutate provider sessions.
    """

    def apply(
        self,
        command: TaskDecisionCommand,
        *,
        idempotency_key: str,
    ) -> TaskReviewResult:
        """Apply one explicit local review decision transactionally."""
