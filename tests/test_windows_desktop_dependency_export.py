from __future__ import annotations

from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.desktop_dependency_export import (
    DesktopDependencyExportError, export_windows_desktop_requirements,
)


HASH_A, HASH_B = "a" * 64, "b" * 64
OUTPUT = (
    f"pywebview==6.2.1 ; sys_platform == 'win32' \\\n    --hash=sha256:{HASH_A} \\\n    --hash=sha256:{HASH_B}\n"
    f"pywin32==311 ; sys_platform == 'win32' \\\n    --hash=sha256:{HASH_B}\n"
).encode()


def _root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='synthetic'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    return tmp_path


def _runner(output: bytes = OUTPUT):
    calls: list[tuple[str, ...]] = []
    def run(command: tuple[str, ...], root: Path):
        calls.append(command)
        return (0, b"", b"") if command[1] == "lock" else (0, output, b"")
    return calls, run


def test_export_uses_offline_checked_desktop_recipe_and_normalizes_hashes(tmp_path: Path) -> None:
    calls, runner = _runner()
    exported = export_windows_desktop_requirements(repository_root=_root(tmp_path), runner=runner)
    assert len(calls) == 2
    assert calls[0] == ("uv", "lock", "--check", "--offline", "--no-config", "--no-python-downloads")
    assert "--extra" in calls[1] and calls[1][calls[1].index("--extra") + 1] == "desktop"
    assert all(flag in calls[1] for flag in ("--frozen", "--offline", "--no-config", "--no-dev", "--no-default-groups", "--no-emit-project", "--no-annotate", "--no-header", "--no-python-downloads"))
    assert "pywebview==6.2.1" in exported.requirements and "--hash=sha256:" in exported.requirements
    assert "torch" not in exported.requirements and "pytest" not in exported.requirements


@pytest.mark.parametrize("output", [
    b"pywebview==6.2.1\n",
    b"-e ./private\n",
    b"pywebview @ https://example.invalid/x --hash=sha256:" + HASH_A.encode() + b"\n",
    b"pywebview==not-a-version --hash=sha256:" + HASH_A.encode() + b"\n",
    b"pywebview==6.2.1 --hash=sha256:" + HASH_A.encode() + b"\npywebview==6.2.2 --hash=sha256:" + HASH_B.encode() + b"\n",
    b"torch==2.0 --hash=sha256:" + HASH_A.encode() + b"\n",
])
def test_export_rejects_unsafe_or_unhashed_output(tmp_path: Path, output: bytes) -> None:
    _calls, runner = _runner(output)
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_root(tmp_path), runner=runner)


def test_export_rejects_runner_failure_truncation_and_lock_mutation(tmp_path: Path) -> None:
    root = _root(tmp_path)
    def failed(command: tuple[str, ...], path: Path): return (1, b"", b"private stderr")
    with pytest.raises(DesktopDependencyExportError): export_windows_desktop_requirements(repository_root=root, runner=failed)
    _calls, oversized = _runner(b"x" * (8 * 1024 * 1024 + 1))
    with pytest.raises(DesktopDependencyExportError): export_windows_desktop_requirements(repository_root=root, runner=oversized)
    count = 0
    def mutate(command: tuple[str, ...], path: Path):
        nonlocal count; count += 1
        if count == 2: (path / "uv.lock").write_text("changed")
        return (0, b"", b"") if command[1] == "lock" else (0, OUTPUT, b"")
    with pytest.raises(DesktopDependencyExportError): export_windows_desktop_requirements(repository_root=root, runner=mutate)


def test_export_allows_distinct_conditional_versions_but_not_same_marker_duplicates(tmp_path: Path) -> None:
    conditional = (
        b"pywebview==6.2.1 ; sys_platform == 'win32' --hash=sha256:" + HASH_A.encode() + b"\n"
        b"pywebview==6.2.2 ; sys_platform == 'darwin' --hash=sha256:" + HASH_B.encode() + b"\n"
    )
    _calls, runner = _runner(conditional)
    assert export_windows_desktop_requirements(repository_root=_root(tmp_path), runner=runner).requirements.count("pywebview==") == 2
    duplicate = conditional + b"pywebview==6.2.3 ; sys_platform == 'win32' --hash=sha256:" + HASH_B.encode() + b"\n"
    _calls, runner = _runner(duplicate)
    with pytest.raises(DesktopDependencyExportError):
        export_windows_desktop_requirements(repository_root=_root(tmp_path), runner=runner)
