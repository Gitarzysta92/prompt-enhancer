"""Closed-schema review lifecycle contracts; all evidence is synthetic."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import timedelta
import hashlib
import json
import time

import pytest

from prompt_enhancer.application.updates.contracts import (
    ApplicationUpdateState,
    ApplicationUpdateStatus,
    PackageReview,
    PackageReviewState,
    UpdateChannel,
)
from prompt_enhancer.application.updates.status import ApplicationUpdateCoordinator, UpdateActionConflict
from prompt_enhancer.application.updates.ports import SignedUpdateManifestEnvelope
from prompt_enhancer.application.updates.package_preflight import MsixPreflightResult, MsixPreflightState
from prompt_enhancer.infrastructure.updates.ed25519_verifier import Ed25519ManifestVerifier
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _status(*, state: ApplicationUpdateState, review: PackageReview,
            can_verify: bool = False) -> ApplicationUpdateStatus:
    staged = state in {ApplicationUpdateState.STAGED, ApplicationUpdateState.VERIFYING}
    return ApplicationUpdateStatus(
        installed_version="1.0.0", channel=UpdateChannel.STABLE, state=state,
        instance_id="a" * 32, revision=1,
        available_version="2.0.0" if staged else None,
        artifact_size_bytes=7 if staged else None,
        downloaded_bytes=7 if staged else None,
        last_checked_at=datetime(2040, 1, 1, tzinfo=UTC) if staged else None,
        can_check=state is ApplicationUpdateState.STAGED, can_stage=False, can_cancel=False, can_retry=False,
        can_apply=False, can_verify=can_verify, package_review=review,
    )


def test_review_schema_allows_only_explicit_staged_review_states() -> None:
    verified = PackageReview(state=PackageReviewState.VERIFIED,
                             checked_at=datetime(2040, 1, 1, tzinfo=UTC))
    assert _status(state=ApplicationUpdateState.STAGED, review=verified,
                   can_verify=True).can_apply is False
    with pytest.raises(ValueError):
        _status(state=ApplicationUpdateState.READY_TO_CHECK, review=verified)
    with pytest.raises(ValueError):
        _status(state=ApplicationUpdateState.STAGED,
                review=PackageReview(state=PackageReviewState.NOT_CHECKED))


def test_verifying_locks_every_action_and_requires_exact_staged_metadata() -> None:
    checking = PackageReview(state=PackageReviewState.CHECKING)
    status = _status(state=ApplicationUpdateState.VERIFYING, review=checking)
    assert not any((status.can_check, status.can_stage, status.can_cancel,
                    status.can_retry, status.can_verify, status.can_apply))
    with pytest.raises(ValueError):
        ApplicationUpdateStatus.model_validate(status.model_dump() | {"can_check": True})


def test_rejected_review_requires_closed_reason_and_timestamp() -> None:
    with pytest.raises(ValueError):
        PackageReview(state=PackageReviewState.REJECTED,
                      checked_at=datetime(2040, 1, 1, tzinfo=UTC))
    rejected = PackageReview(state=PackageReviewState.REJECTED,
                             reason_code="signature_unverifiable",
                             checked_at=datetime(2040, 1, 1, tzinfo=UTC))
    assert _status(state=ApplicationUpdateState.STAGED, review=rejected,
                   can_verify=True).package_review.reason_code == "signature_unverifiable"


class _Source:
    def __init__(self, envelope): self.envelope = envelope
    def fetch_manifest(self, **_): return self.envelope
class _Artifacts:
    def iter_artifact(self, **_): yield b"synthetic"
class _Stage:
    def stage(self, **kwargs):
        for _ in kwargs["chunks"]: pass
class _Review:
    def __init__(self, result=None, error=None, hook=None): self.result, self.error, self.hook, self.calls = result, error, hook, 0
    def verify(self, **_):
        self.calls += 1
        if self.hook: self.hook()
        if self.error: raise self.error
        return self.result

def _ready(review: _Review, *, expires: datetime | None = None, clock=None, replay_ledger=None):
    key, now = Ed25519PrivateKey.generate(), datetime(2040, 1, 1, tzinfo=UTC)
    payload = {"schema_version": 1, "release_version": "2.0.0", "minimum_supported_version": "1.0.0", "channel": "stable", "published_at": now.isoformat(), "expires_at": (expires or now + timedelta(days=1)).isoformat(), "artifact_sha256": hashlib.sha256(b"synthetic").hexdigest(), "artifact_size_bytes": 9}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    c = ApplicationUpdateCoordinator(installed_version="1.0.0", channel=UpdateChannel.STABLE, source=_Source(SignedUpdateManifestEnvelope(raw_manifest=raw, signature=key.sign(raw), key_id="synthetic")), verifier=Ed25519ManifestVerifier(public_keys={"synthetic": public}), artifact_source=_Artifacts(), staging_store=_Stage(), package_verifier=review, replay_ledger=replay_ledger, clock=clock or (lambda: now))
    s=c.status(); s=c.check(expected_revision=s.revision, expected_instance_id=s.instance_id); s=c.stage(expected_revision=s.revision, expected_instance_id=s.instance_id)
    deadline = time.monotonic() + 2
    while c.status().state is ApplicationUpdateState.STAGING:
        assert time.monotonic() < deadline
        time.sleep(.01)
    return c

def _review_done(coordinator):
    deadline = time.monotonic() + 2
    while coordinator.status().state is ApplicationUpdateState.VERIFYING:
        assert time.monotonic() < deadline
        time.sleep(.01)

def test_coordinator_verify_publishes_only_validated_result() -> None:
    review = _Review(MsixPreflightResult(state=MsixPreflightState.VERIFIED))
    coordinator = _ready(review)
    before = coordinator.status()
    checking = coordinator.verify(expected_revision=before.revision, expected_instance_id=before.instance_id)
    assert checking.state is ApplicationUpdateState.VERIFYING
    with pytest.raises(UpdateActionConflict): coordinator.verify(expected_revision=before.revision, expected_instance_id=before.instance_id)
    _review_done(coordinator)
    assert coordinator.status().package_review.state is PackageReviewState.VERIFIED
    assert review.calls == 1

def test_coordinator_verify_exception_never_publishes_success() -> None:
    coordinator = _ready(_Review(error=RuntimeError("synthetic")))
    s=coordinator.status(); coordinator.verify(expected_revision=s.revision, expected_instance_id=s.instance_id)
    _review_done(coordinator)
    assert coordinator.status().package_review.state is PackageReviewState.REJECTED


def test_forged_model_construct_result_never_publishes_success() -> None:
    forged = MsixPreflightResult.model_construct(state="verified", can_install=True)
    coordinator = _ready(_Review(forged))
    s = coordinator.status(); coordinator.verify(expected_revision=s.revision, expected_instance_id=s.instance_id)
    _review_done(coordinator)
    assert coordinator.status().package_review.state is PackageReviewState.REJECTED


def test_replay_floor_change_during_native_review_rejects_success() -> None:
    class _Ledger:
        def __init__(self): self.current = None
        def load(self): return self.current
        def persist_authenticated(self, *, expected_envelope, envelope):
            if expected_envelope is not self.current: raise RuntimeError("synthetic CAS")
            self.current = envelope
    ledger = _Ledger()
    review = _Review(MsixPreflightResult(state=MsixPreflightState.VERIFIED),
                     hook=lambda: setattr(ledger, "current", object()))
    coordinator = _ready(review, replay_ledger=ledger)
    s = coordinator.status(); coordinator.verify(expected_revision=s.revision, expected_instance_id=s.instance_id)
    _review_done(coordinator)
    assert review.calls == 1
    assert coordinator.status().package_review.state is PackageReviewState.REJECTED
    assert not isinstance(ledger.current, SignedUpdateManifestEnvelope)


def test_expired_before_verify_never_calls_native_boundary() -> None:
    review = _Review(MsixPreflightResult(state=MsixPreflightState.VERIFIED))
    now = [datetime(2040, 1, 1, tzinfo=UTC)]
    coordinator = _ready(review, expires=now[0] + timedelta(days=1), clock=lambda: now[0])
    now[0] += timedelta(days=2)
    s = coordinator.status(); coordinator.verify(expected_revision=s.revision, expected_instance_id=s.instance_id)
    _review_done(coordinator)
    assert coordinator.status().package_review.reason_code == "expired"
    assert review.calls == 0


def test_expiry_during_native_review_rejects_verified_result() -> None:
    now = [datetime(2040, 1, 1, tzinfo=UTC)]
    review = _Review(MsixPreflightResult(state=MsixPreflightState.VERIFIED),
                     hook=lambda: now.__setitem__(0, now[0] + timedelta(days=2)))
    coordinator = _ready(review, expires=now[0] + timedelta(days=1), clock=lambda: now[0])
    s = coordinator.status(); coordinator.verify(expected_revision=s.revision, expected_instance_id=s.instance_id)
    _review_done(coordinator)
    assert coordinator.status().package_review.state is PackageReviewState.REJECTED
    assert coordinator.status().package_review.reason_code == "expired"
    assert coordinator.status().package_review.checked_at == now[0]
