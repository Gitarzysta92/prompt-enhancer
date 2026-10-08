"""Composition and out-of-band provisioning of the development control plane.

Provisioning lives here, not in the application layer, because creating a
tenant, a seat, a device, or a credential is exactly the part a real deployment
replaces with an identity provider and a billing system. Keeping it here means
the application layer never learns how principals come into existence, and it
makes the honest limitation visible: in this slice, provisioning is an
in-process administrative act with no authentication of its own.

Nothing is enabled by default. A freshly composed plane has no organizations,
no credentials, and no entitlement, so it authorizes nobody.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import secrets
import threading

from pydantic import SecretStr

from ...application.control_plane import (
    ApiClient,
    ApiClientState,
    ApiScope,
    ControlPlaneService,
    ControlPlaneStores,
    DeploymentProfile,
    Device,
    DeviceRegistration,
    DeviceVerificationKey,
    Entitlement,
    EntitlementTier,
    ManagerAccessGrant,
    Membership,
    MembershipState,
    Organization,
    OrganizationRole,
    SignatureAlgorithm,
    Team,
    VerifiedIdentity,
)
from .development_store import (
    DevelopmentApiClientStore,
    DevelopmentAggregateReleaseStore,
    DevelopmentAuditStore,
    DevelopmentCredentialStore,
    DevelopmentCursorStore,
    DevelopmentDeviceStore,
    DevelopmentDirectoryStore,
    DevelopmentEntitlementStore,
    DevelopmentManagerGrantStore,
    DevelopmentRecipientDeliveryStore,
    DevelopmentSnapshotStore,
    DevelopmentTransaction,
    RandomIdentifierFactory,
    credential_digest,
)
from .resolver import StoredCredentialPrincipalResolver
from .signatures import (
    ExplicitSignatureVerifierRegistry,
    development_verifier_registry,
)


DEVICE_KEY_FINGERPRINT_DOMAIN = b"prompt-enhancer/dev-device-key/v1"

DEFAULT_DEVICE_SCOPES: tuple[ApiScope, ...] = (
    ApiScope.SNAPSHOTS_PULL,
    ApiScope.SNAPSHOTS_PUSH,
)


def development_device_key(material: str | None = None) -> DeviceVerificationKey:
    """Create development verification material and its fingerprint.

    The fingerprint is domain-separated so it cannot be confused with any other
    digest in the system, and the default material is random so a fingerprint
    published in an envelope reveals nothing about the key behind it.
    """

    secret = material or secrets.token_hex(32)
    fingerprint = hashlib.sha256(
        DEVICE_KEY_FINGERPRINT_DOMAIN + b"\x00" + secret.encode("utf-8")
    ).hexdigest()
    return DeviceVerificationKey(
        algorithm=SignatureAlgorithm.DEVELOPMENT_HMAC_SHA256,
        key_fingerprint=fingerprint,
        material=secret,
    )


@dataclass(frozen=True, slots=True)
class ProvisionedSeat:
    """Everything one provisioned participant needs, issued once."""

    membership: Membership
    device: Device
    device_key: DeviceVerificationKey
    client: ApiClient
    credential: SecretStr
    identity: VerifiedIdentity


@dataclass(slots=True)
class DevelopmentControlPlane:
    """The development adapter set, its resolver, and the composed service."""

    directory: DevelopmentDirectoryStore
    devices: DevelopmentDeviceStore
    snapshots: DevelopmentSnapshotStore
    grants: DevelopmentManagerGrantStore
    clients: DevelopmentApiClientStore
    credentials: DevelopmentCredentialStore
    audit: DevelopmentAuditStore
    entitlements: DevelopmentEntitlementStore
    cursors: DevelopmentCursorStore
    aggregate_releases: DevelopmentAggregateReleaseStore
    recipient_deliveries: DevelopmentRecipientDeliveryStore
    identifiers: RandomIdentifierFactory
    verifiers: ExplicitSignatureVerifierRegistry
    transaction: DevelopmentTransaction
    resolver: StoredCredentialPrincipalResolver
    service: ControlPlaneService

    # -- tenant provisioning ----------------------------------------------

    def create_organization(
        self, *, now: datetime, sync_enabled: bool = False
    ) -> Organization:
        """Create a tenant. Synchronization stays off unless asked for.

        ``sync_enabled`` is the only way to satisfy the entitlement gate. There
        is no global development bypass: a tenant nobody deliberately enabled
        cannot publish or read, which is what makes the gate fail closed.
        """

        with self.transaction:
            organization = Organization(
                organization_id=self.identifiers.issue("organization"),
                created_at=now,
            )
            self.directory.organizations[organization.organization_id] = organization
            self.entitlements.entitlements[organization.organization_id] = Entitlement(
                organization_id=organization.organization_id,
                tier=(
                    EntitlementTier.TEAM_PREVIEW
                    if sync_enabled
                    else EntitlementTier.LOCAL_ONLY
                ),
                remote_sync_enabled=sync_enabled,
                evaluated_at=now,
            )
            return organization

    def set_sync_entitlement(
        self, organization_id: str, *, enabled: bool, now: datetime
    ) -> Entitlement:
        """Turn the synchronization entitlement on or off for one tenant."""

        with self.transaction:
            current = self.entitlements.entitlements.get(organization_id)
            if current is None:
                raise ValueError("unknown organization")
            updated = current.model_copy(
                update={"remote_sync_enabled": enabled, "evaluated_at": now}
            )
            self.entitlements.entitlements[organization_id] = updated
            return updated

    def create_team(self, organization_id: str, *, now: datetime) -> Team:
        with self.transaction:
            team = Team(
                team_id=self.identifiers.issue("team"),
                organization_id=organization_id,
                created_at=now,
            )
            self.directory.teams[(organization_id, team.team_id)] = team
            return team

    def add_member(
        self,
        organization_id: str,
        *,
        now: datetime,
        role: OrganizationRole = OrganizationRole.MEMBER,
        team_ids: tuple[str, ...] = (),
    ) -> Membership:
        with self.transaction:
            membership = Membership(
                membership_id=self.identifiers.issue("membership"),
                organization_id=organization_id,
                user_id=self.identifiers.issue("user"),
                role=role,
                state=MembershipState.ACTIVE,
                team_ids=tuple(sorted(team_ids)),
                created_at=now,
            )
            self.directory.memberships[
                (organization_id, membership.user_id)
            ] = membership
            return membership

    def provision_seat(
        self,
        organization_id: str,
        *,
        now: datetime,
        role: OrganizationRole = OrganizationRole.MEMBER,
        team_ids: tuple[str, ...] = (),
        scopes: tuple[ApiScope, ...] = DEFAULT_DEVICE_SCOPES,
        device_material: str | None = None,
    ) -> ProvisionedSeat:
        """Create a member, enrol their device, and issue one bound credential.

        The credential is returned exactly once and only its digest is stored.
        Because it is bound to this member and this device at issuance, holding
        it never lets the holder act as anybody else.
        """

        with self.transaction:
            membership = self.add_member(
                organization_id, now=now, role=role, team_ids=team_ids
            )
            key = development_device_key(device_material)
            device = self.devices.register(
                DeviceRegistration(
                    device_id=self.identifiers.issue("device"),
                    organization_id=organization_id,
                    user_id=membership.user_id,
                    key=key,
                    registered_at=now,
                )
            )
            client = ApiClient(
                client_id=self.identifiers.issue("client"),
                organization_id=organization_id,
                user_id=membership.user_id,
                device_id=device.device_id,
                scopes=tuple(sorted(set(scopes), key=lambda scope: scope.value)),
                state=ApiClientState.ACTIVE,
                created_at=now,
            )
            self.clients.clients[(organization_id, client.client_id)] = client
            credential = SecretStr(secrets.token_urlsafe(48))
            identity = VerifiedIdentity(
                organization_id=organization_id,
                user_id=membership.user_id,
                client_id=client.client_id,
                device_id=device.device_id,
                verified_at=now,
            )
            self.credentials.bind(credential_digest(credential), identity)
            return ProvisionedSeat(
                membership=membership,
                device=device,
                device_key=key,
                client=client,
                credential=credential,
                identity=identity,
            )

    def grant_manager_access(
        self,
        organization_id: str,
        *,
        manager_user_id: str,
        granted_at: datetime,
        expires_at: datetime,
        subject_user_id: str | None = None,
        team_id: str | None = None,
    ) -> ManagerAccessGrant:
        with self.transaction:
            grant = ManagerAccessGrant(
                grant_id=self.identifiers.issue("manager-grant"),
                organization_id=organization_id,
                manager_user_id=manager_user_id,
                subject_user_id=subject_user_id,
                team_id=team_id,
                granted_at=granted_at,
                expires_at=expires_at,
            )
            self.grants.grants.setdefault(organization_id, []).append(grant)
            return grant


def create_development_control_plane(
    clock: Callable[[], datetime] | None = None,
) -> DevelopmentControlPlane:
    """Compose the in-memory control plane used for development and tests."""

    lock = threading.RLock()
    identifiers = RandomIdentifierFactory()
    directory = DevelopmentDirectoryStore(lock=lock)
    devices = DevelopmentDeviceStore(lock=lock)
    snapshots = DevelopmentSnapshotStore(lock=lock, identifiers=identifiers)
    grants = DevelopmentManagerGrantStore(lock=lock)
    clients = DevelopmentApiClientStore(lock=lock)
    credentials = DevelopmentCredentialStore(lock=lock)
    audit = DevelopmentAuditStore(lock=lock)
    entitlements = DevelopmentEntitlementStore(lock=lock)
    cursors = DevelopmentCursorStore(lock=lock)
    aggregate_releases = DevelopmentAggregateReleaseStore(lock=lock)
    recipient_deliveries = DevelopmentRecipientDeliveryStore(
        lock=lock, identifiers=identifiers
    )
    verifiers = development_verifier_registry()
    transaction = DevelopmentTransaction(lock=lock)
    resolver = StoredCredentialPrincipalResolver(
        credentials=credentials,
        clients=clients,
        devices=devices,
        directory=directory,
    )
    service = ControlPlaneService(
        stores=ControlPlaneStores(
            directory=directory,
            devices=devices,
            snapshots=snapshots,
            grants=grants,
            clients=clients,
            audit=audit,
            entitlements=entitlements,
            cursors=cursors,
            aggregate_releases=aggregate_releases,
            credential_revocations=credentials,
            recipient_deliveries=recipient_deliveries,
        ),
        identifiers=identifiers,
        verifiers=verifiers,
        transaction=transaction,
        clock=clock or (lambda: datetime.now(UTC)),
        profile=DeploymentProfile.DEVELOPMENT,
    )
    return DevelopmentControlPlane(
        directory=directory,
        devices=devices,
        snapshots=snapshots,
        grants=grants,
        clients=clients,
        credentials=credentials,
        audit=audit,
        entitlements=entitlements,
        cursors=cursors,
        aggregate_releases=aggregate_releases,
        recipient_deliveries=recipient_deliveries,
        identifiers=identifiers,
        verifiers=verifiers,
        transaction=transaction,
        resolver=resolver,
        service=service,
    )


__all__ = [
    "DEFAULT_DEVICE_SCOPES",
    "DEVICE_KEY_FINGERPRINT_DOMAIN",
    "DevelopmentControlPlane",
    "ProvisionedSeat",
    "create_development_control_plane",
    "development_device_key",
]
