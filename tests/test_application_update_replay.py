from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path

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
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from prompt_enhancer.infrastructure.updates.replay import (
    AtomicReplayLedger,
    ReplayLedgerError,
)
import prompt_enhancer.infrastructure.updates.replay as replay_module


NOW = datetime(2040, 1, 2, tzinfo=UTC)


class _Source:

    def __init__(self, envelope: SignedUpdateManifestEnvelope) -> None:
        self.envelope = envelope

    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        assert channel is UpdateChannel.STABLE
        return self.envelope


class _FailingLedger:

    def load(self) -> None:
        return None

    def persist_authenticated(self, **_: object) -> None:
        raise ReplayLedgerError()


def _envelope(
    signer: Ed25519PrivateKey,
    *,
    version: str,
    now: datetime = NOW,
    expires_at: datetime | None = None,
    artifact: bytes = b"synthetic-replay-artifact",
    key_id: str = "synthetic-replay-key",
) -> SignedUpdateManifestEnvelope:
    raw = json.dumps(
        {
            "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "artifact_size_bytes": len(artifact),
            "channel": "stable",
            "expires_at": (expires_at or now + timedelta(days=1)).isoformat(),
            "minimum_supported_version": "1.0.0",
            "published_at": (now - timedelta(minutes=1)).isoformat(),
            "release_version": version,
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SignedUpdateManifestEnvelope(
        raw_manifest=raw,
        signature=signer.sign(raw),
        key_id=key_id,
    )


def _coordinator(
    root: Path,
    signer: Ed25519PrivateKey,
    envelope: SignedUpdateManifestEnvelope,
    *,
    installed_version: str = "1.0.0",
    clock=lambda: NOW,
    ledger: object | None = None,
    verifier_signer: Ed25519PrivateKey | None = None,
    artifact_source: object | None = None,
    staging_store: object | None = None,
) -> ApplicationUpdateCoordinator:
    trust_signer = signer if verifier_signer is None else verifier_signer
    public = trust_signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return ApplicationUpdateCoordinator(
        installed_version=installed_version,
        channel=UpdateChannel.STABLE,
        source=_Source(envelope),
        verifier=Ed25519ManifestVerifier(
            public_keys={"synthetic-replay-key": public}),
        replay_ledger=AtomicReplayLedger(root=root) if ledger is None else ledger,
        artifact_source=artifact_source,
        staging_store=staging_store,
        clock=clock,
    )


def _check(coordinator: ApplicationUpdateCoordinator):
    before = coordinator.status()
    return coordinator.check(
        expected_revision=before.revision,
        expected_instance_id=before.instance_id,
    )


def test_manifest_only_check_persists_high_water_across_restart(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-replay-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    newest = _envelope(signer, version="3.0.0")

    first = _coordinator(root, signer, newest)
    assert _check(first).state is ApplicationUpdateState.AVAILABLE
    assert (root / "update-replay.ledger.json").is_file()

    restarted = _coordinator(root, signer, _envelope(signer, version="2.0.0"))
    replay = _check(restarted)

    assert replay.state is ApplicationUpdateState.FAILED
    assert replay.verification_code is UpdateRejection.REPLAYED_RELEASE
    assert replay.can_check is True
    assert replay.can_stage is False


def test_expired_historical_envelope_keeps_floor_without_exposing_release(
        tmp_path: Path) -> None:
    root = tmp_path / "synthetic-expired-replay-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    expired = _envelope(
        signer,
        version="3.0.0",
        expires_at=NOW + timedelta(minutes=1),
    )
    ledger = AtomicReplayLedger(root=root)
    ledger.persist_authenticated(expected_envelope=None, envelope=expired)
    later = NOW + timedelta(days=2)

    coordinator = _coordinator(
        root,
        signer,
        _envelope(signer, version="2.0.0", now=later),
        clock=lambda: later,
    )

    # Historical authenticity is sufficient for the floor, but never an offer.
    assert coordinator.status().state is ApplicationUpdateState.READY_TO_CHECK
    assert coordinator.status().available_version is None
    replay = _check(coordinator)
    assert replay.verification_code is UpdateRejection.REPLAYED_RELEASE


def test_same_current_version_with_a_different_authenticated_identity_is_refused(
        tmp_path: Path) -> None:
    root = tmp_path / "synthetic-current-identity-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    historical = _envelope(signer, version="3.0.0")
    ledger = AtomicReplayLedger(root=root)
    ledger.persist_authenticated(expected_envelope=None, envelope=historical)

    coordinator = _coordinator(
        root,
        signer,
        _envelope(signer, version="3.0.0", artifact=b"synthetic-conflict"),
        installed_version="3.0.0",
    )
    result = _check(coordinator)

    assert result.state is ApplicationUpdateState.FAILED
    assert result.verification_code is UpdateRejection.RELEASE_IDENTITY_CONFLICT


def test_malformed_or_guarded_ledger_quarantines_without_actions(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-malformed-replay-root"
    root.mkdir()
    (root / "update-replay.ledger.json").write_text("{", encoding="utf-8")
    signer = Ed25519PrivateKey.generate()
    coordinator = _coordinator(root, signer, _envelope(signer, version="2.0.0"))

    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert not any((status.can_check, status.can_stage, status.can_cancel,
                    status.can_retry, status.can_apply))


def test_persistence_failure_never_publishes_available(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-write-failure-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    coordinator = _coordinator(
        root,
        signer,
        _envelope(signer, version="2.0.0"),
        ledger=_FailingLedger(),
    )

    status = _check(coordinator)
    assert status.state is ApplicationUpdateState.FAILED
    assert status.can_check is False
    assert status.can_retry is False
    assert status.available_version is None


def test_compare_and_swap_never_overwrites_an_unobserved_floor(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cas-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    first, second = AtomicReplayLedger(root=root), AtomicReplayLedger(root=root)
    initial = first.load()
    assert initial is None and second.load() is None
    newest = _envelope(signer, version="3.0.0")
    first.persist_authenticated(expected_envelope=initial, envelope=newest)

    try:
        second.persist_authenticated(
            expected_envelope=None,
            envelope=_envelope(signer, version="2.0.0"),
        )
    except ReplayLedgerError:
        pass
    else:
        raise AssertionError("stale replay-ledger writer unexpectedly succeeded")
    assert second.load() == newest


@pytest.mark.parametrize("key_id,verifier_signer,expected", [
    ("synthetic-replay-key", Ed25519PrivateKey.generate(),
     UpdateRejection.BAD_SIGNATURE),
    ("retired-synthetic-key", None, UpdateRejection.UNKNOWN_KEY),
])
def test_restart_quarantines_revoked_or_unknown_replay_trust(
    tmp_path: Path,
    key_id: str,
    verifier_signer: Ed25519PrivateKey | None,
    expected: UpdateRejection,
) -> None:
    root = tmp_path / "synthetic-revoked-replay-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    historical = _envelope(signer, version="3.0.0", key_id=key_id)
    AtomicReplayLedger(root=root).persist_authenticated(
        expected_envelope=None,
        envelope=historical,
    )

    coordinator = _coordinator(
        root,
        signer,
        _envelope(signer, version="4.0.0"),
        verifier_signer=verifier_signer,
    )
    status = coordinator.status()

    assert status.state is ApplicationUpdateState.FAILED
    assert status.verification_code is expected
    assert not any((status.can_check, status.can_stage, status.can_cancel,
                    status.can_retry, status.can_apply))


@pytest.mark.parametrize("payload", [
    b'{"schema_version":1,"schema_version":1}',
    b"[" * 1_500 + b"0" + b"]" * 1_500,
    b"x" * (AtomicReplayLedger._MAX_BYTES + 1),
], ids=["duplicate", "deep", "oversize"])
def test_malformed_replay_ledger_variants_quarantine_without_actions(
    tmp_path: Path,
    payload: bytes,
) -> None:
    root = tmp_path / "synthetic-malformed-ledger-root"
    root.mkdir()
    (root / "update-replay.ledger.json").write_bytes(payload)
    signer = Ed25519PrivateKey.generate()

    coordinator = _coordinator(root, signer, _envelope(signer, version="2.0.0"))
    status = coordinator.status()

    assert status.state is ApplicationUpdateState.FAILED
    assert not any((status.can_check, status.can_stage, status.can_cancel,
                    status.can_retry, status.can_apply))


@pytest.mark.parametrize("name", ["update-replay.ledger.partial",
                                    "update-replay.ledger.lock"])
def test_orphan_partial_or_held_guard_quarantines_without_actions(
    tmp_path: Path,
    name: str,
) -> None:
    root = tmp_path / "synthetic-orphan-replay-root"
    root.mkdir()
    (root / name).write_bytes(b"synthetic-orphan")
    signer = Ed25519PrivateKey.generate()

    coordinator = _coordinator(root, signer, _envelope(signer, version="2.0.0"))
    status = coordinator.status()

    assert status.state is ApplicationUpdateState.FAILED
    assert not any((status.can_check, status.can_stage, status.can_cancel,
                    status.can_retry, status.can_apply))


def test_symlink_or_reparse_replay_leaf_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-symlink-replay-root"
    root.mkdir()
    target = root / "synthetic-target"
    target.write_bytes(b"synthetic-linked-leaf")
    ledger = root / "update-replay.ledger.json"
    try:
        os.symlink(target, ledger)
    except (NotImplementedError, OSError):
        pytest.skip("symlink fixtures are unsupported on this platform")
    with pytest.raises(ReplayLedgerError):
        AtomicReplayLedger(root=root).load()


def test_hardlink_replay_leaf_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-hardlink-replay-root"
    root.mkdir()
    target = root / "synthetic-target"
    target.write_bytes(b"synthetic-linked-leaf")
    ledger = root / "update-replay.ledger.json"
    try:
        os.link(target, ledger)
    except (NotImplementedError, OSError):
        pytest.skip("hardlink fixtures are unsupported on this platform")
    with pytest.raises(ReplayLedgerError):
        AtomicReplayLedger(root=root).load()


def test_replace_failure_preserves_old_evidence_and_quarantines_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-replace-replay-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    store = AtomicReplayLedger(root=root)
    old = _envelope(signer, version="2.0.0")
    store.persist_authenticated(expected_envelope=None, envelope=old)
    original = (root / "update-replay.ledger.json").read_bytes()
    real_replace = replay_module.os.replace

    def fail_promotion(source: object, target: object) -> None:
        if Path(target).name == "update-replay.ledger.json":
            raise OSError("synthetic replay promotion failure")
        real_replace(source, target)

    monkeypatch.setattr(replay_module.os, "replace", fail_promotion)
    with pytest.raises(ReplayLedgerError):
        store.persist_authenticated(
            expected_envelope=old,
            envelope=_envelope(signer, version="3.0.0"),
        )

    assert (root / "update-replay.ledger.json").read_bytes() == original
    assert (root / "update-replay.ledger.partial").is_file()
    with pytest.raises(ReplayLedgerError):
        store.load()
    coordinator = _coordinator(root, signer, _envelope(signer, version="4.0.0"))
    assert coordinator.status().state is ApplicationUpdateState.FAILED


def test_guard_cleanup_failure_never_publishes_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-guard-cleanup-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    real_unlink = Path.unlink

    def fail_guard_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.name == "update-replay.ledger.lock":
            raise OSError("synthetic replay guard cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_guard_unlink)
    coordinator = _coordinator(root, signer, _envelope(signer, version="2.0.0"))
    status = _check(coordinator)

    assert status.state is ApplicationUpdateState.FAILED
    assert not any((status.can_check, status.can_stage, status.can_cancel,
                    status.can_retry, status.can_apply))
    assert (root / "update-replay.ledger.lock").is_file()


def test_two_coordinators_refuse_a_stale_writer_without_replacing_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-coordinator-cas-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    first = _coordinator(root, signer, _envelope(signer, version="2.0.0"))
    stale = _coordinator(root, signer, _envelope(signer, version="3.0.0"))

    assert _check(first).state is ApplicationUpdateState.AVAILABLE
    original = (root / "update-replay.ledger.json").read_bytes()
    rejected = _check(stale)

    assert rejected.state is ApplicationUpdateState.FAILED
    assert rejected.can_check is False
    assert (root / "update-replay.ledger.json").read_bytes() == original


class _CountingArtifactSource:

    def __init__(self) -> None:
        self.calls = 0

    def iter_artifact(self, **_: object):
        self.calls += 1
        yield b"synthetic-artifact"


class _CountingStagingStore:

    def __init__(self) -> None:
        self.supersede_calls = 0

    def supersede_staged(self, **_: object) -> None:
        self.supersede_calls += 1

    def stage(self, **_: object) -> None:
        raise AssertionError("staging must not run after replay CAS conflict")


def test_stage_refuses_before_fetch_or_supersede_after_other_coordinator_advances(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-stage-cas-root"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    artifact_source, staging_store = _CountingArtifactSource(), _CountingStagingStore()
    first_envelope = _envelope(signer, version="2.0.0")
    first = _coordinator(
        root,
        signer,
        first_envelope,
        artifact_source=artifact_source,
        staging_store=staging_store,
    )
    available = _check(first)
    assert available.state is ApplicationUpdateState.AVAILABLE
    first._supersede_envelope = first_envelope  # type: ignore[attr-defined]
    second = _coordinator(root, signer, _envelope(signer, version="3.0.0"))
    assert _check(second).state is ApplicationUpdateState.AVAILABLE

    refused = first.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert refused.state is ApplicationUpdateState.FAILED
    assert artifact_source.calls == 0
    assert staging_store.supersede_calls == 0
