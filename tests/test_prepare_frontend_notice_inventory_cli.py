"""Direct, synthetic CLI checks for frontend notice inventory preparation."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.frontend_notice_inventory import FrontendNoticeError
from prompt_enhancer.infrastructure.application_wheel_preparation import _normalized_manifest
from prompt_enhancer.infrastructure.frontend_package_bindings import collect_frontend_package_bindings
from prompt_enhancer.infrastructure import frontend_module_inventory
from scripts import prepare_frontend_notice_inventory as cli


def _arguments(root: Path) -> list[str]:
    return [
        "--dependencies-root", str(root / "dependencies"),
        "--dashboard-root", str(root / "dashboard"),
        "--output", str(root / "notice.json"),
        "--dependency-provenance-sha256", "a" * 64,
        "--dashboard-manifest-sha256", "b" * 64,
        "--graph-sha256", "c" * 64,
    ]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(raw: bytes) -> tuple[int, str]:
    return len(raw), _sha(raw)


def _json_bytes(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + suffix).encode()


@pytest.fixture
def staged_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "unused-home"))
    dependencies = tmp_path / "dependencies"
    frontend = dependencies / "frontend"
    dashboard = tmp_path / "dashboard"
    (frontend / "src").mkdir(parents=True)
    dashboard.mkdir()

    integrity = "sha512-" + base64.b64encode(bytes(64)).decode()
    lock = _json_bytes({
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "synthetic-dashboard"},
            "node_modules/example": {"version": "1.0.0", "integrity": integrity},
            "node_modules/rolldown": {"version": "1.1.5", "integrity": integrity},
            "node_modules/vite": {"version": "8.1.5", "integrity": integrity},
        },
    })
    source_bytes = {"package-lock.json": lock, "src/main.tsx": b"export const example = 1;\n"}
    installed_bytes = {
        "example/LICENSE": b"Synthetic example licence notice.\n",
        "example/index.js": b"export const installedExample = true;\n",
        "example/package.json": _json_bytes({"license": "MIT", "name": "example", "version": "1.0.0"}),
        "rolldown/package.json": _json_bytes({"name": "rolldown", "version": "1.1.5"}),
        "vite/package.json": _json_bytes({"name": "vite", "version": "8.1.5"}),
    }
    for name, raw in source_bytes.items():
        target = frontend / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for name, raw in installed_bytes.items():
        target = frontend / "node_modules" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    source = {name: _identity(raw) for name, raw in source_bytes.items()}
    installed = {name: _identity(raw) for name, raw in installed_bytes.items()}
    tools = {"node_modules/vite/package.json": installed["vite/package.json"]}
    source_raw = _normalized_manifest(source)
    installed_raw = _normalized_manifest(installed)
    tools_raw = _normalized_manifest(tools)
    bindings = collect_frontend_package_bindings(frontend, lock)
    provenance = {
        "contract": "frontend-dependency-preparation.v1",
        "installed_manifest_sha256": _sha(installed_raw),
        "lifecycle_scripts_executed": False,
        "logical_binding_sha256": bindings.logical_digest,
        "owned_cleanup_confirmed": True,
        "package_lock_sha256": _sha(lock),
        "release_accepted": False,
        "source_manifest_sha256": _sha(source_raw),
    }
    published = {
        "dependency-manifest.json": installed_raw,
        "provenance.json": _json_bytes(provenance, newline=True),
        "source-manifest.json": source_raw,
        "tooling-manifest.json": tools_raw,
    }
    for name, raw in published.items():
        (dependencies / name).write_bytes(raw)

    chunk = b"export const synthetic = true;\n"
    (dashboard / "assets").mkdir()
    (dashboard / "assets/main.js").write_bytes(chunk)
    graph = {
        "actual_bundled_modules_only": True,
        "assets": [],
        "chunks": [{
            "file_name": "assets/main.js",
            "final_chunk_sha256": _sha(chunk),
            "module_count": 1,
            "size_bytes": len(chunk),
        }],
        "complete": False,
        "contract": "vite-rolldown-module-input-inventory.v1",
        "modules": [{
            "canonical_id": "package:node_modules/example:index.js:",
            "chunks": ["assets/main.js"],
            "dev": False,
            "integrity": integrity,
            "kind": "package",
            "optional": False,
            "package_instance_lock_key": "node_modules/example",
            "package_name": "example",
            "package_relative_path": "index.js",
            "query_kinds": [],
            "transform_hook_code_sha256": _sha(b"synthetic transform observation"),
            "transform_hook_code_size_bytes": len(b"synthetic transform observation"),
            "version": "1.0.0",
        }],
        "package_lock_sha256": _sha(lock),
        "package_lock_size_bytes": len(lock),
        "rolldown_version": "1.1.5",
        "source_manifest_sha256": _sha(_normalized_manifest(source)),
        "tooling_manifest_sha256": _sha(_normalized_manifest(tools)),
        "unresolved_gaps": [],
        "vite_version": "8.1.5",
        "whole_production_lock_closure_claimed": False,
    }
    graph_raw = _json_bytes(graph, newline=True)
    graph_path = dashboard / frontend_module_inventory.INVENTORY_NAME
    graph_path.write_bytes(graph_raw)
    dashboard_manifest = _normalized_manifest({
        "src/prompt_enhancer/_resources/dashboard/assets/main.js": _identity(chunk),
        "src/prompt_enhancer/_resources/dashboard/" + frontend_module_inventory.INVENTORY_NAME: _identity(graph_raw),
    })
    (dashboard / "dashboard-manifest.json").write_bytes(dashboard_manifest)
    output = tmp_path / "notice-inventory.json"
    arguments = [
        "--dependencies-root", str(dependencies),
        "--dashboard-root", str(dashboard),
        "--output", str(output),
        "--dependency-provenance-sha256", _sha(published["provenance.json"]),
        "--dashboard-manifest-sha256", _sha(dashboard_manifest),
        "--graph-sha256", _sha(graph_raw),
    ]
    return {
        "arguments": arguments,
        "dependencies": dependencies,
        "dashboard": dashboard,
        "output": output,
        "notice": installed_bytes["example/LICENSE"],
    }


def test_success_forwards_exact_required_arguments_and_partial_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    received = {}
    receipt = {
        "contract": "frontend-notice-evidence-inventory.v1",
        "passed": True,
        "complete": False,
        "release_accepted": False,
    }

    def prepare(**kwargs):
        received.update(kwargs)
        return receipt

    monkeypatch.setattr(cli, "prepare", prepare)
    assert cli.main(_arguments(tmp_path)) == 0
    assert received == {
        "dependencies_root": tmp_path / "dependencies",
        "dashboard_root": tmp_path / "dashboard",
        "output": tmp_path / "notice.json",
        "dependency_provenance_sha256": "a" * 64,
        "dashboard_manifest_sha256": "b" * 64,
        "graph_sha256": "c" * 64,
    }
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == receipt


def test_production_prepare_writes_partial_hash_bound_notice_inventory(
    staged_inputs: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = staged_inputs["arguments"]
    output = staged_inputs["output"]
    notice = staged_inputs["notice"]
    assert isinstance(arguments, list) and isinstance(output, Path) and isinstance(notice, bytes)

    assert cli.main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    stdout = captured.out
    receipt = json.loads(stdout)
    output_raw = output.read_bytes()
    report = json.loads(output_raw)

    assert receipt["passed"] is True
    assert receipt["sha256"] == _sha(output_raw)
    assert receipt["size_bytes"] == len(output_raw)
    assert receipt["complete"] is False
    assert receipt["release_accepted"] is False
    assert receipt["package_count"] == 1
    assert receipt["notice_file_count"] == 1
    assert report["complete"] is False
    assert report["release_accepted"] is False
    assert report["all_notice_obligations_verified"] is False
    assert "notice_obligations_not_determined" in report["unresolved_gaps"]
    assert report["packages"][0]["notice_files"] == [{
        "relative_path": "example/LICENSE",
        "sha256": _sha(notice),
        "size_bytes": len(notice),
    }]
    assert str(staged_inputs["dependencies"]) not in stdout
    assert str(staged_inputs["dashboard"]) not in stdout
    assert str(output) not in stdout


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [
        ("graph_hash", "frontend_notice_input_changed"),
        ("installed_notice", "frontend_notice_dependency_changed"),
    ],
)
def test_production_prepare_rejects_tampered_input_without_output(
    tamper: str,
    expected_code: str,
    staged_inputs: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = list(staged_inputs["arguments"])
    output = staged_inputs["output"]
    assert isinstance(output, Path)
    if tamper == "graph_hash":
        arguments[arguments.index("--graph-sha256") + 1] = "0" * 64
    else:
        dependencies = staged_inputs["dependencies"]
        assert isinstance(dependencies, Path)
        (dependencies / "frontend/node_modules/example/LICENSE").write_bytes(b"Synthetic changed notice.\n")

    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "passed": False,
        "error_code": expected_code,
    }
    assert not output.exists()


def test_production_prepare_refuses_existing_output_and_preserves_bytes(
    staged_inputs: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    output = staged_inputs["output"]
    assert isinstance(output, Path)
    original = b"synthetic existing output\n"
    output.write_bytes(original)

    assert cli.main(staged_inputs["arguments"]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "passed": False,
        "error_code": "frontend_notice_input_invalid",
    }
    assert output.read_bytes() == original


def test_real_prepare_missing_synthetic_inputs_fails_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "unused-home"))
    output = tmp_path / "notice.json"

    assert cli.main(_arguments(tmp_path)) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    receipt = json.loads(captured.out)
    assert receipt["passed"] is False
    assert receipt["error_code"] in cli.ERROR_CODES | {cli.FALLBACK_ERROR_CODE}
    assert not output.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--dependencies-root", "private-like-missing-marker"],
    ],
)
def test_malformed_arguments_are_content_free(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "prepare", lambda **kwargs: pytest.fail("prepare must not run"))
    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    output = captured.out
    assert "private-like" not in output
    assert json.loads(output) == {"passed": False, "error_code": "frontend_notice_cli_invalid"}


@pytest.mark.parametrize("kind", ["unknown", "abbreviation"])
def test_complete_arguments_refuse_unknown_and_abbreviated_options(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = _arguments(tmp_path)
    marker = "private-like-option-marker"
    if kind == "unknown":
        arguments.extend(["--unknown", marker])
    else:
        arguments[arguments.index("--dependencies-root")] = "--dependencies-r"
        arguments[arguments.index(str(tmp_path / "dependencies"))] = marker
    monkeypatch.setattr(cli, "prepare", lambda **kwargs: pytest.fail("prepare must not run"))

    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert marker not in captured.out
    assert json.loads(captured.out) == {
        "passed": False,
        "error_code": "frontend_notice_cli_invalid",
    }


def test_known_domain_failure_preserves_allowlisted_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "prepare",
        lambda **kwargs: (_ for _ in ()).throw(FrontendNoticeError("frontend_notice_input_changed")),
    )
    assert cli.main(_arguments(tmp_path)) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "passed": False,
        "error_code": "frontend_notice_input_changed",
    }


@pytest.mark.parametrize(
    "failure",
    [
        FrontendNoticeError("private-like-domain-marker"),
        RuntimeError("private-like-runtime-marker"),
        OSError("private-like-path-marker"),
    ],
)
def test_unknown_failures_are_sanitized(
    failure: Exception,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "prepare", lambda **kwargs: (_ for _ in ()).throw(failure))
    assert cli.main(_arguments(tmp_path)) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    output = captured.out
    assert "private-like" not in output
    assert json.loads(output) == {"passed": False, "error_code": "frontend_notice_failed"}
