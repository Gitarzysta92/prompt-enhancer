from __future__ import annotations

from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.ingestion import IngestionSelection, IngestionService
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CodexAppServerAdapter,
    CodexReadMode,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    CodexAppServerClient,
)
from prompt_enhancer.privacy import Pseudonymizer


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_transient_provider_text_never_crosses_the_sqlite_boundary(tmp_path) -> None:
    preview_canary = "SYNTHETIC-PREVIEW-CONTENT-CANARY"
    command_canary = "SYNTHETIC-COMMAND-CONTENT-CANARY"
    output_canary = "SYNTHETIC-OUTPUT-CONTENT-CANARY"
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            {
                "data": [
                    {
                        "id": "example-session-storage-canary",
                        "cwd": "/example/storage-project",
                        "createdAt": 1_768_473_600,
                        "preview": preview_canary,
                    }
                ],
                "nextCursor": None,
            },
            {
                "thread": {
                    "id": "example-session-storage-canary",
                    "cwd": "/example/storage-project",
                    "createdAt": 1_768_473_600,
                    "preview": preview_canary,
                    "turns": [
                        {
                            "id": "example-turn-storage-canary",
                            "status": "completed",
                            "startedAt": 1_768_473_700,
                            "completedAt": 1_768_473_800,
                            "usage": {"inputTokens": 8, "outputTokens": 3},
                            "items": [
                                {
                                    "id": "example-item-storage-canary",
                                    "type": "commandExecution",
                                    "status": "completed",
                                    "command": command_canary,
                                    "output": output_canary,
                                }
                            ],
                        }
                    ],
                }
            },
        ]
    )
    adapter = CodexAppServerAdapter(
        mode=CodexReadMode.OPERATIONAL_HISTORY,
        client_factory=lambda: CodexAppServerClient(transport),
    )
    database = Database(tmp_path / "metrics.sqlite3")
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    installation_id = pseudonymizer.pseudonymize(
        "codex:installation", "codex-app-server-local"
    )
    project_id = pseudonymizer.pseudonymize(
        f"codex:project:{installation_id}", "/example/storage-project"
    )

    report = IngestionService(database, pseudonymizer).ingest(
        adapter,
        selection=IngestionSelection(project_ids=frozenset({project_id})),
    )

    assert report.sessions_selected == 1
    assert report.events_inserted == 5
    assert transport.closed is True
    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
        "thread/read",
    ]

    sqlite_payload = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.glob("metrics.sqlite3*")
        if candidate.is_file()
    )
    for canary in (
        preview_canary,
        command_canary,
        output_canary,
        "example-session-storage-canary",
        "example-turn-storage-canary",
        "example-item-storage-canary",
        "/example/storage-project",
    ):
        assert canary.encode("utf-8") not in sqlite_payload
