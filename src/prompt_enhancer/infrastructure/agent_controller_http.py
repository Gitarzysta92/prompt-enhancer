"""No-proxy, no-redirect HTTP transport for the local Agent controller."""

from __future__ import annotations

from collections.abc import Mapping
import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

from ..application.agent_controller_client import (
    AgentControllerError,
    AgentControllerHttpResponse,
    AgentControllerTransportUnavailable,
    MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES,
    MAX_CONTROLLER_REQUEST_BYTES,
    MAX_CONTROLLER_RESPONSE_BYTES,
)
from ..config import is_loopback_host


class _RejectRedirects(HTTPRedirectHandler):
    """Never forward an authorization header to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _safe_controller_path(path: str) -> bool:
    if (
        not path.startswith("/v1/")
        or len(path) > 2_048
        or any(character in path for character in ("\\", "?", "#", "\r", "\n", "\x00"))
    ):
        return False
    decoded = unquote(path)
    return not any(part == ".." for part in decoded.split("/"))


class LoopbackAgentControllerTransport:
    """Authenticated JSON exchange restricted to one exact loopback origin."""

    __slots__ = ("_base_url", "_opener", "_timeout", "_token")

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        opener: OpenerDirector | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        try:
            port = parsed.port or 80
        except ValueError:
            raise AgentControllerError("controller_base_url_invalid") from None
        host = parsed.hostname or ""
        if (
            parsed.scheme != "http"
            or not is_loopback_host(host)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not 1 <= port <= 65_535
        ):
            raise AgentControllerError("controller_base_url_invalid")
        if not token or len(token) < 32 or any(character.isspace() for character in token):
            raise AgentControllerError("controller_token_invalid")
        if not 0.1 <= timeout_seconds <= 60:
            raise AgentControllerError("controller_request_timeout_invalid")
        rendered_host = f"[{host}]" if ":" in host else host
        self._base_url = f"http://{rendered_host}:{port}"
        self._token = token
        self._timeout = timeout_seconds
        self._opener = opener or build_opener(ProxyHandler({}), _RejectRedirects())

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self._base_url!r}, "
            "token=<redacted>)"
        )

    @staticmethod
    def _read_bounded(response) -> bytes:  # noqa: ANN001
        body = response.read(MAX_CONTROLLER_RESPONSE_BYTES + 1)
        if len(body) > MAX_CONTROLLER_RESPONSE_BYTES:
            raise AgentControllerError("controller_response_too_large")
        return body

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | int | bool] | None = None,
        json_body: Any | None = None,
        max_request_bytes: int = MAX_CONTROLLER_REQUEST_BYTES,
    ) -> AgentControllerHttpResponse:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST", "PATCH", "DELETE"}:
            raise AgentControllerError("controller_method_invalid")
        if not _safe_controller_path(path):
            raise AgentControllerError("controller_path_invalid")
        if max_request_bytes not in {
            MAX_CONTROLLER_REQUEST_BYTES,
            MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES,
        }:
            raise AgentControllerError("controller_request_limit_invalid")
        encoded_query = ""
        if query:
            pairs: list[tuple[str, str]] = []
            for key, value in query.items():
                if isinstance(value, bool):
                    rendered = "true" if value else "false"
                else:
                    rendered = str(value)
                pairs.append((key, rendered))
            encoded_query = "?" + urlencode(pairs)
        url = self._base_url + path + encoded_query

        data: bytes | None = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
            "Cache-Control": "no-store",
            "User-Agent": "prompt-enhancer-agent-controller/1",
        }
        if json_body is not None:
            try:
                data = json.dumps(
                    json_body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError):
                raise AgentControllerError("controller_request_invalid") from None
            if len(data) > max_request_bytes:
                raise AgentControllerError("controller_request_too_large")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=data, headers=headers, method=normalized_method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                final = urlsplit(response.geturl())
                final_port = final.port or 80
                requested = urlsplit(self._base_url)
                requested_port = requested.port or 80
                if (
                    final.scheme != "http"
                    or final.hostname != requested.hostname
                    or final_port != requested_port
                ):
                    raise AgentControllerError("controller_redirect_refused")
                return AgentControllerHttpResponse(
                    status_code=int(response.status),
                    content_type=response.headers.get("Content-Type"),
                    body=self._read_bounded(response),
                )
        except HTTPError as error:
            return AgentControllerHttpResponse(
                status_code=int(error.code),
                content_type=error.headers.get("Content-Type"),
                body=self._read_bounded(error),
            )
        except AgentControllerError:
            raise
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise AgentControllerTransportUnavailable() from None


__all__ = ("LoopbackAgentControllerTransport",)
