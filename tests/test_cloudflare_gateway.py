"""Origin authentication uses generated keys and fictional claims only."""

import importlib.util
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cloudflare_gateway", ROOT / "deploy/coolify/cloudflare_auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
ISSUER = "https://example.cloudflareaccess.com"
AUDIENCE = "a" * 64


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key, **changes):
    claims = {"iss": ISSUER, "aud": [AUDIENCE], "iat": int(time.time()) - 5, "exp": int(time.time()) + 60}
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "example-key"})


def verifier(key):
    return auth.AccessVerifier(ISSUER, AUDIENCE, keys=SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key()),
    ))


def test_valid_access_assertion_needs_no_basic_password(key):
    assert verifier(key).allows(token(key))


@pytest.mark.parametrize("changes", [
    {"iss": "https://other.example.test"}, {"aud": ["b" * 64]},
    {"exp": 1}, {"iat": 9_999_999_999}, {"nbf": 9_999_999_999},
    {"exp": None}, {"aud": None},
])
def test_wrong_application_issuer_or_time_is_rejected(key, changes):
    assert not verifier(key).allows(token(key, **changes))


def test_forged_signature_and_unsigned_token_are_rejected(key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert not verifier(key).allows(token(other))
    assert not verifier(key).allows(jwt.encode({"aud": [AUDIENCE]}, None, algorithm="none"))


@pytest.mark.parametrize("value", [None, "", "example-invalid-jwt", "x" * 16_385])
def test_missing_malformed_and_oversized_tokens_fail_closed(key, value):
    assert not verifier(key).allows(value)


def test_key_service_failure_fails_closed_without_logging(key, capsys):
    def unavailable(_):
        raise jwt.PyJWKClientConnectionError("example-private-diagnostic")
    check = auth.AccessVerifier(ISSUER, AUDIENCE, keys=SimpleNamespace(get_signing_key_from_jwt=unavailable))
    assert not check.allows(token(key))
    assert not capsys.readouterr().out


@pytest.mark.parametrize("issuer,audience", [
    ("http://example.cloudflareaccess.com", AUDIENCE),
    ("https://example.cloudflareaccess.com.attacker.example", AUDIENCE),
    (ISSUER + "/unexpected", AUDIENCE), (ISSUER, ""),
])
def test_only_configured_access_issuer_and_audience_are_accepted(issuer, audience):
    with pytest.raises(ValueError, match="cloudflare_configuration_invalid"):
        auth.AccessVerifier(issuer, audience)


def test_forward_auth_http_rejects_missing_and_duplicate_assertions_without_login_popup(key, capsys):
    server = ThreadingHTTPServer(("127.0.0.1", 0), auth.handler_for(verifier(key)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for assertions, expected in [([], 403), ([token(key)], 204), ([token(key), token(key)], 403)]:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.putrequest("GET", "/verify")
            for assertion in assertions:
                connection.putheader("Cf-Access-Jwt-Assertion", assertion)
            connection.endheaders()
            response = connection.getresponse()
            assert response.status == expected
            assert response.getheader("WWW-Authenticate") is None
            assert response.read() == b""
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert capsys.readouterr().err == ""


def test_cloudflare_mode_does_not_require_or_forward_basic_credentials(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "deploy/coolify"))
    from entrypoint import gateway_environment
    config = gateway_environment({
        "PROMPT_ENHANCER_AUTH_MODE": "cloudflare",
        "PROMPT_ENHANCER_PUBLIC_HOST": "prompt.example.test",
        "PROMPT_ENHANCER_ACCESS_ISSUER": ISSUER,
        "PROMPT_ENHANCER_ACCESS_AUDIENCE": AUDIENCE,
        "PROMPT_ENHANCER_WEB_USER": "example",
        "PROMPT_ENHANCER_WEB_PASSWORD_HASH": "example-unused",
    })
    assert config["PROMPT_ENHANCER_AUTH_CONFIG"] == "auth-cloudflare.caddy"
    assert "PROMPT_ENHANCER_WEB_USER" not in config
    assert "PROMPT_ENHANCER_WEB_PASSWORD_HASH" not in config
