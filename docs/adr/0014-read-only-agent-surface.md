# ADR 0014: Read-only agent surface (MCP over stdio)

- Status: accepted (2026-08-19)
- Owner direction: let an already-running Codex or Claude Code session ask the
  app about the owner's own metrics, without giving any agent a way to read
  transcripts, files, or the database.

## Context

The architecture reserved a "read-only allowlisted MCP server" and said that
before enabling it the app must explain that returned values enter the
connected model's context. Every other surface of the app is loopback HTTP
behind the app token; coding agents reach tools through the Model Context
Protocol, whose simplest transport is one JSON-RPC message per line on
stdin/stdout of a child process the agent starts itself. No MCP SDK is a
dependency of this repository, and adding one only to speak four methods would
widen the supply chain for no gain.

## Decision

1. **One shared read surface.** `application/agent_surface.py` defines the
   allowlisted tools and their bounded inputs; every transport that exposes
   them (today: MCP over stdio) calls the same functions. The tools are:
   `list_metric_definitions`, `list_sessions` (paged, ≤ 50), `get_session_metrics`,
   `summarize_period` (≤ 365 days, ≤ 300 most recent sessions, marked
   `truncated` when capped), `explain_metric`, `get_calibration_status`.
   They return metadata and metric values only: the project and session
   names the owner shows in the dashboard, pseudonymous identifiers, provider,
   timestamps, terminal state, metric keys/values/states/coverage/confidence,
   calibration progress, and model-judge agreement. Never transcript text,
   raw events, file paths, tokens, or model replies. Failures are closed codes
   (`invalid_arguments`, `metric_not_found`, `unknown_tool`, …).
2. **Minimal MCP transport, no SDK.** `interfaces/mcp/server.py` implements
   JSON-RPC 2.0 over newline-delimited stdio: `initialize` (tools capability
   only), `ping`, `tools/list`, `tools/call` (text + `structuredContent`),
   empty `resources/list` / `prompts/list`, everything else "method not
   found"; messages are size-bounded, notifications are ignored, parse errors
   are answered and skipped. There is no network listener and no filesystem
   surface; the process opens the same private database the dashboard uses.
3. **Explicit context-egress acknowledgement.** `prompt-enhancer mcp` refuses
   to serve (exit 2, notice on stderr) unless started with
   `--acknowledge-context-egress` or
   `PROMPT_ENHANCER_MCP_ACKNOWLEDGE_CONTEXT_EGRESS=1`. `prompt-enhancer
   mcp-config` prints the Claude Code and Codex configuration snippets that
   include the flag; the app writes no agent configuration itself.
4. **Unknown stays unknown.** The surface repeats the repository rule in its
   `explain_metric` reading guide and in the server's `instructions`:
   unknown is never zero, objective evidence outranks model judgments, and
   model judgments are not metric values.

## Consequences

- A person can ask their coding agent "how did my sessions go this month" and
  get counts, metric states and calibration progress without the agent ever
  seeing a transcript; what the agent does with those numbers is governed by
  that agent's provider, which is exactly what the acknowledgement says.
- Any new tool must be added to the allowlist with a bounded input model and
  a test that its output keys are content-free; there is no generic query.
- If the protocol version a client needs diverges, the server's
  `initialize` reply is the single place to negotiate; the tool set does not
  depend on it.

## Addendum (2026-08-19): the one text-accepting tool

ADR 0015 adds `check_prompt` to this surface. It is the only tool that accepts
text: the prompt the agent already holds (and, optionally, the earlier turns).
The text is analysed locally, only metrics are stored, and what comes back is
commentary about that prompt - which enters the agent's context exactly as the
prompt itself already has. The read tools are unchanged; there is still no
generic query and no transcript access. When the dashboard server is running
the MCP process forwards the check to it so the active local model's commentary
is included; otherwise the deterministic cues are returned alone.
