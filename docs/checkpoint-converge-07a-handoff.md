# Converge-07a handoff — signed update staging foundation

Status: **C07a automated foundation validated/complete.** Converge-07
remains partial and this handoff does not claim a usable production self-update,
packaged release completion or owner acceptance.

Date: 2026-09-05
Scope: content-free signed-manifest status, bounded artifact staging and
truthful recovery UI; synthetic evidence only.

## Outcome

- The v2 update status carries a process instance fence, monotonic lifecycle
  revision, bounded release facts and explicit action capabilities.
- Explicit check, stage, cancel and retry mutations require the current
  instance/revision fence. Staging reports bounded progress and hash/size
  completion; cancellation remains authoritative while cleanup is pending.
- The sidebar/drawer keeps the default unconfigured state network-silent,
  exposes only enabled actions, and distinguishes checking, downloading,
  stopping, failed recovery and downloaded bytes. Downloaded bytes are not
  described as publisher-verified or installable.
- The UI rejects stale transport responses, resets old status on transport
  replacement, and fails closed on unavailable or uncertain recovery.

## Owning evidence ledger

- Final owning frontend source gate (11 files: app, updater parser and HTTP
  transport): **355/355 passed**.
- Final updater/full-shell browser gate: **16/16 passed** at the owning widths.
- Rebuilt production frontend plus disposable real loopback browser gate:
  **16/16 passed**, with `startup_ready=true`, `runtime_cleanup_confirmed=true`,
  `listener_released=true`, `temporary_state_removed=true` and
  `model_runtimes_remaining=0`.
- Combined backend updater/API/configuration/coordinator/staging/negative/
  source/manifest-source/distribution/runtime/bootstrap gate: **174 passed**,
  with one Windows symlink fixture skip.
- Schema/privacy/configuration gate: **16 passed**; the repaired stale
  byte-exact case independently reran **1 passed**. `npm run check:api` passed.
- Root privacy scan and `git diff --check` passed. These are owning totals;
  overlapping focused subsets are not added.
- Repairs covered ledger binding, false-STAGED repeated checks, staged
  supersede/replay, worker cleanup reporting, and sidebar scroll/focus.

Updater/browser checks use synthetic fixtures and temporary local state with
content-free receipts. The integration gates used loopback network only;
no external network, provider, real model, VRAM, private data, installer,
commit or push was used. The app on port 8765 was not reloaded or installed.

## Explicit boundaries

- Durable high-water evidence exists only for a recovered staged release;
  metadata-only checks are not durably replay-persisted.
- The production Windows DACL adapter is missing; injected test hardeners are
  not Windows evidence.
- Publisher/native installer/MSIX handoff, relaunch, rollback, public release
  URLs/trust/signing, and the complete packaged north-star journey remain open.
- No production self-update is usable yet; pushing to `master` does not deploy
  an update.

## Owner click-later items

1. Review the signed release identity, public HTTPS distribution and trust/key
   custody before enabling any production channel.
2. Run the packaged Windows DACL, publisher, installer, relaunch and rollback
   acceptance on an owner-controlled machine.
3. Verify restart recovery and the durable staged-release high-water boundary.
4. Complete the packaged north-star journey and final visual review.

## Next safe checkpoint: Converge-07b

Implement and validate the Windows private-path hardener, signed package
publisher/installer handoff, restart/relaunch ownership and rollback recovery;
then rerun the owning loopback, packaged and owner evidence gates. Keep
metadata-only checks explicitly non-durable until replay persistence is proven.

## Workflow and privacy boundary

Root reads and reviews the code and independently validates; Terra handles
harder implementation, while Luna handles bounded implementation, tests and
docs. Existing supervised delegation, privacy, synthetic-fixture and
no-commit/push rules remain in force.
