"""Offline, lock-bound export of the reviewed desktop dependency extra."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Callable

from packaging.markers import Marker, InvalidMarker
from packaging.version import InvalidVersion, Version

from ..application.owned_process import OwnedProcessRunError, run_owned_process


_MAX_OUTPUT = 8 * 1024 * 1024
_TIMEOUT_SECONDS = 60
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})$")
_REQUIREMENT = re.compile(r"^([a-z0-9][a-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.!+\-]{0,127})(?:\s*;\s*([A-Za-z0-9_ .!=<>'\"()\-]+))?$")
_FORBIDDEN = frozenset({"torch", "torchvision", "torchaudio", "transformers", "bitsandbytes", "pytest", "ruff", "mypy", "hypothesis"})
_ENVIRONMENT_ALLOWLIST = frozenset({
    "APPDATA", "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA",
    "PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP",
    "USERPROFILE", "WINDIR",
})


class DesktopDependencyExportError(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class DesktopDependencyExport:
    requirements: str
    pyproject_sha256: str
    lockfile_sha256: str


def _same_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev == right.st_dev and left.st_ino == right.st_ino
            and left.st_mode == right.st_mode
            and left.st_nlink == right.st_nlink and left.st_size == right.st_size
            and left.st_mtime_ns == right.st_mtime_ns and left.st_ctime_ns == right.st_ctime_ns
            and getattr(left, "st_file_attributes", 0)
            == getattr(right, "st_file_attributes", 0))


def _same_opened_snapshot(path_snapshot: os.stat_result,
                          opened_snapshot: os.stat_result) -> bool:
    return (
        path_snapshot.st_dev, path_snapshot.st_ino, stat.S_IFMT(path_snapshot.st_mode),
        path_snapshot.st_nlink, path_snapshot.st_size, path_snapshot.st_mtime_ns,
        path_snapshot.st_ctime_ns, getattr(path_snapshot, "st_file_attributes", 0),
    ) == (
        opened_snapshot.st_dev, opened_snapshot.st_ino, stat.S_IFMT(opened_snapshot.st_mode),
        opened_snapshot.st_nlink, opened_snapshot.st_size, opened_snapshot.st_mtime_ns,
        opened_snapshot.st_ctime_ns, getattr(opened_snapshot, "st_file_attributes", 0),
    )


def _ordinary_hash(path: Path) -> str:
    try: metadata = path.lstat()
    except OSError as error: raise DesktopDependencyExportError("desktop dependency export input is unavailable") from error
    if (not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
        or metadata.st_nlink != 1):
        raise DesktopDependencyExportError("desktop dependency export input is unsafe")
    digest = hashlib.sha256(); size = 0
    try:
        with path.open("rb") as stream:
            if not _same_opened_snapshot(metadata, os.fstat(stream.fileno())):
                raise DesktopDependencyExportError("desktop dependency export input changed")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > _MAX_OUTPUT * 8: raise DesktopDependencyExportError("desktop dependency export input is too large")
                digest.update(chunk)
    except OSError as error: raise DesktopDependencyExportError("desktop dependency export input is unavailable") from error
    try: after = path.lstat()
    except OSError as error: raise DesktopDependencyExportError("desktop dependency export input is unavailable") from error
    if not _same_snapshot(metadata, after): raise DesktopDependencyExportError("desktop dependency export input changed")
    return digest.hexdigest()


def _ordinary_directory_ancestors(path: Path) -> None:
    current = path
    while True:
        try: metadata = current.lstat()
        except OSError as error: raise DesktopDependencyExportError("desktop dependency export input is unavailable") from error
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400):
            raise DesktopDependencyExportError("desktop dependency export input is unsafe")
        if current.parent == current: return
        current = current.parent


def _export_environment() -> dict[str, str]:
    """Pass only local runtime locations needed by the offline exporter."""

    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _ENVIRONMENT_ALLOWLIST and "\0" not in value
    }


def _run(command: tuple[str, ...], cwd: Path) -> tuple[int, bytes, bytes]:
    """Run ``uv`` within the shared hidden, descendant-owned process boundary."""

    try:
        result = run_owned_process(
            command,
            cwd=cwd,
            env=_export_environment(),
            stdout_limit=_MAX_OUTPUT,
            stderr_limit=_MAX_OUTPUT,
            timeout=_TIMEOUT_SECONDS,
            maximum_active_processes=1,
        )
    except (OSError, OwnedProcessRunError, ValueError):
        raise DesktopDependencyExportError("desktop dependency export failed") from None
    return result.returncode, result.stdout, result.stderr


def _normalize(output: bytes) -> str:
    if len(output) > _MAX_OUTPUT: raise DesktopDependencyExportError("desktop dependency export output is too large")
    try: text = output.decode("utf-8", "strict")
    except UnicodeDecodeError as error: raise DesktopDependencyExportError("desktop dependency export output is invalid") from error
    records: list[tuple[str, str, str | None, tuple[str, ...]]] = []
    pending = ""
    for raw in text.splitlines():
        if not raw or raw.startswith("#") or raw.startswith("-"):
            raise DesktopDependencyExportError("desktop dependency export output is invalid")
        if raw.endswith("\\"):
            pending += raw[:-1].strip() + " "
            continue
        logical = (pending + raw.strip()).strip(); pending = ""
        parts = logical.split()
        if not parts: raise DesktopDependencyExportError("desktop dependency export output is invalid")
        # Parse the first requirement and optional marker without allowing any
        # URL, editable, option, local-path, or arbitrary requirement syntax.
        requirement = logical.split(" --hash=", 1)[0].strip()
        match = _REQUIREMENT.fullmatch(requirement)
        hashes = tuple(sorted(item.group(1) for token in logical.split() if (item := _HASH.fullmatch(token))))
        hash_tokens = [token for token in logical.split() if token.startswith("--hash=")]
        if (match is None or not hashes or len(hashes) != len(hash_tokens)
            or logical.split() != requirement.split() + hash_tokens):
            raise DesktopDependencyExportError("desktop dependency export output is invalid")
        if match.group(3) is not None:
            try: Marker(match.group(3))
            except InvalidMarker as error: raise DesktopDependencyExportError("desktop dependency export output is invalid") from error
        try: Version(match.group(2))
        except InvalidVersion as error: raise DesktopDependencyExportError("desktop dependency export output is invalid") from error
        name = re.sub(r"[_.-]+", "-", match.group(1)).casefold()
        if name in _FORBIDDEN: raise DesktopDependencyExportError("desktop dependency export output is not desktop-only")
        records.append((name, match.group(2), match.group(3), hashes))
    names_to_markers: dict[str, set[str | None]] = {}
    for name, _version, marker, _hashes in records:
        names_to_markers.setdefault(name, set()).add(marker)
    if (pending or not records or len({(item[0], item[2]) for item in records}) != len(records)
        or any(None in markers and len(markers) > 1 for markers in names_to_markers.values())):
        raise DesktopDependencyExportError("desktop dependency export output is invalid")
    rendered = []
    for name, version, marker, hashes in sorted(records, key=lambda item: (item[0], item[1], item[2] or "")):
        head = f"{name}=={version}" + ("" if marker is None else f" ; {marker}")
        rendered.append(head + " " + " ".join(f"--hash=sha256:{item}" for item in hashes))
    return "\n".join(rendered) + "\n"


def export_windows_desktop_requirements(*, repository_root: Path,
                                        runner: Callable[[tuple[str, ...], Path], tuple[int, bytes, bytes]] = _run) -> DesktopDependencyExport:
    root = Path(repository_root).absolute()
    _ordinary_directory_ancestors(root)
    pyproject, lockfile = root / "pyproject.toml", root / "uv.lock"
    before_project, before_lock = _ordinary_hash(pyproject), _ordinary_hash(lockfile)
    check_command = ("uv", "lock", "--check", "--offline", "--no-config", "--no-python-downloads")
    try: check_code, _check_output, _check_error = runner(check_command, root)
    except Exception as error: raise DesktopDependencyExportError("desktop dependency export failed") from error
    if check_code != 0: raise DesktopDependencyExportError("desktop dependency export failed")
    command = ("uv", "export", "--frozen", "--offline", "--no-config", "--no-python-downloads", "--format", "requirements.txt",
               "--extra", "desktop", "--no-dev", "--no-default-groups", "--no-emit-project", "--no-annotate", "--no-header")
    try: code, output, _stderr = runner(command, root)
    except Exception as error: raise DesktopDependencyExportError("desktop dependency export failed") from error
    if code != 0: raise DesktopDependencyExportError("desktop dependency export failed")
    requirements = _normalize(output)
    if _ordinary_hash(pyproject) != before_project or _ordinary_hash(lockfile) != before_lock:
        raise DesktopDependencyExportError("desktop dependency export inputs changed")
    return DesktopDependencyExport(requirements, before_project, before_lock)
