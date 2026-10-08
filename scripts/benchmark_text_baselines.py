"""Opt-in local benchmark for the deterministic P1 text metric upper bound.

Only generated synthetic messages are analyzed.  Throughput is diagnostic and is
not asserted in the test suite because machines and concurrent load differ.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from time import perf_counter

from pydantic import SecretStr


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    TEXT_METRIC_DEFINITIONS,
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
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.domain import DataTier, Provider


def _identifier(index: int) -> str:
    return hashlib.sha256(f"synthetic-message-{index}".encode()).hexdigest()


def _bounded_context() -> tuple[P1TextAnalysisInput, P1LocalAnalysisGrant]:
    request = (
        "Build a local PNG dashboard for example users so that they can verify "
        "the synthetic result. The export must exist and tests must pass. "
    )
    filler = (
        "Observed synthetic dashboard action with local PNG export and passing test. "
        * 11
    )
    messages = tuple(
        EphemeralRedactedMessage(
            message_id=_identifier(index),
            sequence=index,
            role=TextRole.USER if index == 0 else TextRole.AGENT,
            kind=(
                TextMessageKind.REQUEST
                if index == 0
                else TextMessageKind.ACTION
            ),
            language=TextLanguage.ENGLISH,
            text=SecretStr(request if index == 0 else filler),
        )
        for index in range(500)
    )
    context = P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id="a" * 64,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-schema-1",
        content_schema_version="redacted-message-1",
        redactor_version="synthetic-redactor-1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.ACTION}
        ),
        analysis_window_fingerprint="b" * 64,
        focus_message_id=messages[0].message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=TextTaskProfile(
            applicability=tuple(
                MetricApplicabilityDecision(
                    metric_key=definition.key,
                    applicability=MetricApplicability.APPLICABLE,
                    basis=ApplicabilityBasis.DETERMINISTIC_RULE,
                )
                for definition in TEXT_METRIC_DEFINITIONS
            ),
            expected_constraint_kinds=(ConstraintKind.PRIVACY,),
            expected_deliverable_slots=(
                DeliverableSlot.ARTIFACT,
                DeliverableSlot.FORMAT,
                DeliverableSlot.AUDIENCE,
            ),
            expected_outcome_count=1,
        ),
    )
    grant = P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
    )
    return context, grant


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    arguments = parser.parse_args()
    if not 1 <= arguments.iterations <= 100:
        parser.error("iterations must be between 1 and 100")

    context, grant = _bounded_context()
    DEFAULT_TEXT_METRIC_ENGINE.compute(context, grant)
    started = perf_counter()
    for _ in range(arguments.iterations):
        DEFAULT_TEXT_METRIC_ENGINE.compute(context, grant)
    elapsed = perf_counter() - started
    character_count = sum(
        len(message.text.get_secret_value()) for message in context.messages
    )
    print(f"iterations={arguments.iterations}")
    print(f"messages_per_document={len(context.messages)}")
    print(f"characters_per_document={character_count}")
    print(f"elapsed_seconds={elapsed:.6f}")
    print(f"documents_per_second={arguments.iterations / elapsed:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
