"""Content-free contracts for deterministic scope and temporal routing.

The router operates only on opaque identifiers and objective metadata.  Authored
labels, prompt text, evidence bodies, model judgments, and expected outcomes are
deliberately absent from this boundary.
"""

from __future__ import annotations

from enum import StrEnum
import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel


SCOPE_ROUTER_INPUT_VERSION = "scope-router-input-v1"
SCOPE_ROUTER_OUTPUT_VERSION = "scope-router-output-v1"
MAX_REQUIREMENT_REFERENCES = 64
MAX_EVIDENCE_REFERENCES_PER_KIND = 64


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("scope-router identifiers must be opaque SHA-256 pseudonyms")
    return value


def _canonical_pseudonyms(values: tuple[str, ...]) -> tuple[str, ...]:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("scope-router identifiers must be unique and sorted")
    return tuple(_pseudonym(value) for value in values)


class ScopeCompatibilityState(StrEnum):
    COMPATIBLE = "compatible"
    DIFFERENT_SCOPE = "different_scope"
    SUPERSEDED = "superseded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class ScopeRouterReason(StrEnum):
    EXACT_SCOPE_EVIDENCE_READY = "exact_scope_evidence_ready"
    METRIC_NOT_APPLICABLE = "metric_not_applicable"
    TARGET_REVISION_SUPERSEDED = "target_revision_superseded"
    APPLICABILITY_UNKNOWN = "applicability_unknown"
    COMPARISON_SCOPE_MISSING = "comparison_scope_missing"
    PROJECT_MISMATCH = "project_mismatch"
    SESSION_MISMATCH = "session_mismatch"
    REVISION_IDENTITY_MISMATCH = "revision_identity_mismatch"
    FUTURE_REVISION_EVIDENCE = "future_revision_evidence"
    REQUIREMENT_LINK_MISSING = "requirement_link_missing"
    REQUIREMENT_MISMATCH = "requirement_mismatch"
    REQUIREMENT_VERSION_LINK_MISSING = "requirement_version_link_missing"
    REQUIREMENT_VERSION_MISMATCH = "requirement_version_mismatch"
    EVIDENCE_PRECEDES_REQUIREMENT = "evidence_precedes_requirement"
    EXTRACTION_INCOMPLETE = "extraction_incomplete"
    REQUIRED_EVIDENCE_ABSENT = "required_evidence_absent"
    EVIDENCE_AVAILABILITY_UNKNOWN = "evidence_availability_unknown"
    REQUIRED_EVIDENCE_UNSUPPORTED = "required_evidence_unsupported"
    EVIDENCE_EXTRACTION_FAILED = "evidence_extraction_failed"


class MetricApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ScopeExtractionState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ScopeEvidenceKind(StrEnum):
    ACTION = "action"
    DECISION = "decision"
    FEEDBACK = "feedback"
    VERIFICATION = "verification"


class ScopeEvidenceAvailability(StrEnum):
    AVAILABLE = "available"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class EvidenceCoverageState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"
    NOT_APPLICABLE = "not_applicable"


class ScopeEvidenceAvailabilityReceipt(StrictModel):
    kind: ScopeEvidenceKind
    availability: ScopeEvidenceAvailability
    evidence_reference_ids: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_EVIDENCE_REFERENCES_PER_KIND,
    )

    _validate_references = field_validator("evidence_reference_ids")(
        _canonical_pseudonyms
    )

    @model_validator(mode="after")
    def references_match_availability(self) -> ScopeEvidenceAvailabilityReceipt:
        if self.availability is ScopeEvidenceAvailability.AVAILABLE:
            if not self.evidence_reference_ids:
                raise ValueError("available evidence requires an opaque reference")
        elif self.evidence_reference_ids:
            raise ValueError("non-available evidence cannot claim references")
        return self


class ScopeRequirementEvidenceLink(StrictModel):
    """Opaque evidence linkage to one immutable requirement version."""

    requirement_id: str
    requirement_version_id: str | None = None

    _validate_requirement_id = field_validator("requirement_id")(_pseudonym)
    _validate_requirement_version = field_validator("requirement_version_id")(
        lambda value: None if value is None else _pseudonym(value)
    )


class ScopeRouterInput(StrictModel):
    """Label-blind objective metadata for one target/evidence comparison."""

    contract_version: Literal["scope-router-input-v1"] = SCOPE_ROUTER_INPUT_VERSION
    metric_applicability: MetricApplicability

    target_project_id: str
    target_session_id: str
    target_revision_id: str
    target_revision_ordinal: int = Field(ge=0)
    target_requirement_id: str
    target_requirement_version_id: str
    requirement_observed_sequence: int = Field(ge=0)

    comparison_project_id: str | None = None
    comparison_session_id: str | None = None
    comparison_revision_id: str | None = None
    comparison_revision_ordinal: int | None = Field(default=None, ge=0)
    evidence_observed_sequence: int | None = Field(default=None, ge=0)
    evidence_requirement_links: tuple[ScopeRequirementEvidenceLink, ...] = Field(
        default=(),
        max_length=MAX_REQUIREMENT_REFERENCES,
    )

    extraction_state: ScopeExtractionState
    required_evidence_kinds: tuple[ScopeEvidenceKind, ...] = Field(
        min_length=1,
        max_length=len(ScopeEvidenceKind),
    )
    evidence_receipts: tuple[ScopeEvidenceAvailabilityReceipt, ...] = Field(
        default=(),
        max_length=len(ScopeEvidenceKind),
    )

    superseding_revision_id: str | None = None
    superseding_revision_ordinal: int | None = Field(default=None, ge=0)

    _validate_target_ids = field_validator(
        "target_project_id",
        "target_session_id",
        "target_revision_id",
        "target_requirement_id",
        "target_requirement_version_id",
    )(_pseudonym)
    _validate_optional_ids = field_validator(
        "comparison_project_id",
        "comparison_session_id",
        "comparison_revision_id",
        "superseding_revision_id",
    )(lambda value: None if value is None else _pseudonym(value))

    @field_validator("evidence_requirement_links")
    @classmethod
    def canonical_requirement_links(
        cls,
        values: tuple[ScopeRequirementEvidenceLink, ...],
    ) -> tuple[ScopeRequirementEvidenceLink, ...]:
        keys = tuple(link.requirement_id for link in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError(
                "evidence requirement links must have unique sorted requirement ids"
            )
        return values

    @field_validator("required_evidence_kinds")
    @classmethod
    def canonical_required_kinds(
        cls,
        values: tuple[ScopeEvidenceKind, ...],
    ) -> tuple[ScopeEvidenceKind, ...]:
        if values != tuple(sorted(values, key=lambda item: item.value)):
            raise ValueError("required evidence kinds must be sorted")
        if len(values) != len(set(values)):
            raise ValueError("required evidence kinds must be unique")
        return values

    @field_validator("evidence_receipts")
    @classmethod
    def canonical_receipts(
        cls,
        values: tuple[ScopeEvidenceAvailabilityReceipt, ...],
    ) -> tuple[ScopeEvidenceAvailabilityReceipt, ...]:
        kinds = tuple(receipt.kind for receipt in values)
        if kinds != tuple(sorted(kinds, key=lambda item: item.value)):
            raise ValueError("evidence receipts must be sorted by kind")
        if len(kinds) != len(set(kinds)):
            raise ValueError("evidence receipts must have unique kinds")
        return values

    @model_validator(mode="after")
    def validate_relations(self) -> ScopeRouterInput:
        required = set(self.required_evidence_kinds)
        if any(receipt.kind not in required for receipt in self.evidence_receipts):
            raise ValueError("evidence receipts must describe required evidence kinds")

        superseding_pair = (
            self.superseding_revision_id,
            self.superseding_revision_ordinal,
        )
        if (superseding_pair[0] is None) != (superseding_pair[1] is None):
            raise ValueError("superseding revision identity must be complete")
        if self.superseding_revision_ordinal is not None:
            if self.superseding_revision_ordinal <= self.target_revision_ordinal:
                raise ValueError("superseding revision must be later than the target")
            if self.superseding_revision_id == self.target_revision_id:
                raise ValueError("superseding revision must have a distinct identity")

        if (
            self.comparison_revision_id == self.target_revision_id
            and self.comparison_revision_ordinal is not None
            and self.comparison_revision_ordinal != self.target_revision_ordinal
        ):
            raise ValueError("one revision identity cannot have multiple ordinals")

        if self.extraction_state is ScopeExtractionState.COMPLETE:
            receipt_kinds = {receipt.kind for receipt in self.evidence_receipts}
            if receipt_kinds != required:
                raise ValueError(
                    "complete extraction requires a receipt for every required kind"
                )
        return self


class ScopeEvidenceCoverage(StrictModel):
    state: EvidenceCoverageState
    required_kind_count: int = Field(ge=1, le=len(ScopeEvidenceKind))
    available_kind_count: int | None = Field(default=None, ge=0)
    ratio: float | None = None

    @model_validator(mode="after")
    def values_match_state(self) -> ScopeEvidenceCoverage:
        if self.state is EvidenceCoverageState.KNOWN:
            if self.available_kind_count is None or self.ratio is None:
                raise ValueError("known coverage requires an exact count and ratio")
            if self.available_kind_count > self.required_kind_count:
                raise ValueError("available evidence cannot exceed required evidence")
            if not math.isfinite(self.ratio) or not 0.0 <= self.ratio <= 1.0:
                raise ValueError("known coverage ratio must be a finite unit value")
            expected = self.available_kind_count / self.required_kind_count
            if not math.isclose(self.ratio, expected, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("coverage ratio must match the exact counts")
        elif self.available_kind_count is not None or self.ratio is not None:
            raise ValueError("non-known coverage cannot imply a zero or percentage")
        return self


class ScopeRouterOutput(StrictModel):
    contract_version: Literal["scope-router-output-v1"] = SCOPE_ROUTER_OUTPUT_VERSION
    router_version: Literal["deterministic-scope-router-v1"]
    state: ScopeCompatibilityState
    reason: ScopeRouterReason
    evidence_coverage: ScopeEvidenceCoverage

    @model_validator(mode="after")
    def state_reason_and_coverage_are_closed(self) -> ScopeRouterOutput:
        different_scope_reasons = {
            ScopeRouterReason.PROJECT_MISMATCH,
            ScopeRouterReason.SESSION_MISMATCH,
            ScopeRouterReason.REVISION_IDENTITY_MISMATCH,
            ScopeRouterReason.FUTURE_REVISION_EVIDENCE,
            ScopeRouterReason.REQUIREMENT_MISMATCH,
            ScopeRouterReason.REQUIREMENT_VERSION_MISMATCH,
            ScopeRouterReason.EVIDENCE_PRECEDES_REQUIREMENT,
        }
        unknown_insufficient_reasons = {
            ScopeRouterReason.APPLICABILITY_UNKNOWN,
            ScopeRouterReason.COMPARISON_SCOPE_MISSING,
            ScopeRouterReason.REQUIREMENT_LINK_MISSING,
            ScopeRouterReason.REQUIREMENT_VERSION_LINK_MISSING,
            ScopeRouterReason.EXTRACTION_INCOMPLETE,
            ScopeRouterReason.EVIDENCE_AVAILABILITY_UNKNOWN,
            ScopeRouterReason.REQUIRED_EVIDENCE_UNSUPPORTED,
            ScopeRouterReason.EVIDENCE_EXTRACTION_FAILED,
        }
        coverage = self.evidence_coverage
        if self.state is ScopeCompatibilityState.COMPATIBLE:
            if (
                self.reason is not ScopeRouterReason.EXACT_SCOPE_EVIDENCE_READY
                or coverage.state is not EvidenceCoverageState.KNOWN
                or coverage.available_kind_count != coverage.required_kind_count
                or coverage.ratio != 1.0
            ):
                raise ValueError("compatible output requires exact full evidence")
        elif self.state is ScopeCompatibilityState.DIFFERENT_SCOPE:
            if (
                self.reason not in different_scope_reasons
                or coverage.state is not EvidenceCoverageState.INCOMPATIBLE
            ):
                raise ValueError("different-scope output has an invalid reason or coverage")
        elif self.state is ScopeCompatibilityState.SUPERSEDED:
            if (
                self.reason is not ScopeRouterReason.TARGET_REVISION_SUPERSEDED
                or coverage.state is not EvidenceCoverageState.NOT_APPLICABLE
            ):
                raise ValueError("superseded output has an invalid reason or coverage")
        elif self.state is ScopeCompatibilityState.NOT_APPLICABLE:
            if (
                self.reason is not ScopeRouterReason.METRIC_NOT_APPLICABLE
                or coverage.state is not EvidenceCoverageState.NOT_APPLICABLE
            ):
                raise ValueError("not-applicable output has an invalid reason or coverage")
        elif self.reason is ScopeRouterReason.REQUIRED_EVIDENCE_ABSENT:
            if (
                coverage.state is not EvidenceCoverageState.KNOWN
                or coverage.available_kind_count is None
                or coverage.available_kind_count >= coverage.required_kind_count
            ):
                raise ValueError("known evidence absence requires partial known coverage")
        elif (
            self.reason not in unknown_insufficient_reasons
            or coverage.state is not EvidenceCoverageState.UNKNOWN
        ):
            raise ValueError(
                "insufficient-evidence output has an invalid reason or coverage"
            )
        return self


__all__ = [
    "EvidenceCoverageState",
    "MetricApplicability",
    "SCOPE_ROUTER_INPUT_VERSION",
    "SCOPE_ROUTER_OUTPUT_VERSION",
    "ScopeCompatibilityState",
    "ScopeEvidenceAvailability",
    "ScopeEvidenceAvailabilityReceipt",
    "ScopeEvidenceCoverage",
    "ScopeEvidenceKind",
    "ScopeExtractionState",
    "ScopeRequirementEvidenceLink",
    "ScopeRouterInput",
    "ScopeRouterOutput",
    "ScopeRouterReason",
]
