# Agent checkpoint 09e — idempotency-bound external chat fork

Date: 2026-08-28

## Outcome

External Codex-, Claude-, and MCP-compatible controllers now have a dedicated
`agent_fork` tool for one exact retained Agent history prefix. The previous
low-level `agent_invoke` composition path is refused for
`fork_retained_session`, so a caller cannot bypass the fork-specific identity,
revision, authorization, idempotency, lineage, or authority-copy rules.

The default MCP contract advances to `prompt-enhancer-agent-mcp.v10` and now
advertises exactly fourteen tools. Model lifecycle remains absent unless it is
enabled for the exact scoped connection.

## Fork contract

- The request requires exact source project and chat identities, exact current
  catalog and history revisions, a caller-owned 32-hex request ID, and literal
  `mutation_authorized: true`.
- Optional destination project, completed-turn event sequence, and title are
  part of the immutable request-ID binding.
- A trusted 4xx response is not retried. A transport-ambiguous or
  schema-invalid first response may receive exactly one byte-identical retry
  with the same request ID. A replacement key is never generated.
- A valid first replay is reported as `idempotent_replay`; a valid response
  after ambiguity is reported as `forked_reconciled`; two ambiguous responses
  remain `fork_uncertain`.
- The strict result requires exact source/destination lineage, a different
  durable child identity, and retained conversation availability.
- Approvals, mutation authority, pending tool state, staged attachments, and
  artifacts must each be reported as not copied. Any mismatch fails closed.

## Verification

- Focused controller, MCP, disposable-loopback integration, and direct-client
  probe slice: **92 passed**.
- Expanded controller CLI/HTTP, MCP authentication/connections/packaging,
  orchestration, durable-fork concurrency, artifact/attachment copy,
  cancellation, release-hardening, and privacy-canary slice: **216 passed**.
- Covered a new fork, existing-key replay, normalized titles, exact request
  bodies, one bounded ambiguous retry, two-response uncertainty, trusted 4xx
  no-retry, wrong child/source/destination/revision/branch lineage, same-child
  identity, and a false authority-copy claim.
- A production controller lifecycle opened and used a fictional durable chat,
  closed and safely resumed it, then forked its retained history and verified
  exact lineage with no copied protected authority.
- Two independent direct HTTP MCP clients exercised the fourteen-tool surface.
  The first created a fictional child; the second repeated the exact request
  and received `idempotent_replay` with the same child identity.
- Python compilation, the 512-character MCP-instruction cap, exact v10 tool
  count/order, and whitespace checks passed. The only test warning was the
  repository's existing Starlette/httpx deprecation notice.
- The aggregate privacy scanner passed two of three checks and reproduced only
  the previously recorded `docs/checkpoint-agent-02-shell.png` binary finding;
  no scanner rule or exclusion was changed.
- A graceful native close and reload reopened exactly one Agent workspace,
  retained the fictional durable chat, exposed its Resume and Fork controls,
  and showed the model stopped. The final host snapshot had one loopback
  listener owned by `pythonw`, zero `llama-server` processes, and zero visible
  terminal windows.

## Privacy and process boundary

All test projects, chats, paths, events, and credentials were disposable
fictional fixtures. No provider session, prompt, tool output, credential,
configuration, or unrelated home content was read. No model was loaded, no
GPU/VRAM state was touched, no provider configuration was changed, and no
application, shell, bridge, or visible terminal was launched by the MCP path.

## Remaining work and owner gates

The next code-only external-orchestration gap is a dedicated bounded retained-
history export tool. Real installed-client and model-backed acceptance remain
deliberately owner-gated:

1. explicitly authorize creation of one temporary scoped direct MCP
   credential and probe one selected installed client;
2. separately authorize revocation and prove the same bearer receives 401;
3. choose one installed local model and placement, run one real turn and Stop,
   review one fictional file write/diff, unload, and verify exact process plus
   CPU/GPU cleanup evidence.

No commit or push was requested.

> Historical note: Agent-09f subsequently advances the default MCP contract to
> v11 with fifteen tools by adding the dedicated exact-revision path-free
> `agent_export` action. The v10/fourteen-tool statements above remain the
> exact evidence recorded at this checkpoint.
