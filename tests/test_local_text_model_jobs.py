from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Event
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prompt_enhancer.infrastructure.text_models.jobs import (
    LocalTextModelEvaluationService,
    ModelEvaluationBusyError,
    ModelEvaluationRequest,
    summarize_model_report,
)
from prompt_enhancer.interfaces.http.research_routes import create_research_router


def _safe_report() -> dict[str, object]:
    return {
        "device": "cuda",
        "candidate_outcomes": [
            {"key": "qwen3_embedding_06b", "status": "evaluated", "error_code": None},
            {
                "key": "bge_m3",
                "status": "blocked_before_download",
                "error_code": "unsafe_pickle_only",
            },
        ],
        "retrieval": [
            {"backend_key": "lexical_bm25_v1", "top1_accuracy": 0.5},
            {
                "backend_key": "qwen3_embedding_last_token_v1",
                "top1_accuracy": 0.75,
                "mean_reciprocal_rank": 0.875,
                "inference_latency_ms": 125.0,
                "runtime": {"peak_cuda_allocated_mb": 1200.0},
                "private_canary": "must-not-cross-projection",
            },
        ],
        "reranking": [],
        "nli": [],
        "rubric": [],
    }


def _wait(service: LocalTextModelEvaluationService, job_id: str):
    for _ in range(100):
        job = service.get(job_id)
        if job.status not in {"queued", "running"}:
            return job
        time.sleep(0.01)
    raise AssertionError("synthetic model job did not finish")


def test_shutdown_cancels_the_owned_evaluation_process(tmp_path: Path, monkeypatch) -> None:
    from prompt_enhancer.infrastructure.text_models import jobs

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "evaluate_local_text_models.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(jobs, "repository_root", lambda: tmp_path)
    start_owned = jobs._start_model_evaluation_process
    launched = Event()
    owned = []

    def capture(command, *, root, environment):
        process = start_owned(command, root=root, environment=environment)
        if len(command) > 1 and command[1] == str(script):
            owned.append(process)
            launched.set()
        return process

    monkeypatch.setattr(jobs, "_start_model_evaluation_process", capture)
    service = LocalTextModelEvaluationService()
    job = service.start(ModelEvaluationRequest(candidate="e5", device="cpu"))
    try:
        assert launched.wait(2)
        service.shutdown(timeout=5)
        assert service.get(job.job_id).status == "cancelled"
        assert service.get(job.job_id).error_code == "application_shutdown"
        assert service.get(job.job_id).outcomes == ()
        assert all(process.poll() is not None for process in owned)
        service.shutdown(timeout=1)
        with pytest.raises(jobs.ModelEvaluationUnavailableError):
            service.start(ModelEvaluationRequest(candidate="e5"))
    finally:
        for process in owned:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_evaluation_thread_start_failure_does_not_leave_a_busy_job(monkeypatch) -> None:
    from prompt_enhancer.infrastructure.text_models import jobs

    class UnavailableThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("EXAMPLE_PRIVATE_EVALUATION_START_CANARY")

    service = LocalTextModelEvaluationService(lambda _request: _safe_report())
    with monkeypatch.context() as patch:
        patch.setattr(jobs, "Thread", UnavailableThread)
        with pytest.raises(jobs.ModelEvaluationUnavailableError, match="model_evaluation_start_failed"):
            service.start(ModelEvaluationRequest())
    assert service._active_job_id is None
    assert service._jobs == {}
    job = service.start(ModelEvaluationRequest())
    assert _wait(service, job.job_id).status == "completed"
    service.shutdown(timeout=1)


def test_failed_report_without_candidate_rows_is_not_a_success() -> None:
    report = _safe_report()
    report.update(status="not_completed", candidate_outcomes=[], retrieval=[])
    service = LocalTextModelEvaluationService(lambda _request: report)
    job = service.start(ModelEvaluationRequest())
    assert _wait(service, job.job_id).status == "failed"


def test_shutdown_failure_is_not_hidden_by_a_finished_evaluation_thread() -> None:
    from prompt_enhancer.infrastructure.text_models import jobs

    def fail_cleanup(_request):
        raise jobs.ModelEvaluationCleanupError("model_evaluation_cleanup_unconfirmed")

    service = LocalTextModelEvaluationService(fail_cleanup)
    job = service.start(ModelEvaluationRequest())
    assert _wait(service, job.job_id).error_code == "model_evaluation_cleanup_unconfirmed"
    with pytest.raises(RuntimeError, match="^model_evaluation_shutdown_incomplete$"):
        service.shutdown(timeout=1)
    with pytest.raises(jobs.ModelEvaluationUnavailableError):
        service.start(ModelEvaluationRequest())


@pytest.mark.parametrize("case", ("oversized", "invalid-json"))
def test_evaluation_child_output_is_bounded_and_validated(tmp_path, monkeypatch, case):
    from prompt_enhancer.infrastructure.text_models import jobs

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "evaluate_local_text_models.py"
    if case == "oversized":
        source = "import sys\nsys.stdout.buffer.write(b'x' * (2 * 1024 * 1024 + 1))\n"
    else:
        source = "print('not-json')\n"
    script.write_text(source, encoding="utf-8")
    monkeypatch.setattr(jobs, "repository_root", lambda: tmp_path)
    with pytest.raises(jobs.ModelEvaluationError):
        jobs.run_model_evaluation_subprocess(ModelEvaluationRequest(candidate="e5", device="cpu"))


def test_stopped_evaluation_service_has_an_explicit_http_boundary() -> None:
    service = LocalTextModelEvaluationService(lambda _request: _safe_report())
    service.shutdown()
    app = FastAPI()
    app.include_router(create_research_router(lambda: None, service))
    response = TestClient(app).post("/v1/research/text-model-evaluations", json={"candidate": "e5"})
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "model_evaluation_unavailable"}}


def test_report_projection_is_content_free_and_typed() -> None:
    device, outcomes = summarize_model_report(_safe_report())
    assert device == "cuda"
    assert outcomes[0].primary_metric == "top1_accuracy"
    assert outcomes[0].primary_value == 0.75
    assert outcomes[0].peak_accelerator_memory_mb == 1200.0
    assert outcomes[1].status == "blocked_before_download"
    assert "must-not-cross-projection" not in repr(outcomes)


def test_e5_base_projection_uses_its_own_pinned_candidate_identity() -> None:
    report = {
        "device": "cuda",
        "candidate_outcomes": [
            {
                "key": "multilingual_e5_base",
                "status": "evaluated",
                "error_code": None,
            }
        ],
        "retrieval": [
            {
                "backend_key": "multilingual_e5_base_cosine_v1",
                "top1_accuracy": 0.833333,
                "mean_reciprocal_rank": 0.902778,
                "inference_latency_ms": 453.488,
                "runtime": {"peak_cuda_allocated_mb": 1078.121},
            }
        ],
        "reranking": [],
        "nli": [],
        "rubric": [],
    }

    device, outcomes = summarize_model_report(report)

    assert device == "cuda"
    assert outcomes[0].key == "multilingual_e5_base"
    assert outcomes[0].primary_value == 0.833333
    assert outcomes[0].secondary_value == 0.902778
    assert outcomes[0].peak_accelerator_memory_mb == 1078.121


def test_bge_m3_safe_revision_projects_aggregate_retrieval_measurements() -> None:
    report = {
        "device": "cuda",
        "candidate_outcomes": [
            {"key": "bge_m3", "status": "evaluated", "error_code": None}
        ],
        "retrieval": [
            {
                "backend_key": "bge_m3_cls_cosine_v1",
                "top1_accuracy": 0.666667,
                "mean_reciprocal_rank": 0.819444,
                "inference_latency_ms": 432.376,
                "runtime": {"peak_cuda_allocated_mb": 2179.602},
            }
        ],
        "reranking": [],
        "nli": [],
        "rubric": [],
    }

    device, outcomes = summarize_model_report(report)

    assert device == "cuda"
    assert outcomes[0].key == "bge_m3"
    assert outcomes[0].status == "evaluated"
    assert outcomes[0].primary_value == 0.666667
    assert outcomes[0].secondary_value == 0.819444
    assert outcomes[0].peak_accelerator_memory_mb == 2179.602


def test_service_runs_one_daemon_job_and_rejects_concurrent_work() -> None:
    entered = Event()
    release = Event()

    def runner(_request):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=2)
        return _safe_report()

    service = LocalTextModelEvaluationService(runner)
    first = service.start(ModelEvaluationRequest(candidate="all", device="cuda"))
    assert entered.wait(timeout=1)
    with pytest.raises(ModelEvaluationBusyError):
        service.start(ModelEvaluationRequest(candidate="e5"))
    release.set()
    completed = _wait(service, first.job_id)
    assert completed.status == "completed"
    assert completed.resolved_device == "cuda"
    assert len(completed.outcomes) == 2


def test_e5_base_is_an_explicit_bounded_request_choice() -> None:
    request = ModelEvaluationRequest(candidate="e5-base", device="cuda", mode="full")

    assert request.candidate == "e5-base"
    assert request.allow_download is False


def test_http_job_contract_is_bounded_and_content_free() -> None:
    service = LocalTextModelEvaluationService(lambda _request: _safe_report())
    app = FastAPI()
    app.include_router(create_research_router(lambda: None, service))
    client = TestClient(app)

    runtime = client.get("/v1/research/text-model-runtime")
    started = client.post(
        "/v1/research/text-model-evaluations",
        json={
            "candidate": "all",
            "device": "auto",
            "mode": "smoke",
            "allow_download": False,
        },
    )
    assert runtime.status_code == 200
    assert runtime.json()["raw_session_data_accepted"] is False
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    for _ in range(100):
        result = client.get(f"/v1/research/text-model-evaluations/{job_id}")
        if result.json()["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert result.json()["outcomes"][0]["primary_value"] == 0.75
    serialized = result.text
    assert "must-not-cross-projection" not in serialized
    assert "prompt" not in serialized.casefold()
    assert "transcript" not in serialized.casefold()

    e5_base = client.post(
        "/v1/research/text-model-evaluations",
        json={
            "candidate": "e5-base",
            "device": "cuda",
            "mode": "full",
            "allow_download": False,
        },
    )
    assert e5_base.status_code == 202
    assert e5_base.json()["candidate"]["candidate"] == "e5-base"
