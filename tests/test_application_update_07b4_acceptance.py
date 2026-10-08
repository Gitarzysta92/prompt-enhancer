from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.updates import (
    ApplicationUpdateCoordinator,
    ApplicationUpdateState,
    PackageReviewState,
    UpdateChannel,
)
from prompt_enhancer.application.updates.ports import SignedUpdateManifestEnvelope
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from prompt_enhancer.infrastructure.updates.msix_preflight import MsixPackagePreflight
from prompt_enhancer.infrastructure.updates.replay import AtomicReplayLedger
from prompt_enhancer.infrastructure.updates.staged_package_review import StagedPackageReview
from prompt_enhancer.infrastructure.updates.staging import FileUpdateStagingStore
from prompt_enhancer.application.updates.package_preflight import MsixPackageExpectation
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER


_TOKEN = "synthetic-07b4-http-token-000000000000000000000"
_NOW = datetime(2040, 1, 2, tzinfo=UTC)
_PIN = "a" * 64


class _EmptyStore:
    def initialize(self) -> None:
        return None

    def task_repository(self):
        from prompt_enhancer.application.tasks import MemoryTaskRepository

        return MemoryTaskRepository()

    def analysis_run_repository(self):
        from prompt_enhancer.application.analysis import MemoryAnalysisRunRepository

        return MemoryAnalysisRunRepository()

    def list_metric_definitions(self) -> list[object]:
        return []

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[object]:
        del limit, offset
        return []

    def get_session_metrics(self, session_id: str) -> list[object]:
        del session_id
        return []


class _ManifestSource:
    def __init__(self, envelope: SignedUpdateManifestEnvelope) -> None:
        self._envelope = envelope

    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        assert channel is UpdateChannel.STABLE
        return self._envelope


class _ArtifactSource:
    def __init__(self, artifact: bytes) -> None:
        self._artifact = artifact

    def iter_artifact(self, **_kwargs: object):
        midpoint = len(self._artifact) // 2
        yield self._artifact[:midpoint]
        yield self._artifact[midpoint:]


class _FakeNativeSigner:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def verify(self, *, path: Path, descriptor: int) -> str:
        assert descriptor >= 0
        self.calls.append(path)
        return _PIN


def _package() -> bytes:
    manifest = (
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Identity Name="Synthetic.App" Publisher="CN=Synthetic Publisher" '
        'Version="2.3.4.0" ProcessorArchitecture="x64" />'
        '</Package>'
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("Assets/icon.bin", b"synthetic-icon")
    return output.getvalue()


def _signed_envelope(artifact: bytes, key: Ed25519PrivateKey) -> SignedUpdateManifestEnvelope:
    raw = json.dumps(
        {
            "schema_version": 1,
            "release_version": "2.3.4",
            "minimum_supported_version": "1.0.0",
            "channel": "stable",
            "published_at": (_NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (_NOW + timedelta(days=1)).isoformat(),
            "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "artifact_size_bytes": len(artifact),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SignedUpdateManifestEnvelope(
        raw_manifest=raw,
        signature=key.sign(raw),
        key_id="synthetic-release",
    )


def _coordinator(
    root: Path,
    *,
    artifact: bytes,
    envelope: SignedUpdateManifestEnvelope,
    public_key: bytes,
    native_signer: _FakeNativeSigner,
) -> ApplicationUpdateCoordinator:
    store = FileUpdateStagingStore(root=root)
    return ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=_ManifestSource(envelope),
        verifier=Ed25519ManifestVerifier(
            public_keys={"synthetic-release": public_key}),
        artifact_source=_ArtifactSource(artifact),
        staging_store=store,
        replay_ledger=AtomicReplayLedger(root=root),
        package_verifier=StagedPackageReview(
            staging_store=store,
            preflight=MsixPackagePreflight(signer=native_signer),
            expectation=MsixPackageExpectation(
                name="Synthetic.App",
                publisher="CN=Synthetic Publisher",
                architecture="x64",
                signer_sha256=_PIN,
            ),
        ),
        clock=lambda: _NOW,
    )


def _fence(status: dict[str, object]) -> dict[str, object]:
    return {
        "expected_revision": status["revision"],
        "expected_instance_id": status["instance_id"],
    }


def _status(client: TestClient) -> dict[str, object]:
    response = client.get("/v1/application-updates/status", headers={API_TOKEN_HEADER: _TOKEN})
    assert response.status_code == 200
    return response.json()


def _wait_status(client: TestClient, state: str, *, review: str | None = None) -> dict[str, object]:
    deadline = time.monotonic() + 2
    while True:
        status = _status(client)
        package_review = status["package_review"]
        if status["state"] == state and (review is None or package_review["state"] == review):
            return status
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _browser_headers(client: TestClient) -> dict[str, str]:
    bootstrap = client.get("/auth/session")
    assert bootstrap.status_code == 200
    return {CSRF_HEADER: bootstrap.json()["csrf_token"], "Origin": "http://127.0.0.1"}


def _stage(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    available = _status(client)
    checked = client.post("/v1/application-updates/check", json=_fence(available), headers=headers)
    assert checked.status_code == 200
    available = checked.json()
    assert available["state"] == "available"
    staged = client.post("/v1/application-updates/stage", json=_fence(available), headers=headers)
    assert staged.status_code == 200
    return _wait_status(client, "staged", review="not_checked")


def test_c07b4_http_stages_and_reviews_then_restores_without_persisting_success(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    artifact = _package()
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    envelope = _signed_envelope(artifact, key)
    native = _FakeNativeSigner()
    service = _coordinator(root, artifact=artifact, envelope=envelope,
                           public_key=public_key, native_signer=native)
    app = create_app(
        settings=AppSettings(home=tmp_path / "synthetic-http-state"),
        database=_EmptyStore(),
        api_token=_TOKEN,
        application_update_service=service,
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = _browser_headers(client)
        assert _status(client)["state"] == "ready_to_check"
        assert _status(client)["state"] == "ready_to_check"
        assert native.calls == []
        staged = _stage(client, headers)
        assert native.calls == []
        reviewing = client.post("/v1/application-updates/verify", json=_fence(staged), headers=headers)
        assert reviewing.status_code == 200
        reviewed = _wait_status(client, "staged", review="verified")
        assert reviewed["can_apply"] is False
        assert native.calls == [root / "artifact.staged"]
        assert client.post("/v1/application-updates/apply", json=_fence(reviewed), headers=headers).status_code == 404

    service.shutdown()
    restored_native = _FakeNativeSigner()
    restored = _coordinator(root, artifact=artifact, envelope=envelope,
                            public_key=public_key, native_signer=restored_native)
    restored_status = restored.status()
    assert restored_status.state is ApplicationUpdateState.STAGED
    assert restored_status.can_verify is True
    assert restored_status.package_review.state is PackageReviewState.NOT_CHECKED
    assert restored_native.calls == []
    verify = restored.verify(expected_revision=restored_status.revision,
                             expected_instance_id=restored_status.instance_id)
    assert verify.state is ApplicationUpdateState.VERIFYING
    assert restored._worker is not None
    restored._worker.join(timeout=2)
    assert not restored._worker.is_alive()
    assert restored.status().package_review.state is PackageReviewState.VERIFIED
    restored.shutdown()


def test_c07b4_http_refuses_tampered_staged_file_without_apply(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-private-stage"
    root.mkdir()
    artifact = _package()
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    envelope = _signed_envelope(artifact, key)
    native = _FakeNativeSigner()
    service = _coordinator(root, artifact=artifact, envelope=envelope,
                           public_key=public_key, native_signer=native)
    app = create_app(
        settings=AppSettings(home=tmp_path / "synthetic-http-state"),
        database=_EmptyStore(),
        api_token=_TOKEN,
        application_update_service=service,
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        staged = _stage(client, _browser_headers(client))
        staged_path = root / "artifact.staged"
        staged_path.write_bytes(staged_path.read_bytes() + b"synthetic-tamper")
        result = client.post("/v1/application-updates/verify", json=_fence(staged), headers=_browser_headers(client))
        assert result.status_code == 200
        rejected = _wait_status(client, "staged", review="rejected")
        assert rejected["can_apply"] is False
        assert native.calls == []
        assert staged_path.read_bytes().endswith(b"synthetic-tamper")

    service.shutdown()
