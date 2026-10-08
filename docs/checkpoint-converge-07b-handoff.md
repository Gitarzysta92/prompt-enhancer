# Converge-07b.1 handoff — private update root and replay security

Status: **C07b.1 automated security slice validated/complete.** C07 remains
partial: package publisher, installation, relaunch and rollback acceptance are
still open. This packet does not claim a usable production self-update.

Workflow remains supervised: root reads, assigns, reviews and independently
validates; Terra owns harder implementation, Luna owns smaller changes/tests/
docs, and root does not edit implementation.

## What this slice closes

- A validated package trust file may prepare only the fixed direct
  `application-updates` child. The Windows adapter creates a missing child with
  a protected exact DACL for the current user and SYSTEM, then re-inspects it.
  Existing leaves are inspection-only; unsafe permissions are refused without
  ACL repair or recursive parent changes.
- The application retains one bounded, signed manifest envelope in a fixed-name
  atomic ledger. Compare-and-swap persistence is guarded so concurrent
  coordinators cannot lower the authenticated release floor.
- Replay authentication is separate from current download eligibility. A
  historically authentic but naturally expired envelope still anchors the
  floor; older or same-version/changed manifests remain refused after restart.
- Invalid trust, malformed artifact templates, refused private-root preparation,
  ledger quarantine and persistence failure fail closed before download. The
  default and every current status keep `can_apply=false`.
- Legacy explicit no-root callers remain memory-only and make no durable replay
  guarantee. The local CAS guard is not a claim of same-user/admin isolation or
  full-state rollback protection; those remain outside this checkpoint's threat
  model and are not guaranteed by a future installer alone. Native publisher,
  installation, relaunch and rollback gates are separate.

The native API choice follows the documented [CreateDirectoryW security
attributes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createdirectoryw)
and read-only [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
boundaries. Reports are content-free: they expose no path, SID, username or
account data.

## Evidence

- `tests/test_application_update_07b_acceptance.py`: **13/13 passed** in the
  focused synthetic run (`uv run pytest tests/test_application_update_07b_acceptance.py -q --tb=short -p no:cacheprovider`).
  The Windows-native temporary-root check ran on the owner Windows host; all
  other fixtures use temporary synthetic roots, signed bytes and MockTransport.
- Coverage includes unconfigured no-touch composition, refused existing-root
  preparation, malformed v2 trust, schema-v1 metadata-only replay across
  recomposition, older and changed-manifest restart refusal, expired-floor
  retention, ledger quarantine, staged-old versus metadata-new high-water and
  no-apply status.
- C07a evidence and counts remain historical in
  [the C07a handoff](checkpoint-converge-07a-handoff.md); this amendment does
  not rewrite or combine them. Root's final combined C07b build, API, privacy,
  browser and integration evidence is current below.

- Final owning backend updater/configuration/replay/private-root/distribution/
  runtime/loopback/OpenAPI gate: **244 passed, 2 Windows symlink-creation
  capability skips**. Full frontend: **2,806 tests passed** across 190 files.
  Rebuilt production real-loopback browser: **16/16 passed**, with startup,
  cleanup, listener release, temporary-state removal and zero model-runtime
  evidence all true. Production build, API check, privacy scan and diff check
  passed; the existing large AgentPage chunk warning remains non-blocking.
  No production app reload, real model/VRAM, installer, external release
  download, signing, commit or push was performed.

## Explicit non-claims

This packet does not provide all-application DACL migration, power-loss or
hardware anti-rollback proof, a production release URL/key/certificate,
publisher verification, MSIX/native installation, apply, process handoff,
relaunch, rollback, or owner UX acceptance. `STAGED`-style evidence remains
digest/size-verified bytes, not an installed or publisher-verified application.

## Next safe packet

The next gate is the package publisher and MSIX handoff, followed by exact
process shutdown, relaunch/recovery and rollback acceptance. Until those gates
are current, C07 stays partial and no production self-update should be
advertised.
