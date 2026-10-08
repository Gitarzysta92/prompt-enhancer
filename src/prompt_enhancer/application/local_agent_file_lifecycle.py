"""Review-before-apply creation and no-overwrite moves for one Agent workspace.

Capabilities are in-memory, session-bound, short-lived, single-use, and retain
only path/revision/identity metadata. Draft file content is always resubmitted
by the caller and re-hashed at apply time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import threading
import time
from typing import Literal
import uuid

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .local_agent_editor import WorkspaceLineEnding
from .local_agent_limits import MAX_DIFF_CHARS, MAX_FILE_WRITE_BYTES, LocalAgentError
from .local_agent_workspace import (
    PreparedDirectoryCreate,
    PreparedDirectoryMove,
    PreparedFileTrash,
    PreparedMove,
    PreparedWrite,
    WorkspaceTools,
)


WORKSPACE_LIFECYCLE_CONTRACT_VERSION = "local-agent-workspace-lifecycle.v1"
WORKSPACE_CREATE_CONFIRMATION = "apply_reviewed_workspace_create"
WORKSPACE_DIRECTORY_CREATE_CONFIRMATION = "apply_reviewed_workspace_directory_create"
WORKSPACE_DIRECTORY_MOVE_CONFIRMATION = "apply_reviewed_workspace_directory_move"
WORKSPACE_FILE_TRASH_CONFIRMATION = "apply_reviewed_workspace_file_trash"
WORKSPACE_MOVE_CONFIRMATION = "apply_reviewed_workspace_move"
WORKSPACE_LIFECYCLE_TTL_SECONDS = 120
MAX_ACTIVE_LIFECYCLE_PREVIEWS_PER_SESSION = 8
_ID_PATTERN = r"^[0-9a-f]{32}$"
_REVISION_PATTERN = r"^[0-9a-f]{64}$"


def _normalised_text(value: str) -> str:
    if "\x00" in value or "\r" in value:
        raise ValueError("workspace lifecycle accepts normalized UTF-8 text only")
    return value


class WorkspaceCreatePreviewCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_FILE_WRITE_BYTES)
    line_ending: WorkspaceLineEnding

    _text = field_validator("content")(_normalised_text)

    @model_validator(mode="after")
    def coherent_line_ending(self) -> "WorkspaceCreatePreviewCommand":
        if (self.line_ending is WorkspaceLineEnding.NONE) is not ("\n" not in self.content):
            raise ValueError("workspace create line-ending style is incoherent")
        return self


class WorkspaceCreatePreview(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    preview_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    proposed_revision: str = Field(pattern=_REVISION_PATTERN)
    line_ending: WorkspaceLineEnding
    byte_size: int = Field(ge=0, le=MAX_FILE_WRITE_BYTES)
    diff: str = Field(min_length=1, max_length=MAX_DIFF_CHARS)
    expires_at: datetime


class WorkspaceCreateApplyCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_FILE_WRITE_BYTES)
    proposed_revision: str = Field(pattern=_REVISION_PATTERN)
    line_ending: WorkspaceLineEnding
    confirmation: Literal[WORKSPACE_CREATE_CONFIRMATION]

    _text = field_validator("content")(_normalised_text)

    @model_validator(mode="after")
    def coherent_line_ending(self) -> "WorkspaceCreateApplyCommand":
        if (self.line_ending is WorkspaceLineEnding.NONE) is not ("\n" not in self.content):
            raise ValueError("workspace create line-ending style is incoherent")
        return self


class WorkspaceCreateApplyResult(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    revision: str = Field(pattern=_REVISION_PATTERN)
    byte_size: int = Field(ge=0, le=MAX_FILE_WRITE_BYTES)
    operation: Literal["created"] = "created"
    applied: Literal[True] = True


class WorkspaceDirectoryCreatePreviewCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)


class WorkspaceDirectoryCreatePreview(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    preview_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    expires_at: datetime


class WorkspaceDirectoryCreateApplyCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    confirmation: Literal[WORKSPACE_DIRECTORY_CREATE_CONFIRMATION]


class WorkspaceDirectoryCreateApplyResult(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    operation: Literal["directory_created"] = "directory_created"
    applied: Literal[True] = True


class WorkspaceDirectoryMovePreviewCommand(StrictModel):
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def distinct_paths(self) -> "WorkspaceDirectoryMovePreviewCommand":
        if self.source_path == self.target_path:
            raise ValueError("workspace directory move paths must differ")
        return self


class WorkspaceDirectoryMovePreview(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    preview_id: str = Field(pattern=_ID_PATTERN)
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    contents_reviewed: Literal[False] = False
    expires_at: datetime


class WorkspaceDirectoryMoveApplyCommand(StrictModel):
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    confirmation: Literal[WORKSPACE_DIRECTORY_MOVE_CONFIRMATION]

    @model_validator(mode="after")
    def distinct_paths(self) -> "WorkspaceDirectoryMoveApplyCommand":
        if self.source_path == self.target_path:
            raise ValueError("workspace directory move paths must differ")
        return self


class WorkspaceDirectoryMoveApplyResult(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    contents_reviewed: Literal[False] = False
    operation: Literal["directory_moved"] = "directory_moved"
    applied: Literal[True] = True


class WorkspaceFileTrashPreviewCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(pattern=_REVISION_PATTERN)


class WorkspaceFileTrashPreview(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    preview_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(pattern=_REVISION_PATTERN)
    byte_size: int = Field(ge=0, le=MAX_FILE_WRITE_BYTES)
    recovery: Literal["windows_recycle_bin"] = "windows_recycle_bin"
    permanent: Literal[False] = False
    expires_at: datetime


class WorkspaceFileTrashApplyCommand(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(pattern=_REVISION_PATTERN)
    confirmation: Literal[WORKSPACE_FILE_TRASH_CONFIRMATION]


class WorkspaceFileTrashApplyResult(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    revision: str = Field(pattern=_REVISION_PATTERN)
    byte_size: int = Field(ge=0, le=MAX_FILE_WRITE_BYTES)
    recovery: Literal["windows_recycle_bin"] = "windows_recycle_bin"
    permanent: Literal[False] = False
    operation: Literal["trashed"] = "trashed"
    applied: Literal[True] = True


class WorkspaceMovePreviewCommand(StrictModel):
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(pattern=_REVISION_PATTERN)

    @model_validator(mode="after")
    def distinct_paths(self) -> "WorkspaceMovePreviewCommand":
        if self.source_path == self.target_path:
            raise ValueError("workspace move paths must differ")
        return self


class WorkspaceMovePreview(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    preview_id: str = Field(pattern=_ID_PATTERN)
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(pattern=_REVISION_PATTERN)
    byte_size: int = Field(ge=0, le=MAX_FILE_WRITE_BYTES)
    expires_at: datetime


class WorkspaceMoveApplyCommand(StrictModel):
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(pattern=_REVISION_PATTERN)
    confirmation: Literal[WORKSPACE_MOVE_CONFIRMATION]

    @model_validator(mode="after")
    def distinct_paths(self) -> "WorkspaceMoveApplyCommand":
        if self.source_path == self.target_path:
            raise ValueError("workspace move paths must differ")
        return self


class WorkspaceMoveApplyResult(StrictModel):
    contract_version: Literal[WORKSPACE_LIFECYCLE_CONTRACT_VERSION] = (
        WORKSPACE_LIFECYCLE_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    source_path: str = Field(min_length=1, max_length=1024)
    target_path: str = Field(min_length=1, max_length=1024)
    revision: str = Field(pattern=_REVISION_PATTERN)
    byte_size: int = Field(ge=0, le=MAX_FILE_WRITE_BYTES)
    operation: Literal["moved"] = "moved"
    applied: Literal[True] = True


@dataclass(frozen=True, slots=True)
class _CreateCapability:
    preview_id: str
    session_id: str
    path: str
    proposed_revision: str
    line_ending: WorkspaceLineEnding
    parent_identity: tuple[int, int]
    expires_at: datetime
    deadline: float


@dataclass(frozen=True, slots=True)
class _MoveCapability:
    preview_id: str
    session_id: str
    source_path: str
    target_path: str
    expected_revision: str
    source_identity: tuple[int, int]
    source_parent_identity: tuple[int, int]
    target_parent_identity: tuple[int, int]
    byte_size: int
    mode: int
    expires_at: datetime
    deadline: float


@dataclass(frozen=True, slots=True)
class _DirectoryCreateCapability:
    preview_id: str
    session_id: str
    path: str
    parent_identity: tuple[int, int]
    expires_at: datetime
    deadline: float


@dataclass(frozen=True, slots=True)
class _DirectoryMoveCapability:
    preview_id: str
    session_id: str
    source_path: str
    target_path: str
    source_identity: tuple[int, int]
    source_parent_identity: tuple[int, int]
    target_parent_identity: tuple[int, int]
    expires_at: datetime
    deadline: float


@dataclass(frozen=True, slots=True)
class _FileTrashCapability:
    preview_id: str
    session_id: str
    path: str
    expected_revision: str
    source_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    byte_size: int
    mode: int
    expires_at: datetime
    deadline: float


_Capability = (
    _CreateCapability
    | _DirectoryCreateCapability
    | _DirectoryMoveCapability
    | _FileTrashCapability
    | _MoveCapability
)


class LocalAgentWorkspaceFileLifecycle:
    """Own reviewed file/folder path authority without retaining content."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        ttl_seconds: int = WORKSPACE_LIFECYCLE_TTL_SECONDS,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._ttl_seconds = max(1, min(int(ttl_seconds), WORKSPACE_LIFECYCLE_TTL_SECONDS))
        self._capabilities: dict[str, _Capability] = {}
        self._blocked_sessions: set[str] = set()
        self._lock = threading.RLock()

    @staticmethod
    def _matches(left: str, right: str) -> bool:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

    @staticmethod
    def _disk_content(content: str, line_ending: WorkspaceLineEnding) -> str:
        if "\x00" in content or "\r" in content:
            raise LocalAgentError("workspace_text_invalid")
        return content.replace("\n", "\r\n") if line_ending is WorkspaceLineEnding.CRLF else content

    def _ensure_available_locked(self, session_id: str) -> None:
        if session_id in self._blocked_sessions:
            raise LocalAgentError("workspace_lifecycle_unverified")

    def _prune_locked(self, now: float) -> None:
        for preview_id in [
            key for key, capability in self._capabilities.items() if capability.deadline <= now
        ]:
            self._capabilities.pop(preview_id, None)

    def _store(self, capability: _Capability) -> None:
        with self._lock:
            self._ensure_available_locked(capability.session_id)
            self._prune_locked(self._monotonic())
            existing = sorted(
                (
                    item
                    for item in self._capabilities.values()
                    if item.session_id == capability.session_id
                ),
                key=lambda item: item.deadline,
            )
            while len(existing) >= MAX_ACTIVE_LIFECYCLE_PREVIEWS_PER_SESSION:
                self._capabilities.pop(existing.pop(0).preview_id, None)
            self._capabilities[capability.preview_id] = capability

    def _take(self, session_id: str, preview_id: str, expected: type[_Capability]) -> _Capability:
        now = self._monotonic()
        with self._lock:
            self._ensure_available_locked(session_id)
            capability = self._capabilities.get(preview_id)
            if capability is not None and capability.session_id == session_id:
                self._capabilities.pop(preview_id, None)
        if capability is None or capability.session_id != session_id or not isinstance(capability, expected):
            raise LocalAgentError("workspace_lifecycle_preview_not_found")
        if capability.deadline <= now:
            raise LocalAgentError("workspace_lifecycle_preview_expired")
        return capability

    def _block(self, session_id: str) -> None:
        with self._lock:
            self._blocked_sessions.add(session_id)
            for preview_id in [
                item.preview_id
                for item in self._capabilities.values()
                if item.session_id == session_id
            ]:
                self._capabilities.pop(preview_id, None)

    def discard_session(self, session_id: str) -> None:
        with self._lock:
            self._blocked_sessions.discard(session_id)
            for preview_id in [
                item.preview_id
                for item in self._capabilities.values()
                if item.session_id == session_id
            ]:
                self._capabilities.pop(preview_id, None)

    def discard_preview(self, session_id: str, preview_id: str) -> None:
        """Drop one still-pending capability after denial or cancellation."""

        with self._lock:
            capability = self._capabilities.get(preview_id)
            if capability is not None and capability.session_id == session_id:
                self._capabilities.pop(preview_id, None)

    def preview_create(
        self,
        session_id: str,
        tools: WorkspaceTools,
        command: WorkspaceCreatePreviewCommand,
    ) -> WorkspaceCreatePreview:
        with self._lock:
            self._ensure_available_locked(session_id)
        disk_content = self._disk_content(command.content, command.line_ending)
        prepared = tools.prepare_write(command.path, disk_content)
        if prepared.existed or prepared.base_sha256 is not None or prepared.base_identity is not None:
            raise LocalAgentError("workspace_lifecycle_target_exists")
        rendered = prepared.preview
        if rendered.startswith(f"--- a/{prepared.path}\n"):
            rendered = rendered.replace(f"--- a/{prepared.path}\n", "--- /dev/null\n", 1)
        elif rendered.startswith("(new file"):
            rendered = f"--- /dev/null\n+++ b/{prepared.path}\n@@ -0,0 +0,0 @@"
        now = self._monotonic()
        capability = _CreateCapability(
            preview_id=uuid.uuid4().hex,
            session_id=session_id,
            path=prepared.path,
            proposed_revision=prepared.proposed_sha256,
            line_ending=command.line_ending,
            parent_identity=prepared.parent_identity,
            expires_at=self._clock() + timedelta(seconds=self._ttl_seconds),
            deadline=now + self._ttl_seconds,
        )
        self._store(capability)
        return WorkspaceCreatePreview(
            session_id=session_id,
            preview_id=capability.preview_id,
            path=capability.path,
            proposed_revision=capability.proposed_revision,
            line_ending=capability.line_ending,
            byte_size=len(disk_content.encode("utf-8")),
            diff=rendered,
            expires_at=capability.expires_at,
        )

    def apply_create(
        self,
        session_id: str,
        preview_id: str,
        tools: WorkspaceTools,
        command: WorkspaceCreateApplyCommand,
    ) -> WorkspaceCreateApplyResult:
        capability = self._take(session_id, preview_id, _CreateCapability)
        assert isinstance(capability, _CreateCapability)
        exact = (
            self._matches(capability.path, command.path)
            and self._matches(capability.proposed_revision, command.proposed_revision)
            and capability.line_ending is command.line_ending
        )
        disk_content = self._disk_content(command.content, command.line_ending)
        proposed = hashlib.sha256(disk_content.encode("utf-8")).hexdigest()
        if not exact or not self._matches(proposed, capability.proposed_revision):
            raise LocalAgentError("workspace_lifecycle_preview_mismatch")
        prepared = PreparedWrite(
            path=capability.path,
            content=disk_content,
            preview="",
            base_sha256=None,
            base_identity=None,
            parent_identity=capability.parent_identity,
            proposed_sha256=capability.proposed_revision,
            existed=False,
            mode=None,
            base_content=None,
            base_byte_size=0,
        )
        outcome = tools.apply_prepared_write(prepared)
        if not outcome.ok:
            if outcome.code == "workspace_verification_failed":
                self._block(session_id)
            raise LocalAgentError(outcome.code or "workspace_apply_failed")
        receipt = outcome.write_receipt
        if (
            receipt is None
            or receipt.state != "verified"
            or receipt.operation != "created"
            or receipt.before_sha256 is not None
            or receipt.after_sha256 != capability.proposed_revision
            or receipt.path != capability.path
            or receipt.byte_size is None
        ):
            self._block(session_id)
            raise LocalAgentError("workspace_verification_failed")
        return WorkspaceCreateApplyResult(
            session_id=session_id,
            path=receipt.path,
            revision=receipt.after_sha256,
            byte_size=receipt.byte_size,
        )

    def preview_directory_create(
        self,
        session_id: str,
        tools: WorkspaceTools,
        command: WorkspaceDirectoryCreatePreviewCommand,
    ) -> WorkspaceDirectoryCreatePreview:
        with self._lock:
            self._ensure_available_locked(session_id)
        prepared = tools.prepare_directory_create(command.path)
        now = self._monotonic()
        capability = _DirectoryCreateCapability(
            preview_id=uuid.uuid4().hex,
            session_id=session_id,
            path=prepared.path,
            parent_identity=prepared.parent_identity,
            expires_at=self._clock() + timedelta(seconds=self._ttl_seconds),
            deadline=now + self._ttl_seconds,
        )
        self._store(capability)
        return WorkspaceDirectoryCreatePreview(
            session_id=session_id,
            preview_id=capability.preview_id,
            path=capability.path,
            expires_at=capability.expires_at,
        )

    def apply_directory_create(
        self,
        session_id: str,
        preview_id: str,
        tools: WorkspaceTools,
        command: WorkspaceDirectoryCreateApplyCommand,
    ) -> WorkspaceDirectoryCreateApplyResult:
        capability = self._take(
            session_id, preview_id, _DirectoryCreateCapability
        )
        assert isinstance(capability, _DirectoryCreateCapability)
        if not self._matches(capability.path, command.path):
            raise LocalAgentError("workspace_lifecycle_preview_mismatch")
        outcome = tools.apply_prepared_directory_create(
            PreparedDirectoryCreate(
                path=capability.path,
                parent_identity=capability.parent_identity,
            )
        )
        if outcome.state != "verified":
            if outcome.state == "unverified":
                self._block(session_id)
            raise LocalAgentError(
                outcome.code or "workspace_directory_create_failed"
            )
        return WorkspaceDirectoryCreateApplyResult(
            session_id=session_id,
            path=capability.path,
        )

    def preview_directory_move(
        self,
        session_id: str,
        tools: WorkspaceTools,
        command: WorkspaceDirectoryMovePreviewCommand,
    ) -> WorkspaceDirectoryMovePreview:
        with self._lock:
            self._ensure_available_locked(session_id)
        prepared = tools.prepare_directory_move(
            command.source_path, command.target_path
        )
        now = self._monotonic()
        capability = _DirectoryMoveCapability(
            preview_id=uuid.uuid4().hex,
            session_id=session_id,
            source_path=prepared.source_path,
            target_path=prepared.target_path,
            source_identity=prepared.source_identity,
            source_parent_identity=prepared.source_parent_identity,
            target_parent_identity=prepared.target_parent_identity,
            expires_at=self._clock() + timedelta(seconds=self._ttl_seconds),
            deadline=now + self._ttl_seconds,
        )
        self._store(capability)
        return WorkspaceDirectoryMovePreview(
            session_id=session_id,
            preview_id=capability.preview_id,
            source_path=capability.source_path,
            target_path=capability.target_path,
            expires_at=capability.expires_at,
        )

    def apply_directory_move(
        self,
        session_id: str,
        preview_id: str,
        tools: WorkspaceTools,
        command: WorkspaceDirectoryMoveApplyCommand,
    ) -> WorkspaceDirectoryMoveApplyResult:
        capability = self._take(
            session_id, preview_id, _DirectoryMoveCapability
        )
        assert isinstance(capability, _DirectoryMoveCapability)
        if not (
            self._matches(capability.source_path, command.source_path)
            and self._matches(capability.target_path, command.target_path)
        ):
            raise LocalAgentError("workspace_lifecycle_preview_mismatch")
        outcome = tools.apply_prepared_directory_move(
            PreparedDirectoryMove(
                source_path=capability.source_path,
                target_path=capability.target_path,
                source_identity=capability.source_identity,
                source_parent_identity=capability.source_parent_identity,
                target_parent_identity=capability.target_parent_identity,
            )
        )
        if outcome.state != "verified":
            if outcome.state == "unverified":
                self._block(session_id)
            raise LocalAgentError(
                outcome.code or "workspace_directory_move_failed"
            )
        return WorkspaceDirectoryMoveApplyResult(
            session_id=session_id,
            source_path=capability.source_path,
            target_path=capability.target_path,
        )

    def preview_file_trash(
        self,
        session_id: str,
        tools: WorkspaceTools,
        command: WorkspaceFileTrashPreviewCommand,
    ) -> WorkspaceFileTrashPreview:
        with self._lock:
            self._ensure_available_locked(session_id)
        prepared = tools.prepare_file_trash(command.path)
        if not self._matches(prepared.source_sha256, command.expected_revision):
            raise LocalAgentError("workspace_revision_changed")
        now = self._monotonic()
        capability = _FileTrashCapability(
            preview_id=uuid.uuid4().hex,
            session_id=session_id,
            path=prepared.path,
            expected_revision=prepared.source_sha256,
            source_identity=prepared.source_identity,
            parent_identity=prepared.parent_identity,
            byte_size=prepared.byte_size,
            mode=prepared.mode,
            expires_at=self._clock() + timedelta(seconds=self._ttl_seconds),
            deadline=now + self._ttl_seconds,
        )
        self._store(capability)
        return WorkspaceFileTrashPreview(
            session_id=session_id,
            preview_id=capability.preview_id,
            path=capability.path,
            expected_revision=capability.expected_revision,
            byte_size=capability.byte_size,
            expires_at=capability.expires_at,
        )

    def apply_file_trash(
        self,
        session_id: str,
        preview_id: str,
        tools: WorkspaceTools,
        command: WorkspaceFileTrashApplyCommand,
    ) -> WorkspaceFileTrashApplyResult:
        capability = self._take(session_id, preview_id, _FileTrashCapability)
        assert isinstance(capability, _FileTrashCapability)
        if not (
            self._matches(capability.path, command.path)
            and self._matches(capability.expected_revision, command.expected_revision)
        ):
            raise LocalAgentError("workspace_lifecycle_preview_mismatch")
        outcome = tools.apply_prepared_file_trash(
            PreparedFileTrash(
                path=capability.path,
                source_sha256=capability.expected_revision,
                source_identity=capability.source_identity,
                parent_identity=capability.parent_identity,
                byte_size=capability.byte_size,
                mode=capability.mode,
            )
        )
        if outcome.state != "verified":
            if outcome.state == "unverified":
                self._block(session_id)
            raise LocalAgentError(outcome.code or "workspace_file_trash_failed")
        if (
            outcome.revision != capability.expected_revision
            or outcome.byte_size != capability.byte_size
        ):
            self._block(session_id)
            raise LocalAgentError("workspace_file_trash_unverified")
        return WorkspaceFileTrashApplyResult(
            session_id=session_id,
            path=capability.path,
            revision=capability.expected_revision,
            byte_size=capability.byte_size,
        )

    def preview_move(
        self,
        session_id: str,
        tools: WorkspaceTools,
        command: WorkspaceMovePreviewCommand,
    ) -> WorkspaceMovePreview:
        with self._lock:
            self._ensure_available_locked(session_id)
        prepared = tools.prepare_move(command.source_path, command.target_path)
        if not self._matches(prepared.source_sha256, command.expected_revision):
            raise LocalAgentError("workspace_revision_changed")
        now = self._monotonic()
        capability = _MoveCapability(
            preview_id=uuid.uuid4().hex,
            session_id=session_id,
            source_path=prepared.source_path,
            target_path=prepared.target_path,
            expected_revision=prepared.source_sha256,
            source_identity=prepared.source_identity,
            source_parent_identity=prepared.source_parent_identity,
            target_parent_identity=prepared.target_parent_identity,
            byte_size=prepared.byte_size,
            mode=prepared.mode,
            expires_at=self._clock() + timedelta(seconds=self._ttl_seconds),
            deadline=now + self._ttl_seconds,
        )
        self._store(capability)
        return WorkspaceMovePreview(
            session_id=session_id,
            preview_id=capability.preview_id,
            source_path=capability.source_path,
            target_path=capability.target_path,
            expected_revision=capability.expected_revision,
            byte_size=capability.byte_size,
            expires_at=capability.expires_at,
        )

    def apply_move(
        self,
        session_id: str,
        preview_id: str,
        tools: WorkspaceTools,
        command: WorkspaceMoveApplyCommand,
    ) -> WorkspaceMoveApplyResult:
        capability = self._take(session_id, preview_id, _MoveCapability)
        assert isinstance(capability, _MoveCapability)
        if not (
            self._matches(capability.source_path, command.source_path)
            and self._matches(capability.target_path, command.target_path)
            and self._matches(capability.expected_revision, command.expected_revision)
        ):
            raise LocalAgentError("workspace_lifecycle_preview_mismatch")
        prepared = PreparedMove(
            source_path=capability.source_path,
            target_path=capability.target_path,
            source_sha256=capability.expected_revision,
            source_identity=capability.source_identity,
            source_parent_identity=capability.source_parent_identity,
            target_parent_identity=capability.target_parent_identity,
            byte_size=capability.byte_size,
            mode=capability.mode,
        )
        outcome = tools.apply_prepared_move(prepared)
        if outcome.state != "verified":
            if outcome.state == "unverified":
                self._block(session_id)
            raise LocalAgentError(outcome.code or "workspace_move_failed")
        if (
            outcome.revision != capability.expected_revision
            or outcome.byte_size != capability.byte_size
        ):
            self._block(session_id)
            raise LocalAgentError("workspace_move_unverified")
        return WorkspaceMoveApplyResult(
            session_id=session_id,
            source_path=capability.source_path,
            target_path=capability.target_path,
            revision=capability.expected_revision,
            byte_size=capability.byte_size,
        )


__all__ = (
    "LocalAgentWorkspaceFileLifecycle",
    "MAX_ACTIVE_LIFECYCLE_PREVIEWS_PER_SESSION",
    "WORKSPACE_CREATE_CONFIRMATION",
    "WORKSPACE_DIRECTORY_CREATE_CONFIRMATION",
    "WORKSPACE_DIRECTORY_MOVE_CONFIRMATION",
    "WORKSPACE_FILE_TRASH_CONFIRMATION",
    "WORKSPACE_LIFECYCLE_CONTRACT_VERSION",
    "WORKSPACE_LIFECYCLE_TTL_SECONDS",
    "WORKSPACE_MOVE_CONFIRMATION",
    "WorkspaceCreateApplyCommand",
    "WorkspaceCreateApplyResult",
    "WorkspaceCreatePreview",
    "WorkspaceCreatePreviewCommand",
    "WorkspaceDirectoryCreateApplyCommand",
    "WorkspaceDirectoryCreateApplyResult",
    "WorkspaceDirectoryCreatePreview",
    "WorkspaceDirectoryCreatePreviewCommand",
    "WorkspaceDirectoryMoveApplyCommand",
    "WorkspaceDirectoryMoveApplyResult",
    "WorkspaceDirectoryMovePreview",
    "WorkspaceDirectoryMovePreviewCommand",
    "WorkspaceFileTrashApplyCommand",
    "WorkspaceFileTrashApplyResult",
    "WorkspaceFileTrashPreview",
    "WorkspaceFileTrashPreviewCommand",
    "WorkspaceMoveApplyCommand",
    "WorkspaceMoveApplyResult",
    "WorkspaceMovePreview",
    "WorkspaceMovePreviewCommand",
)
