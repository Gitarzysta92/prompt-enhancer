from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantScope,
    AutomationGrantState,
)
from prompt_enhancer.database import Database, SCHEMA_VERSION
from prompt_enhancer.database import DatabaseError
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2046, 2, 3, 4, 5, tzinfo=UTC)
GRANT_ID = "a" * 64
PRIVATE_CANARY = "SYNTHETIC-PRIVATE-AUTOMATION-CONTENT-CANARY"


def _database(tmp_path) -> tuple[Database, dict[str, object]]:
    database = Database(tmp_path / "automation.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    return database, database.list_sessions(limit=1)[0]


def test_grant_round_trip_due_renew_revoke_and_restart(tmp_path) -> None:
    database, session = _database(tmp_path)
    repository = database.automation_grant_repository()
    scope = AutomationGrantScope(
        provider=Provider.SYNTHETIC,
        project_id=str(session["project_id"]),
        metric_keys=(
            "logic.decomposition_coverage",
            "prompt.context_sufficiency",
        ),
    )
    record = repository.create(
        AutomationGrantDraft(
            grant_id=GRANT_ID,
            scope=scope,
            created_at=NOW,
            expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        )
    )

    try:
        repository.create(
            AutomationGrantDraft(
                grant_id="f" * 64,
                scope=scope,
                created_at=NOW,
                expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
            )
        )
    except DatabaseError:
        pass
    else:
        raise AssertionError("one project cannot hold two active grants")

    assert SCHEMA_VERSION == 61
    assert record.is_due(NOW)
    assert repository.list_due(now=NOW, limit=10) == (record,)
    checked = repository.record_check(
        GRANT_ID,
        now=NOW,
        next_check_at=NOW + timedelta(minutes=15),
        error_code=None,
    )
    assert not checked.is_due(NOW)

    renewal_time = NOW + timedelta(days=10)
    renewed = repository.renew(GRANT_ID, now=renewal_time)
    assert renewed.revision == 2
    assert renewed.expires_at == renewal_time + AUTOMATION_GRANT_LIFETIME

    reopened = Database(database.path)
    reopened.initialize()
    persisted = reopened.automation_grant_repository().get(GRANT_ID)
    assert persisted == renewed
    revoked = reopened.automation_grant_repository().revoke(
        GRANT_ID,
        now=renewal_time + timedelta(hours=1),
    )
    assert revoked.state is AutomationGrantState.REVOKED
    assert reopened.automation_grant_repository().list_for_provider(
        Provider.SYNTHETIC,
        active_only=True,
    ) == ()
    assert PRIVATE_CANARY.encode() not in database.path.read_bytes()
