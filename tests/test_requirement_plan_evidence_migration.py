"""Append-only schema-55 migration checks for requirement-plan evidence."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

import pytest

from prompt_enhancer.database import SCHEMA_VERSION, Database, _apply_migration_atomically
from prompt_enhancer.infrastructure.sqlite import migrations

from test_declared_task_profile_migration import _create_v53


MIGRATION_54_FROZEN_SHA256 = (
    "aafd1c1cc0c121db267d02f7cf14c1a05e6a796af5affda2988fa700216576ac"
)
MIGRATION_55_FROZEN_SHA256 = (
    "c33be75cef513923f86796ec2fe6feb76216c26d3430384b78409d0c2b3f78a2"
)
NOW = datetime(2049, 10, 11, 12, 13, 14, tzinfo=UTC)
REQUIREMENT_PLAN_TABLES = (
    "requirement_plan_evidence_proposals",
    "requirement_plan_evidence_requirements",
    "requirement_plan_evidence_excluded_user_clauses",
    "requirement_plan_evidence_plans",
    "requirement_plan_evidence_links",
    "requirement_plan_evidence_proposal_seals",
    "requirement_plan_evidence_decisions",
    "requirement_plan_evidence_decision_authority_m56",
    "session_model_ensemble_requirement_plan_bindings",
    "session_model_ensemble_metric_states_v2_r6",
    "session_model_ensemble_metric_publication_v2_seals_r6",
)


def _create_v54(path, *, populated: bool) -> str:  # type: ignore[no-untyped-def]
    session_id = _create_v53(path, populated=populated)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _apply_migration_atomically(
            connection,
            version=54,
            script=migrations.MIGRATION_54,
            checksum=hashlib.sha256(migrations.MIGRATION_54.encode()).hexdigest(),
            applied_at=NOW.isoformat(timespec="microseconds"),
        )
    return session_id


def test_populated_v54_upgrades_to_v55_without_backfill_or_m54_drift(tmp_path) -> None:
    path = tmp_path / "populated-v54.sqlite3"
    session_id = _create_v54(path, populated=True)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[53][1] == MIGRATION_54_FROZEN_SHA256
        assert versions[54][1] == hashlib.sha256(
            migrations.MIGRATION_55.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT provider FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone() is not None
        for table in REQUIREMENT_PLAN_TABLES:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_v55_rolls_back_schema_ledger_and_user_version_together(tmp_path) -> None:
    path = tmp_path / "failed-v55.sqlite3"
    _create_v54(path, populated=False)
    broken = migrations.MIGRATION_55.replace(
        "\nCOMMIT;\n",
        "\nSELECT missing_requirement_plan_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_55

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=55,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 54
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 54
        for table in REQUIREMENT_PLAN_TABLES:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is None


def test_database_registry_appends_v55_after_byte_frozen_v54() -> None:
    assert SCHEMA_VERSION == 61
    assert hashlib.sha256(migrations.MIGRATION_54.encode()).hexdigest() == (
        MIGRATION_54_FROZEN_SHA256
    )
    assert hashlib.sha256(migrations.MIGRATION_55.encode()).hexdigest() == (
        MIGRATION_55_FROZEN_SHA256
    )
    assert "requirement_plan_evidence_proposals" not in migrations.MIGRATION_54
    assert "requirement_plan_evidence_proposals" in migrations.MIGRATION_55
    assert migrations.MIGRATION_55.count(
        "CHECK(requirement_count+excluded_user_clause_count<=1000)"
    ) == 2
    assert "non_requirement" not in migrations.MIGRATION_55
    assert "active-requirement-plan-review-rubric-v1" in migrations.MIGRATION_55
    requirement_plan_prefix = migrations.MIGRATION_55.split(
        "-- Projection r6 binds", maxsplit=1
    )[0]
    assert "owned_native_user_presence" in requirement_plan_prefix
    assert "authenticated_local_user" not in requirement_plan_prefix
