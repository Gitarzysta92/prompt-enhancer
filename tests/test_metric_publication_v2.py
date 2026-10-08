"""Synthetic tests for the canonical V2 metric publication seam."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
    metric_contract_v2,
)
from prompt_enhancer.application.analysis.metric_guidance import (
    GuidanceBasis,
    GuidanceFactorEvidence,
    GuidanceStateClass,
    ValueOrigin,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    LiveMetricStateProjectionV2,
    MetricStateV2,
    V1CompatibilityMetricStateProjectionV2,
    project_metric_states_v2,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    METRIC_PUBLICATION_V2_KEY,
    REASON_DENOMINATOR_NOT_OPPORTUNITY_OWNED,
    REASON_MODEL_ASSISTED_NOT_PUBLISHABLE,
    REASON_RESULT_ABSENT,
    REASON_RESULT_STATE_UNPUBLISHABLE,
    REASON_PROVENANCE_INCOMPATIBLE,
    REASON_RUBRIC_DENOMINATOR_MISMATCH,
    MetricImplementationState,
    MetricPublicationSource,
    MetricPublicationV2,
    publish_metric_states_v2,
    publish_v1_compatibility_preview,
    rehydrate_v1_compatibility_states,
    v1_provenance_is_compatible,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    OBJECTIVE_EVIDENCE_METRIC_KEYS,
    ObjectiveMetricOverride,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_RUBRIC_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    TEXT_METRIC_SCHEMA_VERSION,
    EphemeralRedactedMessage,
    MetricDirection,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.persistence import (
    MetricValueState,
    SessionAnalysisResultRecord,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
)
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
)


NOW = datetime(2040, 3, 4, 9, 0, tzinfo=UTC)
OBJECTIVE_KEYS = frozenset(OBJECTIVE_EVIDENCE_METRIC_KEYS)
RUBRIC_KEYS = (
    "prompt.task_definition_coverage",
    "prompt.problem_evidence_quality",
    "prompt.context_sufficiency",
)


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-publication:{label}".encode()).hexdigest()


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
            "\x1f".join((namespace, *values, secret.get_secret_value())).encode()
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
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=_id(label),
        sequence=sequence,
        role=role,
        kind=kind,
        language=language,
        text=SecretStr(text),
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    *,
    label: str,
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
        text_extraction_complete=True,
        available_message_kinds=frozenset(message.kind for message in messages),
        analysis_window_fingerprint=_id(f"window:{label}"),
        focus_message_id=focus.message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=TextTaskProfile(applicability=()),
    )


def _result(
    key: str,
    *,
    value_state: MetricValueState = MetricValueState.KNOWN,
    numerator: int | None = 2,
    denominator: int | None = 3,
    explanation_code: str = "rubric_factors",
    error_code: str | None = None,
    model_id: str | None = None,
    version: int | None = None,
    unit: str | None = None,
    source: MetricSource = MetricSource.DETERMINISTIC,
    direction_override: SessionMetricDirection | None = None,
    metric_schema_version: int = TEXT_METRIC_SCHEMA_VERSION,
    algorithm_id: str = COACHING_METRIC_ALGORITHM_ID,
    algorithm_version: str = COACHING_METRIC_ALGORITHM_VERSION,
    rubric_version: str | None = COACHING_METRIC_RUBRIC_VERSION,
    prompt_version: str | None = None,
    evidence_data_tier: DataTier = DataTier.REDACTED_CONTENT,
) -> SessionAnalysisResultRecord:
    known = value_state is MetricValueState.KNOWN
    definition = next(
        item for item in COACHING_METRIC_DEFINITIONS if item.key == key
    )
    version = definition.version if version is None else version
    unit = definition.unit if unit is None else unit
    direction = (
        SessionMetricDirection.HIGHER_IS_BETTER
        if definition.direction is MetricDirection.HIGHER_IS_BETTER
        else SessionMetricDirection.LOWER_IS_BETTER
    )
    if direction_override is not None:
        direction = direction_override
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key=key,
            version=version,
            numeric_value=(
                None
                if not known or numerator is None or denominator is None
                else numerator / denominator
            ),
            unit=unit,
            source=source,
            observed_count=3,
            eligible_count=3,
            coverage=1.0,
        ),
        value_state=value_state,
        direction=direction,
        applicability=(
            SessionMetricApplicability.APPLICABLE
            if value_state is not MetricValueState.NOT_APPLICABLE
            else SessionMetricApplicability.NOT_APPLICABLE
        ),
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=metric_schema_version,
        evidence_data_tier=evidence_data_tier,
        fraction_numerator=numerator if known else None,
        fraction_denominator=denominator if known else None,
        explanation_code=explanation_code,
        error_code=error_code,
        algorithm_id=algorithm_id,
        algorithm_version=algorithm_version,
        rubric_version=rubric_version,
        prompt_version=prompt_version,
        model_id=model_id,
        model_revision=None if model_id is None else "0" * 40,
        model_license=None if model_id is None else "example-license-1.0",
        tokenizer_id=None if model_id is None else "example/local-tokenizer",
        computed_at=NOW,
    )


def _by_key(publication: MetricPublicationV2) -> dict[str, object]:
    return {item.state.metric_key: item for item in publication.metrics}


def _publish(results, **kwargs) -> MetricPublicationV2:
    return publish_v1_compatibility_preview(results, **kwargs)


def test_publication_always_lists_every_metric_in_registry_order() -> None:
    publication = _publish(())

    assert publication.publication_key == METRIC_PUBLICATION_V2_KEY
    assert len(publication.metrics) == len(METRIC_CONTRACTS_V2) == 20
    assert tuple(item.state.metric_key for item in publication.metrics) == tuple(
        contract.metric_key for contract in METRIC_CONTRACTS_V2
    )
    # An empty run is entirely unknown, never a wall of zeroes.
    assert publication.known_count == 0
    assert publication.unknown_count == 20
    assert all(item.state.numeric_value is None for item in publication.metrics)
    assert all(item.guidance.numerator is None for item in publication.metrics)
    assert all(
        item.guidance.basis is GuidanceBasis.READINESS
        for item in publication.metrics
    )


def test_absent_result_is_unknown_with_a_fixed_reason_not_zero() -> None:
    publication = _publish((_result("prompt.task_definition_coverage", numerator=3),))
    by_key = _by_key(publication)

    published = by_key["prompt.task_definition_coverage"]
    missing = by_key["prompt.context_sufficiency"]

    assert published.state.value_state is MetricValueStateV2.KNOWN
    assert missing.state.value_state is MetricValueStateV2.UNKNOWN
    assert missing.state.explanation_code == REASON_RESULT_ABSENT
    assert missing.state.statistics.eligible_count == 0
    assert missing.guidance.state_class is GuidanceStateClass.EVIDENCE_UNRESOLVED


def test_rubric_result_republishes_only_with_the_reviewed_factor_denominator() -> None:
    aligned = metric_contract_v2("prompt.task_definition_coverage")
    assert len(aligned.factors) == 3

    publication = _publish(
        (
            _result("prompt.task_definition_coverage", numerator=2, denominator=3),
            _result("prompt.context_sufficiency", numerator=5, denominator=9),
        )
    )
    by_key = _by_key(publication)

    good = by_key["prompt.task_definition_coverage"]
    assert good.state.value_state is MetricValueStateV2.KNOWN
    assert (good.state.numerator, good.state.denominator) == (2, 3)
    assert good.state.numeric_value == pytest.approx(2 / 3)
    assert good.state.statistics.met_count == 2
    assert good.state.statistics.not_met_count == 1
    assert good.guidance.state_class is GuidanceStateClass.KNOWN_IMPROVE
    # An aggregate rubric fraction proves a count, never a factor identity.
    assert good.guidance.basis is GuidanceBasis.METHOD_ONLY
    assert good.guidance.factor_evidence is GuidanceFactorEvidence.AGGREGATE_ONLY
    assert good.guidance.focus_factor_keys == ()
    assert good.implementation_state is (
        MetricImplementationState.COMPATIBILITY_PROJECTED
    )

    mismatched = by_key["prompt.context_sufficiency"]
    assert mismatched.state.value_state is MetricValueStateV2.UNKNOWN
    assert mismatched.state.explanation_code == REASON_RUBRIC_DENOMINATOR_MISMATCH


def test_lexical_v1_denominators_never_become_owned_opportunities() -> None:
    withheld_keys = tuple(
        contract.metric_key
        for contract in METRIC_CONTRACTS_V2
        if contract.metric_key not in OBJECTIVE_KEYS
        and contract.metric_key not in RUBRIC_KEYS
    )
    assert len(withheld_keys) == 12

    publication = _publish(
        tuple(_result(metric_key, numerator=1, denominator=1) for metric_key in withheld_keys)
    )
    by_key = _by_key(publication)

    for metric_key in withheld_keys:
        published = by_key[metric_key]
        assert published.state.value_state is MetricValueStateV2.UNKNOWN, metric_key
        assert published.state.explanation_code == (
            REASON_DENOMINATOR_NOT_OPPORTUNITY_OWNED
        )
        assert published.state.numeric_value is None


def test_objective_lane_is_fail_closed_against_stored_conversational_ratios() -> None:
    publication = _publish(
        tuple(
            _result(metric_key, numerator=1, denominator=1)
            for metric_key in sorted(OBJECTIVE_KEYS)
        )
    )
    by_key = _by_key(publication)

    assert publication.objective_measured_count == 0
    for metric_key in OBJECTIVE_KEYS:
        published = by_key[metric_key]
        assert published.state.value_state is MetricValueStateV2.UNKNOWN, metric_key
        assert published.state.explanation_code == "typed_objective_absent"
        assert published.state.evidence_authority is (
            EvidenceAuthority.OBJECTIVE_RECEIPT
        )
        assert published.guidance.state_class is (
            GuidanceStateClass.OBJECTIVE_EVIDENCE_MISSING
        )


def test_typed_evidence_lane_is_the_only_objective_publisher() -> None:
    publication = _publish(
        (),
        objective_overrides={
            "outcome.verified_requirement_coverage": ObjectiveMetricOverride(
                value_state=MetricValueState.KNOWN,
                explanation_code="typed_requirement_verification_links",
                numerator=2,
                denominator=2,
                resolved_opportunity_count=2,
                eligible_opportunity_count=2,
                met_opportunity_count=2,
            ),
            "outcome.first_pass_verification": ObjectiveMetricOverride(
                value_state=MetricValueState.UNKNOWN,
                explanation_code="typed_first_verification_unresolved",
                resolved_opportunity_count=1,
                eligible_opportunity_count=3,
                met_opportunity_count=1,
            ),
        },
    )
    by_key = _by_key(publication)

    covered = by_key["outcome.verified_requirement_coverage"]
    assert covered.state.value_state is MetricValueStateV2.KNOWN
    assert covered.guidance.basis is GuidanceBasis.MEASURED
    assert covered.guidance.value_origin is ValueOrigin.TYPED_OBJECTIVE
    assert covered.guidance.state_class is GuidanceStateClass.KNOWN_RETAIN
    assert publication.objective_measured_count == 1

    censored = by_key["outcome.first_pass_verification"]
    assert censored.state.value_state is MetricValueStateV2.PENDING
    assert censored.state.numeric_value is None
    assert censored.state.censoring_lower_bound == pytest.approx(1 / 3)
    assert censored.state.censoring_upper_bound == pytest.approx(1.0)
    assert censored.guidance.state_class is GuidanceStateClass.PENDING_CLOSURE


def test_model_assisted_result_cannot_publish_a_value() -> None:
    publication = _publish(
        (
            _result(
                "prompt.task_definition_coverage",
                numerator=3,
                denominator=3,
                model_id="example/local-rubric",
            ),
        )
    )
    published = _by_key(publication)["prompt.task_definition_coverage"]

    assert published.state.value_state is MetricValueStateV2.UNKNOWN
    assert published.state.explanation_code == (
        REASON_MODEL_ASSISTED_NOT_PUBLISHABLE
    )
    assert published.state.explanation_code == REASON_PROVENANCE_INCOMPATIBLE
    assert published.guidance.basis is GuidanceBasis.READINESS
    assert published.guidance.value_origin is ValueOrigin.NONE


def test_optional_neural_failure_preserves_its_code_without_blocking_others() -> None:
    publication = _publish(
        (
            # An optional local rubric stage timed out for one metric only.
            _result(
                "prompt.problem_evidence_quality",
                value_state=MetricValueState.EXECUTION_ERROR,
                numerator=None,
                denominator=None,
                explanation_code="model_committee_nli_failed",
                error_code="model_committee_nli_failed",
                model_id="example/local-rubric",
            ),
            _result("prompt.task_definition_coverage", numerator=3, denominator=3),
        ),
        objective_overrides={
            "outcome.agent_claim_grounding": ObjectiveMetricOverride(
                value_state=MetricValueState.KNOWN,
                explanation_code="typed_claim_grounding_links",
                numerator=1,
                denominator=1,
                resolved_opportunity_count=1,
                eligible_opportunity_count=1,
                met_opportunity_count=1,
            ),
        },
    )
    by_key = _by_key(publication)

    # A model-assisted row is provenance-incompatible, so the preview never
    # claims it consumed a model committee outcome for this metric.
    failed = by_key["prompt.problem_evidence_quality"]
    assert failed.state.value_state is MetricValueStateV2.UNKNOWN
    assert failed.state.explanation_code == REASON_PROVENANCE_INCOMPATIBLE
    assert publication.model_stage_consumed is False

    # The deterministic and objective results still publish normally.
    assert (
        by_key["prompt.task_definition_coverage"].state.value_state
        is MetricValueStateV2.KNOWN
    )
    assert (
        by_key["outcome.agent_claim_grounding"].state.value_state
        is MetricValueStateV2.KNOWN
    )
    assert publication.execution_error_count == 0
    assert publication.known_count == 2
    assert len(publication.metrics) == 20


def test_duplicated_stored_metric_rows_are_ambiguous_not_averaged() -> None:
    publication = _publish(
        (
            _result("prompt.task_definition_coverage", numerator=3, denominator=3),
            _result("prompt.task_definition_coverage", numerator=0, denominator=3),
        )
    )
    published = _by_key(publication)["prompt.task_definition_coverage"]

    assert published.state.value_state is MetricValueStateV2.UNKNOWN
    assert published.state.explanation_code == REASON_RESULT_STATE_UNPUBLISHABLE


def test_stored_not_applicable_and_abstained_states_are_preserved() -> None:
    publication = _publish(
        (
            _result(
                "prompt.task_definition_coverage",
                value_state=MetricValueState.NOT_APPLICABLE,
                numerator=None,
                denominator=None,
                explanation_code="no_opportunity_observed",
            ),
            _result(
                "prompt.context_sufficiency",
                value_state=MetricValueState.ABSTAINED,
                numerator=None,
                denominator=None,
                explanation_code="message_kind_unavailable",
            ),
        )
    )
    by_key = _by_key(publication)

    not_applicable = by_key["prompt.task_definition_coverage"]
    assert not_applicable.state.value_state is MetricValueStateV2.NOT_APPLICABLE
    assert not_applicable.guidance.state_class is GuidanceStateClass.NO_OPPORTUNITY

    abstained = by_key["prompt.context_sufficiency"]
    assert abstained.state.value_state is MetricValueStateV2.ABSTAINED
    assert abstained.state.explanation_code == "message_kind_unavailable"
    assert abstained.guidance.state_class is (
        GuidanceStateClass.EVIDENCE_COVERAGE_ABSTAINED
    )
    # A diagnostic intent cannot be proved absent, so V2 keeps it unknown.
    assert by_key["prompt.problem_evidence_quality"].state.value_state is (
        MetricValueStateV2.UNKNOWN
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
def test_live_projection_publishes_identical_guidance_for_en_and_pl(
    language: TextLanguage,
    request_text: str,
    response_text: str,
) -> None:
    context = _context(
        (
            _message(
                "live-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                request_text,
                language=language,
            ),
            _message(
                "live-response",
                2,
                TextRole.AGENT,
                TextMessageKind.RESPONSE,
                response_text,
                language=language,
            ),
        ),
        label=f"live-{language.value}",
    )
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation

    publication = publish_metric_states_v2(
        project_metric_states_v2(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )
    by_key = _by_key(publication)

    assert publication.source is MetricPublicationSource.LIVE_PROJECTION
    assert len(publication.metrics) == 20
    strategy = by_key["outcome.verification_strategy_adequacy"]
    assert strategy.state.value_state is MetricValueStateV2.KNOWN
    assert strategy.state.numerator == 1 and strategy.state.denominator == 1
    assert strategy.guidance.state_class is GuidanceStateClass.KNOWN_RETAIN
    # A deterministic local rule is a measured observation, not an estimate.
    assert strategy.guidance.basis is GuidanceBasis.MEASURED
    assert strategy.guidance.value_origin is ValueOrigin.DETERMINISTIC_LOCAL
    assert strategy.implementation_state is MetricImplementationState.LIVE_MEASURED
    assert strategy.guidance.action_template_id == (
        "action.retain.outcome.verification_strategy_adequacy.v1"
    )
    # A stated strategy is conversational, so it never becomes objective proof.
    assert publication.objective_measured_count == 0


def test_publication_rejects_incomplete_or_reordered_metric_sets() -> None:
    publication = _publish(())
    payload = publication.model_dump()

    with pytest.raises(ValidationError, match="at least 20 items"):
        MetricPublicationV2.model_validate(
            {
                **payload,
                "metrics": payload["metrics"][:19],
                "unknown_count": 19,
            }
        )

    reversed_metrics = list(reversed(payload["metrics"]))
    with pytest.raises(ValidationError, match="registry order"):
        MetricPublicationV2.model_validate(
            {**payload, "metrics": reversed_metrics}
        )

    with pytest.raises(ValidationError, match="counts are inconsistent"):
        MetricPublicationV2.model_validate({**payload, "unknown_count": 3})

    with pytest.raises(ValidationError, match="fingerprint is stale"):
        MetricPublicationV2.model_validate(
            {**payload, "contract_set_fingerprint": "c" * 64}
        )


def test_publication_serialization_is_content_free() -> None:
    payload = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    ).model_dump_json()

    lowered = payload.casefold()
    for prohibited in (
        "prompt_text",
        "excerpt",
        "filesystem_path",
        "raw_content",
        "session_id",
        "message_id",
    ):
        assert prohibited not in lowered
    assert all(
        item.state.product_metric_eligible is False
        for item in _publish(()).metrics
    )


def test_every_v1_provenance_field_tamper_withholds_the_value() -> None:
    compatible = _result(
        "prompt.task_definition_coverage", numerator=3, denominator=3
    )
    assert v1_provenance_is_compatible(compatible)
    assert (
        _publish((compatible,))
        .metrics[0]
        .state.value_state
        is MetricValueStateV2.KNOWN
    )

    tampers = {
        "version": {"version": 9},
        "unit": {"unit": "risk_ratio"},
        "source": {"source": MetricSource.ESTIMATED},
        "direction": {
            "direction_override": SessionMetricDirection.LOWER_IS_BETTER
        },
        "metric_schema_version": {
            "metric_schema_version": TEXT_METRIC_SCHEMA_VERSION + 1
        },
        "algorithm_id": {"algorithm_id": "rules.en-pl.other-pack"},
        "algorithm_version": {"algorithm_version": "3"},
        "rubric_version": {"rubric_version": "coaching-observables-rubric-1"},
        "rubric_version_absent": {"rubric_version": None},
        "prompt_version_with_model": {
            "model_id": "example/local-rubric",
            "prompt_version": "example-prompt-1",
        },
        "model_id": {"model_id": "example/local-rubric"},
    }
    for label, override in tampers.items():
        tampered = _result(
            "prompt.task_definition_coverage",
            numerator=3,
            denominator=3,
            **override,
        )
        assert not v1_provenance_is_compatible(tampered), label
        published = _by_key(_publish((tampered,)))[
            "prompt.task_definition_coverage"
        ]
        assert published.state.value_state is MetricValueStateV2.UNKNOWN, label
        assert published.state.explanation_code == (
            REASON_PROVENANCE_INCOMPATIBLE
        ), label
        assert published.state.numeric_value is None, label


def test_orphan_metric_key_is_never_promoted() -> None:
    orphan = _result("prompt.task_definition_coverage", numerator=3, denominator=3)
    orphan = orphan.model_copy(
        update={
            "observation": orphan.observation.model_copy(
                update={"key": "prompt.unreviewed_candidate"}
            )
        }
    )

    assert not v1_provenance_is_compatible(orphan)
    publication = _publish((orphan,))
    assert publication.known_count == 0
    assert publication.unknown_count == 20


def test_publication_rejects_a_forged_state_or_guidance_field() -> None:
    baseline = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )
    payload = baseline.model_dump()
    metrics = list(payload["metrics"])
    objective_index = next(
        position
        for position, item in enumerate(metrics)
        if item["state"]["metric_key"] == "outcome.first_pass_verification"
    )

    def _reject(index: int, mutate, match: str, **counts: int) -> None:
        forged = [dict(item) for item in metrics]
        forged[index] = mutate(
            {
                "state": dict(forged[index]["state"]),
                "guidance": dict(forged[index]["guidance"]),
                "implementation_state": forged[index]["implementation_state"],
            }
        )
        with pytest.raises(ValidationError, match=match):
            MetricPublicationV2.model_validate(
                {**payload, "metrics": forged, **counts}
            )

    def _forge_fingerprint(item):
        item["state"]["contract_fingerprint"] = "d" * 64
        return item

    def _forge_authority(item):
        item["state"]["evidence_authority"] = "conversation"
        return item

    def _forge_denominator_basis(item):
        item["state"]["statistics"] = {
            **item["state"]["statistics"],
            "denominator_basis": "rubric_factors",
        }
        return item

    def _forge_opportunity_kind(item):
        item["state"]["statistics"] = {
            **item["state"]["statistics"],
            "opportunity_unit_kind": "requirement",
        }
        return item

    def _forge_guidance_authority(item):
        item["guidance"]["evidence_authority"] = "conversation"
        return item

    def _forge_guidance_metric_version(item):
        item["guidance"]["metric_version"] = 99
        return item

    def _forge_guidance_factor_count(item):
        item["guidance"]["contract_factor_count"] = 8
        return item

    def _forge_contract_version(item):
        item["state"]["contract_version"] = "probabilistic-metric-contract-v1"
        return item

    _reject(objective_index, _forge_fingerprint, "fingerprint is forged")
    _reject(objective_index, _forge_authority, "evidence authority is forged")
    _reject(objective_index, _forge_denominator_basis, "denominator basis is forged")
    _reject(objective_index, _forge_opportunity_kind, "opportunity unit kind is forged")
    _reject(objective_index, _forge_guidance_authority, "evidence authority is forged")
    _reject(0, _forge_guidance_metric_version, "metric version is forged")
    _reject(0, _forge_guidance_factor_count, "factor count is forged")
    _reject(objective_index, _forge_contract_version, "contract version does not match")


def test_objective_metric_cannot_be_laundered_from_conversational_material() -> None:
    payload = _publish(()).model_dump()
    metrics = [dict(item) for item in payload["metrics"]]
    index = next(
        position
        for position, item in enumerate(metrics)
        if item["state"]["metric_key"] == "outcome.first_pass_verification"
    )
    state = dict(metrics[index]["state"])
    guidance = dict(metrics[index]["guidance"])
    state.update(
        value_state="known",
        numerator=1,
        denominator=1,
        numeric_value=1.0,
        censoring_lower_bound=1.0,
        censoring_upper_bound=1.0,
        statistics={
            **state["statistics"],
            "denominator_basis": "rubric_factors",
            "capability_available": True,
            "eligible_count": 1,
            "met_count": 1,
        },
    )
    guidance.update(
        value_state="known",
        state_class="known_retain",
        basis="measured",
        value_origin="typed_objective",
        numerator=1,
        denominator=1,
        eligible_count=1,
        met_count=1,
    )
    metrics[index] = {
        "state": state,
        "guidance": guidance,
        "implementation_state": "compatibility_projected",
    }

    with pytest.raises(ValidationError):
        MetricPublicationV2.model_validate(
            {
                **payload,
                "metrics": metrics,
                "known_count": 1,
                "unknown_count": 19,
                "objective_measured_count": 1,
            }
        )


def test_probabilistic_deep_timeout_leaves_deterministic_measurements_intact() -> None:
    """Real-shaped optional deep stage timeout: a separate, model-owned row."""

    deterministic = _result(
        "prompt.task_definition_coverage", numerator=3, denominator=3
    )
    deep_timeout = _result(
        "prompt.context_sufficiency",
        value_state=MetricValueState.EXECUTION_ERROR,
        numerator=None,
        denominator=None,
        explanation_code="probabilistic_deep_timeout",
        error_code="probabilistic_deep_timeout",
        model_id="example/local-deep-rubric",
        prompt_version="example-deep-prompt-1",
    )

    publication = _publish((deterministic, deep_timeout))
    by_key = _by_key(publication)

    # The deterministic measurement is untouched by the optional stage failure.
    measured = by_key["prompt.task_definition_coverage"]
    assert measured.state.value_state is MetricValueStateV2.KNOWN
    assert measured.state.numerator == 3 and measured.state.denominator == 3

    # The preview does not claim to have consumed the deep stage at all.
    assert publication.model_stage_consumed is False
    assert publication.execution_error_count == 0
    timed_out = by_key["prompt.context_sufficiency"]
    assert timed_out.state.value_state is MetricValueStateV2.UNKNOWN
    assert timed_out.state.explanation_code == REASON_PROVENANCE_INCOMPATIBLE
    assert timed_out.implementation_state is (
        MetricImplementationState.METHOD_ONLY_WITHHELD
    )
    assert len(publication.metrics) == 20


def test_implementation_states_partition_the_twenty_metrics() -> None:
    publication = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),),
        objective_overrides={
            "outcome.agent_claim_grounding": ObjectiveMetricOverride(
                value_state=MetricValueState.KNOWN,
                explanation_code="typed_claim_grounding_links",
                numerator=1,
                denominator=1,
                resolved_opportunity_count=1,
                eligible_opportunity_count=1,
                met_opportunity_count=1,
            ),
        },
    )
    counts = publication.implementation_state_counts()

    assert sum(counts.values()) == 20
    assert counts[MetricImplementationState.COMPATIBILITY_PROJECTED] == 2
    assert counts[MetricImplementationState.LIVE_MEASURED] == 0
    assert counts[MetricImplementationState.OBJECTIVE_CAPABILITY_MISSING] == 4
    assert counts[MetricImplementationState.OBJECTIVE_EVIDENCE_UNRESOLVED] == 0
    assert counts[MetricImplementationState.METHOD_ONLY_WITHHELD] == 14
    assert publication.compatibility_preview is True
    assert publication.canonical_live_snapshot is False


def test_compatibility_preview_cannot_claim_a_live_measurement() -> None:
    payload = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    ).model_dump()
    metrics = [dict(item) for item in payload["metrics"]]
    metrics[0] = {**metrics[0], "implementation_state": "live_measured"}

    with pytest.raises(ValidationError, match="live measurement"):
        MetricPublicationV2.model_validate({**payload, "metrics": metrics})


def test_focus_factors_are_empty_for_aggregate_only_compatibility_rows() -> None:
    publication = _publish(
        tuple(
            _result(
                metric_key,
                numerator=len(metric_contract_v2(metric_key).factors),
                denominator=len(metric_contract_v2(metric_key).factors),
            )
            for metric_key in RUBRIC_KEYS
        )
    )

    known = [
        item
        for item in publication.metrics
        if item.state.value_state is MetricValueStateV2.KNOWN
    ]
    assert len(known) == 3
    for item in known:
        assert item.guidance.focus_factor_keys == ()
        assert item.guidance.factor_evidence is (
            GuidanceFactorEvidence.AGGREGATE_ONLY
        )
        assert item.guidance.basis is GuidanceBasis.METHOD_ONLY
        # The complete factor catalog stays metadata, not session advice.
        assert item.guidance.contract_factor_count >= 3


def _forged(publication, index, mutate, **counts):
    payload = publication.model_dump()
    metrics = [dict(item) for item in payload["metrics"]]
    metrics[index] = mutate(
        {
            "state": dict(metrics[index]["state"]),
            "guidance": dict(metrics[index]["guidance"]),
            "implementation_state": metrics[index]["implementation_state"],
        }
    )
    return {**payload, "metrics": metrics, **counts}


def test_known_value_must_equal_its_sufficient_statistics() -> None:
    baseline = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )

    def _empty_stats(item):
        item["state"]["statistics"] = {
            **item["state"]["statistics"],
            "eligible_count": 0,
            "met_count": 0,
            "not_met_count": 0,
        }
        return item

    def _numerator_drift(item):
        item["state"]["statistics"] = {
            **item["state"]["statistics"],
            "met_count": 1,
            "not_met_count": 2,
        }
        return item

    def _leftover_pending(item):
        stats = {
            **item["state"]["statistics"],
            "eligible_count": 4,
            "met_count": 3,
            "not_met_count": 0,
            "pending_count": 1,
        }
        item["state"]["statistics"] = stats
        return item

    def _leftover_unknown(item):
        stats = {
            **item["state"]["statistics"],
            "eligible_count": 4,
            "met_count": 3,
            "not_met_count": 0,
            "unknown_count": 1,
        }
        item["state"]["statistics"] = stats
        return item

    def _incomplete_source(item):
        item["state"]["statistics"] = {
            **item["state"]["statistics"],
            "source_complete": False,
        }
        return item

    # A forged 3/3 beside an empty opportunity set is exactly a masked zero.
    for mutate, match in (
        (_empty_stats, "eligible opportunit"),
        (_numerator_drift, "met opportunities"),
        # A partition-valid statistic cannot both balance and leave a residue,
        # so these forgeries are caught by the denominator/numerator binding.
        (_leftover_pending, "eligible opportunit"),
        (_leftover_unknown, "eligible opportunit"),
        (_incomplete_source, "complete source"),
    ):
        with pytest.raises(ValidationError, match=match):
            MetricPublicationV2.model_validate(_forged(baseline, 0, mutate))


def test_guidance_cannot_be_supplied_independently_of_the_state() -> None:
    baseline = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )

    def _swap_reason(item):
        item["guidance"]["reason_code"] = "no_opportunity_observed"
        return item

    def _swap_audience(item):
        item["guidance"]["audience"] = "tooling"
        return item

    def _swap_role(item):
        item["guidance"]["role"] = "friction_signal"
        return item

    def _swap_state_class(item):
        item["guidance"]["state_class"] = "known_improve"
        item["guidance"]["action_template_id"] = (
            "action.improve.prompt.task_definition_coverage.v1"
        )
        return item

    def _swap_template(item):
        item["guidance"]["verification_template_id"] = (
            "verification.review_evidence_coverage.v1"
        )
        return item

    def _swap_diagnosis(item):
        item["guidance"]["diagnosis_template_id"] = (
            "diagnosis.prompt.context_sufficiency.v1"
        )
        return item

    def _claim_measured(item):
        item["guidance"]["basis"] = "measured"
        item["guidance"]["factor_evidence"] = "not_observed"
        return item

    def _claim_neural(item):
        item["guidance"]["basis"] = "experimental"
        item["guidance"]["value_origin"] = "neural_uncalibrated"
        return item

    def _swap_counts(item):
        item["guidance"]["met_count"] = 2
        item["guidance"]["not_met_count"] = 1
        return item

    def _swap_implementation(item):
        item["implementation_state"] = "abstained"
        return item

    for mutate in (
        _swap_reason,
        _swap_audience,
        _swap_role,
        _swap_state_class,
        _swap_template,
        _swap_diagnosis,
        _claim_measured,
        _swap_counts,
    ):
        with pytest.raises(ValidationError):
            MetricPublicationV2.model_validate(_forged(baseline, 0, mutate))

    # A preview consumes no model stage, so a neural claim is always rejected.
    with pytest.raises(ValidationError):
        MetricPublicationV2.model_validate(_forged(baseline, 0, _claim_neural))

    with pytest.raises(ValidationError):
        MetricPublicationV2.model_validate(_forged(baseline, 0, _swap_implementation))


def test_forged_nonempty_focus_factors_are_rejected() -> None:
    baseline = _publish(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )

    def _claim_focus(item):
        item["guidance"]["factor_evidence"] = "per_factor_measured"
        item["guidance"]["focus_factor_keys"] = ["action"]
        item["guidance"]["basis"] = "measured"
        return item

    with pytest.raises(ValidationError):
        MetricPublicationV2.model_validate(_forged(baseline, 0, _claim_focus))

    # No producer in this tree measures per-factor statistics.
    assert all(
        item.guidance.focus_factor_keys == ()
        and item.guidance.factor_evidence
        is not GuidanceFactorEvidence.PER_FACTOR_MEASURED
        for item in baseline.metrics
    )


def test_partial_authorized_objective_evidence_is_unresolved_not_missing() -> None:
    publication = _publish(
        (),
        objective_overrides={
            # A receipt exists and resolves two of three claims.
            "outcome.agent_claim_grounding": ObjectiveMetricOverride(
                value_state=MetricValueState.UNKNOWN,
                explanation_code="typed_claim_grounding_unresolved",
                resolved_opportunity_count=2,
                eligible_opportunity_count=3,
                met_opportunity_count=1,
            ),
        },
    )
    by_key = _by_key(publication)

    unresolved = by_key["outcome.agent_claim_grounding"]
    missing = by_key["outcome.verified_requirement_coverage"]

    assert unresolved.state.value_state is MetricValueStateV2.UNKNOWN
    assert unresolved.state.statistics.capability_available is True
    assert unresolved.state.statistics.eligible_count == 3
    assert unresolved.implementation_state is (
        MetricImplementationState.OBJECTIVE_EVIDENCE_UNRESOLVED
    )
    assert unresolved.guidance.state_class is (
        GuidanceStateClass.OBJECTIVE_EVIDENCE_UNRESOLVED
    )
    # Advising collection of a receipt that already exists would be false.
    assert unresolved.guidance.action_template_id == (
        "action.resolve_objective_evidence.v1"
    )
    assert unresolved.state.explanation_code == "opportunity_classification_unknown"
    assert unresolved.state.censoring_lower_bound is not None

    assert missing.implementation_state is (
        MetricImplementationState.OBJECTIVE_CAPABILITY_MISSING
    )
    assert missing.guidance.action_template_id == (
        "action.collect_objective_receipt.v1"
    )


def test_publication_source_is_derived_from_the_producer_envelope() -> None:
    compatible = rehydrate_v1_compatibility_states(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )

    context = _context(
        (
            _message(
                "origin-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Implement the fictional widget export.",
            ),
        ),
        label="origin",
    )
    live = project_metric_states_v2(
        context=context,
        reconciliation=SemanticUnitReconciler(IDS).reconcile(context).reconciliation,
        id_factory=IDS,
    )
    preview = publish_metric_states_v2(compatible)
    snapshot = publish_metric_states_v2(live)
    assert preview.compatibility_preview is True
    assert snapshot.compatibility_preview is False
    assert (
        _by_key(preview)["prompt.task_definition_coverage"].implementation_state
        is MetricImplementationState.COMPATIBILITY_PROJECTED
    )
    assert all(
        item.implementation_state
        is not MetricImplementationState.COMPATIBILITY_PROJECTED
        for item in snapshot.metrics
    )


def test_model_copy_and_json_cannot_recreate_publication_authority() -> None:
    compatible = rehydrate_v1_compatibility_states(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )
    copied = tuple(state.model_copy() for state in compatible)
    reconstructed = tuple(
        MetricStateV2.model_validate(state.model_dump()) for state in compatible
    )

    with pytest.raises(TypeError, match="producer-issued"):
        publish_metric_states_v2(copied)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="producer-issued"):
        publish_metric_states_v2(reconstructed)  # type: ignore[arg-type]


def test_runtime_class_swap_cannot_change_the_bound_producer() -> None:
    compatible = rehydrate_v1_compatibility_states(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )
    compatible.__class__ = LiveMetricStateProjectionV2
    try:
        with pytest.raises(TypeError, match="class does not match"):
            publish_metric_states_v2(compatible)
    finally:
        compatible.__class__ = V1CompatibilityMetricStateProjectionV2

    context = _context(
        (
            _message(
                "class-swap-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Review the fictional widget export.",
            ),
        ),
        label="class-swap-live",
    )
    live = project_metric_states_v2(
        context=context,
        reconciliation=SemanticUnitReconciler(IDS).reconcile(context).reconciliation,
        id_factory=IDS,
    )
    live.__class__ = V1CompatibilityMetricStateProjectionV2
    try:
        with pytest.raises(TypeError, match="class does not match"):
            publish_metric_states_v2(live)
    finally:
        live.__class__ = LiveMetricStateProjectionV2


def test_private_envelope_storage_replacement_invalidates_authority() -> None:
    compatible = rehydrate_v1_compatibility_states(
        (_result("prompt.task_definition_coverage", numerator=3, denominator=3),)
    )
    context = _context(
        (
            _message(
                "storage-swap-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Inspect the fictional widget receipt.",
            ),
        ),
        label="storage-swap-live",
    )
    live = project_metric_states_v2(
        context=context,
        reconciliation=SemanticUnitReconciler(IDS).reconcile(context).reconciliation,
        id_factory=IDS,
    )
    original = live._issued_state_tuple()
    live._MetricStateProjectionV2__states = tuple(compatible)  # type: ignore[attr-defined]
    try:
        with pytest.raises(TypeError, match="producer-issued"):
            publish_metric_states_v2(live)
    finally:
        live._MetricStateProjectionV2__states = original  # type: ignore[attr-defined]
