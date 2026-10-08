"""Explicit local measured and predictive analysis for one redacted session window."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Callable, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import DataTier, PSEUDONYM_PATTERN, Provider, SAFE_VERSION_PATTERN, StrictModel
from ..providers import DecoderDescriptor
from ..runtime_cancellation import RuntimeCleanupUnconfirmed, RuntimeCooperativeStop
from .evidence_contracts import (
    ActionState,
    EphemeralTypedEvidenceProjection,
    validate_projection_descriptor,
)
from .declared_task_profiles import (
    DeclaredTaskProfileRecord,
    DeclaredTaskProfileRepository,
    apply_declared_task_profile,
)
from .model_ensemble import (
    EnsembleChunkPlan,
    EnsembleMetricSpec,
    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
    MODEL_ENSEMBLE_MODEL_COUNT,
    SessionModelEnsembleReceipt,
    SessionModelEnsembleTypedMetricReceipt,
    build_ensemble_chunks,
    coaching_ensemble_metric_specs,
)
from .objective_metric_projection import (
    OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
    project_objective_metric_overrides_v4,
)
from .metric_lifecycle_evidence import MetricLifecycleEvidenceSnapshot
from .metric_contract_v2 import METRIC_CONTRACTS_V2, MetricValueStateV2
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
    MetricStateV2,
    reviewed_requirement_plan_denominator_is_authoritative,
)
from .metric_projection_v6 import (
    REASON_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED,
    REASON_REQUIREMENT_PLAN_INVALID,
    REASON_REQUIREMENT_PLAN_UNAVAILABLE,
)
from .metric_projection_v7 import (
    REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
    REASON_REQUIREMENT_ACTION_INVALID,
    REASON_REQUIREMENT_ACTION_OVERFLOW,
    REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE,
    REASON_REQUIREMENT_ACTION_UNAVAILABLE,
    REASON_REVIEWED_REQUIREMENT_ACTION_LINKS,
)
from .metric_projection_v8 import project_metric_states_v8
from .metric_publication_v2 import MetricPublicationV2, publish_metric_states_v2
from .provider_evidence import (
    RequirementActionCandidateManifestOverflowError,
    bind_semantic_unit_opportunities,
)
from .requirement_action_evidence import (
    InMemoryRequirementActionReviewContextStore,
    RequirementActionCandidateManifest,
    RequirementActionEvidenceSnapshot,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_descriptor_matches_candidate_metadata,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_plan_snapshot_fingerprint,
)
from .requirement_plan_evidence import (
    InMemoryRequirementPlanReviewContextStore,
    REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION,
    REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    RequirementDisposition,
    RequirementPlanEvidenceSnapshot,
)
from .requirement_verification_evidence import (
    AppIssuedRequirementVerificationOpportunitySet,
    MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES,
    REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
    REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
    REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
    REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
    REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
    REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
    VERIFIED_REQUIREMENT_METRIC_KEY,
    RequirementAcceptanceOutcome,
    RequirementVerificationEvidenceSet,
    RequirementVerificationOutcome,
    issue_requirement_verification_opportunities,
    validate_requirement_verification_evidence_set,
)
from .requirement_verification_persistence import (
    REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
    CurrentRequirementVerificationEvidenceReader,
    RequirementVerificationEvidenceSnapshot,
)
from .semantic_units import (
    SemanticUnitProjection,
    SemanticUnitReconciliation,
    SemanticUnitReconciler,
)
from .coaching_baselines import (
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    DEFAULT_COACHING_METRIC_ENGINE,
)
from .session_text_service import (
    SessionTextAnalysisAccessPolicy,
    SessionTextAnalysisCompatibilityPolicy,
    SessionTextAnalysisIdFactory,
    SessionTextAnalysisSourceFactory,
)
from .text_analysis_presets import COACHING_PROFILE_V1
from .text_baselines import TextMetricEngine
from .text_contracts import P1LocalAnalysisGrant, P1TextAnalysisInput, TextTaskProfile
from .text_source import (
    TEXT_ANALYSIS_PROVIDERS,
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceAccessGrant,
    TextSourceFailureReason,
    TextSourceReadError,
)


MODEL_ENSEMBLE_CONFIRMATION = "run_local_metric_cascade_on_selected_redacted_text"
LEGACY_MODEL_ENSEMBLE_CONFIRMATION = "run_ten_local_models_on_selected_redacted_text"
MODEL_ENSEMBLE_POLICY_VERSION = "explicit-local-shadow-ensemble-v1"
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION = (
    "coaching-profile-v1-unconfigured"
)
COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION = "server-preset-v1"
REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION = "requirement-plan-unavailable-v1"
REQUIREMENT_PLAN_AWAITING_REVIEW_SCHEMA_VERSION = (
    "requirement-plan-awaiting-review-v1"
)
REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION = "reviewed-requirement-plan-v1"
REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION = (
    "requirement-action-unavailable-v1"
)
REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION = (
    "requirement-action-awaiting-review-v1"
)
REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION = (
    "requirement-action-candidate-manifest-overflow-v1"
)
REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION = (
    "requirement-action-candidate-source-incomplete-v1"
)
REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION = (
    "requirement-action-binding-invalid-v1"
)
REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION = (
    "reviewed-requirement-action-v1"
)


def requirement_plan_unavailable_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-plan-binding-v1",
                "source": "unavailable",
                "schema_version": REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION,
                "policy_version": REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT = (
    "30f6b309825c563a881ed1b7587072222e3cb33ca70f7bff274ba968cb067641"
)
if requirement_plan_unavailable_fingerprint() != REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT:
    raise RuntimeError(
        "requirement-plan unavailable marker changed without a new identity"
    )


def requirement_plan_awaiting_review_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-plan-binding-v1",
                "source": "awaiting_review",
                "schema_version": REQUIREMENT_PLAN_AWAITING_REVIEW_SCHEMA_VERSION,
                "policy_version": REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT = (
    "843a2a5154affde7f7cddc19137dfcdfa8253d9f541c98b6e2cdabd930401ff2"
)
if (
    requirement_plan_awaiting_review_fingerprint()
    != REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT
):
    raise RuntimeError(
        "requirement-plan awaiting-review marker changed without a new identity"
    )


def requirement_action_unavailable_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-action-binding-v1",
                "source": "unavailable",
                "schema_version": REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION,
                "policy_version": REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT = (
    "9059e785839871abf94e1fea1c86c48e737621047a526cd3c9e94099a5b5e07f"
)
if (
    requirement_action_unavailable_fingerprint()
    != REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT
):
    raise RuntimeError(
        "requirement-action unavailable marker changed without a new identity"
    )


def requirement_action_awaiting_review_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-action-binding-v1",
                "source": "awaiting_review",
                "schema_version": (
                    REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION
                ),
                "policy_version": REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT = (
    "0ca65041b98be25e41cbbba908641f116f0e81b45416f89fd7ddf177489add4a"
)
if (
    requirement_action_awaiting_review_fingerprint()
    != REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT
):
    raise RuntimeError(
        "requirement-action awaiting-review marker changed without a new identity"
    )


def requirement_action_candidate_manifest_overflow_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-action-binding-v1",
                "source": "candidate_manifest_overflow",
                "schema_version": (
                    REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION
                ),
                "policy_version": REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT = (
    "528224b052ffbec5c2b404b8970ab2ced61b84bc39cc20d70fd77320a059875f"
)
if (
    requirement_action_candidate_manifest_overflow_fingerprint()
    != REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT
):
    raise RuntimeError(
        "requirement-action candidate-overflow marker changed without a new identity"
    )


def requirement_action_candidate_source_incomplete_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-action-binding-v1",
                "source": "candidate_source_incomplete",
                "schema_version": (
                    REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION
                ),
                "policy_version": REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT = (
    "d44bd4fa494e3123c7cb6f23ada45473204a55736c8a0ae9e5305ba30d91c699"
)
if (
    requirement_action_candidate_source_incomplete_fingerprint()
    != REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT
):
    raise RuntimeError(
        "requirement-action incomplete-source marker changed without a new identity"
    )


def requirement_action_binding_invalid_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "binding_contract": "requirement-action-binding-v1",
                "source": "binding_invalid",
                "schema_version": (
                    REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION
                ),
                "policy_version": REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT = (
    "357ed7bbb833a8dfbd8f907e8309c363957460c6053d5b9d77d069bbbb7e55da"
)
if (
    requirement_action_binding_invalid_fingerprint()
    != REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT
):
    raise RuntimeError(
        "requirement-action invalid-binding marker changed without a new identity"
    )


def coaching_profile_v1_unconfigured_fingerprint() -> str:
    """Hash every fixed field that gives the unconfigured preset meaning."""

    preset = COACHING_PROFILE_V1
    payload = {
        "fingerprint_contract": "coaching-profile-binding-v1",
        "preset_id": preset.preset_id.value,
        "analysis_profile_key": preset.analysis_profile_key,
        "analysis_profile_version": preset.analysis_profile_version,
        "metric_pack_key": preset.metric_pack_key,
        "metric_pack_version": preset.metric_pack_version,
        "task_profile": preset.task_profile.model_dump(mode="json"),
        "max_messages": preset.max_messages,
        "max_characters": preset.max_characters,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT = (
    "4cf952d189fd817c3959540a18538b76b161aa3a03d810cb967cafc7f284be71"
)
if (
    coaching_profile_v1_unconfigured_fingerprint()
    != COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT
):
    raise RuntimeError(
        "COACHING_PROFILE_V1 changed without a new profile-binding identity"
    )


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be a local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("provenance value is invalid")
    return value


class MetricProfileSource(StrEnum):
    """Closed authority vocabulary for a measured r5 denominator profile."""

    COACHING_PROFILE_V1_UNCONFIGURED = "coaching_profile_v1_unconfigured"
    DECLARED_TASK_PROFILE = "declared_task_profile"


@dataclass(frozen=True, slots=True)
class _ResolvedMetricProfile:
    task_profile: TextTaskProfile
    declaration: DeclaredTaskProfileRecord | None

    @property
    def source(self) -> MetricProfileSource:
        return (
            MetricProfileSource.COACHING_PROFILE_V1_UNCONFIGURED
            if self.declaration is None
            else MetricProfileSource.DECLARED_TASK_PROFILE
        )

    def request_identity(self) -> tuple[str, ...]:
        declaration = self.declaration
        if declaration is None:
            return (
                self.source.value,
                "none",
                "none",
                COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT,
                COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION,
                COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION,
            )
        return (
            self.source.value,
            declaration.profile_id,
            str(declaration.revision),
            declaration.profile_fingerprint,
            declaration.schema_version,
            declaration.policy_version,
        )


class SessionMetricProfileBinding(StrictModel):
    """Content-free, exact profile provenance for one measured source window."""

    profile_source: MetricProfileSource
    provider: Provider
    session_id: str
    source_window_fingerprint: str
    profile_id: str | None = None
    profile_revision: int | None = None
    profile_fingerprint: str
    profile_schema_version: str
    profile_policy_version: str
    bound_at: datetime
    local_only: bool = True
    content_persisted: bool = False

    _ids = field_validator(
        "session_id",
        "source_window_fingerprint",
        "profile_fingerprint",
    )(_pseudonym)
    _codes = field_validator(
        "profile_schema_version",
        "profile_policy_version",
    )(_safe_code)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("profile_revision")
    @classmethod
    def validate_profile_revision(cls, value: int | None) -> int | None:
        if value is not None and (
            isinstance(value, bool) or not 1 <= value <= 1_000_000
        ):
            raise ValueError("profile revision is invalid")
        return value

    @field_validator("bound_at")
    @classmethod
    def validate_bound_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("profile binding timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def validate_profile_authority(self) -> "SessionMetricProfileBinding":
        if not self.local_only or self.content_persisted:
            raise ValueError("metric profile bindings are content-free local metadata")
        if self.profile_source is MetricProfileSource.DECLARED_TASK_PROFILE:
            if self.profile_id is None or self.profile_revision is None:
                raise ValueError("declared task profile identity is incomplete")
            if (
                self.profile_schema_version != "declared-task-profile-v1"
                or self.profile_policy_version != "authenticated-local-user-v1"
            ):
                raise ValueError("declared task profile provenance is invalid")
        else:
            if self.profile_id is not None or self.profile_revision is not None:
                raise ValueError("the unconfigured preset has no declared revision")
            if (
                self.profile_fingerprint
                != COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT
                or self.profile_schema_version
                != COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION
                or self.profile_policy_version
                != COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION
            ):
                raise ValueError("unconfigured coaching profile marker is invalid")
        return self


class RequirementPlanEvidenceSource(StrEnum):
    UNAVAILABLE = "unavailable"
    AWAITING_REVIEW = "awaiting_review"
    REVIEWED_REQUIREMENT_PLAN = "reviewed_requirement_plan"


@dataclass(frozen=True, slots=True)
class _ResolvedRequirementPlanEvidence:
    snapshot: RequirementPlanEvidenceSnapshot | None
    evidence_source: RequirementPlanEvidenceSource
    evidence_fingerprint: str

    def request_identity(self) -> tuple[str, ...]:
        snapshot = self.snapshot
        if (
            self.evidence_source
            is not RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
        ):
            awaiting = (
                self.evidence_source
                is RequirementPlanEvidenceSource.AWAITING_REVIEW
            )
            return (
                self.evidence_source.value,
                "none",
                "none",
                (
                    REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT
                    if awaiting
                    else REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT
                ),
                (
                    REQUIREMENT_PLAN_AWAITING_REVIEW_SCHEMA_VERSION
                    if awaiting
                    else REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION
                ),
                REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION,
            )
        if snapshot is None or snapshot.confirmation_id is None:
            raise AssertionError("reviewed requirement-plan evidence is absent")
        return (
            RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN.value,
            snapshot.confirmation_id,
            snapshot.proposal_id or "none",
            self.evidence_fingerprint,
            snapshot.schema_version,
            snapshot.policy_version,
            snapshot.source_window_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class _ResolvedRequirementActionEvidence:
    snapshot: RequirementActionEvidenceSnapshot | None
    evidence_source: "RequirementActionEvidenceSource"

    def request_identity(self) -> tuple[str, ...]:
        snapshot = self.snapshot
        if (
            self.evidence_source
            is not RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
        ):
            awaiting = (
                self.evidence_source
                is RequirementActionEvidenceSource.AWAITING_REVIEW
            )
            return (
                self.evidence_source.value,
                (
                    REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT
                    if awaiting
                    else REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT
                ),
                (
                    REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION
                    if awaiting
                    else REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION
                ),
                REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
            )
        if (
            snapshot is None
            or snapshot.confirmation_id is None
            or snapshot.proposal_id is None
            or snapshot.reviewed_descriptor_set_fingerprint is None
            or snapshot.source_run_id is None
            or snapshot.requirement_plan_confirmation_id is None
            or snapshot.requirement_plan_evidence_fingerprint is None
            or snapshot.candidate_manifest is None
            or snapshot.evidence_fingerprint is None
        ):
            raise AssertionError("reviewed requirement-action evidence is absent")
        return (
            self.evidence_source.value,
            snapshot.source_run_id,
            snapshot.requirement_plan_confirmation_id,
            snapshot.requirement_plan_evidence_fingerprint,
            snapshot.candidate_manifest.manifest_fingerprint,
            snapshot.confirmation_id,
            snapshot.proposal_id,
            snapshot.reviewed_descriptor_set_fingerprint,
            snapshot.evidence_fingerprint,
            snapshot.schema_version,
            snapshot.policy_version,
            snapshot.source_window_fingerprint,
        )


_RequirementActionCandidateStatus = Literal[
    "unavailable",
    "candidate_source_incomplete",
    "bounded",
    "candidate_manifest_overflow",
]


@dataclass(frozen=True, slots=True)
class _RequirementActionCandidatePreflight:
    """One content-free safe-event snapshot used before request identity."""

    status: _RequirementActionCandidateStatus
    manifest: RequirementActionCandidateManifest | None

    @property
    def overflow(self) -> bool:
        return self.status == "candidate_manifest_overflow"


class SessionRequirementPlanEvidenceBinding(StrictModel):
    """Exact content-free requirement-plan authority used by one r6 run."""

    evidence_source: RequirementPlanEvidenceSource
    session_id: str
    source_window_fingerprint: str
    confirmation_id: str | None = None
    proposal_id: str | None = None
    evidence_fingerprint: str
    evidence_schema_version: str
    evidence_policy_version: str
    bound_at: datetime
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "session_id", "source_window_fingerprint", "evidence_fingerprint"
    )(_pseudonym)
    _codes = field_validator(
        "evidence_schema_version", "evidence_policy_version"
    )(_safe_code)

    @field_validator("confirmation_id", "proposal_id")
    @classmethod
    def optional_authority_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("bound_at")
    @classmethod
    def utc_bound_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("requirement-plan binding timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_authority(self) -> "SessionRequirementPlanEvidenceBinding":
        if self.evidence_source is RequirementPlanEvidenceSource.UNAVAILABLE:
            if (
                self.confirmation_id is not None
                or self.proposal_id is not None
                or self.evidence_fingerprint
                != REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError("unavailable requirement-plan marker is invalid")
        elif self.evidence_source is RequirementPlanEvidenceSource.AWAITING_REVIEW:
            if (
                self.confirmation_id is not None
                or self.proposal_id is not None
                or self.evidence_fingerprint
                != REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_PLAN_AWAITING_REVIEW_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError("awaiting-review requirement-plan marker is invalid")
        elif (
            self.confirmation_id is None
            or self.proposal_id is None
            or self.evidence_fingerprint
            in {
                REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT,
                REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT,
            }
            or self.evidence_schema_version != "requirement-plan-evidence-v1"
            or self.evidence_policy_version != "reviewed-requirement-plan-v1"
        ):
            raise ValueError("reviewed requirement-plan authority is incomplete")
        return self


class RequirementActionEvidenceSource(StrEnum):
    UNAVAILABLE = "unavailable"
    AWAITING_REVIEW = "awaiting_review"
    CANDIDATE_MANIFEST_OVERFLOW = "candidate_manifest_overflow"
    CANDIDATE_SOURCE_INCOMPLETE = "candidate_source_incomplete"
    BINDING_INVALID = "binding_invalid"
    REVIEWED_REQUIREMENT_ACTION = "reviewed_requirement_action"


class SessionRequirementActionEvidenceBinding(StrictModel):
    """Exact content-free requirement-action authority used by one r7/r8 run."""

    evidence_source: RequirementActionEvidenceSource
    session_id: str
    source_window_fingerprint: str
    source_run_id: str | None = None
    requirement_plan_confirmation_id: str | None = None
    requirement_plan_evidence_fingerprint: str | None = None
    candidate_manifest_fingerprint: str | None = None
    confirmation_id: str | None = None
    proposal_id: str | None = None
    reviewed_descriptor_set_fingerprint: str | None = None
    evidence_fingerprint: str
    evidence_schema_version: str
    evidence_policy_version: str
    bound_at: datetime
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "session_id", "source_window_fingerprint", "evidence_fingerprint"
    )(_pseudonym)
    _codes = field_validator(
        "evidence_schema_version", "evidence_policy_version"
    )(_safe_code)

    @field_validator(
        "source_run_id",
        "requirement_plan_confirmation_id",
        "requirement_plan_evidence_fingerprint",
        "candidate_manifest_fingerprint",
        "confirmation_id",
        "proposal_id",
        "reviewed_descriptor_set_fingerprint",
    )
    @classmethod
    def optional_authority_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("bound_at")
    @classmethod
    def utc_bound_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("requirement-action binding timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_authority(self) -> "SessionRequirementActionEvidenceBinding":
        source_authority = (
            self.source_run_id,
            self.requirement_plan_confirmation_id,
            self.requirement_plan_evidence_fingerprint,
            self.candidate_manifest_fingerprint,
        )
        if self.evidence_source is RequirementActionEvidenceSource.UNAVAILABLE:
            if (
                any(value is not None for value in source_authority)
                or self.confirmation_id is not None
                or self.proposal_id is not None
                or self.reviewed_descriptor_set_fingerprint is not None
                or self.evidence_fingerprint
                != REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError("unavailable requirement-action marker is invalid")
        elif (
            self.evidence_source
            is RequirementActionEvidenceSource.AWAITING_REVIEW
        ):
            if (
                any(value is not None for value in source_authority)
                or self.confirmation_id is not None
                or self.proposal_id is not None
                or self.reviewed_descriptor_set_fingerprint is not None
                or self.evidence_fingerprint
                != REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError(
                    "awaiting-review requirement-action marker is invalid"
                )
        elif (
            self.evidence_source
            is RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW
        ):
            if (
                any(value is not None for value in source_authority)
                or self.confirmation_id is not None
                or self.proposal_id is not None
                or self.reviewed_descriptor_set_fingerprint is not None
                or self.evidence_fingerprint
                != REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError(
                    "candidate-overflow requirement-action marker is invalid"
                )
        elif (
            self.evidence_source
            is RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE
        ):
            if (
                any(value is not None for value in source_authority)
                or self.confirmation_id is not None
                or self.proposal_id is not None
                or self.reviewed_descriptor_set_fingerprint is not None
                or self.evidence_fingerprint
                != REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError(
                    "incomplete-source requirement-action marker is invalid"
                )
        elif (
            self.evidence_source
            is RequirementActionEvidenceSource.BINDING_INVALID
        ):
            if (
                any(value is not None for value in source_authority)
                or self.confirmation_id is not None
                or self.proposal_id is not None
                or self.reviewed_descriptor_set_fingerprint is not None
                or self.evidence_fingerprint
                != REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT
                or self.evidence_schema_version
                != REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION
                or self.evidence_policy_version
                != REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION
            ):
                raise ValueError(
                    "invalid-binding requirement-action marker is invalid"
                )
        elif (
            any(value is None for value in source_authority)
            or self.confirmation_id is None
            or self.proposal_id is None
            or self.reviewed_descriptor_set_fingerprint is None
            or self.evidence_fingerprint
            in {
                REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT,
                REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
                REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT,
                REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT,
                REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT,
            }
            or self.evidence_schema_version != "requirement-action-evidence-v1"
            or self.evidence_policy_version != "reviewed-requirement-action-v1"
        ):
            raise ValueError(
                "reviewed requirement-action authority is incomplete"
            )
        return self

    def authority_identity(self) -> tuple[str, ...]:
        """Stable trajectory identity; observation time is not semantics."""

        return (
            self.evidence_source.value,
            self.session_id,
            self.source_window_fingerprint,
            self.source_run_id or "none",
            self.requirement_plan_confirmation_id or "none",
            self.requirement_plan_evidence_fingerprint or "none",
            self.candidate_manifest_fingerprint or "none",
            self.confirmation_id or "none",
            self.proposal_id or "none",
            self.reviewed_descriptor_set_fingerprint or "none",
            self.evidence_fingerprint,
            self.evidence_schema_version,
            self.evidence_policy_version,
        )


REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION = (
    "session-requirement-verification-evidence-binding-v1"
)
VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID = (
    "reviewed-requirement-verification-authority"
)
VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION = "4"
VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION = "objective-evidence-no-rubric-v4"


class RequirementVerificationEvidenceSource(StrEnum):
    UNAVAILABLE = "unavailable"
    OPPORTUNITY_BOUND_EXCEEDED = "opportunity_bound_exceeded"
    AWAITING_EVIDENCE = "awaiting_evidence"
    PERSISTED_EVIDENCE = "persisted_evidence"


@dataclass(frozen=True, slots=True)
class _ResolvedRequirementVerificationEvidence:
    evidence_source: RequirementVerificationEvidenceSource
    opportunities: AppIssuedRequirementVerificationOpportunitySet | None = None
    snapshot: RequirementVerificationEvidenceSnapshot | None = None

    def request_identity(self) -> tuple[str, ...]:
        opportunities = self.opportunities
        snapshot = self.snapshot
        return (
            self.evidence_source.value,
            (
                "none"
                if opportunities is None
                else opportunities.requirement_plan_confirmation_id
            ),
            (
                "none"
                if opportunities is None
                else opportunities.requirement_plan_proposal_id
            ),
            (
                "none"
                if opportunities is None
                else opportunities.requirement_plan_evidence_fingerprint
            ),
            (
                "none"
                if opportunities is None
                else str(len(opportunities.opportunities))
            ),
            (
                "none"
                if opportunities is None
                else opportunities.opportunity_set_fingerprint
            ),
            "none" if snapshot is None else str(snapshot.revision),
            (
                "none"
                if snapshot is None
                else snapshot.evidence.evidence_set_fingerprint
            ),
            REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
            REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
            REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
            REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
            REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
            REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
            REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
            OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
            REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
        )


class SessionRequirementVerificationEvidenceBinding(StrictModel):
    """Exact content-free M58 revision authority used by one r8 run."""

    evidence_source: RequirementVerificationEvidenceSource
    session_id: str
    source_window_fingerprint: str
    requirement_plan_confirmation_id: str | None = None
    requirement_plan_proposal_id: str | None = None
    requirement_plan_evidence_fingerprint: str | None = None
    requirement_plan_schema_version: str | None = None
    requirement_plan_policy_version: str | None = None
    requirement_plan_review_rubric_version: str | None = None
    opportunity_count: int | None = Field(default=None, ge=0, le=1_000)
    opportunity_set_fingerprint: str | None = None
    evidence_set_fingerprint: str | None = None
    through_revision: int | None = Field(default=None, ge=0, le=32_000)
    authority_head_count: int | None = Field(default=None, ge=0, le=1_000)
    objective_result_count: int | None = Field(default=None, ge=0, le=1_000)
    native_acceptance_count: int | None = Field(default=None, ge=0, le=1_000)
    resolved_opportunity_count: int | None = Field(default=None, ge=0, le=1_000)
    met_requirement_count: int | None = Field(default=None, ge=0, le=1_000)
    opportunity_issuer_version: str
    result_issuer_version: str
    acceptance_issuer_version: str
    evidence_schema_version: str
    evidence_policy_version: str
    persistence_schema_version: str
    evidence_projection_version: str
    objective_projection_version: str
    binding_schema_version: str = REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION
    binding_fingerprint: str
    bound_at: datetime
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "session_id", "source_window_fingerprint", "binding_fingerprint"
    )(_pseudonym)

    @field_validator(
        "requirement_plan_confirmation_id",
        "requirement_plan_proposal_id",
        "requirement_plan_evidence_fingerprint",
        "opportunity_set_fingerprint",
        "evidence_set_fingerprint",
    )
    @classmethod
    def optional_authority_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator(
        "requirement_plan_schema_version",
        "requirement_plan_policy_version",
        "requirement_plan_review_rubric_version",
    )
    @classmethod
    def optional_version(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    _versions = field_validator(
        "opportunity_issuer_version",
        "result_issuer_version",
        "acceptance_issuer_version",
        "evidence_schema_version",
        "evidence_policy_version",
        "persistence_schema_version",
        "evidence_projection_version",
        "objective_projection_version",
        "binding_schema_version",
    )(_safe_code)

    @field_validator("bound_at")
    @classmethod
    def utc_bound_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("requirement-verification binding timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_authority(self) -> "SessionRequirementVerificationEvidenceBinding":
        expected_versions = (
            REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
            REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
            REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
            REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
            REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
            REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
            REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
            OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
            REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
        )
        actual_versions = (
            self.opportunity_issuer_version,
            self.result_issuer_version,
            self.acceptance_issuer_version,
            self.evidence_schema_version,
            self.evidence_policy_version,
            self.persistence_schema_version,
            self.evidence_projection_version,
            self.objective_projection_version,
            self.binding_schema_version,
        )
        if actual_versions != expected_versions:
            raise ValueError("requirement-verification binding versions are invalid")
        plan_authority = (
            self.requirement_plan_confirmation_id,
            self.requirement_plan_proposal_id,
            self.requirement_plan_evidence_fingerprint,
            self.requirement_plan_schema_version,
            self.requirement_plan_policy_version,
            self.requirement_plan_review_rubric_version,
        )
        evidence_statistics = (
            self.authority_head_count,
            self.objective_result_count,
            self.native_acceptance_count,
            self.resolved_opportunity_count,
            self.met_requirement_count,
        )
        if self.evidence_source is RequirementVerificationEvidenceSource.UNAVAILABLE:
            if (
                any(value is not None for value in plan_authority)
                or self.opportunity_count is not None
                or self.opportunity_set_fingerprint is not None
                or self.evidence_set_fingerprint is not None
                or self.through_revision is not None
                or any(value is not None for value in evidence_statistics)
            ):
                raise ValueError("unavailable verification binding has authority")
            return self
        if any(value is None for value in plan_authority):
            raise ValueError("verification binding lacks reviewed r6 authority")
        if (
            self.requirement_plan_schema_version
            != REQUIREMENT_PLAN_EVIDENCE_SCHEMA_VERSION
            or self.requirement_plan_policy_version
            != REQUIREMENT_PLAN_EVIDENCE_POLICY_VERSION
            or self.requirement_plan_review_rubric_version
            != REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
            or self.opportunity_count is None
            or self.opportunity_set_fingerprint is None
        ):
            raise ValueError("verification opportunity authority is invalid")
        if (
            self.evidence_source
            is RequirementVerificationEvidenceSource.OPPORTUNITY_BOUND_EXCEEDED
        ):
            if (
                self.opportunity_count
                <= MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES
                or self.evidence_set_fingerprint is not None
                or self.through_revision is not None
                or any(value is not None for value in evidence_statistics)
            ):
                raise ValueError("verification opportunity-bound marker is invalid")
            return self
        if self.opportunity_count > MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES:
            raise ValueError("verification evidence exceeds the receipt bound")
        if self.evidence_source is RequirementVerificationEvidenceSource.AWAITING_EVIDENCE:
            if (
                self.evidence_set_fingerprint is not None
                or self.through_revision is not None
                or evidence_statistics != (0, 0, 0, 0, 0)
            ):
                raise ValueError("awaiting verification marker is invalid")
            return self
        if (
            self.evidence_set_fingerprint is None
            or self.through_revision is None
            or any(value is None for value in evidence_statistics)
        ):
            raise ValueError("persisted verification authority is incomplete")
        assert self.authority_head_count is not None
        assert self.through_revision is not None
        assert self.objective_result_count is not None
        assert self.native_acceptance_count is not None
        assert self.resolved_opportunity_count is not None
        assert self.met_requirement_count is not None
        if (
            self.authority_head_count
            != self.objective_result_count + self.native_acceptance_count
            or self.through_revision < self.authority_head_count
            or self.authority_head_count > self.opportunity_count
            or self.resolved_opportunity_count > self.authority_head_count
            or self.met_requirement_count > self.resolved_opportunity_count
        ):
            raise ValueError("persisted verification counts are inconsistent")
        return self

    def authority_identity(self) -> tuple[str, ...]:
        """Stable revision identity; observation time is not semantics."""

        values = self.model_dump(
            mode="python", exclude={"bound_at", "binding_fingerprint"}
        )
        return tuple(
            "none" if value is None else str(value.value if isinstance(value, StrEnum) else value)
            for value in values.values()
        )


def validate_requirement_verification_binding_metric_state(
    binding: SessionRequirementVerificationEvidenceBinding,
    state: MetricStateV2,
) -> None:
    """Cross-bind one r8 M58 source partition to the published metric row."""

    if (
        state.metric_key != "outcome.verified_requirement_coverage"
        or state.projection_version != METRIC_PROJECTION_V2_VERSION_8
    ):
        raise ValueError("verification binding belongs to another metric state")
    statistics = state.statistics
    nonnumeric = (
        state.numerator is None
        and state.denominator is None
        and state.numeric_value is None
    )
    no_bounds = (
        state.censoring_lower_bound is None
        and state.censoring_upper_bound is None
    )
    exact_owner_shape = (
        statistics.superseded_excluded_count == 0
        and statistics.distinct_owner_count == statistics.eligible_count
    )
    if (
        binding.evidence_source
        is RequirementVerificationEvidenceSource.OPPORTUNITY_BOUND_EXCEEDED
    ):
        if (
            state.value_state is not MetricValueStateV2.UNKNOWN
            or state.explanation_code
            != "typed_objective_opportunity_count_exceeds_receipt_bound"
            or statistics.eligible_count != 0
            or not statistics.capability_available
            or not statistics.source_complete
            or not nonnumeric
            or not no_bounds
            or not exact_owner_shape
        ):
            raise ValueError("verification opportunity-bound state is invalid")
        return
    if binding.evidence_source is RequirementVerificationEvidenceSource.UNAVAILABLE:
        expected_authority_flags = {
            "reviewed_requirement_authority_unavailable": (False, True),
            "reviewed_requirement_authority_invalid": (True, False),
            "requirement_verification_evidence_unavailable": (True, True),
        }
        authority_absent = state.explanation_code in {
            "reviewed_requirement_authority_unavailable",
            "reviewed_requirement_authority_invalid",
        }
        exact_unavailable_bounds = (
            no_bounds
            if authority_absent
            else state.censoring_lower_bound == 0.0
            and state.censoring_upper_bound == 1.0
        )
        if (
            state.value_state is not MetricValueStateV2.UNKNOWN
            or state.explanation_code not in expected_authority_flags
            or (
                statistics.capability_available,
                statistics.source_complete,
            )
            != expected_authority_flags[state.explanation_code]
            or statistics.eligible_count != (0 if authority_absent else statistics.unknown_count)
            or (not authority_absent and statistics.eligible_count == 0)
            or not nonnumeric
            or not exact_unavailable_bounds
            or not exact_owner_shape
        ):
            raise ValueError("unavailable verification state is invalid")
        return
    assert binding.opportunity_count is not None
    if binding.opportunity_count == 0:
        if (
            state.value_state is not MetricValueStateV2.NOT_APPLICABLE
            or state.explanation_code != "reviewed_requirement_set_empty"
            or statistics.eligible_count != 0
            or not statistics.capability_available
            or not statistics.source_complete
            or not nonnumeric
            or not no_bounds
            or not exact_owner_shape
        ):
            raise ValueError("empty verification state is invalid")
        return
    if binding.evidence_source is RequirementVerificationEvidenceSource.AWAITING_EVIDENCE:
        if (
            state.value_state is not MetricValueStateV2.UNKNOWN
            or state.explanation_code
            != "requirement_verification_evidence_unavailable"
            or statistics.eligible_count != binding.opportunity_count
            or statistics.unknown_count != binding.opportunity_count
            or not statistics.capability_available
            or not statistics.source_complete
            or not nonnumeric
            or state.censoring_lower_bound != 0.0
            or state.censoring_upper_bound != 1.0
            or not exact_owner_shape
        ):
            raise ValueError("awaiting verification state is invalid")
        return
    assert binding.resolved_opportunity_count is not None
    assert binding.met_requirement_count is not None
    expected_unresolved = (
        binding.opportunity_count - binding.resolved_opportunity_count
    )
    if (
        statistics.eligible_count != binding.opportunity_count
        or not statistics.capability_available
        or not statistics.source_complete
        or statistics.met_count != binding.met_requirement_count
        or statistics.not_met_count
        != binding.resolved_opportunity_count - binding.met_requirement_count
        or statistics.pending_count != 0
        or statistics.unknown_count != expected_unresolved
        or not exact_owner_shape
    ):
        raise ValueError("persisted verification statistics are inconsistent")
    if expected_unresolved:
        if (
            state.value_state is not MetricValueStateV2.UNKNOWN
            or state.explanation_code
            != "app_issued_requirement_verification_pending"
            or not nonnumeric
            or state.censoring_lower_bound
            != binding.met_requirement_count / binding.opportunity_count
            or state.censoring_upper_bound
            != (
                binding.met_requirement_count + expected_unresolved
            )
            / binding.opportunity_count
        ):
            raise ValueError("pending verification state is invalid")
    elif (
        state.value_state is not MetricValueStateV2.KNOWN
        or state.explanation_code != "app_issued_verified_requirement_coverage"
        or state.numerator != binding.met_requirement_count
        or state.denominator != binding.opportunity_count
    ):
        raise ValueError("resolved verification state is invalid")


def validate_r8_typed_metric_projection(
    receipt: SessionModelEnsembleReceipt,
) -> None:
    """Require the complete typed sidecar and exact verified r8 provenance."""

    publication = receipt.metric_publication_v2
    if (
        publication is None
        or publication.projection_version != METRIC_PROJECTION_V2_VERSION_8
    ):
        return
    canonical_keys = {item.metric_key for item in METRIC_CONTRACTS_V2}
    typed_by_key = {item.metric_key: item for item in receipt.typed_metrics}
    if (
        len(receipt.typed_metrics) != len(METRIC_CONTRACTS_V2)
        or len(typed_by_key) != len(METRIC_CONTRACTS_V2)
        or set(typed_by_key) != canonical_keys
    ):
        raise ValueError("r8 publication requires all twenty typed metric receipts")
    states_by_key = {item.state.metric_key: item.state for item in publication.metrics}
    try:
        state = states_by_key[VERIFIED_REQUIREMENT_METRIC_KEY]
        typed = typed_by_key[VERIFIED_REQUIREMENT_METRIC_KEY]
    except KeyError as exc:  # pragma: no cover - publication model also pins this
        raise ValueError("r8 verified-requirement receipt is missing") from exc
    resolved_count = state.statistics.met_count + state.statistics.not_met_count
    expected_coverage = (
        0.0
        if state.statistics.eligible_count == 0
        else resolved_count / state.statistics.eligible_count
    )
    numeric_matches = (
        typed.numeric_value is None and state.numeric_value is None
    ) or (
        typed.numeric_value is not None
        and state.numeric_value is not None
        and math.isclose(
            typed.numeric_value,
            state.numeric_value,
            rel_tol=0,
            abs_tol=1e-12,
        )
    )
    if (
        typed.value_state.value != state.value_state.value
        or typed.numerator != state.numerator
        or typed.denominator != state.denominator
        or not numeric_matches
        or typed.observed_message_count != resolved_count
        or typed.eligible_message_count != state.statistics.eligible_count
        or not math.isclose(
            typed.coverage,
            expected_coverage,
            rel_tol=0,
            abs_tol=1e-12,
        )
        or typed.explanation_code != state.explanation_code
        or typed.error_code is not None
        or typed.engine_version != OBJECTIVE_METRIC_PROJECTION_V4_VERSION
        or typed.algorithm_id != VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID
        or typed.algorithm_version
        != VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION
        or typed.rubric_version != VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION
    ):
        raise ValueError(
            "r8 verified-requirement typed receipt disagrees with its canonical state"
        )


def validate_requirement_action_binding_metric_state(
    binding: SessionRequirementActionEvidenceBinding,
    state: MetricStateV2,
) -> None:
    """Cross-bind one r7/r8 authority marker to its exact action metric row."""

    statistics = state.statistics
    marker_shape = (
        state.value_state is MetricValueStateV2.UNKNOWN
        and state.numerator is None
        and state.denominator is None
        and state.numeric_value is None
        and state.censoring_lower_bound is None
        and state.censoring_upper_bound is None
        and statistics.met_count == 0
        and statistics.not_met_count == 0
        and statistics.pending_count == 0
        and statistics.unknown_count == statistics.eligible_count
        and statistics.superseded_excluded_count == 0
        and statistics.distinct_owner_count == statistics.eligible_count
    )
    marker_expectations = {
        RequirementActionEvidenceSource.UNAVAILABLE: (
            REASON_REQUIREMENT_ACTION_UNAVAILABLE,
            False,
            True,
        ),
        RequirementActionEvidenceSource.AWAITING_REVIEW: (
            REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
            True,
            True,
        ),
        RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW: (
            REASON_REQUIREMENT_ACTION_OVERFLOW,
            True,
            True,
        ),
        RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE: (
            REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE,
            True,
            False,
        ),
        RequirementActionEvidenceSource.BINDING_INVALID: (
            REASON_REQUIREMENT_ACTION_INVALID,
            True,
            False,
        ),
    }
    if binding.evidence_source in marker_expectations:
        reason, capability_available, source_complete = marker_expectations[
            binding.evidence_source
        ]
        valid = (
            marker_shape
            and state.explanation_code == reason
            and statistics.capability_available is capability_available
            and statistics.source_complete is source_complete
        )
    else:
        reviewed_value_shape = (
            state.value_state is MetricValueStateV2.KNOWN
            and state.explanation_code == REASON_REVIEWED_REQUIREMENT_ACTION_LINKS
            and statistics.eligible_count > 0
            and statistics.pending_count == 0
        ) or (
            state.value_state is MetricValueStateV2.PENDING
            and state.explanation_code == "opportunity_right_censored"
            and statistics.eligible_count > 0
            and statistics.pending_count > 0
        ) or (
            state.value_state is MetricValueStateV2.NOT_APPLICABLE
            and state.explanation_code == "no_opportunity_observed"
            and statistics.eligible_count == 0
        )
        valid = (
            reviewed_value_shape
            and statistics.capability_available
            and statistics.source_complete
            and statistics.unknown_count == 0
            and statistics.superseded_excluded_count == 0
            and statistics.distinct_owner_count == statistics.eligible_count
        )
    if (
        state.projection_version
        not in {METRIC_PROJECTION_V2_VERSION_7, METRIC_PROJECTION_V2_VERSION_8}
        or state.metric_key != "logic.requirement_action_traceability"
        or not valid
    ):
        raise ValueError(
            "requirement-action binding disagrees with its r7/r8 metric state"
        )


def validate_requirement_plan_binding_metric_state(
    binding: SessionRequirementPlanEvidenceBinding,
    state: MetricStateV2,
) -> None:
    """Cross-bind one r6-r8 plan authority marker to decomposition truth."""

    statistics = state.statistics
    empty_unknown = (
        state.value_state is MetricValueStateV2.UNKNOWN
        and state.numerator is None
        and state.denominator is None
        and state.numeric_value is None
        and state.censoring_lower_bound is None
        and state.censoring_upper_bound is None
        and statistics.eligible_count == 0
        and statistics.met_count == 0
        and statistics.not_met_count == 0
        and statistics.pending_count == 0
        and statistics.unknown_count == 0
        and statistics.superseded_excluded_count == 0
        and statistics.distinct_owner_count == 0
    )
    if binding.evidence_source is RequirementPlanEvidenceSource.UNAVAILABLE:
        valid = (
            empty_unknown
            and state.explanation_code == REASON_REQUIREMENT_PLAN_UNAVAILABLE
            and not statistics.capability_available
            and statistics.source_complete
        )
    elif binding.evidence_source is RequirementPlanEvidenceSource.AWAITING_REVIEW:
        valid = (
            empty_unknown
            and state.explanation_code
            == REASON_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED
            and statistics.capability_available
            and statistics.source_complete
        )
    else:
        reviewed_invalid = (
            empty_unknown
            and state.explanation_code == REASON_REQUIREMENT_PLAN_INVALID
            and statistics.capability_available
            and not statistics.source_complete
        )
        valid = reviewed_invalid or (
            reviewed_requirement_plan_denominator_is_authoritative(state)
        )
    if (
        state.projection_version
        not in {
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        or state.metric_key != "logic.decomposition_coverage"
        or not valid
    ):
        raise ValueError(
            "requirement-plan binding disagrees with its decomposition metric state"
        )


def _validate_reviewed_opportunity_outcomes(
    state: MetricStateV2,
    *,
    metric_key: str,
    known_reason: str,
    met_count: int,
    not_met_count: int,
    pending_count: int,
) -> None:
    eligible_count = met_count + not_met_count + pending_count
    statistics = state.statistics
    counts_match = (
        statistics.capability_available
        and statistics.source_complete
        and statistics.eligible_count == eligible_count
        and statistics.met_count == met_count
        and statistics.not_met_count == not_met_count
        and statistics.pending_count == pending_count
        and statistics.unknown_count == 0
        and statistics.superseded_excluded_count == 0
        and statistics.distinct_owner_count == eligible_count
    )
    if eligible_count == 0:
        result_matches = (
            state.value_state is MetricValueStateV2.NOT_APPLICABLE
            and state.explanation_code == "no_opportunity_observed"
            and state.censoring_lower_bound is None
            and state.censoring_upper_bound is None
        )
    elif pending_count:
        result_matches = (
            state.value_state is MetricValueStateV2.PENDING
            and state.explanation_code == "opportunity_right_censored"
            and state.censoring_lower_bound is not None
            and state.censoring_upper_bound is not None
            and abs(state.censoring_lower_bound - met_count / eligible_count)
            <= 1e-9
            and abs(
                state.censoring_upper_bound
                - (met_count + pending_count) / eligible_count
            )
            <= 1e-9
        )
    else:
        result_matches = (
            state.value_state is MetricValueStateV2.KNOWN
            and state.explanation_code == known_reason
            and state.numerator == met_count
            and state.denominator == eligible_count
            and state.numeric_value is not None
            and abs(state.numeric_value - met_count / eligible_count) <= 1e-9
        )
    if state.metric_key != metric_key or not counts_match or not result_matches:
        raise ValueError("reviewed evidence graph disagrees with its metric result")


def validate_reviewed_requirement_plan_outcomes_metric_state(
    dispositions: tuple[RequirementDisposition, ...],
    state: MetricStateV2,
) -> None:
    _validate_reviewed_opportunity_outcomes(
        state,
        metric_key="logic.decomposition_coverage",
        known_reason="reviewed_requirement_plan_links",
        met_count=sum(item is RequirementDisposition.LINKED for item in dispositions),
        not_met_count=sum(
            item is RequirementDisposition.NOT_LINKED for item in dispositions
        ),
        pending_count=sum(
            item is RequirementDisposition.PENDING for item in dispositions
        ),
    )


def validate_reviewed_requirement_action_snapshot_metric_state(
    snapshot: RequirementActionEvidenceSnapshot,
    state: MetricStateV2,
) -> None:
    manifest = snapshot.candidate_manifest
    if manifest is None:
        raise ValueError("reviewed action snapshot has no candidate manifest")
    actions = {item.action_id: item for item in manifest.actions}
    if len(actions) != len(manifest.actions):
        raise ValueError("reviewed action snapshot repeats a candidate")
    links = {item.requirement_id: item.action_ids for item in snapshot.links}
    requirement_ids = tuple(item.requirement_id for item in snapshot.requirements)
    if (
        len(links) != len(snapshot.links)
        or tuple(item.requirement_id for item in snapshot.links) != requirement_ids
    ):
        raise ValueError("reviewed action snapshot does not exactly cover requirements")
    met_count = not_met_count = pending_count = 0
    for requirement_id in requirement_ids:
        try:
            linked_states = {actions[action_id].state for action_id in links[requirement_id]}
        except KeyError as exc:
            raise ValueError("reviewed action link names an unknown candidate") from exc
        if ActionState.COMPLETED in linked_states:
            met_count += 1
        elif linked_states & {ActionState.STARTED, ActionState.UNKNOWN}:
            pending_count += 1
        else:
            not_met_count += 1
    _validate_reviewed_opportunity_outcomes(
        state,
        metric_key="logic.requirement_action_traceability",
        known_reason=REASON_REVIEWED_REQUIREMENT_ACTION_LINKS,
        met_count=met_count,
        not_met_count=not_met_count,
        pending_count=pending_count,
    )


class SessionModelEnsembleRunRecord(StrictModel):
    run_id: str
    session_id: str
    request_fingerprint: str
    input_fingerprint: str
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    consent_policy_version: str = MODEL_ENSEMBLE_POLICY_VERSION
    metric_profile_binding: SessionMetricProfileBinding | None = None
    requirement_plan_evidence_binding: (
        SessionRequirementPlanEvidenceBinding | None
    ) = None
    requirement_action_evidence_binding: (
        SessionRequirementActionEvidenceBinding | None
    ) = None
    requirement_verification_evidence_binding: (
        SessionRequirementVerificationEvidenceBinding | None
    ) = None
    receipt: SessionModelEnsembleReceipt

    _ids = field_validator(
        "run_id", "session_id", "request_fingerprint", "input_fingerprint"
    )(_pseudonym)
    _codes = field_validator(
        "provider_version",
        "adapter_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
        "consent_policy_version",
    )(_safe_code)

    @model_validator(mode="after")
    def validate_binding(self) -> "SessionModelEnsembleRunRecord":
        if self.input_fingerprint != self.receipt.source_window_fingerprint:
            raise ValueError("ensemble receipt is bound to another source window")
        binding = self.metric_profile_binding
        if binding is not None and (
            binding.provider is not self.provider
            or binding.session_id != self.session_id
            or binding.source_window_fingerprint != self.input_fingerprint
        ):
            raise ValueError("metric profile is bound to another source window")
        publication = self.receipt.metric_publication_v2
        if publication is not None:
            validate_r8_typed_metric_projection(self.receipt)
            if publication.projection_version in {
                METRIC_PROJECTION_V2_VERSION_5,
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }:
                if binding is None:
                    raise ValueError("current metric publication requires a profile binding")
            elif binding is not None:
                raise ValueError("legacy metric publication cannot carry an r5 profile")
            evidence_binding = self.requirement_plan_evidence_binding
            if publication.projection_version in {
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }:
                if evidence_binding is None:
                    raise ValueError(
                        "r6 metric publication requires a requirement-plan binding"
                    )
                if (
                    evidence_binding.session_id != self.session_id
                    or evidence_binding.source_window_fingerprint
                    != self.input_fingerprint
                ):
                    raise ValueError(
                        "requirement-plan evidence is bound to another source window"
                    )
                decomposition_state = next(
                    item.state
                    for item in publication.metrics
                    if item.state.metric_key == "logic.decomposition_coverage"
                )
                validate_requirement_plan_binding_metric_state(
                    evidence_binding,
                    decomposition_state,
                )
            elif evidence_binding is not None:
                raise ValueError(
                    "legacy metric publication cannot carry requirement-plan authority"
                )
            action_binding = self.requirement_action_evidence_binding
            if publication.projection_version in {
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }:
                if action_binding is None:
                    raise ValueError(
                        "r7/r8 metric publication requires a requirement-action binding"
                    )
                if (
                    action_binding.session_id != self.session_id
                    or action_binding.source_window_fingerprint
                    != self.input_fingerprint
                ):
                    raise ValueError(
                        "requirement-action evidence is bound to another source window"
                    )
                action_state = next(
                    item.state
                    for item in publication.metrics
                    if item.state.metric_key
                    == "logic.requirement_action_traceability"
                )
                validate_requirement_action_binding_metric_state(
                    action_binding,
                    action_state,
                )
            elif action_binding is not None:
                raise ValueError(
                    "pre-r7 metric publication cannot carry requirement-action authority"
                )
            verification_binding = self.requirement_verification_evidence_binding
            if publication.projection_version == METRIC_PROJECTION_V2_VERSION_8:
                if verification_binding is None:
                    raise ValueError(
                        "r8 metric publication requires a requirement-verification binding"
                    )
                if (
                    verification_binding.session_id != self.session_id
                    or verification_binding.source_window_fingerprint
                    != self.input_fingerprint
                ):
                    raise ValueError(
                        "requirement-verification evidence is bound to another source window"
                    )
                verification_state = next(
                    item.state
                    for item in publication.metrics
                    if item.state.metric_key
                    == "outcome.verified_requirement_coverage"
                )
                validate_requirement_verification_binding_metric_state(
                    verification_binding,
                    verification_state,
                )
            elif verification_binding is not None:
                raise ValueError(
                    "pre-r8 metric publication cannot carry requirement-verification authority"
                )
        elif (
            self.requirement_plan_evidence_binding is not None
            or self.requirement_action_evidence_binding is not None
            or self.requirement_verification_evidence_binding is not None
        ):
            raise ValueError("a run without a metric publication has no evidence binding")
        return self


class SessionModelEnsembleOutcome(StrictModel):
    run: SessionModelEnsembleRunRecord
    applied: bool


class SessionModelEnsemblePersistenceAuthority(StrictModel):
    """Ephemeral lease proof checked atomically with a watch-owned save."""

    watch_id: str
    owner: str
    token: str
    generation: int
    observed_at: datetime
    prior_run_id: str | None = None

    _ids = field_validator("watch_id", "owner", "token")(_pseudonym)

    @field_validator("prior_run_id")
    @classmethod
    def validate_prior_run_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("generation")
    @classmethod
    def validate_generation(cls, value: int) -> int:
        if isinstance(value, bool) or not 1 <= value <= 1_000_000_000:
            raise ValueError("watch generation is invalid")
        return value

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("watch persistence observation must be UTC")
        return value


class SessionModelEnsembleRunner(Protocol):
    def plan_fingerprint(
        self,
        metric_specs: tuple[EnsembleMetricSpec, ...],
    ) -> str: ...

    def run(
        self,
        chunk_plan: EnsembleChunkPlan,
        metric_specs: tuple[EnsembleMetricSpec, ...],
        *,
        progress_callback: Callable[[int, int], None] | None = None,
        prior_receipt: SessionModelEnsembleReceipt | None = None,
        typed_evidence: EphemeralTypedEvidenceProjection | None = None,
    ) -> SessionModelEnsembleReceipt: ...


class SessionTypedEvidenceProjector(Protocol):
    """Optional content-free provider-event bridge for the measured lane."""

    @property
    def descriptor(self) -> DecoderDescriptor: ...

    def project(
        self,
        *,
        provider: Provider,
        session_id: str,
    ) -> EphemeralTypedEvidenceProjection | None: ...

    def requirement_action_candidate_manifest(
        self,
        *,
        provider: Provider,
        session_id: str,
        source_run_id: str,
        source_window_fingerprint: str,
        projection: EphemeralTypedEvidenceProjection | None = None,
    ) -> RequirementActionCandidateManifest | None: ...


class SessionMetricLifecycleEvidenceReader(Protocol):
    """Content-free confirmed lifecycle receipts for one exact source window."""

    def snapshot(
        self,
        session_id: str,
        source_window_fingerprint: str,
    ) -> MetricLifecycleEvidenceSnapshot: ...


class SessionRequirementPlanEvidenceReader(Protocol):
    """Latest content-free reviewed requirement-plan authority for a session."""

    def latest_snapshot(self, session_id: str) -> RequirementPlanEvidenceSnapshot: ...


class SessionRequirementActionEvidenceReader(Protocol):
    """Latest content-free native-reviewed requirement/action authority."""

    def latest_snapshot(self, session_id: str) -> RequirementActionEvidenceSnapshot: ...


class SessionModelEnsembleRepository(Protocol):
    def save_completed(
        self,
        run: SessionModelEnsembleRunRecord,
        *,
        authority: SessionModelEnsemblePersistenceAuthority | None = None,
        semantic_units: SemanticUnitReconciliation | None = None,
    ) -> None: ...

    def get(self, run_id: str) -> SessionModelEnsembleRunRecord | None: ...

    def get_latest(self, session_id: str) -> SessionModelEnsembleRunRecord | None: ...

    def save_metric_projection(
        self,
        run: SessionModelEnsembleRunRecord,
        *,
        authority: SessionModelEnsemblePersistenceAuthority | None = None,
    ) -> None: ...

    def get_semantic_unit_reconciliation(
        self,
        run_id: str,
    ) -> SemanticUnitReconciliation | None: ...

    def delete_for_privacy(self, run_id: str) -> bool: ...


class SessionModelEnsembleError(RuntimeError):
    code = "model_ensemble_failed"


class ModelEnsembleInputError(SessionModelEnsembleError):
    code = "invalid_model_ensemble_request"


class ModelEnsembleConfirmationError(SessionModelEnsembleError):
    code = "model_ensemble_confirmation_required"


class ModelEnsembleConsentError(SessionModelEnsembleError):
    code = "redacted_content_consent_required"


class ModelEnsembleSelectionError(SessionModelEnsembleError):
    code = "session_not_in_safe_index"


class ModelEnsembleCompatibilityError(SessionModelEnsembleError):
    code = "provider_compatibility_blocked"


class ModelEnsembleSourceError(SessionModelEnsembleError):
    def __init__(self, reason: TextSourceFailureReason) -> None:
        self.reason = reason
        self.code = reason.value
        super().__init__(reason.value)


class ModelEnsembleExecutionError(SessionModelEnsembleError):
    code = "local_model_ensemble_execution_failed"


class ModelEnsembleRuntimeCleanupError(ModelEnsembleExecutionError):
    code = "model_ensemble_cleanup_unconfirmed"


class ModelEnsemblePersistenceError(SessionModelEnsembleError):
    code = "model_ensemble_persistence_failed"


class SessionModelEnsembleService:
    """Run the local measured-and-predictive cascade over a redacted window."""

    def __init__(
        self,
        access_policy: SessionTextAnalysisAccessPolicy,
        repository: SessionModelEnsembleRepository,
        source_factory: SessionTextAnalysisSourceFactory,
        compatibility_policy: SessionTextAnalysisCompatibilityPolicy,
        identifiers: SessionTextAnalysisIdFactory,
        runner: SessionModelEnsembleRunner,
        metric_engine: TextMetricEngine = DEFAULT_COACHING_METRIC_ENGINE,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        typed_evidence_projector: SessionTypedEvidenceProjector | None = None,
        semantic_unit_reconciler: SemanticUnitReconciler | None = None,
        lifecycle_evidence_reader: SessionMetricLifecycleEvidenceReader | None = None,
        declared_task_profile_reader: DeclaredTaskProfileRepository | None = None,
        requirement_plan_evidence_reader: (
            SessionRequirementPlanEvidenceReader | None
        ) = None,
        requirement_plan_review_contexts: (
            InMemoryRequirementPlanReviewContextStore | None
        ) = None,
        requirement_action_evidence_reader: (
            SessionRequirementActionEvidenceReader | None
        ) = None,
        requirement_action_review_contexts: (
            InMemoryRequirementActionReviewContextStore | None
        ) = None,
        requirement_verification_reader: (
            CurrentRequirementVerificationEvidenceReader | None
        ) = None,
    ) -> None:
        self._access_policy = access_policy
        self._repository = repository
        self._source_factory = source_factory
        self._compatibility_policy = compatibility_policy
        self._identifiers = identifiers
        self._runner = runner
        self._metric_engine = metric_engine
        self._clock = clock
        self._typed_evidence_projector = typed_evidence_projector
        self._semantic_unit_reconciler = semantic_unit_reconciler
        self._lifecycle_evidence_reader = lifecycle_evidence_reader
        self._declared_task_profile_reader = declared_task_profile_reader
        self._requirement_plan_evidence_reader = requirement_plan_evidence_reader
        self._requirement_plan_review_contexts = requirement_plan_review_contexts
        self._requirement_action_evidence_reader = (
            requirement_action_evidence_reader
        )
        self._requirement_action_review_contexts = (
            requirement_action_review_contexts
        )
        self._requirement_verification_reader = requirement_verification_reader
        self._lock = Lock()
        self._runtime_cleanup_failed = False

    @contextmanager
    def _execution_lane(self, progress_callback: Callable[[int, int], None] | None) -> Iterator[None]:
        # A queued watch must keep its lease and observe cancellation even
        # while another request owns the model lane. No source is read here.
        while not self._lock.acquire(timeout=0.1):
            if progress_callback is not None:
                progress_callback(0, MODEL_ENSEMBLE_MODEL_COUNT)
        try:
            if self._runtime_cleanup_failed:
                raise ModelEnsembleRuntimeCleanupError("local model cleanup was not confirmed")
            if progress_callback is not None:
                progress_callback(0, MODEL_ENSEMBLE_MODEL_COUNT)
            yield
        finally:
            self._lock.release()

    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        confirmation: str,
        idempotency_key: str,
        max_messages: int = COACHING_PROFILE_V1.max_messages,
        progress_callback: Callable[[int, int], None] | None = None,
        reuse_latest: bool = False,
        prior_run_id: str | None = None,
        persistence_authority: (
            Callable[[], SessionModelEnsemblePersistenceAuthority] | None
        ) = None,
    ) -> SessionModelEnsembleOutcome:
        if (
            # Migration 51 widened the ensemble tables to the text analysis providers.
            provider not in TEXT_ANALYSIS_PROVIDERS
            or PSEUDONYM_PATTERN.fullmatch(session_id) is None
            or _IDEMPOTENCY.fullmatch(idempotency_key) is None
            or not isinstance(max_messages, int)
            or isinstance(max_messages, bool)
            or not 1 <= max_messages <= COACHING_PROFILE_V1.max_messages
            or (
                prior_run_id is not None
                and PSEUDONYM_PATTERN.fullmatch(prior_run_id) is None
            )
        ):
            raise ModelEnsembleInputError("model ensemble selection is invalid")
        if confirmation not in {
            MODEL_ENSEMBLE_CONFIRMATION,
            LEGACY_MODEL_ENSEMBLE_CONFIRMATION,
        }:
            raise ModelEnsembleConfirmationError(
                "explicit model ensemble confirmation is required"
            )
        with self._execution_lane(progress_callback):
            self._enforce_access(provider, session_id)
            resolved_profile = self._resolve_metric_profile(provider, session_id)
            resolved_requirement_plan = self._resolve_requirement_plan_evidence(
                session_id
            )
            resolved_requirement_action = (
                self._resolve_requirement_action_evidence(session_id)
            )
            resolved_requirement_verification = (
                self._resolve_requirement_verification_evidence(
                    session_id,
                    resolved_requirement_plan,
                )
            )
            typed_evidence = self._project_typed_evidence(provider, session_id)
            candidate_preflight = self._preflight_requirement_action_candidates(
                provider=provider,
                session_id=session_id,
                typed_evidence=typed_evidence,
            )
            action_service_available = (
                resolved_requirement_action.evidence_source
                is not RequirementActionEvidenceSource.UNAVAILABLE
            )

            def request_identity(
                candidate_status: _RequirementActionCandidateStatus,
            ) -> tuple[str, str]:
                # The current namespace includes the revision-bound verification
                # identity. Historical request fingerprints remain stored verbatim.
                fingerprint = self._identifiers.fingerprint(
                    "session-model-ensemble-request-v8",
                    (
                        provider.value,
                        session_id,
                        idempotency_key,
                        MODEL_ENSEMBLE_POLICY_VERSION,
                        str(max_messages),
                        *resolved_profile.request_identity(),
                        *resolved_requirement_plan.request_identity(),
                        *resolved_requirement_action.request_identity(),
                        *resolved_requirement_verification.request_identity(),
                        candidate_status,
                    ),
                )
                return fingerprint, self._identifiers.fingerprint(
                    "session-model-ensemble-run-v1",
                    (session_id, fingerprint),
                )

            if not action_service_available:
                possible_candidate_statuses = ("unavailable",)
            elif candidate_preflight.overflow:
                possible_candidate_statuses = ("candidate_manifest_overflow",)
            elif candidate_preflight.status != "bounded":
                possible_candidate_statuses = ("candidate_source_incomplete",)
            else:
                # An exact replay can return before provider text is read. A
                # new request resolves the descriptor half of this closed pair
                # from the exact local context below.
                possible_candidate_statuses = (
                    "bounded",
                    "candidate_source_incomplete",
                )
            existing_runs = tuple(
                found
                for status in possible_candidate_statuses
                for _, candidate_run_id in (request_identity(status),)
                for found in (self._safe_get(candidate_run_id),)
                if found is not None
            )
            if len(existing_runs) > 1:
                raise ModelEnsemblePersistenceError(
                    "idempotent model ensemble request has conflicting source states"
                )
            if existing_runs:
                return SessionModelEnsembleOutcome(
                    run=existing_runs[0],
                    applied=False,
                )
            context = self._read_context(
                provider,
                session_id,
                max_messages,
                resolved_profile.task_profile,
            )
            preflight_review_surface_complete = (
                self._requirement_action_review_surface_complete(
                    candidate_preflight.manifest,
                    context,
                )
            )
            if not action_service_available:
                candidate_request_status: _RequirementActionCandidateStatus = (
                    "unavailable"
                )
            elif candidate_preflight.overflow:
                candidate_request_status = "candidate_manifest_overflow"
            elif (
                candidate_preflight.status == "bounded"
                and preflight_review_surface_complete
            ):
                candidate_request_status = "bounded"
            else:
                candidate_request_status = "candidate_source_incomplete"
            request_fingerprint, run_id = request_identity(candidate_request_status)
            current_candidates = self._recheck_requirement_action_candidates(
                provider=provider,
                session_id=session_id,
                source_run_id=run_id,
                context=context,
                typed_evidence=typed_evidence,
                preflight=candidate_preflight,
            )
            candidate_review_surface_complete = (
                self._requirement_action_review_surface_complete(
                    current_candidates.manifest,
                    context,
                )
            )
            candidate_manifest_overflow = (
                action_service_available and current_candidates.overflow
            )
            candidate_source_incomplete = (
                action_service_available
                and not candidate_manifest_overflow
                and not candidate_review_surface_complete
            )
            if candidate_source_incomplete != (
                candidate_request_status == "candidate_source_incomplete"
            ) or (
                candidate_manifest_overflow
                != (candidate_request_status == "candidate_manifest_overflow")
            ):
                raise ModelEnsemblePersistenceError(
                    "requirement-action review surface changed during analysis"
                )
            metric_profile_binding = self._bind_metric_profile(
                resolved_profile,
                context,
            )
            (
                requirement_plan_binding,
                requirement_plan_evidence,
            ) = self._bind_requirement_plan_evidence(
                resolved_requirement_plan,
                context,
            )
            (
                requirement_action_binding,
                requirement_action_evidence,
            ) = self._bind_requirement_action_evidence(
                resolved_requirement_action,
                context,
                requirement_plan_binding,
                requirement_plan_evidence,
                candidate_manifest_overflow=candidate_manifest_overflow,
                candidate_source_incomplete=candidate_source_incomplete,
                candidate_review_surface_complete=(
                    candidate_review_surface_complete
                ),
            )
            (
                requirement_verification_binding,
                requirement_verification_evidence,
            ) = self._bind_requirement_verification_evidence(
                resolved_requirement_verification,
                context,
                requirement_plan_binding,
                requirement_plan_evidence,
            )
            typed_metrics: tuple[SessionModelEnsembleTypedMetricReceipt, ...] | None = None
            metric_publication_v2: MetricPublicationV2 | None = None
            projection_completed_at: datetime | None = None
            latest: SessionModelEnsembleRunRecord | None = None
            prior_semantic_units: SemanticUnitReconciliation | None = None
            semantic_projection: SemanticUnitProjection | None = None
            specs = coaching_ensemble_metric_specs()
            try:
                current_plan_fingerprint = self._runner.plan_fingerprint(specs)
            except Exception:
                raise ModelEnsembleExecutionError(
                    "local model ensemble plan is unavailable"
                ) from None
            if reuse_latest:
                try:
                    latest = (
                        None
                        if prior_run_id is None
                        else self._repository.get(prior_run_id)
                    )
                except Exception:
                    raise ModelEnsemblePersistenceError(
                        "model ensemble results are unavailable"
                    ) from None
                compatible = latest is not None and (
                    latest.session_id == session_id
                    and latest.provider is provider
                    and latest.provider_version == context.provider_version
                    and latest.adapter_version == context.adapter_version
                    and latest.source_schema_version == context.source_schema_version
                    and latest.content_schema_version == context.content_schema_version
                    and latest.redactor_version == context.redactor_version
                    and self._metric_profile_identity_matches(
                        latest.metric_profile_binding,
                        metric_profile_binding,
                    )
                    and self._requirement_plan_identity_matches(
                        latest.requirement_plan_evidence_binding,
                        requirement_plan_binding,
                    )
                    and self._requirement_action_identity_matches(
                        latest.requirement_action_evidence_binding,
                        requirement_action_binding,
                    )
                    and self._requirement_verification_identity_matches(
                        latest.requirement_verification_evidence_binding,
                        requirement_verification_binding,
                    )
                    and not (
                        resolved_requirement_action.evidence_source
                        is RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
                        and requirement_action_binding.evidence_source
                        is not RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
                    )
                )
                if latest is not None and not compatible:
                    latest = None
                semantic_projection, prior_semantic_units = (
                    self._reconcile_semantic_units(context, latest)
                )
                typed_evidence = self._bind_objective_opportunities(
                    typed_evidence,
                    semantic_projection,
                )
                (
                    typed_metrics,
                    metric_publication_v2,
                    projection_completed_at,
                ) = self._project_metrics(
                    context,
                    semantic_projection,
                    typed_evidence,
                    requirement_plan_evidence,
                    requirement_action_evidence,
                    requirement_verification_evidence,
                    candidate_manifest_overflow,
                    candidate_source_incomplete,
                    (
                        requirement_action_binding.evidence_source
                        is RequirementActionEvidenceSource.BINDING_INVALID
                    ),
                )
                semantic_units_reusable = (
                    semantic_projection is None
                    or (
                        prior_semantic_units is not None
                        and not semantic_projection.reconciliation.appended
                        and semantic_projection.reconciliation.heads
                        == prior_semantic_units.heads
                    )
                )
                if (
                    latest is not None
                    and latest.input_fingerprint == context.analysis_window_fingerprint
                    and latest.receipt.plan_fingerprint == current_plan_fingerprint
                    and semantic_units_reusable
                ):
                    if (
                        latest.receipt.metric_projection_version
                        == MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
                        and latest.receipt.typed_metrics == typed_metrics
                        and latest.receipt.metric_publication_v2
                        == metric_publication_v2
                    ):
                        if progress_callback is not None:
                            progress_callback(10, 10)
                        self._publish_review_contexts(
                            latest,
                            context,
                            requirement_plan_evidence,
                            current_candidates.manifest,
                        )
                        return SessionModelEnsembleOutcome(run=latest, applied=False)
                    # R8 is revision-bound at run creation. It must never be
                    # appended to a pre-r8 sealed run that has no M59 binding.
                    # Provider event evidence is a second, content-free input
                    # plane. It may change while the bounded text window stays
                    # byte-identical, so a new run must be published instead
                    # of treating that measured change as version drift.
            if semantic_projection is None:
                semantic_projection, prior_semantic_units = (
                    self._reconcile_semantic_units(context, latest)
                )
            if (
                typed_metrics is None
                or metric_publication_v2 is None
                or projection_completed_at is None
            ):
                typed_evidence = self._bind_objective_opportunities(
                    typed_evidence,
                    semantic_projection,
                )
                (
                    typed_metrics,
                    metric_publication_v2,
                    projection_completed_at,
                ) = self._project_metrics(
                    context,
                    semantic_projection,
                    typed_evidence,
                    requirement_plan_evidence,
                    requirement_action_evidence,
                    requirement_verification_evidence,
                    candidate_manifest_overflow,
                    candidate_source_incomplete,
                    (
                        requirement_action_binding.evidence_source
                        is RequirementActionEvidenceSource.BINDING_INVALID
                    ),
                )
            plan = build_ensemble_chunks(context)
            try:
                receipt = self._run_pipeline(
                    plan,
                    specs,
                    progress_callback=progress_callback,
                    prior_receipt=None if latest is None else latest.receipt,
                    typed_evidence=typed_evidence,
                )
                projected_receipt = SessionModelEnsembleReceipt.model_validate(
                    {
                        **receipt.model_dump(),
                        "metric_projection_version": (
                            MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
                        ),
                        "metric_projection_completed_at": projection_completed_at,
                        "typed_metrics": typed_metrics,
                        "metric_publication_v2": metric_publication_v2,
                    }
                )
                record = SessionModelEnsembleRunRecord(
                    run_id=run_id,
                    session_id=session_id,
                    request_fingerprint=request_fingerprint,
                    input_fingerprint=context.analysis_window_fingerprint,
                    provider=provider,
                    provider_version=context.provider_version,
                    adapter_version=context.adapter_version,
                    source_schema_version=context.source_schema_version,
                    content_schema_version=context.content_schema_version,
                    redactor_version=context.redactor_version,
                    metric_profile_binding=metric_profile_binding,
                    requirement_plan_evidence_binding=(
                        requirement_plan_binding
                    ),
                    requirement_action_evidence_binding=(
                        requirement_action_binding
                    ),
                    requirement_verification_evidence_binding=(
                        requirement_verification_binding
                    ),
                    receipt=projected_receipt,
                )
            except RuntimeCooperativeStop:
                raise
            except RuntimeCleanupUnconfirmed:
                self._runtime_cleanup_failed = True
                raise ModelEnsembleRuntimeCleanupError("local model cleanup was not confirmed") from None
            except SessionModelEnsembleError:
                raise
            except Exception:
                raise ModelEnsembleExecutionError(
                    "local model ensemble failed"
                ) from None
            try:
                save_arguments = {}
                if persistence_authority is not None:
                    save_arguments["authority"] = persistence_authority()
                if semantic_projection is not None:
                    save_arguments["semantic_units"] = (
                        semantic_projection.reconciliation
                    )
                self._repository.save_completed(record, **save_arguments)
            except RuntimeCooperativeStop:
                raise
            except Exception:
                race = self._safe_get(run_id)
                if race is not None:
                    if semantic_projection is not None:
                        try:
                            race_semantic = (
                                self._repository.get_semantic_unit_reconciliation(
                                    run_id
                                )
                            )
                        except Exception:
                            race_semantic = None
                        if race_semantic != semantic_projection.reconciliation:
                            raise ModelEnsemblePersistenceError(
                                "semantic-unit sidecar could not be stored"
                            ) from None
                    self._publish_review_contexts(
                        race,
                        context,
                        requirement_plan_evidence,
                        current_candidates.manifest,
                    )
                    return SessionModelEnsembleOutcome(run=race, applied=False)
                raise ModelEnsemblePersistenceError(
                    "model ensemble result could not be stored"
                ) from None
            self._publish_review_contexts(
                record,
                context,
                requirement_plan_evidence,
                current_candidates.manifest,
            )
            return SessionModelEnsembleOutcome(run=record, applied=True)

    def _publish_review_contexts(
        self,
        run: SessionModelEnsembleRunRecord,
        context: P1TextAnalysisInput,
        requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None,
        candidate_manifest: RequirementActionCandidateManifest | None,
    ) -> None:
        plan_store = self._requirement_plan_review_contexts
        if plan_store is not None:
            try:
                plan_store.publish(run.run_id, context)
            except Exception:
                raise ModelEnsemblePersistenceError(
                    "ephemeral requirement-plan review context could not be prepared"
                ) from None
        action_store = self._requirement_action_review_contexts
        plan_binding = run.requirement_plan_evidence_binding
        if (
            action_store is None
            or candidate_manifest is None
            or requirement_plan_evidence is None
            or not requirement_plan_evidence.complete_user_clause_classification
            or requirement_plan_evidence.confirmation_id is None
            or plan_binding is None
            or plan_binding.evidence_source
            is not RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
        ):
            return
        try:
            manifest = self._rebind_requirement_action_candidate_manifest(
                candidate_manifest,
                source_run_id=run.run_id,
                source_window_fingerprint=context.analysis_window_fingerprint,
            )
            if (
                not self._requirement_action_review_surface_complete(
                    manifest,
                    context,
                )
            ):
                return
            action_store.publish(
                run.run_id,
                context,
                requirement_plan_evidence,
                plan_binding.evidence_fingerprint,
                manifest,
            )
        except Exception:
            raise ModelEnsemblePersistenceError(
                "ephemeral requirement-action review context could not be prepared"
            ) from None

    def latest(self, session_id: str) -> SessionModelEnsembleRunRecord | None:
        if PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise ModelEnsembleInputError("model ensemble selection is invalid")
        try:
            return self._repository.get_latest(session_id)
        except Exception:
            raise ModelEnsemblePersistenceError(
                "model ensemble results are unavailable"
            ) from None

    def get(self, run_id: str) -> SessionModelEnsembleRunRecord | None:
        """Load one exact sealed run without substituting a newer session run."""

        if PSEUDONYM_PATTERN.fullmatch(run_id) is None:
            raise ModelEnsembleInputError("model ensemble selection is invalid")
        return self._safe_get(run_id)

    def require_watchable(self, *, provider: Provider, session_id: str) -> None:
        """Validate standing local authority without reading session content."""

        if provider not in TEXT_ANALYSIS_PROVIDERS or PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise ModelEnsembleInputError("model ensemble selection is invalid")
        self._enforce_access(provider, session_id)

    def _safe_get(self, run_id: str) -> SessionModelEnsembleRunRecord | None:
        try:
            return self._repository.get(run_id)
        except Exception:
            raise ModelEnsemblePersistenceError(
                "model ensemble persistence is unavailable"
            ) from None

    def _enforce_access(self, provider: Provider, session_id: str) -> None:
        try:
            consent = self._access_policy.has_active_consent(
                provider, DataTier.REDACTED_CONTENT
            )
        except Exception:
            raise ModelEnsembleConsentError(
                "redacted-content consent is unavailable"
            ) from None
        if not consent:
            raise ModelEnsembleConsentError("redacted-content consent is required")
        try:
            indexed = self._access_policy.selection_is_indexed(
                provider,
                project_ids=frozenset(),
                session_ids=frozenset((session_id,)),
            )
        except Exception:
            raise ModelEnsembleSelectionError("safe selection is unavailable") from None
        if not indexed:
            raise ModelEnsembleSelectionError(
                "session is not present in the safe index"
            )
        try:
            self._compatibility_policy.require_compatible(provider.value)
        except Exception:
            raise ModelEnsembleCompatibilityError(
                "provider compatibility is not verified"
            ) from None

    def _resolve_metric_profile(
        self,
        provider: Provider,
        session_id: str,
    ) -> _ResolvedMetricProfile:
        reader = self._declared_task_profile_reader
        if reader is None:
            return _ResolvedMetricProfile(
                task_profile=COACHING_PROFILE_V1.task_profile,
                declaration=None,
            )
        try:
            declaration = reader.get_latest(provider, session_id)
        except Exception:
            raise ModelEnsemblePersistenceError(
                "reviewed task profile is unavailable"
            ) from None
        if declaration is None:
            return _ResolvedMetricProfile(
                task_profile=COACHING_PROFILE_V1.task_profile,
                declaration=None,
            )
        if (
            declaration.provider is not provider
            or declaration.session_id != session_id
        ):
            raise ModelEnsemblePersistenceError(
                "reviewed task profile is bound to another session"
            )
        try:
            task_profile = apply_declared_task_profile(
                COACHING_PROFILE_V1.task_profile,
                declaration,
            )
        except (TypeError, ValueError):
            raise ModelEnsemblePersistenceError(
                "reviewed task profile is invalid"
            ) from None
        return _ResolvedMetricProfile(
            task_profile=task_profile,
            declaration=declaration,
        )

    def _bind_metric_profile(
        self,
        resolved: _ResolvedMetricProfile,
        context: P1TextAnalysisInput,
    ) -> SessionMetricProfileBinding:
        declaration = resolved.declaration
        try:
            return SessionMetricProfileBinding(
                profile_source=resolved.source,
                provider=context.provider,
                session_id=context.session_id,
                source_window_fingerprint=context.analysis_window_fingerprint,
                profile_id=(None if declaration is None else declaration.profile_id),
                profile_revision=(
                    None if declaration is None else declaration.revision
                ),
                profile_fingerprint=(
                    COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT
                    if declaration is None
                    else declaration.profile_fingerprint
                ),
                profile_schema_version=(
                    COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION
                    if declaration is None
                    else declaration.schema_version
                ),
                profile_policy_version=(
                    COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION
                    if declaration is None
                    else declaration.policy_version
                ),
                bound_at=self._clock(),
                local_only=True,
                content_persisted=False,
            )
        except (TypeError, ValueError):
            raise ModelEnsemblePersistenceError(
                "metric profile binding could not be issued"
            ) from None

    def _resolve_requirement_plan_evidence(
        self,
        session_id: str,
    ) -> _ResolvedRequirementPlanEvidence:
        reader = self._requirement_plan_evidence_reader
        if reader is None:
            return _ResolvedRequirementPlanEvidence(
                snapshot=None,
                evidence_source=RequirementPlanEvidenceSource.UNAVAILABLE,
                evidence_fingerprint=REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT,
            )
        try:
            snapshot = reader.latest_snapshot(session_id)
        except Exception:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-plan evidence is unavailable"
            ) from None
        if snapshot.session_id != session_id:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-plan evidence belongs elsewhere"
            )
        if not snapshot.complete_user_clause_classification:
            return _ResolvedRequirementPlanEvidence(
                snapshot=snapshot,
                evidence_source=RequirementPlanEvidenceSource.AWAITING_REVIEW,
                evidence_fingerprint=(
                    REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT
                ),
            )
        try:
            fingerprint = requirement_plan_snapshot_fingerprint(
                snapshot,
                self._identifiers,
            )
        except Exception:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-plan evidence is invalid"
            ) from None
        return _ResolvedRequirementPlanEvidence(
            snapshot=snapshot,
            evidence_source=RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN,
            evidence_fingerprint=fingerprint,
        )

    def _resolve_requirement_verification_evidence(
        self,
        session_id: str,
        requirement_plan: _ResolvedRequirementPlanEvidence,
    ) -> _ResolvedRequirementVerificationEvidence:
        reader = self._requirement_verification_reader
        snapshot = requirement_plan.snapshot
        if (
            reader is None
            or snapshot is None
            or requirement_plan.evidence_source
            is not RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
            or not snapshot.complete_user_clause_classification
            or snapshot.confirmation_id is None
            or snapshot.proposal_id is None
            or snapshot.producer_receipt is None
        ):
            return _ResolvedRequirementVerificationEvidence(
                evidence_source=RequirementVerificationEvidenceSource.UNAVAILABLE
            )
        try:
            opportunities = issue_requirement_verification_opportunities(
                snapshot,
                self._identifiers,
            )
        except Exception:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-verification denominator is invalid"
            ) from None
        if (
            len(opportunities.opportunities)
            > MAX_REQUIREMENT_VERIFICATION_OPPORTUNITIES
        ):
            return _ResolvedRequirementVerificationEvidence(
                evidence_source=(
                    RequirementVerificationEvidenceSource.OPPORTUNITY_BOUND_EXCEEDED
                ),
                opportunities=opportunities,
            )
        try:
            persisted = reader.snapshot_for_requirement_plan(
                session_id,
                snapshot.confirmation_id,
            )
        except Exception:
            raise ModelEnsemblePersistenceError(
                "requirement-verification evidence is unavailable"
            ) from None
        if persisted is None:
            return _ResolvedRequirementVerificationEvidence(
                evidence_source=(
                    RequirementVerificationEvidenceSource.AWAITING_EVIDENCE
                ),
                opportunities=opportunities,
            )
        try:
            validated_snapshot = RequirementVerificationEvidenceSnapshot.model_validate(
                persisted.model_dump(mode="python")
            )
            validated_evidence = validate_requirement_verification_evidence_set(
                validated_snapshot.evidence,
                snapshot,
                self._identifiers,
            )
            if (
                validated_snapshot.evidence != validated_evidence
                or validated_evidence.opportunities != opportunities
                or validated_evidence.opportunities.session_id != session_id
            ):
                raise ValueError("verification snapshot belongs elsewhere")
        except Exception:
            raise ModelEnsemblePersistenceError(
                "requirement-verification evidence is invalid"
            ) from None
        return _ResolvedRequirementVerificationEvidence(
            evidence_source=RequirementVerificationEvidenceSource.PERSISTED_EVIDENCE,
            opportunities=opportunities,
            snapshot=validated_snapshot,
        )

    def _bind_requirement_plan_evidence(
        self,
        resolved: _ResolvedRequirementPlanEvidence,
        context: P1TextAnalysisInput,
    ) -> tuple[
        SessionRequirementPlanEvidenceBinding,
        RequirementPlanEvidenceSnapshot | None,
    ]:
        snapshot = resolved.snapshot
        reviewed = (
            snapshot
            if snapshot is not None
            and snapshot.complete_user_clause_classification
            and snapshot.source_window_fingerprint
            == context.analysis_window_fingerprint
            else None
        )
        try:
            if reviewed is None:
                service_available = (
                    resolved.evidence_source
                    is not RequirementPlanEvidenceSource.UNAVAILABLE
                )
                return (
                    SessionRequirementPlanEvidenceBinding(
                        evidence_source=(
                            RequirementPlanEvidenceSource.AWAITING_REVIEW
                            if service_available
                            else RequirementPlanEvidenceSource.UNAVAILABLE
                        ),
                        session_id=context.session_id,
                        source_window_fingerprint=(
                            context.analysis_window_fingerprint
                        ),
                        evidence_fingerprint=(
                            REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT
                            if service_available
                            else REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT
                        ),
                        evidence_schema_version=(
                            REQUIREMENT_PLAN_AWAITING_REVIEW_SCHEMA_VERSION
                            if service_available
                            else REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION
                        ),
                        evidence_policy_version=(
                            REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION
                        ),
                        bound_at=self._clock(),
                    ),
                    (
                        RequirementPlanEvidenceSnapshot(
                            session_id=context.session_id,
                            source_window_fingerprint=(
                                context.analysis_window_fingerprint
                            ),
                        )
                        if service_available
                        else None
                    ),
                )
            return (
                SessionRequirementPlanEvidenceBinding(
                    evidence_source=(
                        RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
                    ),
                    session_id=context.session_id,
                    source_window_fingerprint=context.analysis_window_fingerprint,
                    confirmation_id=reviewed.confirmation_id,
                    proposal_id=reviewed.proposal_id,
                    evidence_fingerprint=resolved.evidence_fingerprint,
                    evidence_schema_version=reviewed.schema_version,
                    evidence_policy_version=reviewed.policy_version,
                    bound_at=self._clock(),
                ),
                reviewed,
            )
        except (TypeError, ValueError):
            raise ModelEnsemblePersistenceError(
                "requirement-plan binding could not be issued"
            ) from None

    def _resolve_requirement_action_evidence(
        self,
        session_id: str,
    ) -> _ResolvedRequirementActionEvidence:
        reader = self._requirement_action_evidence_reader
        if reader is None:
            return _ResolvedRequirementActionEvidence(
                snapshot=None,
                evidence_source=RequirementActionEvidenceSource.UNAVAILABLE,
            )
        try:
            snapshot = reader.latest_snapshot(session_id)
        except Exception:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-action evidence is unavailable"
            ) from None
        if snapshot.session_id != session_id:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-action evidence belongs elsewhere"
            )
        if snapshot.confirmation_id is None:
            return _ResolvedRequirementActionEvidence(
                snapshot=snapshot,
                evidence_source=RequirementActionEvidenceSource.AWAITING_REVIEW,
            )
        try:
            expected = requirement_action_evidence_snapshot_fingerprint(
                snapshot, self._identifiers
            )
        except (TypeError, ValueError):
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-action evidence is invalid"
            ) from None
        if snapshot.evidence_fingerprint != expected:
            raise ModelEnsemblePersistenceError(
                "reviewed requirement-action evidence fingerprint is invalid"
            )
        return _ResolvedRequirementActionEvidence(
            snapshot=snapshot,
            evidence_source=(
                RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
            ),
        )

    def _bind_requirement_action_evidence(
        self,
        resolved: _ResolvedRequirementActionEvidence,
        context: P1TextAnalysisInput,
        requirement_plan_binding: SessionRequirementPlanEvidenceBinding,
        requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None,
        *,
        candidate_manifest_overflow: bool,
        candidate_source_incomplete: bool,
        candidate_review_surface_complete: bool,
    ) -> tuple[
        SessionRequirementActionEvidenceBinding,
        RequirementActionEvidenceSnapshot | None,
    ]:
        snapshot = resolved.snapshot
        reviewed = (
            snapshot
            if not candidate_manifest_overflow
            and not candidate_source_incomplete
            and candidate_review_surface_complete
            and snapshot is not None
            and snapshot.confirmation_id is not None
            and snapshot.source_window_fingerprint
            == context.analysis_window_fingerprint
            and snapshot.requirement_plan_confirmation_id
            == requirement_plan_binding.confirmation_id
            and snapshot.requirement_plan_evidence_fingerprint
            == requirement_plan_binding.evidence_fingerprint
            and requirement_plan_binding.evidence_source
            is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
            and requirement_plan_evidence is not None
            and self._requirement_action_source_run_matches(
                snapshot,
                context,
                requirement_plan_binding,
            )
            and self._requirement_action_manifest_matches(snapshot, context)
            else None
        )
        try:
            if reviewed is None:
                service_available = (
                    resolved.evidence_source
                    is not RequirementActionEvidenceSource.UNAVAILABLE
                )
                binding_invalid = (
                    resolved.evidence_source
                    is RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
                )
                source = (
                    RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW
                    if candidate_manifest_overflow
                    else RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE
                    if candidate_source_incomplete
                    else RequirementActionEvidenceSource.BINDING_INVALID
                    if binding_invalid
                    else RequirementActionEvidenceSource.AWAITING_REVIEW
                    if service_available
                    else RequirementActionEvidenceSource.UNAVAILABLE
                )
                return (
                    SessionRequirementActionEvidenceBinding(
                        evidence_source=source,
                        session_id=context.session_id,
                        source_window_fingerprint=(
                            context.analysis_window_fingerprint
                        ),
                        evidence_fingerprint=(
                            REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT
                            if candidate_manifest_overflow
                            else REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT
                            if candidate_source_incomplete
                            else REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT
                            if binding_invalid
                            else
                            REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT
                            if service_available
                            else REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT
                        ),
                        evidence_schema_version=(
                            REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION
                            if candidate_manifest_overflow
                            else REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION
                            if candidate_source_incomplete
                            else REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION
                            if binding_invalid
                            else
                            REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION
                            if service_available
                            else REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION
                        ),
                        evidence_policy_version=(
                            REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION
                        ),
                        bound_at=self._clock(),
                    ),
                    (
                        RequirementActionEvidenceSnapshot(
                            session_id=context.session_id,
                            source_window_fingerprint=(
                                context.analysis_window_fingerprint
                            ),
                        )
                        if service_available
                        else None
                    ),
                )
            assert reviewed.source_run_id is not None
            assert reviewed.requirement_plan_confirmation_id is not None
            assert reviewed.requirement_plan_evidence_fingerprint is not None
            assert reviewed.candidate_manifest is not None
            assert reviewed.confirmation_id is not None
            assert reviewed.proposal_id is not None
            assert reviewed.reviewed_descriptor_set_fingerprint is not None
            assert reviewed.evidence_fingerprint is not None
            return (
                SessionRequirementActionEvidenceBinding(
                    evidence_source=(
                        RequirementActionEvidenceSource
                        .REVIEWED_REQUIREMENT_ACTION
                    ),
                    session_id=context.session_id,
                    source_window_fingerprint=(
                        context.analysis_window_fingerprint
                    ),
                    source_run_id=reviewed.source_run_id,
                    requirement_plan_confirmation_id=(
                        reviewed.requirement_plan_confirmation_id
                    ),
                    requirement_plan_evidence_fingerprint=(
                        reviewed.requirement_plan_evidence_fingerprint
                    ),
                    candidate_manifest_fingerprint=(
                        reviewed.candidate_manifest.manifest_fingerprint
                    ),
                    confirmation_id=reviewed.confirmation_id,
                    proposal_id=reviewed.proposal_id,
                    reviewed_descriptor_set_fingerprint=(
                        reviewed.reviewed_descriptor_set_fingerprint
                    ),
                    evidence_fingerprint=reviewed.evidence_fingerprint,
                    evidence_schema_version=reviewed.schema_version,
                    evidence_policy_version=reviewed.policy_version,
                    bound_at=self._clock(),
                ),
                reviewed,
            )
        except (TypeError, ValueError):
            raise ModelEnsemblePersistenceError(
                "requirement-action binding could not be issued"
            ) from None

    def _bind_requirement_verification_evidence(
        self,
        resolved: _ResolvedRequirementVerificationEvidence,
        context: P1TextAnalysisInput,
        requirement_plan_binding: SessionRequirementPlanEvidenceBinding,
        requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None,
    ) -> tuple[
        SessionRequirementVerificationEvidenceBinding,
        RequirementVerificationEvidenceSet | None,
    ]:
        opportunities = resolved.opportunities
        reviewed = (
            requirement_plan_evidence
            if requirement_plan_evidence is not None
            and requirement_plan_evidence.complete_user_clause_classification
            and requirement_plan_evidence.confirmation_id is not None
            and requirement_plan_evidence.proposal_id is not None
            and requirement_plan_binding.evidence_source
            is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
            else None
        )
        if reviewed is None or resolved.evidence_source is (
            RequirementVerificationEvidenceSource.UNAVAILABLE
        ):
            source = RequirementVerificationEvidenceSource.UNAVAILABLE
            opportunities = None
        else:
            source = resolved.evidence_source
            if (
                opportunities is None
                or opportunities.session_id != context.session_id
                or opportunities.source_window_fingerprint
                != context.analysis_window_fingerprint
                or opportunities.requirement_plan_confirmation_id
                != reviewed.confirmation_id
                or opportunities.requirement_plan_proposal_id
                != reviewed.proposal_id
                or opportunities.requirement_plan_evidence_fingerprint
                != requirement_plan_binding.evidence_fingerprint
            ):
                raise ModelEnsemblePersistenceError(
                    "requirement-verification authority changed during analysis"
                )
        persisted = (
            resolved.snapshot
            if source is RequirementVerificationEvidenceSource.PERSISTED_EVIDENCE
            else None
        )
        evidence = None if persisted is None else persisted.evidence
        objective_result_count = (
            None if evidence is None else len(evidence.verification_results)
        )
        native_acceptance_count = (
            None if evidence is None else len(evidence.acceptance_authorities)
        )
        resolved_count = (
            None
            if evidence is None
            else sum(
                item.outcome is not RequirementVerificationOutcome.UNKNOWN
                for item in evidence.verification_results
            )
            + sum(
                item.outcome is not RequirementAcceptanceOutcome.UNKNOWN
                for item in evidence.acceptance_authorities
            )
        )
        met_count = (
            None
            if evidence is None
            else sum(
                item.outcome is RequirementVerificationOutcome.PASSED
                for item in evidence.verification_results
            )
            + sum(
                item.outcome is RequirementAcceptanceOutcome.ACCEPTED
                for item in evidence.acceptance_authorities
            )
        )
        if source is RequirementVerificationEvidenceSource.AWAITING_EVIDENCE:
            authority_head_count = 0
            objective_result_count = 0
            native_acceptance_count = 0
            resolved_count = 0
            met_count = 0
        elif persisted is None:
            authority_head_count = None
        else:
            authority_head_count = len(persisted.authority_heads)
        data = {
            "evidence_source": source,
            "session_id": context.session_id,
            "source_window_fingerprint": context.analysis_window_fingerprint,
            "requirement_plan_confirmation_id": (
                None if opportunities is None else opportunities.requirement_plan_confirmation_id
            ),
            "requirement_plan_proposal_id": (
                None if opportunities is None else opportunities.requirement_plan_proposal_id
            ),
            "requirement_plan_evidence_fingerprint": (
                None if opportunities is None else opportunities.requirement_plan_evidence_fingerprint
            ),
            "requirement_plan_schema_version": (
                None if opportunities is None else opportunities.requirement_plan_schema_version
            ),
            "requirement_plan_policy_version": (
                None if opportunities is None else opportunities.requirement_plan_policy_version
            ),
            "requirement_plan_review_rubric_version": (
                None
                if opportunities is None
                else opportunities.requirement_plan_review_rubric_version
            ),
            "opportunity_count": (
                None if opportunities is None else len(opportunities.opportunities)
            ),
            "opportunity_set_fingerprint": (
                None if opportunities is None else opportunities.opportunity_set_fingerprint
            ),
            "evidence_set_fingerprint": (
                None if evidence is None else evidence.evidence_set_fingerprint
            ),
            "through_revision": (
                None if persisted is None else persisted.revision
            ),
            "authority_head_count": authority_head_count,
            "objective_result_count": objective_result_count,
            "native_acceptance_count": native_acceptance_count,
            "resolved_opportunity_count": resolved_count,
            "met_requirement_count": met_count,
            "opportunity_issuer_version": (
                REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION
            ),
            "result_issuer_version": REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
            "acceptance_issuer_version": (
                REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION
            ),
            "evidence_schema_version": (
                REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION
            ),
            "evidence_policy_version": (
                REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION
            ),
            "persistence_schema_version": (
                REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION
            ),
            "evidence_projection_version": (
                REQUIREMENT_VERIFICATION_PROJECTION_VERSION
            ),
            "objective_projection_version": OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
            "binding_schema_version": (
                REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION
            ),
            "bound_at": self._clock(),
        }
        try:
            draft = SessionRequirementVerificationEvidenceBinding(
                **data,
                binding_fingerprint="0" * 64,
            )
            binding_fingerprint = self._identifiers.fingerprint(
                REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
                draft.authority_identity(),
            )
            binding = SessionRequirementVerificationEvidenceBinding(
                **data,
                binding_fingerprint=binding_fingerprint,
            )
        except Exception:
            raise ModelEnsemblePersistenceError(
                "requirement-verification binding could not be issued"
            ) from None
        return binding, evidence

    @staticmethod
    def _metric_profile_identity_matches(
        stored: SessionMetricProfileBinding | None,
        current: SessionMetricProfileBinding,
    ) -> bool:
        return stored is not None and stored.model_dump(
            exclude={"bound_at"}
        ) == current.model_dump(exclude={"bound_at"})

    @staticmethod
    def _requirement_plan_identity_matches(
        stored: SessionRequirementPlanEvidenceBinding | None,
        current: SessionRequirementPlanEvidenceBinding,
    ) -> bool:
        return stored is not None and stored.model_dump(
            exclude={"bound_at"}
        ) == current.model_dump(exclude={"bound_at"})

    @staticmethod
    def _requirement_action_identity_matches(
        stored: SessionRequirementActionEvidenceBinding | None,
        current: SessionRequirementActionEvidenceBinding,
    ) -> bool:
        return stored is not None and stored.authority_identity() == (
            current.authority_identity()
        )

    @staticmethod
    def _requirement_verification_identity_matches(
        stored: SessionRequirementVerificationEvidenceBinding | None,
        current: SessionRequirementVerificationEvidenceBinding,
    ) -> bool:
        return stored is not None and stored.authority_identity() == (
            current.authority_identity()
        )

    def _requirement_action_source_run_matches(
        self,
        snapshot: RequirementActionEvidenceSnapshot,
        context: P1TextAnalysisInput,
        requirement_plan_binding: SessionRequirementPlanEvidenceBinding,
    ) -> bool:
        """Require the reviewed graph's source to be one exact sealed r6-r8 run."""

        source_run_id = snapshot.source_run_id
        if source_run_id is None:
            return False
        try:
            source_run = self._repository.get(source_run_id)
        except Exception:
            raise ModelEnsemblePersistenceError(
                "requirement-action source run is unavailable"
            ) from None
        if source_run is None:
            return False
        publication = source_run.receipt.metric_publication_v2
        source_plan = source_run.requirement_plan_evidence_binding
        return (
            source_run.run_id == source_run_id
            and source_run.session_id == context.session_id
            and source_run.input_fingerprint
            == context.analysis_window_fingerprint
            and snapshot.source_window_fingerprint
            == source_run.input_fingerprint
            and publication is not None
            and publication.projection_version
            in {
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
            and source_plan is not None
            and source_plan.evidence_source
            is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
            and source_plan.session_id == context.session_id
            and source_plan.source_window_fingerprint
            == context.analysis_window_fingerprint
            and source_plan.confirmation_id
            == snapshot.requirement_plan_confirmation_id
            and source_plan.evidence_fingerprint
            == snapshot.requirement_plan_evidence_fingerprint
            and self._requirement_plan_identity_matches(
                source_plan,
                requirement_plan_binding,
            )
        )

    def _requirement_action_manifest_matches(
        self,
        snapshot: RequirementActionEvidenceSnapshot,
        context: P1TextAnalysisInput,
    ) -> bool:
        """Reject an old review when the current safe action set has drifted."""

        source_run_id = snapshot.source_run_id
        reviewed_manifest = snapshot.candidate_manifest
        projector = self._typed_evidence_projector
        if source_run_id is None or reviewed_manifest is None or projector is None:
            return False
        try:
            current_manifest = projector.requirement_action_candidate_manifest(
                provider=context.provider,
                session_id=context.session_id,
                source_run_id=source_run_id,
                source_window_fingerprint=(
                    context.analysis_window_fingerprint
                ),
            )
        except RequirementActionCandidateManifestOverflowError:
            return False
        except Exception:
            raise ModelEnsemblePersistenceError(
                "current requirement-action manifest is unavailable"
            ) from None
        if (
            current_manifest is None
            or not current_manifest.extraction_complete
            or not current_manifest.enumeration_complete
        ):
            return False
        try:
            current_fingerprint = (
                requirement_action_candidate_manifest_fingerprint(
                    current_manifest
                )
            )
        except (TypeError, ValueError):
            return False
        return (
            current_manifest.manifest_fingerprint == current_fingerprint
            and current_manifest == reviewed_manifest
        )

    def _read_context(
        self,
        provider: Provider,
        session_id: str,
        max_messages: int,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput:
        selection = TextAnalysisSelection(
            provider=provider,
            session_id=session_id,
            max_messages=max_messages,
            max_characters=COACHING_PROFILE_V1.max_characters,
        )
        grant = TextSourceAccessGrant(
            purpose=TextAnalysisPurpose.TEXT_ANALYSIS,
            provider=provider,
            session_id=session_id,
            data_tier=DataTier.REDACTED_CONTENT,
            per_run_confirmation_active=True,
            local_only=True,
            content_persistence_allowed=False,
        )
        try:
            source = self._source_factory(provider)
            context = source.read(
                selection=selection,
                grant=grant,
                task_profile=task_profile,
            )
        except TextSourceReadError as error:
            raise ModelEnsembleSourceError(error.reason) from None
        except Exception:
            raise ModelEnsembleSourceError(
                TextSourceFailureReason.PROVIDER_UNAVAILABLE
            ) from None
        if (
            context.provider is not provider
            or context.session_id != session_id
            or context.task_profile != task_profile
        ):
            raise ModelEnsembleSourceError(
                TextSourceFailureReason.PROVIDER_UNAVAILABLE
            )
        return context

    def _read_lifecycle_evidence(
        self,
        context: P1TextAnalysisInput,
    ) -> MetricLifecycleEvidenceSnapshot | None:
        if self._lifecycle_evidence_reader is None:
            return None
        try:
            snapshot = self._lifecycle_evidence_reader.snapshot(
                context.session_id,
                context.analysis_window_fingerprint,
            )
        except Exception:
            raise ModelEnsemblePersistenceError(
                "confirmed lifecycle evidence is unavailable"
            ) from None
        if (
            snapshot.session_id != context.session_id
            or snapshot.source_window_fingerprint
            != context.analysis_window_fingerprint
        ):
            raise ModelEnsemblePersistenceError(
                "confirmed lifecycle evidence is bound to another window"
            )
        return snapshot

    def _project_metrics(
        self,
        context: P1TextAnalysisInput,
        semantic_projection: SemanticUnitProjection | None,
        typed_evidence: EphemeralTypedEvidenceProjection | None = None,
        requirement_plan_evidence: RequirementPlanEvidenceSnapshot | None = None,
        requirement_action_evidence: RequirementActionEvidenceSnapshot | None = None,
        requirement_verification_evidence: (
            RequirementVerificationEvidenceSet | None
        ) = None,
        candidate_manifest_overflow: bool = False,
        candidate_source_incomplete: bool = False,
        requirement_action_binding_invalid: bool = False,
    ) -> tuple[
        tuple[SessionModelEnsembleTypedMetricReceipt, ...],
        MetricPublicationV2,
        datetime,
    ]:
        grant = P1LocalAnalysisGrant(
            provider=context.provider,
            session_id=context.session_id,
            analysis_window_fingerprint=context.analysis_window_fingerprint,
            data_tier=DataTier.REDACTED_CONTENT,
            consent_active=True,
            local_only=True,
            content_persistence_allowed=False,
        )
        try:
            results = self._metric_engine.compute(
                context,
                grant,
                pack_key=COACHING_METRIC_PACK_KEY,
                pack_version=COACHING_METRIC_PACK_VERSION,
            )
            projected_at = self._clock()
            if projected_at.tzinfo is None or projected_at.utcoffset() != timedelta(0):
                raise ValueError("metric projection clock must return UTC")
            # Current code writes projection identity r8 only. Frozen earlier
            # producers remain importable so historical rows retain the exact
            # meaning of the algorithm that wrote them.
            objective_overrides = project_objective_metric_overrides_v4(
                typed_evidence,
                self._objective_evidence_descriptor(
                    context.provider, typed_evidence
                ),
                requirement_plan_evidence=requirement_plan_evidence,
                requirement_verification_evidence=(
                    requirement_verification_evidence
                ),
                identifiers=self._identifiers,
            )
            live_states = project_metric_states_v8(
                context=context,
                reconciliation=(
                    None
                    if semantic_projection is None
                    else semantic_projection.reconciliation
                ),
                id_factory=self._identifiers,
                conversational_results={
                    item.observation.key: item for item in results
                },
                objective_overrides=objective_overrides,
                lifecycle_evidence=self._read_lifecycle_evidence(context),
                requirement_plan_evidence=requirement_plan_evidence,
                requirement_action_evidence=requirement_action_evidence,
                requirement_action_descriptor=self._objective_evidence_descriptor(
                    context.provider, typed_evidence
                ),
                candidate_manifest_overflow=candidate_manifest_overflow,
                candidate_source_incomplete=candidate_source_incomplete,
                requirement_action_binding_invalid=(
                    requirement_action_binding_invalid
                ),
            )
            metric_publication_v2 = publish_metric_states_v2(live_states)
            projected_items: list[SessionModelEnsembleTypedMetricReceipt] = []
            for result in results:
                objective_override = objective_overrides.get(result.observation.key)
                persisted_verification_override = (
                    result.observation.key == VERIFIED_REQUIREMENT_METRIC_KEY
                )
                objective_eligible_count = (
                    0
                    if objective_override is None
                    else objective_override.eligible_opportunity_count
                )
                objective_observed_count = (
                    0
                    if objective_override is None
                    else objective_override.resolved_opportunity_count
                )
                projected_items.append(SessionModelEnsembleTypedMetricReceipt(
                    metric_key=result.observation.key,
                    metric_version=result.observation.version,
                    value_state=(
                        objective_override.value_state
                        if objective_override is not None
                        else result.value_state
                    ),
                    numerator=(
                        objective_override.numerator
                        if objective_override is not None
                        else None
                        if result.fraction is None
                        else result.fraction.numerator
                    ),
                    denominator=(
                        objective_override.denominator
                        if objective_override is not None
                        else None
                        if result.fraction is None
                        else result.fraction.denominator
                    ),
                    numeric_value=(
                        (
                            objective_override.numerator
                            / objective_override.denominator
                        )
                        if objective_override is not None
                        and objective_override.numerator is not None
                        and objective_override.denominator is not None
                        else None
                        if objective_override is not None
                        else result.observation.numeric_value
                    ),
                    observed_message_count=(
                        objective_observed_count
                        if objective_override is not None
                        else result.observation.observed_count
                    ),
                    eligible_message_count=(
                        objective_eligible_count
                        if objective_override is not None
                        else result.observation.eligible_count
                    ),
                    coverage=(
                        (
                            0.0
                            if objective_eligible_count == 0
                            else objective_observed_count
                            / objective_eligible_count
                        )
                        if objective_override is not None
                        else result.observation.coverage
                    ),
                    explanation_code=(
                        objective_override.explanation_code
                        if objective_override is not None
                        else result.explanation_code
                    ),
                    error_code=(
                        None
                        if objective_override is not None
                        else result.error_code
                    ),
                    projection_source="deterministic_typed_contract",
                    metric_schema_version=result.provenance.metric_schema_version,
                    engine_version=(
                        OBJECTIVE_METRIC_PROJECTION_V4_VERSION
                        if persisted_verification_override
                        else "typed-objective-evidence-v2"
                        if objective_override is not None
                        else self._metric_engine.engine_version
                    ),
                    algorithm_id=(
                        VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID
                        if persisted_verification_override
                        else "typed-objective-evidence"
                        if objective_override is not None
                        else result.provenance.algorithm_id
                    ),
                    algorithm_version=(
                        VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION
                        if persisted_verification_override
                        else "2"
                        if objective_override is not None
                        else result.provenance.algorithm_version
                    ),
                    rubric_version=(
                        VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION
                        if persisted_verification_override
                        else "objective-evidence-no-rubric-v2"
                        if objective_override is not None
                        else self._metric_engine.rubric_version
                    ),
                    calibration_state="not_assessed",
                    product_metric_eligible=False,
                ))
            projected = tuple(projected_items)
        except SessionModelEnsembleError:
            raise
        except Exception:
            raise ModelEnsembleExecutionError(
                "typed local metric projection failed"
            ) from None
        return projected, metric_publication_v2, projected_at

    def _project_typed_evidence(
        self,
        provider: Provider,
        session_id: str,
    ) -> EphemeralTypedEvidenceProjection | None:
        if self._typed_evidence_projector is None:
            return None
        try:
            projection = self._typed_evidence_projector.project(
                provider=provider,
                session_id=session_id,
            )
            if projection is None:
                return None
            if (
                projection.session_id != session_id
                or projection.provenance.provider is not provider
            ):
                raise ValueError("typed evidence belongs to another session")
            validate_projection_descriptor(
                projection,
                self._objective_evidence_descriptor(provider, projection),
            )
            return projection
        except Exception:
            # The safe metadata bridge is additive. Losing it must withhold
            # objective measurements, never discard deterministic text output.
            return None

    @staticmethod
    def _requirement_action_candidate_status(
        manifest: RequirementActionCandidateManifest | None,
    ) -> _RequirementActionCandidateStatus:
        if manifest is None:
            return "unavailable"
        if not manifest.extraction_complete or not manifest.enumeration_complete:
            return "candidate_source_incomplete"
        return "bounded"

    @staticmethod
    def _requirement_action_review_surface_complete(
        manifest: RequirementActionCandidateManifest | None,
        context: P1TextAnalysisInput,
    ) -> bool:
        if (
            manifest is None
            or not manifest.extraction_complete
            or not manifest.enumeration_complete
            or not context.action_descriptor_extraction_complete
            or context.action_descriptor_algorithm_version is None
            or tuple(item.source_reference_id for item in manifest.actions)
            != tuple(
                item.source_reference_id for item in context.action_descriptors
            )
        ):
            return False
        return all(
            not descriptor.invocation_truncated
            and not descriptor.result_or_effect_truncated
            and requirement_action_descriptor_matches_candidate_metadata(
                candidate,
                descriptor,
            )
            for candidate, descriptor in zip(
                manifest.actions,
                context.action_descriptors,
                strict=True,
            )
        )

    def _preflight_requirement_action_candidates(
        self,
        *,
        provider: Provider,
        session_id: str,
        typed_evidence: EphemeralTypedEvidenceProjection | None,
    ) -> _RequirementActionCandidatePreflight:
        """Read the safe-event plane before minting the current request identity."""

        projector = self._typed_evidence_projector
        if projector is None or typed_evidence is None:
            return _RequirementActionCandidatePreflight(
                status="unavailable",
                manifest=None,
            )
        try:
            manifest = projector.requirement_action_candidate_manifest(
                provider=provider,
                session_id=session_id,
                source_run_id="0" * 64,
                source_window_fingerprint="0" * 64,
                projection=typed_evidence,
            )
        except RequirementActionCandidateManifestOverflowError:
            return _RequirementActionCandidatePreflight(
                status="candidate_manifest_overflow",
                manifest=None,
            )
        except Exception:
            return _RequirementActionCandidatePreflight(
                status="candidate_source_incomplete",
                manifest=None,
            )
        return _RequirementActionCandidatePreflight(
            status=self._requirement_action_candidate_status(manifest),
            manifest=manifest,
        )

    def _recheck_requirement_action_candidates(
        self,
        *,
        provider: Provider,
        session_id: str,
        source_run_id: str,
        context: P1TextAnalysisInput,
        typed_evidence: EphemeralTypedEvidenceProjection | None,
        preflight: _RequirementActionCandidatePreflight,
    ) -> _RequirementActionCandidatePreflight:
        """Fail closed if the safe-event source changes after request identity."""

        projector = self._typed_evidence_projector
        if projector is None or typed_evidence is None:
            current = _RequirementActionCandidatePreflight(
                status="unavailable",
                manifest=None,
            )
        else:
            try:
                manifest = projector.requirement_action_candidate_manifest(
                    provider=provider,
                    session_id=session_id,
                    source_run_id=source_run_id,
                    source_window_fingerprint=context.analysis_window_fingerprint,
                    projection=typed_evidence,
                )
            except RequirementActionCandidateManifestOverflowError:
                current = _RequirementActionCandidatePreflight(
                    status="candidate_manifest_overflow",
                    manifest=None,
                )
            except Exception:
                current = _RequirementActionCandidatePreflight(
                    status="candidate_source_incomplete",
                    manifest=None,
                )
            else:
                current = _RequirementActionCandidatePreflight(
                    status=self._requirement_action_candidate_status(manifest),
                    manifest=manifest,
                )
        if current.status != preflight.status:
            raise ModelEnsemblePersistenceError(
                "requirement-action candidate source changed during analysis"
            )
        if (current.manifest is None) != (preflight.manifest is None):
            raise ModelEnsemblePersistenceError(
                "requirement-action candidate source changed during analysis"
            )
        if current.manifest is not None and preflight.manifest is not None:
            excluded = {
                "source_run_id",
                "source_window_fingerprint",
                "manifest_fingerprint",
            }
            if current.manifest.model_dump(
                mode="json", exclude=excluded
            ) != preflight.manifest.model_dump(mode="json", exclude=excluded):
                raise ModelEnsemblePersistenceError(
                    "requirement-action candidate source changed during analysis"
                )
            expected_fingerprint = requirement_action_candidate_manifest_fingerprint(
                current.manifest
            )
            if current.manifest.manifest_fingerprint != expected_fingerprint:
                raise ModelEnsemblePersistenceError(
                    "requirement-action candidate manifest is invalid"
                )
        return current

    @staticmethod
    def _rebind_requirement_action_candidate_manifest(
        manifest: RequirementActionCandidateManifest,
        *,
        source_run_id: str,
        source_window_fingerprint: str,
    ) -> RequirementActionCandidateManifest:
        provisional = RequirementActionCandidateManifest.model_validate(
            {
                **manifest.model_dump(mode="json"),
                "source_run_id": source_run_id,
                "source_window_fingerprint": source_window_fingerprint,
                "manifest_fingerprint": "0" * 64,
            }
        )
        return provisional.model_copy(
            update={
                "manifest_fingerprint": (
                    requirement_action_candidate_manifest_fingerprint(provisional)
                )
            }
        )
    def _objective_evidence_descriptor(
        self,
        provider: Provider | None = None,
        projection: EphemeralTypedEvidenceProjection | None = None,
    ) -> DecoderDescriptor | None:
        if self._typed_evidence_projector is None:
            return None
        try:
            if projection is not None:
                descriptor_for_projection = getattr(
                    self._typed_evidence_projector,
                    "descriptor_for_projection",
                    None,
                )
                if callable(descriptor_for_projection):
                    descriptor = descriptor_for_projection(projection)
                    return (
                        descriptor
                        if isinstance(descriptor, DecoderDescriptor)
                        else None
                    )
            descriptor_for = getattr(self._typed_evidence_projector, "descriptor_for", None)
            descriptor = (
                descriptor_for(provider)
                if provider is not None and callable(descriptor_for)
                else self._typed_evidence_projector.descriptor
            )
            return descriptor if isinstance(descriptor, DecoderDescriptor) else None
        except Exception:
            return None

    def _bind_objective_opportunities(
        self,
        projection: EphemeralTypedEvidenceProjection | None,
        semantic_projection: SemanticUnitProjection | None,
    ) -> EphemeralTypedEvidenceProjection | None:
        try:
            return bind_semantic_unit_opportunities(
                projection,
                None
                if semantic_projection is None
                else semantic_projection.reconciliation,
                self._objective_evidence_descriptor(
                    None if projection is None else projection.provenance.provider,
                    projection,
                ),
            )
        except Exception:
            # A semantic-link binding is optional objective authority. Any
            # mismatch withholds it without discarding deterministic metrics.
            return None

    def _reconcile_semantic_units(
        self,
        context: P1TextAnalysisInput,
        prior_run: SessionModelEnsembleRunRecord | None,
    ) -> tuple[SemanticUnitProjection | None, SemanticUnitReconciliation | None]:
        if self._semantic_unit_reconciler is None:
            return None, None
        prior: SemanticUnitReconciliation | None = None
        if prior_run is not None:
            try:
                prior = self._repository.get_semantic_unit_reconciliation(
                    prior_run.run_id
                )
            except Exception:
                raise ModelEnsemblePersistenceError(
                    "semantic-unit history is unavailable"
                ) from None
        try:
            projection = self._semantic_unit_reconciler.reconcile(
                context,
                prior_receipts=() if prior is None else prior.heads,
                include_ephemeral_evidence=False,
            )
        except Exception:
            raise ModelEnsembleExecutionError(
                "semantic-unit reconciliation failed"
            ) from None
        return projection, prior

    def _run_pipeline(
        self,
        plan: EnsembleChunkPlan,
        specs: tuple[EnsembleMetricSpec, ...],
        *,
        progress_callback: Callable[[int, int], None] | None,
        prior_receipt: SessionModelEnsembleReceipt | None,
        typed_evidence: EphemeralTypedEvidenceProjection | None,
    ) -> SessionModelEnsembleReceipt:
        if typed_evidence is None:
            if progress_callback is None and prior_receipt is None:
                return self._runner.run(plan, specs)
            if progress_callback is None:
                return self._runner.run(
                    plan,
                    specs,
                    prior_receipt=prior_receipt,
                )
            if prior_receipt is None:
                return self._runner.run(
                    plan,
                    specs,
                    progress_callback=progress_callback,
                )
            return self._runner.run(
                plan,
                specs,
                progress_callback=progress_callback,
                prior_receipt=prior_receipt,
            )
        return self._runner.run(
            plan,
            specs,
            progress_callback=progress_callback,
            prior_receipt=prior_receipt,
            typed_evidence=typed_evidence,
        )

    @staticmethod
    def _with_metric_projection(
        run: SessionModelEnsembleRunRecord,
        metrics: tuple[SessionModelEnsembleTypedMetricReceipt, ...],
        metric_publication_v2: MetricPublicationV2,
        completed_at: datetime,
        metric_profile_binding: SessionMetricProfileBinding,
        requirement_plan_evidence_binding: SessionRequirementPlanEvidenceBinding,
        requirement_action_evidence_binding: SessionRequirementActionEvidenceBinding,
    ) -> SessionModelEnsembleRunRecord:
        receipt = SessionModelEnsembleReceipt.model_validate(
            {
                **run.receipt.model_dump(),
                "metric_projection_version": MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
                "metric_projection_completed_at": completed_at,
                "typed_metrics": metrics,
                "metric_publication_v2": metric_publication_v2,
            }
        )
        return SessionModelEnsembleRunRecord.model_validate(
            {
                **run.model_dump(),
                "metric_profile_binding": metric_profile_binding,
                "requirement_plan_evidence_binding": (
                    requirement_plan_evidence_binding
                ),
                "requirement_action_evidence_binding": (
                    requirement_action_evidence_binding
                ),
                "receipt": receipt,
            }
        )


__all__ = [
    "COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT",
    "COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION",
    "COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION",
    "coaching_profile_v1_unconfigured_fingerprint",
    "LEGACY_MODEL_ENSEMBLE_CONFIRMATION",
    "MODEL_ENSEMBLE_CONFIRMATION",
    "MetricProfileSource",
    "RequirementActionEvidenceSource",
    "RequirementVerificationEvidenceSource",
    "REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION",
    "REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT",
    "REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION",
    "REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT",
    "REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION",
    "REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT",
    "REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION",
    "REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT",
    "REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION",
    "REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT",
    "REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION",
    "REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION",
    "requirement_action_awaiting_review_fingerprint",
    "requirement_action_candidate_manifest_overflow_fingerprint",
    "requirement_action_candidate_source_incomplete_fingerprint",
    "requirement_action_binding_invalid_fingerprint",
    "requirement_action_unavailable_fingerprint",
    "RequirementPlanEvidenceSource",
    "REQUIREMENT_PLAN_AWAITING_REVIEW_FINGERPRINT",
    "REQUIREMENT_PLAN_AWAITING_REVIEW_SCHEMA_VERSION",
    "REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT",
    "REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION",
    "REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION",
    "requirement_plan_awaiting_review_fingerprint",
    "ModelEnsembleCompatibilityError",
    "ModelEnsembleConfirmationError",
    "ModelEnsembleConsentError",
    "ModelEnsembleExecutionError",
    "ModelEnsembleInputError",
    "ModelEnsemblePersistenceError",
    "ModelEnsembleSelectionError",
    "ModelEnsembleSourceError",
    "SessionModelEnsembleError",
    "SessionModelEnsembleOutcome",
    "SessionModelEnsemblePersistenceAuthority",
    "SessionMetricProfileBinding",
    "SessionRequirementActionEvidenceBinding",
    "SessionRequirementPlanEvidenceBinding",
    "SessionRequirementVerificationEvidenceBinding",
    "VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID",
    "VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION",
    "VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION",
    "SessionModelEnsembleRepository",
    "SessionModelEnsembleRunRecord",
    "SessionModelEnsembleRunner",
    "SessionModelEnsembleService",
    "SessionTypedEvidenceProjector",
    "validate_r8_typed_metric_projection",
]
