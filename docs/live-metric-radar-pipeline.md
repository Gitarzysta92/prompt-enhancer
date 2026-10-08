# All-20-metric local probabilistic radar

This document is the product and implementation contract for the always-on
radar. It contains no source text, model output, local paths, or account data.

## What the radar means

The radar intentionally shows two different kinds of information:

- The **solid line and points** are evidence-backed typed measurements.
- An **indigo diamond** is an informative experimental local-model median.
- Per-axis dark and light **radial whiskers** show central 50% and 90% ranges.
- The outer coverage ring reports observed eligible evidence, not confidence.

All twenty axes always remain visible. `Not applicable`, `Pending`, `Unknown`,
and `Execution error` are axis states and gaps; none is drawn at zero. A solid
zero exists only when the deterministic contract proved an eligible denominator
and observed no positive factor. Until a metric passes its own calibration gate,
the model layer is labelled **Experimental model range** rather than probability,
confidence, or predictive interval.

Four fixed lenses keep unlike constructs separate:

| Lens | Metrics |
|---|---|
| Task framing | task definition, problem evidence, context, constraints, acceptance testability, deliverable contract |
| Collaboration | ambiguity resolution, clarification yield, exploration conversion, scope-change discipline, rework candidate rate |
| Reasoning trace | decomposition, decision rationale, open-loop closure, verification-strategy adequacy |
| Evidence lane | hypothesis-test linkage, requirement-action traceability, claim grounding, first-pass verification, verified requirements |

There is no combined developer score and no universal trust percentage.

## Twenty versioned contracts

Each metric has one observation owner. Context may overlap for inference, but a
physical fragment or chunk boundary never creates an additional denominator.

| Metric | Observation unit | Live evidence route |
|---|---|---|
| Task definition coverage | canonical request revision | deterministic extraction + small factor model |
| Problem evidence quality | diagnostic request | deterministic extraction + small model; deep adjudication on ambiguity |
| Context sufficiency | stateful request | deterministic extraction + small factor model |
| Constraint precision | one explicit constraint | deterministic extraction + small factor model |
| Acceptance testability | one requirement | deterministic extraction + small model; deep adjudication on ambiguity |
| Deliverable contract | one requested artifact | deterministic extraction + small factor model |
| Ambiguity resolution | one ambiguity and its resolution horizon | deterministic linkage + small model; deep adjudication on weak links |
| Clarification yield | one agent question and linked user response | deterministic linkage + small factor model |
| Exploration conversion | one hypothesis, evidence action, and plan update | deterministic linkage + small model + objective receipt when available |
| Scope-change discipline | one scope-change episode | deterministic linkage + small factor model |
| Rework candidate rate | one feedback episode | deterministic routing + small model; deep adjudication on disagreement |
| Decomposition coverage | one requirement linked to a plan item | deterministic extraction + retrieval + small model |
| Hypothesis-test linkage | one hypothesis linked to check, result, and update | deterministic linkage + small model + objective receipt |
| Decision-rationale coverage | one material decision | deterministic linkage + small model; deep adjudication on ambiguity |
| Requirement-action traceability | one requirement linked to action or artifact | deterministic linkage + retrieval + objective receipt |
| Open-loop closure | one loop through its closure horizon | deterministic linkage + small model; deep adjudication on ambiguity |
| Agent-claim grounding | one material completion claim | small model may link; objective evidence decides the solid value |
| Verification-strategy adequacy | one testable requirement and verification method | deterministic linkage + small model; deep adjudication on ambiguity |
| First-pass verification | first valid executable verification outcome | objective evidence only for the solid value |
| Verified-requirement coverage | requirements with fresh passing evidence or explicit acceptance | objective evidence only for the solid value |

Factor scales are binary, ordinal `0 / 0.5 / 1`, or exact proportions according
to the contract. The current session value is computed from current unique units
and sufficient statistics; historical radar snapshots are never averaged into a
new value. Applicability and value-conditional-on-applicability remain separate.
An open right-edge episode is `Pending` rather than a negative. A one-message
request can therefore measure relevant task-framing axes while later-interaction
metrics remain N/A or pending.

## Local model router

The live estimator is an external mixture-of-specialists router. It is not a
large native MoE and does not average ten unrelated scores.

The active expert-set receipt is `local-factor-router-v3` and the live
execution plan is `small-factor-router-v5`. Sealed v2 receipts remain readable,
but the changed plan/model identity creates an explicit history break.

1. Deterministic matching and BM25 select bounded candidate evidence first.
2. Three revision-pinned multilingual NLI encoders provide the EN/PL baseline.
3. The pinned ModernBERT-base zero-shot and DeBERTa-small-long-NLI challengers
   remain disabled in the live router. ModernBERT's current binary mapping does
   not satisfy the three-state factor contract, and both models require separate
   resource and quality gates before activation.
4. High disagreement, neutral evidence, or manual deep analysis may invoke the
   pinned Qwen3 4B judge in 4-bit NF4.
5. Models execute serially in isolated child processes. Only typed probabilities,
   factor summaries, stage identity, quantization, and resource telemetry return.
6. Optional-model failure never erases deterministic values or successful small
   estimates. Small-model GPU exhaustion retries once on CPU. Deep-lane failure is
   a typed diagnostic failure.
7. The long-lived server never imports Torch to decide whether the deep lane can
   run. `auto` mode relies only on completed small-stage device receipts. The
   optional deep child has a 27-second inference deadline inside a 30-second lane
   budget. A timeout publishes the usable small-model result as a partial snapshot
   with `probabilistic_deep_timeout` only after process-tree termination is
   positively confirmed. Unconfirmed cleanup is fatal and retains the prior head.

The historical immutable ten-stage committee graph remains readable for old
receipts, but it is not executed by the live estimator.

New explicit requests use
`run_local_metric_cascade_on_selected_redacted_text`. The former
`run_ten_local_models_on_selected_redacted_text` token remains accepted only so
older local clients do not break. Likewise, the v1 API's `model_count: 10` and
`experts` array describe the immutable compatibility graph shape; the
`predictive_model_stages` array is the authoritative record of which live model
processes actually ran.

### Resource contract

- supported target: 8 GB GPU-class VRAM and up to 16 GB system RAM;
- per-child ceilings: 6,144 MiB peak VRAM and 8,192 MiB RSS;
- one GPU child at a time; no simultaneous weights;
- the 6,144 MiB child ceiling leaves roughly 1.5 GiB on an 8 GB-class device,
  but this is currently a post-execution exclusion gate rather than an
  allocator reservation;
- at most 2,048 tokens per semantic episode;
- Qwen 4B always runs in a disposable 4-bit child;
- CPU-only operation disables the deep lane. A fail-closed host-RAM admission
  check is still required before claiming automatic 8 GB-RAM deep-lane disablement.

Synthetic local hardware verification recorded complete all-twenty receipt
construction with the active small specialists and selective Qwen child below
the VRAM ceiling. It did **not** prove that all twenty axes received numeric
model estimates: the current live sidecar can attempt ranges for eight immediate
behavioural metrics and truthfully withholds the other twelve. This is resource
evidence, not model-quality calibration. The current cold
serial pass is still roughly one minute on the reference machine; the desired
warm-update, cold-update, and deep-lane p95 targets remain promotion gates. A
future persistent warm-small-encoder worker must retain the same privacy and
resource boundaries before those latency targets can be claimed.

## Distribution contract

For every metric, v35 persists a predictive receipt beside, never inside, the
measured receipt. Its state is one of `Unavailable`, `Experimental`,
`Calibrated`, `Out of distribution`, or `Execution error`. It contains only:

- mean, median, q05, q25, q75, and q95;
- applicability and pending mass;
- model disagreement and effective observation count;
- model-set, calibration, contract, and quantization identities;
- a fixed 20-bin density and content-free factor contributions in the detail API.

The parent deterministically draws 1,024 samples through the exact factor and
metric aggregation and stores summaries, never samples or raw logits. Raw model
softmax is an experimental feature, not confidence. Temperature/Dirichlet
calibration, a non-negative out-of-fold stacker, and conformalized 90% intervals
become eligible one metric at a time only after the required project/time-separated
holdout gates pass. A cohort mismatch becomes `Out of distribution` and withholds
the calibrated claim.

NLI `neutral` is epistemic uncertainty, not proof that a temporal horizon is
still open. Eight structurally immediate behavioral contracts may publish an
experimental range with zero pending mass. The five collaboration contracts
and open-loop closure withhold their model range until typed semantic lifecycle
receipts can establish closed versus pending/right-censored state; their measured
value and typed state remain independent and available.

The exact live-sidecar availability set is intentionally explicit:

- **Range may be attempted (8):** task definition, problem evidence, context
  sufficiency, constraint precision, acceptance testability, deliverable
  contract, decomposition coverage, and decision-rationale coverage.
- **Range is structurally withheld (12):** ambiguity resolution, clarification
  yield, exploration conversion, scope-change discipline, rework candidate
  rate, open-loop closure, hypothesis-test linkage, requirement-action
  traceability, agent-claim grounding, verification-strategy adequacy,
  first-pass verification, and verified-requirement coverage.

Verification-strategy adequacy belongs to the conversational Reasoning lens in
the V2 contract, but its frozen V1 predictive contract classified it as
objective. That historical identity is not rewritten; the V1 range remains
withheld until a new persisted predictive-contract version can activate the
corrected conversational route. The five evidence-lane metrics remain
objective-receipt-only, while the six lifecycle metrics require typed horizon
state. A larger model cannot override either authority boundary.

Before calibration, an experimental range is also withheld unless at least 95%
of the deterministic Monte Carlo draws resolve to a metric value. This prevents
the displayed quantiles from looking precise after silently conditioning away
material neutral model mass. The unresolved mass is not converted to zero or
relabeled as temporal pending evidence.

Evidence-lane metrics do not receive transcript-model forecasts in the current
contract. Only fresh, scoped objective receipts can create a solid evidence
measurement.

## Persistence, API, and privacy

Schemas v35-v38 add content-free predictive, execution, semantic-unit, and
retry/quarantine receipts without predictive backfill. Schema v39 transactionally
rebuilds only the affected predictive sidecar tables so frozen v2 and active v3
model-set identities can coexist; migrations 1-38 and their checksums remain
unchanged. Schema v40 adds the normalized, sealed all-twenty V2 metric-state
publication beside each new model-ensemble run without backfilling or rewriting
historical receipts. New normalized rows are immutable, content-free, and privacy-cascade
with secure-delete and WAL verification. Stored data includes
only pseudonymous digests, typed states, sufficient statistics, distribution
summaries, version identities, and resource telemetry. It excludes transcript
text, snippets, prompts, generated explanations, source identifiers, and raw
logits.

The full run contains the sealed V2 publication, and the bounded watch trajectory
contains its compact V2 metric states plus compact predictive summaries. A
legacy point and a V2 point are never marked comparable merely because their
model-plan hashes match.
The authenticated metric-detail endpoint exposes the fixed density and factor
contributions for one run/metric. Old/new geometry is comparable only when the
contract, model set, calibration, quantization, provider and content schemas,
redactor, and analysis scope match.

The dashboard and mini-window render one shared workspace over the same canonical
watch head. Both use the same durable **Analyze** and **Cancel** actions, values,
guidance, model-stage status, and publication history. Their lightweight poll
fetches the immutable heavy run only when the head changes and keeps the last
sealed snapshot mounted through transient failures. Opening either view alone
grants no source read.

Schema v36 adds content-free, per-generation attempt and stage receipts with a
sealed terminal graph. Optional model failure may publish a partial result; a
failed or cancelled attempt retains the previous head. Cancellation revokes the
lease and is cooperative at a model-stage boundary; immediate child-process-tree
termination is not yet implemented. Schema v37 adds a content-free semantic-unit
sidecar keyed by message-content digests. It preserves exact-one ownership and
append-idempotent lifecycle heads without persisting evidence text. Schema v38
adds bounded retry/backoff and quarantine state; schema v39 preserves historical
v2 predictive receipts while requiring new v3 model-set provenance. Schema v40
stores and seals canonical V2 metric states and sufficient statistics.
Implementation states and guidance identities are deterministically re-derived
and covered by the seal fingerprint; no wording or source text is stored.

For an immediate request rubric or declared profile slot, `source_complete`
means the adapter proved the exact requested analysis window was supplied. It
does not claim the whole session was available. Cross-turn semantic episodes
retain the stricter reconciliation-completeness rule, so a bounded suffix cannot
silently close earlier ambiguity, feedback, hypothesis, or open-loop episodes.

## Provider boundary

Adapters are read-only and capability-driven. Codex is the reference adapter.
A future Claude Code adapter must use its documented local interfaces and emit
the same provider-neutral envelope. Unsupported provider capabilities become
typed unknown states. No transcript or derived content is sent to a cloud model.

## Verification and honest rollout state

Implemented now:

- all twenty contract identities and predictive receipts;
- exact measured-versus-predictive separation;
- active three-model EN/PL small-model routing plus pinned research-only
  long-context challenger manifests;
- selective 4-bit Qwen lane with child resource enforcement;
- immutable v35 persistence, trajectory and metric-detail API;
- one full/compact workspace with fixed-axis measured geometry and informative
  experimental median/50%/90% whiskers;
- a durable canonical head, partial/failure history, real enqueue, cooperative
  cancellation, and stale-while-refresh behavior;
- conservative semantic-unit identities and immutable sidecar persistence;
- tests for unknown-not-zero, objective precedence, exact ownership, model
  resource failure, API validation, migration, privacy, and visual semantics.

Still deliberately not claimed:

- calibrated model truth or product eligibility;
- a representative 100-example active-learning set plus untouched 200-example
  holdout for every metric;
- p95 warm update at three seconds and cold update at eight seconds;
- a production persistent 60-second warm encoder process;
- full-session incremental source coverage (the current Codex watch remains a
  newest-100-message / 100,000-character bounded view);
- a standalone `AnalysisSnapshotV2` graph or generic analysis-job executor (v2
  currently wraps the existing immutable run and watch worker);
- immediate process-tree termination, complete failed-stage resource telemetry,
  or per-factor model contribution counts;
- complete provider requirement/action/verification linkage; the current safe
  Codex event adapter has no requirement-reference surface, so it withholds
  numeric objective overrides rather than guessing them;
- Claude Code and generic adapter SDK support;
- proof that quantized Qwen preserves quality across the complete factor suite.

Promotion is per metric. It requires the locked macro-F1, class-recall, ECE,
selective-risk, interval-coverage, outcome-false-positive, and mixture-improvement
gates. If the mixture does not beat the best calibrated single expert, the single
expert wins. Public trajectory datasets can support stress tests, but cannot
replace metric-matched calibration labels.
