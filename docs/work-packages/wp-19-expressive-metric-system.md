# WP-19: expressive metric system and recommendation validation

Status: **metric opportunity catalog and decision guidance implemented; production estimators and causal validation deferred**

## Outcome

Prompt Enhancer should help a user decide what to try next and whether it helped.
It should not merely produce more prompt-style ratios or collapse unlike evidence
into an attractive overall score.

This package cross-validates the current metric architecture against independent
evaluation, software-delivery, product-quality, human-AI, and risk-management
frameworks. It records the missing constructs, the evidence required to activate
them, and the validation gates that prevent a roadmap item from masquerading as
an observed value.

The dashboard implementation exposes this gap map as specifications with one of
three states: `partial-foundation`, `not-measured`, or `private-opt-in`. It never
creates placeholder zeroes.

## What “cross-validated” means here

The current result is **construct and design triangulation**, not empirical proof
that a production estimator is valid:

1. inventory every implemented metric, evidence dependency, unknown state, and
   dashboard decision;
2. compare the covered constructs with independent primary frameworks;
3. retain constructs supported across frameworks or needed to protect against a
   known optimization failure;
4. specify evidence, denominators, uncertainty, provenance, and misuse
   guardrails before implementation;
5. activate an estimator only after task-stratified human and objective
   validation on a time-separated holdout.

Synthetic model agreement tests implementation stability and protocol handling.
It does not establish real-session validity, model superiority, or SOTA status.

## Primary-source crosswalk

| Source | Measurement implication | Gap exposed in Coaching v1 | Design response |
|---|---|---|---|
| [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) and [graders](https://developers.openai.com/api/docs/guides/graders) | Use task-specific distributions, explicit criteria, human calibration, continuous evaluation, and validated graders | Candidate ratios have synthetic checks but no representative human-calibrated deployment set | Add agreement, calibration, selective-risk, repeatability, drift, and abstention release gates |
| [SPACE](https://www.microsoft.com/en-us/research/publication/the-space-of-developer-productivity-theres-more-to-it-than-you-think/) and [EngThrive](https://www.microsoft.com/en-us/research/publication/engthrive-make-it-fast-and-easy-to-do-great-work/) | Productivity is multidimensional; speed, ease, quality, and sustainable experience need distinct signals | Prompt form is overrepresented relative to verified value, ease, and durable quality | Keep separate lenses; add optional private experience signals and quality-adjusted efficiency |
| [DORA metrics](https://dora.dev/guides/dora-metrics/) | Throughput must be read beside instability and within delivery context | Immediate session completion cannot show downstream rework, reopens, reversions, or recovery | Add linked durability windows and reason-coded downstream outcomes |
| [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html) | Product quality has multiple task-dependent characteristics | Functional checks alone do not cover reliability, security, maintainability, compatibility, interaction, performance, flexibility, or safety | Let each task select applicable characteristics and bind each to an inspectable gate |
| [NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) | Context, oversight, uncertainty, privacy, safety, monitoring, feedback, and change management are first-class | Autonomy calibration, user control, policy conformance, and drift are not visible as an outcome profile | Add non-tradeable safety gates, oversight errors, recovery, feedback, and drift monitoring |
| [METR time horizons](https://metr.org/time-horizons/) and [experienced-developer RCT](https://arxiv.org/abs/2507.09089) | Use clear objective criteria, repeated independent attempts, held-out tasks, and distinguish perceived from measured benefit | One run and a user's impression cannot estimate reliable capability or time benefit | Add repeated-run intervals, matched/randomized comparisons, and separate objective versus perceived outcomes |
| [Anthropic skill-formation study](https://www.anthropic.com/research/AI-assistance-coding-skills) | Faster completion and retained understanding can move differently | Telemetry cannot establish comprehension or sustainable use | Never infer cognition from prose; use only voluntary private self-report or a separately consented task |
| [Google code-quality/productivity research](https://research.google/pubs/what-improves-developer-productivity-at-google-code-quality/) and [productivity metric design](https://research.google/pubs/what-makes-a-good-productivity-metric/) | Code quality and productivity are related but require multiple facets and careful constructs | A prompt-quality radar is not an outcome or product-quality model | Preserve a metric vector and add artifact/evidence profiles rather than a universal score |

## Cross-validated gap map

| Priority | Family | State now | Candidate decisions | Evidence required before values appear |
|---|---|---|---|---|
| P0 | Goal attainment and user value | Partial foundation | Was each accepted requirement satisfied and useful? What remains open? | Requirement-level accept/partial/reject/reopen decisions, objective checks, optional usefulness response |
| P0 | Quality-adjusted delivery | Not measured | Which valid approach reaches comparable verified coverage with less time, cost, or usage? | Complete timestamps, provider usage or labeled estimates, price provenance, verified requirements, comparable task strata |
| P0 | Oversight and autonomy calibration | Not measured | Did the agent escalate material risk and avoid unnecessary review load? | Risk class, approval, intervention, decision-attribution, reversibility, and verified recovery events |
| P0 | Downstream durability | Not measured | Did accepted work remain correct after the session? | Follow-up window and reason-coded links to reopens, reversions, failures, defects, or incidents |
| P0 | Measurement trust | Partial foundation | When should the estimator be trusted, withheld, or recalibrated? | Independent human labels, repeated runs, counterfactual variants, current cohorts, time-separated samples |
| P0 | Safety, privacy, and user control | Partial foundation | Did every action stay inside authority and exposure boundaries, and could the user recover control? | Policies, action risk, approvals, redaction/canary results, exposure receipts, overrides, rollback, deletion tests |
| P0 | Recommendation effectiveness | Not measured | Was advice applicable, tried, implemented faithfully, beneficial, and safe? | Versioned offer, try/decline, implementation receipt, matched baseline, outcome, effort, adverse effects |
| P1 | Artifact quality profile | Not measured | Which task-relevant product qualities were objectively checked? | Task-selected quality profile and type-specific analyzers, tests, reviews, or probes |
| P1 | Ease and sustainable use | Private opt-in | Did the workflow reduce friction without creating overload or weakening understanding? | Optional private self-report and explicit interruption, review, resumption, or explanation-request events |

These families are orthogonal lenses. `P0` means measurement infrastructure or a
decision-safety dependency should precede additional stylistic ratios; it does
not mean that every task must produce every metric.

## Metric record contract for post-processing

Every computed observation should be self-describing. A consumer must be able to
distinguish a real zero from missing evidence and a comparable estimate from an
invalid comparison without consulting undocumented UI logic.

| Field group | Required fields | Rule |
|---|---|---|
| Identity | metric key, definition version, family, label | Keys are stable; semantic changes create a new definition version |
| State | observed / estimated / unknown / abstained / not-applicable | Only observed or validated estimated states carry a value |
| Quantity | value, unit, numerator, denominator, direction | Denominators remain explicit; contextual metrics have no favorable direction |
| Applicability | task type, artifact type, risk class, comparison stratum | Not-applicable is distinct from zero and unknown |
| Evidence | evidence tier, source classes, coverage, evidence references | Objective verification outranks inferred text and assistant completion claims |
| Uncertainty | interval or distribution, sample size, calibration window, abstention threshold | Point estimates without their uncertainty cannot drive a recommendation |
| Privacy | privacy tier, consent scope, retention class, export eligibility | Private self-report and derived signals are excluded from team ranking and default export |
| Provenance | provider, adapter, schema, redactor, tokenizer, model revision, prompt/rubric, calculator | Every component is versioned; remote processing requires a redaction preview and explicit approval |
| Time | observation window, follow-up window, censoring state, event-time provenance | Downstream metrics expose incomplete follow-up and clock uncertainty |
| Comparison | baseline identity, matching fields, cohort size, task-mix shift | No cross-project or cross-model comparison without compatible strata |

## Evidence and activation hierarchy

1. **Tier A — directly observed:** authoritative event, artifact, objective check,
   explicit user decision, or externally linked outcome.
2. **Tier B — deterministic derived:** reproducible transform over Tier A evidence
   with complete coverage and versioned semantics.
3. **Tier C — calibrated inferred:** model/rubric output that passes human-human,
   model-human, calibration, selective-risk, stability, subgroup, and drift gates.
4. **Specification only:** proposed construct with no active estimator. It remains
   `not-measured` and never receives a placeholder value.

No lower tier may overwrite contradictory higher-tier evidence. An estimate may
abstain, and missing evidence remains unknown.

## Recommendation contract

A useful recommendation is a small, reversible experiment, not a diagnosis of
the user. Each offer needs:

- a versioned recommendation and the metric/evidence that triggered it;
- applicability conditions and explicit reasons to withhold it;
- one concrete action, a success check, and an adverse-effect guardrail;
- an optional `try`, `decline`, or `not-relevant` response without interpreting
  non-adoption as resistance;
- an observable implementation-fidelity receipt when possible;
- a later outcome on a comparable task, plus time/effort cost;
- uncertainty, alternative explanations, and a retain/modify/withdraw decision.

Recommendation analysis must keep this funnel visible:

```text
eligible -> offered -> tried -> implemented faithfully -> outcome observed
         -> matched uplift estimated -> adverse effects reviewed
```

Useful post-processing metrics include applicability coverage, adoption rate,
execution fidelity, outcome coverage, quality-adjusted uplift, effort cost, and
adverse-effect rate. Adoption is contextual, not inherently favorable.

## Causal validation plan

1. Define the task stratum, accepted requirements, objective outcome, expected
   side effects, and minimum useful effect before seeing results.
2. Prefer a randomized within-user crossover where practical. Otherwise use a
   prospective matched comparison and label it observational.
3. Keep model, permission mode, repository/task class, language, complexity,
   evidence completeness, and follow-up window stable or model them explicitly.
4. Measure adoption selection separately from effect among faithful uses.
5. Report intervals, sample size, missingness, censoring, subgroup behavior, and
   adverse effects. Do not treat a time-series correlation as causation.
6. Revalidate after model, rubric, adapter, provider schema, task mix, or metric
   definition changes.

## Visual grammar

Metric richness should create better questions, not a denser radar.

| Question | Preferred view | Guardrail |
|---|---|---|
| Current bounded profile | Radar with 3–8 compatible normalized dimensions | Show evidence/coverage beside it; never mix safety gates, raw units, and private experience into one polygon |
| Quality versus time/cost | Pareto scatter or frontier | Hold verified outcome definition and task stratum constant |
| Recommendation pathway | Eligibility/adoption/fidelity/outcome funnel | Do not interpret non-adoption as failure |
| Estimator trust | Reliability diagram and selective risk–coverage curve | Show human baseline and sample size |
| Repeated model behavior | Distribution/interval plot | Independent runs and pinned revisions; no universal winner score |
| Downstream durability | Time-to-reopen/revert view with censoring | Separate changed requirements and external causes |
| Longitudinal change | Small multiples by metric family with definition boundaries | Never draw through a version discontinuity |

The primary dashboard remains compact. The broader map is disclosed on demand,
and details lead to evidence and a next decision rather than decorative density.

## Delivery sequence

### Phase 1 — trust and value foundation

- persist metric state, applicability, evidence tier, uncertainty, privacy, and
  complete provenance as first-class fields;
- add local requirement-level acceptance and reopen decisions;
- add recommendation offer/try/decline/fidelity/outcome events;
- render the nine-family opportunity map and metric-specific action guidance.

### Phase 2 — P0 outcome links

- implement quality-adjusted time/usage only where denominators are complete;
- add task-risk and approval/intervention events for oversight calibration;
- add reason-coded downstream follow-up links;
- expose safety/user-control gates and measurement-trust diagnostics.

### Phase 3 — task-specific extensions

- add artifact adapters for selected task types and applicable ISO 25010 quality
  characteristics;
- pilot one optional local ease item and explicit interruption/review events;
- evaluate recommendations prospectively in two or three stable task strata.

## Release gates

An inferred or comparative metric remains disabled until:

- its construct, target population, unit, direction, and non-applicable cases are
  documented;
- synthetic privacy, canary, unknown-state, and schema-version tests pass;
- independent reviewers establish an interpretable human-human baseline;
- model-human agreement, calibration, selective risk, repeated-run stability,
  language/task subgroup behavior, and time-separated drift meet pre-registered
  thresholds;
- objective evidence linkage precision/recall is audited where applicable;
- the UI displays state, evidence, uncertainty, comparison scope, and provenance;
- recommendation experiments show no unacceptable safety, quality, workload, or
  privacy regression.

No gate may be bypassed to make a chart complete.

## Privacy and misuse boundary

- Real provider sessions are never read for this package without the existing
  explicit local-history consent flow.
- No transcript or derived metric is sent to a remote model without a separate,
  task-specific instruction, a redaction preview, and explicit approval.
- Self-report, affect, workload, understanding, and recommendation-response data
  are private, optional, independently deletable, and excluded from ranking.
- Metrics describe task evidence and workflow behavior. They do not measure a
  developer's intelligence, worth, personality, or universal productivity.
- Cross-project aggregation uses private local pseudonyms, minimum cohort rules,
  task-stratified comparisons, and visible unknowns; pseudonymized is not
  anonymous.

## Acceptance checks

- the dashboard lists every opportunity family as partial, unmeasured, or
  private opt-in and renders no placeholder value;
- no opportunity contributes to an overall score or developer/model ranking;
- every active coaching metric explains why it matters, what to review, one
  action to try, and evidence that could confirm improvement;
- every coaching experiment includes a success check and adverse-effect
  guardrail;
- metric keys and catalog version are unique and tested;
- full frontend, backend, end-to-end, secret, PII, and privacy tests pass using
  fictional fixtures only.
