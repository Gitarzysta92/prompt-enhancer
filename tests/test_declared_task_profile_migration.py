"""Append-only schema-54 migration checks for reviewed task profiles."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

import pytest

from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    _MIGRATION_1,
    _apply_migration_atomically,
)
from prompt_enhancer.infrastructure.sqlite import migrations


MIGRATION_53_FROZEN_SHA256 = (
    "1a1ae1b18c8626b655b2425eab17300acc724dd5593e281fc6c0f257afbe6e42"
)
NOW = datetime(2048, 9, 10, 11, 12, 13, tzinfo=UTC)
PROFILE_TABLES = (
    "session_declared_task_profile_seals",
    "session_declared_task_profile_constraint_kinds",
    "session_declared_task_profile_deliverable_slots",
    "session_declared_task_profiles",
)


def _create_v53(path, *, populated: bool) -> str:
    """Build the exact public migration ledger through byte-frozen M53."""

    database = Database(path)
    database._prepare_private_path()
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 54)
    )
    timestamp = NOW.isoformat(timespec="microseconds")
    session_id = "3" * 64
    with database._connection() as connection:
        connection.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,
                   checksum TEXT NOT NULL,
                   applied_at TEXT NOT NULL
               )"""
        )
        connection.commit()
        for version, script in enumerate(scripts, start=1):
            _apply_migration_atomically(
                connection,
                version=version,
                script=script,
                checksum=hashlib.sha256(script.encode()).hexdigest(),
                applied_at=timestamp,
            )
        if populated:
            connection.execute(
                "INSERT INTO installations VALUES (?,?,?)",
                ("1" * 64, "codex", timestamp),
            )
            connection.execute(
                """INSERT INTO projects(
                       project_id,installation_id,provider,created_at
                   ) VALUES(?,?,?,?)""",
                ("2" * 64, "1" * 64, "codex", timestamp),
            )
            connection.execute(
                """INSERT INTO sessions(
                       session_id,installation_id,project_id,provider,
                       provider_version,adapter_version,source_schema_version,
                       started_at,ended_at,terminal_state,events_complete,
                       created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    "1" * 64,
                    "2" * 64,
                    "codex",
                    "synthetic-provider-v1",
                    "synthetic-adapter-v1",
                    "synthetic-schema-v1",
                    timestamp,
                    timestamp,
                    "completed",
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
    return session_id


def test_populated_v53_upgrades_to_v54_without_backfill_or_m53_drift(
    tmp_path,
) -> None:
    path = tmp_path / "populated-v53.sqlite3"
    session_id = _create_v53(path, populated=True)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[52][1] == MIGRATION_53_FROZEN_SHA256
        assert versions[53][1] == hashlib.sha256(
            migrations.MIGRATION_54.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT provider FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None
        for table in PROFILE_TABLES:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_v54_rolls_back_schema_ledger_and_user_version_together(
    tmp_path,
) -> None:
    path = tmp_path / "failed-v54.sqlite3"
    _create_v53(path, populated=False)
    broken = migrations.MIGRATION_54.replace(
        "\nCOMMIT;\n",
        "\nSELECT missing_declared_task_profile_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_54

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=54,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 53
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 53
        for table in PROFILE_TABLES:
            assert connection.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name=?""",
                (table,),
            ).fetchone() is None


def test_database_registry_appends_v54_after_byte_frozen_v53() -> None:
    assert SCHEMA_VERSION == 61
    assert hashlib.sha256(migrations.MIGRATION_53.encode()).hexdigest() == (
        MIGRATION_53_FROZEN_SHA256
    )
    assert "session_declared_task_profiles" not in migrations.MIGRATION_53
    assert "session_declared_task_profiles" in migrations.MIGRATION_54
