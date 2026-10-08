from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis import (
    TASK_METRIC_DEFINITIONS,
    TaskAnalysisConflictError,
    TaskAnalysisExecutionError,
    TaskAnalysisInputError,
    TaskAnalysisOutcome,
    TaskAnalysisService,
    TaskRevisionNotFoundError,
)
from prompt_enhancer.application.discovery import (
    AcceptCandidate,
    DiscoveryPersistenceService,
    TaskCategory,
    TaskDiscoveryEngine,
    TaskReviewService,
)
from prompt_enhancer.application.persistence import AnalysisRunStatus
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import SCHEMA_VERSION, Database
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.interfaces.http.review_routes import IDEMPOTENCY_HEADER
from prompt_enhancer.privacy import Pseudonymizer


EXAMPLE_TOKEN = "example_task_analysis_token_do_not_use_123456789"
TASK_ID = "a" * 64
RUN_ID = "b" * 64
NOW = datetime(2026, 5, 6, 9, 0, tzinfo=UTC)


class MinimalStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self):
        return []

    def list_sessions(self, *, limit: int = 100, offset: int = 0):
        return []

    def get_session_metrics(self, session_id: str):
        return []


class MemoryAnalysisService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []
        self.keys: set[str] = set()
        self.failure: Exception | None = None

    def run(
        self,
        task_id: str,
        task_revision: int,
        *,
        idempotency_key: str,
    ) -> TaskAnalysisOutcome:
        if self.failure is not None:
            raise self.failure
        self.calls.append((task_id, task_revision, idempotency_key))
        applied = idempotency_key not in self.keys
        self.keys.add(idempotency_key)
        return TaskAnalysisOutcome(
            run_id=RUN_ID,
            status=AnalysisRunStatus.COMPLETED,
            result_count=8,
            applied=applied,
        )


def _headers(key: str) -> dict[str, str]:
    return {
        API_TOKEN_HEADER: EXAMPLE_TOKEN,
        IDEMPOTENCY_HEADER: key,
    }


def _path(task_id: str = TASK_ID, revision: int = 1) -> str:
    return f"/v1/tasks/{task_id}/revisions/{revision}/analysis-runs"


def _client(tmp_path, service: MemoryAnalysisService | None) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(home=tmp_path),
            database=MinimalStore(),
            api_token=EXAMPLE_TOKEN,
            task_analysis_service=service,
        ),
        base_url="http://127.0.0.1",
    )


def test_analysis_route_is_conditional_authenticated_and_idempotent(tmp_path) -> None:
    service = MemoryAnalysisService()
    with _client(tmp_path, None) as disabled:
        absent = disabled.post(_path(), headers=_headers("analysis-disabled"))
        capabilities_disabled = disabled.get(
            "/v1/capabilities", headers=_headers("capabilities-disabled")
        )
    with _client(tmp_path, service) as client:
        unauthenticated = client.post(
            _path(), headers={IDEMPOTENCY_HEADER: "analysis-1"}
        )
        first = client.post(_path(), headers=_headers("analysis-1"))
        retry = client.post(_path(), headers=_headers("analysis-1"))
        capabilities = client.get(
            "/v1/capabilities", headers=_headers("capabilities")
        )

    assert absent.status_code == 404
    assert capabilities_disabled.json()["task_analysis"] is False
    assert capabilities_disabled.json()["write_api"] is False
    assert unauthenticated.status_code == 401
    assert first.status_code == 200
    assert first.json() == {
        "run_id": RUN_ID,
        "status": "completed",
        "result_count": 8,
        "applied": True,
    }
    assert retry.status_code == 200
    assert retry.json() == {**first.json(), "applied": False}
    assert capabilities.json()["task_analysis"] is True
    assert capabilities.json()["write_api"] is True
    assert service.calls == [
        (TASK_ID, 1, "analysis-1"),
        (TASK_ID, 1, "analysis-1"),
    ]


def test_analysis_route_validates_identifiers_before_service_call(tmp_path) -> None:
    service = MemoryAnalysisService()
    with _client(tmp_path, service) as client:
        invalid_task = client.post(
            _path("not-a-pseudonym"), headers=_headers("analysis-invalid-task")
        )
        invalid_revision = client.post(
            _path(revision=0), headers=_headers("analysis-invalid-revision")
        )
        missing_key = client.post(
            _path(), headers={API_TOKEN_HEADER: EXAMPLE_TOKEN}
        )
        unsafe_key = client.post(
            _path(), headers=_headers("contains spaces")
        )
        hostile_origin = client.post(
            _path(),
            headers={
                **_headers("analysis-origin"),
                "Origin": "https://example.invalid",
            },
        )

    assert invalid_task.status_code == 422
    assert invalid_revision.status_code == 422
    assert missing_key.status_code == 422
    assert unsafe_key.status_code == 422
    assert hostile_origin.status_code == 403
    assert service.calls == []


def test_analysis_application_errors_are_sanitized(tmp_path) -> None:
    service = MemoryAnalysisService()
    cases = (
        (
            TaskRevisionNotFoundError("internal task context"),
            404,
            "task revision not found",
        ),
        (
            TaskAnalysisInputError("internal evidence context"),
            422,
            "task analysis input is unavailable",
        ),
        (
            TaskAnalysisConflictError("internal provenance context"),
            409,
            "task analysis conflicts",
        ),
        (
            TaskAnalysisExecutionError("internal calculator context"),
            500,
            "task analysis failed",
        ),
    )
    with _client(tmp_path, service) as client:
        for index, (failure, status, detail) in enumerate(cases):
            service.failure = failure
            response = client.post(
                _path(), headers=_headers(f"analysis-failure-{index}")
            )
            assert response.status_code == status
            assert response.json() == {"detail": detail}
            assert str(failure) not in response.text


def test_real_sqlite_task_analysis_route_persists_and_reads_results(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    identifiers = LocalArtifactIdFactory(pseudonymizer)
    IngestionService(database, pseudonymizer).ingest(SyntheticAdapter())
    sessions = tuple(
        database.get_session(item["session_id"])
        for item in database.list_sessions()
    )
    assert all(session is not None for session in sessions)
    discovery = DiscoveryPersistenceService(
        TaskDiscoveryEngine(identifiers),
        database.task_repository(),
        identifiers,
        clock=lambda: NOW,
    ).discover_and_persist(sessions)
    candidate = discovery.batch.candidates[0]
    review = TaskReviewService(
        database.task_repository(), identifiers, clock=lambda: NOW
    ).apply(
        AcceptCandidate(
            candidate_id=candidate.candidate_id,
            expected_discovery_version=candidate.discovery_version,
            task_category=TaskCategory.BUG_FIX,
        ),
        idempotency_key="example-analysis-api-review-1",
    )
    task_id, revision = review.output_revisions[0]
    service = TaskAnalysisService(
        database.task_repository(),
        database.analysis_run_repository(),
        database,
        identifiers,
        schema_version=SCHEMA_VERSION,
        clock=lambda: NOW,
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
        task_analysis_service=service,
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.post(
            _path(task_id, revision), headers=_headers("analysis-sqlite-1")
        )
        retry = client.post(
            _path(task_id, revision), headers=_headers("analysis-sqlite-1")
        )
        run = client.get(
            f"/v1/analysis/runs/{first.json()['run_id']}",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )

    assert first.status_code == 200
    assert first.json()["applied"] is True
    assert first.json()["result_count"] == len(TASK_METRIC_DEFINITIONS)
    assert retry.status_code == 200
    assert retry.json() == {**first.json(), "applied": False}
    assert run.status_code == 200
    assert run.json()["run"]["status"] == "completed"
    assert len(run.json()["results"]) == len(TASK_METRIC_DEFINITIONS)
    definitions = {
        (definition.key, definition.version): definition
        for definition in TASK_METRIC_DEFINITIONS
    }
    for result in run.json()["results"]:
        definition = definitions[(result["key"], result["version"])]
        assert result["dimension"] == definition.dimension
        assert result["display_name"] == definition.display_name
        assert result["description"] == definition.description
    serialized = (first.text + run.text).casefold()
    for prohibited in ("prompt_text", "transcript", "filesystem", "account_id"):
        assert prohibited not in serialized
