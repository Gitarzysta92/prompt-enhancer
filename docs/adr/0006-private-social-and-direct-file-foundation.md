# ADR 0006: Invite-only social metadata and direct-only owner-hosted files

- Status: Accepted S0 foundation; durability and narrow local-route portions are
  superseded by [ADR 0008](0008-durable-local-social-metadata-runtime.md);
  production communication is not accepted
- Date: 2026-08-18
- Contract versions: `social-foundation-v1`, `direct-file-sharing-v1`
- Scope: social graph, private conversation metadata, E2EE ports, coarse
  presence, deletion evidence, immutable file manifests, consent, direct
  connectivity and owner-local file access

## Decision boundary

This ADR accepts typed contracts, default-deny policy, development-only
in-memory adapters, a dedicated future SQLite schema boundary and adversarial
tests. It does **not** accept or implement a production messenger, Discord
parity, public communities, account discovery, an identity provider,
cryptography, signaling, ICE candidate exchange, a remote listener, NAT relay,
cloud file storage or a multi-device sync protocol.

No route or listener was mounted by this S0 slice. The local analyzer was
unchanged. The default cryptography and signaling adapters fail closed. ADR 0008
later accepts a default-off, loopback-only development composition for readiness
and narrow relationship mutations; it does not accept a listener, identity
provider, payload route, cryptography, or transport.

## Threat model

The contracts assume that another tenant, an unauthorized organization member,
a removed channel member, a blocked account, a stale/revoked device, a replaying
client, or a recipient presenting a forged range/integrity receipt may be
hostile. They also assume file names and paths may contain traversal, alternate
data stream, device-name, hard-link, symlink or Windows reparse tricks.

The contracts do not protect an unlocked, fully compromised endpoint. A peer
that legitimately receives plaintext can copy it. A compromised owner can send
different bytes after creating a manifest, although the recipient must reject
completion unless every chunk and the whole-file digest match. Traffic analysis
also remains possible: the control plane necessarily observes relationship,
membership, timing, ciphertext-size, file-size, grant and transfer-state
metadata. Pseudonymous identifiers are personal data, not anonymity.

## Social identity and isolation

Social identifiers use a separate random `soc_` namespace. Analytics HMAC
pseudonyms cannot be inserted into these contracts and no social module imports
the analyzer database, metrics, sessions or project identities. The planned
local persistence boundary owns `social.sqlite3` and its independent
`social_schema_migrations` ledger; it never joins or attaches
`metrics.sqlite3`. This S0 slice used a volatile in-memory runtime. ADR 0008
accepts one-device durable metadata persistence, while durable multi-device
synchronization remains explicitly unavailable.

A production identity provider must resolve an authenticated account/device
principal. Callers never gain authority by placing an organization, account or
device in a request. Device references name Ed25519 signing and X25519 agreement
keys by version and fingerprint only; private keys and public key bytes are not
persisted in the control-plane contracts.

Block policy precedes target existence, friendship, organization role, team
membership or conversation permission. A blocked identifier and an unknown
identifier return the same closed reason. Revoked accounts, memberships and
devices deny every operation, including reads. Friendship acceptance and block,
grant consent and revocation, and transfer state changes occur inside one
adapter transaction in development; a durable adapter must preserve those
atomic boundaries.

Direct conversations require a current friendship on every content operation;
removing a friend closes that capability immediately. Message edits and deletes
must remain bound to the account that created the message identifier.

## Messaging and encryption

Only finite-recipient, invite-only direct conversations and private groups are
modeled. Public/discoverable channels are not part of the contract. Persisted
message data is limited to envelope/message identifiers, sender device,
operation/revision, key version, algorithm identifier, ciphertext size and
ciphertext digest. Message plaintext, ciphertext bytes, attachments, display
text and arbitrary emoji are absent.

The code does not invent a Double Ratchet, MLS, key backup or recovery scheme.
`LocalMessageCryptoPort` is the only encryption/authentication boundary. Its
default implementation raises `crypto_adapter_unavailable`. Production work
requires a reviewed library and protocol for Ed25519, X25519, authenticated
encryption, replay binding, membership-driven key rotation, forward secrecy,
post-compromise security and multi-device recovery. Naming algorithms is not an
implementation or security claim.

Presence is explicit per friendship, coarse (`available`, `away`, `offline`),
expires within five minutes and is never derived from analyzer activity or
published as team-manager telemetry. Workplace use, especially manager access,
remains default-deny pending governance and a jurisdiction-specific DPIA review.

## Deletion and entitlement honesty

Local account deletion erases relationship/presence rows and replaces locally
held sender metadata with content-free tombstones. A peer deletion request and
each device acknowledgement are separate states. Neither acknowledgement nor a
server receipt proves that a peer erased a screenshot, export, backup or
previously decrypted plaintext.

The local deletion receipt does not claim that every identifier vanished. A
minimal deleted-account tombstone, device-revocation fences and security audit
events remain subject to an approved retention policy; the receipt exposes
those retained categories and reports `local_metadata_erased=false`. Deleting
one account never tombstones peer-authored messages or peer reaction/read state.

Manifest/grant revocation stops the owner from serving future bytes and cancels
unfinished local transfer records. It cannot recall bytes already delivered.
An entitlement lapse must not silently erase local analyzer history, social
history, received files or export rights. Billing gates remote service; it is
not a data-retention primitive.

## File transfer decision

The control plane stores an immutable manifest with whole-file SHA-256, ordered
chunk SHA-256 values and a domain-separated Merkle root. It stores explicit
per-recipient offers, consent, expiry, revocation, owner availability, requested
byte ranges, per-transfer owner approval and content-free audit events. It never
stores file bytes, names, filesystem paths, IP addresses or ICE candidates.

File bytes are **direct only**. There is no TURN, generic relay, VPS byte proxy
or cloud fallback. Authenticated signaling is still required to introduce two
authorized devices and exchange ephemeral candidates. If a direct route cannot
be established—for example under symmetric NAT or CGNAT—the transfer fails with
an explicit `symmetric_nat_or_cgnat`/`unreachable_no_relay` state. Offline
recipient work can be queued only on the sender device with an expiry; the VPS
does not become a mailbox for bytes.

The owner must make the manifest available and approve every transfer. The
recipient selects sorted, non-overlapping, bounded ranges and cannot complete a
transfer until all expected chunk digests, byte size and whole-file digest
match. The requester device is revalidated after signaling, so a revocation race
cannot promote the transfer to `direct_ready`. Quotas bound active manifests,
recipients, manifest size and concurrent transfers.

## Owner-local quarantine

`QuarantinedLocalFileReader` is read-only and is not exposed through HTTP. It
requires an explicitly selected file already under a dedicated local directory,
accepts one conservative portable basename, rejects absolute/drive/UNC/device/
ADS/traversal spellings, rejects multi-link files, rechecks symlink and reparse
components on each open, opens read-only with `O_NOFOLLOW` where available,
validates size, hashes the entire file on registration and bounds each range
read to one chunk. It stores the absolute path only in process-local adapter
state.

The recipient still performs final integrity verification. Windows ACLs,
platform file identity, malware scanning, quarantine copying and code-signing
belong to a later reviewed platform adapter and installer.

## Privacy and compliance readiness

This foundation is intended only for private, finite-recipient communication.
Before processing real people, the operator must establish controller/processor
roles, purposes, lawful bases where applicable, metadata notices, retention and
backup expiry, access/export/deletion procedures, incident response and
confidentiality/integrity/resilience testing. The readiness contracts therefore
include `legal_controller_undetermined`, `retention_policy_unapproved` and
`metadata_visible_to_control_plane`. These are engineering gates, not legal
conclusions.

Abuse reporting and response are also unfinished. End-to-end encryption limits
server visibility but does not remove the need for user-controlled reporting,
blocking, rate limits and lawful incident handling.

## Required production work

Production remains false until a superseding ADR accepts, implements and tests:

1. an identity provider, proof-of-possession sessions, device enrollment and
   immediate revocation;
2. a reviewed E2EE/multi-device protocol and library, secure keystore, forward
   secrecy, rotation, recovery and independent cryptographic assessment;
3. an authenticated signaling service with anti-abuse controls, while keeping
   candidate values ephemeral and maintaining the direct-only/no-relay promise;
4. durable social adapters with migrations, backup/restore, export, deletion,
   retention and concurrency tests independent from the analyzer store;
5. platform quarantine, malware scanning, signed updates and installer ACLs;
6. privacy/security governance, DPIA assessment where applicable, incident
   response, rate limiting and operational monitoring that does not collect
   message/file content.

## Fitness functions

- analytics identifiers, message/file content, file names/paths, credentials,
  private keys and network candidates cannot enter persistent contracts;
- blocked and unknown targets share the same observable denial;
- revoked account/membership/device state denies reads and writes;
- message envelope replay, stale key version and revision regression fail;
- manifests reject gaps, overlap, duplicate chunks and a mismatched Merkle root;
- grants require explicit recipient consent and expire/revoke atomically;
- ranges are bounded and resumable, owner approval is per transfer, and quotas
  apply before a transfer consumes a slot;
- missing signaling, symmetric NAT/CGNAT and owner offline states never fall
  back to TURN, cloud storage or a generic proxy;
- a transfer cannot complete on a size, chunk or whole-file digest mismatch;
- revocation/deletion receipts never claim recall of peer-held plaintext;
- the default application exposes no social/file route and starts no listener.
