# ADR 0008: Durable local social metadata and principal-gated loopback composition

- Status: Accepted local development runtime; production communication is not accepted
- Date: 2026-08-18
- Contract version: `social-foundation-v1`
- Storage schema: `social_schema_migrations` version 2
- Supersedes: ADR 0006 only where it described the social runtime as volatile
  and route-free

## Decision

Accept an explicitly composed, one-device development runtime for durable social
and direct-file **metadata**. It uses a dedicated `social.sqlite3`, an independent
migration ledger, typed repositories, and one shared transaction boundary for a
social operation and its audit/revocation writes. It does not initialize from
the default application bootstrap and it never attaches or joins the analyzer
database.

Accept two optional loopback HTTP router factories:

1. an authenticated, read-only readiness ledger; and
2. narrow friend-request, friend-decision, friend-removal, block, unblock,
   direct-conversation-create, and own-account-metadata-deletion mutations.

The application mounts neither router unless the exact development flag is
enabled. Mutation routes additionally require an injected `SocialService` and
an injected `SocialPrincipalResolver`. Every request supplies a bounded opaque
social credential to that resolver. A browser cookie or analyzer API token may
satisfy the separate local API authentication boundary, while body and URL
identifiers may identify only an operation target; none can establish the social
principal. Missing, malformed, failing, or wrong-typed resolver results fail
closed.

This decision does not accept message, presence, file-offer, file-transfer, or
file-byte HTTP routes. It does not start a listener or permit a non-loopback
binding.

## Persistent boundary

Schema version 2 stores only validated control-plane metadata:

- tenant-scoped accounts, organization/team/channel memberships and roles;
- devices, key algorithm names, key versions, and public-key fingerprints, but
  no private or public key bytes;
- friend requests, friendships, blocks, private channels, invite-only direct or
  private-group conversations, and durable conversation-closure fences;
- message envelope identifiers, operation/revision/key version, ciphertext size
  and digest, reactions, read positions, tombstones, and peer-deletion
  acknowledgements, but no plaintext or ciphertext bytes;
- coarse, relationship-specific presence records that are not derived from the
  analyzer;
- immutable file-manifest digests/chunk layout, recipient grants, consent,
  availability, transfer ranges/states/approvals, and revocation metadata, but
  no file bytes, name, path, address, or network candidate; and
- content-free social and file audit events plus honest local deletion receipts.

The schema uses strict tables, constrained identifiers/states, foreign keys, and
an explicit forbidden-column-name check in adversarial tests. Social identifiers
remain independent from analyzer session, project, prompt, metric, and account
identifiers. `ATTACH` and a shared join key are not part of the adapter.

Version 1 was an unused placeholder boundary. The migration ledger records it
and version 2 replaces those placeholder tables; this is not a promise to import
data from an independently deployed or populated version-1 product.

## Transaction and restart behavior

One `SqliteSocialConnection` owns one SQLite connection and a re-entrant process
lock. Service operations use `BEGIN IMMEDIATE`; nested repository calls share
that transaction, and exceptions roll back state, audit, deletion, and
revocation writes together. The connection enables foreign keys, disables
trusted schema execution, uses WAL, and requests `synchronous=FULL`.

The adapter is restart-safe for committed local metadata and rejects a database
whose migration ledger is newer than the build. It validates the dedicated file
name and rejects symlink/reparse components before opening. This is a
single-process, single-connection development design—not multi-device sync,
distributed consensus, a production backup system, or a Windows ACL guarantee.

Conversation closure keeps a durable fence even when active membership rows are
removed. Peer-authored envelope metadata can remain for deletion honesty, while
late or replayed writes to the closed conversation fail. Device/account
revocation timestamps and current authorization facts are evaluated at the
service boundary before an operation proceeds.

## Deletion and revocation truth

Account deletion removes the subject's local relationship, membership,
presence, reaction, and read metadata as defined by the deletion service; it
tombstones locally held sender metadata and persists a typed deletion receipt in
the same transaction. Equal receipt replay is idempotent and a changed replay is
rejected. Per-device peer-deletion requests and acknowledgements are distinct.

The receipt deliberately reports `local_metadata_erased=false`: minimum account
tombstones, device revocation fences, peer-authored metadata, and security audit
records may remain. Neither a local receipt nor peer acknowledgement guarantees
recall of plaintext, screenshots, exports, backups, or bytes already received.
Manifest/grant revocation stops unfinished local transfer state; it cannot erase
a recipient's completed copy.

## Readiness truth

An application composing this adapter obtains its receipt from
`SqliteSocialFoundation.readiness()`, which rechecks the dedicated filename,
current migration ledger, and absence of attached databases before delegating to
the lower-level readiness constructor. This removes exactly
`social_store_not_separated`. Production readiness stays false, and the fixed
gaps for identity, device proof, reviewed E2EE, forward secrecy, authenticated
signaling, direct connectivity, multi-device sync, backup/recovery, abuse
handling, retention, metadata visibility, legal-controller determination, and
workplace DPIA review remain visible.

The readiness object is a capability receipt, not authority to mount routes. A
host application must still provide the development flag and, for mutations,
the service plus verified-principal resolver.

## Explicitly unavailable

This runtime does not provide:

- a real identity provider, device enrollment proof, proof-of-possession
  session, credential issuance/revocation service, or production principal
  resolver;
- E2EE, authenticated encryption, Double Ratchet, MLS, forward secrecy,
  post-compromise security, key storage, key rotation, or recovery;
- message/file ciphertext bytes or plaintext persistence and delivery;
- signaling, ICE exchange, STUN, direct reachability checks, TURN, relay, remote
  sockets, or multi-device synchronization;
- owner-file reads, resumable byte streaming, receiver quarantine, integrity
  verification over received bytes, or malware scanning; or
- production PostgreSQL/RLS, encrypted backup/restore, retention execution,
  export delivery, abuse response, rate limiting, operational monitoring, or
  incident response.

Direct-file semantics remain direct-only and no-relay. A later transport must
surface owner/recipient offline and symmetric-NAT/CGNAT failures rather than
silently adding a VPS or cloud byte path.

## Fitness functions

- default application construction does not create or open `social.sqlite3`;
- the development flag alone mounts no social route;
- readiness needs an injected receipt, and mutations need an injected service
  and verified-principal resolver;
- local analyzer authentication never impersonates a social account;
- blocked and unknown targets remain in the same denial class;
- cross-tenant, stale/revoked-device, replay, revision-regression,
  conversation-closure, expiry, quota, and revocation-race attacks fail closed;
- a failed multi-repository operation leaves no partial state or audit row;
- reopening the adapter reconstructs committed typed contracts and receipts;
- persistent schema contains no transcript, message/file bytes, file names or
  paths, network candidates, credentials, secrets, key bytes, or analyzer join
  identifiers; and
- all fixtures remain synthetic and pass privacy/secret scanning.

## Revisit conditions

A superseding ADR is required before adding a production resolver, remote
binding, message/file payload route, reviewed cryptographic protocol, signaling,
STUN, direct byte transport, relay, multi-device sync, or production social
store. Each such change needs its own threat model, operational owner, migration
and rollback plan, retention/deletion behavior, and adversarial evidence.
