"""SQLite attacks for confirmed collaboration lifecycle evidence.

All graph data and identifiers are synthetic.  The canonical sealed-run helper
is reused from the existing model-ensemble persistence suite so this file tests
the new boundary instead of duplicating that large fixture graph.
"""

from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest

from prompt_enhancer.application.analysis.metric_lifecycle_evidence import (
    METRIC_LIFECYCLE_DECISION_CONFIRMATION,
    MetricLifecycleConflictError,
    MetricLifecycleDecisionCommand,
    MetricLifecycleDecisionKind,
    MetricLifecycleEvidenceService,
    MetricLifecycleFamily,
    MetricLifecycleLinkKind,
    MetricLifecycleOpportunityKind,
    MetricLifecycleOutcomeKind,
    MetricLifecycleProposalCommand,
    MetricLifecycleProposalKind,
    MetricLifecycleProposalStatus,
    MetricLifecycleStaleWindowError,
)
from prompt_enhancer.application.analysis.model_ensemble import (
    SessionModelEnsembleReceipt,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    SessionModelEnsembleRunRecord,
)
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.infrastructure.sqlite import metric_lifecycle_evidence as evidence_store
from prompt_enhancer.privacy import Pseudonymizer
from prompt_enhancer.database import Database, DatabaseInvariantError

from test_model_ensemble_persistence import (
    NOW,
    _database_and_session,
    _run,
)


FAMILY_SHAPES = {
    MetricLifecycleFamily.AMBIGUITY_RESOLUTION: (
        MetricLifecycleOpportunityKind.AMBIGUITY,
        MetricLifecycleLinkKind.AMBIGUITY_RESOLUTION,
        MetricLifecycleOutcomeKind.AMBIGUITY_RESOLVED,
    ),
    MetricLifecycleFamily.CLARIFICATION_YIELD: (
        MetricLifecycleOpportunityKind.CLARIFICATION,
        MetricLifecycleLinkKind.CLARIFICATION_ANSWER_INCORPORATION,
        MetricLifecycleOutcomeKind.CLARIFICATION_INCORPORATED,
    ),
    MetricLifecycleFamily.EXPLORATION_CONVERSION: (
        MetricLifecycleOpportunityKind.EXPLORATION,
        MetricLifecycleLinkKind.EXPLORATION_SUPPORT_DECISION,
        MetricLifecycleOutcomeKind.EXPLORATION_CONVERTED,
    ),
    MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE: (
        MetricLifecycleOpportunityKind.SCOPE_CHANGE,
        MetricLifecycleLinkKind.SCOPE_CHANGE_IMPACT_DISPOSITION,
        MetricLifecycleOutcomeKind.SCOPE_CHANGE_DISCIPLINED,
    ),
    MetricLifecycleFamily.REWORK_CANDIDATE_RATE: (
        MetricLifecycleOpportunityKind.REWORK,
        MetricLifecycleLinkKind.REWORK_REQUIREMENT_ASSESSMENT,
        MetricLifecycleOutcomeKind.REWORK_REQUIRED,
    ),
}


def _service(tmp_path):
    database, session_id = _database_and_session(tmp_path)
    model_repository = database.model_ensemble_repository()
    run = _run(session_id)
    model_repository.save_completed(run)
    evidence_repository = database.metric_lifecycle_evidence_repository()
    service = MetricLifecycleEvidenceService(
        database,
        model_repository,
        evidence_repository,
        LocalArtifactIdFactory(Pseudonymizer(bytes(reversed(range(32))))),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    return database, session_id, run, model_repository, evidence_repository, service


def _opportunity_command(run_id: str, family: MetricLifecycleFamily):
    opportunity_kind, _link, _outcome = FAMILY_SHAPES[family]
    return MetricLifecycleProposalCommand(
        expected_source_run_id=run_id,
        proposal_kind=MetricLifecycleProposalKind.OPPORTUNITY,
        family=family,
        opportunity_kind=opportunity_kind,
    )


def _outcome_command(
    run_id: str,
    family: MetricLifecycleFamily,
    opportunity_id: str,
):
    opportunity_kind, link_kind, outcome_kind = FAMILY_SHAPES[family]
    return MetricLifecycleProposalCommand(
        expected_source_run_id=run_id,
        proposal_kind=MetricLifecycleProposalKind.OUTCOME,
        family=family,
        opportunity_kind=opportunity_kind,
        opportunity_id=opportunity_id,
        link_kind=link_kind,
        outcome_kind=outcome_kind,
    )


def _enumeration_command(
    run_id: str,
    family: MetricLifecycleFamily,
    opportunity_ids: tuple[str, ...],
):
    opportunity_kind, _link, _outcome = FAMILY_SHAPES[family]
    return MetricLifecycleProposalCommand(
        expected_source_run_id=run_id,
        proposal_kind=MetricLifecycleProposalKind.ENUMERATION,
        family=family,
        opportunity_kind=opportunity_kind,
        enumerated_opportunity_ids=tuple(sorted(opportunity_ids)),
    )


def _decision(run_id: str, decision=MetricLifecycleDecisionKind.CONFIRM):
    return MetricLifecycleDecisionCommand(
        expected_source_run_id=run_id,
        decision=decision,
        confirmation=METRIC_LIFECYCLE_DECISION_CONFIRMATION,
    )


def _propose(
    service: MetricLifecycleEvidenceService,
    session_id: str,
    command: MetricLifecycleProposalCommand,
    key: str,
):
    return service.propose(
        session_id=session_id,
        command=command,
        idempotency_key=f"synthetic-{key}-00000001",
    )[0]


def _decide(
    service: MetricLifecycleEvidenceService,
    session_id: str,
    proposal_id: str,
    run_id: str,
    key: str,
    decision=MetricLifecycleDecisionKind.CONFIRM,
):
    return service.decide(
        session_id=session_id,
        proposal_id=proposal_id,
        command=_decision(run_id, decision),
        idempotency_key=f"synthetic-{key}-00000001",
    )[0]


def _confirmed_opportunity(
    service,
    session_id: str,
    run_id: str,
    family: MetricLifecycleFamily,
    key: str,
):
    proposal = _propose(
        service,
        session_id,
        _opportunity_command(run_id, family),
        f"{key}-proposal",
    )
    return _decide(
        service,
        session_id,
        proposal.proposal.proposal_id,
        run_id,
        f"{key}-confirm",
    )


def _run_variant(
    original: SessionModelEnsembleRunRecord,
    *,
    marker: str,
    input_fingerprint: str,
    seconds: int,
) -> SessionModelEnsembleRunRecord:
    run_id = marker * 64
    request_fingerprint = chr(ord(marker) + 1) * 64
    receipt = SessionModelEnsembleReceipt.model_validate(
        {
            **original.receipt.model_dump(),
            "source_window_fingerprint": input_fingerprint,
            "created_at": NOW + timedelta(seconds=seconds - 4),
            "completed_at": NOW + timedelta(seconds=seconds),
        }
    )
    return SessionModelEnsembleRunRecord.model_validate(
        {
            **original.model_dump(),
            "run_id": run_id,
            "request_fingerprint": request_fingerprint,
            "input_fingerprint": input_fingerprint,
            "receipt": receipt,
        }
    )


def test_only_confirmed_receipts_enter_the_snapshot_and_exact_set(tmp_path) -> None:
    _database, session_id, run, _models, repository, service = _service(tmp_path)
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION
    opportunity = _propose(
        service,
        session_id,
        _opportunity_command(run.run_id, family),
        "inert-opportunity",
    )
    opportunity_id = opportunity.proposal.opportunity_id
    assert opportunity_id is not None

    inert = repository.snapshot(session_id, run.input_fingerprint)
    assert inert.families[0].opportunities == ()
    assert inert.families[0].enumeration_confirmed is False

    confirmed = _decide(
        service,
        session_id,
        opportunity.proposal.proposal_id,
        run.run_id,
        "confirm-opportunity",
    )
    assert confirmed.status is MetricLifecycleProposalStatus.CONFIRMED
    outcome = _propose(
        service,
        session_id,
        _outcome_command(run.run_id, family, opportunity_id),
        "inert-outcome",
    )
    before_outcome = repository.snapshot(session_id, run.input_fingerprint)
    assert before_outcome.families[0].opportunities[0].outcome is None
    _decide(
        service,
        session_id,
        outcome.proposal.proposal_id,
        run.run_id,
        "confirm-outcome",
    )
    enumeration = _propose(
        service,
        session_id,
        _enumeration_command(run.run_id, family, (opportunity_id,)),
        "exact-enumeration",
    )
    before_enumeration = repository.snapshot(session_id, run.input_fingerprint)
    assert before_enumeration.families[0].enumeration_confirmed is False
    _decide(
        service,
        session_id,
        enumeration.proposal.proposal_id,
        run.run_id,
        "confirm-enumeration",
    )

    snapshot = repository.snapshot(session_id, run.input_fingerprint)
    evidence = snapshot.families[0]
    assert evidence.enumeration_confirmed is True
    assert evidence.enumerated_opportunity_ids == (opportunity_id,)
    assert evidence.opportunities[0].outcome is not None
    assert "synthetic-" not in snapshot.model_dump_json()


def test_rejected_and_unconfirmed_proposals_never_affect_evidence(tmp_path) -> None:
    _database, session_id, run, _models, repository, service = _service(tmp_path)
    family = MetricLifecycleFamily.CLARIFICATION_YIELD
    rejected = _propose(
        service,
        session_id,
        _opportunity_command(run.run_id, family),
        "rejected-opportunity",
    )
    _decide(
        service,
        session_id,
        rejected.proposal.proposal_id,
        run.run_id,
        "reject-opportunity",
        MetricLifecycleDecisionKind.REJECT,
    )
    _propose(
        service,
        session_id,
        _opportunity_command(run.run_id, family),
        "undecided-opportunity",
    )
    enumeration = _propose(
        service,
        session_id,
        _enumeration_command(run.run_id, family, ()),
        "empty-enumeration",
    )
    _decide(
        service,
        session_id,
        enumeration.proposal.proposal_id,
        run.run_id,
        "confirm-empty-enumeration",
    )

    evidence = repository.snapshot(session_id, run.input_fingerprint).families[1]
    assert evidence.enumeration_confirmed is True
    assert evidence.enumerated_opportunity_ids == ()
    assert evidence.opportunities == ()


def test_enumeration_requires_exact_confirmed_family_set_and_seals_it(tmp_path) -> None:
    _database, session_id, run, _models, _repository, service = _service(tmp_path)
    family = MetricLifecycleFamily.EXPLORATION_CONVERSION
    first = _confirmed_opportunity(
        service, session_id, run.run_id, family, "first"
    )
    second = _confirmed_opportunity(
        service, session_id, run.run_id, family, "second"
    )
    first_id = first.proposal.opportunity_id
    second_id = second.proposal.opportunity_id
    assert first_id is not None and second_id is not None
    incomplete = _propose(
        service,
        session_id,
        _enumeration_command(run.run_id, family, (first_id,)),
        "incomplete-enumeration",
    )
    with pytest.raises(MetricLifecycleConflictError):
        _decide(
            service,
            session_id,
            incomplete.proposal.proposal_id,
            run.run_id,
            "reject-incomplete",
        )
    exact = _propose(
        service,
        session_id,
        _enumeration_command(run.run_id, family, (first_id, second_id)),
        "complete-enumeration",
    )
    _decide(
        service,
        session_id,
        exact.proposal.proposal_id,
        run.run_id,
        "confirm-complete",
    )
    with pytest.raises(MetricLifecycleConflictError):
        _propose(
            service,
            session_id,
            _opportunity_command(run.run_id, family),
            "after-seal",
        )


def test_preexisting_unconfirmed_opportunity_cannot_expand_sealed_denominator(
    tmp_path,
) -> None:
    _database, session_id, run, _models, _repository, service = _service(tmp_path)
    family = MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE
    pending = _propose(
        service,
        session_id,
        _opportunity_command(run.run_id, family),
        "pre-seal-pending",
    )
    enumeration = _propose(
        service,
        session_id,
        _enumeration_command(run.run_id, family, ()),
        "pre-seal-empty",
    )
    _decide(
        service,
        session_id,
        enumeration.proposal.proposal_id,
        run.run_id,
        "seal-empty",
    )

    with pytest.raises(MetricLifecycleConflictError):
        _decide(
            service,
            session_id,
            pending.proposal.proposal_id,
            run.run_id,
            "late-confirm",
        )


def test_cross_family_opportunity_cannot_supply_an_outcome_or_enumeration(
    tmp_path,
) -> None:
    _database, session_id, run, _models, _repository, service = _service(tmp_path)
    ambiguity = _confirmed_opportunity(
        service,
        session_id,
        run.run_id,
        MetricLifecycleFamily.AMBIGUITY_RESOLUTION,
        "cross-family-source",
    )
    opportunity_id = ambiguity.proposal.opportunity_id
    assert opportunity_id is not None

    with pytest.raises(MetricLifecycleConflictError):
        _propose(
            service,
            session_id,
            _outcome_command(
                run.run_id,
                MetricLifecycleFamily.CLARIFICATION_YIELD,
                opportunity_id,
            ),
            "cross-family-outcome",
        )
    with pytest.raises(MetricLifecycleConflictError):
        _propose(
            service,
            session_id,
            _enumeration_command(
                run.run_id,
                MetricLifecycleFamily.CLARIFICATION_YIELD,
                (opportunity_id,),
            ),
            "cross-family-enumeration",
        )


class _InterleavingRepository:
    def __init__(self, delegate, interleave, *, on: str) -> None:
        self._delegate = delegate
        self._interleave = interleave
        self._on = on
        self._done = False

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def issue_proposal(self, proposal):
        if self._on == "proposal" and not self._done:
            self._done = True
            self._interleave()
        return self._delegate.issue_proposal(proposal)

    def decide(self, decision):
        if self._on == "decision" and not self._done:
            self._done = True
            self._interleave()
        return self._delegate.decide(decision)


def test_proposal_insert_atomically_rejects_run_committed_after_service_read(
    tmp_path,
) -> None:
    database, session_id, run, models, repository, _service_instance = _service(
        tmp_path
    )
    newer = _run_variant(
        run,
        marker="8",
        input_fingerprint="9" * 64,
        seconds=20,
    )
    interleaving = _InterleavingRepository(
        repository,
        lambda: models.save_completed(newer),
        on="proposal",
    )
    service = MetricLifecycleEvidenceService(
        database,
        models,
        interleaving,
        LocalArtifactIdFactory(Pseudonymizer(bytes(reversed(range(32))))),
        clock=lambda: NOW + timedelta(minutes=1),
    )

    with pytest.raises(MetricLifecycleConflictError):
        _propose(
            service,
            session_id,
            _opportunity_command(run.run_id, MetricLifecycleFamily.REWORK_CANDIDATE_RATE),
            "proposal-race",
        )
    assert repository.list_proposals(session_id) == ()


def test_decision_insert_rejects_changed_window_race_but_allows_same_window(
    tmp_path,
) -> None:
    database, session_id, run, models, repository, service = _service(tmp_path)
    proposal = _propose(
        service,
        session_id,
        _opportunity_command(run.run_id, MetricLifecycleFamily.REWORK_CANDIDATE_RATE),
        "decision-race-source",
    )
    changed = _run_variant(
        run,
        marker="8",
        input_fingerprint="9" * 64,
        seconds=20,
    )
    interleaving = _InterleavingRepository(
        repository,
        lambda: models.save_completed(changed),
        on="decision",
    )
    raced = MetricLifecycleEvidenceService(
        database,
        models,
        interleaving,
        LocalArtifactIdFactory(Pseudonymizer(bytes(reversed(range(32))))),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    with pytest.raises(MetricLifecycleConflictError):
        _decide(
            raced,
            session_id,
            proposal.proposal.proposal_id,
            run.run_id,
            "changed-window-race",
        )

    # A separate installation proves the intentional identical-window rule.
    database2, session2, run2, models2, _repository2, service2 = _service(
        tmp_path / "same-window"
    )
    proposal2 = _propose(
        service2,
        session2,
        _opportunity_command(run2.run_id, MetricLifecycleFamily.REWORK_CANDIDATE_RATE),
        "same-window-source",
    )
    same = _run_variant(
        run2,
        marker="8",
        input_fingerprint=run2.input_fingerprint,
        seconds=20,
    )
    models2.save_completed(same)
    decided = _decide(
        service2,
        session2,
        proposal2.proposal.proposal_id,
        run2.run_id,
        "same-window-decision",
    )
    assert decided.status is MetricLifecycleProposalStatus.CONFIRMED
    assert database2.summary()["schema_version"] == 61


def test_run_and_session_privacy_cascades_purge_the_whole_receipt_graph(
    tmp_path,
) -> None:
    database, session_id, run, models, repository, service = _service(tmp_path)
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION
    opportunity = _confirmed_opportunity(
        service, session_id, run.run_id, family, "privacy-opportunity"
    )
    opportunity_id = opportunity.proposal.opportunity_id
    assert opportunity_id is not None
    enumeration = _propose(
        service,
        session_id,
        _enumeration_command(run.run_id, family, (opportunity_id,)),
        "privacy-enumeration",
    )
    _decide(
        service,
        session_id,
        enumeration.proposal.proposal_id,
        run.run_id,
        "privacy-enumeration-confirm",
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for table in (
            "metric_lifecycle_evidence_windows",
            "metric_lifecycle_evidence_enumeration_members",
            "metric_lifecycle_evidence_decisions",
            "metric_lifecycle_evidence_proposals",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="privacy"):
                connection.execute(f"DELETE FROM {table}")

    assert models.delete_for_privacy(run.run_id) is True
    assert repository.list_proposals(session_id) == ()
    with sqlite3.connect(database.path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "metric_lifecycle_evidence_windows",
                "metric_lifecycle_evidence_enumeration_members",
                "metric_lifecycle_evidence_decisions",
                "metric_lifecycle_evidence_proposals",
            )
        )
    assert counts == (0, 0, 0, 0)

    newer = _run_variant(
        run,
        marker="8",
        input_fingerprint=run.input_fingerprint,
        seconds=20,
    )
    models.save_completed(newer)
    with pytest.raises(MetricLifecycleStaleWindowError):
        _propose(
            service,
            session_id,
            _opportunity_command(run.run_id, family),
            "privacy-opportunity",
        )

    second = _confirmed_opportunity(
        service, session_id, newer.run_id, family, "session-delete"
    )
    assert second.status is MetricLifecycleProposalStatus.CONFIRMED
    with database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        connection.commit()
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "metric_lifecycle_evidence_windows",
                "metric_lifecycle_evidence_enumeration_members",
                "metric_lifecycle_evidence_decisions",
                "metric_lifecycle_evidence_proposals",
            )
        )
    assert counts == (0, 0, 0, 0)


def test_same_window_reruns_share_one_atomic_privacy_graph(tmp_path) -> None:
    database, session_id, first_run, models, repository, service = _service(tmp_path)
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION
    opportunity = _confirmed_opportunity(
        service, session_id, first_run.run_id, family, "rerun-opportunity"
    )
    opportunity_id = opportunity.proposal.opportunity_id
    assert opportunity_id is not None

    rerun = _run_variant(
        first_run,
        marker="8",
        input_fingerprint=first_run.input_fingerprint,
        seconds=20,
    )
    models.save_completed(rerun)

    outcome_command = _outcome_command(
        rerun.run_id, family, opportunity_id
    )
    outcome = _propose(
        service, session_id, outcome_command, "rerun-outcome"
    )
    # The request was freshness-bound to the rerun, while persistence is
    # normalized to the first stable window anchor so one cascade owns the
    # entire cross-rerun evidence graph.
    assert outcome.proposal.source_run_id == first_run.run_id
    replay, inserted = service.propose(
        session_id=session_id,
        command=outcome_command,
        idempotency_key="synthetic-rerun-outcome-00000001",
    )
    assert inserted is False
    assert replay == outcome
    _decide(
        service,
        session_id,
        outcome.proposal.proposal_id,
        first_run.run_id,
        "rerun-outcome-confirm",
    )

    enumeration = _propose(
        service,
        session_id,
        _enumeration_command(rerun.run_id, family, (opportunity_id,)),
        "rerun-enumeration",
    )
    assert enumeration.proposal.source_run_id == first_run.run_id
    _decide(
        service,
        session_id,
        enumeration.proposal.proposal_id,
        first_run.run_id,
        "rerun-enumeration-confirm",
    )
    before = repository.snapshot(session_id, first_run.input_fingerprint)
    assert before.families[0].enumerated_opportunity_ids == (opportunity_id,)
    assert before.families[0].opportunities[0].outcome is not None

    reopened = Database(database.path)
    reopened.initialize()
    restarted_snapshot = reopened.metric_lifecycle_evidence_repository().snapshot(
        session_id, first_run.input_fingerprint
    )
    assert restarted_snapshot == before

    assert models.delete_for_privacy(first_run.run_id) is True
    assert repository.list_proposals(session_id) == ()
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "metric_lifecycle_evidence_windows",
                "metric_lifecycle_evidence_proposals",
                "metric_lifecycle_evidence_enumeration_members",
                "metric_lifecycle_evidence_decisions",
            )
        }
    assert counts == {
        "metric_lifecycle_evidence_windows": 0,
        "metric_lifecycle_evidence_proposals": 0,
        "metric_lifecycle_evidence_enumeration_members": 0,
        "metric_lifecycle_evidence_decisions": 0,
    }


def test_list_fails_closed_when_complete_boundary_is_exceeded(
    tmp_path, monkeypatch
) -> None:
    _database, session_id, run, _models, repository, service = _service(tmp_path)
    monkeypatch.setattr(evidence_store, "MAX_LISTED_LIFECYCLE_PROPOSALS", 1)
    _propose(
        service,
        session_id,
        _opportunity_command(
            run.run_id, MetricLifecycleFamily.AMBIGUITY_RESOLUTION
        ),
        "bounded-list-first",
    )
    _propose(
        service,
        session_id,
        _opportunity_command(
            run.run_id, MetricLifecycleFamily.CLARIFICATION_YIELD
        ),
        "bounded-list-second",
    )
    with pytest.raises(DatabaseInvariantError, match="proven complete boundary"):
        repository.list_proposals(session_id)

    first, total = repository.list_proposals_page(session_id, limit=1, offset=0)
    second, repeated_total = repository.list_proposals_page(
        session_id, limit=1, offset=1
    )
    assert total == repeated_total == 2
    assert len(first) == len(second) == 1
    assert first[0].proposal.proposal_id != second[0].proposal.proposal_id
    assert (
        first[0].proposal.created_at,
        first[0].proposal.proposal_id,
    ) < (
        second[0].proposal.created_at,
        second[0].proposal.proposal_id,
    )
