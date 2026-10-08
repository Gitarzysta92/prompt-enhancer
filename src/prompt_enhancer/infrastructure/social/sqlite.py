"""Independent SQLite database boundary for local social/file metadata.

This module deliberately does not import the analyzer database, its migrations,
or its identifiers.  It owns ``social.sqlite3`` and a separate
``social_schema_migrations`` ledger.  Version 1 was a placeholder schema that
no adapter ever populated; version 2 installs the typed control-plane schema
used by the durable local adapters.  Durable multi-device synchronization,
backups and production identity remain unavailable. Version 3 adds migration
checksums and a matching SQLite schema head without changing social data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import sqlite3

from ...config import lexical_absolute_path, path_has_symlink_component
from ...sqlite_migration_integrity import SqliteMigrationIntegrity
from .sqlite_schema import SOCIAL_SCHEMA_V2, SOCIAL_SCHEMA_VERSION


SOCIAL_DATABASE_FILENAME = "social.sqlite3"

_SOCIAL_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS social_accounts (
    organization_id TEXT NOT NULL CHECK (
        length(organization_id) = 68 AND substr(organization_id, 1, 4) = 'soc_'
        AND substr(organization_id, 5) NOT GLOB '*[^0-9a-f]*'
    ),
    account_id TEXT NOT NULL CHECK (
        length(account_id) = 68 AND substr(account_id, 1, 4) = 'soc_'
        AND substr(account_id, 5) NOT GLOB '*[^0-9a-f]*'
    ),
    state TEXT NOT NULL CHECK (state IN ('active', 'suspended', 'deleted')),
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    PRIMARY KEY (organization_id, account_id)
) STRICT;

CREATE TABLE IF NOT EXISTS social_devices (
    organization_id TEXT NOT NULL CHECK (length(organization_id) = 68),
    device_id TEXT NOT NULL CHECK (
        length(device_id) = 68 AND substr(device_id, 1, 4) = 'soc_'
        AND substr(device_id, 5) NOT GLOB '*[^0-9a-f]*'
    ),
    account_id TEXT NOT NULL CHECK (length(account_id) = 68),
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
    signing_key_version INTEGER NOT NULL CHECK (signing_key_version > 0),
    agreement_key_version INTEGER NOT NULL CHECK (agreement_key_version > 0),
    signing_key_fingerprint TEXT NOT NULL CHECK (length(signing_key_fingerprint) = 64),
    agreement_key_fingerprint TEXT NOT NULL CHECK (length(agreement_key_fingerprint) = 64),
    enrolled_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (organization_id, device_id),
    FOREIGN KEY (organization_id, account_id)
        REFERENCES social_accounts (organization_id, account_id)
) STRICT;

CREATE TABLE IF NOT EXISTS social_relationship_metadata (
    organization_id TEXT NOT NULL CHECK (length(organization_id) = 68),
    relationship_id TEXT NOT NULL CHECK (length(relationship_id) = 68),
    first_account_id TEXT NOT NULL CHECK (length(first_account_id) = 68),
    second_account_id TEXT NOT NULL CHECK (length(second_account_id) = 68),
    relationship_kind TEXT NOT NULL CHECK (
        relationship_kind IN ('friend_request', 'friendship', 'block')
    ),
    lifecycle_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    changed_at TEXT,
    PRIMARY KEY (organization_id, relationship_id)
) STRICT;

CREATE TABLE IF NOT EXISTS social_conversation_metadata (
    organization_id TEXT NOT NULL CHECK (length(organization_id) = 68),
    conversation_id TEXT NOT NULL CHECK (length(conversation_id) = 68),
    conversation_kind TEXT NOT NULL CHECK (
        conversation_kind IN ('direct', 'private_group')
    ),
    current_key_version INTEGER NOT NULL CHECK (current_key_version > 0),
    invitation_only INTEGER NOT NULL CHECK (invitation_only = 1),
    discoverable INTEGER NOT NULL CHECK (discoverable = 0),
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, conversation_id)
) STRICT;

CREATE TABLE IF NOT EXISTS social_message_envelope_metadata (
    organization_id TEXT NOT NULL CHECK (length(organization_id) = 68),
    envelope_id TEXT NOT NULL CHECK (length(envelope_id) = 68),
    conversation_id TEXT NOT NULL CHECK (length(conversation_id) = 68),
    message_id TEXT NOT NULL CHECK (length(message_id) = 68),
    sender_account_id TEXT NOT NULL CHECK (length(sender_account_id) = 68),
    sender_device_id TEXT NOT NULL CHECK (length(sender_device_id) = 68),
    operation TEXT NOT NULL CHECK (operation IN ('create', 'edit', 'delete')),
    revision INTEGER NOT NULL CHECK (revision > 0),
    key_version INTEGER NOT NULL CHECK (key_version > 0),
    ciphertext_size INTEGER NOT NULL CHECK (ciphertext_size > 0),
    ciphertext_sha256 TEXT NOT NULL CHECK (length(ciphertext_sha256) = 64),
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, envelope_id),
    FOREIGN KEY (organization_id, conversation_id)
        REFERENCES social_conversation_metadata (organization_id, conversation_id)
) STRICT;

CREATE TABLE IF NOT EXISTS social_file_manifest_metadata (
    organization_id TEXT NOT NULL CHECK (length(organization_id) = 68),
    manifest_id TEXT NOT NULL CHECK (
        length(manifest_id) = 68 AND substr(manifest_id, 1, 4) = 'shr_'
        AND substr(manifest_id, 5) NOT GLOB '*[^0-9a-f]*'
    ),
    owner_account_id TEXT NOT NULL CHECK (length(owner_account_id) = 68),
    owner_device_id TEXT NOT NULL CHECK (length(owner_device_id) = 68),
    content_kind TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    chunk_size INTEGER NOT NULL CHECK (chunk_size > 0),
    whole_file_sha256 TEXT NOT NULL CHECK (length(whole_file_sha256) = 64),
    merkle_root_sha256 TEXT NOT NULL CHECK (length(merkle_root_sha256) = 64),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (organization_id, manifest_id)
) STRICT;

CREATE TABLE IF NOT EXISTS social_file_grant_metadata (
    organization_id TEXT NOT NULL CHECK (length(organization_id) = 68),
    grant_id TEXT NOT NULL CHECK (
        length(grant_id) = 68 AND substr(grant_id, 1, 4) = 'shr_'
        AND substr(grant_id, 5) NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_id TEXT NOT NULL CHECK (length(manifest_id) = 68),
    owner_account_id TEXT NOT NULL CHECK (length(owner_account_id) = 68),
    recipient_account_id TEXT NOT NULL CHECK (length(recipient_account_id) = 68),
    state TEXT NOT NULL CHECK (
        state IN ('offered', 'consented', 'declined', 'revoked', 'expired')
    ),
    offered_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    revoked_at TEXT,
    PRIMARY KEY (organization_id, grant_id),
    FOREIGN KEY (organization_id, manifest_id)
        REFERENCES social_file_manifest_metadata (organization_id, manifest_id)
) STRICT;
"""


_SOCIAL_SCHEMA_V3 = (
    """
    CREATE TABLE social_migration_checksums (
        version INTEGER PRIMARY KEY
            REFERENCES social_schema_migrations(version) ON DELETE RESTRICT
            CHECK(version > 0),
        checksum TEXT NOT NULL CHECK(
            length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'
        )
    ) STRICT
    """,
)


_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        tuple(
            statement
            for statement in _SOCIAL_SCHEMA_V1.split(";")
            if statement.strip()
        ),
    ),
    (2, SOCIAL_SCHEMA_V2),
    (3, _SOCIAL_SCHEMA_V3),
)

_SOCIAL_APPLICATION_TABLES = frozenset(
    match.group(1)
    for statement in SOCIAL_SCHEMA_V2
    if (
        match := re.search(
            r"\bCREATE TABLE(?: IF NOT EXISTS)?\s+([a-z][a-z0-9_]*)",
            statement,
            re.IGNORECASE,
        )
    )
    and match.group(1)
    not in {"social_schema_migrations", "social_migration_checksums"}
)

_MIGRATION_INTEGRITY = SqliteMigrationIntegrity(
    scope="social",
    ledger_table="social_schema_migrations",
    checksum_table="social_migration_checksums",
    schema_version=SOCIAL_SCHEMA_VERSION,
    checksum_introduced_version=3,
    migrations=_MIGRATIONS,
    application_tables=_SOCIAL_APPLICATION_TABLES,
)


def _normalized_schema_sql(value: str) -> str:
    return " ".join(value.casefold().split()).replace(
        "create table if not exists ", "create table ", 1
    )


_SOCIAL_EXPECTED_APPLICATION_SQL = {
    match.group(1): _normalized_schema_sql(statement)
    for statement in SOCIAL_SCHEMA_V2
    if (
        match := re.search(
            r"\bCREATE TABLE(?: IF NOT EXISTS)?\s+([a-z][a-z0-9_]*)",
            statement,
            re.IGNORECASE,
        )
    )
}
_SOCIAL_EXPECTED_TABLES = _SOCIAL_APPLICATION_TABLES | frozenset(
    {"social_schema_migrations", "social_migration_checksums"}
)
_SOCIAL_EXPECTED_TRIGGER_SQL = {
    match.group(1): _normalized_schema_sql(statement)
    for statement in SOCIAL_SCHEMA_V2
    if (
        match := re.search(
            r"\bCREATE TRIGGER\s+([a-z][a-z0-9_]*)",
            statement,
            re.IGNORECASE,
        )
    )
}


@dataclass(frozen=True, slots=True)
class SocialSqliteDatabase:
    path: Path

    @classmethod
    def under(cls, app_home: Path) -> SocialSqliteDatabase:
        return cls(path=lexical_absolute_path(app_home) / SOCIAL_DATABASE_FILENAME)

    def _validated_path(self) -> Path:
        candidate = lexical_absolute_path(self.path)
        if candidate.name != SOCIAL_DATABASE_FILENAME:
            raise ValueError("social database must use its dedicated filename")
        if path_has_symlink_component(candidate.parent):
            raise ValueError("social database parent contains a link or reparse point")
        if path_has_symlink_component(candidate):
            raise ValueError("social database is a link or reparse point")
        return candidate

    @staticmethod
    def _verify_structure(connection: sqlite3.Connection) -> None:
        table_rows = tuple(
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        )
        tables = frozenset(name for name, _sql in table_rows)
        application_sql = {
            name: _normalized_schema_sql(sql)
            for name, sql in table_rows
            if name in _SOCIAL_APPLICATION_TABLES
        }
        trigger_rows = tuple(
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        )
        trigger_sql = {
            name: _normalized_schema_sql(sql) for name, sql in trigger_rows
        }
        if (
            tables != _SOCIAL_EXPECTED_TABLES
            or application_sql != _SOCIAL_EXPECTED_APPLICATION_SQL
            or trigger_sql != _SOCIAL_EXPECTED_TRIGGER_SQL
            or connection.execute("PRAGMA integrity_check").fetchone() != ("ok",)
            or connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise RuntimeError("social_schema_integrity_invalid")
        _MIGRATION_INTEGRITY.validate(
            connection,
            database_version=int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
            allow_legacy_zero_head=False,
        )

    def initialize(self) -> int:
        path = self._validated_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path_has_symlink_component(path.parent):
            raise ValueError("social database parent changed during initialization")
        if path_has_symlink_component(path):
            raise ValueError("social database path is a link or reparse point")
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("BEGIN IMMEDIATE")
            database_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if not _MIGRATION_INTEGRITY.table_exists(
                connection,
                "social_schema_migrations",
            ):
                if database_version != 0:
                    raise _MIGRATION_INTEGRITY.error("schema_version_mismatch")
                existing = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                        """
                    ).fetchall()
                }
                if existing:
                    raise _MIGRATION_INTEGRITY.error(
                        "migration_history_incomplete"
                    )
                _MIGRATION_INTEGRITY.create_ledger(connection)
            current = _MIGRATION_INTEGRITY.validate(
                connection,
                database_version=database_version,
                allow_legacy_zero_head=True,
            )
            applied_at = datetime.now(UTC).replace(microsecond=0).isoformat()
            _MIGRATION_INTEGRITY.apply_pending(
                connection,
                current=current,
                applied_at=applied_at,
            )
            self._verify_structure(connection)
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        try:
            os.chmod(path, 0o600)
        except OSError:
            # Windows ACL enforcement belongs to an installer/platform adapter.
            pass
        if path_has_symlink_component(path):
            raise ValueError("social database changed into a link or reparse point")
        return SOCIAL_SCHEMA_VERSION

    def connect(self) -> sqlite3.Connection:
        """Open the initialized database for the durable local adapters."""

        self.initialize()
        path = self._validated_path()
        connection = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection


__all__ = [
    "SOCIAL_DATABASE_FILENAME",
    "SOCIAL_SCHEMA_VERSION",
    "SocialSqliteDatabase",
]
