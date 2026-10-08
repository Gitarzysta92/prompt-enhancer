# Agent checkpoint 12c handoff

## Outcome

The Agent context control now presents runtime evidence as exact or unknown
without inventing a tokenizer estimate. Exact evidence is bound to the selected
chat, model and turn. Evidence from an older turn cannot appear as current, and
streamed event-sequence changes no longer restart or starve the context read.

Exact admitted, compacted and refused preflights remain visibly distinct. The
control reports the measured input, configured limit and remaining capacity;
refusal above the limit reports the overflow instead of clamping it to zero.
Compaction reports how many earlier messages were omitted. Accessible warning
states begin at 75% and become critical at 90%, with an exact-use progress meter.

Unknown evidence explicitly says that no token estimate was substituted. During
a refresh, the last confirmed value is labelled **checking latest**. If that
refresh fails, the last confirmed value remains visible but is labelled stale,
rather than disappearing or masquerading as current.

## Correctness boundaries

- Runtime context states remain `known` or `unknown`. There is deliberately no
  heuristic token-count fallback when the selected runtime cannot provide an
  exact chat-template preflight.
- Bound evidence is accepted only for the current chat, selected model alias and
  current turn number. Older-turn receipts and stale request completions are
  ignored.
- A turn-pending preflight is polled on a bounded 500 ms cadence while the turn
  runs. Individual streamed deltas do not create new context requests.
- Exact `admitted`, `compacted` and `refused` policies have separate copy and
  alert semantics. Unknown evidence has no numeric progress meter.
- Exact percentages above 100% retain their raw value in accessible text while
  the progressbar value itself is clamped to its valid range.
- A failed refresh preserves only visibly stale last-confirmed evidence. It does
  not convert missing evidence to zero or to an inferred estimate.
- This slice changes no retained history, approval authority, model process,
  placement, MCP hosting or workspace effect.

## Validation

- Focused component and strict API-contract matrix: **3 files, 38 tests passed**.
- Agent runtime-control suite: **24 tests passed**, including streamed-head
  stability, older-turn rejection, overflow/refusal, compacted and critical
  warnings, unknown presentation, pending polling, and stale/checking refresh
  states.
- Backend exact-context rules: **4 tests passed**, covering whole-turn
  compaction, refusal without cutting the system/current request, unknown
  tokenizer behavior and refusal before inference.
- Strict MCP context-surface test: **1 test passed**; private fields remain
  absent.
- Full Agent UI and shared Agent contract gate: **46 files, 705 tests passed**.
- Production TypeScript/Vite build passed with **559 transformed modules**. The
  existing approximately 523 kB Agent-page chunk warning remains tracked
  performance debt.
- Repository privacy scan and targeted diff whitespace validation passed.
- The protected loopback app reloaded at `/agent`. The stopped-runtime card
  rendered **Unknown · no token estimate · runtime** and explicitly stated that
  no tokenizer estimate was substituted.
- Listener census showed only `127.0.0.1:8765` on the application ports and no
  known local-model process. This checkpoint started no model, GPU workload,
  command worker or MCP host.

## Owner review

Use a disposable chat and an owner-approved local model when convenient:

1. Start the model and send one short request. Confirm exact input use appears
   only after the matching turn preflight and is labelled with its turn number.
2. Send a response slowly enough to observe streaming. Confirm the context card
   does not flicker or repeatedly return to a loading state for every delta.
3. Change the selected model or context limit. Confirm prior exact evidence is
   not presented as current and the refresh state is explicit.
4. Exercise a near-limit request. Confirm 75% and 90% warnings are visually and
   keyboard/screen-reader accessible; if the runtime compacts or refuses, confirm
   that exact policy is named and an overflow is never shown as zero available.
5. Stop and unload the model. Confirm the context returns to an explicit unknown
   state, no terminal windows appear, and process/VRAM cleanup completes.

## Next slice

Runtime-01a will begin Workstream B by reconciling the production local-model
lifecycle: acquisition/import provenance, placement compatibility, start and
readiness ownership, switch-before-load, Stop versus unload, hidden-process
launching, crash/OOM recovery and verified cleanup. Automated synthetic
transition tests come first; no real model or GPU allocation will be started
without an owner-approved walkthrough.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
