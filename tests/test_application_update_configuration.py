from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from prompt_enhancer.application.resources import ResourceKind
from prompt_enhancer.application.updates import ApplicationUpdateState
from prompt_enhancer.application.paths import (
    HardeningReport,
    HardeningState,
    PathRejection,
)
from prompt_enhancer.infrastructure.resources import (
    PACKAGED_RESOURCE_LAYOUT,
    StagedResourceResolver,
)
from prompt_enhancer.application.updates import (
    ApplicationUpdateReason,
    UpdateActionConflict,
)
from prompt_enhancer.application.updates.ports import ArtifactStagingError
from prompt_enhancer.infrastructure.updates import (
    MAX_UPDATE_TRUST_BYTES,
    compose_packaged_application_update_surface,
)
from prompt_enhancer.infrastructure.updates.staging import FileUpdateStagingStore
from prompt_enhancer.infrastructure.updates.staged_package_review import StagedPackageReview
import prompt_enhancer.infrastructure.updates.configuration as configuration_module


URL = "https://updates.example.invalid/prompt-enhancer/stable/manifest-v1.json"
MEDIA_TYPE = "application/vnd.prompt-enhancer.update-manifest.v1+json"


def _trust_file(root: Path, payload: bytes) -> None:
    target = root.joinpath(
        *PACKAGED_RESOURCE_LAYOUT[ResourceKind.APPLICATION_UPDATE_TRUST].relative_parts
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _config(public_key: bytes) -> dict[str, object]:
    return {
        "schema_version": 2,
        "manifest_urls": {"stable": URL},
        "artifact_url_templates": {"stable": "https://updates.example.invalid/prompt-enhancer/{version}/{sha256}.bin"},
        "trusted_keys": [
            {
                "key_id": "release-2040",
                "ed25519_public_key_base64": base64.b64encode(public_key).decode(),
            }
        ],
    }


def _v3_config(public_key: bytes) -> dict[str, object]:
    config = _config(public_key)
    config["schema_version"] = 3
    config["package_identity"] = {
        "name": "Synthetic.App",
        "publisher": "CN=Synthetic Publisher",
        "architecture": "x64",
        "signer_sha256": "a" * 64,
    }
    return config


def _manifest(now: datetime) -> bytes:
    return json.dumps(
        {
            "artifact_sha256": "a" * 64,
            "artifact_size_bytes": 4_096,
            "channel": "stable",
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "minimum_supported_version": "0.1.0",
            "published_at": (now - timedelta(minutes=1)).isoformat(),
            "release_version": "0.2.0",
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class _HardenedPath:
    def inspect(self, _path: Path) -> HardeningReport:
        return HardeningReport(state=HardeningState.HARDENED)

    def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
        return HardeningReport(state=HardeningState.HARDENED)


class _UnverifiedPath:
    def inspect(self, _path: Path) -> HardeningReport:
        return HardeningReport(
            state=HardeningState.UNVERIFIED,
            reason=PathRejection.PERMISSIONS_UNVERIFIED,
        )


class _InspectOnlyHardenedPath:
    def inspect(self, _path: Path) -> HardeningReport:
        return HardeningReport(state=HardeningState.HARDENED)


def test_packaged_trust_composes_without_network_until_explicit_check(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())
    now = datetime.now(UTC)
    raw_manifest = _manifest(now)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Content-Type": MEDIA_TYPE,
                "X-Prompt-Enhancer-Key-Id": "release-2040",
                "X-Prompt-Enhancer-Manifest-Signature": base64.b64encode(
                    key.sign(raw_manifest)
                ).decode(),
            },
            content=raw_manifest,
        )

    stage_root = tmp_path / "synthetic-update-stage"
    stage_root.mkdir()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=_HardenedPath(),
        transport=httpx.MockTransport(handler),
    )

    assert surface.status().state is ApplicationUpdateState.READY_TO_CHECK
    assert requests == []
    snapshot = surface.status()
    checked = surface.check(expected_revision=snapshot.revision, expected_instance_id=snapshot.instance_id)
    assert checked.state is ApplicationUpdateState.AVAILABLE
    assert checked.available_version == "0.2.0"
    assert len(requests) == 1


def test_schema_v1_manifest_only_trust_never_exposes_staging(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trust = {
        "schema_version": 1,
        "manifest_urls": {"stable": URL},
        "trusted_keys": [{
            "key_id": "release-2040",
            "ed25519_public_key_base64": base64.b64encode(public_key).decode(),
        }],
    }
    _trust_file(tmp_path, json.dumps(trust).encode())
    raw_manifest = _manifest(datetime.now(UTC))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Content-Type": MEDIA_TYPE,
                "X-Prompt-Enhancer-Key-Id": "release-2040",
                "X-Prompt-Enhancer-Manifest-Signature": base64.b64encode(
                    key.sign(raw_manifest)
                ).decode(),
            },
            content=raw_manifest,
        )

    stage_root = tmp_path / "synthetic-v1-stage"
    stage_root.mkdir()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=_HardenedPath(),
        transport=httpx.MockTransport(handler),
    )

    ready = surface.status()
    assert ready.state is ApplicationUpdateState.READY_TO_CHECK
    assert ready.can_stage is False
    assert requests == []
    available = surface.check(
        expected_revision=ready.revision,
        expected_instance_id=ready.instance_id,
    )
    assert available.state is ApplicationUpdateState.AVAILABLE
    assert available.can_stage is False
    assert len(requests) == 1
    with pytest.raises(UpdateActionConflict):
        surface.stage(
            expected_revision=available.revision,
            expected_instance_id=available.instance_id,
        )
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("hardener", "expected_state"),
    [
        (None, ApplicationUpdateState.READY_TO_CHECK),
        (_UnverifiedPath(), ApplicationUpdateState.UNCONFIGURED),
    ],
)
def test_schema_v2_without_verified_private_root_has_no_download_capability(
    tmp_path: Path,
    hardener: _UnverifiedPath | None,
    expected_state: ApplicationUpdateState,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())
    raw_manifest = _manifest(datetime.now(UTC))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Content-Type": MEDIA_TYPE,
                "X-Prompt-Enhancer-Key-Id": "release-2040",
                "X-Prompt-Enhancer-Manifest-Signature": base64.b64encode(
                    key.sign(raw_manifest)
                ).decode(),
            },
            content=raw_manifest,
        )

    stage_root = tmp_path / "synthetic-v2-stage"
    stage_root.mkdir()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=hardener,
        transport=httpx.MockTransport(handler),
    )

    ready = surface.status()
    assert ready.state is expected_state
    if expected_state is ApplicationUpdateState.UNCONFIGURED:
        assert ready.can_check is False
        return
    available = surface.check(
        expected_revision=ready.revision,
        expected_instance_id=ready.instance_id,
    )
    assert available.state is ApplicationUpdateState.AVAILABLE
    assert available.can_stage is False
    assert len(requests) == 1


def test_schema_v2_has_no_package_review_capability(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())
    stage_root = tmp_path / "synthetic-v2-stage"
    stage_root.mkdir()

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=_HardenedPath(),
    )

    assert getattr(surface, "_package_verifier", None) is None
    assert surface.status().can_verify is False


def test_schema_v3_composes_private_staged_review_only_after_valid_policy(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_v3_config(public_key)).encode())
    stage_root = tmp_path / "synthetic-v3-stage"
    stage_root.mkdir()

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=_HardenedPath(),
    )

    assert isinstance(getattr(surface, "_package_verifier", None), StagedPackageReview)
    assert surface.status().can_apply is False
    assert list(stage_root.iterdir()) == []


def test_schema_v3_without_private_staging_root_has_no_package_review(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_v3_config(public_key)).encode())

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
    )

    assert getattr(surface, "_package_verifier", None) is None
    assert surface.status().can_verify is False
    assert surface.status().can_apply is False


@pytest.mark.parametrize(
    "payload",
    [
        lambda key: {key: value for key, value in _v3_config(key).items()
                     if key != "package_identity"},
        lambda key: {
            **_v3_config(key),
            "package_identity": {
                **_v3_config(key)["package_identity"],
                "architecture": "synthetic-invalid",
            },
        },
    ],
)
def test_malformed_v3_policy_never_prepares_private_root(
    tmp_path: Path,
    payload: object,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(payload(public_key)).encode())  # type: ignore[operator]

    class _RecordingPreparer:
        def __init__(self) -> None:
            self.calls = 0

        def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
            self.calls += 1
            return HardeningReport(state=HardeningState.HARDENED)

    preparer = _RecordingPreparer()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=tmp_path / "synthetic-v3-stage",
        private_update_staging_root_preparer=preparer,
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert preparer.calls == 0


def test_duplicate_v3_package_policy_never_prepares_private_root(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    valid = json.dumps(_v3_config(public_key))[:-1]
    duplicate = valid + ',"package_identity":{"name":"Synthetic.App"}}'
    _trust_file(tmp_path, duplicate.encode())

    class _RecordingPreparer:
        def __init__(self) -> None:
            self.calls = 0

        def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
            self.calls += 1
            return HardeningReport(state=HardeningState.HARDENED)

    preparer = _RecordingPreparer()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=tmp_path / "synthetic-v3-stage",
        private_update_staging_root_preparer=preparer,
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert preparer.calls == 0


def test_invalid_artifact_template_does_not_prepare_private_root(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    invalid = _config(public_key)
    invalid["artifact_url_templates"] = {
        "stable": "https://{version}.example.invalid/{sha256}.bin"
    }
    _trust_file(tmp_path, json.dumps(invalid).encode())

    class _RecordingPreparer:
        def __init__(self) -> None:
            self.calls = 0

        def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
            self.calls += 1
            return HardeningReport(state=HardeningState.HARDENED)

    preparer = _RecordingPreparer()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=tmp_path / "application-updates",
        private_update_staging_root_preparer=preparer,
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert preparer.calls == 0


def test_explicit_unverified_preparation_disables_update_surface(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())

    class _UnverifiedPreparer:
        def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
            return HardeningReport(
                state=HardeningState.UNVERIFIED,
                reason=PathRejection.PERMISSIONS_UNVERIFIED,
            )

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=tmp_path / "application-updates",
        private_update_staging_root_preparer=_UnverifiedPreparer(),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED


def test_existing_hardened_root_keeps_hardener_only_compatibility(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())
    stage_root = tmp_path / "application-updates"
    stage_root.mkdir()

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=_InspectOnlyHardenedPath(),
    )

    assert surface.status().state is ApplicationUpdateState.READY_TO_CHECK


def test_schema_v1_mixed_in_artifact_config_is_rejected_without_transport(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    mixed = _config(public_key)
    mixed["schema_version"] = 1
    _trust_file(tmp_path, json.dumps(mixed).encode())
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        transport=httpx.MockTransport(handler),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert calls == 0


def test_staging_store_constructor_failure_preserves_signed_advisory_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())

    class _FailingStore:
        def __init__(self, *, root: Path) -> None:
            del root
            raise ArtifactStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
            )

    monkeypatch.setattr(configuration_module, "FileUpdateStagingStore", _FailingStore)
    stage_root = tmp_path / "synthetic-constructor-failure-stage"
    stage_root.mkdir()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_path_hardener=_HardenedPath(),
    )

    assert surface.status().state is ApplicationUpdateState.READY_TO_CHECK
    assert surface.status().can_check is True
    assert surface.status().can_stage is False


def test_trusted_v1_prepares_private_root_for_replay_without_stage_capability(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trust = {
        "schema_version": 1,
        "manifest_urls": {"stable": URL},
        "trusted_keys": [{
            "key_id": "release-2040",
            "ed25519_public_key_base64": base64.b64encode(public_key).decode(),
        }],
    }
    _trust_file(tmp_path, json.dumps(trust).encode())

    class _RecordingPreparer:
        def __init__(self) -> None:
            self.paths: list[Path] = []

        def prepare_private_update_staging_root(self, path: Path) -> HardeningReport:
            self.paths.append(path)
            return HardeningReport(state=HardeningState.HARDENED)

    stage_root = tmp_path / "application-updates"
    stage_root.mkdir()
    preparer = _RecordingPreparer()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_update_staging_root_preparer=preparer,
    )

    assert preparer.paths == [stage_root]
    assert surface.status().state is ApplicationUpdateState.READY_TO_CHECK
    assert surface.status().can_stage is False


def test_invalid_trust_never_prepares_a_private_root(tmp_path: Path) -> None:
    _trust_file(tmp_path, b"not signed update trust")

    class _RecordingPreparer:
        def __init__(self) -> None:
            self.calls = 0

        def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
            self.calls += 1
            return HardeningReport(state=HardeningState.HARDENED)

    preparer = _RecordingPreparer()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=tmp_path / "application-updates",
        private_update_staging_root_preparer=preparer,
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert preparer.calls == 0


def test_verified_root_replay_constructor_failure_disables_update_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())

    class _FailingReplayLedger:
        def __init__(self, *, root: Path) -> None:
            del root
            raise ArtifactStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
            )

    monkeypatch.setattr(configuration_module, "AtomicReplayLedger", _FailingReplayLedger)
    stage_root = tmp_path / "application-updates"
    stage_root.mkdir()
    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=stage_root,
        private_update_staging_root_preparer=_HardenedPath(),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert surface.status().can_check is False


def test_preparation_exception_disables_update_surface_without_transport(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _trust_file(tmp_path, json.dumps(_config(public_key)).encode())

    class _FailingPreparer:
        def prepare_private_update_staging_root(self, _path: Path) -> HardeningReport:
            raise ArtifactStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
            )

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        staging_root=tmp_path / "application-updates",
        private_update_staging_root_preparer=_FailingPreparer(),
        transport=httpx.MockTransport(handler),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert calls == 0


def test_deep_nested_small_ledger_returns_typed_quarantine(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-deep-ledger-stage"
    root.mkdir()
    (root / "artifact.staged").write_bytes(b"synthetic-artifact")
    depth = 2_000
    nested = (b'{"nested":' * depth) + b"null" + (b"}" * depth)
    assert len(nested) < 64 * 1024
    (root / "staged-update.ledger.json").write_bytes(nested)

    with pytest.raises(ArtifactStagingError) as error:
        FileUpdateStagingStore(root=root).recover_envelope()

    assert error.value.reason is not None
    assert error.value.reason.value == "artifact_verification_failed"


def test_missing_packaged_trust_is_network_silent_and_unconfigured(
    tmp_path: Path,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        transport=httpx.MockTransport(handler),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert surface.check().state is ApplicationUpdateState.UNCONFIGURED
    assert calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"schema_version":1,"schema_version":1}',
        json.dumps({"schema_version": True, "manifest_urls": {}, "trusted_keys": []}).encode(),
        json.dumps({
            "schema_version": 1,
            "manifest_urls": {"beta": "https://updates.example.invalid/beta.json"},
            "trusted_keys": [{"key_id": "release-2040", "ed25519_public_key_base64": "A" * 44}],
        }).encode(),
        json.dumps({
            "schema_version": 1,
            "manifest_urls": {"stable": "http://updates.example.invalid/manifest.json"},
            "trusted_keys": [{"key_id": "release-2040", "ed25519_public_key_base64": "A" * 44}],
        }).encode(),
        b"x" * (MAX_UPDATE_TRUST_BYTES + 1),
    ],
)
def test_invalid_packaged_trust_fails_closed_without_opening_transport(
    tmp_path: Path,
    payload: bytes,
) -> None:
    _trust_file(tmp_path, payload)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    surface = compose_packaged_application_update_surface(
        resolver=StagedResourceResolver(tmp_path),
        installed_version="0.1.0",
        transport=httpx.MockTransport(handler),
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert calls == 0


def test_resource_failure_is_content_free_and_disables_update_checks() -> None:
    class _FailingResolver:
        def resolve(self, kind: ResourceKind):
            raise OSError("EXAMPLE_PRIVATE_RESOURCE_CANARY")

    surface = compose_packaged_application_update_surface(
        resolver=_FailingResolver(),
        installed_version="0.1.0",
    )

    assert surface.status().state is ApplicationUpdateState.UNCONFIGURED
    assert "EXAMPLE_PRIVATE_RESOURCE_CANARY" not in surface.status().model_dump_json()
