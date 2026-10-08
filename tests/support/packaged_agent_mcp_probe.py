"""Validate the installed Agent MCP console entry without provider configuration.

The probe emits one content-free JSON receipt. It does not start the MCP server,
Prompt Enhancer, a model, Codex, Claude, a shell, or a network listener.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


def _console_entry() -> Path:
    distribution = importlib.metadata.distribution("prompt-enhancer")
    matches = [
        entry
        for entry in distribution.entry_points
        if entry.group == "console_scripts" and entry.name == "prompt-enhancer"
    ]
    if len(matches) != 1 or matches[0].value != "prompt_enhancer.cli:main":
        raise RuntimeError("packaged_entry_mismatch")
    filename = "prompt-enhancer.exe" if sys.platform == "win32" else "prompt-enhancer"
    executable = Path(sys.executable).with_name(filename)
    if not executable.is_file():
        raise RuntimeError("packaged_entry_missing")
    return executable


def _environment(application_home: Path) -> dict[str, str]:
    keep = {
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in keep
    }
    environment.update(
        {
            "PROMPT_ENHANCER_HOME": os.fspath(application_home),
            "PROMPT_ENHANCER_SESSION_READER": "disabled",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment


def _parse_claude(stdout: str) -> dict:
    prefix = "# Claude Code (.mcp.json, direct HTTP):\n"
    suffix = "\n\n# Codex (~/.codex/config.toml or trusted project .codex/config.toml):\n"
    if prefix not in stdout or suffix not in stdout:
        raise RuntimeError("claude_config_missing")
    payload = stdout.split(prefix, 1)[1].split(suffix, 1)[0]
    parsed = json.loads(payload)
    server = parsed.get("mcpServers", {}).get("prompt-enhancer-agent")
    if not isinstance(server, dict):
        raise RuntimeError("claude_config_invalid")
    if server != {
        "type": "http",
        "url": "http://127.0.0.1:8765/mcp/agent",
        "headers": {
            "Authorization": "Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}",
        },
    }:
        raise RuntimeError("claude_config_invalid")
    return parsed


def _parse_codex(stdout: str) -> dict:
    prefix = "# Codex (~/.codex/config.toml or trusted project .codex/config.toml):\n"
    if prefix not in stdout:
        raise RuntimeError("codex_config_missing")
    parsed = tomllib.loads(stdout.split(prefix, 1)[1])
    server = parsed.get("mcp_servers", {}).get("prompt-enhancer-agent")
    if not isinstance(server, dict):
        raise RuntimeError("codex_config_invalid")
    if server != {
        "url": "http://127.0.0.1:8765/mcp/agent",
        "bearer_token_env_var": "PROMPT_ENHANCER_AGENT_MCP_TOKEN",
        "tool_timeout_sec": 330,
        "default_tools_approval_mode": "prompt",
    }:
        raise RuntimeError("codex_config_invalid")
    return parsed


def probe() -> dict[str, object]:
    report: dict[str, object] = {
        "contract": "packaged-agent-mcp-probe.v1",
        "entry_target_verified": False,
        "entry_present": False,
        "config_exit_code": None,
        "claude_config_valid": False,
        "codex_config_valid": False,
        "lifecycle_default_off": False,
        "private_state_created": None,
        "temporary_state_removed": False,
        "error_code": None,
    }
    temporary_root: Path | None = None
    try:
        executable = _console_entry()
        report["entry_target_verified"] = True
        report["entry_present"] = True
        with tempfile.TemporaryDirectory(
            prefix="prompt-enhancer-agent-mcp-probe-"
        ) as temporary:
            temporary_root = Path(temporary)
            application_home = temporary_root / "application"
            completed = subprocess.run(
                [executable, "agent-mcp-config"],
                cwd=temporary_root,
                env=_environment(application_home),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            report["config_exit_code"] = completed.returncode
            if completed.returncode != 0:
                raise RuntimeError("config_command_failed")
            _parse_claude(completed.stdout)
            report["claude_config_valid"] = True
            _parse_codex(completed.stdout)
            report["codex_config_valid"] = True
            report["lifecycle_default_off"] = (
                "--acknowledge-model-lifecycle" not in completed.stdout
            )
            report["private_state_created"] = application_home.exists()
            if os.fspath(executable.parent) in completed.stdout + completed.stderr:
                raise RuntimeError("install_path_exposed")
        report["temporary_state_removed"] = True
    except Exception:
        report["error_code"] = "packaged_agent_mcp_probe_failed"
    if temporary_root is not None and temporary_root.exists():
        report["temporary_state_removed"] = False
    return report


def main() -> int:
    report = probe()
    print(
        "PACKAGED_AGENT_MCP_PROBE="
        + json.dumps(report, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    passed = (
        report.get("entry_target_verified") is True
        and report.get("entry_present") is True
        and report.get("config_exit_code") == 0
        and report.get("claude_config_valid") is True
        and report.get("codex_config_valid") is True
        and report.get("lifecycle_default_off") is True
        and report.get("private_state_created") is False
        and report.get("temporary_state_removed") is True
        and report.get("error_code") is None
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
