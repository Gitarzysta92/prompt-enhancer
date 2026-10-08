"""Session-bound, review-before-apply multi-file workspace transactions.

The capability store retains paths, revisions, identities and line-ending
metadata only. Draft and baseline content remain request-local. Publication is
failure-atomic while the reviewed workspace stays stable: every member is
preflighted, and earlier members are restored if a later publication rejects.
An external race or uncertain cleanup is reported as unverified, never as a
successful commit or rollback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import difflib
import hashlib
import hmac
import os
from pathlib import PurePosixPath, PureWindowsPath
import threading
import time
from typing import Literal
import uuid

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .local_agent_editor import WorkspaceLineEnding
from .local_agent_limits import (
    LocalAgentError,
    MAX_DIFF_CHARS,
    MAX_FILE_WRITE_BYTES,
    MAX_WORKSPACE_TRANSACTION_BYTES,
    MAX_WORKSPACE_TRANSACTION_DIFF_CHARS,
    MAX_WORKSPACE_TRANSACTION_FILES,
)
from .local_agent_workspace import PreparedWrite, WorkspaceTools


WORKSPACE_TRANSACTION_CONTRACT_VERSION = "local-agent-workspace-transaction.v2"
WORKSPACE_TRANSACTION_APPLY_CONFIRMATION = "apply_reviewed_workspace_transaction"
WORKSPACE_TRANSACTION_PREVIEW_TTL_SECONDS = 120
MAX_ACTIVE_TRANSACTION_PREVIEWS_PER_SESSION = 4
_REVISION_PATTERN = r"^[0-9a-f]{64}$"
_ID_PATTERN = r"^[0-9a-f]{32}$"

TransactionState = Literal["committed", "rejected", "rolled_back", "unverified"]
TransactionOperation = Literal["create", "edit"]
TransactionFileState = Literal[
    "committed",
    "restored",
    "removed",
    "not_applied",
    "unverified",
]
TransactionReason = Literal[
    "workspace_write_failed",
    "workspace_cleanup_failed",
    "workspace_verification_failed",
    "workspace_revision_changed",
    "workspace_file_unavailable",
    "workspace_transaction_unverified",
    "tool_cancelled",
]
_ROLLED_BACK_REASONS = frozenset(
    {
        "workspace_write_failed",
        "workspace_cleanup_failed",
        "workspace_verification_failed",
        "workspace_revision_changed",
        "workspace_file_unavailable",
        "tool_cancelled",
    }
)


def _relative_path(value: str) -> str:
    windows, posix = PureWindowsPath(value), PurePosixPath(value)
    if (
        not value
        or len(value) > 1024
        or value in {".", ".."}
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 or ord(character) == 127 or 0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        raise ValueError("invalid transaction path")
    return value


def _validate_unique_paths(changes: tuple[object, ...]) -> tuple[object, ...]:
    paths = [getattr(change, "path", "") for change in changes]
    identities = [path.casefold() for path in paths]
    if len(identities) != len(set(identities)):
        raise ValueError("transaction paths must be unique")
    return changes


def _normalized_content(value: str) -> str:
    if "\x00" in value or "\r" in value:
        raise ValueError("transaction accepts normalized UTF-8 text only")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("transaction accepts normalized UTF-8 text only") from error
    if len(encoded) > MAX_FILE_WRITE_BYTES:
        raise ValueError("transaction file exceeds the edit limit")
    return value


class WorkspaceTransactionChangeCommand(StrictModel):
    operation: TransactionOperation = "edit"
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_FILE_WRITE_BYTES)
    expected_revision: str | None = Field(default=None, pattern=_REVISION_PATTERN)
    line_ending: WorkspaceLineEnding

    _valid_path = field_validator("path")(_relative_path)
    _valid_content = field_validator("content")(_normalized_content)

    @model_validator(mode="after")
    def coherent_operation(self) -> "WorkspaceTransactionChangeCommand":
        if self.operation == "edit" and self.expected_revision is None:
            raise ValueError("transaction edits require an exact source revision")
        if self.operation == "create" and self.expected_revision is not None:
            raise ValueError("transaction creates require an absent source")
        return self


class WorkspaceTransactionPreviewCommand(StrictModel):
    changes: tuple[WorkspaceTransactionChangeCommand, ...] = Field(
        min_length=2,
        max_length=MAX_WORKSPACE_TRANSACTION_FILES,
    )

    @field_validator("changes")
    @classmethod
    def unique_paths(
        cls,
        value: tuple[WorkspaceTransactionChangeCommand, ...],
    ) -> tuple[WorkspaceTransactionChangeCommand, ...]:
        return _validate_unique_paths(value)  # type: ignore[return-value]


class WorkspaceTransactionPreviewFile(StrictModel):
    operation: TransactionOperation
    path: str = Field(min_length=1, max_length=1024)
    expected_revision: str | None = Field(default=None, pattern=_REVISION_PATTERN)
    proposed_revision: str = Field(pattern=_REVISION_PATTERN)
    line_ending: WorkspaceLineEnding
    proposed_byte_size: int = Field(strict=True, ge=0, le=MAX_FILE_WRITE_BYTES)
    added_lines: int = Field(strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    removed_lines: int = Field(strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    diff: str = Field(min_length=1, max_length=MAX_DIFF_CHARS)

    _valid_path = field_validator("path")(_relative_path)

    @model_validator(mode="after")
    def changed_revision(self) -> "WorkspaceTransactionPreviewFile":
        if self.operation == "edit" and self.expected_revision is None:
            raise ValueError("transaction edit previews require a source revision")
        if self.operation == "create" and self.expected_revision is not None:
            raise ValueError("transaction create previews require an absent source")
        if self.expected_revision == self.proposed_revision:
            raise ValueError("transaction preview member must change")
        return self


class WorkspaceTransactionPreview(StrictModel):
    contract_version: Literal[WORKSPACE_TRANSACTION_CONTRACT_VERSION] = WORKSPACE_TRANSACTION_CONTRACT_VERSION
    session_id: str = Field(pattern=_ID_PATTERN)
    plan_id: str = Field(pattern=_ID_PATTERN)
    file_count: int = Field(strict=True, ge=2, le=MAX_WORKSPACE_TRANSACTION_FILES)
    total_byte_size: int = Field(strict=True, ge=0, le=MAX_WORKSPACE_TRANSACTION_BYTES)
    added_lines: int = Field(strict=True, ge=0, le=MAX_WORKSPACE_TRANSACTION_BYTES + MAX_WORKSPACE_TRANSACTION_FILES)
    removed_lines: int = Field(strict=True, ge=0, le=MAX_WORKSPACE_TRANSACTION_BYTES + MAX_WORKSPACE_TRANSACTION_FILES)
    files: tuple[WorkspaceTransactionPreviewFile, ...] = Field(
        min_length=2,
        max_length=MAX_WORKSPACE_TRANSACTION_FILES,
    )
    expires_at: datetime

    @model_validator(mode="after")
    def coherent_preview(self) -> "WorkspaceTransactionPreview":
        paths = [item.path for item in self.files]
        if paths != sorted(paths, key=lambda path: path.encode("utf-8")):
            raise ValueError("transaction preview files must be byte-sorted")
        if len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("transaction preview paths must be unique")
        if (
            self.file_count != len(self.files)
            or self.total_byte_size != sum(item.proposed_byte_size for item in self.files)
            or self.added_lines != sum(item.added_lines for item in self.files)
            or self.removed_lines != sum(item.removed_lines for item in self.files)
            or sum(len(item.diff) for item in self.files) > MAX_WORKSPACE_TRANSACTION_DIFF_CHARS
        ):
            raise ValueError("transaction preview totals are incoherent")
        return self


class WorkspaceTransactionApplyChange(WorkspaceTransactionChangeCommand):
    proposed_revision: str = Field(pattern=_REVISION_PATTERN)

    @model_validator(mode="after")
    def changed_revision(self) -> "WorkspaceTransactionApplyChange":
        if self.expected_revision == self.proposed_revision:
            raise ValueError("transaction apply member must change")
        return self


class WorkspaceTransactionApplyCommand(StrictModel):
    changes: tuple[WorkspaceTransactionApplyChange, ...] = Field(
        min_length=2,
        max_length=MAX_WORKSPACE_TRANSACTION_FILES,
    )
    confirmation: Literal[WORKSPACE_TRANSACTION_APPLY_CONFIRMATION]

    @field_validator("changes")
    @classmethod
    def unique_paths(
        cls,
        value: tuple[WorkspaceTransactionApplyChange, ...],
    ) -> tuple[WorkspaceTransactionApplyChange, ...]:
        return _validate_unique_paths(value)  # type: ignore[return-value]


class WorkspaceTransactionFileResult(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    state: TransactionFileState
    revision: str | None = Field(default=None, pattern=_REVISION_PATTERN)
    byte_size: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES)

    _valid_path = field_validator("path")(_relative_path)

    @model_validator(mode="after")
    def coherent_file(self) -> "WorkspaceTransactionFileResult":
        verified = self.state in {"committed", "restored"}
        if verified is not (self.revision is not None and self.byte_size is not None):
            raise ValueError("transaction file result is incoherent")
        return self


class WorkspaceTransactionApplyResult(StrictModel):
    contract_version: Literal[WORKSPACE_TRANSACTION_CONTRACT_VERSION] = WORKSPACE_TRANSACTION_CONTRACT_VERSION
    session_id: str = Field(pattern=_ID_PATTERN)
    plan_id: str = Field(pattern=_ID_PATTERN)
    state: TransactionState
    reason: TransactionReason | None = None
    file_count: int = Field(strict=True, ge=2, le=MAX_WORKSPACE_TRANSACTION_FILES)
    files: tuple[WorkspaceTransactionFileResult, ...] = Field(
        min_length=2,
        max_length=MAX_WORKSPACE_TRANSACTION_FILES,
    )

    @model_validator(mode="after")
    def coherent_result(self) -> "WorkspaceTransactionApplyResult":
        paths = [item.path for item in self.files]
        states = [item.state for item in self.files]
        if (
            self.file_count != len(self.files)
            or paths != sorted(paths, key=lambda path: path.encode("utf-8"))
            or len({path.casefold() for path in paths}) != len(paths)
        ):
            raise ValueError("transaction result files are incoherent")
        if self.state == "committed":
            valid = self.reason is None and all(state == "committed" for state in states)
        elif self.state == "rejected":
            valid = self.reason in _ROLLED_BACK_REASONS and all(state == "not_applied" for state in states)
        elif self.state == "rolled_back":
            valid = (
                self.reason in _ROLLED_BACK_REASONS
                and any(state in {"restored", "removed"} for state in states)
                and all(
                    state in {"restored", "removed", "not_applied"}
                    for state in states
                )
            )
        else:
            valid = self.reason == "workspace_transaction_unverified" and "unverified" in states
        if not valid:
            raise ValueError("transaction result state is incoherent")
        return self


@dataclass(frozen=True, slots=True)
class _TransactionCapabilityFile:
    operation: TransactionOperation
    path: str
    expected_revision: str | None
    proposed_revision: str
    line_ending: WorkspaceLineEnding
    base_identity: tuple[int, int] | None
    parent_identity: tuple[int, int]
    mode: int | None


@dataclass(frozen=True, slots=True)
class _TransactionCapability:
    plan_id: str
    session_id: str
    files: tuple[_TransactionCapabilityFile, ...]
    expires_at: datetime
    deadline: float


def _disk_content(content: str, line_ending: WorkspaceLineEnding) -> str:
    return content.replace("\n", "\r\n") if line_ending is WorkspaceLineEnding.CRLF else content


def _line_counts(before: str, after: str) -> tuple[int, int]:
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
    return additions, removals


class LocalAgentWorkspaceTransactionEditor:
    """Short-lived metadata capabilities for reviewed create/edit plans."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        ttl_seconds: int = WORKSPACE_TRANSACTION_PREVIEW_TTL_SECONDS,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._ttl_seconds = max(1, min(int(ttl_seconds), WORKSPACE_TRANSACTION_PREVIEW_TTL_SECONDS))
        self._capabilities: dict[str, _TransactionCapability] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _matches(left: str, right: str) -> bool:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

    def _prune_locked(self, now: float) -> None:
        for plan_id in [
            item.plan_id for item in self._capabilities.values() if item.deadline <= now
        ]:
            self._capabilities.pop(plan_id, None)

    def discard_session(self, session_id: str) -> None:
        with self._lock:
            for plan_id in [
                item.plan_id for item in self._capabilities.values() if item.session_id == session_id
            ]:
                self._capabilities.pop(plan_id, None)

    def discard(self, session_id: str, plan_id: str) -> None:
        with self._lock:
            capability = self._capabilities.get(plan_id)
            if capability is not None and capability.session_id == session_id:
                self._capabilities.pop(plan_id, None)

    def preview(
        self,
        session_id: str,
        tools: WorkspaceTools,
        command: WorkspaceTransactionPreviewCommand,
    ) -> WorkspaceTransactionPreview:
        represented: list[WorkspaceTransactionPreviewFile] = []
        capabilities: list[_TransactionCapabilityFile] = []
        total_bytes = total_diff = additions = removals = 0
        for change in sorted(command.changes, key=lambda item: item.path.encode("utf-8")):
            disk_content = _disk_content(change.content, change.line_ending)
            if change.operation == "edit":
                try:
                    current = tools.read_text_snapshot(change.path)
                except LocalAgentError as error:
                    if error.code == "workspace_path_not_found":
                        raise LocalAgentError(
                            "workspace_existing_file_required"
                        ) from None
                    raise
                if (
                    change.expected_revision is None
                    or not self._matches(current.revision, change.expected_revision)
                    or WorkspaceLineEnding(current.line_ending) is not change.line_ending
                ):
                    raise LocalAgentError("workspace_transaction_changed")
                prepared = tools.prepare_write(current.path, disk_content)
                if (
                    not prepared.existed
                    or prepared.base_sha256 is None
                    or prepared.base_identity is None
                    or prepared.mode is None
                    or not self._matches(
                        prepared.base_sha256,
                        change.expected_revision,
                    )
                ):
                    raise LocalAgentError("workspace_transaction_changed")
            else:
                prepared = tools.prepare_write(change.path, disk_content)
                if (
                    prepared.existed
                    or prepared.base_sha256 is not None
                    or prepared.base_identity is not None
                    or prepared.mode is not None
                ):
                    raise LocalAgentError("workspace_transaction_changed")
            if (
                prepared.base_sha256 is not None
                and self._matches(prepared.proposed_sha256, prepared.base_sha256)
            ):
                raise LocalAgentError("workspace_transaction_no_change")
            if prepared.preview == "(no change)":
                raise LocalAgentError("workspace_change_not_reviewable")
            encoded_size = len(disk_content.encode("utf-8", errors="strict"))
            added, removed = _line_counts(prepared.base_content or "", prepared.content)
            total_bytes += encoded_size
            total_diff += len(prepared.preview)
            additions += added
            removals += removed
            if total_bytes > MAX_WORKSPACE_TRANSACTION_BYTES:
                raise LocalAgentError("workspace_transaction_too_large")
            if total_diff > MAX_WORKSPACE_TRANSACTION_DIFF_CHARS:
                raise LocalAgentError("workspace_transaction_diff_too_large")
            represented.append(
                WorkspaceTransactionPreviewFile(
                    operation=change.operation,
                    path=prepared.path,
                    expected_revision=prepared.base_sha256,
                    proposed_revision=prepared.proposed_sha256,
                    line_ending=change.line_ending,
                    proposed_byte_size=encoded_size,
                    added_lines=added,
                    removed_lines=removed,
                    diff=prepared.preview,
                )
            )
            capabilities.append(
                _TransactionCapabilityFile(
                    operation=change.operation,
                    path=prepared.path,
                    expected_revision=prepared.base_sha256,
                    proposed_revision=prepared.proposed_sha256,
                    line_ending=change.line_ending,
                    base_identity=prepared.base_identity,
                    parent_identity=prepared.parent_identity,
                    mode=prepared.mode,
                )
            )

        now = self._monotonic()
        expires_at = self._clock() + timedelta(seconds=self._ttl_seconds)
        capability = _TransactionCapability(
            plan_id=uuid.uuid4().hex,
            session_id=session_id,
            files=tuple(capabilities),
            expires_at=expires_at,
            deadline=now + self._ttl_seconds,
        )
        with self._lock:
            self._prune_locked(now)
            session_items = sorted(
                (item for item in self._capabilities.values() if item.session_id == session_id),
                key=lambda item: item.deadline,
            )
            while len(session_items) >= MAX_ACTIVE_TRANSACTION_PREVIEWS_PER_SESSION:
                oldest = session_items.pop(0)
                self._capabilities.pop(oldest.plan_id, None)
            self._capabilities[capability.plan_id] = capability
        return WorkspaceTransactionPreview(
            session_id=session_id,
            plan_id=capability.plan_id,
            file_count=len(represented),
            total_byte_size=total_bytes,
            added_lines=additions,
            removed_lines=removals,
            files=tuple(represented),
            expires_at=expires_at,
        )

    def apply(
        self,
        session_id: str,
        plan_id: str,
        tools: WorkspaceTools,
        command: WorkspaceTransactionApplyCommand,
    ) -> WorkspaceTransactionApplyResult:
        now = self._monotonic()
        with self._lock:
            capability = self._capabilities.get(plan_id)
            if capability is not None and capability.session_id == session_id:
                self._capabilities.pop(plan_id, None)
        if capability is None or capability.session_id != session_id:
            raise LocalAgentError("workspace_transaction_not_found")
        if capability.deadline <= now:
            raise LocalAgentError("workspace_transaction_expired")

        submitted = sorted(command.changes, key=lambda item: item.path.encode("utf-8"))
        if len(submitted) != len(capability.files):
            raise LocalAgentError("workspace_transaction_mismatch")
        prepared_items: list[PreparedWrite] = []
        for authority, change in zip(capability.files, submitted, strict=True):
            disk_content = _disk_content(change.content, change.line_ending)
            proposed_revision = hashlib.sha256(disk_content.encode("utf-8", errors="strict")).hexdigest()
            exact = (
                authority.operation == change.operation
                and self._matches(authority.path, change.path)
                and authority.expected_revision == change.expected_revision
                and self._matches(authority.proposed_revision, change.proposed_revision)
                and authority.line_ending is change.line_ending
                and self._matches(authority.proposed_revision, proposed_revision)
            )
            if not exact:
                raise LocalAgentError("workspace_transaction_mismatch")
            try:
                prepared = tools.prepare_write(authority.path, disk_content)
            except LocalAgentError:
                raise LocalAgentError("workspace_transaction_changed") from None
            if (
                prepared.path != authority.path
                or prepared.base_sha256 != authority.expected_revision
                or prepared.base_identity != authority.base_identity
                or prepared.parent_identity != authority.parent_identity
                or prepared.proposed_sha256 != authority.proposed_revision
                or prepared.mode != authority.mode
                or prepared.existed is not (authority.operation == "edit")
            ):
                raise LocalAgentError("workspace_transaction_changed")
            prepared_items.append(prepared)

        outcome = tools.apply_prepared_transaction(tuple(prepared_items))
        reason: TransactionReason | None
        if outcome.state == "committed":
            reason = None
        elif outcome.state == "unverified":
            reason = "workspace_transaction_unverified"
        else:
            reason = (
                outcome.reason
                if outcome.reason in _ROLLED_BACK_REASONS
                else "workspace_write_failed"
            )  # type: ignore[assignment]
        return WorkspaceTransactionApplyResult(
            session_id=session_id,
            plan_id=plan_id,
            state=outcome.state,
            reason=reason,
            file_count=len(outcome.files),
            files=tuple(
                WorkspaceTransactionFileResult(
                    path=item.path,
                    state=item.state,
                    revision=item.revision,
                    byte_size=item.byte_size,
                )
                for item in outcome.files
            ),
        )


__all__ = (
    "LocalAgentWorkspaceTransactionEditor",
    "MAX_ACTIVE_TRANSACTION_PREVIEWS_PER_SESSION",
    "WORKSPACE_TRANSACTION_APPLY_CONFIRMATION",
    "WORKSPACE_TRANSACTION_CONTRACT_VERSION",
    "WORKSPACE_TRANSACTION_PREVIEW_TTL_SECONDS",
    "WorkspaceTransactionApplyChange",
    "WorkspaceTransactionApplyCommand",
    "WorkspaceTransactionApplyResult",
    "WorkspaceTransactionChangeCommand",
    "WorkspaceTransactionFileResult",
    "WorkspaceTransactionPreview",
    "WorkspaceTransactionPreviewCommand",
    "WorkspaceTransactionPreviewFile",
)
