from __future__ import annotations

from pathlib import Path

from scripts.privacy_scan import scan_repository


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_repository_passes_privacy_scan() -> None:
    assert scan_repository(REPOSITORY_ROOT) == []


def test_scanner_flags_secret_email_and_private_path(tmp_path) -> None:
    unsafe = tmp_path / "unsafe.txt"
    personal_email = "alex" + "@" + "company" + ".com"
    private_path = "/" + "home/" + "alex/work"
    assigned_secret = "api_" + "key = " + "sk-" + ("A" * 32)
    unsafe.write_text(
        "\n".join((personal_email, private_path, assigned_secret)),
        encoding="utf-8",
    )

    kinds = {finding.kind for finding in scan_repository(tmp_path)}

    assert "possible personal email" in kinds
    assert "possible private home path" in kinds
    assert "possible assigned secret" in kinds
    assert "possible access token" in kinds


def test_scanner_allows_reserved_examples(tmp_path) -> None:
    safe = tmp_path / "safe.txt"
    safe.write_text(
        "\n".join(
            (
                "person@example.invalid",
                "/home/example/project",
                r"C:\Users\Example\project",
                "api_key = example_token_do_not_use",
            )
        ),
        encoding="utf-8",
    )

    assert scan_repository(tmp_path) == []
