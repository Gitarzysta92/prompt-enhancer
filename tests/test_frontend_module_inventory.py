"""Synthetic emitted-output evidence tests; no Node, build or network."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure import frontend_module_inventory as inventory
from prompt_enhancer.infrastructure.application_wheel_preparation import _normalized_manifest, ApplicationWheelPreparationError


def h(data): return hashlib.sha256(data).hexdigest()


def lock_bytes():
    return json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "synthetic-dashboard"}, "node_modules/vite": {"version": "8.1.5", "integrity": "sha512-" + "A" * 86 + "=="},
        "node_modules/rolldown": {"version": "1.1.5", "integrity": "sha512-" + "A" * 86 + "=="},
        "node_modules/@example/library": {"version": "1.0.0", "integrity": "sha512-" + "A" * 86 + "=="},
    }}, sort_keys=True).encode()


def emit_inventory(root, source, tools, lock):
    graph = {"contract": "vite-rolldown-module-input-inventory.v1", "vite_version": "8.1.5", "rolldown_version": "1.1.5",
        "package_lock_sha256": h(lock), "package_lock_size_bytes": len(lock),
        "source_manifest_sha256": h(_normalized_manifest(source)), "tooling_manifest_sha256": h(_normalized_manifest(tools)),
        "modules": [{"canonical_id": "source:src/main.tsx:", "kind": "source", "query_kinds": [],
            "transform_hook_code_sha256": h(b"observed"), "transform_hook_code_size_bytes": 8,
            "chunks": ["assets/main.js"], "source_relative_path": "src/main.tsx"}],
        "chunks": [], "assets": [], "actual_bundled_modules_only": True,
        "whole_production_lock_closure_claimed": False, "complete": False,
        "unresolved_gaps": ["opaque_asset_dependency_license_mapping_unverified"]}
    for path in sorted(root.rglob("*")):
        if not path.is_file(): continue
        name = path.relative_to(root).as_posix()
        if name == inventory.INVENTORY_NAME: continue
        data = path.read_bytes()
        if name == "assets/main.js":
            graph["chunks"].append({"file_name": name, "final_chunk_sha256": h(data), "size_bytes": len(data), "module_count": 1})
        else:
            graph["assets"].append({"file_name": name, "sha256": h(data), "size_bytes": len(data), "kind": inventory._asset_kind(name)})
    save(root, graph)
    return graph


def save(root, graph):
    (root / inventory.INVENTORY_NAME).write_bytes(json.dumps(graph, separators=(",", ":")).encode() + b"\n")


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / "dashboard"; (root / "assets").mkdir(parents=True); (root / ".vite").mkdir()
    for name, content in {"index.html": b"synthetic", "assets/main.js": b"export const example=1;",
        "assets/main.css": b"body{}", ".vite/manifest.json": b"{}", "assets/example.worker.mjs": b"/* synthetic worker */"}.items():
        (root / name).write_bytes(content)
    lock = lock_bytes()
    source = {"package-lock.json": (len(lock), h(lock)), "src/main.tsx": (1, h(b"x")),
              "src/build/viteModuleInputInventory.ts": (1, h(b"p"))}
    tools = {"node_modules/vite/bin/vite.js": (1, h(b"v"))}
    graph = emit_inventory(root, source, tools, lock)
    return root, source, tools, lock, graph


def verify(sample):
    root, source, tools, lock, _ = sample
    return inventory.verify_frontend_module_inventory(root=root, files=[p for p in root.rglob("*") if p.is_file()],
        source_manifest=source, tooling_manifest=tools, package_lock_bytes=lock,
        verified_package_keys=frozenset(key for key in json.loads(lock)["packages"] if key))


def test_success_preserves_partial_claim(sample):
    result = verify(sample)
    assert result.module_count == 1 and result.chunk_count == 1 and result.asset_count == 4
    assert not result.complete and not result.licence_closure_verified
    assert result.unresolved_gaps == ("opaque_asset_dependency_license_mapping_unverified",)


@pytest.mark.parametrize("kind", ["package", "virtual"])
def test_supported_module_kinds(sample, kind):
    root, _, _, _, graph = sample
    base = graph["modules"][0]; del base["source_relative_path"]
    if kind == "package":
        base.update(kind="package", canonical_id="package:node_modules/@example/library:lib/index.js:",
            package_instance_lock_key="node_modules/@example/library", package_name="@example/library",
            version="1.0.0", integrity="sha512-" + "A" * 86 + "==", dev=False, optional=False, package_relative_path="lib/index.js")
    else:
        base.update(kind="virtual", canonical_id="virtual:rolldown_runtime:", virtual_kind="rolldown_runtime")
    save(root, graph)
    assert verify(sample).package_instance_count == (1 if kind == "package" else 0)
    if kind == "package":
        _, source, tools, lock, _ = sample
        with pytest.raises(inventory.FrontendModuleInventoryError):
            inventory.verify_frontend_module_inventory(root=root,files=[p for p in root.rglob('*') if p.is_file()],
                source_manifest=source,tooling_manifest=tools,package_lock_bytes=lock,verified_package_keys=frozenset())


@pytest.mark.parametrize("field,bad", [("source_manifest_sha256", None), ("tooling_manifest_sha256", "0" * 64),
    ("package_lock_sha256", "0" * 64), ("package_lock_size_bytes", True), ("vite_version", "8.0.0"),
    ("rolldown_version", "4.23.0"), ("complete", True), ("actual_bundled_modules_only", False),
    ("whole_production_lock_closure_claimed", True), ("unresolved_gaps", []), ("raw_path", "private")])
def test_top_level_bindings_and_claims(sample, field, bad):
    root, _, _, _, graph = sample; graph[field] = bad; save(root, graph)
    with pytest.raises(inventory.FrontendModuleInventoryError): verify(sample)


@pytest.mark.parametrize("kind", ["hash", "missing", "extra", "chunk_count", "asset_kind", "duplicate"])
def test_final_emitted_partition_and_bytes(sample, kind):
    root, _, _, _, graph = sample
    if kind == "hash": (root / "assets/main.js").write_bytes(b"changed")
    elif kind == "missing": graph["assets"].pop()
    elif kind == "extra": (root / "assets/extra.js").write_bytes(b"extra")
    elif kind == "chunk_count": graph["chunks"][0]["module_count"] = 2
    elif kind == "asset_kind": graph["assets"][1]["kind"] = "vite_manifest"
    else: graph["chunks"].append(copy.deepcopy(graph["chunks"][0]))
    save(root, graph)
    with pytest.raises((inventory.FrontendModuleInventoryError, ApplicationWheelPreparationError)): verify(sample)


@pytest.mark.parametrize("field,bad", [("canonical_id", "source:other:"), ("source_relative_path", "src/missing.ts"),
    ("query_kinds", ["url=private"]), ("query_kinds", ["url", "url"]), ("chunks", []),
    ("chunks", ["assets/missing.js"]), ("transform_hook_code_sha256", None),
    ("transform_hook_code_size_bytes", True), ("transform_hook_code_size_bytes", 16 * 1024 * 1024 + 1),
    ("raw_source", "private")])
def test_module_contract_rejects_unknown_or_unbound(sample, field, bad):
    root, _, _, _, graph = sample; graph["modules"][0][field] = bad; save(root, graph)
    with pytest.raises(inventory.FrontendModuleInventoryError): verify(sample)


@pytest.mark.parametrize("name", ["../outside", "a\\b", "C:/example", "//example/share", "a?b", "a*b", 'a"b',
    "a<b", "a>b", "a|b", "con.txt", "a. ", "a//b", "a/./b", "a\x00b"])
def test_paths_refused_before_read(sample, monkeypatch, name):
    root, _, _, _, graph = sample; graph["chunks"][0]["file_name"] = name; save(root, graph)
    original = inventory._read
    def read(path, **kwargs):
        assert path.name == inventory.INVENTORY_NAME, "unsafe path must not reach filesystem"
        return original(path, **kwargs)
    monkeypatch.setattr(inventory, "_read", read)
    with pytest.raises(inventory.FrontendModuleInventoryError): verify(sample)


@pytest.mark.parametrize("kind", ["duplicate", "utf16", "bom", "nan", "oversize", "missing"])
def test_json_boundary(sample, kind):
    root, _, _, _, graph = sample; target = root / inventory.INVENTORY_NAME
    if kind == "missing": target.unlink()
    elif kind == "duplicate": target.write_bytes(target.read_bytes().replace(b'"complete":false', b'"complete":false,"complete":false'))
    elif kind == "utf16": target.write_bytes(json.dumps(graph).encode("utf-16"))
    elif kind == "bom": target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes())
    elif kind == "nan": graph["chunks"][0]["size_bytes"] = float("nan"); save(root, graph)
    else: target.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises((inventory.FrontendModuleInventoryError, ApplicationWheelPreparationError)): verify(sample)


@pytest.mark.parametrize("bad", ["sha512-" + "A" * 88, "sha512-" + "A" * 16,
    "sha512-" + "A" * 84 + "====", "sha512-" + "A" * 85 + "B==", "sha256-" + "A" * 86 + "=="])
def test_sri_requires_canonical_sha512(bad):
    with pytest.raises(inventory.FrontendModuleInventoryError): inventory._integrity(bad)


def test_parent_cannot_claim_nested_package_module(sample):
    root, source, tools, lock, graph = sample
    value = json.loads(lock)
    parent = "node_modules/@example/library"
    value["packages"][parent + "/node_modules/child"] = {"version": "2.0.0", "integrity": "sha512-" + "A" * 86 + "=="}
    lock = json.dumps(value).encode()
    source["package-lock.json"] = (len(lock), h(lock))
    graph["source_manifest_sha256"] = h(_normalized_manifest(source))
    graph.update(package_lock_sha256=h(lock), package_lock_size_bytes=len(lock))
    module = graph["modules"][0]; del module["source_relative_path"]
    module.update(kind="package", canonical_id="package:" + parent + ":node_modules/child/index.js:",
        package_instance_lock_key=parent, package_name="@example/library", version="1.0.0",
        integrity="sha512-" + "A" * 86 + "==", dev=False, optional=False, package_relative_path="node_modules/child/index.js")
    save(root, graph)
    with pytest.raises(inventory.FrontendModuleInventoryError): verify((root, source, tools, lock, graph))


@pytest.mark.parametrize("kind", ["empty", "duplicate", "unknown_virtual", "duplicate_chunk", "worker_gap", "observations_total"])
def test_graph_membership_and_partial_evidence(sample, kind):
    root, _, _, _, graph = sample
    if kind == "empty": graph["modules"] = []
    elif kind == "duplicate": graph["modules"] *= 2; graph["chunks"][0]["module_count"] = 2
    elif kind == "unknown_virtual":
        module = graph["modules"][0]; del module["source_relative_path"]
        module.update(kind="virtual", virtual_kind="unknown", canonical_id="virtual:unknown:")
    elif kind == "duplicate_chunk": graph["modules"][0]["chunks"] *= 2
    elif kind == "worker_gap": graph["unresolved_gaps"] = []
    else:
        graph["modules"] = [{**graph["modules"][0], "query_kinds": [query],
            "canonical_id": "source:src/main.tsx:" + query, "transform_hook_code_size_bytes": 16 * 1024 * 1024}
            for query in sorted(inventory._QUERIES)[:9]]
        graph["chunks"][0]["module_count"] = 9
    save(root, graph)
    with pytest.raises(inventory.FrontendModuleInventoryError): verify(sample)


def test_missing_observation_is_explicit_partial_evidence(sample):
    root, _, _, _, graph = sample
    graph["modules"][0].update(transform_hook_code_sha256=None, transform_hook_code_size_bytes=None)
    graph["unresolved_gaps"].append("transform_hook_observation_missing")
    save(root, graph)
    result = verify(sample)
    assert "transform_hook_observation_missing" in result.unresolved_gaps
    assert not result.complete and not result.licence_closure_verified


@pytest.mark.parametrize("kind", ["missing_gap", "false_gap", "hash_only", "size_only"])
def test_missing_observation_requires_exact_null_pair_and_gap(sample, kind):
    root, _, _, _, graph = sample
    if kind != "false_gap":
        graph["modules"][0].update(transform_hook_code_sha256=None, transform_hook_code_size_bytes=None)
    if kind != "missing_gap": graph["unresolved_gaps"].append("transform_hook_observation_missing")
    if kind == "hash_only": graph["modules"][0]["transform_hook_code_sha256"] = h(b"observed")
    if kind == "size_only": graph["modules"][0]["transform_hook_code_size_bytes"] = 8
    save(root, graph)
    with pytest.raises(inventory.FrontendModuleInventoryError): verify(sample)
