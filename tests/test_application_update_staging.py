from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from prompt_enhancer.application.updates import (
    ApplicationUpdateCoordinator,
    ApplicationUpdateState,
    UpdateChannel,
)
from prompt_enhancer.application.updates.ports import SignedUpdateManifestEnvelope
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from prompt_enhancer.infrastructure.updates.staging import FileUpdateStagingStore

NOW = datetime(2040, 1, 2, tzinfo=UTC)
ARTIFACT = b"synthetic-signed-update-artifact"


class _ManifestSource:

    def __init__(self, envelope: SignedUpdateManifestEnvelope) -> None:
        self.envelope = envelope
        self.calls = 0

    def fetch_manifest(self, *,
                       channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        assert channel is UpdateChannel.STABLE
        self.calls += 1
        return self.envelope


class _ArtifactSource:

    def iter_artifact(self, **_kwargs: object):
        yield ARTIFACT[:8]
        yield ARTIFACT[8:]


def _coordinator(root: Path) -> ApplicationUpdateCoordinator:
    signer = Ed25519PrivateKey.generate()
    raw = json.dumps(
        {
            "schema_version": 1,
            "release_version": "2.0.0",
            "minimum_supported_version": "1.0.0",
            "channel": "stable",
            "published_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
            "artifact_sha256": hashlib.sha256(ARTIFACT).hexdigest(),
            "artifact_size_bytes": len(ARTIFACT),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    envelope = SignedUpdateManifestEnvelope(
        raw_manifest=raw,
        signature=signer.sign(raw),
        key_id="synthetic-release",
    )
    public = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=_ManifestSource(envelope),
        verifier=Ed25519ManifestVerifier(
            public_keys={"synthetic-release": public}),
        artifact_source=_ArtifactSource(),
        staging_store=FileUpdateStagingStore(root=root),
        clock=lambda: NOW,
    )


def test_verified_artifact_stages_atomically_with_a_private_ledger(
        tmp_path: Path) -> None:
    root = tmp_path / "synthetic-update-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    ready = coordinator.status()
    available = coordinator.check(
        expected_revision=ready.revision,
        expected_instance_id=ready.instance_id,
    )
    staging = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staging.state is ApplicationUpdateState.STAGING

    deadline = time.monotonic() + 2
    while coordinator.status().state is ApplicationUpdateState.STAGING:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    staged = coordinator.status()
    assert staged.state is ApplicationUpdateState.STAGED
    assert staged.can_apply is False
    assert (root / "artifact.staged").read_bytes() == ARTIFACT
    assert not (root / "artifact.partial").exists()
    assert (root / "staged-update.ledger.json").is_file()

    recovered = ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=coordinator._source,  # type: ignore[attr-defined]
        verifier=coordinator._verifier,  # type: ignore[attr-defined]
        artifact_source=_ArtifactSource(),
        staging_store=FileUpdateStagingStore(root=root),
        clock=lambda: NOW,
    )
    assert recovered.status().state is ApplicationUpdateState.STAGED
    assert recovered.status().can_apply is False
