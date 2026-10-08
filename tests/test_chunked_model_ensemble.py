from __future__ import annotations

import builtins
import os
import sys
import time

from pydantic import SecretStr, ValidationError
import pytest

from prompt_enhancer.application.analysis.model_ensemble import (
    ChunkMetricCommitteeReceipt,
    MODEL_ENSEMBLE_MAX_CHUNKS,
    ModelExpertRole,
    ModelMetricVote,
    ModelVoteState,
    SourceCoverageState,
    aggregate_chunk_metrics,
    build_ensemble_chunks,
    coaching_ensemble_metric_specs,
    committee_chunk_receipt,
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
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.text_models.model_ensemble import (
    MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE,
    MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_ERROR_CODE,
    MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS,
    MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
    ModelEnsembleError,
    SerialModelEnsembleRunner,
    ensemble_expert_specs,
    run_ensemble_expert_subprocess,
)
from prompt_enhancer.infrastructure.text_models import (
    model_ensemble as model_ensemble_module,
)
from prompt_enhancer.infrastructure.text_models import (
    probabilistic_metrics as probabilistic_runtime_module,
)
from prompt_enhancer.infrastructure.text_models.probabilistic_metrics import (
    DISABLED_PROBABILISTIC_MODEL_KEYS,
    LocalProbabilisticMetricRunner,
    PROBABILISTIC_DEEP_TIMEOUT_ERROR_CODE,
    PROBABILISTIC_DEEP_TIMEOUT_SECONDS,
    _cuda_deep_lane_available,
    _draw_metric_samples,
    _has_sufficient_retained_samples,
)
from prompt_enhancer.application.analysis.probabilistic_metrics import (
    EVIDENCE_LANE_METRIC_KEYS,
    PROBABILISTIC_MIN_RETAINED_SAMPLE_RATE,
    PROBABILISTIC_METRIC_CONTRACTS,
    FactorScale,
    PredictiveFactorContribution,
    PredictiveMetricState,
    PredictiveMetricTarget,
    PredictiveModelStageReceipt,
)


def _digest(char: str) -> str:
    return char * 64


def _context(*, complete: bool = True) -> P1TextAnalysisInput:
    decisions = tuple(
        MetricApplicabilityDecision(
            metric_key=definition.key,
            applicability=MetricApplicability.APPLICABLE,
            basis=ApplicabilityBasis.USER_SELECTED,
        )
        for definition in COACHING_METRIC_DEFINITIONS
    )
    messages = tuple(
        EphemeralRedactedMessage(
            message_id=f"{index + 1:064x}",
            sequence=index,
            role=TextRole.USER if index % 2 == 0 else TextRole.AGENT,
            kind=(
                TextMessageKind.REQUEST
                if index % 2 == 0
                else TextMessageKind.RESPONSE
            ),
            language=TextLanguage.ENGLISH,
            text=SecretStr((f"fictional segment {index} " * 260)[:5_200]),
        )
        for index in range(16)
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_digest("a"),
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        text_extraction_complete=complete,
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.RESPONSE}
        ),
        analysis_window_fingerprint=_digest("b"),
        focus_message_id=messages[-2].message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=TextTaskProfile(applicability=decisions),
    )


def _vote(
    model: str,
    role: ModelExpertRole,
    state: ModelVoteState,
    *,
    chunk: int = 0,
    metric: str = "prompt.task_definition_coverage",
) -> ModelMetricVote:
    return ModelMetricVote(
        chunk_ordinal=chunk,
        metric_key=metric,
        model_key=model,
        role=role,
        state=state,
        raw_score=(1.0 if state is ModelVoteState.PRESENT else 0.0)
        if state in {ModelVoteState.PRESENT, ModelVoteState.ABSENT}
        else None,
        reason_code="synthetic_vote",
    )


def test_chunker_is_exhaustive_non_overlapping_and_bounded() -> None:
    context = _context()
    plan = build_ensemble_chunks(context)

    assert 1 < len(plan.chunks) <= MODEL_ENSEMBLE_MAX_CHUNKS
    assert plan.source_coverage_state is SourceCoverageState.COMPLETE_WINDOW
    assert plan.total_message_count == context.observed_message_count
    assert plan.total_character_count == sum(
        len(message.text.get_secret_value()) for message in context.messages
    )
    fragments = [item for chunk in plan.chunks for item in chunk.fragments]
    assert len({item.fragment_id for item in fragments}) == len(fragments)
    assert {item.source_message_id for item in fragments} == {
        item.message_id for item in context.messages
    }
    assert max(len(item.text.get_secret_value()) for item in fragments) <= 3_500
    assert {
        item.source_message_id
        for item in fragments
        if item.is_focus_message
    } == {context.focus_message_id}
    assert repr(plan).find("fictional segment") == -1


def test_chunker_invalidates_the_prior_focus_chunk_when_focus_moves() -> None:
    original = _context()
    original_plan = build_ensemble_chunks(original)
    appended_message = EphemeralRedactedMessage(
        message_id=f"{99:064x}",
        sequence=len(original.messages),
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(("fictional appended request " * 220)[:5_200]),
    )
    appended = original.model_copy(
        update={
            "messages": (*original.messages, appended_message),
            "focus_message_id": appended_message.message_id,
            "observed_message_count": original.observed_message_count + 1,
            "eligible_message_count": original.eligible_message_count + 1,
            "analysis_window_fingerprint": _digest("c"),
        }
    )
    appended_plan = build_ensemble_chunks(appended)

    assert len(original_plan.chunks) > 1
    for index, chunk in enumerate(original_plan.chunks[:-1]):
        contains_old_focus = any(
            fragment.source_message_id == original.focus_message_id
            for fragment in chunk.fragments
        )
        if contains_old_focus:
            assert chunk.chunk_fingerprint != appended_plan.chunks[index].chunk_fingerprint
        else:
            assert chunk.chunk_fingerprint == appended_plan.chunks[index].chunk_fingerprint
    assert (
        original_plan.chunks[-1].chunk_fingerprint
        != appended_plan.chunks[len(original_plan.chunks) - 1].chunk_fingerprint
    )
    assert original_plan.source_window_fingerprint != appended_plan.source_window_fingerprint


def test_incomplete_source_is_preserved_not_promoted_to_complete() -> None:
    plan = build_ensemble_chunks(_context(complete=False))
    assert plan.source_coverage_state is SourceCoverageState.INCOMPLETE_SOURCE


def test_all_twenty_metric_specs_are_versioned_and_distinct() -> None:
    specs = coaching_ensemble_metric_specs()
    assert len(specs) == len(COACHING_METRIC_DEFINITIONS) == 20
    assert len({item.metric_key for item in specs}) == 20
    assert all(item.retrieval_query and item.entailment_hypothesis and item.rubric for item in specs)
    assert {item.evidence_scope for item in specs} == {
        "focus_request",
        "conversation",
        "objective_evidence",
    }
    assert next(
        item for item in specs if item.metric_key == "logic.hypothesis_test_linkage"
    ).evidence_scope == "objective_evidence"


def test_live_probabilistic_runner_emits_behavioral_ranges_only() -> None:
    calls = []

    def execute(spec, stage, payload, device):
        calls.append((spec.identity.model_key, stage, device, len(payload["cases"])))
        rows = [
            {
                "case_id": item["case_id"],
                "entailment": 0.98,
                "neutral": 0.01,
                "contradiction": 0.01,
            }
            for item in payload["cases"]
        ]
        return {
            "status": "completed",
            "device": "cuda",
            "rows": rows,
            "runtime": {
                "inference_latency_ms": 125.0,
                "peak_cuda_allocated_mb": 1_100.0,
                "process_rss_after_load_and_inference_mb": 1_700.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert len(calls) == 3
    assert {call[1] for call in calls} == {"scope_nli"}
    assert all(call[3] <= 160 for call in calls)
    assert receipt.predictive_projection is not None
    projection = receipt.predictive_projection
    assert len(projection.metrics) == 20
    assert len(projection.model_stages) == 3
    assert all(
        item.state is PredictiveMetricState.UNAVAILABLE
        for item in projection.metrics
        if item.metric_key in EVIDENCE_LANE_METRIC_KEYS
    )
    behavioral = tuple(
        item
        for item in projection.metrics
        if item.metric_key not in EVIDENCE_LANE_METRIC_KEYS
        and next(
            contract
            for contract in PROBABILISTIC_METRIC_CONTRACTS
            if contract.metric_key == item.metric_key
        ).closure_horizon == "immediate"
        and not next(
            contract
            for contract in PROBABILISTIC_METRIC_CONTRACTS
            if contract.metric_key == item.metric_key
        ).objective_evidence_required
    )
    assert all(item.state is PredictiveMetricState.EXPERIMENTAL for item in behavioral)
    assert len(behavioral) == 8
    assert all(item.pending_probability == 0 for item in behavioral)
    assert all(len(item.density_bins) == 20 for item in behavioral)
    assert all(abs(sum(item.density_bins) - 1.0) < 1e-6 for item in behavioral)
    assert all(
        item.state is PredictiveMetricState.UNAVAILABLE
        for item in projection.metrics
        if next(
            contract
            for contract in PROBABILISTIC_METRIC_CONTRACTS
            if contract.metric_key == item.metric_key
        ).closure_horizon != "immediate"
        or next(
            contract
            for contract in PROBABILISTIC_METRIC_CONTRACTS
            if contract.metric_key == item.metric_key
        ).objective_evidence_required
    )
    assert next(
        item
        for item in projection.metrics
        if item.metric_key == "outcome.verified_requirement_coverage"
    ).target is PredictiveMetricTarget.OUTCOME_FORECAST
    verification_strategy = next(
        item
        for item in projection.metrics
        if item.metric_key == "outcome.verification_strategy_adequacy"
    )
    assert verification_strategy.state is PredictiveMetricState.UNAVAILABLE
    assert verification_strategy.mean is None
    assert all(item.numeric_value is None for item in receipt.metrics)
    assert all(
        item.status.value == "completed"
        for item in receipt.experts[6:9]
    )
    assert receipt.experts[9].status.value == "unavailable"
    assert "fictional segment" not in receipt.model_dump_json()


def test_live_probabilistic_heartbeats_never_regress_completed_progress() -> None:
    progress: list[tuple[int, int]] = []

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        assert runner._heartbeat is not None
        runner._heartbeat()
        return {
            "status": "completed",
            "device": "cpu",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.98,
                    "neutral": 0.01,
                    "contradiction": 0.01,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 10.0,
                "peak_cuda_allocated_mb": 0.0,
                "process_rss_after_load_and_inference_mb": 900.0,
            },
        }

    runner = LocalProbabilisticMetricRunner(executor=execute, device="cpu")
    runner.run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert progress
    assert all(total == 10 for _, total in progress)
    assert [completed for completed, _ in progress] == sorted(
        completed for completed, _ in progress
    )
    assert progress[-1] == (10, 10)


def test_live_probabilistic_runner_keeps_polish_on_multilingual_models() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        calls.append(
            (
                spec.identity.model_key,
                tuple(str(item["language"]) for item in payload["fragments"]),
            )
        )
        return {
            "status": "completed",
            "device": "cpu",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.98,
                    "neutral": 0.01,
                    "contradiction": 0.01,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 10.0,
                "peak_cuda_allocated_mb": 0.0,
                "process_rss_after_load_and_inference_mb": 800.0,
            },
        }

    english = _context()
    polish = english.model_copy(
        update={
            "messages": tuple(
                message.model_copy(
                    update={
                        "language": TextLanguage.POLISH,
                        "text": SecretStr("fikcyjna bezpieczna wiadomość testowa"),
                    }
                )
                for message in english.messages
            )
        }
    )
    receipt = LocalProbabilisticMetricRunner(
        executor=execute, device="cpu"
    ).run(
        build_ensemble_chunks(polish),
        coaching_ensemble_metric_specs(),
    )

    assert [model_key for model_key, _languages in calls] == [
        "mdeberta_xnli",
        "multilingual_minilmv2_l6_nli",
        "multilingual_minilmv2_l12_nli",
    ]
    assert all(set(languages) == {"pl"} for _model, languages in calls)
    assert receipt.predictive_projection is not None
    assert len(receipt.predictive_projection.metrics) == 20
    assert all(
        metric.state
        is (
            PredictiveMetricState.EXPERIMENTAL
            if next(
                contract
                for contract in PROBABILISTIC_METRIC_CONTRACTS
                if contract.metric_key == metric.metric_key
            ).closure_horizon == "immediate"
            and not next(
                contract
                for contract in PROBABILISTIC_METRIC_CONTRACTS
                if contract.metric_key == metric.metric_key
            ).objective_evidence_required
            and metric.metric_key not in EVIDENCE_LANE_METRIC_KEYS
            else PredictiveMetricState.UNAVAILABLE
        )
        for metric in receipt.predictive_projection.metrics
    )
    assert all(
        metric.state is PredictiveMetricState.UNAVAILABLE
        for metric in receipt.predictive_projection.metrics
        if metric.metric_key in EVIDENCE_LANE_METRIC_KEYS
    )


def test_live_probabilistic_runner_keeps_failed_predictions_nonnumeric() -> None:
    def execute(spec, stage, payload, device):
        return {
            "status": "failed",
            "error_code": "model_cache_missing_or_invalid",
            "device": None,
            "rows": [],
            "runtime": {},
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    assert all(
        item.state is PredictiveMetricState.UNAVAILABLE
        and item.mean is None
        and not item.density_bins
        for item in receipt.predictive_projection.metrics
    )


def test_malformed_optional_model_output_is_isolated() -> None:
    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        if spec.identity.model_key == "mdeberta_xnli":
            rows = []
        else:
            rows = [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.98,
                    "neutral": 0.01,
                    "contradiction": 0.01,
                }
                for item in payload["cases"]
            ]
        return {
            "status": "completed",
            "device": "cuda",
            "rows": rows,
            "runtime": {
                "inference_latency_ms": 10.0,
                "peak_cuda_allocated_mb": 500.0,
                "process_rss_after_load_and_inference_mb": 900.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    stages = {item.model_key: item for item in receipt.predictive_projection.model_stages}
    assert stages["mdeberta_xnli"].status == "failed"
    assert stages["mdeberta_xnli"].error_code == "probabilistic_factor_output_invalid"
    assert any(
        item.state is PredictiveMetricState.EXPERIMENTAL
        for item in receipt.predictive_projection.metrics
    )


def test_one_expert_is_insufficient_for_an_experimental_range() -> None:
    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        if spec.identity.model_key != "mdeberta_xnli":
            return {
                "status": "failed",
                "error_code": "model_cache_missing_or_invalid",
                "device": None,
                "rows": [],
                "runtime": {},
            }
        return {
            "status": "completed",
            "device": "cpu",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.99,
                    "neutral": 0.005,
                    "contradiction": 0.005,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 10.0,
                "peak_cuda_allocated_mb": 0.0,
                "process_rss_after_load_and_inference_mb": 900.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute, device="cpu").run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    assert all(
        item.state is PredictiveMetricState.UNAVAILABLE
        for item in receipt.predictive_projection.metrics
    )


def test_unresolved_neutral_mass_is_withheld_instead_of_conditioned_away() -> None:
    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        return {
            "status": "completed",
            "device": "cpu",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": (
                        0.79
                        if item["metric_key"] == "prompt.task_definition_coverage"
                        else 0.94
                    ),
                    "neutral": (
                        0.20
                        if item["metric_key"] == "prompt.task_definition_coverage"
                        else 0.05
                    ),
                    "contradiction": 0.01,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 10.0,
                "peak_cuda_allocated_mb": 0.0,
                "process_rss_after_load_and_inference_mb": 900.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute, device="cpu").run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    metrics = {
        item.metric_key: item for item in receipt.predictive_projection.metrics
    }
    critical = metrics["prompt.task_definition_coverage"]
    noncritical = metrics["prompt.constraint_precision"]
    assert critical.state is PredictiveMetricState.UNAVAILABLE
    assert critical.pending_probability is None
    assert critical.mean is None
    assert noncritical.state is PredictiveMetricState.UNAVAILABLE
    assert noncritical.pending_probability is None
    assert not noncritical.density_bins


def test_weighted_neutral_mass_withholds_noncritical_estimate() -> None:
    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        return {
            "status": "completed",
            "device": "cpu",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.66,
                    "neutral": 0.33,
                    "contradiction": 0.01,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 10.0,
                "peak_cuda_allocated_mb": 0.0,
                "process_rss_after_load_and_inference_mb": 900.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute, device="cpu").run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    constraint = next(
        item
        for item in receipt.predictive_projection.metrics
        if item.metric_key == "prompt.constraint_precision"
    )
    assert constraint.state is PredictiveMetricState.UNAVAILABLE
    assert constraint.pending_probability is None
    assert not constraint.density_bins


def test_joint_subthreshold_critical_neutral_mass_fails_retained_sample_gate() -> None:
    contributions = tuple(
        PredictiveFactorContribution(
            factor_key=f"synthetic_factor_{index}",
            scale=FactorScale.BINARY,
            weight=1.0,
            applicability_probability=1.0,
            present_probability=0.80,
            neutral_probability=0.19,
            absent_probability=0.01,
            expert_count=2,
            critical=True,
        )
        for index in range(4)
    )

    samples, applicable_draws = _draw_metric_samples(contributions, seed=17)

    assert applicable_draws == 1_024
    assert len(samples) / 1_024 < PROBABILISTIC_MIN_RETAINED_SAMPLE_RATE
    assert _has_sufficient_retained_samples(samples) is False


def test_ten_percent_neutral_per_factor_cannot_hide_outside_the_range() -> None:
    contributions = tuple(
        PredictiveFactorContribution(
            factor_key=f"synthetic_noncritical_{index}",
            scale=FactorScale.BINARY,
            weight=1.0,
            applicability_probability=1.0,
            present_probability=0.89,
            neutral_probability=0.10,
            absent_probability=0.01,
            expert_count=2,
            critical=False,
        )
        for index in range(4)
    )

    samples, applicable_draws = _draw_metric_samples(contributions, seed=19)

    assert applicable_draws == 1_024
    assert len(samples) / 1_024 < PROBABILISTIC_MIN_RETAINED_SAMPLE_RATE
    assert _has_sufficient_retained_samples(samples) is False


def test_unvalidated_long_context_challengers_are_not_live_experts() -> None:
    assert DISABLED_PROBABILISTIC_MODEL_KEYS == {
        "deberta_small_long_nli",
        "modernbert_base_zeroshot",
    }


def test_auto_deep_lane_uses_completed_stage_receipts_without_importing_torch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "torch":
            raise AssertionError("the long-lived server must not initialize Torch")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = ensemble_expert_specs()[6]
    cpu_stage = PredictiveModelStageReceipt(
        model_key=spec.identity.model_key,
        repository_id=spec.identity.repository_id,
        revision=spec.identity.revision,
        status="completed",
        device="cpu",
    )
    cuda_stage = cpu_stage.model_copy(update={"device": "cuda"})

    assert _cuda_deep_lane_available("auto", (cpu_stage,)) is False
    assert _cuda_deep_lane_available("auto", (cpu_stage, cuda_stage)) is True
    assert _cuda_deep_lane_available("cpu", (cuda_stage,)) is False
    assert _cuda_deep_lane_available("cuda", ()) is True


def test_live_probabilistic_runner_routes_only_uncertain_cases_to_nf4_judge() -> None:
    deep_calls = []

    def execute(spec, stage, payload, device):
        model_offset = {
            "mdeberta_xnli": 0.0,
            "multilingual_minilmv2_l6_nli": 0.15,
            "multilingual_minilmv2_l12_nli": -0.15,
            "deberta_small_long_nli": 0.10,
            "modernbert_base_zeroshot": -0.10,
        }[spec.identity.model_key]
        rows = [
            {
                "case_id": item["case_id"],
                "entailment": 0.45 + model_offset,
                "neutral": 0.30,
                "contradiction": 0.25 - model_offset,
            }
            for item in payload["cases"]
        ]
        return {
            "status": "completed",
            "device": "cuda",
            "rows": rows,
            "runtime": {
                "inference_latency_ms": 100.0,
                "peak_cuda_allocated_mb": 900.0,
                "process_rss_after_load_and_inference_mb": 1_500.0,
            },
        }

    def execute_deep(spec, stage, payload, device, quantization):
        deep_calls.append(
            (
                spec.identity.model_key,
                stage,
                device,
                quantization,
                tuple(item["case_id"] for item in payload["cases"]),
            )
        )
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {"case_id": item["case_id"], "label": "present"}
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 800.0,
                "peak_cuda_allocated_mb": 5_800.0,
                "process_rss_after_load_and_inference_mb": 7_500.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(
        executor=execute,
        deep_executor=execute_deep,
        device="cuda",
    ).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert len(deep_calls) == 1
    model_key, stage, device, quantization, case_ids = deep_calls[0]
    assert model_key == "qwen3_4b_rubric"
    assert stage == "structured_rubric"
    assert device == "cuda"
    assert quantization == "bitsandbytes_nf4"
    assert 1 <= len(case_ids) <= 12
    assert receipt.predictive_projection is not None
    assert len(receipt.predictive_projection.model_stages) == 4
    deep_stage = receipt.predictive_projection.model_stages[-1]
    assert deep_stage.model_key == "qwen3_4b_rubric"
    assert deep_stage.quantization == "bitsandbytes_nf4"
    assert deep_stage.status == "completed"
    assert all(
        item.state is not PredictiveMetricState.EXECUTION_ERROR
        for item in receipt.predictive_projection.metrics
    )


def test_deep_lane_failure_never_blocks_completed_small_model_ranges() -> None:
    def execute(spec, stage, payload, device):
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.35,
                    "neutral": 0.50,
                    "contradiction": 0.15,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 100.0,
                "peak_cuda_allocated_mb": 900.0,
                "process_rss_after_load_and_inference_mb": 1_500.0,
            },
        }

    def execute_deep(spec, stage, payload, device, quantization):
        return {
            "status": "failed",
            "error_code": "resource_exhausted",
            "device": None,
            "rows": [],
            "runtime": {},
        }

    receipt = LocalProbabilisticMetricRunner(
        executor=execute,
        deep_executor=execute_deep,
        device="cuda",
    ).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    assert receipt.predictive_projection.model_stages[-1].status == "resource_exhausted"
    assert all(
        item.state is PredictiveMetricState.UNAVAILABLE
        for item in receipt.predictive_projection.metrics
    )


def test_deep_result_returning_after_lane_budget_is_typed_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.35,
                    "neutral": 0.50,
                    "contradiction": 0.15,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 100.0,
                "peak_cuda_allocated_mb": 900.0,
                "process_rss_after_load_and_inference_mb": 1_500.0,
            },
        }

    def execute_deep(spec, stage, payload, device, quantization):  # type: ignore[no-untyped-def]
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {"case_id": item["case_id"], "label": "present"}
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 31_000.0,
                "peak_cuda_allocated_mb": 5_800.0,
                "process_rss_after_load_and_inference_mb": 7_500.0,
            },
        }

    observed_times = iter((100.0, 100.0, 131.0))
    monkeypatch.setattr(
        probabilistic_runtime_module,
        "monotonic",
        lambda: next(observed_times),
    )
    receipt = LocalProbabilisticMetricRunner(
        executor=execute,
        deep_executor=execute_deep,
        device="cuda",
    ).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    assert len(receipt.predictive_projection.model_stages) == 4
    assert receipt.predictive_projection.model_stages[-1].status == "unavailable"
    assert (
        receipt.predictive_projection.model_stages[-1].error_code
        == PROBABILISTIC_DEEP_TIMEOUT_ERROR_CODE
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows owned-job contract")
@pytest.mark.parametrize(
    "expected_confirmation",
    (True, False),
)
def test_windows_tree_cleanup_requires_positive_owned_job_exit(
    expected_confirmation: bool,
) -> None:
    class Pipe:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class Process:
        pid = 424_242

        def __init__(self) -> None:
            self.returncode = None
            self.tree_gone = False
            self.terminate_called = False
            self.kill_called = False
            self.stdin = Pipe()
            self.stdout = Pipe()

        def poll(self):  # type: ignore[no-untyped-def]
            return self.returncode

        def tree_exited(self) -> bool:
            return self.tree_gone

        def terminate(self) -> None:
            self.terminate_called = True
            if expected_confirmation:
                self.returncode = 0
                self.tree_gone = True

        def kill(self) -> None:
            self.kill_called = True
            self.returncode = -9

        def wait(self, *, timeout):  # type: ignore[no-untyped-def]
            if self.returncode is None:
                raise model_ensemble_module.subprocess.TimeoutExpired(
                    "synthetic-taskkill",
                    timeout,
                )
            return self.returncode

        def close(self, *, close_streams: bool = True) -> bool:
            if close_streams:
                self.stdin.close()
                self.stdout.close()
            return True

    process = Process()

    confirmed = model_ensemble_module._terminate_ensemble_process_tree(
        process,  # type: ignore[arg-type]
        environment={},
    )

    assert confirmed is expected_confirmation
    assert process.terminate_called is True
    assert process.kill_called is (not expected_confirmation)
    assert process.stdin.closed is True
    assert process.stdout.closed is True


def test_unconfirmed_subprocess_cleanup_raises_distinct_fatal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        pid = 424_243
        stdin = None
        stdout = None

        def poll(self):
            return None

        def communicate(self, *, input, timeout):  # type: ignore[no-untyped-def]
            raise model_ensemble_module.subprocess.TimeoutExpired(
                "synthetic-model-child",
                timeout,
            )

    observed_times = iter((100.0, 100.0, 102.0))
    monkeypatch.setattr(
        model_ensemble_module,
        "_start_ensemble_process",
        lambda *args, **kwargs: Process(),
    )
    monkeypatch.setattr(
        model_ensemble_module,
        "monotonic",
        lambda: next(observed_times),
    )
    monkeypatch.setattr(
        model_ensemble_module,
        "_terminate_ensemble_process_tree",
        lambda process, environment, close_pipes=True: False,
    )

    with pytest.raises(
        ModelEnsembleError,
        match=(
            rf"^{MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE}$"
        ),
    ):
        run_ensemble_expert_subprocess(
            ensemble_expert_specs()[6],
            "scope_nli",
            {"schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION},
            "cpu",
            timeout_seconds=1.0,
        )


def test_subprocess_deadline_kills_the_synthetic_child_tree(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "synthetic-grandchild-survived"
    child = (
        "import pathlib,time; time.sleep(1.5); "
        f"pathlib.Path({str(marker)!r}).write_text('unexpected','utf-8')"
    )
    script = tmp_path / "scripts" / "run_local_model_ensemble_expert.py"
    script.parent.mkdir()
    script.write_text(
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(model_ensemble_module, "repository_root", lambda: tmp_path)

    with pytest.raises(
        ModelEnsembleError,
        match=rf"^{MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_ERROR_CODE}$",
    ):
        run_ensemble_expert_subprocess(
            ensemble_expert_specs()[6],
            "scope_nli",
            {"schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION},
            "cpu",
            python_executable=sys.executable,
            timeout_seconds=0.5,
        )

    time.sleep(1.7)
    assert marker.exists() is False


def test_default_runner_bounds_only_the_optional_deep_lane_to_thirty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, float]] = []

    def execute(
        spec,
        stage,
        payload,
        device,
        *,
        python_executable=None,
        heartbeat=None,
        quantization="none",
        timeout_seconds=MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS,
    ):  # type: ignore[no-untyped-def]
        calls.append((spec.identity.model_key, timeout_seconds))
        if spec.identity.model_key == "qwen3_4b_rubric":
            raise ModelEnsembleError(
                MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_ERROR_CODE
            )
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.35,
                    "neutral": 0.50,
                    "contradiction": 0.15,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 100.0,
                "peak_cuda_allocated_mb": 900.0,
                "process_rss_after_load_and_inference_mb": 1_500.0,
            },
        }

    monkeypatch.setattr(
        probabilistic_runtime_module,
        "run_ensemble_expert_subprocess",
        execute,
    )
    progress: list[tuple[int, int]] = []
    receipt = LocalProbabilisticMetricRunner(device="cuda").run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
    )

    assert [timeout for key, timeout in calls if key != "qwen3_4b_rubric"] == [
        MODEL_ENSEMBLE_SUBPROCESS_TIMEOUT_SECONDS,
    ] * 3
    assert calls[-1] == (
        "qwen3_4b_rubric",
        PROBABILISTIC_DEEP_TIMEOUT_SECONDS,
    )
    assert receipt.predictive_projection is not None
    deep_stage = receipt.predictive_projection.model_stages[-1]
    assert deep_stage.status == "unavailable"
    assert deep_stage.error_code == PROBABILISTIC_DEEP_TIMEOUT_ERROR_CODE
    assert deep_stage.unloaded_after_stage is True
    assert progress[-1] == (10, 10)


def test_deep_cleanup_unconfirmed_is_fatal_and_cannot_create_a_receipt() -> None:
    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.35,
                    "neutral": 0.50,
                    "contradiction": 0.15,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 100.0,
                "peak_cuda_allocated_mb": 900.0,
                "process_rss_after_load_and_inference_mb": 1_500.0,
            },
        }

    def execute_deep(spec, stage, payload, device, quantization):  # type: ignore[no-untyped-def]
        raise ModelEnsembleError(
            MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE
        )

    with pytest.raises(
        ModelEnsembleError,
        match=(
            rf"^{MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE}$"
        ),
    ):
        LocalProbabilisticMetricRunner(
            executor=execute,
            deep_executor=execute_deep,
            device="cuda",
        ).run(
            build_ensemble_chunks(_context()),
            coaching_ensemble_metric_specs(),
        )


def test_stage_resource_ceiling_fails_closed_without_publishing_numbers() -> None:
    def execute(spec, stage, payload, device):
        return {
            "status": "completed",
            "device": "cuda",
            "rows": [
                {
                    "case_id": item["case_id"],
                    "entailment": 0.70,
                    "neutral": 0.20,
                    "contradiction": 0.10,
                }
                for item in payload["cases"]
            ],
            "runtime": {
                "inference_latency_ms": 100.0,
                "peak_cuda_allocated_mb": 6_145.0,
                "process_rss_after_load_and_inference_mb": 8_193.0,
            },
        }

    receipt = LocalProbabilisticMetricRunner(executor=execute).run(
        build_ensemble_chunks(_context()),
        coaching_ensemble_metric_specs(),
    )

    assert receipt.predictive_projection is not None
    assert all(
        stage.status == "resource_exhausted"
        and stage.error_code == "resource_contract_exceeded"
        for stage in receipt.predictive_projection.model_stages
    )
    assert all(
        item.state is PredictiveMetricState.UNAVAILABLE and item.mean is None
        for item in receipt.predictive_projection.metrics
    )


def test_committee_accepts_present_but_abstains_without_typed_opportunity() -> None:
    promoted = frozenset({"minilm_l6", "minilm_l12"})
    present = committee_chunk_receipt(
        chunk_ordinal=0,
        metric_key="prompt.task_definition_coverage",
        rubric_vote=_vote("qwen_rubric", ModelExpertRole.STRUCTURED_RUBRIC, ModelVoteState.PRESENT),
        nli_votes=(
            _vote("minilm_l6", ModelExpertRole.SCOPE_NLI, ModelVoteState.PRESENT),
            _vote("minilm_l12", ModelExpertRole.SCOPE_NLI, ModelVoteState.PRESENT),
            _vote("mdeberta", ModelExpertRole.SCOPE_NLI, ModelVoteState.ABSENT),
        ),
        contributing_nli_model_keys=promoted,
    )
    absent = committee_chunk_receipt(
        chunk_ordinal=1,
        metric_key="prompt.task_definition_coverage",
        rubric_vote=_vote("qwen_rubric", ModelExpertRole.STRUCTURED_RUBRIC, ModelVoteState.ABSENT, chunk=1),
        nli_votes=(
            _vote("minilm_l6", ModelExpertRole.SCOPE_NLI, ModelVoteState.ABSENT, chunk=1),
            _vote("minilm_l12", ModelExpertRole.SCOPE_NLI, ModelVoteState.ABSENT, chunk=1),
            _vote("mdeberta", ModelExpertRole.SCOPE_NLI, ModelVoteState.PRESENT, chunk=1),
        ),
        contributing_nli_model_keys=promoted,
    )

    assert present.value_state is MetricValueState.KNOWN
    assert (present.numerator, present.denominator) == (1, 1)
    assert absent.value_state is MetricValueState.ABSTAINED
    assert (absent.numerator, absent.denominator) == (None, None)
    assert absent.reason_code == "typed_metric_opportunity_unproven"


@pytest.mark.parametrize(
    ("nli_state", "expected_state", "expected_reason"),
    (
        (
            ModelVoteState.ABSTAIN,
            MetricValueState.ABSTAINED,
            "model_committee_nli_abstained",
        ),
        (
            ModelVoteState.FAILED,
            MetricValueState.EXECUTION_ERROR,
            "model_committee_nli_failed",
        ),
        (
            ModelVoteState.UNSUPPORTED,
            MetricValueState.UNKNOWN,
            "model_committee_nli_unsupported",
        ),
    ),
)
def test_committee_never_turns_missing_nli_evidence_into_known_zero(
    nli_state: ModelVoteState,
    expected_state: MetricValueState,
    expected_reason: str,
) -> None:
    receipt = committee_chunk_receipt(
        chunk_ordinal=0,
        metric_key="prompt.task_definition_coverage",
        rubric_vote=_vote(
            "qwen_rubric",
            ModelExpertRole.STRUCTURED_RUBRIC,
            ModelVoteState.ABSENT,
        ),
        nli_votes=(
            _vote("minilm_l6", ModelExpertRole.SCOPE_NLI, nli_state),
            _vote("minilm_l12", ModelExpertRole.SCOPE_NLI, ModelVoteState.ABSENT),
            _vote("mdeberta", ModelExpertRole.SCOPE_NLI, ModelVoteState.PRESENT),
        ),
        contributing_nli_model_keys=frozenset({"minilm_l6", "minilm_l12"}),
    )

    assert receipt.value_state is expected_state
    assert receipt.numerator is None
    assert receipt.denominator is None
    assert receipt.reason_code == expected_reason


def test_committee_disagreement_abstains_and_diagnostic_model_cannot_decide() -> None:
    receipt = committee_chunk_receipt(
        chunk_ordinal=0,
        metric_key="prompt.task_definition_coverage",
        rubric_vote=_vote("qwen_rubric", ModelExpertRole.STRUCTURED_RUBRIC, ModelVoteState.PRESENT),
        nli_votes=(
            _vote("minilm_l6", ModelExpertRole.SCOPE_NLI, ModelVoteState.ABSENT),
            _vote("minilm_l12", ModelExpertRole.SCOPE_NLI, ModelVoteState.ABSENT),
            _vote("mdeberta", ModelExpertRole.SCOPE_NLI, ModelVoteState.PRESENT),
        ),
        contributing_nli_model_keys=frozenset({"minilm_l6", "minilm_l12"}),
    )
    assert receipt.value_state is MetricValueState.ABSTAINED
    assert receipt.reason_code == "model_committee_disagreement"


def test_session_aggregate_is_ratio_of_valid_chunks_not_model_logits() -> None:
    promoted = frozenset({"minilm_l6", "minilm_l12"})
    receipts = []
    for chunk, rubric_state, nli_state in (
        (0, ModelVoteState.PRESENT, ModelVoteState.PRESENT),
        (1, ModelVoteState.ABSENT, ModelVoteState.ABSENT),
        (2, ModelVoteState.ABSTAIN, ModelVoteState.ABSTAIN),
    ):
        receipts.append(
            committee_chunk_receipt(
                chunk_ordinal=chunk,
                metric_key="prompt.task_definition_coverage",
                rubric_vote=_vote("qwen_rubric", ModelExpertRole.STRUCTURED_RUBRIC, rubric_state, chunk=chunk),
                nli_votes=(
                    _vote("minilm_l6", ModelExpertRole.SCOPE_NLI, nli_state, chunk=chunk),
                    _vote("minilm_l12", ModelExpertRole.SCOPE_NLI, nli_state, chunk=chunk),
                    _vote("mdeberta", ModelExpertRole.SCOPE_NLI, ModelVoteState.PRESENT, chunk=chunk),
                ),
                contributing_nli_model_keys=promoted,
            )
        )
    aggregate = aggregate_chunk_metrics(tuple(receipts))[0]
    assert aggregate.value_state is MetricValueState.KNOWN
    assert (aggregate.numerator, aggregate.denominator) == (1, 1)
    assert aggregate.numeric_value == 1.0
    assert aggregate.abstained_chunk_count == 2
    assert aggregate.product_metric_eligible is False


def test_all_unsupported_chunks_remain_unknown() -> None:
    receipts = tuple(
        committee_chunk_receipt(
            chunk_ordinal=chunk,
            metric_key="outcome.agent_claim_grounding",
            rubric_vote=_vote(
                "qwen_rubric",
                ModelExpertRole.STRUCTURED_RUBRIC,
                ModelVoteState.UNSUPPORTED,
                chunk=chunk,
                metric="outcome.agent_claim_grounding",
            ),
            nli_votes=tuple(
                _vote(
                    model,
                    ModelExpertRole.SCOPE_NLI,
                    ModelVoteState.UNSUPPORTED,
                    chunk=chunk,
                    metric="outcome.agent_claim_grounding",
                )
                for model in ("minilm_l6", "minilm_l12", "mdeberta")
            ),
            contributing_nli_model_keys=frozenset({"minilm_l6", "minilm_l12"}),
        )
        for chunk in range(2)
    )

    aggregate = aggregate_chunk_metrics(receipts)[0]
    assert aggregate.value_state is MetricValueState.UNKNOWN
    assert aggregate.numeric_value is None
    assert aggregate.unsupported_chunk_count == 2
    assert aggregate.explanation_code == "model_shadow_no_supported_observations"


@pytest.mark.parametrize(
    ("owner_state", "expected_state"),
    (
        (MetricValueState.KNOWN, MetricValueState.KNOWN),
        (MetricValueState.ABSTAINED, MetricValueState.ABSTAINED),
        (MetricValueState.UNKNOWN, MetricValueState.UNKNOWN),
        (MetricValueState.EXECUTION_ERROR, MetricValueState.EXECUTION_ERROR),
    ),
)
def test_structural_cells_do_not_distort_the_owned_observation(
    owner_state: MetricValueState,
    expected_state: MetricValueState,
) -> None:
    metric_key = "logic.open_loop_closure"
    structural = ChunkMetricCommitteeReceipt(
        chunk_ordinal=0,
        metric_key=metric_key,
        value_state=MetricValueState.NOT_APPLICABLE,
        rubric_vote=ModelVoteState.UNSUPPORTED,
        contributing_nli_votes=0,
        diagnostic_nli_votes=0,
        reason_code="session_window_observation_owned_by_final_chunk",
    )
    owner = ChunkMetricCommitteeReceipt(
        chunk_ordinal=1,
        metric_key=metric_key,
        value_state=owner_state,
        numerator=1 if owner_state is MetricValueState.KNOWN else None,
        denominator=1 if owner_state is MetricValueState.KNOWN else None,
        rubric_vote=(
            ModelVoteState.PRESENT
            if owner_state is MetricValueState.KNOWN
            else ModelVoteState.ABSTAIN
        ),
        contributing_nli_votes=2,
        diagnostic_nli_votes=1,
        reason_code="synthetic_owner_receipt",
    )

    aggregate = aggregate_chunk_metrics((structural, owner))[0]

    assert aggregate.value_state is expected_state
    assert aggregate.total_chunk_count == 1
    assert (
        aggregate.known_chunk_count
        + aggregate.abstained_chunk_count
        + aggregate.unsupported_chunk_count
        + aggregate.failed_chunk_count
    ) == 1


def test_vote_contract_rejects_scores_for_abstentions() -> None:
    with pytest.raises(ValidationError):
        ModelMetricVote(
            chunk_ordinal=0,
            metric_key="prompt.task_definition_coverage",
            model_key="qwen_rubric",
            role=ModelExpertRole.STRUCTURED_RUBRIC,
            state=ModelVoteState.ABSTAIN,
            raw_score=0.4,
            reason_code="synthetic_vote",
        )


def test_ten_expert_inventory_is_fixed_serial_and_process_releasable() -> None:
    experts = ensemble_expert_specs()
    assert len(experts) == 10
    assert tuple(item.identity.ordinal for item in experts) == tuple(range(10))
    assert tuple(item.identity.role for item in experts) == (
        *(ModelExpertRole.RETRIEVAL for _ in range(4)),
        *(ModelExpertRole.RERANKING for _ in range(2)),
        *(ModelExpertRole.SCOPE_NLI for _ in range(3)),
        ModelExpertRole.STRUCTURED_RUBRIC,
    )
    assert {item.identity.model_key for item in experts} == {
        "multilingual_e5_small",
        "multilingual_e5_base",
        "bge_m3",
        "qwen3_embedding_06b",
        "bge_reranker_v2_m3",
        "qwen3_reranker_06b",
        "mdeberta_xnli",
        "multilingual_minilmv2_l6_nli",
        "multilingual_minilmv2_l12_nli",
        "qwen3_4b_rubric",
    }


def test_serial_runner_preserves_scope_and_keeps_outcomes_unsupported() -> None:
    calls: list[tuple[int, str]] = []
    retrieval_payloads: list[dict[str, object]] = []

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        calls.append((spec.identity.ordinal, stage))
        if stage == "retrieval":
            retrieval_payloads.append(payload)
        rows = []
        for case in payload["cases"]:
            if stage in {"retrieval", "reranking"}:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "scores": [
                            {"fragment_id": identifier, "score": 1.0 / (index + 1)}
                            for index, identifier in enumerate(case["candidate_ids"])
                        ],
                    }
                )
            elif stage == "scope_nli":
                diagnostic = spec.identity.model_key == "mdeberta_xnli"
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "entailment": 0.05 if diagnostic else 0.9,
                        "neutral": 0.05,
                        "contradiction": 0.9 if diagnostic else 0.05,
                    }
                )
            else:
                rows.append({"case_id": case["case_id"], "label": "present"})
        return {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "completed",
            "error_code": None,
            "device": "cuda",
            "rows": rows,
            "runtime": {
                "inference_latency_ms": 1.0,
                "peak_cuda_allocated_mb": 2.0,
                "process_rss_after_load_and_inference_mb": 3.0,
            },
        }

    plan = build_ensemble_chunks(_context())
    specs = coaching_ensemble_metric_specs()
    receipt = SerialModelEnsembleRunner(executor=execute, device="cuda").run(
        plan, specs
    )

    assert calls == [
        (ordinal, ensemble_expert_specs()[ordinal].identity.role.value)
        for ordinal in range(10)
    ]
    assert len(receipt.experts) == 10
    assert all(item.unloaded_after_stage for item in receipt.experts)
    assert len(receipt.metrics) == 20
    objective_keys = {
        item.metric_key for item in specs if item.evidence_scope == "objective_evidence"
    }
    supported = [item for item in receipt.metrics if item.metric_key not in objective_keys]
    unsupported = [item for item in receipt.metrics if item.metric_key in objective_keys]
    assert all(item.value_state is MetricValueState.KNOWN for item in supported)
    assert all(item.numeric_value == 1.0 for item in supported)
    assert all(item.value_state is MetricValueState.UNKNOWN for item in unsupported)
    assert all(item.numeric_value is None for item in unsupported)
    assert all(item.total_chunk_count == 1 for item in receipt.metrics)
    assert all(item.product_metric_eligible is False for item in receipt.metrics)

    first_payload = retrieval_payloads[0]
    fragment_metadata = {
        item["fragment_id"]: item
        for item in first_payload["fragments"]  # type: ignore[index]
    }
    assert any(item["role"] == "agent" for item in fragment_metadata.values())
    assert any(item["language"] == "en" for item in fragment_metadata.values())
    assert all(
        not str(case["metric_key"]).startswith("outcome.")
        for case in first_payload["cases"]  # type: ignore[index]
    )
    prompt_cases = [
        case
        for case in first_payload["cases"]  # type: ignore[index]
        if str(case["metric_key"]).startswith("prompt.")
    ]
    assert prompt_cases
    assert len(prompt_cases) == sum(
        item.evidence_scope == "focus_request" for item in specs
    )
    focus_ids = [
        identifier
        for identifier, metadata in fragment_metadata.items()
        if metadata["is_focus_message"] is True
    ]
    assert all(case["candidate_ids"] == focus_ids for case in prompt_cases)
    assert all(
        fragment_metadata[identifier]["role"] == "user"
        and fragment_metadata[identifier]["kind"] == "request"
        and fragment_metadata[identifier]["is_focus_message"] is True
        for case in prompt_cases
        for identifier in case["candidate_ids"]
    )
    conversation_cases = [
        case
        for case in first_payload["cases"]  # type: ignore[index]
        if next(
            item for item in specs if item.metric_key == case["metric_key"]
        ).evidence_scope == "conversation"
    ]
    all_fragment_ids = [
        item["fragment_id"] for item in first_payload["fragments"]  # type: ignore[index]
    ]
    assert len(conversation_cases) == sum(
        item.evidence_scope == "conversation" for item in specs
    )
    assert all(case["candidate_ids"] == all_fragment_ids for case in conversation_cases)
    assert all(
        sum(
            item.metric_key == metric.metric_key
            and item.value_state is not MetricValueState.NOT_APPLICABLE
            for item in receipt.chunks
        )
        == 1
        for metric in specs
    )
    serialized = receipt.model_dump_json()
    assert "fictional segment" not in serialized
    assert '"content_persisted":false' in serialized


def test_conversation_owner_sees_later_closure_in_source_chronology() -> None:
    decision_payloads: list[dict[str, object]] = []
    opening_marker = "SYNTHETIC_OPEN_LOOP_MARKER"
    closure_marker = "SYNTHETIC_LOOP_CLOSED_MARKER"

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        fragments = {
            item["fragment_id"]: item["text"] for item in payload["fragments"]
        }
        if stage == "scope_nli":
            decision_payloads.append(payload)
        rows = []
        for case in payload["cases"]:
            evidence = "\n".join(fragments[item] for item in case["candidate_ids"])
            closes_loop = opening_marker in evidence and closure_marker in evidence
            if stage in {"retrieval", "reranking"}:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "scores": [
                            {
                                "fragment_id": identifier,
                                "score": (
                                    3.0
                                    if closure_marker in fragments[identifier]
                                    else 2.0
                                    if opening_marker in fragments[identifier]
                                    else 1.0 / (index + 10)
                                ),
                            }
                            for index, identifier in enumerate(case["candidate_ids"])
                        ],
                    }
                )
            elif stage == "scope_nli":
                positive = case["metric_key"] != "logic.open_loop_closure" or closes_loop
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "entailment": 0.9 if positive else 0.05,
                        "neutral": 0.05 if positive else 0.9,
                        "contradiction": 0.05,
                    }
                )
            else:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "label": (
                            "present"
                            if case["metric_key"] != "logic.open_loop_closure"
                            or closes_loop
                            else "abstain"
                        ),
                    }
                )
        return {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "completed",
            "error_code": None,
            "device": "cpu",
            "rows": rows,
            "runtime": {},
        }

    base = _context()
    opened = base.model_copy(
        update={
            "messages": (
                base.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            (opening_marker + " " + ("fictional unresolved question " * 220))[:5_200]
                        )
                    }
                ),
                *base.messages[1:],
            ),
            "analysis_window_fingerprint": _digest("e"),
        }
    )
    runner = SerialModelEnsembleRunner(executor=execute, device="cpu")
    specs = coaching_ensemble_metric_specs()
    before = runner.run(build_ensemble_chunks(opened), specs)
    assert next(
        item for item in before.metrics if item.metric_key == "logic.open_loop_closure"
    ).value_state is MetricValueState.ABSTAINED

    closure = EphemeralRedactedMessage(
        message_id=f"{97:064x}",
        sequence=len(opened.messages),
        role=TextRole.AGENT,
        kind=TextMessageKind.RESPONSE,
        language=TextLanguage.ENGLISH,
        text=SecretStr(
            (closure_marker + " " + ("fictional verified resolution " * 220))[:5_200]
        ),
    )
    closed = opened.model_copy(
        update={
            "messages": (*opened.messages, closure),
            "observed_message_count": opened.observed_message_count + 1,
            "eligible_message_count": opened.eligible_message_count + 1,
            "analysis_window_fingerprint": _digest("f"),
        }
    )
    decision_payloads.clear()
    after = runner.run(build_ensemble_chunks(closed), specs, prior_receipt=before)

    nli_case = next(
        case
        for case in decision_payloads[0]["cases"]  # type: ignore[index]
        if case["metric_key"] == "logic.open_loop_closure"
    )
    text_by_id = {
        item["fragment_id"]: item["text"]
        for item in decision_payloads[0]["fragments"]  # type: ignore[index]
    }
    evidence = [text_by_id[item] for item in nli_case["candidate_ids"]]
    assert opening_marker in evidence[0]
    assert closure_marker in evidence[-1]
    assert nli_case["chunk_ordinal"] == after.chunk_count - 1
    metric = next(
        item for item in after.metrics if item.metric_key == "logic.open_loop_closure"
    )
    assert metric.value_state is MetricValueState.KNOWN
    assert (metric.numerator, metric.denominator, metric.total_chunk_count) == (1, 1, 1)


def test_long_focus_request_is_one_owned_observation_across_chunks() -> None:
    retrieval_payloads: list[dict[str, object]] = []

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        if stage == "retrieval":
            retrieval_payloads.append(payload)
        rows = []
        for case in payload["cases"]:
            if stage in {"retrieval", "reranking"}:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "scores": [
                            {"fragment_id": identifier, "score": 1.0 / (index + 1)}
                            for index, identifier in enumerate(case["candidate_ids"])
                        ],
                    }
                )
            elif stage == "scope_nli":
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "entailment": 0.9,
                        "neutral": 0.05,
                        "contradiction": 0.05,
                    }
                )
            else:
                rows.append({"case_id": case["case_id"], "label": "present"})
        return {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "completed",
            "error_code": None,
            "device": "cpu",
            "rows": rows,
            "runtime": {},
        }

    base = _context()
    focus = EphemeralRedactedMessage(
        message_id=f"{96:064x}",
        sequence=0,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(("fictional complete focus request clause " * 1_000)[:31_500]),
    )
    response = EphemeralRedactedMessage(
        message_id=f"{95:064x}",
        sequence=1,
        role=TextRole.AGENT,
        kind=TextMessageKind.RESPONSE,
        language=TextLanguage.ENGLISH,
        text=SecretStr("fictional acknowledgement"),
    )
    context = base.model_copy(
        update={
            "messages": (focus, response),
            "focus_message_id": focus.message_id,
            "observed_message_count": 2,
            "eligible_message_count": 2,
            "analysis_window_fingerprint": _digest("9"),
        }
    )
    plan = build_ensemble_chunks(context)
    assert len(plan.chunks) > 1
    receipt = SerialModelEnsembleRunner(executor=execute, device="cpu").run(
        plan, coaching_ensemble_metric_specs()
    )

    payload = retrieval_payloads[0]
    focus_ids = [
        item["fragment_id"]
        for item in payload["fragments"]  # type: ignore[index]
        if item["is_focus_message"] is True
    ]
    prompt_cases = [
        item
        for item in payload["cases"]  # type: ignore[index]
        if str(item["metric_key"]).startswith("prompt.")
    ]
    focus_owner = max(
        chunk.ordinal
        for chunk in plan.chunks
        if any(item.is_focus_message for item in chunk.fragments)
    )
    assert all(case["candidate_ids"] == focus_ids for case in prompt_cases)
    assert all(case["chunk_ordinal"] == focus_owner for case in prompt_cases)
    assert all(
        next(item for item in receipt.metrics if item.metric_key == case["metric_key"]).total_chunk_count
        == 1
        for case in prompt_cases
    )


def test_incremental_runner_recomputes_owned_observations_serially() -> None:
    calls: list[tuple[str, str, int]] = []

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        calls.append((device, stage, len(payload["cases"])))
        rows = []
        for case in payload["cases"]:
            if stage in {"retrieval", "reranking"}:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "scores": [
                            {"fragment_id": identifier, "score": 1.0 / (index + 1)}
                            for index, identifier in enumerate(case["candidate_ids"])
                        ],
                    }
                )
            elif stage == "scope_nli":
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "entailment": 0.9,
                        "neutral": 0.05,
                        "contradiction": 0.05,
                    }
                )
            else:
                rows.append({"case_id": case["case_id"], "label": "present"})
        return {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "completed",
            "error_code": None,
            "device": device if device != "auto" else "cpu",
            "rows": rows,
            "runtime": {
                "inference_latency_ms": 1.0,
                "peak_cuda_allocated_mb": 0.0,
                "process_rss_after_load_and_inference_mb": 3.0,
            },
        }

    context = _context()
    specs = coaching_ensemble_metric_specs()
    runner = SerialModelEnsembleRunner(executor=execute, device="cpu")
    first = runner.run(build_ensemble_chunks(context), specs)
    first_call_counts = tuple(calls)
    calls.clear()

    appended_message = EphemeralRedactedMessage(
        message_id=f"{98:064x}",
        sequence=len(context.messages),
        role=TextRole.AGENT,
        kind=TextMessageKind.RESPONSE,
        language=TextLanguage.ENGLISH,
        text=SecretStr(("fictional incremental response " * 220)[:5_200]),
    )
    appended = context.model_copy(
        update={
            "messages": (*context.messages, appended_message),
            "focus_message_id": context.focus_message_id,
            "observed_message_count": context.observed_message_count + 1,
            "eligible_message_count": context.eligible_message_count + 1,
            "analysis_window_fingerprint": _digest("d"),
        }
    )
    second = runner.run(
        build_ensemble_chunks(appended), specs, prior_receipt=first
    )

    assert len(calls) == 10
    assert [stage for _device, stage, _count in calls] == [
        item.identity.role.value for item in ensemble_expert_specs()
    ]
    # A changed source recomputes both canonical focus-request observations and
    # whole-window conversation observations. Exact unchanged inputs are reused
    # by the service before the runner, while partial owner lineage is not yet
    # persisted and therefore cannot be copied safely here.
    assert calls[0][2] == first_call_counts[0][2]
    assert second.plan_fingerprint == first.plan_fingerprint
    assert tuple(item.chunk_fingerprint for item in second.chunk_plan[: len(first.chunk_plan) - 1]) == tuple(
        item.chunk_fingerprint for item in first.chunk_plan[:-1]
    )
    assert all(item.total_chunk_count == 1 for item in second.metrics)


def test_cuda_resource_exhaustion_retries_each_stage_on_cpu_after_release() -> None:
    attempts: list[tuple[str, str]] = []

    def execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
        attempts.append((spec.identity.model_key, device))
        if device == "cuda":
            return {
                "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
                "model_key": spec.identity.model_key,
                "status": "failed",
                "error_code": "resource_exhausted",
                "device": "cuda",
                "rows": [],
                "runtime": {},
            }
        rows = []
        for case in payload["cases"]:
            if stage in {"retrieval", "reranking"}:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "scores": [
                            {"fragment_id": identifier, "score": 1.0}
                            for identifier in case["candidate_ids"]
                        ],
                    }
                )
            elif stage == "scope_nli":
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "entailment": 0.9,
                        "neutral": 0.05,
                        "contradiction": 0.05,
                    }
                )
            else:
                rows.append({"case_id": case["case_id"], "label": "present"})
        return {
            "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
            "model_key": spec.identity.model_key,
            "status": "completed",
            "error_code": None,
            "device": "cpu",
            "rows": rows,
            "runtime": {},
        }

    receipt = SerialModelEnsembleRunner(executor=execute, device="cuda").run(
        build_ensemble_chunks(_context()), coaching_ensemble_metric_specs()
    )

    assert len(attempts) == 20
    assert all(attempts[index][1] == ("cuda" if index % 2 == 0 else "cpu") for index in range(20))
    assert all(item.status.value == "completed" and item.device == "cpu" for item in receipt.experts)
