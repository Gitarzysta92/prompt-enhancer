from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prompt_enhancer.application.display_labels import (
    LabelEntityKind,
    LabelObservationMethod,
    ProviderDisplayLabelObservation,
    ProviderLabelSource,
)
from prompt_enhancer.database import Database, DatabaseInvariantError
from prompt_enhancer.domain import Provider, SafeSession, SessionState


INSTALLATION_ID = "1" * 64
PROJECT_ID = "2" * 64
SESSION_ID = "3" * 64
WRONG_PROJECT_ID = "4" * 64


def _safe_session() -> SafeSession:
    return SafeSession(
        provider=Provider.CODEX,
        installation_id=INSTALLATION_ID,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        provider_version="example-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-schema-1",
        started_at=datetime(2040, 1, 2, tzinfo=UTC),
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
    )


def _observation(
    *,
    entity_kind: LabelEntityKind,
    project_id: str,
    value: str,
    source: ProviderLabelSource,
) -> ProviderDisplayLabelObservation:
    return ProviderDisplayLabelObservation(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        project_id=project_id,
        entity_kind=entity_kind,
        value=value,
        source=source,
        observation_method=LabelObservationMethod.THREAD_READ_SUMMARY,
        extractor_version="codex-display-labels-v1",
        provider_version="example-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-schema-1",
        observed_at=datetime(2040, 1, 3, tzinfo=UTC),
    )


def test_provider_label_batch_rolls_back_when_later_identity_conflicts(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(_safe_session(), ())
    valid_session_label = _observation(
        entity_kind=LabelEntityKind.SESSION,
        project_id=PROJECT_ID,
        value="Example task title",
        source=ProviderLabelSource.EXPLICIT_TITLE,
    )
    conflicting_project_label = _observation(
        entity_kind=LabelEntityKind.PROJECT,
        project_id=WRONG_PROJECT_ID,
        value="example-project",
        source=ProviderLabelSource.PATH_BASENAME,
    )

    with pytest.raises(DatabaseInvariantError):
        database.apply_provider_display_labels(
            (valid_session_label, conflicting_project_label)
        )

    [rolled_back] = database.list_sessions(provider=Provider.CODEX)
    assert rolled_back["project_display_name"] is None
    assert rolled_back["session_display_name"] is None

    written = database.apply_provider_display_labels((valid_session_label,))
    assert written.project_labels_filled == 0
    assert written.session_labels_filled == 1
    [persisted] = database.list_sessions(provider=Provider.CODEX)
    assert persisted["session_display_name"] == "Example task title"
