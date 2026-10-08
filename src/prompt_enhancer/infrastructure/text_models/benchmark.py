"""Synthetic bilingual screening benchmark for optional local text models."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import re
import time
from typing import Protocol


_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_LANGUAGES = frozenset({"en", "pl"})
_NLI_LABELS = frozenset({"entailment", "neutral", "contradiction"})
_SCOPE_RELATIONS = frozenset({"same_scope", "different_scope"})
_MAX_TEXT_CHARACTERS = 768
_MAX_RETRIEVAL_CASES = 64
_MAX_NLI_CASES = 96
_MAX_CANDIDATES = 8
_RUBRIC_LABELS = frozenset({"present", "absent", "abstain"})
_RUBRIC_KEYS = frozenset(
    {
        "task_definition",
        "constraint_precision",
        "acceptance_testability",
        "deliverable_contract",
    }
)
_MAX_RUBRIC_CASES = 96


class SyntheticCorpusError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    candidate_id: str
    text: str


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    language: str
    query: str
    positive_candidate_id: str
    candidates: tuple[RetrievalCandidate, ...]


@dataclass(frozen=True, slots=True)
class NliCase:
    language: str
    premise: str
    hypothesis: str
    expected_label: str
    scope_relation: str


@dataclass(frozen=True, slots=True)
class RubricCase:
    case_id: str
    language: str
    rubric_key: str
    text: str
    expected_label: str


@dataclass(frozen=True, slots=True)
class RubricPrediction:
    label: str | None
    json_valid: bool


@dataclass(frozen=True, slots=True)
class SyntheticRubricCorpus:
    schema_version: int
    benchmark_id: str
    cases: tuple[RubricCase, ...]

    def smoke_subset(self) -> "SyntheticRubricCorpus":
        selected: list[RubricCase] = []
        labels = ("present", "absent", "abstain", "present")
        for language in sorted(_LANGUAGES):
            for index, rubric_key in enumerate(sorted(_RUBRIC_KEYS)):
                selected.append(
                    next(
                        case
                        for case in self.cases
                        if case.language == language
                        and case.rubric_key == rubric_key
                        and case.expected_label == labels[index]
                    )
                )
        return replace(self, cases=tuple(selected))


@dataclass(frozen=True, slots=True)
class SyntheticTextModelCorpus:
    schema_version: int
    benchmark_id: str
    retrieval_cases: tuple[RetrievalCase, ...]
    nli_cases: tuple[NliCase, ...]

    def smoke_subset(self) -> "SyntheticTextModelCorpus":
        """Keep both languages and all NLI labels in a fast smoke run."""

        retrieval = _balanced_prefix(self.retrieval_cases, per_language=2)
        nli: list[NliCase] = []
        for language in sorted(_LANGUAGES):
            by_label: dict[str, NliCase] = {}
            for case in self.nli_cases:
                if case.language == language and case.expected_label not in by_label:
                    by_label[case.expected_label] = case
            nli.extend(by_label[label] for label in sorted(_NLI_LABELS))
        return replace(self, retrieval_cases=tuple(retrieval), nli_cases=tuple(nli))


def _balanced_prefix(
    cases: Sequence[RetrievalCase],
    *,
    per_language: int,
) -> tuple[RetrievalCase, ...]:
    selected: list[RetrievalCase] = []
    for language in sorted(_LANGUAGES):
        selected.extend(
            [case for case in cases if case.language == language][:per_language]
        )
    return tuple(selected)


def _exact_keys(value: dict[str, object], expected: frozenset[str], at: str) -> None:
    if set(value) != expected:
        raise SyntheticCorpusError(f"invalid fields at {at}")


def _safe_id(value: object, at: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise SyntheticCorpusError(f"invalid identifier at {at}")
    return value


def _bounded_text(value: object, at: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyntheticCorpusError(f"missing text at {at}")
    if len(value) > _MAX_TEXT_CHARACTERS or "\x00" in value:
        raise SyntheticCorpusError(f"text bound exceeded at {at}")
    return value


def load_synthetic_corpus(path: Path) -> SyntheticTextModelCorpus:
    """Load the one checked-in synthetic schema without accepting extra fields."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SyntheticCorpusError("corpus root must be an object")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "benchmark_id",
                "synthetic_only",
                "retrieval_cases",
                "nli_cases",
            }
        ),
        "root",
    )
    if payload["schema_version"] != 1 or payload["synthetic_only"] is not True:
        raise SyntheticCorpusError("unsupported or non-synthetic corpus")
    benchmark_id = _safe_id(payload["benchmark_id"], "benchmark_id")

    raw_retrieval = payload["retrieval_cases"]
    if not isinstance(raw_retrieval, list) or not 1 <= len(raw_retrieval) <= _MAX_RETRIEVAL_CASES:
        raise SyntheticCorpusError("retrieval case count outside bounds")
    retrieval: list[RetrievalCase] = []
    for case_index, raw_case in enumerate(raw_retrieval):
        if not isinstance(raw_case, dict):
            raise SyntheticCorpusError("retrieval case must be an object")
        _exact_keys(
            raw_case,
            frozenset({"language", "query", "positive_candidate_id", "candidates"}),
            f"retrieval[{case_index}]",
        )
        language = raw_case["language"]
        if language not in _LANGUAGES:
            raise SyntheticCorpusError("unsupported retrieval language")
        raw_candidates = raw_case["candidates"]
        if not isinstance(raw_candidates, list) or not 2 <= len(raw_candidates) <= _MAX_CANDIDATES:
            raise SyntheticCorpusError("retrieval candidate count outside bounds")
        candidates: list[RetrievalCandidate] = []
        for candidate_index, raw_candidate in enumerate(raw_candidates):
            if not isinstance(raw_candidate, dict):
                raise SyntheticCorpusError("retrieval candidate must be an object")
            _exact_keys(
                raw_candidate,
                frozenset({"candidate_id", "text"}),
                f"retrieval[{case_index}].candidates[{candidate_index}]",
            )
            candidates.append(
                RetrievalCandidate(
                    candidate_id=_safe_id(
                        raw_candidate["candidate_id"],
                        "retrieval candidate",
                    ),
                    text=_bounded_text(raw_candidate["text"], "retrieval candidate"),
                )
            )
        candidate_ids = [candidate.candidate_id for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise SyntheticCorpusError("duplicate candidate identifier")
        positive_id = _safe_id(raw_case["positive_candidate_id"], "positive candidate")
        if positive_id not in candidate_ids:
            raise SyntheticCorpusError("positive candidate not present")
        retrieval.append(
            RetrievalCase(
                language=language,
                query=_bounded_text(raw_case["query"], "retrieval query"),
                positive_candidate_id=positive_id,
                candidates=tuple(candidates),
            )
        )

    raw_nli = payload["nli_cases"]
    if not isinstance(raw_nli, list) or not 1 <= len(raw_nli) <= _MAX_NLI_CASES:
        raise SyntheticCorpusError("NLI case count outside bounds")
    nli: list[NliCase] = []
    for case_index, raw_case in enumerate(raw_nli):
        if not isinstance(raw_case, dict):
            raise SyntheticCorpusError("NLI case must be an object")
        _exact_keys(
            raw_case,
            frozenset(
                {"language", "premise", "hypothesis", "expected_label", "scope_relation"}
            ),
            f"nli[{case_index}]",
        )
        language = raw_case["language"]
        label = raw_case["expected_label"]
        scope = raw_case["scope_relation"]
        if language not in _LANGUAGES or label not in _NLI_LABELS or scope not in _SCOPE_RELATIONS:
            raise SyntheticCorpusError("unsupported NLI categorical value")
        nli.append(
            NliCase(
                language=language,
                premise=_bounded_text(raw_case["premise"], "NLI premise"),
                hypothesis=_bounded_text(raw_case["hypothesis"], "NLI hypothesis"),
                expected_label=label,
                scope_relation=scope,
            )
        )

    if {case.language for case in retrieval} != _LANGUAGES:
        raise SyntheticCorpusError("retrieval corpus must contain both languages")
    if {case.language for case in nli} != _LANGUAGES:
        raise SyntheticCorpusError("NLI corpus must contain both languages")
    if {case.expected_label for case in nli} != _NLI_LABELS:
        raise SyntheticCorpusError("NLI corpus must contain all typed labels")
    if {case.scope_relation for case in nli} != _SCOPE_RELATIONS:
        raise SyntheticCorpusError("NLI corpus must contain same- and different-scope cases")
    return SyntheticTextModelCorpus(
        schema_version=1,
        benchmark_id=benchmark_id,
        retrieval_cases=tuple(retrieval),
        nli_cases=tuple(nli),
    )


def load_synthetic_rubric_corpus(path: Path) -> SyntheticRubricCorpus:
    """Load a closed, fictional EN/PL rubric screen."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SyntheticCorpusError("rubric corpus root must be an object")
    _exact_keys(
        payload,
        frozenset({"schema_version", "benchmark_id", "synthetic_only", "cases"}),
        "rubric root",
    )
    if payload["schema_version"] != 1 or payload["synthetic_only"] is not True:
        raise SyntheticCorpusError("unsupported or non-synthetic rubric corpus")
    benchmark_id = _safe_id(payload["benchmark_id"], "rubric benchmark_id")
    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= _MAX_RUBRIC_CASES:
        raise SyntheticCorpusError("rubric case count outside bounds")
    cases: list[RubricCase] = []
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise SyntheticCorpusError("rubric case must be an object")
        _exact_keys(
            raw_case,
            frozenset(
                {"case_id", "language", "rubric_key", "text", "expected_label"}
            ),
            f"rubric[{index}]",
        )
        language = raw_case["language"]
        rubric_key = raw_case["rubric_key"]
        expected_label = raw_case["expected_label"]
        if (
            language not in _LANGUAGES
            or rubric_key not in _RUBRIC_KEYS
            or expected_label not in _RUBRIC_LABELS
        ):
            raise SyntheticCorpusError("unsupported rubric categorical value")
        cases.append(
            RubricCase(
                case_id=_safe_id(raw_case["case_id"], "rubric case_id"),
                language=language,
                rubric_key=rubric_key,
                text=_bounded_text(raw_case["text"], "rubric text"),
                expected_label=expected_label,
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise SyntheticCorpusError("duplicate rubric case identifier")
    if {case.language for case in cases} != _LANGUAGES:
        raise SyntheticCorpusError("rubric corpus must contain both languages")
    if {case.expected_label for case in cases} != _RUBRIC_LABELS:
        raise SyntheticCorpusError("rubric corpus must contain all typed labels")
    if {case.rubric_key for case in cases} != _RUBRIC_KEYS:
        raise SyntheticCorpusError("rubric corpus must cover every rubric key")
    return SyntheticRubricCorpus(
        schema_version=1,
        benchmark_id=benchmark_id,
        cases=tuple(cases),
    )


class RetrievalScorer(Protocol):
    def score(self, cases: Sequence[RetrievalCase]) -> Sequence[Sequence[float]]: ...


class NliClassifier(Protocol):
    def predict(self, cases: Sequence[NliCase]) -> Sequence[str]: ...


class RubricJudge(Protocol):
    def predict(self, cases: Sequence[RubricCase]) -> Sequence[RubricPrediction]: ...


class LexicalBm25Scorer:
    """Dependency-free BM25 over each query's small candidate set."""

    key = "lexical_bm25_v1"

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return _TOKEN.findall(value.casefold())

    def score(self, cases: Sequence[RetrievalCase]) -> tuple[tuple[float, ...], ...]:
        matrices: list[tuple[float, ...]] = []
        k1 = 1.2
        b = 0.75
        for case in cases:
            documents = [self._tokens(candidate.text) for candidate in case.candidates]
            query_terms = set(self._tokens(case.query))
            document_count = len(documents)
            average_length = sum(map(len, documents)) / document_count
            frequencies = [Counter(document) for document in documents]
            document_frequency = {
                term: sum(1 for frequency in frequencies if frequency[term] > 0)
                for term in query_terms
            }
            scores: list[float] = []
            for document, frequency in zip(documents, frequencies, strict=True):
                score = 0.0
                for term in query_terms:
                    tf = frequency[term]
                    if not tf:
                        continue
                    df = document_frequency[term]
                    inverse_document_frequency = math.log(
                        1 + (document_count - df + 0.5) / (df + 0.5)
                    )
                    denominator = tf + k1 * (
                        1 - b + b * len(document) / max(average_length, 1)
                    )
                    score += inverse_document_frequency * (tf * (k1 + 1)) / denominator
                scores.append(score)
            matrices.append(tuple(scores))
        return tuple(matrices)


def _rounded(value: float) -> float:
    return round(value, 6)


def evaluate_retrieval(
    cases: Sequence[RetrievalCase],
    scorer: RetrievalScorer,
    *,
    backend_key: str,
) -> dict[str, object]:
    start = time.perf_counter()
    score_rows = scorer.score(cases)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if len(score_rows) != len(cases):
        raise ValueError("retrieval scorer returned an invalid row count")

    reciprocal_ranks: list[float] = []
    unique_top_one = 0
    recall_at_three = 0
    for case, raw_scores in zip(cases, score_rows, strict=True):
        scores = tuple(float(score) for score in raw_scores)
        if len(scores) != len(case.candidates) or not all(math.isfinite(score) for score in scores):
            raise ValueError("retrieval scorer returned an invalid score row")
        positive_index = next(
            index
            for index, candidate in enumerate(case.candidates)
            if candidate.candidate_id == case.positive_candidate_id
        )
        positive_score = scores[positive_index]
        better = sum(score > positive_score for score in scores)
        tied_other = sum(score == positive_score for index, score in enumerate(scores) if index != positive_index)
        average_rank = 1 + better + tied_other / 2
        reciprocal_ranks.append(1 / average_rank)
        if better == 0 and tied_other == 0:
            unique_top_one += 1
        if average_rank <= 3:
            recall_at_three += 1

    count = len(cases)
    return {
        "backend_key": backend_key,
        "case_count": count,
        "top1_accuracy": _rounded(unique_top_one / count),
        "mean_reciprocal_rank": _rounded(sum(reciprocal_ranks) / count),
        "recall_at_3": _rounded(recall_at_three / count),
        "inference_latency_ms": round(elapsed_ms, 3),
        "latency_ms_per_case": round(elapsed_ms / count, 3),
    }


def _binary_f1(expected: Sequence[bool], predicted: Sequence[bool], positive: bool) -> float:
    true_positive = sum(e == positive and p == positive for e, p in zip(expected, predicted, strict=True))
    false_positive = sum(e != positive and p == positive for e, p in zip(expected, predicted, strict=True))
    false_negative = sum(e == positive and p != positive for e, p in zip(expected, predicted, strict=True))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def evaluate_nli(
    cases: Sequence[NliCase],
    classifier: NliClassifier,
    *,
    backend_key: str,
) -> dict[str, object]:
    start = time.perf_counter()
    predictions = tuple(classifier.predict(cases))
    elapsed_ms = (time.perf_counter() - start) * 1000
    if len(predictions) != len(cases) or any(label not in _NLI_LABELS for label in predictions):
        raise ValueError("NLI classifier returned invalid typed predictions")

    expected = tuple(case.expected_label for case in cases)
    expected_binary = tuple(label == "contradiction" for label in expected)
    predicted_binary = tuple(label == "contradiction" for label in predictions)
    contradiction_accuracy = sum(
        left == right for left, right in zip(expected_binary, predicted_binary, strict=True)
    ) / len(cases)
    macro_f1 = (
        _binary_f1(expected_binary, predicted_binary, True)
        + _binary_f1(expected_binary, predicted_binary, False)
    ) / 2
    different_scope_indexes = [
        index for index, case in enumerate(cases) if case.scope_relation == "different_scope"
    ]
    different_scope_false_positives = sum(
        predictions[index] == "contradiction" and expected[index] != "contradiction"
        for index in different_scope_indexes
    )
    return {
        "backend_key": backend_key,
        "case_count": len(cases),
        "three_way_accuracy": _rounded(
            sum(left == right for left, right in zip(expected, predictions, strict=True))
            / len(cases)
        ),
        "contradiction_detection_accuracy": _rounded(contradiction_accuracy),
        "contradiction_detection_macro_f1": _rounded(macro_f1),
        "different_scope_case_count": len(different_scope_indexes),
        "different_scope_false_positive_rate": _rounded(
            different_scope_false_positives / len(different_scope_indexes)
            if different_scope_indexes
            else 0.0
        ),
        "inference_latency_ms": round(elapsed_ms, 3),
        "latency_ms_per_case": round(elapsed_ms / len(cases), 3),
    }


def evaluate_rubric(
    cases: Sequence[RubricCase],
    judge: RubricJudge,
    *,
    backend_key: str,
) -> dict[str, object]:
    start = time.perf_counter()
    predictions = tuple(judge.predict(cases))
    elapsed_ms = (time.perf_counter() - start) * 1000
    if len(predictions) != len(cases):
        raise ValueError("rubric judge returned an invalid prediction count")
    if any(
        prediction.label is not None and prediction.label not in _RUBRIC_LABELS
        for prediction in predictions
    ):
        raise ValueError("rubric judge returned an invalid typed label")
    exact = sum(
        prediction.json_valid and prediction.label == case.expected_label
        for case, prediction in zip(cases, predictions, strict=True)
    )
    valid = sum(prediction.json_valid for prediction in predictions)
    abstain_expected = tuple(case.expected_label == "abstain" for case in cases)
    abstain_predicted = tuple(
        prediction.label == "abstain" if prediction.json_valid else False
        for prediction in predictions
    )
    per_language = {
        language: _rounded(
            sum(
                prediction.json_valid and prediction.label == case.expected_label
                for case, prediction in zip(cases, predictions, strict=True)
                if case.language == language
            )
            / sum(case.language == language for case in cases)
        )
        for language in sorted(_LANGUAGES)
    }
    return {
        "backend_key": backend_key,
        "case_count": len(cases),
        "exact_label_accuracy": _rounded(exact / len(cases)),
        "json_schema_compliance_rate": _rounded(valid / len(cases)),
        "abstention_macro_f1": _rounded(
            (
                _binary_f1(abstain_expected, abstain_predicted, True)
                + _binary_f1(abstain_expected, abstain_predicted, False)
            )
            / 2
        ),
        "accuracy_by_language": per_language,
        "inference_latency_ms": round(elapsed_ms, 3),
        "latency_ms_per_case": round(elapsed_ms / len(cases), 3),
    }


def rubric_corpus_public_summary(corpus: SyntheticRubricCorpus) -> dict[str, object]:
    return {
        "schema_version": corpus.schema_version,
        "benchmark_id": corpus.benchmark_id,
        "synthetic_only": True,
        "languages": sorted(_LANGUAGES),
        "case_count": len(corpus.cases),
        "label_counts": dict(
            sorted(Counter(case.expected_label for case in corpus.cases).items())
        ),
        "rubric_counts": dict(
            sorted(Counter(case.rubric_key for case in corpus.cases).items())
        ),
    }


def corpus_public_summary(corpus: SyntheticTextModelCorpus) -> dict[str, object]:
    """Return aggregate-only corpus information."""

    return {
        "schema_version": corpus.schema_version,
        "benchmark_id": corpus.benchmark_id,
        "synthetic_only": True,
        "languages": sorted(_LANGUAGES),
        "retrieval_case_count": len(corpus.retrieval_cases),
        "nli_case_count": len(corpus.nli_cases),
        "nli_label_counts": dict(sorted(Counter(case.expected_label for case in corpus.nli_cases).items())),
        "nli_scope_counts": dict(sorted(Counter(case.scope_relation for case in corpus.nli_cases).items())),
    }
