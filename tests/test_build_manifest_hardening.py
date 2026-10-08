"""Synthetic regression tests for public build-manifest identity boundaries."""

from __future__ import annotations

import os
from pathlib import Path
import warnings

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.build_evidence.manifest import (
    BuildManifest,
    MAX_LOCKFILE_HASHES,
    MAX_PUBLIC_TOOL_VERSIONS,
    StagedFile,
    build_manifest,
    canonical_json,
    compare_manifests,
)
import prompt_enhancer.application.build_evidence.manifest as manifest_module


def _file(path: str, digest: str = "a" * 64) -> StagedFile:
    return StagedFile(relative_path=path, size_bytes=1, sha256=digest)


def _manifest(*files: StagedFile, **updates: object) -> BuildManifest:
    payload: dict[str, object] = {
        "git_revision": "b" * 40,
        "tool_versions": ({"name": "python", "version": "3.11.0"},),
        "lockfile_hashes": ({"name": "uv.lock", "sha256": "c" * 64},),
        "files": files,
    }
    payload.update(updates)
    return BuildManifest.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        "example.txt:stream",
        "folder\\file.txt",
        "/absolute.txt",
        "C:relative.txt",
        "folder//file.txt",
        "folder/./file.txt",
        "folder/../file.txt",
        "NUL.txt",
        "report. ",
        "report?.txt",
        "control\x1f.txt",
    ],
)
def test_staged_file_rejects_windows_ambiguous_or_noncanonical_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        _file(path)


def test_manifest_rejects_duplicate_exact_file_identity_before_comparison() -> None:
    with pytest.raises(ValidationError):
        _manifest(_file("example.txt"), _file("example.txt", "d" * 64))


@pytest.mark.parametrize(
    "files",
    [
        (_file("Folder/example.txt"), _file("folder/EXAMPLE.txt", "d" * 64)),
        (_file("package"), _file("package/module.py", "d" * 64)),
        (_file("Folder"), _file("folder/module.py", "d" * 64)),
    ],
)
def test_manifest_rejects_impossible_windows_file_tree(files: tuple[StagedFile, ...]) -> None:
    with pytest.raises(ValidationError):
        _manifest(*files)


def test_compare_revalidates_an_unchecked_model_copy_before_mapping_files() -> None:
    valid = _manifest(_file("example.txt"))
    unchecked = valid.model_copy(
        update={"files": (_file("example.txt"), _file("example.txt", "d" * 64))}
    )

    with pytest.raises(ValidationError):
        compare_manifests(unchecked, valid)
    with pytest.raises(ValidationError):
        canonical_json(unchecked)


@pytest.mark.parametrize("operation", [compare_manifests, canonical_json])
def test_invalid_model_copy_rejection_never_serializes_its_private_input(
    operation: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "EXAMPLE_PRIVATE_MANIFEST_CANARY"
    valid = _manifest(_file("example.txt"))
    invalid = valid.model_copy(update={"files": (canary,)})

    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter("always")
        with pytest.raises(ValidationError):
            if operation is compare_manifests:
                compare_manifests(invalid, valid)
            else:
                canonical_json(invalid)
    captured = capsys.readouterr()

    assert canary not in captured.out
    assert canary not in captured.err
    assert all(canary not in str(item.message) for item in captured_warnings)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("files", ({"relative_path": "example.txt", "size_bytes": True, "sha256": "a" * 64},)),
    ],
)
def test_manifest_refuses_boolean_schema_or_size_values(field: str, value: object) -> None:
    payload = _manifest(_file("example.txt")).model_dump(mode="python")
    payload[field] = value

    with pytest.raises(ValidationError):
        BuildManifest.model_validate(payload)


def test_manifest_rejects_duplicate_metadata_and_unbounded_policy_prose() -> None:
    with pytest.raises(ValidationError):
        _manifest(
            _file("example.txt"),
            tool_versions=(
                {"name": "python", "version": "3.11.0"},
                {"name": "python", "version": "3.12.0"},
            ),
        )
    with pytest.raises(ValidationError):
        _manifest(
            _file("example.txt"),
            lockfile_hashes=(
                {"name": "uv.lock", "sha256": "c" * 64},
                {"name": "uv.lock", "sha256": "d" * 64},
            ),
        )
    with pytest.raises(ValidationError):
        _manifest(
            _file("example.txt"),
            nondeterministic_exclusions=(("arbitrary", "unbounded prose"),),
        )


def test_manifest_enforces_tool_and_lock_collection_bounds() -> None:
    tools = tuple(
        {"name": f"tool-{index}", "version": "1"}
        for index in range(MAX_PUBLIC_TOOL_VERSIONS + 1)
    )
    locks = tuple(
        {"name": f"lock-{index}", "sha256": "c" * 64}
        for index in range(MAX_LOCKFILE_HASHES + 1)
    )

    with pytest.raises(ValidationError):
        _manifest(_file("example.txt"), tool_versions=tools)
    with pytest.raises(ValidationError):
        _manifest(_file("example.txt"), lockfile_hashes=locks)


def test_generator_rejects_a_synthetic_hardlinked_file(tmp_path: Path) -> None:
    root = tmp_path / "stage"
    root.mkdir()
    first = root / "first.txt"
    first.write_bytes(b"synthetic public build artifact")
    try:
        os.link(first, root / "second.txt")
    except OSError as error:
        pytest.skip(f"hard links unavailable for temporary fixture: {error.errno}")

    with pytest.raises(ValueError):
        build_manifest(
            root,
            git_revision="b" * 40,
            tool_versions={"python": "3.11.0"},
            lockfile_hashes={"uv.lock": "c" * 64},
        )


def test_generator_rejects_a_file_added_after_enumeration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "stage"
    root.mkdir()
    (root / "first.txt").write_bytes(b"synthetic public build artifact")
    original = manifest_module._sha256_file

    def add_file(path: Path, **kwargs: object) -> tuple[str, int]:
        result = original(path, **kwargs)
        (root / "late.txt").write_bytes(b"synthetic late artifact")
        return result

    monkeypatch.setattr(manifest_module, "_sha256_file", add_file)

    with pytest.raises(ValueError):
        build_manifest(
            root,
            git_revision="b" * 40,
            tool_versions={"python": "3.11.0"},
            lockfile_hashes={"uv.lock": "c" * 64},
        )


def test_generator_rejects_a_file_changed_after_hashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "stage"
    root.mkdir()
    source = root / "first.txt"
    source.write_bytes(b"synthetic public build artifact")
    original = manifest_module._sha256_file

    def change_file(path: Path, **kwargs: object) -> tuple[str, int]:
        result = original(path, **kwargs)
        path.write_bytes(b"synthetic changed artifact")
        return result

    monkeypatch.setattr(manifest_module, "_sha256_file", change_file)

    with pytest.raises(ValueError):
        build_manifest(
            root,
            git_revision="b" * 40,
            tool_versions={"python": "3.11.0"},
            lockfile_hashes={"uv.lock": "c" * 64},
        )


def test_hasher_refuses_growth_past_the_enumerated_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "stage"
    root.mkdir()
    source = root / "first.txt"
    source.write_bytes(b"synthetic")
    expected = source.lstat()
    original_fdopen = manifest_module.os.fdopen

    def grow_before_read(descriptor: int, *args: object, **kwargs: object):
        with source.open("ab") as stream:
            stream.write(b" growth")
        return original_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(manifest_module.os, "fdopen", grow_before_read)

    with pytest.raises(ValueError):
        manifest_module._sha256_file(source, expected=expected)
