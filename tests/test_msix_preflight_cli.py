"""Synthetic, offline coverage for the bounded MSIX preflight CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import sys
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from prompt_enhancer.application.updates.package_preflight import (
    AuthenticatedReleaseArtifact,
    MsixPackageExpectation,
    MsixPreflightReason,
)
from prompt_enhancer.infrastructure.updates import msix_preflight
from prompt_enhancer.infrastructure.updates.msix_preflight import MsixPackagePreflight


_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "synthetic_verify_msix_package_cli",
    Path(__file__).parents[1] / "scripts" / "verify_msix_package.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
_CLI = importlib.util.module_from_spec(_SCRIPT_SPEC)
sys.modules[_SCRIPT_SPEC.name] = _CLI
_SCRIPT_SPEC.loader.exec_module(_CLI)

_NAME = "Synthetic.Package"
_PUBLISHER = "CN=Synthetic Publisher"
_ARCHITECTURE = "x64"
_SIGNER_SHA256 = "a" * 64
_RELEASE = "2.3.4"


class _SyntheticSigner:
    def __init__(self, result: str | None = _SIGNER_SHA256) -> None:
        self.result = result
        self.calls = 0

    def verify(self, *, path: Path, descriptor: int) -> str | None:
        self.calls += 1
        return self.result


def _package_bytes() -> bytes:
    manifest = (
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Identity Name="Synthetic.Package" Publisher="CN=Synthetic Publisher" '
        'Version="2.3.4.0" ProcessorArchitecture="x64" /></Package>'
    ).encode("utf-8")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("Assets/", b"")
        archive.writestr("Assets/icon.png", b"synthetic icon")
    return output.getvalue()


def _signed_metadata(package: bytes, *, channel: str = "stable", expires_at: datetime | None = None) -> tuple[bytes, bytes, str]:
    signing_key = Ed25519PrivateKey.generate()
    now = datetime.now(UTC)
    payload = {
        "schema_version": 1,
        "release_version": _RELEASE,
        "minimum_supported_version": "1.0.0",
        "channel": channel,
        "published_at": (now - timedelta(days=1)).isoformat(),
        "expires_at": (expires_at or now + timedelta(days=1)).isoformat(),
        "artifact_sha256": hashlib.sha256(package).hexdigest(),
        "artifact_size_bytes": len(package),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    public_key = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw, signing_key.sign(raw), public_key.hex()


def _arguments(
    package: Path,
    manifest: Path,
    signature: Path,
    public_key_hex: str,
    *,
    installed_version: str = "1.0.0",
    channel: str = "stable",
) -> list[str]:
    return [
        "--package", str(package),
        "--manifest", str(manifest),
        "--signature", str(signature),
        "--key-id", "synthetic-release",
        "--public-key-hex", public_key_hex,
        "--installed-version", installed_version,
        "--channel", channel,
        "--package-name", _NAME,
        "--publisher", _PUBLISHER,
        "--architecture", _ARCHITECTURE,
        "--signer-sha256", _SIGNER_SHA256,
    ]


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    package = tmp_path / "synthetic-release.msix"
    package_bytes = _package_bytes()
    package.write_bytes(package_bytes)
    raw, detached, public_key_hex = _signed_metadata(package_bytes)
    manifest = tmp_path / "release.json"
    signature = tmp_path / "release.sig"
    manifest.write_bytes(raw)
    signature.write_bytes(detached)
    return package, manifest, signature, public_key_hex


def _artifact(package: bytes) -> AuthenticatedReleaseArtifact:
    return AuthenticatedReleaseArtifact(
        sha256=hashlib.sha256(package).hexdigest(),
        size_bytes=len(package),
        release_version=_RELEASE,
    )


def _expectation() -> MsixPackageExpectation:
    return MsixPackageExpectation(
        name=_NAME,
        publisher=_PUBLISHER,
        architecture=_ARCHITECTURE,
        signer_sha256=_SIGNER_SHA256,
    )


def _output(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_cli_authenticates_signed_metadata_and_is_non_installable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package, manifest, signature, public_key_hex = _write_inputs(tmp_path)
    signer = _SyntheticSigner()

    exit_code = _CLI.main(
        _arguments(package, manifest, signature, public_key_hex),
        signer_factory=lambda: signer,
    )

    assert exit_code == 0
    assert _output(capsys) == {"can_install": False, "state": "verified"}
    assert signer.calls == 1


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda arguments: arguments.__setitem__(arguments.index("--public-key-hex") + 1, "a" * 63), "invalid_arguments"),
        (lambda arguments: arguments.__setitem__(arguments.index("--installed-version") + 1, "01.0.0"), "invalid_arguments"),
        (lambda arguments: arguments.__setitem__(arguments.index("--manifest") + 1, str(Path("..") / "private-canary.json")), "invalid_arguments"),
    ],
)
def test_cli_rejects_untrusted_argument_forms_before_file_reads(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutate: object,
    reason: str,
) -> None:
    package, manifest, signature, public_key_hex = _write_inputs(tmp_path)
    arguments = _arguments(package, manifest, signature, public_key_hex)
    assert callable(mutate)
    mutate(arguments)
    signer = _SyntheticSigner()

    exit_code = _CLI.main(arguments, signer_factory=lambda: signer)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert json.loads(captured.out) == {
        "can_install": False,
        "reason": reason,
        "state": "rejected",
    }
    assert "private-canary" not in captured.out
    assert "private-canary" not in captured.err
    assert signer.calls == 0


@pytest.mark.parametrize("failure", ["bad_signature", "oversized_signature", "expired", "channel"])
def test_cli_refuses_bad_or_ineligible_authenticated_metadata_before_signer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    package, manifest, signature, public_key_hex = _write_inputs(tmp_path)
    if failure == "bad_signature":
        signature.write_bytes(b"z" * 64)
    elif failure == "oversized_signature":
        signature.write_bytes(b"z" * 65)
    elif failure == "expired":
        raw, detached, public_key_hex = _signed_metadata(
            package.read_bytes(), expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )
        manifest.write_bytes(raw)
        signature.write_bytes(detached)
    else:
        raw, detached, public_key_hex = _signed_metadata(package.read_bytes(), channel="beta")
        manifest.write_bytes(raw)
        signature.write_bytes(detached)
    signer = _SyntheticSigner()

    exit_code = _CLI.main(
        _arguments(package, manifest, signature, public_key_hex),
        signer_factory=lambda: signer,
    )

    assert exit_code == 2
    assert _output(capsys) == {
        "can_install": False,
        "reason": "metadata_unavailable" if failure == "oversized_signature" else "manifest_rejected",
        "state": "rejected",
    }
    assert signer.calls == 0


def test_cli_help_is_discoverable_without_echoing_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _CLI.main(["--help"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "--package" in captured.out
    assert "invalid_arguments" not in captured.out
    assert captured.err == ""


def test_preflight_rejects_an_opened_file_that_does_not_match_the_safe_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _package_bytes()
    second = _package_bytes() + b"different synthetic bytes"
    package = tmp_path / "first.msix"
    alternate = tmp_path / "second.msix"
    package.write_bytes(first)
    alternate.write_bytes(second)
    signer = _SyntheticSigner()
    hash_calls: list[object] = []
    monkeypatch.setattr(
        msix_preflight,
        "_open_readonly",
        lambda _path: os.open(alternate, os.O_RDONLY),
    )
    monkeypatch.setattr(
        msix_preflight,
        "_hash_descriptor",
        lambda *_args, **_kwargs: hash_calls.append(object()) or "",
    )

    result = MsixPackagePreflight(signer=signer).verify(
        package_path=package,
        artifact=_artifact(first),
        expectation=_expectation(),
    )

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert signer.calls == 0
    assert hash_calls == []


def test_preflight_close_failure_is_not_retried_after_descriptor_relinquish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_bytes = _package_bytes()
    package = tmp_path / "synthetic-release.msix"
    package.write_bytes(package_bytes)
    signer = _SyntheticSigner()
    original_close = msix_preflight.os.close
    close_calls: list[int] = []

    def close_then_fail(descriptor: int) -> None:
        close_calls.append(descriptor)
        original_close(descriptor)
        raise OSError("synthetic close failure")

    monkeypatch.setattr(msix_preflight.os, "close", close_then_fail)
    result = MsixPackagePreflight(signer=signer).verify(
        package_path=package,
        artifact=_artifact(package_bytes),
        expectation=_expectation(),
    )

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert len(close_calls) == 1
    assert signer.calls == 1


def test_preflight_ignores_unrelated_parent_directory_churn_during_signing(
    tmp_path: Path,
) -> None:
    package_bytes = _package_bytes()
    package = tmp_path / "synthetic-release.msix"
    package.write_bytes(package_bytes)

    class _SiblingCreatingSigner(_SyntheticSigner):
        def verify(self, *, path: Path, descriptor: int) -> str | None:
            (path.parent / "unrelated-synthetic-sibling").write_bytes(b"unrelated")
            return super().verify(path=path, descriptor=descriptor)

    signer = _SiblingCreatingSigner()
    result = MsixPackagePreflight(signer=signer).verify(
        package_path=package,
        artifact=_artifact(package_bytes),
        expectation=_expectation(),
    )

    assert result.state.value == "verified"
    assert signer.calls == 1


@pytest.mark.parametrize("forgery", ["entry_count", "central_offset"])
def test_preflight_checks_eocd_count_and_offset_before_zipfile_parsing(
    tmp_path: Path,
    forgery: str,
) -> None:
    original = bytearray(_package_bytes())
    eocd = original.rfind(b"PK\x05\x06")
    assert eocd >= 0
    if forgery == "entry_count":
        struct.pack_into("<H", original, eocd + 8, 1)
        struct.pack_into("<H", original, eocd + 10, 1)
    else:
        offset = struct.unpack_from("<L", original, eocd + 16)[0]
        struct.pack_into("<L", original, eocd + 16, offset - 1)
    package = tmp_path / "synthetic-release.msix"
    package.write_bytes(original)
    signer = _SyntheticSigner()

    result = MsixPackagePreflight(signer=signer).verify(
        package_path=package,
        artifact=_artifact(bytes(original)),
        expectation=_expectation(),
    )

    assert result.reason is MsixPreflightReason.UNSUPPORTED_PACKAGE
    assert signer.calls == 0


def test_locator_magic_in_ordinary_payload_is_not_treated_as_a_zip64_locator(
    tmp_path: Path,
) -> None:
    manifest = (
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Identity Name="Synthetic.Package" Publisher="CN=Synthetic Publisher" '
        'Version="2.3.4.0" ProcessorArchitecture="x64" /></Package>'
    ).encode("utf-8")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("Assets/locator.bin", b"payload PK\x06\x07 marker")
    package_bytes = output.getvalue()
    package = tmp_path / "synthetic-release.msix"
    package.write_bytes(package_bytes)
    signer = _SyntheticSigner()

    result = MsixPackagePreflight(signer=signer).verify(
        package_path=package,
        artifact=_artifact(package_bytes),
        expectation=_expectation(),
    )

    assert result.state.value == "verified"
    assert signer.calls == 1
