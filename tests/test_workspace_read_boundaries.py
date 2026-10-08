"""Workspace inspection uses only disposable fictional files and junctions."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from prompt_enhancer.application.local_agent_limits import MAX_FILE_READ_BYTES, MAX_SEARCH_RESULTS
from prompt_enhancer.application.local_agent_limits import LocalAgentError, MAX_TOOL_RESULT_CHARS
from prompt_enhancer.application.local_agent_workspace import WorkspaceTools
from prompt_enhancer.application.local_command_process import run_with_tree_kill
from prompt_enhancer.application.runtime_cancellation import RuntimeCooperativeStop, runtime_request_scope


@contextmanager
def example_junction(link: Path, target: Path, temporary_root: Path):
    """Create/remove only this link; never recursively delete its target."""
    if sys.platform != "win32":
        pytest.skip("Windows junction acceptance")
    base = temporary_root.resolve(strict=True)
    assert link.parent.resolve(strict=True).is_relative_to(base)
    assert target.resolve(strict=True).is_relative_to(base)
    assert not link.exists()
    command = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    if command.returncode != 0:
        pytest.skip("Synthetic junction creation unavailable")
    try:
        assert link.lstat().st_file_attributes & 0x400
        yield
    finally:
        assert link.parent.resolve(strict=True).is_relative_to(base)
        assert link.resolve(strict=True) == target.resolve(strict=True)
        assert link.lstat().st_file_attributes & 0x400
        link.rmdir()
        assert target.is_dir()


def test_directory_read_failure_is_not_reported_as_an_empty_folder(tmp_path, monkeypatch):
    tools = WorkspaceTools(tmp_path)
    original = os.scandir

    def denied(path):
        if path == tmp_path or (isinstance(path, int) and os.fstat(path).st_ino == tmp_path.stat().st_ino):
            raise PermissionError("EXAMPLE_PRIVATE_DIRECTORY_CANARY")
        return original(path)

    monkeypatch.setattr(os, "scandir", denied)
    result = tools.list_dir()
    assert not result.ok
    assert "empty folder" not in result.text
    assert "EXAMPLE_PRIVATE_DIRECTORY_CANARY" not in result.text


def test_nested_directory_failure_keeps_partial_listing_but_not_success(tmp_path, monkeypatch):
    folder = tmp_path / "example-blocked"
    folder.mkdir()
    (tmp_path / "example.txt").write_text("example", encoding="utf-8")
    original = os.scandir

    def denied(path):
        if path == folder or (isinstance(path, int) and os.fstat(path).st_ino == folder.stat().st_ino):
            raise PermissionError("EXAMPLE_PRIVATE_DIRECTORY_CANARY")
        return original(path)

    tools = WorkspaceTools(tmp_path)
    monkeypatch.setattr(os, "scandir", denied)
    result = tools.list_dir(depth=2)
    assert not result.ok
    assert "example.txt" in result.text
    assert "incomplete" in result.text.casefold()
    assert "EXAMPLE_PRIVATE_DIRECTORY_CANARY" not in result.text


def test_file_prefix_is_not_implemented_by_loading_the_whole_file(tmp_path, monkeypatch):
    (tmp_path / "example.txt").write_bytes(b"x" * (MAX_FILE_READ_BYTES + 1))
    tools = WorkspaceTools(tmp_path)

    def unbounded(_path):
        raise AssertionError("Unbounded whole-file read attempted")

    monkeypatch.setattr(Path, "read_bytes", unbounded)
    result = tools.read_file("example.txt")
    assert result.ok and "truncated" in result.text


def test_binary_marker_later_in_the_read_prefix_is_not_exposed(tmp_path):
    (tmp_path / "example.bin").write_bytes(b"x" * 5000 + b"\0EXAMPLE_BINARY_CANARY")
    result = WorkspaceTools(tmp_path).read_file("example.bin")
    assert not result.ok and "EXAMPLE_BINARY_CANARY" not in result.text


@pytest.mark.parametrize("name", [".GIT", "NODE_MODULES", "Build"])
def test_noisy_directory_policy_is_case_consistent_for_search_and_tree(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "example.txt").write_text("EXAMPLE_SKIPPED_CANARY", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    assert "EXAMPLE_SKIPPED_CANARY" not in tools.search_text("EXAMPLE_SKIPPED_CANARY").text
    entries, _ = tools.list_entries()
    assert entries[0].kind == "unavailable"


def test_search_match_limit_never_looks_like_complete_results(tmp_path):
    (tmp_path / "example.txt").write_text("example\n" * (MAX_SEARCH_RESULTS + 1), encoding="utf-8")
    result = WorkspaceTools(tmp_path).search_text("example")
    assert "incomplete" in result.text.casefold() or "truncated" in result.text.casefold()


@pytest.mark.parametrize("operation", ["read", "list", "search"])
def test_cancelled_inspection_does_not_read_more_workspace_data(tmp_path, operation):
    (tmp_path / "example.txt").write_text("example", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    stopped = Event()
    stopped.set()
    with runtime_request_scope(stopped), pytest.raises(RuntimeCooperativeStop):
        {"read": lambda: tools.read_file("example.txt"), "list": tools.list_dir,
         "search": lambda: tools.search_text("example")}[operation]()


def test_listing_cannot_enter_an_outside_junction(tmp_path):
    root, outside = tmp_path / "example-project", tmp_path / "example-outside"
    root.mkdir()
    outside.mkdir()
    (outside / "EXAMPLE_OUTSIDE_CANARY.txt").write_text("example", encoding="utf-8")
    tools = WorkspaceTools(root)
    with example_junction(root / "example-link", outside, tmp_path):
        result = tools.list_dir(depth=2)
        assert "EXAMPLE_OUTSIDE_CANARY" not in result.text
        assert "not followed" in result.text


@pytest.mark.parametrize("operation", ["read", "search", "list"])
def test_in_root_junction_is_not_an_alternate_read_path(tmp_path, operation):
    root = tmp_path / "example-project"
    folder = root / "example-real"
    folder.mkdir(parents=True)
    (folder / "example.txt").write_text("EXAMPLE_LINK_CANARY", encoding="utf-8")
    tools = WorkspaceTools(root)
    with example_junction(root / "example-link", folder, tmp_path):
        result = {"read": lambda: tools.read_file("example-link/example.txt"),
            "search": lambda: tools.search_text("EXAMPLE_LINK_CANARY", glob="example-link/*.txt"),
            "list": lambda: tools.list_dir("example-link", depth=2)}[operation]()
        assert not result.ok or "incomplete" in result.text.casefold()
        assert "EXAMPLE_LINK_CANARY" not in result.text


def test_pathological_regex_has_a_deadline_not_an_unstoppable_agent_thread(tmp_path):
    (tmp_path / "example.txt").write_text("a" * 50000 + "!", encoding="utf-8")
    # The old failure is contained in an owned finite process, never in pytest.
    program = (
        "import sys; sys.path.insert(0, 'src'); from pathlib import Path; "
        "from prompt_enhancer.application.local_agent_workspace import WorkspaceTools; "
        "result = WorkspaceTools(Path(sys.argv[1])).search_text('(a+)+$', regex=True); "
        "print(result.code)"
    )
    result = run_with_tree_kill([sys.executable, "-I", "-c", program, str(tmp_path)],
        cwd=str(Path(__file__).resolve().parents[1]), timeout=3, encoding="utf-8")
    assert result.returncode == 0
    assert "workspace_search_timeout" in result.stdout


@pytest.mark.parametrize("operation", ["read", "list", "search", "tree", "editor"])
def test_replaced_workspace_root_does_not_become_an_admitted_workspace(tmp_path, operation):
    root = tmp_path / "example-project"
    root.mkdir()
    (root / "example.txt").write_text("original example", encoding="utf-8")
    tools = WorkspaceTools(root)
    root.rename(tmp_path / "example-original")
    root.mkdir()
    (root / "example.txt").write_text("EXAMPLE_REPLACEMENT_CANARY", encoding="utf-8")
    if operation in {"tree", "editor"}:
        with pytest.raises(LocalAgentError, match="^workspace_root_changed$"):
            tools.list_entries() if operation == "tree" else tools.read_text_snapshot("example.txt")
    else:
        if operation == "search":
            with pytest.raises(LocalAgentError, match="^workspace_root_changed$"):
                tools.search_text_snapshot("EXAMPLE_REPLACEMENT_CANARY")
        result = {"read": lambda: tools.read_file("example.txt"), "list": tools.list_dir,
                  "search": lambda: tools.search_text("EXAMPLE_REPLACEMENT_CANARY")}[operation]()
        assert not result.ok and "EXAMPLE_REPLACEMENT_CANARY" not in result.text
        assert "workspace root changed" in result.text


def test_read_byte_and_output_bounds_are_enforced_before_returning(tmp_path, monkeypatch):
    (tmp_path / "example.txt").write_bytes(b"x" * (MAX_FILE_READ_BYTES * 3))
    tools = WorkspaceTools(tmp_path)
    original = os.read
    requests, returned = [], []

    def read(descriptor, size):
        requests.append(size)
        data = original(descriptor, size)
        returned.append(len(data))
        return data

    monkeypatch.setattr(os, "read", read)
    result = tools.read_file("example.txt")
    assert result.ok and "truncated" in result.text
    assert max(requests) <= 65536
    assert sum(returned) == MAX_FILE_READ_BYTES + 1
    assert len(result.text) <= MAX_TOOL_RESULT_CHARS


def test_cancel_during_read_releases_handles_and_suppresses_partial_content(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_bytes(b"x" * 70000)
    tools = WorkspaceTools(tmp_path)
    original = os.read
    stopped = Event()
    reads = []

    def read(descriptor, size):
        reads.append(True)
        data = original(descriptor, size)
        stopped.set()
        return data

    monkeypatch.setattr(os, "read", read)
    with runtime_request_scope(stopped), pytest.raises(RuntimeCooperativeStop):
        tools.read_file("example.txt")
    assert len(reads) == 1
    path.rename(tmp_path / "example-after-cancel.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows component-pinning acceptance")
def test_native_read_pins_ancestors_and_file_until_the_read_finishes(tmp_path, monkeypatch):
    root = tmp_path / "example-project"
    root.mkdir()
    path = root / "example.txt"
    path.write_text("original example", encoding="utf-8")
    tools = WorkspaceTools(root)
    original = os.read
    checked = []

    def read(descriptor, size):
        assert not os.get_inheritable(descriptor)
        with pytest.raises(PermissionError):
            root.rename(tmp_path / "example-moved")
        with pytest.raises(PermissionError):
            path.write_text("EXAMPLE_REPLACEMENT_CANARY", encoding="utf-8")
        checked.append(True)
        return original(descriptor, size)

    monkeypatch.setattr(os, "read", read)
    assert tools.read_file("example.txt").text == "original example"
    assert checked
    # No file or ancestor handles are retained after the operation.
    root.rename(tmp_path / "example-moved")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows final-open race acceptance")
def test_windows_blocks_file_replacement_between_metadata_and_open(tmp_path, monkeypatch):
    from prompt_enhancer.application import local_workspace_windows as native

    path = tmp_path / "example.txt"
    path.write_text("original example", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    original = native.open_read_descriptor
    swapped = []

    def open_read(path_to_open, *, directory):
        if not directory and not swapped:
            swapped.append(True)
            with pytest.raises(PermissionError):
                path.rename(tmp_path / "example-original.txt")
        return original(path_to_open, directory=directory)

    monkeypatch.setattr(native, "open_read_descriptor", open_read)
    result = tools.read_file("example.txt")
    assert result.ok and result.text == "original example"
    assert swapped == [True]
    path.rename(tmp_path / "example-released.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle-identity acceptance")
def test_opened_handle_identity_must_match_the_checked_file_before_reading(tmp_path, monkeypatch):
    from prompt_enhancer.application import local_workspace_windows as native

    (tmp_path / "example.txt").write_text("original example", encoding="utf-8")
    other = tmp_path / "example-other.txt"
    other.write_text("EXAMPLE_REPLACEMENT_CANARY", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    original = native.open_read_descriptor

    def mismatched(path, *, directory):
        return original(path if directory else other, directory=directory)

    monkeypatch.setattr(native, "open_read_descriptor", mismatched)
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("Read from a mismatched handle"))
    result = tools.read_file("example.txt")
    assert not result.ok and result.code == "workspace_file_changed"
    assert "EXAMPLE_REPLACEMENT_CANARY" not in result.text
    other.rename(tmp_path / "example-released.txt")


@pytest.mark.parametrize("operation", ["list", "search", "tree"])
def test_directory_enumeration_uses_a_bounded_iterator_not_listdir(tmp_path, monkeypatch, operation):
    from prompt_enhancer.application import local_agent_workspace as workspace

    for number in range(12):
        (tmp_path / f"example-{number}.txt").write_text("example", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    original = os.scandir
    observed = []

    @contextmanager
    def scan(path):
        with original(path) as entries:
            def bounded():
                for entry in entries:
                    observed.append(True)
                    yield entry
            yield bounded()

    monkeypatch.setattr(os, "scandir", scan)
    monkeypatch.setattr(os, "listdir", lambda *_: pytest.fail("unbounded listdir used"))
    monkeypatch.setattr(workspace, "MAX_TREE_SCAN_ENTRIES", 5)
    if operation == "tree":
        entries, complete = tools.list_entries()
        assert len(entries) == 5 and not complete
    else:
        result = tools.list_dir() if operation == "list" else tools.search_text("example")
        assert not result.ok and "incomplete" in result.text
    assert len(observed) == 6


def test_failed_file_reads_still_consume_the_search_budget(tmp_path, monkeypatch):
    from prompt_enhancer.application import local_agent_workspace as workspace

    for name in ("example-a.txt", "example-b.txt", "example-c.txt"):
        (tmp_path / name).write_text("example", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    attempts = []

    def changed(_path, *, limit, check, consume):
        check()
        attempts.append(limit)
        consume(limit)
        raise LocalAgentError("workspace_file_changed")

    monkeypatch.setattr(tools._inspection, "read", changed)
    monkeypatch.setattr(workspace, "MAX_SEARCH_TOTAL_BYTES", 10)
    result = tools.search_text("example")
    assert attempts == [10]
    assert not result.ok and "total read budget" in result.text


@pytest.mark.parametrize("operation", ["list", "search", "tree"])
def test_inspection_deadline_is_not_reported_as_empty(tmp_path, monkeypatch, operation):
    from prompt_enhancer.application import local_agent_workspace as workspace

    tools = WorkspaceTools(tmp_path)
    monkeypatch.setattr(workspace, "MAX_WORKSPACE_SCAN_SECONDS", 0)
    if operation == "tree":
        with pytest.raises(LocalAgentError, match="^workspace_inspection_timeout$"):
            tools.list_entries()
    else:
        result = tools.list_dir() if operation == "list" else tools.search_text("example")
        assert not result.ok and "deadline" in result.text and "empty" not in result.text


@pytest.mark.parametrize("pattern, expected", [
    ("*.txt", {"example.txt"}),
    ("**/*.txt", {"example.txt", "src/example.txt", "src/nested/example.txt"}),
    ("src/*.txt", {"src/example.txt"}),
    ("src/**/*.txt", {"src/example.txt", "src/nested/example.txt"}),
    ("**/nested/example.*", {"src/nested/example.txt"}),
    ("src/?xample.[tT][xX][tT]", {"src/example.txt"}),
])
def test_globs_are_root_anchored_and_double_star_means_recursion(tmp_path, pattern, expected):
    for relative in ("example.txt", "src/example.txt", "src/nested/example.txt", "src/example.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("example", encoding="utf-8")
    result = WorkspaceTools(tmp_path).search_text("example", glob=pattern)
    assert result.ok
    assert {line.split(":", 1)[0] for line in result.text.splitlines()} == expected


@pytest.mark.parametrize("pattern", ["../*", "**/../*", "C:example/*", "/example/*", "file:stream", "x**y", "./", "x" * 1025])
def test_invalid_globs_do_not_enumerate_any_directory(tmp_path, pattern, monkeypatch):
    tools = WorkspaceTools(tmp_path)
    monkeypatch.setattr(tools._inspection, "entries", lambda *_args, **_kwargs: pytest.fail("Invalid glob reached filesystem"))
    result = tools.search_text("example", glob=pattern)
    assert not result.ok and result.code == "workspace_glob_invalid"


@pytest.mark.parametrize("query, regex, ok", [("x" * 1025, False, False), ("[", True, False), ("example\\d+", True, True), ("example[", False, True)])
def test_search_query_validation_and_literal_regex_modes(tmp_path, query, regex, ok):
    (tmp_path / "example.txt").write_text("example42\nexample[\n", encoding="utf-8")
    result = WorkspaceTools(tmp_path).search_text(query, regex=regex)
    assert result.ok is ok
    if ok:
        assert result.text.startswith("example.txt:")


def test_invalid_utf8_is_not_presented_as_verified_text(tmp_path):
    (tmp_path / "example.bin").write_bytes(b"\xffEXAMPLE_BINARY_CANARY")
    result = WorkspaceTools(tmp_path).read_file("example.bin")
    assert not result.ok and "EXAMPLE_BINARY_CANARY" not in result.text


def test_truncated_multibyte_prefix_does_not_invent_replacement_characters(tmp_path, monkeypatch):
    from prompt_enhancer.application import local_agent_workspace as workspace

    (tmp_path / "example.txt").write_bytes(b"x" * 7 + "é".encode("utf-8"))
    monkeypatch.setattr(workspace, "MAX_FILE_READ_BYTES", 8)
    result = WorkspaceTools(tmp_path).read_file("example.txt")
    assert result.ok and "truncated" in result.text and "\ufffd" not in result.text


def test_output_that_fits_is_not_falsely_marked_truncated():
    from prompt_enhancer.application.local_agent_workspace import _inspection_result

    result = _inspection_result(["x" * (MAX_TOOL_RESULT_CHARS - 100)], set(), empty="empty")
    assert result.ok and "truncated" not in result.text
    truncated = _inspection_result(["x" * (MAX_TOOL_RESULT_CHARS + 1)], set(), empty="empty")
    assert not truncated.ok and "truncated" in truncated.text and len(truncated.text) <= MAX_TOOL_RESULT_CHARS


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native-handle release acceptance")
@pytest.mark.parametrize("failure", ["metadata", "conversion", "wrong_type"])
def test_native_read_setup_failure_releases_the_created_handle(tmp_path, monkeypatch, failure):
    from prompt_enhancer.application import local_workspace_windows as native

    path = tmp_path / "example.txt"
    path.write_text("example", encoding="utf-8")
    original_close = native._close
    closed = []

    def close(handle):
        closed.append(True)
        return original_close(handle)

    def failed_conversion(*_args):
        raise OSError("EXAMPLE_NATIVE_CONVERSION_CANARY")

    monkeypatch.setattr(native, "_close", close)
    if failure == "metadata":
        monkeypatch.setattr(native, "_information", lambda *_: False)
    elif failure == "conversion":
        monkeypatch.setattr(native.msvcrt, "open_osfhandle", failed_conversion)
    with pytest.raises((OSError, LocalAgentError)):
        native.open_read_descriptor(path, directory=failure == "wrong_type")
    assert closed == [True]
    path.rename(tmp_path / "example-released.txt")
