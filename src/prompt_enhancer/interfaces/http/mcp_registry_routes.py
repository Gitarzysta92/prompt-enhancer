"""Authenticated read-only MCP Store catalog routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from ...application.mcp_registry_catalog import (
    MCP_REGISTRY_DEFAULT_LIMIT,
    MCP_REGISTRY_MAX_CURSOR_CHARS,
    MCP_REGISTRY_MAX_LIMIT,
    MCP_REGISTRY_MAX_SEARCH_CHARS,
    MCP_STORE_CATALOG_PATH,
    MCP_STORE_ICON_PATH_PREFIX,
    MCP_STORE_SERVER_PATH_PREFIX,
    McpRegistryCatalog,
    McpRegistryCatalogError,
    McpRegistryCatalogService,
    McpRegistryServerReview,
)


def _private_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, private",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


def _error(error: McpRegistryCatalogError) -> HTTPException:
    if error.code in {
        "mcp_registry_icon_not_found",
        "mcp_registry_server_not_found",
    }:
        status = 404
    elif error.code in {
        "mcp_registry_query_invalid",
        "mcp_registry_cursor_invalid",
        "mcp_registry_limit_invalid",
        "mcp_registry_server_identity_invalid",
    }:
        status = 400
    elif error.code == "mcp_registry_source_disagreement":
        status = 409
    elif error.code in {
        "mcp_registry_identity_conflict",
        "mcp_registry_pagination_cycle",
        "mcp_registry_response_invalid",
    }:
        status = 502
    else:
        status = 503
    return HTTPException(status_code=status, detail=error.code)


def create_mcp_registry_router(
    require_local_auth: Callable[..., None],
    service: McpRegistryCatalogService,
) -> APIRouter:
    router = APIRouter(
        tags=["mcp-store"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get(MCP_STORE_CATALOG_PATH, response_model=McpRegistryCatalog)
    def list_catalog(
        response: Response,
        search: str = Query(default="", max_length=MCP_REGISTRY_MAX_SEARCH_CHARS),
        cursor: str | None = Query(default=None, max_length=MCP_REGISTRY_MAX_CURSOR_CHARS),
        limit: int = Query(
            default=MCP_REGISTRY_DEFAULT_LIMIT,
            ge=1,
            le=MCP_REGISTRY_MAX_LIMIT,
        ),
    ) -> McpRegistryCatalog:
        response.headers.update(_private_headers())
        try:
            return service.list_servers(search=search, cursor=cursor, limit=limit)
        except McpRegistryCatalogError as error:
            raise _error(error) from None

    @router.get(
        f"{MCP_STORE_SERVER_PATH_PREFIX}/{{catalog_id}}/review",
        response_model=McpRegistryServerReview,
    )
    def review_server(
        response: Response,
        catalog_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        name: str = Query(min_length=3, max_length=241),
        version: str = Query(min_length=1, max_length=255),
        presentation_revision: str = Query(pattern=r"^[0-9a-f]{64}$"),
    ) -> McpRegistryServerReview:
        response.headers.update(_private_headers())
        try:
            return service.review_server(
                catalog_id=catalog_id,
                name=name,
                version=version,
                presentation_revision=presentation_revision,
            )
        except McpRegistryCatalogError as error:
            raise _error(error) from None

    @router.get(
        f"{MCP_STORE_ICON_PATH_PREFIX}/{{icon_key}}",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "image/png": {},
                    "image/jpeg": {},
                    "image/webp": {},
                },
                "description": "A bounded raster icon proxied from an approved host.",
            }
        },
    )
    def get_icon(
        icon_key: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> Response:
        try:
            content = service.get_icon(icon_key)
        except McpRegistryCatalogError as error:
            raise _error(error) from None
        return Response(
            content=content.body,
            media_type=content.media_type,
            headers={
                "Cache-Control": "private, max-age=86400, immutable",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    return router


__all__ = ("create_mcp_registry_router",)
