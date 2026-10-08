"""Shared team folders (ADR 0018): share registry, token-gated p2p surface,
peer client pull/push with conflict copies - two sides over the real routes."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import sqlite3

import pytest

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


def test_share_store_closes_connections_on_success_and_error(tmp_path: Path, monkeypatch) -> None:
    from prompt_enhancer.application import shared_folders

    opened: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def capture(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)  # Retain it so garbage collection cannot hide a leak.
        return connection

    monkeypatch.setattr(shared_folders.sqlite3, "connect", capture)
    store = shared_folders.SharedFolderStore(tmp_path / "example-shares.sqlite3")
    assert store.list_shares() == []
    assert store.list_links() == []
    with pytest.raises(ValueError, match="example_transaction_aborted"):
        with store._connect() as connection:
            connection.execute("CREATE TABLE example_rollback (value TEXT)")
            connection.execute("INSERT INTO example_rollback VALUES ('example')")
            raise ValueError("example_transaction_aborted")
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM example_rollback").fetchone()[0] == 0


def _apps(tmp_path: Path, monkeypatch):
    """Two app instances: 'owner' shares a folder, 'peer' joins it in-process."""

    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(tmp_path / "no-claude"))
    owner_settings = AppSettings(home=tmp_path / "owner-home")
    owner = bootstrap_local_application(owner_settings)
    owner_client = TestClient(owner.create_http_app(), base_url="http://127.0.0.1")
    owner_headers = {API_TOKEN_HEADER: owner_settings.api_token_path.read_text(encoding="utf-8").strip()}

    peer_settings = AppSettings(home=tmp_path / "peer-home")
    peer = bootstrap_local_application(peer_settings)

    # The peer's outbound fetch is routed into the owner's ASGI app in-process,
    # so the whole wire format is exercised without sockets.
    def fetch(method: str, url: str, token: str | None, body: bytes | None):
        assert url.startswith("http://owner.example")
        path = url.removeprefix("http://owner.example")
        headers = {"X-Share-Token": token} if token else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        response = owner_client.request(method, path, headers=headers, content=body)
        return response.status_code, response.content

    from prompt_enhancer.application.shared_folders import PeerFolderClient, SharedFolderStore

    peer_store = SharedFolderStore(peer_settings.home / "shared-folders.sqlite3")
    peer_client_service = PeerFolderClient(peer_store, fetch=fetch)

    def peer_app_factory():
        return peer.create_http_app()

    peer_http = TestClient(peer_app_factory(), base_url="http://127.0.0.1")
    peer_headers = {API_TOKEN_HEADER: peer_settings.api_token_path.read_text(encoding="utf-8").strip()}
    return owner_client, owner_headers, peer_client_service, peer_http, peer_headers


def test_share_registry_token_gate_and_file_surface(tmp_path: Path, monkeypatch) -> None:
    owner_client, owner_headers, _, _, _ = _apps(tmp_path, monkeypatch)

    workspace = tmp_path / "team-docs"
    (workspace / "notes").mkdir(parents=True)
    (workspace / "README.md").write_text("# Team docs\n", encoding="utf-8")
    (workspace / "notes" / "plan.md").write_text("- step one\n", encoding="utf-8")

    # Sharing needs an existing absolute folder; the app home is off limits.
    bad = owner_client.post("/v1/shared-folders", headers=owner_headers, json={"path": str(tmp_path / "missing"), "name": "x"})
    assert bad.status_code == 422
    home_share = owner_client.post("/v1/shared-folders", headers=owner_headers, json={"path": str(tmp_path / "owner-home"), "name": "home"})
    assert home_share.status_code == 403, home_share.text

    created = owner_client.post("/v1/shared-folders", headers=owner_headers, json={"path": str(workspace), "name": "team-docs"})
    assert created.status_code == 201, created.text
    share = created.json()
    token = share["share_token"]
    assert token and share["share_id"]

    # The token is never listed again.
    listed = owner_client.get("/v1/shared-folders", headers=owner_headers).json()
    assert listed["shares"][0]["share_token"] is None

    # Peer surface: no token -> 401; right token -> manifest with both files.
    assert owner_client.get(f"/p2p/v1/{share['share_id']}/manifest").status_code == 401
    manifest = owner_client.get(f"/p2p/v1/{share['share_id']}/manifest", headers={"X-Share-Token": token})
    assert manifest.status_code == 200, manifest.text
    paths = {entry["path"] for entry in manifest.json()["files"]}
    assert paths == {"README.md", "notes/plan.md"}

    # Read, then a clean write with the right base hash.
    readme = owner_client.get(f"/p2p/v1/{share['share_id']}/files/README.md", headers={"X-Share-Token": token}).json()
    new_content = base64.b64encode(b"# Team docs\nUpdated by peer.\n").decode("ascii")
    written = owner_client.put(
        f"/p2p/v1/{share['share_id']}/files/README.md",
        headers={"X-Share-Token": token},
        json={"content_b64": new_content, "base_sha256": readme["sha256"], "peer_name": "alex"},
    )
    assert written.status_code == 200 and written.json()["conflict"] is False
    assert (workspace / "README.md").read_text(encoding="utf-8").endswith("Updated by peer.\n")

    # A write based on a stale hash becomes a conflict copy; the original stays.
    stale = owner_client.put(
        f"/p2p/v1/{share['share_id']}/files/README.md",
        headers={"X-Share-Token": token},
        json={"content_b64": base64.b64encode(b"clobber\n").decode("ascii"), "base_sha256": readme["sha256"], "peer_name": "alex"},
    )
    assert stale.status_code == 200 and stale.json()["conflict"] is True
    assert "conflict-alex" in stale.json()["stored_as"]
    assert (workspace / "README.md").read_text(encoding="utf-8").endswith("Updated by peer.\n")
    assert any("conflict-alex" in p.name for p in workspace.glob("README.conflict-*"))

    # Traversal is rejected; revocation closes the surface immediately.
    traversal = owner_client.get(f"/p2p/v1/{share['share_id']}/files/../secret.txt", headers={"X-Share-Token": token})
    assert traversal.status_code in {404, 422}
    assert owner_client.delete(f"/v1/shared-folders/{share['share_id']}", headers=owner_headers).status_code == 204
    assert owner_client.get(f"/p2p/v1/{share['share_id']}/manifest", headers={"X-Share-Token": token}).status_code == 401


def test_peer_joins_pulls_edits_and_pushes_back(tmp_path: Path, monkeypatch) -> None:
    owner_client, owner_headers, peer_client_service, _, _ = _apps(tmp_path, monkeypatch)

    workspace = tmp_path / "team-project"
    workspace.mkdir()
    (workspace / "SPEC.md").write_text("# Spec\nv1\n", encoding="utf-8")

    share = owner_client.post("/v1/shared-folders", headers=owner_headers, json={"path": str(workspace), "name": "team-project"}).json()

    from prompt_enhancer.application.shared_folders import JoinRequest

    target = tmp_path / "peer-copy"
    link = peer_client_service.join(JoinRequest(url="http://owner.example", share_id=share["share_id"], share_token=share["share_token"], target=str(target)))
    assert link.name == "team-project"

    # Pull mirrors the folder; a second pull skips unchanged files.
    report = peer_client_service.pull(link.link_id)
    assert report.pulled == 1 and (target / "SPEC.md").read_text(encoding="utf-8") == "# Spec\nv1\n"
    again = peer_client_service.pull(link.link_id)
    assert again.pulled == 0 and again.skipped == 1

    # The peer's agent (any tool) edits locally; push sends it back cleanly.
    (target / "SPEC.md").write_text("# Spec\nv2 - reviewed by the peer's agent\n", encoding="utf-8")
    (target / "NOTES.md").write_text("fresh file from the peer\n", encoding="utf-8")
    pushed = peer_client_service.push(link.link_id, peer_name="peer-agent")
    assert pushed.pushed == 2 and pushed.conflicts == 0
    assert (workspace / "SPEC.md").read_text(encoding="utf-8").startswith("# Spec\nv2")
    assert (workspace / "NOTES.md").read_text(encoding="utf-8") == "fresh file from the peer\n"

    # Concurrent edit on the owner side -> the peer's next push conflicts, both survive.
    (workspace / "SPEC.md").write_text("# Spec\nv2 - owner's parallel edit\n", encoding="utf-8")
    (target / "SPEC.md").write_text("# Spec\nv3 from the peer\n", encoding="utf-8")
    conflicted = peer_client_service.push(link.link_id, peer_name="peer-agent")
    assert conflicted.conflicts == 1
    assert (workspace / "SPEC.md").read_text(encoding="utf-8").endswith("owner's parallel edit\n")
    assert any("conflict-peer-agent" in p.name for p in workspace.glob("SPEC.conflict-*"))

    # Leaving removes the link.
    peer_client_service.leave(link.link_id)
    links = peer_client_service.list()
    assert links.links == ()
