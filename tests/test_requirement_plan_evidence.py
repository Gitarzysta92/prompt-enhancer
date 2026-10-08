from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import re

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES,
    REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION,
    REQUIREMENT_PLAN_DECISION_CONFIRMATION,
    REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
    REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    REQUIREMENT_PLAN_METRIC_KEY,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    ConfirmedPlanEvidence,
    ConfirmedRequirementEvidence,
    ExcludedRequirementClause,
    InMemoryRequirementPlanReviewContextStore,
    PlanCoordinate,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementPlanConflictError,
    RequirementPlanClauseAlgorithmContract,
    RequirementPlanDecisionCommand,
    RequirementPlanDecisionKind,
    RequirementPlanDefinitionsOutOfDateError,
    RequirementPlanEvidenceService,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanEvidencePreview,
    RequirementPlanExclusionReason,
    RequirementPlanInputError,
    RequirementPlanProposalPageSnapshot,
    RequirementPlanProposalStatus,
    RequirementPlanProposalView,
    RequirementPlanProducer,
    RequirementPlanProducerReceipt,
    RequirementPlanSourceContract,
    RequirementPlanStaleWindowError,
    parse_requirement_plan_evidence_file,
    requirement_plan_evidence_file_json_schema_sha256,
    requirement_plan_graph_fingerprint,
    reviewable_message_clauses,
)
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.domain import Provider


NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
SESSION = "1" * 64
RUN = "2" * 64
WINDOW = "3" * 64


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hmac.new(
            b"synthetic-requirement-plan-test-key",
            "\x1f".join((namespace, *values)).encode(),
            hashlib.sha256,
        ).hexdigest()


class _Source:
    def __init__(
        self,
        *,
        run_id: str = RUN,
        context: P1TextAnalysisInput | None = None,
        clock=lambda: NOW,  # type: ignore[no-untyped-def]
        monotonic_clock=lambda: 100.0,  # type: ignore[no-untyped-def]
    ) -> None:
        self.run_id = run_id
        self.store = InMemoryRequirementPlanReviewContextStore(
            clock=clock,
            monotonic_clock=monotonic_clock,
        )
        self.store.publish(run_id, _context() if context is None else context)

    def current_source_contract(self, session_id: str) -> RequirementPlanSourceContract:
        return RequirementPlanSourceContract(
            session_id=session_id,
            expected_source_run_id=self.run_id,
            source_window_fingerprint=WINDOW,
            projection_version=METRIC_PROJECTION_V2_VERSION_5,
            contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
            source_manifest=self.store.manifest(
                session_id=session_id,
                source_run_id=self.run_id,
                source_window_fingerprint=WINDOW,
            ),
        )


def _context() -> P1TextAnalysisInput:
    request = EphemeralRedactedMessage(
        message_id="5" * 64,
        sequence=1,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr("First requirement. Second requirement."),
    )
    plan = EphemeralRedactedMessage(
        message_id="6" * 64,
        sequence=2,
        role=TextRole.AGENT,
        kind=TextMessageKind.PLAN,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Implement the first requirement."),
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
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.PLAN}
        ),
        analysis_window_fingerprint=WINDOW,
        focus_message_id=request.message_id,
        observed_message_count=2,
        eligible_message_count=2,
        messages=(request, plan),
        task_profile=TextTaskProfile(applicability=()),
    )


def _complete_review_context() -> P1TextAnalysisInput:
    base = _context()
    request, plan = base.messages
    expanded_plan = plan.model_copy(
        update={
            "text": SecretStr(
                "Implement the first requirement. Verify the second requirement."
            )
        }
    )
    feedback = EphemeralRedactedMessage(
        message_id="7" * 64,
        sequence=3,
        role=TextRole.USER,
        kind=TextMessageKind.FEEDBACK,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Preserve the synthetic log. Report the synthetic status."),
    )
    return base.model_copy(
        update={
            "available_message_kinds": frozenset(
                {
                    TextMessageKind.REQUEST,
                    TextMessageKind.PLAN,
                    TextMessageKind.FEEDBACK,
                }
            ),
            "observed_message_count": 3,
            "eligible_message_count": 3,
            "messages": (request, expanded_plan, feedback),
        }
    )


class _Repository:
    def __init__(self) -> None:
        self.proposals: dict[str, RequirementPlanProposalView] = {}
        self.heads: dict[tuple[str, str], str] = {}
        self.ids = _Ids()

    def issue_proposal(self, proposal):  # type: ignore[no-untyped-def]
        existing = self.proposals.get(proposal.proposal_id)
        if existing is not None:
            if existing.proposal == proposal:
                return existing, False
            raise RequirementPlanConflictError("idempotency conflict")
        view = RequirementPlanProposalView(
            proposal=proposal,
            status=RequirementPlanProposalStatus.PROPOSED,
        )
        self.proposals[proposal.proposal_id] = view
        return view, True

    def decide(self, decision):  # type: ignore[no-untyped-def]
        view = self.proposals[decision.proposal_id]
        if view.decision is not None:
            if view.decision == decision:
                return view, False
            raise RequirementPlanConflictError("decision conflict")
        if decision.decision is RequirementPlanDecisionKind.CONFIRM:
            key = (
                view.proposal.session_id,
                view.proposal.source_window_fingerprint,
            )
            if self.heads.get(key) != view.proposal.expected_predecessor_confirmation_id:
                raise RequirementPlanConflictError("predecessor conflict")
            self.heads[key] = decision.decision_id
        updated = RequirementPlanProposalView(
            proposal=view.proposal,
            decision=decision,
            status=(
                RequirementPlanProposalStatus.CONFIRMED
                if decision.decision is RequirementPlanDecisionKind.CONFIRM
                else RequirementPlanProposalStatus.REJECTED
            ),
        )
        self.proposals[decision.proposal_id] = updated
        return updated, True

    def get_proposal(self, proposal_id: str):  # type: ignore[no-untyped-def]
        return self.proposals.get(proposal_id)

    def list_proposals_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementPlanProposalPageSnapshot | None = None,
    ):
        rows = tuple(
            sorted(
                (
                    value
                    for value in self.proposals.values()
                    if value.proposal.session_id == session_id
                ),
                key=lambda value: (
                    value.proposal.created_at,
                    value.proposal.proposal_id,
                ),
            )
        )
        resolved = snapshot
        if resolved is None:
            resolved = RequirementPlanProposalPageSnapshot(
                snapshot_id="0" * 64,
                total=len(rows),
                decision_count=sum(
                    item.decision is not None for item in rows
                ),
                high_water_created_at=(
                    None if not rows else rows[-1].proposal.created_at
                ),
                high_water_proposal_id=(
                    None if not rows else rows[-1].proposal.proposal_id
                ),
            )
        bounded = tuple(
            item
            for item in rows
            if (
                resolved.high_water_created_at is None
                or (
                    item.proposal.created_at,
                    item.proposal.proposal_id,
                )
                <= (
                    resolved.high_water_created_at,
                    resolved.high_water_proposal_id,
                )
            )
        )
        return bounded[offset : offset + limit], resolved

    def snapshot(self, session_id: str, source_window_fingerprint: str):
        confirmation_id = self.heads.get((session_id, source_window_fingerprint))
        if confirmation_id is None:
            return RequirementPlanEvidenceSnapshot(
                session_id=session_id,
                source_window_fingerprint=source_window_fingerprint,
            )
        view = next(
            value
            for value in self.proposals.values()
            if value.decision is not None
            and value.decision.decision_id == confirmation_id
        )
        plan_ids = tuple(
            self.ids.fingerprint(
                "requirement-plan-confirmed-plan-v1",
                (confirmation_id, str(index)),
            )
            for index, _item in enumerate(view.proposal.plan_items)
        )
        plans = tuple(
            ConfirmedPlanEvidence(plan_id=plan_ids[index], coordinate=item)
            for index, item in enumerate(view.proposal.plan_items)
        )
        requirements = tuple(
            ConfirmedRequirementEvidence(
                requirement_id=self.ids.fingerprint(
                    "requirement-plan-confirmed-requirement-v1",
                    (confirmation_id, str(index)),
                ),
                coordinate=item.coordinate,
                disposition=item.disposition,
                linked_plan_ids=tuple(
                    sorted(plan_ids[plan_index] for plan_index in item.plan_indexes)
                ),
            )
            for index, item in enumerate(view.proposal.requirements)
        )
        return RequirementPlanEvidenceSnapshot(
            session_id=session_id,
            source_window_fingerprint=source_window_fingerprint,
            confirmation_id=confirmation_id,
            proposal_id=view.proposal.proposal_id,
            producer_receipt=view.proposal.producer_receipt,
            requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
            excluded_user_clauses=view.proposal.excluded_user_clauses,
            plan_items=tuple(sorted(plans, key=lambda item: item.plan_id)),
            complete_user_clause_classification=True,
            review_rubric_version=view.proposal.review_rubric_version,
        )


def _document(*, predecessor: str | None = None) -> dict[str, object]:
    return {
        "schema_version": REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
        "session_id": SESSION,
        "expected_source_run_id": RUN,
        "source_window_fingerprint": WINDOW,
        "expected_predecessor_confirmation_id": predecessor,
        "registry_version": METRIC_CONTRACT_REGISTRY_VERSION_V2,
        "contract_set_fingerprint": metric_contract_v2_set_fingerprint(),
        "metric_key": REQUIREMENT_PLAN_METRIC_KEY,
        "metric_contract_fingerprint": metric_contract_v2(
            REQUIREMENT_PLAN_METRIC_KEY
        ).fingerprint,
        "source_projection_version": METRIC_PROJECTION_V2_VERSION_5,
        "clause_algorithm": "message-clause-coordinates-en-pl-v1",
        "review_rubric_version": REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        "nonce": "4" * 64,
        "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "producer": {
            "kind": "local_coding_agent",
            "producer_id": "example-agent",
            "producer_version": "1",
            "model_id": "example-local-model",
            "authority": "untrusted_provenance_claim",
        },
        "contains_prose": False,
        "contains_scores": False,
        "contains_authoritative_model_judgment_claims": False,
        "contains_untrusted_structured_proposals": True,
        "contains_objective_receipt_claims": False,
        "complete_user_clause_classification": True,
        "requirements": [
            {
                "coordinate": {"message_sequence": 1, "clause_index": 0},
                "disposition": "linked",
                "plan_indexes": [0],
            },
            {
                "coordinate": {"message_sequence": 1, "clause_index": 1},
                "disposition": "pending",
                "plan_indexes": [],
            },
        ],
        "excluded_user_clauses": [],
        "plan_items": [{"message_sequence": 2, "clause_index": 0}],
    }


def _payload(*, predecessor: str | None = None) -> bytes:
    return json.dumps(
        _document(predecessor=predecessor),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _complete_review_document() -> dict[str, object]:
    document = _document()
    document["requirements"] = [
        *document["requirements"],  # type: ignore[misc]
        {
            "coordinate": {"message_sequence": 3, "clause_index": 0},
            "disposition": "not_linked",
            "plan_indexes": [],
        },
    ]
    document["excluded_user_clauses"] = [
        {
            "coordinate": {"message_sequence": 3, "clause_index": 1},
            "reason": "not_requirement",
        }
    ]
    return document


def _canonical_payload(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _service(
    repository: _Repository,
    source: _Source | None = None,
    *,
    clock=lambda: NOW,  # type: ignore[no-untyped-def]
) -> RequirementPlanEvidenceService:
    selected = _Source() if source is None else source
    return RequirementPlanEvidenceService(
        repository,
        selected,
        _Ids(),
        review_contexts=selected.store,
        clock=clock,
    )


def _decision_command(
    service: RequirementPlanEvidenceService,
    proposal: RequirementPlanProposalView,
    decision: RequirementPlanDecisionKind,
) -> RequirementPlanDecisionCommand:
    if decision is RequirementPlanDecisionKind.REJECT:
        return RequirementPlanDecisionCommand(
            expected_source_run_id=proposal.proposal.source_run_id,
            decision=decision,
            confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
        )
    review = service.review_proposal(
        session_id=proposal.proposal.session_id,
        proposal_id=proposal.proposal.proposal_id,
        expected_source_run_id=proposal.proposal.source_run_id,
    )
    return RequirementPlanDecisionCommand(
        expected_source_run_id=proposal.proposal.source_run_id,
        decision=decision,
        confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
        review_receipt_id=review.review_receipt_id,
        manifest_fingerprint=review.manifest_fingerprint,
        reviewed_graph_fingerprint=review.reviewed_graph_fingerprint,
        reviewed_candidate_set_fingerprint=(
            review.reviewed_candidate_set_fingerprint
        ),
        complete_review_acknowledged=True,
    )


def _import_proposal(
    service: RequirementPlanEvidenceService,
    *,
    suffix: str,
) -> RequirementPlanProposalView:
    payload = _payload()
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    return service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key=f"synthetic-review-import-{suffix}",
        now=NOW,
    )[0]


def test_clause_coordinates_are_stable_without_classification() -> None:
    assert reviewable_message_clauses(
        "  First requirement.\nSecond item;  final clause  "
    ) == ("First requirement.", "Second item;", "final clause")


def test_published_clause_recipe_reproduces_nul_and_unicode_operation_order() -> None:
    spec = RequirementPlanClauseAlgorithmContract()
    assert spec.operation_order == (
        "replace_nul",
        "split",
        "normalize_whitespace",
        "trim",
        "omit_empty",
        "overflow_check",
    )
    text = "First.\x00 Second.\nTrzecie\u00a0 zadanie;"
    working: str | list[str] = text
    for operation in spec.operation_order:
        if operation == "replace_nul":
            assert isinstance(working, str)
            working = working.replace("\x00", " ")
        elif operation == "split":
            assert isinstance(working, str)
            working = re.split(spec.split_regex, working)
        elif operation == "normalize_whitespace":
            assert isinstance(working, list)
            working = [re.sub(spec.whitespace_regex, " ", item) for item in working]
        elif operation == "trim":
            assert isinstance(working, list)
            working = [item.strip() for item in working]
        elif operation == "omit_empty":
            assert isinstance(working, list)
            working = [item for item in working if item]
        elif operation == "overflow_check":
            assert isinstance(working, list)
            if len(working) > spec.max_clauses_per_message:
                raise ValueError("clause overflow")
    assert isinstance(working, list)
    assert tuple(working) == reviewable_message_clauses(text)


def test_clause_overflow_fails_closed_and_contract_never_hides_clause_129() -> None:
    context = _context()
    request, plan = context.messages
    overflowing_text = " ".join(
        f"Synthetic clause {index}." for index in range(129)
    )
    overflowing = request.model_copy(update={"text": SecretStr(overflowing_text)})
    source = _Source(context=context.model_copy(update={"messages": (overflowing, plan)}))

    with pytest.raises(ValueError, match="clause bound"):
        reviewable_message_clauses(overflowing_text)
    with pytest.raises(RequirementPlanInputError, match="clause bound"):
        _service(_Repository(), source).contract(SESSION)


@pytest.mark.parametrize(
    "omitted_coordinate",
    ((1, 1), (3, 0)),
    ids=("request-clause", "feedback-clause"),
)
def test_preview_and_import_reject_an_omitted_user_clause(
    omitted_coordinate: tuple[int, int],
) -> None:
    source = _Source(context=_complete_review_context())
    repository = _Repository()
    service = _service(repository, source)
    document = _complete_review_document()
    document["requirements"] = [
        item
        for item in document["requirements"]  # type: ignore[union-attr]
        if (
            item["coordinate"]["message_sequence"],  # type: ignore[index]
            item["coordinate"]["clause_index"],  # type: ignore[index]
        )
        != omitted_coordinate
    ]
    document["excluded_user_clauses"] = [
        item
        for item in document["excluded_user_clauses"]  # type: ignore[union-attr]
        if (
            item["coordinate"]["message_sequence"],  # type: ignore[index]
            item["coordinate"]["clause_index"],  # type: ignore[index]
        )
        != omitted_coordinate
    ]
    payload = _canonical_payload(document)

    with pytest.raises(
        RequirementPlanInputError,
        match="coordinates do not match the sealed source",
    ):
        service.preview(session_id=SESSION, payload=payload, now=NOW)
    with pytest.raises(
        RequirementPlanInputError,
        match="coordinates do not match the sealed source",
    ):
        service.import_file(
            session_id=SESSION,
            payload=payload,
            expected_payload_sha256=hashlib.sha256(payload).hexdigest(),
            confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
            idempotency_key=(
                f"synthetic-omitted-{omitted_coordinate[0]}-"
                f"{omitted_coordinate[1]}"
            ),
            now=NOW,
        )
    assert repository.proposals == {}


def test_full_review_keeps_an_omitted_agent_plan_clause_visible() -> None:
    source = _Source(context=_complete_review_context())
    repository = _Repository()
    service = _service(repository, source)
    payload = _canonical_payload(_complete_review_document())
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    proposal, _applied = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-complete-review-import",
        now=NOW,
    )

    review = service.review_proposal(
        session_id=SESSION,
        proposal_id=proposal.proposal.proposal_id,
        expected_source_run_id=proposal.proposal.source_run_id,
    )

    requirement_candidates = tuple(
        item for item in review.candidate_clauses
        if item.candidate_kind == "user_clause"
    )
    assert {
        (item.message_sequence, item.clause_index)
        for item in requirement_candidates
    } == {(1, 0), (1, 1), (3, 0), (3, 1)}
    assert all(item.included_in_proposal for item in requirement_candidates)
    assert tuple(item.classification for item in requirement_candidates) == (
        "active_requirement",
        "active_requirement",
        "active_requirement",
        "excluded_from_active_requirement_denominator",
    )
    assert requirement_candidates[-1].exclusion_reason is (
        RequirementPlanExclusionReason.NOT_REQUIREMENT
    )
    omitted_plan = next(
        item
        for item in review.candidate_clauses
        if (item.message_sequence, item.clause_index) == (2, 1)
    )
    assert omitted_plan.candidate_kind == "plan"
    assert omitted_plan.included_in_proposal is False
    assert omitted_plan.text == "Verify the second requirement."


def test_withdrawn_requirement_is_not_mislabeled_as_never_a_requirement() -> None:
    base = _context()
    request, plan = base.messages
    request = request.model_copy(update={"text": SecretStr("Add the fictional export.")})
    feedback = EphemeralRedactedMessage(
        message_id="8" * 64,
        sequence=3,
        role=TextRole.USER,
        kind=TextMessageKind.FEEDBACK,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Cancel the fictional export."),
    )
    context = base.model_copy(
        update={
            "messages": (request, plan, feedback),
            "observed_message_count": 3,
            "eligible_message_count": 3,
            "available_message_kinds": frozenset(
                {
                    TextMessageKind.REQUEST,
                    TextMessageKind.PLAN,
                    TextMessageKind.FEEDBACK,
                }
            ),
        }
    )
    source = _Source(context=context)
    service = _service(_Repository(), source)
    document = _document()
    document["requirements"] = []
    document["excluded_user_clauses"] = [
        {
            "coordinate": {"message_sequence": 1, "clause_index": 0},
            "reason": "withdrawn",
            "basis_coordinate": {"message_sequence": 3, "clause_index": 0},
        },
        {
            "coordinate": {"message_sequence": 3, "clause_index": 0},
            "reason": "not_requirement",
        },
    ]
    payload = _canonical_payload(document)
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    proposal, _ = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-withdrawn-classification",
        now=NOW,
    )
    review = service.review_proposal(
        session_id=SESSION,
        proposal_id=proposal.proposal.proposal_id,
        expected_source_run_id=proposal.proposal.source_run_id,
    )
    excluded = tuple(
        item
        for item in review.candidate_clauses
        if item.candidate_kind == "user_clause"
    )
    assert tuple(item.exclusion_reason for item in excluded) == (
        RequirementPlanExclusionReason.WITHDRAWN,
        RequirementPlanExclusionReason.NOT_REQUIREMENT,
    )
    assert excluded[0].basis_coordinate == RequirementCoordinate(
        message_sequence=3,
        clause_index=0,
    )
    assert excluded[1].basis_coordinate is None
    assert all(
        item.classification == "excluded_from_active_requirement_denominator"
        for item in excluded
    )


def test_contract_exposes_the_exact_file_shape_and_all_parser_budgets() -> None:
    contract = _service(_Repository()).contract(SESSION)

    assert contract.max_file_bytes == 64 * 1024
    assert contract.max_json_depth == 8
    assert contract.max_json_items == 6_000
    assert contract.max_clauses_per_message == 128
    assert (
        contract.clause_algorithm_spec.overflow_policy
        == "fail_closed_above_128_normalized_clauses"
    )
    assert contract.canonicalization == "json-sort-keys-compact-ensure-ascii-v1"
    assert contract.review_rubric_version == REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    assert contract.review_rubric.version == REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    assert contract.review_rubric.uncertain_policy == (
        "reject_or_leave_proposal_unconfirmed"
    )
    assert contract.raw_producer_claim_persisted is False
    assert (
        contract.durable_producer_claim_shape
        == "installation_keyed_opaque_commitment_only"
    )
    assert contract.review_rubric.not_linked_rule.endswith(
        "person_confirms_the_planning_horizon_closed"
    )
    assert contract.allowed_exclusion_reasons == tuple(
        item.value for item in RequirementPlanExclusionReason
    )
    assert contract.file_json_schema_sha256 == (
        requirement_plan_evidence_file_json_schema_sha256()
    )
    required = set(contract.file_json_schema["required"])
    assert {
        "nonce",
        "expires_at",
        "producer",
        "review_rubric_version",
        "contains_prose",
        "contains_scores",
        "contains_authoritative_model_judgment_claims",
        "contains_untrusted_structured_proposals",
        "contains_objective_receipt_claims",
        "complete_user_clause_classification",
        "requirements",
        "excluded_user_clauses",
        "plan_items",
    } <= required
    definitions = contract.file_json_schema["$defs"]
    assert {
        "RequirementEvidenceEntry",
        "RequirementCoordinate",
        "ExcludedRequirementClause",
        "PlanCoordinate",
        "RequirementPlanProducer",
    } <= set(definitions)
    assert contract.file_constraint_contract_version == (
        REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION
    )
    assert contract.file_constraint_codes == REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES
    assert contract.file_json_schema["x-prompt-enhancer-constraint-contract"] == (
        REQUIREMENT_PLAN_FILE_CONSTRAINT_CONTRACT_VERSION
    )
    assert tuple(
        item["code"]
        for item in contract.file_json_schema["x-prompt-enhancer-constraints"]
    ) == REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES
    for key in (
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
        "metric_contract_fingerprint",
        "nonce",
    ):
        assert contract.file_json_schema["properties"][key]["pattern"] == (
            "^[a-f0-9]{64}$"
        )
    producer_schema = definitions["RequirementPlanProducer"]["properties"]
    assert all(
        producer_schema[key]["pattern"]
        == "^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$"
        for key in ("producer_id", "producer_version", "model_id")
    )
    indexes_schema = definitions["RequirementEvidenceEntry"]["properties"][
        "plan_indexes"
    ]
    assert indexes_schema["uniqueItems"] is True
    assert indexes_schema["items"]["minimum"] == 0
    assert contract.file_json_schema["properties"]["source_projection_version"][
        "enum"
    ] == [
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    ]

    # An external consumer can fill the contract-owned identifiers and build
    # both the empty authoritative enumeration and a linked bounded example.
    for requirements, plans in (
        ([], []),
        (
            [
                {
                    "coordinate": {
                        "message_sequence": 1_000_000_000,
                        "clause_index": 127,
                    },
                    "disposition": "linked",
                    "plan_indexes": [0],
                }
            ],
            [{"message_sequence": 1_000_000_000, "clause_index": 127}],
        ),
    ):
        candidate = _document()
        candidate.update(
            {
                "session_id": contract.session_id,
                "expected_source_run_id": contract.expected_source_run_id,
                "source_window_fingerprint": contract.source_window_fingerprint,
                "expected_predecessor_confirmation_id": (
                    contract.expected_predecessor_confirmation_id
                ),
                "registry_version": contract.registry_version,
                "contract_set_fingerprint": contract.contract_set_fingerprint,
                "metric_key": contract.metric_key,
                "metric_contract_fingerprint": contract.metric_contract_fingerprint,
                "source_projection_version": contract.source_projection_version,
                "clause_algorithm": contract.clause_algorithm,
                "requirements": requirements,
                "plan_items": plans,
            }
        )
        payload = json.dumps(
            candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        parsed, _digest = parse_requirement_plan_evidence_file(payload, now=NOW)
        assert len(parsed.requirements) == len(requirements)


def test_preview_counts_are_relationally_bound() -> None:
    producer = RequirementPlanProducer(
        kind="local_coding_agent",
        producer_id="example-agent",
        producer_version="1",
        model_id="example-local-model",
        authority="untrusted_provenance_claim",
    )
    with pytest.raises(ValueError, match="reviewed user-clause counts"):
        RequirementPlanEvidencePreview(
            payload_sha256="1" * 64,
            session_id=SESSION,
            expected_source_run_id=RUN,
            source_window_fingerprint=WINDOW,
            reviewed_user_clause_count=0,
            active_requirement_count=1,
            excluded_user_clause_count=1,
            plan_item_count=1,
            linked_active_requirement_count=1,
            not_linked_active_requirement_count=0,
            pending_active_requirement_count=0,
            link_count=1,
            expires_at=NOW + timedelta(minutes=10),
            producer=producer,
        )


def test_active_and_excluded_classifications_are_disjoint_and_committed() -> None:
    source = _Source(context=_complete_review_context())
    service = _service(_Repository(), source)
    document = _complete_review_document()
    payload = _canonical_payload(document)
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    original, _ = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-classification-original",
        now=NOW,
    )

    overlap = _complete_review_document()
    overlap["excluded_user_clauses"] = [
        {
            "coordinate": {"message_sequence": 1, "clause_index": 0},
            "reason": "duplicate",
        },
        *overlap["excluded_user_clauses"],  # type: ignore[misc]
    ]
    with pytest.raises(RequirementPlanInputError):
        parse_requirement_plan_evidence_file(
            _canonical_payload(overlap), now=NOW
        )

    missing_withdrawal_basis = _complete_review_document()
    missing_withdrawal_basis["excluded_user_clauses"] = [
        {
            "coordinate": {"message_sequence": 3, "clause_index": 1},
            "reason": "withdrawn",
        }
    ]
    with pytest.raises(RequirementPlanInputError):
        parse_requirement_plan_evidence_file(
            _canonical_payload(missing_withdrawal_basis), now=NOW
        )

    forged_duplicate_basis = _complete_review_document()
    forged_duplicate_basis["excluded_user_clauses"] = [
        {
            "coordinate": {"message_sequence": 3, "clause_index": 1},
            "reason": "duplicate",
            "basis_coordinate": {
                "message_sequence": 99,
                "clause_index": 0,
            },
        }
    ]
    forged_payload = _canonical_payload(forged_duplicate_basis)
    with pytest.raises(RequirementPlanInputError, match="sealed source"):
        service.preview(session_id=SESSION, payload=forged_payload, now=NOW)

    requirements = tuple(
        item
        for item in original.proposal.requirements
        if (item.coordinate.message_sequence, item.coordinate.clause_index)
        != (3, 0)
    )
    reclassified = original.proposal.model_copy(
        update={
            "requirements": requirements,
            "excluded_user_clauses": tuple(
                sorted(
                    (
                        *original.proposal.excluded_user_clauses,
                        ExcludedRequirementClause(
                            coordinate=RequirementCoordinate(
                                message_sequence=3, clause_index=0
                            ),
                            reason=RequirementPlanExclusionReason.OUT_OF_SCOPE,
                        ),
                    ),
                    key=lambda item: (
                        item.coordinate.message_sequence,
                        item.coordinate.clause_index,
                    ),
                )
            ),
        }
    )
    assert requirement_plan_graph_fingerprint(original.proposal) != (
        requirement_plan_graph_fingerprint(reclassified)
    )
    changed_reason = original.proposal.model_copy(
        update={
            "excluded_user_clauses": tuple(
                item.model_copy(
                    update={
                        "reason": (
                            RequirementPlanExclusionReason
                            .ALREADY_SATISFIED_OR_CLOSED
                        )
                    }
                )
                if item.coordinate.message_sequence == 3
                else item
                for item in original.proposal.excluded_user_clauses
            )
        }
    )
    assert requirement_plan_graph_fingerprint(original.proposal) != (
        requirement_plan_graph_fingerprint(changed_reason)
    )
    changed_producer = original.proposal.model_copy(
        update={
            "producer_receipt": original.proposal.producer_receipt.model_copy(
                update={"claim_fingerprint": "f" * 64}
            )
        }
    )
    assert requirement_plan_graph_fingerprint(original.proposal) != (
        requirement_plan_graph_fingerprint(changed_producer)
    )


def test_parser_requires_canonical_content_free_exact_bundle() -> None:
    parsed, digest = parse_requirement_plan_evidence_file(_payload(), now=NOW)
    assert parsed.requirements[0].disposition is RequirementDisposition.LINKED
    assert digest == hashlib.sha256(_payload()).hexdigest()

    with pytest.raises(RequirementPlanInputError):
        parse_requirement_plan_evidence_file(
            json.dumps(_document(), indent=2).encode(), now=NOW
        )
    duplicated = _payload().replace(
        b'"contains_prose":false,',
        b'"contains_prose":false,"contains_prose":false,',
    )
    with pytest.raises(RequirementPlanInputError):
        parse_requirement_plan_evidence_file(duplicated, now=NOW)
    with pytest.raises(RequirementPlanInputError):
        parse_requirement_plan_evidence_file(
            _payload().replace(
                b'"contains_prose":false', b'"contains_prose":true'
            ),
            now=NOW,
        )
    with pytest.raises(RequirementPlanDefinitionsOutOfDateError):
        parse_requirement_plan_evidence_file(
            _payload().replace(
                METRIC_PROJECTION_V2_VERSION_5.encode(),
                b"metric-contract-v2-projection-99",
            ),
            now=NOW,
        )


def test_preview_and_import_are_inert_until_native_decision() -> None:
    repository = _Repository()
    service = _service(repository)
    payload = _payload()
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    assert (
        preview.reviewed_user_clause_count,
        preview.active_requirement_count,
        preview.linked_active_requirement_count,
        preview.pending_active_requirement_count,
        preview.link_count,
    ) == (2, 2, 1, 1, 1)
    proposal, applied = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-import-0001",
        now=NOW,
    )
    assert applied is True
    assert proposal.status is RequirementPlanProposalStatus.PROPOSED
    expected_producer_receipt = RequirementPlanProducerReceipt(
        claim_fingerprint=_Ids().fingerprint(
            "requirement-plan-producer-claim-v1",
            (
                preview.producer.kind,
                preview.producer.producer_id,
                preview.producer.producer_version,
                preview.producer.model_id,
                preview.producer.authority,
            ),
        )
    )
    assert proposal.proposal.producer_receipt == expected_producer_receipt
    persisted_proposal = proposal.proposal.model_dump_json()
    assert preview.producer.producer_id not in persisted_proposal
    assert preview.producer.model_id not in persisted_proposal
    assert "producer_version" not in persisted_proposal
    assert service.snapshot_for_window(SESSION, WINDOW).confirmation_id is None

    confirmed, applied = service.decide(
        session_id=SESSION,
        proposal_id=proposal.proposal.proposal_id,
        command=_decision_command(
            service, proposal, RequirementPlanDecisionKind.CONFIRM
        ),
        idempotency_key="synthetic-decision-0001",
    )
    assert applied is True
    assert confirmed.status is RequirementPlanProposalStatus.CONFIRMED
    snapshot = service.snapshot_for_window(SESSION, WINDOW)
    assert snapshot.complete_user_clause_classification is True
    assert snapshot.producer_receipt == expected_producer_receipt
    assert {item.disposition for item in snapshot.requirements} == {
        RequirementDisposition.PENDING,
        RequirementDisposition.LINKED,
    }


def test_content_like_producer_claim_is_replaced_by_a_keyed_receipt() -> None:
    repository = _Repository()
    service = _service(repository)
    document = _document()
    document["producer"] = {
        "kind": "local_coding_agent",
        "producer_id": "SyntheticPromptContentsCanPersist",
        "producer_version": "2026.8.21",
        "model_id": "reserved-example/private-note",
        "authority": "untrusted_provenance_claim",
    }
    payload = _canonical_payload(document)
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)

    proposal, applied = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-producer-smuggling-attack",
        now=NOW,
    )

    assert applied is True
    durable = proposal.proposal.model_dump_json()
    assert "SyntheticPromptContentsCanPersist" not in durable
    assert "reserved-example/private-note" not in durable
    assert "2026.8.21" not in durable
    assert proposal.proposal.producer_receipt.raw_claim_persisted is False
    assert proposal.proposal.producer_receipt.claim_fingerprint == (
        _Ids().fingerprint(
            "requirement-plan-producer-claim-v1",
            (
                preview.producer.kind,
                preview.producer.producer_id,
                preview.producer.producer_version,
                preview.producer.model_id,
                preview.producer.authority,
            ),
        )
    )


def test_expired_review_receipt_cannot_confirm() -> None:
    wall_clock = [NOW]
    monotonic_clock = [100.0]
    source = _Source(
        clock=lambda: wall_clock[0],
        monotonic_clock=lambda: monotonic_clock[0],
    )
    repository = _Repository()
    service = _service(repository, source, clock=lambda: wall_clock[0])
    proposal = _import_proposal(service, suffix="expired")
    command = _decision_command(
        service,
        proposal,
        RequirementPlanDecisionKind.CONFIRM,
    )

    wall_clock[0] += timedelta(minutes=11)
    monotonic_clock[0] += 11 * 60
    with pytest.raises(
        RequirementPlanConflictError,
        match="review receipt is unavailable",
    ):
        service.decide(
            session_id=SESSION,
            proposal_id=proposal.proposal.proposal_id,
            command=command,
            idempotency_key="synthetic-review-decision-expired",
        )
    assert repository.get_proposal(proposal.proposal.proposal_id) == proposal


def test_exact_confirm_replay_does_not_reconsume_review_receipt() -> None:
    repository = _Repository()
    service = _service(repository)
    proposal = _import_proposal(service, suffix="replay")
    command = _decision_command(
        service,
        proposal,
        RequirementPlanDecisionKind.CONFIRM,
    )

    first, applied = service.decide(
        session_id=SESSION,
        proposal_id=proposal.proposal.proposal_id,
        command=command,
        idempotency_key="synthetic-review-decision-replay",
    )
    replayed, replay_applied = service.decide(
        session_id=SESSION,
        proposal_id=proposal.proposal.proposal_id,
        command=command,
        idempotency_key="synthetic-review-decision-replay",
    )

    assert applied is True
    assert replay_applied is False
    assert replayed == first


def test_review_receipt_rejects_ephemeral_context_replacement() -> None:
    source = _Source()
    repository = _Repository()
    service = _service(repository, source)
    proposal = _import_proposal(service, suffix="context-replacement")
    command = _decision_command(
        service,
        proposal,
        RequirementPlanDecisionKind.CONFIRM,
    )
    changed = _context()
    changed = changed.model_copy(
        update={
            "messages": (
                changed.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            "Changed first requirement. Changed second requirement."
                        )
                    }
                ),
                changed.messages[1],
            )
        }
    )
    source.store.publish(RUN, changed)

    with pytest.raises(
        RequirementPlanConflictError,
        match="review receipt binding changed",
    ):
        service.decide(
            session_id=SESSION,
            proposal_id=proposal.proposal.proposal_id,
            command=command,
            idempotency_key="synthetic-review-decision-context-replacement",
        )
    assert repository.get_proposal(proposal.proposal.proposal_id) == proposal


def test_review_receipt_rejects_tampered_proposal_graph() -> None:
    repository = _Repository()
    service = _service(repository)
    proposal = _import_proposal(service, suffix="graph-tamper")
    command = _decision_command(
        service,
        proposal,
        RequirementPlanDecisionKind.CONFIRM,
    )
    requirements = list(proposal.proposal.requirements)
    requirements[1] = requirements[1].model_copy(
        update={"disposition": RequirementDisposition.NOT_LINKED}
    )
    tampered_record = proposal.proposal.model_copy(
        update={"requirements": tuple(requirements)}
    )
    repository.proposals[proposal.proposal.proposal_id] = (
        RequirementPlanProposalView(
            proposal=tampered_record,
            status=RequirementPlanProposalStatus.PROPOSED,
        )
    )

    with pytest.raises(
        RequirementPlanConflictError,
        match="review receipt binding changed",
    ):
        service.decide(
            session_id=SESSION,
            proposal_id=proposal.proposal.proposal_id,
            command=command,
            idempotency_key="synthetic-review-decision-graph-tamper",
        )
    assert repository.heads == {}


def test_review_receipt_rejects_forged_candidate_digest() -> None:
    repository = _Repository()
    service = _service(repository)
    proposal = _import_proposal(service, suffix="candidate-digest")
    command = _decision_command(
        service,
        proposal,
        RequirementPlanDecisionKind.CONFIRM,
    ).model_copy(
        update={"reviewed_candidate_set_fingerprint": "f" * 64}
    )

    with pytest.raises(
        RequirementPlanConflictError,
        match="review receipt binding changed",
    ):
        service.decide(
            session_id=SESSION,
            proposal_id=proposal.proposal.proposal_id,
            command=command,
            idempotency_key="synthetic-review-decision-candidate-digest",
        )
    assert repository.get_proposal(proposal.proposal.proposal_id) == proposal


def test_new_decision_rejects_same_window_after_exact_source_run_rolls() -> None:
    repository = _Repository()
    source = _Source()
    service = _service(repository, source)
    payload = _payload()
    preview = service.preview(session_id=SESSION, payload=payload, now=NOW)
    proposal, _ = service.import_file(
        session_id=SESSION,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-import-run-roll",
        now=NOW,
    )

    source.run_id = "9" * 64
    source.store.publish(source.run_id, _context())
    with pytest.raises(RequirementPlanStaleWindowError):
        service.decide(
            session_id=SESSION,
            proposal_id=proposal.proposal.proposal_id,
            command=RequirementPlanDecisionCommand(
                expected_source_run_id=RUN,
                decision=RequirementPlanDecisionKind.CONFIRM,
                confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
                review_receipt_id="7" * 64,
                manifest_fingerprint="8" * 64,
                reviewed_graph_fingerprint="9" * 64,
                reviewed_candidate_set_fingerprint="a" * 64,
                complete_review_acknowledged=True,
            ),
            idempotency_key="synthetic-decision-run-roll",
        )
    assert service.snapshot_for_window(SESSION, WINDOW).confirmation_id is None


def test_correction_requires_exact_confirmed_predecessor() -> None:
    repository = _Repository()
    service = _service(repository)
    first_payload = _payload()
    first_preview = service.preview(session_id=SESSION, payload=first_payload, now=NOW)
    first, _ = service.import_file(
        session_id=SESSION,
        payload=first_payload,
        expected_payload_sha256=first_preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-import-0002",
        now=NOW,
    )
    first, _ = service.decide(
        session_id=SESSION,
        proposal_id=first.proposal.proposal_id,
        command=_decision_command(
            service, first, RequirementPlanDecisionKind.CONFIRM
        ),
        idempotency_key="synthetic-decision-0002",
    )
    assert first.decision is not None

    with pytest.raises(RequirementPlanConflictError):
        service.preview(session_id=SESSION, payload=_payload(), now=NOW)
    corrected = _payload(predecessor=first.decision.decision_id)
    assert service.preview(session_id=SESSION, payload=corrected, now=NOW)


def test_empty_enumeration_is_rejected_when_user_clauses_exist() -> None:
    document = _document()
    document["requirements"] = []
    document["plan_items"] = []
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    repository = _Repository()
    service = _service(repository)
    with pytest.raises(
        RequirementPlanInputError,
        match="coordinates do not match the sealed source",
    ):
        service.preview(session_id=SESSION, payload=payload, now=NOW)
    with pytest.raises(
        RequirementPlanInputError,
        match="coordinates do not match the sealed source",
    ):
        service.import_file(
            session_id=SESSION,
            payload=payload,
            expected_payload_sha256=hashlib.sha256(payload).hexdigest(),
            confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
            idempotency_key="synthetic-empty-0001",
            now=NOW,
        )
    assert repository.proposals == {}
