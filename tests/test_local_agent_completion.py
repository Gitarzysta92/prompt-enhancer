"""Synthetic completion receipts must gate Agent history and tool execution."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from prompt_enhancer.application.local_agent import (
    AgentSettings,
    AgentStreamStatus,
    LocalAgentService,
    SendMessage,
)
from prompt_enhancer.application.local_models import ChatUpstream


def _sse(choice: dict) -> bytes:
    return ("data: " + json.dumps({"choices": [choice]}) + "\n\n").encode()


def _finish_turn(service: LocalAgentService, session_id: str, text: str) -> None:
    service.send(session_id, SendMessage(text=text))
    worker = service._session(session_id).thread  # noqa: SLF001 - synthetic worker ownership
    assert worker is not None
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert service.get(session_id).running is False


@pytest.mark.parametrize("mode", ("stream", "whole", "stream_fallback"))
@pytest.mark.parametrize(
    ("finish_reason", "expected_notice"),
    (
        ("length", "response token limit"),
        ("content_filter", "runtime filtered"),
        ("example_unknown", "unrecognized completion"),
        (None, "ended before completion"),
    ),
)
@pytest.mark.parametrize("with_tools", (False, True))
def test_incomplete_receipt_never_completes_history_or_executes_tools(
    tmp_path: Path, mode: str, finish_reason: str | None,
    expected_notice: str, with_tools: bool,
) -> None:
    root = tmp_path / "example-project"
    root.mkdir()
    (root / "example.txt").write_text("fictional source\n", encoding="utf-8")
    requests: list[dict] = []
    tools = [
        {"id": "example-read", "type": "function", "function": {
            "name": "read_file", "arguments": json.dumps({"path": "example.txt"}),
        }},
        {"id": "example-write", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "generated.txt", "content": "example"}),
        }},
    ] if with_tools else []

    def reply(body: bytes) -> tuple[dict, str | None]:
        requests.append(json.loads(body))
        if len(requests) == 1:
            return {
                "content": "Example unfinished answer",
                "reasoning_content": "Example partial model trace",
                "tool_calls": tools,
            }, finish_reason
        return {"content": "Example recovered answer"}, "stop"

    def chat(_alias: str, body: bytes):
        message, finish = reply(body)
        return 200, json.dumps({"choices": [{"message": message, "finish_reason": finish}]}).encode(), "application/json"

    def open_chat(_alias: str, body: bytes) -> ChatUpstream:
        if mode == "stream_fallback":
            status, payload, kind = chat(_alias, body)
            return ChatUpstream(status, kind, body=payload)
        message, finish = reply(body)
        delta = dict(message)
        if "tool_calls" in delta:
            delta["tool_calls"] = [dict(call, index=index) for index, call in enumerate(delta["tool_calls"])]
        lines = [_sse({"delta": delta, "finish_reason": finish})]
        if finish is not None:
            lines.append(b"data: [DONE]\n\n")
        return ChatUpstream(200, "text/event-stream", lines=iter(lines))

    service = LocalAgentService(
        chat=chat, open_chat=None if mode == "whole" else open_chat,
        active_model=lambda: "example-model", approval_wait_seconds=0.01,
    )
    session = service.create(AgentSettings(workspace=str(root), parameters={"enable_thinking": True}))
    try:
        _finish_turn(service, session.session_id, "Explain the example file.")
        events = service.events(session.session_id).events
        assistant = [event for event in events if event.kind == "assistant"]
        assert len(assistant) == 1
        assert assistant[0].stream_status is AgentStreamStatus.FAILED
        assert assistant[0].text == "Example unfinished answer"
        assert assistant[0].reasoning == "Example partial model trace"
        assert any(event.kind == "error" and expected_notice in (event.text or "") for event in events)
        assert not any(event.kind in {"tool_call", "tool_result", "approval_required"} for event in events)
        assert not (root / "generated.txt").exists()
        assert len(requests) == 1

        _finish_turn(service, session.session_id, "Try a shorter explanation.")
        assert [message["role"] for message in requests[1]["messages"]] == ["system", "user", "user"]
        assert all("Example unfinished answer" not in (message.get("content") or "") for message in requests[1]["messages"])
        assert service.events(session.session_id).events[-2].text == "Example recovered answer"
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize(
    "bad_choice",
    (
        {"delta": {"content": {"text": "example"}}},
        {"delta": {"reasoning_content": 17}},
        {"delta": {"tool_calls": {"function": "example"}}},
        {"delta": {"tool_calls": [{"index": 0, "function": {"name": "list_dir", "arguments": 17}}]}},
        {"delta": {}, "finish_reason": 17},
    ),
)
def test_malformed_stream_fields_cannot_promote_a_partial_answer(tmp_path: Path, bad_choice: dict) -> None:
    root = tmp_path / "example-project"
    root.mkdir()
    lines = [
        _sse({"delta": {"content": "Example partial answer"}}),
        _sse(bad_choice),
        b"data: [DONE]\n\n",
    ]
    service = LocalAgentService(
        chat=lambda *_: (500, b"", "application/json"),
        open_chat=lambda *_: ChatUpstream(200, "text/event-stream", lines=iter(lines)),
        active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(root), max_steps=1))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        events = service.events(session.session_id).events
        assistant = next(event for event in events if event.kind == "assistant")
        assert assistant.stream_status is AgentStreamStatus.FAILED
        assert assistant.text == "Example partial answer"
        assert not any(event.kind in {"tool_call", "approval_required"} for event in events)
        assert [message["role"] for message in service._session(session.session_id).messages] == ["system", "user"]
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("mode", ("stream", "whole", "stream_fallback"))
def test_reasoning_without_an_answer_is_visibly_incomplete(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "example-project"
    root.mkdir()
    message = {"reasoning_content": "Example model trace without a final answer"}
    payload = json.dumps({"choices": [{"message": message, "finish_reason": "stop"}]}).encode()
    service = LocalAgentService(
        chat=lambda *_: (200, payload, "application/json"),
        open_chat=None if mode == "whole" else lambda *_: (
            ChatUpstream(200, "application/json", body=payload) if mode == "stream_fallback"
            else ChatUpstream(200, "text/event-stream", lines=iter([_sse({"delta": message, "finish_reason": "stop"})]))
        ),
        active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(root), parameters={"enable_thinking": True}))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        events = service.events(session.session_id).events
        assistant = next(event for event in events if event.kind == "assistant")
        assert assistant.stream_status is AgentStreamStatus.FAILED
        assert assistant.reasoning == message["reasoning_content"]
        assert any(event.kind == "error" and "no final answer" in (event.text or "") for event in events)
        assert [message["role"] for message in service._session(session.session_id).messages] == ["system", "user"]
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("mode", ("whole", "stream_fallback"))
def test_stop_during_a_whole_response_cannot_publish_completed_history(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "example-project"
    root.mkdir()
    entered = threading.Event()
    release = threading.Event()

    def chat(*_):
        entered.set()
        assert release.wait(timeout=3)
        payload = {"choices": [{"message": {"content": "Example late answer"}, "finish_reason": "stop"}]}
        return 200, json.dumps(payload).encode(), "application/json"

    def open_chat(*args) -> ChatUpstream:
        status, payload, kind = chat(*args)
        return ChatUpstream(status, kind, body=payload)

    service = LocalAgentService(
        chat=chat, open_chat=None if mode == "whole" else open_chat, active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(root)))
    try:
        service.send(session.session_id, SendMessage(text="Example request."))
        assert entered.wait(timeout=2)
        service.stop(session.session_id)
        release.set()
        worker = service._session(session.session_id).thread
        assert worker is not None
        worker.join(timeout=3)
        assert not worker.is_alive()
        assistant = next(event for event in service.events(session.session_id).events if event.kind == "assistant")
        assert assistant.text == "Example late answer"
        assert assistant.stream_status is AgentStreamStatus.STOPPED
        assert [message["role"] for message in service._session(session.session_id).messages] == ["system", "user"]
    finally:
        release.set()
        service.shutdown(timeout=1)


@pytest.mark.parametrize("reason", ("stop", "length"))
def test_terminal_receipt_closes_response_without_waiting_for_done(tmp_path: Path, reason: str) -> None:
    root = tmp_path / "example-project"
    root.mkdir()
    closed = threading.Event()

    def lines():
        try:
            yield _sse({"delta": {"content": "Example answer"}, "finish_reason": reason})
            raise AssertionError("The terminal receipt must end consumption.")
        finally:
            closed.set()

    service = LocalAgentService(
        chat=lambda *_: (500, b"", "application/json"),
        open_chat=lambda *_: ChatUpstream(200, "text/event-stream", lines=lines()),
        active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(root)))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        assistant = next(event for event in service.events(session.session_id).events if event.kind == "assistant")
        assert assistant.stream_status is (AgentStreamStatus.COMPLETE if reason == "stop" else AgentStreamStatus.FAILED)
        assert closed.is_set()
    finally:
        service.shutdown(timeout=1)
