"""Run exactly one reviewed local shadow-ensemble expert from private stdin.

The process emits content-free JSON only.  It never accepts a file path or
network switch, and verified model loading is forced offline.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Mapping, Sequence


_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "src"
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))

from prompt_enhancer.infrastructure.text_models.benchmark import (
    NliCase,
    RetrievalCandidate,
    RetrievalCase,
)
from prompt_enhancer.infrastructure.text_models.loader import (
    TextModelLoadError,
    isolated_hugging_face_environment,
    prepare_model_snapshot,
    transformers_network_closed,
)
from prompt_enhancer.infrastructure.text_models.model_ensemble import (
    MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
    ModelEnsembleError,
    ensemble_expert_specs,
    probabilistic_challenger_specs,
)
from prompt_enhancer.infrastructure.text_models.transformers_backends import (
    LocalBackendError,
    TransformersClsEmbeddingScorer,
    TransformersDynamicRubricJudge,
    TransformersE5Scorer,
    TransformersLastTokenEmbeddingScorer,
    TransformersNliClassifier,
    TransformersQwenReranker,
    TransformersSequenceReranker,
)


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INPUT_BYTES = 2 * 1024 * 1024
_MAX_FRAGMENTS = 256
_MAX_CASES = 160
_SAFE_ERRORS = {
    "model_cache_missing_or_invalid",
    "resource_exhausted",
    "cuda_unavailable",
    "mps_unavailable",
    "model_stage_failed",
    "quantization_backend_unavailable",
}
_ROLES = frozenset({"user", "agent"})
_KINDS = frozenset(
    {
        "request",
        "response",
        "plan",
        "action",
        "verification",
        "decision",
        "feedback",
        "summary",
    }
)
_LANGUAGES = frozenset({"en", "pl", "mixed", "unknown"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-key", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=("retrieval", "reranking", "scope_nli", "structured_rubric"),
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument(
        "--quantization",
        choices=("none", "bitsandbytes_nf4"),
        default="none",
    )
    return parser


def _read_payload() -> tuple[
    dict[str, dict[str, object]],
    tuple[dict[str, object], ...],
]:
    body = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if not body or len(body) > _MAX_INPUT_BYTES:
        raise ModelEnsembleError("model_stage_input_invalid")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelEnsembleError("model_stage_input_invalid") from None
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "fragments", "cases"
    } or payload["schema_version"] != MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION:
        raise ModelEnsembleError("model_stage_input_invalid")
    raw_fragments = payload["fragments"]
    raw_cases = payload["cases"]
    if (
        not isinstance(raw_fragments, list)
        or not 1 <= len(raw_fragments) <= _MAX_FRAGMENTS
        or not isinstance(raw_cases, list)
        or not 1 <= len(raw_cases) <= _MAX_CASES
    ):
        raise ModelEnsembleError("model_stage_input_invalid")
    fragments: dict[str, dict[str, object]] = {}
    total_characters = 0
    for item in raw_fragments:
        if not isinstance(item, dict) or set(item) != {
            "fragment_id",
            "text",
            "role",
            "kind",
            "language",
            "is_focus_message",
        }:
            raise ModelEnsembleError("model_stage_input_invalid")
        identifier, text = item["fragment_id"], item["text"]
        if (
            not isinstance(identifier, str)
            or _DIGEST.fullmatch(identifier) is None
            or identifier in fragments
            or not isinstance(text, str)
            or not 1 <= len(text) <= 3_500
            or "\x00" in text
            or item["role"] not in _ROLES
            or item["kind"] not in _KINDS
            or item["language"] not in _LANGUAGES
            or not isinstance(item["is_focus_message"], bool)
        ):
            raise ModelEnsembleError("model_stage_input_invalid")
        fragments[identifier] = {
            "text": text,
            "role": item["role"],
            "kind": item["kind"],
            "language": item["language"],
            "is_focus_message": item["is_focus_message"],
        }
        total_characters += len(text)
    if total_characters > 100_000:
        raise ModelEnsembleError("model_stage_input_invalid")
    cases: list[dict[str, object]] = []
    seen_cases: set[str] = set()
    for item in raw_cases:
        if not isinstance(item, dict) or set(item) != {
            "case_id",
            "chunk_ordinal",
            "metric_key",
            "candidate_ids",
            "query",
            "hypothesis",
            "rubric",
        }:
            raise ModelEnsembleError("model_stage_input_invalid")
        case_id = item["case_id"]
        chunk_ordinal = item["chunk_ordinal"]
        metric_key = item["metric_key"]
        candidate_ids = item["candidate_ids"]
        if (
            not isinstance(case_id, str)
            or _DIGEST.fullmatch(case_id) is None
            or case_id in seen_cases
            or isinstance(chunk_ordinal, bool)
            or not isinstance(chunk_ordinal, int)
            or not 0 <= chunk_ordinal < 8
            or not isinstance(metric_key, str)
            or not 1 <= len(metric_key) <= 128
            or not isinstance(candidate_ids, list)
            or not 1 <= len(candidate_ids) <= 128
            or len(candidate_ids) != len(set(candidate_ids))
            or any(identifier not in fragments for identifier in candidate_ids)
            or any(
                not isinstance(item[field], str)
                or not 1 <= len(item[field]) <= limit
                or "\x00" in item[field]
                for field, limit in (
                    ("query", 2_000),
                    ("hypothesis", 2_000),
                    ("rubric", 3_000),
                )
            )
        ):
            raise ModelEnsembleError("model_stage_input_invalid")
        seen_cases.add(case_id)
        cases.append(item)
    return fragments, tuple(cases)


def _retrieval_cases(
    fragments: Mapping[str, Mapping[str, object]],
    cases: Sequence[Mapping[str, object]],
) -> tuple[RetrievalCase, ...]:
    parsed = []
    for item in cases:
        candidates = tuple(
            RetrievalCandidate(
                candidate_id=identifier,
                text=_evidence_text(fragments[identifier]),
            )
            for identifier in item["candidate_ids"]
        )
        parsed.append(
            RetrievalCase(
                language="unknown",
                query=str(item["query"]),
                positive_candidate_id=candidates[0].candidate_id,
                candidates=candidates,
            )
        )
    return tuple(parsed)


def _score_rows(
    cases: Sequence[Mapping[str, object]],
    retrieval: Sequence[RetrievalCase],
    scores: Sequence[Sequence[float]],
) -> list[dict[str, object]]:
    if len(scores) != len(cases):
        raise ModelEnsembleError("model_stage_output_invalid")
    rows = []
    for raw_case, parsed_case, raw_scores in zip(cases, retrieval, scores, strict=True):
        if len(raw_scores) != len(parsed_case.candidates):
            raise ModelEnsembleError("model_stage_output_invalid")
        values = []
        for candidate, score in zip(parsed_case.candidates, raw_scores, strict=True):
            numeric = float(score)
            if not math.isfinite(numeric):
                raise ModelEnsembleError("model_stage_output_invalid")
            values.append(
                {"fragment_id": candidate.candidate_id, "score": round(numeric, 8)}
            )
        rows.append({"case_id": raw_case["case_id"], "scores": values})
    return rows


def _nli_cases(
    fragments: Mapping[str, Mapping[str, object]],
    cases: Sequence[Mapping[str, object]],
) -> tuple[NliCase, ...]:
    return tuple(
        NliCase(
            language="unknown",
            premise="\n".join(
                _evidence_text(fragments[identifier])
                for identifier in item["candidate_ids"]
            ),
            hypothesis=str(item["hypothesis"]),
            expected_label="neutral",
            scope_relation="same_scope",
        )
        for item in cases
    )


def _evidence_text(fragment: Mapping[str, object]) -> str:
    """Preserve allowlisted scope metadata in the ephemeral model input."""

    return (
        "[role="
        f"{fragment['role']} kind={fragment['kind']} "
        f"language={fragment['language']} "
        f"focus={'yes' if fragment['is_focus_message'] else 'no'}]\n"
        f"{fragment['text']}"
    )


# Accelerator allocation failures are not always raised as the typed
# ``torch.OutOfMemoryError``.  Older runtimes, driver paths, and cuBLAS
# workspace allocation surface them as a plain ``RuntimeError`` whose message
# carries one of these fixed markers.  Matching them here is what lets the
# parent classify the stage as ``resource_exhausted`` and retry it on the CPU
# instead of recording an opaque failure.  Only the classification leaves the
# child; the message text itself never does.
_ACCELERATOR_OOM_MARKERS = (
    "cuda out of memory",
    "cuda error: out of memory",
    "cublas_status_alloc_failed",
    "cudaerrormemoryallocation",
    "cuda_error_out_of_memory",
    "hip out of memory",
    "mps backend out of memory",
    "defaultcpuallocator: can't allocate memory",
    "defaultcpuallocator: not enough memory",
)


def _is_accelerator_oom(exc: BaseException) -> bool:
    try:
        import torch

        if isinstance(exc, torch.OutOfMemoryError):
            return True
    except (ImportError, AttributeError):
        pass
    if isinstance(exc, MemoryError):
        return True
    # Restrict text inspection to RuntimeError emitted by known tensor/runtime
    # allocation paths.  The text is used only for this in-child classification
    # and is never copied into the fixed-schema result returned to the parent.
    if type(exc) is RuntimeError:
        try:
            message = str(exc).casefold()
        except Exception:
            return False
        return any(marker in message for marker in _ACCELERATOR_OOM_MARKERS)
    return False


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, TextModelLoadError):
        return "model_cache_missing_or_invalid"
    if isinstance(exc, LocalBackendError):
        value = str(exc)
        return value if value in _SAFE_ERRORS else "model_stage_failed"
    if _is_accelerator_oom(exc):
        return "resource_exhausted"
    return "model_stage_failed"


def run(arguments: argparse.Namespace) -> tuple[int, dict[str, object]]:
    specs = {
        item.identity.model_key: item
        for item in (*ensemble_expert_specs(), *probabilistic_challenger_specs())
    }
    spec = specs.get(arguments.model_key)
    if spec is None or spec.identity.role.value != arguments.stage:
        return 2, {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": arguments.model_key,
            "status": "failed",
            "error_code": "model_stage_failed",
            "device": None,
            "rows": [],
            "runtime": {},
        }
    fragments, cases = _read_payload()
    backend = None
    try:
        with isolated_hugging_face_environment(spec.cache_root), transformers_network_closed():
            snapshot = prepare_model_snapshot(
                spec.manifest,
                cache_root=spec.cache_root,
                allow_download=False,
            )
            backend_type = {
                "multilingual_e5_small": TransformersE5Scorer,
                "multilingual_e5_base": TransformersE5Scorer,
                "bge_m3": TransformersClsEmbeddingScorer,
                "qwen3_embedding_06b": TransformersLastTokenEmbeddingScorer,
                "bge_reranker_v2_m3": TransformersSequenceReranker,
                "qwen3_reranker_06b": TransformersQwenReranker,
                "mdeberta_xnli": TransformersNliClassifier,
                "multilingual_minilmv2_l6_nli": TransformersNliClassifier,
                "multilingual_minilmv2_l12_nli": TransformersNliClassifier,
                "deberta_small_long_nli": TransformersNliClassifier,
                "modernbert_base_zeroshot": TransformersNliClassifier,
                "qwen3_4b_rubric": TransformersDynamicRubricJudge,
            }[spec.identity.model_key]
            if arguments.quantization != "none" and spec.identity.model_key != "qwen3_4b_rubric":
                raise LocalBackendError("unsupported_quantization")
            backend = backend_type(
                spec.manifest,
                snapshot,
                device=arguments.device,
                batch_size=min(8, spec.manifest.max_batch_size),
                quantization=arguments.quantization,
            )
            started = time.perf_counter()
            if arguments.stage in {"retrieval", "reranking"}:
                parsed = _retrieval_cases(fragments, cases)
                rows = _score_rows(cases, parsed, backend.score(parsed))
            elif arguments.stage == "scope_nli":
                parsed = _nli_cases(fragments, cases)
                probabilities = backend.probabilities(parsed)
                rows = [
                    {
                        "case_id": item["case_id"],
                        "entailment": round(float(row["entailment"]), 8),
                        "neutral": round(float(row["neutral"]), 8),
                        "contradiction": round(float(row["contradiction"]), 8),
                    }
                    for item, row in zip(cases, probabilities, strict=True)
                ]
            else:
                dynamic_cases = tuple(
                    (
                        str(item["rubric"]),
                        "\n".join(
                            _evidence_text(fragments[identifier])
                            for identifier in item["candidate_ids"]
                        ),
                    )
                    for item in cases
                )
                predictions = backend.predict_dynamic(dynamic_cases)
                rows = [
                    {
                        "case_id": item["case_id"],
                        "label": prediction.label if prediction.json_valid else "abstain",
                    }
                    for item, prediction in zip(cases, predictions, strict=True)
                ]
            inference_latency = (time.perf_counter() - started) * 1000
            runtime = backend.runtime_observation()
            runtime["inference_latency_ms"] = round(inference_latency, 3)
            device = backend.device
        return 0, {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "completed",
            "error_code": None,
            "device": device,
            "rows": rows,
            "runtime": runtime,
        }
    except Exception as exc:
        return 2, {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "failed",
            "error_code": _safe_error(exc),
            "device": None,
            "rows": [],
            "runtime": {},
        }
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass
            del backend
            gc.collect()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        exit_code, report = run(arguments)
    except Exception:
        exit_code = 2
        report = {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": arguments.model_key,
            "status": "failed",
            "error_code": "model_stage_failed",
            "device": None,
            "rows": [],
            "runtime": {},
        }
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
