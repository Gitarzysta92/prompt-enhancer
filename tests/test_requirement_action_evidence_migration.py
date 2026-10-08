"""Append-only M55-to-M57 migration checks for reviewed action evidence."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import inspect
import sqlite3

import pytest

from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseInvariantError,
    _apply_migration_atomically,
)
from prompt_enhancer.infrastructure.sqlite import migrations

from test_requirement_plan_evidence_migration import _create_v54


MIGRATION_54_FROZEN_SHA256 = (
    "aafd1c1cc0c121db267d02f7cf14c1a05e6a796af5affda2988fa700216576ac"
)
MIGRATION_55_FROZEN_SHA256 = (
    "c33be75cef513923f86796ec2fe6feb76216c26d3430384b78409d0c2b3f78a2"
)
MIGRATION_56_FROZEN_SHA256 = (
    "c744325d82ef54d1349512ba7e833ed44db93db7364ca325ee4cf73cb0ec553f"
)
NOW = datetime(2050, 1, 2, 3, 4, 5, tzinfo=UTC)
M56_TABLES = (
    "requirement_action_evidence_proposals",
    "requirement_action_evidence_requirements",
    "requirement_action_evidence_candidates",
    "requirement_action_evidence_links",
    "requirement_action_evidence_proposal_seals",
    "requirement_action_evidence_decisions",
    "session_model_ensemble_requirement_action_bindings",
    "session_model_ensemble_metric_states_v2_r7",
    "session_model_ensemble_metric_publication_v2_seals_r7",
)


def _create_v55(path, *, populated: bool) -> str:  # type: ignore[no-untyped-def]
    session_id = _create_v54(path, populated=populated)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _apply_migration_atomically(
            connection,
            version=55,
            script=migrations.MIGRATION_55,
            checksum=hashlib.sha256(migrations.MIGRATION_55.encode()).hexdigest(),
            applied_at=NOW.isoformat(timespec="microseconds"),
        )
    return session_id


def _create_v56(path, *, populated: bool) -> str:  # type: ignore[no-untyped-def]
    session_id = _create_v55(path, populated=populated)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _apply_migration_atomically(
            connection,
            version=56,
            script=migrations.MIGRATION_56,
            checksum=hashlib.sha256(migrations.MIGRATION_56.encode()).hexdigest(),
            applied_at=NOW.isoformat(timespec="microseconds"),
        )
    return session_id


def test_populated_v55_upgrades_through_v57_without_frozen_byte_drift(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-populated-v55.sqlite3"
    session_id = _create_v55(path, populated=True)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[53][1] == MIGRATION_54_FROZEN_SHA256
        assert versions[54][1] == MIGRATION_55_FROZEN_SHA256
        assert versions[55][1] == MIGRATION_56_FROZEN_SHA256
        assert versions[56][1] == hashlib.sha256(
            migrations.MIGRATION_57.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT provider FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None
        for table in M56_TABLES:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_populated_v56_upgrades_to_v57_and_installs_only_graph_guards(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-populated-v56.sqlite3"
    session_id = _create_v56(path, populated=True)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[53][1] == MIGRATION_54_FROZEN_SHA256
        assert versions[54][1] == MIGRATION_55_FROZEN_SHA256
        assert versions[55][1] == MIGRATION_56_FROZEN_SHA256
        assert versions[56][1] == hashlib.sha256(
            migrations.MIGRATION_57.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT provider FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None
        assert tuple(
            row[0]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='trigger' AND name LIKE '%graph_state_exact_m57'
                   ORDER BY name"""
            ).fetchall()
        ) == (
            "session_metric_r6_plan_graph_state_exact_m57",
            "session_metric_r7_action_graph_state_exact_m57",
            "session_metric_r7_plan_graph_state_exact_m57",
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_m56_rolls_back_schema_ledger_and_user_version_together(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-failed-v56.sqlite3"
    _create_v55(path, populated=True)
    broken = migrations.MIGRATION_56.replace(
        "\nCOMMIT;\n",
        "\nSELECT synthetic_missing_m56_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_56

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=56,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 55
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 55
        for table in M56_TABLES:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is None


def test_failed_m57_rolls_back_graph_guards_ledger_and_version_together(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-failed-v57.sqlite3"
    _create_v56(path, populated=True)
    broken = migrations.MIGRATION_57.replace(
        "\nCOMMIT;\n",
        "\nSELECT synthetic_missing_m57_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_57

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=57,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 56
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 56
        assert connection.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='trigger' AND name LIKE '%graph_state_exact_m57'"""
        ).fetchone()[0] == 0


def test_migration_checksum_mismatch_fails_closed_before_m56(tmp_path) -> None:
    path = tmp_path / "synthetic-checksum-v55.sqlite3"
    _create_v55(path, populated=False)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=55",
            ("0" * 64,),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="checksum mismatch"):
        Database(path).initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 55
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 55


def test_database_registry_appends_m57_after_byte_frozen_m56() -> None:
    source = inspect.getsource(migrations)
    assert SCHEMA_VERSION == 61
    assert hashlib.sha256(migrations.MIGRATION_54.encode()).hexdigest() == (
        MIGRATION_54_FROZEN_SHA256
    )
    assert hashlib.sha256(migrations.MIGRATION_55.encode()).hexdigest() == (
        MIGRATION_55_FROZEN_SHA256
    )
    assert hashlib.sha256(migrations.MIGRATION_56.encode()).hexdigest() == (
        MIGRATION_56_FROZEN_SHA256
    )
    assert source.index("MIGRATION_54 =") < source.index("MIGRATION_55 =")
    assert source.index("MIGRATION_55 =") < source.index("MIGRATION_56 =")
    assert source.index("MIGRATION_56 =") < source.index("MIGRATION_57 =")
    assert "requirement_action_evidence_proposals" not in migrations.MIGRATION_55
    assert "requirement_action_evidence_proposals" in migrations.MIGRATION_56
    assert "owned_native_user_presence" in migrations.MIGRATION_56
    assert "decision_authority_fingerprint TEXT NOT NULL" in migrations.MIGRATION_56
    assert "reviewed_descriptor_set_fingerprint TEXT" in migrations.MIGRATION_56
    assert "requirement-action-review-rubric-v2" in migrations.MIGRATION_56
    assert "candidate_manifest_overflow" in migrations.MIGRATION_56
    assert "requirement-action-candidate-manifest-overflow-v1" in (
        migrations.MIGRATION_56
    )
    assert "candidate_source_incomplete" in migrations.MIGRATION_56
    assert "binding_invalid" in migrations.MIGRATION_56
    assert "requirement-action-binding-invalid-v1" in migrations.MIGRATION_56
    assert (
        "357ed7bbb833a8dfbd8f907e8309c363957460c6053d5b9d77d069bbbb7e55da"
        in migrations.MIGRATION_56
    )
    assert "requirement-action-candidate-source-incomplete-v1" in (
        migrations.MIGRATION_56
    )
    for forbidden_content_column in (
        "descriptor_text",
        "descriptor_prose",
        "command_args",
        "tool_output",
    ):
        assert forbidden_content_column not in migrations.MIGRATION_56
    for raw_claim_column in (
        "producer_id TEXT",
        "producer_version TEXT",
        "model_id TEXT",
    ):
        assert raw_claim_column not in migrations.MIGRATION_56
    assert migrations.MIGRATION_57.count("CREATE TRIGGER") == 3
    assert "CREATE TABLE" not in migrations.MIGRATION_57
    assert "CREATE INDEX" not in migrations.MIGRATION_57
    assert "session_metric_r6_plan_graph_state_exact_m57" in (
        migrations.MIGRATION_57
    )
    assert "session_metric_r7_plan_graph_state_exact_m57" in (
        migrations.MIGRATION_57
    )
    assert "session_metric_r7_action_graph_state_exact_m57" in (
        migrations.MIGRATION_57
    )
