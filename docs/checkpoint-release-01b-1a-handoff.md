# Checkpoint Release-01b.1a handoff: signed update discovery

Date: 2026-09-02

Status: automated discovery foundation complete; larger goal paused by owner

Entry contract: [Release-01b.1 entry](checkpoint-release-01b-1-entry.md)

## Outcome

Prompt Enhancer now has a content-free software-update control in the desktop
sidebar and compact navigation. A package-owned trust file can activate an
explicit signed-manifest check. Merely opening the app or reading update status
cannot make a network request.

A push to `master` is deliberately **not** an update. Source branches are not
executable distribution authority. A future release pipeline must promote a
version, build and sign the Windows package, publish immutable artifacts and a
signed manifest, and only then make that version discoverable.

## Implemented boundary

- strict `application-update-status.v1` lifecycle and an exact frontend parser;
- authenticated status plus same-origin, CSRF-bound explicit check routes;
- Ed25519 verification over the exact bounded manifest bytes;
- current/newer/downgrade, channel, time, key, tamper, replay and conflicting
  release-identity checks;
- one exact HTTPS manifest URL per packaged channel, with proxies, credentials,
  redirects, alternate ports, compression and unbounded responses refused;
- a bounded, strict package-owned trust configuration containing only public
  manifest URLs and Ed25519 public keys;
- fail-closed unconfigured composition when that trust file is missing or
  invalid; and
- truthful responsive UI for loading, checking, current, available,
  unconfigured and failure states.

The current development checkout intentionally has no production trust file.
After reload it therefore shows **Updates not connected** and performs no
external request. A discovered version is also non-actionable until the native
download/installer handoff exists; the UI does not disguise another check as an
install action.

## Validation evidence

- updater/configuration/HTTP/distribution/bootstrap focused backend coverage
  completed without a functional failure;
- the broad backend run completed with 5,274 passed and nine expected
  Windows symlink skips; its sole failure was the privacy scanner flagging four
  synthetic signing-fixture variable names;
- those names were corrected without weakening the scanner, after which the
  privacy gate and 37 affected updater/privacy tests passed;
- the broad frontend run completed with 2,748 passed and three load-sensitive
  timeouts in pre-existing App/Agent navigation tests; all three exact cases
  passed unchanged in isolation;
- the updater parser/control suite passed 14/14;
- production TypeScript/Vite build passed with 574 modules;
- generated OpenAPI drift, Python compile, dependency lock, privacy scan and
  patch-whitespace gates passed.

No model was loaded and no application helper was launched by this checkpoint.

## Explicitly not implemented

- no production update origin, signing identity, public key or Windows package;
- no artifact download, private staging ledger, progress, cancel or restart
  recovery;
- no MSIX/App Installer handoff, install, app shutdown, relaunch or rollback;
- no automatic check schedule; and
- no merge/push/release workflow that can update an installed copy.

## Resume point

When the owner resumes the goal, continue Release-01b.1 with deterministic
Windows packaging and artifact staging only after choosing the public release
origin and establishing owner-controlled signing identity. Release-01b.2 then
owns reviewed install, exact-tree shutdown, relaunch, health verification and
rollback.
