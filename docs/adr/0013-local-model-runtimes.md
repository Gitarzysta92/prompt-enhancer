# ADR 0013: Local model runtimes and the model-judge lane

- Status: accepted (2026-08-19); runtime slice first, judge lane second
- Owner direction: run a strong local LLM on this machine (GPU where it fits,
  CPU or GPU/CPU split otherwise), use it to help produce and analyse metrics,
  and expose every installed model on the app's local API so a person can use
  it as a regular LLM for small tasks.

## Context

The repository already runs small local text models (transformers backends,
isolated snapshot loader) and keeps every byte of session content on the
machine. The model the owner named, `orcarouter/Qwen3.8-27B-Uncensored`, is
published in several formats; the MLX variant is Apple-Silicon-only, while the
author's GGUF variant runs through llama.cpp on Windows/NVIDIA. On the owner's
machine (RTX 3080 Ti Laptop, 16 GB VRAM, 32 GB RAM) a 27B model at 4-bit does
not fit in VRAM alone, so partial offload (GPU/CPU split) is the realistic
mode; that is exactly the device option the owner asked for.

## Decision

1. **Runtime = llama.cpp `llama-server`.** One subprocess per activated model,
   bound to loopback on a free port, started with the chosen device:
   `cpu` (no offload), `gpu` (all layers), `split` (an estimated number of
   layers that fits the free VRAM; the person can override). The binary is
   detected on PATH or configured (`PROMPT_ENHANCER_LLAMA_SERVER`); the app
   never downloads or executes a binary without an explicit, size-stated
   confirmation in the dashboard.
   On Windows every runtime is spawned directly with `shell=False`, redirected
   standard handles, and `CREATE_NO_WINDOW`; read-only registry/status/overview
   operations never start a process.
2. **Registry.** Installed models (alias, source repo/file or local path,
   format, size, sha256 when known, default device, context size) live in
   `local-models/registry.json` under the app home (registered in the private
   path inventory). Weights live under `local-models/weights/`. Downloads go
   through `huggingface_hub` in public-only mode (`token=False`); the app never
   reads a cached login, and every download is confirmed with its exact pinned
   revision, digest, licence identifier, and byte count first.
3. **Endpoints.** Under the authenticated local API: list, add, activate
   (device, gpu layers, context), deactivate, status, and an OpenAI-compatible
   `POST /v1/local-models/{alias}/chat/completions` that proxies to the model's
   loopback runtime. Inference prompts and responses stay on the machine; the
   explicit Hub discovery/download flow is the only network exception in this
   slice. The runtime port is never exposed beyond loopback; the app's token
   guards the proxy.
4. **Metrics use (model-judge lane, second slice).** The local model rates the
   redacted analysis window on the same three calibration questions and scale
   as the Calibration page (low / medium / high / cannot judge). Those are
   **model judgments**: stored separately (model id, prompt version, label),
   never merged into product metrics, compared with human ratings via the
   existing agreement math, and only ever promoted through the preregistered
   estimator activation gate. Objective evidence (ADR 0012) always outranks
   them.
5. **Scheduling.** Judge work runs in the single serial analysis lane after the
   P1 run, one model process at a time, so models never double-spawn; batching
   within one runtime is used where llama.cpp allows parallel slots.

## Consequences

- A person can keep several models installed and switch which one is active
  and on which device; only active models consume GPU/CPU memory.
- Chat responses from an uncensored model are the person's own local use; the
  app does not filter them, and they are never persisted by the app.
- The judge lane makes no metric "calibrated" by itself; the Calibration page
  ratings and the activation gate decide that.

## Addendum (2026-08-19): streaming and OpenAI-style base URLs

- The chat proxy honours `stream: true` by relaying the runtime's server-sent
  events unchanged, bounded to 16 MB per reply; a failure the runtime reports
  before streaming (for example a context overflow, HTTP 400) is returned as
  the same JSON error a non-streamed call would get.
- Every model is reachable under an OpenAI-style base URL:
  `/v1/local-models/{alias}/v1` (`GET /models`, `POST /chat/completions`), and
  one shared base URL `/v1/local-models/openai/v1` routes by the request's
  `model` field among running aliases. The app token may be sent as
  `Authorization: Bearer <token>` so unchanged OpenAI clients can use the local
  models; the aliases `openai`, `downloads` and `remote-files` are reserved.
- The Models page offers a chat box for running models (thinking disabled by
  default, conversation kept in the browser tab only, never persisted).


## Addendum (2026-08-20): download provenance and the licence admission policy

The first-party Hugging Face path used to discover a mutable repository, download
without a revision, accept any size within a percent, and register no digest,
revision or licence. It now works only against an identity the server resolved
for itself.

- **Discovery pins a commit.** `GET /v1/local-models/remote-files` asks
  `HfApi.model_info` twice: once to learn which commit the repository points at,
  then again addressed to that 40-hex commit oid with `files_metadata=True`, so the
  per-file size, the expected `lfs.sha256` and the repository licence all come from
  the exact revision a download would fetch. A repository that will not name a
  commit oid, or that answers the commit lookup with a different commit, returns a
  fixed content-free unavailable state; a branch name such as `main` or `latest` is
  never reported as pinned. Files without an exact size or an expected sha256 are
  listed as ineligible with a closed reason code, never guessed at.
- **Downloads are bound to that identity, not to the caller.** `POST
  /v1/local-models/downloads` carries the revision, digest, licence and byte count
  the person confirmed in the browser. The service re-resolves the repository and
  refuses unless its own answer matches the confirmation exactly, so substituting a
  repository, file, revision, digest, size or licence is refused, and a repository
  that moved between browsing and confirming is refused rather than silently
  fetched. `hf_hub_download` is called with the commit oid and `repo_type="model"`;
  no repository code is fetched, nothing is unpickled and `trust_remote_code` is
  never involved. Afterwards the file must be a regular non-symlink file inside the
  weights folder, start with the GGUF magic, have exactly the published byte count,
  and hash to the published digest under a constant-time comparison. Any failure
  registers nothing, reports one closed code, and makes a best-effort removal of
  the unverified file; Hub exception text is never read or returned.
- **The record carries the provenance.** `LocalModelRecord` gains
  `source_revision`, `source_license`, `source_license_policy` and
  `provenance_verified` alongside the existing `sha256`. Manually registered files,
  folder scans and registries written before this change stay readable and report
  provenance as unavailable; nothing is back-filled or inferred. A download's
  identity includes the commit and the digest, so two revisions of the same file
  can never alias to one download.
- **Repository admission policy (`local-model-license-policy.v1`).** A frozen
  allow-list of licence identifiers this repository is willing to fetch
  automatically, a frozen refuse-list of identifiers reviewed and rejected
  (bespoke community terms, non-commercial and no-derivative clauses, and the Hub's
  `other`/`unknown` placeholders), and everything else treated as unreviewed. Only
  `allowed` permits a download. **Limits:** this is an operational gate for this
  app's downloader, not a legal conclusion. It does not interpret licence text, does
  not see a repository's own additional conditions, says nothing about how model
  output may be used, and can be wrong about a repository that mislabels itself.
  Anything it does not admit is fetched by hand or not at all. The automated
  path is public-only (`token=False`) and never reads a cached Hugging Face
  login; gated repositories therefore remain ineligible. A person may accept
  the provider's terms and download a file outside the app, then register that
  local GGUF with provenance explicitly unavailable.
- **The Models page shows it.** The revision, licence with its admission outcome,
  the policy version, the exact byte count and the sha256 are on screen before the
  confirmation dialog, which repeats all of them. The download button is disabled
  and labelled "Download unavailable" whenever eligibility is false. The
  recommended list only looks a repository up; nothing downloads from it, and there
  is no automatic "latest model" download anywhere.

## Completion and judgment acceptance (2026-08-26)

The local judge and session interpretation require one completed assistant text
response before accepting structured output. A token limit, filtering, missing
receipt, tool request or ambiguous response is not a successful judgment. The
bounded JSON decoder rejects duplicate keys, invalid Unicode, non-finite values,
excessive depth and surrounding prose. One exact outer JSON fence remains
compatible. Interpretations reject invalid fields instead of manufacturing text
or returning a successful empty explanation. Failed generation never replaces
previous valid labels or explanations.

The main and context-retry protocols are now
`judge-v4-complete-json-anchor-15k` and `judge-v4-complete-json-anchor-6k`.
The rubric questions and sealed window renderer are unchanged; the version bump
records the stricter completion/output acceptance policy. Existing rows are not
relabelled or deleted. Current agreement excludes older/unknown protocols and
reserved missing window identities, reports the excluded count, and leaves
agreement unknown when no eligible pairs exist. The session view keeps historical
labels visible with their protocol and exclusion status. A sweep may rejudge
older rows; historical results do not suppress current-protocol work.

Interpretations report `interpret-v2-complete-json`. A valid completion receipt is
not proof of task success, model accuracy, calibrated metrics, matching human
rating windows or independent verification. No activation or privacy gate changes.

## Reviewed-case comparison (2026-08-26, checkpoint 25)

Current agreement additionally requires `calibration-case.v1`: the provider,
session, source-window identity and exact canonical rendered evidence. Both the
human review endpoint and local judge use this same case preparation. A shortened
context retry records the evidence actually submitted. Human ratings with an
unexpired review receipt use `calibration-rating-v2-reviewed-case`; schema 61
stores nullable case provenance without backfilling historical labels.

Current protocols alone no longer qualify a judgment for comparison. The human
rating and model judgment must identify the same case and source window, and the
model's recorded identity must be coherent. A reused explicit alias with mixed
recorded identities cannot be pooled. Either side's `cannot_judge` is an
abstention; unmatched and abstained counts are separate, and empty agreement stays
unknown. Historical rows remain visible and can be explicitly reviewed again.

Review receipts are bounded, expiring, memory-only metadata. Displayed evidence
honors reader/consent checks and private/no-store transport. A receipt is not
human authentication, proof of independent assessment or a model-activation
decision. Recorded model names are not promoted to verified immutable weight
revisions. See the checkpoint 25 handoff for synthetic verification and remaining
quality/owner-review limits.

## Agent usage trailers and cancellable reads (checkpoint 26)

Agent streaming requests ask the loopback runtime for `stream_options.include_usage`.
Usage may accompany the finish chunk or arrive as an empty-choices metadata
trailer. Only the owned HTTP adapter can collect that trailing metadata, bounded
by 250 ms, 32 lines and 64 KB. Further answer/tool output is not admitted; absent
or malformed metadata leaves counts unavailable instead of stalling completion.
The runtime option is documented in the
[llama.cpp server schema](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-schema.cpp).

The HTTP response retains standard HTTP framing over an owned nonblocking
socket reader. Reads use a 100 ms cancellation-check interval; an absolute metadata
deadline also covers slow partial lines. This avoids a reproduced Windows wait
on cross-thread buffered-reader closure. Socket ownership remains local; proxies
and redirects are still refused. No runtime listening address is broadened.

These are transport observations, not token estimates, GPU inference timings or
certified immutable model identity. Header-wait cancellation, command interruption
and all-installed-runtime compatibility are not established by these synthetic
checks. See the checkpoint 26 handoff for exact coverage.

### Checkpoint 27: ownership before headers and through disconnect

Content-free request cancellation is now scoped through the HTTP adapter, not
the model process. Cancellable connect/upload operations use numeric loopback
destinations without DNS or tunnelling; existing proxy/redirect refusal and
standard HTTP framing remain intact. Header and body reads share that request's
event but keep reader-local cleanup separate from turn cancellation.

All three chat proxy routes move runtime I/O off the API event loop. One ASGI
disconnect watcher spans initial headers and streaming, signals cancellation,
joins the worker and closes the upstream reply. Server-side request cancellation
does not manufacture a runtime-error response, while actual upstream errors
retain their status. Concurrent conversations using the same alias are isolated.

The [checkpoint 27 handoff](../checkpoint-27-handoff.md) records real-loopback
header/body/disconnect tests and controlled connect/upload fault checks. These
supersede the earlier header-wait gap; they do not certify every runtime's
internal generation-abort implementation, unload GPU weights, or establish
background-job cancellation and command interruption.

### Checkpoint 28: background subprocess control and retry quarantine

The serial ensemble and probabilistic runner share per-invocation cancellation
ownership. Progress failures are sticky across model-stage, fallback and deep
paths, and callback references are cleared in a finalizer. Separate joined pipe
workers keep a blocked stdin write from suppressing timeout/cancellation on
Windows. Output is bounded during execution; JSON and exit-status receipts must
agree with the documented child protocol.

The shared service lane checks cooperative cancellation while waiting and
before a new source read. Intentional stops retain their type through execution
and publication. Cleanup uncertainty is a distinct, nonretryable failure: the
runner and service reject later work in that instance, and the watch scheduler
quarantines the attempt without automatically allocating another model.

Cleanup uncertainty can arrive after cancellation has already sealed the
attempt and released its lease. A narrow transactional fallback verifies the
original claim token, generation and stopped state before recording the watch's
quarantine. It never rewrites the sealed attempt or an earlier published head,
never re-enables a disabled watch, and cannot affect a queued replacement or a
later generation. The worker retains this uncertainty after its thread exits;
neither repeated Stop nor starting that same worker instance can report a clean
resource lifecycle.

Minimized API status exposes quarantine independently from ordinary failure.
Missing legacy metadata remains unknown. UI Stop does not clear evidence of
unconfirmed runtime cleanup; inspect the local runtime before restarting and
explicitly retrying. This does not establish arbitrary injected-adapter
preemption or every orphan-process behavior. See the
[checkpoint 28 handoff](../checkpoint-28-handoff.md) for bounded evidence and
remaining limits. Agent command interruption remains separate.

### Agent checkpoint 06: explicit projectors and live multimodal capabilities

Local model records can name one explicit `mmproj_path`. Activation passes it
to `llama-server` with `--mmproj`; registry scans skip projector files and do
not infer a pairing from names. The runtime's
`local-runtime-multimodal-probe.v2` result is bound to the exact served alias
and fails closed. A registry field, repository description, architecture name,
or filename cannot make image/audio controls available by itself.

Verified image requests use OpenAI `image_url` content and verified PCM-WAV
requests use llama.cpp's experimental `input_audio` content. The app does not
claim video, arbitrary audio codecs, every multimodal architecture, or a
portable tokenizer/media-token count. If the runtime does not report media
context usage, the coordinator keeps it unknown. `recording` cannot be true
unless audio is verified, and the UI additionally requires an available local
microphone API and user permission. The runtime remains loopback-only and no
model was launched for the synthetic checkpoint receipt.

### Agent checkpoint 07: executable compatibility and exact context admission

`local-model-compatibility.v1` separates discovery evidence from executable
support. A registered GGUF is not advertised as usable until the exact served
alias passes a live text request through `llama.cpp-openai-gguf.v1`. Stopped
models remain `unknown`; missing artifacts and live failures have distinct
closed reason codes. The adapter receipt includes its version, bounded runtime
version, runtime-binary digest when readable, and capability-probe version.
Model digest, source revision, licence, architecture, tokenizer family and
training context remain nullable when their exact evidence is unavailable.
Filenames and repository names never fill those fields.

The GGUF reader is deliberately bounded and reads only exact metadata keys for
architecture, tokenizer family, block count and training context. Other runtime
families or model formats require a separate versioned adapter and contract row;
this checkpoint does not claim arbitrary Hugging Face compatibility.

Request context is measured with llama.cpp's chat-template-aware
`POST /v1/chat/completions/input_tokens`. On measured overflow the Agent drops
only whole older conversation units and recounts. Leading system instructions,
tool schemas and the current request are protected. If the protected minimum
plus an explicit output reservation cannot fit, inference is refused. If the
counter is absent, malformed or fails, context remains `unknown`; no character
ratio, alternate tokenizer or model-name estimate replaces it, and llama.cpp
remains the final enforcement boundary. See the
[Agent-07 handoff](../checkpoint-agent-07-handoff.md) and generated
[compatibility matrix](../local-model-compatibility-matrix.md).
