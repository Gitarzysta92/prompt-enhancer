"""The desktop launcher must prove a loopback listener's identity without ever
handing the persistent local token to whoever answers the configured port."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Thread
from typing import Any, Callable

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer import desktop_overlay
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http import desktop_identity


TOKEN = "example_desktop_identity_token_1234567890abcdef"
OTHER_TOKEN = "example_other_local_token_abcdefghijklmnop0123"


class EmptyReadStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self) -> list[dict[str, object]]:
        return []

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        return []

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]:
        return []


# --------------------------------------------------------------------------- #
# Pure proof primitives
# --------------------------------------------------------------------------- #


def test_challenge_is_fresh_full_length_lowercase_hex() -> None:
    first = desktop_identity.new_desktop_challenge()
    second = desktop_identity.new_desktop_challenge()
    assert first != second
    assert len(first) == desktop_identity.DESKTOP_CHALLENGE_BYTES * 2
    assert desktop_identity.parse_desktop_challenge(first) == bytes.fromhex(first)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "ab",
        "0" * 63,
        "0" * 65,
        "A" * 64,  # uppercase is refused so there is exactly one encoding
        "g" * 64,
        "0" * 62 + "\r\n",
    ],
)
def test_malformed_challenges_are_rejected(value: str | None) -> None:
    assert desktop_identity.parse_desktop_challenge(value) is None


def test_proof_binds_token_origin_and_challenge() -> None:
    origin = "http://127.0.0.1:18765"
    challenge = bytes(range(32))
    proof = desktop_identity.desktop_identity_proof(TOKEN, origin, challenge)

    assert desktop_identity.verify_desktop_identity_proof(TOKEN, origin, challenge, proof)
    assert not desktop_identity.verify_desktop_identity_proof(
        OTHER_TOKEN, origin, challenge, proof
    )
    assert not desktop_identity.verify_desktop_identity_proof(
        TOKEN, "http://127.0.0.1:18766", challenge, proof
    )
    assert not desktop_identity.verify_desktop_identity_proof(
        TOKEN, "http://localhost:18765", challenge, proof
    )
    assert not desktop_identity.verify_desktop_identity_proof(
        TOKEN, origin, bytes(32), proof
    )
    # The proof never embeds the token or a value derived directly from it.
    assert TOKEN not in proof
    assert proof != desktop_identity.desktop_identity_proof(TOKEN, origin, bytes(32))


@pytest.mark.parametrize(
    "proof",
    [None, "", 42, "0" * 63, "0" * 65, "G" * 64, ["0" * 64], {"proof": "0" * 64}],
)
def test_malformed_proofs_are_untrusted(proof: object) -> None:
    assert not desktop_identity.verify_desktop_identity_proof(
        TOKEN, "http://127.0.0.1:18765", bytes(32), proof
    )


def test_proof_requires_a_full_length_challenge() -> None:
    with pytest.raises(ValueError):
        desktop_identity.desktop_identity_proof(TOKEN, "http://127.0.0.1:18765", b"short")


def test_canonical_origin_matches_launcher_origin() -> None:
    for host, port in (("127.0.0.1", 18765), ("localhost", 8765), ("::1", 9000)):
        assert desktop_identity.canonical_loopback_origin(host, port) == (
            desktop_overlay._loopback_origin(host, port)
        )
    with pytest.raises(ValueError):
        desktop_identity.canonical_loopback_origin("192.0.2.10", 8765)
    with pytest.raises(ValueError):
        desktop_identity.canonical_loopback_origin("127.0.0.1", 80)


@pytest.mark.parametrize(
    ("host_header", "server", "expected"),
    (
        ("127.0.0.1:18765", ("127.0.0.1", 18765), "http://127.0.0.1:18765"),
        ("[::1]:18765", ("::1", 18765), "http://[::1]:18765"),
        ("localhost:18765", ("127.0.0.1", 18765), None),
        ("127.0.0.1:18765", ("::1", 18765), None),
        ("[::1]:18765", ("127.0.0.1", 18765), None),
        ("127.0.0.1:18765", ("127.0.0.1", 18766), None),
        ("127.0.0.1", ("127.0.0.1", 80), None),
    ),
)
def test_exact_request_origin_requires_the_observed_numeric_socket(
    host_header: str,
    server: object,
    expected: str | None,
) -> None:
    assert desktop_identity.exact_request_loopback_origin(host_header, server) == expected


def test_launcher_resolves_localhost_to_separate_exact_ipv4_and_ipv6_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        desktop_overlay.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 18765, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 18765)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 18765, 0, 0)),
        ],
    )

    assert desktop_overlay._exact_loopback_endpoints("localhost", 18765) == (
        ("::1", "http://[::1]:18765"),
        ("127.0.0.1", "http://127.0.0.1:18765"),
    )


# --------------------------------------------------------------------------- #
# Synthetic loopback listeners exercised through the real launcher probe
# --------------------------------------------------------------------------- #


Responder = Callable[[BaseHTTPRequestHandler], None]


class _Listener:
    """A throwaway loopback HTTP listener with a scripted response."""

    def __init__(self, responder: Responder) -> None:
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": {key.lower(): value for key, value in self.headers.items()},
                    }
                )
                responder(self)

            def log_message(self, *_args: object) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "_Listener":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _json_response(handler: BaseHTTPRequestHandler, payload: object, *, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    try:
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        # Timeout tests intentionally close the client before this synthetic
        # response arrives. Do not emit a background traceback with host paths.
        return


def _raw_response(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/json",
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _trusted_responder(token: str, origin: str) -> Responder:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        challenge = desktop_identity.parse_desktop_challenge(
            handler.headers.get(desktop_identity.DESKTOP_CHALLENGE_HEADER)
        )
        if challenge is None:
            _json_response(handler, {"detail": "invalid desktop challenge"}, status=400)
            return
        _json_response(
            handler,
            {
                "identity_version": desktop_identity.DESKTOP_IDENTITY_VERSION,
                "proof": desktop_identity.desktop_identity_proof(token, origin, challenge),
            },
        )

    return respond


def _assert_probe_disclosed_nothing(listener: _Listener) -> None:
    assert listener.requests, "the launcher must actually probe the listener"
    for request in listener.requests:
        assert request["path"] == desktop_identity.DESKTOP_IDENTITY_PATH
        headers = request["headers"]
        assert API_TOKEN_HEADER.lower() not in headers
        assert "cookie" not in headers
        assert "authorization" not in headers
        rendered = json.dumps(request)
        assert TOKEN not in rendered
        assert OTHER_TOKEN not in rendered
        challenge = headers.get(desktop_identity.DESKTOP_CHALLENGE_HEADER.lower())
        assert desktop_identity.parse_desktop_challenge(challenge) is not None


def test_squatter_receives_only_a_random_challenge_and_is_refused() -> None:
    def squat(handler: BaseHTTPRequestHandler) -> None:
        # A squatter that mimics the old capability shape must still fail.
        _json_response(
            handler,
            {
                "cost_mode": "offline_only",
                "data_tier": "metadata",
                "network_inference": False,
                "raw_transcripts": False,
                "arbitrary_sql": False,
                "browser_session": True,
                "identity_version": desktop_identity.DESKTOP_IDENTITY_VERSION,
                "proof": "0" * 64,
            },
        )

    with _Listener(squat) as listener:
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is False
        _assert_probe_disclosed_nothing(listener)


def test_squatter_holding_a_different_token_is_refused() -> None:
    holder: dict[str, str] = {}

    def respond(handler: BaseHTTPRequestHandler) -> None:
        # The listener signs for its own origin but with the wrong secret.
        _trusted_responder(OTHER_TOKEN, holder["origin"])(handler)

    with _Listener(respond) as listener:
        holder["origin"] = listener.origin
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is False
        _assert_probe_disclosed_nothing(listener)


def test_squatter_replaying_a_captured_proof_is_refused() -> None:
    captured = desktop_identity.desktop_identity_proof(
        TOKEN, "http://127.0.0.1:1", bytes(32)
    )
    replay = {"identity_version": 1, "proof": captured}
    with _Listener(lambda handler: _json_response(handler, replay)) as listener:
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is False
        _assert_probe_disclosed_nothing(listener)


def test_squatter_relaying_to_a_real_instance_on_another_origin_is_refused() -> None:
    """A proof bound to another loopback origin cannot be forwarded."""

    with _Listener(lambda handler: None) as real_instance:
        real_origin = real_instance.origin
    # The squatter forwards challenges to a genuine instance elsewhere on
    # loopback and returns that instance's answer verbatim.
    with _Listener(_trusted_responder(TOKEN, real_origin)) as squatter:
        assert squatter.origin != real_origin
        assert desktop_overlay._verify_service_identity(squatter.origin, TOKEN) is False
        _assert_probe_disclosed_nothing(squatter)


def test_trusted_listener_is_accepted_without_seeing_the_token() -> None:
    holder: dict[str, str] = {}

    def respond(handler: BaseHTTPRequestHandler) -> None:
        _trusted_responder(TOKEN, holder["origin"])(handler)

    with _Listener(respond) as listener:
        holder["origin"] = listener.origin
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is True
        assert desktop_overlay._verify_service_identity(listener.origin, OTHER_TOKEN) is False
        _assert_probe_disclosed_nothing(listener)
        challenges = {
            request["headers"][desktop_identity.DESKTOP_CHALLENGE_HEADER.lower()]
            for request in listener.requests
        }
        assert len(challenges) == len(listener.requests), "each probe uses a new challenge"


def _malformed_responders() -> list[tuple[str, Responder]]:
    good_version = desktop_identity.DESKTOP_IDENTITY_VERSION
    return [
        ("html", lambda h: _raw_response(h, b"<html>hi</html>", content_type="text/html")),
        ("not-json", lambda h: _raw_response(h, b"{not json")),
        ("empty", lambda h: _raw_response(h, b"")),
        ("json-list", lambda h: _json_response(h, [good_version, "0" * 64])),
        ("missing-proof", lambda h: _json_response(h, {"identity_version": good_version})),
        ("null-proof", lambda h: _json_response(h, {"identity_version": good_version, "proof": None})),
        ("wrong-version", lambda h: _json_response(h, {"identity_version": 2, "proof": "0" * 64})),
        ("status-500", lambda h: _json_response(h, {"identity_version": good_version, "proof": "0" * 64}, status=500)),
        ("status-401", lambda h: _json_response(h, {"detail": "authentication required"}, status=401)),
        ("oversized", lambda h: _raw_response(h, b"[" + b"1," * 40_000 + b"1]")),
        ("invalid-utf8", lambda h: _raw_response(h, b'{"proof": "\xff\xfe"}')),
    ]


@pytest.mark.parametrize(("label", "responder"), _malformed_responders(), ids=lambda v: v if isinstance(v, str) else "")
def test_malformed_listener_answers_are_untrusted(label: str, responder: Responder) -> None:
    with _Listener(responder) as listener:
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is False, label
        _assert_probe_disclosed_nothing(listener)


def test_redirecting_listener_is_untrusted_and_not_followed() -> None:
    def redirect(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(302)
        handler.send_header("Location", "http://127.0.0.1:1/auth/desktop-identity")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with _Listener(redirect) as listener:
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is False
        assert len(listener.requests) == 1


def test_closed_port_is_simply_untrusted() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert desktop_overlay._verify_service_identity(f"http://127.0.0.1:{port}", TOKEN) is False


def test_slow_listener_is_untrusted_within_the_probe_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setattr(desktop_overlay, "_PROBE_TIMEOUT_SECONDS", 0.2)

    def stall(handler: BaseHTTPRequestHandler) -> None:
        time.sleep(0.6)
        _json_response(handler, {"identity_version": 1, "proof": "0" * 64})

    with _Listener(stall) as listener:
        started = time.monotonic()
        assert desktop_overlay._verify_service_identity(listener.origin, TOKEN) is False
        assert time.monotonic() - started < 3.0


# --------------------------------------------------------------------------- #
# The real service endpoint
# --------------------------------------------------------------------------- #


def _app(tmp_path, *, port: int = 18765, token: str = TOKEN):
    return create_app(
        settings=AppSettings(home=tmp_path, host="127.0.0.1", port=port),
        database=EmptyReadStore(),
        api_token=token,
    )


def test_service_answers_challenges_without_requiring_the_token(tmp_path) -> None:
    challenge = desktop_identity.new_desktop_challenge()
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:18765") as client:
        response = client.get(
            desktop_identity.DESKTOP_IDENTITY_PATH,
            headers={desktop_identity.DESKTOP_CHALLENGE_HEADER: challenge},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"identity_version", "proof"}
    assert payload["identity_version"] == desktop_identity.DESKTOP_IDENTITY_VERSION
    assert desktop_identity.verify_desktop_identity_proof(
        TOKEN, "http://127.0.0.1:18765", bytes.fromhex(challenge), payload["proof"]
    )
    # The answer is bound to the service's own configured origin, not to the
    # Host header a relaying squatter could forward.
    assert not desktop_identity.verify_desktop_identity_proof(
        TOKEN, "http://127.0.0.1:18766", bytes.fromhex(challenge), payload["proof"]
    )
    assert TOKEN not in response.text


def test_service_answer_is_bound_to_its_configured_port_and_token(tmp_path) -> None:
    challenge = desktop_identity.new_desktop_challenge()
    with TestClient(_app(tmp_path, port=18777, token=OTHER_TOKEN), base_url="http://127.0.0.1:18777") as client:
        payload = client.get(
            desktop_identity.DESKTOP_IDENTITY_PATH,
            headers={desktop_identity.DESKTOP_CHALLENGE_HEADER: challenge},
        ).json()
    assert desktop_identity.verify_desktop_identity_proof(
        OTHER_TOKEN, "http://127.0.0.1:18777", bytes.fromhex(challenge), payload["proof"]
    )
    assert not desktop_identity.verify_desktop_identity_proof(
        TOKEN, "http://127.0.0.1:18777", bytes.fromhex(challenge), payload["proof"]
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {desktop_identity.DESKTOP_CHALLENGE_HEADER: ""},
        {desktop_identity.DESKTOP_CHALLENGE_HEADER: "0" * 63},
        {desktop_identity.DESKTOP_CHALLENGE_HEADER: "A" * 64},
        {desktop_identity.DESKTOP_CHALLENGE_HEADER: "z" * 64},
    ],
)
def test_service_rejects_malformed_challenges(tmp_path, headers: dict[str, str]) -> None:
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:18765") as client:
        response = client.get(desktop_identity.DESKTOP_IDENTITY_PATH, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid desktop challenge"}


@pytest.mark.parametrize("host", ("localhost:18765", "[::1]:18765", "127.0.0.1:18766"))
def test_service_refuses_alias_or_mismatched_transport_authorities(
    tmp_path,
    host: str,
) -> None:
    challenge = desktop_identity.new_desktop_challenge()
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:18765") as client:
        response = client.get(
            desktop_identity.DESKTOP_IDENTITY_PATH,
            headers={
                "Host": host,
                desktop_identity.DESKTOP_CHALLENGE_HEADER: challenge,
            },
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "exact loopback authority required"}
    assert "proof" not in response.text


def test_service_refuses_cross_site_browser_probes(tmp_path) -> None:
    challenge = desktop_identity.new_desktop_challenge()
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:18765") as client:
        response = client.get(
            desktop_identity.DESKTOP_IDENTITY_PATH,
            headers={
                desktop_identity.DESKTOP_CHALLENGE_HEADER: challenge,
                "Sec-Fetch-Site": "cross-site",
            },
        )
    assert response.status_code == 403
    assert "proof" not in response.text


def test_service_identity_endpoint_grants_nothing(tmp_path) -> None:
    challenge = desktop_identity.new_desktop_challenge()
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:18765") as client:
        proof = client.get(
            desktop_identity.DESKTOP_IDENTITY_PATH,
            headers={desktop_identity.DESKTOP_CHALLENGE_HEADER: challenge},
        ).json()["proof"]
        # Neither the proof nor the challenge is a credential.
        assert client.get("/v1/capabilities", headers={API_TOKEN_HEADER: proof}).status_code == 401
        assert client.get("/v1/capabilities", headers={API_TOKEN_HEADER: challenge}).status_code == 401
        assert client.get("/v1/capabilities", headers={API_TOKEN_HEADER: TOKEN}).status_code == 200


def test_identity_handshake_is_not_part_of_the_public_schema(tmp_path) -> None:
    schema = _app(tmp_path).openapi()
    assert desktop_identity.DESKTOP_IDENTITY_PATH not in schema["paths"]
    assert "/auth/session" not in schema["paths"]


# --------------------------------------------------------------------------- #
# End-to-end: the launcher against the real service on a real loopback port
# --------------------------------------------------------------------------- #


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def served_app(tmp_path):
    import time

    import uvicorn

    port = _free_loopback_port()
    settings = AppSettings(home=tmp_path, host="127.0.0.1", port=port)
    app = create_app(settings=settings, database=EmptyReadStore(), api_token=TOKEN)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="error")
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    assert server.started
    try:
        yield settings
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_launcher_verifies_the_real_service_and_refuses_the_wrong_token(served_app: AppSettings) -> None:
    origin = desktop_overlay._loopback_origin(served_app.host, served_app.port)
    assert desktop_overlay._port_is_open(served_app.host, served_app.port) is True
    assert desktop_overlay._verify_service_identity(origin, TOKEN) is True
    assert desktop_overlay._verify_service_identity(origin, OTHER_TOKEN) is False


def test_launcher_attaches_to_a_trusted_service_without_owning_or_disclosing(
    served_app: AppSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ClosedEvent:
        def __init__(self) -> None:
            self.handlers: list[Callable[[], None]] = []

        def __iadd__(self, handler: Callable[[], None]):
            self.handlers.append(handler)
            return self

        def emit(self) -> None:
            for handler in tuple(self.handlers):
                handler()

    class Window:
        def __init__(self) -> None:
            self.events = type("Events", (), {"closed": ClosedEvent()})()

    class FakeWebview:
        def __init__(self) -> None:
            self.created: list[dict[str, Any]] = []
            self.window = Window()

        def create_window(self, *_args: object, **kwargs: object) -> object:
            self.created.append(dict(kwargs))
            return self.window

        def start(self, **_kwargs: object) -> None:
            self.window.events.closed.emit()

    webview = FakeWebview()
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(desktop_overlay, "load_or_create_api_token", lambda _path: TOKEN)
    monkeypatch.setattr(desktop_overlay, "_load_webview", lambda: webview)
    monkeypatch.setattr(
        desktop_overlay,
        "_start_owned_server",
        lambda _settings: pytest.fail("a trusted listener must be reused"),
    )
    monkeypatch.setattr(desktop_overlay._DesktopWindowApi, "_bind", lambda self, window: None)

    desktop_overlay.run_desktop_overlay(served_app)

    assert len(webview.created) == 1
    assert webview.created[0]["url"] == (
        f"http://127.0.0.1:{served_app.port}/overlay/model-ensemble"
    )
    assert TOKEN not in json.dumps(webview.created, default=str)


def test_launcher_refuses_a_squatter_before_rendering(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    with _Listener(lambda h: _json_response(h, {"identity_version": 1, "proof": "0" * 64})) as squatter:
        settings = AppSettings(home=tmp_path, host="127.0.0.1", port=squatter.port)
        monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
        monkeypatch.setattr(desktop_overlay, "load_or_create_api_token", lambda _path: TOKEN)
        monkeypatch.setattr(
            desktop_overlay,
            "_load_webview",
            lambda: pytest.fail("an untrusted listener must never be rendered"),
        )
        with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
            desktop_overlay.run_desktop_overlay(settings)
        assert caught.value.reason_code == "service_untrusted"
        assert str(caught.value) == desktop_overlay._FAILURE_MESSAGES["service_untrusted"]
        _assert_probe_disclosed_nothing(squatter)
