"""Fictional Agent work must expose receipts, never inferred usage or file effects."""
from __future__ import annotations

import json
import threading

import pytest

from prompt_enhancer.application.local_agent import AgentSettings, ApprovalDecision, LocalAgentError, LocalAgentService, SendMessage
from prompt_enhancer.application.local_models import ChatUpstream
from tests.test_local_agent_completion import _finish_turn


def _reply(content="Example answer", *, usage=None, calls=None, finish="stop"):
    return json.dumps({"choices": [{"message": {"content": content, "tool_calls": calls or []}, "finish_reason": finish}], "usage": usage}).encode()


def _service(tmp_path, chat, **kwargs):
    root = tmp_path / "example-workspace"
    root.mkdir()
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model", **kwargs)
    session = service.create(AgentSettings(workspace=str(root), max_steps=3))
    return service, session, root


def test_whole_reply_records_actual_alias_reported_usage_and_monotonic_time(tmp_path):
    ticks = [10.0]
    requests = []

    def chat(alias, body):
        requests.append((alias, json.loads(body)))
        ticks[0] += 2.5
        return 200, _reply(usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}), "application/json"

    service, session, _root = _service(tmp_path, chat, monotonic=lambda: ticks[0])
    try:
        _finish_turn(service, session.session_id, "Explain the fictional example.")
        events = service.events(session.session_id).events
        receipt = events[-1].turn_summary
        assert events[-1].kind == "done" and receipt is not None
        assert receipt.model_alias == requests[0][0] == "example-model"
        assert receipt.status == "completed" and receipt.reason == "answer_complete"
        assert receipt.turn_number == 1
        assert {event.turn_id for event in events if event.kind != "status"} == {receipt.turn_id}
        assert receipt.duration_ms == receipt.model_wait_ms == 2500
        assert receipt.time_to_first_text_ms is None  # whole replies do not report first-token timing
        assert receipt.usage.state == "reported"
        assert receipt.usage.model_requests == receipt.usage.reported_requests == 1
        assert (receipt.usage.prompt_tokens, receipt.usage.completion_tokens, receipt.usage.total_tokens) == (5, 7, 12)
        assert receipt.usage.reasoning_tokens is receipt.usage.cached_prompt_tokens is None
        assert receipt.writes == () and receipt.tools_requested == 0
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("usage", [None, {}, {"completion_tokens": 9}])
def test_missing_usage_is_unknown_not_zero_or_a_partial_total(tmp_path, usage):
    service, session, _root = _service(tmp_path, lambda *_: (200, _reply(usage=usage), "application/json"))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        receipt = service.events(session.session_id).events[-1].turn_summary
        assert receipt.usage.prompt_tokens is receipt.usage.total_tokens is None
        assert receipt.usage.completion_tokens == (9 if usage else None)
        assert receipt.usage.state == ("partial" if usage else "unavailable")
        assert receipt.usage.reported_requests == 0
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": True, "completion_tokens": 3, "total_tokens": 4},
    {"prompt_tokens": -1, "completion_tokens": 3, "total_tokens": 2},
    {"prompt_tokens": "2", "completion_tokens": 3, "total_tokens": 5},
    {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 500},
    {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5, "completion_tokens_details": {"reasoning_tokens": 4}},
    {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5, "prompt_tokens_details": {"cached_tokens": 3}},
])
def test_invalid_usage_does_not_become_a_number_or_discard_a_completed_answer(tmp_path, usage):
    service, session, _root = _service(tmp_path, lambda *_: (200, _reply(usage=usage), "application/json"))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        events = service.events(session.session_id).events
        assert events[-2].text == "Example answer"
        receipt = events[-1].turn_summary
        assert receipt.status == "completed" and receipt.usage.state == "invalid"
        assert receipt.usage.prompt_tokens is receipt.usage.completion_tokens is receipt.usage.total_tokens is None
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("approved", [True, False])
def test_write_summary_requires_a_successful_reviewed_write_not_an_assistant_claim(tmp_path, approved):
    requests = []
    call = {"id": "example-write", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "example.txt", "content": "new example\nsecond line\n"})}}

    def chat(_alias, body):
        requests.append(json.loads(body))
        if len(requests) == 1:
            return 200, _reply("", calls=[call], finish="tool_calls", usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}), "application/json"
        return 200, _reply("I changed example.txt.", usage={"prompt_tokens": 6, "completion_tokens": 7, "total_tokens": 13}), "application/json"

    service, session, root = _service(tmp_path, chat, approval_wait_seconds=2)
    (root / "example.txt").write_text("old example\n", encoding="utf-8")
    try:
        service.send(session.session_id, SendMessage(text="Update the example file."))
        cursor = 0
        while True:
            page = service.wait_events(session.session_id, after=cursor, timeout=1)
            cursor = page.last_seq
            if page.pending_approval_id:
                service.approve(session.session_id, page.pending_approval_id, ApprovalDecision(approved=approved))
                break
            assert page.running
        worker = service._session(session.session_id).thread
        worker.join(timeout=3)
        assert not worker.is_alive()
        events = service.events(session.session_id).events
        receipt = events[-1].turn_summary
        assert receipt.usage.total_tokens == 18 and receipt.usage.model_requests == 2
        assert receipt.tools_requested == 1
        result = next(event for event in events if event.kind == "tool_result")
        if approved:
            assert receipt.tools_succeeded == 1 and len(receipt.writes) == 1
            change = receipt.writes[0]
            assert change == result.write_receipt and change.state == "verified"
            assert change.path == "example.txt" and change.operation == "modified"
            assert (change.added_lines, change.removed_lines) == (2, 1)
            assert change.before_sha256 != change.after_sha256
            assert change.byte_size == len("new example\nsecond line\n".encode())
        else:
            assert receipt.tools_not_approved == 1 and receipt.writes == ()
            assert result.tool_state == "not_approved" and result.write_receipt is None
            assert (root / "example.txt").read_text() == "old example\n"
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize(("finish", "expected"), [("length", "model_response_limit"), ("content_filter", "model_response_filtered")])
def test_incomplete_generation_keeps_reported_usage_but_never_claims_a_finished_turn(tmp_path, finish, expected):
    service, session, _root = _service(tmp_path, lambda *_: (200, _reply(finish=finish, usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}), "application/json"))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        receipt = service.events(session.session_id).events[-1].turn_summary
        assert receipt.status == "failed" and receipt.reason == expected
        assert receipt.usage.total_tokens == 12 and receipt.writes == ()
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("late_result", ["http_error", "exception", "local_error"])
def test_user_stop_owns_a_late_failing_whole_request(tmp_path, late_result):
    entered, release = threading.Event(), threading.Event()

    def chat(*_args):
        entered.set()
        assert release.wait(2)
        if late_result == "exception":
            raise OSError("synthetic late failure")
        if late_result == "local_error":
            raise LocalAgentError("runtime_unreachable")
        return 503, b"example unavailable", "application/json"

    service, session, _root = _service(tmp_path, chat)
    try:
        service.send(session.session_id, SendMessage(text="Example request."))
        assert entered.wait(1)
        service.stop(session.session_id)
        release.set()
        worker = service._session(session.session_id).thread
        worker.join(timeout=2)
        assert not worker.is_alive()
        events = service.events(session.session_id).events
        receipt = events[-1].turn_summary
        assert receipt.status == "stopped" and receipt.reason == "stop_requested"
        assert receipt.usage.state == "unavailable" and receipt.usage.model_requests == 1
        assert not any(event.kind == "error" for event in events)
    finally:
        release.set()
        service.shutdown(timeout=1)


def test_turn_identifiers_and_aliases_are_not_rewritten_by_the_next_active_model(tmp_path):
    root = tmp_path / "example-workspace"
    root.mkdir()
    active = ["example-model-one"]

    def chat(alias, _body):
        active[0] = "example-model-two"
        return 200, _reply(f"Answer from {alias}"), "application/json"

    service = LocalAgentService(chat=chat, active_model=lambda: active[0])
    session = service.create(AgentSettings(workspace=str(root)))
    try:
        _finish_turn(service, session.session_id, "First fictional request.")
        first = service.events(session.session_id).events[-1]
        _finish_turn(service, session.session_id, "Second fictional request.")
        later = service.events(session.session_id, after=first.seq).events
        second = later[-1]
        assert first.turn_summary.model_alias == "example-model-one"
        assert second.turn_summary.model_alias == "example-model-two"
        assert first.turn_id != second.turn_id
        assert (first.turn_summary.turn_number, second.turn_summary.turn_number) == (1, 2)
        assert all(event.turn_id == second.turn_id for event in later)
    finally:
        service.shutdown(timeout=1)


@pytest.mark.parametrize("streaming", [False, True])
def test_ambiguous_usage_json_never_becomes_a_reported_metric(tmp_path, streaming):
    kind = "delta" if streaming else "message"
    payload = ('{"choices":[{"' + kind + '":{"content":"Example answer"},"finish_reason":"stop"}],'
               '"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":500,"total_tokens":5}}').encode()
    service, session, _root = _service(tmp_path, lambda *_: (200, payload, "application/json"),
                                     open_chat=(lambda *_: ChatUpstream(200, "text/event-stream", lines=iter([b"data: " + payload + b"\n\n"]))) if streaming else None)
    try:
        _finish_turn(service, session.session_id, "Example request.")
        receipt = service.events(session.session_id).events[-1].turn_summary
        assert receipt.status == "failed" and receipt.reason == "model_reply_unusable"
        assert receipt.usage.total_tokens is None
        assert receipt.usage.state == "unavailable"
    finally:
        service.shutdown(timeout=1)


def test_an_invalid_stream_usage_packet_cannot_be_overwritten_as_valid(tmp_path):
    packets = [
        b'data: {"choices":[],"usage":{"prompt_tokens":true}}\n\n',
        b'data: {"choices":[{"delta":{"content":"Example answer"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n',
    ]
    service, session, _root = _service(tmp_path, lambda *_: pytest.fail("no fallback expected"),
                                     open_chat=lambda *_: ChatUpstream(200, "text/event-stream", lines=iter(packets)))
    try:
        _finish_turn(service, session.session_id, "Example request.")
        receipt = service.events(session.session_id).events[-1].turn_summary
        assert receipt.status == "completed" and receipt.usage.state == "invalid"
        assert receipt.usage.total_tokens is None
    finally:
        service.shutdown(timeout=1)
