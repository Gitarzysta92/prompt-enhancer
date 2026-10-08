"""Trigger one reviewed Coolify application and check its deployed revision.

Secrets and response bodies never enter output. A queued deployment is not a
successful release. Redirects/proxies are disabled and each credential is sent
only to its configured destination. Run this after the tested image is pushed.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Mapping


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def checked_url(value: str, *, webhook: bool) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
        if (
            not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.fragment or any(character.isspace() for character in value)
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError
        if parsed.scheme != "https":
            # Allows an authenticated SSH tunnel on a private deployment runner.
            if not webhook or parsed.scheme != "http" or not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if webhook:
            query = urllib.parse.parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            if (
                parsed.path != "/api/v1/deploy" or set(query) - {"uuid", "force"}
                or len(query.get("uuid", [])) != 1
                or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", query["uuid"][0]) is None
                or query.get("force", ["false"]) != ["false"]
            ):
                raise ValueError
        elif parsed.path not in {"", "/"} or parsed.query:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("deployment_url_invalid") from None
    return value.rstrip("/") if not webhook else value


def configuration(env: Mapping[str, str]) -> tuple[str, str, str, str]:
    webhook = checked_url(env.get("COOLIFY_WEBHOOK", ""), webhook=True)
    public_url = checked_url(env.get("COOLIFY_PUBLIC_URL", ""), webhook=False)
    token = env.get("COOLIFY_TOKEN", "")
    revision = env.get("DEPLOY_REVISION", "")
    if not 16 <= len(token) <= 1024 or not token.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in token):
        raise ValueError("deployment_token_invalid")
    if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        raise ValueError("deployment_revision_invalid")
    return webhook, token, public_url, revision


def access_headers(env: Mapping[str, str], prefix: str, *, required: bool = False) -> dict[str, str]:
    access_id = env.get(prefix + "_ACCESS_CLIENT_ID", "")
    access_secret = env.get(prefix + "_ACCESS_CLIENT_SECRET", "")
    if bool(access_id) != bool(access_secret):
        raise ValueError("cloudflare_access_credentials_incomplete")
    if access_id:
        if any(not value.isascii() or len(value) > 1024 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) for value in (access_id, access_secret)):
            raise ValueError("cloudflare_access_credentials_invalid")
        return {"CF-Access-Client-Id": access_id, "CF-Access-Client-Secret": access_secret}
    if required:
        raise ValueError("cloudflare_access_credentials_required")
    return {}


def deploy(env: Mapping[str, str], *, opener=None, monotonic=time.monotonic, sleep=time.sleep) -> None:
    webhook, token, public_url, revision = configuration(env)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    headers = {"Authorization": f"Bearer {token}", **access_headers(env, "COOLIFY")}
    # Validate health authentication before triggering any deployment. This
    # profile keeps the entire app, including /health, behind Cloudflare Access.
    health_headers = {
        "Cache-Control": "no-cache",
        **access_headers(env, "PROMPT_ENHANCER", required=True),
    }
    request = urllib.request.Request(webhook, headers=headers, method="POST")
    # Exactly one trigger: retrying a timed-out trigger could deploy twice.
    with opener.open(request, timeout=30) as response:
        if response.status not in {200, 201, 202}:
            raise RuntimeError("deployment_not_accepted")
        payload = response.read(65_537)
    if len(payload) > 65_536:
        raise RuntimeError("deployment_response_invalid")
    try:
        result = json.loads(payload)
        deployments = result.get("deployments", [])
        if len(deployments) != 1 or not isinstance(deployments[0].get("deployment_uuid"), str) or not deployments[0]["deployment_uuid"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError, IndexError):
        raise RuntimeError("deployment_response_invalid") from None
    print("Coolify accepted one deployment; waiting for the expected revision.", flush=True)
    deadline = monotonic() + 600
    consecutive = 0
    while monotonic() < deadline:
        try:
            # Only the app's Access credential belongs on health requests.
            health = urllib.request.Request(public_url + "/health", headers=health_headers)
            with opener.open(health, timeout=10) as response:
                body = response.read(4097)
                ready = (
                    response.status == 200 and len(body) <= 4096
                    and response.headers.get("X-Prompt-Enhancer-Revision") == revision
                    and json.loads(body).get("status") == "ok"
                )
            consecutive = consecutive + 1 if ready else 0
            if consecutive >= 2:
                print("The expected revision passed two consecutive health checks.", flush=True)
                return
        except (OSError, ValueError, AttributeError, urllib.error.URLError):
            consecutive = 0
        sleep(5)
    raise RuntimeError("deployment_health_timeout")


def main() -> int:
    try:
        deploy(os.environ)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
        print("Deployment failed or remains unverified; inspect the Coolify deployment privately.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
