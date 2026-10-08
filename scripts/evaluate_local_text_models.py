"""Evaluate pinned local model candidates on fictional EN/PL cases only.

The evaluator never accepts a provider/session path or arbitrary corpus. Public
downloads require ``--download``; verified inference is then forced offline.
Only aggregate measurements and immutable public model pins are printed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Callable, Sequence


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
_CORPUS = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_model_screen_v1.json"
)
_RUBRIC_CORPUS = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_rubric_screen_v1.json"
)
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.infrastructure.text_models.benchmark import (
    LexicalBm25Scorer,
    corpus_public_summary,
    evaluate_nli,
    evaluate_retrieval,
    evaluate_rubric,
    load_synthetic_corpus,
    load_synthetic_rubric_corpus,
    rubric_corpus_public_summary,
)
from prompt_enhancer.infrastructure.text_models.loader import (
    TextModelLoadError,
    isolated_hugging_face_environment,
    model_eval_cache_root,
    prepare_model_snapshot,
    transformers_network_closed,
)
from prompt_enhancer.infrastructure.text_models.manifests import (
    BGE_M3,
    BGE_RERANKER_V2_M3,
    E5_MULTILINGUAL_BASE,
    E5_MULTILINGUAL_SMALL,
    MDEBERTA_XNLI,
    QWEN3_4B_RUBRIC,
    QWEN3_EMBEDDING_06B,
    QWEN3_RERANKER_06B,
    ModelManifest,
)
from prompt_enhancer.infrastructure.text_models.transformers_backends import (
    LocalBackendError,
    TransformersClsEmbeddingScorer,
    TransformersE5Scorer,
    TransformersLastTokenEmbeddingScorer,
    TransformersNliClassifier,
    TransformersQwenReranker,
    TransformersSequenceReranker,
    TransformersStructuredRubricJudge,
    resolve_device,
)


_CANDIDATE_KEYS = (
    "session-link",
    "e5",
    "e5-base",
    "nli",
    "bge-m3",
    "bge-reranker",
    "qwen-embedding",
    "qwen-reranker",
    "qwen-rubric",
)
_SAFE_ERROR_CODES = {
    "batch_size_outside_manifest_bound",
    "cuda_unavailable",
    "mps_unavailable",
    "resource_exhausted",
    "evaluation_failed",
    "model_cache_missing_or_invalid",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Screen pinned local text models on fictional EN/PL cases."
    )
    parser.add_argument(
        "--candidate",
        choices=("all", *_CANDIDATE_KEYS),
        default="all",
        help="Candidate subset; transparent lexical retrieval always runs.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use bilingual, label-balanced subsets before the full screen.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Explicitly allow only immutable public artifacts in the manifests.",
    )
    return parser


def _selected(arguments: argparse.Namespace, key: str) -> bool:
    return arguments.candidate in {"all", key} or (
        arguments.candidate == "session-link"
        and key in {"qwen-embedding", "bge-reranker"}
    )


def _empty_report(arguments: argparse.Namespace, resolved_device: str) -> dict[str, object]:
    corpus = load_synthetic_corpus(_CORPUS)
    rubric = load_synthetic_rubric_corpus(_RUBRIC_CORPUS)
    if arguments.smoke:
        corpus = corpus.smoke_subset()
        rubric = rubric.smoke_subset()
    lexical = evaluate_retrieval(
        corpus.retrieval_cases,
        LexicalBm25Scorer(),
        backend_key=LexicalBm25Scorer.key,
    )
    return {
        "report_schema_version": 2,
        "status": "running",
        "evaluation_scope": "synthetic_exploratory_only",
        "interpretation": (
            "candidate screening only; no model output is activated as a product metric"
        ),
        "calibration_requirement": (
            "private project-stratified, rater-adjudicated and time-separated holdout remains mandatory"
        ),
        "mode": "smoke" if arguments.smoke else "full",
        "network_download_explicit": bool(arguments.download),
        "device": resolved_device,
        "corpus": corpus_public_summary(corpus),
        "rubric_corpus": rubric_corpus_public_summary(rubric),
        "model_pins": [],
        "blocked_candidates": [],
        "candidate_outcomes": [],
        "retrieval": [lexical],
        "reranking": [],
        "nli": [],
        "rubric": [],
        "limitations": [
            "small fictional bilingual corpus",
            "latency and memory are single-run local observations",
            "synthetic agreement is not real-session calibration",
            "no result may be used for developer ranking or a universal quality score",
        ],
        "error_code": None,
    }


def _safe_failure_code(exc: BaseException) -> str:
    if isinstance(exc, (TextModelLoadError,)):
        return "model_cache_missing_or_invalid"
    if isinstance(exc, LocalBackendError):
        code = str(exc)
        return code if code in _SAFE_ERROR_CODES else "evaluation_failed"
    try:
        import torch

        if isinstance(exc, torch.OutOfMemoryError):
            return "resource_exhausted"
    except ImportError:
        pass
    return "evaluation_failed"


def _append_outcome(
    report: dict[str, object],
    *,
    key: str,
    status: str,
    error_code: str | None = None,
) -> None:
    outcomes = report["candidate_outcomes"]
    assert isinstance(outcomes, list)
    outcomes.append({"key": key, "status": status, "error_code": error_code})


def _evaluate_backend(
    *,
    arguments: argparse.Namespace,
    report: dict[str, object],
    manifest: ModelManifest,
    backend_factory: Callable[..., object],
    evaluator: Callable[..., dict[str, object]],
    cases: Sequence[object],
    report_bucket: str,
    backend_key: str,
    baseline: dict[str, object] | None = None,
) -> bool:
    pins = report["model_pins"]
    assert isinstance(pins, list)
    pins.append(manifest.public_pin())
    backend = None
    try:
        snapshot = prepare_model_snapshot(
            manifest,
            cache_root=model_eval_cache_root(),
            allow_download=arguments.download,
        )
        with transformers_network_closed():
            backend = backend_factory(
                manifest,
                snapshot,
                device=report["device"],
                batch_size=min(arguments.batch_size, manifest.max_batch_size),
            )
            result = evaluator(cases, backend, backend_key=backend_key)
            if baseline is not None:
                result["delta_vs_lexical_top1"] = round(
                    float(result["top1_accuracy"]) - float(baseline["top1_accuracy"]),
                    6,
                )
                result["delta_vs_lexical_mrr"] = round(
                    float(result["mean_reciprocal_rank"])
                    - float(baseline["mean_reciprocal_rank"]),
                    6,
                )
            result["runtime"] = backend.runtime_observation()  # type: ignore[attr-defined]
            bucket = report[report_bucket]
            assert isinstance(bucket, list)
            bucket.append(result)
        _append_outcome(report, key=manifest.key, status="evaluated")
        return True
    except Exception as exc:
        code = _safe_failure_code(exc)
        _append_outcome(report, key=manifest.key, status="not_completed", error_code=code)
        return False
    finally:
        if backend is not None:
            try:
                backend.close()  # type: ignore[attr-defined]
            except Exception:
                pass


def run(arguments: argparse.Namespace) -> tuple[int, dict[str, object]]:
    resolved_device = resolve_device(arguments.device)
    report = _empty_report(arguments, resolved_device)
    if not 1 <= arguments.batch_size <= 32:
        report["status"] = "not_completed"
        report["error_code"] = "batch_size_outside_manifest_bound"
        return 2, report

    corpus = load_synthetic_corpus(_CORPUS)
    rubric = load_synthetic_rubric_corpus(_RUBRIC_CORPUS)
    if arguments.smoke:
        corpus = corpus.smoke_subset()
        rubric = rubric.smoke_subset()
    lexical = report["retrieval"][0]  # type: ignore[index]
    completed = True

    if _selected(arguments, "bge-m3"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=BGE_M3,
            backend_factory=TransformersClsEmbeddingScorer,
            evaluator=evaluate_retrieval,
            cases=corpus.retrieval_cases,
            report_bucket="retrieval",
            backend_key=TransformersClsEmbeddingScorer.key,
            baseline=lexical,
        )

    if _selected(arguments, "e5"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=E5_MULTILINGUAL_SMALL,
            backend_factory=TransformersE5Scorer,
            evaluator=evaluate_retrieval,
            cases=corpus.retrieval_cases,
            report_bucket="retrieval",
            backend_key=TransformersE5Scorer.key,
            baseline=lexical,
        )
    if _selected(arguments, "e5-base"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=E5_MULTILINGUAL_BASE,
            backend_factory=TransformersE5Scorer,
            evaluator=evaluate_retrieval,
            cases=corpus.retrieval_cases,
            report_bucket="retrieval",
            backend_key="multilingual_e5_base_cosine_v1",
            baseline=lexical,
        )
    if _selected(arguments, "qwen-embedding"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=QWEN3_EMBEDDING_06B,
            backend_factory=TransformersLastTokenEmbeddingScorer,
            evaluator=evaluate_retrieval,
            cases=corpus.retrieval_cases,
            report_bucket="retrieval",
            backend_key=TransformersLastTokenEmbeddingScorer.key,
            baseline=lexical,
        )
    if _selected(arguments, "bge-reranker"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=BGE_RERANKER_V2_M3,
            backend_factory=TransformersSequenceReranker,
            evaluator=evaluate_retrieval,
            cases=corpus.retrieval_cases,
            report_bucket="reranking",
            backend_key=TransformersSequenceReranker.key,
            baseline=lexical,
        )
    if _selected(arguments, "qwen-reranker"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=QWEN3_RERANKER_06B,
            backend_factory=TransformersQwenReranker,
            evaluator=evaluate_retrieval,
            cases=corpus.retrieval_cases,
            report_bucket="reranking",
            backend_key=TransformersQwenReranker.key,
            baseline=lexical,
        )
    if _selected(arguments, "nli"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=MDEBERTA_XNLI,
            backend_factory=TransformersNliClassifier,
            evaluator=evaluate_nli,
            cases=corpus.nli_cases,
            report_bucket="nli",
            backend_key=TransformersNliClassifier.key,
        )
    if _selected(arguments, "qwen-rubric"):
        completed &= _evaluate_backend(
            arguments=arguments,
            report=report,
            manifest=QWEN3_4B_RUBRIC,
            backend_factory=TransformersStructuredRubricJudge,
            evaluator=evaluate_rubric,
            cases=rubric.cases,
            report_bucket="rubric",
            backend_key=TransformersStructuredRubricJudge.key,
        )

    report["status"] = "completed" if completed else "completed_with_failures"
    if not completed:
        report["error_code"] = "candidate_evaluation_incomplete"
    return (0 if completed else 2), report


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    arguments = _parser().parse_args(argv)
    try:
        with isolated_hugging_face_environment(model_eval_cache_root()):
            exit_code, report = run(arguments)
    except (TextModelLoadError, LocalBackendError) as exc:
        try:
            report
        except UnboundLocalError:
            report = _empty_report(arguments, "unavailable")
        report["status"] = "not_completed"
        report["error_code"] = _safe_failure_code(exc)
        exit_code = 2
    except Exception:
        try:
            report
        except UnboundLocalError:
            report = _empty_report(arguments, "unavailable")
        report["status"] = "not_completed"
        report["error_code"] = "evaluation_failed"
        exit_code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
