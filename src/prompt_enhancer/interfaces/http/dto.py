"""Strict, content-free HTTP DTOs for task discovery and analysis views.

The API maps persistence records explicitly instead of serializing arbitrary
objects. These schemas have no field for prompt text, paths, source snippets,
account data, or provider credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...application.discovery import SignalDirection
from ...application.persistence import (
    AnalysisResultRecord,
    AnalysisRunRecord,
    AnalysisRunStatus,
    CandidateDecisionStatus,
    CandidateListItem,
    CandidateSignalRecord,
    DecisionAction,
    DecisionRevisionRole,
    MetricValueState,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisSignalRecord,
    SessionAnalysisResultRecord,
    SessionAnalysisRunRecord,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricScopeState,
    TaskCandidateRecord,
    TaskDecisionRecord,
    TaskRevisionRecord,
)
from ...display_labels import (
    PROJECT_DISPLAY_NAME_MAX_LENGTH,
    SESSION_DISPLAY_NAME_MAX_LENGTH,
)
from ...domain import (
    DataTier,
    MetricSource,
    PSEUDONYM_PATTERN,
    Provider,
    SessionState,
)


Pseudonym = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=PSEUDONYM_PATTERN.pattern,
        strict=True,
    ),
]


class HttpDto(BaseModel):
    """Base for API-owned DTOs; response construction is validated too."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )


class CapabilitiesDto(HttpDto):
    """Exact, content-free feature contract consumed by the dashboard."""

    cost_mode: Literal["offline_only"]
    data_tier: Literal["metadata"]
    network_inference: Literal[False]
    # False unless the owner enabled the on-demand session reader (ADR 0011);
    # never true silently.
    raw_transcripts: bool = False
    arbitrary_sql: Literal[False]
    write_api: bool
    task_review: bool
    task_lifecycle: bool
    task_analysis: bool
    session_text_analysis: bool
    session_model_link_experiment: bool
    session_text_analysis_data_tier: Literal["redacted_content"] | None
    session_text_content_persistence: Literal[False]
    codex_local_source: bool
    claude_code_local_source: bool = False
    local_models: bool = False
    prompt_check: bool = False
    local_agent: bool = False
    annotation: bool = False
    shared_folders: bool = False
    manual_display_labels: bool
    browser_session: Literal[True]
    demo_provider: Literal["synthetic"]

    @model_validator(mode="after")
    def validate_text_analysis_capability(self) -> CapabilitiesDto:
        expected_tier = (
            "redacted_content" if self.session_text_analysis else None
        )
        if self.session_text_analysis_data_tier != expected_tier:
            raise ValueError("text-analysis capability and data tier disagree")
        if self.session_text_analysis and not self.write_api:
            raise ValueError("text analysis requires the explicit command surface")
        if self.session_model_link_experiment and not self.write_api:
            raise ValueError("model-link experiments require a command surface")
        if self.task_lifecycle and not self.write_api:
            raise ValueError("task lifecycle requires the explicit command surface")
        return self


def _catalog_datetime(value: object, *, nullable: bool) -> datetime | None:
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("catalog timestamp is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("catalog timestamp must include a timezone")
    return parsed


class SessionCatalogItemDto(HttpDto):
    """Exact allowlist for one private-label, content-free catalog row."""

    session_id: Pseudonym
    installation_id: Pseudonym
    project_id: Pseudonym
    provider: Provider
    provider_version: str | None = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=128)
    source_schema_version: str | None = Field(min_length=1, max_length=128)
    started_at: datetime
    ended_at: datetime | None
    terminal_state: SessionState | None
    events_complete: bool
    project_display_name: str | None = Field(
        min_length=1,
        max_length=PROJECT_DISPLAY_NAME_MAX_LENGTH,
        repr=False,
    )
    session_display_name: str | None = Field(
        min_length=1,
        max_length=SESSION_DISPLAY_NAME_MAX_LENGTH,
        repr=False,
    )
    project_display_name_origin: Literal["provider", "manual", "unknown"]
    session_display_name_origin: Literal["provider", "manual", "unknown"]
    project_manual_label_revision: int = Field(ge=0)
    session_manual_label_revision: int = Field(ge=0)

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> SessionCatalogItemDto:
        return cls(
            session_id=record.get("session_id"),
            installation_id=record.get("installation_id"),
            project_id=record.get("project_id"),
            provider=Provider(str(record.get("provider"))),
            provider_version=record.get("provider_version"),
            adapter_version=record.get("adapter_version"),
            source_schema_version=record.get("source_schema_version"),
            started_at=_catalog_datetime(record.get("started_at"), nullable=False),
            ended_at=_catalog_datetime(record.get("ended_at"), nullable=True),
            terminal_state=(
                None
                if record.get("terminal_state") is None
                else SessionState(str(record.get("terminal_state")))
            ),
            events_complete=record.get("events_complete"),
            project_display_name=record.get("project_display_name"),
            session_display_name=record.get("session_display_name"),
            project_display_name_origin=record.get(
                "project_display_name_origin"
            ),
            session_display_name_origin=record.get(
                "session_display_name_origin"
            ),
            project_manual_label_revision=record.get(
                "project_manual_label_revision"
            ),
            session_manual_label_revision=record.get(
                "session_manual_label_revision"
            ),
        )


class SessionCatalogListResponse(HttpDto):
    sessions: tuple[SessionCatalogItemDto, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ProjectSessionCatalogResponse(SessionCatalogListResponse):
    total: int = Field(ge=0)
    has_more: bool

    @model_validator(mode="after")
    def validate_page(self) -> ProjectSessionCatalogResponse:
        if len(self.sessions) > self.limit:
            raise ValueError("session page cannot exceed its limit")
        if self.offset + len(self.sessions) > self.total:
            raise ValueError("session page cannot exceed its total")
        if self.has_more != (self.offset + len(self.sessions) < self.total):
            raise ValueError("session page continuation must match its total")
        return self


class CandidateSignalDto(HttpDto):
    key: str
    version: int = Field(ge=1)
    session_ids: tuple[Pseudonym, Pseudonym]
    direction: SignalDirection
    confidence: float | None = Field(default=None, ge=0, le=1)
    weight: float = Field(gt=0, allow_inf_nan=False)
    evidence_code: str
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    numeric_evidence: float | None = Field(default=None, allow_inf_nan=False)
    evidence_unit: str | None

    @classmethod
    def from_record(cls, record: CandidateSignalRecord) -> CandidateSignalDto:
        return cls(
            key=record.key,
            version=record.version,
            session_ids=record.session_ids,
            direction=record.direction,
            confidence=record.confidence,
            weight=record.weight,
            evidence_code=record.evidence_code,
            observed_count=record.observed_count,
            eligible_count=record.eligible_count,
            coverage=record.coverage,
            numeric_evidence=record.numeric_evidence,
            evidence_unit=record.evidence_unit,
        )


class TaskCandidateDto(HttpDto):
    candidate_id: Pseudonym
    provider: Provider
    installation_id: Pseudonym
    project_id: Pseudonym
    session_ids: tuple[Pseudonym, ...]
    signals: tuple[CandidateSignalDto, ...]
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    discovery_version: str
    input_fingerprint: Pseudonym
    created_at: datetime
    # Display labels from the session catalog (project title, first session's
    # title) so the inbox can name a candidate instead of showing a hash.
    project_display_name: str | None = Field(default=None, max_length=120)
    session_display_name: str | None = Field(default=None, max_length=160)

    @classmethod
    def from_record(cls, record: TaskCandidateRecord) -> TaskCandidateDto:
        return cls(
            candidate_id=record.candidate_id,
            provider=record.provider,
            installation_id=record.installation_id,
            project_id=record.project_id,
            session_ids=record.session_ids,
            signals=tuple(
                CandidateSignalDto.from_record(signal) for signal in record.signals
            ),
            confidence=record.confidence,
            observed_count=record.observed_count,
            eligible_count=record.eligible_count,
            coverage=record.coverage,
            discovery_version=record.discovery_version,
            input_fingerprint=record.input_fingerprint,
            created_at=record.created_at,
        )


class CandidateResponse(HttpDto):
    candidate: TaskCandidateDto


class CandidateListItemDto(HttpDto):
    candidate: TaskCandidateDto
    decision_status: CandidateDecisionStatus
    decision_id: Pseudonym | None
    decision_action: DecisionAction | None
    # "automation" marks a single-session candidate accepted without a person.
    decision_source: Literal["person", "automation"] | None = None

    @classmethod
    def from_record(cls, record: CandidateListItem) -> CandidateListItemDto:
        return cls(
            candidate=TaskCandidateDto.from_record(record.candidate),
            decision_status=record.decision_status,
            decision_id=record.decision_id,
            decision_action=record.decision_action,
            decision_source=record.decision_source,
        )


class CandidateListResponse(HttpDto):
    candidates: tuple[CandidateListItemDto, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class DecisionRevisionLinkDto(HttpDto):
    task_id: Pseudonym
    revision: int = Field(ge=1)
    role: DecisionRevisionRole


class TaskDecisionDto(HttpDto):
    decision_id: Pseudonym
    action: DecisionAction
    candidate_ids: tuple[Pseudonym, ...]
    revision_links: tuple[DecisionRevisionLinkDto, ...]
    decision_schema_version: str
    decision_code: str | None
    decided_at: datetime
    decision_source: Literal["person", "automation"] = "person"

    @classmethod
    def from_record(cls, record: TaskDecisionRecord) -> TaskDecisionDto:
        return cls(
            decision_id=record.decision_id,
            action=record.action,
            candidate_ids=record.candidate_ids,
            revision_links=tuple(
                DecisionRevisionLinkDto(
                    task_id=link.task_id,
                    revision=link.revision,
                    role=link.role,
                )
                for link in record.revision_links
            ),
            decision_schema_version=record.decision_schema_version,
            decision_code=record.decision_code,
            decision_source=record.decision_source,
            decided_at=record.decided_at,
        )


class CandidateDecisionsResponse(HttpDto):
    candidate_id: Pseudonym
    decisions: tuple[TaskDecisionDto, ...]


class TaskRevisionDto(HttpDto):
    task_id: Pseudonym
    revision: int = Field(ge=1)
    project_id: Pseudonym
    task_type: str
    lifecycle_state: str
    session_ids: tuple[Pseudonym, ...]
    input_fingerprint: Pseudonym
    created_at: datetime

    @classmethod
    def from_record(cls, record: TaskRevisionRecord) -> TaskRevisionDto:
        return cls(
            task_id=record.task_id,
            revision=record.revision,
            project_id=record.project_id,
            task_type=record.task_type,
            lifecycle_state=record.lifecycle_state,
            session_ids=record.session_ids,
            input_fingerprint=record.input_fingerprint,
            created_at=record.created_at,
        )


class TaskRevisionResponse(HttpDto):
    task: TaskRevisionDto


class TaskRevisionListResponse(HttpDto):
    tasks: tuple[TaskRevisionDto, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AnalysisRunDto(HttpDto):
    run_id: Pseudonym
    task_id: Pseudonym
    task_revision: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    data_tier: DataTier
    input_fingerprint: Pseudonym
    metric_engine_version: str
    redactor_version: str
    schema_version: int = Field(ge=1)
    started_at: datetime
    status: AnalysisRunStatus
    finished_at: datetime | None
    failure_code: str | None

    @classmethod
    def from_record(cls, record: AnalysisRunRecord) -> AnalysisRunDto:
        return cls(
            run_id=record.draft.run_id,
            task_id=record.draft.task_id,
            task_revision=record.draft.task_revision,
            metric_pack_key=record.draft.metric_pack_key,
            metric_pack_version=record.draft.metric_pack_version,
            data_tier=record.draft.data_tier,
            input_fingerprint=record.draft.input_fingerprint,
            metric_engine_version=record.draft.metric_engine_version,
            redactor_version=record.draft.redactor_version,
            schema_version=record.draft.schema_version,
            started_at=record.draft.started_at,
            status=record.status,
            finished_at=record.finished_at,
            failure_code=record.failure_code,
        )


class AnalysisRunListResponse(HttpDto):
    runs: tuple[AnalysisRunDto, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AnalysisResultDto(HttpDto):
    key: str
    version: int = Field(ge=1)
    dimension: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=1024)
    value_state: MetricValueState
    numeric_value: float | None
    text_value: str | None
    unit: str
    source: MetricSource
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    calculator_version: str
    evidence_event_ids: tuple[Pseudonym, ...]
    model_id: str | None
    model_revision: str | None
    tokenizer_id: str | None
    prompt_version: str | None
    rubric_version: str | None
    error_code: str | None
    computed_at: datetime

    @classmethod
    def from_record(
        cls,
        record: AnalysisResultRecord,
        *,
        definition: Mapping[str, object] | None = None,
    ) -> AnalysisResultDto:
        observation = record.observation

        def optional_text(field: str) -> str | None:
            value = definition.get(field) if definition is not None else None
            return value if isinstance(value, str) else None

        return cls(
            key=observation.key,
            version=observation.version,
            dimension=optional_text("dimension"),
            display_name=optional_text("display_name"),
            description=optional_text("description"),
            value_state=record.value_state,
            numeric_value=observation.numeric_value,
            text_value=observation.text_value,
            unit=observation.unit,
            source=observation.source,
            observed_count=observation.observed_count,
            eligible_count=observation.eligible_count,
            coverage=observation.coverage,
            confidence=observation.confidence,
            calculator_version=record.calculator_version,
            evidence_event_ids=record.evidence_event_ids,
            model_id=record.model_id,
            model_revision=record.model_revision,
            tokenizer_id=record.tokenizer_id,
            prompt_version=record.prompt_version,
            rubric_version=record.rubric_version,
            error_code=record.error_code,
            computed_at=record.computed_at,
        )


class AnalysisRunResponse(HttpDto):
    run: AnalysisRunDto
    results: tuple[AnalysisResultDto, ...]


class SessionAnalysisRunDto(HttpDto):
    """Content-free provenance for one selected redacted session window."""

    run_id: Pseudonym
    session_id: Pseudonym
    request_fingerprint: Pseudonym
    input_fingerprint: Pseudonym
    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    metric_scope_state: SessionMetricScopeState
    selected_metric_keys: tuple[str, ...] = Field(max_length=100)
    data_tier: DataTier
    consent_purpose: str
    consent_policy_version: str
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    content_schema_version: str
    metric_engine_version: str
    redactor_version: str
    model_plan_fingerprint: Pseudonym
    schema_version: int = Field(ge=1)
    local_only: bool
    started_at: datetime
    status: AnalysisRunStatus
    finished_at: datetime | None
    failure_code: str | None

    @classmethod
    def from_record(
        cls, record: SessionAnalysisRunRecord
    ) -> SessionAnalysisRunDto:
        draft = record.draft
        return cls(
            run_id=draft.run_id,
            session_id=draft.session_id,
            request_fingerprint=draft.request_fingerprint,
            input_fingerprint=draft.input_fingerprint,
            analysis_profile_key=draft.analysis_profile_key,
            analysis_profile_version=draft.analysis_profile_version,
            metric_pack_key=draft.metric_pack_key,
            metric_pack_version=draft.metric_pack_version,
            metric_scope_state=draft.metric_scope_state,
            selected_metric_keys=draft.selected_metric_keys,
            data_tier=draft.data_tier,
            consent_purpose=draft.consent_purpose,
            consent_policy_version=draft.consent_policy_version,
            provider=draft.provider,
            provider_version=draft.provider_version,
            adapter_version=draft.adapter_version,
            source_schema_version=draft.source_schema_version,
            content_schema_version=draft.content_schema_version,
            metric_engine_version=draft.metric_engine_version,
            redactor_version=draft.redactor_version,
            model_plan_fingerprint=draft.model_plan_fingerprint,
            schema_version=draft.schema_version,
            local_only=draft.local_only,
            started_at=draft.started_at,
            status=record.status,
            finished_at=record.finished_at,
            failure_code=record.failure_code,
        )


class SessionAnalysisEvidenceDto(HttpDto):
    message_id: Pseudonym
    origin: SessionEvidenceOrigin

    @classmethod
    def from_record(
        cls, record: SessionAnalysisEvidenceRecord
    ) -> SessionAnalysisEvidenceDto:
        return cls(message_id=record.message_id, origin=record.origin)


class SessionAnalysisSignalDto(HttpDto):
    """Closed factor receipt; contains no text, excerpt, or evidence identity."""

    code: str
    status: str
    count: int | None

    @classmethod
    def from_record(
        cls, record: SessionAnalysisSignalRecord
    ) -> SessionAnalysisSignalDto:
        return cls(
            code=record.code,
            status=record.status.value,
            count=record.count,
        )


class SessionMetricFractionDto(HttpDto):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)


class SessionAnalysisResultDto(HttpDto):
    """Numeric result, evidence identities and exact definition presentation."""

    key: str
    version: int = Field(ge=1)
    dimension: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=1024)
    metric_schema_version: int = Field(ge=1)
    value_state: MetricValueState
    numeric_value: float | None
    unit: str
    source: MetricSource
    direction: SessionMetricDirection
    applicability: SessionMetricApplicability
    aggregation_method: SessionMetricAggregation
    fraction: SessionMetricFractionDto | None
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_data_tier: DataTier
    evidence: tuple[SessionAnalysisEvidenceDto, ...]
    signals: tuple[SessionAnalysisSignalDto, ...]
    explanation_code: str
    error_code: str | None
    algorithm_id: str
    algorithm_version: str
    model_id: str | None
    model_revision: str | None
    model_license: str | None
    tokenizer_id: str | None
    prompt_version: str | None
    rubric_version: str | None
    computed_at: datetime

    @classmethod
    def from_record(
        cls,
        record: SessionAnalysisResultRecord,
        *,
        definition: Mapping[str, object] | None = None,
    ) -> SessionAnalysisResultDto:
        observation = record.observation

        def optional_text(field: str) -> str | None:
            value = definition.get(field) if definition is not None else None
            return value if isinstance(value, str) else None

        fraction = None
        if (
            record.fraction_numerator is not None
            and record.fraction_denominator is not None
        ):
            fraction = SessionMetricFractionDto(
                numerator=record.fraction_numerator,
                denominator=record.fraction_denominator,
            )
        return cls(
            key=observation.key,
            version=observation.version,
            dimension=optional_text("dimension"),
            display_name=optional_text("display_name"),
            description=optional_text("description"),
            metric_schema_version=record.metric_schema_version,
            value_state=record.value_state,
            numeric_value=observation.numeric_value,
            unit=observation.unit,
            source=observation.source,
            direction=record.direction,
            applicability=record.applicability,
            aggregation_method=record.aggregation_method,
            fraction=fraction,
            observed_count=observation.observed_count,
            eligible_count=observation.eligible_count,
            coverage=observation.coverage,
            confidence=observation.confidence,
            evidence_data_tier=record.evidence_data_tier,
            evidence=tuple(
                SessionAnalysisEvidenceDto.from_record(item)
                for item in record.evidence
            ),
            signals=tuple(
                SessionAnalysisSignalDto.from_record(item)
                for item in record.signals
            ),
            explanation_code=record.explanation_code,
            error_code=record.error_code,
            algorithm_id=record.algorithm_id,
            algorithm_version=record.algorithm_version,
            model_id=record.model_id,
            model_revision=record.model_revision,
            model_license=record.model_license,
            tokenizer_id=record.tokenizer_id,
            prompt_version=record.prompt_version,
            rubric_version=record.rubric_version,
            computed_at=record.computed_at,
        )


class SessionAnalysisRunListResponse(HttpDto):
    session_id: Pseudonym
    runs: tuple[SessionAnalysisRunDto, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SessionAnalysisRunResponse(HttpDto):
    run: SessionAnalysisRunDto
    results: tuple[SessionAnalysisResultDto, ...]
