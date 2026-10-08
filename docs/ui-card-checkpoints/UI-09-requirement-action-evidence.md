# UI-09 · Reviewed requirement-to-action evidence

Status: **implementation complete · independent and integrated verification green**
Visual review: pending user review in the local app
Baseline: `5e9bd7b` (`docs(ui): record wave one checkpoint status`)
Scope owner: `RequirementActionEvidencePanel` file, proposal, complete descriptor review, and native decision surface

## Frozen scope

This checkpoint changes only the requirement-to-action evidence card:

- full and compact loading, unavailable, empty, error, stale, proposed, confirmed, and rejected states;
- exact session, source-run, projection, public source/binding, and transport ownership;
- bounded canonical file preview and inert import;
- complete local requirement, action-candidate, descriptor, and nested-membership review;
- separate native review, semantic acknowledgement, and confirm/reject decision;
- full opaque receipt display, keyboard focus/`Escape`, long-content wrapping, and 360–1040 px behavior.

Backend/API contracts, provider adapters, generated files, requirement-plan UI, generic evidence UI, global styles, and metric calculations are unchanged.

## Accepted corrections

1. Tag the loaded contract and every transient authority state with a stable content-free binding plus the exact transport object. Old A content is suppressed synchronously during B's first committed frame, before passive cleanup.
2. Recheck the live owner, contract, proposal, preview bytes, review, acknowledgement, and pending decision inside every handler. Captured detached A controls cannot act on B, and superseded same-owner controls cannot act on newer state.
3. Abort prior work and reject delayed preview/import/review/decision completions after any session, run, projection, public source/binding, or transport change.
4. Fail public binding/source disagreement, contract receipt drift, cross-session proposal collections, incomplete candidate enumeration, and inconsistent native-presence capability closed.
5. Validate file media, 1–65,536 byte bounds, read-size stability, exact preview counts/bindings/expiry/flags, and imported digest/proposal authority. File names, raw bytes, and caught exception text are never rendered.
6. Keep import inert. Native review separately requires owned user presence, a current proposed graph, and a complete expiring review receipt.
7. Recheck every review requirement, coordinate, candidate, application-issued state, descriptor algorithm, non-truncation flag, metadata receipt, membership, explicit empty link, and expiry before displaying any semantic acknowledgement control.
8. Require explicit acknowledgement of every requirement, candidate, descriptor, semantic membership, and empty link before a one-shot confirmation can be staged.
9. Validate decision responses against the complete proposal identity and expected confirmed/rejected receipt before updating history or requesting a metric refresh.
10. Keep confirmed and rejected records visible and read-only instead of collapsing them into an empty state. Missing values remain “not recorded,” never zero or false.
11. Display complete opaque run, proposal, source, graph, candidate-set, descriptor-set, and metadata identifiers without semantic truncation; all identifiers and exact escaped text wrap.
12. Move focus into the complete review and final decision layer. `Escape`/Cancel closes only the active layer and restores focus to its opener.
13. Add card-scoped responsive, light/dark-token, forced-colors, and reduced-motion styling without changing shared or global CSS.

## Privacy and authority boundary

- Tests use only reserved synthetic identifiers, fictional producers, and escaped synthetic descriptors.
- No localhost, browser DOM, provider session, credential, raw transcript, raw file byte, or real path was inspected.
- Imported producer claims remain explicitly untrusted and ephemeral.
- Candidate state is visibly application-issued; a descriptor or membership is not objective proof or task success.
- A confirmed native decision only makes the exact reviewed binding eligible for a fresh analysis; the card never computes or invents a metric value.

## Files changed

- `frontend/src/features/model-ensemble/RequirementActionEvidencePanel.tsx`
- `frontend/src/features/model-ensemble/RequirementActionEvidencePanel.test.tsx`
- `frontend/src/features/model-ensemble/RequirementActionEvidencePanel.css`
- this checkpoint note

## Automated verification record

- Focused requirement-action panel regressions: **33 passed**.
- Cases include all public evidence states; empty/proposed/confirmed/rejected history; compact parity; synchronous transport and public-binding A→B layout attacks; delayed import/review completion; contract/preview/proposal/review/decision drift; descriptor/candidate/membership completeness; native-presence fail-closed behavior; file bounds/media/privacy; dense nested links; long one-pass escaped text; full opaque IDs; acknowledgement; focus; and `Escape`.
- Affected card/workspace/panel verification: **4 files / 91 tests passed**.
- Independent validation: **passed** with no reproduced P0/P1; the focused 33-test suite and a 90-test selected host group revalidated ownership, completeness, decided-state truth, long content, fail-closed presence, focus/`Escape`, and compact parity.
- TypeScript project build (`tsc -b --pretty false`): **passed**.
- Production frontend build: **passed** (the existing ~515 kB main-chunk advisory remains).
- Final integrated frontend suite: **113 files / 1,189 tests passed**.
- Repository privacy scan: **passed**.
- Diff whitespace validation: **passed**; Windows LF→CRLF notices only.
- No commit was created by this implementation agent.

## Later visual checklist

- Tour loading, unavailable sources, empty history, stale proposal, ready review, confirmed, rejected, expired receipt, and bounded error copy.
- At 1040, 900, 760, 600, and 360 px, verify complete 64-character identifiers, long escaped descriptors, dense nested memberships, file controls, and decision buttons wrap without horizontal page overflow.
- Confirm full hierarchy reads as contract → preview → inert proposal → complete local review → acknowledgement → native decision; compact mode remains read-only and descriptor-free.
- Verify light/dark, forced colors, enlarged text, visible focus, Tab order, `Escape`, and focus restoration.
- Snapshot A→B during preview, review, and final decision; no A metadata or action may survive B's first frame.
