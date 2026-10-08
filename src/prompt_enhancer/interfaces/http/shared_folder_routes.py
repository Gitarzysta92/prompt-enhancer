"""Shared team folders (ADR 0018): owner surface under /v1/shared-folders, peer surface under /p2p/v1."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import BaseModel, Field

from ...application.shared_folders import (
    FileContent,
    FolderManifest,
    JoinRequest,
    PeerFolderClient,
    PeerLink,
    PeerLinkList,
    SharedFolder,
    SharedFolderError,
    SharedFolderList,
    SharedFolderService,
    SyncReport,
    WriteFileRequest,
    WriteFileResult,
)

SHARE_TOKEN_HEADER = "X-Share-Token"

_STATUS = {
    "folder_not_found": 422,
    "folder_is_a_drive_root": 422,
    "folder_not_allowed": 403,
    "name_invalid": 422,
    "too_many_shares": 409,
    "too_many_links": 409,
    "share_not_found": 404,
    "share_token_invalid": 401,
    "path_invalid": 422,
    "file_not_found": 404,
    "file_too_large": 413,
    "content_invalid": 422,
    "target_invalid": 422,
    "url_invalid": 422,
    "link_not_found": 404,
    "peer_unreachable": 502,
    "peer_reply_invalid": 502,
}


def _failure(error: SharedFolderError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code})


class ShareFolderBody(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=64)


class PushBody(BaseModel):
    peer_name: str = Field(default="peer", min_length=1, max_length=64)


def create_shared_folder_router(
    require_local_auth: Callable[..., None],
    service: SharedFolderService,
    client: PeerFolderClient,
) -> APIRouter:
    """The owner's management surface; everything here needs the app token."""

    router = APIRouter(prefix="/v1/shared-folders", tags=["shared-folders"], dependencies=[Depends(require_local_auth)])

    @router.post("", response_model=SharedFolder, status_code=201)
    def share(body: ShareFolderBody) -> SharedFolder:
        """Share one folder; the share token appears once in this response and is stored only as a hash."""

        try:
            return service.share(body.path, body.name)
        except SharedFolderError as error:
            raise _failure(error) from None

    @router.get("", response_model=SharedFolderList)
    def list_shares() -> SharedFolderList:
        return service.list()

    @router.delete("/{share_id}", status_code=204)
    def revoke(share_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]) -> Response:
        try:
            service.revoke(share_id)
        except SharedFolderError as error:
            raise _failure(error) from None
        return Response(status_code=204)

    @router.post("/join", response_model=PeerLink, status_code=201)
    def join(body: JoinRequest) -> PeerLink:
        """Join a teammate's shared folder: the URL named here is exactly where file bytes will travel."""

        try:
            return client.join(body)
        except SharedFolderError as error:
            raise _failure(error) from None

    @router.get("/links", response_model=PeerLinkList)
    def links() -> PeerLinkList:
        return client.list()

    @router.delete("/links/{link_id}", status_code=204)
    def leave(link_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]) -> Response:
        try:
            client.leave(link_id)
        except SharedFolderError as error:
            raise _failure(error) from None
        return Response(status_code=204)

    @router.post("/links/{link_id}/pull", response_model=SyncReport)
    def pull(link_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]) -> SyncReport:
        try:
            return client.pull(link_id)
        except SharedFolderError as error:
            raise _failure(error) from None

    @router.post("/links/{link_id}/push", response_model=SyncReport)
    def push(link_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")], body: PushBody | None = None) -> SyncReport:
        try:
            return client.push(link_id, peer_name=(body.peer_name if body else "peer"))
        except SharedFolderError as error:
            raise _failure(error) from None

    return router


def create_p2p_router(service: SharedFolderService) -> APIRouter:
    """The peer-facing file surface; authenticated only by the folder's share token."""

    router = APIRouter(prefix="/p2p/v1", tags=["p2p"])

    def _token(share_token: Annotated[str | None, Header(alias=SHARE_TOKEN_HEADER)] = None) -> str:
        return share_token or ""

    @router.get("/{share_id}/manifest", response_model=FolderManifest)
    def manifest(
        share_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
        token: str = Depends(_token),
    ) -> FolderManifest:
        try:
            return service.manifest(share_id, token)
        except SharedFolderError as error:
            raise _failure(error) from None

    @router.get("/{share_id}/files/{relative:path}", response_model=FileContent)
    def read_file(
        share_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
        relative: str,
        token: str = Depends(_token),
    ) -> FileContent:
        try:
            return service.read_file(share_id, token, relative)
        except SharedFolderError as error:
            raise _failure(error) from None

    @router.put("/{share_id}/files/{relative:path}", response_model=WriteFileResult)
    def write_file(
        share_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
        relative: str,
        body: WriteFileRequest,
        token: str = Depends(_token),
    ) -> WriteFileResult:
        try:
            return service.write_file(share_id, token, relative, body)
        except SharedFolderError as error:
            raise _failure(error) from None

    return router


__all__ = ("SHARE_TOKEN_HEADER", "create_p2p_router", "create_shared_folder_router")
