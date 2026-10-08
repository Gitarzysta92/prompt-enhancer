# WP-17: Cross-model selected-session validation

Status: partial. The local model screen and the fictional cross-model challenge
exporter/scorer are implemented. No provider API adapter, unattended remote
runner, real-session export, or private-session execution is enabled.

Snapshot: 2026-08-11.

## Decision

Prompt Enhancer will support a bounded comparison of many models, including
local candidates and explicitly selected frontier API models, but it will not
turn one conversation into a universal model ranking. Every result belongs to
one versioned capability, evaluation packet, tool policy, effort policy, and
scoring definition.

The first remote challengers requested for research are:

| Provider | Display name | Exact API model ID | Intended comparison role |
|---|---|---|---|
| OpenAI | GPT-5.6 Sol | `gpt-5.6-sol` | complex coding and professional-work challenger |
| Anthropic | Claude Opus 5 | `claude-opus-5` | complex agentic-coding challenger |
| Anthropic | Claude Fable 5 | `claude-fable-5` | highest-capability, long-horizon challenger |

Current product documentation: [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[Claude Opus 5](https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5),
and [Claude Fable 5](https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5).
Availability, price, behavior, retention, and aliases must be rechecked when a
registry version changes. A display name never substitutes for the exact model
ID recorded by a run.

These frontier models are remote generative systems. They are not local
Hugging Face manifests and do not enter the safetensors cache, local model
loader, or current synthetic model-job endpoint.

## Two evaluation lanes

### Public synthetic lane

This lane is safe to repeat across many models and may run remotely after the
user selects destinations:

- fictional English/Polish rubric extraction;
- fictional requirement-to-action and question-to-answer linkage;
- synthetic repository tasks with deterministic tests, builds, and privacy
  canaries;
- fixed structured-output and abstention cases; and
- counterfactual order, verbosity, formatting, and model-name-blinding cases.

Only authored fictional inputs may be checked into the repository. Objective
verification is the primary outcome for coding tasks. LLM judges may provide a
separate diagnostic label but never override a failing test, build, privacy
gate, or explicit human decision.

### Selected-session private lane

This lane is an opt-in case study, not benchmark accuracy:

```text
explicit selected-session action
  -> bounded provider read
  -> local deterministic redaction
  -> in-memory outbound-payload preview
  -> destination, retention, price, and model-ID disclosure
  -> one-shot user approval
  -> fixed parallel or randomized model runs
  -> local scoring and blinded human review
  -> content-free measurements and complete provenance only
```

No task navigation, indexing, dashboard load, model selection, or prior consent
may trigger this flow. The redacted outbound text and model responses remain
ephemeral. They are not SQLite fields, logs, screenshots, GET responses,
fixtures, or repository artifacts. Redaction is risk reduction, not anonymity.

Claude Fable 5 refusals are recorded as a separate typed outcome. A fallback to
another model is never silent and never credited to Fable. Provider credentials
remain outside the repository and are never exposed to browser JavaScript.

## Fair-run contract

Every comparison run records:

- provider, exact model ID, provider revision or response fingerprint when
  available, date, endpoint, region, and retention class;
- system/developer prompt version, evaluation packet version, rubric version,
  grader version, redactor version, and schema version;
- tool allowlist, workspace snapshot, time budget, token/output budget, effort
  or reasoning setting, temperature, seed support, and retry policy;
- input, cached-input, reasoning, and output token counts when reported;
- latency, cost, tool calls, refusals, transport failures, truncation, and
  incomplete-run state as separate observations; and
- objective checks, blinded human labels, and model-judge labels as separate
  evidence tiers.

Tool access and effort are experimental conditions. Results from different
conditions are not placed in the same comparison cohort. Model outputs are
canonicalized for format only when the canonicalizer is pinned and its effect
is reported. Pairwise order is swapped, model identity is hidden from human and
LLM graders, and repeated samples are required before a stability claim.

## Capability-specific visual lenses

The model comparison UI may use radar plots only for compact shape scanning
within one compatible capability. The exact aligned value view remains primary.

The first coding-outcome lens may contain up to six positive-direction axes:

1. objective requirement pass fraction;
2. regression-check pass fraction;
3. evidence-grounding precision;
4. required-output contract compliance;
5. calibrated abstention or uncertainty handling; and
6. repeated-run stability.

Latency, cost, token use, memory, refusals, and safety incidents remain outside
that polygon because they have different units and directions. They appear as
exact values and distributions. A transformed efficiency axis requires its own
versioned target-attainment definition and cannot silently use `1 - cost` or
`1 - latency`.

Radar requirements:

- point position is the declared fraction; the point ring is usable-case
  coverage; labels show raw numerator/denominator;
- uncertainty appears in aligned interval rows, not as an implied radar area;
- at most one candidate and one exact-compatible baseline may overlap;
- three or more models use small multiples or aligned dots;
- unavailable, refused, failed, abstained, and not-applicable remain distinct
  and are never plotted as zero; and
- polygon area is non-semantic and no overall model score is calculated.

## Validation gates

- One selected session can validate wiring and produce a private case study; it
  cannot establish comparative model quality.
- Release claims require a frozen, project/time-separated holdout with
  pre-registered task types, metrics, thresholds, and subgroup slices.
- Coding claims require deterministic objective checks and privacy canaries.
- Rubric and linkage claims require independent human labels, adjudication,
  abstention analysis, calibration, and order/format counterfactuals.
- Remote results never activate local coaching metrics automatically.
- No developer, user, provider, or model receives a universal intelligence,
  personality, productivity, or worth score.

## Smallest implementation sequence

1. Add a content-free remote-model registry and immutable evaluation-condition
   contract; no network call. Model IDs are documented, but the registry remains
   to be implemented.
2. **Implemented:** export a fictional, versioned challenge packet and accept a
   manually produced structured response for local content-free scoring. See
   `scripts/cross_model_challenge.py` and
   [WP-18](wp-18-metric-validity-and-roi-constellation.md).
3. Add the in-memory redaction preview and one-shot selected-session approval;
   still no unattended calls.
4. Add provider adapters one at a time behind explicit credentials, destination
   disclosure, fixed safe errors, and no-log tests.
5. Add blinded local grading, exact-value comparison, compatible two-profile
   radar overlays, and small multiples.
