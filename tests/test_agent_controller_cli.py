"""Machine-facing controller CLI emits bounded JSON and never prints secrets."""

from __future__ import annotations

import io
import json

import pytest

from prompt_enhancer.application.agent_controller_client import (
    AgentControllerCloseChatResult,
    AgentControllerInvocationResult,
    AgentControllerOpenChatResult,
    AgentControllerRuntimeResult,
    AgentControllerTurnResult,
)
from prompt_enhancer.application.agent_orchestration import (
    agent_orchestration_manifest,
)
from prompt_enhancer.cli import main
from prompt_enhancer.interfaces import agent_controller_cli


SESSION_ID = "a" * 32
PROJECT_ID = "b" * 32
TOKEN = "example_cli_controller_token_do_not_use_123456789"


def _output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_config_is_content_free_and_does_not_initialize_private_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))

    assert main(["agent-controller-config"]) == 0
    payload = _output(capsys)

    assert payload["contract_version"] == "prompt-enhancer-agent-controller-cli.v5"
    assert payload["command"] == "prompt-enhancer"
    assert payload["commands"]["turn"]["args"][-1] == (
        "--acknowledge-sensitive-context-egress"
    )
    assert payload["commands"]["wait"]["stdin"]["request"]["after"] == (
        "<cursor returned by turn or wait>"
    )
    assert payload["commands"]["open"]["stdin"]["request"]["project_name"] == (
        "<new project name>"
    )
    assert payload["commands"]["close"]["stdin"]["mutation_authorized"] is True
    assert payload["commands"]["runtime"]["stdin"]["request"]["desired_state"] == (
        "ready"
    )
    assert payload["commands"]["runtime"]["args"][-1] == (
        "--acknowledge-model-lifecycle"
    )
    assert payload["safeguards"] == {
        "token_in_arguments_or_output": False,
        "starts_prompt_enhancer_or_agent": False,
        "can_request_model_lifecycle": True,
        "runtime_mutation_requires_explicit_ack": True,
        "runtime_mutation_auto_retry": False,
        "runtime_ambiguous_response_reconciled_once": True,
        "follows_redirects": False,
        "uses_environment_proxy": False,
        "native_review_can_be_approved": False,
        "message_submission_auto_retry": False,
        "open_creation_auto_retry": False,
        "open_4xx_empty_project_rollback": True,
        "open_uncertain_session_preserves_project_for_reconciliation": True,
        "close_requires_exact_mutation_authorization": True,
        "close_live_session_only": True,
        "close_mutation_auto_retry": False,
        "close_ambiguous_response_reconciled_once": True,
        "close_retained_catalog_deleted": False,
        "bounded_deadline_and_single_stop": True,
        "wait_submits_message_or_stop": False,
    }
    serialized = json.dumps(payload)
    assert TOKEN not in serialized
    assert str(tmp_path) not in serialized
    assert not (tmp_path / "api.token").exists()


def test_discover_without_existing_token_fails_without_creating_one(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))

    assert main(["agent-controller", "discover"]) == 1
    payload = _output(capsys)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "controller_token_unavailable"
    assert not (tmp_path / "api.token").exists()
    assert str(tmp_path) not in json.dumps(payload)


@pytest.mark.parametrize("action", ["invoke", "open", "close", "runtime", "turn", "wait"])
def test_sensitive_actions_require_explicit_cli_ack_before_reading_stdin(
    tmp_path,
    monkeypatch,
    capsys,
    action: str,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_controller_cli,
        "_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("client must not be created")
        ),
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO("this input must remain unread"),
    )

    assert main(["agent-controller", action]) == 2
    payload = _output(capsys)

    assert payload["error"]["code"] == "context_egress_acknowledgement_required"
    assert "this input" not in json.dumps(payload)


def test_runtime_requires_explicit_lifecycle_ack_before_reading_stdin(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_controller_cli,
        "_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("client must not be created")
        ),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("this input must remain unread"))

    assert main(
        [
            "agent-controller",
            "runtime",
            "--acknowledge-sensitive-context-egress",
        ]
    ) == 2
    payload = _output(capsys)
    assert payload["error"]["code"] == "model_lifecycle_acknowledgement_required"
    assert "this input" not in json.dumps(payload)


class _FakeController:
    def discover(self):
        return agent_orchestration_manifest()

    def invoke(self, request):
        assert request.operation == "list_projects"
        return AgentControllerInvocationResult(
            operation="list_projects",
            status_code=200,
            response={"projects": []},
        )

    def open_chat(self, request):
        assert request.project_name == "Synthetic controller project"
        assert request.settings.workspace == "/example/workspace"
        return AgentControllerOpenChatResult(
            outcome="ready",
            project={
                "project_id": PROJECT_ID,
                "name": "Synthetic controller project",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "revision": 1,
            },
            project_created=True,
            session={
                "session_id": SESSION_ID,
                "settings": {
                    "workspace": "/example/workspace",
                    "project_id": PROJECT_ID,
                },
                "created_at": "2026-01-01T00:00:00Z",
                "running": False,
                "closing": False,
                "stopping": False,
                "cleanup_unconfirmed": False,
                "last_seq": 1,
                "turns": 0,
            },
        )

    def close_chat(self, request):
        assert request.project_id == PROJECT_ID
        assert request.session_id == SESSION_ID
        assert request.expected_catalog_revision == 2
        assert request.expected_history_revision == 4
        return AgentControllerCloseChatResult(
            outcome="closed",
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            catalog_revision_checked=2,
            history_revision_checked=4,
            mutation_state="accepted",
            live_session_present=False,
            catalog_session_retained=True,
        )

    def coordinate_runtime(self, request):
        assert request.desired_state == "ready"
        assert request.alias == "example-model"
        assert request.device == "split"
        return AgentControllerRuntimeResult(
            desired_state="ready",
            alias="example-model",
            outcome="ready",
            mutation_attempted=True,
            status={
                "contract_version": "local-runtime-coordinator.v2",
                "revision": 2,
                "state": "ready",
                "requested": {
                    "alias": "example-model",
                    "device": "split",
                    "gpu_layers": 24,
                    "context_size": 8192,
                },
                "served": {
                    "alias": "example-model",
                    "device": "split",
                    "gpu_layers": 24,
                    "context_size": 8192,
                    "started_at": "2026-01-01T00:00:00Z",
                    "pid": 4242,
                },
                "cleanup": {
                    "state": "not_required",
                    "process_exit_confirmed": True,
                },
                "capabilities": {
                    "state": "verified",
                    "text": True,
                    "tools": True,
                },
                "context": {
                    "state": "unknown",
                    "limit_tokens": 8192,
                    "reason_code": "no_request_measured",
                },
                "active_requests": 0,
            },
        )

    def run_turn(self, request, **_options):
        assert request.session_id == SESSION_ID
        assert request.message.text == "Synthetic selected request"
        return AgentControllerTurnResult(
            outcome="settled",
            session_id=SESSION_ID,
            submission_state="accepted",
            cursor=4,
            last_seq=4,
            events=(),
        )

    def wait_turn(self, request, **_options):
        assert request.session_id == SESSION_ID
        assert request.after == 4
        return AgentControllerTurnResult(
            outcome="settled",
            session_id=SESSION_ID,
            submission_state="not_attempted",
            cursor=6,
            last_seq=6,
            events=(),
        )


def test_discover_outputs_verified_manifest_without_token(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_controller_cli,
        "_client",
        lambda *_args, **_kwargs: _FakeController(),
    )

    assert main(["agent-controller", "discover"]) == 0
    payload = _output(capsys)

    assert payload["ok"] is True
    assert payload["result"]["contract_version"] == "local-agent-orchestration.v22"
    assert len(payload["result"]["endpoints"]) == 77
    assert TOKEN not in json.dumps(payload)


def test_invoke_requires_per_request_authorization_and_redaction_receipt(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_controller_cli,
        "_client",
        lambda *_args, **_kwargs: _FakeController(),
    )
    incomplete = {
        "egress": {
            "task_authorized": True,
            "redaction_previewed": False,
            "destination": "model_context",
        },
        "request": {"operation": "list_projects"},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(incomplete)))

    assert main(
        [
            "agent-controller",
            "invoke",
            "--acknowledge-sensitive-context-egress",
        ]
    ) == 1
    payload = _output(capsys)

    assert payload["error"]["code"] == "controller_request_invalid"
    assert "redaction_previewed" not in json.dumps(payload)


@pytest.mark.parametrize("authorization", [False, 1])
def test_close_requires_literal_true_mutation_authorization_before_dispatch(
    tmp_path,
    monkeypatch,
    capsys,
    authorization,
) -> None:
    class _CloseMustNotRun:
        def close_chat(self, _request):
            raise AssertionError("invalid close must not reach the controller")

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_controller_cli,
        "_client",
        lambda *_args, **_kwargs: _CloseMustNotRun(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": {
                        "task_authorized": True,
                        "redaction_previewed": True,
                        "destination": "local_controller",
                    },
                    "mutation_authorized": authorization,
                    "request": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                        "expected_catalog_revision": 2,
                        "expected_history_revision": 4,
                    },
                }
            )
        ),
    )

    assert main(
        [
            "agent-controller",
            "close",
            "--acknowledge-sensitive-context-egress",
        ]
    ) == 1
    payload = _output(capsys)
    assert payload["error"]["code"] == "controller_request_invalid"


def test_invoke_open_close_runtime_turn_and_wait_emit_one_machine_readable_result(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_controller_cli,
        "_client",
        lambda *_args, **_kwargs: _FakeController(),
    )
    egress = {
        "task_authorized": True,
        "redaction_previewed": True,
        "destination": "local_controller",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": egress,
                    "request": {"operation": "list_projects"},
                }
            )
        ),
    )
    assert main(
        [
            "agent-controller",
            "invoke",
            "--acknowledge-sensitive-context-egress",
        ]
    ) == 0
    invoke = _output(capsys)
    assert invoke["result"] == {
        "operation": "list_projects",
        "status_code": 200,
        "response": {"projects": []},
    }

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": egress,
                    "request": {
                        "project_name": "Synthetic controller project",
                        "settings": {"workspace": "/example/workspace"},
                    },
                }
            )
        ),
    )
    assert main(
        [
            "agent-controller",
            "open",
            "--acknowledge-sensitive-context-egress",
        ]
    ) == 0
    opened = _output(capsys)
    assert opened["contract_version"] == "prompt-enhancer-agent-controller-cli.v5"
    assert opened["result"]["outcome"] == "ready"
    assert opened["result"]["project"]["project_id"] == PROJECT_ID
    assert opened["result"]["session"]["session_id"] == SESSION_ID

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": egress,
                    "mutation_authorized": True,
                    "request": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                        "expected_catalog_revision": 2,
                        "expected_history_revision": 4,
                    },
                }
            )
        ),
    )
    assert main(
        [
            "agent-controller",
            "close",
            "--acknowledge-sensitive-context-egress",
        ]
    ) == 0
    closed = _output(capsys)
    assert closed["result"]["outcome"] == "closed"
    assert closed["result"]["catalog_session_retained"] is True
    assert closed["result"]["permanent_delete_requested"] is False

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": egress,
                    "request": {
                        "desired_state": "ready",
                        "alias": "example-model",
                        "device": "split",
                        "gpu_layers": 24,
                        "context_size": 8192,
                    },
                }
            )
        ),
    )
    assert main(
        [
            "agent-controller",
            "runtime",
            "--acknowledge-sensitive-context-egress",
            "--acknowledge-model-lifecycle",
        ]
    ) == 0
    runtime = _output(capsys)
    assert runtime["result"]["outcome"] == "ready"
    assert runtime["result"]["contract_version"] == (
        "prompt-enhancer-agent-controller-runtime.v1"
    )
    assert runtime["result"]["status"]["served"]["alias"] == "example-model"

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": egress,
                    "request": {
                        "session_id": SESSION_ID,
                        "message": {"text": "Synthetic selected request"},
                    },
                }
            )
        ),
    )
    assert main(
        [
            "agent-controller",
            "turn",
            "--acknowledge-sensitive-context-egress",
            "--deadline-seconds",
            "2",
        ]
    ) == 0
    turn = _output(capsys)
    assert turn["result"]["outcome"] == "settled"
    assert turn["result"]["contract_version"] == (
        "prompt-enhancer-agent-controller-turn.v2"
    )
    assert turn["result"]["session_id"] == SESSION_ID
    assert turn["result"]["events"] == []
    assert TOKEN not in json.dumps(turn)

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "egress": egress,
                    "request": {"session_id": SESSION_ID, "after": 4},
                }
            )
        ),
    )
    assert main(
        [
            "agent-controller",
            "wait",
            "--acknowledge-sensitive-context-egress",
            "--deadline-seconds",
            "2",
        ]
    ) == 0
    waited = _output(capsys)
    assert waited["result"]["outcome"] == "settled"
    assert waited["result"]["submission_state"] == "not_attempted"
    assert waited["result"]["stop_requested"] is False
