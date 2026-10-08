# Real-metrics campaign ledger

This ledger records implementation evidence and release blockers. A completed
engineering check is not a claim that a metric or estimator is calibrated.
Private sessions, paths, prompts, model responses, credentials, caches, and
local runtime artifacts must never be added here.

## Campaign controls

- Branch: `codex/real-metrics-campaign`
- Merge policy: push coherent green commits; do not merge automatically.
- Data policy: synthetic fixtures for tests and review packets only.
- Review-loop limit: at most two critique/fix loops per phase.
- Phase order: baseline, P0, P1, P2, then optional P3 and P4.

## Phase status

| Phase | Status | Current scope | Acceptance gate | Open blockers |
|---|---|---|---|---|
| Baseline | Complete | Preserve and classify the inherited backend, frontend, model, test, and documentation work | Python, frontend, build, Playwright, privacy scan, clean worktree, and pushed commits | None |
| P0 | Complete | Runtime truth, readiness, visualization, previews, evidence contracts, durable jobs, local automation, Job Centre, exact metric scope, and revocation-safe result activation | Backend, frontend, build, real-loopback and browser E2E, privacy, migration-upgrade, cancellation, supersession, restart, and concurrent revocation gates | Current operability: 16 shipped conditional paths, 0 task-profile configuration gaps, 4 provider/extractor or release-composition gaps, 8 experimental model paths, and zero model-authoritative measured metrics |
| P1 | In progress | Sealed v17 calibration evidence, a durable execution-only runtime through objective evidence and BM25, repository-sealed non-comparable calibration reports, repository-sealed non-activating gate decisions, truthful local metric coverage, reviewed local automation admission controls, crash-safe invalid estimator-automation reconciliation, a restart-durable strict first-claim result-publication cutoff for reviewed automated `session_quality` work, bounded large-thread preparation, and a normalized ten-model local shadow ensemble with chunk-level receipts and a separate radar | Frozen private holdout, calibration, stability, privacy, latency, and abstention gates | No representative human-calibrated holdout, eligibility-capable decision or activation slot, calibrated or product-eligible model ensemble, force-stopping runtime deadline, or product-enabled estimator |
| P2 | In progress | Prospective capture and comparison contracts, untrusted comparison-stratum drafts, untrusted and repository-backed supplied-set raw-aggregation drafts, normalized synthetic-only temporal persistence, repository-issued synthetic comparison-stratum preparation and graph sealing, and bounded repository-sealed synthetic aggregation-validation receipts | Prospective comparable recommendation outcomes with missingness and adverse effects visible | Codex lacks authoritative per-item source timestamps and stable provider snapshot/cursor boundaries, so no Codex product source boundary exists; the new Claude Code hook surface supplies receiver-clock per-item timing (`EVENT_TIMING`) and a keyset-ordered ledger, but it is not yet reviewed as a product source boundary; there are no product snapshots, recommendations, or empirical recommendation-outcome/adverse-effect results, and no legacy backfill is permitted |
| P3 | Deferred; P3a contracts only | Optional cloud identity, pairing, entitlements, payments, and usage ledger. P3a adds development-only control-plane contracts, default-deny policy, signed content-free snapshot envelopes, cursored deltas, tombstones, audit evidence, and an in-memory adapter behind ports | Tenant isolation, revocation, deletion, balanced ledger, webhook replay, spend caps, and offline-local behavior | Owner approval and completed P2 required. P3a adds no deployment: no production identity provider, no Ed25519 adapter, no PostgreSQL adapter, no credential issuance, no billing, and no producer pipeline |
| P4 | Deferred | Teams, governance, aggregate-only sharing, RBAC, and privacy-preserving boards | RBAC, isolation, consent withdrawal, cohort-inference defense, deletion propagation, and accessibility | Requires P3 control plane and a separately reviewed sharing policy |

## Current all-20 operability truth (2026-08-24)

The versioned, authenticated
[`metric-operability-v4`](metric-operability.md) catalog derives its result from
the reviewed V2 contract registry, current r8 evidence-bound projection,
lifecycle registry, semantic-unit extractor set, objective evidence
requirements, and the exact capabilities and native workflows composed for the
current safe-event decoder. It still reports 16 metrics with a defensible
shipped path when evidence exists, none blocked on missing task-profile
configuration, four blocked on provider/extractor authority, and eight with a
separate experimental model-estimate path. Schema 59 and projection r8 append
an atomic exact-M58-revision binding and activate reviewed objective projection
v4 only for verified-requirement coverage. That durable authority does not by
itself prove a complete production-provider evidence surface or calibrate a
model path, so the release partition remains exactly 16/0/4 and no model stage
may author any measured value. Older checkpoint counts below are retained as
historical evidence and must not be read as the current release state.

### Reviewed task-profile and r5 evidence tranche (2026-08-21)

Schema v54 adds an append-only, content-free declared-profile revision ledger
and the profile-bound r5 state/seal sidecars. The owned-window native-confirmed profile editor can
configure only constraint kinds, expected outcome count, and deliverable slots;
null stays unconfigured/unknown and no prompt text is persisted. Run identity,
reuse, persistence, public binding metadata, and trajectory comparability all
include the exact profile source, revision, fingerprint, schema, and policy.
Current projection r5 preserves nineteen r4 rows and corrects acceptance
testability to count distinct checkable clauses owned by the canonical active
request, capped by the reviewed expected-outcome count.

The local agent metric-evidence boundary is append-only v2 for r5, binding both
the exact sealed run and source-window fingerprint. Historical v1/r4 files stay
readable under their original identity. Both formats remain proposal-only and
forbid scores, prose, objective-receipt claims, and self-confirmation. The
profile editor is a separate native-user-authorized workflow, not an expansion of
agent evidence authority.

### Reviewed requirement-to-plan and r6 evidence tranche (2026-08-21)

Schema v55 adds an append-only content-free requirement-plan proposal/decision
ledger and exact r6 run binding. The authenticated local API exposes the exact
sealed-run contract needed to create `requirement-plan-evidence-file-v1`, then
allows bounded canonical preview and inert import. Every reviewable user
request/feedback clause must be classified exactly once as
`active_requirement` or `excluded_from_active_requirement_denominator`.
Excluded clauses carry one closed reason (`not_requirement`, `superseded`,
`withdrawn`, `duplicate`, `out_of_scope`, or
`already_satisfied_or_closed`) and, where required, the later user clause or
distinct active owner that justifies exclusion. Uncertainty is never forced into
a false binary: the proposal is rejected or left unconfirmed. Only active
requirements become denominator opportunities; each compound active clause is
one disclosed coarse unit and is never model-split. `linked` requires reviewed
concrete plan evidence, `not_linked` requires explicit confirmation that the
planning horizon is closed, and other unlinked work stays `pending`. One native
action opens the complete ephemeral eligible user request/feedback and
agent-plan clause set, including omitted plan clauses, and a second one-shot
action confirms only its exact unexpired review
receipt and explicit acknowledgement. Submitted files contain coordinates,
closed classifications, exclusion reasons and bases, dispositions, and a
bounded raw producer/model claim that is explicitly untrusted and may be
content-like despite its safe-code syntax. That raw claim exists only in the
submitted file and its ephemeral preview and never enters durable rows or
proposal responses; those retain only an
application-keyed opaque commitment. Neither file nor durable graph has a
transcript-text, path, score, authoritative-model-judgment, or objective-receipt
field.

Projection r6 preserves nineteen r5 metrics and replaces only decomposition
coverage. Every coordinate is revalidated against the ephemeral source window;
the published splitter fails closed above its bound instead of truncating;
missing or invalid authority is nonnumeric, pending active requirements remain
right-censored, and a complete confirmed classification with zero active
requirements is no-opportunity. Readiness catalog v2-5 and
operability catalog v3 therefore move decomposition from an extractor gap to a
shipped conditional evidence path, producing the exact 16/0/4 partition while
keeping model-authoritative measured metrics at zero.

### Reviewed requirement-to-action and r7 evidence tranche (2026-08-21)

Schema v56/Migration 56 appends a content-free requirement-action
proposal/decision ledger, exact run binding, and r7 state/seal sidecars without
rewriting migrations 1-55. Historical r1-r6 publications remain readable under
their frozen identities. Mixed identities are rejected, an r7 seal requires its
exact twenty rows and inherited plus new authority bindings, and parent privacy
deletion cascades through the r7 graph.

M56 also appends an installation-keyed authority sidecar for native r6
requirement-plan decisions. Existing decisions are eligible for one explicit
trusted-upgrade receipt only when captured by the 55-to-56 migration and keyed
initialization; ordinary repository reads never mint a missing receipt.

Projection r7 preserves nineteen r6 metrics and replaces only
`logic.requirement_action_traceability`. Its denominator is exactly the r6
native-reviewed active-requirement set; it never re-extracts, model-splits, or
relabels requirements. The application issues the matching complete safe-action
candidate manifest for the same sealed run and window from content-free provider
events. Process memory adds bounded redacted tool, invocation, and result/effect
details for exact native review; those strings are never persisted. A local-agent
`requirement-action-evidence-file-v1` may propose only
requirement-to-candidate memberships. It cannot supply action state, objective
proof, metric values, prose, or paths. Its bounded raw producer/model label is
visible only in the file and ephemeral preview; durable rows retain only an
application-keyed opaque untrusted receipt.

One owned-native action opens every r6 active-requirement clause, every action
candidate's redacted invocation/effect details, and every proposed membership in
process memory. A frozen one-pass visible encoding escapes control,
bidirectional, and layout characters without conflating literal escape text,
and a versioned content-free receipt cross-checks each descriptor against the
candidate metadata derived from that same provider read. A second owned-native
action confirms only the exact unexpired
one-shot receipt after acknowledging the complete display and every linked
action's semantics. Under complete extraction,
enumeration, review, and confirmation, any completed linked action resolves its
requirement `met`; started or unknown-state links remain `pending`; and a
failed/cancelled-only set or explicit empty link resolves `not_met`. These are
action-traceability states, never proof that the task or requirement succeeded.
A confirmed r6 denominator with zero active requirements is `not_applicable`.

The r7 run binds the r6 confirmation and keyed evidence fingerprint, source run
and window, safe-event provenance and completeness, candidate-manifest
fingerprint, a process-keyed reviewed descriptor-set commitment incorporating
the ephemeral same-read candidate-metadata receipts, keyed native-decision
authority, reviewed graph, and r7 confirmation.
Missing authority, stale
source or predecessor, incomplete extraction/enumeration/review, overflow,
requirement drift, candidate drift even within the same apparent window, and
any fingerprint or provenance mismatch fail closed to a named `unknown`; a
null-authority `binding_invalid` marker distinguishes stale confirmed evidence
from a proposal that is merely awaiting its first review. A
partial number is never published. Readiness catalog
`metric-evidence-readiness-v2-6` names the service-required,
confirmation-required, binding-invalid, and receipt-bound-overflow cases.

The backend evidence contract and append-only identities exist, but release
operability deliberately remains 16/0/4 until a production provider proves a
complete safe-event enumeration and same-read redacted-descriptor authority. The
next logical evidence tranche is `outcome.verified_requirement_coverage`: reuse
the reviewed requirement identity, then add app-issued typed passing
verification or explicit acceptance authority. R7 action completion and model
or assistant completion claims are insufficient for that future metric.

### Reviewed requirement verification and r8 evidence tranche (2026-08-24)

Schema v58/Migration 58 durably records the exact app-issued verification
opportunity set and dense objective-result or owned-native-acceptance authority
history. Schema v59/Migration 59 then appends the content-free model-run binding,
dedicated r8 state sidecar, and r8 publication seal without rewriting M1-M58 or
reinterpreting r1-r7 history. Every new r8 run seals one closed source partition:
`unavailable`, `opportunity_bound_exceeded`, `awaiting_evidence`, or
`persisted_evidence`. A persisted binding includes the exact r6 identities,
opportunity and evidence fingerprints, through-revision (including revision
zero), current-head/result/acceptance/resolution/met counts, and all relevant
issuer/schema/policy/projection versions.

Projection r8 preserves nineteen r7 states and replaces only
`outcome.verified_requirement_coverage` through reviewed objective projection
v4. The complete app-issued r6 requirement-opportunity set owns the denominator;
only a current app-issued objective result or separately typed owned-native
acceptance can resolve an opportunity. Missing and partial evidence remains
nonnumeric, an empty reviewed set is no-opportunity, and neither action
completion nor assistant/model completion claims are accepted as proof. All
twenty typed receipts and the exact v4 provenance of the verified-requirement
typed row are sealed with the run.

Readiness catalog `metric-evidence-readiness-v2-7` names the r8 source,
revision, availability, pending, and bound conditions without describing native
acceptance as an objective verifier receipt. Operability catalog
`metric-operability-v4` points at r8 while deliberately retaining the exact
16 shipped / 0 task-profile-gap / 4 provider-or-composition-gap partition and
zero model-authoritative measured metrics.

## Baseline evidence

Checkpoint ending at `2a3969a` contains three coherent commits:

1. local analysis and model-evidence backend;
2. real local quality workspace frontend;
3. metric-validity and privacy documentation.

The checkpoint passed 659 Python tests with 4 skips, 256 frontend tests, the
production frontend build, 4 Playwright tests, and the repository privacy
scanner. The build reports a non-blocking bundle-size warning; it is tracked as
performance work, not hidden as a failure.

## P0 checkpoint evidence

Checkpoint ending at `bd9ffe7` adds four coherent P0 slices:

1. explicit `synthetic_demo` and `local_real` runtime composition with verified
   loopback health and fail-closed transport identity;
2. truthful 3-8-axis radar eligibility with exact-value bars below three axes;
3. versioned, content-free provider/session metric readiness for all 20 Coaching
   v1 metrics, including exact reason, required evidence, and next action;
4. a ten-minute, in-memory, one-shot redaction preview and approval backend that
   binds the exact session window, metric set, destination, model plan, redactor,
   retention class, size, and cost estimate without a second provider read.

The current Codex capability projection makes 13 of 20 metric structures
attemptable and marks 7 unsupported before any session content is read. This is
a documented evidence ceiling, not a failed model run, and unsupported values
are never synthesized or plotted as zero.

The checkpoint passed 682 Python tests with 4 platform skips, 283 frontend
tests, the production frontend build, the repository privacy scanner, and diff
validation. The remaining non-blocking frontend bundle-size warning is still
tracked. No remote model received session content, and no estimator was
activated.

The continuation checkpoint ending at `9149af8` adds four more coherent P0
slices:

1. the exact redacted-window preview and one-shot approval UI, including
   expiry, stale-session, and consumed-token handling;
2. versioned ephemeral `ACTION`, `DECISION`, `FEEDBACK`, and `VERIFICATION`
   evidence contracts, with objective verification receipts required;
3. a durable SQLite analysis queue and renewable local-only automation grants
   with leases, restart recovery, cancellation, retry bounds, supersession,
   progress, revocation, and private public DTOs that omit worker lease tokens;
4. a truthful Job Centre plus a real uvicorn/httpx loopback E2E covering consent,
   indexing, exact compatibility, preview/approval, 20-metric analysis,
   readiness, automation supersession/revocation, crash recovery, and canary
   absence from SQLite, files, and logs.

The combined continuation gate passed 703 Python tests with 4 platform skips,
313 frontend tests, 9 Playwright tests across responsive widths, the production
frontend build, and the privacy scanner. The exact test totals belong to this
checkpoint only; they are not estimator-calibration evidence.

The subsequent P0 checkpoints ending at `9afdedb`, `22752c7`, and `d4e129f`
closed the remaining scope, preview, and revocation conditions:

1. immutable analysis runs now persist their exact selected metric set;
2. `{A}` and `{A,B}` runs combine for compatible observations of `A`, while
   omission of `B` remains distinct from missing, failed, and legacy-unknown;
3. migrated scope is marked exact only when it can be proven, and migration 14
   repairs unprovable schema-13 classifications without changing migration-13
   checksums;
4. preview expiry uses both UTC receipt time and an internal monotonic deadline,
   with atomic one-shot redemption and rollback-clock tests;
5. automation result activation validates the exact job, grant, worker lease,
   provider, project, session, and metric scope in the same SQLite write
   transaction. A revocation that wins that transaction publishes no results;
6. project Automation settings, selected-metric execution, Job Centre, packaged
   route refresh, synthetic browser coverage, and local-real browser coverage
   are implemented.

The final P0 backend gate passed 795 tests with 4 platform-only symlink skips.
The last unchanged frontend gate passed 362 unit tests, the production build,
13 synthetic-browser tests, and 3 local-real browser tests. The privacy scanner,
compile checks, and staged-diff validation passed. These are engineering and
privacy gates, not calibration evidence.

Blinded, content-free P0 review packets were evaluated by GPT-5.6 Sol, Claude
Opus 5, and Claude Fable 5. All three returned `pass_with_conditions` with no
P0 blocker. Their bounded conditions are carried into P1/P2: persist a complete
gate manifest, measure performance and usability budgets, and never activate a
model without representative human calibration. Reviewer agreement is advisory
and is not ground truth.

## P1 foundation evidence

The first P1 foundation defines a content-free, versioned serial-cascade
contract and evaluation-math library. It records the complete estimator
configuration, exact execution and stage lineage, requested and served model
identity, local artifact digests, tokenizer and license identity, preprocessing,
question, prompt/rubric digests, reasoning effort, calibration/router/redactor
versions, fallback state, resource measurements, votes, uncertainty,
adjudication, and distinct unavailable, abstained, failed, and not-applicable
states. Candidate screening is capped at five models per family and promotion at
two; local model stages are explicitly serialized.

The evaluation functions cover correctness, retrieval, calibration, selective
risk, false-confident errors, agreement, EN/PL and task/provider/project/time
slices, repeat/order/format/injection stability, latency/resource/cost/failure
telemetry, and incremental cascade value. Their activation-check projection is
diagnostic only. It cannot write an activation slot, and its caller-supplied
facts are not trusted as release evidence. P1 persistence must derive holdout,
human-truth, privacy, and synthetic-origin facts from frozen immutable records
before any estimator can become eligible. Until that vertical slice and the
representative 100-200-judgment program exist, every estimator remains disabled.

The reviewed runner foundation adds only two bounded paths: exploratory Codex
CLI execution and explicit schema-validated manual native import. Subprocesses
use direct argument arrays, an empty temporary Git workspace, read-only sandbox,
strict ignored-user-configuration overrides, bounded stdin/stdout/stderr/workspace,
process-tree cancellation, sanitized errors, and exact structured output. The
installed CLI surface was checked directly before freezing the adapter. Codex
CLI activation-grade requests fail before disclosure because the documented CLI
does not provide a universal no-tool boundary. Claude consumer-subscription
automation is absent; its only supported path is manual export/import. No BYOK
or provider-network runner is implemented in this checkpoint.

The derived gate manifest accepts no caller assertions about eligibility,
holdout integrity, privacy, or synthetic origin. A pre-evaluation manifest
freezes only static case membership and project/time/slice assignments; the
completed cohort separately fingerprints predictions, confidence, run state,
latency, and reference judgments. The gate exact-matches those two projections
and requires split freeze and preregistration before every holdout evaluation.
It then reconstructs eligibility from holdout-access receipts, independent
truth/adjudication receipts, privacy scans, stability runs, performance, and
operational measurements. Missing evidence stays insufficient; synthetic,
consensus/self-reported truth, split leakage, fallback, privacy findings, or
unverified external execution boundaries reject. Codex CLI, manual import,
OpenAI API, and Anthropic API therefore remain activation-blocked until a
separately reviewed execution boundary and immutable provenance exist.

The local retrieval screen also adds `intfloat/multilingual-e5-base` as a
revision-pinned MIT/safetensors challenger with `trust_remote_code` disabled.
On the fixed 12-case fictional EN/PL screen it reached top-1 `0.833333`, MRR
`0.902778`, and Recall@3 `1.0`, with `453.488 ms` measured inference latency
and `1,078.121 MiB` peak CUDA allocation on this machine. This is a useful
screening result, not a promotion: the candidate remains exploratory and
product-disabled until the frozen representative private holdout and all
activation gates pass.

The official BGE-M3 repository was re-screened after a newer immutable revision
added a standard, safetensors-only XLM-RoBERTa path. The historical pickle-only
pin remains recorded as blocked. At the safe superseding pin, all required
weight, config, and tokenizer artifacts are hash-verified and remote code stays
disabled. Its 12-case full result was top-1 `0.666667`, MRR `0.819444`, and
Recall@3 `1.0`, using `2,179.602 MiB` peak CUDA memory. It tied E5-small, trailed
E5-base and Qwen, and used more accelerator memory, so it remains an unpromoted,
product-disabled challenger.

The first P1 persistence checkpoint adds a normalized, content-free schema for
synthetic estimator executions. Plans, immutable synthetic cases, evidence
packet receipts, serialized stage receipts, model runs, votes, probabilities,
opaque evidence references, and metric estimates are stored in relational
tables with immutable-child and parent-cascade-only deletion guards. No prompt,
excerpt, evidence body, model response, rationale, commentary, generic payload,
JSON, or BLOB field is available in this schema.

Execution integrity is checked independently by application contracts and
SQLite constraints. The stored response schema must match its exact plan stage;
always-run stages cannot be skipped; run and estimate timestamps must be inside
their serialized execution interval; a final model-cascade state requires a
selected vote supporting that state; known values require cited evidence; and
failed, refused, timed-out, out-of-memory, and cancelled attempts remain
distinct. Repeated stability executions are preserved, exact retries are
idempotent, and early cascade stops retain their reached-stage prefix.

Schema changes, checksum recording, and `user_version` advancement now commit
as one SQLite transaction without rewriting historical migration checksums.
Privacy deletion uses SQLite secure deletion and does not report completion
until the case cascade is committed and the WAL is cleanly truncated; a busy
reader produces a typed pending failure and a later retry proves durable purge.
The schema still accepts only synthetic executions and exposes no activation
write. Calibration cases, frozen private holdouts, adjudications, derived gate
decisions, and activation slots remain a later P1 checkpoint, so all estimators
remain product-disabled.

The first specialist foundation pre-screen is frozen before any private
evaluation. Its runnable set is exactly a deterministic objective-evidence
abstainer plus multilingual MiniLMv2 L6 and L12 NLI. The 24 fictional EN/PL
cases are a bounded plumbing and operability screen, not the planned
preregistered 96+ case promotion screen. Authored compatibility labels act as
an oracle gate; no scope router is evaluated and router metrics stay unknown.
The previously rejected multilingual mDeBERTa is historical only. BGE-M3
zero-shot and bounded Qwen configurations remain future, unfrozen candidates.
Retrieval models and similarity scores are not metric estimators and can never
be promoted as quality scores. Promotion remains limited to at most two
non-dominated configurations after the later preregistered screen; it is not
product activation.

The deterministic scope-router foundation is now implemented as a separate,
label-blind metadata decision. It routes only content-free project, session,
revision, requirement-version, applicability, supersession, and evidence-kind
identities into five closed states: compatible, different scope, superseded,
insufficient evidence, or not applicable. Unknown evidence is never converted
to zero. The frozen synthetic corpus contains 30 distinct scenarios repeated
across four reporting strata; the report therefore records 30 effective cases,
not 120 independent cases, and explicitly fails the planned 96-case promotion
threshold. The router is contract evidence only and remains product-disabled.

The provisional activation-gate v2 contracts now bind the complete stored
estimator plan, all expected attempts, requested and observed identities,
authoritative candidate projections, blind human labels, and state-aware
stability trials. The in-memory decision type cannot represent an eligible
outcome: immutable persistence is an unconditional insufficient-evidence gate.
This prevents synthetic or caller-constructed receipts from activating an
estimator while the durable calibration evidence ledger is still absent.

Schema v16 adds the first frozen private-calibration commitment without storing
private observations or results. A preregistered campaign binds one previously
stored non-synthetic plan, one exact provider/schema identity, exactly one
versioned metric question per metric, a complete case-assignment manifest, a
project/time split, gate policy, full model constellation, and both legacy and
v2 preregistration receipts. Every planned question must be represented before
the campaign can seal. Application and raw-SQL boundaries enforce the same
lineage, canonical-time, control-character, finite-number, and safe-identifier
rules. Activation remains fixed false.

Campaign deletion securely removes all campaign-owned identifiers from the
main database and SQLite WAL/SHM before reporting success. A domain-separated
revocation digest prevents the same erased campaign identity from being
recreated during or after checkpoint retry without retaining the original
identifier. Global plans and gate policies remain immutable. That next gate,
the normalized v17 evidence journal, is now implemented; repository-derived
reports, sealed gate decisions, and activation remain later work.

Checkpoint `2068b5a` implements that v17 journal as normalized, content-free
SQLite evidence. It stores the exact expected-attempt manifest, launch and
terminal receipts, served identities, independently verified structured
estimate receipts, holdout-access events and gaps, objective truth, blind human
judgments and adjudication, privacy findings and scans, stability trials, and
bounded resource, token, queue, and cost provenance. Partial append/restart,
exact replay, concurrent conflict handling, final sealing, hydration, and
privacy deletion are covered without adding a generic payload, transcript,
prompt, response, path, URI, or commentary field.

The v17 trust boundary is repository-owned and fail-closed: structured
estimates require an independent decoder, the sealed root is written last,
hydration recomputes aggregate counts and fingerprints and revalidates the
static v16 campaign lineage, and connection-bound authorization plus SQLite
guards reject raw inserts, deletes, authorization hijacks, and post-seal
appends. Secure deletion must also purge the WAL before success is reported.
The schema contains no calibration-report, gate-decision, or activation table.
Its checkpoint passed 1,143 backend tests with 4 platform skips, compile checks,
the privacy scanner, and adversarial review; those gates prove implementation
integrity, not calibration quality.

Checkpoint `c261ed2` adds fixed calibration-report contracts and deterministic
math over caller-supplied hydrated v17 domain objects. The comparison identity
binds metric semantics, the stored plan, gate policy, assignments and split,
preregistration, submission, served runtime identities, resource provenance,
source bundle, and report-definition versions. Classification, coverage,
selected-confidence calibration, selective risk, independent-human agreement,
stability, missingness, and bounded operational measurements preserve explicit
known, insufficient, unsupported, not-applicable, and incompatible states.
Insufficient scopes emit no numeric detail rows, selective coverage uses the
full eligible known-truth population, partial resource observation stays
missing, human pairs must name distinct participants, and numeric truth is
preserved without pretending that numeric performance has been evaluated.

This report checkpoint is deliberately not trusted release evidence. Every
report has `repository_owned=false`,
`persistence_state=untrusted_projection`, `comparison_allowed=false`, and
`activation_allowed=false`; private export and team sharing are also disabled.
Brier score, log loss, calibration slope, retrieval quality, cold/warm latency,
throughput, disk use, cascade stop rate, cascade incremental value, and numeric
stability/tolerance remain unsupported when their required receipts are absent.
A later repository migration must rederive the complete report from sealed
rows using a repository clock and reproduce its fingerprint before comparison
or gate evaluation. No report persistence, gate decision, or activation was
added by `c261ed2`. Its focused 20-test contract suite, compile checks, privacy
scan, diff validation, and adversarial review passed; none converts the output
into trusted calibration evidence.

Checkpoint `0fabec0` adds the first durable estimator execution runtime without
weakening the synthetic-calibration or product-metric boundaries. A one-shot,
local authorization is consumed atomically with an exact job, session, project,
provider, plan, question, metric, redactor, source-window, and packet binding.
The worker persists append-only state, stage-attempt, terminal-outcome,
checkpoint, objective-observation, and BM25 retrieval receipts. Queue scope,
grant scope, packet provenance, stage fingerprints, attempt order, and terminal
state are independently sealed in application and SQLite boundaries.

This runtime deliberately stops after objective/readiness and BM25 with state
`partial` and reason `local_model_runtime_not_enabled`. It does not enter local
embedding, reranking, specialist, second-opinion, or adjudication stages; it
does not create calibrated votes or estimates; and it never writes the product
`metric_results` projection. Crash and lease recovery record interrupted
attempts or repair already-durable outputs into exact outcomes and checkpoints
without duplicate receipts. Generic queue APIs cannot create or mutate an
orphan estimator execution. Secure deletion retains only the registered safe
plan and does not report physical purge until the WAL is truncated. The final
gate passed 1,223 backend tests with 4 platform skips, privacy and compile
checks, and two adversarial review rounds. These results prove the bounded
runtime implementation, not model validity or activation eligibility.

Checkpoint `0b45b47` persists the complete calibration report as normalized
schema-v19 data. Its sole write command accepts only a sealed v17 submission
identifier; within one `BEGIN IMMEDIATE` transaction the repository hydrates
and revalidates the exact v16 campaign and v17 evidence, captures one repository
timestamp, rederives the unchanged untrusted report, writes every definition,
scope, measurement, detail, resource, missingness, and metric root, then seals
the report root last. Replay preserves the timestamp and fingerprint, while
conflicting or partial writes fail atomically.

The structurally constructible sealed receipt is explicitly not a capability.
Repository reads rehydrate and fully rederive the v16/v17/report graph before
returning it; connection-bound authorization guards reject stale, forged, or
cross-report writes. Missing and unsupported measurements remain `NULL` with
their explicit state and never become zero. Campaign privacy deletion cascades
the report and still requires secure WAL truncation before success. The report
remains `comparison_allowed=false`, `activation_allowed=false`, and private
export/team sharing false. No gate-decision or activation table was added. The
checkpoint passed 1,241 backend tests with 4 platform skips, focused/adjacent
report gates, privacy and compile checks, and independent adversarial review.

Checkpoint `7704ed6` adds repository-sealed gate decisions as normalized
schema-v20 data. Its public write command accepts only a sealed v19 report
identifier, then rehydrates and independently rederives the exact v16 campaign,
v17 submission, and v19 report lineage in one repository transaction before
writing the decision root last. The code-owned decision vocabulary covers every
registered metric, required stratum and language, subgroup dimension, high-risk
rule, and identity, access, privacy, and stability gate. In the frozen
single-metric fixture, adversarial hardening expanded the initial 83-check
projection to 85 checks by making cold- and warm-latency sample sufficiency
explicit; real vocabulary size remains derived from the registered campaign.

The decision outcome has only `rejected` and `insufficient_data`; there is no
eligible state. Missing or unsupported evidence never becomes zero or a failed
measurement, and an all-pass release root is structurally invalid. A clean
synthetic lineage remains insufficient because activation-grade evidence is
absent, while repository-proven violations reject. The sealed decision keeps
`activation_allowed=false`, `activation_slot_written=false`,
`comparison_allowed=false`, private export false, and team sharing false.
Schema v20 contains no activation slot or activation API. The checkpoint passed
1,312 backend tests with 4 platform skips, privacy and compile checks, and
independent adversarial review. This proves decision integrity, not estimator
eligibility or product activation.

Pushed checkpoint `ac84a40` (`Expose truthful local metric coverage`) adds an
authenticated, content-free, counts-only coverage report and matching local UI
for the provider catalog or one project. It reports an exact local SQLite
snapshot while explicitly leaving provider-history completeness unknown. Latest
attempt status is kept separate from the latest completed Coaching snapshot;
contract-compatible, contract-incompatible, and absent results remain distinct,
and per-metric provenance cohorts are not merged. The Codex descriptor still
makes 13 of 20 metric definitions structurally attemptable; this is structural
evidence-channel support, not a claim that 13 metrics were measured in any
session.

Automation coverage in this checkpoint means only that a metric is selected by
at least one bounded active local grant. It proves neither completed execution
nor full-catalog automation coverage. The report grants no product/source or
population-completeness authority, and no comparison, snapshot, recommendation,
or outcome authority. It therefore improves P1 measurement/readiness visibility
and local P2 coverage diagnostics without changing either phase's acceptance
gate or blockers.

Frozen engineering evidence for the exact
`ac84a4080ba6f5f40010576970dbc71daaf94587` tree is 1,817 passing backend tests,
4 expected platform-only symlink skips, and one existing warning; 385 passing
frontend tests; a successful production build; and 13 passing Playwright tests.
The privacy scan, compile checks, and diff validation passed, and independent
backend and frontend reviews returned `PASS`. These are implementation and
privacy results, not calibration, product-history, or recommendation evidence.

Pushed checkpoint `a05c1e3` (`Enforce reviewed automation admission policy`)
turns the previously persisted automation resource receipt into a narrow,
truthful admission boundary. New grants and renewals accept only the reviewed
balanced profile: one per-grant CPU admission lane, a GPU ceiling of one with
zero current session-quality GPU use, battery/unknown power admission pause,
and a declared 1,800-second runtime budget. Historical broader profiles remain
readable and revocable, but they cannot be renewed, scheduled, claimed, or used
to launch estimator work.

The scheduler checks the exact profile before provider, session-candidate, or
job access; current consent is checked before a fresh per-grant power sample.
Battery and unknown power pause only new admission and leave queued attempts and
leases unchanged. They do not interrupt already-running work. SQLite claim
admission runs under `BEGIN IMMEDIATE`, revalidates the live grant, project,
provider, ordered metric scope, local boundary, and exact resource profile, and
allows at most one unexpired active job per grant without starving manual work
or work for another grant. Invalid non-estimator automation rows receive only a
closed set of content-free reconciliation codes. Invalid queued estimator rows
are not claimed and remain queued, unleased, zero-attempt, and unread because
their append-only runtime requires a separate reviewed reconciliation path.

This checkpoint does not enforce the declared 1,800-second budget as a hard
runtime deadline, pause work in progress, allocate a GPU worker, enable a model
stage, validate any metric, or activate an estimator. The API, OpenAPI schema,
and UI expose those limitations directly, and no schema migration was needed.
The remaining hard runtime deadline and estimator-specific cleanup are still
P1 work; the representative human-calibration and activation blockers are
unchanged.

Frozen engineering evidence for the exact
`a05c1e3a8718b19aa1ab8e79a46cbd2e95cddff0` tree is 1,867 passing backend
tests, 4 expected platform-only symlink skips, and one existing warning; 390
passing frontend tests; a successful production build; and 13 passing
Playwright tests. The privacy scanner, compile checks, and diff validation were
green, and two independent read-only reviews returned `PASS`. These results
prove admission, concurrency, failure, and interface integrity, not estimator
calibration, product metric correctness, or outcome evidence.

Pushed schema-v24 checkpoint `37e6389` (`Reconcile invalid estimator
automation runtimes`) closes the queued-estimator liveness gap left by the
admission checkpoint. Before a generic claim, the estimator runtime now scans
only content-free, repository-bound `automation_once` metadata under
`BEGIN IMMEDIATE`. Missing, revoked, expired, unsupported-profile, and exact
provider, project, destination, local-boundary, route, and ordered-metric-scope
mismatches resolve through a closed reason-code priority. No session identity,
evidence packet, source text, provider API, model, or power state is read.

For a clean `CREATED` runtime, reconciliation appends one exact `CANCELLED`
runtime receipt and closes the queue in the same transaction. A requeued
`RUNNING` runtime must have a valid attempt generation, no open stage attempt,
no terminal-checkpoint anomaly, contiguous completed-stage history, and no
state, checkpoint, or outcome timestamp later than the repository cleanup
clock. It then seals one terminal checkpoint per bound metric before the
runtime state and queue. Faults roll back checkpoints, runtime state, queue
state, and transient HMAC authority together; concurrent and repeated cleanup
is idempotent.

A separate legitimate crash ordering can commit an existing runtime
`PARTIAL`, `FAILED`, `CANCELLED`, or `SUPERSEDED` receipt before queue finish
fails and requeues the job. Reconciliation preserves that exact prior outcome
and reason rather than relabeling it as grant cancellation. Migration v24 adds
no table, column, backfill, or content surface: it only permits queued
estimator-to-`PARTIAL`/`FAILED` convergence when the latest bound sealed runtime
receipt has the exact requested state and reason. The independent runtime
terminal-seal trigger remains in force, and migrations v1-v23 and their
checksums remain unchanged.

This checkpoint does not interrupt an already executing blocking call, enforce
the declared 1,800-second budget, read or calculate a metric, enable a model
stage, establish calibration, create an eligibility or activation slot, or add
an HTTP, CLI, or UI surface. Active execution invalidation remains governed by
the existing cooperative runtime authority and lease-recovery boundaries.

Frozen engineering evidence for the exact
`37e638901289075dfd837f3e90f520efed23ffd7` tree is 55 estimator-runtime tests,
8 direct v24 migration tests, a 324-test adjacent gate, and the full backend
suite with 1,895 passed, 4 expected platform-only symlink skips, and one
existing Starlette deprecation warning. The privacy scanner, compileall, and
diff validation passed, and an independent adversarial review of the frozen
chronology, rollback, concurrency, idempotence, and migration boundaries
returned `PASS`. These results prove local queue/runtime convergence integrity,
not estimator validity, calibration, product correctness, or outcome evidence.

Pushed schema-v25 checkpoint `49e9cb7` (`Enforce automation
result-publication cutoff`) adds a strict 1,800-second result-publication cutoff
for reviewed automated `session_quality` jobs only. The first successful claim
atomically persists an immutable start/deadline root and high-water mark bound
to the exact reviewed grant revision and ordered metric scope; retry, lease
recovery, and process restart cannot reset it. Migration v25 performs no
backfill and preserves migrations and checksums v1-v24. An already-attempted
legacy automation job without that root fails closed before reclaim with
`automation_publication_deadline_missing`. Manual jobs and estimator executions
are unchanged.

The repository accepts the bound run's result, evidence, and signal graph plus
an immutable accepted-publication receipt in one transaction only when
publication is strictly before the cutoff; equality and later are rejected
without partial derived rows. Fixed content-free closures distinguish
`automation_publication_deadline_exceeded`,
`automation_publication_clock_regressed`, and
`automation_publication_deadline_missing`. Once accepted, the receipt outranks
later finish, retry, cancellation or revocation, supersession, recovery, claim,
renewal, and stage bookkeeping, including after restart, so an on-time
publication converges to `COMPLETED`. Transient repository authority seals
these writes and is removed on commit or rollback; explicit privacy deletion
removes the publication graph under the existing local deletion boundary.

Worker and analysis-service checkpoints combine the persisted UTC high-water
mark with a process-local monotonic observation around provider reads, feature
extraction, every selected metric calculator, result validation, and atomic
persistence. They stop cooperatively at checked boundaries; they do not
forcibly preempt an in-flight blocking read or calculation. The API, OpenAPI
schema, and UI expose that separation directly: the session-quality
result-publication cutoff is enforced, blocking-call preemption is not
provided, and the maximum-session hard runtime deadline remains unenforced.
Publication timestamps remain internal while only fixed content-free reason
codes cross the browser-safe job surface.

Frozen engineering evidence for the exact
`49e9cb71c36329c60140bf8bf9c9e3c7d06d1f2c` tree is 34 dedicated v25
persistence tests, a 159-test application/persistence/temporal gate, a 98-test
manual and estimator adjacency gate, and the full backend suite with 1,948
passed, 4 expected platform-only symlink skips, and one existing Starlette
deprecation warning. All 390 frontend tests and the production build passed.
The privacy scanner, compileall, OpenAPI generation, and diff validation were
green, and an independent adversarial review of the frozen cutoff, restart,
raw-SQL, accepted-publication, privacy, and migration boundaries returned
`PASS`.

This checkpoint does not establish metric or estimator calibration, an
eligibility-capable decision, activation, a calibrated model stage, a
force-stopping runtime deadline, or product estimator evidence. P1 remains in
progress. P2 scope and blockers are unchanged, and P3 and P4 remain deferred.

Pushed checkpoint `cc7ef55` (`Clarify bounded source-limit failures`) replaces
the coaching and local model-link surfaces' misleading whole-session limit and
identical-retry behavior with an exact, content-free failure taxonomy. Bounded
provider-session selection, local transport frames, allowlisted thread parsing,
and focus-window selection now have distinct fixed reason codes; the earlier
generic resource-limit code remains only as a conservative compatibility
fallback. Provider exception text and source content do not cross the HTTP
boundary.

The UI now states the actual read order: Codex returns a selected session to a
size-limited local adapter before Prompt Enhancer allowlists, redacts, and
selects the smaller preview or experiment window. The advertised 100-message
and 100,000-redacted-character values describe that selected window; they are
not a claim that an arbitrarily large provider response can be streamed or
partially parsed. A fixed source-limit failure creates no preview, metric, or
model-link result and is terminal for that unchanged request, so the browser no
longer offers a retry that would immediately repeat the same session, adapter,
and limits.

This checkpoint improves failure truth and recovery guidance only. It does not
raise local bounds, add provider-side bounded reads, make the failed large
session analyzable, persist partial content, call a remote model, establish
metric validity, or change the P1/P2 authority boundaries.

Frozen engineering evidence for the exact
`cc7ef5598c4187c5813bf6c88ef986ef90af5dfa` tree is an 82-test focused
source/API gate, an 81-test analysis/model-link adjacency gate, and the full
backend suite with 1,965 passed, 4 expected platform-only symlink skips, and one
existing Starlette deprecation warning. All 401 frontend tests, the production
build, and 13 Playwright tests passed. The privacy scanner, compileall, OpenAPI
generation, and diff validation were green. These results prove bounded error
classification and interface behavior, not provider-history completeness,
large-session support, calibration, product correctness, or outcome evidence.

Pushed checkpoint `aa3c43e` (`Project newest bounded Codex thread suffix`)
adds content adapter `0.4.0`, canonical content schema
`codex-thread-item-text-v5`, and decoder version 5. After the unavoidable
complete local `thread/read` response is decoded, the allowlisted parser walks
newest-to-oldest within fixed turn, per-turn item, total-item, fragment, and
character budgets. It retains whole allowlisted items, restores chronological
order, and marks the projection incomplete whenever older structure is
omitted. Omitted older item payloads do not enter the boundary DTO, preview,
metric engine, persistence, logs, or HTTP response.

Aggregate old-history overflow is therefore no longer a terminal parser error:
a large thread can produce its newest bounded redacted preview. Malformed
selected structures, an individually oversized text fragment or user-content
shape, unknown required wire shapes, and a provider response above the separate
32 MiB transport ceiling still fail closed. This is a bounded local suffix, not
a complete-session claim; the 100-message and 100,000-character preview window
is selected only from that suffix, and `text_extraction_complete=false`
preserves the missing-evidence boundary.

This checkpoint does not add provider-side pagination or streaming, raise the
transport or individual-message bounds, persist source text, establish metric
calibration, or change P1/P2 authority. Existing stored runs retain their
original adapter and content-schema provenance.

Frozen engineering evidence for the exact
`aa3c43e60c3516b13470c7b0bb78d57ae5bb2cac` tree is a 66-test parser,
compatibility, and transport gate; a 119-test analysis/model-link/readiness
adjacency gate; and the full backend suite with 1,971 passed, 4 expected
platform-only symlink skips, and one existing Starlette deprecation warning.
The 88 focused frontend boundary tests and production build passed. The privacy
scanner, compileall, and diff validation were green. These results prove the
bounded suffix and failure semantics, not provider-history completeness,
calibration, product correctness, or outcome evidence.

Pushed checkpoints `a6c98d3` (`Confirm stored local analysis results`) and
`2aafda3` (`Measure complete bounded history windows`) close two real-browser
failures in the same local analysis path. Approval no longer closes without an
explicit content-free receipt: only after the immutable completed run has been
fetched and validated does the dialog erase its sensitive preview, state that
the result was stored locally, explain that individual Unknown or Abstained
values are still possible, and offer `View stored results`.

The Codex adapter is now `0.5.0`, canonical content schema
`codex-thread-item-text-v6`, decoder version 6. Source-history truncation and an
unclassified retained omission are separate fail-closed facts. When the parser
has retained a newest classified suffix and the 100-message/100,000-character
analysis window closes before that suffix's left boundary, that selected window
is complete for metric calculation even though older provider history remains
explicitly truncated. If the window reaches the truncated boundary, or any
retained structure is unclassified, extraction remains incomplete and the
calculators still abstain. The window fingerprint binds both the effective
window-completeness decision and the underlying source-history states.

The previous `0.4.0` contract made every metric abstain on a large session:
successful prefix truncation set `text_extraction_complete=false`, and the
metric engine correctly interpreted that as incomplete evidence inside the
selected window. In a local-real browser replay against the affected session,
the pre-fix profile had zero radar plots and blanket visible abstentions; the
corrected run completed, stored, rendered a radar, removed the fallback, and
removed those blanket abstention cards. This is real workflow evidence, not a
synthetic claim about all possible provider sessions.

Frozen engineering evidence for the exact
`2aafda3dafa5599e8ade67c37bd2ba1f27f43562` implementation tree is 144 focused
ingress, metric-pack, compatibility, service, and API tests plus the full
backend suite with 1,974 passed, 4 expected platform-only symlink skips, and one
existing Starlette deprecation warning. All 401 frontend tests and the
production build passed for the completion-receipt UI. Compileall, the privacy
scanner, and diff validation were green. This does not claim complete provider
history, model calibration, or model-backed product scoring: the active
coaching path remains deterministic EN/PL rules with exact model `none`; the
Qwen and BGE paths remain separate, synthetic, and activation-disabled.

Pushed schema-v26 checkpoint `1c19359` (`Add chunked ten-model shadow
ensemble`) makes the previously failing large-session path usable without
claiming unbounded provider-history coverage. Codex text adapter `0.7.0`,
canonical content schema `codex-thread-item-text-v8`, and decoder version 8
raise only the text-analysis `thread/read` frame and timeout ceilings, retain a
newest bounded allowlisted suffix of at most 1,000,000 admitted characters,
and split oversized admitted text into bounded segments before redaction. The
analysis and model paths still operate on the explicit selected window of at
most 100 messages and 100,000 redacted characters. The provider API still
returns a complete local thread frame before this adapter can project it, and
the selected window is not complete provider history.

The opt-in shadow pipeline partitions that approved redacted window into at
most eight exhaustive contiguous chunks. Four pinned retrieval experts and two
pinned rerankers combine bounded evidence rankings with reciprocal-rank fusion;
three scoped-NLI experts and one structured-rubric expert emit four fixed-role
votes for every persisted chunk-and-metric cell. Only the two reviewed NLI
challengers plus the rubric participate in the conservative decision; the
historical mDeBERTa candidate remains diagnostic. Each metric has one eligible
owned observation in the current shadow policy; structural matrix cells do not
enter its denominator. Unknown, unsupported, failed, and abstained observations
remain separate. The session value is a ratio of validated known observations,
never an average of heterogeneous model logits, and non-known observations are
omitted rather than converted to zero.

All ten immutable public model revisions execute sequentially in separate
local child processes. Each child is network-closed after an explicit model
preparation step, chooses CUDA, MPS, or CPU under the reviewed runtime, emits
only bounded content-free output, and exits before the next model so its RAM
and accelerator allocation are released. Schema v26 performs no backfill and
preserves migrations and checksums v1-v25. It normalizes content-free chunk,
expert, evidence-selection, vote, chunk-metric, session-metric, and root-last
graph-seal rows. Exact rehydration rederives the full graph fingerprint before
commit and on read; privacy deletion uses secure deletion and WAL truncation.
No chunk text, model prompt, model response, fragment identity, source-window
fingerprint, or request fingerprint crosses the authenticated private,
no-store HTTP projection.

The Prompt Quality and Reasoning Quality pages now expose an explicit
`Run 10 models locally` action, content-free progress and model/unload
receipts, source-window completeness, per-chunk state counts, and a separate
direction-adjusted shadow radar. The deterministic product metric view is
unchanged. A radar requires at least three known values; missing states stay
visible and never become zero. The UI labels the ensemble `not_assessed` and
`product_metric_eligible=false` and warns when retained source coverage is
incomplete.

Frozen engineering evidence for the exact
`1c193594fee8d51d1317a00a089951e8a25d3dbb` tree is 18 direct chunk,
persistence, migration, service, and API tests; the full backend gate with
1,993 passed, 4 expected platform-only symlink skips, and one existing
Starlette deprecation warning; all 407 frontend tests; and the production
build. Compileall, the privacy scanner, OpenAPI generation, and diff validation
were green. A fictional child-process smoke completed all ten pinned stages on
CUDA, and a content-free local-real browser replay of the previously failing
selected session completed all ten model stages, rendered the shadow radar,
rehydrated it after reload, and left the deterministic analysis path working.

This proves bounded execution, isolation, unloading, aggregation arithmetic,
persistence, privacy projection, and UI integration. Model agreement, including
agreement with a more capable agent, is not ground truth. There is still no
representative independently labeled private holdout, rater adjudication,
project/time-stratified calibration, threshold selection, stability or fairness
evidence, or product activation authority. The ensemble is therefore useful
only as an uncalibrated local shadow analysis. P1 remains in progress; P2 scope
and blockers are unchanged, and P3 and P4 remain deferred.

The continuous-shadow continuation adds two additive schemas without changing
that authority. Schema v27 retains Codex `updatedAt` only long enough to derive
an installation-keyed 64-hex activity revision; the raw provider timestamp is
not persisted. Schema v28 stores one explicitly enabled, content-free session
watch with a renewable execution lease, ten-stage progress, retry state, and an
exact sealed-run/input binding. One partial unique index makes that watch the
single process-wide model lane. Disabling or deleting its indexed session or
project removes the scheduling authority without retaining content.

Chunking is now `append-stable-redacted-v3`: fingerprints include message scope,
focus identity, and an already-redacted fragment digest, but not the whole
source-window fingerprint. Observation policy `owned-observation-v1` assigns
each prompt metric to one complete focus-request observation and each
conversation metric to one chronological bounded-window observation. Other
chunk-matrix cells are structural and excluded from analytic counts. Exact
unchanged inputs reuse their sealed run before inference; changed inputs do not
partially copy decisions until observation lineage is persisted. Every dirty update still runs the four retrieval, two reranking,
three NLI, and one rubric stages serially. A child process is killed if its lease heartbeat fails,
and CUDA resource exhaustion retries the same pinned stage on CPU only after the
CUDA child exits. The scope contract now carries role, kind, language, and focus
identity into inference. Prompt metrics admit only focus-user request evidence,
outcome metrics and hypothesis-to-test linkage stay unsupported without
objective artifacts. Neutral, failed, unsupported, or agreed-negative model
evidence cannot become a known zero without a typed opportunity receipt.

The dashboard polls the content-free watch receipt, preserves a fixed radar axis
set across generations, and leaves non-known values unplotted rather than at the
center. An optional `prompt-enhancer desktop` Windows host opens only the fixed
overlay route in a normal, resizable, minimizable, always-on-top Edge WebView2
window. It authenticates an existing loopback listener before rendering, starts
one only when the port is free, and stops only an instance it owns. Tokens and
session identifiers do not enter its URL, arguments, title, bridge, or output.

Engineering evidence for this continuation is the full backend gate with 2,039
passed and 4 expected platform-only symlink skips, all 423 frontend tests, the
production build, focused append/reuse/CPU-fallback/watch/desktop tests,
compileall, the privacy scanner, and diff validation. A fictional schema-v2
child-process smoke then completed all ten pinned stages serially on CUDA with
one bounded output row per stage. This is execution and privacy evidence only.
The ten stages are heterogeneous evidence roles, not ten independent estimates
whose arithmetic mean is calibrated truth. P1 remains in progress pending
representative adjudicated labels, calibration, stability, selective-risk,
fairness, latency, and activation evidence. P2, P3, and P4 are unchanged.

## P2 foundation evidence

Checkpoints `249f6c0` and `4db7052` define a prospective, content-free temporal
history and capture-lineage vocabulary. The contracts cover exact last-N,
rolling, and custom UTC windows; typed raw aggregation inputs and uncertainty;
independent selection, source, and value states; fully versioned comparison
identities; prospective history-root epochs; CAS-linked project metric
selections; direct selected-window input receipts; conservative session
revisions; typed observation batches; and an exact completion graph. The graph
requires one root, project, session, selection, run, input window, revision,
batch, observation scope, provider identity, and preprocessing/redaction/router
provenance to agree rather than inferring compatibility from timestamps or row
counts. The combined contract gate passed 67 focused tests plus the privacy and
compile checks.

Checkpoint `083ce8f` corrects the prospective capture vocabulary before any
schema depends on it. It distinguishes the keyed selected-redacted-message
window from separate selected-window and post-floor observed-source manifests,
binds selection identity to the exact pack, catalog, and source authority, and
binds session revisions to both predecessor ID and fingerprint. The first
repository implementation may classify only first, provenance-boundary, or
changed/reordered revisions; it cannot claim an append prefix from increasing
counts. Zero-of-zero evidence coverage has an explicit versioned state rather
than being silently dropped or coerced. The public batch-seal draft remains
untrusted, unsealed, repository-verification-required, comparison-disabled,
snapshot-disabled, and activation-disabled. Its 82-test combined temporal gate
and adversarial review passed, including a coordinated chronology/fingerprint
forgery; no temporal storage or authority was added.

Checkpoint `a1626a9` adds a public source boundary only for bounded synthetic
tests. A draft request revalidates and binds the exact prospective history root,
selection revision, project scope, metric keys, pack, catalog, and source
authority. Canonical chronology and local resource bounds are enforced before
a concrete local HMAC creates content-free commitments; the HMAC is a local
integrity mechanism, not source or repository authority. The resulting draft is
fixed untrusted, synthetic-only, unsealed, and repository-issuance-required.

The Codex capability descriptor remains unavailable because the documented
provider boundary supplies neither an authoritative UTC timestamp for every
source item nor stable provider snapshot and cursor boundaries. Capture, list,
read, session, turn, and repository-clock values cannot substitute for those
missing facts. The draft has no `AnalysisInputReceiptV2` mapping and cannot
enter product capture. Repository verification and issuance, a batch seal,
comparison, snapshot materialization, and activation all remain false. The
checkpoint passed 62 focused tests, a 173-test adjacent temporal/privacy/config
gate, and independent adversarial review. These are synthetic contract and
privacy results, not proof that product history capture is available.

Checkpoint `71246b2` defines the comparison-stratum request and draft boundary
without granting comparison authority. Its privacy projection contains only
the target session and omits unrelated session membership. Task ambiguity
remains explicit, while language, complexity, agent permission, and agent model
dimensions remain `unknown_not_recorded`; unknown categories are visible and
are neither pooled, dropped, imputed, nor treated as equal.
`PreparedComparisonStratumDraftV1` and `SealedComparisonStratumDraftV1` remain
structurally constructible drafts, not capabilities: every repository, source,
run, and batch authority flag remains false, as do product capture/history,
pair matching, comparison, aggregate and snapshot materialization,
recommendation and outcome evaluation, causal claims, activation, private
export, and team sharing. This checkpoint adds contracts and synthetic tests,
not a comparison repository or product capability.

Checkpoint `cdc8f56` adds schema-v21 normalized, content-free, synthetic-only
temporal persistence with zero legacy backfill. It creates one prospective root
epoch per project, append-only CAS-linked metric selections, and an immutable
prepared automation-grant snapshot. Exact Coaching fraction results and the
typed temporal graph are committed atomically with the repository-owned graph
seal written last; v21 permits at most one temporal revision per session within
that project epoch.
Hydration rederives the stored run, session, results, identities, counts,
selection chain, snapshot, observations, and seal before returning them.
Privacy deletion uses SQLite secure deletion, parent-cascade removal, and WAL
truncation, with a pending result when a pinned reader prevents physical purge.

The live job lease and current automation-grant row are seal-time-only
authorization. They are checked under a transient, full-lineage local
authorization during the atomic append but are not persisted as public seal
lineage; later reads rely on the immutable prepared grant snapshot and durable
run/session/results graph. The repository seal therefore proves only exact
repository graph ownership and reconstruction. Source authority, product
history eligibility, comparison, snapshot materialization, activation, private
export, and team sharing remain false, and no product capture source,
recommendation, or product snapshot is exposed.

The schema-v21 checkpoint passed 37 focused temporal-persistence tests, 292
primary adjacent history/capture/session/grant/job tests, 26 SQL-adjacent tests,
and the full 1,584-test backend suite with 4 platform skips. The privacy scanner
and diff validation passed, and two independent read-only reviews returned
`PASS`. These are implementation-integrity results, not empirical comparison,
recommendation-outcome, adverse-effect, or calibration evidence.

Pushed checkpoint `339878d` (`Add synthetic temporal aggregation drafts`) adds
a pure, deterministic, supplied-set-only synthetic raw descriptive aggregation
draft. It implements all four typed raw semantics without averaging incompatible
values: fraction ratio-of-sums, count and exposure sums with preserved units,
pooled distribution samples with code-owned Type-7 quartiles, and summed
sampled-proportion successes and trials with a recomputed code-owned two-sided
95% Wilson interval. Code-owned policy identity also fixes half-open temporal
windows, prospective-floor clipping, last-N revision ordering, finite numeric
handling, compatibility segmentation, and non-pooling task-mix behavior.

Selection, source, value, evidence-coverage eligibility, and evidence-coverage
state remain separate and fully counted. Known zero-of-zero evidence coverage
stays known with an absent ratio; unknown, not-applicable, missing, failed,
abstained, incompatible, not-selected, and selection-unknown states are never
coerced to zero. Reviewed task buckets remain visible and unpooled. Full
comparison-identity changes create contiguous run-length segments, so
`A -> B -> A` remains three runs, while an identity-unavailable gap visibly
breaks a run without inventing a compatibility change.

The draft describes only the bounded set supplied by its caller; collection and
population completeness remain unknown. It is not repository-owned or sealed,
has no source or product-history authority, and grants no comparison, pair
matching, aggregate or snapshot materialization, recommendation, outcome
evaluation, causal claim, activation, private export, or team-sharing authority.
The checkpoint passed 33 focused/adversarial aggregation tests, 415 temporal
tests, and the full backend suite with 1,617 passed, 4 platform skips, and one
existing Starlette deprecation warning. Independent adversarial review returned
`PASS`; privacy, compile, and diff checks were green.

Checkpoint `2330afd` adds schema-v22 normalized, content-free, zero-backfill
persistence for repository-issued synthetic comparison-stratum preparations and
graph seals. The committed V1 drafts and v21 temporal rows remain unchanged.
Because the temporal grant snapshot and comparison grant authority deliberately
use separate fingerprint domains, an explicit repository-verified bridge
rederives both identities from the same full active grant instead of equating or
rewriting them. The selected-session analysis-run contract remains pinned to
schema 21 while the additive database schema advances to 22, and the analysis
command and comparison repository share one keyed, installation-local expected
run-ID issuance boundary.

Preparation requires the exact live synthetic session-quality job lease and
active local grant, prepared temporal scope, project, session, metric selection,
pack, catalog, completed-session authority, and code-owned comparison policies.
The repository derives the target-only reviewed-task manifest from the latest
revision at or before its captured cutoff. Its MAX+1 query rejects an overflow
rather than silently truncating the reviewed 100-task bound. Normalized children
are written before the prepared root; exact retries and concurrent attempts
rehydrate the same repository timestamp, identities, and fingerprint.

Run completion, result persistence, temporal batch sealing, live job/grant
revalidation, the terminal run transition, and the comparison graph seal occur
in one SQLite transaction, with the comparison root written last. The public
seal method is replay-only and cannot attach a comparison graph after completion.
Hydration independently rederives the prepared, run, temporal-batch, and
revalidation graph. Transient local HMAC authorization and raw-SQL guards reject
late attachment, altered-lineage reuse, replacement, mutation, and unauthorized
child deletion even with recursive triggers disabled; injected faults before or
after the terminal update roll the entire transaction back.

Run privacy deletion removes prepared-only or sealed comparison graphs through
SQLite secure deletion and WAL truncation. Task and candidate privacy deletion
expands the complete review-decision component, removes every affected comparison
graph under transient authorization, and preserves an already completed run and
its temporal history; an absent retry still checkpoints the WAL. Prepared and
sealed receipts remain content-free and omit worker lease secrets.

Repository ownership and graph verification do not make the comparison stratum
complete. Source authority, product capture and history eligibility, pair
matching, comparison, aggregate and snapshot materialization, recommendation and
outcome evaluation, causal claims, activation, legacy inference, backfill,
remote processing, private export, and team sharing all remain false. No HTTP,
CLI, UI, product snapshot, recommendation, or activation surface was added.

The checkpoint passed 109 focused v22 tests: 95 direct-contract tests and 14
SQLite persistence tests. An independent frozen integration gate passed 178
tests with one existing deprecation warning, and the full backend gate passed
1,732 tests with 4 platform-only symlink skips and one existing Starlette
deprecation warning. The privacy scanner, compileall, and diff validation passed;
three independent contract, SQL, and integration reviews returned `PASS`. These
results prove synthetic repository-graph integrity, not source truth, comparison
validity, recommendation effectiveness, adverse-effect safety, or calibration.

Pushed checkpoint `bdff8a5` (`Add repository-backed synthetic aggregation
drafts`) adds an application-only V2 raw aggregation draft over schema-v22
repository-sealed synthetic comparison-stratum receipts. The repository backing
belongs to the revalidated input graph, not to the aggregation output. The draft
still describes only the bounded set supplied by its caller: it is unsealed,
nonrepository, noncomplete, and does not claim repository-return provenance or
population completeness. Its exact content-free authority manifest commits the
anchor preparation plus every supplied prepared and sealed stratum, analysis run
and authority fingerprint, sealed batch, temporal revision, session coordinate,
effective and sealed times, and window disposition. Authority-only changes move
the draft identity and fingerprint even when the descriptive numbers do not.

The V2 path reuses the exact aggregation semantics rather than introducing a
second estimator: fraction ratio-of-sums, count and exposure sums and rates,
pooled Type-7 distribution quartiles, and pooled sampled-proportion successes,
trials, and Wilson intervals. Selection, source, value, missingness, evidence
coverage, reviewed task buckets, compatibility runs, `A -> B -> A` transitions,
and identity-unavailable gaps remain separately visible and conservatively
counted. Synthetic contract tests cover one- and two-receipt paths; a separate
SQLite integration uses one actual v22 repository-prepared and repository-sealed
receipt. Neither establishes that the caller supplied a complete repository
collection.

Every product capture, source, comparison, pair-matching, aggregate and snapshot
materialization, recommendation and outcome-evaluation, causal, activation,
private-export, and team-sharing authority remains false. The checkpoint adds no
schema migration, repository write, HTTP or CLI API, or UI surface. Its frozen
evidence is 30 focused V2 tests, an exact 172-test adjacent gate, 554 passing
temporal tests, and the full backend gate with 1,762 passed, 4 platform-only
symlink skips, and one existing Starlette deprecation warning. The privacy scan,
compileall, and diff validation passed, and an independent review of the exact
`bdff8a5b35bdb1a93893c93c38b8b4a57b46442b` tree returned `PASS`. These are
synthetic implementation-integrity results, not product/source truth,
comparison validity, snapshot authority, recommendation effectiveness, or
adverse-effect evidence.

Pushed schema-v23 checkpoint `57d623a` (`Persist bounded synthetic aggregation
validations`) adds normalized, content-free, zero-backfill SQLite persistence
for bounded `RepositorySealedSyntheticAggregationValidationV1` receipts. Under
`BEGIN IMMEDIATE`, the repository rejects conflicting live idempotency-key reuse
before clock capture or enumeration, captures one repository UTC `as_of`, and
enumerates at most 10,000 schema-v22 repository-sealed synthetic comparison
strata in the anchor's exact history-root, installation, project, and provider
scope. Normalized members and ordered graph commitments are written before a
root-last transient-HMAC-authorized seal, and hydration rederives the persisted
issuance graph.

The `bounded_sealed_stratum_collection_complete=true` claim covers only that
exact repository transaction snapshot as of its server clock. It proves neither
population nor source or product-history completeness, and later writes do not
alter an existing receipt. The embedded V2 raw aggregation draft remains
nonrepository and unsealed; only the outer validation receipt is
repository-owned and sealed.

Run, task, and candidate privacy deletion discovers every validation containing
an affected v22 member, authorizes each whole-root cascade under the exact live
upstream operation and actual member lineage, and removes v23 before v22.
Restrictive member-to-v22 foreign keys and guarded root-to-child cascades prevent
partial graphs; multi-root causes are deduplicated and processed serially, and
faults roll back the joint transaction. SQLite secure deletion and WAL
truncation remain required, including on an absent retry. Deletion erases the
root, members, graph commitments, and idempotency binding without retaining a
tombstone: replay is guaranteed only while the receipt exists, and later reuse
of the same key is a fresh issuance.

This checkpoint adds only bounded synthetic collection, enumeration, graph
verification, and receipt-persistence authority. Comparison-stratum and
population completeness, source authority, product capture and history,
pair matching, comparison, aggregate and snapshot materialization,
recommendation and outcome evaluation, causal claims, activation, legacy
inference, backfill, remote processing, private export, and team sharing all
remain false. No HTTP, CLI, UI, product snapshot, recommendation, or activation
surface was added.

Frozen evidence for the exact `57d623ac40ef7eb545351872fd911a4c8553bedb`
tree is 14 focused SQLite tests, a 148-test reviewer-adjacent gate, 586 temporal
tests, a 175-test schema/version-adjacent gate, and the full backend suite with
1,794 passed, 4 expected platform-only symlink skips, and one existing Starlette
deprecation warning. The privacy scanner, compileall, and diff validation were
green, and two independent decisive read-only reviews returned `PASS`. These
results prove bounded synthetic repository-transaction and deletion integrity,
not product/source truth, comparison validity, snapshot authority,
recommendation effectiveness, or adverse-effect evidence.

P2 remains in progress: the product-source boundary is still blocked by missing
authoritative per-item timestamps and stable provider snapshot/cursor
boundaries. The repository graph is not a complete or product comparison
stratum, and there are still no product comparisons, aggregates, snapshots,
recommendations, or empirical recommendation-outcome/adverse-effect results.
P3 and P4 remain deferred in phase order.

The live-radar continuation now advances through schema v34. The watch resolves
and reuses only its exact bound head rather than a
session-wide latest run. Privacy deletion disables and revokes the matching
watch, atomically rejects later watch-owned persistence, and conservatively
erases all shadow-model derivatives for that session. An append-only-by-service publication ledger records
only changed sealed runs actually published by the leased watch. A bounded
private trajectory endpoint returns aggregate metric state/counts without
source fingerprints, fragments, or text. Poll attempts that reuse the same run
do not manufacture history points.

The dashboard and native mini-window now use four fixed lenses (task framing,
collaboration flow, reasoning trace, and outcome evidence). Known-only segments
leave gaps at unknown/not-applicable/abstained/error axes; eligible-observation rings
are labeled coverage rather than confidence. Structural ownership cells never
reduce that coverage or create duplicate numerators. Metric selection exposes the raw
ratio and state partition, while the trajectory can navigate immutable
publications and overlays a prior outline only when plan and message-window
scope are comparable. The primary radar now uses a separately sealed
`coaching-typed-projection-v1` from the deterministic coaching engine; its exact
fractions and message coverage remain distinct from the ten-model diagnostic.
The UI exposes **Analyze now**, a running-state **Restart analysis**, and durable
queued/running/failed/up-to-date status. A renewable five-minute watch lease
bounds crash recovery, and manual restart revokes the displaced token without
discarding the last head. Model receipts remain uncalibrated shadow evidence and
are never averaged across time.

The detailed measurement and interaction contract is documented in
[Live metric radar pipeline](live-metric-radar-pipeline.md). Remaining work is
the activity-revision dirty gate, a scheduler/executor split with coalescing and
hard child cancellation, persisted observation/reuse lineage, richer typed
per-metric observation contracts, objective tool/test evidence, and representative
calibration. A visually full radar is not an acceptance criterion: missing
objective evidence must still remain nonnumeric.

Schema v35 adds the local probabilistic radar as an immutable sidecar to the
measured receipt. All twenty metric keys receive a predictive state and, when
locally estimable, a content-free distribution summary: mean, median, four
quantiles, applicability and pending mass, disagreement, effective observation
count, model/calibration/contract identities, and resource telemetry. The
metric-detail endpoint exposes only a fixed twenty-bin density and content-free
factor contributions. No transcript text, fragments, prompts, generated
explanations, or raw logits are persisted or returned.

The live model set is `local-factor-router-v3` under execution plan
`small-factor-router-v5`. Historical `local-factor-router-v2` receipts remain
readable but are not comparable to the new constellation. Three pinned
multilingual NLI encoders form the EN/PL baseline. The separately pinned English
long-context challengers remain disabled pending three-state factor and resource
gates. A pinned Qwen3 4B judge is invoked only for bounded disagreement/neutral
cases and runs in a disposable bitsandbytes NF4 child. All children run serially
with fixed 6,144 MiB VRAM and
8,192 MiB RSS ceilings. Small-model resource exhaustion retries once on CPU;
deep-lane failure cannot erase deterministic or small-model results. The old
ten-stage graph stays immutable and readable but is emitted as unavailable by
the v35 live path rather than executed.
The optional deep lane does not initialize Torch in the server process: `auto`
eligibility is derived from completed child-stage device receipts. Its child is
limited to 27 seconds within a 30-second lane budget, with process-tree
termination and a typed partial publication on timeout only when unload is
positively confirmed. Unconfirmed cleanup aborts publication and retains the
prior canonical head.

The UI now draws solid measured geometry, a dotted experimental median, dark
central-50 and light central-90 bands, explicit nonnumeric state markers, and a
separate evidence-coverage ring. Experimental outputs are not called confidence
or probability. Only a future per-metric calibrated receipt may use predictive
interval language, and outcome forecasts cannot create solid verified-outcome
values without objective receipts.

Synthetic local hardware probes completed all twenty experimental projections
with every five small specialists plus the selective NF4 judge and stayed under
the child VRAM ceiling. This establishes integration and resource feasibility,
not prediction validity. The current cold serial pass is still approximately one
minute, so the three-second warm and eight-second cold targets remain unmet
promotion gates. Calibration datasets/workflow, per-metric holdout promotion,
a persistent warm encoder, Claude/generic adapters, and full-suite quantized
parity evidence remain unfinished. Product eligibility remains false.

Schema v36 and v37 replace the split first-party live-analysis control plane with
one canonical watch head shared by the dashboard and floating window. A durable,
content-free attempt ledger records queued/running/partial/failed/cancelled
generations and immutable sealed stage graphs. Optional model failures can
publish a partial snapshot with warnings; cancellation retains the prior head.
The dashboard no longer starts a competing synchronous v1 run. Both clients use
the same v2 enqueue, cooperative cancel, head, immutable run, and history routes,
fetch the heavy receipt only when the head changes, and retain the last complete
view during retry or reconnect.

The shared full/compact workspace uses six framing, five collaboration, four
reasoning, and five evidence metrics. It draws only measured teal geometry and
informative per-axis experimental median/50%/90% whiskers. Connected lavender
uncertainty polygons were removed because they implied joint structure that
marginal experimental ranges do not establish. Unknown, pending, not-applicable,
and error states remain nonnumeric. Guidance is deterministic and factor-aware,
and model nodes describe contribution to factors rather than ownership of a
metric.

V37 also adds an immutable content-free semantic-unit sidecar. Installation-keyed
content digests ensure an edit under a stable provider message ID creates a new
unit revision; exact-one owners and lifecycle heads prevent chunk boundaries from
inventing denominators. Only the conservative documented message kinds are
currently extracted in production. The Codex safe-event adapter does not expose
requirement references, so objective overrides are withheld rather than linking
tests/actions by temporal proximity. The remaining watch scope is the newest 100
messages / 100,000 redacted characters, not proven full-session history. Generic
analysis-job execution, immediate child-process-tree cancellation, complete
failed-stage telemetry, a distinct persisted `AnalysisSnapshotV2`, full provider
semantic linkage, calibration, and Claude/generic adapters remain unfinished.

Schema v41 corrects a false-number defect in the measured layer. Projection
identity `metric-contract-v2-projection-1` could anchor a fixed-factor rubric
fraction — scored against the focus message — to whichever request revision was
latest, so a feedback-focused or superseded-focus window published a number about
one turn as if it described another. Identity `-2` publishes a rubric fraction
only when the canonical active request revision owns exactly the scored focus
message and otherwise reports `unknown` with `rubric_opportunity_not_focus_owned`
and an empty opportunity set, never `0`. Because `-1` rows are not reproducible
under the corrected rules they keep their own append-only sidecar: MIGRATION_40
is byte-identical, MIGRATION_41 adds the `_r2` tables with the same immutability
and privacy-deletion triggers, readers accept both identities, and a run may
carry only one.

Schema v42 adds projection `metric-contract-v2-projection-3` without mutating
either historical sidecar. R3 gives `logic.open_loop_closure` one exact
structural denominator: an `AGENT` `PLAN` message, closed only by a later agent
`ACTION` or `VERIFICATION` that explicitly supersedes that plan identifier.
Unclosed plans are pending/right-censored, absent plans are actionable unknown,
and incomplete windows are source-incomplete. No lexical or model inference is
used, and the other lifecycle families remain nonnumeric. R3 also separates
objective authority-missing, source-incomplete, and receipt-bound-overflow
causes; requires outcome authority before an empty objective family becomes
no-opportunity; and withholds rubric rows when reconciliation cannot prove an
owner. The `_r3` sidecar is new-write-only; r1/r2/r3 are readable, every ordered
mixed-identity insertion is rejected before or after sealing, the seal binds
exactly twenty r3 rows, and session privacy deletion cascades through the new
tables.

The same checkpoint separates three provider authorities that were previously
conflated: emitting an evidence kind, enumerating a denominator family, and
linking a record to a member of that family. Each is now an explicit closed
`CapabilityKey`, and a projection is rejected unless its decoder declares the
exact enumeration and link capabilities it uses. Historical safe-event decoder
v2 could mint one verification-task identity from one explicit event under that
authority. Current decoder v3 still emits the verification receipt but does not
turn an event identifier into a task denominator; a tool end categorised as test
or build never may either. The shipped Codex descriptor declares only
`tool_events`, so all five evidence-lane metrics remain unknown. An undeclared decision or
verification event is now skipped rather than raising, so one out-of-scope event
kind no longer destroys a session's authorized action evidence.

The full-run API adds a derived per-metric evidence-readiness projection computed
from the sealed publication and the run's provider/adapter/source-schema
provenance. It persists nothing and adds no schema. Its closed reason codes are
metric-specific: each unavailable semantic family names the extractor or
explicit structure it is waiting on instead of sharing a generic "unobservable"
reason. R3 adds only the explicit-plan open-loop extractor; no lexical lifecycle
extractor was added. Each objective row names
the exact adapter enumeration, link, and outcome capabilities it requires, and
the projection separates how many objective contracts the adapter can measure
from how many produced a numeric observation in this snapshot. Catalog identity
`metric-evidence-readiness-v2-2` adds projection-aware contributors for the
explicit-plan lifecycle, labels r1 rubric values as measured under a superseded
identity without borrowing focus ownership, and distinguishes source-incomplete
objective evidence from a complete opportunity set that exceeds the receipt
bound. A declared
denominator without negative-link or outcome observability therefore remains
nonnumeric instead of becoming a false `0/N`.

The 2026-08-17 synthetic-only local diagnostic re-screen did not promote any
neural metric expert. MiniLM-L6 reached 44.4% and MiniLM-L12 55.6% typed accuracy on 18
eligible EN/PL scoped-NLI cases; both remained below the 96-case activation
gate. ModernBERT reached 5/9 on the English three-state screen and mapped every
contradiction to neutral, so it joined DeBERTa-small-long on the live-disabled
list. Qwen3 4B NF4 fit the resource envelope at about 3.84 GiB peak VRAM but
reached only 15/24 exact rubric labels, so it remains a selective experimental
adjudicator. The four-case retrieval smoke favored lexical BM25 and the Qwen
embedding challenger, while the BGE reranker reduced ranking quality; the sample
is too small for activation. These results prohibit interpreting model count or
agreement as metric correctness and are not a calibration or promotion report.

The later local-authority hardening separates proposal and decision
credentials. A loopback API token may still fetch the contract, preview a
canonical file, and import an inert proposal, but the decision route refuses
that token and requires the ephemeral same-origin browser session, CSRF proof,
an exact decision literal, and an owned-window native one-shot capability bound
to the verified origin and exact request body. Standard `serve` and attached
windows advertise the operation as unavailable and leave proposals inert. This
is an application authorization boundary, not a claim of physical user presence
against software that controls the desktop. The exact workflow and current
five-family limit are documented in
[`local-agent-metric-evidence-api.md`](local-agent-metric-evidence-api.md).

## Claude Code hook-capture evidence

The checkpoint at `2b4d506` closed the untrusted agent-evidence import boundary,
`6c1e9ae` landed the synthetic browser direct-transfer prototype (ADR 0009), and
this checkpoint adds the second provider as a prospective, content-free capture
surface ([ADR 0010](adr/0010-claude-code-hook-capture-boundary.md)):

1. a versioned hook contract (`claude-code-hooks.v1`) whose only record shape
   has no field able to hold text, a path, or a raw identifier, and a receiver
   that reads eight allowlisted payload keys, never reads `transcript_path`,
   writes nothing to stdout or stderr, always exits 0, never initializes state,
   and records nothing without an active `claude_code` consent grant;
2. migration 45: an append-only ledger whose `CHECK` constraints repeat the
   contract's closed vocabulary, so the schema itself refuses content;
3. a read-only `ClaudeCodeHookAdapter` on the existing `ProviderAdapter` port
   with snapshot-scoped keyset paging, so hook sessions flow through the
   unchanged ingestion, pseudonymization, and metric pipeline; `events_complete`
   is never claimed, `terminal_state` maps only `prompt_input_exit` and
   `logout`, and `PostToolUse` alone asserts tool success;
4. a `claude_code` decoder descriptor declaring `SESSION_LIST`,
   `SESSION_LABELS`, `OPERATIONAL_EVENTS`, `TOOL_EVENTS`, and `EVENT_TIMING`,
   and deliberately no opportunity, link, message, decision, verification, or
   token capability, so the five evidence-lane metrics stay `unknown` for
   Claude exactly as for Codex; its compatibility report is `degraded` with
   unknown completeness because the provider version and hook coverage cannot
   be attested;
5. the composition root registers both providers' descriptors, the
   compatibility route resolves each provider's own surface (Codex text window
   unchanged; the public DTO gains `capability = operational_events`), and the
   loopback API adds `/v1/local-sources/claude-code` status, consent, and index
   with a `claude_code_local_source` capability flag.

Nothing here reads a Claude transcript, JSONL file, or settings file; capture
is prospective only. This adds no calibration evidence, activates no
estimator, and makes no metric numeric.

The following checkpoint adds a loopback OTLP/HTTP JSON receiver for Claude
Code's documented telemetry (migration 46, `claude-code-otlp.v1`, decoder
version 2). It reads eleven allowlisted attributes and only `api_request` /
`api_error` records plus six documented counters, drops every account,
organization, user, prompt, tool-parameter, and error field by construction,
joins usage to the hook session pseudonym, and emits `USAGE` events that make
the deterministic token metrics numeric for Claude sessions. `TOKEN_USAGE` is
now a declared capability; the compatibility report reports the provider
version from `app.version` as `provider_version_untested` and stays `degraded`.
The receiver requires a separate write-only ingest token, answers inactive
consent with an OTLP `partialSuccess`, and writes nothing in that case. Token
counts are provider-reported facts, not calibration evidence.

The 2026-08-19 checkpoints then made the transcript files the primary Claude
source (ADR 0011 addendum), added default-on onboarding, and closed the
Codex-only analysis gap: a Claude text source subclassing the Codex text source
(fragments from user text, assistant text, and `TodoWrite` / `ExitPlanMode`
plans; shared redaction, windowing and scope accounting), a structural
text-window compatibility probe (`claude_code_transcripts` family; compatible
with complete extraction only when every message row and block type is
classified), Claude Code in the automation catalog refresher and job handlers,
and `ensure_default_grants` so every indexed project of a consented provider
holds the standard local grant. The first end-to-end run through the real
`SessionQualityAutomationHandler` exposed a latent publication-ordering bug -
`finished_at` was read before the final cooperative checkpoint advanced the
job's high-water mark, so every automated run would have been rejected as
`automation_publication_clock_regressed` - which is fixed by reading the
timestamp after that checkpoint. Rubric results for Claude sessions are model
judgments under the same P1 profile and remain calibration-pending; no metric
becomes numeric by this change alone.

Decoder 4 ([ADR 0012](adr/0012-task-scoped-verification-evidence.md)) then
made `outcome.first_pass_verification` computable from evidence: the Claude
transcript adapter classifies shell commands into `TEST` / `BUILD`
deterministically (command text dropped), and the typed-evidence projector
links every verification receipt to the one current accepted task revision
containing the session, declaring no task family when none or several do.
Per-provider safe-event descriptors let Claude transcript sessions project the
same evidence as Codex. A reviewed task without any receipt stays unknown.

Migration 48 adds the blind calibration ratings surface (`/v1/calibration/*`,
dashboard "Calibration" page): a frozen provider-stratified sample of the
owner's indexed sessions, three rubric metrics rated low / medium / high /
cannot-judge while reading the session in the ADR 0011 reader, rater stored
as a pseudonym, export content-free. These ratings are gathered, not yet fed
into any activation gate; no estimator changes state because of them.

Migration 49 records decision provenance (`decision_source`); single-session
candidates are now accepted automatically after each index (ADR 0012
addendum), which makes `outcome.first_pass_verification` computable for every
singleton session that contains a classified test or build run. Grouped
candidates still require a person.

The automatic P1 run's read routes (detail, latest, V2 compatibility preview)
now overlay the decoder-4 objective projection on the evidence-lane rows, so
`outcome.first_pass_verification` is published as an objective receipt for
every auto-accepted session with a classified test or build run - end to end
from one consent, verified by `tests/test_claude_objective_evidence_e2e.py`.

`GET /v1/sessions/{id}/timeline` (session-timeline.v1) projects the indexed
safe events of one session into turns, tool spans by category, verification
receipts and markers with token totals - content-free by construction - and
the session view draws it as a responsive SVG timeline above the reader.

`GET /v1/projects/{id}/timeline` (project-timeline.v1) lists a project's
sessions and the windows of its current reviewed task revisions (first start to
last stop of their member sessions) with activity by day; the project overview
draws them on one calendar axis with a 30/90-day/all range and session click-through.

Live mini windows: `/live/projects/{id}[/sessions/{sid}]` renders a
chrome-less, self-refreshing view (name, provider, latest automatic analysis,
job state, timeline) that the project and session views open as a named
browser popup - one per project or session, several at once.

Local model runtimes (ADR 0013): registry + weights under the app home
(`local-models/`, inventoried), llama-server spawned per activated model on a
loopback port with cpu / gpu / split layer offload (estimate from free VRAM,
overridable), `/v1/local-models/*` incl. an OpenAI-compatible chat proxy, and
the Models page; downloads are size-confirmed and go through the person's own
Hugging Face login. No metric uses a local LLM yet; that is the judge lane.

First local-model benchmark on the owner's machine (RTX 3080 Ti Laptop 16 GB,
i9-12900HK, llama.cpp b10502 CUDA 12.4, 160 generated tokens, 8192 ctx):
Qwen3.8-27B-Uncensored Q4_K_M (16.8 GB) in split mode peaks at ~13.8 tok/s
with 62/65 layers on the GPU (auto-estimate 48 layers: 7 tok/s; all 65
layers: VRAM overflow, 7.6 tok/s); the IQ3_M 3-bit build (12.8 GB) fully on
the GPU reaches ~25 tok/s generation and ~205 tok/s prompt processing at
13.5 GB VRAM, so it is the default judge model; Q4_K_M stays installed for
higher-quality manual use. Thinking mode must be disabled for short answers
(`chat_template_kwargs.enable_thinking=false`). Hardware numbers only; no
session content was involved.

Model-judge lane (ADR 0013 section 4, migration 50 `model_judgments`): the
active local model reads the same redacted window as P1 (loopback, never
persisted) and answers the three Calibration questions with thinking disabled;
labels are stored with model identity and prompt version `judge-v1`, apart
from every metric table, and compared with human ratings through
`model_human_agreement` (rate + Cohen's kappa per metric) on the Calibration
page. Judgments never become metric values; objective evidence outranks them.

Local model endpoint, second slice: the chat proxy relays `stream: true` as
server-sent events (bounded at 16 MB per reply; upstream 4xx stay JSON), each
model also answers under an OpenAI-style base URL
(`/v1/local-models/{alias}/v1` with `/models` and `/chat/completions`, plus
`/v1/local-models/openai/v1` routed by the `model` field across running
aliases), the app token is accepted as a bearer credential so ordinary OpenAI
clients work unchanged, aliases used by fixed routes are reserved, downloads
report partial bytes, and the Models page has a chat box (thinking off by
default, history kept in the tab only). The unrestricted orcarouter weights are
now installed as an imatrix IQ3_M from an ungated mirror built from
`orcarouter/Qwen3.8-27B-Uncensored-FP8` (12.8 GB, fully on the GPU).

Migration 51 widens `session_model_ensemble_runs` and
`session_model_ensemble_watches` from `provider='codex'` to the text-analysis
providers (`codex`, `claude_code`) using the SQLite-documented
`writable_schema` relaxation (rows untouched, strictly weaker constraint, new
provider index bumps the schema cookie, integrity and foreign-key checks
asserted in tests); the ensemble service, the watch service and the watch
routes now admit any text-analysis provider, resolving the session's real
provider instead of assuming Codex. Claude Code sessions can therefore have
ensemble runs and continuous watches persisted exactly like Codex ones; the
judge sweep gained `scope=all` to cover every indexed session.

Read-only agent surface (ADR 0014): `prompt-enhancer mcp` speaks MCP over
stdio without an SDK (initialize / ping / tools/list / tools/call, bounded
messages) and exposes six allowlisted tools from one shared
`AgentReadSurface` - metric catalog, paged session list with the owner's
display names, per-session metric results, a content-free period summary
(≤ 300 recent sessions, truncation flagged), a metric explainer that restates
"unknown is never zero" and the evidence-over-judgment rule, and calibration
status with per-model judge agreement. No transcript text, raw event, path,
token or model reply crosses the boundary; the server refuses to start without
the context-egress acknowledgement, and `mcp-config` prints (never writes) the
Claude Code and Codex snippets.

Migration 52 makes display-label provenance provider-neutral: the closed value
lists on `project_display_labels` / `session_display_labels` gain
`provider_first_prompt`, `transcript_head` and `hook_event` (same
writable_schema relaxation as migration 51), and indexing stamps every Codex
and Claude Code label into the provenance tables - Claude project labels from
the transcript cwd basename, session titles from the first prompt
(`transcript_head`, extractor `claude-code-display-labels-v1`), hook-carried
labels as `hook_event` - instead of the plain display-name columns, which only
the synthetic demo adapter still writes. Reads are unchanged (COALESCE over
manual, provider, column), so existing rows keep their names.

Prompt check (ADR 0015, migration 53 `prompt_checks`): one service behind
`POST /v1/prompt-checks`, the MCP tool `check_prompt` (the ADR 0014 surface's
single text-accepting tool; the MCP process forwards to the running app so the
active model answers) and the opt-in Claude Code `UserPromptSubmit` hook
`prompt-enhancer claude-prompt-check` (silent, never blocking, switchable by
environment). The prompt and optional earlier turns go through the redactor,
language detector and coaching engine with the prompt as the focus request,
so the six prompt metrics and their cues are the dashboard's own; content-free
context inference adds task type, dependence on earlier turns and whether
verification was asked for; the active local model returns strict-JSON
commentary (findings, a reformulated prompt with `<specify: …>` placeholders,
element rewrites) that is labelled model output and never a metric. Only
metrics, counters and an HMAC fingerprint are stored; the Prompt check page
plots radar and trend over the stored checks. Verified live on the owner's
machine: deterministic answer in well under a second, commentary from the
orcarouter IQ3_M in about 20-40 s, the hook handing the advice to Claude Code
as additional context.

Dashboard theming and the Overview page: every literal colour of the frontend
CSS is now a token (`frontend/scripts/make_theme.py` generates
`palette.generated.css`: original light values plus OKLCH lightness-inverted
dark counterparts, sidebar-family colours pinned, faint white highlights kept,
frosted whites mapped to dark surfaces); `theme.css` hand-tunes the dark core
(deep blue-graphite surfaces, luminous teal accent, ember caution, aurora
canvas, glass cards, glowing chart strokes, dark-ink primary buttons,
scrollbars, forms, zebra and sticky tables). Dark is the default
(`index.html` stamps it before the first paint; `ThemeToggle` in the top bar
persists the choice); an automated contrast audit over the main pages in dark
found no text under WCAG AA after the primary-button fix. The Overview page
reads only existing endpoints and shows sessions per provider with a 30-day
sparkline, calibration progress and judge coverage, the active model and
hardware, prompt checks, and the next worthwhile action.

Local agent workspace (ADR 0016): `LocalAgentService` binds a session to one
folder and lets the active local model use `read_file` / `list_dir` /
`search_text` freely and `write_file` (diff first) / `run_command` /
`fetch_url` only after the person approves that exact call; path containment,
protected-root refusal, owned-window native one-shot approval, revision-bound atomic
writes, bounded outputs, step limit, stop; events are an in-memory, cursor-paged
stream. The session-bound workspace API and Agent page add an existing-file
UTF-8 tree/editor, normalized line endings, server diff, and a short-lived
single-use apply capability; no draft content is retained by that capability.
The same surfaces remain under `/v1/agent/*` and `/agent/window/{id}`. The
runtime now starts with `--jinja` (tool calls in the model's own format),
flash attention and an 8-bit KV cache (about 2.4x prompt processing on the
owner's GPU) with a plain retry; the API is gzip-compressed. Verified live:
list -> read -> diff (approved) -> test added (approved) -> pytest (approved,
3 passed) -> summary in about 17 s. Also: session interpretation by the model
(`POST /v1/model-judge/sessions/{id}/interpret`, commentary never a metric),
folder scan for GGUF files, recommended models, live-window shortcuts on
project cards and session rows, a new brand glyph.

## P3a control-plane foundation evidence

This checkpoint adds a development-only team control plane. It is a contract and
policy foundation, not a product: nothing is deployed, nothing listens off the
loopback interface, no real identity provider or payment integration exists, and
the composed plane reports `production_ready = false` with an explicit gap list
that a configuration value cannot change.

What the slice establishes, with tests:

1. tenancy contracts for organizations, teams, memberships, roles, devices,
   tenant-scoped API clients and scopes, manager grants, audit events, and
   entitlement/readiness placeholders, all content-free and pseudonymous;
2. an exact ten-key numeric publication allowlist with fixed units,
   server-registered producer/definition versions, bounded quantized numbers,
   no free-text field, and unknown values that never become zero; key choice,
   bounded values, and timing remain a residual signalling surface;
3. default-deny authorization as a pure function over directory-resolved facts,
   with organization, team, and individual visibility, explicit and audited
   manager access, cross-tenant rejection before any existence check, and no
   organization/user/client/device identity fields in request bodies;
4. device-bound signed envelopes with domain-separated canonical bytes, tamper
   and key-mismatch rejection, enrolment-time freshness bounds, and a production
   Ed25519 algorithm that is named but deliberately unregistered so composing it
   fails closed;
5. server-issued envelope and snapshot identifiers, one short-lived outstanding
   epoch-bound reservation per producer (bounding reserve-without-consumption,
   while push-then-reissue returns a fresh ID), no caller-visible envelope IDs
   in audit, and owner-bound replay fences that survive deletion; contiguous
   client/device-local cursors, durable recipient-bound retry projections and
   recipient-specific tombstones backed by a prior-delivery ledger; explicit
   manager-grant revocation; and atomic device/client/credential revocation;
6. canonical fixed buckets and internal no-sub-threshold arithmetic contracts,
   while every public aggregate request fails closed without counts or values
   until stable privacy cohorts, overlap rules, and an atomic query budget exist;
7. narrow storage ports with one shared-lock, thread-safe in-memory development
   adapter, plus
   [ADR 0005](adr/0005-team-control-plane-boundary.md) and
   [the production PostgreSQL and row-level-security design](control-plane-postgres-rls.md).

What it explicitly does not establish: authentication of a person by a real
identity provider (the opaque development credential only authenticates its
out-of-band binding), durability, cross-process concurrency, encryption at
rest, erasure across backups and replicas, a complete credential lifecycle,
metering, or any evidence that team sharing is safe to enable for real people.
No safe aggregate-release claim is made. Overlapping teams, longitudinal
composition, cohort stability, and query-budget enforcement remain production
blockers, and the public use case is suppressed until they are resolved.
The local analyzer, its SQLite system of record, and its historical migrations
are untouched; the control plane imports none of them, and with the setting off
the application composes no control-plane service and exposes no route.

## Checkpoint 9D code-only cross-surface audit

Exactly twenty isolated Claude CLI invocations reviewed one immutable
repository-code snapshot with the requested Opus 5 / max configuration and
read/search-only tools. Nine returned accepted structured reviews and eleven
ended capped without a verdict; no capped run was counted as an approval or
retried. The 21 unique candidates were independently classified into 17
defects and four enhancements. The bounded external cost was $17.70.

No provider session, transcript, prompt, tool output, credential, runtime
database, local configuration, or sensitive derived metric entered the
snapshot or the reviewer boundary. The resulting repairs and their frozen
validation evidence are recorded in
[Checkpoint 12](checkpoint-12-handoff.md). Human calibration and card-by-card
visual approval remain explicitly outside this evidence.

## Version inventory

| Component | Pinned identity | Product status |
|---|---|---|
| Deterministic coaching pack | `core.redacted-text.prompt-logic` v1; engine `text-rules-en-pl-1`; rubric `prompt-logic-rubric-1` | Local deterministic observations only; missing objective evidence abstains |
| Historical ten-model shadow graph | `local-shadow-ensemble-v1`; `append-stable-redacted-v3`; `owned-observation-v1`; `coaching-shadow-prompt-v4`; exact ten-model inventory in code-owned immutable manifests | Immutable/readable compatibility history; not executed by the live v35 estimator |
| All-20 predictive sidecar | `local-probabilistic-radar-v1`; active `local-factor-router-v3` / `small-factor-router-v5`, historical v2 readable; experimental calibration; versioned twenty-metric contract set | Local content-free ranges beside measured values; uncalibrated and product-ineligible; objective outcome boundary retained |
| Canonical all-20 measured publication | `metric.contract-v2.publication` v2; registry `all-20-factor-contracts-v2`; current projection `metric-contract-v2-projection-8`; schema v59 exact M58 revision binding plus `_r8` state/seal sidecars, inheriting sealed profile, requirement-plan, and requirement-action authority; r1-r7 rows remain readable | Canonical for new model-ensemble snapshots; r8 preserves nineteen r7 rows and replaces only verified-requirement coverage through objective projection v4, using the exact app-issued reviewed-r6 opportunity set and current objective-result or separately typed owned-native-acceptance authority; missing evidence remains nonnumeric and all model paths remain non-authoritative |
| Per-metric evidence readiness | `metric.contract-v2.evidence-readiness` v1; catalog `metric-evidence-readiness-v2-7` | Derived on read from the exact sealed publication; adds no datum or persistence; includes r8 verification source/revision/bound reasons while preserving r7 requirement-action, r6 requirement-plan, r5 profile, r4 lifecycle, capability, and censoring distinctions |
| All-20 operability catalog | `metric-operability-v4`; authenticated `GET /v1/metric-contracts/v2/operability-catalog` | Content-free release gate derived from the reviewed contracts and composed capabilities: 16 shipped conditional paths, 0 task-profile gaps, 4 provider/extractor or release-composition gaps, 8 experimental model paths, 0 model-authoritative metrics; the r8 binding is not a provider-readiness or calibration promotion |
| Redactor | `deterministic-local-redactor-v1` | Local risk reduction; not sufficient by itself for remote disclosure |
| E5-base retrieval challenger | `intfloat/multilingual-e5-base` at `d128750597153bb5987e10b1c3493a34e5a4502a` | Synthetic exploratory challenger; not promoted or product-enabled |
| BGE-M3 dense challenger | `BAAI/bge-m3` at `142964af7e05de16511657561de8e8750fc153a0` | Safe superseding pin evaluated; trails the current retrieval Pareto set and remains disabled |
| Qwen embedding challenger | `Qwen/Qwen3-Embedding-0.6B` at `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | Synthetic exploratory challenger; not product-enabled |
| BGE reranker challenger | `BAAI/bge-reranker-v2-m3` at `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | Synthetic exploratory challenger; not product-enabled |
| Claude Code hook capture | `claude-code-hooks.v1`; receiver `claude-code-hook-receiver-1`; adapter `claude-code-hooks-adapter-1`; source schema `claude-code-hooks.receipt-clock.v1`; decoder `claude-code.hooks.operational-events` v2; migrations 45-46 plus schema M60 time-basis admission | Prospective, content-free, consent-gated operational events with explicitly receiver-observed receipt timing; provider-reported telemetry remains separate; no transcript access or task-outcome inference |
| Claude Code telemetry capture | `claude-code-otlp.v1`; loopback OTLP/HTTP JSON receiver at `/otlp/v1/{logs,metrics}`; separate write-only ingest token | Per-request tokens, model, duration, and provider-reported cost; six documented cumulative counters; eleven allowlisted attributes; provider-reported facts, not calibration evidence |
| Claude Opus review target | Exact requested and served model must be recorded by a reviewed BYOK/API runner | Not implemented; no private-session review is authorized |
| Claude Fable review target | Exact requested and served model plus retention acknowledgement must be recorded | Not implemented; synthetic architecture review only until the remote approval boundary exists |
| Annotation paths (ADR 0017) | `annotation.v1`; agent surface `/v1/annotation/*` behind a per-person allowance switch; pre-send `/v1/annotation/remote/disclosure`; central server `/central/v1/annotations/batch` with `central-annotations.sqlite3`; labels stored as `agent:<name>` / `central:<model>` judgments; current profiles `judge-v3-untrusted-json-anchor-15k` and `judge-v3-untrusted-json-anchor-6k` | Judgments, never metric values; exact destination/retention/model policy must be disclosed before central submit; canonical windows are untrusted JSON with an anchored task request; objective evidence remains authoritative |
| Shared team folders (ADR 0018) | `shared-folders.v1`; owner surface `/v1/shared-folders/*`; peer surface `/p2p/v1/{share}/manifest|files` with `X-Share-Token` (stored as SHA-256); `shared-folders.sqlite3` registry + per-link last-synced hashes; egress: `application.shared_folders` registered as approved-provider-request (peer URL typed by the person) | Working files the person chose, never the app home; conflict copies instead of silent overwrites; verified live: agent edited a joined copy, pushed back, conflict and revocation exercised |

Full local model revisions, weight digests, tokenizer pins, licenses, bounds,
and gate results live in [the model manifest](model-manifests/wp-11-local-candidates.md).

## Decision log

- Unknown, unsupported, abstained, incompatible, not-applicable, and failed are
  distinct states. None may be converted to zero.
- Objective tests, artifacts, and explicit acceptance outrank model-written
  completion claims.
- Review-load metrics stay on an exact-value board unless a bounded,
  documented normalization exists.
- Remote work is per-run only: a local automation grant can enqueue it, but it
  cannot approve disclosure.
- P1, billing, and teams remain disabled until their preceding phase gates pass.
