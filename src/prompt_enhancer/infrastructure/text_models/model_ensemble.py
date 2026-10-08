"""Sequential, process-isolated local model committee for shadow metrics.

Private redacted fragments are sent only to a local child process over stdin.
The child emits bounded content-free scores and receipts.  A new process is
used for every model so process exit releases model weights from RAM/VRAM even
when a backend cleanup hook is imperfect.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from time import monotonic
from typing import Callable, Mapping, Sequence

from ...application.owned_process import (
    OwnedProcess,
    process_tree_exited,
    start_owned_process,
    terminate_owned_process,
)

from ...application.analysis.model_ensemble import (
    ChunkMetricCommitteeReceipt,
    EnsembleChunkPlan,
    EnsembleMetricSpec,
    MODEL_ENSEMBLE_MODEL_COUNT,
    ModelEvidenceSelectionReceipt,
    ModelExpertIdentity,
    ModelExpertReceipt,
    ModelExpertRole,
    ModelExpertStatus,
    ModelMetricVote,
    ModelVoteState,
    SessionModelEnsembleReceipt,
    SourceCoverageState,
    aggregate_chunk_metrics,
    committee_chunk_receipt,
    content_free_chunk_plan,
    ensemble_plan_fingerprint,
)
from ...application.persistence import MetricValueState
from ...application.model_reply import model_json_object
from .loader import model_eval_cache_root, repository_root
from .run_control import (
    MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE,
    ModelEnsembleCleanupUnconfirmedError,
    ModelEnsembleError,
    ModelRunControl,
    controlled_model_run,
)
from .manifests import (
    BGE_M3,
    BGE_RERANKER_V2_M3,
    DEBERTA_SMALL_LONG_NLI,
    E5_MULTILINGUAL_BASE,
    E5_MULTILINGUAL_SMALL,
    MDEBERTA_XNLI,
    MODERNBERT_BASE_ZEROSHOT,
    QWEN3_4B_RUBRIC,
    QWEN3_EMBEDDING_06B,
    QWEN3_RERANKER_06B,
    ModelManifest,
)
from ..specialist_screen.manifests import MINILMV2_L12_NLI, MINILMV2_L6_NLI


MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION = 3
MAX_ENSEMBLE_SUBPROCESS_INPUT_BYTES = 2 * 1024 * 1024
MAX_ENSEMBLE_SUBPROCESS_OUTPUT_BYTES = 4 * 1024 * 1024
MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS = 1_200.0
MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_ERROR_CODE = (
    "model_ensemble_subprocess_timeout"
)
MODEL_ENSEMBLE_SUBPROCESS_TERMINATION_GRACE_SECONDS = 0.5
# Cancellation shares the lease heartbeat callback, so keep this frequent
# enough that Windows process-tree cleanup still fits inside the bounded Stop
# contract under load. Model inference remains in the child process.
MODEL_ENSEMBLE_SUBPROCESS_CONTROL_INTERVAL_SECONDS = 0.25
MAX_SELECTED_RETRIEVAL_FRAGMENTS = 8
MAX_SELECTED_RERANKED_FRAGMENTS = 2
CONTRIBUTING_NLI_MODEL_KEYS = frozenset(
    {MINILMV2_L6_NLI.key, MINILMV2_L12_NLI.key}
)


@dataclass(frozen=True, slots=True)
class EnsembleExpertSpec:
    identity: ModelExpertIdentity
    manifest: ModelManifest
    cache_root: Path


def _identity(
    ordinal: int,
    manifest: ModelManifest,
    role: ModelExpertRole,
    backend_key: str,
    *,
    contributes: bool,
) -> ModelExpertIdentity:
    return ModelExpertIdentity(
        ordinal=ordinal,
        model_key=manifest.key,
        role=role,
        repository_id=manifest.repository_id,
        revision=manifest.revision,
        tokenizer_id=f"{manifest.key}-tokenizer",
        license_spdx=manifest.license_spdx,
        backend_key=backend_key,
        contributes_to_decision=contributes,
    )


def ensemble_expert_specs() -> tuple[EnsembleExpertSpec, ...]:
    root = model_eval_cache_root()
    specs = (
        EnsembleExpertSpec(
            _identity(0, E5_MULTILINGUAL_SMALL, ModelExpertRole.RETRIEVAL, "e5_mean_pool_v1", contributes=False),
            E5_MULTILINGUAL_SMALL,
            root,
        ),
        EnsembleExpertSpec(
            _identity(1, E5_MULTILINGUAL_BASE, ModelExpertRole.RETRIEVAL, "e5_mean_pool_v1", contributes=False),
            E5_MULTILINGUAL_BASE,
            root,
        ),
        EnsembleExpertSpec(
            _identity(2, BGE_M3, ModelExpertRole.RETRIEVAL, "bge_m3_cls_cosine_v1", contributes=False),
            BGE_M3,
            root,
        ),
        EnsembleExpertSpec(
            _identity(3, QWEN3_EMBEDDING_06B, ModelExpertRole.RETRIEVAL, "qwen3_embedding_last_token_v1", contributes=False),
            QWEN3_EMBEDDING_06B,
            root,
        ),
        EnsembleExpertSpec(
            _identity(4, BGE_RERANKER_V2_M3, ModelExpertRole.RERANKING, "bge_reranker_sequence_classifier_v1", contributes=False),
            BGE_RERANKER_V2_M3,
            root,
        ),
        EnsembleExpertSpec(
            _identity(5, QWEN3_RERANKER_06B, ModelExpertRole.RERANKING, "qwen3_reranker_yes_no_v1", contributes=False),
            QWEN3_RERANKER_06B,
            root,
        ),
        EnsembleExpertSpec(
            _identity(6, MDEBERTA_XNLI, ModelExpertRole.SCOPE_NLI, "mdeberta_xnli_probabilities_v1", contributes=False),
            MDEBERTA_XNLI,
            root,
        ),
        EnsembleExpertSpec(
            _identity(7, MINILMV2_L6_NLI, ModelExpertRole.SCOPE_NLI, "minilm_xnli_probabilities_v1", contributes=True),
            MINILMV2_L6_NLI,
            root / "specialist-screen",
        ),
        EnsembleExpertSpec(
            _identity(8, MINILMV2_L12_NLI, ModelExpertRole.SCOPE_NLI, "minilm_xnli_probabilities_v1", contributes=True),
            MINILMV2_L12_NLI,
            root / "specialist-screen",
        ),
        EnsembleExpertSpec(
            _identity(9, QWEN3_4B_RUBRIC, ModelExpertRole.STRUCTURED_RUBRIC, "qwen3_4b_dynamic_shadow_rubric_v1", contributes=True),
            QWEN3_4B_RUBRIC,
            root,
        ),
    )
    if tuple(item.identity.ordinal for item in specs) != tuple(
        range(MODEL_ENSEMBLE_MODEL_COUNT)
    ):
        raise RuntimeError("ensemble model order is invalid")
    return specs


def probabilistic_challenger_specs() -> tuple[EnsembleExpertSpec, ...]:
    """Pinned English/long-context challengers outside the legacy ten-stage graph."""

    root = model_eval_cache_root()
    return (
        EnsembleExpertSpec(
            _identity(
                6,
                DEBERTA_SMALL_LONG_NLI,
                ModelExpertRole.SCOPE_NLI,
                "deberta_long_nli_probabilities_v1",
                contributes=False,
            ),
            DEBERTA_SMALL_LONG_NLI,
            root,
        ),
        EnsembleExpertSpec(
            _identity(
                7,
                MODERNBERT_BASE_ZEROSHOT,
                ModelExpertRole.SCOPE_NLI,
                "modernbert_binary_nli_probabilities_v1",
                contributes=False,
            ),
            MODERNBERT_BASE_ZEROSHOT,
            root,
        ),
    )


StageExecutor = Callable[
    [EnsembleExpertSpec, str, Mapping[str, object], str], Mapping[str, object]
]


def _child_environment(root: Path, cache_root: Path) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for name in (
        "PATH",
        "SystemRoot",
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
            "HF_HOME": str(cache_root / "hf-home"),
            "HF_HUB_CACHE": str(cache_root),
            "HF_TOKEN_PATH": str(cache_root / "credentials-disabled" / "token"),
            "HF_STORED_TOKENS_PATH": str(
                cache_root / "credentials-disabled" / "stored-tokens"
            ),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "TRANSFORMERS_VERBOSITY": "error",
            # Torch's ModernBERT module decorates one helper with
            # ``torch.compile`` at import time. Give it a task-local cache so
            # it never consults the OS account name or a home directory.
            "TORCHINDUCTOR_CACHE_DIR": str(cache_root / "torch-inductor"),
            "TRITON_CACHE_DIR": str(cache_root / "triton"),
            # A synthetic worker identity prevents third-party cache helpers
            # from attempting to discover or expose the OS account name.
            "USERNAME": "prompt-enhancer-worker",
            "USER": "prompt-enhancer-worker",
        }
    )
    return allowed


def _process_control_environment() -> dict[str, str]:
    """Keep Windows process control functional without inheriting credentials."""

    allowlist = frozenset(
        {
            "APPDATA",
            "COMSPEC",
            "HOMEDRIVE",
            "HOMEPATH",
            "LOCALAPPDATA",
            "PATH",
            "PATHEXT",
            "SYSTEMDRIVE",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
        }
    )
    return {
        name: value
        for name, value in os.environ.items()
        if name.upper() in allowlist and "\x00" not in value
    }


def _start_ensemble_process(
    command: list[str],
    *,
    root: Path,
    environment: dict[str, str],
) -> OwnedProcess:
    return start_owned_process(
        command,
        cwd=root,
        env=environment,
        pipe_stdin=True,
        capture_stdout=True,
        capture_stderr=False,
        maximum_active_processes=16,
    )


def _close_ensemble_process(process: object, *, close_streams: bool) -> bool:
    close = getattr(process, "close", None)
    if callable(close):
        try:
            return bool(close(close_streams=close_streams))
        except Exception:
            return False
    if close_streams:
        for pipe in (getattr(process, "stdin", None), getattr(process, "stdout", None)):
            if pipe is None:
                continue
            try:
                pipe.close()
            except (OSError, ValueError):
                return False
    return True


def _terminate_ensemble_process_tree(
    process: OwnedProcess,
    *,
    environment: Mapping[str, str],
    close_pipes: bool = True,
) -> bool:
    """Force one isolated model tree down and report positive confirmation."""

    del environment
    confirmed = terminate_owned_process(
        process,
        graceful_timeout=MODEL_ENSEMBLE_SUBPROCESS_TERMINATION_GRACE_SECONDS,
        forced_timeout=MODEL_ENSEMBLE_SUBPROCESS_TERMINATION_GRACE_SECONDS,
    )
    closed = _close_ensemble_process(
        process,
        close_streams=close_pipes,
    )
    return confirmed and closed


def run_ensemble_expert_subprocess(
    spec: EnsembleExpertSpec,
    stage: str,
    payload: Mapping[str, object],
    device: str,
    *,
    python_executable: str | None = None,
    heartbeat: Callable[[], None] | None = None,
    quantization: str = "none",
    timeout_seconds: float = MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS,
) -> Mapping[str, object]:
    if quantization not in {"none", "bitsandbytes_nf4"}:
        raise ModelEnsembleError("model_ensemble_quantization_invalid")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS
    ):
        raise ModelEnsembleError("model_ensemble_timeout_invalid")
    bounded_timeout = float(timeout_seconds)
    root = repository_root()
    script = root / "scripts" / "run_local_model_ensemble_expert.py"
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if not body or len(body) > MAX_ENSEMBLE_SUBPROCESS_INPUT_BYTES:
        raise ModelEnsembleError("model_ensemble_input_outside_bound")
    command = [
        python_executable or sys.executable,
        str(script),
        "--model-key",
        spec.identity.model_key,
        "--stage",
        stage,
        "--device",
        device,
        "--quantization",
        quantization,
    ]
    child_environment = _child_environment(root, spec.cache_root)
    process = None
    threads: list[Thread] = []
    captured = bytearray()
    input_finished, output_finished, io_failed = Event(), Event(), Event()
    poll_wait = Event()

    def write_input() -> None:
        try:
            remaining = memoryview(body)
            while remaining:
                written = process.stdin.write(remaining[:64 * 1024])
                if not written:
                    raise OSError("model input pipe stopped accepting bytes")
                remaining = remaining[written:]
            process.stdin.close()  # EOF is part of the child input protocol.
        except Exception:
            io_failed.set()
        finally:
            input_finished.set()

    def read_output() -> None:
        try:
            while len(captured) <= MAX_ENSEMBLE_SUBPROCESS_OUTPUT_BYTES:
                chunk = process.stdout.read(min(64 * 1024, MAX_ENSEMBLE_SUBPROCESS_OUTPUT_BYTES + 1 - len(captured)))
                if not chunk:
                    break
                captured.extend(chunk)
        except Exception:
            io_failed.set()
        finally:
            output_finished.set()

    def finish_io() -> bool:
        joined = True
        for thread in threads:
            if thread.ident is not None:
                try:
                    thread.join(timeout=MODEL_ENSEMBLE_SUBPROCESS_TERMINATION_GRACE_SECONDS)
                    joined = not thread.is_alive() and joined
                except Exception:
                    joined = False
        # Never close a buffered/active pipe from underneath another thread.
        # An unjoined I/O worker is a fatal cleanup uncertainty, not success.
        if joined and process is not None:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    try:
                        pipe.close()
                    except (OSError, ValueError):
                        pass
        return joined

    try:
        # An already cancelled job must not allocate another model process.
        if heartbeat is not None:
            heartbeat()
        started = monotonic()
        process = _start_ensemble_process(
            command,
            root=root,
            environment=child_environment,
        )
        for target, name in ((read_output, "model-stage-output"), (write_input, "model-stage-input")):
            thread = Thread(target=target, name=name, daemon=True)
            threads.append(thread)
            try:
                thread.start()
            except (OSError, RuntimeError):
                raise ModelEnsembleError("model_ensemble_subprocess_failed") from None
        next_heartbeat = started + MODEL_ENSEMBLE_SUBPROCESS_CONTROL_INTERVAL_SECONDS
        while True:
            observed = monotonic()
            remaining = bounded_timeout - (observed - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, bounded_timeout)
            if len(captured) > MAX_ENSEMBLE_SUBPROCESS_OUTPUT_BYTES:
                raise ModelEnsembleError("model_ensemble_output_invalid")
            if io_failed.is_set():
                raise ModelEnsembleError("model_ensemble_subprocess_failed")
            if observed >= next_heartbeat:
                if heartbeat is not None:
                    heartbeat()
                next_heartbeat = (
                    observed + MODEL_ENSEMBLE_SUBPROCESS_CONTROL_INTERVAL_SECONDS
                )
            if (
                input_finished.is_set()
                and output_finished.is_set()
                and process_tree_exited(process)
            ):
                break
            poll_wait.wait(min(0.05, remaining))
        # Cancellation arriving with the final bytes still owns the outcome.
        if heartbeat is not None:
            heartbeat()
    except BaseException as error:
        cleanup_confirmed = process is None
        if process is not None:
            try:
                cleanup_confirmed = process_tree_exited(process)
            except Exception:
                cleanup_confirmed = False
            if not cleanup_confirmed:
                cleanup_confirmed = _terminate_ensemble_process_tree(
                    process,
                    environment=_process_control_environment(),
                    close_pipes=False,
                )
        io_finished = finish_io()
        handles_closed = process is None or _close_ensemble_process(
            process,
            close_streams=False,
        )
        if not io_finished or not cleanup_confirmed or not handles_closed:
            raise ModelEnsembleCleanupUnconfirmedError() from None
        if isinstance(error, subprocess.TimeoutExpired):
            raise ModelEnsembleError(MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_ERROR_CODE) from None
        if isinstance(error, OSError):
            raise ModelEnsembleError("model_ensemble_subprocess_failed") from None
        raise
    if process is None:
        raise ModelEnsembleCleanupUnconfirmedError()
    return_code = process.returncode
    try:
        cleanup_confirmed = process_tree_exited(process)
    except Exception:
        cleanup_confirmed = False
    if (
        not finish_io()
        or not cleanup_confirmed
        or not _close_ensemble_process(process, close_streams=False)
        or return_code is None
    ):
        raise ModelEnsembleCleanupUnconfirmedError()
    stdout = bytes(captured)
    if not stdout or len(stdout) > MAX_ENSEMBLE_SUBPROCESS_OUTPUT_BYTES:
        raise ModelEnsembleError("model_ensemble_output_invalid")
    try:
        result = model_json_object(stdout.decode("utf-8"), max_characters=MAX_ENSEMBLE_SUBPROCESS_OUTPUT_BYTES)
    except UnicodeDecodeError:
        raise ModelEnsembleError("model_ensemble_output_invalid") from None
    if not isinstance(result, dict):
        raise ModelEnsembleError("model_ensemble_output_invalid")
    if not ((return_code == 0 and result.get("status") == "completed") or (return_code == 2 and result.get("status") == "failed")):
        raise ModelEnsembleError("model_ensemble_subprocess_failed")
    return result


def _case_id(chunk_ordinal: int, metric_key: str) -> str:
    return hashlib.sha256(
        f"shadow-ensemble:{chunk_ordinal}:{metric_key}".encode("ascii")
    ).hexdigest()


def _ranking_fingerprint(
    model_key: str,
    case_id: str,
    ordered_ids: Sequence[str],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "model_key": model_key,
                "case_id": case_id,
                "ordered_ids": list(ordered_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()


def _rrf(rankings: Sequence[Sequence[str]], *, limit: int) -> tuple[str, ...]:
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, tuple[int, int]] = {}
    for list_index, ranking in enumerate(rankings):
        for rank, identifier in enumerate(ranking, start=1):
            scores[identifier] += 1.0 / (60 + rank)
            first_seen.setdefault(identifier, (list_index, rank))
    ordered = sorted(
        scores,
        key=lambda identifier: (-scores[identifier], first_seen[identifier], identifier),
    )
    return tuple(ordered[:limit])


def _status_receipt(
    spec: EnsembleExpertSpec,
    result: Mapping[str, object] | None,
    *,
    error_code: str | None = None,
) -> ModelExpertReceipt:
    if result is None:
        return ModelExpertReceipt(
            identity=spec.identity,
            status=ModelExpertStatus.FAILED,
            error_code=error_code or "model_stage_failed",
        )
    if result.get("status") != "completed":
        raw_error = result.get("error_code")
        safe_error = raw_error if isinstance(raw_error, str) else "model_stage_failed"
        status = (
            ModelExpertStatus.RESOURCE_EXHAUSTED
            if safe_error == "resource_exhausted"
            else ModelExpertStatus.UNAVAILABLE
            if safe_error == "model_cache_missing_or_invalid"
            else ModelExpertStatus.FAILED
        )
        return ModelExpertReceipt(
            identity=spec.identity,
            status=status,
            error_code=safe_error,
        )
    runtime = result.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    device = result.get("device")
    if device not in {"cpu", "cuda", "mps"}:
        raise ModelEnsembleError("model_ensemble_output_invalid")
    return ModelExpertReceipt(
        identity=spec.identity,
        status=ModelExpertStatus.COMPLETED,
        device=device,
        inference_latency_ms=_optional_nonnegative(runtime.get("inference_latency_ms")),
        peak_accelerator_memory_mb=_optional_nonnegative(
            runtime.get("peak_cuda_allocated_mb")
        ),
        process_rss_mb=_optional_nonnegative(
            runtime.get("process_rss_after_load_and_inference_mb")
        ),
    )


def _optional_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return None
    return result


class SerialModelEnsembleRunner:
    """Run the ten reviewed experts in a fixed serial, process-isolated plan."""

    def __init__(
        self,
        *,
        executor: StageExecutor | None = None,
        device: str = "auto",
        python_executable: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if device not in {"auto", "cpu", "cuda", "mps"}:
            raise ValueError("unsupported ensemble device")
        self._device = device
        self._python_executable = python_executable
        self._clock = clock
        self._executor = executor or self._execute
        self._run_control = ModelRunControl()

    @property
    def _heartbeat_callback(self) -> Callable[[], None] | None:
        return self._run_control.heartbeat

    @_heartbeat_callback.setter
    def _heartbeat_callback(self, callback: Callable[[], None] | None) -> None:
        self._run_control.heartbeat = callback

    def plan_fingerprint(
        self,
        metric_specs: tuple[EnsembleMetricSpec, ...],
    ) -> str:
        """Return the current execution/observation contract identity."""

        identities = tuple(item.identity for item in ensemble_expert_specs())
        return ensemble_plan_fingerprint(identities, metric_specs)

    def _execute(
        self,
        spec: EnsembleExpertSpec,
        stage: str,
        payload: Mapping[str, object],
        device: str,
    ) -> Mapping[str, object]:
        return run_ensemble_expert_subprocess(
            spec,
            stage,
            payload,
            device,
            python_executable=self._python_executable,
            heartbeat=self._heartbeat_callback,
        )

    @controlled_model_run
    def run(
        self,
        chunk_plan: EnsembleChunkPlan,
        metric_specs: tuple[EnsembleMetricSpec, ...],
        *,
        progress_callback: Callable[[int, int], None] | None = None,
        prior_receipt: SessionModelEnsembleReceipt | None = None,
    ) -> SessionModelEnsembleReceipt:
        if chunk_plan.source_coverage_state is not SourceCoverageState.COMPLETE_WINDOW:
            raise ModelEnsembleError("model_ensemble_source_incomplete")
        if not metric_specs or len({item.metric_key for item in metric_specs}) != len(metric_specs):
            raise ValueError("ensemble metric specs must be non-empty and unique")
        created_at = self._clock()
        self._heartbeat_callback = (
            None
            if progress_callback is None
            else lambda: progress_callback(len(receipts), MODEL_ENSEMBLE_MODEL_COUNT)
        )
        experts = ensemble_expert_specs()
        plan_fingerprint = self.plan_fingerprint(metric_specs)
        # Observation-owner lineage is not persisted yet.  Reusing an older
        # receipt from only a physical chunk fingerprint could split a long
        # focus request or miss later conversation context, so a changed input
        # recomputes every owned observation.  Exact unchanged inputs are
        # already reused by the service before this runner is entered.
        _ = prior_receipt
        ordered_fragments = tuple(
            item
            for chunk in chunk_plan.chunks
            for item in chunk.fragments
        )
        fragments = {item.fragment_id: item for item in ordered_fragments}
        fragment_order = {
            item.fragment_id: index for index, item in enumerate(ordered_fragments)
        }
        all_candidate_ids = tuple(item.fragment_id for item in ordered_fragments)
        focus_fragments = tuple(
            item
            for item in ordered_fragments
            if item.is_focus_message
            and item.role.value == "user"
            and item.kind.value in {"request", "feedback"}
        )
        focus_candidate_ids = tuple(item.fragment_id for item in focus_fragments)
        focus_owner = next(
            (
                chunk.ordinal
                for chunk in reversed(chunk_plan.chunks)
                if any(item.is_focus_message for item in chunk.fragments)
            ),
            chunk_plan.chunks[-1].ordinal,
        )
        session_owner = chunk_plan.chunks[-1].ordinal
        base_cases: list[dict[str, object]] = []
        structural_cases: list[tuple[int, str, str]] = []
        unsupported_cases: list[tuple[int, str, str]] = []
        for chunk in chunk_plan.chunks:
            for metric in metric_specs:
                if metric.evidence_scope == "focus_request":
                    owner = focus_owner
                    candidates = focus_candidate_ids
                    ownership_reason = "focus_request_observation_owned_by_focus_tail"
                elif metric.evidence_scope == "conversation":
                    owner = session_owner
                    candidates = all_candidate_ids
                    ownership_reason = "session_window_observation_owned_by_final_chunk"
                else:
                    owner = session_owner
                    candidates = ()
                    ownership_reason = "objective_observation_owned_by_final_chunk"
                if chunk.ordinal != owner:
                    structural_cases.append(
                        (chunk.ordinal, metric.metric_key, ownership_reason)
                    )
                    continue
                if metric.evidence_scope == "objective_evidence":
                    unsupported_cases.append(
                        (
                            chunk.ordinal,
                            metric.metric_key,
                            "objective_evidence_unavailable",
                        )
                    )
                    continue
                if not candidates:
                    unsupported_cases.append(
                        (
                            chunk.ordinal,
                            metric.metric_key,
                            "metric_scope_excludes_chunk",
                        )
                    )
                    continue
                base_cases.append(
                    {
                        "case_id": _case_id(chunk.ordinal, metric.metric_key),
                        "chunk_ordinal": chunk.ordinal,
                        "metric_key": metric.metric_key,
                        "candidate_ids": list(candidates),
                        "query": metric.retrieval_query,
                        "hypothesis": metric.entailment_hypothesis,
                        "rubric": metric.rubric,
                    }
                )
        fragment_payload = [
            {
                "fragment_id": identifier,
                "text": fragment.text.get_secret_value(),
                "role": fragment.role.value,
                "kind": fragment.kind.value,
                "language": fragment.language.value,
                "is_focus_message": fragment.is_focus_message,
            }
            for identifier, fragment in fragments.items()
        ]
        common = {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "fragments": fragment_payload,
        }
        receipts: list[ModelExpertReceipt] = []
        if progress_callback is not None:
            progress_callback(0, MODEL_ENSEMBLE_MODEL_COUNT)
        selections: list[ModelEvidenceSelectionReceipt] = []
        votes: list[ModelMetricVote] = []
        chunk_receipts: list[ChunkMetricCommitteeReceipt] = [
            ChunkMetricCommitteeReceipt(
                chunk_ordinal=chunk_ordinal,
                metric_key=metric_key,
                value_state=MetricValueState.NOT_APPLICABLE,
                rubric_vote=ModelVoteState.UNSUPPORTED,
                contributing_nli_votes=0,
                diagnostic_nli_votes=0,
                reason_code=reason,
            )
            for chunk_ordinal, metric_key, reason in structural_cases
        ]
        rankings_by_case: dict[str, list[tuple[str, ...]]] = defaultdict(list)

        for spec in experts[:4]:
            result = self._safe_execute(
                spec,
                "retrieval",
                {**common, "cases": base_cases},
            )
            receipts.append(_status_receipt(spec, result))
            if progress_callback is not None:
                progress_callback(len(receipts), MODEL_ENSEMBLE_MODEL_COUNT)
            if result is None or result.get("status") != "completed":
                continue
            for case, scores in _parse_score_rows(result, base_cases):
                ranking = tuple(
                    identifier
                    for identifier, _ in sorted(
                        scores.items(), key=lambda item: (-item[1], item[0])
                    )
                )
                selected = ranking[:MAX_SELECTED_RETRIEVAL_FRAGMENTS]
                rankings_by_case[str(case["case_id"])].append(ranking)
                selections.append(
                    ModelEvidenceSelectionReceipt(
                        chunk_ordinal=int(case["chunk_ordinal"]),
                        metric_key=str(case["metric_key"]),
                        model_key=spec.identity.model_key,
                        role=ModelExpertRole.RETRIEVAL,
                        candidate_count=len(scores),
                        selected_fragment_ids=selected,
                        ranking_fingerprint=_ranking_fingerprint(
                            spec.identity.model_key, str(case["case_id"]), ranking
                        ),
                        top_raw_score=scores[selected[0]],
                    )
                )

        retrieved_by_case: dict[str, tuple[str, ...]] = {}
        for case in base_cases:
            case_id = str(case["case_id"])
            rankings = rankings_by_case.get(case_id)
            if not rankings:
                raise ModelEnsembleError("model_ensemble_retrieval_unavailable")
            retrieved_by_case[case_id] = _rrf(
                rankings, limit=MAX_SELECTED_RETRIEVAL_FRAGMENTS
            )

        rerank_cases = [
            {**case, "candidate_ids": list(retrieved_by_case[str(case["case_id"])])}
            for case in base_cases
        ]
        rerankings_by_case: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        for spec in experts[4:6]:
            result = self._safe_execute(
                spec,
                "reranking",
                {**common, "cases": rerank_cases},
            )
            receipts.append(_status_receipt(spec, result))
            if progress_callback is not None:
                progress_callback(len(receipts), MODEL_ENSEMBLE_MODEL_COUNT)
            if result is None or result.get("status") != "completed":
                continue
            for case, scores in _parse_score_rows(result, rerank_cases):
                ranking = tuple(
                    identifier
                    for identifier, _ in sorted(
                        scores.items(), key=lambda item: (-item[1], item[0])
                    )
                )
                selected = ranking[:MAX_SELECTED_RERANKED_FRAGMENTS]
                rerankings_by_case[str(case["case_id"])].append(ranking)
                selections.append(
                    ModelEvidenceSelectionReceipt(
                        chunk_ordinal=int(case["chunk_ordinal"]),
                        metric_key=str(case["metric_key"]),
                        model_key=spec.identity.model_key,
                        role=ModelExpertRole.RERANKING,
                        candidate_count=len(scores),
                        selected_fragment_ids=selected,
                        ranking_fingerprint=_ranking_fingerprint(
                            spec.identity.model_key, str(case["case_id"]), ranking
                        ),
                        top_raw_score=scores[selected[0]],
                    )
                )

        selected_by_case: dict[str, tuple[str, ...]] = {}
        for case in rerank_cases:
            case_id = str(case["case_id"])
            rankings = rerankings_by_case.get(case_id)
            if not rankings:
                raise ModelEnsembleError("model_ensemble_reranking_unavailable")
            selected_by_case[case_id] = _rrf(
                rankings, limit=MAX_SELECTED_RERANKED_FRAGMENTS
            )

        decision_cases = [
            {
                **case,
                # Retrieval/reranking receipts retain relevance order, while
                # cross-turn NLI and rubric decisions receive evidence in the
                # source chronology so an answer cannot precede its question.
                "candidate_ids": sorted(
                    selected_by_case[str(case["case_id"])],
                    key=fragment_order.__getitem__,
                ),
            }
            for case in base_cases
        ]
        votes.extend(
            _unsupported_vote(spec, chunk_ordinal, metric_key, reason)
            for chunk_ordinal, metric_key, reason in (
                *structural_cases,
                *unsupported_cases,
            )
            for spec in experts[6:]
        )
        for spec in experts[6:9]:
            result = self._safe_execute(
                spec,
                "scope_nli",
                {**common, "cases": decision_cases},
            )
            receipts.append(_status_receipt(spec, result))
            if progress_callback is not None:
                progress_callback(len(receipts), MODEL_ENSEMBLE_MODEL_COUNT)
            parsed = _parse_nli_rows(result, decision_cases) if result is not None else {}
            for case in decision_cases:
                case_id = str(case["case_id"])
                row = parsed.get(case_id)
                if row is None:
                    votes.append(
                        _failed_vote(spec, case, "model_scope_stage_failed")
                    )
                    continue
                label, confidence = max(row.items(), key=lambda item: item[1])
                state = {
                    "entailment": ModelVoteState.PRESENT,
                    "contradiction": ModelVoteState.ABSENT,
                    "neutral": ModelVoteState.ABSTAIN,
                }[label]
                votes.append(
                    ModelMetricVote(
                        chunk_ordinal=int(case["chunk_ordinal"]),
                        metric_key=str(case["metric_key"]),
                        model_key=spec.identity.model_key,
                        role=ModelExpertRole.SCOPE_NLI,
                        state=state,
                        raw_score=confidence if state is not ModelVoteState.ABSTAIN else None,
                        evidence_fragment_ids=tuple(case["candidate_ids"]),
                        reason_code=f"scope_{label}",
                    )
                )

        rubric_spec = experts[9]
        rubric_result = self._safe_execute(
            rubric_spec,
            "structured_rubric",
            {**common, "cases": decision_cases},
        )
        receipts.append(_status_receipt(rubric_spec, rubric_result))
        if progress_callback is not None:
            progress_callback(len(receipts), MODEL_ENSEMBLE_MODEL_COUNT)
        rubric_rows = _parse_rubric_rows(rubric_result, decision_cases) if rubric_result is not None else {}
        for case in decision_cases:
            label = rubric_rows.get(str(case["case_id"]))
            if label is None:
                votes.append(_failed_vote(rubric_spec, case, "model_rubric_stage_failed"))
                continue
            state = {
                "present": ModelVoteState.PRESENT,
                "absent": ModelVoteState.ABSENT,
                "abstain": ModelVoteState.ABSTAIN,
            }[label]
            votes.append(
                ModelMetricVote(
                    chunk_ordinal=int(case["chunk_ordinal"]),
                    metric_key=str(case["metric_key"]),
                    model_key=rubric_spec.identity.model_key,
                    role=ModelExpertRole.STRUCTURED_RUBRIC,
                    state=state,
                    raw_score=(1.0 if state is ModelVoteState.PRESENT else 0.0)
                    if state is not ModelVoteState.ABSTAIN
                    else None,
                    evidence_fragment_ids=tuple(case["candidate_ids"]),
                    reason_code=f"rubric_{label}",
                )
            )

        committee_cases = [
            *decision_cases,
            *(
                {
                    "chunk_ordinal": chunk_ordinal,
                    "metric_key": metric_key,
                }
                for chunk_ordinal, metric_key, _reason in unsupported_cases
            ),
        ]
        for case in committee_cases:
            matching = [
                item
                for item in votes
                if item.chunk_ordinal == int(case["chunk_ordinal"])
                and item.metric_key == str(case["metric_key"])
            ]
            rubric_vote = next(
                item for item in matching if item.role is ModelExpertRole.STRUCTURED_RUBRIC
            )
            nli_votes = tuple(
                item for item in matching if item.role is ModelExpertRole.SCOPE_NLI
            )
            chunk_receipts.append(
                committee_chunk_receipt(
                    chunk_ordinal=int(case["chunk_ordinal"]),
                    metric_key=str(case["metric_key"]),
                    rubric_vote=rubric_vote,
                    nli_votes=nli_votes,
                    contributing_nli_model_keys=CONTRIBUTING_NLI_MODEL_KEYS,
                )
            )

        metric_receipts = aggregate_chunk_metrics(tuple(chunk_receipts))
        completed_at = self._clock()
        return SessionModelEnsembleReceipt(
            plan_fingerprint=plan_fingerprint,
            source_window_fingerprint=chunk_plan.source_window_fingerprint,
            source_coverage_state=chunk_plan.source_coverage_state,
            chunk_count=len(chunk_plan.chunks),
            chunk_plan=content_free_chunk_plan(chunk_plan),
            chunks=tuple(
                sorted(
                    chunk_receipts,
                    key=lambda item: (item.chunk_ordinal, item.metric_key),
                )
            ),
            metrics=tuple(sorted(metric_receipts, key=lambda item: item.metric_key)),
            experts=tuple(receipts),
            evidence_selections=tuple(
                sorted(
                    selections,
                    key=lambda item: (
                        item.chunk_ordinal,
                        item.metric_key,
                        item.model_key,
                    ),
                )
            ),
            model_votes=tuple(
                sorted(
                    votes,
                    key=lambda item: (
                        item.chunk_ordinal,
                        item.metric_key,
                        item.model_key,
                    ),
                )
            ),
            created_at=created_at,
            completed_at=completed_at,
        )

    def _safe_execute(
        self,
        spec: EnsembleExpertSpec,
        stage: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        self._run_control.check()
        try:
            result = self._executor(spec, stage, payload, self._device)
            self._run_control.check()
        except Exception as error:
            self._run_control.check(error)
            return None
        if (
            result.get("status") != "completed"
            and result.get("error_code") == "resource_exhausted"
            and self._device in {"auto", "cuda"}
        ):
            # The first child has exited before fallback begins, so its CUDA
            # context and weights cannot overlap the CPU retry.
            try:
                result = self._executor(spec, stage, payload, "cpu")
                self._run_control.check()
            except Exception as error:
                self._run_control.check(error)
                return None
        if (
            set(result)
            != {
                "schema_version",
                "model_key",
                "status",
                "error_code",
                "device",
                "rows",
                "runtime",
            }
            or result.get("schema_version") != MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION
            or result.get("model_key") != spec.identity.model_key
        ):
            return None
        return result


def _failed_vote(
    spec: EnsembleExpertSpec,
    case: Mapping[str, object],
    reason: str,
) -> ModelMetricVote:
    return ModelMetricVote(
        chunk_ordinal=int(case["chunk_ordinal"]),
        metric_key=str(case["metric_key"]),
        model_key=spec.identity.model_key,
        role=spec.identity.role,
        state=ModelVoteState.FAILED,
        evidence_fragment_ids=tuple(case["candidate_ids"]),
        reason_code=reason,
    )


def _unsupported_vote(
    spec: EnsembleExpertSpec,
    chunk_ordinal: int,
    metric_key: str,
    reason: str,
) -> ModelMetricVote:
    return ModelMetricVote(
        chunk_ordinal=chunk_ordinal,
        metric_key=metric_key,
        model_key=spec.identity.model_key,
        role=spec.identity.role,
        state=ModelVoteState.UNSUPPORTED,
        reason_code=reason,
    )


def _parse_score_rows(
    result: Mapping[str, object],
    cases: Sequence[Mapping[str, object]],
) -> tuple[tuple[Mapping[str, object], dict[str, float]], ...]:
    raw_rows = result.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) != len(cases):
        raise ModelEnsembleError("model_ensemble_output_invalid")
    by_case = {str(case["case_id"]): case for case in cases}
    parsed = []
    for row in raw_rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "scores"}:
            raise ModelEnsembleError("model_ensemble_output_invalid")
        case_id = row["case_id"]
        raw_scores = row["scores"]
        if not isinstance(case_id, str) or case_id not in by_case or not isinstance(raw_scores, list):
            raise ModelEnsembleError("model_ensemble_output_invalid")
        expected_ids = tuple(by_case[case_id]["candidate_ids"])
        scores: dict[str, float] = {}
        for item in raw_scores:
            if not isinstance(item, dict) or set(item) != {"fragment_id", "score"}:
                raise ModelEnsembleError("model_ensemble_output_invalid")
            identifier, score = item["fragment_id"], item["score"]
            if (
                not isinstance(identifier, str)
                or identifier not in expected_ids
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or identifier in scores
            ):
                raise ModelEnsembleError("model_ensemble_output_invalid")
            scores[identifier] = float(score)
        if tuple(sorted(scores)) != tuple(sorted(expected_ids)):
            raise ModelEnsembleError("model_ensemble_output_invalid")
        parsed.append((by_case[case_id], scores))
    if len({str(case["case_id"]) for case, _ in parsed}) != len(cases):
        raise ModelEnsembleError("model_ensemble_output_invalid")
    return tuple(parsed)


def _parse_nli_rows(
    result: Mapping[str, object],
    cases: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, float]]:
    if result.get("status") != "completed":
        return {}
    raw_rows = result.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) != len(cases):
        return {}
    expected = {str(case["case_id"]) for case in cases}
    parsed: dict[str, dict[str, float]] = {}
    for row in raw_rows:
        if not isinstance(row, dict) or set(row) != {
            "case_id", "entailment", "neutral", "contradiction"
        }:
            return {}
        case_id = row["case_id"]
        if not isinstance(case_id, str) or case_id not in expected or case_id in parsed:
            return {}
        values = {
            label: row[label] for label in ("entailment", "neutral", "contradiction")
        }
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
            for value in values.values()
        ) or not math.isclose(sum(float(value) for value in values.values()), 1.0, abs_tol=1e-4):
            return {}
        parsed[case_id] = {key: float(value) for key, value in values.items()}
    return parsed if set(parsed) == expected else {}


def _parse_rubric_rows(
    result: Mapping[str, object],
    cases: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    if result.get("status") != "completed":
        return {}
    raw_rows = result.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) != len(cases):
        return {}
    expected = {str(case["case_id"]) for case in cases}
    parsed: dict[str, str] = {}
    for row in raw_rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "label"}:
            return {}
        case_id, label = row["case_id"], row["label"]
        if (
            not isinstance(case_id, str)
            or case_id not in expected
            or case_id in parsed
            or label not in {"present", "absent", "abstain"}
        ):
            return {}
        parsed[case_id] = str(label)
    return parsed if set(parsed) == expected else {}


__all__ = [
    "CONTRIBUTING_NLI_MODEL_KEYS",
    "EnsembleExpertSpec",
    "MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION",
    "MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE",
    "MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_ERROR_CODE",
    "MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS",
    "MODEL_ENSEMBLE_SUBPROCESS_TERMINATION_GRACE_SECONDS",
    "ModelEnsembleError",
    "SerialModelEnsembleRunner",
    "ensemble_expert_specs",
    "run_ensemble_expert_subprocess",
]
