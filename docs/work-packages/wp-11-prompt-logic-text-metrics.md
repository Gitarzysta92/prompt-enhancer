# WP-11: prompt and observable-logic text metrics

Status: experimental local vertical slice implemented. Explicit Codex ingress,
redaction, immutable persistence, command/query API, single-session and project UI,
and synthetic validation are complete. Private EN/PL calibration remains a release
gate for coaching claims.

## Outcome

WP-11 establishes a privacy-gated P1 analysis boundary and a 20-metric coaching
profile across prompt, collaboration, observable logic, and outcome evidence.
The original ten-metric prompt/logic pack remains readable as immutable legacy
provenance. This work does not create a universal quality score,
infer hidden chain of thought, rank a developer, or treat an assistant completion
claim as outcome evidence.

The boundary is:

```text
explicit selected-session consent
  -> documented read-only provider adapter and bounded ephemeral messages
  -> trusted local redactor and conservative language capability
  -> matching P1 local-analysis grant
  -> deterministic EN/PL feature snapshot
  -> twenty content-free immutable metric results
  -> exact-provenance ratio-of-sums project projection
```

Provider reading and redaction happen outside the metric engine. The engine has no
provider client, filesystem adapter, database repository, network client, model
downloader, or transcript output.

The current Codex mapper declares only `REQUEST`, `RESPONSE`, and `PLAN` as
observable message kinds. It never fabricates `ACTION` or `DECISION` from generic
assistant text. Metrics that require those kinds persist an `abstained` state with a
safe capability code. Missing kinds, no plan, and no decision denominator therefore
never become a favorable or unfavorable zero.

## Implemented contracts

- `EphemeralRedactedMessage` stores text as repr-hidden `SecretStr`. This is
  defense against accidental logging, not encryption and not persistence
  authorization.
- `P1TextAnalysisInput` binds the selected pseudonymous session, provider and
  adapter versions, source/content schema, redactor version, focus message,
  analysis-window fingerprint, partial-window coverage, supersession, explicit
  task profile, and at most 500 observed messages / 500,000 redacted characters.
- `P1LocalAnalysisGrant` must match provider, session, analysis fingerprint, the
  `redacted_content` tier, active consent, local-only execution, and disabled
  content persistence.
- `TextMetricResult` contains no excerpts. Metric schema v2 contains a numeric observation or
  explicit non-value state, a versioned fraction, pseudonymous message IDs,
  direct/inherited origin, applicability, evidence tier, direction, aggregation
  method, safe explanation code, a bounded closed-vocabulary factor receipt, and
  complete provenance. Receipt rows contain only a safe factor code, a typed
  detected/missing/counted/unknown state, and a bounded count.
- `TextMetricRegistry` fails if calculator order differs from definition order.
  The engine also verifies key, version, unit, direction, aggregation, and tier
  against the registered definition.

## State and aggregation semantics

`known`, `unknown`, `not_applicable`, `abstained`, and `execution_error` remain
distinct. A missing task-profile decision is `unknown`. Explicitly irrelevant
plans/questions are `not_applicable`. A rule that lacks a defensible denominator
or supported language abstains. None becomes zero.

`MetricObservation.observed_count / eligible_count` is analysis-window coverage.
It is not the metric score. `MetricFraction.numerator / denominator` is the
versioned metric value. All twenty coaching-v1 fractions aggregate by ratio of sums, never by
averaging per-session ratios. The two risk metrics retain their lower-is-better
direction and are never silently transformed to `1 - risk` for a radar chart.

## Deterministic algorithms

The baseline uses bounded Unicode tokenization, conservative EN/PL lexical
patterns, explicit typed task-profile denominators, lexical Jaccard candidate
links, a versioned plan-state rule, supersession-aware typed claim comparison, and
chronological question/answer/reopen links. Similarity indicates a candidate
relationship only. Action linkage is not success; answer linkage is not
correctness; a conflicting value pair is not a proven contradiction.

Future embedding, NLI, reranking, or structured-LLM adapters must remain behind a
separate port, pin model revision/license/tokenizer, disable remote code, preserve
abstention, and pass a private project/time-separated EN/PL holdout. They cannot
replace objective verification evidence.

## Verification

Focused tests cover:

- all twenty keys, formulas, direction, aggregation and provenance;
- bilingual fictional conversations;
- deliberate delegation and unresolved decisions;
- superseded messages and scoped claims;
- explicit no-plan/no-question applicability;
- partial windows larger than the processing cap;
- unknown, not-applicable and abstained values;
- registry mismatches and model provenance invariants; and
- canary absence from repr, serialization, validation errors and evaluation
  reports.

The checked-in synthetic evaluator reports exact state/value agreement, known
state confusion counts, precision/recall, and numeric mean absolute error. Those
figures validate software behavior on authored fixtures only. They must never be
described as accuracy on real prompts. The opt-in benchmark analyzes a generated
500-message, approximately 400k-character window and reports throughput without a
flaky wall-clock assertion.

Commands:

```powershell
pytest -q tests/test_text_analysis_contracts.py tests/test_text_metric_baselines.py tests/test_text_metric_synthetic_evaluation.py
python scripts/evaluate_text_baselines.py
python scripts/benchmark_text_baselines.py --iterations 5
python scripts/privacy_scan.py
```

## Integrated product boundary

1. The documented Codex `thread/list` + selected `thread/read(includeTurns=true)`
   adapter is constructed lazily only after standing consent, indexed selection, and
   an exact one-shot confirmation. It allows bounded request/response/plan text and
   excludes reasoning, commands, output, diffs, paths, tools, images, and unknown
   variants.
2. The local redactor and EN/PL detector produce an ephemeral, fingerprint-bound P1
   input. Text is `SecretStr`/repr-hidden and is never written to SQLite, logs, API
   responses, screenshots, or model-evaluation artifacts.
3. Immutable schema-v9 session runs persist only the named analysis-profile
   identity, typed result state, fraction,
   analyzable coverage, content-free factor receipts, pseudonymous evidence
   references, safe codes, and complete
   provider/adapter/schema/redactor/algorithm/model provenance. Prior runs cannot be
   overwritten. Schema-v7 rows migrate to `legacy.explicit-profile` version 1;
   the migration never guesses that an older run used the new standard preset.
4. The dashboard exposes one explicit confirmation for the named, server-owned
   `coaching_profile_v1` profile. Its twenty applicability decisions, denominators,
   and 100-message / 100,000-character bounds are versioned application code rather
   than client configuration. Page load,
   navigation, PNG sharing, and project aggregation never initiate a provider read.
5. Prompt Quality/Collaboration and Logic/Outcome use separate 11- and 9-signal profiles. The Prompt view is
   explicitly labeled an experimental deterministic EN/PL baseline and shows the
   score receipt, denominator source, input-window coverage, extractor version,
   calibration boundary, and a bounded coaching suggestion for every expanded
   metric. Each spoke is independent; the two lower-is-better risk axes are visibly distinct. Partial,
   unknown, not-applicable, abstained, and execution-error states remain separate.
6. Project profiles combine the latest completed runs for 1–100 selected indexed
   sessions on the server. Known fractions and analyzable coverage use ratio-of-sums;
   mixed analysis profile, pack, schema, engine, redactor, provider, algorithm, or pinned-model
   provenance blocks the combined value and preserves content-free cohorts.
7. PNG sharing is review-first and client-local. The allowlist contains only metric
   labels, values, typed states, fractions, coverage, definition versions, and bounded
   selection counts. Project/session names and IDs, evidence text/IDs, prompts, paths,
   and model-cache details are excluded.

## Performance and model decision

The deterministic 500-message / 417,299-character synthetic diagnostic completed two
iterations in approximately 0.114 seconds on the development machine. This is a local
throughput observation, not a portable performance guarantee or a correctness gate.

Six pinned, safetensors-only candidates were evaluated sequentially from an isolated
local cache with `trust_remote_code=False` and offline inference; BGE-M3 was blocked
before download because its reviewed pinned artifact was pickle-only. On the 12-query
fictional retrieval fixture, Qwen3 Embedding led with top-1 0.75 and MRR 0.861111.
BGE Reranker also reached top-1 0.75 but showed smoke/full variance. The multilingual
NLI candidate retained a 1.0 different-scope false-positive rate. Qwen3 4B produced
valid JSON on all 24 rubric cases but only 0.666667 exact agreement and 0.521368
abstention macro-F1. None is wired into product metrics; the dashboard exposes these
as explicit synthetic screens only.

## Remaining release gates

1. Build a private, locally retained bilingual annotation set split by project and
   time, with two independent raters and adjudication. No private examples enter this
   repository.
2. Calibrate each heuristic/model independently against its declared construct and
   abstention policy. Synthetic fixtures continue to prove software behavior only.
3. Do not present coaching or improvement claims until untouched-holdout precision,
   recall, calibration, selective-risk, subgroup, and drift thresholds pass.
4. Add a Claude-specific transient content adapter and capability declaration before
   enabling the same pack for Claude Code. Shared calculators remain provider-neutral.
