"""Small fail-closed migration provenance contract for auxiliary SQLite stores.

The primary metrics database and Agent catalog keep their own historical
adapters.  This module gives smaller stores the same invariants without making
their user rows part of any checksum: exact contiguous versions, canonical SQL
checksums, and one matching ``PRAGMA user_version`` head.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import sqlite3
from types import MappingProxyType
from typing import Mapping


_SQL_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class SqliteMigrationIntegrityError(RuntimeError):
    """Fixed content-free refusal for an invalid auxiliary migration state."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_migration_checksum(statements: tuple[str, ...]) -> str:
    """Hash an exact statement list without depending on host line endings."""

    payload = json.dumps(
        tuple(statement.strip() for statement in statements),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class SqliteMigrationIntegrity:
    """Validate and apply one append-only auxiliary-store migration registry."""

    scope: str
    ledger_table: str
    checksum_table: str
    schema_version: int
    checksum_introduced_version: int
    migrations: tuple[tuple[int, tuple[str, ...]], ...]
    application_tables: frozenset[str]
    checksums: Mapping[int, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        identifiers = (
            self.scope,
            self.ledger_table,
            self.checksum_table,
            *self.application_tables,
        )
        if any(_SQL_IDENTIFIER.fullmatch(value) is None for value in identifiers):
            raise RuntimeError("sqlite_migration_contract_identifier_invalid")
        versions = tuple(version for version, _statements in self.migrations)
        if versions != tuple(range(1, self.schema_version + 1)):
            raise RuntimeError(f"{self.scope}_migration_registry_invalid")
        if not (1 <= self.checksum_introduced_version <= self.schema_version):
            raise RuntimeError(f"{self.scope}_migration_registry_invalid")
        if any(
            not statements or any(not statement.strip() for statement in statements)
            for _version, statements in self.migrations
        ):
            raise RuntimeError(f"{self.scope}_migration_registry_invalid")
        object.__setattr__(
            self,
            "checksums",
            MappingProxyType(
                {
                    version: canonical_migration_checksum(statements)
                    for version, statements in self.migrations
                }
            ),
        )

    def error(self, suffix: str) -> SqliteMigrationIntegrityError:
        return SqliteMigrationIntegrityError(f"{self.scope}_{suffix}")

    @staticmethod
    def table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
        return tuple(
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        )

    def create_ledger(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE {self.ledger_table} (
                version INTEGER PRIMARY KEY CHECK(version > 0),
                applied_at TEXT NOT NULL
            ) STRICT
            """
        )

    def adopt_legacy(
        self,
        connection: sqlite3.Connection,
        *,
        through_version: int,
        applied_at: str,
    ) -> None:
        """Record an already-verified exact legacy shape inside the transaction."""

        if not (1 <= through_version < self.checksum_introduced_version):
            raise self.error("migration_history_incomplete")
        if self.table_exists(connection, self.ledger_table):
            raise self.error("migration_history_incomplete")
        self.create_ledger(connection)
        connection.executemany(
            f"INSERT INTO {self.ledger_table}(version, applied_at) VALUES (?, ?)",
            tuple((version, applied_at) for version in range(1, through_version + 1)),
        )

    def validate(
        self,
        connection: sqlite3.Connection,
        *,
        database_version: int,
        allow_legacy_zero_head: bool = False,
    ) -> int:
        if not self.table_exists(connection, self.ledger_table):
            raise self.error("migration_history_incomplete")
        if self._columns(connection, self.ledger_table) != ("version", "applied_at"):
            raise self.error("migration_history_incomplete")
        try:
            versions = tuple(
                int(row[0])
                for row in connection.execute(
                    f"SELECT version FROM {self.ledger_table} ORDER BY version"
                ).fetchall()
            )
        except (TypeError, ValueError, sqlite3.Error):
            raise self.error("migration_history_incomplete") from None
        current = versions[-1] if versions else 0
        if current > self.schema_version or database_version > self.schema_version:
            raise self.error("schema_newer")
        if versions != tuple(range(1, current + 1)):
            raise self.error("migration_history_incomplete")
        legacy_zero_head = (
            allow_legacy_zero_head
            and database_version == 0
            and 0 < current < self.checksum_introduced_version
        )
        if database_version != current and not legacy_zero_head:
            raise self.error("schema_version_mismatch")

        checksum_exists = self.table_exists(connection, self.checksum_table)
        if current == 0:
            placeholders = ",".join("?" for _table in self.application_tables)
            application_table = connection.execute(
                f"""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN ({placeholders})
                LIMIT 1
                """,
                tuple(sorted(self.application_tables)),
            ).fetchone()
            if checksum_exists or application_table is not None:
                raise self.error("migration_history_incomplete")
            return current

        if current < self.checksum_introduced_version:
            if checksum_exists:
                raise self.error("migration_history_incomplete")
            return current
        if not checksum_exists:
            raise self.error("migration_checksum_mismatch")
        if self._columns(connection, self.checksum_table) != ("version", "checksum"):
            raise self.error("migration_checksum_mismatch")
        try:
            observed = {
                int(row[0]): str(row[1])
                for row in connection.execute(
                    f"SELECT version, checksum FROM {self.checksum_table} ORDER BY version"
                ).fetchall()
            }
        except (TypeError, ValueError, sqlite3.Error):
            raise self.error("migration_checksum_mismatch") from None
        expected = {version: self.checksums[version] for version in range(1, current + 1)}
        if observed != expected:
            raise self.error("migration_checksum_mismatch")
        return current

    def apply_pending(
        self,
        connection: sqlite3.Connection,
        *,
        current: int,
        applied_at: str,
    ) -> None:
        for version, statements in self.migrations:
            if version <= current:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                f"INSERT INTO {self.ledger_table}(version, applied_at) VALUES (?, ?)",
                (version, applied_at),
            )
            if version == self.checksum_introduced_version:
                connection.executemany(
                    f"INSERT INTO {self.checksum_table}(version, checksum) VALUES (?, ?)",
                    tuple(
                        (migration_version, self.checksums[migration_version])
                        for migration_version in range(1, version + 1)
                    ),
                )
            elif version > self.checksum_introduced_version:
                connection.execute(
                    f"INSERT INTO {self.checksum_table}(version, checksum) VALUES (?, ?)",
                    (version, self.checksums[version]),
                )
            current = version
        connection.execute(f"PRAGMA user_version={self.schema_version}")
        self.validate(
            connection,
            database_version=self.schema_version,
            allow_legacy_zero_head=False,
        )


__all__ = (
    "SqliteMigrationIntegrity",
    "SqliteMigrationIntegrityError",
    "canonical_migration_checksum",
)
