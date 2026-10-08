"""Workspace-scoped file, command, and fetch tools for ADR 0016.

This module is deliberately independent of session and streaming state.  The
agent service supplies one instance per selected workspace and keeps approval
authority in the orchestration layer.
"""

from __future__ import annotations

from collections.abc import Callable
import codecs
import ctypes
from dataclasses import dataclass
import difflib
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import regex as bounded_regex
import secrets
import stat
import subprocess
import threading
import time
from typing import Any, Literal
import unicodedata

from .local_agent_limits import (
    DEFAULT_COMMAND_SECONDS,
    LocalAgentError,
    MAX_COMMAND_SECONDS,
    MAX_DISCOVERY_FILES,
    MAX_DIFF_CHARS,
    MAX_FILE_READ_BYTES,
    MAX_FILE_WRITE_BYTES,
    MAX_GIT_STATUS_ENTRIES,
    MAX_LIST_ENTRIES,
    MAX_REVIEWABLE_COMMAND_CHARS,
    MAX_REGEX_MATCH_SECONDS,
    MAX_SEARCH_DEPTH,
    MAX_SEARCH_FILE_BYTES,
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_SEARCH_TOTAL_BYTES,
    MAX_TOOL_RESULT_CHARS,
    MAX_TREE_SCAN_ENTRIES,
    MAX_WORKSPACE_TRANSACTION_FILES,
    MAX_WORKSPACE_SCAN_SECONDS,
    SKIP_DIRS,
)
from .local_agent_receipts import (
    AgentMcpToolDescriptor,
    AgentMcpToolResultReceipt,
    AgentToolApprovalState,
    AgentWriteReceipt,
)
from .local_command_process import minimal_environment, run_with_tree_kill
from .local_workspace_glob import WorkspaceGlob
from .local_workspace_io import InspectedEntry, WorkspaceIO, check_workspace_cancellation, is_link_or_reparse
from .runtime_cancellation import (
    RuntimeCleanupUnconfirmed,
    RuntimeCooperativeStop,
    current_runtime_cancellation,
    runtime_critical_cleanup_scope,
)


@dataclass(slots=True)
class ToolOutcome:
    ok: bool
    text: str
    code: str | None = None
    write_receipt: AgentWriteReceipt | None = None
    untracked_command: bool = False
    # Transient filesystem identity captured inside the reviewed write lane.
    # It is used only to bind transaction verification/rollback and is never
    # projected into Agent events, receipts, logs, or durable history.
    publication_identity: tuple[int, int] | None = None
    # Orchestration replaces this default after it observes the exact approval
    # lane. Workspace tools never infer user authority themselves.
    approval_state: AgentToolApprovalState = "not_requested"
    mcp_tool: AgentMcpToolDescriptor | None = None
    mcp_result: AgentMcpToolResultReceipt | None = None


@dataclass(frozen=True, slots=True)
class PreparedWrite:
    """A reviewable write bound to the exact file and parent seen in preview."""

    path: str
    content: str
    preview: str
    base_sha256: str | None
    base_identity: tuple[int, int] | None
    parent_identity: tuple[int, int]
    proposed_sha256: str
    existed: bool
    mode: int | None
    # Transient first-party input for the session change tracker. It is never
    # persisted or placed in an approval capability/receipt.
    base_content: str | None
    base_byte_size: int | None


@dataclass(frozen=True, slots=True)
class PreparedMove:
    """A no-overwrite file move bound to the exact reviewed source and parents."""

    source_path: str
    target_path: str
    source_sha256: str
    source_identity: tuple[int, int]
    source_parent_identity: tuple[int, int]
    target_parent_identity: tuple[int, int]
    byte_size: int
    mode: int


@dataclass(frozen=True, slots=True)
class PreparedMoveOutcome:
    """Content-free outcome for a reviewed move publication."""

    state: Literal["verified", "rejected", "unverified"]
    code: str | None
    revision: str | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class PreparedFileTrash:
    """A recoverable file removal bound to the exact reviewed source."""

    path: str
    source_sha256: str
    source_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    byte_size: int
    mode: int
    recovery: Literal["windows_recycle_bin"] = "windows_recycle_bin"
    permanent: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PreparedFileTrashOutcome:
    """Content-free outcome for one reviewed move into the system trash."""

    state: Literal["verified", "rejected", "unverified"]
    code: str | None
    revision: str | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class PreparedDirectoryCreate:
    """A no-overwrite directory creation bound to one reviewed parent."""

    path: str
    parent_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class PreparedDirectoryCreateOutcome:
    """Content-free outcome for reviewed directory publication."""

    state: Literal["verified", "rejected", "unverified"]
    code: str | None


@dataclass(frozen=True, slots=True)
class PreparedDirectoryMove:
    """A no-overwrite directory move bound to the exact entry and parents."""

    source_path: str
    target_path: str
    source_identity: tuple[int, int]
    source_parent_identity: tuple[int, int]
    target_parent_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class PreparedDirectoryMoveOutcome:
    """Content-free outcome for a reviewed directory path publication."""

    state: Literal["verified", "rejected", "unverified"]
    code: str | None


@dataclass(frozen=True, slots=True)
class PreparedTransactionFileResult:
    """Content-free final state for one member of a reviewed transaction."""

    path: str
    state: Literal[
        "committed",
        "restored",
        "removed",
        "not_applied",
        "unverified",
    ]
    revision: str | None = None
    byte_size: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedTransactionOutcome:
    """Failure-atomic application result; unverified never claims rollback."""

    state: Literal["committed", "rejected", "rolled_back", "unverified"]
    reason: str | None
    files: tuple[PreparedTransactionFileResult, ...]


@dataclass(frozen=True, slots=True)
class _PublicationResult:
    state: Literal["published", "unchanged", "rejected", "unverified"]
    text: str
    code: str | None = None


class _WriteCleanupUnconfirmed(Exception):
    def __init__(self, *, publication_attempted: bool) -> None:
        super().__init__("workspace_cleanup_unconfirmed")
        self.publication_attempted = publication_attempted


_REVIEWED_WRITE_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class WorkspacePathEntry:
    path: str
    name: str
    kind: Literal["directory", "file", "unavailable"]
    byte_size: int | None
    editable_candidate: bool


@dataclass(frozen=True, slots=True)
class WorkspaceTextSnapshot:
    path: str
    content: str
    revision: str
    byte_size: int
    line_ending: Literal["lf", "crlf", "none"]


@dataclass(frozen=True, slots=True)
class WorkspaceTextSearchMatch:
    """One bounded, display-safe line match inside the admitted workspace."""

    path: str
    line_number: int
    preview: str


@dataclass(frozen=True, slots=True)
class WorkspaceTextSearchSnapshot:
    """Structured search evidence shared by the local model, UI, and MCP."""

    coverage: Literal["complete", "partial"]
    reasons: tuple[str, ...]
    reason_code: str | None
    scanned_entry_count: int
    inspected_byte_count: int
    skipped_entry_count: int
    matches: tuple[WorkspaceTextSearchMatch, ...]


def _safe_search_preview(value: str) -> str:
    """Keep search excerpts single-line and inert in browsers and terminals."""

    return "".join(
        "\ufffd" if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
        for character in value
    ).strip()[:240]


@dataclass(frozen=True, slots=True)
class WorkspaceDiscoveredFile:
    path: str
    byte_size: int
    editable_candidate: bool


@dataclass(frozen=True, slots=True)
class WorkspaceInventorySnapshot:
    coverage: Literal["complete", "partial"]
    reasons: tuple[str, ...]
    scanned_entry_count: int
    observed_file_count: int
    files: tuple[WorkspaceDiscoveredFile, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceGitChangeRecord:
    path: str
    kind: Literal[
        "modified", "added", "deleted", "renamed", "copied",
        "type_changed", "untracked", "conflicted", "unknown",
    ]
    staged: bool
    unstaged: bool


@dataclass(frozen=True, slots=True)
class WorkspaceGitStatusSnapshot:
    state: Literal["available", "not_repository", "unavailable"]
    coverage: Literal["complete", "partial", "not_applicable", "unavailable"]
    reasons: tuple[str, ...]
    change_count: int | None
    changes: tuple[WorkspaceGitChangeRecord, ...]


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    return is_link_or_reparse(metadata)


def _path_components_are_safe(value: Path) -> bool:
    """Fail closed when any existing component is a link/reparse or unreadable."""

    for candidate in (value, *value.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if _is_link_or_reparse(metadata):
            return False
    return True


_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_SKIPPED_COMPONENTS = frozenset(component.casefold() for component in SKIP_DIRS)


def _relative_components_are_portable(value: PureWindowsPath) -> bool:
    """Reject Windows device/ADS spellings before any filesystem access."""

    if value.drive or value.root:
        return False
    for component in value.parts:
        if ":" in component or any(ord(character) < 32 for character in component):
            return False
        if platform.system() == "Windows" and (
            component.rstrip(" .") != component
            or any(character in component for character in '<>"|?*')
            or component.split(".", 1)[0].upper() in _WINDOWS_RESERVED_COMPONENTS
        ):
            return False
    return True


class WorkspaceTools:
    """Tool implementations scoped to one folder. No path may escape the root."""

    def __init__(
        self,
        root: Path,
        *,
        command_timeout: int = DEFAULT_COMMAND_SECONDS,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        lexical_root = Path(os.path.abspath(os.fspath(root.expanduser())))
        if not lexical_root.is_dir() or not _path_components_are_safe(lexical_root):
            raise LocalAgentError("workspace_link_or_reparse_refused")
        # Admission must not resolve a junction swapped in after the precheck.
        # WorkspaceIO opens the lexical components without following them.
        self.root = lexical_root
        self._inspection = WorkspaceIO(self.root)
        self._command_timeout = command_timeout
        self._runner = runner or run_with_tree_kill
        self._fetcher = fetcher
        self._write_lock = threading.RLock()
        self._command_lock = threading.Lock()
        self._command_cleanup_unconfirmed = threading.Event()

    @property
    def command_cleanup_unconfirmed(self) -> bool:
        return self._command_cleanup_unconfirmed.is_set()

    def _lexical_candidate(self, relative: str) -> Path:
        if (
            not relative
            or len(relative) > 1024
            or any(
                ord(char) < 32
                or ord(char) == 127
                or 0xD800 <= ord(char) <= 0xDFFF
                for char in relative
            )
        ):
            raise LocalAgentError("path_invalid")
        posix = PurePosixPath(relative)
        windows = PureWindowsPath(relative)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or ".." in posix.parts
            or ".." in windows.parts
        ):
            raise LocalAgentError("path_outside_workspace")
        if any(
            component.casefold() in _SKIPPED_COMPONENTS
            for component in (*posix.parts, *windows.parts)
        ):
            raise LocalAgentError("workspace_path_not_found")
        if not _relative_components_are_portable(windows):
            raise LocalAgentError("path_invalid")
        if platform.system() != "Windows" and "\\" in relative:
            raise LocalAgentError("path_invalid")
        candidate = Path(os.path.abspath(os.fspath(self.root / Path(relative))))
        if candidate != self.root and self.root not in candidate.parents:
            raise LocalAgentError("path_outside_workspace")
        return candidate

    def resolve(self, relative: str) -> Path:
        if relative in {"", "."}:
            candidate = self.root
        else:
            candidate = self._lexical_candidate(relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise LocalAgentError("path_outside_workspace")
        return candidate

    def read_file(self, path: str) -> ToolOutcome:
        check_workspace_cancellation()
        try:
            inspected = self._inspection.read(self._lexical_candidate(path), limit=MAX_FILE_READ_BYTES, allow_prefix=True)
        except (OSError, LocalAgentError) as error:
            return _inspection_error(error)
        if b"\x00" in inspected.payload:
            return ToolOutcome(False, "binary file, not shown", "workspace_binary_refused")
        try:
            # A bounded prefix may end within a valid UTF-8 code point. Do not
            # invent replacement characters or accept malformed bytes as text.
            text = codecs.getincrementaldecoder("utf-8")(errors="strict").decode(
                inspected.payload, final=not inspected.truncated)
        except UnicodeDecodeError:
            return ToolOutcome(False, "non-UTF-8 file, not shown", "workspace_binary_refused")
        if inspected.truncated or len(text) > MAX_TOOL_RESULT_CHARS:
            notice = f"[File prefix truncated; {inspected.metadata.st_size} bytes in the inspected file]\n"
            text = notice + text[:MAX_TOOL_RESULT_CHARS - len(notice)]
        return ToolOutcome(True, text)

    def list_entries(
        self, path: str = "."
    ) -> tuple[tuple[WorkspacePathEntry, ...], bool]:
        check_workspace_cancellation()
        target = self.root if path in {"", "."} else self._lexical_candidate(path)
        deadline = time.monotonic() + MAX_WORKSPACE_SCAN_SECONDS
        try:
            candidates, scan_complete = self._inspection.entries(target, limit=MAX_TREE_SCAN_ENTRIES,
                check=lambda: _check_inspection(deadline, "workspace_inspection_timeout"))
        except FileNotFoundError as error:
            raise LocalAgentError("workspace_path_not_found") from error
        except OSError as error:
            raise LocalAgentError("workspace_directory_unavailable") from error
        entries: list[WorkspacePathEntry] = []
        for inspected in candidates:
            check_workspace_cancellation()
            candidate, item = inspected.path, inspected.metadata
            kind = self._entry_kind(inspected)
            if kind == "unrepresentable":
                scan_complete = False
                continue
            entries.append(
                WorkspacePathEntry(
                    path=candidate.relative_to(self.root).as_posix(),
                    name=candidate.name,
                    kind=kind if kind in {"file", "directory"} else "unavailable",
                    byte_size=item.st_size if item is not None and kind == "file" else None,
                    editable_candidate=bool(
                        item is not None
                        and kind == "file"
                        and item.st_nlink == 1
                        and item.st_size <= MAX_FILE_WRITE_BYTES
                        and not (os.name == "nt" and not item.st_mode & stat.S_IWRITE)
                    ),
                )
            )
        order = {"directory": 0, "file": 1, "unavailable": 2}
        entries.sort(key=lambda entry: (order[entry.kind], entry.name.casefold(), entry.name))
        complete = scan_complete and len(entries) <= MAX_LIST_ENTRIES
        return tuple(entries[:MAX_LIST_ENTRIES]), complete

    def discovery_inventory(self) -> WorkspaceInventorySnapshot:
        """Recursively inventory safe relative files without reading content."""

        check_workspace_cancellation()
        files: list[WorkspaceDiscoveredFile] = []
        reasons: set[str] = set()
        scanned = 0
        observed_files = 0
        deadline = time.monotonic() + MAX_WORKSPACE_SCAN_SECONDS
        folders: list[tuple[Path, int]] = [(self.root, 0)]

        while folders:
            folder, depth = folders.pop()
            try:
                _check_inspection(deadline, "workspace_inspection_timeout")
                entries, scan_complete = self._inspection.entries(
                    folder,
                    limit=max(0, MAX_TREE_SCAN_ENTRIES - scanned),
                    check=lambda: _check_inspection(deadline, "workspace_inspection_timeout"),
                )
            except LocalAgentError as error:
                if error.code == "workspace_inspection_timeout":
                    reasons.add("deadline_reached")
                    break
                if folder == self.root or error.code == "workspace_root_changed":
                    raise
                reasons.add("unavailable_entries")
                continue
            except OSError as error:
                if folder == self.root:
                    raise LocalAgentError("workspace_directory_unavailable") from error
                reasons.add("unavailable_entries")
                continue

            scanned += len(entries)
            if not scan_complete:
                reasons.add("entry_limit")
            for inspected in sorted(entries, key=lambda item: (item.path.name.casefold(), item.path.name)):
                try:
                    _check_inspection(deadline, "workspace_inspection_timeout")
                except LocalAgentError:
                    reasons.add("deadline_reached")
                    folders.clear()
                    break
                kind = self._entry_kind(inspected)
                if kind == "skipped":
                    reasons.add("excluded_directories")
                elif kind == "link":
                    reasons.add("link_or_reparse_entries")
                elif kind == "unrepresentable":
                    reasons.add("unrepresentable_entries")
                elif kind == "unavailable":
                    reasons.add("unavailable_entries")
                elif kind == "directory":
                    if depth >= MAX_SEARCH_DEPTH - 1:
                        reasons.add("depth_limit")
                    else:
                        folders.append((inspected.path, depth + 1))
                elif kind == "file" and inspected.metadata is not None:
                    observed_files += 1
                    if len(files) < MAX_DISCOVERY_FILES:
                        relative = inspected.path.relative_to(self.root).as_posix()
                        files.append(WorkspaceDiscoveredFile(
                            path=relative,
                            byte_size=inspected.metadata.st_size,
                            editable_candidate=bool(
                                inspected.metadata.st_nlink == 1
                                and inspected.metadata.st_size <= MAX_FILE_WRITE_BYTES
                                and not (os.name == "nt" and not inspected.metadata.st_mode & stat.S_IWRITE)
                            ),
                        ))
                    else:
                        reasons.add("display_limit")
            if not scan_complete:
                break

        files.sort(key=lambda item: item.path.encode("utf-8"))
        return WorkspaceInventorySnapshot(
            coverage="partial" if reasons else "complete",
            reasons=tuple(sorted(reasons)),
            scanned_entry_count=scanned,
            observed_file_count=observed_files,
            files=tuple(files),
        )

    def git_status(self) -> WorkspaceGitStatusSnapshot:
        """Read sanitized porcelain status for a repository rooted here only."""

        check_workspace_cancellation()
        git_directory = self.root / ".git"
        try:
            root_identity = self._inspection.directory_identity(self.root)
        except FileNotFoundError as error:
            raise LocalAgentError("workspace_root_changed") from error
        except LocalAgentError as error:
            if error.code == "workspace_root_changed":
                raise
            return _git_unavailable("repository_layout_unsupported")
        except OSError:
            return _git_unavailable("repository_layout_unsupported")
        try:
            git_identity = self._inspection.directory_identity(git_directory)
        except FileNotFoundError:
            try:
                after_root = self._inspection.directory_identity(self.root)
            except FileNotFoundError as error:
                raise LocalAgentError("workspace_root_changed") from error
            except LocalAgentError as error:
                if error.code == "workspace_root_changed":
                    raise
                return _git_unavailable("repository_layout_unsupported")
            except OSError:
                return _git_unavailable("repository_layout_unsupported")
            if after_root != root_identity:
                raise LocalAgentError("workspace_root_changed")
            return WorkspaceGitStatusSnapshot("not_repository", "not_applicable", (), 0, ())
        except LocalAgentError as error:
            return _git_unavailable("repository_layout_unsupported")
        except OSError:
            return _git_unavailable("repository_layout_unsupported")

        if not self._git_layout_is_local(git_directory):
            return _git_unavailable("repository_layout_unsupported")

        if self.command_cleanup_unconfirmed:
            return _git_unavailable("command_cleanup_unconfirmed")
        if not self._command_lock.acquire(blocking=False):
            return _git_unavailable("command_in_progress")
        try:
            if self.command_cleanup_unconfirmed:
                return _git_unavailable("command_cleanup_unconfirmed")
            environment = minimal_environment()
            environment.update({
                "GCM_INTERACTIVE": "Never",
                "GIT_ASKPASS": "",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CEILING_DIRECTORIES": str(self.root),
                "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
                "PAGER": "cat",
            })
            argv = [
                "git",
                "--no-optional-locks",
                "--no-replace-objects",
                "-c", f"core.attributesFile={os.devnull}",
                "-c", f"core.excludesFile={os.devnull}",
                "-c", "core.fsmonitor=false",
                "-c", "core.untrackedCache=false",
                "-c", "status.renames=false",
                "-c", "diff.external=",
                "-c", "submodule.recurse=false",
                f"--git-dir={git_directory}",
                f"--work-tree={self.root}",
                "status",
                "--porcelain=v2",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=all",
            ]
            try:
                completed = self._runner(
                    argv,
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    timeout=MAX_WORKSPACE_SCAN_SECONDS,
                    stdin=subprocess.DEVNULL,
                    errors="surrogateescape",
                    encoding="utf-8",
                    env=environment,
                )
            except RuntimeCleanupUnconfirmed:
                self._command_cleanup_unconfirmed.set()
                return _git_unavailable("command_cleanup_unconfirmed")
            except RuntimeCooperativeStop:
                raise
            except subprocess.TimeoutExpired:
                return _git_unavailable("deadline_reached")
            except FileNotFoundError:
                return _git_unavailable("executable_unavailable")
            except (OSError, UnicodeError):
                return _git_unavailable("status_failed")
        finally:
            self._command_lock.release()

        # Discard every byte when the selected root or repository metadata was
        # replaced while Git inspected it.
        try:
            after_root = self._inspection.directory_identity(self.root)
            after_git = self._inspection.directory_identity(git_directory)
        except LocalAgentError as error:
            if error.code == "workspace_root_changed":
                raise
            return _git_unavailable("repository_changed")
        except OSError:
            return _git_unavailable("repository_changed")
        if after_root != root_identity:
            raise LocalAgentError("workspace_root_changed")
        if after_git != git_identity:
            return _git_unavailable("repository_changed")
        if completed.returncode != 0:
            return _git_unavailable("status_failed")
        if getattr(completed, "output_truncated", False):
            return _git_unavailable("output_limit")
        if not isinstance(completed.stdout, str):
            return _git_unavailable("status_invalid")
        try:
            changes, change_count, reasons = _parse_git_porcelain(
                completed.stdout,
                self._normalize_git_path,
            )
        except (UnicodeError, ValueError):
            return _git_unavailable("status_invalid")
        return WorkspaceGitStatusSnapshot(
            state="available",
            coverage="partial" if reasons else "complete",
            reasons=tuple(sorted(reasons)),
            change_count=change_count,
            changes=changes,
        )

    def _git_layout_is_local(self, git_directory: Path) -> bool:
        """Reject Git metadata that can redirect reads outside this workspace."""

        # Linked metadata is already rejected by WorkspaceIO. These regular
        # files are Git's remaining on-disk indirection mechanisms.
        for relative in (
            "commondir",
            "objects/info/alternates",
            "objects/info/http-alternates",
        ):
            try:
                self._inspection.read(
                    git_directory / Path(relative),
                    limit=1,
                    allow_prefix=True,
                    single_link=True,
                )
            except FileNotFoundError:
                continue
            except (OSError, LocalAgentError):
                return False
            return False

        for name in ("config", "config.worktree"):
            try:
                inspected = self._inspection.read(
                    git_directory / name,
                    limit=MAX_FILE_READ_BYTES,
                    single_link=True,
                )
            except FileNotFoundError:
                continue
            except (OSError, LocalAgentError):
                return False
            try:
                config = inspected.payload.decode("utf-8", errors="strict")
            except UnicodeError:
                return False
            if _git_config_has_external_indirection(config):
                return False
        return True

    def _normalize_git_path(self, value: str) -> tuple[str | None, str | None]:
        if (
            not value
            or len(value) > 1024
            or "\\" in value
            or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in value)
        ):
            return None, "unrepresentable_paths"
        try:
            candidate = self._lexical_candidate(value)
        except LocalAgentError as error:
            return None, "excluded_paths" if error.code == "workspace_path_not_found" else "unrepresentable_paths"
        normalized = candidate.relative_to(self.root).as_posix()
        if normalized != value:
            return None, "unrepresentable_paths"
        return normalized, None

    def read_text_snapshot(self, path: str) -> WorkspaceTextSnapshot:
        target = self._lexical_candidate(path)
        snapshot = self._snapshot_file(target)
        if snapshot is None:
            raise LocalAgentError("workspace_path_not_found")
        payload = snapshot[0]
        try:
            content = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise LocalAgentError("workspace_binary_refused") from error
        if "\x00" in content:
            raise LocalAgentError("workspace_binary_refused")
        without_crlf = payload.replace(b"\r\n", b"")
        if b"\r" in without_crlf or (b"\r\n" in payload and b"\n" in without_crlf):
            raise LocalAgentError("workspace_line_endings_unsupported")
        if b"\r\n" in payload:
            line_ending: Literal["lf", "crlf", "none"] = "crlf"
            content = content.replace("\r\n", "\n")
        elif b"\n" in payload:
            line_ending = "lf"
        else:
            line_ending = "none"
        return WorkspaceTextSnapshot(
            path=target.relative_to(self.root).as_posix(),
            content=content,
            revision=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            line_ending=line_ending,
        )

    def list_dir(self, path: str = ".", depth: int = 1) -> ToolOutcome:
        check_workspace_cancellation()
        try:
            target = self.root if path in {"", "."} else self._lexical_candidate(path)
        except LocalAgentError as error:
            return _inspection_error(error)
        lines: list[str] = []
        reasons: set[str] = set()
        scanned = 0
        deadline = time.monotonic() + MAX_WORKSPACE_SCAN_SECONDS
        depth = max(1, min(int(depth or 1), 2))

        def walk(folder: Path, level: int) -> None:
            nonlocal scanned
            _check_inspection(deadline, "workspace_inspection_timeout")
            try:
                entries, complete = self._inspection.entries(folder, limit=max(0, MAX_TREE_SCAN_ENTRIES - scanned),
                    check=lambda: _check_inspection(deadline, "workspace_inspection_timeout"))
            except (OSError, LocalAgentError) as error:
                reasons.add(_inspection_error(error).text)
                return
            scanned += len(entries)
            if not complete:
                reasons.add("directory scan limit reached")
            entries = sorted(entries, key=lambda entry: (self._entry_kind(entry) != "directory", entry.path.name.casefold(), entry.path.name))
            for inspected in entries:
                _check_inspection(deadline, "workspace_inspection_timeout")
                if len(lines) >= MAX_LIST_ENTRIES:
                    reasons.add("entry display limit reached")
                    return
                entry, metadata = inspected.path, inspected.metadata
                rel = entry.relative_to(self.root).as_posix()
                kind = self._entry_kind(inspected)
                if kind == "unrepresentable":
                    reasons.add("some entry names cannot be safely represented")
                elif kind == "link":
                    lines.append(f"{rel} (link, not followed)")
                elif kind == "skipped":
                    suffix = "/" if metadata is not None and stat.S_ISDIR(metadata.st_mode) else ""
                    lines.append(f"{rel}{suffix} (skipped)")
                elif kind == "directory":
                    lines.append(f"{rel}/")
                    if level < depth:
                        walk(entry, level + 1)
                elif kind == "file" and metadata is not None:
                    lines.append(f"{rel} ({metadata.st_size} bytes)")
                else:
                    lines.append(f"{rel} (unavailable; size unknown)")
                    reasons.add("some entries are unavailable")

        code = None
        try:
            walk(target, 1)
        except LocalAgentError as error:
            code = error.code
            reasons.add(_inspection_error(error).text)
        return _inspection_result(lines, reasons, empty="(empty folder)", code=code)

    def _entry_kind(self, entry: InspectedEntry) -> str:
        relative = entry.path.relative_to(self.root).as_posix()
        try:
            self._lexical_candidate(relative)
        except LocalAgentError as error:
            return "skipped" if error.code == "workspace_path_not_found" else "unrepresentable"
        if entry.metadata is None:
            return "unavailable"
        if _is_link_or_reparse(entry.metadata):
            return "link"
        if stat.S_ISDIR(entry.metadata.st_mode):
            return "directory"
        if stat.S_ISREG(entry.metadata.st_mode):
            return "file"
        return "unavailable"

    def search_text_snapshot(
        self,
        query: str,
        glob: str = "**/*",
        regex: bool = False,
    ) -> WorkspaceTextSearchSnapshot:
        """Search admitted UTF-8 text without creating filesystem authority.

        The result is deliberately structured so every caller receives the
        same coverage, limit, and skipped-entry evidence.  It contains only
        workspace-relative paths and bounded single-line previews.
        """

        check_workspace_cancellation()
        if not query:
            raise LocalAgentError("workspace_query_empty")
        if len(query) > MAX_SEARCH_QUERY_CHARS:
            raise LocalAgentError("workspace_query_too_large")
        try:
            pattern = bounded_regex.compile(query if regex else bounded_regex.escape(query), bounded_regex.I | bounded_regex.VERSION0)
        except (bounded_regex.error, RecursionError, OverflowError):
            raise LocalAgentError("workspace_regex_invalid") from None
        try:
            matcher = WorkspaceGlob(glob or "**/*")
        except LocalAgentError:
            raise LocalAgentError("workspace_glob_invalid") from None
        matches: list[WorkspaceTextSearchMatch] = []
        reasons: set[str] = set()
        scanned = consumed = 0
        skipped = 0
        deadline = time.monotonic() + MAX_WORKSPACE_SCAN_SECONDS
        folders = [(self.root, 0)]
        code = None

        def check() -> None:
            _check_inspection(deadline, "workspace_search_timeout")

        def consume(count: int) -> None:
            nonlocal consumed
            # Failed/changed reads still consume the invocation's byte budget.
            consumed += count

        try:
            while folders:
                check()
                folder, depth = folders.pop()
                try:
                    entries, complete = self._inspection.entries(folder, limit=max(0, MAX_TREE_SCAN_ENTRIES - scanned), check=check)
                except (OSError, LocalAgentError) as error:
                    if isinstance(error, LocalAgentError) and error.code in {
                        "workspace_search_timeout",
                        "workspace_root_changed",
                    }:
                        raise
                    reasons.add(_inspection_error(error).text)
                    continue
                scanned += len(entries)
                if not complete:
                    reasons.add("directory scan limit reached")
                for entry in sorted(entries, key=lambda item: (item.path.name.casefold(), item.path.name)):
                    check()
                    relative = PurePosixPath(entry.path.relative_to(self.root).as_posix())
                    kind = self._entry_kind(entry)
                    if kind == "skipped":
                        skipped += 1
                    elif kind == "directory" and matcher.can_descend(relative):
                        if depth >= MAX_SEARCH_DEPTH - 1:
                            reasons.add("directory depth limit reached")
                        else:
                            folders.append((entry.path, depth + 1))
                    elif kind in {"link", "unavailable", "unrepresentable"}:
                        if matcher.matches(relative) or matcher.can_descend(relative):
                            reasons.add("links are not followed; some entries could not be inspected")
                    elif kind == "file" and matcher.matches(relative):
                        if consumed >= MAX_SEARCH_TOTAL_BYTES:
                            reasons.add("total read budget reached")
                            folders.clear()
                            break
                        read_limit = min(MAX_SEARCH_FILE_BYTES, MAX_SEARCH_TOTAL_BYTES - consumed)
                        try:
                            inspected = self._inspection.read(entry.path, limit=read_limit, check=check, consume=consume)
                        except (OSError, LocalAgentError) as error:
                            if isinstance(error, LocalAgentError) and error.code in {
                                "workspace_search_timeout",
                                "workspace_root_changed",
                            }:
                                raise
                            reasons.add(_inspection_error(error).text)
                            continue
                        if b"\x00" in inspected.payload:
                            skipped += 1
                            continue
                        try:
                            content = inspected.payload.decode("utf-8", errors="strict")
                        except UnicodeDecodeError:
                            skipped += 1
                            continue
                        for number, line in enumerate(content.splitlines(), 1):
                            check()
                            matched = pattern.search(line, timeout=min(MAX_REGEX_MATCH_SECONDS, max(0.001, deadline - time.monotonic())))
                            check()
                            if matched:
                                matches.append(
                                    WorkspaceTextSearchMatch(
                                        path=relative.as_posix(),
                                        line_number=number,
                                        preview=_safe_search_preview(line),
                                    )
                                )
                                if len(matches) >= MAX_SEARCH_RESULTS:
                                    reasons.add("match limit reached")
                                    break
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        folders.clear()
                        break
                if not complete or scanned >= MAX_TREE_SCAN_ENTRIES:
                    if folders:
                        reasons.add("directory scan limit reached")
                    break
        except TimeoutError:
            check_workspace_cancellation()
            code = "workspace_search_timeout"
            reasons.add("regex matching deadline reached")
        except LocalAgentError as error:
            if error.code == "workspace_root_changed":
                raise
            code = error.code
            reasons.add(_inspection_error(error).text)
        matches.sort(key=lambda item: (item.path.encode("utf-8"), item.line_number))
        return WorkspaceTextSearchSnapshot(
            coverage="partial" if reasons else "complete",
            reasons=tuple(sorted(reasons)),
            reason_code=code or ("workspace_inspection_incomplete" if reasons else None),
            scanned_entry_count=scanned,
            inspected_byte_count=consumed,
            skipped_entry_count=skipped,
            matches=tuple(matches),
        )

    def search_text(self, query: str, glob: str = "**/*", regex: bool = False) -> ToolOutcome:
        try:
            snapshot = self.search_text_snapshot(query, glob, regex)
        except LocalAgentError as error:
            messages = {
                "workspace_query_empty": "empty query",
                "workspace_query_too_large": "query exceeds the supported length",
                "workspace_regex_invalid": "invalid regex",
                "workspace_glob_invalid": "glob must be a supported relative workspace pattern",
                "workspace_root_changed": "workspace root changed; start a new session after inspecting the folder",
            }
            return ToolOutcome(False, messages.get(error.code, "workspace search was unavailable"), error.code)

        results = [
            f"{item.path}:{item.line_number}: {item.preview}"
            for item in snapshot.matches
        ]
        if snapshot.skipped_entry_count:
            if not results and not snapshot.reasons:
                results.append("no matches in inspected UTF-8 text files")
            results.append("[Scope: noisy folders and non-UTF-8/binary files are skipped]")
        return _inspection_result(
            results,
            set(snapshot.reasons),
            empty="no matches in inspected UTF-8 text files",
            code=snapshot.reason_code,
        )

    @staticmethod
    def _identity(metadata: os.stat_result) -> tuple[int, int]:
        return metadata.st_dev, metadata.st_ino

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            check_workspace_cancellation()
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short local write")
            offset += written
        check_workspace_cancellation()

    def _snapshot_file(
        self,
        target: Path,
        *,
        check: Callable[[], None] = check_workspace_cancellation,
    ) -> tuple[bytes, os.stat_result] | None:
        try:
            inspected = self._inspection.read(
                target,
                limit=MAX_FILE_WRITE_BYTES,
                single_link=True,
                check=check,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise LocalAgentError("workspace_file_unavailable") from error
        return inspected.payload, inspected.metadata

    @staticmethod
    def _metadata_revision(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_nlink,
        )

    def _read_open_descriptor(
        self,
        descriptor: int,
        *,
        check: Callable[[], None] = check_workspace_cancellation,
        require_single_link: bool = True,
    ) -> tuple[bytes, os.stat_result]:
        """Read one already-open regular file without accepting a changing revision."""
        check()
        os.lseek(descriptor, 0, os.SEEK_SET)
        before = os.fstat(descriptor)
        if (
            is_link_or_reparse(before)
            or not stat.S_ISREG(before.st_mode)
            or (require_single_link and before.st_nlink != 1)
            or before.st_size > MAX_FILE_WRITE_BYTES
        ):
            raise LocalAgentError("workspace_file_unavailable")
        payload = bytearray()
        while len(payload) < before.st_size:
            check()
            chunk = os.read(descriptor, min(65_536, before.st_size - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        check()
        if (
            self._metadata_revision(before) != self._metadata_revision(after)
            or len(payload) != after.st_size
        ):
            raise LocalAgentError("workspace_file_changed")
        return bytes(payload), after

    @staticmethod
    def _windows_path_metadata(target: Path) -> os.stat_result | None:
        try:
            return target.lstat()
        except FileNotFoundError:
            return None

    @staticmethod
    def _private_stage_path(
        parent: Path,
        kind: Literal["edit", "backup", "recovery", "trash"],
    ) -> Path:
        return parent / f".prompt-enhancer-{kind}-{secrets.token_hex(16)}.tmp"

    @staticmethod
    def _open_windows_target(target: Path) -> int:
        from .local_workspace_windows import open_reviewed_target_descriptor

        return open_reviewed_target_descriptor(target)

    @staticmethod
    def _create_windows_stage(target: Path) -> int:
        from .local_workspace_windows import create_staged_descriptor

        return create_staged_descriptor(target)

    @staticmethod
    def _discard_windows_descriptor(descriptor: int) -> None:
        from .local_workspace_windows import discard_descriptor

        discard_descriptor(descriptor)

    @staticmethod
    def _replace_windows_file(target: Path, replacement: Path, backup: Path) -> None:
        from .local_workspace_windows import replace_file_with_backup

        replace_file_with_backup(target, replacement, backup)

    def _discard_owned_windows_path(
        self,
        target: Path,
        expected_identity: tuple[int, int],
    ) -> bool:
        """Discard only the still-matching private name while its parent is pinned."""
        descriptor: int | None = None
        discarded = False
        try:
            descriptor = self._open_windows_target(target)
            if self._identity(os.fstat(descriptor)) == expected_identity:
                self._discard_windows_descriptor(descriptor)
                discarded = True
        except (FileNotFoundError, OSError, LocalAgentError):
            discarded = False
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    discarded = False
        return discarded

    @staticmethod
    def _publish_new_windows(stage: Path, target: Path) -> None:
        # Windows rename without a replacement flag is an atomic create-if-absent.
        os.rename(stage, target)

    def _matches_reviewed_file(
        self,
        payload: bytes,
        metadata: os.stat_result,
        prepared: PreparedWrite,
    ) -> bool:
        return (
            self._identity(metadata) == prepared.base_identity
            and metadata.st_nlink == 1
            and hashlib.sha256(payload).hexdigest() == prepared.base_sha256
        )

    def _apply_prepared_write_windows(
        self,
        target: Path,
        prepared: PreparedWrite,
        proposed: bytes,
    ) -> _PublicationResult:
        no_cancel = lambda: None
        target_descriptor: int | None = None
        stage_descriptor: int | None = None
        published_descriptor: int | None = None
        stage_path: Path | None = None
        stage_identity: tuple[int, int] | None = None
        published_marked_for_delete = False
        write_attempted = False
        try:
            with self._inspection._directory(
                target.parent,
                check_workspace_cancellation,
                mutation=True,
            ) as parent_descriptor:
                if self._identity(os.fstat(parent_descriptor)) != prepared.parent_identity:
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )

                baseline = b""
                if prepared.existed:
                    try:
                        target_descriptor = self._open_windows_target(target)
                        baseline, target_metadata = self._read_open_descriptor(target_descriptor)
                        path_metadata = self._windows_path_metadata(target)
                    except (OSError, LocalAgentError):
                        return _PublicationResult(
                            "rejected",
                            "file is no longer safe to write; inspect it again",
                            "workspace_file_unavailable",
                        )
                    if (
                        path_metadata is None
                        or self._metadata_revision(path_metadata) != self._metadata_revision(target_metadata)
                        or not self._matches_reviewed_file(baseline, target_metadata, prepared)
                    ):
                        return _PublicationResult(
                            "rejected",
                            "file changed since preview; read it again and propose a new change",
                            "workspace_revision_changed",
                        )
                elif self._windows_path_metadata(target) is not None:
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )

                if baseline == proposed and prepared.existed:
                    return _PublicationResult(
                        "unchanged",
                        f"{prepared.path} already matches the reviewed content",
                    )

                for _ in range(8):
                    stage_path = self._private_stage_path(target.parent, "edit")
                    try:
                        stage_descriptor = self._create_windows_stage(stage_path)
                        break
                    except FileExistsError:
                        continue
                if stage_descriptor is None or stage_path is None:
                    return _PublicationResult(
                        "rejected",
                        "a private staging file could not be created; the reviewed path was not changed",
                        "workspace_write_failed",
                    )
                try:
                    self._write_all(stage_descriptor, proposed)
                    os.fsync(stage_descriptor)
                    staged_payload, staged_metadata = self._read_open_descriptor(stage_descriptor)
                except (OSError, LocalAgentError):
                    return _PublicationResult(
                        "rejected",
                        "the reviewed content could not be staged; the reviewed path was not changed",
                        "workspace_write_failed",
                    )
                if staged_payload != proposed:
                    return _PublicationResult(
                        "rejected",
                        "the reviewed content could not be staged exactly; the reviewed path was not changed",
                        "workspace_write_failed",
                    )
                stage_identity = self._identity(staged_metadata)
                check_workspace_cancellation()

                if prepared.existed:
                    assert target_descriptor is not None
                    try:
                        latest_payload, latest_metadata = self._read_open_descriptor(target_descriptor)
                        latest_path = self._windows_path_metadata(target)
                    except (OSError, LocalAgentError):
                        return _PublicationResult(
                            "rejected",
                            "file changed since preview; read it again and propose a new change",
                            "workspace_revision_changed",
                        )
                    if (
                        latest_path is None
                        or self._metadata_revision(latest_path) != self._metadata_revision(latest_metadata)
                        or not self._matches_reviewed_file(latest_payload, latest_metadata, prepared)
                    ):
                        return _PublicationResult(
                            "rejected",
                            "file changed since preview; read it again and propose a new change",
                            "workspace_revision_changed",
                        )

                    os.close(stage_descriptor)
                    stage_descriptor = None
                    backup_path = self._private_stage_path(target.parent, "backup")
                    write_attempted = True
                    try:
                        self._replace_windows_file(target, stage_path, backup_path)
                    except OSError:
                        current = self._windows_path_metadata(target)
                        staged = self._windows_path_metadata(stage_path)
                        try:
                            current_payload, current_metadata = self._read_open_descriptor(
                                target_descriptor,
                                check=no_cancel,
                            )
                        except (OSError, LocalAgentError):
                            current_payload = None
                            current_metadata = None
                        if (
                            current is not None
                            and current_metadata is not None
                            and self._metadata_revision(current) == self._metadata_revision(current_metadata)
                            and staged is not None
                            and self._identity(staged) == stage_identity
                            and self._windows_path_metadata(backup_path) is None
                        ):
                            if not self._discard_owned_windows_path(stage_path, stage_identity):
                                raise _WriteCleanupUnconfirmed(publication_attempted=True)
                            stage_path = None
                            if not self._matches_reviewed_file(
                                current_payload or b"",
                                current_metadata,
                                prepared,
                            ):
                                return _PublicationResult(
                                    "rejected",
                                    "file changed at publication; that version was preserved and must be reviewed again",
                                    "workspace_revision_changed",
                                )
                            return _PublicationResult(
                                "rejected",
                                "the atomic replacement was refused; the reviewed file was not changed",
                                "workspace_write_failed",
                            )
                        if staged is not None and self._identity(staged) == stage_identity:
                            if not self._discard_owned_windows_path(stage_path, stage_identity):
                                raise _WriteCleanupUnconfirmed(publication_attempted=True)
                            stage_path = None
                        return _PublicationResult(
                            "unverified",
                            "the replacement result could not be proven; inspect the file before continuing",
                            "workspace_verification_failed",
                        )
                    stage_path = None

                    try:
                        displaced_payload, displaced_metadata = self._read_open_descriptor(
                            target_descriptor,
                            check=no_cancel,
                        )
                        backup_metadata = self._windows_path_metadata(backup_path)
                        published_descriptor = self._open_windows_target(target)
                        published_payload, published_metadata = self._read_open_descriptor(
                            published_descriptor,
                            check=no_cancel,
                        )
                        published_path = self._windows_path_metadata(target)
                    except (OSError, LocalAgentError):
                        current = self._windows_path_metadata(target)
                        backup_metadata = self._windows_path_metadata(backup_path)
                        try:
                            displaced_payload, displaced_metadata = self._read_open_descriptor(
                                target_descriptor,
                                check=no_cancel,
                            )
                        except (OSError, LocalAgentError):
                            displaced_payload = None
                            displaced_metadata = None
                        can_restore = (
                            current is not None
                            and backup_metadata is not None
                            and displaced_metadata is not None
                            and self._identity(current) == stage_identity
                            and self._identity(backup_metadata) == self._identity(displaced_metadata)
                        )
                        if can_restore:
                            recovery_path = self._private_stage_path(target.parent, "recovery")
                            try:
                                if published_descriptor is not None:
                                    os.close(published_descriptor)
                                    published_descriptor = None
                                os.close(target_descriptor)
                                target_descriptor = None
                                self._replace_windows_file(target, backup_path, recovery_path)
                                target_descriptor = self._open_windows_target(target)
                                restored_payload, restored_metadata = self._read_open_descriptor(
                                    target_descriptor,
                                    check=no_cancel,
                                )
                                restored_path = self._windows_path_metadata(target)
                                if (
                                    restored_path is not None
                                    and self._metadata_revision(restored_path) == self._metadata_revision(restored_metadata)
                                    and restored_payload == displaced_payload
                                ):
                                    published_descriptor = self._open_windows_target(recovery_path)
                                    self._discard_windows_descriptor(published_descriptor)
                                    published_marked_for_delete = True
                                    return _PublicationResult(
                                        "rejected",
                                        "the replacement could not be verified, so the previous file was restored",
                                        "workspace_write_failed",
                                    )
                            except (OSError, LocalAgentError):
                                pass
                        return _PublicationResult(
                            "unverified",
                            "the replacement completed but could not be verified or restored; inspect the file before continuing",
                            "workspace_verification_failed",
                        )
                    baseline_still_exact = (
                        backup_metadata is not None
                        and self._metadata_revision(backup_metadata) == self._metadata_revision(displaced_metadata)
                        and self._matches_reviewed_file(displaced_payload, displaced_metadata, prepared)
                    )
                    proposed_is_exact = (
                        published_path is not None
                        and self._metadata_revision(published_path) == self._metadata_revision(published_metadata)
                        and self._identity(published_metadata) == stage_identity
                        and published_payload == proposed
                    )
                    if not baseline_still_exact or not proposed_is_exact:
                        can_restore = (
                            backup_metadata is not None
                            and published_path is not None
                            and self._identity(published_path) == stage_identity
                            and self._identity(backup_metadata) == self._identity(displaced_metadata)
                        )
                        if can_restore:
                            recovery_path = self._private_stage_path(target.parent, "recovery")
                            try:
                                os.close(published_descriptor)
                                published_descriptor = None
                                os.close(target_descriptor)
                                target_descriptor = None
                                self._replace_windows_file(target, backup_path, recovery_path)
                                target_descriptor = self._open_windows_target(target)
                                restored_path = self._windows_path_metadata(target)
                                restored_payload, restored_metadata = self._read_open_descriptor(
                                    target_descriptor,
                                    check=no_cancel,
                                )
                                if (
                                    restored_path is not None
                                    and self._metadata_revision(restored_path) == self._metadata_revision(restored_metadata)
                                    and restored_payload == displaced_payload
                                ):
                                    published_descriptor = self._open_windows_target(recovery_path)
                                    self._discard_windows_descriptor(published_descriptor)
                                    published_marked_for_delete = True
                                    return _PublicationResult(
                                        "rejected",
                                        "file changed at publication; that version was restored and must be reviewed again",
                                        "workspace_revision_changed",
                                    )
                            except (OSError, LocalAgentError):
                                pass
                        return _PublicationResult(
                            "unverified",
                            "the replacement could not be verified or safely restored; inspect the file before continuing",
                            "workspace_verification_failed",
                        )

                    try:
                        self._discard_windows_descriptor(target_descriptor)
                    except OSError as error:
                        raise _WriteCleanupUnconfirmed(publication_attempted=True) from error
                    return _PublicationResult(
                        "published",
                        f"wrote {prepared.path} ({len(prepared.content)} characters)",
                    )

                current = self._windows_path_metadata(target)
                if current is not None:
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )
                write_attempted = True
                try:
                    self._publish_new_windows(stage_path, target)
                    stage_path = None
                    published_payload, published_metadata = self._read_open_descriptor(
                        stage_descriptor,
                        check=no_cancel,
                    )
                    published_path = self._windows_path_metadata(target)
                    if (
                        published_path is None
                        or self._metadata_revision(published_path) != self._metadata_revision(published_metadata)
                        or self._identity(published_metadata) != stage_identity
                        or published_payload != proposed
                    ):
                        raise LocalAgentError("workspace_file_changed")
                except FileExistsError:
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )
                except (OSError, LocalAgentError):
                    current = self._windows_path_metadata(target)
                    if (
                        current is not None
                        and stage_identity is not None
                        and self._identity(current) == stage_identity
                    ):
                        try:
                            self._discard_windows_descriptor(stage_descriptor)
                            published_marked_for_delete = True
                            return _PublicationResult(
                                "rejected",
                                "the new file could not be verified and was removed",
                                "workspace_write_failed",
                            )
                        except OSError:
                            pass
                    return _PublicationResult(
                        "unverified" if write_attempted else "rejected",
                        "the new-file result could not be proven; inspect the path before continuing",
                        "workspace_verification_failed" if write_attempted else "workspace_write_failed",
                    )
                return _PublicationResult(
                    "published",
                    f"wrote {prepared.path} ({len(prepared.content)} characters)",
                )
        finally:
            cleanup_error = False
            if stage_descriptor is not None and stage_path is not None and not published_marked_for_delete:
                try:
                    self._discard_windows_descriptor(stage_descriptor)
                except OSError:
                    cleanup_error = True
            for descriptor in (published_descriptor, stage_descriptor, target_descriptor):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        cleanup_error = True
            # Escalate only a fixed, content-free state; never leak a path-bearing
            # OS exception or silently claim that private cleanup completed.
            if cleanup_error:
                raise _WriteCleanupUnconfirmed(publication_attempted=write_attempted)

    @staticmethod
    def _exchange_posix(parent_descriptor: int, left: str, right: str) -> None:
        """Atomically exchange two names, or fail closed on unsupported systems."""
        library = ctypes.CDLL(None, use_errno=True)
        encoded_left = os.fsencode(left)
        encoded_right = os.fsencode(right)
        if platform.system() == "Linux" and hasattr(library, "renameat2"):
            rename = library.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            if rename(parent_descriptor, encoded_left, parent_descriptor, encoded_right, 0x2) == 0:
                return
        elif platform.system() == "Darwin" and hasattr(library, "renameatx_np"):
            rename = library.renameatx_np
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            if rename(parent_descriptor, encoded_left, parent_descriptor, encoded_right, 0x00000002) == 0:
                return
        else:
            raise OSError(errno.ENOTSUP, "workspace_atomic_exchange_unavailable")
        code = ctypes.get_errno()
        raise OSError(code or errno.EIO, "workspace_atomic_exchange_failed")

    @staticmethod
    def _posix_entry_metadata(parent_descriptor: int, name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _apply_prepared_write_posix(
        self,
        target: Path,
        prepared: PreparedWrite,
        proposed: bytes,
    ) -> _PublicationResult:
        target_descriptor: int | None = None
        stage_descriptor: int | None = None
        published_descriptor: int | None = None
        stage_name: str | None = None
        stage_identity: tuple[int, int] | None = None
        parent_descriptor: int | None = None
        cleanup_parent_descriptor: int | None = None
        publication_attempted = False
        cleanup_error = False
        try:
            with self._inspection._directory(target.parent, check_workspace_cancellation) as parent_descriptor:
                cleanup_parent_descriptor = os.dup(parent_descriptor)
                if self._identity(os.fstat(parent_descriptor)) != prepared.parent_identity:
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )
                baseline = b""
                if prepared.existed:
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
                    try:
                        target_descriptor = os.open(target.name, flags, dir_fd=parent_descriptor)
                        try:
                            import fcntl

                            fcntl.flock(target_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except (ImportError, BlockingIOError, OSError) as error:
                            raise LocalAgentError("workspace_file_changed") from error
                        baseline, target_metadata = self._read_open_descriptor(target_descriptor)
                        path_metadata = self._posix_entry_metadata(parent_descriptor, target.name)
                    except (OSError, LocalAgentError):
                        return _PublicationResult(
                            "rejected",
                            "file is no longer safe to write; inspect it again",
                            "workspace_file_unavailable",
                        )
                    if (
                        path_metadata is None
                        or self._metadata_revision(path_metadata) != self._metadata_revision(target_metadata)
                        or not self._matches_reviewed_file(baseline, target_metadata, prepared)
                    ):
                        return _PublicationResult(
                            "rejected",
                            "file changed since preview; read it again and propose a new change",
                            "workspace_revision_changed",
                        )
                elif self._posix_entry_metadata(parent_descriptor, target.name) is not None:
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )

                if baseline == proposed and prepared.existed:
                    return _PublicationResult(
                        "unchanged",
                        f"{prepared.path} already matches the reviewed content",
                    )

                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
                for _ in range(8):
                    stage_name = self._private_stage_path(target.parent, "edit").name
                    try:
                        stage_descriptor = os.open(
                            stage_name,
                            flags,
                            prepared.mode if prepared.mode is not None else 0o600,
                            dir_fd=parent_descriptor,
                        )
                        break
                    except FileExistsError:
                        continue
                if stage_descriptor is None or stage_name is None:
                    return _PublicationResult(
                        "rejected",
                        "a private staging file could not be created; the reviewed path was not changed",
                        "workspace_write_failed",
                    )
                try:
                    self._write_all(stage_descriptor, proposed)
                    os.fsync(stage_descriptor)
                    if prepared.mode is not None:
                        os.fchmod(stage_descriptor, prepared.mode)
                    staged_payload, staged_metadata = self._read_open_descriptor(stage_descriptor)
                except (OSError, LocalAgentError):
                    return _PublicationResult(
                        "rejected",
                        "the reviewed content could not be staged; the reviewed path was not changed",
                        "workspace_write_failed",
                    )
                if staged_payload != proposed:
                    return _PublicationResult(
                        "rejected",
                        "the reviewed content could not be staged exactly; the reviewed path was not changed",
                        "workspace_write_failed",
                    )
                stage_identity = self._identity(staged_metadata)
                check_workspace_cancellation()

                if not prepared.existed:
                    if self._posix_entry_metadata(parent_descriptor, target.name) is not None:
                        return _PublicationResult(
                            "rejected",
                            "file changed since preview; read it again and propose a new change",
                            "workspace_revision_changed",
                        )
                    try:
                        publication_attempted = True
                        os.link(
                            stage_name,
                            target.name,
                            src_dir_fd=parent_descriptor,
                            dst_dir_fd=parent_descriptor,
                            follow_symlinks=False,
                        )
                        target_metadata = self._posix_entry_metadata(parent_descriptor, target.name)
                        if target_metadata is None or self._identity(target_metadata) != stage_identity:
                            raise LocalAgentError("workspace_file_changed")
                        os.unlink(stage_name, dir_fd=parent_descriptor)
                        stage_name = None
                        os.fsync(parent_descriptor)
                        published_payload, published_metadata = self._read_open_descriptor(stage_descriptor)
                        published_path = self._posix_entry_metadata(parent_descriptor, target.name)
                        if (
                            published_path is None
                            or self._metadata_revision(published_path) != self._metadata_revision(published_metadata)
                            or published_payload != proposed
                        ):
                            raise LocalAgentError("workspace_file_changed")
                    except (OSError, LocalAgentError):
                        current = self._posix_entry_metadata(parent_descriptor, target.name)
                        if current is not None and self._identity(current) == stage_identity:
                            try:
                                os.unlink(target.name, dir_fd=parent_descriptor)
                                os.fsync(parent_descriptor)
                                return _PublicationResult(
                                    "rejected",
                                    "the new file could not be verified and was removed",
                                    "workspace_write_failed",
                                )
                            except OSError:
                                pass
                        elif current is not None:
                            return _PublicationResult(
                                "rejected",
                                "file changed since preview; read it again and propose a new change",
                                "workspace_revision_changed",
                            )
                        elif self._posix_entry_metadata(parent_descriptor, stage_name) is not None:
                            return _PublicationResult(
                                "rejected",
                                "the atomic publication was refused; the reviewed path was not changed",
                                "workspace_write_failed",
                            )
                        return _PublicationResult(
                            "unverified",
                            "the new-file result could not be proven; inspect the path before continuing",
                            "workspace_verification_failed",
                        )
                    return _PublicationResult(
                        "published",
                        f"wrote {prepared.path} ({len(prepared.content)} characters)",
                    )

                assert target_descriptor is not None
                latest_payload, latest_metadata = self._read_open_descriptor(target_descriptor)
                latest_path = self._posix_entry_metadata(parent_descriptor, target.name)
                if (
                    latest_path is None
                    or self._metadata_revision(latest_path) != self._metadata_revision(latest_metadata)
                    or not self._matches_reviewed_file(latest_payload, latest_metadata, prepared)
                ):
                    return _PublicationResult(
                        "rejected",
                        "file changed since preview; read it again and propose a new change",
                        "workspace_revision_changed",
                    )
                try:
                    publication_attempted = True
                    self._exchange_posix(parent_descriptor, stage_name, target.name)
                except OSError:
                    return _PublicationResult(
                        "rejected",
                        "atomic replacement is unavailable on this filesystem; the reviewed file was not changed",
                        "workspace_write_failed",
                    )
                try:
                    published_descriptor = os.open(
                        target.name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                        dir_fd=parent_descriptor,
                    )
                    displaced_path = self._posix_entry_metadata(parent_descriptor, stage_name)
                    published_path = self._posix_entry_metadata(parent_descriptor, target.name)
                    displaced_payload, displaced_metadata = self._read_open_descriptor(target_descriptor)
                    published_payload, published_metadata = self._read_open_descriptor(published_descriptor)
                except (OSError, LocalAgentError):
                    displaced_path = self._posix_entry_metadata(parent_descriptor, stage_name)
                    published_path = self._posix_entry_metadata(parent_descriptor, target.name)
                    if (
                        displaced_path is not None
                        and published_path is not None
                        and self._identity(published_path) == stage_identity
                    ):
                        try:
                            self._exchange_posix(parent_descriptor, stage_name, target.name)
                            os.fsync(parent_descriptor)
                            restored = self._posix_entry_metadata(parent_descriptor, target.name)
                            if restored is not None and self._identity(restored) == self._identity(displaced_path):
                                return _PublicationResult(
                                    "rejected",
                                    "the replacement could not be verified, so the previous file was restored",
                                    "workspace_write_failed",
                                )
                        except OSError:
                            pass
                    return _PublicationResult(
                        "unverified",
                        "the replacement completed but could not be verified or restored; inspect the file before continuing",
                        "workspace_verification_failed",
                    )
                exact = (
                    displaced_path is not None
                    and self._metadata_revision(displaced_path) == self._metadata_revision(displaced_metadata)
                    and self._matches_reviewed_file(displaced_payload, displaced_metadata, prepared)
                    and published_path is not None
                    and self._metadata_revision(published_path) == self._metadata_revision(published_metadata)
                    and self._identity(published_metadata) == stage_identity
                    and published_payload == proposed
                )
                if not exact:
                    try:
                        self._exchange_posix(parent_descriptor, stage_name, target.name)
                        os.fsync(parent_descriptor)
                        restored = self._posix_entry_metadata(parent_descriptor, target.name)
                        if restored is not None and self._identity(restored) == self._identity(displaced_metadata):
                            return _PublicationResult(
                                "rejected",
                                "file changed at publication; that version was restored and must be reviewed again",
                                "workspace_revision_changed",
                            )
                    except OSError:
                        pass
                    return _PublicationResult(
                        "unverified",
                        "the replacement could not be verified or safely restored; inspect the file before continuing",
                        "workspace_verification_failed",
                    )
                try:
                    os.unlink(stage_name, dir_fd=parent_descriptor)
                    stage_name = None
                    os.fsync(parent_descriptor)
                except OSError as error:
                    raise _WriteCleanupUnconfirmed(publication_attempted=True) from error
                return _PublicationResult(
                    "published",
                    f"wrote {prepared.path} ({len(prepared.content)} characters)",
                )
        finally:
            if stage_descriptor is not None and stage_name is not None and cleanup_parent_descriptor is not None:
                try:
                    stage_metadata = os.fstat(stage_descriptor)
                    path_metadata = os.stat(stage_name, dir_fd=cleanup_parent_descriptor, follow_symlinks=False)
                    if self._identity(stage_metadata) == self._identity(path_metadata):
                        os.unlink(stage_name, dir_fd=cleanup_parent_descriptor)
                except (FileNotFoundError, OSError):
                    cleanup_error = True
            for descriptor in (published_descriptor, stage_descriptor, target_descriptor):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        cleanup_error = True
            if cleanup_parent_descriptor is not None:
                try:
                    os.close(cleanup_parent_descriptor)
                except OSError:
                    cleanup_error = True
            if cleanup_error:
                raise _WriteCleanupUnconfirmed(publication_attempted=publication_attempted)

    @staticmethod
    def _move_entry_metadata(path: Path, parent_descriptor: int) -> os.stat_result | None:
        try:
            return (
                path.lstat()
                if os.name == "nt"
                else os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            )
        except FileNotFoundError:
            return None

    @staticmethod
    def _create_directory_no_replace(target: Path, parent_descriptor: int) -> None:
        """Create exactly one directory; the native primitive never replaces."""

        if os.name == "nt":
            os.mkdir(target)
        else:
            os.mkdir(target.name, mode=0o755, dir_fd=parent_descriptor)

    @staticmethod
    def _open_directory_descriptor(target: Path, parent_descriptor: int) -> int:
        if os.name == "nt":
            from .local_workspace_windows import open_read_descriptor

            return open_read_descriptor(target, directory=True)
        return os.open(
            target.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )

    def _created_directory_identity(
        self,
        target: Path,
        parent_descriptor: int,
    ) -> tuple[int, int] | None:
        descriptor: int | None = None
        identity: tuple[int, int] | None = None
        try:
            descriptor = self._open_directory_descriptor(target, parent_descriptor)
            descriptor_metadata = os.fstat(descriptor)
            path_metadata = self._move_entry_metadata(target, parent_descriptor)
            if not (
                path_metadata is None
                or _is_link_or_reparse(descriptor_metadata)
                or _is_link_or_reparse(path_metadata)
                or not stat.S_ISDIR(descriptor_metadata.st_mode)
                or not stat.S_ISDIR(path_metadata.st_mode)
                or self._identity(descriptor_metadata) != self._identity(path_metadata)
            ):
                identity = self._identity(descriptor_metadata)
        except (OSError, LocalAgentError):
            pass
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    identity = None
        return identity

    def _published_directory_verified(
        self,
        target: Path,
        parent_descriptor: int,
        created_identity: tuple[int, int],
    ) -> bool:
        for _attempt in range(4):
            if self._created_directory_identity(target, parent_descriptor) == created_identity:
                return True
        return False

    def prepare_directory_create(self, path: str) -> PreparedDirectoryCreate:
        """Prepare one absent child directory under one existing reviewed parent."""

        target = self._lexical_candidate(path)
        if target == self.root:
            raise LocalAgentError("path_invalid")
        if not _path_components_are_safe(target.parent):
            raise LocalAgentError("workspace_link_or_reparse_refused")
        try:
            parent_metadata = target.parent.lstat()
        except OSError as error:
            raise LocalAgentError("workspace_parent_unavailable") from error
        if _is_link_or_reparse(parent_metadata) or not stat.S_ISDIR(parent_metadata.st_mode):
            raise LocalAgentError("workspace_parent_unavailable")
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise LocalAgentError("workspace_item_unavailable") from error
        else:
            raise LocalAgentError("workspace_lifecycle_target_exists")
        return PreparedDirectoryCreate(
            path=target.relative_to(self.root).as_posix(),
            parent_identity=self._identity(parent_metadata),
        )

    def apply_prepared_directory_create(
        self,
        prepared: PreparedDirectoryCreate,
    ) -> PreparedDirectoryCreateOutcome:
        """Create and verify one reviewed directory, or report exact uncertainty."""

        target = self._lexical_candidate(prepared.path)
        published = False
        created_identity: tuple[int, int] | None = None
        with _REVIEWED_WRITE_LOCK, self._write_lock:
            try:
                with self._inspection._directory(
                    target.parent,
                    check_workspace_cancellation,
                    mutation=True,
                ) as parent_descriptor:
                    if self._identity(os.fstat(parent_descriptor)) != prepared.parent_identity:
                        return PreparedDirectoryCreateOutcome(
                            "rejected", "workspace_revision_changed"
                        )
                    if self._move_entry_metadata(target, parent_descriptor) is not None:
                        return PreparedDirectoryCreateOutcome(
                            "rejected", "workspace_lifecycle_target_exists"
                        )
                    check_workspace_cancellation()
                    try:
                        self._create_directory_no_replace(target, parent_descriptor)
                        published = True
                    except FileExistsError:
                        return PreparedDirectoryCreateOutcome(
                            "rejected", "workspace_lifecycle_target_exists"
                        )
                    except OSError:
                        return PreparedDirectoryCreateOutcome(
                            "rejected", "workspace_directory_create_failed"
                        )

                    with runtime_critical_cleanup_scope():
                        created_identity = self._created_directory_identity(
                            target, parent_descriptor
                        )
                        if created_identity is None:
                            return PreparedDirectoryCreateOutcome(
                                "unverified", "workspace_directory_create_unverified"
                            )
                        verified = self._published_directory_verified(
                            target, parent_descriptor, created_identity
                        )
                        if verified and os.name != "nt":
                            try:
                                os.fsync(parent_descriptor)
                            except OSError:
                                verified = False
                        if verified:
                            return PreparedDirectoryCreateOutcome("verified", None)
                        return PreparedDirectoryCreateOutcome(
                            "unverified",
                            "workspace_directory_create_unverified",
                        )
            except RuntimeCooperativeStop:
                return PreparedDirectoryCreateOutcome(
                    "unverified" if published else "rejected",
                    "workspace_directory_create_unverified"
                    if published
                    else "tool_cancelled",
                )
            except (OSError, LocalAgentError):
                return PreparedDirectoryCreateOutcome(
                    "unverified" if published else "rejected",
                    "workspace_directory_create_unverified"
                    if published
                    else "workspace_directory_create_failed",
                )

    @staticmethod
    def _rename_move_no_replace(
        source_descriptor: int,
        source_parent_descriptor: int,
        source_name: str,
        target_parent_descriptor: int,
        target_name: str,
        *,
        windows_target: Path | None = None,
    ) -> None:
        if os.name == "nt":
            from .local_workspace_windows import rename_descriptor_no_replace

            if windows_target is None:
                raise OSError("workspace_atomic_move_target_missing")
            rename_descriptor_no_replace(source_descriptor, windows_target)
            return

        library = ctypes.CDLL(None, use_errno=True)
        encoded_source = os.fsencode(source_name)
        encoded_target = os.fsencode(target_name)
        if platform.system() == "Linux" and hasattr(library, "renameat2"):
            rename = library.renameat2
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            rename.restype = ctypes.c_int
            result = rename(
                source_parent_descriptor,
                encoded_source,
                target_parent_descriptor,
                encoded_target,
                0x1,  # RENAME_NOREPLACE
            )
        elif platform.system() == "Darwin" and hasattr(library, "renameatx_np"):
            rename = library.renameatx_np
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            rename.restype = ctypes.c_int
            result = rename(
                source_parent_descriptor,
                encoded_source,
                target_parent_descriptor,
                encoded_target,
                0x00000004,  # RENAME_EXCL
            )
        else:
            raise OSError(errno.ENOTSUP, "workspace_atomic_move_unavailable")
        if result == 0:
            return
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError("workspace_path_exists")
        if code == errno.ENOENT:
            raise FileNotFoundError("workspace_path_not_found")
        raise OSError(code or errno.EIO, "workspace_atomic_move_failed")

    def _directory_move_candidates(
        self,
        source_path: str,
        target_path: str,
    ) -> tuple[Path, Path, str, str]:
        source = self._lexical_candidate(source_path)
        target = self._lexical_candidate(target_path)
        if source == self.root or target == self.root:
            raise LocalAgentError("path_invalid")
        canonical_source = source.relative_to(self.root).as_posix()
        canonical_target = target.relative_to(self.root).as_posix()
        if canonical_source == canonical_target or (
            os.name == "nt" and canonical_source.casefold() == canonical_target.casefold()
        ):
            raise LocalAgentError("workspace_lifecycle_same_path")
        try:
            target.parent.relative_to(source)
        except ValueError:
            pass
        else:
            raise LocalAgentError("workspace_directory_move_into_self")
        return source, target, canonical_source, canonical_target

    def prepare_directory_move(
        self,
        source_path: str,
        target_path: str,
    ) -> PreparedDirectoryMove:
        """Bind one ordinary directory entry and two existing parent identities."""

        source, target, canonical_source, canonical_target = (
            self._directory_move_candidates(source_path, target_path)
        )
        for parent in (source.parent, target.parent):
            if not _path_components_are_safe(parent):
                raise LocalAgentError("workspace_link_or_reparse_refused")
        try:
            source_parent_metadata = source.parent.lstat()
            target_parent_metadata = target.parent.lstat()
        except OSError as error:
            raise LocalAgentError("workspace_parent_unavailable") from error
        if any(
            _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode)
            for metadata in (source_parent_metadata, target_parent_metadata)
        ):
            raise LocalAgentError("workspace_parent_unavailable")
        try:
            source_metadata = source.lstat()
        except FileNotFoundError as error:
            raise LocalAgentError("workspace_path_not_found") from error
        except OSError as error:
            raise LocalAgentError("workspace_directory_unavailable") from error
        if _is_link_or_reparse(source_metadata) or not stat.S_ISDIR(source_metadata.st_mode):
            raise LocalAgentError("workspace_not_a_directory")
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise LocalAgentError("workspace_item_unavailable") from error
        else:
            raise LocalAgentError("workspace_lifecycle_target_exists")
        return PreparedDirectoryMove(
            source_path=canonical_source,
            target_path=canonical_target,
            source_identity=self._identity(source_metadata),
            source_parent_identity=self._identity(source_parent_metadata),
            target_parent_identity=self._identity(target_parent_metadata),
        )

    @staticmethod
    def _open_directory_move_source(source: Path, parent_descriptor: int) -> int:
        if os.name == "nt":
            from .local_workspace_windows import open_move_directory_source_descriptor

            return open_move_directory_source_descriptor(source)
        return os.open(
            source.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )

    def _published_directory_move_verified(
        self,
        prepared: PreparedDirectoryMove,
        source: Path,
        target: Path,
        source_descriptor: int,
        source_parent_descriptor: int,
        target_parent_descriptor: int,
    ) -> bool:
        for _attempt in range(4):
            try:
                descriptor_metadata = os.fstat(source_descriptor)
                source_after = self._move_entry_metadata(source, source_parent_descriptor)
                target_after = self._move_entry_metadata(target, target_parent_descriptor)
                verified = (
                    source_after is None
                    and target_after is not None
                    and self._identity(descriptor_metadata) == prepared.source_identity
                    and self._identity(target_after) == prepared.source_identity
                    and not _is_link_or_reparse(descriptor_metadata)
                    and not _is_link_or_reparse(target_after)
                    and stat.S_ISDIR(descriptor_metadata.st_mode)
                    and stat.S_ISDIR(target_after.st_mode)
                )
            except (OSError, LocalAgentError):
                verified = False
            if verified:
                return True
        return False

    def _rollback_prepared_directory_move(
        self,
        prepared: PreparedDirectoryMove,
        source: Path,
        target: Path,
        source_descriptor: int,
        source_parent_descriptor: int,
        target_parent_descriptor: int,
    ) -> bool:
        try:
            descriptor_metadata = os.fstat(source_descriptor)
            source_before = self._move_entry_metadata(source, source_parent_descriptor)
            target_before = self._move_entry_metadata(target, target_parent_descriptor)
            if not (
                source_before is None
                and target_before is not None
                and self._identity(descriptor_metadata) == prepared.source_identity
                and self._identity(target_before) == prepared.source_identity
                and not _is_link_or_reparse(descriptor_metadata)
                and not _is_link_or_reparse(target_before)
                and stat.S_ISDIR(descriptor_metadata.st_mode)
                and stat.S_ISDIR(target_before.st_mode)
            ):
                return False
            self._rename_move_no_replace(
                source_descriptor,
                target_parent_descriptor,
                target.name,
                source_parent_descriptor,
                source.name,
                windows_target=source,
            )
            if os.name != "nt":
                os.fsync(source_parent_descriptor)
                if source_parent_descriptor != target_parent_descriptor:
                    os.fsync(target_parent_descriptor)
            for _attempt in range(4):
                descriptor_after = os.fstat(source_descriptor)
                source_after = self._move_entry_metadata(source, source_parent_descriptor)
                target_after = self._move_entry_metadata(target, target_parent_descriptor)
                if (
                    source_after is not None
                    and target_after is None
                    and self._identity(descriptor_after) == prepared.source_identity
                    and self._identity(source_after) == prepared.source_identity
                    and not _is_link_or_reparse(descriptor_after)
                    and not _is_link_or_reparse(source_after)
                    and stat.S_ISDIR(descriptor_after.st_mode)
                    and stat.S_ISDIR(source_after.st_mode)
                ):
                    return True
        except (OSError, LocalAgentError):
            pass
        return False

    def apply_prepared_directory_move(
        self,
        prepared: PreparedDirectoryMove,
    ) -> PreparedDirectoryMoveOutcome:
        """Move one bound directory entry without overwrite or content claims."""

        source, target, canonical_source, canonical_target = (
            self._directory_move_candidates(prepared.source_path, prepared.target_path)
        )
        if (
            canonical_source != prepared.source_path
            or canonical_target != prepared.target_path
        ):
            return PreparedDirectoryMoveOutcome(
                "rejected", "workspace_lifecycle_preview_mismatch"
            )
        source_descriptor: int | None = None
        published = False
        outcome: PreparedDirectoryMoveOutcome | None = None
        with _REVIEWED_WRITE_LOCK, self._write_lock:
            try:
                with self._inspection._directory_pair(
                    source.parent,
                    target.parent,
                    check_workspace_cancellation,
                    mutation=True,
                ) as (source_parent_descriptor, target_parent_descriptor):
                    if (
                        self._identity(os.fstat(source_parent_descriptor))
                        != prepared.source_parent_identity
                        or self._identity(os.fstat(target_parent_descriptor))
                        != prepared.target_parent_identity
                    ):
                        outcome = PreparedDirectoryMoveOutcome(
                            "rejected", "workspace_revision_changed"
                        )
                    if outcome is None:
                        try:
                            source_descriptor = self._open_directory_move_source(
                                source, source_parent_descriptor
                            )
                            descriptor_metadata = os.fstat(source_descriptor)
                        except (FileNotFoundError, OSError, LocalAgentError):
                            outcome = PreparedDirectoryMoveOutcome(
                                "rejected", "workspace_revision_changed"
                            )
                    if outcome is None:
                        source_metadata = self._move_entry_metadata(
                            source, source_parent_descriptor
                        )
                        if not (
                            source_metadata is not None
                            and self._identity(source_metadata) == prepared.source_identity
                            and self._identity(descriptor_metadata) == prepared.source_identity
                            and not _is_link_or_reparse(source_metadata)
                            and not _is_link_or_reparse(descriptor_metadata)
                            and stat.S_ISDIR(source_metadata.st_mode)
                            and stat.S_ISDIR(descriptor_metadata.st_mode)
                        ):
                            outcome = PreparedDirectoryMoveOutcome(
                                "rejected", "workspace_revision_changed"
                            )
                    if (
                        outcome is None
                        and self._move_entry_metadata(target, target_parent_descriptor)
                        is not None
                    ):
                        outcome = PreparedDirectoryMoveOutcome(
                            "rejected", "workspace_lifecycle_target_exists"
                        )
                    if outcome is None:
                        check_workspace_cancellation()
                        assert source_descriptor is not None
                        try:
                            self._rename_move_no_replace(
                                source_descriptor,
                                source_parent_descriptor,
                                source.name,
                                target_parent_descriptor,
                                target.name,
                                windows_target=target,
                            )
                            published = True
                        except FileExistsError:
                            outcome = PreparedDirectoryMoveOutcome(
                                "rejected", "workspace_lifecycle_target_exists"
                            )
                        except OSError as error:
                            code = (
                                "workspace_directory_move_unsupported"
                                if getattr(error, "errno", None) == errno.ENOTSUP
                                else "workspace_directory_move_failed"
                            )
                            outcome = PreparedDirectoryMoveOutcome("rejected", code)
                    if published and outcome is None:
                        assert source_descriptor is not None
                        with runtime_critical_cleanup_scope():
                            verified = self._published_directory_move_verified(
                                prepared,
                                source,
                                target,
                                source_descriptor,
                                source_parent_descriptor,
                                target_parent_descriptor,
                            )
                            if verified and os.name != "nt":
                                try:
                                    os.fsync(target_parent_descriptor)
                                    if source_parent_descriptor != target_parent_descriptor:
                                        os.fsync(source_parent_descriptor)
                                except OSError:
                                    verified = False
                            if verified:
                                outcome = PreparedDirectoryMoveOutcome("verified", None)
                            elif self._rollback_prepared_directory_move(
                                prepared,
                                source,
                                target,
                                source_descriptor,
                                source_parent_descriptor,
                                target_parent_descriptor,
                            ):
                                outcome = PreparedDirectoryMoveOutcome(
                                    "rejected", "workspace_revision_changed"
                                )
                            else:
                                outcome = PreparedDirectoryMoveOutcome(
                                    "unverified", "workspace_directory_move_unverified"
                                )
            except RuntimeCooperativeStop:
                outcome = PreparedDirectoryMoveOutcome(
                    "unverified" if published else "rejected",
                    "workspace_directory_move_unverified"
                    if published
                    else "tool_cancelled",
                )
            except (OSError, LocalAgentError):
                outcome = PreparedDirectoryMoveOutcome(
                    "unverified" if published else "rejected",
                    "workspace_directory_move_unverified"
                    if published
                    else "workspace_directory_move_failed",
                )
            finally:
                if source_descriptor is not None:
                    try:
                        os.close(source_descriptor)
                    except OSError:
                        if published:
                            outcome = PreparedDirectoryMoveOutcome(
                                "unverified", "workspace_directory_move_unverified"
                            )
        return outcome or PreparedDirectoryMoveOutcome(
            "rejected", "workspace_directory_move_failed"
        )

    def prepare_file_trash(self, path: str) -> PreparedFileTrash:
        """Bind one regular UTF-8 file for recoverable Windows removal."""

        if os.name != "nt":
            raise LocalAgentError("workspace_file_trash_unsupported")
        source = self._lexical_candidate(path)
        if source == self.root:
            raise LocalAgentError("path_invalid")
        if len(source.drive) != 2 or source.drive[1] != ":":
            raise LocalAgentError("workspace_file_trash_unsupported")
        if not _path_components_are_safe(source.parent):
            raise LocalAgentError("workspace_link_or_reparse_refused")
        try:
            parent_metadata = source.parent.lstat()
        except OSError as error:
            raise LocalAgentError("workspace_parent_unavailable") from error
        if _is_link_or_reparse(parent_metadata) or not stat.S_ISDIR(parent_metadata.st_mode):
            raise LocalAgentError("workspace_parent_unavailable")
        snapshot = self._snapshot_file(source)
        if snapshot is None:
            raise LocalAgentError("workspace_path_not_found")
        payload, metadata = snapshot
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise LocalAgentError("workspace_binary_refused") from error
        if "\x00" in text:
            raise LocalAgentError("workspace_binary_refused")
        return PreparedFileTrash(
            path=source.relative_to(self.root).as_posix(),
            source_sha256=hashlib.sha256(payload).hexdigest(),
            source_identity=self._identity(metadata),
            parent_identity=self._identity(parent_metadata),
            byte_size=len(payload),
            mode=stat.S_IMODE(metadata.st_mode),
        )

    def _rollback_prepared_file_trash(
        self,
        prepared: PreparedFileTrash,
        source: Path,
        staged: Path,
        source_descriptor: int,
        parent_descriptor: int,
    ) -> bool:
        try:
            payload, descriptor_metadata = self._read_open_descriptor(
                source_descriptor,
                check=lambda: None,
            )
            source_metadata = self._move_entry_metadata(source, parent_descriptor)
            staged_metadata = self._move_entry_metadata(staged, parent_descriptor)
            if not (
                source_metadata is None
                and staged_metadata is not None
                and self._identity(staged_metadata) == prepared.source_identity
                and self._identity(descriptor_metadata) == prepared.source_identity
                and hashlib.sha256(payload).hexdigest() == prepared.source_sha256
                and len(payload) == prepared.byte_size
                and stat.S_IMODE(descriptor_metadata.st_mode) == prepared.mode
            ):
                return False
            self._rename_move_no_replace(
                source_descriptor,
                parent_descriptor,
                staged.name,
                parent_descriptor,
                source.name,
                windows_target=source,
            )
            restored_payload, restored_descriptor = self._read_open_descriptor(
                source_descriptor,
                check=lambda: None,
            )
            restored_path = self._move_entry_metadata(source, parent_descriptor)
            staged_after = self._move_entry_metadata(staged, parent_descriptor)
            return bool(
                restored_path is not None
                and staged_after is None
                and self._identity(restored_path) == prepared.source_identity
                and self._identity(restored_descriptor) == prepared.source_identity
                and hashlib.sha256(restored_payload).hexdigest() == prepared.source_sha256
                and len(restored_payload) == prepared.byte_size
                and stat.S_IMODE(restored_descriptor.st_mode) == prepared.mode
            )
        except (OSError, LocalAgentError):
            return False

    def apply_prepared_file_trash(
        self,
        prepared: PreparedFileTrash,
    ) -> PreparedFileTrashOutcome:
        """Move one exact reviewed file to the Windows Recycle Bin or fail closed."""

        if os.name != "nt":
            return PreparedFileTrashOutcome(
                "rejected", "workspace_file_trash_unsupported", None, None
            )
        source = self._lexical_candidate(prepared.path)
        if source == self.root or source.relative_to(self.root).as_posix() != prepared.path:
            return PreparedFileTrashOutcome(
                "rejected", "workspace_lifecycle_preview_mismatch", None, None
            )
        source_descriptor: int | None = None
        staged: Path | None = None
        staged_publication = False
        outcome: PreparedFileTrashOutcome | None = None
        with _REVIEWED_WRITE_LOCK, self._write_lock:
            try:
                with self._inspection._directory(
                    source.parent,
                    check_workspace_cancellation,
                    mutation=True,
                ) as parent_descriptor:
                    if self._identity(os.fstat(parent_descriptor)) != prepared.parent_identity:
                        outcome = PreparedFileTrashOutcome(
                            "rejected", "workspace_revision_changed", None, None
                        )
                    if outcome is None:
                        from .local_workspace_windows import open_trash_source_descriptor

                        try:
                            source_descriptor = open_trash_source_descriptor(source)
                            payload, descriptor_metadata = self._read_open_descriptor(
                                source_descriptor
                            )
                        except (OSError, LocalAgentError):
                            outcome = PreparedFileTrashOutcome(
                                "rejected", "workspace_revision_changed", None, None
                            )
                    if outcome is None:
                        source_metadata = self._move_entry_metadata(source, parent_descriptor)
                        if not (
                            source_metadata is not None
                            and self._identity(source_metadata) == prepared.source_identity
                            and self._identity(descriptor_metadata) == prepared.source_identity
                            and hashlib.sha256(payload).hexdigest() == prepared.source_sha256
                            and len(payload) == prepared.byte_size
                            and stat.S_IMODE(descriptor_metadata.st_mode) == prepared.mode
                        ):
                            outcome = PreparedFileTrashOutcome(
                                "rejected", "workspace_revision_changed", None, None
                            )
                    if outcome is None:
                        assert source_descriptor is not None
                        for _attempt in range(8):
                            candidate = self._private_stage_path(source.parent, "trash")
                            if self._move_entry_metadata(candidate, parent_descriptor) is None:
                                staged = candidate
                                break
                        if staged is None:
                            outcome = PreparedFileTrashOutcome(
                                "rejected", "workspace_file_trash_failed", None, None
                            )
                    if outcome is None:
                        check_workspace_cancellation()
                        assert source_descriptor is not None and staged is not None
                        try:
                            self._rename_move_no_replace(
                                source_descriptor,
                                parent_descriptor,
                                source.name,
                                parent_descriptor,
                                staged.name,
                                windows_target=staged,
                            )
                            staged_publication = True
                        except OSError:
                            outcome = PreparedFileTrashOutcome(
                                "rejected", "workspace_file_trash_failed", None, None
                            )
                    if staged_publication and outcome is None:
                        assert source_descriptor is not None and staged is not None
                        with runtime_critical_cleanup_scope():
                            staged_metadata = self._move_entry_metadata(staged, parent_descriptor)
                            source_metadata = self._move_entry_metadata(source, parent_descriptor)
                            if not (
                                source_metadata is None
                                and staged_metadata is not None
                                and self._identity(staged_metadata) == prepared.source_identity
                            ):
                                outcome = PreparedFileTrashOutcome(
                                    "unverified", "workspace_file_trash_unverified", None, None
                                )
                            if outcome is None:
                                from .local_workspace_windows import (
                                    RecycleOperationUnverified,
                                    recycle_path,
                                )

                                try:
                                    recycle_path(staged)
                                except RecycleOperationUnverified:
                                    outcome = PreparedFileTrashOutcome(
                                        "unverified",
                                        "workspace_file_trash_unverified",
                                        None,
                                        None,
                                    )
                                except OSError:
                                    if self._rollback_prepared_file_trash(
                                        prepared,
                                        source,
                                        staged,
                                        source_descriptor,
                                        parent_descriptor,
                                    ):
                                        outcome = PreparedFileTrashOutcome(
                                            "rejected", "workspace_file_trash_failed", None, None
                                        )
                                    else:
                                        outcome = PreparedFileTrashOutcome(
                                            "unverified", "workspace_file_trash_unverified", None, None
                                        )
                            if outcome is None:
                                from .local_workspace_windows import (
                                    descriptor_is_in_recycle_bin,
                                )

                                try:
                                    recycled_payload, recycled_metadata = self._read_open_descriptor(
                                        source_descriptor,
                                        check=lambda: None,
                                    )
                                    recycled = (
                                        self._move_entry_metadata(source, parent_descriptor) is None
                                        and self._move_entry_metadata(staged, parent_descriptor) is None
                                        and self._identity(recycled_metadata) == prepared.source_identity
                                        and hashlib.sha256(recycled_payload).hexdigest()
                                        == prepared.source_sha256
                                        and len(recycled_payload) == prepared.byte_size
                                        and stat.S_IMODE(recycled_metadata.st_mode)
                                        == prepared.mode
                                        and descriptor_is_in_recycle_bin(
                                            source_descriptor, source
                                        )
                                    )
                                except (OSError, LocalAgentError):
                                    recycled = False
                                if recycled:
                                    outcome = PreparedFileTrashOutcome(
                                        "verified",
                                        None,
                                        prepared.source_sha256,
                                        prepared.byte_size,
                                    )
                                elif self._rollback_prepared_file_trash(
                                    prepared,
                                    source,
                                    staged,
                                    source_descriptor,
                                    parent_descriptor,
                                ):
                                    outcome = PreparedFileTrashOutcome(
                                        "rejected", "workspace_file_trash_failed", None, None
                                    )
                                else:
                                    outcome = PreparedFileTrashOutcome(
                                        "unverified", "workspace_file_trash_unverified", None, None
                                    )
            except RuntimeCooperativeStop:
                outcome = PreparedFileTrashOutcome(
                    "unverified" if staged_publication else "rejected",
                    "workspace_file_trash_unverified"
                    if staged_publication
                    else "tool_cancelled",
                    None,
                    None,
                )
            except (OSError, LocalAgentError):
                outcome = PreparedFileTrashOutcome(
                    "unverified" if staged_publication else "rejected",
                    "workspace_file_trash_unverified"
                    if staged_publication
                    else "workspace_file_trash_failed",
                    None,
                    None,
                )
            finally:
                if source_descriptor is not None:
                    try:
                        os.close(source_descriptor)
                    except OSError:
                        if staged_publication:
                            outcome = PreparedFileTrashOutcome(
                                "unverified", "workspace_file_trash_unverified", None, None
                            )
        return outcome or PreparedFileTrashOutcome(
            "rejected", "workspace_file_trash_failed", None, None
        )

    def prepare_move(self, source_path: str, target_path: str) -> PreparedMove:
        """Prepare one existing regular text file for a reviewed no-overwrite move."""

        source = self._lexical_candidate(source_path)
        target = self._lexical_candidate(target_path)
        if source == self.root or target == self.root:
            raise LocalAgentError("path_invalid")
        canonical_source = source.relative_to(self.root).as_posix()
        canonical_target = target.relative_to(self.root).as_posix()
        if canonical_source == canonical_target or (
            os.name == "nt" and canonical_source.casefold() == canonical_target.casefold()
        ):
            raise LocalAgentError("workspace_lifecycle_same_path")
        for parent in (source.parent, target.parent):
            if not _path_components_are_safe(parent):
                raise LocalAgentError("workspace_link_or_reparse_refused")
        try:
            source_parent_metadata = source.parent.lstat()
            target_parent_metadata = target.parent.lstat()
        except OSError as error:
            raise LocalAgentError("workspace_parent_unavailable") from error
        if any(
            _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode)
            for metadata in (source_parent_metadata, target_parent_metadata)
        ):
            raise LocalAgentError("workspace_parent_unavailable")
        snapshot = self._snapshot_file(source)
        if snapshot is None:
            raise LocalAgentError("workspace_path_not_found")
        payload, metadata = snapshot
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise LocalAgentError("workspace_binary_refused") from error
        if "\x00" in text:
            raise LocalAgentError("workspace_binary_refused")
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise LocalAgentError("workspace_file_unavailable") from error
        else:
            raise LocalAgentError("workspace_lifecycle_target_exists")
        return PreparedMove(
            source_path=canonical_source,
            target_path=canonical_target,
            source_sha256=hashlib.sha256(payload).hexdigest(),
            source_identity=self._identity(metadata),
            source_parent_identity=self._identity(source_parent_metadata),
            target_parent_identity=self._identity(target_parent_metadata),
            byte_size=len(payload),
            mode=stat.S_IMODE(metadata.st_mode),
        )

    def _rollback_prepared_move(
        self,
        prepared: PreparedMove,
        source: Path,
        target: Path,
        source_descriptor: int | None,
        source_parent_descriptor: int,
        target_parent_descriptor: int,
    ) -> bool:
        rollback_descriptor = source_descriptor
        owns_rollback_descriptor = False
        rollback_close_failed = False
        restored_verified = False
        try:
            if os.name == "nt":
                if rollback_descriptor is not None:
                    return False
                from .local_workspace_windows import open_move_source_descriptor

                rollback_descriptor = open_move_source_descriptor(target)
                owns_rollback_descriptor = True
            assert rollback_descriptor is not None
            payload, descriptor_metadata = self._read_open_descriptor(
                rollback_descriptor,
                check=lambda: None,
            )
            source_metadata = self._move_entry_metadata(source, source_parent_descriptor)
            target_metadata = self._move_entry_metadata(target, target_parent_descriptor)
            if (
                source_metadata is not None
                or target_metadata is None
                or self._identity(target_metadata) != prepared.source_identity
                or self._identity(descriptor_metadata) != prepared.source_identity
                or hashlib.sha256(payload).hexdigest() != prepared.source_sha256
                or len(payload) != prepared.byte_size
                or stat.S_IMODE(descriptor_metadata.st_mode) != prepared.mode
            ):
                return False
            self._rename_move_no_replace(
                rollback_descriptor,
                target_parent_descriptor,
                target.name,
                source_parent_descriptor,
                source.name,
                windows_target=source,
            )
            if os.name != "nt":
                os.fsync(source_parent_descriptor)
                if source_parent_descriptor != target_parent_descriptor:
                    os.fsync(target_parent_descriptor)
            for _attempt in range(4):
                restored_payload, restored_descriptor_metadata = self._read_open_descriptor(
                    rollback_descriptor,
                    check=lambda: None,
                )
                restored = self._move_entry_metadata(source, source_parent_descriptor)
                displaced = self._move_entry_metadata(target, target_parent_descriptor)
                restored_verified = (
                    restored is not None
                    and displaced is None
                    and self._identity(restored) == prepared.source_identity
                    and self._identity(restored_descriptor_metadata)
                    == prepared.source_identity
                    and not _is_link_or_reparse(restored)
                    and stat.S_ISREG(restored.st_mode)
                    and restored.st_nlink == 1
                    and restored.st_size == prepared.byte_size
                    and restored_descriptor_metadata.st_size == prepared.byte_size
                    and stat.S_IMODE(restored.st_mode) == prepared.mode
                    and hashlib.sha256(restored_payload).hexdigest()
                    == prepared.source_sha256
                    and len(restored_payload) == prepared.byte_size
                )
                if restored_verified:
                    break
        except (OSError, LocalAgentError):
            return False
        finally:
            if owns_rollback_descriptor and rollback_descriptor is not None:
                try:
                    os.close(rollback_descriptor)
                except OSError:
                    rollback_close_failed = True
        if rollback_close_failed:
            return False
        return restored_verified

    def _published_move_verified(
        self,
        prepared: PreparedMove,
        source: Path,
        target: Path,
        source_descriptor: int,
        source_parent_descriptor: int,
        target_parent_descriptor: int,
    ) -> bool:
        """Verify exact post-publication authority with bounded strict retries."""

        for _attempt in range(4):
            try:
                moved_payload, moved_metadata = self._read_open_descriptor(
                    source_descriptor,
                    check=lambda: None,
                )
                source_after = self._move_entry_metadata(source, source_parent_descriptor)
                target_after = self._move_entry_metadata(target, target_parent_descriptor)
                verified = (
                    source_after is None
                    and target_after is not None
                    and self._identity(target_after) == prepared.source_identity
                    and self._identity(moved_metadata) == prepared.source_identity
                    and not _is_link_or_reparse(target_after)
                    and stat.S_ISREG(target_after.st_mode)
                    and target_after.st_nlink == 1
                    and target_after.st_size == prepared.byte_size
                    and moved_metadata.st_size == prepared.byte_size
                    and stat.S_IMODE(target_after.st_mode) == prepared.mode
                    and hashlib.sha256(moved_payload).hexdigest()
                    == prepared.source_sha256
                    and len(moved_payload) == prepared.byte_size
                )
            except (OSError, LocalAgentError):
                verified = False
            if verified:
                return True
        return False

    def apply_prepared_move(self, prepared: PreparedMove) -> PreparedMoveOutcome:
        """Publish and verify a reviewed move, rolling back before claiming rejection."""

        source = self._lexical_candidate(prepared.source_path)
        target = self._lexical_candidate(prepared.target_path)
        source_descriptor: int | None = None
        published = False
        with _REVIEWED_WRITE_LOCK, self._write_lock:
            try:
                with self._inspection._directory_pair(
                    source.parent,
                    target.parent,
                    check_workspace_cancellation,
                    mutation=True,
                ) as (source_parent_descriptor, target_parent_descriptor):
                        if (
                            self._identity(os.fstat(source_parent_descriptor))
                            != prepared.source_parent_identity
                            or self._identity(os.fstat(target_parent_descriptor))
                            != prepared.target_parent_identity
                        ):
                            return PreparedMoveOutcome(
                                "rejected", "workspace_revision_changed", None, None
                            )
                        try:
                            if os.name == "nt":
                                from .local_workspace_windows import open_move_source_descriptor

                                source_descriptor = open_move_source_descriptor(source)
                            else:
                                source_descriptor = os.open(
                                    source.name,
                                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                    dir_fd=source_parent_descriptor,
                                )
                                try:
                                    import fcntl

                                    fcntl.flock(source_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                except (ImportError, BlockingIOError, OSError) as error:
                                    raise LocalAgentError("workspace_file_changed") from error
                            payload, metadata = self._read_open_descriptor(source_descriptor)
                        except (FileNotFoundError, OSError, LocalAgentError):
                            return PreparedMoveOutcome(
                                "rejected", "workspace_revision_changed", None, None
                            )
                        source_metadata = self._move_entry_metadata(
                            source, source_parent_descriptor
                        )
                        if (
                            source_metadata is None
                            or self._metadata_revision(source_metadata)
                            != self._metadata_revision(metadata)
                            or self._identity(metadata) != prepared.source_identity
                            or hashlib.sha256(payload).hexdigest()
                            != prepared.source_sha256
                            or len(payload) != prepared.byte_size
                            or stat.S_IMODE(metadata.st_mode) != prepared.mode
                        ):
                            return PreparedMoveOutcome(
                                "rejected", "workspace_revision_changed", None, None
                            )
                        if self._move_entry_metadata(target, target_parent_descriptor) is not None:
                            return PreparedMoveOutcome(
                                "rejected", "workspace_lifecycle_target_exists", None, None
                            )
                        check_workspace_cancellation()
                        try:
                            self._rename_move_no_replace(
                                source_descriptor,
                                source_parent_descriptor,
                                source.name,
                                target_parent_descriptor,
                                target.name,
                                windows_target=target,
                            )
                            published = True
                        except FileExistsError:
                            return PreparedMoveOutcome(
                                "rejected", "workspace_lifecycle_target_exists", None, None
                            )
                        except OSError as error:
                            code = (
                                "workspace_move_unsupported"
                                if getattr(error, "errno", None) == errno.ENOTSUP
                                else "workspace_move_failed"
                            )
                            return PreparedMoveOutcome("rejected", code, None, None)

                        with runtime_critical_cleanup_scope():
                            verified = self._published_move_verified(
                                prepared,
                                source,
                                target,
                                source_descriptor,
                                source_parent_descriptor,
                                target_parent_descriptor,
                            )
                            if verified and os.name != "nt":
                                try:
                                    os.fsync(target_parent_descriptor)
                                    if source_parent_descriptor != target_parent_descriptor:
                                        os.fsync(source_parent_descriptor)
                                except OSError:
                                    return PreparedMoveOutcome(
                                        "unverified", "workspace_move_unverified", None, None
                                    )
                            if verified:
                                try:
                                    os.close(source_descriptor)
                                    source_descriptor = None
                                except OSError:
                                    return PreparedMoveOutcome(
                                        "unverified", "workspace_move_unverified", None, None
                                    )
                                return PreparedMoveOutcome(
                                    "verified",
                                    None,
                                    prepared.source_sha256,
                                    prepared.byte_size,
                                )
                            rollback_descriptor = source_descriptor
                            if os.name == "nt":
                                try:
                                    os.close(source_descriptor)
                                    source_descriptor = None
                                    rollback_descriptor = None
                                except OSError:
                                    return PreparedMoveOutcome(
                                        "unverified", "workspace_move_unverified", None, None
                                    )
                            if self._rollback_prepared_move(
                                prepared,
                                source,
                                target,
                                rollback_descriptor,
                                source_parent_descriptor,
                                target_parent_descriptor,
                            ):
                                return PreparedMoveOutcome(
                                    "rejected", "workspace_revision_changed", None, None
                                )
                            return PreparedMoveOutcome(
                                "unverified", "workspace_move_unverified", None, None
                            )
            except RuntimeCooperativeStop:
                if published:
                    return PreparedMoveOutcome(
                        "unverified", "workspace_move_unverified", None, None
                    )
                raise
            finally:
                if source_descriptor is not None:
                    try:
                        os.close(source_descriptor)
                    except OSError:
                        if published:
                            return PreparedMoveOutcome(
                                "unverified", "workspace_move_unverified", None, None
                            )

    def prepare_write(self, path: str, content: str) -> PreparedWrite:
        try:
            proposed = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise LocalAgentError("workspace_text_invalid") from error
        if len(proposed) > MAX_FILE_WRITE_BYTES:
            raise LocalAgentError("workspace_file_too_large")
        if b"\x00" in proposed:
            raise LocalAgentError("workspace_binary_refused")
        target = self._lexical_candidate(path)
        parent = target.parent
        if not _path_components_are_safe(parent):
            raise LocalAgentError("workspace_link_or_reparse_refused")
        try:
            parent_metadata = parent.lstat()
        except OSError as error:
            raise LocalAgentError("workspace_parent_unavailable") from error
        if _is_link_or_reparse(parent_metadata) or not stat.S_ISDIR(parent_metadata.st_mode):
            raise LocalAgentError("workspace_parent_unavailable")
        snapshot = self._snapshot_file(target)
        if snapshot is not None and os.name == "nt" and not snapshot[1].st_mode & stat.S_IWRITE:
            raise LocalAgentError("workspace_file_unavailable")
        before_bytes = snapshot[0] if snapshot is not None else b""
        try:
            before_text = before_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise LocalAgentError("workspace_binary_refused") from error
        if "\x00" in before_text:
            raise LocalAgentError("workspace_binary_refused")
        canonical_path = target.relative_to(self.root).as_posix()
        diff = difflib.unified_diff(
            before_text.split("\n"),
            content.split("\n"),
            fromfile=f"a/{canonical_path}",
            tofile=f"b/{canonical_path}",
            lineterm="",
            n=2,
        )
        text = "\n".join(diff)
        if not text:
            text = (
                "(no change)"
                if snapshot is not None
                else f"(new file, {len(content.splitlines())} lines)"
            )
        if len(text) > MAX_DIFF_CHARS:
            raise LocalAgentError("change_too_large_to_review")
        return PreparedWrite(
            path=target.relative_to(self.root).as_posix(),
            content=content,
            preview=text,
            base_sha256=(hashlib.sha256(before_bytes).hexdigest() if snapshot else None),
            base_identity=(self._identity(snapshot[1]) if snapshot else None),
            parent_identity=self._identity(parent_metadata),
            proposed_sha256=hashlib.sha256(proposed).hexdigest(),
            existed=snapshot is not None,
            mode=(stat.S_IMODE(snapshot[1].st_mode) if snapshot else None),
            base_content=before_text if snapshot is not None else None,
            base_byte_size=len(before_bytes) if snapshot is not None else 0,
        )

    def diff_preview(self, path: str, content: str) -> str:
        return self.prepare_write(path, content).preview

    def apply_prepared_write(self, prepared: PreparedWrite) -> ToolOutcome:
        target = self._lexical_candidate(prepared.path)
        try:
            proposed = prepared.content.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return ToolOutcome(False, "change is not valid UTF-8 text", "workspace_text_invalid")
        if hashlib.sha256(proposed).hexdigest() != prepared.proposed_sha256:
            return ToolOutcome(
                False,
                "change no longer matches its reviewed preview",
                "workspace_preview_mismatch",
            )

        before_text = "" if prepared.base_sha256 is None else None
        # Windows read handles intentionally deny concurrent mutation of a
        # traversed parent. Serialize this receipt-only read with publication
        # so two independently reviewed sessions cannot transiently block each
        # other's mutation handle before stale-revision arbitration begins.
        with _REVIEWED_WRITE_LOCK:
            try:
                snapshot = self._snapshot_file(target) if prepared.existed else None
                if snapshot is not None and hashlib.sha256(snapshot[0]).hexdigest() == prepared.base_sha256:
                    before_text = snapshot[0].decode("utf-8", errors="strict")
            except (OSError, LocalAgentError, UnicodeDecodeError):
                pass
        additions = removals = 0
        if before_text is not None:
            for operation, left_start, left_end, right_start, right_end in difflib.SequenceMatcher(
                a=before_text.splitlines(keepends=True),
                b=prepared.content.splitlines(keepends=True),
                autojunk=True,
            ).get_opcodes():
                if operation in {"replace", "insert"}:
                    additions += right_end - right_start
                if operation in {"replace", "delete"}:
                    removals += left_end - left_start

        def receipt(verified: bool) -> AgentWriteReceipt:
            return AgentWriteReceipt(
                path=prepared.path,
                state="verified" if verified else "unverified",
                before_sha256=prepared.base_sha256,
                after_sha256=prepared.proposed_sha256 if verified else None,
                operation=(
                    "created"
                    if not prepared.existed
                    else "unchanged"
                    if prepared.base_sha256 == prepared.proposed_sha256
                    else "modified"
                )
                if verified
                else None,
                added_lines=additions if verified and before_text is not None else None,
                removed_lines=removals if verified and before_text is not None else None,
                byte_size=len(proposed) if verified else None,
            )

        def reviewed_revision_changed() -> bool:
            """Re-observe authority after a failed publication start.

            Windows can surface a transient OS error instead of the more
            specific stale-revision branch when two already-reviewed writes
            race. Only classify the failure as stale when a fresh no-follow
            observation proves that the reviewed parent or file identity no
            longer matches; an unreadable state remains a closed generic
            failure.
            """

            try:
                parent_metadata = target.parent.lstat()
                if self._identity(parent_metadata) != prepared.parent_identity:
                    return True
                snapshot = self._snapshot_file(target, check=lambda: None)
            except (OSError, LocalAgentError):
                return False
            if prepared.existed:
                return (
                    snapshot is None
                    or self._identity(snapshot[1]) != prepared.base_identity
                    or hashlib.sha256(snapshot[0]).hexdigest()
                    != prepared.base_sha256
                )
            return snapshot is not None

        publication_identity: tuple[int, int] | None = None
        with _REVIEWED_WRITE_LOCK, self._write_lock:
            try:
                result = (
                    self._apply_prepared_write_windows(target, prepared, proposed)
                    if os.name == "nt"
                    else self._apply_prepared_write_posix(target, prepared, proposed)
                )
            except RuntimeCooperativeStop:
                raise
            except _WriteCleanupUnconfirmed as error:
                result = _PublicationResult(
                    "unverified" if error.publication_attempted else "rejected",
                    (
                        "publication or rollback cleanup is unconfirmed; inspect the reviewed path before continuing"
                        if error.publication_attempted
                        else "the private staging file could not be cleaned up; the reviewed path was not changed"
                    ),
                    "workspace_verification_failed" if error.publication_attempted else "workspace_cleanup_failed",
                )
            except (OSError, LocalAgentError):
                stale = reviewed_revision_changed()
                result = _PublicationResult(
                    "rejected",
                    (
                        "file changed since preview; read it again and propose a new change"
                        if stale
                        else "the reviewed write could not be started safely; the path was not changed"
                    ),
                    "workspace_revision_changed"
                    if stale
                    else "workspace_write_failed",
                )
            if (
                result.state == "rejected"
                and result.code == "workspace_write_failed"
                and reviewed_revision_changed()
            ):
                result = _PublicationResult(
                    "rejected",
                    "file changed since preview; read it again and propose a new change",
                    "workspace_revision_changed",
                )
            if result.state in {"published", "unchanged"}:
                try:
                    published = self._snapshot_file(
                        target,
                        check=lambda: None,
                    )
                except (OSError, LocalAgentError):
                    published = None
                if (
                    published is not None
                    and hashlib.sha256(published[0]).hexdigest()
                    == prepared.proposed_sha256
                ):
                    publication_identity = self._identity(published[1])
        if result.state in {"published", "unchanged"}:
            return ToolOutcome(
                True,
                result.text,
                write_receipt=receipt(True),
                publication_identity=publication_identity,
            )
        return ToolOutcome(
            False,
            result.text,
            result.code,
            write_receipt=receipt(False) if result.state == "unverified" else None,
        )

    @staticmethod
    def _same_prepared_authority(left: PreparedWrite, right: PreparedWrite) -> bool:
        return (
            left.path == right.path
            and left.content == right.content
            and left.base_sha256 == right.base_sha256
            and left.base_identity == right.base_identity
            and left.parent_identity == right.parent_identity
            and left.proposed_sha256 == right.proposed_sha256
            and left.existed is right.existed
            and left.mode == right.mode
        )

    def _prepared_observation(
        self,
        prepared: PreparedWrite,
    ) -> tuple[str, int, tuple[int, int]] | None:
        """Re-read one reviewed path without following it or exposing content."""

        try:
            snapshot = self._snapshot_file(
                self._lexical_candidate(prepared.path),
                check=lambda: None,
            )
        except (OSError, LocalAgentError):
            return None
        if snapshot is None:
            return None
        return (
            hashlib.sha256(snapshot[0]).hexdigest(),
            len(snapshot[0]),
            self._identity(snapshot[1]),
        )

    def _remove_created_transaction_write(
        self,
        reviewed: PreparedWrite,
        published_identity: tuple[int, int],
    ) -> bool:
        """Remove only the exact file created by this transaction.

        This is rollback, not general deletion authority: the reviewed member
        must have been absent at preview, and both its post-publication identity
        and bytes must still match. A replacement, link, reparse point, changed
        payload, or parent race is preserved and reported as unverified.
        """

        if (
            reviewed.existed
            or reviewed.base_sha256 is not None
            or reviewed.base_identity is not None
            or reviewed.mode is not None
        ):
            return False
        target = self._lexical_candidate(reviewed.path)
        descriptor: int | None = None
        no_cancel = lambda: None
        try:
            with self._inspection._directory(
                target.parent,
                no_cancel,
                mutation=True,
            ) as parent_descriptor:
                if self._identity(os.fstat(parent_descriptor)) != reviewed.parent_identity:
                    return False
                if os.name == "nt":
                    descriptor = self._open_windows_target(target)
                    payload, metadata = self._read_open_descriptor(
                        descriptor,
                        check=no_cancel,
                    )
                    path_metadata = self._windows_path_metadata(target)
                else:
                    descriptor = os.open(
                        target.name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                        dir_fd=parent_descriptor,
                    )
                    payload, metadata = self._read_open_descriptor(
                        descriptor,
                        check=no_cancel,
                    )
                    path_metadata = self._posix_entry_metadata(
                        parent_descriptor,
                        target.name,
                    )
                if (
                    path_metadata is None
                    or self._metadata_revision(path_metadata)
                    != self._metadata_revision(metadata)
                    or self._identity(metadata) != published_identity
                    or hashlib.sha256(payload).hexdigest()
                    != reviewed.proposed_sha256
                ):
                    return False
                if os.name == "nt":
                    self._discard_windows_descriptor(descriptor)
                    os.close(descriptor)
                    descriptor = None
                    return self._windows_path_metadata(target) is None
                os.unlink(target.name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
                return (
                    self._posix_entry_metadata(parent_descriptor, target.name)
                    is None
                )
        except (FileNotFoundError, OSError, LocalAgentError):
            return False
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def apply_prepared_transaction(
        self,
        prepared_items: tuple[PreparedWrite, ...],
    ) -> PreparedTransactionOutcome:
        """Apply reviewed creates and edits as one rollback-capable unit.

        Cross-file publication cannot be made power-loss atomic by portable
        filesystem primitives. This method instead holds the application write
        lane, preflights every member before publication, and restores already
        published members when a later member is rejected. Any external race,
        uncertain publication, or uncertain rollback becomes ``unverified``.
        """

        if not 2 <= len(prepared_items) <= MAX_WORKSPACE_TRANSACTION_FILES:
            raise LocalAgentError("workspace_transaction_invalid")
        identities = [item.path.casefold() if os.name == "nt" else item.path for item in prepared_items]
        if len(identities) != len(set(identities)):
            raise LocalAgentError("workspace_transaction_invalid")
        states: list[
            Literal[
                "committed",
                "restored",
                "removed",
                "not_applied",
                "unverified",
            ]
        ] = [
            "not_applied" for _item in prepared_items
        ]
        revisions: list[str | None] = [None for _item in prepared_items]
        byte_sizes: list[int | None] = [None for _item in prepared_items]
        published_identities: list[tuple[int, int] | None] = [
            None for _item in prepared_items
        ]

        def result(state: Literal["committed", "rejected", "rolled_back", "unverified"], reason: str | None) -> PreparedTransactionOutcome:
            return PreparedTransactionOutcome(
                state=state,
                reason=reason,
                files=tuple(
                    PreparedTransactionFileResult(
                        path=item.path,
                        state=states[index],
                        revision=revisions[index],
                        byte_size=byte_sizes[index],
                    )
                    for index, item in enumerate(prepared_items)
                ),
            )

        with _REVIEWED_WRITE_LOCK, self._write_lock:
            refreshed: list[PreparedWrite] = []
            for reviewed in prepared_items:
                try:
                    current = self.prepare_write(reviewed.path, reviewed.content)
                except (OSError, LocalAgentError):
                    raise LocalAgentError("workspace_transaction_changed") from None
                if not self._same_prepared_authority(current, reviewed):
                    raise LocalAgentError("workspace_transaction_changed")
                refreshed.append(current)

            applied: list[int] = []
            failure_reason: str | None = None
            failed_index: int | None = None
            for index, reviewed in enumerate(refreshed):
                try:
                    outcome = self.apply_prepared_write(reviewed)
                except RuntimeCooperativeStop:
                    failed_index = index
                    failure_reason = "tool_cancelled"
                    break
                receipt = outcome.write_receipt
                exact_receipt = (
                    outcome.ok
                    and receipt is not None
                    and receipt.state == "verified"
                    and receipt.path == reviewed.path
                    and receipt.before_sha256 == reviewed.base_sha256
                    and receipt.after_sha256 == reviewed.proposed_sha256
                    and receipt.operation
                    == ("modified" if reviewed.existed else "created")
                    and receipt.byte_size is not None
                    and outcome.publication_identity is not None
                )
                if exact_receipt:
                    published_identities[index] = outcome.publication_identity
                    observed = self._prepared_observation(reviewed)
                    if (
                        observed is None
                        or observed[0] != reviewed.proposed_sha256
                        or observed[1] != receipt.byte_size
                        or observed[2] != outcome.publication_identity
                    ):
                        failed_index = index
                        failure_reason = "workspace_verification_failed"
                        states[index] = "unverified"
                        break
                    states[index] = "committed"
                    revisions[index] = receipt.after_sha256
                    byte_sizes[index] = receipt.byte_size
                    applied.append(index)
                    continue
                failed_index = index
                failure_reason = outcome.code or "workspace_write_failed"
                if outcome.ok or receipt is not None:
                    states[index] = "unverified"
                    published_identities[index] = outcome.publication_identity
                break

            if failure_reason is None:
                for index, reviewed in enumerate(refreshed):
                    observed = self._prepared_observation(reviewed)
                    if (
                        observed is None
                        or observed[0] != reviewed.proposed_sha256
                        or observed[2] != published_identities[index]
                    ):
                        states[index] = "unverified"
                        revisions[index] = None
                        byte_sizes[index] = None
                        failure_reason = "workspace_verification_failed"
                    else:
                        revisions[index], byte_sizes[index] = observed[:2]
                if failure_reason is None:
                    return result("committed", None)

            rollback_candidates = list(applied)
            if failed_index is not None and states[failed_index] == "unverified":
                observed = self._prepared_observation(refreshed[failed_index])
                if (
                    observed is not None
                    and observed[0]
                    == refreshed[failed_index].proposed_sha256
                    and published_identities[failed_index] is not None
                    and observed[2] == published_identities[failed_index]
                ):
                    rollback_candidates.append(failed_index)

            for index in sorted(set(rollback_candidates), reverse=True):
                reviewed = refreshed[index]
                try:
                    with runtime_critical_cleanup_scope():
                        published_identity = published_identities[index]
                        if published_identity is None:
                            states[index] = "unverified"
                            revisions[index] = None
                            byte_sizes[index] = None
                            continue
                        if not reviewed.existed:
                            if self._remove_created_transaction_write(
                                reviewed,
                                published_identity,
                            ):
                                states[index] = "removed"
                                revisions[index] = None
                                byte_sizes[index] = None
                            else:
                                states[index] = "unverified"
                                revisions[index] = None
                                byte_sizes[index] = None
                            continue
                        rollback = self.prepare_write(reviewed.path, reviewed.base_content or "")
                        if (
                            rollback.base_sha256 != reviewed.proposed_sha256
                            or rollback.base_identity != published_identity
                            or rollback.proposed_sha256 != reviewed.base_sha256
                        ):
                            states[index] = "unverified"
                            revisions[index] = None
                            byte_sizes[index] = None
                            continue
                        restored = self.apply_prepared_write(rollback)
                except Exception:  # noqa: BLE001 - cleanup failure becomes explicit uncertainty
                    states[index] = "unverified"
                    revisions[index] = None
                    byte_sizes[index] = None
                    continue
                receipt = restored.write_receipt
                if (
                    restored.ok
                    and receipt is not None
                    and receipt.state == "verified"
                    and receipt.path == reviewed.path
                    and receipt.after_sha256 == reviewed.base_sha256
                    and receipt.byte_size == reviewed.base_byte_size
                ):
                    states[index] = "restored"
                    revisions[index] = receipt.after_sha256
                    byte_sizes[index] = receipt.byte_size
                else:
                    states[index] = "unverified"
                    revisions[index] = None
                    byte_sizes[index] = None

            if any(state == "unverified" for state in states):
                return result("unverified", "workspace_transaction_unverified")
            if any(state in {"restored", "removed"} for state in states):
                return result("rolled_back", failure_reason or "workspace_write_failed")
            return result("rejected", failure_reason or "workspace_write_failed")

    def write_file(self, path: str, content: str) -> ToolOutcome:
        return self.apply_prepared_write(self.prepare_write(path, content))

    def run_command(self, command: str, timeout_seconds: int | None = None) -> ToolOutcome:
        cancellation = current_runtime_cancellation()
        while True:
            if self.command_cleanup_unconfirmed:
                return ToolOutcome(False, "Command cleanup is unconfirmed; new commands are blocked.", "command_cleanup_unconfirmed")
            if cancellation is not None and cancellation.is_set():
                return ToolOutcome(False, "cancelled before execution", "tool_cancelled")
            if self._command_lock.acquire(timeout=0.025):
                break
        try:
            if self.command_cleanup_unconfirmed:
                return ToolOutcome(False, "Command cleanup is unconfirmed; new commands are blocked.", "command_cleanup_unconfirmed")
            if cancellation is not None and cancellation.is_set():
                return ToolOutcome(False, "cancelled before execution", "tool_cancelled")
            return self._run_command(command, timeout_seconds)
        finally:
            self._command_lock.release()

    def _run_command(self, command: str, timeout_seconds: int | None) -> ToolOutcome:
        requested = int(timeout_seconds) if timeout_seconds else self._command_timeout
        timeout = max(5, min(requested, self._command_timeout, MAX_COMMAND_SECONDS))
        if len(command) > MAX_REVIEWABLE_COMMAND_CHARS:
            return ToolOutcome(False, "command too long to review; split it into smaller commands")
        if platform.system() == "Windows":
            shell_command = ("& " + command) if command.lstrip().startswith(('"', "'")) else command
            argv = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                shell_command,
            ]
        else:
            argv = ["bash", "-c", command]
        try:
            completed = self._runner(
                argv,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                errors="replace",
                encoding="utf-8",
                env=minimal_environment(),
            )
        except RuntimeCleanupUnconfirmed:
            self._command_cleanup_unconfirmed.set()
            return ToolOutcome(False,
                "Command cleanup could not be confirmed. Further work is blocked; inspect the command processes before restarting the app. Earlier effects were not undone.",
                "command_cleanup_unconfirmed", untracked_command=True)
        except RuntimeCooperativeStop as error:
            return ToolOutcome(False, _command_text(
                "Command stopped. Earlier effects were not undone.",
                getattr(error, "stdout", ""), getattr(error, "stderr", "")),
                "tool_cancelled", untracked_command=True)
        except subprocess.TimeoutExpired as error:
            return ToolOutcome(False, _command_text(f"timed out after {timeout}s", error.stdout, error.stderr), untracked_command=True)
        except OSError as error:
            return ToolOutcome(False, f"could not start: {error.__class__.__name__}", untracked_command=True)
        cancellation = current_runtime_cancellation()
        if cancellation is not None and cancellation.is_set():
            return ToolOutcome(False, _command_text("Command stopped. Earlier effects were not undone.",
                completed.stdout, completed.stderr, truncated=getattr(completed, "output_truncated", False)),
                "tool_cancelled", untracked_command=True)
        return ToolOutcome(completed.returncode == 0,
            _command_text(f"exit {completed.returncode}", completed.stdout, completed.stderr,
                truncated=getattr(completed, "output_truncated", False)), untracked_command=True)

    def fetch_url(self, url: str) -> ToolOutcome:
        if self._fetcher is None:
            return ToolOutcome(False, "web access is not available in this session")
        try:
            return ToolOutcome(True, self._fetcher(url)[:MAX_TOOL_RESULT_CHARS])
        except Exception as error:  # noqa: BLE001 - reported to the model
            return ToolOutcome(False, f"fetch failed: {error.__class__.__name__}")


def _git_unavailable(reason: str) -> WorkspaceGitStatusSnapshot:
    return WorkspaceGitStatusSnapshot("unavailable", "unavailable", (reason,), None, ())


def _git_config_has_external_indirection(payload: str) -> bool:
    """Reject repository config that can redirect reads or launch helpers."""

    if "\0" in payload:
        return True
    section = ""
    for raw_line in payload.splitlines():
        line = raw_line.lstrip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            closing = line.find("]")
            if closing < 0:
                return True
            section = line[1:closing].strip().split(None, 1)[0].casefold().split(".", 1)[0]
            if section in {"diff", "filter", "include", "includeif", "merge"}:
                return True
            continue
        key = line.split("=", 1)[0].strip().casefold()
        if section == "core" and key == "worktree":
            return True
    return False


def _parse_git_porcelain(
    payload: str,
    normalize: Callable[[str], tuple[str | None, str | None]],
) -> tuple[tuple[WorkspaceGitChangeRecord, ...], int, set[str]]:
    """Parse Git porcelain v2 `-z` without accepting quoted or absolute paths."""

    if payload and not payload.endswith("\0"):
        raise ValueError("git_status_terminator_missing")
    records = payload.split("\0")[:-1] if payload else []
    index = 0
    total = 0
    reasons: set[str] = set()
    changes: list[WorkspaceGitChangeRecord] = []
    while index < len(records):
        record = records[index]
        index += 1
        original: str | None = None
        unmerged = False
        if record.startswith("1 "):
            fields = record.split(" ", 8)
            if len(fields) != 9:
                raise ValueError("git_status_record_invalid")
            xy, raw_path = fields[1], fields[8]
        elif record.startswith("2 "):
            fields = record.split(" ", 9)
            if len(fields) != 10 or index >= len(records):
                raise ValueError("git_status_rename_invalid")
            xy, raw_path = fields[1], fields[9]
            original = records[index]
            index += 1
        elif record.startswith("u "):
            fields = record.split(" ", 10)
            if len(fields) != 11:
                raise ValueError("git_status_unmerged_invalid")
            xy, raw_path = fields[1], fields[10]
            unmerged = True
        elif record.startswith("? "):
            xy, raw_path = "??", record[2:]
        else:
            raise ValueError("git_status_record_type_invalid")
        if len(xy) != 2:
            raise ValueError("git_status_xy_invalid")
        total += 1
        path, reason = normalize(raw_path)
        if original is not None:
            _, original_reason = normalize(original)
            reason = reason or original_reason
        if path is None or reason is not None:
            reasons.add(reason or "unrepresentable_paths")
            continue

        codes = set(xy)
        if unmerged or "U" in codes:
            kind = "conflicted"
        elif xy == "??":
            kind = "untracked"
        elif "R" in codes:
            kind = "renamed"
        elif "C" in codes:
            kind = "copied"
        elif "D" in codes:
            kind = "deleted"
        elif "A" in codes:
            kind = "added"
        elif "T" in codes:
            kind = "type_changed"
        elif "M" in codes:
            kind = "modified"
        else:
            kind = "unknown"
        if len(changes) >= MAX_GIT_STATUS_ENTRIES:
            reasons.add("display_limit")
            continue
        changes.append(WorkspaceGitChangeRecord(
            path=path,
            kind=kind,
            staged=False if xy == "??" else xy[0] not in {".", "?"},
            unstaged=False if xy == "??" else xy[1] not in {".", "?"},
        ))
    changes.sort(key=lambda item: item.path.encode("utf-8"))
    if any(left.path == right.path for left, right in zip(changes, changes[1:], strict=False)):
        raise ValueError("git_status_duplicate_path")
    return tuple(changes), total, reasons


def _check_inspection(deadline: float, code: str) -> None:
    check_workspace_cancellation()
    if time.monotonic() >= deadline:
        raise LocalAgentError(code)


def _inspection_error(error: OSError | LocalAgentError) -> ToolOutcome:
    code = error.code if isinstance(error, LocalAgentError) else (
        "workspace_path_not_found" if isinstance(error, FileNotFoundError) else "workspace_item_unavailable")
    messages = {
        "workspace_link_or_reparse_refused": "links and reparse points are not followed",
        "workspace_root_changed": "workspace root changed; start a new session after inspecting the folder",
        "workspace_file_changed": "file changed during inspection; no content returned",
        "workspace_file_too_large": "file exceeds the remaining read limit",
        "workspace_path_not_found": "workspace path is missing or excluded",
        "path_invalid": "workspace path is invalid",
        "path_outside_workspace": "path must stay inside the workspace",
        "workspace_search_timeout": "search deadline reached",
        "workspace_inspection_timeout": "inspection deadline reached",
    }
    return ToolOutcome(False, messages.get(code, "workspace item unavailable; inspection was not completed"), code)


def _inspection_result(lines: list[str], reasons: set[str], *, empty: str, code: str | None = None) -> ToolOutcome:
    body = "\n".join(lines)
    notice = "\n[Inspection incomplete: " + "; ".join(sorted(reasons)) + "]" if reasons else ""
    if len(body) + len(notice) > MAX_TOOL_RESULT_CHARS:
        reasons.add("output truncated at the display limit")
    if reasons:
        notice = "\n[Inspection incomplete: " + "; ".join(sorted(reasons)) + "]"
        return ToolOutcome(False, (body or "(no results returned)")[:MAX_TOOL_RESULT_CHARS - len(notice)] + notice,
                           code or "workspace_inspection_incomplete")
    return ToolOutcome(True, body or empty)


def _command_text(status: str, stdout: str | bytes | None, stderr: str | bytes | None, *, truncated: bool = False) -> str:
    def text(value: str | bytes | None) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""

    output = text(stdout) + ("\n[stderr]\n" + text(stderr) if stderr else "")
    prefix = status + "\n"
    if truncated or len(prefix) + len(output) > MAX_TOOL_RESULT_CHARS:
        prefix += "[Earlier command output truncated]\n"
    return (prefix + output[-max(0, MAX_TOOL_RESULT_CHARS - len(prefix)):]).strip()


__all__ = (
    "PreparedDirectoryCreate",
    "PreparedDirectoryCreateOutcome",
    "PreparedDirectoryMove",
    "PreparedDirectoryMoveOutcome",
    "PreparedFileTrash",
    "PreparedFileTrashOutcome",
    "PreparedMove",
    "PreparedMoveOutcome",
    "PreparedTransactionFileResult",
    "PreparedTransactionOutcome",
    "PreparedWrite",
    "ToolOutcome",
    "WorkspaceDiscoveredFile",
    "WorkspaceGitChangeRecord",
    "WorkspaceGitStatusSnapshot",
    "WorkspaceInventorySnapshot",
    "WorkspacePathEntry",
    "WorkspaceTextSearchMatch",
    "WorkspaceTextSearchSnapshot",
    "WorkspaceTextSnapshot",
    "WorkspaceTools",
    "minimal_environment",
    "run_with_tree_kill",
)
