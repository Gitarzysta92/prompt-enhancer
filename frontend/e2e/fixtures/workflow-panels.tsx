import { useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AgentPage } from "../../src/features/agent/AgentPage";
import { AgentArtifactsPanel } from "../../src/features/agent/AgentArtifactsPanel";
import { exampleAgentTurn, exampleWriteReceipt } from "../../src/features/agent/agentTurnFixtures.test-support";
import { AgentWorkspacePane } from "../../src/features/agent/AgentWorkspacePane";
import { LiveMiniWindow } from "../../src/features/live-window/LiveMiniWindow";
import { TeamFoldersPanel } from "../../src/features/agent/TeamFoldersPanel";
import { LocalModelsPage } from "../../src/features/local-models/LocalModelsPage";
import { PromptCheckPage } from "../../src/features/prompt-check/PromptCheckPage";
import { ModelJudgePane } from "../../src/features/model-judge/ModelJudgePane";
import { SessionTimelinePane } from "../../src/features/session-timeline/SessionTimelinePane";
import { CalibrationCasePane } from "../../src/features/calibration/CalibrationCasePane";
import { exampleCalibrationReview } from "../../src/features/calibration/calibrationFixtures.test-support";
import { ModelJobStatusFixture } from "./model-job-status";
import { SessionRadarCard } from "../../src/features/session-radar/SessionRadarCard";
import { ModelEnsembleOverlay } from "../../src/features/model-ensemble/ModelEnsembleOverlay";
import { checkpointHead, checkpointRun, checkpointTrajectory, CHECKPOINT_SESSION_A } from "../../src/features/model-ensemble/modelEnsembleCheckpointTour.test-fixtures";
import "../../src/features/calibration/CalibrationPage.css";
import type {
  AgentArtifact, AgentArtifactCapturePreview, AgentArtifactDetail, AgentArtifactExport, AgentArtifactPage, AgentArtifactPageQuery, AgentAttachment, AgentCatalogPageQuery, AgentCatalogSession, AgentCatalogSessionPage, AgentCatalogSessionPageQuery, AgentEvent, AgentHardeningSnapshot, AgentHistoryExport, AgentMcpClientSetup, AgentMcpConnectionList, AgentMessageAttachment, AgentProject, AgentProjectPage, AgentSessionContextStatus, AgentSessionForkReceipt, AgentSessionView, AgentWorkspaceFile, LocalModelCompatibilityCatalog, LocalModelPlacementAdmission, LocalModelStatus, LocalModelsOverview, LocalRuntimeCoordinatorStatus, McpRegistryCatalog, McpRegistryServerReview, SessionTimeline,
  PeerLink, PromptCheckRecord, PromptCheckResult, PromptEnhancerTransport, SessionJudgments, SharedFolder, CalibrationReview,
} from "../../src/shared/api/contracts";
import { TransportError } from "../../src/shared/api/httpTransport";
import { createSyntheticTransport } from "../../src/shared/api/syntheticTransport";
import { exampleAgentOrchestrationManifest } from "../../src/shared/api/agentOrchestrationFixtures.test-support";
import { SYNTHETIC_QUALITY_PROJECT_ID, SYNTHETIC_QUALITY_SESSION_ID } from "../../src/shared/api/syntheticFixtures";
import { syntheticMcpManagedProjectRuntime } from "../../src/shared/api/mcpManagedRuntime.test-support";
import { syntheticMcpManagedProbeReceipt, syntheticMcpManagedServer, syntheticMcpManagedServerList, syntheticMcpManagedToolSnapshot } from "../../src/shared/api/mcpManagedServer.test-support";
import { syntheticMcpRegistryServerReview } from "../../src/shared/api/mcpRegistryServerReview.test-support";
import { bootstrapTheme } from "../../src/shared/platform/theme";
import "../../src/styles.css";
import "../../src/app/theme.css";
import "../../src/app/palette.generated.css";

// Dev-only entry, excluded from the production build. Every transport operation
// below is in memory: no HTTP, native bridge, files, provider sessions or GPU.
const parameters = new URLSearchParams(window.location.search);
const panel = parameters.get("panel") ?? "models";
const closingFixture = panel === "agent-closing";
const modelRaceFixture = panel === "agent-model-race";
const modelCompletionFixture = panel === "models-completion";
const agentCompletionFixture = panel === "agent-completion";
const agentTurnFixture = panel === "agent-turn";
const agentShellFixture = panel === "agent-shell";
const agentMcpStoreFixture = panel === "agent-mcp-store";
const agentMcpStoreHostileFixture = agentMcpStoreFixture && parameters.get("state") === "hostile";
const agentMcpStoreScaleFixture = agentMcpStoreFixture && parameters.get("state") === "scale";
const agentMcpProjectToolsFixture = panel === "agent-mcp-project-tools";
const agentMcpCallFixture = panel === "agent-mcp-call";
const agentMcpCallCompletedFixture = agentMcpCallFixture && parameters.get("state") === "completed";
const agentControllerOwnershipFixture = panel === "agent-controller-ownership";
const multimodalFixture = agentShellFixture && parameters.get("multimodal") === "1";
const agentHistoryFixture = panel === "agent-history";
const agentStressFixture = panel === "agent-stress";
const artifactViewerFixture = panel === "artifact-viewers";
const artifactCaptureWorkflowFixture = panel === "artifact-capture";
const artifactLifecycleFixture = panel === "artifact-lifecycle";
const agentCatalogFixture = agentShellFixture || agentMcpStoreFixture || agentMcpProjectToolsFixture || agentHistoryFixture || agentStressFixture || agentControllerOwnershipFixture;
const agentWorkspaceFixture = agentTurnFixture || agentShellFixture;
const agentStoppingFixture = panel === "agent-stopping";
const agentCommandFixture = panel === "agent-command-cleanup";
const editorWriteFailure = panel === "editor-write-rolled-back"
  ? { reason: "workspace_write_failed" as const, status: 503 }
  : panel === "editor-write-cleanup"
    ? { reason: "workspace_cleanup_failed" as const, status: 503 }
    : panel === "editor-write-unverified"
      ? { reason: "workspace_verification_failed" as const, status: 409 }
      : null;
const agentWindow = parameters.get("window") === "1";
const at = "2040-01-01T00:00:00Z";
const sessionId = "a".repeat(32);
const agentProjectId = "1".repeat(32);
const secondAgentProjectId = "2".repeat(32);
const forkedAgentSessionId = "5".repeat(32);
const retainedArtifactId = "3".repeat(32);
const retainedArtifactVersionId = "4".repeat(32);
const retainedArtifactPriorVersionId = "7".repeat(32);
const checkId = "b".repeat(64);
const modelAlias = "example-small-cpu";
const alternateModelAlias = "example-medium-split";
const retainedArtifactText = "# Reviewed synthetic artifact\n\nNo real workspace content.\n";
const retainedArtifactBytes = new TextEncoder().encode(retainedArtifactText).byteLength;
const mcpStoreBaseReview = syntheticMcpRegistryServerReview() as McpRegistryServerReview;
const mcpStoreCatalog: McpRegistryCatalog = {
  contract_version: "mcp-registry-catalog.v1",
  source: {
    registry: "official_mcp_registry",
    base_url: "https://registry.modelcontextprotocol.io",
    fetched_at: at,
    delivery: "live",
    cache_age_seconds: 0,
  },
  search: "",
  servers: [
    {
      ...mcpStoreBaseReview.server,
      catalog_id: "1".repeat(32),
      presentation_revision: "1".repeat(64),
      title: "Synthetic MCP Files",
      description: "Fictional files integration with a locally reviewable package setup.",
      updated_at: "2040-01-01T00:00:00Z",
      icon: {
        path: `/v1/integrations/mcp-store/icons/${"1".repeat(32)}`,
        mime_type: "image/png",
      },
    },
    ...["Browser", "Database", "Design"].map((label, index) => ({
      catalog_id: String(index + 2).repeat(32),
      presentation_revision: String(index + 2).repeat(64),
      name: `com.example/synthetic-${label.toLocaleLowerCase()}`,
      title: `Synthetic MCP ${label}`,
      description: `Fictional ${label.toLocaleLowerCase()} integration for responsive Store acceptance.`,
      publisher: "com.example",
      version: "1.0.0",
      status: "active" as const,
      updated_at: `2040-01-0${index + 2}T00:00:00Z`,
      repository_url: null,
      website_url: null,
      icon: null,
      packages: [],
      remotes: [{
        transport: "streamable-http" as const,
        endpoint_host: `${label.toLocaleLowerCase()}.example.com`,
        endpoint_state: "fixed_host" as const,
        secure: true,
      }],
      supports_local: false,
      supports_remote: true,
      management_state: "not_managed" as const,
      install_action: "unavailable" as const,
      install_reason: "guarded_install_host_not_implemented" as const,
    })),
  ],
  next_cursor: null,
  partial: false,
  management_truth: "registry_only_no_install_authority",
};
const mcpStoreHostileCatalog: McpRegistryCatalog = {
  ...mcpStoreCatalog,
  servers: [{
    ...mcpStoreCatalog.servers[0],
    title: "<img src=x onerror=synthetic>",
    description: "<script>synthetic()</script>",
    icon: null,
  }],
  next_cursor: "hostile-cursor",
};
const mcpStoreScaleCatalog: McpRegistryCatalog = {
  ...mcpStoreCatalog,
  servers: Array.from({ length: 120 }, (_, index) => ({
    ...mcpStoreCatalog.servers[0],
    catalog_id: index.toString(16).padStart(32, "0"),
    presentation_revision: index.toString(16).padStart(64, "0"),
    name: `com.example/synthetic-scale-${index.toString().padStart(3, "0")}`,
    title: `Synthetic scale server ${index.toString().padStart(3, "0")}`,
    description: `Fictional bounded-rendering MCP server ${index}.`,
    icon: null,
    repository_url: null,
    updated_at: new Date(Date.parse(at) + index * 1_000).toISOString(),
  })),
};
const mcpStoreReview: McpRegistryServerReview = {
  ...mcpStoreBaseReview,
  source: mcpStoreCatalog.source,
  server: mcpStoreCatalog.servers[0],
  provenance: {
    ...mcpStoreBaseReview.provenance,
    publisher_namespace: mcpStoreCatalog.servers[0].publisher,
  },
  versions: [{
    ...mcpStoreBaseReview.versions[0],
    version: mcpStoreCatalog.servers[0].version,
    updated_at: mcpStoreCatalog.servers[0].updated_at,
  }],
};
const mcpStoreManaged = syntheticMcpManagedServer({
  catalog_id: mcpStoreCatalog.servers[0].catalog_id,
  server_name: mcpStoreCatalog.servers[0].name,
  server_title: mcpStoreCatalog.servers[0].title,
  server_version: mcpStoreCatalog.servers[0].version,
  option_id: mcpStoreReview.options[0].option_id,
  plan_revision: mcpStoreReview.plan_revision,
});
const mcpProjectToolsSnapshot = syntheticMcpManagedToolSnapshot();
const mcpProjectToolsBase = syntheticMcpManagedProbeReceipt().server;
const mcpProjectToolsManaged = syntheticMcpManagedServer({
  ...mcpProjectToolsBase,
  lifecycle_state: "installed",
  installation_state: "installed",
  installation_kind: "remote_activation",
  installed_plan_revision: mcpProjectToolsBase.plan_revision,
  installed_at: at,
  install_action: "not_applicable_already_installed",
  uninstall_action: "available_native_confirmation_required",
  tool_snapshot: mcpProjectToolsSnapshot,
  tool_review_state: "reviewable",
  project_bindings: [{
    project_id: agentProjectId,
    project_name: "Example coding project",
    enabled: true,
    required_permissions: mcpProjectToolsBase.required_permissions,
    granted_permissions: mcpProjectToolsBase.required_permissions,
    admitted_tool_ids: [mcpProjectToolsSnapshot.tools[0].tool_id],
    tool_snapshot_id: mcpProjectToolsSnapshot.snapshot_id,
    admission_state: "admitted",
    effective_state: "inactive_host_unavailable",
    created_at: at,
    updated_at: at,
    revision: 2,
  }],
});
const hardeningSnapshot: AgentHardeningSnapshot = {
  contract_version: "agent-hardening.v1",
  generated_on_demand: true,
  contains_content: false,
  recovery_state: "attention_required",
  recovery_actions: [
    "resume_interrupted_read_only",
    "revalidate_recovered_authority",
  ],
  catalog: {
    state: "ready",
    reason_code: null,
    schema_version: 30,
    quick_check_passed: true,
    foreign_key_violations_observed: 0,
    foreign_key_scan_truncated: false,
    projection_violations: 0,
    counts: {
      projects: 2,
      archived_projects: 0,
      sessions: 5,
      archived_sessions: 1,
      metadata_only_sessions: 2,
      retained_sessions: 3,
      history_events: 18,
      interrupted_retained_sessions: 1,
      artifacts: 2,
      artifact_versions: 3,
      staged_attachments: 0,
      attached_attachments: 1,
    },
  },
  live: {
    state: "ready",
    reason_code: null,
    counts: {
      sessions: 1,
      running_turns: 0,
      closing_sessions: 0,
      pending_approvals: 0,
      cleanup_unconfirmed: 0,
      command_cleanup_quarantined: false,
      recovered_read_only: 1,
      history_write_failures: 0,
      shutting_down: false,
    },
  },
};
const agentMcpConnections: AgentMcpConnectionList = {
  contract_version: "agent-mcp-management.v2",
  activity_epoch: "f".repeat(32),
  active_count: 1,
  connections: [{
    contract_version: "agent-mcp-connection.v4",
    connection_id: "c".repeat(32),
    label: "Synthetic Codex orchestrator",
    client_kind: "codex",
    created_at: "2040-01-01T00:00:00Z",
    updated_at: "2040-01-01T00:00:00Z",
    expires_at: "2040-04-01T00:00:00Z",
    last_used_at: "2040-01-01T00:05:00Z",
    last_tool_at: "2040-01-01T00:05:01Z",
    last_tool_name: "agent_open",
    last_tool_outcome: "succeeded",
    last_tool_source: "external_client",
    last_auth_rejected_at: null,
    revoked_at: null,
    revision: 1,
    credential_revision: 1,
    allow_model_lifecycle: false,
    scope: {
      contract_version: "agent-mcp-scope.v1",
      state: "bound",
      project_id: agentProjectId,
      project_name: "Example coding project",
      catalog_access: "project_only",
      chat_access: "project_only",
      workspace_access: "project_only",
      native_approval_inherited: false,
    },
    state: "active",
  }],
  controller_ownerships: {
    contract_version: "agent-controller-ownership-list.v1",
    ownerships: [],
    active_count: 0,
  },
  tool_activity_sequences: [{
    contract_version: "agent-mcp-tool-activity-sequence.v1",
    connection_id: "c".repeat(32),
    credential_revision: 1,
    sequence: 1,
    tool_name: "agent_open",
    tool_source: "external_client",
    started_at: "2040-01-01T00:05:01Z",
    completed_at: "2040-01-01T00:05:01Z",
    outcome: "succeeded",
  }],
};
const agentMcpOwnershipConnections: AgentMcpConnectionList = {
  contract_version: "agent-mcp-management.v2",
  activity_epoch: agentMcpConnections.activity_epoch,
  active_count: 2,
  connections: [
    agentMcpConnections.connections[0],
    {
      ...agentMcpConnections.connections[0],
      connection_id: "d".repeat(32),
      label: "Synthetic Claude recipient",
      client_kind: "claude",
      last_tool_at: null,
      last_tool_name: null,
      last_tool_outcome: null,
      last_tool_source: null,
    },
  ],
  controller_ownerships: {
    contract_version: "agent-controller-ownership-list.v1",
    active_count: 1,
    ownerships: [{
      contract_version: "agent-controller-ownership.v1",
      project_id: agentProjectId,
      project_name: "Example coding project",
      session_id: sessionId,
      session_title: "Synthetic coding chat",
      owner_connection_id: "c".repeat(32),
      owner_label: "Synthetic Codex orchestrator",
      owner_client_kind: "codex",
      operation: "turn",
      state: "waiting_native_approval",
      cursor: 7,
      last_seq: 8,
      approval_pending: true,
      ownership_started_at: "2040-01-01T00:05:00Z",
      owner_since: "2040-01-01T00:05:00Z",
      updated_at: "2040-01-01T00:06:00Z",
      revision: 4,
      handoff: {
        target_connection_id: "d".repeat(32),
        target_label: "Synthetic Claude recipient",
        target_client_kind: "claude",
        offered_at: "2040-01-01T00:06:00Z",
        expires_at: "2040-01-01T00:16:00Z",
      },
      native_approval_inherited: false,
    }],
  },
  tool_activity_sequences: [
    agentMcpConnections.tool_activity_sequences[0],
    {
      contract_version: "agent-mcp-tool-activity-sequence.v1",
      connection_id: "d".repeat(32),
      credential_revision: 1,
      sequence: 0,
      tool_name: null,
      tool_source: null,
      started_at: null,
      completed_at: null,
      outcome: null,
    },
  ],
};
const agentMcpSetupEndpoint = "http://127.0.0.1:4173/mcp/agent";
const agentMcpSetup: AgentMcpClientSetup = {
  contract_version: "agent-mcp-client-setup.v1",
  endpoint_url: agentMcpSetupEndpoint,
  bearer_token_env_var: "PROMPT_ENHANCER_AGENT_MCP_TOKEN",
  codex_toml: [
    "[mcp_servers.prompt-enhancer-agent]",
    `url = "${agentMcpSetupEndpoint}"`,
    'bearer_token_env_var = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"',
    "tool_timeout_sec = 330",
    'default_tools_approval_mode = "prompt"',
  ].join("\n"),
  claude_json: JSON.stringify({
    mcpServers: {
      "prompt-enhancer-agent": {
        type: "http",
        url: agentMcpSetupEndpoint,
        headers: { Authorization: "Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}" },
      },
    },
  }),
  codex_add_command: `codex mcp add prompt-enhancer-agent --url ${agentMcpSetupEndpoint} --bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN`,
  claude_add_command: `claude mcp add --transport http --scope local --header 'Authorization: Bearer \${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' prompt-enhancer-agent ${agentMcpSetupEndpoint}`,
  credential_included: false,
  connection_authority_granted: false,
  native_connection_required: true,
  starts_process: false,
  starts_terminal: false,
  provider_configuration_changed: false,
};
const retainedArtifact: AgentArtifact = {
  contract_version: "agent-artifact.v3",
  artifact_id: retainedArtifactId,
  project_id: agentProjectId,
  session_id: sessionId,
  title: "reviewed-example.md",
  kind: "markdown",
  path: "docs/reviewed-example.md",
  created_at: at,
  updated_at: at,
  revision: 2,
  version_count: 2,
  availability: "unchecked",
  lifecycle_state: "active",
  archived_at: null,
  removed_at: null,
  latest_version: {
    contract_version: "agent-artifact.v3",
    version_id: retainedArtifactVersionId,
    artifact_id: retainedArtifactId,
    version_number: 2,
    created_at: at,
    path: "docs/reviewed-example.md",
    media_type: "text/markdown; charset=utf-8",
    preview_kind: "text",
    provenance: "reviewed_write",
    sha256: "5".repeat(64),
    byte_size: retainedArtifactBytes,
    source_turn_id: "e".repeat(32),
    source_event_seq: 2,
  },
};
const retainedArtifactPriorVersion = {
  ...retainedArtifact.latest_version,
  version_id: retainedArtifactPriorVersionId,
  version_number: 1,
  sha256: "8".repeat(64),
  byte_size: 31,
  source_event_seq: 1,
};
const retainedArtifactDetail: AgentArtifactDetail = {
  ...retainedArtifact,
  availability: "available",
  versions: [retainedArtifactPriorVersion, retainedArtifact.latest_version],
};

function bytesFromBase64(value: string): Uint8Array {
  const decoded = atob(value);
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}

function syntheticPdf(): Uint8Array {
  const encoder = new TextEncoder();
  const content = "BT /F1 12 Tf 72 720 Td (Synthetic local artifact) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ];
  let source = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((body, index) => {
    offsets.push(encoder.encode(source).byteLength);
    source += `${index + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xrefOffset = encoder.encode(source).byteLength;
  source += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  source += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  source += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return encoder.encode(source);
}

const viewerProjectId = "8".repeat(32);
const viewerSessionId = "9".repeat(32);
const viewerImageBytes = bytesFromBase64("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=");
const viewerPdfBytes = syntheticPdf();

function viewerArtifact(
  artifactId: string,
  versionId: string,
  title: string,
  kind: "image" | "pdf" | "document",
  mediaType: "image/png" | "application/pdf" | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  byteSize: number,
): AgentArtifactDetail {
  const version = {
    contract_version: "agent-artifact.v3" as const,
    version_id: versionId,
    artifact_id: artifactId,
    version_number: 1,
    created_at: at,
    path: title,
    media_type: mediaType,
    preview_kind: kind,
    provenance: "verified_output" as const,
    sha256: artifactId[0].repeat(64),
    byte_size: byteSize,
    source_turn_id: null,
    source_event_seq: null,
  };
  return {
    contract_version: "agent-artifact.v3",
    artifact_id: artifactId,
    project_id: viewerProjectId,
    session_id: viewerSessionId,
    title,
    kind,
    path: title,
    created_at: at,
    updated_at: at,
    revision: 1,
    version_count: 1,
    availability: "available",
    lifecycle_state: "active",
    archived_at: null,
    removed_at: null,
    latest_version: version,
    versions: [version],
  };
}

const viewerImage = viewerArtifact(
  "a".repeat(32),
  "b".repeat(32),
  "synthetic-preview.png",
  "image",
  "image/png",
  viewerImageBytes.byteLength,
);
const viewerPdf = viewerArtifact(
  "c".repeat(32),
  "d".repeat(32),
  "synthetic-report.pdf",
  "pdf",
  "application/pdf",
  viewerPdfBytes.byteLength,
);
const viewerDocument = viewerArtifact(
  "e".repeat(32),
  "f".repeat(32),
  "synthetic-budget.xlsx",
  "document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  512,
);
const captureProjectId = "6".repeat(32);
const captureSessionId = "7".repeat(32);
const captureArtifact = {
  ...viewerArtifact(
    "1".repeat(32),
    "2".repeat(32),
    "reports/synthetic-generated.pdf",
    "pdf",
    "application/pdf",
    viewerPdfBytes.byteLength,
  ),
  project_id: captureProjectId,
  session_id: captureSessionId,
  title: "Synthetic generated report",
} satisfies AgentArtifactDetail;
const lifecycleArtifact: AgentArtifact = {
  ...retainedArtifact,
  contract_version: "agent-artifact.v3",
  artifact_id: "4".repeat(32),
  project_id: viewerProjectId,
  session_id: viewerSessionId,
  title: "Synthetic lifecycle note",
  path: "docs/synthetic-lifecycle.md",
  revision: 1,
  version_count: 1,
  lifecycle_state: "active",
  archived_at: null,
  removed_at: null,
  latest_version: {
    ...retainedArtifact.latest_version,
    contract_version: "agent-artifact.v3",
    artifact_id: "4".repeat(32),
    version_id: "5".repeat(32),
    version_number: 1,
    path: "docs/synthetic-lifecycle.md",
  },
};

function artifactLineageExport(
  detail: AgentArtifactDetail,
  versionId: string,
): AgentArtifactExport {
  const version = detail.versions.find((candidate) => candidate.version_id === versionId);
  if (version === undefined) return unavailable();
  return {
    contract_version: "agent-artifact-export.v1",
    exported_at: at,
    artifact: detail,
    selected_version: version,
    evidence: {
      verification: "exact_current_workspace_readback",
      algorithm: "sha256",
      sha256: version.sha256,
      byte_size: version.byte_size,
      verified: true,
    },
    content_included: false,
    absolute_path_included: false,
    sensitivity: "sensitive_local_metadata",
  };
}
function placementAdmission(alias: string, contextSize: number): LocalModelPlacementAdmission {
  return {
    contract_version: "local-model-placement.v1",
    alias,
    context_size: contextSize,
    gpu_memory_free_mb: 12000,
    actual_offload_verified: false,
    options: [
      { device: "gpu", state: "available", reason_code: "gpu_estimate_fits", recommended_gpu_layers: 8, estimated_vram_required_mb: 6000 },
      { device: "split", state: "available", reason_code: "split_estimate_available", recommended_gpu_layers: 6, estimated_vram_required_mb: 5000 },
      { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
    ],
  };
}

let model: LocalModelStatus = {
  record: {
    alias: modelAlias, display_name: "Example Small CPU", format: "gguf",
    path: "D:/example/models/example.gguf", context_size: 4096,
    default_device: "cpu", added_at: at, provenance_verified: false,
  },
  runtime: { state: panel === "agent" || closingFixture || modelRaceFixture ? "stopped" : "running", device: "cpu" },
  endpoint_path: `/v1/local-models/${modelAlias}/chat/completions`,
  placement: placementAdmission(modelAlias, 4096),
};
let runtimeAlias: string | null = modelAlias;
let runtimeDevice: "cpu" | "gpu" | "split" = "cpu";
let runtimeContextSize = 4096;
let runtimeRevision = 7;
let runtimeHasMeasuredRequest = agentShellFixture;
let sessions: AgentSessionView[] = [];
if (closingFixture || modelRaceFixture || agentCompletionFixture || agentWorkspaceFixture || agentMcpProjectToolsFixture || agentMcpCallFixture || agentStoppingFixture || agentCommandFixture) {
  sessions = [{ contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: sessionId, closing: closingFixture, stopping: false,
    settings: { workspace: "D:/example/project", project_id: agentShellFixture || agentMcpProjectToolsFixture ? agentProjectId : null, model_alias: modelAlias, parameters: {
      temperature: 0.2, top_p: 0.95, max_tokens: 1400, enable_thinking: agentCompletionFixture },
      instructions: null, allow_writes: agentWorkspaceFixture, allow_commands: agentWorkspaceFixture || agentCommandFixture, allow_web: false,
      max_steps: 10, command_timeout_seconds: 120, title: closingFixture ? "Example closing session" : agentCompletionFixture ? "Example incomplete-response session" : agentTurnFixture ? "Example turn receipts" : agentShellFixture || agentMcpProjectToolsFixture ? "Synthetic coding chat" : "Example model-control session",
      retention_policy: "metadata_only" },
    created_at: at, running: false, last_seq: 0, pending_approval_id: null, model_alias: modelAlias, turns: 1,
    history_revision: 0, recovered: false, authority_revalidated: true, history_write_failed: false, recovery_state: "current" }];
}
let closeFailures = closingFixture ? 1 : 0;
let events: AgentEvent[] = [];
let shares: SharedFolder[] = [];
let links: PeerLink[] = [];
let checks: PromptCheckRecord[] = [];
let chatRequests = 0;
let cancelledExampleReleased = false;
let commandCleanupReported = false;
let olderCommandSnapshotRead: (() => void) | null = null;
let holdNextModelRead = false;
let heldModelRead: { snapshot: LocalModelsOverview; resolve: (value: LocalModelsOverview) => void } | null = null;
let attachmentSequence = 0;
let stagedAttachments: AgentAttachment[] = [];
const documentAttachmentPreviews = new Map<string, string>();
let hardeningRequests = 0;
let acceptanceRequests = 0;
if (agentShellFixture) {
  document.documentElement.dataset.agentHardeningRequests = "0";
  document.documentElement.dataset.agentAcceptanceRequests = "0";
}

function messageAttachment(attachment: AgentAttachment): AgentMessageAttachment {
  return {
    contract_version: "agent-attachment.v2",
    attachment_id: attachment.attachment_id,
    display_name: attachment.display_name,
    kind: attachment.kind,
    media_type: attachment.media_type,
    byte_size: attachment.byte_size,
    sha256: attachment.sha256,
    width: attachment.width,
    height: attachment.height,
    duration_ms: attachment.duration_ms,
    sample_rate_hz: attachment.sample_rate_hz,
    channels: attachment.channels,
    routing: attachment.routing,
    document_format: attachment.document_format,
    projected_characters: attachment.projected_characters,
    projection_truncated: attachment.projection_truncated,
    omitted_features: attachment.omitted_features,
    context_tokens: null,
    context_cost_source: "runtime_unreported",
  };
}

function overview(): LocalModelsOverview {
  const alternate: LocalModelStatus = {
    record: {
      alias: alternateModelAlias, display_name: "Example Medium Split", format: "gguf",
      path: "D:/example/models/example-medium.gguf", context_size: 8192,
      default_device: "split", added_at: at, provenance_verified: false,
    },
    runtime: { state: runtimeAlias === alternateModelAlias ? "running" : "stopped", device: runtimeAlias === alternateModelAlias ? runtimeDevice : null },
    endpoint_path: `/v1/local-models/${alternateModelAlias}/chat/completions`,
    placement: placementAdmission(alternateModelAlias, 8192),
  };
  return {
    contract_version: "local-models.v1", runtime_available: true,
    storage_root: "D:/example/models", storage_free_bytes: 64 * 1024 ** 3,
    download_reserve_bytes: 512 * 1024 ** 2, download_ledger_error_code: null,
    models: agentShellFixture
      ? [{ ...model, runtime: { state: runtimeAlias === modelAlias ? "running" : "stopped", device: runtimeAlias === modelAlias ? runtimeDevice : null } }, alternate]
      : [model], downloads: [],
    hardware: { gpu_name: "Synthetic GPU", gpu_memory_mb: 16000, gpu_memory_free_mb: 12000,
      ram_mb: 32000, llama_server_path: "D:/example/runtime/llama-server.exe", llama_server_version: "example-v1" },
  };
}

function compatibilityCatalog(): LocalModelCompatibilityCatalog {
  const compatibility = (alias: string, running: boolean) => ({
    alias,
    state: running ? "supported" as const : "unknown" as const,
    reason_code: running ? "live_text_probe_verified" as const : "model_not_executed" as const,
    format: "gguf" as const,
    architecture: "example-transformer",
    tokenizer_model: "example-bpe",
    training_context_size: alias === modelAlias ? 4096 : 8192,
    metadata_reader_version: "gguf-metadata.v1" as const,
    artifact_identity_state: "unverified" as const,
    artifact_sha256: null,
    source_revision: null,
    source_license: null,
    source_license_policy: null,
    execution_state: running ? "verified" as const : "not_run" as const,
    context_counter_state: running && runtimeHasMeasuredRequest ? "verified" as const : "not_run" as const,
  });
  return {
    contract_version: "local-model-compatibility.v1",
    adapter: {
      adapter_id: "llama.cpp-openai-gguf",
      adapter_version: "llama.cpp-openai-gguf.v1",
      runtime_version: "example-v1",
      runtime_identity_state: "verified",
      runtime_binary_sha256: "d".repeat(64),
      capability_probe_version: "local-runtime-multimodal-probe.v2",
    },
    models: [
      compatibility(modelAlias, runtimeAlias === modelAlias),
      ...(agentShellFixture
        ? [compatibility(alternateModelAlias, runtimeAlias === alternateModelAlias)]
        : []),
    ],
  };
}

function runtimeCoordinator(): LocalRuntimeCoordinatorStatus {
  const selection = runtimeAlias === null ? null : {
    alias: runtimeAlias,
    device: runtimeDevice,
    gpu_layers: runtimeDevice === "cpu" ? 0 : -1,
    context_size: runtimeContextSize,
  };
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision: runtimeRevision,
    state: selection === null ? "idle" : "ready",
    requested: selection,
    served: selection === null ? null : { ...selection, pid: 4242, started_at: at },
    active_requests: 0,
    cleanup: {
      state: "not_required", process_exit_confirmed: true,
      gpu_memory_free_before_mb: null, gpu_memory_free_after_mb: null, gpu_memory_released_mb: null,
    },
    capabilities: {
      probe_version: "local-runtime-multimodal-probe.v2", state: selection === null ? "not_probed" : "verified",
      text: selection !== null, tools: selection !== null, structured_output: false,
      vision: selection !== null && multimodalFixture,
      audio: selection !== null && multimodalFixture,
      recording: selection !== null && multimodalFixture,
      error_code: null,
    },
    context: selection !== null && runtimeHasMeasuredRequest ? {
      state: "known", used_tokens: 612, limit_tokens: selection.context_size,
      requested_output_tokens: 1400, available_output_tokens: selection.context_size - 612,
      source: "runtime_chat_input_tokens", scope: "last_request", policy: "exact_admitted",
      compacted_messages: 0, reason_code: null,
    } : {
      state: "unknown", used_tokens: null, limit_tokens: selection?.context_size ?? null,
      requested_output_tokens: null, available_output_tokens: null,
      source: "runtime_limit_only", scope: "runtime_limit", policy: "runtime_enforced",
      compacted_messages: 0,
      reason_code: selection === null ? "runtime_not_served" : "no_request_measured",
    },
    last_error_code: null,
  };
}

const result: PromptCheckResult = {
  contract_version: "prompt-check.v1", check_id: checkId, created_at: at,
  provider: "other", agent_model: modelAlias,
  metrics: [
    { key: "prompt.task_definition_coverage", display_name: "Task definition", description: "Synthetic fixture reading",
      state: "known", value: 0.5, numerator: 1, denominator: 2, higher_is_better: true, explanation_code: "cues", cues: [] },
    { key: "prompt.acceptance_testability", display_name: "Acceptance testability", description: "Synthetic fixture reading",
      state: "unknown", value: null, numerator: null, denominator: null, higher_is_better: true,
      explanation_code: "not_observed", cues: [] },
  ],
  context: { task_type: "implement", language: "en", prompt_chars: 48, prompt_words: 8,
    sentence_count: 1, bullet_count: 0, question_count: 0, file_references: 1, code_identifiers: 0,
    urls: 0, prior_context_supplied: 0, depends_on_prior_context: false, verification_requested: false,
    missing_elements: ["a checkable pass condition"] },
  commentary: { state: "ok", model_alias: modelAlias, prompt_version: "example-v1",
    findings: [{ aspect: "verification", severity: "high", why: "No test is named.", suggestion: "Name the exact test command." }],
    reformulated_prompt: "Update example.ts and run the focused test. Report the changed files and result.",
    reformulated_elements: [{ element: "acceptance", original: null, suggested: "The focused example test passes." }],
    notes: null, caveat: "Synthetic model suggestion, not measured evidence." },
  summary: "Synthetic prompt check: verification needs a concrete pass condition.",
  engine_version: "example-v1", rubric_version: "example-v1", dashboard_path: `/prompt-checks/${checkId}`,
  other_metric_families_note: "Outcome metrics require later verification evidence.",
};

function record(): PromptCheckRecord {
  return { check_id: checkId, created_at: at, provider: "other", agent_model: modelAlias,
    language: "en", task_type: "implement", prompt_chars: 48, prior_message_count: 0,
    depends_on_prior_context: false, verification_requested: false, metrics: result.metrics,
    commentary_state: "ok", commentary_model_alias: modelAlias, prompt_fingerprint: "c".repeat(64) };
}

function event(kind: AgentEvent["kind"], extra: Partial<AgentEvent> = {}): AgentEvent {
  return { seq: events.length + 1, at, kind, text: null, tool: null, arguments: null,
    call_id: null, approval_id: null, ok: null, preview: null, attachments: [], ...extra };
}

if (agentTurnFixture) {
  const summary = exampleAgentTurn({ model_alias: modelAlias, started_at: at, finished_at: "2040-01-01T00:00:02Z",
    tools_requested: 3, tools_succeeded: 2, tools_unverified: 1, untracked_command_calls: 1,
    writes: [exampleWriteReceipt({ path: "example.ts" }), exampleWriteReceipt({ path: "pending-example.ts", state: "unverified", operation: null, after_sha256: null, added_lines: null, removed_lines: null, byte_size: null })] });
  events.push(event("user", { text: "Review the fictional example and report the observed effects.", turn_id: summary.turn_id }));
  for (const [index, write] of summary.writes.entries()) {
    events.push(event("tool_call", { turn_id: summary.turn_id, tool: "write_file", call_id: `example-write-${index}`, arguments: { path: write.path } }));
    events.push(event("tool_result", { turn_id: summary.turn_id, tool: "write_file", call_id: `example-write-${index}`, ok: write.state === "verified", tool_state: write.state === "verified" ? "succeeded" : "unverified", write_receipt: write, text: "Synthetic tool-effect fixture." }));
  }
  events.push(event("tool_call", { turn_id: summary.turn_id, tool: "run_command", call_id: "example-command", arguments: { command: "example-check" } }));
  events.push(event("tool_result", { turn_id: summary.turn_id, tool: "run_command", call_id: "example-command", ok: true, tool_state: "succeeded", text: "Synthetic command result; file effects not inventoried." }));
  events.push(event("assistant", { text: "Synthetic response: inspect the receipts below; this fixture did not modify real files.", turn_id: summary.turn_id }));
  events.push(event("done", { turn_id: summary.turn_id, turn_summary: summary }));
  sessions = [{ ...sessions[0], last_seq: events.length }];
}

if (agentShellFixture) {
  events.push(event("user", { text: "Inspect the fictional module and explain the reviewed change." }));
  events.push(event("assistant", { text: "I will inspect the synthetic file before proposing a change.", reasoning: "Synthetic reasoning fixture: identify the requested module and verify the bounded workspace state." }));
  events.push(event("tool_call", { tool: "read_file", call_id: "synthetic-read", arguments: { path: "example.ts" } }));
  events.push(event("tool_result", { tool: "read_file", call_id: "synthetic-read", ok: true, text: "Synthetic file result; no real file was read." }));
  events.push(event("assistant", { text: "The fictional module is ready for review. Open Files & review to inspect its bounded workspace view." }));
  events.push(event("done"));
  sessions = [{ ...sessions[0], last_seq: events.length, turns: 2 }];
}

if (agentMcpCallFixture) {
  const alias = "mcp_99999999_synthetic_read";
  const callId = "synthetic-mcp-model-call";
  const approvalId = "d".repeat(32);
  const descriptor = {
    contract_version: "agent-mcp-tool.v1" as const,
    source: "managed_mcp" as const,
    server_title: "Synthetic Files",
    tool_name: "read_example",
    tool_title: "Read example",
    model_alias: alias,
    every_call_requires_native_approval: true as const,
  };
  events.push(event("tool_call", { tool: alias, call_id: callId, arguments: {} }));
  events.push(event("approval_required", {
    tool: alias,
    call_id: callId,
    approval_id: approvalId,
    arguments: {},
    preview: "Allow one MCP tool call\nServer: Synthetic Files\nArguments: [redacted]",
    mcp_tool: descriptor,
  }));
  if (agentMcpCallCompletedFixture) {
    events.push(event("approval_resolved", {
      tool: alias,
      call_id: callId,
      approval_id: approvalId,
      ok: true,
      mcp_tool: descriptor,
    }));
    events.push(event("tool_result", {
      tool: alias,
      call_id: callId,
      ok: true,
      tool_state: "succeeded",
      text: "Synthetic bounded result; no external MCP server was contacted.",
      execution_receipt: {
        contract_version: "agent-tool-execution.v1",
        elapsed_ms: 250,
        timing_source: "server_monotonic.v1",
        approval_state: "approved",
        evidence_state: "untracked_external_effect",
      },
      mcp_tool: descriptor,
      mcp_result: {
        contract_version: "agent-mcp-tool-result.v1",
        managed_call_id: "a".repeat(32),
        outcome: "succeeded",
        content_mode: "text",
        result_bytes: 24,
        result_digest: "b".repeat(64),
        error_code: null,
        cleanup_verified: true,
        arguments_persisted: false,
        result_text_persisted: false,
        reusable_approval_persisted: false,
      },
    }));
  }
  sessions = [{
    ...sessions[0],
    running: !agentMcpCallCompletedFixture,
    last_seq: events.length,
    pending_approval_id: agentMcpCallCompletedFixture ? null : approvalId,
    turns: 1,
  }];
}

if (agentHistoryFixture) {
  const summary = exampleAgentTurn({
    model_alias: modelAlias,
    started_at: at,
    finished_at: "2040-01-01T00:00:02Z",
    tools_requested: 1,
    tools_succeeded: 1,
    writes: [exampleWriteReceipt({
      path: "docs/reviewed-example.md",
      after_sha256: retainedArtifact.latest_version.sha256,
      byte_size: retainedArtifactBytes,
    })],
  });
  events.push(event("user", { text: "Explain the retained synthetic module.", turn_id: summary.turn_id }));
  events.push(event("tool_result", {
    turn_id: summary.turn_id,
    tool: "write_file",
    call_id: "synthetic-retained-write",
    ok: true,
    tool_state: "succeeded",
    write_receipt: summary.writes[0],
    text: "Synthetic reviewed-write receipt; no real file was accessed.",
  }));
  events.push(event("assistant", {
    text: "The retained synthetic module is ready to reopen after restart.",
    reasoning: "Synthetic retained model rationale.",
    turn_id: summary.turn_id,
  }));
  events.push(event("done", { turn_id: summary.turn_id, turn_summary: summary }));
}

if (agentStressFixture) {
  for (let index = 0; index < 4_000; index += 1) {
    events.push(event("status", { text: `Synthetic maximum-history activity ${index + 1}` }));
  }
}

function syntheticHexId(value: number): string {
  return Math.max(0, Math.floor(value)).toString(16).padStart(32, "0");
}

let agentProjects: AgentProject[] = agentStressFixture
  ? Array.from({ length: 200 }, (_, index) => ({
      contract_version: "agent-catalog.v2" as const,
      project_id: index === 0 ? agentProjectId : syntheticHexId(0x10_000 + index),
      name: index === 0 ? "Maximum catalog project" : `Synthetic project ${index.toString().padStart(3, "0")}`,
      created_at: at,
      updated_at: at,
      revision: 1,
      pinned: index === 0,
      archived_at: null,
      session_count: index === 0 ? 2_000 : 0,
      is_default: index === 0,
    }))
  : [
      { contract_version: "agent-catalog.v2", project_id: agentProjectId, name: "Example coding project", created_at: at, updated_at: at,
        revision: 1, pinned: true, archived_at: null, session_count: agentHistoryFixture ? 1 : 2, is_default: true },
      { contract_version: "agent-catalog.v2", project_id: secondAgentProjectId, name: "Second example project", created_at: at, updated_at: at,
        revision: 1, pinned: false, archived_at: null, session_count: 0, is_default: false },
    ];
let agentCatalogSessions: AgentCatalogSession[] = agentStressFixture ? Array.from({ length: 2_000 }, (_, index) => ({
  contract_version: "agent-catalog.v2" as const,
  session_id: index === 0 ? sessionId : syntheticHexId(0x20_000 + index),
  project_id: agentProjectId,
  title: index === 0 ? "Maximum retained chat" : `Synthetic retained chat ${index.toString().padStart(4, "0")}`,
  workspace: "D:/example/maximum-project",
  model_alias: modelAlias,
  created_at: at,
  updated_at: at,
  last_opened_at: at,
  revision: 1,
  pinned: index === 0,
  archived_at: null,
  history_state: index === 0 ? "durable_local" as const : "memory_only" as const,
  retention_policy: index === 0 ? "local_history" as const : "metadata_only" as const,
  history_revision: index === 0 ? events.length : 0,
  last_event_seq: index === 0 ? events.length : 0,
  turn_count: index === 0 ? 1 : 0,
  conversation_available: index === 0,
  lineage: null,
})) : agentHistoryFixture ? [
  { contract_version: "agent-catalog.v2", session_id: sessionId, project_id: agentProjectId, title: "Saved restart chat",
    workspace: "D:/example/project", model_alias: modelAlias, created_at: at, updated_at: at, last_opened_at: at,
    revision: 1, pinned: true, archived_at: null, history_state: "durable_local", retention_policy: "local_history",
    history_revision: events.length, last_event_seq: events.length, turn_count: 1, conversation_available: true, lineage: null },
] : [
  { contract_version: "agent-catalog.v2", session_id: sessionId, project_id: agentProjectId, title: "Synthetic coding chat",
    workspace: "D:/example/project", model_alias: modelAlias, created_at: at, updated_at: at, last_opened_at: at,
    revision: 1, pinned: true, archived_at: null, history_state: "memory_only", retention_policy: "metadata_only",
    history_revision: 0, last_event_seq: 0, turn_count: 0, conversation_available: true, lineage: null },
  { contract_version: "agent-catalog.v2", session_id: "c".repeat(32), project_id: agentProjectId, title: "Restarted example chat",
    workspace: "D:/example/archived-project", model_alias: modelAlias, created_at: at, updated_at: at, last_opened_at: at,
    revision: 1, pinned: false, archived_at: null, history_state: "memory_only", retention_policy: "metadata_only",
    history_revision: 0, last_event_seq: 0, turn_count: 0, conversation_available: false, lineage: null },
];

const stressArtifacts: AgentArtifact[] = agentStressFixture ? Array.from({ length: 500 }, (_, index) => {
  const artifactId = syntheticHexId(0x30_000 + index);
  const path = `docs/synthetic-artifact-${index.toString().padStart(3, "0")}.md`;
  return {
    contract_version: "agent-artifact.v3",
    artifact_id: artifactId,
    project_id: agentProjectId,
    session_id: sessionId,
    title: `synthetic-artifact-${index.toString().padStart(3, "0")}.md`,
    kind: "markdown",
    path,
    created_at: at,
    updated_at: at,
    revision: 1,
    version_count: 1,
    availability: "unchecked",
    lifecycle_state: "active",
    archived_at: null,
    removed_at: null,
    latest_version: {
      contract_version: "agent-artifact.v3",
      version_id: syntheticHexId(0x40_000 + index),
      artifact_id: artifactId,
      version_number: 1,
      created_at: at,
      path,
      media_type: "text/markdown; charset=utf-8",
      preview_kind: "text",
      provenance: "verified_output",
      sha256: (index % 16).toString(16).repeat(64),
      byte_size: 100 + index,
      source_turn_id: null,
      source_event_seq: null,
    },
  };
}) : [];
const agentStressSnapshot = "9".repeat(64);
let agentForkReceipt: AgentSessionForkReceipt | null = null;

async function unavailable(): Promise<never> {
  throw new Error("This operation is outside the synthetic acceptance fixture.");
}

function fixturePageBounds(total: number, limit: number, offset: number) {
  const nextOffset = offset + limit < total ? offset + limit : null;
  return { complete: nextOffset === null, nextOffset };
}

function stressProjectPage(query: AgentCatalogPageQuery = {}): AgentProjectPage {
  const search = query.search?.trim().toLocaleLowerCase() ?? "";
  const source = search
    ? agentProjects.filter((project) => project.name.toLocaleLowerCase().includes(search))
    : agentProjects;
  const limit = query.limit ?? 100;
  const offset = query.offset ?? 0;
  const projects = source.slice(offset, offset + limit);
  const bounds = fixturePageBounds(source.length, limit, offset);
  return {
    contract_version: "agent-catalog-page.v1",
    snapshot: agentStressSnapshot,
    limit,
    offset,
    total: source.length,
    next_offset: bounds.nextOffset,
    complete: bounds.complete,
    projects,
  };
}

function stressSessionPage(query: AgentCatalogSessionPageQuery = {}): AgentCatalogSessionPage {
  const search = query.search?.trim().toLocaleLowerCase() ?? "";
  const source = agentCatalogSessions.filter((session) => (
    (query.projectId === undefined || session.project_id === query.projectId)
    && (!search || session.title.toLocaleLowerCase().includes(search))
  ));
  const limit = query.limit ?? 100;
  const offset = query.offset ?? 0;
  const sessionsForPage = source.slice(offset, offset + limit);
  const bounds = fixturePageBounds(source.length, limit, offset);
  return {
    contract_version: "agent-catalog-page.v1",
    snapshot: agentStressSnapshot,
    limit,
    offset,
    total: source.length,
    next_offset: bounds.nextOffset,
    complete: bounds.complete,
    sessions: sessionsForPage,
  };
}

function stressArtifactPage(
  projectId: string,
  id: string,
  query: AgentArtifactPageQuery = {},
): AgentArtifactPage {
  const view = query.view ?? "active";
  const source = projectId === agentProjectId && id === sessionId && view === "active"
    ? stressArtifacts
    : [];
  const limit = query.limit ?? 100;
  const offset = query.offset ?? 0;
  const artifacts = source.slice(offset, offset + limit);
  const bounds = fixturePageBounds(source.length, limit, offset);
  return {
    contract_version: "agent-artifact-page.v1",
    project_id: projectId,
    session_id: id,
    view,
    snapshot: agentStressSnapshot,
    limit,
    offset,
    total: source.length,
    next_offset: bounds.nextOffset,
    complete: bounds.complete,
    counts: { active: stressArtifacts.length, archived: 0, removed: 0, total: stressArtifacts.length },
    artifacts,
  };
}

function retainedEventsForExport(source: AgentEvent[]): AgentHistoryExport["events"] {
  return source.flatMap((entry): AgentHistoryExport["events"] => {
    if (
      entry.kind === "assistant_delta"
      || entry.kind === "approval_required"
      || entry.kind === "approval_resolved"
    ) return [];
    return [{
      at: entry.at,
      call_id: entry.call_id,
      kind: entry.kind,
      ok: entry.ok,
      reasoning: entry.reasoning,
      seq: entry.seq,
      stream_id: entry.stream_id,
      stream_status: entry.stream_status,
      text: entry.text,
      tool: entry.tool,
      tool_state: entry.tool_state,
      turn_id: entry.turn_id,
      turn_summary: entry.turn_summary,
      write_receipt: entry.write_receipt,
    }];
  });
}

const transport = {
  getAgentOrchestration: async () => exampleAgentOrchestrationManifest(),
  getAgentMcpClientSetup: async () => agentMcpSetup,
  listAgentMcpConnections: async () => (
    agentControllerOwnershipFixture
      ? agentMcpOwnershipConnections
      : agentMcpConnections
  ),
  ...(agentMcpStoreFixture || agentMcpProjectToolsFixture ? {
    listMcpRegistryCatalog: async (query: { cursor?: string } = {}) => (
      agentMcpStoreHostileFixture
        ? {
            ...mcpStoreHostileCatalog,
            next_cursor: query.cursor ?? mcpStoreHostileCatalog.next_cursor,
          }
        : agentMcpStoreScaleFixture ? mcpStoreScaleCatalog : mcpStoreCatalog
    ),
    getMcpRegistryServerReview: async () => mcpStoreReview,
    listMcpManagedServers: async () => syntheticMcpManagedServerList([
      agentMcpProjectToolsFixture ? mcpProjectToolsManaged : mcpStoreManaged,
    ]),
    getMcpManagedToolSnapshot: async () => mcpProjectToolsSnapshot,
    getMcpManagedProjectRuntime: async (projectId: string) => syntheticMcpManagedProjectRuntime({
      project_id: projectId,
    }),
  } : {}),
  getAgentHardening: async () => {
    hardeningRequests += 1;
    document.documentElement.dataset.agentHardeningRequests = String(hardeningRequests);
    return hardeningSnapshot;
  },
  beginAgentNativeAcceptance: async () => {
    acceptanceRequests += 1;
    document.documentElement.dataset.agentAcceptanceRequests = String(acceptanceRequests);
    return {
      contract_version: "agent-native-acceptance-start.v1" as const,
      owner_presence_confirmed: true as const,
      model_execution_started: false as const,
      process_spawn_requested: false as const,
      workspace_access_requested: false as const,
      content_persisted: false as const,
      expires_on_reload: true as const,
    };
  },
  getLocalModels: async () => {
    const snapshot = overview();
    if (modelRaceFixture && holdNextModelRead) {
      holdNextModelRead = false;
      return new Promise<LocalModelsOverview>((resolve) => { heldModelRead = { snapshot, resolve }; });
    }
    return snapshot;
  },
  getLocalModelCompatibility: async () => compatibilityCatalog(),
  activateLocalModel: async () => {
    model = { ...model, runtime: { state: "running", device: "cpu" } };
    return model;
  },
  deactivateLocalModel: async () => {
    model = { ...model, runtime: { state: "stopped", device: null } };
    return model;
  },
  removeLocalModel: unavailable, getLocalModelRemoteFiles: unavailable,
  startLocalModelDownload: unavailable, addLocalModel: unavailable,
  streamLocalModelChat: async (_alias, _request, onDelta) => {
    if (modelCompletionFixture) {
      if (_request.messages.some((entry) => entry.role === "assistant" && entry.content === "Synthetic unfinished reply.")) {
        throw new Error("An incomplete reply entered the next model history.");
      }
      if (chatRequests++ === 0) {
        onDelta({ content: "Synthetic unfinished reply." });
        return { content: "Synthetic unfinished reply.", reasoning: "", finish_reason: "length", elapsed_ms: 10 };
      }
    }
    onDelta({ reasoning: "Synthetic reasoning: check the example acceptance condition." });
    onDelta({ content: "Synthetic reply: the example is ready to review." });
    return { content: "Synthetic reply: the example is ready to review.",
      reasoning: "Synthetic reasoning: check the example acceptance condition.", finish_reason: "stop", elapsed_ms: 10 };
  },
  ...(agentCatalogFixture ? {
    getLocalRuntime: async () => runtimeCoordinator(),
    getAgentSessionContext: async (id): Promise<AgentSessionContextStatus> => {
      const current = sessions.find((entry) => entry.session_id === id);
      if (!current) return unavailable();
      if (
        agentShellFixture
        && current.model_alias === modelAlias
        && runtimeAlias === modelAlias
        && runtimeHasMeasuredRequest
      ) {
        return {
          contract_version: "agent-session-context.v1",
          session_id: id,
          revision: 1,
          binding_state: "bound",
          source: "runtime_chat_template_preflight",
          unknown_reason: null,
          turn_id: "6".repeat(32),
          turn_number: 2,
          model_alias: modelAlias,
          observed_at: at,
          context: {
            state: "known",
            used_tokens: 612,
            limit_tokens: 4096,
            requested_output_tokens: 1400,
            available_output_tokens: 3484,
            source: "runtime_chat_input_tokens",
            scope: "last_request",
            policy: "exact_admitted",
            compacted_messages: 0,
            reason_code: null,
          },
        };
      }
      return {
        contract_version: "agent-session-context.v1",
        session_id: id,
        revision: 0,
        binding_state: "unmeasured",
        source: "runtime_chat_template_preflight",
        unknown_reason: current.recovered
          ? "recovered_without_context_receipt"
          : "model_changed",
        turn_id: null,
        turn_number: null,
        model_alias: null,
        observed_at: null,
        context: null,
      };
    },
    switchLocalRuntime: async (request) => {
      runtimeAlias = request.alias;
      runtimeDevice = request.device ?? "split";
      runtimeContextSize = request.context_size ?? 8192;
      runtimeHasMeasuredRequest = false;
      runtimeRevision += 1;
      return runtimeCoordinator();
    },
    stopLocalRuntime: async () => {
      runtimeAlias = null;
      runtimeHasMeasuredRequest = false;
      runtimeRevision += 1;
      return runtimeCoordinator();
    },
    ...(agentStressFixture ? {
      pageAgentProjects: async (query?: AgentCatalogPageQuery) => stressProjectPage(query),
      pageAgentCatalogSessions: async (query?: AgentCatalogSessionPageQuery) => stressSessionPage(query),
      pageAgentArtifacts: async (projectId: string, id: string, query?: AgentArtifactPageQuery) => (
        stressArtifactPage(projectId, id, query)
      ),
    } : {}),
    listAgentProjects: async () => ({ contract_version: "agent-catalog.v2" as const, projects: [...agentProjects] }),
    createAgentProject: async () => agentProjects[0],
    updateAgentProject: async () => agentProjects[0],
    deleteAgentProject: async () => undefined,
    listAgentCatalogSessions: async () => ({ contract_version: "agent-catalog.v2" as const, sessions: [...agentCatalogSessions] }),
    getAgentCatalogSession: async (id) => agentCatalogSessions.find((entry) => entry.session_id === id) ?? unavailable(),
    getAgentPersistedEvents: async (projectId, id, after) => {
      const record = agentCatalogSessions.find((entry) => entry.project_id === projectId && entry.session_id === id);
      if (!record || record.retention_policy !== "local_history") return unavailable();
      return {
        contract_version: "local-agent.v9" as const,
        session_id: id,
        events: events.filter((entry) => (
          entry.seq > after && entry.seq <= record.last_event_seq
        )).slice(0, agentStressFixture ? 500 : events.length),
        running: false,
        closing: false,
        stopping: false,
        cleanup_unconfirmed: false,
        pending_approval_id: null,
        last_seq: record.last_event_seq,
        first_seq: events.length ? events[0].seq : 0,
      };
    },
    resumeAgentSession: async (projectId, id) => {
      const record = agentCatalogSessions.find((entry) => entry.project_id === projectId && entry.session_id === id);
      if (!record || record.retention_policy !== "local_history") return unavailable();
      const recovered: AgentSessionView = {
        contract_version: "local-agent.v9",
        session_id: id,
        settings: {
          workspace: record.workspace,
          project_id: record.project_id,
          model_alias: record.model_alias,
          parameters: { temperature: 0.2, top_p: 0.95, max_tokens: 1400, enable_thinking: true },
          instructions: null,
          allow_writes: false,
          allow_commands: false,
          allow_web: false,
          max_steps: 10,
          command_timeout_seconds: 120,
          title: record.title,
          retention_policy: "local_history",
        },
        created_at: record.created_at,
        running: false,
        closing: false,
        stopping: false,
        cleanup_unconfirmed: false,
        last_seq: record.last_event_seq,
        pending_approval_id: null,
        model_alias: record.model_alias,
        turns: record.turn_count,
        history_revision: record.history_revision,
        recovered: true,
        authority_revalidated: false,
        history_write_failed: false,
        recovery_state: "recovered",
      };
      sessions = [recovered];
      return recovered;
    },
    exportAgentHistory: async (projectId, id) => {
      const record = agentCatalogSessions.find((entry) => entry.project_id === projectId && entry.session_id === id);
      if (!record || record.retention_policy !== "local_history") return unavailable();
      return {
        contract_version: "agent-history.v1" as const,
        exported_at: at,
        project_id: projectId,
        session_id: id,
        title: record.title,
        workspace: record.workspace,
        model_alias: record.model_alias,
        history_revision: record.history_revision,
        turn_count: record.turn_count,
        interrupted: false,
        events: retainedEventsForExport(events),
      };
    },
    listAgentArtifacts: async (projectId, id) => ({
      contract_version: "agent-artifact.v3" as const,
      project_id: projectId,
      session_id: id,
      view: "active" as const,
      counts: {
        active: agentStressFixture && projectId === agentProjectId && id === sessionId
          ? stressArtifacts.length
          : agentHistoryFixture && projectId === agentProjectId && id === sessionId ? 1 : 0,
        archived: 0,
        removed: 0,
        total: agentStressFixture && projectId === agentProjectId && id === sessionId
          ? stressArtifacts.length
          : agentHistoryFixture && projectId === agentProjectId && id === sessionId ? 1 : 0,
      },
      artifacts: agentStressFixture && projectId === agentProjectId && id === sessionId
        ? [...stressArtifacts]
        : agentHistoryFixture && projectId === agentProjectId && id === sessionId ? [retainedArtifact] : [],
    }),
    getAgentArtifact: async (projectId, id, artifactId) => {
      if (
        !agentHistoryFixture
        || projectId !== agentProjectId
        || id !== sessionId
        || artifactId !== retainedArtifactId
      ) return unavailable();
      return retainedArtifactDetail;
    },
    exportAgentArtifact: async (projectId, id, artifactId, request) => {
      if (
        !agentHistoryFixture
        || projectId !== agentProjectId
        || id !== sessionId
        || artifactId !== retainedArtifactId
        || request.expected_revision !== retainedArtifactDetail.revision
      ) return unavailable();
      return artifactLineageExport(retainedArtifactDetail, request.version_id);
    },
    updateAgentArtifact: async () => retainedArtifact,
    removeAgentArtifact: async () => retainedArtifact,
    getAgentArtifactContent: async (projectId, id, artifactId, versionId) => {
      if (
        !agentHistoryFixture
        || projectId !== agentProjectId
        || id !== sessionId
        || artifactId !== retainedArtifactId
      ) return unavailable();
      if (versionId === retainedArtifactPriorVersionId) {
        throw new TransportError("Synthetic historical artifact is stale", 409);
      }
      if (versionId !== retainedArtifactVersionId) return unavailable();
      return {
        blob: new Blob([retainedArtifactText], { type: "text/plain" }),
        contentType: "text/plain; charset=utf-8",
        filename: "agent-artifact-33333333.md",
        byteSize: retainedArtifactBytes,
      };
    },
    switchAgentSessionModel: async (id, request) => {
      const existing = sessions.find((entry) => entry.session_id === id);
      if (!existing) return unavailable();
      const updated: AgentSessionView = {
        ...existing,
        settings: { ...existing.settings, model_alias: request.model_alias },
        model_alias: request.model_alias,
      };
      sessions = sessions.map((entry) => entry.session_id === id ? updated : entry);
      agentCatalogSessions = agentCatalogSessions.map((entry) => entry.session_id === id
        ? { ...entry, model_alias: request.model_alias, revision: entry.revision + 1 }
        : entry);
      return updated;
    },
    forkAgentSession: async (projectId, id, request) => {
      if (agentForkReceipt?.request_id === request.request_id) {
        return { ...agentForkReceipt, idempotent_replay: true };
      }
      const source = agentCatalogSessions.find((entry) => (
        entry.project_id === projectId && entry.session_id === id
      ));
      if (!source || source.retention_policy !== "local_history") return unavailable();
      if (
        source.revision !== request.expected_catalog_revision
        || source.history_revision !== request.expected_history_revision
      ) {
        throw new TransportError("Synthetic stale branch request", 409, "agent_history_revision_conflict");
      }
      const latestDone = [...events].reverse().find((entry) => entry.kind === "done")?.seq ?? 0;
      const branchEventSeq = request.through_event_seq ?? latestDone;
      if (branchEventSeq > 0 && events.find((entry) => entry.seq === branchEventSeq)?.kind !== "done") {
        throw new TransportError("Synthetic invalid branch point", 422, "agent_session_fork_point_invalid");
      }
      const destinationProjectId = request.destination_project_id ?? projectId;
      const copiedTurnCount = events.filter((entry) => (
        entry.seq <= branchEventSeq && entry.kind === "done"
      )).length;
      const child: AgentCatalogSession = {
        ...source,
        session_id: forkedAgentSessionId,
        project_id: destinationProjectId,
        title: request.title ?? `${source.title} (branch)`,
        revision: 1,
        pinned: false,
        archived_at: null,
        history_revision: branchEventSeq,
        last_event_seq: branchEventSeq,
        turn_count: copiedTurnCount,
        lineage: {
          contract_version: "agent-session-lineage.v1",
          source_project_id: projectId,
          source_session_id: id,
          source_catalog_revision: source.revision,
          source_history_revision: source.history_revision,
          branch_event_seq: branchEventSeq,
          copied_event_count: branchEventSeq,
          copied_turn_count: copiedTurnCount,
          copied_attachment_count: 0,
          created_at: at,
        },
      };
      agentCatalogSessions = [...agentCatalogSessions, child];
      agentProjects = agentProjects.map((project) => project.project_id === destinationProjectId
        ? { ...project, session_count: project.session_count + 1 }
        : project);
      agentForkReceipt = {
        contract_version: "agent-session-fork.v1",
        request_id: request.request_id,
        idempotent_replay: false,
        session: child,
        source_tail_omitted: source.last_event_seq > branchEventSeq,
        approvals_copied: false,
        mutation_authority_copied: false,
        pending_tool_state_copied: false,
        staged_attachments_copied: false,
        artifacts_copied: false,
      };
      return agentForkReceipt;
    },
    updateAgentCatalogSession: async () => agentCatalogSessions[0],
    deleteAgentCatalogSession: async () => undefined,
  } : {}),
  listAgentSessions: async () => [...sessions],
  listAgentAttachments: async (id) => ({
    contract_version: "agent-attachment.v2" as const,
    session_id: id,
    attachments: stagedAttachments.filter((attachment) => attachment.session_id === id),
  }),
  stageAgentAttachment: async (id, upload) => {
    attachmentSequence += 1;
    const mediaType = upload.blob.type as AgentAttachment["media_type"];
    const kind = mediaType === "audio/wav"
      ? "audio"
      : mediaType.startsWith("image/")
        ? "image"
        : "document";
    const documentFormat = kind === "document"
      ? mediaType === "text/markdown" ? "markdown" as const : "plain_text" as const
      : null;
    const projectedText = kind === "document" ? (await upload.blob.text()).trim() : null;
    const attachment: AgentAttachment = {
      contract_version: "agent-attachment.v2",
      attachment_id: attachmentSequence.toString(16).padStart(32, "0"),
      session_id: id,
      model_alias: runtimeAlias ?? modelAlias,
      display_name: upload.displayName,
      kind,
      media_type: mediaType,
      byte_size: upload.blob.size,
      sha256: attachmentSequence.toString(16).repeat(64).slice(0, 64),
      width: kind === "image" ? 1 : null,
      height: kind === "image" ? 1 : null,
      duration_ms: kind === "audio" ? 1 : null,
      sample_rate_hz: kind === "audio" ? 16_000 : null,
      channels: kind === "audio" ? 1 : null,
      routing: kind === "document" ? "local_text_projection" : "native_multimodal",
      document_format: documentFormat,
      projected_characters: projectedText?.length ?? null,
      projection_truncated: kind === "document" ? false : null,
      omitted_features: [],
      source: upload.source,
      state: "staged",
      retention: "memory_only",
      created_at: at,
      expires_at: "2040-01-01T00:15:00Z",
      attached_event_seq: null,
      capability_probe_version: "local-runtime-multimodal-probe.v2",
      context_tokens: null,
      context_cost_source: "runtime_unreported",
    };
    if (projectedText !== null) {
      documentAttachmentPreviews.set(attachment.attachment_id, projectedText);
    }
    stagedAttachments = [...stagedAttachments, attachment];
    return attachment;
  },
  deleteAgentAttachment: async (id, attachmentId) => {
    stagedAttachments = stagedAttachments.filter((attachment) => (
      attachment.session_id !== id || attachment.attachment_id !== attachmentId
    ));
    documentAttachmentPreviews.delete(attachmentId);
  },
  getAgentAttachmentDocumentPreview: async (id, attachmentId) => {
    const attachment = stagedAttachments.find((candidate) => (
      candidate.session_id === id && candidate.attachment_id === attachmentId
    ));
    const text = documentAttachmentPreviews.get(attachmentId);
    if (attachment?.kind !== "document" || text === undefined || !attachment.document_format) {
      throw new TransportError("Synthetic document preview is unavailable", 404);
    }
    return {
      contract_version: "agent-attachment-document-preview.v1" as const,
      session_id: id,
      attachment_id: attachmentId,
      sha256: attachment.sha256,
      media_type: attachment.media_type,
      document_format: attachment.document_format,
      text,
      projected_characters: text.length,
      projection_truncated: false,
      preview_truncated: false,
      omitted_features: [],
    };
  },
  createAgentSession: async (settings) => {
    if (commandCleanupReported) throw new TransportError("Agent work paused", 409, "command_cleanup_unconfirmed");
    const created: AgentSessionView = { contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false, session_id: sessionId,
      settings, created_at: at, running: false, last_seq: 0, pending_approval_id: null, model_alias: modelAlias, turns: 0,
      history_revision: 0, recovered: false, authority_revalidated: true, history_write_failed: false, recovery_state: "current" };
    sessions = [created];
    events = [];
    return created;
  },
  getAgentSession: async () => sessions[0],
  deleteAgentSession: async () => {
    if (commandCleanupReported) throw new TransportError("Agent work paused", 409, "command_cleanup_unconfirmed");
    if (closeFailures > 0) {
      closeFailures -= 1;
      throw new TransportError("Synthetic close timeout", 409, "session_stop_timeout");
    }
    sessions = []; events = [];
  },
  sendAgentMessage: async (_id, text, attachmentIds = []) => {
    if (commandCleanupReported) throw new TransportError("Agent work paused", 409, "command_cleanup_unconfirmed");
    const attached = stagedAttachments.filter((attachment) => attachmentIds.includes(attachment.attachment_id));
    events.push(event("user", { text, attachments: attached.map(messageAttachment) }));
    stagedAttachments = stagedAttachments.filter((attachment) => !attachmentIds.includes(attachment.attachment_id));
    for (const attachmentId of attachmentIds) documentAttachmentPreviews.delete(attachmentId);
    if (agentStoppingFixture && !cancelledExampleReleased) {
      sessions = [{ ...sessions[0], running: true, stopping: false, last_seq: events.length, turns: sessions[0].turns + 1 }];
      return sessions[0];
    }
    if (agentCompletionFixture && sessions[0].turns === 1) {
      events.push(event("assistant", { text: "Synthetic unfinished Agent reply.",
        reasoning: "Synthetic partial model trace.", stream_id: "e".repeat(32), stream_status: "failed" }));
      events.push(event("error", { text: "The model reached its response token limit before finishing. Partial output was not used for tool actions or conversation history. Ask for a smaller step." }));
    } else {
      events.push(event("assistant", { text: "Synthetic agent reply: no real files were read or changed.",
        reasoning: sessions[0].settings.parameters?.enable_thinking ? "Synthetic reasoning: inspect the fictional request." : null }));
    }
    events.push(event("done"));
    sessions = [{ ...sessions[0], running: false, last_seq: events.length, turns: sessions[0].turns + 1 }];
    // Make the UI enter the working state, then its event read supplies the done receipt.
    return { ...sessions[0], running: true };
  },
  getAgentEvents: async (_id, after) => {
    olderCommandSnapshotRead?.();
    olderCommandSnapshotRead = null;
    return { contract_version: "local-agent.v9", cleanup_unconfirmed: sessions[0]?.cleanup_unconfirmed ?? false, closing: sessions[0]?.closing ?? false, stopping: sessions[0]?.stopping ?? false, session_id: sessionId,
      events: events.filter((entry) => entry.seq > after), running: sessions[0]?.running ?? false,
      pending_approval_id: sessions[0]?.pending_approval_id ?? null, last_seq: events.length, first_seq: events.length ? 1 : 0 };
  },
  revalidateAgentAuthority: async (_id, request) => {
    const existing = sessions[0];
    if (!existing?.recovered) return unavailable();
    const revalidated: AgentSessionView = {
      ...existing,
      authority_revalidated: true,
      settings: {
        ...existing.settings,
        allow_writes: request.allow_writes,
        allow_commands: request.allow_commands,
        allow_web: request.allow_web,
      },
    };
    sessions = [revalidated];
    return revalidated;
  },
  getAgentChangeSet: async (id) => ({
    contract_version: "agent-change-set.v1",
    session_id: id,
    scope: "reviewed_paths_only",
    coverage: agentWorkspaceFixture ? "partial" : "complete",
    settled: true,
    reviewed_writes: agentWorkspaceFixture ? 2 : 0,
    verified_writes: agentWorkspaceFixture ? 1 : 0,
    unverified_writes: agentWorkspaceFixture ? 1 : 0,
    agent_writes: agentWorkspaceFixture ? 2 : 0,
    manual_writes: 0,
    reviewed_noops: 0,
    command_attempts: agentWorkspaceFixture ? 1 : 0,
    omitted_write_receipts: 0,
    tracking_failed: false,
    files: agentWorkspaceFixture ? [
      { path: "example.ts", net_effect: "modified", verification: "verified", reason: null,
        reviewed_writes: 1, agent_writes: 1, manual_writes: 0, current_byte_size: 30, diff_available: true },
      { path: "pending-example.ts", net_effect: "unknown", verification: "unverified", reason: "publication_unverified",
        reviewed_writes: 1, agent_writes: 1, manual_writes: 0, current_byte_size: null, diff_available: false },
    ] : [],
  }),
  getAgentChangeDiff: async (id, path) => {
    if (!agentWorkspaceFixture || path !== "example.ts") return unavailable();
    return {
      contract_version: "agent-change-set.v1",
      session_id: id,
      summary: { path, net_effect: "modified", verification: "verified", reason: null,
        reviewed_writes: 1, agent_writes: 1, manual_writes: 0, current_byte_size: 30, diff_available: true },
      diff_state: "available",
      diff: "--- a/example.ts\n+++ b/example.ts\n@@ -1 +1 @@\n-old fictional value\n+Current fictional file content",
      added_lines: 1,
      removed_lines: 1,
    };
  },
  decideAgentApproval: async (_id, approvalId, approved) => {
    if (!agentMcpCallFixture || approved || approvalId !== "d".repeat(32)) return unavailable();
    const descriptor = events.find((entry) => entry.kind === "approval_required")?.mcp_tool;
    const callId = events.find((entry) => entry.kind === "tool_call")?.call_id ?? null;
    const alias = descriptor?.model_alias ?? null;
    events.push(event("approval_resolved", {
      tool: alias,
      call_id: callId,
      approval_id: approvalId,
      ok: false,
      mcp_tool: descriptor ?? null,
    }));
    events.push(event("tool_result", {
      tool: alias,
      call_id: callId,
      ok: false,
      tool_state: "not_approved",
      text: "Synthetic MCP call was not invoked after denial.",
      execution_receipt: {
        contract_version: "agent-tool-execution.v1",
        elapsed_ms: 0,
        timing_source: "server_monotonic.v1",
        approval_state: "denied",
        evidence_state: "no_effect",
      },
      mcp_tool: descriptor ?? null,
      mcp_result: {
        contract_version: "agent-mcp-tool-result.v1",
        managed_call_id: "a".repeat(32),
        outcome: "not_invoked",
        content_mode: "none",
        result_bytes: 0,
        result_digest: null,
        error_code: null,
        cleanup_verified: true,
        arguments_persisted: false,
        result_text_persisted: false,
        reusable_approval_persisted: false,
      },
    }));
    sessions = [{
      ...sessions[0],
      running: false,
      last_seq: events.length,
      pending_approval_id: null,
    }];
    return sessions[0];
  },
  stopAgentSession: async () => {
    if (agentStoppingFixture || agentCommandFixture) {
      events.push(event("status", { text: "Stopping the fictional request; cleanup is not yet confirmed." }));
      sessions = [{ ...sessions[0], running: true, stopping: true, last_seq: events.length }];
      return sessions[0];
    }
    return { ...sessions[0], running: false, stopping: false };
  },
  getAgentWorkspaceTree: async (id, path) => ({ contract_version: "local-agent-workspace.v1", session_id: id, path,
    entries: agentWorkspaceFixture ? [{ path: "example.ts", name: "example.ts", kind: "file", byte_size: 30, editable_candidate: true }] : [], complete: true }),
  getAgentWorkspaceDiscovery: async (id) => ({
    contract_version: "local-agent-workspace-discovery.v1", session_id: id, scope: "selected_workspace",
    inventory_coverage: "complete", inventory_reasons: [], scanned_entry_count: agentWorkspaceFixture ? 2 : 0,
    observed_file_count: agentWorkspaceFixture ? 2 : 0,
    files: agentWorkspaceFixture ? [
      { path: "example.ts", byte_size: 30, editable_candidate: true },
      { path: "notes/example.md", byte_size: 48, editable_candidate: true },
    ] : [],
    git_state: "not_repository", git_coverage: "not_applicable", git_reasons: [], git_change_count: 0, git_changes: [],
  }),
  getAgentWorkspaceSearch: async (id, request) => ({
    contract_version: "local-agent-workspace-search.v1", session_id: id, scope: "application_readable_utf8_text",
    coverage: request.query === "partial" ? "partial" : "complete",
    reasons: request.query === "partial" ? ["match limit reached"] : [],
    reason_code: request.query === "partial" ? "workspace_inspection_incomplete" : null,
    scanned_entry_count: 2, inspected_byte_count: 78, skipped_entry_count: 0,
    match_count: request.query === "missing" ? 0 : 1,
    matches: request.query === "missing" ? [] : [
      { path: "example.ts", line_number: 1, preview: "Current fictional file content" },
    ],
  }),
  getAgentWorkspaceFile: agentWorkspaceFixture ? async (id, path) => ({ contract_version: "local-agent-workspace.v1", session_id: id, path,
    content: "Current fictional file content\n", revision: "f".repeat(64), byte_size: 30, line_ending: "lf", editable: true }) : unavailable,
  previewAgentWorkspaceEdit: unavailable, applyAgentWorkspaceEdit: unavailable,
  getUserPresenceCapability: async () => agentHistoryFixture || agentMcpCallFixture
    ? ({ contract_version: "native-user-presence-capability-v1" as const, confirmation_available: true, mode: "native_bridge_bound_token" as const })
    : ({ contract_version: "native-user-presence-capability-v1" as const, confirmation_available: false, mode: "unavailable" as const }),
  checkPrompt: async () => { checks = [record()]; return result; },
  getPromptCheck: async () => record(),
  getPromptCheckHistory: async (limit, offset) => ({ contract_version: "prompt-check.v1", checks: [...checks], limit, offset }),
  listSharedFolders: async () => ({ contract_version: "shared-folders.v1", shares: [...shares] }),
  listPeerLinks: async () => ({ contract_version: "shared-folders.v1", links: [...links] }),
  shareFolder: async (path, name) => {
    const created: SharedFolder = { contract_version: "shared-folders.v1", share_id: "example-share", created_at: at,
      name, path, share_token: "synthetic-example-share-token" };
    shares = [{ ...created, share_token: null }];
    return created;
  },
  revokeSharedFolder: async () => { shares = []; },
  joinSharedFolder: async (url, shareId, _token, target) => {
    const joined: PeerLink = { contract_version: "shared-folders.v1", link_id: "example-link", share_id: shareId,
      joined_at: at, name: "Example team folder", url, target };
    links = [joined];
    return joined;
  },
  leavePeerLink: async () => { links = []; },
  pullPeerLink: async (linkId) => ({ contract_version: "shared-folders.v1", link_id: linkId, pulled: 1, pushed: 0, skipped: 2, conflicts: 0 }),
  pushPeerLink: async (linkId) => ({ contract_version: "shared-folders.v1", link_id: linkId, pulled: 0, pushed: 1, skipped: 0, conflicts: 1 }),
} satisfies Partial<PromptEnhancerTransport>;

let editorContent = "export const value = 1;\n";
let reviewedContent = editorContent;
let editorRevision = "b".repeat(64);
let failReadback = false;
let folderReads = 0;
const editorFile = (): AgentWorkspaceFile => ({
  contract_version: "local-agent-workspace.v1", session_id: sessionId, path: "example.ts",
  content: editorContent, revision: editorRevision, byte_size: editorContent.length, line_ending: "lf", editable: true,
});
const editorTransport = {
  getAgentWorkspaceTree: async (id, path) => {
    if (folderReads++ === 0) throw new TransportError("Synthetic temporary read failure", 503);
    return { contract_version: "local-agent-workspace.v1", session_id: id, path, complete: true,
      entries: [{ path: "example.ts", name: "example.ts", kind: "file", byte_size: editorContent.length, editable_candidate: true }] };
  },
  getAgentWorkspaceDiscovery: async (id) => ({
    contract_version: "local-agent-workspace-discovery.v1" as const,
    session_id: id,
    scope: "selected_workspace" as const,
    inventory_coverage: "complete" as const,
    inventory_reasons: [],
    scanned_entry_count: 1,
    observed_file_count: 1,
    files: [{ path: "example.ts", byte_size: editorContent.length, editable_candidate: true }],
    git_state: "not_repository" as const,
    git_coverage: "not_applicable" as const,
    git_reasons: [],
    git_change_count: 0,
    git_changes: [],
  }),
  getAgentWorkspaceSearch: async (id, request) => ({
    contract_version: "local-agent-workspace-search.v1" as const,
    session_id: id,
    scope: "application_readable_utf8_text" as const,
    coverage: request.query === "partial" ? "partial" as const : "complete" as const,
    reasons: request.query === "partial" ? ["match limit reached"] : [],
    reason_code: request.query === "partial" ? "workspace_inspection_incomplete" : null,
    scanned_entry_count: 1,
    inspected_byte_count: editorContent.length,
    skipped_entry_count: 0,
    match_count: request.query === "missing" ? 0 : 1,
    matches: request.query === "missing" ? [] : [
      { path: "example.ts", line_number: 1, preview: editorContent.trim() },
    ],
  }),
  getAgentWorkspaceFile: async () => {
    if (failReadback) { failReadback = false; throw new TransportError("Synthetic readback failure", 503); }
    return editorFile();
  },
  previewAgentWorkspaceEdit: async (_id, request) => {
    reviewedContent = request.content;
    return { contract_version: "local-agent-workspace.v1", session_id: sessionId,
      preview_id: "d".repeat(32), path: "example.ts", expected_revision: editorRevision,
      proposed_revision: "c".repeat(64), line_ending: "lf",
      diff: "--- a/example.ts\n+++ b/example.ts\n- export const value = 1;\n+ export const value = 2;",
      expires_at: "2040-01-01T00:10:00Z" };
  },
  applyAgentWorkspaceEdit: async () => {
    editorContent = reviewedContent;
    editorRevision = "c".repeat(64);
    failReadback = true;
    return { contract_version: "local-agent-workspace.v1", session_id: sessionId,
      path: "example.ts", revision: editorRevision, byte_size: editorContent.length, applied: true };
  },
  previewAgentWorkspaceTransaction: async (id, request) => {
    const files = [...request.changes]
      .sort((left, right) => left.path.localeCompare(right.path))
      .map((change) => ({
        operation: change.operation,
        path: change.path,
        expected_revision: change.expected_revision ?? null,
        proposed_revision: change.operation === "create" ? "3".repeat(64) : "c".repeat(64),
        line_ending: change.line_ending,
        proposed_byte_size: new TextEncoder().encode(
          change.line_ending === "crlf" ? change.content.replaceAll("\n", "\r\n") : change.content,
        ).byteLength,
        added_lines: 1,
        removed_lines: change.operation === "create" ? 0 : 1,
        diff: change.operation === "create"
          ? `--- a/${change.path}\n+++ b/${change.path}\n@@ -0,0 +1 @@\n+synthetic creation`
          : `--- a/${change.path}\n+++ b/${change.path}\n@@ -1 +1 @@\n-old synthetic value\n+new synthetic value`,
      }));
    return {
      contract_version: "local-agent-workspace-transaction.v2" as const,
      session_id: id,
      plan_id: "2".repeat(32),
      file_count: files.length,
      total_byte_size: files.reduce((total, item) => total + item.proposed_byte_size, 0),
      added_lines: files.reduce((total, item) => total + item.added_lines, 0),
      removed_lines: files.reduce((total, item) => total + item.removed_lines, 0),
      files,
      expires_at: "2040-01-01T00:10:00Z",
    };
  },
  applyAgentWorkspaceTransaction: async (id, preview) => ({
    contract_version: "local-agent-workspace-transaction.v2" as const,
    session_id: id,
    plan_id: preview.plan_id,
    state: "committed" as const,
    reason: null,
    file_count: preview.file_count,
    files: preview.files.map((item) => ({
      path: item.path,
      state: "committed" as const,
      revision: item.proposed_revision,
      byte_size: item.proposed_byte_size,
    })),
  }),
} satisfies Pick<PromptEnhancerTransport,
  | "getAgentWorkspaceTree"
  | "getAgentWorkspaceDiscovery"
  | "getAgentWorkspaceSearch"
  | "getAgentWorkspaceFile"
  | "previewAgentWorkspaceEdit"
  | "applyAgentWorkspaceEdit"
  | "previewAgentWorkspaceTransaction"
  | "applyAgentWorkspaceTransaction"
>;

let inspectionFolderReads = 0;
const inspectionEditorTransport: Pick<PromptEnhancerTransport, keyof typeof editorTransport> = {
  ...editorTransport,
  getAgentWorkspaceTree: async (id, path) => {
    const attempt = inspectionFolderReads++;
    if (attempt === 0) return { contract_version: "local-agent-workspace.v1", session_id: id, path, entries: [], complete: false };
    if (attempt === 1) throw new TransportError("EXAMPLE_PRIVATE_WORKSPACE_CANARY", 503, "workspace_inspection_timeout");
    if (attempt >= 3) throw new TransportError("EXAMPLE_PRIVATE_WORKSPACE_CANARY", 409, "workspace_root_changed");
    return { contract_version: "local-agent-workspace.v1", session_id: id, path, complete: true,
      entries: [{ path: "example.ts", name: "example.ts", kind: "file", byte_size: editorContent.length, editable_candidate: true }] };
  },
  getAgentWorkspaceFile: async () => editorFile(),
};

const writeFailureEditorTransport: Pick<PromptEnhancerTransport, keyof typeof editorTransport> = {
  ...editorTransport,
  getAgentWorkspaceTree: async (id, path) => ({
    contract_version: "local-agent-workspace.v1", session_id: id, path, complete: true,
    entries: [{ path: "example.ts", name: "example.ts", kind: "file", byte_size: editorContent.length, editable_candidate: true }],
  }),
  getAgentWorkspaceFile: async () => editorFile(),
  applyAgentWorkspaceEdit: async () => {
    if (!editorWriteFailure) throw new Error("Write-failure fixture selected without a failure state.");
    throw new TransportError("EXAMPLE_PRIVATE_WORKSPACE_CANARY", editorWriteFailure.status, editorWriteFailure.reason);
  },
};

const liveTimeline: SessionTimeline = {
  contract_version: "session-timeline.v1", session_id: SYNTHETIC_QUALITY_SESSION_ID,
  project_id: SYNTHETIC_QUALITY_PROJECT_ID, provider: "codex", project_display_name: "Example project", session_display_name: "Example timeline",
  started_at: at, ended_at: "2040-01-01T00:10:00Z", events_complete: true, truncated: false,
  turns: [{ index: 0, started_at: at, ended_at: "2040-01-01T00:04:00Z" }],
  tools: [{ started_at: "2040-01-01T00:01:00Z", ended_at: "2040-01-01T00:02:00Z", category: "file_write", success: true, duration_ms: 60_000, verification: false }],
  markers: [], usage: { requests: 0, input_tokens: null, output_tokens: null, cached_input_tokens: null },
  counts: { events: 4, turns: 1, tools: 1, verifications_passed: 0, verifications_failed: 0, verifications_unknown: 0, tool_errors: 0 },
};
const liveTransport = { ...createSyntheticTransport(), getSessionTimeline: async () => liveTimeline };
const radarMetricRows = [
  ["prompt.task_definition_coverage", 0.92], ["prompt.problem_evidence_quality", 0.78],
  ["prompt.context_sufficiency", 0.86], ["prompt.constraint_precision", 0.74],
  ["prompt.acceptance_testability", 0.88], ["prompt.deliverable_contract", 0.81],
  ["collaboration.ambiguity_resolution", 0.69], ["logic.requirement_action_traceability", 0.84],
  ["logic.open_loop_closure", 0.76], ["outcome.first_pass_verification", 0.91],
  ["outcome.verification_strategy_adequacy", 0.83], ["outcome.agent_claim_grounding", 0.89],
].map(([metric_key, numeric_value]) => ({ metric_key, numeric_value, value_state: "known" as const }));
const radarTransport = {
  ...createSyntheticTransport(),
  getSessionMetrics: async (sessionId: string) => ({ session_id: sessionId, metrics: radarMetricRows }),
};
const ensembleRun = checkpointRun("a".repeat(64), "a");
const ensembleHead = checkpointHead(ensembleRun, CHECKPOINT_SESSION_A, "a");
const ensembleTransport = {
  ...createSyntheticTransport(),
  getActiveModelEnsembleCanonicalHead: async () => ensembleHead,
  getModelEnsembleSnapshot: async () => ensembleRun,
  getModelEnsembleTrajectory: async () => checkpointTrajectory(ensembleRun, ensembleHead.watch.watch_id, "b".repeat(64)),
};
const scaleTimelineBase = Date.parse(at);
const scaleTimeline: SessionTimeline = {
  ...liveTimeline,
  counts: { events: 6_000, turns: 2_000, tools: 2_000, verifications_passed: 1_000, verifications_failed: 0, verifications_unknown: 0, tool_errors: 0 },
  ended_at: new Date(scaleTimelineBase + 2_000_000).toISOString(),
  markers: Array.from({ length: 2_000 }, (_, index) => ({
    at: new Date(scaleTimelineBase + index * 1_000).toISOString(),
    kind: "compaction" as const,
  })),
  tools: Array.from({ length: 2_000 }, (_, index) => ({
    category: index % 2 === 0 ? "test" as const : "file_read" as const,
    duration_ms: 500,
    ended_at: new Date(scaleTimelineBase + index * 1_000 + 750).toISOString(),
    started_at: new Date(scaleTimelineBase + index * 1_000 + 250).toISOString(),
    success: true,
    verification: index % 2 === 0,
  })),
  turns: Array.from({ length: 2_000 }, (_, index) => ({
    ended_at: new Date(scaleTimelineBase + index * 1_000 + 500).toISOString(),
    index,
    started_at: new Date(scaleTimelineBase + index * 1_000).toISOString(),
  })),
};
const scaleTimelineTransport = { getSessionTimeline: async () => scaleTimeline };

const judgeSessionId = "e".repeat(64);
const judgeProtocol = "judge-v4-complete-json-anchor-15k";
const judgeQuestions = {
  "prompt.task_definition_coverage": "Did the example request state its target?",
  "prompt.context_sufficiency": "Did the example supply enough context?",
  "outcome.verification_strategy_adequacy": "Is there evidence of appropriate checks?",
};
let judgeAttempts = 0;
let interpretationAttempts = 0;
let currentJudgmentProtocol = false;
function judgeView(): SessionJudgments {
  return {
    contract_version: "model-judge.v1", session_id: judgeSessionId, active_model_alias: modelAlias,
    questions: judgeQuestions, accepted_prompt_versions: [judgeProtocol], accepted_case_version: "calibration-case.v1",
    judgments: Object.keys(judgeQuestions).map((metric_key) => ({
      session_id: judgeSessionId, metric_key, label: "high", model_alias: modelAlias,
      model_identity: "example-model.gguf", window_fingerprint: "f".repeat(64), judged_at: at,
      prompt_version: currentJudgmentProtocol ? judgeProtocol : "judge-v3-untrusted-json-anchor-15k",
      case_fingerprint: currentJudgmentProtocol ? "d".repeat(64) : null,
      case_version: currentJudgmentProtocol ? "calibration-case.v1" : null,
    })),
    caveat: "Synthetic model labels are never product metrics. Historical protocols are retained but excluded from current agreement.",
  };
}
const judgeTransport: Pick<PromptEnhancerTransport, "getModelJudgments" | "judgeSessionWithModel" | "interpretSessionWithModel"> = {
  async getModelJudgments() { return judgeView(); },
  async judgeSessionWithModel() {
    if (++judgeAttempts === 1) throw new TransportError("Synthetic invalid completion", 502, "model_reply_invalid");
    currentJudgmentProtocol = true;
    return { contract_version: "model-judge.v1", session_id: judgeSessionId, model_alias: modelAlias, judgments: judgeView().judgments, raw_valid: true };
  },
  async interpretSessionWithModel() {
    if (++interpretationAttempts > 1) throw new TransportError("Synthetic invalid completion", 502, "model_reply_invalid");
    return {
      contract_version: "model-judge.v1", session_id: judgeSessionId, model_alias: modelAlias,
      prompt_version: "interpret-v2-complete-json", summary: "The example request names its target.",
      strengths: ["The example module is named."], improvements: ["State the expected result."],
      reframed_prompt: "Review the example module and report which checks ran.", metrics_seen: 3,
      caveat: "Synthetic model interpretation, not a measurement; unknown metrics remain unknown.",
    };
  },
};

function ModelStatusRaceControls() {
  const [held, setHeld] = useState(false);
  return <section aria-label="Synthetic status timing controls" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
    <button className="button button--ghost" disabled={held} type="button" onClick={() => {
      holdNextModelRead = true;
      window.dispatchEvent(new Event("focus"));
      setHeld(true);
    }}>Hold older model status</button>
    <button className="button button--ghost" disabled={!held} type="button" onClick={() => {
      const pending = heldModelRead;
      heldModelRead = null;
      pending?.resolve(pending.snapshot);
      setHeld(false);
    }}>Release older model status</button>
  </section>;
}

function AgentStoppingControls() {
  const [released, setReleased] = useState(false);
  return <section aria-label="Synthetic cancellation timing controls">
    <p>Fictional delayed response. Stop waits for this test gate; no model is loaded.</p>
    <button className="button button--ghost" disabled={released} type="button" onClick={() => {
      if (!sessions[0]?.stopping) return;
      const receipt = exampleAgentTurn({
        turn_number: sessions[0].turns, model_alias: modelAlias, status: "stopped", reason: "stop_requested",
        time_to_first_text_ms: null, tools_requested: 0, tools_succeeded: 0, writes: [],
        usage: { contract_version: "agent-token-usage.v1", source: "runtime_reported", state: "unavailable", model_requests: 1,
          reported_requests: 0, prompt_tokens: null, completion_tokens: null, total_tokens: null, cached_prompt_tokens: null, reasoning_tokens: null },
      });
      events.push(event("done", { turn_id: receipt.turn_id, turn_summary: receipt }));
      sessions = [{ ...sessions[0], running: false, stopping: false, last_seq: events.length }];
      cancelledExampleReleased = true;
      setReleased(true);
    }}>Finish cancelled example request</button>
  </section>;
}

function AgentCommandControls() {
  const [stage, setStage] = useState(0);
  return <section aria-label="Synthetic command cleanup controls" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
    <p>In-memory timing controls only. No command runs and no native approval is granted.</p>
    <button className="button button--ghost" disabled={stage !== 0} type="button" onClick={() => {
      const receipt = exampleAgentTurn();
      events.push(event("tool_call", { turn_id: receipt.turn_id, tool: "run_command", call_id: "example-command", arguments: { command: "example-check" } }));
      sessions = [{ ...sessions[0], running: true, last_seq: events.length }];
      setStage(1);
    }}>Start fictional command</button>
    <button className="button button--ghost" disabled={stage !== 1} type="button" onClick={() => {
      if (!sessions[0]?.stopping) return;
      const receipt = exampleAgentTurn({
        model_alias: modelAlias, status: "failed", reason: "command_cleanup_unconfirmed",
        tools_requested: 1, tools_succeeded: 0, tools_unverified: 1, untracked_command_calls: 1, writes: [],
      });
      events.push(event("tool_result", { turn_id: receipt.turn_id, tool: "run_command", call_id: "example-command", ok: false, tool_state: "unverified", text: "Command cleanup could not be confirmed." }));
      events.push(event("done", { turn_id: receipt.turn_id, turn_summary: receipt }));
      sessions = [{ ...sessions[0], running: false, stopping: false, closing: true, cleanup_unconfirmed: true, last_seq: events.length }];
      commandCleanupReported = true;
      setStage(2);
    }}>Report example cleanup failure</button>
    <button className="button button--ghost" disabled={stage !== 2} type="button" onClick={() => {
      // An older snapshot is not permission to clear a previously seen quarantine.
      sessions = [{ ...sessions[0], closing: false, cleanup_unconfirmed: false }];
      olderCommandSnapshotRead = () => setStage(4);
      setStage(3);
    }}>Publish older ready snapshot</button>
    {stage === 4 && <p role="status">Older fictional ready snapshot delivered.</p>}
  </section>;
}

const calibrationCaseTransport = {
  async reviewCalibrationCase(sid: string, budget: 6000 | 15000) {
    return exampleCalibrationReview(sid, {
      provider: "claude_code", case_fingerprint: (budget === 15000 ? "d" : "e").repeat(64),
      earlier_records_omitted: budget === 6000,
      records: [
        { sequence: 0, role: "user", content: "Review the fictional example package. Done when the example checks pass." },
        { sequence: 2, role: "agent", content: "Synthetic reported result; not proof of success. " + "example".repeat(80) },
      ],
    });
  },
};
function CalibrationCaseFixture() {
  const [review, setReview] = useState<CalibrationReview | null>(null);
  return <div className="calibration">
    <h1>Calibration review fixture</h1>
    <CalibrationCasePane sessionId={"a".repeat(64)} provider="claude_code" transport={calibrationCaseTransport} disabled={false} onReviewChange={setReview} />
    <p role="status">{review ? "Reviewed-case receipt available. No rating has been submitted." : "No current reviewed-case receipt."}</p>
  </div>;
}

const artifactViewerTransport: Pick<
  PromptEnhancerTransport,
  "exportAgentArtifact" | "getAgentArtifact" | "getAgentArtifactContent" | "getAgentArtifactDocumentPreview" | "removeAgentArtifact" | "updateAgentArtifact"
> = {
  async getAgentArtifact(projectId, id, artifactId) {
    const candidate = [viewerImage, viewerPdf, viewerDocument].find((artifact) => artifact.artifact_id === artifactId);
    if (projectId !== viewerProjectId || id !== viewerSessionId || candidate === undefined) {
      throw new TransportError("Synthetic artifact is unavailable", 404);
    }
    return candidate;
  },
  async exportAgentArtifact(projectId, id, artifactId, request) {
    const candidate = [viewerImage, viewerPdf, viewerDocument].find((artifact) => artifact.artifact_id === artifactId);
    if (
      projectId !== viewerProjectId
      || id !== viewerSessionId
      || candidate === undefined
      || request.expected_revision !== candidate.revision
    ) throw new TransportError("Synthetic artifact export is unavailable", 409);
    return artifactLineageExport(candidate, request.version_id);
  },
  async updateAgentArtifact(projectId, id, artifactId) {
    const candidate = [viewerImage, viewerPdf, viewerDocument].find((artifact) => artifact.artifact_id === artifactId);
    if (projectId !== viewerProjectId || id !== viewerSessionId || candidate === undefined) {
      throw new TransportError("Synthetic artifact is unavailable", 404);
    }
    return candidate;
  },
  async removeAgentArtifact(projectId, id, artifactId) {
    const candidate = [viewerImage, viewerPdf, viewerDocument].find((artifact) => artifact.artifact_id === artifactId);
    if (projectId !== viewerProjectId || id !== viewerSessionId || candidate === undefined) {
      throw new TransportError("Synthetic artifact is unavailable", 404);
    }
    return candidate;
  },
  async getAgentArtifactDocumentPreview(projectId, id, artifactId, version) {
    if (
      projectId !== viewerProjectId
      || id !== viewerSessionId
      || artifactId !== viewerDocument.artifact_id
      || version.version_id !== viewerDocument.latest_version.version_id
    ) throw new TransportError("Synthetic document projection is unavailable", 404);
    return {
      contract_version: "agent-document-preview.v1",
      project_id: viewerProjectId,
      session_id: viewerSessionId,
      artifact_id: viewerDocument.artifact_id,
      version_id: viewerDocument.latest_version.version_id,
      source_sha256: viewerDocument.latest_version.sha256,
      source_byte_size: viewerDocument.latest_version.byte_size,
      format: "xlsx",
      sections: [
        {
          index: 1,
          kind: "sheet",
          title: "Overview",
          paragraphs: [],
          rows: [{ cells: ["Metric", "Synthetic value"] }],
          truncated: false,
        },
        {
          index: 2,
          kind: "sheet",
          title: "Budget",
          paragraphs: [],
          rows: [{ cells: ["Fictional total", "42"] }],
          truncated: true,
        },
      ],
      omitted_features: ["external_links", "macros"],
      truncated: true,
    };
  },
  async getAgentArtifactContent(projectId, id, artifactId, versionId, download) {
    const candidate = [viewerImage, viewerPdf, viewerDocument].find((artifact) => (
      artifact.artifact_id === artifactId && artifact.latest_version.version_id === versionId
    ));
    if (projectId !== viewerProjectId || id !== viewerSessionId || candidate === undefined) {
      throw new TransportError("Synthetic artifact content is unavailable", 404);
    }
    const payload = candidate.kind === "image"
      ? viewerImageBytes
      : candidate.kind === "pdf"
        ? viewerPdfBytes
        : new Uint8Array(candidate.latest_version.byte_size);
    const contentType = download ? "application/octet-stream" : candidate.latest_version.media_type;
    return {
      blob: new Blob([payload], { type: contentType }),
      contentType,
      filename: `agent-artifact-${candidate.artifact_id.slice(0, 8)}.${candidate.kind === "image" ? "png" : candidate.kind === "pdf" ? "pdf" : "xlsx"}`,
      byteSize: payload.byteLength,
    };
  },
};

function ArtifactViewerFixture() {
  return <section aria-labelledby="artifact-viewer-fixture-title">
    <h1 id="artifact-viewer-fixture-title">Synthetic artifact viewer fixture</h1>
    <p>Validated local image, PDF, and inert Office projections only. No file, model, network request or GPU is used.</p>
    <AgentArtifactsPanel
      artifacts={[viewerImage, viewerPdf, viewerDocument]}
      counts={{ active: 3, archived: 0, removed: 0, total: 3 }}
      error=""
      loading={false}
      onRefresh={() => undefined}
      onViewChange={() => undefined}
      projectId={viewerProjectId}
      sessionId={viewerSessionId}
      transport={artifactViewerTransport}
      userPresenceAvailable
      view="active"
    />
  </section>;
}

function ArtifactLifecycleFixture() {
  const [artifact, setArtifact] = useState<AgentArtifact>(lifecycleArtifact);
  const [view, setView] = useState<"active" | "archived" | "removed">("active");
  const artifactRef = useRef(artifact);
  artifactRef.current = artifact;
  const lifecycleTransport = useMemo<Pick<
    PromptEnhancerTransport,
    "exportAgentArtifact" | "getAgentArtifact" | "getAgentArtifactContent" | "removeAgentArtifact" | "updateAgentArtifact"
  >>(() => ({
    async getAgentArtifact(projectId, id, artifactId) {
      const current = artifactRef.current;
      if (
        projectId !== viewerProjectId
        || id !== viewerSessionId
        || artifactId !== current.artifact_id
        || current.lifecycle_state === "removed"
      ) throw new TransportError("Synthetic artifact is unavailable", 410, "agent_artifact_removed");
      return { ...current, versions: [current.latest_version] };
    },
    async exportAgentArtifact(projectId, id, artifactId, request) {
      const current = artifactRef.current;
      if (
        projectId !== viewerProjectId
        || id !== viewerSessionId
        || artifactId !== current.artifact_id
        || request.expected_revision !== current.revision
      ) throw new TransportError("Synthetic artifact export is unavailable", 409);
      return artifactLineageExport(
        { ...current, versions: [current.latest_version] },
        request.version_id,
      );
    },
    async getAgentArtifactContent() {
      throw new TransportError("Synthetic lifecycle bytes are intentionally unavailable", 404);
    },
    async updateAgentArtifact(projectId, id, artifactId, request) {
      const current = artifactRef.current;
      if (projectId !== viewerProjectId || id !== viewerSessionId || artifactId !== current.artifact_id) {
        throw new TransportError("Synthetic artifact is unavailable", 404);
      }
      if (request.expected_revision !== current.revision) {
        throw new TransportError("Synthetic artifact changed", 409, "agent_artifact_revision_conflict");
      }
      const nextRevision = current.revision + 1;
      let next: AgentArtifact;
      if (request.operation === "rename") {
        next = { ...current, title: request.title ?? current.title, revision: nextRevision };
      } else if (request.operation === "archive" && current.lifecycle_state === "active") {
        next = {
          ...current,
          lifecycle_state: "archived",
          archived_at: at,
          removed_at: null,
          revision: nextRevision,
        };
      } else if (request.operation === "restore" && current.lifecycle_state === "archived") {
        next = {
          ...current,
          lifecycle_state: "active",
          archived_at: null,
          removed_at: null,
          revision: nextRevision,
        };
      } else if (request.operation === "recover" && current.lifecycle_state === "removed") {
        next = {
          ...current,
          lifecycle_state: "archived",
          removed_at: null,
          revision: nextRevision,
        };
      } else {
        throw new TransportError("Synthetic lifecycle mismatch", 409, "agent_artifact_state_conflict");
      }
      artifactRef.current = next;
      setArtifact(next);
      return next;
    },
    async removeAgentArtifact(projectId, id, artifactId, request) {
      const current = artifactRef.current;
      if (
        projectId !== viewerProjectId
        || id !== viewerSessionId
        || artifactId !== current.artifact_id
        || request.expected_revision !== current.revision
        || current.lifecycle_state !== "archived"
      ) throw new TransportError("Synthetic lifecycle mismatch", 409, "agent_artifact_state_conflict");
      const next: AgentArtifact = {
        ...current,
        lifecycle_state: "removed",
        removed_at: at,
        revision: current.revision + 1,
      };
      artifactRef.current = next;
      setArtifact(next);
      return next;
    },
  }), []);
  const counts = {
    active: artifact.lifecycle_state === "active" ? 1 : 0,
    archived: artifact.lifecycle_state === "archived" ? 1 : 0,
    removed: artifact.lifecycle_state === "removed" ? 1 : 0,
    total: 1,
  };

  return (
    <section aria-labelledby="artifact-lifecycle-fixture-title">
      <h1 id="artifact-lifecycle-fixture-title">Synthetic artifact lifecycle fixture</h1>
      <p>In-memory lifecycle validation only. No file, provider session, process, network request, native prompt, or GPU is used.</p>
      <AgentArtifactsPanel
        artifacts={artifact.lifecycle_state === view ? [artifact] : []}
        counts={counts}
        error=""
        loading={false}
        onRefresh={() => undefined}
        onViewChange={setView}
        projectId={viewerProjectId}
        sessionId={viewerSessionId}
        transport={lifecycleTransport}
        userPresenceAvailable
        view={view}
      />
    </section>
  );
}

const artifactCapturePreview: AgentArtifactCapturePreview = {
  contract_version: "agent-artifact-capture-preview.v1",
  project_id: captureProjectId,
  session_id: captureSessionId,
  path: captureArtifact.path,
  title: captureArtifact.title,
  kind: "pdf",
  media_type: "application/pdf",
  preview_kind: "pdf",
  sha256: captureArtifact.latest_version.sha256,
  byte_size: captureArtifact.latest_version.byte_size,
  requires_native_confirmation: true,
  file_content_included: false,
};

const artifactCaptureTransport = {
  async getAgentWorkspaceTree(id: string, path: string) {
    return {
      contract_version: "local-agent-workspace.v1" as const,
      session_id: id,
      path,
      entries: [{
        path: captureArtifact.path,
        name: "synthetic-generated.pdf",
        kind: "file" as const,
        byte_size: viewerPdfBytes.byteLength,
        editable_candidate: false,
      }],
      complete: true,
    };
  },
  getAgentWorkspaceFile: unavailable,
  previewAgentWorkspaceEdit: unavailable,
  applyAgentWorkspaceEdit: unavailable,
  async previewAgentArtifactCapture(projectId: string, id: string, request: { path: string; title?: string | null }) {
    if (
      projectId !== captureProjectId
      || id !== captureSessionId
      || request.path !== captureArtifact.path
    ) return unavailable();
    return {
      ...artifactCapturePreview,
      title: request.title ?? artifactCapturePreview.title,
    };
  },
  async captureAgentArtifact(projectId: string, id: string, request: {
    path: string;
    title?: string | null;
    expected_sha256: string;
    expected_byte_size: number;
  }) {
    if (
      projectId !== captureProjectId
      || id !== captureSessionId
      || request.path !== artifactCapturePreview.path
      || request.title !== artifactCapturePreview.title
      || request.expected_sha256 !== artifactCapturePreview.sha256
      || request.expected_byte_size !== artifactCapturePreview.byte_size
    ) throw new TransportError("Synthetic artifact revision changed", 409, "agent_artifact_revision_changed");
    return captureArtifact;
  },
  async getAgentArtifact(projectId: string, id: string, artifactId: string) {
    if (
      projectId !== captureProjectId
      || id !== captureSessionId
      || artifactId !== captureArtifact.artifact_id
    ) return unavailable();
    return captureArtifact;
  },
  async exportAgentArtifact(
    projectId: string,
    id: string,
    artifactId: string,
    request: { expected_revision: number; version_id: string },
  ) {
    if (
      projectId !== captureProjectId
      || id !== captureSessionId
      || artifactId !== captureArtifact.artifact_id
      || request.expected_revision !== captureArtifact.revision
    ) return unavailable();
    return artifactLineageExport(captureArtifact, request.version_id);
  },
  async updateAgentArtifact() {
    return captureArtifact;
  },
  async removeAgentArtifact() {
    return captureArtifact;
  },
  async getAgentArtifactContent(
    projectId: string,
    id: string,
    artifactId: string,
    versionId: string,
    download: boolean,
  ) {
    if (
      projectId !== captureProjectId
      || id !== captureSessionId
      || artifactId !== captureArtifact.artifact_id
      || versionId !== captureArtifact.latest_version.version_id
    ) return unavailable();
    const contentType = download ? "application/octet-stream" : "application/pdf";
    return {
      blob: new Blob([viewerPdfBytes], { type: contentType }),
      contentType,
      filename: "agent-artifact-11111111.pdf",
      byteSize: viewerPdfBytes.byteLength,
    };
  },
} satisfies Pick<
  PromptEnhancerTransport,
  | "getAgentWorkspaceTree"
  | "getAgentWorkspaceFile"
  | "previewAgentWorkspaceEdit"
  | "applyAgentWorkspaceEdit"
  | "previewAgentArtifactCapture"
  | "captureAgentArtifact"
  | "exportAgentArtifact"
  | "getAgentArtifact"
  | "updateAgentArtifact"
  | "removeAgentArtifact"
  | "getAgentArtifactContent"
>;

function ArtifactCaptureWorkflowFixture() {
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  return (
    <section aria-labelledby="artifact-capture-fixture-title" style={{ display: "grid", gap: 16 }}>
      <header>
        <h1 id="artifact-capture-fixture-title">Generated output capture fixture</h1>
        <p>Metadata review and synthetic native capture only. No real file, model, process, network request, or GPU is used.</p>
      </header>
      <AgentWorkspacePane
        onArtifactCaptured={() => setArtifacts([captureArtifact])}
        pendingWrite={null}
        projectId={captureProjectId}
        sessionId={captureSessionId}
        transport={artifactCaptureTransport}
        userPresenceAvailable
      />
      {artifacts.length > 0 && (
        <AgentArtifactsPanel
          artifacts={artifacts}
          counts={{ active: artifacts.length, archived: 0, removed: 0, total: artifacts.length }}
          error=""
          loading={false}
          onRefresh={() => undefined}
          onViewChange={() => undefined}
          projectId={captureProjectId}
          sessionId={captureSessionId}
          transport={artifactCaptureTransport}
          userPresenceAvailable
          view="active"
        />
      )}
    </section>
  );
}

bootstrapTheme();
const fixtureRoot = createRoot(document.getElementById("root")!);
fixtureRoot.render(
  <main style={{ padding: agentStressFixture ? 0 : 24, maxWidth: agentStressFixture ? "none" : 1440, margin: "0 auto" }}>
    <p className="eyebrow">Synthetic workflow fixture — no files, models or GPU used</p>
    {modelRaceFixture && <ModelStatusRaceControls />}
    {agentStoppingFixture && <AgentStoppingControls />}
    {agentCommandFixture && <AgentCommandControls />}
    {(panel === "models" || modelCompletionFixture) && <LocalModelsPage transport={transport} />}
    {(panel === "agent" || closingFixture || modelRaceFixture || agentCompletionFixture || agentWorkspaceFixture || agentMcpStoreFixture || agentMcpProjectToolsFixture || agentMcpCallFixture || agentHistoryFixture || agentStressFixture || agentStoppingFixture || agentCommandFixture || agentControllerOwnershipFixture) && <AgentPage transport={transport} sessionId={agentWindow ? sessionId : undefined} windowMode={agentWindow} />}
    {panel === "editor" && <AgentWorkspacePane pendingWrite={null} sessionId={sessionId} transport={editorTransport} userPresenceAvailable />}
    {panel === "editor-inspection" && <AgentWorkspacePane pendingWrite={null} sessionId={sessionId} transport={inspectionEditorTransport} userPresenceAvailable />}
    {editorWriteFailure && <AgentWorkspacePane pendingWrite={null} sessionId={sessionId} transport={writeFailureEditorTransport} userPresenceAvailable />}
    {panel === "live" && <div data-testid="live-tour"><p className="eyebrow" data-testid="synthetic-demo-badge">Synthetic demo · in-memory fixture</p><LiveMiniWindow projectId={SYNTHETIC_QUALITY_PROJECT_ID} sessionId={SYNTHETIC_QUALITY_SESSION_ID} transport={liveTransport} /></div>}
    {panel === "radar" && <section data-testid="radar-tour"><p className="eyebrow">Synthetic demo · standalone measured session radar</p><SessionRadarCard sessionId={SYNTHETIC_QUALITY_SESSION_ID} transport={radarTransport} /></section>}
    {panel === "ensemble" && <section data-testid="ensemble-tour"><p className="eyebrow">Synthetic demo · model ensemble live watch</p><ModelEnsembleOverlay transport={ensembleTransport} /></section>}
    {panel === "scale-timeline" && <SessionTimelinePane sessionId={SYNTHETIC_QUALITY_SESSION_ID} transport={scaleTimelineTransport} />}
    {panel === "team-folders" && <TeamFoldersPanel transport={transport} />}
    {panel === "prompt-check" && <PromptCheckPage transport={transport} navigate={() => undefined} />}
    {panel === "judge-completion" && <ModelJudgePane sessionId={judgeSessionId} transport={judgeTransport} />}
    {panel === "calibration-case" && <CalibrationCaseFixture />}
    {panel === "model-job-status" && <ModelJobStatusFixture windowMode={agentWindow} />}
    {artifactViewerFixture && <ArtifactViewerFixture />}
    {artifactCaptureWorkflowFixture && <ArtifactCaptureWorkflowFixture />}
    {artifactLifecycleFixture && <ArtifactLifecycleFixture />}
  </main>,
);

if (import.meta.hot) {
  import.meta.hot.dispose(() => fixtureRoot.unmount());
}
