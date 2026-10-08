"""Control-plane use cases over a verified identity.

Every method takes a :class:`VerifiedIdentity` that a resolver produced from a
presented credential. The service never accepts an identity assertion from a
caller, and it re-resolves role, team, device, client, and entitlement from the
stores on every call, so a credential that was valid a moment ago stops working
the instant its membership, device, client, or entitlement changes.

Every mutating use case runs inside one transaction boundary, so a concurrent
caller cannot interleave with a sequence allocation, a fence write, or a
deletion.

Device enrolment and credential issuance are deliberately absent. They are
out-of-band provisioning acts in this slice, performed by the adapter's
administrative surface, because doing them over an authenticated API requires
the identity provider and credential lifecycle that do not exist yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .aggregation import MINIMUM_COHORT_SIZE, SuppressionReason, TeamAggregate
from .contracts import (
    CONTROL_PLANE_CONTRACT_VERSION,
    DEVELOPMENT_READINESS_GAPS,
    ApiClient,
    AuditAction,
    AuditDecision,
    AuditEvent,
    ControlPlaneReadiness,
    DeploymentProfile,
    Device,
    Entitlement,
    ManagerAccessGrant,
    Membership,
    MembershipState,
    ReadinessGap,
    ReasonCode,
)
from .envelopes import (
    SignedSnapshotEnvelope,
    canonical_envelope_bytes,
    envelope_digest,
)
from .errors import (
    AuthorizationDeniedError,
    CursorError,
    DirectoryNotFoundError,
    EntitlementError,
    EnvelopeConflictError,
    EnvelopeRejectedError,
    EnvelopeReplayedError,
)
from .identity import VerifiedIdentity
from .periods import ReportingBucket
from .policy import (
    AccessAction,
    AccessDecision,
    AccessPrincipal,
    AccessResource,
    authorize,
)
from .ports import (
    AggregateReleaseStore,
    ApiClientStore,
    AuditStore,
    CursorStore,
    CredentialRevocationStore,
    DeviceStore,
    DirectoryStore,
    EntitlementStore,
    IdentifierFactory,
    ManagerGrantStore,
    RecipientDeliveryStore,
    SignatureVerifierRegistry,
    SnapshotStore,
    TransactionBoundary,
)
from .sync import (
    DEFAULT_DELTA_PAGE_ITEMS,
    ENVELOPE_RESERVATION_TTL,
    MAX_DELTA_PAGE_ITEMS,
    DeletionReason,
    DeletionReceipt,
    DeltaPage,
    EnvelopeIdentifier,
    EnvelopeReservation,
    PushReceipt,
    SnapshotRecord,
    SyncAudience,
    SyncCursor,
    SyncItem,
)


MAX_ISSUE_SKEW = timedelta(minutes=5)
MAX_AUDIT_PAGE_ITEMS = 200

# Deletion stays available even when synchronization is not entitled: a tenant
# whose entitlement lapsed must still be able to erase what it published.
SYNC_ENTITLED_ACTIONS = frozenset(
    {
        AccessAction.PUSH_SNAPSHOT,
        AccessAction.PULL_DELTA,
        AccessAction.READ_TEAM_AGGREGATE,
    }
)


@dataclass(frozen=True, slots=True)
class ControlPlaneStores:
    """The adapter set composed behind the control-plane ports."""

    directory: DirectoryStore
    devices: DeviceStore
    snapshots: SnapshotStore
    grants: ManagerGrantStore
    clients: ApiClientStore
    audit: AuditStore
    entitlements: EntitlementStore
    cursors: CursorStore
    aggregate_releases: AggregateReleaseStore
    credential_revocations: CredentialRevocationStore
    recipient_deliveries: RecipientDeliveryStore


@dataclass(frozen=True, slots=True)
class ControlPlaneService:
    """Tenant-isolated synchronization of allowlisted metric snapshots."""

    stores: ControlPlaneStores
    identifiers: IdentifierFactory
    verifiers: SignatureVerifierRegistry
    transaction: TransactionBoundary
    clock: Callable[[], datetime]
    profile: DeploymentProfile = DeploymentProfile.DEVELOPMENT
    readiness_gaps: tuple[ReadinessGap, ...] = DEVELOPMENT_READINESS_GAPS
    minimum_cohort_size: int = MINIMUM_COHORT_SIZE

    # -- readiness ---------------------------------------------------------

    def readiness(self) -> ControlPlaneReadiness:
        """State plainly what this plane cannot yet do."""

        return ControlPlaneReadiness(
            contract_version=CONTROL_PLANE_CONTRACT_VERSION,
            profile=self.profile,
            gaps=self.readiness_gaps,
        )

    def _now(self) -> datetime:
        return self.clock().replace(microsecond=0)

    # -- principal resolution ---------------------------------------------

    def _membership(self, organization_id: str, user_id: str) -> Membership:
        membership = self.stores.directory.membership(organization_id, user_id)
        if membership is None:
            # Absent and foreign are answered identically so a probe cannot
            # enumerate another tenant's people.
            raise AuthorizationDeniedError(ReasonCode.DEFAULT_DENY)
        return membership

    def _entitlement(self, organization_id: str) -> Entitlement:
        entitlement = self.stores.entitlements.entitlement(organization_id)
        if entitlement is None:
            raise AuthorizationDeniedError(ReasonCode.ENTITLEMENT_MISSING)
        return entitlement

    def _principal(self, identity: VerifiedIdentity) -> AccessPrincipal:
        """Re-resolve every fact behind a verified credential.

        The resolver proved which membership, client, and device the credential
        is bound to. It did not prove they are still usable, so their current
        state is read here and judged by the policy.
        """

        membership = self._membership(identity.organization_id, identity.user_id)
        client = self.stores.clients.client(
            identity.organization_id, identity.client_id
        )
        device = self.stores.devices.device(
            identity.organization_id, identity.device_id
        )
        if client is None or device is None:
            raise AuthorizationDeniedError(ReasonCode.DEFAULT_DENY)
        # The credential binding is re-checked, not trusted: a client rebound or
        # a device reassigned between issuance and use must not be usable.
        if client.user_id != identity.user_id or client.device_id != identity.device_id:
            raise AuthorizationDeniedError(ReasonCode.DEFAULT_DENY)
        if device.user_id != identity.user_id:
            raise AuthorizationDeniedError(ReasonCode.DEVICE_NOT_BOUND)

        return AccessPrincipal(
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            role=membership.role,
            membership_state=membership.state,
            team_ids=membership.team_ids,
            device_id=device.device_id,
            device_state=device.state,
            client_id=client.client_id,
            client_state=client.state,
            client_scopes=client.scopes,
        )

    def _decide(
        self,
        principal: AccessPrincipal,
        resource: AccessResource,
        action: AccessAction,
        *,
        now: datetime,
    ) -> AccessDecision:
        grants = self.stores.grants.grants_for_manager(
            principal.organization_id, principal.user_id
        )
        return authorize(principal, resource, action, now=now, grants=grants)

    # -- audit -------------------------------------------------------------

    def _audit(
        self,
        *,
        organization_id: str,
        action: AuditAction,
        decision: AuditDecision,
        reason: ReasonCode,
        now: datetime,
        actor_user_id: str | None = None,
        actor_device_id: str | None = None,
        actor_client_id: str | None = None,
        subject_user_id: str | None = None,
        team_id: str | None = None,
        manager_grant_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            audit_id=self.identifiers.issue("audit"),
            organization_id=organization_id,
            sequence=self.stores.audit.next_sequence(organization_id),
            recorded_at=now,
            action=action,
            decision=decision,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_device_id=actor_device_id,
            actor_client_id=actor_client_id,
            subject_user_id=subject_user_id,
            team_id=team_id,
            manager_grant_id=manager_grant_id,
        )
        return self.stores.audit.append(event)

    def _audit_unresolved(
        self,
        principal: AccessPrincipal,
        *,
        action: AuditAction,
        now: datetime,
    ) -> None:
        """Record a fixed denial without persisting any unresolved request ID."""

        self._audit(
            organization_id=principal.organization_id,
            action=action,
            decision=AuditDecision.DENY,
            reason=ReasonCode.DEFAULT_DENY,
            now=now,
            actor_user_id=principal.user_id,
            actor_device_id=principal.device_id,
            actor_client_id=principal.client_id,
        )

    def _enforce(
        self,
        principal: AccessPrincipal,
        resource: AccessResource,
        action: AccessAction,
        *,
        denied_audit_action: AuditAction,
        now: datetime,
    ) -> AccessDecision:
        decision = self._decide(principal, resource, action, now=now)
        if not decision.allowed:
            # Resource identifiers on a denied request have not been resolved
            # to a tenant-owned row. Persist only credential-bound actor facts
            # and the closed reason; otherwise an attacker can use audit as an
            # arbitrary identifier sink (or cause later readers to trust it).
            self._audit(
                organization_id=principal.organization_id,
                action=denied_audit_action,
                decision=AuditDecision.DENY,
                reason=decision.reason,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=None,
                team_id=None,
            )
            raise AuthorizationDeniedError(decision.reason)
        if action in SYNC_ENTITLED_ACTIONS:
            entitlement = self._entitlement(principal.organization_id)
            if not entitlement.remote_sync_enabled:
                self._audit(
                    organization_id=principal.organization_id,
                    action=denied_audit_action,
                    decision=AuditDecision.DENY,
                    reason=ReasonCode.SYNC_NOT_ENTITLED,
                    now=now,
                    actor_user_id=principal.user_id,
                    actor_device_id=principal.device_id,
                    actor_client_id=principal.client_id,
                )
                raise EntitlementError(ReasonCode.SYNC_NOT_ENTITLED)
        if decision.manager_grant_id is not None:
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.MANAGER_ACCESS_USED,
                decision=AuditDecision.ALLOW,
                reason=decision.reason,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=resource.subject_user_id,
                team_id=resource.team_id,
                manager_grant_id=decision.manager_grant_id,
            )
        return decision

    # -- revocation --------------------------------------------------------

    def revoke_device(
        self, identity: VerifiedIdentity, device_id: str
    ) -> Device:
        """Revoke one device. Owners revoke their own; admins revoke any."""

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            device = self.stores.devices.device(
                identity.organization_id, device_id
            )
            if device is None:
                self._audit_unresolved(
                    principal, action=AuditAction.ACCESS_DENIED, now=now
                )
                raise DirectoryNotFoundError(ReasonCode.DEFAULT_DENY)
            is_own_device = device.user_id == principal.user_id
            action = (
                AccessAction.MANAGE_OWN_DEVICE
                if is_own_device
                else AccessAction.ADMINISTER_DIRECTORY
            )
            self._enforce(
                principal,
                AccessResource(
                    organization_id=identity.organization_id,
                    subject_user_id=device.user_id,
                ),
                action,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            revoked = self.stores.devices.revoke(
                identity.organization_id, device_id, now=now
            )
            self._revoke_clients_for_device(
                identity.organization_id, device_id, now=now
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.DEVICE_REVOKED,
                decision=AuditDecision.ALLOW,
                reason=(
                    ReasonCode.SELF_ACCESS
                    if is_own_device
                    else ReasonCode.ADMINISTRATIVE_ROLE
                ),
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=device.user_id,
            )
            return revoked

    def _revoke_clients_for_device(
        self, organization_id: str, device_id: str, *, now: datetime
    ) -> None:
        """Revoke every credential bound to a device that just lost trust."""

        device = self.stores.devices.device(organization_id, device_id)
        if device is None:
            return
        for client in self.stores.clients.clients_for_user(
            organization_id, device.user_id
        ):
            if client.device_id == device_id:
                if client.is_active():
                    self.stores.clients.revoke(
                        organization_id, client.client_id, now=now
                    )
                self.stores.credential_revocations.revoke_client(
                    organization_id, client.client_id, now=now
                )

    def revoke_api_client(
        self, identity: VerifiedIdentity, client_id: str
    ) -> ApiClient:
        """Revoke one client credential. Its holder loses access immediately."""

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            client = self.stores.clients.client(
                identity.organization_id, client_id
            )
            if client is None:
                self._audit_unresolved(
                    principal, action=AuditAction.ACCESS_DENIED, now=now
                )
                raise DirectoryNotFoundError(ReasonCode.DEFAULT_DENY)
            self._enforce(
                principal,
                AccessResource(
                    organization_id=identity.organization_id,
                    subject_user_id=client.user_id,
                ),
                AccessAction.ADMINISTER_DIRECTORY,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            revoked = self.stores.clients.revoke(
                identity.organization_id, client_id, now=now
            )
            self.stores.credential_revocations.revoke_client(
                identity.organization_id, client_id, now=now
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.API_CLIENT_REVOKED,
                decision=AuditDecision.ALLOW,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=client.user_id,
            )
            return revoked

    def revoke_manager_grant(
        self, identity: VerifiedIdentity, grant_id: str
    ) -> ManagerAccessGrant:
        """Revoke one tenant-owned manager grant as an administrator."""

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            grant = self.stores.grants.grant(identity.organization_id, grant_id)
            if grant is None:
                # Unknown and foreign identifiers are indistinguishable and
                # are never copied into audit evidence.
                self._audit_unresolved(
                    principal, action=AuditAction.ACCESS_DENIED, now=now
                )
                raise DirectoryNotFoundError(ReasonCode.DEFAULT_DENY)
            self._enforce(
                principal,
                AccessResource(organization_id=identity.organization_id),
                AccessAction.ADMINISTER_DIRECTORY,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            revoked = self.stores.grants.revoke(
                identity.organization_id, grant.grant_id, now=now
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.MANAGER_GRANT_REVOKED,
                decision=AuditDecision.ALLOW,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                manager_grant_id=grant.grant_id,
            )
            return revoked

    def revoke_membership(
        self, identity: VerifiedIdentity, user_id: str
    ) -> DeletionReceipt:
        """Revoke a membership and propagate the removal of its snapshots.

        Revocation is not only a flag. Every device and credential the person
        held stops working, their published snapshots become tombstones, and
        the deletion fence stops any of it from being republished.
        """

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            membership = self.stores.directory.membership(
                identity.organization_id, user_id
            )
            if membership is None:
                self._audit_unresolved(
                    principal, action=AuditAction.ACCESS_DENIED, now=now
                )
                raise DirectoryNotFoundError(ReasonCode.DEFAULT_DENY)
            self._enforce(
                principal,
                AccessResource(
                    organization_id=identity.organization_id,
                    subject_user_id=membership.user_id,
                ),
                AccessAction.ADMINISTER_DIRECTORY,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            self.stores.directory.revoke_membership(
                membership.organization_id, membership.user_id, now=now
            )
            for device in self.stores.devices.devices_for_user(
                membership.organization_id, membership.user_id
            ):
                if device.is_active():
                    self.stores.devices.revoke(
                        device.organization_id, device.device_id, now=now
                    )
            for client in self.stores.clients.clients_for_user(
                membership.organization_id, membership.user_id
            ):
                if client.is_active():
                    self.stores.clients.revoke(
                        client.organization_id, client.client_id, now=now
                    )
                self.stores.credential_revocations.revoke_client(
                    client.organization_id, client.client_id, now=now
                )
            tombstones = self.stores.snapshots.delete_subject(
                membership.organization_id,
                membership.user_id,
                reason=DeletionReason.MEMBERSHIP_REVOKED,
                now=now,
            )
            self.stores.recipient_deliveries.enqueue_tombstones(
                membership.organization_id, tombstones
            )
            self.stores.aggregate_releases.invalidate_organization(
                membership.organization_id
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.MEMBERSHIP_REVOKED,
                decision=AuditDecision.ALLOW,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=membership.user_id,
            )
            return DeletionReceipt(
                organization_id=membership.organization_id,
                subject_user_id=membership.user_id,
                deleted_snapshot_count=len(tombstones),
            )

    # -- publication -------------------------------------------------------

    def issue_envelope_identifier(
        self, identity: VerifiedIdentity
    ) -> EnvelopeIdentifier:
        """Return the producer's one short-lived opaque reservation.

        Repeated calls during its lifetime return the same identifier. This
        bounds reserve-without-consumption grinding: a successful push consumes
        the slot, after which a new issue call returns a fresh identifier. The
        development recipient payload still carries the accepted envelope, so
        this is not a claim that all identifier-based signalling is impossible.
        Issuance and push audit events never record the caller-visible ID.
        """

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            self._enforce(
                principal,
                AccessResource(
                    organization_id=principal.organization_id,
                    subject_user_id=principal.user_id,
                ),
                AccessAction.PUSH_SNAPSHOT,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            existing = self.stores.snapshots.active_envelope_reservation(
                principal.organization_id,
                principal.user_id,
                principal.client_id,
                principal.device_id,
                now=now,
            )
            if existing is not None:
                return EnvelopeIdentifier(envelope_id=existing.envelope_id)
            reservation = EnvelopeReservation(
                envelope_id=self.identifiers.issue("envelope"),
                organization_id=principal.organization_id,
                subject_user_id=principal.user_id,
                client_id=principal.client_id,
                device_id=principal.device_id,
                subject_epoch=self.stores.snapshots.subject_deletion_generation(
                    principal.organization_id, principal.user_id
                ),
                issued_at=now,
                expires_at=now + ENVELOPE_RESERVATION_TTL,
            )
            self.stores.snapshots.reserve_envelope(reservation)
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.ENVELOPE_IDENTIFIER_ISSUED,
                decision=AuditDecision.ALLOW,
                reason=ReasonCode.SELF_ACCESS,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=principal.user_id,
            )
            return EnvelopeIdentifier(envelope_id=reservation.envelope_id)

    def _reject_envelope(
        self,
        principal: AccessPrincipal,
        *,
        reason: ReasonCode,
        subject_user_id: str,
        now: datetime,
    ) -> None:
        self._audit(
            organization_id=principal.organization_id,
            action=AuditAction.SNAPSHOT_REJECTED,
            decision=AuditDecision.DENY,
            reason=reason,
            now=now,
            actor_user_id=principal.user_id,
            actor_device_id=principal.device_id,
            actor_client_id=principal.client_id,
            subject_user_id=subject_user_id,
        )

    def _envelope_rejection(
        self,
        principal: AccessPrincipal,
        signed: SignedSnapshotEnvelope,
        *,
        now: datetime,
    ) -> ReasonCode | None:
        """Return why this envelope cannot be accepted, or ``None`` if it can.

        Principal and reservation binding are checked by ``push`` before this
        method. Device identity comes only from that principal, never from the
        envelope, and the caller learns one closed reason rather than a
        diagnosis of a forgery.
        """

        envelope = signed.envelope
        signature = signed.signature
        if envelope.team_id is not None and envelope.team_id not in principal.team_ids:
            return ReasonCode.TEAM_MEMBERSHIP_REQUIRED

        device = self.stores.devices.device(
            principal.organization_id, principal.device_id
        )
        device_key = self.stores.devices.verification_key(
            principal.organization_id, principal.device_id
        )
        if device is None or device_key is None:
            return ReasonCode.DEVICE_NOT_BOUND
        if (
            envelope.issued_at < device.registered_at
            or envelope.issued_at > now + MAX_ISSUE_SKEW
        ):
            return ReasonCode.ENVELOPE_NOT_FRESH
        if signature.key_fingerprint != device_key.key_fingerprint:
            return ReasonCode.KEY_MISMATCH

        verifier = self.verifiers.verifier(signature.algorithm)
        if verifier is None or device_key.algorithm is not signature.algorithm:
            return ReasonCode.UNSUPPORTED_ALGORITHM
        if not verifier.verify(
            device_key, canonical_envelope_bytes(envelope), signature.value
        ):
            return ReasonCode.SIGNATURE_INVALID
        return None

    def push(
        self, identity: VerifiedIdentity, signed: SignedSnapshotEnvelope
    ) -> PushReceipt:
        """Accept one signed envelope at most once, ever.

        The consumed-envelope fence outlives deletion. Resending an identical
        envelope that is still stored is a no-op reporting the original
        position; resending one whose data was deleted is a replay and is
        refused, because accepting it would silently undo an erasure. Reusing an
        identifier with different content is a conflict.
        """

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            envelope = signed.envelope
            self._enforce(
                principal,
                AccessResource(
                    organization_id=principal.organization_id,
                    subject_user_id=principal.user_id,
                    team_id=envelope.team_id,
                    visibility=envelope.visibility,
                ),
                AccessAction.PUSH_SNAPSHOT,
                denied_audit_action=AuditAction.SNAPSHOT_REJECTED,
                now=now,
            )

            consumed = self.stores.snapshots.consumed_envelope(
                principal.organization_id, envelope.envelope_id
            )
            reservation = self.stores.snapshots.envelope_reservation(
                principal.organization_id, envelope.envelope_id
            )
            reservation_matches = reservation is not None and (
                reservation.subject_user_id == principal.user_id
                and reservation.client_id == principal.client_id
                and reservation.device_id == principal.device_id
            )
            consumed_matches = consumed is not None and (
                consumed.subject_user_id == principal.user_id
                and consumed.client_id == principal.client_id
                and consumed.device_id == principal.device_id
            )
            # A consumed fence retains the owner binding after the short-lived
            # reservation is removed. Nobody else can use a known identifier
            # as an existence oracle or inject it into audit.
            if not reservation_matches and not consumed_matches:
                self._reject_envelope(
                    principal,
                    reason=ReasonCode.ENVELOPE_ID_UNREGISTERED,
                    subject_user_id=principal.user_id,
                    now=now,
                )
                raise EnvelopeRejectedError(ReasonCode.ENVELOPE_ID_UNREGISTERED)

            if reservation is not None and not reservation.is_active(now):
                self._reject_envelope(
                    principal,
                    reason=ReasonCode.ENVELOPE_RESERVATION_EXPIRED,
                    subject_user_id=principal.user_id,
                    now=now,
                )
                raise EnvelopeRejectedError(
                    ReasonCode.ENVELOPE_RESERVATION_EXPIRED
                )
            if reservation is not None and envelope.issued_at < reservation.issued_at:
                self._reject_envelope(
                    principal,
                    reason=ReasonCode.ENVELOPE_NOT_FRESH,
                    subject_user_id=principal.user_id,
                    now=now,
                )
                raise EnvelopeRejectedError(ReasonCode.ENVELOPE_NOT_FRESH)
            if (
                reservation is not None
                and reservation.subject_epoch
                != self.stores.snapshots.subject_deletion_generation(
                    principal.organization_id, principal.user_id
                )
            ):
                self._reject_envelope(
                    principal,
                    reason=ReasonCode.ENVELOPE_REPLAYED,
                    subject_user_id=principal.user_id,
                    now=now,
                )
                raise EnvelopeReplayedError()

            rejection = self._envelope_rejection(principal, signed, now=now)
            if rejection is not None:
                self._reject_envelope(
                    principal,
                    reason=rejection,
                    subject_user_id=principal.user_id,
                    now=now,
                )
                raise EnvelopeRejectedError(rejection)

            digest = envelope_digest(envelope)
            if consumed is not None:
                if consumed.content_digest != digest:
                    self._reject_envelope(
                        principal,
                        reason=ReasonCode.ENVELOPE_CONFLICT,
                        subject_user_id=principal.user_id,
                        now=now,
                    )
                    raise EnvelopeConflictError(ReasonCode.ENVELOPE_CONFLICT)
                if consumed.deleted:
                    self._reject_envelope(
                        principal,
                        reason=ReasonCode.ENVELOPE_REPLAYED,
                        subject_user_id=principal.user_id,
                        now=now,
                    )
                    raise EnvelopeReplayedError()
                return PushReceipt(
                    envelope_id=envelope.envelope_id,
                    snapshot_id=consumed.snapshot_id,
                    content_digest=consumed.content_digest,
                    duplicate=True,
                )

            record = self.stores.snapshots.append_snapshot(
                SnapshotRecord(
                    snapshot_id=self.identifiers.issue("snapshot"),
                    organization_id=principal.organization_id,
                    subject_user_id=principal.user_id,
                    device_id=principal.device_id,
                    sequence=self.stores.snapshots.next_sequence(
                        principal.organization_id
                    ),
                    accepted_at=now,
                    content_digest=digest,
                    envelope=envelope,
                )
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.SNAPSHOT_PUSHED,
                decision=AuditDecision.ALLOW,
                reason=ReasonCode.SELF_ACCESS,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=principal.user_id,
                team_id=envelope.team_id,
            )
            return PushReceipt(
                envelope_id=record.envelope.envelope_id,
                snapshot_id=record.snapshot_id,
                content_digest=record.content_digest,
                duplicate=False,
            )

    # -- delta synchronization --------------------------------------------

    def pull(
        self,
        identity: VerifiedIdentity,
        *,
        acknowledge_through: int | None = None,
        limit: int = DEFAULT_DELTA_PAGE_ITEMS,
    ) -> DeltaPage:
        """Return the next ordered page the caller is allowed to see.

        Delivery is at-least-once. The server stores a monotonic checkpoint for
        the authenticated client/device pair and redelivers its unacknowledged
        window. Acknowledgement is accepted only through a sequence previously
        offered to that same pair. Every item is authorized individually.
        """

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            self._enforce(
                principal,
                AccessResource(organization_id=identity.organization_id),
                AccessAction.PULL_DELTA,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )

            checkpoint = self.stores.cursors.checkpoint(
                principal.organization_id,
                principal.client_id,
                principal.device_id,
            )
            if acknowledge_through is not None:
                if acknowledge_through < checkpoint.acknowledged_sequence:
                    raise CursorError(ReasonCode.CURSOR_REGRESSION)
                if acknowledge_through > checkpoint.offered_sequence:
                    raise CursorError(ReasonCode.CURSOR_NOT_OFFERED)
                checkpoint = self.stores.cursors.acknowledge(
                    principal.organization_id,
                    principal.client_id,
                    principal.device_id,
                    sequence=acknowledge_through,
                )

            page_size = max(1, min(limit, MAX_DELTA_PAGE_ITEMS))

            def finish_page(
                items: tuple[SyncItem, ...], *, has_more: bool
            ) -> DeltaPage:
                next_sequence = (
                    items[-1].sequence
                    if items
                    else checkpoint.acknowledged_sequence
                )
                offered = self.stores.cursors.offer(
                    principal.organization_id,
                    principal.client_id,
                    principal.device_id,
                    sequence=next_sequence,
                )
                self.stores.recipient_deliveries.mark_delivered(
                    principal.organization_id,
                    principal.client_id,
                    principal.device_id,
                    items,
                )
                if items:
                    self._audit(
                        organization_id=principal.organization_id,
                        action=AuditAction.DELTA_PULLED,
                        decision=AuditDecision.ALLOW,
                        reason=ReasonCode.TENANT_MEMBERSHIP,
                        now=now,
                        actor_user_id=principal.user_id,
                        actor_device_id=principal.device_id,
                        actor_client_id=principal.client_id,
                    )
                return DeltaPage(
                    organization_id=principal.organization_id,
                    items=items,
                    acknowledged_cursor=SyncCursor(
                        sequence=offered.acknowledged_sequence
                    ),
                    next_cursor=SyncCursor(sequence=next_sequence),
                    has_more=has_more,
                )

            # Recipient-local entries include unacknowledged offers and opaque
            # deletion handles queued from the delivery ledger. Serve these
            # first; they are already authorized for this exact client/device.
            pending = self.stores.recipient_deliveries.read(
                principal.organization_id,
                principal.client_id,
                principal.device_id,
                sequence=checkpoint.acknowledged_sequence,
                limit=page_size + 1,
            )
            if pending:
                return finish_page(
                    pending[:page_size], has_more=len(pending) > page_size
                )

            source_position = self.stores.recipient_deliveries.source_position(
                principal.organization_id,
                principal.client_id,
                principal.device_id,
            )
            delivered: list[SyncItem] = []
            audited_grants: set[str] = set()
            has_more = False
            exhausted = False
            while not exhausted and not has_more:
                candidates = self.stores.snapshots.read_since(
                    principal.organization_id,
                    sequence=source_position,
                    limit=MAX_DELTA_PAGE_ITEMS,
                )
                if not candidates:
                    break
                exhausted = len(candidates) < MAX_DELTA_PAGE_ITEMS
                for item in candidates:
                    # Global tombstones never enter a public stream. Recipient
                    # tombstones are queued directly from proven delivery rows.
                    if item.snapshot is None:
                        source_position = item.sequence
                        self.stores.recipient_deliveries.advance_source(
                            principal.organization_id,
                            principal.client_id,
                            principal.device_id,
                            sequence=source_position,
                        )
                        continue
                    decision = self._decide(
                        principal,
                        AccessResource(
                            organization_id=principal.organization_id,
                            subject_user_id=item.subject_user_id,
                            team_id=item.team_id,
                            visibility=item.visibility,
                        ),
                        AccessAction.READ_SNAPSHOT,
                        now=now,
                    )
                    if decision.allowed and len(delivered) >= page_size:
                        # Authorized look-ahead only. Do not advance the hidden
                        # source position, so the item is reconsidered after the
                        # offered local page is acknowledged.
                        has_more = True
                        break
                    source_position = item.sequence
                    self.stores.recipient_deliveries.advance_source(
                        principal.organization_id,
                        principal.client_id,
                        principal.device_id,
                        sequence=source_position,
                    )
                    if not decision.allowed:
                        # This hidden source checkpoint may advance over denied
                        # rows; the visible recipient cursor does not.
                        continue
                    delivered.append(
                        self.stores.recipient_deliveries.enqueue_snapshot(
                            principal.organization_id,
                            principal.client_id,
                            principal.device_id,
                            item.snapshot,
                        )
                    )
                    if (
                        decision.manager_grant_id is not None
                        and item.subject_user_id not in audited_grants
                    ):
                        audited_grants.add(item.subject_user_id)
                        self._audit(
                            organization_id=principal.organization_id,
                            action=AuditAction.MANAGER_ACCESS_USED,
                            decision=AuditDecision.ALLOW,
                            reason=decision.reason,
                            now=now,
                            actor_user_id=principal.user_id,
                            actor_device_id=principal.device_id,
                            actor_client_id=principal.client_id,
                            subject_user_id=item.subject_user_id,
                            team_id=item.team_id,
                            manager_grant_id=decision.manager_grant_id,
                        )

            return finish_page(tuple(delivered), has_more=has_more)

    # -- cohort reporting --------------------------------------------------

    def team_aggregate(
        self,
        identity: VerifiedIdentity,
        team_id: str,
        *,
        period: ReportingBucket,
    ) -> TeamAggregate:
        """Return a suppressed-or-complete cohort result for one bucket."""

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            team = self.stores.directory.team(principal.organization_id, team_id)
            if team is None:
                # Do not put an unresolved request identifier in audit.
                self._audit_unresolved(
                    principal, action=AuditAction.ACCESS_DENIED, now=now
                )
                raise DirectoryNotFoundError(ReasonCode.DEFAULT_DENY)
            decision = self._enforce(
                principal,
                AccessResource(
                    organization_id=identity.organization_id, team_id=team.team_id
                ),
                AccessAction.READ_TEAM_AGGREGATE,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            # A minimum cohort and fixed bucket do not stop differencing across
            # overlapping teams or longitudinal releases. Until stable privacy
            # cohorts, overlap rules, and a query budget have a reviewed store
            # and policy, the public use case fails closed with no counts or
            # values. ``aggregate_team_snapshots`` remains an internal contract
            # test helper; it is not a disclosure claim.
            aggregate = TeamAggregate(
                organization_id=principal.organization_id,
                team_id=team.team_id,
                period=period,
                minimum_cohort_size=self.minimum_cohort_size,
                suppressed=True,
                suppression_reason=(
                    SuppressionReason.DISCLOSURE_CONTROL_UNAVAILABLE
                ),
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.TEAM_AGGREGATE_READ,
                decision=AuditDecision.ALLOW,
                reason=decision.reason,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                team_id=team.team_id,
            )
            return aggregate

    # -- deletion and evidence --------------------------------------------

    def delete_subject_data(
        self,
        identity: VerifiedIdentity,
        subject_user_id: str,
        *,
        reason: DeletionReason = DeletionReason.SUBJECT_REQUEST,
    ) -> DeletionReceipt:
        """Delete one subject's snapshots and publish ordered tombstones."""

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            membership = self.stores.directory.membership(
                identity.organization_id, subject_user_id
            )
            if membership is None:
                self._audit_unresolved(
                    principal, action=AuditAction.ACCESS_DENIED, now=now
                )
                raise DirectoryNotFoundError(ReasonCode.DEFAULT_DENY)
            self._enforce(
                principal,
                AccessResource(
                    organization_id=identity.organization_id,
                    subject_user_id=membership.user_id,
                ),
                AccessAction.DELETE_SUBJECT_DATA,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            tombstones = self.stores.snapshots.delete_subject(
                principal.organization_id,
                membership.user_id,
                reason=reason,
                now=now,
            )
            self.stores.recipient_deliveries.enqueue_tombstones(
                principal.organization_id, tombstones
            )
            self.stores.aggregate_releases.invalidate_organization(
                principal.organization_id
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.SUBJECT_DATA_DELETED,
                decision=AuditDecision.ALLOW,
                reason=(
                    ReasonCode.SELF_ACCESS
                    if membership.user_id == principal.user_id
                    else ReasonCode.ADMINISTRATIVE_ROLE
                ),
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
                subject_user_id=membership.user_id,
            )
            return DeletionReceipt(
                organization_id=principal.organization_id,
                subject_user_id=membership.user_id,
                deleted_snapshot_count=len(tombstones),
            )

    def read_audit(
        self, identity: VerifiedIdentity, *, limit: int = 50
    ) -> tuple[AuditEvent, ...]:
        """Return recent tenant audit evidence for an administrator."""

        with self.transaction:
            now = self._now()
            principal = self._principal(identity)
            self._enforce(
                principal,
                AccessResource(organization_id=identity.organization_id),
                AccessAction.READ_AUDIT,
                denied_audit_action=AuditAction.ACCESS_DENIED,
                now=now,
            )
            events = self.stores.audit.read(
                principal.organization_id,
                limit=max(1, min(limit, MAX_AUDIT_PAGE_ITEMS)),
            )
            self._audit(
                organization_id=principal.organization_id,
                action=AuditAction.AUDIT_READ,
                decision=AuditDecision.ALLOW,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                now=now,
                actor_user_id=principal.user_id,
                actor_device_id=principal.device_id,
                actor_client_id=principal.client_id,
            )
            return events


__all__ = [
    "MAX_AUDIT_PAGE_ITEMS",
    "MAX_ISSUE_SKEW",
    "SYNC_ENTITLED_ACTIONS",
    "ControlPlaneService",
    "ControlPlaneStores",
]
