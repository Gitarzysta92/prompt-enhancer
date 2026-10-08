from __future__ import annotations

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    TEXT_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.analysis.text_contracts import (
    AggregationMethod,
    ApplicabilityBasis,
    ConstraintKind,
    DeliverableSlot,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    MetricDirection,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextMetricSignalStatus,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.domain import DataTier, Provider


def _message(
    identifier: str,
    sequence: int,
    text: str,
    *,
    role: TextRole,
    kind: TextMessageKind,
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
    *,
    excluded: frozenset[str] = frozenset(),
    constraints: tuple[ConstraintKind, ...],
    deliverables: tuple[DeliverableSlot, ...],
    expected_outcomes: int = 1,
) -> TextTaskProfile:
    return TextTaskProfile(
        applicability=tuple(
            MetricApplicabilityDecision(
                metric_key=definition.key,
                applicability=(
                    MetricApplicability.NOT_APPLICABLE
                    if definition.key in excluded
                    else MetricApplicability.APPLICABLE
                ),
                basis=ApplicabilityBasis.TASK_PROFILE,
            )
            for definition in TEXT_METRIC_DEFINITIONS
        ),
        expected_constraint_kinds=constraints,
        expected_deliverable_slots=deliverables,
        expected_outcome_count=expected_outcomes,
    )


def _compute(
    messages: tuple[EphemeralRedactedMessage, ...],
    profile: TextTaskProfile,
    *,
    focus: str = "1",
    eligible_count: int | None = None,
    available_message_kinds: frozenset[TextMessageKind] = frozenset(TextMessageKind),
    text_extraction_complete: bool = True,
    selected_metric_keys: tuple[str, ...] | None = None,
):
    context = P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id="a" * 64,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-schema-1",
        content_schema_version="redacted-message-1",
        redactor_version="synthetic-redactor-1",
        text_extraction_complete=text_extraction_complete,
        available_message_kinds=available_message_kinds,
        analysis_window_fingerprint="b" * 64,
        focus_message_id=focus * 64,
        observed_message_count=len(messages),
        eligible_message_count=eligible_count or len(messages),
        messages=messages,
        task_profile=profile,
    )
    grant = P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
    )
    return {
        result.observation.key: result
        for result in DEFAULT_TEXT_METRIC_ENGINE.compute(
            context,
            grant,
            selected_metric_keys=selected_metric_keys,
        )
    }


def test_explicit_metric_scope_never_invokes_unselected_calculator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = DEFAULT_TEXT_METRIC_ENGINE.registry.calculators[0]
    unselected = DEFAULT_TEXT_METRIC_ENGINE.registry.calculators[1]

    def reject_unselected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unselected calculator was invoked")

    monkeypatch.setattr(type(unselected), "calculate", reject_unselected)
    messages = (
        _message(
            "1",
            0,
            "Build an example report so reviewers can verify the result.",
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
    )
    results = _compute(
        messages,
        _profile(constraints=(), deliverables=()),
        selected_metric_keys=(selected.definition.key,),
    )

    assert tuple(results) == (selected.definition.key,)


def test_unavailable_action_and_decision_evidence_abstains_instead_of_zero() -> None:
    messages = (
        _message(
            "1",
            0,
            "Build a local dashboard so that reviewers can verify the result.",
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
        _message(
            "2",
            1,
            "Plan: build the dashboard and verify the result.",
            role=TextRole.AGENT,
            kind=TextMessageKind.PLAN,
        ),
        _message(
            "3",
            2,
            "The dashboard response is available.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
    )
    profile = _profile(
        constraints=(ConstraintKind.PRIVACY,),
        deliverables=(DeliverableSlot.ARTIFACT,),
    )

    results = _compute(
        messages,
        profile,
        available_message_kinds=frozenset(
            {
                TextMessageKind.REQUEST,
                TextMessageKind.RESPONSE,
                TextMessageKind.PLAN,
            }
        ),
    )

    for key in (
        "logic.requirement_action_traceability",
        "logic.decision_rationale_coverage",
    ):
        assert results[key].value_state is MetricValueState.ABSTAINED
        assert results[key].observation.numeric_value is None
        assert results[key].explanation_code == "message_kind_unavailable"
    assert results["prompt.goal_definition"].value_state is MetricValueState.KNOWN


def test_incomplete_source_extraction_abstains_all_applicable_text_metrics() -> None:
    messages = (
        _message(
            "1",
            0,
            "Build and verify the local dashboard.",
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
    )
    profile = _profile(
        constraints=(ConstraintKind.PRIVACY,),
        deliverables=(DeliverableSlot.ARTIFACT,),
    )

    results = _compute(
        messages,
        profile,
        text_extraction_complete=False,
    )

    assert len(results) == 10
    assert all(
        result.value_state is MetricValueState.ABSTAINED
        and result.observation.numeric_value is None
        and result.fraction is None
        and result.explanation_code == "source_extraction_incomplete"
        for result in results.values()
    )
def test_unknown_task_specific_denominators_have_explicit_safe_receipts() -> None:
    messages = (
        _message(
            "1",
            0,
            "Build a local dashboard so that users can review the result.",
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
    )
    results = _compute(
        messages,
        _profile(constraints=(), deliverables=()),
    )

    constraints = results["prompt.constraint_resolution"]
    deliverable = results["prompt.deliverable_contract"]
    assert constraints.value_state is MetricValueState.ABSTAINED
    assert tuple(
        (signal.code, signal.status, signal.count)
        for signal in constraints.signals
    ) == (
        ("constraint.expected_categories", TextMetricSignalStatus.UNKNOWN, None),
    )
    assert deliverable.value_state is MetricValueState.ABSTAINED
    assert tuple(
        (signal.code, signal.status, signal.count)
        for signal in deliverable.signals
    ) == (
        ("deliverable.expected_slots", TextMetricSignalStatus.UNKNOWN, None),
    )


def test_short_unknown_language_reply_reduces_coverage_without_erasing_prompt() -> None:
    messages = (
        _message(
            "1",
            0,
            "Build a local dashboard so that reviewers can verify the result.",
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
        _message(
            "2",
            1,
            "OK",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
            language=TextLanguage.UNKNOWN,
        ),
    )
    profile = _profile(
        constraints=(ConstraintKind.PRIVACY,),
        deliverables=(DeliverableSlot.ARTIFACT,),
    )

    result = _compute(
        messages,
        profile,
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.RESPONSE}
        ),
    )["prompt.goal_definition"]

    assert result.value_state is MetricValueState.KNOWN
    assert result.observation.observed_count == 1
    assert result.observation.eligible_count == 2
    assert result.observation.coverage == pytest.approx(0.5)


def test_english_golden_profile_computes_ten_separate_metrics() -> None:
    messages = (
        _message(
            "1",
            0,
            (
                "Build a dashboard PNG report with an Export button for engineering users "
                "so that they can review results.\n"
                "Processing must stay local only and free.\n"
                "The PNG export must exist and tests must pass.\n"
                "You can choose the best chart library.\n"
                "Which theme should be used?"
            ),
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
        _message(
            "2",
            1,
            "Build dashboard export\nRun tests [x] done",
            role=TextRole.AGENT,
            kind=TextMessageKind.PLAN,
        ),
        _message(
            "3",
            2,
            "The theme will use navy.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
        _message(
            "4",
            3,
            "Built dashboard PNG report and Export button for engineering users.",
            role=TextRole.AGENT,
            kind=TextMessageKind.ACTION,
        ),
        _message(
            "5",
            4,
            "Kept processing local and free.",
            role=TextRole.AGENT,
            kind=TextMessageKind.ACTION,
        ),
        _message(
            "6",
            5,
            "Verified PNG export exists and tests pass.",
            role=TextRole.AGENT,
            kind=TextMessageKind.ACTION,
        ),
        _message(
            "7",
            6,
            "Selected SVG rendering because it keeps export deterministic.",
            role=TextRole.AGENT,
            kind=TextMessageKind.DECISION,
        ),
        _message(
            "8",
            7,
            "Storage is sqlite.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
        _message(
            "9",
            8,
            "Storage is postgres.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
    )
    profile = _profile(
        constraints=(ConstraintKind.PRIVACY, ConstraintKind.COST),
        deliverables=(
            DeliverableSlot.ARTIFACT,
            DeliverableSlot.FORMAT,
            DeliverableSlot.AUDIENCE,
            DeliverableSlot.INTERFACE,
        ),
    )

    results = _compute(messages, profile)

    assert tuple(results) == tuple(definition.key for definition in TEXT_METRIC_DEFINITIONS)
    expected = {
        "prompt.goal_definition": 1.0,
        "prompt.constraint_resolution": 1.0,
        "prompt.completion_evaluability": 1.0,
        "prompt.deliverable_contract": 1.0,
        "prompt.open_decision_load": 0.2,
        "logic.requirement_action_traceability": 1.0,
        "logic.plan_state_accounting": 1.0,
        "logic.decision_rationale_coverage": 1.0,
        "logic.scoped_consistency_candidate_rate": 1.0,
        "logic.conversation_loop_closure": 1.0,
    }
    assert {
        key: result.observation.numeric_value for key, result in results.items()
    } == pytest.approx(expected)
    assert all(result.value_state is MetricValueState.KNOWN for result in results.values())
    assert all(result.observation.confidence is None for result in results.values())
    assert all(
        result.aggregation_method is AggregationMethod.RATIO_OF_SUMS
        for result in results.values()
    )
    assert results["prompt.open_decision_load"].direction is MetricDirection.LOWER_IS_BETTER
    assert (
        results["logic.scoped_consistency_candidate_rate"].direction
        is MetricDirection.LOWER_IS_BETTER
    )
    assert all(
        result.provenance.analysis_window_fingerprint == "b" * 64
        and result.provenance.model_id is None
        and result.provenance.local_only
        for result in results.values()
    )
    assert tuple(
        (signal.code, signal.status, signal.count)
        for signal in results["prompt.goal_definition"].signals
    ) == (
        ("goal.action", TextMetricSignalStatus.DETECTED, 1),
        ("goal.target", TextMetricSignalStatus.DETECTED, 1),
        ("goal.outcome", TextMetricSignalStatus.DETECTED, 1),
    )
    assert tuple(
        (signal.code, signal.count)
        for signal in results["prompt.completion_evaluability"].signals
    ) == (
        ("completion.requirements", 1),
        ("completion.checkable", 1),
    )
    assert tuple(
        (signal.code, signal.count)
        for signal in results["prompt.open_decision_load"].signals
    ) == (
        ("choices.prompt_clauses", 5),
        ("choices.marker_clauses", 1),
    )


def test_polish_golden_profile_supports_deliberate_delegation_and_explicit_na() -> None:
    messages = (
        _message(
            "1",
            0,
            (
                "Stwórz panel PNG dla użytkowników, aby mogli sprawdzić wynik.\n"
                "Dane muszą zostać tylko lokalnie i bez opłat.\n"
                "Eksport PNG musi istnieć, a test musi przejść.\n"
                "Wybierz najlepszą bibliotekę według twojej oceny."
            ),
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
            language=TextLanguage.POLISH,
        ),
        _message(
            "2",
            1,
            "Stworzono panel PNG dla użytkowników.",
            role=TextRole.AGENT,
            kind=TextMessageKind.ACTION,
            language=TextLanguage.POLISH,
        ),
        _message(
            "3",
            2,
            "Dane pozostają tylko lokalnie i bez opłat.",
            role=TextRole.AGENT,
            kind=TextMessageKind.ACTION,
            language=TextLanguage.POLISH,
        ),
        _message(
            "4",
            3,
            "Eksport PNG istnieje, a test przechodzi.",
            role=TextRole.AGENT,
            kind=TextMessageKind.ACTION,
            language=TextLanguage.POLISH,
        ),
        _message(
            "5",
            4,
            "Wybrano SVG, ponieważ format jest deterministyczny.",
            role=TextRole.AGENT,
            kind=TextMessageKind.DECISION,
            language=TextLanguage.POLISH,
        ),
    )
    excluded = frozenset(
        {
            "logic.plan_state_accounting",
            "logic.scoped_consistency_candidate_rate",
            "logic.conversation_loop_closure",
        }
    )
    profile = _profile(
        excluded=excluded,
        constraints=(ConstraintKind.PRIVACY, ConstraintKind.COST),
        deliverables=(
            DeliverableSlot.ARTIFACT,
            DeliverableSlot.FORMAT,
            DeliverableSlot.AUDIENCE,
        ),
    )

    results = _compute(messages, profile)

    for key in excluded:
        assert results[key].value_state is MetricValueState.NOT_APPLICABLE
        assert results[key].observation.numeric_value is None
    assert results["prompt.goal_definition"].observation.numeric_value == 1
    assert results["prompt.constraint_resolution"].observation.numeric_value == 1
    assert results["prompt.completion_evaluability"].observation.numeric_value == 1
    assert results["prompt.deliverable_contract"].observation.numeric_value == 1
    assert results["prompt.open_decision_load"].observation.numeric_value == 0
    assert (
        results["logic.requirement_action_traceability"].observation.numeric_value
        == 1
    )
    assert results["logic.decision_rationale_coverage"].observation.numeric_value == 1


def test_superseded_claim_is_not_reported_as_a_consistency_candidate() -> None:
    superseded_id = "1" * 64
    messages = (
        _message(
            "1",
            0,
            "Status is draft.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
        _message(
            "2",
            1,
            "Status is ready.",
            role=TextRole.AGENT,
            kind=TextMessageKind.SUMMARY,
            supersedes=(superseded_id,),
        ),
        _message(
            "3",
            2,
            "Validate status.",
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
    )
    profile = _profile(
        constraints=(ConstraintKind.SCOPE,),
        deliverables=(DeliverableSlot.ARTIFACT,),
    )

    result = _compute(messages, profile, focus="3")[
        "logic.scoped_consistency_candidate_rate"
    ]

    assert result.value_state is MetricValueState.UNKNOWN
    assert result.explanation_code == "comparable_claims_unknown"
    assert result.observation.numeric_value is None
