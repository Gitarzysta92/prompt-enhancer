"""Narrow, allowlisted client facade for read-only App Server methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .contracts import (
    RawThread,
    RawThreadLabelSummary,
    RawThreadPage,
    SOURCE_SCHEMA_VERSION,
    parse_provider_version,
    parse_thread_page,
    parse_thread_label_summary,
    parse_thread_read,
)
from .content_contracts import (
    CodexTextContentLimits,
    RawCodexTextThread,
    parse_text_thread_read,
)
from .errors import CodexLifecycleError, CodexScopeError
from .limits import CodexReadLimits
from .transports.protocol import InternalJsonRpcTransport


RPC_METHOD_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"initialize", "initialized", "thread/list", "thread/read"}
)


@dataclass(frozen=True, slots=True)
class CodexServerInfo:
    provider_version: str
    source_schema_version: str = SOURCE_SCHEMA_VERSION


class CodexAppServerClient:
    """Only the documented initialization, list, and read calls are reachable."""

    RPC_METHOD_ALLOWLIST = RPC_METHOD_ALLOWLIST

    def __init__(
        self,
        transport: InternalJsonRpcTransport,
        *,
        limits: CodexReadLimits | None = None,
        text_limits: CodexTextContentLimits | None = None,
    ) -> None:
        self._transport = transport
        self._limits = limits or CodexReadLimits()
        self._text_limits = text_limits or CodexTextContentLimits()
        self._initialized = False
        self._listed_thread_ids: set[str] = set()
        self._summary_read_thread_ids: set[str] = set()

    def initialize(self) -> CodexServerInfo:
        if self._initialized:
            raise CodexLifecycleError("Codex App Server client is already initialized")
        result = self._transport._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "prompt-enhancer",
                    "title": "Prompt Enhancer",
                    "version": "0.1.0",
                },
                "capabilities": {},
            },
        )
        self._transport._notify("initialized", {})
        self._initialized = True
        return CodexServerInfo(provider_version=parse_provider_version(result))

    def list_threads(
        self,
        *,
        cursor: str | None,
        limit: int,
        new_snapshot: bool,
    ) -> RawThreadPage:
        self._require_initialized()
        if limit < 1 or limit > self._limits.max_page_size:
            raise ValueError("limit must be within the configured page bound")
        if new_snapshot:
            self._listed_thread_ids.clear()
            self._summary_read_thread_ids.clear()
        params: dict[str, object] = {
            "limit": limit,
            "sortKey": "created_at",
            "sourceKinds": ["cli", "vscode", "appServer"],
            "useStateDbOnly": True,
        }
        if cursor is not None:
            params["cursor"] = cursor
        result = self._transport._request("thread/list", params)
        page = parse_thread_page(result, self._limits)
        self._listed_thread_ids.update(
            thread.thread_id.get_secret_value() for thread in page.threads
        )
        return page

    def read_thread(self, thread_id: str) -> RawThread:
        self._require_initialized()
        if thread_id not in self._listed_thread_ids:
            raise CodexScopeError("session was not listed in the current snapshot")
        result = self._transport._request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        parsed = parse_thread_read(result, self._limits)
        if parsed.thread.thread_id.get_secret_value() != thread_id:
            raise CodexScopeError("provider read returned a different session")
        return parsed.thread

    def read_thread_text_analysis(self, thread_id: str) -> RawCodexTextThread:
        """Read one listed thread through the explicit P1 text projection."""

        self._require_initialized()
        if thread_id not in self._listed_thread_ids:
            raise CodexScopeError("session was not listed in the current snapshot")
        result = self._transport._request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        parsed = parse_text_thread_read(result, self._text_limits)
        if parsed.thread_id.get_secret_value() != thread_id:
            raise CodexScopeError("provider text read returned a different session")
        return parsed

    def read_thread_summary(self, thread_id: str) -> RawThreadLabelSummary:
        """Read one listed task's summary metadata without requesting turns."""

        self._require_initialized()
        if thread_id not in self._listed_thread_ids:
            raise CodexScopeError("session was not listed in the current snapshot")
        if thread_id in self._summary_read_thread_ids:
            raise CodexScopeError("session summary was already read in this snapshot")
        if len(self._summary_read_thread_ids) >= self._limits.max_label_reads:
            raise CodexScopeError("session summary read bound was reached")
        self._summary_read_thread_ids.add(thread_id)
        result = self._transport._request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
        )
        parsed = parse_thread_label_summary(result)
        if parsed.thread_id.get_secret_value() != thread_id:
            raise CodexScopeError("provider summary returned a different session")
        return parsed


    def _require_initialized(self) -> None:
        if not self._initialized:
            raise CodexLifecycleError("probe must initialize Codex App Server first")

    def close(self) -> None:
        self._initialized = False
        self._listed_thread_ids.clear()
        self._transport.close()
        self._summary_read_thread_ids.clear()
