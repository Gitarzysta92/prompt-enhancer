# Production PostgreSQL and RLS design for the control plane

Status: design only. This repository has no PostgreSQL adapter, migration,
connection, hosted service, or production identity provider. The executable
adapter is loopback-only, in memory, default-off, and reports
`production_ready = false`.

This document is a target for a future adapter, not evidence that the target has
been implemented. Every example identifier is an opaque 64-character value;
the schema contains no prompt, transcript, source snippet, path, account label,
or other free text.

## 1. Trust boundary

The application obtains all four claims from one verified credential and
rechecks active membership, client, device, scopes, and entitlement before it
opens a database transaction:

```sql
SET LOCAL app.organization_id = '<opaque-id>';
SET LOCAL app.user_id         = '<opaque-id>';
SET LOCAL app.client_id       = '<opaque-id>';
SET LOCAL app.device_id       = '<opaque-id>';
```

The request body cannot set or override these claims. The application role is
not a table owner and has neither `BYPASSRLS` nor permission to change roles.
The migration owner is separate. Claims use `SET LOCAL`, so a pooled connection
cannot retain them after commit or rollback. A missing claim matches no row.

All opaque identifiers use a bounded domain:

```sql
CREATE DOMAIN opaque_id AS char(64)
    CHECK (VALUE ~ '^[0-9a-f]{64}$');
```

## 2. Tenant-coherent keys

Every relationship includes `organization_id`. A globally unique-looking ID is
not accepted as proof of tenant ownership, and no single-column foreign key can
pair a row from tenant A with a row from tenant B.

```sql
CREATE TABLE organizations (
    organization_id opaque_id PRIMARY KEY,
    created_at timestamptz NOT NULL
);

CREATE TABLE teams (
    organization_id opaque_id NOT NULL
        REFERENCES organizations ON DELETE CASCADE,
    team_id opaque_id NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, team_id)
);

CREATE TABLE memberships (
    organization_id opaque_id NOT NULL
        REFERENCES organizations ON DELETE CASCADE,
    user_id opaque_id NOT NULL,
    membership_id opaque_id NOT NULL,
    role text NOT NULL CHECK (role IN ('owner','admin','manager','member')),
    state text NOT NULL CHECK (state IN ('active','suspended','revoked')),
    created_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (organization_id, user_id),
    UNIQUE (organization_id, membership_id),
    CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
);

CREATE TABLE team_memberships (
    organization_id opaque_id NOT NULL,
    team_id opaque_id NOT NULL,
    user_id opaque_id NOT NULL,
    state text NOT NULL CHECK (state IN ('active','revoked')),
    joined_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (organization_id, team_id, user_id),
    FOREIGN KEY (organization_id, team_id)
        REFERENCES teams ON DELETE CASCADE,
    FOREIGN KEY (organization_id, user_id)
        REFERENCES memberships ON DELETE CASCADE,
    CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
);

CREATE TABLE devices (
    organization_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    user_id opaque_id NOT NULL,
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    key_fingerprint opaque_id NOT NULL,
    public_key bytea,
    state text NOT NULL CHECK (state IN ('active','revoked')),
    registered_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (organization_id, device_id),
    UNIQUE (organization_id, user_id, device_id),
    UNIQUE (organization_id, key_fingerprint),
    FOREIGN KEY (organization_id, user_id)
        REFERENCES memberships ON DELETE RESTRICT,
    CHECK ((state = 'revoked') = (revoked_at IS NOT NULL)),
    CHECK ((state = 'active') = (public_key IS NOT NULL))
);

CREATE TABLE api_clients (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    user_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    state text NOT NULL CHECK (state IN ('active','revoked')),
    created_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (organization_id, client_id),
    UNIQUE (organization_id, client_id, device_id),
    UNIQUE (organization_id, user_id, client_id, device_id),
    FOREIGN KEY (organization_id, user_id, device_id)
        REFERENCES devices (organization_id, user_id, device_id)
        ON DELETE RESTRICT,
    CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
);

CREATE TABLE api_client_scopes (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    scope text NOT NULL CHECK (scope IN (
        'snapshots:push','snapshots:pull','aggregates:read',
        'audit:read','deletion:request','directory:administer')),
    PRIMARY KEY (organization_id, client_id, scope),
    FOREIGN KEY (organization_id, client_id)
        REFERENCES api_clients ON DELETE CASCADE
);

CREATE TABLE credential_bindings (
    credential_digest opaque_id PRIMARY KEY,
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    revoked_at timestamptz,
    FOREIGN KEY (organization_id, client_id, device_id)
        REFERENCES api_clients (organization_id, client_id, device_id)
        ON DELETE RESTRICT
);

CREATE TABLE entitlements (
    organization_id opaque_id PRIMARY KEY
        REFERENCES organizations ON DELETE CASCADE,
    tier text NOT NULL CHECK (tier IN ('local_only','team_preview')),
    seat_limit integer CHECK (seat_limit >= 1), -- NULL is unknown
    remote_sync_enabled boolean NOT NULL DEFAULT false,
    evaluated_at timestamptz NOT NULL
);
```

The production key algorithm is only Ed25519. Revocation updates the device to
`revoked`, sets `revoked_at`, clears `public_key`, revokes every bound API
client, and sets every bound credential's `revoked_at` in one transaction. The
checks make active-key and revoked-key states coherent. Physical deletion is
deferred until every required deletion notification is durably queued.

## 3. Reservations, versions, and replay fences

The server issues envelope IDs. A client cannot select an ID, a schema version,
or a producer version merely by placing a string in a request.

```sql
CREATE TABLE subject_deletion_epochs (
    organization_id opaque_id NOT NULL,
    subject_user_id opaque_id NOT NULL,
    deletion_epoch bigint NOT NULL DEFAULT 0 CHECK (deletion_epoch >= 0),
    deleted_through timestamptz,
    PRIMARY KEY (organization_id, subject_user_id),
    FOREIGN KEY (organization_id, subject_user_id)
        REFERENCES memberships ON DELETE RESTRICT
);

CREATE TABLE envelope_reservations (
    organization_id opaque_id NOT NULL,
    envelope_id opaque_id NOT NULL,
    subject_user_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    subject_epoch bigint NOT NULL CHECK (subject_epoch >= 0),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, envelope_id),
    UNIQUE (organization_id, subject_user_id, client_id, device_id),
    UNIQUE (
        organization_id, envelope_id, subject_user_id, client_id, device_id
    ),
    FOREIGN KEY (organization_id, subject_user_id, client_id, device_id)
        REFERENCES api_clients (
             organization_id, user_id, client_id, device_id
        ) ON DELETE RESTRICT,
    CHECK (expires_at > issued_at),
    CHECK (expires_at <= issued_at + interval '5 minutes')
);

CREATE TABLE measurement_definition_versions (
    version_id text PRIMARY KEY
        CHECK (version_id ~ '^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$')
);

CREATE TABLE producer_adapter_versions (
    version_id text PRIMARY KEY
        CHECK (version_id ~ '^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$')
);

CREATE TABLE snapshot_metric_allowlist (
    metric_key text PRIMARY KEY
        CHECK (metric_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    unit text NOT NULL,
    maximum_value numeric(20,1) NOT NULL,
    decimal_places integer NOT NULL CHECK (decimal_places IN (0,1))
);

CREATE TABLE tenant_source_sequences (
    organization_id opaque_id PRIMARY KEY
        REFERENCES organizations ON DELETE CASCADE,
    next_sequence bigint NOT NULL DEFAULT 1 CHECK (next_sequence >= 1)
);

CREATE TABLE snapshots (
    organization_id opaque_id NOT NULL,
    source_sequence bigint NOT NULL CHECK (source_sequence >= 1),
    snapshot_id opaque_id NOT NULL,
    envelope_id opaque_id NOT NULL,
    subject_user_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    team_id opaque_id,
    visibility text NOT NULL
        CHECK (visibility IN ('individual','team','organization')),
    period_kind text NOT NULL
        CHECK (period_kind IN ('iso_week','calendar_month')),
    period_key text NOT NULL,
    issued_at timestamptz NOT NULL,
    accepted_at timestamptz NOT NULL,
    content_digest opaque_id NOT NULL,
    definition_version text NOT NULL
        REFERENCES measurement_definition_versions,
    producer_version text NOT NULL
        REFERENCES producer_adapter_versions,
    PRIMARY KEY (organization_id, source_sequence),
    UNIQUE (organization_id, snapshot_id),
    UNIQUE (organization_id, envelope_id),
    FOREIGN KEY (organization_id, subject_user_id, client_id, device_id)
        REFERENCES api_clients (
            organization_id, user_id, client_id, device_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (organization_id, team_id)
        REFERENCES teams ON DELETE RESTRICT,
    CHECK (visibility <> 'team' OR team_id IS NOT NULL)
);

CREATE TABLE snapshot_measurements (
    organization_id opaque_id NOT NULL,
    source_sequence bigint NOT NULL,
    metric_key text NOT NULL REFERENCES snapshot_metric_allowlist,
    unit text NOT NULL,
    value numeric(20,1), -- NULL is unknown; it is never rewritten to zero
    observed_count integer NOT NULL CHECK (observed_count >= 0),
    eligible_count integer NOT NULL CHECK (eligible_count >= 0),
    PRIMARY KEY (organization_id, source_sequence, metric_key),
    FOREIGN KEY (organization_id, source_sequence)
        REFERENCES snapshots ON DELETE CASCADE,
    CHECK (observed_count <= eligible_count),
    CHECK ((value IS NULL) = (observed_count = 0)),
    CHECK (value IS NULL OR value BETWEEN 0 AND 1000000000.0)
);

CREATE TABLE consumed_envelopes (
    organization_id opaque_id NOT NULL,
    envelope_id opaque_id NOT NULL,
    snapshot_id opaque_id NOT NULL,
    subject_user_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    content_digest opaque_id NOT NULL,
    first_source_sequence bigint NOT NULL CHECK (first_source_sequence >= 1),
    consumed_at timestamptz NOT NULL,
    deleted boolean NOT NULL DEFAULT false,
    PRIMARY KEY (organization_id, envelope_id),
    FOREIGN KEY (organization_id, subject_user_id, client_id, device_id)
        REFERENCES api_clients (
            organization_id, user_id, client_id, device_id
        ) ON DELETE RESTRICT
);
```

Version and metric tables are seeded only by reviewed migrations. The API role
cannot insert them. A constraint trigger validates each measurement's unit,
maximum, and allowed decimal places against its allowlist row. `numeric(20,1)`
is a hard outer precision boundary. Key choice, bounded values, and publication
timing can still signal information, so this design makes no absolute covert-
channel claim.

Reservation issuance locks the producer tuple and subject epoch and copies the
epoch into the reservation. The producer-tuple uniqueness constraint permits
exactly one outstanding reservation. Repeated issuance returns that same ID;
an expired row is deleted under the lock before one replacement is generated.
The lifetime is at most five minutes. This bounds candidate grinding without
consumption instead of giving a caller an unlimited unused pool. A successful
push consumes the slot and permits a fresh reservation. The development
adapter's recipient payload can carry accepted envelope IDs; the proposed
PostgreSQL recipient projection below deliberately omits them. Neither case
eliminates the other bounded value, key-selection, identifier, and timing
channels described above. The audit schema never stores an envelope ID.

Acceptance locks both rows and requires all of the following: the reservation
belongs to the authenticated subject/client/device; it has not expired; its
`subject_epoch` equals the current epoch; the signed `issued_at` is not before
the server reservation's `issued_at`; freshness is within the server clock
window; and the versions are registered. It inserts the snapshot and consumed
fence, then removes the outstanding reservation in the same transaction. The
snapshot therefore binds directly to the tenant-coherent API-client tuple and
does not retain a foreign key to a deleted reservation. A future timestamp
cannot revive a reservation from an older epoch or extend its server expiry.

The consumed row retains the minimum owner binding needed to distinguish a
legitimate replay from another tenant member probing a known deleted ID. An
unresolved or wrong-owner ID is reported and audited only as the fixed
`envelope_id_unregistered` reason; the supplied ID is not stored. Audit may use
a server-keyed, fixed-length request digest in a future design, but never the
raw rejected value.

## 4. Recipient-local streams and deletion delivery

Tenant source sequence is internal and is not returned in a push receipt or
delta. Each client/device receives a contiguous local sequence. Rows denied by
visibility advance only an internal source position and allocate no local
sequence, so they cannot create visible cursor gaps.

```sql
CREATE TABLE recipient_source_positions (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    source_sequence bigint NOT NULL DEFAULT 0 CHECK (source_sequence >= 0),
    PRIMARY KEY (organization_id, client_id, device_id),
    FOREIGN KEY (organization_id, client_id, device_id)
        REFERENCES api_clients (organization_id, client_id, device_id)
        ON DELETE RESTRICT
);

CREATE TABLE sync_checkpoints (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    acknowledged_sequence bigint NOT NULL DEFAULT 0
        CHECK (acknowledged_sequence >= 0),
    offered_sequence bigint NOT NULL DEFAULT 0
        CHECK (offered_sequence >= 0),
    next_sequence bigint NOT NULL DEFAULT 1 CHECK (next_sequence >= 1),
    PRIMARY KEY (organization_id, client_id, device_id),
    FOREIGN KEY (organization_id, client_id, device_id)
        REFERENCES api_clients (organization_id, client_id, device_id)
        ON DELETE RESTRICT,
    CHECK (acknowledged_sequence <= offered_sequence),
    CHECK (offered_sequence < next_sequence)
);

CREATE TABLE recipient_stream_items (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    recipient_sequence bigint NOT NULL CHECK (recipient_sequence >= 1),
    kind text NOT NULL CHECK (kind IN ('snapshot','tombstone')),
    recipient_snapshot_id opaque_id,
    tombstone_id opaque_id,
    target_recipient_snapshot_id opaque_id,
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (
        organization_id, client_id, device_id, recipient_sequence
    ),
    UNIQUE (
        organization_id, client_id, device_id, recipient_snapshot_id
    ),
    UNIQUE (organization_id, client_id, device_id, tombstone_id),
    FOREIGN KEY (organization_id, client_id, device_id)
        REFERENCES api_clients (organization_id, client_id, device_id)
        ON DELETE RESTRICT,
    CHECK (
        (kind = 'snapshot'
         AND recipient_snapshot_id IS NOT NULL
         AND tombstone_id IS NULL
         AND target_recipient_snapshot_id IS NULL)
        OR
        (kind = 'tombstone'
         AND recipient_snapshot_id IS NULL
         AND tombstone_id IS NOT NULL
         AND target_recipient_snapshot_id IS NOT NULL)
    )
);

CREATE TABLE recipient_snapshot_payloads (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    recipient_sequence bigint NOT NULL CHECK (recipient_sequence >= 1),
    recipient_subject_handle opaque_id NOT NULL,
    recipient_team_handle opaque_id,
    visibility text NOT NULL
        CHECK (visibility IN ('individual','team','organization')),
    period_kind text NOT NULL
        CHECK (period_kind IN ('iso_week','calendar_month')),
    period_key text NOT NULL,
    issued_at timestamptz NOT NULL,
    accepted_at timestamptz NOT NULL,
    definition_version text NOT NULL
        REFERENCES measurement_definition_versions,
    producer_version text NOT NULL
        REFERENCES producer_adapter_versions,
    PRIMARY KEY (
        organization_id, client_id, device_id, recipient_sequence
    ),
    FOREIGN KEY (
        organization_id, client_id, device_id, recipient_sequence
    ) REFERENCES recipient_stream_items (
        organization_id, client_id, device_id, recipient_sequence
    ) ON DELETE CASCADE,
    CHECK (visibility <> 'team' OR recipient_team_handle IS NOT NULL)
);

CREATE TABLE recipient_snapshot_measurements (
    organization_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    recipient_sequence bigint NOT NULL CHECK (recipient_sequence >= 1),
    metric_key text NOT NULL REFERENCES snapshot_metric_allowlist,
    unit text NOT NULL,
    value numeric(20,1),
    observed_count integer NOT NULL CHECK (observed_count >= 0),
    eligible_count integer NOT NULL CHECK (eligible_count >= 0),
    PRIMARY KEY (
        organization_id, client_id, device_id, recipient_sequence, metric_key
    ),
    FOREIGN KEY (
        organization_id, client_id, device_id, recipient_sequence
    ) REFERENCES recipient_snapshot_payloads (
        organization_id, client_id, device_id, recipient_sequence
    ) ON DELETE CASCADE,
    CHECK (observed_count <= eligible_count),
    CHECK ((value IS NULL) = (observed_count = 0)),
    CHECK (value IS NULL OR value BETWEEN 0 AND 1000000000.0)
);

CREATE TABLE snapshot_delivery_ledger (
    organization_id opaque_id NOT NULL,
    source_snapshot_id opaque_id NOT NULL,
    client_id opaque_id NOT NULL,
    device_id opaque_id NOT NULL,
    recipient_sequence bigint NOT NULL CHECK (recipient_sequence >= 1),
    recipient_snapshot_id opaque_id NOT NULL,
    first_offered_at timestamptz NOT NULL,
    PRIMARY KEY (
        organization_id, source_snapshot_id, client_id, device_id
    ),
    UNIQUE (
        organization_id, client_id, device_id, recipient_snapshot_id
    ),
    FOREIGN KEY (organization_id, source_snapshot_id)
        REFERENCES snapshots (organization_id, snapshot_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (organization_id, client_id, device_id)
        REFERENCES api_clients (organization_id, client_id, device_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (
        organization_id, client_id, device_id, recipient_sequence
    ) REFERENCES recipient_stream_items (
        organization_id, client_id, device_id, recipient_sequence
    )
        ON DELETE RESTRICT
);
```

`recipient_snapshot_payloads` and its measurements are a durable,
recipient-bound projection. They contain only the already-approved structured
metric payload and recipient-specific opaque subject/team handles: never a
source snapshot ID, source content digest, producer envelope ID, prompt,
transcript, source snippet, or global subject/team handle. They have no foreign
key or read path back to `snapshots`. The internal delivery ledger is the only
source-to-recipient association and is not granted to the client-facing role.

Initial authorization against the source snapshot, projection, stream-item and
ledger insertion, and raising `offered_sequence` happen in one transaction. An
acknowledgement is accepted only when it is monotonic and no greater than the
highest sequence offered to that exact client/device. Unacknowledged rows are
redelivered from the durable recipient projection, so the contract is at least
once rather than exactly once. Current snapshot visibility and manager grants
are deliberately not re-evaluated for a row already offered to that recipient.

The delivery ledger is intentionally independent of current visibility. On
deletion, every ledger row receives a new, recipient-specific tombstone whose
target is that recipient's snapshot handle—even if a manager grant has expired
or been revoked. A recipient cannot correlate its handle or tombstone ID with
another recipient's. Once tombstones are durably appended, earlier stream
snapshot rows are converted to opaque tombstones before the source snapshot is
deleted; the corresponding recipient payload and measurement rows are deleted
before conversion, preventing a retry from returning erased payload. The
dedicated new tombstone also closes the race in which a client acknowledges the
old offer at the moment deletion occurs.

## 5. Manager grants and audit

```sql
CREATE TABLE manager_access_grants (
    organization_id opaque_id NOT NULL,
    grant_id opaque_id NOT NULL,
    manager_user_id opaque_id NOT NULL,
    subject_user_id opaque_id,
    team_id opaque_id,
    granted_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (organization_id, grant_id),
    FOREIGN KEY (organization_id, manager_user_id)
        REFERENCES memberships ON DELETE RESTRICT,
    FOREIGN KEY (organization_id, subject_user_id)
        REFERENCES memberships ON DELETE RESTRICT,
    FOREIGN KEY (organization_id, team_id)
        REFERENCES teams ON DELETE RESTRICT,
    CHECK ((subject_user_id IS NULL) <> (team_id IS NULL)),
    CHECK (expires_at > granted_at),
    CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);

CREATE TABLE audit_events (
    organization_id opaque_id NOT NULL
        REFERENCES organizations ON DELETE CASCADE,
    sequence bigint NOT NULL CHECK (sequence >= 1),
    audit_id opaque_id NOT NULL,
    recorded_at timestamptz NOT NULL,
    action text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('allow','deny')),
    reason text NOT NULL,
    actor_user_id opaque_id,
    actor_device_id opaque_id,
    actor_client_id opaque_id,
    subject_user_id opaque_id,
    team_id opaque_id,
    manager_grant_id opaque_id,
    PRIMARY KEY (organization_id, sequence),
    UNIQUE (organization_id, audit_id)
);
```

A grant names exactly one target because the XOR is a database check, not a
comment. Revocation sets `revoked_at` through an administrator-only use case and
writes `manager_grant_revoked`. Read policy requires `revoked_at IS NULL OR
now() < revoked_at` as well as `now() < expires_at`.

Audit has no free-text detail column and no reservation or envelope identifier
column. A caller-visible reservation ID is never persisted in an issuance,
acceptance, replay, expiry, or rejection audit event. `audit_id` is generated
only while the event is appended and is inaccessible before that event, so it
cannot be selected as a publication carrier. Other denied resource identifiers
are null unless the application first resolved ownership from a tenant-scoped
row. Actor IDs come from the credential. Action and reason are closed enums.
This bounds storage and prevents audit-log injection by an arbitrary
valid-looking ID. It does not eliminate residual signaling through permitted
snapshot keys, bounded values, or publication timing.

## 6. RLS without permissive-OR bypass

PostgreSQL combines applicable permissive policies with `OR`. Therefore this
design never installs a broad tenant-only permissive `SELECT` policy beside a
visibility policy: that would make the tenant policy bypass visibility. Each
sensitive command has one combined policy containing tenant, credential
binding, entitlement, scope, and visibility predicates.

The insert policy treats `team_id` as authorization-relevant even when
visibility is not `team`: every non-null value requires an active
`team_memberships` row for the exact organization, team, and credential-bound
subject. This prevents a publisher from attaching another team's identifier as
metadata or relying only on the tenant-coherent foreign key.

```sql
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots FORCE ROW LEVEL SECURITY;

CREATE POLICY snapshots_select_combined ON snapshots FOR SELECT
USING (
    organization_id = NULLIF(
        current_setting('app.organization_id', true), ''
    )::opaque_id
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id = snapshots.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1
        FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.user_id, c.client_id, c.device_id) = (
            snapshots.organization_id,
            NULLIF(current_setting('app.user_id', true), '')::opaque_id,
            NULLIF(current_setting('app.client_id', true), '')::opaque_id,
            NULLIF(current_setting('app.device_id', true), '')::opaque_id
        )
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:pull'
    )
    AND (
        subject_user_id = NULLIF(
            current_setting('app.user_id', true), ''
        )::opaque_id
        OR visibility = 'organization'
        OR (
            visibility = 'team'
            AND EXISTS (
                SELECT 1 FROM team_memberships tm
                WHERE (tm.organization_id, tm.team_id, tm.user_id) = (
                    snapshots.organization_id,
                    snapshots.team_id,
                    NULLIF(current_setting('app.user_id', true), '')::opaque_id
                )
                  AND tm.state = 'active'
            )
        )
        OR EXISTS (
            SELECT 1 FROM manager_access_grants g
            WHERE g.organization_id = snapshots.organization_id
              AND g.manager_user_id =
                  NULLIF(current_setting('app.user_id', true), '')::opaque_id
              AND g.granted_at <= statement_timestamp()
              AND statement_timestamp() < g.expires_at
              AND (g.revoked_at IS NULL
                   OR statement_timestamp() < g.revoked_at)
              AND EXISTS (
                  SELECT 1 FROM memberships gm
                  WHERE (gm.organization_id, gm.user_id) = (
                      g.organization_id, g.manager_user_id
                  )
                    AND gm.state = 'active'
                    AND gm.role IN ('owner','admin','manager')
              )
              AND (g.subject_user_id = snapshots.subject_user_id
                   OR g.team_id = snapshots.team_id)
        )
    )
);

CREATE POLICY snapshots_insert_combined ON snapshots FOR INSERT
WITH CHECK (
    organization_id = NULLIF(
        current_setting('app.organization_id', true), ''
    )::opaque_id
    AND (subject_user_id, client_id, device_id) = (
        NULLIF(current_setting('app.user_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id = snapshots.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1
        FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.user_id, c.client_id, c.device_id) = (
            snapshots.organization_id,
            snapshots.subject_user_id,
            snapshots.client_id,
            snapshots.device_id
        )
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:push'
    )
    AND (
        snapshots.team_id IS NULL
        OR EXISTS (
            SELECT 1 FROM team_memberships tm
            WHERE (tm.organization_id, tm.team_id, tm.user_id) = (
                snapshots.organization_id,
                snapshots.team_id,
                snapshots.subject_user_id
            )
              AND tm.user_id = NULLIF(
                  current_setting('app.user_id', true), ''
              )::opaque_id
              AND tm.state = 'active'
        )
    )
);

ALTER TABLE recipient_stream_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE recipient_stream_items FORCE ROW LEVEL SECURITY;

CREATE POLICY recipient_stream_select_combined
ON recipient_stream_items FOR SELECT
USING (
    (organization_id, client_id, device_id) = (
        NULLIF(current_setting('app.organization_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id = recipient_stream_items.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1 FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.client_id, c.device_id) = (
            recipient_stream_items.organization_id,
            recipient_stream_items.client_id,
            recipient_stream_items.device_id
        )
          AND c.user_id =
              NULLIF(current_setting('app.user_id', true), '')::opaque_id
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:pull'
    )
);

ALTER TABLE recipient_snapshot_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE recipient_snapshot_payloads FORCE ROW LEVEL SECURITY;

CREATE POLICY recipient_payload_select_combined
ON recipient_snapshot_payloads FOR SELECT
USING (
    (organization_id, client_id, device_id) = (
        NULLIF(current_setting('app.organization_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id = recipient_snapshot_payloads.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1 FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.client_id, c.device_id) = (
            recipient_snapshot_payloads.organization_id,
            recipient_snapshot_payloads.client_id,
            recipient_snapshot_payloads.device_id
        )
          AND c.user_id =
              NULLIF(current_setting('app.user_id', true), '')::opaque_id
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:pull'
    )
);

ALTER TABLE recipient_snapshot_measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE recipient_snapshot_measurements FORCE ROW LEVEL SECURITY;

CREATE POLICY recipient_measurement_select_combined
ON recipient_snapshot_measurements FOR SELECT
USING (
    (organization_id, client_id, device_id) = (
        NULLIF(current_setting('app.organization_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id =
              recipient_snapshot_measurements.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1 FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.client_id, c.device_id) = (
            recipient_snapshot_measurements.organization_id,
            recipient_snapshot_measurements.client_id,
            recipient_snapshot_measurements.device_id
        )
          AND c.user_id =
              NULLIF(current_setting('app.user_id', true), '')::opaque_id
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:pull'
    )
);

ALTER TABLE sync_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_checkpoints FORCE ROW LEVEL SECURITY;

CREATE POLICY sync_checkpoint_owner_combined ON sync_checkpoints FOR ALL
USING (
    (organization_id, client_id, device_id) = (
        NULLIF(current_setting('app.organization_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id = sync_checkpoints.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1 FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.client_id, c.device_id) = (
            sync_checkpoints.organization_id,
            sync_checkpoints.client_id,
            sync_checkpoints.device_id
        )
          AND c.user_id =
              NULLIF(current_setting('app.user_id', true), '')::opaque_id
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:pull'
    )
)
WITH CHECK (
    (organization_id, client_id, device_id) = (
        NULLIF(current_setting('app.organization_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    AND EXISTS (
        SELECT 1 FROM entitlements e
        WHERE e.organization_id = sync_checkpoints.organization_id
          AND e.remote_sync_enabled
    )
    AND EXISTS (
        SELECT 1 FROM api_clients c
        JOIN api_client_scopes s
          ON (s.organization_id, s.client_id)
           = (c.organization_id, c.client_id)
        JOIN devices d
          ON (d.organization_id, d.user_id, d.device_id)
           = (c.organization_id, c.user_id, c.device_id)
        JOIN memberships m
          ON (m.organization_id, m.user_id)
           = (c.organization_id, c.user_id)
        WHERE (c.organization_id, c.client_id, c.device_id) = (
            sync_checkpoints.organization_id,
            sync_checkpoints.client_id,
            sync_checkpoints.device_id
        )
          AND c.user_id =
              NULLIF(current_setting('app.user_id', true), '')::opaque_id
          AND c.state = 'active'
          AND d.state = 'active'
          AND m.state = 'active'
          AND s.scope = 'snapshots:pull'
    )
);
```

### Exact recipient retry accessor

The client-facing role uses the following prepared statement inside the same
transaction that owns the checkpoint lock. It accepts only a bounded page size;
the recipient tuple comes exclusively from credential-derived `SET LOCAL`
claims. It neither accepts resource IDs nor reads the source-snapshot or
manager-grant tables.

```sql
WITH locked_checkpoint AS MATERIALIZED (
    SELECT organization_id, client_id, device_id,
           acknowledged_sequence, offered_sequence
    FROM sync_checkpoints
    WHERE (organization_id, client_id, device_id) = (
        NULLIF(current_setting('app.organization_id', true), '')::opaque_id,
        NULLIF(current_setting('app.client_id', true), '')::opaque_id,
        NULLIF(current_setting('app.device_id', true), '')::opaque_id
    )
    FOR UPDATE
),
selected AS MATERIALIZED (
    SELECT i.*
    FROM recipient_stream_items i
    JOIN locked_checkpoint c USING (organization_id, client_id, device_id)
    WHERE i.recipient_sequence > c.acknowledged_sequence
    ORDER BY i.recipient_sequence
    LIMIT LEAST(GREATEST($1, 1), 100)
),
raised_offer AS (
    UPDATE sync_checkpoints c
    SET offered_sequence = GREATEST(
        c.offered_sequence,
        COALESCE(
            (SELECT max(recipient_sequence) FROM selected),
            c.offered_sequence
        )
    )
    FROM locked_checkpoint locked
    WHERE (c.organization_id, c.client_id, c.device_id) =
          (locked.organization_id, locked.client_id, locked.device_id)
    RETURNING c.organization_id, c.client_id, c.device_id,
              c.acknowledged_sequence, c.offered_sequence
)
SELECT selected.recipient_sequence, selected.kind,
       selected.recipient_snapshot_id, selected.tombstone_id,
       selected.target_recipient_snapshot_id, selected.recorded_at,
       payload.recipient_subject_handle, payload.recipient_team_handle,
       payload.visibility, payload.period_kind, payload.period_key,
       payload.issued_at, payload.accepted_at,
       payload.definition_version, payload.producer_version,
       metrics.items AS measurements
FROM selected
JOIN raised_offer USING (organization_id, client_id, device_id)
LEFT JOIN recipient_snapshot_payloads payload
  USING (organization_id, client_id, device_id, recipient_sequence)
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'metric_key', measurement.metric_key,
            'unit', measurement.unit,
            'value', measurement.value,
            'observed_count', measurement.observed_count,
            'eligible_count', measurement.eligible_count
        ) ORDER BY measurement.metric_key
    ) AS items
    FROM recipient_snapshot_measurements measurement
    WHERE (measurement.organization_id, measurement.client_id,
           measurement.device_id, measurement.recipient_sequence) =
          (selected.organization_id, selected.client_id,
           selected.device_id, selected.recipient_sequence)
) metrics ON true
ORDER BY selected.recipient_sequence;
```

All three recipient tables and the checkpoint independently apply the combined
RLS gate above: exact organization/client/device claims, credential-bound user,
active client, active device, active membership, pull scope, and enabled remote
sync entitlement. None has a manager-grant predicate. Thus revoking or expiring
the grant prevents new source materialization while an already-offered,
unacknowledged projection remains retryable by that same still-active
client/device. A constraint trigger also requires a payload row to correspond
to a `kind = 'snapshot'` stream item before commit.

Other tenant tables receive one combined tenant policy per applicable command
and `FORCE ROW LEVEL SECURITY`. Registry tables are migration-owned and
read-only. Internal source positions and the delivery ledger are not granted to
the client-facing SQL role. If predicates are ever split for maintainability,
there must be exactly one permissive tenant gate and every additional policy
must be declared `AS RESTRICTIVE`; adapter tests inspect `pg_policies` to enforce
that invariant.

Recipient tombstones do not re-run snapshot visibility. Exact recipient binding
is the authorization: the row exists only because the ledger proves this
client/device was previously offered that opaque handle. This is what makes
deletion survive manager-grant expiry without broadening access to any snapshot.

## 7. Atomic workflows

Acceptance is one serializable transaction:

1. lock the credential-bound client, device, subject epoch, and server-created
   reservation;
2. verify active state, `remote_sync_enabled`, push scope, reservation owner,
   reservation epoch, reservation issuance time, freshness, registered versions,
   allowlisted metrics, and signature;
3. lock the tenant source counter and allocate one internal sequence;
4. insert the snapshot, measurements, and owner-bound consumed fence, then
   delete the outstanding reservation;
5. append a minimized audit event and commit.

First offer is also one serializable transaction: lock the recipient source
position and checkpoint; authorize the source row as of that transaction;
allocate one local sequence and fresh recipient-only handles; insert the stream
item, payload, measurements, and delivery-ledger row; advance the internal
source position and offered sequence; then commit. Retrying never rebuilds this
projection from its source.

Deletion is one serializable transaction, even when the subject has no snapshot:

1. lock the subject epoch, increment it, and delete **all** unconsumed
   reservations for that subject;
2. lock the subject's snapshots and all matching delivery-ledger rows;
3. allocate and append a recipient-local opaque tombstone for every ledger row,
   without consulting current team membership or manager grants;
4. delete prior recipient projections and convert their stream rows, mark
   consumed fences `deleted`, and remove reservations, source measurements,
   snapshots, and ledger rows;
5. append the fixed audit event and commit.

Manager-grant revocation, device/client/credential revocation, source-sequence
allocation, recipient-sequence allocation, cursor offer/acknowledgement, and
delivery-ledger insertion likewise occur under locked rows in single
transactions. Retry and crash tests must prove these boundaries; application
ordering alone is not sufficient.

## 8. Aggregates fail closed

The public team-aggregate use case returns
`disclosure_control_unavailable` with no cohort count, eligible count,
contributor count, or value. A fixed bucket and threshold alone do not prevent
cross-team or longitudinal differencing.

No production aggregate table or release policy may be added until a separate
review defines and tests stable privacy-cohort membership, overlap rules,
longitudinal composition, a persisted per-principal query budget, budget
consumption atomicity, deletion behavior, and a response policy that does not
reveal sub-threshold cardinality. The internal arithmetic helper is not a safe
release mechanism.

## 9. Required adapter attacks

A PostgreSQL adapter is incomplete until database-level tests prove:

1. tenant A cannot read or mutate tenant B through missing `WHERE` clauses,
   guessed IDs, joins, nullable team keys, or foreign-key substitution;
2. missing claims return zero rows, pooled claims do not survive a transaction,
   and the application role cannot bypass or own RLS tables;
3. `pg_policies` contains no second permissive policy for the same sensitive
   table/command; an expired/revoked manager grant cannot read a snapshot;
4. every composite foreign key rejects a cross-tenant parent combination, and
   every non-null snapshot team ID requires the credential-bound subject's
   active team-membership row;
5. an erasure invalidates every old reservation, including one replayed with a
   future signed timestamp, while a new post-erasure reservation uses the new
   epoch;
6. a wrong-owner probe of a deleted server ID yields the same fixed rejection as
   an unknown ID and stores neither supplied value in audit;
7. denied source rows allocate no recipient sequence and produce no public
   cursor gap or push-receipt gap;
8. each client/device that was offered a snapshot receives a distinct opaque
   deletion handle after grant expiry/revocation, while a never-offered client
   receives none;
9. concurrent writers allocate unique contiguous source and recipient sequences,
   acknowledgements are monotonic and recipient-bound, and retries redeliver;
10. device revocation clears the key and revokes clients and credential bindings
    atomically, and every remote read/write enforces entitlement and scope;
11. unregistered versions, metrics, units, excess magnitude, fractional count
    values, non-finite values, and overlong identifiers are rejected;
12. aggregate reads remain fully suppressed until the separate disclosure
    mechanism is implemented and reviewed;
13. thousands of reserve-only issuance attempts expose only one active candidate
    until its five-minute expiry, and accepted, rejected, expired, wrong-owner,
    and attacker-chosen canary IDs are absent from every audit row;
14. an already-offered, unacknowledged recipient projection redelivers after the
    authorizing manager grant expires or is revoked without joining the source
    snapshot, while checkpoint and projection access fail when the exact client,
    device, membership, pull scope, or remote-sync entitlement is inactive.

Operational erasure still requires documented backup expiry, WAL/archive
retention, replica-lag handling, and client deletion acknowledgement. A queued
tombstone cannot prove a disconnected device processed it.
