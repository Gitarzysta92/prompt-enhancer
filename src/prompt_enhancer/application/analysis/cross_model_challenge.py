"""Synthetic-only challenge contracts for cross-model metric validation.

The challenge deliberately contains no provider session, project, prompt, or
tool data.  It converts the repository's authored fictional EN/PL fixtures into
model-neutral packets, validates structured predictions, and returns only
content-free aggregate measurements.  It never calls a remote model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
import re
from typing import Any, TypeVar


CROSS_MODEL_CHALLENGE_ID = "cross-model-metric-estimation-v1"
CROSS_MODEL_CHALLENGE_SCHEMA_VERSION = 1
CROSS_MODEL_VARIANTS = ("order-a", "order-b")

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_NLI_LABELS = ("entailment", "neutral", "contradiction")
_RUBRIC_LABELS = ("present", "absent", "abstain")
_T = TypeVar("_T")

RUBRIC_DEFINITIONS: Mapping[str, str] = {
    "task_definition": (
        "present when the self-contained request names a concrete action, its "
        "target, and an intended or observable outcome; absent when the request "
        "is self-contained but materially vague; abstain when missing external "
        "context prevents a defensible decision"
    ),
    "constraint_precision": (
        "present when constraints include a concrete number, boundary, platform, "
        "version, or explicit prohibition; absent when only vague qualities are "
        "requested; abstain when the governing constraints are unavailable"
    ),
    "acceptance_testability": (
        "present when completion has an observable check, threshold, comparison, "
        "or pass condition; absent when success is only described with vague "
        "quality words; abstain when acceptance rules are unavailable"
    ),
    "deliverable_contract": (
        "present when the output has an explicit format, interface, location, "
        "audience, or compatibility requirement; absent when the output form is "
        "materially vague; abstain when the defining artifact is unavailable"
    ),
}


class CrossModelChallengeError(ValueError):
    """Raised for a malformed or privacy-incompatible challenge/result."""


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CrossModelChallengeError(f"{name}_must_be_an_object")
    return value


def _sequence(value: object, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CrossModelChallengeError(f"{name}_must_be_an_array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CrossModelChallengeError(f"{name}_must_be_nonempty_text")
    return value


def _fixture_guard(payload: Mapping[str, Any], expected_id: str) -> None:
    if payload.get("synthetic_only") is not True:
        raise CrossModelChallengeError("fixture_must_be_synthetic_only")
    if payload.get("benchmark_id") != expected_id:
        raise CrossModelChallengeError("unexpected_fixture_benchmark_id")


def _case_ids(prefix: str, rows: Sequence[Any]) -> list[str]:
    counters: dict[str, int] = {}
    result: list[str] = []
    for raw in rows:
        row = _mapping(raw, f"{prefix}_case")
        language = _text(row.get("language"), f"{prefix}_language")
        counters[language] = counters.get(language, 0) + 1
        result.append(f"{prefix}-{language}-{counters[language]:02d}")
    return result


def _ordered(values: Sequence[_T], variant: str) -> list[_T]:
    return list(values if variant == "order-a" else reversed(values))


def build_cross_model_challenge(
    model_fixture: Mapping[str, Any],
    rubric_fixture: Mapping[str, Any],
    *,
    variant: str,
) -> dict[str, Any]:
    """Build one blinded fictional challenge packet.

    ``order-b`` reverses case order and every retrieval candidate list so the
    same labels can expose position/order sensitivity without changing content.
    """

    if variant not in CROSS_MODEL_VARIANTS:
        raise CrossModelChallengeError("unsupported_challenge_variant")
    _fixture_guard(model_fixture, "bilingual_model_screen_v1")
    _fixture_guard(rubric_fixture, "bilingual_rubric_screen_v1")

    retrieval_source = _sequence(
        model_fixture.get("retrieval_cases"), "retrieval_cases"
    )
    nli_source = _sequence(model_fixture.get("nli_cases"), "nli_cases")
    rubric_source = _sequence(rubric_fixture.get("cases"), "rubric_cases")
    retrieval_ids = _case_ids("retrieval", retrieval_source)
    nli_ids = _case_ids("nli", nli_source)

    retrieval_rows: list[dict[str, Any]] = []
    for case_id, raw in zip(retrieval_ids, retrieval_source, strict=True):
        row = _mapping(raw, "retrieval_case")
        candidates = []
        for raw_candidate in _sequence(row.get("candidates"), "candidates"):
            candidate = _mapping(raw_candidate, "candidate")
            candidates.append(
                {
                    "candidate_id": _text(
                        candidate.get("candidate_id"), "candidate_id"
                    ),
                    "text": _text(candidate.get("text"), "candidate_text"),
                }
            )
        if len(candidates) < 2:
            raise CrossModelChallengeError("retrieval_requires_two_candidates")
        if len({item["candidate_id"] for item in candidates}) != len(candidates):
            raise CrossModelChallengeError("duplicate_retrieval_candidate_id")
        retrieval_rows.append(
            {
                "case_id": case_id,
                "language": _text(row.get("language"), "retrieval_language"),
                "query": _text(row.get("query"), "retrieval_query"),
                "candidates": _ordered(candidates, variant),
            }
        )

    nli_rows: list[dict[str, Any]] = []
    for case_id, raw in zip(nli_ids, nli_source, strict=True):
        row = _mapping(raw, "nli_case")
        nli_rows.append(
            {
                "case_id": case_id,
                "language": _text(row.get("language"), "nli_language"),
                "premise": _text(row.get("premise"), "nli_premise"),
                "hypothesis": _text(row.get("hypothesis"), "nli_hypothesis"),
            }
        )

    rubric_rows: list[dict[str, Any]] = []
    for raw in rubric_source:
        row = _mapping(raw, "rubric_case")
        rubric_key = _text(row.get("rubric_key"), "rubric_key")
        if rubric_key not in RUBRIC_DEFINITIONS:
            raise CrossModelChallengeError("unsupported_rubric_key")
        rubric_rows.append(
            {
                "case_id": _text(row.get("case_id"), "rubric_case_id"),
                "language": _text(row.get("language"), "rubric_language"),
                "rubric_key": rubric_key,
                "text": _text(row.get("text"), "rubric_text"),
            }
        )
    if len({row["case_id"] for row in rubric_rows}) != len(rubric_rows):
        raise CrossModelChallengeError("duplicate_rubric_case_id")

    return {
        "schema_version": CROSS_MODEL_CHALLENGE_SCHEMA_VERSION,
        "challenge_id": CROSS_MODEL_CHALLENGE_ID,
        "variant": variant,
        "synthetic_only": True,
        "task_contract": {
            "retrieval": (
                "Rank every candidate ID from most to least aligned with the "
                "query. Use each supplied candidate ID exactly once."
            ),
            "nli": (
                "Classify the hypothesis as entailment, neutral, or contradiction "
                "given only the premise. Different subject matter is neutral."
            ),
            "rubric": (
                "Classify each item as present, absent, or abstain using its named "
                "analytic rubric and no unstated external context."
            ),
        },
        "rubric_definitions": dict(RUBRIC_DEFINITIONS),
        "retrieval_cases": _ordered(retrieval_rows, variant),
        "nli_cases": _ordered(nli_rows, variant),
        "rubric_cases": _ordered(rubric_rows, variant),
    }


def cross_model_response_schema(challenge: Mapping[str, Any]) -> dict[str, Any]:
    """Return the strict JSON Schema shared by manual and CLI model runs."""

    challenge_id = _text(challenge.get("challenge_id"), "challenge_id")
    variant = _text(challenge.get("variant"), "variant")
    retrieval_count = len(
        _sequence(challenge.get("retrieval_cases"), "retrieval_cases")
    )
    nli_count = len(_sequence(challenge.get("nli_cases"), "nli_cases"))
    rubric_count = len(_sequence(challenge.get("rubric_cases"), "rubric_cases"))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["challenge_id", "variant", "retrieval", "nli", "rubric"],
        "properties": {
            "challenge_id": {"type": "string", "const": challenge_id},
            "variant": {"type": "string", "const": variant},
            "retrieval": {
                "type": "array",
                "minItems": retrieval_count,
                "maxItems": retrieval_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "ranked_candidate_ids"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "ranked_candidate_ids": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "nli": {
                "type": "array",
                "minItems": nli_count,
                "maxItems": nli_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "label"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "label": {"type": "string", "enum": list(_NLI_LABELS)},
                    },
                },
            },
            "rubric": {
                "type": "array",
                "minItems": rubric_count,
                "maxItems": rubric_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "label"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "label": {
                            "type": "string",
                            "enum": list(_RUBRIC_LABELS),
                        },
                    },
                },
            },
        },
    }


def render_cross_model_prompt(challenge: Mapping[str, Any]) -> str:
    """Render a provider-neutral prompt containing fictional cases only."""

    if challenge.get("synthetic_only") is not True:
        raise CrossModelChallengeError("challenge_must_be_synthetic_only")
    return (
        "You are a bounded analytic classifier. Evaluate only the fictional "
        "challenge below. Do not use tools, files, web search, unstated context, "
        "or model identity. Return exactly one JSON object with exactly these five "
        "top-level fields: challenge_id, variant, retrieval, nli, and rubric. "
        "Each retrieval item must contain only case_id and ranked_candidate_ids. "
        "Each nli or rubric item must contain only case_id and label. Use every "
        "case exactly once, retain the supplied challenge_id and variant, and "
        "include no schema_version, renamed fields, explanations, confidence, "
        "rubric_key, or prose. Treat abstention as a valid class, not as failure."
        "\n\nResponse shape (ellipsis means repeat items; it is not literal output):\n"
        '{"challenge_id":"cross-model-metric-estimation-v1",'
        '"variant":"order-a-or-order-b",'
        '"retrieval":[{"case_id":"...",'
        '"ranked_candidate_ids":["...","..."]}],'
        '"nli":[{"case_id":"...","label":"entailment|neutral|contradiction"}],'
        '"rubric":[{"case_id":"...","label":"present|absent|abstain"}]}\n\n'
        + json.dumps(challenge, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )


def _response_rows(
    response: Mapping[str, Any],
    section: str,
    expected_ids: set[str],
    expected_fields: frozenset[str],
) -> dict[str, Mapping[str, Any]]:
    rows = _sequence(response.get(section), f"response_{section}")
    indexed: dict[str, Mapping[str, Any]] = {}
    for raw in rows:
        row = _mapping(raw, f"response_{section}_item")
        if set(row) != expected_fields:
            raise CrossModelChallengeError(
                f"unexpected_{section}_item_fields"
            )
        case_id = _text(row.get("case_id"), f"response_{section}_case_id")
        if case_id in indexed:
            raise CrossModelChallengeError(f"duplicate_{section}_case_id")
        indexed[case_id] = row
    if set(indexed) != expected_ids:
        raise CrossModelChallengeError(f"incomplete_{section}_case_set")
    return indexed


def validate_cross_model_response(
    challenge: Mapping[str, Any], response: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Validate exact case coverage and return predictions indexed by case ID."""

    if set(response) != {"challenge_id", "variant", "retrieval", "nli", "rubric"}:
        raise CrossModelChallengeError("unexpected_response_fields")
    if response.get("challenge_id") != challenge.get("challenge_id"):
        raise CrossModelChallengeError("response_challenge_id_mismatch")
    if response.get("variant") != challenge.get("variant"):
        raise CrossModelChallengeError("response_variant_mismatch")

    retrieval_cases = {
        _text(row.get("case_id"), "retrieval_case_id"): row
        for row in (
            _mapping(raw, "retrieval_case")
            for raw in _sequence(challenge.get("retrieval_cases"), "retrieval_cases")
        )
    }
    nli_ids = {
        _text(row.get("case_id"), "nli_case_id")
        for row in (
            _mapping(raw, "nli_case")
            for raw in _sequence(challenge.get("nli_cases"), "nli_cases")
        )
    }
    rubric_ids = {
        _text(row.get("case_id"), "rubric_case_id")
        for row in (
            _mapping(raw, "rubric_case")
            for raw in _sequence(challenge.get("rubric_cases"), "rubric_cases")
        )
    }
    retrieval = _response_rows(
        response,
        "retrieval",
        set(retrieval_cases),
        frozenset({"case_id", "ranked_candidate_ids"}),
    )
    nli = _response_rows(
        response,
        "nli",
        nli_ids,
        frozenset({"case_id", "label"}),
    )
    rubric = _response_rows(
        response,
        "rubric",
        rubric_ids,
        frozenset({"case_id", "label"}),
    )

    clean_retrieval: dict[str, Any] = {}
    for case_id, row in retrieval.items():
        ranked = [
            _text(item, "ranked_candidate_id")
            for item in _sequence(
                row.get("ranked_candidate_ids"), "ranked_candidate_ids"
            )
        ]
        expected = {
            _text(candidate.get("candidate_id"), "candidate_id")
            for candidate in (
                _mapping(raw, "candidate")
                for raw in _sequence(
                    retrieval_cases[case_id].get("candidates"), "candidates"
                )
            )
        }
        if len(ranked) != len(expected) or set(ranked) != expected:
            raise CrossModelChallengeError("invalid_retrieval_ranking")
        clean_retrieval[case_id] = ranked

    clean_nli: dict[str, Any] = {}
    for case_id, row in nli.items():
        label = _text(row.get("label"), "nli_label")
        if label not in _NLI_LABELS:
            raise CrossModelChallengeError("invalid_nli_label")
        clean_nli[case_id] = label

    clean_rubric: dict[str, Any] = {}
    for case_id, row in rubric.items():
        label = _text(row.get("label"), "rubric_label")
        if label not in _RUBRIC_LABELS:
            raise CrossModelChallengeError("invalid_rubric_label")
        clean_rubric[case_id] = label
    return {
        "retrieval": clean_retrieval,
        "nli": clean_nli,
        "rubric": clean_rubric,
    }


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(truth: Sequence[str], predicted: Sequence[str], label: str) -> float:
    true_positive = sum(
        expected == label and actual == label
        for expected, actual in zip(truth, predicted, strict=True)
    )
    false_positive = sum(
        expected != label and actual == label
        for expected, actual in zip(truth, predicted, strict=True)
    )
    false_negative = sum(
        expected == label and actual != label
        for expected, actual in zip(truth, predicted, strict=True)
    )
    denominator = 2 * true_positive + false_positive + false_negative
    return 0.0 if denominator == 0 else 2 * true_positive / denominator


def _accuracy_by_slice(
    rows: Sequence[Mapping[str, Any]],
    actual: Mapping[str, str],
    expected: Mapping[str, str],
    slice_key: str,
) -> dict[str, float]:
    values: dict[str, list[bool]] = {}
    for row in rows:
        case_id = _text(row.get("case_id"), "case_id")
        group = _text(row.get(slice_key), slice_key)
        values.setdefault(group, []).append(actual[case_id] == expected[case_id])
    return {
        group: sum(items) / len(items)
        for group, items in sorted(values.items())
    }


def _ground_truth(
    model_fixture: Mapping[str, Any], rubric_fixture: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    _fixture_guard(model_fixture, "bilingual_model_screen_v1")
    _fixture_guard(rubric_fixture, "bilingual_rubric_screen_v1")
    retrieval_source = _sequence(
        model_fixture.get("retrieval_cases"), "retrieval_cases"
    )
    nli_source = _sequence(model_fixture.get("nli_cases"), "nli_cases")
    rubric_source = _sequence(rubric_fixture.get("cases"), "rubric_cases")
    retrieval = {
        case_id: _text(
            _mapping(raw, "retrieval_case").get("positive_candidate_id"),
            "positive_candidate_id",
        )
        for case_id, raw in zip(
            _case_ids("retrieval", retrieval_source), retrieval_source, strict=True
        )
    }
    nli = {
        case_id: _text(
            _mapping(raw, "nli_case").get("expected_label"), "nli_expected_label"
        )
        for case_id, raw in zip(
            _case_ids("nli", nli_source), nli_source, strict=True
        )
    }
    scope = {
        case_id: _text(
            _mapping(raw, "nli_case").get("scope_relation"), "scope_relation"
        )
        for case_id, raw in zip(
            _case_ids("nli", nli_source), nli_source, strict=True
        )
    }
    rubric = {
        _text(_mapping(raw, "rubric_case").get("case_id"), "rubric_case_id"):
        _text(
            _mapping(raw, "rubric_case").get("expected_label"),
            "rubric_expected_label",
        )
        for raw in rubric_source
    }
    return {"retrieval": retrieval, "nli": nli, "scope": scope, "rubric": rubric}


def score_cross_model_response(
    model_fixture: Mapping[str, Any],
    rubric_fixture: Mapping[str, Any],
    challenge: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    model_id: str,
) -> dict[str, Any]:
    """Return separate capability measurements; never an overall model score."""

    if not _MODEL_ID.fullmatch(model_id):
        raise CrossModelChallengeError("invalid_model_id")
    predictions = validate_cross_model_response(challenge, response)
    truth = _ground_truth(model_fixture, rubric_fixture)

    retrieval_rows = [
        _mapping(raw, "retrieval_case")
        for raw in _sequence(challenge.get("retrieval_cases"), "retrieval_cases")
    ]
    top1_correct = 0
    reciprocal_rank = 0.0
    retrieval_language: dict[str, list[bool]] = {}
    for row in retrieval_rows:
        case_id = _text(row.get("case_id"), "retrieval_case_id")
        language = _text(row.get("language"), "retrieval_language")
        ranking = predictions["retrieval"][case_id]
        expected = truth["retrieval"][case_id]
        correct = ranking[0] == expected
        top1_correct += int(correct)
        reciprocal_rank += 1 / (ranking.index(expected) + 1)
        retrieval_language.setdefault(language, []).append(correct)

    nli_rows = [
        _mapping(raw, "nli_case")
        for raw in _sequence(challenge.get("nli_cases"), "nli_cases")
    ]
    nli_expected = [truth["nli"][_text(row.get("case_id"), "case_id")] for row in nli_rows]
    nli_actual = [predictions["nli"][_text(row.get("case_id"), "case_id")] for row in nli_rows]
    contradiction_tp = sum(
        expected == "contradiction" and actual == "contradiction"
        for expected, actual in zip(nli_expected, nli_actual, strict=True)
    )
    contradiction_fp = sum(
        expected != "contradiction" and actual == "contradiction"
        for expected, actual in zip(nli_expected, nli_actual, strict=True)
    )
    contradiction_fn = sum(
        expected == "contradiction" and actual != "contradiction"
        for expected, actual in zip(nli_expected, nli_actual, strict=True)
    )
    different_scope_ids = [
        _text(row.get("case_id"), "case_id")
        for row in nli_rows
        if truth["scope"][_text(row.get("case_id"), "case_id")]
        == "different_scope"
    ]
    different_scope_fp = sum(
        predictions["nli"][case_id] == "contradiction"
        for case_id in different_scope_ids
    )

    rubric_rows = [
        _mapping(raw, "rubric_case")
        for raw in _sequence(challenge.get("rubric_cases"), "rubric_cases")
    ]
    rubric_expected = [
        truth["rubric"][_text(row.get("case_id"), "case_id")]
        for row in rubric_rows
    ]
    rubric_actual = [
        predictions["rubric"][_text(row.get("case_id"), "case_id")]
        for row in rubric_rows
    ]

    return {
        "schema_version": 1,
        "challenge_id": CROSS_MODEL_CHALLENGE_ID,
        "variant": challenge.get("variant"),
        "model_id": model_id,
        "synthetic_only": True,
        "case_counts": {
            "retrieval": len(retrieval_rows),
            "nli": len(nli_rows),
            "rubric": len(rubric_rows),
        },
        "retrieval": {
            "top1_accuracy": top1_correct / len(retrieval_rows),
            "mean_reciprocal_rank": reciprocal_rank / len(retrieval_rows),
            "language_accuracy": {
                language: sum(items) / len(items)
                for language, items in sorted(retrieval_language.items())
            },
        },
        "nli": {
            "three_way_accuracy": sum(
                expected == actual
                for expected, actual in zip(nli_expected, nli_actual, strict=True)
            )
            / len(nli_rows),
            "macro_f1": sum(_f1(nli_expected, nli_actual, label) for label in _NLI_LABELS)
            / len(_NLI_LABELS),
            "contradiction_precision": _safe_ratio(
                contradiction_tp, contradiction_tp + contradiction_fp
            ),
            "contradiction_recall": _safe_ratio(
                contradiction_tp, contradiction_tp + contradiction_fn
            ),
            "contradiction_f1": _f1(
                nli_expected, nli_actual, "contradiction"
            ),
            "different_scope_false_positive_rate": _safe_ratio(
                different_scope_fp, len(different_scope_ids)
            ),
            "language_accuracy": _accuracy_by_slice(
                nli_rows, predictions["nli"], truth["nli"], "language"
            ),
        },
        "rubric": {
            "exact_agreement": sum(
                expected == actual
                for expected, actual in zip(
                    rubric_expected, rubric_actual, strict=True
                )
            )
            / len(rubric_rows),
            "macro_f1": sum(
                _f1(rubric_expected, rubric_actual, label)
                for label in _RUBRIC_LABELS
            )
            / len(_RUBRIC_LABELS),
            "abstain_f1": _f1(rubric_expected, rubric_actual, "abstain"),
            "language_accuracy": _accuracy_by_slice(
                rubric_rows,
                predictions["rubric"],
                truth["rubric"],
                "language",
            ),
            "rubric_accuracy": _accuracy_by_slice(
                rubric_rows,
                predictions["rubric"],
                truth["rubric"],
                "rubric_key",
            ),
        },
    }


def compare_cross_model_response_stability(
    challenge_a: Mapping[str, Any],
    response_a: Mapping[str, Any],
    challenge_b: Mapping[str, Any],
    response_b: Mapping[str, Any],
    *,
    model_id: str,
) -> dict[str, Any]:
    """Compare order variants without interpreting stability as correctness."""

    if not _MODEL_ID.fullmatch(model_id):
        raise CrossModelChallengeError("invalid_model_id")
    if {challenge_a.get("variant"), challenge_b.get("variant")} != set(
        CROSS_MODEL_VARIANTS
    ):
        raise CrossModelChallengeError("stability_requires_both_order_variants")
    first = validate_cross_model_response(challenge_a, response_a)
    second = validate_cross_model_response(challenge_b, response_b)
    if any(set(first[key]) != set(second[key]) for key in first):
        raise CrossModelChallengeError("stability_case_set_mismatch")

    def agreement(section: str, projector: Any) -> float:
        matches = [
            projector(first[section][case_id])
            == projector(second[section][case_id])
            for case_id in first[section]
        ]
        return math.fsum(matches) / len(matches)

    return {
        "schema_version": 1,
        "challenge_id": CROSS_MODEL_CHALLENGE_ID,
        "model_id": model_id,
        "synthetic_only": True,
        "retrieval_top1_stability": agreement(
            "retrieval", lambda ranking: ranking[0]
        ),
        "retrieval_full_ranking_stability": agreement(
            "retrieval", lambda ranking: tuple(ranking)
        ),
        "nli_label_stability": agreement("nli", lambda label: label),
        "rubric_label_stability": agreement("rubric", lambda label: label),
    }


__all__ = [
    "CROSS_MODEL_CHALLENGE_ID",
    "CROSS_MODEL_CHALLENGE_SCHEMA_VERSION",
    "CROSS_MODEL_VARIANTS",
    "CrossModelChallengeError",
    "RUBRIC_DEFINITIONS",
    "build_cross_model_challenge",
    "compare_cross_model_response_stability",
    "cross_model_response_schema",
    "render_cross_model_prompt",
    "score_cross_model_response",
    "validate_cross_model_response",
]
