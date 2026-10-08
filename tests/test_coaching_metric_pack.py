from __future__ import annotations

from pydantic import SecretStr

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    DEFAULT_COACHING_METRIC_ENGINE,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ApplicabilityBasis,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.domain import DataTier, Provider


def _id(character: str) -> str:
    return character * 64


def _profile() -> TextTaskProfile:
    return TextTaskProfile(
        applicability=tuple(
            MetricApplicabilityDecision(
                metric_key=definition.key,
                applicability=MetricApplicability.APPLICABLE,
                basis=ApplicabilityBasis.TASK_PROFILE,
            )
            for definition in COACHING_METRIC_DEFINITIONS
        )
    )


def _context() -> P1TextAnalysisInput:
    messages = (
        EphemeralRedactedMessage(
            message_id=_id("a"),
            sequence=0,
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "Fix the dashboard export bug in the React page. Currently the PNG "
                "button returns an error on Windows 11; it should download a PNG. "
                "Reproduce it after opening the Metrics page. Keep processing local "
                "and under 100 ms so that reviewers can verify the visible file."
            ),
        ),
        EphemeralRedactedMessage(
            message_id=_id("b"),
            sequence=1,
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "My hypothesis is that the canvas export loses its image URL. "
                "Which browser route reproduces the failure?"
            ),
        ),
        EphemeralRedactedMessage(
            message_id=_id("c"),
            sequence=2,
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "To clarify, use the Metrics route in the desktop browser. "
                "Actually keep SVG out of scope and return a PNG file."
            ),
        ),
        EphemeralRedactedMessage(
            message_id=_id("d"),
            sequence=3,
            role=TextRole.AGENT,
            kind=TextMessageKind.PLAN,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "Plan: reproduce the canvas export image URL failure on the Metrics route, "
                "update the React canvas path, and run the export test to verify the PNG file."
            ),
        ),
    )
    return P1TextAnalysisInput(
        provider=Provider.CODEX,
        session_id=_id("e"),
        provider_version="example-provider-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-source-1",
        content_schema_version="example-content-1",
        redactor_version="example-redactor-1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(
            {
                TextMessageKind.REQUEST,
                TextMessageKind.RESPONSE,
                TextMessageKind.PLAN,
            }
        ),
        analysis_window_fingerprint=_id("f"),
        focus_message_id=_id("c"),
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=_profile(),
    )


def _results():
    return _compute(_context())


def _compute(context: P1TextAnalysisInput):
    grant = P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
    )
    return DEFAULT_COACHING_METRIC_ENGINE.compute(
        context,
        grant,
        pack_key=COACHING_METRIC_PACK_KEY,
        pack_version=COACHING_METRIC_PACK_VERSION,
    )


def test_exploration_conversion_requires_a_later_related_structured_item() -> None:
    positive = {
        result.observation.key: result for result in _results()
    }["collaboration.exploration_conversion"]
    assert positive.fraction is not None
    assert positive.fraction.numerator == 1
    assert positive.fraction.denominator == 1

    context = _context()
    unrelated_plan = context.messages[-1].model_copy(
        update={
            "text": SecretStr(
                "Plan: rotate database backups and inspect the unrelated storage quota."
            )
        }
    )
    unrelated_context = context.model_copy(
        update={"messages": (*context.messages[:-1], unrelated_plan)}
    )
    negative = {
        result.observation.key: result for result in _compute(unrelated_context)
    }["collaboration.exploration_conversion"]
    assert negative.value_state is MetricValueState.KNOWN
    assert negative.fraction is not None
    assert negative.fraction.numerator == 0
    assert negative.fraction.denominator == 1

    shared_domain_token_messages = list(context.messages)
    shared_domain_token_messages[1] = shared_domain_token_messages[1].model_copy(
        update={
            "text": SecretStr(
                "My hypothesis is that the database cache causes timeout failures."
            )
        }
    )
    shared_domain_token_messages[-1] = shared_domain_token_messages[-1].model_copy(
        update={
            "text": SecretStr(
                "Plan: migrate the database schema, rotate credentials, archive "
                "reports, document ownership, benchmark queues, and review alerts."
            )
        }
    )
    shared_domain_token_context = context.model_copy(
        update={"messages": tuple(shared_domain_token_messages)}
    )
    hard_negative = {
        result.observation.key: result
        for result in _compute(shared_domain_token_context)
    }["collaboration.exploration_conversion"]
    assert hard_negative.value_state is MetricValueState.KNOWN
    assert hard_negative.fraction is not None
    assert hard_negative.fraction.numerator == 0
    assert hard_negative.fraction.denominator == 1


def test_right_edge_interaction_candidates_never_become_solid_negatives() -> None:
    base = _context()
    cases = (
        (
            "collaboration.ambiguity_resolution",
            TextRole.USER,
            TextMessageKind.REQUEST,
            "Maybe use this thing or something?",
        ),
        (
            "collaboration.clarification_yield",
            TextRole.AGENT,
            TextMessageKind.RESPONSE,
            "Which deployment route should be used?",
        ),
        (
            "collaboration.exploration_conversion",
            TextRole.AGENT,
            TextMessageKind.RESPONSE,
            "My hypothesis is that the render cache might be stale.",
        ),
        (
            "collaboration.scope_change_discipline",
            TextRole.USER,
            TextMessageKind.FEEDBACK,
            "Actually change scope and additionally remove the export option.",
        ),
        (
            "logic.open_loop_closure",
            TextRole.USER,
            TextMessageKind.REQUEST,
            "How should the new export route behave?",
        ),
    )

    for ordinal, (metric_key, role, kind, text) in enumerate(cases, start=1):
        last = EphemeralRedactedMessage(
            message_id=_id(str(ordinal)),
            sequence=4,
            role=role,
            kind=kind,
            language=TextLanguage.ENGLISH,
            text=SecretStr(text),
        )
        messages = (*base.messages, last)
        context = base.model_copy(
            update={
                "messages": messages,
                "observed_message_count": len(messages),
                "eligible_message_count": len(messages),
                "available_message_kinds": frozenset(
                    {*base.available_message_kinds, kind}
                ),
            }
        )
        result = {
            item.observation.key: item for item in _compute(context)
        }[metric_key]

        assert result.value_state is MetricValueState.UNKNOWN
        assert result.observation.numeric_value is None
        assert result.explanation_code == "episode_horizon_open"


def test_later_episode_boundary_allows_a_true_negative_candidate() -> None:
    base = _context()
    hypothesis = EphemeralRedactedMessage(
        message_id=_id("6"),
        sequence=4,
        role=TextRole.AGENT,
        kind=TextMessageKind.RESPONSE,
        language=TextLanguage.ENGLISH,
        text=SecretStr("My hypothesis is that the render cache might be stale."),
    )
    unrelated_plan = EphemeralRedactedMessage(
        message_id=_id("7"),
        sequence=5,
        role=TextRole.AGENT,
        kind=TextMessageKind.PLAN,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Plan: rotate archived audit records and review storage quotas."),
    )
    messages = (*base.messages, hypothesis, unrelated_plan)
    context = base.model_copy(
        update={
            "messages": messages,
            "observed_message_count": len(messages),
            "eligible_message_count": len(messages),
        }
    )

    result = {
        item.observation.key: item for item in _compute(context)
    }["collaboration.exploration_conversion"]

    assert result.value_state is MetricValueState.KNOWN
    assert result.fraction is not None
    assert result.fraction.numerator == 1
    assert result.fraction.denominator == 2


def test_task_and_context_fixed_rubrics_use_only_the_focus_request() -> None:
    context = _context()
    focus_only_messages = list(context.messages)
    focus_only_messages[2] = focus_only_messages[2].model_copy(
        update={"text": SecretStr("Make the report.")}
    )
    focus_only_context = context.model_copy(
        update={"messages": tuple(focus_only_messages)}
    )
    results = {
        result.observation.key: result for result in _compute(focus_only_context)
    }

    task = results["prompt.task_definition_coverage"]
    context_metric = results["prompt.context_sufficiency"]
    assert task.observation.version == 2
    assert context_metric.observation.version == 2
    assert task.fraction is not None
    assert (task.fraction.numerator, task.fraction.denominator) == (2, 3)
    assert context_metric.fraction is not None
    assert (context_metric.fraction.numerator, context_metric.fraction.denominator) == (
        0,
        3,
    )
    assert {signal.code for signal in task.signals} == {
        "task.action",
        "task.target",
        "task.outcome",
    }
    assert {signal.code for signal in context_metric.signals} == {
        "context.current_state",
        "context.environment",
        "context.boundary",
    }
    assert {evidence.message_id for evidence in task.evidence} == {_id("c")}
    assert {evidence.message_id for evidence in context_metric.evidence} == {
        _id("c")
    }


def test_coaching_pack_has_exactly_twenty_versioned_independent_metrics() -> None:
    identities = tuple(
        (definition.key, definition.version) for definition in COACHING_METRIC_DEFINITIONS
    )
    assert len(identities) == 20
    assert len(set(identities)) == 20
    assert {definition.dimension for definition in COACHING_METRIC_DEFINITIONS} == {
        "prompt",
        "collaboration",
        "logic",
        "outcome",
    }
    assert not any("intelligence" in definition.key for definition in COACHING_METRIC_DEFINITIONS)
    assert dict(identities) == {
        "prompt.task_definition_coverage": 2,
        "prompt.problem_evidence_quality": 2,
        "prompt.context_sufficiency": 2,
        "prompt.constraint_precision": 2,
        "prompt.acceptance_testability": 2,
        "prompt.deliverable_contract": 3,
        "collaboration.ambiguity_resolution": 2,
        "collaboration.clarification_yield": 2,
        "collaboration.exploration_conversion": 2,
        "collaboration.scope_change_discipline": 2,
        "collaboration.rework_candidate_rate": 2,
        "logic.decomposition_coverage": 2,
        "logic.hypothesis_test_linkage": 2,
        "logic.decision_rationale_coverage": 3,
        "logic.requirement_action_traceability": 3,
        "logic.open_loop_closure": 2,
        "outcome.agent_claim_grounding": 2,
        "outcome.verification_strategy_adequacy": 2,
        "outcome.first_pass_verification": 2,
        "outcome.verified_requirement_coverage": 2,
    }
    assert COACHING_METRIC_PACK_VERSION == 3


def test_coaching_pack_produces_all_results_without_fabricating_objective_success() -> None:
    results = _results()
    by_key = {result.observation.key: result for result in results}

    assert tuple(
        (result.observation.key, result.observation.version) for result in results
    ) == tuple(
        (definition.key, definition.version) for definition in COACHING_METRIC_DEFINITIONS
    )
    assert len(results) == 20
    assert by_key["prompt.task_definition_coverage"].value_state is MetricValueState.KNOWN
    assert by_key["prompt.problem_evidence_quality"].fraction is not None
    assert by_key["collaboration.clarification_yield"].value_state is MetricValueState.KNOWN
    assert by_key["logic.decomposition_coverage"].value_state is MetricValueState.KNOWN

    for key in (
        "logic.hypothesis_test_linkage",
        "logic.decision_rationale_coverage",
        "logic.requirement_action_traceability",
        "outcome.agent_claim_grounding",
        "outcome.first_pass_verification",
        "outcome.verified_requirement_coverage",
    ):
        assert by_key[key].value_state is MetricValueState.ABSTAINED
        assert by_key[key].observation.numeric_value is None


def test_coaching_results_are_deterministic_and_content_free() -> None:
    first = _results()
    second = _results()
    assert first == second
    rendered = repr(first) + str([result.model_dump() for result in first])
    for canary in ("dashboard export bug", "Windows 11", "canvas export"):
        assert canary not in rendered
    for result in first:
        assert result.provenance.model_id is None
        assert result.provenance.algorithm_id == "rules.en-pl.coaching-observables"
        assert result.observation.confidence is None


def test_incomplete_source_abstains_every_metric_instead_of_scoring_partial_text() -> None:
    context = _context().model_copy(update={"text_extraction_complete": False})
    grant = P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
    )
    results = DEFAULT_COACHING_METRIC_ENGINE.compute(
        context,
        grant,
        pack_key=COACHING_METRIC_PACK_KEY,
        pack_version=COACHING_METRIC_PACK_VERSION,
    )
    assert all(result.value_state is MetricValueState.ABSTAINED for result in results)
    assert all(result.observation.numeric_value is None for result in results)
    assert {result.explanation_code for result in results} == {
        "source_extraction_incomplete"
    }
