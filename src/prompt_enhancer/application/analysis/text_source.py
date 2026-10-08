"""Provider-neutral port for explicit ephemeral text ingress.

The application owns the selector and capability. Provider adapters receive
only a safe pseudonymous session identity and cannot turn standing discovery
consent into a content read.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from ...domain import DataTier, PSEUDONYM_PATTERN, Provider, StrictModel

#: Providers with a reviewed local text surface (Codex app-server window;
#: Claude Code transcript window, ADR 0011).  Every text-analysis entry point
#: that used to say "Codex only" gates on this set instead.
TEXT_ANALYSIS_PROVIDERS: frozenset[Provider] = frozenset({Provider.CODEX, Provider.CLAUDE_CODE})
from .text_contracts import (
    MAX_ANALYSIS_CHARACTERS,
    MAX_ANALYSIS_MESSAGES,
    P1TextAnalysisInput,
    TextAnalysisScopeKind,
    TextTaskProfile,
)


class TextAnalysisPurpose(StrEnum):
    TEXT_ANALYSIS = "text_analysis"


class TextSourceFailureReason(StrEnum):
    """Bounded, provider-neutral reasons for an ephemeral source read failure."""

    SCHEMA_UNSUPPORTED = "source_schema_unsupported"
    NO_ANALYZABLE_TEXT = "no_analyzable_text"
    PROTOCOL_REJECTED = "provider_protocol_rejected"
    SELECTION_SNAPSHOT_MISS = "selection_snapshot_miss"
    SELECTION_LIMIT = "source_selection_limit"
    PROVIDER_RESPONSE_LIMIT = "source_provider_response_limit"
    THREAD_STRUCTURE_LIMIT = "source_thread_structure_limit"
    PREVIEW_WINDOW_LIMIT = "source_preview_window_limit"
    RESOURCE_LIMIT = "source_resource_limit"
    TIMEOUT = "source_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class TextSourceReadError(RuntimeError):
    """A content-free source failure safe to cross the provider boundary."""

    def __init__(self, reason: TextSourceFailureReason) -> None:
        if not isinstance(reason, TextSourceFailureReason):
            raise TypeError("text source failure reason must be a bounded enum value")
        self.reason = reason
        super().__init__(reason.value)


class TextAnalysisSelection(StrictModel):
    """One provider, one pseudonymous session, and one bounded window."""

    purpose: TextAnalysisPurpose = TextAnalysisPurpose.TEXT_ANALYSIS
    provider: Provider
    session_id: str
    # Compatibility default.  New durable full-session callers must explicitly
    # request ``FULL_AVAILABLE_SESSION`` until their persistence schema can bind
    # and publish this scope end to end.
    scope_kind: TextAnalysisScopeKind = TextAnalysisScopeKind.BOUNDED_RECENT
    max_messages: int = Field(default=MAX_ANALYSIS_MESSAGES, ge=1, le=MAX_ANALYSIS_MESSAGES)
    max_characters: int = Field(
        default=MAX_ANALYSIS_CHARACTERS,
        ge=1,
        le=MAX_ANALYSIS_CHARACTERS,
    )

    @field_validator("session_id")
    @classmethod
    def safe_session_id(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("text-analysis selection requires a safe session identifier")
        return value

    @classmethod
    def full_available_session(
        cls,
        *,
        provider: Provider,
        session_id: str,
        max_messages: int = MAX_ANALYSIS_MESSAGES,
        max_characters: int = MAX_ANALYSIS_CHARACTERS,
    ) -> TextAnalysisSelection:
        """Build an explicit full-available-session request.

        Bounds remain mandatory resource ceilings.  Reaching one does not
        silently redefine the requested scope; the provider result must report
        ``incomplete_source``.
        """

        return cls(
            provider=provider,
            session_id=session_id,
            scope_kind=TextAnalysisScopeKind.FULL_AVAILABLE_SESSION,
            max_messages=max_messages,
            max_characters=max_characters,
        )


class TextSourceAccessGrant(StrictModel):
    """Per-run source capability, separate from downstream metric authority."""

    purpose: TextAnalysisPurpose
    provider: Provider
    session_id: str
    data_tier: DataTier
    per_run_confirmation_active: bool
    local_only: bool = True
    content_persistence_allowed: bool = False

    @field_validator("session_id")
    @classmethod
    def safe_session_id(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("text access grant requires a safe session identifier")
        return value

    @model_validator(mode="after")
    def enforce_source_boundary(self) -> TextSourceAccessGrant:
        if self.purpose is not TextAnalysisPurpose.TEXT_ANALYSIS:
            raise ValueError("text access grant purpose is not allowed")
        if self.data_tier is not DataTier.REDACTED_CONTENT:
            raise ValueError("text access requires the redacted-content tier")
        if not self.per_run_confirmation_active:
            raise ValueError("text access requires active per-run confirmation")
        if not self.local_only:
            raise ValueError("text access is local-only")
        if self.content_persistence_allowed:
            raise ValueError("text access cannot authorize content persistence")
        return self


@runtime_checkable
class EphemeralTextAnalysisSource(Protocol):
    """Replaceable source seam for Codex, Claude Code, and synthetic tests."""

    provider: Provider
    purpose: TextAnalysisPurpose
    read_only: bool
    requires_explicit_selection: bool

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput: ...
