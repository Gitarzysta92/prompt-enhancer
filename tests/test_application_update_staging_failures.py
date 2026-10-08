from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from threading import Event, Thread
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import pytest

from prompt_enhancer.application.updates import (
    ApplicationUpdateCoordinator,
    ApplicationUpdateReason,
    ApplicationUpdateState,
    ApplicationUpdateStatus,
    UpdateChannel,
    UpdateActionConflict,
    UpdateRejection,
)
from prompt_enhancer.application.updates.ports import SignedUpdateManifestEnvelope
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from prompt_enhancer.infrastructure.updates.staging import FileUpdateStagingStore
import prompt_enhancer.infrastructure.updates.staging as staging_module

from test_application_update_staging import ARTIFACT, NOW, _ArtifactSource, _coordinator


NEW_ARTIFACT = b"synthetic-next-release-artifact"


def _wait_terminal(coordinator: ApplicationUpdateCoordinator) -> None:
    deadline = time.monotonic() + 3
    while coordinator.status().state in {
        ApplicationUpdateState.CHECKING,
        ApplicationUpdateState.STAGING,
    }:
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _stage_valid(tmp_path: Path) -> tuple[Path, ApplicationUpdateCoordinator]:
    root = tmp_path / "synthetic-update-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    ready = coordinator.status()
    available = coordinator.check(
        expected_revision=ready.revision,
        expected_instance_id=ready.instance_id,
    )
    assert available.state is ApplicationUpdateState.AVAILABLE
    staging = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staging.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)
    assert coordinator.status().state is ApplicationUpdateState.STAGED
    return root, coordinator


def _restart(
    root: Path,
    coordinator: ApplicationUpdateCoordinator,
    *,
    clock=lambda: NOW,
) -> ApplicationUpdateCoordinator:
    return ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=coordinator._source,  # type: ignore[attr-defined]
        verifier=coordinator._verifier,  # type: ignore[attr-defined]
        artifact_source=_ArtifactSource(),
        staging_store=FileUpdateStagingStore(root=root),
        clock=clock,
    )


def _ledger(root: Path) -> dict[str, object]:
    return json.loads((root / "staged-update.ledger.json").read_text(encoding="utf-8"))


def _write_ledger(root: Path, value: bytes | str | dict[str, object]) -> None:
    target = root / "staged-update.ledger.json"
    if isinstance(value, dict):
        target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    elif isinstance(value, bytes):
        target.write_bytes(value)
    else:
        target.write_text(value, encoding="utf-8")


def _signed_envelope(
    signer: Ed25519PrivateKey,
    *,
    version: str,
    artifact: bytes,
    expires_at: datetime = NOW + timedelta(days=1),
) -> SignedUpdateManifestEnvelope:
    raw = json.dumps(
        {
            "schema_version": 1,
            "release_version": version,
            "minimum_supported_version": "1.0.0",
            "channel": "stable",
            "published_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": expires_at.isoformat(),
            "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "artifact_size_bytes": len(artifact),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SignedUpdateManifestEnvelope(
        raw_manifest=raw,
        signature=signer.sign(raw),
        key_id="synthetic-release",
    )


class _ArtifactChunks:
    def __init__(self, chunks: list[bytes] | None = None, error: Exception | None = None) -> None:
        self.chunks = chunks or []
        self.error = error
        self.calls = 0

    def iter_artifact(self, **_kwargs: object):
        self.calls += 1
        if self.error is not None:
            raise self.error
        yield from self.chunks


class _MutableManifestSource:
    def __init__(self, envelope: SignedUpdateManifestEnvelope) -> None:
        self.envelope = envelope

    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        assert channel is UpdateChannel.STABLE
        return self.envelope


def _coordinator_with_signer(
    root: Path,
    *,
    version: str = "2.0.0",
    artifact: bytes = ARTIFACT,
) -> tuple[ApplicationUpdateCoordinator, _MutableManifestSource, Ed25519PrivateKey, _ArtifactChunks]:
    signer = Ed25519PrivateKey.generate()
    source = _MutableManifestSource(_signed_envelope(signer, version=version, artifact=artifact))
    public = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    artifact_source = _ArtifactChunks([artifact])
    coordinator = ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=source,
        verifier=Ed25519ManifestVerifier(public_keys={"synthetic-release": public}),
        artifact_source=artifact_source,
        staging_store=FileUpdateStagingStore(root=root),
        clock=lambda: NOW,
    )
    return coordinator, source, signer, artifact_source


def _stage_valid_with_signer(
    tmp_path: Path,
) -> tuple[Path, ApplicationUpdateCoordinator, _MutableManifestSource, Ed25519PrivateKey]:
    root = tmp_path / "synthetic-update-cache"
    root.mkdir()
    coordinator, source, signer, _artifact_source = _coordinator_with_signer(root)
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
    _wait_terminal(coordinator)
    assert coordinator.status().state is ApplicationUpdateState.STAGED
    return root, coordinator, source, signer


@pytest.mark.parametrize("field,value", [("artifact_sha256", "b" * 64), ("artifact_size_bytes", len(ARTIFACT) + 1)])
def test_restart_rejects_tampered_ledger_without_rewriting_signed_artifact(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    root, coordinator = _stage_valid(tmp_path)
    original_artifact = (root / "artifact.staged").read_bytes()
    ledger = _ledger(root)
    ledger[field] = value
    _write_ledger(root, ledger)

    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().reason_code is ApplicationUpdateReason.ARTIFACT_VERIFICATION_FAILED
    assert recovered.status().can_retry is False
    assert (root / "artifact.staged").read_bytes() == original_artifact
    assert (root / "staged-update.ledger.json").read_bytes() == json.dumps(
        ledger, sort_keys=True, separators=(",", ":")
    ).encode()


def test_restart_rejects_raw_artifact_tamper_and_leaves_evidence_untouched(tmp_path: Path) -> None:
    root, coordinator = _stage_valid(tmp_path)
    target = root / "artifact.staged"
    target.write_bytes(b"tampered-synthetic-artifact")
    before = target.read_bytes()

    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().can_retry is False
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    "ledger_mutation",
    [
        lambda _data: b"x" * (64 * 1024),
        lambda data: json.dumps({**data, "artifact_size_bytes": True}),
        lambda data: json.dumps({**data, "artifact_sha256": "not-a-digest"}),
        lambda data: json.dumps(data, sort_keys=True, separators=(",", ":"))[:-1]
        + ',"artifact_size_bytes":%d}' % len(ARTIFACT),
    ],
    ids=["oversize", "boolean-field", "malformed-digest", "duplicate-key"],
)
def test_restart_quarantines_malformed_or_duplicate_ledger_without_cleanup(
    tmp_path: Path,
    ledger_mutation,
) -> None:
    root, coordinator = _stage_valid(tmp_path)
    original_ledger = (root / "staged-update.ledger.json").read_bytes()
    data = _ledger(root)
    mutated = ledger_mutation(data)
    _write_ledger(root, mutated.encode() if isinstance(mutated, str) else mutated)

    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().reason_code in {
        ApplicationUpdateReason.ARTIFACT_VERIFICATION_FAILED,
        ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
    }
    assert recovered.status().can_retry is False
    assert (root / "artifact.staged").read_bytes() == ARTIFACT
    assert (root / "staged-update.ledger.json").read_bytes() != original_ledger


@pytest.mark.parametrize("kind", ["bad-signature", "expired", "revoked-key"])
def test_restart_reauthenticates_manifest_before_restoring_staged(
    tmp_path: Path,
    kind: str,
) -> None:
    root, coordinator, source, signer = _stage_valid_with_signer(tmp_path)
    ledger = _ledger(root)
    raw = base64.b64decode(ledger["manifest_base64"])
    if kind == "expired":
        manifest = json.loads(raw)
        manifest["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ledger["signature_base64"] = base64.b64encode(signer.sign(raw)).decode()
    elif kind == "bad-signature":
        ledger["signature_base64"] = base64.b64encode(b"x" * 64).decode()
    else:
        ledger["key_id"] = "revoked-release"
    ledger["manifest_base64"] = base64.b64encode(raw).decode()
    _write_ledger(root, ledger)

    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().can_retry is False
    assert (root / "artifact.staged").read_bytes() == ARTIFACT


def test_orphan_partial_and_partial_ledger_are_nonretryable_and_unmodified(tmp_path: Path) -> None:
    for name in ("artifact.partial", "staged-update.ledger.partial"):
        root = tmp_path / name.replace(".", "-")
        root.mkdir()
        coordinator = _coordinator(root)
        target = root / name
        target.write_bytes(b"orphan-synthetic-evidence")
        before = target.read_bytes()
        recovered = _restart(root, coordinator)
        assert recovered.status().state is ApplicationUpdateState.FAILED
        assert recovered.status().reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
        assert recovered.status().can_retry is False
        assert target.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="symlink fixtures are unsupported on Windows")
def test_dangling_symlink_evidence_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-symlink-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    os.symlink(root / "missing-target", root / "artifact.partial")

    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert recovered.status().can_retry is False
    assert (root / "artifact.partial").is_symlink()


def test_hardlink_evidence_is_not_treated_as_owned(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-hardlink-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    outside = tmp_path / "synthetic-outside-evidence"
    outside.write_bytes(b"hardlink-evidence")
    os.link(outside, root / "artifact.partial")

    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert recovered.status().can_retry is False
    assert outside.read_bytes() == b"hardlink-evidence"


def test_reparse_like_leaf_is_quarantined_without_following_or_removing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-reparse-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    target = root / "artifact.partial"
    target.write_bytes(b"reparse-like-evidence")
    real_lstat = Path.lstat

    def fake_lstat(path: Path):
        result = real_lstat(path)
        if path == target:
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_nlink=1,
                st_file_attributes=0x400,
            )
        return result

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    recovered = _restart(root, coordinator)

    assert recovered.status().state is ApplicationUpdateState.FAILED
    assert recovered.status().reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert recovered.status().can_retry is False
    assert target.read_bytes() == b"reparse-like-evidence"


@pytest.mark.parametrize(
    ("chunks", "error", "reason"),
    [
        ([], RuntimeError("EXAMPLE_PRIVATE_SOURCE_FAILURE"), ApplicationUpdateReason.ARTIFACT_DOWNLOAD_FAILED),
        ([ARTIFACT[:3]], None, ApplicationUpdateReason.ARTIFACT_VERIFICATION_FAILED),
        ([ARTIFACT, b"extra"], None, ApplicationUpdateReason.ARTIFACT_VERIFICATION_FAILED),
        ([b"x" * len(ARTIFACT)], None, ApplicationUpdateReason.ARTIFACT_VERIFICATION_FAILED),
    ],
    ids=["source-exception", "truncated", "oversize", "wrong-hash"],
)
def test_artifact_failures_clean_owned_partial_and_publish_no_ready_state(
    tmp_path: Path,
    chunks: list[bytes],
    error: Exception | None,
    reason: ApplicationUpdateReason,
) -> None:
    root = tmp_path / "synthetic-artifact-failure-cache"
    root.mkdir()
    source = _ArtifactChunks(chunks, error)
    coordinator = _coordinator(root)
    coordinator._artifact_source = source  # type: ignore[attr-defined]
    available = coordinator.check()
    assert available.state is ApplicationUpdateState.AVAILABLE
    staging = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staging.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)

    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.reason_code is reason
    assert not (root / "artifact.partial").exists()
    assert not (root / "artifact.staged").exists()


def test_cancel_then_exact_retry_restages_the_pinned_release(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cancel-cache"
    root.mkdir()
    entered = Event()

    class _CancelableSource:
        attempts = 0

        def iter_artifact(self, **_kwargs: object):
            self.attempts += 1
            if self.attempts == 1:
                yield ARTIFACT[:8]
                entered.set()
                while True:
                    yield b""
            yield ARTIFACT[:8]
            yield ARTIFACT[8:]

    artifact_source = _CancelableSource()
    coordinator = _coordinator(root)
    coordinator._artifact_source = artifact_source  # type: ignore[attr-defined]
    available = coordinator.check()
    staging = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staging.state is ApplicationUpdateState.STAGING
    assert entered.wait(timeout=1)
    canceled = coordinator.cancel(
        expected_revision=staging.revision,
        expected_instance_id=staging.instance_id,
    )
    assert canceled.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)
    failed = coordinator.status()
    assert failed.reason_code is ApplicationUpdateReason.STAGING_INTERRUPTED
    assert failed.can_retry is True

    retried = coordinator.retry(
        expected_revision=failed.revision,
        expected_instance_id=failed.instance_id,
    )
    assert retried.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)
    assert coordinator.status().state is ApplicationUpdateState.STAGED
    assert artifact_source.attempts == 2
    assert (root / "artifact.staged").read_bytes() == ARTIFACT


def test_stale_revision_and_instance_fences_refuse_every_mutation(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-fence-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    ready = coordinator.status()
    with pytest.raises(UpdateActionConflict):
        coordinator.check(expected_revision=ready.revision - 1, expected_instance_id=ready.instance_id)
    with pytest.raises(UpdateActionConflict):
        coordinator.check(expected_revision=ready.revision, expected_instance_id="b" * 32)

    available = coordinator.check(
        expected_revision=ready.revision,
        expected_instance_id=ready.instance_id,
    )
    for action in (coordinator.stage, coordinator.cancel, coordinator.retry):
        with pytest.raises(UpdateActionConflict):
            action(expected_revision=available.revision - 1, expected_instance_id=available.instance_id)
        with pytest.raises(UpdateActionConflict):
            action(expected_revision=available.revision, expected_instance_id="b" * 32)


def test_quarantined_failure_does_not_bypass_false_capabilities(tmp_path: Path) -> None:
    root, coordinator = _stage_valid(tmp_path)
    (root / "artifact.partial").write_bytes(b"quarantine")
    quarantined = _restart(root, coordinator)
    status = quarantined.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.can_check is False
    assert status.can_retry is False
    assert status.can_cancel is False
    for action in (quarantined.check, quarantined.retry, quarantined.cancel, quarantined.stage):
        with pytest.raises(UpdateActionConflict):
            action(expected_revision=status.revision, expected_instance_id=status.instance_id)


def test_expiry_between_check_and_stage_refuses_before_artifact_fetch(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-expiry-cache"
    root.mkdir()
    artifact_source = _ArtifactChunks([ARTIFACT])
    coordinator = _coordinator(root)
    coordinator._artifact_source = artifact_source  # type: ignore[attr-defined]
    available = coordinator.check()
    coordinator._clock = lambda: NOW + timedelta(days=2)  # type: ignore[attr-defined]

    failed = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )

    assert failed.state is ApplicationUpdateState.FAILED
    assert failed.verification_code is not None
    assert artifact_source.calls == 0


def test_same_release_recheck_preserves_staged_evidence(tmp_path: Path) -> None:
    root, coordinator = _stage_valid(tmp_path)
    staged = coordinator.status()
    result = coordinator.check(
        expected_revision=staged.revision,
        expected_instance_id=staged.instance_id,
    )

    assert result.state is ApplicationUpdateState.STAGED
    assert (root / "artifact.staged").read_bytes() == ARTIFACT


def test_newer_release_can_supersede_an_existing_staged_release(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-supersede-cache"
    root.mkdir()
    coordinator, source, signer, _artifact_source = _coordinator_with_signer(root)
    available = coordinator.check()
    staging = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staging.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)
    assert coordinator.status().state is ApplicationUpdateState.STAGED
    source.envelope = _signed_envelope(signer, version="3.0.0", artifact=NEW_ARTIFACT)
    coordinator._artifact_source = _ArtifactChunks([NEW_ARTIFACT[:8], NEW_ARTIFACT[8:]])  # type: ignore[attr-defined]
    staged = coordinator.status()
    available = coordinator.check(
        expected_revision=staged.revision,
        expected_instance_id=staged.instance_id,
    )
    assert available.state is ApplicationUpdateState.AVAILABLE
    assert available.available_version == "3.0.0"
    staged_new = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staged_new.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)

    assert coordinator.status().state is ApplicationUpdateState.STAGED
    assert coordinator.status().available_version == "3.0.0"
    assert (root / "artifact.staged").read_bytes() == NEW_ARTIFACT


def test_thread_start_failure_does_not_leave_perpetual_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-start-failure-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    available = coordinator.check()

    def fail_start(_thread: Thread) -> None:
        raise RuntimeError("EXAMPLE_PRIVATE_THREAD_START_FAILURE")

    monkeypatch.setattr(Thread, "start", fail_start)
    coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )

    assert coordinator.status().state is not ApplicationUpdateState.STAGING
    assert coordinator.status().can_cancel is False


def test_ledger_promotion_failure_with_final_artifact_is_nonretryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-promotion-failure-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    available = coordinator.check()
    real_replace = staging_module.os.replace
    replace_calls = 0

    def fail_ledger_promotion(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("EXAMPLE_PRIVATE_LEDGER_PROMOTION_FAILURE")
        real_replace(source, target)

    monkeypatch.setattr(staging_module.os, "replace", fail_ledger_promotion)
    staging = coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert staging.state is ApplicationUpdateState.STAGING
    _wait_terminal(coordinator)

    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert status.can_retry is False
    assert (root / "artifact.staged").read_bytes() == ARTIFACT


def test_shutdown_during_blocked_worker_never_publishes_ready(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-shutdown-cache"
    root.mkdir()
    entered = Event()
    release = Event()

    class _BlockingSource:
        def iter_artifact(self, **_kwargs: object):
            entered.set()
            release.wait(timeout=2)
            yield ARTIFACT

    coordinator = _coordinator(root)
    coordinator._artifact_source = _BlockingSource()  # type: ignore[attr-defined]
    available = coordinator.check()
    coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    assert entered.wait(timeout=1)
    shutdown = Thread(target=coordinator.shutdown)
    shutdown.start()
    time.sleep(0.05)
    release.set()
    shutdown.join(timeout=2)
    assert not shutdown.is_alive()

    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert status.can_check is False
    assert status.can_retry is False
    assert status.state is not ApplicationUpdateState.READY_TO_CHECK


def test_repeated_available_check_does_not_invent_staged_bytes(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-repeat-check-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    first = coordinator.check()
    second = coordinator.check(
        expected_revision=first.revision,
        expected_instance_id=first.instance_id,
    )

    assert first.state is ApplicationUpdateState.AVAILABLE
    assert second.state is ApplicationUpdateState.AVAILABLE
    assert second.downloaded_bytes == 0


def test_manifest_only_coordinator_never_restores_staged_without_artifact_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-manifest-only-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    coordinator._artifact_source = None  # type: ignore[attr-defined]
    coordinator._staging_store = None  # type: ignore[attr-defined]
    first = coordinator.check()
    second = coordinator.check(
        expected_revision=first.revision,
        expected_instance_id=first.instance_id,
    )

    assert first.state is ApplicationUpdateState.AVAILABLE
    assert first.can_stage is False
    assert second.state is ApplicationUpdateState.AVAILABLE
    assert second.downloaded_bytes == 0


def test_check_a_then_b_can_stage_b_without_a_staged_evidence(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-no-cache-supersede"
    root.mkdir()
    coordinator, source, signer, _artifact_source = _coordinator_with_signer(root)
    first = coordinator.check()
    source.envelope = _signed_envelope(signer, version="3.0.0", artifact=NEW_ARTIFACT)
    coordinator._artifact_source = _ArtifactChunks([NEW_ARTIFACT])  # type: ignore[attr-defined]
    second = coordinator.check(
        expected_revision=first.revision,
        expected_instance_id=first.instance_id,
    )
    staged = coordinator.stage(
        expected_revision=second.revision,
        expected_instance_id=second.instance_id,
    )
    _wait_terminal(coordinator)

    assert staged.state is ApplicationUpdateState.STAGING
    assert coordinator.status().state is ApplicationUpdateState.STAGED
    assert (root / "artifact.staged").read_bytes() == NEW_ARTIFACT


def test_staged_a_check_b_then_repeat_b_stays_available(tmp_path: Path) -> None:
    root, coordinator, source, signer = _stage_valid_with_signer(tmp_path)
    source.envelope = _signed_envelope(signer, version="3.0.0", artifact=NEW_ARTIFACT)
    coordinator._artifact_source = _ArtifactChunks([NEW_ARTIFACT])  # type: ignore[attr-defined]
    staged = coordinator.status()
    available_b = coordinator.check(
        expected_revision=staged.revision,
        expected_instance_id=staged.instance_id,
    )
    repeated_b = coordinator.check(
        expected_revision=available_b.revision,
        expected_instance_id=available_b.instance_id,
    )

    assert available_b.state is ApplicationUpdateState.AVAILABLE
    assert repeated_b.state is ApplicationUpdateState.AVAILABLE
    assert repeated_b.available_version == "3.0.0"
    assert repeated_b.downloaded_bytes == 0


def test_staged_a_check_b_check_c_stages_c_over_actual_a(tmp_path: Path) -> None:
    root, coordinator, source, signer = _stage_valid_with_signer(tmp_path)
    source.envelope = _signed_envelope(signer, version="3.0.0", artifact=NEW_ARTIFACT)
    coordinator._artifact_source = _ArtifactChunks([NEW_ARTIFACT])  # type: ignore[attr-defined]
    staged = coordinator.status()
    available_b = coordinator.check(
        expected_revision=staged.revision,
        expected_instance_id=staged.instance_id,
    )
    source.envelope = _signed_envelope(signer, version="4.0.0", artifact=b"synthetic-final-release")
    final_artifact = b"synthetic-final-release"
    coordinator._artifact_source = _ArtifactChunks([final_artifact])  # type: ignore[attr-defined]
    available_c = coordinator.check(
        expected_revision=available_b.revision,
        expected_instance_id=available_b.instance_id,
    )
    staged_c = coordinator.stage(
        expected_revision=available_c.revision,
        expected_instance_id=available_c.instance_id,
    )
    _wait_terminal(coordinator)

    assert staged_c.state is ApplicationUpdateState.STAGING
    assert coordinator.status().state is ApplicationUpdateState.STAGED
    assert coordinator.status().available_version == "4.0.0"
    assert (root / "artifact.staged").read_bytes() == final_artifact


@pytest.mark.parametrize("kind", ["older", "same-version-conflict"])
def test_recovered_staged_release_initializes_high_water_rejection(
    tmp_path: Path,
    kind: str,
) -> None:
    root, coordinator, source, signer = _stage_valid_with_signer(tmp_path)
    recovered = _restart(root, coordinator)
    if kind == "older":
        source.envelope = _signed_envelope(signer, version="1.5.0", artifact=ARTIFACT)
    else:
        source.envelope = _signed_envelope(signer, version="2.0.0", artifact=b"synthetic-conflicting-artifact")
    status = recovered.status()
    result = recovered.check(
        expected_revision=status.revision,
        expected_instance_id=status.instance_id,
    )

    assert result.state is ApplicationUpdateState.FAILED
    assert result.verification_code is not None
    assert result.verification_code.value in {"replayed_release", "release_identity_conflict"}


def test_authenticated_newer_release_then_installed_version_is_replay(
    tmp_path: Path,
) -> None:
    root, coordinator, source, signer = _stage_valid_with_signer(tmp_path)
    recovered = _restart(root, coordinator)

    source.envelope = _signed_envelope(
        signer,
        version="3.0.0",
        artifact=NEW_ARTIFACT,
    )
    staged = recovered.status()
    newer = recovered.check(
        expected_revision=staged.revision,
        expected_instance_id=staged.instance_id,
    )
    assert newer.state is ApplicationUpdateState.AVAILABLE
    assert newer.available_version == "3.0.0"

    source.envelope = _signed_envelope(
        signer,
        version="1.0.0",
        artifact=ARTIFACT,
    )
    installed_version = recovered.check(
        expected_revision=newer.revision,
        expected_instance_id=newer.instance_id,
    )

    assert installed_version.state is ApplicationUpdateState.FAILED
    assert installed_version.state is not ApplicationUpdateState.CURRENT
    assert installed_version.verification_code is UpdateRejection.REPLAYED_RELEASE


def test_blocked_metadata_fetch_finishing_after_shutdown_is_uncertain(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-blocked-check-cache"
    root.mkdir()
    entered = Event()
    release = Event()

    class _BlockingManifestSource:
        def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
            entered.set()
            release.wait(timeout=2)
            raise RuntimeError("EXAMPLE_PRIVATE_SHUTDOWN_SOURCE_FAILURE")

    base = _coordinator(root)
    base._source = _BlockingManifestSource()  # type: ignore[attr-defined]
    before = base.status()
    result: list[ApplicationUpdateStatus] = []

    worker = Thread(target=lambda: result.append(base.check(
        expected_revision=before.revision,
        expected_instance_id=before.instance_id,
    )))
    worker.start()
    assert entered.wait(timeout=1)
    try:
        base.shutdown()
        raise AssertionError("blocked metadata check shutdown must raise")
    except RuntimeError as error:
        assert str(error) == "application update check did not terminate"
    finally:
        release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    status = base.status()

    assert result and result[0].state is ApplicationUpdateState.FAILED
    assert status.reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert status.can_check is False
    assert status.can_retry is False
    assert status.can_cancel is False


def test_artifact_iterator_close_failure_does_not_strand_staging(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-close-failure-cache"
    root.mkdir()

    class _CloseFailingIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise RuntimeError("EXAMPLE_PRIVATE_ITERATOR_FAILURE")

        def close(self) -> None:
            raise RuntimeError("EXAMPLE_PRIVATE_ITERATOR_CLOSE_FAILURE")

    class _CloseFailingSource:
        def iter_artifact(self, **_kwargs: object):
            return _CloseFailingIterator()

    coordinator = _coordinator(root)
    coordinator._artifact_source = _CloseFailingSource()  # type: ignore[attr-defined]
    available = coordinator.check()
    coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    _wait_terminal(coordinator)

    assert coordinator.status().state is ApplicationUpdateState.FAILED
    assert coordinator.status().can_cancel is False
    assert coordinator.status().can_retry is False
    assert not (root / "artifact.partial").exists()


def test_failed_worker_start_can_shutdown_without_join_before_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "synthetic-start-shutdown-cache"
    root.mkdir()
    coordinator = _coordinator(root)
    available = coordinator.check()

    monkeypatch.setattr(Thread, "start", lambda _thread: (_ for _ in ()).throw(RuntimeError("EXAMPLE_PRIVATE_START_FAILURE")))
    coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    coordinator.shutdown()

    assert coordinator.status().state is ApplicationUpdateState.FAILED
    assert coordinator.status().can_check is False
