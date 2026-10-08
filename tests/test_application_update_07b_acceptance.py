"""Synthetic composition boundaries for the C07b update foundation.

These tests intentionally stop at trust, private staging, and replay evidence.
They do not fetch a real release, install anything, or start an updater process.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from prompt_enhancer.application.paths import HardeningReport, HardeningState, PathRejection
from prompt_enhancer.application.resources import ResourceKind
from prompt_enhancer.application.updates import (
    ApplicationUpdateCoordinator,
    ApplicationUpdateReason,
    ApplicationUpdateState,
    UpdateChannel,
    UpdateRejection,
)
from prompt_enhancer.application.updates.ports import (
    SignedUpdateManifestEnvelope,
)
from prompt_enhancer.infrastructure.paths import LocalPrivatePathHardener
from prompt_enhancer.infrastructure.resources import (
    PACKAGED_RESOURCE_LAYOUT,
    StagedResourceResolver,
)
from prompt_enhancer.infrastructure.updates import (
    compose_packaged_application_update_surface,
)
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from prompt_enhancer.infrastructure.updates.replay import AtomicReplayLedger, ReplayLedgerError
from prompt_enhancer.infrastructure.updates.staging import FileUpdateStagingStore


NOW = datetime(2040, 1, 2, tzinfo=UTC)
ARTIFACT = b"synthetic-c07b-artifact"


class _Source:
    def __init__(self, envelope: SignedUpdateManifestEnvelope) -> None:
        self.envelope = envelope
        self.calls = 0

    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        assert channel is UpdateChannel.STABLE
        self.calls += 1
        return self.envelope


class _ArtifactSource:
    def __init__(self, artifact: bytes = ARTIFACT) -> None:
        self.artifact = artifact
        self.calls = 0

    def iter_artifact(self, **_kwargs: object):
        self.calls += 1
        yield self.artifact


def _signed(
    signer: Ed25519PrivateKey,
    *,
    version: str,
    artifact: bytes = ARTIFACT,
    expires_at: datetime = NOW + timedelta(days=10),
    published_at: datetime = NOW - timedelta(minutes=1),
) -> SignedUpdateManifestEnvelope:
    payload: dict[str, object] = {
        "schema_version": 1,
        "release_version": version,
        "minimum_supported_version": "1.0.0",
        "channel": "stable",
        "published_at": published_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "artifact_size_bytes": len(artifact),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return SignedUpdateManifestEnvelope(
        raw_manifest=raw,
        signature=signer.sign(raw),
        key_id="synthetic-release",
    )


def _verifier(signer: Ed25519PrivateKey) -> Ed25519ManifestVerifier:
    public = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return Ed25519ManifestVerifier(public_keys={"synthetic-release": public})


def _coordinator(
    root: Path,
    source: _Source,
    signer: Ed25519PrivateKey,
    *,
    ledger: AtomicReplayLedger | object | None = None,
    artifact: bytes = ARTIFACT,
    clock=lambda: NOW,
) -> tuple[ApplicationUpdateCoordinator, _ArtifactSource]:
    artifact_source = _ArtifactSource(artifact)
    return (
        ApplicationUpdateCoordinator(
            installed_version="1.0.0",
            channel=UpdateChannel.STABLE,
            source=source,
            verifier=_verifier(signer),
            artifact_source=artifact_source,
            staging_store=FileUpdateStagingStore(root=root),
            replay_ledger=ledger,  # type: ignore[arg-type]
            clock=clock,
        ),
        artifact_source,
    )


def _check(coordinator: ApplicationUpdateCoordinator):
    snapshot = coordinator.status()
    return coordinator.check(
        expected_revision=snapshot.revision,
        expected_instance_id=snapshot.instance_id,
    )


def _wait_terminal(coordinator: ApplicationUpdateCoordinator) -> None:
    deadline = time.monotonic() + 3
    while coordinator.status().state is ApplicationUpdateState.STAGING:
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _write_trust(root: Path, payload: bytes) -> None:
    target = root.joinpath(
        *PACKAGED_RESOURCE_LAYOUT[ResourceKind.APPLICATION_UPDATE_TRUST].relative_parts
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


class _RecordingPreparer:
    def __init__(self, report: HardeningReport | None = None) -> None:
        self.calls: list[Path] = []
        self.report = report or HardeningReport(
            state=HardeningState.UNVERIFIED,
            reason=PathRejection.PERMISSIONS_UNVERIFIED,
        )

    def prepare_private_update_staging_root(self, path: Path) -> HardeningReport:
        self.calls.append(path)
        return self.report


def _trust_payload(
    public_key: bytes,
    *,
    schema_version: int = 2,
    artifact_template: str = (
        "https://updates.example.invalid/prompt-enhancer/"
        "{version}/{sha256}.bin"
    ),
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "manifest_urls": {
            "stable": "https://updates.example.invalid/prompt-enhancer/stable/manifest.json"
        },
        "trusted_keys": [{
            "key_id": "synthetic-release",
            "ed25519_public_key_base64": base64.b64encode(public_key).decode(),
        }],
    }
    if schema_version == 2:
        payload["artifact_url_templates"] = {"stable": artifact_template}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_unconfigured_composition_does_not_touch_disk_or_transport(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    requests: list[httpx.Request] = []
    preparer = _RecordingPreparer()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("synthetic transport must not be contacted")

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="1.0.0",
        staging_root=tmp_path / "synthetic-missing-root",
        private_update_staging_root_preparer=preparer,
        transport=httpx.MockTransport(handler),
    )

    status = surface.status()
    assert status.state is ApplicationUpdateState.UNCONFIGURED
    assert status.can_apply is False
    assert requests == []
    assert preparer.calls == []
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    "state,reason",
    [
        (HardeningState.REJECTED, PathRejection.PERMISSIONS_UNVERIFIED),
        (HardeningState.UNVERIFIED, PathRejection.WINDOWS_DACL_UNAVAILABLE),
    ],
)
def test_valid_trust_with_refused_preparation_is_unconfigured(
    tmp_path: Path,
    state: HardeningState,
    reason: PathRejection,
) -> None:
    signer = Ed25519PrivateKey.generate()
    _write_trust(tmp_path, _trust_payload(
        signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ))
    stage_root = tmp_path / "synthetic-stage-root"
    stage_root.mkdir()
    marker = stage_root / "sentinel.txt"
    marker.write_bytes(b"synthetic-preserved")
    preparer = _RecordingPreparer(
        HardeningReport(state=state, reason=reason)
    )
    requests: list[httpx.Request] = []

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="1.0.0",
        staging_root=stage_root,
        private_update_staging_root_preparer=preparer,
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert surface.status().can_apply is False
    assert preparer.calls == [stage_root]
    assert requests == []
    assert marker.read_bytes() == b"synthetic-preserved"


def test_malformed_v2_artifact_template_fails_before_preparation_or_disk_mutation(
    tmp_path: Path,
) -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _write_trust(
        tmp_path,
        _trust_payload(
            public_key,
            artifact_template=(
                "https://updates.example.invalid/prompt-enhancer/"
                "{version}.bin"
            ),
        ),
    )
    stage_root = tmp_path / "synthetic-stage-root"
    stage_root.mkdir()
    marker = stage_root / "sentinel.txt"
    marker.write_bytes(b"synthetic-preserved")
    preparer = _RecordingPreparer(
        HardeningReport(
            state=HardeningState.HARDENED,
        )
    )
    requests: list[httpx.Request] = []

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="1.0.0",
        staging_root=stage_root,
        private_update_staging_root_preparer=preparer,
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert preparer.calls == []
    assert requests == []
    assert marker.read_bytes() == b"synthetic-preserved"


def test_manifest_only_composition_wires_durable_replay_across_restart(
    tmp_path: Path,
) -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _write_trust(tmp_path, _trust_payload(public_key, schema_version=1))
    stage_root = tmp_path / "synthetic-stage-root"
    stage_root.mkdir()
    preparer = _RecordingPreparer(
        HardeningReport(state=HardeningState.HARDENED)
    )
    composition_now = datetime.now(UTC)
    source = _Source(
        _signed(
            signer,
            version="3.0.0",
            published_at=composition_now - timedelta(minutes=1),
            expires_at=composition_now + timedelta(days=10),
        )
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        envelope = source.envelope
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/vnd.prompt-enhancer.update-manifest.v1+json",
                "X-Prompt-Enhancer-Key-Id": envelope.key_id,
                "X-Prompt-Enhancer-Manifest-Signature": base64.b64encode(
                    envelope.signature
                ).decode("ascii"),
            },
            content=envelope.raw_manifest,
        )

    transport = httpx.MockTransport(handler)
    first = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="1.0.0",
        staging_root=stage_root,
        private_update_staging_root_preparer=preparer,
        transport=transport,
    )
    ready = first.status()
    assert ready.state is ApplicationUpdateState.READY_TO_CHECK
    assert ready.can_stage is False
    assert first.check(
        expected_revision=ready.revision,
        expected_instance_id=ready.instance_id,
    ).state is ApplicationUpdateState.AVAILABLE

    source.envelope = _signed(
        signer,
        version="2.0.0",
        published_at=composition_now - timedelta(minutes=1),
        expires_at=composition_now + timedelta(days=10),
    )
    second = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="1.0.0",
        staging_root=stage_root,
        private_update_staging_root_preparer=preparer,
        transport=transport,
    )
    current = second.status()
    replayed = second.check(
        expected_revision=current.revision,
        expected_instance_id=current.instance_id,
    )

    assert replayed.state is ApplicationUpdateState.FAILED
    assert replayed.verification_code is UpdateRejection.REPLAYED_RELEASE
    assert replayed.can_stage is False
    assert replayed.can_apply is False
    assert len(requests) == 2
    assert preparer.calls == [stage_root, stage_root]


class _UnsafeWindowsDirectory:
    def inspect(self, _path: Path) -> PathRejection:
        return PathRejection.PERMISSIONS_UNVERIFIED

    def create_then_inspect(self, _path: Path) -> PathRejection:
        raise AssertionError("existing unsafe leaf must not be repaired")


def test_insecure_existing_windows_leaf_is_inspection_only(tmp_path: Path) -> None:
    parent = tmp_path / "synthetic-parent"
    leaf = parent / "application-updates"
    parent.mkdir()
    leaf.mkdir()
    marker = leaf / "sentinel.txt"
    marker.write_bytes(b"synthetic-preserved")
    before = marker.read_bytes()

    report = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=_UnsafeWindowsDirectory(),
    ).prepare_private_update_staging_root(leaf)

    assert report.state is HardeningState.REJECTED
    assert report.reason is PathRejection.PERMISSIONS_UNVERIFIED
    assert marker.read_bytes() == before
    assert sorted(path.name for path in leaf.iterdir()) == ["sentinel.txt"]


@pytest.mark.skipif(os.name != "nt", reason="requires the real Windows DACL adapter")
def test_new_windows_temp_leaf_has_exact_native_private_report(tmp_path: Path) -> None:
    parent = tmp_path / "synthetic-parent"
    parent.mkdir()
    leaf = parent / "application-updates"

    hardener = LocalPrivatePathHardener()
    report = hardener.prepare_private_update_staging_root(leaf)
    inspected = hardener.inspect(leaf)

    assert report.state is HardeningState.HARDENED
    assert inspected.state is HardeningState.HARDENED
    assert report.reason is None
    assert report.existing_components_checked >= 1
    # The public report is deliberately content-free: no SID, user, or path.
    assert repr(report).find(str(tmp_path)) == -1


def test_metadata_only_restart_rejects_older_signed_release_without_download(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cache"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    first = _signed(signer, version="3.0.0")
    source = _Source(first)
    ledger = AtomicReplayLedger(root=root)
    first_coordinator, _ = _coordinator(root, source, signer, ledger=ledger)
    assert _check(first_coordinator).state is ApplicationUpdateState.AVAILABLE

    source.envelope = _signed(signer, version="2.0.0")
    recovered, artifact_source = _coordinator(root, source, signer, ledger=ledger)
    status = _check(recovered)

    assert status.state is ApplicationUpdateState.FAILED
    assert status.verification_code is UpdateRejection.REPLAYED_RELEASE
    assert status.can_stage is False
    assert status.can_apply is False
    assert artifact_source.calls == 0


def test_same_version_changed_manifest_is_rejected_across_restart(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cache"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    source = _Source(_signed(signer, version="3.0.0", artifact=b"synthetic-a"))
    ledger = AtomicReplayLedger(root=root)
    coordinator, _ = _coordinator(root, source, signer, ledger=ledger)
    assert _check(coordinator).state is ApplicationUpdateState.AVAILABLE

    source.envelope = _signed(signer, version="3.0.0", artifact=b"synthetic-b")
    recovered, artifact_source = _coordinator(root, source, signer, ledger=ledger)
    status = _check(recovered)

    assert status.state is ApplicationUpdateState.FAILED
    assert status.verification_code is UpdateRejection.RELEASE_IDENTITY_CONFLICT
    assert status.can_stage is False
    assert artifact_source.calls == 0


def test_expired_authentic_floor_is_not_reset_by_a_later_older_release(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cache"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    source = _Source(
        _signed(signer, version="3.0.0", expires_at=NOW + timedelta(days=1))
    )
    ledger = AtomicReplayLedger(root=root)
    coordinator, _ = _coordinator(root, source, signer, ledger=ledger)
    assert _check(coordinator).state is ApplicationUpdateState.AVAILABLE

    source.envelope = _signed(
        signer,
        version="2.0.0",
        expires_at=NOW + timedelta(days=30),
    )
    recovered, _ = _coordinator(
        root,
        source,
        signer,
        ledger=ledger,
        clock=lambda: NOW + timedelta(days=2),
    )
    status = _check(recovered)

    assert status.state is ApplicationUpdateState.FAILED
    assert status.verification_code is UpdateRejection.REPLAYED_RELEASE


class _PersistFailureLedger:
    def load(self):
        return None

    def persist_authenticated(self, **_kwargs: object) -> None:
        raise ReplayLedgerError()


class _LoadFailureLedger:
    def load(self):
        raise ReplayLedgerError()

    def persist_authenticated(self, **_kwargs: object) -> None:
        raise AssertionError("quarantined coordinator must not persist")


def test_replay_persist_failure_removes_downloadable_capability(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cache"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    source = _Source(_signed(signer, version="2.0.0"))
    coordinator, artifact_source = _coordinator(
        root, source, signer, ledger=_PersistFailureLedger()
    )

    status = _check(coordinator)
    assert status.state is ApplicationUpdateState.FAILED
    assert status.reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert status.can_check is False
    assert status.can_stage is False
    assert status.can_retry is False
    assert status.can_apply is False
    assert artifact_source.calls == 0


def test_replay_ledger_quarantine_has_no_mutation_capabilities(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cache"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    source = _Source(_signed(signer, version="2.0.0"))
    coordinator, artifact_source = _coordinator(
        root, source, signer, ledger=_LoadFailureLedger()
    )

    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.can_check is False
    assert status.can_stage is False
    assert status.can_cancel is False
    assert status.can_retry is False
    assert status.can_apply is False
    assert artifact_source.calls == 0


def test_staged_old_then_metadata_new_restart_retains_high_water(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-cache"
    root.mkdir()
    signer = Ed25519PrivateKey.generate()
    source = _Source(_signed(signer, version="2.0.0", artifact=ARTIFACT))
    ledger = AtomicReplayLedger(root=root)
    coordinator, _ = _coordinator(root, source, signer, ledger=ledger)
    available = _check(coordinator)
    assert available.state is ApplicationUpdateState.AVAILABLE
    coordinator.stage(
        expected_revision=available.revision,
        expected_instance_id=available.instance_id,
    )
    _wait_terminal(coordinator)
    assert coordinator.status().state is ApplicationUpdateState.STAGED

    source.envelope = _signed(signer, version="3.0.0", artifact=b"synthetic-new")
    metadata_new, _ = _coordinator(root, source, signer, ledger=ledger)
    assert _check(metadata_new).state is ApplicationUpdateState.AVAILABLE

    source.envelope = _signed(signer, version="2.0.0", artifact=ARTIFACT)
    restarted, _ = _coordinator(root, source, signer, ledger=ledger)
    assert restarted.status().can_apply is False
    status = _check(restarted)
    assert status.state is ApplicationUpdateState.FAILED
    assert status.verification_code is UpdateRejection.REPLAYED_RELEASE
