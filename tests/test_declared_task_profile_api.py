"""Synthetic HTTP authority tests for reviewed task profiles."""

import hashlib
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER
from prompt_enhancer.interfaces.http.user_presence import (
    USER_PRESENCE_HEADER,
    UserPresenceApprovalManager,
)

from test_declared_task_profiles import _command, _service


TOKEN = "example_declared_profile_token_do_not_use_123456789"


def _trusted_user_presence(_request, _body: bytes) -> None:
    """Synthetic stand-in for a future non-HTTP native/account approval port."""


def _app(tmp_path, *, user_presence=True):
    database, session_id, _repository, service = _service(tmp_path)
    return (
        create_app(
            settings=AppSettings(home=tmp_path),
            database=database,
            api_token=TOKEN,
            declared_task_profile_service=service,
            user_presence_confirmation=(
                _trusted_user_presence if user_presence else None
            ),
        ),
        session_id,
    )


def _private(response) -> None:
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"


def test_profile_save_consumes_one_exact_native_capability(tmp_path) -> None:
    database, session_id, _repository, service = _service(tmp_path)
    manager = UserPresenceApprovalManager()

    def verify(request, body: bytes) -> None:
        if not manager.consume(
            token=request.headers.get(USER_PRESENCE_HEADER),
            method=request.method,
            path=request.url.path,
            body=body,
        ):
            raise HTTPException(status_code=403, detail="native confirmation required")

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        declared_task_profile_service=service,
        user_presence_confirmation=verify,
        user_presence_confirmation_mode="native_bridge_bound_token",
    )
    path = f"/v1/sessions/{session_id}/declared-task-profile"
    body = json.dumps(
        _command().model_dump(mode="json"),
        separators=(",", ":"),
    ).encode("utf-8")
    token = manager.issue(
        method="POST",
        path=path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session").json()
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": "declared-profile-native-bridge-0001",
            CSRF_HEADER: browser["csrf_token"],
            USER_PRESENCE_HEADER: token,
            "Origin": "http://127.0.0.1",
        }
        created = client.post(path, headers=headers, content=body)
        replayed_capability = client.post(path, headers=headers, content=body)

    assert created.status_code == 201
    assert replayed_capability.status_code == 403


def test_profile_read_is_local_authenticated_and_save_is_browser_confirmed(
    tmp_path,
) -> None:
    app, session_id = _app(tmp_path)
    path = f"/v1/sessions/{session_id}/declared-task-profile"
    payload = _command().model_dump(mode="json")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        denied = client.get(path)
        empty = client.get(path, headers={API_TOKEN_HEADER: TOKEN})
        token_write = client.post(
            path,
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "declared-profile-token-write-0001",
            },
            json=payload,
        )
        browser = client.get("/auth/session")
        assert browser.json()["user_presence_confirmation_available"] is True
        assert browser.json()["user_presence_confirmation_mode"] == (
            "native_bridge_bound_token"
        )
        csrf = browser.json()["csrf_token"]
        created = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-browser-write-0001",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json=payload,
        )
        replay = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-browser-write-0001",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json=payload,
        )
        current = client.get(path, headers={API_TOKEN_HEADER: TOKEN})

    assert denied.status_code == 401
    assert empty.status_code == 200
    assert empty.json() == {
        "session_id": session_id,
        "profile": None,
        "confirmation_available": True,
    }
    assert token_write.status_code == 403
    assert token_write.json() == {"detail": "owned native confirmation required"}
    assert created.status_code == 201
    assert created.json()["applied"] is True
    assert replay.status_code == 200
    assert replay.json() == {**created.json(), "applied": False}
    assert current.json()["profile"] == created.json()["profile"]
    profile = current.json()["profile"]
    assert profile["constraint_kinds"] == ["cost", "privacy"]
    assert profile["expected_outcome_count"] == 2
    assert profile["deliverable_slots"] == ["artifact", "format"]
    assert "idempotency_key_digest" not in profile
    assert "command_fingerprint" not in profile
    for response in (empty, token_write, created, replay, current):
        _private(response)


def test_self_issued_browser_session_cannot_authorize_profile_measurement(
    tmp_path,
) -> None:
    app, session_id = _app(tmp_path, user_presence=False)
    path = f"/v1/sessions/{session_id}/declared-task-profile"
    payload = _command().model_dump(mode="json")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session")
        csrf = browser.json()["csrf_token"]
        attacked = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-self-issued-0001",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json=payload,
        )
        current = client.get(path, headers={API_TOKEN_HEADER: TOKEN})

    assert attacked.status_code == 503
    assert attacked.json() == {
        "detail": "user-presence confirmation is unavailable"
    }
    assert current.json() == {
        "session_id": session_id,
        "profile": None,
        "confirmation_available": False,
    }
    _private(attacked)
    _private(current)


def test_profile_mutation_rejects_csrf_origin_extra_content_and_stale_revision(
    tmp_path,
) -> None:
    app, session_id = _app(tmp_path)
    path = f"/v1/sessions/{session_id}/declared-task-profile"
    payload = _command().model_dump(mode="json")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session")
        csrf = browser.json()["csrf_token"]
        no_csrf = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-no-csrf-0001",
                "Origin": "http://127.0.0.1",
            },
            json=payload,
        )
        wrong_origin = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-wrong-origin-0001",
                CSRF_HEADER: csrf,
                "Origin": "https://attacker.invalid",
            },
            json=payload,
        )
        extra = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-extra-field-0001",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json={**payload, "note": "PRIVATE-PROFILE-CANARY"},
        )
        created = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-created-0001",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json=payload,
        )
        stale = client.post(
            path,
            headers={
                "Idempotency-Key": "declared-profile-stale-0001",
                CSRF_HEADER: csrf,
                "Origin": "http://127.0.0.1",
            },
            json={**payload, "expected_revision": None},
        )

    assert no_csrf.status_code == 403
    assert wrong_origin.status_code == 403
    assert extra.status_code == 422
    assert extra.json() == {"detail": "request validation failed"}
    assert "PRIVATE-PROFILE-CANARY" not in extra.text
    assert created.status_code == 201
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "declared_task_profile_revision_stale"
    for response in (no_csrf, wrong_origin, extra, created, stale):
        _private(response)


def test_openapi_profile_contract_has_no_free_text_surface(tmp_path) -> None:
    app, _session_id = _app(tmp_path)
    schema = app.openapi()
    assert "/v1/sessions/{session_id}/declared-task-profile" in schema["paths"]
    serialized = str(
        {
            key: value
            for key, value in schema["components"]["schemas"].items()
            if "DeclaredTaskProfile" in key
        }
    ).casefold()
    for prohibited in (
        "note",
        "comment",
        "prompt",
        "transcript",
        "excerpt",
        "workspace",
        "path",
    ):
        assert prohibited not in serialized
