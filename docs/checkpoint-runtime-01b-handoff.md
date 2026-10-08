# Runtime checkpoint 01b handoff

## Outcome

Local-model placement is now an explicit, versioned admission decision shared
by the Models page and the Agent runtime card. CPU, full-GPU and split placement
are no longer enabled from a successful text probe or from a model name. The
backend evaluates the registered weight size, verified layer count, requested
context, current free accelerator memory and a conservative safety allowance.
It returns `available`, `blocked` or `recheck_required` with a bounded reason.

The runtime refuses an incoherent request before spawning a process. This
includes a context above verified model metadata, CPU with GPU layers, a
zero-layer split, partial layers presented as full GPU, and split layers above
the admitted limit. When an app-owned accelerator runtime must be replaced,
the decision is conditional until the old process exits, cleanup is confirmed
and hardware evidence is sampled again.

Both interfaces fail closed while live admission is loading or unavailable.
Blocked choices are disabled, an admitted fallback is selected, unsupported
context sizes are disabled, and split layers are bounded. Copy consistently
states that the UI shows a requested placement and preflight estimate; a text
capability probe does not prove physical tensor offload.

## Contract and correctness boundaries

- `local-model-placement.v1` is returned with every model status and by the
  context-specific placement endpoint.
- The contract contains only bounded placement evidence and always reports
  `actual_offload_verified: false`; it cannot inflate a request or a successful
  generation into offload proof.
- Accelerator choices fail closed when current accelerator/free-memory
  evidence, model size or required layer metadata is unavailable.
- CPU remains available when the requested context is within verified model
  metadata. Unknown values remain unknown rather than becoming zero.
- Full-GPU and split estimates include model weights, requested context and
  safety headroom. A split recommendation is a positive bounded layer count.
- A replacement that depends on releasing the current accelerator allocation
  is admitted only after exact owned-runtime cleanup and a fresh preflight.
- Remembered defaults are written only after final admission succeeds.
- The typed OpenAPI contract, strict frontend parser and both production
  transports reject extra or incoherent placement state.

## Additional regression repaired

The broad gate exposed a conversation-notice race: the first event snapshot of
a regenerated branch could erase the successful branch notice. Event-stream
recovery now clears only live-update outage notices. Branch/retry notices stay
visible and no longer carry the unrelated **Retry live updates** action.

## Validation

- Local-model backend suite: **50 tests passed**.
- Runtime, cancellation, shutdown, native-window, single-instance and Windows
  process-hardening matrix: **161 tests passed**.
- OpenAPI export suite: **6 tests passed**; generated TypeScript API drift check
  passed.
- Focused placement, transport, Models and Agent matrix: **5 files, 391 tests
  passed**. The adjacent Models chat panel adds **23 passing tests**.
- Integrated Agent page after the notice repair: **144 tests passed**.
- Full frontend sweep: **171 files, 2,387 tests passed**.
- Production TypeScript/Vite build passed with **560 transformed modules**.
  The existing large Agent/PDF chunk warning remains performance debt.
- Repository privacy scan and diff whitespace validation passed. Git emitted
  only the repository's existing Windows line-ending notices.

## Live protected-app QA

The rebuilt protected app was reloaded on loopback without starting a model.
The Models page accepted the new contract, rendered placement reasons, disabled
a placement that did not fit, selected an admitted fallback and retained the
explicit no-offload-proof copy.

The Agent runtime card exercised every installed model selection read-only.
Every admission settled, every result retained truthful offload copy, blocked
choices remained disabled, and every record had an admitted fallback. The
temporary selection was restored and no Start action was invoked.

The stale pre-checkpoint native process accepted a window-close request but did
not confirm cleanup. After proving that it owned no model process and only its
embedded browser child, that exact stuck instance was terminated. One new
hidden-console protected instance then started successfully. Final ownership
checks showed one loopback listener and zero model processes. A current-build
native close/restart walkthrough remains Release-01 evidence rather than being
silently claimed here.

## Owner review

When a disposable local model can be used:

1. Reload **Models**. Confirm unavailable placements are disabled with a reason
   and a safe fallback is already selected.
2. Open **Agent**, select the same model, and confirm its placement/context
   choices agree with Models.
3. Start once. Confirm the UI says **requested** placement and does not claim
   verified tensor offload merely because chat becomes ready.
4. Request a context above verified metadata and an invalid split-layer value;
   both must be refused before a model process starts.
5. Switch placement/model. Confirm the old runtime exits, cleanup is rechecked,
   a fresh admission is shown and only then may the replacement start.
6. Unload. Confirm the model process exits, accelerator memory is released and
   no console window appears.

## Next slice

Runtime-01c should harden acquisition and failure recovery: disk-space
preflight, resumable progress, explicit pause/cancel/retry, verified partial
cleanup, checksum/revision recovery, crash/OOM classification, bounded restart,
and atomic Windows descendant ownership. Real CPU/GPU/offload evidence remains
an explicit owner-approved acceptance run; this checkpoint did not allocate
model VRAM.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
