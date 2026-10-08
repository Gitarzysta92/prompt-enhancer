"""Content-free acceptance probe for one live direct Agent MCP connection.

The bearer is read only from ``PROMPT_ENHANCER_AGENT_MCP_TOKEN`` and is never
printed, persisted, included in an exception, or sent anywhere except the
validated loopback endpoint.  Active mode uses two independent HTTP clients
and performs only initialize, tool discovery, and the content-free Agent
manifest call.  Revoked mode proves that the same credential is rejected.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener


TOKEN_ENV = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"
ENDPOINT_ENV = "PROMPT_ENHANCER_AGENT_MCP_URL"
DEFAULT_ENDPOINT = "http://127.0.0.1:8765/mcp/agent"
PROTOCOL_VERSION = "2025-06-18"
EXPECTED_SERVER = "prompt-enhancer-agent"
EXPECTED_DISCOVERY_CONTRACT = "local-agent-orchestration.v22"
EXPECTED_TOOLS = frozenset(
    {
        "agent_artifacts",
        "agent_catalog",
        "agent_control",
        "agent_context",
        "agent_discover",
        "agent_history",
        "agent_open",
        "agent_propose",
        "agent_propose_transaction",
        "agent_propose_lifecycle",
        "agent_resume",
        "agent_fork",
        "agent_export",
        "agent_close",
        "agent_stage_attachment",
        "agent_stop",
        "agent_turn",
        "agent_wait",
        "agent_workspace",
    }
)
_TOKEN_PATTERN = re.compile(
    r"^pemcp2\.[0-9a-f]{32}\.[1-9][0-9]{0,8}\.[A-Za-z0-9_-]{43}$"
)


class ProbeFailure(RuntimeError):
    """Fixed-code failure that never carries response or credential content."""


def _endpoint() -> str:
    value = os.environ.get(ENDPOINT_ENV, DEFAULT_ENDPOINT)
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ProbeFailure("endpoint_invalid") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/mcp/agent"
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeFailure("endpoint_invalid")
    return value


def _token() -> str:
    value = os.environ.get(TOKEN_ENV, "")
    if _TOKEN_PATTERN.fullmatch(value) is None:
        raise ProbeFailure("credential_missing_or_invalid")
    return value


def _message_result(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("result"), Mapping
    ):
        raise ProbeFailure("mcp_response_invalid")
    return payload["result"]


def _post(
    opener: OpenerDirector,
    *,
    endpoint: str,
    token: str,
    message: Mapping[str, Any],
) -> Mapping[str, Any]:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        },
        method="POST",
    )
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ProbeFailure("mcp_status_invalid")
        try:
            payload = json.loads(response.read())
        except (UnicodeDecodeError, ValueError):
            raise ProbeFailure("mcp_response_invalid") from None
    if not isinstance(payload, Mapping):
        raise ProbeFailure("mcp_response_invalid")
    return payload


def _initialize(
    opener: OpenerDirector,
    *,
    endpoint: str,
    token: str,
    identifier: int,
    client_name: str,
) -> Mapping[str, Any]:
    payload = _post(
        opener,
        endpoint=endpoint,
        token=token,
        message={
            "jsonrpc": "2.0",
            "id": identifier,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "1"},
            },
        },
    )
    return _message_result(payload)


def _tools(
    opener: OpenerDirector,
    *,
    endpoint: str,
    token: str,
    identifier: int,
) -> frozenset[str]:
    result = _message_result(
        _post(
            opener,
            endpoint=endpoint,
            token=token,
            message={
                "jsonrpc": "2.0",
                "id": identifier,
                "method": "tools/list",
            },
        )
    )
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise ProbeFailure("mcp_tools_invalid")
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, Mapping) or not isinstance(tool.get("name"), str):
            raise ProbeFailure("mcp_tools_invalid")
        names.append(tool["name"])
    if len(names) != len(set(names)):
        raise ProbeFailure("mcp_tools_invalid")
    return frozenset(names)


def _discover(
    opener: OpenerDirector,
    *,
    endpoint: str,
    token: str,
    identifier: int,
) -> Mapping[str, Any]:
    result = _message_result(
        _post(
            opener,
            endpoint=endpoint,
            token=token,
            message={
                "jsonrpc": "2.0",
                "id": identifier,
                "method": "tools/call",
                "params": {"name": "agent_discover", "arguments": {}},
            },
        )
    )
    if result.get("isError") is not False:
        raise ProbeFailure("agent_discovery_failed")
    structured = result.get("structuredContent")
    if not isinstance(structured, Mapping):
        raise ProbeFailure("agent_discovery_failed")
    discovered = structured.get("result")
    if not isinstance(discovered, Mapping):
        raise ProbeFailure("agent_discovery_failed")
    return discovered


def active_probe() -> dict[str, object]:
    report: dict[str, object] = {
        "contract": "direct-agent-mcp-live-probe.v1",
        "mode": "active",
        "loopback_endpoint_valid": False,
        "independent_clients": 0,
        "protocol_valid": False,
        "server_identity_valid": False,
        "tool_count": None,
        "default_tool_surface_exact": False,
        "model_lifecycle_absent": False,
        "discovery_contract_valid": False,
        "catalog_mutation_requested": False,
        "error_code": None,
    }
    try:
        endpoint = _endpoint()
        token = _token()
        report["loopback_endpoint_valid"] = True
        first_client = build_opener(ProxyHandler({}))
        second_client = build_opener(ProxyHandler({}))
        first = _initialize(
            first_client,
            endpoint=endpoint,
            token=token,
            identifier=1,
            client_name="synthetic-direct-agent-probe-one",
        )
        second = _initialize(
            second_client,
            endpoint=endpoint,
            token=token,
            identifier=101,
            client_name="synthetic-direct-agent-probe-two",
        )
        report["independent_clients"] = 2
        report["protocol_valid"] = (
            first.get("protocolVersion") == PROTOCOL_VERSION
            and second.get("protocolVersion") == PROTOCOL_VERSION
        )
        first_server = first.get("serverInfo")
        second_server = second.get("serverInfo")
        report["server_identity_valid"] = (
            isinstance(first_server, Mapping)
            and first_server.get("name") == EXPECTED_SERVER
            and isinstance(second_server, Mapping)
            and second_server.get("name") == EXPECTED_SERVER
        )
        first_tools = _tools(
            first_client,
            endpoint=endpoint,
            token=token,
            identifier=2,
        )
        second_tools = _tools(
            second_client,
            endpoint=endpoint,
            token=token,
            identifier=102,
        )
        if first_tools != second_tools:
            raise ProbeFailure("client_tool_surfaces_differ")
        report["tool_count"] = len(first_tools)
        report["default_tool_surface_exact"] = first_tools == EXPECTED_TOOLS
        report["model_lifecycle_absent"] = "agent_runtime" not in first_tools
        discovery = _discover(
            second_client,
            endpoint=endpoint,
            token=token,
            identifier=103,
        )
        report["discovery_contract_valid"] = (
            discovery.get("contract_version") == EXPECTED_DISCOVERY_CONTRACT
        )
    except (HTTPError, OSError, ProbeFailure):
        report["error_code"] = "direct_agent_mcp_active_probe_failed"
    return report


def revoked_probe() -> dict[str, object]:
    report: dict[str, object] = {
        "contract": "direct-agent-mcp-live-probe.v1",
        "mode": "revoked",
        "loopback_endpoint_valid": False,
        "credential_rejected": False,
        "rejection_status": None,
        "error_code": None,
    }
    try:
        endpoint = _endpoint()
        token = _token()
        report["loopback_endpoint_valid"] = True
        try:
            _post(
                build_opener(ProxyHandler({})),
                endpoint=endpoint,
                token=token,
                message={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            )
        except HTTPError as error:
            report["rejection_status"] = error.code
            report["credential_rejected"] = error.code == 401
        else:
            raise ProbeFailure("revoked_credential_accepted")
    except (OSError, ProbeFailure):
        report["error_code"] = "direct_agent_mcp_revoked_probe_failed"
    return report


def _passed(report: Mapping[str, object]) -> bool:
    if report.get("mode") == "active":
        return (
            report.get("loopback_endpoint_valid") is True
            and report.get("independent_clients") == 2
            and report.get("protocol_valid") is True
            and report.get("server_identity_valid") is True
            and report.get("tool_count") == len(EXPECTED_TOOLS)
            and report.get("default_tool_surface_exact") is True
            and report.get("model_lifecycle_absent") is True
            and report.get("discovery_contract_valid") is True
            and report.get("catalog_mutation_requested") is False
            and report.get("error_code") is None
        )
    return (
        report.get("loopback_endpoint_valid") is True
        and report.get("credential_rejected") is True
        and report.get("rejection_status") == 401
        and report.get("error_code") is None
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--expect-active", action="store_true")
    modes.add_argument("--expect-revoked", action="store_true")
    arguments = parser.parse_args()
    report = active_probe() if arguments.expect_active else revoked_probe()
    print(
        "DIRECT_AGENT_MCP_PROBE="
        + json.dumps(report, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return 0 if _passed(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
