"""No route may promise a body it is not allowed to send.

The composition root registers every router at import time, so a handler that
declares a body-forbidding status together with a resolved response model takes
the whole app down before the first request. This module pins both halves: the
real app still composes, the two shared-folder DELETE routes answer 204 with an
empty body, and no composed route anywhere carries a body contract under a
status code that forbids one.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from fastapi.utils import is_body_allowed_for_status_code

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


# FastAPI's own helper decides this, but the named codes are the contract we
# care about, so they stay written down here even if the helper moves.
BODY_FORBIDDING_STATUS_CODES = frozenset({100, 101, 102, 103, 204, 205, 304})


def _app(tmp_path: Path, monkeypatch):
    """One real composed app over a throwaway synthetic home."""

    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(tmp_path / "no-claude"))
    settings = AppSettings(home=tmp_path / "app-home")
    application = bootstrap_local_application(settings)
    http_app = application.create_http_app()
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    return settings, http_app, TestClient(http_app, base_url="http://127.0.0.1"), headers


def _forbids_body(status_code: object) -> bool:
    if status_code is None:
        return False
    try:
        numeric = int(status_code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if numeric in BODY_FORBIDDING_STATUS_CODES:
        return True
    return not is_body_allowed_for_status_code(numeric)


def _api_routes(app) -> list[APIRoute]:
    """Every APIRoute reachable from the app, including mounted sub-applications."""

    found: list[APIRoute] = []
    pending = [app]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for route in getattr(current, "routes", ()):
            if isinstance(route, APIRoute):
                found.append(route)
            # Mounts and other Starlette route types carry their own children.
            for child in (getattr(route, "app", None), route):
                if child is not None and child is not route and hasattr(child, "routes"):
                    pending.append(child)
    return found


def test_composition_root_builds_the_real_http_app(tmp_path: Path, monkeypatch) -> None:
    _settings, http_app, client, headers = _app(tmp_path, monkeypatch)

    assert _api_routes(http_app), "the composed app registered no API routes"
    # A trivial authorized call proves the app is not merely constructed but served.
    assert client.get("/v1/shared-folders", headers=headers).status_code == 200


def test_shared_folder_delete_routes_answer_204_with_an_empty_body(tmp_path: Path, monkeypatch) -> None:
    settings, http_app, client, headers = _app(tmp_path, monkeypatch)

    workspace = tmp_path / "team-notes"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Team notes\n", encoding="utf-8")

    share = client.post(
        "/v1/shared-folders",
        headers=headers,
        json={"path": str(workspace), "name": "team-notes"},
    )
    assert share.status_code == 201, share.text
    share_body = share.json()

    # Join the app's own share in-process so a link exists to leave; the
    # fictional host name never resolves, every byte stays in this process.
    from prompt_enhancer.application.shared_folders import (
        JoinRequest,
        PeerFolderClient,
        SharedFolderStore,
    )

    def fetch(method: str, url: str, token: str | None, body: bytes | None):
        assert url.startswith("http://peer.example")
        path = url.removeprefix("http://peer.example")
        request_headers = {"X-Share-Token": token} if token else {}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        response = client.request(method, path, headers=request_headers, content=body)
        return response.status_code, response.content

    joiner = PeerFolderClient(SharedFolderStore(settings.home / "shared-folders.sqlite3"), fetch=fetch)
    link = joiner.join(
        JoinRequest(
            url="http://peer.example",
            share_id=share_body["share_id"],
            share_token=share_body["share_token"],
            target=str(tmp_path / "joined-copy"),
        )
    )
    assert client.get("/v1/shared-folders/links", headers=headers).json()["links"]

    leave = client.delete(f"/v1/shared-folders/links/{link.link_id}", headers=headers)
    assert leave.status_code == 204, leave.text
    assert leave.content == b""
    assert client.get("/v1/shared-folders/links", headers=headers).json()["links"] == []

    revoke = client.delete(f"/v1/shared-folders/{share_body['share_id']}", headers=headers)
    assert revoke.status_code == 204, revoke.text
    assert revoke.content == b""
    listed = client.get("/v1/shared-folders", headers=headers).json()["shares"]
    assert [entry["share_id"] for entry in listed] == [share_body["share_id"]]
    assert listed[0]["revoked_at"] is not None

    # Revocation is final, and the failure path still speaks JSON.
    gone = client.delete(f"/v1/shared-folders/{share_body['share_id']}", headers=headers)
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "share_not_found"


def test_no_composed_route_promises_a_body_under_a_body_forbidding_status(tmp_path: Path, monkeypatch) -> None:
    _settings, http_app, _client, _headers = _app(tmp_path, monkeypatch)

    offenders = []
    for route in _api_routes(http_app):
        if not _forbids_body(getattr(route, "status_code", None)):
            continue
        declared = (
            getattr(route, "response_model", None),
            getattr(route, "response_field", None),
            getattr(route, "secure_cloned_response_field", None),
        )
        if any(field is not None for field in declared):
            offenders.append((sorted(route.methods), route.path, route.status_code, declared[0]))

    assert offenders == [], (
        "these routes declare a response body under a status code that forbids one; "
        f"return an explicit Response instead: {offenders}"
    )

    schema = http_app.openapi()
    documented = [
        (method, path, status)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if isinstance(operation, dict)
        for status, response in operation.get("responses", {}).items()
        if _forbids_body(status) and response.get("content")
    ]
    assert documented == [], f"OpenAPI documents a body for body-forbidding statuses: {documented}"
