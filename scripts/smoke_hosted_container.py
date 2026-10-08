"""Exercise a disposable hosted image with synthetic input and no host mounts."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


EXAMPLE_HOST = "prompt.example.test"
EXAMPLE_USER = "example"
EXAMPLE_PASSWORD = "example-only-disposable-test-password"


class SmokeCheckError(RuntimeError):
    """Contains only a fixed check name, never request or response content."""


def probe_gateway(base_url: str, revision: str, *, synthetic_api_token: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    basic = base64.b64encode(f"{EXAMPLE_USER}:{EXAMPLE_PASSWORD}".encode()).decode()
    public = {"Host": EXAMPLE_HOST, "X-Forwarded-Proto": "https"}
    authenticated = {**public, "Authorization": f"Basic {basic}"}

    def request(path, *, headers=None, body=None):
        outgoing = urllib.request.Request(
            base_url + path, headers=headers or {},
            data=json.dumps(body).encode() if body is not None else None,
        )
        if body is not None:
            outgoing.add_header("Content-Type", "application/json")
        try:
            response = opener.open(outgoing, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read(1_048_577)

    def require(condition, code):
        if not condition:
            raise SmokeCheckError(code)

    status, headers, body = request("/health")
    require(status == 200 and json.loads(body)["status"] == "ok", "health_failed")
    require(headers.get("X-Prompt-Enhancer-Revision") == revision, "revision_failed")
    require(request("/auth/session", headers=public)[0] == 401, "unauthenticated_bootstrap")
    require(request("/", headers={**authenticated, "Host": "foreign.example.test"})[0] == 400, "foreign_host")
    require(request("/", headers={**authenticated, "X-Forwarded-Proto": "http"})[0] == 403, "insecure_request")
    require(request("/auth/session", headers={**authenticated, "Origin": "https://foreign.example.test"})[0] == 403, "foreign_origin")
    for site in ("cross-site", "same-site"):
        require(request("/auth/session", headers={**authenticated, "Sec-Fetch-Site": site})[0] == 403, "foreign_fetch")
    status, headers, body = request("/auth/session", headers=authenticated)
    require(status == 200, "bootstrap_failed")
    session = json.loads(body)
    require(session["user_presence_confirmation_available"] is False, "native_authority_available")
    cookie = headers.get("Set-Cookie", "")
    require(all(flag in cookie.lower() for flag in ("httponly", "samesite=strict", "secure")), "cookie_flags")
    browser = {
        **authenticated, "Cookie": cookie.split(";", 1)[0],
        "Origin": f"https://{EXAMPLE_HOST}",
    }
    prompt = {"prompt": "Add a synthetic unit test for addition in the example calculator. Verify that two plus two equals four."}
    require(request("/v1/prompt-checks", headers=browser, body=prompt)[0] == 403, "missing_csrf")
    require(request("/v1/prompt-checks", headers={**browser, "X-Prompt-Enhancer-Token": synthetic_api_token}, body=prompt)[0] == 403, "token_bypass")
    browser["X-Prompt-Enhancer-CSRF"] = session["csrf_token"]
    require(request("/v1/prompt-checks", headers={key: value for key, value in browser.items() if key != "Origin"}, body=prompt)[0] == 403, "missing_origin")
    status, _, body = request("/v1/prompt-checks", headers=browser, body=prompt)
    require(status == 200 and json.loads(body)["contract_version"] == "prompt-check.v1", "prompt_check_failed")
    native_path = f"/v1/agent/projects/{'0' * 32}/sessions/{'0' * 32}/artifacts"
    require(request(native_path, headers={**browser, "X-Prompt-Enhancer-User-Presence": "example-invalid-presence"}, body={})[0] == 503, "native_approval_bypass")
    for path in ("/mcp", "/v1/integrations/example", "/v1/telemetry/example", "/otlp/v1/logs"):
        require(request(path, headers=browser)[0] == 403, "local_integration_exposed")
    status, _, body = request("/", headers=authenticated)
    require(status == 200 and b"<html" in body, "dashboard_missing")


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], check=True, timeout=120,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    return result.stdout.strip()


def main() -> int:
    container = None
    try:
        revision = os.environ.get("DEPLOY_REVISION", "")
        if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
            raise ValueError("revision_required")
        image = "prompt-enhancer:candidate"
        password_hash = docker(
            "run", "--rm", "--network", "none", "--entrypoint", "/usr/local/bin/caddy",
            image, "hash-password", "--plaintext", EXAMPLE_PASSWORD,
        )
        # Only generated, disposable test configuration is passed to Docker.
        container = "prompt-enhancer-smoke-" + uuid.uuid4().hex
        docker(
            "run", "--detach", "--rm", "--name", container,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--publish", "127.0.0.1::8080",
            "--tmpfs", "/data:uid=10001,gid=10001,mode=0700",
            "--env", f"PROMPT_ENHANCER_PUBLIC_HOST={EXAMPLE_HOST}",
            "--env", f"PROMPT_ENHANCER_WEB_USER={EXAMPLE_USER}",
            "--env", f"PROMPT_ENHANCER_WEB_PASSWORD_HASH={password_hash}", image,
        )
        binding = docker("port", container, "8080/tcp")
        if re.fullmatch(r"127\.0\.0\.1:[0-9]+", binding) is None:
            raise SmokeCheckError("unexpected_port_binding")
        base_url = "http://" + binding
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 90
        while True:
            try:
                with opener.open(base_url + "/health", timeout=3) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                try:
                    running = docker("inspect", "--format", "{{.State.Running}}", container)
                except subprocess.SubprocessError:
                    raise SmokeCheckError("container_unavailable") from None
                if running != "true":
                    raise SmokeCheckError("container_exited")
            if time.monotonic() >= deadline:
                raise SmokeCheckError("startup_timeout")
            time.sleep(1)
        # This token belongs only to the disposable synthetic test container.
        # Using its valid token proves the gateway prevents privileged bypass.
        synthetic_api_token = docker(
            "exec", container, "python", "-c",
            "from pathlib import Path; print(Path('/data/prompt-enhancer/api.token').read_text().strip())",
        )
        probe_gateway(base_url, revision, synthetic_api_token=synthetic_api_token)
        docker("exec", container, "python", "/app/deploy/healthcheck.py")
        print("Hosted image passed synthetic authentication, origin, CSRF, prompt-check and dashboard checks.")
        return 0
    except SmokeCheckError as error:
        print(f"Hosted container check failed: {error}; no image should be published.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        print("Hosted container smoke test failed; no image should be published.", file=sys.stderr)
        return 1
    finally:
        if container is not None:
            try:
                docker("rm", "--force", container)
            except (OSError, subprocess.SubprocessError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
