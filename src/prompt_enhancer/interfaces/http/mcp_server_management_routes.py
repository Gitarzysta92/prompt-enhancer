"""Authenticated MCP Store plan-management routes.

Every mutation is bound to one native user-presence confirmation. These routes
persist plans, project decisions, OS-vault references, content-free receipts,
and exact local-only reviewed tool contracts. A probe briefly connects one exact reviewed endpoint;
local MCPB install additionally verifies a checksum-pinned isolated package,
then closes its owned process tree without retaining or invoking any tool.
Local uninstall verifies the retained tree digest and removes it through an
operation-journaled quarantine without starting a process.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from ...application.mcp_managed_host import (
    McpManagedHostStartPreview,
    McpManagedHostStatus,
    StartMcpManagedHost,
    StopMcpManagedHost,
)
from ...application.mcp_managed_runtime import (
    McpManagedProjectRuntime,
    McpManagedRuntimeError,
    McpManagedRuntimeService,
)

from ...application.mcp_server_management import (
    ApplyMcpManagedLifecycle,
    ApplyMcpManagedLocalCleanup,
    ApplyMcpManagedLocalOperationRecovery,
    ApplyMcpManagedLocalRollback,
    ApplyMcpManagedLocalRollbackCleanup,
    ApplyMcpManagedLocalUpdate,
    MCP_MANAGED_SERVER_PATH,
    CreateMcpManagedServer,
    InspectMcpManagedLocalConfiguration,
    McpManagedServer,
    McpManagedServerError,
    McpManagedServerList,
    McpManagedLifecyclePreview,
    McpManagedLifecycleReceipt,
    McpManagedLocalCleanupPreview,
    McpManagedLocalCleanupReceipt,
    McpManagedLocalConfigurationInspectionPreview,
    McpManagedLocalConfigurationInspectionReceipt,
    McpManagedLocalOperationRecoveryPreview,
    McpManagedLocalOperationRecoveryReceipt,
    McpManagedLocalRollbackCleanupPreview,
    McpManagedLocalRollbackCleanupReceipt,
    McpManagedLocalRollbackPreview,
    McpManagedLocalRollbackReceipt,
    McpManagedLocalUpdatePreview,
    McpManagedLocalUpdateReceipt,
    McpManagedProbeReceipt,
    McpManagedServerReceipt,
    McpManagedServerService,
    McpManagedToolSnapshot,
    ProbeMcpManagedServer,
    RemoveMcpManagedConfiguration,
    RemoveMcpManagedSecret,
    SetMcpManagedProjectBinding,
    StoreMcpManagedConfiguration,
    StoreMcpManagedSecret,
)


def _private_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, private",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


def _error(error: McpManagedServerError) -> HTTPException:
    if error.code in {
        "mcp_managed_server_not_found",
        "mcp_managed_project_not_found",
        "mcp_managed_requirement_not_found",
        "mcp_registry_server_not_found",
    }:
        status = 404
    elif error.code in {
        "mcp_managed_plan_revision_conflict",
        "mcp_managed_request_conflict",
        "mcp_managed_replay_stale",
        "mcp_managed_revision_conflict",
        "mcp_managed_lifecycle_preview_conflict",
        "mcp_managed_configuration_inspection_preview_conflict",
        "mcp_managed_configuration_inspection_transition_conflict",
        "mcp_managed_configuration_already_inspected",
        "mcp_managed_cleanup_preview_conflict",
        "mcp_managed_cleanup_transition_conflict",
        "mcp_managed_update_preview_conflict",
        "mcp_managed_update_transition_conflict",
        "mcp_managed_update_target_changed",
        "mcp_managed_update_evidence_invalid",
        "mcp_managed_rollback_preview_conflict",
        "mcp_managed_rollback_transition_conflict",
        "mcp_managed_rollback_cleanup_preview_conflict",
        "mcp_managed_rollback_cleanup_transition_conflict",
        "mcp_managed_recovery_preview_conflict",
        "mcp_managed_recovery_transition_conflict",
        "mcp_managed_lifecycle_transition_conflict",
        "mcp_package_installed_tree_changed",
        "mcp_package_installed_tree_missing",
        "mcp_package_quarantine_tree_changed",
        "mcp_package_uninstall_evidence_mismatch",
        "mcp_package_uninstall_state_conflict",
        "mcp_package_uninstall_tree_changed",
        "mcp_managed_server_exists",
        "mcp_managed_secret_already_configured",
        "mcp_managed_secret_not_configured",
        "mcp_managed_secret_operation_pending",
        "mcp_managed_secret_transition_conflict",
        "mcp_managed_configuration_already_configured",
        "mcp_managed_configuration_not_configured",
        "mcp_managed_configuration_operation_pending",
        "mcp_managed_configuration_transition_conflict",
        "mcp_managed_tool_review_required",
        "mcp_managed_tool_admission_required",
        "mcp_managed_tool_admission_stale",
        "too_many_mcp_managed_servers",
    }:
        status = 409
    elif error.code in {
        "mcp_host_protocol_unsupported",
        "mcp_host_transport_mismatch",
        "mcp_host_tool_alias_collision",
        "mcp_host_tool_count_exceeded",
        "mcp_host_tool_identity_conflict",
        "mcp_host_tool_identity_invalid",
        "mcp_host_tool_metadata_invalid",
        "mcp_host_tool_metadata_total_exceeded",
        "mcp_host_tool_schema_dialect_unsupported",
        "mcp_host_tool_schema_external_ref",
        "mcp_host_tool_schema_format_unsupported",
        "mcp_host_tool_schema_invalid",
        "mcp_host_tool_schema_keyword_unsupported",
        "mcp_host_tool_schema_pattern_unsafe",
        "mcp_host_tool_schema_recursive",
        "mcp_host_tool_schema_ref_invalid",
        "mcp_host_tool_schema_too_complex",
        "mcp_host_tool_schema_too_large",
        "mcp_host_tool_schema_total_exceeded",
    }:
        status = 422
    elif error.code in {
        "mcp_managed_storage_unavailable",
        "mcp_managed_secret_vault_unavailable",
        "mcp_managed_secret_vault_read_failed",
        "mcp_managed_secret_vault_write_failed",
        "mcp_managed_secret_vault_delete_failed",
        "mcp_managed_configuration_vault_read_failed",
        "mcp_managed_configuration_vault_write_failed",
        "mcp_managed_configuration_cleanup_required",
        "mcp_managed_secret_cleanup_required",
        "mcp_registry_unavailable",
        "mcp_managed_probe_host_unavailable",
        "mcp_host_endpoint_unresolvable",
        "mcp_host_endpoint_unreachable",
        "mcp_host_endpoint_not_public",
        "mcp_host_egress_origin_changed",
        "mcp_host_tls_policy_invalid",
        "mcp_host_redirect_refused",
        "mcp_host_headers_too_large",
        "mcp_host_headers_invalid",
        "mcp_host_content_encoding_unsupported",
        "mcp_host_response_too_large",
        "mcp_host_response_count_exceeded",
        "mcp_host_sse_event_count_exceeded",
        "mcp_host_process_output_limit",
        "mcp_host_visible_window_detected",
        "mcp_host_process_visibility_unconfirmed",
        "mcp_host_deadline_exceeded",
        "mcp_host_probe_failed",
        "mcp_package_download_failed",
        "mcp_package_root_unavailable",
        "mcp_package_staging_unavailable",
        "mcp_package_runtime_unavailable",
        "mcp_package_runtime_cleanup_unconfirmed",
        "mcp_package_cleanup_unconfirmed",
        "mcp_host_cleanup_unconfirmed",
        "mcp_package_install_failed",
        "mcp_package_configuration_inspection_failed",
        "mcp_package_publication_failed",
        "mcp_package_commit_failed",
        "mcp_managed_local_installer_unavailable",
        "mcp_managed_uninstall_local_uninstaller_unavailable",
        "mcp_package_uninstall_cleanup_unconfirmed",
        "mcp_package_uninstall_commit_failed",
        "mcp_package_uninstall_failed",
        "mcp_package_uninstall_prepare_commit_failed",
        "mcp_package_uninstall_quarantine_failed",
        "mcp_package_uninstall_recovery_failed",
        "mcp_package_update_staging_unavailable",
        "mcp_package_update_stage_failed",
        "mcp_package_update_publication_failed",
        "mcp_package_update_stage_commit_failed",
        "mcp_package_update_commit_failed",
        "mcp_managed_update_local_installer_unavailable",
        "mcp_package_rollback_commit_failed",
        "mcp_package_rollback_cleanup_commit_failed",
        "mcp_package_operation_recovery_unconfirmed",
    }:
        status = 503
    elif error.code in {
        "mcp_managed_operation_in_progress",
        "mcp_package_existing_tree_requires_cleanup",
    }:
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail=error.code)


def _runtime_error(error: McpManagedRuntimeError) -> HTTPException:
    if error.code in {
        "mcp_managed_server_not_found",
        "mcp_managed_project_not_found",
        "mcp_managed_requirement_not_found",
    }:
        status = 404
    elif error.code in {
        "mcp_managed_host_already_active",
        "mcp_managed_host_start_cancelled",
        "mcp_managed_host_binding_changed",
        "mcp_managed_host_instance_conflict",
        "mcp_managed_host_preview_conflict",
        "mcp_managed_host_tool_snapshot_conflict",
        "mcp_managed_plan_revision_conflict",
        "mcp_managed_revision_conflict",
        "mcp_managed_tool_admission_required",
        "mcp_managed_tool_admission_stale",
        "mcp_managed_tool_review_required",
        "mcp_tool_admission_stale",
        "mcp_tool_call_in_progress",
        "mcp_tool_alias_collision",
        "mcp_tool_approval_replayed",
        "mcp_tool_call_scope_conflict",
        "mcp_tool_host_not_ready",
        "mcp_tool_not_admitted",
        "mcp_host_action_request_already_settled",
        "mcp_host_action_request_conflict",
        "mcp_host_cleanup_block_conflict",
    }:
        status = 409
    elif error.code in {
        "mcp_host_cleanup_unconfirmed",
        "mcp_managed_host_start_failed",
        "mcp_managed_host_start_timeout",
        "mcp_managed_host_stop_failed",
        "mcp_managed_host_stop_timeout",
        "mcp_managed_runtime_shutdown",
        "mcp_managed_runtime_unavailable",
        "mcp_host_endpoint_unresolvable",
        "mcp_host_endpoint_unreachable",
        "mcp_host_endpoint_not_public",
        "mcp_host_egress_origin_changed",
        "mcp_host_tls_policy_invalid",
        "mcp_host_redirect_refused",
        "mcp_host_headers_too_large",
        "mcp_host_headers_invalid",
        "mcp_host_content_encoding_unsupported",
        "mcp_host_response_too_large",
        "mcp_host_response_count_exceeded",
        "mcp_host_sse_event_count_exceeded",
        "mcp_host_process_output_limit",
        "mcp_host_visible_window_detected",
        "mcp_host_process_visibility_unconfirmed",
        "mcp_host_action_receipt_unavailable",
        "mcp_host_cleanup_evidence_incomplete",
        "mcp_host_cleanup_evidence_unavailable",
        "mcp_tool_claim_binding_invalid",
        "mcp_tool_claim_conflict",
        "mcp_tool_claim_missing",
        "mcp_tool_claim_storage_corrupt",
        "mcp_tool_claim_storage_unavailable",
        "mcp_tool_claim_unavailable",
        "mcp_tool_receipt_unavailable",
    }:
        status = 503
    else:
        status = 400
    return HTTPException(status_code=status, detail=error.code)


def create_mcp_server_management_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: McpManagedServerService,
    runtime_service: McpManagedRuntimeService | None = None,
) -> APIRouter:
    router = APIRouter(tags=["mcp-store-management"])
    local_auth = Depends(require_local_auth)
    native_confirmation = Depends(require_user_confirmation)

    def revoke_server_hosts(management_id: str, request_id: str) -> None:
        if runtime_service is None:
            return
        try:
            runtime_service.revoke_server_hosts(
                management_id,
                request_id=request_id,
            )
        except McpManagedRuntimeError as error:
            raise _runtime_error(error) from None

    def revoke_project_host(
        management_id: str,
        project_id: str,
        request_id: str,
    ) -> None:
        if runtime_service is None:
            return
        try:
            runtime_service.revoke_project_host(
                management_id,
                project_id,
                request_id=request_id,
            )
        except McpManagedRuntimeError as error:
            raise _runtime_error(error) from None

    if runtime_service is not None:

        @router.get(
            MCP_MANAGED_SERVER_PATH
            + "/{management_id}/projects/{project_id}/host",
            response_model=McpManagedHostStatus,
            dependencies=[local_auth],
        )
        def managed_host_status(
            response: Response,
            management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
            project_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        ) -> McpManagedHostStatus:
            response.headers.update(_private_headers())
            try:
                return runtime_service.status(management_id, project_id)
            except McpManagedRuntimeError as error:
                raise _runtime_error(error) from None

        @router.get(
            MCP_MANAGED_SERVER_PATH
            + "/{management_id}/projects/{project_id}/host/start-preview",
            response_model=McpManagedHostStartPreview,
            dependencies=[local_auth],
        )
        def managed_host_start_preview(
            response: Response,
            management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
            project_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
            expected_server_revision: int = Query(ge=1),
            expected_project_binding_revision: int = Query(ge=1),
            expected_tool_snapshot_id: str = Query(pattern=r"^[0-9a-f]{32}$"),
        ) -> McpManagedHostStartPreview:
            response.headers.update(_private_headers())
            try:
                return service.resolve_host_start_preview(
                    management_id,
                    project_id,
                    expected_server_revision=expected_server_revision,
                    expected_project_binding_revision=(
                        expected_project_binding_revision
                    ),
                    expected_tool_snapshot_id=expected_tool_snapshot_id,
                )
            except McpManagedServerError as error:
                raise _error(error) from None

        @router.post(
            MCP_MANAGED_SERVER_PATH
            + "/{management_id}/projects/{project_id}/host/start",
            response_model=McpManagedHostStatus,
            dependencies=[local_auth, native_confirmation],
        )
        def start_managed_host(
            payload: StartMcpManagedHost,
            response: Response,
            management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
            project_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        ) -> McpManagedHostStatus:
            response.headers.update(_private_headers())
            try:
                return runtime_service.start(management_id, project_id, payload)
            except McpManagedRuntimeError as error:
                raise _runtime_error(error) from None

        @router.post(
            MCP_MANAGED_SERVER_PATH
            + "/{management_id}/projects/{project_id}/host/stop",
            response_model=McpManagedHostStatus,
            dependencies=[local_auth],
        )
        def stop_managed_host(
            payload: StopMcpManagedHost,
            response: Response,
            management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
            project_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        ) -> McpManagedHostStatus:
            response.headers.update(_private_headers())
            try:
                return runtime_service.stop(management_id, project_id, payload)
            except McpManagedRuntimeError as error:
                raise _runtime_error(error) from None

        @router.get(
            "/v1/agent/mcp/projects/{project_id}/runtime",
            response_model=McpManagedProjectRuntime,
            dependencies=[local_auth],
        )
        def managed_project_runtime(
            response: Response,
            project_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        ) -> McpManagedProjectRuntime:
            response.headers.update(_private_headers())
            try:
                return runtime_service.project_tools(project_id)
            except McpManagedRuntimeError as error:
                raise _runtime_error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH,
        response_model=McpManagedServerList,
        dependencies=[local_auth],
    )
    def list_managed(response: Response) -> McpManagedServerList:
        response.headers.update(_private_headers())
        try:
            return service.list()
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}",
        response_model=McpManagedServer,
        dependencies=[local_auth],
    )
    def get_managed(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedServer:
        response.headers.update(_private_headers())
        try:
            return service.get(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/tools",
        response_model=McpManagedToolSnapshot,
        dependencies=[local_auth],
    )
    def get_managed_tools(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedToolSnapshot:
        response.headers.update(_private_headers())
        try:
            return service.get_tool_snapshot(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH,
        response_model=McpManagedServerReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def create_managed(
        payload: CreateMcpManagedServer,
        response: Response,
    ) -> McpManagedServerReceipt:
        response.headers.update(_private_headers())
        try:
            return service.create(payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/probe",
        response_model=McpManagedProbeReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def probe_managed(
        payload: ProbeMcpManagedServer,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedProbeReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.probe_remote(management_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/install-preview",
        response_model=McpManagedLifecyclePreview,
        dependencies=[local_auth],
    )
    def install_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLifecyclePreview:
        response.headers.update(_private_headers())
        try:
            return service.lifecycle_preview(management_id, "install")
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH
        + "/{management_id}/configuration-inspection-preview",
        response_model=McpManagedLocalConfigurationInspectionPreview,
        dependencies=[local_auth],
    )
    def configuration_inspection_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalConfigurationInspectionPreview:
        response.headers.update(_private_headers())
        try:
            return service.local_configuration_inspection_preview(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/configuration-inspection",
        response_model=McpManagedLocalConfigurationInspectionReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def inspect_local_configuration(
        payload: InspectMcpManagedLocalConfiguration,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalConfigurationInspectionReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.inspect_local_configuration(management_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/install",
        response_model=McpManagedLifecycleReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def install_managed(
        payload: ApplyMcpManagedLifecycle,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLifecycleReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.apply_lifecycle(management_id, "install", payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/uninstall-preview",
        response_model=McpManagedLifecyclePreview,
        dependencies=[local_auth],
    )
    def uninstall_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLifecyclePreview:
        response.headers.update(_private_headers())
        try:
            return service.lifecycle_preview(management_id, "uninstall")
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/update-preview",
        response_model=McpManagedLocalUpdatePreview,
        dependencies=[local_auth],
    )
    def local_update_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalUpdatePreview:
        response.headers.update(_private_headers())
        try:
            return service.local_update_preview(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/update",
        response_model=McpManagedLocalUpdateReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def update_managed_local_package(
        payload: ApplyMcpManagedLocalUpdate,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalUpdateReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.apply_local_update(management_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/rollback-preview",
        response_model=McpManagedLocalRollbackPreview,
        dependencies=[local_auth],
    )
    def local_rollback_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalRollbackPreview:
        response.headers.update(_private_headers())
        try:
            return service.local_rollback_preview(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/rollback",
        response_model=McpManagedLocalRollbackReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def rollback_managed_local_package(
        payload: ApplyMcpManagedLocalRollback,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalRollbackReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.apply_local_rollback(management_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH
        + "/{management_id}/rollback-cleanup-preview",
        response_model=McpManagedLocalRollbackCleanupPreview,
        dependencies=[local_auth],
    )
    def local_rollback_cleanup_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalRollbackCleanupPreview:
        response.headers.update(_private_headers())
        try:
            return service.local_rollback_cleanup_preview(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/rollback-cleanup",
        response_model=McpManagedLocalRollbackCleanupReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def cleanup_local_rollback_generation(
        payload: ApplyMcpManagedLocalRollbackCleanup,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalRollbackCleanupReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.cleanup_local_rollback_generation(
                management_id,
                payload,
            )
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/recovery-preview",
        response_model=McpManagedLocalOperationRecoveryPreview,
        dependencies=[local_auth],
    )
    def local_operation_recovery_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalOperationRecoveryPreview:
        response.headers.update(_private_headers())
        try:
            return service.local_operation_recovery_preview(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/recovery",
        response_model=McpManagedLocalOperationRecoveryReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def recover_local_operation(
        payload: ApplyMcpManagedLocalOperationRecovery,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalOperationRecoveryReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.recover_local_operation(management_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/uninstall",
        response_model=McpManagedLifecycleReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def uninstall_managed(
        payload: ApplyMcpManagedLifecycle,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLifecycleReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.apply_lifecycle(management_id, "uninstall", payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.get(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/cleanup-preview",
        response_model=McpManagedLocalCleanupPreview,
        dependencies=[local_auth],
    )
    def local_cleanup_preview(
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalCleanupPreview:
        response.headers.update(_private_headers())
        try:
            return service.local_cleanup_preview(management_id)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/cleanup",
        response_model=McpManagedLocalCleanupReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def complete_local_cleanup(
        payload: ApplyMcpManagedLocalCleanup,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedLocalCleanupReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.complete_local_uninstall_cleanup(
                management_id,
                payload,
            )
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH + "/{management_id}/projects/{project_id}",
        response_model=McpManagedServerReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def set_project_binding(
        payload: SetMcpManagedProjectBinding,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        project_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedServerReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_project_host(management_id, project_id, payload.request_id)
            return service.set_project_binding(management_id, project_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH
        + "/{management_id}/secrets/{requirement_id}",
        response_model=McpManagedServerReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def store_secret(
        payload: StoreMcpManagedSecret,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        requirement_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedServerReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.store_secret(management_id, requirement_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH
        + "/{management_id}/secrets/{requirement_id}/remove",
        response_model=McpManagedServerReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def remove_secret(
        payload: RemoveMcpManagedSecret,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        requirement_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedServerReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.remove_secret(management_id, requirement_id, payload)
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH
        + "/{management_id}/configuration/{requirement_id}",
        response_model=McpManagedServerReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def store_configuration(
        payload: StoreMcpManagedConfiguration,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        requirement_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedServerReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.store_configuration(
                management_id,
                requirement_id,
                payload,
            )
        except McpManagedServerError as error:
            raise _error(error) from None

    @router.post(
        MCP_MANAGED_SERVER_PATH
        + "/{management_id}/configuration/{requirement_id}/remove",
        response_model=McpManagedServerReceipt,
        dependencies=[local_auth, native_confirmation],
    )
    def remove_configuration(
        payload: RemoveMcpManagedConfiguration,
        response: Response,
        management_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        requirement_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> McpManagedServerReceipt:
        response.headers.update(_private_headers())
        try:
            revoke_server_hosts(management_id, payload.request_id)
            return service.remove_configuration(
                management_id,
                requirement_id,
                payload,
            )
        except McpManagedServerError as error:
            raise _error(error) from None

    return router


__all__ = ("create_mcp_server_management_router",)
