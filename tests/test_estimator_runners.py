from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

import pytest

from prompt_enhancer.application.estimators import (
    ArtifactAvailability,
    EvidencePacketReceipt,
    ExecutionDestination,
    ExecutionDisclosure,
    LabelProbability,
    MetricEstimateState,
    MetricValueKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelSource,
    RetentionClass,
    TokenizerIdentity,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.estimator_runners import (
    CLAUDE_CONSUMER_CLI_AUTOMATION_SUPPORTED,
    CodexExecRunner,
    CodexRunRequest,
    CodexRunnerActivationUnavailable,
    CodexRunnerIdentityUnavailable,
    CodexRunnerProtocolError,
    CodexRunnerToolUseRejected,
    ManualImportProtocolError,
    ManualImportRequest,
    ManualNativeExport,
    RunnerCancelled,
    RunnerLimits,
    RunnerMetricJudgment,
    RunnerOutputLimitExceeded,
    RunnerProcessFailed,
    RunnerResponseState,
    RunnerStructuredResponse,
    RunnerTimedOut,
    RunnerWorkspaceLimitExceeded,
    import_manual_native_export,
)


NOW = datetime(2030, 1, 2, 3, 4, tzinfo=timezone.utc)
PACKET = b'{"fixture":"synthetic-estimator-packet-v1"}'
PACKET_DIGEST = hashlib.sha256(PACKET).hexdigest()
QUESTION_DIGEST = hashlib.sha256(b"synthetic-question").hexdigest()
EVIDENCE_DIGEST = hashlib.sha256(b"synthetic-evidence-ref").hexdigest()
APPROVAL_DIGEST = hashlib.sha256(b"synthetic-approval").hexdigest()


def _receipt(payload: bytes = PACKET) -> EvidencePacketReceipt:
    return EvidencePacketReceipt(
        packet_schema_version="packet-1",
        packet_sha256=hashlib.sha256(payload).hexdigest(),
        requirements_sha256=hashlib.sha256(b"requirements").hexdigest(),
        chronology_sha256=hashlib.sha256(b"chronology").hexdigest(),
        retrieval_index_sha256=hashlib.sha256(b"retrieval").hexdigest(),
        provider=Provider.SYNTHETIC,
        adapter_version="adapter-1",
        provider_schema_version="provider-1",
        preprocessing_version="preprocess-1",
        preprocessing_sha256=hashlib.sha256(b"preprocess").hexdigest(),
        redactor_version="redactor-1",
        redactor_sha256=hashlib.sha256(b"redactor").hexdigest(),
        source_record_count=3,
        requirement_count=1,
        action_count=1,
        decision_count=0,
        feedback_count=0,
        verification_count=1,
        opaque_evidence_refs=(EVIDENCE_DIGEST,),
        created_at=NOW,
    )


def _codex_artifact(
    *,
    requested_model: str = "gpt-example-1",
) -> ModelArtifactIdentity:
    return ModelArtifactIdentity(
        source=ModelSource.CODEX_CLI,
        requested_model_id=requested_model,
        served_model_id=requested_model,
        requested_revision="provider-revision-1",
        served_revision="provider-revision-1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        weight_availability=ArtifactAvailability.PROVIDER_MANAGED,
        tokenizer=TokenizerIdentity(
            tokenizer_id="provider-tokenizer-1",
            revision="provider-revision-1",
            availability=ArtifactAvailability.PROVIDER_MANAGED,
        ),
        license_id="provider-terms-1",
    )


def _codex_disclosure() -> ExecutionDisclosure:
    return ExecutionDisclosure(
        destination=ExecutionDestination.CODEX_CLI,
        retention_class=RetentionClass.PROVIDER_30_DAY,
        retention_days=30,
        disclosure_version="disclosure-1",
        approval_receipt_id=APPROVAL_DIGEST,
        retention_acknowledged=True,
    )


def _manual_disclosure() -> ExecutionDisclosure:
    return ExecutionDisclosure(
        destination=ExecutionDestination.MANUAL_IMPORT,
        retention_class=RetentionClass.MANUAL_EXPORT,
        retention_days=None,
        disclosure_version="disclosure-1",
        retention_acknowledged=True,
    )


def _known_response() -> RunnerStructuredResponse:
    return RunnerStructuredResponse(
        state=RunnerResponseState.COMPLETED,
        judgments=(
            RunnerMetricJudgment(
                metric_key="quality.requirement_coverage",
                metric_question_fingerprint=QUESTION_DIGEST,
                state=MetricEstimateState.KNOWN,
                value_kind=MetricValueKind.FRACTION,
                numeric_value=0.75,
                confidence=0.8,
                opaque_evidence_refs=(EVIDENCE_DIGEST,),
            ),
        ),
    )


def _refused_response() -> RunnerStructuredResponse:
    return RunnerStructuredResponse(
        state=RunnerResponseState.REFUSED,
        refusal_code="provider_policy_refusal",
    )


def _events(
    response: RunnerStructuredResponse,
    *,
    served_model: str | None = "gpt-example-1",
    served_revision: str | None = "provider-revision-1",
    served_mode: str | None = "standard",
) -> list[dict[str, Any]]:
    start: dict[str, Any] = {
        "type": "thread.started",
        "thread_id": "synthetic-thread",
    }
    if served_model is not None:
        start["served_model_id"] = served_model
    if served_revision is not None:
        start["served_revision"] = served_revision
    if served_mode is not None:
        start["served_execution_mode"] = served_mode
    return [
        start,
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "synthetic-item",
                "type": "agent_message",
                "text": json.dumps(response.model_dump(mode="json")),
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 21,
                "cached_input_tokens": 3,
                "output_tokens": 8,
                "reasoning_output_tokens": 2,
            },
        },
    ]


def _fake_executable(
    tmp_path: Path,
    *,
    events: list[dict[str, Any]] | None = None,
    expected_packet: bytes = PACKET,
    prefix: str = "",
    suffix: str = "",
) -> tuple[str, ...]:
    script = tmp_path / "fake_codex.py"
    rendered_events = json.dumps(events or [])
    script.write_text(
        "import json, os, pathlib, subprocess, sys, time\n"
        f"EXPECTED = {expected_packet!r}\n"
        f"EVENTS = {rendered_events!r}\n"
        "payload = sys.stdin.buffer.read()\n"
        "if payload != EXPECTED:\n"
        "    raise SystemExit(41)\n"
        "if any(EXPECTED.decode('utf-8', 'ignore') in arg for arg in sys.argv[1:]):\n"
        "    raise SystemExit(42)\n"
        f"{prefix}\n"
        "for event in json.loads(EVENTS):\n"
        "    print(json.dumps(event, separators=(',', ':')), flush=True)\n"
        f"{suffix}\n",
        encoding="utf-8",
    )
    return (sys.executable, os.fspath(script))


def _request(
    *,
    payload: bytes = PACKET,
    activation_grade: bool = False,
    require_served_identity: bool = True,
    requested_model: str = "gpt-example-1",
) -> CodexRunRequest:
    return CodexRunRequest(
        requested_artifact=_codex_artifact(requested_model=requested_model),
        execution=_codex_disclosure(),
        evidence_receipt=_receipt(payload),
        evidence_packet=payload,
        activation_grade=activation_grade,
        require_served_identity=require_served_identity,
    )


def _runner(
    tmp_path: Path,
    executable: tuple[str, ...],
    *,
    limits: RunnerLimits | None = None,
    environment_source: dict[str, str] | None = None,
) -> tuple[CodexExecRunner, Path]:
    root = tmp_path / "runner-root"
    root.mkdir()
    return (
        CodexExecRunner(
            executable_argv=executable,
            limits=limits,
            temporary_root=root,
            environment_source=environment_source,
        ),
        root,
    )


def test_codex_runner_uses_documented_direct_argv_and_cleans_workspace(
    tmp_path: Path,
) -> None:
    canary = b'{"fixture":"synthetic; touch should-never-run"}'
    marker = tmp_path / "should-never-run"
    executable = _fake_executable(
        tmp_path,
        events=_events(_known_response()),
        expected_packet=canary,
        prefix=(
            "required = {'exec', '--strict-config', '--ephemeral', "
            "'--sandbox', 'read-only', "
            "'--ignore-user-config', "
            "'--ignore-rules', '--json', '--model', '--output-schema'}\n"
            "if not required.issubset(set(sys.argv[1:])):\n"
            "    raise SystemExit(43)\n"
            "if '--ask-for-approval' in sys.argv[1:]:\n"
            "    raise SystemExit(46)\n"
            "configs = {sys.argv[index + 1] for index, value in "
            "enumerate(sys.argv[:-1]) if value == '--config'}\n"
            "required_configs = {'features.shell_tool=false', "
            "'web_search=\"disabled\"', 'tools.view_image=false', "
            "'agents.enabled=false', 'features.multi_agent=false', "
            "'apps._default.enabled=false', 'history.persistence=\"none\"'}\n"
            "if not required_configs.issubset(configs):\n"
            "    raise SystemExit(47)\n"
            "if os.environ.get('OPENAI_API_KEY') is not None:\n"
            "    raise SystemExit(44)\n"
            "if pathlib.Path.cwd().joinpath('.git', 'HEAD').read_text('ascii') "
            "!= 'ref: refs/heads/runner\\n':\n"
            "    raise SystemExit(45)"
        ),
    )
    runner, root = _runner(
        tmp_path,
        executable,
        environment_source={
            **os.environ,
            "OPENAI_API_KEY": "fake_example_credential_do_not_use",
        },
    )

    argv = runner.build_argv(
        requested_model_id="gpt-example-1",
        schema_path=Path("response-schema.json"),
    )
    assert argv[: len(executable)] == executable
    assert argv[argv.index("--model") + 1] == "gpt-example-1"
    assert not any(canary.decode("utf-8") in argument for argument in argv)

    outcome = runner.run(_request(payload=canary))

    assert outcome.served_model_id == "gpt-example-1"
    assert outcome.served_revision == "provider-revision-1"
    assert outcome.fallback_used is False
    assert outcome.activation_eligible is False
    assert outcome.tool_boundary_verified is False
    assert outcome.usage.input_tokens == 21
    assert outcome.usage.api_cost_microusd is None
    assert outcome.response.judgments[0].numeric_value == 0.75
    assert not marker.exists()
    assert list(root.iterdir()) == []
    assert canary.decode("utf-8") not in repr(_request(payload=canary))
    assert canary.decode("utf-8") not in repr(outcome)


def test_activation_grade_fails_closed_when_transport_omits_served_identity(
    tmp_path: Path,
) -> None:
    executable = _fake_executable(
        tmp_path,
        events=_events(
            _known_response(),
            served_model=None,
            served_revision=None,
            served_mode=None,
        ),
    )
    runner, root = _runner(tmp_path, executable)

    with pytest.raises(CodexRunnerIdentityUnavailable) as captured:
        runner.run(_request())

    assert captured.value.code == "codex_served_identity_not_exposed"
    assert list(root.iterdir()) == []


def test_exploratory_run_truthfully_records_missing_identity(tmp_path: Path) -> None:
    executable = _fake_executable(
        tmp_path,
        events=_events(
            _known_response(),
            served_model=None,
            served_revision=None,
            served_mode=None,
        ),
    )
    runner, _ = _runner(tmp_path, executable)

    outcome = runner.run(_request(require_served_identity=False))

    assert outcome.served_model_id is None
    assert outcome.fallback_used is None
    assert outcome.activation_eligible is False


def test_activation_grade_is_disabled_until_the_cli_tool_boundary_is_proven(
    tmp_path: Path,
) -> None:
    invoked = tmp_path / "should-not-be-invoked"
    executable = _fake_executable(
        tmp_path,
        events=_events(_known_response()),
        prefix=f"pathlib.Path({os.fspath(invoked)!r}).write_text('unexpected', 'utf-8')",
    )
    runner, root = _runner(tmp_path, executable)

    with pytest.raises(CodexRunnerActivationUnavailable) as captured:
        runner.run(_request(activation_grade=True))

    assert captured.value.code == "codex_cli_activation_boundary_unproven"
    assert not invoked.exists()
    assert list(root.iterdir()) == []


def test_fallback_and_refusal_are_preserved_without_commentary(tmp_path: Path) -> None:
    executable = _fake_executable(
        tmp_path,
        events=_events(
            _refused_response(),
            served_model="gpt-example-fallback",
            served_revision="provider-revision-2",
        ),
    )
    runner, _ = _runner(tmp_path, executable)

    outcome = runner.run(_request())

    assert outcome.response.state is RunnerResponseState.REFUSED
    assert outcome.response.refusal_code == "provider_policy_refusal"
    assert outcome.fallback_used is True
    assert outcome.activation_eligible is False


@pytest.mark.parametrize(
    "message",
    [
        "not-json",
        json.dumps(
            {
                **_known_response().model_dump(mode="json"),
                "unexpected_private_text": "synthetic-extra-field",
            }
        ),
        '{"schema_version":"estimator-runner-response-v1",'
        '"state":"refused","state":"completed","judgments":[],"refusal_code":null}',
    ],
)
def test_malformed_duplicate_and_extra_response_fields_fail_closed(
    tmp_path: Path,
    message: str,
) -> None:
    events = _events(_known_response())
    events[2]["item"]["text"] = message
    executable = _fake_executable(tmp_path, events=events)
    runner, _ = _runner(tmp_path, executable)

    with pytest.raises(CodexRunnerProtocolError) as captured:
        runner.run(_request())

    assert captured.value.code == "codex_invalid_structured_response"
    assert "synthetic-extra-field" not in repr(captured.value)


def test_any_tool_event_is_rejected(tmp_path: Path) -> None:
    events = _events(_known_response())
    events.insert(
        2,
        {
            "type": "item.started",
            "item": {"id": "synthetic-tool", "type": "command_execution"},
        },
    )
    executable = _fake_executable(tmp_path, events=events)
    runner, _ = _runner(tmp_path, executable)

    with pytest.raises(CodexRunnerToolUseRejected):
        runner.run(_request())


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_stdout_and_stderr_caps_terminate_the_process(
    tmp_path: Path,
    stream: str,
) -> None:
    write = (
        "sys.stdout.write('x' * 4096); sys.stdout.flush()"
        if stream == "stdout"
        else "sys.stderr.write('x' * 4096); sys.stderr.flush()"
    )
    executable = _fake_executable(tmp_path, prefix=write)
    runner, root = _runner(
        tmp_path,
        executable,
        limits=RunnerLimits(
            timeout_ms=2_000,
            stdout_bytes=512,
            stderr_bytes=512,
        ),
    )

    with pytest.raises(RunnerOutputLimitExceeded) as captured:
        runner.run(_request())

    assert captured.value.code == f"runner_{stream}_limit"
    assert list(root.iterdir()) == []


def test_timeout_kills_the_spawned_process_tree(tmp_path: Path) -> None:
    child_marker = tmp_path / "child-survived"
    child = (
        "import pathlib,time; time.sleep(0.7); "
        f"pathlib.Path({os.fspath(child_marker)!r}).write_text('unexpected','utf-8')"
    )
    executable = _fake_executable(
        tmp_path,
        prefix=(
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "time.sleep(5)"
        ),
    )
    runner, root = _runner(
        tmp_path,
        executable,
        limits=RunnerLimits(timeout_ms=120, termination_grace_ms=50),
    )

    with pytest.raises(RunnerTimedOut):
        runner.run(_request())

    time.sleep(0.9)
    assert not child_marker.exists()
    assert list(root.iterdir()) == []


def test_external_cancellation_terminates_the_run(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path, prefix="time.sleep(5)")
    runner, root = _runner(
        tmp_path,
        executable,
        limits=RunnerLimits(timeout_ms=5_000, termination_grace_ms=50),
    )
    cancellation = threading.Event()
    timer = threading.Timer(0.1, cancellation.set)
    timer.start()
    try:
        with pytest.raises(RunnerCancelled):
            runner.run(_request(), cancellation=cancellation)
    finally:
        timer.cancel()

    assert list(root.iterdir()) == []


def test_workspace_growth_is_bounded_and_cleaned(tmp_path: Path) -> None:
    executable = _fake_executable(
        tmp_path,
        events=_events(_known_response()),
        prefix="pathlib.Path('.runner-tmp/oversized').write_bytes(b'x' * 8192)",
    )
    runner, root = _runner(
        tmp_path,
        executable,
        limits=RunnerLimits(workspace_bytes=4096),
    )

    with pytest.raises(RunnerWorkspaceLimitExceeded):
        runner.run(_request())

    assert list(root.iterdir()) == []


def test_model_id_is_validated_before_it_can_become_an_argument(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path, events=_events(_known_response()))
    runner, _ = _runner(tmp_path, executable)

    with pytest.raises(CodexRunnerProtocolError) as captured:
        runner.build_argv(
            requested_model_id="gpt-example;synthetic-injection",
            schema_path=Path("response-schema.json"),
        )

    assert captured.value.code == "codex_invalid_requested_model"


def test_nonzero_exit_does_not_echo_provider_output(tmp_path: Path) -> None:
    executable = _fake_executable(
        tmp_path,
        prefix="sys.stderr.write('synthetic-sensitive-canary'); raise SystemExit(9)",
    )
    runner, _ = _runner(tmp_path, executable)

    with pytest.raises(RunnerProcessFailed) as captured:
        runner.run(_request())

    assert captured.value.code == "codex_nonzero_exit"
    assert "synthetic-sensitive-canary" not in repr(captured.value)


def test_runner_judgment_supports_explicit_not_applicable_state() -> None:
    judgment = RunnerMetricJudgment(
        metric_key="quality.acceptance_result",
        metric_question_fingerprint=QUESTION_DIGEST,
        state=MetricEstimateState.NOT_APPLICABLE,
        value_kind=MetricValueKind.BINARY,
        not_applicable_reason_code="no_acceptance_contract",
    )

    assert judgment.state is MetricEstimateState.NOT_APPLICABLE


def test_manual_native_import_is_strict_content_bounded_and_never_activation_grade() -> None:
    exported = ManualNativeExport(
        provider=Provider.CLAUDE_CODE,
        requested_model_id="claude-example-1",
        served_model_id="claude-example-fallback",
        requested_revision="provider-revision-1",
        served_revision="provider-revision-2",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        evidence_packet_sha256=PACKET_DIGEST,
        exported_at=NOW,
        response=_known_response(),
    )
    payload = json.dumps(exported.model_dump(mode="json")).encode("utf-8")
    request = ManualImportRequest(
        payload=payload,
        expected_requested_model_id="claude-example-1",
        expected_evidence_receipt=_receipt(),
        execution=_manual_disclosure(),
    )

    result = import_manual_native_export(request, now=NOW)

    assert CLAUDE_CONSUMER_CLI_AUTOMATION_SUPPORTED is False
    assert result.receipt.fallback_used is True
    assert result.receipt.activation_eligible is False
    assert result.receipt.automated_consumer_cli is False
    assert result.receipt.import_payload_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.response.judgments[0].numeric_value == 0.75
    assert payload.decode("utf-8") not in repr(request)
    assert payload.decode("utf-8") not in repr(result)


@pytest.mark.parametrize(
    "mutation, expected_code",
    [
        ({"unexpected": "synthetic-extra"}, "manual_import_invalid_schema"),
        ({"evidence_packet_sha256": "0" * 64}, "manual_import_packet_mismatch"),
        ({"requested_model_id": "claude-example-2"}, "manual_import_model_mismatch"),
    ],
)
def test_manual_import_rejects_extra_and_scope_mismatch(
    mutation: dict[str, str],
    expected_code: str,
) -> None:
    exported = ManualNativeExport(
        provider=Provider.CLAUDE_CODE,
        requested_model_id="claude-example-1",
        served_model_id="claude-example-1",
        requested_revision="provider-revision-1",
        served_revision="provider-revision-1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        evidence_packet_sha256=PACKET_DIGEST,
        exported_at=NOW,
        response=_known_response(),
    ).model_dump(mode="json")
    exported.update(mutation)
    request = ManualImportRequest(
        payload=json.dumps(exported).encode("utf-8"),
        expected_requested_model_id="claude-example-1",
        expected_evidence_receipt=_receipt(),
        execution=_manual_disclosure(),
    )

    with pytest.raises(ManualImportProtocolError) as captured:
        import_manual_native_export(request, now=NOW)

    assert captured.value.code == expected_code


def test_categorical_judgment_requires_normalized_sorted_probabilities() -> None:
    judgment = RunnerMetricJudgment(
        metric_key="quality.acceptance_result",
        metric_question_fingerprint=QUESTION_DIGEST,
        state=MetricEstimateState.KNOWN,
        value_kind=MetricValueKind.BINARY,
        label_code="pass",
        confidence=0.9,
        probabilities=(
            LabelProbability(label_code="fail", probability=0.1),
            LabelProbability(label_code="pass", probability=0.9),
        ),
    )

    assert judgment.label_code == "pass"
