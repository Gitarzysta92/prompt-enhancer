# WP-15: Interactive quality lenses and multi-project comparison

Status: first bounded implementation complete, August 2026.

## Decision

Prompt Enhancer will not put every metric into one radar or collapse unlike
constructs into a universal person, intelligence, productivity, or skill score.
The product will use versioned **quality lenses**. Each lens has a stable set of
four to six compatible metrics, one large interactive radar for shape scanning,
and a more accurate aligned value view for reading numbers and uncertainty.

The first four lenses reuse the existing twenty-metric coaching pack:

| Lens | Metrics | Interpretation boundary |
|---|---|---|
| Task framing | task definition, problem evidence, context, constraint precision, acceptance testability, deliverable contract | Observable request/specification candidates; not prompt correctness or intelligence |
| Collaboration flow | ambiguity resolution, clarification yield, exploration conversion, scope-change acknowledgement, rework-candidate rate | Observable repair and convergence patterns; not personality or social aptitude |
| Reasoning trace | decomposition coverage, hypothesis-test linkage, decision-rationale coverage, requirement-action traceability, open-loop closure | Observable plans, decisions, links, and closures; never hidden chain-of-thought |
| Outcome evidence | claim grounding, verification-strategy coverage, first-pass verification, verified-requirement coverage | Objective evidence outranks human acceptance; assistant claims never prove success |

Review-load metrics remain visually separate unless a derived view explicitly
transforms their direction. Persisted values are never silently inverted.

## What ships first

### Large interactive lens plot

- Show one selected lens at a time; do not draw a twenty-axis polygon.
- Use a fixed `0–100%` scale on every ratio axis.
- Keep the axis set and order fixed for the exact lens version when comparing
  profiles. Unknown, not-applicable, abstained, failed, or incompatible values
  are absent, never center zeroes.
- A measured zero is a real center point and is labelled as measured.
- Hover or keyboard focus previews one axis. Click or Enter pins it. Escape or
  the explicit close action clears the pin.
- The adjacent inspector shows the full name, question, direction, raw
  numerator/denominator, coverage, state, method/model, calibration, limitation,
  and one evidence-bounded experiment to try. It never shows transcript text.
- “Expand” means a larger focus view, not unconstrained pan/zoom. Zooming a
  small categorical polygon does not create more evidence.
- Motion morphs points between lenses with transform/path interpolation only;
  reduced-motion users get an immediate state change.

### Exact value view

The radar is secondary. The same lens always includes aligned bars or dot and
interval rows with full metric names, raw fractions, missingness, and coverage.
Color is paired with labels, marker shape, line style, and explicit delta text.

For one current profile and one compatible baseline:

- current profile: solid line and circular points;
- baseline: dashed line and diamond points;
- improvement/regression: explicit signed delta in the exact value view;
- unavailable values: textual state, not a zero-width bar.

Three or more project profiles use small multiples or aligned dot/interval rows,
not overlapping radar polygons.

## Metric expansion policy

The app may research additional communication constructs, but it must measure
observable interaction rather than infer personal traits. Candidate additions
must live in separate experimental lenses until independently calibrated:

| Candidate construct | Defensible operational question | Avoid |
|---|---|---|
| Information structure | Are problem, context, constraints, action, and outcome connected in a usable order? | “Writing intelligence” |
| Referential clarity | Are important entities introduced and referred to without unresolved ambiguity? | Guessing intent from style |
| Concision with coverage | Is required information present without repeated, non-progressing content? | Rewarding short prompts regardless of task complexity |
| Uncertainty calibration | Are material uncertainties stated and later resolved, tested, or explicitly deferred? | Scoring confidence or personality |
| Repair effectiveness | After a misunderstanding, does the next exchange restore a shared task state? | Blaming the user for agent errors |
| Interaction continuity | Do responses preserve active requirements and acknowledge supersession? | Anthropomorphic “relationship with the agent” scores |
| Protocol fluency | Does the user request artifacts, boundaries, evidence, and verification when the task requires them? | A universal expertise score |
| Audience and register fit | Is the requested output style explicit and appropriate for the selected audience? | Cultural or identity inference |
| Rhetorical support | Are consequential recommendations connected to reasons, evidence, and alternatives? | Persuasiveness as truth |
| Question usefulness | Do questions reduce a relevant uncertainty or unlock a decision? | Question frequency as quality |

Emotion, stress, burnout, personality, employability, and affect ranking are out
of scope. If private tone-friction research is ever added, it requires separate
opt-in, calibration, retention, and share/team restrictions.

## Local model pipeline

The current twenty dashboard ratios are deterministic EN/PL rule candidates;
they are not produced by the local Hugging Face experiments. The intended
bounded pipeline is:

```text
explicit one-run local consent
  -> allowlisted provider text projection
  -> deterministic local redaction
  -> task type and applicability
  -> clause/dialogue-act candidates
  -> BM25 + multilingual embedding top-k retrieval
  -> optional cross-encoder reranking
  -> scoped classifier or bounded rubric with abstention
  -> typed requirement/decision/action/evidence graph
  -> content-free receipts, fractions, states, uncertainty, provenance
```

Every activated component requires a pinned revision, reviewed license,
safetensors or ONNX, `trust_remote_code=False`, no remote fallback, EN/PL
holdout results, selective-risk calibration, and a versioned rollback path.
Model similarity is candidate linkage, not entailment, correctness, or outcome.

## Multi-project selection and estimand

The browser must not fetch project pages and average their displayed
percentages. A bounded server command accepts pseudonymous project selections,
resolves their indexed sessions, and reuses the existing immutable aggregation
core. Responses omit project/session identifiers, labels, text, and evidence
references.

The first shipped multi-project estimand is explicitly **per eligible
opportunity across all analyzed work**:

1. include every safely indexed analyzed session in the selected projects;
2. keep only exact compatible metric/provenance cohorts;
3. calculate each metric as ratio of sums,
   `sum(numerator) / sum(eligible denominator)`;
4. report selected/completed/missing sessions and incompatibility explicitly.

This slice is descriptive. It does **not** yet standardize task type or
complexity, estimate uncertainty, or claim a longitudinal improvement. A later
validated coaching estimand should first group compatible observations by task
type and complexity, standardize to a pinned personal reference mix, and report
retained mass, cluster count, and uncertainty.

Two alternative estimands may appear in an Advanced sensitivity view:

- **Typical session:** equal session weight;
- **Typical project:** equal project weight.

They answer different questions and never replace the default silently. Counts
are summed only when their unit, definition, deduplication, provider semantics,
and provenance are compatible. Missing, unknown, abstained, not-applicable,
incompatible, and execution-error states remain separate.

Initial safeguards are policy-versioned, not scientific constants:

- mark low coverage as provisional;
- withhold a trend/coaching claim when evidence is too small;
- disclose project dominance when one project supplies most eligible events;
- compute uncertainty by resampling whole sessions, not individual clauses;
- require the same estimand, task mix, provenance, and missingness policy for a
  longitudinal delta.

No cross-user ranking, percentile, leaderboard, or universal team score is
permitted. Team analytics is a separate future privacy/governance product, not
an extension of local self-coaching.

## API seam

The shipped bounded endpoint uses a project-selection request rather than
overloading the current session endpoint:

```text
ProjectQualityAggregateRequest
  project_ids: 1..25 unique pseudonyms
  selection_mode: all_analyzed_work

ProjectQualityAggregate
  estimand: per_eligible_opportunity
  aggregation_method: ratio_of_sums
  project/session/completed/missing counts
  identifier-free versioned metric cells and compatibility fingerprints
```

The application service resolves sessions through a bounded project-scoped
repository query and then invokes the existing ratio-of-sums core. No provider
read is triggered by selection, navigation, or comparison.

`typical_session`, `typical_project`, task-mix standardization, and interval
estimation remain future versioned estimands, not hidden alternatives in this
response.

## Validation gates

### Visualization

- Four to six axes per lens, fixed order and full names in the inspector/list.
- Pointer, keyboard, touch, screen-reader, reduced-motion, forced-colors, and
  320px/400%-zoom behavior.
- No horizontal page overflow, clipped labels, hover-only information, or
  color-only meaning.
- Unknown is never plotted as zero; measured zero is explicitly labelled.
- Comparison is blocked for incompatible axis sets or provenance.

### Metric validity

- Independently labelled, project/time-separated EN/PL holdout.
- Per-task-type precision, recall, abstention, selective risk, calibration, and
  counterfactual style/verbosity tests.
- Neural candidates must beat transparent rules/BM25 on the target construct.
- A metric remains experimental until it predicts its construct, not merely its
  rubric keywords. Objective task outcome is evaluated separately.

### Aggregation and privacy

- Golden ratio-of-sums and task-stratification tests; no percentage averaging.
- Cluster-aware uncertainty and project-dominance sensitivity tests.
- Default-deny mixed provenance and version-bridge tests.
- No text, IDs, labels, paths, evidence references, or model output in aggregate
  responses, screenshots, shares, errors, logs, or cache keys.
- Repository tests, frontend tests/build, OpenAPI parity, and privacy scan pass.

## Research basis

- Cleveland and McGill, graphical-perception accuracy:
  <https://doi.org/10.1080/01621459.1984.10478080>
- Albo et al., comparative evaluation of radial composite-indicator charts:
  <https://doi.org/10.1109/TVCG.2015.2467322>
- Fuchs et al., task-dependent glyph design in small multiples:
  <https://petra.isenberg.cc/publications/papers/Fuchs_2013_EOA.pdf>
- OECD/JRC, composite-indicator construction, weighting, and sensitivity:
  <https://doi.org/10.1787/9789264043466-en>
- QuantiDCE, human-guided quantifiable dialogue coherence:
  <https://aclanthology.org/2021.acl-long.211/>
- DiscoScore, discourse-coherence evaluation and limits of generic BERT scores:
  <https://aclanthology.org/2023.eacl-main.278/>
- TD-EVAL, turn- and dialogue-level task-oriented evaluation:
  <https://aclanthology.org/2025.sigdial-1.7/>
- Simpson, aggregation and stratification reversal:
  <https://doi.org/10.1111/j.2517-6161.1951.tb00088.x>
- Wilson, score intervals for proportions:
  <https://doi.org/10.1080/01621459.1927.10502953>
- NIST SP 800-188, de-identification risk and governance:
  <https://csrc.nist.gov/pubs/sp/800/188/final>
