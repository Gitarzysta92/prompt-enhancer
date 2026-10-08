from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from prompt_enhancer.application.analysis.cross_model_challenge import (
    CROSS_MODEL_CHALLENGE_ID,
    CrossModelChallengeError,
    build_cross_model_challenge,
    compare_cross_model_response_stability,
    cross_model_response_schema,
    render_cross_model_prompt,
    score_cross_model_response,
    validate_cross_model_response,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_model_screen_v1.json"
)
RUBRIC_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_rubric_screen_v1.json"
)


def load_fixture(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def source_case_ids(prefix: str, rows: list[dict[str, Any]]) -> list[str]:
    counters: dict[str, int] = {}
    result: list[str] = []
    for row in rows:
        language = row["language"]
        counters[language] = counters.get(language, 0) + 1
        result.append(f"{prefix}-{language}-{counters[language]:02d}")
    return result


def perfect_response(
    challenge: dict[str, Any],
    model_fixture: dict[str, Any],
    rubric_fixture: dict[str, Any],
) -> dict[str, Any]:
    retrieval_truth = {
        case_id: row["positive_candidate_id"]
        for case_id, row in zip(
            source_case_ids("retrieval", model_fixture["retrieval_cases"]),
            model_fixture["retrieval_cases"],
            strict=True,
        )
    }
    nli_truth = {
        case_id: row["expected_label"]
        for case_id, row in zip(
            source_case_ids("nli", model_fixture["nli_cases"]),
            model_fixture["nli_cases"],
            strict=True,
        )
    }
    rubric_truth = {
        row["case_id"]: row["expected_label"]
        for row in rubric_fixture["cases"]
    }
    retrieval = []
    for row in challenge["retrieval_cases"]:
        positive = retrieval_truth[row["case_id"]]
        others = sorted(
            candidate["candidate_id"]
            for candidate in row["candidates"]
            if candidate["candidate_id"] != positive
        )
        retrieval.append(
            {
                "case_id": row["case_id"],
                "ranked_candidate_ids": [positive, *others],
            }
        )
    return {
        "challenge_id": challenge["challenge_id"],
        "variant": challenge["variant"],
        "retrieval": retrieval,
        "nli": [
            {"case_id": row["case_id"], "label": nli_truth[row["case_id"]]}
            for row in challenge["nli_cases"]
        ],
        "rubric": [
            {
                "case_id": row["case_id"],
                "label": rubric_truth[row["case_id"]],
            }
            for row in challenge["rubric_cases"]
        ],
    }


@pytest.fixture
def fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    return load_fixture(MODEL_FIXTURE), load_fixture(RUBRIC_FIXTURE)


def test_challenge_is_synthetic_blinded_and_has_order_counterfactual(
    fixtures: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    model_fixture, rubric_fixture = fixtures
    first = build_cross_model_challenge(
        model_fixture, rubric_fixture, variant="order-a"
    )
    second = build_cross_model_challenge(
        model_fixture, rubric_fixture, variant="order-b"
    )

    serialized = json.dumps(first, ensure_ascii=False)
    assert first["synthetic_only"] is True
    assert first["challenge_id"] == CROSS_MODEL_CHALLENGE_ID
    assert "expected_label" not in serialized
    assert "positive_candidate_id" not in serialized
    assert [row["case_id"] for row in second["retrieval_cases"]] == list(
        reversed([row["case_id"] for row in first["retrieval_cases"]])
    )
    first_candidates = {
        row["case_id"]: [item["candidate_id"] for item in row["candidates"]]
        for row in first["retrieval_cases"]
    }
    second_candidates = {
        row["case_id"]: [item["candidate_id"] for item in row["candidates"]]
        for row in second["retrieval_cases"]
    }
    assert all(
        second_candidates[case_id] == list(reversed(candidate_ids))
        for case_id, candidate_ids in first_candidates.items()
    )


def test_prompt_and_schema_keep_the_fixed_structured_contract(
    fixtures: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    challenge = build_cross_model_challenge(*fixtures, variant="order-a")
    schema = cross_model_response_schema(challenge)
    prompt = render_cross_model_prompt(challenge)

    assert schema["properties"]["challenge_id"]["const"] == CROSS_MODEL_CHALLENGE_ID
    assert schema["properties"]["retrieval"]["minItems"] == 12
    assert schema["properties"]["nli"]["minItems"] == 18
    assert schema["properties"]["rubric"]["minItems"] == 24
    assert "Do not use tools" in prompt
    assert "expected_label" not in prompt
    assert "positive_candidate_id" not in prompt


def test_perfect_response_scores_each_capability_separately(
    fixtures: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    model_fixture, rubric_fixture = fixtures
    challenge = build_cross_model_challenge(
        model_fixture, rubric_fixture, variant="order-a"
    )
    response = perfect_response(challenge, model_fixture, rubric_fixture)

    report = score_cross_model_response(
        model_fixture,
        rubric_fixture,
        challenge,
        response,
        model_id="example/frontier-model-1",
    )

    assert report["retrieval"]["top1_accuracy"] == 1
    assert report["retrieval"]["mean_reciprocal_rank"] == 1
    assert report["nli"]["three_way_accuracy"] == 1
    assert report["nli"]["macro_f1"] == 1
    assert report["nli"]["different_scope_false_positive_rate"] == 0
    assert report["rubric"]["exact_agreement"] == 1
    assert report["rubric"]["macro_f1"] == 1
    assert report["rubric"]["abstain_f1"] == 1
    assert "overall_score" not in report


def test_response_validation_rejects_missing_cases_and_invalid_rankings(
    fixtures: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    model_fixture, rubric_fixture = fixtures
    challenge = build_cross_model_challenge(
        model_fixture, rubric_fixture, variant="order-a"
    )
    response = perfect_response(challenge, model_fixture, rubric_fixture)
    response["nli"].pop()
    with pytest.raises(CrossModelChallengeError, match="incomplete_nli_case_set"):
        validate_cross_model_response(challenge, response)

    response = perfect_response(challenge, model_fixture, rubric_fixture)
    response["retrieval"][0]["ranked_candidate_ids"][1] = response["retrieval"][0][
        "ranked_candidate_ids"
    ][0]
    with pytest.raises(CrossModelChallengeError, match="invalid_retrieval_ranking"):
        validate_cross_model_response(challenge, response)

    response = perfect_response(challenge, model_fixture, rubric_fixture)
    response["rubric"][0]["confidence"] = 1
    with pytest.raises(
        CrossModelChallengeError, match="unexpected_rubric_item_fields"
    ):
        validate_cross_model_response(challenge, response)


def test_order_stability_is_reported_without_calling_it_accuracy(
    fixtures: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    model_fixture, rubric_fixture = fixtures
    challenge_a = build_cross_model_challenge(
        model_fixture, rubric_fixture, variant="order-a"
    )
    challenge_b = build_cross_model_challenge(
        model_fixture, rubric_fixture, variant="order-b"
    )
    response_a = perfect_response(challenge_a, model_fixture, rubric_fixture)
    response_b = perfect_response(challenge_b, model_fixture, rubric_fixture)

    stable = compare_cross_model_response_stability(
        challenge_a,
        response_a,
        challenge_b,
        response_b,
        model_id="example/frontier-model-1",
    )
    assert stable["retrieval_top1_stability"] == 1
    assert stable["retrieval_full_ranking_stability"] == 1
    assert stable["nli_label_stability"] == 1
    assert stable["rubric_label_stability"] == 1
    assert "accuracy" not in stable

    response_b["nli"][0]["label"] = (
        "neutral" if response_b["nli"][0]["label"] != "neutral" else "entailment"
    )
    changed = compare_cross_model_response_stability(
        challenge_a,
        response_a,
        challenge_b,
        response_b,
        model_id="example/frontier-model-1",
    )
    assert changed["nli_label_stability"] == pytest.approx(17 / 18)
