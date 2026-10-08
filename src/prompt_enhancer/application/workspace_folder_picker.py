"""User-driven, content-free workspace folder selection for the local UI."""

from __future__ import annotations

from collections.abc import Callable
from importlib.util import find_spec
import os
from pathlib import PurePosixPath, PureWindowsPath
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


WORKSPACE_FOLDER_PICKER_VERSION = "local-workspace-folder-picker.v1"


class WorkspaceFolderPickerCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["local-workspace-folder-picker.v1"] = (
        WORKSPACE_FOLDER_PICKER_VERSION
    )
    available: bool
    mode: Literal["server_native_dialog", "unavailable"]

    @model_validator(mode="after")
    def validate_mode(self) -> "WorkspaceFolderPickerCapability":
        if self.available != (self.mode == "server_native_dialog"):
            raise ValueError("workspace folder picker capability is inconsistent")
        return self


class WorkspaceFolderPick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["local-workspace-folder-picker.v1"] = (
        WORKSPACE_FOLDER_PICKER_VERSION
    )
    status: Literal["selected", "cancelled", "busy", "unavailable"]
    path: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "WorkspaceFolderPick":
        if self.status == "selected":
            if self.path is None or not _is_absolute_workspace_path(self.path):
                raise ValueError("selected workspace folder path is invalid")
        elif self.path is not None:
            raise ValueError("content-free folder picker result cannot include a path")
        return self


def _is_absolute_workspace_path(value: str) -> bool:
    if (
        not value
        or len(value) > 1024
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


def _windows_directory_dialog() -> str | None:
    """Open one in-process Windows folder dialog and return only its selection."""

    if os.name != "nt":
        raise RuntimeError("workspace_folder_picker_unavailable")
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update_idletasks()
        selected = filedialog.askdirectory(
            parent=root,
            mustexist=True,
            title="Choose a workspace folder",
        )
        return selected or None
    finally:
        root.destroy()


class LocalWorkspaceFolderPicker:
    """Serialize folder dialogs and keep exceptions and selections ephemeral."""

    def __init__(
        self,
        dialog: Callable[[], str | None] | None,
    ) -> None:
        self._dialog = dialog
        self._dialog_lock = Lock()

    @property
    def available(self) -> bool:
        return self._dialog is not None

    def capability(self) -> WorkspaceFolderPickerCapability:
        return WorkspaceFolderPickerCapability(
            available=self.available,
            mode="server_native_dialog" if self.available else "unavailable",
        )

    def choose(self) -> WorkspaceFolderPick:
        dialog = self._dialog
        if dialog is None:
            return WorkspaceFolderPick(status="unavailable")
        if not self._dialog_lock.acquire(blocking=False):
            return WorkspaceFolderPick(status="busy")
        try:
            try:
                selected = dialog()
            except Exception:
                return WorkspaceFolderPick(status="unavailable")
            if selected is None or selected == "":
                return WorkspaceFolderPick(status="cancelled")
            if not isinstance(selected, str) or not _is_absolute_workspace_path(selected):
                return WorkspaceFolderPick(status="unavailable")
            return WorkspaceFolderPick(status="selected", path=selected)
        finally:
            self._dialog_lock.release()


def create_default_workspace_folder_picker() -> LocalWorkspaceFolderPicker:
    dialog = (
        _windows_directory_dialog
        if os.name == "nt" and find_spec("tkinter") is not None
        else None
    )
    return LocalWorkspaceFolderPicker(dialog)


__all__ = (
    "LocalWorkspaceFolderPicker",
    "WorkspaceFolderPick",
    "WorkspaceFolderPickerCapability",
    "create_default_workspace_folder_picker",
)
