from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.model_link_experiments import (
    MODEL_LINK_CONFIRMATION,
    ModelExperimentDevice,
    ModelLinkAnnotationLabel,
    ModelLinkAnnotationRecord,
    ModelLinkExecutionError,
    ModelLinkExperimentOutcome,
    ModelLinkModelIdentity,
    ModelLinkRecommendation,
    ModelLinkRunRecord,
    ModelLinkSourceError,
    ModelLinkStoredExperiment,
    ModelLinkStoredLink,
    ModelLinkSuggestion,
    ModelLinkCandidateKind,
)
from prompt_enhancer.application.analysis.text_source import TextSourceFailureReason
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


TOKEN = "example_model_link_api_token_1234567890"
NOW = datetime(2040, 3, 4, 12, tzinfo=UTC)


def _database(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    return database, database.list_sessions(limit=1)[0]["session_id"]


def _model(key: str, identity: str, repository_id: str) -> ModelLinkModelIdentity:
    return ModelLinkModelIdentity(
        key=key,
        repository_id=repository_id,
        revision=identity * 40,
        license_spdx="Apache-2.0",
        tokenizer_id=f"{repository_id}:{identity * 40}",
        backend_key=f"{key}_backend_v1",
    )


def _outcome(session_id: str) -> ModelLinkExperimentOutcome:
    run = ModelLinkRunRecord(
        run_id="a" * 64,
        session_id=session_id,
        request_fingerprint="b" * 64,
        input_fingerprint="c" * 64,
        provider=Provider.CODEX,
        provider_version="example-provider-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-source-1",
        content_schema_version="example-content-1",
        redactor_version="example-redactor-1",
        resolved_device=ModelExperimentDevice.CUDA,
        qwen_model=_model(
            "qwen3_embedding_06b", "d", "Qwen/Qwen3-Embedding-0.6B"
        ),
        bge_model=_model(
            "bge_reranker_v2_m3", "e", "BAAI/bge-reranker-v2-m3"
        ),
        query_count=1,
        link_count=1,
        agreement_count=1,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=3),
    )
    link = ModelLinkStoredLink(
        run_id=run.run_id,
        link_id="f" * 64,
        query_message_id="1" * 64,
        candidate_message_id="2" * 64,
        query_sequence=0,
        candidate_sequence=1,
        candidate_kind=ModelLinkCandidateKind.RESPONSE,
        qwen_score=0.8,
        qwen_rank=1,
        bge_score=4.0,
        bge_rank=1,
        recommended_by=ModelLinkRecommendation.BOTH,
    )
    experiment = ModelLinkStoredExperiment(run=run, links=(link,))
    return ModelLinkExperimentOutcome(
        experiment=experiment,
        suggestions=(
            ModelLinkSuggestion(
                link=link,
                query_excerpt=SecretStr("Fictional redacted request"),
                candidate_excerpt=SecretStr("Fictional redacted response"),
            ),
        ),
        applied=True,
    )


@dataclass
class RecordingService:
    session_id: str
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.outcome = _outcome(self.session_id)

    def run(self, **values):
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return self.outcome

    def latest(self, session_id: str):
        self.calls.append({"latest": session_id})
        return self.outcome.experiment

    def annotate(self, **values):
        self.calls.append(values)
        return ModelLinkAnnotationRecord(
            run_id=values["run_id"],
            link_id=values["link_id"],
            revision=values["expected_revision"] + 1,
            label=values["label"],
            annotated_at=NOW + timedelta(minutes=1),
        )


def _client(tmp_path, *, error: Exception | None = None):
    database, session_id = _database(tmp_path)
    service = RecordingService(session_id, error)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_link_experiment_service=service,  # type: ignore[arg-type]
    )
    return TestClient(app, base_url="http://127.0.0.1"), session_id, service


def test_explicit_experiment_returns_transient_excerpts_but_latest_does_not(tmp_path) -> None:
    client, session_id, service = _client(tmp_path)
    path = f"/v1/sessions/{session_id}/model-link-experiments"
    headers = {API_TOKEN_HEADER: TOKEN, "Idempotency-Key": "example-link-run-0001"}

    with client:
        unauthorized = client.post(
            path,
            json={"confirmation": MODEL_LINK_CONFIRMATION, "device": "cuda"},
            headers={"Idempotency-Key": "example-link-run-0001"},
        )
        response = client.post(
            path,
            json={"confirmation": MODEL_LINK_CONFIRMATION, "device": "cuda"},
            headers=headers,
        )
        latest = client.get(
            f"{path}/latest", headers={API_TOKEN_HEADER: TOKEN}
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["suggestions"] == [
        {
            "link_id": "f" * 64,
            "query_excerpt": "Fictional redacted request",
            "candidate_excerpt": "Fictional redacted response",
        }
    ]
    assert latest.status_code == 200
    assert "Fictional" not in latest.text
    assert "query_message_id" not in latest.text
    # The route passes the session's own catalog provider (synthetic fixture).
    assert service.calls[0]["provider"] is Provider.SYNTHETIC
    assert service.calls[0]["device"] is ModelExperimentDevice.CUDA


def test_experiment_rejects_content_fields_before_service(tmp_path) -> None:
    client, session_id, service = _client(tmp_path)
    with client:
        response = client.post(
            f"/v1/sessions/{session_id}/model-link-experiments",
            json={
                "confirmation": MODEL_LINK_CONFIRMATION,
                "device": "auto",
                "transcript": "SYNTHETIC_PRIVATE_CANARY",
            },
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "example-link-run-0002",
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "request validation failed"}
    assert "SYNTHETIC_PRIVATE_CANARY" not in response.text
    assert service.calls == []


def test_experiment_error_is_fixed_and_discards_exception_detail(tmp_path) -> None:
    client, session_id, _ = _client(
        tmp_path,
        error=ModelLinkExecutionError("SYNTHETIC_PRIVATE_CANARY"),
    )
    with client:
        response = client.post(
            f"/v1/sessions/{session_id}/model-link-experiments",
            json={"confirmation": MODEL_LINK_CONFIRMATION, "device": "auto"},
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "example-link-run-0003",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "local_model_execution_failed",
            "message": "cached local models are unavailable",
        }
    }
    assert "SYNTHETIC_PRIVATE_CANARY" not in response.text


@pytest.mark.parametrize(
    ("reason", "expected_message"),
    (
        (
            TextSourceFailureReason.SELECTION_LIMIT,
            "provider session selection exceeds the local scan bounds",
        ),
        (
            TextSourceFailureReason.PROVIDER_RESPONSE_LIMIT,
            "local provider response exceeds the transport bound",
        ),
        (
            TextSourceFailureReason.THREAD_STRUCTURE_LIMIT,
            "selected session structure exceeds the local parser bounds",
        ),
        (
            TextSourceFailureReason.PREVIEW_WINDOW_LIMIT,
            "selected focus message exceeds the local experiment window",
        ),
    ),
)
def test_experiment_source_limits_are_exact_and_content_free(
    tmp_path,
    reason: TextSourceFailureReason,
    expected_message: str,
) -> None:
    client, session_id, _ = _client(tmp_path, error=ModelLinkSourceError(reason))

    with client:
        response = client.post(
            f"/v1/sessions/{session_id}/model-link-experiments",
            json={"confirmation": MODEL_LINK_CONFIRMATION, "device": "auto"},
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "example-link-source-limit-0001",
            },
        )

    assert response.status_code == 413
    assert response.json() == {
        "detail": {"code": reason.value, "message": expected_message}
    }
    assert "PRIVATE" not in response.text


def test_human_annotation_is_revisioned_without_excerpts(tmp_path) -> None:
    client, _, service = _client(tmp_path)
    run_id = "a" * 64
    link_id = "f" * 64
    with client:
        response = client.post(
            f"/v1/model-link-experiments/{run_id}/links/{link_id}/annotations",
            json={"label": "relevant", "expected_revision": 0},
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert response.json()["label"] == "relevant"
    assert service.calls[0]["label"] is ModelLinkAnnotationLabel.RELEVANT
    assert "excerpt" not in response.text
