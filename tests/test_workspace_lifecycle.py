"""Reviewed workspace create and move lifecycle contracts use synthetic files only."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sys

import pytest

from prompt_enhancer.application.local_agent_file_lifecycle import (
    MAX_ACTIVE_LIFECYCLE_PREVIEWS_PER_SESSION,
    WORKSPACE_CREATE_CONFIRMATION,
    WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
    WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
    WORKSPACE_FILE_TRASH_CONFIRMATION,
    WORKSPACE_MOVE_CONFIRMATION,
    LocalAgentWorkspaceFileLifecycle,
    WorkspaceCreateApplyCommand,
    WorkspaceCreatePreviewCommand,
    WorkspaceDirectoryCreateApplyCommand,
    WorkspaceDirectoryCreatePreviewCommand,
    WorkspaceDirectoryMoveApplyCommand,
    WorkspaceDirectoryMovePreviewCommand,
    WorkspaceFileTrashApplyCommand,
    WorkspaceFileTrashPreviewCommand,
    WorkspaceMoveApplyCommand,
    WorkspaceMovePreviewCommand,
)
from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService
from prompt_enhancer.application.local_agent_limits import LocalAgentError
from prompt_enhancer.application.local_agent_workspace import WorkspaceTools


SESSION = "a" * 32
OTHER_SESSION = "b" * 32
T0 = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


def _create_apply(preview, content: str) -> WorkspaceCreateApplyCommand:
    return WorkspaceCreateApplyCommand(
        path=preview.path,
        content=content,
        proposed_revision=preview.proposed_revision,
        line_ending=preview.line_ending,
        confirmation=WORKSPACE_CREATE_CONFIRMATION,
    )


def _move_apply(preview) -> WorkspaceMoveApplyCommand:
    return WorkspaceMoveApplyCommand(
        source_path=preview.source_path,
        target_path=preview.target_path,
        expected_revision=preview.expected_revision,
        confirmation=WORKSPACE_MOVE_CONFIRMATION,
    )


def _directory_apply(preview) -> WorkspaceDirectoryCreateApplyCommand:
    return WorkspaceDirectoryCreateApplyCommand(
        path=preview.path,
        confirmation=WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
    )


def _directory_move_apply(preview) -> WorkspaceDirectoryMoveApplyCommand:
    return WorkspaceDirectoryMoveApplyCommand(
        source_path=preview.source_path,
        target_path=preview.target_path,
        confirmation=WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
    )


def _trash_apply(preview) -> WorkspaceFileTrashApplyCommand:
    return WorkspaceFileTrashApplyCommand(
        path=preview.path,
        expected_revision=preview.expected_revision,
        confirmation=WORKSPACE_FILE_TRASH_CONFIRMATION,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_reviewed_file_trash_prepares_one_revision_bound_recoverable_file(tmp_path) -> None:
    source = tmp_path / "fictional.txt"
    source.write_bytes(b"synthetic recoverable removal\n")
    tools = WorkspaceTools(tmp_path)

    prepared = tools.prepare_file_trash("fictional.txt")

    assert prepared.path == "fictional.txt"
    assert prepared.source_sha256 == tools.read_text_snapshot("fictional.txt").revision
    assert prepared.byte_size == len("synthetic recoverable removal\n".encode("utf-8"))
    assert prepared.recovery == "windows_recycle_bin"
    assert prepared.permanent is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_reviewed_file_trash_is_verified_recoverable_and_single_use(
    tmp_path, monkeypatch
) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    source = tmp_path / "fictional.txt"
    source.write_bytes(b"synthetic recoverable removal\n")
    recycle = tmp_path / "synthetic-recycle"
    recycle.mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    snapshot = tools.read_text_snapshot("fictional.txt")
    preview = lifecycle.preview_file_trash(
        SESSION,
        tools,
        WorkspaceFileTrashPreviewCommand(
            path="fictional.txt", expected_revision=snapshot.revision
        ),
    )
    recycled: list = []

    def fake_recycle(path) -> None:
        target = recycle / path.name
        path.rename(target)
        recycled.append(target)

    monkeypatch.setattr(native, "recycle_path", fake_recycle)
    monkeypatch.setattr(native, "descriptor_is_in_recycle_bin", lambda *_args: True)

    applied = lifecycle.apply_file_trash(
        SESSION, preview.preview_id, tools, _trash_apply(preview)
    )

    assert applied.operation == "trashed"
    assert applied.recovery == "windows_recycle_bin"
    assert applied.permanent is False
    assert applied.revision == snapshot.revision
    assert not source.exists()
    assert len(recycled) == 1
    assert recycled[0].read_bytes() == b"synthetic recoverable removal\n"
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_file_trash(
            SESSION, preview.preview_id, tools, _trash_apply(preview)
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_file_trash_native_failure_restores_the_exact_reviewed_file(
    tmp_path, monkeypatch
) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    source = tmp_path / "fictional.txt"
    source.write_bytes(b"reviewed bytes\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_file_trash("fictional.txt")
    monkeypatch.setattr(
        native,
        "recycle_path",
        lambda _path: (_ for _ in ()).throw(OSError("synthetic refusal")),
    )

    outcome = tools.apply_prepared_file_trash(prepared)

    assert outcome.state == "rejected"
    assert outcome.code == "workspace_file_trash_failed"
    assert source.read_bytes() == b"reviewed bytes\n"
    assert not any(path.name.startswith(".prompt-enhancer-trash-") for path in tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_file_trash_timeout_never_rolls_back_beneath_a_live_shell_worker(
    tmp_path, monkeypatch
) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    source = tmp_path / "fictional.txt"
    source.write_bytes(b"reviewed bytes\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_file_trash("fictional.txt")
    rollback_calls: list[object] = []

    def unsettled(_path) -> None:
        raise native.RecycleOperationUnverified("synthetic pending Shell worker")

    monkeypatch.setattr(native, "recycle_path", unsettled)
    monkeypatch.setattr(
        tools,
        "_rollback_prepared_file_trash",
        lambda *args: rollback_calls.append(args) or True,
    )

    outcome = tools.apply_prepared_file_trash(prepared)

    assert outcome.state == "unverified"
    assert outcome.code == "workspace_file_trash_unverified"
    assert rollback_calls == []
    assert not source.exists()
    staged = [path for path in tmp_path.iterdir() if path.name.startswith(".prompt-enhancer-trash-")]
    assert len(staged) == 1
    assert staged[0].read_bytes() == b"reviewed bytes\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin worker")
def test_windows_recycle_worker_wait_is_bounded(tmp_path, monkeypatch) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    joined: list[float | None] = []

    class PendingWorker:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def join(self, timeout=None) -> None:
            joined.append(timeout)

        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr(native.threading, "Thread", PendingWorker)

    with pytest.raises(native.RecycleOperationUnverified):
        native.recycle_path(tmp_path / "fictional.txt")

    assert joined == [native._RECYCLE_OPERATION_TIMEOUT_SECONDS]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_file_trash_rejects_a_changed_revision_before_staging(tmp_path) -> None:
    source = tmp_path / "fictional.txt"
    source.write_bytes(b"reviewed bytes\n")
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    snapshot = tools.read_text_snapshot("fictional.txt")
    preview = lifecycle.preview_file_trash(
        SESSION,
        tools,
        WorkspaceFileTrashPreviewCommand(
            path="fictional.txt", expected_revision=snapshot.revision
        ),
    )
    source.write_bytes(b"externally changed\n")

    with pytest.raises(LocalAgentError, match="^workspace_revision_changed$"):
        lifecycle.apply_file_trash(
            SESSION, preview.preview_id, tools, _trash_apply(preview)
        )

    assert source.read_bytes() == b"externally changed\n"
    assert not any(path.name.startswith(".prompt-enhancer-trash-") for path in tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_unverified_file_trash_preserves_a_racing_replacement_and_hard_locks(
    tmp_path, monkeypatch
) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    source = tmp_path / "fictional.txt"
    source.write_bytes(b"reviewed bytes\n")
    recycle = tmp_path / "synthetic-recycle"
    recycle.mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    snapshot = tools.read_text_snapshot("fictional.txt")
    preview = lifecycle.preview_file_trash(
        SESSION,
        tools,
        WorkspaceFileTrashPreviewCommand(
            path="fictional.txt", expected_revision=snapshot.revision
        ),
    )
    recycled: list = []

    def race_recycle(path) -> None:
        source.write_bytes(b"external replacement\n")
        target = recycle / path.name
        path.rename(target)
        recycled.append(target)

    monkeypatch.setattr(native, "recycle_path", race_recycle)
    monkeypatch.setattr(native, "descriptor_is_in_recycle_bin", lambda *_args: True)

    with pytest.raises(LocalAgentError, match="^workspace_file_trash_unverified$"):
        lifecycle.apply_file_trash(
            SESSION, preview.preview_id, tools, _trash_apply(preview)
        )

    assert source.read_bytes() == b"external replacement\n"
    assert len(recycled) == 1
    assert recycled[0].read_bytes() == b"reviewed bytes\n"
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_unverified$"):
        lifecycle.preview_directory_create(
            SESSION,
            tools,
            WorkspaceDirectoryCreatePreviewCommand(path="another"),
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin contract")
def test_file_trash_verification_failure_never_claims_success(
    tmp_path, monkeypatch
) -> None:
    from prompt_enhancer.application import local_workspace_windows as native

    source = tmp_path / "fictional.txt"
    source.write_bytes(b"reviewed bytes\n")
    recycle = tmp_path / "synthetic-recycle"
    recycle.mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    snapshot = tools.read_text_snapshot("fictional.txt")
    preview = lifecycle.preview_file_trash(
        SESSION,
        tools,
        WorkspaceFileTrashPreviewCommand(
            path="fictional.txt", expected_revision=snapshot.revision
        ),
    )

    def fake_recycle(path) -> None:
        path.rename(recycle / path.name)

    monkeypatch.setattr(native, "recycle_path", fake_recycle)
    monkeypatch.setattr(native, "descriptor_is_in_recycle_bin", lambda *_args: False)

    with pytest.raises(LocalAgentError, match="^workspace_file_trash_unverified$"):
        lifecycle.apply_file_trash(
            SESSION, preview.preview_id, tools, _trash_apply(preview)
        )

    assert not source.exists()
    assert len(list(recycle.iterdir())) == 1


def test_reviewed_directory_create_is_exact_single_use_and_content_free(tmp_path) -> None:
    (tmp_path / "docs").mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_directory_create(
        SESSION,
        tools,
        WorkspaceDirectoryCreatePreviewCommand(path="docs/guides"),
    )

    capability = lifecycle._capabilities[preview.preview_id]
    assert preview.path == "docs/guides"
    assert "content" not in repr(capability).casefold()
    applied = lifecycle.apply_directory_create(
        SESSION,
        preview.preview_id,
        tools,
        _directory_apply(preview),
    )

    assert applied.operation == "directory_created"
    assert applied.path == "docs/guides"
    assert (tmp_path / "docs" / "guides").is_dir()
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_directory_create(
            SESSION,
            preview.preview_id,
            tools,
            _directory_apply(preview),
        )


def test_reviewed_directory_create_preserves_a_racing_target(tmp_path, monkeypatch) -> None:
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_directory_create(
        SESSION,
        tools,
        WorkspaceDirectoryCreatePreviewCommand(path="guides"),
    )
    native_create = tools._create_directory_no_replace

    def inject_target_race(target, parent_descriptor) -> None:
        target.mkdir()
        (target / "external.txt").write_text("external\n", encoding="utf-8")
        native_create(target, parent_descriptor)

    monkeypatch.setattr(tools, "_create_directory_no_replace", inject_target_race)
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_target_exists$"):
        lifecycle.apply_directory_create(
            SESSION,
            preview.preview_id,
            tools,
            _directory_apply(preview),
        )

    assert (tmp_path / "guides" / "external.txt").read_text(encoding="utf-8") == "external\n"


def test_directory_create_verification_failure_hard_locks_without_speculative_cleanup(
    tmp_path,
    monkeypatch,
) -> None:
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_directory_create(
        SESSION,
        tools,
        WorkspaceDirectoryCreatePreviewCommand(path="guides"),
    )
    monkeypatch.setattr(tools, "_published_directory_verified", lambda *_args: False)

    with pytest.raises(LocalAgentError, match="^workspace_directory_create_unverified$"):
        lifecycle.apply_directory_create(
            SESSION,
            preview.preview_id,
            tools,
            _directory_apply(preview),
        )
    assert (tmp_path / "guides").is_dir()
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_unverified$"):
        lifecycle.preview_directory_create(
            SESSION,
            tools,
            WorkspaceDirectoryCreatePreviewCommand(path="another"),
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows parent-handle pinning")
def test_windows_directory_create_keeps_the_reviewed_parent_pinned(
    tmp_path,
    monkeypatch,
) -> None:
    parent = tmp_path / "docs"
    displaced = tmp_path / "docs-displaced"
    parent.mkdir()
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_directory_create("docs/guides")
    native_create = tools._create_directory_no_replace
    swap_succeeded = False

    def attempt_parent_swap(target, parent_descriptor) -> None:
        nonlocal swap_succeeded
        try:
            parent.rename(displaced)
        except OSError:
            pass
        else:
            swap_succeeded = True
            parent.mkdir()
        native_create(target, parent_descriptor)

    monkeypatch.setattr(tools, "_create_directory_no_replace", attempt_parent_swap)
    outcome = tools.apply_prepared_directory_create(prepared)

    assert outcome.state == "verified"
    assert swap_succeeded is False
    assert not displaced.exists()
    assert (parent / "guides").is_dir()


def test_reviewed_directory_move_preserves_the_subtree_without_overwrite(tmp_path) -> None:
    source = tmp_path / "docs"
    target_parent = tmp_path / "archive"
    source.mkdir()
    target_parent.mkdir()
    (source / "fictional.txt").write_text("synthetic directory move\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)

    prepared = tools.prepare_directory_move("docs", "archive/docs")
    outcome = tools.apply_prepared_directory_move(prepared)

    assert outcome.state == "verified"
    assert not source.exists()
    assert (target_parent / "docs" / "fictional.txt").read_text(encoding="utf-8") == (
        "synthetic directory move\n"
    )


def test_reviewed_directory_move_is_exact_single_use_and_content_free(tmp_path) -> None:
    source = tmp_path / "docs"
    target_parent = tmp_path / "archive"
    source.mkdir()
    target_parent.mkdir()
    (source / "private-canary.txt").write_text(
        "SYNTHETIC-DIRECTORY-CONTENT-CANARY\n", encoding="utf-8"
    )
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)

    preview = lifecycle.preview_directory_move(
        SESSION,
        tools,
        WorkspaceDirectoryMovePreviewCommand(
            source_path="docs", target_path="archive/reviewed-docs"
        ),
    )

    capability = lifecycle._capabilities[preview.preview_id]
    assert preview.contents_reviewed is False
    assert "SYNTHETIC-DIRECTORY-CONTENT-CANARY" not in repr(capability)
    applied = lifecycle.apply_directory_move(
        SESSION, preview.preview_id, tools, _directory_move_apply(preview)
    )
    assert applied.operation == "directory_moved"
    assert applied.contents_reviewed is False
    assert applied.source_path == "docs"
    assert applied.target_path == "archive/reviewed-docs"
    assert not source.exists()
    assert (target_parent / "reviewed-docs" / "private-canary.txt").is_file()
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_directory_move(
            SESSION, preview.preview_id, tools, _directory_move_apply(preview)
        )


def test_reviewed_directory_move_rejects_a_replaced_source_before_apply(tmp_path) -> None:
    source = tmp_path / "docs"
    displaced = tmp_path / "docs-displaced"
    target = tmp_path / "archive" / "docs"
    source.mkdir()
    target.parent.mkdir()
    (source / "reviewed.txt").write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_directory_move(
        SESSION,
        tools,
        WorkspaceDirectoryMovePreviewCommand(
            source_path="docs", target_path="archive/docs"
        ),
    )
    source.rename(displaced)
    source.mkdir()
    (source / "replacement.txt").write_text("replacement\n", encoding="utf-8")

    with pytest.raises(LocalAgentError, match="^workspace_revision_changed$"):
        lifecycle.apply_directory_move(
            SESSION, preview.preview_id, tools, _directory_move_apply(preview)
        )

    assert (source / "replacement.txt").read_text(encoding="utf-8") == "replacement\n"
    assert (displaced / "reviewed.txt").read_text(encoding="utf-8") == "reviewed\n"
    assert not target.exists()


def test_directory_move_native_collision_preserves_both_trees(tmp_path, monkeypatch) -> None:
    source = tmp_path / "docs"
    target = tmp_path / "archive" / "docs"
    source.mkdir()
    target.parent.mkdir()
    (source / "source.txt").write_text("source\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_directory_move("docs", "archive/docs")
    native_move = tools._rename_move_no_replace

    def inject_target_race(*args, **kwargs) -> None:
        target.mkdir()
        (target / "external.txt").write_text("external\n", encoding="utf-8")
        native_move(*args, **kwargs)

    monkeypatch.setattr(tools, "_rename_move_no_replace", inject_target_race)
    outcome = tools.apply_prepared_directory_move(prepared)

    assert outcome.state == "rejected"
    assert outcome.code == "workspace_lifecycle_target_exists"
    assert (source / "source.txt").read_text(encoding="utf-8") == "source\n"
    assert (target / "external.txt").read_text(encoding="utf-8") == "external\n"


def test_directory_move_verification_failure_rolls_back_exact_entry(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "docs"
    target = tmp_path / "archive" / "docs"
    source.mkdir()
    target.parent.mkdir()
    (source / "fictional.txt").write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_directory_move("docs", "archive/docs")
    monkeypatch.setattr(
        tools, "_published_directory_move_verified", lambda *_args: False
    )

    outcome = tools.apply_prepared_directory_move(prepared)

    assert outcome.state == "rejected"
    assert outcome.code == "workspace_revision_changed"
    assert (source / "fictional.txt").read_text(encoding="utf-8") == "reviewed\n"
    assert not target.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory-move handle pinning")
def test_windows_directory_move_pins_source_and_target_parent(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "docs"
    source_displaced = tmp_path / "docs-displaced"
    target_parent = tmp_path / "archive"
    parent_displaced = tmp_path / "archive-displaced"
    source.mkdir()
    target_parent.mkdir()
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_directory_move("docs", "archive/docs")
    native_move = tools._rename_move_no_replace
    swaps: list[str] = []

    def attempt_swaps(*args, **kwargs) -> None:
        try:
            source.rename(source_displaced)
        except OSError:
            pass
        else:
            swaps.append("source")
            source.mkdir()
        try:
            target_parent.rename(parent_displaced)
        except OSError:
            pass
        else:
            swaps.append("target_parent")
            target_parent.mkdir()
        native_move(*args, **kwargs)

    monkeypatch.setattr(tools, "_rename_move_no_replace", attempt_swaps)
    outcome = tools.apply_prepared_directory_move(prepared)

    assert outcome.state == "verified"
    assert swaps == []
    assert not source_displaced.exists()
    assert not parent_displaced.exists()
    assert (target_parent / "docs").is_dir()


def test_unverified_directory_move_hard_locks_lifecycle(tmp_path, monkeypatch) -> None:
    source = tmp_path / "docs"
    target = tmp_path / "archive" / "docs"
    source.mkdir()
    target.parent.mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_directory_move(
        SESSION,
        tools,
        WorkspaceDirectoryMovePreviewCommand(
            source_path="docs", target_path="archive/docs"
        ),
    )
    monkeypatch.setattr(
        tools, "_published_directory_move_verified", lambda *_args: False
    )
    monkeypatch.setattr(
        tools, "_rollback_prepared_directory_move", lambda *_args: False
    )

    with pytest.raises(LocalAgentError, match="^workspace_directory_move_unverified$"):
        lifecycle.apply_directory_move(
            SESSION, preview.preview_id, tools, _directory_move_apply(preview)
        )
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_unverified$"):
        lifecycle.preview_directory_create(
            SESSION,
            tools,
            WorkspaceDirectoryCreatePreviewCommand(path="another"),
        )
    assert not source.exists()
    assert target.is_dir()


@pytest.mark.parametrize(
    ("source", "target", "code"),
    [
        ("docs", "docs", "workspace directory move paths must differ"),
        ("docs", "docs/nested/moved", "workspace_directory_move_into_self"),
        (".", "archive/root", "path_invalid"),
        ("docs", "../outside", "path_outside_workspace"),
    ],
)
def test_directory_move_refuses_ambiguous_or_escaping_topology(
    tmp_path, source: str, target: str, code: str
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "archive").mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle()
    with pytest.raises((LocalAgentError, ValueError), match=code):
        lifecycle.preview_directory_move(
            SESSION,
            tools,
            WorkspaceDirectoryMovePreviewCommand(
                source_path=source, target_path=target
            ),
        )


@pytest.mark.parametrize(
    ("source", "target", "code"),
    [
        ("missing", "archive/moved", "workspace_path_not_found"),
        ("ordinary.txt", "archive/moved", "workspace_not_a_directory"),
        ("docs", "missing-parent/moved", "workspace_parent_unavailable"),
    ],
)
def test_directory_move_requires_an_existing_ordinary_source_and_parent(
    tmp_path, source: str, target: str, code: str
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "ordinary.txt").write_text("synthetic\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    with pytest.raises(LocalAgentError, match=f"^{code}$"):
        tools.prepare_directory_move(source, target)


def test_reviewed_create_is_exact_single_use_and_content_free(tmp_path) -> None:
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    content = "fictional example\n"

    with pytest.raises(LocalAgentError, match="^workspace_parent_unavailable$"):
        lifecycle.preview_create(
            SESSION,
            tools,
            WorkspaceCreatePreviewCommand(path="notes/example.txt", content=content, line_ending="lf"),
        )


def test_reviewed_create_applies_exact_content_without_retaining_it(tmp_path) -> None:
    (tmp_path / "notes").mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    content = "fictional example\n"
    preview = lifecycle.preview_create(
        SESSION,
        tools,
        WorkspaceCreatePreviewCommand(path="notes/example.txt", content=content, line_ending="lf"),
    )

    capability = lifecycle._capabilities[preview.preview_id]
    assert content not in repr(capability)
    assert preview.diff.startswith("--- /dev/null\n+++ b/notes/example.txt\n")
    assert preview.proposed_revision == hashlib.sha256(content.encode()).hexdigest()

    applied = lifecycle.apply_create(
        SESSION,
        preview.preview_id,
        tools,
        _create_apply(preview, content),
    )
    assert applied.operation == "created"
    assert applied.path == "notes/example.txt"
    assert applied.revision == preview.proposed_revision
    assert (tmp_path / "notes" / "example.txt").read_bytes() == content.encode()

    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_create(SESSION, preview.preview_id, tools, _create_apply(preview, content))


def test_reviewed_create_rejects_forgery_and_target_race(tmp_path) -> None:
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_create(
        SESSION,
        tools,
        WorkspaceCreatePreviewCommand(path="example.txt", content="reviewed\n", line_ending="lf"),
    )
    forged = WorkspaceCreateApplyCommand(
        path=preview.path,
        content="forged\n",
        proposed_revision=preview.proposed_revision,
        line_ending=preview.line_ending,
        confirmation=WORKSPACE_CREATE_CONFIRMATION,
    )
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_mismatch$"):
        lifecycle.apply_create(SESSION, preview.preview_id, tools, forged)
    assert not (tmp_path / "example.txt").exists()

    preview = lifecycle.preview_create(
        SESSION,
        tools,
        WorkspaceCreatePreviewCommand(path="example.txt", content="reviewed\n", line_ending="lf"),
    )
    (tmp_path / "example.txt").write_text("external\n", encoding="utf-8")
    with pytest.raises(LocalAgentError, match="^workspace_revision_changed$"):
        lifecycle.apply_create(SESSION, preview.preview_id, tools, _create_apply(preview, "reviewed\n"))
    assert (tmp_path / "example.txt").read_text(encoding="utf-8") == "external\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows create publication race")
def test_reviewed_create_native_collision_preserves_external_target(tmp_path, monkeypatch) -> None:
    target_path = tmp_path / "example.txt"
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    preview = lifecycle.preview_create(
        SESSION,
        tools,
        WorkspaceCreatePreviewCommand(
            path="example.txt",
            content="reviewed\n",
            line_ending="lf",
        ),
    )
    publish_new = tools._publish_new_windows

    def inject_target_race(stage, target) -> None:
        target_path.write_text("external target\n", encoding="utf-8")
        publish_new(stage, target)

    monkeypatch.setattr(tools, "_publish_new_windows", inject_target_race)
    with pytest.raises(LocalAgentError, match="^workspace_revision_changed$"):
        lifecycle.apply_create(
            SESSION,
            preview.preview_id,
            tools,
            _create_apply(preview, "reviewed\n"),
        )

    assert target_path.read_text(encoding="utf-8") == "external target\n"
    retry = lifecycle.preview_create(
        SESSION,
        tools,
        WorkspaceCreatePreviewCommand(
            path="another.txt",
            content="reviewed\n",
            line_ending="lf",
        ),
    )
    assert retry.path == "another.txt"


def test_reviewed_move_is_exact_no_overwrite_and_single_use(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("fictional source\n", encoding="utf-8")
    (tmp_path / "archive").mkdir()
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    source = tools.read_text_snapshot("source.txt")
    preview = lifecycle.preview_move(
        SESSION,
        tools,
        WorkspaceMovePreviewCommand(
            source_path="source.txt",
            target_path="archive/moved.txt",
            expected_revision=source.revision,
        ),
    )
    assert preview.source_path == "source.txt"
    assert preview.target_path == "archive/moved.txt"
    assert "fictional source" not in repr(lifecycle._capabilities[preview.preview_id])

    applied = lifecycle.apply_move(SESSION, preview.preview_id, tools, _move_apply(preview))
    assert applied.operation == "moved"
    assert applied.source_path == "source.txt"
    assert applied.target_path == "archive/moved.txt"
    assert applied.revision == source.revision
    assert not (tmp_path / "source.txt").exists()
    assert (tmp_path / "archive" / "moved.txt").read_text(encoding="utf-8") == "fictional source\n"

    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_move(SESSION, preview.preview_id, tools, _move_apply(preview))


def test_reviewed_move_rejects_source_or_target_races_without_overwrite(tmp_path) -> None:
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    source = tools.read_text_snapshot("source.txt")

    preview = lifecycle.preview_move(
        SESSION,
        tools,
        WorkspaceMovePreviewCommand(source_path="source.txt", target_path="target.txt", expected_revision=source.revision),
    )
    target_path.write_text("external target\n", encoding="utf-8")
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_target_exists$"):
        lifecycle.apply_move(SESSION, preview.preview_id, tools, _move_apply(preview))
    assert source_path.read_text(encoding="utf-8") == "reviewed\n"
    assert target_path.read_text(encoding="utf-8") == "external target\n"

    target_path.unlink()
    preview = lifecycle.preview_move(
        SESSION,
        tools,
        WorkspaceMovePreviewCommand(source_path="source.txt", target_path="target.txt", expected_revision=source.revision),
    )
    source_path.write_text("changed externally\n", encoding="utf-8")
    with pytest.raises(LocalAgentError, match="^workspace_revision_changed$"):
        lifecycle.apply_move(SESSION, preview.preview_id, tools, _move_apply(preview))
    assert source_path.read_text(encoding="utf-8") == "changed externally\n"
    assert not target_path.exists()


def test_move_native_no_overwrite_closes_the_post_check_race(tmp_path, monkeypatch) -> None:
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_move("source.txt", "target.txt")
    native_move = tools._rename_move_no_replace

    def inject_target_race(*args, **kwargs) -> None:
        target_path.write_text("external target\n", encoding="utf-8")
        native_move(*args, **kwargs)

    monkeypatch.setattr(tools, "_rename_move_no_replace", inject_target_race)
    outcome = tools.apply_prepared_move(prepared)

    assert outcome.state == "rejected"
    assert outcome.code == "workspace_lifecycle_target_exists"
    assert source_path.read_text(encoding="utf-8") == "reviewed\n"
    assert target_path.read_text(encoding="utf-8") == "external target\n"


def test_move_verification_failure_rolls_back_before_rejection(tmp_path, monkeypatch) -> None:
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_move("source.txt", "target.txt")
    monkeypatch.setattr(tools, "_published_move_verified", lambda *_args: False)
    outcome = tools.apply_prepared_move(prepared)

    assert outcome.state == "rejected"
    assert outcome.code == "workspace_revision_changed"
    assert source_path.read_text(encoding="utf-8") == "reviewed\n"
    assert not target_path.exists()


def test_move_never_claims_rollback_without_exact_post_restore_readback(tmp_path, monkeypatch) -> None:
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_move("source.txt", "target.txt")
    read_open_descriptor = tools._read_open_descriptor
    calls = 0

    def corrupt_post_restore_readback(descriptor, **kwargs):
        nonlocal calls
        calls += 1
        payload, metadata = read_open_descriptor(descriptor, **kwargs)
        return (b"x" * len(payload), metadata) if calls >= 3 else (payload, metadata)

    monkeypatch.setattr(tools, "_published_move_verified", lambda *_args: False)
    monkeypatch.setattr(tools, "_read_open_descriptor", corrupt_post_restore_readback)
    outcome = tools.apply_prepared_move(prepared)

    assert calls == 6
    assert outcome.state == "unverified"
    assert outcome.code == "workspace_move_unverified"
    assert source_path.read_text(encoding="utf-8") == "reviewed\n"
    assert not target_path.exists()


def test_unverified_move_hard_locks_lifecycle_mutations(tmp_path, monkeypatch) -> None:
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("reviewed\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    source = tools.read_text_snapshot("source.txt")
    preview = lifecycle.preview_move(
        SESSION,
        tools,
        WorkspaceMovePreviewCommand(
            source_path="source.txt",
            target_path="target.txt",
            expected_revision=source.revision,
        ),
    )
    monkeypatch.setattr(tools, "_published_move_verified", lambda *_args: False)
    monkeypatch.setattr(tools, "_rollback_prepared_move", lambda *_args, **_kwargs: False)

    with pytest.raises(LocalAgentError, match="^workspace_move_unverified$"):
        lifecycle.apply_move(SESSION, preview.preview_id, tools, _move_apply(preview))
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_unverified$"):
        lifecycle.preview_create(
            SESSION,
            tools,
            WorkspaceCreatePreviewCommand(
                path="another.txt",
                content="reviewed\n",
                line_ending="lf",
            ),
        )

    assert not source_path.exists()
    assert target_path.read_text(encoding="utf-8") == "reviewed\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows rename buffer")
def test_windows_move_buffer_retains_native_structure_alignment(tmp_path, monkeypatch) -> None:
    import ctypes

    from prompt_enhancer.application import local_workspace_windows as native

    observed: list[tuple[int, int]] = []

    def set_information(_handle, information_class, _buffer, buffer_size):
        observed.append((information_class, buffer_size))
        return True

    monkeypatch.setattr(native, "_set_information", set_information)
    monkeypatch.setattr(native.msvcrt, "get_osfhandle", lambda _descriptor: 7)
    target = tmp_path / "target.txt"
    native.rename_descriptor_no_replace(3, target)

    encoded_size = len(str(target).encode("utf-16-le"))
    assert observed == [
        (
            native._FILE_RENAME_INFO,
            ctypes.sizeof(native._FileRenameInfo) + encoded_size,
        )
    ]


def test_lifecycle_capabilities_are_session_bound_and_expire(tmp_path) -> None:
    tools = WorkspaceTools(tmp_path)
    monotonic = [10.0]
    lifecycle = LocalAgentWorkspaceFileLifecycle(
        clock=lambda: T0,
        monotonic=lambda: monotonic[0],
        ttl_seconds=2,
    )
    preview = lifecycle.preview_create(
        SESSION,
        tools,
        WorkspaceCreatePreviewCommand(path="example.txt", content="reviewed\n", line_ending="lf"),
    )
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_create(OTHER_SESSION, preview.preview_id, tools, _create_apply(preview, "reviewed\n"))

    monotonic[0] = 12.0
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_expired$"):
        lifecycle.apply_create(SESSION, preview.preview_id, tools, _create_apply(preview, "reviewed\n"))


def test_lifecycle_capabilities_are_bounded_and_discarded_with_session(tmp_path) -> None:
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle(clock=lambda: T0, monotonic=lambda: 10.0)
    previews = [
        lifecycle.preview_create(
            SESSION,
            tools,
            WorkspaceCreatePreviewCommand(
                path=f"example-{index}.txt",
                content="reviewed\n",
                line_ending="lf",
            ),
        )
        for index in range(MAX_ACTIVE_LIFECYCLE_PREVIEWS_PER_SESSION + 1)
    ]

    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_create(
            SESSION,
            previews[0].preview_id,
            tools,
            _create_apply(previews[0], "reviewed\n"),
        )
    lifecycle.discard_session(SESSION)
    with pytest.raises(LocalAgentError, match="^workspace_lifecycle_preview_not_found$"):
        lifecycle.apply_create(
            SESSION,
            previews[-1].preview_id,
            tools,
            _create_apply(previews[-1], "reviewed\n"),
        )


@pytest.mark.parametrize(
    ("content", "line_ending"),
    [("one line", "lf"), ("one line\n", "none")],
)
def test_create_rejects_incoherent_line_ending_authority(content, line_ending) -> None:
    with pytest.raises(ValueError, match="line-ending style is incoherent"):
        WorkspaceCreatePreviewCommand(
            path="example.txt",
            content=content,
            line_ending=line_ending,
        )


def test_service_lifecycle_updates_the_reviewed_change_set(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("fictional source\n", encoding="utf-8")
    (tmp_path / "archive").mkdir()
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: "example-model",
    )
    session = service.create(AgentSettings(workspace=str(tmp_path)))

    created_preview = service.preview_workspace_create(
        session.session_id,
        WorkspaceCreatePreviewCommand(
            path="created.txt",
            content="fictional created\n",
            line_ending="lf",
        ),
    )
    service.apply_workspace_create(
        session.session_id,
        created_preview.preview_id,
        _create_apply(created_preview, "fictional created\n"),
    )

    source = service.workspace_file(session.session_id, "source.txt")
    move_preview = service.preview_workspace_move(
        session.session_id,
        WorkspaceMovePreviewCommand(
            source_path="source.txt",
            target_path="archive/source.txt",
            expected_revision=source.revision,
        ),
    )
    service.apply_workspace_move(
        session.session_id,
        move_preview.preview_id,
        _move_apply(move_preview),
    )

    changes = service.change_set(session.session_id)
    assert changes.coverage == "complete"
    assert changes.reviewed_writes == 3
    assert changes.manual_writes == 3
    files = {item.path: item for item in changes.files}
    assert files["created.txt"].net_effect == "created"
    assert files["source.txt"].net_effect == "deleted"
    assert files["source.txt"].verification == "verified"
    assert files["archive/source.txt"].net_effect == "created"
    assert files["archive/source.txt"].verification == "verified"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("example.txt", "example.txt"),
        ("../example.txt", "moved.txt"),
        ("example.txt", "../moved.txt"),
    ],
)
def test_move_refuses_same_or_escaping_paths(tmp_path, source: str, target: str) -> None:
    (tmp_path / "example.txt").write_text("fictional\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    lifecycle = LocalAgentWorkspaceFileLifecycle()
    with pytest.raises((LocalAgentError, ValueError)):
        lifecycle.preview_move(
            SESSION,
            tools,
            WorkspaceMovePreviewCommand(
                source_path=source,
                target_path=target,
                expected_revision=hashlib.sha256(b"fictional\n").hexdigest(),
            ),
        )
