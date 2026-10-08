"""Canonical Codex and Claude Code configuration for direct Agent MCP."""

from __future__ import annotations

import json
import tomllib

import pytest

from prompt_enhancer.application.agent_mcp_client_config import (
    AGENT_MCP_BEARER_ENV,
    AGENT_MCP_SERVER_NAME,
    AGENT_MCP_TOOL_TIMEOUT_SECONDS,
    AgentMcpClientConfigError,
    build_agent_mcp_client_configs,
    validate_agent_mcp_client_configs,
)


ENDPOINT = "http://127.0.0.1:8765/mcp/agent"


def test_generated_configs_parse_as_exact_provider_shapes() -> None:
    configs = build_agent_mcp_client_configs(ENDPOINT)

    assert configs.endpoint_url == ENDPOINT
    assert tomllib.loads(configs.codex_toml) == {
        "mcp_servers": {
            AGENT_MCP_SERVER_NAME: {
                "url": ENDPOINT,
                "bearer_token_env_var": AGENT_MCP_BEARER_ENV,
                "tool_timeout_sec": AGENT_MCP_TOOL_TIMEOUT_SECONDS,
                "default_tools_approval_mode": "prompt",
            }
        }
    }
    assert json.loads(configs.claude_json) == {
        "mcpServers": {
            AGENT_MCP_SERVER_NAME: {
                "type": "http",
                "url": ENDPOINT,
                "headers": {
                    "Authorization": f"Bearer ${{{AGENT_MCP_BEARER_ENV}}}",
                },
            }
        }
    }
    assert "pemcp1." not in configs.codex_toml
    assert "pemcp2." not in configs.codex_toml
    assert "pemcp1." not in configs.claude_json
    assert "pemcp2." not in configs.claude_json
    assert configs.codex_add_command == (
        "codex mcp add prompt-enhancer-agent "
        f"--url {ENDPOINT} "
        "--bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN"
    )
    assert configs.claude_add_command == (
        "claude mcp add --transport http --scope local "
        "--header 'Authorization: Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' "
        f"prompt-enhancer-agent {ENDPOINT}"
    )
    for command in (configs.codex_add_command, configs.claude_add_command):
        assert "pemcp1." not in command
        assert "pemcp2." not in command
        assert "<paste" not in command


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://localhost:8765/mcp/agent",
        "http://[::1]:8765/mcp/agent",
    ),
)
def test_all_supported_loopback_endpoint_forms_generate(endpoint: str) -> None:
    configs = build_agent_mcp_client_configs(endpoint)
    validate_agent_mcp_client_configs(
        endpoint_url=endpoint,
        codex_toml=configs.codex_toml,
        claude_json=configs.claude_json,
    )


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:8765/mcp/agent",
        "http://0.0.0.0:8765/mcp/agent",
        "http://example.invalid:8765/mcp/agent",
        "http://synthetic-user" + chr(64) + "127.0.0.1:8765/mcp/agent",
        "http://127.0.0.1:8765/mcp/agent?debug=1",
        "http://127.0.0.1:8765/mcp/agent#fragment",
        "http://127.0.0.1:8765/v1/agent",
    ),
)
def test_non_exact_or_non_loopback_endpoints_fail_closed(endpoint: str) -> None:
    with pytest.raises(AgentMcpClientConfigError) as rejected:
        build_agent_mcp_client_configs(endpoint)
    assert rejected.value.code == "agent_mcp_endpoint_invalid"


@pytest.mark.parametrize("provider", ("codex", "claude"))
def test_tampered_provider_config_fails_closed(provider: str) -> None:
    configs = build_agent_mcp_client_configs(ENDPOINT)
    codex = configs.codex_toml
    claude = configs.claude_json
    if provider == "codex":
        codex = codex.replace(
            'default_tools_approval_mode = "prompt"',
            'default_tools_approval_mode = "auto"',
        )
    else:
        claude = claude.replace('"type": "http"', '"type": "sse"')

    with pytest.raises(AgentMcpClientConfigError) as rejected:
        validate_agent_mcp_client_configs(
            endpoint_url=ENDPOINT,
            codex_toml=codex,
            claude_json=claude,
        )
    assert rejected.value.code == "agent_mcp_client_config_invalid"


def test_malformed_config_fails_with_one_content_free_error() -> None:
    with pytest.raises(AgentMcpClientConfigError) as rejected:
        validate_agent_mcp_client_configs(
            endpoint_url=ENDPOINT,
            codex_toml="not = [toml",
            claude_json="{not json}",
        )
    assert rejected.value.code == "agent_mcp_client_config_invalid"
