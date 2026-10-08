"""Hexagonal Codex provider adapter with explicit metadata/history modes."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from enum import StrEnum

from ....adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from ....domain import (
    DataTier,
    Provider,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    SourceSessionSnapshot,
)
from .client import CodexAppServerClient, CodexServerInfo
from .contracts import ADAPTER_VERSION, SOURCE_SCHEMA_VERSION, UNKNOWN_VERSION, RawThread
from .errors import (
    CodexAdapterError,
    CodexCompatibilityError,
    CodexLifecycleError,
    CodexLimitError,
    CodexProtocolViolation,
    CodexScopeError,
    CodexTransportError,
)
from .limits import CodexReadLimits
from .mapping import CodexThreadMapper
from .transports.stdio_jsonl import (
    StdioJsonRpcTransport,
    ThreadReadPolicy,
)


class CodexReadMode(StrEnum):
    METADATA_INDEX = "metadata_index"
    LABEL_ENRICHMENT = "label_enrichment"
    OPERATIONAL_HISTORY = "operational_history"


ClientFactory = Callable[[], CodexAppServerClient]


class CodexAppServerAdapter(ProviderAdapter):
    """Read-only adapter; construction performs no source or subprocess access."""

    provider = Provider.CODEX

    def __init__(
        self,
        *,
        mode: CodexReadMode = CodexReadMode.METADATA_INDEX,
        limits: CodexReadLimits | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._mode = mode
        self._limits = limits or CodexReadLimits()
        self._client_factory = client_factory or self._default_client_factory
        self._client: CodexAppServerClient | None = None
        self._server_info: CodexServerInfo | None = None
        self._mapper: CodexThreadMapper | None = None
        self._health = AdapterHealth.UNAVAILABLE
        self._closed = False
        self._page_count = 0
        self._session_count = 0
        self._cursor_counter = 0
        self._cursor_values: dict[str, str] = {}
        self._seen_raw_cursors: set[str] = set()
        self._raw_threads: dict[str, RawThread] = {}
        self._listed_sessions: dict[str, SourceSession] = {}

    @property
    def required_consent_tier(self) -> DataTier:
        return DataTier.REDACTED_CONTENT

    @property
    def requires_explicit_selection(self) -> bool:
        return self._mode is not CodexReadMode.METADATA_INDEX

    @property
    def mode(self) -> CodexReadMode:
        return self._mode

    def _default_client_factory(self) -> CodexAppServerClient:
        read_policy = {
            CodexReadMode.METADATA_INDEX: ThreadReadPolicy.NONE,
            CodexReadMode.LABEL_ENRICHMENT: ThreadReadPolicy.SUMMARY_ONLY,
            CodexReadMode.OPERATIONAL_HISTORY: ThreadReadPolicy.OPERATIONAL,
        }[self._mode]
        return CodexAppServerClient(
            StdioJsonRpcTransport(
                limits=self._limits, thread_read_policy=read_policy
            ),
            limits=self._limits,
        )

    def probe(self) -> AdapterProbe:
        if self._closed:
            raise CodexLifecycleError("Codex adapter is closed")
        if self._server_info is not None:
            return self._probe_result(self._health)
        client = self._client_factory()
        self._client = client
        try:
            self._server_info = client.initialize()
            self._mapper = CodexThreadMapper(
                provider_version=self._server_info.provider_version,
                limits=self._limits,
            )
            self._health = AdapterHealth.READY
        except (CodexCompatibilityError, CodexProtocolViolation):
            self._health = AdapterHealth.INCOMPATIBLE
            client.close()
            self._client = None
        except CodexTransportError:
            self._health = AdapterHealth.UNAVAILABLE
            client.close()
            self._client = None
        except CodexAdapterError:
            self._health = AdapterHealth.INCOMPATIBLE
            client.close()
            self._client = None
        return self._probe_result(self._health)

    def _probe_result(self, health: AdapterHealth) -> AdapterProbe:
        return AdapterProbe(
            provider=self.provider,
            provider_version=(
                self._server_info.provider_version
                if self._server_info is not None
                else UNKNOWN_VERSION
            ),
            adapter_version=ADAPTER_VERSION,
            source_schema_version=SOURCE_SCHEMA_VERSION,
            supports_metadata=True,
            supports_content=self._mode is CodexReadMode.OPERATIONAL_HISTORY,
            supports_watch=False,
            health=health,
        )

    def list_sessions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> SourceSessionPage:
        client, mapper = self._ready_components()
        if limit < 1 or limit > self._limits.max_page_size:
            raise ValueError("limit must be within the configured page bound")
        new_snapshot = cursor is None
        if new_snapshot:
            self._reset_snapshot()
            raw_cursor = None
        else:
            try:
                raw_cursor = self._cursor_values.pop(cursor)
            except KeyError:
                raise CodexScopeError("pagination cursor is not part of this snapshot") from None
        if self._page_count >= self._limits.max_pages:
            raise CodexLimitError("session listing exceeded the page bound")
        remaining = self._limits.max_sessions - self._session_count
        if remaining < 1:
            raise CodexLimitError("session listing exceeded the session bound")
        requested_limit = min(limit, remaining)
        raw_page = client.list_threads(
            cursor=raw_cursor,
            limit=requested_limit,
            new_snapshot=new_snapshot,
        )
        if len(raw_page.threads) > requested_limit:
            raise CodexLimitError("provider returned more sessions than requested")
        sessions: list[SourceSession] = []
        for raw_thread in raw_page.threads:
            raw_id = raw_thread.thread_id.get_secret_value()
            if raw_id in self._raw_threads:
                raise CodexProtocolViolation("provider repeated a session in one snapshot")
            session = mapper.session(raw_thread, events_complete=False)
            self._raw_threads[raw_id] = raw_thread
            self._listed_sessions[raw_id] = session
            sessions.append(session)
        self._page_count += 1
        self._session_count += len(sessions)
        next_cursor = self._map_next_cursor(raw_page.next_cursor)
        return SourceSessionPage(sessions=tuple(sessions), next_cursor=next_cursor)

    def _map_next_cursor(self, raw_cursor: object) -> str | None:
        if raw_cursor is None:
            return None
        raw_value = raw_cursor.get_secret_value()
        if raw_value in self._seen_raw_cursors:
            raise CodexProtocolViolation("provider repeated a pagination cursor")
        self._seen_raw_cursors.add(raw_value)
        self._cursor_counter += 1
        token = f"p{self._cursor_counter}"
        self._cursor_values[token] = raw_value
        return token

    def _reset_snapshot(self) -> None:
        self._page_count = 0
        self._session_count = 0
        self._cursor_counter = 0
        self._cursor_values.clear()
        self._seen_raw_cursors.clear()
        self._raw_threads.clear()
        self._listed_sessions.clear()

    def read_session(self, session: SourceSession) -> SourceSessionSnapshot:
        client, mapper = self._ready_components()
        raw_id = session.source_session_id.get_secret_value()
        listed_session = self._listed_sessions.get(raw_id)
        if listed_session is None or session != listed_session:
            raise CodexScopeError("session is not part of the current listed snapshot")
        if self._mode is CodexReadMode.METADATA_INDEX:
            return SourceSessionSnapshot(session=session, events=())
        if self._mode is CodexReadMode.LABEL_ENRICHMENT:
            summary = client.read_thread_summary(raw_id)
            project_label, session_label = mapper.display_labels(summary)
            enriched = listed_session.model_copy(
                update={
                    "source_project_display_name": project_label,
                    "source_session_display_name": session_label,
                }
            )
            return SourceSessionSnapshot(session=enriched, events=())

        detailed = client.read_thread(raw_id)
        listed_raw = self._raw_threads[raw_id]
        detailed = detailed.model_copy(
            update={
                "cwd": listed_raw.cwd,
                "name": listed_raw.name,
                "created_at": listed_raw.created_at,
            }
        )
        return mapper.snapshot(detailed)

    def read_display_labels(self, session: SourceSession) -> SourceSession:
        """Return summary-only labels; other adapter modes fail closed."""

        if self._mode is not CodexReadMode.LABEL_ENRICHMENT:
            raise CodexScopeError("display-label reads require label mode")
        return self.read_session(session).session

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        yield from self.read_session(session).events

    def _ready_components(self) -> tuple[CodexAppServerClient, CodexThreadMapper]:
        if self._closed:
            raise CodexLifecycleError("Codex adapter is closed")
        if (
            self._health is not AdapterHealth.READY
            or self._client is None
            or self._mapper is None
        ):
            raise CodexLifecycleError("a successful probe is required before source access")
        return self._client, self._mapper

    def health(self) -> AdapterHealth:
        return self._health

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client = self._client
        self._client = None
        self._server_info = None
        self._mapper = None
        self._health = AdapterHealth.UNAVAILABLE
        self._reset_snapshot()
        if client is not None:
            client.close()
