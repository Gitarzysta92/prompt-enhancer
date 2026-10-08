"""Append-only M59 run-binding migration checks using synthetic identities."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import inspect
import sqlite3

import pytest

from prompt_enhancer.database import SCHEMA_VERSION, Database, _apply_migration_atomically
from prompt_enhancer.infrastructure.sqlite import migrations

from test_requirement_verification_evidence_migration import _create_v57


NOW = datetime(2052, 3, 4, 5, 6, 7, tzinfo=UTC)
MIGRATION_58_FROZEN_SHA256 = (
    "6556ee459d99859895d2a7924b4f6e0dbf5482fa845f7f57becadf69b365385e"
)
M59_TABLES = (
    "session_model_ensemble_requirement_verification_bindings",
    "session_model_ensemble_metric_states_v2_r8",
    "session_model_ensemble_metric_publication_v2_seals_r8",
)


def _create_v58(path, *, populated: bool) -> str:  # type: ignore[no-untyped-def]
    session_id = _create_v57(path, populated=populated)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _apply_migration_atomically(
            connection,
            version=58,
            script=migrations.MIGRATION_58,
            checksum=hashlib.sha256(migrations.MIGRATION_58.encode()).hexdigest(),
            applied_at=NOW.isoformat(timespec="microseconds"),
        )
    return session_id


def test_populated_v58_upgrades_to_v59_without_backfill_or_frozen_drift(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-populated-v58.sqlite3"
    session_id = _create_v58(path, populated=True)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[57][1] == MIGRATION_58_FROZEN_SHA256
        assert versions[58][1] == hashlib.sha256(
            migrations.MIGRATION_59.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT provider FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None
        for table in M59_TABLES:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_m59_rolls_back_schema_ledger_and_tables_together(tmp_path) -> None:
    path = tmp_path / "synthetic-failed-v59.sqlite3"
    _create_v58(path, populated=True)
    broken = migrations.MIGRATION_59.replace(
        "\nCOMMIT;\n",
        "\nSELECT synthetic_missing_m59_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_59

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=59,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 58
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 58
        for table in M59_TABLES:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is None


def test_m59_tables_are_strict_content_free_append_only_sidecars(tmp_path) -> None:
    path = tmp_path / "synthetic-m59-shape.sqlite3"
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
        for table in M59_TABLES:
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
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert "requirement_verification_objective_sequence_monotonic_m59" in triggers
        assert (
            "session_model_ensemble_requirement_verification_bindings_no_update"
            in triggers
        )
        assert "session_metric_r8_states_no_update" in triggers
        assert "session_metric_r8_seals_no_update" in triggers
        assert "session_metric_r8_states_exact" in triggers
        assert "session_metric_r8_seal_complete" in triggers


def test_registry_appends_m59_after_byte_frozen_m58() -> None:
    source = inspect.getsource(migrations)
    assert SCHEMA_VERSION == 61
    assert hashlib.sha256(migrations.MIGRATION_58.encode()).hexdigest() == (
        MIGRATION_58_FROZEN_SHA256
    )
    assert source.index("MIGRATION_58 =") < source.index("MIGRATION_59 =")
    assert "session_model_ensemble_metric_states_v2_r8" not in migrations.MIGRATION_58
    assert "session_model_ensemble_metric_states_v2_r8" in migrations.MIGRATION_59
    assert "projection_version='metric-contract-v2-projection-8'" in (
        migrations.MIGRATION_59
    )
    assert "product_metric_eligible INTEGER NOT NULL CHECK(product_metric_eligible=0)" in (
        migrations.MIGRATION_59
    )
    for forbidden in (
        "prompt TEXT",
        "transcript TEXT",
        "provider_payload",
        "assistant_claim",
        "model_judgment",
        "tool_output",
    ):
        assert forbidden not in migrations.MIGRATION_59
