"""Synthetic deployment evidence; never contacts a controller or provider."""

from __future__ import annotations

import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import urllib.error

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("coolify_release", "scripts/deploy_coolify.py")
hosted = load("coolify_entrypoint", "deploy/coolify/entrypoint.py")


def environment():
    return {
        "COOLIFY_WEBHOOK": "https://controller.example.test/api/v1/deploy?uuid=example-app&force=false",
        "COOLIFY_PUBLIC_URL": "https://prompt.example.test",
        "COOLIFY_TOKEN": "example-invalid-deploy-token",
        "PROMPT_ENHANCER_ACCESS_CLIENT_ID": "example-app.invalid",
        "PROMPT_ENHANCER_ACCESS_CLIENT_SECRET": "example-invalid-app-secret",
        "DEPLOY_REVISION": "a" * 40,
    }


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, revision=None):
        super().__init__(json.dumps(body).encode())
        self.status = status
        self.headers = {"X-Prompt-Enhancer-Revision": revision}


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def accepted():
    return Response({"deployments": [{"deployment_uuid": "example-deployment"}]})


def test_release_waits_for_two_consecutive_expected_revisions_without_sending_token_to_app():
    opener = Opener([
        accepted(), Response({"status": "ok"}, revision="b" * 40),
        Response({"status": "ok"}, revision="a" * 40),
        urllib.error.URLError("example temporary failure"),
        Response({"status": "ok"}, revision="a" * 40),
        Response({"status": "ok"}, revision="a" * 40),
    ])
    release.deploy(environment(), opener=opener, sleep=lambda _: None)
    assert len(opener.requests) == 6
    assert opener.requests[0].get_method() == "POST"
    assert all(request.get_method() == "GET" for request in opener.requests[1:])
    assert opener.requests[0].get_header("Authorization") == "Bearer example-invalid-deploy-token"
    assert all(request.get_header("Authorization") is None for request in opener.requests[1:])
    assert all(request.full_url == "https://prompt.example.test/health" for request in opener.requests[1:])


def test_timed_out_trigger_is_not_retried():
    opener = Opener([urllib.error.URLError("example timed out")])
    with pytest.raises(urllib.error.URLError):
        release.deploy(environment(), opener=opener)
    assert len(opener.requests) == 1


def test_controller_and_app_access_credentials_stay_at_their_destinations():
    opener = Opener([
        accepted(), Response({"status": "ok"}, revision="a" * 40),
        Response({"status": "ok"}, revision="a" * 40),
    ])
    env = {**environment(), "COOLIFY_ACCESS_CLIENT_ID": "example.invalid", "COOLIFY_ACCESS_CLIENT_SECRET": "example-invalid-service-secret"}
    release.deploy(env, opener=opener, sleep=lambda _: None)
    assert opener.requests[0].get_header("Cf-access-client-id") == "example.invalid"
    assert opener.requests[0].get_header("Cf-access-client-secret") == "example-invalid-service-secret"
    assert all(request.get_header("Cf-access-client-id") == "example-app.invalid" for request in opener.requests[1:])
    assert all(request.get_header("Cf-access-client-secret") == "example-invalid-app-secret" for request in opener.requests[1:])
    assert all(request.get_header("Authorization") is None for request in opener.requests[1:])


def test_app_access_credentials_are_not_sent_to_controller_without_access():
    opener = Opener([
        accepted(), Response({"status": "ok"}, revision="a" * 40),
        Response({"status": "ok"}, revision="a" * 40),
    ])
    release.deploy(environment(), opener=opener, sleep=lambda _: None)
    assert opener.requests[0].get_header("Cf-access-client-id") is None
    assert opener.requests[0].get_header("Cf-access-client-secret") is None
    assert all(request.get_header("Cf-access-client-id") == "example-app.invalid" for request in opener.requests[1:])


@pytest.mark.parametrize("access_id,access_secret", [
    ("", ""),
    ("example-app.invalid", ""),
    ("", "example-invalid-app-secret"),
    ("example-app.invalid", "example\ninvalid"),
])
def test_missing_or_invalid_app_access_fails_before_deployment(access_id, access_secret):
    opener = Opener([])
    env = {
        **environment(),
        "PROMPT_ENHANCER_ACCESS_CLIENT_ID": access_id,
        "PROMPT_ENHANCER_ACCESS_CLIENT_SECRET": access_secret,
    }
    with pytest.raises(ValueError, match="cloudflare_access_credentials"):
        release.deploy(env, opener=opener)
    assert opener.requests == []


@pytest.mark.parametrize("extra", [
    {"COOLIFY_ACCESS_CLIENT_ID": "example.invalid"},
    {"COOLIFY_ACCESS_CLIENT_SECRET": "example-invalid-service-secret"},
    {"COOLIFY_ACCESS_CLIENT_ID": "example.invalid", "COOLIFY_ACCESS_CLIENT_SECRET": "example\ninvalid"},
])
def test_incomplete_or_unsafe_access_credentials_fail_before_network(extra):
    opener = Opener([])
    with pytest.raises(ValueError, match="cloudflare_access_credentials"):
        release.deploy({**environment(), **extra}, opener=opener)
    assert opener.requests == []


def test_queued_deployment_without_healthy_expected_revision_fails():
    opener = Opener([accepted(), Response({"status": "ok"}, revision="b" * 40)])
    clock = iter([0, 1, 601])
    with pytest.raises(RuntimeError, match="deployment_health_timeout"):
        release.deploy(environment(), opener=opener, monotonic=lambda: next(clock), sleep=lambda _: None)


@pytest.mark.parametrize("body", [{}, {"deployments": []}, {"deployments": [{"message": "example rejected"}]}, {"deployments": [{"deployment_uuid": "one"}, {"deployment_uuid": "two"}]}])
def test_rejected_or_ambiguous_deployment_response_is_not_success(body):
    with pytest.raises(RuntimeError, match="deployment_response_invalid"):
        release.deploy(environment(), opener=Opener([Response(body)]))


@pytest.mark.parametrize("url", [
    "http://controller.example.test/api/v1/deploy?uuid=example",
    "https://example:example@controller.example.test/api/v1/deploy?uuid=example",
    "https://controller.example.test/api/v1/deploy?uuid=one,two",
    "https://controller.example.test/api/v1/deploy?uuid=one&uuid=two",
    "https://controller.example.test/api/v1/deploy?tag=example",
    "https://controller.example.test/api/v1/deploy?uuid=example&tag=",
    "https://controller.example.test/api/v1/deploy?uuid=example&force=true",
    "https://controller.example.test/api/v1/deploy?uuid=example#fragment",
])
def test_deployment_rejects_insecure_or_multiple_targets(url):
    with pytest.raises(ValueError, match="deployment_url_invalid"):
        release.checked_url(url, webhook=True)


def test_loopback_tunnel_only_allowed_for_controller():
    url = "http://127.0.0.1:18000/api/v1/deploy?uuid=example"
    assert release.checked_url(url, webhook=True) == url
    with pytest.raises(ValueError):
        release.checked_url("http://127.0.0.1:18000", webhook=False)


def test_redirects_do_not_forward_deployment_credentials():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.command, self.path))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/unexpected-redirect")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = environment()
        env["COOLIFY_WEBHOOK"] = f"http://127.0.0.1:{server.server_port}/api/v1/deploy?uuid=example"
        with pytest.raises(urllib.error.HTTPError) as error:
            release.deploy(env)
        assert error.value.code == 302
        assert received == [("POST", "/api/v1/deploy?uuid=example")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_errors_never_print_credentials_or_controller_response(monkeypatch, capsys):
    def fail(_):
        raise ValueError("example-private-response-and-token")
    monkeypatch.setattr(release, "deploy", fail)
    assert release.main() == 1
    assert "example-private" not in capsys.readouterr().err


def gateway_configuration():
    return {
        "PROMPT_ENHANCER_PUBLIC_HOST": "prompt.example.test",
        "PROMPT_ENHANCER_WEB_USER": "example",
        # Invalid synthetic credential, valid configuration shape only.
        "PROMPT_ENHANCER_WEB_PASSWORD_HASH": "$2a$14$" + "." * 53,
        "PROMPT_ENHANCER_REVISION": "a" * 40,
    }


@pytest.mark.parametrize("key,value", [
    ("PROMPT_ENHANCER_PUBLIC_HOST", "https://prompt.example.test"),
    ("PROMPT_ENHANCER_PUBLIC_HOST", "prompt.example.test\nrespond 200"),
    ("PROMPT_ENHANCER_WEB_USER", "example other"),
    ("PROMPT_ENHANCER_WEB_PASSWORD_HASH", "example-plaintext"),
    ("PROMPT_ENHANCER_WEB_PASSWORD_HASH", ""),
    ("PROMPT_ENHANCER_REVISION", "example; directive"),
])
def test_gateway_refuses_missing_credentials_and_configuration_injection(key, value):
    config = gateway_configuration()
    config[key] = value
    with pytest.raises(ValueError, match="hosted_configuration_invalid"):
        hosted.gateway_environment(config)


def test_server_environments_do_not_inherit_provider_or_controller_credentials(monkeypatch):
    monkeypatch.setenv("COOLIFY_TOKEN", "example-invalid-token")
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", "/example/private-data")
    monkeypatch.setenv("PROMPT_ENHANCER_HOST", "0.0.0.0")
    backend = hosted.backend_environment()
    assert backend["PROMPT_ENHANCER_HOST"] == "127.0.0.1"
    assert backend["PROMPT_ENHANCER_HOME"] == "/data/prompt-enhancer"
    assert backend["PROMPT_ENHANCER_SESSION_READER"] == "disabled"
    assert "COOLIFY_TOKEN" not in backend
    config = gateway_configuration()
    gateway = hosted.gateway_environment({**config, "COOLIFY_TOKEN": "example-invalid-token"})
    assert set(gateway) == {*config, "PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "PROMPT_ENHANCER_AUTH_CONFIG"}


def test_malformed_gateway_never_starts_backend(monkeypatch):
    monkeypatch.setattr(hosted.os, "environ", {})
    monkeypatch.setattr(hosted.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("backend started"))
    assert hosted.main() == 1


def test_failed_child_stops_sibling_and_redacts_output(monkeypatch, capsys):
    children = []
    class Child:
        terminated = False
        def poll(self):
            return 1 if self is children[0] else None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout):
            return 0
    def start(*args, **kwargs):
        assert kwargs["stdout"] == hosted.subprocess.DEVNULL
        assert kwargs["stderr"] == hosted.subprocess.DEVNULL
        child = Child()
        children.append(child)
        return child
    monkeypatch.setattr(hosted.os, "environ", gateway_configuration())
    monkeypatch.setattr(hosted.os, "umask", lambda _: None)
    monkeypatch.setattr(hosted.signal, "signal", lambda *args: None)
    monkeypatch.setattr(hosted.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(hosted.subprocess, "Popen", start)
    assert hosted.main() == 1
    assert children[1].terminated
    assert "example" not in capsys.readouterr().err


@pytest.mark.parametrize("status,payload,revision,expected", [
    (200, {"status": "ok"}, "a" * 40, 0),
    (503, {"status": "ok"}, "a" * 40, 1),
    (200, {"status": "starting"}, "a" * 40, 1),
    (200, {"status": "ok"}, "b" * 40, 1),
    (200, {"status": "ok", "extra": "x" * 4096}, "a" * 40, 1),
])
def test_container_readiness_requires_bounded_healthy_matching_revision(monkeypatch, status, payload, revision, expected):
    probe = load("coolify_healthcheck", "deploy/coolify/healthcheck.py")
    monkeypatch.setenv("PROMPT_ENHANCER_REVISION", "a" * 40)
    opener = Opener([Response(payload, status=status, revision=revision)])
    monkeypatch.setattr(probe.urllib.request, "build_opener", lambda *handlers: opener)
    assert probe.main() == expected
    assert opener.requests == ["http://127.0.0.1:8080/health"]


def test_container_readiness_failure_is_quiet(monkeypatch, capsys):
    probe = load("coolify_healthcheck", "deploy/coolify/healthcheck.py")
    monkeypatch.setenv("PROMPT_ENHANCER_REVISION", "a" * 40)
    opener = Opener([OSError("example-private-diagnostic")])
    monkeypatch.setattr(probe.urllib.request, "build_opener", lambda *handlers: opener)
    assert probe.main() == 1
    assert capsys.readouterr() == ("", "")
