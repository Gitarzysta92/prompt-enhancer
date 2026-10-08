# WP-14 — Evidence-bounded Coaching Loop

Status: **candidate integration; not calibrated**.

## User surface

The session dashboard presents five deliberately separate decisions:

1. objective outcome;
2. one observed-practice candidate;
3. one friction candidate;
4. one next-task experiment candidate;
5. one static prompt template to try.

It does not produce an overall score, cognitive-skill rating, intelligence
estimate, developer rank, or task-success claim from transcript text. The old
radar and individual metric receipts remain available only as optional
diagnostics.

## Current pipeline

1. A user explicitly starts the bounded local analysis for one selected
   session.
2. Provider text is projected and redacted in memory. The immutable analysis
   run persists only states, counts, fractions, safe signal codes, and pinned
   provenance.
3. The coaching projection reads those immutable content-free results. It does
   not read provider content or evidence identifiers.
4. A current reviewed-task decision supplies task type. No task, an ambiguous
   task mapping, or an unsupported task type causes coaching to abstain.
5. The versioned candidate policy filters by applicability, evidence class,
   denominator, coverage, task type, and coherent source provenance.
6. `GET /v1/quality-analysis/runs/{run_id}/coaching-summary` returns a closed,
   content-free decision receipt.
7. The frontend fail-closes unknown codes or structural contradictions and
   renders all prose from local static dictionaries.

## Models in production

No neural model or remote LLM currently establishes these coaching candidates.
The active path uses deterministic English/Polish candidate rules. Model
inferences are excluded from Coaching Loop v1 until a pinned local candidate
passes the private calibration and selective-risk gates. The optional local
model lab remains a separate experiment and cannot change coaching results.

Live provider verification classification is also validation-only. Therefore
the objective outcome normally remains **Unknown** today. Assistant completion
claims never count as verification.

## Truthfulness invariants

- Missing, Unknown, Abstained, Not applicable, measured zero, and execution
  failure remain distinct.
- Objective verification outranks human review; human acceptance is retained
  separately and cannot fabricate objective success.
- Candidate linkage uses a real similarity threshold, not single-token overlap.
- Duplicate outcome authorities and mixed coaching provenance fail closed.
- Uncalibrated coaching export is blocked.
- The UI accepts only closed enums and counts—never prompt-derived prose,
  identifiers, paths, excerpts, tool output, or arbitrary evidence labels.

## Validation before “recommended” status

The candidate surface must remain visibly uncalibrated until all of these hold:

- private, independently labelled English/Polish data split by user, project,
  and time;
- task-type-specific precision, recall, abstention, coverage, and selective-risk
  reporting;
- adversarial controls for verbosity, repeated domain nouns, order, correction,
  supersession, and model-name/style cues;
- a pinned local neural challenger that beats the deterministic baseline on an
  untouched holdout without remote fallback;
- prospective evidence that the experiment improves a later comparable task's
  objective verification or human acceptance outcome.

Until then, the surface says **candidate**, offers an experiment rather than a
prescription, blocks sharing, and never represents the result as a person score.
