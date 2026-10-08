"""Hash-bound frontend notice evidence, not a determination of obligations."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .frontend_dependency_preparation import absolute, closure, decode, digest, inventory, _read, _normalized_manifest
from .frontend_package_bindings import collect_frontend_package_bindings
from .frontend_module_inventory import verify_frontend_module_inventory, INVENTORY_NAME

MAX_NOTICE_BYTES = 16 * 1024**2
MAX_TOTAL_NOTICE_BYTES = 64 * 1024**2
MAX_NOTICES = 1024
MAX_REPORT_BYTES = 16 * 1024**2
NOTICE_NAME = re.compile(r"^(?:licen[cs]e|notice|copying|copyright)(?:[._-][a-z0-9._-]+)?$", re.I)


class FrontendNoticeError(ValueError):
    pass


def require(condition, code="frontend_notice_input_invalid"):
    if not condition:
        raise FrontendNoticeError(code)


def pinned(path, sha, maximum=MAX_REPORT_BYTES):
    require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha))
    data = _read(path, maximum=maximum)
    require(digest(data) == sha, "frontend_notice_input_changed")
    return data


def record(relative, identity):
    return {"relative_path": relative, "size_bytes": identity[0], "sha256": identity[1]}


def evidence(*, graph, installed, metadata):
    """Pure projection of already verified bytes; never infer bundled internals."""
    selected = sorted({m["package_instance_lock_key"] for m in graph["modules"] if m["kind"] == "package"})
    require(selected and len(selected) <= 4096)
    all_keys = sorted(metadata, key=len, reverse=True)
    def owner(relative):
        logical = "node_modules/" + relative
        return next((key for key in all_keys if logical.startswith(key + "/")), None)
    packages = []
    gaps = {"notice_obligations_not_determined", "installed_metadata_not_independent_tarball_proof"}
    notice_count = total = 0
    for key in selected:
        require(key in metadata)
        package = metadata[key]
        prefix = key.removeprefix("node_modules/") + "/"
        paths = sorted(name for name in installed if name.startswith(prefix) and owner(name) == key
                       and NOTICE_NAME.fullmatch(name.rsplit("/", 1)[-1]))
        for name in paths:
            size = installed[name][0]
            require(0 < size <= MAX_NOTICE_BYTES, "frontend_notice_evidence_oversize")
            total += size; notice_count += 1
            require(total <= MAX_TOTAL_NOTICE_BYTES and notice_count <= MAX_NOTICES, "frontend_notice_evidence_oversize")
        if not paths: gaps.add("package_notice_evidence_missing")
        if len(paths) > 1: gaps.add("multiple_notice_files_scope_unverified")
        declaration = package.get("license")
        if not (isinstance(declaration, str) and 0 < len(declaration) <= 256
                and re.fullmatch(r"[A-Za-z0-9().+ _-]+", declaration)):
            declaration = None
            gaps.add("package_license_declaration_unknown")
        packages.append({"package_instance_lock_key": key, "package_name": package["name"], "version": package["version"],
                         "license_declaration": declaration, "package_metadata": record(prefix + "package.json", installed[prefix + "package.json"]),
                         "notice_files": [record(name, installed[name]) for name in paths],
                         "notice_evidence_status": "missing" if not paths else "multiple_scope_unverified" if len(paths) > 1 else "present_obligations_unverified"})
    opaque = []
    for asset in graph["assets"]:
        if asset["kind"] != "opaque_worker_or_dependency_asset": continue
        matches = sorted(name for name, identity in installed.items() if identity == (asset["size_bytes"], asset["sha256"])
                         and owner(name) in selected)
        opaque.append({"asset": record(asset["file_name"], (asset["size_bytes"], asset["sha256"])),
                       "matching_package_files": [record(name, installed[name]) for name in matches],
                       "mapping_status": "exact_bytes" if len(matches) == 1 else "ambiguous" if matches else "unmapped",
                       "bundled_components_verified": False})
        gaps.add("opaque_bundled_component_provenance_unverified")
        if len(matches) != 1: gaps.add("opaque_asset_package_mapping_unresolved")
    return packages, opaque, sorted(gaps), notice_count, total


def build_inventory(*, dependencies_root, dashboard_root, dependency_provenance_sha256,
                    dashboard_manifest_sha256, graph_sha256):
    try:
        dep, dashboard = absolute(dependencies_root), absolute(dashboard_root)
        require(dep != dashboard and dep not in dashboard.parents and dashboard not in dep.parents)
        provenance_raw = pinned(dep / "provenance.json", dependency_provenance_sha256)
        provenance = decode(provenance_raw)
        require(provenance.get("contract") == "frontend-dependency-preparation.v1"
                and provenance.get("owned_cleanup_confirmed") is True
                and provenance.get("lifecycle_scripts_executed") is False
                and provenance.get("release_accepted") is False)
        source_raw = pinned(dep / "source-manifest.json", provenance["source_manifest_sha256"])
        installed_raw = pinned(dep / "dependency-manifest.json", provenance["installed_manifest_sha256"])
        tools_raw = _read(dep / "tooling-manifest.json", maximum=MAX_REPORT_BYTES)
        source, installed, tools = closure(source_raw), closure(installed_raw), closure(tools_raw)
        front = dep / "frontend"
        expected_front = {**source, **{"node_modules/" + key: value for key, value in installed.items()}}
        require(inventory(front) == expected_front, "frontend_notice_dependency_changed")
        for name, identity in tools.items(): require(expected_front.get(name) == identity)
        lock_raw = pinned(front / "package-lock.json", provenance["package_lock_sha256"])
        bindings = collect_frontend_package_bindings(front, lock_raw)
        require(bindings.logical_digest == provenance["logical_binding_sha256"])
        dash_raw = pinned(dashboard / "dashboard-manifest.json", dashboard_manifest_sha256)
        dash = closure(dash_raw)
        prefix = "src/prompt_enhancer/_resources/dashboard/"
        require(all(name.startswith(prefix) for name in dash))
        expected_dashboard = {name.removeprefix(prefix): value for name, value in dash.items()}
        require(inventory(dashboard) == {**expected_dashboard, "dashboard-manifest.json": (len(dash_raw), digest(dash_raw))})
        graph_raw = pinned(dashboard / INVENTORY_NAME, graph_sha256)
        verify_frontend_module_inventory(root=dashboard, files=[dashboard / name for name in expected_dashboard],
            source_manifest=source, tooling_manifest=tools, package_lock_bytes=lock_raw, verified_package_keys=bindings.available_keys)
        graph = decode(graph_raw)
        metadata = {}
        for key in sorted(bindings.available_keys):
            relative = key.removeprefix("node_modules/") + "/package.json"
            require(relative in installed)
            raw = pinned(front / key / "package.json", installed[relative][1], 1024**2)
            require(len(raw) == installed[relative][0])
            metadata[key] = decode(raw)
        packages, opaque, gaps, count, total = evidence(graph=graph, installed=installed, metadata=metadata)
        report = {"contract": "frontend-notice-evidence-inventory.v1", "dependency_provenance_sha256": dependency_provenance_sha256,
                  "installed_manifest_sha256": digest(installed_raw), "source_manifest_sha256": digest(source_raw),
                  "tooling_manifest_sha256": digest(tools_raw), "package_lock_sha256": digest(lock_raw),
                  "dashboard_manifest_sha256": dashboard_manifest_sha256, "module_inventory_sha256": graph_sha256,
                  "packages": packages, "opaque_assets": opaque, "package_count": len(packages), "notice_file_count": count,
                  "notice_bytes": total, "unresolved_gaps": gaps, "complete": False, "release_accepted": False,
                  "all_notice_obligations_verified": False, "independent_tarball_byte_proof": False}
        raw = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
        require(len(raw) <= MAX_REPORT_BYTES, "frontend_notice_report_oversize")
        bindings.verify()
        require(inventory(front) == expected_front and inventory(dashboard) ==
                {**expected_dashboard, "dashboard-manifest.json": (len(dash_raw), digest(dash_raw))}, "frontend_notice_input_changed")
        for name, original in (("provenance.json", provenance_raw), ("source-manifest.json", source_raw),
                               ("dependency-manifest.json", installed_raw), ("tooling-manifest.json", tools_raw)):
            require(_read(dep / name, maximum=MAX_REPORT_BYTES) == original, "frontend_notice_input_changed")
        return report, raw
    except FrontendNoticeError:
        raise
    except Exception:
        raise FrontendNoticeError("frontend_notice_input_invalid") from None


def prepare(*, output, **kwargs):
    try:
        target = absolute(output, external=True)
        require(not target.exists() and target.parent.is_dir())
        for name in ("dependencies_root", "dashboard_root"):
            root = absolute(kwargs[name])
            require(target != root and root not in target.parents and target not in root.parents)
        report, raw = build_inventory(**kwargs)
        with target.open("xb") as stream: stream.write(raw)
        require(_read(target, maximum=MAX_REPORT_BYTES) == raw, "frontend_notice_output_changed")
        return {"contract": report["contract"], "passed": True, "sha256": digest(raw), "size_bytes": len(raw),
                "package_count": report["package_count"], "notice_file_count": report["notice_file_count"],
                "opaque_assets": len(report["opaque_assets"]), "complete": False, "release_accepted": False}
    except FrontendNoticeError:
        raise
    except Exception:
        raise FrontendNoticeError("frontend_notice_output_failed") from None
