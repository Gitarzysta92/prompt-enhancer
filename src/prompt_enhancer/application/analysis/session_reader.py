"""Owner-authorized, on-demand session reading for the local dashboard.

Recorded in ADR 0011.  The person who owns the sessions asked to read them
inside the app so that, while rating a session for calibration, they can see
what actually happened rather than judge a fictional stand-in.

Boundaries that hold regardless of provider:

* the reader is **off** unless the owner sets ``PROMPT_ENHANCER_SESSION_READER``
  to ``enabled``; the public capability ``raw_transcripts`` reports the truth;
* a read happens only for a session already in the local catalog, only for a
  provider whose local-history consent is active, only when the dashboard asks
  for that one session, and the result is **never persisted** - it is built,
  sent over loopback, and dropped;
* every turn is bounded, the whole transcript is bounded, and the response
  says when it was truncated;
* the coding agent that maintains this repository never reads a session; the
  application does, for its owner, on the owner's machine.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, field_validator

from ...domain import PSEUDONYM_PATTERN, DataTier, Provider, StrictModel


READER_ENV = "PROMPT_ENHANCER_SESSION_READER"
READER_CONTRACT_VERSION = "session-reader.v1"
MAX_READER_TURNS = 2_000
MAX_TURN_CHARACTERS = 20_000
MAX_TOOL_CHARACTERS = 2_000
MAX_TRANSCRIPT_CHARACTERS = 4_000_000


class ReaderRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"


class ReaderSource(StrEnum):
    CODEX_APP_SERVER = "codex_app_server"
    CLAUDE_TRANSCRIPT_FILE = "claude_transcript_file"


class SessionReadFailure(StrEnum):
    READER_DISABLED = "reader_disabled"
    CONSENT_REQUIRED = "consent_required"
    SESSION_UNKNOWN = "session_unknown"
    PROVIDER_UNSUPPORTED = "provider_unsupported"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SESSION_NOT_FOUND = "session_not_found"
    FORMAT_UNRECOGNIZED = "format_unrecognized"
    LIMIT_EXCEEDED = "limit_exceeded"


class SessionReadError(RuntimeError):
    def __init__(self, reason: SessionReadFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


class ReaderTurn(StrictModel):
    role: ReaderRole
    text: str = Field(max_length=MAX_TURN_CHARACTERS)
    at: datetime | None = None
    tool_name: str | None = Field(default=None, max_length=120)
    truncated: bool = False


class SessionTranscript(StrictModel):
    contract_version: Literal[READER_CONTRACT_VERSION] = READER_CONTRACT_VERSION
    provider: Provider
    session_id: str
    source: ReaderSource
    provider_version: str | None = None
    turns: tuple[ReaderTurn, ...] = Field(max_length=MAX_READER_TURNS)
    turn_count_total: int = Field(ge=0)
    truncated: bool = False
    persisted: Literal[False] = False
    local_only: Literal[True] = True
    read_at: datetime

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("session identifier must be a local pseudonym")
        return value


class ProviderSessionReader(Protocol):
    """One provider's on-demand reader; returns a bounded transcript or raises."""

    provider: Provider

    def read(self, catalog_session_id: str) -> SessionTranscript: ...


class CatalogLookup(Protocol):
    def get_session(self, session_id: str): ...

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool: ...


class SessionReaderService:
    """Composition-root wiring: enabled flag, catalog, consent, per-provider readers."""

    def __init__(
        self,
        catalog: CatalogLookup,
        readers: dict[Provider, ProviderSessionReader],
        *,
        enabled: bool,
    ) -> None:
        self._catalog = catalog
        self._readers = dict(readers)
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def read(self, session_id: str) -> SessionTranscript:
        if not self._enabled:
            raise SessionReadError(SessionReadFailure.READER_DISABLED)
        if PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise SessionReadError(SessionReadFailure.SESSION_UNKNOWN)
        session = self._catalog.get_session(session_id)
        if session is None:
            raise SessionReadError(SessionReadFailure.SESSION_UNKNOWN)
        provider = session.provider
        reader = self._readers.get(provider)
        if reader is None:
            raise SessionReadError(SessionReadFailure.PROVIDER_UNSUPPORTED)
        if not self._catalog.has_active_consent(provider, DataTier.REDACTED_CONTENT):
            raise SessionReadError(SessionReadFailure.CONSENT_REQUIRED)
        return reader.read(session_id)


def clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(), True


__all__ = (
    "MAX_READER_TURNS",
    "MAX_TOOL_CHARACTERS",
    "MAX_TRANSCRIPT_CHARACTERS",
    "MAX_TURN_CHARACTERS",
    "READER_CONTRACT_VERSION",
    "READER_ENV",
    "ProviderSessionReader",
    "ReaderRole",
    "ReaderSource",
    "ReaderTurn",
    "SessionReadError",
    "SessionReadFailure",
    "SessionReaderService",
    "SessionTranscript",
    "clip",
)
