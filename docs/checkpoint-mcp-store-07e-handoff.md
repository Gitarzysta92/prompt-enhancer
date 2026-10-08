# MCP Store checkpoint 07e handoff

Date: 2026-08-31
Status: automated implementation complete; owner protected-action review pending
Runtime effect of the automated gate: synthetic vault references, clients,
projects, chats, calls, receipts and canaries plus a read-only reload of the
loopback application. No real credential, private provider data, MCP package or
host, local model, protected action or GPU workload was used.

## Outcome

Managed MCP configuration and per-call authority are now bound to the exact
reviewed project, plan revision, field, host, chat, client and call. Missing,
replaced, revoked or stale vault references fail closed. Concurrent Stop,
revocation, switch, shutdown and late-result races cannot resurrect authority,
and secret-bearing hostile failures leave only allowlisted, content-free
evidence in HTTP, logs, ordinary SQLite state, retained history, exports and UI.

## Changed

- Runtime preparation resolves exact vault references only at the protected
  lifecycle boundary and signs the reviewed scope. Preparation claims and call
  receipts are one-use, expiring and revision-bound; plaintext is not retained.
- Database schema 29 adds the relational and immutable bindings required to
  reject cross-project, cross-chat, cross-client, wrong-host and wrong-call
  substitution, including after reconstruction.
- Project, chat and controller-client projections now enforce the same scope at
  admission, approval, dispatch, settlement, Stop and retained-history/export
  boundaries. Unknown identifiers remain a bounded non-oracle result.
- Revocation, replacement, project/chat switching, host Stop and shutdown win
  over late preparation or completion. Cleanup uncertainty remains blocking,
  and one closer owns settlement in Stop races.
- The managed-runtime frontend accepts only a closed set of safe error codes and
  maps them to fixed recovery text. Hostile valid-shaped codes, diagnostics,
  arguments, values and results cannot become rendered error detail.
- Controller discovery is now `local-agent-orchestration.v21`: **68 Agent
  routes**, **5 runtime routes** and **73 total routes**, including the exact
  project-managed-runtime projection.

## Regressions repaired during the gate

- Built-in local Agent tools had accidentally inherited the managed-MCP
  `event_call_id` requirement. The identifier is optional for built-ins and
  remains mandatory and fail-closed for managed MCP dispatch.
- Bootstrap previously attached the managed runtime after constructing Agent
  sessions. It now injects the runtime during service construction, eliminating
  a late authority-binding interval.
- An older attachment fixture omitted the current routing and omitted-feature
  columns; it now models the supported schema accurately.
- Strict OpenAPI discovery exposed one missing runtime route and advanced the
  contract from v20 to v21. Python, TypeScript, generated OpenAPI, support copy
  and documentation now agree.
- A privacy assertion treated an unrelated numeric disk-byte count as a secret
  canary. It now checks the exact hostile message, URL and token without
  weakening non-disclosure.

## Automated evidence

- Dedicated secret/scope backend matrix: **182 passed**.
- Dedicated safe frontend projection matrix: **29 passed**.
- Change-set and hardening receipts: **21 passed** and **7 passed**.
- Strict controller/manifest backend matrix: **140 passed**; corrected frontend
  contract/controller matrix: **8 passed**.
- Broad diagnostic tail: **3,111 passed, 7 skipped**.
- Authoritative complete backend gate: **5,122 passed, 9 expected Windows
  symlink-capability skips, 0 failed**.
- Authoritative complete frontend gate: **2,582 passed across 178 files**.
- Generated API parity, Python compilation, dependency-lock verification,
  repository privacy scan, whitespace check and production build all passed.
- The production build retains the known non-fatal Agent/PDF chunk-size warning;
  it is recorded for Sweep-01c performance work rather than hidden here.

## Live protected-app evidence

The exact existing listener was stopped only after its loopback, process and
zero-child identity were revalidated. The repository entry point was launched
once with a hidden window and became healthy at
`http://127.0.0.1:8765/agent`.

The retained Agent page reloaded against the new build. The project/chat rail,
stopped shared model card, readiness view, Connections, MCP Store Browse and
Managed views rendered. The official Registry returned **24 loaded tiles**;
browsing initiated no installation, connection, server start, approval or model
action. The live controller card reported v21 with 68 Agent and 5 runtime
routes. Browser evidence ended with **0 console errors** and **0 dialogs**, and
the tab remains on **Agent settings > MCP Store > Browse servers** for review.

## Final process and GPU census

- Exactly **1** listener owns `127.0.0.1:8765`; `/health` returns **HTTP 200**.
- The hidden service tree contains the launcher, one hidden console host and two
  Python service processes; attributable visible windows: **0**.
- Known `llama-server`/`llama-cli` workers: **0**.
- Prompt Enhancer service-tree GPU processes: **0**. System GPU memory was
  **1,521 MiB used / 14,655 MiB free** by unrelated activity; this checkpoint
  makes no claim that the entire GPU was idle.

## Still deliberately locked

- No automation can certify the owner's native picker/confirmation experience,
  a trusted installed MCP package, a real MCP call, real model placement or
  measured model VRAM release. Those remain Acceptance-01 evidence.
- The live Registry success proves the bounded browse surface, not that any
  listing is trustworthy or safe to install. Registry presence is never a
  security verdict.
- Store-07e completes the synthetic adversarial matrix; final migration,
  packaging and connected-journey proof remain Release-01a/01b.

## Owner click-later ledger

1. In the already-open **Agent settings > MCP Store**, switch between **Browse
   servers** and **Managed servers** and confirm both remain clear at the normal
   display scale.
2. Open one tile's details and verify provenance, version, transport,
   compatibility and risk information are understandable before any lifecycle
   button.
3. With one explicitly trusted inert plan, perform the native-reviewed Start
   and one harmless tool call; confirm project, host and tool identity match in
   the preview, activity card and settled receipt.
4. Attempt no second dispatch from the settled approval, then Stop the host and
   confirm pending authority becomes unusable and no delayed success appears.
5. Confirm the host leaves no visible terminal or owned process. A model need
   not be loaded for this MCP-only check.

## Next checkpoint

Acceptance-01 is next. It collects only evidence automation cannot honestly
replace: native confirmation and picker behavior, retained-chat restart, one
trusted inert MCP click-through, one real CPU/GPU-supported model lifecycle,
workspace action and measured process/VRAM cleanup. No broad UI redesign begins
until that owner-gated evidence is separated from implementation defects.
