"""Projection r7 SQLite authority, seal, and trajectory attacks."""

from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    MetricValueStateV2,
)
from prompt_enhancer.application.analysis.metric_projection_v7 import (
    project_metric_states_v7,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.text_contracts import TextMessageKind
from prompt_enhancer.application.analysis.session_model_ensemble import (
    REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
    REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION,
    REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT,
    REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION,
    REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT,
    REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION,
    REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT,
    REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION,
    REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT,
    REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
    REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION,
    RequirementActionEvidenceSource,
    SessionModelEnsembleOutcome,
    SessionModelEnsembleRunRecord,
    SessionRequirementActionEvidenceBinding,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    RequirementActionConflictError,
    RequirementActionEvidenceSnapshot,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
)
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.database import DatabaseError, DatabaseInvariantError
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.sqlite.model_ensemble import (
    _requirement_action_binding_fingerprint,
)

from test_model_ensemble_r5_profile_persistence import NOW, _STATE_COLUMNS
from test_model_ensemble_r6_persistence import (
    _copy_profile_binding,
    _copy_requirement_binding,
    _r6_record,
    _reviewed_binding,
    _trajectory,
)
from test_probabilistic_metric_persistence import IDS, _context
from test_requirement_action_evidence_persistence import (
    _decision,
    _proposal,
    _restart,
    _setup_reviewed_source,
)
from test_requirement_plan_evidence_persistence import ARTIFACT_IDS


class _R7ProjectionIds:
    """Match the installation-keyed authority used by the combined fixture."""

    @staticmethod
    def fingerprint(namespace: str, values: tuple[str, ...]) -> str:
        return ARTIFACT_IDS.fingerprint(namespace, values)


R7_PROJECTION_IDS = _R7ProjectionIds()


def _reviewed_action_binding(
    snapshot,
    *,
    bound_at=NOW,
):  # type: ignore[no-untyped-def]
    assert snapshot.source_run_id is not None
    assert snapshot.requirement_plan_confirmation_id is not None
    assert snapshot.requirement_plan_evidence_fingerprint is not None
    assert snapshot.candidate_manifest is not None
    assert snapshot.confirmation_id is not None
    assert snapshot.proposal_id is not None
    assert snapshot.reviewed_descriptor_set_fingerprint is not None
    assert snapshot.evidence_fingerprint is not None
    return SessionRequirementActionEvidenceBinding(
        evidence_source=RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION,
        session_id=snapshot.session_id,
        source_window_fingerprint=snapshot.source_window_fingerprint,
        source_run_id=snapshot.source_run_id,
        requirement_plan_confirmation_id=snapshot.requirement_plan_confirmation_id,
        requirement_plan_evidence_fingerprint=(
            snapshot.requirement_plan_evidence_fingerprint
        ),
        candidate_manifest_fingerprint=(
            snapshot.candidate_manifest.manifest_fingerprint
        ),
        reviewed_descriptor_set_fingerprint=(
            snapshot.reviewed_descriptor_set_fingerprint
        ),
        confirmation_id=snapshot.confirmation_id,
        proposal_id=snapshot.proposal_id,
        evidence_fingerprint=snapshot.evidence_fingerprint,
        evidence_schema_version=snapshot.schema_version,
        evidence_policy_version=snapshot.policy_version,
        bound_at=bound_at,
    )


def _unavailable_action_binding(
    session_id: str,
    source_window_fingerprint: str,
    *,
    bound_at=NOW,
) -> SessionRequirementActionEvidenceBinding:
    return SessionRequirementActionEvidenceBinding(
        evidence_source=RequirementActionEvidenceSource.UNAVAILABLE,
        session_id=session_id,
        source_window_fingerprint=source_window_fingerprint,
        evidence_fingerprint=REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT,
        evidence_schema_version=REQUIREMENT_ACTION_UNAVAILABLE_SCHEMA_VERSION,
        evidence_policy_version=REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
        bound_at=bound_at,
    )


def _awaiting_action_binding(
    session_id: str,
    source_window_fingerprint: str,
) -> SessionRequirementActionEvidenceBinding:
    return SessionRequirementActionEvidenceBinding(
        evidence_source=RequirementActionEvidenceSource.AWAITING_REVIEW,
        session_id=session_id,
        source_window_fingerprint=source_window_fingerprint,
        evidence_fingerprint=REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
        evidence_schema_version=REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION,
        evidence_policy_version=REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
        bound_at=NOW,
    )


def _overflow_action_binding(
    session_id: str,
    source_window_fingerprint: str,
) -> SessionRequirementActionEvidenceBinding:
    return SessionRequirementActionEvidenceBinding(
        evidence_source=RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW,
        session_id=session_id,
        source_window_fingerprint=source_window_fingerprint,
        evidence_fingerprint=(
            REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT
        ),
        evidence_schema_version=(
            REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_SCHEMA_VERSION
        ),
        evidence_policy_version=REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
        bound_at=NOW,
    )


def _incomplete_action_binding(
    session_id: str,
    source_window_fingerprint: str,
) -> SessionRequirementActionEvidenceBinding:
    return SessionRequirementActionEvidenceBinding(
        evidence_source=RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE,
        session_id=session_id,
        source_window_fingerprint=source_window_fingerprint,
        evidence_fingerprint=(
            REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT
        ),
        evidence_schema_version=(
            REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_SCHEMA_VERSION
        ),
        evidence_policy_version=REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
        bound_at=NOW,
    )


def _invalid_action_binding(
    session_id: str,
    source_window_fingerprint: str,
) -> SessionRequirementActionEvidenceBinding:
    return SessionRequirementActionEvidenceBinding(
        evidence_source=RequirementActionEvidenceSource.BINDING_INVALID,
        session_id=session_id,
        source_window_fingerprint=source_window_fingerprint,
        evidence_fingerprint=REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT,
        evidence_schema_version=REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION,
        evidence_policy_version=REQUIREMENT_ACTION_UNAVAILABLE_POLICY_VERSION,
        bound_at=NOW,
    )


def _r7_record(
    session_id: str,
    *,
    run_character: str,
    request_character: str,
    plan_snapshot,
    action_snapshot,
    action_binding: SessionRequirementActionEvidenceBinding,
    action_bound_at=NOW,
) -> SessionModelEnsembleRunRecord:  # type: ignore[no-untyped-def]
    base_context = _context(session_id)
    context = base_context.model_copy(
        update={
            "available_message_kinds": frozenset(
                {TextMessageKind.REQUEST, TextMessageKind.PLAN}
            ),
            "messages": (
                base_context.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            "First synthetic requirement. Second synthetic requirement. Third synthetic requirement. Omitted synthetic clause."
                        )
                    }
                ),
                base_context.messages[1].model_copy(
                    update={
                        "kind": TextMessageKind.PLAN,
                        "text": SecretStr(
                            "Implement the first synthetic requirement. Verify the synthetic result."
                        ),
                    }
                ),
            ),
        }
    )
    projected_action_snapshot = action_snapshot
    if (
        projected_action_snapshot is None
        and action_binding.evidence_source
        is RequirementActionEvidenceSource.AWAITING_REVIEW
    ):
        projected_action_snapshot = RequirementActionEvidenceSnapshot(
            session_id=session_id,
            source_window_fingerprint=context.analysis_window_fingerprint,
        )
    publication = publish_metric_states_v2(
        project_metric_states_v7(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(context).reconciliation,
            id_factory=R7_PROJECTION_IDS,
            requirement_plan_evidence=plan_snapshot,
            requirement_action_evidence=projected_action_snapshot,
            requirement_action_descriptor=DecoderDescriptor(
                provider=ProviderIdentity(key=context.provider.value),
                surface=ProviderSurface.OPERATIONAL_EVENTS,
                adapter_version=context.adapter_version,
                decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
                decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
                wire_schema_family="synthetic-safe-events",
                canonical_schema_version=context.source_schema_version,
                schema_artifact=SchemaArtifactProvenance(
                    artifact_key="synthetic-safe-events",
                    artifact_version="1",
                    kind=SchemaArtifactKind.SYNTHETIC,
                ),
                capabilities=(CapabilityKey.TOOL_EVENTS,),
            ),
            candidate_manifest_overflow=(
                action_binding.evidence_source
                is RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW
            ),
            candidate_source_incomplete=(
                action_binding.evidence_source
                is RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE
            ),
            requirement_action_binding_invalid=(
                action_binding.evidence_source
                is RequirementActionEvidenceSource.BINDING_INVALID
            ),
        )
    )
    base = _r6_record(
        session_id,
        run_character=run_character,
        request_character=request_character,
        evidence_binding=_reviewed_binding(plan_snapshot),
        snapshot=plan_snapshot,
        profile_bound_at=action_bound_at,
    )
    return SessionModelEnsembleRunRecord.model_validate(
        {
            **base.model_dump(),
            "requirement_action_evidence_binding": action_binding.model_copy(
                update={"bound_at": action_bound_at}
            ).model_dump(),
            "receipt": {
                **base.receipt.model_dump(),
                "metric_publication_v2": publication.model_dump(),
            },
        }
    )


def _confirmed_action_setup(tmp_path):  # type: ignore[no-untyped-def]
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    proposal = _proposal(source, plan_snapshot)
    repository.issue_proposal(proposal)
    decision = _decision(proposal)
    repository.decide(decision)
    snapshot = repository.snapshot(source.session_id, source.input_fingerprint)
    return database, source, plan_snapshot, repository, proposal, decision, snapshot


def _confirmed_pending_action_setup(tmp_path):  # type: ignore[no-untyped-def]
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    initial = _proposal(source, plan_snapshot)
    links = list(initial.links)
    links[1] = links[1].model_copy(
        update={"action_ids": (initial.candidates[1].action_id,)}
    )
    proposal = type(initial).model_validate(
        {**initial.model_dump(), "links": tuple(links)}
    )
    repository.issue_proposal(proposal)
    decision = _decision(proposal)
    repository.decide(decision)
    snapshot = repository.snapshot(source.session_id, source.input_fingerprint)
    return database, source, plan_snapshot, snapshot


def _bare_r7_run(
    source: SessionModelEnsembleRunRecord,
    *,
    run_character: str,
    request_character: str,
) -> SessionModelEnsembleRunRecord:
    return SessionModelEnsembleRunRecord.model_validate(
        {
            **source.model_dump(),
            "run_id": run_character * 64,
            "request_fingerprint": request_character * 64,
            "metric_profile_binding": None,
            "requirement_plan_evidence_binding": None,
            "requirement_action_evidence_binding": None,
            "receipt": {
                **source.receipt.model_dump(),
                "metric_publication_v2": None,
                "predictive_projection": None,
            },
        }
    )


def _copy_action_binding(
    connection,
    target_run_id: str,
    source_run_id: str,
) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        """INSERT INTO session_model_ensemble_requirement_action_bindings
           SELECT ?,evidence_source,session_id,source_window_fingerprint,
                  source_run_id,requirement_plan_confirmation_id,
                  requirement_plan_evidence_fingerprint,
                  candidate_manifest_fingerprint,
                  reviewed_descriptor_set_fingerprint,
                  confirmation_id,proposal_id,
                  evidence_fingerprint,evidence_schema_version,
                  evidence_policy_version,bound_at,binding_fingerprint,
                  local_only,content_persisted
           FROM session_model_ensemble_requirement_action_bindings
           WHERE run_id=?""",
        (target_run_id, source_run_id),
    )


def _copy_r7_states(
    connection,
    target_run_id: str,
    source_run_id: str,
    *,
    limit: int = 20,
) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        f"""INSERT INTO session_model_ensemble_metric_states_v2_r7({_STATE_COLUMNS})
            SELECT ?,metric_ordinal,registry_version,projection_version,metric_key,
                   contract_version,contract_fingerprint,evidence_authority,
                   value_state,explanation_code,numerator,denominator,
                   numeric_value,censoring_lower_bound,censoring_upper_bound,
                   denominator_basis,opportunity_unit_kind,capability_available,
                   source_complete,eligible_count,met_count,not_met_count,
                   pending_count,unknown_count,superseded_excluded_count,
                   distinct_owner_count,product_metric_eligible
            FROM session_model_ensemble_metric_states_v2_r7
            WHERE run_id=? ORDER BY metric_ordinal LIMIT ?""",
        (target_run_id, source_run_id, limit),
    )


def _copy_r7_seal(
    connection,
    target_run_id: str,
    source_run_id: str,
) -> None:  # type: ignore[no-untyped-def]
    columns = tuple(
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(session_model_ensemble_metric_publication_v2_seals_r7)"
        ).fetchall()
    )
    source_seal = connection.execute(
        """SELECT *
           FROM session_model_ensemble_metric_publication_v2_seals_r7
           WHERE run_id=?""",
        (source_run_id,),
    ).fetchone()
    assert source_seal is not None
    values = tuple(
        target_run_id if column == "run_id" else source_seal[column]
        for column in columns
    )
    connection.execute(
        f"""INSERT INTO session_model_ensemble_metric_publication_v2_seals_r7
            ({','.join(columns)}) VALUES({','.join('?' for _ in columns)})""",
        values,
    )


def _shape_valid_metric_substitution(
    record: SessionModelEnsembleRunRecord,
    metric_key: str,
) -> SessionModelEnsembleRunRecord:
    publication = record.receipt.metric_publication_v2
    assert publication is not None
    target = next(
        item for item in publication.metrics if item.state.metric_key == metric_key
    )
    state = target.state
    eligible = state.statistics.eligible_count
    assert eligible > 0
    state_payload = state.model_dump(mode="json")
    if state.value_state is MetricValueStateV2.KNOWN:
        substituted_met = 0 if state.statistics.met_count else eligible
        state_payload.update(
            {
                "numerator": substituted_met,
                "denominator": eligible,
                "numeric_value": substituted_met / eligible,
                "censoring_lower_bound": substituted_met / eligible,
                "censoring_upper_bound": substituted_met / eligible,
                "statistics": {
                    **state_payload["statistics"],
                    "met_count": substituted_met,
                    "not_met_count": eligible - substituted_met,
                    "pending_count": 0,
                    "unknown_count": 0,
                },
            }
        )
    else:
        assert state.value_state is MetricValueStateV2.PENDING
        pending = state.statistics.pending_count
        substituted_met = 0 if state.statistics.met_count else eligible - pending
        state_payload.update(
            {
                "censoring_lower_bound": substituted_met / eligible,
                "censoring_upper_bound": (substituted_met + pending) / eligible,
                "statistics": {
                    **state_payload["statistics"],
                    "met_count": substituted_met,
                    "not_met_count": eligible - substituted_met - pending,
                    "pending_count": pending,
                    "unknown_count": 0,
                },
            }
        )
    substituted_state = type(state).model_validate(state_payload)
    substituted_metrics = tuple(
        item.model_copy(update={"state": substituted_state})
        if item.state.metric_key == metric_key
        else item
        for item in publication.metrics
    )
    substituted_publication = publication.model_copy(
        update={"metrics": substituted_metrics}
    )
    return record.model_copy(
        update={
            "receipt": record.receipt.model_copy(
                update={"metric_publication_v2": substituted_publication}
            )
        }
    )


def _trajectory_with_saved_first(
    database,
    session_id: str,
    first: SessionModelEnsembleRunRecord,
    second: SessionModelEnsembleRunRecord,
):  # type: ignore[no-untyped-def]
    database.model_ensemble_repository().save_completed(second)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "5" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=100,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner="6" * 64,
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
        owner="6" * 64,
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


def _published_reviewed_action_trajectory(tmp_path):  # type: ignore[no-untyped-def]
    (
        database,
        source,
        plan_snapshot,
        _repository,
        _proposal_record,
        _decision_record,
        snapshot,
    ) = _confirmed_action_setup(tmp_path)
    first = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    head = _r7_record(
        source.session_id,
        run_character="d",
        request_character="2",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(
            snapshot,
            bound_at=NOW + timedelta(minutes=1),
        ),
        action_bound_at=NOW + timedelta(minutes=1),
    )
    _trajectory(database, source.session_id, first, head)
    return database, snapshot, first, head


def test_r7_reviewed_binding_round_trips_with_exact_twenty_state_seal(
    tmp_path,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()

    runs.save_completed(record)

    loaded = runs.get(record.run_id)
    assert loaded is not None
    assert (
        loaded.requirement_action_evidence_binding
        == record.requirement_action_evidence_binding
    )
    assert (
        loaded.requirement_plan_evidence_binding
        == record.requirement_plan_evidence_binding
    )
    assert (
        loaded.receipt.metric_publication_v2
        == record.receipt.metric_publication_v2
    )
    restarted = _restart(database).model_ensemble_repository().get(record.run_id)
    assert restarted == loaded
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r7 WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 20
        seal = connection.execute(
            """SELECT requirement_action_source,
                      requirement_action_source_run_id,
                      requirement_action_confirmation_id,
                      requirement_action_candidate_manifest_fingerprint,
                      requirement_action_reviewed_descriptor_set_fingerprint
               FROM session_model_ensemble_metric_publication_v2_seals_r7
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()
        assert seal == (
            "reviewed_requirement_action",
            snapshot.source_run_id,
            snapshot.confirmation_id,
            snapshot.candidate_manifest.manifest_fingerprint,
            snapshot.reviewed_descriptor_set_fingerprint,
        )


def test_r7_pending_action_bounds_round_trip_and_survive_restart(tmp_path) -> None:
    database, source, plan_snapshot, snapshot = _confirmed_pending_action_setup(
        tmp_path
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()

    runs.save_completed(record)

    loaded = runs.get(record.run_id)
    assert loaded is not None
    restarted = _restart(database).model_ensemble_repository().get(record.run_id)
    assert restarted == loaded
    publication = loaded.receipt.metric_publication_v2
    assert publication is not None
    state = next(
        item.state
        for item in publication.metrics
        if item.state.metric_key == "logic.requirement_action_traceability"
    )
    assert state.value_state is MetricValueStateV2.PENDING
    assert (
        state.statistics.eligible_count,
        state.statistics.met_count,
        state.statistics.not_met_count,
        state.statistics.pending_count,
        state.statistics.unknown_count,
    ) == (3, 1, 1, 1, 0)
    assert (
        state.censoring_lower_bound,
        state.censoring_upper_bound,
    ) == (1 / 3, 2 / 3)


@pytest.mark.parametrize(
    ("bound", "substitution"),
    (("lower", None), ("upper", None), ("lower", 0.25), ("upper", 0.9)),
)
def test_r7_pending_state_rejects_missing_or_forged_bounds_at_sqlite_boundary(
    tmp_path,
    bound: str,
    substitution: float | None,
) -> None:
    database, source, plan_snapshot, snapshot = _confirmed_pending_action_setup(
        tmp_path
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    bare = _bare_r7_run(record, run_character="0", request_character="2")
    runs.save_completed(bare)

    with database._connection() as connection:
        _copy_profile_binding(connection, bare.run_id, record.run_id)
        _copy_requirement_binding(connection, bare.run_id, record.run_id)
        _copy_action_binding(connection, bare.run_id, record.run_id)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"""INSERT INTO session_model_ensemble_metric_states_v2_r7({_STATE_COLUMNS})
                    SELECT ?,metric_ordinal,registry_version,projection_version,
                           metric_key,contract_version,contract_fingerprint,
                           evidence_authority,value_state,explanation_code,
                           numerator,denominator,numeric_value,
                           CASE WHEN ?='lower' THEN ?
                                ELSE censoring_lower_bound END,
                           CASE WHEN ?='upper' THEN ?
                                ELSE censoring_upper_bound END,
                           denominator_basis,opportunity_unit_kind,
                           capability_available,source_complete,eligible_count,
                           met_count,not_met_count,pending_count,unknown_count,
                           superseded_excluded_count,distinct_owner_count,
                           product_metric_eligible
                    FROM session_model_ensemble_metric_states_v2_r7
                    WHERE run_id=?
                      AND metric_key='logic.requirement_action_traceability'""",
                (
                    bare.run_id,
                    bound,
                    substitution,
                    bound,
                    substitution,
                    record.run_id,
                ),
            )


@pytest.mark.parametrize(
    "metric_key,error_fragment",
    (
        (
            "logic.decomposition_coverage",
            "reviewed requirement-plan graph disagrees",
        ),
        (
            "logic.requirement_action_traceability",
            "reviewed requirement-action graph disagrees",
        ),
    ),
)
def test_r7_save_rejects_shape_valid_reviewed_graph_row_substitution(
    tmp_path,
    metric_key: str,
    error_fragment: str,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    substituted = _shape_valid_metric_substitution(record, metric_key)

    with pytest.raises(DatabaseInvariantError, match=error_fragment):
        database.model_ensemble_repository().save_completed(substituted)

    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "metric_key,error_fragment",
    (
        ("logic.decomposition_coverage", "requirement-plan graph mismatch"),
        (
            "logic.requirement_action_traceability",
            "requirement-action graph mismatch",
        ),
    ),
)
def test_m57_r7_seal_rejects_shape_valid_keyed_graph_row_substitution(
    tmp_path,
    metric_key: str,
    error_fragment: str,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    bare = _bare_r7_run(record, run_character="0", request_character="2")
    runs.save_completed(bare)

    with database._connection() as connection:
        source_state = connection.execute(
            """SELECT eligible_count,met_count
               FROM session_model_ensemble_metric_states_v2_r7
               WHERE run_id=? AND metric_key=?""",
            (record.run_id, metric_key),
        ).fetchone()
        assert source_state is not None
        assert source_state["eligible_count"] > 0
        assert source_state["met_count"] > 0
        _copy_profile_binding(connection, bare.run_id, record.run_id)
        _copy_requirement_binding(connection, bare.run_id, record.run_id)
        _copy_action_binding(connection, bare.run_id, record.run_id)
        connection.execute(
            f"""INSERT INTO session_model_ensemble_metric_states_v2_r7({_STATE_COLUMNS})
                SELECT ?,metric_ordinal,registry_version,projection_version,
                       metric_key,contract_version,contract_fingerprint,
                       evidence_authority,value_state,explanation_code,
                       CASE WHEN metric_key=? AND value_state='known'
                            THEN 0 ELSE numerator END,
                       denominator,
                       CASE WHEN metric_key=? AND value_state='known'
                            THEN 0.0 ELSE numeric_value END,
                       CASE WHEN metric_key=? THEN 0.0
                            ELSE censoring_lower_bound END,
                       CASE WHEN metric_key=? AND value_state='pending'
                            THEN CAST(pending_count AS REAL)/eligible_count
                            WHEN metric_key=? THEN 0.0
                            ELSE censoring_upper_bound END,
                       denominator_basis,opportunity_unit_kind,
                       capability_available,source_complete,eligible_count,
                       CASE WHEN metric_key=? THEN 0 ELSE met_count END,
                       CASE WHEN metric_key=?
                            THEN eligible_count-pending_count
                            ELSE not_met_count END,
                       pending_count,unknown_count,superseded_excluded_count,
                       distinct_owner_count,product_metric_eligible
                FROM session_model_ensemble_metric_states_v2_r7
                WHERE run_id=? ORDER BY metric_ordinal""",
            (
                bare.run_id,
                metric_key,
                metric_key,
                metric_key,
                metric_key,
                metric_key,
                metric_key,
                metric_key,
                record.run_id,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match=error_fragment):
            _copy_r7_seal(connection, bare.run_id, record.run_id)


def test_m57_r7_action_seal_rejects_graph_consistent_forged_fraction(
    tmp_path,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    bare = _bare_r7_run(record, run_character="0", request_character="2")
    runs.save_completed(bare)

    with database._connection() as connection:
        source_state = connection.execute(
            """SELECT numerator
               FROM session_model_ensemble_metric_states_v2_r7
               WHERE run_id=?
                 AND metric_key='logic.requirement_action_traceability'""",
            (record.run_id,),
        ).fetchone()
        assert source_state is not None
        assert source_state["numerator"] > 0
        _copy_profile_binding(connection, bare.run_id, record.run_id)
        _copy_requirement_binding(connection, bare.run_id, record.run_id)
        _copy_action_binding(connection, bare.run_id, record.run_id)
        connection.execute(
            f"""INSERT INTO session_model_ensemble_metric_states_v2_r7({_STATE_COLUMNS})
                SELECT ?,metric_ordinal,registry_version,projection_version,
                       metric_key,contract_version,contract_fingerprint,
                       evidence_authority,value_state,explanation_code,
                       CASE WHEN metric_key='logic.requirement_action_traceability'
                            THEN 0 ELSE numerator END,
                       denominator,
                       CASE WHEN metric_key='logic.requirement_action_traceability'
                            THEN 0.0 ELSE numeric_value END,
                       CASE WHEN metric_key='logic.requirement_action_traceability'
                            THEN 0.0 ELSE censoring_lower_bound END,
                       CASE WHEN metric_key='logic.requirement_action_traceability'
                            THEN 0.0 ELSE censoring_upper_bound END,
                       denominator_basis,opportunity_unit_kind,
                       capability_available,source_complete,eligible_count,
                       met_count,not_met_count,pending_count,unknown_count,
                       superseded_excluded_count,distinct_owner_count,
                       product_metric_eligible
                FROM session_model_ensemble_metric_states_v2_r7
                WHERE run_id=? ORDER BY metric_ordinal""",
            (bare.run_id, record.run_id),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="requirement-action graph mismatch",
        ):
            _copy_r7_seal(connection, bare.run_id, record.run_id)


@pytest.mark.parametrize(
    "metric_key",
    (
        "logic.decomposition_coverage",
        "logic.requirement_action_traceability",
    ),
)
def test_r7_shape_valid_graph_row_tamper_fails_hydration_restart_and_watch(
    tmp_path,
    metric_key: str,
) -> None:
    database, _snapshot, _first, head = _published_reviewed_action_trajectory(
        tmp_path
    )
    with sqlite3.connect(database.path) as connection:
        source_state = connection.execute(
            """SELECT eligible_count,met_count
               FROM session_model_ensemble_metric_states_v2_r7
               WHERE run_id=? AND metric_key=?""",
            (head.run_id, metric_key),
        ).fetchone()
        assert source_state is not None
        assert source_state[0] > 0
        assert source_state[1] > 0
        connection.execute("DROP TRIGGER session_metric_r7_states_no_update")
        connection.execute(
            """UPDATE session_model_ensemble_metric_states_v2_r7
               SET numerator=CASE WHEN value_state='known' THEN 0 ELSE numerator END,
                   numeric_value=CASE WHEN value_state='known' THEN 0.0
                                      ELSE numeric_value END,
                   censoring_lower_bound=0.0,
                   censoring_upper_bound=
                     CASE WHEN value_state='pending'
                          THEN CAST(pending_count AS REAL)/eligible_count
                          ELSE 0.0 END,
                   met_count=0,
                   not_met_count=eligible_count-pending_count
               WHERE run_id=? AND metric_key=?""",
            (head.run_id, metric_key),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        database.model_ensemble_repository().get(head.run_id)
    with pytest.raises(DatabaseInvariantError):
        _restart(database).model_ensemble_repository().get(head.run_id)
    with pytest.raises(DatabaseInvariantError):
        database.model_ensemble_watch_repository().list_publications(
            "6" * 64,
            before_generation=None,
            limit=12,
        )


def test_r7_rejects_substituted_action_evidence_fingerprint_atomically(
    tmp_path,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    forged_binding = _reviewed_action_binding(snapshot).model_copy(
        update={"evidence_fingerprint": "f" * 64}
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=forged_binding,
    )

    with pytest.raises(
        DatabaseInvariantError,
        match="binding evidence fingerprint is invalid",
    ):
        database.model_ensemble_repository().save_completed(record)

    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 0


def test_r7_hydration_recomputes_keyed_action_evidence_authority(tmp_path) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    assert record.requirement_action_evidence_binding is not None
    forged_binding = record.requirement_action_evidence_binding.model_copy(
        update={"evidence_fingerprint": "f" * 64}
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_requirement_action_bindings_no_update"
        )
        connection.execute(
            """UPDATE session_model_ensemble_requirement_action_bindings
               SET evidence_fingerprint=?,binding_fingerprint=? WHERE run_id=?""",
            (
                forged_binding.evidence_fingerprint,
                _requirement_action_binding_fingerprint(forged_binding),
                record.run_id,
            ),
        )
        connection.commit()

    with pytest.raises(
        DatabaseInvariantError,
        match="binding evidence fingerprint is invalid",
    ):
        runs.get(record.run_id)
        assert connection.execute(
            """SELECT COUNT(*)
               FROM session_model_ensemble_requirement_action_bindings
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()[0] == 0


def test_r7_watch_revalidates_native_decision_authority(tmp_path) -> None:
    database, snapshot, _first, head = _published_reviewed_action_trajectory(
        tmp_path
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER requirement_action_evidence_decisions_no_update"
        )
        connection.execute(
            """UPDATE requirement_action_evidence_decisions
               SET decision_authority_fingerprint=? WHERE decision_id=?""",
            ("0" * 64, snapshot.confirmation_id),
        )
        connection.commit()

    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is invalid",
    ):
        database.model_ensemble_repository().get(head.run_id)
    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is invalid",
    ):
        database.model_ensemble_watch_repository().list_publications(
            "6" * 64,
            before_generation=None,
            limit=12,
        )


def test_r7_watch_revalidates_descriptor_binding_authority(tmp_path) -> None:
    database, _snapshot, _first, head = _published_reviewed_action_trajectory(
        tmp_path
    )
    binding = head.requirement_action_evidence_binding
    assert binding is not None
    forged = binding.model_copy(
        update={"reviewed_descriptor_set_fingerprint": "0" * 64}
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_requirement_action_bindings_no_update"
        )
        connection.execute(
            """UPDATE session_model_ensemble_requirement_action_bindings
               SET reviewed_descriptor_set_fingerprint=?,binding_fingerprint=?
               WHERE run_id=?""",
            (
                forged.reviewed_descriptor_set_fingerprint,
                _requirement_action_binding_fingerprint(forged),
                head.run_id,
            ),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="binding is cross-bound"):
        database.model_ensemble_repository().get(head.run_id)
    with pytest.raises(DatabaseInvariantError, match="binding is cross-bound"):
        database.model_ensemble_watch_repository().list_publications(
            "6" * 64,
            before_generation=None,
            limit=12,
        )


@pytest.mark.parametrize(
    "binding_factory",
    (
        _unavailable_action_binding,
        _awaiting_action_binding,
        _overflow_action_binding,
        _incomplete_action_binding,
        _invalid_action_binding,
    ),
)
def test_r7_nonreviewed_binding_round_trips_without_false_authority(
    tmp_path,
    binding_factory,
) -> None:  # type: ignore[no-untyped-def]
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    binding = binding_factory(source.session_id, source.input_fingerprint)
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=None,
        action_binding=binding,
    )
    runs = database.model_ensemble_repository()

    runs.save_completed(record)

    loaded = runs.get(record.run_id)
    assert loaded is not None
    assert loaded.requirement_action_evidence_binding == binding
    with sqlite3.connect(database.path) as connection:
        row = connection.execute(
            """SELECT requirement_action_source,
                      requirement_action_source_run_id,
                      requirement_action_confirmation_id,
                      requirement_action_reviewed_descriptor_set_fingerprint,
                      requirement_action_evidence_fingerprint
               FROM session_model_ensemble_metric_publication_v2_seals_r7
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()
    assert row == (
        binding.evidence_source.value,
        None,
        None,
        None,
        binding.evidence_fingerprint,
    )


@pytest.mark.parametrize(
    "binding_factory,substituted_fingerprint",
    (
        (
            _overflow_action_binding,
            REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
        ),
        (
            _incomplete_action_binding,
            REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT,
        ),
        (
            _invalid_action_binding,
            REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
        ),
    ),
)
def test_r7_closed_candidate_markers_reject_sql_substitution(
    tmp_path,
    binding_factory,
    substituted_fingerprint: str,
) -> None:  # type: ignore[no-untyped-def]
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    binding = binding_factory(source.session_id, source.input_fingerprint)
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=None,
        action_binding=binding,
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    bare = _bare_r7_run(record, run_character="0", request_character="2")
    runs.save_completed(bare)

    with database._connection() as connection:
        _copy_profile_binding(connection, bare.run_id, record.run_id)
        _copy_requirement_binding(connection, bare.run_id, record.run_id)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """INSERT INTO session_model_ensemble_requirement_action_bindings
                   SELECT ?,evidence_source,session_id,source_window_fingerprint,
                          source_run_id,requirement_plan_confirmation_id,
                          requirement_plan_evidence_fingerprint,
                          candidate_manifest_fingerprint,
                          reviewed_descriptor_set_fingerprint,
                          confirmation_id,proposal_id,?,evidence_schema_version,
                          evidence_policy_version,bound_at,binding_fingerprint,
                          local_only,content_persisted
                   FROM session_model_ensemble_requirement_action_bindings
                   WHERE run_id=?""",
                (bare.run_id, substituted_fingerprint, record.run_id),
            )


def test_r7_binding_invalid_tamper_is_rejected_by_run_and_watch_reads(
    tmp_path,
) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    first = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=None,
        action_binding=_invalid_action_binding(
            source.session_id,
            source.input_fingerprint,
        ),
    )
    second = _r7_record(
        source.session_id,
        run_character="d",
        request_character="2",
        plan_snapshot=plan_snapshot,
        action_snapshot=None,
        action_binding=_invalid_action_binding(
            source.session_id,
            source.input_fingerprint,
        ),
        action_bound_at=NOW + timedelta(minutes=1),
    )
    _trajectory(database, source.session_id, first, second)
    original = second.requirement_action_evidence_binding
    assert original is not None
    forged = original.model_copy(
        update={
            "evidence_source": RequirementActionEvidenceSource.AWAITING_REVIEW,
            "evidence_fingerprint": (
                REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT
            ),
            "evidence_schema_version": (
                REQUIREMENT_ACTION_AWAITING_REVIEW_SCHEMA_VERSION
            ),
        }
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_requirement_action_bindings_no_update"
        )
        connection.execute(
            """UPDATE session_model_ensemble_requirement_action_bindings
               SET evidence_source=?,evidence_fingerprint=?,
                   evidence_schema_version=?,binding_fingerprint=?
               WHERE run_id=?""",
            (
                forged.evidence_source.value,
                forged.evidence_fingerprint,
                forged.evidence_schema_version,
                _requirement_action_binding_fingerprint(forged),
                second.run_id,
            ),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        database.model_ensemble_repository().get(second.run_id)
    with pytest.raises(DatabaseInvariantError):
        database.model_ensemble_watch_repository().list_publications(
            "6" * 64,
            before_generation=None,
            limit=12,
        )


def test_r7_save_is_atomic_when_exact_seal_is_rejected(tmp_path) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    with database._connection() as connection:
        connection.execute(
            """CREATE TRIGGER synthetic_reject_r7_seal
               BEFORE INSERT ON session_model_ensemble_metric_publication_v2_seals_r7
               BEGIN SELECT RAISE(ABORT,'synthetic r7 seal rejection'); END"""
        )
        connection.commit()

    with pytest.raises(DatabaseError):
        database.model_ensemble_repository().save_completed(record)

    with sqlite3.connect(database.path) as connection:
        for table in (
            "session_model_ensemble_runs",
            "session_model_ensemble_requirement_action_bindings",
            "session_model_ensemble_metric_states_v2_r7",
            "session_model_ensemble_metric_publication_v2_seals_r7",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (record.run_id,)
            ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "table,projection_version",
    (
        ("session_model_ensemble_metric_states_v2", "metric-contract-v2-projection-1"),
        ("session_model_ensemble_metric_states_v2_r2", "metric-contract-v2-projection-2"),
        ("session_model_ensemble_metric_states_v2_r3", "metric-contract-v2-projection-3"),
        ("session_model_ensemble_metric_states_v2_r4", "metric-contract-v2-projection-4"),
        ("session_model_ensemble_metric_states_v2_r5", "metric-contract-v2-projection-5"),
        ("session_model_ensemble_metric_states_v2_r6", "metric-contract-v2-projection-6"),
    ),
)
def test_r7_first_rejects_every_frozen_projection_state(
    tmp_path,
    table: str,
    projection_version: str,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    database.model_ensemble_repository().save_completed(record)

    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="projection identity conflict"):
            connection.execute(
                f"""INSERT INTO {table}
                    SELECT run_id,metric_ordinal,registry_version,?,metric_key,
                           contract_version,contract_fingerprint,evidence_authority,
                           value_state,explanation_code,numerator,denominator,
                           numeric_value,censoring_lower_bound,censoring_upper_bound,
                           denominator_basis,opportunity_unit_kind,capability_available,
                           source_complete,eligible_count,met_count,not_met_count,
                           pending_count,unknown_count,superseded_excluded_count,
                           distinct_owner_count,product_metric_eligible
                    FROM session_model_ensemble_metric_states_v2_r7
                    WHERE run_id=? LIMIT 1""",
                (projection_version, record.run_id),
            )


@pytest.mark.parametrize(
    "table,projection_version,needs_profile,needs_plan",
    (
        (
            "session_model_ensemble_metric_states_v2",
            "metric-contract-v2-projection-1",
            False,
            False,
        ),
        (
            "session_model_ensemble_metric_states_v2_r2",
            "metric-contract-v2-projection-2",
            False,
            False,
        ),
        (
            "session_model_ensemble_metric_states_v2_r3",
            "metric-contract-v2-projection-3",
            False,
            False,
        ),
        (
            "session_model_ensemble_metric_states_v2_r4",
            "metric-contract-v2-projection-4",
            False,
            False,
        ),
        (
            "session_model_ensemble_metric_states_v2_r5",
            "metric-contract-v2-projection-5",
            True,
            False,
        ),
        (
            "session_model_ensemble_metric_states_v2_r6",
            "metric-contract-v2-projection-6",
            True,
            True,
        ),
    ),
)
def test_every_frozen_projection_state_rejects_r7_binding_inserted_second(
    tmp_path,
    table: str,
    projection_version: str,
    needs_profile: bool,
    needs_plan: bool,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    r7 = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(r7)
    bare = _bare_r7_run(r7, run_character="0", request_character="2")
    runs.save_completed(bare)

    with database._connection() as connection:
        if needs_profile:
            _copy_profile_binding(connection, bare.run_id, r7.run_id)
        if needs_plan:
            _copy_requirement_binding(connection, bare.run_id, r7.run_id)
        connection.execute(
            f"""INSERT INTO {table}({_STATE_COLUMNS})
                SELECT ?,metric_ordinal,registry_version,?,metric_key,
                       contract_version,contract_fingerprint,evidence_authority,
                       value_state,explanation_code,numerator,denominator,
                       numeric_value,censoring_lower_bound,censoring_upper_bound,
                       denominator_basis,opportunity_unit_kind,capability_available,
                       source_complete,eligible_count,met_count,not_met_count,
                       pending_count,unknown_count,superseded_excluded_count,
                       distinct_owner_count,product_metric_eligible
                FROM session_model_ensemble_metric_states_v2_r7
                WHERE run_id=? LIMIT 1""",
            (bare.run_id, projection_version, r7.run_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="projection identity conflict"):
            _copy_action_binding(connection, bare.run_id, r7.run_id)


def test_r7_seal_rejects_nineteen_state_partial_publication(tmp_path) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    r7 = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(r7)
    bare = _bare_r7_run(r7, run_character="0", request_character="2")
    runs.save_completed(bare)

    with database._connection() as connection:
        _copy_profile_binding(connection, bare.run_id, r7.run_id)
        _copy_requirement_binding(connection, bare.run_id, r7.run_id)
        _copy_action_binding(connection, bare.run_id, r7.run_id)
        _copy_r7_states(connection, bare.run_id, r7.run_id, limit=19)
        columns = tuple(
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(session_model_ensemble_metric_publication_v2_seals_r7)"
            ).fetchall()
        )
        source_seal = connection.execute(
            """SELECT *
               FROM session_model_ensemble_metric_publication_v2_seals_r7
               WHERE run_id=?""",
            (r7.run_id,),
        ).fetchone()
        assert source_seal is not None
        values = tuple(
            bare.run_id if column == "run_id" else source_seal[column]
            for column in columns
        )
        with pytest.raises(sqlite3.IntegrityError, match="r7 publication is incomplete"):
            connection.execute(
                f"""INSERT INTO session_model_ensemble_metric_publication_v2_seals_r7
                    ({','.join(columns)}) VALUES({','.join('?' for _ in columns)})""",
                values,
            )


@pytest.mark.parametrize(
    "column,value",
    (
        ("candidate_manifest_fingerprint", "0" * 64),
        ("reviewed_descriptor_set_fingerprint", "0" * 64),
        ("bound_at", "2042-04-05T12:01:00.000000+00:00"),
    ),
)
def test_r7_binding_tamper_is_detected_on_hydration(
    tmp_path,
    column: str,
    value: str,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_requirement_action_bindings_no_update"
        )
        connection.execute(
            f"""UPDATE session_model_ensemble_requirement_action_bindings
                SET {column}=? WHERE run_id=?""",
            (value, record.run_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        runs.get(record.run_id)


def test_r7_descriptor_seal_tamper_is_detected_on_hydration(tmp_path) -> None:
    database, _snapshot, _first, record = _published_reviewed_action_trajectory(
        tmp_path
    )
    runs = database.model_ensemble_repository()
    with sqlite3.connect(database.path) as connection:
        connection.execute("DROP TRIGGER session_metric_r7_seals_no_update")
        connection.execute(
            """UPDATE session_model_ensemble_metric_publication_v2_seals_r7
               SET requirement_action_reviewed_descriptor_set_fingerprint=?
               WHERE run_id=?""",
            ("0" * 64, record.run_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="publication seal is invalid"):
        runs.get(record.run_id)
    with pytest.raises(
        DatabaseInvariantError,
        match="trajectory requirement-action authority is invalid",
    ):
        database.model_ensemble_watch_repository().list_publications(
            "6" * 64,
            before_generation=None,
            limit=12,
        )


def test_source_run_privacy_delete_cascades_r7_and_prevents_resurrection(
    tmp_path,
) -> None:
    database, source, plan_snapshot, repository, proposal, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    record = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)

    assert runs.delete_for_privacy(source.run_id) is True

    assert runs.get(source.run_id) is None
    assert runs.get(record.run_id) is None
    assert repository.get_proposal(proposal.proposal_id) is None
    with sqlite3.connect(database.path) as connection:
        for table in (
            "requirement_action_evidence_proposals",
            "requirement_action_evidence_candidates",
            "requirement_action_evidence_decisions",
            "session_model_ensemble_requirement_action_bindings",
            "session_model_ensemble_metric_states_v2_r7",
            "session_model_ensemble_metric_publication_v2_seals_r7",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(RequirementActionConflictError):
        repository.issue_proposal(proposal)


def test_same_action_authority_is_comparable_despite_fresh_binding_time(
    tmp_path,
) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    first = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    second = _r7_record(
        source.session_id,
        run_character="d",
        request_character="2",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(
            snapshot, bound_at=NOW + timedelta(minutes=1)
        ),
        action_bound_at=NOW + timedelta(minutes=1),
    )

    trajectory = _trajectory(database, source.session_id, first, second)

    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is True
    with sqlite3.connect(database.path) as connection:
        values = connection.execute(
            """SELECT binding_fingerprint
               FROM session_model_ensemble_requirement_action_bindings
               WHERE run_id IN (?,?)""",
            (first.run_id, second.run_id),
        ).fetchall()
    assert len({item[0] for item in values}) == 2


def test_distinct_candidate_availability_markers_are_incomparable(
    tmp_path,
) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    first = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=None,
        action_binding=_overflow_action_binding(
            source.session_id,
            source.input_fingerprint,
        ),
    )
    second = _r7_record(
        source.session_id,
        run_character="d",
        request_character="2",
        plan_snapshot=plan_snapshot,
        action_snapshot=None,
        action_binding=_incomplete_action_binding(
            source.session_id,
            source.input_fingerprint,
        ),
        action_bound_at=NOW + timedelta(minutes=1),
    )

    trajectory = _trajectory(database, source.session_id, first, second)

    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is False


def test_changed_action_confirmation_and_manifest_break_comparability(
    tmp_path,
) -> None:
    (
        database,
        source,
        plan_snapshot,
        repository,
        _proposal_record,
        first_decision,
        first_snapshot,
    ) = _confirmed_action_setup(tmp_path)
    first = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=first_snapshot,
        action_binding=_reviewed_action_binding(first_snapshot),
    )
    database.model_ensemble_repository().save_completed(first)
    successor = _proposal(first, plan_snapshot, suffix="7").model_copy(
        update={
            "expected_predecessor_confirmation_id": first_decision.decision_id,
            "payload_sha256": "0" * 64,
            "idempotency_key_digest": "1" * 64,
            "command_fingerprint": "2" * 64,
            "created_at": NOW + timedelta(minutes=4),
        }
    )
    repository.issue_proposal(successor)
    successor_decision = _decision(
        successor,
        suffix="e",
        idempotency_character="3",
        command_character="4",
    ).model_copy(
        update={
            "decided_at": NOW + timedelta(minutes=5),
        }
    )
    repository.decide(successor_decision)
    second_snapshot = repository.snapshot(
        source.session_id, source.input_fingerprint
    )
    assert second_snapshot.confirmation_id != first_snapshot.confirmation_id
    assert second_snapshot.candidate_manifest is not None
    assert first_snapshot.candidate_manifest is not None
    assert (
        second_snapshot.candidate_manifest.manifest_fingerprint
        != first_snapshot.candidate_manifest.manifest_fingerprint
    )
    second = _r7_record(
        source.session_id,
        run_character="d",
        request_character="2",
        plan_snapshot=plan_snapshot,
        action_snapshot=second_snapshot,
        action_binding=_reviewed_action_binding(
            second_snapshot, bound_at=NOW + timedelta(minutes=6)
        ),
        action_bound_at=NOW + timedelta(minutes=6),
    )

    trajectory = _trajectory_with_saved_first(
        database, source.session_id, first, second
    )

    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is False


def test_r6_and_r7_trajectory_points_are_incomparable(tmp_path) -> None:
    database, source, plan_snapshot, _repository, _proposal_record, _decision_record, snapshot = (
        _confirmed_action_setup(tmp_path)
    )
    r7 = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan_snapshot,
        action_snapshot=snapshot,
        action_binding=_reviewed_action_binding(snapshot),
    )
    r6 = _r6_record(
        source.session_id,
        run_character="c",
        request_character="2",
        evidence_binding=_reviewed_binding(plan_snapshot),
        snapshot=plan_snapshot,
    )

    trajectory = _trajectory(database, source.session_id, r6, r7)

    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is False
