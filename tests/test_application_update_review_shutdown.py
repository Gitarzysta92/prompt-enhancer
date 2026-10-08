from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from threading import Event, Thread

import pytest

from prompt_enhancer.application.updates import (
    ApplicationUpdateCoordinator,
    ApplicationUpdateReason,
    ApplicationUpdateState,
    PackageReviewState,
    UpdateChannel,
)
from prompt_enhancer.application.updates.package_preflight import (
    MsixPreflightResult,
    MsixPreflightState,
)
from prompt_enhancer.application.updates.ports import (
    SignatureState,
    SignedUpdateManifestEnvelope,
)
from prompt_enhancer.application.updates.status import UpdateActionConflict
import prompt_enhancer.application.updates.status as status_module


NOW = datetime(2040, 1, 2, tzinfo=UTC)


def _envelope() -> SignedUpdateManifestEnvelope:
    raw = json.dumps(
        {
            "schema_version": 1,
            "release_version": "2.3.4",
            "minimum_supported_version": "1.0.0",
            "channel": "stable",
            "published_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
            "artifact_sha256": hashlib.sha256(b"synthetic-package").hexdigest(),
            "artifact_size_bytes": len(b"synthetic-package"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SignedUpdateManifestEnvelope(
        raw_manifest=raw,
        signature=b"s" * 64,
        key_id="synthetic-release",
    )


class _Source:
    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        del channel
        return _envelope()


class _Verifier:
    def verify(self, *, payload: bytes, signature: bytes, key_id: str) -> SignatureState:
        del payload, signature, key_id
        return SignatureState.VALID


class _RecoveredStage:
    def recover_envelope(self) -> SignedUpdateManifestEnvelope:
        return _envelope()


class _BlockingPackageVerifier:
    def __init__(self) -> None:
        self.entered, self.release = Event(), Event()

    def verify(self, **_: object) -> MsixPreflightResult:
        self.entered.set()
        assert self.release.wait(timeout=2)
        return MsixPreflightResult(state=MsixPreflightState.VERIFIED)


def _coordinator(package_verifier: _BlockingPackageVerifier) -> ApplicationUpdateCoordinator:
    return ApplicationUpdateCoordinator(
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
        source=_Source(),
        verifier=_Verifier(),
        staging_store=_RecoveredStage(),
        package_verifier=package_verifier,
        clock=lambda: NOW,
    )


def _verify(coordinator: ApplicationUpdateCoordinator):
    snapshot = coordinator.status()
    return coordinator.verify(
        expected_revision=snapshot.revision,
        expected_instance_id=snapshot.instance_id,
    )


def test_review_worker_start_failure_is_quarantined(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    del tmp_path

    class _StartFails:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def start(self) -> None:
            raise RuntimeError("synthetic start failure")

    coordinator = _coordinator(_BlockingPackageVerifier())
    monkeypatch.setattr(status_module, "Thread", _StartFails)

    result = _verify(coordinator)

    assert result.state is ApplicationUpdateState.FAILED
    assert result.reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
    assert result.package_review.state is PackageReviewState.NOT_STAGED


def test_duplicate_pending_review_is_refused(tmp_path) -> None:
    del tmp_path
    package_verifier = _BlockingPackageVerifier()
    coordinator = _coordinator(package_verifier)

    snapshot = _verify(coordinator)
    assert snapshot.state is ApplicationUpdateState.VERIFYING
    assert package_verifier.entered.wait(timeout=1)
    with pytest.raises(UpdateActionConflict):
        coordinator.verify(
            expected_revision=snapshot.revision,
            expected_instance_id=snapshot.instance_id,
        )

    package_verifier.release.set()
    assert coordinator._worker is not None
    coordinator._worker.join(timeout=1)
    assert coordinator.status().package_review.state is PackageReviewState.VERIFIED


def test_shutdown_joins_review_worker_and_refuses_late_verified_result(tmp_path) -> None:
    del tmp_path
    package_verifier = _BlockingPackageVerifier()
    coordinator = _coordinator(package_verifier)
    assert _verify(coordinator).state is ApplicationUpdateState.VERIFYING
    assert package_verifier.entered.wait(timeout=1)
    errors: list[BaseException] = []

    def shutdown() -> None:
        try:
            coordinator.shutdown()
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    shutdown_thread = Thread(target=shutdown)
    shutdown_thread.start()
    for _ in range(20):
        if coordinator._closed:
            break
        shutdown_thread.join(timeout=0.01)
    assert coordinator._closed
    package_verifier.release.set()
    shutdown_thread.join(timeout=1)

    assert errors == []
    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.package_review.state is PackageReviewState.NOT_STAGED


def test_shutdown_invalidates_an_idle_verified_review(tmp_path) -> None:
    del tmp_path
    package_verifier = _BlockingPackageVerifier()
    coordinator = _coordinator(package_verifier)
    _verify(coordinator)
    assert package_verifier.entered.wait(timeout=1)
    package_verifier.release.set()
    assert coordinator._worker is not None
    coordinator._worker.join(timeout=1)
    assert coordinator.status().package_review.state is PackageReviewState.VERIFIED

    coordinator.shutdown()

    status = coordinator.status()
    assert status.state is ApplicationUpdateState.FAILED
    assert status.package_review.state is PackageReviewState.NOT_STAGED
