"""Independent synthetic acceptance for the read-only C07b.3 MSIX preflight.

These tests exercise package identity and signer-pin composition only.  They
never install, extract, launch, contact a network, or consult a certificate
store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import struct
import sys
import warnings
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from prompt_enhancer.application.updates.contracts import (
    UpdateChannel,
    UpdateManifest,
    UpdateRejection,
    UpdateVerification,
    UpdateVerificationState,
)
from prompt_enhancer.application.updates.package_preflight import (
    AuthenticatedReleaseArtifact,
    MsixPackageExpectation,
    MsixPreflightReason,
    MsixPreflightState,
    MsixPreflightResult,
    expected_msix_version,
)
from prompt_enhancer.infrastructure.updates import msix_preflight
from prompt_enhancer.infrastructure.updates.msix_preflight import (
    MsixPackagePreflight,
)
from prompt_enhancer.infrastructure.updates.ed25519_verifier import (
    Ed25519ManifestVerifier,
)
from prompt_enhancer.application.updates.verification import (
    authenticate_signed_update_manifest,
)


_RELEASE = "2.3.4"
_SIGNER_SHA256 = "a" * 64
_PACKAGE_NAME = "Synthetic.App"
_PUBLISHER = "CN=Synthetic Publisher"
_ARCHITECTURE = "x64"
_MANIFEST = (
    '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
    '<Identity Name="Synthetic.App" '
    'Publisher="CN=Synthetic Publisher" Version="2.3.4.0" '
    'ProcessorArchitecture="x64" /></Package>'
).encode("utf-8")


_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "synthetic_verify_msix_package",
    Path(__file__).parents[1] / "scripts" / "verify_msix_package.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
_VERIFY_MSIX = importlib.util.module_from_spec(_SCRIPT_SPEC)
sys.modules[_SCRIPT_SPEC.name] = _VERIFY_MSIX
_SCRIPT_SPEC.loader.exec_module(_VERIFY_MSIX)


class _SyntheticSigner:
    def __init__(self, result: str | None = _SIGNER_SHA256, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[Path, int]] = []

    def verify(self, *, path: Path, descriptor: int) -> str | None:
        self.calls.append((path, descriptor))
        if self.error is not None:
            raise self.error
        return self.result


def _package_bytes(entries: list[tuple[str, bytes]] | None = None) -> bytes:
    entries = entries or [("AppxManifest.xml", _MANIFEST)]
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def _artifact(package: bytes, *, release_version: str = _RELEASE) -> AuthenticatedReleaseArtifact:
    return AuthenticatedReleaseArtifact(
        sha256=hashlib.sha256(package).hexdigest(),
        size_bytes=len(package),
        release_version=release_version,
    )


def _expectation(*, signer_sha256: str = _SIGNER_SHA256) -> MsixPackageExpectation:
    return MsixPackageExpectation(
        name=_PACKAGE_NAME,
        publisher=_PUBLISHER,
        architecture=_ARCHITECTURE,
        signer_sha256=signer_sha256,
    )


def _write_package(tmp_path: Path, content: bytes) -> Path:
    package = tmp_path / "synthetic-release.msix"
    package.write_bytes(content)
    return package


def _verify(
    package: Path,
    content: bytes,
    signer: _SyntheticSigner,
    *,
    artifact: AuthenticatedReleaseArtifact | None = None,
    expectation: MsixPackageExpectation | None = None,
):
    return MsixPackagePreflight(signer=signer).verify(
        package_path=package,
        artifact=artifact or _artifact(content),
        expectation=expectation or _expectation(),
    )


def test_synthetic_signed_package_preflight_verifies_without_install_authority(
    tmp_path: Path,
) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    before = package.read_bytes()
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.VERIFIED
    assert result.reason is None
    assert result.can_install is False
    assert package.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [package.name]
    assert len(signer.calls) == 1


def test_artifact_dto_derivation_requires_accepted_update_verification() -> None:
    now = datetime(2040, 1, 2, tzinfo=UTC)
    manifest = UpdateManifest(
        schema_version=1,
        release_version=_RELEASE,
        minimum_supported_version="1.0.0",
        channel=UpdateChannel.STABLE,
        published_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=1),
        artifact_sha256="b" * 64,
        artifact_size_bytes=123,
    )
    accepted = UpdateVerification(
        state=UpdateVerificationState.ACCEPTED,
        manifest=manifest,
    )
    rejected = UpdateVerification(
        state=UpdateVerificationState.REJECTED,
        rejection=UpdateRejection.BAD_SIGNATURE,
    )

    artifact = AuthenticatedReleaseArtifact.from_accepted(accepted)

    assert artifact.sha256 == "b" * 64
    assert artifact.size_bytes == 123
    assert artifact.release_version == _RELEASE
    with pytest.raises(ValueError):
        AuthenticatedReleaseArtifact.from_accepted(rejected)
    assert expected_msix_version(_RELEASE) == "2.3.4.0"


def test_real_synthetic_ed25519_manifest_authenticates_before_artifact_derivation() -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    raw = (
        b'{"artifact_sha256":"' + b"b" * 64
        + b'","artifact_size_bytes":123,"channel":"stable",'
        b'"expires_at":"2040-01-03T00:00:00+00:00",'
        b'"minimum_supported_version":"1.0.0","published_at":"2040-01-01T00:00:00+00:00",'
        b'"release_version":"2.3.4","schema_version":1}'
    )
    verifier = Ed25519ManifestVerifier(public_keys={"synthetic-release": public_key})

    accepted = authenticate_signed_update_manifest(
        raw,
        signature=signer.sign(raw),
        key_id="synthetic-release",
        verifier=verifier,
    )
    bad = authenticate_signed_update_manifest(
        raw,
        signature=b"z" * 64,
        key_id="synthetic-release",
        verifier=verifier,
    )

    assert accepted.state is UpdateVerificationState.ACCEPTED
    assert AuthenticatedReleaseArtifact.from_accepted(accepted).release_version == _RELEASE
    assert bad.state is UpdateVerificationState.REJECTED
    with pytest.raises(ValueError):
        AuthenticatedReleaseArtifact.from_accepted(bad)


def _signed_release_metadata(
    package: bytes,
    signer: Ed25519PrivateKey,
) -> tuple[bytes, bytes, str]:
    now = datetime.now(UTC)
    payload = {
        "schema_version": 1,
        "release_version": _RELEASE,
        "minimum_supported_version": "1.0.0",
        "channel": "stable",
        "published_at": (now - timedelta(days=1)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "artifact_sha256": hashlib.sha256(package).hexdigest(),
        "artifact_size_bytes": len(package),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return raw, signer.sign(raw), signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


@pytest.mark.parametrize(
    "package_path",
    [
        Path("../synthetic-release.msix"),
        Path("synthetic-release.zip"),
        Path(r"\\synthetic-server\share\synthetic-release.msix"),
        Path(r"C:synthetic-release.msix"),
        Path(r"\??\C:\synthetic-release.msix"),
        Path("synthetic-release.msix:stream"),
        Path("updates:stream/synthetic-release.msix"),
        Path("CON.msix"),
        Path("control\x01.msix"),
        Path("control\x01/synthetic-release.msix"),
        Path("updates. /synthetic-release.msix"),
        Path("synthetic-release.msix. "),
    ],
)
def test_unsafe_package_path_is_rejected_before_file_or_signer_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    package_path: Path,
) -> None:
    signer = _SyntheticSigner()
    opened: list[Path] = []
    monkeypatch.setattr(msix_preflight, "_open_readonly", lambda path: opened.append(path) or 0)

    candidate = package_path if package_path.is_absolute() else tmp_path / package_path
    result = MsixPackagePreflight(signer=signer).verify(
        package_path=candidate,
        artifact=AuthenticatedReleaseArtifact(
            sha256="c" * 64,
            size_bytes=1,
            release_version=_RELEASE,
        ),
        expectation=_expectation(),
    )

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.PACKAGE_IO_FAILED
    assert opened == []
    assert signer.calls == []


@pytest.mark.parametrize(
    ("artifact_kwargs", "expected_reason"),
    [
        ({"size_bytes": len(_package_bytes()) + 1}, MsixPreflightReason.RELEASE_BINDING_MISMATCH),
        ({"sha256": "d" * 64}, MsixPreflightReason.RELEASE_BINDING_MISMATCH),
    ],
)
def test_package_size_or_hash_mismatch_fails_before_signer(
    tmp_path: Path,
    artifact_kwargs: dict[str, object],
    expected_reason: MsixPreflightReason,
) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    base = _artifact(content).model_dump()
    base.update(artifact_kwargs)
    signer = _SyntheticSigner()

    result = _verify(
        package,
        content,
        signer,
        artifact=AuthenticatedReleaseArtifact(**base),
    )

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is expected_reason
    assert signer.calls == []


@pytest.mark.parametrize(
    "field",
    ["name", "publisher", "architecture"],
)
def test_package_identity_mismatch_fails_before_signer(
    tmp_path: Path,
    field: str,
) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    expectation = _expectation()
    replacement = {"name": "Synthetic.Other", "publisher": "CN=Other", "architecture": "arm64"}[field]
    expectation = expectation.model_copy(update={field: replacement})
    signer = _SyntheticSigner()

    result = _verify(package, content, signer, expectation=expectation)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.IDENTITY_MISMATCH
    assert signer.calls == []


def test_signer_success_without_pinned_leaf_match_is_rejected(tmp_path: Path) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner(result="e" * 64)

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.SIGNER_MISMATCH


def test_unsigned_or_unknown_signer_is_rejected_content_free(tmp_path: Path) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner(result=None)

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.SIGNATURE_INVALID
    assert str(tmp_path) not in result.model_dump_json()
    assert "synthetic" not in result.model_dump_json().lower()


def test_signer_cleanup_uncertainty_is_rejected_not_raised(tmp_path: Path) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner(error=RuntimeError("synthetic cleanup uncertainty"))

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.SIGNATURE_UNVERIFIABLE
    assert "cleanup" not in result.model_dump_json().lower()


@pytest.mark.parametrize(
    "entries",
    [
        [("AppxManifest.xml", _MANIFEST), ("AppxManifest.xml", _MANIFEST)],
        [("AppxManifest.xml", _MANIFEST), ("../outside.txt", b"synthetic")],
        [("AppxManifest.xml", _MANIFEST), ("payload:stream", b"synthetic")],
        [("AppxManifest.xml", _MANIFEST), ("\\absolute.txt", b"synthetic")],
    ],
)
def test_archive_member_ambiguity_or_traversal_fails_closed(
    tmp_path: Path,
    entries: list[tuple[str, bytes]],
) -> None:
    if entries[1][0] == "AppxManifest.xml":
        with pytest.warns(UserWarning, match="Duplicate name"):
            content = _package_bytes(entries)
    else:
        content = _package_bytes(entries)
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason in {
        MsixPreflightReason.ARCHIVE_INVALID,
        MsixPreflightReason.UNSUPPORTED_PACKAGE,
    }
    assert signer.calls == []


def test_manifest_dtd_entity_and_non_utf8_forms_are_refused(tmp_path: Path) -> None:
    dtd = (
        b'<!DOCTYPE Package [<!ENTITY canary "synthetic-secret">]>'
        b'<Package><Identity Name="Synthetic.App" '
        b'Publisher="CN=Synthetic Publisher" Version="2.3.4.0" '
        b'ProcessorArchitecture="x64" /></Package>'
    )
    content = _package_bytes([("AppxManifest.xml", dtd)])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.MANIFEST_INVALID
    assert signer.calls == []
    assert "canary" not in result.model_dump_json().lower()


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_manifest_without_utf8_encoding_is_refused(tmp_path: Path, encoding: str) -> None:
    content = _package_bytes([("AppxManifest.xml", _MANIFEST.decode("utf-8").encode(encoding))])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.MANIFEST_INVALID
    assert signer.calls == []


def test_manifest_must_use_the_msix_namespace(tmp_path: Path) -> None:
    wrong_namespace = (
        '<Package xmlns="urn:synthetic"><Identity Name="Synthetic.App" '
        'Publisher="CN=Synthetic Publisher" Version="2.3.4.0" '
        'ProcessorArchitecture="x64" /></Package>'
    ).encode()
    content = _package_bytes([("AppxManifest.xml", wrong_namespace)])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.MANIFEST_INVALID
    assert signer.calls == []


def test_valid_namespaced_manifest_with_normal_directory_entries_verifies(tmp_path: Path) -> None:
    content = _package_bytes([
        ("AppxManifest.xml", _MANIFEST),
        ("Assets/", b""),
        ("Assets/icon.png", b"synthetic icon"),
    ])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.VERIFIED
    assert signer.calls


@pytest.mark.parametrize("entry_name", ["CON", "payload. ", "control\x01", "payload|name"])
def test_reserved_control_trailing_and_unsupported_member_names_are_refused(
    tmp_path: Path,
    entry_name: str,
) -> None:
    content = _package_bytes([("AppxManifest.xml", _MANIFEST), (entry_name, b"synthetic")])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.ARCHIVE_INVALID
    assert signer.calls == []


def test_archive_file_directory_collision_is_refused(tmp_path: Path) -> None:
    content = _package_bytes([
        ("AppxManifest.xml", _MANIFEST),
        ("payload", b"synthetic file"),
        ("payload/child.bin", b"synthetic child"),
    ])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.ARCHIVE_INVALID
    assert signer.calls == []


def test_archive_same_path_file_and_directory_is_refused(tmp_path: Path) -> None:
    content = _package_bytes([
        ("AppxManifest.xml", _MANIFEST),
        ("payload", b"synthetic file"),
        ("payload/", b""),
    ])
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.ARCHIVE_INVALID
    assert signer.calls == []


@pytest.mark.parametrize("limit_name", ["_MAX_ARCHIVE_ENTRIES", "_MAX_CENTRAL_DIRECTORY_BYTES"])
def test_archive_central_directory_bounds_reject_before_signer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    limit_name: str,
) -> None:
    content = _package_bytes([
        ("AppxManifest.xml", _MANIFEST),
        ("payload.bin", b"synthetic payload"),
    ])
    package = _write_package(tmp_path, content)
    monkeypatch.setattr(msix_preflight, limit_name, 1)
    signer = _SyntheticSigner()
    zip_calls: list[object] = []

    def unexpected_zipfile(*_args: object, **_kwargs: object) -> None:
        zip_calls.append(object())
        raise AssertionError("ZipFile must not parse an over-bound central directory")

    monkeypatch.setattr(msix_preflight.zipfile, "ZipFile", unexpected_zipfile)

    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.UNSUPPORTED_PACKAGE
    assert signer.calls == []
    assert zip_calls == []


def test_zip64_locator_cannot_override_bounded_legacy_eocd(tmp_path: Path) -> None:
    original = _package_bytes()
    eocd_offset = original.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    _signature, _disk, _central_disk, _disk_entries, entries, central_size, central_offset, _comment = struct.unpack_from(
        "<4s4H2LH", original, eocd_offset
    )
    zip64_record = struct.pack(
        "<4sQ2H2I4Q",
        b"PK\x06\x06", 44, 45, 45, 0, 0, entries, entries,
        central_size, central_offset,
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, eocd_offset, 1)
    content = original[:eocd_offset] + zip64_record + locator + original[eocd_offset:]
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()
    zip_calls: list[object] = []

    def unexpected_zipfile(*_args: object, **_kwargs: object) -> None:
        zip_calls.append(object())
        raise AssertionError("ZipFile must not parse a ZIP64 locator")

    original = msix_preflight.zipfile.ZipFile
    msix_preflight.zipfile.ZipFile = unexpected_zipfile  # type: ignore[assignment]
    try:
        result = _verify(package, content, signer)
    finally:
        msix_preflight.zipfile.ZipFile = original

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.UNSUPPORTED_PACKAGE
    assert zip_calls == []


@pytest.mark.parametrize("field", ["entry_count", "central_size"])
def test_forged_eocd_bounds_reject_before_zipfile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    original = _package_bytes()
    eocd_offset = original.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    forged = bytearray(original)
    if field == "entry_count":
        struct.pack_into("<H", forged, eocd_offset + 10, 2)
    else:
        struct.pack_into("<L", forged, eocd_offset + 12, 0xFFFFFFFF)
    content = bytes(forged)
    package = _write_package(tmp_path, content)
    signer = _SyntheticSigner()
    zip_calls: list[object] = []

    def unexpected_zipfile(*_args: object, **_kwargs: object) -> None:
        zip_calls.append(object())
        raise AssertionError("ZipFile must not parse a forged central directory")

    monkeypatch.setattr(msix_preflight.zipfile, "ZipFile", unexpected_zipfile)
    result = _verify(package, content, signer)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.UNSUPPORTED_PACKAGE
    assert zip_calls == []
    assert signer.calls == []


@pytest.mark.parametrize(
    ("target", "bypass"),
    [
        ("artifact", "model_copy"),
        ("artifact", "model_construct"),
        ("expectation", "model_copy"),
        ("expectation", "model_construct"),
    ],
)
def test_model_validation_bypass_cannot_enable_preflight_or_native_signer(
    tmp_path: Path,
    target: str,
    bypass: str,
) -> None:
    content = _package_bytes()
    package = _write_package(tmp_path, content)
    valid_artifact = _artifact(content)
    valid_expectation = _expectation()
    if target == "artifact" and bypass == "model_copy":
        malformed_artifact = valid_artifact.model_copy(update={"sha256": "not-a-digest"})
        malformed_expectation = valid_expectation
    elif target == "expectation" and bypass == "model_copy":
        malformed_artifact = valid_artifact
        malformed_expectation = valid_expectation.model_copy(update={"signer_sha256": "not-a-digest"})
    elif target == "artifact":
        malformed_artifact = AuthenticatedReleaseArtifact.model_construct(
            sha256="not-a-digest", size_bytes=len(content), release_version="not-a-version"
        )
        malformed_expectation = valid_expectation
    else:
        malformed_expectation = MsixPackageExpectation.model_construct(
            name=_PACKAGE_NAME, publisher=_PUBLISHER, architecture=_ARCHITECTURE,
            signer_sha256="not-a-digest",
        )
        malformed_artifact = valid_artifact
    signer = _SyntheticSigner()

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = _verify(
            package,
            content,
            signer,
            artifact=malformed_artifact,
            expectation=malformed_expectation,
        )

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.RELEASE_BINDING_MISMATCH
    assert signer.calls == []
    assert captured == []


def test_install_capability_is_an_invariant_of_result() -> None:
    with pytest.raises(ValueError):
        MsixPreflightResult(
            state=MsixPreflightState.VERIFIED,
            can_install=True,
        )


def test_cli_authenticates_bounded_metadata_then_runs_read_only_preflight(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_content = _package_bytes()
    package = _write_package(tmp_path, package_content)
    signing_key = Ed25519PrivateKey.generate()
    raw_manifest, raw_signature, public_key_hex = _signed_release_metadata(
        package_content, signing_key
    )
    manifest = tmp_path / "release.json"
    signature = tmp_path / "release.sig"
    manifest.write_bytes(raw_manifest)
    signature.write_bytes(raw_signature)
    signer = _SyntheticSigner()

    exit_code = _VERIFY_MSIX.main(
        [
            "--package", str(package),
            "--manifest", str(manifest),
            "--signature", str(signature),
            "--key-id", "synthetic-release",
            "--public-key-hex", public_key_hex,
            "--installed-version", "1.0.0",
            "--channel", "stable",
            "--package-name", _PACKAGE_NAME,
            "--publisher", _PUBLISHER,
            "--architecture", _ARCHITECTURE,
            "--signer-sha256", _SIGNER_SHA256,
        ],
        signer_factory=lambda: signer,
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert json.loads(output) == {"can_install": False, "state": "verified"}
    assert signer.calls
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "release.json", "release.sig", "synthetic-release.msix"
    ]


def test_cli_bad_signed_metadata_fails_before_package_signer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_content = _package_bytes()
    package = _write_package(tmp_path, package_content)
    signing_key = Ed25519PrivateKey.generate()
    raw_manifest, _signature, public_key_hex = _signed_release_metadata(
        package_content, signing_key
    )
    manifest = tmp_path / "release.json"
    signature = tmp_path / "release.sig"
    manifest.write_bytes(raw_manifest)
    signature.write_bytes(b"z" * 64)
    signer = _SyntheticSigner()

    exit_code = _VERIFY_MSIX.main(
        [
            "--package", str(package), "--manifest", str(manifest),
            "--signature", str(signature), "--key-id", "synthetic-release",
            "--public-key-hex", public_key_hex, "--installed-version", "1.0.0",
            "--channel", "stable", "--package-name", _PACKAGE_NAME,
            "--publisher", _PUBLISHER, "--architecture", _ARCHITECTURE,
            "--signer-sha256", _SIGNER_SHA256,
        ],
        signer_factory=lambda: signer,
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert json.loads(output) == {"can_install": False, "reason": "manifest_rejected", "state": "rejected"}
    assert signer.calls == []
    assert str(tmp_path) not in output


def test_cli_rejects_unsafe_path_without_reading_or_native_signer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    signer_calls: list[object] = []

    exit_code = _VERIFY_MSIX.main(
        [
            "--package", str(tmp_path / ".." / "synthetic-release.msix"),
            "--manifest", str(tmp_path / "release.json"),
            "--signature", str(tmp_path / "release.sig"),
            "--key-id", "synthetic-release", "--public-key-hex", "00" * 32,
            "--installed-version", "1.0.0", "--channel", "stable",
            "--package-name", _PACKAGE_NAME, "--publisher", _PUBLISHER,
            "--architecture", _ARCHITECTURE, "--signer-sha256", _SIGNER_SHA256,
        ],
        signer_factory=lambda: signer_calls.append(object()),
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert json.loads(output) == {"can_install": False, "reason": "invalid_arguments", "state": "rejected"}
    assert signer_calls == []
    assert str(tmp_path) not in output
