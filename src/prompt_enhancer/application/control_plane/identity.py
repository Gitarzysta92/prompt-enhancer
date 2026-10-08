"""Verified caller identity.

There is exactly one way for the control plane to learn who is calling: a
credential presented to a resolver, which returns the identity that credential
is *bound to*. Nothing a caller writes in a request body contributes to that
identity, so a caller cannot name another person, another device, or another
tenant by asking.

:class:`VerifiedIdentity` is the only identity type the service accepts. It is
deliberately not constructible from an HTTP body: the interface layer obtains
it from the resolver dependency and passes it on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from pydantic import SecretStr, field_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel


MAX_CREDENTIAL_CHARACTERS = 256
MIN_CREDENTIAL_CHARACTERS = 32


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identity fields must be HMAC pseudonyms")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("identity timestamps must be UTC")
    if value.microsecond:
        raise ValueError("identity timestamps are whole seconds")
    return value


class VerifiedIdentity(StrictModel):
    """The tenant, member, client, and device a credential is bound to.

    The device is mandatory. Every synchronization read and write is attributed
    to a device, so a stolen credential cannot be used to publish or read
    without also naming the device it was issued for, and revoking that device
    ends both.
    """

    organization_id: str
    user_id: str
    client_id: str
    device_id: str
    verified_at: datetime

    _identifiers = field_validator(
        "organization_id", "user_id", "client_id", "device_id"
    )(_pseudonym)
    _verified = field_validator("verified_at")(_utc)


class PrincipalResolver(Protocol):
    """Port that turns a presented credential into a bound identity.

    Implementations must fail closed: return ``None`` for an unknown,
    malformed, expired, or revoked credential, and never raise a distinguishing
    error, so a caller cannot use failure modes to enumerate tenants or
    clients.
    """

    def resolve(self, credential: SecretStr) -> VerifiedIdentity | None: ...


__all__ = [
    "MAX_CREDENTIAL_CHARACTERS",
    "MIN_CREDENTIAL_CHARACTERS",
    "PrincipalResolver",
    "VerifiedIdentity",
]
