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
