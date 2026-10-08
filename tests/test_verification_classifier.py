from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.verification import (
    EphemeralVerificationCandidate,
    VerificationAbstentionReason,
    VerificationCapability,
    VerificationCapabilityState,
    VerificationClassificationDecision,
    VerificationExecutionState,
    VerificationKind,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.verification import (
    CANDIDATE_SCHEMA_VERSION,
    DeterministicCommandVerificationClassifier,
    validation_only_capability,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic"
    / "verification"
    / "command_cases.json"
)
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _candidate(
    command: str,
    *,
    state: VerificationExecutionState = VerificationExecutionState.UNKNOWN,
) -> EphemeralVerificationCandidate:
    return EphemeralVerificationCandidate(
        provider=Provider.SYNTHETIC,
        source_item_id=SecretStr("example-verification-item"),
        command=SecretStr(command),
        candidate_schema_version=CANDIDATE_SCHEMA_VERSION,
        execution_state=state,
    )


@pytest.mark.parametrize("case", CASES["positive"])
def test_supported_signatures_match_exactly_one_expected_kind(case: dict[str, str]) -> None:
    result = DeterministicCommandVerificationClassifier().classify(
        _candidate(case["command"])
    )

    assert result.decision is VerificationClassificationDecision.VERIFICATION
    assert result.kind is VerificationKind(case["kind"])
    assert result.rule_id is not None
    assert result.abstention_reason is None


@pytest.mark.parametrize("case", CASES["negative"])
def test_near_misses_never_become_verification(case: dict[str, str]) -> None:
    result = DeterministicCommandVerificationClassifier().classify(
        _candidate(case["command"])
    )

    assert result.decision is VerificationClassificationDecision(case["decision"])
    assert result.kind is None


@pytest.mark.parametrize("command", CASES["ambiguous"])
def test_compound_or_interpreted_shell_shapes_always_abstain(command: str) -> None:
    result = DeterministicCommandVerificationClassifier().classify(
        _candidate(command)
    )

    assert result.decision is VerificationClassificationDecision.ABSTAINED
    assert result.abstention_reason is VerificationAbstentionReason.AMBIGUOUS_SHELL


def test_classification_is_deterministic_and_execution_state_independent() -> None:
    classifier = DeterministicCommandVerificationClassifier()
    results = {
        classifier.classify(_candidate("pytest -q", state=state)).model_dump_json()
        for state in VerificationExecutionState
    }

    assert len(results) == 1


def test_empty_and_oversized_commands_abstain_without_echoing_input() -> None:
    classifier = DeterministicCommandVerificationClassifier()
    empty = classifier.classify(_candidate(""))
    oversized = classifier.classify(_candidate("x" * 4_097))

    assert empty.abstention_reason is VerificationAbstentionReason.EMPTY
    assert oversized.abstention_reason is VerificationAbstentionReason.TOO_LARGE
    assert "x" * 128 not in oversized.model_dump_json()


def test_private_command_canary_never_crosses_the_safe_result_boundary() -> None:
    canary = "SYNTHETIC-PRIVATE-COMMAND-CANARY"
    candidate = _candidate(f"echo {canary}")
    result = DeterministicCommandVerificationClassifier().classify(candidate)

    assert canary not in repr(candidate)
    assert canary not in candidate.model_dump_json()
    assert canary not in repr(result)
    assert canary not in result.model_dump_json()
    assert set(result.model_dump()) == {
        "decision",
        "kind",
        "rule_id",
        "abstention_reason",
        "classifier_version",
        "normalizer_version",
    }


def test_capability_is_truthful_about_validation_only_state() -> None:
    capability = validation_only_capability()

    assert capability.state is VerificationCapabilityState.VALIDATION_ONLY
    assert capability.live_classification_enabled is False
    assert capability.supported_kinds == tuple(VerificationKind)
    assert capability.reason_code == "provider_adapter_and_holdout_required"


def test_incompatible_candidate_schema_abstains_before_command_rules() -> None:
    candidate = _candidate("pytest -q").model_copy(
        update={"candidate_schema_version": "alien-v99"}
    )

    result = DeterministicCommandVerificationClassifier().classify(candidate)

    assert result.decision is VerificationClassificationDecision.ABSTAINED
    assert result.abstention_reason is VerificationAbstentionReason.INCOMPATIBLE_SCHEMA


def test_supported_capability_cannot_claim_live_disabled() -> None:
    payload = validation_only_capability().model_dump()
    payload.update(state="supported", live_classification_enabled=False)

    with pytest.raises(ValidationError, match="supported verification"):
        VerificationCapability.model_validate(payload)
