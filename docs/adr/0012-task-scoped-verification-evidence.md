# ADR 0012: Task-scoped verification evidence (safe-event decoder 4)

- Status: accepted (2026-08-19)
- Supersedes nothing; decoders 2 and 3 stay frozen and readable.

## Context

`outcome.first_pass_verification` asks a simple question - did the first
verification attempt for a task pass? - but a safe-event stream carries no
provider-owned *task* identity. Decoder 2 manufactured one per explicit
verification event, which made the metric a tautology (one task, one outcome,
always resolved). Decoder 3 therefore emitted verification receipts and
declared no task denominator at all, so the objective row stayed an honest
"unknown" for every provider. The owner's direction is that objective rows
should compute automatically wherever the evidence really exists.

Two facts make that possible without guessing:

1. **A reviewed task is observable.** Discovery proposes task candidates; a
   person accepts, rejects, merges or splits them, and the lifecycle ledger
   keeps the current accepted revision and the sessions it contains
   (`list_current_revisions_for_session`). That is a denominator someone
   actually asserted.
2. **A test or build run with an exit status is a verification receipt.** The
   Claude Code transcript adapter now classifies shell commands into the
   closed `TEST` / `BUILD` categories deterministically (leading program
   words only - the command text is never kept) and carries `success` from
   the tool result's `is_error`; an explicit provider verification event is
   the same receipt kind.

## Decision

Decoder 4 ("task-scoped") keeps decoder 3's receipts exactly and adds one
rule: when **exactly one** current accepted task revision contains the
session, that revision is the verification task, and every verification
receipt in the session links to it. Its reference id is a fingerprint of the
session, task id and revision under a new namespace
(`typed-reviewed-task-evidence-v4`); event evidence identities are unchanged.

When there is no task source, no accepted revision, more than one current
revision claiming the session, or the task store fails, the decoder declares
**no** task family. `outcome.first_pass_verification` then stays unknown with
`typed_objective_opportunity_authority_missing` - never a guessed attribution
and never a manufactured 1/1. A reviewed task with no verification receipt at
all stays unknown with `typed_first_verification_unresolved`: "nothing was
verified" is its own state, not a zero.

The composition root ships decoder 4 for both providers with four
capabilities - `tool_events`, `verification_events`,
`verification_task_opportunities`, `verification_task_evidence_links` - and a
per-provider descriptor (Codex app-server safe events; Claude Code transcript
safe events) so the projection's provenance matches the session's adapter
and schema. Hook-only Claude sessions do not match the transcript descriptor
and project nothing; hooks cannot classify commands without reading tool
input, which ADR 0010 forbids.

## Addendum: single-session candidates are accepted automatically (2026-08-19)

The owner chose propose-then-accept for groupings and asked that single-session
candidates not wait for a click. After every index the refresh path runs
discovery and then `SingletonCandidateAutoAccepter`: each undecided candidate
with exactly one session is accepted with `task_category = UNKNOWN` and the
decision is stored with `decision_source = "automation"` (migration 49) so the
inbox shows "Auto-accepted" instead of a person's review. Multi-session
candidates - the ones that carry a grouping judgement - still wait for a
person. This gives decoder 4 its reviewed denominator for the common case
without inventing one: the session is the task by construction.

## Consequences

- First-pass verification becomes numeric exactly when a person has accepted
  the task and the session contains a classified test or build run. The
  other four objective contracts keep their existing authority rules.
- The measured value is read wherever a session's metrics are read: the
  model-ensemble run's objective layer as before, and - since 2026-08-19 -
  the automatic P1 run's detail, latest-run and V2 compatibility preview
  routes, which overlay the decoder-4 projection on the five evidence-lane
  rows at read time (typed-objective-evidence provenance, objective_receipt
  authority). Nothing is rewritten in the stored run; a projection failure
  leaves the rows withheld exactly as before. No ensemble click is needed.
- Decoder versions 2 and 3 remain supported for reading historical
  projections; current code composes 4 only.
