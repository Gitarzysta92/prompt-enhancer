"""Challenge/response identity proof for the native desktop launcher.

Before the Windows launcher renders anything it must decide whether the
process listening on the configured loopback port is this application.  The
launcher used to send the persistent local API token to whatever answered,
which hands that token to any port squatter.  Instead the launcher now sends
a fresh random challenge and only a service that already knows the token can
answer with the expected keyed digest.

Properties of the proof:

- the persistent token never leaves the launcher during verification;
- the digest is keyed by a value *derived* from the token, so the token itself
  is never used directly as an HMAC key for attacker-chosen messages;
- the digest is bound to the service's own canonical loopback origin, so a
  squatter cannot relay the challenge to a real instance on another port or
  another loopback address and forward the answer;
- every probe uses a new 256-bit challenge, so captured answers cannot be
  replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from typing import Sequence
from urllib.parse import urlsplit

from ...config import is_loopback_host


DESKTOP_IDENTITY_PATH = "/auth/desktop-identity"
DESKTOP_OWNED_INSTANCE_PATH_PREFIX = "/auth/desktop-owned-instance/"
DESKTOP_CHALLENGE_HEADER = "X-Prompt-Enhancer-Desktop-Challenge"
DESKTOP_IDENTITY_VERSION = 1
DESKTOP_CHALLENGE_BYTES = 32
_DESKTOP_OWNED_INSTANCE_BYTES = 32
_DESKTOP_OWNED_INSTANCE_LENGTH = 43
_DESKTOP_KEY_CONTEXT = b"prompt-enhancer/desktop-identity/v1"
_HEX_DIGITS = frozenset("0123456789abcdef")
_BASE64URL_DIGITS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def canonical_loopback_origin(host: str, port: int) -> str:
    """Return the single canonical origin string for a validated loopback host.

    Numeric origins double as the origin-binding context of the proof.  The
    ``localhost`` form is retained only for configuration display/validation;
    the launcher resolves it before probing and the service never signs it.
    """

    if not is_loopback_host(host) or not 1024 <= port <= 65535:
        raise ValueError("desktop identity requires a validated loopback service")
    normalized = host.casefold()
    if normalized == "localhost":
        authority = "localhost"
    else:
        address = ipaddress.ip_address(host)
        authority = (
            f"[{address.compressed}]" if address.version == 6 else address.compressed
        )
    return f"http://{authority}:{port}"


def exact_request_loopback_origin(
    host_header: str | None,
    server: object,
) -> str | None:
    """Return the request's exact numeric loopback transport origin.

    A desktop identity proof must not be issued for a DNS alias such as
    ``localhost``.  The same alias can resolve to both IPv4 and IPv6, which
    would let a listener on one address relay a challenge to a genuine service
    on the other.  The Host authority therefore has to name the numeric socket
    address and port observed by ASGI, exactly.  A relay that preserves Host
    reaches a different local socket and is refused; a relay that rewrites Host
    receives a proof for the rewritten origin, which the launcher rejects.

    ``server`` is deliberately typed as ``object`` because ASGI exposes it as
    an optional two-item sequence.  Malformed or implementation-specific
    values are simply untrusted.
    """

    if not isinstance(host_header, str) or not host_header:
        return None
    if any(character.isspace() for character in host_header):
        return None
    try:
        parsed = urlsplit(f"//{host_header}")
        requested_port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
        or requested_port is None
    ):
        return None
    try:
        requested_address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        # In particular, never sign for ``localhost``: it is not an exact
        # transport authority and may resolve to multiple loopback addresses.
        return None
    if not requested_address.is_loopback:
        return None

    if (
        not isinstance(server, Sequence)
        or isinstance(server, (str, bytes, bytearray))
        or len(server) != 2
    ):
        return None
    server_host, server_port = server
    if not isinstance(server_host, str) or not isinstance(server_port, int):
        return None
    try:
        server_address = ipaddress.ip_address(server_host)
    except ValueError:
        return None
    if (
        not server_address.is_loopback
        or server_address != requested_address
        or server_port != requested_port
    ):
        return None
    return canonical_loopback_origin(requested_address.compressed, requested_port)


def new_desktop_challenge() -> str:
    """Create a fresh lowercase-hex challenge for exactly one probe."""

    return secrets.token_hex(DESKTOP_CHALLENGE_BYTES)


def new_desktop_owned_instance_path() -> str:
    """Return an unguessable exact route for one launcher-owned server."""

    return (
        DESKTOP_OWNED_INSTANCE_PATH_PREFIX
        + secrets.token_urlsafe(_DESKTOP_OWNED_INSTANCE_BYTES)
    )


def is_desktop_owned_instance_path(value: object) -> bool:
    """Accept only the exact route shape produced by this module."""

    if not isinstance(value, str) or not value.startswith(
        DESKTOP_OWNED_INSTANCE_PATH_PREFIX
    ):
        return False
    identifier = value.removeprefix(DESKTOP_OWNED_INSTANCE_PATH_PREFIX)
    return len(identifier) == _DESKTOP_OWNED_INSTANCE_LENGTH and all(
        character in _BASE64URL_DIGITS for character in identifier
    )


def parse_desktop_challenge(value: str | None) -> bytes | None:
    """Accept only a full-length lowercase-hex challenge; anything else is None."""

    if not isinstance(value, str) or len(value) != DESKTOP_CHALLENGE_BYTES * 2:
        return None
    if any(character not in _HEX_DIGITS for character in value):
        return None
    return bytes.fromhex(value)


def _desktop_identity_key(token: str) -> bytes:
    return hmac.new(token.encode("utf-8"), _DESKTOP_KEY_CONTEXT, hashlib.sha256).digest()


def desktop_identity_proof(token: str, origin: str, challenge: bytes) -> str:
    """Compute the hex proof a trusted service returns for one challenge."""

    if len(challenge) != DESKTOP_CHALLENGE_BYTES:
        raise ValueError("desktop challenge has an invalid length")
    message = (
        str(DESKTOP_IDENTITY_VERSION).encode("ascii")
        + b"\x00"
        + origin.encode("ascii")
        + b"\x00"
        + challenge
    )
    return hmac.new(_desktop_identity_key(token), message, hashlib.sha256).hexdigest()


def verify_desktop_identity_proof(
    token: str,
    origin: str,
    challenge: bytes,
    proof: object,
) -> bool:
    """Constant-time comparison of a returned proof; malformed proofs are False."""

    if not isinstance(proof, str) or len(proof) != hashlib.sha256().digest_size * 2:
        return False
    if any(character not in _HEX_DIGITS for character in proof):
        return False
    expected = desktop_identity_proof(token, origin, challenge)
    return hmac.compare_digest(expected.encode("ascii"), proof.encode("ascii"))


__all__ = [
    "DESKTOP_CHALLENGE_BYTES",
    "DESKTOP_CHALLENGE_HEADER",
    "DESKTOP_IDENTITY_PATH",
    "DESKTOP_IDENTITY_VERSION",
    "DESKTOP_OWNED_INSTANCE_PATH_PREFIX",
    "canonical_loopback_origin",
    "desktop_identity_proof",
    "exact_request_loopback_origin",
    "is_desktop_owned_instance_path",
    "new_desktop_challenge",
    "new_desktop_owned_instance_path",
    "parse_desktop_challenge",
    "verify_desktop_identity_proof",
]
