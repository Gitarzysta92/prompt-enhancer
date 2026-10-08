from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.automation import (
    AutomationGrantService,
    AutomationScheduleResult,
    AutomationSessionCandidate,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.application.jobs import PowerSourceState
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


TOKEN = "example_automation_api_token_123456789"
NOW = datetime(2046, 2, 3, 4, 5, tzinfo=UTC)
GRANT_ID = "a" * 64
PRIVATE_CANARY = "SYNTHETIC-PRIVATE-AUTOMATION-API-CANARY"


@dataclass
class Access:
    project_id: str

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        return tier is DataTier.REDACTED_CONTENT

    def project_is_indexed(self, provider: Provider, project_id: str) -> bool:
        return project_id == self.project_id


class Refresher:
    def refresh(self, provider: Provider, *, max_sessions: int) -> None:
        return None


@dataclass
class Candidates:
    project_id: str
    session_id: str

    def newest_changed(self, scope, *, limit):  # type: ignore[no-untyped-def]
        return (
            AutomationSessionCandidate(
                provider=scope.provider,
                project_id=self.project_id,
                session_id=self.session_id,
                input_fingerprint="b" * 64,
                provenance_fingerprint="c" * 64,
                provider_schema_version="synthetic-schema-v1",
                updated_at=NOW,
            ),
        )


@dataclass
class Jobs:
    scheduled: int = 0
    cancelled: list[str] = field(default_factory=list)

    def schedule(self, grant, candidate):  # type: ignore[no-untyped-def]
        self.scheduled += 1
        return AutomationScheduleResult(created=True)

    def cancel_for_grant(self, grant_id: str, *, now: datetime) -> int:
        self.cancelled.append(grant_id)
        return 1


class Ids:
    def new_id(self) -> str:
        return GRANT_ID


class ExternalPower:
    def current(self) -> PowerSourceState:
        return PowerSourceState.EXTERNAL_POWER


def _app(tmp_path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "automation-api.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session = database.list_sessions(limit=1)[0]
    jobs = Jobs()
    service = AutomationGrantService(
        database.automation_grant_repository(),
        Access(str(session["project_id"])),
        Refresher(),
        Candidates(str(session["project_id"]), str(session["session_id"])),
        jobs,
        Ids(),
        ExternalPower(),
        clock=lambda: NOW,
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        automation_grant_service=service,
    )
    return app, database, session, jobs


def test_automation_routes_are_strict_authenticated_and_revocable(
    tmp_path,
    caplog,
) -> None:
    app, database, session, jobs = _app(tmp_path)
    payload = {
        "provider": "synthetic",
        "project_id": session["project_id"],
        "metric_keys": ["prompt.context_sufficiency"],
        "newest_session_limit": 20,
        "check_interval_seconds": 900,
        "resource_policy": {
            "route": "balanced",
            "max_gpu_workers": 1,
            "max_cpu_workers": 1,
            "pause_on_battery": True,
            "maximum_session_seconds": 1800,
        },
    }
    client = TestClient(app, base_url="http://127.0.0.1")
    with client:
        unauthorized = client.post("/v1/automation-grants", json=payload)
        private = dict(payload)
        private["prompt"] = PRIVATE_CANARY
        rejected = client.post(
            "/v1/automation-grants",
            json=private,
            headers={API_TOKEN_HEADER: TOKEN},
        )
        created = client.post(
            "/v1/automation-grants",
            json=payload,
            headers={API_TOKEN_HEADER: TOKEN},
        )
        listed = client.get(
            "/v1/automation-grants?provider=synthetic",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        polled = client.post(
            "/v1/automation-grants/poll",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        renewed = client.post(
            f"/v1/automation-grants/{GRANT_ID}/renewal",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        revoked = client.post(
            f"/v1/automation-grants/{GRANT_ID}/revocation",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert unauthorized.status_code == 401
    assert rejected.status_code == 422
    assert PRIVATE_CANARY not in rejected.text
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store, private"
    assert created.headers["pragma"] == "no-cache"
    assert created.json()["scope"]["remote_requires_fresh_approval"] is True
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert polled.status_code == 200 and polled.json()["jobs_created"] == 1
    assert jobs.scheduled == 1
    assert renewed.status_code == 200 and renewed.json()["revision"] == 2
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert jobs.cancelled == [GRANT_ID]
    assert PRIVATE_CANARY not in caplog.text
    assert PRIVATE_CANARY.encode() not in database.path.read_bytes()
