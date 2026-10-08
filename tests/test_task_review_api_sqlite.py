from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.discovery import TaskReviewService
from prompt_enhancer.application.persistence import TaskCandidateRecord
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.interfaces.http.review_routes import IDEMPOTENCY_HEADER
from prompt_enhancer.privacy import Pseudonymizer


EXAMPLE_TOKEN = "example_sqlite_review_token_do_not_use_123456789"
CANDIDATE_ID = "7" * 64
FINGERPRINT = "8" * 64


def test_sqlite_review_retry_is_idempotent_and_second_decision_conflicts(tmp_path) -> None:
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, pseudonymizer).ingest(SyntheticAdapter())
    session_id = database.list_sessions(limit=1)[0]["session_id"]
    session = database.get_session(session_id)
    assert session is not None

    database.task_repository().add_candidate(
        TaskCandidateRecord(
            candidate_id=CANDIDATE_ID,
            provider=session.provider,
            installation_id=session.installation_id,
            project_id=session.project_id,
            session_ids=(session.session_id,),
            signals=(),
            confidence=None,
            observed_count=0,
            eligible_count=0,
            coverage=0.0,
            discovery_version="discovery-v1",
            input_fingerprint=FINGERPRINT,
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    service = TaskReviewService(
        database.task_repository(),
        LocalArtifactIdFactory(pseudonymizer),
        clock=lambda: datetime(2026, 1, 3, tzinfo=UTC),
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
        task_review_service=service,
    )
    body = {
        "candidate_id": CANDIDATE_ID,
        "expected_discovery_version": "discovery-v1",
        "task_category": "unknown",
    }

    def headers(key: str) -> dict[str, str]:
        return {
            API_TOKEN_HEADER: EXAMPLE_TOKEN,
            IDEMPOTENCY_HEADER: key,
        }

    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.post(
            "/v1/task-decisions/accept",
            headers=headers("accept-one"),
            json=body,
        )
        retry = client.post(
            "/v1/task-decisions/accept",
            headers=headers("accept-one"),
            json=body,
        )
        competing = client.post(
            "/v1/task-decisions/accept",
            headers=headers("accept-competing"),
            json=body,
        )

    assert first.status_code == 200
    assert first.json()["applied"] is True
    assert retry.status_code == 200
    assert retry.json()["decision_id"] == first.json()["decision_id"]
    assert retry.json()["applied"] is False
    assert competing.status_code == 409
    assert competing.json() == {"detail": "task review conflicts"}
    assert "already has a decision" not in competing.text
