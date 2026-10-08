"""Sanitized failures for social operations."""

from __future__ import annotations

from .contracts import SocialReasonCode


class SocialError(RuntimeError):
    """Base exception carrying only a closed reason code."""

    def __init__(self, reason: SocialReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


class SocialAuthorizationError(SocialError):
    pass


class SocialConflictError(SocialError):
    pass


class SocialCryptoUnavailableError(SocialError):
    pass


__all__ = [
    "SocialAuthorizationError",
    "SocialConflictError",
    "SocialCryptoUnavailableError",
    "SocialError",
]
