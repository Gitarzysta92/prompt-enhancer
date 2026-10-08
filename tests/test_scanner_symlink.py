from __future__ import annotations

import pytest

from scripts.privacy_scan import scan_repository


def test_scanner_rejects_symlink_without_reading_target(tmp_path) -> None:
    target = tmp_path / "synthetic-target.txt"
    target.write_text("synthetic placeholder", encoding="utf-8")
    link = tmp_path / "synthetic-link.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc.__class__.__name__}")

    findings = {
        (finding.path, finding.kind) for finding in scan_repository(tmp_path)
    }

    assert ("synthetic-link.txt", "prohibited repository symlink") in findings
