# Agent checkpoint 10k — stable navigation and runtime controls

Date: 2026-08-29

## Outcome

The Agent project/chat rail no longer clears the active project or unmounts the
conversation when a search temporarily returns no matches. The selected chat,
retained conversation, and draft-owning work surface stay mounted while the
rail truthfully shows an empty filtered result. Clearing search restores the
project and chat rows without requiring another selection.

The rail and shared-runtime card now also meet the checkpoint's interaction
baseline: primary navigation/runtime controls are at least 44 px high, project
and chat dialogs keep keyboard focus inside the modal, background scrolling is
locked while a modal is open, and Escape restores focus to the invoking
control.

## Reproduced defect

Entering a search that excluded the selected project caused the catalog-fetch
effect to treat the filtered response as an authoritative deletion. It called
the project-selection callback with a replacement or `null`, which unmounted
the still-valid active conversation and showed the empty-session state. The
chat returned to the list after clearing search, but the user had to select it
again.

## Implemented boundary

- Search filtering no longer reconciles or clears the active project.
- The rail retains a bounded identity snapshot for the selected project so the
  collapsed rail remains intelligible while that project is outside the
  filtered result.
- Unfiltered catalog loads still reconcile genuinely missing projects; the fix
  does not preserve deleted or unavailable records indefinitely.
- Project/chat modal focus is derived from DOM order, wraps in both directions,
  and restores to the trigger on Escape.
- Modal open state locks both document and body scrolling and restores their
  prior values on close.
- Rail icon buttons, search, project/chat rows, runtime selects, runtime
  details, and Start/Stop/Refresh actions have a 44 px minimum target.

No model was started, no GPU memory was allocated, and no project/chat record
was created, renamed, archived, or deleted during live verification.

## Verification

- Focused rail/runtime/layout suite: **41/41 passed**.
- Real Chromium search-preservation scenario: **1/1 passed**.
- Production TypeScript/Vite build: **553 modules**, passed.
- Rebuilt live application at **1046 × 912**:
  - no-match search left the retained conversation mounted;
  - collapsed navigation retained the selected project identity;
  - clearing search restored both project and chat rows without reselection;
  - all **12** measured rail/runtime controls were at least **44 px** high;
  - create-project dialog wrapped Shift+Tab/Tab, locked background scrolling,
    and restored focus and scrolling on Escape;
  - selecting an installed model left runtime state **Stopped**, enabled Start,
    kept Stop disabled, and exposed GPU placement plus an 8K context choice;
    the selection was cleared without starting the model;
  - no horizontal overflow and zero browser diagnostics.
- Final runtime inventory: one Prompt Enhancer window, one listener on
  `127.0.0.1:8765`, zero detected local-model server processes, and no terminal
  windows opened by this checkpoint.

The full historical frontend/backend/browser matrices were not rerun because
this slice is limited to the catalog rail, runtime-card interaction styling,
and their focused regression contracts. Their last complete receipts remain in
the earlier Agent checkpoints.

## Next checkpoint

Agent-10l should audit the conversation, composer, and activity timeline as one
chat-first surface at desktop and narrow widths. It should verify streaming and
Stop affordances, reasoning/tool disclosure, composer reachability and keyboard
flow, draft preservation, empty/error/retry states, and message/code rendering.
Only reproduced failures become implementation work. The owner-controlled
artifact, separate-window, real-model, reviewed-write, unload, and GPU-cleanup
acceptance remains an explicit later gate.
