from __future__ import annotations

from pydantic import SecretStr

from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.analysis.text_source import (
    EphemeralTextAnalysisSource,
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceAccessGrant,
)
from prompt_enhancer.domain import DataTier, Provider


_SESSION_ID = "a" * 64
_MESSAGE_ID = "b" * 64
_WINDOW_ID = "c" * 64


def _synthetic_result(profile: TextTaskProfile) -> P1TextAnalysisInput:
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_SESSION_ID,
        provider_version="synthetic-1",
        adapter_version="synthetic-1",
        source_schema_version="synthetic-1",
        content_schema_version="synthetic-1",
        redactor_version="synthetic-1",
        text_extraction_complete=True,
        available_message_kinds=frozenset({TextMessageKind.REQUEST}),
        analysis_window_fingerprint=_WINDOW_ID,
        focus_message_id=_MESSAGE_ID,
        observed_message_count=1,
        eligible_message_count=1,
        messages=(
            EphemeralRedactedMessage(
                message_id=_MESSAGE_ID,
                sequence=0,
                role=TextRole.USER,
                kind=TextMessageKind.REQUEST,
                language=TextLanguage.ENGLISH,
                text=SecretStr("Build the reserved example report locally."),
            ),
        ),
        task_profile=profile,
    )


class SyntheticTextSource:
    provider = Provider.SYNTHETIC
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput:
        assert selection.provider is self.provider
        assert grant.session_id == selection.session_id
        return _synthetic_result(task_profile)


def test_synthetic_source_satisfies_provider_neutral_application_port() -> None:
    profile = TextTaskProfile(applicability=())
    selection = TextAnalysisSelection(
        provider=Provider.SYNTHETIC,
        session_id=_SESSION_ID,
        max_messages=1,
        max_characters=1_000,
    )
    grant = TextSourceAccessGrant(
        purpose=selection.purpose,
        provider=selection.provider,
        session_id=selection.session_id,
        data_tier=DataTier.REDACTED_CONTENT,
        per_run_confirmation_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )
    source = SyntheticTextSource()

    assert isinstance(source, EphemeralTextAnalysisSource)
    assert source.read(
        selection=selection,
        grant=grant,
        task_profile=profile,
    ).provider is Provider.SYNTHETIC
