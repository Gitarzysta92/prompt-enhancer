# Runtime checkpoint 01a handoff

## Outcome

The Models page and Agent runtime card now use the same revision-bound global
runtime coordinator. The Models page no longer starts and stops models through
independent per-alias controls when the coordinator surface is available.

The page presents one app-owned runtime with its requested alias, served alias,
active-request count, cleanup state and coordinator revision. Start, restart,
switch and unload requests carry that exact revision. While any lifecycle
command is pending, every model lifecycle control is disabled, so repeated
clicks or another model card cannot launch an overlapping command.

Only the exact served alias offers **Unload shared runtime**. A served model
registration cannot be removed until it is unloaded, and the reason is visible.
Loading, unloading, active-request draining, cleanup uncertainty and quarantine
have distinct status copy. Runtime failures retain allowlisted, content-free
reason codes instead of collapsing revision conflicts and cleanup failures into
the former generic “runtime missing” message.

The coordinator is also authoritative for chat eligibility. A stale per-model
poll that still says `running` cannot enable the Models-page chat while the
shared coordinator is stopped, loading, unloading, failed or quarantined.

## Correctness boundaries

- The Models page uses coordinator endpoints only when the complete read,
  switch and stop surface is present. The older per-alias transport remains a
  compatibility fallback for older app compositions, not the production path.
- A switch and unload are each sent at most once with the currently displayed
  coordinator revision. An error triggers a read-only reload; it is not retried
  blindly.
- Every model lifecycle and placement control is locked while another local
  mutation, a coordinator transition, active inference or cleanup quarantine is
  present.
- Per-model runtime rows are projected from the authoritative coordinator before
  they reach the chat panel. Only a capability-verified `ready` served alias is
  projected as running.
- The existing backend still owns at most one loopback `llama-server`, refuses a
  switch during active inference, waits for process exit, and fails closed when
  GPU cleanup is unknown.
- Runtime spawn, hardware discovery and runtime-version probes use the Windows
  no-console process flag. This checkpoint adds direct evidence for both probe
  commands; it does not claim atomic Windows descendant ownership yet.
- Placement support/fit truth, actual offload verification, download pause and
  retry, and an owner-approved real CPU/GPU walkthrough remain later Runtime-01
  slices.

## Validation

- Red tests first: **3 lifecycle UI regressions failed** against the legacy
  page, proving uncoordinated start, unload and cleanup-quarantine behavior.
- Models-page suite: **28 tests passed**.
- Focused Models/Agent/runtime/transport matrix: **6 files, 254 tests passed**.
- Full local-model backend suite: **47 tests passed**, including the new
  console-free hardware/version-probe contract.
- Shutdown, cancellation, background-model, Windows-distribution and native
  lifecycle gate: **114 tests passed**.
- Broad local-model, Agent and shared-API frontend gate: **77 files, 1,264 tests
  passed**.
- Production TypeScript/Vite build passed with **559 transformed modules**. The
  existing approximately 523 kB Agent-page chunk warning remains tracked
  performance debt.
- Repository privacy scan and targeted diff whitespace validation passed. Only
  the repository's existing Windows line-ending notices were emitted.
- The protected loopback app reloaded at `/models`. The shared-runtime card
  rendered stopped with no served alias, model cards offered coordinated start,
  the chat stayed inactive, and browser logs were empty.
- Listener census showed only `127.0.0.1:8765` on the application ports and no
  known local-model process. This checkpoint started no model, GPU workload,
  command worker or MCP host.

## Owner review

Use one disposable local model when convenient:

1. Open **Models** and **Agent**. Confirm both show the same shared-runtime
   state, served alias and transition after refresh.
2. Choose **Start shared runtime** once. Confirm every other model lifecycle
   button becomes disabled while it starts and no terminal window appears.
3. Confirm chat remains unavailable during loading and becomes available only
   after the runtime reports ready and its text-capability probe succeeds.
4. Start a slow response. Confirm switch and unload remain blocked while the
   request is active; stopping the response must not itself unload the model.
5. Switch to a second model. Confirm the old process exits before the new model
   loads and there is never more than one served alias.
6. Unload the model. Confirm chats and registrations remain, the model can then
   be removed from the registry, and process/VRAM cleanup completes without a
   visible console.

## Next slice

Runtime-01b will make placement and parameter admission truthful. CPU, GPU and
hybrid choices will be enabled only with explicit support evidence; requested
GPU layers, context, flash-attention/tool-template settings, model metadata and
available accelerator memory will receive coherent validation and reasons.
The UI will distinguish requested placement from verified execution rather than
claiming that a successful text probe proves where every layer ran.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
