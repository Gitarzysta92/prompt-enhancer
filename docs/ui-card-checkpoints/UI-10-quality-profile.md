# UI-10 · Quality profile, exact metric board, and local review dialogs

Status: **implementation complete · independently rechecked · full gates green**
Visual review: pending user review in the local app
Baseline: `378781f` (`docs(ui): record wave two checkpoint status`)
Scope owner: `QualityProfileView`, `QualityRadar`, metric readiness/opportunity presentation, and the analyze/share dialogs

## Frozen scope

This checkpoint changes only the quality-profile feature and its direct tests and styles:

- truthful loading, empty, unavailable, error, stale, known, omitted-by-scope, incompatible, abstained, not-applicable, and failed states;
- exact profile, session, metric-pack, snapshot, preview, readiness, and captured-handler ownership;
- an authoritative exact-value board with a secondary, direction-safe radar;
- content-free readiness provenance, evidence requirements, and next actions;
- the one-session local preview/approval dialog and minimized derived-metric share dialog;
- unique accessible identities, focus containment/restoration, keyboard cancellation, long-value wrapping, and 360–1040 px behavior.

Shared API contracts, transports, host call sites, generated files, backend adapters, metric calculations, global styles, and the UI backlog are unchanged.

## Initial audit and gap matrix

| Priority | Audited gap | Accepted correction | Verification |
| --- | --- | --- | --- |
| P1 | Profile state reset only when `profile.kind` changed, so same-kind A→B snapshots could retain the initial selection, pinned metric, or open dialog. | Use a complete content-free semantic owner identity, reset mutable state in a layout checkpoint without remounting live host controls, and bind dialogs to the opening owner. | Same-kind profile/provenance A→B tests plus the 30-test workspace host suite. |
| P1 | Radar pins were keyed only by metric key and could survive changed values or provenance. | Key radar interaction state by the exact metric/readiness identity, including distinct non-finite numeric states. | Same-key pin A→B regression. |
| P1 | Readiness could be attached across sessions/packs and duplicate rows were last-write-wins. A foreign pack key or preset could pass ownership, missing provider context failed open, malformed prop reports could throw, and raw caught error text could reach the UI. | Revalidate the complete bounded report before rendering; require exact session, preset, pack, analysis-profile, current provider context, key, and version ownership; withhold invalid reports; use fixed error and mismatch copy. | Cross-session, foreign-pack, foreign-preset, absent/mismatched-provider, malformed-report, duplicate, contradictory-state, and host readiness tests. |
| P1 | Missing counted values rendered as zero, and empty metric arrays triggered vacuous all-unavailable/all-omitted claims. | Preserve missing counts and empty sets as unavailable/empty, never zero or failure. | Malformed-count and empty-profile regressions. |
| P1 | Analyze actions could mix initial session identity with newer callbacks or publish delayed completions after close/replacement. Preview validation checked only the session. | Capture the opening handlers, abort and epoch-guard every operation, make detached controls inert, and validate the complete local/no-cost/ephemeral preview binding before approval. | Transport swap, delayed prepare/approve, cancel, expiry, binding mismatch, and host integration tests. |
| P1 | Share capability probes and runtime actions could throw, outlive close, or act after runtime/profile replacement. | Fail capability probes closed, allowlist derived labels, validate the PNG asset contract, revoke once, and guard every action by live runtime/asset ownership. | Capability-throw, runtime-swap, detached-action, delayed-copy, and revocation tests. |
| P2 | The radar visually preceded the exact metric values and could be read as the authoritative or composite result. | Put the authoritative exact-value board first; label the radar as a secondary overview; calculate no combined score. | DOM-order and hierarchy regressions. |
| P2 | Lower-is-better, unknown, malformed coverage, and exact fractions needed clearer separation from normalized radar geometry. | Plot only valid measured higher-is-better ratios; retain measured zero; exclude unknown and review-load axes; expose exact raw fractions, direction, and coverage separately. | Direction, zero, unknown, malformed, partial, and all-state radar tests. |
| P2 | Static IDs, passive focus, narrow two-column layouts, hidden mobile explanations, and weak forced-color treatment reduced parity. | Use per-instance IDs, modal focus traps with consumed `Escape` and connected-opener restoration, one-column narrow layouts, visible mobile explanations, semantic tokens, forced colors, and reduced motion. | Duplicate-instance, keyboard/focus, long escaped value, CSS/build, and compact host checks. |

## Accepted corrections

1. Preserve exact stored metric values as the authority. Readiness can explain a value but cannot create, erase, normalize, or replace it.
2. Keep missing token-like counts, fractions, coverage, and empty collections unknown or unavailable; no missing value is coerced to zero or failure.
3. Reset snapshot, pin, dialog, and local compatibility state at an exact same-kind profile transition while keeping the current host controls attached through background refreshes.
4. Withhold readiness unless session, preset, metric pack, analysis profile, provider, metric key, and version match the displayed profile and a present current-provider compatibility context. A malformed report is bounded before property access and cannot produce verified metadata; row-level contradictions use a fixed metadata-mismatch explanation.
5. Show known readiness and its no-action receipt as well as unknown, unsupported, incompatible, abstained, not-applicable, and failed explanations.
6. Render the exact metric board before the radar. The radar is a secondary fixed-scale overview of valid higher-is-better candidate ratios only and never produces a composite score.
7. Keep lower-is-better metrics in the exact board as raw review-load values. Measured zero remains plottable; unknown and invalid values are omitted rather than placed at the center.
8. Capture the exact session descriptor and prepare/approve/compatibility handlers when the analyze dialog opens. Later host callback recreation cannot silently mix transports into that review.
9. Validate preview ID, fingerprint, session, local destination, no-model/no-cost/ephemeral binding, versions, lifetime, message/character counts, and the exact unique Coaching v1 metric set before displaying an approval control.
10. Abort active dialog work on cancel/context loss and ignore delayed or detached prepare, compatibility, approval, copy, share, and download actions.
11. Allow the share dialog to render only a coherent, allowlisted, derived-metric snapshot and a bounded local PNG blob URL with a fixed filename. Raw/private profile labels and caught runtime details never enter the preview.
12. Use unique `useId` relationships for profiles, radars, opportunity maps, and dialogs; trap focus, consume `Escape`, and restore focus only to a still-connected opener.
13. Keep long opaque IDs and escaped synthetic copy wrap-safe; retain availability and explanation text at narrow widths; stack dialog actions into 44 px one-column controls.
14. Add scoped reduced-motion and forced-colors rules while reusing the existing semantic theme tokens.

## Privacy and authority boundary

- Tests use only reserved synthetic identifiers, fictional providers, `example.invalid` blob URLs, and escaped synthetic redacted text.
- No localhost, in-app browser, provider session, credential, raw transcript, private source content, real path, screenshot, or network service was inspected.
- Preview text is treated as sensitive ephemeral local-review material. It is never copied into errors, documentation, fixtures outside the direct synthetic test, or share output.
- Derived metrics and readiness remain sensitive metadata. Sharing is still blocked by the host until a separately reviewed calibrated export contract exists.
- A local approval receipt proves only that the exact reviewed preview was consumed and its immutable result loaded; it does not prove task success or user benefit.

## Files changed

- `frontend/src/features/quality-profile/QualityProfileView.tsx`
- `frontend/src/features/quality-profile/QualityProfileView.css`
- `frontend/src/features/quality-profile/QualityProfileView.test.tsx`
- `frontend/src/features/quality-profile/QualityRadar.tsx`
- `frontend/src/features/quality-profile/QualityRadar.css`
- `frontend/src/features/quality-profile/QualityRadar.test.tsx`
- `frontend/src/features/quality-profile/AnalyzeLocallyDialog.tsx`
- `frontend/src/features/quality-profile/AnalyzeLocallyDialog.test.tsx`
- `frontend/src/features/quality-profile/ProfileShareDialog.tsx`
- `frontend/src/features/quality-profile/qualityShareCard.test.tsx`
- `frontend/src/features/quality-profile/MetricOpportunityMap.tsx`
- `frontend/src/features/quality-profile/MetricOpportunityMap.css`
- `frontend/src/features/quality-profile/MetricOpportunityMap.test.tsx`
- `frontend/src/features/quality-profile/metricReadiness.ts`
- `frontend/src/features/quality-profile/metricReadiness.test.ts`
- this checkpoint note

## Automated verification record

- Direct UI-10 regression group: **6 files / 90 tests passed**.
- Entire quality-profile feature: **9 files / 131 tests passed**.
- Project workspace host integration: **1 file / 30 tests passed**.
- Independent frozen-tree re-audit: **passed**. It reproduced the original foreign pack, foreign preset, absent/mismatched current-provider context, and malformed report attacks; all now fail closed while the positive exact-owner control remains verified.
- Focused coverage includes all metric/readiness truth states; exact preset/pack/profile/session/provider ownership; absent and mismatched current-provider context; malformed prop reports; same-kind and same-key A→B; host callback recreation; transport/runtime swaps; detached actions; delayed prepare/approve/share completions; preview expiry/replacement/binding drift; exact raw versus radar direction semantics; zero versus unknown; long escaped synthetic text; duplicate IDs; focus trap, `Escape`, and return focus.
- TypeScript project build (`tsc -b --pretty false`): **passed**.
- Production frontend build: **passed**; the existing approximately 515 kB main-chunk advisory remains.
- Final integrated frontend run: **114 files / 1,219 tests passed**.
- Final locked-runtime Python repository run: **3,335 passed / 9 platform-skipped**; no failures.
- Repository privacy scan: **passed**.
- Owned-path whitespace validation: **passed**; Windows LF→CRLF notices only.
- No commit was created by this implementation agent.

## Later visual checklist

- Tour loading, no-run empty, known, partial, exact-scope omission, legacy unknown scope, incompatible provenance, stale pack, invalid contract, readiness load error, and readiness mismatch states.
- At 1040, 900, 760, 640, 460, 420, and 360 px, verify exact values remain first; the secondary radar, opportunity board, long identifiers, long errors, and dialog controls do not create horizontal page overflow.
- Confirm lower-is-better metrics never enter the radar; measured zero sits at the center; unknown and malformed values have no point; no total, average, or composite score appears.
- Analyze dialog: prepare, compatibility recheck, exact preview, expiry, approval, completion, cancel, and retry. Verify Tab order, visible focus, `Escape`, focus restoration, and no stale action after close or profile/session replacement.
- Share dialog direct state: rendering, unsupported clipboard/share, download, runtime replacement, delayed action completion, and revocation. Confirm only the minimized derived PNG is present and no raw/private label enters its accessible name.
- Light/dark, forced colors, reduced motion, enlarged text, keyboard-only navigation, and long escaped synthetic values: boundaries, state text, exact values, focus rings, and action order remain visible without relying on color alone.
- Snapshot A→B during a pinned metric, compatibility request, analyze preview, and share render; no A state or delayed completion may survive B's first committed frame.
