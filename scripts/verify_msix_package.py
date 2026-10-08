"""Offline, read-only MSIX preflight for explicitly pinned release inputs."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
import sys
from typing import Callable

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.application.paths.policy import classify_windows_path_text
from prompt_enhancer.application.paths.policy import validate_private_relative_parts
from prompt_enhancer.application.updates import UpdateChannel, verify_update_manifest
from prompt_enhancer.application.updates.package_preflight import (
    AuthenticatedReleaseArtifact,
    MsixPackageExpectation,
)
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from prompt_enhancer.infrastructure.updates.msix_preflight import MsixPackagePreflight


_MAX_MANIFEST_BYTES = 32 * 1024
_MAX_SIGNATURE_BYTES = 64
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class _SafeParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, "invalid_arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeParser(add_help=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--public-key-hex", required=True)
    parser.add_argument("--installed-version", required=True)
    parser.add_argument("--channel", required=True, choices=[item.value for item in UpdateChannel])
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--signer-sha256", required=True)
    return parser


def _safe_path(raw: str, *, suffix: str | None) -> Path | None:
    if (
        not isinstance(raw, str)
        or ".." in PurePath(raw).parts
        or ".." in PureWindowsPath(raw).parts
        or classify_windows_path_text(raw) is not None
    ):
        return None
    path = Path(raw)
    parts = tuple(part for part in path.parts if part not in {path.anchor, ""})
    if (
        validate_private_relative_parts(parts) is not None
        or any(ord(character) <= 31 or 127 <= ord(character) <= 159 for character in raw)
        or any(character in '<>"|?*' for character in raw)
    ):
        return None
    if not path.is_absolute() or (suffix is not None and path.suffix.lower() != suffix):
        return None
    return path


def _path_snapshot(path: Path) -> tuple[tuple[int, ...], ...]:
    """Bind a file's contents and its ancestor identities, not directory churn."""

    snapshots: list[tuple[int, ...]] = []
    current = path
    while True:
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise OSError("path component is a link")
        if current == path:
            snapshots.append(_stable_metadata(metadata))
        else:
            snapshots.append(
                (metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode))
            )
        if current.parent == current:
            return tuple(snapshots)
        current = current.parent


def _stable_metadata(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_nlink,
        stat.S_IFMT(metadata.st_mode),
    )


def _open_readonly(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _read_regular(path: Path, *, maximum: int, exact: int | None = None) -> bytes | None:
    descriptor = -1
    value: bytes | None = None
    try:
        path_snapshot = _path_snapshot(path)
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
            or metadata.st_size < 0
            or metadata.st_size > maximum
            or (exact is not None and metadata.st_size != exact)
        ):
            return None
        descriptor = _open_readonly(path)
        opened = os.fstat(descriptor)
        if _stable_metadata(metadata) != _stable_metadata(opened):
            return None
        chunks: list[bytes] = []
        total = 0
        while total <= metadata.st_size:
            chunk = os.read(
                descriptor,
                min(64 * 1024, metadata.st_size - total + 1),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        value = b"".join(chunks)
        if (
            len(value) != metadata.st_size
            or (exact is not None and len(value) != exact)
            or _stable_metadata(opened) != _stable_metadata(os.fstat(descriptor))
            or path_snapshot != _path_snapshot(path)
        ):
            value = None
    except OSError:
        value = None
    finally:
        if descriptor != -1:
            try:
                os.close(descriptor)
            except OSError:
                value = None
    return value


def _result(state: str, reason: str | None = None) -> bytes:
    value: dict[str, object] = {"state": state, "can_install": False}
    if reason is not None:
        value["reason"] = reason
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def main(
    argv: list[str] | None = None,
    *,
    signer_factory: Callable[[], object] | None = None,
) -> int:
    try:
        arguments = _parser().parse_args(argv)
        package = _safe_path(arguments.package, suffix=".msix")
        manifest = _safe_path(arguments.manifest, suffix=None)
        signature = _safe_path(arguments.signature, suffix=None)
        if (
            _VERSION.fullmatch(arguments.installed_version) is None
            or len(arguments.public_key_hex) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in arguments.public_key_hex)
        ):
            raise ValueError
        key = bytes.fromhex(arguments.public_key_hex)
        expectation = MsixPackageExpectation(
            name=arguments.package_name,
            publisher=arguments.publisher,
            architecture=arguments.architecture,
            signer_sha256=arguments.signer_sha256,
        )
        channel = UpdateChannel(arguments.channel)
        verifier = Ed25519ManifestVerifier(public_keys={arguments.key_id: key})
        if package is None or manifest is None or signature is None or len(key) != 32:
            raise ValueError
    except SystemExit as error:
        if error.code == 0:
            return 0
        sys.stdout.buffer.write(_result("rejected", "invalid_arguments"))
        return 2
    except (TypeError, ValueError):
        sys.stdout.buffer.write(_result("rejected", "invalid_arguments"))
        return 2
    raw_manifest = _read_regular(manifest, maximum=_MAX_MANIFEST_BYTES)
    raw_signature = _read_regular(signature, maximum=_MAX_SIGNATURE_BYTES, exact=_MAX_SIGNATURE_BYTES)
    if raw_manifest is None or raw_signature is None:
        sys.stdout.buffer.write(_result("rejected", "metadata_unavailable"))
        return 2
    verification = verify_update_manifest(
        raw_manifest,
        signature=raw_signature,
        key_id=arguments.key_id,
        verifier=verifier,
        now=datetime.now(UTC),
        installed_version=arguments.installed_version,
        channel=channel,
    )
    try:
        artifact = AuthenticatedReleaseArtifact.from_accepted(verification)
    except ValueError:
        sys.stdout.buffer.write(_result("rejected", "manifest_rejected"))
        return 2
    try:
        if signer_factory is None:
            from prompt_enhancer.infrastructure.updates.windows_msix_signer import WindowsMsixSigner

            signer_factory = WindowsMsixSigner
        result = MsixPackagePreflight(signer=signer_factory()).verify(
            package_path=package,
            artifact=artifact,
            expectation=expectation,
        )
    except Exception:
        sys.stdout.buffer.write(_result("rejected", "signature_unverifiable"))
        return 2
    sys.stdout.buffer.write(result.model_dump_json(exclude_none=True).encode() + b"\n")
    return 0 if result.state.value == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
