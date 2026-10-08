"""Adversarial synthetic checks for the Claude hooks r7 provider ceiling."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import sqlite3

from pydantic import SecretStr
import pytest

from prompt_enhancer.application.analysis.metric_operability import (
    MetricShippedPathState,
    metric_operability_catalog,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION,
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SafeEventTypedEvidenceProjector,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
    EphemeralRedactedActionDescriptor,
)
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    ToolCategory,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.adapter import (
    ClaudeCodeHookAdapter,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.contracts import (
    ADAPTER_VERSION,
    SOURCE_SCHEMA_VERSION,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.ledger import (
    HookLedgerSnapshotError,
    LedgerSessionSnapshot,
    ledger_read_boundary_fingerprint,
    validate_ledger_session_snapshot,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.r7_readiness import (
    ClaudeHookEphemeralDescriptorBatch,
    ClaudeHooksR7Blocker,
    build_claude_hooks_r7_readiness,
    validate_ephemeral_descriptor_batch,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import (
    ReceiverStatus,
    receive,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.telemetry import (
    TelemetryCounters,
    TelemetrySessionView,
)
from prompt_enhancer.infrastructure.redaction.deterministic import (
    DETERMINISTIC_REDACTOR_VERSION,
)


T0 = datetime(2040, 1, 2, 9, 0, tzinfo=UTC)
RAW_SESSION = "synthetic-session-r7-001"
SYNTHETIC_CWD = "/srv/example.invalid/workspaces/r7-demo"
PRIVATE_INVOCATION = "synthetic-private-invocation-marker"
PRIVATE_EFFECT = "synthetic-private-effect-marker"


def _payload(name: str, **extra: object) -> io.BytesIO:
    payload: dict[str, object] = {
        "session_id": RAW_SESSION,
        "cwd": SYNTHETIC_CWD,
        "hook_event_name": name,
    }
    payload.update(extra)
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


@pytest.fixture
def hook_home(tmp_path: Path) -> Path:
    bootstrap_local_application(AppSettings(home=tmp_path))
    Database(tmp_path / "metrics.sqlite3").grant_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    return tmp_path


def _drive(
    home: Path,
    *,
    times: tuple[datetime, ...] | None = None,
    include_unknown: bool = False,
) -> None:
    settings = AppSettings(home=home)
    steps = [
        _payload("SessionStart", source="startup"),
        _payload(
            "PreToolUse",
            tool_name="Bash",
            tool_use_id="synthetic-tool-use-001",
            tool_input={"command": PRIVATE_INVOCATION},
        ),
        _payload(
            "PostToolUse",
            tool_name="Bash",
            tool_use_id="synthetic-tool-use-001",
            tool_input={"command": PRIVATE_INVOCATION},
            tool_response={"status": PRIVATE_EFFECT},
        ),
    ]
    if include_unknown:
        steps.append(_payload("SyntheticFutureHook"))
    steps.append(_payload("SessionEnd", reason="prompt_input_exit"))
    schedule = times or tuple(T0 + timedelta(seconds=index) for index in range(len(steps)))
    assert len(schedule) == len(steps)
    for item, observed_at in zip(steps, schedule, strict=True):
        outcome = receive(
            item,
            settings=settings,
            now=lambda value=observed_at: value,
        )
        assert outcome.status is ReceiverStatus.APPENDED


def _snapshot(home: Path) -> LedgerSessionSnapshot:
    ledger = Database(home / "metrics.sqlite3").claude_hook_ledger()
    session = ledger.list_sessions(limit=2)[0]
    snapshot = ledger.read_session_snapshot(session.hook_session_id)
    assert snapshot is not None
    return snapshot


def _rebind_snapshot(
    snapshot: LedgerSessionSnapshot,
    *,
    telemetry: TelemetrySessionView | None = None,
) -> LedgerSessionSnapshot:
    selected_telemetry = snapshot.telemetry if telemetry is None else telemetry
    fingerprint = ledger_read_boundary_fingerprint(
        snapshot.session,
        snapshot.events,
        selected_telemetry,
        snapshot.telemetry_requests,
    )
    boundary = snapshot.boundary.model_copy(
        update={"boundary_fingerprint": fingerprint}
    )
    return replace(snapshot, telemetry=selected_telemetry, boundary=boundary)


def _descriptor_batch(
    snapshot: LedgerSessionSnapshot,
) -> ClaudeHookEphemeralDescriptorBatch:
    receipt = build_claude_hooks_r7_readiness(snapshot)
    descriptors = []
    for candidate in receipt.candidate_metadata:
        descriptors.append(
            EphemeralRedactedActionDescriptor(
                source_reference_id=candidate.source_reference_id,
                event_kind=candidate.event_kind,
                tool_name=SecretStr("Bash"),
                invocation_preview=SecretStr(PRIVATE_INVOCATION),
                result_or_effect_preview=(
                    None
                    if candidate.event_kind is EventKind.TOOL_START
                    else SecretStr(PRIVATE_EFFECT)
                ),
                invocation_truncated=False,
                result_or_effect_truncated=False,
                redactor_version=DETERMINISTIC_REDACTOR_VERSION,
                candidate_metadata_fingerprint_version=(
                    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                ),
                candidate_metadata_fingerprint=(
                    candidate.candidate_metadata_fingerprint
                ),
            )
        )
    return ClaudeHookEphemeralDescriptorBatch(
        hook_session_id=snapshot.session.hook_session_id,
        source_boundary_fingerprint=snapshot.boundary.boundary_fingerprint,
        descriptor_algorithm_version=ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
        redactor_version=DETERMINISTIC_REDACTOR_VERSION,
        extraction_complete=True,
        descriptors=tuple(descriptors),
    )


def test_atomic_admitted_row_boundary_is_stable_but_never_promotes(
    hook_home: Path,
) -> None:
    _drive(hook_home)
    first = _snapshot(hook_home)
    second = _snapshot(hook_home)

    assert first.boundary == second.boundary
    assert first.boundary.admitted_events_enumerated is True
    assert [item.sequence for item in first.events] == list(range(4))
    receipt = build_claude_hooks_r7_readiness(first)
    assert receipt.stable_source_boundary is True
    assert receipt.admitted_event_enumeration_complete is True
    assert receipt.admitted_action_enumeration_complete is True
    assert receipt.admitted_action_candidate_count == 2
    assert receipt.release_ready is False and receipt.operability_promoted is False
    assert ClaudeHooksR7Blocker.COMPLETE_DELIVERY_UNPROVEN in receipt.blockers
    assert ClaudeHooksR7Blocker.EPHEMERAL_DESCRIPTORS_UNAVAILABLE in receipt.blockers
    assert receipt.complete_provider_delivery_proven is False
    assert receipt.same_read_candidate_descriptor_binding_complete is False


@pytest.mark.parametrize(
    "mutation", ["duplicate", "reordered", "missing", "cross_session", "boundary"]
)
def test_duplicate_reordered_missing_or_incoherent_boundary_fails_closed(
    hook_home: Path,
    mutation: str,
) -> None:
    _drive(hook_home)
    snapshot = _snapshot(hook_home)
    if mutation == "duplicate":
        events = (snapshot.events[0], snapshot.events[0], *snapshot.events[2:])
        attacked = replace(snapshot, events=events)
    elif mutation == "reordered":
        events = (snapshot.events[1], snapshot.events[0], *snapshot.events[2:])
        attacked = replace(snapshot, events=events)
    elif mutation == "missing":
        attacked = replace(snapshot, events=snapshot.events[:-1])
    elif mutation == "cross_session":
        foreign = snapshot.events[0].model_copy(
            update={"hook_session_id": "e" * 64}
        )
        attacked = replace(snapshot, events=(foreign, *snapshot.events[1:]))
    else:
        attacked = replace(
            snapshot,
            boundary=snapshot.boundary.model_copy(
                update={"boundary_fingerprint": "f" * 64}
            ),
        )

    receipt = build_claude_hooks_r7_readiness(attacked)
    assert receipt.stable_source_boundary is False
    assert receipt.admitted_event_enumeration_complete is False
    assert receipt.admitted_action_enumeration_complete is False
    assert receipt.candidate_metadata == ()
    assert ClaudeHooksR7Blocker.SOURCE_BOUNDARY_INVALID in receipt.blockers


def test_receiver_clock_ambiguity_and_unknown_union_variant_are_named(
    hook_home: Path,
) -> None:
    times = (T0, T0 + timedelta(seconds=2), T0 + timedelta(seconds=1), T0 + timedelta(seconds=3), T0 + timedelta(seconds=4))
    _drive(hook_home, times=times, include_unknown=True)
    receipt = build_claude_hooks_r7_readiness(_snapshot(hook_home))

    assert receipt.stable_source_boundary is True
    assert receipt.receiver_clock_order_unambiguous is False
    assert ClaudeHooksR7Blocker.RECEIVER_CLOCK_AMBIGUOUS in receipt.blockers
    assert ClaudeHooksR7Blocker.UNKNOWN_EVENT_VARIANT in receipt.blockers


def test_exact_ephemeral_descriptor_binding_validates_but_is_not_composed_authority(
    hook_home: Path,
) -> None:
    _drive(hook_home)
    snapshot = _snapshot(hook_home)
    batch = _descriptor_batch(snapshot)

    validation = validate_ephemeral_descriptor_batch(snapshot, batch)
    assert validation.complete is True and validation.blockers == ()
    # The production readiness function intentionally has no descriptor input:
    # a fresh process/restart cannot recover these strings from the ledger.
    restarted = build_claude_hooks_r7_readiness(snapshot)
    assert restarted.ephemeral_redacted_descriptors_complete is False
    assert ClaudeHooksR7Blocker.EPHEMERAL_DESCRIPTORS_UNAVAILABLE in restarted.blockers


def test_descriptor_metadata_and_snapshot_drift_fail_closed(hook_home: Path) -> None:
    _drive(hook_home)
    snapshot_a = _snapshot(hook_home)
    batch = _descriptor_batch(snapshot_a)
    first = batch.descriptors[0]
    wrong = "0" * 64 if first.candidate_metadata_fingerprint != "0" * 64 else "1" * 64
    drifted_descriptor = first.model_copy(
        update={"candidate_metadata_fingerprint": wrong}
    )
    drifted_batch = batch.model_copy(
        update={"descriptors": (drifted_descriptor, *batch.descriptors[1:])}
    )
    metadata_result = validate_ephemeral_descriptor_batch(
        snapshot_a, drifted_batch
    )
    assert metadata_result.complete is False
    assert ClaudeHooksR7Blocker.CANDIDATE_METADATA_DRIFT in metadata_result.blockers

    settings = AppSettings(home=hook_home)
    assert receive(
        _payload("PreToolUse", tool_name="Read", tool_use_id="synthetic-tool-use-002"),
        settings=settings,
        now=lambda: T0 + timedelta(minutes=1),
    ).status is ReceiverStatus.APPENDED
    snapshot_b = _snapshot(hook_home)
    boundary_result = validate_ephemeral_descriptor_batch(snapshot_b, batch)
    assert boundary_result.complete is False
    assert ClaudeHooksR7Blocker.DESCRIPTOR_SNAPSHOT_DRIFT in boundary_result.blockers


def test_descriptor_controls_redactor_drift_and_raw_content_never_enter_receipts_or_store(
    hook_home: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _drive(hook_home)
    snapshot = _snapshot(hook_home)
    batch = _descriptor_batch(snapshot)
    attacked = batch.descriptors[0].model_copy(
        update={"invocation_preview": SecretStr(PRIVATE_INVOCATION + "\u202e")}
    )
    attacked_batch = batch.model_copy(
        update={"descriptors": (attacked, *batch.descriptors[1:])}
    )
    control_result = validate_ephemeral_descriptor_batch(snapshot, attacked_batch)
    assert ClaudeHooksR7Blocker.DESCRIPTOR_CONTENT_INVALID in control_result.blockers

    truncated = batch.descriptors[0].model_copy(update={"invocation_truncated": True})
    truncated_batch = batch.model_copy(
        update={"descriptors": (truncated, *batch.descriptors[1:])}
    )
    truncated_result = validate_ephemeral_descriptor_batch(
        snapshot, truncated_batch
    )
    assert ClaudeHooksR7Blocker.DESCRIPTOR_CONTENT_INVALID in truncated_result.blockers

    redactor_drift = batch.model_copy(update={"redactor_version": "synthetic-redactor-v2"})
    redactor_result = validate_ephemeral_descriptor_batch(snapshot, redactor_drift)
    assert ClaudeHooksR7Blocker.REDACTOR_VERSION_MISMATCH in redactor_result.blockers

    receipt_text = build_claude_hooks_r7_readiness(snapshot).model_dump_json()
    validation_text = control_result.model_dump_json()
    assert PRIVATE_INVOCATION not in repr(batch)
    assert PRIVATE_EFFECT not in repr(batch)
    assert PRIVATE_INVOCATION not in receipt_text + validation_text
    assert PRIVATE_EFFECT not in receipt_text + validation_text
    assert PRIVATE_INVOCATION not in caplog.text and PRIVATE_EFFECT not in caplog.text

    connection = sqlite3.connect(hook_home / "metrics.sqlite3")
    try:
        dump = "\n".join(
            repr(row)
            for table in (
                "claude_code_hook_sessions",
                "claude_code_hook_events",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
        )
    finally:
        connection.close()
    assert PRIVATE_INVOCATION not in dump and PRIVATE_EFFECT not in dump


def test_overflow_and_unsupported_provider_version_do_not_create_partial_authority(
    hook_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drive(hook_home)
    snapshot = _snapshot(hook_home)
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.providers.claude_code_hooks.r7_readiness.MAX_REQUIREMENT_ACTION_CANDIDATES",
        1,
    )
    overflow = build_claude_hooks_r7_readiness(snapshot)
    assert overflow.admitted_action_enumeration_complete is False
    assert overflow.candidate_metadata == ()
    assert ClaudeHooksR7Blocker.CANDIDATE_OVERFLOW in overflow.blockers

    telemetry = TelemetrySessionView(
        hook_session_id=snapshot.session.hook_session_id,
        hook_project_id=snapshot.session.hook_project_id,
        provider_version="synthetic-provider-v999",
        first_received_at=T0,
        last_received_at=T0,
        request_count=0,
        counters=None,
    )
    versioned = build_claude_hooks_r7_readiness(
        _rebind_snapshot(snapshot, telemetry=telemetry)
    )
    assert ClaudeHooksR7Blocker.PROVIDER_VERSION_UNSUPPORTED in versioned.blockers
    assert versioned.release_ready is False


@pytest.mark.parametrize(
    "identity_drift",
    (
        "summary_session",
        "summary_project",
        "counters_session",
        "counters_project",
    ),
)
def test_telemetry_summary_and_nested_counter_identity_drift_fail_closed(
    hook_home: Path,
    identity_drift: str,
) -> None:
    _drive(hook_home)
    snapshot = _snapshot(hook_home)
    session_id = snapshot.session.hook_session_id
    project_id = snapshot.session.hook_project_id
    foreign_session_id = "a" * 64
    foreign_project_id = "b" * 64
    counters = TelemetryCounters(
        hook_session_id=(
            foreign_session_id
            if identity_drift == "counters_session"
            else session_id
        ),
        hook_project_id=(
            foreign_project_id
            if identity_drift == "counters_project"
            else project_id
        ),
        provider_version="synthetic-provider-v1",
        reported_at=T0,
    )
    telemetry = TelemetrySessionView(
        hook_session_id=(
            foreign_session_id
            if identity_drift == "summary_session"
            else session_id
        ),
        hook_project_id=(
            foreign_project_id
            if identity_drift == "summary_project"
            else project_id
        ),
        provider_version="synthetic-provider-v1",
        first_received_at=T0,
        last_received_at=T0,
        request_count=0,
        counters=counters,
    )
    attacked = _rebind_snapshot(snapshot, telemetry=telemetry)

    with pytest.raises(HookLedgerSnapshotError):
        validate_ledger_session_snapshot(attacked)
    readiness = build_claude_hooks_r7_readiness(attacked)
    assert readiness.stable_source_boundary is False
    assert ClaudeHooksR7Blocker.SOURCE_BOUNDARY_INVALID in readiness.blockers


def test_composed_hook_projection_uses_exact_hook_provenance_and_mismatch_fails_closed(
    hook_home: Path,
) -> None:
    _drive(hook_home)
    application = bootstrap_local_application(AppSettings(home=hook_home))
    application.create_ingestion_service().ingest(
        ClaudeCodeHookAdapter(application.database.claude_hook_ledger())
    )
    row = next(
        item
        for item in application.database.list_sessions(limit=10, offset=0)
        if item["provider"] == Provider.CLAUDE_CODE.value
    )
    session_id = str(row["session_id"])
    projector = application.create_typed_evidence_projector()
    projection = projector.project(
        provider=Provider.CLAUDE_CODE,
        session_id=session_id,
    )
    assert projection is not None
    exact = projector.descriptor_for_projection(projection)
    assert projection.provenance.adapter_version == ADAPTER_VERSION
    assert projection.provenance.source_schema_version == SOURCE_SCHEMA_VERSION
    assert exact.adapter_version == ADAPTER_VERSION
    assert exact.capabilities == (CapabilityKey.TOOL_EVENTS,)
    transcript_default = projector.descriptor_for(Provider.CLAUDE_CODE)
    assert transcript_default.adapter_version != exact.adapter_version

    session = application.database.get_session(session_id)
    assert session is not None
    mismatched = session.model_copy(
        update={"adapter_version": "synthetic-unregistered-hook-adapter-v1"}
    )

    class _Source:
        def get_session(self, selected: str) -> SafeSession | None:
            return mismatched if selected == session_id else None

        def get_session_events(self, selected: str) -> tuple[SafeEvent, ...]:
            assert selected == session_id
            return application.database.get_session_events(session_id)

    class _Ids:
        def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
            return hashlib.sha256((namespace + "|" + "|".join(values)).encode()).hexdigest()

    strict = SafeEventTypedEvidenceProjector(
        _Source(),
        _Ids(),
        projector.descriptor,
        descriptors={Provider.CLAUDE_CODE: transcript_default},
        source_descriptors={
            (
                Provider.CLAUDE_CODE,
                ADAPTER_VERSION,
                SOURCE_SCHEMA_VERSION,
            ): exact,
        },
    )
    with pytest.raises(ValueError, match="not registered"):
        strict.project(provider=Provider.CLAUDE_CODE, session_id=session_id)


def test_operability_partition_remains_16_0_4_with_no_r7_promotion() -> None:
    catalog = metric_operability_catalog()
    assert (
        catalog.shipped_path_count,
        catalog.task_profile_configuration_gap_count,
        catalog.provider_adapter_gap_count,
    ) == (16, 0, 4)
    action = next(
        item
        for item in catalog.entries
        if item.metric_key == "logic.requirement_action_traceability"
    )
    assert action.shipped_path_state is MetricShippedPathState.PROVIDER_ADAPTER_REQUIRED
