"""Minimal MCP server: JSON-RPC 2.0 over newline-delimited stdio, tools only.

The Model Context Protocol's stdio transport is one JSON-RPC message per line
on stdin/stdout. This implementation speaks exactly the subset a coding agent
needs to discover and call read-only tools - ``initialize``, ``ping``,
``tools/list``, ``tools/call`` - and answers every other request with "method
not found". It has no network listener, no filesystem surface, and no
dependency beyond the standard library; the tool bodies live in
:mod:`prompt_enhancer.application.agent_surface`.

Starting the server requires an explicit acknowledgement that whatever a tool
returns enters the connected model's context (and may therefore leave the
device through that model's provider). Without it the process prints the
notice and exits without serving.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import sys
from typing import Any, Protocol, TextIO

from ...application.agent_surface import AgentSurfaceError


MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "prompt-enhancer"
MCP_SERVER_INSTRUCTIONS = (
    "Read-only metrics of the owner's own Codex and Claude Code sessions. "
    "Values are metadata and metric results; unknown is never zero, and "
    "model judgments are not metrics."
)
CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV = "PROMPT_ENHANCER_MCP_ACKNOWLEDGE_CONTEXT_EGRESS"
CONTEXT_EGRESS_NOTICE = (
    "prompt-enhancer mcp: every value a tool returns (session names, metric values, counts) "
    "enters the connected model's context and may leave this device through that model's "
    "provider. The tools are read-only and never return transcript text, paths, or tokens. "
    "Start with --acknowledge-context-egress (or set "
    f"{CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV}=1) to serve."
)
MAX_MESSAGE_BYTES = 256 * 1024
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


class McpToolSurface(Protocol):
    """Transport-neutral tool surface used by the small stdio server."""

    def tools(self) -> tuple[Any, ...]: ...

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]: ...


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _result(message_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": dict(result)}


def handle_message(
    surface: McpToolSurface,
    message: Mapping[str, Any],
    *,
    version: str = "0",
    server_name: str = MCP_SERVER_NAME,
    instructions: str = MCP_SERVER_INSTRUCTIONS,
) -> dict[str, Any] | None:
    """Answer one JSON-RPC message; notifications (no id) return None."""

    if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, Mapping) else None, _INVALID_REQUEST, "invalid request")
    method = message["method"]
    message_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, Mapping):
        return None if message_id is None else _error(message_id, _INVALID_PARAMS, "params must be an object")
    if message_id is None:
        # Notifications (notifications/initialized, notifications/cancelled, ...) need no answer.
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": server_name, "version": version},
                "instructions": instructions,
            },
        )
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(
            message_id,
            {
                "tools": [
                    {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema()}
                    for tool in surface.tools()
                ]
            },
        )
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            return _error(message_id, _INVALID_PARAMS, "tool call needs a name and an arguments object")
        try:
            payload = surface.call(name, arguments)
        except AgentSurfaceError as error:
            if error.code == "unknown_tool":
                return _error(message_id, _INVALID_PARAMS, "unknown tool")
            failure: dict[str, object] = {"error": error.code}
            http_status = error.details.get("http_status")
            retryable = error.details.get("retryable")
            if http_status is None or (
                isinstance(http_status, int)
                and not isinstance(http_status, bool)
                and 100 <= http_status <= 599
            ):
                if "http_status" in error.details:
                    failure["http_status"] = http_status
            if isinstance(retryable, bool):
                failure["retryable"] = retryable
            return _result(
                message_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(failure)}
                    ],
                    "structuredContent": failure,
                    "isError": True,
                },
            )
        except Exception:
            return _result(message_id, {"content": [{"type": "text", "text": json.dumps({"error": "tool_failed"})}], "isError": True})
        return _result(
            message_id,
            {"content": [{"type": "text", "text": json.dumps(payload, separators=(",", ":"), default=str)}], "structuredContent": payload, "isError": False},
        )
    if method in {"resources/list", "resources/templates/list"}:
        return _result(message_id, {"resources": []} if method == "resources/list" else {"resourceTemplates": []})
    if method == "prompts/list":
        return _result(message_id, {"prompts": []})
    return _error(message_id, _METHOD_NOT_FOUND, "method not found")


class McpStdioServer:
    """Serve one connected client over text streams until stdin closes."""

    def __init__(
        self,
        surface: McpToolSurface,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        version: str = "0",
        server_name: str = MCP_SERVER_NAME,
        instructions: str = MCP_SERVER_INSTRUCTIONS,
        on_message: Callable[[str], None] | None = None,
    ) -> None:
        if not server_name or len(server_name) > 120:
            raise ValueError("MCP server name is invalid")
        if not instructions or len(instructions) > 512:
            raise ValueError("MCP server instructions are invalid")
        self._surface = surface
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._version = version
        self._server_name = server_name
        self._instructions = instructions
        self._on_message = on_message

    def _send(self, payload: Mapping[str, Any]) -> None:
        self._stdout.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        self._stdout.flush()

    def serve_forever(self) -> int:
        for raw in self._stdin:
            line = raw.strip()
            if not line:
                continue
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                self._send(_error(None, _INVALID_REQUEST, "message too large"))
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self._send(_error(None, _PARSE_ERROR, "parse error"))
                continue
            if self._on_message is not None:
                self._on_message(message.get("method", "?") if isinstance(message, dict) else "?")
            if isinstance(message, list):
                replies = [
                    reply
                    for reply in (
                        handle_message(
                            self._surface,
                            item,
                            version=self._version,
                            server_name=self._server_name,
                            instructions=self._instructions,
                        )
                        for item in message
                    )
                    if reply is not None
                ]
                if replies:
                    self._send_batch(replies)
                continue
            reply = handle_message(
                self._surface,
                message,
                version=self._version,
                server_name=self._server_name,
                instructions=self._instructions,
            )
            if reply is not None:
                self._send(reply)
        return 0

    def _send_batch(self, replies: list[dict[str, Any]]) -> None:
        self._stdout.write(json.dumps(replies, separators=(",", ":"), default=str) + "\n")
        self._stdout.flush()


__all__ = (
    "CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV",
    "CONTEXT_EGRESS_NOTICE",
    "MAX_MESSAGE_BYTES",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVER_NAME",
    "MCP_SERVER_INSTRUCTIONS",
    "McpToolSurface",
    "McpStdioServer",
    "handle_message",
)
