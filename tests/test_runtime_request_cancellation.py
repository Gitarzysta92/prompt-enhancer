"""Real loopback HTTP, fictional replies, and gated cancellation boundaries."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
import threading
import time
from types import SimpleNamespace

import anyio
from fastapi import FastAPI
import httpx
import pytest
import uvicorn

from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService, SendMessage
from prompt_enhancer.application.local_agent_limits import LocalAgentError
from prompt_enhancer.application.local_models import LocalModelService
from prompt_enhancer.interfaces.http.local_model_routes import _ChatRelayResponse, create_local_model_router


@contextmanager
def _gated_runtime(phase="headers"):
    entered, release, disconnected = (threading.Event() for _ in range(3))
    requests = []
    closed_request_numbers = []
    metadata_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def wait_for_release(self):
            entered.set()
            deadline = time.monotonic() + 5
            while not release.is_set() and time.monotonic() < deadline:
                ready, _, _ = select.select([self.connection], [], [], 0.02)
                try:
                    closed = bool(ready) and not self.connection.recv(1, socket.MSG_PEEK)
                except (ConnectionResetError, ConnectionAbortedError):
                    closed = True
                if closed:
                    closed_request_numbers.append(self.example_request_number)
                    disconnected.set()
                    return False
            return release.is_set()

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with metadata_lock:
                requests.append(request)
                self.example_request_number = len(requests)
            streaming = request.get("stream") is True and phase != "json-body"
            packet = {"choices": [{"message": {"content": "Example answer"}, "finish_reason": "stop"}]}
            if streaming:
                packet["choices"][0]["delta"] = packet["choices"][0].pop("message")
            body = ("data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n").encode() if streaming else json.dumps(packet).encode()
            status = 503 if phase == "error-body" else 200
            content_type = "text/event-stream" if streaming and status == 200 else "application/json"
            if status != 200:
                body = b'{"error":{"code":"example_runtime_error"}}'
            try:
                if phase == "headers" and not self.wait_for_release():
                    return
                if phase == "partial-headers":
                    self.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Typ")
                    self.wfile.flush()
                    if not self.wait_for_release():
                        return
                    self.wfile.write(f"e: {content_type}\r\nContent-Length: {len(body)}\r\n\r\n".encode())
                else:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                if phase in {"body", "json-body", "error-body"}:
                    self.wfile.write(body[:1])
                    self.wfile.flush()
                    if not self.wait_for_release():
                        return
                    body = body[1:]
                self.wfile.write(body)
                self.wfile.flush()
            except (OSError, ValueError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, name="example-gated-runtime")
    worker.start()

    class Models(LocalModelService):
        def __init__(self):
            # Only the real HTTP adapter is under test; no registry or GPU.
            # Shadow model/template admission: this seam owns only socket
            # cancellation and deliberately has no runtime or context ledger.
            self._context_preflight = None
            self.closed_request_numbers = closed_request_numbers
            self.reservation_lock = threading.Lock()
            self.active_runtime_requests = 0

        def _prepare_chat(self, _alias, body):
            return SimpleNamespace(base_url=f"http://127.0.0.1:{server.server_port}"), json.loads(body)

        def _reserve_runtime_request(self, _alias, _handle):
            with self.reservation_lock:
                self.active_runtime_requests += 1

        def _release_runtime_request(self, _alias):
            with self.reservation_lock:
                assert self.active_runtime_requests > 0
                self.active_runtime_requests -= 1

    models = Models()
    try:
        yield models, entered, release, disconnected, requests
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()
        with models.reservation_lock:
            assert models.active_runtime_requests == 0


@contextmanager
def _served_router(models):
    # This fixture tests ASGI responsiveness, not authentication. Existing full
    # app tests exercise the production loopback/auth/privacy middleware.
    app = FastAPI()
    app.include_router(create_local_model_router(lambda: None, models))

    @app.get("/example-heartbeat")
    async def heartbeat():
        return {"ready": True}

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical", lifespan="off"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, name="example-chat-api")
        worker.start()
        deadline = time.monotonic() + 3
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        try:
            assert server.started
            yield port
        finally:
            server.should_exit = True
            worker.join(timeout=3)
            assert not worker.is_alive()


@pytest.mark.parametrize("phase,fallback", [
    ("headers", False), ("partial-headers", False), ("headers", True),
    ("json-body", False), ("error-body", False), ("body", True),
], ids=["stream-headers", "partial-headers", "whole-headers", "json-body", "error-body", "whole-body"])
def test_agent_stop_cancels_pre_response_io_and_allows_a_fresh_turn(tmp_path, phase, fallback):
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    with _gated_runtime(phase) as (models, entered, release, disconnected, _requests):
        service = LocalAgentService(chat=models.chat, open_chat=None if fallback else models.open_chat, active_model=lambda: "example-model")
        session = service.create(AgentSettings(workspace=str(workspace)))
        try:
            service.send(session.session_id, SendMessage(text="Example request."))
            assert entered.wait(2)
            service.stop(session.session_id)
            worker = service._session(session.session_id).thread
            worker.join(timeout=0.8)
            assert not worker.is_alive(), "Stop left the owned runtime request running"
            assert disconnected.wait(0.5), "Stop did not close its upstream connection"
            events = service.events(session.session_id).events
            assert events[-1].turn_summary.status == "stopped"
            assert not any(event.kind == "error" for event in events)
            release.set()
            service.send(session.session_id, SendMessage(text="Example next request."))
            service._session(session.session_id).thread.join(timeout=2)
            assert not service.get(session.session_id).running
            receipt = service.events(session.session_id).events[-1].turn_summary
            assert receipt.turn_number == 2
            assert receipt.status == ("failed" if phase == "error-body" else "completed")
        finally:
            release.set()
            service.shutdown(timeout=2)


def _start_http_chat(port, route, *, stream=True):
    body = json.dumps({"model": "example-model", "messages": [{"role": "user", "content": "Example request."}], "stream": stream}).encode()
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    client.sendall(f"POST {route} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
    return client


@pytest.mark.parametrize("route", [
    "/v1/local-models/openai/v1/chat/completions",
    "/v1/local-models/example-model/v1/chat/completions",
    "/v1/local-models/example-model/chat/completions",
], ids=["openai", "alias-base", "models-chat"])
def test_models_chat_keeps_api_responsive_before_runtime_headers(route):
    with _gated_runtime() as (models, entered, release, _disconnected, _requests), _served_router(models) as port:
        client = _start_http_chat(port, route)
        try:
            assert entered.wait(2)
            with httpx.Client(trust_env=False, timeout=0.5) as probe:
                assert probe.get(f"http://127.0.0.1:{port}/example-heartbeat").json() == {"ready": True}
        finally:
            client.close()
            release.set()


@pytest.mark.parametrize("phase,stream", [("headers", True), ("body", True), ("headers", False), ("json-body", True)], ids=["stream-headers", "stream-body", "whole-headers", "json-body"])
def test_disconnected_models_chat_closes_only_its_upstream(phase, stream):
    with _gated_runtime(phase) as (models, entered, release, disconnected, _requests), _served_router(models) as port:
        client = _start_http_chat(port, "/v1/local-models/example-model/chat/completions", stream=stream)
        try:
            assert entered.wait(2)
            client.close()
            assert disconnected.wait(0.8), "Disconnected chat left its upstream request running"
        finally:
            client.close()
            release.set()


def test_stopping_one_agent_does_not_cancel_another_turn_using_the_same_model(tmp_path):
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    with _gated_runtime() as (models, entered, release, disconnected, requests):
        service = LocalAgentService(chat=models.chat, open_chat=models.open_chat, active_model=lambda: "example-model")
        first, second = (service.create(AgentSettings(workspace=str(workspace))) for _ in range(2))
        try:
            service.send(first.session_id, SendMessage(text="Example first request."))
            assert entered.wait(2)
            service.send(second.session_id, SendMessage(text="Example second request."))
            deadline = time.monotonic() + 2
            while len(requests) < 2 and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            assert len(requests) == 2
            service.stop(first.session_id)
            service._session(first.session_id).thread.join(timeout=0.8)
            assert not service.get(first.session_id).running
            assert disconnected.wait(0.5) and models.closed_request_numbers == [1]
            assert service.get(second.session_id).running
            assert not service.get(second.session_id).stopping
            release.set()
            service._session(second.session_id).thread.join(timeout=2)
            assert service.events(second.session_id).events[-1].turn_summary.status == "completed"
        finally:
            release.set()
            service.shutdown(timeout=2)


@pytest.mark.parametrize("operation", ["delete", "shutdown"])
def test_session_teardown_joins_a_request_waiting_for_headers(tmp_path, operation):
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    with _gated_runtime() as (models, entered, release, disconnected, _requests):
        service = LocalAgentService(chat=models.chat, open_chat=models.open_chat, active_model=lambda: "example-model")
        session = service.create(AgentSettings(workspace=str(workspace)))
        try:
            service.send(session.session_id, SendMessage(text="Example teardown request."))
            assert entered.wait(2)
            worker = service._session(session.session_id).thread
            started = time.monotonic()
            if operation == "delete":
                service.delete(session.session_id)
            else:
                service.shutdown(timeout=1)
            assert time.monotonic() - started < 1
            assert not worker.is_alive()
            assert disconnected.wait(0.5)
        finally:
            release.set()
            service.shutdown(timeout=2)


def test_noncooperative_adapter_stays_running_and_stop_is_published_only_once(tmp_path):
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    entered, release = threading.Event(), threading.Event()

    def chat(_alias, _body):
        entered.set()
        release.wait(2)
        return 200, b'{"choices":[{"message":{"content":"Example late reply"},"finish_reason":"stop"}]}', "application/json"

    service = LocalAgentService(chat=chat, active_model=lambda: "example-model")
    session = service.create(AgentSettings(workspace=str(workspace)))
    try:
        service.send(session.session_id, SendMessage(text="Example uncancellable adapter request."))
        assert entered.wait(1)
        first_stop = service.stop(session.session_id)
        second_stop = service.stop(session.session_id)
        assert first_stop.running and first_stop.stopping
        assert second_stop.last_seq == first_stop.last_seq
        assert service.events(session.session_id).stopping
        with pytest.raises(LocalAgentError, match="turn_in_progress"):
            service.send(session.session_id, SendMessage(text="Example premature next turn."))
        release.set()
        service._session(session.session_id).thread.join(timeout=1)
        final = service.events(session.session_id)
        assert not final.running and not final.stopping
        assert final.events[-1].turn_summary.status == "stopped"
    finally:
        release.set()
        service.shutdown(timeout=2)


def test_client_disconnect_is_isolated_between_two_models_chat_requests():
    with _gated_runtime() as (models, entered, release, disconnected, requests), _served_router(models) as port:
        first = _start_http_chat(port, "/v1/local-models/example-model/chat/completions")
        second = None
        try:
            assert entered.wait(2)
            second = _start_http_chat(port, "/v1/local-models/example-model/chat/completions")
            deadline = time.monotonic() + 2
            while len(requests) < 2 and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            assert len(requests) == 2
            first.close()
            assert disconnected.wait(0.8) and models.closed_request_numbers == [1]
            second.settimeout(0.15)
            with pytest.raises(TimeoutError):
                second.recv(1)
            release.set()
            second.settimeout(2)
            reply = bytearray()
            while chunk := second.recv(8192):
                reply.extend(chunk)
                assert len(reply) < 64_000
            assert b"200 OK" in reply and b"Example answer" in reply and b"data: [DONE]" in reply
        finally:
            first.close()
            if second is not None:
                second.close()
            release.set()


def test_asgi_task_cancellation_joins_the_pre_header_worker_without_a_false_error():
    with _gated_runtime() as (models, entered, release, disconnected, _requests):
        sent = []

        async def receive():
            await anyio.sleep_forever()

        async def send(message):
            sent.append(message)

        async def cancel_request():
            response = _ChatRelayResponse(lambda: models.open_chat("example-model", b'{"messages":[],"stream":true}'))
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(response, {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
                assert await anyio.to_thread.run_sync(entered.wait, 2)
                tasks.cancel_scope.cancel()

        try:
            anyio.run(cancel_request)
            assert disconnected.wait(0.8)
            assert not sent, "A cancelled request must not invent response headers or status"
        finally:
            release.set()
