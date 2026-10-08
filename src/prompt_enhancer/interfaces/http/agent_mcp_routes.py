"""Direct, authenticated Streamable HTTP transport for the local Agent MCP.

The HTTP endpoint is stateless: it starts no subprocess and owns no model.
Each client uses a narrowly scoped, revocable bearer derived by the local app;
browser and main-API credentials are deliberately not accepted by the MCP
route.  Connection management remains behind the owned native confirmation
boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ... import __version__
from ...application.agent_controller_ownership import (
    AgentControllerOwnershipError,
    AgentControllerOwnershipReleaseReceipt,
    ReleaseAgentControllerOwnership,
)
from ...application.agent_mcp_connections import (
    AGENT_MCP_HTTP_PATH,
    AGENT_MCP_MANAGEMENT_PATH,
    AGENT_MCP_SETUP_PATH,
    AgentMcpClientSetup,
    AgentMcpConnection,
    AgentMcpConnectionCredential,
    AgentMcpConnectionError,
    AgentMcpConnectionList,
    AgentMcpConnectionService,
    AgentMcpPrincipal,
    AgentMcpToolOutcome,
    AgentMcpToolSource,
    CreateAgentMcpConnection,
    RevokeAgentMcpConnection,
    RotateAgentMcpConnection,
    build_agent_mcp_setup_document,
)
from ..agent_mcp import AGENT_MCP_INSTRUCTIONS, AGENT_MCP_SERVER_NAME
from ..mcp.server import (
    MAX_MESSAGE_BYTES,
    MCP_PROTOCOL_VERSION,
    McpToolSurface,
    handle_message,
)
from .desktop_identity import exact_request_loopback_origin


AgentMcpSurfaceFactory = Callable[[str, AgentMcpPrincipal], McpToolSurface]
AgentControllerSessionSettled = Callable[[str], bool]
_AUTHENTICATE_HEADER = 'Bearer realm="prompt-enhancer-agent-mcp"'
AGENT_MCP_SELF_TEST_HEADER = "x-prompt-enhancer-mcp-probe"
AGENT_MCP_SELF_TEST_HEADER_VALUE = "native-endpoint-self-test.v1"
_JSON_RPC_PARSE_ERROR = {
    "jsonrpc": "2.0",
    "id": None,
    "error": {"code": -32700, "message": "parse error"},
}
_JSON_RPC_INVALID_REQUEST = {
    "jsonrpc": "2.0",
    "id": None,
    "error": {"code": -32600, "message": "invalid request"},
}


def _private_headers(*, protocol: bool = False) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store, private",
        "Pragma": "no-cache",
    }
    if protocol:
        headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    return headers


def _positive_media_types(value: str | None) -> set[str]:
    accepted: set[str] = set()
    for raw_range in (value or "").split(","):
        parts = [part.strip() for part in raw_range.split(";")]
        media_type = parts[0].casefold()
        if not media_type:
            continue
        quality = 1.0
        valid = True
        for parameter in parts[1:]:
            name, separator, raw_value = parameter.partition("=")
            if name.strip().casefold() != "q":
                continue
            try:
                quality = float(raw_value.strip()) if separator else -1.0
            except ValueError:
                valid = False
            if not 0.0 <= quality <= 1.0:
                valid = False
        if valid and quality > 0:
            accepted.add(media_type)
    return accepted


def _accepts_streamable_http(request: Request) -> bool:
    accepted = _positive_media_types(request.headers.get("accept"))
    return {
        "application/json",
        "text/event-stream",
    }.issubset(accepted)


def _is_json_content_type(request: Request) -> bool:
    value = request.headers.get("content-type") or ""
    return value.partition(";")[0].strip().casefold() == "application/json"


def _tool_activity_name(
    message: Mapping[str, Any],
    surface: McpToolSurface,
) -> str | None:
    if message.get("method") != "tools/call":
        return None
    params = message.get("params")
    if not isinstance(params, Mapping):
        return "unknown_tool"
    requested = params.get("name")
    if not isinstance(requested, str):
        return "unknown_tool"
    allowed = {tool.name for tool in surface.tools()}
    return requested if requested in allowed else "unknown_tool"


def _tool_activity_outcome(
    reply: Mapping[str, Any] | None,
) -> AgentMcpToolOutcome:
    if reply is None:
        return "failed"
    result = reply.get("result")
    if not isinstance(result, Mapping) or result.get("isError") is not False:
        return "failed"
    return "succeeded"


def _tool_activity_source(request: Request) -> AgentMcpToolSource:
    if (
        request.headers.get(AGENT_MCP_SELF_TEST_HEADER)
        == AGENT_MCP_SELF_TEST_HEADER_VALUE
    ):
        return "native_self_test"
    return "external_client"


async def _bounded_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_MESSAGE_BYTES:
            raise HTTPException(status_code=413, detail="MCP message too large")
    return bytes(body)


def _connection_endpoint(request: Request) -> str:
    origin = exact_request_loopback_origin(
        request.headers.get("host"),
        request.scope.get("server"),
    )
    if origin is None:
        raise HTTPException(
            status_code=403,
            detail="exact loopback authority required",
        )
    return origin + AGENT_MCP_HTTP_PATH


def _management_error(error: AgentMcpConnectionError) -> HTTPException:
    if error.code == "agent_mcp_connection_not_found":
        status = 404
    elif error.code == "agent_mcp_connection_storage_unavailable":
        status = 503
    elif error.code in {
        "agent_mcp_connection_identity_conflict",
        "agent_mcp_connection_inactive",
        "agent_mcp_connection_replay_inactive",
        "agent_mcp_connection_request_conflict",
        "agent_mcp_connection_revision_conflict",
        "agent_mcp_scope_project_unavailable",
        "agent_mcp_rotation_replay_stale",
        "agent_mcp_rotation_request_conflict",
        "agent_mcp_tool_activity_exhausted",
        "agent_mcp_tool_activity_stale",
        "too_many_agent_mcp_connections",
    }:
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail=error.code)


def _ownership_error(error: AgentControllerOwnershipError) -> HTTPException:
    if error.code == "agent_controller_ownership_not_found":
        status = 404
    elif error.code == "agent_controller_ownership_storage_unavailable":
        status = 503
    elif error.code in {
        "agent_controller_connection_inactive",
        "agent_controller_ownership_revision_conflict",
        "agent_controller_session_not_settled",
        "agent_controller_session_owned",
    }:
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail=error.code)


def _authenticate_mcp(
    request: Request,
    service: AgentMcpConnectionService,
) -> AgentMcpPrincipal:
    values = request.headers.getlist("authorization")
    token = ""
    if len(values) == 1:
        scheme, separator, candidate = values[0].partition(" ")
        if (
            separator
            and scheme.casefold() == "bearer"
            and candidate
            and candidate == candidate.strip()
            and not any(character.isspace() for character in candidate)
            and len(candidate) <= 192
        ):
            token = candidate
    try:
        return service.authenticate(token)
    except AgentMcpConnectionError:
        raise HTTPException(
            status_code=401,
            detail="MCP authentication required",
            headers={"WWW-Authenticate": _AUTHENTICATE_HEADER},
        ) from None


def _json_rpc_response(
    payload: Mapping[str, Any],
    *,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(
        content=dict(payload),
        status_code=status_code,
        headers=_private_headers(protocol=True),
        media_type="application/json",
    )


def create_agent_mcp_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: AgentMcpConnectionService,
    surface_factory: AgentMcpSurfaceFactory,
    session_settled: AgentControllerSessionSettled | None = None,
) -> APIRouter:
    """Create connection-management routes and the direct MCP endpoint."""

    router = APIRouter(tags=["agent-mcp"])
    local_auth = Depends(require_local_auth)
    native_confirmation = Depends(require_user_confirmation)

    @router.get(
        AGENT_MCP_SETUP_PATH,
        response_model=AgentMcpClientSetup,
        dependencies=[local_auth],
    )
    def client_setup(request: Request, response: Response) -> AgentMcpClientSetup:
        response.headers.update(_private_headers())
        try:
            return build_agent_mcp_setup_document(_connection_endpoint(request))
        except AgentMcpConnectionError as error:
            raise _management_error(error) from None

    @router.get(
        AGENT_MCP_MANAGEMENT_PATH,
        response_model=AgentMcpConnectionList,
        dependencies=[local_auth],
    )
    def list_connections(response: Response) -> AgentMcpConnectionList:
        response.headers.update(_private_headers())
        try:
            return service.list()
        except AgentMcpConnectionError as error:
            raise _management_error(error) from None

    @router.post(
        AGENT_MCP_MANAGEMENT_PATH,
        response_model=AgentMcpConnectionCredential,
        dependencies=[local_auth, native_confirmation],
    )
    def create_connection(
        payload: CreateAgentMcpConnection,
        request: Request,
        response: Response,
    ) -> AgentMcpConnectionCredential:
        response.headers.update(_private_headers())
        try:
            return service.create(
                payload,
                endpoint_url=_connection_endpoint(request),
            )
        except AgentMcpConnectionError as error:
            raise _management_error(error) from None

    @router.post(
        AGENT_MCP_MANAGEMENT_PATH + "/{connection_id}/rotate",
        response_model=AgentMcpConnectionCredential,
        dependencies=[local_auth, native_confirmation],
    )
    def rotate_connection(
        connection_id: str,
        payload: RotateAgentMcpConnection,
        request: Request,
        response: Response,
    ) -> AgentMcpConnectionCredential:
        response.headers.update(_private_headers())
        try:
            return service.rotate(
                connection_id,
                payload,
                endpoint_url=_connection_endpoint(request),
            )
        except AgentMcpConnectionError as error:
            raise _management_error(error) from None

    @router.post(
        AGENT_MCP_MANAGEMENT_PATH + "/{connection_id}/revoke",
        response_model=AgentMcpConnection,
        dependencies=[local_auth, native_confirmation],
    )
    def revoke_connection(
        connection_id: str,
        payload: RevokeAgentMcpConnection,
        response: Response,
    ) -> AgentMcpConnection:
        response.headers.update(_private_headers())
        try:
            return service.revoke(connection_id, payload)
        except AgentMcpConnectionError as error:
            raise _management_error(error) from None

    @router.post(
        AGENT_MCP_MANAGEMENT_PATH + "/ownerships/release",
        response_model=AgentControllerOwnershipReleaseReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def release_controller_ownership(
        payload: ReleaseAgentControllerOwnership,
        response: Response,
    ) -> AgentControllerOwnershipReleaseReceipt:
        """Release stale control only after the native backend proves settlement."""

        response.headers.update(_private_headers())
        if session_settled is None:
            raise HTTPException(
                status_code=503,
                detail="agent_controller_settlement_unavailable",
            )
        try:
            settled = session_settled(payload.session_id)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="agent_controller_settlement_unavailable",
            ) from None
        try:
            return service.ownership.release_native(
                payload,
                session_settled=settled,
            )
        except AgentControllerOwnershipError as error:
            raise _ownership_error(error) from None

    @router.post(AGENT_MCP_HTTP_PATH, include_in_schema=False)
    async def agent_mcp(request: Request) -> Response:
        principal = _authenticate_mcp(request, service)
        if request.headers.get("content-encoding") not in {None, "", "identity"}:
            raise HTTPException(
                status_code=415,
                detail="encoded MCP requests are unsupported",
            )
        if not _is_json_content_type(request):
            raise HTTPException(
                status_code=415,
                detail="MCP requests require application/json",
            )
        if not _accepts_streamable_http(request):
            raise HTTPException(
                status_code=406,
                detail="MCP Accept must include JSON and event stream",
            )
        body = await _bounded_body(request)
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _json_rpc_response(_JSON_RPC_PARSE_ERROR, status_code=400)
        if not isinstance(message, Mapping):
            return _json_rpc_response(_JSON_RPC_INVALID_REQUEST, status_code=400)
        method = message.get("method")
        if (
            method != "initialize"
            and request.headers.get("mcp-protocol-version")
            != MCP_PROTOCOL_VERSION
        ):
            raise HTTPException(
                status_code=400,
                detail="unsupported or missing MCP protocol version",
            )
        surface = surface_factory(
            _connection_endpoint(request).removesuffix(AGENT_MCP_HTTP_PATH),
            principal,
        )
        tool_activity_name = _tool_activity_name(message, surface)
        tool_activity_source = _tool_activity_source(request)
        tool_activity_sequence: int | None = None
        if tool_activity_name is not None:
            try:
                tool_activity_sequence = service.begin_tool_call(
                    principal.connection_id,
                    credential_revision=principal.credential_revision,
                    tool_name=tool_activity_name,
                    source=tool_activity_source,
                )
            except AgentMcpConnectionError as error:
                # An unsequenced tool call could be hidden between acceptance
                # observations. Fail before dispatch rather than execute an
                # action that the content-free controller ledger cannot order.
                raise _management_error(error) from None
        try:
            reply = await run_in_threadpool(
                handle_message,
                surface,
                message,
                version=__version__,
                server_name=AGENT_MCP_SERVER_NAME,
                instructions=AGENT_MCP_INSTRUCTIONS,
            )
        except Exception:
            if tool_activity_name is not None and tool_activity_sequence is not None:
                try:
                    service.finish_tool_call(
                        principal.connection_id,
                        credential_revision=principal.credential_revision,
                        sequence=tool_activity_sequence,
                        tool_name=tool_activity_name,
                        outcome="failed",
                        source=tool_activity_source,
                    )
                except AgentMcpConnectionError:
                    pass
            raise
        if tool_activity_name is not None and tool_activity_sequence is not None:
            try:
                service.finish_tool_call(
                    principal.connection_id,
                    credential_revision=principal.credential_revision,
                    sequence=tool_activity_sequence,
                    tool_name=tool_activity_name,
                    outcome=_tool_activity_outcome(reply),
                    source=tool_activity_source,
                )
            except AgentMcpConnectionError:
                # The call may have settled while native code rotated or
                # revoked its credential. Preserve the tool response, but keep
                # the admitted cursor incomplete so acceptance cannot pass.
                pass
        if reply is None:
            return Response(status_code=202, headers=_private_headers(protocol=True))
        return _json_rpc_response(reply)

    @router.get(AGENT_MCP_HTTP_PATH, include_in_schema=False)
    def agent_mcp_get(request: Request) -> Response:
        _authenticate_mcp(request, service)
        return Response(
            status_code=405,
            headers={**_private_headers(protocol=True), "Allow": "POST"},
        )

    @router.delete(AGENT_MCP_HTTP_PATH, include_in_schema=False)
    def agent_mcp_delete(request: Request) -> Response:
        _authenticate_mcp(request, service)
        return Response(
            status_code=405,
            headers={**_private_headers(protocol=True), "Allow": "POST"},
        )

    return router


__all__ = (
    "AGENT_MCP_SELF_TEST_HEADER",
    "AGENT_MCP_SELF_TEST_HEADER_VALUE",
    "AgentControllerSessionSettled",
    "AgentMcpSurfaceFactory",
    "create_agent_mcp_router",
)
