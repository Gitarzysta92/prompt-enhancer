"""Durable local metadata store for the optional paid-product boundary.

The database is deliberately separate from ``metrics.sqlite3`` and never has a
column for prompts, transcript text, provider credentials, payment-card data,
or approved payload bytes.  It persists only the closed Pydantic receipts from
``application.paid_product``.  Runtime composition remains default-off.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
from pathlib import Path
import sqlite3
from threading import RLock, get_ident
from types import TracebackType
from typing import Iterator, TypeVar

from pydantic import BaseModel

from ...application.paid_product.contracts import (
    Account,
    AccountIdentityBinding,
    ApprovalState,
    DeepAnalysisJob,
    DeepJobState,
    EntitlementFeature,
    EntitlementLedgerEntry,
    OrganizationSpendPolicy,
    PaidAuditEvent,
    RemoteAnalysisApproval,
    SpendHold,
    SpendHoldState,
    SpendPolicy,
    TenantAccountBinding,
)
from ...config import lexical_absolute_path, path_has_symlink_component
from ...sqlite_migration_integrity import (
    SqliteMigrationIntegrity,
    SqliteMigrationIntegrityError,
)


PAID_PRODUCT_DATABASE_FILENAME = "paid-product.sqlite3"
PAID_PRODUCT_SCHEMA_VERSION = 2
MINIMUM_SQLITE_VERSION = (3, 37, 0)

_T = TypeVar("_T", bound=BaseModel)


_SCHEMA_V1 = (
    """
    CREATE TABLE paid_identity_nonces (
        issuer_id TEXT NOT NULL,
        nonce_id TEXT NOT NULL,
        consumed_at TEXT NOT NULL,
        PRIMARY KEY (issuer_id, nonce_id)
    ) STRICT
    """,
    """
    CREATE TABLE paid_accounts (
        account_id TEXT PRIMARY KEY,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384)
    ) STRICT
    """,
    """
    CREATE TABLE paid_identity_bindings (
        issuer_id TEXT NOT NULL,
        subject_pseudonym TEXT NOT NULL,
        account_id TEXT NOT NULL UNIQUE,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (issuer_id, subject_pseudonym),
        FOREIGN KEY (account_id) REFERENCES paid_accounts(account_id)
    ) STRICT
    """,
    """
    CREATE TABLE paid_tenant_bindings (
        organization_id TEXT NOT NULL,
        account_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (organization_id, account_id),
        UNIQUE (organization_id, user_id),
        FOREIGN KEY (account_id) REFERENCES paid_accounts(account_id)
    ) STRICT
    """,
    """
    CREATE TABLE paid_webhook_fences (
        provider_event_id TEXT PRIMARY KEY,
        provider_event_digest TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE paid_entitlement_ledger (
        organization_id TEXT NOT NULL,
        entry_id TEXT NOT NULL,
        provider_event_id TEXT NOT NULL UNIQUE,
        ledger_sequence INTEGER NOT NULL CHECK (ledger_sequence > 0),
        feature TEXT NOT NULL,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (organization_id, entry_id),
        UNIQUE (organization_id, ledger_sequence),
        FOREIGN KEY (provider_event_id)
            REFERENCES paid_webhook_fences(provider_event_id)
    ) STRICT
    """,
    """
    CREATE INDEX paid_entitlement_projection_idx
        ON paid_entitlement_ledger(organization_id, feature, ledger_sequence)
    """,
    """
    CREATE TABLE paid_user_spend_policies (
        organization_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (organization_id, user_id)
    ) STRICT
    """,
    """
    CREATE TABLE paid_organization_spend_policies (
        organization_id TEXT PRIMARY KEY,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384)
    ) STRICT
    """,
    """
    CREATE TABLE paid_spend_holds (
        organization_id TEXT NOT NULL,
        hold_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        job_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (
            state IN ('held', 'settled', 'released', 'cost_unknown')
        ),
        settled_amount_micro INTEGER,
        settled_at TEXT,
        base_json TEXT NOT NULL CHECK (length(base_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (organization_id, hold_id),
        UNIQUE (organization_id, job_id),
        CHECK (
            (state IN ('held', 'cost_unknown')
                AND settled_amount_micro IS NULL AND settled_at IS NULL)
            OR (state = 'released'
                AND settled_amount_micro IS NULL AND settled_at IS NOT NULL)
            OR (state = 'settled'
                AND settled_amount_micro IS NOT NULL AND settled_at IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE INDEX paid_spend_holds_tenant_user_idx
        ON paid_spend_holds(organization_id, user_id, state)
    """,
    """
    CREATE TABLE paid_remote_approvals (
        organization_id TEXT NOT NULL,
        approval_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('available', 'consumed', 'revoked')),
        consumed_at TEXT,
        base_json TEXT NOT NULL CHECK (length(base_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (organization_id, approval_id),
        CHECK (
            (state = 'consumed' AND consumed_at IS NOT NULL)
            OR (state IN ('available', 'revoked') AND consumed_at IS NULL)
        )
    ) STRICT
    """,
    """
    CREATE TABLE paid_deep_analysis_jobs (
        organization_id TEXT NOT NULL,
        job_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (
            state IN ('queued', 'completed', 'failed', 'cancelled', 'cost_unknown')
        ),
        base_json TEXT NOT NULL CHECK (length(base_json) BETWEEN 2 AND 16384),
        terminal_json TEXT CHECK (
            terminal_json IS NULL OR length(terminal_json) BETWEEN 2 AND 16384
        ),
        PRIMARY KEY (organization_id, job_id),
        CHECK (
            (state = 'queued' AND terminal_json IS NULL)
            OR (state != 'queued' AND terminal_json IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE TABLE paid_audit_events (
        organization_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        body_json TEXT NOT NULL CHECK (length(body_json) BETWEEN 2 AND 16384),
        PRIMARY KEY (organization_id, event_id)
    ) STRICT
    """,
    """
    CREATE INDEX paid_audit_events_tenant_idx
        ON paid_audit_events(organization_id, event_id)
    """,
    """
    CREATE TRIGGER paid_identity_nonces_no_update
    BEFORE UPDATE ON paid_identity_nonces
    BEGIN SELECT RAISE(ABORT, 'paid_identity_nonce_immutable'); END
    """,
    """
    CREATE TRIGGER paid_identity_nonces_no_delete
    BEFORE DELETE ON paid_identity_nonces
    BEGIN SELECT RAISE(ABORT, 'paid_identity_nonce_immutable'); END
    """,
    """
    CREATE TRIGGER paid_webhook_fences_no_update
    BEFORE UPDATE ON paid_webhook_fences
    BEGIN SELECT RAISE(ABORT, 'paid_webhook_fence_immutable'); END
    """,
    """
    CREATE TRIGGER paid_webhook_fences_no_delete
    BEFORE DELETE ON paid_webhook_fences
    BEGIN SELECT RAISE(ABORT, 'paid_webhook_fence_immutable'); END
    """,
    """
    CREATE TRIGGER paid_entitlement_ledger_no_update
    BEFORE UPDATE ON paid_entitlement_ledger
    BEGIN SELECT RAISE(ABORT, 'paid_entitlement_immutable'); END
    """,
    """
    CREATE TRIGGER paid_entitlement_ledger_no_delete
    BEFORE DELETE ON paid_entitlement_ledger
    BEGIN SELECT RAISE(ABORT, 'paid_entitlement_immutable'); END
    """,
    """
    CREATE TRIGGER paid_audit_events_no_update
    BEFORE UPDATE ON paid_audit_events
    BEGIN SELECT RAISE(ABORT, 'paid_audit_immutable'); END
    """,
    """
    CREATE TRIGGER paid_audit_events_no_delete
    BEFORE DELETE ON paid_audit_events
    BEGIN SELECT RAISE(ABORT, 'paid_audit_immutable'); END
    """,
    """
    CREATE TRIGGER paid_accounts_immutable
    BEFORE UPDATE ON paid_accounts
    BEGIN SELECT RAISE(ABORT, 'paid_account_immutable'); END
    """,
    """
    CREATE TRIGGER paid_accounts_no_delete
    BEFORE DELETE ON paid_accounts
    BEGIN SELECT RAISE(ABORT, 'paid_account_immutable'); END
    """,
    """
    CREATE TRIGGER paid_identity_bindings_immutable
    BEFORE UPDATE ON paid_identity_bindings
    BEGIN SELECT RAISE(ABORT, 'paid_identity_binding_immutable'); END
    """,
    """
    CREATE TRIGGER paid_identity_bindings_no_delete
    BEFORE DELETE ON paid_identity_bindings
    BEGIN SELECT RAISE(ABORT, 'paid_identity_binding_immutable'); END
    """,
    """
    CREATE TRIGGER paid_tenant_bindings_immutable
    BEFORE UPDATE ON paid_tenant_bindings
    BEGIN SELECT RAISE(ABORT, 'paid_tenant_binding_immutable'); END
    """,
    """
    CREATE TRIGGER paid_tenant_bindings_no_delete
    BEFORE DELETE ON paid_tenant_bindings
    BEGIN SELECT RAISE(ABORT, 'paid_tenant_binding_immutable'); END
    """,
    """
    CREATE TRIGGER paid_user_spend_policies_no_delete
    BEFORE DELETE ON paid_user_spend_policies
    BEGIN SELECT RAISE(ABORT, 'paid_spend_policy_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER paid_organization_spend_policies_no_delete
    BEFORE DELETE ON paid_organization_spend_policies
    BEGIN SELECT RAISE(ABORT, 'paid_spend_policy_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER paid_spend_holds_no_delete
    BEFORE DELETE ON paid_spend_holds
    BEGIN SELECT RAISE(ABORT, 'paid_spend_hold_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER paid_remote_approvals_no_delete
    BEFORE DELETE ON paid_remote_approvals
    BEGIN SELECT RAISE(ABORT, 'paid_approval_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER paid_deep_analysis_jobs_no_delete
    BEFORE DELETE ON paid_deep_analysis_jobs
    BEGIN SELECT RAISE(ABORT, 'paid_job_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER paid_spend_holds_transition
    BEFORE UPDATE ON paid_spend_holds
    WHEN NEW.organization_id != OLD.organization_id
      OR NEW.hold_id != OLD.hold_id
      OR NEW.user_id != OLD.user_id
      OR NEW.job_id != OLD.job_id
      OR NEW.base_json != OLD.base_json
      OR NOT (
          (OLD.state = 'held' AND NEW.state IN ('settled', 'released', 'cost_unknown'))
          OR (OLD.state = 'cost_unknown' AND NEW.state IN ('settled', 'cost_unknown'))
      )
    BEGIN SELECT RAISE(ABORT, 'paid_spend_hold_transition_invalid'); END
    """,
    """
    CREATE TRIGGER paid_spend_holds_initial_state
    BEFORE INSERT ON paid_spend_holds
    WHEN NEW.state != 'held'
    BEGIN SELECT RAISE(ABORT, 'paid_spend_hold_initial_state_invalid'); END
    """,
    """
    CREATE TRIGGER paid_remote_approvals_transition
    BEFORE UPDATE ON paid_remote_approvals
    WHEN NEW.organization_id != OLD.organization_id
      OR NEW.approval_id != OLD.approval_id
      OR NEW.user_id != OLD.user_id
      OR NEW.base_json != OLD.base_json
      OR OLD.state != 'available'
      OR NEW.state NOT IN ('consumed', 'revoked')
    BEGIN SELECT RAISE(ABORT, 'paid_approval_transition_invalid'); END
    """,
    """
    CREATE TRIGGER paid_remote_approvals_initial_state
    BEFORE INSERT ON paid_remote_approvals
    WHEN NEW.state != 'available'
    BEGIN SELECT RAISE(ABORT, 'paid_approval_initial_state_invalid'); END
    """,
    """
    CREATE TRIGGER paid_deep_analysis_jobs_transition
    BEFORE UPDATE ON paid_deep_analysis_jobs
    WHEN NEW.organization_id != OLD.organization_id
      OR NEW.job_id != OLD.job_id
      OR NEW.user_id != OLD.user_id
      OR NEW.base_json != OLD.base_json
      OR OLD.state != 'queued'
      OR NEW.state NOT IN ('completed', 'failed', 'cancelled', 'cost_unknown')
    BEGIN SELECT RAISE(ABORT, 'paid_job_transition_invalid'); END
    """,
    """
    CREATE TRIGGER paid_deep_analysis_jobs_initial_state
    BEFORE INSERT ON paid_deep_analysis_jobs
    WHEN NEW.state != 'queued'
    BEGIN SELECT RAISE(ABORT, 'paid_job_initial_state_invalid'); END
    """,
)

_SCHEMA_V2 = (
    """
    CREATE TABLE paid_product_migration_checksums (
        version INTEGER PRIMARY KEY
            REFERENCES paid_product_schema_migrations(version) ON DELETE RESTRICT
            CHECK(version > 0),
        checksum TEXT NOT NULL CHECK(
            length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'
        )
    ) STRICT
    """,
)

_MIGRATIONS = (
    (1, _SCHEMA_V1),
    (2, _SCHEMA_V2),
)

_EXPECTED_PAID_TABLES = frozenset(
    {
        "paid_accounts",
        "paid_audit_events",
        "paid_deep_analysis_jobs",
        "paid_entitlement_ledger",
        "paid_identity_bindings",
        "paid_identity_nonces",
        "paid_organization_spend_policies",
        "paid_product_schema_migrations",
        "paid_product_migration_checksums",
        "paid_remote_approvals",
        "paid_spend_holds",
        "paid_tenant_bindings",
        "paid_user_spend_policies",
        "paid_webhook_fences",
    }
)

_MIGRATION_INTEGRITY = SqliteMigrationIntegrity(
    scope="paid_product",
    ledger_table="paid_product_schema_migrations",
    checksum_table="paid_product_migration_checksums",
    schema_version=PAID_PRODUCT_SCHEMA_VERSION,
    checksum_introduced_version=2,
    migrations=_MIGRATIONS,
    application_tables=frozenset(
        _EXPECTED_PAID_TABLES
        - {"paid_product_schema_migrations", "paid_product_migration_checksums"}
    ),
)
_EXPECTED_PAID_TRIGGERS = frozenset(
    {
        "paid_accounts_immutable",
        "paid_accounts_no_delete",
        "paid_audit_events_no_delete",
        "paid_audit_events_no_update",
        "paid_deep_analysis_jobs_initial_state",
        "paid_deep_analysis_jobs_no_delete",
        "paid_deep_analysis_jobs_transition",
        "paid_entitlement_ledger_no_delete",
        "paid_entitlement_ledger_no_update",
        "paid_identity_bindings_immutable",
        "paid_identity_bindings_no_delete",
        "paid_identity_nonces_no_delete",
        "paid_identity_nonces_no_update",
        "paid_organization_spend_policies_no_delete",
        "paid_remote_approvals_initial_state",
        "paid_remote_approvals_no_delete",
        "paid_remote_approvals_transition",
        "paid_spend_holds_initial_state",
        "paid_spend_holds_no_delete",
        "paid_spend_holds_transition",
        "paid_tenant_bindings_immutable",
        "paid_tenant_bindings_no_delete",
        "paid_user_spend_policies_no_delete",
        "paid_webhook_fences_no_delete",
        "paid_webhook_fences_no_update",
    }
)


def _normalized_sql(value: str) -> str:
    return " ".join(value.casefold().split())


_EXPECTED_PAID_TABLE_SQL = {
    statement.split()[2]: _normalized_sql(statement)
    for statement in _SCHEMA_V1
    if statement.lstrip().startswith("CREATE TABLE ")
}
_EXPECTED_PAID_TRIGGER_SQL = {
    statement.split()[2]: _normalized_sql(statement)
    for statement in _SCHEMA_V1
    if statement.lstrip().startswith("CREATE TRIGGER ")
}
_EXPECTED_PAID_INDEX_SQL = {
    statement.split()[2]: _normalized_sql(statement)
    for statement in _SCHEMA_V1
    if statement.lstrip().startswith("CREATE INDEX ")
}


@dataclass(slots=True)
class PaidProductSqliteStore:
    """One SQLite-backed transaction/store implementation for the paid ports."""

    path: Path
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _connection: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _owner_thread: int | None = field(default=None, init=False, repr=False)

    @classmethod
    def under(cls, app_home: Path) -> PaidProductSqliteStore:
        return cls(
            path=lexical_absolute_path(app_home) / PAID_PRODUCT_DATABASE_FILENAME
        )

    def _validated_path(self) -> Path:
        candidate = lexical_absolute_path(self.path)
        if candidate.name != PAID_PRODUCT_DATABASE_FILENAME:
            raise ValueError("paid-product database must use its dedicated filename")
        if path_has_symlink_component(candidate.parent):
            raise ValueError("paid-product database parent contains a link or reparse point")
        if path_has_symlink_component(candidate):
            raise ValueError("paid-product database is a link or reparse point")
        return candidate

    def _validated_existing_path(self) -> Path:
        candidate = self._validated_path()
        if not candidate.is_file():
            raise RuntimeError("paid_product_database_not_initialized")
        return candidate

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute("PRAGMA synchronous = FULL")

    @staticmethod
    def _verify_structure(connection: sqlite3.Connection) -> None:
        table_rows = tuple(
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type = 'table'
                """
            )
        )
        tables = frozenset(name for name, _sql in table_rows)
        table_sql = {
            name: _normalized_sql(sql)
            for name, sql in table_rows
            if name in _MIGRATION_INTEGRITY.application_tables
        }
        trigger_rows = tuple(
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type = 'trigger'
                """
            )
        )
        triggers = frozenset(name for name, _sql in trigger_rows)
        trigger_sql = {
            name: _normalized_sql(sql) for name, sql in trigger_rows
        }
        index_sql = {
            str(row[0]): _normalized_sql(str(row[1]))
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type = 'index' AND sql IS NOT NULL
                """
            )
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        if (
            tables != _EXPECTED_PAID_TABLES
            or table_sql != _EXPECTED_PAID_TABLE_SQL
            or triggers != _EXPECTED_PAID_TRIGGERS
            or trigger_sql != _EXPECTED_PAID_TRIGGER_SQL
            or index_sql != _EXPECTED_PAID_INDEX_SQL
            or integrity != ("ok",)
            or foreign
        ):
            raise RuntimeError("paid_product_schema_integrity_invalid")
        _MIGRATION_INTEGRITY.validate(
            connection,
            database_version=int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
            allow_legacy_zero_head=False,
        )

    def initialize(self) -> int:
        if sqlite3.sqlite_version_info < MINIMUM_SQLITE_VERSION:
            raise RuntimeError("paid_product_sqlite_version_unsupported")
        path = self._validated_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path_has_symlink_component(path.parent) or path_has_symlink_component(path):
            raise ValueError("paid-product database path changed during initialization")
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        for optional_flag in ("O_BINARY", "O_NOINHERIT", "O_NOFOLLOW"):
            flags |= int(getattr(os, optional_flag, 0))
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        if path_has_symlink_component(path) or not path.is_file():
            raise ValueError("paid-product database path changed during creation")
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            self._configure(connection)
            connection.execute("BEGIN IMMEDIATE")
            database_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if not _MIGRATION_INTEGRITY.table_exists(
                connection,
                "paid_product_schema_migrations",
            ):
                if database_version != 0:
                    raise _MIGRATION_INTEGRITY.error("schema_version_mismatch")
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                        """
                    ).fetchall()
                }
                if tables:
                    raise _MIGRATION_INTEGRITY.error(
                        "migration_history_incomplete"
                    )
                _MIGRATION_INTEGRITY.create_ledger(connection)
            current = _MIGRATION_INTEGRITY.validate(
                connection,
                database_version=database_version,
                allow_legacy_zero_head=True,
            )
            _MIGRATION_INTEGRITY.apply_pending(
                connection,
                current=current,
                applied_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            )
            self._verify_structure(connection)
            connection.execute("COMMIT")
        except Exception as error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if (
                isinstance(error, SqliteMigrationIntegrityError)
                and error.code == "paid_product_schema_newer"
            ):
                raise RuntimeError(
                    "paid-product database schema is newer than this build"
                ) from None
            raise
        finally:
            connection.close()
        try:
            os.chmod(path, 0o600)
        except OSError:
            # The signed Windows installer owns the stronger ACL gate.
            pass
        if path_has_symlink_component(path):
            raise ValueError("paid-product database changed into a link or reparse point")
        return PAID_PRODUCT_SCHEMA_VERSION

    def __enter__(self) -> None:
        if not self._lock.acquire(timeout=5.0):
            raise RuntimeError("paid_product_transaction_busy")
        connection: sqlite3.Connection | None = None
        try:
            if self._connection is not None:
                raise RuntimeError("paid_product_transaction_nested")
            connection = sqlite3.connect(
                self._validated_existing_path(), isolation_level=None, timeout=5.0
            )
            self._configure(connection)
            self._verify_structure(connection)
            connection.execute("BEGIN IMMEDIATE")
            self._connection = connection
            self._owner_thread = get_ident()
        except Exception:
            if connection is not None:
                connection.close()
            self._lock.release()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        connection = self._connection
        if connection is None or self._owner_thread != get_ident():
            raise RuntimeError("paid_product_transaction_owner_mismatch")
        transaction_error: RuntimeError | None = None
        try:
            if exc_type is None:
                if not connection.in_transaction:
                    transaction_error = RuntimeError(
                        "paid_product_transaction_lost"
                    )
                else:
                    try:
                        connection.execute("COMMIT")
                    except sqlite3.Error as error:
                        if connection.in_transaction:
                            try:
                                connection.execute("ROLLBACK")
                            except sqlite3.Error:
                                pass
                        transaction_error = RuntimeError(
                            "paid_product_transaction_commit_failed"
                        )
                        transaction_error.__cause__ = error
            elif connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    # Preserve the original application/domain exception.
                    pass
        finally:
            connection.close()
            self._connection = None
            self._owner_thread = None
            self._lock.release()
        if transaction_error is not None:
            raise transaction_error
        return None

    def _writer(self) -> sqlite3.Connection:
        if self._connection is None or self._owner_thread != get_ident():
            raise RuntimeError("paid_product_write_requires_transaction")
        if not self._connection.in_transaction:
            raise RuntimeError("paid_product_transaction_lost")
        return self._connection

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        if self._connection is not None and self._owner_thread == get_ident():
            if not self._connection.in_transaction:
                raise RuntimeError("paid_product_transaction_lost")
            yield self._connection
            return
        if not self._lock.acquire(timeout=5.0):
            raise RuntimeError("paid_product_transaction_busy")
        try:
            if self._connection is not None:
                raise RuntimeError("paid_product_transaction_owner_mismatch")
            connection = sqlite3.connect(
                self._validated_existing_path(), isolation_level=None, timeout=5.0
            )
            try:
                self._configure(connection)
                self._verify_structure(connection)
                yield connection
            finally:
                connection.close()
        finally:
            self._lock.release()

    @staticmethod
    def _body(value: BaseModel) -> str:
        return value.model_dump_json()

    @staticmethod
    def _parse(model: type[_T], body: str) -> _T:
        return model.model_validate_json(body)

    @classmethod
    def _parse_bound(
        cls,
        model: type[_T],
        body: str,
        **expected: object,
    ) -> _T:
        value = cls._parse(model, body)
        if any(getattr(value, key) != item for key, item in expected.items()):
            raise ValueError("paid_product_persisted_identity_mismatch")
        return value

    def nonce_consumed(self, issuer_id: str, nonce_id: str) -> bool:
        with self._reader() as connection:
            return connection.execute(
                "SELECT 1 FROM paid_identity_nonces WHERE issuer_id = ? AND nonce_id = ?",
                (issuer_id, nonce_id),
            ).fetchone() is not None

    def consume_nonce(self, issuer_id: str, nonce_id: str, *, at: datetime) -> None:
        try:
            self._writer().execute(
                "INSERT INTO paid_identity_nonces VALUES (?, ?, ?)",
                (issuer_id, nonce_id, at.isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_nonce_already_consumed") from exc

    def binding_by_subject(
        self, issuer_id: str, subject_pseudonym: str
    ) -> AccountIdentityBinding | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT account_id, body_json FROM paid_identity_bindings
                WHERE issuer_id = ? AND subject_pseudonym = ?
                """,
                (issuer_id, subject_pseudonym),
            ).fetchone()
        return None if row is None else self._parse_bound(
            AccountIdentityBinding,
            row[1],
            issuer_id=issuer_id,
            subject_pseudonym=subject_pseudonym,
            account_id=row[0],
        )

    def account(self, account_id: str) -> Account | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT body_json FROM paid_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return None if row is None else self._parse_bound(
            Account, row[0], account_id=account_id
        )

    def tenant_binding(
        self, organization_id: str, account_id: str
    ) -> TenantAccountBinding | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT user_id, body_json FROM paid_tenant_bindings
                WHERE organization_id = ? AND account_id = ?
                """,
                (organization_id, account_id),
            ).fetchone()
        return None if row is None else self._parse_bound(
            TenantAccountBinding,
            row[1],
            organization_id=organization_id,
            account_id=account_id,
            user_id=row[0],
        )

    def save_identity(
        self,
        account: Account,
        identity: AccountIdentityBinding,
        tenant: TenantAccountBinding,
    ) -> None:
        if account.account_id != identity.account_id or account.account_id != tenant.account_id:
            raise ValueError("paid_product_identity_graph_mismatch")
        connection = self._writer()
        try:
            connection.execute(
                "INSERT INTO paid_accounts VALUES (?, ?)",
                (account.account_id, self._body(account)),
            )
            connection.execute(
                "INSERT INTO paid_identity_bindings VALUES (?, ?, ?, ?)",
                (
                    identity.issuer_id,
                    identity.subject_pseudonym,
                    identity.account_id,
                    self._body(identity),
                ),
            )
            connection.execute(
                "INSERT INTO paid_tenant_bindings VALUES (?, ?, ?, ?)",
                (
                    tenant.organization_id,
                    tenant.account_id,
                    tenant.user_id,
                    self._body(tenant),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_identity_conflict") from exc

    def webhook_digest(self, provider_event_id: str) -> str | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT provider_event_digest FROM paid_webhook_fences
                WHERE provider_event_id = ?
                """,
                (provider_event_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def next_entitlement_sequence(self, organization_id: str) -> int:
        connection = self._writer()
        row = connection.execute(
            """
            SELECT COALESCE(MAX(ledger_sequence), 0) + 1
            FROM paid_entitlement_ledger WHERE organization_id = ?
            """,
            (organization_id,),
        ).fetchone()
        return int(row[0])

    def fence_webhook(self, provider_event_id: str, digest: str) -> None:
        try:
            self._writer().execute(
                "INSERT INTO paid_webhook_fences VALUES (?, ?)",
                (provider_event_id, digest),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_webhook_fence_conflict") from exc

    def append_entitlement(self, entry: EntitlementLedgerEntry) -> None:
        try:
            self._writer().execute(
                """
                INSERT INTO paid_entitlement_ledger(
                    organization_id, entry_id, provider_event_id,
                    ledger_sequence, feature, body_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.organization_id,
                    entry.entry_id,
                    entry.provider_event_id,
                    entry.ledger_sequence,
                    entry.feature.value,
                    self._body(entry),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_entitlement_conflict") from exc

    def entitlement_entries(
        self, organization_id: str, feature: EntitlementFeature
    ) -> tuple[EntitlementLedgerEntry, ...]:
        with self._reader() as connection:
            rows = connection.execute(
                """
                SELECT entry_id, provider_event_id, ledger_sequence, body_json
                FROM paid_entitlement_ledger
                WHERE organization_id = ? AND feature = ?
                ORDER BY ledger_sequence
                """,
                (organization_id, feature.value),
            ).fetchall()
        return tuple(
            self._parse_bound(
                EntitlementLedgerEntry,
                row[3],
                organization_id=organization_id,
                feature=feature,
                entry_id=row[0],
                provider_event_id=row[1],
                ledger_sequence=row[2],
            )
            for row in rows
        )

    def spend_policy(self, organization_id: str, user_id: str) -> SpendPolicy | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT body_json FROM paid_user_spend_policies
                WHERE organization_id = ? AND user_id = ?
                """,
                (organization_id, user_id),
            ).fetchone()
        return None if row is None else self._parse_bound(
            SpendPolicy,
            row[0],
            organization_id=organization_id,
            user_id=user_id,
        )

    def organization_spend_policy(
        self, organization_id: str
    ) -> OrganizationSpendPolicy | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT body_json FROM paid_organization_spend_policies
                WHERE organization_id = ?
                """,
                (organization_id,),
            ).fetchone()
        return None if row is None else self._parse_bound(
            OrganizationSpendPolicy,
            row[0],
            organization_id=organization_id,
        )

    def save_spend_policy(self, policy: SpendPolicy) -> None:
        self._writer().execute(
            """
            INSERT INTO paid_user_spend_policies VALUES (?, ?, ?)
            ON CONFLICT(organization_id, user_id)
            DO UPDATE SET body_json = excluded.body_json
            """,
            (policy.organization_id, policy.user_id, self._body(policy)),
        )

    def save_organization_spend_policy(
        self, policy: OrganizationSpendPolicy
    ) -> None:
        self._writer().execute(
            """
            INSERT INTO paid_organization_spend_policies VALUES (?, ?)
            ON CONFLICT(organization_id)
            DO UPDATE SET body_json = excluded.body_json
            """,
            (policy.organization_id, self._body(policy)),
        )

    def spend_holds(self, organization_id: str) -> tuple[SpendHold, ...]:
        with self._reader() as connection:
            rows = connection.execute(
                """
                SELECT organization_id, hold_id, user_id, job_id, base_json,
                       state, settled_amount_micro, settled_at
                FROM paid_spend_holds
                WHERE organization_id = ? ORDER BY hold_id
                """,
                (organization_id,),
            ).fetchall()
        return tuple(self._spend_hold_from_row(row) for row in rows)

    def spend_hold(self, organization_id: str, hold_id: str) -> SpendHold | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT organization_id, hold_id, user_id, job_id, base_json,
                       state, settled_amount_micro, settled_at
                FROM paid_spend_holds
                WHERE organization_id = ? AND hold_id = ?
                """,
                (organization_id, hold_id),
            ).fetchone()
        return None if row is None else self._spend_hold_from_row(row)

    def _spend_hold_from_row(self, row: tuple[object, ...]) -> SpendHold:
        base = self._parse_bound(
            SpendHold,
            str(row[4]),
            organization_id=row[0],
            hold_id=row[1],
            user_id=row[2],
            job_id=row[3],
        )
        if base.state is not SpendHoldState.HELD:
            raise ValueError("paid_product_spend_hold_base_invalid")
        return SpendHold.model_validate(
            {
                **base.model_dump(),
                "state": str(row[5]),
                "settled_amount_micro": row[6],
                "settled_at": row[7],
            }
        )

    def save_spend_hold(self, hold: SpendHold) -> None:
        connection = self._writer()
        existing = connection.execute(
            """
            SELECT organization_id, hold_id, user_id, job_id, base_json,
                   state, settled_amount_micro, settled_at
            FROM paid_spend_holds
            WHERE organization_id = ? AND hold_id = ?
            """,
            (hold.organization_id, hold.hold_id),
        ).fetchone()
        if existing is None:
            if hold.state is not SpendHoldState.HELD:
                raise ValueError("paid_product_spend_hold_initial_state_invalid")
            connection.execute(
                "INSERT INTO paid_spend_holds VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    hold.organization_id,
                    hold.hold_id,
                    hold.user_id,
                    hold.job_id,
                    hold.state.value,
                    None,
                    None,
                    self._body(hold),
                ),
            )
            return
        prior = self._spend_hold_from_row(existing)
        if (
            prior.user_id != hold.user_id
            or prior.job_id != hold.job_id
            or prior.amount_micro != hold.amount_micro
            or prior.created_at != hold.created_at
        ):
            raise ValueError("paid_product_spend_hold_identity_mismatch")
        try:
            connection.execute(
                """
                UPDATE paid_spend_holds
                SET state = ?, settled_amount_micro = ?, settled_at = ?
                WHERE organization_id = ? AND hold_id = ?
                """,
                (
                    hold.state.value,
                    hold.settled_amount_micro,
                    None if hold.settled_at is None else hold.settled_at.isoformat(),
                    hold.organization_id,
                    hold.hold_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_spend_hold_transition_invalid") from exc

    def approval(
        self, organization_id: str, approval_id: str
    ) -> RemoteAnalysisApproval | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT organization_id, approval_id, user_id, base_json,
                       state, consumed_at
                FROM paid_remote_approvals
                WHERE organization_id = ? AND approval_id = ?
                """,
                (organization_id, approval_id),
            ).fetchone()
        return None if row is None else self._approval_from_row(row)

    def _approval_from_row(self, row: tuple[object, ...]) -> RemoteAnalysisApproval:
        base = self._parse_bound(
            RemoteAnalysisApproval,
            str(row[3]),
            organization_id=row[0],
            approval_id=row[1],
            user_id=row[2],
        )
        if base.state is not ApprovalState.AVAILABLE:
            raise ValueError("paid_product_approval_base_invalid")
        return RemoteAnalysisApproval.model_validate(
            {
                **base.model_dump(),
                "state": str(row[4]),
                "consumed_at": row[5],
            }
        )

    def save_approval(self, approval: RemoteAnalysisApproval) -> None:
        connection = self._writer()
        row = connection.execute(
            """
            SELECT organization_id, approval_id, user_id, base_json,
                   state, consumed_at
            FROM paid_remote_approvals
            WHERE organization_id = ? AND approval_id = ?
            """,
            (approval.organization_id, approval.approval_id),
        ).fetchone()
        if row is None:
            if approval.state is not ApprovalState.AVAILABLE:
                raise ValueError("paid_product_approval_initial_state_invalid")
            connection.execute(
                "INSERT INTO paid_remote_approvals VALUES (?, ?, ?, ?, ?, ?)",
                (
                    approval.organization_id,
                    approval.approval_id,
                    approval.user_id,
                    approval.state.value,
                    None,
                    self._body(approval),
                ),
            )
            return
        prior = self._approval_from_row(row)
        identity_fields = (
            "user_id",
            "provider",
            "model_id",
            "window_fingerprint",
            "payload_pseudonym",
            "metric_keys",
            "redactor_version",
            "retention_class",
            "approved_payload_bytes",
            "max_cost_micro",
            "approved_at",
            "expires_at",
        )
        if any(getattr(prior, key) != getattr(approval, key) for key in identity_fields):
            raise ValueError("paid_product_approval_identity_mismatch")
        try:
            connection.execute(
                """
                UPDATE paid_remote_approvals SET state = ?, consumed_at = ?
                WHERE organization_id = ? AND approval_id = ?
                """,
                (
                    approval.state.value,
                    (
                        None
                        if approval.consumed_at is None
                        else approval.consumed_at.isoformat()
                    ),
                    approval.organization_id,
                    approval.approval_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_approval_transition_invalid") from exc

    def job(self, organization_id: str, job_id: str) -> DeepAnalysisJob | None:
        with self._reader() as connection:
            row = connection.execute(
                """
                SELECT organization_id, job_id, user_id, base_json,
                       state, terminal_json
                FROM paid_deep_analysis_jobs
                WHERE organization_id = ? AND job_id = ?
                """,
                (organization_id, job_id),
            ).fetchone()
        return None if row is None else self._job_from_row(row)

    def _job_from_row(self, row: tuple[object, ...]) -> DeepAnalysisJob:
        base = self._parse_bound(
            DeepAnalysisJob,
            str(row[3]),
            organization_id=row[0],
            job_id=row[1],
            user_id=row[2],
        )
        if base.state is not DeepJobState.QUEUED:
            raise ValueError("paid_product_job_base_invalid")
        state = DeepJobState(str(row[4]))
        if state is DeepJobState.QUEUED:
            if row[5] is not None:
                raise ValueError("paid_product_job_terminal_mismatch")
            return base
        if row[5] is None:
            raise ValueError("paid_product_job_terminal_missing")
        terminal = self._parse(DeepAnalysisJob, str(row[5]))
        if (
            terminal.state is not state
            or terminal.organization_id != base.organization_id
            or terminal.job_id != base.job_id
            or terminal.user_id != base.user_id
            or terminal.destination is not base.destination
            or terminal.model_id != base.model_id
            or terminal.metric_keys != base.metric_keys
            or terminal.requested_at != base.requested_at
        ):
            raise ValueError("paid_product_job_terminal_identity_mismatch")
        return terminal

    def save_job(self, job: DeepAnalysisJob) -> None:
        connection = self._writer()
        row = connection.execute(
            """
            SELECT organization_id, job_id, user_id, base_json,
                   state, terminal_json
            FROM paid_deep_analysis_jobs
            WHERE organization_id = ? AND job_id = ?
            """,
            (job.organization_id, job.job_id),
        ).fetchone()
        if row is None:
            if job.state is not DeepJobState.QUEUED:
                raise ValueError("paid_product_job_initial_state_invalid")
            connection.execute(
                "INSERT INTO paid_deep_analysis_jobs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.organization_id,
                    job.job_id,
                    job.user_id,
                    job.state.value,
                    self._body(job),
                    None,
                ),
            )
            return
        prior = self._job_from_row(row)
        if (
            prior.user_id != job.user_id
            or prior.destination is not job.destination
            or prior.model_id != job.model_id
            or prior.metric_keys != job.metric_keys
            or prior.requested_at != job.requested_at
        ):
            raise ValueError("paid_product_job_identity_mismatch")
        try:
            connection.execute(
                """
                UPDATE paid_deep_analysis_jobs SET state = ?, terminal_json = ?
                WHERE organization_id = ? AND job_id = ?
                """,
                (job.state.value, self._body(job), job.organization_id, job.job_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_job_transition_invalid") from exc

    def queued_jobs(self) -> tuple[DeepAnalysisJob, ...]:
        with self._reader() as connection:
            rows = connection.execute(
                """
                SELECT organization_id, job_id, user_id, base_json,
                       state, terminal_json
                FROM paid_deep_analysis_jobs
                WHERE state = 'queued'
                ORDER BY organization_id, job_id
                """
            ).fetchall()
        return tuple(self._job_from_row(row) for row in rows)

    def append_audit(self, event: PaidAuditEvent) -> None:
        try:
            self._writer().execute(
                "INSERT INTO paid_audit_events VALUES (?, ?, ?)",
                (event.organization_id, event.event_id, self._body(event)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("paid_product_audit_conflict") from exc

    def audit_for_tenant(self, organization_id: str) -> tuple[PaidAuditEvent, ...]:
        with self._reader() as connection:
            rows = connection.execute(
                """
                SELECT event_id, body_json FROM paid_audit_events
                WHERE organization_id = ? ORDER BY event_id
                """,
                (organization_id,),
            ).fetchall()
        return tuple(
            self._parse_bound(
                PaidAuditEvent,
                row[1],
                organization_id=organization_id,
                event_id=row[0],
            )
            for row in rows
        )

    def structural_check(self) -> bool:
        """Check schema/trigger/FK structure, not hostile-file authenticity.

        The development adapter has no platform-vault key or receipt MAC. A
        process that can rewrite this local file can still forge a well-formed
        row. Production composition therefore remains structurally unavailable.
        """

        try:
            with self._reader() as connection:
                self._verify_structure(connection)
        except (RuntimeError, sqlite3.DatabaseError):
            return False
        return True


__all__ = [
    "PAID_PRODUCT_DATABASE_FILENAME",
    "PAID_PRODUCT_SCHEMA_VERSION",
    "PaidProductSqliteStore",
]
