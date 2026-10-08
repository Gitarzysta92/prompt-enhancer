"""Failure-atomic reviewed edits use only disposable fictional workspaces."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, CSRF_HEADER
from prompt_enhancer.application.local_agent_limits import LocalAgentError
from prompt_enhancer.application.local_agent import (
    AgentSettings,
    ApprovalDecision,
    LocalAgentService,
    SendMessage,
)
from prompt_enhancer.application.local_agent_transactions import (
    MAX_ACTIVE_TRANSACTION_PREVIEWS_PER_SESSION,
    WORKSPACE_TRANSACTION_APPLY_CONFIRMATION,
    LocalAgentWorkspaceTransactionEditor,
    WorkspaceTransactionApplyChange,
    WorkspaceTransactionApplyCommand,
    WorkspaceTransactionChangeCommand,
    WorkspaceTransactionPreviewCommand,
)
from prompt_enhancer.application.local_agent_workspace import ToolOutcome, WorkspaceTools
from prompt_enhancer.application.runtime_cancellation import runtime_request_scope
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


SESSION = "a" * 32


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _workspace(tmp_path: Path) -> tuple[Path, WorkspaceTools]:
    root = tmp_path / "fictional-project"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha old\n")
    (root / "beta.txt").write_bytes(b"beta old\n")
    return root, WorkspaceTools(root)


def _preview_command(
    tools: WorkspaceTools,
    replacements: dict[str, str],
) -> WorkspaceTransactionPreviewCommand:
    changes = []
    for path, content in replacements.items():
        current = tools.read_text_snapshot(path)
        changes.append(
            WorkspaceTransactionChangeCommand(
                path=path,
                content=content,
                expected_revision=current.revision,
                line_ending=current.line_ending,
            )
        )
    return WorkspaceTransactionPreviewCommand(changes=tuple(changes))


def _apply_command(preview, replacements: dict[str, str]) -> WorkspaceTransactionApplyCommand:
    return WorkspaceTransactionApplyCommand(
        changes=tuple(
            WorkspaceTransactionApplyChange(
                operation=item.operation,
                path=item.path,
                content=replacements[item.path],
                expected_revision=item.expected_revision,
                proposed_revision=item.proposed_revision,
                line_ending=item.line_ending,
            )
            for item in preview.files
        ),
        confirmation=WORKSPACE_TRANSACTION_APPLY_CONFIRMATION,
    )


def test_transaction_preview_retains_only_content_free_authority_and_commits_all_files(
    tmp_path: Path,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"beta.txt": "beta reviewed\n", "alpha.txt": "alpha reviewed\n"}

    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))

    assert preview.contract_version == "local-agent-workspace-transaction.v2"
    assert [item.path for item in preview.files] == ["alpha.txt", "beta.txt"]
    assert preview.file_count == 2
    assert preview.added_lines == 2 and preview.removed_lines == 2
    assert "alpha reviewed" in preview.files[0].diff
    assert "alpha reviewed" not in repr(editor._capabilities)  # noqa: SLF001
    result = editor.apply(SESSION, preview.plan_id, tools, _apply_command(preview, replacements))

    assert result.state == "committed" and result.reason is None
    assert [item.state for item in result.files] == ["committed", "committed"]
    assert (root / "alpha.txt").read_text(encoding="utf-8") == "alpha reviewed\n"
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta reviewed\n"
    with pytest.raises(LocalAgentError, match="workspace_transaction_not_found"):
        editor.apply(SESSION, preview.plan_id, tools, _apply_command(preview, replacements))


def test_transaction_preflight_rejects_one_stale_file_before_any_publication(tmp_path: Path) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    (root / "beta.txt").write_bytes(b"beta external\n")

    with pytest.raises(LocalAgentError, match="workspace_transaction_changed"):
        editor.apply(SESSION, preview.plan_id, tools, _apply_command(preview, replacements))

    assert (root / "alpha.txt").read_text(encoding="utf-8") == "alpha old\n"
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta external\n"


def test_transaction_restores_prior_files_when_a_later_publication_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    original_apply = tools.apply_prepared_write
    calls = 0

    def reject_second(prepared):
        nonlocal calls
        calls += 1
        if calls == 2:
            return ToolOutcome(False, "fictional publication refused", "workspace_write_failed")
        return original_apply(prepared)

    monkeypatch.setattr(tools, "apply_prepared_write", reject_second)
    result = editor.apply(SESSION, preview.plan_id, tools, _apply_command(preview, replacements))

    assert result.state == "rolled_back"
    assert result.reason == "workspace_write_failed"
    assert [item.state for item in result.files] == ["restored", "not_applied"]
    assert (root / "alpha.txt").read_text(encoding="utf-8") == "alpha old\n"
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta old\n"


def test_transaction_reports_unverified_when_rollback_cannot_be_proven(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    original_apply = tools.apply_prepared_write
    calls = 0

    def fail_publication_and_rollback(prepared):
        nonlocal calls
        calls += 1
        if calls == 2:
            return ToolOutcome(False, "fictional publication refused", "workspace_write_failed")
        if calls == 3:
            return ToolOutcome(False, "fictional rollback uncertain", "workspace_verification_failed")
        return original_apply(prepared)

    monkeypatch.setattr(tools, "apply_prepared_write", fail_publication_and_rollback)
    result = editor.apply(SESSION, preview.plan_id, tools, _apply_command(preview, replacements))

    assert result.state == "unverified"
    assert result.reason == "workspace_transaction_unverified"
    assert [item.state for item in result.files] == ["unverified", "not_applied"]
    assert result.files[0].revision is None and result.files[0].byte_size is None
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta old\n"


def test_transaction_finishes_rollback_after_cooperative_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    cancelled = threading.Event()
    original_apply = tools.apply_prepared_write
    calls = 0

    def cancel_after_first_publication(prepared):
        nonlocal calls
        calls += 1
        outcome = original_apply(prepared)
        if calls == 1:
            cancelled.set()
        return outcome

    monkeypatch.setattr(tools, "apply_prepared_write", cancel_after_first_publication)
    with runtime_request_scope(cancelled):
        result = editor.apply(
            SESSION,
            preview.plan_id,
            tools,
            _apply_command(preview, replacements),
        )

    assert result.state == "rolled_back"
    assert result.reason == "tool_cancelled"
    assert [item.state for item in result.files] == ["restored", "not_applied"]
    assert (root / "alpha.txt").read_bytes() == b"alpha old\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_transaction_stop_removes_an_exact_same_transaction_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    beta = tools.read_text_snapshot("beta.txt")
    command = WorkspaceTransactionPreviewCommand(
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="aardvark-new.txt",
                content="created before stop\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="beta.txt",
                content="beta reviewed\n",
                expected_revision=beta.revision,
                line_ending=beta.line_ending,
            ),
        )
    )
    replacements = {
        "aardvark-new.txt": "created before stop\n",
        "beta.txt": "beta reviewed\n",
    }
    preview = editor.preview(SESSION, tools, command)
    cancelled = threading.Event()
    original_apply = tools.apply_prepared_write
    calls = 0

    def cancel_after_first_publication(prepared):
        nonlocal calls
        calls += 1
        outcome = original_apply(prepared)
        if calls == 1:
            cancelled.set()
        return outcome

    monkeypatch.setattr(tools, "apply_prepared_write", cancel_after_first_publication)
    with runtime_request_scope(cancelled):
        result = editor.apply(
            SESSION,
            preview.plan_id,
            tools,
            _apply_command(preview, replacements),
        )

    assert result.state == "rolled_back"
    assert result.reason == "tool_cancelled"
    assert [item.state for item in result.files] == ["removed", "not_applied"]
    assert not (root / "aardvark-new.txt").exists()
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_transaction_capability_is_session_bound_expiring_and_single_use_on_mismatch(
    tmp_path: Path,
) -> None:
    root, tools = _workspace(tmp_path)
    now = [10.0]
    editor = LocalAgentWorkspaceTransactionEditor(monotonic=lambda: now[0], ttl_seconds=2)
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    command = _apply_command(preview, replacements)

    with pytest.raises(LocalAgentError, match="workspace_transaction_not_found"):
        editor.apply("b" * 32, preview.plan_id, tools, command)
    tampered = command.model_copy(
        update={
            "changes": (
                command.changes[0].model_copy(update={"content": "unreviewed replacement\n"}),
                command.changes[1],
            )
        }
    )
    with pytest.raises(LocalAgentError, match="workspace_transaction_mismatch"):
        editor.apply(SESSION, preview.plan_id, tools, tampered)
    with pytest.raises(LocalAgentError, match="workspace_transaction_not_found"):
        editor.apply(SESSION, preview.plan_id, tools, command)
    assert (root / "alpha.txt").read_bytes() == b"alpha old\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\n"

    expired = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    now[0] = 12.0
    with pytest.raises(LocalAgentError, match="workspace_transaction_expired"):
        editor.apply(SESSION, expired.plan_id, tools, _apply_command(expired, replacements))
    assert (root / "alpha.txt").read_bytes() == b"alpha old\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_transaction_capabilities_are_bounded_and_discarded_with_the_session(
    tmp_path: Path,
) -> None:
    _root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    previews = [
        editor.preview(SESSION, tools, _preview_command(tools, replacements))
        for _index in range(MAX_ACTIVE_TRANSACTION_PREVIEWS_PER_SESSION + 1)
    ]

    assert len(editor._capabilities) == MAX_ACTIVE_TRANSACTION_PREVIEWS_PER_SESSION  # noqa: SLF001
    with pytest.raises(LocalAgentError, match="workspace_transaction_not_found"):
        editor.apply(
            SESSION,
            previews[0].plan_id,
            tools,
            _apply_command(previews[0], replacements),
        )

    editor.discard_session(SESSION)
    assert not editor._capabilities  # noqa: SLF001
    with pytest.raises(LocalAgentError, match="workspace_transaction_not_found"):
        editor.apply(
            SESSION,
            previews[-1].plan_id,
            tools,
            _apply_command(previews[-1], replacements),
        )


def test_transaction_total_diff_limit_rejects_the_whole_plan(tmp_path: Path) -> None:
    root = tmp_path / "fictional-project"
    root.mkdir()
    replacements: dict[str, str] = {}
    for index in range(6):
        path = f"file-{index}.txt"
        (root / path).write_bytes(b"a" * 20_000 + b"\n")
        replacements[path] = "b" * 20_000 + "\n"
    tools = WorkspaceTools(root)
    editor = LocalAgentWorkspaceTransactionEditor()

    with pytest.raises(LocalAgentError, match="workspace_transaction_diff_too_large"):
        editor.preview(SESSION, tools, _preview_command(tools, replacements))
    assert not editor._capabilities  # noqa: SLF001 - failed preview grants no authority
    assert all((root / path).read_bytes() == (b"a" * 20_000 + b"\n") for path in replacements)


def test_transaction_total_content_limit_rejects_the_whole_plan(tmp_path: Path) -> None:
    root = tmp_path / "fictional-project"
    root.mkdir()
    base_lines = [f"{index:05d}-{'a' * 43}\n" for index in range(5_000)]
    base = "".join(base_lines)
    replacements: dict[str, str] = {}
    for index in range(5):
        path = f"large-{index}.txt"
        (root / path).write_bytes(base.encode("utf-8"))
        changed = list(base_lines)
        changed[2_500 + index] = f"{2_500 + index:05d}-{'b' * 43}\n"
        replacements[path] = "".join(changed)
    tools = WorkspaceTools(root)
    editor = LocalAgentWorkspaceTransactionEditor()

    with pytest.raises(LocalAgentError, match="workspace_transaction_too_large"):
        editor.preview(SESSION, tools, _preview_command(tools, replacements))
    assert not editor._capabilities  # noqa: SLF001 - failed preview grants no authority
    assert all((root / path).read_bytes() == base.encode("utf-8") for path in replacements)


def test_transaction_rollback_restores_exact_crlf_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "fictional-project"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha old\r\n")
    (root / "beta.txt").write_bytes(b"beta old\r\n")
    tools = WorkspaceTools(root)
    editor = LocalAgentWorkspaceTransactionEditor()
    replacements = {"alpha.txt": "alpha reviewed\n", "beta.txt": "beta reviewed\n"}
    preview = editor.preview(SESSION, tools, _preview_command(tools, replacements))
    original_apply = tools.apply_prepared_write
    calls = 0

    def reject_second(prepared):
        nonlocal calls
        calls += 1
        if calls == 2:
            return ToolOutcome(False, "fictional publication refused", "workspace_write_failed")
        return original_apply(prepared)

    monkeypatch.setattr(tools, "apply_prepared_write", reject_second)
    result = editor.apply(SESSION, preview.plan_id, tools, _apply_command(preview, replacements))

    assert result.state == "rolled_back"
    assert (root / "alpha.txt").read_bytes() == b"alpha old\r\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\r\n"


def test_transaction_validates_create_edit_identity_duplicates_and_cardinality(
    tmp_path: Path,
) -> None:
    _root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    alpha = tools.read_text_snapshot("alpha.txt")

    with pytest.raises(ValueError):
        WorkspaceTransactionPreviewCommand(
            changes=(
                WorkspaceTransactionChangeCommand(
                    path="alpha.txt", content="one\n", expected_revision=alpha.revision, line_ending=alpha.line_ending,
                ),
            )
        )
    with pytest.raises(ValueError):
        WorkspaceTransactionPreviewCommand(
            changes=tuple(
                WorkspaceTransactionChangeCommand(
                    path="alpha.txt", content=content, expected_revision=alpha.revision, line_ending=alpha.line_ending,
                )
                for content in ("one\n", "two\n")
            )
        )
    with pytest.raises(ValueError, match="edits require an exact source revision"):
        WorkspaceTransactionChangeCommand(
            operation="edit",
            path="new.txt",
            content="new\n",
            line_ending="lf",
        )
    with pytest.raises(ValueError, match="creates require an absent source"):
        WorkspaceTransactionChangeCommand(
            operation="create",
            path="new.txt",
            content="new\n",
            expected_revision="0" * 64,
            line_ending="lf",
        )
    command = WorkspaceTransactionPreviewCommand(
        changes=(
            WorkspaceTransactionChangeCommand(
                path="alpha.txt",
                content="alpha reviewed\n",
                expected_revision=alpha.revision,
                line_ending=alpha.line_ending,
            ),
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="beta.txt",
                content="collision\n",
                line_ending="lf",
            ),
        )
    )
    with pytest.raises(LocalAgentError, match="workspace_transaction_changed"):
        editor.preview(SESSION, tools, command)


def test_transaction_commits_one_create_and_one_edit(tmp_path: Path) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    alpha = tools.read_text_snapshot("alpha.txt")
    command = WorkspaceTransactionPreviewCommand(
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="new.txt",
                content="new reviewed\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="alpha.txt",
                content="alpha reviewed\n",
                expected_revision=alpha.revision,
                line_ending=alpha.line_ending,
            ),
        )
    )
    replacements = {
        "alpha.txt": "alpha reviewed\n",
        "new.txt": "new reviewed\n",
    }

    preview = editor.preview(SESSION, tools, command)

    assert [(item.path, item.operation, item.expected_revision) for item in preview.files] == [
        ("alpha.txt", "edit", alpha.revision),
        ("new.txt", "create", None),
    ]
    result = editor.apply(
        SESSION,
        preview.plan_id,
        tools,
        _apply_command(preview, replacements),
    )
    assert result.state == "committed"
    assert [item.state for item in result.files] == ["committed", "committed"]
    assert (root / "alpha.txt").read_bytes() == b"alpha reviewed\n"
    assert (root / "new.txt").read_bytes() == b"new reviewed\n"


def test_transaction_create_collision_after_preview_preserves_external_file(
    tmp_path: Path,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    alpha = tools.read_text_snapshot("alpha.txt")
    command = WorkspaceTransactionPreviewCommand(
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="new.txt",
                content="reviewed create\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="alpha.txt",
                content="alpha reviewed\n",
                expected_revision=alpha.revision,
                line_ending=alpha.line_ending,
            ),
        )
    )
    replacements = {"alpha.txt": "alpha reviewed\n", "new.txt": "reviewed create\n"}
    preview = editor.preview(SESSION, tools, command)
    (root / "new.txt").write_bytes(b"external owner file\n")

    with pytest.raises(LocalAgentError, match="workspace_transaction_changed"):
        editor.apply(
            SESSION,
            preview.plan_id,
            tools,
            _apply_command(preview, replacements),
        )

    assert (root / "alpha.txt").read_bytes() == b"alpha old\n"
    assert (root / "new.txt").read_bytes() == b"external owner file\n"


def test_transaction_rollback_removes_only_its_created_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    beta = tools.read_text_snapshot("beta.txt")
    command = WorkspaceTransactionPreviewCommand(
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="aardvark-new.txt",
                content="created then rolled back\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="beta.txt",
                content="beta reviewed\n",
                expected_revision=beta.revision,
                line_ending=beta.line_ending,
            ),
        )
    )
    replacements = {
        "aardvark-new.txt": "created then rolled back\n",
        "beta.txt": "beta reviewed\n",
    }
    preview = editor.preview(SESSION, tools, command)
    original_apply = tools.apply_prepared_write
    calls = 0

    def reject_second(prepared):
        nonlocal calls
        calls += 1
        if calls == 2:
            return ToolOutcome(False, "fictional publication refused", "workspace_write_failed")
        return original_apply(prepared)

    monkeypatch.setattr(tools, "apply_prepared_write", reject_second)
    result = editor.apply(
        SESSION,
        preview.plan_id,
        tools,
        _apply_command(preview, replacements),
    )

    assert result.state == "rolled_back"
    assert [item.state for item in result.files] == ["removed", "not_applied"]
    assert not (root / "aardvark-new.txt").exists()
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_transaction_preserves_identity_replaced_create_and_reports_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    editor = LocalAgentWorkspaceTransactionEditor()
    beta = tools.read_text_snapshot("beta.txt")
    command = WorkspaceTransactionPreviewCommand(
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="aardvark-new.txt",
                content="same bytes\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="beta.txt",
                content="beta reviewed\n",
                expected_revision=beta.revision,
                line_ending=beta.line_ending,
            ),
        )
    )
    replacements = {
        "aardvark-new.txt": "same bytes\n",
        "beta.txt": "beta reviewed\n",
    }
    preview = editor.preview(SESSION, tools, command)
    original_apply = tools.apply_prepared_write
    calls = 0

    def replace_created_then_reject(prepared):
        nonlocal calls
        calls += 1
        if calls == 1:
            outcome = original_apply(prepared)
            replacement = root / "replacement.tmp"
            replacement.write_bytes(b"same bytes\n")
            replacement.replace(root / "aardvark-new.txt")
            return outcome
        return ToolOutcome(False, "fictional publication refused", "workspace_write_failed")

    monkeypatch.setattr(tools, "apply_prepared_write", replace_created_then_reject)
    result = editor.apply(
        SESSION,
        preview.plan_id,
        tools,
        _apply_command(preview, replacements),
    )

    assert result.state == "unverified"
    assert [item.state for item in result.files] == ["unverified", "not_applied"]
    assert (root / "aardvark-new.txt").read_bytes() == b"same bytes\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_consecutive_model_writes_use_one_review_and_keep_individual_receipts(
    tmp_path: Path,
) -> None:
    root, _tools = _workspace(tmp_path)
    requests: list[dict] = []
    replies = [
        {
            "tool_calls": [
                {
                    "id": "alpha-write",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({"path": "alpha.txt", "content": "alpha reviewed\n"}),
                    },
                },
                {
                    "id": "beta-write",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({"path": "beta.txt", "content": "beta reviewed\n"}),
                    },
                },
            ]
        },
        {"content": "Both fictional files were updated together."},
    ]

    def chat(_alias: str, body: bytes):
        requests.append(json.loads(body))
        reply = replies.pop(0)
        message = {
            "role": "assistant",
            "content": reply.get("content"),
            "tool_calls": reply.get("tool_calls"),
        }
        return (
            200,
            json.dumps(
                {
                    "choices": [
                        {
                            "message": message,
                            "finish_reason": "tool_calls" if reply.get("tool_calls") else "stop",
                        }
                    ]
                }
            ).encode(),
            "application/json",
        )

    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "example-model",
        approval_wait_seconds=5,
    )
    session = service.create(AgentSettings(workspace=str(root), model_alias="example-model"))
    service.send(session.session_id, SendMessage(text="Update both fictional files together."))
    assert _wait(lambda: service.events(session.session_id).pending_approval_id is not None)

    pending_page = service.events(session.session_id)
    approvals = [event for event in pending_page.events if event.kind == "approval_required"]
    assert len(approvals) == 1
    pending = approvals[0]
    assert pending.arguments == {
        "file_count": 2,
        "create_count": 0,
        "edit_count": 2,
        "paths": ["alpha.txt", "beta.txt"],
        "transaction": "failure_atomic_create_edit",
    }
    assert "Transaction file 1/2 [edit]: alpha.txt" in (pending.preview or "")
    assert "Transaction file 2/2 [edit]: beta.txt" in (pending.preview or "")
    assert (root / "alpha.txt").read_text(encoding="utf-8") == "alpha old\n"
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta old\n"

    service.approve(
        session.session_id,
        pending.approval_id or "",
        ApprovalDecision(approved=True),
    )
    assert _wait(lambda: not service.get(session.session_id).running)

    page = service.events(session.session_id)
    results = [event for event in page.events if event.kind == "tool_result"]
    assert [event.call_id for event in results] == ["alpha-write", "beta-write"]
    assert all(event.ok and event.write_receipt is not None for event in results)
    assert [event.write_receipt.path for event in results if event.write_receipt] == [
        "alpha.txt",
        "beta.txt",
    ]
    assert page.events[-1].turn_summary is not None
    assert len(page.events[-1].turn_summary.writes) == 2
    assert len([message for message in requests[1]["messages"] if message["role"] == "tool"]) == 2
    change_set = service.change_set(session.session_id)
    assert change_set.reviewed_writes == 2 and change_set.agent_writes == 2
    assert (root / "alpha.txt").read_text(encoding="utf-8") == "alpha reviewed\n"
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta reviewed\n"


def test_consecutive_model_writes_atomically_create_and_edit_with_one_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _tools = _workspace(tmp_path)
    service = LocalAgentService(
        chat=lambda *_args: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(
        AgentSettings(workspace=str(root), model_alias="example-model", allow_writes=True)
    )
    session = service._session(view.session_id)  # noqa: SLF001 - exact batch contract under test
    reviewed: dict[str, object] = {}

    def approve(_session, _tool, arguments, preview) -> bool:
        reviewed["arguments"] = arguments
        reviewed["preview"] = preview
        return True

    monkeypatch.setattr(service, "_await_approval", approve)
    outcomes = service._execute_write_batch(  # noqa: SLF001 - bounded orchestration branch
        session,
        (
            {"path": "alpha.txt", "content": "alpha reviewed\n"},
            {"path": "new.txt", "content": "new reviewed\n"},
        ),
    )

    assert reviewed["arguments"] == {
        "file_count": 2,
        "create_count": 1,
        "edit_count": 1,
        "paths": ["alpha.txt", "new.txt"],
        "transaction": "failure_atomic_create_edit",
    }
    assert "Transaction file 1/2 [edit]: alpha.txt" in str(reviewed["preview"])
    assert "Transaction file 2/2 [create]: new.txt" in str(reviewed["preview"])
    assert all(item.ok and item.write_receipt is not None for item in outcomes)
    assert [item.write_receipt.operation for item in outcomes if item.write_receipt] == [
        "modified",
        "created",
    ]
    assert (root / "alpha.txt").read_bytes() == b"alpha reviewed\n"
    assert (root / "new.txt").read_bytes() == b"new reviewed\n"


def test_manual_transaction_service_tracks_each_committed_path(tmp_path: Path) -> None:
    root, tools = _workspace(tmp_path)
    service = LocalAgentService(
        chat=lambda *_args: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(root), model_alias="example-model"))
    replacements = {"alpha.txt": "alpha manual\n", "beta.txt": "beta manual\n"}
    preview = service.preview_workspace_transaction(
        session.session_id,
        _preview_command(tools, replacements),
    )

    result = service.apply_workspace_transaction(
        session.session_id,
        preview.plan_id,
        _apply_command(preview, replacements),
    )

    assert result.state == "committed"
    change_set = service.change_set(session.session_id)
    assert change_set.reviewed_writes == 2
    assert change_set.manual_writes == 2 and change_set.agent_writes == 0
    assert [item.path for item in change_set.files] == ["alpha.txt", "beta.txt"]
    assert all(item.verification == "verified" for item in change_set.files)


def test_manual_transaction_mismatch_discards_every_transient_plan_baseline(
    tmp_path: Path,
) -> None:
    root, tools = _workspace(tmp_path)
    service = LocalAgentService(
        chat=lambda *_args: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(root), model_alias="example-model"))
    replacements = {"alpha.txt": "alpha manual\n", "beta.txt": "beta manual\n"}
    preview = service.preview_workspace_transaction(
        session.session_id,
        _preview_command(tools, replacements),
    )
    command = _apply_command(preview, replacements)
    tampered = command.model_copy(
        update={
            "changes": (
                command.changes[0].model_copy(update={"content": "unreviewed\n"}),
                command.changes[1],
            )
        }
    )
    tracked_session = service._session(session.session_id)  # noqa: SLF001 - bounded transient cleanup invariant
    assert len(tracked_session.changes._manual_stages) == 2  # noqa: SLF001

    with pytest.raises(LocalAgentError, match="workspace_transaction_mismatch"):
        service.apply_workspace_transaction(session.session_id, preview.plan_id, tampered)

    assert not tracked_session.changes._manual_stages  # noqa: SLF001
    assert (root / "alpha.txt").read_bytes() == b"alpha old\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_model_batch_denial_discards_authority_and_changes_no_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _tools = _workspace(tmp_path)
    service = LocalAgentService(
        chat=lambda *_args: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(
        AgentSettings(workspace=str(root), model_alias="example-model", allow_writes=True)
    )
    session = service._session(view.session_id)  # noqa: SLF001 - exact batch authority under test
    monkeypatch.setattr(service, "_await_approval", lambda *_args: False)

    outcomes = service._execute_write_batch(  # noqa: SLF001 - bounded orchestration branch
        session,
        (
            {"path": "alpha.txt", "content": "alpha reviewed\n"},
            {"path": "beta.txt", "content": "beta reviewed\n"},
        ),
    )

    assert len(outcomes) == 2
    assert all(not item.ok and item.code == "approval_not_granted" for item in outcomes)
    assert not service._transactions._capabilities  # noqa: SLF001 - denial consumes metadata authority
    assert (root / "alpha.txt").read_bytes() == b"alpha old\n"
    assert (root / "beta.txt").read_bytes() == b"beta old\n"


def test_model_batch_rebuilds_an_identical_review_after_capability_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _tools = _workspace(tmp_path)
    monotonic_now = [0.0]
    service = LocalAgentService(
        chat=lambda *_args: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    service._transactions = LocalAgentWorkspaceTransactionEditor(  # noqa: SLF001
        monotonic=lambda: monotonic_now[0],
        ttl_seconds=1,
    )
    view = service.create(
        AgentSettings(workspace=str(root), model_alias="example-model", allow_writes=True)
    )
    session = service._session(view.session_id)  # noqa: SLF001 - bounded orchestration branch

    def approve_after_original_capability_expires(*_args) -> bool:
        monotonic_now[0] = 2.0
        return True

    monkeypatch.setattr(service, "_await_approval", approve_after_original_capability_expires)
    outcomes = service._execute_write_batch(  # noqa: SLF001
        session,
        (
            {"path": "alpha.txt", "content": "alpha reviewed\n"},
            {"path": "beta.txt", "content": "beta reviewed\n"},
        ),
    )

    assert all(item.ok and item.write_receipt is not None for item in outcomes)
    assert (root / "alpha.txt").read_bytes() == b"alpha reviewed\n"
    assert (root / "beta.txt").read_bytes() == b"beta reviewed\n"


def test_transaction_http_apply_requires_native_confirmation_and_is_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, tools = _workspace(tmp_path)
    settings = AppSettings(home=tmp_path / "application")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    service = LocalAgentService(
        chat=lambda *_args: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    monkeypatch.setattr(
        type(application),
        "create_local_agent_service",
        lambda self, local_model_service=None, *, mcp_managed_runtime_service=None: service,
    )
    client = TestClient(
        application.create_http_app(
            user_presence_confirmation=lambda _request, _body: None,
        ),
        base_url="http://127.0.0.1",
    )
    token = settings.api_token_path.read_text(encoding="utf-8").strip()
    token_headers = {API_TOKEN_HEADER: token}
    created = client.post(
        "/v1/agent/sessions",
        headers=token_headers,
        json={"workspace": str(root), "model_alias": "example-model"},
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    replacements = {"alpha.txt": "alpha http\n", "beta.txt": "beta http\n"}
    command = _preview_command(tools, replacements)
    preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/transactions",
        headers=token_headers,
        json=command.model_dump(mode="json"),
    )
    assert preview_response.status_code == 201, preview_response.text
    assert preview_response.headers["cache-control"] == "no-store, private"
    assert preview_response.headers["pragma"] == "no-cache"
    preview_body = preview_response.json()
    apply_payload = {
        "changes": [
            {
                "path": item["path"],
                "content": replacements[item["path"]],
                "expected_revision": item["expected_revision"],
                "proposed_revision": item["proposed_revision"],
                "line_ending": item["line_ending"],
            }
            for item in preview_body["files"]
        ],
        "confirmation": WORKSPACE_TRANSACTION_APPLY_CONFIRMATION,
    }
    token_apply = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/transactions/{preview_body['plan_id']}/apply",
        headers=token_headers,
        json=apply_payload,
    )
    assert token_apply.status_code == 403
    assert token_apply.json() == {"detail": "owned native confirmation required"}

    browser = client.get("/auth/session").json()
    result = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/transactions/{preview_body['plan_id']}/apply",
        headers={
            CSRF_HEADER: browser["csrf_token"],
            "Origin": "http://127.0.0.1",
        },
        json=apply_payload,
    )
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store, private"
    assert result.headers["pragma"] == "no-cache"
    assert result.json()["state"] == "committed"
    assert (root / "alpha.txt").read_text(encoding="utf-8") == "alpha http\n"
    assert (root / "beta.txt").read_text(encoding="utf-8") == "beta http\n"
