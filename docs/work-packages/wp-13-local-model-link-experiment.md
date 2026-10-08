# WP-13: selected-session local model-link experiment
Status: experimental; human validation required.

## Question

For a bounded selected session, do two pinned local models retrieve the later
agent response or plan that best corresponds to each user request?

This is a model-evaluation question. It is not a prompt-quality metric, an
overall score, a task-success claim, or a person/developer rating.

## Fixed first slice

- Provider: Codex only.
- Trigger: one explicit per-run button on a selected session.
- Source: the existing redacted-content ingress and compatibility gate.
- Window: at most 100 redacted messages and 100,000 redacted characters.
- Model input: at most 8 user request/feedback messages, each compared with at
  most 8 later agent response/plan messages.
- Models: pinned `Qwen/Qwen3-Embedding-0.6B` and
  `BAAI/bge-reranker-v2-m3`, loaded sequentially.
- Runtime: isolated subprocess, verified local cache, offline environment,
  `trust_remote_code=False`, safetensors-only reviewed manifests.
- Device: automatic CUDA, MPS, or CPU resolution; CUDA is the current tested
  development path.

The response contains the union of each model's top candidate. Agreement is a
descriptive count, not evidence that either model is correct.

## Human review

The dashboard shows the redacted request/candidate excerpts only in the direct
command response. The reviewer labels each suggested link:

- `Relevant`
- `Incorrect`
- `Unsure`

Model suggestion precision is reported only over Relevant/Incorrect decisions;
Unsure is excluded and the denominator is always visible. No threshold activates
these models as product metrics. A private bilingual labeled holdout and a frozen
release gate are still required.

## Privacy and persistence

Redacted excerpts are ephemeral `SecretStr` values. They cross only the local
authenticated command response and current browser memory; they are not written
to SQLite, logs, model output, GET responses, share images, or synthetic public
fixtures based on user data. Redaction reduces exposure but is not anonymization.

SQLite stores only:

- installation-local pseudonymous run, message, and link references;
- ranks and finite model scores;
- explicit human annotation revisions;
- experiment, provider, adapter, schema, redactor, consent, model, tokenizer,
  backend, device, and timestamp provenance.

Run/link records are immutable. Annotation history is append-only. Explicit
privacy deletion removes the parent run and cascades through scores and labels.

## Verification gates

- Synthetic service tests: consent and safe-index checks occur before source or
  model construction; idempotent retries never reread provider text.
- Transport tests: redacted text is sent only on subprocess stdin; command line,
  environment, stderr, and parsed model result remain content-free.
- Persistence tests: no text/prompt/response/excerpt/path/output columns exist;
  immutable triggers, annotation revisions, and privacy cascade are enforced.
- HTTP tests: authentication/CSRF, exact request schema, fixed safe errors,
  no-store responses, and transient-excerpt-only POST behavior.
- Frontend tests: navigation performs only a content-free GET; one explicit Run
  action starts the experiment; malformed contracts fail closed; review labels
  use optimistic revisions; no overall score is rendered.
- Cached CUDA smoke: both pinned models must complete without download using
  fictional inputs before the live command is composed.
