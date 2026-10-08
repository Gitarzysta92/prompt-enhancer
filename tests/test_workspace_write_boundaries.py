"""Reviewed-write failures use only disposable fictional files and junctions."""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import threading

import pytest

from prompt_enhancer.application.local_agent_limits import LocalAgentError
from prompt_enhancer.application.local_agent_workspace import WorkspaceTools
from prompt_enhancer.application.local_workspace_io import WorkspaceIO
from prompt_enhancer.application.runtime_cancellation import RuntimeCooperativeStop, runtime_request_scope
from tests.test_workspace_read_boundaries import example_junction


@pytest.mark.parametrize("failure", ["write", "sync"])
def test_failed_new_file_is_not_published_partially(tmp_path, monkeypatch, failure):
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example-new.txt", "complete fictional content\n")

    def short_write(descriptor, payload):
        os.write(descriptor, payload[:4])
        raise OSError("EXAMPLE_WRITE_FAILURE_CANARY")

    def failed_sync(_descriptor):
        raise OSError("EXAMPLE_SYNC_FAILURE_CANARY")

    if failure == "write":
        monkeypatch.setattr(tools, "_write_all", short_write)
    else:
        monkeypatch.setattr(os, "fsync", failed_sync)
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok
    assert not (tmp_path / "example-new.txt").exists()
    assert not list(tmp_path.glob(".prompt-enhancer-edit-*"))
    assert "CANARY" not in outcome.text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle cleanup fault seam")
def test_failed_stage_cleanup_is_reported_without_claiming_a_target_write(tmp_path, monkeypatch):
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example-new.txt", "complete fictional content\n")

    monkeypatch.setattr(
        tools,
        "_write_all",
        lambda _descriptor, _payload: (_ for _ in ()).throw(OSError("EXAMPLE_WRITE_FAILURE_CANARY")),
    )
    monkeypatch.setattr(
        tools,
        "_discard_windows_descriptor",
        lambda _descriptor: (_ for _ in ()).throw(OSError("EXAMPLE_CLEANUP_FAILURE_CANARY")),
    )
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok and outcome.code == "workspace_cleanup_failed"
    assert outcome.write_receipt is None and not (tmp_path / "example-new.txt").exists()
    assert len(list(tmp_path.glob(".prompt-enhancer-edit-*.tmp"))) == 1
    assert "CANARY" not in outcome.text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle cleanup fault seam")
def test_failed_backup_cleanup_keeps_the_write_state_unverified(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_bytes(b"original example\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "approved example\n")
    monkeypatch.setattr(
        tools,
        "_discard_windows_descriptor",
        lambda _descriptor: (_ for _ in ()).throw(OSError("EXAMPLE_CLEANUP_FAILURE_CANARY")),
    )
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok and outcome.code == "workspace_verification_failed"
    assert outcome.write_receipt.state == "unverified"
    assert path.read_bytes() == b"approved example\n"
    assert len(list(tmp_path.glob(".prompt-enhancer-backup-*.tmp"))) == 1
    assert "CANARY" not in outcome.text


def test_unchanged_approved_content_is_a_true_noop(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_bytes(b"example\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "example\n")
    before = path.stat()
    outcome = tools.apply_prepared_write(prepared)
    after = path.stat()
    assert outcome.ok and outcome.write_receipt.operation == "unchanged"
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
def test_cancellation_after_staging_never_publishes(tmp_path, monkeypatch, existing):
    path = tmp_path / "example.txt"
    if existing:
        path.write_bytes(b"original example\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "approved example\n")
    cancelled = threading.Event()
    original = tools._write_all

    def cancel_after_write(descriptor, payload):
        original(descriptor, payload)
        cancelled.set()

    monkeypatch.setattr(tools, "_write_all", cancel_after_write)
    with runtime_request_scope(cancelled), pytest.raises(RuntimeCooperativeStop):
        tools.apply_prepared_write(prepared)
    if existing:
        assert path.read_bytes() == b"original example\n"
    else:
        assert not path.exists()
    assert not list(tmp_path.glob(".prompt-enhancer-*.tmp"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows read-only attribute")
def test_readonly_existing_file_is_refused_before_review(tmp_path):
    path = tmp_path / "example.txt"
    path.write_bytes(b"original example\n")
    os.chmod(path, 0o444)
    try:
        tools = WorkspaceTools(tmp_path)
        entries, _ = tools.list_entries(".")
        assert next(item for item in entries if item.name == "example.txt").editable_candidate is False
        with pytest.raises(LocalAgentError, match="workspace_file_unavailable"):
            tools.prepare_write("example.txt", "approved example\n")
        assert path.read_bytes() == b"original example\n"
        assert not list(tmp_path.glob(".prompt-enhancer-*.tmp"))
    finally:
        if path.exists():
            os.chmod(path, 0o666)


def test_late_external_edit_is_not_silently_replaced(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_bytes(b"original example\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "approved example\n")
    attempted = []
    writer = -1

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        create = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x40000000, 0x1 | 0x2 | 0x4, None, 3, 0, None)
        assert handle != ctypes.c_void_p(-1).value
        writer = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT)
        original = tools._replace_windows_file

        def replace(target, replacement, backup):
            nonlocal writer
            if not attempted:
                attempted.append(True)
                payload = b"concurrent example\n"
                os.lseek(writer, 0, os.SEEK_SET)
                os.write(writer, payload)
                os.ftruncate(writer, len(payload))
                os.fsync(writer)
                os.close(writer)
                writer = -1
            return original(target, replacement, backup)

        monkeypatch.setattr(tools, "_replace_windows_file", replace)
    else:
        original = tools._exchange_posix

        def exchange(parent, left, right):
            attempted.append(True)
            path.write_bytes(b"concurrent example\n")
            return original(parent, left, right)

        monkeypatch.setattr(tools, "_exchange_posix", exchange)
    try:
        outcome = tools.apply_prepared_write(prepared)
    finally:
        if writer >= 0:
            os.close(writer)
    assert attempted
    assert not outcome.ok and path.read_bytes() == b"concurrent example\n", (
        outcome.text,
        outcome.code,
        path.read_bytes(),
    )


def test_two_sessions_cannot_both_apply_the_same_reviewed_revision(tmp_path):
    path = tmp_path / "example.txt"
    path.write_bytes(b"original example\n")
    first, second = WorkspaceTools(tmp_path), WorkspaceTools(tmp_path)
    prepared = (
        first.prepare_write("example.txt", "approved first\n"),
        second.prepare_write("example.txt", "approved second\n"),
    )
    barrier = threading.Barrier(3)
    outcomes = []

    def apply(tools, change):
        barrier.wait(timeout=2)
        outcomes.append(tools.apply_prepared_write(change))

    workers = [
        threading.Thread(target=apply, args=(first, prepared[0]), name="example-first-write"),
        threading.Thread(target=apply, args=(second, prepared[1]), name="example-second-write"),
    ]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=2)
    for worker in workers:
        worker.join(timeout=3)
    assert all(not worker.is_alive() for worker in workers)
    assert len(outcomes) == 2 and sum(outcome.ok for outcome in outcomes) == 1
    rejected = next(outcome for outcome in outcomes if not outcome.ok)
    assert rejected.code == "workspace_revision_changed" and rejected.write_receipt is None
    assert path.read_bytes() in {b"approved first\n", b"approved second\n"}


def test_failed_write_start_reobserves_a_changed_reviewed_revision(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "example.txt"
    path.write_bytes(b"original example\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "approved example\n")
    path.write_bytes(b"concurrent example\n")

    method = (
        "_apply_prepared_write_windows"
        if os.name == "nt"
        else "_apply_prepared_write_posix"
    )

    def fail_start(*_args, **_kwargs):
        raise OSError("synthetic publication-start race")

    monkeypatch.setattr(tools, method, fail_start)
    rejected = tools.apply_prepared_write(prepared)

    assert rejected.ok is False
    assert rejected.code == "workspace_revision_changed"
    assert rejected.write_receipt is None
    assert path.read_bytes() == b"concurrent example\n"
    assert not list(tmp_path.glob(".prompt-enhancer-*.tmp"))


def test_hard_link_added_during_approval_blocks_publication(tmp_path):
    path = tmp_path / "example.txt"
    path.write_bytes(b"original example\n")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "approved example\n")
    linked = tmp_path / "example-linked.txt"
    try:
        os.link(path, linked)
    except OSError as error:
        pytest.skip(f"hard-link fixture unavailable: {error.__class__.__name__}")
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok and outcome.write_receipt is None
    assert path.read_bytes() == linked.read_bytes() == b"original example\n"
    assert not list(tmp_path.glob(".prompt-enhancer-*.tmp"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction mutation acceptance")
def test_folder_swap_cannot_redirect_existing_file_replacement(tmp_path, monkeypatch):
    root = tmp_path / "example-project"
    folder, outside = root / "example-src", tmp_path / "example-outside"
    folder.mkdir(parents=True)
    outside.mkdir()
    path = folder / "example.txt"
    path.write_bytes(b"original example\n")
    outside_file = outside / "example.txt"
    outside_file.write_bytes(b"EXAMPLE_OUTSIDE_ORIGINAL\n")
    tools = WorkspaceTools(root)
    prepared = tools.prepare_write("example-src/example.txt", "approved example\n")
    original = tools._replace_windows_file
    attempted = []
    blocked = []
    with ExitStack() as stack:
        def replace(target, replacement, backup):
            if Path(target) == path and not attempted:
                attempted.append(True)
                try:
                    folder.rename(root / "example-original")
                except OSError:
                    blocked.append(True)
                else:
                    stack.enter_context(example_junction(folder, outside, tmp_path))
                    (outside / Path(replacement).name).write_bytes(b"EXAMPLE_UNREVIEWED_STAGE\n")
            return original(target, replacement, backup)

        monkeypatch.setattr(tools, "_replace_windows_file", replace)
        outcome = tools.apply_prepared_write(prepared)
        assert attempted and blocked and outcome.ok
        assert path.read_bytes() == b"approved example\n"
        assert outside_file.read_bytes() == b"EXAMPLE_OUTSIDE_ORIGINAL\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction cleanup acceptance")
def test_temporary_cleanup_cannot_unlink_another_file_after_a_folder_swap(tmp_path, monkeypatch):
    root = tmp_path / "example-project"
    folder, outside = root / "example-src", tmp_path / "example-outside"
    folder.mkdir(parents=True)
    outside.mkdir()
    (folder / "example.txt").write_bytes(b"original example\n")
    tools = WorkspaceTools(root)
    prepared = tools.prepare_write("example-src/example.txt", "approved example\n")
    original = tools._discard_windows_descriptor
    outside_candidate = outside / ".prompt-enhancer-edit-unrelated.tmp"
    outside_candidate.write_bytes(b"EXAMPLE_OUTSIDE_ORIGINAL\n")
    attempted = []
    blocked = []
    with ExitStack() as stack:
        def failed_write(_descriptor, _payload):
            raise OSError("EXAMPLE_WRITE_FAILURE_CANARY")

        def discard(descriptor):
            if not attempted:
                attempted.append(True)
                try:
                    folder.rename(root / "example-original")
                except OSError:
                    blocked.append(True)
                else:
                    stack.enter_context(example_junction(folder, outside, tmp_path))
            return original(descriptor)

        monkeypatch.setattr(tools, "_write_all", failed_write)
        monkeypatch.setattr(tools, "_discard_windows_descriptor", discard)
        outcome = tools.apply_prepared_write(prepared)
        assert not outcome.ok and attempted and blocked
        assert outside_candidate.read_bytes() == b"EXAMPLE_OUTSIDE_ORIGINAL\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows atomic replacement")
def test_windows_atomic_replacement_keeps_the_parent_pinned(tmp_path):
    from prompt_enhancer.application.local_workspace_windows import (
        create_staged_descriptor,
        discard_descriptor,
        open_reviewed_target_descriptor,
        replace_file_with_backup,
    )

    original = tmp_path / "example.txt"
    stage = tmp_path / "example-stage.txt"
    backup = tmp_path / "example-backup.txt"
    original.write_bytes(b"original example\n")
    with WorkspaceIO(tmp_path)._directory(tmp_path, lambda: None, mutation=True):
        target_descriptor = open_reviewed_target_descriptor(original)
        stage_descriptor = create_staged_descriptor(stage)
        try:
            os.write(stage_descriptor, b"staged example\n")
            os.fsync(stage_descriptor)
            os.close(stage_descriptor)
            stage_descriptor = -1
            replace_file_with_backup(original, stage, backup)
            assert os.fstat(target_descriptor).st_ino == backup.stat().st_ino
            discard_descriptor(target_descriptor)
        finally:
            if stage_descriptor >= 0:
                os.close(stage_descriptor)
            os.close(target_descriptor)
    assert original.read_bytes() == b"staged example\n"
    assert not stage.exists() and not backup.exists()
