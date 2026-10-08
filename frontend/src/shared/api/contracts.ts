import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

export type CandidateSignal = Schemas["CandidateSignalDto"];
export type TaskCandidate = Schemas["TaskCandidateDto"];
export type CandidateListItem = Schemas["CandidateListItemDto"];
export type CandidateListResponse = Schemas["CandidateListResponse"];
export type CandidateDecisionsResponse = Schemas["CandidateDecisionsResponse"];
export type TaskDecision = Schemas["TaskDecisionDto"];
export type DecisionRevisionLink = Schemas["DecisionRevisionLinkDto"];
export type TaskRevision = Schemas["TaskRevisionDto"];
export type TaskRevisionResponse = Schemas["TaskRevisionResponse"];
export type TaskRevisionListResponse = Schemas["TaskRevisionListResponse"];
export type TaskLifecycleState = Schemas["TaskLifecycleState"];
export type TaskLifecycleEvent = Schemas["TaskLifecycleEventDto"];
export type TaskLifecycleSnapshot = Schemas["TaskLifecycleSnapshotDto"];
export type TaskLifecycleListResponse = Schemas["TaskLifecycleListResponse"];
export type TaskLifecycleMutationResponse = Schemas["TaskLifecycleMutationResponse"];
export type AnalysisRun = Schemas["AnalysisRunDto"];
export type AnalysisResult = Schemas["AnalysisResultDto"];
export type AnalysisRunListResponse = Schemas["AnalysisRunListResponse"];
export type AnalysisRunResponse = Schemas["AnalysisRunResponse"];
export type ControlPlaneReadiness = Schemas["ControlPlaneReadiness"];
export type ControlPlaneReadinessGap = Schemas["ReadinessGap"];
export type SessionAnalysisRun = Schemas["SessionAnalysisRunDto"];
export type SessionAnalysisResult = Schemas["SessionAnalysisResultDto"];
export type SessionAnalysisEvidence = Schemas["SessionAnalysisEvidenceDto"];
export type SessionAnalysisSignal = Schemas["SessionAnalysisSignalDto"];
export type SessionMetricFraction = Schemas["SessionMetricFractionDto"];
export type SessionMetricScopeState = Schemas["SessionMetricScopeState"];
export type SessionQualityCompatibilityKey =
  Schemas["SessionQualityCompatibilityKey"];
export type SessionAnalysisRunListResponse =
  Schemas["SessionAnalysisRunListResponse"];
export type SessionAnalysisRunResponse = Schemas["SessionAnalysisRunResponse"];
export type SessionCoachingProjection = Schemas["SessionCoachingProjection"];
export type SessionQualityAggregate = Schemas["SessionQualityAggregate"];
export type SessionQualityMetricAggregate =
  Schemas["SessionQualityMetricAggregate"];
export type SessionQualityAggregateRequest =
  Schemas["SessionQualityAggregateRequest"];
export type ProjectQualityAggregate = Schemas["ProjectQualityAggregate"];
export type ProjectQualityAggregateRequest =
  Schemas["ProjectQualityAggregateRequest"];
export type ProjectSessionQualityAggregate =
  Schemas["ProjectSessionQualityAggregate"];
export type ProjectQualityMetricAggregate =
  Schemas["ProjectQualityMetricAggregate"];
export type ProjectQualityCompatibilityCohort =
  Schemas["ProjectQualityCompatibilityCohort"];
export type TaskReviewResponse = Schemas["TaskReviewResponse"];
export type TaskAnalysisResponse = Schemas["TaskAnalysisResponse"];
export type TaskCategory = Schemas["AcceptTaskRequest"]["task_category"];
export type RejectionReason = Schemas["RejectTaskRequest"]["reason"];

export type ReviewCommand =
  | { action: "accept"; request: Schemas["AcceptTaskRequest"] }
  | { action: "reject"; request: Schemas["RejectTaskRequest"] }
  | { action: "merge"; request: Schemas["MergeTasksRequest"] }
  | { action: "split"; request: Schemas["SplitTaskRequest"] };

export type CandidateStatusFilter = "all" | "undecided" | "decided";

export interface ContentFreeListPage {
  limit: number;
  offset: number;
}

export type VerificationKind = Schemas["VerificationKind"];
export type VerificationCapability = Schemas["VerificationCapability"];
export type CodexLocalSourceStatus = Schemas["CodexLocalSourceStatus"];
export type ClaudeCodeLocalSourceStatus = Schemas["ClaudeCodeLocalSourceStatus"];
export type IngestionReport = Schemas["IngestionReport"];
export type SessionTranscript = Schemas["SessionTranscript"];
export type SessionTimeline = Schemas["SessionTimeline"];
export type ProjectTimeline = Schemas["ProjectTimeline"];
export type LocalModelsOverview = Schemas["LocalModelsOverview"];
export type LocalModelStatus = Schemas["LocalModelStatus"];
export type LocalModelPlacementAdmission = Schemas["LocalModelPlacementAdmission"];
export type LocalModelRecord = Schemas["LocalModelRecord"];
export type AddLocalModel = Schemas["AddLocalModel"];
export type ActivateLocalModel = Schemas["ActivateLocalModel"];
export type LocalRuntimeCoordinatorStatus = Schemas["LocalRuntimeCoordinatorStatus"];
export type LocalRuntimeSelection = Schemas["LocalRuntimeSelection"];
export type LocalRuntimeServedSelection = Schemas["LocalRuntimeServedSelection"];
export type RuntimeCapabilities = Schemas["RuntimeCapabilities"];
export type RuntimeCleanupReceipt = Schemas["RuntimeCleanupReceipt"];
export type RuntimeContextStatus = Schemas["RuntimeContextStatus"];
export type LocalModelCompatibilityCatalog = Schemas["LocalModelCompatibilityCatalog"];
export type LocalModelCompatibility = Schemas["LocalModelCompatibility"];
export type SwitchLocalRuntime = Schemas["SwitchLocalRuntime"];
export type StopLocalRuntime = Schemas["StopLocalRuntime"];
export type DownloadRequest = Schemas["DownloadRequest"];
export type DownloadStatus = Schemas["DownloadStatus"];
export type DownloadCommandRequest = Schemas["DownloadCommandRequest"];
export type RemoteRepoFiles = Schemas["RemoteRepoFiles"];
export type ScanFolderResult = Schemas["ScanFolderResult"];
export type ApplicationUpdateState = Schemas["ApplicationUpdateState"];
export type ApplicationUpdateReason = Schemas["ApplicationUpdateReason"];
export type ApplicationUpdateVerificationCode = NonNullable<Schemas["ApplicationUpdateStatus"]["verification_code"]>;
export type ApplicationUpdatePackageReview = Required<Schemas["PackageReview"]>;
export type ApplicationUpdatePackageReviewState = ApplicationUpdatePackageReview["state"];
export type ApplicationUpdatePackageReviewReason = NonNullable<ApplicationUpdatePackageReview["reason_code"]>;
export type ApplicationUpdateStatus = Omit<Required<Schemas["ApplicationUpdateStatus"]>, "package_review"> & {
  package_review: ApplicationUpdatePackageReview;
};
export type ApplicationUpdateAction = "check" | "stage" | "cancel" | "retry" | "verify";
export interface ApplicationUpdateMutationRequest {
  expected_revision: number;
  expected_instance_id: string;
}

/** One turn sent to a local model's loopback endpoint (OpenAI chat shape). */
export type LocalModelChatMessage = { role: "system" | "user" | "assistant"; content: string };
export type LocalModelChatRequest = {
  messages: LocalModelChatMessage[];
  temperature?: number;
  max_tokens?: number;
  /** Qwen-style thinking; off by default so small tasks answer quickly. */
  enable_thinking?: boolean;
};
/** A streamed fragment: visible answer text and, when the model thinks aloud, its reasoning. */
export type LocalModelChatDelta = { content?: string; reasoning?: string };
export type LocalModelChatResult = {
  content: string;
  reasoning: string;
  finish_reason: string | null;
  elapsed_ms: number;
};
export type DeviceMode = Schemas["DeviceMode"];
export type JudgeOutcome = Schemas["JudgeOutcome"];
export type JudgeSweepStatus = Schemas["JudgeSweepStatus"];
export type JudgeAgreementReport = Schemas["JudgeAgreementReport"];
export type AnnotationAllowance = Schemas["AllowanceState"];
export type SharedFolder = Schemas["SharedFolder"];
export type SharedFolderList = Schemas["SharedFolderList"];
export type PeerLink = Schemas["PeerLink"];
export type PeerLinkList = Schemas["PeerLinkList"];
export type FolderSyncReport = Schemas["SyncReport"];
export type AnnotationMetaprompt = Schemas["Metaprompt"];
export type RemoteAnnotationDisclosure = Schemas["RemoteAnnotationDisclosure"];
export type RemoteAnnotationResult = Schemas["RemoteSubmitResult"];
export type SessionJudgments = Schemas["SessionJudgments"];
export type SessionInterpretation = Schemas["SessionInterpretation"];
export type PromptCheckConfiguration = Schemas["PromptCheckConfiguration"];
export type PromptCheckPreview = Schemas["PromptCheckPreview"];
export type PromptCheckRequest = Schemas["PromptCheckRequest"];
export type PromptCheckResult = Schemas["PromptCheckResult"];
export type PromptCheckRecord = Schemas["PromptCheckRecord"];
export type PromptCheckHistory = Schemas["PromptCheckHistory"];
export type AgentOrchestrationManifest = Schemas["AgentOrchestrationManifest"];
export type AgentHardeningState = "ready" | "degraded" | "unavailable";
export type AgentRecoveryState = "clean" | "attention_required" | "unknown";
export type AgentRecoveryAction =
  | "inspect_local_catalog"
  | "resume_interrupted_read_only"
  | "revalidate_recovered_authority"
  | "restart_after_cleanup_uncertain"
  | "retry_after_history_write_failure"
  | "verify_live_state";
export interface AgentPersistenceCounts {
  projects: number;
  archived_projects: number;
  sessions: number;
  archived_sessions: number;
  metadata_only_sessions: number;
  retained_sessions: number;
  history_events: number;
  interrupted_retained_sessions: number;
  artifacts: number;
  artifact_versions: number;
  staged_attachments: number;
  attached_attachments: number;
}
export interface AgentLiveHardeningFacts {
  sessions: number;
  running_turns: number;
  closing_sessions: number;
  pending_approvals: number;
  cleanup_unconfirmed: number;
  command_cleanup_quarantined: boolean;
  recovered_read_only: number;
  history_write_failures: number;
  shutting_down: boolean;
}
export interface AgentCatalogHardeningStatus {
  state: AgentHardeningState;
  reason_code:
    | "catalog_path_invalid"
    | "catalog_path_unsafe"
    | "catalog_schema_newer"
    | "catalog_migration_invalid"
    | "catalog_storage_unavailable"
    | "catalog_quick_check_failed"
    | "catalog_foreign_key_violation"
    | "catalog_projection_mismatch"
    | "catalog_diagnostic_unavailable"
    | null;
  schema_version: number | null;
  quick_check_passed: boolean | null;
  foreign_key_violations_observed: number | null;
  foreign_key_scan_truncated: boolean;
  projection_violations: number | null;
  counts: AgentPersistenceCounts | null;
}
export type AgentLiveHardeningStatus =
  | { state: "ready"; reason_code: null; counts: AgentLiveHardeningFacts }
  | { state: "unavailable"; reason_code: "live_state_unavailable"; counts: null };
export interface AgentHardeningSnapshot {
  contract_version: "agent-hardening.v1";
  generated_on_demand: true;
  contains_content: false;
  recovery_state: AgentRecoveryState;
  recovery_actions: AgentRecoveryAction[];
  catalog: AgentCatalogHardeningStatus;
  live: AgentLiveHardeningStatus;
}
export type AgentMcpClientKind = "codex" | "claude" | "other";
export type AgentMcpConnectionState = "active" | "expired" | "revoked" | "scope_missing";
export type AgentMcpScopeState = "bound" | "missing";
export type AgentMcpToolOutcome = "succeeded" | "failed";
export type AgentMcpToolSource = "external_client" | "native_self_test";
export type AgentControllerOwnershipState =
  | "claimed"
  | "running"
  | "waiting_native_approval"
  | "reconnecting"
  | "submission_uncertain"
  | "stopping"
  | "stop_uncertain"
  | "cleanup_unconfirmed"
  | "revoked";
export type AgentControllerOperation =
  | "turn"
  | "write_proposal"
  | "transaction_proposal"
  | "lifecycle_proposal";
export interface AgentControllerHandoff {
  target_connection_id: string;
  target_label: string;
  target_client_kind: AgentMcpClientKind;
  offered_at: string;
  expires_at: string;
}
export interface AgentControllerOwnership {
  contract_version: "agent-controller-ownership.v1";
  project_id: string;
  project_name: string;
  session_id: string;
  session_title: string;
  owner_connection_id: string;
  owner_label: string;
  owner_client_kind: AgentMcpClientKind;
  operation: AgentControllerOperation;
  state: AgentControllerOwnershipState;
  cursor: number;
  last_seq: number;
  approval_pending: boolean;
  ownership_started_at: string;
  owner_since: string;
  updated_at: string;
  revision: number;
  handoff: AgentControllerHandoff | null;
  native_approval_inherited: false;
}
export interface AgentControllerOwnershipList {
  contract_version: "agent-controller-ownership-list.v1";
  ownerships: AgentControllerOwnership[];
  active_count: number;
}
export interface AgentMcpConnectionScope {
  contract_version: "agent-mcp-scope.v1";
  state: AgentMcpScopeState;
  project_id: string | null;
  project_name: string | null;
  catalog_access: "project_only" | "none";
  chat_access: "project_only" | "none";
  workspace_access: "project_only" | "none";
  native_approval_inherited: false;
}
export interface AgentMcpConnection {
  contract_version: "agent-mcp-connection.v4";
  connection_id: string;
  label: string;
  client_kind: AgentMcpClientKind;
  created_at: string;
  updated_at: string;
  expires_at: string;
  last_used_at: string | null;
  last_tool_at: string | null;
  last_tool_name: string | null;
  last_tool_outcome: AgentMcpToolOutcome | null;
  last_tool_source: AgentMcpToolSource | null;
  last_auth_rejected_at: string | null;
  revoked_at: string | null;
  revision: number;
  credential_revision: number;
  allow_model_lifecycle: boolean;
  scope: AgentMcpConnectionScope;
  state: AgentMcpConnectionState;
}
export interface AgentMcpToolActivitySequence {
  contract_version: "agent-mcp-tool-activity-sequence.v1";
  connection_id: string;
  credential_revision: number;
  sequence: number;
  tool_name: string | null;
  tool_source: AgentMcpToolSource | null;
  started_at: string | null;
  completed_at: string | null;
  outcome: AgentMcpToolOutcome | null;
}
export interface AgentMcpConnectionList {
  contract_version: "agent-mcp-management.v2";
  activity_epoch: string;
  connections: AgentMcpConnection[];
  active_count: number;
  controller_ownerships: AgentControllerOwnershipList;
  tool_activity_sequences: AgentMcpToolActivitySequence[];
}
export interface CreateAgentMcpConnection {
  request_id: string;
  label: string;
  client_kind: AgentMcpClientKind;
  project_id: string;
  allow_model_lifecycle: boolean;
  expires_in_days: number;
}
export interface RotateAgentMcpConnection {
  request_id: string;
  expected_revision: number;
  expires_in_days: number;
}
export interface RevokeAgentMcpConnection {
  expected_revision: number;
}
export interface ReleaseAgentControllerOwnership {
  session_id: string;
  expected_revision: number;
}
export interface AgentControllerOwnershipReleaseReceipt {
  contract_version: "agent-controller-ownership.v1";
  project_id: string;
  session_id: string;
  released_connection_id: string;
  released_revision: number;
  released_at: string;
  released_by: "owner" | "native";
  session_settled: true;
  native_approval_inherited: false;
}
export interface AgentMcpConnectionCredential {
  contract_version: "agent-mcp-connection.v4";
  connection: AgentMcpConnection;
  endpoint_url: string;
  bearer_token: string;
  codex_toml: string;
  claude_json: string;
  idempotent_replay: boolean;
  secret_stored_by_server: false;
  starts_process: false;
  starts_terminal: false;
}
export interface AgentMcpClientSetup {
  contract_version: "agent-mcp-client-setup.v1";
  endpoint_url: string;
  bearer_token_env_var: "PROMPT_ENHANCER_AGENT_MCP_TOKEN";
  codex_toml: string;
  claude_json: string;
  codex_add_command: string;
  claude_add_command: string;
  credential_included: false;
  connection_authority_granted: false;
  native_connection_required: true;
  starts_process: false;
  starts_terminal: false;
  provider_configuration_changed: false;
}
export type McpRegistryStatus = "active" | "deprecated" | "deleted" | "unknown";
export type McpRegistryTransport = "stdio" | "streamable-http" | "sse" | "unknown";
export interface McpRegistryPackage {
  registry_type: string;
  identifier: string;
  version: string | null;
  transport: McpRegistryTransport;
  runtime_hint: string | null;
  checksum_available: boolean;
}
export interface McpRegistryRemote {
  transport: McpRegistryTransport;
  endpoint_host: string | null;
  endpoint_state: "fixed_host" | "template_requires_configuration";
  secure: boolean | null;
}
export interface McpRegistryIcon {
  path: string;
  mime_type: "image/png" | "image/jpeg" | "image/webp";
}
export interface McpRegistryServer {
  catalog_id: string;
  presentation_revision: string;
  name: string;
  title: string;
  description: string;
  publisher: string;
  version: string;
  status: McpRegistryStatus;
  updated_at: string | null;
  repository_url: string | null;
  website_url: string | null;
  icon: McpRegistryIcon | null;
  packages: McpRegistryPackage[];
  remotes: McpRegistryRemote[];
  supports_local: boolean;
  supports_remote: boolean;
  management_state: "not_managed";
  install_action: "unavailable";
  install_reason: "guarded_install_host_not_implemented";
}
export interface McpRegistryCatalog {
  contract_version: "mcp-registry-catalog.v1";
  source: {
    registry: "official_mcp_registry";
    base_url: "https://registry.modelcontextprotocol.io";
    fetched_at: string;
    delivery: "live" | "cached";
    cache_age_seconds: number;
  };
  search: string;
  servers: McpRegistryServer[];
  next_cursor: string | null;
  partial: boolean;
  management_truth: "registry_only_no_install_authority";
}
export interface McpRegistryCatalogQuery {
  search?: string;
  cursor?: string;
  limit?: number;
}
export type McpRegistryReviewOptionKind = "local_package" | "remote_server";
export type McpRegistryReviewCompatibilityStatus = "reviewable" | "requires_configuration" | "unsupported";
export type McpRegistryReviewCompatibilityReason =
  | "known_package_registry"
  | "unknown_package_registry"
  | "supported_transport"
  | "unknown_transport"
  | "runtime_hint_missing"
  | "configuration_required"
  | "endpoint_template_requires_configuration"
  | "endpoint_invalid"
  | "machine_runtime_not_probed"
  | "platform_not_declared"
  | "mcp_handshake_not_performed";
export type McpRegistryReviewRisk =
  | "downloads_package"
  | "executes_local_code"
  | "package_integrity_not_declared"
  | "command_arguments_declared"
  | "filesystem_input_declared"
  | "credential_input_declared"
  | "remote_network_egress"
  | "insecure_remote_transport";
export interface McpRegistryInputRequirement {
  requirement_id: string;
  location: "runtime_argument" | "package_argument" | "environment_variable" | "transport_header" | "remote_variable";
  name: string;
  description: string | null;
  required: boolean;
  secret: boolean;
  format: "string" | "number" | "boolean" | "filepath" | "unknown";
  repeated: boolean;
  fixed_value_declared: boolean;
  default_declared: boolean;
  choices_count: number;
  user_value_needed: boolean;
}
export interface McpRegistryOptionCompatibility {
  status: McpRegistryReviewCompatibilityStatus;
  reasons: McpRegistryReviewCompatibilityReason[];
  platform_compatibility: "unverified";
  runtime_availability: "unverified";
  mcp_handshake: "not_performed";
}
export interface McpRegistryInstallOption {
  option_id: string;
  kind: McpRegistryReviewOptionKind;
  label: string;
  registry_type: string | null;
  package_identifier: string | null;
  package_version: string | null;
  runtime_hint: string | null;
  transport: McpRegistryTransport;
  endpoint_host: string | null;
  endpoint_state: "not_applicable" | "fixed_host" | "template_requires_configuration" | "invalid";
  secure_transport: boolean | null;
  checksum_state: "declared" | "not_declared" | "not_applicable";
  requirements: McpRegistryInputRequirement[];
  risks: McpRegistryReviewRisk[];
  compatibility: McpRegistryOptionCompatibility;
  execution_state: "preview_only";
}
export interface McpRegistryProvenance {
  registry: "official_mcp_registry";
  registry_membership_security_review: "not_claimed";
  publisher_namespace: string;
  repository_url: string | null;
  repository_source: string | null;
  repository_identity_declared: boolean;
  repository_subfolder_declared: boolean;
  website_url: string | null;
  schema_url: string | null;
  license_state: "not_declared_by_registry_contract";
}
export interface McpRegistryVersionSummary {
  version: string;
  status: McpRegistryStatus;
  updated_at: string | null;
  selected: boolean;
}
export interface McpRegistryServerReview {
  contract_version: "mcp-registry-server-review.v1";
  source: McpRegistryCatalog["source"];
  server: McpRegistryServer;
  provenance: McpRegistryProvenance;
  versions: McpRegistryVersionSummary[];
  version_history_state: "live" | "partial" | "unavailable";
  options: McpRegistryInstallOption[];
  plan_revision: string;
  partial: boolean;
  management_state: "not_managed";
  install_action: "unavailable";
  uninstall_action: "not_applicable";
  review_truth: "preview_only_no_install_or_connection_authority";
}
export interface McpRegistryServerReviewQuery {
  catalog_id: string;
  presentation_revision: string;
  name: string;
  version: string;
}
export type McpManagedPermission =
  | "process_spawn"
  | "filesystem_read"
  | "filesystem_write"
  | "network_egress"
  | "credential_use";
export type McpManagedRequirementState =
  | "publisher_value_declared"
  | "registry_default_declared"
  | "value_required"
  | "value_pending_store"
  | "value_stored"
  | "value_store_failed"
  | "value_pending_removal"
  | "value_cleanup_required"
  | "optional_unset"
  | "secret_missing"
  | "secret_pending_store"
  | "secret_stored"
  | "secret_store_failed"
  | "secret_pending_removal"
  | "secret_cleanup_required";
export interface McpManagedSecretVaultStatus {
  provider: "windows_credential_manager" | "unavailable";
  availability: "available" | "unavailable";
  values_in_database: false;
  values_in_api_responses: false;
  values_in_model_context: false;
}
export interface McpManagedRequirement {
  requirement_id: string;
  location: McpRegistryInputRequirement["location"];
  name: string;
  required: boolean;
  secret: boolean;
  format: McpRegistryInputRequirement["format"];
  user_value_needed: boolean;
  configuration_state: McpManagedRequirementState;
  secret_vault_provider: "windows_credential_manager" | null;
  value_vault_provider: "windows_credential_manager" | null;
}
export interface McpManagedProjectBinding {
  project_id: string;
  project_name: string;
  enabled: boolean;
  required_permissions: McpManagedPermission[];
  granted_permissions: McpManagedPermission[];
  admitted_tool_ids: string[];
  tool_snapshot_id: string | null;
  admission_state: "disabled" | "review_required" | "admitted";
  effective_state:
    | "disabled"
    | "inactive_tool_review_required"
    | "inactive_install_required"
    | "inactive_host_unavailable";
  created_at: string;
  updated_at: string;
  revision: number;
}
export interface McpManagedHostProbe {
  request_id: string;
  checked_at: string;
  transport: "stdio" | "streamable-http" | "sse";
  protocol_version: string;
  tool_count: number;
  schema_digest: string;
  elapsed_ms: number;
  connection_state: "closed_after_probe";
  process_started: boolean;
  process_tree_cleanup: "verified" | "not_applicable";
  tool_names_persisted: boolean;
  tool_schemas_persisted: boolean;
  tool_results_requested: false;
  tool_authority_granted: false;
}
export interface McpManagedReviewedTool {
  tool_id: string;
  name: string;
  title: string | null;
  description: string | null;
  model_alias: string;
  input_schema: Record<string, unknown>;
  input_schema_digest: string;
  model_input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown> | null;
  output_schema_digest: string | null;
  contract_digest: string;
}
export interface McpManagedToolSnapshotSummary {
  snapshot_id: string;
  plan_revision: string;
  source: "remote_probe" | "local_package_probe";
  source_tree_digest: string | null;
  source_manifest_digest: string | null;
  protocol_version: string;
  tool_count: number;
  schema_digest: string;
  reviewed_at: string;
  tool_names_retained_locally: true;
  tool_schemas_retained_locally: true;
  connection_retained: false;
  tool_authority_granted: false;
}
export interface McpManagedToolSnapshot extends McpManagedToolSnapshotSummary {
  contract_version: "mcp-managed-tool-snapshot.v1";
  management_id: string;
  tools: McpManagedReviewedTool[];
}
export type McpManagedHostState =
  | "not_started"
  | "starting"
  | "ready"
  | "unhealthy"
  | "stopping"
  | "cleanup_required";
export type McpManagedHostCleanupState =
  | "not_applicable"
  | "pending"
  | "verified"
  | "unconfirmed";
export interface McpManagedHostBinding {
  contract_version: "mcp-managed-host.v2";
  management_id: string;
  project_id: string;
  server_revision: number;
  project_binding_revision: number;
  plan_revision: string;
  option_kind: "local_package" | "remote_server";
  transport: "stdio" | "streamable-http" | "sse";
  tool_snapshot_id: string;
  tool_schema_digest: string;
  reviewed_tool_count: number;
  admitted_tool_ids: string[];
  granted_permissions: McpManagedPermission[];
  execution_scope: "current_app_run_owner_start_only";
  tool_calls_available: true;
  tool_routing_state: "project_scoped_fresh_approval";
}
export type McpManagedHostStartEffect =
  | "execute_reviewed_local_package"
  | "run_with_current_user_os_permissions"
  | "own_hidden_process_tree"
  | "open_reviewed_remote_connection"
  | "enumerate_exact_tool_contracts"
  | "retain_connection_for_current_app_run"
  | "periodic_contract_health_check"
  | "register_admitted_project_tools"
  | "tool_calls_require_fresh_native_approval"
  | "no_automatic_restart";
export interface McpManagedHostStartPreview {
  contract_version: "mcp-managed-host-start-preview.v2";
  binding: McpManagedHostBinding;
  binding_digest: string;
  execution_kind: "local_native_process" | "reviewed_remote_connection";
  risk_notice:
    | "local_native_code_uses_current_user_os_authority"
    | "remote_connection_uses_reviewed_configuration";
  effects: McpManagedHostStartEffect[];
  availability: "available";
  reason: "ready_for_native_confirmation";
  native_confirmation_required: true;
  preview_starts_host: false;
  current_app_run_only: true;
  automatic_start: false;
  automatic_restart: false;
  persists_across_app_restart: false;
  model_tool_registration_available: true;
  tool_calls_available: true;
  tool_routing_state: "project_scoped_fresh_approval";
  connection_material_in_preview: false;
  preview_digest: string;
}
export interface StartMcpManagedHost {
  request_id: string;
  expected_server_revision: number;
  expected_project_binding_revision: number;
  expected_tool_snapshot_id: string;
  preview_digest: string;
  deadline_seconds?: number;
}
export interface StopMcpManagedHost {
  request_id: string;
  expected_instance_id: string | null;
  deadline_seconds?: number;
}
export interface McpManagedHostStatus {
  contract_version: "mcp-managed-host.v2";
  management_id: string;
  project_id: string;
  state: McpManagedHostState;
  reason:
    | "never_started"
    | "stopped_by_owner"
    | "stopped_after_restart"
    | "start_cancelled"
    | "app_shutdown"
    | "start_requested"
    | "healthy"
    | "transport_failed"
    | "process_exited"
    | "health_timeout"
    | "contract_drift"
    | "binding_changed"
    | "server_changed"
    | "owner_stop"
    | "cleanup_unconfirmed";
  binding: McpManagedHostBinding | null;
  instance_id: string | null;
  observed_tool_count: number | null;
  observed_schema_digest: string | null;
  started_at: string | null;
  last_checked_at: string | null;
  stopped_at: string | null;
  last_transition_at: string;
  process_started: boolean;
  cleanup_state: McpManagedHostCleanupState;
  host_lease_active: boolean;
  error_code: string | null;
  tool_calls_available: boolean;
  tool_routing_state: "inactive" | "project_scoped_fresh_approval";
  connection_material_retained_in_status: false;
}
export interface McpManagedReadyTool {
  management_id: string;
  project_id: string;
  host_instance_id: string;
  server_title: string;
  tool_id: string;
  name: string;
  model_alias: string;
  title: string | null;
  description: string | null;
  model_input_schema: Record<string, unknown>;
}
export interface McpManagedProjectRuntime {
  contract_version: "mcp-managed-runtime.v1";
  project_id: string;
  ready_host_count: number;
  ready_tool_count: number;
  tools: McpManagedReadyTool[];
  automatic_start: false;
  remembered_call_approval: false;
  every_call_requires_native_approval: true;
}
export interface McpManagedLocalPackageEvidence {
  artifact_sha256: string;
  artifact_bytes: number;
  tree_digest: string;
  manifest_digest: string;
  manifest_version: "0.3" | "0.4";
  license_state: "declared";
  runtime_kind: "node" | "python" | "binary";
  runtime_version: string | null;
}
export interface McpManagedLocalConfigurationInspection {
  plan_revision: string;
  artifact_sha256: string;
  artifact_bytes: number;
  manifest_digest: string;
  manifest_version: "0.3" | "0.4";
  configuration_schema_digest: string;
  requirement_ids: string[];
  inspected_at: string;
  archive_retained: false;
  process_started: false;
  configuration_values_persisted: false;
  manifest_content_persisted: false;
}
export interface McpManagedLocalRollbackGeneration {
  catalog_id: string;
  server_name: string;
  server_title: string;
  server_version: string;
  server_status_at_review: McpRegistryStatus;
  option_id: string;
  plan_revision: string;
  option_label: string;
  registry_type: "mcpb";
  package_identifier: string;
  package_version: string | null;
  runtime_hint: string | null;
  transport: "stdio";
  required_permissions: McpManagedPermission[];
  risks: McpRegistryReviewRisk[];
  generation_id: string;
  local_package_evidence: McpManagedLocalPackageEvidence;
  probe: McpManagedHostProbe;
  installed_at: string;
  retained_at: string;
}
export type McpManagedProbeAction =
  | "available_native_confirmation_required"
  | "unavailable_install_required"
  | "unavailable_configuration_required"
  | "unavailable_option_unsupported"
  | "not_applicable_verified_during_install";
export interface McpManagedServer {
  contract_version: "mcp-managed-server.v2";
  management_id: string;
  catalog_id: string;
  server_name: string;
  server_title: string;
  server_version: string;
  server_status_at_review: McpRegistryStatus;
  option_id: string;
  plan_revision: string;
  option_kind: McpRegistryReviewOptionKind;
  option_label: string;
  registry_type: string | null;
  package_identifier: string | null;
  package_version: string | null;
  runtime_hint: string | null;
  transport: McpRegistryTransport;
  endpoint_host: string | null;
  endpoint_state: McpRegistryInstallOption["endpoint_state"];
  secure_transport: boolean | null;
  required_permissions: McpManagedPermission[];
  risks: McpRegistryReviewRisk[];
  requirements: McpManagedRequirement[];
  project_bindings: McpManagedProjectBinding[];
  created_at: string;
  updated_at: string;
  revision: number;
  lifecycle_state: "planned" | "installed" | "cleanup_required";
  installation_state: "not_installed" | "installed" | "cleanup_required";
  installation_kind: "none" | "remote_activation" | "local_package";
  operation_state: "idle" | "installing" | "updating" | "uninstalling" | "rolling_back" | "cleaning_up" | "cleanup_required";
  installed_plan_revision: string | null;
  installed_at: string | null;
  local_package_evidence: McpManagedLocalPackageEvidence | null;
  local_configuration_inspection: McpManagedLocalConfigurationInspection | null;
  rollback_generation: McpManagedLocalRollbackGeneration | null;
  process_tree_cleanup: "not_applicable" | "verified" | "unconfirmed";
  host_state: "not_started";
  health_state: "not_checked" | "compatible";
  last_health_checked_at: string | null;
  last_probe: McpManagedHostProbe | null;
  tool_snapshot: McpManagedToolSnapshotSummary | null;
  tool_review_state: "probe_required" | "reviewable";
  update_state: "not_checked";
  latest_available_version: null;
  tool_routing_state: "inactive";
  install_action:
    | "available_native_confirmation_required"
    | "unavailable_compatibility_check_required"
    | "unavailable_configuration_required"
    | "unavailable_package_registry_not_supported"
    | "unavailable_package_integrity_required"
    | "unavailable_local_transport_unsupported"
    | "unavailable_configuration_inspection_required"
    | "unavailable_cleanup_required"
    | "unavailable_operation_in_progress"
    | "not_applicable_already_installed";
  uninstall_action:
    | "available_native_confirmation_required"
    | "not_applicable_not_installed"
    | "unavailable_cleanup_required"
    | "unavailable_operation_in_progress";
  probe_action: McpManagedProbeAction;
}
export interface McpManagedServerList {
  contract_version: "mcp-managed-server.v2";
  servers: McpManagedServer[];
  total: number;
  secret_vault: McpManagedSecretVaultStatus;
  execution_truth: "reviewed_tool_admission_without_persistent_host_or_tool_authority";
}
export interface McpManagedServerReceipt {
  contract_version: "mcp-managed-server.v2";
  server: McpManagedServer;
  idempotent_replay: boolean;
  process_started: false;
  endpoint_connected: false;
  package_changed: false;
  tool_authority_granted: false;
}
export interface McpManagedProbeReceipt {
  contract_version: "mcp-managed-server.v2";
  server: McpManagedServer;
  probe: McpManagedHostProbe;
  idempotent_replay: boolean;
  endpoint_connection_attempted: true;
  connection_retained: false;
  package_changed: false;
  tool_results_requested: false;
  tool_authority_granted: false;
}
export type McpManagedLifecycleEffect =
  | "persist_remote_activation"
  | "remove_remote_activation"
  | "download_exact_package"
  | "verify_artifact_sha256"
  | "stage_isolated_package"
  | "execute_bounded_compatibility_probe"
  | "stop_and_verify_process_tree"
  | "publish_verified_package"
  | "verify_installed_tree_digest"
  | "quarantine_verified_package"
  | "remove_quarantined_package"
  | "no_package_change"
  | "no_process_start"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLifecyclePreview {
  contract_version: "mcp-managed-lifecycle-preview.v1";
  action: "install" | "uninstall";
  management_id: string;
  expected_revision: number;
  plan_revision: string;
  installation_kind: "remote_activation" | "local_package";
  availability: "available" | "unavailable";
  reason:
    | "ready_for_native_confirmation"
    | "compatibility_check_required"
    | "configuration_required"
    | "configuration_inspection_required"
    | "package_registry_not_supported"
    | "package_integrity_required"
    | "local_transport_unsupported"
    | "local_installer_unavailable"
    | "local_uninstaller_unavailable"
    | "already_installed"
    | "not_installed"
    | "cleanup_required"
    | "operation_in_progress";
  effects: McpManagedLifecycleEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface ApplyMcpManagedLifecycle {
  request_id: string;
  expected_revision: number;
  preview_digest: string;
}
export interface McpManagedLifecycleReceipt {
  contract_version: "mcp-managed-lifecycle-receipt.v2";
  action: "install" | "uninstall";
  installation_kind: "remote_activation" | "local_package";
  server: McpManagedServer;
  preview_digest: string;
  idempotent_replay: boolean;
  package_changed: boolean;
  process_started: boolean;
  process_tree_cleanup: "verified" | "not_applicable";
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}
export type McpManagedLocalConfigurationInspectionEffect =
  | "download_exact_package"
  | "verify_artifact_sha256"
  | "inspect_manifest_configuration"
  | "discard_inspection_archive"
  | "persist_content_free_configuration_schema"
  | "revoke_project_bindings_if_permissions_expand"
  | "no_configuration_values_persisted"
  | "no_process_start"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLocalConfigurationInspectionPreview {
  contract_version: "mcp-managed-local-configuration-inspection-preview.v1";
  action: "inspect_configuration";
  management_id: string;
  expected_revision: number;
  plan_revision: string;
  availability: "available" | "unavailable";
  reason:
    | "ready_for_native_confirmation"
    | "local_package_required"
    | "already_inspected"
    | "already_installed"
    | "cleanup_required"
    | "operation_in_progress"
    | "package_registry_not_supported"
    | "package_integrity_required"
    | "local_transport_unsupported"
    | "local_installer_unavailable";
  effects: McpManagedLocalConfigurationInspectionEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface InspectMcpManagedLocalConfiguration {
  request_id: string;
  expected_revision: number;
  preview_digest: string;
}
export interface McpManagedLocalConfigurationInspectionReceipt {
  contract_version: "mcp-managed-local-configuration-inspection-receipt.v1";
  action: "inspect_configuration";
  server: McpManagedServer;
  inspection: McpManagedLocalConfigurationInspection;
  preview_digest: string;
  idempotent_replay: boolean;
  archive_retained: false;
  process_started: false;
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
  configuration_values_persisted: false;
}
export type McpManagedLocalCleanupEffect =
  | "verify_operation_journal"
  | "verify_installed_or_quarantined_tree_digest"
  | "finish_quarantined_removal"
  | "clear_cleanup_state"
  | "no_process_start"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLocalCleanupPreview {
  contract_version: "mcp-managed-local-cleanup-preview.v1";
  action: "complete_interrupted_uninstall";
  management_id: string;
  expected_revision: number;
  plan_revision: string;
  availability: "available" | "unavailable";
  reason:
    | "ready_for_native_confirmation"
    | "cleanup_not_required"
    | "unsupported_cleanup_state"
    | "local_uninstaller_unavailable";
  effects: McpManagedLocalCleanupEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface ApplyMcpManagedLocalCleanup {
  request_id: string;
  expected_revision: number;
  preview_digest: string;
}
export interface McpManagedLocalCleanupReceipt {
  contract_version: "mcp-managed-local-cleanup-receipt.v1";
  action: "complete_interrupted_uninstall";
  server: McpManagedServer;
  preview_digest: string;
  idempotent_replay: boolean;
  package_presence: "absent";
  filesystem_changed: boolean;
  process_started: false;
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}
export type McpManagedLocalUpdateEffect =
  | "resolve_official_latest_exact_version"
  | "download_exact_target_package"
  | "verify_target_artifact_sha256"
  | "stage_target_in_isolation"
  | "execute_bounded_target_probe"
  | "stop_and_verify_target_process_tree"
  | "retain_verified_rollback_generation"
  | "publish_verified_target_package"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLocalUpdatePreview {
  contract_version: "mcp-managed-local-update-preview.v1";
  action: "update";
  management_id: string;
  expected_revision: number;
  current_version: string;
  current_plan_revision: string;
  target_version: string | null;
  target_catalog_id: string | null;
  target_option_id: string | null;
  target_plan_revision: string | null;
  availability: "available" | "unavailable";
  reason:
    | "ready_for_native_confirmation"
    | "local_package_required"
    | "install_required"
    | "cleanup_required"
    | "operation_in_progress"
    | "registry_unavailable"
    | "already_latest"
    | "current_version_metadata_changed"
    | "rollback_cleanup_required"
    | "configuration_migration_required"
    | "target_not_installable"
    | "target_option_ambiguous"
    | "permission_change_required"
    | "local_installer_unavailable";
  effects: McpManagedLocalUpdateEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface ApplyMcpManagedLocalUpdate {
  request_id: string;
  expected_revision: number;
  preview_digest: string;
}
export interface McpManagedLocalUpdateReceipt {
  contract_version: "mcp-managed-local-update-receipt.v1";
  action: "update";
  server: McpManagedServer;
  preview_digest: string;
  idempotent_replay: boolean;
  package_changed: true;
  process_started: true;
  process_tree_cleanup: "verified";
  rollback_generation_retained: true;
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}
export type McpManagedLocalRollbackEffect =
  | "verify_current_tree_digest"
  | "verify_rollback_tree_digest"
  | "atomically_swap_verified_generations"
  | "retain_superseded_current_generation"
  | "no_process_start"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLocalRollbackPreview {
  contract_version: "mcp-managed-local-rollback-preview.v1";
  action: "rollback";
  management_id: string;
  expected_revision: number;
  current_version: string;
  current_plan_revision: string;
  target_version: string | null;
  target_plan_revision: string | null;
  availability: "available" | "unavailable";
  reason:
    | "ready_for_native_confirmation"
    | "local_package_required"
    | "install_required"
    | "cleanup_required"
    | "operation_in_progress"
    | "rollback_generation_missing"
    | "local_installer_unavailable";
  effects: McpManagedLocalRollbackEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface ApplyMcpManagedLocalRollback extends ApplyMcpManagedLocalUpdate {}
export interface McpManagedLocalRollbackReceipt {
  contract_version: "mcp-managed-local-rollback-receipt.v1";
  action: "rollback";
  server: McpManagedServer;
  preview_digest: string;
  idempotent_replay: boolean;
  package_changed: true;
  process_started: false;
  process_tree_cleanup: "not_applicable";
  rollback_generation_retained: true;
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}
export type McpManagedLocalRollbackCleanupEffect =
  | "verify_rollback_tree_digest"
  | "quarantine_verified_rollback_generation"
  | "remove_quarantined_rollback_generation"
  | "keep_current_generation_installed"
  | "no_process_start"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLocalRollbackCleanupPreview {
  contract_version: "mcp-managed-local-rollback-cleanup-preview.v1";
  action: "cleanup_rollback_generation";
  management_id: string;
  expected_revision: number;
  rollback_version: string | null;
  rollback_plan_revision: string | null;
  availability: "available" | "unavailable";
  reason: McpManagedLocalRollbackPreview["reason"];
  effects: McpManagedLocalRollbackCleanupEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface ApplyMcpManagedLocalRollbackCleanup extends ApplyMcpManagedLocalUpdate {}
export interface McpManagedLocalRollbackCleanupReceipt {
  contract_version: "mcp-managed-local-rollback-cleanup-receipt.v1";
  action: "cleanup_rollback_generation";
  server: McpManagedServer;
  preview_digest: string;
  idempotent_replay: boolean;
  filesystem_changed: boolean;
  rollback_generation_retained: false;
  process_started: false;
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}
export type McpManagedLocalOperationRecoveryEffect =
  | "verify_operation_journal"
  | "restore_durable_current_generation"
  | "discard_verified_staged_target"
  | "retain_verified_rollback_generation"
  | "finish_verified_rollback_generation_removal"
  | "clear_cleanup_state"
  | "no_process_start"
  | "no_connection_retained"
  | "no_tool_authority";
export interface McpManagedLocalOperationRecoveryPreview {
  contract_version: "mcp-managed-local-operation-recovery-preview.v1";
  action: "recover_interrupted_local_operation";
  management_id: string;
  expected_revision: number;
  interrupted_action: "update" | "rollback" | "cleanup" | null;
  availability: "available" | "unavailable";
  reason:
    | "ready_for_native_confirmation"
    | "cleanup_not_required"
    | "unsupported_cleanup_state"
    | "process_cleanup_unconfirmed"
    | "local_installer_unavailable";
  effects: McpManagedLocalOperationRecoveryEffect[];
  preview_digest: string;
  native_confirmation_required: true;
}
export interface ApplyMcpManagedLocalOperationRecovery extends ApplyMcpManagedLocalUpdate {}
export interface McpManagedLocalOperationRecoveryReceipt {
  contract_version: "mcp-managed-local-operation-recovery-receipt.v1";
  action: "recover_interrupted_local_operation";
  recovered_action: "update" | "rollback" | "cleanup";
  server: McpManagedServer;
  preview_digest: string;
  idempotent_replay: boolean;
  filesystem_state_verified: true;
  process_started: false;
  endpoint_connected: false;
  connection_retained: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}
export interface CreateMcpManagedServer {
  request_id: string;
  catalog_id: string;
  name: string;
  version: string;
  option_id: string;
  plan_revision: string;
}
export interface SetMcpManagedProjectBinding {
  request_id: string;
  expected_revision: number;
  enabled: boolean;
  granted_permissions: McpManagedPermission[];
  admitted_tool_ids: string[];
}
export interface StoreMcpManagedSecret {
  request_id: string;
  expected_revision: number;
  value: string;
}
export interface RemoveMcpManagedSecret {
  request_id: string;
  expected_revision: number;
}
export interface StoreMcpManagedConfiguration {
  request_id: string;
  expected_revision: number;
  value: string;
}
export interface RemoveMcpManagedConfiguration {
  request_id: string;
  expected_revision: number;
}
export interface ProbeMcpManagedServer {
  request_id: string;
  expected_revision: number;
}
export interface BeginAgentNativeAcceptance {
  confirmation: "begin_guarded_agent_native_acceptance";
}
export interface AgentNativeAcceptanceStartReceipt {
  contract_version: "agent-native-acceptance-start.v1";
  owner_presence_confirmed: true;
  model_execution_started: false;
  process_spawn_requested: false;
  workspace_access_requested: false;
  content_persisted: false;
  expires_on_reload: true;
}
export type AgentSettings = Schemas["AgentSettings"];
export type AgentSessionView = Schemas["AgentSessionView"];
export type AgentSessionContextStatus = Schemas["AgentSessionContextStatus"];
export type AgentProject = Schemas["AgentProjectRecord"];
export type AgentProjectList = Schemas["AgentProjectList"];
export type AgentProjectPage = Schemas["AgentProjectPage"];
export type AgentCatalogSession = Schemas["AgentCatalogSessionRecord"];
export type AgentCatalogSessionList = Schemas["AgentCatalogSessionList"];
export type AgentCatalogSessionPage = Schemas["AgentCatalogSessionPage"];
export type CreateAgentProject = Schemas["CreateAgentProject"];
export type UpdateAgentProject = Schemas["UpdateAgentProject"];
export type UpdateAgentCatalogSession = Schemas["UpdateAgentCatalogSession"];
export interface DeleteAgentProject {
  expected_revision: number;
}
export interface DeleteAgentCatalogSession {
  expected_catalog_revision: number;
  expected_history_revision: number;
}
export type SwitchAgentSessionModel = Schemas["SwitchAgentSessionModel"];
export type ResumeAgentSession = Schemas["ResumeAgentSession"];
export type ForkAgentSession = Schemas["ForkAgentSession"];
export type AgentSessionForkReceipt = Schemas["AgentSessionForkReceipt"];
export type AgentSessionLineage = Schemas["AgentSessionLineage"];
export type RevalidateAgentAuthority = Schemas["RevalidateAgentAuthority"];
export type AgentHistoryExport = Schemas["AgentHistoryExport"];
export type AgentArtifact = Schemas["AgentArtifact"];
export type AgentArtifactCapturePreview = Schemas["AgentArtifactCapturePreview"];
export type AgentArtifactDetail = Schemas["AgentArtifactDetail"];
export type AgentArtifactExport = Schemas["AgentArtifactExport"];
export type AgentArtifactList = Schemas["AgentArtifactList"];
export type AgentArtifactPage = Schemas["AgentArtifactPage"];
export type AgentArtifactLifecycleCounts = Schemas["AgentArtifactLifecycleCounts"];
export type AgentArtifactListView = AgentArtifactList["view"];
export type AgentArtifactVersion = Schemas["AgentArtifactVersion"];
export type CaptureAgentArtifact = Schemas["CaptureAgentArtifact"];
export type ExportAgentArtifact = Schemas["ExportAgentArtifact"];
export type UpdateAgentArtifact = Schemas["UpdateAgentArtifact"];
export type RemoveAgentArtifact = Schemas["RemoveAgentArtifact"];
export type PreviewAgentArtifactCapture = Schemas["PreviewAgentArtifactCapture"];
export type AgentDocumentPreview = Schemas["AgentDocumentPreview"];
export interface AgentArtifactContent {
  blob: Blob;
  contentType: string;
  filename: string;
  byteSize: number;
}
export type AgentAttachment = Schemas["AgentAttachment"];
export type AgentAttachmentDocumentPreview = Schemas["AgentAttachmentDocumentPreview"];
export type AgentAttachmentList = Schemas["AgentAttachmentList"];
export type AgentMessageAttachment = Schemas["AgentMessageAttachment"];
export interface AgentAttachmentUpload {
  blob: Blob;
  displayName: string;
  source: "file" | "microphone";
}
export interface AgentAttachmentContent {
  blob: Blob;
  contentType: "image/png" | "image/jpeg" | "audio/wav";
  filename: string;
  byteSize: number;
}
export interface AgentCatalogQuery {
  search?: string;
  includeArchived?: boolean;
  limit?: number;
}
export interface AgentCatalogSessionQuery extends AgentCatalogQuery {
  projectId?: string;
}
export interface AgentCatalogPageQuery extends AgentCatalogQuery {
  offset?: number;
  snapshot?: string;
}
export interface AgentCatalogSessionPageQuery extends AgentCatalogPageQuery {
  projectId?: string;
}
export interface AgentArtifactPageQuery {
  view?: AgentArtifactListView;
  limit?: number;
  offset?: number;
  snapshot?: string;
}
export interface AgentHistoryExportRequest {
  expected_catalog_revision: number;
  expected_history_revision: number;
}
export type AgentChangeSet = Schemas["AgentChangeSet"];
export type AgentChangeDiff = Schemas["AgentChangeDiff"];
export type AgentChangedFile = Schemas["AgentChangedFile"];
export type AgentChangeRestorePreviewCommand = Schemas["AgentChangeRestorePreviewCommand"];
export type AgentChangeRestorePreview = Schemas["AgentChangeRestorePreview"];
export type AgentChangeRestoreApplyCommand = Schemas["AgentChangeRestoreApplyCommand"];
export type AgentChangeRestoreApplyResult = Schemas["AgentChangeRestoreApplyResult"];
export type AgentEvents = Schemas["AgentEvents"];
export type AgentEvent = Schemas["AgentEvent"];
export type AgentMcpToolDescriptor = Schemas["AgentMcpToolDescriptor"];
export type AgentMcpToolResultReceipt = Schemas["AgentMcpToolResultReceipt"];
export type AgentToolExecutionReceipt = Schemas["AgentToolExecutionReceipt"];
export type AgentTurnSummary = Schemas["AgentTurnSummary"];
export type AgentWriteReceipt = Schemas["AgentWriteReceipt"];
export type AgentTokenUsage = Schemas["AgentTokenUsage"];
export type AgentWorkspaceTree = Schemas["WorkspaceTree"];
export type AgentWorkspaceEntry = Schemas["WorkspaceEntry"];
export type AgentWorkspaceDiscovery = Schemas["WorkspaceDiscovery"];
export type AgentWorkspaceDiscoveryFile = Schemas["WorkspaceDiscoveryFile"];
export type AgentWorkspaceGitChange = Schemas["WorkspaceGitChange"];
export type AgentWorkspaceFile = Schemas["WorkspaceFile"];
export type AgentWorkspaceSearchMatch = Schemas["WorkspaceSearchMatch"];
export type AgentWorkspaceSearchResult = Schemas["WorkspaceSearchResult"];
export type { AgentMessageSearchRequest, AgentMessageSearchMatch, AgentMessageSearchResult } from "./agentMessageSearchContract";
export type AgentWorkspaceSearchRequest = {
  query: string;
  glob: string;
  regex: boolean;
};
export type AgentWorkspacePreviewCommand = Schemas["WorkspacePreviewCommand"];
export type AgentWorkspaceEditPreview = Schemas["WorkspaceEditPreview"];
export type AgentWorkspaceApplyCommand = Schemas["WorkspaceApplyCommand"];
export type AgentWorkspaceApplyResult = Schemas["WorkspaceApplyResult"];
export type AgentWorkspaceCreatePreviewCommand = Schemas["WorkspaceCreatePreviewCommand"];
export type AgentWorkspaceCreatePreview = Schemas["WorkspaceCreatePreview"];
export type AgentWorkspaceCreateApplyCommand = Schemas["WorkspaceCreateApplyCommand"];
export type AgentWorkspaceCreateApplyResult = Schemas["WorkspaceCreateApplyResult"];
export type AgentWorkspaceDirectoryCreatePreviewCommand = Schemas["WorkspaceDirectoryCreatePreviewCommand"];
export type AgentWorkspaceDirectoryCreatePreview = Schemas["WorkspaceDirectoryCreatePreview"];
export type AgentWorkspaceDirectoryCreateApplyCommand = Schemas["WorkspaceDirectoryCreateApplyCommand"];
export type AgentWorkspaceDirectoryCreateApplyResult = Schemas["WorkspaceDirectoryCreateApplyResult"];
export type AgentWorkspaceDirectoryMovePreviewCommand = Schemas["WorkspaceDirectoryMovePreviewCommand"];
export type AgentWorkspaceDirectoryMovePreview = Schemas["WorkspaceDirectoryMovePreview"];
export type AgentWorkspaceDirectoryMoveApplyCommand = Schemas["WorkspaceDirectoryMoveApplyCommand"];
export type AgentWorkspaceDirectoryMoveApplyResult = Schemas["WorkspaceDirectoryMoveApplyResult"];
export type AgentWorkspaceFileTrashPreviewCommand = Schemas["WorkspaceFileTrashPreviewCommand"];
export type AgentWorkspaceFileTrashPreview = Schemas["WorkspaceFileTrashPreview"];
export type AgentWorkspaceFileTrashApplyCommand = Schemas["WorkspaceFileTrashApplyCommand"];
export type AgentWorkspaceFileTrashApplyResult = Schemas["WorkspaceFileTrashApplyResult"];
export type AgentWorkspaceMovePreviewCommand = Schemas["WorkspaceMovePreviewCommand"];
export type AgentWorkspaceMovePreview = Schemas["WorkspaceMovePreview"];
export type AgentWorkspaceMoveApplyCommand = Schemas["WorkspaceMoveApplyCommand"];
export type AgentWorkspaceMoveApplyResult = Schemas["WorkspaceMoveApplyResult"];
export type AgentWorkspaceTransactionChangeCommand = Schemas["WorkspaceTransactionChangeCommand"];
export type AgentWorkspaceTransactionPreviewCommand = Schemas["WorkspaceTransactionPreviewCommand"];
export type AgentWorkspaceTransactionPreviewFile = Schemas["WorkspaceTransactionPreviewFile"];
export type AgentWorkspaceTransactionPreview = Schemas["WorkspaceTransactionPreview"];
export type AgentWorkspaceTransactionApplyChange = Schemas["WorkspaceTransactionApplyChange"];
export type AgentWorkspaceTransactionApplyCommand = Schemas["WorkspaceTransactionApplyCommand"];
export type AgentWorkspaceTransactionFileResult = Schemas["WorkspaceTransactionFileResult"];
export type AgentWorkspaceTransactionApplyResult = Schemas["WorkspaceTransactionApplyResult"];
export type OnboardingStatus = Schemas["OnboardingStatus"];
export type ProviderDetection = Schemas["ProviderDetection"];
export type OnboardingAccept = Schemas["OnboardingAccept"];
export type OnboardingResult = Schemas["OnboardingResult"];
export type CalibrationSample = Schemas["CalibrationSample"];
export type CalibrationSampleMember = Schemas["CalibrationSampleMember"];
export type CalibrationRating = Schemas["CalibrationRating"];
export type CalibrationReview = Schemas["CalibrationReview"];
export type CalibrationProgress = Schemas["CalibrationProgress"];
export type CalibrationExport = Schemas["CalibrationExport"];
export type RatingSubmission = Schemas["RatingSubmission"];
export type RatingLabel = Schemas["RatingLabel"];
export type SessionTranscriptTurn = Schemas["ReaderTurn"];
export type Provider = Schemas["Provider"];
export type ProviderCapabilityReport = Schemas["ProviderCapabilityReport"];
export type ProviderMetricCapability = Schemas["ProviderMetricCapability"];
export type ProviderMetricCapabilityReason =
  Schemas["ProviderMetricCapabilityReason"];
export type ProviderMetricCapabilityState =
  Schemas["ProviderMetricCapabilityState"];
export type MetricEvidenceCapability = Schemas["MetricEvidenceCapability"];
export type MetricReadiness = Schemas["MetricReadiness"];
export type MetricReadinessAction = Schemas["MetricReadinessAction"];
export type MetricReadinessReason = Schemas["MetricReadinessReason"];
export type MetricReadinessState = Schemas["MetricReadinessState"];
export type MetricRadarPolicy = Schemas["MetricRadarPolicy"];
export type MetricCoverageMetric = Schemas["MetricCoverageMetric"];
export type MetricCoverageReport = Schemas["MetricCoverageReport"];
export type MetricCoverageScope = Schemas["MetricCoverageScope"];
export type MetricResultStateCounts = Schemas["MetricResultStateCounts"];
export type SessionMetricReadinessReport =
  Schemas["SessionMetricReadinessReport"];
export type TextAnalysisPresetId = Schemas["TextAnalysisPresetId"];

export type CodexSession = Schemas["SessionCatalogItemDto"];
/** Provider-neutral name for the same catalog row; `CodexSession` is the legacy alias. */
export type SessionCatalogItem = Schemas["SessionCatalogItemDto"];

/** Every provider whose sessions can appear in the local catalog. */
export const LOCAL_PROVIDERS = ["codex", "claude_code", "synthetic"] as const;
export type LocalProvider = (typeof LOCAL_PROVIDERS)[number];

export function isLocalProvider(value: unknown): value is LocalProvider {
  return typeof value === "string" && (LOCAL_PROVIDERS as readonly string[]).includes(value);
}

/** Human label for a provider; never derived from session content. */
export function providerLabel(provider: unknown): string {
  switch (provider) {
    case "codex":
      return "Codex";
    case "claude_code":
      return "Claude Code";
    case "synthetic":
      return "Synthetic";
    default:
      return "Unknown source";
  }
}
export type CodexSessionListResponse = Schemas["SessionCatalogListResponse"];
export type ProjectSessionListResponse =
  Schemas["ProjectSessionCatalogResponse"];
export type TextAnalysisResearchCatalog =
  Schemas["TextAnalysisResearchCatalogDto"];
export type ModelRuntimeInventory = Schemas["ModelRuntimeInventoryDto"];
export type ModelCompatibilityCatalog =
  Schemas["ModelCompatibilityCatalogDto"];
export type ModelCompatibilityEntry = Schemas["ModelCompatibilityEntryDto"];
export type ModelEvaluationRequest = Schemas["ModelEvaluationRequestDto"];
export type ModelEvaluationJob = Schemas["ModelEvaluationJobDto"];
export type ModelLabInventory = Schemas["ModelLabInventoryDto"];
export type ModelLabPlanSummary = Schemas["ModelLabPlanSummaryDto"];
export type ModelLinkExperiment = Schemas["ModelLinkExperimentDto"];
export type ModelLinkExperimentRequest = Schemas["ModelLinkExperimentRequest"];
export type ModelLinkExperimentOutcome =
  Schemas["ModelLinkExperimentCommandResponse"];
export type ModelLinkAnnotation = Schemas["ModelLinkAnnotationDto"];
export type ModelLinkAnnotationRequest = Schemas["ModelLinkAnnotationRequest"];
export type ModelEnsembleRequest = Schemas["ModelEnsembleRequest"];

/**
 * Handwritten strict-narrowing seam over the generated r6 client. It preserves
 * historical projection unions while making the current receipt fields that
 * the runtime always serializes explicit to presentation code.
 */
export type MetricProjectionV2Version =
  | Schemas["MetricStateV2"]["projection_version"]
  | "metric-contract-v2-projection-6"
  | "metric-contract-v2-projection-7"
  | "metric-contract-v2-projection-8";
export type MetricStateV2 = Omit<Schemas["MetricStateV2"], "projection_version"> & {
  projection_version: MetricProjectionV2Version;
};
export type PublishedMetricV2 = Omit<Schemas["PublishedMetricV2"], "state"> & {
  state: MetricStateV2;
};
export type MetricPublicationV2Contract = Omit<
  Schemas["MetricPublicationV2"],
  "projection_version" | "metrics"
> & {
  projection_version: MetricProjectionV2Version;
  metrics: PublishedMetricV2[];
};

export interface ModelRequirementPlanEvidenceBinding {
  evidence_source: "unavailable" | "awaiting_review" | "reviewed_requirement_plan";
  confirmation_id: string | null;
  proposal_id: string | null;
  evidence_fingerprint: string;
  evidence_schema_version:
    | "requirement-plan-unavailable-v1"
    | "requirement-plan-awaiting-review-v1"
    | "requirement-plan-evidence-v1";
  evidence_policy_version: "reviewed-requirement-plan-v1";
  local_only: true;
  content_persisted: false;
}

export interface ModelRequirementActionEvidenceBinding {
  evidence_source:
    | "unavailable"
    | "awaiting_review"
    | "candidate_manifest_overflow"
    | "candidate_source_incomplete"
    | "binding_invalid"
    | "reviewed_requirement_action";
  source_run_id: string | null;
  requirement_plan_confirmation_id: string | null;
  requirement_plan_evidence_fingerprint: string | null;
  candidate_manifest_fingerprint: string | null;
  confirmation_id: string | null;
  proposal_id: string | null;
  reviewed_descriptor_set_fingerprint: string | null;
  evidence_fingerprint: string;
  evidence_schema_version:
    | "requirement-action-unavailable-v1"
    | "requirement-action-awaiting-review-v1"
    | "requirement-action-candidate-manifest-overflow-v1"
    | "requirement-action-candidate-source-incomplete-v1"
    | "requirement-action-binding-invalid-v1"
    | "requirement-action-evidence-v1";
  evidence_policy_version: "reviewed-requirement-action-v1";
  local_only: true;
  content_persisted: false;
}

/** Content-free requirement-verification authority frozen into one r8 run. */
export interface ModelRequirementVerificationEvidenceBinding {
  evidence_source:
    | "unavailable"
    | "opportunity_bound_exceeded"
    | "awaiting_evidence"
    | "persisted_evidence";
  requirement_plan_confirmation_id: string | null;
  requirement_plan_proposal_id: string | null;
  requirement_plan_evidence_fingerprint: string | null;
  requirement_plan_schema_version: "requirement-plan-evidence-v1" | null;
  requirement_plan_policy_version: "reviewed-requirement-plan-v1" | null;
  requirement_plan_review_rubric_version: "active-requirement-plan-review-rubric-v1" | null;
  opportunity_count: number | null;
  opportunity_set_fingerprint: string | null;
  evidence_set_fingerprint: string | null;
  through_revision: number | null;
  authority_head_count: number | null;
  objective_result_count: number | null;
  native_acceptance_count: number | null;
  resolved_opportunity_count: number | null;
  met_requirement_count: number | null;
  opportunity_issuer_version: "reviewed-r6-requirement-opportunity-issuer-v1";
  result_issuer_version: "local-objective-verification-result-issuer-v1";
  acceptance_issuer_version: "native-explicit-requirement-acceptance-issuer-v1";
  evidence_schema_version: "requirement-verification-evidence-v1";
  evidence_policy_version: "app-issued-reviewed-requirement-verification-v1";
  persistence_schema_version: "requirement-verification-persistence-v1";
  evidence_projection_version: "reviewed-requirement-verification-objective-projection-v1";
  objective_projection_version: "reviewed-requirement-verification-objective-projection-v1";
  binding_schema_version: "session-requirement-verification-evidence-binding-v1";
  binding_fingerprint: string;
  local_only: true;
  content_persisted: false;
}

export type ModelEnsembleRun = Omit<
  Schemas["ModelEnsembleRunDto"],
  | "metric_publication_v2"
  | "metric_evidence_readiness_v2"
  | "requirement_plan_evidence_binding"
  | "requirement_action_evidence_binding"
  | "requirement_verification_evidence_binding"
> & {
  metric_publication_v2: MetricPublicationV2Contract | null;
  metric_evidence_readiness_v2: MetricEvidenceReadinessProjectionV2 | null;
  requirement_plan_evidence_binding: ModelRequirementPlanEvidenceBinding | null;
  requirement_action_evidence_binding: ModelRequirementActionEvidenceBinding | null;
  requirement_verification_evidence_binding: ModelRequirementVerificationEvidenceBinding | null;
};

/** Manual bridge until the generated OpenAPI client includes the reviewed profile route. */
export type DeclaredTaskProfileConstraintKind =
  | "privacy"
  | "cost"
  | "platform"
  | "version"
  | "scope"
  | "performance"
  | "delivery"
  | "safety";
export type DeclaredTaskProfileDeliverableSlot =
  | "artifact"
  | "format"
  | "location"
  | "audience"
  | "interface"
  | "compatibility";
export interface DeclaredTaskProfile {
  profile_id: string;
  provider: Provider;
  session_id: string;
  revision: number;
  previous_profile_id: string | null;
  constraint_kinds: readonly DeclaredTaskProfileConstraintKind[] | null;
  expected_outcome_count: number | null;
  deliverable_slots: readonly DeclaredTaskProfileDeliverableSlot[] | null;
  profile_fingerprint: string;
  confirmed_at: string;
  confirmation_authority: "authenticated_local_user";
  schema_version: "declared-task-profile-v1";
  policy_version: "authenticated-local-user-v1";
  local_only: true;
  content_persisted: false;
}
export interface DeclaredTaskProfileCurrent {
  session_id: string;
  profile: DeclaredTaskProfile | null;
  /** True only when a non-self-issuable user-presence adapter is composed. */
  confirmation_available: boolean;
}
export interface DeclaredTaskProfileCommand {
  expected_revision: number | null;
  constraint_kinds: readonly DeclaredTaskProfileConstraintKind[] | null;
  expected_outcome_count: number | null;
  deliverable_slots: readonly DeclaredTaskProfileDeliverableSlot[] | null;
  confirmation: "save_reviewed_declared_task_profile";
}
export interface DeclaredTaskProfileOutcome {
  profile: DeclaredTaskProfile;
  applied: boolean;
}
export type MetricEvidenceContributor =
  | Schemas["MetricEvidenceContributor"]
  | "reviewed_requirement_enumeration"
  | "reviewed_requirement_plan_disposition"
  | "reviewed_requirement_action_link"
  | "safe_action_candidate_enumeration";
export type MetricEvidenceReadinessReason =
  | Schemas["MetricEvidenceReadinessReason"]
  | "reviewed_requirement_plan_service_required"
  | "reviewed_requirement_plan_confirmation_required"
  | "reviewed_requirement_plan_binding_invalid"
  | "reviewed_requirement_action_service_required"
  | "reviewed_requirement_action_confirmation_required"
  | "reviewed_requirement_action_binding_invalid";
export type MetricEvidenceReadinessV2 = Omit<
  Schemas["MetricEvidenceReadinessV2"],
  "required_contributors" | "observed_contributors" | "missing_contributors" | "reason_code"
> & {
  required_contributors: MetricEvidenceContributor[];
  observed_contributors: MetricEvidenceContributor[];
  missing_contributors: MetricEvidenceContributor[];
  reason_code: MetricEvidenceReadinessReason;
};
export type MetricEvidenceReadinessProjectionV2 = Omit<
  Schemas["MetricEvidenceReadinessProjectionV2"],
  "catalog_version" | "metric_projection_version" | "metrics"
> & {
  catalog_version:
    | "metric-evidence-readiness-v2-2"
    | "metric-evidence-readiness-v2-3"
    | "metric-evidence-readiness-v2-4"
    | "metric-evidence-readiness-v2-5"
    | "metric-evidence-readiness-v2-6"
    | "metric-evidence-readiness-v2-7";
  metric_projection_version: MetricProjectionV2Version;
  metrics: MetricEvidenceReadinessV2[];
};
export type MetricEvidenceAvailabilityState =
  Schemas["MetricEvidenceAvailabilityState"];
export type MetricOperabilityEntry = Omit<
  Schemas["MetricOperabilityEntry"],
  "measured_path" | "next_step_code"
> & {
  measured_path:
    | Schemas["MetricOperabilityEntry"]["measured_path"]
    | "reviewed_requirement_plan"
    | "reviewed_requirement_action";
  next_step_code:
    | Schemas["MetricOperabilityEntry"]["next_step_code"]
    | "confirm_requirement_plan_evidence"
    | "compose_requirement_action_evidence";
};
export type MetricOperabilityCatalog = Omit<
  Schemas["MetricOperabilityCatalog"],
  "catalog_version" | "projection_version" | "readiness_catalog_version" | "entries"
> & {
  catalog_version: "metric-operability-v4";
  projection_version: "metric-contract-v2-projection-8";
  readiness_catalog_version: "metric-evidence-readiness-v2-7";
  entries: MetricOperabilityEntry[];
};

export interface RequirementPlanCoordinate {
  message_sequence: number;
  clause_index: number;
}
export interface RequirementPlanEvidenceEntry {
  coordinate: RequirementPlanCoordinate;
  disposition: "linked" | "not_linked" | "pending";
  plan_indexes: number[];
}
export interface RequirementPlanProducer {
  kind: "local_coding_agent";
  producer_id: string;
  producer_version: string;
  model_id: string;
  authority: "untrusted_provenance_claim";
}
export type RequirementPlanClauseAlgorithmContract = Schemas["RequirementPlanClauseAlgorithmContract"];
export type RequirementPlanReviewRubric = Schemas["RequirementPlanReviewRubric"];
export type RequirementPlanExclusionReason = Schemas["RequirementPlanExclusionReason"];
export type RequirementPlanProducerReceipt = Schemas["RequirementPlanProducerReceipt"];
export type ExcludedRequirementClause = Omit<
  Schemas["ExcludedRequirementClause"],
  "basis_coordinate"
> & { basis_coordinate: RequirementPlanCoordinate | null };
export type RequirementPlanSourceManifest = Omit<
  Schemas["RequirementPlanSourceManifest"],
  "clause_algorithm_spec" | "review_rubric"
> & {
  clause_algorithm_spec: RequirementPlanClauseAlgorithmContract;
  review_rubric: RequirementPlanReviewRubric;
};
export interface RequirementPlanEvidenceContract {
  schema_version: "requirement-plan-evidence-file-v1";
  session_id: string;
  expected_source_run_id: string;
  source_window_fingerprint: string;
  expected_predecessor_confirmation_id: string | null;
  registry_version: "all-20-factor-contracts-v2";
  contract_set_fingerprint: string;
  metric_key: "logic.decomposition_coverage";
  metric_contract_fingerprint: string;
  source_projection_version:
    | "metric-contract-v2-projection-5"
    | "metric-contract-v2-projection-6"
    | "metric-contract-v2-projection-7"
    | "metric-contract-v2-projection-8";
  clause_algorithm: "message-clause-coordinates-en-pl-v1";
  clause_algorithm_spec: RequirementPlanClauseAlgorithmContract;
  review_rubric_version: "active-requirement-plan-review-rubric-v1";
  review_rubric: RequirementPlanReviewRubric;
  allowed_dispositions: ["linked", "not_linked", "pending"];
  allowed_user_clause_classifications: [
    "active_requirement", "excluded_from_active_requirement_denominator",
  ];
  allowed_exclusion_reasons: [
    "not_requirement", "superseded", "withdrawn", "duplicate", "out_of_scope",
    "already_satisfied_or_closed",
  ];
  max_reviewed_user_clause_count: 1000;
  max_active_requirement_count: 1000;
  max_excluded_user_clause_count: 1000;
  max_plan_item_count: 1000;
  max_link_count: 4000;
  max_file_bytes: 65536;
  max_json_depth: 8;
  max_json_items: 6000;
  max_clauses_per_message: 128;
  max_lifetime_seconds: 86400;
  canonical_json_required: true;
  canonicalization: "json-sort-keys-compact-ensure-ascii-v1";
  payload_digest: "sha256";
  utf8_without_bom_required: true;
  duplicate_keys_allowed: false;
  floating_point_values_allowed: false;
  candidate_unit: "reviewable_user_request_or_feedback_clause";
  opportunity_unit: "reviewed_active_requirement_clause";
  complete_user_clause_classification_required: true;
  compound_clause_coarsening_disclosed: true;
  one_active_requirement_coordinate_is_one_opportunity: true;
  excluded_user_clauses_are_excluded_from_metric: true;
  uncertain_classification_policy: "reject_or_leave_proposal_unconfirmed";
  import_creates_unconfirmed_proposal_only: true;
  native_confirmation_required_for_metric_authority: true;
  raw_payload_persisted: false;
  prose_allowed: false;
  scores_allowed: false;
  untrusted_structured_classification_proposals_allowed: true;
  authoritative_model_judgment_claims_allowed: false;
  raw_producer_claim_persisted: false;
  durable_producer_claim_shape: "installation_keyed_opaque_commitment_only";
  objective_receipt_claims_allowed: false;
  import_confirmation: "import_requirement_plan_evidence_as_unconfirmed_proposal";
  file_json_schema_sha256: string;
  file_json_schema: Record<string, unknown>;
  source_manifest: RequirementPlanSourceManifest;
  file_constraint_contract_version: "requirement-plan-file-constraints-v1";
  file_constraint_codes: readonly [
    "identifiers_match_current_contract",
    "producer_codes_match_safe_version_pattern",
    "expires_at_is_utc_after_validation_and_within_86400_seconds",
    "requirement_coordinates_are_sorted_unique",
    "plan_coordinates_are_sorted_unique",
    "plan_indexes_are_sorted_unique_non_negative",
    "linked_requires_nonempty_plan_indexes",
    "nonlinked_and_pending_require_empty_plan_indexes",
    "plan_indexes_reference_existing_plan_items",
    "total_plan_indexes_lte_4000",
    "requirement_coordinates_reference_user_request_or_feedback_clauses",
    "excluded_user_clause_coordinates_are_sorted_unique",
    "excluded_user_clause_reasons_use_closed_rubric",
    "exclusion_basis_coordinates_follow_reason_rules",
    "user_clauses_exactly_classified_as_active_or_excluded",
    "active_and_excluded_user_clause_coordinates_are_disjoint",
    "source_messages_fail_closed_above_128_normalized_clauses",
    "plan_coordinates_reference_agent_plan_clauses",
    "linked_plan_sequence_gte_requirement_sequence",
  ];
}
export interface RequirementPlanEvidencePreview {
  payload_sha256: string;
  session_id: string;
  expected_source_run_id: string;
  source_window_fingerprint: string;
  expected_predecessor_confirmation_id: string | null;
  reviewed_user_clause_count: number;
  active_requirement_count: number;
  excluded_user_clause_count: number;
  plan_item_count: number;
  linked_active_requirement_count: number;
  not_linked_active_requirement_count: number;
  pending_active_requirement_count: number;
  link_count: number;
  expires_at: string;
  producer: RequirementPlanProducer;
  creates_unconfirmed_proposal_only: true;
  native_confirmation_required_for_metric_authority: true;
  can_set_numeric_metric_on_import: false;
  raw_payload_persisted: false;
  raw_producer_claim_persisted: false;
}
export interface RequirementPlanProposal {
  proposal_id: string;
  session_id: string;
  source_run_id: string;
  source_window_fingerprint: string;
  expected_predecessor_confirmation_id: string | null;
  payload_sha256: string;
  producer_receipt: RequirementPlanProducerReceipt;
  review_rubric_version: "active-requirement-plan-review-rubric-v1";
  requirements: RequirementPlanEvidenceEntry[];
  excluded_user_clauses: ExcludedRequirementClause[];
  plan_items: RequirementPlanCoordinate[];
  created_at: string;
  schema_version: "requirement-plan-evidence-v1";
  policy_version: "reviewed-requirement-plan-v1";
  status: "proposed" | "confirmed" | "rejected";
  decision_id: string | null;
  decision: "confirm" | "reject" | null;
  decided_at: string | null;
  confirmation_authority: "owned_native_user_presence" | null;
  local_only: true;
  content_persisted: false;
}
export interface RequirementPlanImport {
  payload_sha256: string;
  proposal: RequirementPlanProposal;
  applied: boolean;
  creates_unconfirmed_proposal_only: true;
  native_confirmation_required_for_metric_authority: true;
  raw_payload_persisted: false;
}
export interface RequirementPlanProposalOutcome {
  proposal: RequirementPlanProposal;
  applied: boolean;
}
export type RequirementPlanProposalPageSnapshot = Schemas["RequirementPlanProposalPageSnapshot"];
export type RequirementPlanReviewClause = Omit<
  Schemas["RequirementPlanReviewClause"],
  "basis_coordinate" | "classification" | "disposition" | "exclusion_reason"
> & {
  basis_coordinate: RequirementPlanCoordinate | null;
  classification: "active_requirement" | "excluded_from_active_requirement_denominator" | null;
  disposition: "linked" | "not_linked" | "pending" | null;
  exclusion_reason: RequirementPlanExclusionReason | null;
};
export type RequirementPlanProposalReview = Omit<
  Schemas["RequirementPlanProposalReview"],
  "candidate_clauses"
> & { candidate_clauses: RequirementPlanReviewClause[] };
export interface RequirementPlanReviewRequest {
  expected_source_run_id: string;
  confirmation: "open_exact_local_requirement_plan_clause_review";
}
export interface RequirementPlanProposalPage {
  session_id: string;
  proposals: RequirementPlanProposal[];
  limit: number;
  offset: number;
  total: number;
  next_offset: number | null;
  complete: boolean;
  snapshot: RequirementPlanProposalPageSnapshot;
}
export interface RequirementPlanProposalCollection {
  session_id: string;
  proposals: RequirementPlanProposal[];
  total: number;
  complete: true;
  snapshot: RequirementPlanProposalPageSnapshot;
}
export interface RequirementPlanConfirmDecisionRequest {
  expected_source_run_id: string;
  decision: "confirm";
  confirmation: "apply_local_user_requirement_plan_evidence_decision";
  review_receipt_id: string;
  manifest_fingerprint: string;
  reviewed_graph_fingerprint: string;
  reviewed_candidate_set_fingerprint: string;
  complete_review_acknowledged: true;
}
export interface RequirementPlanRejectDecisionRequest {
  expected_source_run_id: string;
  decision: "reject";
  confirmation: "apply_local_user_requirement_plan_evidence_decision";
}
export type RequirementPlanDecisionRequest =
  | RequirementPlanConfirmDecisionRequest
  | RequirementPlanRejectDecisionRequest;

/** Explicit r7/r8 facade narrowed by the strict runtime parsers below the generated wire types. */
export interface RequirementActionEvidenceProvenance {
  provider: Provider;
  provider_version: string;
  adapter_version: string;
  decoder_key: string;
  decoder_version: string;
  source_schema_version: string;
  evidence_schema_version: 2;
  extraction_complete: boolean;
}
export type RequirementActionEventKind = "tool_start" | "tool_end" | "artifact";
export type RequirementActionToolCategory =
  | "file_read" | "file_write" | "command" | "search" | "test" | "build"
  | "version_control" | "network" | "mcp" | "subagent" | "other" | "unknown";
export type RequirementActionFamily = "tool" | "command" | "file_change" | "review" | "other_documented";
export type RequirementActionState = "started" | "completed" | "failed" | "cancelled" | "unknown";
export interface RequirementActionCandidate {
  candidate_index: number;
  action_id: string;
  source_reference_id: string;
  sequence: number;
  event_kind: RequirementActionEventKind;
  tool_category: RequirementActionToolCategory | null;
  occurred_at: string;
  duration_ms: number | null;
  family: RequirementActionFamily;
  state: RequirementActionState;
}
export interface RequirementActionCandidateManifest {
  session_id: string;
  source_run_id: string;
  source_window_fingerprint: string;
  provenance: RequirementActionEvidenceProvenance;
  extraction_complete: boolean;
  enumeration_complete: boolean;
  actions: RequirementActionCandidate[];
  manifest_fingerprint: string;
  schema_version: "requirement-action-candidate-manifest-v1";
  local_only: true;
  content_persisted: false;
}
export interface RequirementActionRequirement {
  requirement_index: number;
  requirement_id: string;
  coordinate: RequirementPlanCoordinate;
}
export interface RequirementActionEvidenceContract {
  action_descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1";
  action_descriptor_content_persisted: false;
  candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1";
  schema_version: "requirement-action-evidence-file-v1";
  session_id: string;
  expected_source_run_id: string;
  source_window_fingerprint: string;
  source_projection_version:
    | "metric-contract-v2-projection-6"
    | "metric-contract-v2-projection-7"
    | "metric-contract-v2-projection-8";
  requirement_plan_confirmation_id: string;
  requirement_plan_evidence_fingerprint: string;
  candidate_manifest: RequirementActionCandidateManifest;
  requirements: RequirementActionRequirement[];
  expected_predecessor_confirmation_id: string | null;
  metric_key: "logic.requirement_action_traceability";
  max_requirement_count: 1000;
  max_candidate_count: 4000;
  max_link_count: 8000;
  max_file_bytes: 65536;
  max_json_depth: 8;
  max_json_items: 8000;
  max_lifetime_seconds: 86400;
  canonicalization: "json-sort-keys-compact-ensure-ascii-v1";
  import_creates_unconfirmed_proposal_only: true;
  native_confirmation_required_for_metric_authority: true;
  all_linked_action_semantics_acknowledgement_required: true;
  native_review_displays_every_redacted_invocation_and_effect: true;
  review_visible_display_algorithm_version: "requirement-action-review-visible-display-v1";
  review_visible_display_is_injective_one_pass: true;
  review_visible_display_never_truncates: true;
  every_requirement_requires_one_link_classification: true;
  empty_action_links_are_explicit_reviewed_negative_links: true;
  action_states_are_application_issued: true;
  action_state_claims_allowed_in_file: false;
  objective_proof_claims_allowed_in_file: false;
  metric_values_allowed_in_file: false;
  raw_payload_persisted: false;
  raw_producer_claim_persisted: false;
  durable_producer_claim_shape: "installation_keyed_opaque_commitment_only";
  import_confirmation: "import_requirement_action_proposal_without_metric_authority";
  review_rubric_version: "requirement-action-review-rubric-v2";
  file_json_schema_sha256: string;
  file_json_schema: Record<string, unknown>;
}
export interface RequirementActionEvidencePreview {
  payload_sha256: string;
  session_id: string;
  expected_source_run_id: string;
  source_window_fingerprint: string;
  requirement_plan_confirmation_id: string;
  requirement_plan_evidence_fingerprint: string;
  candidate_manifest_fingerprint: string;
  expected_predecessor_confirmation_id: string | null;
  requirement_count: number;
  candidate_count: number;
  linked_requirement_count: number;
  unlinked_requirement_count: number;
  link_count: number;
  expires_at: string;
  producer: RequirementPlanProducer;
  creates_unconfirmed_proposal_only: true;
  native_confirmation_required_for_metric_authority: true;
  can_set_numeric_metric_on_import: false;
  raw_payload_persisted: false;
  raw_producer_claim_persisted: false;
}
export interface RequirementActionLink {
  requirement_id: string;
  action_ids: string[];
}
export interface RequirementActionProposal {
  proposal_id: string;
  session_id: string;
  source_run_id: string;
  source_window_fingerprint: string;
  requirement_plan_confirmation_id: string;
  requirement_plan_evidence_fingerprint: string;
  candidate_manifest_fingerprint: string;
  candidate_provenance: RequirementActionEvidenceProvenance;
  candidate_extraction_complete: boolean;
  candidate_enumeration_complete: boolean;
  expected_predecessor_confirmation_id: string | null;
  payload_sha256: string;
  producer_receipt: RequirementPlanProducerReceipt;
  review_rubric_version: "requirement-action-review-rubric-v2";
  requirements: RequirementActionRequirement[];
  candidates: RequirementActionCandidate[];
  links: RequirementActionLink[];
  created_at: string;
  schema_version: "requirement-action-evidence-v1";
  policy_version: "reviewed-requirement-action-v1";
  status: "proposed" | "confirmed" | "rejected";
  decision_id: string | null;
  decision: "confirm" | "reject" | null;
  decided_at: string | null;
  confirmation_authority: "owned_native_user_presence" | null;
  local_only: true;
  content_persisted: false;
}
export interface RequirementActionImport {
  payload_sha256: string;
  proposal: RequirementActionProposal;
  applied: boolean;
  creates_unconfirmed_proposal_only: true;
  native_confirmation_required_for_metric_authority: true;
  raw_payload_persisted: false;
  raw_producer_claim_persisted: false;
}
export interface RequirementActionReviewRequirement {
  requirement_id: string;
  coordinate: RequirementPlanCoordinate;
  text: string;
  linked_action_ids: string[];
}
export interface RequirementActionReviewCandidate {
  candidate: RequirementActionCandidate;
  candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1";
  candidate_metadata_fingerprint: string;
  descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1";
  tool_name: string;
  invocation_preview: string;
  result_or_effect_preview: string | null;
  invocation_truncated: false;
  result_or_effect_truncated: false;
  redactor_version: string;
  linked_requirement_ids: string[];
}
export interface RequirementActionProposalReview {
  proposal_id: string;
  session_id: string;
  source_run_id: string;
  source_window_fingerprint: string;
  review_receipt_id: string;
  payload_sha256: string;
  requirement_plan_evidence_fingerprint: string;
  candidate_manifest_fingerprint: string;
  reviewed_graph_fingerprint: string;
  reviewed_candidate_set_fingerprint: string;
  reviewed_descriptor_set_fingerprint: string;
  review_visible_display_algorithm_version: "requirement-action-review-visible-display-v1";
  requirements: RequirementActionReviewRequirement[];
  candidates: RequirementActionCandidate[];
  candidate_memberships: RequirementActionReviewCandidate[];
  review_context_expires_at: string;
  review_receipt_expires_at: string;
  all_requirements_and_candidates_displayed: true;
  raw_text_persisted: false;
  local_only: true;
}
export interface RequirementActionProposalPageSnapshot {
  snapshot_id: string;
  total: number;
  decision_count: number;
  high_water_created_at: string | null;
  high_water_proposal_id: string | null;
}
export interface RequirementActionProposalPage {
  session_id: string;
  proposals: RequirementActionProposal[];
  limit: number;
  offset: number;
  total: number;
  snapshot: RequirementActionProposalPageSnapshot;
  next_offset: number | null;
  complete: boolean;
}
export interface RequirementActionProposalCollection {
  session_id: string;
  proposals: RequirementActionProposal[];
  total: number;
  complete: true;
  snapshot: RequirementActionProposalPageSnapshot;
}
export interface RequirementActionReviewRequest {
  expected_source_run_id: string;
  confirmation: "open_exact_local_requirement_action_review";
}
export interface RequirementActionConfirmDecisionRequest {
  expected_source_run_id: string;
  decision: "confirm";
  confirmation: "decide_exact_reviewed_requirement_action_proposal";
  review_receipt_id: string;
  reviewed_graph_fingerprint: string;
  candidate_manifest_fingerprint: string;
  reviewed_candidate_set_fingerprint: string;
  reviewed_descriptor_set_fingerprint: string;
  complete_review_acknowledged: true;
  all_requirements_and_candidates_acknowledged: true;
  all_linked_action_semantics_reviewed: true;
}
export interface RequirementActionRejectDecisionRequest {
  expected_source_run_id: string;
  decision: "reject";
  confirmation: "decide_exact_reviewed_requirement_action_proposal";
}
export type RequirementActionDecisionRequest =
  | RequirementActionConfirmDecisionRequest
  | RequirementActionRejectDecisionRequest;
export interface RequirementActionProposalOutcome {
  proposal: RequirementActionProposal;
  applied: boolean;
}
export type AgentMetricEvidencePreview = Schemas["AgentMetricEvidencePreviewDto"];
export type AgentMetricEvidenceImport = Schemas["AgentMetricEvidenceImportDto"];
export type MetricLifecycleProposal = Schemas["MetricLifecycleProposalDto"];
export type MetricLifecycleProposalList = Schemas["MetricLifecycleProposalListDto"];
export type MetricLifecycleProposalPage = Schemas["MetricLifecycleProposalPageDto"];
export type MetricLifecycleProposalOutcome = Schemas["MetricLifecycleProposalOutcomeDto"];
export type MetricLifecycleDecisionRequest = Schemas["MetricLifecycleDecisionCommand"];
export interface MetricLifecycleProposalCollection {
  session_id: string;
  proposals: MetricLifecycleProposal[];
  total: number;
  complete: boolean;
}
export type CapabilityKey = Schemas["CapabilityKey"];
export type ModelEnsembleOutcome = Omit<Schemas["ModelEnsembleOutcomeDto"], "run"> & {
  run: ModelEnsembleRun;
};
export type ModelEnsembleWatchRequest = Schemas["ModelEnsembleWatchRequest"];
export type ModelEnsembleWatch = Schemas["ModelEnsembleWatchDto"];
export type ModelEnsembleWatchSnapshot = Omit<Schemas["ModelEnsembleWatchSnapshotDto"], "latest_run"> & {
  latest_run: ModelEnsembleRun | null;
};
export type ModelEnsembleTrajectoryPoint = Omit<Schemas["ModelEnsembleTrajectoryPoint"], "metric_states_v2"> & {
  metric_states_v2: MetricStateV2[];
};
export type ModelEnsembleTrajectoryPage = Omit<Schemas["ModelEnsembleTrajectoryPage"], "points"> & {
  points: ModelEnsembleTrajectoryPoint[];
};
export type ModelPredictiveMetricDetail = Schemas["ModelPredictiveMetricDetailDto"];

export interface ModelEnsembleAttempt {
  attempt_id: string;
  watch_id: string;
  generation: number;
  state: "running" | "completed" | "partial" | "failed" | "cancelled";
  prior_head_run_id: string | null;
  published_run_id: string | null;
  progress_completed: number;
  progress_total: number;
  stage_count: number;
  warning_count: number;
  error_code: string | null;
  requested_at: string;
  started_at: string;
  completed_at: string | null;
  content_persisted: false;
}

export interface ModelEnsembleAttemptStage {
  stage_ordinal: number;
  stage_key: string;
  state: "completed" | "unavailable" | "resource_exhausted" | "failed" | "cancelled";
  model_key: string | null;
  repository_id: string | null;
  revision: string | null;
  error_code: string | null;
  device: "cpu" | "cuda" | "mps" | null;
  quantization: "none" | "bitsandbytes_nf4";
  inference_latency_ms: number | null;
  peak_accelerator_memory_mb: number | null;
  process_rss_mb: number | null;
  evaluated_case_count: number | null;
  contributed_case_count: number | null;
  unloaded_after_stage: boolean | null;
  completed_at: string;
}

export interface ModelEnsembleCanonicalHead {
  schema_version: "analysis-snapshot-v2";
  watch: ModelEnsembleWatch;
  head_run_id: string | null;
  head_generation: number | null;
  latest_attempt: ModelEnsembleAttempt | null;
  stages: ModelEnsembleAttemptStage[];
  content_persisted: false;
}

export interface ModelEnsembleAttemptSnapshot {
  attempt: ModelEnsembleAttempt;
  stages: ModelEnsembleAttemptStage[];
}

export interface SessionMetric {
  key: string;
  version: number;
  dimension: string;
  display_name: string;
  numeric_value: number | null;
  text_value: string | null;
  unit: string | null;
  source: string;
  observed_count: number;
  eligible_count: number;
  coverage: number;
  confidence: number | null;
  metric_pack_key: string;
  metric_pack_version: number;
  metric_engine_version: string;
  redactor_version: string | null;
  model_id: string | null;
  model_revision: string | null;
  tokenizer_id: string | null;
  prompt_version: string | null;
  rubric_version: string | null;
  computed_at: string;
}

export interface SessionMetricResponse {
  session_id: string;
  metrics: SessionMetric[];
}

export type AnalysisJobKind = Schemas["AnalysisJobKind"];
export type AnalysisJobState = Schemas["AnalysisJobState"];

export interface AnalysisJobIdentity extends Omit<
  Schemas["AnalysisJobIdentity"],
  "automation_grant_id" | "local_only"
> {
  automation_grant_id: string | null;
  local_only: true;
}

/**
 * Validated browser-safe projection. The generated public DTO never includes
 * an internal dedupe key or worker lease credentials.
 */
export interface AnalysisJobRecord extends Omit<
  Schemas["AnalysisJobResponse"],
  "identity"
> {
  identity: AnalysisJobIdentity;
}

export interface AnalysisJobPage extends Omit<
  Schemas["AnalysisJobPageResponse"],
  "jobs"
> {
  jobs: AnalysisJobRecord[];
}

export type AutomationGrantState = Schemas["AutomationGrantState"];
export type AutomationRoute = Schemas["AutomationRoute"];
export type AutomationResourcePolicy = Schemas["AutomationResourcePolicy"];
export interface ReviewedAutomationResourcePolicyRequest {
  route: "balanced";
  max_gpu_workers: 1;
  max_cpu_workers: 1;
  pause_on_battery: true;
  maximum_session_seconds: 1_800;
}
export interface AutomationGrantCreateRequest extends Omit<
  Schemas["AutomationGrantCreateRequest"],
  "resource_policy"
> {
  resource_policy: ReviewedAutomationResourcePolicyRequest;
}
export interface AutomationGrantScope extends Omit<
  Schemas["AutomationGrantScope"],
  "resource_policy"
> {
  resource_policy: AutomationResourcePolicy;
}
export interface AutomationGrantRecord extends Omit<
  Schemas["AutomationGrantRecord"],
  "last_checked_at" | "last_error_code" | "revoked_at" | "scope"
> {
  last_checked_at: string | null;
  last_error_code: string | null;
  revoked_at: string | null;
  scope: AutomationGrantScope;
}
export interface AutomationPollResult {
  grants_checked: number;
  grants_revoked: number;
  grants_power_paused: number;
  grants_policy_unsupported: number;
  power_external_observations: number;
  power_battery_observations: number;
  power_unknown_observations: number;
  candidates_seen: number;
  jobs_created: number;
  jobs_reused: number;
  jobs_superseded: number;
  failures: number;
  maximum_session_runtime_deadline_enforced: false;
  session_quality_result_publication_deadline_enforced: true;
  blocking_execution_preemption_enforced: false;
}

export type SessionQualityAnalysisRequest =
  Schemas["SessionTextAnalysisRequest"];
export type SessionQualityAnalysisOutcome =
  Schemas["SessionTextAnalysisCommandResponse"];
export type RedactionPreviewBinding = Schemas["RedactionPreviewBinding"];
export type SessionQualityAnalysisPreviewRequest =
  Schemas["SessionTextAnalysisPreviewRequest"];
export type SessionQualityAnalysisPreview =
  Schemas["SessionTextAnalysisPreviewResponse"];
export type SessionQualityAnalysisPreviewApprovalRequest =
  Schemas["SessionTextAnalysisPreviewApprovalRequest"];

export type SessionTextAnalysisUnavailableReason =
  | "analysis_service_unavailable"
  | "local_source_unavailable"
  | "redacted_content_consent_required"
  | "consent_status_invalid"
  | "capability_response_invalid"
  | "synthetic_preview";

/**
 * Content-free projection of the server capability response. The HTTP adapter
 * validates all privacy invariants before constructing this value.
 */
export type SessionTextAnalysisCapability =
  | {
      available: true;
      reason_code: "available";
      data_tier: "redacted_content";
      content_persistence: false;
      network_inference: false;
      /** True only when the owner enabled the on-demand session reader. */
      raw_transcripts: boolean;
    }
  | {
      available: false;
      reason_code: SessionTextAnalysisUnavailableReason;
      data_tier: null;
      content_persistence: false;
      network_inference: false;
      raw_transcripts: boolean;
    };

export type ProviderCompatibilityProvider = "codex" | "claude_code" | "synthetic";
export type ProviderCompatibilityState =
  | "exact"
  | "compatible"
  | "degraded"
  | "untested"
  | "incompatible"
  | "unavailable";
export type ProviderTextCapabilityState = "supported" | "unsupported" | "unknown";
export type ProviderCompatibilityReason =
  | "exact_match"
  | "compatible_version"
  | "degraded_extraction"
  | "not_checked"
  | "provider_unavailable"
  | "provider_version_unsupported"
  | "adapter_outdated"
  | "source_schema_unsupported"
  | "content_schema_unsupported"
  | "check_failed";
export type ProviderUpdateSupport = "supported" | "unsupported" | "unknown";
export type ProviderUpdateTarget = "prompt_enhancer" | "provider";

/** Content-free, closed projection of one provider compatibility check. */
export interface ProviderCompatibilityStatus {
  provider: ProviderCompatibilityProvider;
  capability: "session_text_analysis" | "operational_events";
  state: ProviderCompatibilityState;
  capability_state: ProviderTextCapabilityState;
  provider_family: string;
  provider_version: string | null;
  adapter_family: string;
  adapter_version: string | null;
  source_schema_family: string;
  source_schema_version: string | null;
  content_schema_family: string;
  content_schema_version: string | null;
  reason_code: ProviderCompatibilityReason;
  checked_at: string | null;
  update_support: ProviderUpdateSupport;
  update_target: ProviderUpdateTarget | null;
}

export interface CodexIngestionReport {
  provider: "codex";
  sessions_seen: number;
  sessions_selected: number;
  sessions_inserted: number;
  sessions_updated: number;
  events_seen: number;
  events_inserted: number;
  events_updated: number;
  metrics_written: number;
  truncated: boolean;
}

export interface CodexAnalysisSelection {
  project_ids: string[];
  session_ids: string[];
  max_sessions: number;
}

export interface CodexLabelEnrichmentReport {
  provider: "codex";
  requested_sessions: number;
  matched_sessions: number;
  summary_reads: number;
  project_labels_filled: number;
  session_labels_filled: number;
  labels_unavailable: number;
  sessions_not_found: number;
  truncated: boolean;
}

export interface ManualDisplayLabelResult {
  entity_kind: "project" | "session";
  entity_id: string;
  revision: number;
  changed: boolean;
}

export type DisplayLabelEntityKind = "project" | "session";

export interface UserPresenceCapability {
  contract_version: "native-user-presence-capability-v1";
  confirmation_available: boolean;
  mode: "unavailable" | "native_bridge_bound_token";
}

export interface WorkspaceFolderPickerCapability {
  contract_version: "local-workspace-folder-picker.v1";
  available: boolean;
  mode: "server_native_dialog" | "unavailable";
}

export type WorkspaceFolderPick =
  | {
      contract_version: "local-workspace-folder-picker.v1";
      status: "selected";
      path: string;
    }
  | {
      contract_version: "local-workspace-folder-picker.v1";
      status: "cancelled" | "busy" | "unavailable";
      path: null;
    };

export interface PromptEnhancerTransport {
  /** Content-free local snapshot. Reading it never performs update egress. */
  getApplicationUpdateStatus?(
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus>;
  /** Explicit UI-gesture advisory check; never downloads or installs bytes. */
  checkApplicationUpdate?(
    request: ApplicationUpdateMutationRequest,
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus>;
  /** Explicit UI-gesture staging action; does not apply or install the package. */
  stageApplicationUpdate?(
    request: ApplicationUpdateMutationRequest,
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus>;
  /** Explicit UI-gesture cancellation of an active local staging operation. */
  cancelApplicationUpdate?(
    request: ApplicationUpdateMutationRequest,
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus>;
  /** Explicit retry of a failed local update operation. */
  retryApplicationUpdate?(
    request: ApplicationUpdateMutationRequest,
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus>;
  verifyApplicationUpdate?(
    request: ApplicationUpdateMutationRequest,
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus>;
  /**
   * Whether this exact server/window composition can perform a native,
   * non-self-issuable confirmation for protected local decisions.
   */
  getUserPresenceCapability?(
    signal?: AbortSignal,
  ): Promise<UserPresenceCapability>;
  /** Whether this browser session can open the local OS folder chooser. */
  getWorkspaceFolderPickerCapability?(
    signal?: AbortSignal,
  ): Promise<WorkspaceFolderPickerCapability>;
  /** Open one user-driven OS folder chooser; this does not scan the selection. */
  chooseWorkspaceFolder?(
    signal?: AbortSignal,
  ): Promise<WorkspaceFolderPick>;
  /**
   * Read the optional, default-off loopback development control-plane status.
   * This never carries the separate credential used by privileged data routes.
   */
  getControlPlaneReadiness(signal?: AbortSignal): Promise<ControlPlaneReadiness>;
  getTextAnalysisResearch?(
    signal?: AbortSignal,
  ): Promise<TextAnalysisResearchCatalog>;
  getTextModelRuntime?(signal?: AbortSignal): Promise<ModelRuntimeInventory>;
  getTextModelCompatibility?(
    signal?: AbortSignal,
  ): Promise<ModelCompatibilityCatalog>;
  /** Content-free all-twenty release map; never reads a project or session. */
  getMetricOperabilityCatalog?(
    signal?: AbortSignal,
  ): Promise<MetricOperabilityCatalog>;
  getModelLabInventory?(signal?: AbortSignal): Promise<ModelLabInventory>;
  startTextModelEvaluation?(
    request: ModelEvaluationRequest,
    signal?: AbortSignal,
  ): Promise<ModelEvaluationJob>;
  getTextModelEvaluation?(
    jobId: string,
    signal?: AbortSignal,
  ): Promise<ModelEvaluationJob>;
  getSessionTextAnalysisCapability(
    signal?: AbortSignal,
  ): Promise<SessionTextAnalysisCapability>;
  getProviderCompatibility?(
    provider: ProviderCompatibilityProvider,
    signal?: AbortSignal,
  ): Promise<ProviderCompatibilityStatus>;
  getProviderMetricCapabilities(
    provider: Provider,
    signal?: AbortSignal,
  ): Promise<ProviderCapabilityReport>;
  getMetricCoverage(
    provider: Provider,
    signal?: AbortSignal,
  ): Promise<MetricCoverageReport>;
  getProjectMetricCoverage(
    projectId: string,
    provider: Provider,
    signal?: AbortSignal,
  ): Promise<MetricCoverageReport>;
  getSessionMetricReadiness(
    sessionId: string,
    presetId?: TextAnalysisPresetId,
    signal?: AbortSignal,
  ): Promise<SessionMetricReadinessReport>;
  checkProviderCompatibility?(
    provider: ProviderCompatibilityProvider,
    signal?: AbortSignal,
  ): Promise<ProviderCompatibilityStatus>;
  getCodexLocalSourceStatus(signal?: AbortSignal): Promise<CodexLocalSourceStatus>;
  grantCodexLocalHistoryConsent(signal?: AbortSignal): Promise<CodexLocalSourceStatus>;
  revokeCodexLocalHistoryConsent(signal?: AbortSignal): Promise<CodexLocalSourceStatus>;
  /** Owner-authorized on-demand read of one session (ADR 0011); nothing is stored. */
  getSessionTranscript(sessionId: string, signal?: AbortSignal): Promise<SessionTranscript>;
  /** Deterministic, content-free timeline of one session's indexed events. */
  getSessionTimeline(sessionId: string, signal?: AbortSignal): Promise<SessionTimeline>;
  /** Sessions and reviewed task windows of one project over calendar time. */
  getProjectTimeline(projectId: string, signal?: AbortSignal): Promise<ProjectTimeline>;
  /** Local model runtimes (ADR 0013): registry, activation on cpu/gpu/split, per-model endpoint. */
  getLocalModels(signal?: AbortSignal): Promise<LocalModelsOverview>;
  /** Path-free exact-artifact identity and live executable compatibility receipts. */
  getLocalModelCompatibility?(signal?: AbortSignal): Promise<LocalModelCompatibilityCatalog>;
  getLocalModelPlacement(alias: string, contextSize: number, signal?: AbortSignal): Promise<LocalModelPlacementAdmission>;
  addLocalModel(request: AddLocalModel, signal?: AbortSignal): Promise<LocalModelRecord>;
  activateLocalModel(alias: string, request: ActivateLocalModel, signal?: AbortSignal): Promise<LocalModelStatus>;
  deactivateLocalModel(alias: string, signal?: AbortSignal): Promise<LocalModelStatus>;
  getLocalRuntime(signal?: AbortSignal): Promise<LocalRuntimeCoordinatorStatus>;
  switchLocalRuntime(request: SwitchLocalRuntime, signal?: AbortSignal): Promise<LocalRuntimeCoordinatorStatus>;
  stopLocalRuntime(request: StopLocalRuntime, signal?: AbortSignal): Promise<LocalRuntimeCoordinatorStatus>;
  removeLocalModel(alias: string, deleteWeights: boolean, signal?: AbortSignal): Promise<void>;
  getLocalModelRemoteFiles(repoId: string, signal?: AbortSignal): Promise<RemoteRepoFiles>;
  startLocalModelDownload(request: DownloadRequest, signal?: AbortSignal): Promise<DownloadStatus>;
  pauseLocalModelDownload(downloadId: string, statusRevision: number, signal?: AbortSignal): Promise<DownloadStatus>;
  resumeLocalModelDownload(downloadId: string, statusRevision: number, signal?: AbortSignal): Promise<DownloadStatus>;
  retryLocalModelDownload(downloadId: string, statusRevision: number, signal?: AbortSignal): Promise<DownloadStatus>;
  cancelLocalModelDownload(downloadId: string, statusRevision: number, signal?: AbortSignal): Promise<DownloadStatus>;
  /** Register every GGUF found in a folder (one level deep). */
  scanLocalModelFolder(path: string, signal?: AbortSignal): Promise<ScanFolderResult>;
  /** Stream one chat completion from a running local model; `onDelta` receives fragments as they arrive. */
  streamLocalModelChat(
    alias: string,
    request: LocalModelChatRequest,
    onDelta: (delta: LocalModelChatDelta) => void,
    signal?: AbortSignal,
  ): Promise<LocalModelChatResult>;
  /** Model-judge lane: the active local model answers the calibration questions (judgments, not metrics). */
  judgeSessionWithModel(sessionId: string, signal?: AbortSignal): Promise<JudgeOutcome>;
  /** Stored judgments for one session (labels only; never metric values). */
  getModelJudgments(sessionId: string, signal?: AbortSignal): Promise<SessionJudgments>;
  /** Plain-language reading of a session's metrics by the local model (commentary, not a metric). */
  interpretSessionWithModel(sessionId: string, signal?: AbortSignal): Promise<SessionInterpretation>;
  /** Prompt check (ADR 0015): validate a prompt in context; only metrics are stored. */
  getPromptCheckConfiguration?(signal?: AbortSignal): Promise<PromptCheckConfiguration>;
  previewPrompt?(request: PromptCheckRequest, signal?: AbortSignal): Promise<PromptCheckPreview>;
  checkPrompt(request: PromptCheckRequest, signal?: AbortSignal): Promise<PromptCheckResult>;
  getPromptCheckHistory(limit: number, offset: number, signal?: AbortSignal): Promise<PromptCheckHistory>;
  getPromptCheck(checkId: string, signal?: AbortSignal): Promise<PromptCheckRecord>;
  /** Local agent workspace (ADR 0016): sessions, turns, events, approvals. */
  getAgentOrchestration(signal?: AbortSignal): Promise<AgentOrchestrationManifest>;
  /** Owner-invoked aggregate health check; no Agent content or identities. */
  getAgentHardening(signal?: AbortSignal): Promise<AgentHardeningSnapshot>;
  /** Scoped, revocable direct HTTP connections; secret material is returned only on create/rotate. */
  listAgentMcpConnections?(signal?: AbortSignal): Promise<AgentMcpConnectionList>;
  /** Exact, token-free client setup preview; read-only and never grants connection authority. */
  getAgentMcpClientSetup?(signal?: AbortSignal): Promise<AgentMcpClientSetup>;
  /** Public official-registry metadata only; this route has no install or connection authority. */
  listMcpRegistryCatalog?(
    query?: McpRegistryCatalogQuery,
    signal?: AbortSignal,
  ): Promise<McpRegistryCatalog>;
  /** Bounded public metadata review; never installs, connects, stores credentials, or starts a process. */
  getMcpRegistryServerReview?(
    query: McpRegistryServerReviewQuery,
    signal?: AbortSignal,
  ): Promise<McpRegistryServerReview>;
  /** Durable plans, vault references, and closed compatibility receipts; no package or tool authority. */
  listMcpManagedServers?(signal?: AbortSignal): Promise<McpManagedServerList>;
  getMcpManagedServer?(managementId: string, signal?: AbortSignal): Promise<McpManagedServer>;
  getMcpManagedToolSnapshot?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedToolSnapshot>;
  getMcpManagedHostStatus?(
    managementId: string,
    projectId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedHostStatus>;
  getMcpManagedHostStartPreview?(
    managementId: string,
    projectId: string,
    expectedServerRevision: number,
    expectedProjectBindingRevision: number,
    expectedToolSnapshotId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedHostStartPreview>;
  startMcpManagedHost?(
    managementId: string,
    projectId: string,
    request: StartMcpManagedHost,
    signal?: AbortSignal,
  ): Promise<McpManagedHostStatus>;
  stopMcpManagedHost?(
    managementId: string,
    projectId: string,
    request: StopMcpManagedHost,
    signal?: AbortSignal,
  ): Promise<McpManagedHostStatus>;
  getMcpManagedProjectRuntime?(
    projectId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedProjectRuntime>;
  createMcpManagedServer?(
    request: CreateMcpManagedServer,
    signal?: AbortSignal,
  ): Promise<McpManagedServerReceipt>;
  probeMcpManagedServer?(
    managementId: string,
    request: ProbeMcpManagedServer,
    signal?: AbortSignal,
  ): Promise<McpManagedProbeReceipt>;
  getMcpManagedLifecyclePreview?(
    managementId: string,
    action: "install" | "uninstall",
    signal?: AbortSignal,
  ): Promise<McpManagedLifecyclePreview>;
  getMcpManagedLocalConfigurationInspectionPreview?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalConfigurationInspectionPreview>;
  inspectMcpManagedLocalConfiguration?(
    managementId: string,
    request: InspectMcpManagedLocalConfiguration,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalConfigurationInspectionReceipt>;
  applyMcpManagedLifecycle?(
    managementId: string,
    action: "install" | "uninstall",
    request: ApplyMcpManagedLifecycle,
    signal?: AbortSignal,
  ): Promise<McpManagedLifecycleReceipt>;
  getMcpManagedLocalCleanupPreview?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalCleanupPreview>;
  getMcpManagedLocalUpdatePreview?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalUpdatePreview>;
  applyMcpManagedLocalUpdate?(
    managementId: string,
    request: ApplyMcpManagedLocalUpdate,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalUpdateReceipt>;
  getMcpManagedLocalRollbackPreview?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalRollbackPreview>;
  applyMcpManagedLocalRollback?(
    managementId: string,
    request: ApplyMcpManagedLocalRollback,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalRollbackReceipt>;
  getMcpManagedLocalRollbackCleanupPreview?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalRollbackCleanupPreview>;
  cleanupMcpManagedLocalRollback?(
    managementId: string,
    request: ApplyMcpManagedLocalRollbackCleanup,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalRollbackCleanupReceipt>;
  getMcpManagedLocalOperationRecoveryPreview?(
    managementId: string,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalOperationRecoveryPreview>;
  recoverMcpManagedLocalOperation?(
    managementId: string,
    request: ApplyMcpManagedLocalOperationRecovery,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalOperationRecoveryReceipt>;
  completeMcpManagedLocalCleanup?(
    managementId: string,
    request: ApplyMcpManagedLocalCleanup,
    signal?: AbortSignal,
  ): Promise<McpManagedLocalCleanupReceipt>;
  setMcpManagedProjectBinding?(
    managementId: string,
    projectId: string,
    request: SetMcpManagedProjectBinding,
    signal?: AbortSignal,
  ): Promise<McpManagedServerReceipt>;
  storeMcpManagedSecret?(
    managementId: string,
    requirementId: string,
    request: StoreMcpManagedSecret,
    signal?: AbortSignal,
  ): Promise<McpManagedServerReceipt>;
  removeMcpManagedSecret?(
    managementId: string,
    requirementId: string,
    request: RemoveMcpManagedSecret,
    signal?: AbortSignal,
  ): Promise<McpManagedServerReceipt>;
  storeMcpManagedConfiguration?(
    managementId: string,
    requirementId: string,
    request: StoreMcpManagedConfiguration,
    signal?: AbortSignal,
  ): Promise<McpManagedServerReceipt>;
  removeMcpManagedConfiguration?(
    managementId: string,
    requirementId: string,
    request: RemoveMcpManagedConfiguration,
    signal?: AbortSignal,
  ): Promise<McpManagedServerReceipt>;
  createAgentMcpConnection?(
    request: CreateAgentMcpConnection,
    signal?: AbortSignal,
  ): Promise<AgentMcpConnectionCredential>;
  rotateAgentMcpConnection?(
    connectionId: string,
    request: RotateAgentMcpConnection,
    signal?: AbortSignal,
  ): Promise<AgentMcpConnectionCredential>;
  revokeAgentMcpConnection?(
    connectionId: string,
    request: RevokeAgentMcpConnection,
    signal?: AbortSignal,
  ): Promise<AgentMcpConnection>;
  releaseAgentControllerOwnership?(
    request: ReleaseAgentControllerOwnership,
    signal?: AbortSignal,
  ): Promise<AgentControllerOwnershipReleaseReceipt>;
  /** Native-owner gate for the page-local, non-spawning acceptance guide. */
  beginAgentNativeAcceptance?(
    request: BeginAgentNativeAcceptance,
    signal?: AbortSignal,
  ): Promise<AgentNativeAcceptanceStartReceipt>;
  listAgentProjects(query?: AgentCatalogQuery, signal?: AbortSignal): Promise<AgentProjectList>;
  pageAgentProjects?(query?: AgentCatalogPageQuery, signal?: AbortSignal): Promise<AgentProjectPage>;
  createAgentProject(request: CreateAgentProject, signal?: AbortSignal): Promise<AgentProject>;
  getAgentProject(projectId: string, signal?: AbortSignal): Promise<AgentProject>;
  updateAgentProject(projectId: string, request: UpdateAgentProject, signal?: AbortSignal): Promise<AgentProject>;
  deleteAgentProject(projectId: string, request: DeleteAgentProject, signal?: AbortSignal): Promise<void>;
  listAgentCatalogSessions(query?: AgentCatalogSessionQuery, signal?: AbortSignal): Promise<AgentCatalogSessionList>;
  searchAgentSavedMessages(request: import("./agentMessageSearchContract").AgentMessageSearchRequest, signal?: AbortSignal): Promise<import("./agentMessageSearchContract").AgentMessageSearchResult>;
  pageAgentCatalogSessions?(query?: AgentCatalogSessionPageQuery, signal?: AbortSignal): Promise<AgentCatalogSessionPage>;
  getAgentCatalogSession(sessionId: string, signal?: AbortSignal): Promise<AgentCatalogSession>;
  updateAgentCatalogSession(sessionId: string, request: UpdateAgentCatalogSession, signal?: AbortSignal): Promise<AgentCatalogSession>;
  deleteAgentCatalogSession(sessionId: string, request: DeleteAgentCatalogSession, signal?: AbortSignal): Promise<void>;
  getAgentPersistedEvents(projectId: string, sessionId: string, after: number, signal?: AbortSignal): Promise<AgentEvents>;
  forkAgentSession(projectId: string, sessionId: string, request: ForkAgentSession, signal?: AbortSignal): Promise<AgentSessionForkReceipt>;
  resumeAgentSession(projectId: string, sessionId: string, request: ResumeAgentSession, signal?: AbortSignal): Promise<AgentSessionView>;
  exportAgentHistory(
    projectId: string,
    sessionId: string,
    request: AgentHistoryExportRequest,
    signal?: AbortSignal,
  ): Promise<AgentHistoryExport>;
  listAgentArtifacts(projectId: string, sessionId: string, view?: AgentArtifactListView, signal?: AbortSignal): Promise<AgentArtifactList>;
  pageAgentArtifacts?(projectId: string, sessionId: string, query?: AgentArtifactPageQuery, signal?: AbortSignal): Promise<AgentArtifactPage>;
  getAgentArtifact(projectId: string, sessionId: string, artifactId: string, signal?: AbortSignal): Promise<AgentArtifactDetail>;
  exportAgentArtifact(projectId: string, sessionId: string, artifactId: string, request: ExportAgentArtifact, signal?: AbortSignal): Promise<AgentArtifactExport>;
  updateAgentArtifact(projectId: string, sessionId: string, artifactId: string, request: UpdateAgentArtifact, signal?: AbortSignal): Promise<AgentArtifact>;
  removeAgentArtifact(projectId: string, sessionId: string, artifactId: string, request: RemoveAgentArtifact, signal?: AbortSignal): Promise<AgentArtifact>;
  previewAgentArtifactCapture(projectId: string, sessionId: string, request: PreviewAgentArtifactCapture, signal?: AbortSignal): Promise<AgentArtifactCapturePreview>;
  captureAgentArtifact(projectId: string, sessionId: string, request: CaptureAgentArtifact, signal?: AbortSignal): Promise<AgentArtifactDetail>;
  getAgentArtifactDocumentPreview(projectId: string, sessionId: string, artifactId: string, version: AgentArtifactVersion, signal?: AbortSignal): Promise<AgentDocumentPreview>;
  getAgentArtifactContent(projectId: string, sessionId: string, artifactId: string, versionId: string, download: boolean, signal?: AbortSignal): Promise<AgentArtifactContent>;
  listAgentSessions(signal?: AbortSignal): Promise<AgentSessionView[]>;
  createAgentSession(settings: AgentSettings, signal?: AbortSignal): Promise<AgentSessionView>;
  getAgentSession(sessionId: string, signal?: AbortSignal): Promise<AgentSessionView>;
  getAgentSessionContext?(sessionId: string, signal?: AbortSignal): Promise<AgentSessionContextStatus>;
  switchAgentSessionModel(sessionId: string, request: SwitchAgentSessionModel, signal?: AbortSignal): Promise<AgentSessionView>;
  revalidateAgentAuthority(sessionId: string, request: RevalidateAgentAuthority, signal?: AbortSignal): Promise<AgentSessionView>;
  deleteAgentSession(sessionId: string, signal?: AbortSignal): Promise<void>;
  listAgentAttachments(sessionId: string, signal?: AbortSignal): Promise<AgentAttachmentList>;
  stageAgentAttachment(sessionId: string, upload: AgentAttachmentUpload, signal?: AbortSignal): Promise<AgentAttachment>;
  deleteAgentAttachment(sessionId: string, attachmentId: string, signal?: AbortSignal): Promise<void>;
  getAgentAttachmentContent(sessionId: string, attachmentId: string, signal?: AbortSignal): Promise<AgentAttachmentContent>;
  getAgentAttachmentDocumentPreview(sessionId: string, attachmentId: string, signal?: AbortSignal): Promise<AgentAttachmentDocumentPreview>;
  sendAgentMessage(sessionId: string, text: string, attachmentIds?: readonly string[], signal?: AbortSignal): Promise<AgentSessionView>;
  getAgentChangeSet(sessionId: string, signal?: AbortSignal): Promise<AgentChangeSet>;
  getAgentChangeDiff(sessionId: string, path: string, signal?: AbortSignal): Promise<AgentChangeDiff>;
  previewAgentChangeRestore(sessionId: string, request: AgentChangeRestorePreviewCommand, signal?: AbortSignal): Promise<AgentChangeRestorePreview>;
  applyAgentChangeRestore(sessionId: string, previewId: string, request: AgentChangeRestoreApplyCommand, signal?: AbortSignal): Promise<AgentChangeRestoreApplyResult>;
  getAgentEvents(sessionId: string, after: number, signal?: AbortSignal): Promise<AgentEvents>;
  streamAgentEvents(sessionId: string, after: number, onPage: (page: AgentEvents) => void, signal?: AbortSignal): Promise<void>;
  decideAgentApproval(sessionId: string, approvalId: string, approved: boolean, signal?: AbortSignal): Promise<AgentSessionView>;
  stopAgentSession(sessionId: string, signal?: AbortSignal): Promise<AgentSessionView>;
  getAgentWorkspaceDiscovery(sessionId: string, signal?: AbortSignal): Promise<AgentWorkspaceDiscovery>;
  getAgentWorkspaceTree(sessionId: string, path: string, signal?: AbortSignal): Promise<AgentWorkspaceTree>;
  getAgentWorkspaceSearch(sessionId: string, request: AgentWorkspaceSearchRequest, signal?: AbortSignal): Promise<AgentWorkspaceSearchResult>;
  getAgentWorkspaceFile(sessionId: string, path: string, signal?: AbortSignal): Promise<AgentWorkspaceFile>;
  previewAgentWorkspaceEdit(sessionId: string, request: AgentWorkspacePreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceEditPreview>;
  applyAgentWorkspaceEdit(sessionId: string, previewId: string, request: AgentWorkspaceApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceApplyResult>;
  previewAgentWorkspaceCreate(sessionId: string, request: AgentWorkspaceCreatePreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceCreatePreview>;
  applyAgentWorkspaceCreate(sessionId: string, preview: AgentWorkspaceCreatePreview, request: AgentWorkspaceCreateApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceCreateApplyResult>;
  previewAgentWorkspaceDirectoryCreate(sessionId: string, request: AgentWorkspaceDirectoryCreatePreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceDirectoryCreatePreview>;
  applyAgentWorkspaceDirectoryCreate(sessionId: string, preview: AgentWorkspaceDirectoryCreatePreview, request: AgentWorkspaceDirectoryCreateApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceDirectoryCreateApplyResult>;
  previewAgentWorkspaceDirectoryMove(sessionId: string, request: AgentWorkspaceDirectoryMovePreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceDirectoryMovePreview>;
  applyAgentWorkspaceDirectoryMove(sessionId: string, preview: AgentWorkspaceDirectoryMovePreview, request: AgentWorkspaceDirectoryMoveApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceDirectoryMoveApplyResult>;
  previewAgentWorkspaceFileTrash(sessionId: string, request: AgentWorkspaceFileTrashPreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceFileTrashPreview>;
  applyAgentWorkspaceFileTrash(sessionId: string, preview: AgentWorkspaceFileTrashPreview, request: AgentWorkspaceFileTrashApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceFileTrashApplyResult>;
  previewAgentWorkspaceMove(sessionId: string, request: AgentWorkspaceMovePreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceMovePreview>;
  applyAgentWorkspaceMove(sessionId: string, preview: AgentWorkspaceMovePreview, request: AgentWorkspaceMoveApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceMoveApplyResult>;
  previewAgentWorkspaceTransaction(sessionId: string, request: AgentWorkspaceTransactionPreviewCommand, signal?: AbortSignal): Promise<AgentWorkspaceTransactionPreview>;
  applyAgentWorkspaceTransaction(sessionId: string, preview: AgentWorkspaceTransactionPreview, request: AgentWorkspaceTransactionApplyCommand, signal?: AbortSignal): Promise<AgentWorkspaceTransactionApplyResult>;
  startModelJudgeSweep(signal?: AbortSignal, scope?: "sample" | "all"): Promise<JudgeSweepStatus>;
  getModelJudgeSweep(signal?: AbortSignal): Promise<JudgeSweepStatus>;
  getModelJudgeAgreement(signal?: AbortSignal): Promise<JudgeAgreementReport>;
  /** Annotation paths (ADR 0017): agent allowance switch, metaprompt, and the explicit "annotate remotely" action. */
  getAnnotationAllowance(signal?: AbortSignal): Promise<AnnotationAllowance>;
  setAnnotationAllowance(agentAllowed: boolean, signal?: AbortSignal): Promise<AnnotationAllowance>;
  getAnnotationMetaprompt(signal?: AbortSignal): Promise<AnnotationMetaprompt>;
  getRemoteAnnotationDisclosure(signal?: AbortSignal): Promise<RemoteAnnotationDisclosure>;
  annotateRemotely(limit: number, signal?: AbortSignal): Promise<RemoteAnnotationResult>;
  /** Shared team folders (ADR 0018): share, revoke, join a peer's folder, pull/push. */
  shareFolder(path: string, name: string, signal?: AbortSignal): Promise<SharedFolder>;
  listSharedFolders(signal?: AbortSignal): Promise<SharedFolderList>;
  revokeSharedFolder(shareId: string, signal?: AbortSignal): Promise<void>;
  joinSharedFolder(url: string, shareId: string, shareToken: string, target: string, signal?: AbortSignal): Promise<PeerLink>;
  listPeerLinks(signal?: AbortSignal): Promise<PeerLinkList>;
  leavePeerLink(linkId: string, signal?: AbortSignal): Promise<void>;
  pullPeerLink(linkId: string, signal?: AbortSignal): Promise<FolderSyncReport>;
  pushPeerLink(linkId: string, peerName: string, signal?: AbortSignal): Promise<FolderSyncReport>;
  getOnboardingStatus(signal?: AbortSignal): Promise<OnboardingStatus>;
  acceptOnboarding(request: OnboardingAccept, signal?: AbortSignal): Promise<OnboardingResult>;
  /** Blind calibration ratings over a frozen sample of the owner's own sessions. */
  getCalibrationSample(raterLabel: string | null, signal?: AbortSignal): Promise<CalibrationSample>;
  reviewCalibrationCase(sessionId: string, windowCharacters: 6000 | 15000, signal?: AbortSignal): Promise<CalibrationReview>;
  submitCalibrationRatings(request: RatingSubmission, signal?: AbortSignal): Promise<CalibrationProgress>;
  getCalibrationRatings(raterLabel: string, signal?: AbortSignal): Promise<CalibrationRating[]>;
  getCalibrationProgress(signal?: AbortSignal): Promise<CalibrationProgress>;
  getCalibrationExport(signal?: AbortSignal): Promise<CalibrationExport>;
  getClaudeLocalSourceStatus(signal?: AbortSignal): Promise<ClaudeCodeLocalSourceStatus>;
  grantClaudeLocalHistoryConsent(signal?: AbortSignal): Promise<ClaudeCodeLocalSourceStatus>;
  revokeClaudeLocalHistoryConsent(signal?: AbortSignal): Promise<ClaudeCodeLocalSourceStatus>;
  indexClaudeLocalSessions(
    maxSessions: number,
    signal?: AbortSignal,
  ): Promise<IngestionReport>;
  indexCodexLocalSessions(
    maxSessions: number,
    signal?: AbortSignal,
  ): Promise<CodexIngestionReport>;
  analyzeCodexLocalSessions(
    selection: CodexAnalysisSelection,
    signal?: AbortSignal,
  ): Promise<CodexIngestionReport>;
  enrichCodexDisplayLabels(
    selection: CodexAnalysisSelection,
    signal?: AbortSignal,
  ): Promise<CodexLabelEnrichmentReport>;
  setManualDisplayLabel(
    entityKind: DisplayLabelEntityKind,
    entityId: string,
    value: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<ManualDisplayLabelResult>;
  clearManualDisplayLabel(
    entityKind: DisplayLabelEntityKind,
    entityId: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<ManualDisplayLabelResult>;
  listCodexSessions(
    limit?: number,
    offset?: number,
    signal?: AbortSignal,
  ): Promise<CodexSessionListResponse>;
  listProjectSessions(
    projectId: string,
    limit?: number,
    offset?: number,
    signal?: AbortSignal,
  ): Promise<ProjectSessionListResponse>;
  getSessionMetrics(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<SessionMetricResponse>;
  listAnalysisJobs(
    state?: AnalysisJobState | null,
    limit?: number,
    offset?: number,
    signal?: AbortSignal,
  ): Promise<AnalysisJobPage>;
  getAnalysisJob(
    jobId: string,
    signal?: AbortSignal,
  ): Promise<AnalysisJobRecord>;
  getLatestSessionAnalysisJob(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<AnalysisJobRecord>;
  cancelAnalysisJob(
    jobId: string,
    signal?: AbortSignal,
  ): Promise<AnalysisJobRecord>;
  listAutomationGrants(
    provider: Provider,
    activeOnly?: boolean,
    signal?: AbortSignal,
  ): Promise<AutomationGrantRecord[]>;
  getAutomationGrant(
    grantId: string,
    expectedScope: AutomationGrantScope,
    signal?: AbortSignal,
  ): Promise<AutomationGrantRecord>;
  createAutomationGrant(
    request: AutomationGrantCreateRequest,
    signal?: AbortSignal,
  ): Promise<AutomationGrantRecord>;
  renewAutomationGrant(
    grantId: string,
    expectedScope: AutomationGrantScope,
    signal?: AbortSignal,
  ): Promise<AutomationGrantRecord>;
  revokeAutomationGrant(
    grantId: string,
    expectedScope: AutomationGrantScope,
    signal?: AbortSignal,
  ): Promise<AutomationGrantRecord>;
  pollAutomationGrants(signal?: AbortSignal): Promise<AutomationPollResult>;
  getLatestSessionQualityAnalysis(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<SessionAnalysisRunResponse>;
  getSessionQualityAnalysisRun(
    runId: string,
    signal?: AbortSignal,
  ): Promise<SessionAnalysisRunResponse>;
  getSessionCoachingSummary?(
    runId: string,
    signal?: AbortSignal,
  ): Promise<SessionCoachingProjection>;
  startSessionQualityAnalysis(
    sessionId: string,
    request: SessionQualityAnalysisRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionQualityAnalysisOutcome>;
  prepareSessionQualityAnalysisPreview(
    sessionId: string,
    request: SessionQualityAnalysisPreviewRequest,
    signal?: AbortSignal,
  ): Promise<SessionQualityAnalysisPreview>;
  approveSessionQualityAnalysisPreview(
    previewId: string,
    request: SessionQualityAnalysisPreviewApprovalRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionQualityAnalysisOutcome>;
  aggregateSessionQuality(
    request: SessionQualityAggregateRequest,
    signal?: AbortSignal,
  ): Promise<SessionQualityAggregate>;
  aggregateProjectQuality(
    request: ProjectQualityAggregateRequest,
    signal?: AbortSignal,
  ): Promise<ProjectQualityAggregate>;
  getLatestModelLinkExperiment(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<ModelLinkExperiment>;
  startModelLinkExperiment(
    sessionId: string,
    request: ModelLinkExperimentRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ModelLinkExperimentOutcome>;
  annotateModelLink(
    runId: string,
    linkId: string,
    request: ModelLinkAnnotationRequest,
    signal?: AbortSignal,
  ): Promise<ModelLinkAnnotation>;
  getLatestModelEnsemble(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleRun>;
  /** Reviewed, content-free denominators for future r5 metric publications. */
  getDeclaredTaskProfile?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<DeclaredTaskProfileCurrent>;
  saveDeclaredTaskProfile?(
    sessionId: string,
    request: DeclaredTaskProfileCommand,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<DeclaredTaskProfileOutcome>;
  startModelEnsemble(
    sessionId: string,
    request: ModelEnsembleRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleOutcome>;
  getActiveModelEnsembleWatch?(
    signal?: AbortSignal,
  ): Promise<ModelEnsembleWatchSnapshot>;
  getActiveModelEnsembleCanonicalHead?(
    signal?: AbortSignal,
  ): Promise<ModelEnsembleCanonicalHead>;
  getSessionModelEnsembleCanonicalHead?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleCanonicalHead>;
  getModelEnsembleSnapshot?(
    runId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleRun>;
  enqueueModelEnsembleAnalysis?(
    watchId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleCanonicalHead>;
  cancelModelEnsembleAnalysis?(
    watchId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleCanonicalHead>;
  getModelEnsembleAttempt?(
    attemptId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleAttemptSnapshot>;
  enableModelEnsembleWatch?(
    sessionId: string,
    request: ModelEnsembleWatchRequest,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleWatchSnapshot>;
  disableModelEnsembleWatch?(
    watchId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleWatchSnapshot>;
  refreshModelEnsembleWatch?(
    watchId: string,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleWatchSnapshot>;
  getModelEnsembleTrajectory?(
    watchId: string,
    limit?: number,
    beforeGeneration?: number,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleTrajectoryPage>;
  getModelPredictiveMetricDetail?(
    runId: string,
    metricKey: string,
    signal?: AbortSignal,
  ): Promise<ModelPredictiveMetricDetail>;
  previewAgentMetricEvidence?(
    sessionId: string,
    payload: ArrayBuffer,
    signal?: AbortSignal,
  ): Promise<AgentMetricEvidencePreview>;
  importAgentMetricEvidence?(
    sessionId: string,
    payload: ArrayBuffer,
    expectedPayloadSha256: string,
    confirmation: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AgentMetricEvidenceImport>;
  listMetricLifecycleProposals?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<MetricLifecycleProposalCollection>;
  decideMetricLifecycleProposal?(
    sessionId: string,
    proposalId: string,
    request: MetricLifecycleDecisionRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<MetricLifecycleProposalOutcome>;
  /** Content-free, native-reviewed requirement-to-plan denominator for r6. */
  getRequirementPlanEvidenceContract?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<RequirementPlanEvidenceContract>;
  previewRequirementPlanEvidence?(
    sessionId: string,
    payload: ArrayBuffer,
    signal?: AbortSignal,
  ): Promise<RequirementPlanEvidencePreview>;
  importRequirementPlanEvidence?(
    sessionId: string,
    payload: ArrayBuffer,
    preview: RequirementPlanEvidencePreview,
    confirmation: RequirementPlanEvidenceContract["import_confirmation"],
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<RequirementPlanImport>;
  listRequirementPlanProposals?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<RequirementPlanProposalCollection>;
  reviewRequirementPlanProposal?(
    sessionId: string,
    proposal: RequirementPlanProposal,
    contract: RequirementPlanEvidenceContract,
    request: RequirementPlanReviewRequest,
    signal?: AbortSignal,
  ): Promise<RequirementPlanProposalReview>;
  decideRequirementPlanProposal?(
    sessionId: string,
    proposalId: string,
    request: RequirementPlanDecisionRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<RequirementPlanProposalOutcome>;
  /** Content-free, native-reviewed requirement-to-action authority for r7/r8. */
  getRequirementActionEvidenceContract?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<RequirementActionEvidenceContract>;
  previewRequirementActionEvidence?(
    sessionId: string,
    payload: ArrayBuffer,
    signal?: AbortSignal,
  ): Promise<RequirementActionEvidencePreview>;
  importRequirementActionEvidence?(
    sessionId: string,
    payload: ArrayBuffer,
    preview: RequirementActionEvidencePreview,
    confirmation: RequirementActionEvidenceContract["import_confirmation"],
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<RequirementActionImport>;
  listRequirementActionProposals?(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<RequirementActionProposalCollection>;
  reviewRequirementActionProposal?(
    sessionId: string,
    proposal: RequirementActionProposal,
    contract: RequirementActionEvidenceContract,
    request: RequirementActionReviewRequest,
    signal?: AbortSignal,
  ): Promise<RequirementActionProposalReview>;
  decideRequirementActionProposal?(
    sessionId: string,
    proposalId: string,
    request: RequirementActionDecisionRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<RequirementActionProposalOutcome>;
  listCandidates(
    status?: CandidateStatusFilter,
    signal?: AbortSignal,
    page?: ContentFreeListPage,
  ): Promise<CandidateListResponse>;
  listTaskRevisions(
    taskId?: string,
    signal?: AbortSignal,
    page?: ContentFreeListPage,
  ): Promise<TaskRevisionListResponse>;
  getCandidateDecisions(
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<CandidateDecisionsResponse>;
  getTaskRevision(
    taskId: string,
    revision: number,
    signal?: AbortSignal,
  ): Promise<TaskRevisionResponse>;
  listTaskLifecycles(
    signal?: AbortSignal,
    page?: ContentFreeListPage,
    eventLimit?: number,
  ): Promise<TaskLifecycleListResponse>;
  getTaskLifecycle(
    taskId: string,
    revision: number,
    eventLimit?: number,
    eventOffset?: number,
    signal?: AbortSignal,
  ): Promise<TaskLifecycleSnapshot>;
  transitionTaskLifecycle(
    taskId: string,
    revision: number,
    expectedHeadEventId: string | null,
    state: TaskLifecycleState,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<TaskLifecycleMutationResponse>;
  correctTaskLifecycle(
    taskId: string,
    revision: number,
    expectedHeadEventId: string,
    expectedPriorState: TaskLifecycleState | null,
    expectedResultingState: TaskLifecycleState | null,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<TaskLifecycleMutationResponse>;
  listAnalysisRuns(
    taskId?: string,
    signal?: AbortSignal,
    page?: ContentFreeListPage,
  ): Promise<AnalysisRunListResponse>;
  getAnalysisRun(runId: string, signal?: AbortSignal): Promise<AnalysisRunResponse>;
  review(
    command: ReviewCommand,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<TaskReviewResponse>;
  startAnalysis(
    taskId: string,
    revision: number,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<TaskAnalysisResponse>;
}
