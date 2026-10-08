"""Prepare the single, reviewed ``proxy-tools`` wheel from local inputs.

This module deliberately has no resolver or downloader. It verifies fixed
reviewed bytes before each input is consumed, executes the pinned interpreter
inside an owned, hidden process, and accepts only a deliberately small wheel
layout. Process ownership is not a network sandbox; callers must report that
network isolation is independently unproven.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path, PurePosixPath

from packaging.utils import canonicalize_name, parse_wheel_filename

from ..application.owned_process import OwnedProcessRunError, run_owned_process


_SOURCE_SHA = "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010"
_SOURCE_SIZE = 2978
_SETUPTOOLS_SHA = "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670"
_SETUPTOOLS_SIZE = 818216
_SETUPTOOLS_VERSION = "84.0.0"
_SOURCE_DATE_EPOCH = "1399328544"
_MAX_SOURCE_ARCHIVE_BYTES = 64 * 1024
_MAX_SOURCE_MEMBER_BYTES = 16 * 1024
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_MEMBER_BYTES = 16 * 1024
_MAX_PYTHON_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 32
_MAX_WHEEL_MEMBERS = 16

_SOURCE_MEMBERS: dict[str, tuple[int, str]] = {
    "PKG-INFO": (437, "89a85f6d9e74e8c391755c33e9529b078250e5365fb35ddaecf7cb7f227d18ec"),
    "README.rst": (1185, "1283ea54e21d1bdd171452aef9228d869fb2ad7bd3f88f0419493413dcb0096e"),
    "proxy_tools.egg-info/PKG-INFO": (437, "dd73a0ca763996298b717cf0a26198a07d0ae393849081c7aafefca6b08ddae7"),
    "proxy_tools.egg-info/SOURCES.txt": (217, "83eee4d6f62f339d4e66ab9a14108cecb55530a113073da55b63e7bfc60a4a84"),
    "proxy_tools.egg-info/dependency_links.txt": (1, "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b"),
    "proxy_tools.egg-info/not-zip-safe": (1, "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b"),
    "proxy_tools.egg-info/top_level.txt": (12, "5787cceffb627f279f0ca8c359b2a84462a455fee63525f3fbde19c2de0ff252"),
    "proxy_tools/__init__.py": (6409, "d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be"),
    "setup.cfg": (59, "063d04b462ef73e9d86e0b0ae49c4321b51984444a5a2a90aece1e0082b488ee"),
    "setup.py": (717, "2bb5e8e3c91a5cc5768310b67c2da6c7e5942f8d348402b5e9cee2fcce558b5b"),
}
_SOURCE_ROOT = "proxy_tools-0.1.0"
_WHEEL_FILES = frozenset({
    "proxy_tools/__init__.py",
    "proxy_tools-0.1.0.dist-info/METADATA",
    "proxy_tools-0.1.0.dist-info/WHEEL",
    "proxy_tools-0.1.0.dist-info/RECORD",
    "proxy_tools-0.1.0.dist-info/top_level.txt",
})
_WINDOWS_RESERVED_NAMES = frozenset({
    "con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
})
_BUILD_PROGRAM = (
    "import os,runpy,sys;"
    "site_directory,setup_file,output_directory=sys.argv[1:];"
    "sys.path.insert(0,site_directory);os.chdir(os.path.dirname(setup_file));"
    "sys.argv=[setup_file,'bdist_wheel','--dist-dir',output_directory];"
    "runpy.run_path(setup_file,run_name='__main__')"
)
_PYTHON_VERSION_PROGRAM = "import sys;print('.'.join(map(str,sys.version_info[:3])))"


class ProxyToolsWheelPreparationError(RuntimeError):
    """Content-free failure for the reviewed source build boundary."""


@dataclass(frozen=True, slots=True)
class PreparedProxyToolsWheel:
    filename: str
    sha256: str
    size_bytes: int
    python_sha256: str
    python_size_bytes: int
    python_version: str
    setuptools_sha256: str = _SETUPTOOLS_SHA
    setuptools_size_bytes: int = _SETUPTOOLS_SIZE
    setuptools_version: str = _SETUPTOOLS_VERSION
    source_sha256: str = _SOURCE_SHA
    source_size_bytes: int = _SOURCE_SIZE
    source_date_epoch: str = _SOURCE_DATE_EPOCH
    license_discrepancy_review_required: bool = True
    network_isolation_not_proven: bool = True
    python_runtime_dependencies_not_pinned: bool = True


def _fail(message: str, cause: Exception | None = None) -> None:
    if cause is None:
        raise ProxyToolsWheelPreparationError(message)
    raise ProxyToolsWheelPreparationError(message) from cause


def _regular_file_snapshot(path: Path, maximum_size: int) -> os.stat_result:
    try:
        snapshot = path.lstat()
    except OSError as error:
        _fail("proxy wheel input unavailable", error)
    is_reparse_point = bool(getattr(snapshot, "st_file_attributes", 0) & 0x400)
    if (not stat.S_ISREG(snapshot.st_mode) or stat.S_ISLNK(snapshot.st_mode)
            or is_reparse_point or snapshot.st_nlink != 1
            or not 0 < snapshot.st_size <= maximum_size):
        _fail("proxy wheel input unsafe")
    return snapshot


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare replacement-relevant fields without rejecting an atime update."""
    return (
        left.st_dev, left.st_ino, left.st_mode, left.st_nlink, left.st_size,
        left.st_mtime_ns, left.st_ctime_ns,
        getattr(left, "st_file_attributes", 0),
    ) == (
        right.st_dev, right.st_ino, right.st_mode, right.st_nlink, right.st_size,
        right.st_mtime_ns, right.st_ctime_ns,
        getattr(right, "st_file_attributes", 0),
    )


def _same_opened_file_snapshot(path_snapshot: os.stat_result,
                               opened_snapshot: os.stat_result) -> bool:
    """Bind an opened handle while allowing Windows extension-derived mode bits."""
    return (
        path_snapshot.st_dev, path_snapshot.st_ino, stat.S_IFMT(path_snapshot.st_mode),
        path_snapshot.st_nlink, path_snapshot.st_size, path_snapshot.st_mtime_ns,
        path_snapshot.st_ctime_ns, getattr(path_snapshot, "st_file_attributes", 0),
    ) == (
        opened_snapshot.st_dev, opened_snapshot.st_ino, stat.S_IFMT(opened_snapshot.st_mode),
        opened_snapshot.st_nlink, opened_snapshot.st_size, opened_snapshot.st_mtime_ns,
        opened_snapshot.st_ctime_ns, getattr(opened_snapshot, "st_file_attributes", 0),
    )


def _read_verified_file(path: Path, *, size: int, sha256: str, maximum_size: int) -> bytes:
    before = _regular_file_snapshot(path, maximum_size)
    if before.st_size != size:
        _fail("proxy wheel input does not match review")
    try:
        chunks = bytearray()
        with path.open("rb") as stream:
            if not _same_opened_file_snapshot(before, os.fstat(stream.fileno())):
                _fail("proxy wheel input does not match review")
            while chunk := stream.read(min(64 * 1024, maximum_size + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > maximum_size:
                    _fail("proxy wheel input does not match review")
        data = bytes(chunks)
    except OSError as error:
        _fail("proxy wheel input unavailable", error)
    after = _regular_file_snapshot(path, maximum_size)
    if (not _same_file_snapshot(after, before) or len(data) != size
            or hashlib.sha256(data).hexdigest() != sha256):
        _fail("proxy wheel input does not match review")
    return data


def _read_bounded_regular_file(path: Path, maximum_size: int) -> bytes:
    """Read a build output only after checking its type and bounded size."""
    before = _regular_file_snapshot(path, maximum_size)
    try:
        chunks = bytearray()
        with path.open("rb") as stream:
            if not _same_opened_file_snapshot(before, os.fstat(stream.fileno())):
                _fail("proxy wheel build output is invalid")
            while chunk := stream.read(min(64 * 1024, maximum_size + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > maximum_size:
                    _fail("proxy wheel build output is invalid")
        data = bytes(chunks)
    except OSError as error:
        _fail("proxy wheel build output is invalid", error)
    if (not _same_file_snapshot(_regular_file_snapshot(path, maximum_size), before)
            or len(data) != before.st_size):
        _fail("proxy wheel build output is invalid")
    return data


def _safe_archive_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    parts = path.parts
    if (not name or path.is_absolute() or "\\" in name or any(
            part in {"", ".", ".."} or ":" in part
            or part != part.rstrip(". ")
            or part.rstrip(". ").split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in parts)):
        _fail("proxy wheel archive layout is invalid")
    return parts


def _read_reviewed_source(source_archive: bytes) -> dict[str, bytes]:
    source: dict[str, bytes] = {}
    allowed_directories = {
        _SOURCE_ROOT, f"{_SOURCE_ROOT}/proxy_tools",
        f"{_SOURCE_ROOT}/proxy_tools.egg-info",
    }
    try:
        with tarfile.open(fileobj=io.BytesIO(source_archive), mode="r:gz") as archive:
            members = archive.getmembers()
            if not 1 <= len(members) <= _MAX_ARCHIVE_MEMBERS:
                raise ValueError("member count")
            for member in members:
                parts = _safe_archive_parts(member.name)
                if member.isdir():
                    if member.name not in allowed_directories:
                        raise ValueError("directory")
                    continue
                relative_name = "/".join(parts[1:])
                reviewed = _SOURCE_MEMBERS.get(relative_name)
                if (not member.isfile() or parts[0] != _SOURCE_ROOT or reviewed is None
                        or relative_name in source or member.size != reviewed[0]
                        or member.size > _MAX_SOURCE_MEMBER_BYTES):
                    raise ValueError("member")
                file_object = archive.extractfile(member)
                if file_object is None:
                    raise ValueError("unreadable member")
                member_bytes = file_object.read(_MAX_SOURCE_MEMBER_BYTES + 1)
                if (len(member_bytes) != reviewed[0]
                        or hashlib.sha256(member_bytes).hexdigest() != reviewed[1]):
                    raise ValueError("member digest")
                source[relative_name] = member_bytes
    except (OSError, ValueError, tarfile.TarError) as error:
        _fail("proxy wheel source is not reviewed", error)
    if set(source) != set(_SOURCE_MEMBERS):
        _fail("proxy wheel source is not reviewed")
    forbidden = (b"setup_requires", b"cmdclass", b"ext_modules", b"pyproject")
    if any(value in source["setup.py"] for value in forbidden):
        _fail("proxy wheel source is not reviewed")
    return source


def _extract_verified_setuptools(wheel_bytes: bytes, destination: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel:
            infos = wheel.infolist()
            if (not 1 <= len(infos) <= 4096
                    or sum(info.file_size for info in infos) > 16 * 1024 * 1024):
                raise ValueError("wheel limits")
            seen: set[str] = set()
            for info in infos:
                parts = _safe_archive_parts(info.filename)
                if (info.is_dir() or info.filename in seen
                        or stat.S_ISLNK(info.external_attr >> 16)
                        or info.file_size > _MAX_WHEEL_BYTES):
                    raise ValueError("wheel member")
                seen.add(info.filename)
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with wheel.open(info, "r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=64 * 1024)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        _fail("proxy wheel builder is invalid", error)


def _validate_setuptools_wheel(wheel_bytes: bytes, filename: str) -> None:
    try:
        distribution, version, _build, tags = parse_wheel_filename(filename)
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel:
            names = set(wheel.namelist())
        valid = (canonicalize_name(distribution) == "setuptools"
                 and str(version) == _SETUPTOOLS_VERSION
                 and {str(tag) for tag in tags} == {"py3-none-any"}
                 and "setuptools/__init__.py" in names)
    except (ValueError, zipfile.BadZipFile):
        valid = False
    if not valid:
        _fail("proxy wheel builder is invalid")


def _record_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _validate_record(wheel: zipfile.ZipFile, names: set[str]) -> None:
    record_name = "proxy_tools-0.1.0.dist-info/RECORD"
    try:
        rows = list(csv.reader(io.StringIO(wheel.read(record_name).decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error) as error:
        _fail("proxy wheel output is invalid", error)
    if len(rows) != len(names) or any(len(row) != 3 for row in rows):
        _fail("proxy wheel output is invalid")
    row_names = [row[0] for row in rows]
    if len(set(row_names)) != len(row_names) or set(row_names) != names:
        _fail("proxy wheel output is invalid")
    for member_name, digest, size in rows:
        if member_name == record_name:
            if digest or size:
                _fail("proxy wheel output is invalid")
            continue
        member = wheel.read(member_name)
        if digest != _record_digest(member) or size != str(len(member)):
            _fail("proxy wheel output is invalid")


def _validate_built_wheel(wheel_bytes: bytes, filename: str, python_sha256: str,
                          python_size: int, python_version: str) -> PreparedProxyToolsWheel:
    try:
        distribution, version, _build, tags = parse_wheel_filename(filename)
        tag_set = {str(tag) for tag in tags}
        if (canonicalize_name(distribution) != "proxy-tools" or str(version) != "0.1.0"
                or tag_set != {"py3-none-any"}
                or len(wheel_bytes) > _MAX_WHEEL_BYTES):
            raise ValueError("filename")
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel:
            infos = wheel.infolist()
            names = {info.filename for info in infos}
            if len(infos) != len(names) or names != _WHEEL_FILES or len(infos) > _MAX_WHEEL_MEMBERS:
                raise ValueError("layout")
            for info in infos:
                _safe_archive_parts(info.filename)
                if (info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)
                        or info.file_size > _MAX_WHEEL_MEMBER_BYTES):
                    raise ValueError("member")
            module = wheel.read("proxy_tools/__init__.py")
            if hashlib.sha256(module).hexdigest() != _SOURCE_MEMBERS["proxy_tools/__init__.py"][1]:
                raise ValueError("module digest")
            metadata = BytesParser(policy=compat32).parsebytes(
                wheel.read("proxy_tools-0.1.0.dist-info/METADATA"))
            wheel_metadata = BytesParser(policy=compat32).parsebytes(
                wheel.read("proxy_tools-0.1.0.dist-info/WHEEL"))
            metadata_valid = (canonicalize_name(metadata.get("Name", "")) == "proxy-tools"
                              and metadata.get("Version") == "0.1.0"
                              and metadata.get("License") == "MIT"
                              and metadata.get("Metadata-Version") is not None
                              and not metadata.get_all("Requires-Dist"))
            wheel_metadata_valid = (wheel_metadata.get("Wheel-Version") == "1.0"
                                    and wheel_metadata.get("Root-Is-Purelib") == "true"
                                    and set(wheel_metadata.get_all("Tag") or ()) == tag_set)
            if not metadata_valid or not wheel_metadata_valid:
                raise ValueError("metadata")
            if wheel.read("proxy_tools-0.1.0.dist-info/top_level.txt") != b"proxy_tools\n":
                raise ValueError("top level")
            _validate_record(wheel, names)
    except (KeyError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
        _fail("proxy wheel output is invalid", error)
    return PreparedProxyToolsWheel(filename, hashlib.sha256(wheel_bytes).hexdigest(),
                                   len(wheel_bytes), python_sha256, python_size,
                                   python_version)


def _write_source_tree(source: dict[str, bytes], destination: Path) -> None:
    for relative_name, data in source.items():
        target = destination.joinpath(*PurePosixPath(relative_name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _build_environment(build_root: Path) -> dict[str, str]:
    system_root = os.environ.get("SYSTEMROOT", os.environ.get("SystemRoot", ""))
    return {"PATH": "", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": _SOURCE_DATE_EPOCH, "SYSTEMROOT": system_root,
            "TEMP": str(build_root), "TMP": str(build_root)}


def _verify_python_version(executable: Path, expected_version: str,
                           build_root: Path) -> None:
    """Check the supplied executable in place; its DLL/stdlib closure is external."""
    snapshot = _regular_file_snapshot(executable, _MAX_PYTHON_BYTES)
    try:
        result = run_owned_process(
            (str(executable), "-I", "-c", _PYTHON_VERSION_PROGRAM),
            cwd=build_root,
            env=_build_environment(build_root),
            stdout_limit=128,
            stderr_limit=1024,
            timeout=20,
            maximum_active_processes=1,
        )
    except OwnedProcessRunError as error:
        _fail("proxy wheel builder version is invalid", error)
    if not _same_file_snapshot(_regular_file_snapshot(executable, _MAX_PYTHON_BYTES), snapshot):
        _fail("proxy wheel builder identity is invalid")
    expected_output = f"{expected_version}\n".encode("ascii")
    expected_windows_output = f"{expected_version}\r\n".encode("ascii")
    if result.returncode != 0 or result.stdout not in {expected_output, expected_windows_output}:
        _fail("proxy wheel builder version is invalid")


def _assert_link_free_tree(directory: Path, task_root: Path) -> None:
    """Confirm that only task-owned ordinary directories/files are removed."""
    try:
        resolved_root = task_root.resolve(strict=True)
        resolved_directory = directory.resolve(strict=True)
        if directory.parent.resolve(strict=True) != resolved_root:
            raise ValueError("outside task root")
        if resolved_directory.parent != resolved_root:
            raise ValueError("outside task root")
        stack = [directory]
        while stack:
            current = stack.pop()
            snapshot = current.lstat()
            if stat.S_ISLNK(snapshot.st_mode) or getattr(snapshot, "st_file_attributes", 0) & 0x400:
                raise ValueError("link")
            if not stat.S_ISDIR(snapshot.st_mode):
                raise ValueError("not directory")
            with os.scandir(current) as entries:
                for entry in entries:
                    child_snapshot = entry.stat(follow_symlinks=False)
                    if (stat.S_ISLNK(child_snapshot.st_mode)
                            or getattr(child_snapshot, "st_file_attributes", 0) & 0x400):
                        raise ValueError("link")
                    if stat.S_ISDIR(child_snapshot.st_mode):
                        stack.append(Path(entry.path))
                    elif not stat.S_ISREG(child_snapshot.st_mode):
                        raise ValueError("special file")
    except (OSError, ValueError) as error:
        _fail("proxy wheel cleanup unconfirmed", error)


def _remove_task_owned_directory(directory: Path, task_root: Path) -> None:
    _assert_link_free_tree(directory, task_root)
    try:
        shutil.rmtree(directory)
    except OSError as error:
        _fail("proxy wheel cleanup unconfirmed", error)
    if directory.exists():
        _fail("proxy wheel cleanup unconfirmed")


def prepare_proxy_tools_wheel(*, source_archive: Path, python_executable: Path,
                              python_sha256: str, python_size_bytes: int, python_version: str,
                              setuptools_wheel: Path, destination: Path) -> PreparedProxyToolsWheel:
    """Build twice from the same verified bytes and publish only matching output."""
    if (isinstance(python_size_bytes, bool) or not isinstance(python_size_bytes, int)
            or not 0 < python_size_bytes <= _MAX_PYTHON_BYTES
            or not isinstance(python_sha256, str) or len(python_sha256) != 64
            or any(character not in "0123456789abcdef" for character in python_sha256)
            or not isinstance(python_version, str)
            or not python_version.count(".") == 2
            or any(not part.isdecimal() for part in python_version.split("."))):
        _fail("proxy wheel builder identity is invalid")
    source = _read_reviewed_source(_read_verified_file(
        Path(source_archive), size=_SOURCE_SIZE, sha256=_SOURCE_SHA,
        maximum_size=_MAX_SOURCE_ARCHIVE_BYTES))
    setuptools_bytes = _read_verified_file(
        Path(setuptools_wheel), size=_SETUPTOOLS_SIZE, sha256=_SETUPTOOLS_SHA,
        maximum_size=_MAX_WHEEL_BYTES)
    _validate_setuptools_wheel(setuptools_bytes, Path(setuptools_wheel).name)
    _read_verified_file(Path(python_executable), size=python_size_bytes,
                        sha256=python_sha256, maximum_size=_MAX_PYTHON_BYTES)
    destination_path = Path(destination)
    destination_leaf = destination_path.name
    if (".." in destination_path.parts or not destination_leaf
            or destination_leaf != destination_leaf.rstrip(". ")
            or destination_leaf.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES):
        _fail("proxy wheel destination is unavailable")
    output_directory = destination_path.absolute()
    if output_directory.exists() or output_directory.is_symlink() or output_directory.parent.is_symlink():
        _fail("proxy wheel destination is unavailable")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    _verify_python_version(Path(python_executable), python_version, output_directory.parent)
    temporary_roots: list[Path] = []
    builds: list[tuple[PreparedProxyToolsWheel, bytes]] = []
    try:
        for _build_number in range(2):
            build_root = Path(tempfile.mkdtemp(prefix=".proxy-tools-build-", dir=output_directory.parent))
            temporary_roots.append(build_root)
            source_directory, site_directory, distribution_directory = (
                build_root / "source", build_root / "site", build_root / "dist")
            source_directory.mkdir()
            site_directory.mkdir()
            distribution_directory.mkdir()
            _write_source_tree(source, source_directory)
            _extract_verified_setuptools(setuptools_bytes, site_directory)
            _read_verified_file(Path(python_executable), size=python_size_bytes,
                                sha256=python_sha256, maximum_size=_MAX_PYTHON_BYTES)
            try:
                result = run_owned_process(
                    (str(python_executable), "-I", "-c", _BUILD_PROGRAM, str(site_directory),
                     str(source_directory / "setup.py"), str(distribution_directory)),
                    cwd=source_directory, env=_build_environment(build_root), stdout_limit=16 * 1024,
                    stderr_limit=16 * 1024, timeout=60, maximum_active_processes=1)
            except OwnedProcessRunError as error:
                _fail("proxy wheel build failed", error)
            _read_verified_file(Path(python_executable), size=python_size_bytes,
                                sha256=python_sha256, maximum_size=_MAX_PYTHON_BYTES)
            build_outputs = list(distribution_directory.iterdir())
            wheel_files = [path for path in build_outputs if path.is_file()]
            if result.returncode != 0:
                _fail("proxy wheel build command failed")
            if (len(build_outputs) != 1 or len(wheel_files) != 1
                    or wheel_files[0].suffix != ".whl"):
                _fail("proxy wheel build output is invalid")
            wheel_bytes = _read_bounded_regular_file(wheel_files[0], _MAX_WHEEL_BYTES)
            builds.append((_validate_built_wheel(wheel_bytes, wheel_files[0].name,
                                                 python_sha256, python_size_bytes,
                                                 python_version), wheel_bytes))
        first_result, first_bytes = builds[0]
        second_result, second_bytes = builds[1]
        if first_result.filename != second_result.filename or first_bytes != second_bytes:
            _fail("proxy wheel build is not deterministic")
        try:
            output_directory.mkdir()  # The no-clobber publication primitive.
            (output_directory / first_result.filename).write_bytes(first_bytes)
        except OSError as error:
            _fail("proxy wheel destination is unavailable", error)
        return first_result
    finally:
        cleanup_failed = False
        for build_root in temporary_roots:
            try:
                _remove_task_owned_directory(build_root, output_directory.parent)
            except ProxyToolsWheelPreparationError:
                cleanup_failed = True
        if cleanup_failed:
            _fail("proxy wheel cleanup unconfirmed")


__all__ = ("PreparedProxyToolsWheel", "ProxyToolsWheelPreparationError",
           "prepare_proxy_tools_wheel")
