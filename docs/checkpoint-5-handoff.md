# Checkpoint 5 handoff

Status date: 2026-08-22

This handoff closes the bounded stabilization sequence for the evidence-bound
r7 requirement-action tranche. It does not authorize a commit or begin the
card-by-card UI repair phase.

## Stable state

- Branch: `codex/real-metrics-campaign`
- Baseline commit: `a1c94dc21707ce88b111aaec43474952bfe8756e`
  (`feat(metrics): add reviewed r6 decomposition evidence`)
- Database schema: 57
- Local service: loopback-only, metadata tier, offline-only cost mode
- Current operability catalog: 16 operable, 0 model-authoritative measured,
  4 provider-adapter-required
- Commit created by the stabilization work: no

Before these handoff documents were added, the tranche contained 107 working
tree entries: 90 modified tracked files and 17 intentional new r7 source/test
files. No file was staged or deleted. The tracked diff contained 15,393
insertions and 902 deletions.

## Frozen migration identities

These applied migrations are immutable. Any future schema change must append
M58 rather than edit M57 or an earlier migration.

| Migration | SHA-256 |
| --- | --- |
| M54 | `aafd1c1cc0c121db267d02f7cf14c1a05e6a796af5affda2988fa700216576ac` |
| M55 | `c33be75cef513923f86796ec2fe6feb76216c26d3430384b78409d0c2b3f78a2` |
| M56 | `c744325d82ef54d1349512ba7e833ed44db93db7364ca325ee4cf73cb0ec553f` |
| M57 | `862957517aecd544054c60f4a1d486a70ae97656bdf74c5252217ebf59887776` |

## Generated contract identities

Both generated artifacts belong in the eventual tranche commit. They are
explicitly LF-pinned for deterministic hashes across platforms.

| Artifact | SHA-256 |
| --- | --- |
| `docs/openapi.json` | `25c1c2fb7cd49880c9e800b37873b811138f2cae115f9ace1eb44ff85b85f797` |
| `frontend/src/shared/api/generated/openapi.ts` | `0ab459fe41a9b4df240c21c329c8981e279f7f736c14bc4630524cffb00d584d` |

## Release evidence

- Backend: 3,294 passed, 9 expected Windows capability skips
- Frontend: 1,099 passed across 112 files
- TypeScript and production frontend build: passed
- OpenAPI/runtime/generated-client byte parity: passed
- Python compile/import, privacy scan, migration ledger, and diff checks: passed
- Independent fresh-r7 repair recheck: passed
- Local root page, health endpoint, and JavaScript asset: HTTP 200

The release audit found and closed one compatibility regression: fresh r7 runs
were initially excluded from the inherited r5/r6 reviewed requirement-plan
workflow. The final HTTP regression proves fresh r7 contract, preview, import,
owned-native review and confirmation, exact authority inheritance into the next
r7 run, and stale or mismatched source rejection.

## Accepted non-blocking limitations

- Requirement-action evidence remains non-operable for providers that cannot
  supply a complete, same-snapshot safe-event and redacted-descriptor authority.
  The UI and catalog must continue to say provider adapter required.
- The main frontend bundle is about 515 kB minified, slightly above Vite's
  advisory threshold.
- One existing Starlette test-client deprecation warning remains.
- Windows line-ending notices remain informational; diff validation is clean.
- There is no screenshot visual-regression suite. Component tests establish
  contracts, states, actions, and accessibility semantics, not visual polish.
- Card/layout corrections are deliberately outside the stabilized tranche.

## Packaging recommendation

The backend migrations, repositories, orchestration, generated contracts, and
large shared tests overlap heavily. The safest packaging is one atomic commit
for the complete stabilized tranche after inspecting the staged diff and
confirming a public or noreply commit identity.

Suggested subject:

`feat(metrics): ship evidence-bound r7 requirement-action projection`

Do not include build caches, local databases, runtime state, logs,
`frontend/dist`, `frontend/node_modules`, `.pytest_cache`, or temporary export
files. All 17 pre-handoff untracked files are intentional r7 source or tests.

After that atomic commit, each UI-card repair should be a separate bounded
commit or one tightly related card group. The ordered inventory and acceptance
template live in `docs/ui-card-review-backlog.md`.
