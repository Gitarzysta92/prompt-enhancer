"""Synthetic acceptance tests for append-only metric projection r5."""

from __future__ import annotations

import hashlib

from pydantic import SecretStr

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    MetricValueStateV2,
)
from prompt_enhancer.application.analysis.metric_projection_v5 import (
    ACCEPTANCE_METRIC_KEY,
    METRIC_PROJECTION_V5_VERSION,
    REASON_CLAUSE_OWNED_ACCEPTANCE,
    project_metric_states_v5,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.semantic_units import (
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
    return hashlib.sha256(f"synthetic-v5:{label}".encode()).hexdigest()


class _SyntheticIds:
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


IDS = _SyntheticIds()


def _message(
    label: str,
    sequence: int,
    text: str,
    *,
    supersedes: tuple[str, ...] = (),
    language: TextLanguage = TextLanguage.ENGLISH,
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=_id(label),
        sequence=sequence,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=language,
        text=SecretStr(text),
        supersedes_message_ids=supersedes,
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    *,
    expected: int | None,
    label: str,
) -> P1TextAnalysisInput:
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=True,
        available_message_kinds=frozenset({TextMessageKind.REQUEST}),
        analysis_window_fingerprint=_id(f"window:{label}"),
        focus_message_id=messages[-1].message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=TextTaskProfile(
            applicability=(),
            expected_outcome_count=expected,
        ),
    )


def _project(context: P1TextAnalysisInput):
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    return project_metric_states_v5(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
    )


def _acceptance(context: P1TextAnalysisInput):
    return next(
        state for state in _project(context) if state.metric_key == ACCEPTANCE_METRIC_KEY
    )


def test_three_expected_outcomes_with_two_checkable_clauses_is_two_thirds() -> None:
    context = _context(
        (
            _message(
                "request",
                1,
                "Create the fictional report and return exactly three rows. "
                "Add a regression test that must pass without errors.",
            ),
        ),
        expected=3,
        label="two-of-three",
    )

    state = _acceptance(context)

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator) == (2, 3)
    assert state.numeric_value == 2 / 3
    assert state.explanation_code == REASON_CLAUSE_OWNED_ACCEPTANCE
    assert state.projection_version == METRIC_PROJECTION_V5_VERSION


def test_duplicate_checkable_clause_does_not_inflate_acceptance() -> None:
    repeated = "The fictional export must return exactly three rows."
    context = _context(
        (_message("request", 1, f"{repeated} {repeated}"),),
        expected=2,
        label="duplicate",
    )

    state = _acceptance(context)

    assert (state.numerator, state.denominator) == (1, 2)


def test_polish_checkable_clauses_use_the_same_owned_denominator() -> None:
    context = _context(
        (
            _message(
                "polish-request",
                1,
                "Utwórz fikcyjny raport, który zwraca dokładnie trzy wiersze. "
                "Dodaj test, który musi przejść.",
                language=TextLanguage.POLISH,
            ),
        ),
        expected=3,
        label="polish-two-of-three",
    )

    state = _acceptance(context)

    assert (state.numerator, state.denominator) == (2, 3)


def test_question_with_check_cues_is_not_an_acceptance_requirement() -> None:
    context = _context(
        (
            _message(
                "question-request",
                1,
                "Should the fictional report return exactly three rows? "
                "Create a regression test that must pass.",
            ),
        ),
        expected=2,
        label="question-excluded",
    )

    state = _acceptance(context)

    assert (state.numerator, state.denominator) == (1, 2)


def test_superseded_checkable_clauses_do_not_satisfy_active_request() -> None:
    old = _message(
        "old",
        1,
        "Return exactly three rows. Add a test that must pass.",
    )
    current = _message(
        "current",
        2,
        "Create the revised fictional report with a visible summary.",
        supersedes=(old.message_id,),
    )
    context = _context((old, current), expected=3, label="superseded")

    state = _acceptance(context)

    assert (state.numerator, state.denominator, state.numeric_value) == (1, 3, 1 / 3)


def test_unconfigured_profile_remains_unknown_and_never_zero() -> None:
    context = _context(
        (_message("request", 1, "Create the fictional report."),),
        expected=None,
        label="unconfigured",
    )

    state = _acceptance(context)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.numerator is None
    assert state.denominator is None
    assert state.numeric_value is None


def test_r5_retags_all_twenty_rows_and_publication_as_one_identity() -> None:
    context = _context(
        (_message("request", 1, "Create the report and return exactly one row."),),
        expected=1,
        label="identity",
    )

    states = _project(context)
    publication = publish_metric_states_v2(states)

    assert len(states) == 20
    assert {state.projection_version for state in states} == {
        METRIC_PROJECTION_V5_VERSION
    }
    assert publication.projection_version == METRIC_PROJECTION_V5_VERSION
