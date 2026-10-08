from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.redaction_preview import (
    REDACTION_PREVIEW_CONFIRMATION,
    AnalysisApproval,
    AnalysisDestination,
    CostEstimateState,
    InMemoryRedactionPreviewStore,
    RedactionPreviewBinding,
    RedactionPreviewConsumedError,
    RedactionPreviewExpiredError,
    RedactionPreviewMismatchError,
    RetentionClass,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ApplicabilityBasis,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.domain import Provider


NOW = datetime(2042, 4, 5, 10, 0, tzinfo=UTC)
SESSION_ID = "a" * 64
WINDOW_ID = "b" * 64
PREVIEW_ID = "c" * 64
TEXT_CANARY = "SYNTHETIC-REDACTED-PREVIEW-CANARY"


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class MutableMonotonicClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _context() -> P1TextAnalysisInput:
    profile = TextTaskProfile(
        applicability=(
            MetricApplicabilityDecision(
                metric_key="prompt.goal_cue_coverage",
                applicability=MetricApplicability.APPLICABLE,
                basis=ApplicabilityBasis.TASK_PROFILE,
            ),
        )
    )
    message = EphemeralRedactedMessage(
        message_id="d" * 64,
        sequence=0,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(TEXT_CANARY),
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-source-1",
        content_schema_version="synthetic-content-1",
        redactor_version="synthetic-redactor-1",
        text_extraction_complete=True,
        available_message_kinds=frozenset((TextMessageKind.REQUEST,)),
        analysis_window_fingerprint=WINDOW_ID,
        focus_message_id=message.message_id,
        observed_message_count=1,
        eligible_message_count=1,
        messages=(message,),
        task_profile=profile,
    )


def _binding(**changes: object) -> RedactionPreviewBinding:
    values: dict[str, object] = {
        "provider": Provider.SYNTHETIC,
        "session_id": SESSION_ID,
        "analysis_window_fingerprint": WINDOW_ID,
        "metric_keys": ("prompt.goal_cue_coverage",),
        "destination": AnalysisDestination.LOCAL,
        "exact_model": "deterministic-text-rules-v1",
        "estimator_plan_version": "coaching-v1",
        "redactor_version": "synthetic-redactor-1",
        "retention_class": RetentionClass.LOCAL_EPHEMERAL,
        "message_count": 1,
        "character_count": len(TEXT_CANARY),
        "cost_state": CostEstimateState.NOT_APPLICABLE,
    }
    values.update(changes)
    return RedactionPreviewBinding.model_validate(values)


def _approval(binding: RedactionPreviewBinding) -> AnalysisApproval:
    return AnalysisApproval(
        preview_id=PREVIEW_ID,
        confirmation=REDACTION_PREVIEW_CONFIRMATION,
        idempotency_key="synthetic-approval-1",
        expected_binding=binding,
    )


def test_preview_is_exactly_ten_minutes_and_secret_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = MutableClock()
    store = InMemoryRedactionPreviewStore(
        clock=clock,
        token_factory=lambda: PREVIEW_ID,
    )
    receipt = store.create(_context(), _binding())

    assert receipt.expires_at - receipt.created_at == timedelta(minutes=10)
    inspection = store.inspect(PREVIEW_ID)
    assert TEXT_CANARY not in repr(store)
    assert TEXT_CANARY not in repr(store._entries)
    assert TEXT_CANARY not in repr(inspection)
    assert TEXT_CANARY not in repr(inspection.messages)
    assert TEXT_CANARY not in caplog.text
    assert inspection.messages[0].text.get_secret_value() == TEXT_CANARY


def test_expired_preview_is_removed_and_cannot_be_consumed() -> None:
    clock = MutableClock()
    store = InMemoryRedactionPreviewStore(
        clock=clock,
        token_factory=lambda: PREVIEW_ID,
    )
    binding = _binding()
    store.create(_context(), binding)
    clock.now += timedelta(minutes=10)

    with pytest.raises(RedactionPreviewExpiredError):
        store.consume(_approval(binding))
    with pytest.raises(RedactionPreviewExpiredError):
        store.inspect(PREVIEW_ID)


def test_wall_clock_rollback_cannot_extend_monotonic_expiry() -> None:
    clock = MutableClock()
    monotonic_clock = MutableMonotonicClock()
    store = InMemoryRedactionPreviewStore(
        clock=clock,
        monotonic_clock=monotonic_clock,
        token_factory=lambda: PREVIEW_ID,
    )
    binding = _binding()
    receipt = store.create(_context(), binding)

    clock.now -= timedelta(days=1)
    monotonic_clock.now += timedelta(minutes=10).total_seconds()

    with pytest.raises(RedactionPreviewExpiredError) as expired:
        store.consume(_approval(binding))
    assert TEXT_CANARY not in str(expired.value)
    assert TEXT_CANARY not in repr(expired.value)
    assert receipt.created_at == NOW
    assert receipt.expires_at == NOW + timedelta(minutes=10)


def test_binding_mismatch_does_not_consume_preview() -> None:
    store = InMemoryRedactionPreviewStore(
        clock=lambda: NOW,
        token_factory=lambda: PREVIEW_ID,
    )
    binding = _binding()
    store.create(_context(), binding)
    wrong = _binding(metric_keys=("logic.open_loop_closure",))

    with pytest.raises(RedactionPreviewMismatchError) as mismatch:
        store.consume(_approval(wrong))
    assert TEXT_CANARY not in str(mismatch.value)
    assert TEXT_CANARY not in repr(mismatch.value)

    approved = store.consume(_approval(binding))
    assert approved.context.analysis_window_fingerprint == WINDOW_ID
    assert TEXT_CANARY not in repr(approved)


def test_only_one_concurrent_exact_approval_can_consume() -> None:
    store = InMemoryRedactionPreviewStore(
        clock=lambda: NOW,
        token_factory=lambda: PREVIEW_ID,
    )
    binding = _binding()
    store.create(_context(), binding)
    start = Barrier(2)

    def consume() -> str:
        start.wait(timeout=5)
        try:
            store.consume(_approval(binding))
            return "approved"
        except RedactionPreviewConsumedError:
            return "consumed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: consume(), range(2)))

    assert sorted(outcomes) == ["approved", "consumed"]
    with pytest.raises(RedactionPreviewConsumedError) as consumed:
        store.consume(_approval(binding))
    assert TEXT_CANARY not in str(consumed.value)
    assert TEXT_CANARY not in repr(consumed.value)


def test_remote_preview_requires_disclosed_remote_retention_and_cost_shape() -> None:
    with pytest.raises(ValidationError):
        _binding(
            destination=AnalysisDestination.REMOTE,
            retention_class=RetentionClass.LOCAL_EPHEMERAL,
        )

    remote = _binding(
        destination=AnalysisDestination.REMOTE,
        retention_class=RetentionClass.REMOTE_30_DAY,
        cost_state=CostEstimateState.UNKNOWN,
    )
    assert remote.estimated_cost_microunits is None


def test_context_and_binding_must_match_before_storage() -> None:
    store = InMemoryRedactionPreviewStore(
        clock=lambda: NOW,
        token_factory=lambda: PREVIEW_ID,
    )
    with pytest.raises(RedactionPreviewMismatchError):
        store.create(_context(), _binding(character_count=1))
