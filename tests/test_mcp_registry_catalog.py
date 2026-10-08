"""Store-01: bounded official MCP Registry discovery without install authority."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any
import zlib

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import httpx2
from pydantic import SecretStr
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.mcp_registry_catalog import (
    MCP_STORE_CATALOG_PATH,
    MCP_STORE_SERVER_PATH_PREFIX,
    McpRegistryCacheRecord,
    McpRegistryCatalogError,
    McpRegistryCatalogService,
    McpRegistryClientError,
    McpRegistryIconContent,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.mcp_registry import JsonMcpRegistryCache
from prompt_enhancer.infrastructure.mcp_registry import (
    MAX_REGISTRY_ICON_BYTES,
    MAX_REGISTRY_RESPONSE_BYTES,
    McpRegistryTransportError,
    OfficialMcpRegistryHttpClient,
)
from prompt_enhancer.infrastructure.mcp_guarded_host import (
    MAX_MCP_HTTP_HEADER_VALUE_BYTES,
    PinnedMcpSyncTransport,
)
from prompt_enhancer.interfaces.http.mcp_registry_routes import create_mcp_registry_router


T0 = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return (
        len(data).to_bytes(4, "big")
        + kind
        + data
        + checksum.to_bytes(4, "big")
    )


def _synthetic_png(*, width: int = 1, height: int = 1) -> bytes:
    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )
    scanline = b"\x00" + (b"\x00\x00\x00\xff" * width)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(scanline * height))
        + _png_chunk(b"IEND", b"")
    )


SYNTHETIC_PNG = _synthetic_png()


def _page(*, icon: bool = True) -> dict[str, Any]:
    server: dict[str, Any] = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/example/server.schema.json",
        "name": "com.example/synthetic-files",
        "title": "Synthetic Files",
        "description": "Inspect fictional example files through MCP.",
        "version": "1.2.3",
        "websiteUrl": "https://example.com/synthetic-files",
        "repository": {
            "url": "https://github.com/example/synthetic-files",
            "source": "github",
        },
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/synthetic-files",
                "version": "1.2.3",
                "runtimeHint": "npx",
                "fileSha256": "a" * 64,
                "transport": {"type": "stdio"},
            }
        ],
        "remotes": [
            {
                "type": "streamable-http",
                "url": "https://mcp.example.com/service?public=example",
            }
        ],
    }
    if icon:
        server["icons"] = [
            {
                "src": "https://raw.githubusercontent.com/example/synthetic/main/icon.png",
                "mimeType": "image/png",
                "sizes": ["48x48"],
            }
        ]
    return {
        "servers": [
            {
                "server": server,
                "_meta": {
                    "io.modelcontextprotocol.registry/official": {
                        "status": "active",
                        "updatedAt": "2026-08-28T10:20:30Z",
                        "isLatest": True,
                    }
                },
            }
        ],
        "metadata": {"count": 1, "nextCursor": "com.example/synthetic-files:1.2.3"},
    }


def _detail_page() -> dict[str, Any]:
    detail = _page()["servers"][0]
    server = detail["server"]
    server["repository"].update(
        {"id": "synthetic-repository-id", "subfolder": "packages/files"}
    )
    package = server["packages"][0]
    package["runtimeArguments"] = [
        {
            "type": "named",
            "name": "--workspace",
            "description": "A fictional workspace folder.",
            "format": "filepath",
            "isRequired": True,
            "placeholder": "D:\\example\\workspace",
        }
    ]
    package["packageArguments"] = [
        {"type": "named", "name": "--mode", "value": "synthetic-fixed"}
    ]
    package["environmentVariables"] = [
        {
            "name": "EXAMPLE_TOKEN",
            "description": "A fictional access token.",
            "isRequired": True,
            "isSecret": True,
            "placeholder": "synthetic-secret-must-not-escape",
        }
    ]
    server["remotes"] = [
        {
            "type": "streamable-http",
            "url": "{base_url}/mcp?credential=synthetic-hidden-query",
            "headers": [
                {
                    "name": "Authorization",
                    "isRequired": True,
                    "isSecret": True,
                    "default": "synthetic-hidden-default",
                }
            ],
            "variables": {
                "base_url": {
                    "description": "Remote service base URL.",
                    "isRequired": True,
                    "format": "string",
                }
            },
        }
    ]
    return detail


def _versions_page() -> dict[str, Any]:
    selected = _detail_page()
    older = _detail_page()
    older["server"]["version"] = "1.1.0"
    older["server"]["packages"][0]["version"] = "1.1.0"
    older["_meta"]["io.modelcontextprotocol.registry/official"].update(
        {"isLatest": False, "updatedAt": "2026-07-01T10:20:30Z"}
    )
    return {"servers": [selected, older], "metadata": {"count": 2}}


def _probeable_remote_detail() -> dict[str, Any]:
    detail = _detail_page()
    detail["server"]["remotes"] = [
        {
            "type": "streamable-http",
            "url": "https://mcp.example.com/service?synthetic=hidden",
            "headers": [
                {"name": "X-Example-Mode", "value": "synthetic-fixed"},
                {
                    "name": "Authorization",
                    "isRequired": True,
                    "isSecret": True,
                },
            ],
        }
    ]
    return detail


def _mcpb_detail() -> dict[str, Any]:
    detail = _detail_page()
    detail["server"]["packages"] = [
        {
            "registryType": "mcpb",
            "identifier": (
                "https://github.com/example/synthetic-files/releases/download/"
                "v1.2.3/synthetic-files.mcpb"
            ),
            "version": "1.2.3",
            "fileSha256": "c" * 64,
            "transport": {"type": "stdio"},
        }
    ]
    return detail


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, McpRegistryCacheRecord] = {}

    def get(self, key: str) -> McpRegistryCacheRecord | None:
        return self.values.get(key)

    def put(self, key: str, record: McpRegistryCacheRecord) -> None:
        self.values[key] = record


class _EmptyReadStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self):
        return []

    def list_sessions(self, **_kwargs):
        return []

    def count_sessions(self, **_kwargs):
        return 0

    def get_session_metrics(self, _session_id: str):
        return []


class _Client:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or _page()
        self.fail = False
        self.calls: list[tuple[str, str | None, int]] = []
        self.detail_calls: list[tuple[str, str]] = []
        self.version_calls: list[str] = []
        self.icon_calls: list[str] = []
        self.icon_content = McpRegistryIconContent(
            media_type="image/png",
            body=SYNTHETIC_PNG,
        )
        self.detail_payload = _detail_page()
        self.versions_payload = _versions_page()
        self.fail_history = False

    def list_servers(self, *, search: str, cursor: str | None, limit: int):
        self.calls.append((search, cursor, limit))
        if self.fail:
            raise RuntimeError("synthetic registry unavailable")
        return self.payload

    def fetch_icon(self, source: str) -> McpRegistryIconContent:
        self.icon_calls.append(source)
        if self.fail:
            raise RuntimeError("synthetic icon unavailable")
        return self.icon_content

    def get_server_version(self, *, name: str, version: str):
        self.detail_calls.append((name, version))
        if self.fail:
            raise McpRegistryClientError("registry_unavailable")
        return self.detail_payload

    def list_server_versions(self, *, name: str):
        self.version_calls.append(name)
        if self.fail or self.fail_history:
            raise McpRegistryClientError("registry_unavailable")
        return self.versions_payload


def test_catalog_normalizes_public_metadata_without_install_authority() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)

    catalog = service.list_servers(search="  fictional   files ", limit=24)

    assert client.calls == [("fictional files", None, 24)]
    assert catalog.contract_version == "mcp-registry-catalog.v1"
    assert catalog.source.registry == "official_mcp_registry"
    assert catalog.source.delivery == "live"
    assert catalog.source.cache_age_seconds == 0
    assert catalog.search == "fictional files"
    assert catalog.next_cursor == "com.example/synthetic-files:1.2.3"
    assert catalog.management_truth == "registry_only_no_install_authority"
    assert len(catalog.servers) == 1
    server = catalog.servers[0]
    assert server.name == "com.example/synthetic-files"
    assert server.publisher == "com.example"
    assert server.repository_url == "https://github.com/example/synthetic-files"
    assert server.packages[0].registry_type == "npm"
    assert server.packages[0].checksum_available is True
    assert server.remotes[0].endpoint_host == "mcp.example.com"
    assert server.supports_local is True and server.supports_remote is True
    assert server.management_state == "not_managed"
    assert server.install_action == "unavailable"
    assert server.install_reason == "guarded_install_host_not_implemented"
    rendered = catalog.model_dump_json()
    assert "packageArguments" not in rendered
    assert "environmentVariables" not in rendered
    assert "public=example" not in rendered
    assert "raw.githubusercontent.com" not in rendered


def test_live_failure_uses_exact_restart_safe_cache_and_marks_it_cached(tmp_path: Path) -> None:
    now = [T0]
    client = _Client()
    cache = JsonMcpRegistryCache(tmp_path / "store" / "catalog.json")
    service = McpRegistryCatalogService(client, cache, clock=lambda: now[0])
    live = service.list_servers(search="files", limit=12)
    assert live.source.delivery == "live"

    client.fail = True
    now[0] += timedelta(hours=2)
    restarted = McpRegistryCatalogService(client, cache, clock=lambda: now[0])
    cached = restarted.list_servers(search="files", limit=12)

    assert cached.source.delivery == "cached"
    assert cached.source.cache_age_seconds == 7_200
    assert cached.servers == live.servers
    assert cache._path.stat().st_size < 4 * 1024 * 1024  # noqa: SLF001


def test_declared_raster_icon_without_extension_survives_restart_cache(
    tmp_path: Path,
) -> None:
    source = "https://raw.githubusercontent.com/example/synthetic/main/icon"
    payload = _page()
    payload["servers"][0]["server"]["icons"] = [
        {"src": source, "mimeType": "image/png"}
    ]
    client = _Client(payload)
    cache = JsonMcpRegistryCache(tmp_path / "store" / "catalog.json")
    service = McpRegistryCatalogService(client, cache, clock=lambda: T0)

    live = service.list_servers(search="extensionless", limit=12)
    assert live.servers[0].icon is not None

    client.fail = True
    restarted = McpRegistryCatalogService(client, cache, clock=lambda: T0)
    cached = restarted.list_servers(search="extensionless", limit=12)
    assert cached.source.delivery == "cached"
    assert cached.servers[0].icon == live.servers[0].icon

    client.fail = False
    key = cached.servers[0].icon.path.rsplit("/", 1)[1]
    assert restarted.get_icon(key).media_type == "image/png"
    assert client.icon_calls == [source]


def test_cache_is_bound_to_exact_search_cursor_and_limit() -> None:
    client = _Client()
    cache = _MemoryCache()
    service = McpRegistryCatalogService(client, cache, clock=lambda: T0)
    service.list_servers(search="files", limit=12)
    client.fail = True

    assert service.list_servers(search="files", limit=12).source.delivery == "cached"
    for kwargs in (
        {"search": "other", "limit": 12},
        {"search": "files", "limit": 24},
        {"search": "files", "cursor": "next", "limit": 12},
    ):
        try:
            service.list_servers(**kwargs)
        except McpRegistryCatalogError as error:
            assert error.code == "mcp_registry_unavailable"
        else:
            raise AssertionError("different query unexpectedly reused cached data")


def test_malformed_entries_are_skipped_and_catalog_admits_partial_truth() -> None:
    payload = _page()
    payload["servers"].extend(
        [
            {"server": {"name": "invalid", "description": "bad", "version": "1"}},
            {"not_server": {"name": "com.example/missing"}},
        ]
    )
    service = McpRegistryCatalogService(_Client(payload), _MemoryCache(), clock=lambda: T0)
    catalog = service.list_servers()
    assert len(catalog.servers) == 1
    assert catalog.partial is True


def test_unicode_format_controls_and_combining_floods_never_reach_catalog_text() -> None:
    for field, value in (
        ("title", "Synthetic\u202eFiles"),
        ("description", "Synthetic" + "\u0301" * 5),
    ):
        payload = _page()
        payload["servers"][0]["server"][field] = value
        catalog = McpRegistryCatalogService(
            _Client(payload),
            _MemoryCache(),
            clock=lambda: T0,
        ).list_servers()
        assert catalog.servers == ()
        assert catalog.partial is True


def test_unicode_format_controls_in_query_or_cursor_fail_before_network_use() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    for kwargs, code in (
        ({"search": "files\u202e"}, "mcp_registry_query_invalid"),
        ({"cursor": "cursor\u2066"}, "mcp_registry_cursor_invalid"),
    ):
        with pytest.raises(McpRegistryCatalogError) as failure:
            service.list_servers(**kwargs)
        assert failure.value.code == code
    assert client.calls == []


def test_duplicate_registry_identity_is_idempotent_only_when_every_field_agrees() -> None:
    payload = _page()
    payload["servers"].append(deepcopy(payload["servers"][0]))
    payload["metadata"]["count"] = 2
    catalog = McpRegistryCatalogService(
        _Client(payload),
        _MemoryCache(),
        clock=lambda: T0,
    ).list_servers()
    assert len(catalog.servers) == 1
    assert catalog.partial is False

    payload["servers"][1]["server"]["title"] = "Conflicting synthetic title"
    with pytest.raises(McpRegistryCatalogError) as conflict:
        McpRegistryCatalogService(
            _Client(payload),
            _MemoryCache(),
            clock=lambda: T0,
        ).list_servers()
    assert conflict.value.code == "mcp_registry_identity_conflict"


def test_identity_conflict_preserves_only_an_exact_preexisting_cache() -> None:
    client = _Client()
    cache = _MemoryCache()
    service = McpRegistryCatalogService(client, cache, clock=lambda: T0)
    trusted = service.list_servers()

    poisoned = _page()
    poisoned["servers"].append(deepcopy(poisoned["servers"][0]))
    poisoned["servers"][1]["server"]["description"] = "Contradictory metadata."
    client.payload = poisoned
    fallback = service.list_servers()

    assert fallback.source.delivery == "cached"
    assert fallback.servers == trusted.servers


def test_registry_page_cannot_return_its_own_cursor() -> None:
    payload = _page()
    payload["metadata"]["nextCursor"] = "synthetic-cursor"
    service = McpRegistryCatalogService(
        _Client(payload),
        _MemoryCache(),
        clock=lambda: T0,
    )
    with pytest.raises(McpRegistryCatalogError) as cycle:
        service.list_servers(cursor="synthetic-cursor")
    assert cycle.value.code == "mcp_registry_pagination_cycle"


def test_untrusted_or_svg_icons_never_reach_the_browser_contract() -> None:
    payload = _page(icon=False)
    payload["servers"][0]["server"]["icons"] = [
        {"src": "https://127.0.0.1/private.png", "mimeType": "image/png"},
        {"src": "https://example.com/active.svg", "mimeType": "image/svg+xml"},
    ]
    service = McpRegistryCatalogService(_Client(payload), _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    assert server.icon is None


def test_query_bearing_registry_artwork_is_never_registered_or_fetched() -> None:
    payload = _page(icon=False)
    payload["servers"][0]["server"]["icons"] = [
        {
            "src": "https://raw.githubusercontent.com/example/synthetic/main/icon.png?tracking=disabled",
            "mimeType": "image/png",
        }
    ]
    client = _Client(payload)
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    assert service.list_servers().servers[0].icon is None
    assert client.icon_calls == []


def test_icon_proxy_rejects_spoofed_corrupt_and_dimension_bomb_content() -> None:
    invalid_icons = (
        McpRegistryIconContent(media_type="image/png", body=b"<html>synthetic</html>"),
        McpRegistryIconContent(media_type="image/jpeg", body=SYNTHETIC_PNG),
        McpRegistryIconContent(media_type="image/png", body=SYNTHETIC_PNG[:-1] + b"x"),
        McpRegistryIconContent(media_type="image/png", body=_synthetic_png(width=1_025)),
    )
    for content in invalid_icons:
        client = _Client()
        client.icon_content = content
        service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
        server = service.list_servers().servers[0]
        assert server.icon is not None
        key = server.icon.path.rsplit("/", 1)[1]
        with pytest.raises(McpRegistryCatalogError) as unavailable:
            service.get_icon(key)
        assert unavailable.value.code == "mcp_registry_icon_unavailable"
        assert len(client.icon_calls) == 1


def test_icon_proxy_uses_registered_exact_source_and_memory_cache() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    assert server.icon is not None
    key = server.icon.path.rsplit("/", 1)[1]

    first = service.get_icon(key)
    second = service.get_icon(key)

    assert first == second == McpRegistryIconContent(
        media_type="image/png", body=SYNTHETIC_PNG
    )
    assert client.icon_calls == [
        "https://raw.githubusercontent.com/example/synthetic/main/icon.png"
    ]
    try:
        service.get_icon("0" * 32)
    except McpRegistryCatalogError as error:
        assert error.code == "mcp_registry_icon_not_found"
    else:
        raise AssertionError("unknown icon key was accepted")


def test_query_and_cursor_are_bounded_before_network_use() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    for kwargs, code in (
        ({"search": "x" * 101}, "mcp_registry_query_invalid"),
        ({"cursor": "x" * 513}, "mcp_registry_cursor_invalid"),
        ({"limit": 49}, "mcp_registry_limit_invalid"),
    ):
        try:
            service.list_servers(**kwargs)
        except McpRegistryCatalogError as error:
            assert error.code == code
        else:
            raise AssertionError("invalid registry request was accepted")
    assert client.calls == []


def test_http_surface_requires_local_auth_and_is_read_only() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    app = FastAPI()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer synthetic-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    app.include_router(create_mcp_registry_router(require_auth, service))
    http = TestClient(app)

    assert http.get(MCP_STORE_CATALOG_PATH).status_code == 401
    response = http.get(
        MCP_STORE_CATALOG_PATH,
        params={"search": "files", "limit": 12},
        headers={"Authorization": "Bearer synthetic-local-token"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["management_truth"] == "registry_only_no_install_authority"
    assert http.post(
        MCP_STORE_CATALOG_PATH,
        headers={"Authorization": "Bearer synthetic-local-token"},
    ).status_code == 405

    icon_path = response.json()["servers"][0]["icon"]["path"]
    icon = http.get(icon_path, headers={"Authorization": "Bearer synthetic-local-token"})
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/png"
    assert icon.headers["x-content-type-options"] == "nosniff"
    assert icon.content == SYNTHETIC_PNG


def test_full_app_security_middleware_preserves_private_catalog_headers(
    tmp_path: Path,
) -> None:
    token = "synthetic-local-token-do-not-use-123456"
    service = McpRegistryCatalogService(_Client(), _MemoryCache(), clock=lambda: T0)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=_EmptyReadStore(),
        api_token=token,
        mcp_registry_catalog_service=service,
    )
    with TestClient(app, base_url="http://127.0.0.1") as http:
        response = http.get(
            MCP_STORE_CATALOG_PATH,
            headers={API_TOKEN_HEADER: token},
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        assert response.headers["pragma"] == "no-cache"
        assert response.json()["management_truth"] == "registry_only_no_install_authority"

        server = response.json()["servers"][0]
        review = http.get(
            f"{MCP_STORE_SERVER_PATH_PREFIX}/{server['catalog_id']}/review",
            params={
                "name": server["name"],
                "version": server["version"],
                "presentation_revision": server["presentation_revision"],
            },
            headers={API_TOKEN_HEADER: token},
        )
    assert review.status_code == 200
    assert review.headers["cache-control"] == "no-store, private"
    assert review.headers["pragma"] == "no-cache"
    assert review.json()["install_action"] == "unavailable"


def test_exact_review_is_bound_to_the_catalog_presentation_revision() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]

    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        presentation_revision=server.presentation_revision,
    )
    assert review.server.presentation_revision == server.presentation_revision

    client.detail_payload["server"]["title"] = "Changed after catalog listing"
    with pytest.raises(McpRegistryCatalogError) as disagreement:
        service.review_server(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            presentation_revision=server.presentation_revision,
        )
    assert disagreement.value.code == "mcp_registry_source_disagreement"


def test_server_review_http_reports_source_disagreement_without_metadata_echo() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    client.detail_payload["server"]["description"] = "Changed after catalog listing."
    app = FastAPI()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer synthetic-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    app.include_router(create_mcp_registry_router(require_auth, service))
    response = TestClient(app).get(
        f"{MCP_STORE_SERVER_PATH_PREFIX}/{server.catalog_id}/review",
        params={
            "name": server.name,
            "version": server.version,
            "presentation_revision": server.presentation_revision,
        },
        headers={"Authorization": "Bearer synthetic-local-token"},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "mcp_registry_source_disagreement"}
    assert "Changed after" not in response.text


def test_server_review_discloses_plan_risks_without_exposing_declared_values() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    catalog_server = service.list_servers().servers[0]

    review = service.review_server(
        catalog_id=catalog_server.catalog_id,
        name=catalog_server.name,
        version=catalog_server.version,
    )

    assert client.detail_calls == [(catalog_server.name, catalog_server.version)]
    assert client.version_calls == [catalog_server.name]
    assert review.contract_version == "mcp-registry-server-review.v1"
    assert review.source.delivery == "live"
    assert review.review_truth == "preview_only_no_install_or_connection_authority"
    assert review.install_action == "unavailable"
    assert review.uninstall_action == "not_applicable"
    assert review.version_history_state == "live"
    assert [item.version for item in review.versions] == ["1.2.3", "1.1.0"]
    assert review.versions[0].selected is True
    assert review.provenance.repository_identity_declared is True
    assert review.provenance.repository_subfolder_declared is True
    assert review.provenance.license_state == "not_declared_by_registry_contract"
    assert review.provenance.registry_membership_security_review == "not_claimed"
    assert len(review.options) == 2

    local = next(item for item in review.options if item.kind == "local_package")
    assert local.compatibility.status == "requires_configuration"
    assert local.compatibility.platform_compatibility == "unverified"
    assert local.compatibility.runtime_availability == "unverified"
    assert local.compatibility.mcp_handshake == "not_performed"
    assert "downloads_package" in local.risks
    assert "executes_local_code" in local.risks
    assert "filesystem_input_declared" in local.risks
    assert "credential_input_declared" in local.risks
    assert {item.name for item in local.requirements} == {
        "--workspace",
        "--mode",
        "EXAMPLE_TOKEN",
    }
    token = next(item for item in local.requirements if item.name == "EXAMPLE_TOKEN")
    assert token.secret is True and token.user_value_needed is True

    remote = next(item for item in review.options if item.kind == "remote_server")
    assert remote.endpoint_state == "template_requires_configuration"
    assert remote.endpoint_host is None
    assert remote.compatibility.status == "requires_configuration"
    assert "remote_network_egress" in remote.risks
    assert {item.name for item in remote.requirements} == {
        "Authorization",
        "base_url",
    }

    rendered = review.model_dump_json()
    for forbidden in (
        "synthetic-secret-must-not-escape",
        "synthetic-hidden-query",
        "synthetic-hidden-default",
        "D:\\\\example\\\\workspace",
        "packageArguments",
        "runtimeArguments",
        "environmentVariables",
    ):
        assert forbidden not in rendered
    assert len(review.plan_revision) == 64
    repeated = service.review_server(
        catalog_id=catalog_server.catalog_id,
        name=catalog_server.name,
        version=catalog_server.version,
    )
    assert repeated.plan_revision == review.plan_revision


def test_latest_review_resolves_alias_then_binds_one_exact_version() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    expected_name = "com.example/synthetic-files"

    review = service.review_latest_server(name=expected_name)

    assert review.server.name == expected_name
    assert review.server.version == "1.2.3"
    assert review.server.catalog_id == hashlib.sha256(
        f"{expected_name}\x001.2.3".encode("utf-8")
    ).hexdigest()[:32]
    assert client.detail_calls == [
        (expected_name, "latest"),
        (expected_name, "1.2.3"),
    ]
    assert client.version_calls == [expected_name]


def test_latest_review_rejects_alias_response_for_another_server() -> None:
    client = _Client()
    mismatched = _detail_page()
    mismatched["server"]["name"] = "com.example/other-synthetic"
    client.detail_payload = mismatched
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)

    with pytest.raises(McpRegistryCatalogError) as error:
        service.review_latest_server(name="com.example/synthetic-files")

    assert error.value.code == "mcp_registry_response_invalid"


def test_internal_remote_resolution_is_exact_transient_and_plan_bound() -> None:
    client = _Client()
    client.detail_payload = _probeable_remote_detail()
    client.versions_payload = {
        "servers": [client.detail_payload],
        "metadata": {"count": 1},
    }
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    option = next(item for item in review.options if item.kind == "remote_server")

    resolved = service.resolve_remote_connection(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        option_id=option.option_id,
        plan_revision=review.plan_revision,
    )

    assert resolved.transport == "streamable-http"
    assert resolved.endpoint_host == "mcp.example.com"
    assert resolved.endpoint.get_secret_value().endswith("synthetic=hidden")
    assert [item.name for item in resolved.headers] == [
        "X-Example-Mode",
        "Authorization",
    ]
    assert resolved.headers[0].declared_value.get_secret_value() == "synthetic-fixed"
    assert resolved.headers[1].declared_value is None
    rendered = resolved.model_dump_json()
    assert "synthetic=hidden" not in rendered
    assert "synthetic-fixed" not in rendered

    client.detail_payload["server"]["remotes"][0]["url"] = (
        "https://changed.example.com/service"
    )
    try:
        service.resolve_remote_connection(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
        )
    except McpRegistryCatalogError as error:
        assert error.code == "mcp_registry_connection_plan_changed"
    else:
        raise AssertionError("changed Registry material reused an existing plan")


def test_plan_revision_binds_hidden_endpoint_and_declared_execution_values() -> None:
    client = _Client()
    client.detail_payload = _probeable_remote_detail()
    client.versions_payload = {
        "servers": [client.detail_payload],
        "metadata": {"count": 1},
    }
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    original = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )

    client.detail_payload["server"]["remotes"][0]["url"] = (
        "https://mcp.example.com/different-path?synthetic=changed"
    )
    endpoint_changed = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    assert endpoint_changed.plan_revision != original.plan_revision

    client.detail_payload["server"]["remotes"][0]["url"] = (
        "https://mcp.example.com/service?synthetic=hidden"
    )
    client.detail_payload["server"]["remotes"][0]["headers"][0]["value"] = (
        "synthetic-different-fixed-value"
    )
    header_changed = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    assert header_changed.plan_revision != original.plan_revision

    rendered = header_changed.model_dump_json()
    assert "synthetic-different-fixed-value" not in rendered
    assert "execution_material_digest" not in rendered


def test_plan_revision_binds_local_checksum_and_fixed_arguments() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    original = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )

    client.detail_payload["server"]["packages"][0]["fileSha256"] = "b" * 64
    checksum_changed = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    assert checksum_changed.plan_revision != original.plan_revision

    client.detail_payload["server"]["packages"][0]["fileSha256"] = "a" * 64
    client.detail_payload["server"]["packages"][0]["packageArguments"][0][
        "value"
    ] = "synthetic-changed-mode"
    argument_changed = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    assert argument_changed.plan_revision != original.plan_revision
    assert "synthetic-changed-mode" not in argument_changed.model_dump_json()


def test_internal_mcpb_resolution_is_exact_secret_and_release_bounded() -> None:
    client = _Client()
    client.detail_payload = _mcpb_detail()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    option = next(item for item in review.options if item.kind == "local_package")

    resolved = service.resolve_local_package(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        option_id=option.option_id,
        plan_revision=review.plan_revision,
    )

    assert resolved.registry_type == "mcpb"
    assert resolved.file_sha256 == "c" * 64
    assert resolved.transport == "stdio"
    assert "github.com" not in repr(resolved)
    assert "github.com" not in resolved.model_dump_json()

    client.detail_payload["server"]["packages"][0]["fileSha256"] = "d" * 64
    with pytest.raises(McpRegistryCatalogError) as changed:
        service.resolve_local_package(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
        )
    assert changed.value.code == "mcp_registry_package_plan_changed"

    client.detail_payload = _mcpb_detail()
    client.detail_payload["server"]["packages"][0]["identifier"] = (
        "https://example.com/releases/download/v1.2.3/synthetic-files.mcpb"
    )
    invalid_review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    invalid_option = next(
        item for item in invalid_review.options if item.kind == "local_package"
    )
    with pytest.raises(McpRegistryCatalogError) as invalid:
        service.resolve_local_package(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=invalid_option.option_id,
            plan_revision=invalid_review.plan_revision,
        )
    assert invalid.value.code == "mcp_registry_package_url_invalid"


def test_internal_mcpb_launch_configuration_is_exact_vault_only_and_shell_free() -> None:
    client = _Client()
    client.detail_payload = _mcpb_detail()
    package = client.detail_payload["server"]["packages"][0]
    package.update(
        {
            "runtimeHint": "mcpb",
            "runtimeArguments": [
                {"type": "named", "name": "--runtime", "value": "synthetic"}
            ],
            "packageArguments": [
                {
                    "type": "named",
                    "name": "--workspace",
                    "format": "filepath",
                    "isRequired": True,
                },
                {"type": "positional", "value": "fixed-mode"},
                {
                    "type": "named",
                    "name": "--scope",
                    "value": "{tenant}:{mode}",
                    "variables": {
                        "tenant": {"isRequired": True},
                        "mode": {"default": "stable"},
                    },
                },
            ],
            "environmentVariables": [
                {
                    "name": "EXAMPLE_TOKEN",
                    "isRequired": True,
                    "isSecret": True,
                },
                {"name": "EXAMPLE_MODE", "default": "bounded"},
            ],
        }
    )
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    option = next(item for item in review.options if item.kind == "local_package")
    by_name = {item.name: item for item in option.requirements}
    workspace_value = "X:\\example\\synthetic-workspace"
    tenant_value = "synthetic-tenant"
    token_value = "synthetic-vault-token"
    configured = {
        by_name["--workspace"].requirement_id: SecretStr(workspace_value),
        by_name["tenant"].requirement_id: SecretStr(tenant_value),
        by_name["EXAMPLE_TOKEN"].requirement_id: SecretStr(token_value),
    }

    with pytest.raises(McpRegistryCatalogError) as missing:
        service.resolve_local_package(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
        )
    assert missing.value.code == "mcp_registry_package_configuration_required"

    resolved = service.resolve_local_package(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        option_id=option.option_id,
        plan_revision=review.plan_revision,
        configuration_values=configured,
    )

    assert tuple(item.get_secret_value() for item in resolved.runtime_arguments) == (
        "--runtime=synthetic",
    )
    assert tuple(item.get_secret_value() for item in resolved.package_arguments) == (
        f"--workspace={workspace_value}",
        "fixed-mode",
        f"--scope={tenant_value}:stable",
    )
    assert {
        item.name: item.value.get_secret_value() for item in resolved.environment
    } == {
        "EXAMPLE_TOKEN": token_value,
        "EXAMPLE_MODE": "bounded",
    }
    rendered = resolved.model_dump_json()
    represented = repr(resolved)
    for private_value in (workspace_value, tenant_value, token_value):
        assert private_value not in rendered
        assert private_value not in represented

    with pytest.raises(McpRegistryCatalogError) as relative_path:
        service.resolve_local_package(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
            configuration_values={
                **configured,
                by_name["--workspace"].requirement_id: SecretStr("relative/path"),
            },
        )
    assert relative_path.value.code == "mcp_registry_package_configuration_invalid"

    with pytest.raises(McpRegistryCatalogError) as unreviewed:
        service.resolve_local_package(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
            configuration_values={**configured, "f" * 32: SecretStr("extra")},
        )
    assert unreviewed.value.code == "mcp_registry_package_configuration_required"


def test_internal_remote_resolution_requires_vault_values_and_revalidates_templates() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    option = next(item for item in review.options if item.kind == "remote_server")
    with pytest.raises(McpRegistryCatalogError) as missing:
        service.resolve_remote_connection(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
        )
    assert missing.value.code == "mcp_registry_connection_configuration_required"

    variable = next(
        item for item in option.requirements if item.location == "remote_variable"
    )
    configured_value = "https://mcp.example.com"
    resolved = service.resolve_remote_connection(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        option_id=option.option_id,
        plan_revision=review.plan_revision,
        variable_values={
            variable.requirement_id: SecretStr(configured_value),
        },
    )
    assert resolved.endpoint_host == "mcp.example.com"
    assert resolved.endpoint.get_secret_value() == (
        "https://mcp.example.com/mcp?credential=synthetic-hidden-query"
    )
    assert configured_value not in repr(resolved)
    assert configured_value not in resolved.model_dump_json()

    with pytest.raises(McpRegistryCatalogError) as insecure:
        service.resolve_remote_connection(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
            variable_values={
                variable.requirement_id: SecretStr("http://mcp.example.com"),
            },
        )
    assert insecure.value.code == "mcp_registry_connection_configuration_required"
    with pytest.raises(McpRegistryCatalogError) as unreviewed:
        service.resolve_remote_connection(
            catalog_id=server.catalog_id,
            name=server.name,
            version=server.version,
            option_id=option.option_id,
            plan_revision=review.plan_revision,
            variable_values={"f" * 32: SecretStr(configured_value)},
        )
    assert unreviewed.value.code == "mcp_registry_connection_configuration_required"

    client.detail_payload = _probeable_remote_detail()
    client.detail_payload["server"]["remotes"][0]["url"] += "#hidden"
    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    fragmented = next(item for item in review.options if item.kind == "remote_server")
    assert fragmented.endpoint_state == "invalid"
    assert fragmented.compatibility.status == "unsupported"


def test_server_review_fails_closed_on_identity_mismatch_and_marks_history_outage() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]

    try:
        service.review_server(
            catalog_id="0" * 32,
            name=server.name,
            version=server.version,
        )
    except McpRegistryCatalogError as error:
        assert error.code == "mcp_registry_server_identity_invalid"
    else:
        raise AssertionError("mismatched catalog identity reached the registry")
    assert client.detail_calls == []

    client.fail_history = True
    review = service.review_server(
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    assert review.version_history_state == "unavailable"
    assert review.partial is True
    assert len(review.versions) == 1 and review.versions[0].selected is True


def test_server_review_http_surface_is_authenticated_private_and_read_only() -> None:
    client = _Client()
    service = McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)
    server = service.list_servers().servers[0]
    app = FastAPI()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer synthetic-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    app.include_router(create_mcp_registry_router(require_auth, service))
    http = TestClient(app)
    path = f"{MCP_STORE_SERVER_PATH_PREFIX}/{server.catalog_id}/review"
    params = {
        "name": server.name,
        "version": server.version,
        "presentation_revision": server.presentation_revision,
    }

    assert http.get(path, params=params).status_code == 401
    response = http.get(
        path,
        params=params,
        headers={"Authorization": "Bearer synthetic-local-token"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["review_truth"] == "preview_only_no_install_or_connection_authority"
    assert http.post(
        path,
        params=params,
        headers={"Authorization": "Bearer synthetic-local-token"},
    ).status_code == 405


class _HttpResponse:
    def __init__(
        self,
        body: bytes,
        url: str,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.headers.update(extra_headers or {})

    def read(self, maximum: int) -> bytes:
        return self.body[:maximum]

    def geturl(self) -> str:
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Opener:
    def __init__(self, response: _HttpResponse) -> None:
        self.response = response
        self.requests = []

    def open(self, request, timeout):  # noqa: ANN001
        self.requests.append((request, timeout))
        return self.response


class _NotFoundOpener:
    def open(self, request, timeout):  # noqa: ANN001
        from urllib.error import HTTPError

        raise HTTPError(request.full_url, 404, "synthetic not found", {}, None)


class _Resolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    def resolve(self, host: str, port: int) -> tuple[str, ...]:
        self.calls.append((host, port))
        return self.addresses


class _StreamingResponse:
    def __init__(
        self,
        *,
        url: str,
        body: bytes,
        status_code: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self.url = httpx2.URL(url)
        self.status_code = status_code
        self.headers = httpx2.Headers({"Content-Type": content_type})
        self._body = body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    def iter_bytes(self):
        yield self._body


class _StreamingClient:
    created: list["_StreamingClient"] = []
    response: _StreamingResponse

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.__class__.created.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream(self, method: str, url: str, headers: dict[str, str]):
        self.requests.append((method, url, headers))
        return self.response


def test_official_http_client_pins_origin_query_and_bounded_json() -> None:
    import json

    url = "https://registry.modelcontextprotocol.io/v0.1/servers?limit=12&version=latest&search=file+tools&cursor=next%3A1"
    opener = _Opener(_HttpResponse(json.dumps(_page()).encode(), url, "application/json"))
    client = OfficialMcpRegistryHttpClient(opener=opener, timeout_seconds=3)

    result = client.list_servers(search="file tools", cursor="next:1", limit=12)

    assert len(result["servers"]) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == url
    assert request.get_method() == "GET"
    assert timeout == 3
    assert request.get_header("Authorization") is None
    assert request.get_header("Accept-encoding") == "identity"


def test_official_registry_production_path_ignores_proxy_env_and_pins_public_dns(
    monkeypatch,
) -> None:
    import json

    url = (
        "https://registry.modelcontextprotocol.io/v0.1/servers"
        "?limit=1&version=latest"
    )
    _StreamingClient.created = []
    _StreamingClient.response = _StreamingResponse(
        url=url,
        body=json.dumps(_page()).encode("utf-8"),
    )
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.mcp_registry.httpx2.Client",
        _StreamingClient,
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:65530")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:65531")
    resolver = _Resolver("8.8.8.8", "2606:4700:4700::1111")

    result = OfficialMcpRegistryHttpClient(resolver=resolver).list_servers(
        search="",
        cursor=None,
        limit=1,
    )

    assert len(result["servers"]) == 1
    assert resolver.calls == [("registry.modelcontextprotocol.io", 443)]
    assert len(_StreamingClient.created) == 1
    created = _StreamingClient.created[0]
    assert created.kwargs["trust_env"] is False
    assert created.kwargs["follow_redirects"] is False
    transport = created.kwargs["transport"]
    assert isinstance(transport, PinnedMcpSyncTransport)
    assert transport._pool._proxy is None  # type: ignore[attr-defined]
    assert transport._origin.addresses == (  # type: ignore[attr-defined]
        "8.8.8.8",
        "2606:4700:4700::1111",
    )
    assert created.requests[0][0:2] == ("GET", url)
    assert created.requests[0][2]["Accept-encoding"] == "identity"


def test_official_registry_refuses_private_or_multicast_dns_before_http(
    monkeypatch,
) -> None:
    def forbidden_client(**_kwargs):
        raise AssertionError("HTTP client must not be constructed")

    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.mcp_registry.httpx2.Client",
        forbidden_client,
    )
    for address in ("127.0.0.1", "10.0.0.1", "224.0.0.1", "ff02::1"):
        resolver = _Resolver(address)
        client = OfficialMcpRegistryHttpClient(resolver=resolver)
        with pytest.raises(McpRegistryTransportError) as caught:
            client.list_servers(search="", cursor=None, limit=1)
        assert caught.value.code == "registry_unavailable"
        assert str(caught.value) == "registry_unavailable"
        assert resolver.calls == [("registry.modelcontextprotocol.io", 443)]


def test_official_registry_total_deadline_closes_a_late_stream_content_free(
    monkeypatch,
) -> None:
    class Clock:
        def __init__(self) -> None:
            self.values = iter((0.0, 0.0, 0.0, 13.0))

        def __call__(self) -> float:
            return next(self.values)

    url = (
        "https://registry.modelcontextprotocol.io/v0.1/servers"
        "?limit=1&version=latest"
    )
    response = _StreamingResponse(
        url=url,
        body=b'{"private":"synthetic-late-body"}',
    )
    _StreamingClient.created = []
    _StreamingClient.response = response
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.mcp_registry.httpx2.Client",
        _StreamingClient,
    )
    client = OfficialMcpRegistryHttpClient(
        resolver=_Resolver("8.8.8.8"),
        timeout_seconds=12.0,
        clock=Clock(),
    )

    with pytest.raises(McpRegistryTransportError) as caught:
        client.list_servers(search="", cursor=None, limit=1)

    assert caught.value.code == "registry_unavailable"
    assert "synthetic-late-body" not in str(caught.value)
    assert response.closed is True


def test_official_http_client_pins_encoded_detail_and_version_history_paths() -> None:
    import json

    detail_url = (
        "https://registry.modelcontextprotocol.io/v0.1/servers/"
        "com.example%2Fsynthetic-files/versions/1.2.3%2Bbuild"
    )
    detail_opener = _Opener(
        _HttpResponse(json.dumps(_detail_page()).encode(), detail_url, "application/json")
    )
    detail_client = OfficialMcpRegistryHttpClient(opener=detail_opener)
    assert detail_client.get_server_version(
        name="com.example/synthetic-files",
        version="1.2.3+build",
    )["server"]["name"] == "com.example/synthetic-files"
    request, _timeout = detail_opener.requests[0]
    assert request.full_url == detail_url
    assert request.get_header("Authorization") is None

    versions_url = (
        "https://registry.modelcontextprotocol.io/v0.1/servers/"
        "com.example%2Fsynthetic-files/versions"
    )
    versions_opener = _Opener(
        _HttpResponse(json.dumps(_versions_page()).encode(), versions_url, "application/json")
    )
    versions_client = OfficialMcpRegistryHttpClient(opener=versions_opener)
    assert len(
        versions_client.list_server_versions(name="com.example/synthetic-files")[
            "servers"
        ]
    ) == 2
    request, _timeout = versions_opener.requests[0]
    assert request.full_url == versions_url


def test_official_http_client_maps_detail_404_without_response_content() -> None:
    client = OfficialMcpRegistryHttpClient(opener=_NotFoundOpener())
    try:
        client.get_server_version(
            name="com.example/synthetic-files",
            version="1.2.3",
        )
    except McpRegistryTransportError as error:
        assert error.code == "registry_server_not_found"
        assert str(error) == "registry_server_not_found"
    else:
        raise AssertionError("registry 404 was not mapped to a bounded failure")


def test_official_http_client_rejects_redirects_types_and_oversize() -> None:
    cases = (
        _HttpResponse(b"{}", "https://example.com/v0.1/servers", "application/json"),
        _HttpResponse(b"{}", "https://registry.modelcontextprotocol.io/v0.1/servers?limit=1", "text/html"),
        _HttpResponse(
            b"x" * (MAX_REGISTRY_RESPONSE_BYTES + 1),
            "https://registry.modelcontextprotocol.io/v0.1/servers?limit=1",
            "application/json",
        ),
        _HttpResponse(
            b"{}",
            "https://registry.modelcontextprotocol.io/v0.1/servers?limit=1",
            "application/json",
            extra_headers={
                "X-Synthetic": "x" * (MAX_MCP_HTTP_HEADER_VALUE_BYTES + 1)
            },
        ),
        _HttpResponse(
            b"compressed",
            "https://registry.modelcontextprotocol.io/v0.1/servers?limit=1",
            "application/json",
            extra_headers={"Content-Encoding": "gzip"},
        ),
    )
    for response in cases:
        client = OfficialMcpRegistryHttpClient(opener=_Opener(response))
        try:
            client.list_servers(search="", cursor=None, limit=1)
        except McpRegistryTransportError:
            pass
        else:
            raise AssertionError("unsafe registry response was accepted")


def test_icon_transport_rechecks_host_type_and_size() -> None:
    source = "https://raw.githubusercontent.com/example/synthetic/main/icon.png"
    opener = _Opener(_HttpResponse(b"png", source, "image/png"))
    client = OfficialMcpRegistryHttpClient(opener=opener)
    assert client.fetch_icon(source) == McpRegistryIconContent(
        media_type="image/png", body=b"png"
    )

    for invalid in (
        "https://127.0.0.1/icon.png",
        "http://raw.githubusercontent.com/example/icon.png",
        "https://example.com/icon.png",
    ):
        try:
            client.fetch_icon(invalid)
        except McpRegistryTransportError:
            pass
        else:
            raise AssertionError("untrusted icon source was fetched")

    oversized = _Opener(_HttpResponse(b"x" * (MAX_REGISTRY_ICON_BYTES + 1), source, "image/png"))
    try:
        OfficialMcpRegistryHttpClient(opener=oversized).fetch_icon(source)
    except McpRegistryTransportError:
        pass
    else:
        raise AssertionError("oversized icon was accepted")
