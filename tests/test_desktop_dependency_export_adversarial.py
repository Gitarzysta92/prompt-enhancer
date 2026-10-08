from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.desktop_dependency_export import (
    DesktopDependencyExportError,
    export_windows_desktop_requirements,
)
import prompt_enhancer.infrastructure.desktop_dependency_export as export_module
from prompt_enhancer.application.owned_process import (
    OwnedProcessResult,
    OwnedProcessRunError,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='synthetic'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return tmp_path


def _cli_module():  # type: ignore[no-untyped-def]
    path = Path(__file__).parents[1] / "scripts" / "export_windows_desktop_requirements.py"
    spec = importlib.util.spec_from_file_location("synthetic_desktop_export_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runner(output: bytes):
    def run(command: tuple[str, ...], cwd: Path) -> tuple[int, bytes, bytes]:
        assert command in {
            ("uv", "lock", "--check", "--offline", "--no-config", "--no-python-downloads"),
            ("uv", "export", "--frozen", "--offline", "--no-config", "--no-python-downloads", "--format", "requirements.txt", "--extra", "desktop", "--no-dev", "--no-default-groups", "--no-emit-project", "--no-annotate", "--no-header"),
        }
        assert cwd.is_dir()
        return (0, b"", b"") if command[1] == "lock" else (0, output, b"")
    return run


def test_input_hash_binds_bytes_to_the_opened_file_identity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = tmp_path / "reviewed.toml"
    substitute = tmp_path / "substitute.toml"
    reviewed.write_bytes(b"reviewed")
    substitute.write_bytes(b"attacker")
    real_open = Path.open

    def redirected_open(path: Path, *args: object, **kwargs: object) -> object:
        return real_open(substitute if path == reviewed else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", redirected_open)
    with pytest.raises(DesktopDependencyExportError, match="changed"):
        export_module._ordinary_hash(reviewed)


def test_valid_hashed_export_preserves_safe_marker_and_canonicalizes_order(tmp_path: Path) -> None:
    output = (
        f"pywebview==6.2.1 ; python_version >= '3.11' --hash=sha256:{HASH_B} --hash=sha256:{HASH_A}\n"
        f"cryptography==46.0.0 --hash=sha256:{HASH_A}\n"
    ).encode()
    result = export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner(output))
    assert result.requirements == (
        f"cryptography==46.0.0 --hash=sha256:{HASH_A}\n"
        f"pywebview==6.2.1 ; python_version >= '3.11' --hash=sha256:{HASH_A} --hash=sha256:{HASH_B}\n"
    )
    assert result.pyproject_sha256 == hashlib.sha256((tmp_path / "pyproject.toml").read_bytes()).hexdigest()


@pytest.mark.parametrize("line", [
    "package @ https://example.invalid/pkg.whl --hash=sha256:" + HASH_A,
    "package==1.0 --index-url https://example.invalid --hash=sha256:" + HASH_A,
    "package @ ./local.whl --hash=sha256:" + HASH_A,
    "-e ./local --hash=sha256:" + HASH_A,
    "package==1.0 --hash=sha256:" + HASH_A + " --index-url https://example.invalid",
    "package==1.0 ; python_version >>> '3.11' --hash=sha256:" + HASH_A,
    "package==1.0 --hash=sha256:" + HASH_A + " unexpected-suffix",
])
def test_export_rejects_urls_local_paths_and_option_injection(tmp_path: Path, line: str) -> None:
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner((line + "\n").encode()))


@pytest.mark.parametrize("line", [
    "package==1.0",
    "package>=1.0 --hash=sha256:" + HASH_A,
    "package==1.0 --hash=sha256:" + "g" * 64,
])
def test_export_rejects_unhashed_or_range_requirements(tmp_path: Path, line: str) -> None:
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner((line + "\n").encode()))


def test_export_rejects_bogus_exact_version(tmp_path: Path) -> None:
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner(f"package==nonsense --hash=sha256:{HASH_A}\n".encode()))


def test_export_rejects_same_package_marker_mix_without_type_error(tmp_path: Path) -> None:
    output = f"package==1.0 --hash=sha256:{HASH_A}\npackage==1.0 ; python_version >= '3.11' --hash=sha256:{HASH_A}\n".encode()
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner(output))


def test_export_rejects_duplicate_conflicting_entries(tmp_path: Path) -> None:
    output = f"package==1.0 --hash=sha256:{HASH_A}\npackage==2.0 --hash=sha256:{HASH_B}\n".encode()
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner(output))


def test_export_rejects_forbidden_non_desktop_dependency(tmp_path: Path) -> None:
    output = f"torch==2.0 --hash=sha256:{HASH_A}\n".encode()
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=_runner(output))


def test_export_sanitizes_nonzero_subprocess_failure(tmp_path: Path) -> None:
    def failed(_command: tuple[str, ...], _cwd: Path) -> tuple[int, bytes, bytes]:
        return 7, b"private command output", b"private local path"

    with pytest.raises(DesktopDependencyExportError, match="desktop dependency export failed"):
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=failed)


def test_export_sanitizes_runner_exception(tmp_path: Path) -> None:
    def failed(_command: tuple[str, ...], _cwd: Path) -> tuple[int, bytes, bytes]:
        raise OSError("EXAMPLE_PRIVATE_CANARY")

    with pytest.raises(DesktopDependencyExportError) as error:
        export_windows_desktop_requirements(repository_root=_repo(tmp_path), runner=failed)
    assert "EXAMPLE_PRIVATE_CANARY" not in str(error.value)


def test_export_rejects_source_lock_mutation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    output = f"package==1.0 --hash=sha256:{HASH_A}\n".encode()

    def mutating(_command: tuple[str, ...], cwd: Path) -> tuple[int, bytes, bytes]:
        (cwd / "uv.lock").write_text("changed\n", encoding="utf-8")
        return 0, output, b""

    with pytest.raises(DesktopDependencyExportError, match="inputs changed"):
        export_windows_desktop_requirements(repository_root=root, runner=mutating)


def test_export_rejects_symlinked_lockfile(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    target = tmp_path / "target.lock"
    target.write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "uv.lock").unlink()
    try:
        (tmp_path / "uv.lock").symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {type(error).__name__}")
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=root, runner=_runner(b"package==1.0 --hash=sha256:" + HASH_A.encode() + b"\n"))


def test_cli_success_is_plain_requirements_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _cli_module()
    monkeypatch.setattr(cli, "export_windows_desktop_requirements", lambda **_: type("Result", (), {"requirements": "pywebview==6.2.1 --hash=sha256:" + HASH_A + "\n"})())
    assert cli.main(["--repository-root", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "pywebview==6.2.1 --hash=sha256:" + HASH_A + "\n"
    assert captured.err == ""


def test_cli_argument_error_is_sanitized(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _cli_module()
    canary = "EXAMPLE_PRIVATE_CANARY_PATH"
    with pytest.raises(SystemExit) as error:
        cli.main(["--unknown", canary])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert canary not in captured.out + captured.err
    assert "windows_desktop_export_failed" in captured.err


def test_cli_runtime_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = _cli_module()

    def failed(**_: object):
        raise OSError("EXAMPLE_PRIVATE_CANARY")

    monkeypatch.setattr(cli, "export_windows_desktop_requirements", failed)
    assert cli.main(["--repository-root", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "windows_desktop_export_failed"
    assert "EXAMPLE_PRIVATE_CANARY" not in captured.err


def test_run_delegates_to_shared_owned_process_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: dict[str, object] = {}

    def owned(command: tuple[str, ...], **kwargs: object) -> OwnedProcessResult:
        observed["command"] = command
        observed.update(kwargs)
        return OwnedProcessResult(0, stdout=b"synthetic stdout", stderr=b"synthetic stderr")

    monkeypatch.setattr(export_module, "_export_environment", lambda: {"PATH": "synthetic"})
    monkeypatch.setattr(export_module, "run_owned_process", owned)

    assert export_module._run(("uv", "lock", "--check"), tmp_path) == (
        0,
        b"synthetic stdout",
        b"synthetic stderr",
    )
    assert observed == {
        "command": ("uv", "lock", "--check"),
        "cwd": tmp_path,
        "env": {"PATH": "synthetic"},
        "stdout_limit": export_module._MAX_OUTPUT,
        "stderr_limit": export_module._MAX_OUTPUT,
        "timeout": export_module._TIMEOUT_SECONDS,
        "maximum_active_processes": 1,
    }


def test_run_redacts_owned_process_cleanup_and_limit_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failed(*_args: object, **_kwargs: object) -> OwnedProcessResult:
        raise OwnedProcessRunError("owned_process_stdout_limit")

    monkeypatch.setattr(export_module, "run_owned_process", failed)
    with pytest.raises(DesktopDependencyExportError) as error:
        export_module._run(("uv", "export"), tmp_path)
    assert str(error.value) == "desktop dependency export failed"
    assert "owned_process_stdout_limit" not in str(error.value)


def test_export_child_environment_excludes_unrelated_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_SYNTHETIC_TOKEN", "synthetic-secret")
    monkeypatch.setenv("PATH", "synthetic-path")

    environment = export_module._export_environment()

    assert environment.get("PATH") == "synthetic-path"
    assert "PROMPT_ENHANCER_SYNTHETIC_TOKEN" not in environment
