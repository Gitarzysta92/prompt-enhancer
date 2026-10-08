"""Official-SDK MCP probe adapters with pinned egress and bounded I/O.

Remote probes never honor proxies or redirects.  DNS is resolved once, every
answer must be globally routable, and the connection backend is pinned to
those reviewed addresses while TLS still authenticates the original host.
Stdio uses the SDK's no-window process transport and a minimal environment;
the Store does not make that path reachable until an exact install exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import ipaddress
import logging
from pathlib import Path
import re
import socket
import ssl
import sys
import time
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import anyio
import httpcore2
import httpx2
from httpcore2._backends.auto import AutoBackend
from httpcore2._backends.sync import SyncBackend
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from ..application.local_command_process import minimal_environment
from ..application.mcp_guarded_host import (
    MAX_MCP_PROBE_TOOLS,
    MAX_MCP_TOOL_PAGES,
    McpDiscoveredTool,
    McpGuardedHostError,
    McpHostProbeObservation,
    McpRemoteConnectionSpec,
    McpStdioConnectionSpec,
)
from .mcp_stdio_transport import McpStdioCleanupEvidence, owned_stdio_client


MAX_MCP_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_MCP_DNS_ADDRESSES = 16
MAX_MCP_HTTP_HEADERS = 128
MAX_MCP_HTTP_HEADER_NAME_BYTES = 256
MAX_MCP_HTTP_HEADER_VALUE_BYTES = 8 * 1024
MAX_MCP_HTTP_HEADER_BYTES = 64 * 1024
MAX_MCP_HTTP_RESPONSES = 2_048
MAX_MCP_SSE_EVENTS_PER_RESPONSE = 2_048
MAX_MCP_STDIO_ARGUMENTS = 128
MAX_MCP_STDIO_ARGUMENT_CHARS = 4_096
MCP_CONNECT_TIMEOUT_SECONDS = 5.0
MCP_READ_TIMEOUT_SECONDS = 8.0

_ID = re.compile(r"^[0-9a-f]{32}$")


# The upstream SDK's debug/error paths can include raw JSON-RPC messages or
# endpoint paths.  Prompt Enhancer converts all failures to content-free codes,
# so library transport logging is intentionally disabled for this boundary.
for _logger_name in (
    "mcp.client",
    "mcp.shared",
    "httpx2",
    "httpcore2",
):
    logging.getLogger(_logger_name).setLevel(logging.CRITICAL + 1)


class McpDnsResolver(Protocol):
    def resolve(self, host: str, port: int) -> tuple[str, ...]: ...


class SystemMcpDnsResolver:
    """Resolve only the requested endpoint; never enumerate host networking."""

    def resolve(self, host: str, port: int) -> tuple[str, ...]:
        try:
            rows = socket.getaddrinfo(
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except (OSError, UnicodeError):
            raise McpGuardedHostError("mcp_host_endpoint_unresolvable") from None
        addresses = tuple(dict.fromkeys(str(row[4][0]) for row in rows))
        if not addresses or len(addresses) > MAX_MCP_DNS_ADDRESSES:
            raise McpGuardedHostError("mcp_host_endpoint_unresolvable")
        return addresses


@dataclass(frozen=True, slots=True)
class PinnedMcpOrigin:
    host: str
    port: int
    addresses: tuple[str, ...]


def _global_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise McpGuardedHostError("mcp_host_endpoint_address_invalid") from None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        not address.is_global
        or address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or (
            isinstance(address, ipaddress.IPv6Address)
            and address.is_site_local
        )
    ):
        raise McpGuardedHostError("mcp_host_endpoint_not_public")
    return str(address)


def _strict_tls_context() -> ssl.SSLContext:
    """Return the sole TLS policy accepted by guarded MCP HTTP transports."""

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _validate_http_headers(headers: Iterable[tuple[bytes, bytes]]) -> None:
    """Reject response/request header amplification with a content-free code."""

    count = 0
    total = 0
    for raw_name, raw_value in headers:
        count += 1
        name = bytes(raw_name)
        value = bytes(raw_value)
        if (
            count > MAX_MCP_HTTP_HEADERS
            or not name
            or len(name) > MAX_MCP_HTTP_HEADER_NAME_BYTES
            or len(value) > MAX_MCP_HTTP_HEADER_VALUE_BYTES
        ):
            raise McpGuardedHostError("mcp_host_headers_too_large")
        total += len(name) + len(value) + 4
        if total > MAX_MCP_HTTP_HEADER_BYTES:
            raise McpGuardedHostError("mcp_host_headers_too_large")


def _validate_http_response(
    headers: Iterable[tuple[bytes, bytes]],
    *,
    status_code: int,
    maximum_body_bytes: int,
) -> None:
    raw = tuple(headers)
    _validate_http_headers(raw)
    if 300 <= status_code < 400:
        raise McpGuardedHostError("mcp_host_redirect_refused")
    content_encodings = [
        value.strip().lower()
        for name, value in raw
        if name.lower() == b"content-encoding"
    ]
    if content_encodings and content_encodings != [b"identity"]:
        raise McpGuardedHostError("mcp_host_content_encoding_unsupported")
    content_lengths = [
        value.strip()
        for name, value in raw
        if name.lower() == b"content-length"
    ]
    if len(content_lengths) > 1:
        raise McpGuardedHostError("mcp_host_headers_invalid")
    if content_lengths:
        try:
            declared = int(content_lengths[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            raise McpGuardedHostError("mcp_host_headers_invalid") from None
        if declared < 0:
            raise McpGuardedHostError("mcp_host_headers_invalid")
        if declared > maximum_body_bytes:
            raise McpGuardedHostError("mcp_host_response_too_large")


def resolve_public_https_origin(
    endpoint: str,
    endpoint_host: str,
    resolver: McpDnsResolver,
) -> PinnedMcpOrigin:
    """Validate the exact reviewed HTTPS origin and pin public DNS answers."""

    try:
        parsed = urlsplit(endpoint)
        raw_host = parsed.hostname
        port = parsed.port or 443
    except ValueError:
        raise McpGuardedHostError("mcp_host_endpoint_invalid") from None
    if (
        parsed.scheme != "https"
        or not raw_host
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
        or raw_host.endswith(".")
        or "%" in raw_host
    ):
        raise McpGuardedHostError("mcp_host_endpoint_invalid")
    literal_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    try:
        literal_address = ipaddress.ip_address(raw_host)
    except ValueError:
        literal_address = None
        try:
            host = raw_host.encode("idna").decode("ascii").casefold()
        except UnicodeError:
            raise McpGuardedHostError("mcp_host_endpoint_invalid") from None
        reviewed_name = host
    else:
        host = str(literal_address)
        reviewed_name = (
            f"[{host}]"
            if isinstance(literal_address, ipaddress.IPv6Address)
            else host
        )
    reviewed_host = reviewed_name if port == 443 else f"{reviewed_name}:{port}"
    if reviewed_host != endpoint_host.casefold():
        raise McpGuardedHostError("mcp_host_endpoint_identity_changed")
    if literal_address is None:
        raw_addresses = resolver.resolve(host, port)
    else:
        raw_addresses = (str(literal_address),)
    addresses = tuple(dict.fromkeys(_global_address(value) for value in raw_addresses))
    if not addresses or len(addresses) > MAX_MCP_DNS_ADDRESSES:
        raise McpGuardedHostError("mcp_host_endpoint_unresolvable")
    return PinnedMcpOrigin(host=host, port=port, addresses=addresses)


def resolve_public_mcp_origin(
    connection: McpRemoteConnectionSpec,
    resolver: McpDnsResolver,
) -> PinnedMcpOrigin:
    return resolve_public_https_origin(
        connection.endpoint.get_secret_value(),
        connection.endpoint_host,
        resolver,
    )


class _PinnedNetworkStream(httpcore2.AsyncNetworkStream):
    """Preserve reviewed SNI/hostname verification after connecting by IP."""

    def __init__(
        self,
        stream: httpcore2.AsyncNetworkStream,
        origin: PinnedMcpOrigin,
    ) -> None:
        self._stream = stream
        self._origin = origin

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._stream.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._stream.write(buffer, timeout)

    async def aclose(self) -> None:
        await self._stream.aclose()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        minimum = getattr(ssl_context, "minimum_version", ssl.TLSVersion.MINIMUM_SUPPORTED)
        if (
            server_hostname is None
            or server_hostname.casefold() != self._origin.host
            or ssl_context.verify_mode != ssl.CERT_REQUIRED
            or not ssl_context.check_hostname
            or minimum < ssl.TLSVersion.TLSv1_2
        ):
            await self._stream.aclose()
            raise McpGuardedHostError("mcp_host_tls_policy_invalid")
        secured = await self._stream.start_tls(
            ssl_context,
            server_hostname,
            timeout,
        )
        return _PinnedNetworkStream(secured, self._origin)

    def get_extra_info(self, info: str) -> Any:
        return self._stream.get_extra_info(info)


class _PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    def __init__(
        self,
        origin: PinnedMcpOrigin,
        backend: httpcore2.AsyncNetworkBackend | None = None,
    ) -> None:
        self._origin = origin
        self._backend = backend or AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        if host.casefold() != self._origin.host or port != self._origin.port:
            raise McpGuardedHostError("mcp_host_egress_origin_changed")
        for address in self._origin.addresses:
            try:
                stream = await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
                return _PinnedNetworkStream(stream, self._origin)
            except Exception:  # pragma: no cover - address fallback is platform-specific
                continue
        raise McpGuardedHostError("mcp_host_endpoint_unreachable") from None

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        del path, timeout, socket_options
        raise McpGuardedHostError("mcp_host_egress_origin_changed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedSyncNetworkStream(httpcore2.NetworkStream):
    def __init__(self, stream: httpcore2.NetworkStream, origin: PinnedMcpOrigin) -> None:
        self._stream = stream
        self._origin = origin

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._stream.read(max_bytes, timeout)

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._stream.write(buffer, timeout)

    def close(self) -> None:
        self._stream.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.NetworkStream:
        minimum = getattr(ssl_context, "minimum_version", ssl.TLSVersion.MINIMUM_SUPPORTED)
        if (
            server_hostname is None
            or server_hostname.casefold() != self._origin.host
            or ssl_context.verify_mode != ssl.CERT_REQUIRED
            or not ssl_context.check_hostname
            or minimum < ssl.TLSVersion.TLSv1_2
        ):
            self._stream.close()
            raise McpGuardedHostError("mcp_host_tls_policy_invalid")
        secured = self._stream.start_tls(ssl_context, server_hostname, timeout)
        return _PinnedSyncNetworkStream(secured, self._origin)

    def get_extra_info(self, info: str) -> Any:
        return self._stream.get_extra_info(info)


class _PinnedSyncNetworkBackend(httpcore2.NetworkBackend):
    def __init__(
        self,
        origin: PinnedMcpOrigin,
        backend: httpcore2.NetworkBackend | None = None,
    ) -> None:
        self._origin = origin
        self._backend = backend or SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.NetworkStream:
        if host.casefold() != self._origin.host or port != self._origin.port:
            raise McpGuardedHostError("mcp_host_egress_origin_changed")
        for address in self._origin.addresses:
            try:
                stream = self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
                return _PinnedSyncNetworkStream(stream, self._origin)
            except Exception:  # pragma: no cover - address fallback is platform-specific
                continue
        raise McpGuardedHostError("mcp_host_endpoint_unreachable") from None

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.NetworkStream:
        del path, timeout, socket_options
        raise McpGuardedHostError("mcp_host_egress_origin_changed")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class _BoundedResponseStream(httpx2.AsyncByteStream):
    def __init__(
        self,
        stream: httpx2.AsyncByteStream,
        maximum: int,
        *,
        maximum_events: int | None = None,
    ) -> None:
        self._stream = stream
        self._maximum = maximum
        self._maximum_events = maximum_events
        self._received = 0
        self._events = 0
        self._previous_cr = False
        self._last_was_newline = False

    def _newline(self) -> None:
        if self._last_was_newline:
            self._events += 1
            if self._maximum_events is not None and self._events > self._maximum_events:
                raise McpGuardedHostError("mcp_host_sse_event_count_exceeded")
        self._last_was_newline = True

    def _track_events(self, chunk: bytes) -> None:
        if self._maximum_events is None:
            return
        for byte in chunk:
            if self._previous_cr:
                self._previous_cr = False
                self._newline()
                if byte == 10:
                    continue
            if byte == 13:
                self._previous_cr = True
            elif byte == 10:
                self._newline()
            else:
                self._last_was_newline = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            self._received += len(chunk)
            if self._received > self._maximum:
                await self._stream.aclose()
                raise McpGuardedHostError("mcp_host_response_too_large")
            try:
                self._track_events(chunk)
            except McpGuardedHostError:
                await self._stream.aclose()
                raise
            yield chunk
        if self._previous_cr:
            try:
                self._newline()
            except McpGuardedHostError:
                await self._stream.aclose()
                raise

    async def aclose(self) -> None:
        await self._stream.aclose()


class _BoundedSyncResponseStream(httpx2.SyncByteStream):
    def __init__(self, stream: httpx2.SyncByteStream, maximum: int) -> None:
        self._stream = stream
        self._maximum = maximum
        self._received = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._stream:
            self._received += len(chunk)
            if self._received > self._maximum:
                self._stream.close()
                raise McpGuardedHostError("mcp_host_response_too_large")
            yield chunk

    def close(self) -> None:
        self._stream.close()


class _PinnedOriginTransport(httpx2.AsyncHTTPTransport):
    """HTTP transport that cannot connect outside one DNS-pinned origin."""

    def __init__(
        self,
        origin: PinnedMcpOrigin,
        *,
        maximum_response_bytes: int = MAX_MCP_RESPONSE_BYTES,
        maximum_responses: int = MAX_MCP_HTTP_RESPONSES,
    ) -> None:
        if maximum_response_bytes < 1 or maximum_responses < 1:
            raise ValueError("invalid guarded MCP HTTP transport limits")
        tls_context = _strict_tls_context()
        super().__init__(
            verify=tls_context,
            trust_env=False,
            http1=True,
            http2=False,
            limits=httpx2.Limits(max_connections=2, max_keepalive_connections=2),
            retries=0,
        )
        # httpx2/httpcore2 are locked with the MCP SDK.  Replacing the pool is
        # deliberate: it preserves TLS SNI/hostname validation while the TCP
        # backend connects only to the prevalidated addresses above.
        self._pool = httpcore2.AsyncConnectionPool(  # type: ignore[attr-defined]
            ssl_context=tls_context,
            max_connections=2,
            max_keepalive_connections=2,
            keepalive_expiry=2.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedNetworkBackend(origin),
        )
        self._origin = origin
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_responses = maximum_responses
        self._response_count = 0

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        request_host = request.url.host.casefold()
        request_port = request.url.port or 443
        if (
            request.url.scheme != "https"
            or request_host != self._origin.host
            or request_port != self._origin.port
            or bool(request.url.username)
            or bool(request.url.password)
            or bool(request.url.fragment)
        ):
            raise McpGuardedHostError("mcp_host_egress_origin_changed")
        _validate_http_headers(request.headers.raw)
        if self._response_count >= self._maximum_responses:
            await self.aclose()
            raise McpGuardedHostError("mcp_host_response_count_exceeded")
        self._response_count += 1
        response = await super().handle_async_request(request)
        try:
            _validate_http_response(
                response.headers.raw,
                status_code=response.status_code,
                maximum_body_bytes=self._maximum_response_bytes,
            )
        except McpGuardedHostError:
            await response.aclose()
            raise
        content_type = response.headers.get("content-type", "").casefold()
        return httpx2.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_BoundedResponseStream(
                response.stream,
                self._maximum_response_bytes,
                maximum_events=(
                    MAX_MCP_SSE_EVENTS_PER_RESPONSE
                    if content_type.startswith("text/event-stream")
                    else None
                ),
            ),
            extensions=response.extensions,
        )


class PinnedMcpSyncTransport(httpx2.HTTPTransport):
    """No-proxy synchronous sibling used by official Registry reads."""

    def __init__(
        self,
        origin: PinnedMcpOrigin,
        *,
        maximum_response_bytes: int = MAX_MCP_RESPONSE_BYTES,
        maximum_responses: int = 1,
    ) -> None:
        if maximum_response_bytes < 1 or maximum_responses < 1:
            raise ValueError("invalid guarded MCP HTTP transport limits")
        tls_context = _strict_tls_context()
        super().__init__(
            verify=tls_context,
            trust_env=False,
            http1=True,
            http2=False,
            limits=httpx2.Limits(max_connections=1, max_keepalive_connections=0),
            retries=0,
        )
        self._pool = httpcore2.ConnectionPool(  # type: ignore[attr-defined]
            ssl_context=tls_context,
            max_connections=1,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedSyncNetworkBackend(origin),
        )
        self._origin = origin
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_responses = maximum_responses
        self._response_count = 0

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        request_host = request.url.host.casefold()
        request_port = request.url.port or 443
        if (
            request.url.scheme != "https"
            or request_host != self._origin.host
            or request_port != self._origin.port
            or bool(request.url.username)
            or bool(request.url.password)
            or bool(request.url.fragment)
        ):
            raise McpGuardedHostError("mcp_host_egress_origin_changed")
        _validate_http_headers(request.headers.raw)
        if self._response_count >= self._maximum_responses:
            self.close()
            raise McpGuardedHostError("mcp_host_response_count_exceeded")
        self._response_count += 1
        response = super().handle_request(request)
        try:
            _validate_http_response(
                response.headers.raw,
                status_code=response.status_code,
                maximum_body_bytes=self._maximum_response_bytes,
            )
        except McpGuardedHostError:
            response.close()
            raise
        return httpx2.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_BoundedSyncResponseStream(
                response.stream,
                self._maximum_response_bytes,
            ),
            extensions=response.extensions,
        )


ProbeTargetFactory = Callable[
    [McpRemoteConnectionSpec | McpStdioConnectionSpec, PinnedMcpOrigin | None],
    Any,
]


@dataclass(slots=True)
class McpSdkClientLease:
    """One context-bound SDK client without serializable connection material."""

    client: Any = field(repr=False)
    transport: Literal["stdio", "streamable-http", "sse"]
    process_cleanup: McpStdioCleanupEvidence | None = field(
        default=None,
        repr=False,
    )


class OfficialSdkMcpConnectionFactory:
    """Build one guarded SDK context; construction itself starts nothing."""

    def __init__(
        self,
        *,
        resolver: McpDnsResolver | None = None,
        target_factory: ProbeTargetFactory | None = None,
    ) -> None:
        self._resolver = resolver or SystemMcpDnsResolver()
        self._target_factory = target_factory

    @staticmethod
    def _remote_target(
        connection: McpRemoteConnectionSpec,
        origin: PinnedMcpOrigin,
    ):
        endpoint = connection.endpoint.get_secret_value()
        headers = {
            item.name: item.value.get_secret_value() for item in connection.headers
        }
        headers["Accept-Encoding"] = "identity"

        def client_factory(
            headers: dict[str, str] | None = None,
            timeout: httpx2.Timeout | None = None,
            auth: httpx2.Auth | None = None,
        ) -> httpx2.AsyncClient:
            if auth is not None:
                raise McpGuardedHostError("mcp_host_transport_auth_unsupported")
            return httpx2.AsyncClient(
                headers=headers,
                timeout=timeout or httpx2.Timeout(
                    MCP_CONNECT_TIMEOUT_SECONDS,
                    read=MCP_READ_TIMEOUT_SECONDS,
                ),
                follow_redirects=False,
                trust_env=False,
                transport=_PinnedOriginTransport(origin),
            )

        if connection.transport == "sse":
            return sse_client(
                endpoint,
                headers=headers,
                timeout=MCP_CONNECT_TIMEOUT_SECONDS,
                sse_read_timeout=MCP_READ_TIMEOUT_SECONDS,
                httpx_client_factory=client_factory,
            )

        @asynccontextmanager
        async def streamable():
            async with client_factory(headers=headers) as http:
                async with streamable_http_client(
                    endpoint,
                    http_client=http,
                    terminate_on_close=True,
                ) as streams:
                    yield streams

        return streamable()

    @staticmethod
    def _stdio_target(
        connection: McpStdioConnectionSpec,
    ) -> tuple[Any, McpStdioCleanupEvidence]:
        if _ID.fullmatch(connection.management_id) is None:
            raise McpGuardedHostError("mcp_host_stdio_identity_invalid")
        executable = Path(connection.executable)
        if (
            not executable.is_absolute()
            or not executable.is_file()
            or executable.is_symlink()
            or "\x00" in connection.executable
        ):
            raise McpGuardedHostError("mcp_host_stdio_executable_invalid")
        if (
            len(connection.arguments) > MAX_MCP_STDIO_ARGUMENTS
            or any(
                not value
                or len(value) > MAX_MCP_STDIO_ARGUMENT_CHARS
                or "\x00" in value
                for value in connection.arguments
            )
        ):
            raise McpGuardedHostError("mcp_host_stdio_arguments_invalid")
        environment = minimal_environment()
        for name, value in connection.environment.items():
            if (
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name)
                or len(value) > 8_192
                or "\x00" in value
            ):
                raise McpGuardedHostError("mcp_host_stdio_environment_invalid")
            environment[name] = value
        working_directory = connection.working_directory
        if working_directory is not None:
            directory = Path(working_directory)
            if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
                raise McpGuardedHostError("mcp_host_stdio_working_directory_invalid")
        evidence = McpStdioCleanupEvidence()
        return owned_stdio_client(
            executable=str(executable),
            arguments=connection.arguments,
            environment=environment,
            working_directory=working_directory,
            maximum_response_bytes=MAX_MCP_RESPONSE_BYTES,
            evidence=evidence,
        ), evidence

    def _target(
        self,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
    ) -> tuple[Any, PinnedMcpOrigin | None, McpStdioCleanupEvidence | None]:
        if isinstance(connection, McpRemoteConnectionSpec):
            origin = resolve_public_mcp_origin(connection, self._resolver)
            if self._target_factory is not None:
                return self._target_factory(connection, origin), origin, None
            return self._remote_target(connection, origin), origin, None
        if self._target_factory is not None:
            return self._target_factory(connection, None), None, None
        target, evidence = self._stdio_target(connection)
        return target, None, evidence

    @asynccontextmanager
    async def connect(
        self,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        *,
        read_timeout_seconds: float,
        client_info: Implementation,
    ) -> AsyncIterator[McpSdkClientLease]:
        """Own target, handshake, SDK session, and cleanup in one async context."""

        target, _origin, cleanup = self._target(connection)
        transport: Literal["stdio", "streamable-http", "sse"] = (
            connection.transport
            if isinstance(connection, McpRemoteConnectionSpec)
            else "stdio"
        )
        async with Client(
            target,
            mode="auto",
            read_timeout_seconds=read_timeout_seconds,
            client_info=client_info,
            cache=None,
        ) as client:
            yield McpSdkClientLease(
                client=client,
                transport=transport,
                process_cleanup=cleanup,
            )


async def enumerate_mcp_tool_contracts(
    client: Any,
) -> tuple[str, tuple[McpDiscoveredTool, ...]]:
    """Read one complete, cache-bypassed, bounded tool contract listing.

    Probes, persistent-host admission, and health checks share this exact
    operation. It never invokes a tool and refuses partial or cyclic pagination
    rather than turning incomplete evidence into an empty/complete claim.
    """

    protocol_version = str(client.protocol_version)
    if client.server_capabilities.tools is None:
        return protocol_version, ()

    tools: list[McpDiscoveredTool] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _page in range(MAX_MCP_TOOL_PAGES):
        result = await client.list_tools(cursor=cursor, cache_mode="bypass")
        if result.result_type != "complete":
            raise McpGuardedHostError("mcp_host_tool_listing_incomplete")
        if len(tools) + len(result.tools) > MAX_MCP_PROBE_TOOLS:
            raise McpGuardedHostError("mcp_host_tool_count_exceeded")
        tools.extend(
            McpDiscoveredTool(
                name=tool.name,
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                title=tool.title,
                description=tool.description,
            )
            for tool in result.tools
        )
        cursor = result.next_cursor
        if cursor is None:
            return protocol_version, tuple(tools)
        if (
            not isinstance(cursor, str)
            or not cursor
            or len(cursor) > 1_024
            or any(character in cursor for character in ("\x00", "\r", "\n"))
            or cursor in seen_cursors
        ):
            raise McpGuardedHostError("mcp_host_tool_cursor_invalid")
        seen_cursors.add(cursor)
    raise McpGuardedHostError("mcp_host_tool_pages_exceeded")


class OfficialSdkMcpProbeClient:
    """Negotiate modern or legacy MCP and enumerate only bounded tool contracts."""

    def __init__(
        self,
        *,
        resolver: McpDnsResolver | None = None,
        target_factory: ProbeTargetFactory | None = None,
        connection_factory: OfficialSdkMcpConnectionFactory | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if connection_factory is not None and (
            resolver is not None or target_factory is not None
        ):
            raise ValueError(
                "connection_factory cannot be combined with resolver or target_factory"
            )
        self._connections = connection_factory or OfficialSdkMcpConnectionFactory(
            resolver=resolver,
            target_factory=target_factory,
        )
        self._clock = clock or time.monotonic

    async def _probe_async(
        self,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        *,
        deadline_seconds: float,
    ) -> McpHostProbeObservation:
        started = self._clock()
        tools: list[McpDiscoveredTool] = []
        cleanup: McpStdioCleanupEvidence | None = None
        try:
            with anyio.fail_after(deadline_seconds):
                async with self._connections.connect(
                    connection,
                    read_timeout_seconds=min(
                        MCP_READ_TIMEOUT_SECONDS,
                        deadline_seconds,
                    ),
                    client_info=Implementation(
                        name="prompt-enhancer-guarded-host",
                        version="1",
                    ),
                ) as lease:
                    client = lease.client
                    cleanup = lease.process_cleanup
                    protocol_version, discovered = await enumerate_mcp_tool_contracts(
                        client
                    )
                    tools.extend(discovered)
        except TimeoutError:
            raise McpGuardedHostError("mcp_host_deadline_exceeded") from None
        except McpGuardedHostError:
            raise
        except BaseException as error:
            # Never interpolate an exception here: transport errors may contain
            # endpoints, headers, tool payloads or server diagnostics.
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            guarded_codes: set[str] = set()
            pending: list[BaseException] = [error]
            while pending:
                candidate = pending.pop()
                if isinstance(candidate, McpGuardedHostError):
                    guarded_codes.add(candidate.code)
                elif isinstance(candidate, BaseExceptionGroup):
                    pending.extend(candidate.exceptions)
            if len(guarded_codes) == 1:
                raise McpGuardedHostError(guarded_codes.pop()) from None
            raise McpGuardedHostError("mcp_host_probe_failed") from None
        elapsed_ms = max(0, min(120_000, int((self._clock() - started) * 1_000)))
        process_started = isinstance(connection, McpStdioConnectionSpec)
        return McpHostProbeObservation(
            transport=(connection.transport if isinstance(connection, McpRemoteConnectionSpec) else "stdio"),
            protocol_version=protocol_version,
            tools=tuple(tools),
            elapsed_ms=elapsed_ms,
            process_started=process_started,
            process_tree_cleanup_verified=(
                bool(cleanup and cleanup.cleanup_verified)
                if process_started
                else True
            ),
        )

    def probe(
        self,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        *,
        deadline_seconds: float,
    ) -> McpHostProbeObservation:
        async def run() -> McpHostProbeObservation:
            return await self._probe_async(
                connection,
                deadline_seconds=deadline_seconds,
            )

        return anyio.run(run)


__all__ = (
    "MAX_MCP_DNS_ADDRESSES",
    "MAX_MCP_HTTP_HEADER_BYTES",
    "MAX_MCP_HTTP_HEADER_NAME_BYTES",
    "MAX_MCP_HTTP_HEADER_VALUE_BYTES",
    "MAX_MCP_HTTP_HEADERS",
    "MAX_MCP_HTTP_RESPONSES",
    "MAX_MCP_RESPONSE_BYTES",
    "MAX_MCP_SSE_EVENTS_PER_RESPONSE",
    "MCP_CONNECT_TIMEOUT_SECONDS",
    "MCP_READ_TIMEOUT_SECONDS",
    "McpDnsResolver",
    "McpSdkClientLease",
    "OfficialSdkMcpConnectionFactory",
    "OfficialSdkMcpProbeClient",
    "PinnedMcpOrigin",
    "PinnedMcpSyncTransport",
    "SystemMcpDnsResolver",
    "enumerate_mcp_tool_contracts",
    "resolve_public_mcp_origin",
    "resolve_public_https_origin",
)
