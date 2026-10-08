# Agent checkpoint 10l — streaming chat and output recovery

Date: 2026-08-29

## Outcome

The active Agent conversation now behaves more like a current coding-agent
chat while a response is in progress. The user can write and retain the next
text instruction during streaming or response cancellation instead of losing
access to the composer. Stop remains the only active-response action; Send
appears and becomes available only after the current response has settled.

The transcript also exposes a clear recovery control when the user scrolls
away from the newest activity. Auto-follow pauses without snapping the reader
back to the bottom, **Jump to latest activity** appears, and activating it
returns to the live edge with keyboard focus placed on the transcript.

## Reproduced defects

1. The message textarea was disabled whenever `current.running` or the Stop
   transition was true. A user could not draft the next request while reading a
   streaming response, even though per-chat draft ownership was already safe.
2. The transcript correctly stopped auto-following after a user scrolled up,
   but there was no visible way to return to the newest output. Long tool or
   reasoning runs therefore required manual scrollbar recovery.

## Implemented boundary

- Text drafting remains enabled while a response is running or stopping.
- The running state continues to show **Stop response**, never Send; a draft is
  not silently queued or transmitted.
- When the response settles, the exact per-chat draft remains and **Send**
  unlocks.
- The composer has persistent state-aware guidance:
  - idle: `Ctrl/⌘+Enter sends · Enter adds a line`;
  - running/stopping: the next message can be written now and Send unlocks only
    after the response ends.
- Attachment staging remains bounded during an active response; this slice
  changes text-draft ownership, not model-bound media admission.
- Transcript follow state is explicit and resets on session/resume/new-chat
  boundaries.
- **Jump to latest activity** is sticky, keyboard reachable, at least 44 px,
  scrolls to the live edge, and focuses the transcript after activation.
- Model-provided reasoning and expandable tool results now have at least 44 px
  disclosure targets. The UI continues to state that hidden chain of thought is
  not reconstructed.

No endpoint, approval, file-mutation, history-retention, or model-runtime
authority changed in this checkpoint.

## Verification

- Complete AgentPage lifecycle suite: **120/120 passed**.
- Focused rendering, activity, turn-details, copy, and layout suite:
  **31/31 passed**.
- Real Chromium streaming scenarios at **390 × 844** and **1046 × 912**:
  **2/2 passed**. Each verified:
  - live response and model-provided reasoning visibility;
  - editable next-message draft with Stop visible and Send absent;
  - 44 px reasoning disclosure;
  - paused transcript follow plus Jump-to-latest recovery;
  - draft preservation and Send availability after terminal output;
  - no horizontal overflow.
- Production TypeScript/Vite build: **553 modules**, passed.
- Rebuilt live application at **1046 × 912**: no horizontal overflow and zero
  browser diagnostics.
- Final runtime inventory: one Prompt Enhancer window, one listener on
  `127.0.0.1:8765`, zero detected local-model server processes, and no terminal
  windows opened by this checkpoint.

The full historical backend and unrelated-page matrices were not rerun because
this slice changes the Agent conversation client and its focused browser
contracts only. Existing endpoint/file/runtime receipts remain authoritative
for those separate areas.

## Next checkpoint

Agent-10m should audit **Files & review** as the coding workbench: browse and
refresh, open and view, create files/folders, edit, diff, multi-file staging,
rename/move, recoverable removal, agent-proposed changes, focus/dirty-draft
preservation, and responsive review-drawer behavior. Only reproduced failures
become implementation work. Artifact/document viewers, attachment polish, the
separate-window native bug, and real-model/controller acceptance remain later
explicit gates.
