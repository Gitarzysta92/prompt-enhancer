from __future__ import annotations

import hashlib
import pytest
from prompt_enhancer.interfaces.http.user_presence import (
    UserPresenceApprovalManager,
)


SESSION = "a" * 64
PROPOSAL = "b" * 64


def _path() -> str:
    return (
        f"/v1/sessions/{SESSION}/metric-lifecycle-evidence/"
        f"proposals/{PROPOSAL}/decision"
    )


def test_user_presence_is_one_shot_and_bound_to_exact_body_and_path() -> None:
    manager = UserPresenceApprovalManager()
    body = b'{"decision":"confirm"}'
    token = manager.issue(
        method="POST",
        path=_path(),
        body_sha256=hashlib.sha256(body).hexdigest(),
    )

    assert manager.consume(
        token=token,
        method="POST",
        path=_path(),
        body=body,
    ) is True
    assert manager.consume(
        token=token,
        method="POST",
        path=_path(),
        body=body,
    ) is False


def test_mismatch_burns_capability_and_unknown_actions_are_rejected() -> None:
    manager = UserPresenceApprovalManager()
    body = b'{"decision":"reject"}'
    token = manager.issue(
        method="POST",
        path=_path(),
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    assert manager.consume(
        token=token,
        method="POST",
        path=_path(),
        body=b'{"decision":"confirm"}',
    ) is False
    assert manager.consume(
        token=token,
        method="POST",
        path=_path(),
        body=body,
    ) is False

    assert manager.action_label("POST", "/v1/unreviewed/action") is None
    try:
        manager.issue(
            method="POST",
            path="/v1/unreviewed/action",
            body_sha256="0" * 64,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unreviewed action received an approval")


def test_requirement_action_review_and_decision_are_the_only_new_safe_actions() -> None:
    manager = UserPresenceApprovalManager()
    base = (
        f"/v1/sessions/{SESSION}/requirement-action-evidence/"
        f"proposals/{PROPOSAL}"
    )

    assert manager.action_label("POST", f"{base}/review") == (
        "Open exact local requirements plus redacted action invocation and effect "
        "details for one review"
    )
    assert manager.action_label("POST", f"{base}/decision") == (
        "Confirm or reject one reviewed requirement-to-action link proposal"
    )
    assert manager.action_label("GET", f"{base}/review") is None
    assert manager.action_label("POST", f"{base}/import") is None
    assert manager.action_label("POST", f"{base}/review/extra") is None


def test_requirement_acceptance_is_one_exact_native_safe_action() -> None:
    manager = UserPresenceApprovalManager()
    path = (
        f"/v1/sessions/{SESSION}/"
        "requirement-verification-evidence/acceptances"
    )

    assert manager.action_label("POST", path) == (
        "Record one explicit native requirement acceptance outcome"
    )
    assert manager.action_label("GET", path) is None
    assert manager.action_label("POST", f"{path}/extra") is None


@pytest.mark.parametrize(
    "path",
    (
        f"/v1/agent/sessions/{'1' * 32}/authority",
        f"/v1/agent/sessions/{'1' * 32}/approvals/{'2' * 32}",
        f"/v1/agent/sessions/{'1' * 32}/workspace/creates/{'2' * 32}/apply",
        f"/v1/agent/sessions/{'1' * 32}/workspace/directories/{'2' * 32}/apply",
        f"/v1/agent/sessions/{'1' * 32}/workspace/directory-moves/{'2' * 32}/apply",
        f"/v1/agent/sessions/{'1' * 32}/workspace/file-trash/{'2' * 32}/apply",
        f"/v1/agent/sessions/{'1' * 32}/workspace/moves/{'2' * 32}/apply",
        f"/v1/agent/sessions/{'1' * 32}/workspace/previews/{'2' * 32}/apply",
        f"/v1/agent/sessions/{'1' * 32}/workspace/transactions/{'2' * 32}/apply",
        f"/v1/agent/projects/{'3' * 32}/sessions/{'1' * 32}/artifacts",
        "/v1/integrations/agent-mcp/connections",
        f"/v1/integrations/agent-mcp/connections/{'4' * 32}/rotate",
        f"/v1/integrations/agent-mcp/connections/{'4' * 32}/revoke",
        "/v1/integrations/mcp-store/managed",
        f"/v1/integrations/mcp-store/managed/{'5' * 32}/probe",
        f"/v1/integrations/mcp-store/managed/{'5' * 32}/install",
        f"/v1/integrations/mcp-store/managed/{'5' * 32}/uninstall",
        f"/v1/integrations/mcp-store/managed/{'5' * 32}/projects/{'6' * 32}",
        f"/v1/integrations/mcp-store/managed/{'5' * 32}/secrets/{'7' * 32}",
        f"/v1/integrations/mcp-store/managed/{'5' * 32}/secrets/{'7' * 32}/remove",
    ),
)
def test_every_protected_agent_action_has_an_exact_native_bridge_shape(path: str) -> None:
    manager = UserPresenceApprovalManager()
    assert manager.action_label("POST", path)
    assert manager.action_label("GET", path) is None
    assert manager.action_label("POST", f"{path}/extra") is None


def test_agent_mcp_connection_actions_have_specific_native_confirmation_copy() -> None:
    manager = UserPresenceApprovalManager()
    connection_id = "4" * 32

    assert manager.action_label(
        "POST", "/v1/integrations/agent-mcp/connections"
    ) == (
        "Create one scoped external Agent connection and reveal its credential once"
    )
    assert manager.action_label(
        "POST", f"/v1/integrations/agent-mcp/connections/{connection_id}/rotate"
    ) == (
        "Rotate one external Agent connection and reveal its replacement credential once"
    )
    assert manager.action_label(
        "POST", f"/v1/integrations/agent-mcp/connections/{connection_id}/revoke"
    ) == "Revoke one external Agent connection"


def test_mcp_store_management_actions_have_specific_bounded_confirmation_copy() -> None:
    manager = UserPresenceApprovalManager()
    management_id = "5" * 32
    project_id = "6" * 32
    requirement_id = "7" * 32

    assert manager.action_label(
        "POST", "/v1/integrations/mcp-store/managed"
    ) == "Save one reviewed MCP setup plan without installing or starting it"
    assert manager.action_label(
        "POST", f"/v1/integrations/mcp-store/managed/{management_id}/probe"
    ) == (
        "Briefly connect one exact reviewed MCP endpoint, inspect bounded tool schemas, "
        "then close it without calling tools"
    )
    assert manager.action_label(
        "POST", f"/v1/integrations/mcp-store/managed/{management_id}/install"
    ) == (
        "Activate one exact reviewed remote MCP plan without starting a persistent "
        "host or granting tool authority"
    )
    assert manager.action_label(
        "POST", f"/v1/integrations/mcp-store/managed/{management_id}/uninstall"
    ) == (
        "Remove one remote MCP activation without deleting its reviewed plan or "
        "compatibility receipt"
    )
    assert manager.action_label(
        "POST",
        f"/v1/integrations/mcp-store/managed/{management_id}/projects/{project_id}",
    ) == "Change one project's future MCP permission plan; no tool becomes active"
    assert manager.action_label(
        "POST",
        f"/v1/integrations/mcp-store/managed/{management_id}/secrets/{requirement_id}",
    ) == "Store one MCP credential in the operating-system vault"
    assert manager.action_label(
        "POST",
        f"/v1/integrations/mcp-store/managed/{management_id}/secrets/{requirement_id}/remove",
    ) == "Remove one MCP credential from the operating-system vault"
    assert manager.action_label(
        "GET", "/v1/integrations/mcp-store/managed"
    ) is None
    assert manager.action_label(
        "POST", f"/v1/integrations/mcp-store/managed/{management_id}/start"
    ) is None
