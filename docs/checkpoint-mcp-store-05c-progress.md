# MCP Store checkpoint 05c handoff

Date: 2026-08-30
Status: implementation and automated/live gates complete; owner review pending
Next milestone: Store-06 remains locked until explicit approval

## Completed behavior

- A verified local MCPB package can be removed only when its installed tree
  still matches the retained digest.
- Removal is two-phase and journaled: the exact tree moves atomically into an
  application-owned quarantine before database state changes, then the
  quarantined tree is removed. No shell, package process, terminal, connection,
  tool call, persistent host, or model authority is created.
- Clean preparation failures restore the installed state and remain retryable.
  Ambiguous, drifted, interrupted, or unconfirmed states become an explicit
  `cleanup_required` record instead of being reported as removed.
- Restart reconciliation converts crash-left reserved or prepared uninstall
  journals into an owner-visible recovery state.
- The Agent MCP plan card now exposes an exact recovery preview and a native-
  confirmed **Complete interrupted removal** action. Recovery accepts a
  digest-matching installed tree, digest-matching quarantined tree, or an
  already-absent tree after a crash. The journal is cleared only after absence
  is verified.
- Recovery receipts distinguish whether the current attempt changed the
  filesystem from an idempotent retry that only finalized durable state.
- Local install/uninstall lifecycle receipts are versioned and strictly bind
  the installation kind and truthful package/process effects.
- Update resolution treats the Official Registry `latest` alias only as a
  discovery pointer, then re-fetches and binds one exact version and plan
  revision. Ordering and semantic-version guesses are not authoritative.
- Updates are admitted only for one configuration-free, checksum-declared MCPB
  target with unchanged permissions. Metadata drift, configuration migration,
  permission change, ambiguity, or an existing rollback generation fail closed.
- The exact target is checksum-verified, staged in isolation, probed by one
  hidden bounded process, and published only after its full owned process tree
  is verified stopped.
- Atomic publication retains the prior verified package as the sole rollback
  generation. Rollback verifies and exchanges both generations without running
  package code, retaining the superseded generation so rollback is reversible.
- Explicit retained-generation cleanup verifies, quarantines, and removes only
  that generation while leaving the current package installed.
- Interrupted update, rollback, and rollback cleanup now share an exact
  journal-bound recovery flow. Recovery starts no package process and clears
  the blocked state only after filesystem verification.
- The Agent card exposes update, rollback, retained-generation cleanup, and
  interrupted-operation recovery with strict native-confirmation gates.

## Safety and persistence evidence

- Agent catalog schema 17 adds bounded operation, update-target,
  rollback-generation, atomic-swap, and recovery-attempt records. They store
  exact identities, digests, fixed state/effect codes, revisions, and
  content-free probe evidence, but no paths, commands, package content, tool
  names/schemas/results, credentials, prompts, transcripts, or model content.
- Install, update, rollback, cleanup, uninstall, and recovery request IDs are
  conflict-checked and replay-safe. Recovery IDs are durably reserved before
  filesystem mutation.
- A database failure after filesystem removal leaves the recovery journal in
  place. Retrying observes the package as already absent and can finish the
  database transition without claiming another file change.
- Historical migration replay now drops the dependent operation journal before
  its package table.
- Recovery and lifecycle endpoints are private/no-store. Mutating endpoints
  require native user-presence confirmation.

## Automated gates

- Backend installer, durable management, restart, HTTP, migration, idempotency,
  compensation, and failure matrix: **66 passed**.
- Strict frontend response parser, authenticated/native-confirmed transport,
  and Agent MCP Store UI matrix: **55 passed**.
- Complete frontend regression: **2,319 passed; one unrelated team-analytics
  test hit its 5-second timeout under full-suite load**. Its isolated rerun was
  **18/18 passed in 3.20 seconds**; no unrelated code was changed to hide it.
- OpenAPI export and exact managed-route/schema assertions: **6 passed**.
- Generated TypeScript API consistency, TypeScript compilation, and production
  Vite build: passed with **559 modules**. The existing Agent chunk-size
  advisory remains a later performance-budget item.
- Python compilation, repository privacy scan, and `git diff --check`: passed.
  Line-ending notices are existing Windows checkout normalization warnings, not
  whitespace errors.

## Live runtime state

- The previous protected Agent owner displayed its normal quit confirmation;
  after confirmation, its exact listener and owner process both exited.
- One hidden native Agent launcher now owns exactly one
  `127.0.0.1:8765` listener and reports `health_status=ok`.
- Its tree contains the native Python owner plus WebView children only: zero
  terminal processes and zero local-model workers. The only GPU-associated
  child is WebView rendering; no model runtime or MCP host was started.
- The refreshed Agent page loaded its durable synthetic project/chat, opened
  Agent settings, and loaded **24 live Official MCP Registry entries**. The
  browser console reported **zero warnings or errors**.
- The MCP Store tab is left open for owner review.

## Deliberately still locked

Store-05c manages package generations but grants no runtime tool authority.
Persistent hosting, project-scoped enable/disable, tool admission,
least-privilege routing, call approvals, health supervision, and observable
tool execution belong to Store-06.

## Owner click checklist

1. In **Agent settings → MCP Store**, confirm the catalog tiles, search, and
   Local packages / Remote servers filters feel clear.
2. Open **Review safety & plan** on any tile and verify that setup, permissions,
   risks, and the no-authority boundary are understandable.
3. If a previously installed synthetic/test MCPB plan is present later, inspect
   **Registry latest update** and its exact current/target versions and effects.
4. After an update, inspect **Retained rollback generation** and the separate
   **Roll back** and **Remove retained generation** actions.
5. Report any copy, density, hierarchy, icon, or interaction problem; owner
   review can remain pending without invalidating the automated checkpoint.

## Next

Proposed next checkpoint: **Store-06 — project-scoped MCP admission and safe
tool routing**. It begins only after explicit approval, preserving this handoff
as the stable rollback/review point.
