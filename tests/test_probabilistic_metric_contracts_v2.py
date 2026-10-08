from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json

from pydantic import ValidationError
import pytest

import prompt_enhancer.application.analysis.probabilistic_metrics as probabilistic_module
from prompt_enhancer.application.analysis.probabilistic_metrics import (
    EVIDENCE_LANE_METRIC_KEYS,
    EXPERIMENTAL_CALIBRATION_VERSION,
    PROBABILISTIC_METRIC_CONTRACTS,
    PROBABILISTIC_METRIC_PROMPT_PACKETS,
    PROBABILISTIC_PROMPT_PACKET_VERSION,
    MetricWorkspaceView,
    PredictiveMetricState,
    PromptLocale,
    SessionPredictiveMetricProjection,
    SessionPredictiveMetricReceipt,
    metric_keys_for_workspace_view,
    probabilistic_metric_prompt_packet,
)


def test_workspace_groups_partition_all_twenty_metrics() -> None:
    grouped = {
        view: metric_keys_for_workspace_view(view) for view in MetricWorkspaceView
    }

    assert {view: len(keys) for view, keys in grouped.items()} == {
        MetricWorkspaceView.FRAMING: 6,
        MetricWorkspaceView.COLLABORATION: 5,
        MetricWorkspaceView.REASONING: 4,
        MetricWorkspaceView.EVIDENCE: 5,
    }
    flattened = tuple(key for keys in grouped.values() for key in keys)
    assert len(flattened) == len(set(flattened)) == 20
    assert set(grouped[MetricWorkspaceView.EVIDENCE]) == EVIDENCE_LANE_METRIC_KEYS


def test_every_factor_has_a_versioned_bilingual_prompt_packet() -> None:
    contracts = {item.metric_key: item for item in PROBABILISTIC_METRIC_CONTRACTS}

    assert len(PROBABILISTIC_METRIC_PROMPT_PACKETS) == 20
    for packet in PROBABILISTIC_METRIC_PROMPT_PACKETS:
        contract = contracts[packet.metric_key]
        assert packet.packet_version == PROBABILISTIC_PROMPT_PACKET_VERSION
        assert tuple(item.factor_key for item in packet.factors) == tuple(
            item.factor_key for item in contract.factors
        )
        for factor in packet.factors:
            assert factor.statement(PromptLocale.ENGLISH)
            assert factor.statement(PromptLocale.POLISH)
            for locale in PromptLocale:
                rubric = packet.deep_rubric(factor.factor_key, locale)
                assert len(rubric) <= 3_000
                assert (
                    "untrusted data" in rubric
                    or "niezaufane dane" in rubric
                )


def test_rework_packet_requires_mutually_exclusive_episode_classification() -> None:
    packet = next(
        item
        for item in PROBABILISTIC_METRIC_PROMPT_PACKETS
        if item.metric_key == "collaboration.rework_candidate_rate"
    )

    assert any("exactly one episode type" in item for item in packet.exclusions_en)
    assert any("dokładnie jeden typ epizodu" in item for item in packet.exclusions_pl)
    assert "preference" in packet.definition_en
    assert "preferencji" in packet.definition_pl


def test_reused_factor_keys_have_metric_exact_polish_statements() -> None:
    duplicated_factor_metrics = {
        "scope": (
            "prompt.constraint_precision",
            "outcome.verification_strategy_adequacy",
        ),
        "oracle": (
            "prompt.acceptance_testability",
            "outcome.verification_strategy_adequacy",
        ),
        "hypothesis": (
            "collaboration.exploration_conversion",
            "logic.hypothesis_test_linkage",
        ),
        "requirement": (
            "logic.requirement_action_traceability",
            "outcome.verification_strategy_adequacy",
            "outcome.verified_requirement_coverage",
        ),
    }

    for factor_key, metric_keys in duplicated_factor_metrics.items():
        statements = tuple(
            probabilistic_metric_prompt_packet(metric_key)
            .factor(factor_key)
            .statement(PromptLocale.POLISH)
            for metric_key in metric_keys
        )
        assert len(statements) == len(set(statements))


def test_stored_v1_projection_uses_frozen_contract_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts = tuple(
        SessionPredictiveMetricReceipt(
            metric_key=contract.metric_key,
            target=contract.target,
            state=PredictiveMetricState.UNAVAILABLE,
            effective_observation_count=0,
            calibration_version=EXPERIMENTAL_CALIBRATION_VERSION,
            contract_version=contract.contract_version,
            contract_fingerprint=contract.fingerprint,
        )
        for contract in PROBABILISTIC_METRIC_CONTRACTS
    )
    stored_payload = json.loads(
        SessionPredictiveMetricProjection(
            projected_at=datetime(2040, 1, 1, tzinfo=UTC),
            metrics=receipts,
            model_stages=(),
        ).model_dump_json()
    )

    advanced = replace(
        PROBABILISTIC_METRIC_CONTRACTS[0],
        contract_version="probabilistic-metric-contract-v2",
    )
    advanced_registry = (advanced, *PROBABILISTIC_METRIC_CONTRACTS[1:])
    monkeypatch.setattr(
        probabilistic_module,
        "PROBABILISTIC_METRIC_CONTRACTS",
        advanced_registry,
    )
    monkeypatch.setattr(
        probabilistic_module,
        "_CONTRACT_BY_KEY",
        {item.metric_key: item for item in advanced_registry},
    )

    restored = SessionPredictiveMetricProjection.model_validate(stored_payload)
    assert restored.metrics[0].contract_version == "probabilistic-metric-contract-v1"

    tampered_payload = json.loads(json.dumps(stored_payload))
    tampered_payload["metrics"][0]["contract_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="frozen metric contract"):
        SessionPredictiveMetricProjection.model_validate(tampered_payload)
