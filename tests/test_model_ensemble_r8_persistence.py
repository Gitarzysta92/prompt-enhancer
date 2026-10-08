"""Projection r8 atomic M58 run-binding persistence attacks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
import sqlite3
import threading

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.metric_projection_v8 import (
    project_metric_states_v8,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.model_ensemble import (
    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
    SessionModelEnsembleTypedMetricReceipt,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
    project_objective_metric_overrides_v4,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
)
from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
    REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
    REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
    REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
    REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
    REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
    RequirementAcceptanceOutcome,
    RequirementVerificationOutcome,
)
from prompt_enhancer.application.analysis.requirement_verification_persistence import (
    REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
    RequirementVerificationConflictError,
    RequirementVerificationPersistenceError,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.session_model_ensemble import (
    REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
    RequirementVerificationEvidenceSource,
    SessionModelEnsembleRunRecord,
    SessionRequirementVerificationEvidenceBinding,
    VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID,
    VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION,
    VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION,
    validate_requirement_verification_binding_metric_state,
)
from prompt_enhancer.application.analysis.text_contracts import TextMessageKind
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.database import DatabaseError, DatabaseInvariantError
from prompt_enhancer.infrastructure.sqlite.model_ensemble import (
    _metric_projection_fingerprint,
    _requirement_verification_binding_fingerprint,
)

from test_model_ensemble_r5_profile_persistence import NOW, _STATE_COLUMNS
from test_model_ensemble_r7_persistence import (
    R7_PROJECTION_IDS,
    _confirmed_action_setup,
    _r7_record,
    _reviewed_action_binding,
    _trajectory_with_saved_first,
)
from test_probabilistic_metric_persistence import IDS, _context
from test_requirement_action_evidence_persistence import _restart
from test_requirement_plan_evidence_persistence import ARTIFACT_IDS
from test_requirement_verification_evidence_persistence import (
    _objective_command,
    _reviewed_setup as _verification_reviewed_setup,
    _service,
)


def _projection_context(session_id: str):  # type: ignore[no-untyped-def]
    base = _context(session_id)
    return base.model_copy(
        update={
            "available_message_kinds": frozenset(
                {TextMessageKind.REQUEST, TextMessageKind.PLAN}
            ),
            "messages": (
                base.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            "First synthetic requirement. Second synthetic requirement. "
                            "Third synthetic requirement. Omitted synthetic clause."
                        )
                    }
                ),
                base.messages[1].model_copy(
                    update={
                        "kind": TextMessageKind.PLAN,
                        "text": SecretStr(
                            "Implement the first synthetic requirement. "
                            "Verify the synthetic result."
                        ),
                    }
                ),
            ),
        }
    )


def _descriptor(context):  # type: ignore[no-untyped-def]
    return DecoderDescriptor(
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
    )


def _verification_binding(snapshot):  # type: ignore[no-untyped-def]
    evidence = snapshot.evidence
    opportunities = evidence.opportunities
    results = evidence.verification_results
    acceptances = evidence.acceptance_authorities
    resolved = sum(
        item.outcome
        in {RequirementVerificationOutcome.PASSED, RequirementVerificationOutcome.FAILED}
        for item in results
    ) + sum(
        item.outcome
        in {RequirementAcceptanceOutcome.ACCEPTED, RequirementAcceptanceOutcome.REJECTED}
        for item in acceptances
    )
    met = sum(
        item.outcome is RequirementVerificationOutcome.PASSED for item in results
    ) + sum(
        item.outcome is RequirementAcceptanceOutcome.ACCEPTED
        for item in acceptances
    )
    draft = SessionRequirementVerificationEvidenceBinding(
        evidence_source=RequirementVerificationEvidenceSource.PERSISTED_EVIDENCE,
        session_id=opportunities.session_id,
        source_window_fingerprint=opportunities.source_window_fingerprint,
        requirement_plan_confirmation_id=(
            opportunities.requirement_plan_confirmation_id
        ),
        requirement_plan_proposal_id=opportunities.requirement_plan_proposal_id,
        requirement_plan_evidence_fingerprint=(
            opportunities.requirement_plan_evidence_fingerprint
        ),
        requirement_plan_schema_version=(
            opportunities.requirement_plan_schema_version
        ),
        requirement_plan_policy_version=(
            opportunities.requirement_plan_policy_version
        ),
        requirement_plan_review_rubric_version=(
            opportunities.requirement_plan_review_rubric_version
        ),
        opportunity_count=len(opportunities.opportunities),
        opportunity_set_fingerprint=opportunities.opportunity_set_fingerprint,
        evidence_set_fingerprint=evidence.evidence_set_fingerprint,
        through_revision=snapshot.revision,
        authority_head_count=len(snapshot.authority_heads),
        objective_result_count=len(results),
        native_acceptance_count=len(acceptances),
        resolved_opportunity_count=resolved,
        met_requirement_count=met,
        opportunity_issuer_version=REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
        result_issuer_version=REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
        acceptance_issuer_version=REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
        evidence_schema_version=REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        evidence_policy_version=REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        persistence_schema_version=REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
        evidence_projection_version=REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
        objective_projection_version=OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
        binding_schema_version=REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
        binding_fingerprint="0" * 64,
        bound_at=NOW,
    )
    return draft.model_copy(
        update={
            "binding_fingerprint": ARTIFACT_IDS.fingerprint(
                REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
                draft.authority_identity(),
            )
        }
    )


def _unavailable_verification_binding(
    session_id: str,
    source_window_fingerprint: str,
) -> SessionRequirementVerificationEvidenceBinding:
    draft = SessionRequirementVerificationEvidenceBinding(
        evidence_source=RequirementVerificationEvidenceSource.UNAVAILABLE,
        session_id=session_id,
        source_window_fingerprint=source_window_fingerprint,
        opportunity_issuer_version=REQUIREMENT_VERIFICATION_OPPORTUNITY_ISSUER_VERSION,
        result_issuer_version=REQUIREMENT_VERIFICATION_RESULT_ISSUER_VERSION,
        acceptance_issuer_version=REQUIREMENT_ACCEPTANCE_AUTHORITY_ISSUER_VERSION,
        evidence_schema_version=REQUIREMENT_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        evidence_policy_version=REQUIREMENT_VERIFICATION_EVIDENCE_POLICY_VERSION,
        persistence_schema_version=REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
        evidence_projection_version=REQUIREMENT_VERIFICATION_PROJECTION_VERSION,
        objective_projection_version=OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
        binding_fingerprint="0" * 64,
        bound_at=NOW,
    )
    return draft.model_copy(
        update={
            "binding_fingerprint": ARTIFACT_IDS.fingerprint(
                REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
                draft.authority_identity(),
            )
        }
    )


def _r8_typed_metrics(typed_metrics, publication):  # type: ignore[no-untyped-def]
    del typed_metrics
    projected = []
    for item in publication.metrics:
        state = item.state
        resolved = state.statistics.met_count + state.statistics.not_met_count
        eligible = state.statistics.eligible_count
        values = {
            "metric_key": state.metric_key,
            "metric_version": 1,
            "value_state": (
                "unknown"
                if state.value_state.value == "pending"
                else state.value_state.value
            ),
            "numerator": state.numerator,
            "denominator": state.denominator,
            "numeric_value": state.numeric_value,
            "observed_message_count": resolved,
            "eligible_message_count": eligible,
            "coverage": 0.0 if eligible == 0 else resolved / eligible,
            "explanation_code": state.explanation_code,
            "error_code": (
                "synthetic-projection-error"
                if state.value_state.value == "execution_error"
                else None
            ),
            "projection_source": "deterministic_typed_contract",
            "metric_schema_version": 1,
            "engine_version": "synthetic-typed-engine-v1",
            "algorithm_id": "synthetic-typed-algorithm",
            "algorithm_version": "1",
            "rubric_version": "synthetic-no-rubric-v1",
            "calibration_state": "not_assessed",
            "product_metric_eligible": False,
        }
        if state.metric_key == "outcome.verified_requirement_coverage":
            values.update(
                {
                    "engine_version": OBJECTIVE_METRIC_PROJECTION_V4_VERSION,
                    "algorithm_id": VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID,
                    "algorithm_version": (
                        VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION
                    ),
                    "rubric_version": VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION,
                }
            )
        projected.append(SessionModelEnsembleTypedMetricReceipt.model_validate(values))
    return tuple(projected)


def _r8_record(
    session_id: str,
    *,
    run_character: str,
    request_character: str,
    plan_snapshot,
    action_snapshot,
    verification_snapshot,
) -> SessionModelEnsembleRunRecord:  # type: ignore[no-untyped-def]
    context = _projection_context(session_id)
    verification_evidence = (
        None if verification_snapshot is None else verification_snapshot.evidence
    )
    objective_overrides = project_objective_metric_overrides_v4(
        None,
        None,
        requirement_plan_evidence=plan_snapshot,
        requirement_verification_evidence=verification_evidence,
        identifiers=ARTIFACT_IDS,
    )
    publication = publish_metric_states_v2(
        project_metric_states_v8(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=R7_PROJECTION_IDS,
            objective_overrides=objective_overrides,
            requirement_plan_evidence=plan_snapshot,
            requirement_action_evidence=action_snapshot,
            requirement_action_descriptor=_descriptor(context),
        )
    )
    base = _r7_record(
        session_id,
        run_character=run_character,
        request_character=request_character,
        plan_snapshot=plan_snapshot,
        action_snapshot=action_snapshot,
        action_binding=_reviewed_action_binding(action_snapshot),
    )
    return SessionModelEnsembleRunRecord.model_validate(
        {
            **base.model_dump(),
            "requirement_verification_evidence_binding": (
                (
                    _unavailable_verification_binding(
                        session_id,
                        context.analysis_window_fingerprint,
                    )
                    if verification_snapshot is None
                    else _verification_binding(verification_snapshot)
                ).model_dump()
            ),
            "receipt": {
                **base.receipt.model_dump(),
                "metric_projection_version": (
                    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
                ),
                "metric_projection_completed_at": (
                    base.receipt.completed_at
                    + timedelta(seconds=ord(run_character))
                ),
                "typed_metrics": _r8_typed_metrics(
                    base.receipt.typed_metrics,
                    publication,
                ),
                "metric_publication_v2": publication.model_dump(),
            },
        }
    )


def _r8_setup(tmp_path):  # type: ignore[no-untyped-def]
    (
        database,
        source,
        plan_snapshot,
        _action_repository,
        _proposal,
        _decision,
        action_snapshot,
    ) = _confirmed_action_setup(tmp_path)
    verification_service = _service(database)
    verification_snapshot, created = (
        verification_service.issue_current_opportunities(source.session_id)
    )
    assert created is True
    assert verification_snapshot.revision == 0
    return (
        database,
        source,
        plan_snapshot,
        action_snapshot,
        verification_service,
        verification_snapshot,
    )


def test_r8_revision_zero_round_trips_then_hydrates_historical_after_append(
    tmp_path,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()

    runs.save_completed(record)

    loaded = runs.get(record.run_id)
    assert loaded is not None
    assert (
        loaded.requirement_verification_evidence_binding
        == record.requirement_verification_evidence_binding
    )
    assert (
        loaded.receipt.metric_publication_v2
        == record.receipt.metric_publication_v2
    )
    restarted = _restart(database).model_ensemble_repository().get(record.run_id)
    assert restarted == loaded
    appended, applied = service.append_objective_result(
        session_id=source.session_id,
        command=_objective_command(revision_zero, 0, sequence=1),
        idempotency_key="synthetic-r8-after-save-0001",
    )
    assert applied is True
    assert appended.revision == 1
    historical = runs.get(record.run_id)
    assert historical is not None
    assert (
        historical.requirement_verification_evidence_binding
        == record.requirement_verification_evidence_binding
    )
    assert (
        historical.receipt.metric_publication_v2
        == record.receipt.metric_publication_v2
    )
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r8 WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 20
        assert connection.execute(
            "SELECT through_revision FROM session_model_ensemble_requirement_verification_bindings WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 0


def test_r8_save_rejects_a_missing_typed_projection_atomically(tmp_path) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    forged = record.model_copy(
        update={
            "receipt": record.receipt.model_copy(update={"typed_metrics": ()})
        }
    )

    with pytest.raises(DatabaseInvariantError, match="typed metric projection"):
        database.model_ensemble_repository().save_completed(forged)

    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 0


def test_r8_seal_rejects_missing_typed_rows_when_python_guard_is_bypassed(
    tmp_path,
    monkeypatch,
) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    monkeypatch.setattr(
        type(runs),
        "_insert_metric_projection",
        staticmethod(lambda connection, run: None),
    )

    with pytest.raises((DatabaseError, sqlite3.IntegrityError)):
        runs.save_completed(record)

    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs WHERE run_id=?",
            (record.run_id,),
        ).fetchone()[0] == 0


def test_r8_hydration_rejects_a_resealed_stale_verified_typed_receipt(
    tmp_path,
) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    stale_metrics = tuple(
        item.model_copy(update={"algorithm_version": "3"})
        if item.metric_key == "outcome.verified_requirement_coverage"
        else item
        for item in record.receipt.typed_metrics
    )
    stale_receipt = record.receipt.model_copy(
        update={"typed_metrics": stale_metrics}
    )
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_typed_metrics_no_update"
        )
        connection.execute(
            "DROP TRIGGER session_model_ensemble_typed_metric_seals_no_update"
        )
        connection.execute(
            """UPDATE session_model_ensemble_typed_metrics
               SET algorithm_version='3'
               WHERE run_id=? AND metric_key=?""",
            (record.run_id, "outcome.verified_requirement_coverage"),
        )
        connection.execute(
            """UPDATE session_model_ensemble_typed_metric_seals
               SET projection_fingerprint=? WHERE run_id=?""",
            (_metric_projection_fingerprint(stale_receipt), record.run_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="verified typed metric"):
        runs.get(record.run_id)


def test_reviewed_r6_with_unavailable_verification_reader_saves_and_restarts(
    tmp_path,
) -> None:
    (
        database,
        source,
        plan,
        _action_repository,
        _proposal,
        _decision,
        action,
    ) = _confirmed_action_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=None,
    )
    binding = record.requirement_verification_evidence_binding
    assert binding is not None
    assert (
        binding.evidence_source
        is RequirementVerificationEvidenceSource.UNAVAILABLE
    )
    assert binding.requirement_plan_confirmation_id is None
    publication = record.receipt.metric_publication_v2
    assert publication is not None
    verified = next(
        item.state
        for item in publication.metrics
        if item.state.metric_key == "outcome.verified_requirement_coverage"
    )
    assert verified.value_state.value == "unknown"
    assert verified.explanation_code == (
        "requirement_verification_evidence_unavailable"
    )
    assert verified.statistics.eligible_count == len(plan.requirements)

    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    loaded = runs.get(record.run_id)
    restarted = _restart(database).model_ensemble_repository().get(record.run_id)

    assert loaded is not None
    assert restarted == loaded
    assert (
        loaded.requirement_verification_evidence_binding
        == record.requirement_verification_evidence_binding
    )
    assert (
        loaded.receipt.metric_publication_v2
        == record.receipt.metric_publication_v2
    )


def test_r8_watch_keeps_an_exact_revision_comparable_across_fresh_runs(
    tmp_path,
) -> None:
    database, source, plan, action, _service, revision_zero = _r8_setup(tmp_path)
    first = _r8_record(
        source.session_id,
        run_character="c",
        request_character="3",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    second = _r8_record(
        source.session_id,
        run_character="d",
        request_character="4",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    database.model_ensemble_repository().save_completed(first)

    trajectory = _trajectory_with_saved_first(
        database,
        source.session_id,
        first,
        second,
    )

    assert len(trajectory.points) == 2
    assert all(point.comparable_to_head for point in trajectory.points)


def test_r8_watch_treats_a_changed_verification_revision_as_incomparable(
    tmp_path,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    first = _r8_record(
        source.session_id,
        run_character="c",
        request_character="3",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    database.model_ensemble_repository().save_completed(first)
    revision_one, applied = service.append_objective_result(
        session_id=source.session_id,
        command=_objective_command(revision_zero, 0, sequence=1),
        idempotency_key="synthetic-r8-watch-revision-0001",
    )
    assert applied is True
    assert revision_one.revision == 1
    second = _r8_record(
        source.session_id,
        run_character="d",
        request_character="4",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_one,
    )

    trajectory = _trajectory_with_saved_first(
        database,
        source.session_id,
        first,
        second,
    )

    assert len(trajectory.points) == 2
    assert trajectory.points[0].run_id == second.run_id
    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].run_id == first.run_id
    assert trajectory.points[1].comparable_to_head is False


def test_m58_append_before_r8_save_rejects_and_rolls_back_complete_run(
    tmp_path,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    service.append_objective_result(
        session_id=source.session_id,
        command=_objective_command(revision_zero, 0, sequence=1),
        idempotency_key="synthetic-r8-before-save-0001",
    )

    with pytest.raises((DatabaseInvariantError, sqlite3.IntegrityError)):
        database.model_ensemble_repository().save_completed(record)

    with sqlite3.connect(database.path) as connection:
        for table in (
            "session_model_ensemble_runs",
            "session_model_ensemble_requirement_verification_bindings",
            "session_model_ensemble_metric_states_v2_r8",
            "session_model_ensemble_metric_publication_v2_seals_r8",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",  # noqa: S608
                (record.run_id,),
            ).fetchone()[0] == 0


def test_r8_current_nonzero_revision_round_trips_exact_authority_counts(
    tmp_path,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    revision_one, applied = service.append_objective_result(
        session_id=source.session_id,
        command=_objective_command(revision_zero, 0, sequence=1),
        idempotency_key="synthetic-r8-current-revision-0001",
    )
    assert applied is True
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_one,
    )

    runs = database.model_ensemble_repository()
    runs.save_completed(record)

    loaded = runs.get(record.run_id)
    assert loaded is not None
    binding = loaded.requirement_verification_evidence_binding
    assert binding is not None
    assert (
        binding.through_revision,
        binding.authority_head_count,
        binding.objective_result_count,
        binding.native_acceptance_count,
        binding.resolved_opportunity_count,
        binding.met_requirement_count,
    ) == (1, 1, 1, 0, 1, 1)
    publication = loaded.receipt.metric_publication_v2
    assert publication is not None
    state = next(
        item.state
        for item in publication.metrics
        if item.state.metric_key == "outcome.verified_requirement_coverage"
    )
    assert (
        state.statistics.eligible_count,
        state.statistics.met_count,
        state.statistics.not_met_count,
        state.statistics.unknown_count,
    ) == (3, 1, 0, 2)


def test_r8_and_legacy_publication_identities_reject_mixing_in_both_orders(
    tmp_path,
) -> None:
    (
        database,
        source,
        plan,
        _action_repository,
        _proposal,
        _decision,
        action,
    ) = _confirmed_action_setup(tmp_path)
    legacy = _r7_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        action_binding=_reviewed_action_binding(action),
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(legacy)
    revision_zero, _ = _service(database).issue_current_opportunities(
        source.session_id
    )
    current = _r8_record(
        source.session_id,
        run_character="d",
        request_character="2",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs.save_completed(current)

    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"""INSERT INTO session_model_ensemble_metric_states_v2_r7({_STATE_COLUMNS})
                    SELECT ?,metric_ordinal,registry_version,projection_version,
                           metric_key,contract_version,contract_fingerprint,
                           evidence_authority,value_state,explanation_code,numerator,
                           denominator,numeric_value,censoring_lower_bound,
                           censoring_upper_bound,denominator_basis,
                           opportunity_unit_kind,capability_available,source_complete,
                           eligible_count,met_count,not_met_count,pending_count,
                           unknown_count,superseded_excluded_count,
                           distinct_owner_count,product_metric_eligible
                    FROM session_model_ensemble_metric_states_v2_r7
                    WHERE run_id=? AND metric_ordinal=0""",
                (current.run_id, legacy.run_id),
            )
        connection.rollback()
        columns = tuple(
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(session_model_ensemble_requirement_verification_bindings)"
            ).fetchall()
        )
        source_binding = connection.execute(
            "SELECT * FROM session_model_ensemble_requirement_verification_bindings WHERE run_id=?",
            (current.run_id,),
        ).fetchone()
        assert source_binding is not None
        values = tuple(
            legacy.run_id if column == "run_id" else source_binding[column]
            for column in columns
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"""INSERT INTO session_model_ensemble_requirement_verification_bindings
                    ({','.join(columns)}) VALUES({','.join('?' for _ in columns)})""",
                values,
            )


def test_observed_sequence_future_guard_and_historical_validator_roll_back(
    tmp_path,
) -> None:
    database, session_id, _run, _confirmed = _verification_reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    first, _ = service.append_objective_result(
        session_id=session_id,
        command=_objective_command(issued, 0, sequence=2, receipt_suffix="first"),
        idempotency_key="synthetic-r8-sequence-first",
    )
    predecessor = first.authority_heads[0].authority_record_id
    with pytest.raises(RequirementVerificationConflictError):
        service.append_objective_result(
            session_id=session_id,
            command=_objective_command(
                issued,
                0,
                sequence=2,
                predecessor=predecessor,
                receipt_suffix="duplicate",
            ),
            idempotency_key="synthetic-r8-sequence-duplicate",
        )
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_verification_objective_sequence_monotonic_m59"
        )
        connection.commit()
    with pytest.raises(RequirementVerificationPersistenceError):
        service.append_objective_result(
            session_id=session_id,
            command=_objective_command(
                issued,
                0,
                sequence=1,
                predecessor=predecessor,
                receipt_suffix="historical",
            ),
            idempotency_key="synthetic-r8-sequence-historical",
        )
    current = service.snapshot(
        session_id,
        issued.evidence.opportunities.opportunity_set_fingerprint,
    )
    assert current == first


def test_r8_direct_child_deletes_reject_and_owning_parent_deletes_cascade(
    tmp_path,
) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)

    with database._connection() as connection:
        for table in (
            "session_model_ensemble_metric_publication_v2_seals_r8",
            "session_model_ensemble_metric_states_v2_r8",
            "session_model_ensemble_requirement_verification_bindings",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"DELETE FROM {table} WHERE run_id=?",  # noqa: S608
                    (record.run_id,),
                )
            connection.rollback()

    # Deleting only the consuming run is an authorized parent cascade.  It
    # removes the binding/publication, but not the independently owned M58
    # evidence graph whose reviewed source run still exists.
    with database._connection() as connection:
        connection.execute(
            "DELETE FROM session_model_ensemble_runs WHERE run_id=?",
            (record.run_id,),
        )
        connection.commit()
        for table in (
            "session_model_ensemble_requirement_verification_bindings",
            "session_model_ensemble_metric_states_v2_r8",
            "session_model_ensemble_metric_publication_v2_seals_r8",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}",  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM requirement_verification_opportunity_sets"
        ).fetchone()[0] == 1

        # The owning session/source deletion is the authority that removes
        # M58 and its complete append-only child graph.
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute(
            "DELETE FROM sessions WHERE session_id=?",
            (source.session_id,),
        )
        connection.commit()
        for table in (
            "requirement_verification_result_receipt_refs",
            "requirement_verification_authority_record_seals",
            "requirement_verification_authority_records",
            "requirement_verification_opportunity_set_seals",
            "requirement_verification_opportunities",
            "requirement_verification_opportunity_sets",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}",  # noqa: S608 - closed constants
            ).fetchone()[0] == 0


def test_keyed_binding_fingerprint_helper_matches_application_identity(
    tmp_path,
) -> None:
    _database, _source, _plan, _action, _service_, revision_zero = _r8_setup(
        tmp_path
    )
    binding = _verification_binding(revision_zero)
    assert binding.binding_fingerprint == _requirement_verification_binding_fingerprint(
        binding,
        ARTIFACT_IDS,
    )


def test_two_connection_append_wins_before_save_without_hybrid_graph(
    tmp_path,
    monkeypatch,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    evidence_repository = service._repository
    original_insert = evidence_repository._insert_authority_tx
    writer_locked = threading.Event()
    release_writer = threading.Event()

    def paused_insert(connection, authority):  # type: ignore[no-untyped-def]
        writer_locked.set()
        assert release_writer.wait(timeout=10)
        return original_insert(connection, authority)

    monkeypatch.setattr(evidence_repository, "_insert_authority_tx", paused_insert)
    save_started = threading.Event()

    def save():
        save_started.set()
        return database.model_ensemble_repository().save_completed(record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        appended_future = executor.submit(
            service.append_objective_result,
            session_id=source.session_id,
            command=_objective_command(revision_zero, 0, sequence=1),
            idempotency_key="synthetic-r8-race-append-wins",
        )
        assert writer_locked.wait(timeout=10)
        saved_future = executor.submit(save)
        assert save_started.wait(timeout=10)
        release_writer.set()
        appended, applied = appended_future.result(timeout=20)
        assert applied is True
        assert appended.revision == 1
        with pytest.raises(DatabaseInvariantError):
            saved_future.result(timeout=20)

    with sqlite3.connect(database.path) as connection:
        for table in (
            "session_model_ensemble_runs",
            "session_model_ensemble_requirement_verification_bindings",
            "session_model_ensemble_metric_states_v2_r8",
            "session_model_ensemble_metric_publication_v2_seals_r8",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",  # noqa: S608
                (record.run_id,),
            ).fetchone()[0] == 0


def test_two_connection_save_wins_then_append_preserves_historical_binding(
    tmp_path,
    monkeypatch,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    original_profile_insert = runs._insert_metric_profile_binding
    writer_locked = threading.Event()
    release_writer = threading.Event()

    def paused_profile_insert(connection, candidate):  # type: ignore[no-untyped-def]
        writer_locked.set()
        assert release_writer.wait(timeout=10)
        return original_profile_insert(connection, candidate)

    monkeypatch.setattr(runs, "_insert_metric_profile_binding", paused_profile_insert)
    append_started = threading.Event()

    def append():
        append_started.set()
        return service.append_objective_result(
            session_id=source.session_id,
            command=_objective_command(revision_zero, 0, sequence=1),
            idempotency_key="synthetic-r8-race-save-wins",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        saved_future = executor.submit(runs.save_completed, record)
        assert writer_locked.wait(timeout=10)
        appended_future = executor.submit(append)
        assert append_started.wait(timeout=10)
        release_writer.set()
        assert saved_future.result(timeout=20) is None
        appended, applied = appended_future.result(timeout=20)
        assert applied is True
        assert appended.revision == 1

    loaded = runs.get(record.run_id)
    assert loaded is not None
    binding = loaded.requirement_verification_evidence_binding
    assert binding is not None
    assert binding.through_revision == 0
    assert binding.evidence_set_fingerprint == (
        revision_zero.evidence.evidence_set_fingerprint
    )


def test_two_connection_same_identity_save_has_one_complete_winner(
    tmp_path,
    monkeypatch,
) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    original_profile_insert = runs._insert_metric_profile_binding
    first_writer_locked = threading.Event()
    release_first_writer = threading.Event()

    def paused_profile_insert(connection, candidate):  # type: ignore[no-untyped-def]
        first_writer_locked.set()
        assert release_first_writer.wait(timeout=10)
        return original_profile_insert(connection, candidate)

    monkeypatch.setattr(runs, "_insert_metric_profile_binding", paused_profile_insert)
    second_started = threading.Event()

    def second_save():
        second_started.set()
        return runs.save_completed(record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runs.save_completed, record)
        assert first_writer_locked.wait(timeout=10)
        second = executor.submit(second_save)
        assert second_started.wait(timeout=10)
        release_first_writer.set()
        assert first.result(timeout=20) is None
        with pytest.raises(DatabaseError):
            second.result(timeout=20)

    loaded = runs.get(record.run_id)
    assert loaded is not None
    assert (
        loaded.requirement_verification_evidence_binding
        == record.requirement_verification_evidence_binding
    )
    assert (
        loaded.receipt.metric_publication_v2
        == record.receipt.metric_publication_v2
    )
    with sqlite3.connect(database.path) as connection:
        expected_counts = {
            "session_model_ensemble_runs": 1,
            "session_model_ensemble_requirement_verification_bindings": 1,
            "session_model_ensemble_metric_states_v2_r8": 20,
            "session_model_ensemble_metric_publication_v2_seals_r8": 1,
        }
        for table, expected in expected_counts.items():
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",  # noqa: S608
                (record.run_id,),
            ).fetchone()[0] == expected


def test_keyed_binding_rejects_substitution_with_recomputed_plain_hash(
    tmp_path,
) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    binding = record.requirement_verification_evidence_binding
    assert binding is not None
    forged = binding.model_copy(
        update={
            "opportunity_set_fingerprint": "9" * 64,
            "binding_fingerprint": "0" * 64,
        }
    )
    ordinary_hash = hashlib.sha256(
        json.dumps(
            forged.authority_identity(),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert ordinary_hash != _requirement_verification_binding_fingerprint(
        forged,
        ARTIFACT_IDS,
    )
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_requirement_verification_bindings_no_update"
        )
        connection.execute(
            """UPDATE session_model_ensemble_requirement_verification_bindings
               SET opportunity_set_fingerprint=?,binding_fingerprint=?
               WHERE run_id=?""",
            ("9" * 64, ordinary_hash, record.run_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        runs.get(record.run_id)


def test_forged_verified_numerator_rejects_on_hydration(tmp_path) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    current = revision_zero
    for index in range(3):
        current, applied = service.append_objective_result(
            session_id=source.session_id,
            command=_objective_command(
                revision_zero,
                index,
                sequence=1,
                receipt_suffix=f"resolved-{index}",
            ),
            idempotency_key=f"synthetic-r8-resolved-{index:04}",
        )
        assert applied is True
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=current,
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    with database._connection() as connection:
        connection.execute("DROP TRIGGER session_metric_r8_states_no_update")
        connection.execute(
            """UPDATE session_model_ensemble_metric_states_v2_r8
               SET numerator=2,numeric_value=(2.0/3.0),
                   censoring_lower_bound=(2.0/3.0),
                   censoring_upper_bound=(2.0/3.0),
                   met_count=2,not_met_count=1
               WHERE run_id=?
                 AND metric_key='outcome.verified_requirement_coverage'""",
            (record.run_id,),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        runs.get(record.run_id)


def test_forged_verification_seal_field_rejects_on_hydration(tmp_path) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(record)
    with database._connection() as connection:
        connection.execute("DROP TRIGGER session_metric_r8_seals_no_update")
        connection.execute(
            """UPDATE session_model_ensemble_metric_publication_v2_seals_r8
               SET requirement_verification_binding_fingerprint=?
               WHERE run_id=?""",
            ("8" * 64, record.run_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        runs.get(record.run_id)


def test_incomplete_nineteen_state_r8_graph_rolls_back_whole_run(tmp_path) -> None:
    database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    with database._connection() as connection:
        connection.execute(
            """CREATE TRIGGER synthetic_ignore_twentieth_r8_state
               BEFORE INSERT ON session_model_ensemble_metric_states_v2_r8
               WHEN NEW.metric_ordinal=19
               BEGIN SELECT RAISE(IGNORE); END"""
        )
        connection.commit()

    with pytest.raises(DatabaseError):
        database.model_ensemble_repository().save_completed(record)

    with sqlite3.connect(database.path) as connection:
        for table in (
            "session_model_ensemble_runs",
            "session_model_ensemble_requirement_verification_bindings",
            "session_model_ensemble_metric_states_v2_r8",
            "session_model_ensemble_metric_publication_v2_seals_r8",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",  # noqa: S608
                (record.run_id,),
            ).fetchone()[0] == 0


def test_sql_rejects_through_revision_lower_than_authority_head_count(
    tmp_path,
) -> None:
    database, source, plan, action, service, revision_zero = _r8_setup(tmp_path)
    revision_one, _ = service.append_objective_result(
        session_id=source.session_id,
        command=_objective_command(revision_zero, 0, sequence=1),
        idempotency_key="synthetic-r8-revision-head-check",
    )
    record = _r8_record(
        source.session_id,
        run_character="f",
        request_character="1",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_one,
    )
    database.model_ensemble_repository().save_completed(record)
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_requirement_verification_bindings_no_update"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE session_model_ensemble_requirement_verification_bindings
                   SET through_revision=0 WHERE run_id=?""",
                (record.run_id,),
            )
        connection.rollback()


def test_application_binding_rejects_revision_behind_its_authority_heads(
    tmp_path,
) -> None:
    database, source, _plan, _action, service, revision_zero = _r8_setup(tmp_path)
    revision_one, applied = service.append_objective_result(
        session_id=source.session_id,
        command=_objective_command(revision_zero, 0, sequence=1),
        idempotency_key="synthetic-r8-application-revision-head-check",
    )
    assert applied is True
    binding = _verification_binding(revision_one)

    with pytest.raises(ValueError, match="persisted verification counts"):
        SessionRequirementVerificationEvidenceBinding.model_validate(
            {**binding.model_dump(), "through_revision": 0}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("opportunity_count", 1_001),
        ("authority_head_count", 1_001),
        ("through_revision", 32_001),
    ),
)
def test_application_binding_rejects_values_above_storage_bounds(
    tmp_path,
    field: str,
    value: int,
) -> None:
    _database, _source, _plan, _action, _service_, revision_zero = _r8_setup(
        tmp_path
    )
    binding = _verification_binding(revision_zero)

    with pytest.raises(ValueError):
        SessionRequirementVerificationEvidenceBinding.model_validate(
            {**binding.model_dump(), field: value}
        )


def test_application_cross_binding_rejects_shape_valid_forged_pending_bounds(
    tmp_path,
) -> None:
    _database, source, plan, action, _service_, revision_zero = _r8_setup(tmp_path)
    record = _r8_record(
        source.session_id,
        run_character="c",
        request_character="3",
        plan_snapshot=plan,
        action_snapshot=action,
        verification_snapshot=revision_zero,
    )
    binding = record.requirement_verification_evidence_binding
    publication = record.receipt.metric_publication_v2
    assert binding is not None
    assert publication is not None
    state = next(
        item.state
        for item in publication.metrics
        if item.state.metric_key == "outcome.verified_requirement_coverage"
    )
    forged = type(state).model_validate(
        {
            **state.model_dump(),
            "censoring_lower_bound": 0.25,
        }
    )

    with pytest.raises(ValueError, match="pending verification state"):
        validate_requirement_verification_binding_metric_state(binding, forged)
