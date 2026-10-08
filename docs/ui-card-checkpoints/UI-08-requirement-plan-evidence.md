# UI-08 · Requirement-to-plan evidence

Status: **implementation complete · independent and integrated verification green**
Visual review: pending user review in the local app
Baseline: `5e9bd7b` (`docs(ui): record wave one checkpoint status`)
Scope owner: `RequirementPlanEvidencePanel` canonical-file, complete-clause review, and native-decision surface

## Frozen scope

This checkpoint changes only the requirement-to-plan card and its direct presentation rules:

- fresh r5/r6/r7 contract loading and exact session, source-run, projection, source-window, predecessor, and transport ownership;
- bounded canonical-file selection, strict preview, inert import, complete local clause review, and separate native confirm/reject decisions;
- unavailable, loading, empty, ready, preview, stale, error, confirmed, and rejected truth states;
- full and compact hierarchy, focus restoration, keyboard cancellation, long exact safe-coordinate wrapping, and narrow-container behavior.

Requirement-to-action review, generic metric evidence, backend and generated contracts, provider adapters, metric calculations, global styles, and the shared card backlog are unchanged here.

## Accepted corrections

1. Bind all rendered state synchronously to the exact `(session_id, source_run_id, source_projection_version, transport)` owner. A preview, proposal, review, acknowledgement, busy flag, error, or decision from A is hidden on the first B render before effects run.
2. Recheck that owner in every mutation handler and asynchronous completion. Retained A buttons are inert after a run or transport swap, and delayed A contract, review, or decision work cannot repopulate B or call the refresh callback.
3. Require the contract and nested source manifest to match the selected session, sealed run, source-window fingerprint, projection, and unexpired local review context. r5 bootstrap plus r6 and r7 sources retain their existing authority without projection widening.
4. Distinguish runtime-unavailable, initial loading, empty exact-source proposal sets, load error, stale authority, active preview/review, and recorded confirmed/rejected decisions. Unknown or absent authority never becomes zero.
5. Validate one non-empty `.json` file, accepted JSON/canonical media type, exact bytes read, and the contract's 64 KiB bound before preview. File names, raw bytes, caught exception details, and parser details are never rendered.
6. Require preview session, run, source window, predecessor, expiry, bounded counts, count arithmetic, and non-authoritative flags to match the fresh contract. An expiry timer clears both preview and retained payload before import.
7. Require imported digest, source authority, predecessor, inert status, decision-null shape, counts, and link count to preserve the exact preview. Import can create only an unconfirmed proposal and cannot publish a metric.
8. Filter proposal history to the exact session/run/window, while preserving stale-predecessor proposals as rejection-only work. Current and stale proposals are labelled separately.
9. Validate the complete one-shot review against every eligible source-manifest coordinate in exact order. Every user clause must match one active or excluded proposal entry; every disposition, PLAN link, exclusion reason and basis, plus every included or omitted PLAN clause, must agree before acknowledgement is available.
10. Render exact clause text only inside the expiring native review. Long synthetic escaped text, full content-free IDs, nine-digit coordinates, basis text, and link coordinates wrap without truncation or HTML interpretation.
11. Make acknowledgement receipt-specific and explicit. Closing, refreshing, changing context/transport/proposal, opening another review, errors, or expiry clears it.
12. Validate native decision responses against the complete immutable proposal evidence identity, requested decision, terminal status, decision receipt, and owned-native authority. Only a valid confirmation triggers analysis refresh.
13. Keep confirm and reject as explicit two-step actions. Focus moves to preview/review/decision content, Cancel or `Escape` restores the opening control, and compact mode remains read-only.
14. Add card-scoped container behavior for the 360–1040 px range, semantic theme tokens, 44 px controls, exact-value wrapping, forced-colors boundaries, and reduced-motion treatment.
15. Bind each rendered Import control to the exact live preview epoch and byte payload. Replacing or clearing a same-owner preview immediately makes a retained earlier Import control inert, and import consumes the live preview before crossing the native boundary.
16. Bind review and decision controls to content-free proposal-membership, review, acknowledgement, and pending-decision epochs. Cancel, Close Review, acknowledgement changes, proposal replacement, and the first Apply synchronously invalidate retained controls; Apply cannot call native code without one currently live exact pending tuple.
17. Treat native presence as one coherent fail-closed tuple: only the exact v1 contract with `confirmation_available: true` and `native_bridge_bound_token` mode enables review or decisions. Inconsistent mode/availability values and unknown contract versions remain unavailable.

## Privacy and authority boundary

- Tests use only reserved synthetic identifiers, fictional producers, and synthetic clause text.
- No localhost, browser DOM, real session, provider credential, transcript, source snippet, path, or screenshot was inspected.
- Fixed bounded UI errors replace caught exception text. File names and selected bytes never enter the document.
- Exact clause text is ephemeral local-review material and is not persisted by the card.
- A proposal remains inert until complete native review and confirmation. Confirmation makes evidence eligible only for a later fresh sealed analysis; it is not objective proof of plan quality, requirement atomicity, or task success.

## Files changed

- `frontend/src/features/model-ensemble/RequirementPlanEvidencePanel.tsx`
- `frontend/src/features/model-ensemble/RequirementPlanEvidencePanel.test.tsx`
- `frontend/src/features/model-ensemble/RequirementPlanEvidencePanel.css`
- this checkpoint note

## Automated verification record

- Direct UI-08 suite: **28 tests passed**.
- Affected panel and synthetic checkpoint-tour integrations: **3 files / 77 tests passed**.
- Independent exact-defect recheck: **passed**. All four same-owner stale-preview, stale-review/decision, proposal-membership, and contradictory native-presence attacks passed read-only revalidation.
- TypeScript project build (`tsc -b --pretty false`): **passed**.
- Focused cases cover every supported truth state; r5/r6/r7 authority; transport and run A→B retained-action attacks; same-owner preview replacement; retained controls after Cancel, Close Review, acknowledgement changes, proposal decisions, and first Apply; delayed contract/review/decision suppression; file size/media/schema/expiry; preview/import/review/decision mismatches; complete active/excluded/PLAN clause rendering; long exact coordinates and escaped text; coherent fail-closed native presence; acknowledgement reset; `Escape`; and focus restoration.
- Production frontend build: **passed**; the existing approximately 515 kB main-chunk advisory remains.
- Final integrated frontend suite: **113 files / 1,189 tests passed**.
- Repository privacy scan: **passed**.
- Owned-path diff check: **passed**; Windows LF→CRLF notices only.
- No commit was created by this implementation agent.

## Later visual checklist

- Full mode, light and dark: confirm the authority explanation reads as file → strict preview → inert proposal → complete local review → native decision, without suggesting that import or confirmation proves plan quality.
- Compact mode: unavailable, loading, empty, one/multiple pending, confirmed, rejected, and error states remain readable and expose no file/review/decision controls.
- Widths 1040, 900, 760, 600, 420, and 360 px: file input, full opaque IDs, nine-digit coordinates, exact clause text, basis evidence, PLAN links, acknowledgement, and decision controls wrap without horizontal page overflow.
- Keyboard: Tab reaches every enabled control; preview and review receive visible focus; review and decision `Escape` restore their exact opening buttons.
- State tour: missing capability, delayed load, empty snapshot, file validation error, expired preview, stale contract, stale predecessor, incomplete review, native presence unavailable, valid confirmation, rejection, and load failure.
- Snapshot A→B: retain an import or decision control under A, change run or transport to B, and verify no A text, proposal, alert, action, or delayed completion survives.
- Forced colors, reduced motion, 200% text zoom, and long safe synthetic values: boundaries, focus rings, alerts, and decision order remain visible without relying on color alone.
