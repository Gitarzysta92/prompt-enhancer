"""Strict data contracts for content-free Phase 1 ingestion.

Source models may briefly contain provider identifiers in memory. Their fields use
``SecretStr`` so normal logging and exception rendering cannot reveal those
identifiers. Only the corresponding ``Safe*`` models may cross the persistence
boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from .display_labels import (
    PROJECT_DISPLAY_NAME_MAX_LENGTH,
    SESSION_DISPLAY_NAME_MAX_LENGTH,
    require_private_display_name,
)



PSEUDONYM_PATTERN = re.compile(r"^[a-f0-9]{64}$")
SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$")
SAFE_METRIC_TEXT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class Provider(StrEnum):
    CODEX = "codex"
    CLAUDE_CODE = "claude_code"
    SYNTHETIC = "synthetic"


class DataTier(StrEnum):
    METADATA = "metadata"
    REDACTED_CONTENT = "redacted_content"
    RAW_VAULT = "raw_vault"
    REMOTE_REDACTED = "remote_redacted"


class CostMode(StrEnum):
    OFFLINE_ONLY = "offline_only"


class SessionState(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class EventKind(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    PLAN = "plan"
    DECISION = "decision"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    VERIFICATION = "verification"
    APPROVAL = "approval"
    PERMISSION_CHANGE = "permission_change"
    TASK_STATE = "task_state"
    USAGE = "usage"
    COMPACTION = "compaction"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    FORK = "fork"
    ARTIFACT = "artifact"
    USER_FEEDBACK = "user_feedback"
    UNKNOWN = "unknown"


class ToolCategory(StrEnum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    COMMAND = "command"
    SEARCH = "search"
    TEST = "test"
    BUILD = "build"
    VERSION_CONTROL = "version_control"
    NETWORK = "network"
    MCP = "mcp"
    SUBAGENT = "subagent"
    OTHER = "other"
    UNKNOWN = "unknown"


class EventTimeBasis(StrEnum):
    """How precisely an event's ordering timestamp was observed."""

    PROVIDER_REPORTED = "provider_reported"
    RECEIVER_OBSERVED = "receiver_observed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    SESSION_STARTED = "session_started"


class UsageCounterKind(StrEnum):
    """Whether a usage observation can be safely added to adjacent records."""

    DELTA = "delta"
    CUMULATIVE = "cumulative"
    UNKNOWN = "unknown"


class UsageScope(StrEnum):
    """Provider scope represented by one usage observation."""

    REQUEST = "request"
    TURN = "turn"
    THREAD = "thread"
    UNKNOWN = "unknown"


class MetricSource(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    DETERMINISTIC = "deterministic"
    HUMAN_LABEL = "human_label"
    ESTIMATED = "estimated"


class SignalDirection(StrEnum):
    """Whether safe discovery evidence supports joining or separating items."""

    SUPPORTS_LINK = "supports_link"
    SUPPORTS_BOUNDARY = "supports_boundary"
    UNKNOWN = "unknown"


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


def _ensure_safe_version(value: str | None) -> str | None:
    if value is None:
        return None
    if not SAFE_VERSION_PATTERN.fullmatch(value):
        raise ValueError("version identifiers may contain only safe identifier characters")
    return value


def _ensure_pseudonym(value: str) -> str:
    if not PSEUDONYM_PATTERN.fullmatch(value):
        raise ValueError("persistent identifiers must be 64-character HMAC pseudonyms")
    return value


def _ensure_safe_metric_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not SAFE_METRIC_TEXT_PATTERN.fullmatch(value):
        raise ValueError("text metrics must be short, content-free labels")
    return value


class UsageRecord(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    model_id: str | None = None
    provider_reported: bool = True
    counter_kind: UsageCounterKind = UsageCounterKind.UNKNOWN
    scope: UsageScope = UsageScope.UNKNOWN

    _validate_model_id = field_validator("model_id")(_ensure_safe_version)


class SourceEvent(StrictModel):
    """Ephemeral provider event. Never persist this model directly."""

    source_event_id: SecretStr
    kind: EventKind
    sequence: int = Field(ge=0)
    occurred_at: datetime
    time_basis: EventTimeBasis = EventTimeBasis.PROVIDER_REPORTED
    duration_ms: int | None = Field(default=None, ge=0)
    success: bool | None = None
    tool_category: ToolCategory | None = None
    usage: UsageRecord | None = None

    _validate_occurred_at = field_validator("occurred_at")(_ensure_aware_utc)


class SourceSession(StrictModel):
    """Ephemeral provider session metadata. Never persist directly."""

    provider: Provider
    source_installation_id: SecretStr
    source_project_id: SecretStr
    source_session_id: SecretStr
    provider_version: str
    adapter_version: str
    source_schema_version: str
    started_at: datetime
    source_activity_at: datetime | None = None
    ended_at: datetime | None = None
    terminal_state: SessionState = SessionState.UNKNOWN
    events_complete: bool = False
    source_project_display_name: SecretStr | None = Field(
        default=None, repr=False
    )
    source_session_display_name: SecretStr | None = Field(
        default=None, repr=False
    )

    _validate_versions = field_validator(
        "provider_version", "adapter_version", "source_schema_version"
    )(_ensure_safe_version)
    _validate_timestamps = field_validator(
        "started_at", "source_activity_at", "ended_at"
    )(_ensure_aware_utc)

    @model_validator(mode="after")
    def ended_after_start(self) -> SourceSession:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        return self


class SourceSessionPage(StrictModel):
    sessions: tuple[SourceSession, ...]
    next_cursor: str | None = None

    _validate_cursor = field_validator("next_cursor")(_ensure_safe_version)


class SourceSessionSnapshot(StrictModel):
    """One provider session enriched by a read-only detail request."""

    session: SourceSession
    events: tuple[SourceEvent, ...]


class SafeSession(StrictModel):
    provider: Provider
    installation_id: str
    project_id: str
    session_id: str
    provider_version: str
    adapter_version: str
    source_schema_version: str
    started_at: datetime
    provider_activity_revision: str | None = None
    ended_at: datetime | None = None
    terminal_state: SessionState
    events_complete: bool
    project_display_name: str | None = Field(default=None, repr=False)
    session_display_name: str | None = Field(default=None, repr=False)

    @field_validator("project_display_name")
    @classmethod
    def validate_project_display_name(cls, value: str | None) -> str | None:
        return require_private_display_name(
            value, max_length=PROJECT_DISPLAY_NAME_MAX_LENGTH
        )

    @field_validator("session_display_name")
    @classmethod
    def validate_session_display_name(cls, value: str | None) -> str | None:
        return require_private_display_name(
            value, max_length=SESSION_DISPLAY_NAME_MAX_LENGTH
        )

    _validate_pseudonyms = field_validator(
        "installation_id", "project_id", "session_id"
    )(_ensure_pseudonym)

    @field_validator("provider_activity_revision")
    @classmethod
    def validate_optional_activity_revision(cls, value: str | None) -> str | None:
        return None if value is None else _ensure_pseudonym(value)
    _validate_versions = field_validator(
        "provider_version", "adapter_version", "source_schema_version"
    )(_ensure_safe_version)
    _validate_timestamps = field_validator("started_at", "ended_at")(_ensure_aware_utc)

    @model_validator(mode="after")
    def ended_after_start(self) -> SafeSession:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        return self


class SafeEvent(StrictModel):
    session_id: str
    event_id: str
    kind: EventKind
    sequence: int = Field(ge=0)
    occurred_at: datetime
    time_basis: EventTimeBasis = EventTimeBasis.PROVIDER_REPORTED
    duration_ms: int | None = Field(default=None, ge=0)
    success: bool | None = None
    tool_category: ToolCategory | None = None
    usage: UsageRecord | None = None

    _validate_pseudonyms = field_validator("session_id", "event_id")(_ensure_pseudonym)
    _validate_occurred_at = field_validator("occurred_at")(_ensure_aware_utc)


class MetricObservation(StrictModel):
    key: str
    version: int = Field(ge=1)
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    text_value: str | None = None
    unit: str
    source: MetricSource
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)

    _validate_key = field_validator("key", "unit")(_ensure_safe_version)
    _validate_text_value = field_validator("text_value")(_ensure_safe_metric_text)

    @model_validator(mode="after")
    def exactly_one_value_or_unknown(self) -> MetricObservation:
        if self.numeric_value is not None and self.text_value is not None:
            raise ValueError("metric observations cannot have two values")
        if self.observed_count > self.eligible_count:
            raise ValueError("observed_count cannot exceed eligible_count")
        expected = 0.0 if self.eligible_count == 0 else self.observed_count / self.eligible_count
        if abs(self.coverage - expected) > 1e-9:
            raise ValueError("coverage must equal observed_count / eligible_count")
        return self
