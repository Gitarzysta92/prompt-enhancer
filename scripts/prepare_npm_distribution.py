"""Offline extraction of an explicitly pinned public npm distribution archive."""
import argparse
import io
import json
import re
from pathlib import Path
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prompt_enhancer.infrastructure.frontend_dependency_preparation import (
    absolute, pinned, require, digest, inventory, decode, FrontendDependencyPreparationError,
    _normalized_manifest, _remove_owned, _validate_staged_relative_path,
)

MAX_ARCHIVE = 16 * 1024**2
MAX_TOTAL = 128 * 1024**2
MAX_FILE = 16 * 1024**2
MAX_ENTRIES = 4096


def members(archive):
    """Validate the entire bounded table before creating any output member."""
    result = []
    names = {}
    total = 0
    for item in archive:
        require(len(result) < MAX_ENTRIES, "npm_archive_invalid")
        name = item.name.rstrip("/") if item.isdir() else item.name
        _validate_staged_relative_path(name)
        require(name == "package" or name.startswith("package/"), "npm_archive_invalid")
        require(item.isdir() or item.isreg(), "npm_archive_invalid")
        require(not item.linkname and not item.sparse and not item.pax_headers, "npm_archive_invalid")
        require(name.casefold() not in names and type(item.size) is int and 0 <= item.size <= MAX_FILE, "npm_archive_invalid")
        require(not item.isdir() or item.size == 0, "npm_archive_invalid")
        names[name.casefold()] = item.isdir()
        total += item.size
        require(total <= MAX_TOTAL, "npm_archive_invalid")
        result.append((name, item))
    require(result and any(name == "package/package.json" for name, _ in result)
            and any(name == "package/bin/npm-cli.js" for name, _ in result), "npm_archive_invalid")
    for name, _ in result:
        for parent in Path(name).parents:
            if str(parent) != ".":
                require(names.get(parent.as_posix().casefold(), True), "npm_archive_invalid")
    return result


def prepare(*, archive_path, archive_size, archive_sha256, npm_version, destination):
    work = None
    try:
        require(isinstance(npm_version, str) and re.fullmatch(r"\d+\.\d+\.\d+", npm_version), "npm_identity_invalid")
        source = absolute(archive_path)
        output = absolute(destination, external=True)
        require(not output.exists() and output.parent.is_dir())
        require(output != source and output not in source.parents and source not in output.parents)
        raw = pinned(source, archive_size, archive_sha256, MAX_ARCHIVE)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            entries = members(archive)
            work = Path(tempfile.mkdtemp(prefix=".npm-distribution-", dir=output.parent))
            expected = {}
            for name, item in entries:
                target = work / name
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                require(name != "package", "npm_archive_invalid")
                target.parent.mkdir(parents=True, exist_ok=True)
                reader = archive.extractfile(item)
                require(reader is not None, "npm_archive_invalid")
                with reader:
                    data = reader.read(item.size + 1)
                require(len(data) == item.size, "npm_archive_invalid")
                with target.open("xb") as stream:
                    stream.write(data)
                expected[name.removeprefix("package/")] = (len(data), digest(data))
        require(inventory(work / "package") == expected, "npm_extraction_changed")
        from prompt_enhancer.infrastructure.application_wheel_preparation import _read
        metadata = decode(_read(work / "package/package.json", maximum=MAX_FILE))
        require(metadata.get("name") == "npm" and metadata.get("version") == npm_version, "npm_identity_invalid")
        manifest = _normalized_manifest(expected)
        with (work / "manifest.json").open("xb") as stream:
            stream.write(manifest)
        receipt = {"contract": "npm-distribution-preparation.v1", "archive_sha256": archive_sha256,
                   "archive_size_bytes": archive_size, "npm_version": npm_version, "files": len(expected),
                   "unpacked_bytes": sum(size for size, _ in expected.values()), "manifest_sha256": digest(manifest),
                   "manifest_size_bytes": len(manifest), "executed": False, "licence_closure_claimed": False}
        provenance = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with (work / "provenance.json").open("xb") as stream:
            stream.write(provenance)
        require(pinned(source, archive_size, archive_sha256, MAX_ARCHIVE) == raw)
        require(inventory(work / "package") == expected and not output.exists())
        expected_work = {"package/" + name: identity for name, identity in expected.items()}
        expected_work.update({"manifest.json": (len(manifest), digest(manifest)),
                              "provenance.json": (len(provenance), digest(provenance))})
        require(inventory(work) == expected_work and {item.name for item in work.iterdir()} ==
                {"package", "manifest.json", "provenance.json"}, "npm_publication_changed")
        work.rename(output)
        work = None
        return receipt
    except FrontendDependencyPreparationError:
        raise
    except Exception:
        raise FrontendDependencyPreparationError("npm_distribution_failed") from None
    finally:
        if work is not None:
            try:
                _remove_owned(work, work.parent)
            except Exception:
                raise FrontendDependencyPreparationError("npm_distribution_cleanup_unconfirmed") from None


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FrontendDependencyPreparationError("npm_distribution_cli_invalid")


def main(argv=None):
    try:
        parser = Parser()
        parser.add_argument("--archive-path", type=Path, required=True)
        parser.add_argument("--archive-size", type=int, required=True)
        parser.add_argument("--archive-sha256", required=True)
        parser.add_argument("--npm-version", required=True)
        parser.add_argument("--destination", type=Path, required=True)
        print(json.dumps(prepare(**vars(parser.parse_args(argv))), sort_keys=True))
        return 0
    except FrontendDependencyPreparationError as error:
        print(json.dumps({"passed": False, "error_code": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
