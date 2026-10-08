"""Bounded, content-free discovery for one fictional Agent workspace."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService
from prompt_enhancer.application.local_agent_discovery import (
    LocalAgentWorkspaceDiscovery,
    WorkspaceDiscovery,
)
from prompt_enhancer.application.local_agent_limits import LocalAgentError
from prompt_enhancer.application.local_agent_workspace import WorkspaceGitStatusSnapshot, WorkspaceTools
from prompt_enhancer.application.local_command_process import CommandResult
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


SESSION = "a" * 32
ZERO = "0" * 40
ONE = "1" * 40


def _result(stdout: str, *, code: int = 0, truncated: bool = False) -> CommandResult:
    return CommandResult(["git"], code, stdout, "EXAMPLE_PRIVATE_GIT_STDERR", truncated=truncated)


def _porcelain() -> str:
    return "".join((
        f"1 M. N... 100644 100644 100644 {ZERO} {ONE} src/example.py\0",
        "? notes.txt\0",
        f"2 R. N... 100644 100644 100644 {ZERO} {ONE} R100 renamed.txt\0old.txt\0",
        f"u UU N... 100644 100644 100644 100644 {ZERO} {ONE} {ZERO} conflict.txt\0",
    ))


def test_discovery_inventory_and_git_status_are_bounded_content_free_and_sanitized(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("EXAMPLE_PRIVATE_SOURCE_CANARY", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("fictional notes", encoding="utf-8")
    (tmp_path / "old.txt").write_text("old", encoding="utf-8")
    (tmp_path / "renamed.txt").write_text("renamed", encoding="utf-8")
    (tmp_path / "conflict.txt").write_text("conflict", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "excluded.txt").write_text("EXAMPLE_EXCLUDED_CANARY", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return _result(_porcelain())

    snapshot = LocalAgentWorkspaceDiscovery().snapshot(
        SESSION,
        WorkspaceTools(tmp_path, runner=runner),
    )

    assert snapshot.contract_version == "local-agent-workspace-discovery.v1"
    assert snapshot.session_id == SESSION and snapshot.scope == "selected_workspace"
    assert snapshot.inventory_coverage == "partial"
    assert "excluded_directories" in snapshot.inventory_reasons
    assert {item.path for item in snapshot.files} == {
        "conflict.txt", "notes.txt", "old.txt", "renamed.txt", "src/example.py",
    }
    assert snapshot.observed_file_count == 5
    assert snapshot.git_state == "available" and snapshot.git_coverage == "complete"
    assert snapshot.git_change_count == 4
    assert [(item.path, item.kind, item.staged, item.unstaged) for item in snapshot.git_changes] == [
        ("conflict.txt", "conflicted", True, True),
        ("notes.txt", "untracked", False, False),
        ("renamed.txt", "renamed", True, False),
        ("src/example.py", "modified", True, False),
    ]
    dumped = snapshot.model_dump_json()
    assert "EXAMPLE_PRIVATE_SOURCE_CANARY" not in dumped
    assert "EXAMPLE_PRIVATE_GIT_STDERR" not in dumped
    assert str(tmp_path) not in dumped
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == "git" and "status" in argv and "--porcelain=v2" in argv
    assert not any(word in argv for word in ("fetch", "pull", "push", "remote"))
    assert kwargs["cwd"] == str(tmp_path)
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"]
    assert environment["GIT_CONFIG_SYSTEM"]
    assert environment["GIT_CEILING_DIRECTORIES"] == str(tmp_path)
    assert environment["GIT_DISCOVERY_ACROSS_FILESYSTEM"] == "0"
    assert environment["GIT_NO_LAZY_FETCH"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"


def test_non_repository_does_not_spawn_git_and_reports_not_applicable(tmp_path):
    (tmp_path / "example.txt").write_text("example", encoding="utf-8")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Git must not run without a .git directory at the selected root")

    snapshot = LocalAgentWorkspaceDiscovery().snapshot(
        SESSION,
        WorkspaceTools(tmp_path, runner=unexpected),
    )
    assert snapshot.inventory_coverage == "complete"
    assert snapshot.observed_file_count == 1
    assert snapshot.git_state == "not_repository"
    assert snapshot.git_coverage == "not_applicable"
    assert snapshot.git_change_count == 0 and snapshot.git_changes == ()


@pytest.mark.parametrize(
    ("relative", "payload"),
    [
        ("commondir", "../EXAMPLE_EXTERNAL_GIT_DIR\n"),
        ("objects/info/alternates", "../../../EXAMPLE_EXTERNAL_OBJECTS\n"),
        ("objects/info/http-alternates", "https://example.invalid/objects\n"),
        ("config", '[include]\n\tpath = ../EXAMPLE_EXTERNAL_CONFIG\n'),
        ("config", '[filter "example"]\n\tclean = EXAMPLE_PRIVATE_COMMAND\n'),
        ("config", '[filter.example]\n\tprocess = EXAMPLE_PRIVATE_COMMAND\n'),
        ("config.worktree", '[core]\n\tworktree = ../EXAMPLE_EXTERNAL_TREE\n'),
    ],
)
def test_git_metadata_indirections_are_refused_before_process_start(tmp_path, relative, payload):
    git_directory = tmp_path / ".git"
    target = git_directory / Path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Git must not run for metadata that can redirect outside the selected root")

    snapshot = WorkspaceTools(tmp_path, runner=unexpected).git_status()

    assert snapshot == _git_unavailable_fixture("repository_layout_unsupported")


def test_git_file_layout_is_refused_without_process_start(tmp_path):
    (tmp_path / ".git").write_text("gitdir: ../EXAMPLE_EXTERNAL_GIT_DIR\n", encoding="utf-8")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Git must not run for a gitfile/worktree layout")

    assert WorkspaceTools(tmp_path, runner=unexpected).git_status() == _git_unavailable_fixture(
        "repository_layout_unsupported"
    )


def test_git_status_preserves_workspace_root_replacement_authority(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    tools = WorkspaceTools(tmp_path, runner=lambda *_args, **_kwargs: _result(""))
    original = tools._inspection.directory_identity

    def changed(target, *args, **kwargs):
        if target == tmp_path:
            raise LocalAgentError("workspace_root_changed")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(tools._inspection, "directory_identity", changed)
    with pytest.raises(LocalAgentError) as caught:
        tools.git_status()
    assert caught.value.code == "workspace_root_changed"


def test_git_status_does_not_label_a_missing_workspace_as_non_repository(tmp_path):
    tools = WorkspaceTools(tmp_path, runner=lambda *_args, **_kwargs: _result(""))
    tmp_path.rmdir()

    with pytest.raises(LocalAgentError) as caught:
        tools.git_status()
    assert caught.value.code == "workspace_root_changed"


def test_git_status_discards_output_when_repository_metadata_changes(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    tools = WorkspaceTools(tmp_path, runner=lambda *_args, **_kwargs: _result("? EXAMPLE_PRIVATE_PATH\0"))
    original = tools._inspection.directory_identity
    calls = 0

    def changed(target, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise LocalAgentError("workspace_link_or_reparse_refused")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(tools._inspection, "directory_identity", changed)
    snapshot = tools.git_status()
    assert snapshot == _git_unavailable_fixture("repository_changed")


def test_duplicate_git_paths_fail_closed_as_invalid_status(tmp_path):
    (tmp_path / ".git").mkdir()
    tools = WorkspaceTools(tmp_path, runner=lambda *_args, **_kwargs: _result("? duplicate.txt\0? duplicate.txt\0"))

    assert tools.git_status() == _git_unavailable_fixture("status_invalid")


def _git_unavailable_fixture(reason: str):
    return WorkspaceGitStatusSnapshot("unavailable", "unavailable", (reason,), None, ())


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("truncated", "output_limit"),
        ("timeout", "deadline_reached"),
        ("missing", "executable_unavailable"),
        ("failed", "status_failed"),
    ],
)
def test_git_failures_are_fixed_content_free_unavailable_states(tmp_path, failure, reason):
    (tmp_path / ".git").mkdir()

    def runner(*_args, **_kwargs):
        if failure == "truncated":
            return _result("EXAMPLE_PRIVATE_PARTIAL_PATH\0", truncated=True)
        if failure == "timeout":
            raise subprocess.TimeoutExpired("EXAMPLE_PRIVATE_COMMAND", 5, output="EXAMPLE_PRIVATE_OUTPUT")
        if failure == "missing":
            raise FileNotFoundError("EXAMPLE_PRIVATE_EXECUTABLE")
        return _result("", code=128)

    snapshot = LocalAgentWorkspaceDiscovery().snapshot(
        SESSION,
        WorkspaceTools(tmp_path, runner=runner),
    )
    assert snapshot.git_state == "unavailable"
    assert snapshot.git_coverage == "unavailable"
    assert snapshot.git_reasons == (reason,)
    assert snapshot.git_change_count is None and snapshot.git_changes == ()
    dumped = snapshot.model_dump_json()
    assert "EXAMPLE_PRIVATE" not in dumped and str(tmp_path) not in dumped


def test_discovery_contract_rejects_incoherent_complete_inventory():
    with pytest.raises(ValidationError):
        WorkspaceDiscovery(
            session_id=SESSION,
            scope="selected_workspace",
            inventory_coverage="complete",
            inventory_reasons=("entry_limit",),
            scanned_entry_count=0,
            observed_file_count=0,
            files=(),
            git_state="not_repository",
            git_coverage="not_applicable",
            git_reasons=(),
            git_change_count=0,
            git_changes=(),
        )


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable unavailable")
def test_real_git_status_uses_the_selected_synthetic_root_only(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True, capture_output=True)
    (tmp_path / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    snapshot = LocalAgentWorkspaceDiscovery().snapshot(SESSION, WorkspaceTools(tmp_path))

    assert snapshot.git_state == "available"
    assert snapshot.git_coverage == "complete"
    assert snapshot.git_change_count == 2
    assert {(item.path, item.kind) for item in snapshot.git_changes} == {
        ("tracked.txt", "added"), ("untracked.txt", "untracked"),
    }


def test_http_discovery_is_private_and_replaced_root_fails_closed(tmp_path, monkeypatch):
    workspace = tmp_path / "example-project"
    workspace.mkdir()
    (workspace / "example.txt").write_text("EXAMPLE_PRIVATE_FILE_CANARY", encoding="utf-8")
    settings = AppSettings(home=tmp_path / "example-app")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(AgentSettings(workspace=str(workspace)))
    monkeypatch.setattr(
        type(application),
        "create_local_agent_service",
        lambda self, local_model_service=None, *, mcp_managed_runtime_service=None: service,
    )
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    url = f"/v1/agent/sessions/{view.session_id}/workspace/discovery"
    try:
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        assert response.headers["pragma"] == "no-cache"
        assert response.json()["files"][0]["path"] == "example.txt"
        assert "EXAMPLE_PRIVATE_FILE_CANARY" not in response.text
        assert str(workspace) not in response.text

        workspace.rename(workspace.parent / "example-original")
        workspace.mkdir()
        response = client.get(url, headers=headers)
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "workspace_root_changed"}}
        assert "example-original" not in response.text
    finally:
        client.close()
        service.shutdown(timeout=2)
