"""Metadata-only projection from estimator scope into the deterministic router.

This boundary intentionally contains no source text, authored label, expected
outcome, model judgment, or score.  It only binds an exact metric question to
the existing objective scope-router metadata contract.
"""

from __future__ import annotations

from typing import Literal
import hashlib
import json

from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from ..analysis.scope_router_contracts import (
    MAX_REQUIREMENT_REFERENCES,
    MetricApplicability,
    ScopeEvidenceAvailabilityReceipt,
    ScopeEvidenceKind,
    ScopeExtractionState,
    ScopeRequirementEvidenceLink,
    ScopeRouterInput,
)


RUNTIME_SCOPE_PROJECTION_VERSION = "runtime-scope-projection-v1"


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("scope projection identifiers must be SHA-256 pseudonyms")
    return value


class RuntimeScopeProjection(StrictModel):
    """Exact, content-free scope metadata for one metric question."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> RuntimeScopeProjection:
        if update:
            raise TypeError("scope projections forbid update-copy bypass")
        return super().model_copy(deep=deep)

    contract_version: Literal[RUNTIME_SCOPE_PROJECTION_VERSION] = (
        RUNTIME_SCOPE_PROJECTION_VERSION
    )
    metric_question_fingerprint: str
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
    metadata_only: Literal[True] = True
    model_output_allowed: Literal[False] = False
    authored_label_allowed: Literal[False] = False

    _safe_required_ids = field_validator(
        "metric_question_fingerprint",
        "target_project_id",
        "target_session_id",
        "target_revision_id",
        "target_requirement_id",
        "target_requirement_version_id",
    )(_digest)

    @field_validator(
        "comparison_project_id",
        "comparison_session_id",
        "comparison_revision_id",
        "superseding_revision_id",
    )
    @classmethod
    def safe_optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def validate_router_projection(self) -> RuntimeScopeProjection:
        self.to_router_input()
        return self

    def to_router_input(self) -> ScopeRouterInput:
        """Project only the fields already accepted by the deterministic router."""

        links = tuple(
            ScopeRequirementEvidenceLink.model_validate(
                item.model_dump(mode="python")
            )
            for item in self.evidence_requirement_links
        )
        receipts = tuple(
            ScopeEvidenceAvailabilityReceipt.model_validate(
                item.model_dump(mode="python")
            )
            for item in self.evidence_receipts
        )
        return ScopeRouterInput(
            metric_applicability=self.metric_applicability,
            target_project_id=self.target_project_id,
            target_session_id=self.target_session_id,
            target_revision_id=self.target_revision_id,
            target_revision_ordinal=self.target_revision_ordinal,
            target_requirement_id=self.target_requirement_id,
            target_requirement_version_id=self.target_requirement_version_id,
            requirement_observed_sequence=self.requirement_observed_sequence,
            comparison_project_id=self.comparison_project_id,
            comparison_session_id=self.comparison_session_id,
            comparison_revision_id=self.comparison_revision_id,
            comparison_revision_ordinal=self.comparison_revision_ordinal,
            evidence_observed_sequence=self.evidence_observed_sequence,
            evidence_requirement_links=links,
            extraction_state=self.extraction_state,
            required_evidence_kinds=self.required_evidence_kinds,
            evidence_receipts=receipts,
            superseding_revision_id=self.superseding_revision_id,
            superseding_revision_ordinal=self.superseding_revision_ordinal,
        )

    @property
    def canonical_fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def project_scope_router_input(projection: RuntimeScopeProjection) -> ScopeRouterInput:
    """Named adapter used by composition roots without importing any text packet."""

    projection = RuntimeScopeProjection.model_validate(
        projection.model_dump(mode="python")
    )
    return projection.to_router_input()


__all__ = [
    "RuntimeScopeProjection",
    "project_scope_router_input",
]
