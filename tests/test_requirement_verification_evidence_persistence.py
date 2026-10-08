"""Synthetic persistence tests for durable requirement-verification authority."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import sqlite3
import threading

import pytest

from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    RequirementAcceptanceOutcome,
    RequirementVerificationMethod,
    RequirementVerificationOutcome,
    issue_requirement_verification_result,
)
from prompt_enhancer.application.analysis.requirement_verification_persistence import (
    REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    RequirementAcceptanceAppendCommand,
    RequirementVerificationConflictError,
    RequirementVerificationDefinitionsOutOfDateError,
    RequirementVerificationEvidenceService,
    RequirementVerificationPersistenceError,
    RequirementVerificationResultAppendCommand,
    RequirementVerificationStaleWindowError,
)
from prompt_enhancer.database import Database, DatabaseInvariantError

from test_model_ensemble_r5_profile_persistence import NOW
from test_requirement_plan_evidence_persistence import (
    ARTIFACT_IDS,
    _confirm,
    _import,
    _setup,
)


def _id(label: str) -> str:
    return hashlib.sha256(
        f"synthetic-requirement-verification-persistence:{label}".encode()
    ).hexdigest()


def _reviewed_setup(tmp_path):  # type: ignore[no-untyped-def]
    database, session_id, run, _repository, plan_service = _setup(tmp_path)
    confirmed = _confirm(
        plan_service,
        session_id,
        run,
        _import(plan_service, session_id, run, suffix="verification"),
        suffix="verification",
    )
    assert confirmed.decision is not None
    return database, session_id, run, confirmed


def _service(database: Database, *, clock=lambda: NOW + timedelta(minutes=2)):
    return RequirementVerificationEvidenceService(
        database.requirement_verification_evidence_repository(),
        database.requirement_verification_current_plan_authority(),
        ARTIFACT_IDS,
        clock=clock,
    )


def _objective_command(
    snapshot,  # type: ignore[no-untyped-def]
    index: int,
    *,
    outcome: RequirementVerificationOutcome = RequirementVerificationOutcome.PASSED,
    sequence: int = 1,
    predecessor: str | None = None,
    receipt_suffix: str = "one",
) -> RequirementVerificationResultAppendCommand:
    opportunities = snapshot.evidence.opportunities
    opportunity = opportunities.opportunities[index]
    return RequirementVerificationResultAppendCommand(
        result=issue_requirement_verification_result(
            opportunities,
            opportunity_id=opportunity.opportunity_id,
            observed_sequence=sequence,
            method=RequirementVerificationMethod.TEST,
            outcome=outcome,
            receipt_reference_ids=(_id(f"receipt-{receipt_suffix}"),),
            identifiers=ARTIFACT_IDS,
        ),
        expected_predecessor_authority_id=predecessor,
    )


def test_issue_append_replay_historical_snapshot_and_restart(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    ticks = iter(
        (
            NOW + timedelta(minutes=2),
            NOW + timedelta(minutes=3),
            NOW + timedelta(minutes=4),
            NOW + timedelta(minutes=5),
        )
    )
    service = _service(database, clock=lambda: next(ticks))

    issued, created = service.issue_current_opportunities(session_id)
    assert created is True
    assert issued.revision == 0
    assert issued.authority_heads == ()
    command = _objective_command(issued, 0)
    appended, applied = service.append_objective_result(
        session_id=session_id,
        command=command,
        idempotency_key="synthetic-verification-result-0001",
    )
    assert applied is True
    assert appended.revision == 1
    assert appended.evidence.verification_results == (command.result,)

    replayed, replay_applied = service.append_objective_result(
        session_id=session_id,
        command=command,
        idempotency_key="synthetic-verification-result-0001",
    )
    assert replay_applied is False
    assert replayed == appended

    acceptance, acceptance_applied = service.append_acceptance(
        session_id=session_id,
        command=RequirementAcceptanceAppendCommand(
            opportunity_set_fingerprint=(
                issued.evidence.opportunities.opportunity_set_fingerprint
            ),
            opportunity_id=issued.evidence.opportunities.opportunities[1].opportunity_id,
            outcome=RequirementAcceptanceOutcome.ACCEPTED,
            confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
        ),
        idempotency_key="synthetic-verification-acceptance-0001",
    )
    assert acceptance_applied is True
    assert acceptance.revision == 2
    assert len(acceptance.evidence.acceptance_authorities) == 1
    assert service.snapshot(
        session_id,
        issued.evidence.opportunities.opportunity_set_fingerprint,
        through_revision=1,
    ) == appended

    restarted = Database(database.path)
    restarted.configure_local_artifact_id_factory(ARTIFACT_IDS)
    restarted_snapshot = _service(restarted).snapshot(
        session_id, issued.evidence.opportunities.opportunity_set_fingerprint
    )
    assert restarted_snapshot == acceptance


def test_dense_revisions_predecessors_and_idempotency_conflicts(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    first_command = _objective_command(issued, 0, receipt_suffix="first")
    first, _ = service.append_objective_result(
        session_id=session_id,
        command=first_command,
        idempotency_key="synthetic-verification-dense-0001",
    )
    first_id = first.authority_heads[0].authority_record_id

    stale = _objective_command(
        issued,
        0,
        outcome=RequirementVerificationOutcome.FAILED,
        sequence=2,
        receipt_suffix="stale",
    )
    with pytest.raises(RequirementVerificationConflictError):
        service.append_objective_result(
            session_id=session_id,
            command=stale,
            idempotency_key="synthetic-verification-dense-stale",
        )

    second_command = _objective_command(
        issued,
        0,
        outcome=RequirementVerificationOutcome.FAILED,
        sequence=2,
        predecessor=first_id,
        receipt_suffix="second",
    )
    second, applied = service.append_objective_result(
        session_id=session_id,
        command=second_command,
        idempotency_key="synthetic-verification-dense-0002",
    )
    assert applied is True
    assert second.revision == 2
    assert second.authority_heads[0].revision == 2
    assert second.evidence.verification_results == (second_command.result,)

    historical_replay, historical_applied = service.append_objective_result(
        session_id=session_id,
        command=first_command,
        idempotency_key="synthetic-verification-dense-0001",
    )
    assert historical_applied is False
    assert historical_replay == first

    with pytest.raises(RequirementVerificationConflictError):
        service.append_objective_result(
            session_id=session_id,
            command=second_command,
            idempotency_key="synthetic-verification-dense-0001",
        )


def test_authority_kind_cannot_be_substituted_at_one_opportunity(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    first, _ = service.append_objective_result(
        session_id=session_id,
        command=_objective_command(issued, 0),
        idempotency_key="synthetic-verification-kind-result",
    )
    with pytest.raises(RequirementVerificationConflictError):
        service.append_acceptance(
            session_id=session_id,
            command=RequirementAcceptanceAppendCommand(
                opportunity_set_fingerprint=(
                    issued.evidence.opportunities.opportunity_set_fingerprint
                ),
                opportunity_id=(
                    issued.evidence.opportunities.opportunities[0].opportunity_id
                ),
                expected_predecessor_authority_id=(
                    first.authority_heads[0].authority_record_id
                ),
                outcome=RequirementAcceptanceOutcome.ACCEPTED,
                confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
            ),
            idempotency_key="synthetic-verification-kind-acceptance",
        )


def test_same_predecessor_race_has_one_winner(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    issued, _ = _service(database).issue_current_opportunities(session_id)
    barrier = threading.Barrier(2)

    def append(suffix: str):  # type: ignore[no-untyped-def]
        local = Database(database.path)
        local.configure_local_artifact_id_factory(ARTIFACT_IDS)
        command = _objective_command(
            issued,
            0,
            outcome=(
                RequirementVerificationOutcome.PASSED
                if suffix == "a"
                else RequirementVerificationOutcome.FAILED
            ),
            receipt_suffix=f"race-{suffix}",
        )
        barrier.wait()
        try:
            result, applied = _service(local).append_objective_result(
                session_id=session_id,
                command=command,
                idempotency_key=f"synthetic-verification-race-{suffix}-0001",
            )
            return ("applied", applied, result.revision)
        except RequirementVerificationConflictError:
            return ("conflict", False, None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(append, ("a", "b")))

    assert sorted(item[0] for item in outcomes) == ["applied", "conflict"]
    assert _service(database).snapshot(
        session_id, issued.evidence.opportunities.opportunity_set_fingerprint
    ).revision == 1


def test_different_opportunity_race_serializes_dense_revisions(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    issued, _ = _service(database).issue_current_opportunities(session_id)
    barrier = threading.Barrier(2)

    def append(index: int):  # type: ignore[no-untyped-def]
        local = Database(database.path)
        local.configure_local_artifact_id_factory(ARTIFACT_IDS)
        command = _objective_command(
            issued,
            index,
            receipt_suffix=f"different-{index}",
        )
        barrier.wait()
        result, applied = _service(local).append_objective_result(
            session_id=session_id,
            command=command,
            idempotency_key=f"synthetic-verification-different-{index}-0001",
        )
        return applied, result.revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(append, (0, 1)))

    assert all(item[0] for item in outcomes)
    assert {item[1] for item in outcomes} == {1, 2}
    current = _service(database).snapshot(
        session_id, issued.evidence.opportunities.opportunity_set_fingerprint
    )
    assert current.revision == 2
    assert tuple(item.revision for item in current.authority_heads) in {
        (1, 2),
        (2, 1),
    }


def test_exact_replay_survives_new_r6_head_but_new_append_is_stale(tmp_path) -> None:
    database, session_id, run, _repository, plan_service = _setup(tmp_path)
    first_plan = _confirm(
        plan_service,
        session_id,
        run,
        _import(plan_service, session_id, run, suffix="stale-first"),
        suffix="stale-first",
    )
    assert first_plan.decision is not None
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    first_command = _objective_command(issued, 0, receipt_suffix="stale-first")
    first, _ = service.append_objective_result(
        session_id=session_id,
        command=first_command,
        idempotency_key="synthetic-verification-stale-replay",
    )

    replacement_plan = _confirm(
        plan_service,
        session_id,
        run,
        _import(
            plan_service,
            session_id,
            run,
            predecessor=first_plan.decision.decision_id,
            suffix="stale-second",
        ),
        suffix="stale-second",
    )
    assert replacement_plan.decision is not None

    replayed, applied = service.append_objective_result(
        session_id=session_id,
        command=first_command,
        idempotency_key="synthetic-verification-stale-replay",
    )
    assert applied is False
    assert replayed == first

    with pytest.raises(RequirementVerificationStaleWindowError):
        service.append_objective_result(
            session_id=session_id,
            command=_objective_command(
                issued,
                0,
                sequence=2,
                predecessor=first.authority_heads[0].authority_record_id,
                receipt_suffix="stale-new",
            ),
            idempotency_key="synthetic-verification-stale-new",
        )


def test_foreign_requirement_id_direct_tamper_fails_closed(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    set_id = issued.evidence.opportunities.opportunity_set_fingerprint
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_verification_opportunities_no_update"
        )
        connection.execute(
            """UPDATE requirement_verification_opportunities
               SET requirement_id=?
               WHERE opportunity_set_fingerprint=? AND requirement_index=0""",
            (_id("foreign-requirement"), set_id),
        )
        connection.commit()

    with pytest.raises(RequirementVerificationPersistenceError):
        service.snapshot(session_id, set_id)


@pytest.mark.parametrize("target", ["opportunity_set", "authority"])
def test_unsealed_graph_fails_closed(tmp_path, target: str) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    set_id = issued.evidence.opportunities.opportunity_set_fingerprint
    if target == "authority":
        appended, _ = service.append_objective_result(
            session_id=session_id,
            command=_objective_command(issued, 0),
            idempotency_key="synthetic-verification-unsealed-authority",
        )
        authority_id = appended.authority_heads[0].authority_record_id
    with database._connection() as connection:
        if target == "opportunity_set":
            connection.execute(
                "DROP TRIGGER requirement_verification_opportunity_set_seals_privacy_delete_only"
            )
            connection.execute(
                """DELETE FROM requirement_verification_opportunity_set_seals
                   WHERE opportunity_set_fingerprint=?""",
                (set_id,),
            )
        else:
            connection.execute(
                "DROP TRIGGER requirement_verification_authority_record_seals_privacy_delete_only"
            )
            connection.execute(
                """DELETE FROM requirement_verification_authority_record_seals
                   WHERE authority_record_id=?""",
                (authority_id,),
            )
        connection.commit()

    with pytest.raises(RequirementVerificationPersistenceError):
        service.snapshot(session_id, set_id)


def test_unsealed_or_revision_gap_tamper_fails_closed(tmp_path) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    set_id = issued.evidence.opportunities.opportunity_set_fingerprint
    appended, _ = service.append_objective_result(
        session_id=session_id,
        command=_objective_command(issued, 0),
        idempotency_key="synthetic-verification-gap-0001",
    )
    second = _objective_command(
        issued,
        0,
        sequence=2,
        predecessor=appended.authority_heads[0].authority_record_id,
        receipt_suffix="gap-two",
    )
    service.append_objective_result(
        session_id=session_id,
        command=second,
        idempotency_key="synthetic-verification-gap-0002",
    )
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_verification_authority_records_no_update"
        )
        connection.execute(
            "DROP TRIGGER requirement_verification_authority_record_seals_no_update"
        )
        connection.execute(
            """UPDATE requirement_verification_authority_records SET revision=3
               WHERE opportunity_set_fingerprint=? AND revision=2""",
            (set_id,),
        )
        connection.execute(
            """UPDATE requirement_verification_authority_record_seals SET revision=3
               WHERE opportunity_set_fingerprint=? AND revision=2""",
            (set_id,),
        )
        connection.commit()

    with pytest.raises(RequirementVerificationPersistenceError):
        service.snapshot(session_id, set_id)


def test_direct_child_delete_is_blocked_but_session_privacy_delete_cascades(
    tmp_path,
) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    service.append_objective_result(
        session_id=session_id,
        command=_objective_command(issued, 0),
        idempotency_key="synthetic-verification-delete-0001",
    )
    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """DELETE FROM requirement_verification_authority_records
                   WHERE opportunity_set_fingerprint=?""",
                (issued.evidence.opportunities.opportunity_set_fingerprint,),
            )
        connection.rollback()
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
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
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_source_run_privacy_delete_cascades_durable_verification_graph(
    tmp_path,
) -> None:
    database, session_id, run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    service.append_objective_result(
        session_id=session_id,
        command=_objective_command(issued, 0),
        idempotency_key="synthetic-verification-run-delete-0001",
    )

    assert database.model_ensemble_repository().delete_for_privacy(run.run_id) is True
    with sqlite3.connect(database.path) as connection:
        for table in (
            "requirement_verification_result_receipt_refs",
            "requirement_verification_authority_record_seals",
            "requirement_verification_authority_records",
            "requirement_verification_opportunity_set_seals",
            "requirement_verification_opportunities",
            "requirement_verification_opportunity_sets",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_raw_idempotency_and_native_confirmation_tokens_are_not_persisted(
    tmp_path,
) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    raw_result_key = "synthetic-verification-private-result-key"
    raw_acceptance_key = "synthetic-verification-private-acceptance-key"
    service.append_objective_result(
        session_id=session_id,
        command=_objective_command(issued, 0, receipt_suffix="private"),
        idempotency_key=raw_result_key,
    )
    service.append_acceptance(
        session_id=session_id,
        command=RequirementAcceptanceAppendCommand(
            opportunity_set_fingerprint=(
                issued.evidence.opportunities.opportunity_set_fingerprint
            ),
            opportunity_id=issued.evidence.opportunities.opportunities[1].opportunity_id,
            outcome=RequirementAcceptanceOutcome.ACCEPTED,
            confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
        ),
        idempotency_key=raw_acceptance_key,
    )

    persisted = database.path.read_bytes()
    assert raw_result_key.encode() not in persisted
    assert raw_acceptance_key.encode() not in persisted
    assert REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION.encode() not in persisted


def test_durable_current_window_rejects_contract_identity_drift(tmp_path) -> None:
    database, session_id, run, _confirmed = _reviewed_setup(tmp_path)
    with database._connection() as connection:
        connection.execute("DROP TRIGGER session_metric_r6_seals_no_update")
        connection.execute(
            """UPDATE session_model_ensemble_metric_publication_v2_seals_r6
               SET contract_set_fingerprint=? WHERE run_id=?""",
            (_id("foreign-contract-set"), run.run_id),
        )
        connection.commit()

    with pytest.raises(RequirementVerificationDefinitionsOutOfDateError):
        _service(database).issue_current_opportunities(session_id)


def test_derived_id_sort_permutation_persists_exact_r6_order(tmp_path) -> None:
    database, session_id, _run, confirmed = _reviewed_setup(tmp_path)
    source_coordinates = tuple(
        (item.coordinate.message_sequence, item.coordinate.clause_index)
        for item in confirmed.proposal.requirements
    )
    issued, _ = _service(database).issue_current_opportunities(session_id)
    issued_coordinates = tuple(
        (item.coordinate.message_sequence, item.coordinate.clause_index)
        for item in issued.evidence.opportunities.opportunities
    )
    assert set(issued_coordinates) == set(source_coordinates)
    assert issued_coordinates != source_coordinates
    assert tuple(item.requirement_index for item in issued.evidence.opportunities.opportunities) == tuple(
        range(len(issued_coordinates))
    )
    # The keyed r6 requirement identity, not proposal ordinal, owns order.
    assert tuple(item.requirement_id for item in issued.evidence.opportunities.opportunities) == tuple(
        sorted(item.requirement_id for item in issued.evidence.opportunities.opportunities)
    )


def test_per_opportunity_history_bound_is_enforced_without_partial_append(
    tmp_path,
) -> None:
    database, session_id, _run, _confirmed = _reviewed_setup(tmp_path)
    service = _service(database)
    issued, _ = service.issue_current_opportunities(session_id)
    predecessor = None
    current = issued
    for revision in range(1, 33):
        current, applied = service.append_objective_result(
            session_id=session_id,
            command=_objective_command(
                issued,
                0,
                outcome=(
                    RequirementVerificationOutcome.PASSED
                    if revision % 2
                    else RequirementVerificationOutcome.FAILED
                ),
                sequence=revision,
                predecessor=predecessor,
                receipt_suffix=f"history-{revision:02}",
            ),
            idempotency_key=f"synthetic-verification-history-{revision:04}",
        )
        assert applied is True
        assert current.revision == revision
        predecessor = current.authority_heads[0].authority_record_id

    with pytest.raises(RequirementVerificationConflictError):
        service.append_objective_result(
            session_id=session_id,
            command=_objective_command(
                issued,
                0,
                sequence=33,
                predecessor=predecessor,
                receipt_suffix="history-overflow",
            ),
            idempotency_key="synthetic-verification-history-overflow",
        )
    assert service.snapshot(
        session_id, issued.evidence.opportunities.opportunity_set_fingerprint
    ) == current
