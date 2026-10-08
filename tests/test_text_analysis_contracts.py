from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    DETERMINISTIC_TEXT_CALCULATORS,
    TEXT_METRIC_DEFINITIONS,
    TextMetricRegistry,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ApplicabilityBasis,
    ConstraintKind,
    DeliverableSlot,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TextAnalysisScope,
    TextAnalysisScopeKind,
    TextAnalysisScopeReason,
    TextAnalysisScopeState,
    TextLanguage,
    TextMessageKind,
    TextMetricProvenance,
    TextRole,
    TextTaskProfile,
    MAX_REDACTED_MESSAGE_CHARACTERS,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.domain import DataTier, Provider


def _message(
    identifier: str,
    sequence: int,
    text: str,
    *,
    role: TextRole = TextRole.USER,
    kind: TextMessageKind = TextMessageKind.REQUEST,
    language: TextLanguage = TextLanguage.ENGLISH,
    supersedes: tuple[str, ...] = (),
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=identifier * 64,
        sequence=sequence,
        role=role,
        kind=kind,
        language=language,
        text=SecretStr(text),
        supersedes_message_ids=supersedes,
    )


def _profile(
    *decisions: tuple[str, MetricApplicability],
) -> TextTaskProfile:
    return TextTaskProfile(
        applicability=tuple(
            MetricApplicabilityDecision(
                metric_key=key,
                applicability=applicability,
                basis=ApplicabilityBasis.USER_SELECTED,
            )
            for key, applicability in decisions
        ),
        expected_constraint_kinds=(ConstraintKind.PRIVACY,),
        expected_deliverable_slots=(
            DeliverableSlot.ARTIFACT,
            DeliverableSlot.FORMAT,
        ),
        expected_outcome_count=1,
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    profile: TextTaskProfile,
    *,
    eligible_count: int | None = None,
) -> P1TextAnalysisInput:
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id="a" * 64,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-schema-1",
        content_schema_version="redacted-message-1",
        redactor_version="synthetic-redactor-1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(TextMessageKind),
        analysis_window_fingerprint="b" * 64,
        focus_message_id=messages[0].message_id,
        observed_message_count=len(messages),
        eligible_message_count=(
            len(messages) if eligible_count is None else eligible_count
        ),
        messages=messages,
        task_profile=profile,
    )


def _grant(context: P1TextAnalysisInput) -> P1LocalAnalysisGrant:
    return P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )


def test_ephemeral_text_is_masked_in_repr_dump_and_validation_errors() -> None:
    canary = "PRIVATE-CANARY-DO-NOT-PERSIST-12345"
    message = _message("c", 0, canary)
    profile = _profile(
        ("prompt.goal_definition", MetricApplicability.APPLICABLE)
    )
    context = _context((message,), profile)

    rendered = repr(message) + repr(context) + context.model_dump_json()
    assert canary not in rendered
    assert "**********" in message.model_dump_json()

    with pytest.raises(ValidationError) as error:
        _message("d", 0, canary + "\x00")
    assert canary not in str(error.value)


def test_extraction_completeness_defaults_fail_closed_for_new_adapters() -> None:
    message = _message("c", 0, "Build the report.")
    context = _context(
        (message,),
        _profile(("prompt.goal_definition", MetricApplicability.APPLICABLE)),
    )
    payload = context.model_dump()
    payload.pop("text_extraction_complete")

    reconstructed = P1TextAnalysisInput.model_validate(payload)

    assert reconstructed.text_extraction_complete is False


def test_full_session_scope_cannot_claim_complete_for_a_partial_window() -> None:
    message = _message("c", 0, "Build the report.")
    context = _context(
        (message,),
        _profile(("prompt.goal_definition", MetricApplicability.APPLICABLE)),
        eligible_count=2,
    )

    with pytest.raises(ValidationError, match="every eligible message"):
        P1TextAnalysisInput.model_validate(
            {
                **context.model_dump(),
                "analysis_scope": TextAnalysisScope(
                    kind=TextAnalysisScopeKind.FULL_AVAILABLE_SESSION,
                    state=TextAnalysisScopeState.COMPLETE,
                    requested_max_messages=100,
                    requested_max_characters=100_000,
                    source_history_complete=True,
                ),
            }
        )


def test_explicit_incomplete_full_session_scope_fails_closed_without_claim() -> None:
    message = _message("c", 0, "Build the report.")
    context = P1TextAnalysisInput.model_validate(
        {
            **_context(
                (message,),
                _profile(
                    ("prompt.goal_definition", MetricApplicability.APPLICABLE)
                ),
                eligible_count=2,
            ).model_dump(),
            "text_extraction_complete": False,
            "analysis_scope": TextAnalysisScope(
                kind=TextAnalysisScopeKind.FULL_AVAILABLE_SESSION,
                state=TextAnalysisScopeState.INCOMPLETE_SOURCE,
                requested_max_messages=1,
                requested_max_characters=100_000,
                source_history_complete=True,
                reason_codes=(TextAnalysisScopeReason.MESSAGE_LIMIT,),
            ),
        }
    )

    assert context.requested_scope_complete is False
    assert context.analysis_scope is not None
    assert context.analysis_scope.state is TextAnalysisScopeState.INCOMPLETE_SOURCE


def test_analysis_scope_enforces_its_requested_character_bound() -> None:
    message = _message("c", 0, "Build the report.")
    context = _context(
        (message,),
        _profile(("prompt.goal_definition", MetricApplicability.APPLICABLE)),
    )

    with pytest.raises(ValidationError, match="requested character scope"):
        P1TextAnalysisInput.model_validate(
            {
                **context.model_dump(),
                "analysis_scope": TextAnalysisScope(
                    kind=TextAnalysisScopeKind.BOUNDED_RECENT,
                    state=TextAnalysisScopeState.COMPLETE,
                    requested_max_messages=1,
                    requested_max_characters=3,
                    source_history_complete=True,
                ),
            }
        )


def test_input_window_is_bounded_but_coverage_can_represent_larger_source() -> None:
    message = _message("c", 0, "Build the report.")
    context = _context(
        (message,),
        _profile(("prompt.goal_definition", MetricApplicability.APPLICABLE)),
        eligible_count=10_001,
    )

    result = DEFAULT_TEXT_METRIC_ENGINE.compute(context, _grant(context))[0]

    assert result.observation.observed_count == 1
    assert result.observation.eligible_count == 10_001
    assert result.observation.coverage == pytest.approx(1 / 10_001)
    assert result.observation.confidence is None


def test_input_rejects_observed_message_kind_outside_source_capability() -> None:
    messages = (
        _message("a", 0, "Build the local report."),
        _message(
            "b",
            1,
            "The report response is ready.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
    )

    with pytest.raises(ValidationError, match="source capability"):
        P1TextAnalysisInput.model_validate(
            {
                **_context(messages, _profile()).model_dump(),
                "available_message_kinds": [TextMessageKind.REQUEST],
            }
        )


def test_analysis_window_rejects_an_aggregate_text_budget_overrun() -> None:
    messages = tuple(
        _message(
            format(index + 1, "x")[-1],
            index,
            "x" * MAX_REDACTED_MESSAGE_CHARACTERS,
        )
        for index in range(16)
    )
    # Make every pseudonym unique while keeping only hexadecimal fixture values.
    messages = tuple(
        message.model_copy(update={"message_id": format(index + 1, "064x")})
        for index, message in enumerate(messages)
    )

    with pytest.raises(ValidationError, match="text budget"):
        _context(
            messages,
            _profile(("prompt.goal_definition", MetricApplicability.APPLICABLE)),
        )


def test_registry_requires_definition_and_calculator_order_to_match() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        TextMetricRegistry(
            definitions=tuple(reversed(TEXT_METRIC_DEFINITIONS)),
            calculators=DETERMINISTIC_TEXT_CALCULATORS,
        )


def test_unknown_not_applicable_and_abstained_remain_distinct() -> None:
    message = _message("c", 0, "Build the report locally.")
    profile = _profile(
        (
            "prompt.constraint_resolution",
            MetricApplicability.APPLICABLE,
        ),
        (
            "logic.plan_state_accounting",
            MetricApplicability.NOT_APPLICABLE,
        ),
        (
            "logic.conversation_loop_closure",
            MetricApplicability.NOT_APPLICABLE,
        ),
    ).model_copy(update={"expected_constraint_kinds": ()})
    context = _context((message,), profile)
    results = {
        result.observation.key: result
        for result in DEFAULT_TEXT_METRIC_ENGINE.compute(context, _grant(context))
    }

    assert results["prompt.goal_definition"].value_state is MetricValueState.UNKNOWN
    assert (
        results["prompt.constraint_resolution"].value_state
        is MetricValueState.ABSTAINED
    )
    assert (
        results["logic.plan_state_accounting"].value_state
        is MetricValueState.NOT_APPLICABLE
    )
    assert (
        results["logic.conversation_loop_closure"].value_state
        is MetricValueState.NOT_APPLICABLE
    )
    assert all(
        result.observation.numeric_value is None
        for result in results.values()
        if result.value_state is not MetricValueState.KNOWN
    )


def test_model_provenance_requires_pin_license_and_tokenizer_as_a_tuple() -> None:
    common = dict(
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-schema-1",
        content_schema_version="redacted-message-1",
        redactor_version="synthetic-redactor-1",
        analysis_window_fingerprint="b" * 64,
        algorithm_id="synthetic.model-adapter",
        algorithm_version="1",
        metric_schema_version=1,
    )
    with pytest.raises(ValidationError, match="pinned revision"):
        TextMetricProvenance(**common, model_id="example/model")

    provenance = TextMetricProvenance(
        **common,
        model_id="example/model",
        model_revision="0123456789abcdef",
        model_license="mit",
        tokenizer_id="example/tokenizer",
    )
    assert provenance.model_revision == "0123456789abcdef"
