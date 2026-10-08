"""Filesystem boundary tests use only temporary synthetic bytes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path

import pytest

from prompt_enhancer.application.file_sharing import (
    ByteRange,
    ChunkDigest,
    FileContentKind,
    FileManifest,
    FileShareReasonCode,
    compute_merkle_root,
)
from prompt_enhancer.infrastructure.file_sharing import (
    QuarantineAccessError,
    QuarantinedLocalFileReader,
)


NOW = datetime(2047, 3, 8, 12, tzinfo=UTC)
ORG = "soc_" + "a" * 64
OWNER = "soc_" + "b" * 64
DEVICE = "soc_" + "c" * 64
MANIFEST = "shr_" + "1" * 64
LOCAL_FILE = "shr_" + "2" * 64
ROOT = "shr_" + "3" * 64
PAYLOAD = b"synthetic-example-file" * 4_000


def file_manifest(payload: bytes = PAYLOAD) -> FileManifest:
    pieces = tuple(
        payload[offset : offset + 65_536]
        for offset in range(0, len(payload), 65_536)
    )
    chunks = tuple(
        ChunkDigest(
            index=index,
            offset=index * 65_536,
            size=len(piece),
            sha256=hashlib.sha256(piece).hexdigest(),
        )
        for index, piece in enumerate(pieces)
    )
    return FileManifest(
        manifest_id=MANIFEST,
        organization_id=ORG,
        owner_account_id=OWNER,
        owner_device_id=DEVICE,
        content_kind=FileContentKind.OTHER,
        byte_size=len(payload),
        chunk_size=65_536,
        whole_file_sha256=hashlib.sha256(payload).hexdigest(),
        merkle_root_sha256=compute_merkle_root(chunks),
        chunks=chunks,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


def test_registered_quarantine_file_is_hash_checked_and_range_bounded(
    tmp_path: Path,
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (quarantine / "Synthetic.bin").write_bytes(PAYLOAD)
    reader = QuarantinedLocalFileReader(quarantine, ROOT)
    descriptor = reader.register(
        local_file_id=LOCAL_FILE,
        safe_basename="Synthetic.bin",
        manifest=file_manifest(),
    )
    assert reader.stat_matches_manifest(descriptor, file_manifest()) is True
    assert reader.read_range(descriptor, ByteRange(start=10, end_exclusive=30)) == PAYLOAD[10:30]
    assert reader.unregister(LOCAL_FILE) is True
    with pytest.raises(QuarantineAccessError):
        reader.read_range(descriptor, ByteRange(start=0, end_exclusive=1))


def test_tampered_or_replaced_file_is_rejected(tmp_path: Path) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    selected = quarantine / "Synthetic.bin"
    selected.write_bytes(PAYLOAD)
    reader = QuarantinedLocalFileReader(quarantine, ROOT)
    descriptor = reader.register(
        local_file_id=LOCAL_FILE,
        safe_basename="Synthetic.bin",
        manifest=file_manifest(),
    )
    selected.write_bytes(b"x" * len(PAYLOAD))
    assert reader.stat_matches_manifest(descriptor, file_manifest()) is False


def test_unregistered_traversal_and_link_are_rejected(tmp_path: Path) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(PAYLOAD)
    reader = QuarantinedLocalFileReader(quarantine, ROOT)
    with pytest.raises(QuarantineAccessError) as captured:
        reader.register(
            local_file_id=LOCAL_FILE,
            safe_basename="..\\outside.bin",
            manifest=file_manifest(),
        )
    assert captured.value.reason is FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE

    linked = quarantine / "Linked.bin"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks unavailable on this platform")
    with pytest.raises(QuarantineAccessError):
        reader.register(
            local_file_id=LOCAL_FILE,
            safe_basename="Linked.bin",
            manifest=file_manifest(),
        )


def test_quarantine_root_itself_cannot_be_a_link(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable on this platform")
    with pytest.raises(QuarantineAccessError):
        QuarantinedLocalFileReader(linked, ROOT)


def test_hard_link_cannot_escape_the_quarantine_boundary(tmp_path: Path) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    outside = tmp_path / "synthetic-outside.bin"
    outside.write_bytes(PAYLOAD)
    linked = quarantine / "Linked.bin"
    try:
        os.link(outside, linked)
    except OSError:
        pytest.skip("hard links unavailable on this platform")
    reader = QuarantinedLocalFileReader(quarantine, ROOT)
    with pytest.raises(QuarantineAccessError) as captured:
        reader.register(
            local_file_id=LOCAL_FILE,
            safe_basename="Linked.bin",
            manifest=file_manifest(),
        )
    assert captured.value.reason is FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
