"""Local model runtimes: list, add, activate/deactivate, downloads, chat proxy."""

from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from ...application.local_models import (
    ALIAS_PATTERN,
    ActivateLocalModel,
    AddLocalModel,
    ChatUpstream,
    ChatInputTokenCount,
    DownloadCommandRequest,
    DownloadRequest,
    DownloadStatus,
    LocalModelError,
    LocalModelCompatibilityCatalog,
    LocalModelPlacementAdmission,
    LocalModelRecord,
    LocalModelService,
    LocalModelStatus,
    LocalModelsOverview,
    LocalRuntimeCoordinatorStatus,
    RemoteRepoFiles,
    ScanFolderRequest,
    ScanFolderResult,
    StopLocalRuntime,
    SwitchLocalRuntime,
)
from ...application.runtime_cancellation import runtime_request_scope
from ...domain import StrictModel

import json


_STATUS_FOR_CODE = {
    "model_not_found": 404,
    "alias_exists": 409,
    "model_file_invalid": 422,
    "model_file_missing": 409,
    "model_projector_invalid": 422,
    "model_projector_missing": 409,
    "runtime_unavailable": 409,
    "runtime_placement_unavailable": 409,
    "runtime_gpu_layers_invalid": 409,
    "runtime_context_unsupported": 409,
    "runtime_spawn_failed": 502,
    "runtime_not_healthy": 502,
    "runtime_unreachable": 502,
    "runtime_activation_superseded": 409,
    "runtime_shutdown_in_progress": 409,
    "runtime_busy": 409,
    "runtime_revision_conflict": 409,
    "runtime_quarantined": 409,
    "runtime_stop_failed": 503,
    "runtime_cleanup_unconfirmed": 503,
    "runtime_capability_probe_failed": 502,
    "model_not_active": 409,
    "chat_body_invalid": 422,
    "chat_body_too_large": 413,
    "context_window_exceeded": 413,
    "input_tokens_unavailable": 409,
    "huggingface_hub_unavailable": 409,
    "folder_not_found": 422,
    "remote_repo_unavailable": 502,
    "provenance_unavailable": 409,
    "provenance_mismatch": 409,
    "file_not_eligible": 409,
    "download_not_found": 404,
    "download_revision_conflict": 409,
    "download_action_invalid": 409,
    "download_ledger_invalid": 409,
    "download_ledger_unavailable": 503,
    "download_adapter_incompatible": 409,
    "download_cleanup_failed": 503,
    "runtime_crashed": 502,
    "runtime_out_of_memory": 502,
}


class LocalModelNotFoundFailureDetail(StrictModel):
    code: Literal["model_not_found"]


class LocalModelNotFoundFailureResponse(StrictModel):
    detail: LocalModelNotFoundFailureDetail


class LocalModelActivationConflictFailureDetail(StrictModel):
    code: Literal[
        "model_file_missing",
        "model_projector_missing",
        "runtime_unavailable",
        "runtime_placement_unavailable",
        "runtime_gpu_layers_invalid",
        "runtime_context_unsupported",
        "runtime_activation_superseded",
        "runtime_shutdown_in_progress",
        "runtime_busy",
        "runtime_revision_conflict",
        "runtime_quarantined",
    ]


class LocalModelActivationConflictFailureResponse(StrictModel):
    detail: LocalModelActivationConflictFailureDetail


class LocalModelActivationFailureDetail(StrictModel):
    code: Literal[
        "runtime_spawn_failed",
        "runtime_not_healthy",
        "runtime_capability_probe_failed",
        "runtime_crashed",
        "runtime_out_of_memory",
    ]


class LocalModelActivationFailureResponse(StrictModel):
    detail: LocalModelActivationFailureDetail


class LocalModelStopFailureDetail(StrictModel):
    code: Literal["runtime_stop_failed", "runtime_cleanup_unconfirmed"]


class LocalModelStopFailureResponse(StrictModel):
    detail: LocalModelStopFailureDetail


class LocalModelContextFailureDetail(StrictModel):
    code: Literal["context_window_exceeded", "input_tokens_unavailable"]


class LocalModelContextFailureResponse(StrictModel):
    detail: LocalModelContextFailureDetail


class LocalModelDownloadNotFoundFailureDetail(StrictModel):
    code: Literal["download_not_found"]


class LocalModelDownloadNotFoundFailureResponse(StrictModel):
    detail: LocalModelDownloadNotFoundFailureDetail


class LocalModelDownloadConflictFailureDetail(StrictModel):
    code: Literal[
        "alias_exists",
        "download_action_invalid",
        "download_revision_conflict",
        "download_ledger_invalid",
        "download_adapter_incompatible",
        "huggingface_hub_unavailable",
        "provenance_unavailable",
        "provenance_mismatch",
        "file_not_eligible",
    ]


class LocalModelDownloadConflictFailureResponse(StrictModel):
    detail: LocalModelDownloadConflictFailureDetail


class LocalModelDownloadUnavailableFailureDetail(StrictModel):
    code: Literal["download_cleanup_failed", "download_ledger_unavailable"]


class LocalModelDownloadUnavailableFailureResponse(StrictModel):
    detail: LocalModelDownloadUnavailableFailureDetail


class LocalModelDownloadUpstreamFailureDetail(StrictModel):
    code: Literal["remote_repo_unavailable"]


class LocalModelDownloadUpstreamFailureResponse(StrictModel):
    detail: LocalModelDownloadUpstreamFailureDetail


_DOWNLOAD_START_RESPONSES = {
    409: {"model": LocalModelDownloadConflictFailureResponse},
    502: {"model": LocalModelDownloadUpstreamFailureResponse},
    503: {"model": LocalModelDownloadUnavailableFailureResponse},
}
_DOWNLOAD_COMMAND_RESPONSES = {
    404: {"model": LocalModelDownloadNotFoundFailureResponse},
    **_DOWNLOAD_START_RESPONSES,
}


def _failure(error: LocalModelError) -> HTTPException:
    return HTTPException(status_code=_STATUS_FOR_CODE.get(error.code, 500), detail={"code": error.code})


def _close_chat(upstream: ChatUpstream) -> None:
    try:
        if upstream.cancel is not None:
            upstream.cancel()
    finally:
        close = getattr(upstream.lines, "close", None)
        if callable(close):
            close()


class _ChatRelayResponse(Response):
    """Own connect, headers and streaming until delivery or client disconnect.

    There is exactly one ASGI receive consumer, including before headers. The
    standard streaming sender still handles framing and the iterator thread
    pool; calling stream_response avoids starting a second disconnect watcher.
    """

    def __init__(self, open_chat: Callable[[], ChatUpstream]):
        super().__init__(content=b"")
        self._open_chat = open_chat

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        cancelled = threading.Event()
        upstream = None
        failure = None
        disconnected = False
        delivery_finished = False

        async with anyio.create_task_group() as tasks:
            async def watch_disconnect() -> None:
                nonlocal disconnected
                try:
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            disconnected = True
                            tasks.cancel_scope.cancel()
                            return
                finally:
                    # Also release the worker when the ASGI request itself is
                    # cancelled during application shutdown.
                    if not delivery_finished:
                        disconnected = True
                    cancelled.set()

            tasks.start_soon(watch_disconnect)
            try:
                with runtime_request_scope(cancelled):
                    try:
                        # Never wait for a runtime socket on the API event loop.
                        # The worker is joined, not abandoned on cancellation.
                        upstream = await run_in_threadpool(self._open_chat)
                    except LocalModelError as error:
                        failure = error
                    if upstream is not None and not cancelled.is_set():
                        if upstream.lines is not None:
                            response = StreamingResponse(
                                upstream.lines, status_code=upstream.status_code,
                                media_type="text/event-stream",
                                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                            )
                            await response.stream_response(send)
                        else:
                            response = Response(
                                content=upstream.body or b"", status_code=upstream.status_code,
                                media_type=upstream.content_type, headers={"Cache-Control": "no-store"},
                            )
                            await response(scope, receive, send)
            except OSError:
                # ASGI 2.4+ may report a closed client through send as well.
                disconnected = True
            finally:
                delivery_finished = True
                cancelled.set()
                try:
                    with anyio.CancelScope(shield=True):
                        if upstream is not None:
                            await run_in_threadpool(_close_chat, upstream)
                finally:
                    tasks.cancel_scope.cancel()
        # Raise outside the task group so exception handlers receive the normal
        # sanitized HTTP error rather than an ExceptionGroup or a false 200.
        if failure is not None and not disconnected:
            raise _failure(failure) from None


def create_local_model_router(require_local_auth: Callable[..., None], service: LocalModelService) -> APIRouter:
    router = APIRouter(prefix="/v1/local-models", tags=["local-models"], dependencies=[Depends(require_local_auth)])

    @router.get("", response_model=LocalModelsOverview)
    def overview() -> LocalModelsOverview:
        return service.overview()

    @router.get("/compatibility", response_model=LocalModelCompatibilityCatalog)
    def compatibility() -> LocalModelCompatibilityCatalog:
        """Path-free model identity and live executable compatibility truth."""

        return service.compatibility_catalog()

    @router.post("", response_model=LocalModelRecord, status_code=201)
    def add(payload: AddLocalModel) -> LocalModelRecord:
        try:
            return service.add(payload)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.get("/remote-files", response_model=RemoteRepoFiles)
    def remote_files(repo_id: Annotated[str, Query(min_length=3, max_length=200)]) -> RemoteRepoFiles:
        try:
            return service.remote_files(repo_id)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post("/scan-folder", response_model=ScanFolderResult)
    def scan_folder(payload: ScanFolderRequest) -> ScanFolderResult:
        """Register every GGUF in a folder (one level deep); nothing is moved or downloaded."""

        try:
            return service.scan_folder(payload)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/downloads",
        response_model=DownloadStatus,
        status_code=202,
        responses=_DOWNLOAD_START_RESPONSES,
    )
    def start_download(payload: DownloadRequest) -> DownloadStatus:
        try:
            return service.start_download(payload)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/downloads/{download_id}/pause",
        response_model=DownloadStatus,
        responses=_DOWNLOAD_COMMAND_RESPONSES,
    )
    def pause_download(
        download_id: Annotated[str, Path(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
        payload: DownloadCommandRequest,
    ) -> DownloadStatus:
        try:
            return service.pause_download(
                download_id,
                expected_revision=payload.expected_status_revision,
            )
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/downloads/{download_id}/resume",
        response_model=DownloadStatus,
        responses=_DOWNLOAD_COMMAND_RESPONSES,
    )
    def resume_download(
        download_id: Annotated[str, Path(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
        payload: DownloadCommandRequest,
    ) -> DownloadStatus:
        try:
            return service.resume_download(
                download_id,
                expected_revision=payload.expected_status_revision,
            )
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/downloads/{download_id}/retry",
        response_model=DownloadStatus,
        responses=_DOWNLOAD_COMMAND_RESPONSES,
    )
    def retry_download(
        download_id: Annotated[str, Path(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
        payload: DownloadCommandRequest,
    ) -> DownloadStatus:
        try:
            return service.retry_download(
                download_id,
                expected_revision=payload.expected_status_revision,
            )
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/downloads/{download_id}/cancel",
        response_model=DownloadStatus,
        responses=_DOWNLOAD_COMMAND_RESPONSES,
    )
    def cancel_download(
        download_id: Annotated[str, Path(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
        payload: DownloadCommandRequest,
    ) -> DownloadStatus:
        try:
            return service.cancel_download(
                download_id,
                expected_revision=payload.expected_status_revision,
            )
        except LocalModelError as error:
            raise _failure(error) from None

    @router.get("/runtime", response_model=LocalRuntimeCoordinatorStatus)
    def runtime_status() -> LocalRuntimeCoordinatorStatus:
        """Truthful requested-versus-served state for the one global runtime."""

        return service.coordinator_status()

    @router.post(
        "/runtime/switch",
        response_model=LocalRuntimeCoordinatorStatus,
        responses={
            404: {"model": LocalModelNotFoundFailureResponse},
            409: {"model": LocalModelActivationConflictFailureResponse},
            502: {"model": LocalModelActivationFailureResponse},
            503: {"model": LocalModelStopFailureResponse},
        },
    )
    def switch_runtime(payload: SwitchLocalRuntime) -> LocalRuntimeCoordinatorStatus:
        try:
            return service.switch_runtime(payload)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/runtime/stop",
        response_model=LocalRuntimeCoordinatorStatus,
        responses={
            409: {"model": LocalModelActivationConflictFailureResponse},
            503: {"model": LocalModelStopFailureResponse},
        },
    )
    def stop_runtime(payload: StopLocalRuntime) -> LocalRuntimeCoordinatorStatus:
        try:
            return service.stop_runtime(payload)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.get("/{alias}", response_model=LocalModelStatus)
    def status(alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)]) -> LocalModelStatus:
        try:
            return service.status(alias)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.delete(
        "/{alias}",
        status_code=204,
        responses={
            404: {"model": LocalModelNotFoundFailureResponse},
            503: {"model": LocalModelStopFailureResponse},
        },
    )
    def remove(
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
        delete_weights: Annotated[bool, Query()] = False,
    ) -> Response:
        try:
            service.remove(alias, delete_weights=delete_weights)
        except LocalModelError as error:
            raise _failure(error) from None
        return Response(status_code=204)

    @router.post(
        "/{alias}/activate",
        response_model=LocalModelStatus,
        responses={
            404: {"model": LocalModelNotFoundFailureResponse},
            409: {"model": LocalModelActivationConflictFailureResponse},
            502: {"model": LocalModelActivationFailureResponse},
            503: {"model": LocalModelStopFailureResponse},
        },
    )
    def activate(
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
        payload: ActivateLocalModel | None = None,
    ) -> LocalModelStatus:
        try:
            return service.activate(alias, payload)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/{alias}/deactivate",
        response_model=LocalModelStatus,
        responses={
            404: {"model": LocalModelNotFoundFailureResponse},
            503: {"model": LocalModelStopFailureResponse},
        },
    )
    def deactivate(alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)]) -> LocalModelStatus:
        try:
            service.deactivate(alias)
            return service.status(alias)
        except LocalModelError as error:
            raise _failure(error) from None

    def _model_list(aliases: tuple[str, ...]) -> dict[str, object]:
        return {
            "object": "list",
            "data": [{"id": alias, "object": "model", "created": 0, "owned_by": "local"} for alias in aliases],
        }

    def _relay(alias: str, body: bytes) -> Response:
        return _ChatRelayResponse(lambda: service.open_chat(alias, body))

    @router.get("/openai/v1/models")
    def openai_models() -> dict[str, object]:
        """OpenAI-style model list for clients that use one base URL for every running model."""

        return _model_list(service.running_aliases())

    @router.post(
        "/openai/v1/chat/completions/input_tokens",
        response_model=ChatInputTokenCount,
        responses={409: {"model": LocalModelContextFailureResponse}},
    )
    async def openai_chat_input_tokens(request: Request) -> ChatInputTokenCount:
        """Exact chat-template input tokens, routed by the OpenAI ``model`` field."""

        body = await request.body()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=422, detail={"code": "chat_body_invalid"}) from None
        model = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(model, str) or ALIAS_PATTERN.fullmatch(model) is None:
            raise HTTPException(status_code=422, detail={"code": "chat_body_invalid"})
        try:
            return service.chat_input_tokens(model, body)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.get("/{alias}/placement", response_model=LocalModelPlacementAdmission)
    def placement_admission(
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
        context_size: Annotated[int | None, Query(ge=512, le=131072)] = None,
    ) -> LocalModelPlacementAdmission:
        """Conservative device admission for one model and context limit."""

        try:
            return service.placement_admission(alias, context_size=context_size)
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/openai/v1/chat/completions",
        responses={413: {"model": LocalModelContextFailureResponse}},
    )
    async def openai_chat_completions(request: Request) -> Response:
        """OpenAI-style chat completion routed by the ``model`` field to a running alias."""

        body = await request.body()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=422, detail={"code": "chat_body_invalid"}) from None
        model = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(model, str) or ALIAS_PATTERN.fullmatch(model) is None:
            raise HTTPException(status_code=422, detail={"code": "chat_body_invalid"})
        return _relay(model, body)

    @router.get("/{alias}/v1/models")
    def model_list(alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)]) -> dict[str, object]:
        """OpenAI-style single-model list, so ``…/{alias}/v1`` works as a base URL."""

        try:
            status = service.status(alias)
        except LocalModelError as error:
            raise _failure(error) from None
        return _model_list((alias,) if status.runtime.state == "running" else ())

    @router.post(
        "/{alias}/v1/chat/completions",
        responses={413: {"model": LocalModelContextFailureResponse}},
    )
    async def chat_completions_openai_base(
        request: Request,
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
    ) -> Response:
        """Same proxy under an OpenAI-style base URL (``…/{alias}/v1``)."""

        return _relay(alias, await request.body())

    @router.post(
        "/{alias}/v1/chat/completions/input_tokens",
        response_model=ChatInputTokenCount,
        responses={409: {"model": LocalModelContextFailureResponse}},
    )
    async def chat_input_tokens_openai_base(
        request: Request,
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
    ) -> ChatInputTokenCount:
        try:
            return service.chat_input_tokens(alias, await request.body())
        except LocalModelError as error:
            raise _failure(error) from None

    @router.post(
        "/{alias}/chat/completions",
        responses={413: {"model": LocalModelContextFailureResponse}},
    )
    async def chat_completions(
        request: Request,
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
    ) -> Response:
        """OpenAI-compatible chat completion proxied to the model's loopback runtime; ``stream: true`` relays SSE."""

        return _relay(alias, await request.body())

    @router.post(
        "/{alias}/chat/completions/input_tokens",
        response_model=ChatInputTokenCount,
        responses={409: {"model": LocalModelContextFailureResponse}},
    )
    async def chat_input_tokens(
        request: Request,
        alias: Annotated[str, Path(pattern=ALIAS_PATTERN.pattern)],
    ) -> ChatInputTokenCount:
        try:
            return service.chat_input_tokens(alias, await request.body())
        except LocalModelError as error:
            raise _failure(error) from None

    return router


__all__ = ("create_local_model_router",)
