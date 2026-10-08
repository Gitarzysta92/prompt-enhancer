"""Ephemeral chunking and content-free receipts for a local model committee.

The committee is deliberately a shadow estimator.  It may help discover where
the deterministic coaching pack abstains, but it is not calibrated and cannot
replace the product metric pack.  Redacted text exists only in the ephemeral
chunk contracts; every receipt is content-free and safe for local persistence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel
from ..persistence import MetricValueState
from .coaching_baselines import COACHING_METRIC_DEFINITIONS
from .probabilistic_metrics import (
    PROBABILISTIC_METRIC_PROJECTION_VERSION,
    SessionPredictiveMetricProjection,
)
from .metric_publication_v2 import MetricPublicationSource, MetricPublicationV2
from .text_contracts import (
    MAX_ELIGIBLE_MESSAGES,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
)


MODEL_ENSEMBLE_PLAN_VERSION = "local-shadow-ensemble-v1"
MODEL_ENSEMBLE_CHUNKER_VERSION = "append-stable-redacted-v3"
MODEL_ENSEMBLE_RUBRIC_VERSION = "coaching-shadow-rubric-v3"
MODEL_ENSEMBLE_PROMPT_VERSION = "coaching-shadow-prompt-v4"
MODEL_ENSEMBLE_OBSERVATION_POLICY_VERSION = "owned-observation-v1"
MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION = "coaching-typed-projection-v1"
MODEL_ENSEMBLE_MAX_CHUNKS = 8
MODEL_ENSEMBLE_MAX_FRAGMENT_CHARACTERS = 3_500
# With fragments capped at 3,500 characters, every closed bucket exceeds
# 12,500 characters.  A 100,000-character source therefore fits in at most
# eight buckets while appends leave all closed boundaries unchanged.
MODEL_ENSEMBLE_TARGET_CHUNK_CHARACTERS = 16_000
MODEL_ENSEMBLE_MODEL_COUNT = 10
_REPOSITORY_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z"
)
_LOWER_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 digest")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _canonical_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class ModelExpertRole(StrEnum):
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
    SCOPE_NLI = "scope_nli"
    STRUCTURED_RUBRIC = "structured_rubric"


class ModelExpertStatus(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    FAILED = "failed"


class ModelVoteState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    ABSTAIN = "abstain"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class SourceCoverageState(StrEnum):
    COMPLETE_WINDOW = "complete_window"
    INCOMPLETE_SOURCE = "incomplete_source"


class EphemeralEnsembleFragment(StrictModel):
    """One bounded redacted fragment.  Its body must never be persisted."""

    fragment_id: str
    source_message_id: str
    source_sequence: int = Field(ge=0)
    segment_ordinal: int = Field(ge=0, le=64)
    role: TextRole
    kind: TextMessageKind
    language: TextLanguage
    is_focus_message: bool
    text: SecretStr = Field(repr=False, min_length=1, max_length=MODEL_ENSEMBLE_MAX_FRAGMENT_CHARACTERS)

    _ids = field_validator("fragment_id", "source_message_id")(_digest)

    @field_validator("text")
    @classmethod
    def safe_redacted_text(cls, value: SecretStr) -> SecretStr:
        if "\x00" in value.get_secret_value():
            raise ValueError("redacted ensemble fragments cannot contain NUL")
        return value


class EphemeralEnsembleChunk(StrictModel):
    ordinal: int = Field(ge=0, lt=MODEL_ENSEMBLE_MAX_CHUNKS)
    chunk_fingerprint: str
    source_message_count: int = Field(ge=1, le=100)
    character_count: int = Field(ge=1, le=100_000)
    fragments: tuple[EphemeralEnsembleFragment, ...] = Field(
        repr=False, min_length=1, max_length=128
    )

    _fingerprint = field_validator("chunk_fingerprint")(_digest)

    @model_validator(mode="after")
    def validate_counts(self) -> "EphemeralEnsembleChunk":
        if self.character_count != sum(
            len(item.text.get_secret_value()) for item in self.fragments
        ):
            raise ValueError("chunk character count does not match its fragments")
        if self.source_message_count != len(
            {item.source_message_id for item in self.fragments}
        ):
            raise ValueError("chunk message count does not match its fragments")
        sequences = tuple(item.source_sequence for item in self.fragments)
        if sequences != tuple(sorted(sequences)):
            raise ValueError("chunk fragments must preserve source chronology")
        return self


class EnsembleChunkPlan(StrictModel):
    chunker_version: Literal[MODEL_ENSEMBLE_CHUNKER_VERSION] = (
        MODEL_ENSEMBLE_CHUNKER_VERSION
    )
    source_window_fingerprint: str
    source_coverage_state: SourceCoverageState
    total_message_count: int = Field(ge=1, le=100)
    total_character_count: int = Field(ge=1, le=100_000)
    chunks: tuple[EphemeralEnsembleChunk, ...] = Field(
        repr=False, min_length=1, max_length=MODEL_ENSEMBLE_MAX_CHUNKS
    )

    _fingerprint = field_validator("source_window_fingerprint")(_digest)

    @model_validator(mode="after")
    def validate_partition(self) -> "EnsembleChunkPlan":
        if tuple(item.ordinal for item in self.chunks) != tuple(range(len(self.chunks))):
            raise ValueError("ensemble chunks must use contiguous ordinals")
        if self.total_character_count != sum(
            item.character_count for item in self.chunks
        ):
            raise ValueError("chunk plan character count is not exhaustive")
        source_ids = {
            item.source_message_id for chunk in self.chunks for item in chunk.fragments
        }
        if self.total_message_count != len(source_ids):
            raise ValueError("chunk plan message count is not exhaustive")
        fragment_ids = [
            item.fragment_id for chunk in self.chunks for item in chunk.fragments
        ]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("ensemble chunks cannot overlap fragments")
        return self


class EnsembleMetricSpec(StrictModel):
    metric_key: str
    metric_version: int = Field(ge=1)
    display_name: str
    direction: str
    evidence_scope: Literal[
        "focus_request",
        "conversation",
        "objective_evidence",
    ]
    retrieval_query: str = Field(min_length=1, max_length=2_000)
    entailment_hypothesis: str = Field(min_length=1, max_length=2_000)
    rubric: str = Field(min_length=1, max_length=3_000)

    _key = field_validator("metric_key", "direction")(_safe_version)


class ModelExpertIdentity(StrictModel):
    ordinal: int = Field(ge=0, lt=MODEL_ENSEMBLE_MODEL_COUNT)
    model_key: str
    role: ModelExpertRole
    repository_id: str
    revision: str
    tokenizer_id: str
    license_spdx: str
    backend_key: str
    contributes_to_decision: bool

    _versions = field_validator("model_key", "tokenizer_id", "backend_key")(
        _safe_version
    )

    @field_validator("repository_id")
    @classmethod
    def explicit_repository(cls, value: str) -> str:
        if _REPOSITORY_ID.fullmatch(value) is None:
            raise ValueError("model repository must be an explicit Hub repository")
        return value

    @field_validator("revision")
    @classmethod
    def immutable_revision(cls, value: str) -> str:
        if _LOWER_HEX_40.fullmatch(value) is None:
            raise ValueError("model revision must be an immutable commit")
        return value

    @field_validator("license_spdx")
    @classmethod
    def reviewed_license(cls, value: str) -> str:
        if value not in {"MIT", "Apache-2.0"}:
            raise ValueError("model license is outside the reviewed permissive set")
        return value


class ModelExpertReceipt(StrictModel):
    identity: ModelExpertIdentity
    status: ModelExpertStatus
    error_code: str | None = None
    device: Literal["cpu", "cuda", "mps"] | None = None
    inference_latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    peak_accelerator_memory_mb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    process_rss_mb: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unloaded_after_stage: Literal[True] = True
    calibration_state: Literal["not_assessed"] = "not_assessed"

    _error = field_validator("error_code")(
        lambda value: None if value is None else _safe_version(value)
    )

    @model_validator(mode="after")
    def validate_status(self) -> "ModelExpertReceipt":
        if self.status is ModelExpertStatus.COMPLETED:
            if self.error_code is not None or self.device is None:
                raise ValueError("completed model stages require a device and no error")
        elif self.error_code is None:
            raise ValueError("incomplete model stages require a fixed error code")
        return self


class ModelMetricVote(StrictModel):
    chunk_ordinal: int = Field(ge=0, lt=MODEL_ENSEMBLE_MAX_CHUNKS)
    metric_key: str
    model_key: str
    role: ModelExpertRole
    state: ModelVoteState
    raw_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    evidence_fragment_ids: tuple[str, ...] = Field(default=(), max_length=8)
    reason_code: str
    calibration_state: Literal["not_assessed"] = "not_assessed"

    _versions = field_validator("metric_key", "model_key", "reason_code")(_safe_version)

    @field_validator("evidence_fragment_ids")
    @classmethod
    def canonical_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("model votes cannot repeat evidence references")
        return tuple(_digest(value) for value in values)

    @model_validator(mode="after")
    def validate_vote(self) -> "ModelMetricVote":
        if self.state in {ModelVoteState.PRESENT, ModelVoteState.ABSENT}:
            if self.raw_score is None:
                raise ValueError("decided model votes require a bounded raw score")
        elif self.raw_score is not None:
            raise ValueError("non-decisions cannot claim a raw score")
        return self


class ModelEvidenceSelectionReceipt(StrictModel):
    chunk_ordinal: int = Field(ge=0, lt=MODEL_ENSEMBLE_MAX_CHUNKS)
    metric_key: str
    model_key: str
    role: Literal[ModelExpertRole.RETRIEVAL, ModelExpertRole.RERANKING]
    candidate_count: int = Field(ge=1, le=128)
    selected_fragment_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    ranking_fingerprint: str
    top_raw_score: float = Field(allow_inf_nan=False)
    calibration_state: Literal["not_assessed"] = "not_assessed"

    _versions = field_validator("metric_key", "model_key")(_safe_version)
    _fingerprint = field_validator("ranking_fingerprint")(_digest)

    @field_validator("selected_fragment_ids")
    @classmethod
    def canonical_selection(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("evidence selection cannot repeat fragment identifiers")
        return tuple(_digest(value) for value in values)


class ChunkMetricCommitteeReceipt(StrictModel):
    chunk_ordinal: int = Field(ge=0, lt=MODEL_ENSEMBLE_MAX_CHUNKS)
    metric_key: str
    value_state: MetricValueState
    numerator: int | None = Field(default=None, ge=0, le=1)
    denominator: int | None = Field(default=None, ge=1, le=1)
    rubric_vote: ModelVoteState
    contributing_nli_votes: int = Field(ge=0, le=2)
    diagnostic_nli_votes: int = Field(ge=0, le=1)
    reason_code: str

    _versions = field_validator("metric_key", "reason_code")(_safe_version)

    @model_validator(mode="after")
    def validate_value(self) -> "ChunkMetricCommitteeReceipt":
        known = self.value_state is MetricValueState.KNOWN
        if known != (self.numerator is not None and self.denominator == 1):
            raise ValueError("known chunk metrics require a binary fraction")
        return self


class ModelEnsembleChunkReceipt(StrictModel):
    """Content-free description of one exhaustive chunk."""

    ordinal: int = Field(ge=0, lt=MODEL_ENSEMBLE_MAX_CHUNKS)
    chunk_fingerprint: str
    source_message_count: int = Field(ge=1, le=100)
    fragment_count: int = Field(ge=1, le=128)
    character_count: int = Field(ge=1, le=100_000)

    _fingerprint = field_validator("chunk_fingerprint")(_digest)


class SessionModelEnsembleMetricReceipt(StrictModel):
    metric_key: str
    value_state: MetricValueState
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=1)
    numeric_value: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    known_chunk_count: int = Field(
        ge=0,
        le=MODEL_ENSEMBLE_MAX_CHUNKS,
        description="Known eligible observations; legacy field name retained for compatibility.",
    )
    abstained_chunk_count: int = Field(
        ge=0,
        le=MODEL_ENSEMBLE_MAX_CHUNKS,
        description="Abstained eligible observations; structural ownership cells are excluded.",
    )
    unsupported_chunk_count: int = Field(
        ge=0,
        le=MODEL_ENSEMBLE_MAX_CHUNKS,
        description="Unknown or unsupported eligible observations; structural cells are excluded.",
    )
    failed_chunk_count: int = Field(
        ge=0,
        le=MODEL_ENSEMBLE_MAX_CHUNKS,
        description="Execution-failed eligible observations; structural cells are excluded.",
    )
    total_chunk_count: int = Field(
        ge=1,
        le=MODEL_ENSEMBLE_MAX_CHUNKS,
        description="Eligible observation count; may be smaller than the physical chunk count.",
    )
    explanation_code: str
    calibration_state: Literal["not_assessed"] = "not_assessed"
    product_metric_eligible: Literal[False] = False

    _versions = field_validator("metric_key", "explanation_code")(_safe_version)

    @model_validator(mode="after")
    def validate_aggregate(self) -> "SessionModelEnsembleMetricReceipt":
        if (
            self.known_chunk_count
            + self.abstained_chunk_count
            + self.unsupported_chunk_count
            + self.failed_chunk_count
            != self.total_chunk_count
        ):
            raise ValueError("observation states must partition eligible observations")
        known = self.value_state is MetricValueState.KNOWN
        if known:
            if (
                self.numerator is None
                or self.denominator != self.known_chunk_count
                or self.numeric_value is None
                or not math.isclose(
                    self.numeric_value,
                    self.numerator / self.denominator,
                    rel_tol=0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("known ensemble metrics require ratio-of-observations")
        elif any(value is not None for value in (self.numerator, self.denominator, self.numeric_value)):
            raise ValueError("non-known ensemble metrics cannot claim a value")
        return self


class SessionModelEnsembleTypedMetricReceipt(StrictModel):
    """One content-free typed coaching observation projected beside the committee.

    The measured receipt is produced by the deterministic coaching contract;
    its numerator and denominator are tied to explicit observation units rather
    than model agreement.  A separate predictive projection may accompany it,
    but it cannot rewrite this evidence-backed value.
    """

    metric_key: str
    metric_version: int = Field(ge=1, le=1_000_000)
    value_state: MetricValueState
    numerator: int | None = Field(default=None, ge=0, le=1_000_000)
    denominator: int | None = Field(default=None, ge=1, le=1_000_000)
    numeric_value: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    observed_message_count: int = Field(ge=0, le=100)
    eligible_message_count: int = Field(ge=0, le=MAX_ELIGIBLE_MESSAGES)
    coverage: float = Field(ge=0, le=1, allow_inf_nan=False)
    explanation_code: str
    error_code: str | None
    projection_source: Literal["deterministic_typed_contract"]
    metric_schema_version: int = Field(ge=1, le=1_000_000)
    engine_version: str
    algorithm_id: str
    algorithm_version: str
    rubric_version: str
    calibration_state: Literal["not_assessed"]
    product_metric_eligible: Literal[False]

    _versions = field_validator(
        "metric_key",
        "explanation_code",
        "engine_version",
        "algorithm_id",
        "algorithm_version",
        "rubric_version",
    )(_safe_version)
    _error = field_validator("error_code")(
        lambda value: None if value is None else _safe_version(value)
    )

    @model_validator(mode="after")
    def validate_projection(self) -> "SessionModelEnsembleTypedMetricReceipt":
        if self.observed_message_count > self.eligible_message_count:
            raise ValueError("typed metric observation count exceeds eligibility")
        expected_coverage = (
            0.0
            if self.eligible_message_count == 0
            else self.observed_message_count / self.eligible_message_count
        )
        if not math.isclose(
            self.coverage,
            expected_coverage,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("typed metric coverage must match its message counts")
        known = self.value_state is MetricValueState.KNOWN
        if known:
            if (
                self.numerator is None
                or self.denominator is None
                or self.numerator > self.denominator
                or self.numeric_value is None
                or self.error_code is not None
                or not math.isclose(
                    self.numeric_value,
                    self.numerator / self.denominator,
                    rel_tol=0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("known typed metrics require an exact bounded fraction")
        elif any(
            value is not None
            for value in (self.numerator, self.denominator, self.numeric_value)
        ):
            raise ValueError("non-known typed metrics cannot claim a value")
        if (self.value_state is MetricValueState.EXECUTION_ERROR) != (
            self.error_code is not None
        ):
            raise ValueError("only typed execution errors may contain an error code")
        return self


class SessionModelEnsembleReceipt(StrictModel):
    plan_version: Literal[MODEL_ENSEMBLE_PLAN_VERSION] = MODEL_ENSEMBLE_PLAN_VERSION
    plan_fingerprint: str
    source_window_fingerprint: str
    source_coverage_state: SourceCoverageState
    chunk_count: int = Field(ge=1, le=MODEL_ENSEMBLE_MAX_CHUNKS)
    model_count: Literal[MODEL_ENSEMBLE_MODEL_COUNT] = MODEL_ENSEMBLE_MODEL_COUNT
    chunk_plan: tuple[ModelEnsembleChunkReceipt, ...] = Field(
        min_length=1,
        max_length=MODEL_ENSEMBLE_MAX_CHUNKS,
    )
    chunks: tuple[ChunkMetricCommitteeReceipt, ...]
    metrics: tuple[SessionModelEnsembleMetricReceipt, ...]
    metric_projection_version: Literal[
        MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
    ] | None = None
    metric_projection_completed_at: datetime | None = None
    typed_metrics: tuple[SessionModelEnsembleTypedMetricReceipt, ...] = ()
    metric_publication_v2: MetricPublicationV2 | None = None
    predictive_projection: SessionPredictiveMetricProjection | None = None
    experts: tuple[ModelExpertReceipt, ...] = Field(
        min_length=MODEL_ENSEMBLE_MODEL_COUNT,
        max_length=MODEL_ENSEMBLE_MODEL_COUNT,
    )
    evidence_selections: tuple[ModelEvidenceSelectionReceipt, ...] = ()
    model_votes: tuple[ModelMetricVote, ...] = ()
    created_at: datetime
    completed_at: datetime
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False
    calibration_state: Literal["not_assessed"] = "not_assessed"
    product_metric_eligible: Literal[False] = False

    _fingerprints = field_validator("plan_fingerprint", "source_window_fingerprint")(_digest)
    _times = field_validator("created_at", "completed_at")(_utc)

    @field_validator("metric_projection_completed_at")
    @classmethod
    def validate_projection_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_graph(self) -> "SessionModelEnsembleReceipt":
        if self.completed_at < self.created_at:
            raise ValueError("ensemble completion cannot precede creation")
        if tuple(item.identity.ordinal for item in self.experts) != tuple(
            range(MODEL_ENSEMBLE_MODEL_COUNT)
        ):
            raise ValueError("ensemble experts must use all ten canonical ordinals")
        if tuple(item.ordinal for item in self.chunk_plan) != tuple(
            range(self.chunk_count)
        ):
            raise ValueError("ensemble chunk plan must use every canonical ordinal")
        if len({item.identity.model_key for item in self.experts}) != MODEL_ENSEMBLE_MODEL_COUNT:
            raise ValueError("ensemble experts must be unique")
        expected_pairs = {
            (chunk_ordinal, metric.metric_key)
            for chunk_ordinal in range(self.chunk_count)
            for metric in self.metrics
        }
        actual_pairs = {(item.chunk_ordinal, item.metric_key) for item in self.chunks}
        if expected_pairs != actual_pairs or len(actual_pairs) != len(self.chunks):
            raise ValueError("ensemble chunk metrics must form a complete matrix")
        projection_complete = (
            self.metric_projection_version is not None
            and self.metric_projection_completed_at is not None
        )
        if bool(self.typed_metrics) != projection_complete or (
            (self.metric_projection_version is None)
            != (self.metric_projection_completed_at is None)
        ):
            raise ValueError("typed metric projection identity must be complete")
        if (
            self.metric_publication_v2 is not None
            and self.metric_publication_v2.projection_version
            == "metric-contract-v2-projection-8"
            and len(self.typed_metrics) != 20
        ):
            raise ValueError("r8 publication requires all twenty typed metric receipts")
        if self.typed_metrics:
            typed_keys = tuple(item.metric_key for item in self.typed_metrics)
            metric_keys = tuple(item.metric_key for item in self.metrics)
            if (
                len(set(typed_keys)) != len(typed_keys)
                or set(typed_keys) != set(metric_keys)
            ):
                raise ValueError(
                    "typed metric projection must cover the complete committee metric set"
                )
        if self.metric_publication_v2 is not None:
            publication = self.metric_publication_v2
            if (
                publication.source is not MetricPublicationSource.LIVE_PROJECTION
                or publication.compatibility_preview
                or not publication.canonical_live_snapshot
                or publication.model_stage_consumed
            ):
                raise ValueError(
                    "canonical V2 metric publication must come from the live measured producer"
                )
            publication_keys = tuple(
                item.state.metric_key for item in publication.metrics
            )
            metric_keys = tuple(item.metric_key for item in self.metrics)
            if len(set(publication_keys)) != len(publication_keys) or set(
                publication_keys
            ) != set(metric_keys):
                raise ValueError(
                    "canonical V2 metric publication must cover the complete metric set"
                )
        if self.predictive_projection is not None:
            if (
                self.predictive_projection.projection_version
                != PROBABILISTIC_METRIC_PROJECTION_VERSION
            ):
                raise ValueError("predictive metric projection version is unsupported")
            predictive_keys = tuple(
                item.metric_key for item in self.predictive_projection.metrics
            )
            metric_keys = tuple(item.metric_key for item in self.metrics)
            if len(set(predictive_keys)) != len(predictive_keys) or set(
                predictive_keys
            ) != set(metric_keys):
                raise ValueError(
                    "predictive metric projection must cover the complete metric set"
                )
        expert_keys = {item.identity.model_key for item in self.experts}
        expert_roles = {
            item.identity.model_key: item.identity.role for item in self.experts
        }
        if any(
            item.model_key not in expert_keys
            for item in (*self.evidence_selections, *self.model_votes)
        ):
            raise ValueError("ensemble outputs reference an unknown expert")
        if any(
            expert_roles[item.model_key] is not item.role
            for item in (*self.evidence_selections, *self.model_votes)
        ):
            raise ValueError("ensemble outputs must preserve each expert's role")
        if any(
            (item.chunk_ordinal, item.metric_key) not in expected_pairs
            for item in (*self.evidence_selections, *self.model_votes)
        ):
            raise ValueError("ensemble outputs reference an unknown chunk metric")
        votes_by_pair: dict[tuple[int, str], list[ModelMetricVote]] = defaultdict(list)
        for vote in self.model_votes:
            votes_by_pair[(vote.chunk_ordinal, vote.metric_key)].append(vote)
        for pair in expected_pairs:
            votes = votes_by_pair[pair]
            vote_keys = {(vote.model_key, vote.role) for vote in votes}
            if len(votes) != 4 or len(vote_keys) != 4:
                raise ValueError("each chunk metric requires four unique decision votes")
            if sum(vote.role is ModelExpertRole.SCOPE_NLI for vote in votes) != 3:
                raise ValueError("each chunk metric requires three NLI votes")
            if sum(vote.role is ModelExpertRole.STRUCTURED_RUBRIC for vote in votes) != 1:
                raise ValueError("each chunk metric requires one rubric vote")
        return self


def content_free_chunk_plan(
    plan: EnsembleChunkPlan,
) -> tuple[ModelEnsembleChunkReceipt, ...]:
    """Drop all fragment identities and text before persistence/API output."""

    return tuple(
        ModelEnsembleChunkReceipt(
            ordinal=chunk.ordinal,
            chunk_fingerprint=chunk.chunk_fingerprint,
            source_message_count=chunk.source_message_count,
            fragment_count=len(chunk.fragments),
            character_count=chunk.character_count,
        )
        for chunk in plan.chunks
    )


def coaching_ensemble_metric_specs() -> tuple[EnsembleMetricSpec, ...]:
    """Return the exact rubric prompts used by every local expert stage."""

    specs = []
    for definition in COACHING_METRIC_DEFINITIONS:
        condition = definition.description.rstrip(".")
        specs.append(
            EnsembleMetricSpec(
                metric_key=definition.key,
                metric_version=definition.version,
                display_name=definition.display_name,
                direction=definition.direction.value,
                evidence_scope=(
                    "objective_evidence"
                    if definition.dimension == "outcome"
                    or definition.key == "logic.hypothesis_test_linkage"
                    else (
                        "focus_request"
                        if definition.dimension == "prompt"
                        else "conversation"
                    )
                ),
                retrieval_query=(
                    f"Find direct evidence relevant to {definition.display_name}: {condition}."
                ),
                entailment_hypothesis=(
                    f"The selected evidence directly demonstrates {definition.display_name} "
                    "under the stated bounded rubric."
                ),
                rubric=(
                    f"Assess only {definition.display_name}. {condition}. "
                    "Return present only with direct evidence, absent only when the relevant "
                    "opportunity is observable but unmet, and abstain when scope or evidence "
                    "is insufficient."
                ),
            )
        )
    return tuple(specs)


def build_ensemble_chunks(context: P1TextAnalysisInput) -> EnsembleChunkPlan:
    """Partition the window into append-stable, non-overlapping chunks.

    Earlier complete buckets keep the same boundary when a new message is
    appended.  The final bucket is deliberately provisional and may be
    replaced by the next snapshot.  Fingerprints include a local-only digest
    of the already-redacted fragment so edits cannot reuse stale decisions.
    """

    fragments: list[EphemeralEnsembleFragment] = []
    for message in context.messages:
        value = message.text.get_secret_value()
        pieces = tuple(
            value[start : start + MODEL_ENSEMBLE_MAX_FRAGMENT_CHARACTERS]
            for start in range(0, len(value), MODEL_ENSEMBLE_MAX_FRAGMENT_CHARACTERS)
        ) or (value,)
        for segment_ordinal, piece in enumerate(pieces):
            fragment_id = _canonical_digest(
                {
                    "message_id": message.message_id,
                    "segment_ordinal": segment_ordinal,
                    "chunker_version": MODEL_ENSEMBLE_CHUNKER_VERSION,
                    "role": message.role.value,
                    "kind": message.kind.value,
                    "language": message.language.value,
                    "is_focus_message": message.message_id
                    == context.focus_message_id,
                    "redacted_content_digest": hashlib.sha256(
                        piece.encode("utf-8")
                    ).hexdigest(),
                }
            )
            fragments.append(
                EphemeralEnsembleFragment(
                    fragment_id=fragment_id,
                    source_message_id=message.message_id,
                    source_sequence=message.sequence,
                    segment_ordinal=segment_ordinal,
                    role=message.role,
                    kind=message.kind,
                    language=message.language,
                    is_focus_message=message.message_id == context.focus_message_id,
                    text=SecretStr(piece),
                )
            )

    total_characters = sum(len(item.text.get_secret_value()) for item in fragments)
    target_characters = MODEL_ENSEMBLE_TARGET_CHUNK_CHARACTERS
    buckets: list[list[EphemeralEnsembleFragment]] = [[]]
    bucket_characters = 0
    for fragment in fragments:
        length = len(fragment.text.get_secret_value())
        if (
            buckets[-1]
            and bucket_characters + length > target_characters
        ):
            if len(buckets) >= MODEL_ENSEMBLE_MAX_CHUNKS:
                raise ValueError("bounded window cannot be partitioned into safe chunks")
            buckets.append([])
            bucket_characters = 0
        buckets[-1].append(fragment)
        bucket_characters += length

    chunks: list[EphemeralEnsembleChunk] = []
    for ordinal, bucket in enumerate(buckets):
        chunk_fingerprint = _canonical_digest(
            {
                "chunker_version": MODEL_ENSEMBLE_CHUNKER_VERSION,
                "fragment_ids": [item.fragment_id for item in bucket],
            }
        )
        chunks.append(
            EphemeralEnsembleChunk(
                ordinal=ordinal,
                chunk_fingerprint=chunk_fingerprint,
                source_message_count=len({item.source_message_id for item in bucket}),
                character_count=sum(
                    len(item.text.get_secret_value()) for item in bucket
                ),
                fragments=tuple(bucket),
            )
        )
    return EnsembleChunkPlan(
        source_window_fingerprint=context.analysis_window_fingerprint,
        source_coverage_state=(
            SourceCoverageState.COMPLETE_WINDOW
            if context.text_extraction_complete
            else SourceCoverageState.INCOMPLETE_SOURCE
        ),
        total_message_count=context.observed_message_count,
        total_character_count=total_characters,
        chunks=tuple(chunks),
    )


def committee_chunk_receipt(
    *,
    chunk_ordinal: int,
    metric_key: str,
    rubric_vote: ModelMetricVote,
    nli_votes: tuple[ModelMetricVote, ...],
    contributing_nli_model_keys: frozenset[str],
) -> ChunkMetricCommitteeReceipt:
    """Resolve a conservative chunk decision from rubric plus scoped NLI checks."""

    if rubric_vote.role is not ModelExpertRole.STRUCTURED_RUBRIC:
        raise ValueError("committee resolution requires the rubric expert")
    if len(nli_votes) != 3 or any(
        item.role is not ModelExpertRole.SCOPE_NLI for item in nli_votes
    ):
        raise ValueError("committee resolution requires all three NLI diagnostics")
    contributing = tuple(
        item for item in nli_votes if item.model_key in contributing_nli_model_keys
    )
    if len(contributing) != 2:
        raise ValueError("committee resolution requires two promoted NLI votes")
    diagnostic_count = len(nli_votes) - len(contributing)

    if rubric_vote.state in {
        ModelVoteState.ABSTAIN,
        ModelVoteState.UNSUPPORTED,
        ModelVoteState.FAILED,
    }:
        state = {
            ModelVoteState.ABSTAIN: MetricValueState.ABSTAINED,
            ModelVoteState.UNSUPPORTED: MetricValueState.UNKNOWN,
            ModelVoteState.FAILED: MetricValueState.EXECUTION_ERROR,
        }[rubric_vote.state]
        return ChunkMetricCommitteeReceipt(
            chunk_ordinal=chunk_ordinal,
            metric_key=metric_key,
            value_state=state,
            rubric_vote=rubric_vote.state,
            contributing_nli_votes=len(contributing),
            diagnostic_nli_votes=diagnostic_count,
            reason_code=f"rubric_{rubric_vote.state.value}",
        )

    contributing_states = {item.state for item in contributing}
    if ModelVoteState.FAILED in contributing_states:
        return ChunkMetricCommitteeReceipt(
            chunk_ordinal=chunk_ordinal,
            metric_key=metric_key,
            value_state=MetricValueState.EXECUTION_ERROR,
            rubric_vote=rubric_vote.state,
            contributing_nli_votes=len(contributing),
            diagnostic_nli_votes=diagnostic_count,
            reason_code="model_committee_nli_failed",
        )
    if ModelVoteState.UNSUPPORTED in contributing_states:
        return ChunkMetricCommitteeReceipt(
            chunk_ordinal=chunk_ordinal,
            metric_key=metric_key,
            value_state=MetricValueState.UNKNOWN,
            rubric_vote=rubric_vote.state,
            contributing_nli_votes=len(contributing),
            diagnostic_nli_votes=diagnostic_count,
            reason_code="model_committee_nli_unsupported",
        )
    if ModelVoteState.ABSTAIN in contributing_states:
        return ChunkMetricCommitteeReceipt(
            chunk_ordinal=chunk_ordinal,
            metric_key=metric_key,
            value_state=MetricValueState.ABSTAINED,
            rubric_vote=rubric_vote.state,
            contributing_nli_votes=len(contributing),
            diagnostic_nli_votes=diagnostic_count,
            reason_code="model_committee_nli_abstained",
        )

    entailments = sum(item.state is ModelVoteState.PRESENT for item in contributing)
    contradictions = sum(item.state is ModelVoteState.ABSENT for item in contributing)
    if rubric_vote.state is ModelVoteState.ABSENT:
        # The v3+ shadow pipeline does not yet persist a typed opportunity
        # receipt.  Agreement that a signal is absent therefore cannot prove
        # that the metric's denominator existed.  Keep the decision
        # nonnumeric until a metric-specific eligibility contract supplies
        # that evidence; semantic missingness must never become a zero.
        return ChunkMetricCommitteeReceipt(
            chunk_ordinal=chunk_ordinal,
            metric_key=metric_key,
            value_state=MetricValueState.ABSTAINED,
            rubric_vote=rubric_vote.state,
            contributing_nli_votes=len(contributing),
            diagnostic_nli_votes=diagnostic_count,
            reason_code="typed_metric_opportunity_unproven",
        )

    accepted = entailments == len(contributing) and contradictions == 0
    numerator = 1
    if not accepted:
        return ChunkMetricCommitteeReceipt(
            chunk_ordinal=chunk_ordinal,
            metric_key=metric_key,
            value_state=MetricValueState.ABSTAINED,
            rubric_vote=rubric_vote.state,
            contributing_nli_votes=len(contributing),
            diagnostic_nli_votes=diagnostic_count,
            reason_code="model_committee_disagreement",
        )
    return ChunkMetricCommitteeReceipt(
        chunk_ordinal=chunk_ordinal,
        metric_key=metric_key,
        value_state=MetricValueState.KNOWN,
        numerator=numerator,
        denominator=1,
        rubric_vote=rubric_vote.state,
        contributing_nli_votes=len(contributing),
        diagnostic_nli_votes=diagnostic_count,
        reason_code="model_committee_agreed",
    )


def aggregate_chunk_metrics(
    receipts: tuple[ChunkMetricCommitteeReceipt, ...],
) -> tuple[SessionModelEnsembleMetricReceipt, ...]:
    """Aggregate eligible owned observations; never average model logits.

    The sealed graph remains a complete chunk-by-metric matrix. Structural
    ``NOT_APPLICABLE`` cells only identify which chunk owns a focus-request or
    session-window observation, so they are excluded from the analytic
    denominator.
    """

    if not receipts:
        raise ValueError("ensemble aggregation requires chunk receipts")
    grouped: dict[str, list[ChunkMetricCommitteeReceipt]] = defaultdict(list)
    for receipt in receipts:
        grouped[receipt.metric_key].append(receipt)
    results = []
    for metric_key in sorted(grouped):
        rows = sorted(grouped[metric_key], key=lambda item: item.chunk_ordinal)
        if tuple(item.chunk_ordinal for item in rows) != tuple(range(len(rows))):
            raise ValueError("each ensemble metric requires every chunk ordinal")
        eligible = [
            item
            for item in rows
            if item.value_state is not MetricValueState.NOT_APPLICABLE
        ]
        if not eligible:
            raise ValueError("each ensemble metric requires an eligible observation owner")
        known = [
            item for item in eligible if item.value_state is MetricValueState.KNOWN
        ]
        abstained = sum(
            item.value_state is MetricValueState.ABSTAINED for item in eligible
        )
        unsupported = sum(
            item.value_state is MetricValueState.UNKNOWN for item in eligible
        )
        failed = sum(
            item.value_state is MetricValueState.EXECUTION_ERROR for item in eligible
        )
        numerator = sum(item.numerator or 0 for item in known)
        denominator = len(known)
        results.append(
            SessionModelEnsembleMetricReceipt(
                metric_key=metric_key,
                value_state=(
                    MetricValueState.KNOWN
                    if denominator
                    else (
                        MetricValueState.EXECUTION_ERROR
                        if failed == len(eligible)
                        else (
                            MetricValueState.UNKNOWN
                            if unsupported == len(eligible)
                            else MetricValueState.ABSTAINED
                        )
                    )
                ),
                numerator=numerator if denominator else None,
                denominator=denominator or None,
                numeric_value=numerator / denominator if denominator else None,
                known_chunk_count=denominator,
                abstained_chunk_count=abstained,
                unsupported_chunk_count=unsupported,
                failed_chunk_count=failed,
                total_chunk_count=len(eligible),
                explanation_code=(
                    "model_shadow_ratio_of_valid_observations"
                    if denominator
                    else (
                        "model_shadow_no_supported_observations"
                        if unsupported == len(eligible)
                        else "model_shadow_no_valid_observations"
                    )
                ),
            )
        )
    return tuple(results)


def ensemble_plan_fingerprint(
    experts: tuple[ModelExpertIdentity, ...],
    metrics: tuple[EnsembleMetricSpec, ...],
) -> str:
    if len(experts) != MODEL_ENSEMBLE_MODEL_COUNT:
        raise ValueError("the local ensemble requires exactly ten experts")
    return _canonical_digest(
        {
            "plan_version": MODEL_ENSEMBLE_PLAN_VERSION,
            "chunker_version": MODEL_ENSEMBLE_CHUNKER_VERSION,
            "rubric_version": MODEL_ENSEMBLE_RUBRIC_VERSION,
            "prompt_version": MODEL_ENSEMBLE_PROMPT_VERSION,
            "observation_policy_version": MODEL_ENSEMBLE_OBSERVATION_POLICY_VERSION,
            "experts": [item.model_dump(mode="json") for item in experts],
            "metrics": [item.model_dump(mode="json") for item in metrics],
        }
    )


__all__ = [
    "ChunkMetricCommitteeReceipt",
    "EnsembleChunkPlan",
    "EnsembleMetricSpec",
    "EphemeralEnsembleChunk",
    "EphemeralEnsembleFragment",
    "MODEL_ENSEMBLE_CHUNKER_VERSION",
    "MODEL_ENSEMBLE_MAX_CHUNKS",
    "MODEL_ENSEMBLE_TARGET_CHUNK_CHARACTERS",
    "MODEL_ENSEMBLE_MODEL_COUNT",
    "MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION",
    "MODEL_ENSEMBLE_OBSERVATION_POLICY_VERSION",
    "MODEL_ENSEMBLE_PLAN_VERSION",
    "MODEL_ENSEMBLE_PROMPT_VERSION",
    "MODEL_ENSEMBLE_RUBRIC_VERSION",
    "ModelExpertIdentity",
    "ModelExpertReceipt",
    "ModelExpertRole",
    "ModelExpertStatus",
    "ModelEvidenceSelectionReceipt",
    "ModelMetricVote",
    "ModelVoteState",
    "SessionModelEnsembleMetricReceipt",
    "SessionModelEnsembleReceipt",
    "SessionModelEnsembleTypedMetricReceipt",
    "SourceCoverageState",
    "aggregate_chunk_metrics",
    "build_ensemble_chunks",
    "coaching_ensemble_metric_specs",
    "committee_chunk_receipt",
    "ensemble_plan_fingerprint",
]
