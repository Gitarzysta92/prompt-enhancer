# Agent checkpoint 09c — evidence-bound external turn Stop

Date: 2026-08-28

## Outcome

External Codex-, Claude-, and MCP-compatible controllers now have a dedicated
`agent_stop` tool for one exact live Agent chat. The previous low-level
`agent_invoke` composition path is refused for `stop_turn`, so a caller cannot
bypass the Stop-specific identity, authorization, bounded-drain, and cleanup
rules.

The default MCP contract advances to `prompt-enhancer-agent-mcp.v8` and now
advertises exactly twelve tools. Model lifecycle remains absent unless it is
enabled for the exact scoped connection.

## Stop contract

- The request requires an exact 32-hex chat identity, an exclusive event
  cursor, literal `mutation_authorized: true`, and a drain timeout from 0.1 to
  30 seconds.
- A clean idle chat is observed without mutation. A chat already stopping is
  drained without sending a duplicate Stop.
- For any other active state, Stop is attempted at most once. Transport-
  ambiguous or schema-invalid delivery is never retried.
- Read-only event reconciliation distinguishes `accepted`, `reconciled`,
  `uncertain`, and `not_attempted` request states.
- `stopped` and `already_settled` require a complete cursor, no pending
  approval, no running/closing/stopping state, and no cleanup quarantine.
- Missing terminal proof remains `stop_uncertain` or `incomplete`;
  command-cleanup quarantine remains `cleanup_unconfirmed`.

## Verification

- Focused controller, MCP, disposable-loopback integration, and direct-client
  probe slice: **74 passed**.
- Expanded controller CLI/HTTP, MCP authentication/connections/packaging,
  orchestration, cancellation, release-hardening, and privacy-canary slice:
  **168 passed**.
- Covered active Stop, idle observation, already-stopping reconciliation,
  future-cursor rejection, cleanup quarantine, accepted cleanup drain,
  transport-ambiguous reconciliation, uncertain timeout, literal-authority
  rejection, and generic-invocation bypass rejection.
- Two independent direct HTTP MCP clients saw the exact twelve-tool surface.
  One client opened a fictional durable chat; the other invoked `agent_stop`
  on its idle state and received `already_settled` with `not_attempted`, proving
  the direct tool path without introducing a mutation.
- Python compilation and whitespace checks passed. The only test warning was
  the repository's existing Starlette/httpx deprecation notice.
- The aggregate privacy scanner passed two of three checks and reproduced only
  the previously recorded `docs/checkpoint-agent-02-shell.png` binary finding;
  no scanner rule or exclusion was changed.
- A graceful native close and reload reopened exactly one Agent workspace,
  retained the fictional durable chat, and showed the model stopped. The final
  host snapshot had one loopback listener owned by `pythonw`, zero
  `llama-server` processes, and zero visible terminal windows.

## Privacy and process boundary

All test projects, chats, paths, events, and credentials were disposable
fictional fixtures. No provider session, prompt, tool output, credential,
configuration, or unrelated home content was read. No model was loaded, no
GPU/VRAM state was touched, no provider configuration was changed, and no
application, shell, bridge, or visible terminal was launched by this slice.

## Remaining owner gates

This checkpoint does not claim the real installed-client handshake or a
model-backed Stop. Those remain deliberately owner-gated:

1. explicitly authorize creation of one temporary scoped direct MCP
   credential and probe one selected installed client;
2. separately authorize revocation and prove the same bearer receives 401;
3. choose one installed local model and placement, run one real turn and Stop,
   review one fictional file write/diff, unload, and verify exact process plus
   CPU/GPU cleanup evidence.

No commit or push was requested.

> Historical note: Agent-09d subsequently advances the default MCP contract to
> v9 with thirteen tools by adding the dedicated revision-bound
> `agent_resume` action. The v8/twelve-tool statements above remain the exact
> evidence recorded at this checkpoint.
