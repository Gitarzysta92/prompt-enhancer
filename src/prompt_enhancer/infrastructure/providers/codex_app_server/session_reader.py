"""On-demand Codex session reader over the documented app-server text read.

Owner-authorized (ADR 0011).  Reuses the same client, thread selection, and
scope rules as the P1 text-analysis source: list threads in the current
snapshot, re-derive each thread's catalog pseudonym, and read only the one that
matches.  Unlike the analysis source it does not redact - the owner asked to
read their own conversation - and, like it, persists nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ....application.analysis.session_reader import (
    MAX_READER_TURNS,
    MAX_TRANSCRIPT_CHARACTERS,
    MAX_TURN_CHARACTERS,
    ReaderRole,
    ReaderSource,
    ReaderTurn,
    SessionReadError,
    SessionReadFailure,
    SessionTranscript,
    clip,
)
from ....domain import Provider
from .content_contracts import CodexTextItemKind, RawCodexTextThread
from .content_source import CodexTextAnalysisSource
from .errors import (
    CodexAdapterError,
    CodexCompatibilityError,
    CodexLimitError,
    CodexScopeError,
    CodexTransportError,
    CodexTransportTimeout,
)


_ROLES = {
    CodexTextItemKind.USER_MESSAGE: ReaderRole.USER,
    CodexTextItemKind.AGENT_MESSAGE: ReaderRole.ASSISTANT,
    CodexTextItemKind.PLAN: ReaderRole.PLAN,
}


def transcript_from_thread(session_id: str, thread: RawCodexTextThread, provider_version: str | None) -> SessionTranscript:
    turns: list[ReaderTurn] = []
    total = 0
    characters = 0
    truncated = thread.older_history_truncated
    # Fragments are already ordered by turn, item, content, and segment; merge
    # consecutive segments of the same item into one turn.
    current_key: tuple[str, str, int] | None = None
    buffer: list[str] = []
    current_kind: CodexTextItemKind | None = None

    def flush() -> None:
        nonlocal total, characters, truncated
        if current_kind is None or not buffer:
            return
        text, clipped = clip("".join(buffer), MAX_TURN_CHARACTERS)
        total += 1
        if len(turns) >= MAX_READER_TURNS or characters + len(text) > MAX_TRANSCRIPT_CHARACTERS:
            truncated = True
            return
        turns.append(ReaderTurn(role=_ROLES[current_kind], text=text, truncated=clipped))
        characters += len(text)

    for fragment in thread.fragments:
        key = (
            fragment.turn_id.get_secret_value(),
            fragment.item_id.get_secret_value(),
            fragment.content_index,
        )
        if key != current_key:
            flush()
            current_key = key
            current_kind = fragment.kind
            buffer = []
        buffer.append(fragment.text.get_secret_value())
    flush()
    return SessionTranscript(
        provider=Provider.CODEX,
        session_id=session_id,
        source=ReaderSource.CODEX_APP_SERVER,
        provider_version=provider_version,
        turns=tuple(turns),
        turn_count_total=total,
        truncated=truncated,
        read_at=datetime.now(UTC),
    )


class CodexSessionReader:
    provider = Provider.CODEX

    def __init__(self, source: CodexTextAnalysisSource) -> None:
        self._source = source

    def read(self, catalog_session_id: str) -> SessionTranscript:
        try:
            thread, server_info = self._source.read_raw_thread(catalog_session_id)
        except CodexTransportTimeout:
            raise SessionReadError(SessionReadFailure.SOURCE_UNAVAILABLE) from None
        except CodexScopeError:
            raise SessionReadError(SessionReadFailure.SESSION_NOT_FOUND) from None
        except CodexLimitError:
            raise SessionReadError(SessionReadFailure.LIMIT_EXCEEDED) from None
        except CodexCompatibilityError:
            raise SessionReadError(SessionReadFailure.FORMAT_UNRECOGNIZED) from None
        except (CodexTransportError, CodexAdapterError):
            raise SessionReadError(SessionReadFailure.SOURCE_UNAVAILABLE) from None
        return transcript_from_thread(
            catalog_session_id, thread, getattr(server_info, "provider_version", None)
        )


__all__ = ("CodexSessionReader", "transcript_from_thread")
