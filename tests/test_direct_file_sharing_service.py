"""Authorization, quota, connectivity and integrity tests for direct transfers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import threading

import pytest

from prompt_enhancer.application.file_sharing import (
    ByteRange,
    ChunkDigest,
    DirectConnectivityAssessment,
    DirectConnectivityState,
    DirectFileSharingService,
    FileContentKind,
    FileManifest,
    FileShareAuthorizationError,
    FileShareConflictError,
    FileShareQuota,
    FileShareReasonCode,
    FileSharingStores,
    OwnerFileAvailability,
    PeerAvailabilityState,
    TransferFailureReason,
    TransferIntegrityEvidence,
    TransferState,
    compute_merkle_root,
)
from prompt_enhancer.application.social import BlockRecord, Friendship
from prompt_enhancer.infrastructure.file_sharing import (
    FailClosedDirectSignaling,
    create_development_file_sharing_foundation,
)
from prompt_enhancer.infrastructure.social import create_development_social_foundation

from test_social_service import (
    ALICE,
    ALICE_DEVICE,
    BOB,
    BOB_DEVICE,
    Clock,
    ORG,
    NOW,
    provision,
)


MANIFEST = "shr_" + "1" * 64


@dataclass(frozen=True)
class SyntheticDirectSignaling:
    reason: TransferFailureReason | None = None
    available: bool = True
    authenticated: bool = True
    relay_supported: bool = False

    def negotiate_direct(self, owner, request, *, now):
        return DirectConnectivityAssessment(
            transfer_id=request.transfer_id,
            state=(
                DirectConnectivityState.UNAVAILABLE
                if self.reason is not None
                else DirectConnectivityState.READY
            ),
            reason=self.reason,
            authenticated_signaling=True,
            assessed_at=now,
        )


@dataclass
class LockProbeSignaling:
    lock: threading.RLock
    hook: object | None = None
    available: bool = True
    authenticated: bool = True
    relay_supported: bool = False

    def negotiate_direct(self, owner, request, *, now):
        acquired: list[bool] = []

        def probe() -> None:
            result = self.lock.acquire(timeout=1)
            acquired.append(result)
            if result:
                self.lock.release()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=2)
        assert acquired == [True], "signaling ran while the metadata lock was held"
        if callable(self.hook):
            self.hook()
        return DirectConnectivityAssessment(
            transfer_id=request.transfer_id,
            state=DirectConnectivityState.READY,
            authenticated_signaling=True,
            assessed_at=now,
        )


def chunks() -> tuple[ChunkDigest, ...]:
    return (
        ChunkDigest(index=0, offset=0, size=65_536, sha256="4" * 64),
        ChunkDigest(index=1, offset=65_536, size=9, sha256="5" * 64),
    )


def manifest() -> FileManifest:
    selected = chunks()
    return FileManifest(
        manifest_id=MANIFEST,
        organization_id=ORG,
        owner_account_id=ALICE,
        owner_device_id=ALICE_DEVICE,
        content_kind=FileContentKind.ARCHIVE,
        byte_size=65_545,
        chunk_size=65_536,
        whole_file_sha256="6" * 64,
        merkle_root_sha256=compute_merkle_root(selected),
        chunks=selected,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


def setup(signaling=None, quota=None):
    clock = Clock()
    social = create_development_social_foundation(clock)
    alice = provision(social.state, ALICE, ALICE_DEVICE)
    bob = provision(social.state, BOB, BOB_DEVICE)
    social.state.save_friendship(
        Friendship(
            organization_id=ORG,
            first_account_id=ALICE,
            second_account_id=BOB,
            accepted_request_id="soc_" + "7" * 64,
            created_at=NOW,
        )
    )
    files = create_development_file_sharing_foundation(
        social, clock, quota=quota
    )
    service = DirectFileSharingService(
        stores=files.service.stores,
        identifiers=files.service.identifiers,
        signaling=signaling or SyntheticDirectSignaling(),
        quota=quota or FileShareQuota(),
        clock=clock,
    )
    return clock, social, files, service, alice, bob


def consented_grant(service, alice, bob):
    service.register_manifest(alice, manifest())
    offered = service.offer(
        alice, MANIFEST, BOB, expires_at=NOW + timedelta(hours=4)
    )
    return service.decide_grant(bob, offered.grant_id, consent=True)


def online(service, alice):
    service.publish_availability(
        alice,
        OwnerFileAvailability(
            organization_id=ORG,
            manifest_id=MANIFEST,
            owner_account_id=ALICE,
            owner_device_id=ALICE_DEVICE,
            state=PeerAvailabilityState.ONLINE,
            observed_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
        ),
    )


def test_full_metadata_lifecycle_requires_consent_approval_direct_path_and_integrity() -> None:
    _, _, _, service, alice, bob = setup()
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    assert transfer.state is TransferState.WAITING_OWNER_APPROVAL
    ready = service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert ready.state is TransferState.DIRECT_READY
    completed = service.complete_transfer(
        bob,
        TransferIntegrityEvidence(
            transfer_id=transfer.request.transfer_id,
            manifest_id=MANIFEST,
            received_bytes=manifest().byte_size,
            whole_file_sha256=manifest().whole_file_sha256,
            chunk_sha256=tuple(chunk.sha256 for chunk in chunks()),
            verified_at=NOW,
        ),
    )
    assert completed.state is TransferState.COMPLETED
    assert completed.remote_recall_guaranteed is False


def test_owner_offline_fails_without_cloud_or_relay_queue() -> None:
    _, _, _, service, alice, bob = setup()
    grant = consented_grant(service, alice, bob)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    assert transfer.state is TransferState.FAILED
    assert transfer.failure_reason is TransferFailureReason.OWNER_OFFLINE
    assert transfer.request.relay_allowed is False
    assert transfer.request.cloud_byte_fallback_allowed is False


def test_symmetric_nat_and_missing_signaling_fail_explicitly_without_turn() -> None:
    for signaling, expected in (
        (
            SyntheticDirectSignaling(
                reason=TransferFailureReason.SYMMETRIC_NAT_OR_CGNAT
            ),
            TransferFailureReason.SYMMETRIC_NAT_OR_CGNAT,
        ),
        (FailClosedDirectSignaling(), TransferFailureReason.SIGNALING_UNAVAILABLE),
    ):
        _, _, _, service, alice, bob = setup(signaling=signaling)
        grant = consented_grant(service, alice, bob)
        online(service, alice)
        transfer = service.request_transfer(
            bob,
            grant.grant_id,
            ranges=(ByteRange(start=0, end_exclusive=2),),
            expires_at=NOW + timedelta(hours=1),
        )
        failed = service.approve_and_negotiate(
            alice, transfer.request.transfer_id
        )
        assert failed.state is TransferState.FAILED
        assert failed.failure_reason is expected


def test_tampered_digest_fails_and_never_completes() -> None:
    _, _, files, service, alice, bob = setup()
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    service.approve_and_negotiate(alice, transfer.request.transfer_id)
    failed = service.complete_transfer(
        bob,
        TransferIntegrityEvidence(
            transfer_id=transfer.request.transfer_id,
            manifest_id=MANIFEST,
            received_bytes=manifest().byte_size,
            whole_file_sha256="0" * 64,
            chunk_sha256=tuple(chunk.sha256 for chunk in chunks()),
            verified_at=NOW,
        ),
    )
    assert failed.state is TransferState.FAILED
    assert failed.failure_reason is TransferFailureReason.INTEGRITY_FAILED
    stored = files.state.transfer(ORG, transfer.request.transfer_id)
    assert stored.state is TransferState.FAILED
    assert stored.failure_reason is TransferFailureReason.INTEGRITY_FAILED


def test_owner_device_revocation_before_completion_fails_closed() -> None:
    _, social, _, service, alice, bob = setup()
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    service.approve_and_negotiate(alice, transfer.request.transfer_id)
    social.state.revoke_device(ORG, ALICE_DEVICE, now=NOW)
    failed = service.complete_transfer(
        bob,
        TransferIntegrityEvidence(
            transfer_id=transfer.request.transfer_id,
            manifest_id=MANIFEST,
            received_bytes=manifest().byte_size,
            whole_file_sha256=manifest().whole_file_sha256,
            chunk_sha256=tuple(chunk.sha256 for chunk in chunks()),
            verified_at=NOW,
        ),
    )
    assert failed.state is TransferState.FAILED
    assert failed.failure_reason is TransferFailureReason.REVOKED_BEFORE_COMPLETION


def test_expired_transfer_cannot_complete_even_with_valid_integrity_evidence() -> None:
    clock, _, _, service, alice, bob = setup()
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    service.approve_and_negotiate(alice, transfer.request.transfer_id)
    clock.value = NOW + timedelta(hours=2)
    failed = service.complete_transfer(
        bob,
        TransferIntegrityEvidence(
            transfer_id=transfer.request.transfer_id,
            manifest_id=MANIFEST,
            received_bytes=manifest().byte_size,
            whole_file_sha256=manifest().whole_file_sha256,
            chunk_sha256=tuple(chunk.sha256 for chunk in chunks()),
            verified_at=clock.value,
        ),
    )
    assert failed.state is TransferState.FAILED
    assert failed.failure_reason is TransferFailureReason.EXPIRED


def test_blocked_and_unknown_recipient_use_same_anti_enumeration_reason() -> None:
    _, social, _, service, alice, bob = setup()
    service.register_manifest(alice, manifest())
    social.state.save_block(
        BlockRecord(
            organization_id=ORG,
            blocker_account_id=BOB,
            blocked_account_id=ALICE,
            created_at=NOW,
        )
    )
    unknown = "soc_" + "8" * 64
    reasons = []
    for target in (BOB, unknown):
        with pytest.raises(FileShareAuthorizationError) as captured:
            service.offer(
                alice, MANIFEST, target, expires_at=NOW + timedelta(hours=1)
            )
        reasons.append(captured.value.reason)
    assert reasons == [
        FileShareReasonCode.BLOCKED_OR_UNAVAILABLE,
        FileShareReasonCode.BLOCKED_OR_UNAVAILABLE,
    ]


def test_range_and_concurrency_quotas_fail_closed() -> None:
    quota = FileShareQuota(max_concurrent_transfers_per_owner=1)
    _, _, _, service, alice, bob = setup(quota=quota)
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    with pytest.raises(FileShareConflictError) as captured:
        service.request_transfer(
            bob,
            grant.grant_id,
            ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size + 1),),
            expires_at=NOW + timedelta(hours=1),
        )
    assert captured.value.reason is FileShareReasonCode.INVALID_RANGE
    service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(FileShareConflictError) as captured:
        service.request_transfer(
            bob,
            grant.grant_id,
            ranges=(ByteRange(start=1, end_exclusive=2),),
            expires_at=NOW + timedelta(hours=1),
        )
    assert captured.value.reason is FileShareReasonCode.QUOTA_EXCEEDED


def test_revocation_stops_future_serving_but_never_claims_remote_recall() -> None:
    _, _, _, service, alice, bob = setup()
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    receipt = service.revoke_manifest(alice, MANIFEST)
    assert receipt.owner_will_no_longer_serve_bytes is True
    assert receipt.already_received_bytes_recalled is False
    assert receipt.revoked_grants == 1
    assert receipt.cancelled_active_transfers == 1
    with pytest.raises(FileShareAuthorizationError):
        service.publish_availability(
            alice,
            OwnerFileAvailability(
                organization_id=ORG,
                manifest_id=MANIFEST,
                owner_account_id=ALICE,
                owner_device_id=ALICE_DEVICE,
                state=PeerAvailabilityState.ONLINE,
                observed_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
        )


def test_external_signaling_runs_outside_transaction_and_rechecks_revocation() -> None:
    clock = Clock()
    social = create_development_social_foundation(clock)
    alice = provision(social.state, ALICE, ALICE_DEVICE)
    bob = provision(social.state, BOB, BOB_DEVICE)
    social.state.save_friendship(
        Friendship(
            organization_id=ORG,
            first_account_id=ALICE,
            second_account_id=BOB,
            accepted_request_id="soc_" + "7" * 64,
            created_at=NOW,
        )
    )
    files = create_development_file_sharing_foundation(social, clock)
    signaling = LockProbeSignaling(social.state.lock)
    service = DirectFileSharingService(
        stores=files.service.stores,
        identifiers=files.service.identifiers,
        signaling=signaling,
        quota=FileShareQuota(),
        clock=clock,
    )
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    signaling.hook = lambda: service.revoke_grant(alice, grant.grant_id)
    result = service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert result.state is TransferState.REVOKED


def test_requester_device_revocation_during_signaling_never_reaches_direct_ready() -> None:
    clock = Clock()
    social = create_development_social_foundation(clock)
    alice = provision(social.state, ALICE, ALICE_DEVICE)
    bob = provision(social.state, BOB, BOB_DEVICE)
    social.state.save_friendship(
        Friendship(
            organization_id=ORG,
            first_account_id=ALICE,
            second_account_id=BOB,
            accepted_request_id="soc_" + "7" * 64,
            created_at=NOW,
        )
    )
    files = create_development_file_sharing_foundation(social, clock)
    signaling = LockProbeSignaling(social.state.lock)
    service = DirectFileSharingService(
        stores=files.service.stores,
        identifiers=files.service.identifiers,
        signaling=signaling,
        quota=FileShareQuota(),
        clock=clock,
    )
    grant = consented_grant(service, alice, bob)
    online(service, alice)
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    signaling.hook = lambda: social.state.revoke_device(
        ORG, BOB_DEVICE, now=NOW
    )
    result = service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert result.state is TransferState.FAILED
    assert result.failure_reason is TransferFailureReason.REVOKED_BEFORE_COMPLETION


def test_manifest_audit_uses_acceptance_time_and_rejects_stale_client_time() -> None:
    clock, _, files, service, alice, _ = setup()
    clock.value = NOW + timedelta(minutes=2)
    service.register_manifest(alice, manifest())
    assert files.state.audits[-1].occurred_at == clock.value

    other_manifest = FileManifest.model_validate(
        {
            **manifest().model_dump(mode="python"),
            "manifest_id": "shr_" + "9" * 64,
            "created_at": NOW - timedelta(minutes=10),
        }
    )
    with pytest.raises(FileShareConflictError) as captured:
        service.register_manifest(alice, other_manifest)
    assert captured.value.reason is FileShareReasonCode.STATE_CONFLICT
