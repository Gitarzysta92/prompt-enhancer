from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database, SCHEMA_VERSION, _MIGRATION_1
from prompt_enhancer.display_labels import minimize_private_display_name
from prompt_enhancer.domain import DataTier, Provider, SafeSession, SessionState
from prompt_enhancer.ingestion import IngestionSelection, IngestionService
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CodexAppServerAdapter,
    CodexReadMode,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    CodexAppServerClient,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    RawThread,
    parse_thread_page,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.limits import (
    CodexReadLimits,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.mapping import (
    CodexThreadMapper,
)
from prompt_enhancer.infrastructure.sqlite.migrations import MIGRATION_2, MIGRATION_3
from prompt_enhancer.privacy import Pseudonymizer


API_TOKEN = "synthetic-display-api-token-" + "x" * 32
ORIGIN = "http://127.0.0.1:8766"
INSTALLATION_ID = "1" * 64
PROJECT_ID = "2" * 64
SESSION_ID = "3" * 64
FULL_PATH_PARENT_CANARY = "SYNTHETIC-FULL-PATH-PARENT-CANARY"
PREVIEW_CANARY = "SYNTHETIC-PREVIEW-CONTENT-CANARY"


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.notifications: list[tuple[str, dict[str, object] | None]] = []
        self.closed = False

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        self.notifications.append((method, params))

    def close(self) -> None:
        self.closed = True


def _safe_session(
    *,
    project_display_name: str | None = "example-project",
    session_display_name: str | None = "Example planning session",
) -> SafeSession:
    return SafeSession(
        provider=Provider.CODEX,
        installation_id=INSTALLATION_ID,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        project_display_name=project_display_name,
        session_display_name=session_display_name,
        provider_version="example-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-schema-1",
        started_at=datetime(2040, 1, 2, 10, tzinfo=UTC),
        ended_at=None,
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
    )


def test_display_name_minimizer_rejects_unencodable_surrogates() -> None:
    assert minimize_private_display_name(chr(0xD800), max_length=160) is None


@pytest.mark.parametrize(
    "unsafe_name",
    (
        "Fix /example/private/file.py",
        r"Fix C:\example\private\file.py",
        r"Inspect \\example.invalid\share\file.py",
        "Inspect //example.invalid/share/file.py",
        "Inspect file:///example/private/file.py",
    ),
)
def test_mapper_drops_session_labels_containing_absolute_paths(
    unsafe_name: str,
) -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-unsafe-label",
            "cwd": "/example/example-project",
            "name": unsafe_name,
            "createdAt": 2_208_988_800,
        }
    )

    source = CodexThreadMapper(provider_version="example-1").session(
        raw, events_complete=False
    )

    assert source.source_session_display_name is None

@pytest.mark.parametrize(
    "unsafe_name",
    ("Example\nProject", "Example\u202eProject"),
)
def test_display_name_minimizer_drops_controls(unsafe_name: str) -> None:
    assert minimize_private_display_name(unsafe_name, max_length=160) is None


def test_display_name_minimizer_normalizes_and_bounds_labels() -> None:
    assert (
        minimize_private_display_name(
            "  \uff25\uff58\uff41\uff4d\uff50\uff4c\uff45   Project  ", max_length=120
        )
        == "Example Project"
    )
    bounded = minimize_private_display_name("x" * 200, max_length=120)
    assert bounded is not None
    assert len(bounded) == 120


@pytest.mark.parametrize(
    "cwd",
    ("/", "C:/", "relative/project", "/home/example", "C:/Users/Example"),
)
def test_mapper_suppresses_unsafe_or_identity_revealing_project_labels(
    cwd: str,
) -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-suppressed-project-label",
            "cwd": cwd,
            "name": "Example safe task",
            "createdAt": 2_208_988_800,
        }
    )

    source = CodexThreadMapper(provider_version="example-1").session(
        raw, events_complete=False
    )

    assert source.source_project_display_name is None



def test_thread_name_is_allowlisted_as_a_secret_but_preview_is_discarded() -> None:
    page = parse_thread_page(
        {
            "data": [
                {
                    "id": "example-session-display-name",
                    "cwd": "/example/example-project",
                    "name": "Example planning session",
                    "preview": PREVIEW_CANARY,
                    "createdAt": 2_208_988_800,
                }
            ],
            "nextCursor": None,
        },
        CodexReadLimits(),
    )

    thread = page.threads[0]
    assert isinstance(thread.name, SecretStr)
    assert thread.name.get_secret_value() == "Example planning session"
    assert "name" in type(thread).model_fields
    assert "preview" not in type(thread).model_fields
    assert PREVIEW_CANARY not in repr(page)
    assert PREVIEW_CANARY not in page.model_dump_json()


@pytest.mark.parametrize(
    ("cwd", "expected"),
    (
        (
            f"/example/{FULL_PATH_PARENT_CANARY}/example-project/.",
            "example-project",
        ),
        (
            f"C:\\example\\{FULL_PATH_PARENT_CANARY}\\example-project\\",
            "example-project",
        ),
    ),
)
def test_mapper_exposes_only_the_cwd_basename_as_a_secret_project_label(
    cwd: str,
    expected: str,
) -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-mapped-name",
            "cwd": cwd,
            "name": "Example mapped session",
            "createdAt": 2_208_988_800,
        }
    )

    source = CodexThreadMapper(provider_version="example-1").session(
        raw, events_complete=False
    )

    assert isinstance(source.source_project_display_name, SecretStr)
    assert source.source_project_display_name.get_secret_value() == expected
    assert isinstance(source.source_session_display_name, SecretStr)
    assert (
        source.source_session_display_name.get_secret_value()
        == "Example mapped session"
    )
    assert FULL_PATH_PARENT_CANARY not in repr(source)
    assert FULL_PATH_PARENT_CANARY not in source.model_dump_json()


def test_v3_migration_adds_nullable_display_names_without_fabricating_values(
    tmp_path,
) -> None:
    path = tmp_path / "metrics.sqlite3"
    applied_at = "2040-01-01T00:00:00+00:00"
    migrations = ((1, _MIGRATION_1), (2, MIGRATION_2), (3, MIGRATION_3))

    with sqlite3.connect(path) as connection:
        for _version, script in migrations:
            connection.executescript(script)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for version, script in migrations:
            connection.execute(
                """
                INSERT INTO schema_migrations(version, checksum, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    applied_at,
                ),
            )
        connection.execute(
            """
            INSERT INTO installations(installation_id, provider, created_at)
            VALUES (?, 'codex', ?)
            """,
            (INSTALLATION_ID, applied_at),
        )
        connection.execute(
            """
            INSERT INTO projects(project_id, installation_id, provider, created_at)
            VALUES (?, ?, 'codex', ?)
            """,
            (PROJECT_ID, INSTALLATION_ID, applied_at),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id, installation_id, project_id, provider,
                provider_version, adapter_version, source_schema_version,
                started_at, ended_at, terminal_state, events_complete,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'codex', ?, ?, ?, ?, NULL, 'unknown', 0, ?, ?)
            """,
            (
                SESSION_ID,
                INSTALLATION_ID,
                PROJECT_ID,
                "example-1",
                "example-adapter-1",
                "example-schema-1",
                "2040-01-02T10:00:00+00:00",
                applied_at,
                applied_at,
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    database = Database(path)
    database.initialize()

    assert SCHEMA_VERSION == 61
    assert database.summary()["schema_version"] == SCHEMA_VERSION
    [record] = database.list_sessions(provider=Provider.CODEX)
    assert record["project_display_name"] is None
    assert record["session_display_name"] is None
    with sqlite3.connect(path) as connection:
        [project_name] = connection.execute(
            "SELECT display_name FROM projects WHERE project_id = ?", (PROJECT_ID,)
        ).fetchone()
        [session_name] = connection.execute(
            "SELECT display_name FROM sessions WHERE session_id = ?", (SESSION_ID,)
        ).fetchone()
        applied_versions = tuple(
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        )
    assert project_name is None
    assert session_name is None
    assert applied_versions == tuple(range(1, SCHEMA_VERSION + 1))


def test_display_name_observations_update_without_changing_safe_identity(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(_safe_session(), ())

    database.persist_session(
        _safe_session(project_display_name=None, session_display_name=None), ()
    )
    unchanged = database.get_session(SESSION_ID)
    assert unchanged is not None
    assert unchanged.project_display_name == "example-project"
    assert unchanged.session_display_name == "Example planning session"

    database.persist_session(
        _safe_session(
            project_display_name="renamed-example-project",
            session_display_name="Renamed example planning session",
        ),
        (),
    )
    updated = database.get_session(SESSION_ID)
    assert updated is not None
    assert updated.installation_id == INSTALLATION_ID
    assert updated.project_id == PROJECT_ID
    assert updated.session_id == SESSION_ID
    assert updated.project_display_name == "renamed-example-project"
    assert updated.session_display_name == "Renamed example planning session"
    [record] = database.list_sessions(provider=Provider.CODEX)
    assert record["project_id"] == PROJECT_ID
    assert record["session_id"] == SESSION_ID
    assert record["project_display_name"] == "renamed-example-project"
    assert record["session_display_name"] == "Renamed example planning session"


def test_authorized_names_are_minimized_through_sqlite_api_and_logs(
    tmp_path,
    caplog,
    capsys,
) -> None:
    provider_session_id = "example-session-end-to-end-display"
    full_cwd = f"/example/{FULL_PATH_PARENT_CANARY}/example-project"
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1"}},
            {
                "data": [
                    {
                        "id": provider_session_id,
                        "cwd": full_cwd,
                        "name": "Example end-to-end session",
                        "preview": PREVIEW_CANARY,
                        "createdAt": 2_208_988_800,
                        "status": "idle",
                    }
                ],
                "nextCursor": None,
            },
        ]
    )
    adapter = CodexAppServerAdapter(
        mode=CodexReadMode.METADATA_INDEX,
        client_factory=lambda: CodexAppServerClient(transport),
    )
    database_path = tmp_path / "metrics.sqlite3"
    database = Database(database_path)
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)

    report = IngestionService(
        database, Pseudonymizer(bytes(range(32)))
    ).ingest(adapter, selection=IngestionSelection(max_sessions=1))

    assert report.sessions_selected == 1
    assert transport.closed is True
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=database,
        api_token=API_TOKEN,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get(
            "/v1/sessions?provider=codex",
            headers={API_TOKEN_HEADER: API_TOKEN},
        )

    assert response.status_code == 200
    [record] = response.json()["sessions"]
    assert record["project_display_name"] == "example-project"
    assert record["session_display_name"] == "Example end-to-end session"
    assert len(record["project_id"]) == 64
    assert len(record["session_id"]) == 64
    assert "cwd" not in record
    assert "preview" not in record
    assert "name" not in record

    forbidden = (
        FULL_PATH_PARENT_CANARY,
        full_cwd,
        PREVIEW_CANARY,
        provider_session_id,
    )
    sqlite_payload = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.glob("metrics.sqlite3*")
        if candidate.is_file()
    )
    captured = capsys.readouterr()
    rendered_surfaces = "\n".join(
        (response.text, caplog.text, captured.out, captured.err)
    )
    for canary in forbidden:
        assert canary.encode("utf-8") not in sqlite_payload
        assert canary not in rendered_surfaces
