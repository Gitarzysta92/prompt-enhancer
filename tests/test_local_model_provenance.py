"""Supply-chain provenance for first-party GGUF discovery and download.

Adversarial, offline and synthetic: every Hub call is stubbed, no network is
touched, no real repository or model is named, and no weights are fetched. The
rules under test are that a download only ever happens against an immutable
commit with an exact size, an expected sha256 and an admitted licence, that the
caller cannot substitute any of those, and that a failure registers nothing and
says nothing about the repository beyond a closed code.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.local_models import (
    ADMITTED_LICENSE_IDS,
    AddLocalModel,
    DownloadRequest,
    HardwareSummary,
    LICENSE_POLICY_VERSION,
    LicenseAdmission,
    LocalModelError,
    LocalModelRecord,
    LocalModelRegistry,
    LocalModelService,
    REFUSED_LICENSE_IDS,
    RemoteFile,
    RemoteRepoFiles,
    admit_license,
    resolve_repo_identity,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from tests.local_model_hub_stubs import (
    OTHER_REVISION,
    REPO_ID,
    REVISION,
    stub_model_info,
    wait_for_download,
)


T0 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
BODY = b"GGUF" + bytes(2044)
DIGEST = hashlib.sha256(BODY).hexdigest()
FILENAME = "example-q4_k_m.gguf"
FILES = {FILENAME: (2048, DIGEST)}


def _service(tmp_path: Path, *, model_info=None, downloader=None) -> LocalModelService:
    return LocalModelService(
        tmp_path / "local-models",
        llama_server=lambda: None,
        hardware=lambda _binary: HardwareSummary(),
        clock=lambda: T0,
        downloader=downloader if downloader is not None else _writing_downloader(BODY),
        model_info=model_info if model_info is not None else stub_model_info(files=FILES),
    )


def _writing_downloader(body: bytes, *, name: str | None = None):
    def download(*, repo_id: str, filename: str, local_dir: Path, revision: str) -> Path:
        assert revision == REVISION, "the download must be pinned to the immutable commit"
        path = Path(local_dir) / (name or filename)
        path.write_bytes(body)
        return path

    return download


def _request(**changes: object) -> DownloadRequest:
    payload: dict[str, object] = {
        "repo_id": REPO_ID,
        "filename": FILENAME,
        "confirmed_size_bytes": 2048,
        "confirmed_revision": REVISION,
        "confirmed_sha256": DIGEST,
        "confirmed_license": "apache-2.0",
        "alias": "example-q4",
    }
    payload.update(changes)
    return DownloadRequest(**payload)  # type: ignore[arg-type]


# ----- discovery -----


def test_discovery_binds_size_digest_and_licence_to_an_immutable_commit() -> None:
    seen: list[tuple[str, object]] = []

    inner = stub_model_info(files=FILES)

    def recording(repo_id: str, *, revision: str | None = None, files_metadata: bool = False):
        seen.append((repo_id, revision))
        return inner(repo_id, revision=revision, files_metadata=files_metadata)

    identity = resolve_repo_identity(REPO_ID, model_info=recording)
    # The first lookup only learns the commit; every value used comes from the second,
    # which is addressed to that commit oid rather than to a mutable branch.
    assert seen == [(REPO_ID, None), (REPO_ID, REVISION)]
    assert identity.revision == REVISION and identity.revision_pinned is True
    assert identity.license_id == "apache-2.0"
    assert identity.license_admission is LicenseAdmission.ALLOWED
    assert identity.license_policy_version == LICENSE_POLICY_VERSION
    assert [(f.filename, f.size_bytes, f.sha256, f.eligible) for f in identity.files] == [
        (FILENAME, 2048, DIGEST, True)
    ]


@pytest.mark.parametrize(
    ("head", "pinned", "reason"),
    [
        ("main", None, "revision_not_immutable"),
        (None, None, "revision_not_immutable"),
        ("latest", None, "revision_not_immutable"),
        ("0123", None, "revision_not_immutable"),
        (REVISION, OTHER_REVISION, "revision_contradicted"),
    ],
)
def test_a_repository_that_will_not_pin_gets_the_fixed_unavailable_state(head, pinned, reason) -> None:
    identity = resolve_repo_identity(
        REPO_ID,
        model_info=stub_model_info(files=FILES, head_revision=head, pinned_revision=pinned),
    )
    assert identity.revision is None and identity.revision_pinned is False
    assert identity.unavailable_reason == reason
    assert identity.files == ()
    assert identity.license_id is None
    assert identity.license_admission is LicenseAdmission.UNAVAILABLE


@pytest.mark.parametrize(
    ("size", "digest", "reason"),
    [
        (2048, None, "digest_unavailable"),
        (2048, "not-a-digest", "digest_unavailable"),
        (2048, "ab" * 20, "digest_unavailable"),
        (2048, DIGEST.upper(), None),  # a digest in capitals is the same digest
        (None, DIGEST, "size_unavailable"),
        ("2048", DIGEST, "size_unavailable"),
        (0, DIGEST, "size_unavailable"),
    ],
)
def test_a_file_without_an_exact_size_and_digest_is_never_eligible(size, digest, reason) -> None:
    identity = resolve_repo_identity(
        REPO_ID, model_info=stub_model_info(files={FILENAME: (size, digest)})
    )
    only = identity.files[0]
    assert only.ineligible_reason == reason
    assert only.eligible is (reason is None)


@pytest.mark.parametrize(
    ("license_id", "tags", "admission", "reason"),
    [
        ("apache-2.0", None, LicenseAdmission.ALLOWED, None),
        (None, None, LicenseAdmission.UNAVAILABLE, "license_unavailable"),
        ("other", None, LicenseAdmission.NOT_ALLOWED, "license_not_allowed"),
        ("cc-by-nc-4.0", None, LicenseAdmission.NOT_ALLOWED, "license_not_allowed"),
        ("example-community-1.0", None, LicenseAdmission.UNREVIEWED, "license_unreviewed"),
        ("apache-2.0", ["license:mit"], LicenseAdmission.UNAVAILABLE, "license_unavailable"),
        ("!!not an id!!", [], LicenseAdmission.UNAVAILABLE, "license_unavailable"),
    ],
)
def test_the_frozen_admission_policy_fails_closed_on_every_unclear_licence(
    license_id, tags, admission, reason
) -> None:
    identity = resolve_repo_identity(
        REPO_ID, model_info=stub_model_info(files=FILES, license_id=license_id, tags=tags)
    )
    assert identity.license_admission is admission
    assert identity.files[0].eligible is (reason is None)
    assert identity.files[0].ineligible_reason == reason


def test_the_admission_policy_is_frozen_and_disjoint() -> None:
    assert not (ADMITTED_LICENSE_IDS & REFUSED_LICENSE_IDS)
    assert admit_license(None) is LicenseAdmission.UNAVAILABLE
    assert admit_license("apache-2.0") is LicenseAdmission.ALLOWED
    assert admit_license("other") is LicenseAdmission.NOT_ALLOWED
    assert admit_license("example-new-license") is LicenseAdmission.UNREVIEWED


def test_a_file_outside_the_repository_root_is_listed_but_not_downloadable() -> None:
    identity = resolve_repo_identity(
        REPO_ID, model_info=stub_model_info(files={"nested/../escape.gguf": (2048, DIGEST)})
    )
    assert identity.files[0].eligible is False
    assert identity.files[0].ineligible_reason == "unsupported_file_path"


@pytest.mark.parametrize(
    "filename",
    [
        "nested/model.gguf",
        "..model.gguf",
        "model..q4.gguf",
        "model\nq4.gguf",
        "model q4.gguf",
        "CON.gguf",
        "LPT1.gguf",
        "éxample.gguf",
    ],
)
def test_nonportable_hub_file_names_are_never_downloadable(filename: str) -> None:
    identity = resolve_repo_identity(
        REPO_ID,
        model_info=stub_model_info(files={filename: (2048, DIGEST)}),
    )
    assert identity.files[0].eligible is False
    assert identity.files[0].ineligible_reason == "unsupported_file_path"


def test_gated_repository_metadata_never_enables_the_public_downloader(tmp_path: Path) -> None:
    model_info = stub_model_info(files=FILES, gated=True)
    identity = resolve_repo_identity(REPO_ID, model_info=model_info)
    assert identity.gated is True
    assert identity.files[0].eligible is False
    assert identity.files[0].ineligible_reason == "repository_gated"

    service = _service(tmp_path, model_info=model_info)
    with pytest.raises(LocalModelError) as caught:
        service.start_download(_request())
    assert caught.value.code == "file_not_eligible"
    assert service.registry.list() == ()


def test_provenance_dtos_reject_incoherent_verified_claims() -> None:
    with pytest.raises(ValidationError):
        LocalModelRecord(
            alias="forged",
            display_name="Forged",
            path="D:/example/forged.gguf",
            size_bytes=2048,
            provenance_verified=True,
            added_at=T0,
        )
    with pytest.raises(ValidationError):
        RemoteFile(filename=FILENAME, size_bytes=2048, sha256=DIGEST, eligible=True, ineligible_reason="blocked")
    with pytest.raises(ValidationError):
        RemoteRepoFiles(repo_id=REPO_ID, revision_pinned=True, revision=None)


def test_an_unreadable_repository_raises_a_closed_code() -> None:
    def exploding(*_args, **_kwargs):
        raise RuntimeError("connection to example-org failed: token 'example-secret'")

    with pytest.raises(LocalModelError) as caught:
        resolve_repo_identity(REPO_ID, model_info=exploding)
    assert caught.value.code == "remote_repo_unavailable"
    assert "example-secret" not in str(caught.value)


# ----- caller substitution -----


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"confirmed_revision": OTHER_REVISION}, "provenance_mismatch"),
        ({"confirmed_sha256": "f" * 64}, "provenance_mismatch"),
        ({"confirmed_license": "mit"}, "provenance_mismatch"),
        ({"confirmed_size_bytes": 4096}, "provenance_mismatch"),
        ({"filename": "example-q8_0.gguf"}, "file_not_eligible"),
        ({"repo_id": "example-org/Other-GGUF"}, "provenance_mismatch"),
    ],
)
def test_the_caller_cannot_substitute_any_part_of_the_identity(tmp_path: Path, changes, code) -> None:
    def refuse(**_kwargs):
        raise AssertionError("a substituted request reached the downloader")

    # A repository whose answer differs from the confirmation for the swapped field.
    other = stub_model_info(files=FILES) if "repo_id" not in changes else stub_model_info(
        files={FILENAME: (2048, DIGEST)}, head_revision=OTHER_REVISION, pinned_revision=OTHER_REVISION
    )
    service = _service(tmp_path, model_info=other, downloader=refuse)
    with pytest.raises(LocalModelError) as caught:
        service.start_download(_request(**changes))
    assert caught.value.code == code
    assert service.registry.list() == ()
    assert service.overview().downloads == ()


def test_a_repository_that_moved_since_the_person_looked_is_refused(tmp_path: Path) -> None:
    """The person confirmed one commit; discovery now resolves another."""

    def refuse(**_kwargs):
        raise AssertionError("a moved repository was downloaded anyway")

    service = _service(
        tmp_path,
        model_info=stub_model_info(files=FILES, head_revision=OTHER_REVISION, pinned_revision=OTHER_REVISION),
        downloader=refuse,
    )
    with pytest.raises(LocalModelError) as caught:
        service.start_download(_request())
    assert caught.value.code == "provenance_mismatch"
    assert service.registry.list() == ()


def test_an_unpinnable_repository_refuses_the_download(tmp_path: Path) -> None:
    service = _service(tmp_path, model_info=stub_model_info(files=FILES, head_revision="main"))
    with pytest.raises(LocalModelError) as caught:
        service.start_download(_request())
    assert caught.value.code == "provenance_unavailable"


@pytest.mark.parametrize("license_id", ["other", "example-community-1.0", None])
def test_a_licence_the_policy_does_not_admit_refuses_the_download(tmp_path: Path, license_id) -> None:
    service = _service(tmp_path, model_info=stub_model_info(files=FILES, license_id=license_id))
    with pytest.raises(LocalModelError) as caught:
        service.start_download(_request(confirmed_license=license_id or "apache-2.0"))
    assert caught.value.code == "file_not_eligible"
    assert service.registry.list() == ()


def test_the_download_identity_separates_two_revisions_and_two_digests(tmp_path: Path) -> None:
    first = _service(tmp_path / "a").start_download(_request())
    other_body = b"GGUF" + bytes(2044) + b"x"
    other_digest = hashlib.sha256(other_body).hexdigest()
    second = _service(
        tmp_path / "b",
        model_info=stub_model_info(
            files={FILENAME: (2049, other_digest)}, head_revision=OTHER_REVISION, pinned_revision=OTHER_REVISION
        ),
        downloader=_writing_downloader(other_body),
    ).start_download(
        _request(confirmed_revision=OTHER_REVISION, confirmed_sha256=other_digest, confirmed_size_bytes=2049)
    )
    assert first.download_id != second.download_id


def test_distinct_revisions_use_distinct_managed_directories(tmp_path: Path) -> None:
    directories: list[Path] = []

    def recording(body: bytes):
        def download(*, repo_id: str, filename: str, local_dir: Path, revision: str) -> Path:
            directories.append(Path(local_dir))
            path = Path(local_dir) / filename
            path.write_bytes(body)
            return path

        return download

    first = _service(tmp_path / "first", downloader=recording(BODY))
    assert wait_for_download(first, first.start_download(_request(alias="first")).download_id).state == "completed"

    other_body = b"GGUF" + bytes(2044) + b"x"
    other_digest = hashlib.sha256(other_body).hexdigest()
    second = _service(
        tmp_path / "second",
        model_info=stub_model_info(
            files={FILENAME: (len(other_body), other_digest)},
            head_revision=OTHER_REVISION,
            pinned_revision=OTHER_REVISION,
        ),
        downloader=recording(other_body),
    )
    request = _request(
        alias="second",
        confirmed_revision=OTHER_REVISION,
        confirmed_sha256=other_digest,
        confirmed_size_bytes=len(other_body),
    )
    assert wait_for_download(second, second.start_download(request).download_id).state == "completed"
    assert len(directories) == 2 and directories[0].name != directories[1].name
    assert all(directory.name.startswith("hf-") and len(directory.name) == 67 for directory in directories)


def test_default_hub_clients_are_public_only(tmp_path: Path, monkeypatch) -> None:
    import huggingface_hub

    seen: dict[str, object] = {}

    class PublicApi:
        def __init__(self, *, token=None, **_kwargs) -> None:
            seen["api_token"] = token

        def model_info(self, *_args, **_kwargs):  # pragma: no cover - identity lookup is separately tested
            raise AssertionError("not called")

    monkeypatch.setattr(huggingface_hub, "HfApi", PublicApi)
    service = LocalModelService(tmp_path / "public", llama_server=lambda: None)
    service._hub_model_info()  # noqa: SLF001 - verify the production composition boundary
    assert seen["api_token"] is False

    def public_url(repo_id, filename, *, repo_type, revision):
        assert repo_id == REPO_ID and filename == FILENAME
        assert repo_type == "model" and revision == REVISION
        return "https://example.invalid/synthetic-artifact"

    class Metadata:
        commit_hash = REVISION
        size = len(BODY)
        location = "https://example.invalid/synthetic-bytes"

    def public_metadata(_url, *, token):
        seen["metadata_token"] = token
        return Metadata()

    def public_headers(*, token):
        seen["header_token"] = token
        return {"User-Agent": "synthetic-test"}

    def public_download(_url, target, *, resume_size, headers, expected_size, _tqdm_bar, **_kwargs):
        assert resume_size == 0 and expected_size == len(BODY)
        assert headers == {"User-Agent": "synthetic-test"}
        _tqdm_bar.update(len(BODY))
        target.write(BODY)

    monkeypatch.setattr(
        LocalModelService,
        "_assert_hub_transfer_compatibility",
        staticmethod(lambda: (public_url, public_metadata, public_download, public_headers)),
    )
    download_service = LocalModelService(
        tmp_path / "download",
        llama_server=lambda: None,
        hardware=lambda _binary: HardwareSummary(),
        clock=lambda: T0,
        model_info=stub_model_info(files=FILES),
    )
    status = wait_for_download(download_service, download_service.start_download(_request()).download_id)
    assert status.state == "completed"
    assert seen == {"api_token": False, "metadata_token": False, "header_token": False}


def test_one_alias_cannot_be_reserved_by_two_artifacts_concurrently(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(*, repo_id: str, filename: str, local_dir: Path, revision: str) -> Path:
        entered.set()
        assert release.wait(5), "test did not release the synthetic downloader"
        path = Path(local_dir) / filename
        path.write_bytes(BODY)
        return path

    service = _service(tmp_path, downloader=blocked)
    first = service.start_download(_request(alias="shared-alias"))
    assert entered.wait(5), "synthetic downloader did not start"
    service._model_info = stub_model_info(  # noqa: SLF001 - simulate a second immutable artifact
        files={FILENAME: (2048, DIGEST)},
        head_revision=OTHER_REVISION,
        pinned_revision=OTHER_REVISION,
    )
    with pytest.raises(LocalModelError) as caught:
        service.start_download(_request(alias="shared-alias", confirmed_revision=OTHER_REVISION))
    assert caught.value.code == "alias_exists"
    release.set()
    assert wait_for_download(service, first.download_id).state == "completed"


# ----- what actually landed on disk -----


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"GGUF" + bytes(2043), "size_mismatch"),
        (b"GGUF" + bytes(2045), "size_mismatch"),
        (b"XXXX" + bytes(2044), "not_a_gguf_file"),
    ],
)
def test_a_file_that_is_not_what_was_promised_registers_nothing(tmp_path: Path, body, code) -> None:
    service = _service(tmp_path, downloader=_writing_downloader(body))
    status = wait_for_download(service, service.start_download(_request()).download_id)
    assert status.state == "failed" and status.error_code == code
    assert service.registry.list() == ()
    written = service.registry.root / "registry.json"
    assert not written.is_file() or json.loads(written.read_text(encoding="utf-8"))["models"] == []


def test_a_body_with_the_right_size_but_the_wrong_digest_is_deleted(tmp_path: Path) -> None:
    """Same length, same magic, different bytes: only the digest catches it."""

    tampered = b"GGUF" + bytes(2043) + b"\x01"
    assert len(tampered) == 2048 and hashlib.sha256(tampered).hexdigest() != DIGEST
    service = _service(tmp_path, downloader=_writing_downloader(tampered))
    status = wait_for_download(service, service.start_download(_request()).download_id)
    assert status.state == "failed" and status.error_code == "hash_mismatch"
    assert service.registry.list() == ()
    # Nothing is left behind for a later folder scan to register as a model.
    assert list(service.registry.weights_dir.rglob("*.gguf")) == []


def test_a_downloader_that_returns_a_path_outside_the_weights_folder_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    planted = outside / FILENAME
    planted.write_bytes(BODY)

    def escaping(*, repo_id: str, filename: str, local_dir: Path, revision: str) -> Path:
        return planted

    service = _service(tmp_path, downloader=escaping)
    status = wait_for_download(service, service.start_download(_request()).download_id)
    assert status.state == "failed" and status.error_code == "artifact_rejected"
    assert service.registry.list() == ()
    # A file the app did not put there is never deleted.
    assert planted.is_file()


def test_a_symlinked_artifact_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "outside.gguf"
    real.write_bytes(BODY)
    probe = tmp_path / "probe.link"
    try:
        probe.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("this machine does not allow creating symlinks")

    def linking(*, repo_id: str, filename: str, local_dir: Path, revision: str) -> Path:
        link = Path(local_dir) / filename
        link.symlink_to(real)
        return link

    service = _service(tmp_path, downloader=linking)
    status = wait_for_download(service, service.start_download(_request()).download_id)
    assert status.state == "failed" and status.error_code == "artifact_rejected"
    assert service.registry.list() == ()
    assert real.is_file()  # the symlink target survives


def test_a_downloader_failure_never_leaks_the_exception_text(tmp_path: Path) -> None:
    class GatedRepoError(RuntimeError):
        pass

    hostile_message = (
        "403 for https://example.invalid/api: token 'example-secret-value'"
    )

    def gated(**_kwargs):
        raise GatedRepoError(hostile_message)

    service = _service(tmp_path, downloader=gated)
    status = wait_for_download(service, service.start_download(_request()).download_id)
    assert status.state == "failed" and status.error_code == "gated_or_unauthorized"
    serialized = status.model_dump_json()
    assert hostile_message not in serialized
    assert "https://example.invalid/api" not in serialized
    assert "example-secret-value" not in serialized

    def bland(**_kwargs):
        raise RuntimeError("example-secret-value")

    other = _service(tmp_path / "other", downloader=bland)
    failed = wait_for_download(other, other.start_download(_request()).download_id)
    assert failed.error_code == "download_failed"
    assert "example-secret-value" not in failed.model_dump_json()


# ----- persistence, restart and old registries -----


def test_verified_provenance_survives_a_restart(tmp_path: Path) -> None:
    service = _service(tmp_path)
    status = wait_for_download(service, service.start_download(_request()).download_id)
    assert status.state == "completed"

    restarted = _service(tmp_path)
    record = restarted.registry.get("example-q4")
    assert record is not None
    assert record.source_revision == REVISION
    assert record.sha256 == DIGEST
    assert record.source_license == "apache-2.0"
    assert record.source_license_policy == LICENSE_POLICY_VERSION
    assert record.provenance_verified is True


def test_a_registry_written_before_provenance_stays_readable_and_says_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "local-models"
    root.mkdir(parents=True)
    (root / "registry.json").write_text(
        json.dumps(
            {
                "contract_version": "local-models.v1",
                "models": [
                    {
                        "alias": "legacy-q4",
                        "display_name": "Legacy Q4",
                        "format": "gguf",
                        "path": "D:/example/models/legacy-q4.gguf",
                        "source_repo": REPO_ID,
                        "source_file": FILENAME,
                        "size_bytes": 2048,
                        "sha256": None,
                        "default_device": "split",
                        "default_gpu_layers": None,
                        "context_size": 8192,
                        "layer_count": 32,
                        "added_at": "2026-03-04T09:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    record = LocalModelRegistry(root).get("legacy-q4")
    assert record is not None
    assert record.source_revision is None
    assert record.source_license is None
    assert record.source_license_policy is None
    assert record.provenance_verified is False


def test_a_manually_registered_file_never_claims_provenance(tmp_path: Path) -> None:
    weights = tmp_path / "manual.gguf"
    weights.write_bytes(BODY)
    service = _service(tmp_path)
    record = service.add(AddLocalModel(alias="manual-q4", path=str(weights)))
    assert record.provenance_verified is False
    assert record.source_revision is None and record.source_license is None and record.sha256 is None


# ----- HTTP surface -----


def test_the_api_returns_and_refuses_provenance(tmp_path: Path, monkeypatch) -> None:
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    service = application.create_local_model_service()
    service._model_info = stub_model_info(files=FILES)  # noqa: SLF001 - stubbing the Hub, never the network
    service._downloader = _writing_downloader(BODY)  # noqa: SLF001
    monkeypatch.setattr(type(application), "create_local_model_service", lambda _self: service)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    listing = client.get(f"/v1/local-models/remote-files?repo_id={REPO_ID}", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["revision"] == REVISION and body["revision_pinned"] is True
    assert body["license_id"] == "apache-2.0" and body["license_admission"] == "allowed"
    assert body["license_policy_version"] == LICENSE_POLICY_VERSION
    assert body["files"] == [
        {
            "filename": FILENAME,
            "size_bytes": 2048,
            "sha256": DIGEST,
            "eligible": True,
            "ineligible_reason": None,
        }
    ]

    substituted = client.post(
        "/v1/local-models/downloads",
        headers=headers,
        json={
            "repo_id": REPO_ID,
            "filename": FILENAME,
            "confirmed_size_bytes": 2048,
            "confirmed_revision": OTHER_REVISION,
            "confirmed_sha256": DIGEST,
            "confirmed_license": "apache-2.0",
            "alias": "example-q4",
        },
    )
    assert substituted.status_code == 409
    assert substituted.json()["detail"] == {"code": "provenance_mismatch"}

    # A mutable revision is not even a well-formed request.
    mutable = client.post(
        "/v1/local-models/downloads",
        headers=headers,
        json={
            "repo_id": REPO_ID,
            "filename": FILENAME,
            "confirmed_size_bytes": 2048,
            "confirmed_revision": "main",
            "confirmed_sha256": DIGEST,
            "confirmed_license": "apache-2.0",
            "alias": "example-q4",
        },
    )
    assert mutable.status_code == 422

    accepted = client.post(
        "/v1/local-models/downloads",
        headers=headers,
        json={
            "repo_id": REPO_ID,
            "filename": FILENAME,
            "confirmed_size_bytes": 2048,
            "confirmed_revision": REVISION,
            "confirmed_sha256": DIGEST,
            "confirmed_license": "apache-2.0",
            "alias": "example-q4",
        },
    )
    assert accepted.status_code == 202
    assert accepted.json()["revision"] == REVISION and accepted.json()["sha256"] == DIGEST
    wait_for_download(service, accepted.json()["download_id"])
    overview = client.get("/v1/local-models", headers=headers).json()
    record = next(m["record"] for m in overview["models"] if m["record"]["alias"] == "example-q4")
    assert record["source_revision"] == REVISION
    assert record["sha256"] == DIGEST
    assert record["source_license"] == "apache-2.0"
    assert record["provenance_verified"] is True
