"""Synthetic archive checks for the offline, pinned npm extractor."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts import prepare_npm_distribution as cli
from prompt_enhancer.infrastructure import frontend_dependency_preparation as dependencies


def _archive(entries: list[tuple[str, bytes | None]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            if content is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "package/package.json"
                archive.addfile(info)
            else:
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def _valid_entries() -> list[tuple[str, bytes | None]]:
    return [
        ("package/package.json", b'{"name":"npm","version":"11.6.2"}'),
        ("package/bin/npm-cli.js", b"// fictional test fixture\n"),
    ]


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fictional-home"))
    monkeypatch.setattr(dependencies, "REPOSITORY", tmp_path / "fictional-repository")
    source = tmp_path / "npm.tgz"
    destination = tmp_path / "prepared-npm"

    def prepare(raw: bytes):
        source.write_bytes(raw)
        return cli.prepare(
            archive_path=source, archive_size=len(raw), archive_sha256=cli.digest(raw),
            npm_version="11.6.2", destination=destination,
        )

    return source, destination, prepare


def test_exact_pinned_archive_extracts_without_execution(paths) -> None:
    _, destination, prepare = paths
    receipt = prepare(_archive(_valid_entries()))
    assert receipt["executed"] is False
    assert receipt["licence_closure_claimed"] is False
    assert receipt["files"] == 2
    assert (destination / "package/bin/npm-cli.js").read_bytes() == b"// fictional test fixture\n"
    assert json.loads((destination / "provenance.json").read_text())["manifest_sha256"] == receipt["manifest_sha256"]
    assert not list(destination.parent.glob(".npm-distribution-*"))


@pytest.mark.parametrize("extra", [
    ("package/../escape.txt", b"fictional"),
    ("package/bin/npm-cli.js", b"duplicate"),
    ("package/linked", None),
    ("outside-package.txt", b"fictional"),
])
def test_unsafe_archive_members_fail_without_publication(paths, extra) -> None:
    _, destination, prepare = paths
    with pytest.raises(dependencies.FrontendDependencyPreparationError):
        prepare(_archive(_valid_entries() + [extra]))
    assert not destination.exists()
    assert not list(destination.parent.glob(".npm-distribution-*"))


def test_wrong_npm_identity_and_digest_do_not_publish(paths) -> None:
    source, destination, prepare = paths
    changed = _valid_entries()
    changed[0] = ("package/package.json", b'{"name":"other","version":"11.6.2"}')
    with pytest.raises(dependencies.FrontendDependencyPreparationError):
        prepare(_archive(changed))
    assert not destination.exists()
    raw = _archive(_valid_entries())
    source.write_bytes(raw)
    with pytest.raises(dependencies.FrontendDependencyPreparationError):
        cli.prepare(archive_path=source, archive_size=len(raw), archive_sha256="0" * 64,
                    npm_version="11.6.2", destination=destination)
    assert not destination.exists()


def test_cli_errors_are_content_free(capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "prepare", lambda **kwargs: (_ for _ in ()).throw(AssertionError("launched")))
    assert cli.main(["--archive-size", "private-like-value"]) == 1
    output = capsys.readouterr().out
    assert "private-like-value" not in output
    assert json.loads(output)["error_code"] == "npm_distribution_cli_invalid"
