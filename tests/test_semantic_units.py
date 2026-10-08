from __future__ import annotations

import hashlib

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.semantic_units import (
    FeedbackReworkClass,
    SEMANTIC_UNIT_CONTRACT_VERSION,
    SemanticUnitKind,
    SemanticUnitLifecycle,
    SemanticUnitReceipt,
    SemanticUnitReconciler,
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


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic:{label}".encode()).hexdigest()


class _SyntheticIdFactory:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        payload = "\x1f".join((namespace, *values))
        return hashlib.sha256(payload.encode()).hexdigest()

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        payload = "\x1f".join((namespace, *values, secret.get_secret_value()))
        return hashlib.sha256(payload.encode()).hexdigest()


def _message(
    label: str,
    sequence: int,
    role: TextRole,
    kind: TextMessageKind,
    text: str,
    *,
    supersedes: tuple[str, ...] = (),
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=_id(label),
        sequence=sequence,
        role=role,
        kind=kind,
        language=TextLanguage.ENGLISH,
        text=SecretStr(text),
        supersedes_message_ids=supersedes,
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    *,
    label: str,
    focus: str | None = None,
    eligible_count: int | None = None,
    extraction_complete: bool = True,
) -> P1TextAnalysisInput:
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=extraction_complete,
        available_message_kinds=frozenset(message.kind for message in messages),
        analysis_window_fingerprint=_id(f"window:{label}"),
        focus_message_id=focus or messages[0].message_id,
        observed_message_count=len(messages),
        eligible_message_count=eligible_count or len(messages),
        messages=messages,
        task_profile=TextTaskProfile(applicability=()),
    )


def _reconciler() -> SemanticUnitReconciler:
    return SemanticUnitReconciler(_SyntheticIdFactory())


def test_kind_registry_covers_all_contract_units() -> None:
    assert {item.value for item in SemanticUnitKind} == {
        "request_revision",
        "requirement",
        "constraint",
        "deliverable",
        "ambiguity",
        "clarification",
        "scope_change",
        "feedback",
        "hypothesis",
        "decision",
        "open_loop",
        "action",
        "verification",
    }


def test_extractor_uses_only_documented_role_kind_pairs() -> None:
    request = _message(
        "request",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "A fictional request mentioning constraint, hypothesis, and ambiguity.",
    )
    plan = _message(
        "plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "A fictional plan that says requirement, deliverable, and open loop.",
    )
    response = _message(
        "response",
        3,
        TextRole.AGENT,
        TextMessageKind.RESPONSE,
        "A fictional clarification claim that is not typed as clarification.",
    )
    action = _message(
        "action",
        4,
        TextRole.AGENT,
        TextMessageKind.ACTION,
        "A fictional documented action.",
    )
    decision = _message(
        "decision",
        5,
        TextRole.AGENT,
        TextMessageKind.DECISION,
        "A fictional documented decision.",
    )
    verification = _message(
        "verification",
        6,
        TextRole.AGENT,
        TextMessageKind.VERIFICATION,
        "A fictional documented verification message.",
    )
    feedback = _message(
        "feedback",
        7,
        TextRole.USER,
        TextMessageKind.FEEDBACK,
        "A fictional feedback message.",
    )
    context = _context(
        (request, plan, response, action, decision, verification, feedback),
        label="typed-kinds",
        focus=feedback.message_id,
    )

    output = _reconciler().reconcile(context).reconciliation

    assert {item.kind for item in output.heads} == {
        SemanticUnitKind.REQUEST_REVISION,
        SemanticUnitKind.ACTION,
        SemanticUnitKind.DECISION,
        SemanticUnitKind.VERIFICATION,
        SemanticUnitKind.FEEDBACK,
    }
    assert all(
        item.source_digests == (item.owner_source_digest,) for item in output.heads
    )
    feedback_receipt = next(
        item for item in output.heads if item.kind is SemanticUnitKind.FEEDBACK
    )
    assert feedback_receipt.rework_class is FeedbackReworkClass.UNKNOWN


def test_explicit_supersession_revises_lifecycle_without_duplicate_owner() -> None:
    first = _message(
        "request-1",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the fictional report.",
    )
    first_context = _context((first,), label="first")
    first_result = _reconciler().reconcile(first_context).reconciliation
    first_head = first_result.heads[0]
    assert first_head.lifecycle is SemanticUnitLifecycle.OPEN

    second = _message(
        "request-2",
        2,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the revised fictional report.",
        supersedes=(first.message_id,),
    )
    complete_context = _context(
        (first, second), label="second", focus=second.message_id
    )
    result = _reconciler().reconcile(
        complete_context,
        prior_receipts=first_result.heads,
    ).reconciliation

    assert len(result.heads) == 2
    assert len(result.appended) == 2
    superseded = next(item for item in result.heads if item.unit_id == first_head.unit_id)
    current = next(item for item in result.heads if item.unit_id != first_head.unit_id)
    assert superseded.revision == 2
    assert superseded.previous_receipt_id == first_head.receipt_id
    assert superseded.lifecycle is SemanticUnitLifecycle.SUPERSEDED
    assert superseded.superseded_by_unit_id == current.unit_id
    assert superseded.closed_at_sequence == second.sequence
    assert current.lifecycle is SemanticUnitLifecycle.OPEN
    assert all(
        item.source_digests.count(item.owner_source_digest) == 1
        for item in result.heads
    )


def test_incomplete_right_edge_is_censored_not_closed_or_zero() -> None:
    request = _message(
        "bounded-request",
        4,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "A bounded fictional request.",
    )
    context = _context(
        (request,),
        label="bounded",
        eligible_count=9,
        extraction_complete=False,
    )

    result = _reconciler().reconcile(context).reconciliation

    assert result.source_complete is False
    assert result.heads[0].lifecycle is SemanticUnitLifecycle.RIGHT_CENSORED
    assert result.heads[0].closed_at_sequence is None


def test_reconciliation_is_append_idempotent() -> None:
    request = _message(
        "idempotent-request",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "An idempotent fictional request.",
    )
    context = _context((request,), label="idempotent")
    reconciler = _reconciler()

    first = reconciler.reconcile(context).reconciliation
    second = reconciler.reconcile(
        context,
        prior_receipts=first.heads,
    ).reconciliation

    assert len(first.appended) == 1
    assert second.appended == ()
    assert second.heads == first.heads
    assert second.unchanged_receipt_ids == (first.heads[0].receipt_id,)
    assert second.reconciliation_id == first.reconciliation_id


def test_changed_content_under_same_message_id_appends_a_new_unit_revision() -> None:
    before = _message(
        "stable-source-id",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "First synthetic redacted content.",
    )
    after = _message(
        "stable-source-id",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Changed synthetic redacted content.",
    )
    reconciler = _reconciler()
    initial = reconciler.reconcile(
        _context((before,), label="content-before")
    ).reconciliation

    changed = reconciler.reconcile(
        _context((after,), label="content-after"),
        prior_receipts=initial.heads,
    ).reconciliation

    assert len(changed.appended) == 1
    assert changed.heads[0].unit_id == initial.heads[0].unit_id
    assert changed.heads[0].revision == 2
    assert (
        changed.heads[0].source_version_digest
        != initial.heads[0].source_version_digest
    )
    assert changed.heads[0].unit_digest != initial.heads[0].unit_digest


def test_incremental_and_full_reconciliation_have_equal_semantic_heads() -> None:
    first = _message(
        "incremental-request-1",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "First fictional request.",
    )
    second = _message(
        "incremental-request-2",
        2,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Second fictional request.",
        supersedes=(first.message_id,),
    )
    reconciler = _reconciler()
    initial = reconciler.reconcile(
        _context((first,), label="incremental-first")
    ).reconciliation
    full_context = _context(
        (first, second), label="incremental-full", focus=second.message_id
    )

    incremental = reconciler.reconcile(
        full_context, prior_receipts=initial.heads
    ).reconciliation
    from_scratch = reconciler.reconcile(full_context).reconciliation

    incremental_semantics = {
        item.unit_id: (item.unit_digest, item.kind, item.lifecycle)
        for item in incremental.heads
    }
    full_semantics = {
        item.unit_id: (item.unit_digest, item.kind, item.lifecycle)
        for item in from_scratch.heads
    }
    assert incremental_semantics == full_semantics


def test_ephemeral_text_is_never_serialized_or_represented() -> None:
    canary = "ephemeral-only-synthetic-canary-47c0"
    request = _message(
        "private-request",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        canary,
    )
    projection = _reconciler().reconcile(
        _context((request,), label="private"),
        include_ephemeral_evidence=True,
    )

    assert projection.evidence_packets[0].text.get_secret_value() == canary
    assert canary not in repr(projection)
    assert canary not in projection.model_dump_json()
    assert canary not in projection.evidence_packets[0].model_dump_json()
    assert "text" not in projection.evidence_packets[0].model_dump()
    assert "evidence_packets" not in projection.model_dump()


@pytest.mark.parametrize(
    "bad_owner",
    (_id("not-an-owner-a"), _id("not-an-owner-b")),
)
def test_receipt_rejects_missing_exact_owner(bad_owner: str) -> None:
    request = _message(
        "owner-request",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "A fictional owner invariant request.",
    )
    receipt = _reconciler().reconcile(
        _context((request,), label="owner")
    ).reconciliation.heads[0]
    payload = receipt.model_dump()
    payload["owner_source_digest"] = bad_owner

    with pytest.raises(ValidationError, match="exactly one owner"):
        SemanticUnitReceipt.model_validate(payload)


def test_contract_version_is_persistable_content_free_metadata() -> None:
    request = _message(
        "contract-request",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "A fictional contract-version request.",
    )
    receipt = _reconciler().reconcile(
        _context((request,), label="contract")
    ).reconciliation.heads[0]

    assert receipt.contract_version == SEMANTIC_UNIT_CONTRACT_VERSION
    serialized = receipt.model_dump_json()
    assert "fictional contract-version request" not in serialized
    assert set(receipt.source_digests) == {receipt.owner_source_digest}
