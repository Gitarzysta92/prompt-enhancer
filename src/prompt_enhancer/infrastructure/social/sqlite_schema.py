"""Typed, content-free SQLite schema for the local social/file control plane.

Every table is STRICT and tenant scoped.  Only control-plane metadata exists:
identifiers, states, roles, digests, sizes, versions and timestamps.  There is
no column for message bodies, ciphertext bytes, file bytes, file names, paths,
network candidates, credentials, key material or analyzer identifiers, and no
migration may add one without a reviewed ADR.
"""

from __future__ import annotations


SOCIAL_SCHEMA_VERSION = 3

# Version 1 was a placeholder boundary; no adapter ever wrote rows to it.  The
# ledger keeps the entry and version 2 replaces the placeholder tables.
_V1_PLACEHOLDER_TABLES = (
    "social_file_grant_metadata",
    "social_file_manifest_metadata",
    "social_message_envelope_metadata",
    "social_conversation_metadata",
    "social_relationship_metadata",
    "social_devices",
    "social_accounts",
)


def _soc(column: str) -> str:
    return (
        f"{column} TEXT NOT NULL CHECK (length({column}) = 68 "
        f"AND substr({column}, 1, 4) = 'soc_' "
        f"AND substr({column}, 5) NOT GLOB '*[^0-9a-f]*')"
    )


def _soc_null(column: str) -> str:
    return (
        f"{column} TEXT CHECK ({column} IS NULL OR (length({column}) = 68 "
        f"AND substr({column}, 1, 4) = 'soc_' "
        f"AND substr({column}, 5) NOT GLOB '*[^0-9a-f]*'))"
    )


def _shr(column: str) -> str:
    return (
        f"{column} TEXT NOT NULL CHECK (length({column}) = 68 "
        f"AND substr({column}, 1, 4) = 'shr_' "
        f"AND substr({column}, 5) NOT GLOB '*[^0-9a-f]*')"
    )


def _shr_null(column: str) -> str:
    return (
        f"{column} TEXT CHECK ({column} IS NULL OR (length({column}) = 68 "
        f"AND substr({column}, 1, 4) = 'shr_' "
        f"AND substr({column}, 5) NOT GLOB '*[^0-9a-f]*'))"
    )


def _digest(column: str) -> str:
    return (
        f"{column} TEXT NOT NULL CHECK (length({column}) = 64 "
        f"AND {column} NOT GLOB '*[^0-9a-f]*')"
    )


def _digest_null(column: str) -> str:
    return (
        f"{column} TEXT CHECK ({column} IS NULL OR (length({column}) = 64 "
        f"AND {column} NOT GLOB '*[^0-9a-f]*'))"
    )


def _ts(column: str) -> str:
    # ISO-8601 UTC whole seconds: 2047-03-08T12:00:00+00:00
    return (
        f"{column} TEXT NOT NULL CHECK (length({column}) = 25 "
        f"AND substr({column}, 20) = '+00:00')"
    )


def _ts_null(column: str) -> str:
    return (
        f"{column} TEXT CHECK ({column} IS NULL OR (length({column}) = 25 "
        f"AND substr({column}, 20) = '+00:00'))"
    )


def _enum(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} TEXT NOT NULL CHECK ({column} IN ({quoted}))"


def _enum_null(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} TEXT CHECK ({column} IS NULL OR {column} IN ({quoted}))"


SOCIAL_SCHEMA_V2: tuple[str, ...] = (
    *(f"DROP TABLE IF EXISTS {table}" for table in _V1_PLACEHOLDER_TABLES),
    f"""
    CREATE TABLE social_accounts (
        {_soc("organization_id")}, {_soc("account_id")},
        {_enum("state", ("active", "suspended", "deleted"))},
        {_ts("created_at")}, {_ts_null("deleted_at")},
        PRIMARY KEY (organization_id, account_id),
        CHECK ((state = 'deleted') = (deleted_at IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_organization_memberships (
        {_soc("organization_id")}, {_soc("account_id")},
        {_enum("role", ("owner", "admin", "moderator", "member"))},
        {_enum("state", ("active", "suspended", "revoked"))},
        {_ts("created_at")}, {_ts_null("revoked_at")},
        PRIMARY KEY (organization_id, account_id),
        FOREIGN KEY (organization_id, account_id)
            REFERENCES social_accounts (organization_id, account_id),
        CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_devices (
        {_soc("organization_id")}, {_soc("device_id")}, {_soc("account_id")},
        {_enum("state", ("active", "revoked"))},
        signing_algorithm TEXT NOT NULL CHECK (signing_algorithm = 'ed25519'),
        agreement_algorithm TEXT NOT NULL CHECK (agreement_algorithm = 'x25519'),
        signing_key_version INTEGER NOT NULL CHECK (signing_key_version > 0),
        agreement_key_version INTEGER NOT NULL CHECK (agreement_key_version > 0),
        {_digest("signing_key_fingerprint")}, {_digest("agreement_key_fingerprint")},
        {_ts("enrolled_at")}, {_ts_null("revoked_at")},
        PRIMARY KEY (organization_id, device_id),
        FOREIGN KEY (organization_id, account_id)
            REFERENCES social_accounts (organization_id, account_id),
        CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_teams (
        {_soc("organization_id")}, {_soc("team_id")}, {_soc("owner_account_id")},
        invitation_only INTEGER NOT NULL CHECK (invitation_only = 1),
        discoverable INTEGER NOT NULL CHECK (discoverable = 0),
        {_ts("created_at")},
        PRIMARY KEY (organization_id, team_id),
        FOREIGN KEY (organization_id, owner_account_id)
            REFERENCES social_accounts (organization_id, account_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_team_memberships (
        {_soc("organization_id")}, {_soc("team_id")}, {_soc("account_id")},
        {_enum("role", ("lead", "member"))},
        {_enum("state", ("active", "suspended", "revoked"))},
        {_ts("created_at")}, {_ts_null("revoked_at")},
        PRIMARY KEY (organization_id, team_id, account_id),
        FOREIGN KEY (organization_id, team_id)
            REFERENCES social_teams (organization_id, team_id),
        FOREIGN KEY (organization_id, account_id)
            REFERENCES social_accounts (organization_id, account_id),
        CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_friend_requests (
        {_soc("organization_id")}, {_soc("request_id")},
        {_soc("requester_account_id")}, {_soc("recipient_account_id")},
        {_enum("state", ("pending", "accepted", "declined", "cancelled", "expired"))},
        {_ts("created_at")}, {_ts("expires_at")}, {_ts_null("decided_at")},
        PRIMARY KEY (organization_id, request_id),
        CHECK (requester_account_id <> recipient_account_id),
        CHECK ((state = 'pending') = (decided_at IS NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_friendships (
        {_soc("organization_id")}, {_soc("first_account_id")},
        {_soc("second_account_id")}, {_soc("accepted_request_id")},
        {_ts("created_at")},
        PRIMARY KEY (organization_id, first_account_id, second_account_id),
        CHECK (first_account_id < second_account_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_blocks (
        {_soc("organization_id")}, {_soc("blocker_account_id")},
        {_soc("blocked_account_id")}, {_ts("created_at")},
        PRIMARY KEY (organization_id, blocker_account_id, blocked_account_id),
        CHECK (blocker_account_id <> blocked_account_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_private_channels (
        {_soc("organization_id")}, {_soc("channel_id")}, {_soc_null("team_id")},
        {_soc("owner_account_id")},
        invitation_only INTEGER NOT NULL CHECK (invitation_only = 1),
        discoverable INTEGER NOT NULL CHECK (discoverable = 0),
        {_ts("created_at")},
        PRIMARY KEY (organization_id, channel_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_channel_memberships (
        {_soc("organization_id")}, {_soc("channel_id")}, {_soc("account_id")},
        {_enum("role", ("owner", "moderator", "member"))},
        {_enum("state", ("invited", "active", "left", "removed"))},
        {_soc("invited_by_account_id")}, {_ts("created_at")}, {_ts("changed_at")},
        PRIMARY KEY (organization_id, channel_id, account_id),
        FOREIGN KEY (organization_id, channel_id)
            REFERENCES social_private_channels (organization_id, channel_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_conversation_fences (
        {_soc("organization_id")}, {_soc("conversation_id")},
        {_ts("created_at")}, {_ts_null("closed_at")},
        PRIMARY KEY (organization_id, conversation_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_conversations (
        {_soc("organization_id")}, {_soc("conversation_id")},
        {_enum("kind", ("direct", "private_group"))}, {_soc_null("channel_id")},
        invitation_only INTEGER NOT NULL CHECK (invitation_only = 1),
        discoverable INTEGER NOT NULL CHECK (discoverable = 0),
        current_key_version INTEGER NOT NULL CHECK (current_key_version > 0),
        {_ts("created_at")},
        PRIMARY KEY (organization_id, conversation_id),
        UNIQUE (organization_id, channel_id),
        FOREIGN KEY (organization_id, conversation_id)
            REFERENCES social_conversation_fences (organization_id, conversation_id),
        CHECK ((kind = 'direct') = (channel_id IS NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_conversation_members (
        {_soc("organization_id")}, {_soc("conversation_id")}, {_soc("account_id")},
        PRIMARY KEY (organization_id, conversation_id, account_id),
        FOREIGN KEY (organization_id, conversation_id)
            REFERENCES social_conversations (organization_id, conversation_id)
            ON DELETE CASCADE
    ) STRICT
    """,
    f"""
    CREATE TABLE social_message_envelopes (
        {_soc("organization_id")}, {_soc("envelope_id")}, {_soc("conversation_id")},
        {_soc("message_id")}, {_soc("sender_account_id")}, {_soc("sender_device_id")},
        {_enum("operation", ("create", "edit", "delete"))},
        revision INTEGER NOT NULL CHECK (revision > 0),
        key_version INTEGER NOT NULL CHECK (key_version > 0),
        aead_algorithm TEXT NOT NULL CHECK (aead_algorithm = 'xchacha20-poly1305'),
        ciphertext_size INTEGER NOT NULL CHECK (
            ciphertext_size > 0 AND ciphertext_size <= 16777216
        ),
        {_digest("ciphertext_sha256")}, {_soc_null("thread_root_message_id")},
        {_ts("created_at")}, {_ts("accepted_at")},
        PRIMARY KEY (organization_id, envelope_id),
        UNIQUE (organization_id, conversation_id, message_id, revision),
        FOREIGN KEY (organization_id, conversation_id)
            REFERENCES social_conversation_fences (organization_id, conversation_id),
        CHECK ((operation = 'create') = (revision = 1))
    ) STRICT
    """,
    """
    CREATE TRIGGER social_message_envelopes_require_active_conversation
    BEFORE INSERT ON social_message_envelopes
    FOR EACH ROW
    WHEN NOT EXISTS (
        SELECT 1 FROM social_conversations
        WHERE organization_id = NEW.organization_id
          AND conversation_id = NEW.conversation_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'conversation unavailable');
    END
    """,
    f"""
    CREATE TABLE social_message_tombstones (
        {_soc("organization_id")}, {_soc("conversation_id")}, {_soc("message_id")},
        {_soc("sender_account_id")}, {_ts("deleted_at")},
        remote_plaintext_recall_guaranteed INTEGER NOT NULL CHECK (
            remote_plaintext_recall_guaranteed = 0
        ),
        PRIMARY KEY (organization_id, conversation_id, message_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_message_reactions (
        {_soc("organization_id")}, {_soc("conversation_id")}, {_soc("message_id")},
        {_soc("actor_account_id")},
        {_enum("reaction", ("acknowledged", "approved", "heart", "laugh", "thumbs_down", "thumbs_up"))},
        active INTEGER NOT NULL CHECK (active IN (0, 1)), {_ts("changed_at")},
        PRIMARY KEY (organization_id, conversation_id, message_id, actor_account_id, reaction)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_conversation_read_states (
        {_soc("organization_id")}, {_soc("conversation_id")}, {_soc("account_id")},
        last_read_sequence INTEGER NOT NULL CHECK (last_read_sequence >= 0),
        {_ts("updated_at")},
        PRIMARY KEY (organization_id, conversation_id, account_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_presence (
        {_soc("organization_id")}, {_soc("subject_account_id")},
        {_soc("audience_account_id")},
        {_enum("state", ("available", "away", "offline"))},
        {_ts("observed_at")}, {_ts("expires_at")},
        PRIMARY KEY (organization_id, subject_account_id, audience_account_id),
        CHECK (subject_account_id <> audience_account_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_audit_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        {_soc("organization_id")}, {_soc("audit_id")}, {_soc("actor_account_id")},
        {_soc("actor_device_id")}, {_soc_null("target_account_id")},
        action TEXT NOT NULL CHECK (length(action) <= 40 AND action NOT GLOB '*[^a-z_]*'),
        {_enum("decision", ("allow", "deny"))},
        reason TEXT NOT NULL CHECK (length(reason) <= 40 AND reason NOT GLOB '*[^a-z_]*'),
        {_ts("occurred_at")},
        UNIQUE (organization_id, audit_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_peer_deletion_acknowledgements (
        {_soc("organization_id")}, {_soc("subject_account_id")}, {_soc("peer_device_id")},
        {_enum("state", ("requested", "acknowledged", "expired"))},
        {_ts("requested_at")}, {_ts_null("acknowledged_at")},
        PRIMARY KEY (organization_id, subject_account_id, peer_device_id),
        CHECK ((state = 'acknowledged') = (acknowledged_at IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_deletion_receipts (
        {_soc("organization_id")}, {_soc("account_id")}, {_soc("receipt_id")},
        relationship_rows_removed INTEGER NOT NULL CHECK (relationship_rows_removed >= 0),
        message_metadata_rows_tombstoned INTEGER NOT NULL CHECK (message_metadata_rows_tombstoned >= 0),
        conversation_membership_rows_removed INTEGER NOT NULL CHECK (conversation_membership_rows_removed >= 0),
        reaction_and_read_rows_removed INTEGER NOT NULL CHECK (reaction_and_read_rows_removed >= 0),
        presence_rows_removed INTEGER NOT NULL CHECK (presence_rows_removed >= 0),
        local_metadata_erased INTEGER NOT NULL CHECK (local_metadata_erased = 0),
        peer_deletion_requested INTEGER NOT NULL CHECK (peer_deletion_requested IN (0, 1)),
        remote_plaintext_recall_guaranteed INTEGER NOT NULL CHECK (
            remote_plaintext_recall_guaranteed = 0
        ),
        {_ts("completed_at")},
        PRIMARY KEY (organization_id, receipt_id),
        UNIQUE (organization_id, account_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_manifests (
        {_soc("organization_id")}, {_shr("manifest_id")}, {_soc("owner_account_id")},
        {_soc("owner_device_id")},
        {_enum("content_kind", ("archive", "audio", "document", "image", "other", "source_bundle", "video"))},
        byte_size INTEGER NOT NULL CHECK (byte_size > 0),
        chunk_size INTEGER NOT NULL CHECK (chunk_size >= 65536 AND chunk_size <= 16777216),
        {_digest("whole_file_sha256")}, {_digest("merkle_root_sha256")},
        {_ts("created_at")}, {_ts("expires_at")}, {_ts_null("revoked_at")},
        stores_file_name INTEGER NOT NULL CHECK (stores_file_name = 0),
        stores_file_path INTEGER NOT NULL CHECK (stores_file_path = 0),
        PRIMARY KEY (organization_id, manifest_id),
        FOREIGN KEY (organization_id, owner_device_id)
            REFERENCES social_devices (organization_id, device_id),
        CHECK (expires_at > created_at)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_manifest_chunks (
        {_soc("organization_id")}, {_shr("manifest_id")},
        chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
        chunk_offset INTEGER NOT NULL CHECK (chunk_offset >= 0),
        chunk_bytes INTEGER NOT NULL CHECK (chunk_bytes > 0),
        {_digest("sha256")},
        PRIMARY KEY (organization_id, manifest_id, chunk_index),
        FOREIGN KEY (organization_id, manifest_id)
            REFERENCES social_file_manifests (organization_id, manifest_id)
            ON DELETE CASCADE
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_grants (
        {_soc("organization_id")}, {_shr("grant_id")}, {_shr("manifest_id")},
        {_soc("owner_account_id")}, {_soc("recipient_account_id")},
        {_enum("state", ("offered", "consented", "declined", "revoked", "expired"))},
        {_ts("offered_at")}, {_ts("expires_at")}, {_ts_null("decided_at")},
        {_ts_null("revoked_at")},
        explicit_recipient_consent INTEGER NOT NULL CHECK (explicit_recipient_consent IN (0, 1)),
        PRIMARY KEY (organization_id, grant_id),
        FOREIGN KEY (organization_id, manifest_id)
            REFERENCES social_file_manifests (organization_id, manifest_id),
        CHECK (owner_account_id <> recipient_account_id),
        CHECK ((state = 'consented') = (explicit_recipient_consent = 1)),
        CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_availability (
        {_soc("organization_id")}, {_shr("manifest_id")}, {_soc("owner_account_id")},
        {_soc("owner_device_id")}, {_enum("state", ("online", "offline"))},
        {_ts("observed_at")}, {_ts("expires_at")},
        direct_only INTEGER NOT NULL CHECK (direct_only = 1),
        PRIMARY KEY (organization_id, manifest_id),
        FOREIGN KEY (organization_id, manifest_id)
            REFERENCES social_file_manifests (organization_id, manifest_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_transfers (
        {_soc("organization_id")}, {_shr("transfer_id")}, {_shr("manifest_id")},
        {_shr("grant_id")}, {_soc("requester_account_id")}, {_soc("requester_device_id")},
        {_ts("created_at")}, {_ts("expires_at")},
        {_enum("state", ("queued_on_sender", "waiting_recipient_consent", "waiting_owner_approval", "negotiating_direct", "direct_ready", "transferring", "verifying", "completed", "failed", "cancelled", "revoked"))},
        failure_reason TEXT CHECK (
            failure_reason IS NULL
            OR (length(failure_reason) <= 40 AND failure_reason NOT GLOB '*[^a-z_]*')
        ),
        {_ts_null("owner_approved_at")}, {_ts("changed_at")},
        received_bytes INTEGER NOT NULL CHECK (received_bytes >= 0),
        {_digest_null("completed_whole_file_sha256")},
        relay_allowed INTEGER NOT NULL CHECK (relay_allowed = 0),
        cloud_byte_fallback_allowed INTEGER NOT NULL CHECK (cloud_byte_fallback_allowed = 0),
        remote_recall_guaranteed INTEGER NOT NULL CHECK (remote_recall_guaranteed = 0),
        PRIMARY KEY (organization_id, transfer_id),
        FOREIGN KEY (organization_id, manifest_id)
            REFERENCES social_file_manifests (organization_id, manifest_id),
        FOREIGN KEY (organization_id, grant_id)
            REFERENCES social_file_grants (organization_id, grant_id),
        CHECK ((state = 'failed') = (failure_reason IS NOT NULL)),
        CHECK ((state = 'completed') = (completed_whole_file_sha256 IS NOT NULL))
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_transfer_ranges (
        {_soc("organization_id")}, {_shr("transfer_id")},
        range_index INTEGER NOT NULL CHECK (range_index >= 0),
        range_start INTEGER NOT NULL CHECK (range_start >= 0),
        range_end_exclusive INTEGER NOT NULL CHECK (range_end_exclusive > range_start),
        PRIMARY KEY (organization_id, transfer_id, range_index),
        FOREIGN KEY (organization_id, transfer_id)
            REFERENCES social_file_transfers (organization_id, transfer_id)
            ON DELETE CASCADE
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_transfer_approvals (
        {_soc("organization_id")}, {_shr("transfer_id")}, {_shr("manifest_id")},
        {_soc("owner_account_id")}, {_soc("owner_device_id")}, {_ts("approved_at")},
        PRIMARY KEY (organization_id, transfer_id),
        FOREIGN KEY (organization_id, transfer_id)
            REFERENCES social_file_transfers (organization_id, transfer_id)
    ) STRICT
    """,
    f"""
    CREATE TABLE social_file_audit_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        {_soc("organization_id")}, {_shr("audit_id")}, {_soc("actor_account_id")},
        {_soc("actor_device_id")}, {_shr_null("manifest_id")}, {_shr_null("transfer_id")},
        action TEXT NOT NULL CHECK (length(action) <= 40 AND action NOT GLOB '*[^a-z_]*'),
        {_ts("occurred_at")},
        UNIQUE (organization_id, audit_id)
    ) STRICT
    """,
)

# Column names that must never appear in any social table.
FORBIDDEN_COLUMN_NAMES = frozenset(
    {
        "plaintext", "ciphertext", "ciphertext_bytes", "message_body", "message_text",
        "body", "text", "content", "attachment", "file_bytes", "bytes", "payload",
        "file_path", "absolute_path", "path", "file_name", "filename", "basename",
        "safe_basename", "ip", "ip_address", "ice_candidate", "candidate", "host",
        "port", "token", "credential", "password", "secret", "private_key",
        "public_key", "session_id", "project_id", "prompt_id", "analytics_user_id",
        "metric", "join_key", "email", "display_name",
    }
)

__all__ = ["FORBIDDEN_COLUMN_NAMES", "SOCIAL_SCHEMA_V2", "SOCIAL_SCHEMA_VERSION"]
