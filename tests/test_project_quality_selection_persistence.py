from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.analysis.project_quality_aggregation import (
    ProjectQualitySelectionIncompleteError,
    ProjectQualitySelectionLimitError,
)
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
)
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider, SafeSession, SessionState


NOW = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)
INSTALLATION_ID = "f" * 64


class _QueryCountingDatabase(Database):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.read_statements = 0
        self.read_connection_ids: list[int] = []

    def _trace(self, statement: str, connection_id: int) -> None:
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith(("SELECT ", "WITH ")):
            self.read_statements += 1
            self.read_connection_ids.append(connection_id)

    @contextmanager
    def _connection(self, *, readonly: bool = False):
        with super()._connection(readonly=readonly) as connection:
            connection.set_trace_callback(
                lambda statement: self._trace(statement, id(connection))
            )
            yield connection


def _persist_session(
    database: Database,
    *,
    project_id: str,
    session_id: str,
    ordinal: int,
) -> None:
    database.persist_session(
        SafeSession(
            provider=Provider.SYNTHETIC,
            installation_id=INSTALLATION_ID,
            project_id=project_id,
            session_id=session_id,
            provider_version="synthetic-1",
            adapter_version="synthetic-adapter-1",
            source_schema_version="synthetic-schema-1",
            started_at=NOW + timedelta(minutes=ordinal),
            ended_at=NOW + timedelta(minutes=ordinal + 1),
            terminal_state=SessionState.COMPLETED,
            events_complete=True,
        ),
        (),
    )


def test_complete_multi_project_resolution_uses_one_bounded_query(tmp_path) -> None:
    database = _QueryCountingDatabase(tmp_path / "metrics.sqlite3")
    database.initialize()
    first_project, second_project = "1" * 64, "2" * 64
    expected_sessions = ("a" * 64, "b" * 64, "c" * 64)
    _persist_session(
        database,
        project_id=first_project,
        session_id=expected_sessions[0],
        ordinal=0,
    )
    _persist_session(
        database,
        project_id=first_project,
        session_id=expected_sessions[1],
        ordinal=1,
    )
    _persist_session(
        database,
        project_id=second_project,
        session_id=expected_sessions[2],
        ordinal=2,
    )
    database.read_statements = 0

    resolved = database.resolve_indexed_project_sessions(
        (first_project, second_project),
        max_sessions=100,
    )

    assert database.read_statements == 1
    assert resolved.selected_project_count == 2
    assert set(resolved.session_ids) == set(expected_sessions)
    assert len(resolved.session_ids) == 3


def test_missing_or_empty_project_fails_without_a_partial_resolution(tmp_path) -> None:
    database = _QueryCountingDatabase(tmp_path / "metrics.sqlite3")
    database.initialize()
    populated_project, empty_project, missing_project = (
        "1" * 64,
        "2" * 64,
        "3" * 64,
    )
    _persist_session(
        database,
        project_id=populated_project,
        session_id="a" * 64,
        ordinal=0,
    )
    with database._connection() as connection:
        connection.execute(
            """
            INSERT INTO projects(
                project_id, installation_id, provider, display_name, created_at
            ) VALUES (?, ?, ?, NULL, ?)
            """,
            (
                empty_project,
                INSTALLATION_ID,
                Provider.SYNTHETIC.value,
                NOW.isoformat(),
            ),
        )
        connection.commit()
    database.read_statements = 0

    with pytest.raises(ProjectQualitySelectionIncompleteError):
        database.resolve_indexed_project_sessions(
            (populated_project, missing_project),
            max_sessions=100,
        )
    assert database.read_statements == 1

    database.read_statements = 0
    with pytest.raises(ProjectQualitySelectionIncompleteError):
        database.resolve_indexed_project_sessions(
            (populated_project, empty_project),
            max_sessions=100,
        )
    assert database.read_statements == 1


def test_over_limit_scope_fails_instead_of_returning_a_page(tmp_path) -> None:
    database = _QueryCountingDatabase(tmp_path / "metrics.sqlite3")
    database.initialize()
    project_id = "1" * 64
    for ordinal in range(101):
        _persist_session(
            database,
            project_id=project_id,
            session_id=f"{ordinal + 1000:064x}",
            ordinal=ordinal,
        )
    database.read_statements = 0

    with pytest.raises(ProjectQualitySelectionLimitError):
        database.resolve_indexed_project_sessions(
            (project_id,),
            max_sessions=100,
        )

    assert database.read_statements == 1


def test_resolution_and_run_aggregation_share_one_sqlite_snapshot(tmp_path) -> None:
    database = _QueryCountingDatabase(tmp_path / "metrics.sqlite3")
    database.initialize()
    project_id = "1" * 64
    _persist_session(
        database,
        project_id=project_id,
        session_id="a" * 64,
        ordinal=0,
    )
    database.read_statements = 0
    database.read_connection_ids = []

    with database.open_indexed_project_quality_snapshot(
        (project_id,),
        max_sessions=100,
    ) as snapshot:
        snapshots = snapshot.repository.get_latest_completed_for_aggregation(
            snapshot.resolution.session_ids,
            analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
            analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
            metric_pack_key=COACHING_METRIC_PACK_KEY,
            metric_pack_version=COACHING_METRIC_PACK_VERSION,
        )

    assert snapshots == ()
    assert database.read_statements == 2
    assert len(set(database.read_connection_ids)) == 1
