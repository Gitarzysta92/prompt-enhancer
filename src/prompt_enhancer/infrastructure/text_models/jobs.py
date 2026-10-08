"""Bounded, content-free subprocess jobs for the synthetic model screen."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import Event, RLock, Thread
from time import monotonic
from types import MappingProxyType
from typing import Callable, Mapping

from ...application.owned_process import (
    OwnedProcess,
    process_tree_exited,
    start_owned_process,
    terminate_owned_process,
)
from .compatibility import (
    ModelCompatibilityCatalog,
    ModelRuntimeInventory,
    build_model_compatibility_catalog,
    cached_runtime_inventory,
)
from .loader import repository_root


_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_CANDIDATES = frozenset(
    {
        "all",
        "session-link",
        "e5",
        "e5-base",
        "nli",
        "bge-m3",
        "bge-reranker",
        "qwen-embedding",
        "qwen-reranker",
        "qwen-rubric",
    }
)
_DEVICES = frozenset({"auto", "cpu", "cuda", "mps"})
_MODES = frozenset({"smoke", "full"})
_OUTCOME_STATUS = frozenset(
    {"evaluated", "not_completed", "blocked_before_download"}
)
_ERROR_CODES = frozenset(
    {
        "unsafe_pickle_only",
        "model_cache_missing_or_invalid",
        "batch_size_outside_manifest_bound",
        "cuda_unavailable",
        "mps_unavailable",
        "resource_exhausted",
        "evaluation_failed",
    }
)
_MODEL_KEYS = frozenset(
    {
        "multilingual_e5_small",
        "multilingual_e5_base",
        "mdeberta_xnli",
        "bge_m3",
        "bge_reranker_v2_m3",
        "qwen3_embedding_06b",
        "qwen3_reranker_06b",
        "qwen3_4b_rubric",
    }
)
_BACKEND_TO_MODEL = MappingProxyType(
    {
        "multilingual_e5_small_cosine_v1": "multilingual_e5_small",
        "multilingual_e5_base_cosine_v1": "multilingual_e5_base",
        "bge_m3_cls_cosine_v1": "bge_m3",
        "qwen3_embedding_last_token_v1": "qwen3_embedding_06b",
        "bge_reranker_sequence_classifier_v1": "bge_reranker_v2_m3",
        "qwen3_reranker_yes_no_v1": "qwen3_reranker_06b",
        "mdeberta_xnli_argmax_v1": "mdeberta_xnli",
        "qwen3_4b_structured_rubric_v1": "qwen3_4b_rubric",
    }
)


class ModelEvaluationError(RuntimeError):
    pass


class ModelEvaluationBusyError(ModelEvaluationError):
    pass


class ModelEvaluationUnavailableError(ModelEvaluationError):
    pass


class ModelEvaluationCancelled(ModelEvaluationError):
    pass


class ModelEvaluationCleanupError(ModelEvaluationError):
    pass


class ModelEvaluationNotFoundError(ModelEvaluationError):
    pass


@dataclass(frozen=True, slots=True)
class ModelEvaluationRequest:
    candidate: str = "all"
    device: str = "auto"
    mode: str = "smoke"
    allow_download: bool = False

    def __post_init__(self) -> None:
        if self.candidate not in _CANDIDATES:
            raise ValueError("unsupported model candidate selection")
        if self.device not in _DEVICES:
            raise ValueError("unsupported model device")
        if self.mode not in _MODES:
            raise ValueError("unsupported model evaluation mode")


@dataclass(frozen=True, slots=True)
class CandidateEvaluationSummary:
    key: str
    status: str
    error_code: str | None
    primary_metric: str | None = None
    primary_value: float | None = None
    secondary_metric: str | None = None
    secondary_value: float | None = None
    critical_metric: str | None = None
    critical_value: float | None = None
    inference_latency_ms: float | None = None
    peak_accelerator_memory_mb: float | None = None


@dataclass(frozen=True, slots=True)
class ModelEvaluationJob:
    job_id: str
    status: str
    request: ModelEvaluationRequest
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    resolved_device: str | None = None
    error_code: str | None = None
    outcomes: tuple[CandidateEvaluationSummary, ...] = ()


Runner = Callable[[ModelEvaluationRequest], Mapping[str, object]]


def runtime_inventory(*, force_refresh: bool = False) -> ModelRuntimeInventory:
    return cached_runtime_inventory(force_refresh=force_refresh)


def _child_environment(root: Path) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for name in (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "CUDA_VISIBLE_DEVICES",
    ):
        value = os.environ.get(name)
        if value:
            allowed[name] = value
    allowed.update(
        {
            "PYTHONPATH": str(root / "src"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "TRANSFORMERS_VERBOSITY": "error",
        }
    )
    return allowed


def _start_model_evaluation_process(
    command: list[str],
    *,
    root: Path,
    environment: dict[str, str],
) -> OwnedProcess:
    return start_owned_process(
        command,
        cwd=root,
        env=environment,
        capture_stdout=True,
        capture_stderr=False,
        maximum_active_processes=32,
    )


def _close_model_evaluation_process(process: object) -> bool:
    close = getattr(process, "close", None)
    if callable(close):
        try:
            return bool(close())
        except Exception:
            return False
    stdout = getattr(process, "stdout", None)
    if stdout is not None:
        try:
            stdout.close()
        except (OSError, ValueError):
            return False
    return True


def run_model_evaluation_subprocess(
    request: ModelEvaluationRequest,
    *,
    cancellation: Event | None = None,
) -> Mapping[str, object]:
    cancellation = cancellation if cancellation is not None else Event()
    if cancellation.is_set():
        raise ModelEvaluationCancelled("application_shutdown")
    root = repository_root()
    script = root / "scripts" / "evaluate_local_text_models.py"
    if not script.is_file():
        raise ModelEvaluationError("model evaluator unavailable")
    command = [
        sys.executable,
        str(script),
        "--candidate",
        request.candidate,
        "--device",
        request.device,
    ]
    if request.mode == "smoke":
        command.append("--smoke")
    if request.allow_download:
        command.append("--download")
    process = None
    reader = None
    captured = bytearray()
    read_finished = Event()
    read_failed = Event()
    output_limit = 2 * 1024 * 1024

    def read_bounded() -> None:
        try:
            assert process is not None and process.stdout is not None
            while len(captured) <= output_limit:
                chunk = process.stdout.read(min(64 * 1024, output_limit + 1 - len(captured)))
                if not chunk:
                    break
                captured.extend(chunk)
        except (OSError, ValueError):
            read_failed.set()
        finally:
            read_finished.set()

    try:
        process = _start_model_evaluation_process(
            command,
            root=root,
            environment=_child_environment(root),
        )
        reader = Thread(target=read_bounded, name="model-evaluation-output", daemon=True)
        reader.start()
        deadline = monotonic() + 1_800
        while True:
            if cancellation.is_set():
                raise ModelEvaluationCancelled("application_shutdown")
            if len(captured) > output_limit:
                raise ModelEvaluationError("model evaluation output exceeded bound")
            if read_failed.is_set():
                raise ModelEvaluationError("model evaluation output invalid")
            if read_finished.is_set() and process_tree_exited(process):
                break
            if monotonic() >= deadline:
                raise ModelEvaluationError("model evaluation timed out")
            cancellation.wait(0.05)
    except BaseException:
        cleanup_confirmed = process is None
        if process is not None:
            cleanup_confirmed = terminate_owned_process(
                process,
                graceful_timeout=1.0,
                forced_timeout=1.0,
            )
        if reader is not None and reader.ident is not None:
            reader.join(timeout=1)
            cleanup_confirmed = not reader.is_alive() and cleanup_confirmed
        if process is not None:
            cleanup_confirmed = (
                _close_model_evaluation_process(process) and cleanup_confirmed
            )
        if not cleanup_confirmed:
            raise ModelEvaluationCleanupError("model_evaluation_cleanup_unconfirmed") from None
        raise
    if reader is not None:
        reader.join(timeout=1)
    if process is None or reader is None or reader.is_alive():
        raise ModelEvaluationCleanupError("model_evaluation_cleanup_unconfirmed")
    return_code = process.returncode
    try:
        cleanup_confirmed = process_tree_exited(process)
    except Exception:
        cleanup_confirmed = False
    if (
        not cleanup_confirmed
        or not _close_model_evaluation_process(process)
        or return_code is None
    ):
        raise ModelEvaluationCleanupError("model_evaluation_cleanup_unconfirmed")
    try:
        payload = json.loads(captured.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelEvaluationError("model evaluation output invalid") from None
    if not isinstance(payload, dict):
        raise ModelEvaluationError("model evaluation output invalid")
    if return_code not in {0, 2} or (
        return_code == 0 and payload.get("status") != "completed"
    ) or (
        return_code == 2 and payload.get("status") not in {"not_completed", "completed_with_failures"}
    ):
        raise ModelEvaluationError("model evaluation output invalid")
    return payload


def _finite_ratio(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        return None
    return round(numeric, 6)


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return round(numeric, 3)


def _measurement_by_model(report: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    found: dict[str, Mapping[str, object]] = {}
    for bucket_name in ("retrieval", "reranking", "nli", "rubric"):
        bucket = report.get(bucket_name)
        if not isinstance(bucket, list):
            raise ModelEvaluationError("model evaluation output invalid")
        for item in bucket:
            if not isinstance(item, dict):
                raise ModelEvaluationError("model evaluation output invalid")
            backend = item.get("backend_key")
            if backend == "lexical_bm25_v1":
                continue
            model_key = _BACKEND_TO_MODEL.get(backend) if isinstance(backend, str) else None
            if model_key is None or model_key in found:
                raise ModelEvaluationError("model evaluation output invalid")
            found[model_key] = item
    return found


def summarize_model_report(report: Mapping[str, object]) -> tuple[str, tuple[CandidateEvaluationSummary, ...]]:
    device = report.get("device")
    if device not in {"cpu", "cuda", "mps"}:
        raise ModelEvaluationError("model evaluation output invalid")
    raw_outcomes = report.get("candidate_outcomes")
    if not isinstance(raw_outcomes, list) or len(raw_outcomes) > 8:
        raise ModelEvaluationError("model evaluation output invalid")
    measurements = _measurement_by_model(report)
    summaries: list[CandidateEvaluationSummary] = []
    for raw in raw_outcomes:
        if not isinstance(raw, dict) or set(raw) != {"key", "status", "error_code"}:
            raise ModelEvaluationError("model evaluation output invalid")
        key = raw["key"]
        status = raw["status"]
        error = raw["error_code"]
        if (
            key not in _MODEL_KEYS
            or status not in _OUTCOME_STATUS
            or (error is not None and error not in _ERROR_CODES)
        ):
            raise ModelEvaluationError("model evaluation output invalid")
        measurement = measurements.get(key)
        primary_metric = secondary_metric = critical_metric = None
        primary_value = secondary_value = critical_value = None
        if measurement is not None:
            if key in {
                "multilingual_e5_small",
                "multilingual_e5_base",
                "bge_m3",
                "qwen3_embedding_06b",
                "bge_reranker_v2_m3",
                "qwen3_reranker_06b",
            }:
                primary_metric, secondary_metric = "top1_accuracy", "mean_reciprocal_rank"
            elif key == "mdeberta_xnli":
                primary_metric, secondary_metric, critical_metric = (
                    "three_way_accuracy",
                    "contradiction_detection_macro_f1",
                    "different_scope_false_positive_rate",
                )
            elif key == "qwen3_4b_rubric":
                primary_metric, secondary_metric, critical_metric = (
                    "exact_label_accuracy",
                    "json_schema_compliance_rate",
                    "abstention_macro_f1",
                )
            if primary_metric:
                primary_value = _finite_ratio(measurement.get(primary_metric))
            if secondary_metric:
                secondary_value = _finite_ratio(measurement.get(secondary_metric))
            if critical_metric:
                critical_value = _finite_ratio(measurement.get(critical_metric))
            runtime = measurement.get("runtime")
            if not isinstance(runtime, dict):
                runtime = {}
            peak = runtime.get("peak_cuda_allocated_mb")
            if peak is None:
                peak = runtime.get("mps_allocated_mb")
            latency = _finite_nonnegative(measurement.get("inference_latency_ms"))
            memory = _finite_nonnegative(peak)
        else:
            latency = memory = None
        summaries.append(
            CandidateEvaluationSummary(
                key=str(key),
                status=str(status),
                error_code=None if error is None else str(error),
                primary_metric=primary_metric,
                primary_value=primary_value,
                secondary_metric=secondary_metric,
                secondary_value=secondary_value,
                critical_metric=critical_metric,
                critical_value=critical_value,
                inference_latency_ms=latency,
                peak_accelerator_memory_mb=memory,
            )
        )
    return str(device), tuple(summaries)


class LocalTextModelEvaluationService:
    """One process-local model job at a time; no session input is accepted."""

    def __init__(self, runner: Runner | None = None) -> None:
        self._stop = Event()
        self._runner = runner or (lambda request: run_model_evaluation_subprocess(request, cancellation=self._stop))
        self._lock = RLock()
        self._jobs: dict[str, ModelEvaluationJob] = {}
        self._active_job_id: str | None = None
        self._thread: Thread | None = None
        self._cleanup_failed = False

    def inventory(self, *, force_refresh: bool = False) -> ModelRuntimeInventory:
        return runtime_inventory(force_refresh=force_refresh)

    def compatibility_catalog(self) -> ModelCompatibilityCatalog:
        return build_model_compatibility_catalog(self.inventory())

    def start(self, request: ModelEvaluationRequest) -> ModelEvaluationJob:
        with self._lock:
            if self._stop.is_set() or self._cleanup_failed:
                raise ModelEvaluationUnavailableError("model_evaluation_shutting_down")
            if self._active_job_id is not None:
                active = self._jobs.get(self._active_job_id)
                if active and active.status in {"queued", "running"}:
                    raise ModelEvaluationBusyError("model evaluation is already running")
            job_id = secrets.token_hex(16)
            job = ModelEvaluationJob(
                job_id=job_id,
                status="queued",
                request=request,
                created_at=datetime.now(UTC),
            )
            self._jobs[job_id] = job
            self._active_job_id = job_id
            self._trim_locked()
            start_failed = False
            try:
                thread = Thread(target=self._execute, args=(job_id,), name="local-model-evaluation", daemon=True)
                self._thread = thread
                thread.start()
            except Exception:
                self._jobs.pop(job_id, None)
                self._active_job_id = None
                self._thread = None
                start_failed = True
            if start_failed:
                raise ModelEvaluationUnavailableError("model_evaluation_start_failed")
        return job

    def shutdown(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            self._stop.set()
            thread = self._thread
        failed = False
        if thread is not None:
            try:
                thread.join(timeout=max(0.0, timeout))
                failed = thread.is_alive()
            except Exception:
                failed = True
        with self._lock:
            failed = self._cleanup_failed or failed
        if failed:
            raise RuntimeError("model_evaluation_shutdown_incomplete")

    def get(self, job_id: str) -> ModelEvaluationJob:
        if _JOB_ID.fullmatch(job_id) is None:
            raise ModelEvaluationNotFoundError("model evaluation not found")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ModelEvaluationNotFoundError("model evaluation not found")
            return job

    def _execute(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job = replace(job, status="running", started_at=datetime.now(UTC))
            self._jobs[job_id] = job
        try:
            if self._stop.is_set():
                raise ModelEvaluationCancelled("application_shutdown")
            report = self._runner(job.request)
            device, outcomes = summarize_model_report(report)
            failed = report.get("status") in {"not_completed", "completed_with_failures"} or any(
                item.status == "not_completed" for item in outcomes
            )
            final = replace(
                job,
                status="failed" if failed else "completed",
                completed_at=datetime.now(UTC),
                resolved_device=device,
                error_code="candidate_evaluation_incomplete" if failed else None,
                outcomes=outcomes,
            )
        except ModelEvaluationCancelled:
            final = replace(job, status="cancelled", completed_at=datetime.now(UTC), error_code="application_shutdown")
        except ModelEvaluationCleanupError:
            with self._lock:
                self._cleanup_failed = True
            final = replace(job, status="failed", completed_at=datetime.now(UTC), error_code="model_evaluation_cleanup_unconfirmed")
        except Exception:
            final = replace(
                job,
                status="failed",
                completed_at=datetime.now(UTC),
                error_code="model_evaluation_failed",
            )
        with self._lock:
            if self._stop.is_set() and final.status == "completed":
                final = replace(job, status="cancelled", completed_at=datetime.now(UTC), error_code="application_shutdown")
            self._jobs[job_id] = final
            if self._active_job_id == job_id:
                self._active_job_id = None

    def _trim_locked(self) -> None:
        completed = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status not in {"queued", "running"}
            ),
            key=lambda item: item.created_at,
        )
        for job in completed[:-7]:
            self._jobs.pop(job.job_id, None)
