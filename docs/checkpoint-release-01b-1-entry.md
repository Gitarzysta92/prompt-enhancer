# Checkpoint Release-01b.1 entry: signed update discovery and staging

Date: 2026-09-02

Status: signed-discovery sub-slice complete; download/staging paused by owner

Handoff: [Release-01b.1a handoff](checkpoint-release-01b-1a-handoff.md)

This checkpoint adds the application-shell update control and stages a newer
immutable installer without mutating the running app. A branch push is not an
update authority: only a versioned release manifest and installer that pass the
packaged trust policy may become owner-visible as available.

## Frozen trust and privacy contract

| Boundary | Required behavior | Forbidden behavior |
| --- | --- | --- |
| Release trigger | A separately promoted, versioned release after quality gates | Executing or pulling arbitrary `master` branch contents |
| Check authority | Explicit same-origin browser gesture or an owner-enabled schedule | Hidden background egress in the default composition |
| Disclosure | One bounded request carrying no account, install, device, hardware, metric, usage or content identifier | Telemetry, cookies, referrers, prompts, sessions or machine fingerprinting |
| Manifest | Bounded strict JSON, trusted signature, channel, version, minimum version, publication/expiry, artifact size and SHA-256 | Unknown keys, redirects, downgrade, replay, expired or unsigned metadata |
| Artifact | Exact HTTPS origin, size and digest plus trusted Windows package signature | Executing partial, mismatched, foreign-publisher or mutable bytes |
| Staging | Hardened application-private directory, resumable content-free ledger and atomic final name | Writing into the install directory or changing the running app |
| UI | Sidebar and compact-navigation states for unconfigured, current, available, staging, staged and fixed failures | A disabled control with no explanation or a success claim without evidence |

## Acceptance matrix

1. Two synthetic releases exercise newer/current/downgrade/channel/replay and
   expiry boundaries with no network service.
2. Tampered manifest, signature, artifact bytes, size and package publisher fail
   closed.
3. Interrupted staging reconciles from exact ledger and byte evidence; cancel,
   retry and concurrent checks cannot cross operation revisions.
4. GET status never performs egress. A check requires an authenticated,
   same-origin UI gesture and the default unconfigured build opens no socket.
5. Responsive, keyboard, screen-reader, contrast and reduced-motion tests cover
   every update state in both sidebar and compact navigation.
6. Complete backend/frontend/API/build/privacy gates remain green.

Release-01b.2 owns reviewed installation, exact-tree shutdown, relaunch, health
verification and rollback. Release-01b.1 must not implement a privileged
self-updater.
