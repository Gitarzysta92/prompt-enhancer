from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CodexAppServerAdapter,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    CodexAppServerClient,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    RawThread,
    parse_thread_read,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexLimitError,
    CodexProtocolViolation,
    CodexResponseLimitError,
    CodexTransportTimeout,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.limits import (
    CodexReadLimits,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.mapping import (
    CodexThreadMapper,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.transports.stdio_jsonl import (
    StdioJsonRpcTransport,
    ThreadReadPolicy,
)
from prompt_enhancer.interfaces.http.local_source_routes import (
    CodexAnalysisRequest,
)


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        return None

    def close(self) -> None:
        return None


def test_dashboard_analysis_request_has_a_small_independent_session_bound() -> None:
    selector = "a" * 64

    default_request = CodexAnalysisRequest(project_ids=frozenset({selector}))
    largest_request = CodexAnalysisRequest(
        project_ids=frozenset({selector}), max_sessions=100
    )

    assert default_request.max_sessions == 10
    assert largest_request.max_sessions == 100
    with pytest.raises(ValidationError):
        CodexAnalysisRequest(
            project_ids=frozenset({selector}), max_sessions=101
        )


def test_transport_classifies_oversized_lines_as_a_provider_response_limit() -> None:
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(max_json_line_bytes=16)
    )
    transport._lines.put(b"x" * 17 + b"\n")

    with pytest.raises(CodexResponseLimitError):
        transport._next_message(deadline=time.monotonic() + 0.1)

    assert transport._process is None


def test_text_analysis_transport_has_a_separate_bounded_response_ceiling() -> None:
    limits = CodexReadLimits(
        max_json_line_bytes=64,
        max_text_analysis_json_line_bytes=256,
    )
    generic = StdioJsonRpcTransport(limits=limits)
    text_analysis = StdioJsonRpcTransport(
        limits=limits,
        thread_read_policy=ThreadReadPolicy.TEXT_ANALYSIS,
    )
    response = b'{"id":1,"result":{"padding":"' + (b"x" * 96) + b'"}}\n'
    assert len(response) > limits.max_json_line_bytes
    assert len(response) <= limits.max_text_analysis_json_line_bytes

    generic._lines.put(response)
    with pytest.raises(CodexResponseLimitError):
        generic._next_message(deadline=time.monotonic() + 0.1)

    text_analysis._lines.put(response)
    parsed = text_analysis._next_message(deadline=time.monotonic() + 0.1)
    assert parsed["id"] == 1
    assert isinstance(parsed["result"], dict)


def test_unterminated_in_bound_line_remains_a_protocol_violation() -> None:
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(max_json_line_bytes=64)
    )
    transport._lines.put(b'{"id":1,"result":{}}')

    with pytest.raises(CodexProtocolViolation):
        transport._next_message(deadline=time.monotonic() + 0.1)


def test_transport_timeout_needs_no_provider_process() -> None:
    transport = StdioJsonRpcTransport()

    with pytest.raises(CodexTransportTimeout):
        transport._next_message(deadline=time.monotonic() - 1)

    assert transport._process is None


def test_thread_read_enforces_turn_and_item_bounds_before_mapping() -> None:
    thread = {
        "id": "example-session-bounds",
        "cwd": "/example/project",
        "createdAt": 1_768_473_600,
    }
    with pytest.raises(CodexLimitError):
        parse_thread_read(
            {
                "thread": {
                    **thread,
                    "turns": [
                        {"id": "example-turn-1", "items": []},
                        {"id": "example-turn-2", "items": []},
                    ],
                }
            },
            CodexReadLimits(max_turns_per_session=1),
        )

    with pytest.raises(CodexLimitError):
        parse_thread_read(
            {
                "thread": {
                    **thread,
                    "turns": [
                        {
                            "id": "example-turn-1",
                            "items": [
                                {"id": "example-item-1"},
                                {"id": "example-item-2"},
                            ],
                        }
                    ],
                }
            },
            CodexReadLimits(max_items_per_turn=1),
        )


def test_mapper_enforces_event_bound() -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-event-bound",
            "cwd": "/example/project",
            "createdAt": 1_768_473_600,
            "turns": [
                {
                    "id": "example-turn-final",
                    "status": "completed",
                    "items": [],
                }
            ],
        }
    )

    with pytest.raises(CodexLimitError):
        CodexThreadMapper(
            provider_version="example-1",
            limits=CodexReadLimits(max_events_per_session=1),
        ).snapshot(raw)


def test_adapter_stops_pagination_before_a_second_request() -> None:
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            {
                "data": [
                    {
                        "id": "example-session-page-bound",
                        "cwd": "/example/project",
                        "createdAt": 1_768_473_600,
                        "preview": "discarded synthetic preview",
                    }
                ],
                "nextCursor": "example-next-cursor",
            },
        ]
    )
    limits = CodexReadLimits(max_pages=1)
    adapter = CodexAppServerAdapter(
        limits=limits,
        client_factory=lambda: CodexAppServerClient(transport, limits=limits),
    )

    adapter.probe()
    first = adapter.list_sessions()
    with pytest.raises(CodexLimitError):
        adapter.list_sessions(cursor=first.next_cursor)

    assert [method for method, _params in transport.requests].count(
        "thread/list"
    ) == 1
