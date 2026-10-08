# Checkpoint 25: compare ratings of the same reviewed evidence

Scope: Calibration, local judgment and annotation case provenance. This closes a
specific comparison error, not the whole product or a model-quality evaluation.

## What was wrong

- Agreement joined human and model labels by session and metric even when the
  person had read different evidence from the model's bounded redacted window.
  Current generation protocols alone did not prove matching review cases.
- A reused model alias could mix recorded model identities. `cannot_judge` could
  enter the agreement denominator instead of remaining an abstention.
- A context-length retry could save the original window's identity rather than
  the smaller evidence actually judged. Annotation completion could count partial
  or unbound labels, and a remote result's claimed count was not sufficient proof
  of locally recorded labels.
- Component mocks missed transport failures: safe review-expiry codes and JSON
  headers were missing. A separate real API check then found shared middleware
  overwrote the review's required private/no-store cache policy.

## Implemented

- The Calibration page shows the exact bounded redacted task anchor and recent
  tail, with standard 15,000-character and short 6,000-character views. Evidence is
  escaped plain text. Truncation, unavailable review, consent requirements and
  expired receipts have explicit states.
- `calibration-case.v1` binds the provider, session, source-window fingerprint and
  canonical rendered evidence. It identifies what was displayed, not merely the
  configured character budget. The local judge seals the actual retry window.
- Save requires a current review receipt and the person's acknowledgment in the
  UI. Receipts retain only case identity in server memory, expire after 15 minutes
  and are bounded to 128 entries. Review honors the existing reader setting and
  redacted-content consent; missing, foreign, expired or revoked receipts fail
  closed. Refresh preserves the draft but requires a new acknowledgment.
- Schema 61 adds nullable provenance columns. New receipt-bound ratings use
  `calibration-rating-v2-reviewed-case`; historical rows and old submissions
  without a receipt stay readable and unbound. They are never backfilled into
  reviewed evidence. A multi-question save commits all labels and revisions in
  one transaction or rolls all of them back.
- Agreement requires the current judgment protocol, one recorded model identity,
  matching case/source fingerprints and the current human rating version.
  Unmatched ratings and abstentions are counted separately. No comparable pairs
  remains unknown, not zero percent. An explicit alias with mixed identities is
  ambiguous and is not pooled.
- Agent/central annotation receipts carry case provenance and reject substituted
  evidence. Work completion requires all rubric labels for one known case.
  Remote accounting uses accepted local records rather than a server's claimed
  count; partial, duplicate or foreign receipts cannot inflate completion. The
  central SQLite store now closes connections on success and failure.
- Review and save use the real HTTP transport's safe closed error codes. Review
  requests send JSON and require private/no-store responses; shared middleware
  preserves this policy on all Calibration responses. Browser-cookie review/save
  requires same-origin and CSRF proof. Rejection never reads evidence or stores a
  rating. The token-authenticated API remains a declarative interface, not proof
  that an independent human supplied a label.
- Exports include per-row case/version provenance, but no evidence text. The UI
  calls these sensitive derived metadata; pseudonyms and hashes are not anonymous.

## Verification evidence

- Initial comparison regressions: 11 failures with one passing control before
  the repair. Three direct HTTP transport regressions reproduced missing safe
  codes/cache acceptance; the new intercepted browser recovery failed at both
  widths before the transport fix. Two real API cache-policy tests reproduced
  the middleware defect before its correction.
- Final reviewed-case, comparison and annotation tests: **54 passed** across
  three files. Coverage includes TTL/restart/consent/ownership, bounded receipts,
  historical migration, atomic rollback, cookie/CSRF and token HTTP paths,
  tampered/partial remote receipts and SQLite connection cleanup. A known-answer
  case reports 3/4 agreement and kappa 7/11, excluding one unmatched rating and
  one abstention from its denominator.
- Full backend: both non-overlapping sorted-file shards finished, covering all
  **260 test files**. Their initial receipts were **1,919 passed / 7 failed /
  4 skipped** in 16m21s and **1,986 passed / 17 failed / 5 skipped** in 20m51s:
  **3,905 passed, 24 failed, 9 skipped** in total. Twenty-two failures were
  assertions still loaded with schema-60 expectations while the source fixtures
  were being updated for schema 61. One synthetic downgrade helper also retained
  the new columns while falsely marking its database as version 55; that fixture
  now removes those columns and asserts their absence before exercising the real
  upgrade. All 23 corrected cases passed targeted reruns. Production migration
  checks were not relaxed. The remaining failure is the known privacy artifact.
  The final combined current-source run passed **107 tests** in 123.69 seconds:
  all 23 corrected cases plus reviewed-case/comparison/annotation, local judgment,
  HTTP/authentication/reader and OpenAPI tests. This is corrected-case coverage,
  not a claim of a clean all-green full-backend run.
- The nine skips are this Windows host's unavailable file/directory symlinks:
  database, model provenance/evaluation, quarantined reader, scanner, social
  SQLite and home-boundary tests. They remain unverified on this host, not passes.
  The existing test-client deprecation warning remains.
- Final full frontend: **1,623 passed across 124 files** in 149.44 seconds, with
  two workers. An initial broad run had 1,619 passes and an unrelated Team
  Analytics timeout; its unchanged 18-test file passed in isolation. Two later
  complete runs passed with the final added cases. No assertion or timeout was
  weakened; constrained-worker runs avoid competing with the backend shards.
- Browser suites: **81 synthetic workflows** in 39.9 seconds and **20 intercepted
  HTTP cases** in 20.9 seconds passed. These exercise the real frontend transport but do not substitute for
  the separate full-application HTTP tests above.
- In-app browser inspection at 360 and 1440 px verified the case selector,
  refreshed identity, truncation notice, readable wrapped evidence and absence of
  horizontal page overflow. The browser skill supplied the interactive layout
  check. No screenshot was saved in the repository.
- Production build, generated API consistency, strict browser-fixture TypeScript,
  Python compilation and whitespace checks passed. Updating the export's public
  description initially made the byte-exact OpenAPI check fail; the schema and
  client were regenerated and all six OpenAPI tests passed. Sixteen separate
  HTTP/authentication/reader checks also passed. The final production build and
  generated client checks passed again after that regeneration.

These are separate verification runs, not a combined count of unique tests.
Synthetic evidence does not establish representative model quality.

## Later review checklist

1. Open Calibration, choose a session and read **Evidence to rate**. Standard and
   Short display their own bounded case; no model label appears by your choices.
2. Choose labels. Save remains disabled until the evidence is available and you
   acknowledge that the answers describe that case. Saving records a revision.
3. Refresh or let the review expire. The draft remains, but acknowledgment resets
   and an expired/missing receipt cannot save. Refresh, review and acknowledge to
   continue; do not repeatedly press Save against the same failed receipt.
4. Old unbound or different-case ratings have a notice. Review them explicitly
   before saving a new revision; old labels were not silently upgraded.
5. Agreement shows unmatched ratings and abstentions separately. Historical
   protocols and unverified cases do not count. When a judge retried at 6,000
   characters, use Short and review the actual case before expecting a pair.
6. With reader access disabled or redacted-content consent unavailable, evidence
   review explains the requirement and Save remains unavailable. Native consent
   boundaries were not replaced by a browser or agent shortcut.
7. Show export: the result includes rating versions and evidence fingerprints,
   but no evidence text. Treat the export as sensitive if moving it elsewhere.

## Remaining boundaries

- A receipt binds the issued evidence case; it does not prove a person viewed it,
  human identity, independence, task completion or model correctness. Direct agent
  annotations remain declared labels. No metric is activated or promoted by this
  checkpoint.
- Recorded model identity is not always an immutable weight digest/revision.
  Representative human calibration, admitted model provenance and owner review
  remain separate acceptance work. Matching bounded evidence is not a claim that
  the whole transcript was read or that the chosen sample is representative.
- The unchanged privacy scanner still reports one prohibited old synthetic
  SQLite fixture under `test-results/browser-workflow-e3rix2kz`. Its automated
  removal was previously blocked. No alternate removal, exclusion or scanner
  bypass was attempted. This prevents privacy sign-off, not independent repairs.
- No real provider session, owner configuration or provider credential was read;
  no external inference was requested and no GPU model was loaded. No normal
  owner-app restart, native approval click-through or real peer delivery is
  claimed. No commit or push was performed.
- Cleanup checks found zero model-runtime processes and no listeners on the
  owned HTTP-test ports or the usual owner-app port. The pre-existing loopback
  synthetic development server was left alone. The owned browser tab was closed
  and its viewport restored. Production assets are rebuilt, but the normal
  owner application was not started against private configuration or sessions.
- Durable Agent conversations, truthful per-turn telemetry, richer changed-file
  summaries, packaged-launcher acceptance, symlink-capable validation, remote
  delivery reconciliation and the existing authorization-gated product decisions
  remain open in the whole-application ledger.

Next bounded development candidate: Agent turn telemetry and changed-file
summaries from actual generation/tool receipts. Keep unavailable values unknown,
keep the conversation memory-only, and do not add durable content retention or
skip protected-action approval as part of that work.
