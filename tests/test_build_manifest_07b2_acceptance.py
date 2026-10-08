"""Synthetic C07b.2 acceptance for deterministic public build manifests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import os

from pydantic import ValidationError
import pytest

from prompt_enhancer.application.build_evidence import (
    BuildManifest,
    build_manifest,
    canonical_json,
    compare_manifests,
)
from prompt_enhancer.application.build_evidence.manifest import (
    StagedFile,
)
import prompt_enhancer.application.build_evidence.manifest as manifest_module


_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "synthetic_build_public_manifest_cli",
    Path(__file__).parents[1] / "scripts" / "build_public_manifest.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
_SCRIPT_MODULE = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(_SCRIPT_MODULE)
build_manifest_cli = _SCRIPT_MODULE.main


GIT_REVISION = "a" * 40
TOOL_VERSIONS = {"python": "3.11.9", "setuptools": "75.0.0"}
LOCKFILE_HASHES = {"uv.lock": "b" * 64}


def _build_tree(root: Path, *, payload: bytes = b"synthetic artifact\n") -> None:
    (root / "package").mkdir(parents=True)
    (root / "package" / "module.py").write_bytes(payload)
    (root / "NOTICE.txt").write_bytes(b"public notice\n")


def _manifest(root: Path):
    return build_manifest(
        root,
        git_revision=GIT_REVISION,
        tool_versions=TOOL_VERSIONS,
        lockfile_hashes=LOCKFILE_HASHES,
    )


def _staged(path: str, digest: str = "a" * 64) -> StagedFile:
    return StagedFile(relative_path=path, size_bytes=1, sha256=digest)


def _manual_manifest(files: tuple[StagedFile, ...]) -> BuildManifest:
    return BuildManifest(
        git_revision=GIT_REVISION,
        tool_versions=tuple(),
        lockfile_hashes=tuple(),
        files=files,
    )


def test_two_equivalent_synthetic_trees_are_byte_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _build_tree(first_root)
    _build_tree(second_root)

    first = _manifest(first_root)
    second = _manifest(second_root)

    assert canonical_json(first) == canonical_json(second)
    assert compare_manifests(first, second).identical is True
    assert str(tmp_path).encode() not in canonical_json(first)
    assert first.distributable is False


@pytest.mark.parametrize(
    "paths",
    [
        ("package/module.py", "package/module.py"),
        ("Readme.txt", "README.TXT"),
        ("bundle", "bundle/settings.json"),
    ],
)
def test_manifest_rejects_duplicate_casefold_and_prefix_ambiguous_names(
    paths: tuple[str, str],
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _manual_manifest((_staged(paths[0]), _staged(paths[1], "c" * 64)))


@pytest.mark.parametrize(
    "path",
    [
        "./package.py",
        "package/../package.py",
        "/absolute/package.py",
        "package\\module.py",
        "package//module.py",
        "example.txt:stream",
        "example.",
        "example ",
    ],
)
def test_staged_file_requires_normalized_portable_relative_path(path: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _staged(path)


def test_hardlinked_staged_leaf_is_rejected_without_mutating_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-tree"
    root.mkdir()
    original = root / "original.bin"
    alias = root / "alias.bin"
    original.write_bytes(b"synthetic immutable bytes")
    try:
        os.link(original, alias)
    except (OSError, NotImplementedError):
        pytest.skip("hardlink fixture is unsupported on this filesystem")

    before = {path.name: path.read_bytes() for path in (original, alias)}
    with pytest.raises(ValueError):
        _manifest(root)

    assert {path.name: path.read_bytes() for path in (original, alias)} == before


def test_build_manifest_hashes_each_source_leaf_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-tree"
    _build_tree(root)
    original = manifest_module._sha256_file
    reads: list[Path] = []

    def counted(path: Path, **kwargs: object) -> tuple[str, int]:
        reads.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(manifest_module, "_sha256_file", counted)
    _manifest(root)

    assert len(reads) == 2
    assert len({path.relative_to(root) for path in reads}) == 2


def test_collection_bound_is_enforced_before_manifest_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-tree"
    _build_tree(root)
    monkeypatch.setattr(manifest_module, "MAX_STAGED_FILES", 1)

    with pytest.raises(ValueError):
        _manifest(root)


def test_required_manifest_metadata_cannot_be_silently_missing() -> None:
    with pytest.raises(ValidationError):
        BuildManifest.model_validate({"files": []})


def test_cli_bad_synthetic_tree_returns_content_free_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad_root = tmp_path / "synthetic-missing-tree"

    result = build_manifest_cli(
        [
            str(bad_root),
            "--git-revision",
            GIT_REVISION,
            "--tool-version",
            "python=3.11.9",
            "--lockfile-hash",
            "uv.lock=" + "b" * 64,
        ]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == "build_manifest_failed\n"
    assert str(tmp_path) not in captured.err
