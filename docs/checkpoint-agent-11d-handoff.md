# Agent checkpoint 11d handoff

## Outcome

Every catalog-session update now reconciles the Agent page from the strict
record returned by the backend, and deleting the currently selected retained
chat no longer leaves a stale conversation shell behind.

Before this checkpoint, only project moves published their canonical response.
Rename, pin/unpin, archive, and restore refreshed the rail but left an open
retained chat's title and archive state stale. Successful deletion called a
draft-cleanup function only, so the deleted retained chat could remain visible
with resume, export, and fork controls targeting a record that no longer
existed.

The rail now uses one success-only session-update helper for rename, pin/unpin,
archive/restore, and move. AgentPage reconciles matching live caches and the
selected retained record. Deleting the selected retained chat clears its
history, artifacts, messages, selection, and stale action surface; deleting a
background record removes only its draft and leaves the foreground chat and
composer untouched.

## Correctness boundaries

- A canonical update is published only after the existing abort, mutation-owner,
  and revision checks succeed. Failed or superseded updates publish nothing.
- Live views accept only the canonical project and title fields that overlap
  their settings. Catalog-only pin and archive state remain in the strict
  catalog record.
- Rename, pin, archive, and restore do not blank and refetch unchanged retained
  conversation history. History reload now depends on session identity,
  project, retention mode, and history heads rather than unrelated catalog
  metadata.
- Archive immediately disables resume and fork through the selected canonical
  record. Restore re-enables them without reconstructing unchanged history.
- Successful selected deletion clears retained events and artifact state and,
  in a dedicated window, clears the deleted window target.
- Background updates and deletion never change the visible project or active
  composer.
- Live catalog deletion remains forbidden by the backend; this checkpoint does
  not weaken that rule.
- No real chat was renamed, pinned, archived, restored, or deleted during live
  validation.

## Validation

- Focused rail run: **24 tests passed**. Coverage includes canonical callbacks
  for rename, pin, archive, restore, and move, plus failure suppression.
- Focused AgentPage matrix: **4 tests passed** for selected rename,
  archive→restore without a history refetch, selected deletion cleanup, and
  background deletion continuity.
- Full frontend Agent integration: **176 tests passed** across the rail,
  complete Agent page, catalog parser, and retained-history parser.
- After TypeScript identified and corrected one helper narrowing boundary and
  two overly narrow synthetic mock signatures, the production TypeScript/Vite
  build passed with **559 transformed modules**. A post-correction focused run
  passed **28 tests**.
- The existing approximately 508 kB minified Agent-page chunk advisory remains
  performance debt rather than a correctness failure.
- Repository privacy scan passed. Diff validation found no whitespace error;
  two existing LF-to-CRLF working-copy notices remain.
- The rebuilt loopback app was reloaded at `/agent`. Its real retained chat
  exposed rename, move, fork, pin, archive, and delete actions; the bounded
  rename dialog contained the canonical current title. The dialog was cancelled
  without mutation and browser logs remained empty.
- Runtime census after validation: one loopback `pythonw` listener on port 8765,
  no listener on 8766, and no known model-serving process. No model, GPU
  runtime, MCP host, or visible terminal was started.

## Owner review

The app is already reloaded. Use only a disposable chat for destructive checks:

1. Rename an open retained chat and confirm both page headings update
   immediately.
2. Archive it and confirm the retained view says **Restore chat before
   resuming**; enable **Show archived**, restore it, and confirm **Resume chat**
   returns without a conversation reload.
3. Delete the selected disposable retained chat and confirm its retained
   timeline, Resume, Export, and Fork controls disappear.
4. With another chat open, delete a different background record and confirm the
   foreground project and composer do not change.

## Next slice

Agent-11e will make retained-history export revision-bound end to end. The local
route already accepts expected catalog and history revisions, but the browser
transport and Agent page currently omit them. The checkpoint will send the
visible heads, distinguish revision conflicts from download failures, use a
WebView-safe temporary-link lifecycle, and add success, conflict, local-file,
and cleanup tests.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
