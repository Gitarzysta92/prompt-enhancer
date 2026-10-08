from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from prompt_enhancer.application.analysis.method_research import (
    METHODS,
    METRIC_ROADMAP,
    MODEL_CANDIDATES,
    SOURCES,
    MetricRoadmapState,
    ModelCandidateStatus,
    ScoreDirection,
    validate_research_catalog,
)
from prompt_enhancer.infrastructure.text_models.manifests import (
    BGE_M3,
    BGE_M3_LEGACY_BLOCKED,
    BGE_RERANKER_V2_M3,
    E5_MULTILINGUAL_BASE,
    E5_MULTILINGUAL_SMALL,
    MDEBERTA_XNLI,
    QWEN3_4B_RUBRIC,
    QWEN3_EMBEDDING_06B,
    QWEN3_RERANKER_06B,
)
from prompt_enhancer.interfaces.http.research_routes import create_research_router


def test_catalog_is_a_multidimensional_disabled_research_registry() -> None:
    validate_research_catalog()

    assert len(METRIC_ROADMAP) == 20
    assert len(METHODS) >= 10
    assert len(MODEL_CANDIDATES) >= 5
    assert all(not candidate.product_enabled for candidate in MODEL_CANDIDATES)
    assert all(not candidate.trust_remote_code for candidate in MODEL_CANDIDATES)
    assert all(source.url.startswith("https://") for source in SOURCES)
    assert {metric.profile for metric in METRIC_ROADMAP} == {
        "prompt",
        "collaboration",
        "logic",
        "agent_answer",
        "outcome",
    }
    assert any(
        metric.direction is ScoreDirection.CONTEXTUAL for metric in METRIC_ROADMAP
    )
    assert any(
        metric.state is MetricRoadmapState.NEEDS_OBJECTIVE_EVIDENCE
        for metric in METRIC_ROADMAP
    )
    retrieval_method = next(
        method for method in METHODS if method.key == "multilingual_embeddings"
    )
    assert len(retrieval_method.candidate_model_keys) <= 5


def test_evaluated_candidates_match_the_immutable_runtime_manifests() -> None:
    candidates = {candidate.key: candidate for candidate in MODEL_CANDIDATES}

    e5 = candidates[E5_MULTILINGUAL_SMALL.key]
    assert e5.repository_id == E5_MULTILINGUAL_SMALL.repository_id
    assert e5.revision == E5_MULTILINGUAL_SMALL.revision
    assert e5.license_spdx == E5_MULTILINGUAL_SMALL.license_spdx
    assert e5.status is ModelCandidateStatus.EVALUATED_EXPLORATORY
    assert e5.benchmark is not None

    e5_base = candidates[E5_MULTILINGUAL_BASE.key]
    assert e5_base.repository_id == E5_MULTILINGUAL_BASE.repository_id
    assert e5_base.revision == E5_MULTILINGUAL_BASE.revision
    assert e5_base.license_spdx == E5_MULTILINGUAL_BASE.license_spdx
    assert e5_base.status is ModelCandidateStatus.EVALUATED_EXPLORATORY
    assert e5_base.benchmark is not None
    assert e5_base.benchmark.primary_value == 0.833333
    assert e5_base.benchmark.secondary_value == 0.902778

    nli = candidates[MDEBERTA_XNLI.key]
    assert nli.repository_id == MDEBERTA_XNLI.repository_id
    assert nli.revision == MDEBERTA_XNLI.revision
    assert nli.status is ModelCandidateStatus.REJECTED_SCREEN
    assert nli.benchmark is not None
    assert nli.benchmark.critical_metric == "different_scope_false_positive_rate"
    assert nli.benchmark.critical_value == 1.0

    bge_m3 = candidates[BGE_M3.key]
    assert bge_m3.revision == BGE_M3.revision
    assert bge_m3.status is ModelCandidateStatus.EVALUATED_EXPLORATORY
    assert bge_m3.benchmark is not None
    assert bge_m3.benchmark.primary_value == 0.666667
    assert bge_m3.benchmark.secondary_value == 0.819444
    assert BGE_M3_LEGACY_BLOCKED.revision != BGE_M3.revision

    for manifest in (
        BGE_RERANKER_V2_M3,
        QWEN3_EMBEDDING_06B,
        QWEN3_RERANKER_06B,
    ):
        candidate = candidates[manifest.key]
        assert candidate.revision == manifest.revision
        assert candidate.status is ModelCandidateStatus.EVALUATED_EXPLORATORY
        assert candidate.benchmark is not None

    rubric = candidates[QWEN3_4B_RUBRIC.key]
    assert rubric.revision == QWEN3_4B_RUBRIC.revision
    assert rubric.status is ModelCandidateStatus.REJECTED_SCREEN
    assert rubric.benchmark is not None
    assert rubric.benchmark.primary_value == 0.666667
    assert rubric.benchmark.critical_value == 0.521368


def test_research_endpoint_is_content_free_and_read_only() -> None:
    app = FastAPI()
    app.include_router(create_research_router(lambda: None))
    client = TestClient(app)

    response = client.get("/v1/research/text-analysis-methods")
    assert response.status_code == 200
    body = response.json()
    assert body["catalog_key"] == "text-analysis-methods"
    assert body["catalog_version"] == 4
    assert body["privacy_mode"] == "local_only_redacted_content"
    assert body["summary_policy"] == "multidimensional_profile_no_universal_score"
    assert body["catalog_read_starts_session_access"] is False
    assert body["catalog_read_downloads_models"] is False
    assert len(body["metric_roadmap"]) == 20
    assert all(candidate["product_enabled"] is False for candidate in body["model_candidates"])

    serialized = response.text.casefold()
    for forbidden in (
        "prompt_text",
        "response_text",
        "transcript",
        "source_path",
        "account_id",
        "credential",
        "authorization",
    ):
        assert forbidden not in serialized
