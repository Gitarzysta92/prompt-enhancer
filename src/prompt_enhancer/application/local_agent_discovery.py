"""Content-free, bounded workspace and Git discovery for one Agent session."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .local_agent_limits import MAX_DISCOVERY_FILES, MAX_FILE_WRITE_BYTES, MAX_GIT_STATUS_ENTRIES
from .local_agent_workspace import WorkspaceTools


WORKSPACE_DISCOVERY_CONTRACT_VERSION = "local-agent-workspace-discovery.v1"
_ID_PATTERN = r"^[0-9a-f]{32}$"


class WorkspaceInventoryCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class WorkspaceInventoryReason(StrEnum):
    DEADLINE_REACHED = "deadline_reached"
    DEPTH_LIMIT = "depth_limit"
    DISPLAY_LIMIT = "display_limit"
    ENTRY_LIMIT = "entry_limit"
    EXCLUDED_DIRECTORIES = "excluded_directories"
    LINK_OR_REPARSE_ENTRIES = "link_or_reparse_entries"
    UNAVAILABLE_ENTRIES = "unavailable_entries"
    UNREPRESENTABLE_ENTRIES = "unrepresentable_entries"


class WorkspaceGitState(StrEnum):
    AVAILABLE = "available"
    NOT_REPOSITORY = "not_repository"
    UNAVAILABLE = "unavailable"


class WorkspaceGitCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class WorkspaceGitReason(StrEnum):
    COMMAND_CLEANUP_UNCONFIRMED = "command_cleanup_unconfirmed"
    COMMAND_IN_PROGRESS = "command_in_progress"
    DEADLINE_REACHED = "deadline_reached"
    DISPLAY_LIMIT = "display_limit"
    EXECUTABLE_UNAVAILABLE = "executable_unavailable"
    EXCLUDED_PATHS = "excluded_paths"
    OUTPUT_LIMIT = "output_limit"
    REPOSITORY_CHANGED = "repository_changed"
    REPOSITORY_LAYOUT_UNSUPPORTED = "repository_layout_unsupported"
    STATUS_FAILED = "status_failed"
    STATUS_INVALID = "status_invalid"
    UNREPRESENTABLE_PATHS = "unrepresentable_paths"


class WorkspaceGitChangeKind(StrEnum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNTRACKED = "untracked"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


def _relative_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value
        or len(value) > 1024
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in parts)
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
        or (len(value) >= 2 and value[0].isalpha() and value[1] == ":")
    ):
        raise ValueError("workspace discovery path must stay relative")
    return value


class WorkspaceDiscoveryFile(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    byte_size: int = Field(ge=0, le=2**53 - 1)
    editable_candidate: bool

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def coherent_editability(self) -> "WorkspaceDiscoveryFile":
        if self.editable_candidate and self.byte_size > MAX_FILE_WRITE_BYTES:
            raise ValueError("oversized discovery file cannot be editable")
        return self


class WorkspaceGitChange(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    kind: WorkspaceGitChangeKind
    staged: bool
    unstaged: bool

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def coherent_state(self) -> "WorkspaceGitChange":
        if self.kind is WorkspaceGitChangeKind.UNTRACKED and (self.staged or self.unstaged):
            raise ValueError("untracked entry cannot claim index/worktree staging")
        if self.kind is WorkspaceGitChangeKind.CONFLICTED and not (self.staged and self.unstaged):
            raise ValueError("conflicted entry must carry both sides")
        return self


class WorkspaceDiscovery(StrictModel):
    contract_version: Literal[WORKSPACE_DISCOVERY_CONTRACT_VERSION] = WORKSPACE_DISCOVERY_CONTRACT_VERSION
    session_id: str = Field(pattern=_ID_PATTERN)
    scope: Literal["selected_workspace"]
    inventory_coverage: WorkspaceInventoryCoverage
    inventory_reasons: tuple[WorkspaceInventoryReason, ...] = Field(max_length=len(WorkspaceInventoryReason))
    scanned_entry_count: int = Field(ge=0, le=20_000)
    observed_file_count: int = Field(ge=0, le=20_000)
    files: tuple[WorkspaceDiscoveryFile, ...] = Field(max_length=MAX_DISCOVERY_FILES)
    git_state: WorkspaceGitState
    git_coverage: WorkspaceGitCoverage
    git_reasons: tuple[WorkspaceGitReason, ...] = Field(max_length=len(WorkspaceGitReason))
    git_change_count: int | None = Field(ge=0)
    git_changes: tuple[WorkspaceGitChange, ...] = Field(max_length=MAX_GIT_STATUS_ENTRIES)

    @model_validator(mode="after")
    def coherent_snapshot(self) -> "WorkspaceDiscovery":
        inventory_reasons = tuple(reason.value for reason in self.inventory_reasons)
        if len(set(inventory_reasons)) != len(inventory_reasons) or inventory_reasons != tuple(sorted(inventory_reasons)):
            raise ValueError("inventory reasons must be unique and sorted")
        file_paths = tuple(item.path for item in self.files)
        if len(set(file_paths)) != len(file_paths) or file_paths != tuple(
            sorted(file_paths, key=lambda path: path.encode("utf-8"))
        ):
            raise ValueError("inventory files must be unique and sorted")
        if self.observed_file_count < len(self.files) or self.scanned_entry_count < self.observed_file_count:
            raise ValueError("inventory counts were incoherent")
        if self.inventory_coverage is WorkspaceInventoryCoverage.COMPLETE:
            if self.inventory_reasons or self.observed_file_count != len(self.files):
                raise ValueError("complete inventory cannot omit evidence")
        elif not self.inventory_reasons:
            raise ValueError("partial inventory needs a fixed reason")

        git_reasons = tuple(reason.value for reason in self.git_reasons)
        if len(set(git_reasons)) != len(git_reasons) or git_reasons != tuple(sorted(git_reasons)):
            raise ValueError("Git reasons must be unique and sorted")
        git_paths = tuple(item.path for item in self.git_changes)
        if len(set(git_paths)) != len(git_paths) or git_paths != tuple(
            sorted(git_paths, key=lambda path: path.encode("utf-8"))
        ):
            raise ValueError("Git changes must be unique and sorted")
        if self.git_state is WorkspaceGitState.AVAILABLE:
            if self.git_coverage not in {WorkspaceGitCoverage.COMPLETE, WorkspaceGitCoverage.PARTIAL}:
                raise ValueError("available Git state needs available coverage")
            if self.git_change_count is None or self.git_change_count < len(self.git_changes):
                raise ValueError("available Git counts were incoherent")
            if self.git_coverage is WorkspaceGitCoverage.COMPLETE:
                if self.git_reasons or self.git_change_count != len(self.git_changes):
                    raise ValueError("complete Git state cannot omit changes")
            elif not self.git_reasons:
                raise ValueError("partial Git state needs a fixed reason")
        elif self.git_state is WorkspaceGitState.NOT_REPOSITORY:
            if (
                self.git_coverage is not WorkspaceGitCoverage.NOT_APPLICABLE
                or self.git_reasons
                or self.git_change_count != 0
                or self.git_changes
            ):
                raise ValueError("non-repository Git state was incoherent")
        elif (
            self.git_coverage is not WorkspaceGitCoverage.UNAVAILABLE
            or not self.git_reasons
            or self.git_change_count is not None
            or self.git_changes
        ):
            raise ValueError("unavailable Git state was incoherent")
        return self


class LocalAgentWorkspaceDiscovery:
    """Build one current snapshot; no content or result is retained."""

    def snapshot(self, session_id: str, tools: WorkspaceTools) -> WorkspaceDiscovery:
        inventory = tools.discovery_inventory()
        git = tools.git_status()
        return WorkspaceDiscovery(
            session_id=session_id,
            scope="selected_workspace",
            inventory_coverage=inventory.coverage,
            inventory_reasons=inventory.reasons,
            scanned_entry_count=inventory.scanned_entry_count,
            observed_file_count=inventory.observed_file_count,
            files=tuple(
                WorkspaceDiscoveryFile(
                    path=item.path,
                    byte_size=item.byte_size,
                    editable_candidate=item.editable_candidate,
                )
                for item in inventory.files
            ),
            git_state=git.state,
            git_coverage=git.coverage,
            git_reasons=git.reasons,
            git_change_count=git.change_count,
            git_changes=tuple(
                WorkspaceGitChange(
                    path=item.path,
                    kind=item.kind,
                    staged=item.staged,
                    unstaged=item.unstaged,
                )
                for item in git.changes
            ),
        )


__all__ = (
    "LocalAgentWorkspaceDiscovery",
    "WORKSPACE_DISCOVERY_CONTRACT_VERSION",
    "WorkspaceDiscovery",
    "WorkspaceDiscoveryFile",
    "WorkspaceGitChange",
)
