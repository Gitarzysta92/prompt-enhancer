"""Claude Code transcript text source, text-window probe, and default grants.

Synthetic transcripts only; the tests run inside an isolated Claude home and
never touch a real ``~/.claude``.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.providers.claude_code_hooks import (
    text_source as text_source_module,
)

from prompt_enhancer.application.analysis.text_contracts import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    TextAnalysisPrivacyError,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    requirement_action_candidate_metadata_fingerprint,
)
from prompt_enhancer.application.analysis.text_source import (
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceAccessGrant,
    TextSourceFailureReason,
    TextSourceReadError,
)
from prompt_enhancer.application.providers import (
    CapabilityKey,
    CapabilityState,
    CompatibilityReasonCode,
    CompatibilityState,
    ExtractionCompletenessState,
    ProviderSurface,
)
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.providers.codex_app_server.content_contracts import (
    CodexTextContentLimits,
    CodexTextItemKind,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.text_source import (
    CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR,
    TEXT_ADAPTER_VERSION,
    TEXT_SOURCE_SCHEMA_VERSION,
    ClaudeTranscriptTextAnalysisSource,
    ClaudeTranscriptTextWindowProbe,
    extract_fragments,
    sample_transcript_structure,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.transcript_adapter import (
    parse_events,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.transcript_reader import (
    ClaudeTranscriptReader,
    catalog_session_id_for,
)
from prompt_enhancer.privacy import Pseudonymizer


CWD = "/srv/example/workspaces/text-demo"
SESSION = "0f7f5d2e-1111-4a4a-8888-aaaaaaaaaaaa"


def _pseudonymizer() -> Pseudonymizer:
    return Pseudonymizer(bytes(range(32)))


def _row(kind: str, content: object, second: int, **extra: object) -> str:
    at = datetime(2026, 3, 1, 9, 0, second, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    record: dict[str, object] = {
        "type": kind,
        "timestamp": at,
        "sessionId": SESSION,
        "cwd": CWD,
        "version": "2.1.0",
        "message": {"role": kind, "content": content},
    }
    record.update(extra)
    return json.dumps(record)


def write_transcript(claude_home: Path, *, unknown_block: bool = False) -> Path:
    project_dir = claude_home / "projects" / "-srv-example-workspaces-text-demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "summary", "summary": "ignored", "leafUuid": "x"}),
        _row("user", "<command-name>/clear</command-name>", 0),
        _row("user", "ignored meta", 1, isMeta=True),
        _row("user", "Please add a retry to the example uploader.", 2),
        _row(
            "assistant",
            [
                {"type": "thinking", "thinking": "never a message"},
                {"type": "text", "text": "I will add a bounded retry first."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "TodoWrite",
                    "input": {"todos": [{"content": "Add retry", "status": "in_progress"}, {"content": "Run tests", "status": "pending"}]},
                },
            ],
            5,
        ),
        _row("user", [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}], 6),
        _row("assistant", [{"type": "text", "text": "Done - the uploader now retries three times."}], 9),
        _row("user", [{"type": "text", "text": "Great, now also log each retry."}], 12),
    ]
    if unknown_block:
        lines.append(_row("assistant", [{"type": "mystery", "payload": 1}], 13))
    lines.append(_row("assistant", [{"type": "text", "text": "Logging added on every attempt."}], 15))
    path = project_dir / f"{SESSION}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def claude_home(tmp_path: Path) -> Path:
    home = tmp_path / "claude-home"
    (home / "projects").mkdir(parents=True)
    return home


def test_extract_fragments_keeps_messages_and_plans_only(claude_home: Path) -> None:
    path = write_transcript(claude_home)

    thread = extract_fragments(path, limits=CodexTextContentLimits())

    kinds = [fragment.kind for fragment in thread.fragments]
    assert kinds == [
        CodexTextItemKind.USER_MESSAGE,
        CodexTextItemKind.AGENT_MESSAGE,
        CodexTextItemKind.PLAN,
        CodexTextItemKind.AGENT_MESSAGE,
        CodexTextItemKind.USER_MESSAGE,
        CodexTextItemKind.AGENT_MESSAGE,
    ]
    texts = [fragment.text.get_secret_value() for fragment in thread.fragments]
    assert "ignored meta" not in " ".join(texts)
    assert "/clear" not in " ".join(texts)
    assert "never a message" not in " ".join(texts)
    assert texts[2] == "- [in_progress] Add retry\n- [pending] Run tests"
    # Prompts open turns; the agent's reply and plan share the prompt's turn.
    assert [f.turn_id.get_secret_value() for f in thread.fragments] == [
        "turn-1", "turn-1", "turn-1", "turn-1", "turn-2", "turn-2",
    ]
    assert thread.thread_id.get_secret_value() == SESSION
    assert thread.extraction_complete is True
    assert thread.older_history_truncated is False
    assert thread.unclassified_omission is False


def test_extract_fragments_bounds_history_and_flags_truncation(claude_home: Path) -> None:
    path = write_transcript(claude_home)
    limits = CodexTextContentLimits(max_text_fragments_per_session=2)

    thread = extract_fragments(path, limits=limits)

    assert len(thread.fragments) == 2
    assert thread.older_history_truncated is True
    assert thread.fragments[-1].kind is CodexTextItemKind.AGENT_MESSAGE


def test_extract_fragments_marks_unknown_content_variant_incomplete(
    claude_home: Path,
) -> None:
    path = write_transcript(claude_home, unknown_block=True)

    thread = extract_fragments(path, limits=CodexTextContentLimits())

    assert thread.extraction_complete is False
    assert thread.unclassified_omission is True


def _selection(session_id: str) -> TextAnalysisSelection:
    return TextAnalysisSelection(provider=Provider.CLAUDE_CODE, session_id=session_id)


def _grant(selection: TextAnalysisSelection) -> TextSourceAccessGrant:
    return TextSourceAccessGrant(
        purpose=TextAnalysisPurpose.TEXT_ANALYSIS,
        provider=selection.provider,
        session_id=selection.session_id,
        data_tier=DataTier.REDACTED_CONTENT,
        per_run_confirmation_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )


def test_source_reads_transcript_into_p1_input(claude_home: Path) -> None:
    path = write_transcript(claude_home)
    pseudonymizer = _pseudonymizer()
    reader = ClaudeTranscriptReader(pseudonymizer, claude_home=claude_home)
    source = ClaudeTranscriptTextAnalysisSource(pseudonymizer, locate=reader.locate)
    selection = _selection(catalog_session_id_for(pseudonymizer, SESSION))

    result = source.read(selection=selection, grant=_grant(selection), task_profile=TextTaskProfile(applicability=()))

    assert result.provider is Provider.CLAUDE_CODE
    assert result.provider_version == "2.1.0"
    assert result.adapter_version == TEXT_ADAPTER_VERSION
    assert result.source_schema_version == TEXT_SOURCE_SCHEMA_VERSION
    assert result.session_id == selection.session_id
    roles = [message.role for message in result.messages]
    assert TextRole.USER in roles and TextRole.AGENT in roles
    kinds = {message.kind for message in result.messages}
    assert TextMessageKind.PLAN in kinds
    # The focus is the newest prompt; nothing before it is lost to a window bound.
    focus = next(m for m in result.messages if m.message_id == result.focus_message_id)
    assert focus.role is TextRole.USER
    assert "log each retry" in focus.text.get_secret_value()
    assert result.action_descriptor_extraction_complete is True
    assert len(result.action_descriptors) == 2
    assert len({item.source_reference_id for item in result.action_descriptors}) == 2
    parsed = parse_events(path, SESSION)
    event_by_source = {
        item.source_event_id.get_secret_value(): item for item in parsed.events
    }
    expected_receipts = {}
    for item in parsed.action_details:
        raw_source_id = item.source_event_id.get_secret_value()
        event = event_by_source[raw_source_id]
        safe_source_id = pseudonymizer.pseudonymize(
            f"claude_code:event:{selection.session_id}",
            raw_source_id,
        )
        expected_receipts[safe_source_id] = (
            requirement_action_candidate_metadata_fingerprint(
                source_reference_id=safe_source_id,
                sequence=event.sequence * 4,
                event_kind=item.event_kind,
                tool_category=item.tool_category,
                occurred_at=item.occurred_at,
                duration_ms=item.duration_ms,
                family=item.family,
                state=item.state,
            )
        )
    assert {
        item.source_reference_id: (
            item.candidate_metadata_fingerprint_version,
            item.candidate_metadata_fingerprint,
        )
        for item in result.action_descriptors
    } == {
        source_id: (
            ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
            fingerprint,
        )
        for source_id, fingerprint in expected_receipts.items()
    }


def test_analysis_window_binds_same_id_metadata_and_descriptor_drift(
    claude_home: Path,
) -> None:
    path = write_transcript(claude_home)
    pseudonymizer = _pseudonymizer()
    reader = ClaudeTranscriptReader(pseudonymizer, claude_home=claude_home)
    source = ClaudeTranscriptTextAnalysisSource(
        pseudonymizer,
        locate=reader.locate,
    )
    selection = _selection(catalog_session_id_for(pseudonymizer, SESSION))
    profile = TextTaskProfile(applicability=())

    first = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=profile,
    )
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace(
            "2026-03-01T09:00:06Z",
            "2026-03-01T09:00:07Z",
            1,
        ),
        encoding="utf-8",
    )
    metadata_drift = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=profile,
    )

    assert tuple(item.source_reference_id for item in first.action_descriptors) == tuple(
        item.source_reference_id for item in metadata_drift.action_descriptors
    )
    assert tuple(
        item.result_or_effect_preview for item in first.action_descriptors
    ) == tuple(
        item.result_or_effect_preview for item in metadata_drift.action_descriptors
    )
    assert tuple(
        item.candidate_metadata_fingerprint for item in first.action_descriptors
    ) != tuple(
        item.candidate_metadata_fingerprint
        for item in metadata_drift.action_descriptors
    )
    assert first.analysis_window_fingerprint != (
        metadata_drift.analysis_window_fingerprint
    )

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"content": "ok"',
            '"content": "changed"',
            1,
        ),
        encoding="utf-8",
    )
    descriptor_drift = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=profile,
    )
    assert tuple(
        item.candidate_metadata_fingerprint
        for item in metadata_drift.action_descriptors
    ) == tuple(
        item.candidate_metadata_fingerprint
        for item in descriptor_drift.action_descriptors
    )
    assert tuple(
        item.result_or_effect_preview for item in metadata_drift.action_descriptors
    ) != tuple(
        item.result_or_effect_preview for item in descriptor_drift.action_descriptors
    )
    assert metadata_drift.analysis_window_fingerprint != (
        descriptor_drift.analysis_window_fingerprint
    )


def test_source_uses_one_byte_snapshot_across_all_transcript_parsers(
    claude_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An equal-size path replacement cannot splice text A with actions B."""

    path = write_transcript(claude_home)
    pseudonymizer = _pseudonymizer()
    reader = ClaudeTranscriptReader(pseudonymizer, claude_home=claude_home)
    source = ClaudeTranscriptTextAnalysisSource(
        pseudonymizer,
        locate=reader.locate,
    )
    selection = _selection(catalog_session_id_for(pseudonymizer, SESSION))
    profile = TextTaskProfile(applicability=())
    baseline = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=profile,
    )

    original = path.read_text(encoding="utf-8")
    replacement = original.replace("add a retry", "add a queue", 1).replace(
        '"content": "ok"',
        '"content": "NO"',
        1,
    )
    assert replacement != original
    assert len(replacement.encode("utf-8")) == len(original.encode("utf-8"))
    original_stat = path.stat()
    real_extract = text_source_module.extract_fragments

    def replace_after_fragment_parse(
        transcript_path: Path,
        *,
        limits: CodexTextContentLimits,
        snapshot_text: str | None = None,
        snapshot_complete: bool = True,
    ):
        thread = real_extract(
            transcript_path,
            limits=limits,
            snapshot_text=snapshot_text,
            snapshot_complete=snapshot_complete,
        )
        transcript_path.write_text(replacement, encoding="utf-8")
        os.utime(
            transcript_path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        return thread

    monkeypatch.setattr(
        text_source_module,
        "extract_fragments",
        replace_after_fragment_parse,
    )
    observed = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=profile,
    )

    assert "add a queue" in path.read_text(encoding="utf-8")
    assert observed.analysis_window_fingerprint == baseline.analysis_window_fingerprint
    assert observed.action_descriptor_extraction_complete is True
    observed_text = " ".join(
        item.text.get_secret_value() for item in observed.messages
    )
    assert "add a retry" in observed_text
    assert "add a queue" not in observed_text
    results = tuple(
        (
            None
            if item.result_or_effect_preview is None
            else item.result_or_effect_preview.get_secret_value()
        )
        for item in observed.action_descriptors
    )
    assert any(value is not None and '"ok"' in value for value in results)
    assert all(value is None or '"NO"' not in value for value in results)


def test_source_refuses_other_provider_and_unknown_session(claude_home: Path) -> None:
    write_transcript(claude_home)
    pseudonymizer = _pseudonymizer()
    reader = ClaudeTranscriptReader(pseudonymizer, claude_home=claude_home)
    source = ClaudeTranscriptTextAnalysisSource(pseudonymizer, locate=reader.locate)

    codex_selection = TextAnalysisSelection(provider=Provider.CODEX, session_id="a" * 64)
    with pytest.raises(TextAnalysisPrivacyError):
        source.read(selection=codex_selection, grant=_grant(codex_selection), task_profile=TextTaskProfile(applicability=()))

    missing = _selection(catalog_session_id_for(pseudonymizer, "not-a-real-session"))
    with pytest.raises(TextSourceReadError) as failure:
        source.read(selection=missing, grant=_grant(missing), task_profile=TextTaskProfile(applicability=()))
    assert failure.value.reason is TextSourceFailureReason.SELECTION_SNAPSHOT_MISS


def test_probe_reports_complete_when_structure_is_known(claude_home: Path) -> None:
    write_transcript(claude_home)
    probe = ClaudeTranscriptTextWindowProbe(lambda: claude_home)

    report = probe.check()

    assert report.descriptor is CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR
    assert report.descriptor.surface is ProviderSurface.TEXT_WINDOW
    assert report.state is CompatibilityState.COMPATIBLE
    assert report.extraction.state is ExtractionCompletenessState.COMPLETE
    assert report.provider_version == "2.1.0"
    assert {item.key for item in report.capabilities} == {
        CapabilityKey.USER_MESSAGES,
        CapabilityKey.AGENT_MESSAGES,
        CapabilityKey.PLAN_MESSAGES,
    }
    assert all(item.state is CapabilityState.SUPPORTED for item in report.capabilities)
    assert [reason.code for reason in report.reasons] == [CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED]


def test_probe_degrades_on_unknown_block_and_unavailable_without_root(tmp_path: Path, claude_home: Path) -> None:
    write_transcript(claude_home, unknown_block=True)
    sample = sample_transcript_structure(claude_home)
    assert sample.unknown_block_types == 1

    degraded = ClaudeTranscriptTextWindowProbe(lambda: claude_home).check()
    assert degraded.state is CompatibilityState.DEGRADED
    assert degraded.extraction.state is ExtractionCompletenessState.UNKNOWN
    assert [reason.code for reason in degraded.reasons] == [CompatibilityReasonCode.UNKNOWN_UNION_VARIANT]

    unavailable = ClaudeTranscriptTextWindowProbe(lambda: tmp_path / "nowhere").check()
    assert unavailable.state is CompatibilityState.UNAVAILABLE
    assert unavailable.extraction.state is ExtractionCompletenessState.NONE


def test_default_grants_drive_claude_sessions_through_the_analysis_lane(tmp_path: Path, monkeypatch) -> None:
    """Consent -> index -> default grant -> poll -> the job worker analyses a Claude session."""

    from prompt_enhancer.application.jobs import AnalysisJobState
    from prompt_enhancer.application.providers import ProviderSurfaceCompatibilityPolicy
    from prompt_enhancer.bootstrap import bootstrap_local_application
    from prompt_enhancer.config import AppSettings

    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    write_transcript(claude_home)
    application = bootstrap_local_application(AppSettings(home=tmp_path / "app"))
    catalog = application.create_provider_compatibility_catalog()
    catalog.refresh("claude_code", ProviderSurface.TEXT_WINDOW)
    policy = ProviderSurfaceCompatibilityPolicy(
        catalog,
        surface=ProviderSurface.TEXT_WINDOW,
        required_capabilities=(CapabilityKey.USER_MESSAGES, CapabilityKey.AGENT_MESSAGES, CapabilityKey.PLAN_MESSAGES),
    )
    claude_service = application.create_claude_local_source_service()
    grant_service, _grant_worker, job_worker = application.create_automation_runtime(
        codex_source_service=application.create_codex_local_source_service(),
        session_text_analysis_service=application.create_session_text_analysis_service(policy),
        analysis_job_service=application.create_analysis_job_service(),
        claude_source_service=claude_service,
    )
    application.database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    assert claude_service.index(max_sessions=50).sessions_seen == 1
    project_ids = application.database.list_project_ids(Provider.CLAUDE_CODE)
    assert len(project_ids) == 1
    assert grant_service.ensure_default_grants(Provider.CLAUDE_CODE, project_ids) == 1
    assert grant_service.ensure_default_grants(Provider.CLAUDE_CODE, project_ids) == 0

    polled = grant_service.poll_due()
    assert polled.grants_checked == 1 and polled.jobs_created == 1, polled

    assert job_worker.run_once() is True
    jobs = application.create_analysis_job_service().list(limit=10, offset=0)
    record = jobs.jobs[0]
    assert record.identity.provider is Provider.CLAUDE_CODE
    assert record.state is AnalysisJobState.COMPLETED, record
