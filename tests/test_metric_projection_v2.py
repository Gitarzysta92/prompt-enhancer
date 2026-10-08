from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION,
    SUPPORTED_METRIC_PROJECTION_V2_VERSIONS,
    _issue_metric_state_projection,
    classify_feedback_rework,
    project_metric_states_v2,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    ObjectiveMetricOverride,
)
from prompt_enhancer.application.analysis.semantic_units import (
    FeedbackReworkClass,
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ConstraintKind,
    EphemeralRedactedMessage,
    MetricFraction,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.domain import Provider


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-v2:{label}".encode()).hexdigest()


class _SyntheticIdFactory:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        return hashlib.sha256(
            "\x1f".join(
                (namespace, *values, secret.get_secret_value())
            ).encode()
        ).hexdigest()


IDS = _SyntheticIdFactory()


def _message(
    label: str,
    sequence: int,
    role: TextRole,
    kind: TextMessageKind,
    text: str,
    *,
    language: TextLanguage = TextLanguage.ENGLISH,
    supersedes: tuple[str, ...] = (),
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=_id(label),
        sequence=sequence,
        role=role,
        kind=kind,
        language=language,
        text=SecretStr(text),
        supersedes_message_ids=supersedes,
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    *,
    label: str,
    profile: TextTaskProfile | None = None,
    complete: bool = True,
) -> P1TextAnalysisInput:
    focus = next(
        message
        for message in reversed(messages)
        if message.role is TextRole.USER
        and message.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=complete,
        available_message_kinds=frozenset(message.kind for message in messages),
        analysis_window_fingerprint=_id(f"window:{label}"),
        focus_message_id=focus.message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages) if complete else len(messages) + 5,
        messages=messages,
        task_profile=profile or TextTaskProfile(applicability=()),
    )


def _project(
    context: P1TextAnalysisInput,
    *,
    conversational: dict[str, Any] | None = None,
    objective: dict[str, ObjectiveMetricOverride] | None = None,
):
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    return project_metric_states_v2(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
        conversational_results=conversational,
        objective_overrides=objective,
    )


def _by_key(states: tuple[Any, ...]) -> dict[str, Any]:
    return {state.metric_key: state for state in states}


def test_one_message_session_projects_all_twenty_without_unknown_at_zero() -> None:
    context = _context(
        (
            _message(
                "one-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create a fictional widget report.",
            ),
        ),
        label="one-message",
    )

    states = _project(context)
    by_key = _by_key(states)

    assert len(states) == len(METRIC_CONTRACTS_V2) == 20
    assert len(by_key) == 20
    assert all(
        state.numeric_value is None
        for state in states
        if state.value_state is not MetricValueStateV2.KNOWN
    )
    assert (
        by_key["outcome.verification_strategy_adequacy"].value_state
        is MetricValueStateV2.PENDING
    )
    assert (
        by_key["collaboration.rework_candidate_rate"].value_state
        is MetricValueStateV2.NOT_APPLICABLE
    )
    # The built-in adapter cannot extract ambiguity episodes.  An empty head
    # set therefore proves neither N/A nor zero.
    assert (
        by_key["collaboration.ambiguity_resolution"].value_state
        is MetricValueStateV2.UNKNOWN
    )


@pytest.mark.parametrize(
    ("language", "request_text", "response_text"),
    (
        (
            TextLanguage.ENGLISH,
            "Implement the fictional widget export.",
            "For the widget export, run a regression test; it must pass with exactly 3 rows.",
        ),
        (
            TextLanguage.POLISH,
            "Zaimplementuj fikcyjny widget eksport.",
            "Dla widget eksport uruchom test regresji; wynik musi przejść dokładnie 3 wiersze.",
        ),
    ),
)
def test_verification_strategy_is_conversational_en_pl(
    language: TextLanguage,
    request_text: str,
    response_text: str,
) -> None:
    context = _context(
        (
            _message(
                "strategy-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                request_text,
                language=language,
            ),
            _message(
                "strategy-response",
                2,
                TextRole.AGENT,
                TextMessageKind.RESPONSE,
                response_text,
                language=language,
            ),
        ),
        label=f"strategy-{language.value}",
    )

    state = _by_key(_project(context))["outcome.verification_strategy_adequacy"]

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (1, 1, 1.0)
    assert state.evidence_authority.value == "conversation"


def test_related_terminal_response_can_prove_a_strategy_gap() -> None:
    context = _context(
        (
            _message(
                "gap-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Implement the fictional widget export.",
            ),
            _message(
                "gap-response",
                2,
                TextRole.AGENT,
                TextMessageKind.RESPONSE,
                "The fictional widget export is implemented with no stated check.",
            ),
        ),
        label="strategy-gap",
    )

    state = _by_key(_project(context))["outcome.verification_strategy_adequacy"]

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (0, 1, 0.0)


def test_superseded_request_is_excluded_from_strategy_denominator() -> None:
    old = _message(
        "old-request",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Implement the old fictional widget export.",
    )
    response = _message(
        "old-response",
        2,
        TextRole.AGENT,
        TextMessageKind.RESPONSE,
        "For the old fictional widget export, run a test that must pass.",
    )
    current = _message(
        "current-request",
        3,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the current fictional summary.",
        supersedes=(old.message_id,),
    )
    context = _context((old, response, current), label="superseded-strategy")

    state = _by_key(_project(context))["outcome.verification_strategy_adequacy"]

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.statistics.eligible_count == 1
    assert state.statistics.distinct_owner_count == 1
    assert state.statistics.superseded_excluded_count == 1


def test_profile_slots_use_only_the_active_request_revision() -> None:
    old = _message(
        "platform-old",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the fictional report for Windows 11.",
    )
    current = _message(
        "platform-current",
        2,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the revised fictional report.",
        supersedes=(old.message_id,),
    )
    context = _context(
        (old, current),
        label="active-profile",
        profile=TextTaskProfile(
            applicability=(),
            expected_constraint_kinds=(ConstraintKind.PLATFORM,),
        ),
    )

    state = _by_key(_project(context))["prompt.constraint_precision"]

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (0, 1, 0.0)


def test_rubric_statistics_match_the_exact_factor_fraction() -> None:
    context = _context(
        (
            _message(
                "rubric-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="rubric",
    )
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=2, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    state = _by_key(
        _project(
            context,
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator) == (2, 3)
    assert (
        state.statistics.eligible_count,
        state.statistics.met_count,
        state.statistics.not_met_count,
        state.statistics.distinct_owner_count,
    ) == (3, 2, 1, 1)


def test_incomplete_legacy_scope_withholds_a_known_rubric_without_crashing() -> None:
    context = _context(
        (
            _message(
                "incomplete-rubric-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="incomplete-rubric",
        complete=False,
    )
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=2, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    projection = _project(
        context,
        conversational={"prompt.task_definition_coverage": result},
    )
    state = _by_key(projection)["prompt.task_definition_coverage"]
    publication = publish_metric_states_v2(projection)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.numeric_value is None
    assert state.explanation_code == "source_reconciliation_incomplete"
    assert publication.unknown_count >= 1


RUBRIC_METRIC_KEYS = (
    "prompt.task_definition_coverage",
    "prompt.problem_evidence_quality",
    "prompt.context_sufficiency",
)


def test_projection_identities_are_readable_but_only_the_newest_is_written() -> None:
    # Every identity stays readable. Each newer producer is append-only while
    # this frozen historical producer continues to stamp ``-2``.
    assert SUPPORTED_METRIC_PROJECTION_V2_VERSIONS == (
        "metric-contract-v2-projection-1",
        "metric-contract-v2-projection-2",
        "metric-contract-v2-projection-3",
        "metric-contract-v2-projection-4",
        "metric-contract-v2-projection-5",
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
    )
    assert METRIC_PROJECTION_V2_VERSION == "metric-contract-v2-projection-2"
    context = _context(
        (
            _message(
                "identity-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="identity",
    )

    states = _project(context)

    assert all(
        state.projection_version == METRIC_PROJECTION_V2_VERSION
        for state in states
    )
    assert publish_metric_states_v2(states).projection_version == (
        METRIC_PROJECTION_V2_VERSION
    )


def test_a_publication_cannot_mix_producer_projection_identities() -> None:
    context = _context(
        (
            _message(
                "mixed-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="mixed-identity",
    )
    states = _project(context)
    mixed = _issue_metric_state_projection(
        (
            states[0].model_copy(
                update={"projection_version": "metric-contract-v2-projection-1"}
            ),
            *tuple(states)[1:],
        ),
        compatibility=False,
    )

    with pytest.raises(ValueError, match="mix producer projection identities"):
        publish_metric_states_v2(mixed)


def _feedback_focus_context() -> P1TextAnalysisInput:
    """A window whose focus turn is feedback, not the request revision."""

    return _context(
        (
            _message(
                "owned-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report with exact acceptance rows.",
            ),
            _message(
                "later-feedback",
                2,
                TextRole.USER,
                TextMessageKind.FEEDBACK,
                "A neutral fictional remark about the widget report.",
            ),
        ),
        label="feedback-focus",
    )


def test_feedback_focus_cannot_borrow_request_revision_ownership() -> None:
    context = _feedback_focus_context()
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=3, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    by_key = _by_key(
        _project(
            context,
            conversational={key: result for key in RUBRIC_METRIC_KEYS},
        )
    )

    for key in RUBRIC_METRIC_KEYS:
        state = by_key[key]
        assert state.value_state is MetricValueStateV2.UNKNOWN
        assert state.numeric_value is None
        assert state.numerator is state.denominator is None
        assert state.explanation_code == "rubric_opportunity_not_focus_owned"
        # Never a zero: an unowned opportunity is not a failed one.
        assert state.statistics.eligible_count == 0
        assert state.statistics.met_count == 0
        assert state.statistics.not_met_count == 0


def test_feedback_focus_withholding_survives_publication_round_trip() -> None:
    context = _feedback_focus_context()
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=3, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    projection = _project(
        context,
        conversational={key: result for key in RUBRIC_METRIC_KEYS},
    )
    publication = publish_metric_states_v2(projection)
    published = {item.state.metric_key: item for item in publication.metrics}

    for key in RUBRIC_METRIC_KEYS:
        item = published[key]
        assert item.state.value_state is MetricValueStateV2.UNKNOWN
        assert item.guidance.numerator is item.guidance.denominator is None
        assert item.implementation_state.value == "method_only_withheld"
    payload = publication.model_dump_json()
    assert "rubric_opportunity_not_focus_owned" in payload


def test_request_focus_still_publishes_the_owned_rubric_fraction() -> None:
    context = _context(
        (
            _message(
                "focus-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="request-focus",
    )
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=2, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    state = _by_key(
        _project(
            context,
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator) == (2, 3)
    assert state.statistics.distinct_owner_count == 1


def test_superseded_focus_request_is_not_an_owned_rubric_opportunity() -> None:
    old = _message(
        "superseded-focus",
        1,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the old fictional report.",
    )
    current = _message(
        "current-owner",
        2,
        TextRole.USER,
        TextMessageKind.REQUEST,
        "Create the current fictional report.",
        supersedes=(old.message_id,),
    )
    messages = (old, current)
    context = P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(item.kind for item in messages),
        analysis_window_fingerprint=_id("window:superseded-focus"),
        focus_message_id=old.message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=TextTaskProfile(applicability=()),
    )
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=3, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    state = _by_key(
        _project(
            context,
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == "rubric_opportunity_not_focus_owned"


def test_rubric_denominator_mismatch_is_unknown_not_a_score() -> None:
    context = _context(
        (
            _message(
                "mismatch-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="rubric-mismatch",
    )
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=1, denominator=2),
        explanation_code="synthetic_mismatched_result",
    )

    state = _by_key(
        _project(
            context,
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.numeric_value is None
    assert state.explanation_code == "rubric_denominator_mismatch"


def test_partial_objective_receipt_yields_pending_bounds_not_a_point() -> None:
    context = _context(
        (
            _message(
                "objective-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Run two fictional checks.",
            ),
        ),
        label="objective-pending",
    )
    override = ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code="synthetic_first_pass_open",
        resolved_opportunity_count=1,
        eligible_opportunity_count=2,
        met_opportunity_count=1,
    )

    state = _by_key(
        _project(
            context,
            objective={"outcome.first_pass_verification": override},
        )
    )["outcome.first_pass_verification"]

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.numeric_value is None
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (0.5, 1.0)
    assert (
        state.statistics.met_count,
        state.statistics.pending_count,
        state.statistics.eligible_count,
    ) == (1, 1, 2)


def test_incomplete_source_is_unknown_not_temporal_pending() -> None:
    context = _context(
        (
            _message(
                "incomplete-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="incomplete",
        complete=False,
    )

    state = _by_key(_project(context))["outcome.verification_strategy_adequacy"]

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.numeric_value is None
    assert state.explanation_code == "source_reconciliation_incomplete"


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("That is wrong; redo it.", FeedbackReworkClass.AVOIDABLE_CORRECTION),
        ("To jest źle; zrób ponownie.", FeedbackReworkClass.AVOIDABLE_CORRECTION),
        ("New requirement: also add a fictional CSV.", FeedbackReworkClass.SCOPE_EVOLUTION),
        ("Zmiana zakresu: dodaj fikcyjny CSV.", FeedbackReworkClass.SCOPE_EVOLUTION),
        ("I would prefer a fictional blue theme.", FeedbackReworkClass.PREFERENCE_CHANGE),
        ("Wolę fikcyjny niebieski motyw.", FeedbackReworkClass.PREFERENCE_CHANGE),
        ("For context, a fictional API changed.", FeedbackReworkClass.NEW_INFORMATION),
        ("Dla kontekstu, fikcyjne API się zmieniło.", FeedbackReworkClass.NEW_INFORMATION),
        ("A neutral fictional comment.", FeedbackReworkClass.UNKNOWN),
    ),
)
def test_rework_classifier_is_mutually_exclusive_en_pl(
    text: str,
    expected: FeedbackReworkClass,
) -> None:
    assert classify_feedback_rework(text) is expected


def test_scope_change_exclusion_outranks_a_correction_cue() -> None:
    assert (
        classify_feedback_rework(
            "New requirement: change the scope; the earlier result is wrong."
        )
        is FeedbackReworkClass.SCOPE_EVOLUTION
    )


def test_v2_projection_serializes_no_ephemeral_text() -> None:
    canary = "synthetic-private-canary-v2-43e1"
    context = _context(
        (
            _message(
                "private-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                canary,
            ),
        ),
        label="privacy",
    )

    states = _project(context)

    assert all(canary not in state.model_dump_json() for state in states)
    payload = states[0].model_dump()
    payload["explanation_code"] = "synthetic private reason must not persist"
    with pytest.raises(ValidationError, match="content-free"):
        type(states[0]).model_validate(payload)
    payload = states[0].model_dump()
    payload["product_metric_eligible"] = True
    with pytest.raises(ValidationError):
        type(states[0]).model_validate(payload)
