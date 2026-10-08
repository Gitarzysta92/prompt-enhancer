"""Store-06b inert host contracts use synthetic opaque evidence only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
import pytest

from prompt_enhancer.application.mcp_managed_host import (
    MCP_MANAGED_HOST_CONTRACT_VERSION,
    MCP_MANAGED_HOST_HEALTH_INTERVAL_SECONDS,
    MAX_MCP_MANAGED_ACTIVE_HOSTS,
    MAX_MCP_MANAGED_HOST_HEALTH_SECONDS,
    MAX_MCP_MANAGED_HOST_QUEUE,
    MAX_MCP_MANAGED_HOST_START_SECONDS,
    McpManagedHostBinding,
    McpManagedHostActionReceipt,
    McpManagedHostCleanupBlock,
    McpManagedHostStartPreview,
    McpManagedHostStatus,
    StartMcpManagedHost,
    StopMcpManagedHost,
    build_mcp_managed_host_start_preview,
    mcp_managed_host_binding_digest,
    require_mcp_managed_host_transition,
)


T0 = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(seconds=2)
T2 = T1 + timedelta(seconds=1)


def _binding(*, local: bool = False) -> McpManagedHostBinding:
    return McpManagedHostBinding(
        management_id="1" * 32,
        project_id="2" * 32,
        server_revision=7,
        project_binding_revision=3,
        plan_revision="4" * 64,
        option_kind="local_package" if local else "remote_server",
        transport="stdio" if local else "streamable-http",
        tool_snapshot_id="3" * 32,
        tool_schema_digest="5" * 64,
        reviewed_tool_count=2,
        admitted_tool_ids=("a" * 32, "b" * 32),
        granted_permissions=(
            ("process_spawn", "filesystem_read")
            if local
            else ("network_egress",)
        ),
    )


def _status(**updates) -> McpManagedHostStatus:  # noqa: ANN003
    payload = {
        "management_id": "1" * 32,
        "project_id": "2" * 32,
        "state": "not_started",
        "reason": "never_started",
        "binding": _binding(),
        "instance_id": None,
        "observed_tool_count": None,
        "observed_schema_digest": None,
        "started_at": None,
        "last_checked_at": None,
        "stopped_at": None,
        "last_transition_at": T0,
        "process_started": False,
        "cleanup_state": "not_applicable",
        "host_lease_active": False,
        "error_code": None,
    }
    payload.update(updates)
    return McpManagedHostStatus.model_validate(payload)


def _receipt(**updates) -> McpManagedHostActionReceipt:  # noqa: ANN003
    payload = {
        "receipt_id": "8" * 32,
        "request_id": "7" * 32,
        "management_id": "1" * 32,
        "project_id": "2" * 32,
        "instance_id": "6" * 32,
        "app_run_digest": "9" * 64,
        "binding_digest": "4" * 64,
        "execution_kind": "reviewed_remote_connection",
        "action": "start",
        "outcome": "ready",
        "reason": "owner_start",
        "requested_at": T0,
        "completed_at": T1,
        "process_started": False,
        "cleanup_state": "not_applicable",
        "host_ready": True,
        "error_code": None,
    }
    payload.update(updates)
    return McpManagedHostActionReceipt.model_validate(payload)


def _cleanup_block(**updates) -> McpManagedHostCleanupBlock:  # noqa: ANN003
    payload = {
        "block_id": "5" * 32,
        "management_id": "1" * 32,
        "project_id": "2" * 32,
        "instance_id": "6" * 32,
        "app_run_digest": "9" * 64,
        "binding_digest": "4" * 64,
        "reason": "local_process_cleanup_unconfirmed",
        "state": "active",
        "process_started": True,
        "cleanup_verified": False,
        "lifecycle_actions_blocked": True,
        "recovery_attempts": 0,
        "created_at": T0,
        "updated_at": T1,
        "resolved_at": None,
    }
    payload.update(updates)
    return McpManagedHostCleanupBlock.model_validate(payload)


def test_host_contract_constants_are_explicit_and_conservative() -> None:
    assert MCP_MANAGED_HOST_CONTRACT_VERSION == "mcp-managed-host.v2"
    assert MAX_MCP_MANAGED_ACTIVE_HOSTS == 4
    assert MAX_MCP_MANAGED_HOST_QUEUE == 16
    assert MAX_MCP_MANAGED_HOST_START_SECONDS == 20.0
    assert MAX_MCP_MANAGED_HOST_HEALTH_SECONDS == 10.0
    assert MCP_MANAGED_HOST_HEALTH_INTERVAL_SECONDS == 30.0


def test_binding_is_exact_canonical_and_content_free() -> None:
    binding = _binding(local=True)
    first = mcp_managed_host_binding_digest(binding)
    second = mcp_managed_host_binding_digest(
        McpManagedHostBinding.model_validate(binding.model_dump(mode="python"))
    )

    assert first == second
    assert len(first) == 64
    rendered = binding.model_dump_json()
    assert binding.tool_calls_available is True
    assert binding.tool_routing_state == "project_scoped_fresh_approval"
    for forbidden in (
        "endpoint",
        "executable",
        "argument",
        "environment",
        "credential",
        "tool_name",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "update",
    [
        {"admitted_tool_ids": ("b" * 32, "a" * 32)},
        {"admitted_tool_ids": ("a" * 32, "a" * 32)},
        {"admitted_tool_ids": ("not-an-id",)},
        {"reviewed_tool_count": 1},
        {"granted_permissions": ("network_egress", "process_spawn")},
        {"option_kind": "remote_server", "transport": "stdio"},
    ],
)
def test_binding_rejects_noncanonical_or_incoherent_authority(update) -> None:  # noqa: ANN001
    payload = _binding().model_dump(mode="python")
    payload.update(update)
    with pytest.raises(ValidationError):
        McpManagedHostBinding.model_validate(payload)


def test_start_previews_are_exact_truthful_and_content_free() -> None:
    remote = build_mcp_managed_host_start_preview(_binding())
    local = build_mcp_managed_host_start_preview(_binding(local=True))

    assert remote.execution_kind == "reviewed_remote_connection"
    assert remote.risk_notice == "remote_connection_uses_reviewed_configuration"
    assert remote.effects == (
        "open_reviewed_remote_connection",
        "enumerate_exact_tool_contracts",
        "retain_connection_for_current_app_run",
        "periodic_contract_health_check",
        "register_admitted_project_tools",
        "tool_calls_require_fresh_native_approval",
        "no_automatic_restart",
    )
    assert local.execution_kind == "local_native_process"
    assert local.risk_notice == (
        "local_native_code_uses_current_user_os_authority"
    )
    assert local.effects[:3] == (
        "execute_reviewed_local_package",
        "run_with_current_user_os_permissions",
        "own_hidden_process_tree",
    )
    for preview in (remote, local):
        assert preview.native_confirmation_required is True
        assert preview.preview_starts_host is False
        assert preview.current_app_run_only is True
        assert preview.automatic_start is False
        assert preview.automatic_restart is False
        assert preview.persists_across_app_restart is False
        assert preview.model_tool_registration_available is True
        assert preview.tool_calls_available is True
        assert preview.tool_routing_state == "project_scoped_fresh_approval"
        assert preview.connection_material_in_preview is False
        assert len(preview.preview_digest) == 64
        rendered = preview.model_dump_json()
        assert preview.preview_digest in rendered
        for forbidden in (
            "endpoint",
            "executable",
            "environment",
            "credential",
            "tool_name",
        ):
            assert forbidden not in rendered


def test_start_preview_digest_is_stable_and_revision_bound() -> None:
    binding = _binding()
    first = build_mcp_managed_host_start_preview(binding)
    second = build_mcp_managed_host_start_preview(
        McpManagedHostBinding.model_validate(binding.model_dump(mode="python"))
    )
    changed_payload = binding.model_dump(mode="python")
    changed_payload["server_revision"] = binding.server_revision + 1
    changed = build_mcp_managed_host_start_preview(
        McpManagedHostBinding.model_validate(changed_payload)
    )

    assert first.binding_digest == second.binding_digest
    assert first.preview_digest == second.preview_digest
    assert changed.binding_digest != first.binding_digest
    assert changed.preview_digest != first.preview_digest


@pytest.mark.parametrize(
    "update",
    [
        {"binding_digest": "0" * 64},
        {"execution_kind": "local_native_process"},
        {"risk_notice": "local_native_code_uses_current_user_os_authority"},
        {"effects": ("open_reviewed_remote_connection",) * 7},
        {"endpoint": "https://mcp.example.com/synthetic"},
    ],
)
def test_start_preview_refuses_drift_and_connection_material(update) -> None:  # noqa: ANN001
    preview = build_mcp_managed_host_start_preview(_binding())
    payload = preview.model_dump(
        mode="python",
        exclude_computed_fields=True,
    )
    payload.update(update)
    with pytest.raises(ValidationError):
        McpManagedHostStartPreview.model_validate(payload)


def test_action_receipts_cover_settled_lifecycle_truth_without_authority() -> None:
    receipts = (
        _receipt(),
        _receipt(
            execution_kind="local_native_process",
            process_started=True,
            cleanup_state="pending",
        ),
        _receipt(
            instance_id=None,
            outcome="refused",
            reason="start_refused",
            host_ready=False,
            error_code="mcp_host_revision_conflict",
        ),
        _receipt(
            instance_id=None,
            outcome="failed",
            reason="start_failed",
            host_ready=False,
            error_code="mcp_host_transport_failed",
        ),
        _receipt(
            outcome="failed",
            reason="start_failed",
            execution_kind="local_native_process",
            process_started=True,
            cleanup_state="verified",
            host_ready=False,
            error_code="mcp_host_transport_failed",
        ),
        _receipt(
            action="stop",
            outcome="stopped",
            reason="owner_stop",
            host_ready=False,
        ),
        _receipt(
            action="shutdown",
            outcome="stopped",
            reason="app_shutdown",
            execution_kind="local_native_process",
            process_started=True,
            cleanup_state="verified",
            host_ready=False,
        ),
        _receipt(
            action="health_revoke",
            outcome="cleanup_required",
            reason="cleanup_unconfirmed",
            execution_kind="local_native_process",
            process_started=True,
            cleanup_state="unconfirmed",
            host_ready=False,
            error_code="mcp_host_cleanup_unconfirmed",
        ),
        _receipt(
            action="stop",
            outcome="cleanup_required",
            reason="cleanup_unconfirmed",
            cleanup_state="unconfirmed",
            host_ready=False,
            error_code="mcp_host_cleanup_unconfirmed",
        ),
    )

    assert {item.outcome for item in receipts} == {
        "ready",
        "refused",
        "failed",
        "stopped",
        "cleanup_required",
    }
    for receipt in receipts:
        assert receipt.endpoint_persisted is False
        assert receipt.credential_persisted is False
        assert receipt.command_or_path_persisted is False
        assert receipt.tool_content_persisted is False
        assert receipt.prompt_or_result_persisted is False
        assert receipt.replay_grants_authority is False
        rendered = receipt.model_dump_json()
        for forbidden in (
            "https://",
            "executable",
            "credential_value",
            "tool_name",
            "prompt_text",
            "process_id",
        ):
            assert forbidden not in rendered


@pytest.mark.parametrize(
    "update",
    [
        {"instance_id": None},
        {"error_code": "mcp_host_unexpected_error"},
        {"outcome": "refused", "reason": "start_refused"},
        {
            "outcome": "failed",
            "reason": "start_failed",
            "host_ready": False,
            "process_started": True,
            "cleanup_state": "unconfirmed",
            "error_code": "mcp_host_cleanup_unconfirmed",
        },
        {
            "action": "stop",
            "outcome": "stopped",
            "reason": "app_shutdown",
            "host_ready": False,
        },
        {
            "outcome": "cleanup_required",
            "reason": "cleanup_unconfirmed",
            "cleanup_state": "unconfirmed",
            "host_ready": False,
        },
        {"completed_at": T0 - timedelta(seconds=1)},
        {"pid": 1234},
        {"endpoint": "https://mcp.example.com/synthetic"},
    ],
)
def test_action_receipt_refuses_false_or_sensitive_truth(update) -> None:  # noqa: ANN001
    payload = _receipt().model_dump(mode="python")
    payload.update(update)
    with pytest.raises(ValidationError):
        McpManagedHostActionReceipt.model_validate(payload)


def test_cleanup_blocks_are_content_free_and_lifecycle_blocking_until_verified() -> None:
    local_active = _cleanup_block()
    remote_active = _cleanup_block(
        reason="remote_connection_cleanup_unconfirmed",
        process_started=False,
    )
    local_resolved = _cleanup_block(
        state="resolved",
        cleanup_verified=True,
        lifecycle_actions_blocked=False,
        recovery_attempts=1,
        resolved_at=T1,
    )

    assert local_active.lifecycle_actions_blocked is True
    assert remote_active.lifecycle_actions_blocked is True
    assert local_resolved.cleanup_verified is True
    assert local_resolved.lifecycle_actions_blocked is False
    for block in (local_active, remote_active, local_resolved):
        assert block.endpoint_persisted is False
        assert block.credential_persisted is False
        assert block.process_identity_persisted is False
        assert block.command_or_path_persisted is False
        assert block.tool_content_persisted is False


@pytest.mark.parametrize(
    "update",
    [
        {"process_started": False},
        {
            "reason": "remote_connection_cleanup_unconfirmed",
            "process_started": True,
        },
        {"cleanup_verified": True},
        {"lifecycle_actions_blocked": False},
        {"state": "resolved"},
        {
            "state": "resolved",
            "cleanup_verified": True,
            "lifecycle_actions_blocked": False,
            "resolved_at": T2,
        },
        {"updated_at": T0 - timedelta(seconds=1)},
        {"recovery_attempts": True},
        {"pid": 1234},
        {"command": "synthetic-server.exe"},
    ],
)
def test_cleanup_block_refuses_incoherent_or_sensitive_state(update) -> None:  # noqa: ANN001
    payload = _cleanup_block().model_dump(mode="python")
    payload.update(update)
    with pytest.raises(ValidationError):
        McpManagedHostCleanupBlock.model_validate(payload)


def test_start_and_stop_commands_are_revision_bound_and_strict() -> None:
    start = StartMcpManagedHost(
        request_id="6" * 32,
        expected_server_revision=7,
        expected_project_binding_revision=3,
        expected_tool_snapshot_id="3" * 32,
        preview_digest="7" * 64,
        deadline_seconds=5,
    )
    stop = StopMcpManagedHost(
        request_id="8" * 32,
        expected_instance_id="9" * 32,
        deadline_seconds=4,
    )

    assert start.deadline_seconds == 5
    assert stop.expected_instance_id == "9" * 32
    assert "native_confirmation" not in stop.model_dump_json()
    for model, update in (
        (StartMcpManagedHost, {**start.model_dump(), "deadline_seconds": True}),
        (StartMcpManagedHost, {**start.model_dump(), "deadline_seconds": float("nan")}),
        (StopMcpManagedHost, {**stop.model_dump(), "deadline_seconds": 21}),
        (StopMcpManagedHost, {**stop.model_dump(), "endpoint": "synthetic"}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(update)


def test_valid_statuses_keep_host_and_tool_authority_distinct() -> None:
    remote = _binding()
    local = _binding(local=True)
    statuses = (
        _status(
            reason="stopped_after_restart",
            binding=remote,
            stopped_at=T0,
            cleanup_state="verified",
        ),
        _status(
            state="starting",
            reason="start_requested",
            binding=remote,
            instance_id="6" * 32,
            started_at=T0,
            last_transition_at=T0,
        ),
        _status(
            state="ready",
            reason="healthy",
            binding=remote,
            instance_id="6" * 32,
            observed_tool_count=2,
            observed_schema_digest="5" * 64,
            started_at=T0,
            last_checked_at=T1,
            last_transition_at=T1,
            host_lease_active=True,
            tool_calls_available=True,
            tool_routing_state="project_scoped_fresh_approval",
        ),
        _status(
            state="ready",
            reason="healthy",
            binding=local,
            instance_id="6" * 32,
            observed_tool_count=2,
            observed_schema_digest="5" * 64,
            started_at=T0,
            last_checked_at=T1,
            last_transition_at=T1,
            process_started=True,
            cleanup_state="pending",
            host_lease_active=True,
            tool_calls_available=True,
            tool_routing_state="project_scoped_fresh_approval",
        ),
        _status(
            state="unhealthy",
            reason="contract_drift",
            binding=remote,
            instance_id="6" * 32,
            observed_tool_count=1,
            observed_schema_digest="7" * 64,
            started_at=T0,
            last_checked_at=T1,
            last_transition_at=T1,
            error_code="mcp_host_contract_drift",
        ),
        _status(
            state="stopping",
            reason="owner_stop",
            binding=local,
            instance_id="6" * 32,
            started_at=T0,
            last_transition_at=T1,
            process_started=True,
            cleanup_state="pending",
        ),
        _status(
            state="cleanup_required",
            reason="cleanup_unconfirmed",
            binding=local,
            instance_id="6" * 32,
            started_at=T0,
            stopped_at=T2,
            last_transition_at=T2,
            process_started=True,
            cleanup_state="unconfirmed",
            error_code="mcp_host_cleanup_unconfirmed",
        ),
    )

    assert {item.state for item in statuses} == {
        "not_started",
        "starting",
        "ready",
        "unhealthy",
        "stopping",
        "cleanup_required",
    }
    assert sum(item.tool_calls_available for item in statuses) == 2
    assert all(
        item.tool_routing_state
        == ("project_scoped_fresh_approval" if item.state == "ready" else "inactive")
        for item in statuses
    )
    assert all(not item.connection_material_retained_in_status for item in statuses)


@pytest.mark.parametrize(
    "updates",
    [
        {"reason": "healthy"},
        {"instance_id": "6" * 32},
        {"state": "ready", "reason": "healthy"},
        {
            "state": "ready",
            "reason": "healthy",
            "instance_id": "6" * 32,
            "started_at": T0,
            "last_checked_at": T1,
            "observed_tool_count": 1,
            "observed_schema_digest": "5" * 64,
            "host_lease_active": True,
        },
        {
            "state": "unhealthy",
            "reason": "health_timeout",
            "instance_id": "6" * 32,
            "started_at": T0,
        },
        {
            "state": "cleanup_required",
            "reason": "cleanup_unconfirmed",
            "instance_id": "6" * 32,
            "started_at": T0,
            "stopped_at": T2,
            "cleanup_state": "verified",
            "error_code": "mcp_host_cleanup_unconfirmed",
        },
    ],
)
def test_status_rejects_false_or_incomplete_runtime_truth(updates) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        _status(**updates)


def test_status_refuses_connection_process_and_tool_content_fields() -> None:
    payload = _status().model_dump(mode="python")
    for field, value in (
        ("endpoint", "https://mcp.example.com/hidden"),
        ("executable", "X:\\example\\server.exe"),
        ("pid", 1234),
        ("tool_names", ["synthetic_lookup"]),
        ("credential", "synthetic-secret"),
    ):
        with pytest.raises(ValidationError):
            McpManagedHostStatus.model_validate({**payload, field: value})


def test_transition_table_prevents_authority_skips_and_restart_reuse() -> None:
    for previous, next_state in (
        ("not_started", "starting"),
        ("starting", "ready"),
        ("ready", "unhealthy"),
        ("ready", "stopping"),
        ("stopping", "not_started"),
        ("stopping", "cleanup_required"),
        ("cleanup_required", "not_started"),
    ):
        require_mcp_managed_host_transition(previous, next_state)

    for previous, next_state in (
        ("not_started", "ready"),
        ("unhealthy", "ready"),
        ("cleanup_required", "starting"),
        ("ready", "not_started"),
    ):
        with pytest.raises(ValueError, match="transition is not allowed"):
            require_mcp_managed_host_transition(previous, next_state)
