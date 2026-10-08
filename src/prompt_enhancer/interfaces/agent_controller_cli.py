"""Single-request stdio bridge for local Agent controller integrations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Literal, TypeVar

from pydantic import TypeAdapter, ValidationError, field_validator, model_validator

from ..application.agent_controller_client import (
    AGENT_CONTROLLER_CLI_CONTRACT,
    AgentControllerClient,
    AgentControllerCloseChatRequest,
    AgentControllerError,
    AgentControllerInvokeRequest,
    AgentControllerOpenChatRequest,
    AgentControllerRuntimeRequest,
    AgentControllerTurnRequest,
    AgentControllerWaitRequest,
    MAX_CONTROLLER_REQUEST_BYTES,
)
from ..config import AppSettings
from ..domain import StrictModel
from ..infrastructure.agent_controller_http import (
    LoopbackAgentControllerTransport,
)
from ..privacy import PrivacyBoundaryError, load_api_token


CONTEXT_EGRESS_NOTICE = (
    "This command may return selected Agent messages, relative workspace data, "
    "runtime identity, or derived output to its invoking controller. Each "
    "invoke/open/close/runtime/turn/wait "
    "request requires task-specific authorization and a completed redaction preview."
)


class AgentControllerEgressAcknowledgement(StrictModel):
    task_authorized: Literal[True]
    redaction_previewed: Literal[True]
    destination: Literal["local_controller", "model_context"]


class AgentControllerInvokeEnvelope(StrictModel):
    egress: AgentControllerEgressAcknowledgement
    request: AgentControllerInvokeRequest


class AgentControllerTurnEnvelope(StrictModel):
    egress: AgentControllerEgressAcknowledgement
    request: AgentControllerTurnRequest


class AgentControllerOpenChatEnvelope(StrictModel):
    egress: AgentControllerEgressAcknowledgement
    request: AgentControllerOpenChatRequest


class AgentControllerCloseChatEnvelope(StrictModel):
    egress: AgentControllerEgressAcknowledgement
    mutation_authorized: Literal[True]
    request: AgentControllerCloseChatRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("chat close authorization must be exact true")
        return value


class AgentControllerRuntimeEnvelope(StrictModel):
    egress: AgentControllerEgressAcknowledgement
    request: AgentControllerRuntimeRequest


class AgentControllerWaitEnvelope(StrictModel):
    egress: AgentControllerEgressAcknowledgement
    request: AgentControllerWaitRequest


class AgentControllerCliError(StrictModel):
    code: str
    http_status: int | None = None
    retryable: bool = False


class AgentControllerCliEnvelope(StrictModel):
    contract_version: Literal["prompt-enhancer-agent-controller-cli.v5"] = (
        AGENT_CONTROLLER_CLI_CONTRACT
    )
    ok: bool
    result: Any | None = None
    error: AgentControllerCliError | None = None

    @model_validator(mode="after")
    def validate_result_or_error(self) -> "AgentControllerCliEnvelope":
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError("successful controller output requires only a result")
        if not self.ok and (self.result is not None or self.error is None):
            raise ValueError("failed controller output requires only an error")
        return self


_Envelope = TypeVar("_Envelope", bound=StrictModel)


def _base_url(settings: AppSettings, override: str | None) -> str:
    if override:
        return override
    host = f"[{settings.host}]" if ":" in settings.host else settings.host
    return f"http://{host}:{settings.port}"


def _write(payload: AgentControllerCliEnvelope) -> None:
    print(
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _write_error(error: AgentControllerError) -> None:
    _write(
        AgentControllerCliEnvelope(
            ok=False,
            error=AgentControllerCliError(
                code=error.code,
                http_status=error.http_status,
                retryable=error.retryable,
            ),
        )
    )


def _read_envelope(model: type[_Envelope]) -> _Envelope:
    text = sys.stdin.read(MAX_CONTROLLER_REQUEST_BYTES + 1)
    if len(text.encode("utf-8")) > MAX_CONTROLLER_REQUEST_BYTES:
        raise AgentControllerError("controller_request_too_large")
    try:
        payload = json.loads(text)
        return TypeAdapter(model).validate_python(payload)
    except (json.JSONDecodeError, ValidationError):
        raise AgentControllerError("controller_request_invalid") from None


def _client(
    settings: AppSettings,
    *,
    base_url: str | None,
    request_timeout_seconds: float,
) -> AgentControllerClient:
    try:
        token = load_api_token(settings.api_token_path)
    except (OSError, PrivacyBoundaryError):
        raise AgentControllerError("controller_token_unavailable") from None
    transport = LoopbackAgentControllerTransport(
        _base_url(settings, base_url),
        token,
        timeout_seconds=request_timeout_seconds,
    )
    return AgentControllerClient(transport)


def run_agent_controller(settings: AppSettings, args: argparse.Namespace) -> int:
    """Run one bounded controller action and emit exactly one JSON envelope."""

    action = str(args.agent_controller_command)
    if action in {"invoke", "open", "close", "runtime", "turn", "wait"} and not bool(
        args.acknowledge_sensitive_context_egress
    ):
        _write_error(
            AgentControllerError("context_egress_acknowledgement_required")
        )
        return 2
    if action == "runtime" and not bool(
        getattr(args, "acknowledge_model_lifecycle", False)
    ):
        _write_error(
            AgentControllerError("model_lifecycle_acknowledgement_required")
        )
        return 2
    try:
        client = _client(
            settings,
            base_url=args.base_url,
            request_timeout_seconds=float(args.request_timeout_seconds),
        )
        if action == "discover":
            result: Any = client.discover().model_dump(mode="json")
        elif action == "invoke":
            envelope = _read_envelope(AgentControllerInvokeEnvelope)
            result = client.invoke(envelope.request).model_dump(mode="json")
        elif action == "open":
            envelope = _read_envelope(AgentControllerOpenChatEnvelope)
            result = client.open_chat(envelope.request).model_dump(mode="json")
        elif action == "close":
            envelope = _read_envelope(AgentControllerCloseChatEnvelope)
            result = client.close_chat(envelope.request).model_dump(mode="json")
        elif action == "runtime":
            envelope = _read_envelope(AgentControllerRuntimeEnvelope)
            result = client.coordinate_runtime(envelope.request).model_dump(mode="json")
        elif action == "turn":
            envelope = _read_envelope(AgentControllerTurnEnvelope)
            result = client.run_turn(
                envelope.request,
                deadline_seconds=float(args.deadline_seconds),
                poll_interval_seconds=float(args.poll_interval_seconds),
                drain_timeout_seconds=float(args.drain_timeout_seconds),
            ).model_dump(mode="json")
        elif action == "wait":
            envelope = _read_envelope(AgentControllerWaitEnvelope)
            result = client.wait_turn(
                envelope.request,
                deadline_seconds=float(args.deadline_seconds),
                poll_interval_seconds=float(args.poll_interval_seconds),
            ).model_dump(mode="json")
        else:
            raise AgentControllerError("controller_action_invalid")
    except AgentControllerError as error:
        _write_error(error)
        return 1
    _write(AgentControllerCliEnvelope(ok=True, result=result))
    return 0


def agent_controller_config_document() -> dict[str, Any]:
    """Return content-free setup metadata; never include the local API token."""

    acknowledgement = {
        "task_authorized": True,
        "redaction_previewed": True,
        "destination": "local_controller",
    }
    return {
        "contract_version": AGENT_CONTROLLER_CLI_CONTRACT,
        "transport": "stdio_json_single_request",
        "command": "prompt-enhancer",
        "commands": {
            "discover": {
                "args": ["agent-controller", "discover"],
                "stdin": "none",
                "sensitive_output": False,
            },
            "invoke": {
                "args": [
                    "agent-controller",
                    "invoke",
                    "--acknowledge-sensitive-context-egress",
                ],
                "stdin": {
                    "egress": acknowledgement,
                    "request": {
                        "operation": "<manifest operation>",
                        "path_parameters": {},
                        "query": {},
                        "body": None,
                    },
                },
                "sensitive_output": True,
            },
            "open": {
                "args": [
                    "agent-controller",
                    "open",
                    "--acknowledge-sensitive-context-egress",
                ],
                "stdin": {
                    "egress": acknowledgement,
                    "request": {
                        "project_id": None,
                        "project_name": "<new project name>",
                        "settings": {
                            "workspace": "<absolute workspace path>",
                            "model_alias": "<ready local model alias>",
                            "title": "<chat title>",
                            "retention_policy": "local_history",
                            "allow_writes": True,
                            "allow_commands": True,
                            "allow_web": False,
                        },
                    },
                },
                "sensitive_output": True,
            },
            "close": {
                "args": [
                    "agent-controller",
                    "close",
                    "--acknowledge-sensitive-context-egress",
                ],
                "stdin": {
                    "egress": acknowledgement,
                    "mutation_authorized": True,
                    "request": {
                        "project_id": "<32 lowercase hex characters>",
                        "session_id": "<32 lowercase hex characters>",
                        "expected_catalog_revision": "<current positive revision>",
                        "expected_history_revision": "<current non-negative revision>",
                    },
                },
                "sensitive_output": True,
            },
            "runtime": {
                "args": [
                    "agent-controller",
                    "runtime",
                    "--acknowledge-sensitive-context-egress",
                    "--acknowledge-model-lifecycle",
                ],
                "stdin": {
                    "egress": acknowledgement,
                    "request": {
                        "desired_state": "ready",
                        "alias": "<registered local model alias>",
                        "device": "<cpu, gpu, or split>",
                        "gpu_layers": None,
                        "context_size": None,
                    },
                },
                "sensitive_output": True,
            },
            "turn": {
                "args": [
                    "agent-controller",
                    "turn",
                    "--acknowledge-sensitive-context-egress",
                ],
                "stdin": {
                    "egress": acknowledgement,
                    "request": {
                        "session_id": "<32 lowercase hex characters>",
                        "message": {
                            "text": "<selected message>",
                            "attachment_ids": [],
                        },
                    },
                },
                "sensitive_output": True,
            },
            "wait": {
                "args": [
                    "agent-controller",
                    "wait",
                    "--acknowledge-sensitive-context-egress",
                ],
                "stdin": {
                    "egress": acknowledgement,
                    "request": {
                        "session_id": "<32 lowercase hex characters>",
                        "after": "<cursor returned by turn or wait>",
                    },
                },
                "sensitive_output": True,
            },
        },
        "safeguards": {
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
        },
        "destination_values": ["local_controller", "model_context"],
        "notice": CONTEXT_EGRESS_NOTICE,
    }


def run_agent_controller_config() -> int:
    print(
        json.dumps(
            agent_controller_config_document(),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


__all__ = (
    "AgentControllerEgressAcknowledgement",
    "AgentControllerCloseChatEnvelope",
    "AgentControllerInvokeEnvelope",
    "AgentControllerOpenChatEnvelope",
    "AgentControllerRuntimeEnvelope",
    "AgentControllerTurnEnvelope",
    "AgentControllerWaitEnvelope",
    "CONTEXT_EGRESS_NOTICE",
    "agent_controller_config_document",
    "run_agent_controller",
    "run_agent_controller_config",
)
