"""Owned synthetic package metadata and simulated package-manager junctions."""
import json
import os
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure import frontend_package_bindings as bindings


def package(root, relative, name, version="1.0.0"):
    path = root / relative; path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")
    return path


def lock(keys):
    return json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "example"}, **{key: {"version": "1.0.0", "optional": True} for key in keys}}}).encode()


def resolve_map(monkeypatch, mapping):
    original = Path.resolve
    def resolve(path, strict=False):
        return mapping[path] if path in mapping else original(path, strict=strict)
    monkeypatch.setattr(Path, "resolve", resolve)


def test_ordinary_layout_and_private_mapping(tmp_path):
    root = tmp_path / "frontend"
    package(root, "node_modules/example", "example")
    result = bindings.collect_frontend_package_bindings(root, lock(["node_modules/example", "node_modules/missing"]))
    assert result.available_keys == frozenset({"node_modules/example"}) and result.missing_count == 1
    result.verify()
    output = tmp_path / "mapping.private.json"
    digest = result.write_mapping(output)
    assert len(digest) == 64
    result.verify_mapping(output)
    with pytest.raises(FileExistsError): result.write_mapping(output)
    output.write_bytes(b"changed")
    with pytest.raises(bindings.FrontendPackageBindingError): result.verify_mapping(output)


def test_pnpm_scoped_and_nested_keys_are_explicit(tmp_path, monkeypatch):
    root = tmp_path / "frontend"
    scoped_store = "@".join(("@example+library", "1.0.0")) + "(" + "@".join(("peer", "2.0.0")) + ")"
    nested_store = "@".join(("shared", "1.0.0"))
    scoped = package(root, f"node_modules/.pnpm/{scoped_store}/node_modules/@example/library", "@example/library")
    nested = package(root, f"node_modules/.pnpm/{nested_store}/node_modules/shared", "shared")
    keys = ["node_modules/@example/library", "node_modules/@example/library/node_modules/shared"]
    resolve_map(monkeypatch, {root / keys[0]: scoped, root / keys[1]: nested})
    result = bindings.collect_frontend_package_bindings(root, lock(keys))
    assert result.available_keys == frozenset(keys)
    result.verify()
    assert all(entry.physical is not None for entry in result.entries)
    # Digest excludes physical placement and stays equal for ordinary layout.
    other = tmp_path / "ordinary"
    package(other, keys[0], "@example/library"); package(other, keys[1], "shared")
    assert bindings.collect_frontend_package_bindings(other, lock(keys)).logical_digest == result.logical_digest


def test_ambiguous_physical_root_refused(tmp_path, monkeypatch):
    root = tmp_path / "frontend"; physical = package(root, "node_modules/.store/example", "example")
    resolve_map(monkeypatch, {root / "node_modules/example": physical, root / "node_modules/other": physical})
    with pytest.raises(bindings.FrontendPackageBindingError):
        bindings.collect_frontend_package_bindings(root, lock(["node_modules/example", "node_modules/other"]))


def test_outside_root_refused_before_metadata_read(tmp_path, monkeypatch):
    root = tmp_path / "frontend"; (root / "node_modules").mkdir(parents=True)
    outside = package(tmp_path, "outside", "example")
    resolve_map(monkeypatch, {root / "node_modules/example": outside})
    monkeypatch.setattr(bindings, "_metadata", lambda *a: pytest.fail("outside metadata must not be read"))
    with pytest.raises(bindings.FrontendPackageBindingError):
        bindings.collect_frontend_package_bindings(root, lock(["node_modules/example"]))


@pytest.mark.parametrize("change", ["repoint", "metadata", "name", "version", "missing_appears"])
def test_revalidation_refuses_changed_identity_or_metadata(tmp_path, monkeypatch, change):
    root = tmp_path / "frontend"
    first = package(root, "node_modules/.store/first", "example")
    second = package(root, "node_modules/.store/second", "example")
    logical = root / "node_modules/example"; mapping = {logical: first}
    resolve_map(monkeypatch, mapping)
    value = bindings.collect_frontend_package_bindings(root, lock(["node_modules/example", "node_modules/missing"]))
    if change == "repoint": mapping[logical] = second
    elif change == "metadata": (first / "package.json").write_text('{"name":"example","version":"1.0.0","extra":true}')
    elif change in {"name", "version"}:
        (first / "package.json").write_text(json.dumps({"name": "other" if change == "name" else "example",
            "version": "2.0.0" if change == "version" else "1.0.0"}))
    else: package(root, "node_modules/missing", "missing")
    with pytest.raises(bindings.FrontendPackageBindingError): value.verify()


def test_real_metadata_hardlink_is_supported(tmp_path):
    root = tmp_path / "frontend"; target = package(root, "node_modules/example", "example")
    os.link(target / "package.json", tmp_path / "metadata-hardlink.json")
    assert (target / "package.json").stat().st_nlink >= 2
    value = bindings.collect_frontend_package_bindings(root, lock(["node_modules/example"]))
    value.verify()


def test_reparse_metadata_refused_before_open(tmp_path, monkeypatch):
    root = tmp_path / "frontend"; physical = package(root, "node_modules/example", "example")
    target = physical / "package.json"; original = Path.lstat
    def lstat(path):
        info = original(path)
        if path == target:
            from types import SimpleNamespace
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(bindings.FrontendPackageBindingError):
        bindings.collect_frontend_package_bindings(root, lock(["node_modules/example"]))


def test_metadata_size_bound_precedes_open(tmp_path, monkeypatch):
    root = tmp_path / "frontend"; package(root, "node_modules/example", "example")
    monkeypatch.setattr(bindings, "_MAX_METADATA", 1)
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("overbudget metadata must not be opened"))
    with pytest.raises(bindings.FrontendPackageBindingError):
        bindings.collect_frontend_package_bindings(root, lock(["node_modules/example"]))
