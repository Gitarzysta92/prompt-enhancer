"""Profile-bound metric projection r5 SQLite authority tests.

Fixtures are synthetic and the persisted surface is restricted to closed
metadata, counters, fingerprints, and server timestamps.
"""

from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest

from prompt_enhancer.application.analysis.declared_task_profiles import (
    DECLARED_TASK_PROFILE_CONFIRMATION,
    DeclaredTaskProfileCommand,
    DeclaredTaskProfileRecord,
    DeclaredTaskProfileService,
)
from prompt_enhancer.application.analysis.metric_projection_v4 import (
    project_metric_states_v4,
)
from prompt_enhancer.application.analysis.metric_projection_v5 import (
    project_metric_states_v5,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.model_ensemble import (
    build_ensemble_chunks,
    coaching_ensemble_metric_specs,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT,
    COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION,
    COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION,
    coaching_profile_v1_unconfigured_fingerprint,
    MetricProfileSource,
    SessionMetricProfileBinding,
    SessionModelEnsembleOutcome,
    SessionModelEnsembleRunRecord,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ConstraintKind,
    DeliverableSlot,
)
from prompt_enhancer.database import DatabaseInvariantError
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.infrastructure.text_models.probabilistic_metrics import (
    LocalProbabilisticMetricRunner,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.model_ensemble import (
    SqliteSessionModelEnsembleRepository,
    _metric_profile_binding_fingerprint,
    _metric_publication_profile_fingerprint,
    _metric_publication_v2_fingerprint,
    to_iso,
)
from prompt_enhancer.privacy import Pseudonymizer

from test_probabilistic_metric_persistence import (
    IDS,
    NOW,
    _completed_result,
    _context,
    _database_and_session,
    _insert_legacy_r4_sidecar,
)


_STATE_COLUMNS = (
    "run_id,metric_ordinal,registry_version,projection_version,metric_key,"
    "contract_version,contract_fingerprint,evidence_authority,value_state,"
    "explanation_code,numerator,denominator,numeric_value,"
    "censoring_lower_bound,censoring_upper_bound,denominator_basis,"
    "opportunity_unit_kind,capability_available,source_complete,eligible_count,"
    "met_count,not_met_count,pending_count,unknown_count,"
    "superseded_excluded_count,distinct_owner_count,product_metric_eligible"
)


def test_unconfigured_preset_fingerprint_is_derived_and_schema_pinned() -> None:
    """Any fixed COACHING_PROFILE_V1 field drift requires a new SQL identity."""

    assert (
        coaching_profile_v1_unconfigured_fingerprint()
        == COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT
    )
    assert COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT in migrations.MIGRATION_54


def test_current_writer_rejects_frozen_r5_publications(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    record = _record(
        session_id,
        run_character="f",
        request_character="e",
        binding=_preset_binding(session_id),
    )
    repository = database.model_ensemble_repository()

    with pytest.raises(DatabaseInvariantError, match="current projection identity"):
        repository.save_completed(record)

    assert repository.get(record.run_id) is None


def _preset_binding(session_id: str) -> SessionMetricProfileBinding:
    return SessionMetricProfileBinding(
        profile_source=MetricProfileSource.COACHING_PROFILE_V1_UNCONFIGURED,
        provider=Provider.CODEX,
        session_id=session_id,
        source_window_fingerprint="a" * 64,
        profile_fingerprint=COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT,
        profile_schema_version=COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION,
        profile_policy_version=COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION,
        bound_at=NOW,
    )


def _declared_binding(
    profile: DeclaredTaskProfileRecord,
) -> SessionMetricProfileBinding:
    return SessionMetricProfileBinding(
        profile_source=MetricProfileSource.DECLARED_TASK_PROFILE,
        provider=profile.provider,
        session_id=profile.session_id,
        source_window_fingerprint="a" * 64,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_fingerprint=profile.profile_fingerprint,
        profile_schema_version=profile.schema_version,
        profile_policy_version=profile.policy_version,
        bound_at=NOW,
    )


def _record(
    session_id: str,
    *,
    run_character: str,
    request_character: str,
    binding: SessionMetricProfileBinding,
    profile: DeclaredTaskProfileRecord | None = None,
) -> SessionModelEnsembleRunRecord:
    context = _context(session_id)
    if profile is not None:
        context = context.model_copy(
            update={
                "task_profile": context.task_profile.model_copy(
                    update={
                        "expected_constraint_kinds": (
                            ()
                            if profile.constraint_kinds is None
                            else profile.constraint_kinds
                        ),
                        "expected_outcome_count": profile.expected_outcome_count,
                        "expected_deliverable_slots": (
                            ()
                            if profile.deliverable_slots is None
                            else profile.deliverable_slots
                        ),
                    }
                )
            }
        )
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    return SessionModelEnsembleRunRecord(
        run_id=run_character * 64,
        session_id=session_id,
        request_fingerprint=request_character * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        metric_profile_binding=binding,
        receipt=receipt.model_copy(update={"metric_publication_v2": publication}),
    )


def _without_predictive(
    record: SessionModelEnsembleRunRecord,
) -> SessionModelEnsembleRunRecord:
    return record.model_copy(
        update={
            "receipt": record.receipt.model_copy(
                update={"predictive_projection": None}
            )
        }
    )


def _save_historical_r5_fixture(database, record) -> None:  # type: ignore[no-untyped-def]
    """Persist one frozen r5 fixture without reopening the production writer."""

    publication = record.receipt.metric_publication_v2
    binding = record.metric_profile_binding
    assert publication is not None
    assert publication.projection_version == "metric-contract-v2-projection-5"
    assert binding is not None
    bare = record.model_copy(
        update={
            "metric_profile_binding": None,
            "requirement_plan_evidence_binding": None,
            "receipt": record.receipt.model_copy(
                update={"metric_publication_v2": None}
            ),
        }
    )
    repository = database.model_ensemble_repository()
    repository.save_completed(bare)
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        SqliteSessionModelEnsembleRepository._insert_metric_profile_binding(
            connection, record
        )
        connection.executemany(
            f"""INSERT INTO session_model_ensemble_metric_states_v2_r5({_STATE_COLUMNS})
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            tuple(
                (
                    record.run_id,
                    ordinal,
                    publication.registry_version,
                    publication.projection_version,
                    item.state.metric_key,
                    item.state.contract_version,
                    item.state.contract_fingerprint,
                    item.state.evidence_authority.value,
                    item.state.value_state.value,
                    item.state.explanation_code,
                    item.state.numerator,
                    item.state.denominator,
                    item.state.numeric_value,
                    item.state.censoring_lower_bound,
                    item.state.censoring_upper_bound,
                    item.state.statistics.denominator_basis.value,
                    (
                        None
                        if item.state.statistics.opportunity_unit_kind is None
                        else item.state.statistics.opportunity_unit_kind.value
                    ),
                    int(item.state.statistics.capability_available),
                    int(item.state.statistics.source_complete),
                    item.state.statistics.eligible_count,
                    item.state.statistics.met_count,
                    item.state.statistics.not_met_count,
                    item.state.statistics.pending_count,
                    item.state.statistics.unknown_count,
                    item.state.statistics.superseded_excluded_count,
                    item.state.statistics.distinct_owner_count,
                )
                for ordinal, item in enumerate(publication.metrics)
            ),
        )
        projected_at = (
            record.receipt.metric_projection_completed_at
            or record.receipt.completed_at
        )
        connection.execute(
            """INSERT INTO session_model_ensemble_metric_publication_v2_seals_r5(
                   run_id,publication_key,publication_version,registry_version,
                   contract_set_fingerprint,projection_version,
                   guidance_contract_version,guidance_template_catalog_version,
                   source,canonical_live_snapshot,model_stage_consumed,
                   compatibility_preview,metric_count,known_count,pending_count,
                   unknown_count,not_applicable_count,abstained_count,
                   execution_error_count,objective_measured_count,
                   projection_fingerprint,profile_source,profile_id,
                   profile_revision,profile_fingerprint,profile_schema_version,
                   profile_policy_version,profile_binding_fingerprint,
                   publication_profile_fingerprint,projected_at,local_only,
                   content_persisted,product_metric_eligible
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.run_id,
                publication.publication_key,
                publication.publication_version,
                publication.registry_version,
                publication.contract_set_fingerprint,
                publication.projection_version,
                publication.guidance_contract_version,
                publication.guidance_template_catalog_version,
                publication.source.value,
                1,
                0,
                0,
                len(publication.metrics),
                publication.known_count,
                publication.pending_count,
                publication.unknown_count,
                publication.not_applicable_count,
                publication.abstained_count,
                publication.execution_error_count,
                publication.objective_measured_count,
                _metric_publication_v2_fingerprint(publication),
                binding.profile_source.value,
                binding.profile_id,
                binding.profile_revision,
                binding.profile_fingerprint,
                binding.profile_schema_version,
                binding.profile_policy_version,
                _metric_profile_binding_fingerprint(binding),
                _metric_publication_profile_fingerprint(publication, binding),
                to_iso(projected_at),
                1,
                0,
                0,
            ),
        )
        connection.commit()
    loaded = repository.get(record.run_id)
    assert loaded is not None
    assert loaded.metric_profile_binding == binding
    assert loaded.receipt.metric_publication_v2 == publication


def _profile_service(database) -> DeclaredTaskProfileService:  # type: ignore[no-untyped-def]
    return DeclaredTaskProfileService(
        database.declared_task_profile_repository(),
        LocalArtifactIdFactory(Pseudonymizer(bytes(range(32)))),
        clock=lambda: NOW,
    )


def _save_profile(
    database,
    session_id: str,
    *,
    expected_revision: int | None = None,
    expected_outcome_count: int = 2,
    retry_suffix: str = "0001",
) -> DeclaredTaskProfileRecord:
    profile, created = _profile_service(database).save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=DeclaredTaskProfileCommand(
            expected_revision=expected_revision,
            constraint_kinds=(ConstraintKind.COST, ConstraintKind.PRIVACY),
            expected_outcome_count=expected_outcome_count,
            deliverable_slots=(DeliverableSlot.ARTIFACT, DeliverableSlot.FORMAT),
            confirmation=DECLARED_TASK_PROFILE_CONFIRMATION,
        ),
        idempotency_key=f"synthetic-r5-profile-retry-{retry_suffix}",
    )
    assert created is True
    return profile


def _two_run_trajectory(
    database,
    session_id: str,
    first: SessionModelEnsembleRunRecord,
    second: SessionModelEnsembleRunRecord,
    *,
    persist: bool = True,
):  # type: ignore[no-untyped-def]
    runs = database.model_ensemble_repository()
    if persist:
        _save_historical_r5_fixture(database, first)
        _save_historical_r5_fixture(database, second)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "6" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=100,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner="7" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=1),
        next_check_at=NOW + timedelta(seconds=2),
        outcome=SessionModelEnsembleOutcome(run=first, applied=True),
    )
    claimed = watches.claim_due(
        owner="7" * 64,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=3),
        next_check_at=NOW + timedelta(minutes=2),
        outcome=SessionModelEnsembleOutcome(run=second, applied=True),
    )
    return watches.list_publications(
        watch_id,
        before_generation=None,
        limit=12,
    )


def test_r5_preset_binding_round_trips_is_immutable_and_privacy_cascades(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    record = _record(
        session_id,
        run_character="7",
        request_character="8",
        binding=_preset_binding(session_id),
    )
    repository = database.model_ensemble_repository()

    _save_historical_r5_fixture(database, record)

    loaded = repository.get(record.run_id)
    assert loaded is not None
    assert loaded.metric_profile_binding == record.metric_profile_binding
    assert (
        loaded.receipt.metric_publication_v2
        == record.receipt.metric_publication_v2
    )
    assert repository.get_latest(session_id) == loaded
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute(
            """SELECT COUNT(*)
               FROM session_model_ensemble_metric_states_v2_r5
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()[0] == 20
        seal = connection.execute(
            """SELECT profile_source,profile_fingerprint,profile_revision
               FROM session_model_ensemble_metric_publication_v2_seals_r5
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()
        assert seal == (
            "coaching_profile_v1_unconfigured",
            COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT,
            None,
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_metric_profile_bindings
                   SET bound_at=bound_at WHERE run_id=?""",
                (record.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_metric_states_v2_r5
                   SET source_complete=source_complete WHERE run_id=?""",
                (record.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_metric_publication_v2_seals_r5
                   SET known_count=known_count WHERE run_id=?""",
                (record.run_id,),
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert repository.delete_for_privacy(record.run_id) is True
    with sqlite3.connect(database.path) as connection:
        for table in (
            "session_model_ensemble_metric_profile_bindings",
            "session_model_ensemble_metric_states_v2_r5",
            "session_model_ensemble_metric_publication_v2_seals_r5",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0


def test_r5_declared_profile_is_relationally_bound_and_tamper_evident(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    profile = _save_profile(database, session_id)
    record = _record(
        session_id,
        run_character="6",
        request_character="5",
        binding=_declared_binding(profile),
        profile=profile,
    )
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, record)

    bare = record.model_copy(
        update={
            "run_id": "4" * 64,
            "request_fingerprint": "3" * 64,
            "metric_profile_binding": None,
            "receipt": record.receipt.model_copy(
                update={"metric_publication_v2": None}
                | {"predictive_projection": None}
            ),
        }
    )
    repository.save_completed(bare)
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="identity conflict"):
            connection.execute(
                """INSERT INTO session_model_ensemble_metric_profile_bindings(
                       run_id,profile_source,provider,session_id,
                       source_window_fingerprint,profile_id,profile_revision,
                       profile_fingerprint,profile_schema_version,
                       profile_policy_version,bound_at,binding_fingerprint,
                       local_only,content_persisted
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
                (
                    bare.run_id,
                    "declared_task_profile",
                    "codex",
                    session_id,
                    "a" * 64,
                    profile.profile_id,
                    profile.revision,
                    "f" * 64,
                    profile.schema_version,
                    profile.policy_version,
                    NOW.isoformat(timespec="microseconds"),
                    "e" * 64,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_declared_task_profiles
                   SET profile_fingerprint=? WHERE profile_id=?""",
                ("f" * 64, profile.profile_id),
            )

        # Defense in depth: even if a local database editor deliberately
        # removes the SQL immutability trigger, repository hydration verifies
        # the cryptographic binding before returning a run.
        connection.execute(
            "DROP TRIGGER session_model_ensemble_metric_profile_bindings_no_update"
        )
        connection.execute(
            """UPDATE session_model_ensemble_metric_profile_bindings
               SET binding_fingerprint=? WHERE run_id=?""",
            ("f" * 64, record.run_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="binding seal is invalid"):
        repository.get(record.run_id)


def test_r5_binding_and_declared_profile_follow_session_privacy_cascade(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    profile = _save_profile(database, session_id)
    record = _record(
        session_id,
        run_character="9",
        request_character="a",
        binding=_declared_binding(profile),
        profile=profile,
    )
    _save_historical_r5_fixture(database, record)

    with database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute(
            "DELETE FROM sessions WHERE session_id=?",
            (session_id,),
        )
        connection.commit()
        for table in (
            "session_declared_task_profiles",
            "session_model_ensemble_runs",
            "session_model_ensemble_metric_profile_bindings",
            "session_model_ensemble_metric_states_v2_r5",
            "session_model_ensemble_metric_publication_v2_seals_r5",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize(
    ("legacy_states", "legacy_projection"),
    (
        ("session_model_ensemble_metric_states_v2", "metric-contract-v2-projection-1"),
        ("session_model_ensemble_metric_states_v2_r2", "metric-contract-v2-projection-2"),
        ("session_model_ensemble_metric_states_v2_r3", "metric-contract-v2-projection-3"),
        ("session_model_ensemble_metric_states_v2_r4", "metric-contract-v2-projection-4"),
    ),
)
def test_r5_reciprocal_legacy_guards_and_partial_seal(
    tmp_path,
    legacy_states: str,
    legacy_projection: str,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    source = _record(
        session_id,
        run_character="b",
        request_character="c",
        binding=_preset_binding(session_id),
    )
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, source)
    sidecar_free = source.receipt.model_copy(
        update={"metric_publication_v2": None, "predictive_projection": None}
    )
    legacy = source.model_copy(
        update={
            "run_id": "d" * 64,
            "request_fingerprint": "e" * 64,
            "metric_profile_binding": None,
            "receipt": sidecar_free,
        }
    )
    partial_r5 = source.model_copy(
        update={
            "run_id": "0" * 64,
            "request_fingerprint": "1" * 64,
            "receipt": sidecar_free,
        }
    )
    repository.save_completed(legacy)
    repository.save_completed(partial_r5)

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            f"""INSERT INTO {legacy_states}({_STATE_COLUMNS})
                SELECT ?,metric_ordinal,registry_version,?,metric_key,
                       contract_version,contract_fingerprint,evidence_authority,
                       value_state,explanation_code,numerator,denominator,
                       numeric_value,censoring_lower_bound,censoring_upper_bound,
                       denominator_basis,opportunity_unit_kind,
                       capability_available,source_complete,eligible_count,
                       met_count,not_met_count,pending_count,unknown_count,
                       superseded_excluded_count,distinct_owner_count,
                       product_metric_eligible
                FROM session_model_ensemble_metric_states_v2_r5
                WHERE run_id=? ORDER BY metric_ordinal LIMIT 1""",  # noqa: S608
            (legacy.run_id, legacy_projection, source.run_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="identity conflict"):
            connection.execute(
                """INSERT INTO session_model_ensemble_metric_profile_bindings
                   SELECT ?,profile_source,provider,session_id,
                          source_window_fingerprint,profile_id,profile_revision,
                          profile_fingerprint,profile_schema_version,
                          profile_policy_version,bound_at,binding_fingerprint,
                          local_only,content_persisted
                   FROM session_model_ensemble_metric_profile_bindings
                   WHERE run_id=?""",
                (legacy.run_id, source.run_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="identity conflict"):
            connection.execute(
                f"""INSERT INTO {legacy_states}({_STATE_COLUMNS})
                    SELECT ?,metric_ordinal,registry_version,?,metric_key,
                           contract_version,contract_fingerprint,
                           evidence_authority,value_state,explanation_code,
                           numerator,denominator,numeric_value,
                           censoring_lower_bound,censoring_upper_bound,
                           denominator_basis,opportunity_unit_kind,
                           capability_available,source_complete,eligible_count,
                           met_count,not_met_count,pending_count,unknown_count,
                           superseded_excluded_count,distinct_owner_count,
                           product_metric_eligible
                    FROM session_model_ensemble_metric_states_v2_r5
                    WHERE run_id=? ORDER BY metric_ordinal LIMIT 1""",  # noqa: S608
                (partial_r5.run_id, legacy_projection, source.run_id),
            )

        connection.execute(
            f"""INSERT INTO session_model_ensemble_metric_states_v2_r5({_STATE_COLUMNS})
                SELECT ?,metric_ordinal,registry_version,projection_version,
                       metric_key,contract_version,contract_fingerprint,
                       evidence_authority,value_state,explanation_code,numerator,
                       denominator,numeric_value,censoring_lower_bound,
                       censoring_upper_bound,denominator_basis,
                       opportunity_unit_kind,capability_available,
                       source_complete,eligible_count,met_count,not_met_count,
                       pending_count,unknown_count,superseded_excluded_count,
                       distinct_owner_count,product_metric_eligible
                FROM session_model_ensemble_metric_states_v2_r5
                WHERE run_id=? ORDER BY metric_ordinal LIMIT 1""",  # noqa: S608
            (partial_r5.run_id, source.run_id),
        )
        seal_columns = tuple(
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(session_model_ensemble_metric_publication_v2_seals_r5)"
            )
        )
        copied_columns = ",".join(seal_columns[1:])
        with pytest.raises(sqlite3.IntegrityError, match="incomplete"):
            connection.execute(
                f"""INSERT INTO session_model_ensemble_metric_publication_v2_seals_r5
                    SELECT ?,{copied_columns}
                    FROM session_model_ensemble_metric_publication_v2_seals_r5
                    WHERE run_id=?""",  # noqa: S608
                (partial_r5.run_id, source.run_id),
            )

    loaded = repository.get(partial_r5.run_id)
    assert loaded is not None
    assert loaded.receipt.metric_publication_v2 is None


def test_changed_declared_profile_breaks_watch_trajectory_comparability(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    first_profile = _save_profile(database, session_id)
    second_profile = _save_profile(
        database,
        session_id,
        expected_revision=1,
        expected_outcome_count=3,
        retry_suffix="0002",
    )
    first = _without_predictive(
        _record(
            session_id,
            run_character="2",
            request_character="3",
            binding=_declared_binding(first_profile),
            profile=first_profile,
        )
    )
    second = _without_predictive(
        _record(
            session_id,
            run_character="4",
            request_character="5",
            binding=_declared_binding(second_profile),
            profile=second_profile,
        )
    )
    trajectory = _two_run_trajectory(database, session_id, first, second)
    assert tuple(point.run_id for point in trajectory.points) == (
        second.run_id,
        first.run_id,
    )
    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is False


def test_same_declared_profile_remains_comparable_across_fresh_run_seals(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    profile = _save_profile(database, session_id)
    first_binding = _declared_binding(profile)
    second_binding = first_binding.model_copy(
        update={"bound_at": NOW + timedelta(seconds=30)}
    )
    first = _without_predictive(
        _record(
            session_id,
            run_character="2",
            request_character="3",
            binding=first_binding,
            profile=profile,
        )
    )
    second = _without_predictive(
        _record(
            session_id,
            run_character="4",
            request_character="5",
            binding=second_binding,
            profile=profile,
        )
    )

    trajectory = _two_run_trajectory(database, session_id, first, second)

    with sqlite3.connect(database.path) as connection:
        fingerprints = connection.execute(
            """SELECT profile_binding_fingerprint,
                      publication_profile_fingerprint
               FROM session_model_ensemble_metric_publication_v2_seals_r5
               ORDER BY run_id"""
        ).fetchall()
    assert len({row[0] for row in fingerprints}) == 2
    assert len({row[1] for row in fingerprints}) == 2
    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is True


def test_stable_unconfigured_preset_remains_comparable_across_bind_times(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    first_binding = _preset_binding(session_id)
    second_binding = first_binding.model_copy(
        update={"bound_at": NOW + timedelta(minutes=1)}
    )
    first = _without_predictive(
        _record(
            session_id,
            run_character="2",
            request_character="3",
            binding=first_binding,
        )
    )
    second = _without_predictive(
        _record(
            session_id,
            run_character="4",
            request_character="5",
            binding=second_binding,
        )
    )

    trajectory = _two_run_trajectory(database, session_id, first, second)

    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is True


def test_projection_identity_change_remains_incomparable_with_same_window(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    current = _without_predictive(
        _record(
            session_id,
            run_character="4",
            request_character="5",
            binding=_preset_binding(session_id),
        )
    )
    context = _context(session_id)
    historical_publication = publish_metric_states_v2(
        project_metric_states_v4(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    historical = current.model_copy(
        update={
            "run_id": "2" * 64,
            "request_fingerprint": "3" * 64,
            "metric_profile_binding": None,
            "receipt": current.receipt.model_copy(
                update={
                    "metric_publication_v2": None,
                    "predictive_projection": None,
                }
            ),
        }
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(historical)
    _save_historical_r5_fixture(database, current)
    _insert_legacy_r4_sidecar(
        database,
        historical.run_id,
        historical_publication,
    )
    historical = runs.get(historical.run_id)
    assert historical is not None

    trajectory = _two_run_trajectory(
        database,
        session_id,
        historical,
        current,
        persist=False,
    )

    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is False
