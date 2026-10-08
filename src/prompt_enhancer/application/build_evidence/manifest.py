"""Deterministic, public manifest generation for a synthetic staged tree."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
import stat
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ...domain import StrictModel
from ..paths.policy import classify_windows_path_text, validate_private_relative_parts


BUILD_MANIFEST_SCHEMA_VERSION = 1
BUILD_MANIFEST_GENERATOR_VERSION = "deterministic-public-build-manifest-v1"
MAX_STAGED_FILES = 50_000
MAX_STAGED_ENTRIES = 100_000
MAX_STAGED_FILE_BYTES = 4 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_PUBLIC_TOOL_VERSIONS = 64
MAX_LOCKFILE_HASHES = 256
NONDETERMINISTIC_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("filesystem_mtime", "timestamps are not artifact identity"),
    ("absolute_path", "host paths are private and non-reproducible"),
    ("hostname", "host identity is private and non-reproducible"),
    ("environment", "ambient variables are private and non-reproducible"),
)


class PublicToolVersion(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9_.-]{1,64}$")
    version: str = Field(pattern=r"^[A-Za-z0-9_.+\-]{1,96}$")


class NamedDigest(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,96}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class StagedFile(StrictModel):
    relative_path: str = Field(min_length=1, max_length=512, strict=True)
    size_bytes: int = Field(ge=0, le=MAX_STAGED_FILE_BYTES, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _validate_staged_relative_path(value)


def _validate_staged_relative_path(value: str) -> str:
    if ("\\" in value or any(character in '<>"|?*' for character in value)
            or any(ord(character) <= 31 or 127 <= ord(character) <= 159
                   for character in value)):
        raise ValueError("build path must use portable separators")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("build path must be a normalized relative path")
    path_rejection = validate_private_relative_parts(parts)
    if path_rejection is not None:
        raise ValueError("build path contains a Windows-ambiguous component")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value:
        raise ValueError("build path must be a normalized relative path")
    return value


def _require_unique_names(
    entries: tuple[PublicToolVersion, ...] | tuple[NamedDigest, ...],
    collection_name: str,
) -> None:
    names = [entry.name for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError(f"build manifest contains duplicate {collection_name} names")


class BuildManifest(StrictModel):
    schema_version: Literal[1] = BUILD_MANIFEST_SCHEMA_VERSION
    generator_version: Literal["deterministic-public-build-manifest-v1"] = (
        BUILD_MANIFEST_GENERATOR_VERSION
    )
    git_revision: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    tool_versions: tuple[PublicToolVersion, ...] = Field(max_length=MAX_PUBLIC_TOOL_VERSIONS)
    lockfile_hashes: tuple[NamedDigest, ...] = Field(max_length=MAX_LOCKFILE_HASHES)
    files: tuple[StagedFile, ...] = Field(max_length=MAX_STAGED_FILES)
    nondeterministic_exclusions: tuple[tuple[str, str], ...] = NONDETERMINISTIC_EXCLUSIONS
    distributable: Literal[False] = False

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_schema_version(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("build manifest schema version must be an integer")
        return value

    @model_validator(mode="after")
    def validate_unambiguous_collections(self) -> BuildManifest:
        _require_unique_names(self.tool_versions, "tool version")
        _require_unique_names(self.lockfile_hashes, "lockfile hash")
        if self.nondeterministic_exclusions != NONDETERMINISTIC_EXCLUSIONS:
            raise ValueError("build manifest exclusions must use the fixed public policy")
        normalized_paths = [
            tuple(component.casefold() for component in entry.relative_path.split("/"))
            for entry in self.files
        ]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("build manifest contains duplicate file paths")
        for earlier, later in zip(sorted(normalized_paths), sorted(normalized_paths)[1:]):
            if len(earlier) < len(later) and later[:len(earlier)] == earlier:
                raise ValueError("build manifest contains a file-directory path conflict")
        return self


def _validated_manifest(manifest: BuildManifest) -> BuildManifest:
    """Reapply model invariants after unchecked Pydantic copy construction."""

    return BuildManifest.model_validate(
        manifest.model_dump(mode="python", warnings=False)
    )


class DifferenceKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class ManifestDifference(StrictModel):
    relative_path: str
    kind: DifferenceKind
    first_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    second_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ManifestComparison(StrictModel):
    identical: bool
    differences: tuple[ManifestDifference, ...]


def canonical_json(value: StrictModel | Mapping[str, Any]) -> bytes:
    if isinstance(value, BuildManifest):
        payload = _validated_manifest(value).model_dump(mode="json")
    else:
        payload = value.model_dump(mode="json") if isinstance(value, StrictModel) else dict(value)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii") + b"\n"
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("canonical manifest exceeded the public size bound")
    return encoded


def _same_snapshot(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
        and stat.S_IFMT(first.st_mode) == stat.S_IFMT(second.st_mode)
        and first.st_nlink == second.st_nlink
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and first.st_ctime_ns == second.st_ctime_ns
    )


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def _ordinary_directory(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError("staging directory could not be inspected") from error
    if not stat.S_ISDIR(metadata.st_mode) or _is_link_or_reparse(metadata):
        raise ValueError("staging directory is not ordinary")
    return metadata


def _verify_directory_ancestors(staging_root: Path) -> None:
    current = staging_root
    while True:
        _ordinary_directory(current)
        if current.parent == current:
            return
        current = current.parent


def _lexical_absolute_staging_root(staging_root: Path) -> Path:
    try:
        raw_path = os.fspath(staging_root)
    except (OSError, TypeError, ValueError) as error:
        raise ValueError("staging root could not be inspected") from error
    if (".." in PurePath(raw_path).parts
            or ".." in PureWindowsPath(raw_path).parts):
        raise ValueError("staging root contains traversal")
    if classify_windows_path_text(raw_path) is not None:
        raise ValueError("staging root uses an ambiguous Windows path")
    try:
        return Path(os.path.abspath(raw_path))
    except (OSError, TypeError, ValueError) as error:
        raise ValueError("staging root could not be inspected") from error


def _sha256_file(path: Path, *, expected: os.stat_result) -> tuple[str, int]:
    try:
        before = path.lstat()
    except OSError as error:
        raise ValueError("staged file could not be inspected") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or _is_link_or_reparse(before)
        or before.st_nlink != 1
        or expected.st_size < 0
        or expected.st_size > MAX_STAGED_FILE_BYTES
        or not _same_snapshot(expected, before)
    ):
        raise ValueError("staged file changed or is not ordinary")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    size = 0
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("staged file could not be opened safely") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not _same_snapshot(before, opened)
        ):
            raise ValueError("staged file changed while it was opened")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > expected.st_size or size > MAX_STAGED_FILE_BYTES:
                    raise ValueError("staged file exceeded the build size bound")
                digest.update(chunk)
            after_open = os.fstat(stream.fileno())
    except OSError as error:
        raise ValueError("staged file could not be read safely") from error
    finally:
        if descriptor != -1:
            os.close(descriptor)
    try:
        after_path = path.lstat()
    except OSError as error:
        raise ValueError("staged file changed while it was hashed") from error
    if not _same_snapshot(before, after_open) or not _same_snapshot(before, after_path):
        raise ValueError("staged file changed while it was hashed")
    return digest.hexdigest(), size


def _ordinary_staged_files(
    staging_root: Path,
) -> tuple[
    list[tuple[Path, str, os.stat_result]],
    list[tuple[Path, os.stat_result]],
]:
    """Walk without descending through symlinks, junctions, or reparse points."""

    discovered: list[tuple[Path, str, os.stat_result]] = []
    directories: list[tuple[Path, os.stat_result]] = []
    pending: list[tuple[Path, PurePosixPath]] = [(staging_root, PurePosixPath())]
    entry_count = 0
    while pending:
        directory, relative_directory = pending.pop()
        before_directory = _ordinary_directory(directory)
        directories.append((directory, before_directory))
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entry_count += 1
                    if entry_count > MAX_STAGED_ENTRIES:
                        raise ValueError("staging tree exceeded the entry-count bound")
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        raise ValueError("staging entry could not be inspected") from error
                    if _is_link_or_reparse(metadata):
                        raise ValueError("staging tree contains a link or reparse point")
                    relative = relative_directory / entry.name
                    relative_text = _validate_staged_relative_path(relative.as_posix())
                    candidate = Path(entry.path)
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append((candidate, relative))
                    elif stat.S_ISREG(metadata.st_mode):
                        try:
                            file_metadata = candidate.lstat()
                        except OSError as error:
                            raise ValueError("staging file could not be inspected") from error
                        if (
                            _is_link_or_reparse(file_metadata)
                            or not stat.S_ISREG(file_metadata.st_mode)
                            or file_metadata.st_nlink != 1
                        ):
                            raise ValueError("staging tree contains a hardlinked file")
                        discovered.append((candidate, relative_text, file_metadata))
                        if len(discovered) > MAX_STAGED_FILES:
                            raise ValueError("staging tree exceeded the file-count bound")
                    else:
                        raise ValueError("staging tree contains a non-regular file")
        except OSError as error:
            raise ValueError("staging directory could not be inspected") from error
        if not _same_snapshot(before_directory, _ordinary_directory(directory)):
            raise ValueError("staging directory changed while it was inspected")
    return sorted(discovered, key=lambda item: item[1]), directories


def build_manifest(
    staging_root: Path,
    *,
    git_revision: str,
    tool_versions: Mapping[str, str],
    lockfile_hashes: Mapping[str, str],
) -> BuildManifest:
    """Hash ordinary files under a synthetic/public staging root.

    Symlinks, reparse points, special files, and changing files are rejected.
    The output intentionally contains neither timestamps nor absolute paths.
    """

    staging_root = _lexical_absolute_staging_root(staging_root)
    _verify_directory_ancestors(staging_root)
    files: list[StagedFile] = []
    discovered, directories = _ordinary_staged_files(staging_root)
    for candidate, relative, metadata in discovered:
        digest, size = _sha256_file(candidate, expected=metadata)
        files.append(StagedFile(relative_path=relative, size_bytes=size, sha256=digest))
    for candidate, _relative, metadata in discovered:
        try:
            after = candidate.lstat()
        except OSError as error:
            raise ValueError("staged file changed while it was hashed") from error
        if not _same_snapshot(metadata, after):
            raise ValueError("staged file changed while it was hashed")
    for directory, metadata in directories:
        if not _same_snapshot(metadata, _ordinary_directory(directory)):
            raise ValueError("staging directory changed while it was hashed")
    _verify_directory_ancestors(staging_root)
    manifest = BuildManifest(
        git_revision=git_revision,
        tool_versions=tuple(
            PublicToolVersion(name=name, version=version)
            for name, version in sorted(tool_versions.items())
        ),
        lockfile_hashes=tuple(
            NamedDigest(name=name, sha256=digest)
            for name, digest in sorted(lockfile_hashes.items())
        ),
        files=tuple(files),
    )
    canonical_json(manifest)
    return manifest


def compare_manifests(first: BuildManifest, second: BuildManifest) -> ManifestComparison:
    first = _validated_manifest(first)
    second = _validated_manifest(second)
    first_files = {entry.relative_path: entry for entry in first.files}
    second_files = {entry.relative_path: entry for entry in second.files}
    differences: list[ManifestDifference] = []
    for path in sorted(first_files.keys() | second_files.keys()):
        left = first_files.get(path)
        right = second_files.get(path)
        if left is None:
            differences.append(ManifestDifference(relative_path=path, kind=DifferenceKind.ADDED, second_sha256=right.sha256 if right else None))
        elif right is None:
            differences.append(ManifestDifference(relative_path=path, kind=DifferenceKind.REMOVED, first_sha256=left.sha256))
        elif left != right:
            differences.append(ManifestDifference(relative_path=path, kind=DifferenceKind.CHANGED, first_sha256=left.sha256, second_sha256=right.sha256))
    metadata_equal = (
        first.git_revision == second.git_revision
        and first.tool_versions == second.tool_versions
        and first.lockfile_hashes == second.lockfile_hashes
        and first.nondeterministic_exclusions == second.nondeterministic_exclusions
    )
    if not metadata_equal and not differences:
        differences.append(
            ManifestDifference(
                relative_path=".build-metadata",
                kind=DifferenceKind.CHANGED,
                first_sha256=hashlib.sha256(canonical_json(first)).hexdigest(),
                second_sha256=hashlib.sha256(canonical_json(second)).hexdigest(),
            )
        )
    return ManifestComparison(identical=not differences, differences=tuple(differences))
