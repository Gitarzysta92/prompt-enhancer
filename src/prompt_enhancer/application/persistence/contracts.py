"""Content-free contracts for task and immutable analysis persistence.

These records deliberately contain only pseudonymous identifiers, bounded safe
labels, numeric observations, and provenance. They provide no place to attach
prompt text, summaries, source snippets, paths, or provider account data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import (
    DataTier,
    MetricObservation,
    Provider,
    SignalDirection,
    StrictModel,
)

if TYPE_CHECKING:
    from ..history.persistence import (
        RepositorySealedTemporalBatchV1,
        SyntheticTemporalCompletionRequestV1,
    )


_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_SAFE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$")
_SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


# This is the immutable application contract carried by selected-session run
# rows, not the SQLite migration level. Database-only additive migrations must
# not silently rewrite the provenance identity of an existing analysis plan.
SESSION_ANALYSIS_RUN_SCHEMA_VERSION = 21
_AUTOMATION_PUBLICATION_REJECTION_CODES = frozenset(
    {
        "automation_publication_deadline_exceeded",
        "automation_publication_clock_regressed",
        "automation_publication_deadline_missing",
    }
)


class SessionAnalysisPublicationRejectedError(RuntimeError):
    """The queue atomically rejected an automation result publication."""

    def __init__(self, reason_code: str) -> None:
        if (
            not isinstance(reason_code, str)
            or reason_code not in _AUTOMATION_PUBLICATION_REJECTION_CODES
        ):
            raise ValueError("publication rejection reason is not reviewed")
        self.reason_code = reason_code
        super().__init__(reason_code)


def _pseudonym(value: str) -> str:
    if not _HEX_64.fullmatch(value):
        raise ValueError("persistent identifiers must be 64-character safe identifiers")
    return value


def _optional_pseudonym(value: str | None) -> str | None:
    if value is None:
        return None
    return _pseudonym(value)


def _safe_code(value: str | None) -> str | None:
    if value is not None and not _SAFE_CODE.fullmatch(value):
        raise ValueError("provenance versions must use safe identifier characters")
    return value


def _safe_label(value: str | None) -> str | None:
    if value is not None and not _SAFE_LABEL.fullmatch(value):
        raise ValueError("labels must be short content-free identifiers")
    return value


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


def _unique(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} cannot contain duplicates")
    return values


def _selected_metric_keys(values: tuple[str, ...]) -> tuple[str, ...]:
    if values != tuple(sorted(values)) or len(set(values)) != len(values):
        raise ValueError("selected metric keys must be unique and sorted")
    if any(_SAFE_CODE.fullmatch(value) is None for value in values):
        raise ValueError("selected metric keys must use safe identifier characters")
    return values


class DecisionAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MERGE = "merge"
    SPLIT = "split"


class CandidateDecisionStatus(StrEnum):
    UNDECIDED = "undecided"
    DECIDED = "decided"


class DecisionRevisionRole(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class AnalysisRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionMetricScopeState(StrEnum):
    """Whether a persisted run's complete requested metric set is recoverable."""

    EXACT = "exact"
    LEGACY_UNKNOWN = "legacy_unknown"


class SessionAnalysisCompletionAuthority(StrictModel):
    """Ephemeral queue authority checked atomically with result persistence.

    The identifiers are content-free and are never stored with the analysis
    snapshot.  SQLite uses them only to prove that the exact local automation
    grant and worker lease are still live in the result-commit transaction.
    """

    job_id: str
    automation_grant_id: str
    lease_owner: str = Field(repr=False)
    lease_token: str = Field(repr=False)

    _validate_ids = field_validator(
        "job_id",
        "automation_grant_id",
        "lease_owner",
        "lease_token",
    )(_pseudonym)


class MetricValueState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    ABSTAINED = "abstained"
    EXECUTION_ERROR = "execution_error"


class SessionMetricDirection(StrEnum):
    """Display polarity for one persisted qualitative ratio."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class SessionMetricApplicability(StrEnum):
    """Whether the selected redacted analysis window supports a denominator."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class SessionMetricAggregation(StrEnum):
    """Server-side aggregation contract; ratios must never be client-averaged."""

    RATIO_OF_SUMS = "ratio_of_sums"


class SessionEvidenceOrigin(StrEnum):
    """How a content-free evidence reference entered the selected window."""

    DIRECT = "direct"
    INHERITED = "inherited"


class SessionMetricSignalStatus(StrEnum):
    DETECTED = "detected"
    MISSING = "missing"
    COUNTED = "counted"
    UNKNOWN = "unknown"


class CandidateSignalRecord(StrictModel):
    key: str
    version: int = Field(ge=1)
    session_ids: tuple[str, str]
    direction: SignalDirection
    confidence: float | None = Field(default=None, ge=0, le=1)
    weight: float = Field(gt=0, allow_inf_nan=False)
    evidence_code: str
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    numeric_evidence: float | None = Field(default=None, allow_inf_nan=False)
    evidence_unit: str | None = None

    _validate_key = field_validator("key")(_safe_code)
    _validate_evidence_code = field_validator("evidence_code")(_safe_label)
    _validate_evidence_unit = field_validator("evidence_unit")(_safe_code)
    _validate_session_ids = field_validator("session_ids")(
        lambda values: _unique(tuple(_pseudonym(value) for value in values), "session_ids")
    )

    @model_validator(mode="after")
    def validate_signal(self) -> CandidateSignalRecord:
        if self.observed_count > self.eligible_count:
            raise ValueError("observed_count cannot exceed eligible_count")
        expected = (
            0.0
            if self.eligible_count == 0
            else self.observed_count / self.eligible_count
        )
        if abs(self.coverage - expected) > 1e-9:
            raise ValueError("coverage must equal observed_count / eligible_count")
        if self.direction is SignalDirection.UNKNOWN:
            if self.confidence is not None:
                raise ValueError("unknown signals cannot have confidence")
        elif self.confidence is None:
            raise ValueError("directional signals require confidence")
        if self.confidence is not None and self.observed_count == 0:
            raise ValueError("confidence requires observed evidence")
        if (self.numeric_evidence is None) != (self.evidence_unit is None):
            raise ValueError("numeric evidence and unit must be supplied together")
        return self


class TaskCandidateRecord(StrictModel):
    candidate_id: str
    provider: Provider
    installation_id: str
    project_id: str
    session_ids: tuple[str, ...]
    signals: tuple[CandidateSignalRecord, ...]
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    discovery_version: str
    input_fingerprint: str
    created_at: datetime

    _validate_ids = field_validator(
        "candidate_id", "installation_id", "project_id", "input_fingerprint"
    )(_pseudonym)
    _validate_version = field_validator("discovery_version")(_safe_code)
    _validate_created_at = field_validator("created_at")(_utc)
    _validate_session_ids = field_validator("session_ids")(
        lambda values: _unique(tuple(_pseudonym(value) for value in values), "session_ids")
    )

    @model_validator(mode="after")
    def validate_candidate(self) -> TaskCandidateRecord:
        if not self.session_ids:
            raise ValueError("task candidates require at least one session")
        if self.observed_count > self.eligible_count:
            raise ValueError("observed_count cannot exceed eligible_count")
        expected = (
            0.0
            if self.eligible_count == 0
            else self.observed_count / self.eligible_count
        )
        if abs(self.coverage - expected) > 1e-9:
            raise ValueError("coverage must equal observed_count / eligible_count")
        if self.confidence is not None and self.observed_count == 0:
            raise ValueError("candidate confidence requires observed evidence")
        candidate_sessions = set(self.session_ids)
        if any(not set(signal.session_ids) <= candidate_sessions for signal in self.signals):
            raise ValueError("signal sessions must belong to the candidate")
        return self


class CandidateListItem(StrictModel):
    candidate: TaskCandidateRecord
    decision_status: CandidateDecisionStatus
    decision_id: str | None = None
    decision_action: DecisionAction | None = None
    decision_source: Literal["person", "automation"] | None = None

    _validate_decision_id = field_validator("decision_id")(_optional_pseudonym)

    @model_validator(mode="after")
    def validate_decision_state(self) -> CandidateListItem:
        has_decision = self.decision_id is not None or self.decision_action is not None
        if self.decision_status is CandidateDecisionStatus.UNDECIDED:
            if has_decision:
                raise ValueError("undecided candidates cannot include a decision")
        elif self.decision_id is None or self.decision_action is None:
            raise ValueError("decided candidates require decision provenance")
        return self


class TaskRevisionRecord(StrictModel):
    task_id: str
    revision: int = Field(ge=1)
    project_id: str
    task_type: str
    lifecycle_state: str
    session_ids: tuple[str, ...]
    input_fingerprint: str
    created_at: datetime

    _validate_ids = field_validator("task_id", "project_id", "input_fingerprint")(
        _pseudonym
    )
    _validate_labels = field_validator("task_type", "lifecycle_state")(_safe_label)
    _validate_created_at = field_validator("created_at")(_utc)
    _validate_session_ids = field_validator("session_ids")(
        lambda values: _unique(tuple(_pseudonym(value) for value in values), "session_ids")
    )

    @model_validator(mode="after")
    def require_sessions(self) -> TaskRevisionRecord:
        if not self.session_ids:
            raise ValueError("task revisions require at least one session")
        return self


class DecisionRevisionLink(StrictModel):
    task_id: str
    revision: int = Field(ge=1)
    role: DecisionRevisionRole

    _validate_task_id = field_validator("task_id")(_pseudonym)


class TaskDecisionRecord(StrictModel):
    decision_id: str
    action: DecisionAction
    candidate_ids: tuple[str, ...]
    revision_links: tuple[DecisionRevisionLink, ...]
    decision_schema_version: str
    decision_code: str | None = None
    decided_at: datetime
    # Provenance: a person in the review panel, or local automation that
    # accepted a single-session candidate (visible, never silent).
    decision_source: Literal["person", "automation"] = "person"

    _validate_decision_id = field_validator("decision_id")(_pseudonym)
    _validate_version = field_validator("decision_schema_version")(_safe_code)
    _validate_decision_code = field_validator("decision_code")(_safe_label)
    _validate_decided_at = field_validator("decided_at")(_utc)
    _validate_candidate_ids = field_validator("candidate_ids")(
        lambda values: _unique(tuple(_pseudonym(value) for value in values), "candidate_ids")
    )

    @model_validator(mode="after")
    def validate_shape(self) -> TaskDecisionRecord:
        revision_identities = {
            (link.task_id, link.revision, link.role) for link in self.revision_links
        }
        if len(revision_identities) != len(self.revision_links):
            raise ValueError("revision links cannot contain duplicates")
        inputs = [link for link in self.revision_links if link.role is DecisionRevisionRole.INPUT]
        outputs = [link for link in self.revision_links if link.role is DecisionRevisionRole.OUTPUT]
        if self.action is DecisionAction.REJECT:
            if (
                len(self.candidate_ids) != 1
                or self.revision_links
                or self.decision_code is None
            ):
                raise ValueError("reject decisions require candidates and no task revisions")
        elif self.decision_code is not None:
            raise ValueError("only reject decisions may include a decision code")
        elif self.action is DecisionAction.ACCEPT:
            if len(self.candidate_ids) != 1 or inputs or len(outputs) != 1:
                raise ValueError("accept decisions require one candidate and one output revision")
        elif self.action is DecisionAction.MERGE:
            source_count = len(self.candidate_ids) + len(inputs)
            if source_count < 2 or len(outputs) != 1:
                raise ValueError("merge decisions require multiple inputs and one output revision")
        elif self.action is DecisionAction.SPLIT:
            source_count = len(self.candidate_ids) + len(inputs)
            if source_count != 1 or len(outputs) < 2:
                raise ValueError("split decisions require one input and multiple output revisions")
        return self


class AnalysisRunDraft(StrictModel):
    run_id: str
    task_id: str
    task_revision: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    data_tier: DataTier
    input_fingerprint: str
    metric_engine_version: str
    redactor_version: str
    schema_version: int = Field(ge=1)
    started_at: datetime

    _validate_ids = field_validator("run_id", "task_id", "input_fingerprint")(
        _pseudonym
    )
    _validate_pack = field_validator("metric_pack_key")(_safe_code)
    _validate_versions = field_validator("metric_engine_version", "redactor_version")(
        _safe_code
    )
    _validate_started_at = field_validator("started_at")(_utc)


class AnalysisResultRecord(StrictModel):
    observation: MetricObservation
    value_state: MetricValueState
    calculator_version: str
    evidence_event_ids: tuple[str, ...] = ()
    model_id: str | None = None
    model_revision: str | None = None
    tokenizer_id: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None
    error_code: str | None = None
    computed_at: datetime

    _validate_calculator = field_validator("calculator_version")(_safe_code)
    _validate_provenance = field_validator(
        "model_id", "model_revision", "tokenizer_id", "prompt_version", "rubric_version"
    )(_safe_code)
    _validate_error = field_validator("error_code")(_safe_label)
    _validate_computed_at = field_validator("computed_at")(_utc)
    _validate_evidence = field_validator("evidence_event_ids")(
        lambda values: _unique(
            tuple(_pseudonym(value) for value in values), "evidence_event_ids"
        )
    )

    @model_validator(mode="after")
    def validate_value_state(self) -> AnalysisResultRecord:
        has_value = (
            self.observation.numeric_value is not None
            or self.observation.text_value is not None
        )
        if self.value_state is MetricValueState.KNOWN:
            if not has_value or self.error_code is not None:
                raise ValueError("known results require a value and no error code")
        elif has_value:
            raise ValueError("non-known results cannot contain a metric value")
        elif self.value_state is MetricValueState.EXECUTION_ERROR:
            if self.error_code is None:
                raise ValueError("execution errors require a safe error code")
        elif self.error_code is not None:
            raise ValueError("only execution errors may contain an error code")
        return self


class AnalysisRunRecord(StrictModel):
    draft: AnalysisRunDraft
    status: AnalysisRunStatus
    finished_at: datetime | None = None
    failure_code: str | None = None

    _validate_finished_at = field_validator("finished_at")(_utc)
    _validate_failure_code = field_validator("failure_code")(_safe_label)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> AnalysisRunRecord:
        if self.status is AnalysisRunStatus.RUNNING:
            if self.finished_at is not None or self.failure_code is not None:
                raise ValueError("running analysis cannot have terminal fields")
        elif self.status is AnalysisRunStatus.COMPLETED:
            if self.finished_at is None or self.failure_code is not None:
                raise ValueError("completed analysis requires only a finish timestamp")
        elif self.finished_at is None or self.failure_code is None:
            raise ValueError("failed analysis requires a finish timestamp and failure code")
        return self


class SessionAnalysisEvidenceRecord(StrictModel):
    """Pseudonymous evidence identity only; never a message excerpt or path."""

    message_id: str
    origin: SessionEvidenceOrigin

    _validate_message_id = field_validator("message_id")(_pseudonym)


class SessionAnalysisSignalRecord(StrictModel):
    """Closed score-receipt item; never text or an evidence identifier."""

    code: str
    status: SessionMetricSignalStatus
    count: int | None = Field(default=None, ge=0, le=10_000_000)

    _validate_code = field_validator("code")(_safe_label)

    @model_validator(mode="after")
    def validate_signal(self) -> SessionAnalysisSignalRecord:
        if self.status is SessionMetricSignalStatus.DETECTED and self.count != 1:
            raise ValueError("detected binary signals require count one")
        if self.status is SessionMetricSignalStatus.MISSING and self.count != 0:
            raise ValueError("missing binary signals require count zero")
        if self.status is SessionMetricSignalStatus.COUNTED and self.count is None:
            raise ValueError("counted signals require a non-negative count")
        if self.status is SessionMetricSignalStatus.UNKNOWN and self.count is not None:
            raise ValueError("unknown signals cannot claim a count")
        return self


class SessionAnalysisRunDraft(StrictModel):
    """Immutable provenance for one explicitly authorized P1 analysis window.

    ``request_fingerprint`` covers only the reviewed content-free request,
    bounds, pack, plan and policy so idempotency can be checked before a provider
    read. ``input_fingerprint`` identifies the already-redacted, selected
    analysis window. Neither may be a raw-content hash or provider identifier.
    """

    run_id: str
    session_id: str
    request_fingerprint: str
    input_fingerprint: str
    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    metric_scope_state: SessionMetricScopeState = SessionMetricScopeState.EXACT
    selected_metric_keys: tuple[str, ...] = Field(max_length=100)
    data_tier: DataTier
    consent_purpose: str = "text_analysis"
    consent_policy_version: str
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    content_schema_version: str
    metric_engine_version: str
    redactor_version: str
    model_plan_fingerprint: str
    schema_version: int = Field(ge=1)
    local_only: bool = True
    started_at: datetime

    _validate_ids = field_validator(
        "run_id",
        "session_id",
        "request_fingerprint",
        "input_fingerprint",
        "model_plan_fingerprint",
    )(_pseudonym)
    _validate_codes = field_validator(
        "analysis_profile_key",
        "metric_pack_key",
        "consent_policy_version",
        "provider_version",
        "adapter_version",
        "source_schema_version",
        "content_schema_version",
        "metric_engine_version",
        "redactor_version",
    )(_safe_code)
    _validate_started_at = field_validator("started_at")(_utc)

    _validate_selected_metric_keys = field_validator("selected_metric_keys")(
        _selected_metric_keys
    )

    @model_validator(mode="after")
    def validate_privacy_provenance(self) -> SessionAnalysisRunDraft:
        if self.data_tier is not DataTier.REDACTED_CONTENT:
            raise ValueError("session text analysis requires the redacted-content tier")
        if self.consent_purpose != "text_analysis":
            raise ValueError("session analysis requires the text_analysis purpose")
        if not self.local_only:
            raise ValueError("session analysis persistence is local-only")
        if (
            self.metric_scope_state is SessionMetricScopeState.EXACT
        ) != bool(self.selected_metric_keys):
            raise ValueError(
                "exact metric scope requires keys; unknown legacy scope cannot claim keys"
            )
        return self


class SessionAnalysisResultRecord(StrictModel):
    """Content-free persisted projection of one qualitative metric result."""

    observation: MetricObservation
    value_state: MetricValueState
    direction: SessionMetricDirection
    applicability: SessionMetricApplicability
    aggregation_method: SessionMetricAggregation = SessionMetricAggregation.RATIO_OF_SUMS
    metric_schema_version: int = Field(ge=1)
    evidence_data_tier: DataTier
    fraction_numerator: int | None = Field(default=None, ge=0)
    fraction_denominator: int | None = Field(default=None, ge=1)
    evidence: tuple[SessionAnalysisEvidenceRecord, ...] = ()
    signals: tuple[SessionAnalysisSignalRecord, ...] = ()
    explanation_code: str
    error_code: str | None = None
    algorithm_id: str
    algorithm_version: str
    model_id: str | None = None
    model_revision: str | None = None
    model_license: str | None = None
    tokenizer_id: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None
    computed_at: datetime

    _validate_explanation = field_validator("explanation_code")(_safe_label)
    _validate_error = field_validator("error_code")(_safe_label)
    _validate_algorithm = field_validator("algorithm_id", "algorithm_version")(
        _safe_code
    )
    _validate_model_provenance = field_validator(
        "model_id",
        "model_revision",
        "model_license",
        "tokenizer_id",
        "prompt_version",
        "rubric_version",
    )(_safe_code)
    _validate_computed_at = field_validator("computed_at")(_utc)

    @model_validator(mode="after")
    def validate_qualitative_result(self) -> SessionAnalysisResultRecord:
        observation = self.observation
        if observation.text_value is not None:
            raise ValueError("session analysis results cannot persist textual values")
        if self.evidence_data_tier is not DataTier.REDACTED_CONTENT:
            raise ValueError("qualitative evidence must originate at redacted-content tier")
        if self.aggregation_method is not SessionMetricAggregation.RATIO_OF_SUMS:
            raise ValueError("qualitative fractions require ratio-of-sums aggregation")

        has_fraction = (
            self.fraction_numerator is not None
            and self.fraction_denominator is not None
        )
        if (self.fraction_numerator is None) != (self.fraction_denominator is None):
            raise ValueError("fraction numerator and denominator must be supplied together")
        if has_fraction and self.fraction_numerator > self.fraction_denominator:
            raise ValueError("fraction numerator cannot exceed its denominator")

        has_value = observation.numeric_value is not None
        if self.value_state is MetricValueState.KNOWN:
            if (
                not has_value
                or not has_fraction
                or self.error_code is not None
                or self.applicability is not SessionMetricApplicability.APPLICABLE
            ):
                raise ValueError(
                    "known session results require an applicable fraction and no error"
                )
            expected = self.fraction_numerator / self.fraction_denominator
            if abs(observation.numeric_value - expected) > 1e-9:
                raise ValueError("numeric value must equal the persisted fraction")
        else:
            if has_value or has_fraction:
                raise ValueError("non-known session results cannot contain a value")
            if observation.confidence is not None:
                raise ValueError("non-known session results cannot claim confidence")
            if self.value_state is MetricValueState.EXECUTION_ERROR:
                if self.error_code is None:
                    raise ValueError("execution errors require a safe error code")
            elif self.error_code is not None:
                raise ValueError("only execution errors may contain an error code")

        if (
            self.value_state is MetricValueState.NOT_APPLICABLE
        ) != (
            self.applicability is SessionMetricApplicability.NOT_APPLICABLE
        ):
            raise ValueError("not-applicable state and applicability must agree")
        evidence_ids = tuple(item.message_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("session analysis evidence cannot contain duplicates")
        signal_codes = tuple(item.code for item in self.signals)
        if len(signal_codes) > 32:
            raise ValueError("session analysis signal receipt exceeds its fixed bound")
        if len(set(signal_codes)) != len(signal_codes):
            raise ValueError("session analysis signals cannot contain duplicate codes")
        if self.value_state is MetricValueState.EXECUTION_ERROR and self.signals:
            raise ValueError("execution errors cannot claim extracted signals")

        pinned_model_fields = (
            self.model_revision,
            self.model_license,
            self.tokenizer_id,
        )
        if self.model_id is None:
            if any(value is not None for value in pinned_model_fields):
                raise ValueError("model provenance must be entirely absent or pinned")
            if self.prompt_version is not None:
                raise ValueError("prompt provenance requires a model identifier")
        elif any(value is None for value in pinned_model_fields):
            raise ValueError("models require pinned revision, license and tokenizer")
        return self


class SessionAnalysisRunRecord(StrictModel):
    draft: SessionAnalysisRunDraft
    status: AnalysisRunStatus
    finished_at: datetime | None = None
    failure_code: str | None = None

    _validate_finished_at = field_validator("finished_at")(_utc)
    _validate_failure_code = field_validator("failure_code")(_safe_label)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> SessionAnalysisRunRecord:
        if self.status is AnalysisRunStatus.RUNNING:
            if self.finished_at is not None or self.failure_code is not None:
                raise ValueError("running session analysis cannot have terminal fields")
        elif self.status is AnalysisRunStatus.COMPLETED:
            if self.finished_at is None or self.failure_code is not None:
                raise ValueError("completed session analysis requires only a finish timestamp")
        elif self.finished_at is None or self.failure_code is None:
            raise ValueError("failed session analysis requires a finish timestamp and code")
        return self


class SessionAnalysisAggregationResultRecord(StrictModel):
    """Evidence-free metric projection used only for batch aggregation reads.

    The persisted result owns evidence and explanatory codes.  Cross-session
    aggregation needs neither, so this projection has no field capable of
    carrying an evidence identifier, excerpt, path, label, or timestamp.
    """

    observation: MetricObservation
    value_state: MetricValueState
    direction: SessionMetricDirection
    applicability: SessionMetricApplicability
    aggregation_method: SessionMetricAggregation
    metric_schema_version: int = Field(ge=1)
    fraction_numerator: int | None = Field(default=None, ge=0)
    fraction_denominator: int | None = Field(default=None, ge=1)
    algorithm_id: str
    algorithm_version: str
    model_id: str | None = None
    model_revision: str | None = None
    model_license: str | None = None
    tokenizer_id: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None

    _validate_algorithm = field_validator("algorithm_id", "algorithm_version")(
        _safe_code
    )
    _validate_model_provenance = field_validator(
        "model_id",
        "model_revision",
        "model_license",
        "tokenizer_id",
        "prompt_version",
        "rubric_version",
    )(_safe_code)

    @model_validator(mode="after")
    def validate_projection(self) -> SessionAnalysisAggregationResultRecord:
        observation = self.observation
        if observation.text_value is not None:
            raise ValueError("aggregation projections cannot contain textual values")
        if self.aggregation_method is not SessionMetricAggregation.RATIO_OF_SUMS:
            raise ValueError("qualitative fractions require ratio-of-sums aggregation")
        has_fraction = (
            self.fraction_numerator is not None
            and self.fraction_denominator is not None
        )
        if (self.fraction_numerator is None) != (self.fraction_denominator is None):
            raise ValueError("fraction numerator and denominator must be supplied together")
        if has_fraction and self.fraction_numerator > self.fraction_denominator:
            raise ValueError("fraction numerator cannot exceed its denominator")
        has_value = observation.numeric_value is not None
        if self.value_state is MetricValueState.KNOWN:
            if (
                not has_value
                or not has_fraction
                or self.applicability is not SessionMetricApplicability.APPLICABLE
            ):
                raise ValueError("known aggregation projections require a fraction")
            expected = self.fraction_numerator / self.fraction_denominator
            if abs(observation.numeric_value - expected) > 1e-9:
                raise ValueError("numeric value must equal the projected fraction")
        elif has_value or has_fraction or observation.confidence is not None:
            raise ValueError("non-known aggregation projections cannot claim a value")
        if (
            self.value_state is MetricValueState.NOT_APPLICABLE
        ) != (
            self.applicability is SessionMetricApplicability.NOT_APPLICABLE
        ):
            raise ValueError("not-applicable state and applicability must agree")
        pinned_model_fields = (
            self.model_revision,
            self.model_license,
            self.tokenizer_id,
        )
        if self.model_id is None:
            if any(value is not None for value in pinned_model_fields):
                raise ValueError("model provenance must be entirely absent or pinned")
            if self.prompt_version is not None:
                raise ValueError("prompt provenance requires a model identifier")
        elif any(value is None for value in pinned_model_fields):
            raise ValueError("models require pinned revision, license and tokenizer")
        return self


class SessionAnalysisAggregationSnapshotRecord(StrictModel):
    """Latest completed run provenance with evidence-free metric projections."""

    session_id: str
    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    metric_scope_state: SessionMetricScopeState
    selected_metric_keys: tuple[str, ...] = Field(max_length=100)
    data_tier: DataTier
    consent_policy_version: str
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    content_schema_version: str
    metric_engine_version: str
    redactor_version: str
    model_plan_fingerprint: str
    persistence_schema_version: int = Field(ge=1)
    local_only: bool = True
    results: tuple[SessionAnalysisAggregationResultRecord, ...] = ()

    _validate_ids = field_validator("session_id", "model_plan_fingerprint")(
        _pseudonym
    )
    _validate_codes = field_validator(
        "analysis_profile_key",
        "metric_pack_key",
        "consent_policy_version",
        "provider_version",
        "adapter_version",
        "source_schema_version",
        "content_schema_version",
        "metric_engine_version",
        "redactor_version",
    )(_safe_code)

    _validate_selected_metric_keys = field_validator("selected_metric_keys")(
        _selected_metric_keys
    )

    @model_validator(mode="after")
    def validate_snapshot(self) -> SessionAnalysisAggregationSnapshotRecord:
        if self.data_tier is not DataTier.REDACTED_CONTENT or not self.local_only:
            raise ValueError("session aggregation snapshots are local P1 records")
        identities = tuple(
            (result.observation.key, result.observation.version)
            for result in self.results
        )
        if len(set(identities)) != len(identities):
            raise ValueError("aggregation snapshot results cannot contain duplicates")
        result_keys = {result.observation.key for result in self.results}
        if self.metric_scope_state is SessionMetricScopeState.EXACT:
            if not self.selected_metric_keys or result_keys != set(
                self.selected_metric_keys
            ):
                raise ValueError(
                    "exact aggregation scope must equal its completed result keys"
                )
        elif self.selected_metric_keys:
            raise ValueError("unknown legacy scope cannot claim selected metric keys")
        return self


class TaskRepository(Protocol):
    def add_candidate(self, candidate: TaskCandidateRecord) -> None: ...

    def get_candidate(self, candidate_id: str) -> TaskCandidateRecord | None: ...

    def list_candidates(
        self,
        *,
        status: CandidateDecisionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CandidateListItem, ...]: ...

    def append_revision(self, revision: TaskRevisionRecord) -> None: ...

    def get_revision(self, task_id: str, revision: int) -> TaskRevisionRecord | None: ...

    def list_task_revisions(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[TaskRevisionRecord, ...]: ...

    def list_current_revisions_for_session(
        self,
        session_id: str,
    ) -> tuple[TaskRevisionRecord, ...]: ...

    def record_decision(self, decision: TaskDecisionRecord) -> None: ...

    def apply_review_decision(
        self,
        decision: TaskDecisionRecord,
        output_revisions: tuple[TaskRevisionRecord, ...],
        *,
        expected_discovery_version: str,
    ) -> bool: ...

    def list_decisions(self, candidate_id: str) -> tuple[TaskDecisionRecord, ...]: ...

    def delete_candidate_for_privacy(self, candidate_id: str) -> bool: ...

    def delete_task_for_privacy(self, task_id: str) -> bool: ...


class AnalysisRunRepository(Protocol):
    def begin(self, draft: AnalysisRunDraft) -> None: ...

    def complete(
        self,
        run_id: str,
        results: tuple[AnalysisResultRecord, ...],
        *,
        finished_at: datetime,
    ) -> None: ...

    def fail(self, run_id: str, *, finished_at: datetime, failure_code: str) -> None: ...

    def get(self, run_id: str) -> AnalysisRunRecord | None: ...

    def list_analysis_runs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[AnalysisRunRecord, ...]: ...

    def get_results(self, run_id: str) -> tuple[AnalysisResultRecord, ...]: ...

    def delete_for_privacy(self, run_id: str) -> bool: ...


class SessionAnalysisRunRepository(Protocol):
    """Append-only store for selected-session qualitative analysis snapshots."""

    def begin(
        self,
        draft: SessionAnalysisRunDraft,
        *,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None: ...

    def complete(
        self,
        run_id: str,
        results: tuple[SessionAnalysisResultRecord, ...],
        *,
        finished_at: datetime,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
        temporal_completion_request: SyntheticTemporalCompletionRequestV1 | None = None,
    ) -> RepositorySealedTemporalBatchV1 | None: ...

    def fail(self, run_id: str, *, finished_at: datetime, failure_code: str) -> None: ...

    def get(self, run_id: str) -> SessionAnalysisRunRecord | None: ...

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[SessionAnalysisRunRecord, ...]: ...

    def get_latest_completed(
        self, session_id: str
    ) -> SessionAnalysisRunRecord | None: ...

    def get_latest_for_profile(
        self,
        session_id: str,
        *,
        analysis_profile_key: str,
        analysis_profile_version: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> SessionAnalysisRunRecord | None: ...

    def get_latest_completed_for_aggregation(
        self,
        session_ids: tuple[str, ...],
        *,
        analysis_profile_key: str,
        analysis_profile_version: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> tuple[SessionAnalysisAggregationSnapshotRecord, ...]: ...

    def get_results(
        self, run_id: str
    ) -> tuple[SessionAnalysisResultRecord, ...]: ...

    def delete_for_privacy(self, run_id: str) -> bool: ...
