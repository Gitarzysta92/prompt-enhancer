from __future__ import annotations

from pathlib import Path

from scripts.privacy_scan import scan_repository


def test_scanner_flags_private_artifacts_without_reading_them(tmp_path, monkeypatch) -> None:
    environment_file = tmp_path / ".env"
    provider_file = tmp_path / ".codex" / "history.jsonl"
    provider_file.parent.mkdir()
    environment_file.write_text("synthetic placeholder", encoding="utf-8")
    provider_file.write_text("synthetic placeholder", encoding="utf-8")
    protected = {environment_file, provider_file}
    original_read_bytes = Path.read_bytes

    def reject_private_reads(path: Path) -> bytes:
        if path in protected:
            raise AssertionError("scanner read a prohibited private artifact")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_private_reads)

    findings = {
        (finding.path, finding.kind) for finding in scan_repository(tmp_path)
    }

    assert findings == {
        (".env", "prohibited repository artifact"),
        (".codex/history.jsonl", "prohibited private-data path"),
    }
