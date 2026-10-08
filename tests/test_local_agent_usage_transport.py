"""Loopback-only synthetic usage trailers exercise the actual runtime transport."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from types import SimpleNamespace

import pytest

from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService, SendMessage
from prompt_enhancer.application.local_models import LocalModelService
from tests.test_local_agent_completion import _finish_turn


@contextmanager
def _runtime(trailer, *, complete=True, framing="close", piece_delay=0):
    release = threading.Event()
    requests = []
    active_requests = 0

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1" if framing == "chunked" else "HTTP/1.0"
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            packet = {"choices": [{"delta": {"content": "Example streamed answer"}, "finish_reason": "stop" if complete else None}]}
            first = ("data: " + json.dumps(packet) + "\n\n").encode()
            pieces = trailer if isinstance(trailer, list) else [trailer] if trailer is not None else []
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            if framing == "chunked":
                self.send_header("Transfer-Encoding", "chunked")
            elif framing == "length":
                self.send_header("Content-Length", str(len(first) + sum(len(piece) for piece in pieces)))
            self.end_headers()

            def write(piece):
                self.wfile.write((f"{len(piece):x}\r\n".encode() + piece + b"\r\n") if framing == "chunked" else piece)
                self.wfile.flush()

            try:
                write(first)
                for piece in pieces:
                    if piece_delay and release.wait(piece_delay):
                        break
                    write(piece)
                release.wait(3)  # deliberately no EOF or DONE while the client finishes
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, name="example-runtime-usage")
    worker.start()
    def reserve_runtime_request(_alias, _handle):
        nonlocal active_requests
        active_requests += 1

    def release_runtime_request(_alias):
        nonlocal active_requests
        active_requests -= 1

    owner = SimpleNamespace(
        _prepare_chat=lambda _alias, body: (
            SimpleNamespace(base_url=f"http://127.0.0.1:{server.server_port}"),
            json.loads(body),
        ),
        _reserve_runtime_request=reserve_runtime_request,
        _release_runtime_request=release_runtime_request,
    )
    try:
        yield lambda alias, body: LocalModelService.open_chat(owner, alias, body), requests
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert active_requests == 0


@pytest.mark.parametrize("trailer,expected_state", [
    (b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":6,"total_tokens":10}}\n\n', "reported"),
    (b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":6,"total_tokens":999}}\n\n', "invalid"),
    (None, "unavailable"),
    (b'data: {"choices":[{"delta":{"content":"UNSOLICITED EXAMPLE"},"finish_reason":null}]}\n\n', "unavailable"),
    (b'data: {"choices":[],"usage":"example-invalid"}\n\n', "invalid"),
    (b'data: {"choices":[],"usage":{"total_tokens":10,"total_tokens":20}}\n\n', "unavailable"),
    (b'data: {"choices":[],"usage":{"total_tokens":' + b"[" * 80 + b"0" + b"]" * 80 + b'}}\n\n', "unavailable"),
    (b'data: {"choices":[],"usage":{"example_padding":"' + b"x" * 65_000 + b'"}}\n\n', "unavailable"),
    ([b'data: {"choices":[],"usage":{"prompt_tokens":4,', b'"completion_tokens":6,"total_tokens":10}}\n\n'], "reported"),
    (b'data: [DONE]\n\n', "unavailable"),
], ids=["reported", "inconsistent", "absent", "extra-output", "wrong-type", "duplicate", "too-deep", "too-large", "fragmented", "done-only"])
def test_real_http_stream_captures_only_bounded_usage_metadata(tmp_path, trailer, expected_state):
    root = tmp_path / "example-workspace"
    root.mkdir()
    with _runtime(trailer) as (open_chat, requests):
        service = LocalAgentService(chat=lambda *_: pytest.fail("no fallback expected"), open_chat=open_chat, active_model=lambda: "example-model")
        session = service.create(AgentSettings(workspace=str(root)))
        try:
            started = time.monotonic()
            _finish_turn(service, session.session_id, "Example request.")
            assert time.monotonic() - started < 1.5
            assert requests[0]["stream_options"] == {"include_usage": True}
            events = service.events(session.session_id).events
            assert events[-2].text == "Example streamed answer"
            receipt = events[-1].turn_summary
            assert receipt.status == "completed" and receipt.time_to_first_text_ms is not None
            assert receipt.usage.state == expected_state
            assert receipt.usage.total_tokens == (10 if expected_state == "reported" else None)
            assert "UNSOLICITED" not in json.dumps([event.model_dump(mode="json") for event in events])
        finally:
            service.shutdown(timeout=1)


def test_stop_interrupts_an_actual_owned_socket_read_without_waiting_for_eof(tmp_path):
    root = tmp_path / "example-workspace"
    root.mkdir()
    with _runtime(None, complete=False) as (open_chat, _requests):
        service = LocalAgentService(chat=lambda *_: pytest.fail("no fallback expected"), open_chat=open_chat, active_model=lambda: "example-model")
        session = service.create(AgentSettings(workspace=str(root)))
        try:
            service.send(session.session_id, SendMessage(text="Example interruptible request."))
            cursor = 0
            for _ in range(5):
                page = service.wait_events(session.session_id, after=cursor, timeout=0.3)
                if any(event.kind == "assistant_delta" for event in page.events):
                    break
                cursor = page.last_seq
            else:
                pytest.fail("synthetic runtime did not begin streaming")
            started = time.monotonic()
            service.stop(session.session_id)
            worker = service._session(session.session_id).thread
            worker.join(timeout=1)
            assert not worker.is_alive() and time.monotonic() - started < 1
            events = service.events(session.session_id).events
            assert events[-1].turn_summary.status == "stopped"
            assert events[-1].turn_summary.usage.state == "unavailable"
            assert not any(event.kind == "error" for event in events)
        finally:
            service.shutdown(timeout=1)


@pytest.mark.parametrize("framing", ["chunked", "length"])
def test_runtime_reader_preserves_http_framing_for_usage_trailers(tmp_path, framing):
    root = tmp_path / "example-workspace"
    root.mkdir()
    trailer = b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":6,"total_tokens":10}}\n\n'
    with _runtime(trailer, framing=framing) as (open_chat, _requests):
        service = LocalAgentService(chat=lambda *_: pytest.fail("no fallback expected"), open_chat=open_chat, active_model=lambda: "example-model")
        session = service.create(AgentSettings(workspace=str(root)))
        try:
            _finish_turn(service, session.session_id, "Example request.")
            receipt = service.events(session.session_id).events[-1].turn_summary
            assert receipt.status == "completed" and receipt.usage.total_tokens == 10
        finally:
            service.shutdown(timeout=1)


def test_dribbled_metadata_is_bounded_by_one_absolute_deadline(tmp_path):
    root = tmp_path / "example-workspace"
    root.mkdir()
    pieces = [bytes([byte]) for byte in b'data: {"choices":[],"usage":{"total_tokens":10}}\n\n']
    with _runtime(pieces, piece_delay=0.04) as (open_chat, _requests):
        service = LocalAgentService(chat=lambda *_: pytest.fail("no fallback expected"), open_chat=open_chat, active_model=lambda: "example-model")
        session = service.create(AgentSettings(workspace=str(root)))
        try:
            started = time.monotonic()
            _finish_turn(service, session.session_id, "Example request.")
            assert time.monotonic() - started < 1
            receipt = service.events(session.session_id).events[-1].turn_summary
            assert receipt.status == "completed" and receipt.usage.state == "unavailable"
            assert receipt.usage.total_tokens is None
        finally:
            service.shutdown(timeout=1)
