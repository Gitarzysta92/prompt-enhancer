from __future__ import annotations

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    TEXT_METRIC_DEFINITIONS,
    TextMetricEngine,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ApplicabilityBasis,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TextAnalysisPrivacyError,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.domain import DataTier, Provider


CANARY = "SYNTHETIC-TRANSCRIPT-CANARY-NEVER-PERSIST-12345"


def _context() -> P1TextAnalysisInput:
    message = EphemeralRedactedMessage(
        message_id="c" * 64,
        sequence=0,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(f"Build a report so that tests can verify it. {CANARY}"),
    )
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
        focus_message_id=message.message_id,
        observed_message_count=1,
        eligible_message_count=1,
        messages=(message,),
        task_profile=TextTaskProfile(
            applicability=tuple(
                MetricApplicabilityDecision(
                    metric_key=definition.key,
                    applicability=MetricApplicability.NOT_APPLICABLE,
                    basis=ApplicabilityBasis.USER_SELECTED,
                )
                for definition in TEXT_METRIC_DEFINITIONS
            )
        ),
    )


def _grant(
    context: P1TextAnalysisInput,
    *,
    fingerprint: str | None = None,
) -> P1LocalAnalysisGrant:
    return P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=(
            context.analysis_window_fingerprint
            if fingerprint is None
            else fingerprint
        ),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
    )


def test_content_canary_never_enters_metric_result_serialization() -> None:
    context = _context()

    results = DEFAULT_TEXT_METRIC_ENGINE.compute(context, _grant(context))
    rendered = "".join(result.model_dump_json() for result in results)

    assert CANARY not in rendered
    assert "Build a report" not in rendered
    assert all(
        evidence.message_id == "c" * 64
        for result in results
        for evidence in result.evidence
    )


def test_mismatched_capability_fails_before_ephemeral_feature_extraction() -> None:
    context = _context()

    class RecordingExtractor:
        algorithm_id = "synthetic.recording"
        algorithm_version = "1"

        def __init__(self) -> None:
            self.called = False

        def extract(self, analysis_input: P1TextAnalysisInput) -> object:
            self.called = True
            raise AssertionError("privacy gate must precede text extraction")

    extractor = RecordingExtractor()
    engine = TextMetricEngine(extractor=extractor)  # type: ignore[arg-type]

    with pytest.raises(TextAnalysisPrivacyError, match="does not match"):
        engine.compute(context, _grant(context, fingerprint="d" * 64))
    assert extractor.called is False
