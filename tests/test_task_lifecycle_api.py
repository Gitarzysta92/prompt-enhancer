from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.persistence import TaskRevisionRecord
from prompt_enhancer.application.task_lifecycle import TaskLifecycleService
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER
from prompt_enhancer.interfaces.http.task_lifecycle_routes import IDEMPOTENCY_HEADER
from prompt_enhancer.privacy import Pseudonymizer


TOKEN = "example_lifecycle_api_token_do_not_use_123456789"
NOW = datetime(2043, 4, 5, 6, 7, tzinfo=UTC)


def _app(tmp_path):
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, pseudonymizer).ingest(SyntheticAdapter())
    session_id = database.list_sessions(limit=1)[0]["session_id"]
    session = database.get_session(session_id)
    assert session is not None
    revision = TaskRevisionRecord(
        task_id="a" * 64,
        revision=1,
        project_id=session.project_id,
        task_type="feature_implementation",
        lifecycle_state="confirmed",
        session_ids=(session_id,),
        input_fingerprint="b" * 64,
        created_at=NOW,
    )
    database.task_repository().append_revision(revision)
    service = TaskLifecycleService(
        database.task_lifecycle_repository(),
        LocalArtifactIdFactory(pseudonymizer),
        clock=lambda: NOW,
    )
    return (
        create_app(
            settings=AppSettings(home=tmp_path),
            database=database,
            api_token=TOKEN,
            task_lifecycle_service=service,
        ),
        database,
        revision,
    )


def _headers(key: str) -> dict[str, str]:
    return {API_TOKEN_HEADER: TOKEN, IDEMPOTENCY_HEADER: key}


def _assert_private_no_store(response) -> None:
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"


def test_authenticated_get_and_idempotent_transition_return_strict_receipts(tmp_path) -> None:
    app, _database, revision = _app(tmp_path)
    path = f"/v1/tasks/{revision.task_id}/revisions/1/lifecycle"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get(path).status_code == 401
        legacy = client.get(path, headers={API_TOKEN_HEADER: TOKEN})
        first = client.post(
            f"{path}/transitions",
            headers=_headers("api-backlog"),
            json={"expected_head_event_id": None, "state": "backlog"},
        )
        replay = client.post(
            f"{path}/transitions",
            headers=_headers("api-backlog"),
            json={"expected_head_event_id": None, "state": "backlog"},
        )
        current = client.get(path, headers={API_TOKEN_HEADER: TOKEN})
        listing = client.get(
            "/v1/task-lifecycles?limit=10&event_limit=10",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    for result in (legacy, first, replay, current, listing):
        _assert_private_no_store(result)

    assert legacy.status_code == 200
    assert legacy.json()["current_state"] is None
    assert legacy.json()["head_event_id"] is None
    assert legacy.json()["events"] == []
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["state"] == "backlog"
    assert first.json()["event"]["source"] == "explicit_local_user"
    assert first.json()["event"]["actor_scope"] == "local_user"
    assert first.json()["event"]["task_input_fingerprint"] == revision.input_fingerprint
    assert "idempotency_key_hash" not in first.text
    assert current.json()["current_state"] == "backlog"
    assert current.json()["events_complete"] is True
    assert listing.json()["lifecycles"][0]["task_id"] == revision.task_id
    assert listing.json()["lifecycles"][0]["current_state"] == "backlog"


def test_browser_mutations_require_same_origin_csrf_and_strict_body(tmp_path) -> None:
    app, _database, revision = _app(tmp_path)
    path = f"/v1/tasks/{revision.task_id}/revisions/1/lifecycle/transitions"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session = client.get("/auth/session")
        csrf = session.json()["csrf_token"]
        no_csrf = client.post(
            path,
            headers={IDEMPOTENCY_HEADER: "browser-no-csrf", "Origin": "http://127.0.0.1"},
            json={"expected_head_event_id": None, "state": "backlog"},
        )
        wrong_origin = client.post(
            path,
            headers={
                IDEMPOTENCY_HEADER: "browser-wrong-origin",
                CSRF_HEADER: csrf,
                "Origin": "https://attacker.invalid",
            },
            json={"expected_head_event_id": None, "state": "backlog"},
        )
        extra = client.post(
            path,
            headers={
                IDEMPOTENCY_HEADER: "browser-extra",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json={
                "expected_head_event_id": None,
                "state": "backlog",
                "note": "PRIVATE-LIFECYCLE-CANARY",
            },
        )
        accepted = client.post(
            path,
            headers={
                IDEMPOTENCY_HEADER: "browser-backlog",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json={"expected_head_event_id": None, "state": "backlog"},
        )

    assert no_csrf.status_code == 403
    assert wrong_origin.status_code == 403
    assert extra.status_code == 422
    assert extra.json() == {"detail": "request validation failed"}
    assert "PRIVATE-LIFECYCLE-CANARY" not in extra.text
    assert accepted.status_code == 201


def test_invalid_transition_stale_head_revision_and_foreign_head_are_sanitized(tmp_path) -> None:
    app, database, revision = _app(tmp_path)
    path = f"/v1/tasks/{revision.task_id}/revisions/1/lifecycle"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        invalid_initial = client.post(
            f"{path}/transitions",
            headers=_headers("invalid-initial"),
            json={"expected_head_event_id": None, "state": "in_progress"},
        )
        backlog = client.post(
            f"{path}/transitions",
            headers=_headers("valid-initial"),
            json={"expected_head_event_id": None, "state": "backlog"},
        )
        stale = client.post(
            f"{path}/transitions",
            headers=_headers("stale-head"),
            json={"expected_head_event_id": None, "state": "in_progress"},
        )
        conflict = client.post(
            f"{path}/transitions",
            headers=_headers("valid-initial"),
            json={
                "expected_head_event_id": backlog.json()["head_event_id"],
                "state": "in_progress",
            },
        )
        missing = client.get(
            f"/v1/tasks/{'f' * 64}/revisions/1/lifecycle",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert invalid_initial.status_code == 422
    assert invalid_initial.json() == {"detail": "invalid task lifecycle change"}
    assert stale.status_code == 409
    assert stale.json() == {"detail": "task lifecycle conflicts"}
    assert conflict.status_code == 409
    assert missing.status_code == 404
    for result in (invalid_initial, stale, conflict, missing):
        _assert_private_no_store(result)

    second = revision.model_copy(
        update={"revision": 2, "input_fingerprint": "c" * 64}
    )
    database.task_repository().append_revision(second)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        old_revision = client.post(
            f"{path}/transitions",
            headers=_headers("old-revision"),
            json={
                "expected_head_event_id": backlog.json()["head_event_id"],
                "state": "in_progress",
            },
        )
    assert old_revision.status_code == 409


def test_correction_is_append_only_and_openapi_has_no_free_text_field(tmp_path) -> None:
    app, _database, revision = _app(tmp_path)
    path = f"/v1/tasks/{revision.task_id}/revisions/1/lifecycle"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        backlog = client.post(
            f"{path}/transitions",
            headers=_headers("correction-backlog"),
            json={"expected_head_event_id": None, "state": "backlog"},
        )
        head = backlog.json()["head_event_id"]
        corrected = client.post(
            f"{path}/corrections",
            headers=_headers("correction-undo"),
            json={"expected_head_event_id": head, "supersedes_event_id": head},
        )
        audit = client.get(path, headers={API_TOKEN_HEADER: TOKEN})

    assert corrected.status_code == 201
    assert corrected.json()["state"] is None
    assert corrected.json()["event"]["event_kind"] == "correction"
    assert corrected.json()["event"]["supersedes_event_id"] == head
    assert audit.json()["event_count"] == 2
    assert [item["event_kind"] for item in audit.json()["events"]] == [
        "transition",
        "correction",
    ]

    schema = app.openapi()
    serialized = str(
        {
            key: value
            for key, value in schema["components"]["schemas"].items()
            if "TaskLifecycle" in key
        }
    ).casefold()
    for prohibited in ("note", "comment", "description_text", "prompt", "transcript"):
        assert prohibited not in serialized
    transition_operation = schema["paths"][
        "/v1/tasks/{task_id}/revisions/{task_revision}/lifecycle/transitions"
    ]["post"]
    correction_operation = schema["paths"][
        "/v1/tasks/{task_id}/revisions/{task_revision}/lifecycle/corrections"
    ]["post"]
    assert "exact idempotent replay returns 200" in transition_operation["description"]
    assert "exact idempotent replay returns 200" in correction_operation["description"]
