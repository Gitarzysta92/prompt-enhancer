"""Bound emitted bytes to a partial Vite/Rolldown module-input observation.

This verifies evidence consistency, not the truth of a plugin's transform
observations, complete dependency closure, or licence compliance.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import binascii
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .application_wheel_preparation import _read, _normalized_manifest

INVENTORY_NAME = "module-input-inventory.json"
_MAX_JSON = 2 * 1024 * 1024
_MAX_FILE = 16 * 1024 * 1024
_MAX_TOTAL = 128 * 1024 * 1024
_MAX_ENTRIES = 4096
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?\Z", re.ASCII)
_QUERIES = {"commonjs-proxy", "commonjs-es-import", "url", "raw", "worker", "sharedworker", "inline",
            "used", "import", "direct", "inline-css", "style-attr", "transform-only", "html-proxy"}
_ASSETS = {"html", "css", "vite_manifest", "static_asset", "opaque_worker_or_dependency_asset", "opaque_asset"}
_VIRTUALS = {"rolldown_runtime", "vite_dynamic_import_helper", "vite_modulepreload_polyfill",
             "vite_preload_helper", "vite_wasm_helper"}
_GAPS = {"source_manifest_binding_missing", "tooling_manifest_binding_missing",
         "opaque_asset_dependency_license_mapping_unverified", "transform_hook_observation_missing"}
_TOP = {"contract", "vite_version", "rolldown_version", "package_lock_sha256", "package_lock_size_bytes",
        "source_manifest_sha256", "tooling_manifest_sha256", "modules", "chunks", "assets",
        "actual_bundled_modules_only", "whole_production_lock_closure_claimed", "complete", "unresolved_gaps"}


class FrontendModuleInventoryError(ValueError):
    """A fixed, content-free evidence rejection."""


def _require(condition):
    if not condition:
        raise FrontendModuleInventoryError("frontend module inventory invalid")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _json(data):
    _require(0 < len(data) <= _MAX_JSON)
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise FrontendModuleInventoryError("frontend module inventory invalid") from None
    _require(isinstance(value, dict))
    return value


def _path(value):
    _require(isinstance(value, str) and 0 < len(value) <= 1024)
    parts = value.split("/")
    _require(not any(char in value for char in '\\:?\x00<>"|*') and not value.startswith("/"))
    _require(all(part not in {"", ".", ".."} and part == part.rstrip(". ") for part in parts))
    _require(all(32 <= ord(char) < 127 for char in value))
    reserved = {"con", "prn", "aux", "nul", *(f"com{x}" for x in range(1, 10)), *(f"lpt{x}" for x in range(1, 10))}
    _require(not any(part.split(".")[0].lower() in reserved for part in parts))
    return value


def _identity(size, digest):
    _require(type(size) is int and 0 <= size <= _MAX_FILE)
    _require(isinstance(digest, str) and _SHA.fullmatch(digest) is not None)


def _ordered(values, *, maximum=_MAX_ENTRIES):
    _require(isinstance(values, list) and len(values) <= maximum and all(isinstance(v, str) for v in values))
    _require(values == sorted(set(values)))
    return values


def _asset_kind(name):
    name = name.lower()
    if name == ".vite/manifest.json": return "vite_manifest"
    if name.endswith(".html"): return "html"
    if name.endswith(".css"): return "css"
    if PurePosixPath(name).suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".woff", ".woff2"}: return "static_asset"
    if PurePosixPath(name).suffix in {".js", ".mjs", ".wasm"}: return "opaque_worker_or_dependency_asset"
    return "opaque_asset"


def _integrity(value):
    _require(isinstance(value, str) and value.startswith("sha512-") and len(value) == 95)
    try:
        decoded = base64.b64decode(value[7:], validate=True)
    except (binascii.Error, ValueError):
        raise FrontendModuleInventoryError("frontend module inventory invalid") from None
    _require(len(decoded) == 64 and base64.b64encode(decoded).decode("ascii") == value[7:])


@dataclass(frozen=True)
class VerifiedFrontendModuleInventory:
    sha256: str
    size_bytes: int
    module_count: int
    package_instance_count: int
    chunk_count: int
    asset_count: int
    unresolved_gaps: tuple[str, ...]
    output_manifest_sha256: str
    complete: bool = False
    licence_closure_verified: bool = False


def verify_frontend_module_inventory(*, root: Path, files: list[Path], source_manifest,
                                     tooling_manifest, package_lock_bytes: bytes,
                                     verified_package_keys: frozenset[str]) -> VerifiedFrontendModuleInventory:
    """Verify all final outputs, exact lock identities and bidirectional membership.

    The caller supplies already revalidated source/tool manifests and revalidates
    them again after this read; environment digest strings alone are not proof.
    """
    names = {path.relative_to(root).as_posix() for path in files}
    _require(len(names) == len(files) and 0 < len(names) <= _MAX_ENTRIES and INVENTORY_NAME in names)
    for name in names:
        _path(name)
    raw = _read(root / INVENTORY_NAME, maximum=_MAX_JSON)
    graph = _json(raw)
    _require(set(graph) == _TOP and graph["contract"] == "vite-rolldown-module-input-inventory.v1")
    _require(graph["actual_bundled_modules_only"] is True and graph["whole_production_lock_closure_claimed"] is False
             and graph["complete"] is False)
    _require(graph["source_manifest_sha256"] == _sha(_normalized_manifest(source_manifest))
             and graph["tooling_manifest_sha256"] == _sha(_normalized_manifest(tooling_manifest)))
    _require(type(graph["package_lock_size_bytes"]) is int and graph["package_lock_size_bytes"] == len(package_lock_bytes)
             and graph["package_lock_sha256"] == _sha(package_lock_bytes))
    _require(source_manifest.get("package-lock.json") == (len(package_lock_bytes), _sha(package_lock_bytes)))
    lock = _json(package_lock_bytes)
    _require(type(lock.get("lockfileVersion")) is int and lock["lockfileVersion"] == 3
             and isinstance(lock.get("packages"), dict) and 0 < len(lock["packages"]) <= _MAX_ENTRIES + 1)
    packages = lock["packages"]
    for tool, field in (("vite", "vite_version"), ("rolldown", "rolldown_version")):
        version = graph[field]
        _require(isinstance(version, str) and len(version) <= 80 and _VERSION.fullmatch(version) is not None)
        _require(isinstance(packages.get("node_modules/" + tool), dict)
                 and packages["node_modules/" + tool].get("version") == version)
    chunks, assets, modules = graph["chunks"], graph["assets"], graph["modules"]
    _require(all(isinstance(items, list) and len(items) <= _MAX_ENTRIES for items in (chunks, assets, modules)))
    _require(bool(chunks) and bool(modules))
    emitted, chunk_counts, total = {}, {}, 0
    for items, fields, digest_key in (
        (chunks, {"file_name", "final_chunk_sha256", "size_bytes", "module_count"}, "final_chunk_sha256"),
        (assets, {"file_name", "sha256", "size_bytes", "kind"}, "sha256"),
    ):
        order = []
        for item in items:
            _require(isinstance(item, dict) and set(item) == fields)
            name = _path(item["file_name"])
            _require(name not in emitted and name != INVENTORY_NAME)
            _identity(item["size_bytes"], item[digest_key])
            total += item["size_bytes"]
            _require(total <= _MAX_TOTAL)
            if digest_key == "final_chunk_sha256":
                _require(PurePosixPath(name).suffix in {".js", ".mjs"})
                _require(type(item["module_count"]) is int and 0 <= item["module_count"] <= _MAX_ENTRIES)
                chunk_counts[name] = item["module_count"]
            else:
                _require(type(item["kind"]) is str and item["kind"] in _ASSETS and item["kind"] == _asset_kind(name))
            emitted[name] = (item["size_bytes"], item[digest_key])
            order.append(name)
        _ordered(order)
    _require(set(emitted) | {INVENTORY_NAME} == names)
    for name, (size, digest) in emitted.items():
        _read(root.joinpath(*PurePosixPath(name).parts), size=size, sha256=digest, maximum=_MAX_FILE)
    # Module identity and the fixed unresolved-gap contract are checked below.
    _require(isinstance(verified_package_keys, frozenset) and verified_package_keys <= packages.keys())
    return _verify_modules(graph, modules, chunk_counts, packages, source_manifest, raw, verified_package_keys,
                           _sha(_normalized_manifest({**emitted, INVENTORY_NAME: (len(raw), _sha(raw))})))


def _verify_modules(graph, modules, chunk_counts, packages, source_manifest, raw, verified_package_keys, output_digest):
    common = {"canonical_id", "kind", "query_kinds", "transform_hook_code_sha256",
              "transform_hook_code_size_bytes", "chunks"}
    extra = {"source": {"source_relative_path"}, "virtual": {"virtual_kind"},
             "package": {"package_instance_lock_key", "package_name", "version", "integrity", "dev",
                         "optional", "package_relative_path"}}
    membership = dict.fromkeys(chunk_counts, 0)
    identities, package_instances, total = [], set(), 0
    observation_missing = False
    opaque = any(asset["kind"] != "vite_manifest" for asset in graph["assets"])
    for module in modules:
        _require(isinstance(module, dict) and type(module.get("kind")) is str and module["kind"] in extra)
        kind = module["kind"]
        _require(set(module) == common | extra[kind])
        queries = _ordered(module["query_kinds"], maximum=len(_QUERIES))
        _require(set(queries) <= _QUERIES)
        opaque = opaque or bool(set(queries) & {"url", "worker", "sharedworker"})
        suffix = ":" + ",".join(queries)
        size, digest = module["transform_hook_code_size_bytes"], module["transform_hook_code_sha256"]
        if size is None or digest is None:
            _require(size is None and digest is None)
            observation_missing = True
        else:
            _identity(size, digest)
            total += size
        _require(total <= _MAX_TOTAL)
        chunks = _ordered(module["chunks"])
        _require(bool(chunks) and set(chunks) <= set(chunk_counts))
        for chunk in chunks:
            membership[chunk] += 1
        if kind == "source":
            relative = _path(module["source_relative_path"])
            _require(relative in source_manifest)
            canonical = "source:" + relative + suffix
        elif kind == "virtual":
            virtual = module["virtual_kind"]
            _require(type(virtual) is str and virtual in _VIRTUALS)
            canonical = "virtual:" + virtual + suffix
        else:
            key, relative = _path(module["package_instance_lock_key"]), _path(module["package_relative_path"])
            _require(key in verified_package_keys)
            _require(key.startswith("node_modules/") and key in packages and isinstance(packages[key], dict))
            entry = packages[key]
            logical = key + "/" + relative
            owners = [candidate for candidate in packages if isinstance(candidate, str) and candidate.startswith("node_modules/")
                      and (logical == candidate or logical.startswith(candidate + "/"))]
            _require(bool(owners) and max(owners, key=len) == key)
            name = key.rsplit("node_modules/", 1)[1]
            _require(re.fullmatch(r"(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+", name, flags=re.ASCII) is not None)
            _require(module["package_name"] == name and module["version"] == entry.get("version"))
            _require(isinstance(module["version"], str)
                     and re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}", module["version"], flags=re.ASCII) is not None)
            _integrity(module["integrity"])
            _require(module["integrity"] == entry.get("integrity"))
            for flag in ("dev", "optional"):
                _require(type(module[flag]) is bool and module[flag] is (entry.get(flag) is True))
                _require(flag not in entry or type(entry[flag]) is bool)
            canonical = "package:" + key + ":" + relative + suffix
            package_instances.add(key)
        _require(module["canonical_id"] == canonical)
        identities.append(canonical)
    _ordered(identities)
    _require(membership == chunk_counts)
    gaps = _ordered(graph["unresolved_gaps"], maximum=len(_GAPS))
    _require(set(gaps) <= _GAPS)
    # Release pins are required above, so missing-binding gaps are contradictory.
    expected_gaps = {"opaque_asset_dependency_license_mapping_unverified"} if opaque else set()
    if observation_missing:
        expected_gaps.add("transform_hook_observation_missing")
    _require(set(gaps) == expected_gaps)
    return VerifiedFrontendModuleInventory(_sha(raw), len(raw), len(modules), len(package_instances),
        len(chunk_counts), len(graph["assets"]), tuple(gaps), output_digest)
