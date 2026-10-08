"""Command-line entry points for the offline-only Phase 1 service."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
import sys
from typing import Any

from .bootstrap import LocalApplication, bootstrap_local_application
from .config import AppSettings
from .domain import DataTier, Provider
from .ingestion import IngestionSelection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt-enhancer",
        description="Private, local-only coding-agent metadata analytics.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="initialize the private local metadata store")
    subparsers.add_parser("demo", help="load deterministic synthetic metadata")
    subparsers.add_parser("status", help="show safe aggregate store status")
    subparsers.add_parser("serve", help="serve the authenticated loopback API")
    subparsers.add_parser(
        "desktop",
        help="open the native always-on-top live-metrics window",
    )
    subparsers.add_parser(
        "agent-desktop",
        help="open the owned native Agent window with protected-action approvals",
    )
    controller = subparsers.add_parser(
        "agent-controller",
        help=(
            "perform one bounded loopback Agent-controller action without "
            "starting the app or another agent; the explicit runtime action "
            "can request model load or unload"
        ),
    )
    controller.add_argument(
        "--base-url",
        default=None,
        help="optional loopback HTTP origin; defaults to configured host and port",
    )
    controller.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=10.0,
        help="bounded timeout for each loopback exchange (0.1 to 60 seconds)",
    )
    controller_actions = controller.add_subparsers(
        dest="agent_controller_command",
        required=True,
    )
    controller_actions.add_parser(
        "discover",
        help="verify and return the content-free v8 controller manifest",
    )
    controller_invoke = controller_actions.add_parser(
        "invoke",
        help="invoke one manifest-declared JSON operation from a stdin envelope",
    )
    controller_invoke.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="confirm this request may return selected sensitive local data",
    )
    controller_open = controller_actions.add_parser(
        "open",
        help=(
            "create or select one durable project and open one validated live chat"
        ),
    )
    controller_open.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="confirm this request may return selected sensitive local data",
    )
    controller_close = controller_actions.add_parser(
        "close",
        help=(
            "close one exact idle live chat while retaining durable metadata and history"
        ),
    )
    controller_close.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="confirm this request may return selected sensitive local data",
    )
    controller_runtime = controller_actions.add_parser(
        "runtime",
        help=(
            "ensure one registered model is ready or stopped with bounded "
            "revision-safe reconciliation"
        ),
    )
    controller_runtime.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="confirm this request may return selected sensitive local data",
    )
    controller_runtime.add_argument(
        "--acknowledge-model-lifecycle",
        action="store_true",
        help="explicitly authorize this request to load, switch, or stop a local model",
    )
    controller_turn = controller_actions.add_parser(
        "turn",
        help="submit exactly one message and run the finite event-polling loop",
    )
    controller_turn.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="confirm this request may return selected sensitive local data",
    )
    controller_turn.add_argument("--deadline-seconds", type=float, default=120.0)
    controller_turn.add_argument("--poll-interval-seconds", type=float, default=0.1)
    controller_turn.add_argument("--drain-timeout-seconds", type=float, default=5.0)
    controller_wait = controller_actions.add_parser(
        "wait",
        help=(
            "continue bounded observation from a prior cursor without "
            "submitting a message or requesting Stop"
        ),
    )
    controller_wait.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="confirm this request may return selected sensitive local data",
    )
    controller_wait.add_argument("--deadline-seconds", type=float, default=120.0)
    controller_wait.add_argument("--poll-interval-seconds", type=float, default=0.1)
    subparsers.add_parser(
        "agent-controller-config",
        help="print the token-free provider-neutral controller command contract",
    )
    agent_mcp = subparsers.add_parser(
        "agent-mcp",
        help=(
            "serve the already-running local Agent controller as standard MCP "
            "tools; starts no app, model, agent, shell, or terminal"
        ),
    )
    agent_mcp.add_argument(
        "--base-url",
        default=None,
        help="optional loopback HTTP origin; defaults to configured host and port",
    )
    agent_mcp.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=10.0,
        help="bounded timeout for each loopback exchange (0.1 to 60 seconds)",
    )
    agent_mcp.add_argument(
        "--acknowledge-sensitive-context-egress",
        action="store_true",
        help="authorize selected local Agent values to enter the connected model context",
    )
    agent_mcp.add_argument(
        "--acknowledge-model-lifecycle",
        action="store_true",
        help="also advertise the explicitly gated local-model load/switch/stop tool",
    )
    agent_mcp_config = subparsers.add_parser(
        "agent-mcp-config",
        help="print token-free direct HTTP Claude Code and Codex configuration snippets",
    )
    agent_mcp_config.add_argument(
        "--transport",
        choices=("http", "stdio"),
        default="http",
        help="direct loopback HTTP by default; stdio is an advanced fallback",
    )
    agent_mcp_config.add_argument(
        "--with-model-lifecycle",
        action="store_true",
        help="include model lifecycle only for the advanced stdio fallback",
    )

    grant = subparsers.add_parser(
        "codex-consent-grant",
        help="grant a local Codex source-access scope without reading it",
    )
    grant.add_argument("scope", choices=("local-history",))
    revoke = subparsers.add_parser(
        "codex-consent-revoke",
        help="revoke a local Codex source-access scope",
    )
    revoke.add_argument("scope", choices=("local-history",))
    index = subparsers.add_parser(
        "codex-index",
        help="build a bounded content-discarding Codex project/session index",
    )
    index.add_argument("--max-sessions", type=int, default=500)
    analyze = subparsers.add_parser(
        "codex-analyze",
        help="derive bounded operational metrics for selected safe IDs",
    )
    analyze.add_argument("--project-id", action="append", default=[])
    analyze.add_argument("--session-id", action="append", default=[])
    analyze.add_argument("--max-sessions", type=int, default=100)

    claude_grant = subparsers.add_parser(
        "claude-consent-grant",
        help="grant the local Claude Code hook-capture scope without reading anything",
    )
    claude_grant.add_argument("scope", choices=("local-history",))
    claude_revoke = subparsers.add_parser(
        "claude-consent-revoke",
        help="revoke the local Claude Code hook-capture scope",
    )
    claude_revoke.add_argument("scope", choices=("local-history",))
    subparsers.add_parser(
        "claude-hook",
        help=(
            "receive one Claude Code hook event on stdin; silent, always exits 0, "
            "writes only a content-free record and only while consent is active"
        ),
    )
    subparsers.add_parser(
        "claude-hooks-config",
        help="print the Claude Code settings.json hooks snippet for this receiver",
    )
    subparsers.add_parser(
        "claude-otel-config",
        help=(
            "print the environment variables that point Claude Code telemetry at "
            "this loopback receiver (token usage, cost, model, version)"
        ),
    )
    mcp = subparsers.add_parser(
        "mcp",
        help=(
            "serve the read-only, allowlisted metrics tools to one coding agent over "
            "stdio (MCP); refuses to start without the context-egress acknowledgement"
        ),
    )
    mcp.add_argument(
        "--acknowledge-context-egress",
        action="store_true",
        help="confirm that returned values enter the connected model's context",
    )
    subparsers.add_parser(
        "mcp-config",
        help="print the Claude Code / Codex configuration snippets for the MCP server",
    )
    subparsers.add_parser(
        "claude-prompt-check",
        help=(
            "Claude Code UserPromptSubmit hook: check the prompt through the local app and "
            "return the advice as additional context; silent and exit 0 on any failure"
        ),
    )
    subparsers.add_parser(
        "claude-prompt-check-config",
        help="print the Claude Code settings.json hooks snippet for the prompt check",
    )
    return parser


def _initialize(settings: AppSettings) -> LocalApplication:
    return bootstrap_local_application(settings)


def _safe_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _status_lines(summary: Any) -> list[str]:
    """Render only a small allowlist of non-identifying aggregate counters."""

    lines = ["Local metadata store is ready."]
    if not isinstance(summary, dict):
        return lines
    labels = (
        ("sessions", "Sessions"),
        ("events", "Events"),
        ("metric_results", "Metric results"),
    )
    for key, label in labels:
        count = _safe_count(summary.get(key))
        if count is not None:
            lines.append(f"{label}: {count}")
    return lines


def _run_init(settings: AppSettings) -> int:
    _initialize(settings)
    print("Initialized the private local metadata store.")
    return 0


def _run_demo(settings: AppSettings) -> int:
    from .adapters.synthetic import SyntheticAdapter

    application = _initialize(settings)
    report = application.create_ingestion_service().ingest(SyntheticAdapter())
    safe_sessions = []
    offset = 0
    while True:
        page = application.database.list_sessions(limit=500, offset=offset)
        for item in page:
            if item.get("provider") != "synthetic":
                continue
            session = application.database.get_session(str(item["session_id"]))
            if session is not None:
                safe_sessions.append(session)
        offset += len(page)
        if len(page) < 500:
            break
    discovery = (
        application.create_discovery_persistence_service().discover_and_persist(
            safe_sessions
        )
    )
    print(
        "Synthetic demo loaded: "
        f"{report.sessions_seen} sessions, {report.events_seen} events, and "
        f"{len(discovery.batch.candidates)} reviewable task suggestion(s)."
    )
    return 0


def _run_status(settings: AppSettings) -> int:
    application = _initialize(settings)
    for line in _status_lines(application.database.summary()):
        print(line)
    return 0



def _codex_tier(scope: str) -> DataTier:
    if scope == "local-history":
        return DataTier.REDACTED_CONTENT
    raise ValueError("unsupported Codex source-access scope")


def _run_codex_consent(
    settings: AppSettings,
    args: argparse.Namespace,
    *,
    revoke: bool,
) -> int:
    application = _initialize(settings)
    tier = _codex_tier(str(args.scope))
    if revoke:
        application.database.revoke_consent(Provider.CODEX, tier)
        from .application.analysis.model_ensemble_watch import (
            MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED,
        )

        application.database.model_ensemble_watch_repository().quarantine_provider_watches(
            Provider.CODEX,
            now=datetime.now(UTC),
            reason_code=MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED,
        )
        print("Revoked the selected local Codex source-access scope.")
    else:
        application.database.grant_consent(Provider.CODEX, tier)
        print("Granted the selected local Codex source-access scope.")
    return 0


def _provider_sessions(
    application: LocalApplication,
    provider: Provider,
) -> list[Any]:
    sessions = []
    offset = 0
    while True:
        page = application.database.list_sessions(limit=500, offset=offset)
        for item in page:
            if item.get("provider") != provider.value:
                continue
            session = application.database.get_session(str(item["session_id"]))
            if session is not None:
                sessions.append(session)
        offset += len(page)
        if len(page) < 500:
            return sessions


def _run_codex_index(settings: AppSettings, args: argparse.Namespace) -> int:
    application = _initialize(settings)
    selection = IngestionSelection(max_sessions=int(args.max_sessions))
    report = application.create_ingestion_service().ingest(
        application.create_codex_adapter(),
        selection=selection,
    )
    discovery = (
        application.create_discovery_persistence_service().discover_and_persist(
            _provider_sessions(application, Provider.CODEX)
        )
    )
    suffix = " (bounded result)" if report.truncated else ""
    print(
        "Codex metadata index loaded: "
        f"{report.sessions_selected} sessions and "
        f"{len(discovery.batch.candidates)} reviewable task suggestion(s){suffix}."
    )
    return 0


def _run_codex_analysis(settings: AppSettings, args: argparse.Namespace) -> int:
    project_ids = frozenset(str(value) for value in args.project_id)
    session_ids = frozenset(str(value) for value in args.session_id)
    if not project_ids and not session_ids:
        raise ValueError("Codex analysis requires a safe project or session ID")
    application = _initialize(settings)
    report = application.create_codex_local_source_service().analyze(
        project_ids=project_ids,
        session_ids=session_ids,
        max_sessions=int(args.max_sessions),
    )
    suffix = " (bounded result)" if report.truncated else ""
    print(
        "Codex operational metrics updated: "
        f"{report.sessions_selected} sessions, {report.events_seen} events, and "
        f"{report.metrics_written} metric observations{suffix}."
    )
    return 0

def _run_claude_consent(
    settings: AppSettings,
    args: argparse.Namespace,
    *,
    revoke: bool,
) -> int:
    application = _initialize(settings)
    tier = _codex_tier(str(args.scope))
    if revoke:
        application.database.revoke_consent(Provider.CLAUDE_CODE, tier)
        print(
            "Revoked the local Claude Code hook-capture scope. The receiver now "
            "records nothing; already-recorded events remain until deleted."
        )
    else:
        application.database.grant_consent(Provider.CLAUDE_CODE, tier)
        print(
            "Granted the local Claude Code hook-capture scope. Add the hooks "
            "snippet from `claude-hooks-config` to enable capture."
        )
    return 0


def _run_claude_hook(settings: AppSettings) -> int:
    from .infrastructure.providers.claude_code_hooks.receiver import main as hook_main

    return hook_main(settings)


def _run_claude_hooks_config(settings: AppSettings) -> int:
    """Print the settings.json fragment; the user pastes it, we write nothing."""

    import json

    command = f"{sys.executable} -m prompt_enhancer claude-hook"
    events = (
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "SubagentStop",
        "PreCompact",
    )
    hooks = {
        event: [{"hooks": [{"type": "command", "command": command, "timeout": 5}]}]
        for event in events
    }
    print(json.dumps({"hooks": hooks}, indent=2))
    notes = (
        "",
        "# Paste the object above into your Claude Code settings.json (merge the",
        '# "hooks" key). The receiver records only content-free lifecycle',
        "# metadata, only while `claude-consent-grant local-history` is active,",
        "# and never reads transcripts, prompts, or tool output.",
    )
    print("\n".join(notes), file=sys.stderr)
    return 0


def _run_mcp(settings: AppSettings, args: argparse.Namespace) -> int:
    """Serve the read-only agent surface over stdio after an explicit acknowledgement."""

    import os

    from . import __version__
    from .interfaces.mcp import (
        CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV,
        CONTEXT_EGRESS_NOTICE,
        McpStdioServer,
    )

    acknowledged = bool(getattr(args, "acknowledge_context_egress", False)) or os.environ.get(
        CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV, ""
    ).strip() in {"1", "true", "yes"}
    if not acknowledged:
        print(CONTEXT_EGRESS_NOTICE, file=sys.stderr)
        return 2
    application = _initialize(settings)
    surface = application.create_agent_read_surface()
    return McpStdioServer(surface, version=__version__).serve_forever()


def _run_mcp_config(settings: AppSettings) -> int:
    """Print configuration snippets; the person adds them, we write no config."""

    import json
    import shlex

    command = sys.executable
    args = ["-m", "prompt_enhancer", "mcp", "--acknowledge-context-egress"]
    claude_snippet = {
        "mcpServers": {
            "prompt-enhancer": {"type": "stdio", "command": command, "args": args}
        }
    }
    print("# Claude Code (.mcp.json in a project, or ~/.claude.json under mcpServers):")
    print(json.dumps(claude_snippet, indent=2))
    print()
    print("# Claude Code one-liner:")
    print(
        "claude mcp add --transport stdio prompt-enhancer -- "
        + " ".join(shlex.quote(part) for part in [command, *args])
    )
    print()
    print("# Codex (~/.codex/config.toml):")
    print("[mcp_servers.prompt-enhancer]")
    print(f"command = {json.dumps(command)}")
    print(f"args = {json.dumps(args)}")
    notes = (
        "",
        "# Read-only and allowlisted: list_metric_definitions, list_sessions, get_session_metrics,",
        "# summarize_period, explain_metric, get_calibration_status. No transcript text, paths, or",
        "# tokens are ever returned; everything a tool returns enters the connected model's context.",
    )
    print("\n".join(notes), file=sys.stderr)
    return 0


def _run_claude_prompt_check(settings: AppSettings) -> int:
    from .interfaces.hooks import run_prompt_check_hook

    return run_prompt_check_hook(settings)


def _run_claude_prompt_check_config(settings: AppSettings) -> int:
    """Print the hooks snippet; the person adds it, we write no config."""

    import json

    from .interfaces.hooks import HOOK_COMMENTARY_ENV, HOOK_ENABLED_ENV

    command = f'"{sys.executable}" -m prompt_enhancer claude-prompt-check'
    snippet = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": command, "timeout": 60}]}
            ]
        }
    }
    print(json.dumps(snippet, indent=2))
    notes = (
        "",
        "# Merge into ~/.claude/settings.json (or a project's .claude/settings.json).",
        "# Every prompt of at least four words is then checked by the local app (prompt-enhancer serve",
        "# must be running): deterministic cues always, local-model commentary and a reformulated prompt",
        f"# when a model is active. Switch off without editing settings: {HOOK_ENABLED_ENV}=0;",
        f"# deterministic-only (fast): {HOOK_COMMENTARY_ENV}=0. The prompt travels only to 127.0.0.1;",
        "# nothing but metrics is stored. The hook never blocks: on any failure it prints nothing.",
    )
    print("\n".join(notes), file=sys.stderr)
    return 0


def _run_claude_otel_config(settings: AppSettings) -> int:
    """Print exporter env vars; the user sets them, we write no config."""

    from .privacy import load_or_create_api_token

    token = load_or_create_api_token(settings.otlp_ingest_token_path)
    endpoint = f"http://{settings.host}:{settings.port}"
    lines = (
        "CLAUDE_CODE_ENABLE_TELEMETRY=1",
        "OTEL_METRICS_EXPORTER=otlp",
        "OTEL_LOGS_EXPORTER=otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL=http/json",
        f"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT={endpoint}/otlp/v1/logs",
        f"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT={endpoint}/otlp/v1/metrics",
        f"OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer {token}",
        "OTEL_LOG_USER_PROMPTS=0",
    )
    print("\n".join(lines))
    notes = (
        "",
        "# Set these in the environment that launches Claude Code, then run",
        "# `prompt-enhancer serve`. Only api_request usage (tokens, model, duration,",
        "# the provider's own cost estimate) and documented session counters are",
        "# recorded; account, organization, user, prompt, tool-parameter, and error",
        "# fields are never read. Capture requires the local server to be running",
        "# and `claude-consent-grant local-history` to be active; a missing batch",
        "# is a gap, never a zero. Keep OTEL_LOG_USER_PROMPTS unset or 0.",
    )
    print("\n".join(notes), file=sys.stderr)
    return 0


def _run_serve(settings: AppSettings) -> int:
    import uvicorn

    application = _initialize(settings)
    app = application.create_http_app()
    print(f"Serving the authenticated local API on loopback port {settings.port}.")
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_level="warning",
    )
    return 0


def _run_desktop(settings: AppSettings) -> int:
    from .desktop_overlay import run_desktop_overlay

    run_desktop_overlay(settings)
    return 0


def _run_agent_desktop(settings: AppSettings) -> int:
    from .desktop_overlay import launch_desktop_agent

    launch_desktop_agent(settings)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = AppSettings.from_env()
        if args.command == "codex-consent-grant":
            return _run_codex_consent(settings, args, revoke=False)
        if args.command == "codex-consent-revoke":
            return _run_codex_consent(settings, args, revoke=True)
        if args.command == "codex-index":
            return _run_codex_index(settings, args)
        if args.command == "codex-analyze":
            return _run_codex_analysis(settings, args)
        if args.command == "claude-consent-grant":
            return _run_claude_consent(settings, args, revoke=False)
        if args.command == "claude-consent-revoke":
            return _run_claude_consent(settings, args, revoke=True)
        if args.command == "claude-hook":
            return _run_claude_hook(settings)
        if args.command == "claude-hooks-config":
            return _run_claude_hooks_config(settings)
        if args.command == "claude-otel-config":
            return _run_claude_otel_config(settings)
        if args.command == "mcp":
            return _run_mcp(settings, args)
        if args.command == "mcp-config":
            return _run_mcp_config(settings)
        if args.command == "claude-prompt-check":
            return _run_claude_prompt_check(settings)
        if args.command == "claude-prompt-check-config":
            return _run_claude_prompt_check_config(settings)
        if args.command == "agent-controller":
            from .interfaces.agent_controller_cli import run_agent_controller

            return run_agent_controller(settings, args)
        if args.command == "agent-controller-config":
            from .interfaces.agent_controller_cli import run_agent_controller_config

            return run_agent_controller_config()
        if args.command == "agent-mcp":
            from .interfaces.agent_mcp import run_agent_mcp

            return run_agent_mcp(settings, args)
        if args.command == "agent-mcp-config":
            from .interfaces.agent_mcp import run_agent_mcp_config

            return run_agent_mcp_config(
                settings,
                transport=str(args.transport),
                with_model_lifecycle=bool(args.with_model_lifecycle)
            )
        handlers = {
            "init": _run_init,
            "demo": _run_demo,
            "status": _run_status,
            "serve": _run_serve,
            "desktop": _run_desktop,
            "agent-desktop": _run_agent_desktop,
        }
        return handlers[args.command](settings)
    except (OSError, RuntimeError, ValueError):
        print("prompt-enhancer: local operation failed safely.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
