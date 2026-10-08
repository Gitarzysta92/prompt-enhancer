"""Bounded, memory-only net change evidence for one local Agent session.

The tracker records only paths that pass through an approved file publication.
It retains the first reviewed baseline within a per-session byte budget and
re-reads each tracked path through the existing no-follow workspace boundary.
It is deliberately not a Git status or a whole-workspace scanner: command,
manual external, and omitted-path effects make the scoped result partial.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
import difflib
import hashlib
import os
import threading
from typing import Literal, TYPE_CHECKING

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .local_agent_limits import LocalAgentError, MAX_DIFF_CHARS, MAX_FILE_WRITE_BYTES

if TYPE_CHECKING:
    from .local_agent_editor import WorkspaceApplyResult
    from .local_agent_file_lifecycle import (
        WorkspaceCreateApplyResult,
        WorkspaceFileTrashApplyResult,
        WorkspaceMoveApplyResult,
    )
    from .local_agent_receipts import AgentWriteReceipt
    from .local_agent_workspace import PreparedWrite, WorkspaceTextSnapshot, WorkspaceTools


CHANGE_SET_CONTRACT_VERSION = "agent-change-set.v1"
CHANGE_RESTORE_CONTRACT_VERSION = "agent-change-restore.v1"
CHANGE_RESTORE_CONFIRMATION = "apply_reviewed_change_restore"
MAX_CHANGE_SET_FILES = 64
MAX_CHANGE_SET_BASELINE_BYTES = 4_000_000
MAX_MANUAL_PREVIEW_BASELINES = 16

ChangeCoverage = Literal["complete", "partial"]
ChangeNetEffect = Literal["created", "modified", "deleted", "reverted", "unknown"]
ChangeVerification = Literal["verified", "partial", "unverified", "unavailable"]
ChangeReason = Literal[
    "publication_unverified",
    "current_revision_changed",
    "review_chain_gap",
    "current_file_missing",
    "current_file_unavailable",
    "baseline_not_retained",
]
ChangeDiffState = Literal["available", "no_change", "line_ending_only", "too_large", "unavailable"]
ChangeSource = Literal["agent", "manual"]
ChangeRestoreOperation = Literal["edit", "recreate", "trash_created"]
ChangeRestoreDiffState = Literal["available", "line_ending_only", "too_large"]
ChangeRestoreRecovery = Literal["revision_bound_write", "windows_recycle_bin"]


def _relative_path(value: str) -> str:
    if (
        not value
        or len(value) > 1024
        or value in {".", ".."}
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("invalid change-set path")
    return value


class AgentChangedFile(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    net_effect: ChangeNetEffect
    verification: ChangeVerification
    reason: ChangeReason | None = None
    reviewed_writes: int = Field(strict=True, ge=1)
    agent_writes: int = Field(strict=True, ge=0)
    manual_writes: int = Field(strict=True, ge=0)
    current_byte_size: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES)
    diff_available: bool

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def coherent_file(self) -> "AgentChangedFile":
        if self.reviewed_writes != self.agent_writes + self.manual_writes:
            raise ValueError("change-set write sources do not add up")
        if (self.verification == "verified") is not (self.reason is None):
            raise ValueError("change-set verification reason is incoherent")
        expected_reason = {
            "unverified": "publication_unverified",
            "unavailable": "current_file_unavailable",
        }.get(self.verification)
        if expected_reason is not None and self.reason != expected_reason:
            raise ValueError("change-set verification state is incoherent")
        if self.verification == "partial" and self.reason not in {
            "current_revision_changed",
            "review_chain_gap",
            "current_file_missing",
            "baseline_not_retained",
        }:
            raise ValueError("partial change-set file requires a fixed reason")
        if self.net_effect == "unknown" and self.diff_available:
            raise ValueError("unknown change-set effect cannot expose a diff")
        if self.net_effect in {"created", "modified"} and self.current_byte_size is None:
            raise ValueError("present change-set effect requires a current byte size")
        if self.net_effect == "deleted" and self.current_byte_size is not None:
            raise ValueError("deleted change-set effect cannot carry a current byte size")
        if self.reason == "current_file_missing" and (
            self.net_effect not in {"deleted", "reverted"}
            or self.current_byte_size is not None
        ):
            raise ValueError("missing change-set path state is incoherent")
        if self.reason == "current_file_unavailable" and (
            self.net_effect != "unknown"
            or self.current_byte_size is not None
            or self.diff_available
        ):
            raise ValueError("unavailable change-set path state is incoherent")
        if self.reason in {
            "current_revision_changed",
            "review_chain_gap",
            "baseline_not_retained",
        } and self.current_byte_size is None:
            raise ValueError("present partial change-set path requires a byte size")
        if self.reason == "baseline_not_retained" and self.diff_available:
            raise ValueError("unretained baseline cannot expose a diff")
        return self


class AgentChangeSet(StrictModel):
    contract_version: Literal[CHANGE_SET_CONTRACT_VERSION] = CHANGE_SET_CONTRACT_VERSION
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    scope: Literal["reviewed_paths_only"] = "reviewed_paths_only"
    coverage: ChangeCoverage
    settled: bool
    reviewed_writes: int = Field(strict=True, ge=0)
    verified_writes: int = Field(strict=True, ge=0)
    unverified_writes: int = Field(strict=True, ge=0)
    agent_writes: int = Field(strict=True, ge=0)
    manual_writes: int = Field(strict=True, ge=0)
    reviewed_noops: int = Field(strict=True, ge=0)
    command_attempts: int = Field(strict=True, ge=0)
    omitted_write_receipts: int = Field(strict=True, ge=0)
    tracking_failed: bool
    files: tuple[AgentChangedFile, ...] = Field(max_length=MAX_CHANGE_SET_FILES)

    @model_validator(mode="after")
    def coherent_set(self) -> "AgentChangeSet":
        if self.reviewed_writes != self.verified_writes + self.unverified_writes:
            raise ValueError("change-set verification counts do not add up")
        if self.reviewed_writes != self.agent_writes + self.manual_writes:
            raise ValueError("change-set source counts do not add up")
        if self.reviewed_noops > self.verified_writes:
            raise ValueError("change-set no-op count exceeds verified writes")
        paths = [item.path for item in self.files]
        identities = [_path_identity(path) for path in paths]
        if (
            paths != sorted(paths, key=lambda value: (value.casefold(), value))
            or len(identities) != len(set(identities))
        ):
            raise ValueError("change-set paths must be unique and sorted")
        if (
            sum(item.reviewed_writes for item in self.files) > self.reviewed_writes
            or sum(item.agent_writes for item in self.files) > self.agent_writes
            or sum(item.manual_writes for item in self.files) > self.manual_writes
        ):
            raise ValueError("change-set file counts exceed the envelope")
        complete = (
            self.settled
            and self.command_attempts == 0
            and self.omitted_write_receipts == 0
            and not self.tracking_failed
            and self.unverified_writes == 0
            and all(item.verification == "verified" for item in self.files)
        )
        if (self.coverage == "complete") is not complete:
            raise ValueError("change-set coverage is incoherent")
        return self


class AgentChangeDiff(StrictModel):
    contract_version: Literal[CHANGE_SET_CONTRACT_VERSION] = CHANGE_SET_CONTRACT_VERSION
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    summary: AgentChangedFile
    diff_state: ChangeDiffState
    diff: str | None = Field(default=None, max_length=MAX_DIFF_CHARS)
    added_lines: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    removed_lines: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)

    @model_validator(mode="after")
    def coherent_diff(self) -> "AgentChangeDiff":
        if self.diff_state == "available":
            if not self.diff or self.added_lines is None or self.removed_lines is None:
                raise ValueError("available change diff requires bounded content and counts")
            lines = self.diff.split("\n")
            expected_from = "/dev/null" if self.summary.net_effect == "created" else f"a/{self.summary.path}"
            expected_to = "/dev/null" if self.summary.net_effect == "deleted" else f"b/{self.summary.path}"
            if (
                len(lines) < 3
                or lines[0] != f"--- {expected_from}"
                or lines[1] != f"+++ {expected_to}"
                or not any(line.startswith("@@") for line in lines[2:])
            ):
                raise ValueError("available change diff headers are incoherent")
        elif self.diff_state == "too_large":
            if self.diff is not None or self.added_lines is None or self.removed_lines is None:
                raise ValueError("oversized change diff requires content-free line counts")
        elif self.diff is not None:
            raise ValueError("unavailable change diff cannot carry content")
        if self.diff_state in {"no_change", "line_ending_only"} and (
            self.added_lines != 0 or self.removed_lines != 0
        ):
            raise ValueError("content-free change diff requires zero line counts")
        if self.diff_state == "no_change" and self.summary.net_effect != "reverted":
            raise ValueError("unchanged diff requires a reverted net effect")
        if self.diff_state == "line_ending_only" and self.summary.net_effect != "modified":
            raise ValueError("line-ending diff requires a modified net effect")
        if self.diff_state == "unavailable" and (
            self.added_lines is not None or self.removed_lines is not None
        ):
            raise ValueError("unavailable change diff cannot claim line counts")
        if (self.diff_state == "unavailable") is not (not self.summary.diff_available):
            raise ValueError("change diff availability is incoherent")
        return self


class AgentChangeRestorePreviewCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return _relative_path(value)


class AgentChangeRestorePreview(StrictModel):
    contract_version: Literal[CHANGE_RESTORE_CONTRACT_VERSION] = (
        CHANGE_RESTORE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    preview_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    path: str = Field(min_length=1, max_length=1024)
    operation: ChangeRestoreOperation
    baseline_state: Literal["present", "absent"]
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    restored_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    restored_byte_size: int | None = Field(
        default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES
    )
    line_ending: Literal["lf", "crlf", "none"] | None = None
    diff_state: ChangeRestoreDiffState
    diff: str | None = Field(default=None, max_length=MAX_DIFF_CHARS)
    added_lines: int = Field(strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    removed_lines: int = Field(strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    recovery: ChangeRestoreRecovery
    permanent: Literal[False] = False
    expires_at: datetime
    requires_native_confirmation: Literal[True] = True

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def coherent_preview(self) -> "AgentChangeRestorePreview":
        restores_file = self.operation in {"edit", "recreate"}
        if restores_file is not (self.baseline_state == "present"):
            raise ValueError("restore operation and baseline state are incoherent")
        if restores_file:
            if (
                self.restored_revision is None
                or self.restored_byte_size is None
                or self.line_ending is None
                or self.recovery != "revision_bound_write"
            ):
                raise ValueError("file restore requires an exact retained baseline")
            if self.operation == "edit" and self.expected_revision is None:
                raise ValueError("edit restore requires the current revision")
            if self.operation == "recreate" and self.expected_revision is not None:
                raise ValueError("recreate restore requires a missing current path")
        elif (
            self.expected_revision is None
            or self.restored_revision is not None
            or self.restored_byte_size is not None
            or self.line_ending is not None
            or self.recovery != "windows_recycle_bin"
        ):
            raise ValueError("created-file restore must be recoverable trash")

        if self.diff_state == "available":
            if not self.diff:
                raise ValueError("available restore diff requires bounded text")
            lines = self.diff.split("\n")
            expected_from = "/dev/null" if self.operation == "recreate" else f"a/{self.path}"
            expected_to = "/dev/null" if self.operation == "trash_created" else f"b/{self.path}"
            if (
                len(lines) < 3
                or lines[0] != f"--- {expected_from}"
                or lines[1] != f"+++ {expected_to}"
                or not any(line.startswith("@@") for line in lines[2:])
            ):
                raise ValueError("restore diff headers are incoherent")
        elif self.diff is not None:
            raise ValueError("content-free restore diff state carried text")
        if self.diff_state == "line_ending_only" and (
            self.operation != "edit"
            or self.added_lines != 0
            or self.removed_lines != 0
        ):
            raise ValueError("line-ending restore state is incoherent")
        return self


class AgentChangeRestoreApplyCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    operation: ChangeRestoreOperation
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    restored_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmation: Literal[CHANGE_RESTORE_CONFIRMATION]

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def coherent_command(self) -> "AgentChangeRestoreApplyCommand":
        if self.operation == "edit" and (
            self.expected_revision is None or self.restored_revision is None
        ):
            raise ValueError("edit restore command requires both revisions")
        if self.operation == "recreate" and (
            self.expected_revision is not None or self.restored_revision is None
        ):
            raise ValueError("recreate restore command is incoherent")
        if self.operation == "trash_created" and (
            self.expected_revision is None or self.restored_revision is not None
        ):
            raise ValueError("created-file restore command is incoherent")
        return self


class AgentChangeRestoreApplyResult(StrictModel):
    contract_version: Literal[CHANGE_RESTORE_CONTRACT_VERSION] = (
        CHANGE_RESTORE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    path: str = Field(min_length=1, max_length=1024)
    operation: ChangeRestoreOperation
    baseline_state: Literal["present", "absent"]
    current_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_byte_size: int | None = Field(
        default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES
    )
    recovery: ChangeRestoreRecovery
    permanent: Literal[False] = False
    net_effect: Literal["reverted"] = "reverted"
    filesystem_verification: Literal["verified"] = "verified"
    change_set_verification: ChangeVerification | Literal["tracking_unavailable"]
    change_set_reason: ChangeReason | Literal["tracking_failed"] | None = None
    applied: Literal[True] = True

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def coherent_result(self) -> "AgentChangeRestoreApplyResult":
        restores_file = self.operation in {"edit", "recreate"}
        if restores_file is not (self.baseline_state == "present"):
            raise ValueError("restore result baseline state is incoherent")
        if restores_file:
            if (
                self.current_revision is None
                or self.current_byte_size is None
                or self.recovery != "revision_bound_write"
            ):
                raise ValueError("restored file result requires objective read-back")
        elif (
            self.current_revision is not None
            or self.current_byte_size is not None
            or self.recovery != "windows_recycle_bin"
        ):
            raise ValueError("trashed created-file result is incoherent")
        if (self.change_set_verification == "verified") is not (
            self.change_set_reason is None
        ):
            raise ValueError("restore result change-set reason is incoherent")
        expected_reason = {
            "unverified": "publication_unverified",
            "unavailable": "current_file_unavailable",
            "tracking_unavailable": "tracking_failed",
        }.get(self.change_set_verification)
        if expected_reason is not None and self.change_set_reason != expected_reason:
            raise ValueError("restore result verification state is incoherent")
        if self.change_set_verification == "partial" and self.change_set_reason not in {
            "current_revision_changed",
            "review_chain_gap",
            "current_file_missing",
            "baseline_not_retained",
        }:
            raise ValueError("partial restore result requires a fixed reason")
        return self


@dataclass(slots=True)
class _TrackedFile:
    path: str
    baseline_kind: Literal["present", "absent", "unknown"]
    baseline_revision: str | None
    baseline_content: str | None
    baseline_byte_size: int | None
    baseline_retained: bool
    last_reviewed_revision: str | None
    reviewed_writes: int = 0
    agent_writes: int = 0
    manual_writes: int = 0
    chain_gap: bool = False
    publication_unverified: bool = False


@dataclass(frozen=True, slots=True)
class _ManualStage:
    preview_id: str
    path: str
    revision: str | None
    content: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class _ObservedCurrent:
    state: Literal["present", "missing", "unavailable"]
    revision: str | None
    content: str | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class AgentChangeRestorePlan:
    """Sensitive in-memory restore material; never serialized to a client."""

    path: str
    operation: ChangeRestoreOperation
    baseline_state: Literal["present", "absent"]
    expected_revision: str | None
    restored_revision: str | None
    restored_byte_size: int | None
    line_ending: Literal["lf", "crlf", "none"] | None
    content: str | None
    diff_state: ChangeRestoreDiffState
    diff: str | None
    added_lines: int
    removed_lines: int

    @property
    def recovery(self) -> ChangeRestoreRecovery:
        return (
            "windows_recycle_bin"
            if self.operation == "trash_created"
            else "revision_bound_write"
        )


def _normalise_disk_text(value: str) -> str:
    return value.replace("\r\n", "\n")


def _path_identity(value: str) -> str:
    """Match the workspace's Windows case-insensitive path identity."""

    return value.casefold() if os.name == "nt" else value


class AgentChangeTracker:
    """One session's bounded baseline registry and live reviewed-path view."""

    def __init__(
        self,
        *,
        max_files: int = MAX_CHANGE_SET_FILES,
        max_baseline_bytes: int = MAX_CHANGE_SET_BASELINE_BYTES,
    ) -> None:
        self._max_files = max(1, min(max_files, MAX_CHANGE_SET_FILES))
        self._max_baseline_bytes = max(0, min(max_baseline_bytes, MAX_CHANGE_SET_BASELINE_BYTES))
        self._baseline_bytes = 0
        self._files: dict[str, _TrackedFile] = {}
        self._manual_stages: OrderedDict[str, _ManualStage] = OrderedDict()
        self._reviewed_writes = 0
        self._verified_writes = 0
        self._unverified_writes = 0
        self._agent_writes = 0
        self._manual_writes = 0
        self._reviewed_noops = 0
        self._command_attempts = 0
        self._omitted_write_receipts = 0
        self._tracking_failed = False
        self._lock = threading.RLock()

    def mark_failed(self) -> None:
        with self._lock:
            self._tracking_failed = True

    def observe_command(self) -> None:
        with self._lock:
            self._command_attempts += 1

    def stage_manual_preview(self, preview_id: str, snapshot: WorkspaceTextSnapshot) -> None:
        stage = _ManualStage(
            preview_id=preview_id,
            path=snapshot.path,
            revision=snapshot.revision,
            content=snapshot.content,
            byte_size=snapshot.byte_size,
        )
        with self._lock:
            self._manual_stages[preview_id] = stage
            self._manual_stages.move_to_end(preview_id)
            while len(self._manual_stages) > MAX_MANUAL_PREVIEW_BASELINES:
                self._manual_stages.popitem(last=False)

    def stage_manual_create(self, preview_id: str, path: str) -> None:
        stage = _ManualStage(
            preview_id=preview_id,
            path=_relative_path(path),
            revision=None,
            content="",
            byte_size=0,
        )
        with self._lock:
            self._manual_stages[preview_id] = stage
            self._manual_stages.move_to_end(preview_id)
            while len(self._manual_stages) > MAX_MANUAL_PREVIEW_BASELINES:
                self._manual_stages.popitem(last=False)

    def discard_manual_preview(self, preview_id: str) -> None:
        with self._lock:
            self._manual_stages.pop(preview_id, None)

    def discard_manual_plan(self, plan_id: str) -> None:
        """Forget every transient baseline owned by one multi-file review."""

        prefix = f"{plan_id}:"
        with self._lock:
            for preview_id in tuple(self._manual_stages):
                if preview_id.startswith(prefix):
                    self._manual_stages.pop(preview_id, None)

    def observe_manual_applied(
        self,
        preview_id: str,
        result: WorkspaceApplyResult,
        *,
        expected_revision: str,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = stage is not None and stage.path == result.path and stage.revision == expected_revision
        self._observe_write(
            path=result.path,
            state="verified",
            before_revision=expected_revision,
            after_revision=result.revision,
            operation="unchanged" if result.revision == expected_revision else "modified",
            baseline_content=stage.content if coherent else None,
            baseline_bytes=stage.byte_size if coherent else None,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_unverified(
        self,
        preview_id: str,
        *,
        path: str,
        expected_revision: str,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = stage is not None and stage.path == path and stage.revision == expected_revision
        self._observe_write(
            path=path,
            state="unverified",
            before_revision=expected_revision,
            after_revision=None,
            operation=None,
            baseline_content=stage.content if coherent else None,
            baseline_bytes=stage.byte_size if coherent else None,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_created(
        self,
        preview_id: str,
        result: WorkspaceCreateApplyResult,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = stage is not None and stage.path == result.path and stage.revision is None
        self._observe_write(
            path=result.path,
            state="verified",
            before_revision=None,
            after_revision=result.revision,
            operation="created",
            baseline_content="" if coherent else None,
            baseline_bytes=0 if coherent else None,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_create_unverified(self, preview_id: str, *, path: str) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = stage is not None and stage.path == path and stage.revision is None
        self._observe_write(
            path=path,
            state="unverified",
            before_revision=None,
            after_revision=None,
            operation=None,
            baseline_content="" if coherent else None,
            baseline_bytes=0 if coherent else None,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_moved(
        self,
        preview_id: str,
        result: WorkspaceMoveApplyResult,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = (
            stage is not None
            and stage.path == result.source_path
            and stage.revision == result.revision
        )
        self._observe_write(
            path=result.source_path,
            state="verified",
            before_revision=result.revision,
            after_revision=None,
            operation="deleted",
            baseline_content=stage.content if coherent else None,
            baseline_bytes=stage.byte_size if coherent else None,
            source="manual",
        )
        self._observe_write(
            path=result.target_path,
            state="verified",
            before_revision=None,
            after_revision=result.revision,
            operation="created",
            baseline_content="",
            baseline_bytes=0,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_move_unverified(
        self,
        preview_id: str,
        *,
        source_path: str,
        target_path: str,
        expected_revision: str,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = (
            stage is not None
            and stage.path == source_path
            and stage.revision == expected_revision
        )
        self._observe_write(
            path=source_path,
            state="unverified",
            before_revision=expected_revision,
            after_revision=None,
            operation=None,
            baseline_content=stage.content if coherent else None,
            baseline_bytes=stage.byte_size if coherent else None,
            source="manual",
        )
        self._observe_write(
            path=target_path,
            state="unverified",
            before_revision=None,
            after_revision=None,
            operation=None,
            baseline_content="",
            baseline_bytes=0,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_trashed(
        self,
        preview_id: str,
        result: WorkspaceFileTrashApplyResult,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = (
            stage is not None
            and stage.path == result.path
            and stage.revision == result.revision
            and stage.byte_size == result.byte_size
        )
        self._observe_write(
            path=result.path,
            state="verified",
            before_revision=result.revision,
            after_revision=None,
            operation="deleted",
            baseline_content=stage.content if coherent else None,
            baseline_bytes=stage.byte_size if coherent else None,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_manual_trash_unverified(
        self,
        preview_id: str,
        *,
        path: str,
        expected_revision: str,
    ) -> None:
        with self._lock:
            stage = self._manual_stages.pop(preview_id, None)
        coherent = (
            stage is not None
            and stage.path == path
            and stage.revision == expected_revision
        )
        self._observe_write(
            path=path,
            state="unverified",
            before_revision=expected_revision,
            after_revision=None,
            operation=None,
            baseline_content=stage.content if coherent else None,
            baseline_bytes=stage.byte_size if coherent else None,
            source="manual",
        )
        if not coherent:
            self.mark_failed()

    def observe_agent_write(self, prepared: PreparedWrite, receipt: AgentWriteReceipt) -> bool:
        coherent = (
            receipt.path == prepared.path
            and receipt.before_sha256 == prepared.base_sha256
            and (
                receipt.state == "unverified"
                or receipt.after_sha256 == prepared.proposed_sha256
            )
        )
        if not coherent:
            self.mark_failed()
            return False
        self._observe_write(
            path=prepared.path,
            state=receipt.state,
            before_revision=prepared.base_sha256,
            after_revision=receipt.after_sha256,
            operation=receipt.operation,
            baseline_content=prepared.base_content,
            baseline_bytes=prepared.base_byte_size,
            source="agent",
        )
        return True

    def observe_agent_moved(
        self,
        baseline: WorkspaceTextSnapshot,
        result: WorkspaceMoveApplyResult,
    ) -> bool:
        coherent = (
            baseline.path == result.source_path
            and baseline.revision == result.revision
            and baseline.byte_size == result.byte_size
        )
        self._observe_write(
            path=result.source_path,
            state="verified",
            before_revision=result.revision,
            after_revision=None,
            operation="deleted",
            baseline_content=baseline.content if coherent else None,
            baseline_bytes=baseline.byte_size if coherent else None,
            source="agent",
        )
        self._observe_write(
            path=result.target_path,
            state="verified",
            before_revision=None,
            after_revision=result.revision,
            operation="created",
            baseline_content="",
            baseline_bytes=0,
            source="agent",
        )
        if not coherent:
            self.mark_failed()
        return coherent

    def observe_agent_move_unverified(
        self,
        baseline: WorkspaceTextSnapshot,
        *,
        source_path: str,
        target_path: str,
    ) -> None:
        coherent = baseline.path == source_path
        self._observe_write(
            path=source_path,
            state="unverified",
            before_revision=baseline.revision if coherent else None,
            after_revision=None,
            operation=None,
            baseline_content=baseline.content if coherent else None,
            baseline_bytes=baseline.byte_size if coherent else None,
            source="agent",
        )
        self._observe_write(
            path=target_path,
            state="unverified",
            before_revision=None,
            after_revision=None,
            operation=None,
            baseline_content="",
            baseline_bytes=0,
            source="agent",
        )
        if not coherent:
            self.mark_failed()

    def observe_agent_trashed(
        self,
        baseline: WorkspaceTextSnapshot,
        result: WorkspaceFileTrashApplyResult,
    ) -> bool:
        coherent = (
            baseline.path == result.path
            and baseline.revision == result.revision
            and baseline.byte_size == result.byte_size
        )
        self._observe_write(
            path=result.path,
            state="verified",
            before_revision=result.revision,
            after_revision=None,
            operation="deleted",
            baseline_content=baseline.content if coherent else None,
            baseline_bytes=baseline.byte_size if coherent else None,
            source="agent",
        )
        if not coherent:
            self.mark_failed()
        return coherent

    def observe_agent_trash_unverified(
        self,
        baseline: WorkspaceTextSnapshot,
        *,
        path: str,
    ) -> None:
        coherent = baseline.path == path
        self._observe_write(
            path=path,
            state="unverified",
            before_revision=baseline.revision if coherent else None,
            after_revision=None,
            operation=None,
            baseline_content=baseline.content if coherent else None,
            baseline_bytes=baseline.byte_size if coherent else None,
            source="agent",
        )
        if not coherent:
            self.mark_failed()

    def _observe_write(
        self,
        *,
        path: str,
        state: Literal["verified", "unverified"],
        before_revision: str | None,
        after_revision: str | None,
        operation: Literal["created", "modified", "unchanged", "deleted"] | None,
        baseline_content: str | None,
        baseline_bytes: int | None,
        source: ChangeSource,
    ) -> None:
        path = _relative_path(path)
        with self._lock:
            self._reviewed_writes += 1
            self._agent_writes += int(source == "agent")
            self._manual_writes += int(source == "manual")
            self._verified_writes += int(state == "verified")
            self._unverified_writes += int(state == "unverified")

            path_key = _path_identity(path)
            record = self._files.get(path_key)
            if state == "verified" and operation == "unchanged" and record is None:
                self._reviewed_noops += 1
                return
            if record is None:
                if len(self._files) >= self._max_files:
                    self._omitted_write_receipts += 1
                    return
                baseline_kind: Literal["present", "absent", "unknown"] = (
                    "absent" if before_revision is None else "present"
                )
                retained = baseline_kind == "absent"
                stored_content: str | None = "" if retained else None
                if baseline_kind == "present" and baseline_content is not None and baseline_bytes is not None:
                    if self._baseline_bytes + baseline_bytes <= self._max_baseline_bytes:
                        stored_content = _normalise_disk_text(baseline_content)
                        retained = True
                        self._baseline_bytes += baseline_bytes
                record = _TrackedFile(
                    path=path,
                    baseline_kind=baseline_kind,
                    baseline_revision=before_revision,
                    baseline_content=stored_content,
                    baseline_byte_size=(
                        0 if baseline_kind == "absent" else baseline_bytes
                    ),
                    baseline_retained=retained,
                    last_reviewed_revision=before_revision,
                )
                self._files[path_key] = record

            record.reviewed_writes += 1
            record.agent_writes += int(source == "agent")
            record.manual_writes += int(source == "manual")
            if state == "unverified":
                record.publication_unverified = True
                return
            if record.last_reviewed_revision != before_revision:
                record.chain_gap = True
            record.last_reviewed_revision = after_revision
            if operation == "unchanged":
                self._reviewed_noops += 1

    @staticmethod
    def _read_current(record: _TrackedFile, tools: WorkspaceTools) -> _ObservedCurrent:
        try:
            current = tools.read_text_snapshot(record.path)
        except LocalAgentError as error:
            if error.code == "workspace_path_not_found":
                return _ObservedCurrent("missing", None, None, None)
            return _ObservedCurrent("unavailable", None, None, None)
        except Exception:
            return _ObservedCurrent("unavailable", None, None, None)
        return _ObservedCurrent(
            "present",
            current.revision,
            current.content,
            current.byte_size,
        )

    @staticmethod
    def _summary(record: _TrackedFile, current: _ObservedCurrent) -> AgentChangedFile:
        if record.baseline_kind == "unknown":
            net_effect: ChangeNetEffect = "unknown"
        elif current.state == "missing":
            net_effect = "reverted" if record.baseline_kind == "absent" else "deleted"
        elif current.state == "unavailable":
            net_effect = "unknown"
        elif record.baseline_kind == "absent":
            net_effect = "created"
        elif current.revision == record.baseline_revision:
            net_effect = "reverted"
        else:
            net_effect = "modified"

        reason: ChangeReason | None = None
        verification: ChangeVerification = "verified"
        if current.state == "unavailable":
            verification, reason = "unavailable", "current_file_unavailable"
        elif record.publication_unverified:
            verification, reason = "unverified", "publication_unverified"
        elif current.state == "missing" and record.last_reviewed_revision is not None:
            verification, reason = "partial", "current_file_missing"
        elif current.revision != record.last_reviewed_revision:
            verification, reason = "partial", "current_revision_changed"
        elif record.chain_gap:
            verification, reason = "partial", "review_chain_gap"
        elif not record.baseline_retained:
            verification, reason = "partial", "baseline_not_retained"

        diff_available = (
            record.baseline_kind != "unknown"
            and record.baseline_retained
            and current.state != "unavailable"
        )
        return AgentChangedFile(
            path=record.path,
            net_effect=net_effect,
            verification=verification,
            reason=reason,
            reviewed_writes=record.reviewed_writes,
            agent_writes=record.agent_writes,
            manual_writes=record.manual_writes,
            current_byte_size=current.byte_size,
            diff_available=diff_available,
        )

    @staticmethod
    def _retained_baseline(
        record: _TrackedFile,
    ) -> tuple[str, Literal["lf", "crlf", "none"], int] | None:
        if (
            record.baseline_kind != "present"
            or not record.baseline_retained
            or record.baseline_content is None
            or record.baseline_revision is None
            or record.baseline_byte_size is None
        ):
            return None
        content = record.baseline_content
        candidates: tuple[tuple[Literal["lf", "crlf", "none"], str], ...]
        if "\n" not in content:
            candidates = (("none", content),)
        else:
            candidates = (
                ("lf", content),
                ("crlf", content.replace("\n", "\r\n")),
            )
        matches = []
        for line_ending, disk_content in candidates:
            payload = disk_content.encode("utf-8")
            if (
                len(payload) == record.baseline_byte_size
                and hashlib.sha256(payload).hexdigest() == record.baseline_revision
            ):
                matches.append((content, line_ending, len(payload)))
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _restore_diff(
        *,
        path: str,
        before_exists: bool,
        before: str,
        after_exists: bool,
        after: str,
    ) -> tuple[ChangeRestoreDiffState, str | None, int, int]:
        if before == after:
            if before_exists != after_exists:
                from_file = f"a/{path}" if before_exists else "/dev/null"
                to_file = f"b/{path}" if after_exists else "/dev/null"
                return (
                    "available",
                    f"--- {from_file}\n+++ {to_file}\n@@ -0,0 +0,0 @@",
                    0,
                    0,
                )
            return "line_ending_only", None, 0, 0

        additions = removals = 0
        for operation, left_start, left_end, right_start, right_end in difflib.SequenceMatcher(
            a=before.splitlines(keepends=True),
            b=after.splitlines(keepends=True),
            autojunk=True,
        ).get_opcodes():
            if operation in {"replace", "insert"}:
                additions += right_end - right_start
            if operation in {"replace", "delete"}:
                removals += left_end - left_start
        from_file = f"a/{path}" if before_exists else "/dev/null"
        to_file = f"b/{path}" if after_exists else "/dev/null"
        rendered = "\n".join(
            difflib.unified_diff(
                before.split("\n"),
                after.split("\n"),
                fromfile=from_file,
                tofile=to_file,
                lineterm="",
                n=3,
            )
        )
        if not rendered:
            return "line_ending_only", None, 0, 0
        if len(rendered) > MAX_DIFF_CHARS:
            return "too_large", None, additions, removals
        return "available", rendered, additions, removals

    def restore_plan(self, path: str, tools: WorkspaceTools) -> AgentChangeRestorePlan:
        """Build an exact inverse plan without exposing retained baseline text."""

        try:
            path = _relative_path(path)
        except ValueError:
            raise LocalAgentError("change_path_not_found") from None
        with self._lock:
            record = self._files.get(_path_identity(path))
            copied = replace(record) if record is not None else None
        if copied is None or copied.path != path:
            raise LocalAgentError("change_path_not_found")
        current = self._read_current(copied, tools)
        if current.state == "unavailable":
            raise LocalAgentError("change_restore_unavailable")
        summary = self._summary(copied, current)
        if summary.net_effect == "reverted":
            raise LocalAgentError("change_already_reverted")
        if not copied.baseline_retained or copied.baseline_kind == "unknown":
            raise LocalAgentError("change_restore_baseline_unavailable")

        baseline_content = ""
        baseline_line_ending: Literal["lf", "crlf", "none"] | None = None
        baseline_size: int | None = None
        if copied.baseline_kind == "present":
            retained = self._retained_baseline(copied)
            if retained is None:
                self.mark_failed()
                raise LocalAgentError("change_restore_baseline_unavailable")
            baseline_content, baseline_line_ending, baseline_size = retained

        before_exists = current.state == "present"
        before_content = current.content if before_exists and current.content is not None else ""
        after_exists = copied.baseline_kind == "present"
        diff_state, diff, added_lines, removed_lines = self._restore_diff(
            path=path,
            before_exists=before_exists,
            before=before_content,
            after_exists=after_exists,
            after=baseline_content,
        )
        operation: ChangeRestoreOperation
        if copied.baseline_kind == "absent":
            if not before_exists or current.revision is None:
                raise LocalAgentError("change_already_reverted")
            operation = "trash_created"
        elif before_exists:
            if current.revision is None:
                raise LocalAgentError("change_restore_unavailable")
            operation = "edit"
        else:
            operation = "recreate"
        return AgentChangeRestorePlan(
            path=path,
            operation=operation,
            baseline_state=copied.baseline_kind,
            expected_revision=current.revision,
            restored_revision=copied.baseline_revision,
            restored_byte_size=baseline_size,
            line_ending=baseline_line_ending,
            content=baseline_content if copied.baseline_kind == "present" else None,
            diff_state=diff_state,
            diff=diff,
            added_lines=added_lines,
            removed_lines=removed_lines,
        )

    def snapshot(self, session_id: str, tools: WorkspaceTools, *, settled: bool) -> AgentChangeSet:
        with self._lock:
            records = [replace(item) for item in self._files.values()]
            counts = (
                self._reviewed_writes,
                self._verified_writes,
                self._unverified_writes,
                self._agent_writes,
                self._manual_writes,
                self._reviewed_noops,
                self._command_attempts,
                self._omitted_write_receipts,
                self._tracking_failed,
            )
        files = tuple(
            sorted(
                (self._summary(record, self._read_current(record, tools)) for record in records),
                key=lambda item: (item.path.casefold(), item.path),
            )
        )
        reviewed, verified, unverified, agent, manual, noops, commands, omitted, failed = counts
        complete = (
            settled
            and commands == 0
            and omitted == 0
            and not failed
            and unverified == 0
            and all(item.verification == "verified" for item in files)
        )
        return AgentChangeSet(
            session_id=session_id,
            coverage="complete" if complete else "partial",
            settled=settled,
            reviewed_writes=reviewed,
            verified_writes=verified,
            unverified_writes=unverified,
            agent_writes=agent,
            manual_writes=manual,
            reviewed_noops=noops,
            command_attempts=commands,
            omitted_write_receipts=omitted,
            tracking_failed=failed,
            files=files,
        )

    def diff(self, session_id: str, path: str, tools: WorkspaceTools) -> AgentChangeDiff:
        try:
            path = _relative_path(path)
        except ValueError:
            raise LocalAgentError("change_path_not_found") from None
        with self._lock:
            record = self._files.get(_path_identity(path))
            copied = replace(record) if record is not None else None
        if copied is None or copied.path != path:
            raise LocalAgentError("change_path_not_found")
        current = self._read_current(copied, tools)
        summary = self._summary(copied, current)
        if not summary.diff_available or copied.baseline_content is None:
            return AgentChangeDiff(
                session_id=session_id,
                summary=summary,
                diff_state="unavailable",
            )

        before = copied.baseline_content
        after = current.content if current.state == "present" and current.content is not None else ""
        if before == after:
            existence_changed = (
                (copied.baseline_kind == "absent" and current.state == "present")
                or (copied.baseline_kind == "present" and current.state == "missing")
            )
            if existence_changed:
                from_file = "/dev/null" if copied.baseline_kind == "absent" else f"a/{path}"
                to_file = "/dev/null" if current.state == "missing" else f"b/{path}"
                return AgentChangeDiff(
                    session_id=session_id,
                    summary=summary,
                    diff_state="available",
                    diff=f"--- {from_file}\n+++ {to_file}\n@@ -0,0 +0,0 @@",
                    added_lines=0,
                    removed_lines=0,
                )
            state: ChangeDiffState = (
                "line_ending_only" if summary.net_effect == "modified" else "no_change"
            )
            return AgentChangeDiff(
                session_id=session_id,
                summary=summary,
                diff_state=state,
                added_lines=0,
                removed_lines=0,
            )

        additions = removals = 0
        for operation, left_start, left_end, right_start, right_end in difflib.SequenceMatcher(
            a=before.splitlines(keepends=True),
            b=after.splitlines(keepends=True),
            autojunk=True,
        ).get_opcodes():
            if operation in {"replace", "insert"}:
                additions += right_end - right_start
            if operation in {"replace", "delete"}:
                removals += left_end - left_start
        from_file = "/dev/null" if copied.baseline_kind == "absent" else f"a/{path}"
        to_file = "/dev/null" if current.state == "missing" else f"b/{path}"
        rendered = "\n".join(
            difflib.unified_diff(
                before.split("\n"),
                after.split("\n"),
                fromfile=from_file,
                tofile=to_file,
                lineterm="",
                n=3,
            )
        )
        if not rendered:
            return AgentChangeDiff(
                session_id=session_id,
                summary=summary,
                diff_state="line_ending_only",
                added_lines=0,
                removed_lines=0,
            )
        if len(rendered) > MAX_DIFF_CHARS:
            return AgentChangeDiff(
                session_id=session_id,
                summary=summary,
                diff_state="too_large",
                added_lines=additions,
                removed_lines=removals,
            )
        return AgentChangeDiff(
            session_id=session_id,
            summary=summary,
            diff_state="available",
            diff=rendered,
            added_lines=additions,
            removed_lines=removals,
        )


__all__ = (
    "AgentChangeDiff",
    "AgentChangeRestoreApplyCommand",
    "AgentChangeRestoreApplyResult",
    "AgentChangeRestorePlan",
    "AgentChangeRestorePreview",
    "AgentChangeRestorePreviewCommand",
    "AgentChangeSet",
    "AgentChangeTracker",
    "AgentChangedFile",
    "CHANGE_RESTORE_CONFIRMATION",
    "CHANGE_RESTORE_CONTRACT_VERSION",
    "CHANGE_SET_CONTRACT_VERSION",
    "MAX_CHANGE_SET_BASELINE_BYTES",
    "MAX_CHANGE_SET_FILES",
)
