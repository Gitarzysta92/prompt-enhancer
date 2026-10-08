from __future__ import annotations

from datetime import UTC, datetime, timedelta
import base64
import hashlib
import io
import json
import os
from pathlib import Path
from collections.abc import Callable
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from prompt_enhancer.application.updates.contracts import (
    ApplicationUpdateReason,
    UpdateManifest,
)
from prompt_enhancer.application.updates.package_preflight import (
    AuthenticatedReleaseArtifact,
    MsixPackageExpectation,
    MsixPreflightReason,
    MsixPreflightState,
)
from prompt_enhancer.application.updates.ports import SignedUpdateManifestEnvelope
from prompt_enhancer.infrastructure.updates.msix_preflight import (
    MsixPackagePreflight,
    PackageSignerUnavailable,
)
import prompt_enhancer.infrastructure.updates.msix_preflight as msix_preflight_module
from prompt_enhancer.infrastructure.updates.staged_package_review import StagedPackageReview
from prompt_enhancer.infrastructure.updates.staging import (
    FileUpdateStagingStore,
    UpdateStagingError,
)


_NAME = "Synthetic.App"
_PUBLISHER = "CN=Synthetic Publisher"
_ARCHITECTURE = "x64"
_SIGNER = "a" * 64


class _FakePackageSigner:
    def __init__(
        self,
        result: str | None = _SIGNER,
        error: Exception | None = None,
        mutate: Callable[[], None] | None = None,
    ) -> None:
        self.result, self.error, self.mutate = result, error, mutate
        self.calls: list[Path] = []

    def verify(self, *, path: Path, descriptor: int) -> str | None:
        assert descriptor >= 0
        self.calls.append(path)
        if self.mutate is not None:
            self.mutate()
        if self.error is not None:
            raise self.error
        return self.result


def _package() -> bytes:
    manifest = (
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        f'<Identity Name="{_NAME}" Publisher="{_PUBLISHER}" '
        'Version="2.3.4.0" ProcessorArchitecture="x64" />'
        '</Package>'
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("Assets/icon.bin", b"synthetic-icon")
    return output.getvalue()


def _signed_manifest(package: bytes) -> tuple[UpdateManifest, SignedUpdateManifestEnvelope]:
    now = datetime.now(UTC)
    raw = json.dumps(
        {
            "schema_version": 1,
            "release_version": "2.3.4",
            "minimum_supported_version": "1.0.0",
            "channel": "stable",
            "published_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "artifact_sha256": hashlib.sha256(package).hexdigest(),
            "artifact_size_bytes": len(package),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    key = Ed25519PrivateKey.generate()
    signature = key.sign(raw)
    # Keep the fixture genuinely signed even though coordinator authentication
    # is deliberately outside this read-only adapter boundary.
    try:
        key.public_key().verify(signature, raw)
    except InvalidSignature:  # pragma: no cover - fixture cannot reach this
        raise AssertionError("synthetic Ed25519 fixture was not signed") from None
    return UpdateManifest.model_validate_json(raw), SignedUpdateManifestEnvelope(
        raw_manifest=raw, signature=signature, key_id="synthetic-release"
    )


def _review(root: Path, signer: _FakePackageSigner) -> tuple[StagedPackageReview, UpdateManifest, SignedUpdateManifestEnvelope]:
    package = _package()
    manifest, envelope = _signed_manifest(package)
    store = FileUpdateStagingStore(root=root)
    store.stage(
        manifest=manifest,
        envelope=envelope,
        chunks=[package],
        cancelled=lambda: False,
        on_progress=lambda _count: None,
    )
    return (
        StagedPackageReview(
            staging_store=store,
            preflight=MsixPackagePreflight(signer=signer),
            expectation=MsixPackageExpectation(
                name=_NAME,
                publisher=_PUBLISHER,
                architecture=_ARCHITECTURE,
                signer_sha256=_SIGNER,
            ),
        ),
        manifest,
        envelope,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir()}


def test_staged_review_verifies_exact_accounted_candidate_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner()
    review, manifest, envelope = _review(root, signer)
    before = _snapshot(root)

    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.state is MsixPreflightState.VERIFIED
    assert result.can_install is False
    assert signer.calls == [root / "artifact.staged"]
    assert _snapshot(root) == before


def test_release_tool_entrypoint_still_rejects_artifact_staged(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner()
    review, manifest, _envelope = _review(root, signer)
    del review

    result = MsixPackagePreflight(signer=signer).verify(
        package_path=root / "artifact.staged",
        artifact=AuthenticatedReleaseArtifact(
            sha256=manifest.artifact_sha256,
            size_bytes=manifest.artifact_size_bytes,
            release_version=manifest.release_version,
        ),
        expectation=MsixPackageExpectation(
            name=_NAME,
            publisher=_PUBLISHER,
            architecture=_ARCHITECTURE,
            signer_sha256=_SIGNER,
        ),
    )

    assert result.reason is MsixPreflightReason.PACKAGE_IO_FAILED
    assert signer.calls == []


def test_staged_review_refuses_changed_or_missing_envelope_before_native_signer(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner()
    review, manifest, envelope = _review(root, signer)
    changed = SignedUpdateManifestEnvelope(
        raw_manifest=envelope.raw_manifest,
        signature=b"z" * len(envelope.signature),
        key_id=envelope.key_id,
    )

    changed_result = review.verify(manifest=manifest, envelope=changed)
    (root / "staged-update.ledger.json").unlink()
    missing_result = review.verify(manifest=manifest, envelope=envelope)

    assert changed_result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert missing_result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert signer.calls == []


def test_staged_review_never_caches_positive_result_across_tamper(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner()
    review, manifest, envelope = _review(root, signer)

    assert review.verify(manifest=manifest, envelope=envelope).state is MsixPreflightState.VERIFIED
    staged = root / "artifact.staged"
    staged.write_bytes(staged.read_bytes() + b"tamper")
    after = _snapshot(root)
    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert len(signer.calls) == 1
    assert _snapshot(root) == after


def test_staged_review_unknown_native_result_is_unverifiable_and_read_only(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner(error=PackageSignerUnavailable("synthetic unknown"))
    review, manifest, envelope = _review(root, signer)
    before = _snapshot(root)

    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.state is MsixPreflightState.REJECTED
    assert result.reason is MsixPreflightReason.SIGNATURE_UNVERIFIABLE
    assert _snapshot(root) == before


def test_staged_review_accessor_safety_failure_is_typed_not_raised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner()
    review, manifest, envelope = _review(root, signer)

    def unsafe_accessor() -> Path:
        raise UpdateStagingError(ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)

    monkeypatch.setattr(review._staging_store, "staged_package_path", unsafe_accessor)
    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.reason is MsixPreflightReason.PACKAGE_IO_FAILED
    assert signer.calls == []


def test_staged_review_rejects_ledger_mutation_after_native_without_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    mutated: list[bytes] = []

    def mutate() -> None:
        ledger = root / "staged-update.ledger.json"
        replacement = json.loads(ledger.read_bytes())
        replacement["signature_base64"] = base64.b64encode(b"z" * 64).decode()
        changed = json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode()
        ledger.write_bytes(changed)
        mutated.append(changed)

    signer = _FakePackageSigner(mutate=mutate)
    review, manifest, envelope = _review(root, signer)

    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert signer.calls == [root / "artifact.staged"]
    assert _snapshot(root)["staged-update.ledger.json"] == mutated[0]
    assert sorted(path.name for path in root.iterdir()) == [
        "artifact.staged", "staged-update.ledger.json"
    ]


def test_staged_review_rejects_package_path_swap_after_native_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    swapped = False
    original_components = msix_preflight_module._path_components

    def mutate() -> None:
        nonlocal swapped
        swapped = True

    def path_components(path: Path) -> tuple[tuple[int, ...], ...]:
        value = original_components(path)
        # This is a deterministic synthetic path-swap observation.  Windows
        # normally denies replacing a live no-share descriptor, so a real
        # rename would test OS locking rather than the adapter's fail-closed
        # post-native observation.
        return value + ((-1,),) if swapped else value

    signer = _FakePackageSigner(mutate=mutate)
    review, manifest, envelope = _review(root, signer)
    contents_before = _snapshot(root)
    monkeypatch.setattr(msix_preflight_module, "_path_components", path_components)

    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert signer.calls == [root / "artifact.staged"]
    assert _snapshot(root) == contents_before
    assert sorted(path.name for path in root.iterdir()) == [
        "artifact.staged", "staged-update.ledger.json"
    ]


def test_staged_review_rejects_orphan_partial_after_native_without_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()

    def mutate() -> None:
        (root / "artifact.partial").write_bytes(b"synthetic-orphan")

    signer = _FakePackageSigner(mutate=mutate)
    review, manifest, envelope = _review(root, signer)

    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert signer.calls == [root / "artifact.staged"]
    assert _snapshot(root)["artifact.partial"] == b"synthetic-orphan"
    assert sorted(path.name for path in root.iterdir()) == [
        "artifact.partial", "artifact.staged", "staged-update.ledger.json"
    ]


def test_staged_review_rejects_hardlinked_leaf_without_reading_native_signer(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    signer = _FakePackageSigner()
    review, manifest, envelope = _review(root, signer)
    os.link(root / "artifact.staged", root / "synthetic-hardlink")

    result = review.verify(manifest=manifest, envelope=envelope)

    assert result.reason is MsixPreflightReason.PACKAGE_CHANGED
    assert signer.calls == []
