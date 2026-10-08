from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.check_provider_compatibility_manifest import (
    ManifestError,
    evaluate_support,
    load_manifest,
    validate_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "check_provider_compatibility_manifest.py"
SYNTHETIC_MANIFEST = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "providers"
    / "compatibility-manifest-v1.json"
)


def _synthetic_payload() -> dict[str, object]:
    return json.loads(SYNTHETIC_MANIFEST.read_text(encoding="utf-8"))


def test_synthetic_manifest_validates_and_requires_an_exact_supported_tuple() -> None:
    manifest = load_manifest(SYNTHETIC_MANIFEST)

    assert evaluate_support(
        manifest,
        provider="example_agent",
        surface="catalog",
        schema_family="example.catalog.v1",
        provider_version="example-1.0",
        capability="session_list",
    ) == "compatibility_supported"
    assert evaluate_support(
        manifest,
        provider="example_agent",
        surface="catalog",
        schema_family="example.catalog.v1",
        provider_version="example-2.0",
        capability="session_list",
    ) == "provider_version_untested"
    assert evaluate_support(
        manifest,
        provider="example_agent",
        surface="catalog",
        schema_family="example.catalog.v1",
        provider_version="example-1.0",
        capability="text_window",
    ) == "capability_unsupported"


def test_manifest_rejects_unreviewed_fields_without_echoing_values() -> None:
    payload = _synthetic_payload()
    private_canary = "PRIVATE-MANIFEST-VALUE-CANARY"
    entry = payload["entries"][0]  # type: ignore[index]
    entry["raw_schema"] = private_canary  # type: ignore[index]

    with pytest.raises(ManifestError) as raised:
        validate_manifest(payload)

    assert private_canary not in str(raised.value)


def test_verified_release_requires_official_source_and_all_release_evidence() -> None:
    synthetic_only = _synthetic_payload()
    synthetic_only["entries"][0]["schema_source"] = "synthetic_contract"  # type: ignore[index]
    missing_review = _synthetic_payload()
    missing_review["entries"][0]["release_evidence"].remove("privacy_review")  # type: ignore[index]

    with pytest.raises(ManifestError):
        validate_manifest(synthetic_only)
    with pytest.raises(ManifestError):
        validate_manifest(missing_review)


def test_experimental_decoder_cannot_borrow_verified_status_from_another_decoder() -> None:
    payload = _synthetic_payload()
    verified = payload["entries"][0]  # type: ignore[index]
    experimental = dict(verified)  # type: ignore[arg-type]
    experimental["decoder_version"] = "2"
    experimental["release_state"] = "experimental"
    experimental["capabilities"] = {
        "session_list": "supported",
        "text_window": "supported",
    }
    payload["entries"].append(experimental)  # type: ignore[union-attr]

    manifest = validate_manifest(payload)

    assert evaluate_support(
        manifest,
        provider="example_agent",
        surface="catalog",
        schema_family="example.catalog.v1",
        provider_version="example-1.0",
        capability="text_window",
    ) == "decoder_experimental"


@pytest.mark.parametrize(
    "provider_version",
    (
        "*",
        ">=example-1",
        "example-1,example-2",
        "C:/Users/Example/provider",
        "/home/example/provider",
    ),
)
def test_manifest_rejects_ranges_wildcards_and_paths(provider_version: str) -> None:
    payload = _synthetic_payload()
    payload["entries"][0]["tested_provider_versions"] = [provider_version]  # type: ignore[index]

    with pytest.raises(ManifestError):
        validate_manifest(payload)


def test_duplicate_json_keys_fail_with_a_sanitized_cli_result(tmp_path: Path) -> None:
    private_canary = "PRIVATE-DUPLICATE-KEY-CANARY"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"manifest_version":"provider-compatibility-manifest-v1",'
        '"manifest_version":"' + private_canary + '","entries":[]}',
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(manifest)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stderr.strip() == "manifest_invalid"
    assert private_canary not in result.stdout + result.stderr


def test_cli_validates_and_queries_the_synthetic_manifest() -> None:
    validated = subprocess.run(
        [sys.executable, str(SCRIPT), str(SYNTHETIC_MANIFEST)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    queried = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(SYNTHETIC_MANIFEST),
            "--provider",
            "example_agent",
            "--surface",
            "catalog",
            "--schema-family",
            "example.catalog.v1",
            "--provider-version",
            "example-1.0",
            "--capability",
            "session_list",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert validated.returncode == 0
    assert validated.stdout.strip() == "manifest_valid"
    assert queried.returncode == 0
    assert queried.stdout.strip() == "compatibility_supported"


def test_cli_module_has_no_provider_process_or_network_dependency() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            if node.module is None:
                raise AssertionError("relative imports are not allowed")
            imports.add(node.module.split(".", 1)[0])

    assert imports <= {
        "argparse",
        "dataclasses",
        "json",
        "pathlib",
        "re",
        "sys",
        "typing",
    }
