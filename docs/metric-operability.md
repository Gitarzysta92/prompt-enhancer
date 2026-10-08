# All-20 metric operability

This is the release-facing map of how every canonical metric can obtain a
measured value. It is not a claim that every analyzed window contains the
required evidence. A missing opportunity set, link, or receipt remains
`unknown`; an experimental model estimate never becomes measured evidence.

The authenticated, content-free source of truth is:

`GET /v1/metric-contracts/v2/operability-catalog`

The response is bound to the current contract-set fingerprint, projection
identity, readiness catalog, and all twenty individual contract fingerprints.
It reports the exact counts below and is private/non-cacheable.

## Current release gate

| Gate | Count |
|---|---:|
| Shipped measured path when its evidence exists | 16 |
| Task-profile configuration still required | 0 |
| Provider/extractor or release composition still required | 4 |
| Experimental model-estimate path | 8 |
| Metrics for which a model may author the measured value | 0 |

## Per-metric map

| Metric | Measured path | Current release state | Experimental model path |
|---|---|---|---:|
| `prompt.task_definition_coverage` | Focus-owned fixed-factor rubric | Available when evidence exists | Yes |
| `prompt.problem_evidence_quality` | Focus-owned fixed-factor rubric | Available when evidence exists | Yes |
| `prompt.context_sufficiency` | Focus-owned fixed-factor rubric | Available when evidence exists | Yes |
| `prompt.constraint_precision` | Reviewed declared task-profile slots | Available when evidence exists | Yes |
| `prompt.acceptance_testability` | Reviewed outcomes plus distinct checkable clauses in the canonical active request | Available when evidence exists | Yes |
| `prompt.deliverable_contract` | Reviewed declared task-profile slots | Available when evidence exists | Yes |
| `collaboration.ambiguity_resolution` | Confirmed lifecycle evidence | Available when evidence exists | No |
| `collaboration.clarification_yield` | Confirmed lifecycle evidence | Available when evidence exists | No |
| `collaboration.exploration_conversion` | Confirmed lifecycle evidence | Available when evidence exists | No |
| `collaboration.scope_change_discipline` | Confirmed lifecycle evidence | Available when evidence exists | No |
| `collaboration.rework_candidate_rate` | Confirmed lifecycle evidence | Available when evidence exists | No |
| `logic.decomposition_coverage` | Native-confirmed complete user-clause classification plus active-requirement-to-plan evidence | Available when evidence exists | Yes |
| `logic.hypothesis_test_linkage` | Typed opportunity, link, and outcome receipts | Provider adapter required | No |
| `logic.decision_rationale_coverage` | Documented decision semantic units | Available when evidence exists | Yes |
| `logic.requirement_action_traceability` | Native-reviewed r6 active requirements plus an app-issued complete safe-action manifest, ephemeral redacted action details, and reviewed links/outcomes | Provider adapter required (no promoted provider yet proves the complete review surface) | No |
| `logic.open_loop_closure` | Explicit plan-to-superseding-action link | Available when evidence exists | No |
| `outcome.agent_claim_grounding` | Typed opportunity, link, and outcome receipts | Provider adapter required | No |
| `outcome.verification_strategy_adequacy` | Documented verification-strategy semantic units | Available when evidence exists | No |
| `outcome.first_pass_verification` | Reviewed task plus task-scoped verification receipt | Available when evidence exists | No |
| `outcome.verified_requirement_coverage` | Typed opportunity, link, and outcome receipts | Provider adapter required | No |

“Available when evidence exists” includes honest `unknown`, `pending`, and
`not_applicable` outcomes. For example, a collaboration family needs a
natively confirmed complete enumeration before it has a denominator, and
first-pass verification needs exactly one reviewed task owning the session.

## Local agent evidence files

The historical v1/r4 and current v2/r5 local-agent lifecycle-file workflows
cover the five collaboration families. The v2 file additionally binds the
exact sealed run and source-window fingerprint. An API-token client may fetch
the current contract, preview canonical JSON, and import an inert proposal. It
cannot confirm or reject that proposal. A separate same-origin browser session,
CSRF proof, exact confirmation literal, and non-self-issuable native
user-presence confirmation are required before a confirmed receipt can affect a
future sealed snapshot. Only an owned desktop window currently composes that
origin- and body-bound one-shot bridge. Standard `serve`, an attached window,
and unsupported hosts report confirmation unavailable and disable decision
controls. See
[`local-agent-metric-evidence-api.md`](local-agent-metric-evidence-api.md).

Projection r6 adds a separate `requirement-plan-evidence-file-v1` workflow for
`logic.decomposition_coverage`. The local API publishes the exact sealed-run,
window, contract, and predecessor recipe an agent needs to create canonical
JSON. The file contains bounded message/clause coordinates, untrusted structured
proposals, and a bounded untrusted producer/model label claim. Every visible user
request/feedback clause is classified as either
`active_requirement` or `excluded_from_active_requirement_denominator`.
Excluded clauses carry one closed reason: `not_requirement`, `superseded`,
`withdrawn`, `duplicate`, `out_of_scope`, or
`already_satisfied_or_closed`. Superseded and withdrawn clauses point to the
later user clause that changed their status; duplicates point to the distinct
active clause that owns the work. Only active requirements carry the closed
dispositions `linked`, `not_linked`, or `pending`.
There is no prose, score, authoritative-model-judgment, path, or objective-receipt
field. A safe-code-shaped producer/model label can still be content-like, so it
appears only in the submitted file and its ephemeral preview; persistence and
proposal responses retain only an application-keyed opaque commitment marked
untrusted. Preview and import remain inert. Every reviewable user
request/feedback clause must be classified exactly once, and uncertainty means
rejecting or leaving the proposal unconfirmed. Only a clause confirmed as an
active requirement becomes one coarse metric opportunity, so compound active
clauses are explicitly not model-split. `linked` requires a reviewed concrete
plan clause; `not_linked` additionally requires the person to confirm the
planning horizon is closed; otherwise an unlinked active requirement is
`pending`. The published recipe fails closed above 128 normalized clauses per
message. A first owned-native action opens every reviewable user request/feedback
clause and every agent plan clause from process memory, including omitted plan clauses. Only a second
owned-native action, exact full-review acknowledgement, and unexpired one-shot
receipt makes that graph eligible for the next sealed r6 run. The projector
revalidates every classification, exclusion basis, disposition, link, and
coordinate against the ephemeral source window. Missing authority stays
`unknown`; a complete native-confirmed classification with zero active
requirements is `not_applicable`; pending active requirements remain
right-censored.

Projection r7 adds a separate `requirement-action-evidence-file-v1` workflow for
`logic.requirement_action_traceability` and preserves the other nineteen r6
metrics. Its denominator is exactly the native-reviewed active-requirement set
bound to r6. The application, not the file producer, issues the same-window safe
action candidate manifest with complete extraction/enumeration provenance and
closed content-free metadata. For native review only, process memory also holds
the exact bounded redacted tool name, invocation, and result/effect descriptor
for each candidate; those strings are never persisted. A local agent file may
propose only the mapping
from each requirement to zero or more candidate indexes. It has no field for an
action state, objective proof, metric value, prose, or path. A bounded raw
producer/model label remains only in the file and ephemeral preview; durable
storage keeps an application-keyed opaque untrusted receipt.

The first owned-native action reviews every r6 active-requirement clause, every
candidate's redacted invocation/effect details, and every proposed membership.
A frozen one-pass display encoding visibly escapes control, bidirectional, and
layout characters without decoding literal escape text; the exact encoded view
is part of the review receipt. Each action also carries a versioned,
content-free metadata receipt derived from the same provider read as its
descriptor and exactly matched to the indexed safe-event candidate.
A second action confirms only the exact unexpired one-shot receipt and requires
explicit acknowledgement that the complete set was displayed and every linked
action's semantics were reviewed. Under that complete
authority, a requirement with any completed linked action is `met`; one with a
started or unknown-state linked action is `pending`; and a failed/cancelled-only
set or an explicitly empty link is `not_met`. None of those action outcomes is
objective proof of task success. A confirmed empty r6 active-requirement set is
`not_applicable`.

Every graph is bound to the exact r6 confirmation and evidence fingerprint,
sealed source run and window, safe-event decoder provenance, candidate-manifest
fingerprint, a process-keyed reviewed descriptor-set commitment that incorporates
the ephemeral same-read candidate-metadata receipts, keyed native-decision
authority, reviewed graph, and r7 confirmation. A stale source, changed r6
denominator, incomplete extraction/enumeration/review, overflow, or candidate
drift even under the same apparent window fails closed to a named `unknown`.
An exact, null-authority `binding_invalid` run marker distinguishes a stale or
incoherent prior confirmation from a proposal that has simply not been reviewed;
the latter alone remains `awaiting_review`.
Schema v56/Migration 56 is append-only: r1-r6 remain readable with their frozen
meaning and the r7 graph stores no model-authored metric authority, objective
proof, prose, or path. M56 also gives native r6 requirement-plan decisions an
installation-keyed authority sidecar. Only decisions explicitly captured at the
55-to-56 upgrade receive the one-time trusted-upgrade receipt; normal reads fail
closed instead of manufacturing a missing receipt.

This contract, API, and native review UI exist, but the release count above
deliberately remains 16/0/4 until at least one production provider proves a
complete safe-event enumeration and exact redacted descriptor surface. Codex's
current resumable snapshots remain incomplete, so UI composition alone is not a
shipped-path claim.

Extending this file format is not a shortcut around evidence authority. The
task-profile workflow is a separate, closed, native-confirmed editor: it stores an
immutable reviewed revision containing only constraint kinds, expected outcome
count, and deliverable slots. That revision and fingerprint are sealed into a
fresh r5-or-later run before any of the three profile metrics can become numeric. Null
means unconfigured and stays `unknown`; empty sets and caller-authored prose are
rejected. Objective evidence still must bind app-issued opportunity identities
to typed outcome receipts; an agent-authored claim that a test passed cannot
verify itself.

## Model boundary

The current experimental sidecar can attempt eight immediate metrics. Small
encoders estimate factor evidence; the optional deep judge adjudicates selected
disagreements. All model outputs remain uncalibrated and product-ineligible.
The sealed measured publication is computed only from deterministic reviewed
structure or typed receipts, so switching to a larger model cannot fill one of
the four remaining provider/extractor or release-composition gaps above.

The live factor router is deliberately smaller than the historical ten-slot
compatibility graph:

| Stage family | Live role |
|---|---|
| mDeBERTa XNLI | Multilingual factor NLI baseline |
| MiniLM-L6 NLI | Small multilingual factor expert |
| MiniLM-L12 NLI | Small multilingual factor expert |
| Qwen3 4B NF4 | Optional, bounded adjudicator for selected disagreements |
| Four retrieval and two reranking slots | Historical diagnostics; not factor classifiers and not executed by the live router |
| DeBERTa-long and ModernBERT challengers | Reviewed but live-disabled after the current synthetic/resource gates |

Thus a typical live run exposes three small stages and, only when eligible, one
deep stage. “Ten models” is an immutable historical receipt shape, not ten
independent metric authorities. Adding more stages is justified only by a
representative per-metric holdout showing incremental calibrated value within
the latency, memory, privacy, and failure budgets.
