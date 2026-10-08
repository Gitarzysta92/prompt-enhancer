"""M56 reviewed requirement-action persistence attacks.

All fixtures are synthetic and contain only content-free coordinates, closed
provenance labels, timestamps, counters, and local pseudonyms.
"""

from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest

from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionFamily,
    ActionState,
    TypedEvidenceProvenance,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    ConfirmedRequirementActionLink,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    RequirementActionConflictError,
    RequirementActionDecisionKind,
    RequirementActionDecisionRecord,
    RequirementActionProposalRecord,
    RequirementActionProposalStatus,
    RequirementActionRequirement,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_decision_authority_fingerprint,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    RequirementPlanProducerReceipt,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
)
from prompt_enhancer.database import Database, DatabaseInvariantError
from prompt_enhancer.domain import EventKind, Provider, ToolCategory

from test_model_ensemble_r5_profile_persistence import NOW
from test_model_ensemble_r6_persistence import (
    _r6_record,
    _reviewed_binding,
    _reviewed_setup,
)
from test_requirement_plan_evidence_persistence import ARTIFACT_IDS


def _restart(database: Database) -> Database:
    restarted = Database(database.path)
    restarted.configure_local_artifact_id_factory(ARTIFACT_IDS)
    return restarted


def _candidate_manifest(
    source,
) -> RequirementActionCandidateManifest:  # type: ignore[no-untyped-def]
    provenance = TypedEvidenceProvenance(
        provider=source.provider,
        provider_version=source.provider_version,
        adapter_version=source.adapter_version,
        decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
        decoder_version="4",
        source_schema_version=source.source_schema_version,
        extraction_complete=True,
    )
    manifest = RequirementActionCandidateManifest(
        session_id=source.session_id,
        source_run_id=source.run_id,
        source_window_fingerprint=source.input_fingerprint,
        provenance=provenance,
        extraction_complete=True,
        enumeration_complete=True,
        actions=(
            RequirementActionCandidate(
                candidate_index=0,
                action_id="1" * 64,
                source_reference_id="2" * 64,
                sequence=10,
                event_kind=EventKind.TOOL_END,
                tool_category=ToolCategory.TEST,
                occurred_at=NOW + timedelta(seconds=1),
                duration_ms=125,
                family=ActionFamily.COMMAND,
                state=ActionState.COMPLETED,
            ),
            RequirementActionCandidate(
                candidate_index=1,
                action_id="3" * 64,
                source_reference_id="4" * 64,
                sequence=11,
                event_kind=EventKind.ARTIFACT,
                occurred_at=NOW + timedelta(seconds=2),
                family=ActionFamily.FILE_CHANGE,
                state=ActionState.UNKNOWN,
            ),
        ),
        manifest_fingerprint="5" * 64,
    )
    return manifest.model_copy(
        update={
            "manifest_fingerprint": (
                requirement_action_candidate_manifest_fingerprint(manifest)
            )
        }
    )


def _proposal(
    source,
    plan_snapshot,
    *,
    suffix: str = "6",
) -> RequirementActionProposalRecord:  # type: ignore[no-untyped-def]
    manifest = _candidate_manifest(source)
    requirements = tuple(
        RequirementActionRequirement(
            requirement_index=index,
            requirement_id=item.requirement_id,
            coordinate=item.coordinate,
        )
        for index, item in enumerate(
            sorted(plan_snapshot.requirements, key=lambda item: item.requirement_id)
        )
    )
    return RequirementActionProposalRecord(
        proposal_id=suffix * 64,
        session_id=source.session_id,
        source_run_id=source.run_id,
        source_window_fingerprint=source.input_fingerprint,
        requirement_plan_confirmation_id=plan_snapshot.confirmation_id,
        requirement_plan_evidence_fingerprint=(
            _reviewed_binding(plan_snapshot).evidence_fingerprint
        ),
        candidate_manifest_fingerprint=manifest.manifest_fingerprint,
        candidate_provenance=manifest.provenance,
        candidate_extraction_complete=True,
        candidate_enumeration_complete=True,
        payload_sha256="7" * 64,
        idempotency_key_digest="8" * 64,
        command_fingerprint="9" * 64,
        producer_receipt=RequirementPlanProducerReceipt(
            claim_fingerprint="a" * 64
        ),
        requirements=requirements,
        candidates=manifest.actions,
        links=tuple(
            ConfirmedRequirementActionLink(
                requirement_id=item.requirement_id,
                action_ids=(manifest.actions[0].action_id,) if index == 0 else (),
            )
            for index, item in enumerate(requirements)
        ),
        created_at=NOW + timedelta(minutes=2),
    )


def _decision(
    proposal: RequirementActionProposalRecord,
    *,
    decision: RequirementActionDecisionKind = RequirementActionDecisionKind.CONFIRM,
    suffix: str = "b",
    idempotency_character: str = "c",
    command_character: str = "d",
    descriptor_character: str = "e",
) -> RequirementActionDecisionRecord:
    decision_id = suffix * 64
    idempotency_key_digest = idempotency_character * 64
    command_fingerprint = command_character * 64
    reviewed_descriptor_set_fingerprint = (
        descriptor_character * 64
        if decision is RequirementActionDecisionKind.CONFIRM
        else None
    )
    return RequirementActionDecisionRecord(
        decision_id=decision_id,
        proposal_id=proposal.proposal_id,
        session_id=proposal.session_id,
        decision=decision,
        idempotency_key_digest=idempotency_key_digest,
        command_fingerprint=command_fingerprint,
        reviewed_descriptor_set_fingerprint=(
            reviewed_descriptor_set_fingerprint
        ),
        decision_authority_fingerprint=(
            requirement_action_decision_authority_fingerprint(
                ARTIFACT_IDS,
                proposal=proposal,
                decision_id=decision_id,
                decision=decision,
                idempotency_key_digest=idempotency_key_digest,
                command_fingerprint=command_fingerprint,
                reviewed_descriptor_set_fingerprint=(
                    reviewed_descriptor_set_fingerprint
                ),
            )
        ),
        decided_at=NOW + timedelta(minutes=3),
    )


def _setup_reviewed_source(tmp_path):  # type: ignore[no-untyped-def]
    (
        database,
        session_id,
        _source,
        _plan_repository,
        _plan_service,
        plan_snapshot,
        _head,
    ) = _reviewed_setup(tmp_path)
    source = _r6_record(
        session_id,
        run_character="e",
        request_character="f",
        evidence_binding=_reviewed_binding(plan_snapshot),
        snapshot=plan_snapshot,
    )
    database.model_ensemble_repository().save_completed(source)
    return database, source, plan_snapshot


def test_proposal_is_inert_and_exact_graph_round_trips_after_restart(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    proposal = _proposal(source, plan_snapshot)
    repository = database.requirement_action_evidence_repository()

    view, applied = repository.issue_proposal(proposal)

    assert applied is True
    assert view.proposal == proposal
    assert view.status is RequirementActionProposalStatus.PROPOSED
    assert repository.snapshot(source.session_id, source.input_fingerprint).confirmation_id is None
    restarted = _restart(database).requirement_action_evidence_repository()
    assert restarted.get_proposal(proposal.proposal_id) == view
    replay, replay_applied = restarted.issue_proposal(proposal)
    assert replay == view
    assert replay_applied is False
    with sqlite3.connect(database.path) as connection:
        columns = tuple(
            item[1]
            for item in connection.execute(
                "PRAGMA table_info(requirement_action_evidence_proposals)"
            ).fetchall()
        )
        assert "producer_id" not in columns
        assert "producer_version" not in columns
        assert "model_id" not in columns
        assert connection.execute(
            "SELECT local_only,content_persisted FROM requirement_action_evidence_proposals"
        ).fetchone() == (1, 0)


def test_native_confirmation_issues_keyed_snapshot_and_replays_after_source_ages(
    tmp_path,
) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    proposal = _proposal(source, plan_snapshot)
    repository = database.requirement_action_evidence_repository()
    repository.issue_proposal(proposal)
    decision = _decision(proposal)

    confirmed, applied = repository.decide(decision)
    snapshot = repository.snapshot(source.session_id, source.input_fingerprint)

    assert applied is True
    assert confirmed.status is RequirementActionProposalStatus.CONFIRMED
    assert snapshot.confirmation_id == decision.decision_id
    assert snapshot.proposal_id == proposal.proposal_id
    assert (
        snapshot.reviewed_descriptor_set_fingerprint
        == decision.reviewed_descriptor_set_fingerprint
    )
    assert snapshot.candidate_manifest is not None
    assert snapshot.candidate_manifest.actions == proposal.candidates
    assert snapshot.evidence_fingerprint is not None

    newer = _r6_record(
        source.session_id,
        run_character="f",
        request_character="1",
        evidence_binding=_reviewed_binding(plan_snapshot),
        snapshot=plan_snapshot,
    )
    database.model_ensemble_repository().save_completed(newer)
    proposal_replay, proposal_replay_applied = repository.issue_proposal(
        proposal
    )
    assert proposal_replay == confirmed
    assert proposal_replay_applied is False
    replay, replay_applied = repository.decide(decision)
    assert replay == confirmed
    assert replay_applied is False


def test_stale_proposal_can_be_rejected_but_not_confirmed(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    rejected_proposal = _proposal(source, plan_snapshot, suffix="6")
    confirmed_proposal = rejected_proposal.model_copy(
        update={
            "proposal_id": "7" * 64,
            "payload_sha256": "8" * 64,
            "idempotency_key_digest": "9" * 64,
            "command_fingerprint": "a" * 64,
        }
    )
    repository.issue_proposal(rejected_proposal)
    repository.issue_proposal(confirmed_proposal)
    newer = _r6_record(
        source.session_id,
        run_character="f",
        request_character="1",
        evidence_binding=_reviewed_binding(plan_snapshot),
        snapshot=plan_snapshot,
    )
    database.model_ensemble_repository().save_completed(newer)

    rejected, applied = repository.decide(
        _decision(
            rejected_proposal,
            decision=RequirementActionDecisionKind.REJECT,
            suffix="b",
        )
    )
    assert applied is True
    assert rejected.status is RequirementActionProposalStatus.REJECTED
    with pytest.raises(RequirementActionConflictError):
        repository.decide(_decision(confirmed_proposal, suffix="e"))


def test_paging_snapshot_rejects_decision_drift_and_tampering(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    first = _proposal(source, plan_snapshot, suffix="6")
    second = first.model_copy(
        update={
            "proposal_id": "7" * 64,
            "payload_sha256": "8" * 64,
            "idempotency_key_digest": "9" * 64,
            "command_fingerprint": "a" * 64,
            "created_at": first.created_at + timedelta(seconds=1),
        }
    )
    repository.issue_proposal(first)
    repository.issue_proposal(second)
    page, boundary = repository.list_proposals_page(
        source.session_id, limit=1, offset=0
    )
    assert page == (repository.get_proposal(first.proposal_id),)

    repository.decide(
        _decision(
            second,
            decision=RequirementActionDecisionKind.REJECT,
            suffix="b",
        )
    )
    with pytest.raises(RequirementActionConflictError):
        repository.list_proposals_page(
            source.session_id,
            limit=1,
            offset=1,
            snapshot=boundary,
        )
    with pytest.raises(RequirementActionConflictError):
        repository.list_proposals_page(
            source.session_id,
            limit=1,
            offset=1,
            snapshot=boundary.model_copy(update={"snapshot_id": "f" * 64}),
        )


def test_children_are_immutable_but_session_privacy_delete_cascades(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    proposal = _proposal(source, plan_snapshot)
    repository = database.requirement_action_evidence_repository()
    repository.issue_proposal(proposal)
    repository.decide(_decision(proposal))

    with database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE requirement_action_evidence_candidates SET state='failed'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM requirement_action_evidence_candidates"
            )
        connection.rollback()
        connection.execute(
            "DELETE FROM sessions WHERE session_id=?", (source.session_id,)
        )
        connection.commit()
        for table in (
            "requirement_action_evidence_proposals",
            "requirement_action_evidence_requirements",
            "requirement_action_evidence_candidates",
            "requirement_action_evidence_links",
            "requirement_action_evidence_proposal_seals",
            "requirement_action_evidence_decisions",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

    assert repository.get_proposal(proposal.proposal_id) is None
    with pytest.raises(RequirementActionConflictError):
        repository.issue_proposal(proposal)


def test_graph_or_provenance_tamper_is_detected_on_read(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    proposal = _proposal(source, plan_snapshot)
    repository = database.requirement_action_evidence_repository()
    repository.issue_proposal(proposal)

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA recursive_triggers=OFF")
        connection.execute(
            "DROP TRIGGER requirement_action_evidence_proposals_no_update"
        )
        connection.execute(
            """UPDATE requirement_action_evidence_proposals
               SET candidate_provider_version='synthetic.2'"""
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        repository.get_proposal(proposal.proposal_id)


@pytest.mark.parametrize(
    "decision_kind,reviewed_descriptor_set_fingerprint",
    (
        (RequirementActionDecisionKind.CONFIRM, "e" * 64),
        (RequirementActionDecisionKind.REJECT, None),
    ),
)
def test_raw_sql_decision_authority_claim_never_rehydrates(
    tmp_path,
    decision_kind: RequirementActionDecisionKind,
    reviewed_descriptor_set_fingerprint: str | None,
) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    proposal = _proposal(source, plan_snapshot)
    repository = database.requirement_action_evidence_repository()
    repository.issue_proposal(proposal)

    with database._connection() as connection:
        connection.execute(
            """INSERT INTO requirement_action_evidence_decisions(
                   decision_id,proposal_id,session_id,decision,
                   idempotency_key_digest,command_fingerprint,
                   reviewed_descriptor_set_fingerprint,
                   decision_authority_fingerprint,decided_at,
                   confirmation_authority,schema_version,
                   local_only,content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,0)""",
            (
                "b" * 64,
                proposal.proposal_id,
                proposal.session_id,
                decision_kind.value,
                "c" * 64,
                "d" * 64,
                reviewed_descriptor_set_fingerprint,
                "f" * 64,
                (NOW + timedelta(minutes=3)).isoformat(timespec="microseconds"),
                "owned_native_user_presence",
                proposal.schema_version,
            ),
        )
        connection.commit()

    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is invalid",
    ):
        repository.get_proposal(proposal.proposal_id)
    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is invalid",
    ):
        repository.list_proposals_page(
            proposal.session_id,
            limit=10,
            offset=0,
        )
    if decision_kind is RequirementActionDecisionKind.CONFIRM:
        with pytest.raises(
            DatabaseInvariantError,
            match="decision authority is invalid",
        ):
            repository.snapshot(
                proposal.session_id,
                proposal.source_window_fingerprint,
            )


def test_repository_rolls_back_unkeyed_decision_record(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    proposal = _proposal(source, plan_snapshot)
    repository = database.requirement_action_evidence_repository()
    repository.issue_proposal(proposal)
    forged = _decision(proposal).model_copy(
        update={"decision_authority_fingerprint": "f" * 64}
    )

    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is invalid",
    ):
        repository.decide(forged)

    view = repository.get_proposal(proposal.proposal_id)
    assert view is not None
    assert view.status is RequirementActionProposalStatus.PROPOSED
    assert view.decision is None
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM requirement_action_evidence_decisions"
        ).fetchone()[0] == 0


def test_swapped_keyed_decision_authorities_fail_closed(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    first = _proposal(source, plan_snapshot, suffix="6")
    second = first.model_copy(
        update={
            "proposal_id": "7" * 64,
            "payload_sha256": "8" * 64,
            "idempotency_key_digest": "9" * 64,
            "command_fingerprint": "a" * 64,
            "created_at": first.created_at + timedelta(seconds=1),
        }
    )
    repository.issue_proposal(first)
    repository.issue_proposal(second)
    first_decision = _decision(
        first,
        decision=RequirementActionDecisionKind.REJECT,
        suffix="b",
    )
    second_decision = _decision(
        second,
        decision=RequirementActionDecisionKind.REJECT,
        suffix="e",
        idempotency_character="3",
        command_character="4",
    )
    repository.decide(first_decision)
    repository.decide(second_decision)

    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER requirement_action_evidence_decisions_no_update"
        )
        connection.execute(
            """UPDATE requirement_action_evidence_decisions
               SET decision_authority_fingerprint=? WHERE decision_id=?""",
            (
                second_decision.decision_authority_fingerprint,
                first_decision.decision_id,
            ),
        )
        connection.execute(
            """UPDATE requirement_action_evidence_decisions
               SET decision_authority_fingerprint=? WHERE decision_id=?""",
            (
                first_decision.decision_authority_fingerprint,
                second_decision.decision_id,
            ),
        )
        connection.commit()

    for proposal in (first, second):
        with pytest.raises(
            DatabaseInvariantError,
            match="decision authority is invalid",
        ):
            repository.get_proposal(proposal.proposal_id)


def test_decision_session_cross_binding_tamper_fails_closed(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    proposal = _proposal(source, plan_snapshot)
    repository.issue_proposal(proposal)
    repository.decide(_decision(proposal))

    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER requirement_action_evidence_decisions_no_update"
        )
        connection.execute(
            """UPDATE requirement_action_evidence_decisions
               SET session_id=? WHERE proposal_id=?""",
            ("f" * 64, proposal.proposal_id),
        )
        connection.commit()

    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is cross-bound",
    ):
        repository.get_proposal(proposal.proposal_id)


def test_reviewed_descriptor_set_tamper_fails_closed(tmp_path) -> None:
    database, source, plan_snapshot = _setup_reviewed_source(tmp_path)
    repository = database.requirement_action_evidence_repository()
    proposal = _proposal(source, plan_snapshot)
    repository.issue_proposal(proposal)
    repository.decide(_decision(proposal))

    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER requirement_action_evidence_decisions_no_update"
        )
        connection.execute(
            """UPDATE requirement_action_evidence_decisions
               SET reviewed_descriptor_set_fingerprint=? WHERE proposal_id=?""",
            ("f" * 64, proposal.proposal_id),
        )
        connection.commit()

    with pytest.raises(
        DatabaseInvariantError,
        match="decision authority is invalid",
    ):
        repository.get_proposal(proposal.proposal_id)
