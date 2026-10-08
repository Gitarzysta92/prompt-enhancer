# Checkpoint Release-01a.1 entry

Status: automated complete; owner click-later review queued
Entered: 2026-09-01
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Prerequisite: [Sweep-01c.3 handoff](checkpoint-sweep-01c-3-handoff.md)
Handoff: [Release-01a.1 handoff](checkpoint-release-01a-1-handoff.md)

## User-visible outcome

An existing durable Agent project/chat database either upgrades completely to
the current application schema or remains at its prior committed schema/data
head with one fixed, content-free failure. The app must never silently repair a
gapped migration ledger, overwrite a conflicting SQLite schema head or present
a current healthy catalog as invalid because the frontend expects an obsolete
schema number.

## Entry evidence and gap

- The primary analytics database already keeps SHA-256 migration checksums and
  refuses incomplete history.
- The dedicated Agent catalog reaches schema 29 but records only version and
  timestamp. Initialization trusts the maximum ledger value, does not require
  every earlier version and rewrites `PRAGMA user_version` to the current head.
- Historical Agent upgrade tests cover important populated transitions, but no
  single matrix upgrades every supported schema 1 through 29.
- The strict frontend hardening parser still accepts only Agent schema 6 even
  though the backend reports the current schema dynamically.
- Existing process, command, model, MCP and desktop cleanup suites remain the
  prerequisite for later Release-01a process-composition slices; they are not
  represented as newly proven by this entry.

## Frozen implementation boundary

1. Append Agent catalog schema 30 without rewriting migrations 1 through 29.
2. Persist a content-free SHA-256 checksum for every Agent migration and verify
   the exact contiguous ledger before any upgrade statement runs.
3. Require the SQLite `user_version`, ledger head and checksum head to agree.
   Missing, changed, split or unledgered state fails closed without mutation.
4. Upgrade a populated synthetic v1 project/chat through every supported source
   version 1 through 29, checking data survival, integrity and foreign keys.
5. Force schema-30 interruption after its first DDL and prove the sidecar,
   ledger and SQLite head roll back together.
6. Replace the obsolete frontend schema-6 literal with the backend's positive
   integer contract and expose one fixed migration-invalid diagnostic.

## Privacy and safety boundary

- Tests create disposable SQLite files containing only reserved hexadecimal
  identifiers, fictional labels, fixed timestamps and example paths.
- No provider cache, real project, transcript, prompt, workspace content,
  credential, model, GPU, command or MCP host is read or started.
- Failure diagnostics contain only fixed reason codes; checksums cover migration
  statements, never user records.
- Historical migrations remain immutable. Any discovered schema requirement is
  appended as a new migration.

## Exit gate

- Every supported Agent schema upgrades to the current head and is reopenable.
- Gapped history, checksum drift, schema-head disagreement and unledgered tables
  are refused without changing the failing database.
- Interrupted schema 30 leaves the complete schema-29 state intact.
- Backend migration/hardening/HTTP tests, frontend strict-contract tests,
  generated OpenAPI, full privacy checks and the proportional release/process
  matrix pass before the checkpoint is handed off.
