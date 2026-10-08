# Work packages

Campaign execution status and blockers are tracked in the
[real-metrics campaign ledger](../real-metrics-campaign-ledger.md).

- [WP-13: selected-session local model-link experiment](wp-13-local-model-link-experiment.md)
- [WP-14: evidence-bounded coaching loop](wp-14-coaching-loop.md)
- [WP-15: interactive quality lenses](wp-15-interactive-quality-lenses.md)
- [WP-16: multi-project quality aggregation](wp-16-multi-project-quality-aggregation.md)
- [WP-17: cross-model selected-session validation](wp-17-cross-model-session-validation.md)
- [WP-18: metric validity and ROI-optimized model constellation](wp-18-metric-validity-and-roi-constellation.md)
- [WP-19: expressive metric system and recommendation validation](wp-19-expressive-metric-system.md)

Work packages turn the architecture in
[ADR 0001](../adr/0001-modular-monolith-hexagonal-metric-graph.md) into small,
verifiable product increments. A package is complete only when its implementation,
contract tests, privacy checks, and documentation are complete.

The primary milestone is a synthetic task-discovery vertical slice:

```text
synthetic sessions -> task candidate -> user decision -> task revision
                   -> metric pack -> analysis run -> typed API -> dashboard
```

WP-07A is a narrow, active exception for the documented Codex App Server. It
authorizes provider access only when the user explicitly grants `local-history`
consent and then invokes an explicit index, label-enrichment, or analysis command.
Installation, server startup, dashboard page load, tests, and the synthetic demo
must never access real Codex or Claude state.

| ID | Work package | Status | Depends on |
|---|---|---|---|
| WP-01 | Task and immutable analysis storage | Complete (synthetic) | ADR 0001 |
| WP-02 | Deterministic task discovery and review decisions | Complete (synthetic) | WP-01 contracts |
| WP-03 | Typed task/discovery API | Complete | WP-01, WP-02 |
| WP-04 | React Discovery Inbox | Complete (synthetic preview) | WP-03 |
| WP-05 | Constrained desktop host and local auth bridge | Partial (integrated loopback bridge; Tauri packaging planned) | WP-04 |
| WP-06 | Privacy Tier 2 and encrypted content vault | Deferred | WP-05 security review |
| WP-07 | Documented Codex and Claude read adapters | Deferred | WP-06 review |
| WP-07A | Bounded Codex local-history reader | Active (dashboard-integrated labels and metrics) | ADR 0002, WP-01 privacy contracts |
| WP-08 | Local model evaluation and calibration | Deferred | reviewable task labels |
| WP-09 | Metric readiness and observed operational effort | Complete | WP-07A safe events, reviewed task revisions |
| WP-10 | Objective verification and acceptance evidence | In progress (WP-10A validation boundary) | WP-09 coverage contract, reviewed outcome labels |
| WP-11 | Prompt Quality and observable-logic profiles | Experimental local vertical slice complete; private calibration pending | WP-07A selected content boundary, WP-09 provenance |
| WP-18 | Metric validity and ROI-optimized model constellation | Partial (synthetic frontier screen and metric decision guidance complete; private calibration deferred) | WP-11, WP-16, WP-17 |
| WP-19 | Expressive metric system and recommendation validation | Partial (versioned gap map and action guidance complete; outcome links and empirical validation deferred) | WP-10, WP-14, WP-18 |

## WP-01: Task and immutable analysis storage

Deliverables:

- numbered SQLite migrations;
- focused repository contracts rather than additional arbitrary SQL access;
- task candidates, candidate-session evidence, decisions, and task revisions;
- immutable analysis runs with versioned result provenance;
- current-result queries implemented as projections, not destructive replacement;
- deletion APIs that can remove a synthetic task and all derived records.

Acceptance checks:

- persistent identities and selectors are 64-character pseudonyms; display labels never act as identity;
- no transcript, full-path, account, or provider-credential columns exist;
- the only plaintext provider-derived columns are bounded, consented private project/session display labels;
- an analysis rerun does not overwrite an earlier run;
- migration checksums are immutable and upgrade from schema version 1 is tested;
- repository tests use reserved synthetic values only.

## WP-02: Deterministic task discovery

Deliverables:

- typed `DiscoverySignal`, `TaskCandidate`, `TaskDecision`, and `TaskRevision`
  contracts;
- deterministic metadata-only discovery strategies;
- evidence explaining every proposed grouping;
- accept, reject, merge, and split decision semantics;
- stable candidate generation without assuming that one session equals one task.

Acceptance checks:

- identical safe inputs produce identical candidates and evidence;
- missing data remains unknown and cannot become negative evidence;
- an algorithm revision creates new candidates rather than changing a human
  decision;
- no discovery strategy can read provider state, content, or the network.

## WP-03: Typed task/discovery API

Deliverables:

- strict Pydantic request and response DTOs;
- discovery inbox, task detail, evidence, metric, and analysis-run queries;
- narrow decision commands for accept, reject, merge, and split;
- optimistic revision checks for user decisions;
- build-time OpenAPI export while runtime API documentation remains disabled.

Acceptance checks:

- loopback, authentication, Host, and Origin protections remain mandatory;
- there is no arbitrary CRUD, SQL, provider mutation, filesystem, or transcript
  endpoint;
- command retries are idempotent;
- malformed or stale revisions fail without changing state.

## WP-04: React Discovery Inbox

Deliverables:

- React, TypeScript, and Vite application shell;
- generated API types and a single transport adapter;
- discovery inbox and synthetic task-detail route;
- shared design tokens and semantic metric/evidence components;
- browser platform adapter, with Tauri deferred;
- Vitest, component, accessibility, and Playwright smoke tests.

Acceptance checks:

- the frontend contains no secrets, raw paths, transcript fixtures, or remote
  analytics;
- unexpected network origins are blocked in tests;
- unknown values, coverage, evidence, and provenance are visible;
- an ordinary backend metric renders without a feature-specific UI change.

## WP-05: Constrained desktop host and local auth bridge (partial)

Deliverables:

- an integrated loopback host serving only the built dashboard and local API;
- a same-origin, HttpOnly, SameSite authentication bridge that never exposes the
  API token to browser JavaScript, URLs, logs, or browser storage;
- production Content Security Policy and capability allowlists;
- synthetic integration tests against the same-origin bridge and persistent
  SQLite profile; and
- a future narrow Tauri packaging host without shell, arbitrary filesystem, or
  raw provider-state capabilities.

Acceptance checks:

- the production dashboard can review and analyze synthetic tasks after restart;
- the local bearer token is absent from JavaScript, DOM, URL, storage, and logs;
- the native launcher never sends the persistent token to an unverified loopback
  listener: it proves service identity through a fresh challenge and an
  exact numeric socket-origin-bound keyed answer, refusing squatters, replays,
  cross-port and IPv4/IPv6 relays, and malformed responses before any window is
  rendered;
- non-loopback hosts and unexpected origins remain blocked;
- neither the integrated host nor future desktop wrapper exposes an unrestricted command, file, network, or SQL bridge;
- package signing and updater behavior are explicitly deferred or threat-modeled
  before distribution.

## WP-07A: Bounded Codex local-history reader

This package is intentionally narrower than WP-07. It covers only the documented
local Codex App Server and persists no transcript text. Claude ingestion, raw
cache parsing, model-based content analysis, and unattended provider access stay
deferred.

Deliverables:

- one revocable `local-history` consent scope, recorded as content-bearing source
  access because `thread/list` can contain preview plaintext;
- content-minimizing list and summary DTOs that discard preview, turns, account,
  Git, and all other non-label fields;
- three capability-gated adapter modes: state-only index, at-most-25 selected
  summary reads with `includeTurns: false`, and selected operational reads with
  `includeTurns: true`;
- a separate label-enrichment application service and repository port that bind
  observations to already-indexed safe identities and persist extractor, adapter,
  provider, and source-schema provenance;
- a local manual-label layer with optimistic revisions and precedence over
  provider observations, without any provider rename call;
- fixed read-only RPC allowlists, resource limits, deterministic structural
  metrics, and sanitized cleanup; and
- dashboard and architecture documentation that do not describe list access as
  metadata-only authorization.

Acceptance checks:

- denied consent and construction cause no client or subprocess access;
- index mode forces `useStateDbOnly: true` and never emits `thread/read`;
- label and operational modes require safe persisted selectors before access;
- label mode reads only current-snapshot IDs, rejects non-empty turns, and is
  capped at 25 unique reads;
- tests use only fictional wire responses and leakage canaries;
- preview text, full paths, raw provider IDs, and content canaries never enter
  SQLite, logs, errors, or fixtures;
- label enrichment cannot mutate identity, overwrite a visible manual override,
  or trigger metric recomputation;
- duplicate or renamed display labels never change grouping or selection identity; and
- live compatibility is claimed only after an explicit local user exercise whose
  response is never copied into the repository.

## WP-09: Metric readiness and observed operational effort

This package makes the metadata already available through the safe event boundary
useful without turning an incomplete provider snapshot into a claim about task
success. It deliberately precedes verification classifiers and prompt-text models.

Deliverables:

- versioned session and reviewed-task metrics for observed finalized turns;
- explicit coverage metrics for turn usage, turn duration, tool results, tool
  duration, timestamp provenance, and unknown event kinds;
- a dashboard question layer that separates data readiness from operational
  effort and labels incomplete values as observed subtotals;
- generic metric composition so an ordinary registered metric continues to render
  without provider-specific UI plumbing; and
- explicit pack/definition provenance and synthetic golden tests for full,
  partial, empty, and missing-field event streams. Reviewed-task analysis runs
  remain immutable; session cards are a versioned current projection and do not
  yet provide longitudinal run history.

Acceptance checks:

- the provider adapter is unchanged and calculators consume only persisted
  `SafeSession` and `SafeEvent` values;
- a finalized-turn count is described as an observed current-snapshot subtotal,
  never as the number of turns required to finish;
- zero with incomplete coverage is not displayed as confirmed absence;
- ratios expose their numerator, denominator, definition version, source, and
  completeness separately;
- missing token, duration, result, or timestamp fields remain unknown rather than
  becoming zero or failure;
- session and task metric-pack revisions do not mutate prior metric definitions or
  immutable task-analysis runs; and
- session cards say `current snapshot`; durable session trends remain deferred
  until an immutable session-analysis-run store exists; and
- no score, color, or ranking implies that fewer turns, tools, tokens, plans, or
  compactions are inherently better.

## WP-10: Objective verification and acceptance evidence

WP-10A establishes a provider-neutral, high-precision, abstaining classification
contract for test, build, lint, type-check, security, and artifact-validation
commands. Its tracked evaluation corpus contains only fictional invocations,
hard negatives, ambiguous shell shapes, and privacy canaries. The dashboard
surfaces the capability as **validation only**.

Live Codex command classification is deliberately disabled in WP-10A. The
current adapter still discards commands and output, and generic command lifecycle
events are not verification outcomes. Enabling a provider requires a separate
WP-10B boundary with explicit selected-session disclosure, transient `SecretStr`
input, version-gated decoding, immutable safe evidence, deletion tests, and a
private labeled holdout. Raw commands, paths, and tool output must never be
persisted, logged, committed, or sent online.

Release gates for live evidence prioritize precision over recall: unsupported or
compound commands abstain; classifier coverage and abstention remain separate;
and the one-sided 95% exact precision lower bound must reach 99% overall and 95%
per family on an untouched private holdout. Synthetic tests prove deterministic
software behavior, not real-world precision. First-pass verification, final
verification state, test-fix cycles, and delivery acceptance remain unknown until
their own evidence and linkage gates pass.

## WP-11: Prompt Quality and observable-logic profiles

WP-11 adds an explicit one-session, local-only redacted-text command and ten
independently versioned prompt/logic metrics. The dashboard presents two five-axis
profiles, never a universal score. Immutable session runs retain content-free values,
typed non-value states, fractions, coverage, and full provenance. A project profile
aggregates 1–100 selected latest runs on the server by ratio-of-sums and blocks mixed
provenance; browser code never averages session percentages.

The current Codex content adapter exposes request, response, and plan text only.
Metrics that require typed action or decision observations therefore abstain instead
of producing a false zero. Analysis uses the named, server-owned
`standard_engineering_v1` profile, its fixed bounded read, and the exact one-shot
confirmation. Task-specific constraint/deliverable denominators safely abstain. Navigation,
startup, indexing, and project aggregation never trigger this provider read.

The compact dashboard includes independent radar spokes, explicit risk-axis direction,
coverage/state detail, and a review-first local PNG export. The export allowlist contains
only metric labels, values, typed states, fractions, coverage, versions, and bounded
selection counts; it excludes project/session labels, pseudonyms, excerpts, evidence
IDs, paths, and model-cache details.

Synthetic EN/PL fixtures validate deterministic software behavior only. The pinned
local embedding candidate remains exploratory, and the NLI candidate failed the scoped
false-positive gate; neither is active in product metrics. See
[the WP-11 specification](wp-11-prompt-logic-text-metrics.md),
[aggregation contract](wp-11-session-quality-aggregation.md), and
[local candidate report](../model-manifests/wp-11-local-candidates.md).

## WP-14: Evidence-bounded Coaching Loop

WP-14 turns compatible immutable session results into a five-item, content-free
coaching projection: objective outcome, one practice candidate, one friction
candidate, one next-task experiment, and one static template to try. Reviewed
task context is mandatory; ambiguous or absent context abstains. The dashboard
shows this compact deck first and moves the radar and individual receipts into
optional diagnostics.

The active coaching path remains deterministic and uncalibrated. It excludes
model inference, blocks sharing, keeps objective verification Unknown when no
authoritative evidence exists, and never creates an overall score or person
rating. See [the WP-14 boundary and release gates](wp-14-coaching-loop.md).

## WP-15: Interactive quality lenses

WP-15 replaces the crowded all-metric radar with four versioned semantic
lenses: task framing, collaboration flow, reasoning trace, and outcome
evidence. Each lens uses four to six compatible metrics on a fixed `0–100%`
scale, an interactive preview/pin inspector, and an exact raw-value board.
Unknown values are omitted, measured zero remains explicit, review-load values
are not silently inverted, and no polygon area becomes an overall score.

The research plan also defines the model-calibration ladder, observable
communication candidates, comparison visualization, and the statistical
boundary for multi-project work. See
[the WP-15 design and release gates](wp-15-interactive-quality-lenses.md).

## WP-16: Complete multi-project quality aggregation

WP-16 adds a backend-only, provider-free projection over 1–25 selected indexed
projects and at most 100 total sessions. The first slice implements only the
`all_analyzed_work` selection, `per_eligible_opportunity` estimand, and
`ratio_of_sums` aggregation method. Missing, empty, oversized, or incomplete
selections fail rather than paginate or truncate. Responses contain only the
selected project count and the existing content-free session-quality aggregate.
See [the WP-16 contract](wp-16-multi-project-quality-aggregation.md).

## WP-17: Cross-model selected-session validation

WP-17 defines separate public-synthetic and private selected-session lanes for
comparing local candidates with exact-version frontier models such as GPT-5.6
Sol, Claude Opus 5, and Claude Fable 5. It requires an in-memory redaction
preview and one-shot destination approval before any session text leaves the
device. Objective checks, human labels, model-judge diagnostics, cost, latency,
and failure states remain separate. Model radars are capability-specific,
coverage-aware secondary views; no universal model or developer score is
created. See [the WP-17 contract](wp-17-cross-model-session-validation.md).

## WP-18: Metric validity and ROI-optimized model constellation

WP-18 records the current no-SOTA verdict, separates outcome quality, delivery
ROI, and measurement trust, and defines a cheap-first cross-family routing
policy. A fictional 54-case EN/PL challenge now supports strict structured
scoring and two order variants across local or manually invoked frontier models.
The first frontier run saturated across GPT-5.6 Sol/Terra/Luna and Claude
Sonnet/Opus/Fable, so it validates wiring but cannot rank the models. The quality
inspector also adds decision role, why-it-matters, and review-next guidance. See
[the WP-18 contract](wp-18-metric-validity-and-roi-constellation.md).

## WP-19: Expressive metric system and recommendation validation

WP-19 triangulates the active metric surface against primary evaluation,
software-delivery, product-quality, human-AI, and risk-management frameworks.
It identifies nine missing or partial evidence families and exposes them as a
versioned dashboard roadmap without inventing values. It also specifies the
post-processing record, visual grammar, recommendation funnel, causal
validation, and privacy/release gates required before each estimator can affect
a decision. See [the WP-19 contract](wp-19-expressive-metric-system.md).

## Completed milestone boundary

WP-01 through WP-04 are complete for fictional metadata. The backend integration
tests exercise persistence across ingestion, discovery, review, analysis, and
query boundaries. The dashboard exercises the same typed contract with an
in-memory synthetic transport, including accept, reject, merge, split, and
explicit analysis creation.

The production HTTP transport bootstraps an ephemeral same-origin browser session
without exposing the persistent API token to JavaScript or storage. The
integrated dashboard can query the persistent local API. This bridge authorizes
no provider access by itself: WP-07A remains consent-gated and requires a separate
explicit index, label-enrichment, or analysis action. Tauri packaging remains a future distribution
step rather than a prerequisite for the loopback browser workflow.

## Exit condition for the active milestone

The synthetic milestone is complete when the UI flow and persistent backend flow
satisfy the same generated contract through the integrated loopback bridge, with
all privacy, unit, integration, build, and browser suites passing. A later desktop
package must preserve the same authentication and capability boundaries.
