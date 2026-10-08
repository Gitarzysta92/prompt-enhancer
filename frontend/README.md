# Prompt Enhancer dashboard

This directory contains the browser-first React dashboard for the synthetic
task-discovery milestone. It follows the dependency direction from ADR 0001:

```text
app -> features -> entities -> shared
```

The default development composition uses only fictional, content-free fixture
data. The HTTP transport accepts relative `/v1/...` paths, sends credentials only
to the same origin, and has no API-token or browser-storage facility. In a
production build, the integrated loopback server issues an ephemeral HttpOnly
cookie and an in-memory CSRF token. Page load and session bootstrap never access
a provider; indexing, selected summary-label enrichment, and analysis remain
separate explicit actions. Manual display labels modify only Prompt Enhancer's
local catalog and never rename provider tasks. A desktop host can later implement
the narrow platform adapter without changing features.

## Development

```console
npm install
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
```

The production build is emitted into the ignored Python package resource
directory at `src/prompt_enhancer/_resources/dashboard`. The local `serve`
command and a staged wheel resolve that directory through the same package
resource abstraction; runtime code never walks repository parents.

The dev and preview servers bind to `127.0.0.1`. No analytics, CDN, remote font,
image, or model request is included.

The packaged local server should send this production Content Security Policy:

```text
default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self';
object-src 'none'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'
```

It is intentionally a server header rather than a static meta element because
the local server owns the browser security boundary. The production build emits
its stylesheet as a local asset; the current coverage visualization uses one
bounded inline width style, which is why `style-src` permits inline styles.

## API contract

`src/shared/api/generated/openapi.ts` is a checked-in snapshot of the content-free
WP-03 DTOs. After exporting the backend schema to `../docs/openapi.json`, run
`npm run generate:api` and review the diff. Runtime API documentation remains
disabled; generation is a build-time operation.

## Team control-plane port

`src/shared/api/teamControlPlane.ts` is a typed frontend port for a future
canonical team data service. The loopback backend implements a default-off,
development-only readiness route, but it does not implement the aggregate or
member methods. Honest adapters keep those boundaries separate:

- `createSyntheticTeamControlPlanePort()` serves a fictional, content-free
  cohort in the synthetic development preview (every payload is stamped
  `origin: "synthetic_fixture"`);
- `createLocalLoopbackTeamControlPlanePort()` may display the exact backend
  readiness blockers but never carries the privileged control-plane credential
  and always rejects aggregate/member reads;
- `createUnavailableTeamControlPlanePort()` is the fallback when the optional
  route is not mounted and reports team, organization, sync, and billing absent.

`createTeamControlPlanePortForRuntime(mode)` binds each runtime data mode to
its adapter; a remote adapter must not be added until one exists with an
approval-bound transport. The port publishes aggregates only: cohort size,
missingness, comparability, freshness, and uncertainty per metric, with
measured typed rows and experimental model ranges kept as separate entries.
Individual member rows exist only behind an explicit visibility grant with
audit facts, are ordered by pseudonymous identifier, and never carry a total,
rank, or score. The `/team` route (Me · Team · Organization), the `/tasks/flow`
board and timeline, and the compact "Team context" drawer in the floating
overlay consume the port; per-metric two-sentence explainers reuse the
metric-help-v2 registry and decision guidance in both full and compact modes.
Task Flow traverses each content-free index in bounded pages and labels the
result non-atomic; a cap or duplicate across pages is shown as incomplete.

## Social hub port

`src/shared/api/socialHub.ts` is a typed frontend port for a future social
coordination service (friends, requests, direct messages, group channels,
presence, role permissions, reactions, threads, read state, and metadata-only
direct file offers). Nothing in the shipped backend implements it. Honest
adapters keep the boundary explicit:

- `createSyntheticSocialHubPort()` serves a fictional, content-free fixture in
  the synthetic development preview (every payload is stamped
  `origin: "synthetic_fixture"` and `fictional: true`, and the `/social` route
  shows an unmistakable "Fictional synthetic demo" notice);
- `createUnavailableSocialHubPort()` is the local loopback adapter: the
  capability reports `unavailable`, snapshot reads reject, and the page shows
  exactly zero friends, requests, conversations, messages, and file offers.

`composeSocialHubPort(mode, injected)` mirrors the team control-plane runtime
composition: a fixture (or a relabelled fixture) can never cross into
`local_real`. UI actions in the demo mutate only local React state; nothing is
delivered, stored durably, synced, or encrypted, and no such claim is made. The
file-sharing panel is a UI simulation with metadata only (display name, size,
media type, fictional digest): no file picker, path, or bytes exist, recipients
must consent, transfers pause/resume/expire/revoke, and the copy states that a
real exchange would move bytes directly between devices without the
coordination service storing a copy.

Truth boundaries the port and UI carry explicitly (validated by
`socialSnapshotIsValid`, `socialHub.test.ts`, `socialHubModel.test.ts`,
`SocialHubPage.test.tsx`, `socialPayloadBoundary.test.ts`, and
`e2e/social-hub.spec.ts`):

- groups are `access: "invite_only"`, `discoverable: false`, with a finite
  bounded member list; there is no public directory, join link, or channel
  browser;
- presence is an explicit opt-in (`SocialPresenceSignal`: `sharing`,
  coarse `level`, `source: "self_declared_opt_in"`); "not shared" is its own
  rendered state, never offline, and presence is labelled as separate from
  analyzer activity (`presence.derived_from_analyzer_activity: false`);
- the application never auto-inserts analyzer sessions, prompts, metrics, or
  explanations into a chat or file-share payload (`payload_policy.analyzer_content:
  "never_inserted"`; the social feature imports no analyzer module and no
  analyzer surface has a share-to-chat control). This boundary does not inspect
  or classify text a person chooses to type;
- file transfer is direct only (`path: "direct_only"`, `relay: "none"`,
  `turn: "none"`): a symmetric NAT or CGNAT on either side is the explicit
  `direct_path_unavailable` offer state; the owner must be online; a
  sender-offline offer can still be created and waits as `queued_on_sender`
  on the sender's device with bounded expiry (`queue_location:
  "sender_device"`), never on a server; revoke stops future bytes but cannot
  recall bytes already downloaded (`revoke_recalls_downloaded_bytes: false`);
- end-to-end encryption is `not_implemented`, and even a future encrypted
  service's coordination plane would observe `relationship`, `timing`,
  `availability`, and `size_class` metadata (`coordination_plane_observes`);
  file bytes never traverse or rest on it;
- no export/delete-my-data controls exist because no server-side data exists
  (`data_controls`), and `local_real` fails closed with exactly zero
  relationships, messages, and offers and presence not shared.

Shared UI primitives used across the Social hub, Task Flow, and the metric
cards live in `src/shared/ui` (`Dialog`, `Disclosure`, `Tabs`, `FactList`,
`EmptyState`, `FictionalNotice`, `ProgressMeter`, `Avatar`, `LiveRegion`) with
their forced-colors and reduced-motion rules in `src/shared/ui/primitives.css`.
Every metric knowledge/explainer card now carries a "Context and evidence"
section (Scope · Contributors · Model · Evidence) in both full and compact
modes; the personal workspace labels the Me scope and team surfaces label the
cohort scope, and absent facts render as "Not reported", never as zero.
