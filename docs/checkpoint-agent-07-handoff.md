# Agent-07 handoff: executable compatibility and truthful context

Date: 2026-08-27
Status: implementation and synthetic automated/browser verification complete; native owner reload and real-model placement checks remain deferred

## Outcome

The local Agent no longer equates “registered GGUF” with “usable model,” and it
no longer presents a character/count heuristic as context truth. Executable
support, exact artifact/runtime identity, GGUF metadata, live capability
execution and request context now have separate versioned receipts.

`local-model-compatibility.v1` has one admitted adapter:
`llama.cpp-openai-gguf.v1`. A model is `supported` only when the exact served
alias passes a live text request. Stopped models are `unknown`; missing artifacts
and failed executions are closed `unsupported` results with reason codes. This
does not claim that every Hugging Face LLM, GGUF architecture, tokenizer,
projector, chat template or licence is compatible.

## Implemented boundary

- The Models API exposes `GET /v1/local-models/compatibility` without paths,
  prompts, model output or registry internals. Its adapter receipt records the
  adapter/probe versions, bounded runtime version, verified/unknown runtime
  identity and runtime-binary SHA-256 when readable.
- Each model receipt separates live execution from provenance. Exact
  architecture, tokenizer family, training context, artifact digest, pinned
  source revision and licence stay nullable; aliases and filenames never fill
  missing evidence.
- The bounded `gguf-metadata.v1` reader admits only exact GGUF keys for
  architecture, tokenizer family, block count and training context. It bounds
  file reads, entries, strings and arrays.
- Exact request counting uses llama.cpp's documented
  [`POST /v1/chat/completions/input_tokens`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
  The local API exposes the same official response shape through routed and
  alias-specific loopback endpoints.
- The Agent protects leading system instructions, tool schemas and the current
  request. On measured overflow it removes only whole older conversation units,
  recounts, reports every omission visibly, and refuses before inference when
  the protected minimum plus an explicit output reservation cannot fit.
- When the exact counter is missing, malformed or fails, context use remains
  `unknown`. The app does not substitute a character ratio, another tokenizer,
  a catalog context claim or a model-name estimate. llama.cpp remains the final
  enforcement boundary in that state.
- `local-runtime-coordinator.v2` reports exact known input, served limit,
  available output capacity, requested output, compaction count and admission
  policy—or a closed unknown reason. Agent shows this in Model & context;
  Models shows executable compatibility beside static GGUF identity.
- A short bounded request receipt preserves an exact Agent preflight/compaction
  result through the subsequent owned streaming call without treating it as
  reusable authority.
- Hardware/version probes on Windows now use hidden subprocess creation flags.
  Read-only overview/compatibility calls do not start a model.
- `scripts/export_local_model_compatibility.py` generates the public
  [synthetic compatibility matrix](local-model-compatibility-matrix.md).

## Correctness repairs found during validation

1. The earlier Agent silently trimmed history by message count and character
   count. That path is gone from live admission; token-driven compaction is
   exact or context stays unknown.
2. The original whole-turn removal needed explicit protection for all leading
   system messages and assistant-tool/tool-result adjacency. The compactor now
   drops only user-delimited older units and refuses when only protected content
   remains.
3. An older synthetic judge server treated the activation probe as a judging
   request and crashed. The fixture now implements the live text probe and
   exact input-token endpoint; production fail-closed behavior was not weakened.
4. Two HTTP tests replaced `create_local_agent_service` on the application class
   and never restored it. Later tests then received an Agent service with no
   durable catalog, creating the misleading “passes alone, fails later” 503.
   Both patches are now scoped and the exact polluted sequence has a regression
   receipt.
5. The first visual assertion matched both the context summary and its expanded
   detail. The assertion now targets the summary while the repeated value stays
   intentionally consistent.

## Verification receipts

- Agent-07 backend selection: **262 passed**, **1 platform-only symlink case
  skipped**, with two dependency deprecation warnings. It covers registration,
  activation, live probes, compatibility, GGUF bounds, context counting,
  compaction/refusal, Agent streaming, usage, provenance, orchestration,
  annotation, judging, liveness and byte-exact OpenAPI.
- Exact cross-test pollution sequence: **3/3 passed** after scoped factory
  patches.
- Complete frontend unit/component gate: **1,988 tests across 147 files**.
- Complete Playwright gate: **111/111 passed**, including Agent/Models at 360
  and 1,440 px. New assertions cover live-supported compatibility and exact
  `612 input / 4,096 · 3,484 available` context.
- Manual synthetic browser inspection at 1,280 px found the project/session
  rail, exact context receipt and compatibility receipt visible; page width did
  not overflow and browser error/warning logs were empty.
- TypeScript project check passed. Production Vite build passed with **524
  modules transformed**. Generated OpenAPI consistency passed after regenerating
  the committed schema and client types.
- `git diff --check` passed; Git emitted only the repository's existing Windows
  LF-to-CRLF notices and no whitespace error.
- The privacy scanner found only the known pre-existing untracked binary
  `docs/checkpoint-agent-02-shell.png`. No Agent-07 source, fixture or document
  added another finding; the existing file was not deleted or bypassed.
- The repository-wide backend invocation contains 4,398 tests and was stopped
  early rather than spending an unbounded checkpoint on it. No complete-suite
  claim is made; the 262-test affected selection is the backend receipt.
- No real model, native Prompt Enhancer process, GPU inference job, Claude CLI,
  or additional application server was launched. Synthetic runtime subprocesses
  were hidden, bounded and cleaned up. No Prompt Enhancer, `llama-server` or
  synthetic runtime process remained; ports 8765 and 8766 were closed. The
  existing synthetic Vite fixture remained on loopback port 4173 for review.

## Owner checklist after the later native reload

1. Open Models. Confirm the running model says `supported` only after its live
   probe, stopped/untried models say `unknown`, and architecture/tokenizer/
   provenance fields stay unknown when the artifact does not supply them.
2. Open Agent. Before the first message after activation, confirm context input
   is unknown while the served limit is visible. Send a small Unicode/code
   request and confirm the exact input/available receipt appears afterward.
3. Expand Runtime details. Confirm Admission matches the visible summary and a
   model switch resets last-request context instead of carrying the old number.
4. With a deliberately small context limit and synthetic long history, confirm
   only whole older turns disappear with a visible notice. Make the protected
   current request too large and confirm it is refused before generation.
5. Compare CPU, GPU and GPU+CPU placement for one admitted model. Stop between
   runs and confirm the model process exits and VRAM is released before loading
   another model.
6. Try one GGUF/runtime combination whose live text probe fails. Confirm it is
   not advertised as usable and no chat session binds to it.

These checks are intentionally not marked passed. They require the native app
and optional real model/GPU use, which were avoided after the earlier visible
terminal cascade.

## Capability-list status and next checkpoint

Agent-07 completes the list's executable compatibility distinction, bounded
GGUF metadata, exact/unknown context semantics, whole-turn compaction/refusal,
strict API/UI contracts and generated compatibility matrix. It does not add a
second runtime family, certify arbitrary Hugging Face repositories, expose
hidden chain of thought or estimate missing usage.

The next correct slice is **Agent-08 — release hardening and legacy retirement**:
responsive/accessibility completion, repeated load/unload and long-stream soak,
crash recovery across runtime/approval/file/artifact paths, bounded content-free
diagnostics, retention/delete/export verification, and removal of legacy layout
only after parity evidence.
