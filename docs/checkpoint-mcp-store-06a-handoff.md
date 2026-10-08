# MCP Store checkpoint 06a handoff

Date: 2026-08-30
Status: implementation and automated/live gates complete; owner review pending
Next milestone: Store-06b remains locked until explicit owner approval

## Outcome

Prompt Enhancer can now retain and review the exact tool contracts reported by
one bounded MCP compatibility probe, then save an exact per-project tool
allowlist. This does **not** start a persistent MCP host, route a tool to a
model, or execute a tool call. Installation, tool review, project admission,
host authority, and call approval remain separate states.

## Completed behavior

- A successful remote or local compatibility probe creates one immutable
  reviewed-tool snapshot containing bounded names, titles, descriptions, exact
  input/output schemas, schema and contract digests, and deterministic
  collision-checked model aliases.
- Local snapshots bind the exact managed plan, installed tree digest, and
  installed manifest digest. Remote snapshots cannot claim local package
  evidence. Backend and browser parsers independently reject a mismatch.
- Exact canonical schemas remain local validation and drift evidence. A second,
  recomputed model-facing projection removes descriptions, defaults, examples,
  titles, comments, external references, and other prompt-bearing metadata.
- Tool metadata rejects control characters, unsupported explicit JSON Schema
  dialects, external references, duplicate identities, alias collisions, schema
  bombs, excessive depth/nodes/bytes, and excessive aggregate metadata.
- An authenticated private/no-store read route returns the current exact
  snapshot. It is read-only and does not ask for native effect confirmation.
- A project binding now saves an allowlist of exact tool IDs for the current
  snapshot, together with all inferred coarse permissions. The mutation is
  revision-checked, idempotent, native-confirmed, and project-scoped.
- Any new tool snapshot invalidates prior project admissions. A stale snapshot,
  stale tool ID, partial permission grant, disabled binding, or cross-project
  attempt fails closed.
- Install, update, rollback, uninstall, and recovery flows publish, reactivate,
  or revoke snapshots at the same durable generation boundary. Tool routing
  remains explicitly inactive throughout Store-06a.
- The Agent MCP Store view now shows reviewed tools, exact schema details, and
  separate project-admission checkboxes with truthful stopped/inactive copy.

## Persistence and privacy evidence

- Agent catalog schema 18 adds immutable reviewed snapshots, exact reviewed
  tools, current-snapshot state, and per-project tool admission records.
- Schema 19 expands the already bounded local-update target-result journal to
  4 MiB so an exact reviewed contract can be recovered instead of silently
  exceeding the old 32 KiB record limit.
- Schema 20 adds the local source manifest digest and safely backfills current
  installed and retained rollback generations from existing content-free
  package evidence.
- Public server summaries omit exact tool contracts; the dedicated tool route
  is authenticated and private/no-store. Tool contracts remain local sensitive
  derived data and are excluded from logs and errors.
- Durable records contain no tool results, arguments, credentials, endpoints,
  commands, workspace paths, prompts, transcripts, or model content.
- Probes still close their connection/process tree and request no tool result.
  No persistent MCP host, model runtime, GPU worker, or terminal window is
  started by this checkpoint.

## Automated gates

- Focused backend MCP host, Registry, package lifecycle, durable management,
  migration, HTTP, and OpenAPI matrix: **139 passed**.
- Focused frontend contract, transport, connection, and MCP Store UI matrix:
  **122 passed across 9 files**.
- Complete frontend regression: **2,323 passed across 170 files**.
- Complete backend regression: **4,824 passed; 9 platform-symlink cases
  skipped**.
- OpenAPI regeneration/check, generated TypeScript consistency, strict
  TypeScript compilation, and Python compilation: passed.
- Production build (**559 modules**), privacy scan, and final diff check: passed.
  The existing Agent chunk-size advisory remains a later performance-budget
  item.

## Live runtime state

- The prior protected Agent owner closed through its normal quit confirmation;
  its exact listener exited before replacement.
- The rebuilt console-free Agent launcher owns exactly one listener on
  `127.0.0.1:8765`. Its seven-process tree contains only `pythonw` and WebView
  children: zero terminal processes and zero local-model workers.
- The production Agent route reloaded successfully. Agent settings opened the
  MCP Store, which loaded **24 live Official MCP Registry entries** with search,
  distribution filters, review controls, and truthful no-authority copy.
- Browser warning/error diagnostics were empty. No managed plan existed in the
  live catalog, so the smoke test did not create user state merely to populate
  the reviewed-tools section; that exact UI is covered by the strict component
  suite and remains in the owner click checklist.
- The MCP Store tab is left open for owner review. No model, MCP host, or GPU
  inference runtime was started.

## Deliberately still locked

- Store-06b: app-run MCP host start/stop, health supervision, crash recovery,
  exact re-handshake, and shutdown ownership.
- Store-06c: actual Agent tool routing, per-call native approval, argument/result
  validation, cancellation, receipts, and chat activity cards.
- Store-06d: vault-backed user configuration, remote templates, and reviewed
  MCPB `user_config` breadth.
- Store-06e: final management/chat layout, responsive/accessibility acceptance,
  and the owner walkthrough.
- Store-07 and later: adversarial end-to-end runtime acceptance and additional
  documented MCP portal adapters. The discovery source remains the Official MCP
  Registry; a listing is never treated as security approval.

## Owner click checklist

After the protected app reload:

1. Open **Agent settings → MCP Store** and select one already managed synthetic
   or test server.
2. Confirm **Reviewed tools** shows tool count, exact names, and expandable
   input/output schema evidence without claiming the host is running.
3. In **Projects**, enable a project, select exact tools, and save the admission;
   confirm the row says allowed/stopped or otherwise clearly inactive.
4. Change or refresh the reviewed tool generation in a later test walkthrough
   and confirm the prior selections return to **Review required**.
5. Confirm no chat tool is callable yet; that is intentionally Store-06c, not a
   missing Store-06a action.

## Next checkpoint

Store-06b adds an app-run-only supervisor for the already supported fixed,
configuration-free MCP subset. It must re-verify exact snapshots before routing,
use hidden atomically owned processes for local servers, retain no execution
authority across app restart, and pass crash/Stop/shutdown/process-census tests
with zero terminal windows. It adds no tool-call route.
