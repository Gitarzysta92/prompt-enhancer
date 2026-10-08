from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3

import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.model_link_experiments import (
    MODEL_LINK_EXPERIMENT_KEY,
    MODEL_LINK_EXPERIMENT_VERSION,
    ModelExperimentDevice,
    ModelLinkAnnotationLabel,
    ModelLinkAnnotationRecord,
    ModelLinkCandidateKind,
    ModelLinkModelIdentity,
    ModelLinkRecommendation,
    ModelLinkRunRecord,
    ModelLinkStoredLink,
)
from prompt_enhancer.database import SCHEMA_VERSION, Database, _MIGRATION_1
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer
from prompt_enhancer.infrastructure.sqlite.migrations import (
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    MIGRATION_6,
    MIGRATION_7,
    MIGRATION_8,
    MIGRATION_9,
)


NOW = datetime(2040, 2, 3, 10, 0, tzinfo=UTC)


def _database_and_session(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_id = database.list_sessions(provider=Provider.SYNTHETIC, limit=1)[0][
        "session_id"
    ]
    return database, session_id


def _model(*, qwen: bool):
    identity = "c" if qwen else "d"
    repository = (
        "Qwen/Qwen3-Embedding-0.6B"
        if qwen
        else "BAAI/bge-reranker-v2-m3"
    )
    return ModelLinkModelIdentity(
        key="qwen3_embedding_06b" if qwen else "bge_reranker_v2_m3",
        repository_id=repository,
        revision=identity * 40,
        license_spdx="Apache-2.0",
        tokenizer_id=f"{repository}:{identity * 40}",
        backend_key=(
            "qwen3_embedding_last_token_v1"
            if qwen
            else "bge_reranker_sequence_classifier_v1"
        ),
    )


def _run(session_id: str) -> ModelLinkRunRecord:
    return ModelLinkRunRecord(
        run_id="a" * 64,
        session_id=session_id,
        request_fingerprint="b" * 64,
        input_fingerprint="e" * 64,
        experiment_key=MODEL_LINK_EXPERIMENT_KEY,
        experiment_version=MODEL_LINK_EXPERIMENT_VERSION,
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-source-1",
        content_schema_version="redacted-message-1",
        redactor_version="deterministic-redactor-1",
        consent_policy_version="explicit-session-model-link-v1",
        resolved_device=ModelExperimentDevice.CUDA,
        qwen_model=_model(qwen=True),
        bge_model=_model(qwen=False),
        query_count=1,
        link_count=1,
        agreement_count=1,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=4),
    )


def _link() -> ModelLinkStoredLink:
    return ModelLinkStoredLink(
        run_id="a" * 64,
        link_id="f" * 64,
        query_message_id="1" * 64,
        candidate_message_id="2" * 64,
        query_sequence=2,
        candidate_sequence=4,
        candidate_kind=ModelLinkCandidateKind.RESPONSE,
        qwen_score=0.8125,
        qwen_rank=1,
        bge_score=4.25,
        bge_rank=1,
        recommended_by=ModelLinkRecommendation.BOTH,
    )


def test_model_link_snapshot_round_trips_without_content_columns(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_link_experiment_repository()
    run = _run(session_id)
    link = _link()

    repository.save_completed(run, (link,))
    stored = repository.get(run.run_id)

    assert stored is not None
    assert stored.run == run
    assert stored.links == (link,)
    assert repository.get_latest(session_id) == stored
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {
            row[1]
            for table in (
                "session_model_link_runs",
                "session_model_links",
                "session_model_link_annotations",
            )
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
    forbidden_fragments = ("text", "prompt", "response", "excerpt", "path", "output")
    assert not any(
        fragment in column for column in columns for fragment in forbidden_fragments
    )


def test_v9_database_upgrades_to_empty_model_link_tables_without_inference(tmp_path) -> None:
    path = tmp_path / "legacy-v9.sqlite3"
    migrations = (
        _MIGRATION_1,
        MIGRATION_2,
        MIGRATION_3,
        MIGRATION_4,
        MIGRATION_5,
        MIGRATION_6,
        MIGRATION_7,
        MIGRATION_8,
        MIGRATION_9,
    )
    with sqlite3.connect(path) as connection:
        for script in migrations:
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
        connection.executemany(
            "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
            (
                (
                    index,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    NOW.isoformat(),
                )
                for index, script in enumerate(migrations, start=1)
            ),
        )
        connection.execute("PRAGMA user_version = 9")
        connection.commit()

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "session_model_link_runs",
                "session_model_links",
                "session_model_link_annotations",
            )
        ) == (0, 0, 0)


def test_model_link_annotations_are_append_only_and_revision_checked(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_link_experiment_repository()
    run = _run(session_id)
    link = _link()
    repository.save_completed(run, (link,))

    first = ModelLinkAnnotationRecord(
        run_id=run.run_id,
        link_id=link.link_id,
        revision=1,
        label=ModelLinkAnnotationLabel.RELEVANT,
        annotated_at=NOW + timedelta(minutes=1),
    )
    stale = ModelLinkAnnotationRecord(
        run_id=run.run_id,
        link_id=link.link_id,
        revision=2,
        label=ModelLinkAnnotationLabel.INCORRECT,
        annotated_at=NOW + timedelta(minutes=2),
    )

    assert repository.append_annotation(first, expected_revision=0) is True
    assert repository.append_annotation(stale, expected_revision=0) is False
    stored = repository.get(run.run_id)
    assert stored is not None and stored.annotations == (first,)
    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE session_model_link_annotations SET label = 'unsure' WHERE run_id = ?",
                (run.run_id,),
            )


def test_model_link_snapshot_is_immutable_and_privacy_delete_cascades(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_link_experiment_repository()
    run = _run(session_id)
    link = _link()
    repository.save_completed(run, (link,))
    assert repository.append_annotation(
        ModelLinkAnnotationRecord(
            run_id=run.run_id,
            link_id=link.link_id,
            revision=1,
            label=ModelLinkAnnotationLabel.UNSURE,
            annotated_at=NOW + timedelta(minutes=1),
        ),
        expected_revision=0,
    )

    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE session_model_link_runs SET query_count = 2 WHERE run_id = ?",
                (run.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE session_model_links SET qwen_score = 0 WHERE run_id = ?",
                (run.run_id,),
            )

    assert repository.delete_for_privacy(run.run_id) is True
    assert repository.get(run.run_id) is None
    with sqlite3.connect(database.path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "session_model_link_runs",
                "session_model_links",
                "session_model_link_annotations",
            )
        )
    assert counts == (0, 0, 0)
