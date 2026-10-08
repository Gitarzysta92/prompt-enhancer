"""No-proxy, no-redirect adapters for the official public MCP Registry."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import OpenerDirector, Request

import httpx2

from ..application.mcp_registry_catalog import (
    MCP_REGISTRY_BASE_URL,
    MCP_REGISTRY_MAX_CURSOR_CHARS,
    MCP_REGISTRY_MAX_ICON_BYTES,
    MCP_REGISTRY_MAX_LIMIT,
    MCP_REGISTRY_MAX_SEARCH_CHARS,
    McpRegistryCacheRecord,
    McpRegistryClientError,
    McpRegistryIconContent,
)
from ..application.mcp_guarded_host import McpGuardedHostError
from .mcp_guarded_host import (
    MCP_CONNECT_TIMEOUT_SECONDS,
    McpDnsResolver,
    PinnedMcpSyncTransport,
    SystemMcpDnsResolver,
    _validate_http_response,
    resolve_public_https_origin,
)


MAX_REGISTRY_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REGISTRY_CACHE_BYTES = 4 * 1024 * 1024
MAX_REGISTRY_CACHE_ENTRIES = 32
MAX_REGISTRY_ICON_BYTES = MCP_REGISTRY_MAX_ICON_BYTES
REGISTRY_TIMEOUT_SECONDS = 12.0
_CACHE_FORMAT_VERSION = 2
_ICON_CONTENT_TYPES = {
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/webp": "image/webp",
}


class McpRegistryTransportError(McpRegistryClientError):
    """A bounded, content-free official-registry transport failure."""


class OfficialMcpRegistryHttpClient:
    """Fetch only the pinned official registry origin and pre-approved icons."""

    __slots__ = ("_clock", "_opener", "_resolver", "_timeout")

    def __init__(
        self,
        *,
        opener: OpenerDirector | None = None,
        resolver: McpDnsResolver | None = None,
        timeout_seconds: float = REGISTRY_TIMEOUT_SECONDS,
        clock: Any | None = None,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 30:
            raise ValueError("invalid registry timeout")
        self._opener = opener
        self._resolver = resolver or SystemMcpDnsResolver()
        self._timeout = timeout_seconds
        self._clock = clock or time.monotonic

    @staticmethod
    def _read_bounded(response, maximum: int) -> bytes:  # noqa: ANN001
        body = response.read(maximum + 1)
        if len(body) > maximum:
            raise McpRegistryTransportError("registry_response_too_large")
        return body

    @staticmethod
    def _header_items(headers: Any) -> tuple[tuple[bytes, bytes], ...]:
        if hasattr(headers, "raw"):
            return tuple((bytes(name), bytes(value)) for name, value in headers.raw)
        try:
            return tuple(
                (str(name).encode("ascii"), str(value).encode("utf-8"))
                for name, value in headers.items()
            )
        except (AttributeError, TypeError, UnicodeError):
            raise McpRegistryTransportError("registry_response_invalid") from None

    def _open_bounded(
        self,
        request: Request,
        *,
        expected_host: str,
        maximum: int,
    ) -> tuple[int, str, Any, bytes]:
        """Open one GET with either a synthetic seam or the pinned production path."""

        if self._opener is not None:
            with self._opener.open(request, timeout=self._timeout) as response:
                status = int(getattr(response, "status", 200))
                try:
                    _validate_http_response(
                        self._header_items(response.headers),
                        status_code=status,
                        maximum_body_bytes=maximum,
                    )
                except McpGuardedHostError as error:
                    if error.code == "mcp_host_redirect_refused":
                        raise McpRegistryTransportError(
                            "registry_redirect_refused"
                        ) from None
                    if error.code == "mcp_host_response_too_large":
                        raise McpRegistryTransportError(
                            "registry_response_too_large"
                        ) from None
                    raise McpRegistryTransportError(
                        "registry_response_invalid"
                    ) from None
                return (
                    status,
                    response.geturl(),
                    response.headers,
                    self._read_bounded(response, maximum),
                )

        deadline = self._clock() + self._timeout
        try:
            origin = resolve_public_https_origin(
                request.full_url,
                expected_host,
                self._resolver,
            )
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise McpRegistryTransportError("registry_unavailable")
            timeout = httpx2.Timeout(
                remaining,
                connect=min(MCP_CONNECT_TIMEOUT_SECONDS, remaining),
                read=min(self._timeout, remaining),
                write=min(self._timeout, remaining),
                pool=min(MCP_CONNECT_TIMEOUT_SECONDS, remaining),
            )
            transport = PinnedMcpSyncTransport(
                origin,
                maximum_response_bytes=maximum,
            )
            with httpx2.Client(
                transport=transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "GET",
                    request.full_url,
                    headers=dict(request.header_items()),
                ) as response:
                    if self._clock() > deadline:
                        raise McpRegistryTransportError("registry_unavailable")
                    body_parts: list[bytes] = []
                    received = 0
                    if response.status_code < 400:
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > maximum:
                                raise McpRegistryTransportError(
                                    "registry_response_too_large"
                                )
                            if self._clock() > deadline:
                                raise McpRegistryTransportError("registry_unavailable")
                            body_parts.append(chunk)
                    return (
                        response.status_code,
                        str(response.url),
                        response.headers,
                        b"".join(body_parts),
                    )
        except McpRegistryTransportError:
            raise
        except McpGuardedHostError as error:
            if error.code == "mcp_host_redirect_refused":
                raise McpRegistryTransportError("registry_redirect_refused") from None
            if error.code == "mcp_host_response_too_large":
                raise McpRegistryTransportError("registry_response_too_large") from None
            if error.code in {
                "mcp_host_content_encoding_unsupported",
                "mcp_host_headers_invalid",
                "mcp_host_headers_too_large",
            }:
                raise McpRegistryTransportError("registry_response_invalid") from None
            raise McpRegistryTransportError("registry_unavailable") from None
        except (httpx2.HTTPError, TimeoutError, socket.timeout, OSError):
            raise McpRegistryTransportError("registry_unavailable") from None

    def _get_json(
        self,
        url: str,
        *,
        not_found_code: str | None = None,
    ) -> Mapping[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "prompt-enhancer-mcp-store/1",
            },
            method="GET",
        )
        try:
            status, final_url, headers, body = self._open_bounded(
                request,
                expected_host="registry.modelcontextprotocol.io",
                maximum=MAX_REGISTRY_RESPONSE_BYTES,
            )
            if status == 404 and not_found_code is not None:
                raise McpRegistryTransportError(not_found_code)
            if status >= 400:
                raise McpRegistryTransportError("registry_unavailable")
            if final_url != url:
                raise McpRegistryTransportError("registry_redirect_refused")
            final = urlsplit(final_url)
            if (
                final.scheme != "https"
                or final.hostname != "registry.modelcontextprotocol.io"
                or final.port not in (None, 443)
                or final.username is not None
                or final.password is not None
                or final.fragment
            ):
                raise McpRegistryTransportError("registry_redirect_refused")
            content_type = (headers.get("Content-Type") or "").casefold()
            if not content_type.startswith("application/json"):
                raise McpRegistryTransportError("registry_content_type_invalid")
        except McpRegistryTransportError:
            raise
        except HTTPError as error:
            if error.code == 404 and not_found_code is not None:
                raise McpRegistryTransportError(not_found_code) from None
            raise McpRegistryTransportError("registry_unavailable") from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise McpRegistryTransportError("registry_unavailable") from None
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise McpRegistryTransportError("registry_response_invalid") from None
        if not isinstance(payload, Mapping):
            raise McpRegistryTransportError("registry_response_invalid")
        return payload

    def list_servers(
        self,
        *,
        search: str,
        cursor: str | None,
        limit: int,
    ) -> Mapping[str, Any]:
        if (
            len(search) > MCP_REGISTRY_MAX_SEARCH_CHARS
            or (cursor is not None and len(cursor) > MCP_REGISTRY_MAX_CURSOR_CHARS)
            or not 1 <= limit <= MCP_REGISTRY_MAX_LIMIT
        ):
            raise McpRegistryTransportError("registry_request_invalid")
        query: list[tuple[str, str]] = [("limit", str(limit)), ("version", "latest")]
        if search:
            query.append(("search", search))
        if cursor is not None:
            query.append(("cursor", cursor))
        url = f"{MCP_REGISTRY_BASE_URL}/v0.1/servers?{urlencode(query)}"
        return self._get_json(url)

    @staticmethod
    def _encoded_identity(*, name: str, version: str | None = None) -> tuple[str, ...]:
        values = (name,) if version is None else (name, version)
        if any(
            not value
            or len(value) > (241 if index == 0 else 255)
            or value != value.strip()
            or any(character in value for character in ("\x00", "\r", "\n"))
            for index, value in enumerate(values)
        ):
            raise McpRegistryTransportError("registry_request_invalid")
        return tuple(quote(value, safe="") for value in values)

    def get_server_version(self, *, name: str, version: str) -> Mapping[str, Any]:
        encoded_name, encoded_version = self._encoded_identity(
            name=name,
            version=version,
        )
        url = (
            f"{MCP_REGISTRY_BASE_URL}/v0.1/servers/{encoded_name}/versions/"
            f"{encoded_version}"
        )
        return self._get_json(url, not_found_code="registry_server_not_found")

    def list_server_versions(self, *, name: str) -> Mapping[str, Any]:
        (encoded_name,) = self._encoded_identity(name=name)
        url = f"{MCP_REGISTRY_BASE_URL}/v0.1/servers/{encoded_name}/versions"
        return self._get_json(url, not_found_code="registry_server_not_found")

    def fetch_icon(self, source: str) -> McpRegistryIconContent:
        # The application layer supplied this URL only after exact HTTPS host
        # allow-listing. Recheck the shape here before any network request.
        try:
            parsed = urlsplit(source)
        except ValueError:
            raise McpRegistryTransportError("registry_icon_invalid") from None
        allowed = parsed.hostname in {
            "static.modelcontextprotocol.io",
            "modelcontextprotocol.io",
            "avatars.githubusercontent.com",
            "raw.githubusercontent.com",
            "user-images.githubusercontent.com",
            "cdn.jsdelivr.net",
        } or bool(parsed.hostname and parsed.hostname.endswith(".githubusercontent.com"))
        if (
            parsed.scheme != "https"
            or not allowed
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
        ):
            raise McpRegistryTransportError("registry_icon_invalid")
        request = Request(
            source,
            headers={
                "Accept": "image/png,image/jpeg,image/webp",
                "Accept-Encoding": "identity",
                "User-Agent": "prompt-enhancer-mcp-store/1",
            },
            method="GET",
        )
        try:
            status, final_url, headers, body = self._open_bounded(
                request,
                expected_host=parsed.hostname or "",
                maximum=MAX_REGISTRY_ICON_BYTES,
            )
            if status >= 400:
                raise McpRegistryTransportError("registry_icon_unavailable")
            if final_url != source:
                raise McpRegistryTransportError("registry_icon_redirect_refused")
            content_type = (headers.get("Content-Type") or "").casefold()
            media_type = content_type.split(";", 1)[0].strip()
            normalized = _ICON_CONTENT_TYPES.get(media_type)
            if normalized is None:
                raise McpRegistryTransportError("registry_icon_content_type_invalid")
        except McpRegistryTransportError:
            raise
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError):
            raise McpRegistryTransportError("registry_icon_unavailable") from None
        if not body:
            raise McpRegistryTransportError("registry_icon_empty")
        return McpRegistryIconContent(media_type=normalized, body=body)  # type: ignore[arg-type]


class JsonMcpRegistryCache:
    """Small restart-safe cache containing normalized public metadata only."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()

    def _load(self) -> dict[str, McpRegistryCacheRecord]:
        try:
            if not self._path.is_file() or self._path.is_symlink():
                return {}
            size = self._path.stat().st_size
            if size <= 0 or size > MAX_REGISTRY_CACHE_BYTES:
                return {}
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format_version") != _CACHE_FORMAT_VERSION:
                return {}
            entries = payload.get("entries")
            if not isinstance(entries, dict) or len(entries) > MAX_REGISTRY_CACHE_ENTRIES:
                return {}
            parsed: dict[str, McpRegistryCacheRecord] = {}
            for key, value in entries.items():
                if not isinstance(key, str) or not len(key) == 64:
                    continue
                try:
                    int(key, 16)
                    parsed[key] = McpRegistryCacheRecord.model_validate(value)
                except (TypeError, ValueError):
                    continue
            return parsed
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def get(self, key: str) -> McpRegistryCacheRecord | None:
        if len(key) != 64:
            return None
        with self._lock:
            return self._load().get(key)

    def put(self, key: str, record: McpRegistryCacheRecord) -> None:
        if len(key) != 64:
            raise ValueError("invalid registry cache key")
        int(key, 16)
        with self._lock:
            entries = self._load()
            entries[key] = record
            ordered = sorted(
                entries.items(),
                key=lambda item: item[1].fetched_at,
                reverse=True,
            )[:MAX_REGISTRY_CACHE_ENTRIES]
            payload = {
                "format_version": _CACHE_FORMAT_VERSION,
                "entries": {
                    item_key: item.model_dump(mode="json") for item_key, item in ordered
                },
            }
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            while len(encoded) > MAX_REGISTRY_CACHE_BYTES and len(ordered) > 1:
                ordered.pop()
                payload["entries"] = {
                    item_key: item.model_dump(mode="json") for item_key, item in ordered
                }
                encoded = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            if len(encoded) > MAX_REGISTRY_CACHE_BYTES:
                raise OSError("registry cache entry too large")

            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self._path.parent,
                    prefix=".mcp-registry-",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary.write(encoded)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                temporary_path.chmod(0o600)
                os.replace(temporary_path, self._path)
                self._path.chmod(0o600)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    try:
                        temporary_path.unlink()
                    except OSError:
                        pass


__all__ = (
    "JsonMcpRegistryCache",
    "McpRegistryTransportError",
    "OfficialMcpRegistryHttpClient",
)
