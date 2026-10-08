"""Verify Access signatures at the origin without another browser login."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re

import jwt


_ISSUER = re.compile(r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com\Z")
_AUDIENCE = re.compile(r"[a-f0-9]{64}\Z")


def configuration(environment):
    issuer = environment.get("PROMPT_ENHANCER_ACCESS_ISSUER", "")
    audience = environment.get("PROMPT_ENHANCER_ACCESS_AUDIENCE", "")
    if _ISSUER.fullmatch(issuer) is None or _AUDIENCE.fullmatch(audience) is None:
        raise ValueError("cloudflare_configuration_invalid")
    return issuer, audience


class AccessVerifier:
    def __init__(self, issuer, audience, *, keys=None):
        self.issuer, self.audience = configuration({
            "PROMPT_ENHANCER_ACCESS_ISSUER": issuer,
            "PROMPT_ENHANCER_ACCESS_AUDIENCE": audience,
        })
        self.keys = keys if keys is not None else jwt.PyJWKClient(
            issuer + "/cdn-cgi/access/certs", timeout=5, lifespan=300,
        )

    def allows(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 16_384:
            return False
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                return False
            if not 1 <= len(header["kid"]) <= 256:
                return False
            # Ignore all token-supplied key URLs; keys come only from the configured issuer.
            key = self.keys.get_signing_key_from_jwt(token).key
            jwt.decode(
                token, key, algorithms=["RS256"], audience=self.audience,
                issuer=self.issuer, options={"require": ["exp", "iat", "iss", "aud"]},
            )
            return True
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return False


def handler_for(verifier):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            tokens = self.headers.get_all("Cf-Access-Jwt-Assertion", [])
            accepted = self.path == "/verify" and len(tokens) == 1 and verifier.allows(tokens[0])
            self.send_response(204 if accepted else 403)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


def main():
    issuer, audience = configuration(os.environ)
    server = ThreadingHTTPServer(("127.0.0.1", 8081), handler_for(AccessVerifier(issuer, audience)))
    server.serve_forever()


if __name__ == "__main__":
    main()
