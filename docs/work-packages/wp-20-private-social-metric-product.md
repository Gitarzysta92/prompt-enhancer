# WP-20: evidence-complete metrics and private social collaboration

Status: **S0 delivered; a bounded S1 local-metadata runtime and an isolated
synthetic browser data-channel prototype are implemented. Real device pairing,
authenticated encrypted payload delivery, direct user-file bytes, and S2-S4
remain blocked until their preceding security and infrastructure gates pass.**

## Outcome

Prompt Enhancer should turn its metric workspace into a useful decision surface
and add private collaboration without turning local analytics into workplace
surveillance or a cloud content store.

The product target has two connected, but deliberately separated, systems:

1. a local analyzer that owns sessions, semantic units, objective receipts,
   metrics, explanations, and plots; and
2. an optional social control plane that owns identity, relationships,
   permissions, signalling, and encrypted delivery metadata.

Message plaintext, file bytes, transcript content, embeddings, and analyzer
explanations never enter the social control plane. The systems do not share a
database or a content-level join key.

## What “every metric works” means

Every one of the twenty canonical metrics must produce one inspectable outcome:

- an observed value backed by authoritative evidence;
- an explicitly experimental estimate that passed its reviewed coverage gate;
- a right-censored `pending` state with bounds;
- `not_applicable` because no opportunity existed;
- `unknown` with a concrete evidence-readiness reason;
- `abstained` because coverage or selective-risk gates failed; or
- `execution_error` with a fixed, content-free repair reason.

It does **not** mean inventing a numeric value. The five objective-receipt
contracts cannot be resolved from prose or model agreement. They become numeric
only when a documented adapter supplies the required requirement, hypothesis,
claim, verification-task, and objective-check references.

The dashboard and compact overlay must consume the same immutable publication,
contract fingerprint, value state, guidance receipt, and evidence authority.
Unknown, pending, not-applicable, abstained, and failed metrics are never plotted
as zero.

## Metric user-value contract

Each selected metric provides exactly two concise, reviewed sentences:

1. what the metric measures, its denominator, direction, evidence authority,
   window, and current state; and
2. the smallest actionable next step plus a concrete way to verify whether it
   improved.

Advice cannot name a weak factor unless a measured per-factor receipt proves it.
An uncalibrated model contribution is labelled experimental and cannot be
presented as measured evidence. Client wording is valid only for the exact
server registry version and contract-set fingerprint; a mismatch renders a
definitions-out-of-date state.

The server-issued guidance receipt is authoritative for state class, basis,
audience, templates, counts, and measured focus factors. The client translates
reviewed template identities into localized sentences; it does not independently
choose whether a value means retain or improve. A contract mismatch clears the
old snapshot and guidance in both surfaces and asks the user to update the
client—it is not displayed as a network reconnection problem.

Pending metrics show their censoring bounds in text and accessible state labels.
The workspace header separately reports how many of the five objective metrics
the current adapter can measure. When an adapter cannot supply the required
receipt family, advice states that limitation rather than directing the user to
perform an impossible action.

## Social capability target

The private social foundation is invite-only and finite-recipient. It includes
closed contracts and authorization for:

- friend request, accept, decline, remove, and block;
- direct and explicitly invited group conversations;
- organization, team, channel, membership, and role changes;
- message send, edit, local deletion, peer-deletion request, reactions, thread
  replies, per-device read position, and coarse opt-in presence;
- device enrolment, verification, rotation, and revocation;
- abuse reports that reveal only user-selected evidence; and
- owner-hosted, recipient-allowlisted direct file transfer.

There are no public or automatically discoverable channels in this tranche.
Block takes precedence over every grant, and a blocked or unknown identity must
not create an enumeration oracle. Presence is never derived from analyzer
activity and is never exported to a team metric surface.

S0 exposes closed readiness gaps for missing production identity, separated
social persistence, forward secrecy, direct reachability, abuse reporting,
retention approval, and control-plane metadata visibility. The direct-file
contract separately records relay as absent by design. A bounded S1 adapter may
remove only `social_store_not_separated` after it verifies its own independent
`social.sqlite3`; every other gap stays visible. These are visible states, not
generic errors or hidden controls.

## Direct file-sharing contract

File bytes travel directly from the owner’s device to an approved recipient.
The central plane may coordinate identity and signalling, but it does not relay
or store file bytes in this tranche.

Consequences are stated rather than hidden:

- the owner must be online;
- same-LAN or directly reachable peers work without an account through explicit
  out-of-band pairing;
- symmetric NAT or CGNAT may make a transfer unavailable because no TURN relay
  is used;
- an offline recipient leaves a bounded, expiring request on the sender only;
- revocation stops a transfer that has not completed, but bytes already received
  cannot be recalled; and
- “delete for everyone” is a peer request, never a guarantee.

Each transfer has a server-issued identifier, immutable manifest, explicit
recipient list, expiry, byte-size ceiling, sender and receiver quotas, whole-file
and chunk integrity, resumable ranges, per-transfer approval, and fixed state
reasons. Receiver paths are generated inside a separate quarantine root;
absolute paths, traversal, symlinks, reparse points, executable bits, and
implicit opening are rejected.

The state vocabulary distinguishes at least: owner offline, recipient offline
with expiring sender queue, unreachable without relay, revoked before
completion, quota exceeded, invalid manifest, integrity failure, and quarantine
path rejection. Local erasure, peer-deletion request, per-device deletion
acknowledgement, and unacknowledged remote copies are distinct states.

## Cryptography boundary

The repository must not invent a ratchet or group-encryption protocol.

- Device identity uses a reviewed signature implementation and stores private
  keys in the operating-system credential store.
- Conversation and transfer content uses reviewed authenticated encryption with
  associated data binding the schema, conversation or transfer identity,
  sender device, recipient set, and sequence.
- Forward secrecy is claimed only if a reviewed Signal/MLS-compatible library is
  integrated and independently tested. Otherwise readiness states say it is
  unavailable.
- The central plane inevitably observes relationship, timing, size-class, and
  availability metadata. End-to-end encryption does not hide that fact.
- Server-side plaintext moderation is incompatible with end-to-end encryption.
  Reporting therefore requires an explicit sender-verifiable reporting design
  or remains unavailable.

## Storage and deployment boundary

| Data | Owner | Development persistence | Production requirement |
|---|---|---|---|
| Analyzer receipts and metrics | local analyzer | existing local SQLite | unchanged local-first boundary |
| Social graph and delivery metadata | social service | separate development store/database | tenant-bound PostgreSQL with RLS, audit, backup, and deletion controls |
| Device private keys | device | OS credential store adapter | platform keystore and recovery policy |
| Message plaintext | sender/recipient devices | never in control plane | reviewed E2EE client storage and retention |
| File bytes | sender/recipient devices | separate quarantine/share root | direct transport; no server byte store |
| Signalling | optional control plane | fail-closed contract/adapter; no candidate exchange | authenticated TLS service with replay and abuse controls |

The existing analyzer database is not extended with social tables. Development
social persistence has its own schema version and migration ledger. Production
remote listening, identity, mail delivery, billing, relay service, and provider
LLM execution remain disabled until separately approved and provisioned.

An expired subscription cannot remove access to local analysis, local metric
history, local social history, received files, export, or deletion. Entitlements
may gate remote synchronization or hosted analysis only; local capability must
remain usable offline and cannot depend on a billing request from the analyzer
process.

## Privacy and compliance check

This is product/compliance triage, not legal advice. Before employer-controlled
or production deployment, the owner must establish controller/processor roles,
lawful bases, notices, retention, export, rectification and deletion workflows,
incident response, subprocessor terms, and whether a DPIA is required.

The design follows the security and privacy-by-design direction in
[GDPR Articles 25, 32, and 35](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679).
The Polish supervisory authority’s
[Article 35(4) DPIA list](https://www.edpb.europa.eu/sites/default/files/decisions/pl-dpia-list_monitor_polski.pdf)
specifically makes systematic monitoring of employee-tool activity a review
concern. Therefore:

- individual manager visibility is default-deny, explicit, expiring, and
  audited;
- no developer ranking, leaderboard, inferred intelligence, personality, or
  emotion score is permitted;
- team aggregates require stable cohorts, disclosure control, and protection
  against differencing;
- chat, relationship, presence, and transfer metadata are sensitive personal
  data even when payloads are encrypted; and
- public/open channels are excluded. If they are added later, the applicability
  of the [Digital Services Act](https://eur-lex.europa.eu/eli/reg/2022/2065/oj),
  electronic-communications rules, and content-governance obligations must be
  reassessed.

## Delivery stages

### S0 — contract and truth foundation

- Bind metric help and team copy to the canonical contract fingerprint.
- Wire live V2 lifecycle and objective projections into canonical publication.
- Add social contracts, policy, ports, readiness gaps, and in-memory adapters.
- Keep every new route and transport default-off.
- Record direct-only transfer, metadata, deletion, and cryptography decisions in
  an ADR.

S0 acceptance requires:

- exact all-twenty guidance-receipt rendering and full/compact parity tests;
- a dedicated definitions-out-of-date state;
- objective-adapter readiness counts and non-imperative missing-capability copy;
- pending-bound rendering;
- social state machines, fixed readiness gaps, default-deny policy, server-issued
  identifiers, and in-memory synthetic adapters;
- block-over-friend/team/organization/manager-grant attack tests; and
- at S0 acceptance, no social HTTP route, key material, message content, or file
  byte path; a later route must prove and document each prerequisite before it
  supersedes that boundary.

### S1 — local private collaboration

- Implemented in the bounded metadata runtime: a separate local social database
  and migration ledger; transactional friendship, block, invite-only
  conversation, envelope-metadata, reaction, read-state, deletion-receipt,
  file-offer/grant/transfer-metadata, audit, and revocation persistence.
- Implemented as an explicitly composed development surface: readiness plus a
  narrow relationship/account-deletion API. It is default-off, loopback-only,
  and exposes mutations only when an application injects both the social
  service and a verified-principal resolver. The analyzer browser session and
  local API token do not establish a social identity.
- Not implemented for real users: out-of-band device pairing, a real identity
  provider, reviewed E2EE, plaintext/ciphertext-byte history,
  same-LAN/direct-address signaling, STUN, direct user-file transport, or a
  usable export workflow. An exact-opt-in development lab may exercise two
  in-page browser peers using generated fixture bytes only; it does not close
  any of these readiness gaps.
- No public discovery, relay, cloud file bytes, or presence inference.

### S2 — production control-plane prerequisites

- Standard identity provider, tenant-bound credentials, device verification,
  TLS, PostgreSQL/RLS, encrypted backups, audit, rate limits, abuse handling,
  key rotation, erasure and recovery.
- Official billing and hosted-analysis services remain separate later phases.

### S3 — direct file transport

- Authenticated negotiation, direct reachability check, encrypted chunk stream,
  resumability, integrity, quarantine, revocation race handling, and no-orphan
  process/network tests.
- Implemented only as a synthetic precursor: browser-standard WebRTC data
  channels, generated in-memory bytes, ephemeral same-realm signaling,
  SHA-256/Merkle integrity, bounded frames/ranges, consent, approval,
  pause/resume, expiry, and revocation fences. The lab is development-only,
  requires an exact build and user opt-in, and is unavailable to `local_real`.
- Still required for S3: real identity and device proof, authenticated
  cross-device signaling, direct-path policy including reviewed STUN use, real
  file selection/reading, receiver quarantine and storage, and independent
  network/cryptographic review. No TURN, relay, or cloud-byte fallback is added.

### S4 — higher-metadata collaboration

- Expose reactions, threads, per-device read state, and coarse presence through
  usable collaboration only after S1-S3 security and retention gates pass. S1
  may durably preserve their content-free metadata contracts without exposing
  payload or presence operations over HTTP.

## Release gates

1. Every metric key, state, definition, explanation, and plot is identical in
   dashboard and compact overlay for the same canonical snapshot.
2. Objective metrics reject conversational or model-only evidence.
3. A client/server contract fingerprint mismatch never renders stale guidance.
4. Friendship, block, membership, role, device, and expiry authorization is
   evaluated from server-resolved facts on every item.
5. Revocation wins races with message reads and in-progress transfers.
6. Cross-tenant, enumeration, replay, cursor-regression, traversal, symlink,
   quota, oversize, malformed-manifest, and duplicate-chunk attacks fail closed.
7. Synthetic PII/secret/content canaries are absent from analyzer storage,
   social metadata, audit events, logs, crash output, OpenAPI examples, and
   generated clients.
8. Full frontend, backend, build, direct-network synthetic tests, accessibility,
   reduced-motion, forced-colors, privacy scan, and schema drift gates pass.
9. Production readiness remains false until identity, durable storage, key
   management, legal review, backups, monitoring, and incident response are
   independently proven.
10. Local analysis, history, export, deletion, received files, and explicitly
    local collaboration remain available when offline or when a paid entitlement
    lapses.

## Product-value rule

SOTA is not the number of models, metrics, plots, chat controls, or Discord-like
features. A feature creates value only when it helps a user make a safer or more
effective decision and provides evidence that the decision worked. Every new
surface must therefore expose provenance, uncertainty, permission, next action,
and a verification path while keeping unavailable evidence honest.
