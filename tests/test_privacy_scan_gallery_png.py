from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import zlib

import scripts.privacy_scan as privacy_scan


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _synthetic_png(
    *,
    metadata: bool = False,
    appended: bytes = b"",
    pixel: bytes = b"\x00\x00\x00",
) -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    chunks = [_chunk(b"IHDR", header)]
    if metadata:
        chunks.append(_chunk(b"tEXt", b"Author=synthetic"))
    chunks.extend((_chunk(b"IDAT", zlib.compress(b"\x00" + pixel)), _chunk(b"IEND", b"")))
    return privacy_scan._PNG_SIGNATURE + b"".join(chunks) + appended


def _approve(monkeypatch, relative_path: str, payload: bytes) -> None:
    monkeypatch.setattr(
        privacy_scan,
        "_APPROVED_SYNTHETIC_GALLERY_PNG_SHA256",
        {relative_path: hashlib.sha256(payload).hexdigest()},
    )


def test_scanner_allows_only_a_hash_pinned_metadata_free_gallery_png(tmp_path, monkeypatch) -> None:
    relative_path = "docs/images/approved-synthetic-gallery.png"
    payload = _synthetic_png()
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    _approve(monkeypatch, relative_path, payload)

    assert privacy_scan.scan_repository(tmp_path) == []


def test_scanner_rejects_gallery_png_with_wrong_name_or_path(tmp_path, monkeypatch) -> None:
    payload = _synthetic_png()
    _approve(monkeypatch, "docs/images/approved-synthetic-gallery.png", payload)
    wrong_name = tmp_path / "docs/images/other.png"
    wrong_path = tmp_path / "assets/approved-synthetic-gallery.png"
    wrong_name.parent.mkdir(parents=True)
    wrong_path.parent.mkdir(parents=True)
    wrong_name.write_bytes(payload)
    wrong_path.write_bytes(payload)

    findings = {(finding.path, finding.kind) for finding in privacy_scan.scan_repository(tmp_path)}

    assert findings == {
        ("assets/approved-synthetic-gallery.png", "binary or non-UTF-8 file"),
        ("docs/images/other.png", "binary or non-UTF-8 file"),
    }


def test_scanner_rejects_unapproved_hash_metadata_and_appended_bytes(tmp_path, monkeypatch) -> None:
    relative_path = "docs/images/approved-synthetic-gallery.png"
    approved = _synthetic_png()
    _approve(monkeypatch, relative_path, approved)
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)

    target.write_bytes(_synthetic_png(appended=b"unexpected"))
    assert privacy_scan.scan_repository(tmp_path)[0].kind == "gallery PNG envelope invalid"

    target.write_bytes(_synthetic_png(metadata=True))
    assert privacy_scan.scan_repository(tmp_path)[0].kind == "gallery PNG envelope invalid"

    target.write_bytes(_synthetic_png(pixel=b"\x01\x02\x03"))
    assert privacy_scan.scan_repository(tmp_path)[0].kind == "gallery PNG is not an approved hash"


def test_scanner_rejects_oversized_gallery_png_and_private_gallery_path(tmp_path, monkeypatch) -> None:
    relative_path = "docs/images/approved-synthetic-gallery.png"
    payload = _synthetic_png()
    _approve(monkeypatch, relative_path, payload)
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    monkeypatch.setattr(privacy_scan, "_MAX_GALLERY_PNG_BYTES", len(payload) - 1)
    original_read_bytes = Path.read_bytes

    def reject_oversized_gallery_read(path: Path) -> bytes:
        if path == target:
            raise AssertionError("scanner read an oversized gallery binary")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_oversized_gallery_read)
    assert privacy_scan.scan_repository(tmp_path)[0].kind == "gallery PNG exceeds size limit"

    private = tmp_path / "docs/images/sessions/approved-synthetic-gallery.png"
    private.parent.mkdir(parents=True)
    private.write_bytes(payload)
    assert any(
        finding.path == "docs/images/sessions/approved-synthetic-gallery.png"
        and finding.kind == "prohibited private-data path"
        for finding in privacy_scan.scan_repository(tmp_path)
    )
