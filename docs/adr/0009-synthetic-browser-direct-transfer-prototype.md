# ADR 0009: Synthetic browser direct-transfer prototype

- Status: Accepted synthetic development prototype; real-user transport is not accepted
- Date: 2026-08-18
- Protocol version: `browser-direct-file.v1`
- Extends: ADR 0006's direct-only decision and ADR 0008's explicit transport gap

## Decision

Accept an isolated browser exercise that moves generated fixture bytes between
two in-page `RTCPeerConnection` peers over one ordered `RTCDataChannel`. The lab
exists to test direct-transport mechanics without weakening the identity,
content, persistence, or deployment gates that keep real social transport
closed.

The lab is available only when all of these conditions hold:

1. Vite is running in development mode;
2. the exact build opt-in is
   `VITE_SOCIAL_DIRECT_FILE_PROTOTYPE=webrtc-datachannel-synthetic-v0`;
3. the validated social snapshot is the registered fictional synthetic fixture;
4. the person explicitly acknowledges the generated-byte boundary in the UI;
5. both peer capabilities were issued by the module-private synthetic principal
   registry; and
6. the recipient separately consents and the owner separately approves that
   transfer.

The exact string is an operator/developer safety gate, not an authentication
secret. The synthetic principal registry is a fixture mechanism, not an
identity provider. The normal synthetic preview leaves the lab absent, and
`local_real` cannot mount it even if the environment string is present. No
backend route, listener, social adapter, generated API, remote service, or
dependency is added.

## Payload boundary

The exported transfer-session factory accepts no `File`, `Blob`, picker,
filename, filesystem path, URL, message attachment, analyzer content, or
caller-supplied byte array.
Its only source is a one-shot, module-registered `SyntheticByteSource` whose
bytes are generated deterministically in memory. The public source object
exposes only fixture kind, fictional status, and byte length. Low-level
integrity helpers accept byte arrays for deterministic tests and verification;
they do not open a channel, persist data, or form a runtime composition port.

The source is capped at 8 MiB because WebCrypto exposes no portable streaming
SHA-256 API. Source and recipient buffers are best-effort overwritten when the
session terminates, but JavaScript garbage collection and browser-internal
copies mean this is not a secure-erasure claim. The constraint is safe because
the bytes are generated fixtures, never user content.

No byte, name, path, candidate, or session description is written to
`localStorage`, `sessionStorage`, IndexedDB, Cache Storage, a URL, the DOM, a
log, a trace, an HTTP request, a WebSocket, or the social SQLite control plane.
Playwright tracing, screenshots, and video are disabled for the direct-transfer
exercise.

## Integrity and framing

The immutable manifest mirrors the Python direct-file integrity contract:

- whole-file SHA-256 via browser WebCrypto;
- 256 KiB chunk SHA-256 commitments;
- the same domain-separated leaf and node encodings, unsigned 64-bit big-endian
  positions/sizes, and odd-node duplication used by
  `application/file_sharing/integrity.py`;
- sorted, contiguous, full-coverage ranges aligned to manifest chunks, with at
  most 32 ranges; and
- an 8 MiB file ceiling.

Data-channel frames have a fixed 16-byte header and at most 12 KiB of payload.
They are ordered and must begin at the recipient's exact next expected offset;
duplicate, overlapping, skipped, oversized, malformed, or trailing frames fail
closed. The sender observes `bufferedAmount` high/low water marks and a bounded
wait before queuing more frames. The negotiated SCTP maximum message size must
fit the fixed frame.

Completion is recipient-authoritative. It requires the declared byte count,
every chunk digest, the whole-file digest, and the domain-separated Merkle root
to match. The receipt contains only identifiers, sizes, digests, and the honest
no-relay/no-cloud/no-recall flags; it does not expose received bytes.

## Consent, approval, pause, expiry, and revocation

Recipient consent must precede a per-transfer owner approval. Both capabilities
are revalidated immediately before negotiation. Expiry and owner revocation are
checked before negotiation, before and after a pause, around backpressure waits,
and immediately before every new frame. JavaScript run-to-completion means a
revocation cannot interleave between the final check and the synchronous
`RTCDataChannel.send()` call.

Pause stops new frames from being queued; frames already buffered in the browser
may settle. Resume rechecks expiry and revocation before another frame. A
revoked or expired transfer closes both peers and rejects resume/start. Bytes a
recipient already received cannot be recalled, and no UI or receipt claims
otherwise.

## Direct-only connectivity and signaling

Each peer is constructed with `iceServers: []`, an empty ICE candidate pool,
and no injectable RTC configuration. This exercises a host/direct-candidate
policy, while the implemented non-portable signaling confines the lab to two
peers in one browser realm. It is not a LAN or Internet transport. It uses no
STUN, TURN, relay, VPS proxy, cloud mailbox, or cloud-byte fallback. A defensive
relay-candidate check rejects the transfer and closes both peers if a `typ
relay` candidate ever appears.

Offer and answer descriptions are held only in a module-private `WeakMap` behind
content-free, non-portable ephemeral envelope objects. The receiving in-process
fixture peer consumes each object capability once; a cloned or serialized copy
is unregistered and fails closed. The envelope's public shape exposes only
protocol, direction, transfer identifier, fictional status, and non-persistence
facts—never SDP or candidates.

This is intentionally not cross-device signaling. A real peer cannot copy the
envelope to another browser, and no signaling server exists. If connection or
channel establishment fails, the outcome is `unreachable_no_relay` with an
honest `symmetric_nat_or_cgnat_or_firewall_possible` hint. The browser cannot
prove which topology caused the failure, and the UI does not pretend it can.

## Cryptography truth

WebRTC supplies its standard DTLS/SCTP transport protection. This repository
adds no encryption primitive, key exchange, identity binding, ratchet, MLS,
forward-secrecy claim, recovery scheme, or custom crypto. Because the fixture
offer/answer exchange does not authenticate a real person or device, the lab is
not accepted as product E2EE and does not remove the E2EE, device-proof, identity,
signaling, direct-connectivity, or multi-device readiness gaps.

## Verification

Synthetic unit and browser tests require:

- exact opt-in and registered-capability rejection of forged principals;
- a cross-language golden Merkle vector;
- canonical manifest/range and corruption rejection;
- consent-before-approval, expiry, and revocation fences;
- no persistence/logging/cloud/file-picker primitives in implementation files;
- a real two-peer Chromium transfer with pause/resume and full integrity;
- unchanged local/session/IndexedDB state and no remote resource request during
  that transfer;
- `browser_webrtc_unavailable` when the peer API is absent, distinct from
  `unreachable_no_relay` when direct establishment fails; and
- no local-real composition or production readiness claim.

## Required real-transport work

A superseding ADR is required before accepting any real file or cross-device
peer. It must provide a real identity provider and device proof, authenticated
and abuse-resistant signaling, an approved direct-path/STUN policy, explicit IP
metadata disclosure, replay binding, real file access with immutable-source
checks, streaming integrity, receiver quarantine and safe naming, storage and
quota policy, cancellation/orphan cleanup, multi-browser/platform evidence,
and independent network and cryptographic assessment. TURN, relay, and cloud
byte fallback remain separate product decisions and are not implied by this
prototype.
