"""Append-only M60 checks for honest receiver-observed event timestamps."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

import pytest

from prompt_enhancer.database import SCHEMA_VERSION, Database, _apply_migration_atomically
from prompt_enhancer.infrastructure.sqlite import migrations

from test_requirement_verification_run_binding_migration import _create_v58


NOW = datetime(2053, 4, 5, 6, 7, 8, tzinfo=UTC)
MIGRATION_59_FROZEN_SHA256 = (
    "b80cd3e4073504d827e2ab917be2aa7ca72133561a9d204d5f683ef3fbb2865a"
)
EVENT_ID = "4" * 64
RUN_ID = "7" * 64
METRIC_KEY = "synthetic.event.timing"


def _create_populated_v59(path) -> str:  # type: ignore[no-untyped-def]
    session_id = _create_v58(path, populated=True)
    timestamp = NOW.isoformat(timespec="microseconds")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _apply_migration_atomically(
            connection,
            version=59,
            script=migrations.MIGRATION_59,
            checksum=hashlib.sha256(migrations.MIGRATION_59.encode()).hexdigest(),
            applied_at=timestamp,
        )
        connection.execute(
            """INSERT INTO events(
                   event_id,session_id,kind,sequence,occurred_at,duration_ms,
                   success,tool_category,created_at,updated_at,time_basis
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                EVENT_ID,
                session_id,
                "usage",
                0,
                timestamp,
                None,
                None,
                None,
                timestamp,
                timestamp,
                "provider_reported",
            ),
        )
        connection.execute(
            """INSERT INTO usage_records(
                   event_id,input_tokens,cached_input_tokens,
                   cache_creation_tokens,output_tokens,reasoning_output_tokens,
                   total_tokens,model_id,provider_reported,counter_kind,scope
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (EVENT_ID, 11, 3, 2, 5, None, 18, "synthetic-model-v1", 1, "delta", "request"),
        )
        connection.execute(
            "INSERT INTO tasks(task_id,project_id,created_at) VALUES(?,?,?)",
            ("5" * 64, "2" * 64, timestamp),
        )
        connection.execute(
            """INSERT INTO task_revisions(
                   task_id,revision,task_type,lifecycle_state,
                   input_fingerprint,created_at
               ) VALUES(?,?,?,?,?,?)""",
            ("5" * 64, 1, "synthetic", "completed", "6" * 64, timestamp),
        )
        connection.execute(
            """INSERT INTO metric_definitions(
                   key,version,dimension,display_name,description,unit,source,
                   algorithm_version,definition_checksum
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                METRIC_KEY,
                1,
                "data_quality",
                "Synthetic event timing",
                "Synthetic migration evidence only.",
                "ratio",
                "deterministic",
                "synthetic-v1",
                "8" * 64,
            ),
        )
        connection.execute(
            """INSERT INTO analysis_runs(
                   run_id,task_id,task_revision,metric_pack_key,
                   metric_pack_version,data_tier,input_fingerprint,
                   metric_engine_version,redactor_version,schema_version,
                   started_at,finished_at,status,failure_code
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                RUN_ID,
                "5" * 64,
                1,
                "synthetic.metadata",
                1,
                "metadata",
                "9" * 64,
                "synthetic-engine-v1",
                "synthetic-redactor-v1",
                1,
                timestamp,
                timestamp,
                "completed",
                None,
            ),
        )
        connection.execute(
            """INSERT INTO analysis_results(
                   run_id,key,version,value_state,numeric_value,text_value,
                   unit,source,observed_count,eligible_count,coverage,confidence,
                   calculator_version,model_id,model_revision,tokenizer_id,
                   prompt_version,rubric_version,error_code,computed_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                RUN_ID,
                METRIC_KEY,
                1,
                "known",
                1.0,
                None,
                "ratio",
                "deterministic",
                1,
                1,
                1.0,
                1.0,
                "synthetic-calculator-v1",
                None,
                None,
                None,
                None,
                None,
                None,
                timestamp,
            ),
        )
        connection.execute(
            """INSERT INTO analysis_result_evidence(
                   run_id,key,version,event_id,ordinal
               ) VALUES(?,?,?,?,?)""",
            (RUN_ID, METRIC_KEY, 1, EVENT_ID, 0),
        )
        connection.commit()
    return session_id


def test_populated_v59_upgrades_to_v60_without_rewriting_old_event_provenance(
    tmp_path,
) -> None:
    path = tmp_path / "synthetic-populated-v59.sqlite3"
    session_id = _create_populated_v59(path)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        versions = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in versions) == tuple(range(1, 62))
        assert versions[58][1] == MIGRATION_59_FROZEN_SHA256
        assert versions[59][1] == hashlib.sha256(
            migrations.MIGRATION_60.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT session_id,time_basis FROM events WHERE event_id=?", (EVENT_ID,)
        ).fetchone() == (session_id, "provider_reported")
        assert connection.execute(
            """SELECT input_tokens,cached_input_tokens,output_tokens,
                      provider_reported,counter_kind,scope
               FROM usage_records WHERE event_id=?""",
            (EVENT_ID,),
        ).fetchone() == (11, 3, 5, 1, "delta", "request")
        assert connection.execute(
            """SELECT run_id,key,version,event_id,ordinal
               FROM analysis_result_evidence"""
        ).fetchone() == (RUN_ID, METRIC_KEY, 1, EVENT_ID, 0)
        event_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()[0]
        assert "receiver_observed" in event_sql
        connection.execute(
            """INSERT INTO events(
                   event_id,session_id,kind,sequence,occurred_at,duration_ms,
                   success,tool_category,created_at,updated_at,time_basis
               ) SELECT ?,session_id,'turn_start',1,occurred_at,NULL,NULL,NULL,
                        created_at,updated_at,'receiver_observed'
                 FROM events WHERE event_id=?""",
            ("a" * 64, EVENT_ID),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO events(
                       event_id,session_id,kind,sequence,occurred_at,duration_ms,
                       success,tool_category,created_at,updated_at,time_basis
                   ) SELECT ?,session_id,'turn_end',2,occurred_at,NULL,NULL,NULL,
                            created_at,updated_at,'synthetic_invalid_basis'
                     FROM events WHERE event_id=?""",
                ("b" * 64, EVENT_ID),
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_m60_rolls_back_table_graph_and_migration_ledger(tmp_path) -> None:
    path = tmp_path / "synthetic-failed-v60.sqlite3"
    session_id = _create_populated_v59(path)
    broken = migrations.MIGRATION_60.replace(
        "\nCOMMIT;\n",
        "\nSELECT synthetic_missing_m60_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_60

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=60,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 59
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 59
        assert connection.execute(
            "SELECT session_id,time_basis FROM events WHERE event_id=?", (EVENT_ID,)
        ).fetchone() == (session_id, "provider_reported")
        assert connection.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE '%_v59'"""
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
