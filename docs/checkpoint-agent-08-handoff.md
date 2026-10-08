# Agent-08a handoff: complete loopback controller contract

Date: 2026-08-27
Status: implementation and synthetic automated/browser verification complete; native owner reload remains deferred

## Outcome

The local Agent now publishes one versioned, provider-neutral discovery contract
for a Codex, Claude, or other local controller. The manifest exactly covers the
implemented Agent HTTP surface instead of advertising only a small subset of
routes. It also describes the finite event-polling loop, the runtime operations
needed to prepare a model, and every operation that must remain behind native
user presence.

The Agent page exposes this boundary in a compact **Connections & controller
API** card. It reports readiness and route counts, identifies the discovery
endpoint and OpenAPI document, and explains that the bearer token is supplied by
the native secret store and is never displayed or retained by the card.

## Implemented boundary

- `local-agent-orchestration.v4` declares **52 Agent routes** and **5 local
  runtime routes**. Exact OpenAPI/manifest parity is tested.
- The contract includes durable project and chat creation, browsing, update,
  close, retained-history resume, and deletion; bounded workspace reads;
  attachments and artifacts; event polling; message submission and
  cancellation; reviewed change diffs; all file/directory/transaction preview
  and apply pairs; and local runtime start, status, cancel, stop, and unload.
- Binary artifact and attachment responses are represented truthfully instead
  of being described as JSON.
- Ten protected routes are marked native-only: recovered-authority validation,
  protected-action approval, reviewed artifact capture, and the seven workspace
  apply operations. A bearer controller may prepare and inspect these actions,
  but it cannot manufacture user presence or apply them itself.
- Workspace reads remain bounded to the admitted root, and path reparse points
  fail closed. Controller mutation is explicitly preview-only until a native
  owner applies the reviewed operation.
- The finite-controller protocol requires one send only while idle, monotonic
  event cursors, no automatic retry after an ambiguous submission, and explicit
  terminal conditions.
- The frontend validates the entire manifest at runtime. It rejects downgraded,
  incomplete, duplicate, remotely addressed, path-unsafe, internally
  inconsistent, or token-disclosing contracts.
- Production synthetic transport reports the controller surface as unavailable
  instead of inventing a ready state. A dev-only fixture supplies a complete
  synthetic v4 manifest for visual acceptance tests.

## Correctness repairs found during validation

1. The previous manifest covered only a subset of routes that the Agent UI and
   backend already used. The contract now matches every `/v1/agent` OpenAPI
   route exactly and additionally lists the five required runtime routes.
2. The earlier boundary did not distinguish binary content responses or list
   the full set of native gates. Response and access declarations now agree
   with the implemented routes.
3. The controller lifecycle test proves that bearer-only access can create,
   chat, poll, inspect, preview, close, resume, and delete, while a workspace
   apply fails with 403 and leaves the filesystem unchanged.
4. Broad backend testing found an old synthetic cancellation harness that
   accidentally entered a newer runtime context-preflight path it did not
   model. The fixture now disables that unrelated capability explicitly; all
   cancellation ownership assertions still run.
5. Full parallel frontend testing exposed a pre-existing race in a workspace
   test that clicked **New folder** while asynchronous tree loading still kept
   the button disabled. The test now waits for the real enabled state before
   interacting; no product guard or assertion was relaxed.
6. Rendered narrow and desktop checks found the controller card was technically
   present but below a less important connections panel. It now appears first
   inside the connections section and remains reachable without displacing the
   chat composer or runtime controls.

## Verification receipts

- The relevant backend Agent/runtime/workspace/OpenAPI suite passed **801 tests**
  with **1 Windows symlink-privilege skip**.
- The focused orchestration and OpenAPI slice passed **10 tests**. The complete
  synthetic bearer-controller lifecycle and exact route-parity checks are
  included.
- The complete frontend gate passed **1,995 tests across 149 files**.
- The focused frontend contract, transport, Agent, and workspace slice passed
  **270 tests**.
- The complete Playwright suite passed **113 tests**, including controller-card
  acceptance at 360 px and 1,440 px widths.
- The production TypeScript/Vite build passed with **527 modules transformed**.
- Strict TypeScript checking, generated-API consistency, and OpenAPI export
  validation passed.
- Rendered loopback inspection confirmed the ready state, 52/5/10 counts,
  discovery endpoint, bearer-placeholder disclosure, native safety boundary,
  retained composer visibility, and no horizontal overflow.
- `git diff --check` reported no whitespace errors. Windows line-ending notices
  remain informational.
- The repository privacy scan still has one known pre-existing untracked binary
  finding. This checkpoint added no further finding, and the blocker was not
  deleted or bypassed.
- Zero Prompt Enhancer, Agent, or `llama-server` processes and zero relevant GPU
  allocations remained after validation. Ports 8765 and 8766 were closed. The
  existing synthetic Vite fixture remained bound only to 127.0.0.1:4173; no
  native app, local model, GPU job, Claude CLI, or extra server was launched.

## Owner checklist for the later native reload

1. Reload a matching frontend/backend build and open **Agent -> Connections &
   controller API**. Confirm it reports v4, 52 Agent routes, 5 runtime routes,
   and 10 native gates.
2. Let a local controller discover `GET /v1/agent/orchestration` using the secret
   supplied by the native application. Never paste or log that token in a chat.
3. In a synthetic workspace, create a durable project and local-history chat,
   send one message, and advance the event cursor until the declared terminal
   condition.
4. Preview one synthetic file operation through the controller. Confirm the
   bearer-only apply attempt receives 403 and that only the native reviewed
   approval can change the workspace.
5. Close and reopen the chat. Confirm retained history remains available while
   recovered sessions stay read-only until native authority is revalidated.
6. Stop or unload any real model used for this check and confirm its process and
   VRAM allocation are gone.

These native checks are deliberately not marked passed. They require the owner
reload and optional real-model use that were avoided after the earlier
terminal-window cascade.

## Next checkpoint

The next correct slice is **Agent-08b — bounded controller client and setup
workflow**. It should add a provider-neutral local client/CLI example that reads
the v4 manifest, performs the finite send/poll/stop loop, surfaces native gates
without attempting to approve them, redacts logs by default, and proves the
complete lifecycle against synthetic fixtures. It must not spawn Codex, Claude,
the native app, or a model by itself.

After Agent-08b, the capability list can continue with owner-visible refinements
such as session fork/branch/export and richer provider adapters, each kept as a
separate tested checkpoint.
