"""Local Agent routes: live turns plus a separate durable navigation catalog."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from ...application.agent_artifacts import (
    MAX_AGENT_ARTIFACT_LIST,
    MAX_AGENT_ARTIFACT_PAGE_SIZE,
    AgentArtifact,
    AgentArtifactCapturePreview,
    AgentArtifactContent,
    AgentArtifactDetail,
    AgentArtifactError,
    AgentArtifactExport,
    AgentArtifactList,
    AgentArtifactListView,
    AgentArtifactPage,
    AgentDocumentPreview,
    CaptureAgentArtifact,
    ExportAgentArtifact,
    PreviewAgentArtifactCapture,
    RemoveAgentArtifact,
    UpdateAgentArtifact,
)
from ...application.agent_catalog import (
    AGENT_PROJECT_ID_PATTERN,
    MAX_AGENT_CATALOG_PAGE_SIZE,
    AgentCatalogError,
    AgentCatalogService,
    AgentCatalogSessionPage,
    AgentCatalogSessionList,
    AgentCatalogSessionRecord,
    AgentMessageSearchPage,
    AgentMessageSearchRequest,
    AgentHistoryExport,
    AgentSessionForkReceipt,
    AgentProjectList,
    AgentProjectPage,
    AgentProjectRecord,
    CreateAgentProject,
    ForkAgentSession,
    ResumeAgentSession,
    UpdateAgentCatalogSession,
    UpdateAgentProject,
)
from ...application.agent_attachment_contracts import (
    AgentAttachment,
    AgentAttachmentDocumentPreview,
    AgentAttachmentList,
    MAX_AGENT_AUDIO_BYTES,
    MAX_AGENT_DOCUMENT_BYTES,
    StageAgentAttachment,
    StageInlineAgentAttachment,
)
from ...application.agent_orchestration import (
    AgentOrchestrationManifest,
    agent_orchestration_manifest,
)
from ...application.agent_session_context import AgentSessionContextStatus
from ...application.local_agent import (
    AgentEvents,
    AgentLifecycleProposal,
    AgentLifecycleProposalReceipt,
    AgentSessionView,
    AgentSettings,
    AgentWriteProposal,
    AgentWriteProposalReceipt,
    AgentWriteTransactionProposal,
    AgentWriteTransactionProposalReceipt,
    ApprovalDecision,
    LocalAgentError,
    LocalAgentService,
    RevalidateAgentAuthority,
    SendMessage,
    SwitchAgentSessionModel,
)
from ...application.local_agent_changes import (
    AgentChangeDiff,
    AgentChangeRestoreApplyCommand,
    AgentChangeRestoreApplyResult,
    AgentChangeRestorePreview,
    AgentChangeRestorePreviewCommand,
    AgentChangeSet,
)
from ...application.local_agent_discovery import WorkspaceDiscovery
from ...application.local_agent_editor import (
    WorkspaceApplyCommand,
    WorkspaceApplyResult,
    WorkspaceEditPreview,
    WorkspaceFile,
    WorkspacePreviewCommand,
    WorkspaceSearchResult,
    WorkspaceTree,
)
from ...application.local_agent_limits import MAX_SEARCH_QUERY_CHARS
from ...application.local_agent_file_lifecycle import (
    WorkspaceCreateApplyCommand,
    WorkspaceCreateApplyResult,
    WorkspaceCreatePreview,
    WorkspaceCreatePreviewCommand,
    WorkspaceDirectoryCreateApplyCommand,
    WorkspaceDirectoryCreateApplyResult,
    WorkspaceDirectoryCreatePreview,
    WorkspaceDirectoryCreatePreviewCommand,
    WorkspaceDirectoryMoveApplyCommand,
    WorkspaceDirectoryMoveApplyResult,
    WorkspaceDirectoryMovePreview,
    WorkspaceDirectoryMovePreviewCommand,
    WorkspaceFileTrashApplyCommand,
    WorkspaceFileTrashApplyResult,
    WorkspaceFileTrashPreview,
    WorkspaceFileTrashPreviewCommand,
    WorkspaceMoveApplyCommand,
    WorkspaceMoveApplyResult,
    WorkspaceMovePreview,
    WorkspaceMovePreviewCommand,
)
from ...application.local_agent_transactions import (
    WorkspaceTransactionApplyCommand,
    WorkspaceTransactionApplyResult,
    WorkspaceTransactionPreview,
    WorkspaceTransactionPreviewCommand,
)


_STATUS = {
    "workspace_not_a_folder": 422,
    "workspace_not_allowed": 403,
    "workspace_link_or_reparse_refused": 403,
    "workspace_is_a_drive_root": 422,
    "workspace_path_not_found": 404,
    "workspace_directory_unavailable": 422,
    "workspace_not_a_directory": 422,
    "workspace_file_unavailable": 422,
    "workspace_file_changed": 409,
    "workspace_root_changed": 409,
    "workspace_inspection_timeout": 503,
    "workspace_query_empty": 422,
    "workspace_query_too_large": 413,
    "workspace_regex_invalid": 422,
    "workspace_glob_invalid": 422,
    "workspace_binary_refused": 415,
    "workspace_line_endings_unsupported": 422,
    "workspace_revision_changed": 409,
    "workspace_line_ending_changed": 409,
    "workspace_existing_file_required": 422,
    "workspace_no_change": 409,
    "workspace_change_not_reviewable": 422,
    "workspace_file_too_large": 413,
    "workspace_text_invalid": 422,
    "workspace_parent_unavailable": 422,
    "change_too_large_to_review": 413,
    "workspace_preview_not_found": 409,
    "workspace_preview_expired": 409,
    "workspace_preview_mismatch": 409,
    "workspace_apply_failed": 409,
    "workspace_lifecycle_target_exists": 409,
    "workspace_lifecycle_same_path": 422,
    "workspace_lifecycle_preview_not_found": 409,
    "workspace_lifecycle_preview_expired": 409,
    "workspace_lifecycle_preview_mismatch": 409,
    "workspace_lifecycle_unverified": 409,
    "workspace_directory_create_failed": 503,
    "workspace_directory_create_unverified": 409,
    "workspace_directory_move_into_self": 422,
    "workspace_directory_move_unsupported": 422,
    "workspace_directory_move_failed": 503,
    "workspace_directory_move_unverified": 409,
    "workspace_file_trash_unsupported": 422,
    "workspace_file_trash_failed": 503,
    "workspace_file_trash_unverified": 409,
    "workspace_move_unsupported": 422,
    "workspace_move_failed": 503,
    "workspace_move_unverified": 409,
    "workspace_write_failed": 503,
    "workspace_cleanup_failed": 503,
    "workspace_verification_failed": 409,
    "agent_artifact_relocation_unverified": 409,
    "agent_artifact_relocation_conflict": 409,
    "agent_artifact_relocation_target_conflict": 409,
    "workspace_transaction_invalid": 422,
    "workspace_transaction_changed": 409,
    "workspace_transaction_no_change": 409,
    "workspace_transaction_too_large": 413,
    "workspace_transaction_diff_too_large": 413,
    "workspace_transaction_not_found": 409,
    "workspace_transaction_expired": 409,
    "workspace_transaction_mismatch": 409,
    "path_outside_workspace": 403,
    "path_invalid": 422,
    "too_many_sessions": 409,
    "session_not_found": 404,
    "turn_in_progress": 409,
    "turn_start_failed": 503,
    "session_closing": 409,
    "session_stop_timeout": 409,
    "command_cleanup_unconfirmed": 409,
    "runtime_shutdown_in_progress": 409,
    "no_active_model": 409,
    "model_not_ready": 409,
    "web_fetch_unavailable": 409,
    "approval_not_pending": 409,
    "approval_already_settled": 409,
    "agent_write_proposal_request_conflict": 409,
    "agent_write_proposal_not_allowed": 403,
    "agent_write_proposal_limit_reached": 409,
    "agent_write_proposal_start_failed": 503,
    "change_path_not_found": 404,
    "change_already_reverted": 409,
    "change_restore_baseline_unavailable": 409,
    "change_restore_unavailable": 422,
    "change_restore_mismatch": 409,
    "change_restore_verification_failed": 409,
    "agent_catalog_unavailable": 503,
    "agent_catalog_path_invalid": 503,
    "agent_catalog_path_unsafe": 503,
    "agent_catalog_storage_unavailable": 503,
    "agent_catalog_schema_newer": 503,
    "agent_catalog_migration_history_incomplete": 503,
    "agent_catalog_migration_checksum_mismatch": 503,
    "agent_catalog_schema_version_mismatch": 503,
    "agent_catalog_id_invalid": 500,
    "agent_project_not_found": 404,
    "agent_project_archived": 409,
    "agent_project_conflict": 409,
    "agent_project_revision_conflict": 409,
    "agent_project_not_empty": 409,
    "agent_default_project_protected": 409,
    "too_many_agent_projects": 409,
    "agent_catalog_session_not_found": 404,
    "agent_catalog_session_conflict": 409,
    "agent_catalog_session_revision_conflict": 409,
    "agent_catalog_session_live": 409,
    "too_many_agent_catalog_sessions": 409,
    "agent_catalog_page_invalid": 422,
    "agent_catalog_page_snapshot_required": 422,
    "agent_catalog_page_snapshot_conflict": 409,
    "agent_catalog_page_out_of_range": 409,
    "agent_message_search_snapshot_conflict": 409,
    "agent_message_search_page_out_of_range": 409,
    "agent_message_search_timed_out": 503,
    "agent_message_search_unavailable": 503,
    "agent_message_search_corrupt": 503,
    "agent_catalog_session_archived": 409,
    "agent_history_not_retained": 409,
    "agent_history_revision_conflict": 409,
    "agent_history_sequence_conflict": 409,
    "agent_history_limit_reached": 409,
    "agent_history_event_too_large": 413,
    "agent_history_corrupt": 503,
    "agent_history_storage_unavailable": 503,
    "agent_history_write_failed": 503,
    "agent_close_identity_incomplete": 422,
    "agent_session_fork_point_invalid": 422,
    "agent_session_fork_request_conflict": 409,
    "agent_session_fork_conflict": 409,
    "agent_artifact_unavailable": 503,
    "agent_artifact_storage_unavailable": 503,
    "agent_artifact_id_invalid": 500,
    "agent_artifact_not_found": 404,
    "agent_artifact_version_not_found": 404,
    "agent_artifact_retention_required": 409,
    "agent_artifact_revision_changed": 409,
    "agent_artifact_stale": 409,
    "agent_artifact_missing": 404,
    "agent_artifact_malformed": 422,
    "agent_artifact_preview_unsupported": 415,
    "agent_artifact_too_large": 413,
    "agent_artifact_limit_reached": 409,
    "agent_artifact_version_limit_reached": 409,
    "agent_artifact_conflict": 409,
    "agent_artifact_revision_conflict": 409,
    "agent_artifact_state_conflict": 409,
    "agent_artifact_no_change": 409,
    "agent_artifact_archive_required": 409,
    "agent_artifact_removed": 410,
    "agent_artifact_page_invalid": 422,
    "agent_artifact_page_snapshot_required": 422,
    "agent_artifact_page_snapshot_conflict": 409,
    "agent_artifact_page_out_of_range": 409,
    "agent_attachment_unavailable": 503,
    "agent_attachment_capabilities_unavailable": 503,
    "agent_attachment_id_invalid": 500,
    "agent_attachment_not_found": 404,
    "agent_attachment_empty": 422,
    "agent_attachment_media_unsupported": 415,
    "agent_attachment_media_mismatch": 422,
    "agent_attachment_dimensions_unsupported": 422,
    "agent_attachment_audio_unsupported": 422,
    "agent_attachment_duration_unsupported": 422,
    "agent_attachment_image_capability_unavailable": 409,
    "agent_attachment_audio_capability_unavailable": 409,
    "agent_attachment_document_capability_unavailable": 409,
    "agent_attachment_document_encoding_unsupported": 422,
    "agent_attachment_document_structure_invalid": 422,
    "agent_attachment_document_empty": 422,
    "agent_attachment_document_message_too_large": 413,
    "agent_attachment_content_preview_unsupported": 415,
    "agent_attachment_document_preview_unsupported": 415,
    "agent_attachment_too_large": 413,
    "agent_attachment_message_too_large": 413,
    "agent_attachment_session_too_large": 413,
    "agent_attachment_stage_limit": 409,
    "agent_attachment_message_limit": 409,
    "agent_attachment_duplicate": 422,
    "agent_attachment_model_changed": 409,
    "agent_attachment_retention_changed": 409,
    "agent_attachment_already_sent": 409,
    "agent_attachment_state_changed": 409,
    "agent_attachment_corrupt": 503,
    "agent_attachment_conflict": 409,
    "agent_attachment_storage_unavailable": 503,
}
_SESSION_ID = r"^[0-9a-f]{32}$"
_PROJECT_ID = AGENT_PROJECT_ID_PATTERN
_ARTIFACT_ID = r"^[0-9a-f]{32}$"
_ATTACHMENT_ID = r"^[0-9a-f]{32}$"
_SINGLE_BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_AGENT_ATTACHMENT_MEDIA_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "audio/wav",
        "text/plain",
        "text/markdown",
        "application/json",
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.text",
    }
)
_MAX_AGENT_ATTACHMENT_UPLOAD_BYTES = max(
    MAX_AGENT_AUDIO_BYTES,
    MAX_AGENT_DOCUMENT_BYTES,
)


def _failure(error: LocalAgentError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code})


def _catalog_failure(error: AgentCatalogError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code})


def _artifact_failure(error: AgentArtifactError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code})


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


def _artifact_response(
    request: Request,
    content: AgentArtifactContent,
    *,
    download: bool,
) -> Response:
    payload = content.payload
    size = len(payload)
    disposition = "attachment" if download else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store, private",
        "Pragma": "no-cache",
        "Content-Disposition": f'{disposition}; filename="{content.filename}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Content-Type": content.content_type,
    }
    status_code = 200
    requested = request.headers.get("range")
    if requested is not None:
        matched = (
            None
            if len(requested) > 80
            else _SINGLE_BYTE_RANGE.fullmatch(requested.strip())
        )
        if matched is None or "," in requested or size == 0:
            headers["Content-Range"] = f"bytes */{size}"
            raise HTTPException(status_code=416, detail={"code": "agent_artifact_range_invalid"}, headers=headers)
        start_text, end_text = matched.groups()
        if not start_text and not end_text:
            headers["Content-Range"] = f"bytes */{size}"
            raise HTTPException(status_code=416, detail={"code": "agent_artifact_range_invalid"}, headers=headers)
        if start_text:
            start = int(start_text)
            end = size - 1 if not end_text else min(int(end_text), size - 1)
            invalid = start >= size or end < start
        else:
            suffix = int(end_text)
            invalid = suffix <= 0
            start = max(0, size - suffix)
            end = size - 1
        if invalid:
            headers["Content-Range"] = f"bytes */{size}"
            raise HTTPException(status_code=416, detail={"code": "agent_artifact_range_invalid"}, headers=headers)
        payload = payload[start:end + 1]
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(len(payload))
    return Response(content=payload, status_code=status_code, headers=headers)


def _catalog(service: LocalAgentService) -> AgentCatalogService:
    catalog = service.catalog
    if catalog is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "agent_catalog_unavailable"},
        )
    return catalog


def _stream_event_pages(
    service: LocalAgentService,
    session_id: str,
    after: int,
    limit: int,
) -> Iterator[bytes]:
    """Relay event pages until the turn settles or enters cleanup quarantine.

    Stream closure is not itself proof of success.  A cleanup quarantine is a
    terminal controller outcome, so its final page is emitted and the relay
    closes.  Ordinary success follows the stricter orchestration-v6 condition:
    closing and stopping must both be false in addition to the turn being idle,
    approval-free, and fully drained.
    """

    cursor = after
    while True:
        try:
            page = service.wait_events(session_id, cursor, limit)
        except LocalAgentError:
            return
        outcome: Literal["settled", "cleanup_unconfirmed"] | None = None
        if page.cleanup_unconfirmed:
            outcome = "cleanup_unconfirmed"
        elif (
            not page.running
            and not page.closing
            and not page.stopping
            and page.pending_approval_id is None
            and cursor >= page.last_seq
        ):
            outcome = "settled"
        if page.events:
            cursor = page.events[-1].seq
            yield f"data: {page.model_dump_json()}\n\n".encode("utf-8")
            if (
                outcome is None
                and not page.running
                and not page.closing
                and not page.stopping
                and page.pending_approval_id is None
                and cursor >= page.last_seq
            ):
                outcome = "settled"
        elif outcome is not None:
            # A newly attached controller must receive the exact terminal state,
            # even when its cursor was already at ``last_seq``.  A bare
            # keepalive followed by EOF would make success and quarantine
            # indistinguishable.
            yield f"data: {page.model_dump_json()}\n\n".encode("utf-8")
        else:
            yield b": keepalive\n\n"
        if outcome is not None:
            return


def create_local_agent_router(
    require_local_auth: Callable[..., None],
    require_browser_confirmation: Callable[..., None],
    service: LocalAgentService,
) -> APIRouter:
    router = APIRouter(prefix="/v1/agent", tags=["local-agent"], dependencies=[Depends(require_local_auth)])

    @router.get("/orchestration", response_model=AgentOrchestrationManifest)
    def orchestration_manifest(response: Response) -> AgentOrchestrationManifest:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        return agent_orchestration_manifest()

    @router.get("/projects", response_model=AgentProjectList)
    def list_projects(
        search: Annotated[str | None, Query(max_length=120)] = None,
        include_archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
    ) -> AgentProjectList:
        try:
            return _catalog(service).list_projects(
                search=search,
                include_archived=include_archived,
                limit=limit,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None

    @router.get("/projects/page", response_model=AgentProjectPage)
    def page_projects(
        response: Response,
        search: Annotated[str | None, Query(max_length=120)] = None,
        include_archived: bool = False,
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_AGENT_CATALOG_PAGE_SIZE),
        ] = MAX_AGENT_CATALOG_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, le=200)] = 0,
        snapshot: Annotated[
            str | None,
            Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
        ] = None,
    ) -> AgentProjectPage:
        _private(response)
        try:
            return _catalog(service).page_projects(
                search=search,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
                snapshot=snapshot,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None

    @router.post("/projects", response_model=AgentProjectRecord, status_code=201)
    def create_project(payload: CreateAgentProject) -> AgentProjectRecord:
        try:
            return _catalog(service).create_project(payload)
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None

    @router.get("/projects/{project_id}", response_model=AgentProjectRecord)
    def get_project(
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
    ) -> AgentProjectRecord:
        try:
            return _catalog(service).get_project(project_id)
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None

    @router.patch("/projects/{project_id}", response_model=AgentProjectRecord)
    def update_project(
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        payload: UpdateAgentProject,
    ) -> AgentProjectRecord:
        try:
            return _catalog(service).update_project(project_id, payload)
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None

    @router.delete("/projects/{project_id}", status_code=204)
    def delete_project(
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        expected_revision: Annotated[int, Query(ge=1)],
    ) -> Response:
        try:
            _catalog(service).delete_project(
                project_id,
                expected_revision=expected_revision,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return Response(status_code=204)

    @router.get(
        "/projects/{project_id}/sessions",
        response_model=AgentCatalogSessionList,
    )
    def list_project_sessions(
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        search: Annotated[str | None, Query(max_length=120)] = None,
        include_archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
    ) -> AgentCatalogSessionList:
        try:
            result = _catalog(service).list_sessions(
                project_id=project_id,
                search=search,
                include_archived=include_archived,
                limit=limit,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return result.model_copy(
            update={
                "sessions": tuple(
                    service.catalog_session_availability(session)
                    for session in result.sessions
                )
            }
        )

    @router.get(
        "/projects/{project_id}/sessions/page",
        response_model=AgentCatalogSessionPage,
    )
    def page_project_sessions(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        search: Annotated[str | None, Query(max_length=120)] = None,
        include_archived: bool = False,
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_AGENT_CATALOG_PAGE_SIZE),
        ] = MAX_AGENT_CATALOG_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, le=2_000)] = 0,
        snapshot: Annotated[
            str | None,
            Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
        ] = None,
    ) -> AgentCatalogSessionPage:
        _private(response)
        try:
            result = _catalog(service).page_sessions(
                project_id=project_id,
                search=search,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
                snapshot=snapshot,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return result.model_copy(
            update={
                "sessions": tuple(
                    service.catalog_session_availability(session)
                    for session in result.sessions
                )
            }
        )

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/events",
        response_model=AgentEvents,
    )
    def persisted_session_events(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 500,
    ) -> AgentEvents:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        try:
            return service.catalog_events(
                project_id=project_id,
                session_id=session_id,
                after=after,
                limit=limit,
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/forks",
        response_model=AgentSessionForkReceipt,
    )
    def fork_retained_session(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: ForkAgentSession,
    ) -> AgentSessionForkReceipt:
        _private(response)
        try:
            receipt = _catalog(service).fork_session(
                source_project_id=project_id,
                source_session_id=session_id,
                command=payload,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return receipt.model_copy(
            update={
                "session": service.catalog_session_availability(receipt.session),
            }
        )

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/artifacts",
        response_model=AgentArtifactList,
    )
    def list_session_artifacts(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        view: Annotated[AgentArtifactListView, Query()] = "active",
        limit: Annotated[int, Query(ge=1, le=MAX_AGENT_ARTIFACT_LIST)] = MAX_AGENT_ARTIFACT_LIST,
    ) -> AgentArtifactList:
        _private(response)
        try:
            return service.list_artifacts(
                project_id=project_id,
                session_id=session_id,
                view=view,
                limit=limit,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/artifacts/page",
        response_model=AgentArtifactPage,
    )
    def page_session_artifacts(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        view: Annotated[AgentArtifactListView, Query()] = "active",
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_AGENT_ARTIFACT_PAGE_SIZE),
        ] = MAX_AGENT_ARTIFACT_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, le=500)] = 0,
        snapshot: Annotated[
            str | None,
            Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
        ] = None,
    ) -> AgentArtifactPage:
        _private(response)
        try:
            return service.page_artifacts(
                project_id=project_id,
                session_id=session_id,
                view=view,
                limit=limit,
                offset=offset,
                snapshot=snapshot,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/artifacts/capture-preview",
        response_model=AgentArtifactCapturePreview,
    )
    def preview_session_artifact_capture(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: PreviewAgentArtifactCapture,
    ) -> AgentArtifactCapturePreview:
        _private(response)
        try:
            return service.preview_artifact_capture(
                project_id=project_id,
                session_id=session_id,
                command=payload,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/artifacts",
        response_model=AgentArtifactDetail,
        status_code=201,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def capture_session_artifact(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: CaptureAgentArtifact,
    ) -> AgentArtifactDetail:
        _private(response)
        try:
            return service.capture_artifact(
                project_id=project_id,
                session_id=session_id,
                command=payload,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}",
        response_model=AgentArtifactDetail,
    )
    def get_session_artifact(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        artifact_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
    ) -> AgentArtifactDetail:
        _private(response)
        try:
            return service.get_artifact(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/export",
        response_model=AgentArtifactExport,
    )
    def export_session_artifact_lineage(
        response: Response,
        payload: ExportAgentArtifact,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        artifact_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
    ) -> AgentArtifactExport:
        _private(response)
        try:
            return service.export_artifact_lineage(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
                command=payload,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.patch(
        "/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}",
        response_model=AgentArtifact,
    )
    def update_session_artifact(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        artifact_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
        payload: UpdateAgentArtifact,
    ) -> AgentArtifact:
        _private(response)
        try:
            return service.update_artifact(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
                command=payload,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/remove",
        response_model=AgentArtifact,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def remove_session_artifact(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        artifact_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
        payload: RemoveAgentArtifact,
    ) -> AgentArtifact:
        _private(response)
        try:
            return service.remove_artifact(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
                command=payload,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/versions/{version_id}/preview",
        response_model=AgentDocumentPreview,
    )
    def get_session_artifact_document_preview(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        artifact_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
        version_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
    ) -> AgentDocumentPreview:
        _private(response)
        try:
            return service.artifact_document_preview(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
                version_id=version_id,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/versions/{version_id}/content",
        response_class=Response,
        responses={
            200: {"content": {"application/octet-stream": {}}},
            206: {"content": {"application/octet-stream": {}}},
        },
    )
    def get_session_artifact_content(
        request: Request,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        artifact_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
        version_id: Annotated[str, Path(pattern=_ARTIFACT_ID)],
        download: bool = False,
    ) -> Response:
        try:
            content = service.artifact_content(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
                version_id=version_id,
                download=download,
            )
        except AgentArtifactError as error:
            raise _artifact_failure(error) from None
        except LocalAgentError as error:
            raise _failure(error) from None
        return _artifact_response(request, content, download=download)

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/resume",
        response_model=AgentSessionView,
    )
    def resume_session(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: ResumeAgentSession,
    ) -> AgentSessionView:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        try:
            return service.resume(
                project_id=project_id,
                session_id=session_id,
                command=payload,
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/projects/{project_id}/sessions/{session_id}/export",
        response_model=AgentHistoryExport,
    )
    def export_session_history(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        expected_catalog_revision: Annotated[int | None, Query(ge=1)] = None,
        expected_history_revision: Annotated[int | None, Query(ge=0)] = None,
    ) -> AgentHistoryExport:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Content-Disposition"] = (
            f'attachment; filename="agent-chat-{session_id[:8]}.json"'
        )
        try:
            return service.export_history(
                project_id=project_id,
                session_id=session_id,
                expected_catalog_revision=expected_catalog_revision,
                expected_history_revision=expected_history_revision,
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get("/catalog/sessions", response_model=AgentCatalogSessionList)
    def list_catalog_sessions(
        search: Annotated[str | None, Query(max_length=120)] = None,
        include_archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
    ) -> AgentCatalogSessionList:
        try:
            result = _catalog(service).list_sessions(
                search=search,
                include_archived=include_archived,
                limit=limit,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return result.model_copy(
            update={
                "sessions": tuple(
                    service.catalog_session_availability(session)
                    for session in result.sessions
                )
            }
        )

    @router.post(
        "/catalog/sessions/message-search",
        response_model=AgentMessageSearchPage,
    )
    def search_catalog_messages(
        payload: AgentMessageSearchRequest,
        response: Response,
    ) -> AgentMessageSearchPage:
        # The query is body-only and this response is private. Do not add this
        # operation to the orchestration/MCP surface or an export contract.
        _private(response)
        try:
            return _catalog(service).search_messages(request=payload)
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None

    @router.get("/catalog/sessions/page", response_model=AgentCatalogSessionPage)
    def page_catalog_sessions(
        response: Response,
        search: Annotated[str | None, Query(max_length=120)] = None,
        include_archived: bool = False,
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_AGENT_CATALOG_PAGE_SIZE),
        ] = MAX_AGENT_CATALOG_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, le=2_000)] = 0,
        snapshot: Annotated[
            str | None,
            Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
        ] = None,
    ) -> AgentCatalogSessionPage:
        _private(response)
        try:
            result = _catalog(service).page_sessions(
                search=search,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
                snapshot=snapshot,
            )
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return result.model_copy(
            update={
                "sessions": tuple(
                    service.catalog_session_availability(session)
                    for session in result.sessions
                )
            }
        )

    @router.get(
        "/catalog/sessions/{session_id}",
        response_model=AgentCatalogSessionRecord,
    )
    def get_catalog_session(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
    ) -> AgentCatalogSessionRecord:
        try:
            result = _catalog(service).get_session(session_id)
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        return service.catalog_session_availability(result)

    @router.patch(
        "/catalog/sessions/{session_id}",
        response_model=AgentCatalogSessionRecord,
    )
    def update_catalog_session(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: UpdateAgentCatalogSession,
    ) -> AgentCatalogSessionRecord:
        try:
            return service.update_catalog_session(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.delete("/catalog/sessions/{session_id}", status_code=204)
    def delete_catalog_session(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        expected_catalog_revision: Annotated[int, Query(ge=1)],
        expected_history_revision: Annotated[int, Query(ge=0)],
    ) -> Response:
        try:
            service.delete_catalog_session(
                session_id,
                expected_catalog_revision=expected_catalog_revision,
                expected_history_revision=expected_history_revision,
            )
        except LocalAgentError as error:
            raise _failure(error) from None
        return Response(status_code=204)

    @router.get("/sessions", response_model=tuple[AgentSessionView, ...])
    def list_sessions() -> tuple[AgentSessionView, ...]:
        return service.list()

    @router.post("/sessions", response_model=AgentSessionView, status_code=201)
    def create_session(payload: AgentSettings) -> AgentSessionView:
        try:
            return service.create(payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get("/sessions/{session_id}", response_model=AgentSessionView)
    def get_session(session_id: Annotated[str, Path(pattern=_SESSION_ID)]) -> AgentSessionView:
        try:
            return service.get(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/context",
        response_model=AgentSessionContextStatus,
    )
    def get_session_context(
        response: Response,
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
    ) -> AgentSessionContextStatus:
        _private(response)
        try:
            return service.session_context(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.delete("/sessions/{session_id}", status_code=204)
    def delete_session(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        expected_project_id: Annotated[
            str | None,
            Query(pattern=_PROJECT_ID),
        ] = None,
        expected_catalog_revision: Annotated[
            int | None,
            Query(ge=1),
        ] = None,
        expected_history_revision: Annotated[
            int | None,
            Query(ge=0),
        ] = None,
    ) -> Response:
        try:
            service.delete(
                session_id,
                expected_project_id=expected_project_id,
                expected_catalog_revision=expected_catalog_revision,
                expected_history_revision=expected_history_revision,
            )
        except LocalAgentError as error:
            raise _failure(error) from None
        return Response(status_code=204)

    @router.post(
        "/sessions/{session_id}/model",
        response_model=AgentSessionView,
    )
    def switch_session_model(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: SwitchAgentSessionModel,
    ) -> AgentSessionView:
        try:
            return service.switch_model(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/authority",
        response_model=AgentSessionView,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def revalidate_session_authority(
        response: Response,
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: RevalidateAgentAuthority,
    ) -> AgentSessionView:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        try:
            return service.revalidate_authority(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/attachments",
        response_model=AgentAttachmentList,
    )
    def list_attachments(
        response: Response,
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
    ) -> AgentAttachmentList:
        _private(response)
        try:
            return service.list_staged_attachments(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/attachments",
        response_model=AgentAttachment,
        status_code=201,
    )
    async def stage_attachment(
        request: Request,
        response: Response,
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        name: Annotated[str, Query(min_length=1, max_length=120)],
        source: Annotated[Literal["file", "microphone"], Query()] = "file",
    ) -> AgentAttachment:
        _private(response)
        media_type = request.headers.get("content-type", "").strip().casefold()
        if media_type not in _AGENT_ATTACHMENT_MEDIA_TYPES:
            raise HTTPException(
                status_code=415,
                detail={"code": "agent_attachment_media_unsupported"},
            )
        content_length = request.headers.get("content-length")
        if content_length is not None and (
            not content_length.isascii()
            or not content_length.isdigit()
            or int(content_length) > _MAX_AGENT_ATTACHMENT_UPLOAD_BYTES
        ):
            raise HTTPException(
                status_code=413,
                detail={"code": "agent_attachment_too_large"},
            )
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > _MAX_AGENT_ATTACHMENT_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "agent_attachment_too_large"},
                )
            payload.extend(chunk)
        try:
            return service.stage_attachment(
                session_id,
                command=StageAgentAttachment(display_name=name, source=source),
                media_type=media_type,
                payload=bytes(payload),
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/projects/{project_id}/sessions/{session_id}/attachments/stage-inline",
        response_model=AgentAttachment,
        status_code=201,
    )
    def stage_inline_attachment(
        response: Response,
        project_id: Annotated[str, Path(pattern=_PROJECT_ID)],
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: StageInlineAgentAttachment,
    ) -> AgentAttachment:
        """Admit exact caller-supplied media without accepting a local path."""

        _private(response)
        try:
            record = _catalog(service).get_session(session_id)
        except AgentCatalogError as error:
            raise _catalog_failure(error) from None
        if record.project_id != project_id:
            raise HTTPException(
                status_code=404,
                detail={"code": "agent_catalog_session_not_found"},
            )
        try:
            return service.stage_attachment(
                session_id,
                command=StageAgentAttachment(
                    display_name=payload.display_name,
                    source="external_agent",
                ),
                media_type=payload.media_type,
                payload=payload.payload(),
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.delete(
        "/sessions/{session_id}/attachments/{attachment_id}",
        status_code=204,
    )
    def delete_attachment(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        attachment_id: Annotated[str, Path(pattern=_ATTACHMENT_ID)],
    ) -> Response:
        try:
            service.delete_staged_attachment(session_id, attachment_id)
        except LocalAgentError as error:
            raise _failure(error) from None
        response = Response(status_code=204)
        _private(response)
        return response

    @router.get(
        "/sessions/{session_id}/attachments/{attachment_id}/document-preview",
        response_model=AgentAttachmentDocumentPreview,
    )
    def attachment_document_preview(
        response: Response,
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        attachment_id: Annotated[str, Path(pattern=_ATTACHMENT_ID)],
    ) -> AgentAttachmentDocumentPreview:
        _private(response)
        try:
            return service.attachment_document_preview(session_id, attachment_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/attachments/{attachment_id}/content",
        response_class=Response,
    )
    def attachment_content(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        attachment_id: Annotated[str, Path(pattern=_ATTACHMENT_ID)],
    ) -> Response:
        try:
            content = service.attachment_content(session_id, attachment_id)
        except LocalAgentError as error:
            raise _failure(error) from None
        response = Response(
            content=content.payload,
            media_type=content.attachment.media_type,
            headers={
                "Content-Disposition": f'inline; filename="{content.filename}"',
                "Content-Length": str(len(content.payload)),
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )
        _private(response)
        return response

    @router.post("/sessions/{session_id}/messages", response_model=AgentSessionView, status_code=202)
    def send_message(session_id: Annotated[str, Path(pattern=_SESSION_ID)], payload: SendMessage) -> AgentSessionView:
        try:
            return service.send(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get("/sessions/{session_id}/changes", response_model=AgentChangeSet)
    def session_changes(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
    ) -> AgentChangeSet:
        try:
            return service.change_set(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/write-proposals",
        response_model=AgentWriteProposalReceipt,
        status_code=202,
    )
    def propose_write(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: AgentWriteProposal,
    ) -> AgentWriteProposalReceipt:
        try:
            return service.propose_write(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/write-transaction-proposals",
        response_model=AgentWriteTransactionProposalReceipt,
        status_code=202,
    )
    def propose_write_transaction(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: AgentWriteTransactionProposal,
    ) -> AgentWriteTransactionProposalReceipt:
        try:
            return service.propose_write_transaction(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/lifecycle-proposals",
        response_model=AgentLifecycleProposalReceipt,
        status_code=202,
    )
    def propose_lifecycle(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: AgentLifecycleProposal,
    ) -> AgentLifecycleProposalReceipt:
        try:
            return service.propose_lifecycle(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get("/sessions/{session_id}/changes/diff", response_model=AgentChangeDiff)
    def session_change_diff(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        path: Annotated[str, Query(min_length=1, max_length=1024)],
    ) -> AgentChangeDiff:
        try:
            return service.change_diff(session_id, path)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/changes/restores",
        response_model=AgentChangeRestorePreview,
        status_code=201,
    )
    def preview_change_restore(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: AgentChangeRestorePreviewCommand,
    ) -> AgentChangeRestorePreview:
        try:
            return service.preview_change_restore(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/changes/restores/{preview_id}/apply",
        response_model=AgentChangeRestoreApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_change_restore(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: AgentChangeRestoreApplyCommand,
    ) -> AgentChangeRestoreApplyResult:
        try:
            return service.apply_change_restore(session_id, preview_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get("/sessions/{session_id}/events", response_model=AgentEvents)
    def events(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 500,
    ) -> AgentEvents:
        try:
            return service.events(session_id, after, limit)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/workspace/discovery",
        response_model=WorkspaceDiscovery,
    )
    def workspace_discovery(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
    ) -> WorkspaceDiscovery:
        try:
            return service.workspace_discovery(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/workspace/tree",
        response_model=WorkspaceTree,
    )
    def workspace_tree(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        path: Annotated[str, Query(min_length=1, max_length=1024)] = ".",
    ) -> WorkspaceTree:
        try:
            return service.workspace_tree(session_id, path)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/workspace/search",
        response_model=WorkspaceSearchResult,
    )
    def workspace_search(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        query: Annotated[
            str,
            Query(min_length=1, max_length=MAX_SEARCH_QUERY_CHARS),
        ],
        glob_pattern: Annotated[
            str,
            Query(alias="glob", min_length=1, max_length=MAX_SEARCH_QUERY_CHARS),
        ] = "**/*",
        regex: Annotated[bool, Query()] = False,
    ) -> WorkspaceSearchResult:
        try:
            return service.workspace_search(
                session_id,
                query,
                glob_pattern,
                regex,
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/workspace/file",
        response_model=WorkspaceFile,
    )
    def workspace_file(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        path: Annotated[str, Query(min_length=1, max_length=1024)],
    ) -> WorkspaceFile:
        try:
            return service.workspace_file(session_id, path)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/creates",
        response_model=WorkspaceCreatePreview,
        status_code=201,
    )
    def preview_workspace_create(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceCreatePreviewCommand,
    ) -> WorkspaceCreatePreview:
        try:
            return service.preview_workspace_create(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/creates/{preview_id}/apply",
        response_model=WorkspaceCreateApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_create(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceCreateApplyCommand,
    ) -> WorkspaceCreateApplyResult:
        try:
            return service.apply_workspace_create(session_id, preview_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/directories",
        response_model=WorkspaceDirectoryCreatePreview,
        status_code=201,
    )
    def preview_workspace_directory_create(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceDirectoryCreatePreviewCommand,
    ) -> WorkspaceDirectoryCreatePreview:
        try:
            return service.preview_workspace_directory_create(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/directories/{preview_id}/apply",
        response_model=WorkspaceDirectoryCreateApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_directory_create(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceDirectoryCreateApplyCommand,
    ) -> WorkspaceDirectoryCreateApplyResult:
        try:
            return service.apply_workspace_directory_create(
                session_id, preview_id, payload
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/directory-moves",
        response_model=WorkspaceDirectoryMovePreview,
        status_code=201,
    )
    def preview_workspace_directory_move(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceDirectoryMovePreviewCommand,
    ) -> WorkspaceDirectoryMovePreview:
        try:
            return service.preview_workspace_directory_move(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/directory-moves/{preview_id}/apply",
        response_model=WorkspaceDirectoryMoveApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_directory_move(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceDirectoryMoveApplyCommand,
    ) -> WorkspaceDirectoryMoveApplyResult:
        try:
            return service.apply_workspace_directory_move(
                session_id, preview_id, payload
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/file-trash",
        response_model=WorkspaceFileTrashPreview,
        status_code=201,
    )
    def preview_workspace_file_trash(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceFileTrashPreviewCommand,
    ) -> WorkspaceFileTrashPreview:
        try:
            return service.preview_workspace_file_trash(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/file-trash/{preview_id}/apply",
        response_model=WorkspaceFileTrashApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_file_trash(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceFileTrashApplyCommand,
    ) -> WorkspaceFileTrashApplyResult:
        try:
            return service.apply_workspace_file_trash(
                session_id, preview_id, payload
            )
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/moves",
        response_model=WorkspaceMovePreview,
        status_code=201,
    )
    def preview_workspace_move(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceMovePreviewCommand,
    ) -> WorkspaceMovePreview:
        try:
            return service.preview_workspace_move(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/moves/{preview_id}/apply",
        response_model=WorkspaceMoveApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_move(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceMoveApplyCommand,
    ) -> WorkspaceMoveApplyResult:
        try:
            return service.apply_workspace_move(session_id, preview_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/previews",
        response_model=WorkspaceEditPreview,
        status_code=201,
    )
    def preview_workspace_edit(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspacePreviewCommand,
    ) -> WorkspaceEditPreview:
        try:
            return service.preview_workspace_edit(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/previews/{preview_id}/apply",
        response_model=WorkspaceApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_edit(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        preview_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceApplyCommand,
    ) -> WorkspaceApplyResult:
        try:
            return service.apply_workspace_edit(session_id, preview_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/transactions",
        response_model=WorkspaceTransactionPreview,
        status_code=201,
    )
    def preview_workspace_transaction(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceTransactionPreviewCommand,
    ) -> WorkspaceTransactionPreview:
        try:
            return service.preview_workspace_transaction(session_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/workspace/transactions/{plan_id}/apply",
        response_model=WorkspaceTransactionApplyResult,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def apply_workspace_transaction(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        plan_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: WorkspaceTransactionApplyCommand,
    ) -> WorkspaceTransactionApplyResult:
        try:
            return service.apply_workspace_transaction(session_id, plan_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.get(
        "/sessions/{session_id}/events/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    def stream_events(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 500,
    ) -> StreamingResponse:
        try:
            service.get(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None
        return StreamingResponse(
            _stream_event_pages(service, session_id, after, limit),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, private",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post(
        "/sessions/{session_id}/approvals/{approval_id}",
        response_model=AgentSessionView,
        dependencies=[Depends(require_browser_confirmation)],
    )
    def decide(
        session_id: Annotated[str, Path(pattern=_SESSION_ID)],
        approval_id: Annotated[str, Path(pattern=_SESSION_ID)],
        payload: ApprovalDecision,
    ) -> AgentSessionView:
        try:
            return service.approve(session_id, approval_id, payload)
        except LocalAgentError as error:
            raise _failure(error) from None

    @router.post("/sessions/{session_id}/stop", response_model=AgentSessionView)
    def stop(session_id: Annotated[str, Path(pattern=_SESSION_ID)]) -> AgentSessionView:
        try:
            return service.stop(session_id)
        except LocalAgentError as error:
            raise _failure(error) from None

    return router


__all__ = ("create_local_agent_router",)
