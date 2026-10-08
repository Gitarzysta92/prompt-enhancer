# Checkpoint 31: revision-bound reviewed-write publication

Status: scoped implementation and automated verification complete on Windows.
The whole application remains open against the verification ledger. The single
existing privacy-artifact finding remains open.

## What changed

- Agent write policy is now versioned as `workspace-publication.v1`. The model
  is told that a write is revision-bound and that stale, failed or unverified
  outcomes require inspection before another change.
- A reviewed write binds the lexical path, parent identity, prior file identity,
  revision and exact proposed digest. A process-wide lock closes the
  cross-session compare/publish gap. Two sessions applying the same stale review
  cannot both succeed.
- Full content is written to a private same-directory stage, flushed and read
  back before publication. Stop is checked throughout staging and immediately
  before publication. Cancellation does not publish and does not produce a
  successful write receipt.
- Existing exact content is a true no-op, preserving the file identity and
  timestamps. New names publish create-if-absent; a concurrently created target
  wins and the reviewed write is refused.
- Windows pins the admitted ancestor chain and opens the final directory for the
  mutation. Existing files use `ReplaceFileW` with a backup. The displaced
  content/identity and new staged identity/content are verified. A late
  concurrent edit is restored. Hard-link insertion, read-only files, target
  replacement and folder replacement fail closed.
- Windows private stages and displaced backups are removed through owned handles.
  Cleanup failure is never hidden. If publication may have begun, the outcome is
  unverified; before publication, the outcome states that private cleanup is
  unconfirmed and that the reviewed path was not changed.
- POSIX uses descriptor-relative operations and atomic name exchange, failing
  closed where the filesystem lacks the required primitive. It is implemented
  but was not executed on this Windows host; ownership, ACL, xattr and
  filesystem-specific metadata parity remain unaccepted.
- Actual Agent tool execution now carries the turn's cancellation scope into
  the write apply. The editor no longer performs a redundant post-apply read to
  decide success; it accepts only the exact verified receipt.
- HTTP status mapping and frontend reason allowlists distinguish verified
  no-write, cleanup uncertainty and unverified publication. The editor always
  keeps the draft. Verified no-write remains reviewable; uncertain outcomes lock
  review and require Reload. Backend detail and fictional canaries are not shown.

Windows API references:

- [ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew)
- [SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)
- [FILE_DISPOSITION_INFORMATION_EX](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/2e860264-018a-47b3-8555-565a13b35a45)

## Outcome contract

| Outcome | What is known | UI recovery |
| --- | --- | --- |
| Published / unchanged | Exact reviewed revision is verified; an applied receipt exists | Show the receipt |
| `workspace_write_failed` | Publication was refused or the prior version was verified restored | Keep draft; allow a fresh review |
| `workspace_cleanup_failed` | Publication did not start; private-stage cleanup is unconfirmed | Keep draft; block review and inspect/reload |
| `workspace_verification_failed` | Publication or rollback may have occurred and exact state could not be proven | Keep draft; block review and reload |
| Revision/root/file changed | Reviewed authority is stale | Reinspect and create a new preview |

## Verification receipts

- Python compilation: passed for the Windows workspace helper, shared workspace
  I/O, reviewed-write service, editor service, Agent service and write-boundary
  regressions.
- Consolidated backend checkpoint selection: **304 passed / 17 files** in
  **78.31 s**, with the existing Starlette/httpx deprecation warning and no test
  skips in this selection.
- Focused write-boundary file: **14 passed**. It covers stage/write/sync/cleanup
  failure, exact no-op, cancellation for new and existing files, read-only
  refusal, shared-writer edits, cross-session applies, hard links, directory
  swaps and the real Windows replacement primitive.
- Full frontend: **1,755 passed / 128 files** in **136.90 s**.
- Strict E2E TypeScript: passed for the workflow fixture/spec and real-server
  spec. Production build and generated API consistency: passed.
- Full synthetic browser suite: **105 passed** in about **1.1 min**.
- Full loopback real-server browser suite: **30 passed** in **51.5 s**. These are
  135 distinct full-suite cases; focused reruns are not added to the total.
- Six new responsive workflows passed at 360 and 1440 px: verified rollback,
  pre-publication cleanup uncertainty and unverified publication. The in-app
  browser separately exercised file open, edit, review and apply. It confirmed
  the exact draft stayed present, Review disabled, Reload enabled, the fixed
  alert was visible and the private synthetic message did not leak. The owned
  browser tab was closed.
- Tracked-diff and checkpoint-new-file whitespace checks passed. The privacy
  scanner reports exactly the one unchanged old synthetic SQLite artifact under
  `test-results`; no exclusion, deletion retry or scanner weakening was used.
- Final resource check found zero `llama-server` processes and no listeners on
  the real-test or owner-app ports 4175/8765. The pre-existing synthetic
  development listener on loopback port 4173 was preserved.

## Explicit limits and next work

- This is a strong Windows publication receipt, not universal filesystem or
  crash-consistency certification. The POSIX exchange branch needs Linux/macOS
  execution plus explicit ownership, ACL and xattr policy tests.
- A single-file atomic replacement is not a multi-file transaction or a net Git
  change inventory. Commands can still create effects outside reviewed writes.
- Native folder-picker and protected-action confirmation require owner-presence
  acceptance. Ordinary-browser tests correctly fail closed without it.
- Agent conversations remain memory-only. Durable, privacy-tiered retention,
  richer multi-file editing and final owner UI preference review remain separate
  slices.
- No real provider data, credentials or owner configuration were used. No GPU
  model was loaded for this checkpoint. The normal owner app was not restarted.
