from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from threading import Event, Thread

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from prompt_enhancer.application.updates import (
    ApplicationUpdateCoordinator,
    ApplicationUpdateState,
    UpdateChannel,
    UpdateRejection,
)
from prompt_enhancer.application.updates.ports import SignedUpdateManifestEnvelope
from prompt_enhancer.application.updates.status import UpdateActionConflict
from prompt_enhancer.infrastructure.updates import Ed25519ManifestVerifier


NOW = datetime(2040, 1, 2, 3, 4, 5, tzinfo=UTC)


def _manifest(
    *,
    version: str = "2.0.0",
    channel: str = "stable",
    expires_at: datetime | None = None,
    artifact_size: int = 2_048,
) -> bytes:
    return json.dumps(
        {
            "artifact_sha256": "a" * 64,
            "artifact_size_bytes": artifact_size,
            "channel": channel,
            "expires_at": (expires_at or NOW + timedelta(days=1)).isoformat(),
            "minimum_supported_version": "1.0.0",
            "published_at": (NOW - timedelta(minutes=1)).isoformat(),
            "release_version": version,
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class _Source:
    def __init__(self, raw: bytes, signer: Ed25519PrivateKey) -> None:
        self.raw = raw
        self.signer = signer
        self.calls = 0

    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        self.calls += 1
        return SignedUpdateManifestEnvelope(
            raw_manifest=self.raw,
            signature=self.signer.sign(self.raw),
            key_id="release-2040",
        )


def _coordinator(source: _Source, signer: Ed25519PrivateKey):
    public = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=source,
        verifier=Ed25519ManifestVerifier(public_keys={"release-2040": public}),
        clock=lambda: NOW,
    )


def _check(coordinator: ApplicationUpdateCoordinator):
    snapshot = coordinator.status()
    return coordinator.check(
        expected_revision=snapshot.revision,
        expected_instance_id=snapshot.instance_id,
    )


def test_ed25519_verifier_accepts_only_the_exact_payload_key_and_signature() -> None:
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    raw = _manifest()
    signature = signer.sign(raw)
    verifier = Ed25519ManifestVerifier(public_keys={"release-2040": public})

    assert verifier.verify(payload=raw, signature=signature, key_id="release-2040").value == "valid"
    assert verifier.verify(payload=raw + b"x", signature=signature, key_id="release-2040").value == "invalid"
    assert verifier.verify(payload=raw, signature=signature, key_id="other-key").value == "unknown_key"
    assert verifier.verify(payload=raw, signature=signature[:-1], key_id="release-2040").value == "invalid"


def test_coordinator_reports_a_verified_newer_release_without_exposing_bytes() -> None:
    key = Ed25519PrivateKey.generate()
    source = _Source(_manifest(), key)
    coordinator = _coordinator(source, key)

    assert coordinator.status().state is ApplicationUpdateState.READY_TO_CHECK
    result = coordinator.check()

    assert result.state is ApplicationUpdateState.AVAILABLE
    assert result.available_version == "2.0.0"
    assert result.artifact_size_bytes == 2_048
    assert result.downloaded_bytes == 0
    assert result.can_stage is False
    assert result.verification_code is None
    assert source.calls == 1
    assert "artifact_sha256" not in result.model_dump_json()


def test_current_is_not_misreported_as_a_failure_but_downgrade_is_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    current_source = _Source(_manifest(version="1.0.0"), key)
    current = _coordinator(current_source, key).check()
    downgrade_source = _Source(_manifest(version="0.9.0"), key)
    downgrade = _coordinator(downgrade_source, key).check()

    assert current.state is ApplicationUpdateState.CURRENT
    assert current.reason_code is None
    assert downgrade.state is ApplicationUpdateState.FAILED
    assert downgrade.verification_code is UpdateRejection.DOWNGRADE


def test_tamper_expiry_channel_and_unknown_key_fail_closed() -> None:
    key = Ed25519PrivateKey.generate()
    cases = [
        (_manifest(expires_at=NOW - timedelta(seconds=1)), UpdateRejection.EXPIRED),
        (_manifest(channel="beta"), UpdateRejection.CHANNEL_MISMATCH),
    ]
    for raw, expected in cases:
        result = _coordinator(_Source(raw, key), key).check()
        assert result.state is ApplicationUpdateState.FAILED
        assert result.verification_code is expected
        assert result.can_stage is False

    source = _Source(_manifest(), key)
    coordinator = _coordinator(source, key)
    source.raw += b" "
    # The source signs its current bytes, so this is a different but still
    # schema-valid signed payload. Exact-schema validation remains decisive.
    assert coordinator.check().state is ApplicationUpdateState.AVAILABLE

    other_key = Ed25519PrivateKey.generate()
    source = _Source(_manifest(), other_key)
    trusted = _coordinator(source, key)
    rejected = trusted.check()
    assert rejected.state is ApplicationUpdateState.FAILED
    assert rejected.verification_code is UpdateRejection.BAD_SIGNATURE


def test_replayed_older_release_and_conflicting_same_version_are_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    source = _Source(_manifest(version="3.0.0"), key)
    coordinator = _coordinator(source, key)
    assert coordinator.check().available_version == "3.0.0"

    source.raw = _manifest(version="2.0.0")
    replay = coordinator.check()
    assert replay.verification_code is UpdateRejection.REPLAYED_RELEASE

    source.raw = _manifest(version="3.0.0", artifact_size=4_096)
    conflict = coordinator.check()
    assert conflict.verification_code is UpdateRejection.RELEASE_IDENTITY_CONFLICT


def test_concurrent_check_returns_checking_and_opens_the_source_once() -> None:
    key = Ed25519PrivateKey.generate()
    entered = Event()
    release = Event()

    class _BlockingSource(_Source):
        def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
            entered.set()
            release.wait(timeout=2)
            return super().fetch_manifest(channel=channel)

    source = _BlockingSource(_manifest(), key)
    coordinator = _coordinator(source, key)
    results = []
    worker = Thread(target=lambda: results.append(coordinator.check()))
    worker.start()
    assert entered.wait(timeout=1)

    with pytest.raises(UpdateActionConflict):
        coordinator.check()
    assert source.calls == 0

    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert source.calls == 1
    assert results[0].state is ApplicationUpdateState.AVAILABLE


def test_source_exception_becomes_content_free_retryable_failure() -> None:
    key = Ed25519PrivateKey.generate()

    class _FailingSource(_Source):
        def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
            raise RuntimeError("EXAMPLE_PRIVATE_UPDATE_SOURCE_CANARY")

    coordinator = _coordinator(_FailingSource(_manifest(), key), key)
    result = coordinator.check()

    assert result.state is ApplicationUpdateState.FAILED
    assert result.reason_code.value == "release_feed_unavailable"
    assert result.verification_code is None
    assert "EXAMPLE_PRIVATE_UPDATE_SOURCE_CANARY" not in result.model_dump_json()
