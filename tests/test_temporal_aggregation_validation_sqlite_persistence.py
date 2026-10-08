from __future__ import annotations

from datetime import timedelta
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3

import pytest

from prompt_enhancer.application.history.aggregation import RawStratumDispositionV1
from prompt_enhancer.application.history.contracts import (
    TemporalWindowKind,
    TemporalWindowSpec,
)
from prompt_enhancer.database import (
    Database,
    DatabaseInvariantError,
    SCHEMA_VERSION,
    _MIGRATION_1,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.temporal_aggregation_validation import (
    SqliteTemporalSyntheticAggregationValidationRepository,
)
from prompt_enhancer.infrastructure.sqlite.tasks import SqliteTaskRepository
from prompt_enhancer.infrastructure.sqlite.temporal_history import _from_us
from tests import test_temporal_comparison_strata_sqlite_persistence as v22_sqlite
from tests.test_temporal_comparison_strata_sqlite_persistence import (
    BASE,
    _comparison_completion,
    _id,
)


def _sealed_context(tmp_path: Path):
    context = _comparison_completion(tmp_path)
    batch = context.runs.complete(
        context.prepared.expected_analysis_run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.temporal_request,
    )
    assert batch is not None
    sealed = context.comparison.get_sealed_stratum_for_run(
        context.prepared.expected_analysis_run_id
    )
    assert sealed is not None
    repository = context.database.temporal_synthetic_aggregation_validation_repository()
    return context, sealed, repository


def _window() -> TemporalWindowSpec:
    return TemporalWindowSpec(kind=TemporalWindowKind.LAST_N, last_n=3)


def _key(label: str) -> str:
    return hashlib.sha256(f"reserved-v23:{label}".encode("ascii")).hexdigest()


def test_issue_replay_and_getters_use_one_repository_clock(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    clock_calls = 0
    as_of = sealed.sealed_at + timedelta(microseconds=5)

    def clock():
        nonlocal clock_calls
        clock_calls += 1
        return as_of

    repository._clock = clock
    key = _key("one-clock")
    receipt = repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=key,
    )
    assert clock_calls == 1
    assert receipt.predicate.as_of == receipt.sealed_at == as_of
    assert receipt.enumeration.member_count == 1
    assert receipt.enumeration.ordered_members[0].sealed_stratum_id == (
        sealed.sealed_stratum_id
    )
    assert receipt.enumeration.ordered_members[0].disposition is (
        RawStratumDispositionV1.INCLUDED
    )
    assert repository.get_synthetic_aggregation_validation(
        receipt.validation_receipt_id
    ) == receipt
    assert repository.get_synthetic_aggregation_validation_for_idempotency(
        key
    ) == receipt

    repository._clock = lambda: (_ for _ in ()).throw(AssertionError("clock replay"))
    repository._comparison._hydrate_sealed_locked = lambda *args: (_ for _ in ()).throw(
        AssertionError("enumeration replay")
    )
    # Replay must find and compare the durable key binding before clock or a
    # fresh universe query. Hydration is still required to return the graph,
    # so restore only the trusted hydrator after proving clock is poisoned.
    repository._comparison = context.comparison
    assert repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=key,
    ) == receipt

    with context.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM synthetic_aggregation_validation_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM synthetic_aggregation_append_authorizations"
        ).fetchone()[0] == 0


def test_key_conflict_precedes_clock_and_enumeration(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    key = _key("conflict")
    repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=key,
    )
    repository._clock = lambda: (_ for _ in ()).throw(AssertionError("clock"))
    with pytest.raises(DatabaseInvariantError, match="idempotency key conflicts"):
        repository.validate_synthetic_aggregation(
            sealed.sealed_stratum_id,
            context.metric_key,
            TemporalWindowSpec(kind=TemporalWindowKind.ROLLING_DAYS, days=7),
            idempotency_key_sha256=key,
        )


def test_unselected_metric_is_rejected_before_clock(tmp_path) -> None:
    _, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: (_ for _ in ()).throw(AssertionError("clock"))
    with pytest.raises(DatabaseInvariantError, match="not selected by the anchor"):
        repository.validate_synthetic_aggregation(
            sealed.sealed_stratum_id,
            "reserved.unselected.metric",
            _window(),
            idempotency_key_sha256=_key("unselected"),
        )


def test_hydration_rederives_members_draft_and_outer_graph(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    receipt = repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=_key("tamper"),
    )
    with context.database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("DROP TRIGGER synthetic_aggregation_member_no_update")
        connection.execute(
            """UPDATE synthetic_aggregation_validation_members
               SET member_fingerprint=? WHERE validation_receipt_id=?""",
            (_key("forged-member"), receipt.validation_receipt_id),
        )
        connection.commit()
        connection.execute("PRAGMA trusted_schema=OFF")
    with pytest.raises(DatabaseInvariantError, match="failed rehydration"):
        repository.get_synthetic_aggregation_validation(receipt.validation_receipt_id)


def test_repository_query_has_fixed_limit_and_no_metric_or_window_filter() -> None:
    source = Path(
        "src/prompt_enhancer/infrastructure/sqlite/temporal_aggregation_validation.py"
    ).read_text(encoding="utf-8")
    query = source.split("SELECT sealed.sealed_stratum_id", 1)[1].split(
        '"""', 1
    )[0]
    assert "LIMIT ?" in query
    assert "metric_key" not in query
    assert "window_" not in query
    assert "sealed.sealed_at_us<=?" in query
    assert "revision.effective_at_us,revision.session_id" in query


def test_overflow_probe_rejects_before_member_hydration(tmp_path) -> None:
    context, sealed, _ = _sealed_context(tmp_path)

    class OverflowCursor:
        def fetchall(self):
            return tuple({"sealed_stratum_id": _key(f"overflow-{i}")} for i in range(10001))

    class WrappedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            if "SELECT sealed.sealed_stratum_id" in sql:
                return OverflowCursor()
            return self.connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def scope(*, readonly=False):
        with context.database._connection(readonly=readonly) as connection:
            yield WrappedConnection(connection)

    hydrate_calls = 0

    class ComparisonSpy:
        def _hydrate_sealed_locked(self, connection, sealed_stratum_id):
            nonlocal hydrate_calls
            hydrate_calls += 1
            if hydrate_calls > 1:
                raise AssertionError("overflow members must not be hydrated")
            return sealed

    repository = SqliteTemporalSyntheticAggregationValidationRepository(
        scope,
        context.database._ensure_initialized,
        comparison_repository=ComparisonSpy(),
        begin_append_authorization=(
            context.database._begin_synthetic_aggregation_append_authorization
        ),
        end_append_authorization=(
            context.database._end_synthetic_aggregation_append_authorization
        ),
        clock=lambda: sealed.sealed_at + timedelta(microseconds=1),
    )
    with pytest.raises(DatabaseInvariantError, match="exceeds its bound"):
        repository.validate_synthetic_aggregation(
            sealed.sealed_stratum_id,
            context.metric_key,
            _window(),
            idempotency_key_sha256=_key("overflow"),
        )
    assert hydrate_calls == 1


def test_private_delete_hook_requires_callbacks_and_dedupes_graphs(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    receipt = repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=_key("privacy"),
    )
    unprivileged = SqliteTemporalSyntheticAggregationValidationRepository(
        context.database._connection,
        context.database._ensure_initialized,
        comparison_repository=context.comparison,
        begin_append_authorization=(
            context.database._begin_synthetic_aggregation_append_authorization
        ),
        end_append_authorization=(
            context.database._end_synthetic_aggregation_append_authorization
        ),
    )
    with context.database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(DatabaseInvariantError, match="not authorized"):
            unprivileged._delete_for_upstream_privacy_locked(
                connection,
                operation_id=_key("upstream-operation"),
                cause_kind="run",
                cause_id=context.prepared.expected_analysis_run_id,
            )
        connection.rollback()
    assert repository.get_synthetic_aggregation_validation(
        receipt.validation_receipt_id
    ) == receipt


def test_run_privacy_deletes_v23_before_v22_and_clears_authorizations(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    key = _key("run-privacy")
    receipt = repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=key,
    )
    assert context.database.session_analysis_run_repository().delete_for_privacy(
        context.prepared.expected_analysis_run_id
    )
    assert repository.get_synthetic_aggregation_validation(
        receipt.validation_receipt_id
    ) is None
    with context.database._connection(readonly=True) as connection:
        for table in (
            "synthetic_aggregation_validation_roots",
            "synthetic_aggregation_validation_members",
            "synthetic_aggregation_validation_graph_commitments",
            "synthetic_aggregation_append_authorizations",
            "synthetic_aggregation_delete_authorizations",
            "comparison_sealed_stratum_roots",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
    # No tombstone survives: the same key has no durable replay binding.
    assert repository.get_synthetic_aggregation_validation_for_idempotency(key) is None


def test_task_privacy_deletes_v23_but_preserves_run_and_temporal(
    tmp_path,
    monkeypatch,
) -> None:
    captured: list[tuple[Database, str, str, str]] = []
    original = SqliteTaskRepository.delete_task_for_privacy

    def issue_before_delete(self, task_id: str) -> bool:
        database = self._connection_scope.__self__
        with database._connection(readonly=True) as connection:
            row = connection.execute(
                """SELECT sealed.sealed_stratum_id,sealed.sealed_at_us,
                          sealed.analysis_run_id,sealed.sealed_batch_id,
                          key.metric_key
                   FROM comparison_prepared_task_projections projection
                   JOIN comparison_sealed_stratum_roots sealed
                     ON sealed.prepared_stratum_id=projection.prepared_stratum_id
                   JOIN comparison_prepared_stratum_roots prepared
                     ON prepared.prepared_stratum_id=sealed.prepared_stratum_id
                   JOIN temporal_prepared_scope_roots scope
                     ON scope.prepared_scope_id=prepared.prepared_scope_id
                   JOIN temporal_metric_selection_keys key
                     ON key.selection_revision_id=scope.selection_revision_id
                   WHERE projection.task_id=? ORDER BY key.ordinal LIMIT 1""",
                (task_id,),
            ).fetchone()
        assert row is not None
        repository = database.temporal_synthetic_aggregation_validation_repository()
        repository._clock = lambda: _from_us(row["sealed_at_us"]) + timedelta(
            microseconds=1
        )
        receipt = repository.validate_synthetic_aggregation(
            str(row["sealed_stratum_id"]),
            str(row["metric_key"]),
            _window(),
            idempotency_key_sha256=_key("task-privacy"),
        )
        captured.append(
            (
                database,
                receipt.validation_receipt_id,
                str(row["analysis_run_id"]),
                str(row["sealed_batch_id"]),
            )
        )
        return original(self, task_id)

    monkeypatch.setattr(
        SqliteTaskRepository,
        "delete_task_for_privacy",
        issue_before_delete,
    )
    v22_sqlite.test_task_privacy_deletes_sealed_graph_but_preserves_run_and_temporal(
        tmp_path
    )
    assert len(captured) == 1
    database, receipt_id, run_id, batch_id = captured[0]
    repository = database.temporal_synthetic_aggregation_validation_repository()
    assert repository.get_synthetic_aggregation_validation(receipt_id) is None
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM synthetic_aggregation_validation_roots"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM synthetic_aggregation_delete_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT 1 FROM session_analysis_runs WHERE run_id=?", (run_id,)
        ).fetchone() is not None
        assert connection.execute(
            "SELECT 1 FROM temporal_sealed_batch_roots WHERE sealed_batch_id=?",
            (batch_id,),
        ).fetchone() is not None


def test_raw_v23_mutation_and_v22_parent_deletion_fail_closed(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    receipt = repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=_key("raw-guards"),
    )
    with context.database._connection() as connection:
        connection.execute("PRAGMA recursive_triggers=OFF")
        connection.execute("PRAGMA trusted_schema=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE synthetic_aggregation_validation_roots
                   SET request_fingerprint=? WHERE validation_receipt_id=?""",
                (_key("update-root"), receipt.validation_receipt_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE synthetic_aggregation_validation_members
                   SET member_fingerprint=? WHERE validation_receipt_id=?""",
                (_key("update-member"), receipt.validation_receipt_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE synthetic_aggregation_validation_graph_commitments
                   SET fingerprint=? WHERE validation_receipt_id=?""",
                (_key("update-graph"), receipt.validation_receipt_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """DELETE FROM synthetic_aggregation_validation_members
                   WHERE validation_receipt_id=?""",
                (receipt.validation_receipt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """DELETE FROM synthetic_aggregation_validation_graph_commitments
                   WHERE validation_receipt_id=?""",
                (receipt.validation_receipt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """DELETE FROM synthetic_aggregation_validation_roots
                   WHERE validation_receipt_id=?""",
                (receipt.validation_receipt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT OR REPLACE INTO synthetic_aggregation_validation_members
                   SELECT * FROM synthetic_aggregation_validation_members
                   WHERE validation_receipt_id=?""",
                (receipt.validation_receipt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT OR REPLACE INTO
                   synthetic_aggregation_validation_graph_commitments
                   SELECT * FROM synthetic_aggregation_validation_graph_commitments
                   WHERE validation_receipt_id=? AND ordinal=0""",
                (receipt.validation_receipt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT OR REPLACE INTO synthetic_aggregation_validation_roots
                   SELECT * FROM synthetic_aggregation_validation_roots
                   WHERE validation_receipt_id=?""",
                (receipt.validation_receipt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """DELETE FROM comparison_sealed_stratum_roots
                   WHERE sealed_stratum_id=?""",
                (sealed.sealed_stratum_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT OR REPLACE INTO comparison_sealed_stratum_roots
                   SELECT * FROM comparison_sealed_stratum_roots
                   WHERE sealed_stratum_id=?""",
                (sealed.sealed_stratum_id,),
            )
        connection.rollback()
        connection.execute("PRAGMA trusted_schema=OFF")


def test_v23_delete_process_tag_without_upstream_authority_fails(tmp_path) -> None:
    context, sealed, repository = _sealed_context(tmp_path)
    repository._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    receipt = repository.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        _window(),
        idempotency_key_sha256=_key("no-upstream"),
    )
    with pytest.raises(DatabaseInvariantError, match="upstream privacy authority"):
        context.database._begin_synthetic_aggregation_delete_authorization(
            _key("operation"),
            receipt.validation_receipt_id,
            "run",
            context.prepared.expected_analysis_run_id,
            receipt.fingerprint,
            _key("delete-auth"),
        )


def test_v23_fresh_schema_is_normalized_zero_backfill_and_checksum_bound(
    tmp_path,
) -> None:
    database = Database(tmp_path / "reserved-v23-schema.sqlite3")
    database.initialize()
    assert SCHEMA_VERSION == 61
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        row = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version=23"
        ).fetchone()
        assert row is not None
        assert row["checksum"] == hashlib.sha256(
            migrations.MIGRATION_23.encode("utf-8")
        ).hexdigest()
        tables = tuple(
            str(row["name"])
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'synthetic_aggregation_%'
                   ORDER BY name"""
            )
        )
        assert len(tables) == 5
        for table in tables:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            assert all(str(column["type"]).upper() != "BLOB" for column in columns)
            assert not {"json", "payload", "content", "prompt", "path", "uri"} & {
                str(column["name"]).lower() for column in columns
            }


def test_populated_v22_upgrade_preserves_rows_and_zero_backfills_v23(tmp_path) -> None:
    path = tmp_path / "reserved-populated-v22.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 23)
    )
    installation_id = _key("legacy-installation")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """INSERT INTO installations(installation_id,provider,created_at)
               VALUES(?,?,?)""",
            (
                installation_id,
                "synthetic",
                BASE.isoformat(timespec="microseconds"),
            ),
        )
        connection.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,
                   applied_at TEXT NOT NULL)"""
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            tuple(
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    BASE.isoformat(timespec="microseconds"),
                )
                for version, script in enumerate(scripts, start=1)
            ),
        )
        connection.execute("PRAGMA user_version=22")
        connection.commit()
    database = Database(path)
    database.initialize()
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert tuple(
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ) == tuple(range(1, 62))
        assert connection.execute(
            "SELECT provider FROM installations WHERE installation_id=?",
            (installation_id,),
        ).fetchone()["provider"] == "synthetic"
        for table in (
            "synthetic_aggregation_append_authorizations",
            "synthetic_aggregation_delete_authorizations",
            "synthetic_aggregation_validation_roots",
            "synthetic_aggregation_validation_members",
            "synthetic_aggregation_validation_graph_commitments",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0


def test_module_has_no_snapshot_or_product_surface() -> None:
    source = Path(
        "src/prompt_enhancer/infrastructure/sqlite/temporal_aggregation_validation.py"
    ).read_text(encoding="utf-8")
    assert "TemporalSnapshot" not in source
    assert "aggregate_materialization" not in source
    assert "recommendation" not in source
