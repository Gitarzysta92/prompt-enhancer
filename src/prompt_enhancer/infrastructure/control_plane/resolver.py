"""The development principal resolver.

A credential is an opaque random string issued during provisioning and bound,
at issuance, to exactly one tenant, member, client, and device. Resolving it
returns that binding and nothing the caller asked for.

The resolver fails closed and uniformly: unknown, malformed, and revoked
credentials all resolve to ``None``, so failure modes cannot be used to
enumerate tenants or clients. It is still a development resolver — there is no
expiry, no rotation, no proof of possession, and no identity provider — and it
must not be mistaken for authentication of a person.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from ...application.control_plane import (
    ApiClientState,
    DeviceState,
    MembershipState,
    VerifiedIdentity,
)
from .development_store import (
    DevelopmentApiClientStore,
    DevelopmentCredentialStore,
    DevelopmentDeviceStore,
    DevelopmentDirectoryStore,
    credential_digest,
)


@dataclass(frozen=True, slots=True)
class StoredCredentialPrincipalResolver:
    """Resolve a presented credential to the identity it was issued for."""

    credentials: DevelopmentCredentialStore
    clients: DevelopmentApiClientStore
    devices: DevelopmentDeviceStore
    directory: DevelopmentDirectoryStore

    def resolve(self, credential: SecretStr) -> VerifiedIdentity | None:
        try:
            digest = credential_digest(credential)
        except ValueError:
            return None
        identity = self.credentials.identity_for(digest)
        if identity is None:
            return None

        # Authentication refuses what authorization would only deny later. The
        # policy re-checks all of this; doing it here means a revoked
        # credential stops being a credential rather than becoming a denial.
        client = self.clients.client(identity.organization_id, identity.client_id)
        if client is None or client.state is not ApiClientState.ACTIVE:
            return None
        if (
            client.user_id != identity.user_id
            or client.device_id != identity.device_id
        ):
            return None
        device = self.devices.device(identity.organization_id, identity.device_id)
        if device is None or device.state is not DeviceState.ACTIVE:
            return None
        if device.user_id != identity.user_id:
            return None
        membership = self.directory.membership(
            identity.organization_id, identity.user_id
        )
        if membership is None or membership.state is not MembershipState.ACTIVE:
            return None
        return identity


__all__ = ["StoredCredentialPrincipalResolver"]
