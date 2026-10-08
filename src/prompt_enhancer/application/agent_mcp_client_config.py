"""Canonical, token-free client configuration for the Agent MCP endpoint.

The application may generate copyable provider configuration, but it must
never edit Codex or Claude settings itself. Keeping generation and structural
validation in one module prevents the native credential response and the CLI
template from drifting into two subtly different connection contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import tomllib
from urllib.parse import urlsplit


AGENT_MCP_BEARER_ENV = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"
AGENT_MCP_HTTP_PATH = "/mcp/agent"
AGENT_MCP_SERVER_NAME = "prompt-enhancer-agent"
AGENT_MCP_TOOL_TIMEOUT_SECONDS = 330


class AgentMcpClientConfigError(RuntimeError):
    """A generated or supplied client configuration failed closed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentMcpClientConfigs:
    """Exact copyable setup values; none contains a bearer secret."""

    endpoint_url: str
    codex_toml: str
    claude_json: str
    codex_add_command: str
    claude_add_command: str


def _codex_add_command(endpoint_url: str) -> str:
    return (
        f"codex mcp add {AGENT_MCP_SERVER_NAME} --url {endpoint_url} "
        f"--bearer-token-env-var {AGENT_MCP_BEARER_ENV}"
    )


def _claude_add_command(endpoint_url: str) -> str:
    # Single quotes preserve the ${VAR} template in both PowerShell and POSIX
    # shells. The user's bearer value remains separate and never enters the
    # generated command or shell history through this application.
    authorization = f"Authorization: Bearer ${{{AGENT_MCP_BEARER_ENV}}}"
    return (
        "claude mcp add --transport http --scope local "
        f"--header '{authorization}' {AGENT_MCP_SERVER_NAME} {endpoint_url}"
    )


def validate_agent_mcp_endpoint(endpoint_url: str) -> str:
    """Accept only the direct loopback Streamable HTTP endpoint."""

    parsed = urlsplit(endpoint_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != AGENT_MCP_HTTP_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise AgentMcpClientConfigError("agent_mcp_endpoint_invalid")
    return endpoint_url


def _expected_codex(endpoint_url: str) -> dict[str, object]:
    return {
        "mcp_servers": {
            AGENT_MCP_SERVER_NAME: {
                "url": endpoint_url,
                "bearer_token_env_var": AGENT_MCP_BEARER_ENV,
                "tool_timeout_sec": AGENT_MCP_TOOL_TIMEOUT_SECONDS,
                "default_tools_approval_mode": "prompt",
            }
        }
    }


def _expected_claude(endpoint_url: str) -> dict[str, object]:
    return {
        "mcpServers": {
            AGENT_MCP_SERVER_NAME: {
                "type": "http",
                "url": endpoint_url,
                "headers": {
                    "Authorization": f"Bearer ${{{AGENT_MCP_BEARER_ENV}}}",
                },
            }
        }
    }


def validate_agent_mcp_client_configs(
    *,
    endpoint_url: str,
    codex_toml: str,
    claude_json: str,
) -> None:
    """Parse and compare both snippets against the exact supported schemas."""

    endpoint = validate_agent_mcp_endpoint(endpoint_url)
    if not (0 < len(codex_toml) <= 4096 and 0 < len(claude_json) <= 4096):
        raise AgentMcpClientConfigError("agent_mcp_client_config_invalid")
    try:
        codex = tomllib.loads(codex_toml)
        claude = json.loads(claude_json)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, UnicodeError):
        raise AgentMcpClientConfigError(
            "agent_mcp_client_config_invalid"
        ) from None
    if codex != _expected_codex(endpoint) or claude != _expected_claude(endpoint):
        raise AgentMcpClientConfigError("agent_mcp_client_config_invalid")


def build_agent_mcp_client_configs(endpoint_url: str) -> AgentMcpClientConfigs:
    """Build the exact official Codex TOML and Claude Code JSON shapes."""

    endpoint = validate_agent_mcp_endpoint(endpoint_url)
    codex = "\n".join(
        (
            f"[mcp_servers.{AGENT_MCP_SERVER_NAME}]",
            f"url = {json.dumps(endpoint)}",
            f"bearer_token_env_var = {json.dumps(AGENT_MCP_BEARER_ENV)}",
            f"tool_timeout_sec = {AGENT_MCP_TOOL_TIMEOUT_SECONDS}",
            'default_tools_approval_mode = "prompt"',
        )
    )
    claude = json.dumps(_expected_claude(endpoint), indent=2)
    validate_agent_mcp_client_configs(
        endpoint_url=endpoint,
        codex_toml=codex,
        claude_json=claude,
    )
    return AgentMcpClientConfigs(
        endpoint_url=endpoint,
        codex_toml=codex,
        claude_json=claude,
        codex_add_command=_codex_add_command(endpoint),
        claude_add_command=_claude_add_command(endpoint),
    )


__all__ = (
    "AGENT_MCP_BEARER_ENV",
    "AGENT_MCP_HTTP_PATH",
    "AGENT_MCP_SERVER_NAME",
    "AGENT_MCP_TOOL_TIMEOUT_SECONDS",
    "AgentMcpClientConfigError",
    "AgentMcpClientConfigs",
    "build_agent_mcp_client_configs",
    "validate_agent_mcp_client_configs",
    "validate_agent_mcp_endpoint",
)
