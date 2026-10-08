# MCP Store checkpoint 05a handoff

## Outcome

The MCP Store can now persist or remove one exact reviewed **remote activation**
after a current guarded compatibility receipt and one native user-presence
confirmation. The activation survives application restart, is idempotent, and
is bound to the exact Registry plan and exact lifecycle preview the owner saw.

Remote activation is deliberately configuration only. It does not install a
package, start a process, retain an endpoint connection, create a persistent
host, admit a tool, call a tool, or grant model authority. Local package
installation remains locked for Store-05b; update, rollback and interrupted-
cleanup reconciliation remain Store-05c.

## Exact plan and lifecycle binding

- The reviewed plan revision now binds hidden execution material as well as the
  public review: endpoint path/query, declared header values, package checksum,
  fixed arguments and transport/variable material.
- The hidden digest and hidden execution values are excluded from API and model
  JSON. Regression tests prove that changing any bound material changes the
  plan revision without leaking it.
- Install and uninstall previews bind action, management record revision, plan
  revision, installation kind and a content-free effect list into one preview
  digest.
- Apply re-fetches and revalidates the Official Registry plan immediately before
  committing the activation. A stale record, stale preview or changed hidden
  Registry material fails before mutation.
- Request IDs are idempotent. A retry returns the retained receipt instead of
  duplicating state.

## Durable state and recovery

- Agent catalog schema 14 adds coherent lifecycle state and bounded content-free
  receipts for planned, installed and cleanup-required records.
- Existing schema-13 plans backfill as planned/not-installed/idle. Older v4,
  v5, v7, v11 and v13 migration fixtures were updated to remove schema-14 child
  tables before replaying their exact historical migration path.
- Remote activation persists its exact installed plan revision and timestamp.
  Uninstall removes only that activation; the reviewed plan, compatibility
  receipt, requirements and project bindings remain available.
- Local-package previews now say that installation is locked. They never claim
  a remote activation and explicitly prove that no package or process changed.

## API and Agent experience

- Private authenticated install/uninstall preview and apply routes expose strict
  contracts. Apply routes require native confirmation and the exact preview
  digest plus expected revision.
- The Agent plan view loads the current preview, renders every bounded effect,
  disables unavailable actions, and transitions between prepared and activated
  states without implying a live connection or usable tool.
- The Store landing page now distinguishes native-confirmed remote activation
  from still-locked local packages, persistent hosts, retained connections and
  tool execution.
- Generated OpenAPI and TypeScript clients match the current schema exactly.

## Validation

- Exact MCP Registry/management/user-presence/OpenAPI gate: **75/75 passed**.
- Expanded Agent MCP, managed lifecycle, guarded-host, schema-migration, Windows
  process/lifecycle, cancellation, OpenAPI and privacy matrix: **401/401
  passed** across 30 backend files.
- Complete frontend suite: **170 files / 2,304 tests passed**. One initial
  Team Analytics timeout under concurrent backend load passed immediately in
  isolation, then passed five consecutive repetitions; the complete isolated
  frontend rerun was green.
- Post-live-copy focused reruns: MCP Store **15/15 passed** and the Agent settings
  integration case passed. Strict TypeScript compilation passed.
- Generated API drift, Python compilation, repository privacy scan and
  `git diff --check` passed.
- Production TypeScript/Vite build passed with **559 modules**. Vite retains the
  existing advisory for the approximately 507 kB minified Agent page; this is a
  later bundle-budget item, not a failed correctness gate.
- No real credential, owner workspace content, third-party MCP package, remote
  compatibility probe, endpoint connection, tool schema/result or tool call was
  used in this slice. Tests use reserved synthetic fixtures.

## Live reload and runtime inventory

- The protected native Agent was closed through its own quit confirmation and
  relaunched through the console-free GUI entry point; no force-kill or duplicate
  launcher was used.
- The live Store loaded **24** Official Registry entries. The corrected remote-
  activation/local-package boundary is visible and browser warning/error count
  is zero.
- The existing localhost browser tab is left open on **Agent settings → MCP
  Store** for owner review.
- Final census: one Prompt Enhancer window, one listener on
  `127.0.0.1:8765`, none on 8766, zero console processes in the owned tree,
  zero known local-model processes and zero known local-model GPU compute
  contexts. Other unrelated applications currently own GPU contexts, so no
  system-wide zero-GPU claim is made.

## Owner click checklist

When convenient:

1. In **Agent settings → MCP Store**, confirm the landing copy says remote
   activation requires exact review, compatibility and native confirmation,
   while local packages/hosts/connections/tools remain locked.
2. Open a fixed-HTTPS remote option, review it, and save its setup plan. Confirm
   the catalog tile itself never installs or grants authority.
3. Run **Check compatibility** only for a disposable endpoint you recognize.
   Confirm the receipt says the connection closed and no tool was called.
4. Review **Activate remote plan**. Its exact effect list must say: save only
   this reviewed activation; no package change; no process; no retained
   connection; no tool authority.
5. Approve once, reload, and confirm the activated record survives. Then review
   and approve **Remove remote activation**; confirm the durable plan and probe
   remain while activation is removed.
6. Open a local-package plan and confirm it says the isolated installer is
   locked until Store-05b and does not offer an install action.

No valuable credential or production endpoint is required for this review.

## Exact next checkpoint

**Store-05b — isolated local package staging and install verification.** Add an
application-owned package root, integrity/license/runtime preflight, bounded
download/staging, atomic publication, console-free owned stdio host verification,
exact native-confirmed install preview, idempotent receipts and truthful cleanup
state. Installation will still not admit tools to an Agent project; that remains
Store-06.
