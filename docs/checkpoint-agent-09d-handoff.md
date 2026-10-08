# Agent checkpoint 09d — revision-bound retained-chat resume

Date: 2026-08-28

## Outcome

External Codex-, Claude-, and MCP-compatible controllers now have a dedicated
`agent_resume` tool for one exact retained Agent chat. The previous low-level
`agent_invoke` composition path is refused for `resume_retained_session`, so a
caller cannot bypass the resume-specific revision, identity, authorization,
at-most-once, or protected-authority rules.

The default MCP contract advances to `prompt-enhancer-agent-mcp.v9` and now
advertises exactly thirteen tools. Model lifecycle remains absent unless it is
enabled for the exact scoped connection.

## Resume contract

- The request requires exact project and chat identities, exact current
  catalog and history revisions, and literal `mutation_authorized: true`.
- Stale, archived, metadata-only, unavailable, and cross-project records fail
  before any resume request is sent.
- An exact chat that is already live returns `already_live` without mutation.
- A retained chat is resumed at most once. A transport-ambiguous or
  schema-invalid response is never retried.
- One read-only exact-live-chat reconciliation distinguishes `accepted`,
  `reconciled`, `uncertain`, and `not_attempted` mutation states.
- A successful recovered session must report `recovered: true`,
  `authority_revalidated: false`, and write, command, and web permissions all
  disabled. Native review is required before protected authority can return.
- Cleanup uncertainty remains explicit and cannot be reported as a clean
  resume.

## Verification

- Focused controller, MCP, disposable-loopback integration, and direct-client
  probe slice: **80 passed**.
- Expanded controller CLI/HTTP, MCP authentication/connections/packaging,
  orchestration, cancellation, release-hardening, and privacy-canary slice:
  **174 passed**.
- Covered successful resume, already-live idempotence, stale catalog/history
  revisions, archived/history-unavailable records, cross-project identity,
  literal-authority rejection, generic-invocation bypass rejection,
  transport-ambiguous reconciliation, unreconciled uncertainty, and unsafe
  recovered-authority rejection.
- A production controller lifecycle opened a fictional durable chat, completed
  one bounded synthetic turn, closed the live session, reread exact durable
  revisions, resumed it, and verified recovered state with no restored
  protected authority.
- Two independent direct HTTP MCP clients exercised the thirteen-tool surface;
  the second client observed and resumed the first client's fictional durable
  chat after it was closed.
- Python compilation, the 512-character MCP-instruction cap, and whitespace
  checks passed. The optional Ruff executable is not installed in this
  workspace; no dependency was added merely to run it. The only test warning
  was the repository's existing Starlette/httpx deprecation notice.
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
application, shell, bridge, or visible terminal was launched by the MCP path.

## Remaining owner gates

This checkpoint does not claim the real installed-client handshake or a
model-backed turn. Those remain deliberately owner-gated:

1. explicitly authorize creation of one temporary scoped direct MCP
   credential and probe one selected installed client;
2. separately authorize revocation and prove the same bearer receives 401;
3. choose one installed local model and placement, run one real turn and Stop,
   review one fictional file write/diff, unload, and verify exact process plus
   CPU/GPU cleanup evidence.

No commit or push was requested.

> Historical note: Agent-09e subsequently advances the default MCP contract to
> v10 with fourteen tools by adding the dedicated idempotency-bound
> `agent_fork` action. The v9/thirteen-tool statements above remain the exact
> evidence recorded at this checkpoint.
