import { readLocalModelChat } from "./localModelChatStream";
import { parseLocalModelPlacement } from "./localModelPlacementContract";
import type {
  InferenceCatalog, InferencePreview, ManualAnalysisResult, PendingInferenceReview,
  AnalysisJobIdentity,
  AnalysisJobPage,
  AnalysisJobRecord,
  AnalysisJobState,
  AnalysisRunListResponse,
  AnalysisRunResponse,
  AgentMetricEvidenceImport,
  AgentMetricEvidencePreview,
  AutomationGrantCreateRequest,
  AutomationGrantRecord,
  AutomationGrantScope,
  AutomationPollResult,
  AutomationResourcePolicy,
  CandidateListResponse,
  CandidateStatusFilter,
  CodexAnalysisSelection,
  CodexIngestionReport,
  CodexLabelEnrichmentReport,
  CodexLocalSourceStatus,
  CodexSessionListResponse,
  DisplayLabelEntityKind,
  DeclaredTaskProfileCommand,
  ManualDisplayLabelResult,
  MetricCoverageReport,
  ModelLabInventory,
  ModelEnsembleCanonicalHead,
  ModelEnsembleAttemptSnapshot,
  ModelEnsembleRequest,
  ModelPredictiveMetricDetail,
  ModelEnsembleTrajectoryPage,
  ModelEnsembleWatchRequest,
  ModelLinkAnnotation,
  ModelLinkAnnotationRequest,
  ModelLinkExperiment,
  ModelLinkExperimentOutcome,
  ModelLinkExperimentRequest,
  ProjectQualityAggregate,
  ProjectQualityAggregateRequest,
  ProjectSessionListResponse,
  Provider,
  ProviderCapabilityReport,
  ProviderCompatibilityProvider,
  ProviderCompatibilityStatus,
  MetricEvidenceCapability,
  MetricLifecycleDecisionRequest,
  MetricLifecycleProposal,
  RequirementPlanProposal,
  RequirementActionProposal,
  MetricReadiness,
  MetricReadinessAction,
  ReviewCommand,
  SessionAnalysisRunResponse,
  SessionCoachingProjection,
  SessionMetricResponse,
  SessionMetricReadinessReport,
  SessionQualityAnalysisOutcome,
  SessionQualityAnalysisPreview,
  SessionQualityAnalysisPreviewApprovalRequest,
  SessionQualityAnalysisPreviewRequest,
  SessionQualityAnalysisRequest,
  SessionTextAnalysisCapability,
  SessionQualityAggregate,
  SessionQualityAggregateRequest,
  TaskRevisionListResponse,
  TaskRevisionResponse,
  TaskLifecycleState,
  TaskAnalysisResponse,
  TaskReviewResponse,
  TextAnalysisResearchCatalog,
  TextAnalysisPresetId,
  ClaudeCodeLocalSourceStatus,
  IngestionReport,
  SessionTranscript,
  OnboardingAccept,
  OnboardingResult,
  OnboardingStatus,
  CalibrationExport,
  CalibrationProgress,
  CalibrationRating,
  CalibrationSample,
  CalibrationReview,
  SessionTimeline,
  ProjectTimeline,
  LocalModelsOverview,
  LocalModelStatus,
  LocalModelRecord,
  LocalModelChatRequest,
  LocalRuntimeCoordinatorStatus,
  LocalModelCompatibilityCatalog,
  DownloadStatus,
  RemoteRepoFiles,
  ScanFolderResult,
  JudgeOutcome,
  JudgeSweepStatus,
  JudgeAgreementReport,
  AnnotationAllowance,
  FolderSyncReport,
  PeerLink,
  PeerLinkList,
  SharedFolder,
  SharedFolderList,
  AnnotationMetaprompt,
  RemoteAnnotationDisclosure,
  RemoteAnnotationResult,
  SessionJudgments,
  SessionInterpretation,
  PromptCheckRequest,
  PromptCheckConfiguration,
  PromptCheckPreview,
  PromptCheckResult,
  PromptCheckRecord,
  PromptCheckHistory,
  AgentOrchestrationManifest,
  AgentHardeningSnapshot,
  AgentNativeAcceptanceStartReceipt,
  AgentSettings,
  AgentSessionView,
  AgentSessionContextStatus,
  AgentEvents,
  AgentCatalogQuery,
  AgentCatalogPageQuery,
  AgentCatalogSessionQuery,
  AgentCatalogSessionPageQuery,
  AgentProject,
  AgentProjectList,
  AgentProjectPage,
  AgentCatalogSession,
  AgentCatalogSessionList,
  AgentCatalogSessionPage,
  AgentHistoryExportRequest,
  AgentSessionForkReceipt,
  CreateAgentProject,
  UpdateAgentProject,
  UpdateAgentCatalogSession,
  AgentHistoryExport,
  ResumeAgentSession,
  RevalidateAgentAuthority,
  AgentArtifactContent,
  AgentArtifactCapturePreview,
  AgentArtifact,
  AgentArtifactDetail,
  AgentArtifactExport,
  AgentArtifactList,
  AgentArtifactListView,
  AgentArtifactPage,
  AgentArtifactPageQuery,
  AgentArtifactVersion,
  AgentDocumentPreview,
  CaptureAgentArtifact,
  ExportAgentArtifact,
  RemoveAgentArtifact,
  UpdateAgentArtifact,
  PreviewAgentArtifactCapture,
  AgentAttachment,
  AgentAttachmentContent,
  AgentAttachmentList,
  AgentAttachmentUpload,
  AgentMessageSearchRequest,
  AgentMessageSearchResult,
  WorkspaceFolderPick,
  WorkspaceFolderPickerCapability,
  ApplicationUpdateAction,
  ApplicationUpdateMutationRequest,
  ApplicationUpdateStatus,
} from "./contracts";
import {
  AgentOrchestrationPayloadError,
  parseAgentOrchestrationManifest,
} from "./agentOrchestrationContract";
import {
  AgentHardeningPayloadError,
  parseAgentHardeningSnapshot,
} from "./agentHardeningContract";
import {
  AgentMcpConnectionPayloadError,
  parseAgentControllerOwnershipReleaseReceipt,
  parseAgentMcpClientSetup,
  parseAgentMcpConnection,
  parseAgentMcpConnectionCredential,
  parseAgentMcpConnectionList,
} from "./agentMcpConnectionContract";
import {
  isSafeMcpRegistryText,
  McpRegistryCatalogPayloadError,
  parseMcpRegistryCatalog,
} from "./mcpRegistryCatalogContract";
import {
  McpRegistryServerReviewPayloadError,
  parseMcpRegistryServerReview,
} from "./mcpRegistryServerReviewContract";
import {
  McpManagedServerPayloadError,
  parseMcpManagedLifecyclePreview,
  parseMcpManagedLifecycleReceipt,
  parseMcpManagedLocalConfigurationInspectionPreview,
  parseMcpManagedLocalConfigurationInspectionReceipt,
  parseMcpManagedLocalCleanupPreview,
  parseMcpManagedLocalCleanupReceipt,
  parseMcpManagedLocalUpdatePreview,
  parseMcpManagedLocalUpdateReceipt,
  parseMcpManagedLocalRollbackPreview,
  parseMcpManagedLocalRollbackReceipt,
  parseMcpManagedLocalRollbackCleanupPreview,
  parseMcpManagedLocalRollbackCleanupReceipt,
  parseMcpManagedLocalOperationRecoveryPreview,
  parseMcpManagedLocalOperationRecoveryReceipt,
  parseMcpManagedProbeReceipt,
  parseMcpManagedServer,
  parseMcpManagedServerList,
  parseMcpManagedServerReceipt,
  parseMcpManagedToolSnapshot,
} from "./mcpManagedServerContract";
import {
  McpManagedRuntimePayloadError,
  parseMcpManagedHostStartPreview,
  parseMcpManagedHostStatus,
  parseMcpManagedProjectRuntime,
} from "./mcpManagedRuntimeContract";
import {
  AgentNativeAcceptancePayloadError,
  parseAgentNativeAcceptanceStartReceipt,
} from "./agentNativeAcceptanceContract";
import {
  AgentSessionContextPayloadError,
  parseAgentSessionContext,
} from "./agentSessionContextContract";
import {
  LocalRuntimePayloadError,
  parseLocalRuntimeCoordinator,
} from "./localRuntimeContract";
import {
  LocalModelCompatibilityPayloadError,
  parseLocalModelCompatibility,
} from "./localModelCompatibilityContract";
import {
  AgentCatalogPayloadError,
  parseAgentCatalogSession,
  parseAgentCatalogSessionList,
  parseAgentCatalogSessionPage,
  parseAgentProject,
  parseAgentProjectList,
  parseAgentProjectPage,
  parseAgentSessionForkReceipt,
} from "./agentCatalogContract";
import {
  AgentWorkspacePayloadError,
  parseAgentWorkspaceApplyResult,
  parseAgentWorkspaceFile,
  parseAgentWorkspacePreview,
  parseAgentWorkspaceTree,
} from "./agentWorkspaceContract";
import {
  AgentWorkspaceSearchPayloadError,
  parseAgentWorkspaceSearchResult,
} from "./agentWorkspaceSearchContract";
import {
  AgentMessageSearchPayloadError,
  parseAgentMessageSearchResult,
} from "./agentMessageSearchContract";
import {
  AgentWorkspaceLifecyclePayloadError,
  parseAgentWorkspaceCreatePreview,
  parseAgentWorkspaceCreateResult,
  parseAgentWorkspaceDirectoryCreatePreview,
  parseAgentWorkspaceDirectoryCreateResult,
  parseAgentWorkspaceDirectoryMovePreview,
  parseAgentWorkspaceDirectoryMoveResult,
  parseAgentWorkspaceFileTrashPreview,
  parseAgentWorkspaceFileTrashResult,
  parseAgentWorkspaceMovePreview,
  parseAgentWorkspaceMoveResult,
} from "./agentWorkspaceLifecycleContract";
import {
  AgentWorkspaceDiscoveryPayloadError,
  parseAgentWorkspaceDiscovery,
} from "./agentWorkspaceDiscoveryContract";
import {
  AgentWorkspaceTransactionPayloadError,
  parseAgentWorkspaceTransactionPreview,
  parseAgentWorkspaceTransactionResult,
} from "./agentWorkspaceTransactionContract";
import {
  AgentChangeSetPayloadError,
  parseAgentChangeDiff,
  parseAgentChangeSet,
} from "./agentChangeSetContract";
import {
  AgentChangeRestorePayloadError,
  parseAgentChangeRestorePreview,
  parseAgentChangeRestoreResult,
} from "./agentChangeRestoreContract";
import {
  ModelEnsembleHeadPayloadError,
  parseModelEnsembleAttemptSnapshot,
  parseModelEnsembleCanonicalHead,
} from "./modelEnsembleHeadContract";
import {
  ModelEnsemblePayloadError,
  parseModelEnsembleOutcome,
  parseModelEnsembleRun,
} from "./modelEnsembleContract";
import {
  ModelEnsembleWatchPayloadError,
  parseModelEnsembleWatchSnapshot,
} from "./modelEnsembleWatchContract";
import {
  ModelEnsembleTrajectoryPayloadError,
  parseModelEnsembleTrajectoryPage,
} from "./modelEnsembleTrajectoryContract";
import {
  ModelPredictiveMetricDetailPayloadError,
  parseModelPredictiveMetricDetail,
} from "./modelPredictiveMetricDetailContract";
import {
  ModelCompatibilityPayloadError,
  parseModelCompatibilityCatalog,
} from "./modelCompatibilityContract";
import {
  MetricOperabilityDefinitionsOutOfDateError,
  MetricOperabilityPayloadError,
  parseMetricOperabilityCatalog,
} from "./metricOperabilityContract";
import { parseControlPlaneReadiness } from "./controlPlaneReadiness";
import { parseCandidateDecisionsResponse } from "./taskDecisionContract";
import { hasNativeUserPresenceBridge } from "../platform/nativeDesktopBridge";
import {
  ApplicationUpdatePayloadError,
  parseApplicationUpdateStatus,
} from "./applicationUpdateContract";
import {
  TaskLifecyclePayloadError,
  parseTaskLifecycleListResponse,
  parseTaskLifecycleMutationResponse,
  parseTaskLifecycleSnapshot,
} from "./taskLifecycleContract";
import {
  AgentMetricEvidencePayloadError,
  parseAgentMetricEvidenceImport,
  parseAgentMetricEvidencePreview,
  parseMetricLifecycleProposalPage,
  parseMetricLifecycleProposalOutcome,
} from "./agentMetricEvidenceContract";
import {
  REQUIREMENT_PLAN_MEDIA_TYPE,
  RequirementPlanEvidencePayloadError,
  parseRequirementPlanEvidenceContract,
  parseRequirementPlanEvidencePreview,
  parseRequirementPlanImport,
  parseRequirementPlanProposalOutcome,
  parseRequirementPlanProposalPage,
  parseRequirementPlanProposalReview,
} from "./requirementPlanEvidenceContract";
import {
  REQUIREMENT_ACTION_MEDIA_TYPE,
  RequirementActionEvidencePayloadError,
  parseRequirementActionEvidenceContract,
  parseRequirementActionEvidencePreview,
  parseRequirementActionImport,
  parseRequirementActionProposalOutcome,
  parseRequirementActionProposalPage,
  parseRequirementActionProposalReview,
  requirementActionUtcMicrosecondKey,
} from "./requirementActionEvidenceContract";
import {
  DeclaredTaskProfilePayloadError,
  parseDeclaredTaskProfileCurrent,
  parseDeclaredTaskProfileOutcome,
} from "./declaredTaskProfileContract";
import { AgentEventPayloadError, parseAgentEvents, parseAgentSession } from "./agentEventContract";
import { AgentHistoryPayloadError, parseAgentHistoryExport } from "./agentHistoryContract";
import {
  AgentArtifactPayloadError,
  parseAgentArtifact,
  parseAgentArtifactCapturePreview,
  parseAgentArtifactDetail,
  parseAgentArtifactExport,
  parseAgentDocumentPreview,
  parseAgentArtifactList,
  parseAgentArtifactPage,
} from "./agentArtifactContract";
import {
  AgentAttachmentPayloadError,
  parseAgentAttachment,
  parseAgentAttachmentDocumentPreview,
  parseAgentAttachmentList,
} from "./agentAttachmentContract";
import type {
  LocalRuntimeTransport,
  RuntimeHealth,
} from "../platform/runtimeMode";

type FetchLike = typeof globalThis.fetch;

const REQUIREMENT_PLAN_UTC_MICROSECOND_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/;

function requirementPlanUtcMicrosecondKey(value: string): string {
  const match = REQUIREMENT_PLAN_UTC_MICROSECOND_PATTERN.exec(value);
  if (match === null) throw new RequirementPlanEvidencePayloadError();
  return `${match[1]}${match[2]}${match[3]}${match[4]}${match[5]}${match[6]}`
    + (match[7] ?? "").padEnd(6, "0");
}

export class TransportError extends Error {
  readonly status: number;
  readonly reasonCode: SafeTransportReasonCode | null;

  constructor(
    message: string,
    status: number,
    reasonCode: SafeTransportReasonCode | null = null,
  ) {
    super(message);
    this.name = "TransportError";
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

function agentSessionResponse(value: unknown, expectedSessionId?: string): AgentSessionView {
  try {
    return parseAgentSession(value, expectedSessionId);
  } catch (error) {
    if (error instanceof AgentEventPayloadError) throw new TransportError("Local agent session response was invalid", 200);
    throw error;
  }
}

function agentSessionContextResponse(
  value: unknown,
  expectedSessionId: string,
): AgentSessionContextStatus {
  try {
    return parseAgentSessionContext(value, expectedSessionId);
  } catch (error) {
    if (error instanceof AgentSessionContextPayloadError) {
      throw new TransportError("Agent session context response was invalid", 200);
    }
    throw error;
  }
}

function agentProjectResponse(value: unknown, expectedProjectId?: string): AgentProject {
  try {
    const project = parseAgentProject(value);
    if (expectedProjectId !== undefined && project.project_id !== expectedProjectId) {
      throw new AgentCatalogPayloadError();
    }
    return project;
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent project response was invalid", 200);
    }
    throw error;
  }
}

function agentProjectListResponse(value: unknown): AgentProjectList {
  try {
    return parseAgentProjectList(value);
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent project list response was invalid", 200);
    }
    throw error;
  }
}

function agentProjectPageResponse(
  value: unknown,
  limit: number,
  offset: number,
  snapshot?: string,
): AgentProjectPage {
  try {
    return parseAgentProjectPage(value, limit, offset, snapshot);
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent project page response was invalid", 200);
    }
    throw error;
  }
}

function agentCatalogSessionResponse(
  value: unknown,
  expectedSessionId?: string,
  expectedProjectId?: string,
): AgentCatalogSession {
  try {
    return parseAgentCatalogSession(value, expectedSessionId, expectedProjectId);
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent catalog session response was invalid", 200);
    }
    throw error;
  }
}

function agentCatalogSessionListResponse(
  value: unknown,
  expectedProjectId?: string,
): AgentCatalogSessionList {
  try {
    return parseAgentCatalogSessionList(value, expectedProjectId);
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent catalog session list response was invalid", 200);
    }
    throw error;
  }
}

function agentCatalogSessionPageResponse(
  value: unknown,
  limit: number,
  offset: number,
  snapshot?: string,
  expectedProjectId?: string,
): AgentCatalogSessionPage {
  try {
    return parseAgentCatalogSessionPage(
      value,
      limit,
      offset,
      snapshot,
      expectedProjectId,
    );
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent catalog session page response was invalid", 200);
    }
    throw error;
  }
}

function agentMessageSearchResponse(value: unknown, request: AgentMessageSearchRequest): AgentMessageSearchResult {
  try {
    return parseAgentMessageSearchResult(value, request);
  } catch (error) {
    if (error instanceof AgentMessageSearchPayloadError) {
      throw new TransportError("Agent message search response was invalid", 200);
    }
    throw error;
  }
}

function agentSessionForkResponse(
  value: unknown,
  expectedRequestId: string,
  expectedSourceProjectId: string,
  expectedSourceSessionId: string,
): AgentSessionForkReceipt {
  try {
    const receipt = parseAgentSessionForkReceipt(value);
    const lineage = receipt.session.lineage;
    if (
      receipt.request_id !== expectedRequestId
      || lineage === null
      || lineage === undefined
      || lineage.source_project_id !== expectedSourceProjectId
      || lineage.source_session_id !== expectedSourceSessionId
    ) throw new AgentCatalogPayloadError();
    return receipt;
  } catch (error) {
    if (error instanceof AgentCatalogPayloadError) {
      throw new TransportError("Agent session fork response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactListResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  view: AgentArtifactListView,
): AgentArtifactList {
  try {
    return parseAgentArtifactList(value, projectId, sessionId, view);
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent artifact list response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactPageResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  query: Required<Pick<AgentArtifactPageQuery, "view" | "limit" | "offset">>
    & Pick<AgentArtifactPageQuery, "snapshot">,
): AgentArtifactPage {
  try {
    return parseAgentArtifactPage(
      value,
      projectId,
      sessionId,
      query.view,
      query.limit,
      query.offset,
      query.snapshot,
    );
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent artifact page response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  artifactId: string,
): AgentArtifact {
  try {
    return parseAgentArtifact(value, projectId, sessionId, artifactId);
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent artifact response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactDetailResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  artifactId?: string,
): AgentArtifactDetail {
  try {
    return parseAgentArtifactDetail(value, projectId, sessionId, artifactId);
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent artifact response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactExportResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  artifactId: string,
  request: ExportAgentArtifact,
): AgentArtifactExport {
  try {
    return parseAgentArtifactExport(
      value,
      projectId,
      sessionId,
      artifactId,
      request.expected_revision,
      request.version_id,
    );
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent artifact export response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactCapturePreviewResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  request: PreviewAgentArtifactCapture,
): AgentArtifactCapturePreview {
  try {
    return parseAgentArtifactCapturePreview(
      value,
      projectId,
      sessionId,
      request.path,
      request.title,
    );
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent artifact capture preview response was invalid", 200);
    }
    throw error;
  }
}

function agentArtifactDocumentPreviewResponse(
  value: unknown,
  projectId: string,
  sessionId: string,
  artifactId: string,
  version: AgentArtifactVersion,
): AgentDocumentPreview {
  try {
    return parseAgentDocumentPreview(
      value,
      projectId,
      sessionId,
      artifactId,
      version,
    );
  } catch (error) {
    if (error instanceof AgentArtifactPayloadError) {
      throw new TransportError("Agent document preview response was invalid", 200);
    }
    throw error;
  }
}

function localRuntimeResponse(value: unknown): LocalRuntimeCoordinatorStatus {
  try {
    return parseLocalRuntimeCoordinator(value);
  } catch (error) {
    if (error instanceof LocalRuntimePayloadError) {
      throw new TransportError("Local runtime response was invalid", 200);
    }
    throw error;
  }
}

function agentOrchestrationResponse(value: unknown): AgentOrchestrationManifest {
  try {
    return parseAgentOrchestrationManifest(value);
  } catch (error) {
    if (error instanceof AgentOrchestrationPayloadError) {
      throw new TransportError("Agent controller manifest was invalid", 200);
    }
    throw error;
  }
}

function agentHardeningResponse(value: unknown): AgentHardeningSnapshot {
  try {
    return parseAgentHardeningSnapshot(value);
  } catch (error) {
    if (error instanceof AgentHardeningPayloadError) {
      throw new TransportError("Agent hardening response was invalid", 200);
    }
    throw error;
  }
}

function agentNativeAcceptanceResponse(value: unknown): AgentNativeAcceptanceStartReceipt {
  try {
    return parseAgentNativeAcceptanceStartReceipt(value);
  } catch (error) {
    if (error instanceof AgentNativeAcceptancePayloadError) {
      throw new TransportError("Agent native acceptance response was invalid", 200);
    }
    throw error;
  }
}

function localModelCompatibilityResponse(value: unknown): LocalModelCompatibilityCatalog {
  try {
    return parseLocalModelCompatibility(value);
  } catch (error) {
    if (error instanceof LocalModelCompatibilityPayloadError) {
      throw new TransportError("Local model compatibility response was invalid", 200);
    }
    throw error;
  }
}

function agentCatalogQuery(query: AgentCatalogQuery = {}): string {
  const params = new URLSearchParams();
  if (query.search !== undefined) {
    if (Array.from(query.search).length > 120) {
      throw new TransportError("Agent catalog query was invalid", 422);
    }
    params.set("search", query.search);
  }
  if (query.includeArchived !== undefined) {
    params.set("include_archived", String(query.includeArchived));
  }
  if (query.limit !== undefined) {
    if (!Number.isInteger(query.limit) || query.limit < 1 || query.limit > 200) {
      throw new TransportError("Agent catalog query was invalid", 422);
    }
    params.set("limit", String(query.limit));
  }
  const encoded = params.toString();
  return encoded.length === 0 ? "" : `?${encoded}`;
}

interface PreparedCatalogPageQuery {
  encoded: string;
  limit: number;
  offset: number;
  snapshot?: string;
}

function agentCatalogPageQuery(
  query: AgentCatalogPageQuery = {},
  maximumOffset: number,
): PreparedCatalogPageQuery {
  const limit = query.limit ?? 100;
  const offset = query.offset ?? 0;
  if (
    (query.search !== undefined && Array.from(query.search).length > 120)
    || !Number.isInteger(limit) || limit < 1 || limit > 100
    || !Number.isInteger(offset) || offset < 0 || offset > maximumOffset
    || (query.snapshot !== undefined && !/^[0-9a-f]{64}$/u.test(query.snapshot))
    || (offset > 0 && query.snapshot === undefined)
  ) throw new TransportError("Agent catalog page query was invalid", 422);
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (query.search !== undefined) params.set("search", query.search);
  if (query.includeArchived !== undefined) {
    params.set("include_archived", String(query.includeArchived));
  }
  if (query.snapshot !== undefined) params.set("snapshot", query.snapshot);
  return {
    encoded: `?${params.toString()}`,
    limit,
    offset,
    snapshot: query.snapshot,
  };
}

function agentArtifactPageQuery(
  query: AgentArtifactPageQuery = {},
): Required<Pick<AgentArtifactPageQuery, "view" | "limit" | "offset">>
  & Pick<AgentArtifactPageQuery, "snapshot">
  & { encoded: string } {
  const view = query.view ?? "active";
  const limit = query.limit ?? 100;
  const offset = query.offset ?? 0;
  if (
    !["active", "archived", "removed", "all"].includes(view)
    || !Number.isInteger(limit) || limit < 1 || limit > 100
    || !Number.isInteger(offset) || offset < 0 || offset > 500
    || (query.snapshot !== undefined && !/^[0-9a-f]{64}$/u.test(query.snapshot))
    || (offset > 0 && query.snapshot === undefined)
  ) throw new TransportError("Agent artifact page query was invalid", 422);
  const params = new URLSearchParams({
    view,
    limit: String(limit),
    offset: String(offset),
  });
  if (query.snapshot !== undefined) params.set("snapshot", query.snapshot);
  return {
    encoded: `?${params.toString()}`,
    view,
    limit,
    offset,
    snapshot: query.snapshot,
  };
}

export type SafeTransportReasonCode =
  | "redacted_content_consent_required"
  | "session_not_in_safe_index"
  | "analysis_idempotency_conflict"
  | "invalid_analysis_request"
  | "confirmation_required"
  | "source_schema_unsupported"
  | "selection_snapshot_miss"
  | "source_selection_limit"
  | "source_provider_response_limit"
  | "source_thread_structure_limit"
  | "source_preview_window_limit"
  | "source_resource_limit"
  | "source_timeout"
  | "provider_unavailable"
  | "no_analyzable_text"
  | "provider_protocol_rejected"
  | "provider_compatibility_blocked"
  | "analysis_persistence_failed"
  | "metric_execution_failed"
  | "redaction_preview_not_found"
  | "redaction_preview_expired"
  | "redaction_preview_consumed"
  | "redaction_preview_binding_mismatch"
  | "redaction_preview_capacity_reached"
  | "analysis_job_not_found"
  | "analysis_job_conflict"
  | "automation_consent_required"
  | "automation_metric_unsupported"
  | "automation_project_not_indexed"
  | "automation_grant_conflict"
  | "automation_grant_not_found"
  | "automation_resource_policy_unsupported"
  | "invalid_model_link_request"
  | "model_link_confirmation_required"
  | "no_model_link_candidates"
  | "local_model_execution_failed"
  | "model_link_persistence_failed"
  | "model_link_revision_conflict"
  | "invalid_model_ensemble_request"
  | "model_ensemble_confirmation_required"
  | "local_model_ensemble_execution_failed"
  | "model_ensemble_cleanup_unconfirmed"
  | "model_ensemble_persistence_failed"
  | "invalid_model_ensemble_watch_request"
  | "model_ensemble_watch_not_found"
  | "model_ensemble_watch_conflict"
  | "claude_home_invalid"
  | "claude_home_override_unsupported"
  | "claude_code_not_installed"
  | "model_not_ready"
  | "no_active_model"
  | "model_not_active"
  | "model_not_found"
  | "model_file_missing"
  | "model_projector_invalid"
  | "model_projector_missing"
  | "runtime_unavailable"
  | "runtime_placement_unavailable"
  | "runtime_gpu_layers_invalid"
  | "runtime_context_unsupported"
  | "runtime_activation_superseded"
  | "runtime_shutdown_in_progress"
  | "web_fetch_unavailable"
  | "runtime_spawn_failed"
  | "runtime_not_healthy"
  | "runtime_capability_probe_failed"
  | "runtime_busy"
  | "runtime_revision_conflict"
  | "runtime_quarantined"
  | "runtime_cleanup_unconfirmed"
  | "runtime_stop_failed"
  | "runtime_crashed"
  | "runtime_out_of_memory"
  | "download_not_found"
  | "download_revision_conflict"
  | "download_action_invalid"
  | "download_ledger_invalid"
  | "download_ledger_unavailable"
  | "download_adapter_incompatible"
  | "download_cleanup_failed"
  | "provenance_mismatch"
  | "file_not_eligible"
  | "model_reply_invalid"
  | "calibration_review_disabled"
  | "calibration_review_consent_required"
  | "calibration_review_unavailable"
  | "calibration_window_unavailable"
  | "calibration_review_missing"
  | "calibration_review_mismatch"
  | "calibration_review_expired"
  | "too_many_sessions"
  | "turn_in_progress"
  | "session_closing"
  | "session_stop_timeout"
  | "command_cleanup_unconfirmed"
  | "approval_not_pending"
  | "approval_already_settled"
  | "workspace_not_a_folder"
  | "workspace_not_allowed"
  | "workspace_root_changed"
  | "workspace_inspection_timeout"
  | "workspace_query_empty"
  | "workspace_query_too_large"
  | "workspace_regex_invalid"
  | "workspace_glob_invalid"
  | "workspace_write_failed"
  | "workspace_cleanup_failed"
  | "workspace_verification_failed"
  | "workspace_parent_unavailable"
  | "workspace_path_not_found"
  | "workspace_directory_unavailable"
  | "workspace_not_a_directory"
  | "workspace_revision_changed"
  | "workspace_preview_not_found"
  | "workspace_preview_expired"
  | "workspace_preview_mismatch"
  | "workspace_link_or_reparse_refused"
  | "path_invalid"
  | "path_outside_workspace"
  | "workspace_lifecycle_target_exists"
  | "workspace_lifecycle_same_path"
  | "workspace_lifecycle_preview_not_found"
  | "workspace_lifecycle_preview_expired"
  | "workspace_lifecycle_preview_mismatch"
  | "workspace_lifecycle_unverified"
  | "workspace_directory_create_failed"
  | "workspace_directory_create_unverified"
  | "workspace_directory_move_into_self"
  | "workspace_directory_move_unsupported"
  | "workspace_directory_move_failed"
  | "workspace_directory_move_unverified"
  | "workspace_file_trash_unsupported"
  | "workspace_file_trash_failed"
  | "workspace_file_trash_unverified"
  | "workspace_move_unsupported"
  | "workspace_move_failed"
  | "workspace_move_unverified"
  | "workspace_transaction_invalid"
  | "workspace_transaction_changed"
  | "workspace_transaction_no_change"
  | "workspace_transaction_too_large"
  | "workspace_transaction_diff_too_large"
  | "workspace_transaction_not_found"
  | "workspace_transaction_expired"
  | "workspace_transaction_mismatch"
  | "change_path_not_found"
  | "change_already_reverted"
  | "change_restore_baseline_unavailable"
  | "change_restore_unavailable"
  | "change_restore_mismatch"
  | "change_restore_verification_failed"
  | "agent_catalog_unavailable"
  | "agent_catalog_path_invalid"
  | "agent_catalog_path_unsafe"
  | "agent_catalog_storage_unavailable"
  | "agent_catalog_schema_newer"
  | "agent_catalog_migration_history_incomplete"
  | "agent_catalog_migration_checksum_mismatch"
  | "agent_catalog_schema_version_mismatch"
  | "agent_project_not_found"
  | "agent_project_archived"
  | "agent_project_conflict"
  | "agent_project_revision_conflict"
  | "agent_project_not_empty"
  | "agent_default_project_protected"
  | "too_many_agent_projects"
  | "agent_catalog_session_not_found"
  | "agent_catalog_session_conflict"
  | "agent_catalog_session_revision_conflict"
  | "agent_catalog_session_live"
  | "too_many_agent_catalog_sessions"
  | "agent_catalog_session_archived"
  | "agent_catalog_page_invalid"
  | "agent_catalog_page_snapshot_required"
  | "agent_catalog_page_snapshot_conflict"
  | "agent_catalog_page_out_of_range"
  | "agent_history_not_retained"
  | "agent_history_revision_conflict"
  | "agent_history_sequence_conflict"
  | "agent_history_limit_reached"
  | "agent_history_event_too_large"
  | "agent_history_corrupt"
  | "agent_history_storage_unavailable"
  | "agent_history_write_failed"
  | "agent_session_fork_point_invalid"
  | "agent_session_fork_request_conflict"
  | "agent_session_fork_conflict"
  | "agent_artifact_unavailable"
  | "agent_artifact_storage_unavailable"
  | "agent_artifact_not_found"
  | "agent_artifact_version_not_found"
  | "agent_artifact_retention_required"
  | "agent_artifact_revision_changed"
  | "agent_artifact_stale"
  | "agent_artifact_missing"
  | "agent_artifact_malformed"
  | "agent_artifact_preview_unsupported"
  | "agent_artifact_too_large"
  | "agent_artifact_limit_reached"
  | "agent_artifact_version_limit_reached"
  | "agent_artifact_conflict"
  | "agent_artifact_revision_conflict"
  | "agent_artifact_state_conflict"
  | "agent_artifact_no_change"
  | "agent_artifact_archive_required"
  | "agent_artifact_removed"
  | "agent_artifact_page_invalid"
  | "agent_artifact_page_snapshot_required"
  | "agent_artifact_page_snapshot_conflict"
  | "agent_artifact_page_out_of_range"
  | "native_confirmation_declined_before_dispatch"
  | "agent_attachment_unavailable"
  | "agent_attachment_capabilities_unavailable"
  | "agent_attachment_not_found"
  | "agent_attachment_empty"
  | "agent_attachment_media_unsupported"
  | "agent_attachment_media_mismatch"
  | "agent_attachment_dimensions_unsupported"
  | "agent_attachment_audio_unsupported"
  | "agent_attachment_duration_unsupported"
  | "agent_attachment_image_capability_unavailable"
  | "agent_attachment_audio_capability_unavailable"
  | "agent_attachment_document_capability_unavailable"
  | "agent_attachment_document_encoding_unsupported"
  | "agent_attachment_document_structure_invalid"
  | "agent_attachment_document_empty"
  | "agent_attachment_document_message_too_large"
  | "agent_attachment_content_preview_unsupported"
  | "agent_attachment_document_preview_unsupported"
  | "agent_attachment_too_large"
  | "agent_attachment_message_too_large"
  | "agent_attachment_session_too_large"
  | "agent_attachment_stage_limit"
  | "agent_attachment_message_limit"
  | "agent_attachment_duplicate"
  | "agent_attachment_model_changed"
  | "agent_attachment_retention_changed"
  | "agent_attachment_already_sent"
  | "agent_attachment_state_changed"
  | "agent_attachment_corrupt"
  | "agent_attachment_conflict"
  | "agent_attachment_storage_unavailable"
  | "mcp_registry_response_invalid"
  | "mcp_registry_identity_conflict"
  | "mcp_registry_pagination_cycle"
  | "mcp_registry_source_disagreement"
  | "mcp_host_protocol_unsupported"
  | "mcp_host_transport_mismatch"
  | "mcp_host_tool_alias_collision"
  | "mcp_host_tool_count_exceeded"
  | "mcp_host_tool_identity_conflict"
  | "mcp_host_tool_identity_invalid"
  | "mcp_host_tool_metadata_invalid"
  | "mcp_host_tool_metadata_total_exceeded"
  | "mcp_host_tool_schema_dialect_unsupported"
  | "mcp_host_tool_schema_external_ref"
  | "mcp_host_tool_schema_format_unsupported"
  | "mcp_host_tool_schema_invalid"
  | "mcp_host_tool_schema_keyword_unsupported"
  | "mcp_host_tool_schema_pattern_unsafe"
  | "mcp_host_tool_schema_recursive"
  | "mcp_host_tool_schema_ref_invalid"
  | "mcp_host_tool_schema_too_complex"
  | "mcp_host_tool_schema_too_large"
  | "mcp_host_tool_schema_total_exceeded"
  | "mcp_host_endpoint_unresolvable"
  | "mcp_host_endpoint_unreachable"
  | "mcp_host_endpoint_not_public"
  | "mcp_host_egress_origin_changed"
  | "mcp_host_tls_policy_invalid"
  | "mcp_host_redirect_refused"
  | "mcp_host_headers_too_large"
  | "mcp_host_headers_invalid"
  | "mcp_host_content_encoding_unsupported"
  | "mcp_host_response_too_large"
  | "mcp_host_response_count_exceeded"
  | "mcp_host_sse_event_count_exceeded"
  | "mcp_host_process_output_limit"
  | "mcp_host_visible_window_detected"
  | "mcp_host_process_visibility_unconfirmed"
  | "mcp_host_deadline_exceeded"
  | "mcp_host_probe_failed"
  | "mcp_host_cleanup_unconfirmed"
  | "mcp_managed_host_start_cancelled"
  | "mcp_managed_host_start_timeout"
  | "mcp_managed_host_stop_timeout"
  | "codex_not_installed";

const SAFE_TRANSPORT_REASONS = new Set<SafeTransportReasonCode>([
  "redacted_content_consent_required",
  "session_not_in_safe_index",
  "analysis_idempotency_conflict",
  "invalid_analysis_request",
  "confirmation_required",
  "source_schema_unsupported",
  "selection_snapshot_miss",
  "source_selection_limit",
  "source_provider_response_limit",
  "source_thread_structure_limit",
  "source_preview_window_limit",
  "source_resource_limit",
  "source_timeout",
  "provider_unavailable",
  "no_analyzable_text",
  "provider_protocol_rejected",
  "provider_compatibility_blocked",
  "analysis_persistence_failed",
  "metric_execution_failed",
  "redaction_preview_not_found",
  "redaction_preview_expired",
  "redaction_preview_consumed",
  "redaction_preview_binding_mismatch",
  "redaction_preview_capacity_reached",
  "analysis_job_not_found",
  "analysis_job_conflict",
  "automation_consent_required",
  "automation_metric_unsupported",
  "automation_project_not_indexed",
  "automation_grant_conflict",
  "automation_grant_not_found",
  "automation_resource_policy_unsupported",
  "invalid_model_link_request",
  "model_link_confirmation_required",
  "no_model_link_candidates",
  "local_model_execution_failed",
  "model_link_persistence_failed",
  "model_link_revision_conflict",
  "invalid_model_ensemble_request",
  "model_ensemble_confirmation_required",
  "local_model_ensemble_execution_failed",
  "model_ensemble_cleanup_unconfirmed",
  "model_ensemble_persistence_failed",
  "invalid_model_ensemble_watch_request",
  "model_ensemble_watch_not_found",
  "model_ensemble_watch_conflict",
  "claude_home_invalid",
  "claude_home_override_unsupported",
  "claude_code_not_installed",
  "model_not_ready",
  "no_active_model",
  "model_not_active",
  "model_not_found",
  "model_file_missing",
  "model_projector_invalid",
  "model_projector_missing",
  "runtime_unavailable",
  "runtime_placement_unavailable",
  "runtime_gpu_layers_invalid",
  "runtime_context_unsupported",
  "runtime_activation_superseded",
  "runtime_shutdown_in_progress",
  "web_fetch_unavailable",
  "runtime_spawn_failed",
  "runtime_not_healthy",
  "runtime_capability_probe_failed",
  "runtime_busy",
  "runtime_revision_conflict",
  "runtime_quarantined",
  "runtime_cleanup_unconfirmed",
  "runtime_stop_failed",
  "runtime_crashed",
  "runtime_out_of_memory",
  "download_not_found",
  "download_revision_conflict",
  "download_action_invalid",
  "download_ledger_invalid",
  "download_ledger_unavailable",
  "download_adapter_incompatible",
  "download_cleanup_failed",
  "provenance_mismatch",
  "file_not_eligible",
  "model_reply_invalid",
  "calibration_review_disabled",
  "calibration_review_consent_required",
  "calibration_review_unavailable",
  "calibration_window_unavailable",
  "calibration_review_missing",
  "calibration_review_mismatch",
  "calibration_review_expired",
  "too_many_sessions",
  "turn_in_progress",
  "session_closing",
  "session_stop_timeout",
  "command_cleanup_unconfirmed",
  "approval_not_pending",
  "approval_already_settled",
  "workspace_not_a_folder",
  "workspace_not_allowed",
  "workspace_root_changed",
  "workspace_inspection_timeout",
  "workspace_query_empty",
  "workspace_query_too_large",
  "workspace_regex_invalid",
  "workspace_glob_invalid",
  "workspace_write_failed",
  "workspace_cleanup_failed",
  "workspace_verification_failed",
  "workspace_parent_unavailable",
  "workspace_path_not_found",
  "workspace_directory_unavailable",
  "workspace_not_a_directory",
  "workspace_revision_changed",
  "workspace_preview_not_found",
  "workspace_preview_expired",
  "workspace_preview_mismatch",
  "workspace_link_or_reparse_refused",
  "path_invalid",
  "path_outside_workspace",
  "workspace_lifecycle_target_exists",
  "workspace_lifecycle_same_path",
  "workspace_lifecycle_preview_not_found",
  "workspace_lifecycle_preview_expired",
  "workspace_lifecycle_preview_mismatch",
  "workspace_lifecycle_unverified",
  "workspace_directory_create_failed",
  "workspace_directory_create_unverified",
  "workspace_directory_move_into_self",
  "workspace_directory_move_unsupported",
  "workspace_directory_move_failed",
  "workspace_directory_move_unverified",
  "workspace_file_trash_unsupported",
  "workspace_file_trash_failed",
  "workspace_file_trash_unverified",
  "workspace_move_unsupported",
  "workspace_move_failed",
  "workspace_move_unverified",
  "workspace_transaction_invalid",
  "workspace_transaction_changed",
  "workspace_transaction_no_change",
  "workspace_transaction_too_large",
  "workspace_transaction_diff_too_large",
  "workspace_transaction_not_found",
  "workspace_transaction_expired",
  "workspace_transaction_mismatch",
  "change_path_not_found",
  "change_already_reverted",
  "change_restore_baseline_unavailable",
  "change_restore_unavailable",
  "change_restore_mismatch",
  "change_restore_verification_failed",
  "agent_catalog_unavailable",
  "agent_catalog_path_invalid",
  "agent_catalog_path_unsafe",
  "agent_catalog_storage_unavailable",
  "agent_catalog_schema_newer",
  "agent_catalog_migration_history_incomplete",
  "agent_catalog_migration_checksum_mismatch",
  "agent_catalog_schema_version_mismatch",
  "agent_project_not_found",
  "agent_project_archived",
  "agent_project_conflict",
  "agent_project_revision_conflict",
  "agent_project_not_empty",
  "agent_default_project_protected",
  "too_many_agent_projects",
  "agent_catalog_session_not_found",
  "agent_catalog_session_conflict",
  "agent_catalog_session_revision_conflict",
  "agent_catalog_session_live",
  "too_many_agent_catalog_sessions",
  "agent_catalog_session_archived",
  "agent_catalog_page_invalid",
  "agent_catalog_page_snapshot_required",
  "agent_catalog_page_snapshot_conflict",
  "agent_catalog_page_out_of_range",
  "agent_history_not_retained",
  "agent_history_revision_conflict",
  "agent_history_sequence_conflict",
  "agent_history_limit_reached",
  "agent_history_event_too_large",
  "agent_history_corrupt",
  "agent_history_storage_unavailable",
  "agent_history_write_failed",
  "agent_session_fork_point_invalid",
  "agent_session_fork_request_conflict",
  "agent_session_fork_conflict",
  "agent_artifact_unavailable",
  "agent_artifact_storage_unavailable",
  "agent_artifact_not_found",
  "agent_artifact_version_not_found",
  "agent_artifact_retention_required",
  "agent_artifact_revision_changed",
  "agent_artifact_stale",
  "agent_artifact_missing",
  "agent_artifact_malformed",
  "agent_artifact_preview_unsupported",
  "agent_artifact_too_large",
  "agent_artifact_limit_reached",
  "agent_artifact_version_limit_reached",
  "agent_artifact_conflict",
  "agent_artifact_revision_conflict",
  "agent_artifact_state_conflict",
  "agent_artifact_no_change",
  "agent_artifact_archive_required",
  "agent_artifact_removed",
  "agent_artifact_page_invalid",
  "agent_artifact_page_snapshot_required",
  "agent_artifact_page_snapshot_conflict",
  "agent_artifact_page_out_of_range",
  "native_confirmation_declined_before_dispatch",
  "agent_attachment_unavailable",
  "agent_attachment_capabilities_unavailable",
  "agent_attachment_not_found",
  "agent_attachment_empty",
  "agent_attachment_media_unsupported",
  "agent_attachment_media_mismatch",
  "agent_attachment_dimensions_unsupported",
  "agent_attachment_audio_unsupported",
  "agent_attachment_duration_unsupported",
  "agent_attachment_image_capability_unavailable",
  "agent_attachment_audio_capability_unavailable",
  "agent_attachment_document_capability_unavailable",
  "agent_attachment_document_encoding_unsupported",
  "agent_attachment_document_structure_invalid",
  "agent_attachment_document_empty",
  "agent_attachment_document_message_too_large",
  "agent_attachment_content_preview_unsupported",
  "agent_attachment_document_preview_unsupported",
  "agent_attachment_too_large",
  "agent_attachment_message_too_large",
  "agent_attachment_session_too_large",
  "agent_attachment_stage_limit",
  "agent_attachment_message_limit",
  "agent_attachment_duplicate",
  "agent_attachment_model_changed",
  "agent_attachment_retention_changed",
  "agent_attachment_already_sent",
  "agent_attachment_state_changed",
  "agent_attachment_corrupt",
  "agent_attachment_conflict",
  "agent_attachment_storage_unavailable",
  "mcp_registry_response_invalid",
  "mcp_registry_identity_conflict",
  "mcp_registry_pagination_cycle",
  "mcp_registry_source_disagreement",
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
  "mcp_host_cleanup_unconfirmed",
  "mcp_managed_host_start_cancelled",
  "mcp_managed_host_start_timeout",
  "mcp_managed_host_stop_timeout",
  "codex_not_installed",
]);

const MODEL_LAB_INVENTORY_KEYS = new Set([
  "contract_version", "scope", "session_data_read", "private_evidence_returned",
  "registered_plan_count", "synthetic_execution_count", "model_run_count",
  "model_vote_count", "metric_estimate_count", "activation_outcome",
  "activation_allowed", "plans",
]);
const MODEL_LAB_PLAN_KEYS = new Set([
  "plan_fingerprint", "plan_key", "plan_version", "route",
  "metric_question_count", "synthetic_execution_count", "model_run_count",
  "model_vote_count", "metric_estimate_count", "activation_outcome",
  "activation_allowed",
]);
const MODEL_LAB_PLAN_KEY = /^[a-z][a-z0-9_.:-]{0,127}$/;
const MODEL_LAB_SAFE_VERSION = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const MODEL_LAB_PSEUDONYM = /^[a-f0-9]{64}$/;
const MAX_MODEL_LAB_PLANS = 1_000;
// Eight worst-case escaped approval previews remain below the 4 MB SSE frame cap.
const AGENT_EVENT_PAGE_LIMIT = 8;

function modelLabSafeInteger(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) &&
    value >= 0 && value <= maximum;
}

function modelLabSafeVersion(value: unknown): value is string {
  return typeof value === "string" && MODEL_LAB_SAFE_VERSION.test(value) &&
    !value.startsWith("/") && !value.startsWith("\\") &&
    !/^[A-Za-z]:[/\\]/.test(value) && !value.includes("\\") &&
    !value.includes("://") && !value.split("/").includes("..");
}

function parseModelLabPlan(value: unknown): ModelLabInventory["plans"][number] {
  if (
    !isRecord(value) || !hasExactKeys(value, MODEL_LAB_PLAN_KEYS) ||
    typeof value.plan_fingerprint !== "string" ||
    !MODEL_LAB_PSEUDONYM.test(value.plan_fingerprint) ||
    typeof value.plan_key !== "string" || !MODEL_LAB_PLAN_KEY.test(value.plan_key) ||
    !modelLabSafeVersion(value.plan_version) ||
    !["fast", "balanced", "deep"].includes(value.route as string) ||
    !modelLabSafeInteger(value.metric_question_count, 100) ||
    (value.metric_question_count as number) < 1 ||
    !modelLabSafeInteger(value.synthetic_execution_count) ||
    !modelLabSafeInteger(value.model_run_count) ||
    !modelLabSafeInteger(value.model_vote_count) ||
    !modelLabSafeInteger(value.metric_estimate_count) ||
    value.activation_outcome !== "synthetic_or_insufficient" ||
    value.activation_allowed !== false
  ) {
    throw new TransportError("Model Lab inventory response was invalid", 200);
  }
  return value as unknown as ModelLabInventory["plans"][number];
}

/** Strict content-free projection. Invalid or partial inventory is never shown as zero. */
export function parseModelLabInventory(value: unknown): ModelLabInventory {
  if (
    !isRecord(value) || !hasExactKeys(value, MODEL_LAB_INVENTORY_KEYS) ||
    value.contract_version !== "model-lab-inventory-v1" ||
    value.scope !== "synthetic_only" || value.session_data_read !== false ||
    value.private_evidence_returned !== false ||
    !modelLabSafeInteger(value.registered_plan_count, MAX_MODEL_LAB_PLANS) ||
    !modelLabSafeInteger(value.synthetic_execution_count) ||
    !modelLabSafeInteger(value.model_run_count) ||
    !modelLabSafeInteger(value.model_vote_count) ||
    !modelLabSafeInteger(value.metric_estimate_count) ||
    value.activation_outcome !== "synthetic_or_insufficient" ||
    value.activation_allowed !== false || !Array.isArray(value.plans) ||
    value.plans.length > MAX_MODEL_LAB_PLANS
  ) {
    throw new TransportError("Model Lab inventory response was invalid", 200);
  }
  const plans = value.plans.map(parseModelLabPlan);
  const order = plans.map((plan) =>
    `${plan.plan_key}\u0000${plan.plan_version}\u0000${plan.plan_fingerprint}`
  );
  const totals = plans.reduce(
    (result, plan) => ({
      executions: result.executions + plan.synthetic_execution_count,
      runs: result.runs + plan.model_run_count,
      votes: result.votes + plan.model_vote_count,
      estimates: result.estimates + plan.metric_estimate_count,
    }),
    { executions: 0, runs: 0, votes: 0, estimates: 0 },
  );
  if (
    value.registered_plan_count !== plans.length ||
    new Set(plans.map((plan) => plan.plan_fingerprint)).size !== plans.length ||
    order.some((item, index) => index > 0 && order[index - 1] > item) ||
    !Object.values(totals).every(Number.isSafeInteger) ||
    value.synthetic_execution_count !== totals.executions ||
    value.model_run_count !== totals.runs || value.model_vote_count !== totals.votes ||
    value.metric_estimate_count !== totals.estimates
  ) {
    throw new TransportError("Model Lab inventory response was invalid", 200);
  }
  return { ...value, plans } as ModelLabInventory;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function allowlistedReason(value: unknown): SafeTransportReasonCode | null {
  return typeof value === "string" &&
    SAFE_TRANSPORT_REASONS.has(value as SafeTransportReasonCode)
    ? (value as SafeTransportReasonCode)
    : null;
}

function safeReasonFromErrorPayload(value: unknown): SafeTransportReasonCode | null {
  if (!isRecord(value)) return null;
  if (isRecord(value.detail)) return allowlistedReason(value.detail.code);
  return allowlistedReason(value.detail);
}

export function parseSessionTextAnalysisCapability(
  value: unknown,
): SessionTextAnalysisCapability {
  if (
    !isRecord(value) ||
    typeof value.session_text_analysis !== "boolean" ||
    !(
      value.session_text_analysis_data_tier === "redacted_content" ||
      value.session_text_analysis_data_tier === null
    ) ||
    value.session_text_content_persistence !== false ||
    typeof value.codex_local_source !== "boolean" ||
    !(value.network_inference === false || (value.network_inference === true &&
      ((value.reviewed_inference === true && value.automatic_session_text_network_inference === false) ||
       (value.prompt_check_network_inference === true && value.session_text_network_inference === false)))) ||
    typeof value.raw_transcripts !== "boolean"
  ) {
    throw new TransportError("Local analysis capability response was invalid", 200);
  }

  if (value.session_text_analysis) {
    if (
      value.session_text_analysis_data_tier !== "redacted_content" ||
      value.codex_local_source !== true
    ) {
      throw new TransportError("Local analysis capability response was invalid", 200);
    }
    return {
      available: true,
      reason_code: "available",
      data_tier: "redacted_content",
      content_persistence: false,
      network_inference: false,
      raw_transcripts: value.raw_transcripts as boolean,
    };
  }

  if (value.session_text_analysis_data_tier !== null) {
    throw new TransportError("Local analysis capability response was invalid", 200);
  }
  return {
    available: false,
    reason_code: value.codex_local_source
      ? "analysis_service_unavailable"
      : "local_source_unavailable",
    data_tier: null,
    content_persistence: false,
    network_inference: false,
    raw_transcripts: value.raw_transcripts as boolean,
  };
}

const COMPATIBILITY_KEYS = new Set([
  "provider",
  "capability",
  "state",
  "capability_state",
  "provider_family",
  "provider_version",
  "adapter_family",
  "adapter_version",
  "source_schema_family",
  "source_schema_version",
  "content_schema_family",
  "content_schema_version",
  "reason_code",
  "checked_at",
  "update_support",
  "update_target",
]);
const SAFE_COMPATIBILITY_FAMILY = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const SAFE_COMPATIBILITY_VERSION = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/;
function safeNullableVersion(value: unknown): value is string | null {
  return value === null ||
    (typeof value === "string" && SAFE_COMPATIBILITY_VERSION.test(value));
}

// A provider may publish more than one surface family over time; Claude Code
// serves its transcript text window first and the hook ledger behind it.
const COMPATIBILITY_FAMILIES = {
  codex: [{
    provider: "codex_app_server",
    adapter: "codex_app_server",
    source: "codex_thread",
    content: "codex_thread_items",
  }],
  claude_code: [{
    provider: "claude_code",
    adapter: "claude_code_transcripts",
    source: "claude_transcript_jsonl",
    content: "claude_transcript_messages",
  }, {
    provider: "claude_code",
    adapter: "claude_code_hooks",
    source: "claude_hook_ledger",
    content: "claude_hook_events",
  }],
  synthetic: [{
    provider: "synthetic_provider",
    adapter: "synthetic_adapter",
    source: "synthetic_session",
    content: "synthetic_content",
  }],
} as const;

export function parseProviderCompatibilityStatus(
  value: unknown,
  expectedProvider?: ProviderCompatibilityProvider,
): ProviderCompatibilityStatus {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== COMPATIBILITY_KEYS.size ||
    Object.keys(value).some((key) => !COMPATIBILITY_KEYS.has(key)) ||
    !["codex", "claude_code", "synthetic"].includes(value.provider as string) ||
    !["session_text_analysis", "operational_events"].includes(value.capability as string) ||
    ![
      "exact",
      "compatible",
      "degraded",
      "untested",
      "incompatible",
      "unavailable",
    ].includes(value.state as string) ||
    !["supported", "unsupported", "unknown"].includes(
      value.capability_state as string,
    ) ||
    ![value.provider_family, value.adapter_family, value.source_schema_family, value.content_schema_family].every(
      (item) => typeof item === "string" && SAFE_COMPATIBILITY_FAMILY.test(item),
    ) ||
    ![
      value.provider_version,
      value.adapter_version,
      value.source_schema_version,
      value.content_schema_version,
    ].every(safeNullableVersion) ||
    ![
      "exact_match",
      "compatible_version",
      "degraded_extraction",
      "not_checked",
      "provider_unavailable",
      "provider_version_unsupported",
      "adapter_outdated",
      "source_schema_unsupported",
      "content_schema_unsupported",
      "check_failed",
    ].includes(value.reason_code as string) ||
    !(
      value.checked_at === null ||
      isUtcCoverageTimestamp(value.checked_at)
    ) ||
    !["supported", "unsupported", "unknown"].includes(
      value.update_support as string,
    ) ||
    !(
      value.update_target === null ||
      value.update_target === "prompt_enhancer" ||
      value.update_target === "provider"
    )
  ) {
    throw new TransportError("Provider compatibility response was invalid", 200);
  }

  const state = value.state as ProviderCompatibilityStatus["state"];
  const provider = value.provider as ProviderCompatibilityProvider;
  const capabilityState =
    value.capability_state as ProviderCompatibilityStatus["capability_state"];
  const reason = value.reason_code as ProviderCompatibilityStatus["reason_code"];
  const checkedAt = value.checked_at as string | null;
  const updateSupport =
    value.update_support as ProviderCompatibilityStatus["update_support"];
  const updateTarget =
    value.update_target as ProviderCompatibilityStatus["update_target"];
  const exactVersions = [
    value.provider_version,
    value.adapter_version,
    value.source_schema_version,
    value.content_schema_version,
  ].every((item) => typeof item === "string");
  const familiesMatch = COMPATIBILITY_FAMILIES[provider].some((expected) =>
    value.provider_family === expected.provider &&
    value.adapter_family === expected.adapter &&
    value.source_schema_family === expected.source &&
    value.content_schema_family === expected.content);
  const coherent =
    ((state === "exact" &&
      capabilityState === "supported" &&
      reason === "exact_match" &&
      checkedAt !== null &&
      exactVersions) ||
      (state === "compatible" &&
        capabilityState === "supported" &&
        reason === "compatible_version" &&
        checkedAt !== null &&
        exactVersions) ||
      (state === "degraded" &&
        reason === "degraded_extraction" &&
        checkedAt !== null) ||
      (state === "untested" &&
        capabilityState === "unknown" &&
        reason === "not_checked" &&
        checkedAt === null &&
        updateSupport === "unknown") ||
      (state === "incompatible" &&
        capabilityState === "unsupported" &&
        [
          "provider_version_unsupported",
          "adapter_outdated",
          "source_schema_unsupported",
          "content_schema_unsupported",
        ].includes(reason) &&
        checkedAt !== null) ||
      (state === "unavailable" &&
        capabilityState === "unknown" &&
        ["provider_unavailable", "check_failed"].includes(reason) &&
        checkedAt !== null)) &&
    familiesMatch &&
    (updateSupport === "supported"
      ? updateTarget !== null
      : updateTarget === null);

  if (!coherent) {
    throw new TransportError("Provider compatibility response was invalid", 200);
  }
  if (expectedProvider !== undefined && value.provider !== expectedProvider) {
    throw new TransportError("Provider compatibility response was invalid", 200);
  }
  return value as unknown as ProviderCompatibilityStatus;
}

const READINESS_EVIDENCE_CAPABILITIES = [
  "request_text",
  "response_text",
  "plan_text",
  "action_evidence",
  "decision_evidence",
  "feedback_text",
  "objective_verification",
] as const satisfies readonly MetricEvidenceCapability[];

const READINESS_ACTIONS = new Set<MetricReadinessAction>([
  "none",
  "run_local_analysis",
  "check_provider_compatibility",
  "update_provider_adapter",
  "collect_action_evidence",
  "collect_decision_evidence",
  "collect_feedback_evidence",
  "collect_objective_verification",
  "review_applicability",
  "review_evidence_coverage",
  "retry_analysis",
  "select_metric_for_analysis",
]);

type ReadinessCatalogEntry = {
  version: number;
  dimension: "prompt" | "collaboration" | "logic" | "outcome";
  displayName: string;
  unit: "ratio" | "risk_ratio";
  direction: "higher_is_better" | "lower_is_better";
  capabilityGroups: readonly (readonly MetricEvidenceCapability[])[];
};

const REQUEST_OR_FEEDBACK = ["feedback_text", "request_text"] as const;
const COACHING_READINESS_CATALOG = {
  "prompt.task_definition_coverage": {
    version: 2, dimension: "prompt", displayName: "Task definition coverage",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "prompt.problem_evidence_quality": {
    version: 2, dimension: "prompt", displayName: "Problem evidence quality",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "prompt.context_sufficiency": {
    version: 2, dimension: "prompt", displayName: "Context cue coverage",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "prompt.constraint_precision": {
    version: 2, dimension: "prompt", displayName: "Constraint precision candidates",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "prompt.acceptance_testability": {
    version: 2, dimension: "prompt", displayName: "Acceptance testability cues",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "prompt.deliverable_contract": {
    version: 3, dimension: "prompt", displayName: "Deliverable contract cues",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "collaboration.ambiguity_resolution": {
    version: 2, dimension: "collaboration", displayName: "Ambiguity-resolution candidates",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "collaboration.clarification_yield": {
    version: 2, dimension: "collaboration", displayName: "Clarification yield candidates",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["response_text"], REQUEST_OR_FEEDBACK],
  },
  "collaboration.exploration_conversion": {
    version: 2, dimension: "collaboration", displayName: "Exploration-to-plan conversion",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["plan_text", "request_text", "response_text"]],
  },
  "collaboration.scope_change_discipline": {
    version: 2, dimension: "collaboration", displayName: "Scope-change acknowledgement",
    unit: "ratio", direction: "higher_is_better", capabilityGroups: [REQUEST_OR_FEEDBACK],
  },
  "collaboration.rework_candidate_rate": {
    version: 2, dimension: "collaboration", displayName: "Rework-candidate rate",
    unit: "risk_ratio", direction: "lower_is_better",
    capabilityGroups: [["response_text"], ["feedback_text"]],
  },
  "logic.decomposition_coverage": {
    version: 2, dimension: "logic", displayName: "Requirement-to-plan coverage",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [REQUEST_OR_FEEDBACK, ["plan_text"]],
  },
  "logic.hypothesis_test_linkage": {
    version: 2, dimension: "logic", displayName: "Hypothesis-to-test linkage",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["objective_verification"]],
  },
  "logic.decision_rationale_coverage": {
    version: 3, dimension: "logic", displayName: "Decision-rationale coverage",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["decision_evidence"]],
  },
  "logic.requirement_action_traceability": {
    version: 3, dimension: "logic", displayName: "Requirement-to-action traceability",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [REQUEST_OR_FEEDBACK, ["action_evidence"]],
  },
  "logic.open_loop_closure": {
    version: 2, dimension: "logic", displayName: "Open-loop closure candidates",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["feedback_text", "request_text", "response_text"]],
  },
  "outcome.agent_claim_grounding": {
    version: 2, dimension: "outcome", displayName: "Agent claim grounding",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["response_text"], ["objective_verification"]],
  },
  "outcome.verification_strategy_adequacy": {
    version: 2, dimension: "outcome", displayName: "Verification-strategy coverage",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [
      REQUEST_OR_FEEDBACK,
      ["objective_verification", "plan_text", "response_text"],
    ],
  },
  "outcome.first_pass_verification": {
    version: 2, dimension: "outcome", displayName: "First-pass verification",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [["objective_verification"]],
  },
  "outcome.verified_requirement_coverage": {
    version: 2, dimension: "outcome", displayName: "Verified requirement coverage",
    unit: "ratio", direction: "higher_is_better",
    capabilityGroups: [REQUEST_OR_FEEDBACK, ["objective_verification"]],
  },
} as const satisfies Record<string, ReadinessCatalogEntry>;

const COACHING_READINESS_KEYS = Object.keys(COACHING_READINESS_CATALOG) as Array<
  keyof typeof COACHING_READINESS_CATALOG
>;
const COACHING_READINESS_KEY_SET = new Set<string>(COACHING_READINESS_KEYS);
const READINESS_SAFE_TOKEN = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const PSEUDONYM = /^[a-f0-9]{64}$/;

const PROVIDER_CAPABILITY_REPORT_KEYS = new Set([
  "provider", "surface", "catalog_version", "compatibility_state",
  "provider_version", "decoder_key", "decoder_version", "checked_at",
  "capabilities", "structurally_attemptable_metric_count",
  "structurally_unsupported_metric_count", "structurally_unknown_metric_count",
]);
const PROVIDER_METRIC_CAPABILITY_KEYS = new Set([
  "capability", "state", "reason_code",
]);
const SESSION_READINESS_REPORT_KEYS = new Set([
  "session_id", "provider", "preset_id", "analysis_profile_key",
  "analysis_profile_version", "metric_pack_key", "metric_pack_version",
  "capability_report", "metrics",
]);
const METRIC_READINESS_KEYS = new Set([
  "metric_key", "metric_version", "dimension", "display_name", "unit",
  "direction", "radar_policy", "evidence_tier", "state", "reason_code",
  "next_actions", "capability_groups", "available_capabilities",
  "missing_capabilities", "latest_run_id",
]);

function hasExactKeys(value: Record<string, unknown>, keys: Set<string>): boolean {
  return Object.keys(value).length === keys.size &&
    Object.keys(value).every((key) => keys.has(key));
}

function isSafeNullableReadinessToken(value: unknown): value is string | null {
  return value === null ||
    (typeof value === "string" && READINESS_SAFE_TOKEN.test(value));
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function sameArray(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function sortedUniqueCapabilities(value: unknown): value is MetricEvidenceCapability[] {
  return Array.isArray(value) &&
    value.every((item) => READINESS_EVIDENCE_CAPABILITIES.includes(item)) &&
    sameArray(value, [...new Set(value)].sort());
}

function exactCapabilityGroups(
  value: unknown,
  expected: readonly (readonly MetricEvidenceCapability[])[],
): value is MetricEvidenceCapability[][] {
  return Array.isArray(value) && value.length === expected.length &&
    value.every((group, index) =>
      sortedUniqueCapabilities(group) && sameArray(group, expected[index]),
    );
}

function readinessRequirementsSatisfied(
  entry: ReadinessCatalogEntry,
  available: ReadonlySet<MetricEvidenceCapability>,
): boolean {
  return entry.capabilityGroups.every((group) =>
    group.some((capability) => available.has(capability)),
  );
}

export function parseProviderCapabilityReport(
  value: unknown,
  expectedProvider?: Provider,
): ProviderCapabilityReport {
  if (
    !isRecord(value) || !hasExactKeys(value, PROVIDER_CAPABILITY_REPORT_KEYS) ||
    !["codex", "claude_code", "synthetic"].includes(value.provider as string) ||
    (expectedProvider !== undefined && value.provider !== expectedProvider) ||
    value.surface !== "text_window" ||
    value.catalog_version !== "coaching-evidence-capabilities-v1" ||
    !["exact", "compatible", "degraded", "untested", "incompatible", "unavailable"]
      .includes(value.compatibility_state as string) ||
    !isSafeNullableReadinessToken(value.provider_version) ||
    !isSafeNullableReadinessToken(value.decoder_key) ||
    !isSafeNullableReadinessToken(value.decoder_version) ||
    !(
      value.checked_at === null ||
      isUtcCoverageTimestamp(value.checked_at)
    ) ||
    !isNonNegativeInteger(value.structurally_attemptable_metric_count) ||
    !isNonNegativeInteger(value.structurally_unsupported_metric_count) ||
    !isNonNegativeInteger(value.structurally_unknown_metric_count) ||
    !Array.isArray(value.capabilities) ||
    value.capabilities.length !== READINESS_EVIDENCE_CAPABILITIES.length
  ) {
    throw new TransportError("Provider metric capability response was invalid", 200);
  }

  const seen = new Set<string>();
  for (const item of value.capabilities) {
    if (
      !isRecord(item) || !hasExactKeys(item, PROVIDER_METRIC_CAPABILITY_KEYS) ||
      !READINESS_EVIDENCE_CAPABILITIES.includes(item.capability as MetricEvidenceCapability) ||
      !["supported", "unsupported", "unknown"].includes(item.state as string) ||
      ![
        "verified_by_compatible_decoder", "not_declared_by_decoder",
        "provider_adapter_unavailable", "compatibility_not_checked",
        "provider_incompatible", "capability_not_observed", "capability_unverified",
      ].includes(item.reason_code as string) ||
      seen.has(item.capability as string)
    ) {
      throw new TransportError("Provider metric capability response was invalid", 200);
    }
    seen.add(item.capability as string);
    const coherent =
      (item.state === "supported" && item.reason_code === "verified_by_compatible_decoder") ||
      (item.state === "unsupported" &&
        ["not_declared_by_decoder", "capability_not_observed"].includes(item.reason_code as string)) ||
      (item.state === "unknown" &&
        [
          "provider_adapter_unavailable", "compatibility_not_checked",
          "provider_incompatible", "capability_unverified",
        ].includes(item.reason_code as string));
    if (!coherent) {
      throw new TransportError("Provider metric capability response was invalid", 200);
    }
  }
  if (!READINESS_EVIDENCE_CAPABILITIES.every((item) => seen.has(item))) {
    throw new TransportError("Provider metric capability response was invalid", 200);
  }

  const compatibility = value.compatibility_state as ProviderCapabilityReport["compatibility_state"];
  const capabilities = value.capabilities as Array<{
    capability: MetricEvidenceCapability;
    state: "supported" | "unsupported" | "unknown";
    reason_code: string;
  }>;
  const noDecoder = value.decoder_key === null;
  const reportShapeCoherent = noDecoder
    ? value.decoder_version === null && value.provider_version === null &&
      value.checked_at === null && compatibility === "untested" &&
      capabilities.every((item) =>
        item.state === "unknown" && item.reason_code === "provider_adapter_unavailable")
    : typeof value.decoder_version === "string" &&
      (compatibility === "untested"
        ? value.provider_version === null && value.checked_at === null &&
          capabilities.every((item) =>
            item.reason_code === "not_declared_by_decoder" ||
            item.reason_code === "compatibility_not_checked")
        : typeof value.provider_version === "string" &&
          typeof value.checked_at === "string" &&
          (compatibility === "exact" || compatibility === "compatible"
            ? capabilities.every((item) => [
                "verified_by_compatible_decoder", "not_declared_by_decoder",
                "capability_not_observed", "capability_unverified",
              ].includes(item.reason_code))
            : capabilities.every((item) =>
                item.reason_code === "not_declared_by_decoder" ||
                item.reason_code === "provider_incompatible")));
  if (!reportShapeCoherent) {
    throw new TransportError("Provider metric capability response was invalid", 200);
  }

  const structurallyAvailable = new Set(
    capabilities
      .filter((item) =>
        item.reason_code !== "not_declared_by_decoder" &&
        item.reason_code !== "provider_adapter_unavailable")
      .map((item) => item.capability),
  );
  const attemptable = Object.values(COACHING_READINESS_CATALOG).filter((entry) =>
    readinessRequirementsSatisfied(entry, structurallyAvailable),
  ).length;
  const expectedUnknown = noDecoder ? COACHING_READINESS_KEYS.length : 0;
  const expectedUnsupported = noDecoder ? 0 : COACHING_READINESS_KEYS.length - attemptable;
  if (
    value.structurally_attemptable_metric_count !== attemptable ||
    value.structurally_unsupported_metric_count !== expectedUnsupported ||
    value.structurally_unknown_metric_count !== expectedUnknown ||
    attemptable + expectedUnsupported + expectedUnknown !== COACHING_READINESS_KEYS.length
  ) {
    throw new TransportError("Provider metric capability response was invalid", 200);
  }
  return value as unknown as ProviderCapabilityReport;
}

const METRIC_COVERAGE_REPORT_KEYS = new Set([
  "contract_version", "scope", "provider", "generated_at",
  "analysis_profile_key", "analysis_profile_version", "metric_pack_key",
  "metric_pack_version", "metric_catalog_version", "indexed_project_count",
  "indexed_session_count", "latest_profile_runs",
  "latest_completed_snapshot_count", "effective_automation_grant_count",
  "effective_automation_project_count", "unrecognized_result_record_count",
  "automation_scheduling_scope", "metrics", "capability_report",
  "local_index_snapshot_exact", "provider_history_completeness",
  "provider_snapshot_authority", "stored_result_contract_validation_performed",
  "provider_capability_snapshot_atomic",
  "full_catalog_automation_coverage_guaranteed", "metric_values_included",
  "product_source_authority", "population_completeness_verified",
  "comparison_authority", "snapshot_materialization_allowed",
  "recommendation_authority",
]);
const METRIC_COVERAGE_METRIC_KEYS = new Set([
  "metric_key", "metric_version", "latest_completed_run_count",
  "selected_run_count", "not_selected_run_count", "unknown_scope_run_count",
  "completed_selected_run_count", "contract_compatible_result_states",
  "contract_incompatible_result_count", "expected_result_absent_count",
  "compatible_provenance_cohort_count",
  "effective_automation_selected_project_count", "dimension", "display_name",
  "structural_support", "required_evidence",
]);
const LATEST_PROFILE_RUN_KEYS = new Set([
  "completed", "running", "failed", "never_run",
]);
const METRIC_RESULT_STATE_KEYS = new Set([
  "known", "unknown", "not_applicable", "abstained", "execution_error",
]);

function safeCountSum(values: readonly unknown[]): number | null {
  if (!values.every(isNonNegativeInteger)) return null;
  const total = (values as number[]).reduce((sum, value) => sum + value, 0);
  return Number.isSafeInteger(total) ? total : null;
}

function isUtcCoverageTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]00:00)$/.exec(value);
  if (match === null) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const maxDay = year >= 1 && month >= 1 && month <= 12
    ? new Date(Date.UTC(year, month, 0)).getUTCDate()
    : 0;
  return day >= 1 && day <= maxDay && Number(hourText) <= 23 &&
    Number(minuteText) <= 59 && Number(secondText) <= 59 &&
    !Number.isNaN(new Date(value).valueOf());
}

function invalidMetricCoverage(): never {
  throw new TransportError("Metric coverage response was invalid", 200);
}

/** Strict identifier-free projection of exact local-index coverage counts. */
export function parseMetricCoverageReport(
  value: unknown,
  expectedProvider?: Provider,
  expectedScope?: MetricCoverageReport["scope"],
): MetricCoverageReport {
  if (
    !isRecord(value) || !hasExactKeys(value, METRIC_COVERAGE_REPORT_KEYS) ||
    value.contract_version !== "metric-coverage-report-v1" ||
    !["provider_catalog", "one_project"].includes(value.scope as string) ||
    !["codex", "claude_code", "synthetic"].includes(value.provider as string) ||
    (expectedProvider !== undefined && value.provider !== expectedProvider) ||
    (expectedScope !== undefined && value.scope !== expectedScope) ||
    !isUtcCoverageTimestamp(value.generated_at) ||
    value.analysis_profile_key !== "coaching_profile" ||
    value.analysis_profile_version !== 1 ||
    value.metric_pack_key !== "experimental.redacted-text.coaching" ||
    value.metric_pack_version !== 3 ||
    value.metric_catalog_version !== "coaching-evidence-capabilities-v1" ||
    safeCountSum([
      value.indexed_project_count, value.indexed_session_count,
      value.latest_completed_snapshot_count, value.effective_automation_grant_count,
      value.effective_automation_project_count, value.unrecognized_result_record_count,
    ]) === null ||
    value.automation_scheduling_scope !== "new_or_changed_newest_bounded" ||
    !Array.isArray(value.metrics) ||
    value.metrics.length !== COACHING_READINESS_KEYS.length ||
    value.local_index_snapshot_exact !== true ||
    value.provider_history_completeness !== "unknown" ||
    value.provider_snapshot_authority !== "unavailable" ||
    value.stored_result_contract_validation_performed !== true ||
    value.provider_capability_snapshot_atomic !== false ||
    value.full_catalog_automation_coverage_guaranteed !== false ||
    value.metric_values_included !== false ||
    value.product_source_authority !== false ||
    value.population_completeness_verified !== false ||
    value.comparison_authority !== false ||
    value.snapshot_materialization_allowed !== false ||
    value.recommendation_authority !== false ||
    !isRecord(value.latest_profile_runs) ||
    !hasExactKeys(value.latest_profile_runs, LATEST_PROFILE_RUN_KEYS)
  ) {
    return invalidMetricCoverage();
  }

  const provider = value.provider as Provider;
  const capabilityReport = parseProviderCapabilityReport(
    value.capability_report,
    provider,
  );
  const runCount = safeCountSum([
    value.latest_profile_runs.completed, value.latest_profile_runs.running,
    value.latest_profile_runs.failed, value.latest_profile_runs.never_run,
  ]);
  const attemptedRunCount = safeCountSum([
    value.latest_profile_runs.completed, value.latest_profile_runs.running,
    value.latest_profile_runs.failed,
  ]);
  if (
    runCount === null || attemptedRunCount === null ||
    runCount !== value.indexed_session_count ||
    (value.latest_profile_runs.completed as number) >
      (value.latest_completed_snapshot_count as number) ||
    (value.latest_completed_snapshot_count as number) > attemptedRunCount ||
    (value.latest_completed_snapshot_count as number) >
      (value.indexed_session_count as number) ||
    (value.scope === "one_project" && value.indexed_project_count !== 1) ||
    (value.effective_automation_project_count as number) >
      (value.indexed_project_count as number) ||
    (value.effective_automation_project_count as number) >
      (value.effective_automation_grant_count as number) ||
    capabilityReport.catalog_version !== value.metric_catalog_version
  ) {
    return invalidMetricCoverage();
  }

  const declaredCapabilities = new Set(
    capabilityReport.capabilities
      .filter((item) =>
        item.reason_code !== "not_declared_by_decoder" &&
        item.reason_code !== "provider_adapter_unavailable")
      .map((item) => item.capability),
  );
  const allStructurallyUnknown =
    capabilityReport.structurally_unknown_metric_count ===
    COACHING_READINESS_KEYS.length;
  const supportCounts = { attemptable: 0, unsupported: 0, unknown: 0 };

  for (let index = 0; index < value.metrics.length; index += 1) {
    const metricCandidate: unknown = value.metrics[index];
    const metricKey = COACHING_READINESS_KEYS[index];
    const definition = COACHING_READINESS_CATALOG[metricKey];
    if (
      !isRecord(metricCandidate) ||
      !hasExactKeys(metricCandidate, METRIC_COVERAGE_METRIC_KEYS)
    ) {
      return invalidMetricCoverage();
    }
    const metric: Record<string, unknown> = metricCandidate;
    if (
      metric.metric_key !== metricKey || metric.metric_version !== definition.version ||
      metric.dimension !== definition.dimension ||
      metric.display_name !== definition.displayName ||
      !["attemptable", "unsupported", "unknown"].includes(
        metric.structural_support as string,
      ) ||
      !exactCapabilityGroups(metric.required_evidence, definition.capabilityGroups) ||
      safeCountSum([
        metric.latest_completed_run_count, metric.selected_run_count,
        metric.not_selected_run_count, metric.unknown_scope_run_count,
        metric.completed_selected_run_count,
        metric.contract_incompatible_result_count,
        metric.expected_result_absent_count,
        metric.compatible_provenance_cohort_count,
        metric.effective_automation_selected_project_count,
      ]) === null ||
      !isRecord(metric.contract_compatible_result_states) ||
      !hasExactKeys(metric.contract_compatible_result_states, METRIC_RESULT_STATE_KEYS)
    ) {
      return invalidMetricCoverage();
    }
    const compatibleResultCount = safeCountSum([
      metric.contract_compatible_result_states.known,
      metric.contract_compatible_result_states.unknown,
      metric.contract_compatible_result_states.not_applicable,
      metric.contract_compatible_result_states.abstained,
      metric.contract_compatible_result_states.execution_error,
    ]);
    const selectionTotal = safeCountSum([
      metric.selected_run_count, metric.not_selected_run_count,
      metric.unknown_scope_run_count,
    ]);
    const resultTotal = safeCountSum([
      compatibleResultCount, metric.contract_incompatible_result_count,
      metric.expected_result_absent_count,
    ]);
    const expectedSupport = allStructurallyUnknown
      ? "unknown"
      : definition.capabilityGroups.every((group) =>
          group.some((capability) => declaredCapabilities.has(capability)))
        ? "attemptable"
        : "unsupported";
    if (
      compatibleResultCount === null || selectionTotal === null || resultTotal === null ||
      metric.latest_completed_run_count !== value.latest_completed_snapshot_count ||
      selectionTotal !== metric.latest_completed_run_count ||
      metric.completed_selected_run_count !== metric.selected_run_count ||
      resultTotal !== metric.completed_selected_run_count ||
      (metric.compatible_provenance_cohort_count as number) > compatibleResultCount ||
      ((compatibleResultCount === 0) !==
        (metric.compatible_provenance_cohort_count === 0)) ||
      (metric.effective_automation_selected_project_count as number) >
        (value.effective_automation_project_count as number) ||
      metric.structural_support !== expectedSupport
    ) {
      return invalidMetricCoverage();
    }
    supportCounts[expectedSupport] += 1;
  }

  if (
    supportCounts.attemptable !==
      capabilityReport.structurally_attemptable_metric_count ||
    supportCounts.unsupported !==
      capabilityReport.structurally_unsupported_metric_count ||
    supportCounts.unknown !== capabilityReport.structurally_unknown_metric_count
  ) {
    return invalidMetricCoverage();
  }
  return value as unknown as MetricCoverageReport;
}

const READINESS_STATE_REASON_ACTION = new Map<string, readonly MetricReadinessAction[]>([
  ["known:measured", ["none"]],
  ["unknown:analysis_not_run", ["run_local_analysis"]],
  ["unknown:analysis_in_progress", ["none"]],
  ["unknown:result_unknown", ["review_applicability"]],
  ["unknown:metric_not_selected", ["select_metric_for_analysis"]],
  ["unknown:metric_scope_unknown", ["select_metric_for_analysis"]],
  ["unknown:provider_compatibility_unverified", ["check_provider_compatibility"]],
  ["unsupported:provider_adapter_unavailable", ["update_provider_adapter"]],
  ["abstained:result_abstained", ["review_evidence_coverage"]],
  ["incompatible:provider_incompatible", ["update_provider_adapter"]],
  ["not_applicable:explicitly_not_applicable", ["none"]],
  ["failed:provider_unavailable", ["check_provider_compatibility"]],
  ["failed:analysis_failed", ["retry_analysis"]],
  ["failed:result_failed", ["retry_analysis"]],
  ["failed:result_missing", ["retry_analysis"]],
]);

function actionsForMissingCapabilities(
  capabilities: readonly MetricEvidenceCapability[],
): MetricReadinessAction[] {
  const actionForCapability: Record<MetricEvidenceCapability, MetricReadinessAction> = {
    action_evidence: "collect_action_evidence",
    decision_evidence: "collect_decision_evidence",
    feedback_text: "collect_feedback_evidence",
    objective_verification: "collect_objective_verification",
    plan_text: "update_provider_adapter",
    request_text: "update_provider_adapter",
    response_text: "update_provider_adapter",
  };
  const mapped = capabilities.map((capability) => actionForCapability[capability]);
  return [...new Set(mapped)];
}

function parseMetricReadiness(
  value: unknown,
  entry: ReadinessCatalogEntry,
  expectedKey: string,
  capabilityReport: ProviderCapabilityReport,
): MetricReadiness {
  const expectedRadarPolicy = entry.direction === "higher_is_better"
    ? "direct_bounded_ratio"
    : "exact_value_only_unnormalized_lower_is_better";
  if (
    !isRecord(value) || !hasExactKeys(value, METRIC_READINESS_KEYS) ||
    value.metric_key !== expectedKey || value.metric_version !== entry.version ||
    value.dimension !== entry.dimension || value.display_name !== entry.displayName ||
    value.unit !== entry.unit || value.direction !== entry.direction ||
    value.radar_policy !== expectedRadarPolicy || value.evidence_tier !== "redacted_content" ||
    !["known", "unknown", "unsupported", "abstained", "incompatible", "not_applicable", "failed"]
      .includes(value.state as string) ||
    ![
      "measured", "analysis_not_run", "analysis_in_progress", "result_unknown",
      "result_abstained", "explicitly_not_applicable", "provider_capability_missing",
      "provider_adapter_unavailable", "provider_compatibility_unverified",
      "provider_incompatible", "provider_unavailable", "analysis_failed",
      "result_failed", "result_missing", "metric_not_selected",
      "metric_scope_unknown",
    ].includes(value.reason_code as string) ||
    !Array.isArray(value.next_actions) || value.next_actions.length < 1 ||
    value.next_actions.some((item) => !READINESS_ACTIONS.has(item as MetricReadinessAction)) ||
    new Set(value.next_actions).size !== value.next_actions.length ||
    !exactCapabilityGroups(value.capability_groups, entry.capabilityGroups) ||
    !sortedUniqueCapabilities(value.available_capabilities) ||
    !sortedUniqueCapabilities(value.missing_capabilities) ||
    !(value.latest_run_id === null ||
      (typeof value.latest_run_id === "string" && PSEUDONYM.test(value.latest_run_id)))
  ) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }

  const stateReason = `${String(value.state)}:${String(value.reason_code)}`;
  let expectedActions = READINESS_STATE_REASON_ACTION.get(stateReason);
  if (stateReason === "unsupported:provider_capability_missing") {
    expectedActions = actionsForMissingCapabilities(
      value.missing_capabilities as MetricEvidenceCapability[],
    );
  }
  if (!expectedActions || !sameArray(value.next_actions as string[], expectedActions)) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }

  const capabilityIndex = new Map(
    capabilityReport.capabilities.map((item) => [item.capability, item.state]),
  );
  const required = [...new Set(entry.capabilityGroups.flat())].sort();
  const expectedAvailable = required.filter(
    (capability) => capabilityIndex.get(capability) === "supported",
  );
  if (!sameArray(value.available_capabilities as string[], expectedAvailable)) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }
  let expectedMissing: MetricEvidenceCapability[] = [];
  if (value.reason_code === "provider_adapter_unavailable") {
    expectedMissing = required;
  } else if (value.reason_code === "provider_capability_missing") {
    expectedMissing = [...new Set(
      entry.capabilityGroups
        .filter((group) => !group.some((item) => capabilityIndex.get(item) === "supported"))
        .flat(),
    )].sort();
  }
  if (!sameArray(value.missing_capabilities as string[], expectedMissing)) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }

  const globalOverride = capabilityReport.decoder_key === null
    ? "unsupported:provider_adapter_unavailable"
    : capabilityReport.compatibility_state === "untested"
      ? "unknown:provider_compatibility_unverified"
      : capabilityReport.compatibility_state === "unavailable"
        ? "failed:provider_unavailable"
        : ["exact", "compatible"].includes(capabilityReport.compatibility_state)
          ? null
          : "incompatible:provider_incompatible";
  if (globalOverride !== null && stateReason !== globalOverride) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }
  if (value.reason_code === "analysis_not_run" && value.latest_run_id !== null) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }
  if ([
    "measured", "analysis_in_progress", "result_unknown", "result_abstained",
    "explicitly_not_applicable", "analysis_failed", "result_failed", "result_missing",
    "metric_not_selected", "metric_scope_unknown",
  ].includes(value.reason_code as string) && value.latest_run_id === null) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }
  return value as unknown as MetricReadiness;
}

export function parseSessionMetricReadinessReport(
  value: unknown,
  expectedSessionId?: string,
  expectedPresetId: TextAnalysisPresetId = "coaching_profile_v1",
): SessionMetricReadinessReport {
  if (
    !isRecord(value) || !hasExactKeys(value, SESSION_READINESS_REPORT_KEYS) ||
    typeof value.session_id !== "string" || !PSEUDONYM.test(value.session_id) ||
    (expectedSessionId !== undefined && value.session_id !== expectedSessionId) ||
    !["codex", "claude_code", "synthetic"].includes(value.provider as string) ||
    value.preset_id !== expectedPresetId || value.preset_id !== "coaching_profile_v1" ||
    value.analysis_profile_key !== "coaching_profile" ||
    value.analysis_profile_version !== 1 ||
    value.metric_pack_key !== "experimental.redacted-text.coaching" ||
    value.metric_pack_version !== 3 || !Array.isArray(value.metrics) ||
    value.metrics.length !== COACHING_READINESS_KEYS.length
  ) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }
  const provider = value.provider as Provider;
  const capabilityReport = parseProviderCapabilityReport(value.capability_report, provider);
  const metrics = value.metrics.map((metric, index) => {
    const expectedKey = COACHING_READINESS_KEYS[index];
    return parseMetricReadiness(
      metric,
      COACHING_READINESS_CATALOG[expectedKey],
      expectedKey,
      capabilityReport,
    );
  });
  if (
    new Set(metrics.map((metric) => `${metric.metric_key}.v${metric.metric_version}`)).size !==
    COACHING_READINESS_KEYS.length ||
    metrics.some((metric) => !COACHING_READINESS_KEY_SET.has(metric.metric_key))
  ) {
    throw new TransportError("Session metric readiness response was invalid", 200);
  }
  return value as unknown as SessionMetricReadinessReport;
}

const ANALYSIS_JOB_STATES = new Set<AnalysisJobState>([
  "queued", "preprocessing", "stage_n", "awaiting_approval", "completed",
  "partial", "failed", "cancelled", "superseded",
]);
const TERMINAL_ANALYSIS_JOB_STATES = new Set<AnalysisJobState>([
  "completed", "partial", "failed", "cancelled", "superseded",
]);
const ANALYSIS_JOB_PAGE_KEYS = new Set(["jobs", "limit", "offset"]);
const ANALYSIS_JOB_RECORD_KEYS = new Set([
  "job_id", "identity", "state", "stage_number",
  "progress_completed", "progress_total", "attempt_count", "max_attempts",
  "available_at", "cancel_requested", "last_error_code", "terminal_reason_code",
  "created_at", "updated_at", "terminal_at",
]);
const ANALYSIS_JOB_IDENTITY_KEYS = new Set([
  "kind", "provider", "project_id", "session_id", "input_fingerprint",
  "provenance_fingerprint", "metric_keys", "estimator_plan_version",
  "redactor_version", "provider_schema_version", "automation_grant_id",
  "local_only",
]);

function isSafeJobCode(value: unknown): value is string | null {
  return value === null ||
    (typeof value === "string" && READINESS_SAFE_TOKEN.test(value));
}

function isUtcJobTimestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /(?:Z|\+00:00)$/.test(value) &&
    Number.isFinite(Date.parse(value));
}

function parseAnalysisJobIdentity(value: unknown): AnalysisJobIdentity {
  if (
    !isRecord(value) || !hasExactKeys(value, ANALYSIS_JOB_IDENTITY_KEYS) ||
    !["session_quality", "synthetic_validation"].includes(value.kind as string) ||
    !["codex", "claude_code", "synthetic"].includes(value.provider as string) ||
    typeof value.project_id !== "string" || !PSEUDONYM.test(value.project_id) ||
    typeof value.session_id !== "string" || !PSEUDONYM.test(value.session_id) ||
    typeof value.input_fingerprint !== "string" || !PSEUDONYM.test(value.input_fingerprint) ||
    typeof value.provenance_fingerprint !== "string" || !PSEUDONYM.test(value.provenance_fingerprint) ||
    !Array.isArray(value.metric_keys) || value.metric_keys.length < 1 ||
    value.metric_keys.length > 100 ||
    value.metric_keys.some((key) => typeof key !== "string" || !READINESS_SAFE_TOKEN.test(key)) ||
    new Set(value.metric_keys).size !== value.metric_keys.length ||
    !sameArray(value.metric_keys, [...value.metric_keys].sort()) ||
    typeof value.estimator_plan_version !== "string" ||
    !READINESS_SAFE_TOKEN.test(value.estimator_plan_version) ||
    typeof value.redactor_version !== "string" ||
    !READINESS_SAFE_TOKEN.test(value.redactor_version) ||
    typeof value.provider_schema_version !== "string" ||
    !READINESS_SAFE_TOKEN.test(value.provider_schema_version) ||
    !(
      value.automation_grant_id === null ||
      (typeof value.automation_grant_id === "string" &&
        PSEUDONYM.test(value.automation_grant_id))
    ) ||
    value.local_only !== true
  ) {
    throw new TransportError("Analysis job response was invalid", 200);
  }
  return {
    kind: value.kind as AnalysisJobIdentity["kind"],
    provider: value.provider as Provider,
    project_id: value.project_id,
    session_id: value.session_id,
    input_fingerprint: value.input_fingerprint,
    provenance_fingerprint: value.provenance_fingerprint,
    metric_keys: [...value.metric_keys] as string[],
    estimator_plan_version: value.estimator_plan_version,
    redactor_version: value.redactor_version,
    provider_schema_version: value.provider_schema_version,
    automation_grant_id: value.automation_grant_id as string | null,
    local_only: true,
  };
}

/** Strictly validate the browser-safe durable job response. */
export function parseAnalysisJobRecord(
  value: unknown,
  expectedJobId?: string,
): AnalysisJobRecord {
  if (
    !isRecord(value) || !hasExactKeys(value, ANALYSIS_JOB_RECORD_KEYS) ||
    typeof value.job_id !== "string" || !PSEUDONYM.test(value.job_id) ||
    (expectedJobId !== undefined && value.job_id !== expectedJobId) ||
    !ANALYSIS_JOB_STATES.has(value.state as AnalysisJobState) ||
    !Number.isInteger(value.progress_completed) ||
    (value.progress_completed as number) < 0 ||
    !Number.isInteger(value.progress_total) ||
    (value.progress_total as number) < 1 ||
    (value.progress_total as number) > 1_000_000 ||
    (value.progress_completed as number) > (value.progress_total as number) ||
    !Number.isInteger(value.attempt_count) ||
    (value.attempt_count as number) < 0 || (value.attempt_count as number) > 5 ||
    !Number.isInteger(value.max_attempts) ||
    (value.max_attempts as number) < 1 || (value.max_attempts as number) > 5 ||
    (value.attempt_count as number) > (value.max_attempts as number) ||
    typeof value.cancel_requested !== "boolean" ||
    !isUtcJobTimestamp(value.available_at) ||
    !isUtcJobTimestamp(value.created_at) ||
    !isUtcJobTimestamp(value.updated_at) ||
    Date.parse(value.updated_at) < Date.parse(value.created_at) ||
    !isSafeJobCode(value.last_error_code) ||
    !isSafeJobCode(value.terminal_reason_code)
  ) {
    throw new TransportError("Analysis job response was invalid", 200);
  }
  const state = value.state as AnalysisJobState;
  const terminal = TERMINAL_ANALYSIS_JOB_STATES.has(state);
  const stageValid = state === "stage_n"
    ? Number.isInteger(value.stage_number) &&
      (value.stage_number as number) >= 1 && (value.stage_number as number) <= 32
    : value.stage_number === null;
  const terminalValid = terminal
    ? isUtcJobTimestamp(value.terminal_at) &&
      typeof value.terminal_reason_code === "string" &&
      Date.parse(value.terminal_at) >= Date.parse(value.created_at)
    : value.terminal_at === null && value.terminal_reason_code === null;
  if (!stageValid || !terminalValid) {
    throw new TransportError("Analysis job response was invalid", 200);
  }
  const identity = parseAnalysisJobIdentity(value.identity);
  return {
    job_id: value.job_id,
    identity,
    state,
    stage_number: value.stage_number as number | null,
    progress_completed: value.progress_completed as number,
    progress_total: value.progress_total as number,
    attempt_count: value.attempt_count as number,
    max_attempts: value.max_attempts as number,
    available_at: value.available_at,
    cancel_requested: value.cancel_requested,
    last_error_code: value.last_error_code as string | null,
    terminal_reason_code: value.terminal_reason_code as string | null,
    created_at: value.created_at,
    updated_at: value.updated_at,
    terminal_at: value.terminal_at as string | null,
  };
}

export function parseAnalysisJobPage(
  value: unknown,
  expectedLimit: number,
  expectedOffset: number,
  expectedState: AnalysisJobState | null = null,
): AnalysisJobPage {
  if (
    !isRecord(value) || !hasExactKeys(value, ANALYSIS_JOB_PAGE_KEYS) ||
    value.limit !== expectedLimit || value.offset !== expectedOffset ||
    !Array.isArray(value.jobs) || value.jobs.length > expectedLimit
  ) {
    throw new TransportError("Analysis job page response was invalid", 200);
  }
  const jobs = value.jobs.map((job) => parseAnalysisJobRecord(job));
  if (
    new Set(jobs.map((job) => job.job_id)).size !== jobs.length ||
    (expectedState !== null && jobs.some((job) => job.state !== expectedState))
  ) {
    throw new TransportError("Analysis job page response was invalid", 200);
  }
  return { jobs, limit: expectedLimit, offset: expectedOffset };
}

const AUTOMATION_GRANT_RECORD_KEYS = new Set([
  "created_at", "expires_at", "grant_id", "last_checked_at",
  "last_error_code", "next_check_at", "renewed_at", "revision",
  "revoked_at", "scope", "state",
]);
const AUTOMATION_GRANT_SCOPE_KEYS = new Set([
  "provider", "project_id", "metric_keys", "newest_session_limit",
  "check_interval_seconds", "resource_policy", "local_only",
  "remote_requires_fresh_approval",
]);
const AUTOMATION_RESOURCE_POLICY_KEYS = new Set([
  "route", "max_gpu_workers", "max_cpu_workers", "pause_on_battery",
  "maximum_session_seconds",
]);
const AUTOMATION_GRANT_CREATE_KEYS = new Set([
  "provider", "project_id", "metric_keys", "newest_session_limit",
  "check_interval_seconds", "resource_policy",
]);
const AUTOMATION_POLL_RESULT_KEYS = new Set([
  "grants_checked", "grants_revoked",
  "grants_power_paused", "grants_policy_unsupported", "candidates_seen",
  "power_external_observations", "power_battery_observations",
  "power_unknown_observations",
  "jobs_created", "jobs_reused", "jobs_superseded", "failures",
  "maximum_session_runtime_deadline_enforced",
  "session_quality_result_publication_deadline_enforced",
  "blocking_execution_preemption_enforced",
]);
const AUTOMATION_GRANT_LIFETIME_MS = 30 * 24 * 60 * 60 * 1_000;

function parseAutomationResourcePolicy(value: unknown): AutomationResourcePolicy {
  if (
    !isRecord(value) || !hasExactKeys(value, AUTOMATION_RESOURCE_POLICY_KEYS) ||
    !["fast", "balanced", "deep"].includes(value.route as string) ||
    value.max_gpu_workers !== 1 ||
    !Number.isInteger(value.max_cpu_workers) ||
    (value.max_cpu_workers as number) < 1 || (value.max_cpu_workers as number) > 4 ||
    typeof value.pause_on_battery !== "boolean" ||
    !Number.isInteger(value.maximum_session_seconds) ||
    (value.maximum_session_seconds as number) < 60 ||
    (value.maximum_session_seconds as number) > 14_400
  ) {
    throw new TransportError("Automation resource policy response was invalid", 200);
  }
  return {
    route: value.route as AutomationResourcePolicy["route"],
    max_gpu_workers: 1,
    max_cpu_workers: value.max_cpu_workers as number,
    pause_on_battery: value.pause_on_battery,
    maximum_session_seconds: value.maximum_session_seconds as number,
  };
}

function parseAutomationGrantScope(value: unknown): AutomationGrantScope {
  if (
    !isRecord(value) || !hasExactKeys(value, AUTOMATION_GRANT_SCOPE_KEYS) ||
    !["codex", "claude_code", "synthetic"].includes(value.provider as string) ||
    typeof value.project_id !== "string" || !PSEUDONYM.test(value.project_id) ||
    !Array.isArray(value.metric_keys) || value.metric_keys.length < 1 ||
    value.metric_keys.length > 100 ||
    value.metric_keys.some((key) =>
      typeof key !== "string" || !READINESS_SAFE_TOKEN.test(key)
    ) ||
    new Set(value.metric_keys).size !== value.metric_keys.length ||
    !sameArray(value.metric_keys, [...value.metric_keys].sort()) ||
    !Number.isInteger(value.newest_session_limit) ||
    (value.newest_session_limit as number) < 1 ||
    (value.newest_session_limit as number) > 100 ||
    !Number.isInteger(value.check_interval_seconds) ||
    (value.check_interval_seconds as number) < 60 ||
    (value.check_interval_seconds as number) > 86_400 ||
    value.local_only !== true || value.remote_requires_fresh_approval !== true
  ) {
    throw new TransportError("Automation grant scope response was invalid", 200);
  }
  return {
    provider: value.provider as Provider,
    project_id: value.project_id,
    metric_keys: [...value.metric_keys] as string[],
    newest_session_limit: value.newest_session_limit as number,
    check_interval_seconds: value.check_interval_seconds as number,
    resource_policy: parseAutomationResourcePolicy(value.resource_policy),
    local_only: true,
    remote_requires_fresh_approval: true,
  };
}

function sameAutomationResourcePolicy(
  left: AutomationResourcePolicy,
  right: AutomationResourcePolicy,
): boolean {
  return left.route === right.route &&
    left.max_gpu_workers === right.max_gpu_workers &&
    left.max_cpu_workers === right.max_cpu_workers &&
    left.pause_on_battery === right.pause_on_battery &&
    left.maximum_session_seconds === right.maximum_session_seconds;
}

export function sameAutomationGrantScope(
  left: AutomationGrantScope,
  right: AutomationGrantScope,
): boolean {
  return left.provider === right.provider &&
    left.project_id === right.project_id &&
    sameArray(left.metric_keys, right.metric_keys) &&
    left.newest_session_limit === right.newest_session_limit &&
    left.check_interval_seconds === right.check_interval_seconds &&
    left.local_only === right.local_only &&
    left.remote_requires_fresh_approval === right.remote_requires_fresh_approval &&
    sameAutomationResourcePolicy(left.resource_policy, right.resource_policy);
}

function parseAutomationGrantCreateRequest(
  value: unknown,
): AutomationGrantCreateRequest {
  if (!isRecord(value) || !hasExactKeys(value, AUTOMATION_GRANT_CREATE_KEYS)) {
    throw new TransportError("Automation grant request was invalid", 400);
  }
  const scope = parseAutomationGrantScope({
    ...value,
    local_only: true,
    remote_requires_fresh_approval: true,
  });
  if (
    scope.resource_policy.route !== "balanced" ||
    scope.resource_policy.max_gpu_workers !== 1 ||
    scope.resource_policy.max_cpu_workers !== 1 ||
    scope.resource_policy.pause_on_battery !== true ||
    scope.resource_policy.maximum_session_seconds !== 1_800
  ) {
    throw new TransportError("Automation grant request was invalid", 400);
  }
  return {
    provider: scope.provider,
    project_id: scope.project_id,
    metric_keys: scope.metric_keys,
    newest_session_limit: scope.newest_session_limit,
    check_interval_seconds: scope.check_interval_seconds,
    resource_policy: {
      route: "balanced",
      max_gpu_workers: 1,
      max_cpu_workers: 1,
      pause_on_battery: true,
      maximum_session_seconds: 1_800,
    },
  };
}

function scopeForAutomationRequest(
  request: AutomationGrantCreateRequest,
): AutomationGrantScope {
  return {
    ...request,
    local_only: true,
    remote_requires_fresh_approval: true,
  };
}

/** Strictly validate a content-free renewable automation grant. */
export function parseAutomationGrantRecord(
  value: unknown,
  expectedGrantId?: string,
  expectedScope?: AutomationGrantScope,
): AutomationGrantRecord {
  if (
    !isRecord(value) || !hasExactKeys(value, AUTOMATION_GRANT_RECORD_KEYS) ||
    typeof value.grant_id !== "string" || !PSEUDONYM.test(value.grant_id) ||
    (expectedGrantId !== undefined && value.grant_id !== expectedGrantId) ||
    !Number.isSafeInteger(value.revision) || (value.revision as number) < 1 ||
    !["active", "revoked", "expired"].includes(value.state as string) ||
    !isUtcJobTimestamp(value.created_at) ||
    !isUtcJobTimestamp(value.renewed_at) ||
    !isUtcJobTimestamp(value.expires_at) ||
    !isUtcJobTimestamp(value.next_check_at) ||
    Date.parse(value.renewed_at) < Date.parse(value.created_at) ||
    Date.parse(value.expires_at) - Date.parse(value.renewed_at) !==
      AUTOMATION_GRANT_LIFETIME_MS ||
    Date.parse(value.next_check_at) < Date.parse(value.created_at) ||
    !(
      value.last_checked_at === null ||
      (isUtcJobTimestamp(value.last_checked_at) &&
        Date.parse(value.last_checked_at) >= Date.parse(value.created_at))
    ) ||
    !(
      value.revoked_at === null ||
      (isUtcJobTimestamp(value.revoked_at) &&
        Date.parse(value.revoked_at) >= Date.parse(value.created_at))
    ) ||
    !isSafeJobCode(value.last_error_code) ||
    ((value.state === "revoked") !== (value.revoked_at !== null))
  ) {
    throw new TransportError("Automation grant response was invalid", 200);
  }
  const scope = parseAutomationGrantScope(value.scope);
  if (expectedScope !== undefined && !sameAutomationGrantScope(scope, expectedScope)) {
    throw new TransportError("Automation grant response was invalid", 200);
  }
  return {
    grant_id: value.grant_id,
    revision: value.revision as number,
    scope,
    state: value.state as AutomationGrantRecord["state"],
    created_at: value.created_at,
    renewed_at: value.renewed_at,
    expires_at: value.expires_at,
    next_check_at: value.next_check_at,
    last_checked_at: value.last_checked_at as string | null,
    revoked_at: value.revoked_at as string | null,
    last_error_code: value.last_error_code as string | null,
  };
}

export function parseAutomationGrantList(
  value: unknown,
  expectedProvider: Provider,
): AutomationGrantRecord[] {
  if (!Array.isArray(value) || value.length > 1_000) {
    throw new TransportError("Automation grant list response was invalid", 200);
  }
  const records = value.map((record) => parseAutomationGrantRecord(record));
  if (
    new Set(records.map((record) => record.grant_id)).size !== records.length ||
    records.some((record) => record.scope.provider !== expectedProvider)
  ) {
    throw new TransportError("Automation grant list response was invalid", 200);
  }
  return records;
}

export function parseAutomationPollResult(value: unknown): AutomationPollResult {
  const countKeys = [...AUTOMATION_POLL_RESULT_KEYS].filter((key) => ![
    "maximum_session_runtime_deadline_enforced",
    "session_quality_result_publication_deadline_enforced",
    "blocking_execution_preemption_enforced",
  ].includes(key));
  if (
    !isRecord(value) || !hasExactKeys(value, AUTOMATION_POLL_RESULT_KEYS) ||
    value.maximum_session_runtime_deadline_enforced !== false ||
    value.session_quality_result_publication_deadline_enforced !== true ||
    value.blocking_execution_preemption_enforced !== false ||
    countKeys.some((key) =>
      !Number.isSafeInteger(value[key]) || (value[key] as number) < 0
    ) ||
    (value.grants_revoked as number) +
      (value.grants_power_paused as number) +
      (value.grants_policy_unsupported as number) >
      (value.grants_checked as number) ||
    (value.grants_policy_unsupported as number) > (value.failures as number) ||
    (value.power_external_observations as number) +
      (value.power_battery_observations as number) +
      (value.power_unknown_observations as number) +
      (value.grants_policy_unsupported as number) +
      (value.grants_revoked as number) !==
      (value.grants_checked as number) ||
    (value.grants_power_paused as number) !==
      (value.power_battery_observations as number) +
      (value.power_unknown_observations as number) ||
    (value.jobs_created as number) + (value.jobs_reused as number) >
      (value.candidates_seen as number) ||
    (value.jobs_superseded as number) >
      (value.jobs_created as number) + (value.jobs_reused as number)
  ) {
    throw new TransportError("Automation poll response was invalid", 200);
  }
  return value as unknown as AutomationPollResult;
}

const PREVIEW_KEYS = new Set([
  "preview_id", "created_at", "expires_at", "binding", "messages",
]);
const PREVIEW_BINDING_KEYS = new Set([
  "provider", "session_id", "analysis_window_fingerprint", "metric_keys",
  "destination", "exact_model", "estimator_plan_version", "redactor_version",
  "retention_class", "message_count", "character_count", "cost_state",
  "estimated_cost_microunits", "cost_currency",
]);
const PREVIEW_MESSAGE_KEYS = new Set(["role", "kind", "language", "text"]);
const ANALYSIS_OUTCOME_KEYS = new Set([
  "run_id", "status", "result_count", "applied", "analysis_profile_key",
  "analysis_profile_version",
]);
const SESSION_ANALYSIS_RESPONSE_KEYS = new Set(["run", "results"]);
const SESSION_ANALYSIS_RUN_KEYS = new Set([
  "adapter_version", "analysis_profile_key", "analysis_profile_version",
  "consent_policy_version", "consent_purpose", "content_schema_version",
  "data_tier", "failure_code", "finished_at", "input_fingerprint",
  "local_only", "metric_engine_version", "metric_pack_key",
  "metric_pack_version", "metric_scope_state", "model_plan_fingerprint",
  "provider", "provider_version", "redactor_version", "request_fingerprint",
  "run_id", "schema_version", "selected_metric_keys", "session_id",
  "source_schema_version", "started_at", "status",
]);
const SESSION_ANALYSIS_RESULT_REQUIRED_KEYS = new Set([
  "aggregation_method", "algorithm_id", "algorithm_version", "applicability",
  "computed_at", "coverage", "direction", "eligible_count", "error_code",
  "evidence", "evidence_data_tier", "explanation_code", "fraction", "key",
  "metric_schema_version", "model_id", "model_license", "model_revision",
  "numeric_value", "observed_count", "prompt_version", "rubric_version",
  "signals", "source", "tokenizer_id", "unit", "value_state", "version",
]);
const SESSION_ANALYSIS_RESULT_OPTIONAL_KEYS = new Set([
  "confidence", "description", "dimension", "display_name",
]);
const PREVIEW_MESSAGE_KINDS = new Set([
  "request", "response", "plan", "action", "verification", "decision",
  "feedback", "summary",
]);
const PREVIEW_LANGUAGES = new Set(["en", "pl", "mixed", "unknown"]);

function isUtcTimestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /(?:Z|\+00:00)$/.test(value) &&
    Number.isFinite(Date.parse(value));
}

function parseLocalPreviewBinding(
  value: unknown,
  expectedSessionId: string,
  expectedPresetId: TextAnalysisPresetId,
) {
  if (
    !isRecord(value) || !hasExactKeys(value, PREVIEW_BINDING_KEYS) ||
    value.provider !== "codex" ||
    value.session_id !== expectedSessionId || !PSEUDONYM.test(expectedSessionId) ||
    typeof value.analysis_window_fingerprint !== "string" ||
    !PSEUDONYM.test(value.analysis_window_fingerprint) ||
    !Array.isArray(value.metric_keys) || value.metric_keys.length < 1 ||
    value.metric_keys.length > 100 ||
    value.metric_keys.some((key) => typeof key !== "string" || !READINESS_SAFE_TOKEN.test(key)) ||
    new Set(value.metric_keys).size !== value.metric_keys.length ||
    value.destination !== "local" || value.exact_model !== "none" ||
    typeof value.estimator_plan_version !== "string" ||
    !READINESS_SAFE_TOKEN.test(value.estimator_plan_version) ||
    typeof value.redactor_version !== "string" ||
    !READINESS_SAFE_TOKEN.test(value.redactor_version) ||
    value.retention_class !== "local_ephemeral" ||
    !Number.isInteger(value.message_count) ||
    (value.message_count as number) < 1 || (value.message_count as number) > 500 ||
    !Number.isInteger(value.character_count) ||
    (value.character_count as number) < 1 || (value.character_count as number) > 500_000 ||
    value.cost_state !== "not_applicable" ||
    value.estimated_cost_microunits !== null || value.cost_currency !== null
  ) {
    throw new TransportError("Redaction preview response was invalid", 200);
  }
  if (expectedPresetId === "coaching_profile_v1") {
    const keys = value.metric_keys as string[];
    if (
      keys.length !== COACHING_READINESS_KEYS.length ||
      keys.some((key) => !COACHING_READINESS_KEY_SET.has(key))
    ) {
      throw new TransportError("Redaction preview response was invalid", 200);
    }
  }
  return value;
}

/**
 * Validate the only secret-bearing browser DTO. Unknown fields and every
 * remote/cost-bearing shape fail closed before preview text reaches React.
 */
export function parseSessionQualityAnalysisPreview(
  value: unknown,
  expectedSessionId: string,
  expectedPresetId: TextAnalysisPresetId = "coaching_profile_v1",
): SessionQualityAnalysisPreview {
  if (
    !isRecord(value) || !hasExactKeys(value, PREVIEW_KEYS) ||
    typeof value.preview_id !== "string" || !PSEUDONYM.test(value.preview_id) ||
    !isUtcTimestamp(value.created_at) || !isUtcTimestamp(value.expires_at) ||
    Date.parse(value.expires_at) - Date.parse(value.created_at) !== 600_000 ||
    !Array.isArray(value.messages)
  ) {
    throw new TransportError("Redaction preview response was invalid", 200);
  }
  const binding = parseLocalPreviewBinding(
    value.binding,
    expectedSessionId,
    expectedPresetId,
  );
  const messages = value.messages;
  if (messages.length !== binding.message_count) {
    throw new TransportError("Redaction preview response was invalid", 200);
  }
  let characterCount = 0;
  for (const message of messages) {
    if (
      !isRecord(message) || !hasExactKeys(message, PREVIEW_MESSAGE_KEYS) ||
      !["user", "agent"].includes(message.role as string) ||
      !PREVIEW_MESSAGE_KINDS.has(message.kind as string) ||
      !PREVIEW_LANGUAGES.has(message.language as string) ||
      typeof message.text !== "string" || message.text.length < 1 ||
      Array.from(message.text).length > 32_000
    ) {
      throw new TransportError("Redaction preview response was invalid", 200);
    }
    characterCount += Array.from(message.text).length;
  }
  if (characterCount !== binding.character_count) {
    throw new TransportError("Redaction preview response was invalid", 200);
  }
  return value as unknown as SessionQualityAnalysisPreview;
}

export function parseSessionQualityAnalysisOutcome(
  value: unknown,
): SessionQualityAnalysisOutcome {
  if (
    !isRecord(value) || !hasExactKeys(value, ANALYSIS_OUTCOME_KEYS) ||
    typeof value.run_id !== "string" || !PSEUDONYM.test(value.run_id) ||
    !["running", "completed", "failed"].includes(value.status as string) ||
    !Number.isInteger(value.result_count) ||
    (value.result_count as number) < 0 || (value.result_count as number) > 100 ||
    typeof value.applied !== "boolean" ||
    typeof value.analysis_profile_key !== "string" ||
    !READINESS_SAFE_TOKEN.test(value.analysis_profile_key) ||
    !Number.isInteger(value.analysis_profile_version) ||
    (value.analysis_profile_version as number) < 1
  ) {
    throw new TransportError("Local analysis response was invalid", 200);
  }
  return value as unknown as SessionQualityAnalysisOutcome;
}

function hasRequiredAndAllowedKeys(
  value: Record<string, unknown>,
  required: ReadonlySet<string>,
  optional: ReadonlySet<string>,
): boolean {
  return [...required].every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => required.has(key) || optional.has(key));
}

/**
 * Validate content-free run scope before any quality adapter sees the response.
 * Exact scopes are canonical and must match completed result keys one-for-one;
 * legacy rows deliberately keep an empty selection because their omission
 * provenance is unknowable.
 */
export function parseSessionAnalysisRunResponse(
  value: unknown,
  expected: { sessionId?: string; runId?: string } = {},
): SessionAnalysisRunResponse {
  if (
    !isRecord(value) || !hasExactKeys(value, SESSION_ANALYSIS_RESPONSE_KEYS) ||
    !isRecord(value.run) || !hasExactKeys(value.run, SESSION_ANALYSIS_RUN_KEYS) ||
    !Array.isArray(value.results) || value.results.length > 100
  ) {
    throw new TransportError("Quality analysis response was invalid", 200);
  }
  const run = value.run;
  const positiveInteger = (candidate: unknown) =>
    Number.isSafeInteger(candidate) && (candidate as number) > 0;
  const safeVersion = (candidate: unknown) =>
    typeof candidate === "string" && READINESS_SAFE_TOKEN.test(candidate);
  if (
    typeof run.run_id !== "string" || !PSEUDONYM.test(run.run_id) ||
    typeof run.session_id !== "string" || !PSEUDONYM.test(run.session_id) ||
    (expected.runId !== undefined && run.run_id !== expected.runId) ||
    (expected.sessionId !== undefined && run.session_id !== expected.sessionId) ||
    ![run.request_fingerprint, run.input_fingerprint, run.model_plan_fingerprint]
      .every((item) => typeof item === "string" && PSEUDONYM.test(item)) ||
    ![run.analysis_profile_key, run.metric_pack_key, run.consent_policy_version,
      run.provider_version, run.adapter_version, run.source_schema_version,
      run.content_schema_version, run.metric_engine_version, run.redactor_version]
      .every(safeVersion) ||
    !positiveInteger(run.analysis_profile_version) ||
    !positiveInteger(run.metric_pack_version) ||
    !positiveInteger(run.schema_version) ||
    run.data_tier !== "redacted_content" || run.consent_purpose !== "text_analysis" ||
    run.local_only !== true ||
    !["codex", "claude_code", "synthetic"].includes(run.provider as string) ||
    !["running", "completed", "failed"].includes(run.status as string) ||
    !isUtcTimestamp(run.started_at) ||
    (run.finished_at !== null && !isUtcTimestamp(run.finished_at)) ||
    (run.failure_code !== null && !safeVersion(run.failure_code)) ||
    !Array.isArray(run.selected_metric_keys) || run.selected_metric_keys.length > 100 ||
    run.selected_metric_keys.some((key) => !safeVersion(key)) ||
    !sameArray(
      run.selected_metric_keys as string[],
      [...new Set(run.selected_metric_keys as string[])].sort(),
    ) ||
    !(
      (run.metric_scope_state === "exact" && run.selected_metric_keys.length > 0) ||
      (run.metric_scope_state === "legacy_unknown" && run.selected_metric_keys.length === 0)
    ) ||
    (run.status === "completed" && (run.finished_at === null || run.failure_code !== null)) ||
    (run.status === "running" && (run.finished_at !== null || run.failure_code !== null)) ||
    (run.status === "failed" && (run.finished_at === null || run.failure_code === null))
  ) {
    throw new TransportError("Quality analysis response was invalid", 200);
  }

  const resultKeys: string[] = [];
  const resultIdentities = new Set<string>();
  for (const result of value.results) {
    if (
      !isRecord(result) ||
      !hasRequiredAndAllowedKeys(
        result,
        SESSION_ANALYSIS_RESULT_REQUIRED_KEYS,
        SESSION_ANALYSIS_RESULT_OPTIONAL_KEYS,
      ) ||
      typeof result.key !== "string" || !READINESS_SAFE_TOKEN.test(result.key) ||
      !positiveInteger(result.version)
    ) {
      throw new TransportError("Quality analysis response was invalid", 200);
    }
    const identity = `${result.key}@${String(result.version)}`;
    if (resultIdentities.has(identity)) {
      throw new TransportError("Quality analysis response was invalid", 200);
    }
    resultIdentities.add(identity);
    resultKeys.push(result.key);
  }
  if (
    (run.status === "completed" && run.metric_scope_state === "exact" &&
      !sameArray([...new Set(resultKeys)].sort(), run.selected_metric_keys as string[]))
  ) {
    throw new TransportError("Quality analysis response was invalid", 200);
  }
  return value as unknown as SessionAnalysisRunResponse;
}

/**
 * Return a request target only when the caller supplied a root-relative URL for
 * the current origin. Absolute, protocol-relative, credentialed, and cross-origin
 * targets are rejected before fetch is called.
 */
export function assertSameOriginRelativePath(path: string, origin: string): string {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) {
    throw new TransportError("Only root-relative API paths are allowed", 0);
  }

  const expectedOrigin = new URL(origin).origin;
  const resolved = new URL(path, expectedOrigin);
  if (
    resolved.origin !== expectedOrigin ||
    resolved.username !== "" ||
    resolved.password !== ""
  ) {
    throw new TransportError("Unexpected API origin", 0);
  }
  return `${resolved.pathname}${resolved.search}`;
}

function isJsonResponse(response: Response): boolean {
  return response.headers.get("content-type")?.toLowerCase().includes("application/json") ?? false;
}

/** Parse the deliberately minimal, unauthenticated loopback health response. */
export function parseRuntimeHealth(value: unknown): RuntimeHealth {
  if (
    !isRecord(value) ||
    Object.keys(value).sort().join(",") !== "cost_mode,data_tier,status" ||
    value.status !== "ok" ||
    value.cost_mode !== "offline_only" ||
    value.data_tier !== "metadata"
  ) {
    throw new TransportError("Local runtime health response was invalid", 200);
  }
  return {
    status: "ok",
    costMode: "offline_only",
    dataTier: "metadata",
  };
}

const WORKSPACE_FOLDER_PICKER_CAPABILITY_KEYS = new Set([
  "contract_version", "available", "mode",
]);
const WORKSPACE_FOLDER_PICK_KEYS = new Set([
  "contract_version", "status", "path",
]);

function isAbsoluteWorkspacePath(value: unknown): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= 1024
    && value === value.trim()
    && !/[\u0000-\u001f\u007f]/u.test(value)
    && (
      /^[A-Za-z]:[\\/]/u.test(value)
      || /^\\\\[^\\/]+[\\/][^\\/]+/u.test(value)
      || /^\/(?!\/)/u.test(value)
    );
}

export function parseWorkspaceFolderPickerCapability(
  value: unknown,
): WorkspaceFolderPickerCapability {
  if (
    !isRecord(value)
    || !hasExactKeys(value, WORKSPACE_FOLDER_PICKER_CAPABILITY_KEYS)
    || value.contract_version !== "local-workspace-folder-picker.v1"
    || typeof value.available !== "boolean"
    || !["server_native_dialog", "unavailable"].includes(String(value.mode))
    || value.available !== (value.mode === "server_native_dialog")
  ) {
    throw new TransportError("Workspace folder picker capability response was invalid", 200);
  }
  return value as unknown as WorkspaceFolderPickerCapability;
}

export function parseWorkspaceFolderPick(value: unknown): WorkspaceFolderPick {
  if (
    !isRecord(value)
    || !hasExactKeys(value, WORKSPACE_FOLDER_PICK_KEYS)
    || value.contract_version !== "local-workspace-folder-picker.v1"
    || !["selected", "cancelled", "busy", "unavailable"].includes(String(value.status))
  ) {
    throw new TransportError("Workspace folder picker response was invalid", 200);
  }
  if (value.status === "selected") {
    if (!isAbsoluteWorkspacePath(value.path)) {
      throw new TransportError("Workspace folder picker response was invalid", 200);
    }
  } else if (value.path !== null) {
    throw new TransportError("Workspace folder picker response was invalid", 200);
  }
  return value as unknown as WorkspaceFolderPick;
}

function validManagedMutation(
  managementId: string,
  payload: { request_id: string; expected_revision: number; preview_digest: string },
): boolean {
  return /^[0-9a-f]{32}$/u.test(managementId)
    && /^[0-9a-f]{32}$/u.test(payload.request_id)
    && Number.isInteger(payload.expected_revision)
    && payload.expected_revision >= 1
    && /^[0-9a-f]{64}$/u.test(payload.preview_digest);
}

export function createHttpTransport(options: {
  fetch?: FetchLike;
  origin?: string;
  /** Test/host injection; production defaults to the pywebview native bridge. */
  userPresenceApproval?: (request: {
    method: "POST";
    path: string;
    bodySha256: string;
  }) => Promise<string>;
  /** Test/host injection. Production verifies the live pywebview bridge. */
  userPresenceBridgeAvailable?: () => boolean;
  /** Test/host injection for the bounded pywebview-ready wait. */
  userPresenceBridgeReadyTimeoutMs?: number;
} = {}): LocalRuntimeTransport {
  const fetchRequest = options.fetch ?? globalThis.fetch.bind(globalThis);
  const origin = options.origin ?? globalThis.location.origin;
  let sessionAuth: {
    csrfToken: string;
    refreshAfter: number;
    userPresenceAvailable: boolean;
    userPresenceMode: "unavailable" | "native_bridge_bound_token";
  } | undefined;
  let sessionBootstrap: Promise<string> | undefined;

  async function sha256Utf8(value: string): Promise<string> {
    if (globalThis.crypto?.subtle === undefined) {
      throw new TransportError("Native user-presence hashing is unavailable", 503);
    }
    const digest = new Uint8Array(
      await globalThis.crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(value),
      ),
    );
    return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function desktopUserPresenceApproval(input: {
    method: "POST";
    path: string;
    bodySha256: string;
  }): Promise<string> {
    const host = globalThis as typeof globalThis & {
      pywebview?: {
        api?: {
          confirm_user_presence?: (request: {
            method: "POST";
            path: string;
            body_sha256: string;
          }) => Promise<unknown>;
        };
      };
    };
    const confirm = host.pywebview?.api?.confirm_user_presence;
    if (typeof confirm !== "function") {
      throw new TransportError("Native user-presence confirmation is unavailable", 503);
    }
    const result = await confirm({
      method: input.method,
      path: input.path,
      body_sha256: input.bodySha256,
    });
    if (typeof result !== "object" || result === null || Array.isArray(result)) {
      throw new TransportError("Native user-presence response was invalid", 503);
    }
    const record = result as Record<string, unknown>;
    if (record.version !== "native-user-presence-v1" || typeof record.approved !== "boolean") {
      throw new TransportError("Native user-presence response was invalid", 503);
    }
    if (record.approved === false) {
      if (
        Object.keys(record).sort().join(",") !== "approved,reason,version"
        || ![
          "native_confirmation_unavailable",
          "invalid_confirmation_request",
          "action_not_allowed",
          "user_declined",
        ].includes(String(record.reason))
      ) {
        throw new TransportError("Native user-presence response was invalid", 503);
      }
      throw new TransportError(
        record.reason === "user_declined"
          ? "Native user-presence confirmation was declined"
          : "Native user-presence confirmation is unavailable",
        record.reason === "user_declined" ? 403 : 503,
        record.reason === "user_declined" ? "native_confirmation_declined_before_dispatch" : null,
      );
    }
    if (
      Object.keys(record).sort().join(",") !== "approval_token,approved,version"
      || typeof record.approval_token !== "string"
      || !/^[A-Za-z0-9_-]{32,128}$/.test(record.approval_token)
    ) {
      throw new TransportError("Native user-presence response was invalid", 503);
    }
    return record.approval_token;
  }

  const approveUserPresence = options.userPresenceApproval ?? desktopUserPresenceApproval;
  const bridgeAvailable = options.userPresenceBridgeAvailable
    ?? (options.userPresenceApproval === undefined
      ? hasNativeUserPresenceBridge
      : () => true);
  const userPresenceBridgeIsAvailable = (): boolean => {
    try {
      return bridgeAvailable() === true;
    } catch {
      return false;
    }
  };
  const bridgeReadyTimeoutMs = Math.max(
    0,
    options.userPresenceBridgeReadyTimeoutMs ?? 800,
  );
  const waitForUserPresenceBridge = async (signal?: AbortSignal): Promise<boolean> => {
    signal?.throwIfAborted();
    if (userPresenceBridgeIsAvailable()) return true;
    if (
      typeof globalThis.addEventListener !== "function"
      || typeof globalThis.removeEventListener !== "function"
    ) {
      return false;
    }

    return new Promise<boolean>((resolve, reject) => {
      let settled = false;
      const finish = (available: boolean) => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timeout);
        globalThis.removeEventListener("pywebviewready", handleReady);
        signal?.removeEventListener("abort", handleAbort);
        resolve(available);
      };
      const handleReady = () => finish(userPresenceBridgeIsAvailable());
      const handleAbort = () => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timeout);
        globalThis.removeEventListener("pywebviewready", handleReady);
        signal?.removeEventListener("abort", handleAbort);
        reject(signal?.reason ?? new DOMException("The operation was aborted", "AbortError"));
      };
      const timeout = globalThis.setTimeout(() => finish(false), bridgeReadyTimeoutMs);
      globalThis.addEventListener("pywebviewready", handleReady);
      signal?.addEventListener("abort", handleAbort, { once: true });

      // Close the check/listener race without polling.
      if (signal?.aborted) handleAbort();
      else if (userPresenceBridgeIsAvailable()) finish(true);
    });
  };

  async function bootstrapBrowserSession(): Promise<string> {
    const target = assertSameOriginRelativePath("/auth/session", origin);
    const response = await fetchRequest(target, {
      method: "GET",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new TransportError(
        `Local browser session could not be created (${response.status})`,
        response.status,
      );
    }
    if (!isJsonResponse(response)) {
      throw new TransportError(
        "Local browser session returned an unexpected content type",
        response.status,
      );
    }

    const payload = (await response.json()) as {
      csrf_token?: unknown;
      expires_in_seconds?: unknown;
      user_presence_confirmation_available?: unknown;
      user_presence_confirmation_mode?: unknown;
    };
    if (
      typeof payload.csrf_token !== "string" ||
      payload.csrf_token.length === 0 ||
      typeof payload.expires_in_seconds !== "number" ||
      payload.expires_in_seconds <= 0 ||
      (
        payload.user_presence_confirmation_available !== undefined &&
        typeof payload.user_presence_confirmation_available !== "boolean"
      ) ||
      (
        payload.user_presence_confirmation_mode !== undefined &&
        ![
          "unavailable",
          "native_bridge_bound_token",
        ].includes(String(payload.user_presence_confirmation_mode))
      )
    ) {
      throw new TransportError("Local browser session response was invalid", response.status);
    }
    const userPresenceMode = (
      payload.user_presence_confirmation_mode ?? "unavailable"
    ) as "unavailable" | "native_bridge_bound_token";
    const userPresenceAvailable = payload.user_presence_confirmation_available === true;
    if (userPresenceAvailable !== (userPresenceMode !== "unavailable")) {
      throw new TransportError("Local browser session response was invalid", response.status);
    }
    sessionAuth = {
      csrfToken: payload.csrf_token,
      refreshAfter: Date.now() + Math.max(1, payload.expires_in_seconds - 5) * 1000,
      userPresenceAvailable,
      userPresenceMode,
    };
    return sessionAuth.csrfToken;
  }

  async function ensureBrowserSession(signal?: AbortSignal): Promise<string> {
    signal?.throwIfAborted();
    if (sessionAuth && Date.now() < sessionAuth.refreshAfter) {
      return sessionAuth.csrfToken;
    }

    if (sessionBootstrap === undefined) {
      sessionBootstrap = bootstrapBrowserSession().finally(() => {
        sessionBootstrap = undefined;
      });
    }
    const csrfToken = await sessionBootstrap;
    signal?.throwIfAborted();
    return csrfToken;
  }

  async function request<T>(
    path: string,
    init: RequestInit,
    signal?: AbortSignal,
    readSafeErrorReason = false,
    requirePrivateNoStore = false,
    requireUserPresence = false,
    responseMode: "json" | "no_content" = "json",
  ): Promise<T> {
    const target = assertSameOriginRelativePath(path, origin);
    const method = (init.method ?? "GET").toUpperCase();
    const mutation = !["GET", "HEAD", "OPTIONS"].includes(method);
    let csrfToken = await ensureBrowserSession(signal);
    let userPresenceToken: string | undefined;
    if (requireUserPresence) {
      if (method !== "POST" || typeof init.body !== "string") {
        throw new TransportError("Native user-presence request was invalid", 503);
      }
      if (
        sessionAuth?.userPresenceMode === "native_bridge_bound_token"
        && userPresenceBridgeIsAvailable()
      ) {
        userPresenceToken = await approveUserPresence({
          method: "POST",
          path,
          bodySha256: await sha256Utf8(init.body),
        });
      } else {
        throw new TransportError("Native user-presence confirmation is unavailable", 503);
      }
    }
    const send = (csrf: string) =>
      fetchRequest(target, {
        ...init,
        cache: requirePrivateNoStore ? "no-store" : init.cache,
        credentials: "include",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal,
        headers: {
          Accept: "application/json",
          ...(mutation ? { "X-Prompt-Enhancer-CSRF": csrf } : {}),
          ...(userPresenceToken === undefined
            ? {}
            : { "X-Prompt-Enhancer-User-Presence": userPresenceToken }),
          ...init.headers,
        },
      });
    let response = await send(csrfToken);
    if (response.status === 401) {
      if (sessionAuth?.csrfToken === csrfToken) sessionAuth = undefined;
      csrfToken = await ensureBrowserSession(signal);
      response = await send(csrfToken);
    }

    if (!response.ok) {
      let reasonCode: SafeTransportReasonCode | null = null;
      if (readSafeErrorReason && isJsonResponse(response)) {
        try {
          reasonCode = safeReasonFromErrorPayload(await response.json());
        } catch {
          // Malformed or unexpected server content is deliberately discarded.
        }
      }
      throw new TransportError(
        `Local API request failed (${response.status})`,
        response.status,
        reasonCode,
      );
    }
    if (
      requirePrivateNoStore &&
      (
        response.headers.get("cache-control") !== "no-store, private" ||
        response.headers.get("pragma") !== "no-cache"
      )
    ) {
      throw new TransportError("Private local response was not cache-safe", response.status);
    }
    if (responseMode === "no_content") {
      if (response.status !== 204) {
        throw new TransportError("Local API did not confirm the operation", response.status);
      }
      return undefined as T;
    }
    if (!isJsonResponse(response)) {
      throw new TransportError("Local API returned an unexpected content type", response.status);
    }
    return (await response.json()) as T;
  }

  async function requestAgentArtifactContent(
    path: string,
    expectedDisposition: "inline" | "attachment",
    signal?: AbortSignal,
  ): Promise<AgentArtifactContent> {
    const target = assertSameOriginRelativePath(path, origin);
    const csrfToken = await ensureBrowserSession(signal);
    const send = () => fetchRequest(target, {
      method: "GET",
      cache: "no-store",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal,
      headers: {
        Accept: "application/octet-stream, application/pdf, image/png, image/jpeg, image/gif, text/plain",
      },
    });
    let response = await send();
    if (response.status === 401) {
      if (sessionAuth?.csrfToken === csrfToken) sessionAuth = undefined;
      await ensureBrowserSession(signal);
      response = await send();
    }
    if (!response.ok) {
      throw new TransportError(`Local API request failed (${response.status})`, response.status);
    }
    const contentType = response.headers.get("content-type") ?? "";
    const disposition = response.headers.get("content-disposition") ?? "";
    const dispositionMatch = /^(inline|attachment); filename="(agent-artifact-[0-9a-f]{8}(?:\.[A-Za-z0-9]{1,15})?)"$/u.exec(disposition);
    const lengthText = response.headers.get("content-length") ?? "";
    const byteSize = /^\d{1,8}$/u.test(lengthText) ? Number(lengthText) : Number.NaN;
    const allowedTypes = new Set([
      "application/octet-stream",
      "application/pdf",
      "image/png",
      "image/jpeg",
      "image/gif",
      "text/plain; charset=utf-8",
    ]);
    if (
      response.status !== 200
      || response.headers.get("cache-control") !== "no-store, private"
      || response.headers.get("pragma") !== "no-cache"
      || response.headers.get("accept-ranges") !== "bytes"
      || response.headers.get("content-security-policy") !== "default-src 'none'; sandbox"
      || response.headers.get("referrer-policy") !== "no-referrer"
      || response.headers.get("x-content-type-options") !== "nosniff"
      || dispositionMatch === null
      || dispositionMatch[1] !== expectedDisposition
      || !allowedTypes.has(contentType)
      || !Number.isSafeInteger(byteSize)
      || byteSize < 0
      || byteSize > 24 * 1024 * 1024
    ) {
      throw new TransportError("Agent artifact content response was invalid", response.status);
    }
    const blob = await response.blob();
    if (blob.size !== byteSize) {
      throw new TransportError("Agent artifact content response was invalid", response.status);
    }
    return {
      blob,
      contentType,
      filename: dispositionMatch[2],
      byteSize,
    };
  }

  async function requestAgentAttachmentContent(
    path: string,
    signal?: AbortSignal,
  ): Promise<AgentAttachmentContent> {
    const target = assertSameOriginRelativePath(path, origin);
    const csrfToken = await ensureBrowserSession(signal);
    const send = () => fetchRequest(target, {
      method: "GET",
      cache: "no-store",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal,
      headers: { Accept: "image/png, image/jpeg, audio/wav" },
    });
    let response = await send();
    if (response.status === 401) {
      if (sessionAuth?.csrfToken === csrfToken) sessionAuth = undefined;
      await ensureBrowserSession(signal);
      response = await send();
    }
    if (!response.ok) {
      throw new TransportError(`Local API request failed (${response.status})`, response.status);
    }
    const contentType = response.headers.get("content-type") ?? "";
    const disposition = response.headers.get("content-disposition") ?? "";
    const dispositionMatch = /^inline; filename="(agent-attachment-[0-9a-f]{8}\.(?:png|jpg|wav))"$/u.exec(disposition);
    const lengthText = response.headers.get("content-length") ?? "";
    const byteSize = /^\d{1,8}$/u.test(lengthText) ? Number(lengthText) : Number.NaN;
    if (
      response.status !== 200
      || response.headers.get("cache-control") !== "no-store, private"
      || response.headers.get("pragma") !== "no-cache"
      || response.headers.get("content-security-policy") !== "default-src 'none'; sandbox"
      || response.headers.get("cross-origin-resource-policy") !== "same-origin"
      || response.headers.get("referrer-policy") !== "no-referrer"
      || response.headers.get("x-content-type-options") !== "nosniff"
      || dispositionMatch === null
      || !["image/png", "image/jpeg", "audio/wav"].includes(contentType)
      || !Number.isSafeInteger(byteSize)
      || byteSize < 1
      || byteSize > 12 * 1024 * 1024
    ) throw new TransportError("Agent attachment content response was invalid", response.status);
    const blob = await response.blob();
    if (blob.size !== byteSize || blob.type !== contentType) {
      throw new TransportError("Agent attachment content response was invalid", response.status);
    }
    return {
      blob,
      contentType: contentType as AgentAttachmentContent["contentType"],
      filename: dispositionMatch[1],
      byteSize,
    };
  }

  async function applicationUpdateMutation(
    action: ApplicationUpdateAction,
    payload: ApplicationUpdateMutationRequest,
    signal?: AbortSignal,
  ): Promise<ApplicationUpdateStatus> {
    if (
      !Number.isSafeInteger(payload.expected_revision)
      || payload.expected_revision < 0
      || !/^[0-9a-f]{32}$/u.test(payload.expected_instance_id)
    ) {
      throw new TransportError("Application update request was invalid", 422);
    }
    const value = await request<unknown>(
      `/v1/application-updates/${action}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      signal,
      false,
      true,
    );
    try {
      return parseApplicationUpdateStatus(value);
    } catch (error) {
      if (error instanceof ApplicationUpdatePayloadError) {
        throw new TransportError(error.message, 200);
      }
      throw error;
    }
  }

  return {
    runtimeKind: "local_loopback",
    async getApplicationUpdateStatus(signal) {
      const value = await request<unknown>(
        "/v1/application-updates/status",
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseApplicationUpdateStatus(value);
      } catch (error) {
        if (error instanceof ApplicationUpdatePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async checkApplicationUpdate(payload, signal) {
      return applicationUpdateMutation("check", payload, signal);
    },
    async stageApplicationUpdate(payload, signal) {
      return applicationUpdateMutation("stage", payload, signal);
    },
    async cancelApplicationUpdate(payload, signal) {
      return applicationUpdateMutation("cancel", payload, signal);
    },
    async retryApplicationUpdate(payload, signal) {
      return applicationUpdateMutation("retry", payload, signal);
    },
    async verifyApplicationUpdate(payload, signal) {
      return applicationUpdateMutation("verify", payload, signal);
    },
    async getUserPresenceCapability(signal) {
      await ensureBrowserSession(signal);
      const serverCapabilityAvailable = sessionAuth?.userPresenceAvailable === true
        && sessionAuth.userPresenceMode === "native_bridge_bound_token";
      const confirmationAvailable = serverCapabilityAvailable
        && await waitForUserPresenceBridge(signal);
      return {
        contract_version: "native-user-presence-capability-v1",
        confirmation_available: confirmationAvailable,
        mode: confirmationAvailable ? "native_bridge_bound_token" : "unavailable",
      };
    },
    async getWorkspaceFolderPickerCapability(signal) {
      const value = await request<unknown>(
        "/v1/local-ui/workspace-folder-picker",
        { method: "GET" },
        signal,
        false,
        true,
      );
      return parseWorkspaceFolderPickerCapability(value);
    },
    async chooseWorkspaceFolder(signal) {
      const value = await request<unknown>(
        "/v1/local-ui/workspace-folder-picker",
        { method: "POST" },
        signal,
        false,
        true,
      );
      return parseWorkspaceFolderPick(value);
    },
    async getControlPlaneReadiness(signal) {
      const value = await request<unknown>(
        "/v1/control-plane/readiness",
        { method: "GET" },
        signal,
        false,
        true,
      );
      return parseControlPlaneReadiness(value);
    },
    async getRuntimeHealth(signal) {
      signal?.throwIfAborted();
      const target = assertSameOriginRelativePath("/health", origin);
      const response = await fetchRequest(target, {
        method: "GET",
        credentials: "include",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new TransportError(
          `Local runtime health check failed (${response.status})`,
          response.status,
        );
      }
      if (!isJsonResponse(response)) {
        throw new TransportError(
          "Local runtime health returned an unexpected content type",
          response.status,
        );
      }
      return parseRuntimeHealth(await response.json());
    },
    getTextAnalysisResearch(signal) {
      return request<TextAnalysisResearchCatalog>(
        "/v1/research/text-analysis-methods",
        { method: "GET" },
        signal,
      );
    },
    async getMetricOperabilityCatalog(signal) {
      const value = await request<unknown>(
        "/v1/metric-contracts/v2/operability-catalog",
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseMetricOperabilityCatalog(value);
      } catch (error) {
        if (error instanceof MetricOperabilityDefinitionsOutOfDateError) {
          throw error;
        }
        if (error instanceof MetricOperabilityPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    getTextModelRuntime(signal) {
      return request(
        "/v1/research/text-model-runtime",
        { method: "GET" },
        signal,
      );
    },
    async getTextModelCompatibility(signal) {
      const value = await request<unknown>(
        "/v1/research/text-model-compatibility",
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseModelCompatibilityCatalog(value);
      } catch (error) {
        if (error instanceof ModelCompatibilityPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getModelLabInventory(signal) {
      const value = await request<unknown>(
        "/v1/estimators/plans",
        { method: "GET" },
        signal,
        false,
        true,
      );
      return parseModelLabInventory(value);
    },
    startTextModelEvaluation(body, signal) {
      return request(
        "/v1/research/text-model-evaluations",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
        signal,
      );
    },
    getTextModelEvaluation(jobId, signal) {
      return request(
        `/v1/research/text-model-evaluations/${encodeURIComponent(jobId)}`,
        { method: "GET" },
        signal,
      );
    },
    async getSessionTextAnalysisCapability(signal) {
      const value = await request<unknown>(
        "/v1/capabilities",
        { method: "GET" },
        signal,
      );
      return parseSessionTextAnalysisCapability(value);
    },
    async getProviderCompatibility(provider, signal) {
      const value = await request<unknown>(
        `/v1/providers/${encodeURIComponent(provider)}/compatibility`,
        { method: "GET" },
        signal,
      );
      return parseProviderCompatibilityStatus(value, provider);
    },
    async getProviderMetricCapabilities(provider, signal) {
      const value = await request<unknown>(
        `/v1/providers/${encodeURIComponent(provider)}/capabilities`,
        { method: "GET" },
        signal,
      );
      return parseProviderCapabilityReport(value, provider);
    },
    async getMetricCoverage(provider, signal) {
      const value = await request<unknown>(
        `/v1/metric-coverage?provider=${encodeURIComponent(provider)}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      return parseMetricCoverageReport(value, provider, "provider_catalog");
    },
    async getProjectMetricCoverage(projectId, provider, signal) {
      const value = await request<unknown>(
        `/v1/projects/${encodeURIComponent(projectId)}/metric-coverage?provider=${encodeURIComponent(provider)}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      return parseMetricCoverageReport(value, provider, "one_project");
    },
    async getSessionMetricReadiness(
      sessionId,
      presetId = "coaching_profile_v1",
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/metric-readiness?preset_id=${encodeURIComponent(presetId)}`,
        { method: "GET" },
        signal,
      );
      return parseSessionMetricReadinessReport(value, sessionId, presetId);
    },
    async checkProviderCompatibility(provider, signal) {
      const value = await request<unknown>(
        `/v1/providers/${encodeURIComponent(provider)}/compatibility/check`,
        { method: "POST" },
        signal,
      );
      return parseProviderCompatibilityStatus(value, provider);
    },
    getCodexLocalSourceStatus(signal) {
      return request<CodexLocalSourceStatus>(
        "/v1/local-sources/codex",
        { method: "GET" },
        signal,
      );
    },
    grantCodexLocalHistoryConsent(signal) {
      return request<CodexLocalSourceStatus>(
        "/v1/local-sources/codex/consents/local-history",
        { method: "POST" },
        signal,
      );
    },
    revokeCodexLocalHistoryConsent(signal) {
      return request<CodexLocalSourceStatus>(
        "/v1/local-sources/codex/consents/local-history",
        { method: "DELETE" },
        signal,
      );
    },
    getOnboardingStatus(signal) {
      return request<OnboardingStatus>("/v1/onboarding", { method: "GET" }, signal);
    },
    judgeSessionWithModel(sessionId, signal) {
      return request<JudgeOutcome>(`/v1/model-judge/sessions/${encodeURIComponent(sessionId)}`, { method: "POST" }, signal, true);
    },
    startModelJudgeSweep(signal, scope = "sample") {
      return request<JudgeSweepStatus>(`/v1/model-judge/sweep?scope=${scope}`, { method: "POST" }, signal, true);
    },
    getModelJudgeSweep(signal) {
      return request<JudgeSweepStatus>("/v1/model-judge/sweep", { method: "GET" }, signal);
    },
    getPromptCheckConfiguration(signal) {
      return request<PromptCheckConfiguration>("/v1/prompt-checks/configuration", { method: "GET" }, signal);
    },
    previewPrompt(payload, signal) {
      return request<PromptCheckPreview>("/v1/prompt-checks/preview",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, signal);
    },
    checkPrompt(payload, signal) {
      return request<PromptCheckResult>(
        "/v1/prompt-checks",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
      );
    },
    getPromptCheckHistory(limit, offset, signal) {
      return request<PromptCheckHistory>(`/v1/prompt-checks?limit=${limit}&offset=${offset}`, { method: "GET" }, signal);
    },
    getPromptCheck(checkId, signal) {
      return request<PromptCheckRecord>(`/v1/prompt-checks/${encodeURIComponent(checkId)}`, { method: "GET" }, signal);
    },
    async getAgentOrchestration(signal) {
      const value = await request<unknown>(
        "/v1/agent/orchestration",
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentOrchestrationResponse(value);
    },
    async getAgentHardening(signal) {
      const value = await request<unknown>(
        "/v1/diagnostics/agent-hardening",
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentHardeningResponse(value);
    },
    async listAgentMcpConnections(signal) {
      const value = await request<unknown>(
        "/v1/integrations/agent-mcp/connections",
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentMcpConnectionList(value);
      } catch (error) {
        if (error instanceof AgentMcpConnectionPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getAgentMcpClientSetup(signal) {
      const value = await request<unknown>(
        "/v1/integrations/agent-mcp/setup",
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentMcpClientSetup(value);
      } catch (error) {
        if (error instanceof AgentMcpConnectionPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async listMcpRegistryCatalog(query = {}, signal) {
      const search = query.search ?? "";
      const normalizedSearch = search.normalize("NFC").trim().replace(/\s+/gu, " ");
      const cursor = query.cursor;
      const limit = query.limit ?? 24;
      if (
        !isSafeMcpRegistryText(normalizedSearch, 0, 100)
        || /\p{C}/u.test(search)
        || (cursor !== undefined && (
          !isSafeMcpRegistryText(cursor, 1, 512)
        ))
        || !Number.isInteger(limit)
        || limit < 1
        || limit > 48
      ) {
        throw new TransportError("MCP Registry catalog query was invalid", 422);
      }
      const params = new URLSearchParams();
      if (normalizedSearch !== "") params.set("search", normalizedSearch);
      if (cursor !== undefined) params.set("cursor", cursor);
      params.set("limit", String(limit));
      const value = await request<unknown>(
        `/v1/integrations/mcp-store/catalog?${params.toString()}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        const catalog = parseMcpRegistryCatalog(value);
        if (catalog.search !== normalizedSearch) {
          throw new McpRegistryCatalogPayloadError();
        }
        return catalog;
      } catch (error) {
        if (error instanceof McpRegistryCatalogPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
        }
      },
      async getMcpRegistryServerReview(query, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(query.catalog_id)
          || query.name.length < 3
          || query.name.length > 241
          || !/^[A-Za-z0-9.-]{1,160}\/[A-Za-z0-9._-]{1,80}$/u.test(query.name)
          || query.version.length < 1
          || query.version.length > 255
          || !isSafeMcpRegistryText(query.version, 1, 255)
          || !/^[0-9a-f]{64}$/u.test(query.presentation_revision)
        ) {
          throw new TransportError("MCP Registry server identity was invalid", 422);
        }
        const params = new URLSearchParams({
          name: query.name,
          version: query.version,
          presentation_revision: query.presentation_revision,
        });
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/servers/${query.catalog_id}/review?${params.toString()}`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const review = parseMcpRegistryServerReview(value);
          if (
            review.server.catalog_id !== query.catalog_id
            || review.server.name !== query.name
            || review.server.version !== query.version
            || review.server.presentation_revision !== query.presentation_revision
          ) {
            throw new McpRegistryServerReviewPayloadError();
          }
          return review;
        } catch (error) {
          if (error instanceof McpRegistryServerReviewPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async listMcpManagedServers(signal) {
        const value = await request<unknown>(
          "/v1/integrations/mcp-store/managed",
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          return parseMcpManagedServerList(value);
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedServer(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed-server identity was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const server = parseMcpManagedServer(value);
          if (server.management_id !== managementId) throw new McpManagedServerPayloadError();
          return server;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedToolSnapshot(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed-server identity was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/tools`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const snapshot = parseMcpManagedToolSnapshot(value);
          if (snapshot.management_id !== managementId) {
            throw new McpManagedServerPayloadError();
          }
          return snapshot;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedHostStatus(managementId, projectId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId) || !/^[0-9a-f]{32}$/u.test(projectId)) {
          throw new TransportError("MCP managed-host identity was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/projects/${projectId}/host`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const status = parseMcpManagedHostStatus(value);
          if (status.management_id !== managementId || status.project_id !== projectId) {
            throw new McpManagedRuntimePayloadError();
          }
          return status;
        } catch (error) {
          if (error instanceof McpManagedRuntimePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedHostStartPreview(
        managementId,
        projectId,
        expectedServerRevision,
        expectedProjectBindingRevision,
        expectedToolSnapshotId,
        signal,
      ) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(projectId)
          || !Number.isInteger(expectedServerRevision) || expectedServerRevision < 1
          || !Number.isInteger(expectedProjectBindingRevision) || expectedProjectBindingRevision < 1
          || !/^[0-9a-f]{32}$/u.test(expectedToolSnapshotId)
        ) {
          throw new TransportError("MCP managed-host preview request was invalid", 422);
        }
        const params = new URLSearchParams({
          expected_server_revision: String(expectedServerRevision),
          expected_project_binding_revision: String(expectedProjectBindingRevision),
          expected_tool_snapshot_id: expectedToolSnapshotId,
        });
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/projects/${projectId}/host/start-preview?${params.toString()}`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedHostStartPreview(value);
          if (
            preview.binding.management_id !== managementId
            || preview.binding.project_id !== projectId
            || preview.binding.server_revision !== expectedServerRevision
            || preview.binding.project_binding_revision !== expectedProjectBindingRevision
            || preview.binding.tool_snapshot_id !== expectedToolSnapshotId
          ) throw new McpManagedRuntimePayloadError();
          return preview;
        } catch (error) {
          if (error instanceof McpManagedRuntimePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async startMcpManagedHost(managementId, projectId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(projectId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_server_revision) || payload.expected_server_revision < 1
          || !Number.isInteger(payload.expected_project_binding_revision) || payload.expected_project_binding_revision < 1
          || !/^[0-9a-f]{32}$/u.test(payload.expected_tool_snapshot_id)
          || !/^[0-9a-f]{64}$/u.test(payload.preview_digest)
          || (payload.deadline_seconds !== undefined
            && (!Number.isFinite(payload.deadline_seconds)
              || payload.deadline_seconds < 0.1 || payload.deadline_seconds > 20))
        ) throw new TransportError("MCP managed-host start request was invalid", 422);
        const path = `/v1/integrations/mcp-store/managed/${managementId}/projects/${projectId}/host/start`;
        const value = await request<unknown>(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }, signal, true, true, true);
        try {
          const status = parseMcpManagedHostStatus(value);
          if (status.management_id !== managementId || status.project_id !== projectId
            || status.state !== "ready"
            || status.binding?.server_revision !== payload.expected_server_revision
            || status.binding.project_binding_revision !== payload.expected_project_binding_revision
            || status.binding.tool_snapshot_id !== payload.expected_tool_snapshot_id) {
            throw new McpManagedRuntimePayloadError();
          }
          return status;
        } catch (error) {
          if (error instanceof McpManagedRuntimePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async stopMcpManagedHost(managementId, projectId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(projectId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || (payload.expected_instance_id !== null
            && !/^[0-9a-f]{32}$/u.test(payload.expected_instance_id))
          || (payload.deadline_seconds !== undefined
            && (!Number.isFinite(payload.deadline_seconds)
              || payload.deadline_seconds < 0.1 || payload.deadline_seconds > 20))
        ) throw new TransportError("MCP managed-host stop request was invalid", 422);
        const path = `/v1/integrations/mcp-store/managed/${managementId}/projects/${projectId}/host/stop`;
        const value = await request<unknown>(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }, signal, true, true);
        try {
          const status = parseMcpManagedHostStatus(value);
          if (status.management_id !== managementId || status.project_id !== projectId
            || status.state !== "not_started") throw new McpManagedRuntimePayloadError();
          return status;
        } catch (error) {
          if (error instanceof McpManagedRuntimePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedProjectRuntime(projectId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(projectId)) {
          throw new TransportError("MCP managed project identity was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/agent/mcp/projects/${projectId}/runtime`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const runtime = parseMcpManagedProjectRuntime(value);
          if (runtime.project_id !== projectId) throw new McpManagedRuntimePayloadError();
          return runtime;
        } catch (error) {
          if (error instanceof McpManagedRuntimePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async createMcpManagedServer(payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !/^[0-9a-f]{32}$/u.test(payload.catalog_id)
          || !/^[A-Za-z0-9.-]{1,160}\/[A-Za-z0-9._-]{1,80}$/u.test(payload.name)
          || payload.version.length < 1 || payload.version.length > 255
          || payload.version.trim() !== payload.version
          || /[\u0000-\u001f\u007f]/u.test(payload.version)
          || !/^[0-9a-f]{32}$/u.test(payload.option_id)
          || !/^[0-9a-f]{64}$/u.test(payload.plan_revision)
        ) {
          throw new TransportError("MCP managed-server plan was invalid", 422);
        }
        const value = await request<unknown>(
          "/v1/integrations/mcp-store/managed",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedServerReceipt(value);
          if (
            receipt.server.catalog_id !== payload.catalog_id
            || receipt.server.server_name !== payload.name
            || receipt.server.server_version !== payload.version
            || receipt.server.option_id !== payload.option_id
            || receipt.server.plan_revision !== payload.plan_revision
          ) throw new McpManagedServerPayloadError();
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async probeMcpManagedServer(managementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision)
          || payload.expected_revision < 1
        ) {
          throw new TransportError("MCP managed-server probe request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/probe`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedProbeReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.probe.request_id !== payload.request_id) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLifecyclePreview(managementId, action, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !["install", "uninstall"].includes(action)
        ) {
          throw new TransportError("MCP managed lifecycle preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/${action}-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLifecyclePreview(value);
          if (preview.management_id !== managementId || preview.action !== action) {
            throw new McpManagedServerPayloadError();
          }
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLocalConfigurationInspectionPreview(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP package configuration inspection preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/configuration-inspection-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLocalConfigurationInspectionPreview(value);
          if (preview.management_id !== managementId) {
            throw new McpManagedServerPayloadError();
          }
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async inspectMcpManagedLocalConfiguration(managementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision)
          || payload.expected_revision < 1
          || !/^[0-9a-f]{64}$/u.test(payload.preview_digest)
        ) {
          throw new TransportError("MCP package configuration inspection request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/configuration-inspection`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLocalConfigurationInspectionReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async applyMcpManagedLifecycle(managementId, action, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !["install", "uninstall"].includes(action)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision)
          || payload.expected_revision < 1
          || !/^[0-9a-f]{64}$/u.test(payload.preview_digest)
        ) {
          throw new TransportError("MCP managed lifecycle request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/${action}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLifecycleReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.action !== action
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLocalCleanupPreview(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed cleanup preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/cleanup-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLocalCleanupPreview(value);
          if (preview.management_id !== managementId) {
            throw new McpManagedServerPayloadError();
          }
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLocalUpdatePreview(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed update preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/update-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLocalUpdatePreview(value);
          if (preview.management_id !== managementId) {
            throw new McpManagedServerPayloadError();
          }
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async applyMcpManagedLocalUpdate(managementId, payload, signal) {
        if (!validManagedMutation(managementId, payload)) {
          throw new TransportError("MCP managed update request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/update`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLocalUpdateReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLocalRollbackPreview(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed rollback preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/rollback-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLocalRollbackPreview(value);
          if (preview.management_id !== managementId) throw new McpManagedServerPayloadError();
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async applyMcpManagedLocalRollback(managementId, payload, signal) {
        if (!validManagedMutation(managementId, payload)) {
          throw new TransportError("MCP managed rollback request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/rollback`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLocalRollbackReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLocalRollbackCleanupPreview(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed rollback cleanup preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/rollback-cleanup-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLocalRollbackCleanupPreview(value);
          if (preview.management_id !== managementId) throw new McpManagedServerPayloadError();
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async cleanupMcpManagedLocalRollback(managementId, payload, signal) {
        if (!validManagedMutation(managementId, payload)) {
          throw new TransportError("MCP managed rollback cleanup request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/rollback-cleanup`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLocalRollbackCleanupReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async getMcpManagedLocalOperationRecoveryPreview(managementId, signal) {
        if (!/^[0-9a-f]{32}$/u.test(managementId)) {
          throw new TransportError("MCP managed recovery preview was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/recovery-preview`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const preview = parseMcpManagedLocalOperationRecoveryPreview(value);
          if (preview.management_id !== managementId) throw new McpManagedServerPayloadError();
          return preview;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async recoverMcpManagedLocalOperation(managementId, payload, signal) {
        if (!validManagedMutation(managementId, payload)) {
          throw new TransportError("MCP managed recovery request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/recovery`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLocalOperationRecoveryReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async completeMcpManagedLocalCleanup(managementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision)
          || payload.expected_revision < 1
          || !/^[0-9a-f]{64}$/u.test(payload.preview_digest)
        ) {
          throw new TransportError("MCP managed cleanup request was invalid", 422);
        }
        const value = await request<unknown>(
          `/v1/integrations/mcp-store/managed/${managementId}/cleanup`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedLocalCleanupReceipt(value);
          if (receipt.server.management_id !== managementId
            || receipt.preview_digest !== payload.preview_digest) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async setMcpManagedProjectBinding(managementId, projectId, payload, signal) {
        const permissionOrder = [
          "process_spawn", "filesystem_read", "filesystem_write", "network_egress", "credential_use",
        ] as const;
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(projectId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision) || payload.expected_revision < 1
          || typeof payload.enabled !== "boolean"
          || !Array.isArray(payload.granted_permissions)
          || payload.granted_permissions.some((item) => !permissionOrder.includes(item))
          || new Set(payload.granted_permissions).size !== payload.granted_permissions.length
          || permissionOrder.filter((item) => payload.granted_permissions.includes(item)).join("\u0000") !== payload.granted_permissions.join("\u0000")
          || (!payload.enabled && payload.granted_permissions.length > 0)
          || !Array.isArray(payload.admitted_tool_ids)
          || payload.admitted_tool_ids.length > 256
          || payload.admitted_tool_ids.some((item) => !/^[0-9a-f]{32}$/u.test(item))
          || new Set(payload.admitted_tool_ids).size !== payload.admitted_tool_ids.length
          || [...payload.admitted_tool_ids].sort().join("\u0000") !== payload.admitted_tool_ids.join("\u0000")
          || (payload.enabled ? payload.admitted_tool_ids.length === 0 : payload.admitted_tool_ids.length > 0)
        ) {
          throw new TransportError("MCP managed project binding was invalid", 422);
        }
        const path = `/v1/integrations/mcp-store/managed/${managementId}/projects/${projectId}`;
        const value = await request<unknown>(
          path,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedServerReceipt(value);
          const binding = receipt.server.project_bindings.find((item) => item.project_id === projectId);
          if (receipt.server.management_id !== managementId || binding === undefined
            || binding.enabled !== payload.enabled
            || binding.granted_permissions.join("\u0000") !== payload.granted_permissions.join("\u0000")
            || binding.admitted_tool_ids.join("\u0000") !== payload.admitted_tool_ids.join("\u0000")) {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async storeMcpManagedSecret(managementId, requirementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(requirementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision) || payload.expected_revision < 1
          || typeof payload.value !== "string" || payload.value.length < 1 || payload.value.length > 2_048
          || payload.value.includes("\u0000")
          || new TextEncoder().encode(payload.value).byteLength > 2_048
        ) {
          throw new TransportError("MCP managed secret request was invalid", 422);
        }
        const path = `/v1/integrations/mcp-store/managed/${managementId}/secrets/${requirementId}`;
        const value = await request<unknown>(
          path,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedServerReceipt(value);
          const requirement = receipt.server.requirements.find((item) => item.requirement_id === requirementId);
          if (receipt.server.management_id !== managementId
            || requirement?.configuration_state !== "secret_stored") {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async removeMcpManagedSecret(managementId, requirementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(requirementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision) || payload.expected_revision < 1
        ) {
          throw new TransportError("MCP managed secret-removal request was invalid", 422);
        }
        const path = `/v1/integrations/mcp-store/managed/${managementId}/secrets/${requirementId}/remove`;
        const value = await request<unknown>(
          path,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedServerReceipt(value);
          const requirement = receipt.server.requirements.find((item) => item.requirement_id === requirementId);
          if (receipt.server.management_id !== managementId
            || requirement?.configuration_state !== "secret_missing") {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async storeMcpManagedConfiguration(managementId, requirementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(requirementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision) || payload.expected_revision < 1
          || typeof payload.value !== "string" || payload.value.length < 1 || payload.value.length > 2_048
          || /[\u0000\r\n]/u.test(payload.value)
          || new TextEncoder().encode(payload.value).byteLength > 2_048
        ) {
          throw new TransportError("MCP managed configuration request was invalid", 422);
        }
        const path = `/v1/integrations/mcp-store/managed/${managementId}/configuration/${requirementId}`;
        const value = await request<unknown>(
          path,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedServerReceipt(value);
          const requirement = receipt.server.requirements.find((item) => item.requirement_id === requirementId);
          if (receipt.server.management_id !== managementId
            || requirement?.configuration_state !== "value_stored") {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async removeMcpManagedConfiguration(managementId, requirementId, payload, signal) {
        if (
          !/^[0-9a-f]{32}$/u.test(managementId)
          || !/^[0-9a-f]{32}$/u.test(requirementId)
          || !/^[0-9a-f]{32}$/u.test(payload.request_id)
          || !Number.isInteger(payload.expected_revision) || payload.expected_revision < 1
        ) {
          throw new TransportError("MCP managed configuration-removal request was invalid", 422);
        }
        const path = `/v1/integrations/mcp-store/managed/${managementId}/configuration/${requirementId}/remove`;
        const value = await request<unknown>(
          path,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
          true,
          true,
        );
        try {
          const receipt = parseMcpManagedServerReceipt(value);
          const requirement = receipt.server.requirements.find((item) => item.requirement_id === requirementId);
          if (receipt.server.management_id !== managementId
            || requirement?.configuration_state !== "value_required") {
            throw new McpManagedServerPayloadError();
          }
          return receipt;
        } catch (error) {
          if (error instanceof McpManagedServerPayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      },
      async createAgentMcpConnection(payload, signal) {
      const value = await request<unknown>(
        "/v1/integrations/agent-mcp/connections",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentMcpConnectionCredential(value);
      } catch (error) {
        if (error instanceof AgentMcpConnectionPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async rotateAgentMcpConnection(connectionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/integrations/agent-mcp/connections/${encodeURIComponent(connectionId)}/rotate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentMcpConnectionCredential(value);
      } catch (error) {
        if (error instanceof AgentMcpConnectionPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async revokeAgentMcpConnection(connectionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/integrations/agent-mcp/connections/${encodeURIComponent(connectionId)}/revoke`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentMcpConnection(value);
      } catch (error) {
        if (error instanceof AgentMcpConnectionPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async releaseAgentControllerOwnership(payload, signal) {
      const value = await request<unknown>(
        "/v1/integrations/agent-mcp/connections/ownerships/release",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentControllerOwnershipReleaseReceipt(value);
      } catch (error) {
        if (error instanceof AgentMcpConnectionPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async beginAgentNativeAcceptance(payload, signal) {
      const value = await request<unknown>(
        "/v1/diagnostics/agent-native-acceptance/start",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        signal,
        true,
        true,
        true,
      );
      return agentNativeAcceptanceResponse(value);
    },
    async listAgentProjects(query, signal) {
      const value = await request<unknown>(
        `/v1/agent/projects${agentCatalogQuery(query)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentProjectListResponse(value);
    },
    async pageAgentProjects(query, signal) {
      const prepared = agentCatalogPageQuery(query, 200);
      const value = await request<unknown>(
        `/v1/agent/projects/page${prepared.encoded}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentProjectPageResponse(
        value,
        prepared.limit,
        prepared.offset,
        prepared.snapshot,
      );
    },
    async createAgentProject(project, signal) {
      const value = await request<unknown>(
        "/v1/agent/projects",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(project),
        },
        signal,
        true,
        true,
      );
      return agentProjectResponse(value);
    },
    async getAgentProject(projectId, signal) {
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentProjectResponse(value, projectId);
    },
    async updateAgentProject(projectId, project, signal) {
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(project),
        },
        signal,
        true,
        true,
      );
      return agentProjectResponse(value, projectId);
    },
    async deleteAgentProject(projectId, command, signal) {
      const query = new URLSearchParams({
        expected_revision: String(command.expected_revision),
      });
      await request<void>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}?${query.toString()}`,
        { method: "DELETE" },
        signal,
        true,
        true,
        false,
        "no_content",
      );
    },
    async listAgentCatalogSessions(query: AgentCatalogSessionQuery = {}, signal) {
      const { projectId, ...catalogQuery } = query;
      const path = projectId === undefined
        ? "/v1/agent/catalog/sessions"
        : `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions`;
      const value = await request<unknown>(
        `${path}${agentCatalogQuery(catalogQuery)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentCatalogSessionListResponse(value, projectId);
    },
    async searchAgentSavedMessages(search: AgentMessageSearchRequest, signal) {
      const query = typeof search.query === "string" ? search.query.replace(/\s+/gu, " ").trim() : "";
      if (query.length < 1 || Array.from(query).length > 120 || typeof search.includeArchived !== "undefined" && typeof search.includeArchived !== "boolean"
        || (search.projectId !== undefined && !/^[0-9a-f]{32}$/u.test(search.projectId))
        || (search.limit !== undefined && (!Number.isInteger(search.limit) || search.limit < 1 || search.limit > 50))
        || (search.offset !== undefined && (!Number.isInteger(search.offset) || search.offset < 0 || search.offset > 2000))
        || (search.snapshot !== undefined && !/^[0-9a-f]{64}$/u.test(search.snapshot))) {
        throw new TransportError("Agent message search request was invalid", 422);
      }
      const prepared: AgentMessageSearchRequest = { ...search, query, includeArchived: search.includeArchived ?? false, limit: search.limit ?? 20, offset: search.offset ?? 0 };
      if (prepared.offset !== undefined && prepared.offset > 0 && prepared.snapshot === undefined) throw new TransportError("Agent message search continuation requires a snapshot", 422);
      const value = await request<unknown>(
        "/v1/agent/catalog/sessions/message-search",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: prepared.query, project_id: prepared.projectId ?? null, include_archived: prepared.includeArchived, limit: prepared.limit, offset: prepared.offset, ...(prepared.snapshot === undefined ? {} : { snapshot: prepared.snapshot }) }) },
        signal,
        true,
        true,
      );
      return agentMessageSearchResponse(value, prepared);
    },
    async pageAgentCatalogSessions(
      query: AgentCatalogSessionPageQuery = {},
      signal,
    ) {
      const { projectId, ...catalogQuery } = query;
      const prepared = agentCatalogPageQuery(catalogQuery, 2_000);
      const path = projectId === undefined
        ? "/v1/agent/catalog/sessions/page"
        : `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/page`;
      const value = await request<unknown>(
        `${path}${prepared.encoded}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentCatalogSessionPageResponse(
        value,
        prepared.limit,
        prepared.offset,
        prepared.snapshot,
        projectId,
      );
    },
    async getAgentCatalogSession(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/agent/catalog/sessions/${encodeURIComponent(sessionId)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return agentCatalogSessionResponse(value, sessionId);
    },
    async updateAgentCatalogSession(sessionId, session, signal) {
      const value = await request<unknown>(
        `/v1/agent/catalog/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(session),
        },
        signal,
        true,
        true,
      );
      return agentCatalogSessionResponse(value, sessionId);
    },
    async deleteAgentCatalogSession(sessionId, command, signal) {
      const query = new URLSearchParams({
        expected_catalog_revision: String(command.expected_catalog_revision),
        expected_history_revision: String(command.expected_history_revision),
      });
      await request<void>(
        `/v1/agent/catalog/sessions/${encodeURIComponent(sessionId)}?${query.toString()}`,
        { method: "DELETE" },
        signal,
        true,
        true,
        false,
        "no_content",
      );
    },
    async getAgentPersistedEvents(projectId, sessionId, after, signal) {
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/events?after=${after}&limit=${AGENT_EVENT_PAGE_LIMIT}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseAgentEvents(value, sessionId, after);
      } catch (error) {
        if (error instanceof AgentEventPayloadError) {
          throw new TransportError("Retained agent history response was invalid", 200);
        }
        throw error;
      }
    },
    async forkAgentSession(projectId, sessionId, command, signal) {
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/forks`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(command),
        },
        signal,
        true,
        true,
      );
      return agentSessionForkResponse(
        value,
        command.request_id,
        projectId,
        sessionId,
      );
    },
    async resumeAgentSession(projectId, sessionId, resume: ResumeAgentSession, signal) {
      const recovered = agentSessionResponse(
        await request<unknown>(
          `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/resume`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(resume),
          },
          signal,
          true,
          true,
        ),
        sessionId,
      );
      if (recovered.settings.project_id !== projectId) {
        throw new TransportError("Recovered Agent session project identity was invalid", 200);
      }
      return recovered;
    },
    async exportAgentHistory(projectId, sessionId, exportRequest, signal): Promise<AgentHistoryExport> {
      if (
        !Number.isSafeInteger(exportRequest.expected_catalog_revision)
        || exportRequest.expected_catalog_revision < 1
        || !Number.isSafeInteger(exportRequest.expected_history_revision)
        || exportRequest.expected_history_revision < 0
      ) {
        throw new TransportError("Agent history export revision was invalid", 400);
      }
      const query = new URLSearchParams({
        expected_catalog_revision: String(exportRequest.expected_catalog_revision),
        expected_history_revision: String(exportRequest.expected_history_revision),
      });
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/export?${query.toString()}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseAgentHistoryExport(value, projectId, sessionId);
      } catch (error) {
        if (error instanceof AgentHistoryPayloadError) {
          throw new TransportError("Agent history export response was invalid", 200);
        }
        throw error;
      }
    },
    async listAgentArtifacts(projectId, sessionId, view = "active", signal) {
      if (!["active", "archived", "removed", "all"].includes(view)) {
        throw new TransportError("Agent artifact lifecycle view was invalid", 400);
      }
      const query = new URLSearchParams({ view });
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts?${query.toString()}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      return agentArtifactListResponse(value, projectId, sessionId, view);
    },
    async pageAgentArtifacts(projectId, sessionId, query, signal) {
      const prepared = agentArtifactPageQuery(query);
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/page${prepared.encoded}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      return agentArtifactPageResponse(value, projectId, sessionId, prepared);
    },
    async getAgentArtifact(projectId, sessionId, artifactId, signal) {
      const value = await request<unknown>(
        `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      return agentArtifactDetailResponse(value, projectId, sessionId, artifactId);
    },
    async exportAgentArtifact(projectId, sessionId, artifactId, exportRequest, signal) {
      if (
        !Number.isSafeInteger(exportRequest.expected_revision)
        || exportRequest.expected_revision < 1
        || exportRequest.expected_revision > Number.MAX_SAFE_INTEGER
        || !/^[0-9a-f]{32}$/u.test(exportRequest.version_id)
      ) {
        throw new TransportError("Agent artifact export request was invalid", 400);
      }
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/export`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(exportRequest),
        },
        signal,
        true,
        true,
      );
      return agentArtifactExportResponse(
        value,
        projectId,
        sessionId,
        artifactId,
        exportRequest,
      );
    },
    async updateAgentArtifact(
      projectId,
      sessionId,
      artifactId,
      update: UpdateAgentArtifact,
      signal,
    ) {
      const rename = update.operation === "rename";
      const title = update.title;
      if (
        !Number.isSafeInteger(update.expected_revision)
        || update.expected_revision < 1
        || update.expected_revision > Number.MAX_SAFE_INTEGER
        || !["rename", "archive", "restore", "recover"].includes(update.operation)
        || (rename && (
          typeof title !== "string"
          || title !== title.trim()
          || Array.from(title).length < 1
          || Array.from(title).length > 120
        ))
        || (!rename && title !== undefined && title !== null)
      ) {
        throw new TransportError("Agent artifact lifecycle request was invalid", 400);
      }
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`;
      const value = await request<unknown>(
        path,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(update),
        },
        signal,
        true,
        true,
      );
      return agentArtifactResponse(value, projectId, sessionId, artifactId);
    },
    async removeAgentArtifact(
      projectId,
      sessionId,
      artifactId,
      removal: RemoveAgentArtifact,
      signal,
    ) {
      if (
        !Number.isSafeInteger(removal.expected_revision)
        || removal.expected_revision < 1
        || removal.expected_revision > Number.MAX_SAFE_INTEGER
        || removal.confirmation !== "move_archived_artifact_record_to_removed"
      ) {
        throw new TransportError("Agent artifact removal request was invalid", 400);
      }
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/remove`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(removal),
        },
        signal,
        true,
        true,
        true,
      );
      return agentArtifactResponse(value, projectId, sessionId, artifactId);
    },
    async previewAgentArtifactCapture(projectId, sessionId, preview, signal) {
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/capture-preview`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(preview),
        },
        signal,
        false,
        true,
      );
      return agentArtifactCapturePreviewResponse(value, projectId, sessionId, preview);
    },
    async captureAgentArtifact(
      projectId,
      sessionId,
      capture: CaptureAgentArtifact,
      signal,
    ) {
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(capture),
        },
        signal,
        true,
        true,
        true,
      );
      return agentArtifactDetailResponse(value, projectId, sessionId);
    },
    async getAgentArtifactDocumentPreview(
      projectId,
      sessionId,
      artifactId,
      version,
      signal,
    ) {
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/versions/${encodeURIComponent(version.version_id)}/preview`;
      const value = await request<unknown>(
        path,
        { method: "GET" },
        signal,
        false,
        true,
      );
      return agentArtifactDocumentPreviewResponse(
        value,
        projectId,
        sessionId,
        artifactId,
        version,
      );
    },
    getAgentArtifactContent(
      projectId,
      sessionId,
      artifactId,
      versionId,
      download,
      signal,
    ) {
      const path = `/v1/agent/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/versions/${encodeURIComponent(versionId)}/content${download ? "?download=true" : ""}`;
      return requestAgentArtifactContent(
        path,
        download ? "attachment" : "inline",
        signal,
      );
    },
    async listAgentSessions(signal) {
      const value = await request<unknown>("/v1/agent/sessions", { method: "GET" }, signal);
      if (!Array.isArray(value) || value.length > 12) throw new TransportError("Local agent session response was invalid", 200);
      const views = value.map((item) => agentSessionResponse(item));
      if (new Set(views.map((item) => item.session_id)).size !== views.length) throw new TransportError("Local agent session response was invalid", 200);
      return views;
    },
    async createAgentSession(settings, signal) {
      return agentSessionResponse(await request<unknown>("/v1/agent/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) }, signal, true));
    },
    async getAgentSession(sessionId, signal) {
      return agentSessionResponse(await request<unknown>(`/v1/agent/sessions/${encodeURIComponent(sessionId)}`, { method: "GET" }, signal), sessionId);
    },
    async getAgentSessionContext(sessionId, signal) {
      return agentSessionContextResponse(
        await request<unknown>(
          `/v1/agent/sessions/${encodeURIComponent(sessionId)}/context`,
          { method: "GET" },
          signal,
        ),
        sessionId,
      );
    },
    async switchAgentSessionModel(sessionId, model, signal) {
      return agentSessionResponse(
        await request<unknown>(
          `/v1/agent/sessions/${encodeURIComponent(sessionId)}/model`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(model),
          },
          signal,
          true,
        ),
        sessionId,
      );
    },
    async revalidateAgentAuthority(sessionId, authority: RevalidateAgentAuthority, signal) {
      return agentSessionResponse(
        await request<unknown>(
          `/v1/agent/sessions/${encodeURIComponent(sessionId)}/authority`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(authority),
          },
          signal,
          true,
          true,
          true,
        ),
        sessionId,
      );
    },
    async deleteAgentSession(sessionId, signal) {
      await request<void>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}`,
        { method: "DELETE" }, signal, true, false, false, "no_content",
      );
    },
    async listAgentAttachments(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/attachments`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentAttachmentList(value, sessionId);
      } catch (error) {
        if (error instanceof AgentAttachmentPayloadError) {
          throw new TransportError("Local Agent attachment list was invalid", 200);
        }
        throw error;
      }
    },
    async stageAgentAttachment(sessionId, upload, signal) {
      if (
        upload.displayName.length < 1
        || Array.from(upload.displayName).length > 120
        || /[\\/\u0000-\u001f\u007f]/u.test(upload.displayName)
        || (upload.source !== "file" && upload.source !== "microphone")
        || ![
          "image/png",
          "image/jpeg",
          "audio/wav",
          "text/plain",
          "text/markdown",
          "application/json",
          "text/csv",
          "text/tab-separated-values",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "application/vnd.oasis.opendocument.text",
        ].includes(upload.blob.type)
        || upload.blob.size < 1
        || upload.blob.size > 12 * 1024 * 1024
      ) throw new TransportError("Local Agent attachment upload was invalid", 422);
      const path = `/v1/agent/sessions/${encodeURIComponent(sessionId)}/attachments?name=${encodeURIComponent(upload.displayName)}&source=${upload.source}`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": upload.blob.type },
          body: upload.blob,
        },
        signal,
        true,
        true,
      );
      try {
        return parseAgentAttachment(value, sessionId);
      } catch (error) {
        if (error instanceof AgentAttachmentPayloadError) {
          throw new TransportError("Local Agent attachment response was invalid", 200);
        }
        throw error;
      }
    },
    async deleteAgentAttachment(sessionId, attachmentId, signal) {
      await request<void>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`,
        { method: "DELETE" },
        signal,
        true,
        true,
        false,
        "no_content",
      );
    },
    async getAgentAttachmentContent(sessionId, attachmentId, signal) {
      return requestAgentAttachmentContent(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/content`,
        signal,
      );
    },
    async getAgentAttachmentDocumentPreview(sessionId, attachmentId, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/document-preview`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentAttachmentDocumentPreview(value, sessionId, attachmentId);
      } catch (error) {
        if (error instanceof AgentAttachmentPayloadError) {
          throw new TransportError("Local Agent document preview was invalid", 200);
        }
        throw error;
      }
    },
    async sendAgentMessage(sessionId, text, attachmentIds = [], signal) {
      return agentSessionResponse(await request<unknown>(`/v1/agent/sessions/${encodeURIComponent(sessionId)}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, attachment_ids: [...attachmentIds] }) }, signal, true), sessionId);
    },
    async getAgentChangeSet(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/changes`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentChangeSet(value, sessionId);
      } catch (error) {
        if (error instanceof AgentChangeSetPayloadError) {
          throw new TransportError("Local agent change-set response was invalid", 200);
        }
        throw error;
      }
    },
    async getAgentChangeDiff(sessionId, path, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/changes/diff?path=${encodeURIComponent(path)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentChangeDiff(value, sessionId, path);
      } catch (error) {
        if (error instanceof AgentChangeSetPayloadError) {
          throw new TransportError("Local agent change diff response was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentChangeRestore(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/changes/restores`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentChangeRestorePreview(value, sessionId, payload.path);
      } catch (error) {
        if (error instanceof AgentChangeRestorePayloadError) {
          throw new TransportError("Local agent change restore preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentChangeRestore(sessionId, previewId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/changes/restores/${encodeURIComponent(previewId)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentChangeRestoreResult(
          value,
          sessionId,
          payload.path,
          payload.operation,
        );
      } catch (error) {
        if (error instanceof AgentChangeRestorePayloadError) {
          throw new TransportError("Local agent change restore result was invalid", 200);
        }
        throw error;
      }
    },
    async getAgentEvents(sessionId, after, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/events?after=${after}&limit=${AGENT_EVENT_PAGE_LIMIT}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseAgentEvents(value, sessionId, after);
      } catch (error) {
        if (error instanceof AgentEventPayloadError) {
          throw new TransportError("Local agent event response was invalid", 200);
        }
        throw error;
      }
    },
    async streamAgentEvents(sessionId, after, onPage, signal) {
      const target = assertSameOriginRelativePath(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/events/stream?after=${after}&limit=${AGENT_EVENT_PAGE_LIMIT}`,
        origin,
      );
      let csrfToken = await ensureBrowserSession(signal);
      const send = () => fetchRequest(target, {
        method: "GET",
        cache: "no-store",
        credentials: "include",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal,
        headers: { Accept: "text/event-stream" },
      });
      let response = await send();
      if (response.status === 401) {
        if (sessionAuth?.csrfToken === csrfToken) sessionAuth = undefined;
        csrfToken = await ensureBrowserSession(signal);
        response = await send();
      }
      if (!response.ok) {
        throw new TransportError(`Local API request failed (${response.status})`, response.status);
      }
      if (
        response.headers.get("cache-control") !== "no-store, private" ||
        response.headers.get("pragma") !== "no-cache" ||
        !response.headers.get("content-type")?.startsWith("text/event-stream")
      ) {
        throw new TransportError("Local agent stream response was not private SSE", response.status);
      }
      if (response.body === null) {
        throw new TransportError("Local agent stream response had no body", response.status);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8", { fatal: true });
      let buffer = "";
      let cursor = after;
      let latestRunning = false;
      const consumeFrames = () => {
        while (true) {
          const match = /\r?\n\r?\n/u.exec(buffer);
          if (match?.index === undefined) return;
          const frame = buffer.slice(0, match.index).replaceAll("\r\n", "\n");
          buffer = buffer.slice(match.index + match[0].length);
          const data = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (!data) continue;
          if (data.length > 4_000_000) {
            throw new TransportError("Local agent stream frame exceeded its limit", 200);
          }
          let raw: unknown;
          try {
            raw = JSON.parse(data);
          } catch {
            throw new TransportError("Local agent stream frame was invalid", 200);
          }
          try {
            const page = parseAgentEvents(raw, sessionId, cursor);
            onPage(page);
            latestRunning = page.running;
            if (page.events.length > 0) cursor = page.events[page.events.length - 1].seq;
          } catch (error) {
            if (error instanceof AgentEventPayloadError) {
              throw new TransportError("Local agent stream payload was invalid", 200);
            }
            throw error;
          }
        }
      };
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          if (buffer.length > 4_000_000) {
            throw new TransportError("Local agent stream buffer exceeded its limit", 200);
          }
          consumeFrames();
        }
        buffer += decoder.decode();
        if (buffer.trim()) {
          buffer += "\n\n";
          consumeFrames();
        }
        if (latestRunning) {
          throw new TransportError("Local agent stream ended during a running turn", 200);
        }
      } catch (error) {
        try {
          await reader.cancel();
        } catch {
          // The stream may already have closed or been aborted.
        }
        throw error;
      } finally {
        reader.releaseLock();
      }
    },
    async decideAgentApproval(sessionId, approvalId, approved, signal) {
      return agentSessionResponse(await request<unknown>(`/v1/agent/sessions/${encodeURIComponent(sessionId)}/approvals/${encodeURIComponent(approvalId)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved }) }, signal, true, false, true), sessionId);
    },
    async stopAgentSession(sessionId, signal) {
      return agentSessionResponse(await request<unknown>(`/v1/agent/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" }, signal), sessionId);
    },
    async getAgentWorkspaceDiscovery(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/discovery`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceDiscovery(value, sessionId);
      } catch (error) {
        if (error instanceof AgentWorkspaceDiscoveryPayloadError) {
          throw new TransportError("Local agent workspace discovery response was invalid", 200);
        }
        throw error;
      }
    },
    async getAgentWorkspaceTree(sessionId, path, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/tree?path=${encodeURIComponent(path)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceTree(value, sessionId, path);
      } catch (error) {
        if (error instanceof AgentWorkspacePayloadError) {
          throw new TransportError("Local agent workspace tree response was invalid", 200);
        }
        throw error;
      }
    },
    async getAgentWorkspaceSearch(sessionId, search, signal) {
      const params = new URLSearchParams({
        query: search.query,
        glob: search.glob,
        regex: search.regex ? "true" : "false",
      });
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/search?${params.toString()}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceSearchResult(value, sessionId);
      } catch (error) {
        if (error instanceof AgentWorkspaceSearchPayloadError) {
          throw new TransportError("Local agent workspace search response was invalid", 200);
        }
        throw error;
      }
    },
    async getAgentWorkspaceFile(sessionId, path, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/file?path=${encodeURIComponent(path)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceFile(value, sessionId, path);
      } catch (error) {
        if (error instanceof AgentWorkspacePayloadError) {
          throw new TransportError("Local agent workspace file response was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceEdit(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/previews`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspacePreview(
          value,
          sessionId,
          payload.path,
          payload.expected_revision,
          payload.line_ending,
        );
      } catch (error) {
        if (error instanceof AgentWorkspacePayloadError) {
          throw new TransportError("Local agent workspace preview response was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceEdit(sessionId, previewId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/previews/${encodeURIComponent(previewId)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceApplyResult(
          value,
          sessionId,
          payload.path,
          payload.proposed_revision,
        );
      } catch (error) {
        if (error instanceof AgentWorkspacePayloadError) {
          throw new TransportError("Local agent workspace apply response was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceCreate(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/creates`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        const diskContent = payload.line_ending === "crlf"
          ? payload.content.replaceAll("\n", "\r\n")
          : payload.content;
        return parseAgentWorkspaceCreatePreview(
          value,
          sessionId,
          payload.path,
          payload.line_ending,
          new TextEncoder().encode(diskContent).byteLength,
        );
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace create preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceCreate(sessionId, preview, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/creates/${encodeURIComponent(preview.preview_id)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceCreateResult(value, sessionId, preview);
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace create result was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceDirectoryCreate(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/directories`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceDirectoryCreatePreview(
          value,
          sessionId,
          payload.path,
        );
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace directory preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceDirectoryCreate(sessionId, preview, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/directories/${encodeURIComponent(preview.preview_id)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceDirectoryCreateResult(value, sessionId, preview);
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace directory result was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceDirectoryMove(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/directory-moves`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceDirectoryMovePreview(
          value,
          sessionId,
          payload.source_path,
          payload.target_path,
        );
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace directory move preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceDirectoryMove(sessionId, preview, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/directory-moves/${encodeURIComponent(preview.preview_id)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceDirectoryMoveResult(value, sessionId, preview);
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace directory move result was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceFileTrash(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/file-trash`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceFileTrashPreview(
          value,
          sessionId,
          payload.path,
          payload.expected_revision,
        );
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace Recycle Bin preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceFileTrash(sessionId, preview, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/file-trash/${encodeURIComponent(preview.preview_id)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceFileTrashResult(value, sessionId, preview);
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace Recycle Bin result was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceMove(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/moves`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceMovePreview(
          value,
          sessionId,
          payload.source_path,
          payload.target_path,
          payload.expected_revision,
        );
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace move preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceMove(sessionId, preview, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/moves/${encodeURIComponent(preview.preview_id)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceMoveResult(value, sessionId, preview);
      } catch (error) {
        if (error instanceof AgentWorkspaceLifecyclePayloadError) {
          throw new TransportError("Local agent workspace move result was invalid", 200);
        }
        throw error;
      }
    },
    async previewAgentWorkspaceTransaction(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/transactions`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceTransactionPreview(value, sessionId, payload);
      } catch (error) {
        if (error instanceof AgentWorkspaceTransactionPayloadError) {
          throw new TransportError("Local agent workspace transaction preview was invalid", 200);
        }
        throw error;
      }
    },
    async applyAgentWorkspaceTransaction(sessionId, preview, payload, signal) {
      const value = await request<unknown>(
        `/v1/agent/sessions/${encodeURIComponent(sessionId)}/workspace/transactions/${encodeURIComponent(preview.plan_id)}/apply`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseAgentWorkspaceTransactionResult(value, sessionId, preview);
      } catch (error) {
        if (error instanceof AgentWorkspaceTransactionPayloadError) {
          throw new TransportError("Local agent workspace transaction result was invalid", 200);
        }
        throw error;
      }
    },
    interpretSessionWithModel(sessionId, signal) {
      return request<SessionInterpretation>(`/v1/model-judge/sessions/${encodeURIComponent(sessionId)}/interpret`, { method: "POST" }, signal, true);
    },
    getModelJudgments(sessionId, signal) {
      return request<SessionJudgments>(`/v1/model-judge/sessions/${encodeURIComponent(sessionId)}`, { method: "GET" }, signal);
    },
    getModelJudgeAgreement(signal) {
      return request<JudgeAgreementReport>("/v1/model-judge/agreement", { method: "GET" }, signal);
    },
    getAnnotationAllowance(signal) {
      return request<AnnotationAllowance>("/v1/annotation/allowance", { method: "GET" }, signal);
    },
    setAnnotationAllowance(agentAllowed, signal) {
      return request<AnnotationAllowance>(
        "/v1/annotation/allowance",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ agent_allowed: agentAllowed }) },
        signal,
      );
    },
    getAnnotationMetaprompt(signal) {
      return request<AnnotationMetaprompt>("/v1/annotation/metaprompt", { method: "GET" }, signal);
    },
    getRemoteAnnotationDisclosure(signal) {
      return request<RemoteAnnotationDisclosure>("/v1/annotation/remote/disclosure", { method: "GET" }, signal);
    },
    annotateRemotely(limit, signal) {
      return request<RemoteAnnotationResult>(
        "/v1/annotation/remote/submit",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit }) },
        signal,
      );
    },
    shareFolder(path, name, signal) {
      return request<SharedFolder>(
        "/v1/shared-folders",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path, name }) },
        signal,
      );
    },
    listSharedFolders(signal) {
      return request<SharedFolderList>("/v1/shared-folders", { method: "GET" }, signal);
    },
    async revokeSharedFolder(shareId, signal) {
      await request<unknown>("/v1/shared-folders/" + encodeURIComponent(shareId), { method: "DELETE" }, signal);
    },
    joinSharedFolder(url, shareId, shareToken, target, signal) {
      return request<PeerLink>(
        "/v1/shared-folders/join",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, share_id: shareId, share_token: shareToken, target }) },
        signal,
      );
    },
    listPeerLinks(signal) {
      return request<PeerLinkList>("/v1/shared-folders/links", { method: "GET" }, signal);
    },
    async leavePeerLink(linkId, signal) {
      await request<unknown>("/v1/shared-folders/links/" + encodeURIComponent(linkId), { method: "DELETE" }, signal);
    },
    pullPeerLink(linkId, signal) {
      return request<FolderSyncReport>("/v1/shared-folders/links/" + encodeURIComponent(linkId) + "/pull", { method: "POST" }, signal);
    },
    pushPeerLink(linkId, peerName, signal) {
      return request<FolderSyncReport>(
        "/v1/shared-folders/links/" + encodeURIComponent(linkId) + "/push",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ peer_name: peerName }) },
        signal,
      );
    },
    getLocalModels(signal) {
      return request<LocalModelsOverview>("/v1/local-models", { method: "GET" }, signal);
    },
    async getLocalModelPlacement(alias, contextSize, signal) {
      const query = new URLSearchParams({ context_size: String(contextSize) });
      return parseLocalModelPlacement(
        await request<unknown>(
          `/v1/local-models/${encodeURIComponent(alias)}/placement?${query.toString()}`,
          { method: "GET" },
          signal,
        ),
      );
    },
    async getLocalModelCompatibility(signal) {
      return localModelCompatibilityResponse(
        await request<unknown>("/v1/local-models/compatibility", { method: "GET" }, signal),
      );
    },
    addLocalModel(payload, signal) {
      return request<LocalModelRecord>(
        "/v1/local-models",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
      );
    },
    activateLocalModel(alias, payload, signal) {
      return request<LocalModelStatus>(
        `/v1/local-models/${encodeURIComponent(alias)}/activate`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
      );
    },
    deactivateLocalModel(alias, signal) {
      return request<LocalModelStatus>(
        `/v1/local-models/${encodeURIComponent(alias)}/deactivate`,
        { method: "POST" },
        signal,
      );
    },
    async getLocalRuntime(signal) {
      return localRuntimeResponse(
        await request<unknown>("/v1/local-models/runtime", { method: "GET" }, signal),
      );
    },
    async switchLocalRuntime(payload, signal) {
      return localRuntimeResponse(
        await request<unknown>(
          "/v1/local-models/runtime/switch",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
        ),
      );
    },
    async stopLocalRuntime(payload, signal) {
      return localRuntimeResponse(
        await request<unknown>(
          "/v1/local-models/runtime/stop",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          signal,
          true,
        ),
      );
    },
    async removeLocalModel(alias, deleteWeights, signal) {
      await request<unknown>(
        `/v1/local-models/${encodeURIComponent(alias)}?delete_weights=${deleteWeights ? "true" : "false"}`,
        { method: "DELETE" },
        signal,
      );
    },
    getLocalModelRemoteFiles(repoId, signal) {
      return request<RemoteRepoFiles>(
        `/v1/local-models/remote-files?repo_id=${encodeURIComponent(repoId)}`,
        { method: "GET" },
        signal,
      );
    },
    startLocalModelDownload(payload, signal) {
      return request<DownloadStatus>(
        "/v1/local-models/downloads",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
      );
    },
    scanLocalModelFolder(path, signal) {
      return request<ScanFolderResult>(
        "/v1/local-models/scan-folder",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path, default_device: "split" }) },
        signal,
      );
    },
    async streamInferenceChat(payload, onDelta, signal) {
      const target = assertSameOriginRelativePath(
        "/v1/inference/chat",
        origin,
      );
      const body = JSON.stringify(payload);
      const started = Date.now();
      let csrfToken = await ensureBrowserSession(signal);
      const send = (csrf: string) =>
        fetchRequest(target, {
          method: "POST",
          credentials: "include",
          redirect: "error",
          referrerPolicy: "no-referrer",
          cache: "no-store",
          signal,
          headers: {
            Accept: "text/event-stream, application/json",
            "Content-Type": "application/json",
            "X-Prompt-Enhancer-CSRF": csrf,
          },
          body,
        });
      let response = await send(csrfToken);
      if (response.status === 401) {
        if (sessionAuth?.csrfToken === csrfToken) sessionAuth = undefined;
        csrfToken = await ensureBrowserSession(signal);
        response = await send(csrfToken);
      }
      if (!response.ok) {
        let reasonCode: SafeTransportReasonCode | null = null;
        if (isJsonResponse(response)) {
          try {
            reasonCode = safeReasonFromErrorPayload(await response.json());
          } catch {
            // Upstream error bodies are deliberately not surfaced.
          }
        }
        throw new TransportError(`Model chat failed (${response.status})`, response.status, reasonCode);
      }
      try {
        return await readLocalModelChat(response, onDelta, signal, started);
      } catch {
        if (signal?.aborted) throw new DOMException("The model reply was cancelled.", "AbortError");
        // No raw runtime payload, parse detail or reader exception leaves this boundary.
        throw new TransportError("The model reply did not complete.", response.status);
      }
    },
    getInferenceModels(signal) { return request<InferenceCatalog>("/v1/inference/models", { method: "GET" }, signal); },
    previewInferenceChat(payload, signal) { return request<InferencePreview>("/v1/inference/chat/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, signal); },
    previewManualAnalysis(payload, signal) { return request<InferencePreview>("/v1/inference/analysis/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, signal); },
    runManualAnalysis(payload, signal) { return request<ManualAnalysisResult>("/v1/inference/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, signal); },
    getAgentInferenceReviews(sessionId, signal) { return request<PendingInferenceReview[]>(`/v1/inference/agent/${encodeURIComponent(sessionId)}/reviews`, { method: "GET" }, signal); },
    async decideAgentInferenceReview(sessionId, reviewId, accepted, signal) { await request<unknown>(`/v1/inference/agent/${encodeURIComponent(sessionId)}/reviews/${encodeURIComponent(reviewId)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accepted }) }, signal); },
    previewSessionInference(sessionId, kind, modelId, signal) { return request<InferencePreview>(`/v1/model-judge/sessions/${encodeURIComponent(sessionId)}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, model_id: modelId }) }, signal); },
    runSessionInference(sessionId, kind, modelId, approval, signal) { return request<JudgeOutcome | SessionInterpretation>(`/v1/model-judge/sessions/${encodeURIComponent(sessionId)}${kind === "interpret" ? "/interpret" : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: modelId, approval }) }, signal); },
    async streamLocalModelChat(alias, payload, onDelta, signal) {
      const target = assertSameOriginRelativePath(
        `/v1/local-models/${encodeURIComponent(alias)}/chat/completions`,
        origin,
      );
      const { enable_thinking, ...rest } = payload;
      const body = JSON.stringify({
        ...rest,
        stream: true,
        chat_template_kwargs: { enable_thinking: enable_thinking === true },
      });
      const started = Date.now();
      let csrfToken = await ensureBrowserSession(signal);
      const send = (csrf: string) =>
        fetchRequest(target, {
          method: "POST",
          credentials: "include",
          redirect: "error",
          referrerPolicy: "no-referrer",
          cache: "no-store",
          signal,
          headers: {
            Accept: "text/event-stream, application/json",
            "Content-Type": "application/json",
            "X-Prompt-Enhancer-CSRF": csrf,
          },
          body,
        });
      let response = await send(csrfToken);
      if (response.status === 401) {
        if (sessionAuth?.csrfToken === csrfToken) sessionAuth = undefined;
        csrfToken = await ensureBrowserSession(signal);
        response = await send(csrfToken);
      }
      if (!response.ok) {
        let reasonCode: SafeTransportReasonCode | null = null;
        if (isJsonResponse(response)) {
          try {
            reasonCode = safeReasonFromErrorPayload(await response.json());
          } catch {
            // Upstream error bodies are deliberately not surfaced.
          }
        }
        throw new TransportError(`Local model chat failed (${response.status})`, response.status, reasonCode);
      }
      try {
        return await readLocalModelChat(response, onDelta, signal, started);
      } catch {
        if (signal?.aborted) throw new DOMException("The model reply was cancelled.", "AbortError");
        // No raw runtime payload, parse detail or reader exception leaves this boundary.
        throw new TransportError("The local model reply did not complete.", response.status);
      }
    },
    getProjectTimeline(projectId, signal) {
      return request<ProjectTimeline>(
        `/v1/projects/${encodeURIComponent(projectId)}/timeline`,
        { method: "GET" },
        signal,
      );
    },
    getSessionTimeline(sessionId, signal) {
      return request<SessionTimeline>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/timeline`,
        { method: "GET" },
        signal,
      );
    },
    getCalibrationSample(raterLabel, signal) {
      const query = raterLabel ? `?rater_label=${encodeURIComponent(raterLabel)}` : "";
      return request<CalibrationSample>(`/v1/calibration/sample${query}`, { method: "GET" }, signal);
    },
    reviewCalibrationCase(sessionId, windowCharacters, signal) {
      return request<CalibrationReview>("/v1/calibration/review", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, window_characters: windowCharacters }),
      }, signal, true, true);
    },
    submitCalibrationRatings(payload, signal) {
      return request<CalibrationProgress>(
        "/v1/calibration/ratings",
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
      );
    },
    getCalibrationRatings(raterLabel, signal) {
      return request<CalibrationRating[]>(
        `/v1/calibration/ratings?rater_label=${encodeURIComponent(raterLabel)}`,
        { method: "GET" },
        signal,
      );
    },
    getCalibrationProgress(signal) {
      return request<CalibrationProgress>("/v1/calibration/progress", { method: "GET" }, signal);
    },
    getCalibrationExport(signal) {
      return request<CalibrationExport>("/v1/calibration/export", { method: "GET" }, signal);
    },
    acceptOnboarding(payload, signal) {
      return request<OnboardingResult>(
        "/v1/onboarding/accept",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        signal,
        true,
      );
    },
    pauseLocalModelDownload(downloadId, statusRevision, signal) {
      return request<DownloadStatus>(
        `/v1/local-models/downloads/${encodeURIComponent(downloadId)}/pause`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_status_revision: statusRevision }) },
        signal,
      );
    },
    resumeLocalModelDownload(downloadId, statusRevision, signal) {
      return request<DownloadStatus>(
        `/v1/local-models/downloads/${encodeURIComponent(downloadId)}/resume`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_status_revision: statusRevision }) },
        signal,
      );
    },
    retryLocalModelDownload(downloadId, statusRevision, signal) {
      return request<DownloadStatus>(
        `/v1/local-models/downloads/${encodeURIComponent(downloadId)}/retry`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_status_revision: statusRevision }) },
        signal,
      );
    },
    cancelLocalModelDownload(downloadId, statusRevision, signal) {
      return request<DownloadStatus>(
        `/v1/local-models/downloads/${encodeURIComponent(downloadId)}/cancel`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_status_revision: statusRevision }) },
        signal,
      );
    },
    getSessionTranscript(sessionId, signal) {
      return request<SessionTranscript>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/transcript`,
        { method: "GET" },
        signal,
      );
    },
    getClaudeLocalSourceStatus(signal) {
      return request<ClaudeCodeLocalSourceStatus>(
        "/v1/local-sources/claude-code",
        { method: "GET" },
        signal,
      );
    },
    grantClaudeLocalHistoryConsent(signal) {
      return request<ClaudeCodeLocalSourceStatus>(
        "/v1/local-sources/claude-code/consents/local-history",
        { method: "POST" },
        signal,
      );
    },
    revokeClaudeLocalHistoryConsent(signal) {
      return request<ClaudeCodeLocalSourceStatus>(
        "/v1/local-sources/claude-code/consents/local-history",
        { method: "DELETE" },
        signal,
      );
    },
    indexClaudeLocalSessions(maxSessions, signal) {
      return request<IngestionReport>(
        "/v1/local-sources/claude-code/index",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ max_sessions: maxSessions }),
        },
        signal,
      );
    },
    indexCodexLocalSessions(maxSessions, signal) {
      return request<CodexIngestionReport>(
        "/v1/local-sources/codex/index",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ max_sessions: maxSessions }),
        },
        signal,
      );
    },
    analyzeCodexLocalSessions(selection: CodexAnalysisSelection, signal) {
      return request<CodexIngestionReport>(
        "/v1/local-sources/codex/analysis",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selection),
        },
        signal,
      );
    },
    enrichCodexDisplayLabels(selection: CodexAnalysisSelection, signal) {
      return request<CodexLabelEnrichmentReport>(
        "/v1/local-sources/codex/display-labels/enrich",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selection),
        },
        signal,
      );
    },
    setManualDisplayLabel(
      entityKind: DisplayLabelEntityKind,
      entityId,
      value,
      expectedRevision,
      signal,
    ) {
      const collection = entityKind === "project" ? "projects" : "sessions";
      return request<ManualDisplayLabelResult>(
        `/v1/catalog/${collection}/${encodeURIComponent(entityId)}/display-label`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            value,
            expected_revision: expectedRevision,
          }),
        },
        signal,
      );
    },
    clearManualDisplayLabel(
      entityKind: DisplayLabelEntityKind,
      entityId,
      expectedRevision,
      signal,
    ) {
      const collection = entityKind === "project" ? "projects" : "sessions";
      return request<ManualDisplayLabelResult>(
        `/v1/catalog/${collection}/${encodeURIComponent(entityId)}/display-label?expected_revision=${expectedRevision}`,
        { method: "DELETE" },
        signal,
      );
    },
    // Despite the legacy name this lists every local provider's sessions;
    // a provider filter here silently hid hook-captured Claude Code sessions.
    listCodexSessions(limit = 100, offset = 0, signal) {
      return request<CodexSessionListResponse>(
        `/v1/sessions?limit=${limit}&offset=${offset}`,
        { method: "GET" },
        signal,
      );
    },
    listProjectSessions(projectId, limit = 100, offset = 0, signal) {
      return request<ProjectSessionListResponse>(
        `/v1/projects/${encodeURIComponent(projectId)}/sessions?limit=${limit}&offset=${offset}`,
        { method: "GET" },
        signal,
      );
    },
    getSessionMetrics(sessionId, signal) {
      return request<SessionMetricResponse>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/metrics`,
        { method: "GET" },
        signal,
      );
    },
    async listAnalysisJobs(state = null, limit = 100, offset = 0, signal) {
      const query = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (state !== null) query.set("state", state);
      const value = await request<unknown>(
        `/v1/analysis-jobs?${query.toString()}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return parseAnalysisJobPage(value, limit, offset, state);
    },
    async getAnalysisJob(jobId, signal) {
      const value = await request<unknown>(
        `/v1/analysis-jobs/${encodeURIComponent(jobId)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return parseAnalysisJobRecord(value, jobId);
    },
    async getLatestSessionAnalysisJob(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/analysis-jobs/latest`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      const job = parseAnalysisJobRecord(value);
      if (job.identity.session_id !== sessionId) {
        throw new TransportError("Analysis job response was invalid", 200);
      }
      return job;
    },
    async cancelAnalysisJob(jobId, signal) {
      const value = await request<unknown>(
        `/v1/analysis-jobs/${encodeURIComponent(jobId)}/cancellation`,
        { method: "POST" },
        signal,
        true,
        true,
      );
      return parseAnalysisJobRecord(value, jobId);
    },
    async listAutomationGrants(provider, activeOnly = false, signal) {
      if (!["codex", "claude_code", "synthetic"].includes(provider)) {
        throw new TransportError("Automation provider was invalid", 400);
      }
      const query = new URLSearchParams({
        provider,
        active_only: String(activeOnly),
      });
      const value = await request<unknown>(
        `/v1/automation-grants?${query.toString()}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return parseAutomationGrantList(value, provider);
    },
    async getAutomationGrant(grantId, expectedScope, signal) {
      if (!PSEUDONYM.test(grantId)) {
        throw new TransportError("Automation grant identifier was invalid", 400);
      }
      const canonicalScope = parseAutomationGrantScope(expectedScope);
      const value = await request<unknown>(
        `/v1/automation-grants/${encodeURIComponent(grantId)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      return parseAutomationGrantRecord(value, grantId, canonicalScope);
    },
    async createAutomationGrant(automationRequest, signal) {
      const canonicalRequest = parseAutomationGrantCreateRequest(automationRequest);
      const value = await request<unknown>(
        "/v1/automation-grants",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(canonicalRequest),
        },
        signal,
        true,
        true,
      );
      return parseAutomationGrantRecord(
        value,
        undefined,
        scopeForAutomationRequest(canonicalRequest),
      );
    },
    async renewAutomationGrant(grantId, expectedScope, signal) {
      if (!PSEUDONYM.test(grantId)) {
        throw new TransportError("Automation grant identifier was invalid", 400);
      }
      const canonicalScope = parseAutomationGrantScope(expectedScope);
      const value = await request<unknown>(
        `/v1/automation-grants/${encodeURIComponent(grantId)}/renewal`,
        { method: "POST" },
        signal,
        true,
        true,
      );
      return parseAutomationGrantRecord(value, grantId, canonicalScope);
    },
    async revokeAutomationGrant(grantId, expectedScope, signal) {
      if (!PSEUDONYM.test(grantId)) {
        throw new TransportError("Automation grant identifier was invalid", 400);
      }
      const canonicalScope = parseAutomationGrantScope(expectedScope);
      const value = await request<unknown>(
        `/v1/automation-grants/${encodeURIComponent(grantId)}/revocation`,
        { method: "POST" },
        signal,
        true,
        true,
      );
      return parseAutomationGrantRecord(value, grantId, canonicalScope);
    },
    async pollAutomationGrants(signal) {
      const value = await request<unknown>(
        "/v1/automation-grants/poll",
        { method: "POST" },
        signal,
        true,
        true,
      );
      return parseAutomationPollResult(value);
    },
    async getLatestSessionQualityAnalysis(sessionId, signal) {
      if (!PSEUDONYM.test(sessionId)) {
        throw new TransportError("Session identifier was invalid", 400);
      }
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/quality-analysis-runs/latest`,
        { method: "GET" },
        signal,
      );
      return parseSessionAnalysisRunResponse(value, { sessionId });
    },
    async getSessionQualityAnalysisRun(runId, signal) {
      if (!PSEUDONYM.test(runId)) {
        throw new TransportError("Quality analysis run identifier was invalid", 400);
      }
      const value = await request<unknown>(
        `/v1/quality-analysis/runs/${encodeURIComponent(runId)}`,
        { method: "GET" },
        signal,
      );
      return parseSessionAnalysisRunResponse(value, { runId });
    },
    getSessionCoachingSummary(runId, signal) {
      return request<SessionCoachingProjection>(
        `/v1/quality-analysis/runs/${encodeURIComponent(runId)}/coaching-summary`,
        { method: "GET" },
        signal,
      );
    },
    startSessionQualityAnalysis(
      sessionId,
      analysisRequest: SessionQualityAnalysisRequest,
      idempotencyKey,
      signal,
    ) {
      return request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/quality-analysis-runs`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(analysisRequest),
        },
        signal,
        true,
      ).then(parseSessionQualityAnalysisOutcome);
    },
    async prepareSessionQualityAnalysisPreview(
      sessionId,
      previewRequest: SessionQualityAnalysisPreviewRequest,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/quality-analysis-previews`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(previewRequest),
        },
        signal,
        true,
        true,
      );
      return parseSessionQualityAnalysisPreview(
        value,
        sessionId,
        previewRequest.preset_id,
      );
    },
    async approveSessionQualityAnalysisPreview(
      previewId,
      approvalRequest: SessionQualityAnalysisPreviewApprovalRequest,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/quality-analysis-previews/${encodeURIComponent(previewId)}/approval`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(approvalRequest),
        },
        signal,
        true,
        true,
      );
      return parseSessionQualityAnalysisOutcome(value);
    },
    aggregateSessionQuality(
      aggregateRequest: SessionQualityAggregateRequest,
      signal,
    ) {
      return request<SessionQualityAggregate>(
        "/v1/quality-analysis/aggregate",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(aggregateRequest),
        },
        signal,
      );
    },
    aggregateProjectQuality(
      aggregateRequest: ProjectQualityAggregateRequest,
      signal,
    ) {
      return request<ProjectQualityAggregate>(
        "/v1/quality-analysis/aggregate-projects",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(aggregateRequest),
        },
        signal,
      );
    },
    getLatestModelLinkExperiment(sessionId, signal) {
      return request<ModelLinkExperiment>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/model-link-experiments/latest`,
        { method: "GET" },
        signal,
      );
    },
    startModelLinkExperiment(
      sessionId,
      experimentRequest: ModelLinkExperimentRequest,
      idempotencyKey,
      signal,
    ) {
      return request<ModelLinkExperimentOutcome>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/model-link-experiments`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(experimentRequest),
        },
        signal,
        true,
      );
    },
    annotateModelLink(
      runId,
      linkId,
      annotationRequest: ModelLinkAnnotationRequest,
      signal,
    ) {
      return request<ModelLinkAnnotation>(
        `/v1/model-link-experiments/${encodeURIComponent(runId)}/links/${encodeURIComponent(linkId)}/annotations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(annotationRequest),
        },
        signal,
        true,
      );
    },
    async getLatestModelEnsemble(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/model-ensemble-runs/latest`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleRun(value);
      } catch (error) {
        if (error instanceof ModelEnsemblePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getDeclaredTaskProfile(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/declared-task-profile`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseDeclaredTaskProfileCurrent(value, sessionId);
      } catch (error) {
        if (error instanceof DeclaredTaskProfilePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async saveDeclaredTaskProfile(
      sessionId,
      profileRequest: DeclaredTaskProfileCommand,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/declared-task-profile`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(profileRequest),
        },
        signal,
        false,
        true,
        true,
      );
      try {
        return parseDeclaredTaskProfileOutcome(value, sessionId);
      } catch (error) {
        if (error instanceof DeclaredTaskProfilePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async startModelEnsemble(
      sessionId,
      ensembleRequest: ModelEnsembleRequest,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/model-ensemble-runs`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(ensembleRequest),
        },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleOutcome(value);
      } catch (error) {
        if (error instanceof ModelEnsemblePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getModelPredictiveMetricDetail(runId, metricKey, signal) {
      const value = await request<unknown>(
        `/v1/model-ensemble-runs/${encodeURIComponent(runId)}/metrics/${encodeURIComponent(metricKey)}/predictive-detail`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelPredictiveMetricDetail(value) as ModelPredictiveMetricDetail;
      } catch (error) {
        if (error instanceof ModelPredictiveMetricDetailPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async previewAgentMetricEvidence(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/agent-metric-evidence/preview`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/vnd.prompt-enhancer.agent-metric-evidence+json",
          },
          body: payload,
        },
        signal,
        true,
        true,
      );
      try { return parseAgentMetricEvidencePreview(value); }
      catch (error) {
        if (error instanceof AgentMetricEvidencePayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async importAgentMetricEvidence(
      sessionId,
      payload,
      expectedPayloadSha256,
      confirmation,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/agent-metric-evidence/import`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/vnd.prompt-enhancer.agent-metric-evidence+json",
            "Idempotency-Key": idempotencyKey,
            "X-Agent-Evidence-Confirmation": confirmation,
            "X-Agent-Evidence-Payload-SHA256": expectedPayloadSha256,
          },
          body: payload,
        },
        signal,
        true,
        true,
      );
      try { return parseAgentMetricEvidenceImport(value); }
      catch (error) {
        if (error instanceof AgentMetricEvidencePayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async listMetricLifecycleProposals(sessionId, signal) {
      const limit = 200;
      let offset = 0;
      let total: number | null = null;
      const proposals: MetricLifecycleProposal[] = [];
      const identities = new Set<string>();
      for (let pageIndex = 0; pageIndex < 120; pageIndex += 1) {
        const value = await request<unknown>(
          `/v1/sessions/${encodeURIComponent(sessionId)}/metric-lifecycle-evidence/proposal-page?limit=${limit}&offset=${offset}`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const page = parseMetricLifecycleProposalPage(value, sessionId, limit, offset);
          if (total !== null && page.total !== total) throw new AgentMetricEvidencePayloadError();
          total = page.total;
          for (const proposal of page.proposals) {
            if (identities.has(proposal.proposal_id)) throw new AgentMetricEvidencePayloadError();
            identities.add(proposal.proposal_id);
            proposals.push(proposal);
          }
          if (page.complete) return { session_id: sessionId, proposals, total, complete: true };
          if (typeof page.next_offset !== "number") throw new AgentMetricEvidencePayloadError();
          offset = page.next_offset;
        } catch (error) {
          if (error instanceof AgentMetricEvidencePayloadError) throw new TransportError(error.message, 200);
          throw error;
        }
      }
      throw new TransportError("Metric lifecycle proposal list exceeded the reviewed page budget", 200);
    },
    async decideMetricLifecycleProposal(
      sessionId,
      proposalId,
      decisionRequest: MetricLifecycleDecisionRequest,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/metric-lifecycle-evidence/proposals/${encodeURIComponent(proposalId)}/decision`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(decisionRequest),
        },
        signal,
        true,
        true,
        true,
      );
      try { return parseMetricLifecycleProposalOutcome(value); }
      catch (error) {
        if (error instanceof AgentMetricEvidencePayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async getRequirementPlanEvidenceContract(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-plan-evidence/contract`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try { return parseRequirementPlanEvidenceContract(value, sessionId); }
      catch (error) {
        if (error instanceof RequirementPlanEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async previewRequirementPlanEvidence(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-plan-evidence/preview`,
        {
          method: "POST",
          headers: { "Content-Type": REQUIREMENT_PLAN_MEDIA_TYPE },
          body: payload,
        },
        signal,
        true,
        true,
      );
      try { return parseRequirementPlanEvidencePreview(value, sessionId); }
      catch (error) {
        if (error instanceof RequirementPlanEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async importRequirementPlanEvidence(
      sessionId,
      payload,
      preview,
      confirmation,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-plan-evidence/import`,
        {
          method: "POST",
          headers: {
            "Content-Type": REQUIREMENT_PLAN_MEDIA_TYPE,
            "Idempotency-Key": idempotencyKey,
            "X-Requirement-Plan-Confirmation": confirmation,
            "X-Requirement-Plan-Payload-SHA256": preview.payload_sha256,
          },
          body: payload,
        },
        signal,
        true,
        true,
      );
      try { return parseRequirementPlanImport(value, preview); }
      catch (error) {
        if (error instanceof RequirementPlanEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async listRequirementPlanProposals(sessionId, signal) {
      const limit = 200;
      let offset = 0;
      let total: number | null = null;
      let snapshot: import("./contracts").RequirementPlanProposalPageSnapshot | null = null;
      const proposals: RequirementPlanProposal[] = [];
      const identities = new Set<string>();
      let previousCreatedAtKey: string | null = null;
      let previousProposalId = "";
      for (let pageIndex = 0; pageIndex < 120; pageIndex += 1) {
        const snapshotQuery = snapshot === null ? "" : [
          `&snapshot_id=${encodeURIComponent(snapshot.snapshot_id)}`,
          `&snapshot_total=${snapshot.total}`,
          `&snapshot_decision_count=${snapshot.decision_count}`,
          `&snapshot_high_water_created_at=${encodeURIComponent(snapshot.high_water_created_at!)}`,
          `&snapshot_high_water_proposal_id=${encodeURIComponent(snapshot.high_water_proposal_id!)}`,
        ].join("");
        const value = await request<unknown>(
          `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-plan-evidence/proposal-page?limit=${limit}&offset=${offset}${snapshotQuery}`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const page = parseRequirementPlanProposalPage(
            value, sessionId, limit, offset, snapshot,
          );
          if (total !== null && page.total !== total) throw new RequirementPlanEvidencePayloadError();
          total = page.total;
          snapshot = page.snapshot;
          for (const proposal of page.proposals) {
            if (identities.has(proposal.proposal_id)) throw new RequirementPlanEvidencePayloadError();
            const createdAtKey = requirementPlanUtcMicrosecondKey(proposal.created_at);
            if (
              previousCreatedAtKey !== null
              && (
                createdAtKey < previousCreatedAtKey
                || (createdAtKey === previousCreatedAtKey
                  && proposal.proposal_id <= previousProposalId)
              )
            ) throw new RequirementPlanEvidencePayloadError();
            identities.add(proposal.proposal_id);
            proposals.push(proposal);
            previousCreatedAtKey = createdAtKey;
            previousProposalId = proposal.proposal_id;
          }
          if (page.complete) {
            const boundary = proposals.at(-1);
            if (
              proposals.length !== total
              || snapshot.decision_count !== proposals.filter(
                (proposal) => proposal.status !== "proposed",
              ).length
              || (boundary === undefined) !== (snapshot.total === 0)
              || (boundary !== undefined && (
                requirementPlanUtcMicrosecondKey(snapshot.high_water_created_at!)
                  !== requirementPlanUtcMicrosecondKey(boundary.created_at)
                || snapshot.high_water_proposal_id !== boundary.proposal_id
              ))
            ) throw new RequirementPlanEvidencePayloadError();
            return { session_id: sessionId, proposals, total, complete: true, snapshot };
          }
          if (typeof page.next_offset !== "number") throw new RequirementPlanEvidencePayloadError();
          offset = page.next_offset;
        } catch (error) {
          if (error instanceof RequirementPlanEvidencePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      }
      throw new TransportError("Requirement-plan proposal list exceeded the reviewed page budget", 200);
    },
    async reviewRequirementPlanProposal(
      sessionId,
      proposal,
      contract,
      reviewRequest,
      signal,
    ) {
      const path = `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-plan-evidence/proposals/${encodeURIComponent(proposal.proposal_id)}/review`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reviewRequest),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseRequirementPlanProposalReview(value, { sessionId, proposal, contract });
      } catch (error) {
        if (error instanceof RequirementPlanEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async decideRequirementPlanProposal(
      sessionId,
      proposalId,
      decisionRequest,
      idempotencyKey,
      signal,
    ) {
      const path = `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-plan-evidence/proposals/${encodeURIComponent(proposalId)}/decision`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(decisionRequest),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseRequirementPlanProposalOutcome(value, {
          sessionId,
          proposalId,
          sourceRunId: decisionRequest.expected_source_run_id,
          decision: decisionRequest.decision,
        });
      } catch (error) {
        if (error instanceof RequirementPlanEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getRequirementActionEvidenceContract(sessionId, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-action-evidence/contract`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try { return parseRequirementActionEvidenceContract(value, sessionId); }
      catch (error) {
        if (error instanceof RequirementActionEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async previewRequirementActionEvidence(sessionId, payload, signal) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-action-evidence/preview`,
        {
          method: "POST",
          headers: { "Content-Type": REQUIREMENT_ACTION_MEDIA_TYPE },
          body: payload,
        },
        signal,
        true,
        true,
      );
      try { return parseRequirementActionEvidencePreview(value, { sessionId }); }
      catch (error) {
        if (error instanceof RequirementActionEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async importRequirementActionEvidence(
      sessionId,
      payload,
      preview,
      confirmation,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-action-evidence/import`,
        {
          method: "POST",
          headers: {
            "Content-Type": REQUIREMENT_ACTION_MEDIA_TYPE,
            "Idempotency-Key": idempotencyKey,
            "X-Requirement-Action-Confirmation": confirmation,
            "X-Requirement-Action-Payload-SHA256": preview.payload_sha256,
          },
          body: payload,
        },
        signal,
        true,
        true,
      );
      try { return parseRequirementActionImport(value, preview); }
      catch (error) {
        if (error instanceof RequirementActionEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async listRequirementActionProposals(sessionId, signal) {
      const limit = 200;
      let offset = 0;
      let total: number | null = null;
      let stableSnapshot: import("./contracts").RequirementActionProposalPageSnapshot | null = null;
      const proposals: RequirementActionProposal[] = [];
      const identities = new Set<string>();
      let previousCreatedAtKey: string | null = null;
      let previousProposalId = "";
      for (let pageIndex = 0; pageIndex < 120; pageIndex += 1) {
        const snapshotParts = stableSnapshot === null ? [] : [
          `snapshot_id=${encodeURIComponent(stableSnapshot.snapshot_id)}`,
          `snapshot_total=${stableSnapshot.total}`,
          `snapshot_decision_count=${stableSnapshot.decision_count}`,
          ...(stableSnapshot.high_water_created_at === null ? [] : [
            `snapshot_high_water_created_at=${encodeURIComponent(stableSnapshot.high_water_created_at)}`,
            `snapshot_high_water_proposal_id=${encodeURIComponent(stableSnapshot.high_water_proposal_id!)}`,
          ]),
        ];
        const query = [
          `limit=${limit}`,
          `offset=${offset}`,
          ...snapshotParts,
        ].join("&");
        const value = await request<unknown>(
          `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-action-evidence/proposal-page?${query}`,
          { method: "GET" },
          signal,
          true,
          true,
        );
        try {
          const page = parseRequirementActionProposalPage(value, {
            sessionId, limit, offset, snapshot: stableSnapshot,
          });
          if (total !== null && page.total !== total) throw new RequirementActionEvidencePayloadError();
          total = page.total;
          stableSnapshot = page.snapshot;
          for (const proposal of page.proposals) {
            if (identities.has(proposal.proposal_id)) throw new RequirementActionEvidencePayloadError();
            const createdAtKey = requirementActionUtcMicrosecondKey(proposal.created_at);
            if (
              previousCreatedAtKey !== null
              && (createdAtKey < previousCreatedAtKey
                || (createdAtKey === previousCreatedAtKey && proposal.proposal_id <= previousProposalId))
            ) throw new RequirementActionEvidencePayloadError();
            identities.add(proposal.proposal_id);
            proposals.push(proposal);
            previousCreatedAtKey = createdAtKey;
            previousProposalId = proposal.proposal_id;
          }
          if (page.complete) {
            const boundary = proposals.at(-1);
            if (
              proposals.length !== total
              || stableSnapshot.decision_count !== proposals.filter((proposal) => proposal.status !== "proposed").length
              || (boundary === undefined) !== (stableSnapshot.total === 0)
              || (boundary !== undefined && (
                requirementActionUtcMicrosecondKey(stableSnapshot.high_water_created_at!)
                  !== requirementActionUtcMicrosecondKey(boundary.created_at)
                || stableSnapshot.high_water_proposal_id !== boundary.proposal_id
              ))
            ) throw new RequirementActionEvidencePayloadError();
            return { session_id: sessionId, proposals, total, complete: true, snapshot: stableSnapshot };
          }
          if (typeof page.next_offset !== "number") throw new RequirementActionEvidencePayloadError();
          offset = page.next_offset;
        } catch (error) {
          if (error instanceof RequirementActionEvidencePayloadError) {
            throw new TransportError(error.message, 200);
          }
          throw error;
        }
      }
      throw new TransportError("Requirement-action proposal list exceeded the reviewed page budget", 200);
    },
    async reviewRequirementActionProposal(
      sessionId,
      proposal,
      contract,
      reviewRequest,
      signal,
    ) {
      const path = `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-action-evidence/proposals/${encodeURIComponent(proposal.proposal_id)}/review`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reviewRequest),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseRequirementActionProposalReview(value, { sessionId, proposal, contract });
      } catch (error) {
        if (error instanceof RequirementActionEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async decideRequirementActionProposal(
      sessionId,
      proposalId,
      decisionRequest,
      idempotencyKey,
      signal,
    ) {
      const path = `/v1/sessions/${encodeURIComponent(sessionId)}/requirement-action-evidence/proposals/${encodeURIComponent(proposalId)}/decision`;
      const value = await request<unknown>(
        path,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(decisionRequest),
        },
        signal,
        true,
        true,
        true,
      );
      try {
        return parseRequirementActionProposalOutcome(value, {
          sessionId,
          proposalId,
          sourceRunId: decisionRequest.expected_source_run_id,
          decision: decisionRequest.decision,
        });
      } catch (error) {
        if (error instanceof RequirementActionEvidencePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getActiveModelEnsembleWatch(signal) {
      const value = await request<unknown>(
        "/v1/model-ensemble-watch/active",
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleWatchSnapshot(value);
      } catch (error) {
        if (error instanceof ModelEnsembleWatchPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getActiveModelEnsembleCanonicalHead(signal) {
      const value = await request<unknown>(
        "/v2/model-ensemble-watch/active/head",
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleCanonicalHead(value) as ModelEnsembleCanonicalHead;
      } catch (error) {
        if (error instanceof ModelEnsembleHeadPayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async getSessionModelEnsembleCanonicalHead(sessionId, signal) {
      const value = await request<unknown>(
        `/v2/sessions/${encodeURIComponent(sessionId)}/model-ensemble-head`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleCanonicalHead(value) as ModelEnsembleCanonicalHead;
      } catch (error) {
        if (error instanceof ModelEnsembleHeadPayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async getModelEnsembleSnapshot(runId, signal) {
      const value = await request<unknown>(
        `/v2/model-ensemble-snapshots/${encodeURIComponent(runId)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleRun(value);
      } catch (error) {
        if (error instanceof ModelEnsemblePayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async enqueueModelEnsembleAnalysis(watchId, signal) {
      const value = await request<unknown>(
        `/v2/model-ensemble-watches/${encodeURIComponent(watchId)}/analysis`,
        { method: "POST" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleCanonicalHead(value) as ModelEnsembleCanonicalHead;
      } catch (error) {
        if (error instanceof ModelEnsembleHeadPayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async cancelModelEnsembleAnalysis(watchId, signal) {
      const value = await request<unknown>(
        `/v2/model-ensemble-watches/${encodeURIComponent(watchId)}/attempts/active`,
        { method: "DELETE" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleCanonicalHead(value) as ModelEnsembleCanonicalHead;
      } catch (error) {
        if (error instanceof ModelEnsembleHeadPayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async getModelEnsembleAttempt(attemptId, signal) {
      const value = await request<unknown>(
        `/v2/model-ensemble-attempts/${encodeURIComponent(attemptId)}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleAttemptSnapshot(value) as ModelEnsembleAttemptSnapshot;
      } catch (error) {
        if (error instanceof ModelEnsembleHeadPayloadError) throw new TransportError(error.message, 200);
        throw error;
      }
    },
    async enableModelEnsembleWatch(
      sessionId,
      watchRequest: ModelEnsembleWatchRequest,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/sessions/${encodeURIComponent(sessionId)}/model-ensemble-watch`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(watchRequest),
        },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleWatchSnapshot(value);
      } catch (error) {
        if (error instanceof ModelEnsembleWatchPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async disableModelEnsembleWatch(watchId, signal) {
      const value = await request<unknown>(
        `/v1/model-ensemble-watches/${encodeURIComponent(watchId)}`,
        { method: "DELETE" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleWatchSnapshot(value);
      } catch (error) {
        if (error instanceof ModelEnsembleWatchPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async refreshModelEnsembleWatch(watchId, signal) {
      const value = await request<unknown>(
        `/v1/model-ensemble-watches/${encodeURIComponent(watchId)}/refresh`,
        { method: "POST" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleWatchSnapshot(value);
      } catch (error) {
        if (error instanceof ModelEnsembleWatchPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getModelEnsembleTrajectory(watchId, limit = 12, beforeGeneration, signal) {
      const query = new URLSearchParams({ limit: String(limit) });
      if (beforeGeneration !== undefined) {
        query.set("before_generation", String(beforeGeneration));
      }
      const value = await request<unknown>(
        `/v1/model-ensemble-watches/${encodeURIComponent(watchId)}/trajectory?${query.toString()}`,
        { method: "GET" },
        signal,
        true,
        true,
      );
      try {
        return parseModelEnsembleTrajectoryPage(
          value,
          beforeGeneration === undefined,
        ) as ModelEnsembleTrajectoryPage;
      } catch (error) {
        if (error instanceof ModelEnsembleTrajectoryPayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    listCandidates(status = "all", signal, page) {
      const query = new URLSearchParams();
      if (status !== "all") query.set("status", status);
      if (page !== undefined) {
        query.set("limit", String(page.limit));
        query.set("offset", String(page.offset));
      }
      const suffix = query.size === 0 ? "" : `?${query.toString()}`;
      return request<CandidateListResponse>(`/v1/discovery/candidates${suffix}`, { method: "GET" }, signal);
    },
    listTaskRevisions(taskId, signal, page) {
      const query = new URLSearchParams();
      if (taskId) query.set("task_id", taskId);
      if (page !== undefined) {
        query.set("limit", String(page.limit));
        query.set("offset", String(page.offset));
      }
      const suffix = query.size === 0 ? "" : `?${query.toString()}`;
      return request<TaskRevisionListResponse>(`/v1/task-revisions${suffix}`, { method: "GET" }, signal);
    },
    async getCandidateDecisions(candidateId, signal) {
      const response = await request<unknown>(
        `/v1/discovery/candidates/${encodeURIComponent(candidateId)}/decisions`,
        { method: "GET" },
        signal,
      );
      return parseCandidateDecisionsResponse(response, candidateId);
    },
    getTaskRevision(taskId, revision, signal) {
      return request<TaskRevisionResponse>(
        `/v1/tasks/${encodeURIComponent(taskId)}/revisions/${revision}`,
        { method: "GET" },
        signal,
      );
    },
    async listTaskLifecycles(signal, page, eventLimit = 100) {
      const limit = page?.limit ?? 100;
      const offset = page?.offset ?? 0;
      const query = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
        event_limit: String(eventLimit),
      });
      const value = await request<unknown>(
        `/v1/task-lifecycles?${query.toString()}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseTaskLifecycleListResponse(value, { limit, offset });
      } catch (error) {
        if (error instanceof TaskLifecyclePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async getTaskLifecycle(taskId, revision, eventLimit = 100, eventOffset = 0, signal) {
      const query = new URLSearchParams({
        event_limit: String(eventLimit),
        event_offset: String(eventOffset),
      });
      const value = await request<unknown>(
        `/v1/tasks/${encodeURIComponent(taskId)}/revisions/${revision}/lifecycle?${query.toString()}`,
        { method: "GET" },
        signal,
        false,
        true,
      );
      try {
        return parseTaskLifecycleSnapshot(value, { taskId, revision });
      } catch (error) {
        if (error instanceof TaskLifecyclePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async transitionTaskLifecycle(
      taskId,
      revision,
      expectedHeadEventId,
      state: TaskLifecycleState,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/tasks/${encodeURIComponent(taskId)}/revisions/${revision}/lifecycle/transitions`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify({
            expected_head_event_id: expectedHeadEventId,
            state,
          }),
        },
        signal,
        false,
        true,
      );
      try {
        return parseTaskLifecycleMutationResponse(value, {
          taskId,
          revision,
          eventKind: "transition",
          expectedHeadEventId,
          requestedState: state,
        });
      } catch (error) {
        if (error instanceof TaskLifecyclePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    async correctTaskLifecycle(
      taskId,
      revision,
      expectedHeadEventId,
      expectedPriorState,
      expectedResultingState,
      idempotencyKey,
      signal,
    ) {
      const value = await request<unknown>(
        `/v1/tasks/${encodeURIComponent(taskId)}/revisions/${revision}/lifecycle/corrections`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify({
            expected_head_event_id: expectedHeadEventId,
            supersedes_event_id: expectedHeadEventId,
          }),
        },
        signal,
        false,
        true,
      );
      try {
        return parseTaskLifecycleMutationResponse(value, {
          taskId,
          revision,
          eventKind: "correction",
          expectedHeadEventId,
          correctionPriorState: expectedPriorState,
          correctionResultingState: expectedResultingState,
        });
      } catch (error) {
        if (error instanceof TaskLifecyclePayloadError) {
          throw new TransportError(error.message, 200);
        }
        throw error;
      }
    },
    listAnalysisRuns(taskId, signal, page) {
      const query = new URLSearchParams();
      if (taskId) query.set("task_id", taskId);
      if (page !== undefined) {
        query.set("limit", String(page.limit));
        query.set("offset", String(page.offset));
      }
      const suffix = query.size === 0 ? "" : `?${query.toString()}`;
      return request<AnalysisRunListResponse>(`/v1/analysis/runs${suffix}`, { method: "GET" }, signal);
    },
    getAnalysisRun(runId, signal) {
      return request<AnalysisRunResponse>(
        `/v1/analysis/runs/${encodeURIComponent(runId)}`,
        { method: "GET" },
        signal,
      );
    },
    review(command, idempotencyKey, signal) {
      return request<TaskReviewResponse>(
        `/v1/task-decisions/${command.action}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(command.request),
        },
        signal,
      );
    },
    startAnalysis(taskId, revision, idempotencyKey, signal) {
      return request<TaskAnalysisResponse>(
        `/v1/tasks/${encodeURIComponent(taskId)}/revisions/${revision}/analysis-runs`,
        {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey },
        },
        signal,
      );
    },
  };
}
