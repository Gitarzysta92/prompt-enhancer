# WP-18: Metric validity and ROI-optimized model constellation
Status: first synthetic cross-model challenge and decision-guidance UI are
implemented; human calibration, private-session execution, and production model
routing remain deferred.

Snapshot: 2026-08-11.

## Verdict on the current metrics

Prompt Enhancer must not claim that its metric estimates are state of the art.
The measurement architecture is unusually strong in several ways: missing
values remain unknown, abstention and not-applicable are typed states, objective
verification outranks prose, ratios retain numerators and denominators, coverage
and provenance are visible, and no universal developer or model score is
calculated. Those are necessary foundations for high-quality measurement.

The active prompt, collaboration, and observable-trace estimators are still
deterministic EN/PL lexical candidates. They are transparent and useful for
product wiring, but they are not human-calibrated estimators of the constructs
their labels approximate. The existing local neural screen is also too small to
establish population accuracy. Its NLI and structured-rubric candidates failed
their critical gates and remain inactive.

The correct product claim today is therefore:

> evidence-forward experimental metrics with strong missingness, privacy, and
> provenance semantics; estimator validity is not yet established.

## Three primary decision layers

The dashboard should make three different questions visually distinct.

### 1. Outcome quality

This is the primary success layer for coding-agent work. It contains only
evidence-linked, positive-direction measures such as:

- objective requirement pass fraction;
- regression-check pass fraction;
- verified requirement coverage;
- required-output contract compliance;
- material-claim grounding; and
- repeated-run stability for comparable tasks.

The quality radar remains a compact shape scanner for four to six compatible
axes. Exact aligned values, raw fractions, coverage, and evidence remain primary.
No polygon area is interpreted.

### 2. Delivery ROI

ROI is not another quality spoke and is never `1 - cost` or `1 - latency`.
Quality must be conditioned on task type and held constant before efficiency is
compared. The first valid delivery views are:

- time to first passing objective verification;
- total cycle time with completeness state;
- cost and tokens per objectively accepted requirement;
- first-pass verification fraction;
- test/fix or correction episodes per accepted requirement; and
- a quality-versus-cost or quality-versus-time Pareto view.

A monetary ROI estimate additionally needs an explicit user-supplied value or
baseline. Without that input, the product reports resource efficiency and a
Pareto frontier, not financial return.

### 3. Measurement trust

Every quality or efficiency estimate needs an adjacent trust layer:

- applicable and usable case coverage;
- exact numerator and denominator;
- confidence or uncertainty interval when a valid sampling model exists;
- human-human and model-human agreement;
- calibration error and selective risk/coverage;
- order, format, and repeated-run stability;
- provenance and compatibility state; and
- drift or out-of-distribution status.

Prompt framing, collaboration flow, and observable traceability remain valuable
diagnostic lenses. They are leading or process signals, not substitutes for
outcome quality.

## Recommended model constellation

The best expected-ROI design is a cascade, not a panel that sends every case to
every frontier model.

| Stage | Default role | Candidate configuration | Escalation rule |
|---|---|---|---|
| 0 | Objective and structural evidence | deterministic provider/version-gated extractors, tests, builds, privacy canaries, typed missingness | never let a model override failing objective evidence |
| 1 | Local evidence retrieval and linkage | BM25 for transparent recall, Qwen3 Embedding 0.6B for candidate retrieval, BGE Reranker v2 M3 for top candidates | abstain when linkage margin or scoped evidence is insufficient |
| 2 | Cheap analytic rubric screen | GPT-5.6 Luna plus Claude Sonnet 5 on a calibrated sample or ambiguous items; use the opposite provider family as the primary judge of a model-generated output | escalate disagreement, low calibrated confidence, drift, or high-value tasks |
| 3 | High-assurance adjudication | GPT-5.6 Sol and/or Claude Opus 5, identity-blinded with fixed analytic rubrics | require human review when frontier judges disagree or objective evidence is incomplete |
| 4 | Rare long-horizon audit | Claude Fable 5 on public synthetic or explicitly approved redacted material only | use only when a preregistered hard-task eval shows incremental value over Opus/Sol |

This is a proposed routing policy, not an activated production ensemble. GPT-5.6
Luna and Claude Sonnet 5 earn the next routine-challenger slot because the first
synthetic screen saturated across every tested tier while their published prices
are below the frontier tiers. The result does not yet prove that they match
frontier models on representative work.

For outputs generated by an OpenAI model, an Anthropic model is the primary
rubric judge; for outputs generated by a Claude model, an OpenAI model is
primary. This reduces, but cannot remove, model-family self-preference. Model
identity is hidden, pair order is swapped, and a judge never evaluates its own
unblinded output as the sole source of truth.

Fable is specifically unsuitable as the routine private-session judge. Anthropic
documents it as the highest-capability and highest-price widely released Claude
model, with required 30-day retention and no zero-data-retention option. It must
show a measured gain on a hard, representative holdout before its cost and
retention trade-off can be justified.

Current model references:

- [OpenAI GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [Anthropic current model comparison](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Anthropic Claude Fable 5 integration and retention](https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5)

## Implemented synthetic frontier screen

`scripts/cross_model_challenge.py` now exports two blinded variants from the
checked-in fictional EN/PL fixtures. Each variant contains:

- 12 requirement-to-action retrieval rankings;
- 18 scoped NLI classifications; and
- 24 present/absent/abstain analytic-rubric classifications.

`order-b` reverses case order and candidate position. The scorer enforces exact
case coverage and candidate permutations, returns separate capability metrics,
and calculates order stability without producing an overall score. No provider
client, credential handling, real session selector, or arbitrary input corpus is
part of the script.

The following CLI runs used medium effort, no persisted model session, fictional
inputs only, Codex CLI 0.144.5, and Claude Code 2.1.220. Claude tools were
disabled. Codex used its strict output schema. These two CLI harnesses have
different system overhead, so their observed latency and token totals are not
cross-provider cost measurements.

| Exact model ID | Retrieval top-1, both variants | NLI accuracy, both variants | Rubric agreement, both variants | Core label stability | Full retrieval ranking stability |
|---|---:|---:|---:|---:|---:|
| `gpt-5.6-sol` | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| `gpt-5.6-terra` | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 |
| `gpt-5.6-luna` | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| `claude-sonnet-5` | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 |
| `claude-opus-5` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| `claude-fable-5` | 1.000 | 1.000 | 1.000 | 1.000 | 0.833 |

The screen is saturated. It validates model IDs, CLI wiring, structured output,
EN/PL support on these authored examples, abstention handling, and resistance to
the tested order transformation. It cannot rank the six models or establish
real-world metric accuracy. Lower-rank retrieval ordering has no additional gold
labels, so its stability is a consistency diagnostic rather than a quality
score.

Generated packet SHA-256 values for this run:

- order A challenge: `f3b183f3611caea6e3f5f4417a8324e7df55d43872a57a2f8c73a5f31054c682`;
- order A prompt: `191098bf3a2a73d854eac6484b1abf6383e7f7850bd72249aff8d850736ae7fc`;
- order A schema: `1ed9f4cb4a0c9947bc9f4e4ec7306156806dbed7cc87f108c57eb58e9fdb122e`;
- order B challenge: `48f34cedf81113a5ae894ea55b0bfc33d12cfa5efad14b3ce557656ba0077164`;
- order B prompt: `3d1ad9ac4f64f74d72f4923550b961393b52a9a320965c7b28f69e18edc5d6ab`; and
- order B schema: `6987ffca8067ff1cd45df81bab16f0c24e3ab71bce6d1157b3e144c56b2ebeb4`.

## Estimator release gates

No model constellation becomes an active metric estimator until a separately
authored, adjudicated holdout satisfies all of the following:

1. The construct, analytic rubric, evidence hierarchy, and abstention policy are
   preregistered before the holdout is scored.
2. Splits are separated by project and time; near-duplicate sessions, tasks, and
   templates cannot cross folds.
3. English and Polish, task type, provider family, task duration, and evidence
   availability are reported separately rather than hidden in a micro-average.
4. Objective checks are scored by deterministic code. LLM judges handle only
   analytic rubric items for which no objective check exists.
5. Model-human agreement is compared with adjudicated human-human agreement.
   An automated estimator must be non-inferior within a preregistered margin,
   not merely exceed an arbitrary headline accuracy.
6. Class precision/recall/F1, abstention F1, Brier score or an equivalent proper
   scoring rule, calibration curves, and selective risk/coverage are reported.
7. Confidence intervals use the sampling unit that matches deployment and
   cluster by project/session where observations are dependent.
8. Position, verbosity, formatting, language, model-family self-preference, and
   adversarial instruction counterfactuals pass their own gates.
9. Drift monitoring can withhold the estimator rather than silently applying an
   old calibration to a new provider/model distribution.
10. A model upgrade, rubric change, redactor change, or provider-schema change
    creates a new compatibility cohort and requires revalidation.

This follows current evaluation guidance to use task-specific distributions,
automated checks where possible, and human calibration rather than generic or
vibe-based scores: [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) and
[Anthropic success criteria and evaluation design](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests).
It also addresses documented judge position, superficial-quality, multilingual,
and self-preference biases: [Wang et al. 2024](https://aclanthology.org/2024.acl-long.511/),
[Zhou et al. 2024](https://aclanthology.org/2024.ccl-1.101/),
[EACL multilingual evaluator study](https://aclanthology.org/2024.findings-eacl.71/),
and [Pombal et al. 2026](https://arxiv.org/abs/2604.06996).

## Plot contract

The product should use the smallest plot that answers each decision:

- one candidate versus one compatible baseline: quality radar plus exact rows;
- three or more models: aligned dot intervals or small multiples, never a dense
  overlaid radar;
- quality versus time/cost: Pareto scatter with uncertainty and coverage;
- estimator trust: calibration and selective risk/coverage curves;
- longitudinal change: task-mix-aware intervals or control charts; and
- model routing: a flow/cost table showing how many cases stop or escalate at
  each stage.

Each metric inspector now includes a role, a short explanation of why the metric
can matter, and a concrete review question. It must continue to show the metric
question, raw fraction, coverage, direction, method, calibration state,
limitation, and lens boundary. Guidance never changes the persisted value and
never converts an uncalibrated association into causal advice.

## Private all-project boundary

This coding workflow does not open or score real local Codex/Claude sessions or
unrelated project source. Repository policy forbids that access. The application
may eventually let the user run a local-only, explicit, bounded analysis across
already indexed projects, but raw content and sensitive derived aggregates do
not become coding-agent output.

Any remote private-session lane remains behind an in-memory redaction preview,
exact destination/model/retention/price disclosure, and one-shot approval. Fable
requires an additional explicit acknowledgement of its retention class. A public
synthetic result never activates a private-session estimator.

## Next implementation sequence

1. Add difficult, independently adjudicated synthetic counterfactuals so the
   frontier screen no longer saturates.
2. Add a human-label tool that stores only local adjudication contracts and
   content-free aggregate reports; never check labels from real sessions into
   the repository.
3. Implement calibration, selective-risk, agreement, and clustered-interval
   reports before adding model-derived confidence to the UI.
4. Complete the frontend for WP-16's bounded multi-project aggregate without
   reading a provider during navigation.
5. Add provider adapters only after the WP-17 redaction preview and destination
   approval boundary is complete.
