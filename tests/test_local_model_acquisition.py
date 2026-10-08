"""Durable local-model acquisition and owned-runtime recovery.

Every artifact, repository and process in this module is synthetic.  The tests
never use the network, a provider credential, a real model, or the GPU.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prompt_enhancer.application.local_models import (
    DOWNLOAD_DISK_RESERVE_BYTES,
    AddLocalModel,
    DownloadRequest,
    HardwareSummary,
    LlamaServerProcess,
    LocalModelError,
    LocalModelService,
    RuntimeState,
    RuntimeStatus,
    _runtime_environment,
    _spawn_owned_runtime,
    runtime_exit_failure_code,
)
from prompt_enhancer.interfaces.http.local_model_routes import create_local_model_router
from tests.local_model_hub_stubs import REVISION, REPO_ID, stub_model_info


T0 = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
BODY = b"GGUF" + bytes(4092)
DIGEST = hashlib.sha256(BODY).hexdigest()
FILENAME = "synthetic-q4.gguf"


def _request(**changes: object) -> DownloadRequest:
    payload: dict[str, object] = {
        "repo_id": REPO_ID,
        "filename": FILENAME,
        "confirmed_size_bytes": len(BODY),
        "confirmed_revision": REVISION,
        "confirmed_sha256": DIGEST,
        "confirmed_license": "apache-2.0",
        "alias": "synthetic-q4",
    }
    payload.update(changes)
    return DownloadRequest(**payload)  # type: ignore[arg-type]


def _disk(*, free: int):
    return lambda _path: shutil._ntuple_diskusage(total=free * 2, used=free, free=free)


def _service(
    root: Path,
    *,
    transfer=None,
    free: int = DOWNLOAD_DISK_RESERVE_BYTES + len(BODY) + 1024,
    model_info=None,
) -> LocalModelService:
    return LocalModelService(
        root,
        llama_server=lambda: None,
        hardware=lambda _binary: HardwareSummary(),
        clock=lambda: T0,
        model_info=model_info or stub_model_info(files={FILENAME: (len(BODY), DIGEST)}),
        download_transfer=transfer,
        disk_usage=_disk(free=free),
    )


def _wait(service: LocalModelService, download_id: str, states: set[str], timeout: float = 5) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = next(item for item in service.overview().downloads if item.download_id == download_id)
        if current.state in states:
            return current
        time.sleep(0.01)
    return next(item for item in service.overview().downloads if item.download_id == download_id)


def _rewind_completed_ledger(root: Path) -> int:
    ledger = root / "downloads.json"
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    status = payload["jobs"][0]["status"]
    completed_revision = int(status["status_revision"])
    status.update(
        state="downloading",
        error_code=None,
        finished_at=None,
    )
    ledger.write_text(json.dumps(payload), encoding="utf-8")
    return completed_revision


def _complete_synthetic_download(root: Path) -> LocalModelService:
    def transfer(*, partial_path: Path, progress, **_kwargs) -> Path:
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_bytes(BODY)
        progress(len(BODY))
        return partial_path

    service = _service(root, transfer=transfer)
    started = service.start_download(_request())
    assert _wait(service, started.download_id, {"completed", "failed"}).state == "completed"
    service.shutdown()
    return service


def test_disk_refusal_is_durable_and_never_enters_the_transfer(tmp_path: Path) -> None:
    calls: list[object] = []
    service = _service(
        tmp_path / "local-models",
        free=DOWNLOAD_DISK_RESERVE_BYTES + len(BODY) - 1,
        transfer=lambda **kwargs: calls.append(kwargs),
    )

    status = service.start_download(_request())

    assert status.state == "failed"
    assert status.error_code == "insufficient_disk_space"
    assert status.disk_required_bytes == DOWNLOAD_DISK_RESERVE_BYTES + len(BODY)
    assert status.disk_free_bytes_at_start == DOWNLOAD_DISK_RESERVE_BYTES + len(BODY) - 1
    assert status.status_revision == 1
    assert calls == []
    assert (service.registry.root / "downloads.json").is_file()

    restarted = _service(
        tmp_path / "local-models",
        free=DOWNLOAD_DISK_RESERVE_BYTES + len(BODY) - 1,
    )
    restored = restarted.overview().downloads[0]
    assert restored.download_id == status.download_id
    assert restored.state == "failed"
    assert restored.error_code == "insufficient_disk_space"


def test_unknown_disk_capacity_fails_closed_without_entering_the_transfer(tmp_path: Path) -> None:
    calls: list[object] = []
    service = LocalModelService(
        tmp_path / "local-models",
        llama_server=lambda: None,
        hardware=lambda _binary: HardwareSummary(),
        clock=lambda: T0,
        model_info=stub_model_info(files={FILENAME: (len(BODY), DIGEST)}),
        download_transfer=lambda **kwargs: calls.append(kwargs),
        disk_usage=lambda _path: (_ for _ in ()).throw(OSError("synthetic disk probe failure")),
    )

    status = service.start_download(_request())

    assert status.state == "failed"
    assert status.error_code == "disk_space_unavailable"
    assert status.disk_free_bytes_at_start is None
    assert calls == []


def test_pause_survives_restart_and_resume_continues_the_owned_partial(tmp_path: Path) -> None:
    first_chunk_written = threading.Event()
    resume_offsets: list[int] = []

    def transfer(*, artifact, partial_path: Path, resume_size: int, progress, **_kwargs) -> Path:
        resume_offsets.append(resume_size)
        mode = "ab" if resume_size else "wb"
        with partial_path.open(mode) as target:
            if resume_size == 0:
                target.write(BODY[:1024])
                target.flush()
                progress(1024)
                first_chunk_written.set()
                while True:
                    time.sleep(0.01)
                    progress(0)
            target.write(BODY[resume_size:])
            target.flush()
            progress(len(BODY))
        return partial_path

    root = tmp_path / "local-models"
    service = _service(root, transfer=transfer)
    started = service.start_download(_request())
    assert first_chunk_written.wait(2)

    current = next(item for item in service.overview().downloads if item.download_id == started.download_id)
    pausing = service.pause_download(started.download_id, expected_revision=current.status_revision)
    assert pausing.state in {"pausing", "paused"}
    paused = _wait(service, started.download_id, {"paused"})
    assert paused.state == "paused"
    assert paused.bytes_done == 1024
    assert paused.partial_retained is True

    restarted = _service(root, transfer=transfer)
    recovered = restarted.overview().downloads[0]
    assert recovered.state == "paused"
    resumed = restarted.resume_download(
        recovered.download_id,
        expected_revision=recovered.status_revision,
    )
    completed = _wait(restarted, resumed.download_id, {"completed", "failed"})
    assert completed.state == "completed"
    assert resume_offsets == [0, 1024]
    assert restarted.registry.get("synthetic-q4") is not None


def test_restart_settles_exact_published_download_without_a_second_transfer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "local-models"
    completed_service = _complete_synthetic_download(root)
    completed_revision = _rewind_completed_ledger(root)
    transfer_calls: list[object] = []

    restarted = _service(
        root,
        transfer=lambda **kwargs: transfer_calls.append(kwargs),
    )

    recovered = restarted.overview().downloads[0]
    assert recovered.state == "completed"
    assert recovered.error_code is None
    assert recovered.bytes_done == len(BODY)
    assert recovered.status_revision == completed_revision + 1
    assert transfer_calls == []
    assert restarted.registry.get("synthetic-q4") == completed_service.registry.get(
        "synthetic-q4"
    )

    repeated = _service(root)
    assert repeated.overview().downloads[0] == recovered


@pytest.mark.parametrize("conflict", ["registry", "artifact"])
def test_restart_fails_closed_on_published_download_conflict_without_cleanup(
    tmp_path: Path,
    conflict: str,
) -> None:
    root = tmp_path / "local-models"
    service = _complete_synthetic_download(root)
    record = service.registry.get("synthetic-q4")
    assert record is not None
    final = Path(record.path)
    _rewind_completed_ledger(root)

    if conflict == "registry":
        registry_path = root / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["models"][0]["display_name"] = "Conflicting synthetic owner record"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        expected_bytes = BODY
    else:
        expected_bytes = b"GGUF" + bytes(4086) + b"drift!"
        assert len(expected_bytes) == len(BODY)
        final.write_bytes(expected_bytes)

    restarted = _service(root)

    recovered = restarted.overview().downloads[0]
    assert recovered.state == "failed"
    assert recovered.error_code == "download_registry_conflict"
    assert recovered.cleanup_confirmed is None
    assert final.read_bytes() == expected_bytes
    assert restarted.registry.get("synthetic-q4") is not None

    repeated = _service(root)
    assert repeated.overview().downloads[0] == recovered


def test_cancel_removes_only_the_owned_partial_and_is_idempotent(tmp_path: Path) -> None:
    started_writing = threading.Event()

    def transfer(*, partial_path: Path, progress, **_kwargs) -> Path:
        with partial_path.open("wb") as target:
            target.write(BODY[:512])
            target.flush()
            progress(512)
            started_writing.set()
            while True:
                time.sleep(0.01)
                progress(0)

    service = _service(tmp_path / "local-models", transfer=transfer)
    unrelated = tmp_path / "unrelated.gguf"
    unrelated.write_bytes(BODY)
    started = service.start_download(_request())
    assert started_writing.wait(2)

    current = next(item for item in service.overview().downloads if item.download_id == started.download_id)
    cancelling = service.cancel_download(started.download_id, expected_revision=current.status_revision)
    assert cancelling.state in {"cancelling", "cancelled"}
    cancelled = _wait(service, started.download_id, {"cancelled", "failed"})
    assert cancelled.state == "cancelled"
    assert cancelled.cleanup_confirmed is True
    assert cancelled.partial_retained is False
    assert list(service.registry.weights_dir.rglob("*.partial")) == []
    assert unrelated.read_bytes() == BODY

    same = service.cancel_download(
        started.download_id,
        expected_revision=cancelled.status_revision,
    )
    assert same == cancelled


def test_retry_revalidates_provenance_and_increments_attempt(tmp_path: Path) -> None:
    calls = 0

    def failing_transfer(**_kwargs) -> Path:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic closed failure")

    info = stub_model_info(files={FILENAME: (len(BODY), DIGEST)})
    service = _service(tmp_path / "local-models", transfer=failing_transfer, model_info=info)
    started = service.start_download(_request())
    failed = _wait(service, started.download_id, {"failed"})
    assert failed.attempt == 1
    assert calls == 1

    service._model_info = stub_model_info(  # noqa: SLF001 - synthetic repository movement
        files={FILENAME: (len(BODY), DIGEST)},
        head_revision="89abcdef0123456789abcdef0123456789abcdef",
        pinned_revision="89abcdef0123456789abcdef0123456789abcdef",
    )
    with pytest.raises(LocalModelError, match="^provenance_mismatch$"):
        service.retry_download(failed.download_id, expected_revision=failed.status_revision)
    unchanged = service.overview().downloads[0]
    assert unchanged.attempt == 1
    assert calls == 1


def test_download_commands_have_closed_revision_checked_http_routes(tmp_path: Path) -> None:
    writing = threading.Event()

    def transfer(*, partial_path: Path, resume_size: int, progress, **_kwargs) -> Path:
        with partial_path.open("ab" if resume_size else "wb") as target:
            if resume_size == 0:
                target.write(BODY[:256])
                target.flush()
                progress(256)
                writing.set()
                while True:
                    time.sleep(0.01)
                    progress(0)
            target.write(BODY[resume_size:])
            target.flush()
            progress(len(BODY))
        return partial_path

    service = _service(tmp_path / "local-models", transfer=transfer)
    started = service.start_download(_request())
    assert writing.wait(2)
    app = FastAPI()
    app.include_router(create_local_model_router(lambda: None, service))
    client = TestClient(app, base_url="http://127.0.0.1")
    current = service.overview().downloads[0]

    stale = client.post(
        f"/v1/local-models/downloads/{started.download_id}/pause",
        json={"expected_status_revision": current.status_revision - 1},
    )
    assert stale.status_code == 409
    assert stale.json() == {"detail": {"code": "download_revision_conflict"}}

    pausing = client.post(
        f"/v1/local-models/downloads/{started.download_id}/pause",
        json={"expected_status_revision": current.status_revision},
    )
    assert pausing.status_code == 200
    paused = _wait(service, started.download_id, {"paused"})
    resumed = client.post(
        f"/v1/local-models/downloads/{started.download_id}/resume",
        json={"expected_status_revision": paused.status_revision},
    )
    assert resumed.status_code == 200
    assert _wait(service, started.download_id, {"completed", "failed"}).state == "completed"

    completed = service.overview().downloads[0]
    invalid = client.post(
        f"/v1/local-models/downloads/{started.download_id}/cancel",
        json={"expected_status_revision": completed.status_revision},
    )
    assert invalid.status_code == 409
    assert invalid.json() == {"detail": {"code": "download_action_invalid"}}


def test_shutdown_cooperatively_pauses_and_joins_download_workers(tmp_path: Path) -> None:
    writing = threading.Event()

    def transfer(*, partial_path: Path, progress, **_kwargs) -> Path:
        with partial_path.open("wb") as target:
            target.write(BODY[:128])
            target.flush()
            progress(128)
            writing.set()
            while True:
                time.sleep(0.01)
                progress(0)

    root = tmp_path / "local-models"
    service = _service(root, transfer=transfer)
    started = service.start_download(_request())
    assert writing.wait(2)

    service.shutdown()

    paused = next(item for item in service.overview().downloads if item.download_id == started.download_id)
    assert paused.state == "paused"
    assert service._download_workers == {}  # noqa: SLF001 - bounded shutdown evidence
    restarted = _service(root, transfer=transfer)
    assert restarted.overview().downloads[0].state == "paused"


def test_malformed_download_ledger_is_preserved_and_blocks_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "local-models"
    root.mkdir(parents=True)
    ledger = root / "downloads.json"
    ledger.write_text("{not-json", encoding="utf-8")

    service = _service(root)

    assert service.overview().download_ledger_error_code == "download_ledger_invalid"
    with pytest.raises(LocalModelError, match="^download_ledger_invalid$"):
        service.start_download(_request())
    assert ledger.read_text(encoding="utf-8") == "{not-json"


def test_hub_transfer_adapter_fails_closed_on_dependency_version_drift(monkeypatch) -> None:
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "__version__", "0.37.0")
    with pytest.raises(LocalModelError, match="^download_adapter_incompatible$"):
        LocalModelService._assert_hub_transfer_compatibility()  # noqa: SLF001

@pytest.mark.parametrize(
    ("platform_name", "exit_code", "expected"),
    [
        ("nt", 0xC0000017, "runtime_out_of_memory"),
        ("nt", -1073741523, "runtime_out_of_memory"),
        ("nt", 0xC000012D, "runtime_out_of_memory"),
        ("nt", 17, "runtime_crashed"),
        ("posix", -9, "runtime_crashed"),
        ("nt", 0, "runtime_exited"),
    ],
)
def test_runtime_exit_classification_uses_only_exact_exit_evidence(
    platform_name: str,
    exit_code: int,
    expected: str,
) -> None:
    assert runtime_exit_failure_code(exit_code, platform_name=platform_name) == expected


def test_runtime_environment_excludes_ambient_provider_credentials() -> None:
    environment = _runtime_environment({
        "PATH": "C:/synthetic/runtime",
        "SYSTEMROOT": "C:/synthetic/windows",
        "CUDA_VISIBLE_DEVICES": "0",
        "HF_TOKEN": "synthetic-provider-token",
        "OPENAI_API_KEY": "synthetic-provider-key",
        "PROMPT_ENHANCER_API_TOKEN": "synthetic-local-token",
    })

    assert environment == {
        "PATH": "C:/synthetic/runtime",
        "SYSTEMROOT": "C:/synthetic/windows",
        "CUDA_VISIBLE_DEVICES": "0",
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows job admission is Windows-specific")
def test_production_runtime_spawn_uses_hidden_atomic_windows_job(monkeypatch) -> None:
    from prompt_enhancer.application import local_command_windows

    captured: dict[str, object] = {}

    class Job:
        def __init__(self, argv, **options) -> None:
            captured["argv"] = argv
            captured.update(options)

    monkeypatch.setattr(local_command_windows, "WindowsCommandJob", Job)
    result = _spawn_owned_runtime(
        ["C:/synthetic/llama-server.exe", "--host", "127.0.0.1"],
        stdin=-3,
        stdout=-3,
        stderr=-3,
        shell=False,
        creationflags=0x08000000,
    )

    assert isinstance(result, Job)
    assert captured["capture_output"] is False
    assert captured["cwd"] is None
    assert captured["argv"] == ["C:/synthetic/llama-server.exe", "--host", "127.0.0.1"]
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert all("TOKEN" not in key.upper() and "KEY" not in key.upper() for key in environment)


@pytest.mark.skipif(os.name != "nt", reason="exact NTSTATUS classification is Windows-specific")
def test_status_integrates_exact_windows_oom_exit_truth(tmp_path: Path) -> None:
    service = LocalModelService(
        tmp_path / "local-models",
        llama_server=lambda: None,
        hardware=lambda _binary: HardwareSummary(),
        clock=lambda: T0,
    )
    weights = tmp_path / "synthetic.gguf"
    weights.write_bytes(BODY)
    service.add(AddLocalModel(alias="synthetic-runtime", path=str(weights)))

    class Process:
        pid = 7002

        @staticmethod
        def poll():
            return 0xC0000017

        @staticmethod
        def tree_exited():
            return True

        @staticmethod
        def close():
            return True

    handle = LlamaServerProcess(
        process=Process(),
        port=48123,
        activation_generation=1,
        status=RuntimeStatus(state=RuntimeState.RUNNING, pid=7002),
    )
    service._processes["synthetic-runtime"] = handle  # noqa: SLF001 - synthetic crash receipt
    status = service.status("synthetic-runtime")

    assert status.runtime.state is RuntimeState.FAILED
    assert status.runtime.last_error_code == "runtime_out_of_memory"


def test_stop_requires_the_owned_process_tree_and_handle_cleanup() -> None:
    class Process:
        pid = 7001

        def __init__(self) -> None:
            self.terminated = False
            self.closed = False

        def poll(self):
            return 1 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            assert timeout > 0
            return 1

        def tree_exited(self):
            return False

        def close(self):
            self.closed = True
            return True

    process = Process()
    handle = type("Handle", (), {"process": process})()

    with pytest.raises(LocalModelError, match="^runtime_stop_failed$"):
        LocalModelService._stop(handle)  # noqa: SLF001
    assert process.terminated is True
    assert process.closed is True
