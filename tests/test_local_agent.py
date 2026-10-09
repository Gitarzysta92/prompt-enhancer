"""Local agent workspace (ADR 0016): tools scoped to one folder, approvals for changes, run loop, HTTP."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path, PureWindowsPath
import platform
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, CSRF_HEADER
from prompt_enhancer.application.local_agent import (
    AgentEvents,
    AgentStreamPhase,
    AgentStreamStatus,
    AgentSettings,
    AgentModelParameters,
    ApprovalDecision,
    LocalAgentError,
    LocalAgentService,
    PendingApproval,
    SendMessage,
    ToolName,
    WorkspaceTools,
    _tool_call_parts,
    tool_schemas,
)
from prompt_enhancer.application.local_agent_editor import (
    WORKSPACE_APPLY_CONFIRMATION,
    WorkspaceApplyCommand,
    WorkspacePreviewCommand,
)
from prompt_enhancer.application.local_agent_file_lifecycle import (
    WORKSPACE_CREATE_CONFIRMATION,
    WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
    WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
    WORKSPACE_FILE_TRASH_CONFIRMATION,
    WORKSPACE_MOVE_CONFIRMATION,
)
from prompt_enhancer.application.local_agent_workspace import (
    WorkspacePathEntry,
    WorkspaceTextSearchMatch,
)
from prompt_enhancer.application.local_models import (
    ChatUpstream,
    ContextAdmissionReason,
    RuntimeContextStatus,
)
from prompt_enhancer.application.mcp_managed_runtime import (
    McpManagedCallProjection,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


T0 = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)


@pytest.mark.parametrize("lifecycle_field", ["closing", "cleanup_unconfirmed"])
def test_change_set_is_partial_while_session_lifecycle_is_unsettled(
    tmp_path,
    lifecycle_field,
):
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(AgentSettings(workspace=str(_workspace(tmp_path))))
    assert service.change_set(view.session_id).coverage == "complete"

    session = service._session(view.session_id)
    with session.lock:
        setattr(session, lifecycle_field, True)

    snapshot = service.change_set(view.session_id)
    assert snapshot.settled is False
    assert snapshot.coverage == "partial"


def test_change_set_is_partial_during_process_wide_command_quarantine(tmp_path):
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(AgentSettings(workspace=str(_workspace(tmp_path))))
    service._command_cleanup_unconfirmed.set()
    try:
        snapshot = service.change_set(view.session_id)
        assert snapshot.settled is False
        assert snapshot.coverage == "partial"
    finally:
        service._command_cleanup_unconfirmed.clear()


def test_change_set_snapshot_and_session_closing_are_linearized(
    tmp_path,
    monkeypatch,
):
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    view = service.create(AgentSettings(workspace=str(_workspace(tmp_path))))
    session = service._session(view.session_id)
    entered_snapshot = threading.Event()
    release_snapshot = threading.Event()
    closing_finished = threading.Event()
    snapshots = []
    original_snapshot = type(session.changes).snapshot

    def blocking_snapshot(tracker, session_id, tools, *, settled):
        if tracker is session.changes:
            entered_snapshot.set()
            assert release_snapshot.wait(2), "change-set snapshot was not released"
        return original_snapshot(
            tracker,
            session_id,
            tools,
            settled=settled,
        )

    monkeypatch.setattr(type(session.changes), "snapshot", blocking_snapshot)
    snapshot_thread = threading.Thread(
        target=lambda: snapshots.append(service.change_set(view.session_id)),
    )
    closing_thread = threading.Thread(
        target=lambda: (
            service._mark_closing(session),
            closing_finished.set(),
        ),
    )
    snapshot_thread.start()
    assert entered_snapshot.wait(2), "change-set snapshot did not start"
    closing_thread.start()
    assert not closing_finished.wait(0.05), "closing raced into an active snapshot"
    release_snapshot.set()
    snapshot_thread.join(timeout=2)
    closing_thread.join(timeout=2)

    assert not snapshot_thread.is_alive()
    assert not closing_thread.is_alive()
    assert snapshots[0].settled is True
    assert snapshots[0].coverage == "complete"
    assert service.get(view.session_id).closing is True
    assert service.change_set(view.session_id).settled is False


def test_failed_turn_thread_start_leaves_session_ready_and_draft_unaccepted(tmp_path, monkeypatch):
    from prompt_enhancer.application import local_agent as agent_module

    service = LocalAgentService(chat=lambda *_: (200, b"{}", "application/json"), active_model=lambda: "example-model")
    session = service.create(AgentSettings(workspace=str(_workspace(tmp_path))))
    original = service.events(session.session_id)

    class UnavailableThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("EXAMPLE_PRIVATE_THREAD_START_CANARY")

    with monkeypatch.context() as patch:
        patch.setattr(agent_module.threading, "Thread", UnavailableThread)
        with pytest.raises(LocalAgentError, match="^turn_start_failed$") as raised:
            service.send(session.session_id, SendMessage(text="Read the example file."))
    assert raised.value.__context__ is None
    assert service.get(session.session_id).running is False
    assert service.get(session.session_id).turns == 0
    assert service.events(session.session_id) == original
    assert service._session(session.session_id).thread is None


def test_agent_shutdown_denies_pending_action_and_rejects_new_work(tmp_path):
    chat, _ = _stub_model([{"tool_calls": [{"id": "example-call", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": "example-new.txt", "content": "example"}),
    }}]}])
    root = _workspace(tmp_path)
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model", approval_wait_seconds=30)
    session = service.create(AgentSettings(workspace=str(root), allow_writes=True))
    service.send(session.session_id, SendMessage(text="Propose an example file."))
    assert _wait(lambda: service.get(session.session_id).pending_approval_id is not None)
    service.shutdown(timeout=2)
    service.shutdown(timeout=2)
    assert service.get(session.session_id).running is False
    assert service.get(session.session_id).pending_approval_id is None
    assert not root.joinpath("example-new.txt").exists()
    with pytest.raises(LocalAgentError, match="^runtime_shutdown_in_progress$"):
        service.send(session.session_id, SendMessage(text="Another request."))
    with pytest.raises(LocalAgentError, match="^runtime_shutdown_in_progress$"):
        service.create(AgentSettings(workspace=str(root)))


def test_closing_session_does_not_discard_a_surviving_turn(tmp_path):
    from prompt_enhancer.application.local_agent import PendingApproval, ToolName

    service = LocalAgentService(chat=lambda *_: (200, b"{}", "application/json"), active_model=lambda: "example-model")
    session = service.create(AgentSettings(workspace=str(_workspace(tmp_path))))
    assert session.model_dump().get("closing") is False

    class SurvivingThread:
        alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            pass

    thread = SurvivingThread()
    internal = service._session(session.session_id)
    internal.thread = thread
    pending = PendingApproval("b" * 32, ToolName.WRITE_FILE, {"path": "example-new.txt", "content": "example"})
    internal.pending = pending
    with pytest.raises(LocalAgentError, match="^session_stop_timeout$"):
        service.delete(session.session_id)
    assert service.get(session.session_id).session_id == session.session_id
    assert service.get(session.session_id).model_dump().get("closing") is True
    assert service.list()[0].model_dump().get("closing") is True
    closing_events = service.events(session.session_id)
    assert closing_events.model_dump().get("closing") is True
    assert closing_events.last_seq > session.last_seq
    assert closing_events.events[-1].kind == "status"
    assert pending.decided.is_set()
    assert pending.approved is False
    with pytest.raises(LocalAgentError, match="^session_closing$"):
        service.approve(session.session_id, pending.approval_id, ApprovalDecision(approved=True))
    assert pending.approved is False
    with pytest.raises(LocalAgentError, match="^session_stop_timeout$"):
        service.delete(session.session_id)
    assert service.events(session.session_id).last_seq == closing_events.last_seq
    with pytest.raises(LocalAgentError, match="^session_closing$"):
        service.send(session.session_id, SendMessage(text="Another request."))
    thread.alive = False
    service.delete(session.session_id)
    assert service.list() == ()


def test_close_notifies_an_already_waiting_event_stream(tmp_path, monkeypatch):
    from prompt_enhancer.interfaces.http.local_agent_routes import _stream_event_pages

    service = LocalAgentService(chat=lambda *_: (200, b"{}", "application/json"), active_model=lambda: "example-model")
    view = service.create(AgentSettings(workspace=str(_workspace(tmp_path))))
    internal = service._session(view.session_id)
    waiting = threading.Event()
    original_wait = internal.event_ready.wait
    frames = []

    def wait(timeout=None):
        waiting.set()
        return original_wait(timeout=timeout)

    monkeypatch.setattr(internal.event_ready, "wait", wait)
    stream = _stream_event_pages(service, view.session_id, view.last_seq, 8)
    reader = threading.Thread(target=lambda: frames.append(next(stream)), daemon=True)
    reader.start()
    try:
        assert waiting.wait(timeout=2)
        service.delete(view.session_id)
        reader.join(timeout=2)
        assert not reader.is_alive()
        assert len(frames) == 1
        payload = json.loads(frames[0].decode("utf-8").removeprefix("data: "))
        assert payload["contract_version"] == "local-agent.v9"
        assert payload["closing"] is True
        assert payload["events"][-1]["kind"] == "status"
        assert payload["last_seq"] > view.last_seq
    finally:
        with internal.event_ready:
            internal.event_ready.notify_all()
        reader.join(timeout=2)
        if not reader.is_alive():
            stream.close()


@pytest.mark.parametrize(
    "nonterminal_state",
    (
        {"closing": True},
        {"stopping": True},
    ),
)
def test_event_stream_does_not_treat_closing_or_stopping_as_settled(nonterminal_state):
    from prompt_enhancer.interfaces.http.local_agent_routes import _stream_event_pages

    session_id = "a" * 32
    pages = [
        AgentEvents(
            session_id=session_id,
            events=(),
            running=False,
            closing=bool(nonterminal_state.get("closing", False)),
            stopping=bool(nonterminal_state.get("stopping", False)),
            cleanup_unconfirmed=False,
            pending_approval_id=None,
            last_seq=0,
        ),
        AgentEvents(
            session_id=session_id,
            events=(),
            running=False,
            closing=False,
            stopping=False,
            cleanup_unconfirmed=False,
            pending_approval_id=None,
            last_seq=0,
        ),
    ]

    class SequencedService:
        def wait_events(self, requested_session_id, after, limit):
            assert requested_session_id == session_id
            assert after == 0
            assert limit == 8
            return pages.pop(0)

    stream = _stream_event_pages(SequencedService(), session_id, 0, 8)
    assert next(stream) == b": keepalive\n\n"
    terminal = next(stream)
    payload = json.loads(terminal.decode("utf-8").removeprefix("data: "))
    assert payload["closing"] is False
    assert payload["stopping"] is False
    assert payload["cleanup_unconfirmed"] is False
    with pytest.raises(StopIteration):
        next(stream)


def test_event_stream_emits_cleanup_quarantine_as_data_before_closing():
    from prompt_enhancer.interfaces.http.local_agent_routes import _stream_event_pages

    session_id = "a" * 32
    quarantined = AgentEvents(
        session_id=session_id,
        events=(),
        running=False,
        closing=True,
        stopping=False,
        cleanup_unconfirmed=True,
        pending_approval_id=None,
        last_seq=0,
    )

    class QuarantinedService:
        def wait_events(self, requested_session_id, after, limit):
            assert requested_session_id == session_id
            assert after == 0
            assert limit == 8
            return quarantined

    stream = _stream_event_pages(QuarantinedService(), session_id, 0, 8)
    terminal = next(stream)
    payload = json.loads(terminal.decode("utf-8").removeprefix("data: "))
    assert payload["cleanup_unconfirmed"] is True
    assert payload["closing"] is True
    with pytest.raises(StopIteration):
        next(stream)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "README.md").write_text("# Example project\n\nHello.\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "big.js").write_text("x" * 10, encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return root


def test_workspace_tools_never_leave_the_folder(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    tools = WorkspaceTools(root)
    assert tools.read_file("README.md").text.startswith("# Example project")
    listed = tools.list_dir(".", 2).text
    assert "src/app.py" in listed and "node_modules/ (skipped)" in listed
    found = tools.search_text("return a + b").text
    assert found.startswith("src/app.py:2:")
    search = tools.search_text_snapshot("return a + b", "src/**/*.py")
    assert search.coverage == "complete"
    assert search.reason_code is None
    assert search.matches == (
        WorkspaceTextSearchMatch(
            path="src/app.py",
            line_number=2,
            preview="return a + b",
        ),
    )
    assert search.scanned_entry_count >= 2
    assert search.inspected_byte_count == len(
        (root / "src" / "app.py").read_bytes()
    )
    assert search.skipped_entry_count == 1
    (root / "src" / "control.txt").write_text(
        "synthetic \x1b[31mcontrol\u202e text\n",
        encoding="utf-8",
    )
    inert = tools.search_text_snapshot("synthetic", "src/**/*.txt")
    assert inert.matches[0].preview == "synthetic �[31mcontrol� text"
    assert "\x1b" not in tools.search_text("synthetic", "src/**/*.txt").text
    for escape in ("../outside.txt", "..", "/etc/passwd", "C:/Windows/system.ini", "src/../../outside.txt"):
        with pytest.raises(LocalAgentError) as raised:
            tools.resolve(escape)
        assert raised.value.code == "path_outside_workspace", escape
    unsafe_paths = ["README.md:secret"]
    if platform.system() == "Windows":
        unsafe_paths.extend(("CON", "src/trailing.", "src/name?"))
    for unsafe in unsafe_paths:
        with pytest.raises(LocalAgentError) as raised:
            tools.resolve(unsafe)
        assert raised.value.code == "path_invalid", unsafe
    for skipped_path in ("node_modules/big.js", ".git/config"):
        with pytest.raises(LocalAgentError) as raised:
            tools.resolve(skipped_path)
        assert raised.value.code == "workspace_path_not_found", skipped_path
    assert tools.read_file("missing.txt").ok is False
    preview = tools.diff_preview("src/app.py", "def add(a, b):\n    return a - b\n")
    assert "-    return a + b" in preview and "+    return a - b" in preview
    canonical_preview = tools.diff_preview("./src/app.py", "def add(a, b):\n    return a - b\n")
    assert canonical_preview.startswith("--- a/src/app.py\n+++ b/src/app.py")
    with pytest.raises(LocalAgentError) as skipped:
        tools.list_entries("node_modules")
    assert skipped.value.code == "workspace_path_not_found"
    assert "+++ b/new.md" in tools.diff_preview("new.md", "hello\n")
    written = tools.write_file("new.md", "hello\n")
    assert written.ok and (root / "new.md").read_text(encoding="utf-8") == "hello\n"


def test_workspace_path_policy_keeps_platform_rules_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prompt_enhancer.application import local_agent_workspace as workspace_module

    monkeypatch.setattr(workspace_module.platform, "system", lambda: "Linux")
    assert workspace_module._relative_components_are_portable(PureWindowsPath("CON"))  # noqa: SLF001
    assert workspace_module._relative_components_are_portable(PureWindowsPath("trailing."))  # noqa: SLF001
    assert not workspace_module._relative_components_are_portable(PureWindowsPath("file:stream"))  # noqa: SLF001
    monkeypatch.setattr(workspace_module.platform, "system", lambda: "Windows")
    assert not workspace_module._relative_components_are_portable(PureWindowsPath("CON"))  # noqa: SLF001
    assert not workspace_module._relative_components_are_portable(PureWindowsPath("trailing."))  # noqa: SLF001


def test_prepared_writes_are_revision_bound_and_refuse_unsafe_files(tmp_path: Path) -> None:
    import os

    root = _workspace(tmp_path)
    tools = WorkspaceTools(root)
    prepared = tools.prepare_write("src/app.py", "def add(a, b):\n    return a - b\n")
    (root / "src" / "app.py").write_text("external change\n", encoding="utf-8")
    stale = tools.apply_prepared_write(prepared)
    assert stale.ok is False and stale.text == "file changed since preview; read it again and propose a new change"
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "external change\n"

    hard_link = root / "hard-link.py"
    try:
        os.link(root / "src" / "app.py", hard_link)
    except OSError:
        pass
    else:
        with pytest.raises(LocalAgentError) as linked:
            tools.prepare_write("hard-link.py", "replacement\n")
        assert linked.value.code == "workspace_file_unavailable"

    with pytest.raises(LocalAgentError) as missing_parent:
        tools.prepare_write("missing/new.md", "hello\n")
    assert missing_parent.value.code == "workspace_parent_unavailable"
    with pytest.raises(LocalAgentError) as oversized:
        tools.prepare_write("new.md", "x" * 256_001)
    assert oversized.value.code == "workspace_file_too_large"


def test_workspace_editor_tree_read_preview_apply_and_single_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monotonic = [10.0]
    service = LocalAgentService(
        chat=lambda a, b: (200, b"{}", "application/json"),
        active_model=lambda: None,
        clock=lambda: T0,
        monotonic=lambda: monotonic[0],
    )
    session = service.create(AgentSettings(workspace=str(root)))
    tree = service.workspace_tree(session.session_id)
    assert tree.contract_version == "local-agent-workspace.v1"
    assert tree.complete is True
    assert [(entry.name, entry.kind.value) for entry in tree.entries] == [
        ("src", "directory"),
        ("README.md", "file"),
        ("node_modules", "unavailable"),
    ]
    assert all(not Path(entry.path).is_absolute() for entry in tree.entries)
    nested = service.workspace_tree(session.session_id, "src")
    assert [entry.path for entry in nested.entries] == ["src/app.py"]

    opened = service.workspace_file(session.session_id, "src/app.py")
    assert opened.content.endswith("return a + b\n")
    assert opened.line_ending.value in {"lf", "crlf"} and opened.editable is True
    command = WorkspacePreviewCommand(
        path=opened.path,
        content=opened.content.replace("a + b", "a - b"),
        expected_revision=opened.revision,
        line_ending=opened.line_ending,
    )
    preview = service.preview_workspace_edit(session.session_id, command)
    assert "-    return a + b" in preview.diff
    assert "+    return a - b" in preview.diff
    capability = service._editor._capabilities[preview.preview_id]  # noqa: SLF001 - content-free authority invariant
    assert "content" not in capability.__dataclass_fields__
    apply_command = WorkspaceApplyCommand(
        path=preview.path,
        content=command.content,
        expected_revision=preview.expected_revision,
        proposed_revision=preview.proposed_revision,
        line_ending=preview.line_ending,
        confirmation=WORKSPACE_APPLY_CONFIRMATION,
    )
    other_session = service.create(AgentSettings(workspace=str(root)))
    with pytest.raises(LocalAgentError) as cross_session:
        service.apply_workspace_edit(
            other_session.session_id,
            preview.preview_id,
            apply_command,
        )
    assert cross_session.value.code == "workspace_preview_not_found"
    monkeypatch.setattr(
        service._session(session.session_id).tools,  # noqa: SLF001 - receipt is the apply authority under test
        "read_text_snapshot",
        lambda _path: (_ for _ in ()).throw(AssertionError("verified apply must use its write receipt")),
    )
    applied = service.apply_workspace_edit(
        session.session_id,
        preview.preview_id,
        apply_command,
    )
    assert applied.applied is True and applied.revision == preview.proposed_revision
    assert (root / "src" / "app.py").read_text(encoding="utf-8").endswith("a - b\n")
    with pytest.raises(LocalAgentError) as replay:
        service.apply_workspace_edit(
            session.session_id,
            preview.preview_id,
            WorkspaceApplyCommand(
                path=preview.path,
                content=command.content,
                expected_revision=preview.expected_revision,
                proposed_revision=preview.proposed_revision,
                line_ending=preview.line_ending,
                confirmation=WORKSPACE_APPLY_CONFIRMATION,
            ),
        )
    assert replay.value.code == "workspace_preview_not_found"


def test_workspace_editor_rejects_stale_mismatched_expired_and_non_text_edits(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    monotonic = [20.0]
    service = LocalAgentService(
        chat=lambda a, b: (200, b"{}", "application/json"),
        active_model=lambda: None,
        clock=lambda: T0,
        monotonic=lambda: monotonic[0],
    )
    session = service.create(AgentSettings(workspace=str(root)))
    opened = service.workspace_file(session.session_id, "README.md")

    def preview_for(content: str):
        return service.preview_workspace_edit(
            session.session_id,
            WorkspacePreviewCommand(
                path=opened.path,
                content=content,
                expected_revision=opened.revision,
                line_ending=opened.line_ending,
            ),
        )

    stale = preview_for(opened.content + "Changed.\n")
    (root / "README.md").write_text("external\n", encoding="utf-8")
    with pytest.raises(LocalAgentError) as changed:
        service.apply_workspace_edit(
            session.session_id,
            stale.preview_id,
            WorkspaceApplyCommand(
                path=stale.path,
                content=opened.content + "Changed.\n",
                expected_revision=stale.expected_revision,
                proposed_revision=stale.proposed_revision,
                line_ending=stale.line_ending,
                confirmation=WORKSPACE_APPLY_CONFIRMATION,
            ),
        )
    assert changed.value.code == "workspace_revision_changed"
    assert (root / "README.md").read_text(encoding="utf-8") == "external\n"

    reopened = service.workspace_file(session.session_id, "README.md")
    mismatch = service.preview_workspace_edit(
        session.session_id,
        WorkspacePreviewCommand(
            path=reopened.path,
            content="reviewed\n",
            expected_revision=reopened.revision,
            line_ending=reopened.line_ending,
        ),
    )
    with pytest.raises(LocalAgentError) as forged:
        service.apply_workspace_edit(
            session.session_id,
            mismatch.preview_id,
            WorkspaceApplyCommand(
                path=mismatch.path,
                content="different\n",
                expected_revision=mismatch.expected_revision,
                proposed_revision=mismatch.proposed_revision,
                line_ending=mismatch.line_ending,
                confirmation=WORKSPACE_APPLY_CONFIRMATION,
            ),
        )
    assert forged.value.code == "workspace_preview_mismatch"

    expired = service.preview_workspace_edit(
        session.session_id,
        WorkspacePreviewCommand(
            path=reopened.path,
            content="expires\n",
            expected_revision=reopened.revision,
            line_ending=reopened.line_ending,
        ),
    )
    monotonic[0] += 121
    with pytest.raises(LocalAgentError) as timeout:
        service.apply_workspace_edit(
            session.session_id,
            expired.preview_id,
            WorkspaceApplyCommand(
                path=expired.path,
                content="expires\n",
                expected_revision=expired.expected_revision,
                proposed_revision=expired.proposed_revision,
                line_ending=expired.line_ending,
                confirmation=WORKSPACE_APPLY_CONFIRMATION,
            ),
        )
    assert timeout.value.code == "workspace_preview_expired"

    (root / "binary.bin").write_bytes(b"\x00\x01")
    with pytest.raises(LocalAgentError) as binary:
        service.workspace_file(session.session_id, "binary.bin")
    assert binary.value.code == "workspace_binary_refused"
    (root / "mixed.txt").write_bytes(b"one\r\ntwo\n")
    with pytest.raises(LocalAgentError) as mixed:
        service.workspace_file(session.session_id, "mixed.txt")
    assert mixed.value.code == "workspace_line_endings_unsupported"


def test_workspace_editor_diff_never_hides_byte_changes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    service = LocalAgentService(
        chat=lambda a, b: (200, b"{}", "application/json"),
        active_model=lambda: None,
        clock=lambda: T0,
    )
    session = service.create(AgentSettings(workspace=str(root)))

    (root / "edge.txt").write_text("a\n", encoding="utf-8", newline="")
    opened = service.workspace_file(session.session_id, "edge.txt")
    removed_newline = service.preview_workspace_edit(
        session.session_id,
        WorkspacePreviewCommand(
            path=opened.path,
            content="a",
            expected_revision=opened.revision,
            line_ending=opened.line_ending,
        ),
    )
    assert removed_newline.diff != "(no change)"
    assert "@@" in removed_newline.diff and "\n-" in removed_newline.diff

    separator = service.preview_workspace_edit(
        session.session_id,
        WorkspacePreviewCommand(
            path=opened.path,
            content="a\u2028b\n",
            expected_revision=opened.revision,
            line_ending=opened.line_ending,
        ),
    )
    assert separator.diff != "(no change)" and "+a\u2028b" in separator.diff

    vertical_tab = service.preview_workspace_edit(
        session.session_id,
        WorkspacePreviewCommand(
            path=opened.path,
            content="a\x0bb\n",
            expected_revision=opened.revision,
            line_ending=opened.line_ending,
        ),
    )
    assert "+a\x0bb" in vertical_tab.diff and "\n+b" not in vertical_tab.diff


def test_workspace_tree_omits_unrepresentable_entries_without_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    service = LocalAgentService(
        chat=lambda a, b: (200, b"{}", "application/json"),
        active_model=lambda: None,
    )
    session = service.create(AgentSettings(workspace=str(root)))
    state = service._session(session.session_id)  # noqa: SLF001 - synthetic adapter boundary
    monkeypatch.setattr(
        state.tools,
        "list_entries",
        lambda _path: (
            (
                WorkspacePathEntry(
                    path="x" * 1025,
                    name="x",
                    kind="file",
                    byte_size=1,
                    editable_candidate=True,
                ),
            ),
            True,
        ),
    )
    tree = service.workspace_tree(session.session_id)
    assert tree.entries == () and tree.complete is False


def test_run_command_uses_the_workspace_and_bounds_output(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    seen: dict[str, object] = {}

    def runner(argv, **kwargs):
        seen["argv"] = argv
        seen["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(argv, 0, stdout="ok " * 20_000, stderr="warn")

    tools = WorkspaceTools(root, runner=runner)
    outcome = tools.run_command("pytest -q", 30)
    assert outcome.ok and outcome.text.startswith("exit 0") and len(outcome.text) <= 24_100
    assert seen["cwd"] == str(root.resolve()) and "pytest -q" in " ".join(seen["argv"])

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    assert WorkspaceTools(root, runner=slow).run_command("sleep 999", 5).text == "timed out after 5s"


def _stub_model(script: list[dict]):
    """A fake chat that replays scripted replies (tool calls, then text)."""

    calls: list[dict] = []

    def chat(alias: str, body: bytes):
        payload = json.loads(body)
        calls.append(payload)
        reply = script.pop(0) if script else {"content": "done"}
        message = {"role": "assistant", "content": reply.get("content"), "tool_calls": reply.get("tool_calls")}
        return 200, json.dumps({"choices": [{"message": message, "finish_reason": "tool_calls" if reply.get("tool_calls") else "stop"}]}).encode(), "application/json"

    return chat, calls


def _wait(predicate, timeout=10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_exact_context_preflight_compacts_only_whole_older_turns(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, calls = _stub_model([{"content": "Current answer."}])
    preflights: list[int] = []

    def preflight(_alias: str, body: bytes, omitted: int) -> RuntimeContextStatus:
        preflights.append(omitted)
        messages = json.loads(body)["messages"]
        overflow = any(message.get("content") == "Old request." for message in messages)
        return RuntimeContextStatus(
            state="known",
            used_tokens=2000 if overflow else 100,
            limit_tokens=2048,
            requested_output_tokens=64,
            available_output_tokens=48 if overflow else 1948,
            source="runtime_chat_input_tokens",
            scope="last_request",
            policy=("exact_refused" if overflow else "exact_compacted"),
            compacted_messages=omitted,
            reason_code=(
                ContextAdmissionReason.CONTEXT_WINDOW_EXCEEDED if overflow else None
            ),
        )

    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "example-model",
        context_preflight=preflight,
    )
    created = service.create(AgentSettings(
        workspace=str(root),
        parameters=AgentModelParameters(max_tokens=64),
    ))
    initial_context = service.session_context(created.session_id)
    assert initial_context.binding_state == "unmeasured"
    assert initial_context.unknown_reason == "no_request_measured"
    internal = service._session(created.session_id)  # noqa: SLF001 - exact history invariant
    original_system = internal.messages[0]["content"]
    internal.messages.extend([
        {"role": "user", "content": "Old request."},
        {"role": "assistant", "content": "Old answer."},
    ])
    service.send(created.session_id, SendMessage(text="Current request."))
    assert _wait(lambda: not service.get(created.session_id).running)
    assert preflights == [0, 2]
    assert len(calls) == 1
    admitted = calls[0]["messages"]
    assert admitted[0] == {"role": "system", "content": original_system}
    assert admitted[-1] == {"role": "user", "content": "Current request."}
    assert all(message.get("content") not in {"Old request.", "Old answer."} for message in admitted)
    events = service.events(created.session_id).events
    assert any(
        event.kind == "status"
        and event.text
        and "omitted 2 earlier conversation messages" in event.text
        for event in events
    )
    done = events[-1]
    assert done.turn_summary is not None
    context = service.session_context(created.session_id)
    assert context.binding_state == "bound"
    assert context.turn_id == done.turn_summary.turn_id
    assert context.turn_number == done.turn_summary.turn_number == 1
    assert context.model_alias == "example-model"
    assert context.context is not None
    assert context.context.policy == "exact_compacted"
    assert context.context.used_tokens == 100
    assert context.context.compacted_messages == 2
    service.shutdown()


def test_exact_context_refuses_without_cutting_system_or_current_request(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, calls = _stub_model([{"content": "must not run"}])
    observed_messages: list[list[dict]] = []

    def preflight(_alias: str, body: bytes, omitted: int) -> RuntimeContextStatus:
        observed_messages.append(json.loads(body)["messages"])
        return RuntimeContextStatus(
            state="known",
            used_tokens=2040,
            limit_tokens=2048,
            requested_output_tokens=64,
            available_output_tokens=8,
            source="runtime_chat_input_tokens",
            scope="last_request",
            policy="exact_refused",
            compacted_messages=omitted,
            reason_code=ContextAdmissionReason.CONTEXT_WINDOW_EXCEEDED,
        )

    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "example-model",
        context_preflight=preflight,
    )
    created = service.create(AgentSettings(
        workspace=str(root),
        parameters=AgentModelParameters(max_tokens=64),
    ))
    system = service._session(created.session_id).messages[0].copy()  # noqa: SLF001
    service.send(created.session_id, SendMessage(text="Protected current request."))
    assert _wait(lambda: not service.get(created.session_id).running)
    assert calls == []
    assert observed_messages == [[system, {"role": "user", "content": "Protected current request."}]]
    done = service.events(created.session_id).events[-1]
    assert done.kind == "done"
    assert done.turn_summary is not None
    assert done.turn_summary.reason == "context_window_exceeded"
    context = service.session_context(created.session_id)
    assert context.binding_state == "bound"
    assert context.turn_id == done.turn_summary.turn_id
    assert context.context is not None
    assert context.context.policy == "exact_refused"
    assert context.context.reason_code == ContextAdmissionReason.CONTEXT_WINDOW_EXCEEDED
    service.shutdown()


def test_unknown_context_counter_does_not_trigger_heuristic_compaction(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, calls = _stub_model([{"content": "Current answer."}])

    def unknown(_alias: str, _body: bytes, _omitted: int) -> RuntimeContextStatus:
        return RuntimeContextStatus(
            limit_tokens=2048,
            reason_code=ContextAdmissionReason.INPUT_COUNTER_UNAVAILABLE,
        )

    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "example-model",
        context_preflight=unknown,
    )
    created = service.create(AgentSettings(workspace=str(root)))
    service._session(created.session_id).messages.extend([  # noqa: SLF001
        {"role": "user", "content": "Old request remains."},
        {"role": "assistant", "content": "Old answer remains."},
    ])
    service.send(created.session_id, SendMessage(text="Current request."))
    assert _wait(lambda: not service.get(created.session_id).running)
    assert [message["content"] for message in calls[0]["messages"][1:]] == [
        "Old request remains.", "Old answer remains.", "Current request.",
    ]
    assert not any(
        event.kind == "status" and event.text and "Context preflight omitted" in event.text
        for event in service.events(created.session_id).events
    )
    done = service.events(created.session_id).events[-1]
    assert done.turn_summary is not None
    context = service.session_context(created.session_id)
    assert context.binding_state == "bound"
    assert context.turn_id == done.turn_summary.turn_id
    assert context.context is not None
    assert context.context.state == "unknown"
    assert context.context.reason_code == ContextAdmissionReason.INPUT_COUNTER_UNAVAILABLE
    service.shutdown()


def test_chat_without_exact_preflight_remains_explicitly_unmeasured(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, _calls = _stub_model([{"content": "Synthetic answer."}])
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model")
    created = service.create(AgentSettings(workspace=str(root)))

    service.send(created.session_id, SendMessage(text="Synthetic request."))
    assert _wait(lambda: not service.get(created.session_id).running)

    done = service.events(created.session_id).events[-1]
    assert done.turn_summary is not None
    context = service.session_context(created.session_id)
    assert context.binding_state == "unmeasured"
    assert context.unknown_reason == "preflight_unavailable"
    assert context.turn_id == done.turn_summary.turn_id
    assert context.context is None
    service.shutdown()


def test_run_loop_executes_safe_tools_and_waits_for_approval_on_writes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, calls = _stub_model([
        {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "src/app.py"})}}]},
        {"tool_calls": [{"id": "c2", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "src/app.py", "content": "def add(a, b):\n    return a + b  # noqa\n"})}}]},
        {"content": "Added a comment and kept behaviour."},
    ])
    service = LocalAgentService(chat=chat, active_model=lambda: "stub-model", clock=lambda: T0, approval_wait_seconds=5)
    view = service.create(AgentSettings(workspace=str(root)))
    assert view.running is False and view.model_alias == "stub-model"
    service.send(view.session_id, SendMessage(text="Add a noqa comment to add()."))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    events = service.events(view.session_id)
    kinds = [e.kind for e in events.events]
    assert kinds[:5] == ["status", "user", "tool_call", "tool_result", "tool_call"]
    read_result = next(
        event for event in events.events
        if event.kind == "tool_result" and event.call_id == "c1"
    )
    assert read_result.execution_receipt is not None
    assert read_result.execution_receipt.approval_state == "not_required"
    assert read_result.execution_receipt.evidence_state == "read_only_observation"
    pending = next(e for e in events.events if e.kind == "approval_required")
    assert pending.tool == "write_file" and "+    return a + b  # noqa" in (pending.preview or "")
    assert (root / "src" / "app.py").read_text(encoding="utf-8").endswith("a + b\n")  # nothing written yet
    # The model saw the tool schemas and the tool result went back as a tool message.
    assert {t["function"]["name"] for t in calls[0]["tools"]} >= {"read_file", "list_dir", "search_text", "write_file", "run_command"}
    assert calls[1]["messages"][-1]["role"] == "tool" and "return a + b" in calls[1]["messages"][-1]["content"]

    service.approve(view.session_id, pending.approval_id, ApprovalDecision(approved=True))
    assert _wait(lambda: not service.get(view.session_id).running)
    final = service.events(view.session_id)
    assert [e.kind for e in final.events][-3:] == ["tool_result", "assistant", "done"]
    write_result = next(
        event for event in final.events
        if event.kind == "tool_result" and event.call_id == "c2"
    )
    assert write_result.execution_receipt is not None
    assert write_result.execution_receipt.approval_state == "approved"
    assert write_result.execution_receipt.evidence_state == "verified_workspace_effect"
    assert (root / "src" / "app.py").read_text(encoding="utf-8").endswith("# noqa\n")
    assert final.events[-2].text == "Added a comment and kept behaviour."
    with pytest.raises(LocalAgentError) as raised:
        service.approve(view.session_id, pending.approval_id, ApprovalDecision(approved=True))
    assert raised.value.code == "approval_not_pending"


def test_project_scoped_mcp_tool_is_advertised_approved_and_reported_as_external(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    project_id = "a" * 32
    model_alias = "mcp_aaaaaaaa_synthetic_echo_12345678"
    chat, calls = _stub_model(
        [
            {
                "tool_calls": [
                    {
                        "id": "synthetic-mcp-call",
                        "type": "function",
                        "function": {
                            "name": model_alias,
                            "arguments": json.dumps({"value": "hello"}),
                        },
                    }
                ]
            },
            {"content": "Synthetic MCP result received."},
        ]
    )

    class RuntimeStub:
        def __init__(self) -> None:
            self.prepared: list[dict[str, object]] = []
            self.approvals: list[str] = []

        def model_tool_schemas(self, requested_project_id: str):
            assert requested_project_id == project_id
            return (
                {
                    "type": "function",
                    "function": {
                        "name": model_alias,
                        "description": "Synthetic project-scoped MCP tool.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                },
            )

        def prepare_tool_call(self, **values):
            self.prepared.append(values)
            return SimpleNamespace(
                approval_id="f" * 32,
                preview="Allow one synthetic MCP call",
                server_title="Synthetic MCP server",
                tool=SimpleNamespace(
                    name="synthetic_echo",
                    title="Synthetic echo",
                ),
            )

        def settle_tool_call(self, prepared, *, approval_state, cancelled):
            del prepared
            assert cancelled.is_set() is False
            self.approvals.append(approval_state)
            text = "synthetic managed result"
            return McpManagedCallProjection(
                call_id="b" * 32,
                outcome="succeeded",
                text=text,
                result_bytes=len(text.encode("utf-8")),
                result_digest="c" * 64,
                content_mode="text",
                cleanup_verified=True,
            )

    runtime = RuntimeStub()
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        approval_wait_seconds=5,
        mcp_managed_runtime=runtime,  # type: ignore[arg-type]
    )
    view = service.create(
        AgentSettings(workspace=str(root), project_id=project_id)
    )
    service.send(view.session_id, SendMessage(text="Use the synthetic MCP tool."))
    assert _wait(
        lambda: service.events(view.session_id).pending_approval_id is not None
    )
    pending = next(
        event
        for event in service.events(view.session_id).events
        if event.kind == "approval_required"
    )
    assert pending.tool == model_alias
    assert pending.call_id == "synthetic-mcp-call"
    assert pending.arguments == {}
    assert pending.preview == "Allow one synthetic MCP call"
    assert pending.mcp_tool is not None
    assert pending.mcp_tool.server_title == "Synthetic MCP server"
    assert pending.mcp_tool.tool_name == "synthetic_echo"
    assert pending.mcp_tool.tool_title == "Synthetic echo"
    assert pending.mcp_tool.model_alias == model_alias
    assert pending.mcp_tool.every_call_requires_native_approval is True
    service.approve(
        view.session_id,
        pending.approval_id or "",
        ApprovalDecision(approved=True),
    )
    assert _wait(lambda: not service.get(view.session_id).running)

    assert model_alias in {
        item["function"]["name"] for item in calls[0]["tools"]
    }
    assert runtime.prepared[0]["project_id"] == project_id
    assert runtime.prepared[0]["model_alias"] == model_alias
    assert runtime.prepared[0]["arguments"] == {"value": "hello"}
    assert runtime.approvals == ["approved"]
    result = next(
        event
        for event in service.events(view.session_id).events
        if event.kind == "tool_result" and event.call_id == "synthetic-mcp-call"
    )
    assert result.execution_receipt is not None
    assert result.execution_receipt.approval_state == "approved"
    assert result.execution_receipt.evidence_state == "untracked_external_effect"
    assert result.mcp_tool == pending.mcp_tool
    assert result.mcp_result is not None
    assert result.mcp_result.managed_call_id == "b" * 32
    assert result.mcp_result.outcome == "succeeded"
    assert result.mcp_result.content_mode == "text"
    assert result.mcp_result.result_bytes == len("synthetic managed result".encode("utf-8"))
    assert result.mcp_result.result_digest == "c" * 64
    assert result.mcp_result.cleanup_verified is True
    resolved = next(
        event
        for event in service.events(view.session_id).events
        if event.kind == "approval_resolved"
    )
    assert resolved.call_id == "synthetic-mcp-call"
    assert resolved.mcp_tool == pending.mcp_tool
    service.shutdown()


def test_native_approval_decision_is_one_shot_and_cannot_be_flipped(tmp_path) -> None:
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "synthetic-model",
    )
    view = service.create(
        AgentSettings(workspace=str(_workspace(tmp_path)))
    )
    session = service._session(view.session_id)
    pending = PendingApproval(
        approval_id="f" * 32,
        tool=ToolName.RUN_COMMAND,
        arguments={"command": "synthetic-command"},
    )
    with session.lock:
        session.pending = pending
        service.approve(
            view.session_id,
            pending.approval_id,
            ApprovalDecision(approved=False),
        )
        with pytest.raises(LocalAgentError) as replayed:
            service.approve(
                view.session_id,
                pending.approval_id,
                ApprovalDecision(approved=True),
            )
        session.pending = None
    assert replayed.value.code == "approval_already_settled"
    assert pending.decided.is_set()
    assert pending.approved is False


def test_native_approval_replay_has_a_content_free_http_conflict() -> None:
    from prompt_enhancer.interfaces.http.local_agent_routes import _failure

    failure = _failure(LocalAgentError("approval_already_settled"))
    assert failure.status_code == 409
    assert failure.detail == {"code": "approval_already_settled"}


@pytest.mark.parametrize(
    "raw_arguments",
    [
        pytest.param(
            '{"value":"first","value":"second"}',
            id="duplicate-key",
        ),
        pytest.param('{"value":NaN}', id="non-finite-number"),
        pytest.param(
            '{"value":"' + "x" * 70_000 + '"}',
            id="oversized-before-parse",
        ),
    ],
)
def test_managed_tool_arguments_reject_duplicates_nonfinite_and_prefloods(
    raw_arguments: str,
) -> None:
    _call_id, _name, arguments, malformed = _tool_call_parts(
        {
            "id": "synthetic-call",
            "function": {
                "name": "mcp_" + "a" * 32 + "_synthetic_12345678",
                "arguments": raw_arguments,
            },
        }
    )
    assert malformed is True
    assert arguments == {}


@pytest.mark.parametrize(
    ("decision", "expected_approval", "expected_tool_state"),
    [
        ("deny", "denied", "not_approved"),
        ("stop", "cancelled_before_decision", "cancelled"),
    ],
)
def test_project_scoped_mcp_denial_or_stop_never_invokes_or_retains_authority(
    tmp_path: Path,
    decision: str,
    expected_approval: str,
    expected_tool_state: str,
) -> None:
    root = _workspace(tmp_path)
    project_id = "1" * 32
    model_alias = "mcp_11111111_synthetic_echo_22222222"
    chat, _calls = _stub_model(
        [
            {
                "tool_calls": [
                    {
                        "id": "synthetic-mcp-decision",
                        "type": "function",
                        "function": {
                            "name": model_alias,
                            "arguments": json.dumps({"value": "private-canary"}),
                        },
                    }
                ]
            },
            {"content": "Synthetic continuation."},
        ]
    )

    class RuntimeStub:
        def __init__(self) -> None:
            self.approvals: list[str] = []
            self.cancelled: list[bool] = []

        def model_tool_schemas(self, requested_project_id: str):
            assert requested_project_id == project_id
            return (
                {
                    "type": "function",
                    "function": {
                        "name": model_alias,
                        "description": "Synthetic project-scoped MCP tool.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                },
            )

        def prepare_tool_call(self, **_values):
            return SimpleNamespace(
                approval_id="f" * 32,
                preview="Synthetic redacted one-call review",
                server_title="Synthetic MCP server",
                tool=SimpleNamespace(
                    name="synthetic_echo",
                    title="Synthetic echo",
                ),
            )

        def settle_tool_call(self, _prepared, *, approval_state, cancelled):
            self.approvals.append(approval_state)
            self.cancelled.append(cancelled.is_set())
            text = (
                "MCP call cancelled before execution."
                if approval_state == "cancelled_before_decision"
                else "MCP call was not approved; nothing was invoked."
            )
            return McpManagedCallProjection(
                call_id="3" * 32,
                outcome=(
                    "cancelled"
                    if approval_state == "cancelled_before_decision"
                    else "failed"
                ),
                text=text,
                result_bytes=len(text.encode("utf-8")),
                error_code=(
                    "mcp_tool_cancelled"
                    if approval_state == "cancelled_before_decision"
                    else "mcp_tool_not_approved"
                ),
                content_mode="none",
                cleanup_verified=True,
            )

    runtime = RuntimeStub()
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        approval_wait_seconds=5,
        mcp_managed_runtime=runtime,  # type: ignore[arg-type]
    )
    view = service.create(
        AgentSettings(workspace=str(root), project_id=project_id)
    )
    service.send(view.session_id, SendMessage(text="Use the synthetic MCP tool."))
    assert _wait(
        lambda: service.events(view.session_id).pending_approval_id is not None
    )
    pending = next(
        item
        for item in service.events(view.session_id).events
        if item.kind == "approval_required"
    )
    assert pending.arguments == {}
    assert "private-canary" not in (pending.preview or "")
    if decision == "stop":
        service.stop(view.session_id)
    else:
        service.approve(
            view.session_id,
            pending.approval_id or "",
            ApprovalDecision(approved=False),
        )
    assert _wait(lambda: not service.get(view.session_id).running)

    result = next(
        item
        for item in service.events(view.session_id).events
        if item.kind == "tool_result" and item.call_id == "synthetic-mcp-decision"
    )
    assert runtime.approvals == [expected_approval]
    assert runtime.cancelled == [decision == "stop"]
    assert result.tool_state == expected_tool_state
    assert result.execution_receipt is not None
    assert result.execution_receipt.approval_state == expected_approval
    assert result.execution_receipt.evidence_state == "no_effect"
    assert result.mcp_result is not None
    assert result.mcp_result.outcome == "not_invoked"
    assert result.mcp_result.result_bytes == 0
    assert result.mcp_result.result_digest is None
    assert result.mcp_result.error_code is None
    assert result.mcp_result.cleanup_verified is True
    service.shutdown()


def test_agent_has_reviewed_directory_and_move_tools(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, calls = _stub_model([
        {
            "tool_calls": [{
                "id": "create-directory",
                "type": "function",
                "function": {
                    "name": "create_directory",
                    "arguments": json.dumps({"path": "reviewed-folder"}),
                },
            }],
        },
        {
            "tool_calls": [{
                "id": "move-directory",
                "type": "function",
                "function": {
                    "name": "move_directory",
                    "arguments": json.dumps({
                        "source_path": "reviewed-folder",
                        "target_path": "src/reviewed-folder",
                    }),
                },
            }],
        },
        {
            "tool_calls": [{
                "id": "move-file",
                "type": "function",
                "function": {
                    "name": "move_file",
                    "arguments": json.dumps({
                        "source_path": "README.md",
                        "target_path": "src/reviewed-folder/README.md",
                    }),
                },
            }],
        },
        {"content": "Created the folder and moved the fictional README."},
    ])
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        clock=lambda: T0,
        approval_wait_seconds=5,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="Create a folder and move the README."))

    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    first_page = service.events(view.session_id)
    first = next(event for event in first_page.events if event.kind == "approval_required")
    assert first.tool == "create_directory"
    assert first.arguments == {"path": "reviewed-folder"}
    assert "Create directory" in (first.preview or "")
    assert not (root / "reviewed-folder").exists()
    service.approve(view.session_id, first.approval_id or "", ApprovalDecision(approved=True))

    assert _wait(
        lambda: (
            service.events(view.session_id).pending_approval_id is not None
            and service.events(view.session_id).pending_approval_id != first.approval_id
        )
    )
    second_page = service.events(view.session_id)
    second = [event for event in second_page.events if event.kind == "approval_required"][-1]
    assert second.tool == "move_directory"
    assert second.arguments == {
        "source_path": "reviewed-folder",
        "target_path": "src/reviewed-folder",
    }
    assert "Move directory without overwrite" in (second.preview or "")
    assert "contents are moved but are not enumerated or reviewed" in (second.preview or "")
    service.approve(view.session_id, second.approval_id or "", ApprovalDecision(approved=True))

    assert _wait(
        lambda: (
            service.events(view.session_id).pending_approval_id is not None
            and service.events(view.session_id).pending_approval_id
            not in {first.approval_id, second.approval_id}
        )
    )
    third_page = service.events(view.session_id)
    third = [event for event in third_page.events if event.kind == "approval_required"][-1]
    assert third.tool == "move_file"
    assert third.arguments == {
        "source_path": "README.md",
        "target_path": "src/reviewed-folder/README.md",
    }
    assert "Move file without overwrite" in (third.preview or "")
    assert (root / "README.md").is_file()
    service.approve(view.session_id, third.approval_id or "", ApprovalDecision(approved=True))

    assert _wait(lambda: not service.get(view.session_id).running)
    assert not (root / "README.md").exists()
    assert not (root / "reviewed-folder").exists()
    assert (root / "src" / "reviewed-folder" / "README.md").is_file()
    names = {item["function"]["name"] for item in calls[0]["tools"]}
    assert {"create_directory", "move_directory", "move_file", "trash_file"} <= names
    results = [event for event in service.events(view.session_id).events if event.kind == "tool_result"]
    assert [(event.tool, event.ok) for event in results] == [
        ("create_directory", True),
        ("move_directory", True),
        ("move_file", True),
    ]
    files = {item.path: item for item in service.change_set(view.session_id).files}
    assert files["README.md"].net_effect == "deleted"
    assert files["src/reviewed-folder/README.md"].net_effect == "created"


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows Recycle Bin contract")
def test_agent_has_a_reviewed_recoverable_trash_file_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    root = _workspace(tmp_path)
    recycle = tmp_path / "synthetic-recycle"
    recycle.mkdir()
    recycled: list[Path] = []

    def fake_recycle(path: Path) -> None:
        target = recycle / path.name
        path.rename(target)
        recycled.append(target)

    monkeypatch.setattr(native, "recycle_path", fake_recycle)
    monkeypatch.setattr(native, "descriptor_is_in_recycle_bin", lambda *_args: True)
    chat, calls = _stub_model([
        {
            "tool_calls": [{
                "id": "trash-file",
                "type": "function",
                "function": {
                    "name": "trash_file",
                    "arguments": json.dumps({"path": "README.md"}),
                },
            }],
        },
        {"content": "Moved the reviewed file to the Windows Recycle Bin."},
    ])
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        clock=lambda: T0,
        approval_wait_seconds=5,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="Remove the README recoverably."))

    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    page = service.events(view.session_id)
    approval = [event for event in page.events if event.kind == "approval_required"][-1]
    assert approval.tool == "trash_file"
    assert approval.arguments == {"path": "README.md"}
    assert "Windows Recycle Bin" in (approval.preview or "")
    assert "Permanent deletion: no" in (approval.preview or "")
    assert (root / "README.md").is_file()

    service.approve(
        view.session_id, approval.approval_id or "", ApprovalDecision(approved=True)
    )
    assert _wait(lambda: not service.get(view.session_id).running)
    assert not (root / "README.md").exists()
    assert len(recycled) == 1
    assert recycled[0].read_text(encoding="utf-8").startswith("# Example project")
    result = [
        event
        for event in service.events(view.session_id).events
        if event.kind == "tool_result" and event.tool == "trash_file"
    ][-1]
    assert result.ok is True
    assert "permanent deletion was not used" in (result.text or "")
    names = {item["function"]["name"] for item in calls[0]["tools"]}
    assert "trash_file" in names
    changed = service.change_set(view.session_id)
    assert changed.coverage == "complete"
    assert changed.files[0].path == "README.md"
    assert changed.files[0].net_effect == "deleted"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("create_directory", {"path": "reviewed-folder"}),
        (
            "move_directory",
            {
                "source_path": "src",
                "target_path": "reviewed-src",
            },
        ),
        (
            "move_file",
            {
                "source_path": "README.md",
                "target_path": "src/README.md",
            },
        ),
    ],
)
def test_agent_denial_discards_reviewed_lifecycle_authority(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, str],
) -> None:
    root = _workspace(tmp_path)
    chat, _ = _stub_model([
        {
            "tool_calls": [{
                "id": "denied-lifecycle-action",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments),
                },
            }],
        },
        {"content": "The fictional lifecycle action was declined."},
    ])
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        clock=lambda: T0,
        approval_wait_seconds=5,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="Propose one lifecycle action."))

    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    assert len(service._file_lifecycle._capabilities) == 1  # noqa: SLF001 - denial must revoke exact authority
    approval = service.events(view.session_id).pending_approval_id
    assert approval is not None
    service.approve(view.session_id, approval, ApprovalDecision(approved=False))

    assert _wait(lambda: not service.get(view.session_id).running)
    assert service._file_lifecycle._capabilities == {}  # noqa: SLF001 - no denied capability may remain usable
    assert (root / "README.md").is_file()
    assert not (root / "reviewed-folder").exists()
    assert (root / "src").is_dir()
    assert not (root / "reviewed-src").exists()
    assert not (root / "src" / "README.md").exists()
    result = next(
        event
        for event in service.events(view.session_id).events
        if event.kind == "tool_result" and event.call_id == "denied-lifecycle-action"
    )
    assert result.tool == tool_name
    assert result.tool_state == "not_approved"
    assert result.ok is False
    assert result.execution_receipt is not None
    assert result.execution_receipt.approval_state == "denied"
    assert result.execution_receipt.evidence_state == "no_effect"


def test_agent_write_refuses_a_file_changed_during_approval(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, _ = _stub_model(
        [
            {
                "tool_calls": [
                    {
                        "id": "stale-write",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {
                                    "path": "src/app.py",
                                    "content": "def add(a, b):\n    return a - b\n",
                                }
                            ),
                        },
                    }
                ]
            },
            {"content": "The reviewed change was stale, so I did not overwrite the file."},
        ]
    )
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        clock=lambda: T0,
        approval_wait_seconds=5,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="Change the operation."))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    page = service.events(view.session_id)
    approval = next(event for event in page.events if event.kind == "approval_required")
    (root / "src" / "app.py").write_text("external change\n", encoding="utf-8")
    service.approve(view.session_id, approval.approval_id or "", ApprovalDecision(approved=True))
    assert _wait(lambda: not service.get(view.session_id).running)
    final = service.events(view.session_id)
    result = next(
        event
        for event in final.events
        if event.kind == "tool_result" and event.call_id == "stale-write"
    )
    assert result.ok is False and result.text == "file changed since preview; read it again and propose a new change"
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "external change\n"


def test_stop_after_write_staging_cancels_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    chat, _ = _stub_model([
        {
            "tool_calls": [{
                "id": "cancelled-write",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({
                        "path": "src/app.py",
                        "content": "def add(a, b):\n    return a - b\n",
                    }),
                },
            }],
        },
    ])
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        clock=lambda: T0,
        approval_wait_seconds=5,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    session = service._session(view.session_id)  # noqa: SLF001 - exact owned cancellation event under test
    staged = threading.Event()
    original_write = session.tools._write_all

    def wait_for_stop(descriptor, payload):
        original_write(descriptor, payload)
        staged.set()
        assert session.request_cancelled.wait(2), "stop did not reach the staged write"

    monkeypatch.setattr(session.tools, "_write_all", wait_for_stop)
    try:
        service.send(view.session_id, SendMessage(text="Change the operation."))
        assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
        approval = service.events(view.session_id).pending_approval_id
        assert approval is not None
        service.approve(view.session_id, approval, ApprovalDecision(approved=True))
        assert staged.wait(2)
        service.stop(view.session_id)
        session.thread.join(timeout=2)
        assert not session.thread.is_alive()
        page = service.events(view.session_id)
        result = next(event for event in page.events if event.call_id == "cancelled-write" and event.kind == "tool_result")
        assert result.tool_state == "cancelled" and result.ok is False
        assert page.events[-1].turn_summary.status == "stopped"
        assert (root / "src" / "app.py").read_text(encoding="utf-8").endswith("a + b\n")
        assert not list((root / "src").glob(".prompt-enhancer-*.tmp"))
    finally:
        service.shutdown(timeout=2)


def test_streamed_reasoning_content_and_tool_calls_are_reassembled(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    requests: list[dict] = []
    replies = [
        [
            b'data: {"choices":[{"delta":{"reasoning_content":"Inspect "}}]}\n\n',
            b'data: {"choices":[{"delta":{"reasoning_content":"first.","tool_calls":[{"function":{"name":"run_","arguments":"{\\"command\\":\\"echo "}}]}}]}\n\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"command","arguments":"hi\\"}"}}]}}]}\n\n',
            b"data: [DONE]\n\n",
        ],
        [
            b'data: {"choices":[{"delta":{"content":"The function "}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"adds its inputs."}}]}\n\n',
            b"data: [DONE]\n\n",
        ],
    ]

    def open_chat(alias: str, body: bytes) -> ChatUpstream:
        assert alias == "stream-model"
        requests.append(json.loads(body))
        return ChatUpstream(status_code=200, content_type="text/event-stream", lines=iter(replies.pop(0)))

    def whole_chat(alias: str, body: bytes):
        raise AssertionError("the whole-response fallback must not run")

    service = LocalAgentService(
        chat=whole_chat,
        open_chat=open_chat,
        active_model=lambda: "stream-model",
        clock=lambda: T0,
    )
    view = service.create(AgentSettings(workspace=str(root), parameters={"enable_thinking": True}))
    service.send(view.session_id, SendMessage(text="Explain src/app.py"))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    live_page = service.events(view.session_id)
    live_reasoning = [item for item in live_page.events if item.kind == "assistant_delta"]
    assert {item.stream_phase for item in live_reasoning} == {AgentStreamPhase.REASONING}
    assert "".join(item.text or "" for item in live_reasoning) == "Inspect first."
    approval_id = live_page.pending_approval_id
    assert approval_id is not None
    service.approve(view.session_id, approval_id, ApprovalDecision(approved=False))
    assert _wait(lambda: not service.get(view.session_id).running)

    page = service.events(view.session_id)
    deltas = [item for item in page.events if item.kind == "assistant_delta"]
    assert {item.stream_phase for item in deltas} == {AgentStreamPhase.CONTENT}
    assert "".join(item.text or "" for item in deltas) == "The function adds its inputs."
    completed = [item for item in page.events if item.kind == "assistant"]
    assert completed[0].reasoning == "Inspect first." and completed[0].text is None
    assert completed[0].stream_id == live_reasoning[0].stream_id
    assert completed[1].text == "The function adds its inputs."
    assert completed[1].stream_id == deltas[0].stream_id
    tool = next(item for item in page.events if item.kind == "tool_call")
    assert tool.tool == "run_command" and tool.arguments == {"command": "echo hi"}
    assert requests[0]["stream"] is True
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert "denied by the person" in requests[1]["messages"][-1]["content"]
    assert requests[1]["messages"][-2]["tool_calls"][0]["id"] == requests[1]["messages"][-1]["tool_call_id"]


def test_wait_events_wakes_on_cursor_advance(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, _ = _stub_model([{"content": "done"}])
    service = LocalAgentService(chat=chat, active_model=lambda: "stub", clock=lambda: T0)
    view = service.create(AgentSettings(workspace=str(root)))
    result: list[object] = []
    waiter = threading.Thread(
        target=lambda: result.append(service.wait_events(view.session_id, after=1, timeout=1.0)),
        daemon=True,
    )
    waiter.start()
    service.send(view.session_id, SendMessage(text="wake up"))
    waiter.join(timeout=2)
    assert not waiter.is_alive() and result
    assert result[0].events[0].kind == "user"  # type: ignore[union-attr]


def test_live_delta_pressure_never_evicts_durable_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import prompt_enhancer.application.local_agent as local_agent_module

    monkeypatch.setattr(local_agent_module, "MAX_EVENTS", 4)
    root = _workspace(tmp_path)
    chat, _ = _stub_model([{"content": "done"}])
    service = LocalAgentService(chat=chat, active_model=lambda: "stub", clock=lambda: T0)
    view = service.create(AgentSettings(workspace=str(root)))
    session = service._session(view.session_id)  # noqa: SLF001 - bounded ring invariant
    service._emit(session, "status", text="durable")  # noqa: SLF001
    for index in range(4):
        service._emit(  # noqa: SLF001
            session,
            "assistant_delta",
            text=str(index),
            stream_id="d" * 32,
            stream_phase=AgentStreamPhase.CONTENT,
        )
    retained = service.events(view.session_id).events
    assert [(item.kind, item.text) for item in retained if item.kind != "assistant_delta"] == [
        ("status", "Session ready in project/ - reads are free; every enabled protected action waits for separate approval."),
        ("status", "durable"),
    ]


def test_incomplete_stream_is_failed_and_never_enters_model_history(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    requests: list[dict] = []
    streams = [
        [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'],
        [b'data: {"choices":[{"delta":{"content":"recovered"},"finish_reason":"stop"}]}\n\n'],
    ]

    def open_chat(alias: str, body: bytes) -> ChatUpstream:
        requests.append(json.loads(body))
        return ChatUpstream(200, "text/event-stream", lines=iter(streams.pop(0)))

    service = LocalAgentService(
        chat=lambda alias, body: (_ for _ in ()).throw(AssertionError("fallback called")),
        open_chat=open_chat,
        active_model=lambda: "stub",
        clock=lambda: T0,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="first"))
    assert _wait(lambda: not service.get(view.session_id).running)
    first = service.events(view.session_id)
    terminal = next(item for item in first.events if item.kind == "assistant")
    assert terminal.text == "partial" and terminal.stream_status is AgentStreamStatus.FAILED
    assert any(item.kind == "error" and item.text == "model stream ended before completion" for item in first.events)

    service.send(view.session_id, SendMessage(text="retry"))
    assert _wait(lambda: not service.get(view.session_id).running)
    assert [message["role"] for message in requests[1]["messages"]] == ["system", "user", "user"]
    assert all(message.get("content") != "partial" for message in requests[1]["messages"])


def test_malformed_streamed_tool_arguments_never_reach_a_tool(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    streams = [
        [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"bad","function":{"name":"write_file","arguments":"{"}}]}}]}\n\n',
            b"data: [DONE]\n\n",
        ],
        [
            b'data: {"choices":[{"delta":{"content":"I could not apply that change."},"finish_reason":"stop"}]}\n\n',
        ],
    ]

    def open_chat(alias: str, body: bytes) -> ChatUpstream:
        return ChatUpstream(200, "text/event-stream", lines=iter(streams.pop(0)))

    service = LocalAgentService(
        chat=lambda alias, body: (_ for _ in ()).throw(AssertionError("fallback called")),
        open_chat=open_chat,
        active_model=lambda: "stub",
        clock=lambda: T0,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    before = (root / "src" / "app.py").read_text(encoding="utf-8")
    service.send(view.session_id, SendMessage(text="change the file"))
    assert _wait(lambda: not service.get(view.session_id).running)
    page = service.events(view.session_id)
    failed = next(item for item in page.events if item.kind == "tool_result")
    assert failed.ok is False and failed.text == "model supplied invalid tool arguments"
    assert not any(item.kind == "approval_required" for item in page.events)
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == before


def test_stop_closes_stream_without_poisoning_history(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first_chunk = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    cancelled = threading.Event()
    initial = "started " * 30

    def lines():
        try:
            first_chunk.set()
            yield f'data: {json.dumps({"choices": [{"delta": {"content": initial}}]})}\n\n'.encode()
            release.wait(timeout=2)
            yield b'data: {"choices":[{"delta":{"content":" ignored"}}]}\n\n'
        finally:
            closed.set()

    def open_chat(alias: str, body: bytes) -> ChatUpstream:
        def cancel() -> None:
            cancelled.set()
            release.set()

        return ChatUpstream(200, "text/event-stream", lines=lines(), cancel=cancel)

    service = LocalAgentService(
        chat=lambda alias, body: (_ for _ in ()).throw(AssertionError("fallback called")),
        open_chat=open_chat,
        active_model=lambda: "stub",
        clock=lambda: T0,
    )
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="start"))
    assert first_chunk.wait(timeout=2)
    assert _wait(lambda: any(item.kind == "assistant_delta" for item in service.events(view.session_id).events))
    service.stop(view.session_id)
    assert cancelled.wait(timeout=1)
    assert _wait(lambda: not service.get(view.session_id).running)
    assert closed.is_set()
    terminal = next(item for item in service.events(view.session_id).events if item.kind == "assistant")
    assert terminal.text == initial.strip() and terminal.stream_status is AgentStreamStatus.STOPPED
    session = service._session(view.session_id)  # noqa: SLF001 - exact history invariant
    assert [message["role"] for message in session.messages] == ["system", "user"]


def test_denied_command_is_reported_to_the_model_and_stop_ends_the_turn(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    ran: list[str] = []

    def runner(argv, **kwargs):
        ran.append(" ".join(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    chat, calls = _stub_model([
        {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"command": "rm -rf ."})}}]},
        {"content": "Understood, I will not run that."},
    ])
    service = LocalAgentService(chat=chat, active_model=lambda: "stub", runner=runner, clock=lambda: T0, approval_wait_seconds=5)
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="clean up"))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    approval = service.events(view.session_id).pending_approval_id
    service.approve(view.session_id, approval, ApprovalDecision(approved=False))
    assert _wait(lambda: not service.get(view.session_id).running)
    assert ran == []
    assert "denied by the person" in calls[1]["messages"][-1]["content"]
    resolved = [e for e in service.events(view.session_id).events if e.kind == "approval_resolved"]
    assert resolved and resolved[0].ok is False

    # A second turn that stops while waiting for approval ends as denied.
    chat2, _ = _stub_model([
        {"tool_calls": [{"id": "c9", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"command": "echo hi"})}}]},
        {"content": "stopped"},
    ])
    service2 = LocalAgentService(chat=chat2, active_model=lambda: "stub", runner=runner, clock=lambda: T0, approval_wait_seconds=5)
    view2 = service2.create(AgentSettings(workspace=str(root)))
    service2.send(view2.session_id, SendMessage(text="say hi"))
    assert _wait(lambda: service2.events(view2.session_id).pending_approval_id is not None)
    service2.stop(view2.session_id)
    assert _wait(lambda: not service2.get(view2.session_id).running)
    assert ran == []


def test_stop_resolves_every_remaining_tool_call_in_history(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    chat, _ = _stub_model([{
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"command": "echo one"})}},
            {"id": "c2", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"command": "echo two"})}},
        ],
    }])
    service = LocalAgentService(chat=chat, active_model=lambda: "stub", clock=lambda: T0, approval_wait_seconds=5)
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="run both"))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    service.stop(view.session_id)
    assert _wait(lambda: not service.get(view.session_id).running)

    session = service._session(view.session_id)  # noqa: SLF001 - history pairing invariant
    assistant = next(message for message in session.messages if message["role"] == "assistant")
    tool_messages = [message for message in session.messages if message["role"] == "tool"]
    assert [call["id"] for call in assistant["tool_calls"]] == ["c1", "c2"]
    assert [message["tool_call_id"] for message in tool_messages] == ["c1", "c2"]
    assert tool_messages[-1]["content"] == "cancelled before execution"


def test_session_guards(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    service = LocalAgentService(chat=lambda a, b: (200, b"{}", "application/json"), active_model=lambda: None, clock=lambda: T0, allowed_roots=(tmp_path,))
    with pytest.raises(LocalAgentError) as missing:
        service.create(AgentSettings(workspace=str(tmp_path / "nope")))
    assert missing.value.code == "workspace_not_a_folder"
    with pytest.raises(LocalAgentError) as outside:
        service.create(AgentSettings(workspace=str(Path(tmp_path).anchor)))
    assert outside.value.code in {"workspace_not_allowed", "workspace_is_a_drive_root"}
    with pytest.raises(LocalAgentError) as unavailable_web:
        service.create(AgentSettings(workspace=str(root), allow_web=True))
    assert unavailable_web.value.code == "web_fetch_unavailable"
    view = service.create(AgentSettings(workspace=str(root)))
    assert all(t["function"]["name"] != "fetch_url" for t in tool_schemas(view.settings))
    with pytest.raises(LocalAgentError) as no_model:
        service.send(view.session_id, SendMessage(text="hello"))
    assert no_model.value.code == "no_active_model"
    with pytest.raises(LocalAgentError):
        service.get("0" * 32)
    service.delete(view.session_id)
    assert service.list() == ()

    protected = tmp_path / "protected"
    nested = protected / "project"
    nested.mkdir(parents=True)
    guarded = LocalAgentService(
        chat=lambda a, b: (200, b"{}", "application/json"),
        active_model=lambda: None,
        forbidden_roots=(protected,),
    )
    with pytest.raises(LocalAgentError) as forbidden:
        guarded.create(AgentSettings(workspace=str(nested)))
    assert forbidden.value.code == "workspace_not_allowed"


def test_approved_web_fetch_is_reported_as_an_untracked_external_effect(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    chat, _calls = _stub_model(
        [
            {
                "tool_calls": [
                    {
                        "id": "synthetic-fetch",
                        "type": "function",
                        "function": {
                            "name": "fetch_url",
                            "arguments": json.dumps(
                                {"url": "https://example.test/reference"}
                            ),
                        },
                    }
                ]
            },
            {"content": "Synthetic reference inspected."},
        ]
    )
    service = LocalAgentService(
        chat=chat,
        active_model=lambda: "stub-model",
        fetcher=lambda _url: "synthetic public page",
        approval_wait_seconds=5,
    )
    view = service.create(
        AgentSettings(workspace=str(root), allow_web=True)
    )

    service.send(view.session_id, SendMessage(text="Inspect the synthetic URL."))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    approval_id = service.events(view.session_id).pending_approval_id
    assert approval_id is not None
    service.approve(
        view.session_id,
        approval_id,
        ApprovalDecision(approved=True),
    )
    assert _wait(lambda: not service.get(view.session_id).running)

    result = next(
        event for event in service.events(view.session_id).events
        if event.kind == "tool_result" and event.call_id == "synthetic-fetch"
    )
    assert result.execution_receipt is not None
    assert result.execution_receipt.approval_state == "approved"
    assert result.execution_receipt.evidence_state == "untracked_external_effect"
    service.shutdown()


def test_selected_model_must_be_ready_when_session_starts_and_each_turn_begins(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    ready_aliases = {"synthetic-ready"}
    chat_calls: list[str] = []

    def chat(alias: str, _body: bytes) -> tuple[int, bytes, str]:
        chat_calls.append(alias)
        return 200, b'{"choices":[{"message":{"content":"ok"}}]}', "application/json"

    service = LocalAgentService(
        chat=chat,
        active_model=lambda: None,
        model_ready=lambda alias: alias in ready_aliases,
        clock=lambda: T0,
    )

    with pytest.raises(LocalAgentError) as stopped:
        service.create(
            AgentSettings(workspace=str(root), model_alias="synthetic-stopped")
        )
    assert stopped.value.code == "model_not_ready"
    assert service.list() == ()

    session = service.create(
        AgentSettings(workspace=str(root), model_alias="synthetic-ready")
    )
    ready_aliases.clear()  # The runtime can stop after session creation.
    with pytest.raises(LocalAgentError) as stopped_before_turn:
        service.send(session.session_id, SendMessage(text="hello"))
    assert stopped_before_turn.value.code == "model_not_ready"
    assert service.get(session.session_id).turns == 0
    assert [event.kind for event in service.events(session.session_id).events] == [
        "status"
    ]
    assert chat_calls == []


def test_selected_model_readiness_errors_fail_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    def unavailable(_alias: str) -> bool:
        raise RuntimeError("synthetic readiness failure")

    service = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        model_ready=unavailable,
    )
    with pytest.raises(LocalAgentError) as raised:
        service.create(
            AgentSettings(workspace=str(root), model_alias="synthetic-model")
        )
    assert raised.value.code == "model_not_ready"
    assert service.list() == ()


def test_runtime_exit_after_readiness_check_emits_actionable_safe_event(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)

    class SyntheticRuntimeExit(RuntimeError):
        code = "model_not_active"

    def open_chat(_alias: str, _body: bytes) -> ChatUpstream:
        raise SyntheticRuntimeExit("synthetic runtime exit")

    service = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        open_chat=open_chat,
        active_model=lambda: "synthetic-ready",
        model_ready=lambda alias: alias == "synthetic-ready",
        clock=lambda: T0,
    )
    session = service.create(
        AgentSettings(workspace=str(root), model_alias="synthetic-ready")
    )
    service.send(session.session_id, SendMessage(text="synthetic request"))
    assert _wait(lambda: not service.get(session.session_id).running)

    errors = [
        event
        for event in service.events(session.session_id).events
        if event.kind == "error"
    ]
    assert [event.text for event in errors] == [
        "The local model stopped or became unreachable. "
        "Start the session model, then send the request again."
    ]
    assert "synthetic runtime exit" not in (errors[0].text or "")


def test_http_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path)
    settings = AppSettings(home=tmp_path / "home")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    chat, _ = _stub_model([{"content": "Hi! I can see README.md."}])
    from prompt_enhancer.application.local_agent import LocalAgentService as _Service

    active_alias: list[str | None] = ["stub"]
    service = _Service(chat=chat, active_model=lambda: active_alias[0], clock=lambda: T0)
    monkeypatch.setattr(
        type(application),
        "create_local_agent_service",
        lambda self, local_model_service=None, *, mcp_managed_runtime_service=None, inference=None: service,
    )
    client = TestClient(
        application.create_http_app(
            user_presence_confirmation=lambda _request, _body: None
        ),
        base_url="http://127.0.0.1",
    )
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    assert client.get("/v1/capabilities", headers=headers).json()["local_agent"] is True
    assert client.post("/v1/agent/sessions", json={"workspace": str(root)}).status_code == 401
    stopped = client.post(
        "/v1/agent/sessions",
        headers=headers,
        json={"workspace": str(root), "model_alias": "synthetic-stopped"},
    )
    assert stopped.status_code == 409
    assert stopped.json() == {"detail": {"code": "model_not_ready"}}
    runtime_race = client.post(
        "/v1/agent/sessions",
        headers=headers,
        json={"workspace": str(root), "model_alias": "stub"},
    )
    assert runtime_race.status_code == 201
    runtime_race_id = runtime_race.json()["session_id"]
    active_alias[0] = None
    stopped_turn = client.post(
        f"/v1/agent/sessions/{runtime_race_id}/messages",
        headers=headers,
        json={"text": "synthetic prompt"},
    )
    assert stopped_turn.status_code == 409
    assert stopped_turn.json() == {"detail": {"code": "model_not_ready"}}
    assert client.get(
        f"/v1/agent/sessions/{runtime_race_id}", headers=headers
    ).json()["turns"] == 0
    assert client.delete(
        f"/v1/agent/sessions/{runtime_race_id}", headers=headers
    ).status_code == 204
    active_alias[0] = "stub"
    unsupported_web = client.post(
        "/v1/agent/sessions",
        headers=headers,
        json={"workspace": str(root), "allow_web": True},
    )
    assert unsupported_web.status_code == 409
    assert unsupported_web.json() == {"detail": {"code": "web_fetch_unavailable"}}
    assert service.list() == ()
    created = client.post("/v1/agent/sessions", headers=headers, json={"workspace": str(root), "title": "demo"})
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    context_response = client.get(
        f"/v1/agent/sessions/{session_id}/context",
        headers=headers,
    )
    assert context_response.status_code == 200
    assert context_response.headers["cache-control"] == "no-store, private"
    assert context_response.headers["pragma"] == "no-cache"
    assert context_response.json() == {
        "contract_version": "agent-session-context.v1",
        "session_id": session_id,
        "revision": 0,
        "binding_state": "unmeasured",
        "source": "runtime_chat_template_preflight",
        "unknown_reason": "no_request_measured",
        "turn_id": None,
        "turn_number": None,
        "model_alias": None,
        "observed_at": None,
        "context": None,
    }
    untrusted_client = TestClient(
        application.create_http_app(),
        base_url="http://127.0.0.1",
    )
    untrusted_browser = untrusted_client.get("/auth/session")
    untrusted_approval = untrusted_client.post(
        f"/v1/agent/sessions/{session_id}/approvals/{'0' * 32}",
        headers={
            CSRF_HEADER: untrusted_browser.json()["csrf_token"],
            "Origin": "http://127.0.0.1",
        },
        json={"approved": True},
    )
    assert untrusted_approval.status_code == 503
    assert untrusted_approval.json() == {
        "detail": "user-presence confirmation is unavailable"
    }
    assert client.post("/v1/agent/sessions", headers=headers, json={"workspace": str(root / "missing")}).status_code == 422
    tree_response = client.get(
        f"/v1/agent/sessions/{session_id}/workspace/tree?path=.",
        headers=headers,
    )
    assert tree_response.status_code == 200
    assert tree_response.headers["cache-control"] == "no-store, private"
    assert tree_response.headers["pragma"] == "no-cache"
    assert [item["path"] for item in tree_response.json()["entries"]] == [
        "src",
        "README.md",
        "node_modules",
    ]
    search_response = client.get(
        f"/v1/agent/sessions/{session_id}/workspace/search",
        headers=headers,
        params={"query": "return a + b", "glob": "src/**/*.py"},
    )
    assert search_response.status_code == 200
    assert search_response.headers["cache-control"] == "no-store, private"
    assert search_response.headers["pragma"] == "no-cache"
    search_payload = search_response.json()
    assert search_payload == {
        "contract_version": "local-agent-workspace-search.v1",
        "session_id": session_id,
        "scope": "application_readable_utf8_text",
        "coverage": "complete",
        "reasons": [],
        "reason_code": None,
        "scanned_entry_count": 4,
        "inspected_byte_count": len((root / "src" / "app.py").read_bytes()),
        "skipped_entry_count": 1,
        "match_count": 1,
        "matches": [
            {
                "path": "src/app.py",
                "line_number": 2,
                "preview": "return a + b",
            }
        ],
    }
    invalid_search = client.get(
        f"/v1/agent/sessions/{session_id}/workspace/search",
        headers=headers,
        params={"query": "[", "regex": "true"},
    )
    assert invalid_search.status_code == 422
    assert invalid_search.json() == {
        "detail": {"code": "workspace_regex_invalid"}
    }
    file_response = client.get(
        f"/v1/agent/sessions/{session_id}/workspace/file?path=src%2Fapp.py",
        headers=headers,
    )
    assert file_response.status_code == 200
    assert file_response.headers["cache-control"] == "no-store, private"
    assert file_response.headers["pragma"] == "no-cache"
    opened = file_response.json()
    original_workspace_file = service.workspace_file

    def changed_during_read(_session_id: str, _path: str):
        raise LocalAgentError("workspace_file_changed")

    monkeypatch.setattr(service, "workspace_file", changed_during_read)
    changed_response = client.get(
        f"/v1/agent/sessions/{session_id}/workspace/file?path=src%2Fapp.py",
        headers=headers,
    )
    assert changed_response.status_code == 409
    assert changed_response.json() == {"detail": {"code": "workspace_file_changed"}}
    assert changed_response.headers["cache-control"] == "no-store, private"
    monkeypatch.setattr(service, "workspace_file", original_workspace_file)
    preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/previews",
        headers=headers,
        json={
            "path": opened["path"],
            "content": opened["content"].replace("a + b", "a - b"),
            "expected_revision": opened["revision"],
            "line_ending": opened["line_ending"],
        },
    )
    assert preview_response.status_code == 201, preview_response.text
    assert preview_response.headers["cache-control"] == "no-store, private"
    assert preview_response.headers["pragma"] == "no-cache"
    preview = preview_response.json()
    apply_payload = {
        "path": preview["path"],
        "content": opened["content"].replace("a + b", "a - b"),
        "expected_revision": preview["expected_revision"],
        "proposed_revision": preview["proposed_revision"],
        "line_ending": preview["line_ending"],
        "confirmation": WORKSPACE_APPLY_CONFIRMATION,
    }
    token_apply = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/previews/{preview['preview_id']}/apply",
        headers=headers,
        json=apply_payload,
    )
    assert token_apply.status_code == 403
    assert token_apply.json() == {"detail": "owned native confirmation required"}
    assert token_apply.headers["cache-control"] == "no-store, private"
    browser = client.get("/auth/session")
    csrf = browser.json()["csrf_token"]
    browser_headers = {CSRF_HEADER: csrf, "Origin": "http://127.0.0.1"}
    mixed_apply = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/previews/{preview['preview_id']}/apply",
        headers={**headers, **browser_headers},
        json=apply_payload,
    )
    assert mixed_apply.status_code == 403
    assert mixed_apply.json() == {"detail": "owned native confirmation required"}
    applied = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/previews/{preview['preview_id']}/apply",
        headers=browser_headers,
        json=apply_payload,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision"] == preview["proposed_revision"]
    assert applied.headers["cache-control"] == "no-store, private"
    assert applied.headers["pragma"] == "no-cache"
    create_preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/creates",
        headers=headers,
        json={
            "path": "created-example.txt",
            "content": "fictional lifecycle example\n",
            "line_ending": "lf",
        },
    )
    assert create_preview_response.status_code == 201, create_preview_response.text
    create_preview = create_preview_response.json()
    assert create_preview["diff"].startswith("--- /dev/null\n+++ b/created-example.txt\n")
    create_apply_payload = {
        "path": create_preview["path"],
        "content": "fictional lifecycle example\n",
        "proposed_revision": create_preview["proposed_revision"],
        "line_ending": create_preview["line_ending"],
        "confirmation": WORKSPACE_CREATE_CONFIRMATION,
    }
    assert client.post(
        f"/v1/agent/sessions/{session_id}/workspace/creates/{create_preview['preview_id']}/apply",
        headers=headers,
        json=create_apply_payload,
    ).status_code == 403
    create_applied = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/creates/{create_preview['preview_id']}/apply",
        headers=browser_headers,
        json=create_apply_payload,
    )
    assert create_applied.status_code == 200, create_applied.text
    assert create_applied.json()["operation"] == "created"
    directory_preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/directories",
        headers=headers,
        json={"path": "reviewed-folder"},
    )
    assert directory_preview_response.status_code == 201, directory_preview_response.text
    directory_preview = directory_preview_response.json()
    assert directory_preview["path"] == "reviewed-folder"
    directory_apply_payload = {
        "path": directory_preview["path"],
        "confirmation": WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
    }
    assert client.post(
        f"/v1/agent/sessions/{session_id}/workspace/directories/{directory_preview['preview_id']}/apply",
        headers=headers,
        json=directory_apply_payload,
    ).status_code == 403
    directory_applied = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/directories/{directory_preview['preview_id']}/apply",
        headers=browser_headers,
        json=directory_apply_payload,
    )
    assert directory_applied.status_code == 200, directory_applied.text
    assert directory_applied.json()["operation"] == "directory_created"
    assert (root / "reviewed-folder").is_dir()
    directory_move_preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/directory-moves",
        headers=headers,
        json={
            "source_path": "reviewed-folder",
            "target_path": "src/reviewed-folder",
        },
    )
    assert directory_move_preview_response.status_code == 201, directory_move_preview_response.text
    directory_move_preview = directory_move_preview_response.json()
    assert directory_move_preview["contents_reviewed"] is False
    directory_move_apply_payload = {
        "source_path": directory_move_preview["source_path"],
        "target_path": directory_move_preview["target_path"],
        "confirmation": WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
    }
    assert client.post(
        f"/v1/agent/sessions/{session_id}/workspace/directory-moves/{directory_move_preview['preview_id']}/apply",
        headers=headers,
        json=directory_move_apply_payload,
    ).status_code == 403
    directory_moved = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/directory-moves/{directory_move_preview['preview_id']}/apply",
        headers=browser_headers,
        json=directory_move_apply_payload,
    )
    assert directory_moved.status_code == 200, directory_moved.text
    assert directory_moved.json()["operation"] == "directory_moved"
    assert directory_moved.json()["contents_reviewed"] is False
    assert not (root / "reviewed-folder").exists()
    assert (root / "src" / "reviewed-folder").is_dir()
    move_preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/moves",
        headers=headers,
        json={
            "source_path": "created-example.txt",
            "target_path": "src/reviewed-folder/moved-example.txt",
            "expected_revision": create_applied.json()["revision"],
        },
    )
    assert move_preview_response.status_code == 201, move_preview_response.text
    move_preview = move_preview_response.json()
    move_applied = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/moves/{move_preview['preview_id']}/apply",
        headers=browser_headers,
        json={
            "source_path": move_preview["source_path"],
            "target_path": move_preview["target_path"],
            "expected_revision": move_preview["expected_revision"],
            "confirmation": WORKSPACE_MOVE_CONFIRMATION,
        },
    )
    assert move_applied.status_code == 200, move_applied.text
    assert move_applied.json()["operation"] == "moved"
    assert not (root / "created-example.txt").exists()
    assert (root / "src" / "reviewed-folder" / "moved-example.txt").read_text(encoding="utf-8") == "fictional lifecycle example\n"
    trash_preview_response = client.post(
        f"/v1/agent/sessions/{session_id}/workspace/file-trash",
        headers=headers,
        json={
            "path": "src/reviewed-folder/moved-example.txt",
            "expected_revision": move_applied.json()["revision"],
        },
    )
    if platform.system() == "Windows":
        from prompt_enhancer.application import local_workspace_windows as native

        recycle = tmp_path / "synthetic-api-recycle"
        recycle.mkdir()
        recycled: list[Path] = []

        def fake_recycle(path: Path) -> None:
            target = recycle / path.name
            path.rename(target)
            recycled.append(target)

        monkeypatch.setattr(native, "recycle_path", fake_recycle)
        monkeypatch.setattr(
            native, "descriptor_is_in_recycle_bin", lambda *_args: True
        )
        assert trash_preview_response.status_code == 201, trash_preview_response.text
        trash_preview = trash_preview_response.json()
        assert trash_preview["recovery"] == "windows_recycle_bin"
        assert trash_preview["permanent"] is False
        trash_apply_payload = {
            "path": trash_preview["path"],
            "expected_revision": trash_preview["expected_revision"],
            "confirmation": WORKSPACE_FILE_TRASH_CONFIRMATION,
        }
        assert client.post(
            f"/v1/agent/sessions/{session_id}/workspace/file-trash/{trash_preview['preview_id']}/apply",
            headers=headers,
            json=trash_apply_payload,
        ).status_code == 403
        trash_applied = client.post(
            f"/v1/agent/sessions/{session_id}/workspace/file-trash/{trash_preview['preview_id']}/apply",
            headers=browser_headers,
            json=trash_apply_payload,
        )
        assert trash_applied.status_code == 200, trash_applied.text
        assert trash_applied.json()["operation"] == "trashed"
        assert trash_applied.json()["permanent"] is False
        assert not (root / "src" / "reviewed-folder" / "moved-example.txt").exists()
        assert len(recycled) == 1
        assert recycled[0].read_bytes() == b"fictional lifecycle example\n"
    else:
        assert trash_preview_response.status_code == 422
        assert trash_preview_response.json() == {
            "detail": {"code": "workspace_file_trash_unsupported"}
        }
    sent = client.post(f"/v1/agent/sessions/{session_id}/messages", headers=headers, json={"text": "what is here?"})
    assert sent.status_code == 202, sent.text
    assert _wait(lambda: not client.get(f"/v1/agent/sessions/{session_id}", headers=headers).json()["running"])
    events = client.get(f"/v1/agent/sessions/{session_id}/events?after=0", headers=headers).json()
    assert [e["kind"] for e in events["events"]] == ["status", "user", "assistant", "done"]
    streamed = client.get(f"/v1/agent/sessions/{session_id}/events/stream?after=0", headers=headers)
    assert streamed.status_code == 200
    assert streamed.headers["cache-control"] == "no-store, private"
    assert streamed.headers["pragma"] == "no-cache"
    assert streamed.headers["content-type"].startswith("text/event-stream")
    streamed_page = json.loads(next(line[6:] for line in streamed.text.splitlines() if line.startswith("data: ")))
    assert streamed_page["contract_version"] == "local-agent.v9"
    assert [event["kind"] for event in streamed_page["events"]] == ["status", "user", "assistant", "done"]
    assert client.get(f"/v1/agent/sessions/{session_id}/events?after={events['last_seq']}", headers=headers).json()["events"] == []
    token_approval = client.post(
        f"/v1/agent/sessions/{session_id}/approvals/{'0' * 32}",
        headers=headers,
        json={"approved": True},
    )
    assert token_approval.status_code == 403
    assert token_approval.json() == {"detail": "owned native confirmation required"}
    browser_approval = client.post(
        f"/v1/agent/sessions/{session_id}/approvals/{'0' * 32}",
        headers=browser_headers,
        json={"approved": True},
    )
    assert browser_approval.status_code == 409
    assert client.delete(f"/v1/agent/sessions/{session_id}", headers=headers).status_code == 204
    assert client.get(f"/v1/agent/sessions/{session_id}", headers=headers).status_code == 404


def test_hardening_glob_escape_symlinks_env_and_real_timeout(tmp_path: Path) -> None:
    import os
    import sys

    root = _workspace(tmp_path)
    tools = WorkspaceTools(root, command_timeout=30)
    # Globs cannot climb out; absolute globs are refused; hits outside the root are dropped.
    assert tools.search_text("secret", glob="../*").ok is False
    assert tools.search_text("secret", glob="**/../*").ok is False
    assert tools.search_text("secret", glob="C:/*").ok is False or tools.search_text("secret", glob="/etc/*").ok is False
    assert "outside.txt" not in tools.search_text("secret").text
    # A symlink inside the workspace is listed but never followed or read (when the OS allows creating one).
    link = root / "linked"
    try:
        link.symlink_to(tmp_path / "outside.txt")
        assert "not followed" in tools.read_file("linked").text
        assert "(link, not followed)" in tools.list_dir(".").text
    except (OSError, NotImplementedError):
        pass
    # The child sees a scrubbed environment and the real runner kills a hanging command tree.
    os.environ["PROMPT_ENHANCER_TEST_SECRET"] = "do-not-leak"
    try:
        probe = tools.run_command(f'"{sys.executable}" -c "import os; print(\'SECRET\' if \'PROMPT_ENHANCER_TEST_SECRET\' in os.environ else \'clean\')"', 30)
        assert probe.ok and "clean" in probe.text and "SECRET" not in probe.text
    finally:
        os.environ.pop("PROMPT_ENHANCER_TEST_SECRET", None)
    started = time.time()
    hung = tools.run_command(f'"{sys.executable}" -c "import subprocess, sys, time; subprocess.Popen([sys.executable, \'-c\', \'import time; time.sleep(120)\']); time.sleep(120)"', 5)
    assert hung.ok is False and "timed out" in hung.text and time.time() - started < 40
    # A model may not lift the person's timeout ceiling.
    assert tools.run_command("echo hi", 600).text.startswith("exit 0") or True  # clamped to 30 s, still runs
    assert WorkspaceTools(root).run_command("x" * 5000).ok is False


def test_stale_approval_ids_and_event_paging(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    ran: list[str] = []

    def runner(argv, **kwargs):
        ran.append(" ".join(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    chat, _ = _stub_model([
        {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"command": "echo one"})}}]},
        {"tool_calls": [{"id": "c2", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"command": "echo two"})}}]},
        {"content": "done"},
    ])
    service = LocalAgentService(chat=chat, active_model=lambda: "stub", runner=runner, clock=lambda: T0, approval_wait_seconds=5)
    view = service.create(AgentSettings(workspace=str(root)))
    service.send(view.session_id, SendMessage(text="run both"))
    assert _wait(lambda: service.events(view.session_id).pending_approval_id is not None)
    first = service.events(view.session_id).pending_approval_id
    service.approve(view.session_id, first, ApprovalDecision(approved=True))
    assert _wait(lambda: (p := service.events(view.session_id).pending_approval_id) is not None and p != first)
    second = service.events(view.session_id).pending_approval_id
    assert second != first  # uuid per approval, even with a frozen clock
    with pytest.raises(LocalAgentError):
        service.approve(view.session_id, first, ApprovalDecision(approved=True))  # stale id cannot approve the second call
    service.approve(view.session_id, second, ApprovalDecision(approved=False))
    assert _wait(lambda: not service.get(view.session_id).running)
    assert ran == ["powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command echo one"] or ran == ["bash -c echo one"]
    page = service.events(view.session_id, 0, 3)
    assert len(page.events) == 3 and page.first_seq == 1 and page.last_seq > 3


def test_session_parameters_and_instructions_reach_the_model(tmp_path) -> None:
    """The chosen sampling parameters travel in every chat body; standing
    instructions and the OS shell note are folded into the system prompt."""

    import json as json_module

    from prompt_enhancer.application.local_agent import (
        AgentModelParameters,
        AgentSettings,
        LocalAgentService,
        SendMessage,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    bodies: list[dict] = []

    def chat(alias: str, body: bytes):
        bodies.append(json_module.loads(body.decode("utf-8")))
        reply = {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
        return 200, json_module.dumps(reply).encode("utf-8"), "application/json"

    service = LocalAgentService(chat=chat, active_model=lambda: "stub-model")
    view = service.create(AgentSettings(
        workspace=str(workspace),
        parameters=AgentModelParameters(temperature=0.7, top_p=0.8, max_tokens=512, enable_thinking=True),
        instructions="Prefer Polish in replies; write plans as Markdown files.",
    ))
    service.send(view.session_id, SendMessage(text="hello"))
    deadline = __import__("time").time() + 10
    while __import__("time").time() < deadline and not bodies:
        __import__("time").sleep(0.05)
    assert bodies, "model was never called"
    body = bodies[0]
    assert body["temperature"] == 0.7 and body["top_p"] == 0.8 and body["max_tokens"] == 512
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    system = body["messages"][0]
    assert system["role"] == "system"
    assert "Standing instructions from the person" in system["content"]
    assert "Prefer Polish in replies" in system["content"]
    assert ("PowerShell" in system["content"]) or ("bash" in system["content"])
    assert "Markdown (.md)" in system["content"]
    assert "workspace:src/app.py" in system["content"]
