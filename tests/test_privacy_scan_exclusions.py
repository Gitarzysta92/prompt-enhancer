from __future__ import annotations

from pathlib import Path

import scripts.privacy_scan as privacy_scan


def test_scanner_ignores_generated_directories_but_rejects_database_artifacts(
    tmp_path,
) -> None:
    unsafe_value = "api_" + "key = " + "sk-" + ("B" * 32)
    for directory_name in (".git", ".cache", "runtime"):
        directory = tmp_path / directory_name
        directory.mkdir()
        (directory / "private-state").write_text(unsafe_value, encoding="utf-8")

    runtime_database = tmp_path / "runtime" / "metrics.sqlite3"
    runtime_database.write_text(unsafe_value, encoding="utf-8")
    (tmp_path / "metrics.sqlite3").write_text(unsafe_value, encoding="utf-8")

    findings = privacy_scan.scan_repository(tmp_path)

    assert [(finding.path, finding.kind) for finding in findings] == [
        ("metrics.sqlite3", "prohibited repository artifact")
    ]

    explicit_findings = privacy_scan.scan_repository(
        tmp_path,
        paths=(runtime_database,),
    )
    assert [
        (finding.path, finding.kind) for finding in explicit_findings
    ] == [("runtime/metrics.sqlite3", "prohibited repository artifact")]


def test_scanner_ignores_only_the_generated_dashboard_resource_tree(
    tmp_path,
) -> None:
    unsafe_value = "api_" + "key = " + "sk-" + ("B" * 32)
    generated = (
        tmp_path
        / "src"
        / "prompt_enhancer"
        / "_resources"
        / "dashboard"
        / "assets"
        / "generated.js"
    )
    sibling = (
        tmp_path
        / "src"
        / "prompt_enhancer"
        / "_resources"
        / "review-me.js"
    )
    generated.parent.mkdir(parents=True)
    generated.write_text(unsafe_value, encoding="utf-8")
    sibling.write_text(unsafe_value, encoding="utf-8")

    findings = privacy_scan.scan_repository(tmp_path)

    assert [(finding.path, finding.kind) for finding in findings] == [
        (
            "src/prompt_enhancer/_resources/review-me.js",
            "possible assigned secret",
        ),
        (
            "src/prompt_enhancer/_resources/review-me.js",
            "possible access token",
        ),
    ]

    explicit_findings = privacy_scan.scan_repository(tmp_path, paths=(generated,))
    assert [finding.kind for finding in explicit_findings] == [
        "possible assigned secret",
        "possible access token",
    ]


def test_scanner_fails_closed_for_oversized_and_binary_files(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(privacy_scan, "_MAX_TEXT_BYTES", 4)
    (tmp_path / "oversized.txt").write_bytes(b"12345")
    (tmp_path / "binary.txt").write_bytes(b"\x00")

    findings = {
        finding.path: finding.kind
        for finding in privacy_scan.scan_repository(tmp_path)
    }

    assert findings == {
        "binary.txt": "binary or non-UTF-8 file",
        "oversized.txt": "file exceeds privacy scan size limit",
    }


def test_scanner_fails_closed_when_file_content_cannot_be_read(
    tmp_path,
    monkeypatch,
) -> None:
    unreadable = tmp_path / "unreadable.txt"
    unreadable.write_text("synthetic safe content", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def fail_for_unreadable(path: Path) -> bytes:
        if path == unreadable:
            raise OSError("synthetic read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_for_unreadable)

    findings = privacy_scan.scan_repository(tmp_path)

    assert [(finding.path, finding.kind) for finding in findings] == [
        ("unreadable.txt", "file content could not be read")
    ]


def test_scanner_reports_only_repository_relative_paths(tmp_path) -> None:
    unsafe = tmp_path / "nested" / "unsafe.txt"
    unsafe.parent.mkdir()
    unsafe.write_text(
        "person" + "@" + "private" + ".example.com",
        encoding="utf-8",
    )

    findings = privacy_scan.scan_repository(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "nested/unsafe.txt"
    assert str(tmp_path) not in findings[0].render()
