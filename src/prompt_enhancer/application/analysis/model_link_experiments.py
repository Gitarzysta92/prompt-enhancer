"""Explicit local neural-link experiment over one redacted session window.

This is deliberately separate from the coaching metric pack.  Neural outputs are
candidate links for human review, not quality scores.  Redacted excerpts exist
only in the command response; persistence receives pseudonymous identities,
scores, pinned model provenance, and user annotations.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
import math
import re
from threading import Lock
from typing import Protocol

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import DataTier, PSEUDONYM_PATTERN, Provider, SAFE_VERSION_PATTERN, StrictModel
from .session_text_service import (
    SessionTextAnalysisAccessPolicy,
    SessionTextAnalysisCompatibilityPolicy,
    SessionTextAnalysisIdFactory,
    SessionTextAnalysisSourceFactory,
)
from .text_analysis_presets import COACHING_PROFILE_V1
from .text_contracts import P1TextAnalysisInput, TextMessageKind, TextRole
from .text_source import (
    TEXT_ANALYSIS_PROVIDERS,
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceAccessGrant,
    TextSourceFailureReason,
    TextSourceReadError,
)


MODEL_LINK_EXPERIMENT_KEY = "local.neural-link-comparison"
MODEL_LINK_EXPERIMENT_VERSION = 1
MODEL_LINK_CONFIRMATION = "compare_selected_redacted_text_with_local_models"
MODEL_LINK_POLICY_VERSION = "explicit-session-model-link-v1"
MODEL_LINK_MAX_QUERIES = 8
MODEL_LINK_MAX_CANDIDATES = 8
MODEL_LINK_MAX_TEXT_CHARACTERS = 4_000
MODEL_LINK_EXCERPT_CHARACTERS = 360

_SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class ModelExperimentDevice(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"


class ModelLinkCandidateKind(StrEnum):
    RESPONSE = "response"
    PLAN = "plan"


class ModelLinkRecommendation(StrEnum):
    QWEN = "qwen"
    BGE = "bge"
    BOTH = "both"


class ModelLinkAnnotationLabel(StrEnum):
    RELEVANT = "relevant"
    INCORRECT = "incorrect"
    UNSURE = "unsure"


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be a local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("provenance value is invalid")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


class ModelLinkModelIdentity(StrictModel):
    key: str
    repository_id: str
    revision: str
    license_spdx: str
    tokenizer_id: str
    backend_key: str

    _validate_values = field_validator(
        "key",
        "repository_id",
        "revision",
        "license_spdx",
        "tokenizer_id",
        "backend_key",
    )(_safe_code)


class ModelLinkCandidate(StrictModel):
    message_id: str
    sequence: int = Field(ge=0)
    kind: ModelLinkCandidateKind
    text: SecretStr = Field(repr=False, min_length=1, max_length=MODEL_LINK_MAX_TEXT_CHARACTERS)

    _validate_id = field_validator("message_id")(_pseudonym)


class ModelLinkCase(StrictModel):
    query_message_id: str
    query_sequence: int = Field(ge=0)
    query_text: SecretStr = Field(
        repr=False,
        min_length=1,
        max_length=MODEL_LINK_MAX_TEXT_CHARACTERS,
    )
    candidates: tuple[ModelLinkCandidate, ...] = Field(
        min_length=1,
        max_length=MODEL_LINK_MAX_CANDIDATES,
    )

    _validate_query_id = field_validator("query_message_id")(_pseudonym)

    @model_validator(mode="after")
    def validate_case(self) -> ModelLinkCase:
        ids = tuple(item.message_id for item in self.candidates)
        if len(set(ids)) != len(ids):
            raise ValueError("model-link candidates cannot contain duplicates")
        if any(item.sequence <= self.query_sequence for item in self.candidates):
            raise ValueError("model-link candidates must follow the user request")
        return self


class ModelLinkRunnerRequest(StrictModel):
    device: ModelExperimentDevice
    cases: tuple[ModelLinkCase, ...] = Field(
        min_length=1,
        max_length=MODEL_LINK_MAX_QUERIES,
    )

    @model_validator(mode="after")
    def validate_request(self) -> ModelLinkRunnerRequest:
        ids = tuple(item.query_message_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("model-link queries cannot contain duplicates")
        return self


class ModelLinkPairScore(StrictModel):
    query_message_id: str
    candidate_message_id: str
    qwen_score: float
    bge_score: float

    _validate_ids = field_validator("query_message_id", "candidate_message_id")(
        _pseudonym
    )

    @model_validator(mode="after")
    def validate_scores(self) -> ModelLinkPairScore:
        if not math.isfinite(self.qwen_score) or not -1.000001 <= self.qwen_score <= 1.000001:
            raise ValueError("Qwen similarity must be finite and bounded")
        if not math.isfinite(self.bge_score) or not -100_000 <= self.bge_score <= 100_000:
            raise ValueError("BGE score must be finite and bounded")
        return self


class ModelLinkRunnerResult(StrictModel):
    resolved_device: ModelExperimentDevice
    qwen_model: ModelLinkModelIdentity
    bge_model: ModelLinkModelIdentity
    scores: tuple[ModelLinkPairScore, ...] = Field(min_length=1, max_length=64)


class ModelLinkRunRecord(StrictModel):
    run_id: str
    session_id: str
    request_fingerprint: str
    input_fingerprint: str
    experiment_key: str = MODEL_LINK_EXPERIMENT_KEY
    experiment_version: int = MODEL_LINK_EXPERIMENT_VERSION
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    consent_policy_version: str = MODEL_LINK_POLICY_VERSION
    resolved_device: ModelExperimentDevice
    qwen_model: ModelLinkModelIdentity
    bge_model: ModelLinkModelIdentity
    query_count: int = Field(ge=1, le=MODEL_LINK_MAX_QUERIES)
    link_count: int = Field(ge=1, le=MODEL_LINK_MAX_QUERIES * 2)
    agreement_count: int = Field(ge=0, le=MODEL_LINK_MAX_QUERIES)
    started_at: datetime
    finished_at: datetime
    local_only: bool = True

    _validate_ids = field_validator(
        "run_id", "session_id", "request_fingerprint", "input_fingerprint"
    )(_pseudonym)
    _validate_codes = field_validator(
        "experiment_key",
        "provider_version",
        "adapter_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
        "consent_policy_version",
    )(_safe_code)
    _validate_times = field_validator("started_at", "finished_at")(_utc)

    @model_validator(mode="after")
    def validate_run(self) -> ModelLinkRunRecord:
        if self.finished_at < self.started_at:
            raise ValueError("experiment finish cannot precede its start")
        if self.agreement_count > self.query_count or self.link_count < self.query_count:
            raise ValueError("experiment counts are inconsistent")
        if not self.local_only:
            raise ValueError("model-link experiments are local-only")
        return self


class ModelLinkStoredLink(StrictModel):
    run_id: str
    link_id: str
    query_message_id: str
    candidate_message_id: str
    query_sequence: int = Field(ge=0)
    candidate_sequence: int = Field(ge=0)
    candidate_kind: ModelLinkCandidateKind
    qwen_score: float
    qwen_rank: int = Field(ge=1, le=MODEL_LINK_MAX_CANDIDATES)
    bge_score: float
    bge_rank: int = Field(ge=1, le=MODEL_LINK_MAX_CANDIDATES)
    recommended_by: ModelLinkRecommendation

    _validate_ids = field_validator(
        "run_id", "link_id", "query_message_id", "candidate_message_id"
    )(_pseudonym)

    @model_validator(mode="after")
    def validate_link(self) -> ModelLinkStoredLink:
        if self.candidate_sequence <= self.query_sequence:
            raise ValueError("stored candidate must follow its query")
        if not math.isfinite(self.qwen_score) or not -1.000001 <= self.qwen_score <= 1.000001:
            raise ValueError("stored Qwen score is invalid")
        if not math.isfinite(self.bge_score) or not -100_000 <= self.bge_score <= 100_000:
            raise ValueError("stored BGE score is invalid")
        return self


class ModelLinkAnnotationRecord(StrictModel):
    run_id: str
    link_id: str
    revision: int = Field(ge=1)
    label: ModelLinkAnnotationLabel
    annotated_at: datetime

    _validate_ids = field_validator("run_id", "link_id")(_pseudonym)
    _validate_time = field_validator("annotated_at")(_utc)


class ModelLinkStoredExperiment(StrictModel):
    run: ModelLinkRunRecord
    links: tuple[ModelLinkStoredLink, ...]
    annotations: tuple[ModelLinkAnnotationRecord, ...] = ()

    @model_validator(mode="after")
    def validate_experiment(self) -> ModelLinkStoredExperiment:
        if len(self.links) != self.run.link_count:
            raise ValueError("stored experiment link count is inconsistent")
        link_ids = {item.link_id for item in self.links}
        if len(link_ids) != len(self.links):
            raise ValueError("stored experiment links cannot duplicate identities")
        if any(item.run_id != self.run.run_id for item in self.links):
            raise ValueError("stored experiment links belong to another run")
        if any(
            item.run_id != self.run.run_id or item.link_id not in link_ids
            for item in self.annotations
        ):
            raise ValueError("stored annotations do not match the experiment")
        return self


class ModelLinkSuggestion(StrictModel):
    """Transient review item.  Excerpts are masked in repr and never persisted."""

    link: ModelLinkStoredLink
    query_excerpt: SecretStr = Field(repr=False, min_length=1, max_length=MODEL_LINK_EXCERPT_CHARACTERS + 1)
    candidate_excerpt: SecretStr = Field(repr=False, min_length=1, max_length=MODEL_LINK_EXCERPT_CHARACTERS + 1)


class ModelLinkExperimentOutcome(StrictModel):
    experiment: ModelLinkStoredExperiment
    suggestions: tuple[ModelLinkSuggestion, ...] = ()
    applied: bool


class ModelLinkRunner(Protocol):
    def run(self, request: ModelLinkRunnerRequest) -> ModelLinkRunnerResult: ...


class ModelLinkExperimentRepository(Protocol):
    def save_completed(
        self,
        run: ModelLinkRunRecord,
        links: tuple[ModelLinkStoredLink, ...],
    ) -> None: ...

    def get(self, run_id: str) -> ModelLinkStoredExperiment | None: ...

    def get_latest(self, session_id: str) -> ModelLinkStoredExperiment | None: ...

    def append_annotation(
        self,
        annotation: ModelLinkAnnotationRecord,
        *,
        expected_revision: int,
    ) -> bool: ...

    def delete_for_privacy(self, run_id: str) -> bool: ...


class SessionModelLinkExperimentError(RuntimeError):
    code = "model_link_experiment_failed"


class ModelLinkInputError(SessionModelLinkExperimentError):
    code = "invalid_model_link_request"


class ModelLinkConfirmationError(SessionModelLinkExperimentError):
    code = "model_link_confirmation_required"


class ModelLinkConsentError(SessionModelLinkExperimentError):
    code = "redacted_content_consent_required"


class ModelLinkSelectionError(SessionModelLinkExperimentError):
    code = "session_not_in_safe_index"


class ModelLinkCompatibilityError(SessionModelLinkExperimentError):
    code = "provider_compatibility_blocked"


class ModelLinkSourceError(SessionModelLinkExperimentError):
    def __init__(self, reason: TextSourceFailureReason) -> None:
        self.reason = reason
        self.code = reason.value
        super().__init__(reason.value)


class ModelLinkNoCandidatesError(SessionModelLinkExperimentError):
    code = "no_model_link_candidates"


class ModelLinkExecutionError(SessionModelLinkExperimentError):
    code = "local_model_execution_failed"


class ModelLinkPersistenceError(SessionModelLinkExperimentError):
    code = "model_link_persistence_failed"


class ModelLinkConflictError(SessionModelLinkExperimentError):
    code = "model_link_revision_conflict"


def _excerpt(value: SecretStr) -> SecretStr:
    compact = " ".join(value.get_secret_value().split())
    if len(compact) > MODEL_LINK_EXCERPT_CHARACTERS:
        compact = compact[: MODEL_LINK_EXCERPT_CHARACTERS - 3].rstrip() + "..."
    return SecretStr(compact)


def _rank(values: dict[str, float]) -> dict[str, int]:
    ordered = sorted(values, key=lambda key: (-values[key], key))
    return {key: index + 1 for index, key in enumerate(ordered)}


class SessionModelLinkExperimentService:
    """Run and label a bounded local neural comparison for one safe session."""

    def __init__(
        self,
        access_policy: SessionTextAnalysisAccessPolicy,
        repository: ModelLinkExperimentRepository,
        source_factory: SessionTextAnalysisSourceFactory,
        compatibility_policy: SessionTextAnalysisCompatibilityPolicy,
        identifiers: SessionTextAnalysisIdFactory,
        runner: ModelLinkRunner,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._access_policy = access_policy
        self._repository = repository
        self._source_factory = source_factory
        self._compatibility_policy = compatibility_policy
        self._identifiers = identifiers
        self._runner = runner
        self._clock = clock
        self._lock = Lock()

    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        confirmation: str,
        device: ModelExperimentDevice,
        idempotency_key: str,
    ) -> ModelLinkExperimentOutcome:
        if provider not in TEXT_ANALYSIS_PROVIDERS or PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise ModelLinkInputError("model-link selection is invalid")
        if confirmation != MODEL_LINK_CONFIRMATION:
            raise ModelLinkConfirmationError("explicit model-link confirmation is required")
        if not isinstance(device, ModelExperimentDevice) or _IDEMPOTENCY.fullmatch(idempotency_key) is None:
            raise ModelLinkInputError("model-link request is invalid")

        request_fingerprint = self._identifiers.fingerprint(
            "session-model-link-request-v1",
            (
                MODEL_LINK_EXPERIMENT_KEY,
                str(MODEL_LINK_EXPERIMENT_VERSION),
                provider.value,
                session_id,
                device.value,
                idempotency_key,
                MODEL_LINK_POLICY_VERSION,
            ),
        )
        run_id = self._identifiers.fingerprint(
            "session-model-link-run-v1", (session_id, request_fingerprint)
        )
        with self._lock:
            existing = self._safe_get(run_id)
            if existing is not None:
                return ModelLinkExperimentOutcome(
                    experiment=existing,
                    suggestions=(),
                    applied=False,
                )
            self._enforce_access(provider, session_id)
            context = self._read_context(provider, session_id)
            cases = self._build_cases(context)
            started_at = _utc(self._clock())
            try:
                runner_result = self._runner.run(
                    ModelLinkRunnerRequest(device=device, cases=cases)
                )
                run, links, suggestions = self._assemble(
                    context=context,
                    cases=cases,
                    result=runner_result,
                    run_id=run_id,
                    request_fingerprint=request_fingerprint,
                    started_at=started_at,
                )
            except SessionModelLinkExperimentError:
                raise
            except Exception:
                raise ModelLinkExecutionError("local model comparison failed") from None
            try:
                self._repository.save_completed(run, links)
            except Exception:
                race = self._safe_get(run_id)
                if race is not None:
                    return ModelLinkExperimentOutcome(
                        experiment=race,
                        suggestions=(),
                        applied=False,
                    )
                raise ModelLinkPersistenceError("model-link result could not be stored") from None
            return ModelLinkExperimentOutcome(
                experiment=ModelLinkStoredExperiment(run=run, links=links),
                suggestions=suggestions,
                applied=True,
            )

    def latest(self, session_id: str) -> ModelLinkStoredExperiment | None:
        if PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise ModelLinkInputError("model-link selection is invalid")
        try:
            return self._repository.get_latest(session_id)
        except Exception:
            raise ModelLinkPersistenceError("model-link results are unavailable") from None

    def annotate(
        self,
        *,
        run_id: str,
        link_id: str,
        label: ModelLinkAnnotationLabel,
        expected_revision: int,
    ) -> ModelLinkAnnotationRecord:
        if (
            PSEUDONYM_PATTERN.fullmatch(run_id) is None
            or PSEUDONYM_PATTERN.fullmatch(link_id) is None
            or not isinstance(label, ModelLinkAnnotationLabel)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise ModelLinkInputError("model-link annotation is invalid")
        annotation = ModelLinkAnnotationRecord(
            run_id=run_id,
            link_id=link_id,
            revision=expected_revision + 1,
            label=label,
            annotated_at=_utc(self._clock()),
        )
        try:
            applied = self._repository.append_annotation(
                annotation, expected_revision=expected_revision
            )
        except Exception:
            raise ModelLinkPersistenceError("model-link annotation could not be stored") from None
        if not applied:
            raise ModelLinkConflictError("model-link annotation revision changed")
        return annotation

    def _safe_get(self, run_id: str) -> ModelLinkStoredExperiment | None:
        try:
            return self._repository.get(run_id)
        except Exception:
            raise ModelLinkPersistenceError("model-link persistence is unavailable") from None

    def _enforce_access(self, provider: Provider, session_id: str) -> None:
        try:
            consent = self._access_policy.has_active_consent(
                provider, DataTier.REDACTED_CONTENT
            )
        except Exception:
            raise ModelLinkConsentError("redacted-content consent is unavailable") from None
        if not consent:
            raise ModelLinkConsentError("redacted-content consent is required")
        try:
            indexed = self._access_policy.selection_is_indexed(
                provider,
                project_ids=frozenset(),
                session_ids=frozenset((session_id,)),
            )
        except Exception:
            raise ModelLinkSelectionError("safe selection is unavailable") from None
        if not indexed:
            raise ModelLinkSelectionError("session is not present in the safe index")
        try:
            self._compatibility_policy.require_compatible(provider.value)
        except Exception:
            raise ModelLinkCompatibilityError("provider compatibility is not verified") from None

    def _read_context(self, provider: Provider, session_id: str) -> P1TextAnalysisInput:
        selection = TextAnalysisSelection(
            provider=provider,
            session_id=session_id,
            max_messages=COACHING_PROFILE_V1.max_messages,
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
                task_profile=COACHING_PROFILE_V1.task_profile,
            )
        except TextSourceReadError as error:
            raise ModelLinkSourceError(error.reason) from None
        except Exception:
            raise ModelLinkSourceError(TextSourceFailureReason.PROVIDER_UNAVAILABLE) from None
        if context.provider is not provider or context.session_id != session_id:
            raise ModelLinkSourceError(TextSourceFailureReason.PROVIDER_UNAVAILABLE)
        return context

    @staticmethod
    def _build_cases(context: P1TextAnalysisInput) -> tuple[ModelLinkCase, ...]:
        queries = [
            message
            for message in context.messages
            if message.role is TextRole.USER
            and message.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
        ][-MODEL_LINK_MAX_QUERIES:]
        cases: list[ModelLinkCase] = []
        for query in queries:
            candidates = [
                message
                for message in context.messages
                if message.sequence > query.sequence
                and message.role is TextRole.AGENT
                and message.kind in {TextMessageKind.RESPONSE, TextMessageKind.PLAN}
            ][:MODEL_LINK_MAX_CANDIDATES]
            if not candidates:
                continue
            cases.append(
                ModelLinkCase(
                    query_message_id=query.message_id,
                    query_sequence=query.sequence,
                    query_text=SecretStr(
                        query.text.get_secret_value()[:MODEL_LINK_MAX_TEXT_CHARACTERS]
                    ),
                    candidates=tuple(
                        ModelLinkCandidate(
                            message_id=item.message_id,
                            sequence=item.sequence,
                            kind=(
                                ModelLinkCandidateKind.PLAN
                                if item.kind is TextMessageKind.PLAN
                                else ModelLinkCandidateKind.RESPONSE
                            ),
                            text=SecretStr(
                                item.text.get_secret_value()[:MODEL_LINK_MAX_TEXT_CHARACTERS]
                            ),
                        )
                        for item in candidates
                    ),
                )
            )
        if not cases:
            raise ModelLinkNoCandidatesError("no request-to-agent candidates were observed")
        return tuple(cases)

    def _assemble(
        self,
        *,
        context: P1TextAnalysisInput,
        cases: tuple[ModelLinkCase, ...],
        result: ModelLinkRunnerResult,
        run_id: str,
        request_fingerprint: str,
        started_at: datetime,
    ) -> tuple[
        ModelLinkRunRecord,
        tuple[ModelLinkStoredLink, ...],
        tuple[ModelLinkSuggestion, ...],
    ]:
        expected_pairs = {
            (case.query_message_id, candidate.message_id)
            for case in cases
            for candidate in case.candidates
        }
        score_by_pair = {
            (score.query_message_id, score.candidate_message_id): score
            for score in result.scores
        }
        if set(score_by_pair) != expected_pairs or len(score_by_pair) != len(result.scores):
            raise ModelLinkExecutionError("local model output did not cover the bounded input")
        candidate_by_pair = {
            (case.query_message_id, candidate.message_id): (case, candidate)
            for case in cases
            for candidate in case.candidates
        }
        links: list[ModelLinkStoredLink] = []
        suggestions: list[ModelLinkSuggestion] = []
        agreement_count = 0
        for case in cases:
            query_scores = {
                candidate.message_id: score_by_pair[
                    (case.query_message_id, candidate.message_id)
                ]
                for candidate in case.candidates
            }
            qwen_ranks = _rank(
                {key: value.qwen_score for key, value in query_scores.items()}
            )
            bge_ranks = _rank(
                {key: value.bge_score for key, value in query_scores.items()}
            )
            qwen_top = min(qwen_ranks, key=qwen_ranks.get)
            bge_top = min(bge_ranks, key=bge_ranks.get)
            if qwen_top == bge_top:
                agreement_count += 1
            for candidate_id in sorted({qwen_top, bge_top}):
                pair = (case.query_message_id, candidate_id)
                _, candidate = candidate_by_pair[pair]
                score = score_by_pair[pair]
                recommended_by = (
                    ModelLinkRecommendation.BOTH
                    if candidate_id == qwen_top == bge_top
                    else ModelLinkRecommendation.QWEN
                    if candidate_id == qwen_top
                    else ModelLinkRecommendation.BGE
                )
                link_id = self._identifiers.fingerprint(
                    "session-model-link-v1", (run_id, *pair)
                )
                link = ModelLinkStoredLink(
                    run_id=run_id,
                    link_id=link_id,
                    query_message_id=case.query_message_id,
                    candidate_message_id=candidate_id,
                    query_sequence=case.query_sequence,
                    candidate_sequence=candidate.sequence,
                    candidate_kind=candidate.kind,
                    qwen_score=score.qwen_score,
                    qwen_rank=qwen_ranks[candidate_id],
                    bge_score=score.bge_score,
                    bge_rank=bge_ranks[candidate_id],
                    recommended_by=recommended_by,
                )
                links.append(link)
                suggestions.append(
                    ModelLinkSuggestion(
                        link=link,
                        query_excerpt=_excerpt(case.query_text),
                        candidate_excerpt=_excerpt(candidate.text),
                    )
                )
        finished_at = _utc(self._clock())
        run = ModelLinkRunRecord(
            run_id=run_id,
            session_id=context.session_id,
            request_fingerprint=request_fingerprint,
            input_fingerprint=context.analysis_window_fingerprint,
            provider=context.provider,
            provider_version=context.provider_version,
            adapter_version=context.adapter_version,
            source_schema_version=context.source_schema_version,
            content_schema_version=context.content_schema_version,
            redactor_version=context.redactor_version,
            resolved_device=result.resolved_device,
            qwen_model=result.qwen_model,
            bge_model=result.bge_model,
            query_count=len(cases),
            link_count=len(links),
            agreement_count=agreement_count,
            started_at=started_at,
            finished_at=finished_at,
        )
        return run, tuple(links), tuple(suggestions)
