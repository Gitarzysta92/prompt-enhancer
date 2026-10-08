"""Synthetic, content-free checks for frontend notice evidence semantics."""

from __future__ import annotations

import pytest

from prompt_enhancer.infrastructure import frontend_notice_inventory as notices


def _identity(marker: str, size: int = 10) -> tuple[int, str]:
    return size, marker * 64


def _package(name: str, *, license: str | None = "MIT") -> dict[str, str]:
    value = {"name": name, "version": "1.0.0"}
    if license is not None:
        value["license"] = license
    return value


def _graph(*keys: str, assets: list[dict] | None = None) -> dict:
    return {
        "modules": [{"kind": "package", "package_instance_lock_key": key} for key in keys],
        "assets": assets or [],
    }


def test_notice_is_evidence_not_verified_obligation() -> None:
    key = "node_modules/example"
    installed = {
        "example/package.json": _identity("a"),
        "example/LICENSE.md": _identity("b"),
    }
    packages, opaque, gaps, count, total = notices.evidence(
        graph=_graph(key), installed=installed, metadata={key: _package("example")}
    )
    assert (opaque, count, total) == ([], 1, 10)
    assert packages[0]["notice_evidence_status"] == "present_obligations_unverified"
    assert packages[0]["license_declaration"] == "MIT"
    assert "notice_obligations_not_determined" in gaps
    assert "package_notice_evidence_missing" not in gaps


def test_missing_notice_and_license_remain_explicit_unknowns() -> None:
    key = "node_modules/example"
    packages, _, gaps, count, total = notices.evidence(
        graph=_graph(key), installed={"example/package.json": _identity("a")},
        metadata={key: _package("example", license=None)},
    )
    assert (count, total) == (0, 0)
    assert packages[0]["notice_files"] == []
    assert packages[0]["license_declaration"] is None
    assert packages[0]["notice_evidence_status"] == "missing"
    assert {"package_notice_evidence_missing", "package_license_declaration_unknown"} <= set(gaps)


def test_nested_package_owns_its_own_notice() -> None:
    parent = "node_modules/parent"
    child = "node_modules/parent/node_modules/child"
    installed = {
        "parent/package.json": _identity("a"),
        "parent/LICENSE": _identity("b"),
        "parent/node_modules/child/package.json": _identity("c"),
        "parent/node_modules/child/NOTICE": _identity("d"),
    }
    packages, _, gaps, count, _ = notices.evidence(
        graph=_graph(parent, child), installed=installed,
        metadata={parent: _package("parent"), child: _package("child")},
    )
    assert count == 2
    assert [entry["notice_files"][0]["relative_path"] for entry in packages] == [
        "parent/LICENSE", "parent/node_modules/child/NOTICE"
    ]
    assert "multiple_notice_files_scope_unverified" not in gaps


def test_multiple_notices_do_not_become_a_verified_license() -> None:
    key = "node_modules/example"
    installed = {
        "example/package.json": _identity("a"),
        "example/LICENSE": _identity("b"),
        "example/NOTICE.txt": _identity("c"),
    }
    packages, _, gaps, count, _ = notices.evidence(
        graph=_graph(key), installed=installed, metadata={key: _package("example")}
    )
    assert count == 2
    assert packages[0]["notice_evidence_status"] == "multiple_scope_unverified"
    assert "multiple_notice_files_scope_unverified" in gaps


@pytest.mark.parametrize("matching_files, expected_status", [
    (0, "unmapped"), (1, "exact_bytes"), (2, "ambiguous"),
])
def test_opaque_asset_identity_never_proves_bundled_components(
    matching_files: int, expected_status: str
) -> None:
    key = "node_modules/example"
    matching = _identity("c")
    installed = {"example/package.json": _identity("a"), "example/LICENSE": _identity("b")}
    for index in range(matching_files):
        installed[f"example/worker-{index}.js"] = matching
    asset = {"kind": "opaque_worker_or_dependency_asset", "file_name": "assets/worker.js",
             "size_bytes": matching[0], "sha256": matching[1]}
    _, opaque, gaps, _, _ = notices.evidence(
        graph=_graph(key, assets=[asset]), installed=installed,
        metadata={key: _package("example")},
    )
    assert opaque[0]["mapping_status"] == expected_status
    assert opaque[0]["bundled_components_verified"] is False
    assert "opaque_bundled_component_provenance_unverified" in gaps
    assert ("opaque_asset_package_mapping_unresolved" in gaps) == (matching_files != 1)


def test_missing_selected_package_and_oversize_notice_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "node_modules/example"
    with pytest.raises(notices.FrontendNoticeError):
        notices.evidence(graph=_graph(key), installed={}, metadata={})
    monkeypatch.setattr(notices, "MAX_NOTICE_BYTES", 4)
    with pytest.raises(notices.FrontendNoticeError, match="frontend_notice_evidence_oversize"):
        notices.evidence(
            graph=_graph(key),
            installed={"example/package.json": _identity("a"), "example/LICENSE": _identity("b", 5)},
            metadata={key: _package("example")},
        )
