from __future__ import annotations

import hashlib
import sqlite3

from prompt_enhancer.application.analysis import TASK_METRIC_ENGINE_VERSION
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_ENGINE_VERSION,
)
from prompt_enhancer.application.analysis.contracts import MetricDefinition
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    _MIGRATION_1,
    _definition_checksum,
)
from prompt_enhancer.domain import MetricSource
from prompt_enhancer.infrastructure.sqlite.migrations import MIGRATION_2
from prompt_enhancer.metrics import METRIC_ENGINE_VERSION


def test_v2_database_keeps_v1_metric_provenance_when_seeding_v2(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    applied_at = "2026-01-01T00:00:00+00:00"
    old_checksum = "0" * 64
    old_definitions = (
        (
            "workflow.event_count",
            1,
            "workflow",
            "Legacy event count",
            "Synthetic v1 definition retained for migration coverage.",
            "count",
            "deterministic",
            "deterministic-1",
            old_checksum,
        ),
        (
            "task.workflow.session_count",
            1,
            "workflow",
            "Legacy task session count",
            "Synthetic v1 task definition retained for migration coverage.",
            "count",
            "deterministic",
            "task-deterministic-1",
            old_checksum,
        ),
    )

    with sqlite3.connect(path) as connection:
        connection.executescript(_MIGRATION_1)
        connection.executescript(MIGRATION_2)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for version, script in ((1, _MIGRATION_1), (2, MIGRATION_2)):
            connection.execute(
                """
                INSERT INTO schema_migrations(version, checksum, applied_at)
                VALUES (?, ?, ?)
                """,
                (version, hashlib.sha256(script.encode("utf-8")).hexdigest(), applied_at),
            )
        connection.executemany(
            """
            INSERT INTO metric_definitions(
                key, version, dimension, display_name, description, unit,
                source, algorithm_version, definition_checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            old_definitions,
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()

    database = Database(path)
    database.initialize()
    definitions = {
        (item["key"], item["version"]): item
        for item in database.list_metric_definitions()
    }

    assert database.summary()["schema_version"] == SCHEMA_VERSION == 61
    assert definitions[("workflow.event_count", 1)]["algorithm_version"] == (
        "deterministic-1"
    )
    assert definitions[("workflow.event_count", 1)]["definition_checksum"] == (
        old_checksum
    )
    assert definitions[("workflow.event_count", 2)]["algorithm_version"] == (
        METRIC_ENGINE_VERSION
    )
    assert definitions[("task.workflow.session_count", 1)][
        "algorithm_version"
    ] == "task-deterministic-1"
    assert definitions[("task.workflow.session_count", 2)][
        "algorithm_version"
    ] == TASK_METRIC_ENGINE_VERSION


def test_existing_coaching_catalog_is_immutable_when_new_versions_are_seeded(
    tmp_path,
) -> None:
    path = tmp_path / "coaching-upgrade.sqlite3"
    Database(path).initialize()
    prior_versions = {
        "prompt.task_definition_coverage": 1,
        "prompt.problem_evidence_quality": 1,
        "prompt.context_sufficiency": 1,
        "prompt.constraint_precision": 1,
        "prompt.acceptance_testability": 1,
        "prompt.deliverable_contract": 2,
        "collaboration.ambiguity_resolution": 1,
        "collaboration.clarification_yield": 1,
        "collaboration.exploration_conversion": 1,
        "collaboration.scope_change_discipline": 1,
        "collaboration.rework_candidate_rate": 1,
        "logic.decomposition_coverage": 1,
        "logic.hypothesis_test_linkage": 1,
        "logic.decision_rationale_coverage": 2,
        "logic.requirement_action_traceability": 2,
        "logic.open_loop_closure": 1,
        "outcome.agent_claim_grounding": 1,
        "outcome.verification_strategy_adequacy": 1,
        "outcome.first_pass_verification": 1,
        "outcome.verified_requirement_coverage": 1,
    }
    prior_descriptions = {
        "prompt.task_definition_coverage": (
            "Detected action, target, operating context, and intended-outcome "
            "cues divided by four explicit rubric factors."
        ),
        "prompt.context_sufficiency": (
            "Detected artifact or component, current state, environment or "
            "version, and relevant boundary cues divided by four rubric factors."
        ),
    }
    old_rows = []
    for current in COACHING_METRIC_DEFINITIONS:
        prior = MetricDefinition(
            key=current.key,
            version=prior_versions[current.key],
            dimension=current.dimension,
            display_name=current.display_name,
            description=prior_descriptions.get(current.key, current.description),
            unit=current.unit,
            source=MetricSource.DETERMINISTIC,
        )
        old_rows.append(
            (
                prior.key,
                prior.version,
                prior.dimension,
                prior.display_name,
                prior.description,
                prior.unit,
                prior.source.value,
                "coaching-rules-en-pl-1",
                _definition_checksum(prior),
            )
        )

    coaching_keys = tuple(prior_versions)
    placeholders = ",".join("?" for _ in coaching_keys)
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"DELETE FROM metric_definitions WHERE key IN ({placeholders})",
            coaching_keys,
        )
        connection.executemany(
            """
            INSERT INTO metric_definitions(
                key, version, dimension, display_name, description, unit,
                source, algorithm_version, definition_checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            old_rows,
        )
        connection.commit()
        before = tuple(
            connection.execute(
                f"""
                SELECT key, version, dimension, display_name, description, unit,
                       source, algorithm_version, definition_checksum
                FROM metric_definitions
                WHERE key IN ({placeholders})
                ORDER BY key, version
                """,
                coaching_keys,
            )
        )

    upgraded = Database(path)
    upgraded.initialize()
    with sqlite3.connect(path) as connection:
        after_old = tuple(
            connection.execute(
                f"""
                SELECT key, version, dimension, display_name, description, unit,
                       source, algorithm_version, definition_checksum
                FROM metric_definitions
                WHERE key IN ({placeholders})
                  AND (key, version) IN ({','.join('(?, ?)' for _ in coaching_keys)})
                ORDER BY key, version
                """,
                (*coaching_keys, *tuple(
                    value
                    for key in coaching_keys
                    for value in (key, prior_versions[key])
                )),
            )
        )

    assert after_old == before
    definitions = {
        (item["key"], item["version"]): item
        for item in upgraded.list_metric_definitions()
    }
    for current in COACHING_METRIC_DEFINITIONS:
        assert current.version > prior_versions[current.key]
        seeded = definitions[(current.key, current.version)]
        assert seeded["algorithm_version"] == COACHING_METRIC_ENGINE_VERSION
