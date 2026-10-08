"""Aggregate-only evaluation for the synthetic scoped-NLI specialist screen."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from importlib import metadata
import hashlib
import json
import math
from pathlib import Path
import platform
import re
from typing import Protocol

from prompt_enhancer.infrastructure.text_models.loader import (
    TextModelLoadError,
    isolated_hugging_face_environment,
)
from prompt_enhancer.infrastructure.text_models.manifests import ModelManifest

from .backends import MiniLmV2NliBackend, SpecialistBackendError
from .contracts import (
    SPECIALIST_LABEL_ORDER,
    SpecialistAbstentionReason,
    SpecialistCase,
    SpecialistCompatibility,
    SpecialistCorpus,
    SpecialistLabel,
    SpecialistOutcome,
    SpecialistPrediction,
    SpecialistPredictionState,
    SpecialistTaskStratum,
)
from .loader import prepare_specialist_snapshot, specialist_cache_root
from .manifests import (
    MDEBERTA_HISTORICAL_REJECTION,
    SPECIALIST_MODEL_MANIFESTS,
)


_SAFE_BACKEND_KEY = re.compile(r"[a-z][a-z0-9_]{2,95}\Z")
_CASE_FIELDS = frozenset(
    {
        "language",
        "task_stratum",
        "premise",
        "hypothesis",
        "compatibility",
        "expected_outcome",
        "critical_claim",
    }
)
_CORPUS_FIELDS = frozenset(
    {"schema_version", "benchmark_id", "synthetic_only", "cases"}
)

SPECIALIST_CORPUS_SHA256 = (
    "facf05495e48966684446426157c423ebe661387c7a50860e43cc8d663943703"
)
SPECIALIST_EVALUATOR_VERSION = "specialist-foundation-evaluator-v2"
SPECIALIST_METRIC_DEFINITION_VERSION = "specialist-foundation-metrics-v2"


class SpecialistCorpusError(ValueError):
    pass


class SpecialistProbabilityBackend(Protocol):
    def predict_probabilities(
        self,
        cases: Sequence[SpecialistCase],
    ) -> tuple[tuple[tuple[SpecialistLabel, float], ...], ...]: ...


def runtime_dependency_provenance() -> dict[str, str | None]:
    """Return package versions only; never environment or install paths."""

    def version(distribution: str) -> str | None:
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:
            return None

    return {
        "python": platform.python_version(),
        "huggingface_hub": version("huggingface-hub"),
        "safetensors": version("safetensors"),
        "sentencepiece": version("sentencepiece"),
        "torch": version("torch"),
        "transformers": version("transformers"),
    }


def load_specialist_corpus(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> SpecialistCorpus:
    """Load a strict fictional corpus without tolerating extension fields."""

    try:
        fixture_bytes = path.read_bytes()
        fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
        if expected_sha256 is not None and fixture_sha256 != expected_sha256:
            raise SpecialistCorpusError("specialist_corpus_sha256_mismatch")
        raw = json.loads(fixture_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SpecialistCorpusError("specialist_corpus_unreadable") from None
    if not isinstance(raw, dict) or set(raw) != _CORPUS_FIELDS:
        raise SpecialistCorpusError("specialist_corpus_invalid_fields")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list):
        raise SpecialistCorpusError("specialist_cases_must_be_a_list")
    cases: list[SpecialistCase] = []
    try:
        for raw_case in raw_cases:
            if not isinstance(raw_case, dict) or set(raw_case) != _CASE_FIELDS:
                raise SpecialistCorpusError("specialist_case_invalid_fields")
            cases.append(
                SpecialistCase(
                    language=raw_case["language"],
                    task_stratum=SpecialistTaskStratum(raw_case["task_stratum"]),
                    premise=raw_case["premise"],
                    hypothesis=raw_case["hypothesis"],
                    compatibility=SpecialistCompatibility(
                        raw_case["compatibility"]
                    ),
                    expected_outcome=SpecialistOutcome(
                        raw_case["expected_outcome"]
                    ),
                    critical_claim=raw_case["critical_claim"],
                )
            )
        return SpecialistCorpus(
            schema_version=raw["schema_version"],
            benchmark_id=raw["benchmark_id"],
            synthetic_only=raw["synthetic_only"],
            source_fixture_sha256=fixture_sha256,
            cases=tuple(cases),
        )
    except SpecialistCorpusError:
        raise
    except (KeyError, TypeError, ValueError):
        raise SpecialistCorpusError("specialist_corpus_contract_failed") from None


def corpus_public_summary(corpus: SpecialistCorpus) -> dict[str, object]:
    return {
        "schema_version": corpus.schema_version,
        "benchmark_id": corpus.benchmark_id,
        "synthetic_only": True,
        "source_fixture_sha256": corpus.source_fixture_sha256,
        "case_count": len(corpus.cases),
        "languages": sorted({case.language for case in corpus.cases}),
        "outcome_counts": dict(
            sorted(Counter(case.expected_outcome.value for case in corpus.cases).items())
        ),
        "compatibility_counts": dict(
            sorted(Counter(case.compatibility.value for case in corpus.cases).items())
        ),
        "task_stratum_counts": dict(
            sorted(Counter(case.task_stratum.value for case in corpus.cases).items())
        ),
        "critical_claim_count": sum(case.critical_claim for case in corpus.cases),
    }


class DeterministicAbstainingSpecialist:
    """Honest baseline: text alone cannot prove an objective metric claim."""

    key = "deterministic_objective_evidence_abstainer_v1"

    def predict(
        self,
        cases: Sequence[SpecialistCase],
    ) -> tuple[SpecialistPrediction, ...]:
        return tuple(
            SpecialistPrediction(
                state=SpecialistPredictionState.ABSTAINED,
                abstention_reason=(
                    SpecialistAbstentionReason.BASELINE_REQUIRES_OBJECTIVE_EVIDENCE
                ),
            )
            for _ in cases
        )


class OracleGatedNliSpecialist:
    """Plumb authored compatibility metadata into confidence-gated NLI.

    This is deliberately an oracle gate for the bounded synthetic foundation
    screen.  It does not predict compatibility and therefore cannot evaluate a
    real deterministic scope router.
    """

    compatibility_gate_version = "synthetic_oracle_compatibility_gate_v1"
    routing_mode = "oracle_fixture_compatibility_labels"
    router_evaluated = False
    calibration_version = "uncalibrated_synthetic_threshold_v1"

    def __init__(
        self,
        backend: SpecialistProbabilityBackend,
        *,
        confidence_threshold: float,
    ) -> None:
        if not 0.5 <= confidence_threshold <= 0.99:
            raise ValueError("specialist confidence threshold is outside reviewed bounds")
        self.backend = backend
        self.confidence_threshold = confidence_threshold

    def predict(
        self,
        cases: Sequence[SpecialistCase],
    ) -> tuple[SpecialistPrediction, ...]:
        compatible_positions = [
            index
            for index, case in enumerate(cases)
            if case.compatibility is SpecialistCompatibility.COMPATIBLE
        ]
        compatible_cases = tuple(cases[index] for index in compatible_positions)
        probability_rows = self.backend.predict_probabilities(compatible_cases)
        if len(probability_rows) != len(compatible_cases):
            raise SpecialistBackendError("specialist_prediction_count_mismatch")
        by_position = dict(zip(compatible_positions, probability_rows, strict=True))

        results: list[SpecialistPrediction] = []
        for position, case in enumerate(cases):
            if case.compatibility is not SpecialistCompatibility.COMPATIBLE:
                reason = {
                    SpecialistCompatibility.DIFFERENT_SCOPE: (
                        SpecialistAbstentionReason.DIFFERENT_SCOPE
                    ),
                    SpecialistCompatibility.SUPERSEDED: (
                        SpecialistAbstentionReason.SUPERSEDED
                    ),
                    SpecialistCompatibility.INSUFFICIENT_EVIDENCE: (
                        SpecialistAbstentionReason.INSUFFICIENT_EVIDENCE
                    ),
                }[case.compatibility]
                results.append(
                    SpecialistPrediction(
                        state=SpecialistPredictionState.ABSTAINED,
                        abstention_reason=reason,
                    )
                )
                continue

            probabilities = by_position[position]
            raw_label, confidence = max(probabilities, key=lambda item: item[1])
            if confidence < self.confidence_threshold:
                results.append(
                    SpecialistPrediction(
                        state=SpecialistPredictionState.ABSTAINED,
                        probabilities=probabilities,
                        abstention_reason=SpecialistAbstentionReason.LOW_CONFIDENCE,
                    )
                )
            else:
                results.append(
                    SpecialistPrediction(
                        state=SpecialistPredictionState.KNOWN,
                        label=raw_label,
                        probabilities=probabilities,
                    )
                )
        return tuple(results)


def _predicted_outcome(prediction: SpecialistPrediction) -> SpecialistOutcome:
    if prediction.state is SpecialistPredictionState.ABSTAINED:
        return SpecialistOutcome.ABSTAIN
    assert prediction.label is not None
    return SpecialistOutcome(prediction.label.value)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _classification_metrics(
    cases: Sequence[SpecialistCase],
    predictions: Sequence[SpecialistPrediction],
) -> dict[str, object]:
    known_count = sum(
        prediction.state is SpecialistPredictionState.KNOWN
        for prediction in predictions
    )
    correct_count = sum(
        _predicted_outcome(prediction) is case.expected_outcome
        for case, prediction in zip(cases, predictions, strict=True)
    )
    known_correct = sum(
        prediction.state is SpecialistPredictionState.KNOWN
        and _predicted_outcome(prediction) is case.expected_outcome
        for case, prediction in zip(cases, predictions, strict=True)
    )

    per_label: dict[str, dict[str, float | int | None]] = {}
    label_f1_values: list[float] = []
    for label in SPECIALIST_LABEL_ORDER:
        outcome = SpecialistOutcome(label.value)
        true_positive = sum(
            case.expected_outcome is outcome
            and _predicted_outcome(prediction) is outcome
            for case, prediction in zip(cases, predictions, strict=True)
        )
        false_positive = sum(
            case.expected_outcome is not outcome
            and _predicted_outcome(prediction) is outcome
            for case, prediction in zip(cases, predictions, strict=True)
        )
        false_negative = sum(
            case.expected_outcome is outcome
            and _predicted_outcome(prediction) is not outcome
            for case, prediction in zip(cases, predictions, strict=True)
        )
        support = true_positive + false_negative
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, support)
        if true_positive == 0:
            f1 = 0.0
        else:
            f1 = round(
                2 * true_positive / (2 * true_positive + false_positive + false_negative),
                6,
            )
        label_f1_values.append(f1)
        per_label[label.value] = {
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    expected_abstain = sum(
        case.expected_outcome is SpecialistOutcome.ABSTAIN for case in cases
    )
    predicted_abstain = len(cases) - known_count
    correct_abstain = sum(
        case.expected_outcome is SpecialistOutcome.ABSTAIN
        and prediction.state is SpecialistPredictionState.ABSTAINED
        for case, prediction in zip(cases, predictions, strict=True)
    )
    return {
        "case_count": len(cases),
        "known_count": known_count,
        "coverage": _ratio(known_count, len(cases)),
        "overall_typed_accuracy": _ratio(correct_count, len(cases)),
        "selective_accuracy": _ratio(known_correct, known_count),
        "selective_risk": (
            round(1.0 - known_correct / known_count, 6) if known_count else None
        ),
        "three_way_macro_f1": round(
            sum(label_f1_values) / len(label_f1_values), 6
        ),
        "per_label": per_label,
        "abstention_precision": _ratio(correct_abstain, predicted_abstain),
        "abstention_recall": _ratio(correct_abstain, expected_abstain),
    }


def _probability_metrics(
    cases: Sequence[SpecialistCase],
    predictions: Sequence[SpecialistPrediction],
) -> dict[str, object]:
    evaluated: list[
        tuple[SpecialistOutcome, SpecialistPrediction]
    ] = [
        (case.expected_outcome, prediction)
        for case, prediction in zip(cases, predictions, strict=True)
        if case.compatibility is SpecialistCompatibility.COMPATIBLE
        and prediction.probabilities
    ]
    if not evaluated:
        return {
            "probability_case_count": 0,
            "multiclass_brier_score": None,
            "log_loss": None,
            "expected_calibration_error_10_bin": None,
            "false_confident_error_rate_at_0_9": None,
        }

    brier_total = 0.0
    log_loss_total = 0.0
    confidence_correct: list[tuple[float, bool]] = []
    false_confident = 0
    for expected, prediction in evaluated:
        probabilities = dict(prediction.probabilities)
        expected_label = SpecialistLabel(expected.value)
        brier_total += sum(
            (probabilities[label] - (1.0 if label is expected_label else 0.0)) ** 2
            for label in SPECIALIST_LABEL_ORDER
        )
        log_loss_total += -math.log(max(probabilities[expected_label], 1e-15))
        raw_label = prediction.raw_label
        confidence = prediction.confidence
        assert raw_label is not None and confidence is not None
        correct = raw_label is expected_label
        confidence_correct.append((confidence, correct))
        if confidence >= 0.9 and not correct:
            false_confident += 1

    ece = 0.0
    for bin_index in range(10):
        lower = bin_index / 10
        upper = (bin_index + 1) / 10
        members = [
            (confidence, correct)
            for confidence, correct in confidence_correct
            if lower <= confidence <= upper
            and (confidence < upper or bin_index == 9)
        ]
        if not members:
            continue
        mean_confidence = sum(value for value, _ in members) / len(members)
        mean_accuracy = sum(correct for _, correct in members) / len(members)
        ece += len(members) / len(evaluated) * abs(mean_accuracy - mean_confidence)

    return {
        "probability_case_count": len(evaluated),
        "multiclass_brier_score": round(brier_total / len(evaluated), 6),
        "log_loss": round(log_loss_total / len(evaluated), 6),
        "expected_calibration_error_10_bin": round(ece, 6),
        "false_confident_error_rate_at_0_9": _ratio(
            false_confident,
            len(evaluated),
        ),
    }


def evaluate_specialist_predictions(
    cases: Sequence[SpecialistCase],
    predictions: Sequence[SpecialistPrediction],
    *,
    backend_key: str,
) -> dict[str, object]:
    if _SAFE_BACKEND_KEY.fullmatch(backend_key) is None:
        raise ValueError("specialist backend key must be safe and stable")
    if len(cases) != len(predictions) or not cases:
        raise ValueError("specialist prediction count must match non-empty cases")

    compatible_pairs = [
        (case, prediction)
        for case, prediction in zip(cases, predictions, strict=True)
        if case.compatibility is SpecialistCompatibility.COMPATIBLE
    ]
    compatible_cases = [case for case, _ in compatible_pairs]
    compatible_predictions = [prediction for _, prediction in compatible_pairs]
    oracle_withheld_count = len(cases) - len(compatible_cases)
    confusion = {
        expected.value: {predicted.value: 0 for predicted in SpecialistOutcome}
        for expected in SpecialistOutcome
    }
    for case, prediction in compatible_pairs:
        confusion[case.expected_outcome.value][_predicted_outcome(prediction).value] += 1

    report: dict[str, object] = {
        "backend_key": backend_key,
        "synthetic_only": True,
        "evaluator_version": SPECIALIST_EVALUATOR_VERSION,
        "metric_definition_version": SPECIALIST_METRIC_DEFINITION_VERSION,
        "routing_mode": "oracle_fixture_compatibility_labels",
        "router_evaluated": False,
        "router_metrics": {
            "state": "not_evaluated",
            "incompatible_known_rate": None,
            "different_scope_contradiction_false_positive_rate": None,
        },
        "corpus_case_count": len(cases),
        "oracle_withheld_count": oracle_withheld_count,
        "evaluated_nli_case_count": len(compatible_cases),
        "activation_allowed": False,
        "promotion_allowed": False,
        **_classification_metrics(compatible_cases, compatible_predictions),
        **_probability_metrics(compatible_cases, compatible_predictions),
        "confusion_matrix": confusion,
        "language_slices": {
            language: _classification_metrics(
                [case for case in compatible_cases if case.language == language],
                [
                    prediction
                    for case, prediction in compatible_pairs
                    if case.language == language
                ],
            )
            for language in ("en", "pl")
        },
        "task_stratum_slices": {
            stratum.value: _classification_metrics(
                [case for case in compatible_cases if case.task_stratum is stratum],
                [
                    prediction
                    for case, prediction in compatible_pairs
                    if case.task_stratum is stratum
                ],
            )
            for stratum in SpecialistTaskStratum
        },
    }
    return report


def run_specialist_candidate(
    corpus: SpecialistCorpus,
    manifest: ModelManifest,
    *,
    cache_root: Path | None = None,
    allow_public_download: bool = False,
    device: str = "auto",
    batch_size: int = 8,
    confidence_threshold: float = 0.7,
) -> dict[str, object]:
    public = {
        "candidate": manifest.public_pin(),
        "synthetic_only": True,
        "screen_tier": "bounded_foundation_pre_screen",
        "evaluator_version": SPECIALIST_EVALUATOR_VERSION,
        "metric_definition_version": SPECIALIST_METRIC_DEFINITION_VERSION,
        "routing_mode": "oracle_fixture_compatibility_labels",
        "router_evaluated": False,
        "activation_allowed": False,
        "promotion_allowed": False,
        "compatibility_gate_version": (
            OracleGatedNliSpecialist.compatibility_gate_version
        ),
        "calibration_version": OracleGatedNliSpecialist.calibration_version,
        "confidence_threshold": confidence_threshold,
    }
    try:
        prepared = prepare_specialist_snapshot(
            manifest,
            cache_root=cache_root,
            allow_public_download=allow_public_download,
        )
    except TextModelLoadError:
        return {
            **public,
            "status": "unavailable",
            "failure_code": "model_cache_missing_or_invalid",
            "metrics": None,
            "runtime": None,
        }
    except Exception:
        return {
            **public,
            "status": "failed",
            "failure_code": "model_preflight_failed",
            "metrics": None,
            "runtime": None,
        }

    try:
        with isolated_hugging_face_environment(
            cache_root or specialist_cache_root()
        ):
            with MiniLmV2NliBackend(
                manifest,
                prepared.snapshot,
                device=device,
                batch_size=batch_size,
            ) as backend:
                specialist = OracleGatedNliSpecialist(
                    backend,
                    confidence_threshold=confidence_threshold,
                )
                predictions = specialist.predict(corpus.cases)
                metrics = evaluate_specialist_predictions(
                    corpus.cases,
                    predictions,
                    backend_key=f"{manifest.key}_scoped_nli_v1",
                )
                runtime = backend.runtime_observation()
        return {
            **public,
            "status": "completed",
            "failure_code": None,
            "metrics": metrics,
            "runtime": runtime,
        }
    except (SpecialistBackendError, TextModelLoadError):
        return {
            **public,
            "status": "failed",
            "failure_code": "model_execution_failed",
            "metrics": None,
            "runtime": None,
        }


def run_specialist_screen(
    corpus: SpecialistCorpus,
    *,
    cache_root: Path | None = None,
    allow_public_download: bool = False,
    device: str = "auto",
    batch_size: int = 8,
    confidence_threshold: float = 0.7,
) -> dict[str, object]:
    """Run the baseline and candidates serially, never as activation evidence."""

    baseline = DeterministicAbstainingSpecialist()
    baseline_metrics = evaluate_specialist_predictions(
        corpus.cases,
        baseline.predict(corpus.cases),
        backend_key=baseline.key,
    )
    candidates = [
        run_specialist_candidate(
            corpus,
            manifest,
            cache_root=cache_root,
            allow_public_download=allow_public_download,
            device=device,
            batch_size=batch_size,
            confidence_threshold=confidence_threshold,
        )
        for manifest in SPECIALIST_MODEL_MANIFESTS.values()
    ]
    return {
        "contract": "synthetic-specialist-screen-v1",
        "synthetic_only": True,
        "scope": "fictional_en_pl_scoped_nli",
        "screen_tier": "bounded_foundation_pre_screen",
        "evaluator_version": SPECIALIST_EVALUATOR_VERSION,
        "metric_definition_version": SPECIALIST_METRIC_DEFINITION_VERSION,
        "routing_mode": "oracle_fixture_compatibility_labels",
        "router_evaluated": False,
        "promotion_screen_minimum_case_count": 96,
        "promotion_screen_gate_met": False,
        "serialized_execution": True,
        "runtime_dependencies": runtime_dependency_provenance(),
        "activation_allowed": False,
        "promotion_allowed": False,
        "corpus": corpus_public_summary(corpus),
        "baseline": {
            "status": "completed",
            "metrics": baseline_metrics,
        },
        "candidates": candidates,
        "historical_rejections": [
            MDEBERTA_HISTORICAL_REJECTION.public_record()
        ],
        "omitted_candidate_families": [
            "bge_zero_shot",
            "qwen_structured_rubric",
        ],
    }
