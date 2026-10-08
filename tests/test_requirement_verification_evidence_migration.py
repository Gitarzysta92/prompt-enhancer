"""Append-only M58 migration checks for requirement-verification evidence."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import inspect
import sqlite3

import pytest

from prompt_enhancer.database import SCHEMA_VERSION, Database, _apply_migration_atomically
from prompt_enhancer.infrastructure.sqlite import migrations

from test_requirement_action_evidence_migration import _create_v56


MIGRATION_57_FROZEN_SHA256 = (
    "862957517aecd544054c60f4a1d486a70ae97656bdf74c5252217ebf59887776"
)
NOW = datetime(2051, 2, 3, 4, 5, 6, tzinfo=UTC)
M58_TABLES = (
    "requirement_verification_opportunity_sets",
    "requirement_verification_opportunities",
    "requirement_verification_opportunity_set_seals",
    "requirement_verification_authority_records",
    "requirement_verification_result_receipt_refs",
    "requirement_verification_authority_record_seals",
)


def _create_v57(path, *, populated: bool) -> str:  # type: ignore[no-untyped-def]
    session_id = _create_v56(path, populated=populated)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _apply_migration_atomically(
            connection,
            version=57,
            script=migrations.MIGRATION_57,
            checksum=hashlib.sha256(migrations.MIGRATION_57.encode()).hexdigest(),
            applied_at=NOW.isoformat(timespec="microseconds"),
        )
    return session_id


def test_populated_v57_upgrades_to_v58_without_backfill_or_frozen_drift(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-populated-v57.sqlite3"
    session_id = _create_v57(path, populated=True)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[56][1] == MIGRATION_57_FROZEN_SHA256
        assert versions[57][1] == hashlib.sha256(
            migrations.MIGRATION_58.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT provider FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None
        for table in M58_TABLES:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_m58_rolls_back_schema_ledger_and_user_version_together(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-failed-v58.sqlite3"
    _create_v57(path, populated=True)
    broken = migrations.MIGRATION_58.replace(
        "\nCOMMIT;\n",
        "\nSELECT synthetic_missing_m58_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_58

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=58,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 57
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 57
        for table in M58_TABLES:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is None


def test_m58_tables_are_strict_content_free_and_append_only(tmp_path) -> None:
    path = tmp_path / "synthetic-m58-shape.sqlite3"
    Database(path).initialize()

    forbidden = {
        "prompt",
        "transcript",
        "content",
        "prose",
        "text",
        "path",
        "command_args",
        "tool_output",
        "provider_payload",
        "assistant_claim",
        "model_judgment",
    }
    with sqlite3.connect(path) as connection:
        for table in M58_TABLES:
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            assert sql.rstrip().endswith("STRICT")
            columns = {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({table})"  # noqa: S608 - closed constants
                ).fetchall()
            }
            assert not (columns & forbidden)
        triggers = {
            row[0]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='trigger' AND name LIKE 'requirement_verification_%'"""
            ).fetchall()
        }
        for table in M58_TABLES:
            assert f"{table}_no_update" in triggers
            assert f"{table}_privacy_delete_only" in triggers


def test_registry_appends_m58_after_byte_frozen_m57() -> None:
    source = inspect.getsource(migrations)
    assert SCHEMA_VERSION == 61
    assert hashlib.sha256(migrations.MIGRATION_57.encode()).hexdigest() == (
        MIGRATION_57_FROZEN_SHA256
    )
    assert source.index("MIGRATION_57 =") < source.index("MIGRATION_58 =")
    assert "CREATE TABLE" not in migrations.MIGRATION_57
    assert "requirement_verification_opportunity_sets" not in migrations.MIGRATION_57
    assert "requirement_verification_opportunity_sets" in migrations.MIGRATION_58
    assert "CHECK(opportunity_count BETWEEN 0 AND 1000)" in migrations.MIGRATION_58
    assert "CHECK(revision BETWEEN 1 AND 32000)" in migrations.MIGRATION_58
    assert "local_only INTEGER NOT NULL CHECK(local_only=1)" in migrations.MIGRATION_58
    assert "content_persisted INTEGER NOT NULL CHECK(content_persisted=0)" in (
        migrations.MIGRATION_58
    )
    for forbidden in (
        "prompt TEXT",
        "transcript TEXT",
        "provider_payload",
        "assistant_claim",
        "model_judgment",
        "tool_output",
    ):
        assert forbidden not in migrations.MIGRATION_58
