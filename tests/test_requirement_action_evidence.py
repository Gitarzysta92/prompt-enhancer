from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionFamily,
    ActionState,
    TypedEvidenceProvenance,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES,
    REQUIREMENT_ACTION_DECISION_CONFIRMATION,
    REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION,
    REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
    REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION,
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    ConfirmedRequirementActionLink,
    InMemoryRequirementActionReviewContextStore,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    RequirementActionConflictError,
    RequirementActionDecisionCommand,
    RequirementActionDecisionKind,
    RequirementActionEvidenceFileV1,
    RequirementActionEvidenceService,
    RequirementActionEvidenceSnapshot,
    RequirementActionInputError,
    RequirementActionLinkEntry,
    RequirementActionProposalPageSnapshot,
    RequirementActionReviewCandidate,
    RequirementActionReviewRequirement,
    RequirementActionProposalStatus,
    RequirementActionProposalView,
    RequirementActionNotFoundError,
    SealedRunRequirementActionSource,
    RequirementActionSourceContract,
    RequirementActionStaleWindowError,
    escape_requirement_action_review_display,
    parse_requirement_action_evidence_file,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_candidate_metadata_fingerprint,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_plan_snapshot_fingerprint,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_6,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    ConfirmedRequirementEvidence,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanProducer,
    RequirementPlanProducerReceipt,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
    EphemeralRedactedActionDescriptor,
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.domain import EventKind, Provider, ToolCategory
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
SESSION = "1" * 64
RUN = "2" * 64
WINDOW = "3" * 64
PLAN_CONFIRMATION = "4" * 64
PLAN_PROPOSAL = "5" * 64
REQUIREMENT_A = "a" * 64
REQUIREMENT_B = "b" * 64
ACTION_A = "c" * 64
ACTION_B = "d" * 64


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hmac.new(
            b"synthetic-requirement-action-test-key",
            "\x1f".join((namespace, *values)).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()


def _requirement_snapshot(*, window: str = WINDOW) -> RequirementPlanEvidenceSnapshot:
    return RequirementPlanEvidenceSnapshot(
        session_id=SESSION,
        source_window_fingerprint=window,
        confirmation_id=PLAN_CONFIRMATION,
        proposal_id=PLAN_PROPOSAL,
        producer_receipt=RequirementPlanProducerReceipt(
            claim_fingerprint="6" * 64
        ),
        review_rubric_version="active-requirement-plan-review-rubric-v1",
        requirements=(
            ConfirmedRequirementEvidence(
                requirement_id=REQUIREMENT_A,
                coordinate=RequirementCoordinate(message_sequence=1, clause_index=0),
                disposition=RequirementDisposition.NOT_LINKED,
            ),
            ConfirmedRequirementEvidence(
                requirement_id=REQUIREMENT_B,
                coordinate=RequirementCoordinate(message_sequence=1, clause_index=1),
                disposition=RequirementDisposition.NOT_LINKED,
            ),
        ),
        complete_user_clause_classification=True,
    )


def test_requirement_plan_snapshot_fingerprint_accepts_real_keyed_factory_and_drifts(
) -> None:
    identifiers = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    requirements = tuple(
        ConfirmedRequirementEvidence(
            requirement_id=f"{index + 1:064x}",
            coordinate=RequirementCoordinate(
                message_sequence=index,
                clause_index=0,
            ),
            disposition=RequirementDisposition.NOT_LINKED,
        )
        for index in range(128)
    )
    snapshot = _requirement_snapshot().model_copy(
        update={"requirements": requirements}
    )

    fingerprint = requirement_plan_snapshot_fingerprint(snapshot, identifiers)
    round_tripped = RequirementPlanEvidenceSnapshot.model_validate_json(
        snapshot.model_dump_json()
    )

    assert len(fingerprint) == 64
    assert requirement_plan_snapshot_fingerprint(
        round_tripped,
        identifiers,
    ) == fingerprint
    assert requirement_plan_snapshot_fingerprint(
        snapshot.model_copy(update={"source_window_fingerprint": "7" * 64}),
        identifiers,
    ) != fingerprint


def _manifest(*, run: str = RUN, window: str = WINDOW) -> RequirementActionCandidateManifest:
    provenance = TypedEvidenceProvenance(
        provider=Provider.SYNTHETIC,
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        decoder_key="safe-event-evidence",
        decoder_version="4",
        source_schema_version="synthetic-source.1",
        extraction_complete=True,
    )
    manifest = RequirementActionCandidateManifest(
        session_id=SESSION,
        source_run_id=run,
        source_window_fingerprint=window,
        provenance=provenance,
        extraction_complete=True,
        enumeration_complete=True,
        actions=(
            RequirementActionCandidate(
                candidate_index=0,
                action_id=ACTION_A,
                source_reference_id="7" * 64,
                sequence=10,
                event_kind=EventKind.TOOL_END,
                tool_category=ToolCategory.FILE_WRITE,
                occurred_at=NOW - timedelta(minutes=2),
                duration_ms=150,
                family=ActionFamily.FILE_CHANGE,
                state=ActionState.COMPLETED,
            ),
            RequirementActionCandidate(
                candidate_index=1,
                action_id=ACTION_B,
                source_reference_id="8" * 64,
                sequence=11,
                event_kind=EventKind.TOOL_END,
                tool_category=ToolCategory.TEST,
                occurred_at=NOW - timedelta(minutes=1),
                duration_ms=900,
                family=ActionFamily.COMMAND,
                state=ActionState.FAILED,
            ),
        ),
        manifest_fingerprint="9" * 64,
    )
    return manifest.model_copy(
        update={
            "manifest_fingerprint": requirement_action_candidate_manifest_fingerprint(
                manifest
            )
        }
    )


def _context(
    *,
    window: str = WINDOW,
    message_text: str = "Create the synthetic file. Run the synthetic tests.",
    tool_name: str = "example-file-tool",
    invocation_preview: str = '{"target":"example-output.txt"}',
    result_or_effect_preview: str = '{"status":"example-written"}',
) -> P1TextAnalysisInput:
    candidates = _manifest().actions
    message = EphemeralRedactedMessage(
        message_id="e" * 64,
        sequence=1,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(message_text),
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=SESSION,
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=True,
        available_message_kinds=frozenset({TextMessageKind.REQUEST}),
        analysis_window_fingerprint=window,
        focus_message_id=message.message_id,
        observed_message_count=1,
        eligible_message_count=1,
        messages=(message,),
        task_profile=TextTaskProfile(applicability=()),
        action_descriptor_algorithm_version=(
            ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
        ),
        action_descriptor_extraction_complete=True,
        action_descriptors=(
            EphemeralRedactedActionDescriptor(
                source_reference_id="7" * 64,
                event_kind=EventKind.TOOL_END,
                tool_name=SecretStr(tool_name),
                invocation_preview=SecretStr(invocation_preview),
                result_or_effect_preview=SecretStr(result_or_effect_preview),
                invocation_truncated=False,
                result_or_effect_truncated=False,
                redactor_version="synthetic-redactor.1",
                candidate_metadata_fingerprint_version=(
                    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                ),
                candidate_metadata_fingerprint=(
                    requirement_action_candidate_metadata_fingerprint(
                        source_reference_id=candidates[0].source_reference_id,
                        sequence=candidates[0].sequence,
                        event_kind=candidates[0].event_kind,
                        tool_category=candidates[0].tool_category,
                        occurred_at=candidates[0].occurred_at,
                        duration_ms=candidates[0].duration_ms,
                        family=candidates[0].family,
                        state=candidates[0].state,
                    )
                ),
            ),
            EphemeralRedactedActionDescriptor(
                source_reference_id="8" * 64,
                event_kind=EventKind.TOOL_END,
                tool_name=SecretStr("example-test-tool"),
                invocation_preview=SecretStr('{"suite":"example"}'),
                result_or_effect_preview=SecretStr(
                    '{"status":"example-failed"}'
                ),
                invocation_truncated=False,
                result_or_effect_truncated=False,
                redactor_version="synthetic-redactor.1",
                candidate_metadata_fingerprint_version=(
                    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                ),
                candidate_metadata_fingerprint=(
                    requirement_action_candidate_metadata_fingerprint(
                        source_reference_id=candidates[1].source_reference_id,
                        sequence=candidates[1].sequence,
                        event_kind=candidates[1].event_kind,
                        tool_category=candidates[1].tool_category,
                        occurred_at=candidates[1].occurred_at,
                        duration_ms=candidates[1].duration_ms,
                        family=candidates[1].family,
                        state=candidates[1].state,
                    )
                ),
            ),
        ),
    )


def _context_with_forged_candidate_metadata(
    **metadata_overrides: object,
) -> P1TextAnalysisInput:
    context = _context()
    candidate = _manifest().actions[0]
    metadata: dict[str, object] = {
        "source_reference_id": candidate.source_reference_id,
        "sequence": candidate.sequence,
        "event_kind": candidate.event_kind,
        "tool_category": candidate.tool_category,
        "occurred_at": candidate.occurred_at,
        "duration_ms": candidate.duration_ms,
        "family": candidate.family,
        "state": candidate.state,
    }
    metadata.update(metadata_overrides)
    forged_fingerprint = requirement_action_candidate_metadata_fingerprint(
        **metadata,  # type: ignore[arg-type]
    )
    descriptor = context.action_descriptors[0].model_copy(
        update={"candidate_metadata_fingerprint": forged_fingerprint}
    )
    return context.model_copy(
        update={
            "action_descriptors": (
                descriptor,
                context.action_descriptors[1],
            )
        }
    )


class _Source:
    def __init__(self, contract: RequirementActionSourceContract) -> None:
        self.value = contract

    def current_source_contract(self, session_id: str) -> RequirementActionSourceContract:
        assert session_id == self.value.session_id
        return self.value


class _Repository:
    def __init__(self, ids: _Ids) -> None:
        self.ids = ids
        self.proposals: dict[str, RequirementActionProposalView] = {}
        self.heads: dict[tuple[str, str], str] = {}

    def issue_proposal(self, proposal):  # type: ignore[no-untyped-def]
        existing = self.proposals.get(proposal.proposal_id)
        if existing is not None:
            if existing.proposal == proposal:
                return existing, False
            raise RequirementActionConflictError("idempotency conflict")
        view = RequirementActionProposalView(
            proposal=proposal,
            status=RequirementActionProposalStatus.PROPOSED,
        )
        self.proposals[proposal.proposal_id] = view
        return view, True

    def decide(self, decision):  # type: ignore[no-untyped-def]
        view = self.proposals[decision.proposal_id]
        if view.decision is not None:
            if view.decision == decision:
                return view, False
            raise RequirementActionConflictError("decision conflict")
        if decision.decision is RequirementActionDecisionKind.CONFIRM:
            key = (view.proposal.session_id, view.proposal.source_window_fingerprint)
            if self.heads.get(key) != view.proposal.expected_predecessor_confirmation_id:
                raise RequirementActionConflictError("predecessor conflict")
            self.heads[key] = decision.decision_id
        updated = RequirementActionProposalView(
            proposal=view.proposal,
            decision=decision,
            status=(
                RequirementActionProposalStatus.CONFIRMED
                if decision.decision is RequirementActionDecisionKind.CONFIRM
                else RequirementActionProposalStatus.REJECTED
            ),
        )
        self.proposals[decision.proposal_id] = updated
        return updated, True

    def get_proposal(self, proposal_id: str):  # type: ignore[no-untyped-def]
        return self.proposals.get(proposal_id)

    def list_proposals_page(  # type: ignore[no-untyped-def]
        self, session_id, *, limit, offset, snapshot=None
    ):
        values = tuple(
            sorted(
                (
                    item
                    for item in self.proposals.values()
                    if item.proposal.session_id == session_id
                ),
                key=lambda item: (item.proposal.created_at, item.proposal.proposal_id),
            )
        )
        boundary = RequirementActionProposalPageSnapshot(
            snapshot_id="0" * 64,
            total=len(values),
            decision_count=sum(item.decision is not None for item in values),
            high_water_created_at=(None if not values else values[-1].proposal.created_at),
            high_water_proposal_id=(None if not values else values[-1].proposal.proposal_id),
        )
        return values[offset : offset + limit], boundary

    def snapshot(  # type: ignore[no-untyped-def]
        self, session_id: str, source_window_fingerprint: str
    ):
        head = self.heads.get((session_id, source_window_fingerprint))
        if head is None:
            return RequirementActionEvidenceSnapshot(
                session_id=session_id,
                source_window_fingerprint=source_window_fingerprint,
            )
        view = next(
            item
            for item in self.proposals.values()
            if item.decision and item.decision.decision_id == head
        )
        record = view.proposal
        manifest = RequirementActionCandidateManifest(
            session_id=record.session_id,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
            provenance=record.candidate_provenance,
            extraction_complete=record.candidate_extraction_complete,
            enumeration_complete=record.candidate_enumeration_complete,
            actions=record.candidates,
            manifest_fingerprint=record.candidate_manifest_fingerprint,
        )
        snapshot = RequirementActionEvidenceSnapshot(
            session_id=record.session_id,
            source_run_id=record.source_run_id,
            source_window_fingerprint=record.source_window_fingerprint,
            requirement_plan_confirmation_id=record.requirement_plan_confirmation_id,
            requirement_plan_evidence_fingerprint=(
                record.requirement_plan_evidence_fingerprint
            ),
            confirmation_id=head,
            proposal_id=record.proposal_id,
            reviewed_descriptor_set_fingerprint=(
                view.decision.reviewed_descriptor_set_fingerprint
            ),
            producer_receipt=record.producer_receipt,
            candidate_manifest=manifest,
            requirements=record.requirements,
            links=record.links,
            complete_requirement_enumeration=True,
            complete_action_candidate_enumeration=True,
            complete_requirement_link_classification=True,
            evidence_fingerprint="f" * 64,
        )
        return snapshot.model_copy(
            update={
                "evidence_fingerprint": requirement_action_evidence_snapshot_fingerprint(
                    snapshot, self.ids
                )
            }
        )

    def latest_snapshot(self, session_id: str):  # type: ignore[no-untyped-def]
        candidates = tuple(
            (window, confirmation)
            for (owner, window), confirmation in self.heads.items()
            if owner == session_id
        )
        if not candidates:
            return RequirementActionEvidenceSnapshot(
                session_id=session_id,
                source_window_fingerprint=WINDOW,
            )
        return self.snapshot(session_id, candidates[-1][0])


def _harness(
    *,
    context: P1TextAnalysisInput | None = None,
):  # type: ignore[no-untyped-def]
    ids = _Ids()
    requirements = _requirement_snapshot()
    manifest = _manifest()
    source_contract = RequirementActionSourceContract(
        session_id=SESSION,
        expected_source_run_id=RUN,
        source_window_fingerprint=WINDOW,
        projection_version=METRIC_PROJECTION_V2_VERSION_6,
        requirement_plan_evidence=requirements,
        candidate_manifest=manifest,
    )
    source = _Source(source_contract)
    repository = _Repository(ids)
    reviews = InMemoryRequirementActionReviewContextStore(
        clock=lambda: NOW,
        monotonic_clock=lambda: 100.0,
        token_factory=lambda: "f" * 64,
        candidate_binding_key=b"s" * 32,
    )
    plan_fingerprint = requirement_plan_snapshot_fingerprint(requirements, ids)
    reviews.publish(
        RUN,
        _context() if context is None else context,
        requirements,
        plan_fingerprint,
        manifest,
    )
    service = RequirementActionEvidenceService(
        repository,
        source,
        ids,
        review_contexts=reviews,
        clock=lambda: NOW,
    )
    return service, source, repository, reviews


def _payload(
    service: RequirementActionEvidenceService,
    *,
    links: tuple[RequirementActionLinkEntry, ...] | None = None,
    created_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> bytes:
    contract = service.contract(SESSION)
    file = RequirementActionEvidenceFileV1(
        schema_version=REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION,
        session_id=SESSION,
        expected_source_run_id=contract.expected_source_run_id,
        source_window_fingerprint=contract.source_window_fingerprint,
        requirement_plan_confirmation_id=contract.requirement_plan_confirmation_id,
        requirement_plan_evidence_fingerprint=(
            contract.requirement_plan_evidence_fingerprint
        ),
        candidate_manifest_fingerprint=contract.candidate_manifest.manifest_fingerprint,
        expected_predecessor_confirmation_id=(
            contract.expected_predecessor_confirmation_id
        ),
        nonce="9" * 64,
        created_at=created_at,
        expires_at=expires_at,
        producer=RequirementPlanProducer(
            kind="local_coding_agent",
            producer_id="synthetic-agent",
            producer_version="synthetic.1",
            model_id="synthetic-model",
            authority="untrusted_provenance_claim",
        ),
        complete_requirement_enumeration=True,
        complete_action_candidate_enumeration=True,
        complete_requirement_link_classification=True,
        links=(
            (
                RequirementActionLinkEntry(
                    requirement_index=0, action_candidate_indexes=(0,)
                ),
                RequirementActionLinkEntry(requirement_index=1),
            )
            if links is None
            else links
        ),
        contains_action_state_claims=False,
        contains_objective_proof_claims=False,
        contains_metric_values=False,
        contains_prose=False,
        contains_paths=False,
    )
    return json.dumps(
        file.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _import(  # type: ignore[no-untyped-def]
    service: RequirementActionEvidenceService,
    *,
    key: str = "proposal-key-0001",
):
    payload = _payload(service)
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    view, created = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
        idempotency_key=key,
        now=NOW,
    )
    return preview, view, created


def _review_context(
    context: P1TextAnalysisInput,
):  # type: ignore[no-untyped-def]
    service, _source, _repository, reviews = _harness(context=context)
    _preview, view, _created = _import(service)
    review = service.review_proposal(
        session_id=SESSION,
        proposal_id=view.proposal.proposal_id,
        expected_source_run_id=RUN,
    )
    return service, reviews, view, review


def test_preview_and_import_are_inert_and_persist_only_opaque_producer_receipt() -> None:
    service, _source, repository, _reviews = _harness()

    preview, view, created = _import(service)

    assert created is True
    assert preview.producer.producer_id == "synthetic-agent"
    assert preview.linked_requirement_count == 1
    assert preview.unlinked_requirement_count == 1
    assert view.status is RequirementActionProposalStatus.PROPOSED
    assert view.proposal.links == (
        ConfirmedRequirementActionLink(
            requirement_id=REQUIREMENT_A, action_ids=(ACTION_A,)
        ),
        ConfirmedRequirementActionLink(requirement_id=REQUIREMENT_B),
    )
    durable_json = json.dumps(view.proposal.model_dump(mode="json"))
    assert "synthetic-agent" not in durable_json
    assert "synthetic-model" not in durable_json
    assert repository.snapshot(SESSION, WINDOW).confirmation_id is None


def test_native_review_displays_every_clause_candidate_and_membership_then_confirms_once() -> None:
    service, _source, repository, reviews = _harness()
    _preview, view, _created = _import(service)

    review = service.review_proposal(
        session_id=SESSION,
        proposal_id=view.proposal.proposal_id,
        expected_source_run_id=RUN,
    )

    assert tuple(item.text for item in review.requirements) == (
        "Create the synthetic file.",
        "Run the synthetic tests.",
    )
    assert review.candidates == _manifest().actions
    assert review.candidate_memberships[0].linked_requirement_ids == (REQUIREMENT_A,)
    assert review.candidate_memberships[1].linked_requirement_ids == ()
    command = RequirementActionDecisionCommand(
        expected_source_run_id=RUN,
        decision=RequirementActionDecisionKind.CONFIRM,
        confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
        review_receipt_id=review.review_receipt_id,
        reviewed_graph_fingerprint=review.reviewed_graph_fingerprint,
        candidate_manifest_fingerprint=review.candidate_manifest_fingerprint,
        reviewed_candidate_set_fingerprint=review.reviewed_candidate_set_fingerprint,
        reviewed_descriptor_set_fingerprint=(
            review.reviewed_descriptor_set_fingerprint
        ),
        complete_review_acknowledged=True,
        all_requirements_and_candidates_acknowledged=True,
        all_linked_action_semantics_reviewed=True,
    )
    decided, applied = service.decide(
        session_id=SESSION,
        proposal_id=view.proposal.proposal_id,
        command=command,
        idempotency_key="decision-key-0001",
    )

    assert applied is True
    assert decided.status is RequirementActionProposalStatus.CONFIRMED
    snapshot = repository.snapshot(SESSION, WINDOW)
    assert snapshot.links[0].action_ids == (ACTION_A,)
    assert snapshot.evidence_fingerprint == requirement_action_evidence_snapshot_fingerprint(
        snapshot, repository.ids
    )
    with pytest.raises(RequirementActionConflictError):
        reviews.consume_review_receipt(
            review_receipt_id=review.review_receipt_id,
            proposal=view,
            reviewed_graph_fingerprint=review.reviewed_graph_fingerprint,
            candidate_manifest_fingerprint=review.candidate_manifest_fingerprint,
            reviewed_candidate_set_fingerprint=(
                review.reviewed_candidate_set_fingerprint
            ),
            reviewed_descriptor_set_fingerprint=(
                review.reviewed_descriptor_set_fingerprint
            ),
        )


@pytest.mark.parametrize(
    "metadata_overrides",
    (
        {"state": ActionState.FAILED},
        {"tool_category": ToolCategory.COMMAND},
        {"occurred_at": NOW - timedelta(minutes=3)},
        {"sequence": 12},
        {"duration_ms": 151},
    ),
    ids=("state", "category", "time", "sequence", "duration"),
)
def test_review_publish_rejects_same_id_candidate_metadata_drift(
    metadata_overrides: dict[str, object],
) -> None:
    with pytest.raises(
        ValueError,
        match="action review descriptor authority is incomplete",
    ):
        _harness(
            context=_context_with_forged_candidate_metadata(
                **metadata_overrides
            )
        )


def test_descriptor_content_is_bound_independently_of_candidate_metadata() -> None:
    first_context = _context(invocation_preview='{"value":"first"}')
    second_context = _context(invocation_preview='{"value":"second"}')

    _service, _reviews, _view, first = _review_context(first_context)
    _service, _reviews, _view, second = _review_context(second_context)

    assert (
        first.candidate_memberships[0].candidate_metadata_fingerprint
        == second.candidate_memberships[0].candidate_metadata_fingerprint
    )
    assert first.reviewed_candidate_set_fingerprint != (
        second.reviewed_candidate_set_fingerprint
    )
    assert first.reviewed_descriptor_set_fingerprint != (
        second.reviewed_descriptor_set_fingerprint
    )


def test_visible_review_display_escape_is_injective_and_one_pass() -> None:
    raw = (
        "A\\B\n\r\t\x07\u202e\u2066\u2028\u2029\ud800"
        "\U000e0001Zażółć🙂"
    )

    escaped = escape_requirement_action_review_display(raw)

    assert escaped == (
        "A\\\\B\\n\\r\\t\\u0007\\u202e\\u2066\\u2028\\u2029\\ud800"
        "\\U000e0001Zażółć🙂"
    )
    assert escape_requirement_action_review_display("\u202e") == "\\u202e"
    assert escape_requirement_action_review_display("\\u202e") == "\\\\u202e"
    assert escape_requirement_action_review_display(
        escape_requirement_action_review_display("\u202e")
    ) == "\\\\u202e"
    assert all(
        value not in escaped
        for value in (
            "\n",
            "\r",
            "\t",
            "\x07",
            "\u202e",
            "\u2066",
            "\u2028",
            "\u2029",
            "\ud800",
            "\U000e0001",
        )
    )


@pytest.mark.parametrize(
    "forbidden",
    ("\n", "\u202e", "\u2066", "\u2028", "\u2029", "\ud800"),
)
def test_review_dtos_reject_raw_forbidden_display_controls(
    forbidden: str,
) -> None:
    with pytest.raises(ValidationError) as requirement_error:
        RequirementActionReviewRequirement(
            requirement_id=REQUIREMENT_A,
            coordinate=RequirementCoordinate(message_sequence=1, clause_index=0),
            text=f"before{forbidden}after",
        )
    with pytest.raises(ValidationError) as candidate_error:
        RequirementActionReviewCandidate(
            candidate=_manifest().actions[0],
            candidate_metadata_fingerprint_version=(
                ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
            ),
            candidate_metadata_fingerprint="0" * 64,
            tool_name=f"before{forbidden}after",
            invocation_preview="synthetic invocation",
            result_or_effect_preview="synthetic effect",
            redactor_version="synthetic-redactor.1",
        )
    if forbidden != "\ud800":
        assert "raw forbidden control" in str(requirement_error.value)
        assert "raw forbidden control" in str(candidate_error.value)


def test_review_service_visibly_escapes_and_binds_every_display_string() -> None:
    raw_requirement = "Create \u202e literal \\u202e Zażółć."
    raw_tool_name = "tool\n\u2066\\n"
    raw_invocation = "invoke\t\u2028"
    raw_effect = "effect\r\u2029\ud800"
    context = _context(
        message_text=f"{raw_requirement} Run the synthetic tests.",
        tool_name=raw_tool_name,
        invocation_preview=raw_invocation,
        result_or_effect_preview=raw_effect,
    )
    service, reviews, view, review = _review_context(context)

    assert review.review_visible_display_algorithm_version == (
        REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    )
    assert review.requirements[0].text == (
        "Create \\u202e literal \\\\u202e Zażółć."
    )
    assert review.candidate_memberships[0].tool_name == (
        "tool\\n\\u2066\\\\n"
    )
    assert review.candidate_memberships[0].invocation_preview == (
        "invoke\\t\\u2028"
    )
    assert review.candidate_memberships[0].result_or_effect_preview == (
        "effect\\r\\u2029\\ud800"
    )
    encoded = review.model_dump_json()
    assert all(
        value not in encoded
        for value in ("\n", "\r", "\t", "\u202e", "\u2066", "\u2028", "\u2029", "\ud800")
    )
    decoded = json.loads(encoded)
    assert decoded["requirements"][0]["text"] == review.requirements[0].text
    assert (
        decoded["candidate_memberships"][0]["result_or_effect_preview"]
        == review.candidate_memberships[0].result_or_effect_preview
    )

    raw_requirements = (
        review.requirements[0].model_copy(update={"text": raw_requirement}),
        *review.requirements[1:],
    )
    raw_memberships = (
        review.candidate_memberships[0].model_copy(
            update={
                "tool_name": raw_tool_name,
                "invocation_preview": raw_invocation,
                "result_or_effect_preview": raw_effect,
            }
        ),
        *review.candidate_memberships[1:],
    )
    raw_candidate_fingerprint = reviews._candidate_set_fingerprint(
        raw_requirements,
        raw_memberships,
    )
    raw_descriptor_fingerprint = reviews._descriptor_set_fingerprint(
        raw_memberships
    )
    assert raw_candidate_fingerprint != review.reviewed_candidate_set_fingerprint
    assert raw_descriptor_fingerprint != review.reviewed_descriptor_set_fingerprint
    with pytest.raises(
        RequirementActionConflictError,
        match="review receipt binding changed",
    ):
        service.decide(
            session_id=SESSION,
            proposal_id=view.proposal.proposal_id,
            command=RequirementActionDecisionCommand(
                expected_source_run_id=RUN,
                decision=RequirementActionDecisionKind.CONFIRM,
                confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
                review_receipt_id=review.review_receipt_id,
                reviewed_graph_fingerprint=review.reviewed_graph_fingerprint,
                candidate_manifest_fingerprint=(
                    review.candidate_manifest_fingerprint
                ),
                reviewed_candidate_set_fingerprint=raw_candidate_fingerprint,
                reviewed_descriptor_set_fingerprint=raw_descriptor_fingerprint,
                complete_review_acknowledged=True,
                all_requirements_and_candidates_acknowledged=True,
                all_linked_action_semantics_reviewed=True,
            ),
            idempotency_key="decision-visible-escape",
        )


def test_raw_control_and_literal_escape_have_distinct_stable_review_hmacs() -> None:
    raw_control_context = _context(
        message_text="Create \u202e item. Run the synthetic tests.",
        tool_name="tool\u202e",
    )
    literal_escape_context = _context(
        message_text="Create \\u202e item. Run the synthetic tests.",
        tool_name="tool\\u202e",
    )

    _service, _reviews, _view, control = _review_context(raw_control_context)
    _service, _reviews, _view, literal = _review_context(literal_escape_context)
    _service, _reviews, _view, repeated = _review_context(raw_control_context)

    assert control.requirements[0].text == "Create \\u202e item."
    assert literal.requirements[0].text == "Create \\\\u202e item."
    assert control.reviewed_candidate_set_fingerprint != (
        literal.reviewed_candidate_set_fingerprint
    )
    assert control.reviewed_descriptor_set_fingerprint != (
        literal.reviewed_descriptor_set_fingerprint
    )
    assert control.reviewed_candidate_set_fingerprint == (
        repeated.reviewed_candidate_set_fingerprint
    )
    assert control.reviewed_descriptor_set_fingerprint == (
        repeated.reviewed_descriptor_set_fingerprint
    )


@pytest.mark.parametrize(
    "context",
    (
        _context(
            message_text=("\\" * 16_000) + ". Run the synthetic tests."
        ),
        _context(tool_name="\\" * 120),
        _context(invocation_preview="\\" * 4_096),
        _context(result_or_effect_preview="\\" * 4_096),
    ),
    ids=("requirement", "tool-name", "invocation", "effect"),
)
def test_visible_review_escape_expansion_fails_closed_without_truncation(
    context: P1TextAnalysisInput,
) -> None:
    service, _source, _repository, _reviews = _harness(context=context)
    _preview, view, _created = _import(service)

    with pytest.raises(
        RequirementActionConflictError,
        match="visible requirement-action review text exceeds its bound",
    ):
        service.review_proposal(
            session_id=SESSION,
            proposal_id=view.proposal.proposal_id,
            expected_source_run_id=RUN,
        )


def test_exact_decision_replay_survives_source_change_but_new_confirm_fails() -> None:
    service, source, _repository, _reviews = _harness()
    _preview, first, _created = _import(service)
    review = service.review_proposal(
        session_id=SESSION,
        proposal_id=first.proposal.proposal_id,
        expected_source_run_id=RUN,
    )
    command = RequirementActionDecisionCommand(
        expected_source_run_id=RUN,
        decision=RequirementActionDecisionKind.CONFIRM,
        confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
        review_receipt_id=review.review_receipt_id,
        reviewed_graph_fingerprint=review.reviewed_graph_fingerprint,
        candidate_manifest_fingerprint=review.candidate_manifest_fingerprint,
        reviewed_candidate_set_fingerprint=review.reviewed_candidate_set_fingerprint,
        reviewed_descriptor_set_fingerprint=(
            review.reviewed_descriptor_set_fingerprint
        ),
        complete_review_acknowledged=True,
        all_requirements_and_candidates_acknowledged=True,
        all_linked_action_semantics_reviewed=True,
    )
    service.decide(
        session_id=SESSION,
        proposal_id=first.proposal.proposal_id,
        command=command,
        idempotency_key="decision-key-0002",
    )
    source.value = source.value.model_copy(
        update={"expected_source_run_id": "0" * 64}
    )

    replay, applied = service.decide(
        session_id=SESSION,
        proposal_id=first.proposal.proposal_id,
        command=command,
        idempotency_key="decision-key-0002",
    )

    assert applied is False
    assert replay.status is RequirementActionProposalStatus.CONFIRMED


def test_rejection_is_independent_of_stale_source_and_native_review() -> None:
    service, source, _repository, _reviews = _harness()
    _preview, view, _created = _import(service)
    source.value = source.value.model_copy(
        update={"expected_source_run_id": "0" * 64}
    )

    rejected, applied = service.decide(
        session_id=SESSION,
        proposal_id=view.proposal.proposal_id,
        command=RequirementActionDecisionCommand(
            expected_source_run_id=RUN,
            decision=RequirementActionDecisionKind.REJECT,
            confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
        ),
        idempotency_key="decision-key-0003",
    )

    assert applied is True
    assert rejected.status is RequirementActionProposalStatus.REJECTED


def test_file_parser_and_source_binding_fail_closed() -> None:
    service, _source, _repository, _reviews = _harness()
    payload = _payload(service)
    parsed, digest = parse_requirement_action_evidence_file(payload, now=NOW)
    assert parsed.session_id == SESSION
    assert digest == hashlib.sha256(payload).hexdigest()

    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(payload + b"\n", now=NOW)
    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(
            b'{"session_id":"' + SESSION.encode() + b'","session_id":"' + SESSION.encode() + b'"}',
            now=NOW,
        )
    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(
            b'{"value":1.5}', now=NOW
        )
    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(
            b"{" + b'"x":' * 10 + b"0" + b"}" * 10,
            now=NOW,
        )
    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(
            b"x" * (MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES + 1), now=NOW
        )

    expired = _payload(
        service,
        created_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(hours=1),
    )
    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(expired, now=NOW)

    incomplete = _payload(
        service,
        links=(RequirementActionLinkEntry(requirement_index=0),),
    )
    with pytest.raises(RequirementActionInputError):
        service.preview(session_id=SESSION, payload=incomplete, now=NOW)
    absent_action = _payload(
        service,
        links=(
            RequirementActionLinkEntry(
                requirement_index=0, action_candidate_indexes=(2,)
            ),
            RequirementActionLinkEntry(requirement_index=1),
        ),
    )
    with pytest.raises(RequirementActionInputError):
        service.preview(session_id=SESSION, payload=absent_action, now=NOW)

    raw = json.loads(payload)
    raw["action_state"] = "completed"
    forged = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("ascii")
    with pytest.raises(RequirementActionInputError):
        parse_requirement_action_evidence_file(forged, now=NOW)


def test_confirmation_requires_both_explicit_review_acknowledgements() -> None:
    with pytest.raises(ValidationError):
        RequirementActionDecisionCommand(
            expected_source_run_id=RUN,
            decision=RequirementActionDecisionKind.CONFIRM,
            confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
            review_receipt_id="1" * 64,
            reviewed_graph_fingerprint="2" * 64,
            candidate_manifest_fingerprint="3" * 64,
            reviewed_candidate_set_fingerprint="4" * 64,
            complete_review_acknowledged=True,
            all_requirements_and_candidates_acknowledged=False,
        )


def test_stable_paging_is_signed_and_delegated() -> None:
    service, _source, _repository, _reviews = _harness()
    _import(service)

    page, snapshot = service.list_page(SESSION, limit=1, offset=0)

    assert len(page) == 1
    assert snapshot.snapshot_id != "0" * 64
    page_again, same_snapshot = service.list_page(
        SESSION, limit=1, offset=0, snapshot=snapshot
    )
    assert page_again == page
    assert same_snapshot == snapshot
    with pytest.raises(RequirementActionInputError):
        service.list_page(SESSION, limit=1, offset=1)


def test_sealed_source_requires_matching_latest_run_and_live_context() -> None:
    _service, _source, _repository, reviews = _harness()
    ids = _Ids()
    plan = _requirement_snapshot()
    plan_fingerprint = requirement_plan_snapshot_fingerprint(plan, ids)
    binding = SimpleNamespace(
        evidence_source=SimpleNamespace(value="reviewed_requirement_plan"),
        session_id=SESSION,
        source_window_fingerprint=WINDOW,
        confirmation_id=PLAN_CONFIRMATION,
        proposal_id=PLAN_PROPOSAL,
        evidence_fingerprint=plan_fingerprint,
        evidence_schema_version=plan.schema_version,
        evidence_policy_version=plan.policy_version,
    )
    latest = SimpleNamespace(
        session_id=SESSION,
        run_id=RUN,
        input_fingerprint=WINDOW,
        requirement_plan_evidence_binding=binding,
        receipt=SimpleNamespace(
            metric_publication_v2=SimpleNamespace(
                projection_version=METRIC_PROJECTION_V2_VERSION_6
            )
        ),
    )
    repository = SimpleNamespace(get_latest=lambda _session_id: latest)

    contract = SealedRunRequirementActionSource(
        repository, reviews
    ).current_source_contract(SESSION)

    assert contract.expected_source_run_id == RUN
    assert contract.requirement_plan_evidence.confirmation_id == PLAN_CONFIRMATION

    empty_contexts = InMemoryRequirementActionReviewContextStore(
        clock=lambda: NOW, monotonic_clock=lambda: 100.0
    )
    with pytest.raises(RequirementActionNotFoundError):
        SealedRunRequirementActionSource(
            repository, empty_contexts
        ).current_source_contract(SESSION)

    binding.evidence_fingerprint = "0" * 64
    with pytest.raises(RequirementActionConflictError):
        SealedRunRequirementActionSource(
            repository, reviews
        ).current_source_contract(SESSION)
