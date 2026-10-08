from __future__ import annotations

from collections.abc import Callable

from prompt_enhancer.domain import DataTier, EventKind
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CodexAppServerAdapter,
    CodexReadMode,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import CodexAppServerClient


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.notifications: list[tuple[str, dict[str, object] | None]] = []
        self.closed = False

    def _start(self) -> None:
        raise AssertionError("the fake transport does not launch a process")

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        self.notifications.append((method, params))

    def close(self) -> None:
        self.closed = True


def _client_factory(
    transport: RecordingTransport,
    calls: list[str],
) -> Callable[[], CodexAppServerClient]:
    def factory() -> CodexAppServerClient:
        calls.append("constructed")
        return CodexAppServerClient(transport)

    return factory


def _listed_thread(*, next_cursor: str | None = None) -> dict[str, object]:
    return {
        "data": [
            {
                "id": "example-session-alpha",
                "cwd": "C:\\example\\workspace\\..\\project",
                "createdAt": 1_768_473_600,
                "updatedAt": 1_768_474_200,
                "status": "idle",
                "preview": "discarded synthetic preview",
            }
        ],
        "nextCursor": next_cursor,
    }


def test_constructor_is_inert_and_metadata_mode_never_reads_thread() -> None:
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.2.3"}},
            _listed_thread(),
        ]
    )
    factory_calls: list[str] = []
    adapter = CodexAppServerAdapter(
        mode=CodexReadMode.METADATA_INDEX,
        client_factory=_client_factory(transport, factory_calls),
    )

    assert factory_calls == []
    assert transport.requests == []
    assert adapter.required_consent_tier is DataTier.REDACTED_CONTENT
    assert adapter.requires_explicit_selection is False

    probe = adapter.probe()
    page = adapter.list_sessions()
    snapshot = adapter.read_session(page.sessions[0])

    assert factory_calls == ["constructed"]
    assert probe.supports_content is False
    assert snapshot.events == ()
    assert snapshot.session.events_complete is False
    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
    ]
    assert transport.notifications == [("initialized", {})]
    list_params = transport.requests[1][1]
    assert list_params["useStateDbOnly"] is True


def test_operational_mode_reads_only_metadata_events_after_listing() -> None:
    transport = RecordingTransport(
        [
            {"version": "example-2"},
            _listed_thread(),
            {
                "thread": {
                    "id": "example-session-alpha",
                    "cwd": "c:/example/project",
                    "createdAt": 1_768_473_600,
                    "updatedAt": 1_768_474_200,
                    "status": "completed",
                    "turns": [
                        {
                            "id": "example-turn-1",
                            "status": "completed",
                            "startedAt": 1_768_473_700,
                            "completedAt": 1_768_474_100,
                            "items": [
                                {
                                    "id": "example-item-1",
                                    "type": "commandExecution",
                                    "status": "completed",
                                    "durationMs": 250,
                                    "command": "discarded synthetic command",
                                    "output": "discarded synthetic output",
                                }
                            ],
                            "usage": {
                                "inputTokens": 120,
                                "outputTokens": 30,
                                "totalTokens": 150,
                            },
                        }
                    ],
                }
            },
        ]
    )
    adapter = CodexAppServerAdapter(
        mode=CodexReadMode.OPERATIONAL_HISTORY,
        client_factory=lambda: CodexAppServerClient(transport),
    )

    assert adapter.required_consent_tier is DataTier.REDACTED_CONTENT
    assert adapter.requires_explicit_selection is True
    assert adapter.probe().supports_content is True
    listed = adapter.list_sessions().sessions[0]
    snapshot = adapter.read_session(listed)

    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
        "thread/read",
    ]
    assert transport.requests[2][1] == {
        "threadId": "example-session-alpha",
        "includeTurns": True,
    }
    assert snapshot.session.events_complete is False
    assert EventKind.TURN_START in {event.kind for event in snapshot.events}
    assert EventKind.TOOL_END in {event.kind for event in snapshot.events}
    assert EventKind.USAGE in {event.kind for event in snapshot.events}
    for event in snapshot.events:
        assert not {"prompt", "message", "content", "command", "output"}.intersection(
            event.model_fields_set
        )
