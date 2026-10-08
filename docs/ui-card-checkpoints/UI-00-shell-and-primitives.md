# UI-00 · Application shell and shared primitives

Status: **implementation complete · independently rechecked · full gates green**
Visual review: pending owner review in the local app
Baseline: `a3578a4` (last pushed pre-UI-00 checkpoint)
Scope owner: responsive application shell, bootstrap and route boundaries, browser navigation adapter, and shared UI primitives

## Frozen scope

This checkpoint establishes the interaction and truth conventions that later
card checkpoints inherit:

- vertically grouped desktop navigation with a dedicated scroll owner and a
  fixed privacy/runtime footer;
- a compact mobile header and contained navigation dialog with visible
  privacy/runtime truth;
- canonical browser history behavior, route-title and focus ownership, safe
  bootstrap failure, and retryable route failure;
- modal stacking, background isolation, scroll locking, focus containment,
  Escape ownership, and exact restoration;
- truthful loading, empty, unavailable, unknown coverage, fractional progress,
  status-pill, and tab behavior;
- desktop/mobile, light/dark, reduced-motion, forced-colors, keyboard, wrapping,
  clipping, and 12 px minimum navigation-copy checks.

No provider adapter, runtime database, private session, metric calculation, or
raw transcript surface is part of this slice.

## Audit and accepted corrections

| Priority | Reproduced gap | Accepted correction |
| --- | --- | --- |
| P1 | The short desktop shell clipped lower navigation and the privacy footer. | Give the grouped primary navigation the only vertical scroll region, keep the footer fixed, and reveal a deep current route with bounded container scrolling that does not change keyboard start order. |
| P1 | Mobile hid runtime/privacy truth behind a long horizontal route strip. | Use a compact sticky header, persistent privacy/runtime marker, and accessible modal navigation drawer. |
| P1 | Nested dialogs could disagree about visual, keyboard, pointer, and assistive-technology ownership. | Register one ordered dialog stack; derive z-layers and topmost focus/Escape ownership from it; make every lower root inert and hidden from assistive technology; restore the remaining layer exactly. |
| P1 | Bootstrap rejection could leave a blank root. | Render an immediate accessible bootstrap loading state and a fixed, privacy-safe reload boundary without exposing the caught exception. |
| P1 | No-eligible coverage and malformed progress could be announced as numeric zero. | Emit numeric meter semantics only for valid measurable coverage, retain no-eligible/malformed states as nonnumeric unknown, and preserve small nonzero progress percentages. |
| P2 | A route bundle failure could only leave the route and successful retry discarded focus. | Add same-route retry, optional truthful exit, fixed safe copy, and focus the recovered main region. |
| P2 | Browser Back could update content behind an open drawer; breakpoint expansion could strand focus on a hidden opener. | Close on external route change and restore main focus; on mobile-to-desktop expansion move focus to the current desktop route. |
| P2 | Reviewed-task loading disappeared after the mobile drawer closed. | Keep a visible live status and busy mobile menu copy until the bounded lookup resolves, fails, or is superseded. |
| P2 | Same-route navigation duplicated history, while malformed multi-slash paths could be mistaken for the canonical route. | Treat the canonical path and one optional trailing slash as equal; repair malformed paths through a real navigation. |
| P2 | Horizontal tabs captured vertical arrow keys and transport-backed research tabs auto-activated during focus movement. | Leave Up/Down to page scrolling and use manual activation for the research transport panels. |
| P2 | Loading announcements and neutral/unknown pills conflated state semantics. | Use an atomic polite status without self-suppressing `aria-busy`; keep ordinary neutral state visually distinct from explicit unknown. |
| P2 | Mobile drawer section labels fell below the 12 px floor. | Apply the same minimum readable size to grouped labels, buttons, secondary copy, and badges at 360 px. |

## Privacy and authority boundary

- Browser work used the fictional in-memory transport at `127.0.0.1:4173`.
- The synthetic fixture blocks and records any attempted `/auth`, `/health`, or
  `/v1` request; the complete UI-00 browser run made none.
- No real provider session, prompt, transcript, credential, runtime database,
  derived private metric, browser storage, or local configuration was read.
- The integrated app at `127.0.0.1:8765` was reloaded after the production
  build, but its content was not inspected or copied.
- Missing evidence remains unknown. Objective verification remains distinct
  from inferred text quality and from any developer/person ranking.

## Main implementation paths

- `frontend/src/app/App.tsx`
- `frontend/src/app/BootstrapState.tsx`
- `frontend/src/main.tsx`
- `frontend/src/shared/platform/browserPlatform.ts`
- `frontend/src/shared/ui/AsyncState.tsx`
- `frontend/src/shared/ui/CoverageBar.tsx`
- `frontend/src/shared/ui/Dialog.tsx`
- `frontend/src/shared/ui/ProgressMeter.tsx`
- `frontend/src/shared/ui/StatusPill.tsx`
- `frontend/src/shared/ui/Tabs.tsx`
- `frontend/src/shared/ui/primitives.css`
- `frontend/src/styles.css`
- focused unit and synthetic Playwright fixtures/specifications beside those paths

## Automated verification record

- Frozen focused component/integration gate: **11 files / 84 tests passed**.
- Final shell/platform/dialog confirmation after audit repairs: **3 files / 44 tests passed**.
- Focused UI-00 and standalone-route browser gate: **16/16 passed**.
- Complete frontend unit gate: **118/118 files, 1,321/1,321 tests passed**.
- Complete synthetic Chromium gate: **49/49 passed**.
- TypeScript and production Vite build: **passed**, 241 modules transformed.
- Generated OpenAPI TypeScript drift check: **passed**.
- Repository privacy scan and whitespace check: **passed**; Windows LF-to-CRLF notices only.
- Independent shell and primitive confirmation audits: **no blockers remain**.

Screenshot baselines were intentionally not added because fonts and rendering
platforms are not pinned tightly enough for stable pixel diffs. The synthetic
browser matrix instead asserts structure, exact state truth, viewport bounds,
focus, font floors, theme persistence, reduced motion, and forced colors.

## Owner visual checklist

1. At 1280×720 and a shorter desktop height, confirm the active route is
   visible, the navigation alone scrolls, and the privacy footer never clips.
2. At 360×800, confirm the compact header, theme control, runtime marker, and
   drawer hierarchy are clear; scroll through every route group.
3. Use keyboard only: skip link, drawer open/close, current-route focus, route
   selection, browser Back, and breakpoint expansion.
4. Inspect light and dark themes, enlarged text, forced colors, and reduced
   motion; state must never depend on color alone.
5. Tour loading, ordinary empty, closed/unavailable, error/retry, numeric and
   unknown coverage, tiny nonzero progress, tabs, neutral status, and explicit
   unknown status.

## Deferred, not lost

- Overview route content currently meets the shell edge more tightly than the
  eventual card layout should, and its card-level icon semantics still need a
  dedicated pass. Both are recorded under UI-13, not silently accepted here.
- Card-specific hierarchy, prompting, metric generation, repeated card icons,
  and dense-state design remain assigned to their UI-03 through UI-20 owners.
- Owner visual approval is still required; automated and synthetic visual
  evidence does not claim subjective approval.
