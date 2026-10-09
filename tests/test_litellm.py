"""Synthetic-only remote adapter boundaries. No gateway or provider is contacted."""
from datetime import UTC, datetime, timedelta
import json
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from prompt_enhancer.config import AppSettings, ConfigurationError, LiteLLMSettings
from prompt_enhancer.infrastructure.litellm import LiteLLMChat, MAX_RESPONSE_BYTES


def settings(**kwargs):
    return LiteLLMSettings(base_url="https://gateway.example.test/v1",
        credential="example-invalid-key", model="example-qwen", **kwargs)


@pytest.fixture
def certificate():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "example.test")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class Connection:
    def __init__(self, *, status=200, data=b'{"choices":[]}', peer=b"example-cert"):
        self.status, self.data, self.peer = status, data, peer
        self.requests = []
        self.sock = self
        self.closed = False
        self.connected = False

    def connect(self): self.connected = True
    def getpeercert(self, binary_form): return self.peer
    def request(self, *args):
        assert self.connected
        self.requests.append(args)
    def getresponse(self): return self
    def read(self, limit): return self.data[:limit]
    def close(self): self.closed = True


def install(monkeypatch, connection):
    created = []
    def factory(*args, **kwargs):
        created.append((args, kwargs))
        return connection
    monkeypatch.setattr("prompt_enhancer.infrastructure.litellm.http.client.HTTPSConnection", factory)
    return created


def test_adapter_uses_fixed_model_verified_tls_and_no_content_logging(monkeypatch):
    connection = Connection()
    created = install(monkeypatch, connection)
    body = json.dumps({"messages": [{"role": "user", "content": "Synthetic calculator test."}]}).encode()
    assert LiteLLMChat(settings(reasoning_effort="none"))("example-qwen", body)[0] == 200
    assert len(connection.requests) == 1 and connection.closed
    _, path, sent, headers = connection.requests[0]
    assert path == "/v1/chat/completions"
    payload = json.loads(sent)
    assert payload["reasoning_effort"] == "none"
    assert "chat_template_kwargs" not in payload
    assert payload["model"] == "example-qwen" and payload["no-log"] is True and payload["stream"] is False
    assert headers["Authorization"] == "Bearer example-invalid-key"
    assert headers["x-litellm-enable-message-redaction"] == "true"
    assert created[0][1]["context"].verify_mode == ssl.CERT_REQUIRED
    assert created[0][1]["context"].check_hostname


@pytest.mark.parametrize("matches", [True, False])
def test_private_pin_verified_before_authorization_is_sent(monkeypatch, certificate, matches):
    peer = ssl.PEM_cert_to_DER_cert(certificate) if matches else b"different-example-cert"
    connection = Connection(peer=peer)
    created = install(monkeypatch, connection)
    result = LiteLLMChat(settings(tls_cert_pem=certificate))(
        "example-qwen", b'{"messages":[]}')
    assert result[0] == (200 if matches else 502)
    assert len(connection.requests) == (1 if matches else 0)
    assert created[0][1]["context"].verify_mode == ssl.CERT_REQUIRED
    assert created[0][1]["context"].check_hostname
    assert connection.closed


@pytest.mark.parametrize("status,data", [(302, b"example-location"), (401, b"example-secret-error"),
                                            (200, b"x" * (MAX_RESPONSE_BYTES + 1))])
def test_redirects_errors_and_oversized_responses_are_not_returned(monkeypatch, status, data):
    connection = Connection(status=status, data=data)
    install(monkeypatch, connection)
    assert LiteLLMChat(settings())("example-qwen", b'{"messages":[]}') == (502, b"{}", "application/json")
    assert len(connection.requests) == 1 and connection.closed


def test_partial_or_unsafe_remote_configuration_fails_closed():
    assert AppSettings.from_env({"PROMPT_ENHANCER_HOME": "/example/app"}).prompt_check_litellm is None
    for env in ({"API_KEY": "example-invalid-key"},
                {"BASE_URL": "http://gateway.example.test", "API_KEY": "example-invalid-key", "MODEL": "example-qwen"}):
        with pytest.raises(ConfigurationError, match="litellm_configuration_invalid"):
            AppSettings.from_env({"PROMPT_ENHANCER_LITELLM_" + k: v for k, v in env.items()})
    assert "example-invalid-key" not in repr(settings())
    with pytest.raises(ValueError): settings(connect_address="invalid-address.example.test")


def test_private_address_retains_url_hostname_for_verified_tls(monkeypatch):
    from unittest.mock import Mock
    from prompt_enhancer.infrastructure.litellm import _PrivateHTTPSConnection
    raw = Mock()
    context = Mock(wraps=ssl.create_default_context())
    context.wrap_socket = Mock(return_value=Mock())
    dial = Mock(return_value=raw)
    monkeypatch.setattr("prompt_enhancer.infrastructure.litellm.socket.create_connection", dial)
    connection = _PrivateHTTPSConnection("gateway.example.test", 443, address="192.0.2.10",
        context=context, timeout=90)
    connection.connect()
    dial.assert_called_once_with(("192.0.2.10", 443), 90)
    context.wrap_socket.assert_called_once_with(raw, server_hostname="gateway.example.test")
    assert context._mock_wraps.check_hostname and context._mock_wraps.verify_mode == ssl.CERT_REQUIRED


def test_streaming_preserves_chunks_and_closes_owned_connection(monkeypatch):
    import io
    from prompt_enhancer.infrastructure.litellm import LiteLLMProvider
    connection = Connection()
    data = b'data: {"choices":[{"delta":{"content":"Example"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    stream = io.BytesIO(data)
    connection.getheader = lambda *args: "text/event-stream"
    connection.readline = stream.readline
    install(monkeypatch, connection)
    provider = LiteLLMProvider(settings())
    model = provider.models()[0]
    reply = provider.open_chat(model.id, b'{"messages":[{"role":"user","content":"Synthetic test"}]}')
    assert not connection.closed
    assert b"".join(reply.lines) == data
    assert connection.closed
    assert json.loads(connection.requests[0][2])["stream"] is True
    assert model.context_tokens is None and model.tools is None
    assert model.availability == "configured"


def test_stream_limits_are_enforced_without_echoing_upstream_data(monkeypatch):
    import io
    from prompt_enhancer.infrastructure.litellm import MAX_STREAM_LINE_BYTES
    connection = Connection(); connection.getheader = lambda *args: "text/event-stream"
    connection.readline = io.BytesIO(b"x" * (MAX_STREAM_LINE_BYTES + 1)).readline
    install(monkeypatch, connection)
    reply = LiteLLMChat(settings()).open_chat("example-qwen", b'{"messages":[]}')
    with pytest.raises(OSError, match="inference_stream_failed"):
        list(reply.lines)
    assert connection.closed


def test_cancel_before_headers_interrupts_only_that_request(monkeypatch):
    import threading
    from prompt_enhancer.application.runtime_cancellation import RuntimeCooperativeStop, runtime_request_scope
    connection = Connection(); waiting = threading.Event(); interrupted = threading.Event()
    connection.shutdown = lambda *args: interrupted.set()
    def response():
        waiting.set()
        assert interrupted.wait(3), "Synthetic cancellation did not interrupt socket"
        raise OSError("synthetic private upstream detail")
    connection.getresponse = response
    install(monkeypatch, connection)
    cancelled = threading.Event(); outcomes = []
    def run():
        try:
            with runtime_request_scope(cancelled): LiteLLMChat(settings()).open_chat("example-qwen", b'{"messages":[]}')
        except RuntimeCooperativeStop: outcomes.append("cancelled")
    thread = threading.Thread(target=run); thread.start()
    try:
        assert waiting.wait(2)
        cancelled.set(); thread.join(2)
        assert not thread.is_alive() and outcomes == ["cancelled"] and connection.closed
    finally:
        cancelled.set(); interrupted.set(); thread.join(3)


@pytest.mark.parametrize("phase", ["headers", "stream", "json"])
def test_owned_tls_socket_is_cancelable_before_headers_and_during_close_delimited_body(tmp_path, phase):
    """Real TLS and HTTP framing; only a generated certificate and fictional input."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from prompt_enhancer.application.runtime_cancellation import runtime_request_scope, RuntimeCooperativeStop
    entered, cancelled, disconnected, release = (threading.Event() for _ in range(4))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "gateway.example.test")])
    now = datetime.now(UTC)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("gateway.example.test")]), critical=False)
        .sign(key, hashes.SHA256())).public_bytes(serialization.Encoding.PEM)
    cert_file = tmp_path / "example-cert.pem"; cert_file.write_bytes(certificate)
    key_file = tmp_path / "example-key.pem"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    requests = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if phase != "headers":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if phase == "stream" else "application/json")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"data: " if phase == "stream" else b'{"choices":[')
                self.wfile.flush()
            entered.set()
            self.connection.settimeout(3)
            try:
                if not self.connection.recv(1): disconnected.set()
            except (OSError, ValueError):
                disconnected.set()
            release.wait(3)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}); server_thread.start()
    config = LiteLLMSettings(base_url=f"https://gateway.example.test:{server.server_port}/v1", connect_address="127.0.0.1",
        credential="example-invalid-key", model="example-qwen", tls_cert_pem=certificate.decode())
    outcomes = []
    def request():
        try:
            with runtime_request_scope(cancelled):
                if phase == "json": LiteLLMChat(config)("example-qwen", b'{"messages":[]}')
                else:
                    reply = LiteLLMChat(config).open_chat("example-qwen", b'{"messages":[]}')
                    if reply.lines is not None: list(reply.lines)
        except BaseException as error: outcomes.append(type(error))
    worker = threading.Thread(target=request); worker.start()
    try:
        assert entered.wait(2)
        cancelled.set()
        worker.join(1)
        assert not worker.is_alive(), "Stop left the owned TLS request blocked"
        assert outcomes == [RuntimeCooperativeStop]
        assert disconnected.wait(.5)
        assert len(requests) == 1 and requests[0]["model"] == "example-qwen"
    finally:
        cancelled.set(); release.set(); server.shutdown(); server.server_close()
        worker.join(4); server_thread.join(2)
