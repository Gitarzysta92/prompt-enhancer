# ADR 0005: Content-free team control plane with a replaceable storage port

- Status: Accepted foundation (P3a); the product decision it prepares is not accepted
- Date: 2026-08-17
- Contract version: `control-plane-v2`
- Scope: tenancy and identity contracts, device key binding, publication
  envelopes, delta synchronization, cohort disclosure, audit evidence, and the
  storage boundary between development and production
- Supersedes: nothing. It refines the future-team paragraphs of
  [ADR 0001](0001-modular-monolith-hexagonal-metric-graph.md).

## What this ADR does and does not accept

Accepted: the **shape** of a team control plane, expressed as contracts, ports,
an authorization policy, and an in-memory development adapter, so the hard
questions (isolation, revocation, deletion, disclosure) are answered in testable
code before any of it is deployed.

Not accepted, not implemented, and not scheduled by this ADR:

- operating a hosted service, a remote listener, or any transport off one machine;
- a production identity provider, credential issuance, or session management;
- billing, payments, or metering; the development entitlement is only an
  explicit, default-off synchronization gate and is not proof of purchase;
- turning team sharing on for real people, which
  [the campaign ledger](../real-metrics-campaign-ledger.md) still gates behind
  P2 completion, owner approval, and a separate governance review.

The composed plane reports `production_ready = false` as a `Literal[False]`, and
lists its gaps explicitly. That is a contract, not a status message: making it
true requires a superseding ADR.

## Decision

1. **The unit of exchange is a signed, allowlisted metric-snapshot envelope.**
   The allowlist is a closed enumeration of ten numeric keys with fixed units.
   There is no free-text field anywhere in the envelope. This sharply limits
   the semantic surface, but it is not a claim that covert signalling is
   impossible: key selection, bounded values, and timing remain low-bandwidth
   channels. Private coaching, affect, friction, and model-written judgements
   are excluded from the allowlist by construction, consistent with
   [the metrics catalog](../metrics-catalog.md), which already forbids exporting
   C-tier private signals to team surfaces.
2. **Missing stays missing.** A measurement carries `value = null` with an
   observation count of zero. Nothing in the plane converts an unknown into a
   zero. Internal candidate aggregates retain missingness explicitly, while the
   public aggregate use case currently publishes no counts or values at all.
3. **Default deny.** `authorize()` is a pure function over facts the service
   resolved from the directory. Every path that does not match an explicit
   allow clause returns `default_deny`. A caller cannot widen its own authority
   because a caller's claims never reach the decision — only resolved
   membership, role, team, device state, and client scopes do.
4. **Managerial access is a grant, not a role.** A manager reading somebody
   else's individual snapshot needs an unexpired `ManagerAccessGrant` naming
   that subject or that team, and its use writes a `manager_access_used` audit
   row. An administrator can revoke the grant atomically; later reads deny it,
   while deletion notices already owed to that manager's client/device remain
   deliverable. A grant naming one person does not unlock a cohort aggregate.
5. **Devices are the publication identity.** A snapshot is accepted only if it
   is signed by an active device enrolled to the publishing member, issued after
   that device was enrolled, and within a five-minute clock skew. Organization,
   subject, client, and device do not appear in the request envelope; the server
   stamps them from the credential-bound principal and reservation. Revoking a
   device destroys its verification material and revokes its credentials, not
   only a flag.
6. **Synchronization has recipient-local streams and bound checkpoints.**
   Accepted writes have an internal tenant-source order, but a pull exposes a
   separate contiguous sequence for the authenticated client/device. Denied
   source rows advance only a hidden scan position, so they cannot create
   visible gaps. Until a local offer is acknowledged it is redelivered, making
   delivery honestly at-least-once. A different client/device cannot
   acknowledge it. A delivery ledger records each recipient-specific opaque
   snapshot handle so deletion reaches that recipient even after access expires.
   The PostgreSQL target materializes a durable recipient-bound payload before
   first offer; retries read that projection without rejoining the source or
   rechecking the now-expired manager grant.
7. **Idempotency is fenced and identifiers are server-issued.** A producer first
   reserves an opaque envelope identifier bound to its credential, then signs
   the envelope containing it. A producer may hold one reservation for at most
   five minutes, and repeated issue calls return that same candidate; this
   bounds only reserve-without-consumption prefix grinding. A successful push
   consumes the slot, so a later issue call returns a fresh ID, and the current
   development recipient payload carries the accepted envelope ID. Therefore
   the reservation bound is not a claim that all covert channels are removed.
   The same envelope identifier with the
   same digest is a no-op reporting the original handle; the same identifier
   with different content is a conflict, because one of the two is forged or
   corrupted. Reservations carry the subject's current deletion epoch and all
   old reservations are invalidated in the deletion transaction; a future
   signed timestamp cannot revive a pre-erasure reservation. The retained
   consumed fence also keeps its owner binding, so a wrong-owner probe is
   indistinguishable from an unknown ID. No issuance, acceptance, replay,
   expiry, or rejection audit stores a caller-visible reservation/envelope ID;
   audit correlation is generated only when the event is appended.
8. **Public cohorts fail closed.** Minimum size and fixed buckets do not prevent
   cross-team or longitudinal differencing. Until stable privacy cohorts,
   overlap rules, and a persisted atomic query budget are separately reviewed
   and implemented, the team-aggregate use case returns only
   `disclosure_control_unavailable`, with no cohort count, eligible count,
   contributor count, or value. The arithmetic helper is not a release claim.
9. **Storage is a port set, not a database.** Narrow tenant-scoped ports are
   implemented today by
   an in-memory development adapter and later by PostgreSQL with row-level
   security, per [the production schema design](../control-plane-postgres-rls.md).
   Every port method takes its organization identifier explicitly, so tenant
   scoping is part of the call signature rather than an ambient value a caller
   can forget.

## Why REST deltas plus later SSE, not continuous WebSockets

Team synchronization here is a low-rate, batch-shaped exchange: a device
publishes a period summary, other devices catch up when they next run. Its
correctness requirements are resumability, exactly-once acceptance, ordered
deletion, and per-item authorization.

- **Resume is the hard part, and a cursor solves it.** A request-response delta
  endpoint makes the client's position an explicit, storable integer. A
  connection-oriented protocol has to rebuild that position after every network
  change, laptop sleep, and process restart — which means implementing the same
  cursor anyway, plus the connection lifecycle.
- **Authorization is per item, not per connection.** Membership, device state,
  and manager grants change while a socket is open. Re-authorizing each item on
  each request is straightforward; keeping a long-lived socket's authorization
  fresh requires invalidation plumbing that is easy to get subtly wrong.
- **Idempotent retries need no session state.** A repeated push is defined by
  its envelope identifier and digest. A message-oriented socket has to define
  and store its own de-duplication and acknowledgement semantics.
- **Ordinary infrastructure understands it.** Timeouts, retries, proxies, rate
  limits, and audit logging all work on request-response without special cases.
- **Latency is not a requirement.** Nothing here is interactive. When "the
  dashboard should update sooner" becomes a real complaint, the cheap answer is
  a one-way Server-Sent Events notification that carries *no data* and only says
  "there is something after sequence N" — after which the client performs the
  same authenticated, authorized, cursored pull. That keeps exactly one code
  path for data and authorization, and adds a hint channel that can fail without
  affecting correctness.
- WebSockets remain the right answer for bidirectional, low-latency,
  high-frequency exchange. Adopting them for this workload would buy latency we
  do not need and cost us session-bound authorization, connection-scoped
  ordering, and a second delivery path to secure.

## Why development SQLite/in-memory is not production PostgreSQL

The local analyzer keeps SQLite as its system of record and this ADR does not
change that. The control plane's development adapter is in memory, which is
even further from a production store. The distance is deliberate and must not
be closed by "just pointing it at a file":

| Requirement | Development adapter | Production PostgreSQL |
|---|---|---|
| Tenant isolation | Dictionary keys include the tenant, so a wrong-tenant lookup misses | `ROW LEVEL SECURITY` policies on every table, enforced by the database even if a query forgets its filter |
| Concurrent writers | One process, multiple threads serialized by one shared re-entrant lock | MVCC, per-tenant sequence allocation, and explicit conflict handling |
| Durability | None; state dies with the process | WAL, backups, and point-in-time recovery |
| Deletion | Removes source objects and queues recipient-scoped opaque tombstones under one shared lock | Transactional source erasure plus durable recipient payload projections, a delivery ledger, and recipient-local tombstones, with retention and backup expiry as separate policy problems |
| Identity | An opaque random development credential is bound out of band to one tenant/member/client/device | An identity provider issues verifiable, expiring credentials |
| Encryption | None | At rest and in transit, with key management |

SQLite is an excellent local system of record and a poor multi-tenant one: no
row-level security, one writer, and no server-side authorization boundary. A
multi-tenant deployment where a bug in one query returns another company's rows
is not a bug class we should accept, and RLS is the mechanism that makes it a
database invariant rather than a code-review promise.

## Alternatives considered

**Extending the local SQLite analyzer with tenant columns.** Rejected. It would
put multi-tenant data in the same store as one person's private local analysis,
weaken the existing deletion story, and provide no enforcement boundary. The
control plane deliberately shares no table, no migration, and no module with the
analyzer; it does not import `database.py` at all.

**A blockchain, distributed ledger, or content-addressed gossip network.**
Rejected. The requirements are tenant isolation, revocation, and *deletion*. An
append-only replicated ledger makes erasure structurally difficult, adds
consensus and key-management burden, and solves a trust problem — mutually
distrusting parties without an operator — that a team's own control plane does
not have. Signed envelopes plus an ordered per-tenant log give the tamper
evidence that is actually wanted, and remain deletable.

**Reusing a personal Codex or Claude CLI as the team backend.** Rejected on
every axis. Those are single-user, credential-bearing, interactive tools with
unstable internal formats. Using one as a multi-user server would mean sharing
one person's provider credentials, running arbitrary agent capability on behalf
of others, and depending on formats their vendors explicitly decline to
stabilize. Provider authentication stays inside the provider's own tool.

**Symmetric shared-secret device authentication in production.** Rejected as an
endpoint, accepted as a development stand-in. `dev-hmac-sha256` proves tamper
detection and key binding on one machine, but anyone who can verify can also
sign, so it is not a public-key identity. Ed25519 is named in the contract and
deliberately left unregistered: composing it fails closed with
`unsupported_algorithm` rather than silently degrading to the symmetric scheme.

**Free-form metric keys with a redactor.** Rejected. Redaction after the fact
has repeatedly proven weaker than never accepting the field. An enumeration
costs a contract change to extend, which is the correct price.

## Consequences

Benefits:

- the isolation, revocation, deletion, and disclosure rules exist as executable
  tests before any deployment decision;
- the local, offline product is untouched: with the setting off there is no
  route, no service, and no import from the analyzer;
- a PostgreSQL adapter is a port implementation, not a rewrite;
- the honest gap list travels with the code instead of living in a slide.

Costs:

- the allowlist must be extended deliberately, one reviewed key at a time;
- an in-memory adapter exercises thread serialization but cannot exercise
  durability, process failure, MVCC, or RLS, so a production adapter-level test
  suite will be needed;
- development credentials have no identity provider, expiry, rotation, or
  proof of possession. The routes remain loopback-only, token-gated, and off by
  default, and the readiness contract reports this gap.

## Fitness functions

1. every envelope field rejects prose, and extra fields are refused;
2. every action denies by default without a scope and across tenants;
3. a revoked membership or device loses publication and read access;
4. a replayed identifier with new content is a conflict, while pre-erasure
   reservations are invalid after deletion regardless of signed timestamp;
5. acknowledgements never move backwards or cross a client/device boundary,
   denied source rows create no visible gaps, and unacknowledged offers may
   redeliver by design;
6. a tampered envelope fails verification and takes no sequence number;
7. every public cohort request is suppressed without counts or values until
   reviewed differencing controls exist;
8. deletion keeps an owner-bound consumed fence and produces distinct opaque
   tombstones for every client/device in the prior-delivery ledger, even after
   a grant is revoked;
9. reserve-without-consumption prefix grinding yields one expiring candidate per
   producer; push-then-reissue yields a fresh ID, while no caller-visible
   reservation ID or attacker canary reaches audit;
10. PostgreSQL design checks require retry from a recipient projection after
    grant revocation and full active client/device/membership/scope/entitlement
    gates on the recipient checkpoint;
11. the default composed application exposes no control-plane route.

## Revisit and falsification triggers

Create a superseding ADR if any of these occurs:

- a real deployment is proposed, which requires an identity provider, Ed25519,
  the PostgreSQL adapter, and a governance review to be accepted together;
- the allowlist needs a non-numeric field, which would materially widen the
  minimized signalling surface;
- a public cohort release is proposed, which requires stable privacy cohorts,
  overlap and longitudinal rules, and a persisted atomic query budget;
- polling proves too slow in practice, which adds an SSE notification channel
  but must not add a second data path;
- pgvector or any embedding storage is proposed. It is deliberately absent: no
  reviewed use case exists, embeddings are sensitive derived data, and nothing
  in a content-free numeric plane needs vector search.
