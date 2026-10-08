from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import prepare_windows_stage_recipe as RECIPE


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_windows_stage_recipe.py"


def test_import_uses_tracked_candidate_without_generated_test_results() -> None:
    assert Path(RECIPE.__file__).resolve() == SCRIPT
    assert "test-results" not in SCRIPT.parts
    assert not hasattr(RECIPE, "acquire_windows_wheels")
    assert not hasattr(RECIPE, "stage_windows_wheels")


def test_historical_runtime_default_is_replaced_by_complete_explicit_inputs() -> None:
    with pytest.raises(ValueError, match="complete"):
        RECIPE.runtime_pin(None, None, None, None)


def test_explicit_patch_pin_is_preserved_as_one_bundle(tmp_path: Path) -> None:
    archive = (tmp_path / "python-3.13.15-embed-amd64.zip").resolve()
    pin = RECIPE.runtime_pin(archive, "3.13.15", "a" * 64, 11_009_825)
    assert pin == RECIPE.RuntimePin(archive, "3.13.15", "a" * 64, 11_009_825)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "3.12.9"},
        {"version": "3.13"},
        {"sha256": "A" * 64},
        {"sha256": "a" * 63},
        {"size_bytes": 0},
        {"size_bytes": True},
        {"version": "3.13.1000"},
        {"version": 31315},
        {"sha256": 64},
    ],
)
def test_invalid_runtime_pin_scalar_is_refused_for_an_otherwise_valid_pin(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    values: dict[str, object] = {
        "archive": (tmp_path / "archive.zip").resolve(),
        "version": "3.13.15",
        "sha256": "a" * 64,
        "size_bytes": 1,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        RECIPE.runtime_pin(**values)


def test_partial_runtime_pin_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="complete"):
        RECIPE.runtime_pin((tmp_path / "archive.zip").resolve(), None, None, None)


@pytest.mark.parametrize(
    "archive_text",
    [r"\\server\share\archive.zip", r"\\?\C:\archive.zip", r"\\.\C:\archive.zip"],
)
def test_windows_network_and_device_runtime_archives_are_refused(archive_text: str) -> None:
    with pytest.raises(ValueError):
        RECIPE.runtime_pin(Path(archive_text), "3.13.15", "a" * 64, 1)


def test_runtime_archive_traversal_is_refused(tmp_path: Path) -> None:
    archive = tmp_path.resolve() / "part" / ".." / "archive.zip"
    with pytest.raises(ValueError):
        RECIPE.runtime_pin(archive, "3.13.15", "a" * 64, 1)


def test_plan_propagates_patch_version_and_explicit_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_requirement = (
        "example-package==1.0 --hash=sha256:" + "c" * 64
        + " --hash=sha256:" + "e" * 64
    )
    export = RECIPE.DesktopDependencyExport(
        requirements=registry_requirement + "\n"
        + "proxy-tools==0.1.0 --hash=sha256:" + "d" * 64 + "\n",
        pyproject_sha256="a" * 64,
        lockfile_sha256="b" * 64,
    )
    captured: dict[str, object] = {}
    repository = tmp_path.resolve()
    proxy_wheel = (tmp_path / "proxy_tools-0.1.0-py3-none-any.whl").resolve()
    proxy_provenance = (tmp_path / "proxy-tools-provenance.json").resolve()

    def export_requirements(**kwargs: object) -> object:
        captured["repository_root"] = kwargs["repository_root"]
        return export

    monkeypatch.setattr(RECIPE, "export_windows_desktop_requirements", export_requirements)

    def prepare(**kwargs: object) -> object:
        captured["dependency_target"] = kwargs["target"]
        captured["proxy_tools_wheel"] = kwargs["proxy_tools_wheel"]
        captured["proxy_tools_provenance"] = kwargs["proxy_tools_provenance"]
        return SimpleNamespace(
            registry_wheels=(SimpleNamespace(package="example-package"),),
        )

    def inventory(**kwargs: object) -> object:
        captured["inventory_target"] = kwargs["target"]
        captured["inventory_requirements"] = kwargs["export"].requirements
        return SimpleNamespace()

    monkeypatch.setattr(RECIPE, "prepare_windows_dependencies", prepare)
    monkeypatch.setattr(RECIPE, "plan_windows_wheels", inventory)
    target, _, _ = RECIPE.plan(
        "3.13.15",
        repository_root=repository,
        proxy_tools_wheel=proxy_wheel,
        proxy_tools_provenance=proxy_provenance,
    )
    assert target.python_full_version == "3.13.15"
    assert captured == {
        "repository_root": repository,
        "dependency_target": target,
        "proxy_tools_wheel": proxy_wheel,
        "proxy_tools_provenance": proxy_provenance,
        "inventory_target": target,
        "inventory_requirements": registry_requirement + "\n",
    }


def test_review_cli_is_content_free_read_only_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = b"synthetic-runtime-archive"
    archive = (tmp_path / "archive.zip").resolve()
    archive.write_bytes(data)
    proxy_wheel = (tmp_path / "proxy_tools-0.1.0-py3-none-any.whl").resolve()
    proxy_provenance = (tmp_path / "proxy-tools-provenance.json").resolve()
    seen: list[tuple[str, Path, Path, Path]] = []
    report = SimpleNamespace(pyproject_sha256="a" * 64, lockfile_sha256="b" * 64)
    inventory = SimpleNamespace(artifacts=())

    def plan(version: str, *, repository_root: Path,
             proxy_tools_wheel: Path, proxy_tools_provenance: Path) -> tuple[object, object, object]:
        seen.append((version, repository_root, proxy_tools_wheel, proxy_tools_provenance))
        return object(), report, inventory

    monkeypatch.setattr(RECIPE, "plan", plan)
    monkeypatch.setattr(RECIPE, "report_json", lambda value: "{}")
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("review must not request network authority"),
    )
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert RECIPE.main([
        "--review",
        "--repository-root", str(tmp_path.resolve()),
        "--proxy-tools-wheel", str(proxy_wheel),
        "--proxy-tools-provenance", str(proxy_provenance),
        "--runtime-archive", str(archive),
        "--runtime-version", "3.13.15",
        "--runtime-sha256", hashlib.sha256(data).hexdigest(),
        "--runtime-size-bytes", str(len(data)),
    ]) == 0
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    payload = json.loads(capsys.readouterr().out)
    assert seen == [("3.13.15", tmp_path.resolve(), proxy_wheel, proxy_provenance)]
    assert payload["network_used"] is False
    assert payload["runtime_version"] == "3.13.15"
    assert payload["runtime_sha256"] == hashlib.sha256(data).hexdigest()
    assert payload["runtime_size_bytes"] == len(data)
    assert str(tmp_path) not in json.dumps(payload)
    assert after == before


def test_review_cli_rejects_all_missing_inputs() -> None:
    with pytest.raises(SystemExit, match="runtime pin must be complete"):
        RECIPE.main([])


def test_prepare_runtime_verifies_actual_file_and_propagates_the_same_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"synthetic-runtime-archive"
    archive = (tmp_path / "archive.zip").resolve()
    archive.write_bytes(data)
    pin = RECIPE.RuntimePin(
        archive,
        "3.13.15",
        hashlib.sha256(data).hexdigest(),
        len(data),
    )
    captured: dict[str, object] = {}

    def prepare(**kwargs: object) -> object:
        captured.update(kwargs)
        return "prepared"

    monkeypatch.setattr(RECIPE, "prepare_windows_python_runtime", prepare)
    destination = (tmp_path / "runtime").resolve()
    assert RECIPE.prepare_runtime(pin, destination) == "prepared"
    assert captured == {
        "archive": pin.archive,
        "expected_version": "3.13.15",
        "expected_architecture": "amd64",
        "expected_sha256": pin.sha256,
        "expected_size_bytes": pin.size_bytes,
        "destination": destination,
    }


def test_prepare_runtime_rejects_actual_file_mismatch_before_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = (tmp_path / "archive.zip").resolve()
    archive.write_bytes(b"nope")
    pin = RECIPE.RuntimePin(archive, "3.13.15", "0" * 64, 4)
    monkeypatch.setattr(
        RECIPE,
        "prepare_windows_python_runtime",
        lambda **kwargs: pytest.fail("preparation must not run after identity mismatch"),
    )
    with pytest.raises(SystemExit, match="runtime identity mismatch"):
        RECIPE.prepare_runtime(pin, (tmp_path / "runtime").resolve())


def test_prepare_runtime_revalidates_a_directly_constructed_pin(tmp_path: Path) -> None:
    pin = RECIPE.RuntimePin((tmp_path / "missing.zip").resolve(), "3.13.15", "A" * 64, 1)
    with pytest.raises(ValueError, match="invalid"):
        RECIPE.prepare_runtime(pin, (tmp_path / "runtime").resolve())
