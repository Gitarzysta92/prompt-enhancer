"""Integrity, path, consent and readiness contracts for direct file sharing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.file_sharing import (
    ByteRange,
    ChunkDigest,
    DirectTransferRequest,
    FileContentKind,
    FileGrantState,
    FileManifest,
    FileRecipientGrant,
    FileSharingReadiness,
    FileSharingReadinessGap,
    LocalFileDescriptor,
    TransferFailureReason,
    TransferRecord,
    TransferState,
    compute_merkle_root,
    safe_local_basename,
)


NOW = datetime(2047, 3, 8, 12, tzinfo=UTC)
ORG = "soc_" + "a" * 64
OWNER = "soc_" + "b" * 64
RECIPIENT = "soc_" + "c" * 64
OWNER_DEVICE = "soc_" + "d" * 64
RECIPIENT_DEVICE = "soc_" + "e" * 64
MANIFEST = "shr_" + "1" * 64
GRANT = "shr_" + "2" * 64
TRANSFER = "shr_" + "3" * 64


def chunks() -> tuple[ChunkDigest, ...]:
    return (
        ChunkDigest(index=0, offset=0, size=65_536, sha256="4" * 64),
        ChunkDigest(index=1, offset=65_536, size=11, sha256="5" * 64),
    )


def manifest(**overrides: object) -> FileManifest:
    source = chunks()
    fields: dict[str, object] = {
        "manifest_id": MANIFEST,
        "organization_id": ORG,
        "owner_account_id": OWNER,
        "owner_device_id": OWNER_DEVICE,
        "content_kind": FileContentKind.SOURCE_BUNDLE,
        "byte_size": 65_547,
        "chunk_size": 65_536,
        "whole_file_sha256": "6" * 64,
        "merkle_root_sha256": compute_merkle_root(source),
        "chunks": source,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=1),
    }
    fields.update(overrides)
    return FileManifest(**fields)


def test_manifest_requires_exact_ordered_coverage_and_merkle_commitment() -> None:
    accepted = manifest()
    assert accepted.stores_file_name is False
    assert accepted.stores_file_path is False
    assert len(accepted.chunks) == 2

    with pytest.raises(ValidationError):
        manifest(chunks=(chunks()[1], chunks()[0]))
    with pytest.raises(ValidationError):
        manifest(chunks=(chunks()[0], chunks()[0]))
    with pytest.raises(ValidationError):
        manifest(merkle_root_sha256="0" * 64)
    with pytest.raises(ValidationError):
        manifest(expires_at=NOW + timedelta(days=31))
    tampered = chunks()[1].model_copy(update={"size": 10})
    with pytest.raises(ValidationError):
        manifest(chunks=(chunks()[0], tampered))


@pytest.mark.parametrize(
    "unsafe",
    (
        "../report.txt",
        "..\\report.txt",
        "C:report.txt",
        "C:\\report.txt",
        "\\\\server\\share.txt",
        "\\\\?\\C:\\report.txt",
        "report.txt:secret",
        "CON",
        "con.txt",
        "LPT9.log",
        "report. ",
        "report.",
        ".hidden",
        "report\x00.txt",
        "report\n.txt",
    ),
)
def test_owner_local_basename_rejects_traversal_devices_ads_and_controls(
    unsafe: str,
) -> None:
    with pytest.raises(ValueError):
        safe_local_basename(unsafe)


def test_safe_local_descriptor_has_no_absolute_path() -> None:
    descriptor = LocalFileDescriptor(
        local_file_id="shr_" + "7" * 64,
        manifest_id=MANIFEST,
        safe_basename="Synthetic bundle (1).zip",
        quarantine_root_id="shr_" + "8" * 64,
        symlink_or_reparse_checked=True,
    )
    assert descriptor.safe_basename == "Synthetic bundle (1).zip"
    assert not set(LocalFileDescriptor.model_fields).intersection(
        {"path", "absolute_path", "root_path", "bytes", "content"}
    )


def test_recipient_consent_is_explicit_and_bound_to_lifecycle() -> None:
    offered = FileRecipientGrant(
        organization_id=ORG,
        grant_id=GRANT,
        manifest_id=MANIFEST,
        owner_account_id=OWNER,
        recipient_account_id=RECIPIENT,
        state=FileGrantState.OFFERED,
        offered_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    assert offered.explicit_recipient_consent is False
    with pytest.raises(ValidationError):
        FileRecipientGrant(
            **offered.model_dump(exclude={"state", "explicit_recipient_consent"}),
            state=FileGrantState.CONSENTED,
            explicit_recipient_consent=False,
        )
    with pytest.raises(ValidationError):
        FileRecipientGrant(
            **offered.model_dump(exclude={"state", "explicit_recipient_consent"}),
            state=FileGrantState.OFFERED,
            explicit_recipient_consent=True,
        )


def test_transfer_is_direct_only_bounded_and_resumable() -> None:
    request = DirectTransferRequest(
        organization_id=ORG,
        transfer_id=TRANSFER,
        manifest_id=MANIFEST,
        grant_id=GRANT,
        requester_account_id=RECIPIENT,
        requester_device_id=RECIPIENT_DEVICE,
        ranges=(ByteRange(start=0, end_exclusive=10), ByteRange(start=20, end_exclusive=30)),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    assert request.relay_allowed is False
    assert request.cloud_byte_fallback_allowed is False
    with pytest.raises(ValidationError):
        DirectTransferRequest(
            **request.model_dump(exclude={"ranges"}),
            ranges=(
                ByteRange(start=20, end_exclusive=30),
                ByteRange(start=10, end_exclusive=25),
            ),
        )
    with pytest.raises(ValidationError):
        DirectTransferRequest(
            **request.model_dump(exclude={"relay_allowed"}), relay_allowed=True
        )
    with pytest.raises(ValidationError):
        TransferRecord(
            request=request,
            state=TransferState.DIRECT_READY,
            changed_at=NOW,
            received_bytes=0,
        )
    approved = TransferRecord(
        request=request,
        state=TransferState.DIRECT_READY,
        owner_approved_at=NOW,
        changed_at=NOW,
        received_bytes=0,
    )
    assert approved.owner_approved_at == NOW


def test_file_sharing_readiness_never_implies_relay_cloud_or_recall() -> None:
    readiness = FileSharingReadiness(enabled=True)
    assert readiness.production_ready is False
    assert readiness.direct_only is True
    assert readiness.relay_allowed is False
    assert readiness.cloud_file_byte_storage is False
    assert readiness.offline_recipient_queue_location == "sender_device_only"
    assert readiness.remote_recall_guaranteed is False
    assert readiness.central_file_name_storage is False
    assert readiness.central_file_path_storage is False
    assert readiness.local_history_deleted_on_entitlement_lapse is False
    assert readiness.received_files_deleted_on_entitlement_lapse is False
    assert readiness.local_export_requires_active_entitlement is False
    assert FileSharingReadinessGap.SYMMETRIC_NAT_AND_CGNAT_UNSUPPORTED in readiness.gaps
    assert FileSharingReadinessGap.TURN_RELAY_ABSENT in readiness.gaps
    assert FileSharingReadinessGap.METADATA_VISIBLE_TO_CONTROL_PLANE in readiness.gaps
    assert {
        "owner_offline",
        "recipient_offline",
        "sender_queue_expiring",
        "unreachable_no_relay",
        "revoked_before_completion",
        "quota_exceeded",
        "manifest_invalid",
        "integrity_failed",
        "quarantine_rejected_path",
    }.issubset({reason.value for reason in TransferFailureReason})


def test_manifest_rejects_content_and_path_canaries() -> None:
    accepted = manifest()
    for field in ("path", "file_name", "content", "bytes", "plaintext"):
        with pytest.raises(ValidationError):
            FileManifest(**accepted.model_dump(), **{field: "SYNTHETIC canary"})
