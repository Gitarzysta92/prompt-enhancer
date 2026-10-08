from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, CSRF_HEADER
from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService
from prompt_enhancer.application.local_agent_changes import (
    CHANGE_RESTORE_CONFIRMATION,
    AgentChangeRestoreApplyCommand,
    AgentChangeRestorePreviewCommand,
    AgentChangeDiff,
    AgentChangeSet,
    AgentChangeTracker,
    AgentChangedFile,
)
from prompt_enhancer.application.local_agent_editor import (
    WORKSPACE_APPLY_CONFIRMATION,
    WorkspaceApplyCommand,
    WorkspaceLineEnding,
    WorkspacePreviewCommand,
)
from prompt_enhancer.application.local_agent_receipts import AgentWriteReceipt
from prompt_enhancer.application.local_agent_workspace import ToolOutcome
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "fictional-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"one\n")
    return root


def _service(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[LocalAgentService, str]:
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(AgentSettings(workspace=str(root), model_alias="example-model"))
    monkeypatch.setattr(service, "_await_approval", lambda *_args, **_kwargs: True)
    return service, view.session_id


def test_reviewed_change_set_tracks_current_net_effect_and_manual_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001 - integration boundary under test

    assert service._execute(  # noqa: SLF001 - exact protected-write integration
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "created.txt", "content": "new\n"}
    ).ok

    opened = service.workspace_file(session_id, "alpha.txt")
    preview = service.preview_workspace_edit(
        session_id,
        WorkspacePreviewCommand(
            path=opened.path,
            content="three\n",
            expected_revision=opened.revision,
            line_ending=opened.line_ending,
        ),
    )
    service.apply_workspace_edit(
        session_id,
        preview.preview_id,
        WorkspaceApplyCommand(
            path=preview.path,
            content="three\n",
            expected_revision=preview.expected_revision,
            proposed_revision=preview.proposed_revision,
            line_ending=preview.line_ending,
            confirmation=WORKSPACE_APPLY_CONFIRMATION,
        ),
    )

    change_set = service.change_set(session_id)
    assert change_set.contract_version == "agent-change-set.v1"
    assert change_set.scope == "reviewed_paths_only"
    assert change_set.coverage == "complete"
    assert change_set.reviewed_writes == 3
    assert change_set.agent_writes == 2
    assert change_set.manual_writes == 1
    assert change_set.unverified_writes == 0
    assert change_set.command_attempts == 0
    files = {item.path: item for item in change_set.files}
    assert files["alpha.txt"].net_effect == "modified"
    assert files["alpha.txt"].verification == "verified"
    assert files["alpha.txt"].reviewed_writes == 2
    assert files["created.txt"].net_effect == "created"

    detail = service.change_diff(session_id, "alpha.txt")
    assert detail.summary == files["alpha.txt"]
    assert detail.diff_state == "available"
    assert detail.diff is not None
    assert detail.diff.splitlines()[:2] == ["--- a/alpha.txt", "+++ b/alpha.txt"]
    assert "-one" in detail.diff and "+three" in detail.diff


def test_reversion_and_external_divergence_are_not_reported_as_current_verified_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001

    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "one\n"}
    ).ok

    reverted = service.change_set(session_id)
    assert reverted.coverage == "complete"
    assert len(reverted.files) == 1
    assert reverted.files[0].net_effect == "reverted"
    assert reverted.files[0].verification == "verified"
    no_diff = service.change_diff(session_id, "alpha.txt")
    assert no_diff.diff_state == "no_change"
    assert no_diff.diff is None
    assert no_diff.added_lines == 0 and no_diff.removed_lines == 0

    (root / "alpha.txt").write_text("outside\n", encoding="utf-8")
    diverged = service.change_set(session_id)
    assert diverged.coverage == "partial"
    assert diverged.files[0].net_effect == "modified"
    assert diverged.files[0].verification == "partial"
    assert diverged.files[0].reason == "current_revision_changed"
    current_diff = service.change_diff(session_id, "alpha.txt")
    assert current_diff.diff_state == "available"
    assert current_diff.diff is not None and "+outside" in current_diff.diff


def test_reviewed_change_restore_previews_and_verifies_the_exact_session_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok

    current = service.workspace_file(session_id, "alpha.txt")
    preview = service.preview_change_restore(
        session_id,
        AgentChangeRestorePreviewCommand(path="alpha.txt"),
    )
    assert preview.contract_version == "agent-change-restore.v1"
    assert preview.operation == "edit"
    assert preview.baseline_state == "present"
    assert preview.expected_revision == current.revision
    assert preview.restored_revision != current.revision
    assert preview.diff_state == "available"
    assert preview.diff is not None
    assert preview.diff.splitlines()[:2] == ["--- a/alpha.txt", "+++ b/alpha.txt"]
    assert "-two" in preview.diff and "+one" in preview.diff
    assert preview.requires_native_confirmation is True

    result = service.apply_change_restore(
        session_id,
        preview.preview_id,
        AgentChangeRestoreApplyCommand(
            path=preview.path,
            operation=preview.operation,
            expected_revision=preview.expected_revision,
            restored_revision=preview.restored_revision,
            confirmation=CHANGE_RESTORE_CONFIRMATION,
        ),
    )
    assert result.net_effect == "reverted"
    assert result.filesystem_verification == "verified"
    assert result.change_set_verification == "verified"
    assert result.current_revision == preview.restored_revision
    assert (root / "alpha.txt").read_bytes() == b"one\n"
    assert service.change_set(session_id).files[0].net_effect == "reverted"

    with pytest.raises(Exception) as replayed:
        service.apply_change_restore(
            session_id,
            preview.preview_id,
            AgentChangeRestoreApplyCommand(
                path=preview.path,
                operation=preview.operation,
                expected_revision=preview.expected_revision,
                restored_revision=preview.restored_revision,
                confirmation=CHANGE_RESTORE_CONFIRMATION,
            ),
        )
    assert getattr(replayed.value, "code", None) in {
        "change_already_reverted",
        "workspace_preview_not_found",
    }


def test_change_restore_recreates_a_missing_baseline_without_hiding_the_chain_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    (root / "alpha.txt").unlink()

    preview = service.preview_change_restore(
        session_id,
        AgentChangeRestorePreviewCommand(path="alpha.txt"),
    )
    assert preview.operation == "recreate"
    assert preview.expected_revision is None
    assert preview.baseline_state == "present"
    assert preview.diff is not None
    assert preview.diff.splitlines()[:2] == ["--- /dev/null", "+++ b/alpha.txt"]

    result = service.apply_change_restore(
        session_id,
        preview.preview_id,
        AgentChangeRestoreApplyCommand(
            path=preview.path,
            operation=preview.operation,
            expected_revision=None,
            restored_revision=preview.restored_revision,
            confirmation=CHANGE_RESTORE_CONFIRMATION,
        ),
    )
    assert result.current_revision == preview.restored_revision
    assert result.change_set_verification == "partial"
    assert result.change_set_reason == "review_chain_gap"
    assert (root / "alpha.txt").read_bytes() == b"one\n"


def test_change_restore_recovers_the_exact_retained_crlf_representation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    (root / "alpha.txt").write_bytes(b"one\r\n")
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "one\n"}
    ).ok

    current = service.workspace_file(session_id, "alpha.txt")
    with pytest.raises(Exception) as ordinary_edit:
        service.preview_workspace_edit(
            session_id,
            WorkspacePreviewCommand(
                path="alpha.txt",
                content="one\n",
                expected_revision=current.revision,
                line_ending=WorkspaceLineEnding.CRLF,
            ),
        )
    assert getattr(ordinary_edit.value, "code", None) == "workspace_line_ending_changed"

    preview = service.preview_change_restore(
        session_id,
        AgentChangeRestorePreviewCommand(path="alpha.txt"),
    )
    assert preview.operation == "edit"
    assert preview.line_ending == "crlf"
    assert preview.diff_state == "line_ending_only"
    assert preview.diff is None

    result = service.apply_change_restore(
        session_id,
        preview.preview_id,
        AgentChangeRestoreApplyCommand(
            path=preview.path,
            operation=preview.operation,
            expected_revision=preview.expected_revision,
            restored_revision=preview.restored_revision,
            confirmation=CHANGE_RESTORE_CONFIRMATION,
        ),
    )
    assert result.filesystem_verification == "verified"
    assert result.current_revision == preview.restored_revision
    assert (root / "alpha.txt").read_bytes() == b"one\r\n"


@pytest.mark.skipif(os.name != "nt", reason="recoverable file trash is Windows-only")
def test_change_restore_moves_a_session_created_file_to_the_recycle_bin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "created.txt", "content": "new\n"}
    ).ok

    preview = service.preview_change_restore(
        session_id,
        AgentChangeRestorePreviewCommand(path="created.txt"),
    )
    assert preview.operation == "trash_created"
    assert preview.baseline_state == "absent"
    assert preview.recovery == "windows_recycle_bin"
    assert preview.permanent is False
    assert preview.restored_revision is None
    assert preview.diff is not None
    assert preview.diff.splitlines()[:2] == ["--- a/created.txt", "+++ /dev/null"]

    result = service.apply_change_restore(
        session_id,
        preview.preview_id,
        AgentChangeRestoreApplyCommand(
            path=preview.path,
            operation=preview.operation,
            expected_revision=preview.expected_revision,
            restored_revision=None,
            confirmation=CHANGE_RESTORE_CONFIRMATION,
        ),
    )
    assert result.recovery == "windows_recycle_bin"
    assert result.current_revision is None
    assert result.net_effect == "reverted"
    assert not (root / "created.txt").exists()


def test_change_restore_rechecks_the_current_revision_before_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    preview = service.preview_change_restore(
        session_id,
        AgentChangeRestorePreviewCommand(path="alpha.txt"),
    )
    (root / "alpha.txt").write_bytes(b"external\n")

    with pytest.raises(Exception) as stale:
        service.apply_change_restore(
            session_id,
            preview.preview_id,
            AgentChangeRestoreApplyCommand(
                path=preview.path,
                operation=preview.operation,
                expected_revision=preview.expected_revision,
                restored_revision=preview.restored_revision,
                confirmation=CHANGE_RESTORE_CONFIRMATION,
            ),
        )
    assert getattr(stale.value, "code", None) == "change_restore_mismatch"
    assert (root / "alpha.txt").read_bytes() == b"external\n"


def test_change_restore_refuses_unretained_or_already_restored_baselines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    session.changes = AgentChangeTracker(max_baseline_bytes=0)
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    with pytest.raises(Exception) as unavailable:
        service.preview_change_restore(
            session_id,
            AgentChangeRestorePreviewCommand(path="alpha.txt"),
        )
    assert getattr(unavailable.value, "code", None) == "change_restore_baseline_unavailable"

    session.changes = AgentChangeTracker()
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "three\n"}
    ).ok
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    with pytest.raises(Exception) as complete:
        service.preview_change_restore(
            session_id,
            AgentChangeRestorePreviewCommand(path="alpha.txt"),
        )
    assert getattr(complete.value, "code", None) == "change_already_reverted"


def test_unverified_publication_and_commands_keep_change_set_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001

    def uncertain(prepared):
        return ToolOutcome(
            False,
            "publication uncertain",
            "workspace_verification_failed",
            write_receipt=AgentWriteReceipt(
                path=prepared.path,
                state="unverified",
                before_sha256=prepared.base_sha256,
            ),
        )

    monkeypatch.setattr(session.tools, "apply_prepared_write", uncertain)
    outcome = service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "uncertain\n"}
    )
    assert not outcome.ok and outcome.write_receipt is not None

    monkeypatch.setattr(
        session.tools,
        "run_command",
        lambda *_args, **_kwargs: ToolOutcome(True, "synthetic command", untracked_command=True),
    )
    assert service._execute(session, "run_command", {"command": "synthetic"}).ok  # noqa: SLF001

    change_set = service.change_set(session_id)
    assert change_set.coverage == "partial"
    assert change_set.reviewed_writes == 1
    assert change_set.unverified_writes == 1
    assert change_set.command_attempts == 1
    assert change_set.files[0].verification == "unverified"
    assert change_set.files[0].reason == "publication_unverified"
    detail = service.change_diff(session_id, "alpha.txt")
    assert detail.diff_state == "no_change"
    assert detail.diff is None


def test_http_change_set_is_private_session_bound_and_strictly_path_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    settings = AppSettings(home=tmp_path / "synthetic-home")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    service, session_id = _service(root, monkeypatch)
    monkeypatch.setattr(
        type(application),
        "create_local_agent_service",
        lambda self, local_model_service=None, *, mcp_managed_runtime_service=None: service,
    )
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "alpha.txt", "content": "two\n"},
    ).ok
    confirmations: list[str] = []

    def confirm(request, _body) -> None:
        confirmations.append(request.url.path)

    with TestClient(
        application.create_http_app(user_presence_confirmation=confirm),
        base_url="http://127.0.0.1",
    ) as client:
        token = settings.api_token_path.read_text(encoding="utf-8").strip()
        headers = {API_TOKEN_HEADER: token}
        response = client.get(f"/v1/agent/sessions/{session_id}/changes", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        assert response.json()["files"][0]["path"] == "alpha.txt"
        diff = client.get(
            f"/v1/agent/sessions/{session_id}/changes/diff",
            params={"path": "alpha.txt"},
            headers=headers,
        )
        assert diff.status_code == 200
        assert diff.headers["cache-control"] == "no-store, private"
        assert diff.json()["diff"].splitlines()[:2] == [
            "--- a/alpha.txt",
            "+++ b/alpha.txt",
        ]
        missing = client.get(
            f"/v1/agent/sessions/{session_id}/changes/diff",
            params={"path": "other.txt"},
            headers=headers,
        )
        assert missing.status_code == 404
        assert missing.json() == {"detail": {"code": "change_path_not_found"}}
        for invalid_path in (
            "../alpha.txt",
            "/alpha.txt",
            "alpha\\beta.txt",
            "C:/alpha.txt",
            "alpha//beta.txt",
        ):
            invalid = client.get(
                f"/v1/agent/sessions/{session_id}/changes/diff",
                params={"path": invalid_path},
                headers=headers,
            )
            assert invalid.status_code == 404
            assert invalid.json() == {"detail": {"code": "change_path_not_found"}}

        restore_preview_response = client.post(
            f"/v1/agent/sessions/{session_id}/changes/restores",
            json={"path": "alpha.txt"},
            headers=headers,
        )
        assert restore_preview_response.status_code == 201
        assert restore_preview_response.headers["cache-control"] == "no-store, private"
        restore_preview = restore_preview_response.json()
        assert restore_preview["operation"] == "edit"
        token_apply = client.post(
            f"/v1/agent/sessions/{session_id}/changes/restores/"
            f"{restore_preview['preview_id']}/apply",
            json={
                "path": restore_preview["path"],
                "operation": restore_preview["operation"],
                "expected_revision": restore_preview["expected_revision"],
                "restored_revision": restore_preview["restored_revision"],
                "confirmation": CHANGE_RESTORE_CONFIRMATION,
            },
            headers=headers,
        )
        assert token_apply.status_code == 403
        browser = client.get("/auth/session")
        browser_headers = {
            CSRF_HEADER: browser.json()["csrf_token"],
            "Origin": "http://127.0.0.1",
        }
        restored = client.post(
            f"/v1/agent/sessions/{session_id}/changes/restores/"
            f"{restore_preview['preview_id']}/apply",
            json={
                "path": restore_preview["path"],
                "operation": restore_preview["operation"],
                "expected_revision": restore_preview["expected_revision"],
                "restored_revision": restore_preview["restored_revision"],
                "confirmation": CHANGE_RESTORE_CONFIRMATION,
            },
            headers=browser_headers,
        )
        assert restored.status_code == 200, restored.text
        assert restored.headers["cache-control"] == "no-store, private"
        assert restored.json()["net_effect"] == "reverted"
        assert confirmations == [
            f"/v1/agent/sessions/{session_id}/changes/restores/"
            f"{restore_preview['preview_id']}/apply"
        ]


def test_line_ending_only_change_and_external_deletion_remain_truthful(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    (root / "alpha.txt").write_bytes(b"one\r\n")
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "alpha.txt", "content": "one\n"},
    ).ok
    line_only = service.change_diff(session_id, "alpha.txt")
    assert line_only.summary.net_effect == "modified"
    assert line_only.summary.verification == "verified"
    assert line_only.diff_state == "line_ending_only"
    assert line_only.diff is None

    (root / "alpha.txt").unlink()
    deleted = service.change_diff(session_id, "alpha.txt")
    assert deleted.summary.net_effect == "deleted"
    assert deleted.summary.verification == "partial"
    assert deleted.summary.reason == "current_file_missing"
    assert deleted.diff_state == "available"
    assert deleted.diff is not None
    assert deleted.diff.splitlines()[:2] == ["--- a/alpha.txt", "+++ /dev/null"]


def test_review_chain_gap_stays_partial_after_a_later_verified_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "two\n"}
    ).ok
    (root / "alpha.txt").write_bytes(b"external\n")
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "three\n"}
    ).ok

    change_set = service.change_set(session_id)
    assert change_set.coverage == "partial"
    assert change_set.files[0].net_effect == "modified"
    assert change_set.files[0].verification == "partial"
    assert change_set.files[0].reason == "review_chain_gap"
    assert service.change_diff(session_id, "alpha.txt").diff is not None


def test_noops_active_turn_and_tracking_limits_never_claim_complete_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    (root / "second.txt").write_bytes(b"second\n")
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001

    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "one\n"}
    ).ok
    noops = service.change_set(session_id)
    assert noops.coverage == "complete"
    assert noops.reviewed_noops == 1
    assert noops.files == ()

    session.changes = AgentChangeTracker(max_files=1, max_baseline_bytes=0)
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "alpha.txt", "content": "changed\n"}
    ).ok
    assert service._execute(  # noqa: SLF001
        session, "write_file", {"path": "second.txt", "content": "changed too\n"}
    ).ok
    limited = service.change_set(session_id)
    assert limited.coverage == "partial"
    assert limited.omitted_write_receipts == 1
    assert limited.files[0].reason == "baseline_not_retained"
    assert limited.files[0].diff_available is False
    assert "one" not in limited.model_dump_json()

    with session.lock:
        session.running = True
    try:
        active = service.change_set(session_id)
        assert active.settled is False and active.coverage == "partial"
    finally:
        with session.lock:
            session.running = False


def test_failed_manual_apply_does_not_create_a_verified_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    opened = service.workspace_file(session_id, "alpha.txt")
    preview = service.preview_workspace_edit(
        session_id,
        WorkspacePreviewCommand(
            path=opened.path,
            content="two\n",
            expected_revision=opened.revision,
            line_ending=opened.line_ending,
        ),
    )
    with pytest.raises(Exception) as raised:
        service.apply_workspace_edit(
            session_id,
            preview.preview_id,
            WorkspaceApplyCommand(
                path=preview.path,
                content="different\n",
                expected_revision=preview.expected_revision,
                proposed_revision=preview.proposed_revision,
                line_ending=preview.line_ending,
                confirmation=WORKSPACE_APPLY_CONFIRMATION,
            ),
        )
    assert getattr(raised.value, "code", None) == "workspace_preview_mismatch"
    change_set = service.change_set(session_id)
    assert change_set.reviewed_writes == 0
    assert change_set.files == ()


def test_empty_file_existence_changes_have_an_explicit_net_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001

    assert service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "empty.txt", "content": ""},
    ).ok
    created = service.change_diff(session_id, "empty.txt")
    assert created.summary.net_effect == "created"
    assert created.diff_state == "available"
    assert created.diff is not None
    assert created.diff.splitlines() == [
        "--- /dev/null",
        "+++ b/empty.txt",
        "@@ -0,0 +0,0 @@",
    ]
    assert created.added_lines == 0 and created.removed_lines == 0

    (root / "empty.txt").unlink()
    reverted = service.change_diff(session_id, "empty.txt")
    assert reverted.summary.net_effect == "reverted"
    assert reverted.summary.verification == "partial"
    assert reverted.summary.reason == "current_file_missing"
    assert reverted.diff_state == "no_change"


def test_unverified_manual_publication_is_counted_without_claiming_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    opened = service.workspace_file(session_id, "alpha.txt")
    preview = service.preview_workspace_edit(
        session_id,
        WorkspacePreviewCommand(
            path=opened.path,
            content="two\n",
            expected_revision=opened.revision,
            line_ending=opened.line_ending,
        ),
    )
    monkeypatch.setattr(
        session.tools,
        "apply_prepared_write",
        lambda _prepared: ToolOutcome(
            False,
            "publication outcome unavailable",
            "workspace_verification_failed",
        ),
    )

    with pytest.raises(Exception) as raised:
        service.apply_workspace_edit(
            session_id,
            preview.preview_id,
            WorkspaceApplyCommand(
                path=preview.path,
                content="two\n",
                expected_revision=preview.expected_revision,
                proposed_revision=preview.proposed_revision,
                line_ending=preview.line_ending,
                confirmation=WORKSPACE_APPLY_CONFIRMATION,
            ),
        )
    assert getattr(raised.value, "code", None) == "workspace_verification_failed"
    change_set = service.change_set(session_id)
    assert change_set.coverage == "partial"
    assert change_set.reviewed_writes == 1
    assert change_set.manual_writes == 1
    assert change_set.verified_writes == 0
    assert change_set.unverified_writes == 1
    assert change_set.files[0].verification == "unverified"
    assert change_set.files[0].reason == "publication_unverified"
    assert service.change_diff(session_id, "alpha.txt").diff_state == "no_change"


def test_manual_noop_preview_does_not_enter_the_reviewed_change_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    opened = service.workspace_file(session_id, "alpha.txt")
    with pytest.raises(Exception) as raised:
        service.preview_workspace_edit(
            session_id,
            WorkspacePreviewCommand(
                path=opened.path,
                content=opened.content,
                expected_revision=opened.revision,
                line_ending=opened.line_ending,
            ),
        )
    assert getattr(raised.value, "code", None) == "workspace_no_change"

    change_set = service.change_set(session_id)
    assert change_set.coverage == "complete"
    assert change_set.reviewed_writes == 0
    assert change_set.manual_writes == 0
    assert change_set.reviewed_noops == 0
    assert change_set.files == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows path identity is case-insensitive")
def test_windows_case_aliases_share_one_reviewed_path_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001

    assert service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "ALPHA.txt", "content": "two\n"},
    ).ok
    assert service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "alpha.txt", "content": "three\n"},
    ).ok

    change_set = service.change_set(session_id)
    assert change_set.coverage == "complete"
    assert len(change_set.files) == 1
    assert change_set.files[0].path == "ALPHA.txt"
    assert change_set.files[0].reviewed_writes == 2
    detail = service.change_diff(session_id, "ALPHA.txt")
    assert detail.diff is not None
    assert "-one" in detail.diff and "+three" in detail.diff
    with pytest.raises(Exception) as raised:
        service.change_diff(session_id, "alpha.txt")
    assert getattr(raised.value, "code", None) == "change_path_not_found"


def test_change_models_reject_incoherent_presence_counts_and_diff_authority() -> None:
    with pytest.raises(ValueError):
        AgentChangedFile(
            path="created.txt",
            net_effect="created",
            verification="verified",
            reason=None,
            reviewed_writes=1,
            agent_writes=1,
            manual_writes=0,
            current_byte_size=None,
            diff_available=True,
        )

    changed = AgentChangedFile(
        path="alpha.txt",
        net_effect="modified",
        verification="verified",
        reason=None,
        reviewed_writes=1,
        agent_writes=1,
        manual_writes=0,
        current_byte_size=4,
        diff_available=True,
    )
    with pytest.raises(ValueError):
        AgentChangeSet(
            session_id="a" * 32,
            coverage="complete",
            settled=True,
            reviewed_writes=0,
            verified_writes=0,
            unverified_writes=0,
            agent_writes=0,
            manual_writes=0,
            reviewed_noops=0,
            command_attempts=0,
            omitted_write_receipts=0,
            tracking_failed=False,
            files=(changed,),
        )
    with pytest.raises(ValueError):
        AgentChangeDiff(
            session_id="a" * 32,
            summary=changed,
            diff_state="available",
            diff="--- a/other.txt\n+++ b/other.txt\n@@ -1 +1 @@\n-old\n+new",
            added_lines=1,
            removed_lines=1,
        )


def test_success_without_a_write_receipt_fails_closed_and_marks_tracking_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001
    monkeypatch.setattr(
        session.tools,
        "apply_prepared_write",
        lambda _prepared: ToolOutcome(True, "synthetic receipt omitted"),
    )

    outcome = service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "alpha.txt", "content": "two\n"},
    )
    assert not outcome.ok
    assert outcome.code == "workspace_verification_failed"
    change_set = service.change_set(session_id)
    assert change_set.coverage == "partial"
    assert change_set.tracking_failed is True
    assert change_set.reviewed_writes == 0
    assert change_set.files == ()


def test_mismatched_verified_write_receipt_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service, session_id = _service(root, monkeypatch)
    session = service._session(session_id)  # noqa: SLF001

    def mismatched(prepared):
        return ToolOutcome(
            True,
            "synthetic mismatched receipt",
            write_receipt=AgentWriteReceipt(
                path="other.txt",
                state="verified",
                operation="modified",
                before_sha256=prepared.base_sha256,
                after_sha256=prepared.proposed_sha256,
                added_lines=1,
                removed_lines=1,
                byte_size=4,
            ),
        )

    monkeypatch.setattr(session.tools, "apply_prepared_write", mismatched)
    outcome = service._execute(  # noqa: SLF001
        session,
        "write_file",
        {"path": "alpha.txt", "content": "two\n"},
    )
    assert not outcome.ok
    assert outcome.code == "workspace_verification_failed"
    assert outcome.write_receipt is None
    change_set = service.change_set(session_id)
    assert change_set.coverage == "partial"
    assert change_set.tracking_failed is True
    assert change_set.reviewed_writes == 0
    assert change_set.files == ()
