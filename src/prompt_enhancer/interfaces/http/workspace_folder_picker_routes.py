"""Browser-gesture-only adapter for the local operating-system folder chooser."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Response

from ...application.workspace_folder_picker import (
    LocalWorkspaceFolderPicker,
    WorkspaceFolderPick,
    WorkspaceFolderPickerCapability,
)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


def create_workspace_folder_picker_router(
    require_local_auth: Callable[..., None],
    require_browser_interaction: Callable[..., None],
    picker: LocalWorkspaceFolderPicker | None,
) -> APIRouter:
    """Expose capability discovery broadly, but chooser launch only to the UI."""

    router = APIRouter(
        prefix="/v1/local-ui/workspace-folder-picker",
        tags=["local-ui"],
    )

    @router.get(
        "",
        response_model=WorkspaceFolderPickerCapability,
        dependencies=[Depends(require_local_auth)],
    )
    def capability(response: Response) -> WorkspaceFolderPickerCapability:
        _private(response)
        if picker is None:
            return WorkspaceFolderPickerCapability(
                available=False,
                mode="unavailable",
            )
        return picker.capability()

    @router.post(
        "",
        response_model=WorkspaceFolderPick,
        dependencies=[Depends(require_browser_interaction)],
    )
    def choose(response: Response) -> WorkspaceFolderPick:
        _private(response)
        if picker is None:
            return WorkspaceFolderPick(status="unavailable")
        return picker.choose()

    return router


__all__ = ("create_workspace_folder_picker_router",)
