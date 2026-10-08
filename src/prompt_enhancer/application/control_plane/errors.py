"""Sanitized control-plane errors carrying closed reason codes only.

Errors never echo request input. A caller learns which rule rejected the
operation, not what the rejected value contained, so an error string can never
become an exfiltration channel for identifiers or content.
"""

from __future__ import annotations

from .contracts import ReasonCode


class ControlPlaneError(RuntimeError):
    """Base class for every rejected control-plane operation."""

    def __init__(self, reason: ReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


class CredentialRejectedError(ControlPlaneError):
    """The presented credential did not resolve to a bound identity."""

    def __init__(self) -> None:
        super().__init__(ReasonCode.CREDENTIAL_REJECTED)


class AuthorizationDeniedError(ControlPlaneError):
    """The default-deny policy refused the requested access."""


class EnvelopeRejectedError(ControlPlaneError):
    """A signed envelope failed verification, binding, or freshness checks."""


class EnvelopeConflictError(ControlPlaneError):
    """A known envelope identifier arrived with different content."""


class EnvelopeReplayedError(ControlPlaneError):
    """An envelope that was already consumed and deleted was offered again."""

    def __init__(self) -> None:
        super().__init__(ReasonCode.ENVELOPE_REPLAYED)


class CursorError(ControlPlaneError):
    """An acknowledgement moved backward or beyond a server offer."""


class EntitlementError(ControlPlaneError):
    """The tenant is not entitled to synchronize."""


class DirectoryNotFoundError(ControlPlaneError):
    """A referenced tenant, membership, device, or client does not exist.

    This deliberately shares the ``DEFAULT_DENY`` reason vocabulary so a
    probing caller cannot distinguish "absent" from "not yours".
    """


__all__ = [
    "AuthorizationDeniedError",
    "ControlPlaneError",
    "CredentialRejectedError",
    "CursorError",
    "DirectoryNotFoundError",
    "EntitlementError",
    "EnvelopeConflictError",
    "EnvelopeRejectedError",
    "EnvelopeReplayedError",
]
