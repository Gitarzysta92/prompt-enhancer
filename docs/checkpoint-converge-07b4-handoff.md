# Converge-07b.4 handoff — staged package review, not installation

Status: **automated slice complete.** This checkpoint connects the existing
read-only MSIX preflight to the staged-update review action. It does not add
installation, apply, restart, relaunch, rollback, or a configured public
release.

Date: 2026-09-05
Scope: authenticated review of the fixed private `artifact.staged` candidate,
with a content-free owner-visible verified/rejected result only.

## What this slice closes

- Package-owned update trust schema v3 requires explicit artifact URL templates
  and an explicit `MsixPackageExpectation`: package name, publisher,
  architecture, and signer-leaf SHA-256 pin. Versions 1 and 2 retain their
  prior behavior and do not gain package-review capability.
- Composition creates a review verifier only after the full v3 policy validates
  and an already-private staging root admits the real staging store. Invalid,
  duplicate, incomplete, or missing-root policy fails closed before staging
  preparation. No real publisher, key, origin, or release configuration is
  supplied by this repository.
- `StagedPackageReview` verifies only the fixed `artifact.staged` leaf from
  `FileUpdateStagingStore`. The normal preflight entry point remains
  `.msix`-only; no caller-selected filesystem path, HTTP flag, copying,
  extraction, or extension-based rename was added.
- Each review revalidates its supplied models, recovers and reparses the exact
  staged signed envelope before and after preflight, and does not cache a
  positive result. Orphan partials, missing/mismatched envelopes, hardlinks,
  digest/size changes, accessor uncertainty, path-swap observations, and
  post-native ledger/package mutations reject without cleanup.
- The production composition uses the existing cache-only
  `WindowsMsixSigner` boundary. An unavailable or indeterminate Windows SIP
  result remains signature-unverifiable; synthetic fake signers are test-only.
- The coordinator exposes a fenced review action with `checking`, `verified`,
  and `rejected` package-review states. A non-staged configured surface reports
  `not_staged`; an unconfigured surface remains `not_configured`. A verified
  result is intentionally not durable: restoring a stage requires a new review.
  `can_apply` remains false and there is no apply/install route.
- Review-worker shutdown joins its owned worker within a bound and refuses late
  results; an active synchronous metadata fetch still reports its established
  content-free shutdown uncertainty rather than claiming cleanup.

## Focused evidence

All evidence in this slice used temporary fictional packages, identities,
keys, manifests, and local test state. No network release fetch, native package
smoke, provider data, model, installation, relaunch, application restart, or
PC restart occurred.

- `tests/test_staged_package_review.py` covers positive fixed-leaf review,
  normal `.msix`-only entry-point refusal of `artifact.staged`, changed/missing
  envelopes, tamper, hardlink, accessor, ledger, package/path, and orphan
  partial races without mutation by the adapter.
- `tests/test_application_update_07b4_acceptance.py` provides two full local
  HTTP/TestClient flows with real Ed25519 verification, real private staging and
  replay stores, and fake native signer evidence: browser cookie/CSRF
  check→stage→poll→review→poll; no status read invokes the signer; the restored
  stage is reviewable again as `not_checked`; and a tampered staged artifact is
  refused. Both focused acceptance cases pass.
- The root-owned 20-file backend gate is **357 passed, 2 Windows
  symlink-fixture skips, and 1 intentionally deselected
  `native_unsigned_container_fail_closed_smoke`** in 63.01 seconds. This total
  includes the two HTTP acceptance tests; it is not additive with focused runs.
- The full frontend gate is **2,810 passed across 190 files** in 432.74 seconds.
  The final updater-focused component, decoder, and transport selection is
  **244 passed across 3 files**; it is an overlapping subset and is not summed.
- The final headless Chromium fixture is **6/6 passed** in 9.4 seconds. It
  covers the 360/1440 review flow, 320×360 refusal, unconfigured, retry, and
  unmount behavior; its temporary loopback listener on port 4173 was released,
  and the application listener on port 8765 was untouched.
- Final build, API, and byte-exact schema checks are green. The prior schema
  mismatch was resolved by using the repository `uv run python` interpreter
  rather than a global interpreter. The existing over-500 kB build chunk warning
  remains. Root reran privacy scanning and whitespace checks after this
  documentation update; both are green.

## Explicit non-claims and next gate

No production host, publisher identity, owner-signed positive native MSIX
acceptance, installer handoff, installation, application relaunch, packaged-app
restart recovery claim, real-install recovery claim, or rollback implementation
is present. Recovery of the fixed staged file is synthetic-tested; that is not
evidence of packaged application restart or real installation recovery. No PC
reboot was performed. The active remote-session restriction remains in force.
The next C07 work is separately authorized owner-native publisher/signing and
installer/relaunch/rollback evidence; no release claim is valid before those
steps.
