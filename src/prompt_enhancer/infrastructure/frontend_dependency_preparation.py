"""Prepare fresh npm-lock dependencies; never imply tarball or licence proof.

Only a caller-reviewed Node executable and complete npm distribution are executed.
The network-facing install is deliberately separate from offline dashboard builds.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
from urllib.parse import urlsplit

from ..application.owned_process import OwnedProcessRunError, run_owned_process
from ..application.paths.policy import classify_windows_path_text, validate_private_relative_parts
from ..application.build_evidence.manifest import (
    _ordinary_staged_files, _sha256_file, _validate_staged_relative_path,
)
from .application_wheel_preparation import _assert_link_free_ancestors, _read, _remove_owned, _normalized_manifest
from .frontend_dashboard_preparation import _manifest, _assert_source_inventory, _verify_tree, _read_root_file, _verify_node
from .frontend_package_bindings import collect_frontend_package_bindings

MAX_TOTAL = 8 * 1024**3
MAX_JSON = 16 * 1024**2
REPOSITORY = Path(__file__).resolve().parents[3]


class FrontendDependencyPreparationError(RuntimeError):
    """Content-free failure; partial output is never published."""


def require(condition, code="dependency_input_invalid"):
    if not condition:
        raise FrontendDependencyPreparationError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    require(len(raw) <= MAX_JSON)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: require(False))


def absolute(path, *, external=False):
    path = Path(path)
    # Reject network/device/drive-relative spellings before any filesystem call.
    require(classify_windows_path_text(os.fspath(path)) is None and path.is_absolute() and ".." not in path.parts)
    require(validate_private_relative_parts(PureWindowsPath(os.fspath(path)).parts[1:]) is None)
    if external:
        for forbidden in (REPOSITORY, Path.home()):
            require(path != forbidden and path not in forbidden.parents and forbidden not in path.parents)
    _assert_link_free_ancestors(path)
    return path


def pinned(path, size, sha, maximum=MAX_JSON):
    require(type(size) is int and 0 < size <= maximum and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha))
    return _read(absolute(path), size=size, sha256=sha, maximum=maximum)


def inventory(root):
    """Reuse the release walker's 50k-file/100k-entry bounds, then hash safely."""
    _assert_link_free_ancestors(root)
    files, _ = _ordinary_staged_files(root)
    require(sum(info.st_size for _, _, info in files) <= MAX_TOTAL, "dependency_tree_oversize")
    result = {}
    folded = set()
    for path, relative, info in files:
        name = str(relative)
        _validate_staged_relative_path(name)
        require(name.casefold() not in folded)
        folded.add(name.casefold())
        sha, size = _sha256_file(path, expected=info)
        result[name] = (size, sha)
    return result


def closure(raw):
    value = decode(raw)
    require(isinstance(value, dict) and 0 < len(value) <= 50000)
    result = {}
    folded = set()
    for name, item in value.items():
        _validate_staged_relative_path(name)
        require(name.casefold() not in folded)
        folded.add(name.casefold())
        require(isinstance(item, dict) and set(item) == {"size_bytes", "sha256"})
        size, sha = item["size_bytes"], item["sha256"]
        require(type(size) is int and 0 <= size <= 4 * 1024**3 and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha))
        result[name] = (size, sha)
    require(sum(s for s, _ in result.values()) <= MAX_TOTAL)
    return result


def registry_lock(package_raw, lock_raw):
    package, lock = decode(package_raw), decode(lock_raw)
    require(isinstance(package, dict) and isinstance(lock, dict) and lock.get("lockfileVersion") == 3)
    require(not package.get("workspaces") and "overrides" not in package)
    packages = lock.get("packages")
    require(isinstance(packages, dict) and "" in packages and 1 < len(packages) <= 4096)
    root = packages[""]
    require(isinstance(root, dict))
    for key in ("name", "version", "dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        require(package.get(key) == root.get(key))
    for name, entry in packages.items():
        require(isinstance(entry, dict))
        require("overrides" not in entry)
        for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            specs = entry.get(field, {})
            require(isinstance(specs, dict))
            for dependency, spec in specs.items():
                require(isinstance(dependency, str) and re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", dependency))
                # Registry tags and ordinary semver ranges only. Aliases and
                # workspace/file/git/URL specs require a separate reviewed policy.
                require(isinstance(spec, str) and 0 < len(spec) <= 256 and re.fullmatch(r"[A-Za-z0-9.*^~<>=|+ -]+", spec))
        if not name:
            continue
        _validate_staged_relative_path(name)
        require(name.startswith("node_modules/") and not entry.get("link"))
        for field in ("dev", "optional", "devOptional"):
            require(field not in entry or type(entry[field]) is bool)
        url = entry.get("resolved")
        require(isinstance(url, str) and len(url) <= 2048)
        parsed = urlsplit(url)
        require(parsed.scheme == "https" and parsed.netloc == "registry.npmjs.org" and not parsed.query and not parsed.fragment
                and parsed.path.startswith("/") and parsed.path.endswith(".tgz") and "%" not in url and "\\" not in url
                and not any(p in {".", ".."} for p in parsed.path.split("/")))
        sri = entry.get("integrity")
        require(isinstance(sri, str) and sri.startswith("sha512-"))
        try:
            decoded = base64.b64decode(sri[7:], validate=True)
        except ValueError:
            require(False)
        require(len(decoded) == 64 and base64.b64encode(decoded).decode("ascii") == sri[7:])
    return packages


def verify_configs(private):
    for name in ("user.npmrc", "global.npmrc"):
        require(_read(private / name, maximum=1) == b"", "dependency_config_changed")


def verify_frontend(frontend, sources):
    actual = inventory(frontend)
    require({k: v for k, v in actual.items() if not k.startswith("node_modules/")} == sources,
            "dependency_source_output_changed")
    return {k.removeprefix("node_modules/"): v for k, v in actual.items() if k.startswith("node_modules/")}


def environment(private):
    return {"SYSTEMROOT": os.environ.get("SYSTEMROOT", os.environ.get("SystemRoot", "")),
            "PATH": "", "HOME": str(private), "USERPROFILE": str(private),
            "APPDATA": str(private / "appdata"), "LOCALAPPDATA": str(private / "local"),
            "TEMP": str(private / "tmp"), "TMP": str(private / "tmp"),
            "NPM_CONFIG_USERCONFIG": str(private / "user.npmrc"),
            "NPM_CONFIG_GLOBALCONFIG": str(private / "global.npmrc"),
            "NPM_CONFIG_CACHE": str(private / "cache"), "NO_PROXY": "*"}


def command(node, npm, private):
    return [str(node), str(npm / "bin/npm-cli.js"), "ci", "--ignore-scripts", "--no-audit", "--no-fund",
            "--include=dev", "--include=optional", "--install-strategy=hoisted", "--bin-links=false",
            "--registry=https://registry.npmjs.org/", "--loglevel=error", "--progress=false", "--logs-max=0",
            "--fetch-retries=0", "--fetch-timeout=20000", "--maxsockets=4",
            "--userconfig=" + str(private / "user.npmrc"), "--globalconfig=" + str(private / "global.npmrc"),
            "--cache=" + str(private / "cache")]


def prepare_frontend_dependencies(*, frontend_root, source_manifest, source_manifest_size, source_manifest_sha256,
                                  node_executable, node_size, node_sha256, node_version,
                                  npm_root, npm_manifest, npm_manifest_size, npm_manifest_sha256, npm_version,
                                  destination):
    work = None
    cleanup_safe = True
    try:
        source = absolute(frontend_root)
        node = absolute(node_executable)
        npm = absolute(npm_root)
        output = absolute(destination, external=True)
        require(not output.exists() and output.parent.is_dir())
        for item in (source, npm, node.parent):
            require(output != item and output not in item.parents and item not in output.parents)
        source_raw = pinned(source_manifest, source_manifest_size, source_manifest_sha256)
        sources, parsed_raw = _manifest(Path(source_manifest))
        require(parsed_raw == source_raw)
        _assert_source_inventory(source, sources)
        _verify_tree(source, sources)
        npm_raw = pinned(npm_manifest, npm_manifest_size, npm_manifest_sha256)
        npm_files = closure(npm_raw)
        require({"package.json", "bin/npm-cli.js"} <= npm_files.keys() and inventory(npm) == npm_files)
        npm_package = decode(_read(npm / "package.json", maximum=1024**2))
        require(npm_package.get("name") == "npm" and npm_package.get("version") == npm_version)
        require(re.fullmatch(r"\d+\.\d+\.\d+", npm_version) and re.fullmatch(r"v\d+\.\d+\.\d+", node_version))
        _verify_node(node, node_size, node_sha256)
        package_raw = _read_root_file(source, "package.json", *sources["package.json"])
        lock_raw = _read_root_file(source, "package-lock.json", *sources["package-lock.json"])
        packages = registry_lock(package_raw, lock_raw)
        work = Path(tempfile.mkdtemp(prefix=".frontend-dependencies-", dir=output.parent))
        frontend, private = work / "frontend", work / "private"
        frontend.mkdir(); private.mkdir()
        for name in ("tmp", "appdata", "local", "cache"):
            (private / name).mkdir()
        for name in ("user.npmrc", "global.npmrc"):
            with (private / name).open("xb"):
                pass
        for name, identity in sources.items():
            target = frontend / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(_read_root_file(source, name, *identity))
        env = environment(private)
        version = run_owned_process([str(node), "--version"], cwd=frontend, env=env, timeout=20,
                                    stdout_limit=128, stderr_limit=128, maximum_active_processes=1)
        require(version.returncode == 0 and version.stderr == b"" and version.stdout in
                {(node_version + "\n").encode(), (node_version + "\r\n").encode()}, "dependency_node_version_invalid")
        _verify_node(node, node_size, node_sha256)
        require(inventory(npm) == npm_files, "dependency_npm_changed")
        _verify_tree(source, sources)
        require(inventory(frontend) == sources, "dependency_source_output_changed")
        verify_configs(private)
        result = run_owned_process(command(node, npm, private), cwd=frontend, env=env, timeout=180,
                                   stdout_limit=32768, stderr_limit=32768, maximum_active_processes=1)
        require(result.returncode == 0, "dependency_install_failed")
        del result
        _verify_tree(source, sources); _verify_tree(frontend, sources)
        _verify_node(node, node_size, node_sha256)
        require(inventory(npm) == npm_files, "dependency_npm_changed")
        require(pinned(source_manifest, source_manifest_size, source_manifest_sha256) == source_raw)
        require(pinned(npm_manifest, npm_manifest_size, npm_manifest_sha256) == npm_raw)
        require((frontend / "node_modules").is_dir(), "dependency_required_missing")
        bindings = collect_frontend_package_bindings(frontend, lock_raw)
        missing = set(packages) - {""} - set(bindings.available_keys)
        require(all(packages[key].get("optional") is True for key in missing), "dependency_required_missing")
        installed = verify_frontend(frontend, sources)
        tools = {"node_modules/" + name: installed[name] for name in ("typescript/bin/tsc", "vite/bin/vite.js")}
        bindings.verify()
        receipt = {"contract": "frontend-dependency-preparation.v1", "node_version": node_version, "npm_version": npm_version,
                   "node_sha256": node_sha256, "npm_manifest_sha256": npm_manifest_sha256,
                   "source_manifest_sha256": source_manifest_sha256, "package_lock_sha256": digest(lock_raw),
                   "installed_manifest_sha256": digest(_normalized_manifest(installed)), "installed_files": len(installed),
                   "installed_bytes": sum(s for s, _ in installed.values()), "missing_optional_packages": len(missing),
                   "logical_binding_sha256": bindings.logical_digest, "owned_cleanup_confirmed": True,
                   "lifecycle_scripts_executed": False, "independent_tarball_byte_proof": False,
                   "licence_closure_claimed": False, "release_accepted": False}
        published = {"source-manifest.json": source_raw, "tooling-manifest.json": _normalized_manifest(tools),
                          "dependency-manifest.json": _normalized_manifest(installed),
                          "provenance.json": (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()}
        for name, raw in published.items():
            with (work / name).open("xb") as stream:
                stream.write(raw)
        _remove_owned(private, work)
        # Recheck all final inputs/output, after hashing and before atomic publish.
        _verify_tree(source, sources); _verify_tree(frontend, sources); bindings.verify()
        _verify_node(node, node_size, node_sha256)
        require(inventory(npm) == npm_files and verify_frontend(frontend, sources) == installed)
        require(pinned(source_manifest, source_manifest_size, source_manifest_sha256) == source_raw)
        require(pinned(npm_manifest, npm_manifest_size, npm_manifest_sha256) == npm_raw)
        for name, raw in published.items():
            require(_read(work / name, maximum=MAX_JSON) == raw)
        expected_work = {"frontend/" + name: identity for name, identity in sources.items()}
        expected_work.update({"frontend/node_modules/" + name: identity for name, identity in installed.items()})
        expected_work.update({name: (len(raw), digest(raw)) for name, raw in published.items()})
        require(inventory(work) == expected_work, "dependency_publication_changed")
        require({entry.name for entry in work.iterdir()} == {"frontend", *published}, "dependency_publication_changed")
        require(not output.exists())
        work.rename(output)
        work = None
        return receipt
    except OwnedProcessRunError as error:
        code = error.code
        cleanup_safe = code != "owned_process_cleanup_unconfirmed"
        raise FrontendDependencyPreparationError(code if code in {
            "owned_process_timeout", "owned_process_stdout_limit", "owned_process_stderr_limit",
            "owned_process_cleanup_unconfirmed"} else "dependency_process_failed") from None
    except FrontendDependencyPreparationError:
        raise
    except Exception:
        raise FrontendDependencyPreparationError("dependency_preparation_failed") from None
    finally:
        if work is not None and cleanup_safe:
            try:
                _remove_owned(work, work.parent)
            except Exception:
                raise FrontendDependencyPreparationError("dependency_cleanup_unconfirmed") from None
