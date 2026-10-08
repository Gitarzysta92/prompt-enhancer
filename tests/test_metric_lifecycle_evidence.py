"""Application rules for explicit, content-free lifecycle confirmations."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.metric_lifecycle_evidence import (
    METRIC_LIFECYCLE_DECISION_CONFIRMATION,
    MetricLifecycleConflictError,
    MetricLifecycleDecisionCommand,
    MetricLifecycleDecisionKind,
    MetricLifecycleEvidenceService,
    MetricLifecycleEvidenceSnapshot,
    MetricLifecycleFamily,
    MetricLifecycleLinkKind,
    MetricLifecycleOpportunityKind,
    MetricLifecycleOutcomeKind,
    MetricLifecycleProposalCommand,
    MetricLifecycleProposalKind,
    MetricLifecycleProposalStatus,
    MetricLifecycleProposalView,
    MetricLifecycleStaleWindowError,
)


NOW = datetime(2042, 4, 5, 12, 0, tzinfo=UTC)
SESSION_ID = hashlib.sha256(b"synthetic-lifecycle-session").hexdigest()
RUN_1 = hashlib.sha256(b"synthetic-lifecycle-run-1").hexdigest()
RUN_2 = hashlib.sha256(b"synthetic-lifecycle-run-2").hexdigest()
WINDOW_1 = hashlib.sha256(b"synthetic-lifecycle-window-1").hexdigest()
WINDOW_2 = hashlib.sha256(b"synthetic-lifecycle-window-2").hexdigest()


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()


class _Access:
    def selection_is_indexed(self, *_args, **_kwargs) -> bool:
        return True


class _Window:
    latest = SimpleNamespace(run_id=RUN_1, input_fingerprint=WINDOW_1)

    def get_latest(self, _session_id: str):
        return self.latest


class _Repository:
    def __init__(self) -> None:
        self.views: dict[str, MetricLifecycleProposalView] = {}

    def issue_proposal(self, proposal):
        existing = self.views.get(proposal.proposal_id)
        if existing is not None:
            return existing, False
        view = MetricLifecycleProposalView(proposal=proposal)
        self.views[proposal.proposal_id] = view
        return view, True

    def decide(self, decision):
        view = self.views[decision.proposal_id]
        if view.decision is not None:
            return view, False
        decided = MetricLifecycleProposalView(
            proposal=view.proposal,
            decision=decision,
        )
        self.views[decision.proposal_id] = decided
        return decided, True

    def get_proposal(self, proposal_id: str):
        return self.views.get(proposal_id)

    def list_proposals(self, _session_id: str):
        return tuple(self.views.values())

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> MetricLifecycleEvidenceSnapshot:
        raise AssertionError((session_id, source_window_fingerprint))


def _service() -> tuple[MetricLifecycleEvidenceService, _Window, _Repository]:
    window = _Window()
    repository = _Repository()
    return (
        MetricLifecycleEvidenceService(
            _Access(),
            window,
            repository,
            _Ids(),
            clock=lambda: NOW,
        ),
        window,
        repository,
    )


def _opportunity(
    *,
    run_id: str = RUN_1,
    family: MetricLifecycleFamily = MetricLifecycleFamily.AMBIGUITY_RESOLUTION,
) -> MetricLifecycleProposalCommand:
    kinds = {
        MetricLifecycleFamily.AMBIGUITY_RESOLUTION: (
            MetricLifecycleOpportunityKind.AMBIGUITY
        ),
        MetricLifecycleFamily.CLARIFICATION_YIELD: (
            MetricLifecycleOpportunityKind.CLARIFICATION
        ),
        MetricLifecycleFamily.EXPLORATION_CONVERSION: (
            MetricLifecycleOpportunityKind.EXPLORATION
        ),
        MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE: (
            MetricLifecycleOpportunityKind.SCOPE_CHANGE
        ),
        MetricLifecycleFamily.REWORK_CANDIDATE_RATE: (
            MetricLifecycleOpportunityKind.REWORK
        ),
    }
    return MetricLifecycleProposalCommand(
        expected_source_run_id=run_id,
        proposal_kind=MetricLifecycleProposalKind.OPPORTUNITY,
        family=family,
        opportunity_kind=kinds[family],
    )


def _decision(
    decision: MetricLifecycleDecisionKind = MetricLifecycleDecisionKind.CONFIRM,
) -> MetricLifecycleDecisionCommand:
    return MetricLifecycleDecisionCommand(
        expected_source_run_id=RUN_1,
        decision=decision,
        confirmation=METRIC_LIFECYCLE_DECISION_CONFIRMATION,
    )


def test_server_issues_identifiers_times_and_inert_proposal_status() -> None:
    service, _window, _repository = _service()

    view, applied = service.propose(
        session_id=SESSION_ID,
        command=_opportunity(),
        idempotency_key="synthetic-proposal-0001",
    )

    assert applied is True
    assert view.status is MetricLifecycleProposalStatus.PROPOSED
    assert view.decision is None
    assert view.proposal.created_at == NOW
    assert view.proposal.opportunity_id is not None
    assert len(view.proposal.proposal_id) == len(view.proposal.opportunity_id) == 64
    payload = view.model_dump_json()
    assert "text" not in payload
    assert "path" not in payload


def test_exact_proposal_retry_survives_a_changed_latest_run() -> None:
    service, window, _repository = _service()
    first, applied = service.propose(
        session_id=SESSION_ID,
        command=_opportunity(),
        idempotency_key="synthetic-proposal-0002",
    )
    assert applied is True
    window.latest = SimpleNamespace(run_id=RUN_2, input_fingerprint=WINDOW_2)

    replay, applied = service.propose(
        session_id=SESSION_ID,
        command=_opportunity(),
        idempotency_key="synthetic-proposal-0002",
    )

    assert applied is False
    assert replay == first
    with pytest.raises(MetricLifecycleConflictError, match="idempotency"):
        service.propose(
            session_id=SESSION_ID,
            command=_opportunity(
                family=MetricLifecycleFamily.CLARIFICATION_YIELD
            ),
            idempotency_key="synthetic-proposal-0002",
        )


def test_new_proposal_rejects_a_stale_source_run() -> None:
    service, window, _repository = _service()
    window.latest = SimpleNamespace(run_id=RUN_2, input_fingerprint=WINDOW_2)

    with pytest.raises(MetricLifecycleStaleWindowError, match="source run"):
        service.propose(
            session_id=SESSION_ID,
            command=_opportunity(),
            idempotency_key="synthetic-proposal-0003",
        )


def test_new_decision_rejects_changed_window_but_accepts_same_window_rerun() -> None:
    service, window, _repository = _service()
    proposal, _ = service.propose(
        session_id=SESSION_ID,
        command=_opportunity(),
        idempotency_key="synthetic-proposal-0004",
    )
    window.latest = SimpleNamespace(run_id=RUN_2, input_fingerprint=WINDOW_2)
    with pytest.raises(MetricLifecycleStaleWindowError, match="source window"):
        service.decide(
            session_id=SESSION_ID,
            proposal_id=proposal.proposal.proposal_id,
            command=_decision(),
            idempotency_key="synthetic-decision-0004",
        )

    window.latest = SimpleNamespace(run_id=RUN_2, input_fingerprint=WINDOW_1)
    decided, applied = service.decide(
        session_id=SESSION_ID,
        proposal_id=proposal.proposal.proposal_id,
        command=_decision(),
        idempotency_key="synthetic-decision-0004",
    )
    assert applied is True
    assert decided.status is MetricLifecycleProposalStatus.CONFIRMED


def test_exact_decision_retry_survives_a_changed_latest_window() -> None:
    service, window, _repository = _service()
    proposal, _ = service.propose(
        session_id=SESSION_ID,
        command=_opportunity(),
        idempotency_key="synthetic-proposal-0005",
    )
    first, applied = service.decide(
        session_id=SESSION_ID,
        proposal_id=proposal.proposal.proposal_id,
        command=_decision(),
        idempotency_key="synthetic-decision-0005",
    )
    assert applied is True
    window.latest = SimpleNamespace(run_id=RUN_2, input_fingerprint=WINDOW_2)

    replay, applied = service.decide(
        session_id=SESSION_ID,
        proposal_id=proposal.proposal.proposal_id,
        command=_decision(),
        idempotency_key="synthetic-decision-0005",
    )

    assert applied is False
    assert replay == first
    with pytest.raises(MetricLifecycleConflictError, match="another decision"):
        service.decide(
            session_id=SESSION_ID,
            proposal_id=proposal.proposal.proposal_id,
            command=_decision(MetricLifecycleDecisionKind.REJECT),
            idempotency_key="synthetic-decision-0006",
        )


@pytest.mark.parametrize(
    "fields",
    (
        {
            "proposal_kind": MetricLifecycleProposalKind.OPPORTUNITY,
            "opportunity_id": "a" * 64,
        },
        {
            "proposal_kind": MetricLifecycleProposalKind.OUTCOME,
            "opportunity_id": "a" * 64,
            "link_kind": MetricLifecycleLinkKind.AMBIGUITY_RESOLUTION,
            "outcome_kind": MetricLifecycleOutcomeKind.CLARIFICATION_INCORPORATED,
        },
        {
            "proposal_kind": MetricLifecycleProposalKind.ENUMERATION,
            "enumerated_opportunity_ids": ("b" * 64, "a" * 64),
        },
    ),
)
def test_closed_commands_reject_caller_issued_or_cross_family_shapes(fields) -> None:
    base = {
        "expected_source_run_id": RUN_1,
        "family": MetricLifecycleFamily.AMBIGUITY_RESOLUTION,
        "opportunity_kind": MetricLifecycleOpportunityKind.AMBIGUITY,
    }
    with pytest.raises(ValidationError):
        MetricLifecycleProposalCommand(**base, **fields)
