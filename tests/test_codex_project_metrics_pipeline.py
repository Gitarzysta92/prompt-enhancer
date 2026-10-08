from __future__ import annotations

import hashlib

import pytest

from prompt_enhancer.domain import (
    EventKind,
    EventTimeBasis,
    SafeEvent,
    SafeSession,
    UsageCounterKind,
    UsageScope,
)
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CodexAppServerAdapter,
    CodexReadLimits,
    CodexReadMode,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import CodexAppServerClient
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    RawThread,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexLimitError,
    CodexScopeError,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.mapping import (
    CodexThreadMapper,
)
from prompt_enhancer.metrics import compute_session_metrics


def _opaque(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def test_operational_metadata_maps_to_metrics_without_double_counting_usage() -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-metrics",
            "cwd": "/example/project",
            "createdAt": 1_768_473_600,
            "updatedAt": 1_768_474_200,
            "status": "completed",
            "usage": {
                "inputTokens": 100,
                "outputTokens": 40,
                "totalTokens": 140,
            },
            "turns": [
                {
                    "id": "example-turn-metrics",
                    "status": "completed",
                    "startedAt": 1_768_473_700,
                    "completedAt": 1_768_474_100,
                    "usage": {
                        "inputTokens": 10,
                        "outputTokens": 5,
                    },
                    "items": [
                        {
                            "id": "example-item-metrics",
                            "type": "commandExecution",
                        }
                    ],
                }
            ],
        }
    )
    snapshot = CodexThreadMapper(provider_version="example-1").snapshot(raw)
    usage_events = [
        event for event in snapshot.events if event.kind is EventKind.USAGE
    ]

    assert len(usage_events) == 1
    turn_usage = next(
        event.usage
        for event in usage_events
        if event.usage is not None and event.usage.scope is UsageScope.TURN
    )
    assert turn_usage.counter_kind is UsageCounterKind.DELTA
    assert turn_usage.total_tokens is None
    assert snapshot.session.ended_at is None

    tool_event = next(
        event for event in snapshot.events if event.kind is EventKind.TOOL_END
    )
    assert tool_event.success is None
    assert tool_event.duration_ms is None
    assert tool_event.time_basis is EventTimeBasis.TURN_COMPLETED

    safe_session = SafeSession(
        provider=snapshot.session.provider,
        installation_id=_opaque("installation"),
        project_id=_opaque("project"),
        session_id=_opaque("session"),
        provider_version=snapshot.session.provider_version,
        adapter_version=snapshot.session.adapter_version,
        source_schema_version=snapshot.session.source_schema_version,
        started_at=snapshot.session.started_at,
        ended_at=snapshot.session.ended_at,
        terminal_state=snapshot.session.terminal_state,
        events_complete=snapshot.session.events_complete,
    )
    safe_events = tuple(
        SafeEvent(
            session_id=safe_session.session_id,
            event_id=_opaque(f"event-{index}"),
            kind=event.kind,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            time_basis=event.time_basis,
            duration_ms=event.duration_ms,
            success=event.success,
            tool_category=event.tool_category,
            usage=event.usage,
        )
        for index, event in enumerate(snapshot.events)
    )
    metrics = {
        metric.key: metric for metric in compute_session_metrics(safe_session, safe_events)
    }

    assert metrics["usage.input_tokens"].numeric_value == 10
    assert metrics["usage.output_tokens"].numeric_value == 5
    assert metrics["usage.total_tokens"].numeric_value is None
    assert metrics["usage.input_tokens"].eligible_count == 1
    assert metrics["usage.input_tokens"].observed_count == 1

    turn_usage_coverage = metrics["data_quality.turn_usage_coverage"]
    assert turn_usage_coverage.numeric_value == 1
    assert turn_usage_coverage.observed_count == 1
    assert turn_usage_coverage.eligible_count == 1
    assert turn_usage_coverage.confidence is None

    turn_duration = metrics["efficiency.observed_finalized_turn_duration_ms"]
    assert turn_duration.numeric_value == 400_000
    assert turn_duration.coverage == 1
    assert turn_duration.confidence is None


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []

    def _start(self) -> None:
        raise AssertionError("synthetic transport must not launch")

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        return None

    def close(self) -> None:
        return None


def test_raw_cursor_is_hidden_and_adapter_token_is_single_use() -> None:
    raw_cursor_canary = "SYNTHETIC-RAW-CURSOR-PRIVATE"
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            {
                "data": [
                    {
                        "id": "example-session-page-1",
                        "cwd": "/example/project",
                        "createdAt": 1_768_473_600,
                    }
                ],
                "nextCursor": raw_cursor_canary,
            },
            {"data": [], "nextCursor": None},
        ]
    )
    adapter = CodexAppServerAdapter(
        mode=CodexReadMode.METADATA_INDEX,
        client_factory=lambda: CodexAppServerClient(transport),
    )
    adapter.probe()

    first = adapter.list_sessions(limit=1)
    assert first.next_cursor == "p1"
    assert raw_cursor_canary not in repr(first)
    adapter.list_sessions(cursor=first.next_cursor, limit=1)

    with pytest.raises(CodexScopeError) as error:
        adapter.list_sessions(cursor=first.next_cursor, limit=1)

    assert raw_cursor_canary not in str(error.value)
    list_requests = [request for request in transport.requests if request[0] == "thread/list"]
    assert list_requests[1][1]["cursor"] == raw_cursor_canary


def test_session_limit_stops_before_an_unbounded_followup_page() -> None:
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            {
                "data": [
                    {
                        "id": "example-session-limit",
                        "cwd": "/example/project",
                        "createdAt": 1_768_473_600,
                    }
                ],
                "nextCursor": "example-next-page",
            },
        ]
    )
    limits = CodexReadLimits(max_page_size=1, max_sessions=1)
    adapter = CodexAppServerAdapter(
        limits=limits,
        client_factory=lambda: CodexAppServerClient(transport, limits=limits),
    )
    adapter.probe()
    first = adapter.list_sessions(limit=1)

    with pytest.raises(CodexLimitError):
        adapter.list_sessions(cursor=first.next_cursor, limit=1)

    assert [method for method, _params in transport.requests].count("thread/list") == 1
