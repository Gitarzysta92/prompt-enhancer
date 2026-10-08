# Agent checkpoint 09b — direct-client proof and stable Agent rail

Date: 2026-08-28

## Outcome

The recommended external-agent path is now exercised as direct Streamable HTTP
MCP against the already-running loopback application rather than through a
per-client bridge process. A disposable integration probe uses two independent
HTTP clients, proves that both see the same durable fictional Agent catalog,
then proves that revocation rejects the same credential immediately.

The native Agent layout was also repaired after a 1,268 x 800 walkthrough found
that an expanded runtime card could reduce Projects, Chats, and Agent settings
to a very small scroll strip. Project/chat navigation now owns the flexible
space, Agent settings remains a separate always-reachable control, and the
desktop runtime card is bounded with its own scroll region.

## Direct MCP boundary

- The probe accepts the bearer only from
  `PROMPT_ENHANCER_AGENT_MCP_TOKEN`; it never accepts it on the command line,
  prints it, persists it, or prints response content.
- It validates the exact loopback MCP endpoint, initializes two independent
  clients, and required the exact eleven default tools at this checkpoint.
  Agent-09c later advances the default surface to twelve with `agent_stop`;
  model lifecycle remains absent by default.
- Client one creates one fictional durable project/chat. Client two reads the
  same catalog and validates the content-free `local-agent-orchestration.v8`
  discovery contract.
- The revoked probe requires HTTP 401. An expired or revoked credential cannot
  be treated as an empty catalog or a successful disconnected client.
- The real-listener regression owns a disposable application, exercises the
  active and revoked phases, and confirms listener cleanup.

## Agent layout repair

- `Agent settings` moved out of the project/chat scroll region and into its own
  stable rail row.
- The project/chat rail keeps a meaningful minimum flexible height on short
  desktop windows.
- The desktop Model & context card is capped at 36dvh / 23rem and scrolls its
  own expanded details. Narrow layouts release that cap and stack normally.
- Grid items explicitly permit min-content shrinkage. This fixes the reproduced
  3.3 px overflow at 360 px without clipping controls or weakening the viewport
  assertion.
- Returning users continue to reopen the newest retained chat. The branch
  workflow now waits for retained history readiness instead of redundantly
  reopening the already-selected chat.

## Verification

- Direct MCP/controller integration slice: **77 passed**.
- Focused privacy slice: **28 passed**. The aggregate scanner still reports only
  the previously recorded `docs/checkpoint-agent-02-shell.png`; no exclusion or
  scanner weakening was added.
- Distribution, generated OpenAPI, and release slice: **57 passed**.
- Agent component/layout/runtime/controller slice: **123 passed**.
- Responsive workflow matrix at 360 px and 1,440 px, including main and
  dedicated Agent views: **67 passed**.
- Generated API check and production build passed; **537 modules** were built
  into the packaged dashboard resources.
- The rebuilt native window was reloaded at 1,268 x 783. Projects/Chats, Agent
  settings, the bounded Model & context card, and the retained conversation were
  simultaneously reachable. The host remained at one loopback listener, zero
  `llama-server` processes, and zero terminal-like windows.

## Privacy and authority

All integration data is fictional. No provider credential, configuration,
session, prompt, tool output, account data, or unrelated workspace content was
read. No client configuration was changed. The one-time native credential was
not created because credential creation requires an immediate explicit owner
confirmation; automated tests use only disposable application state.

## Next owner-visible gate

With an explicit confirmation at action time:

1. create one temporary direct MCP connection with model lifecycle disabled;
2. copy its one-time bearer without displaying it;
3. run the active probe from one selected installed client;
4. separately confirm revocation, prove the same bearer receives 401, and clear
   the clipboard/environment value.

After that, the remaining acceptance is one chosen local-model turn and Stop,
one reviewed fictional write/diff, unload, and exact process plus CPU/GPU
cleanup evidence. No commit or push was requested for this checkpoint.
