"""Repeatable packaging checks for the Agent MCP console integration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib

from prompt_enhancer.interfaces.agent_mcp import run_agent_mcp_config


REPOSITORY = Path(__file__).resolve().parents[1]


def _probe_module():
    probe_path = REPOSITORY / "tests" / "support" / "packaged_agent_mcp_probe.py"
    spec = importlib.util.spec_from_file_location(
        "packaged_agent_mcp_probe_for_test",
        probe_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_console_entry_is_declared_at_the_exact_cli_target() -> None:
    project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["prompt-enhancer"] == (
        "prompt_enhancer.cli:main"
    )


def test_packaging_probe_accepts_the_generated_claude_and_codex_documents(
    capsys,
) -> None:
    assert run_agent_mcp_config() == 0
    captured = capsys.readouterr()
    probe = _probe_module()

    claude = probe._parse_claude(captured.out)
    codex = probe._parse_codex(captured.out)

    assert set(claude["mcpServers"]) == {"prompt-enhancer-agent"}
    assert set(codex["mcp_servers"]) == {"prompt-enhancer-agent"}
    assert "private token" not in captured.out.casefold()
    assert "visible terminal" in captured.err.casefold()
