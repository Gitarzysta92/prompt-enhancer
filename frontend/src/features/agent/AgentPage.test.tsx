import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentArtifact, AgentArtifactPage, AgentArtifactPageQuery, AgentAttachment, AgentCatalogSession, AgentEvent, AgentEvents, AgentHistoryExport, AgentMcpConnection, AgentMcpConnectionList, AgentMessageAttachment, AgentProject, AgentSessionView, AgentSettings, AgentWorkspaceTree, ForkAgentSession, LocalModelStatus, LocalModelsOverview, LocalRuntimeCoordinatorStatus, PromptCheckRequest, PromptCheckResult, UpdateAgentCatalogSession } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { exampleAgentOrchestrationManifest } from "../../shared/api/agentOrchestrationFixtures.test-support";
import { syntheticMcpManagedProjectRuntime } from "../../shared/api/mcpManagedRuntime.test-support";
import {
  syntheticMcpManagedProbeReceipt,
  syntheticMcpManagedServer,
  syntheticMcpManagedServerList,
  syntheticMcpManagedToolSnapshot,
} from "../../shared/api/mcpManagedServer.test-support";
import { AgentPage, readCompleteRetainedEvents } from "./AgentPage";
import {
  AGENT_WINDOW_CHANNEL_VERSION,
  connectAgentWindowSelectionOwner,
  listenForAgentWindowSelection,
} from "./agentWindowChannel";
import { exampleAgentTurn } from "./agentTurnFixtures.test-support";
import "../../styles.css";

const SESSION = "a".repeat(32);
const APPROVAL = "b".repeat(32);
const MODEL_ALIAS = "orca27b-iq3m";
const originalPywebview = Object.getOwnPropertyDescriptor(globalThis, "pywebview");
const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");

// This file exercises the complete Agent workbench 100+ times. Leave enough
// room for a heavily loaded CI worker to settle async catalogue/session reads.
configure({ asyncUtilTimeout: 3_000 });

function userPresenceCapability(available: boolean) {
  return {
    contract_version: "native-user-presence-capability-v1" as const,
    confirmation_available: available,
    mode: available ? "native_bridge_bound_token" as const : "unavailable" as const,
  };
}

function installNativeFolderPicker(choose: () => Promise<unknown>): void {
  Object.defineProperty(globalThis, "pywebview", {
    configurable: true,
    value: { api: { choose_workspace_folder: choose } },
  });
}

afterEach(() => {
  if (originalPywebview) Object.defineProperty(globalThis, "pywebview", originalPywebview);
  else Reflect.deleteProperty(globalThis, "pywebview");
  if (originalScrollIntoView) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScrollIntoView);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  if (originalCreateObjectURL) Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevokeObjectURL) Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
  else Reflect.deleteProperty(URL, "revokeObjectURL");
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function view(overrides: Partial<AgentSessionView> = {}): AgentSessionView {
  return {
    contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false,
    session_id: SESSION,
    settings: { workspace: "D:\\example\\project", project_id: null, model_alias: null, parameters: { temperature: 0.2, top_p: 0.95, max_tokens: 1400, enable_thinking: false }, instructions: null, allow_writes: true, allow_commands: true, allow_web: false, max_steps: 10, command_timeout_seconds: 120, title: null, retention_policy: "metadata_only" },
    created_at: "2026-08-20T01:00:00Z",
    running: false,
    last_seq: 0,
    pending_approval_id: null,
    model_alias: MODEL_ALIAS,
    turns: 0,
    history_revision: 0,
    recovered: false,
    authority_revalidated: true,
    history_write_failed: false,
    recovery_state: "current",
    ...overrides,
  };
}

function event(seq: number, kind: AgentEvent["kind"], extra: Partial<AgentEvent> = {}): AgentEvent {
  return { seq, at: "2026-08-20T01:00:00Z", kind, attachments: [], text: null, tool: null, arguments: null, call_id: null, approval_id: null, ok: null, preview: null, ...extra };
}

function modelStatus(
  state: LocalModelStatus["runtime"]["state"],
  alias = MODEL_ALIAS,
  displayName = "Synthetic Local Model",
): LocalModelStatus {
  return {
    endpoint_path: `/v1/local-models/${alias}/chat`,
    record: {
      added_at: "2026-08-20T00:00:00Z",
      alias,
      context_size: 8192,
      default_device: "cpu",
      display_name: displayName,
      format: "gguf",
      path: "D:\\example\\models\\synthetic-model.gguf",
      provenance_verified: true,
    },
    runtime: { state },
    placement: {
      contract_version: "local-model-placement.v1",
      alias,
      context_size: 8192,
      gpu_memory_free_mb: null,
      actual_offload_verified: false,
      options: [
        { device: "gpu", state: "blocked", reason_code: "accelerator_evidence_unavailable", recommended_gpu_layers: null, estimated_vram_required_mb: null },
        { device: "split", state: "blocked", reason_code: "accelerator_evidence_unavailable", recommended_gpu_layers: null, estimated_vram_required_mb: null },
        { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
      ],
    },
  };
}

function modelsOverview(...models: LocalModelStatus[]): LocalModelsOverview {
  return {
    contract_version: "local-models.v1",
    runtime_available: true,
    storage_root: "D:\\example\\models",
    storage_free_bytes: 64 * 1024 ** 3,
    download_reserve_bytes: 512 * 1024 ** 2,
    download_ledger_error_code: null,
    downloads: [],
    hardware: {
      gpu_name: null,
      gpu_memory_mb: null,
      gpu_memory_free_mb: null,
      ram_mb: null,
      llama_server_path: null,
      llama_server_version: null,
    },
    models,
  };
}

function runtimeCoordinator(alias: string, revision = 7): LocalRuntimeCoordinatorStatus {
  const selection = {
    alias,
    device: "cpu" as const,
    gpu_layers: 0,
    context_size: 8192,
  };
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision,
    state: "ready",
    requested: selection,
    served: {
      ...selection,
      pid: 4242,
      started_at: "2040-01-01T10:00:00Z",
    },
    active_requests: 0,
    cleanup: {
      state: "not_required",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: null,
      gpu_memory_free_after_mb: null,
      gpu_memory_released_mb: null,
    },
    capabilities: {
      probe_version: "local-runtime-multimodal-probe.v2",
      state: "verified",
      text: true,
      tools: true,
      structured_output: false,
      vision: false,
      audio: false,
      recording: false,
      error_code: null,
    },
    context: {
      state: "unknown",
      used_tokens: null,
      limit_tokens: 8192,
      requested_output_tokens: null,
      available_output_tokens: null,
      source: "runtime_limit_only",
      scope: "runtime_limit",
      policy: "runtime_enforced",
      compacted_messages: 0,
      reason_code: "no_request_measured",
    },
    last_error_code: null,
  };
}

function idleRuntimeCoordinator(revision = 7): LocalRuntimeCoordinatorStatus {
  return {
    ...runtimeCoordinator(MODEL_ALIAS, revision),
    state: "idle",
    requested: null,
    served: null,
  };
}

function imageMessageAttachment(): AgentMessageAttachment {
  return {
    contract_version: "agent-attachment.v2",
    attachment_id: "d".repeat(32),
    display_name: "example-diagram.png",
    kind: "image",
    media_type: "image/png",
    byte_size: 68,
    sha256: "e".repeat(64),
    width: 1,
    height: 1,
    duration_ms: null,
    sample_rate_hz: null,
    channels: null,
    routing: "native_multimodal",
    document_format: null,
    projected_characters: null,
    projection_truncated: null,
    omitted_features: [],
    context_tokens: null,
    context_cost_source: "runtime_unreported",
  };
}

function documentMessageAttachment(): AgentMessageAttachment {
  return {
    ...imageMessageAttachment(),
    display_name: "example-notes.md",
    kind: "document",
    media_type: "text/markdown",
    byte_size: 2_048,
    width: null,
    height: null,
    routing: "local_text_projection",
    document_format: "markdown",
    projected_characters: 1_024,
    projection_truncated: true,
    omitted_features: [],
  };
}

function stagedImageAttachment(): AgentAttachment {
  return {
    ...imageMessageAttachment(),
    session_id: SESSION,
    model_alias: MODEL_ALIAS,
    capability_probe_version: "local-runtime-multimodal-probe.v2",
    source: "file",
    retention: "memory_only",
    state: "staged",
    created_at: "2040-01-01T10:00:00Z",
    expires_at: "2040-01-01T11:00:00Z",
    attached_event_seq: null,
  };
}

function workspaceMethods() {
  return {
    getAgentWorkspaceTree: vi.fn(async (sessionId: string, path: string): Promise<AgentWorkspaceTree> => ({
      contract_version: "local-agent-workspace.v1" as const,
      session_id: sessionId,
      path,
      entries: [],
      complete: true,
    })),
    getAgentWorkspaceFile: vi.fn(),
    previewAgentWorkspaceEdit: vi.fn(),
    applyAgentWorkspaceEdit: vi.fn(),
  };
}

function promptCheckResult(overrides: Partial<PromptCheckResult> = {}): PromptCheckResult {
  return {
    contract_version: "prompt-check.v1",
    check_id: "c".repeat(32),
    created_at: "2026-08-20T01:02:00Z",
    provider: "other",
    agent_model: "orca27b-iq3m",
    metrics: [{
      key: "prompt.acceptance_testability",
      display_name: "Acceptance testability",
      description: "Checkable acceptance requirements",
      state: "known",
      value: 0.5,
      numerator: 1,
      denominator: 2,
      higher_is_better: true,
      explanation_code: "observed",
      cues: [],
    }],
    context: {
      task_type: "implement",
      language: "en",
      prompt_chars: 42,
      prompt_words: 8,
      sentence_count: 1,
      bullet_count: 0,
      question_count: 0,
      file_references: 1,
      code_identifiers: 0,
      urls: 0,
      prior_context_supplied: 2,
      depends_on_prior_context: true,
      verification_requested: false,
      missing_elements: ["a checkable pass condition"],
    },
    commentary: {
      state: "ok",
      model_alias: "orca27b-iq3m",
      prompt_version: "prompt-check-commentary-v1",
      findings: [{ aspect: "verification", severity: "high", why: "No test is named.", suggestion: "Name the exact test command." }],
      reformulated_prompt: "Update example.ts and run the focused test; report the changed files and result.",
      reformulated_elements: [],
      notes: null,
      caveat: "Local-model suggestion; not measured evidence.",
    },
    summary: "The goal is visible, but verification needs a concrete pass condition.",
    engine_version: "engine-v1",
    rubric_version: "rubric-v1",
    dashboard_path: "/prompt-checks/" + "c".repeat(32),
    other_metric_families_note: "Collaboration and outcome metrics require later session evidence.",
    ...overrides,
  };
}

function sessionTransport(...sessions: AgentSessionView[]) {
  return {
    ...workspaceMethods(),
    listAgentSessions: vi.fn(async () => sessions),
    createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
    getAgentEvents: vi.fn(async (sessionId: string) => ({
      contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: sessionId, events: [],
      running: false, pending_approval_id: null, last_seq: 0, first_seq: 0,
    })),
    decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
  };
}

function catalogProjectFixture(
  projectId: string,
  name: string,
  sessionCount: number,
): AgentProject {
  return {
    contract_version: "agent-catalog.v2",
    project_id: projectId,
    name,
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 1,
    pinned: false,
    archived_at: null,
    session_count: sessionCount,
    is_default: false,
  };
}

function catalogSessionFixture(
  sessionId: string,
  projectId: string,
  title: string,
  overrides: Partial<AgentCatalogSession> = {},
): AgentCatalogSession {
  return {
    contract_version: "agent-catalog.v2",
    session_id: sessionId,
    project_id: projectId,
    title,
    workspace: "D:\\example\\move-workspace",
    model_alias: MODEL_ALIAS,
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    last_opened_at: "2040-01-01T10:00:00Z",
    revision: 1,
    pinned: false,
    archived_at: null,
    history_state: "memory_only",
    retention_policy: "metadata_only",
    history_revision: 0,
    last_event_seq: 0,
    turn_count: 0,
    conversation_available: false,
    lineage: null,
    ...overrides,
  };
}

function artifactFixture(
  index: number,
  projectId: string,
  sessionId: string,
  lifecycleState: "active" | "archived" = "active",
): AgentArtifact {
  const artifactId = (index + 100).toString(16).padStart(32, "0");
  const path = `outputs/synthetic-${index.toString().padStart(3, "0")}.md`;
  const createdAt = "2040-01-01T10:00:00Z";
  const updatedAt = lifecycleState === "archived" ? "2040-01-01T10:01:00Z" : createdAt;
  return {
    contract_version: "agent-artifact.v3",
    artifact_id: artifactId,
    project_id: projectId,
    session_id: sessionId,
    title: `Synthetic artifact ${index.toString().padStart(3, "0")}`,
    kind: "markdown",
    path,
    created_at: createdAt,
    updated_at: updatedAt,
    revision: lifecycleState === "archived" ? 2 : 1,
    version_count: 1,
    availability: "available",
    lifecycle_state: lifecycleState,
    archived_at: lifecycleState === "archived" ? updatedAt : null,
    removed_at: null,
    latest_version: {
      contract_version: "agent-artifact.v3",
      version_id: (index + 1000).toString(16).padStart(32, "0"),
      artifact_id: artifactId,
      version_number: 1,
      created_at: createdAt,
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
}

function artifactPageFixture(
  artifacts: AgentArtifact[],
  total: number,
  projectId: string,
  sessionId: string,
  offset = 0,
  view: "active" | "archived" = "active",
): AgentArtifactPage {
  const nextOffset = offset + artifacts.length < total ? offset + artifacts.length : null;
  return {
    contract_version: "agent-artifact-page.v1",
    project_id: projectId,
    session_id: sessionId,
    view,
    snapshot: "a".repeat(64),
    limit: 100,
    offset,
    total,
    next_offset: nextOffset,
    complete: nextOffset === null,
    counts: view === "active"
      ? { active: total, archived: 0, removed: 0, total }
      : { active: 0, archived: total, removed: 0, total },
    artifacts,
  };
}

function artifactViewerMethods() {
  return {
    getAgentArtifact: vi.fn(),
    getAgentArtifactContent: vi.fn(),
    updateAgentArtifact: vi.fn(),
    removeAgentArtifact: vi.fn(),
  };
}

function historyExportFixture(session: AgentCatalogSession): AgentHistoryExport {
  return {
    contract_version: "agent-history.v1",
    exported_at: "2040-01-01T10:05:00Z",
    project_id: session.project_id,
    session_id: session.session_id,
    title: session.title,
    workspace: session.workspace,
    model_alias: session.model_alias,
    history_revision: session.history_revision,
    turn_count: session.turn_count,
    interrupted: false,
    events: [],
  };
}

function retainedCatalogTransport<T extends object>(
  project: AgentProject,
  sessions: AgentCatalogSession[],
  extra: T,
) {
  return {
    ...sessionTransport(),
    listAgentProjects: vi.fn(async () => ({
      contract_version: "agent-catalog.v2" as const,
      projects: [project],
    })),
    createAgentProject: vi.fn(async () => project),
    updateAgentProject: vi.fn(async () => project),
    deleteAgentProject: vi.fn(async () => undefined),
    listAgentCatalogSessions: vi.fn(async () => ({
      contract_version: "agent-catalog.v2" as const,
      sessions,
    })),
    getAgentCatalogSession: vi.fn(async (sessionId: string) => (
      sessions.find((session) => session.session_id === sessionId) ?? sessions[0]
    )),
    updateAgentCatalogSession: vi.fn(async (_sessionId: string, request: UpdateAgentCatalogSession) => ({
      ...sessions[0],
      revision: request.expected_revision + 1,
    })),
    deleteAgentCatalogSession: vi.fn(async () => undefined),
    getAgentPersistedEvents: vi.fn(async (_projectId: string, sessionId: string) => ({
      contract_version: "local-agent.v9" as const,
      session_id: sessionId,
      events: [],
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: 0,
      first_seq: 0,
    })),
    ...extra,
  };
}

function turnRevisionHarness(
  retainedEvents: AgentEvent[],
  options: { sendFailure?: unknown } = {},
) {
  const projectId = "7".repeat(32);
  const childSessionId = "9".repeat(32);
  const head = retainedEvents.at(-1)?.seq ?? 0;
  const sourceTurns = retainedEvents.filter((item) => item.kind === "done").length;
  const project = catalogProjectFixture(projectId, "Revision project", 1);
  const sourceRecord = catalogSessionFixture(SESSION, projectId, "Revision source", {
    history_state: "durable_local",
    retention_policy: "local_history",
    history_revision: head,
    last_event_seq: head,
    turn_count: sourceTurns,
    conversation_available: true,
  });
  const sourceView = view({
    settings: {
      ...view().settings,
      project_id: projectId,
      title: sourceRecord.title,
      model_alias: MODEL_ALIAS,
      retention_policy: "local_history",
    },
    history_revision: head,
    last_seq: head,
    turns: sourceTurns,
  });
  let childRecord: AgentCatalogSession | null = null;
  let childView: AgentSessionView | null = null;
  const forkAgentSession = vi.fn(async (
    _projectId: string,
    _sessionId: string,
    request: ForkAgentSession,
    _signal?: AbortSignal,
  ) => {
    const branchPoint = request.through_event_seq ?? head;
    const copiedTurns = retainedEvents.filter((item) => item.kind === "done" && item.seq <= branchPoint).length;
    childRecord = catalogSessionFixture(childSessionId, projectId, "Revision source (branch)", {
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: branchPoint,
      last_event_seq: branchPoint,
      turn_count: copiedTurns,
      conversation_available: true,
      lineage: {
        contract_version: "agent-session-lineage.v1",
        source_project_id: projectId,
        source_session_id: SESSION,
        source_catalog_revision: sourceRecord.revision,
        source_history_revision: sourceRecord.history_revision,
        branch_event_seq: branchPoint,
        copied_event_count: branchPoint,
        copied_turn_count: copiedTurns,
        copied_attachment_count: 0,
        created_at: "2040-01-01T10:02:00Z",
      },
    });
    childView = view({
      session_id: childSessionId,
      settings: {
        ...sourceView.settings,
        title: childRecord.title,
        allow_writes: false,
        allow_commands: false,
        allow_web: false,
      },
      history_revision: branchPoint,
      last_seq: branchPoint,
      turns: copiedTurns,
      recovered: true,
      authority_revalidated: false,
    });
    return {
      contract_version: "agent-session-fork.v1" as const,
      request_id: request.request_id,
      idempotent_replay: false,
      source_tail_omitted: branchPoint < head,
      approvals_copied: false as const,
      mutation_authority_copied: false as const,
      pending_tool_state_copied: false as const,
      staged_attachments_copied: false as const,
      artifacts_copied: false as const,
      session: childRecord,
    };
  });
  const resumeAgentSession = vi.fn(async () => {
    if (childView === null) throw new Error("synthetic_child_missing");
    return childView;
  });
  const sendAgentMessage = options.sendFailure === undefined
    ? vi.fn(async () => {
        if (childView === null) throw new Error("synthetic_child_missing");
        return { ...childView, running: true, turns: childView.turns + 1 };
      })
    : vi.fn(async () => { throw options.sendFailure; });
  const transport = retainedCatalogTransport(project, [sourceRecord], {
    listAgentSessions: vi.fn(async () => [sourceView]),
    getAgentCatalogSession: vi.fn(async () => sourceRecord),
    getAgentEvents: vi.fn(async (sessionId: string, after: number) => ({
      contract_version: "local-agent.v9" as const,
      cleanup_unconfirmed: false,
      closing: false,
      stopping: false,
      session_id: sessionId,
      events: sessionId === SESSION ? retainedEvents.filter((item) => item.seq > after) : [],
      running: sessionId === childSessionId && Boolean(childView?.running),
      pending_approval_id: null,
      last_seq: sessionId === SESSION ? head : childView?.last_seq ?? 0,
      first_seq: sessionId === SESSION && head > 0 ? 1 : 0,
    })),
    getAgentPersistedEvents: vi.fn(async (_projectId: string, sessionId: string, after: number) => ({
      contract_version: "local-agent.v9" as const,
      cleanup_unconfirmed: false,
      closing: false,
      stopping: false,
      session_id: sessionId,
      events: sessionId === SESSION ? retainedEvents.filter((item) => item.seq > after) : [],
      running: false,
      pending_approval_id: null,
      last_seq: sessionId === SESSION ? head : childRecord?.last_event_seq ?? 0,
      first_seq: sessionId === SESSION && head > 0 ? 1 : 0,
    })),
    forkAgentSession,
    resumeAgentSession,
    sendAgentMessage,
  });
  return {
    childSessionId,
    forkAgentSession,
    project,
    resumeAgentSession,
    sendAgentMessage,
    sourceRecord,
    sourceView,
    transport,
  };
}

function editableWorkspaceTransport(...sessions: AgentSessionView[]) {
  const transport = sessionTransport(...sessions);
  transport.getAgentWorkspaceTree.mockResolvedValue({
    contract_version: "local-agent-workspace.v1" as const,
    session_id: sessions[0]?.session_id ?? SESSION,
    path: ".",
    entries: [{
      path: "synthetic-note.txt",
      name: "synthetic-note.txt",
      kind: "file" as const,
      byte_size: 24,
      editable_candidate: true,
    }],
    complete: true,
  });
  transport.getAgentWorkspaceFile.mockImplementation(async (sessionId: string) => ({
    contract_version: "local-agent-workspace.v1" as const,
    session_id: sessionId,
    path: "synthetic-note.txt",
    content: "Synthetic original text.\n",
    revision: "f".repeat(64),
    byte_size: 25,
    line_ending: "lf" as const,
    editable: true as const,
  }));
  return transport;
}

async function openDirtyWorkspaceDraft(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: "Files & review" }));
  fireEvent.click(await screen.findByRole("button", { name: "synthetic-note.txt" }));
  const editor = await screen.findByLabelText("Workspace file editor");
  await waitFor(() => expect(editor).toHaveValue("Synthetic original text.\n"));
  fireEvent.change(editor, { target: { value: "Synthetic unsaved edit.\n" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Discard draft" })).toBeEnabled());
  return editor;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

async function acceptCloseChat(): Promise<void> {
  const dialog = await screen.findByRole("dialog", { name: "Close live chat?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Close chat" }));
}

function controlledStop(initial = view({ running: true, turns: 1 })) {
  const command = deferred<AgentSessionView>();
  let onPage: ((page: AgentEvents) => void) | undefined;
  const transport = {
    ...sessionTransport(initial),
    stopAgentSession: vi.fn((_id: string, _signal?: AbortSignal) => command.promise),
    streamAgentEvents: vi.fn(async (_id: string, _after: number, accept: (page: AgentEvents) => void, signal?: AbortSignal) => {
      onPage = accept;
      await new Promise<void>((resolve) => {
        if (signal?.aborted) resolve();
        else signal?.addEventListener("abort", () => resolve(), { once: true });
      });
    }),
  };
  return {
    command, transport,
    publish: (last_seq: number, running: boolean, stopping = false) => act(() => onPage!({
      contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: SESSION, closing: false, stopping, running,
      pending_approval_id: null, first_seq: 1, last_seq,
      events: [event(last_seq, "status", { text: "Example runtime state changed." })],
    })),
  };
}

describe("request-owned Agent Stop", () => {
  it("keeps the next-message draft editable while a response runs and unlocks Send afterward", async () => {
    const fixture = controlledStop();
    render(<AgentPage transport={fixture.transport} />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(fixture.transport.streamAgentEvents).toHaveBeenCalled());
    expect(composer).toBeEnabled();
    expect(composer).toHaveAttribute("placeholder", "Write the next message while the agent responds…");
    expect(screen.getByText("Write the next message now · Send unlocks when this response ends")).toBeVisible();
    fireEvent.change(composer, { target: { value: "Example instruction for the next turn" } });
    fireEvent.keyDown(composer, { key: "Enter", ctrlKey: true });
    expect(fixture.transport.sendAgentMessage).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeVisible();

    fixture.publish(2, false);
    expect(composer).toBeEnabled();
    expect(composer).toHaveValue("Example instruction for the next turn");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.getByText("Ctrl/⌘+Enter sends · Enter adds a line")).toBeVisible();
  });

  it("coalesces clicks, waits for the worker, and preserves the next draft", async () => {
    const fixture = controlledStop(view({ turns: 1 }));
    await act(async () => { render(<AgentPage transport={fixture.transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Example next draft" } });
    fixture.publish(1, true);
    const stop = screen.getByRole("button", { name: "Stop response" });
    fireEvent.click(stop);
    fireEvent.click(stop);
    expect(fixture.transport.stopAgentSession).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Stopping response");
    expect(screen.getByText(/running · stopping current response/)).toBeVisible();
    expect(screen.queryByText(/running · ready for messages/)).toBeNull();
    await act(async () => fixture.command.resolve(view({ running: true, stopping: true, turns: 1, last_seq: 2 })));
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    fixture.publish(3, false);
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Example next draft");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.getByText(/running · ready for messages/)).toBeVisible();
  });

  it("does not let a stale Stop acknowledgment or event page rewind a newer turn", async () => {
    const fixture = controlledStop();
    await act(async () => { render(<AgentPage transport={fixture.transport} />); });
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
    fixture.publish(5, true);
    await act(async () => fixture.command.resolve(view({ running: true, stopping: true, turns: 1, last_seq: 2 })));
    expect(screen.getByRole("button", { name: "Stop response" })).toBeEnabled();
    fixture.publish(2, true, true);
    expect(screen.getByLabelText("Agent activity status")).not.toHaveTextContent("Stopping response");
    expect(screen.getByRole("button", { name: "Stop response" })).toBeEnabled();
    fixture.publish(6, false);
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
  });

  it("does not let an equal-head page captured before Stop clear the newer acknowledgement", async () => {
    const fixture = controlledStop(view({ running: true, turns: 1, last_seq: 2 }));
    await act(async () => { render(<AgentPage transport={fixture.transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), {
      target: { value: "Synthetic next request" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
    await act(async () => fixture.command.resolve(view({ running: true, stopping: true, turns: 1, last_seq: 2 })));
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();

    // This is the first stream page, but it was captured before the Stop POST
    // completed. Its event head is equal to the acknowledgement, so its
    // `stopping: false` snapshot must not rewind the newer request state.
    fixture.publish(2, true, false);
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Stopping response");

    fixture.publish(3, false);
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.getByText(/running · ready for messages/)).toBeVisible();
  });

  it("offers retry after a failed stop without claiming the response ended", async () => {
    const fixture = controlledStop();
    await act(async () => { render(<AgentPage transport={fixture.transport} />); });
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
    await act(async () => fixture.command.reject(new Error("example stop request failed")));
    expect(screen.getByRole("alert")).toHaveTextContent("could not be stopped");
    expect(screen.getByRole("button", { name: "Stop response" })).toBeEnabled();
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    fixture.transport.stopAgentSession.mockResolvedValueOnce(view({ running: true, stopping: true, turns: 1 }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Stop response" })));
    expect(fixture.transport.stopAgentSession).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
  });

  it("recognizes a stop requested in another window", async () => {
    const fixture = controlledStop(view({ running: true, stopping: true, turns: 1 }));
    await act(async () => { render(<AgentPage transport={fixture.transport} windowMode />); });
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Stopping response");
    expect(fixture.transport.stopAgentSession).not.toHaveBeenCalled();
    fixture.publish(2, false);
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
  });

  it("releases the pending acknowledgment request when its view is unmounted", async () => {
    const fixture = controlledStop();
    const rendered = render(<AgentPage transport={fixture.transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop response" }));
    const signal = fixture.transport.stopAgentSession.mock.calls[0][1];
    expect(signal?.aborted).toBe(false);
    rendered.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => fixture.command.reject(new Error("example view closed")));
  });
});

describe("AgentPage coordinated runtime integration", () => {
  it("preserves an unsent prompt while switching the shared model and rebinding the chat", async () => {
    const nextAlias = "example-model-b";
    const current = view({
      settings: { ...view().settings, model_alias: MODEL_ALIAS },
      model_alias: MODEL_ALIAS,
    });
    const rebound = view({
      settings: { ...view().settings, model_alias: nextAlias },
      model_alias: nextAlias,
    });
    const catalog: AgentCatalogSession = {
      contract_version: "agent-catalog.v2",
      session_id: SESSION,
      project_id: "d".repeat(32),
      title: "Synthetic runtime chat",
      workspace: "D:\\example\\project",
      model_alias: MODEL_ALIAS,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      last_opened_at: "2040-01-01T10:00:00Z",
      revision: 3,
      pinned: false,
      archived_at: null,
      history_state: "memory_only",
      retention_policy: "metadata_only",
      history_revision: 0,
      last_event_seq: 0,
      turn_count: 0,
      conversation_available: true,
      lineage: null,
    };
    let runtimeState = runtimeCoordinator(MODEL_ALIAS);
    const getLocalModels = vi.fn(async () => modelsOverview(
      modelStatus(runtimeState.served?.alias === MODEL_ALIAS ? "running" : "stopped", MODEL_ALIAS, "Example Model A"),
      modelStatus(runtimeState.served?.alias === nextAlias ? "running" : "stopped", nextAlias, "Example Model B"),
    ));
    const transport = {
      ...sessionTransport(current),
      getLocalModels,
      getLocalRuntime: vi.fn(async () => runtimeState),
      switchLocalRuntime: vi.fn(async () => {
        runtimeState = runtimeCoordinator(nextAlias, runtimeState.revision + 1);
        return runtimeState;
      }),
      stopLocalRuntime: vi.fn(),
      getAgentCatalogSession: vi.fn(async () => catalog),
      switchAgentSessionModel: vi.fn(async () => rebound),
    };

    render(<AgentPage transport={transport} />);
    const composer = await screen.findByLabelText("Message to the agent");
    fireEvent.change(composer, { target: { value: "Keep this synthetic unsent prompt" } });
    const runtimePanel = await screen.findByRole("region", { name: "Shared local model runtime" });
    const runtimeDisclosure = await within(runtimePanel).findByLabelText(
      /Model and context settings\..*Ready\./,
    );
    fireEvent.click(runtimeDisclosure);

    fireEvent.change(within(runtimePanel).getByLabelText("Model"), { target: { value: nextAlias } });
    fireEvent.click(within(runtimePanel).getByRole("button", { name: "Switch model" }));

    await waitFor(() => expect(transport.switchAgentSessionModel).toHaveBeenCalledWith(SESSION, {
      model_alias: nextAlias,
      expected_revision: 3,
    }, expect.any(AbortSignal)));
    expect(transport.switchLocalRuntime).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByLabelText("Message to the agent")).toHaveValue("Keep this synthetic unsent prompt"));
    expect(await within(runtimePanel).findByRole("status")).toHaveTextContent("This chat is bound to it.");
  });
});

describe("AgentPage", () => {
  it("restores the newest durable chat without covering the catalog with setup", async () => {
    const projectId = "7".repeat(32);
    const project = {
      contract_version: "agent-catalog.v2" as const,
      project_id: projectId,
      name: "Saved example project",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      revision: 1,
      pinned: false,
      archived_at: null,
      session_count: 1,
      is_default: false,
    };
    const saved: AgentCatalogSession = {
      contract_version: "agent-catalog.v2",
      session_id: SESSION,
      project_id: projectId,
      title: "Saved example chat",
      workspace: "D:\\example\\saved-project",
      model_alias: MODEL_ALIAS,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      last_opened_at: "2040-01-01T10:01:00Z",
      revision: 1,
      pinned: false,
      archived_at: null,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 0,
      last_event_seq: 0,
      turn_count: 0,
      conversation_available: true,
      lineage: null,
    };
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [project] })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, sessions: [saved] })),
      updateAgentCatalogSession: vi.fn(async () => saved),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      getAgentPersistedEvents: vi.fn(async (): Promise<AgentEvents> => ({
        contract_version: "local-agent.v9",
        session_id: SESSION,
        events: [],
        running: false,
        closing: false,
        stopping: false,
        cleanup_unconfirmed: false,
        pending_approval_id: null,
        first_seq: 0,
        last_seq: 0,
      })),
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole(
      "heading",
      { level: 1, name: "Saved example chat" },
      { timeout: 4_000 },
    )).toBeVisible();
    expect(await screen.findByText("Retained conversation")).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();
    expect(screen.getByRole("button", { name: /^Saved example chat ·/ }).closest("li"))
      .toHaveAttribute("data-current", "true");
    expect(transport.getAgentPersistedEvents).toHaveBeenCalledWith(
      projectId,
      SESSION,
      0,
      expect.any(AbortSignal),
    );
  });

  it("opens setup automatically only after a durable catalog is confirmed empty", async () => {
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [] })),
      createAgentProject: vi.fn(),
      updateAgentProject: vi.fn(),
      deleteAgentProject: vi.fn(),
      listAgentCatalogSessions: vi.fn(),
      updateAgentCatalogSession: vi.fn(),
      deleteAgentCatalogSession: vi.fn(),
    };

    render(<AgentPage transport={transport} />);

    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();
    expect(await screen.findByRole("dialog", { name: "New session" })).toBeVisible();
    expect(screen.getByLabelText("Workspace folder")).toBeVisible();
  });

  it.each([false, true])("opens a verified turn file in the current workspace (dedicated window: %s)", async (windowMode) => {
    const summary = exampleAgentTurn();
    const session = view({ turns: 1, last_seq: 2 });
    const transport = {
      ...sessionTransport(session),
      getAgentSession: vi.fn(async () => session),
      getAgentEvents: vi.fn(async (): Promise<AgentEvents> => ({ contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: SESSION, closing: false, stopping: false, running: false, pending_approval_id: null, first_seq: 1, last_seq: 2,
        events: [event(1, "assistant", { text: "Example response" }), event(2, "done", { turn_id: summary.turn_id, turn_summary: summary })] })),
      getAgentChangeSet: vi.fn(async () => ({
        contract_version: "agent-change-set.v1" as const,
        session_id: SESSION,
        scope: "reviewed_paths_only" as const,
        coverage: "complete" as const,
        settled: true,
        reviewed_writes: 1,
        verified_writes: 1,
        unverified_writes: 0,
        agent_writes: 1,
        manual_writes: 0,
        reviewed_noops: 0,
        command_attempts: 0,
        omitted_write_receipts: 0,
        tracking_failed: false,
        files: [{ path: "example.txt", net_effect: "modified" as const, verification: "verified" as const, reason: null, reviewed_writes: 1, agent_writes: 1, manual_writes: 0, current_byte_size: 30, diff_available: true }],
      })),
      getAgentChangeDiff: vi.fn(async () => ({
        contract_version: "agent-change-set.v1" as const,
        session_id: SESSION,
        summary: { path: "example.txt", net_effect: "modified" as const, verification: "verified" as const, reason: null, reviewed_writes: 1, agent_writes: 1, manual_writes: 0, current_byte_size: 30, diff_available: true },
        diff_state: "available" as const,
        diff: "--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+Current fictional file content",
        added_lines: 1,
        removed_lines: 1,
      })),
      getAgentWorkspaceFile: vi.fn(async (_id: string, path: string) => ({ contract_version: "local-agent-workspace.v1" as const, session_id: SESSION, path,
        content: "Current fictional file content\n", revision: "f".repeat(64), byte_size: 30, line_ending: "lf" as const, editable: true as const })),
    };
    await act(async () => { render(<AgentPage transport={transport} sessionId={SESSION} windowMode={windowMode} />); });
    fireEvent.click(screen.getByRole("button", { name: "Files & review" }));
    fireEvent.click(screen.getByRole("tab", { name: "Changes" }));
    expect(await screen.findByText("Complete reviewed-path coverage")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review net diff" }));
    expect(await screen.findByRole("region", { name: "Net diff for example.txt" })).toHaveTextContent("Current fictional file content");
    expect(await screen.findByLabelText("Session activity and write receipts")).toHaveTextContent("1 reviewed path");
    fireEvent.click(await screen.findByLabelText("Turn 1 details"));
    expect(screen.getByText(/not verification that the task succeeded/u)).toBeVisible();
    if (windowMode) expect(screen.getByLabelText("Workspace file editor")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open example.txt in workspace" }));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveValue("Current fictional file content\n"));
    expect(transport.getAgentWorkspaceFile).toHaveBeenCalledWith(SESSION, "example.txt", expect.any(AbortSignal));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveFocus());
    if (windowMode) {
      fireEvent.click(screen.getByRole("button", { name: "Hide workspace" }));
      expect(screen.queryByLabelText("Workspace file editor")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Message to the agent")).toHaveFocus();
    }
  });

  it("connects a current document artifact to reveal-in-files and exact net-diff review", async () => {
    const projectId = "1".repeat(32);
    const artifactId = "7".repeat(32);
    const versionId = "8".repeat(32);
    const session = view({
      settings: {
        ...view().settings,
        project_id: projectId,
        retention_policy: "local_history",
      },
    });
    const version = {
      contract_version: "agent-artifact.v3" as const,
      version_id: versionId,
      artifact_id: artifactId,
      version_number: 1,
      created_at: "2040-01-01T10:00:00Z",
      path: "docs/synthetic-review.docx",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" as const,
      preview_kind: "document" as const,
      provenance: "reviewed_write" as const,
      sha256: "9".repeat(64),
      byte_size: 512,
      source_turn_id: "6".repeat(32),
      source_event_seq: 4,
    };
    const artifact = {
      contract_version: "agent-artifact.v3" as const,
      artifact_id: artifactId,
      project_id: projectId,
      session_id: SESSION,
      title: "synthetic-review.docx",
      kind: "document" as const,
      path: version.path,
      created_at: version.created_at,
      updated_at: version.created_at,
      revision: 1,
      version_count: 1,
      availability: "available" as const,
      lifecycle_state: "active" as const,
      archived_at: null,
      removed_at: null,
      latest_version: version,
    };
    const changed = {
      path: version.path,
      net_effect: "created" as const,
      verification: "verified" as const,
      reason: null,
      reviewed_writes: 1,
      agent_writes: 1,
      manual_writes: 0,
      current_byte_size: 512,
      diff_available: true,
    };
    const transport = {
      ...sessionTransport(session),
      listAgentArtifacts: vi.fn(async () => ({
        contract_version: "agent-artifact.v3" as const,
        project_id: projectId,
        session_id: SESSION,
        view: "active" as const,
        counts: { active: 1, archived: 0, removed: 0, total: 1 },
        artifacts: [artifact],
      })),
      getAgentArtifact: vi.fn(async () => ({ ...artifact, versions: [version] })),
      updateAgentArtifact: vi.fn(async () => artifact),
      removeAgentArtifact: vi.fn(async () => artifact),
      getAgentArtifactDocumentPreview: vi.fn(async () => ({
        contract_version: "agent-document-preview.v1" as const,
        project_id: projectId,
        session_id: SESSION,
        artifact_id: artifactId,
        version_id: versionId,
        source_sha256: version.sha256,
        source_byte_size: version.byte_size,
        format: "docx" as const,
        sections: [{
          index: 1,
          kind: "document" as const,
          title: "Document",
          paragraphs: ["Synthetic reviewed document"],
          rows: [],
          truncated: false,
        }],
        omitted_features: [],
        truncated: false,
      })),
      getAgentArtifactContent: vi.fn(),
      getAgentChangeSet: vi.fn(async () => ({
        contract_version: "agent-change-set.v1" as const,
        session_id: SESSION,
        scope: "reviewed_paths_only" as const,
        coverage: "complete" as const,
        settled: true,
        reviewed_writes: 1,
        verified_writes: 1,
        unverified_writes: 0,
        agent_writes: 1,
        manual_writes: 0,
        reviewed_noops: 0,
        command_attempts: 0,
        omitted_write_receipts: 0,
        tracking_failed: false,
        files: [changed],
      })),
      getAgentChangeDiff: vi.fn(async () => ({
        contract_version: "agent-change-set.v1" as const,
        session_id: SESSION,
        summary: changed,
        diff_state: "available" as const,
        diff: "--- /dev/null\n+++ b/docs/synthetic-review.docx\n+binary document created",
        added_lines: 1,
        removed_lines: 0,
      })),
      getAgentWorkspaceTree: vi.fn(async (sessionId: string, path: string) => ({
        contract_version: "local-agent-workspace.v1" as const,
        session_id: sessionId,
        path,
        entries: path === "docs" ? [{
          path: version.path,
          name: "synthetic-review.docx",
          kind: "file" as const,
          byte_size: 512,
          editable_candidate: false,
        }] : [],
        complete: true,
      })),
    };

    await act(async () => { render(<AgentPage transport={transport} />); });
    await waitFor(() => expect(transport.listAgentArtifacts).toHaveBeenCalledWith(
      projectId,
      SESSION,
      "active",
      expect.any(AbortSignal),
    ));
    fireEvent.click(await screen.findByRole(
      "button",
      { name: "Preview synthetic-review.docx" },
      { timeout: 4_000 },
    ));
    expect(await screen.findByRole(
      "region",
      { name: "Word document preview of synthetic-review.docx v1" },
      { timeout: 4_000 },
    )).toHaveTextContent("Synthetic reviewed document");
    fireEvent.click(screen.getByRole("button", { name: "Reveal in files" }));
    const revealed = await screen.findByRole("button", { name: /^synthetic-review\.docx —/u });
    expect(revealed.closest("li")).toHaveAttribute("data-revealed", "true");
    expect(transport.getAgentWorkspaceFile).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-review.docx" }));
    await screen.findByRole(
      "region",
      { name: "Word document preview of synthetic-review.docx v1" },
      { timeout: 4_000 },
    );
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(await screen.findByRole("region", { name: "Net diff for docs/synthetic-review.docx" }))
      .toHaveTextContent("binary document created");
    expect(transport.getAgentChangeDiff).toHaveBeenCalledWith(
      SESSION,
      version.path,
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("button", { name: "Open artifact" }));
    expect(await screen.findByRole(
      "region",
      { name: "Word document preview of synthetic-review.docx v1" },
      { timeout: 4_000 },
    )).toHaveTextContent("Synthetic reviewed document");
    expect(transport.getAgentArtifact).toHaveBeenLastCalledWith(
      projectId,
      SESSION,
      artifactId,
      expect.any(AbortSignal),
    );
  }, 15_000);

  it("keeps truthful output feedback visible after a completed turn without a reviewed write", async () => {
    const projectId = "1".repeat(32);
    const session = view({
      turns: 1,
      settings: {
        ...view().settings,
        project_id: projectId,
        retention_policy: "local_history",
      },
    });
    const transport = {
      ...sessionTransport(session),
      listAgentArtifacts: vi.fn(async () => ({
        contract_version: "agent-artifact.v3" as const,
        project_id: projectId,
        session_id: SESSION,
        view: "active" as const,
        counts: { active: 0, archived: 0, removed: 0, total: 0 },
        artifacts: [],
      })),
      getAgentArtifact: vi.fn(),
      getAgentArtifactContent: vi.fn(),
      updateAgentArtifact: vi.fn(),
      removeAgentArtifact: vi.fn(),
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/No verified workspace output is recorded/u)).toBeVisible();
    expect(screen.getByText(/A model statement alone is not a created file/u)).toBeVisible();
    expect(transport.listAgentArtifacts).toHaveBeenCalledWith(projectId, SESSION, "active", expect.any(AbortSignal));
    expect(screen.queryByRole("button", { name: /Preview/u })).not.toBeInTheDocument();
  });

  it("loads artifact lifecycle views inside the exact project and chat scope", async () => {
    const projectId = "1".repeat(32);
    const artifactId = "7".repeat(32);
    const version = {
      contract_version: "agent-artifact.v3" as const,
      version_id: "8".repeat(32),
      artifact_id: artifactId,
      version_number: 1,
      created_at: "2040-01-01T10:00:00Z",
      path: "docs/archived.md",
      media_type: "text/markdown; charset=utf-8",
      preview_kind: "text" as const,
      provenance: "verified_output" as const,
      sha256: "9".repeat(64),
      byte_size: 32,
      source_turn_id: null,
      source_event_seq: null,
    };
    const archived = {
      contract_version: "agent-artifact.v3" as const,
      artifact_id: artifactId,
      project_id: projectId,
      session_id: SESSION,
      title: "Archived review",
      kind: "markdown" as const,
      path: version.path,
      created_at: version.created_at,
      updated_at: "2040-01-01T10:01:00Z",
      revision: 2,
      version_count: 1,
      availability: "unchecked" as const,
      lifecycle_state: "archived" as const,
      archived_at: "2040-01-01T10:01:00Z",
      removed_at: null,
      latest_version: version,
    };
    const session = view({
      turns: 1,
      settings: {
        ...view().settings,
        project_id: projectId,
        retention_policy: "local_history",
      },
    });
    const listAgentArtifacts = vi.fn(async (
      _projectId: string,
      _sessionId: string,
      lifecycleView: "active" | "archived" | "removed" | "all" = "active",
    ) => ({
      contract_version: "agent-artifact.v3" as const,
      project_id: projectId,
      session_id: SESSION,
      view: lifecycleView,
      counts: { active: 0, archived: 1, removed: 0, total: 1 },
      artifacts: lifecycleView === "archived" ? [archived] : [],
    }));
    const transport = {
      ...sessionTransport(session),
      listAgentArtifacts,
      getAgentArtifact: vi.fn(async () => ({ ...archived, versions: [version] })),
      getAgentArtifactContent: vi.fn(),
      updateAgentArtifact: vi.fn(async () => archived),
      removeAgentArtifact: vi.fn(async () => archived),
    };

    render(<AgentPage transport={transport} />);
    const archivedView = await screen.findByRole("tab", { name: "Archived 1" });
    fireEvent.click(archivedView);

    expect(await screen.findByText("Archived review")).toBeVisible();
    expect(listAgentArtifacts).toHaveBeenLastCalledWith(
      projectId,
      SESSION,
      "archived",
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: "Manage Archived review" })).toBeEnabled();
  });

  it("loads an exact snapshot-bound artifact continuation while keeping rendering bounded", async () => {
    const projectId = "1".repeat(32);
    const records = Array.from({ length: 105 }, (_, index) => (
      artifactFixture(index, projectId, SESSION)
    ));
    const session = view({
      settings: {
        ...view().settings,
        project_id: projectId,
        retention_policy: "local_history",
      },
    });
    const pageAgentArtifacts = vi.fn(async (
      _projectId: string,
      _sessionId: string,
      query: AgentArtifactPageQuery,
      _signal?: AbortSignal,
    ) => query.offset === 0
      ? artifactPageFixture(records.slice(0, 100), 105, projectId, SESSION)
      : artifactPageFixture(records.slice(100), 105, projectId, SESSION, 100));
    const transport = {
      ...sessionTransport(session),
      ...artifactViewerMethods(),
      pageAgentArtifacts,
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByText("100 of 105 active artifacts loaded")).toBeVisible();
    expect(document.querySelectorAll(".agent-artifacts__card")).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Load more artifacts" }));
    expect(await screen.findByText("105 of 105 active artifacts loaded")).toBeVisible();
    expect(pageAgentArtifacts).toHaveBeenLastCalledWith(
      projectId,
      SESSION,
      {
        view: "active",
        limit: 100,
        offset: 100,
        snapshot: "a".repeat(64),
      },
      expect.any(AbortSignal),
    );
    expect(document.querySelectorAll(".agent-artifacts__card")).toHaveLength(50);
  });

  it.each(["duplicate", "snapshot conflict"] as const)(
    "preserves the loaded artifact prefix after a %s continuation",
    async (failure) => {
      const projectId = "1".repeat(32);
      const records = Array.from({ length: 100 }, (_, index) => (
        artifactFixture(index, projectId, SESSION)
      ));
      const session = view({
        settings: {
          ...view().settings,
          project_id: projectId,
          retention_policy: "local_history",
        },
      });
      const pageAgentArtifacts = vi.fn()
        .mockResolvedValueOnce(artifactPageFixture(records, 101, projectId, SESSION));
      if (failure === "duplicate") {
        pageAgentArtifacts.mockResolvedValueOnce(
          artifactPageFixture([records[0]], 101, projectId, SESSION, 100),
        );
      } else {
        pageAgentArtifacts.mockRejectedValueOnce(new TransportError(
          "Synthetic snapshot conflict",
          409,
          "agent_artifact_page_snapshot_conflict",
        ));
      }
      const transport = {
        ...sessionTransport(session),
        ...artifactViewerMethods(),
        pageAgentArtifacts,
      };

      render(<AgentPage transport={transport} />);
      await screen.findByText("100 of 101 active artifacts loaded");
      fireEvent.click(screen.getByRole("button", { name: "Load more artifacts" }));

      expect(await screen.findByText(
        failure === "duplicate"
          ? "A repeated artifact page was refused. Reload from the first page."
          : "Artifacts changed while another page was loading. Reload from the first page.",
      )).toHaveAttribute("role", "alert");
      expect(screen.getByText("100 of 101 active artifacts loaded")).toBeVisible();
      expect(screen.getByText("Synthetic artifact 000")).toBeVisible();
      expect(screen.getByRole("button", { name: "Reload artifacts" })).toBeVisible();
    },
  );

  it("ignores an artifact page that resolves after the lifecycle scope is replaced", async () => {
    const projectId = "1".repeat(32);
    const active = artifactFixture(0, projectId, SESSION);
    const archived = artifactFixture(1, projectId, SESSION, "archived");
    const pending = deferred<AgentArtifactPage>();
    const session = view({
      settings: {
        ...view().settings,
        project_id: projectId,
        retention_policy: "local_history",
      },
    });
    const pageAgentArtifacts = vi.fn()
      .mockImplementationOnce((
        _projectId: string,
        _sessionId: string,
        _query: AgentArtifactPageQuery,
        _signal?: AbortSignal,
      ) => pending.promise)
      .mockResolvedValueOnce(artifactPageFixture(
        [archived],
        1,
        projectId,
        SESSION,
        0,
        "archived",
      ));
    const transport = {
      ...sessionTransport(session),
      ...artifactViewerMethods(),
      pageAgentArtifacts,
    };

    render(<AgentPage transport={transport} />);
    await waitFor(() => expect(pageAgentArtifacts).toHaveBeenCalledTimes(1));
    const firstSignal = pageAgentArtifacts.mock.calls[0][3];
    fireEvent.click(await screen.findByRole("tab", { name: /^Archived/u }));

    expect(await screen.findByText("Synthetic artifact 001")).toBeVisible();
    expect(firstSignal?.aborted).toBe(true);
    pending.resolve(artifactPageFixture([active], 1, projectId, SESSION));
    await Promise.resolve();
    expect(screen.queryByText("Synthetic artifact 000")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic artifact 001")).toBeVisible();
  });

  it("aborts a delayed artifact continuation and refuses its late records after lifecycle replacement", async () => {
    const projectId = "1".repeat(32);
    const active = Array.from({ length: 100 }, (_, index) => (
      artifactFixture(index, projectId, SESSION)
    ));
    const lateActive = artifactFixture(500, projectId, SESSION);
    const archived = artifactFixture(501, projectId, SESSION, "archived");
    const delayed = deferred<AgentArtifactPage>();
    const session = view({
      settings: {
        ...view().settings,
        project_id: projectId,
        retention_policy: "local_history",
      },
    });
    const pageAgentArtifacts = vi.fn((
      _projectId: string,
      _sessionId: string,
      query: AgentArtifactPageQuery,
      _signal?: AbortSignal,
    ) => {
      if (query.view === "active" && query.offset === 100) return delayed.promise;
      return Promise.resolve(query.view === "archived"
        ? artifactPageFixture([archived], 1, projectId, SESSION, 0, "archived")
        : artifactPageFixture(active, 101, projectId, SESSION));
    });
    const transport = {
      ...sessionTransport(session),
      ...artifactViewerMethods(),
      pageAgentArtifacts,
    };

    render(<AgentPage transport={transport} />);
    await screen.findByText("100 of 101 active artifacts loaded");
    fireEvent.click(screen.getByRole("button", { name: "Load more artifacts" }));
    await waitFor(() => expect(pageAgentArtifacts).toHaveBeenCalledTimes(2));
    const delayedSignal = pageAgentArtifacts.mock.calls[1][3];

    fireEvent.click(screen.getByRole("tab", { name: /^Archived/u }));
    expect(await screen.findByText("Synthetic artifact 501")).toBeVisible();
    expect(delayedSignal?.aborted).toBe(true);
    delayed.resolve(artifactPageFixture([lateActive], 101, projectId, SESSION, 100));
    await delayed.promise;
    await Promise.resolve();
    expect(screen.queryByText("Synthetic artifact 500")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic artifact 501")).toBeVisible();
  });

  it("shows absent turn receipts as unknown and separates denied tools from failed tools", async () => {
    const transport = { ...sessionTransport(view({ turns: 1 })),
      getAgentEvents: vi.fn(async (): Promise<AgentEvents> => ({ contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: SESSION, closing: false, stopping: false, running: false, pending_approval_id: null, first_seq: 1, last_seq: 3,
        events: [event(1, "tool_result", { tool: "write_file", ok: false, tool_state: "not_approved" }), event(2, "tool_result", { tool: "read_file", ok: null }), event(3, "done")] })) };
    await act(async () => { render(<AgentPage transport={transport} />); });
    expect(screen.getByText("Not approved")).toBeVisible();
    expect(screen.getByText("Outcome unknown")).toBeVisible();
    expect(screen.getByText("Turn details were not reported for this run.")).toBeVisible();
    expect(screen.queryByLabelText("Turn telemetry")).not.toBeInTheDocument();
  });

  it("marks session effects partial when earlier in-memory events expired", async () => {
    const summary = exampleAgentTurn({ turn_id: "9".repeat(32), turn_number: 3 });
    const session = view({ turns: 3, last_seq: 10 });
    const transport = {
      ...sessionTransport(session),
      getAgentEvents: vi.fn(async (): Promise<AgentEvents> => ({
        contract_version: "local-agent.v9", cleanup_unconfirmed: false,
        session_id: SESSION, closing: false, stopping: false, running: false,
        pending_approval_id: null, first_seq: 10, last_seq: 10,
        events: [event(10, "done", { turn_id: summary.turn_id, turn_summary: summary })],
      })),
    };
    await act(async () => { render(<AgentPage transport={transport} />); });
    const effects = await screen.findByLabelText("Session activity and write receipts");
    expect(effects).toHaveTextContent("Partial retained history");
    fireEvent.click(effects);
    expect(screen.getByText(/Earlier in-memory events expired, so the receipts below are only the retained suffix/u)).toBeVisible();
    expect(screen.queryAllByText("Complete retained session history")).toHaveLength(0);
  });

  it.each(["session", "events"] as const)("blocks new messages in a closing session reported by %s", async (source) => {
    const current = { ...view(), closing: source === "session" };
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, session_id: SESSION, events: [],
        running: false, closing: source === "events", stopping: false, pending_approval_id: null, last_seq: 0, first_seq: 0,
      })),
    };
    await act(async () => { render(<AgentPage transport={transport} />); });
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Session closing");
    expect(screen.getByRole("button", { name: "Retry closing session" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Message composer" }));
    expect(transport.sendAgentMessage).not.toHaveBeenCalled();
  });

  it("does not start a stopped model for a closing session", async () => {
    const transport = {
      ...sessionTransport(view({ closing: true })),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(async () => modelStatus("running")),
    };
    await act(async () => { render(<AgentPage transport={transport} />); });
    const start = screen.getByRole("button", { name: "Start session model" });
    expect(start).toBeDisabled();
    fireEvent.click(start);
    expect(transport.activateLocalModel).not.toHaveBeenCalled();
  });

  it("keeps an unsent draft when the server reports that its session is closing", async () => {
    const transport = sessionTransport(view());
    transport.sendAgentMessage.mockRejectedValue(new TransportError("synthetic closing session", 409, "session_closing"));
    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "An unsent fictional request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("button", { name: "Retry closing session" });
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("An unsent fictional request");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("cannot reopen a closing dedicated chat with a stale event snapshot", async () => {
    let accept: ((page: AgentEvents) => void) | undefined;
    const transport = {
      ...sessionTransport(view()),
      streamAgentEvents: vi.fn(async (_id: string, _after: number, onPage: (page: AgentEvents) => void, signal?: AbortSignal) => {
        accept = onPage;
        await new Promise<void>((resolve) => { signal?.addEventListener("abort", () => resolve(), { once: true }); });
      }),
    };
    await act(async () => { render(<AgentPage transport={transport} sessionId={SESSION} windowMode />); });
    expect(accept).toBeDefined();
    const page: AgentEvents = { contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: SESSION, closing: true, stopping: false,
      running: false, pending_approval_id: null, events: [], first_seq: 0, last_seq: 0 };
    act(() => accept!(page));
    act(() => accept!({ ...page, closing: false, stopping: false }));
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Session closing");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it.each([false, true])("keeps command cleanup quarantine and the draft in window mode %s", async (windowMode) => {
    let accept: ((page: AgentEvents) => void) | undefined;
    const transport = {
      ...sessionTransport(view()),
      getAgentSession: vi.fn(async () => view()),
      deactivateLocalModel: vi.fn(),
      streamAgentEvents: vi.fn(async (_id: string, _after: number, onPage: (page: AgentEvents) => void, signal?: AbortSignal) => {
        accept = onPage;
        await new Promise<void>((resolve) => { signal?.addEventListener("abort", () => resolve(), { once: true }); });
      }),
    };
    await act(async () => { render(<AgentPage transport={transport} sessionId={windowMode ? SESSION : undefined} windowMode={windowMode} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Keep this fictional draft" } });
    const paused: AgentEvents = { contract_version: "local-agent.v9", cleanup_unconfirmed: true,
      session_id: SESSION, closing: true, stopping: false, running: false, pending_approval_id: null,
      events: [event(1, "error", { text: "Example command cleanup is unconfirmed." })], first_seq: 1, last_seq: 1 };
    act(() => accept!(paused));
    act(() => accept!({ ...paused, cleanup_unconfirmed: false, closing: false, events: [], first_seq: 0, last_seq: 0 }));
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Command cleanup unconfirmed");
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("select and copy your draft");
    expect(screen.getAllByText(/Copy your draft before restarting; it is not saved/)).toHaveLength(1);
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Keep this fictional draft");
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    expect(screen.getByLabelText("Message to the agent")).toHaveAttribute("readonly");
    screen.getByLabelText("Message to the agent").focus();
    expect(screen.getByLabelText("Message to the agent")).toHaveFocus();
    fireEvent.keyDown(screen.getByLabelText("Message to the agent"), { key: "Enter", ctrlKey: true });
    expect(transport.sendAgentMessage).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Retry closing session" })).toBeNull();
    expect(screen.queryByText(/ready for messages/i)).toBeNull();
    const newChat = screen.getByRole("button", { name: "New chat" });
    expect(newChat).toBeEnabled();
    fireEvent.click(newChat);
    expect(screen.getByRole("button", { name: "Agent paused for cleanup" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close session project" })).toBeDisabled();
    expect(transport.deleteAgentSession).not.toHaveBeenCalled();
    expect(transport.createAgentSession).not.toHaveBeenCalled();
  });

  it("preserves an unsent draft when command cleanup rejects admission", async () => {
    const transport = sessionTransport(view());
    transport.sendAgentMessage.mockRejectedValue(new TransportError("example cleanup", 409, "command_cleanup_unconfirmed"));
    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Do not lose this example request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Command cleanup unconfirmed"));
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Do not lose this example request");
    expect(screen.getByLabelText("Message to the agent")).toHaveAttribute("readonly");
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "A stale draft update" } });
    fireEvent.keyDown(screen.getByLabelText("Message to the agent"), { key: "Enter", ctrlKey: true });
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Do not lose this example request");
    expect(transport.sendAgentMessage).toHaveBeenCalledTimes(1);
  });

  it("cannot reopen a closing chat with a late stop acknowledgement", async () => {
    let accept: ((page: AgentEvents) => void) | undefined;
    let finishStop: ((view: AgentSessionView) => void) | undefined;
    const transport = {
      ...sessionTransport(view({ running: true })),
      stopAgentSession: vi.fn(() => new Promise<AgentSessionView>((resolve) => { finishStop = resolve; })),
      streamAgentEvents: vi.fn(async (_id: string, _after: number, onPage: (page: AgentEvents) => void, signal?: AbortSignal) => {
        accept = onPage;
        await new Promise<void>((resolve) => { signal?.addEventListener("abort", () => resolve(), { once: true }); });
      }),
    };
    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
    act(() => accept!({ contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: SESSION, closing: true, stopping: true,
      running: true, pending_approval_id: null, events: [], first_seq: 0, last_seq: 0 }));
    await act(async () => finishStop!(view()));
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Session closing");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("does not apply another session's close timeout to the active chat", async () => {
    const other = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Other example" } });
    const transport = sessionTransport(view(), other);
    transport.deleteAgentSession.mockRejectedValue(new TransportError("synthetic close timeout", 409, "session_stop_timeout"));
    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Active example draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Close session Other example" }));
    await acceptCloseChat();
    await waitFor(() => expect(transport.deleteAgentSession).toHaveBeenCalledWith(other.session_id));
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Active example draft");
    expect(screen.queryByRole("button", { name: "Retry closing session" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Other example.*closing/ }));
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retry closing session" })).toBeVisible();
  });

  it("clears a closing session that another window has already removed", async () => {
    const transport = sessionTransport(view({ closing: true }));
    transport.deleteAgentSession.mockRejectedValue(new TransportError("synthetic missing session", 404));
    await act(async () => { render(<AgentPage transport={transport} />); });
    transport.listAgentSessions.mockResolvedValue([]);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Retry closing session" })));
    expect(screen.queryByLabelText("Message to the agent")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry closing session" })).toBeNull();
    expect(transport.deleteAgentSession).toHaveBeenCalledOnce();
  });

  it("does not carry a completed close marker into a resumed durable chat", async () => {
    const projectId = "e".repeat(32);
    const settings = {
      ...view().settings,
      project_id: projectId,
      title: "Resume fixture",
      model_alias: null,
      retention_policy: "local_history" as const,
    };
    const live = view({ settings, model_alias: null });
    const recovered = view({
      settings,
      model_alias: null,
      recovered: true,
      authority_revalidated: false,
      recovery_state: "recovered",
    });
    const project = {
      contract_version: "agent-catalog.v2" as const,
      project_id: projectId,
      name: "Resume project",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      revision: 1,
      pinned: false,
      archived_at: null,
      session_count: 1,
      is_default: false,
    };
    const saved: AgentCatalogSession = {
      contract_version: "agent-catalog.v2",
      session_id: SESSION,
      project_id: projectId,
      title: "Resume fixture",
      workspace: settings.workspace,
      model_alias: null,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      last_opened_at: "2040-01-01T10:00:00Z",
      revision: 2,
      pinned: false,
      archived_at: null,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 0,
      last_event_seq: 0,
      turn_count: 0,
      conversation_available: true,
      lineage: null,
    };
    const retainedPage: AgentEvents = {
      contract_version: "local-agent.v9",
      session_id: SESSION,
      events: [],
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      first_seq: 0,
      last_seq: 0,
    };
    let open = [live];
    const transport = {
      ...sessionTransport(live),
      listAgentSessions: vi.fn(async () => open),
      deleteAgentSession: vi.fn(async () => { open = []; }),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [project] })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, sessions: [saved] })),
      getAgentCatalogSession: vi.fn(async () => saved),
      updateAgentCatalogSession: vi.fn(async () => saved),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      getAgentPersistedEvents: vi.fn(async () => retainedPage),
      resumeAgentSession: vi.fn(async () => { open = [recovered]; return recovered; }),
    };
    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByLabelText("Chat actions for Resume fixture"));
    const actions = screen.getByRole("dialog", { name: "Chat actions for Resume fixture" });
    fireEvent.click(within(actions).getByRole("button", { name: "Close live chat" }));
    await acceptCloseChat();
    await waitFor(() => expect(transport.deleteAgentSession).toHaveBeenCalledWith(SESSION));

    fireEvent.click(await screen.findByRole("button", { name: /^Resume fixture · 0 turns · saved locally/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Resume chat" }));
    await waitFor(() => expect(transport.resumeAgentSession).toHaveBeenCalledOnce());
    expect(await screen.findByLabelText("Agent activity status")).not.toHaveTextContent("Session closing");
    expect(screen.queryByRole("button", { name: "Retry closing session" })).toBeNull();
  });

  it("retains the draft after a close timeout and lets the exact session close be retried", async () => {
    const transport = sessionTransport(view());
    transport.deleteAgentSession.mockRejectedValueOnce(new TransportError("synthetic close timeout", 409, "session_stop_timeout"));
    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "An unsent fictional request" } });
    fireEvent.click(screen.getByRole("button", { name: "Close session project" }));
    await acceptCloseChat();
    const retry = await screen.findByRole("button", { name: "Retry closing session" });
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("An unsent fictional request");
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Session closing");
    transport.listAgentSessions.mockResolvedValue([]);
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Close session project" })).toBeNull());
    expect(transport.deleteAgentSession).toHaveBeenCalledTimes(2);
    expect(transport.deleteAgentSession).toHaveBeenNthCalledWith(2, SESSION);
    expect(transport.sendAgentMessage).not.toHaveBeenCalled();
  });

  it.each(["complete", "stopped", "failed"] as const)("keeps empty %s responses truthful when a tool follows", async (streamStatus) => {
    const current = view({ turns: 1, last_seq: 4 });
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION,
        events: [
          event(1, "assistant", { text: "", stream_id: "c".repeat(32), stream_status: streamStatus }),
          event(2, "tool_call", { tool: "read_file", arguments: { path: "example.txt" }, call_id: "example-call" }),
          event(3, "tool_result", { tool: "read_file", call_id: "example-call", ok: true, text: "EXAMPLE_OK" }),
          event(4, "assistant", { text: "EXAMPLE_OK", stream_id: "d".repeat(32), stream_status: "complete" as const }),
        ],
        running: false, pending_approval_id: null, last_seq: 4, first_seq: 1,
      })),
    };
    render(<AgentPage transport={transport} />);
    expect(await screen.findByLabelText("Agent action: Read file")).toBeVisible();
    if (streamStatus === "complete") {
      expect(screen.queryByText("No assistant text was completed.")).toBeNull();
      expect(screen.getAllByText("Complete", { exact: true })).toHaveLength(1);
    } else {
      expect(screen.getByText("No assistant text was completed.")).toBeVisible();
      expect(screen.getByText(streamStatus === "stopped" ? "Stopped" : "Interrupted", { exact: true })).toBeVisible();
    }
  });

  it("removes an acknowledged closed session even when refreshing the list fails", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Session B" } });
    const transport = sessionTransport(first, second);
    render(<AgentPage transport={transport} />);
    await screen.findByRole("heading", { name: "Session A" });
    transport.listAgentSessions.mockRejectedValueOnce(new Error("synthetic read failure"));
    fireEvent.click(screen.getByRole("button", { name: "Close session Session B" }));
    await acceptCloseChat();
    await waitFor(() => expect(transport.deleteAgentSession).toHaveBeenCalledWith(second.session_id));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Close session Session B" })).toBeNull());
    expect(screen.getByRole("heading", { name: "Session A" })).toBeVisible();
    expect(transport.deleteAgentSession).toHaveBeenCalledOnce();
  });

  it.each([false, true])("keeps model-stop feedback on its owning session (late=%s)", async (late) => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Session B" } });
    let rejectStop!: (error: Error) => void;
    const transport = {
      ...sessionTransport(first, second),
      deactivateLocalModel: vi.fn(() => new Promise<LocalModelStatus>((_resolve, reject) => { rejectStop = reject; })),
    };
    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop model" }));
    await waitFor(() => expect(transport.deactivateLocalModel).toHaveBeenCalledOnce());
    if (!late) {
      await act(async () => rejectStop(new Error("synthetic stop failure")));
      expect(screen.getByRole("alert")).toHaveTextContent("model could not be stopped");
    }
    fireEvent.click(screen.getByText("Session B").closest("button")!);
    if (late) await act(async () => rejectStop(new Error("synthetic stop failure")));
    await waitFor(() => expect(screen.queryByText(/model could not be stopped/)).toBeNull());
    expect(screen.getByRole("heading", { name: "Session B" })).toBeVisible();
  });

  it("clears a declined approval error when the next decision succeeds", async () => {
    let current = view({ running: true, pending_approval_id: APPROVAL });
    const transport = {
      ...sessionTransport(current),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION,
        events: current.pending_approval_id ? [event(1, "approval_required", { tool: "write_file", approval_id: APPROVAL, preview: "synthetic diff" })] : [],
        running: current.running, pending_approval_id: current.pending_approval_id, last_seq: 1, first_seq: 1,
      })),
      decideAgentApproval: vi.fn().mockRejectedValueOnce(new TransportError("synthetic decline", 403)).mockImplementation(async () => {
        current = view();
        return current;
      }),
    };
    // Complete the fixture's initial capability/session/event promises before
    // testing a decision; startup scheduling is not this regression's subject.
    await act(async () => { render(<AgentPage transport={transport} />); });
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(await screen.findByRole("alert")).toHaveTextContent("agent action remains pending");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(transport.decideAgentApproval).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText(/agent action remains pending/)).toBeNull());
  });

  it("refreshes a one-shot approval after a repeated decision is refused", async () => {
    let current = view({ running: true, pending_approval_id: APPROVAL });
    const settled = view({ running: false, pending_approval_id: null, last_seq: 2 });
    const getAgentSession = vi.fn(async () => settled);
    const transport = {
      ...sessionTransport(current),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      getAgentSession,
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: current.pending_approval_id
          ? [event(1, "approval_required", {
            tool: "write_file",
            approval_id: APPROVAL,
            preview: "synthetic diff",
          })]
          : [],
        running: current.running,
        pending_approval_id: current.pending_approval_id,
        last_seq: current.last_seq,
        first_seq: current.last_seq > 0 ? 1 : 0,
      })),
      decideAgentApproval: vi.fn(async () => {
        current = settled;
        throw new TransportError(
          "EXAMPLE_PRIVATE_APPROVAL_CANARY",
          409,
          "approval_already_settled",
        );
      }),
    };

    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already settled and cannot be changed",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("session state was refreshed");
    expect(screen.queryByText(/EXAMPLE_PRIVATE_APPROVAL_CANARY/)).toBeNull();
    await waitFor(() => expect(getAgentSession).toHaveBeenCalledWith(SESSION));
    await waitFor(() => expect(screen.queryByRole("alertdialog", { name: "Approval needed" })).toBeNull());
  });

  it("keeps independent in-memory drafts when switching between live chats", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Session B" } });
    const transport = sessionTransport(first, second);
    render(<AgentPage transport={transport} />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toBeEnabled());
    fireEvent.change(composer, { target: { value: "Synthetic draft for A" } });
    expect(screen.getByRole("button", { name: /Session A.*draft in this window/ })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /^Session B ·/ }));
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Synthetic draft for B" } });
    expect(screen.getByRole("button", { name: /Session B.*draft in this window/ })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /^Session A ·/ }));
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Synthetic draft for A");
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "" } });
    expect(screen.queryByRole("button", { name: /Session A.*draft in this window/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Session B ·/ }));
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Synthetic draft for B");
  });

  it("keeps staged attachment identities scoped to their owning chat", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Session B" } });
    const firstAttachment = { ...stagedImageAttachment(), display_name: "session-a.png" };
    const secondAttachment = {
      ...stagedImageAttachment(),
      attachment_id: "e".repeat(32),
      session_id: second.session_id,
      display_name: "session-b.png",
    };
    const transport = {
      ...sessionTransport(first, second),
      listAgentAttachments: vi.fn(async (sessionId: string) => ({
        contract_version: "agent-attachment.v2" as const,
        session_id: sessionId,
        attachments: sessionId === first.session_id ? [firstAttachment] : [secondAttachment],
      })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText("session-a.png")).toBeVisible();
    expect(screen.queryByText("session-b.png")).toBeNull();
    expect(screen.getByRole("button", { name: /Session A.*draft in this window/ })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /^Session B ·/ }));
    expect(await screen.findByText("session-b.png")).toBeVisible();
    expect(screen.queryByText("session-a.png")).toBeNull();
    expect(screen.getByRole("button", { name: /Session B.*draft in this window/ })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /^Session A ·/ }));
    expect(await screen.findByText("session-a.png")).toBeVisible();
    expect(screen.queryByText("session-b.png")).toBeNull();
  });

  it("discards a late attachment listing after the user switches chats", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Session B" } });
    const firstListing = deferred<{
      contract_version: "agent-attachment.v2";
      session_id: string;
      attachments: AgentAttachment[];
    }>();
    const secondAttachment = {
      ...stagedImageAttachment(),
      attachment_id: "e".repeat(32),
      session_id: second.session_id,
      display_name: "session-b.png",
    };
    const listAgentAttachments = vi.fn((sessionId: string) => (
      sessionId === first.session_id
        ? firstListing.promise
        : Promise.resolve({
            contract_version: "agent-attachment.v2" as const,
            session_id: sessionId,
            attachments: [secondAttachment],
          })
    ));
    const transport = {
      ...sessionTransport(first, second),
      listAgentAttachments,
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    await waitFor(() => expect(listAgentAttachments).toHaveBeenCalledWith(first.session_id, expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole("button", { name: /^Session B ·/ }));
    expect(await screen.findByText("session-b.png")).toBeVisible();
    firstListing.resolve({
      contract_version: "agent-attachment.v2",
      session_id: first.session_id,
      attachments: [{ ...stagedImageAttachment(), display_name: "late-session-a.png" }],
    });
    await act(async () => { await Promise.resolve(); });

    expect(screen.queryByText("late-session-a.png")).toBeNull();
    expect(screen.getByText("session-b.png")).toBeVisible();
  });

  it("does not switch back or erase another chat's draft when a send completes", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({ session_id: "d".repeat(32), settings: { ...view().settings, title: "Session B" } });
    let resolveSend!: (value: AgentSessionView) => void;
    const transport = sessionTransport(first, second);
    transport.sendAgentMessage.mockImplementation(() => new Promise<AgentSessionView>((resolve) => { resolveSend = resolve; }));
    render(<AgentPage transport={transport} />);
    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toBeEnabled());
    fireEvent.change(composer, { target: { value: "Synthetic first request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.click(screen.getByText("Session B").closest("button")!);
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Synthetic second draft" } });
    await act(async () => resolveSend({ ...first, running: true }));
    expect(screen.getByRole("heading", { name: "Session B" })).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Synthetic second draft");
    fireEvent.click(screen.getByRole("button", { name: /^Session A ·/ }));
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /^Session B ·/ }));
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Synthetic second draft");
  });

  it("preserves a next draft typed while the previous message is being admitted", async () => {
    const current = view({ settings: { ...view().settings, title: "Session A" } });
    let resolveSend!: (value: AgentSessionView) => void;
    const transport = sessionTransport(current);
    transport.sendAgentMessage.mockImplementation(() => new Promise<AgentSessionView>((resolve) => { resolveSend = resolve; }));
    render(<AgentPage transport={transport} />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toBeEnabled());
    fireEvent.change(composer, { target: { value: "Synthetic request being sent" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.change(composer, { target: { value: "Synthetic next draft" } });
    await act(async () => resolveSend({ ...current, running: true }));

    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Synthetic next draft");
    expect(screen.getByRole("button", { name: /Session A.*draft in this window/ })).toBeVisible();
  });

  it("coalesces streamed deltas into one live bubble and replaces it with the terminal reply", async () => {
    const streamId = "c".repeat(32);
    let finishStream: (() => void) | undefined;
    const current = view({ running: true, turns: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(async () => current),
      streamAgentEvents: vi.fn(async (_id: string, _after: number, onPage: (page: AgentEvents) => void) => {
        onPage({
          contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
          session_id: SESSION,
          events: [
            event(1, "user", { text: "Say hello" }),
            event(2, "assistant_delta", { text: "Hel", stream_id: streamId, stream_phase: "content" }),
            event(3, "assistant_delta", { text: "lo", stream_id: streamId, stream_phase: "content" }),
          ],
          running: true,
          pending_approval_id: null,
          last_seq: 3,
          first_seq: 1,
        });
        await new Promise<void>((resolve) => { finishStream = resolve; });
        onPage({
          contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
          session_id: SESSION,
          events: [
            event(4, "assistant", { text: "Hello", stream_id: streamId, stream_status: "complete" }),
            event(5, "done"),
          ],
          running: false,
          pending_approval_id: null,
          last_seq: 5,
          first_seq: 1,
        });
      }),
    };
    render(<AgentPage transport={transport} />);
    const live = await screen.findByLabelText("Agent response streaming");
    expect(live.textContent).toContain("Hello");
    expect(screen.getByRole("form", { name: "Message composer" })).toContainElement(
      screen.getByRole("button", { name: "Stop response" }),
    );
    finishStream?.();
    await waitFor(() => expect(screen.queryByLabelText("Agent response streaming")).toBeNull());
    expect(screen.getByText("Hello")).toBeTruthy();
    expect(transport.getAgentEvents).not.toHaveBeenCalled();
  });

  it("reconnects from the exact cursor and replaces partial output with one late terminal reply", async () => {
    const streamId = "c".repeat(32);
    const current = view({ running: true, turns: 1 });
    let connection = 0;
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(async () => current),
      streamAgentEvents: vi.fn(async (_id: string, after: number, onPage: (page: AgentEvents) => void) => {
        connection += 1;
        if (connection === 1) {
          expect(after).toBe(0);
          onPage({
            contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
            session_id: SESSION,
            events: [
              event(1, "user", { text: "Say hello" }),
              event(2, "assistant_delta", { text: "Hel", stream_id: streamId, stream_phase: "content" }),
              event(3, "assistant_delta", { text: "lo", stream_id: streamId, stream_phase: "content" }),
            ],
            running: true,
            pending_approval_id: null,
            last_seq: 3,
            first_seq: 1,
          });
          throw new Error("synthetic disconnect after partial output");
        }
        expect(after).toBe(3);
        onPage({
          contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
          session_id: SESSION,
          events: [
            event(4, "assistant", { text: "Hello", stream_id: streamId, stream_status: "complete" }),
            event(5, "done"),
          ],
          running: false,
          pending_approval_id: null,
          last_seq: 5,
          first_seq: 1,
        });
      }),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByLabelText("Agent response streaming")).toHaveTextContent("Hello");
    await waitFor(() => expect(transport.streamAgentEvents).toHaveBeenCalledTimes(2), { timeout: 1_500 });
    await waitFor(() => expect(screen.queryByLabelText("Agent response streaming")).toBeNull());
    expect(screen.getAllByText("Hello")).toHaveLength(1);
    expect(transport.streamAgentEvents.mock.calls[1][1]).toBe(3);
  });

  it("bounds a large transcript and pages earlier activity without cumulative mounting", async () => {
    const activity = Array.from({ length: 205 }, (_, index) => (
      event(index + 1, "status", { text: `Synthetic activity ${index + 1}` })
    ));
    const current = view({ last_seq: activity.length, turns: 1 });
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async (): Promise<AgentEvents> => ({
        contract_version: "local-agent.v9",
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: activity,
        running: false,
        pending_approval_id: null,
        last_seq: activity.length,
        first_seq: 1,
      })),
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByText("Showing activity 6–205 of 205 events.")).toBeVisible();
    expect(screen.queryByText("Synthetic activity 1")).toBeNull();
    expect(screen.getByText("Synthetic activity 6")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Earlier 5" }));
    expect(screen.getByText("Synthetic activity 1")).toBeVisible();
    expect(screen.queryByText("Synthetic activity 6")).toBeNull();
    expect(screen.getByText("Showing activity 1–5 of 205 events.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Latest" }));
    expect(screen.getByText("Showing activity 6–205 of 205 events.")).toBeVisible();
    expect(screen.queryByText("Synthetic activity 1")).toBeNull();
  });

  it("fails closed on wrong-chat, repeated, out-of-order, and empty retained pages", async () => {
    const projectId = "f".repeat(32);
    const page = (
      sessionId: string,
      events: AgentEvent[],
      lastSeq = 3,
    ): AgentEvents => ({
      contract_version: "local-agent.v9",
      session_id: sessionId,
      events,
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: lastSeq,
      first_seq: events[0]?.seq ?? 0,
    });
    const signal = new AbortController().signal;

    await expect(readCompleteRetainedEvents(
      async () => page("e".repeat(32), [event(1, "status")], 1),
      projectId,
      SESSION,
      signal,
    )).rejects.toThrow("retained_history_session_mismatch");

    await expect(readCompleteRetainedEvents(
      async () => page(SESSION, [event(1, "status")]),
      projectId,
      SESSION,
      signal,
    )).rejects.toThrow("retained_history_cursor_invalid");

    await expect(readCompleteRetainedEvents(
      async () => page(SESSION, [event(2, "status"), event(1, "status")]),
      projectId,
      SESSION,
      signal,
    )).rejects.toThrow("retained_history_cursor_invalid");

    await expect(readCompleteRetainedEvents(
      async () => page(SESSION, [], 1),
      projectId,
      SESSION,
      signal,
    )).rejects.toThrow("retained_history_cursor_stalled");
  });

  it("refuses retained history that exceeds the 100-page reconstruction ceiling", async () => {
    const getPage = vi.fn(async (
      _projectId: string,
      _sessionId: string,
      after: number,
    ): Promise<AgentEvents> => ({
      contract_version: "local-agent.v9",
      session_id: SESSION,
      events: [event(after + 1, "status")],
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: 200,
      first_seq: 1,
    }));

    await expect(readCompleteRetainedEvents(
      getPage,
      "f".repeat(32),
      SESSION,
      new AbortController().signal,
    )).rejects.toThrow("retained_history_page_limit");
    expect(getPage).toHaveBeenCalledTimes(100);
  });

  it("pages the maximum 4,000-event retained history through one fixed mounted window", async () => {
    const projectId = "a".repeat(32);
    const activity = Array.from({ length: 4_000 }, (_, index) => (
      event(index + 1, "status", { text: `Maximum retained activity ${index + 1}` })
    ));
    const project = catalogProjectFixture(projectId, "Maximum history project", 1);
    const saved = catalogSessionFixture(SESSION, projectId, "Maximum retained chat", {
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: activity.length,
      last_event_seq: activity.length,
      turn_count: 1,
      conversation_available: true,
    });
    const getAgentPersistedEvents = vi.fn(async (
      _projectId: string,
      _sessionId: string,
      after: number,
    ): Promise<AgentEvents> => ({
      contract_version: "local-agent.v9",
      session_id: SESSION,
      events: activity.slice(after, after + 500),
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: activity.length,
      first_seq: 1,
    }));
    const transport = retainedCatalogTransport(project, [saved], {
      getAgentSession: vi.fn(async () => {
        throw new TransportError("synthetic live session cleared", 404);
      }),
      getAgentPersistedEvents,
    });

    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByText(
      "Showing activity 3,801–4,000 of 4,000 events.",
      {},
      { timeout: 5_000 },
    )).toBeVisible();
    const timeline = screen.getByRole("region", { name: "Retained agent activity" });
    expect(timeline.children.length).toBeLessThanOrEqual(201);
    expect(screen.queryByText("Maximum retained activity 3600")).toBeNull();
    expect(screen.getByText("Maximum retained activity 3801")).toBeVisible();
    expect(getAgentPersistedEvents).toHaveBeenCalledTimes(8);

    fireEvent.click(screen.getByRole("button", { name: "Earlier 200" }));
    expect(screen.getByText("Showing activity 3,601–3,800 of 4,000 events.")).toBeVisible();
    expect(screen.getByText("Maximum retained activity 3601")).toBeVisible();
    expect(screen.queryByText("Maximum retained activity 3801")).toBeNull();
    expect(timeline.children.length).toBeLessThanOrEqual(201);

    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByText("Showing activity 3,801–4,000 of 4,000 events.")).toBeVisible();
    expect(timeline.children.length).toBeLessThanOrEqual(201);
  });

  it("refuses to reconstruct retained history from pages with different immutable heads", async () => {
    const projectId = "b".repeat(32);
    const project = catalogProjectFixture(projectId, "Changed history project", 1);
    const saved = catalogSessionFixture(SESSION, projectId, "Changed retained chat", {
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 4,
      last_event_seq: 4,
      turn_count: 1,
      conversation_available: true,
    });
    const first = [
      event(1, "status", { text: "Mixed history page one" }),
      event(2, "status", { text: "Mixed history page two" }),
    ];
    const second = [
      event(3, "status", { text: "Foreign changed-head page" }),
      event(4, "status", { text: "Foreign changed-head tail" }),
    ];
    const getAgentPersistedEvents = vi.fn(async (
      _projectId: string,
      _sessionId: string,
      after: number,
    ): Promise<AgentEvents> => ({
      contract_version: "local-agent.v9",
      session_id: SESSION,
      events: after === 0 ? first : second,
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: after === 0 ? 4 : 5,
      first_seq: 1,
    }));
    const transport = retainedCatalogTransport(project, [saved], {
      getAgentSession: vi.fn(async () => {
        throw new TransportError("synthetic live session cleared", 404);
      }),
      getAgentPersistedEvents,
    });

    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The retained conversation could not be read. Nothing was reconstructed.",
    );
    expect(screen.queryByText("Mixed history page one")).toBeNull();
    expect(screen.queryByText("Foreign changed-head page")).toBeNull();
    expect(getAgentPersistedEvents).toHaveBeenCalledTimes(2);
  });

  it("offers a keyboard-reachable jump to the latest activity after the user scrolls up", async () => {
    const current = view({ last_seq: 2, turns: 1 });
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async (): Promise<AgentEvents> => ({
        contract_version: "local-agent.v9",
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: [
          event(1, "user", { text: "Synthetic earlier request" }),
          event(2, "assistant", { text: "Synthetic latest response" }),
        ],
        running: false,
        pending_approval_id: null,
        last_seq: 2,
        first_seq: 1,
      })),
    };
    render(<AgentPage transport={transport} />);

    const log = await screen.findByRole("log");
    Object.defineProperties(log, {
      clientHeight: { configurable: true, value: 300 },
      scrollHeight: { configurable: true, value: 1200 },
      scrollTop: { configurable: true, value: 120, writable: true },
    });
    fireEvent.scroll(log);

    const jump = screen.getByRole("button", { name: "Jump to latest activity" });
    expect(jump).toBeVisible();
    fireEvent.click(jump);
    expect(log.scrollTop).toBe(1200);
    expect(log).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Jump to latest activity" })).toBeNull();
  });

  it("keeps a long active stream visible when its first delta is outside the transcript window", async () => {
    const streamId = "c".repeat(32);
    const activity = Array.from({ length: 205 }, (_, index) => (
      event(index + 1, "assistant_delta", { text: "x", stream_id: streamId, stream_phase: "content" })
    ));
    const current = view({ last_seq: activity.length, running: true, turns: 1 });
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async (): Promise<AgentEvents> => ({
        contract_version: "local-agent.v9",
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: activity,
        running: true,
        pending_approval_id: null,
        last_seq: activity.length,
        first_seq: 1,
      })),
    };

    render(<AgentPage transport={transport} />);

    const live = await screen.findByLabelText("Agent response streaming");
    expect(live).toHaveTextContent("x".repeat(205));
    expect(screen.getByText("Showing activity 6–205 of 205 events.")).toBeVisible();
  });

  it("renders reasoning and tool execution as explicit coding-agent activity", async () => {
    const current = view({
      last_seq: 10,
      turns: 1,
      settings: {
        ...view().settings,
        parameters: { ...view().settings.parameters, enable_thinking: true },
      },
    });
    const activity = [
      event(1, "user", { text: "Inspect the synthetic project" }),
      event(2, "assistant", { text: "I inspected [the requested file](workspace:src/example.ts).", reasoning: "I should read the target before proposing a change." }),
      event(3, "tool_call", { tool: "read_file", arguments: { path: "src/example.ts" }, call_id: "synthetic-call" }),
      event(4, "tool_result", { tool: "read_file", call_id: "synthetic-call", ok: true, text: "synthetic result", execution_receipt: { contract_version: "agent-tool-execution.v1", elapsed_ms: 25, timing_source: "server_monotonic.v1", approval_state: "not_required", evidence_state: "read_only_observation" } }),
      event(5, "tool_call", { tool: "create_directory", arguments: { path: "src/reviewed" }, call_id: "synthetic-create-directory" }),
      event(6, "tool_result", { tool: "create_directory", call_id: "synthetic-create-directory", ok: true, text: "created directory src/reviewed", execution_receipt: { contract_version: "agent-tool-execution.v1", elapsed_ms: 1250, timing_source: "server_monotonic.v1", approval_state: "approved", evidence_state: "verified_workspace_effect" } }),
      event(7, "tool_call", { tool: "move_directory", arguments: { source_path: "src/reviewed", target_path: "archive/reviewed" }, call_id: "synthetic-move-directory" }),
      event(8, "tool_result", { tool: "move_directory", call_id: "synthetic-move-directory", ok: true, text: "moved directory src/reviewed to archive/reviewed; contents were not reviewed" }),
      event(9, "tool_call", { tool: "move_file", arguments: { source_path: "example.ts", target_path: "archive/reviewed/example.ts" }, call_id: "synthetic-move-file" }),
      event(10, "tool_result", { tool: "move_file", call_id: "synthetic-move-file", ok: true, text: "moved example.ts to archive/reviewed/example.ts" }),
    ];
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: activity, running: false, pending_approval_id: null, last_seq: 10, first_seq: 1 })),
      getAgentWorkspaceFile: vi.fn(async (_id: string, path: string) => ({
        contract_version: "local-agent-workspace.v1" as const,
        session_id: SESSION,
        path,
        content: "export const example = true;\n",
        revision: "f".repeat(64),
        byte_size: 29,
        line_ending: "lf" as const,
        editable: true as const,
      })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("region", { name: "Agent activity" })).toBeVisible();
    expect(await screen.findByText("Reasoning visible")).toBeVisible();
    expect(screen.getByText("model-provided · expand")).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy agent response" })).toBeVisible();
    expect(screen.getByLabelText("Agent action: Read file")).toHaveTextContent("src/example.ts");
    expect(screen.getByLabelText("Agent action: Create directory")).toHaveTextContent("src/reviewed");
    expect(screen.getByLabelText("Agent action: Move directory")).toHaveTextContent("src/reviewed → archive/reviewed");
    expect(screen.getByLabelText("Agent action: Move file")).toHaveTextContent("example.ts → archive/reviewed/example.ts");
    fireEvent.click(screen.getByRole("button", { name: "the requested file" }));
    expect(await screen.findByLabelText("Workspace file editor")).toHaveValue("export const example = true;\n");
    expect(transport.getAgentWorkspaceFile).toHaveBeenCalledWith(SESSION, "src/example.ts", expect.any(AbortSignal));
    expect(screen.getAllByText("Completed").map((item) => item.closest("summary")?.textContent)).toEqual([
      "CompletedRead file25 msNot requiredRead-only observation",
      "CompletedCreate directory1.25 sApprovedVerified workspace effect",
      "CompletedMove directoryExecution details unavailable",
      "CompletedMove fileExecution details unavailable",
    ]);
    expect(screen.getByText("25 ms")).toHaveAttribute("title", "Elapsed from action request to terminal result; approval waiting is included.");
    expect(screen.getByText("Read-only observation")).toBeVisible();
    expect(screen.getByText("Verified workspace effect")).toBeVisible();
  });

  it("creates a session, sends a message, shows tool activity and approves a write with its diff", async () => {
    let events: AgentEvent[] = [event(1, "status", { text: "Session ready in project/ - reads are free." })];
    let current = view();
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      listAgentSessions: vi.fn(async () => (current ? [current] : [])),
      createAgentSession: vi.fn(async () => { current = view(); return current; }),
      getAgentSession: vi.fn(async () => current),
      deleteAgentSession: vi.fn(async () => undefined),
      sendAgentMessage: vi.fn(async () => {
        events = [
          ...events,
          event(2, "user", { text: "Add a noqa comment" }),
          event(3, "tool_call", { tool: "read_file", arguments: { path: "src/app.py" }, call_id: "c1" }),
          event(4, "tool_result", { tool: "read_file", call_id: "c1", ok: true, text: "def add(a, b):\n    return a + b\n" }),
          event(5, "approval_required", { tool: "write_file", arguments: { path: "src/app.py", content: "..." }, approval_id: APPROVAL, preview: "--- a/src/app.py\n+++ b/src/app.py\n-    return a + b\n+    return a + b  # noqa" }),
        ];
        current = view({ running: true, pending_approval_id: APPROVAL, last_seq: 5, turns: 1 });
        return current;
      }),
      getAgentEvents: vi.fn(async (_id: string, after: number) => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: events.filter((e) => e.seq > after), running: current.running, pending_approval_id: current.pending_approval_id, last_seq: events.length ? events[events.length - 1].seq : 0, first_seq: events.length ? events[0].seq : 0 })),
      decideAgentApproval: vi.fn(async () => {
        events = [...events, event(6, "approval_resolved", { tool: "write_file", approval_id: APPROVAL, ok: true }), event(7, "tool_result", { tool: "write_file", ok: true, text: "wrote src/app.py" }), event(8, "assistant", { text: "Done - comment added." }), event(9, "done")];
        current = view({ running: false, pending_approval_id: null, last_seq: 9, turns: 1 });
        return current;
      }),
      stopAgentSession: vi.fn(async () => current),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByText(/Session ready/);
    const composer = screen.getByRole("form", { name: "Message composer" });
    expect(composer).toHaveTextContent("Message to the agent");
    expect(screen.getByLabelText("Message to the agent")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Add a noqa comment" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(transport.sendAgentMessage).toHaveBeenCalledWith(SESSION, "Add a noqa comment", []));
    await screen.findByLabelText("Agent action: Read file");
    const approvalDialog = await screen.findByRole("alertdialog", { name: "Approval needed" });
    expect(approvalDialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(approvalDialog);
    expect(screen.getByText("Approval needed for Write file.")).toBeTruthy();
    expect(screen.getByText(/return a \+ b\s+# noqa/)).toBeTruthy();
    expect(within(approvalDialog).getByRole("figure", { name: "Pending reviewed file diff" })).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(transport.decideAgentApproval).toHaveBeenCalledWith(SESSION, APPROVAL, true));
    await screen.findByText("Done - comment added.");
    expect(screen.getByText("Approved").closest(".agent__activity-event")).toHaveTextContent("Write file");
  });

  it("labels an external-controller proposal and keeps its diff native-reviewed", async () => {
    const proposalCall = "c".repeat(32);
    const activity = [
      event(1, "tool_call", {
        tool: "write_file",
        call_id: proposalCall,
        arguments: {
          path: "src/example.py",
          operation: "edit",
          source: "external_controller",
        },
      }),
      event(2, "approval_required", {
        tool: "write_file",
        call_id: proposalCall,
        approval_id: APPROVAL,
        arguments: {
          path: "src/example.py",
          operation: "edit",
          source: "external_controller",
        },
        preview: "--- a/src/example.py\n+++ b/src/example.py\n-old\n+reviewed",
      }),
    ];
    const current = view({
      running: true,
      pending_approval_id: APPROVAL,
      last_seq: 2,
    });
    const transport = {
      ...sessionTransport(current),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: activity,
        running: true,
        pending_approval_id: APPROVAL,
        last_seq: 2,
        first_seq: 1,
      })),
      decideAgentApproval: vi.fn(async () => view({ last_seq: 3 })),
    };

    render(<AgentPage transport={transport} />);

    const dialog = await screen.findByRole("alertdialog", { name: "Approval needed" });
    expect(within(dialog).getByText("External controller proposal")).toBeVisible();
    expect(dialog).toHaveTextContent("src/example.py");
    expect(dialog).toHaveTextContent("+reviewed");
    expect(within(dialog).getByRole("figure", { name: "Pending reviewed file diff" })).toBeVisible();
    expect(screen.getAllByText("Controller proposal")).toHaveLength(2);
    expect(screen.getByText(/external proposal awaiting review/)).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Deny" }));
    await waitFor(() => expect(transport.decideAgentApproval).toHaveBeenCalledWith(
      SESSION,
      APPROVAL,
      false,
    ));
  });

  it("renders one native review card for an external atomic change set", async () => {
    const proposalCall = "d".repeat(32);
    const transactionArguments = {
      file_count: 2,
      create_count: 1,
      edit_count: 1,
      paths: ["src/alpha.py", "src/new.py"],
      transaction: "failure_atomic_create_edit",
      source: "external_controller",
    };
    const current = view({
      running: true,
      pending_approval_id: APPROVAL,
      last_seq: 2,
    });
    const transport = {
      ...sessionTransport(current),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: [
          event(1, "tool_call", {
            tool: "write_file",
            call_id: proposalCall,
            arguments: transactionArguments,
          }),
          event(2, "approval_required", {
            tool: "write_file",
            call_id: proposalCall,
            approval_id: APPROVAL,
            arguments: transactionArguments,
            preview: "Transaction file 1/2 [edit]: src/alpha.py\n-alpha\n+reviewed alpha\n\nTransaction file 2/2 [create]: src/new.py\n+reviewed new",
          }),
        ],
        running: true,
        pending_approval_id: APPROVAL,
        last_seq: 2,
        first_seq: 1,
      })),
    };

    render(<AgentPage transport={transport} />);

    const dialog = await screen.findByRole("alertdialog", { name: "Approval needed" });
    expect(within(dialog).getByText("External controller change set")).toBeVisible();
    expect(dialog).toHaveTextContent("2 files · 1 create · 1 edit: src/alpha.py, src/new.py");
    expect(dialog).toHaveTextContent("reviewed alpha");
    expect(dialog).toHaveTextContent("reviewed new");
    expect(within(dialog).getByRole("figure", { name: "Pending reviewed file diff" })).toBeVisible();
    expect(screen.getAllByText("Controller change set")).toHaveLength(2);
    expect(within(dialog).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Wrap long lines",
      "Copy",
      "Approve",
      "Deny",
    ]);
  });

  it("shows stopped models truthfully, starts the selection in place, then creates the exact session", async () => {
    const stopped = modelStatus("stopped", MODEL_ALIAS, "Synthetic 27B");
    const running = modelStatus("running", MODEL_ALIAS, "Synthetic 27B");
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async (settings: AgentSettings) => view({
        settings: { ...view().settings, workspace: settings.workspace, model_alias: settings.model_alias },
        model_alias: settings.model_alias,
      })),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(stopped)),
      activateLocalModel: vi.fn(async () => running),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("option", { name: "Synthetic 27B · stopped" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    fireEvent.change(screen.getByLabelText("Agent model"), { target: { value: MODEL_ALIAS } });

    expect(screen.getByText("Synthetic 27B is stopped. Opening the chat will start it automatically.")).toBeVisible();
    const start = screen.getByRole("button", { name: "Start model & open read-only chat" });
    expect(start).toBeEnabled();
    fireEvent.click(start);

    await waitFor(() => expect(transport.activateLocalModel).toHaveBeenCalledWith(MODEL_ALIAS, {
      remember: true,
      fast_attention: true,
      tool_calling: true,
    }));
    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledOnce());
    expect(transport.createAgentSession.mock.calls[0][0]).toMatchObject({
      workspace: "D:\\example\\project",
      model_alias: MODEL_ALIAS,
    });
    expect(await screen.findByLabelText("Message to the agent")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeVisible();
  });

  it("loads a stopped model as read-only state and never starts it without an explicit action", async () => {
    const activateLocalModel = vi.fn(async () => modelStatus("running"));
    const createAgentSession = vi.fn();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession,
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel,
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("option", { name: "Synthetic Local Model · stopped" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose workspace to open chat" })).toBeDisabled();
    expect(activateLocalModel).not.toHaveBeenCalled();
    expect(createAgentSession).not.toHaveBeenCalled();
  });

  it("opens a durable native chat without loading a model and keeps sending blocked until one is ready", async () => {
    const created = view({
      model_alias: null,
      settings: { ...view().settings, workspace: "D:\\example\\model-free", model_alias: null },
    });
    const activateLocalModel = vi.fn();
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async () => created),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview()),
      activateLocalModel,
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/chat will open without a model/i)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\model-free" } });
    const open = screen.getByRole("button", { name: "Open chat without model" });
    expect(open).toBeEnabled();
    fireEvent.click(open);

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledWith(
      expect.objectContaining({ workspace: "D:\\example\\model-free", model_alias: null }),
    ));
    expect(activateLocalModel).not.toHaveBeenCalled();
    expect(await screen.findByText("No local model is running for this session. Start one on the Models page.")).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getByRole("link", { name: "Open Models" })).toHaveAttribute("href", "/models");
  });

  it("keeps a model-neutral chat fail-closed when the optional model catalogue cannot be read", async () => {
    const current = view({
      model_alias: null,
      settings: { ...view().settings, workspace: "D:\\example\\catalogue-offline", model_alias: null },
    });
    const transport = {
      ...sessionTransport(current),
      getLocalModels: vi.fn(async () => { throw new TypeError("synthetic catalogue unavailable"); }),
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByLabelText("Agent activity status")).toHaveTextContent("No model");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(transport.sendAgentMessage).not.toHaveBeenCalled();
  });

  it("keeps a new chat model-neutral when another local model is already running", async () => {
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async (settings: AgentSettings) => view({
        settings: { ...view().settings, workspace: settings.workspace, model_alias: settings.model_alias },
        model_alias: settings.model_alias,
      })),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("option", { name: "Synthetic Local Model · running" })).toBeVisible();
    expect(screen.getByLabelText("Agent model")).toHaveValue("");
    expect(screen.getByLabelText("Agent model")).toHaveDisplayValue("Choose later in chat · no model");
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat without model" }));

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledOnce());
    expect(transport.createAgentSession.mock.calls[0][0]).toMatchObject({
      workspace: "D:\\example\\project",
      model_alias: null,
    });
  });

  it("opens a model-neutral chat while the optional model catalogue is still loading", async () => {
    const catalogue = deferred<LocalModelsOverview>();
    const created = view({
      model_alias: null,
      settings: { ...view().settings, workspace: "D:\\example\\pending-catalogue", model_alias: null },
    });
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(false)),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async () => created),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(() => catalogue.promise),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText("Checking which local models are ready…")).toBeVisible();
    const workspace = screen.getByLabelText("Workspace folder");
    expect(workspace).toBeEnabled();
    fireEvent.change(workspace, { target: { value: "D:\\example\\pending-catalogue" } });
    const open = screen.getByRole("button", { name: "Open read-only chat without model" });
    expect(open).toBeEnabled();
    fireEvent.click(open);

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledWith(
      expect.objectContaining({ model_alias: null }),
    ));
    await act(async () => catalogue.resolve(modelsOverview(modelStatus("running"))));
  });

  it("does not leak the active chat runtime selection into the next New session", async () => {
    const current = view();
    const runtime = runtimeCoordinator(MODEL_ALIAS);
    const created = view({
      model_alias: null,
      settings: { ...view().settings, workspace: "D:\\example\\fresh-chat", model_alias: null },
    });
    const transport = {
      ...sessionTransport(current),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(false)),
      createAgentSession: vi.fn(async () => created),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(async () => runtime),
      stopLocalRuntime: vi.fn(async () => runtime),
      switchAgentSessionModel: vi.fn(async () => current),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("region", { name: "Shared local model runtime" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    const setupModel = await screen.findByLabelText("Agent model");
    expect(setupModel).toHaveValue("");
    expect(setupModel).toHaveDisplayValue("Choose later in chat · no model");
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\fresh-chat" } });
    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat without model" }));

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledWith(
      expect.objectContaining({ model_alias: null }),
    ));
  });

  it("keeps a successfully created chat selected when the session list is temporarily unavailable", async () => {
    const created = view();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => { throw new TypeError("synthetic list failure"); }),
      createAgentSession: vi.fn(async () => created),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/Sessions could not be refreshed/)).toBeVisible();
    expect(screen.queryByText("No session yet.")).toBeNull();
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    fireEvent.click(await screen.findByRole("button", { name: "Open read-only chat without model" }));

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledOnce());
    expect(await screen.findByLabelText("Message to the agent")).toBeEnabled();
    expect(screen.getByRole("form", { name: "Message composer" })).toBeVisible();
    expect(transport.listAgentSessions).toHaveBeenCalledOnce();
  });

  it("shows session-list failures distinctly and recovers through retry", async () => {
    const listAgentSessions = vi.fn()
      .mockRejectedValueOnce(new TypeError("synthetic list failure"))
      .mockResolvedValueOnce([]);
    const transport = {
      ...workspaceMethods(),
      listAgentSessions,
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/Sessions could not be refreshed/)).toBeVisible();
    expect(screen.queryByText("No session yet.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry sessions" }));

    expect(await screen.findByText("No session yet.")).toBeVisible();
    expect(screen.queryByText(/Sessions could not be refreshed/)).toBeNull();
    expect(listAgentSessions).toHaveBeenCalledTimes(2);
  });

  it.each(["running", "stopped"] as const)("blocks stale %s model and session controls when the local app disconnects", async (state) => {
    const current = view();
    const transport = {
      ...workspaceMethods(),
      getRuntimeHealth: vi.fn(async () => { throw new TypeError("synthetic connection failure"); }),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus(state))),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Local app disconnected");
    const composer = await screen.findByLabelText("Message to the agent");
    expect(composer).toBeDisabled();
    expect(composer).toHaveAttribute("placeholder", expect.stringMatching(/local app is disconnected/i));
    expect(screen.getByRole("button", { name: state === "running" ? "Stop model" : "Start session model" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "New chat" })).toBeDisabled();
  });

  it("clears a ghost session after an authoritative refresh reports it gone", async () => {
    const current = view();
    const base = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    const rendered = render(<AgentPage transport={base} />);
    expect(await screen.findByLabelText("Message to the agent")).toBeVisible();

    const refreshed = { ...base, listAgentSessions: vi.fn(async () => []) };
    rendered.rerender(<AgentPage transport={refreshed} />);

    await waitFor(() => expect(screen.queryByLabelText("Message to the agent")).toBeNull());
    expect(screen.getByText(/Open New chat and enter a workspace folder/)).toBeVisible();
  });

  it("blocks an existing session while its model is stopped and enables the composer after activation", async () => {
    const current = view();
    const stopped = modelStatus("stopped");
    const running = modelStatus("running");
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(),
      sendAgentMessage: vi.fn(async () => view({ turns: 1 })),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(stopped)),
      activateLocalModel: vi.fn(async () => running),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/stopped · start it before sending/)).toBeVisible();
    const composer = screen.getByLabelText("Message to the agent");
    expect(composer).toBeDisabled();
    expect(composer).toHaveAttribute("placeholder", "Start the session model to write a message");

    fireEvent.click(screen.getByRole("button", { name: "Start session model" }));
    await waitFor(() => expect(transport.activateLocalModel).toHaveBeenCalledOnce());
    expect(await screen.findByText(/running · ready for messages/)).toBeVisible();
    expect(composer).toBeEnabled();

    fireEvent.change(composer, { target: { value: "Inspect the synthetic project" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(transport.sendAgentMessage).toHaveBeenCalledWith(SESSION, "Inspect the synthetic project", []));
  });

  it("stops the exact session model without closing the session and exposes restart recovery", async () => {
    const current = view({ turns: 2 });
    const running = modelStatus("running");
    const stopped = modelStatus("stopped");
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(running)),
      activateLocalModel: vi.fn(async () => running),
      deactivateLocalModel: vi.fn(async () => stopped),
    };

    render(<AgentPage transport={transport} />);

    const stopModel = await screen.findByRole("button", { name: "Stop model" });
    expect(stopModel).toBeEnabled();
    fireEvent.click(stopModel);

    await waitFor(() => expect(transport.deactivateLocalModel).toHaveBeenCalledWith(MODEL_ALIAS));
    expect(await screen.findByText(/stopped · start it before sending/)).toBeVisible();
    expect(screen.getByText(/sessions using it remain open but cannot send until it is restarted/i)).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start session model" })).toBeEnabled();
    expect(transport.deleteAgentSession).not.toHaveBeenCalled();
  });

  it.each([
    ["start", "before", "resolve"], ["start", "before", "reject"],
    ["start", "during", "resolve"], ["start", "during", "reject"],
    ["stop", "before", "resolve"], ["stop", "before", "reject"],
    ["stop", "during", "resolve"], ["stop", "during", "reject"],
  ] as const)("keeps a confirmed model %s when a refresh from %s the command later %ss", async (action, timing, outcome) => {
    const initial = modelStatus(action === "start" ? "stopped" : "running");
    const confirmed = modelStatus(action === "start" ? "running" : "stopped");
    const oldRead = deferred<LocalModelsOverview>();
    const command = deferred<LocalModelStatus>();
    const transport = {
      ...sessionTransport(view()),
      getLocalModels: vi.fn().mockResolvedValueOnce(modelsOverview(initial)).mockReturnValueOnce(oldRead.promise),
      activateLocalModel: vi.fn(() => command.promise),
      deactivateLocalModel: vi.fn(() => command.promise),
    };
    await act(async () => { render(<AgentPage transport={transport} />); });
    if (timing === "before") act(() => window.dispatchEvent(new Event("focus")));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: action === "start" ? "Start session model" : "Stop model" })); });
    if (timing === "during") act(() => window.dispatchEvent(new Event("focus")));
    expect(transport.getLocalModels).toHaveBeenCalledTimes(2);
    await act(async () => { command.resolve(confirmed); });
    await act(async () => {
      if (outcome === "resolve") oldRead.resolve(modelsOverview(initial));
      else oldRead.reject(new Error("Synthetic old refresh failure"));
    });
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent(action === "start" ? "Ready" : "Model stopped");
    if (action === "start") expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    else expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("blocks sends during a model-stop request while preserving the draft", async () => {
    const command = deferred<LocalModelStatus>();
    const transport = { ...sessionTransport(view()), deactivateLocalModel: vi.fn(() => command.promise),
      checkPrompt: vi.fn(async () => promptCheckResult()) };
    await act(async () => { render(<AgentPage transport={transport} />); });
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Fictional unsent request" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Stop model" })); });
    try {
      expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Stopping model");
      expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Review prompt without sending" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Review prompt without sending" }));
      fireEvent.submit(screen.getByRole("form", { name: "Message composer" }));
      expect(transport.sendAgentMessage).not.toHaveBeenCalled();
      expect(transport.checkPrompt).not.toHaveBeenCalled();
      expect(screen.getByLabelText("Message to the agent")).toHaveValue("Fictional unsent request");
    } finally { await act(async () => { command.resolve(modelStatus("stopped")); }); }
  });

  it("uses the newest model refresh rather than the last response to arrive", async () => {
    const older = deferred<LocalModelsOverview>();
    const newer = deferred<LocalModelsOverview>();
    const transport = { ...sessionTransport(view()), getLocalModels: vi.fn()
      .mockResolvedValueOnce(modelsOverview(modelStatus("running")))
      .mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise) };
    await act(async () => { render(<AgentPage transport={transport} />); });
    act(() => window.dispatchEvent(new Event("focus")));
    act(() => window.dispatchEvent(new Event("focus")));
    await act(async () => { newer.resolve(modelsOverview(modelStatus("stopped"))); });
    await act(async () => { older.resolve(modelsOverview(modelStatus("running"))); });
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Model stopped");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("does not continue an old model-stop preflight after the transport is replaced", async () => {
    const preflight = deferred<AgentSessionView[]>();
    const previous = { ...sessionTransport(view()), deactivateLocalModel: vi.fn(async () => modelStatus("stopped")) };
    const replacement = sessionTransport(view());
    let rendered!: ReturnType<typeof render>;
    await act(async () => { rendered = render(<AgentPage transport={previous} />); });
    previous.listAgentSessions.mockReturnValueOnce(preflight.promise);
    fireEvent.click(screen.getByRole("button", { name: "Stop model" }));
    await act(async () => { rendered.rerender(<AgentPage transport={replacement} />); });
    await act(async () => { preflight.resolve([view()]); });
    expect(previous.deactivateLocalModel).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Ready");
  });

  it("does not open a session from an activation belonging to a replaced transport", async () => {
    const activation = deferred<LocalModelStatus>();
    const previous = { ...sessionTransport(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(() => activation.promise) };
    const replacement = { ...sessionTransport(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(async () => modelStatus("running")) };
    previous.createAgentSession.mockResolvedValue(view());
    let rendered!: ReturnType<typeof render>;
    await act(async () => { rendered = render(<AgentPage transport={previous} />); });
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:/example/project" } });
    fireEvent.change(screen.getByLabelText("Agent model"), { target: { value: MODEL_ALIAS } });
    fireEvent.click(screen.getByRole("button", { name: "Start model & open read-only chat" }));
    expect(previous.activateLocalModel).toHaveBeenCalledOnce();
    await act(async () => { rendered.rerender(<AgentPage transport={replacement} />); });
    await act(async () => { activation.resolve(modelStatus("running")); });
    expect(previous.createAgentSession).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Message to the agent")).toBeNull();
    expect(screen.getByRole("button", { name: "Start model & open read-only chat" })).toBeEnabled();
  });

  it("keeps failed model-stop status unverified until a fresh refresh confirms recovery", async () => {
    const oldRead = deferred<LocalModelsOverview>();
    const stop = deferred<LocalModelStatus>();
    const transport = { ...sessionTransport(view()),
      getLocalModels: vi.fn().mockResolvedValueOnce(modelsOverview(modelStatus("running")))
        .mockReturnValueOnce(oldRead.promise).mockResolvedValue(modelsOverview(modelStatus("stopped"))),
      deactivateLocalModel: vi.fn(() => stop.promise) };
    await act(async () => { render(<AgentPage transport={transport} />); });
    act(() => window.dispatchEvent(new Event("focus")));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Stop model" })); });
    await act(async () => { stop.reject(new Error("Synthetic unconfirmed stop")); });
    await act(async () => { oldRead.resolve(modelsOverview(modelStatus("running"))); });
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Model unverified");
    expect(screen.getByRole("alert")).toHaveTextContent("model could not be stopped");
    await act(async () => { fireEvent.click(within(screen.getByRole("region", { name: "Agent conversation" }))
      .getByRole("button", { name: "Refresh model status" })); });
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Model stopped");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not release a new connection's pending model action when the old one finishes", async () => {
    const oldStart = deferred<LocalModelStatus>();
    const newStart = deferred<LocalModelStatus>();
    const previous = { ...sessionTransport(view()),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(() => oldStart.promise) };
    const replacement = { ...sessionTransport(view()),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(() => newStart.promise) };
    let rendered!: ReturnType<typeof render>;
    await act(async () => { rendered = render(<AgentPage transport={previous} />); });
    fireEvent.click(screen.getByRole("button", { name: "Start session model" }));
    await act(async () => { rendered.rerender(<AgentPage transport={replacement} />); });
    fireEvent.click(screen.getByRole("button", { name: "Start session model" }));
    await act(async () => { oldStart.resolve(modelStatus("running")); });
    expect(screen.getByRole("button", { name: "Starting model…" })).toBeDisabled();
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(replacement.activateLocalModel).toHaveBeenCalledOnce();
    await act(async () => { newStart.resolve(modelStatus("running")); });
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
  });

  it("does not create a follow-up session after its Agent page unmounts during activation", async () => {
    const activation = deferred<LocalModelStatus>();
    const transport = { ...sessionTransport(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(() => activation.promise) };
    let rendered!: ReturnType<typeof render>;
    await act(async () => { rendered = render(<AgentPage transport={transport} />); });
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:/example/project" } });
    fireEvent.change(screen.getByLabelText("Agent model"), { target: { value: MODEL_ALIAS } });
    fireEvent.click(screen.getByRole("button", { name: "Start model & open read-only chat" }));
    expect(transport.activateLocalModel).toHaveBeenCalledOnce();
    rendered.unmount();
    await act(async () => { activation.resolve(modelStatus("running")); });
    expect(transport.createAgentSession).not.toHaveBeenCalled();
  });

  it("accepts a fresh model observation after an activation has settled", async () => {
    const transport = { ...sessionTransport(view()),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      activateLocalModel: vi.fn(async () => modelStatus("running")) };
    await act(async () => { render(<AgentPage transport={transport} />); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Start session model" })); });
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(screen.getByLabelText("Agent activity status")).toHaveTextContent("Model stopped");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("does not stop a shared model while another session is actively using it", async () => {
    const current = view({ turns: 2 });
    const other = view({ session_id: "d".repeat(32), running: true, turns: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current, other]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
      deactivateLocalModel: vi.fn(async () => modelStatus("stopped")),
    };

    render(<AgentPage transport={transport} />);

    fireEvent.click(await screen.findByRole("button", { name: "Stop model" }));
    expect(await screen.findByText(/Stop every active response using this model/i)).toBeVisible();
    expect(transport.deactivateLocalModel).not.toHaveBeenCalled();
  });

  it("polls a starting model until it becomes ready instead of leaving the session blocked", async () => {
    const current = view();
    const getLocalModels = vi.fn()
      .mockResolvedValueOnce(modelsOverview(modelStatus("starting")))
      .mockResolvedValue(modelsOverview(modelStatus("running")));
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels,
      activateLocalModel: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/starting · start it before sending/)).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Refresh model status" }).length).toBeGreaterThan(0);

    expect(await screen.findByText(/running · ready for messages/, {}, { timeout: 3000 })).toBeVisible();
    expect(getLocalModels).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("Message to the agent")).toBeEnabled();
  });

  it("refreshes a stopped model when the Agent window regains focus", async () => {
    const current = view();
    const getLocalModels = vi.fn()
      .mockResolvedValueOnce(modelsOverview(modelStatus("stopped")))
      .mockResolvedValue(modelsOverview(modelStatus("running")));
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels,
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/stopped · start it before sending/)).toBeVisible();
    window.dispatchEvent(new Event("focus"));

    expect(await screen.findByText(/running · ready for messages/)).toBeVisible();
    expect(getLocalModels).toHaveBeenCalledTimes(2);
  });

  it("refreshes readiness after an asynchronous runtime failure event", async () => {
    const current = view({ running: true, turns: 1 });
    const getLocalModels = vi.fn()
      .mockResolvedValueOnce(modelsOverview(modelStatus("running")))
      .mockResolvedValue(modelsOverview(modelStatus("stopped")));
    const runtimeError = event(1, "error", {
      text: "The local model stopped or became unreachable. Start the session model, then send the request again.",
    });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async (_id: string, after: number) => ({
        contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false,
        session_id: SESSION,
        events: after < 1 ? [runtimeError, event(2, "done")] : [],
        running: false,
        pending_approval_id: null,
        last_seq: 2,
        first_seq: 1,
      })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels,
      activateLocalModel: vi.fn(async () => modelStatus("running")),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText(/stopped · start it before sending/)).toBeVisible();
    expect(getLocalModels).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Start session model" })).toBeEnabled();
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("keeps the own-window conversation primary while preserving the session rail and runtime controls", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const current = view();
    const projectId = "e".repeat(32);
    const project = {
      contract_version: "agent-catalog.v2" as const,
      project_id: projectId,
      name: "Synthetic project",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      revision: 1,
      pinned: true,
      archived_at: null,
      session_count: 1,
      is_default: true,
    };
    const catalogSession: AgentCatalogSession = {
      contract_version: "agent-catalog.v2",
      session_id: SESSION,
      project_id: projectId,
      title: "Synthetic chat",
      workspace: current.settings.workspace,
      model_alias: current.model_alias,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      last_opened_at: "2040-01-01T10:00:00Z",
      revision: 1,
      pinned: false,
      archived_at: null,
      history_state: "memory_only",
      retention_policy: "metadata_only",
      history_revision: 0,
      last_event_seq: 0,
      turn_count: 0,
      conversation_available: true,
      lineage: null,
    };
    const runtime = runtimeCoordinator(MODEL_ALIAS);
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(async () => runtime),
      stopLocalRuntime: vi.fn(async () => runtime),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [project] })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, sessions: [catalogSession] })),
      updateAgentCatalogSession: vi.fn(async () => catalogSession),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
    };
    const { container } = render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toHaveFocus());
    expect(composer).toHaveAttribute("aria-describedby", "agent-session-model-status agent-composer-shortcut");
    expect(container.querySelector(".agent__workbench")).toHaveAttribute("data-has-workspace", "false");
    expect(screen.queryByText("Files and reviewed changes")).toBeNull();
    expect(await screen.findByRole("navigation", { name: "Agent projects and chats" })).toBeVisible();
    const runtimeRegion = await screen.findByRole("region", { name: "Shared local model runtime" });
    expect(runtimeRegion).toBeVisible();
    expect(screen.getByRole("form", { name: "Message composer" })).toContainElement(runtimeRegion);
    expect(container.querySelector(".agent__side")).not.toContainElement(runtimeRegion);
    expect(screen.queryByLabelText("Workspace folder")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByRole("dialog", { name: "New session" })).toBeVisible();
    expect(await screen.findByLabelText("Workspace folder")).toBeVisible();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("opens one native child and restores its exact chat after the child document reloads", async () => {
    const windowKey = "d".repeat(32);
    const originalChannel = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    class FakeChannel {
      static channels = new Set<FakeChannel>();
      readonly name: string;
      private listeners = new Set<(event: MessageEvent<unknown>) => void>();

      constructor(name: string) {
        this.name = name;
        FakeChannel.channels.add(this);
      }

      addEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.add(listener);
      }

      removeEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.delete(listener);
      }

      postMessage(message: unknown): void {
        for (const channel of FakeChannel.channels) {
          if (channel === this || channel.name !== this.name) continue;
          queueMicrotask(() => {
            for (const listener of channel.listeners) listener(new MessageEvent("message", { data: message }));
          });
        }
      }

      close(): void {
        this.listeners.clear();
        FakeChannel.channels.delete(this);
      }
    }

    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: FakeChannel });
    const nativeOpen = vi.fn(async () => ({
      version: "native-agent-window-v1",
      status: "opened",
      window_key: windowKey,
      listener_started: false,
      worker_started: false,
      process_spawned: false,
      runtime_owner_created: false,
    }));
    Object.defineProperty(globalThis, "pywebview", {
      configurable: true,
      value: { api: { open_agent_chat_window: nativeOpen } },
    });
    const selected: string[] = [];
    let closeChild = listenForAgentWindowSelection(windowKey, (sessionId) => {
      selected.push(sessionId);
      return true;
    });
    const rendered = render(<AgentPage transport={sessionTransport(view())} />);
    try {
      fireEvent.click(await screen.findByRole("button", { name: "Open separate window" }));
      await waitFor(() => expect(selected).toEqual([SESSION]));
      expect(nativeOpen).toHaveBeenCalledOnce();
      expect(nativeOpen).toHaveBeenCalledWith({
        version: "native-agent-window-v1",
        window_key: expect.stringMatching(/^[a-f0-9]{32}$/u),
      });

      closeChild();
      closeChild = listenForAgentWindowSelection(windowKey, (sessionId) => {
        selected.push(sessionId);
        return true;
      });
      await waitFor(() => expect(selected).toEqual([SESSION, SESSION]));
      expect(nativeOpen).toHaveBeenCalledOnce();
    } finally {
      rendered.unmount();
      closeChild();
      FakeChannel.channels.clear();
      if (originalChannel) Object.defineProperty(globalThis, "BroadcastChannel", originalChannel);
      else Reflect.deleteProperty(globalThis, "BroadcastChannel");
    }
  });

  it("keeps child-local chat navigation as the detached window reload target", async () => {
    const windowKey = "e".repeat(32);
    const first = view({ settings: { ...view().settings, title: "Detached chat A" } });
    const second = view({
      session_id: "f".repeat(32),
      settings: { ...view().settings, title: "Detached chat B" },
    });
    const originalChannel = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    const originalRoute = `${window.location.pathname}${window.location.search}${window.location.hash}`;

    class FakeChannel {
      static channels = new Set<FakeChannel>();
      readonly name: string;
      private listeners = new Set<(event: MessageEvent<unknown>) => void>();

      constructor(name: string) {
        this.name = name;
        FakeChannel.channels.add(this);
      }

      addEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.add(listener);
      }

      removeEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.delete(listener);
      }

      postMessage(message: unknown): void {
        for (const channel of FakeChannel.channels) {
          if (channel === this || channel.name !== this.name) continue;
          queueMicrotask(() => {
            for (const listener of channel.listeners) listener(new MessageEvent("message", { data: message }));
          });
        }
      }

      close(): void {
        this.listeners.clear();
        FakeChannel.channels.delete(this);
      }
    }

    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: FakeChannel });
    window.history.replaceState({}, "", `/agent/window?window=${windowKey}`);
    const owner = connectAgentWindowSelectionOwner();
    expect(owner.assign(windowKey, first.session_id)).toBe(true);
    const transport = sessionTransport(first, second);
    transport.getAgentSession.mockImplementation(async (sessionId: string) => (
      sessionId === second.session_id ? second : first
    ));
    let rendered = render(<AgentPage transport={transport} windowMode />);
    try {
      expect(await screen.findByRole("heading", { name: "Detached chat A" })).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: /^Detached chat B ·/u }));
      expect(await screen.findByRole("heading", { name: "Detached chat B" })).toBeVisible();
      await act(async () => undefined);

      rendered.unmount();
      rendered = render(<AgentPage transport={transport} windowMode />);
      expect(await screen.findByRole("heading", { name: "Detached chat B" })).toBeVisible();
    } finally {
      rendered.unmount();
      owner.close();
      FakeChannel.channels.clear();
      window.history.replaceState({}, "", originalRoute);
      if (originalChannel) Object.defineProperty(globalThis, "BroadcastChannel", originalChannel);
      else Reflect.deleteProperty(globalThis, "BroadcastChannel");
    }
  });

  it("acknowledges an own-window handoff only after a dirty workspace switch is accepted", async () => {
    const targetSessionId = "c".repeat(32);
    const windowKey = "d".repeat(32);
    const first = view();
    const target = view({
      session_id: targetSessionId,
      settings: { ...view().settings, workspace: "D:\\example\\target" },
    });
    const targetLookup = deferred<AgentSessionView>();
    const originalChannel = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    const originalRoute = `${window.location.pathname}${window.location.search}${window.location.hash}`;

    class FakeChannel {
      static channels = new Set<FakeChannel>();
      readonly name: string;
      private listeners = new Set<(event: MessageEvent<unknown>) => void>();

      constructor(name: string) {
        this.name = name;
        FakeChannel.channels.add(this);
      }

      addEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.add(listener);
      }

      removeEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.delete(listener);
      }

      postMessage(message: unknown): void {
        for (const channel of FakeChannel.channels) {
          if (channel === this || channel.name !== this.name) continue;
          queueMicrotask(() => {
            for (const listener of channel.listeners) listener(new MessageEvent("message", { data: message }));
          });
        }
      }

      close(): void {
        this.listeners.clear();
        FakeChannel.channels.delete(this);
      }
    }

    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: FakeChannel });
    window.history.replaceState({}, "", `/agent/window?window=${windowKey}`);
    const transport = editableWorkspaceTransport(first);
    transport.getAgentSession.mockImplementation((nextSessionId: string) => (
      nextSessionId === targetSessionId ? targetLookup.promise : Promise.resolve(first)
    ));
    const rendered = render(<AgentPage transport={transport} windowMode />);
    const sender = new FakeChannel("prompt-enhancer-agent-window-v1");
    const acknowledgements: string[] = [];
    const observer = new FakeChannel("prompt-enhancer-agent-window-v1");
    observer.addEventListener("message", (message) => {
      const value = message.data as { kind?: unknown; session_id?: unknown };
      if (value?.kind === "selected" && typeof value.session_id === "string") {
        acknowledgements.push(value.session_id);
      }
    });
    try {
      await screen.findByText("D:\\example\\project");
      const editor = await openDirtyWorkspaceDraft();
      sender.postMessage({
        version: AGENT_WINDOW_CHANNEL_VERSION,
        kind: "select",
        window_key: windowKey,
        session_id: targetSessionId,
      });

      await waitFor(() => expect(transport.getAgentSession).toHaveBeenCalledWith(
        targetSessionId,
        expect.any(AbortSignal),
      ));
      expect(screen.queryByRole("dialog", { name: "Discard workspace changes?" })).toBeNull();
      expect(acknowledgements).toEqual([]);
      targetLookup.resolve(target);
      const keepDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
      fireEvent.click(within(keepDialog).getByRole("button", { name: "Keep current state" }));
      fireEvent.click(screen.getByText("Chat details", { exact: true }));
      expect(screen.getByText("D:\\example\\project")).toBeVisible();
      expect(editor).toHaveValue("Synthetic unsaved edit.\n");
      expect(acknowledgements).toEqual([]);

      await act(async () => undefined);
      sender.postMessage({
        version: AGENT_WINDOW_CHANNEL_VERSION,
        kind: "select",
        window_key: windowKey,
        session_id: targetSessionId,
      });
      const switchDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
      fireEvent.click(within(switchDialog).getByRole("button", { name: "Discard and switch chat" }));

      expect(await screen.findByText("D:\\example\\target")).toBeVisible();
      expect(screen.queryByText("D:\\example\\project")).toBeNull();
      expect(transport.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
      await waitFor(() => expect(acknowledgements).toEqual([targetSessionId]));
    } finally {
      rendered.unmount();
      sender.close();
      observer.close();
      window.history.replaceState({}, "", originalRoute);
      if (originalChannel) Object.defineProperty(globalThis, "BroadcastChannel", originalChannel);
      else Reflect.deleteProperty(globalThis, "BroadcastChannel");
    }
  }, 15_000);

  it("refreshes the live chat title after a content-free catalog change from another window", async () => {
    const originalChannel = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    class FakeChannel {
      static channels = new Set<FakeChannel>();
      readonly name: string;
      private listeners = new Set<(event: MessageEvent<unknown>) => void>();

      constructor(name: string) {
        this.name = name;
        FakeChannel.channels.add(this);
      }

      addEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.add(listener);
      }

      removeEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
        this.listeners.delete(listener);
      }

      postMessage(message: unknown): void {
        for (const channel of FakeChannel.channels) {
          if (channel === this || channel.name !== this.name) continue;
          queueMicrotask(() => {
            for (const listener of channel.listeners) listener(new MessageEvent("message", { data: message }));
          });
        }
      }

      close(): void {
        this.listeners.clear();
        FakeChannel.channels.delete(this);
      }
    }

    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: FakeChannel });
    let current = view({ settings: { ...view().settings, title: "Before rename" } });
    const transport = sessionTransport();
    transport.listAgentSessions.mockImplementation(async () => [current]);
    const rendered = render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);
    const sender = new FakeChannel("prompt-enhancer-agent-window-v1");
    try {
      expect(await screen.findByRole("heading", { name: "Before rename" })).toBeVisible();
      current = view({ settings: { ...view().settings, title: "After rename" } });
      sender.postMessage({
        version: AGENT_WINDOW_CHANNEL_VERSION,
        kind: "catalog-changed",
      });

      expect(await screen.findByRole("heading", { name: "After rename" })).toBeVisible();
      expect(transport.listAgentSessions).toHaveBeenCalledTimes(2);
    } finally {
      rendered.unmount();
      sender.close();
      FakeChannel.channels.clear();
      if (originalChannel) Object.defineProperty(globalThis, "BroadcastChannel", originalChannel);
      else Reflect.deleteProperty(globalThis, "BroadcastChannel");
    }
  });

  it("resolves a dedicated window directly when the session list does not contain its route session", async () => {
    const current = view({ turns: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(),
      getAgentSession: vi.fn(async () => current),
      deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };

    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByLabelText("Message to the agent")).toBeVisible();
    expect(transport.getAgentSession).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal));
    expect(screen.queryByText(/This window has no session/)).toBeNull();
  });

  it("reopens retained history in a dedicated route after its live session was cleared by restart", async () => {
    const projectId = "a".repeat(32);
    const project = catalogProjectFixture(projectId, "Restart project", 1);
    const saved = catalogSessionFixture(SESSION, projectId, "Restarted retained chat", {
      revision: 4,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 2,
      last_event_seq: 2,
      turn_count: 1,
      conversation_available: true,
    });
    const retainedEvents = [
      event(1, "user", { text: "Synthetic request retained across restart." }),
      event(2, "assistant", { text: "Synthetic response retained across restart." }),
    ];
    const getAgentSession = vi.fn(async () => {
      throw new TransportError("synthetic live session cleared", 404);
    });
    const transport = retainedCatalogTransport(project, [saved], {
      getAgentSession,
      resumeAgentSession: vi.fn(async () => view({
        session_id: SESSION,
        model_alias: saved.model_alias,
        settings: { ...view().settings, project_id: projectId, model_alias: saved.model_alias, title: saved.title, retention_policy: "local_history" },
      })),
      getAgentPersistedEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        session_id: SESSION,
        events: retainedEvents,
        running: false,
        closing: false,
        stopping: false,
        cleanup_unconfirmed: false,
        pending_approval_id: null,
        last_seq: 2,
        first_seq: 1,
      })),
    });

    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByRole("heading", { name: "Restarted retained chat", level: 2 })).toBeVisible();
    expect(await screen.findByText("Synthetic request retained across restart.")).toBeVisible();
    expect(screen.getByText("Synthetic response retained across restart.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Resume chat" })).toBeEnabled();
    expect(screen.queryByLabelText("Message to the agent")).toBeNull();
    expect(screen.queryByText(/in-memory session is no longer available/i)).toBeNull();
    expect(getAgentSession).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal));
    expect(transport.getAgentCatalogSession).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal));
    expect(transport.getAgentPersistedEvents).toHaveBeenCalledWith(
      projectId,
      SESSION,
      0,
      expect.any(AbortSignal),
    );
  });

  it("reopens a metadata-only dedicated route without inventing lost conversation history", async () => {
    const projectId = "b".repeat(32);
    const project = catalogProjectFixture(projectId, "Metadata restart project", 1);
    const saved = catalogSessionFixture(SESSION, projectId, "Metadata-only restarted chat", {
      revision: 3,
      history_state: "memory_only",
      retention_policy: "metadata_only",
      conversation_available: false,
    });
    const transport = retainedCatalogTransport(project, [saved], {
      getAgentSession: vi.fn(async () => {
        throw new TransportError("synthetic live session cleared", 404);
      }),
    });

    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByRole("heading", { name: "Metadata-only restarted chat", level: 2 })).toBeVisible();
    expect(screen.getByText("Metadata only · history unavailable")).toBeVisible();
    expect(screen.getByText(/Its messages were not stored; nothing has been reconstructed/)).toBeVisible();
    expect(transport.getAgentPersistedEvents).not.toHaveBeenCalled();
    expect(screen.queryByText(/in-memory session is no longer available/i)).toBeNull();
  });

  it("explains when a dedicated route exists in neither live memory nor the durable catalog", async () => {
    const projectId = "c".repeat(32);
    const project = catalogProjectFixture(projectId, "Missing route project", 0);
    const getAgentCatalogSession = vi.fn(async () => {
      throw new TransportError("synthetic catalog session missing", 404);
    });
    const transport = retainedCatalogTransport(project, [], {
      getAgentSession: vi.fn(async () => {
        throw new TransportError("synthetic live session missing", 404);
      }),
      getAgentCatalogSession,
    });

    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByText(/in-memory session is no longer available/i)).toBeVisible();
    expect(screen.getByRole("link", { name: "Return to Agent" })).toHaveAttribute("href", "/agent");
    expect(getAgentCatalogSession).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal));
  });

  it("does not let a late durable lookup replace a newer dedicated route", async () => {
    const projectId = "d".repeat(32);
    const secondSessionId = "e".repeat(32);
    const project = catalogProjectFixture(projectId, "Route ownership project", 1);
    const staleRecord = catalogSessionFixture(SESSION, projectId, "Stale retained route", {
      history_state: "durable_local",
      retention_policy: "local_history",
      conversation_available: true,
    });
    const secondLive = view({
      session_id: secondSessionId,
      settings: {
        ...view().settings,
        project_id: projectId,
        title: "Newer live route",
      },
    });
    const staleLookup = deferred<AgentCatalogSession>();
    let staleSignal: AbortSignal | undefined;
    const getAgentCatalogSession = vi.fn((sessionId: string, signal?: AbortSignal) => {
      if (sessionId !== SESSION) throw new TransportError("synthetic catalog session missing", 404);
      staleSignal = signal;
      return staleLookup.promise;
    });
    const transport = retainedCatalogTransport(project, [staleRecord], {
      getAgentSession: vi.fn(async (sessionId: string) => {
        if (sessionId === secondSessionId) return secondLive;
        throw new TransportError("synthetic live session missing", 404);
      }),
      getAgentCatalogSession,
    });

    const rendered = render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);
    await waitFor(() => expect(getAgentCatalogSession).toHaveBeenCalledWith(
      SESSION,
      expect.any(AbortSignal),
    ));

    rendered.rerender(<AgentPage sessionId={secondSessionId} transport={transport} windowMode />);
    expect(await screen.findByRole("heading", { name: "Newer live route", level: 1 })).toBeVisible();
    await waitFor(() => expect(staleSignal?.aborted).toBe(true));

    await act(async () => { staleLookup.resolve(staleRecord); });
    expect(screen.getByRole("heading", { name: "Newer live route", level: 1 })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Stale retained route", level: 2 })).toBeNull();
  });

  it("gives a model-less own-window session an explicit recovery path", async () => {
    const current = view({
      model_alias: null,
      settings: { ...view().settings, model_alias: null },
    });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview()),
    };
    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByText("No local model is running for this session. Start one on the Models page.")).toBeVisible();
    const recovery = screen.getByRole("link", { name: "Open Models" });
    expect(recovery).toHaveAttribute("href", "/models");
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("keeps coordinated model recovery inside Agent and reveals the exact control", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const current = view({
      model_alias: null,
      settings: { ...view().settings, model_alias: null },
    });
    const runtime = idleRuntimeCoordinator();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(async () => runtime),
      stopLocalRuntime: vi.fn(async () => runtime),
    };
    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByText("No model is bound to this chat. Choose one in Model & context, then start or bind it.")).toBeVisible();
    const runtimePanel = screen.getByRole("region", { name: "Shared local model runtime" });
    const modelControl = within(runtimePanel).getByLabelText("Model");
    fireEvent.click(screen.getByRole("button", { name: "Collapse projects and chats" }));
    expect(screen.getByRole("navigation", { name: "Agent projects and chats (collapsed)" })).toBeVisible();

    const recovery = screen.getByRole("button", { name: "Choose or start model" });
    expect(recovery).toHaveAttribute("aria-controls", "agent-runtime-controls");
    fireEvent.click(recovery);

    await waitFor(() => expect(modelControl).toHaveFocus());
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    expect(screen.getByRole("navigation", { name: "Agent sessions" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open Models" })).toBeNull();
    expect(screen.getByLabelText("Message to the agent")).toHaveAttribute(
      "placeholder",
      "Choose or start a model in Model & context to write a message",
    );
  });

  it("routes a known stopped chat model to the coordinated in-Agent control", async () => {
    const current = view();
    const runtime = idleRuntimeCoordinator();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("stopped"))),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(async () => runtime),
      stopLocalRuntime: vi.fn(async () => runtime),
    };
    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByText("Synthetic Local Model · stopped · start or switch it in Model & context")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose or start model" })).toBeEnabled();
    expect(screen.getByLabelText("Message to the agent")).toBeDisabled();
  });

  it("sends an empty coordinated model catalogue to installation instead of a dead selector", async () => {
    const current = view({
      model_alias: null,
      settings: { ...view().settings, model_alias: null },
    });
    const runtime = idleRuntimeCoordinator();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview()),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(async () => runtime),
      stopLocalRuntime: vi.fn(async () => runtime),
    };
    render(<AgentPage sessionId={SESSION} transport={transport} windowMode />);

    expect(await screen.findByText("No installed local model is available. Add one on the Models page.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open Models" })).toHaveAttribute("href", "/models");
    expect(screen.queryByRole("button", { name: "Choose or start model" })).toBeNull();
  });

  it("keeps session-creation capacity feedback beside the New session form", async () => {
    const current = view();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(async () => { throw new TransportError("synthetic rejection", 409, "too_many_sessions"); }),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);

    await screen.findByText(/running · ready for messages/);
    const newChat = screen.getByRole("button", { name: "New chat" });
    await waitFor(() => expect(newChat).toBeEnabled());
    fireEvent.click(newChat);
    fireEvent.change(await screen.findByLabelText("Workspace folder"), { target: { value: "D:\\example\\second-project" } });
    const start = await screen.findByRole("button", { name: "Open read-only chat without model" });
    fireEvent.click(start);

    const error = await screen.findByText("Too many open sessions - close one first.");
    expect(start.closest("form")).toContainElement(error);
    expect(start).toHaveAttribute("aria-describedby", "agent-create-error");
    expect(screen.getByLabelText("Message to the agent")).toHaveAttribute("aria-describedby", "agent-session-model-status agent-composer-shortcut");
  });

  it("explains a model-readiness race instead of misreporting session capacity", async () => {
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async () => { throw new TransportError("synthetic rejection", 409, "model_not_ready"); }),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);

    await screen.findByRole("option", { name: "Synthetic Local Model · running" });
    fireEvent.change(screen.getByLabelText("Agent model"), { target: { value: MODEL_ALIAS } });
    expect(screen.getByText(/running and ready/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("selected model is not running");
    expect(document.body).not.toHaveTextContent("Too many open sessions");
  });

  it.each([
    ["model_not_ready" as const, /session's model is stopped/i],
    ["no_active_model" as const, /No local model is running/i],
    ["turn_in_progress" as const, /already working on a turn/i],
  ])("shows an actionable %s send failure", async (reasonCode, expected) => {
    const current = view();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(),
      sendAgentMessage: vi.fn(async () => { throw new TransportError("synthetic rejection", 409, reasonCode); }),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toBeEnabled());
    fireEvent.change(composer, { target: { value: "Synthetic request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
  });

  it("clears turn feedback when the user switches to a different session", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({
      session_id: "d".repeat(32),
      settings: { ...view().settings, title: "Session B" },
    });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [first, second]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(),
      sendAgentMessage: vi.fn(async () => { throw new TransportError("synthetic rejection", 409, "model_not_ready"); }),
      getAgentEvents: vi.fn(async (sessionId: string) => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: sessionId, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      getLocalModels: vi.fn(async () => modelsOverview(modelStatus("running"))),
    };
    render(<AgentPage transport={transport} />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toBeEnabled());
    fireEvent.change(composer, { target: { value: "Synthetic request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("session's model is stopped");
    expect(composer).toHaveAttribute("aria-describedby", "agent-session-model-status agent-composer-shortcut agent-message-error");

    fireEvent.click(screen.getByText("Session B").closest("button")!);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByLabelText("Message to the agent")).toHaveAttribute("aria-describedby", "agent-session-model-status agent-composer-shortcut");
  });

  it("explains when the agent is unavailable and lets a new session be created", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(false)),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async (settings: AgentSettings) => view({ settings: { ...view().settings, workspace: settings.workspace } })),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByText(/No session yet/);
    await screen.findByText(/This browser can start read-only sessions/);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat without model" }));
    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalled());
    expect(await screen.findByText(/Session ready\. Write your first request below\./)).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toHaveFocus();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    const settings = transport.createAgentSession.mock.calls[0][0];
    expect(settings.workspace).toBe("D:\\example\\project");
    expect(settings.allow_writes).toBe(false);
    expect(settings.allow_commands).toBe(false);
    expect(settings.allow_web).toBe(false);
  });

  it("uses the native folder picker without reading files and preserves the path on cancel", async () => {
    const choose = vi.fn()
      .mockResolvedValueOnce({
        version: "native-folder-picker-v1",
        status: "selected",
        path: "D:\\example\\chosen-workspace",
      })
      .mockResolvedValueOnce({
        version: "native-folder-picker-v1",
        status: "cancelled",
      });
    installNativeFolderPicker(choose);
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async (_settings: AgentSettings) => view({
        settings: { ...view().settings, workspace: "D:\\example\\chosen-workspace", allow_writes: false, allow_commands: false, allow_web: false },
      })),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    const workspace = screen.getByLabelText("Workspace folder");
    const browse = screen.getByRole("button", { name: "Browse…" });
    expect(browse).toBeEnabled();
    expect(getComputedStyle(workspace).cursor).not.toBe("pointer");
    expect(getComputedStyle(browse).cursor).toBe("pointer");

    fireEvent.click(browse);
    await waitFor(() => expect(workspace).toHaveValue("D:\\example\\chosen-workspace"));
    expect(screen.getByText("Workspace folder selected.")).toBeVisible();

    fireEvent.click(browse);
    await screen.findByText("Folder selection cancelled. The workspace path was not changed.");
    expect(workspace).toHaveValue("D:\\example\\chosen-workspace");
    expect(choose).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat without model" }));
    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledOnce());
    expect(transport.createAgentSession.mock.calls[0][0]).toMatchObject({
      workspace: "D:\\example\\chosen-workspace",
      allow_writes: false,
      allow_commands: false,
      allow_web: false,
    });
  });

  it("enables Browse when the native bridge becomes ready after the form renders", async () => {
    Reflect.deleteProperty(globalThis, "pywebview");
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);
    expect(screen.queryByRole("button", { name: "Browse…" })).toBeNull();
    expect(screen.getByText("Enter path")).toBeVisible();
    expect(screen.getByLabelText("Workspace folder")).toBeEnabled();

    installNativeFolderPicker(vi.fn().mockResolvedValue({
      version: "native-folder-picker-v1",
      status: "cancelled",
    }));
    window.dispatchEvent(new Event("pywebviewready"));

    await waitFor(
      () => expect(screen.getByRole("button", { name: "Browse…" })).toBeEnabled(),
      { timeout: 5_000 },
    );
  });

  it("opens the Windows folder chooser from the ordinary browser without creating a session", async () => {
    Reflect.deleteProperty(globalThis, "pywebview");
    const chooseWorkspaceFolder = vi.fn()
      .mockResolvedValueOnce({
        contract_version: "local-workspace-folder-picker.v1" as const,
        status: "selected" as const,
        path: "D:\\example\\chosen-workspace",
      })
      .mockResolvedValueOnce({
        contract_version: "local-workspace-folder-picker.v1" as const,
        status: "cancelled" as const,
        path: null,
      })
      .mockResolvedValueOnce({
        contract_version: "local-workspace-folder-picker.v1" as const,
        status: "busy" as const,
        path: null,
      });
    const transport = {
      ...workspaceMethods(),
      getWorkspaceFolderPickerCapability: vi.fn(async () => ({
        contract_version: "local-workspace-folder-picker.v1" as const,
        available: true,
        mode: "server_native_dialog" as const,
      })),
      chooseWorkspaceFolder,
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async (_settings: AgentSettings) => view({
        settings: { ...view().settings, workspace: "D:\\example\\chosen-workspace" },
      })),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    const browse = await screen.findByRole("button", { name: "Browse…" });
    const workspace = screen.getByLabelText("Workspace folder");
    expect(transport.createAgentSession).not.toHaveBeenCalled();

    fireEvent.click(browse);
    await waitFor(() => expect(workspace).toHaveValue("D:\\example\\chosen-workspace"));
    expect(transport.createAgentSession).not.toHaveBeenCalled();
    expect(screen.getByText(/Choosing only fills this field/)).toBeVisible();

    fireEvent.click(browse);
    await screen.findByText("Folder selection cancelled. The workspace path was not changed.");
    expect(workspace).toHaveValue("D:\\example\\chosen-workspace");

    fireEvent.click(browse);
    await screen.findByText(/Another folder chooser is already open/);
    expect(workspace).toHaveValue("D:\\example\\chosen-workspace");
    expect(transport.createAgentSession).not.toHaveBeenCalled();
    expect(chooseWorkspaceFolder).toHaveBeenCalledTimes(3);
  });

  it("falls back to the browser chooser when the native bridge fails", async () => {
    const nativeChoose = vi.fn().mockRejectedValue(new Error("synthetic bridge failure"));
    installNativeFolderPicker(nativeChoose);
    const chooseWorkspaceFolder = vi.fn(async () => ({
      contract_version: "local-workspace-folder-picker.v1" as const,
      status: "selected" as const,
      path: "D:\\example\\browser-fallback",
    }));
    const transport = {
      ...workspaceMethods(),
      getWorkspaceFolderPickerCapability: vi.fn(async () => ({
        contract_version: "local-workspace-folder-picker.v1" as const,
        available: true,
        mode: "server_native_dialog" as const,
      })),
      chooseWorkspaceFolder,
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    const browse = await screen.findByRole("button", { name: "Browse…" });
    fireEvent.click(browse);

    await waitFor(() => expect(screen.getByLabelText("Workspace folder")).toHaveValue(
      "D:\\example\\browser-fallback",
    ));
    expect(nativeChoose).toHaveBeenCalledOnce();
    expect(chooseWorkspaceFolder).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps protected scopes off while checking, enables supported choices, and hard-disables web", async () => {
    let resolveCapability!: (value: ReturnType<typeof userPresenceCapability>) => void;
    const capability = new Promise<ReturnType<typeof userPresenceCapability>>((resolve) => {
      resolveCapability = resolve;
    });
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability: vi.fn(() => capability),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async (_settings: AgentSettings) => view()),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    expect(screen.getByText("Checking whether native confirmation is available…")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open read-only chat without model" })).toBeDisabled();
    expect(screen.getByLabelText(/May write files/i)).toBeDisabled();

    await act(async () => resolveCapability(userPresenceCapability(true)));
    await waitFor(() => expect(screen.getByLabelText(/May write files/i)).toBeEnabled());
    expect(screen.getByLabelText(/May write files/i)).not.toBeChecked();
    expect(screen.getByLabelText(/May run commands/i)).not.toBeChecked();
    expect(screen.getByLabelText(/Web fetch unavailable/i)).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/May write files/i));
    fireEvent.click(screen.getByRole("button", { name: "Open chat without model" }));
    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledOnce());
    expect(transport.createAgentSession.mock.calls[0][0]).toMatchObject({
      workspace: "D:\\example\\project",
      allow_writes: true,
      allow_commands: false,
      allow_web: false,
    });
  });

  it("fails closed on a capability error and exposes a retry plus the Windows launcher", async () => {
    const getUserPresenceCapability = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic capability failure"))
      .mockResolvedValueOnce(userPresenceCapability(false));
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability,
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Native confirmation could not be verified");
    expect(screen.getByLabelText(/May write files/i)).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry confirmation check" }));

    await screen.findByText(/This browser can start read-only sessions/);
    expect(screen.getByText("prompt-enhancer agent-desktop")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose workspace to open chat" })).toBeDisabled();
    expect(getUserPresenceCapability).toHaveBeenCalledTimes(2);
  });

  it.each([
    [422, /not an existing folder/i],
    [403, /outside the allowed workspace roots/i],
  ])("associates a %s workspace failure with the folder field", async (status, expected) => {
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async () => { throw new TransportError("synthetic rejection", status); }),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    const workspace = screen.getByLabelText("Workspace folder");
    fireEvent.change(workspace, { target: { value: "D:\\example\\rejected" } });
    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat without model" }));

    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent(expected);
    expect(workspace).toHaveAttribute("aria-invalid", "true");
    expect(workspace).toHaveAttribute("aria-errormessage", error.id);
    expect(workspace).toHaveFocus();
  });

  it("sends the chosen model parameters and standing instructions", async () => {
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => []),
      createAgentSession: vi.fn(async () => view()),
      getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByText(/No session yet/);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "D:\\example\\project" } });
    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.7" } });
    fireEvent.change(screen.getByLabelText("Max tokens"), { target: { value: "2048" } });
    fireEvent.click(screen.getByLabelText(/Thinking mode/));
    fireEvent.change(screen.getByLabelText("Standing instructions"), { target: { value: "Answer in Polish." } });
    fireEvent.click(screen.getByRole("button", { name: "Open read-only chat without model" }));
    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalled());
    const settings = (transport.createAgentSession.mock.calls[0] as unknown[])[0] as {
      parameters: { temperature: number; max_tokens: number; enable_thinking: boolean };
      instructions: string | null;
      retention_policy: "metadata_only" | "local_history";
    };
    expect(settings.parameters.temperature).toBeCloseTo(0.7);
    expect(settings.parameters.max_tokens).toBe(2048);
    expect(settings.parameters.enable_thinking).toBe(true);
    expect(settings.instructions).toBe("Answer in Polish.");
    expect(settings.retention_policy).toBe("local_history");
  });

  it("honours an explicit metadata-only history choice", async () => {
    const transport = {
      ...sessionTransport(),
      createAgentSession: vi.fn(async (settings: AgentSettings) => view({ settings })),
    };
    render(<AgentPage transport={transport} />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "D:\\example\\metadata-only" },
    });
    fireEvent.click(screen.getByRole("radio", { name: /Metadata only/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Open read-only chat without model" }));

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledWith(
      expect.objectContaining({ retention_policy: "metadata_only" }),
    ));
  });

  it("creates a chat in the selected durable project", async () => {
    const firstProjectId = "1".repeat(32);
    const secondProjectId = "2".repeat(32);
    const projects = [
      {
        contract_version: "agent-catalog.v2" as const,
        project_id: firstProjectId,
        name: "Personal workspace",
        created_at: "2040-01-01T10:00:00Z",
        updated_at: "2040-01-01T10:00:00Z",
        revision: 1,
        pinned: true,
        archived_at: null,
        session_count: 0,
        is_default: true,
      },
      {
        contract_version: "agent-catalog.v2" as const,
        project_id: secondProjectId,
        name: "Second project",
        created_at: "2040-01-01T10:00:00Z",
        updated_at: "2040-01-01T10:00:00Z",
        revision: 1,
        pinned: false,
        archived_at: null,
        session_count: 0,
        is_default: false,
      },
    ];
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects })),
      createAgentProject: vi.fn(async () => projects[0]),
      updateAgentProject: vi.fn(async () => projects[0]),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, sessions: [] })),
      updateAgentCatalogSession: vi.fn(),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      createAgentSession: vi.fn(async (settings: AgentSettings) => view({ settings })),
    };
    render(<AgentPage transport={transport} />);

    await screen.findByText("Second project");
    fireEvent.click(screen.getByRole("button", { name: /^Second project/u }));
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "D:\\example\\second-project" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Open read-only chat without model" }));

    await waitFor(() => expect(transport.createAgentSession).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: secondProjectId }),
    ));
    expect(await screen.findByLabelText("Message to the agent")).toBeVisible();
  });

  it("returns focus to the New chat trigger when setup is dismissed", async () => {
    render(<AgentPage transport={sessionTransport()} />);

    const trigger = await screen.findByRole("button", { name: "New chat" });
    await waitFor(() => expect(trigger).toBeEnabled());
    trigger.focus();
    fireEvent.click(trigger);

    const workspace = await screen.findByLabelText("Workspace folder");
    await waitFor(() => expect(workspace).toHaveFocus());
    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps settings and file review subordinate to the active chat", async () => {
    render(<AgentPage transport={sessionTransport(view())} />);

    const composer = await screen.findByLabelText("Message to the agent");
    const conversation = screen.getByRole("region", { name: "Agent conversation" });
    fireEvent.click(screen.getByRole("link", {
      name: "Skip projects and settings; go to conversation",
    }));
    expect(conversation).toHaveFocus();

    const settingsTrigger = screen.getByRole("button", { name: /Agent settings/ });
    expect(settingsTrigger.closest(".agent__side-scroll")).toBeNull();
    expect(settingsTrigger.parentElement).toHaveClass("agent__settings-launch");
    fireEvent.click(settingsTrigger);
    expect(screen.getByRole("dialog", { name: "Agent settings" })).toBeVisible();
    const readinessTab = screen.getByRole("tab", { name: "Readiness" });
    expect(readinessTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Agent capability readiness" })).toBeVisible();
    readinessTab.focus();
    fireEvent.keyDown(readinessTab, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Connections" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Connections" })).toHaveFocus();
    expect(screen.queryByRole("region", { name: "Guarded native Agent acceptance" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "MCP Store" }));
    const store = await screen.findByRole("region", { name: "MCP Store" });
    expect(store).toBeVisible();
    expect(screen.getByRole("dialog", { name: "Agent settings" })).toHaveAttribute("data-settings-tab", "store");
    expect(within(store).getByRole("tab", { name: "Browse servers" })).toHaveAttribute("aria-selected", "true");
    expect(within(store).getByText(/Browsing never installs, connects, starts a process, or grants a tool permission/i)).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Owner checks" }));
    const ownerAcceptance = screen.getByRole("region", { name: "Guarded native Agent acceptance" });
    expect(ownerAcceptance).toBeVisible();
    expect(within(ownerAcceptance).getByRole("button", { name: "Native confirmation required" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "Team folders" }));
    const teamFolders = screen.getByRole("region", { name: "Team folders" });
    expect(teamFolders).toBeVisible();
    expect(screen.queryByRole("region", { name: "Guarded native Agent acceptance" })).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Agent settings" })).toBeNull();
    expect(settingsTrigger).toHaveFocus();

    fireEvent.change(composer, { target: { value: "Keep this synthetic draft" } });
    expect(screen.queryByRole("heading", { name: "Files and reviewed changes" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Files & review" }));
    expect(await screen.findByRole("heading", { name: "Files and reviewed changes" })).toBeVisible();
    const resizer = screen.getByRole("separator", { name: "Resize files and review drawer" });
    expect(resizer).toHaveAttribute("aria-valuenow", "520");
    fireEvent.keyDown(resizer, { key: "ArrowLeft" });
    expect(resizer).toHaveAttribute("aria-valuenow", "544");
    fireEvent.keyDown(resizer, { key: "Home" });
    expect(resizer).toHaveAttribute("aria-valuenow", "352");
    fireEvent.click(screen.getByRole("button", { name: "Hide workspace" }));
    expect(screen.queryByRole("heading", { name: "Files and reviewed changes" })).toBeNull();
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Keep this synthetic draft");
  }, 10_000);

  it("keeps an active owner acceptance receipt when Settings closes and reopens", async () => {
    const current = view({
      recovered: true,
      recovery_state: "recovered",
      settings: {
        ...view().settings,
        retention_policy: "local_history",
      },
    });
    const idleRuntime: LocalRuntimeCoordinatorStatus = {
      ...runtimeCoordinator(MODEL_ALIAS, 41),
      state: "idle",
      requested: null,
      served: null,
      capabilities: {
        ...runtimeCoordinator(MODEL_ALIAS, 41).capabilities,
        state: "not_probed",
        text: false,
        tools: false,
      },
      context: {
        ...runtimeCoordinator(MODEL_ALIAS, 41).context,
        state: "unknown",
        used_tokens: null,
        limit_tokens: null,
        requested_output_tokens: null,
        available_output_tokens: null,
        source: "runtime_limit_only",
        scope: "runtime_limit",
        policy: "runtime_enforced",
        compacted_messages: 0,
        reason_code: "runtime_not_served",
      },
    };
    const beginAgentNativeAcceptance = vi.fn(async () => ({
      contract_version: "agent-native-acceptance-start.v1" as const,
      owner_presence_confirmed: true as const,
      model_execution_started: false as const,
      process_spawn_requested: false as const,
      workspace_access_requested: false as const,
      content_persisted: false as const,
      expires_on_reload: true as const,
    }));
    const transport = {
      ...sessionTransport(current),
      beginAgentNativeAcceptance,
      getLocalRuntime: vi.fn(async () => idleRuntime),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
    };
    render(<AgentPage transport={transport} />);

    const settingsTrigger = await screen.findByRole("button", { name: /Agent settings/ });
    fireEvent.click(settingsTrigger);
    fireEvent.click(screen.getByRole("tab", { name: "Owner checks" }));
    fireEvent.click(await screen.findByRole("button", { name: "Begin guarded acceptance" }));
    await screen.findByRole("button", { name: "Check current evidence" });

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Agent settings" })).toBeNull());
    fireEvent.click(settingsTrigger);
    fireEvent.click(screen.getByRole("tab", { name: "Owner checks" }));

    expect(screen.getByRole("button", { name: "Check current evidence" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Begin guarded acceptance" })).toBeNull();
    expect(beginAgentNativeAcceptance).toHaveBeenCalledOnce();
  }, 10_000);

  it("keeps or discards a dirty review drawer through the non-blocking dialog with focus return", async () => {
    const transport = editableWorkspaceTransport(view());
    const nativeConfirm = vi.spyOn(window, "confirm");
    try {
      render(<AgentPage transport={transport} />);
      const editor = await openDirtyWorkspaceDraft();
      const hide = screen.getByRole("button", { name: "Hide workspace" });
      hide.focus();
      fireEvent.click(hide);

      const keepDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
      expect(within(keepDialog).getByText("Discard the unsaved manual workspace edit?")).toBeVisible();
      expect(within(keepDialog).getByText(/No workspace file is changed/u)).toBeVisible();
      await waitFor(() => expect(within(keepDialog).getByRole("button", { name: "Keep current state" })).toHaveFocus());
      fireEvent.keyDown(document, { key: "Escape" });

      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard workspace changes?" })).not.toBeInTheDocument());
      expect(editor).toHaveValue("Synthetic unsaved edit.\n");
      await waitFor(() => expect(hide).toHaveFocus());

      fireEvent.click(hide);
      const discardDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
      fireEvent.click(within(discardDialog).getByRole("button", { name: "Discard and close" }));

      await waitFor(() => expect(screen.queryByLabelText("Workspace file editor")).not.toBeInTheDocument());
      await waitFor(() => expect(screen.getByLabelText("Message to the agent")).toHaveFocus());
      expect(transport.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
      expect(nativeConfirm).not.toHaveBeenCalled();
    } finally {
      nativeConfirm.mockRestore();
    }
  }, 15_000);

  it("protects a dirty workspace while switching chats and clears the dirty state only after acceptance", async () => {
    const first = view({ settings: { ...view().settings, title: "Session A" } });
    const second = view({
      session_id: "d".repeat(32),
      settings: { ...view().settings, title: "Session B" },
    });
    const transport = editableWorkspaceTransport(first, second);
    render(<AgentPage transport={transport} />);
    const editor = await openDirtyWorkspaceDraft();

    const secondChat = screen.getByRole("button", { name: /^Session B ·/u });
    fireEvent.click(secondChat);
    const keepDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(keepDialog).getByRole("button", { name: "Keep current state" }));
    expect(screen.getByRole("heading", { name: "Session A" })).toBeVisible();
    expect(editor).toHaveValue("Synthetic unsaved edit.\n");

    fireEvent.click(secondChat);
    const switchDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(switchDialog).getByRole("button", { name: "Discard and switch chat" }));

    expect(await screen.findByRole("heading", { name: "Session B" })).toBeVisible();
    expect(screen.queryByLabelText("Workspace file editor")).not.toBeInTheDocument();
    expect(transport.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  }, 15_000);

  it("combines live-chat close and dirty-workspace consequences into one confirmation", async () => {
    const session = view({ settings: { ...view().settings, title: "Close fixture" } });
    let open = [session];
    const transport = editableWorkspaceTransport(session);
    transport.listAgentSessions.mockImplementation(async () => open);
    transport.deleteAgentSession.mockImplementation(async () => { open = []; });
    render(<AgentPage transport={transport} />);
    const editor = await openDirtyWorkspaceDraft();

    const close = screen.getByRole("button", { name: "Close session Close fixture" });
    fireEvent.click(close);
    const keepDialog = await screen.findByRole("dialog", { name: "Close live chat?" });
    expect(within(keepDialog).getByText(/metadata-only conversation content cannot be reopened/u)).toBeVisible();
    expect(within(keepDialog).getByText(/unsaved manual workspace edit.*will also be discarded/u)).toBeVisible();
    fireEvent.click(within(keepDialog).getByRole("button", { name: "Keep current state" }));
    expect(editor).toHaveValue("Synthetic unsaved edit.\n");
    expect(transport.deleteAgentSession).not.toHaveBeenCalled();

    fireEvent.click(close);
    const closeDialog = await screen.findByRole("dialog", { name: "Close live chat?" });
    fireEvent.click(within(closeDialog).getByRole("button", { name: "Close chat" }));

    await waitFor(() => expect(transport.deleteAgentSession).toHaveBeenCalledExactlyOnceWith(SESSION));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Close fixture" })).not.toBeInTheDocument());
    expect(screen.queryByRole("dialog", { name: "Discard workspace changes?" })).not.toBeInTheDocument();
    expect(transport.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  }, 15_000);

  it("keeps a selected metadata-only chat visible instead of bouncing back to the newest live chat", async () => {
    const projectId = "1".repeat(32);
    const savedSessionId = "c".repeat(32);
    const live = view({
      settings: { ...view().settings, project_id: projectId, title: "Live synthetic chat" },
    });
    const project = {
      contract_version: "agent-catalog.v2" as const,
      project_id: projectId,
      name: "Example project",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      revision: 1,
      pinned: true,
      archived_at: null,
      session_count: 2,
      is_default: true,
    };
    const savedSession = {
      contract_version: "agent-catalog.v2" as const,
      session_id: savedSessionId,
      project_id: projectId,
      title: "Restarted synthetic chat",
      workspace: "D:\\example\\project",
      model_alias: MODEL_ALIAS,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      last_opened_at: "2040-01-01T10:00:00Z",
      revision: 1,
      pinned: false,
      archived_at: null,
      history_state: "memory_only" as const,
      retention_policy: "metadata_only" as const,
      history_revision: 0,
      last_event_seq: 0,
      turn_count: 0,
      conversation_available: false,
      lineage: null,
    };
    const liveCatalogSession = {
      ...savedSession,
      session_id: SESSION,
      title: "Live synthetic chat",
      conversation_available: true,
      lineage: null,
    };
    const transport = {
      ...sessionTransport(),
      listAgentSessions: vi.fn(async () => [live]),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [project] })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: [liveCatalogSession, savedSession],
      })),
      updateAgentCatalogSession: vi.fn(async () => savedSession),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
    };

    render(<AgentPage transport={transport} />);
    await screen.findByLabelText("Message to the agent", {}, { timeout: 5_000 });
    fireEvent.click(await screen.findByRole("button", { name: /^Restarted synthetic chat/u }, { timeout: 5_000 }));

    expect(await screen.findByRole("heading", { level: 2, name: "Restarted synthetic chat" })).toBeVisible();
    expect(screen.getByText("Metadata only · history unavailable")).toBeVisible();
    expect(screen.getByText(/navigation entry survived restart, but this chat was created with Metadata only/i)).toBeVisible();
    expect(screen.queryByLabelText("Message to the agent")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^Live synthetic chat/u }));
    expect(await screen.findByLabelText("Message to the agent", {}, { timeout: 5_000 })).toBeVisible();
  });

  it("follows an open live chat to its confirmed project and keeps that project when reselected", async () => {
    const sourceProjectId = "4".repeat(32);
    const destinationProjectId = "5".repeat(32);
    const live = view({
      settings: {
        ...view().settings,
        project_id: sourceProjectId,
        title: "Movable live chat",
      },
    });
    const sourceRecord = catalogSessionFixture(
      SESSION,
      sourceProjectId,
      "Movable live chat",
      { conversation_available: true },
    );
    const movedRecord: AgentCatalogSession = {
      ...sourceRecord,
      project_id: destinationProjectId,
      revision: 2,
      updated_at: "2040-01-01T10:02:00Z",
    };
    let moved = false;
    const transport = {
      ...sessionTransport(live),
      listAgentSessions: vi.fn(async () => [
        moved
          ? {
            ...live,
            settings: {
              ...live.settings,
              project_id: destinationProjectId,
            },
          }
          : live,
      ]),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [
          catalogProjectFixture(sourceProjectId, "Source project", moved ? 0 : 1),
          catalogProjectFixture(destinationProjectId, "Destination project", moved ? 1 : 0),
        ],
      })),
      createAgentProject: vi.fn(async () => catalogProjectFixture(sourceProjectId, "Source project", 1)),
      updateAgentProject: vi.fn(async () => catalogProjectFixture(sourceProjectId, "Source project", 1)),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async (query?: { projectId?: string }) => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: query?.projectId === destinationProjectId
          ? (moved ? [movedRecord] : [])
          : query?.projectId === sourceProjectId
            ? (moved ? [] : [sourceRecord])
            : [moved ? movedRecord : sourceRecord],
      })),
      updateAgentCatalogSession: vi.fn(async () => {
        moved = true;
        return movedRecord;
      }),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByLabelText("Message to the agent", {}, { timeout: 5_000 })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Chat actions for Movable live chat" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Movable live chat" }))
      .getByRole("button", { name: "Move to project" }));
    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByLabelText("Destination project")).toHaveValue(
      destinationProjectId,
    );
    fireEvent.click(within(moveDialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(transport.updateAgentCatalogSession).toHaveBeenCalledWith(
      SESSION,
      { expected_revision: 1, project_id: destinationProjectId },
      expect.any(AbortSignal),
    ));

    const destinationPicker = await screen.findByRole("button", {
      name: /^Destination project 1 chat/u,
    }, { timeout: 5_000 });
    await waitFor(() => expect(destinationPicker.closest("[role='listitem']"))
      .toHaveAttribute("data-current", "true"));

    fireEvent.click(screen.getByRole("button", { name: /^Source project 0 chats/u }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Source project 0 chats/u })
      .closest("[role='listitem']")).toHaveAttribute("data-current", "true"));
    fireEvent.click(screen.getByRole("button", { name: /^Destination project 1 chat/u }));
    fireEvent.click(await screen.findByRole("button", { name: /^Movable live chat ·/u }));

    await waitFor(() => expect(screen.getByRole("button", { name: /^Destination project 1 chat/u })
      .closest("[role='listitem']")).toHaveAttribute("data-current", "true"));
    expect(screen.getByLabelText("Message to the agent")).toBeVisible();
  }, 15_000);

  it("moves an open retained chat with its canonical revision before reloading and resuming", async () => {
    const sourceProjectId = "6".repeat(32);
    const destinationProjectId = "7".repeat(32);
    const savedSessionId = "8".repeat(32);
    const sourceRecord = catalogSessionFixture(
      savedSessionId,
      sourceProjectId,
      "Movable retained chat",
      {
        revision: 4,
        history_state: "durable_local",
        retention_policy: "local_history",
        conversation_available: true,
      },
    );
    const movedRecord: AgentCatalogSession = {
      ...sourceRecord,
      project_id: destinationProjectId,
      revision: 5,
      updated_at: "2040-01-01T10:02:00Z",
    };
    const recovered = view({
      session_id: savedSessionId,
      settings: {
        ...view().settings,
        workspace: sourceRecord.workspace,
        project_id: destinationProjectId,
        title: sourceRecord.title,
        retention_policy: "local_history",
      },
      recovered: true,
      authority_revalidated: false,
      recovery_state: "recovered",
    });
    let moved = false;
    const persistedEvents = vi.fn(async (projectId: string, sessionId: string) => ({
      contract_version: "local-agent.v9" as const,
      session_id: sessionId,
      events: [],
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: 0,
      first_seq: 0,
      projectId,
    }));
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [
          catalogProjectFixture(sourceProjectId, "Retained source", moved ? 0 : 1),
          catalogProjectFixture(destinationProjectId, "Retained destination", moved ? 1 : 0),
        ],
      })),
      createAgentProject: vi.fn(async () => catalogProjectFixture(sourceProjectId, "Retained source", 1)),
      updateAgentProject: vi.fn(async () => catalogProjectFixture(sourceProjectId, "Retained source", 1)),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async (query?: { projectId?: string }) => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: query?.projectId === destinationProjectId
          ? (moved ? [movedRecord] : [])
          : query?.projectId === sourceProjectId
            ? (moved ? [] : [sourceRecord])
            : [moved ? movedRecord : sourceRecord],
      })),
      updateAgentCatalogSession: vi.fn(async () => {
        moved = true;
        return movedRecord;
      }),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      getAgentPersistedEvents: persistedEvents,
      resumeAgentSession: vi.fn(async () => recovered),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByText("Saved locally · 0 turns", {}, { timeout: 5_000 })).toBeVisible();
    await waitFor(() => expect(persistedEvents).toHaveBeenCalledWith(
      sourceProjectId,
      savedSessionId,
      0,
      expect.any(AbortSignal),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Chat actions for Movable retained chat" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Movable retained chat" }))
      .getByRole("button", { name: "Move to project" }));
    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByLabelText("Destination project")).toHaveValue(
      destinationProjectId,
    );
    fireEvent.click(within(moveDialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(persistedEvents).toHaveBeenCalledWith(
      destinationProjectId,
      savedSessionId,
      0,
      expect.any(AbortSignal),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Resume chat" }));
    await waitFor(() => expect(transport.resumeAgentSession).toHaveBeenCalledWith(
      destinationProjectId,
      savedSessionId,
      { expected_catalog_revision: 5, expected_history_revision: 0 },
    ));
  });

  it("does not change the visible project when a background chat is moved", async () => {
    const sourceProjectId = "9".repeat(32);
    const destinationProjectId = "b".repeat(32);
    const backgroundSessionId = "c".repeat(32);
    const live = view({
      settings: {
        ...view().settings,
        project_id: sourceProjectId,
        title: "Open foreground chat",
      },
    });
    const liveRecord = catalogSessionFixture(
      SESSION,
      sourceProjectId,
      "Open foreground chat",
      { conversation_available: true },
    );
    const background = catalogSessionFixture(
      backgroundSessionId,
      sourceProjectId,
      "Background chat",
    );
    const movedBackground: AgentCatalogSession = {
      ...background,
      project_id: destinationProjectId,
      revision: 2,
    };
    let moved = false;
    const transport = {
      ...sessionTransport(live),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [
          catalogProjectFixture(sourceProjectId, "Foreground project", moved ? 1 : 2),
          catalogProjectFixture(destinationProjectId, "Background destination", moved ? 1 : 0),
        ],
      })),
      createAgentProject: vi.fn(async () => catalogProjectFixture(sourceProjectId, "Foreground project", 2)),
      updateAgentProject: vi.fn(async () => catalogProjectFixture(sourceProjectId, "Foreground project", 2)),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async (query?: { projectId?: string }) => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: query?.projectId === destinationProjectId
          ? (moved ? [movedBackground] : [])
          : [liveRecord, ...(moved ? [] : [background])],
      })),
      updateAgentCatalogSession: vi.fn(async () => {
        moved = true;
        return movedBackground;
      }),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByLabelText("Message to the agent", {}, { timeout: 5_000 })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Chat actions for Background chat" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Background chat" }))
      .getByRole("button", { name: "Move to project" }));
    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByLabelText("Destination project")).toHaveValue(
      destinationProjectId,
    );
    fireEvent.click(within(moveDialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(transport.updateAgentCatalogSession).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("button", { name: /^Foreground project 1 chat/u })
      .closest("[role='listitem']")).toHaveAttribute("data-current", "true"), { timeout: 5_000 });
    expect(screen.getByRole("heading", { name: "Open foreground chat", level: 1 })).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toBeVisible();
  });

  it("reconciles a retained chat title from the canonical rename response", async () => {
    const projectId = "d".repeat(32);
    const sessionId = "e".repeat(32);
    const project = catalogProjectFixture(projectId, "Rename project", 1);
    let record = catalogSessionFixture(sessionId, projectId, "Original retained title");
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [project],
      })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: [record],
      })),
      updateAgentCatalogSession: vi.fn(async (_sessionId: string, request: UpdateAgentCatalogSession) => {
        record = {
          ...record,
          title: request.title ?? record.title,
          revision: record.revision + 1,
          updated_at: "2040-01-01T10:02:00Z",
        };
        return record;
      }),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByRole("heading", {
      level: 2,
      name: "Original retained title",
    }, { timeout: 5_000 })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Chat actions for Original retained title" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Chat actions for Original retained title" }))
      .getByRole("button", { name: "Rename" }));
    const renameDialog = await screen.findByRole("dialog", { name: "Rename chat" });
    fireEvent.change(within(renameDialog).getByLabelText("Chat name"), {
      target: { value: "Canonical retained title" },
    });
    fireEvent.click(within(renameDialog).getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("heading", {
      level: 2,
      name: "Canonical retained title",
    })).toBeVisible();
    expect(screen.getByRole("heading", {
      level: 1,
      name: "Canonical retained title",
    })).toBeVisible();
  });

  it("reconciles archive and restore without refetching unchanged retained history", async () => {
    const projectId = "f".repeat(32);
    const sessionId = "1".repeat(31) + "0";
    const project = catalogProjectFixture(projectId, "Archive project", 1);
    let record = catalogSessionFixture(sessionId, projectId, "Archivable retained chat", {
      history_state: "durable_local",
      retention_policy: "local_history",
      conversation_available: true,
    });
    const persistedEvents = vi.fn(async (_projectId: string, selectedSessionId: string) => ({
      contract_version: "local-agent.v9" as const,
      session_id: selectedSessionId,
      events: [],
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: 0,
      first_seq: 0,
    }));
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [project],
      })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async (query?: { includeArchived?: boolean }) => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: record.archived_at && !query?.includeArchived ? [] : [record],
      })),
      updateAgentCatalogSession: vi.fn(async (_sessionId: string, request: UpdateAgentCatalogSession) => {
        record = {
          ...record,
          archived_at: request.archived === undefined || request.archived === null
            ? record.archived_at
            : request.archived ? "2040-01-01T10:03:00Z" : null,
          revision: record.revision + 1,
          updated_at: "2040-01-01T10:03:00Z",
        };
        return record;
      }),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      getAgentPersistedEvents: persistedEvents,
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByText("Saved locally · 0 turns", {}, { timeout: 5_000 })).toBeVisible();
    await waitFor(() => expect(persistedEvents).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume chat" })).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Chat actions for Archivable retained chat" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Archivable retained chat" }))
      .getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("button", { name: "Restore chat before resuming" })).toBeDisabled();
    expect(persistedEvents).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("button", {
      name: "Chat actions for Archivable retained chat",
    })).toBeNull());

    fireEvent.click(screen.getByLabelText("Show archived"));
    fireEvent.click(await screen.findByRole("button", { name: "Chat actions for Archivable retained chat" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Archivable retained chat" }))
      .getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume chat" })).toBeEnabled());
    expect(persistedEvents).toHaveBeenCalledOnce();
  }, 15_000);

  it("clears a deleted selected retained chat and removes every stale action", async () => {
    const projectId = "2".repeat(32);
    const sessionId = "3".repeat(32);
    const project = catalogProjectFixture(projectId, "Delete project", 1);
    const record = catalogSessionFixture(sessionId, projectId, "Delete selected retained chat", {
      history_state: "durable_local",
      retention_policy: "local_history",
      conversation_available: true,
    });
    let deleted = false;
    const transport = {
      ...sessionTransport(),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [catalogProjectFixture(projectId, "Delete project", deleted ? 0 : 1)],
      })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: deleted ? [] : [record],
      })),
      updateAgentCatalogSession: vi.fn(async () => record),
      deleteAgentCatalogSession: vi.fn(async () => {
        deleted = true;
      }),
      getAgentPersistedEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        session_id: sessionId,
        events: [],
        running: false,
        closing: false,
        stopping: false,
        cleanup_unconfirmed: false,
        pending_approval_id: null,
        last_seq: 0,
        first_seq: 0,
      })),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByText("Saved locally · 0 turns", {}, { timeout: 5_000 })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Chat actions for Delete selected retained chat" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Chat actions for Delete selected retained chat" }))
      .getByRole("button", { name: "Delete" }));
    const deleteDialog = await screen.findByRole("dialog", { name: "Delete chat" });
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Agent workspace" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Resume chat" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Export JSON" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Fork chat" })).toBeNull();
    expect(screen.queryByText("Saved locally · 0 turns")).toBeNull();
  });

  it("preserves the foreground live chat when a background retained record is deleted", async () => {
    const projectId = "4".repeat(31) + "0";
    const backgroundSessionId = "5".repeat(31) + "0";
    const live = view({
      settings: {
        ...view().settings,
        project_id: projectId,
        title: "Deletion foreground chat",
      },
    });
    const liveRecord = catalogSessionFixture(
      SESSION,
      projectId,
      "Deletion foreground chat",
      { conversation_available: true },
    );
    const background = catalogSessionFixture(
      backgroundSessionId,
      projectId,
      "Delete background chat",
    );
    let deleted = false;
    const project = catalogProjectFixture(projectId, "Deletion foreground project", 2);
    const transport = {
      ...sessionTransport(live),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [catalogProjectFixture(projectId, "Deletion foreground project", deleted ? 1 : 2)],
      })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: [liveRecord, ...(deleted ? [] : [background])],
      })),
      updateAgentCatalogSession: vi.fn(async () => background),
      deleteAgentCatalogSession: vi.fn(async () => {
        deleted = true;
      }),
    };

    render(<AgentPage transport={transport} />);
    expect(await screen.findByLabelText("Message to the agent", {}, { timeout: 5_000 })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Chat actions for Delete background chat" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Delete background chat" }))
      .getByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Delete chat" }))
      .getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(transport.deleteAgentCatalogSession).toHaveBeenCalledOnce());
    expect(screen.getByRole("heading", { level: 1, name: "Deletion foreground chat" })).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toBeVisible();
    expect(screen.queryByRole("heading", { level: 1, name: "Agent workspace" })).toBeNull();
  });

  it("reopens retained history, resumes without authority, then requires native revalidation", async () => {
    const projectId = "1".repeat(32);
    const savedSessionId = "c".repeat(32);
    const turnId = "e".repeat(32);
    const project = {
      contract_version: "agent-catalog.v2" as const,
      project_id: projectId,
      name: "Saved project",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      revision: 1,
      pinned: true,
      archived_at: null,
      session_count: 1,
      is_default: true,
    };
    const savedSession: AgentCatalogSession = {
      contract_version: "agent-catalog.v2",
      session_id: savedSessionId,
      project_id: projectId,
      title: "Saved synthetic chat",
      workspace: "D:\\example\\saved-project",
      model_alias: MODEL_ALIAS,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      last_opened_at: "2040-01-01T10:00:00Z",
      revision: 2,
      pinned: false,
      archived_at: null,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 3,
      last_event_seq: 3,
      turn_count: 1,
      conversation_available: true,
      lineage: null,
    };
    const retainedEvents = [
      event(1, "user", { text: "Synthetic retained request.", turn_id: turnId }),
      event(2, "assistant", { text: "Synthetic retained answer.", turn_id: turnId }),
      event(3, "done", {
        turn_id: turnId,
        turn_summary: exampleAgentTurn({
          turn_id: turnId,
          tools_requested: 0,
          tools_succeeded: 0,
          writes: [],
        }),
      }),
    ];
    const retainedPage: AgentEvents = {
      contract_version: "local-agent.v9",
      session_id: savedSessionId,
      events: retainedEvents,
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: 3,
      first_seq: 1,
    };
    const recovered = view({
      session_id: savedSessionId,
      settings: {
        ...view().settings,
        workspace: savedSession.workspace,
        project_id: projectId,
        model_alias: MODEL_ALIAS,
        title: savedSession.title,
        retention_policy: "local_history",
        allow_writes: false,
        allow_commands: false,
        allow_web: false,
      },
      last_seq: 3,
      turns: 1,
      history_revision: 3,
      recovered: true,
      authority_revalidated: false,
      recovery_state: "recovered",
    });
    const transport = {
      ...sessionTransport(),
      getAgentEvents: vi.fn(async () => retainedPage),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [project] })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: [savedSession],
      })),
      getAgentCatalogSession: vi.fn(async () => savedSession),
      updateAgentCatalogSession: vi.fn(async () => savedSession),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      getAgentPersistedEvents: vi.fn(async () => retainedPage),
      listAgentArtifacts: vi.fn(async () => ({
        contract_version: "agent-artifact.v3" as const,
        project_id: projectId,
        session_id: savedSessionId,
        view: "active" as const,
        counts: { active: 1, archived: 0, removed: 0, total: 1 },
        artifacts: [{
          contract_version: "agent-artifact.v3" as const,
          artifact_id: "7".repeat(32),
          project_id: projectId,
          session_id: savedSessionId,
          title: "synthetic-report.md",
          kind: "markdown" as const,
          path: "docs/synthetic-report.md",
          created_at: "2040-01-01T10:00:00Z",
          updated_at: "2040-01-01T10:00:00Z",
          revision: 1,
          version_count: 1,
          availability: "unchecked" as const,
          lifecycle_state: "active" as const,
          archived_at: null,
          removed_at: null,
          latest_version: {
            contract_version: "agent-artifact.v3" as const,
            version_id: "8".repeat(32),
            artifact_id: "7".repeat(32),
            version_number: 1,
            created_at: "2040-01-01T10:00:00Z",
            path: "docs/synthetic-report.md",
            media_type: "text/markdown; charset=utf-8",
            preview_kind: "text" as const,
            provenance: "reviewed_write" as const,
            sha256: "9".repeat(64),
            byte_size: 120,
            source_turn_id: turnId,
            source_event_seq: 2,
          },
        }],
      })),
      getAgentArtifact: vi.fn(),
      getAgentArtifactContent: vi.fn(),
      updateAgentArtifact: vi.fn(),
      removeAgentArtifact: vi.fn(),
      resumeAgentSession: vi.fn(async () => recovered),
      revalidateAgentAuthority: vi.fn(async (_sessionId: string, request: { allow_writes: boolean }) => ({
        ...recovered,
        authority_revalidated: true,
        settings: { ...recovered.settings, allow_writes: request.allow_writes },
      })),
    };

    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByRole(
      "button",
      { name: /^Saved synthetic chat/u },
      { timeout: 5_000 },
    ));

    expect(await screen.findByText("Saved locally · 1 turn")).toBeVisible();
    expect(await screen.findByText("Synthetic retained request.")).toBeVisible();
    expect(screen.getByText("Synthetic retained answer.")).toBeVisible();
    const artifactTitle = await screen.findByText("synthetic-report.md");
    expect(artifactTitle).toBeVisible();
    expect(artifactTitle.closest(".agent__log--retained")).not.toBeNull();
    expect(screen.getByText("Reviewed write · event 2 · v1 · rev 1 · 120 B")).toBeVisible();
    const turnDetails = screen.getByLabelText("Turn 1 details").closest("details");
    expect(turnDetails).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: "Go to producing turn for synthetic-report.md" }));
    await waitFor(() => expect(turnDetails).toHaveAttribute("open"));
    expect(turnDetails).toHaveFocus();
    expect(screen.getByText(/Approval IDs, approval decisions, raw tool arguments\/output/)).toBeVisible();
    expect(screen.queryByLabelText("Message to the agent")).toBeNull();
    expect(transport.getAgentPersistedEvents).toHaveBeenCalledWith(
      projectId,
      savedSessionId,
      0,
      expect.anything(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Resume chat" }));
    await waitFor(() => expect(transport.resumeAgentSession).toHaveBeenCalledWith(
      projectId,
      savedSessionId,
      { expected_catalog_revision: 2, expected_history_revision: 3 },
    ));
    expect(await screen.findByRole("heading", { name: "Revalidate this workspace before changing it" })).toBeVisible();
    expect(screen.getByText("Recovered · protected actions off")).toBeVisible();
    expect(recovered.settings.allow_writes).toBe(false);
    expect(recovered.settings.allow_commands).toBe(false);
    expect(recovered.settings.allow_web).toBe(false);

    fireEvent.click(screen.getByRole("checkbox", { name: "File writes" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm and revalidate" }));
    await waitFor(() => expect(transport.revalidateAgentAuthority).toHaveBeenCalledWith(
      savedSessionId,
      {
        expected_catalog_revision: 2,
        allow_writes: true,
        allow_commands: false,
        allow_web: false,
      },
    ));
    expect(screen.queryByRole("heading", { name: "Revalidate this workspace before changing it" })).toBeNull();
  }, 20_000);

  it("exports the exact retained revision through a connected local download and delayed cleanup", async () => {
    const projectId = "2".repeat(32);
    const sessionId = "3".repeat(32);
    const project = catalogProjectFixture(projectId, "Export project", 1);
    const saved = catalogSessionFixture(sessionId, projectId, "Exportable retained chat", {
      revision: 4,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 7,
      conversation_available: true,
    });
    const exportAgentHistory = vi.fn(async () => historyExportFixture(saved));
    const transport = retainedCatalogTransport(project, [saved], { exportAgentHistory });
    const createObjectURL = vi.fn(() => "blob:synthetic-agent-export");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    let clickedLink: HTMLAnchorElement | null = null;
    let connectedAtClick = false;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click(this: HTMLAnchorElement) {
      clickedLink = this;
      connectedAtClick = this.isConnected;
    });

    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByRole(
      "button",
      { name: /^Exportable retained chat/u },
      { timeout: 5_000 },
    ));
    expect(await screen.findByText("Saved locally · 0 turns")).toBeVisible();

    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
      await Promise.resolve();
    });

    expect(exportAgentHistory).toHaveBeenCalledWith(
      projectId,
      sessionId,
      { expected_catalog_revision: 4, expected_history_revision: 7 },
      expect.any(AbortSignal),
    );
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(connectedAtClick).toBe(true);
    expect(clickedLink).not.toBeNull();
    const downloadedLink = clickedLink as unknown as HTMLAnchorElement;
    expect(downloadedLink.download).toBe("agent-chat-33333333.json");
    expect(downloadedLink.href).toBe("blob:synthetic-agent-export");
    expect(downloadedLink.isConnected).toBe(false);
    expect(screen.getByText("History export prepared locally.")).toBeVisible();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(999); });
    expect(revokeObjectURL).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1); });
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-agent-export");
  });

  it("reports a retained export revision conflict without creating a download", async () => {
    const projectId = "4".repeat(32);
    const sessionId = "5".repeat(32);
    const project = catalogProjectFixture(projectId, "Conflict project", 1);
    const saved = catalogSessionFixture(sessionId, projectId, "Conflicted retained chat", {
      revision: 6,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 8,
      conversation_available: true,
    });
    const exportAgentHistory = vi.fn(async () => {
      throw new TransportError("Synthetic history conflict", 409, "agent_history_revision_conflict");
    });
    const transport = retainedCatalogTransport(project, [saved], { exportAgentHistory });
    const createObjectURL = vi.fn(() => "blob:must-not-exist");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });

    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByRole(
      "button",
      { name: /^Conflicted retained chat/u },
      { timeout: 5_000 },
    ));
    expect(await screen.findByText("Saved locally · 0 turns")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));

    expect(await screen.findByText(
      "This chat changed in another window. Reopen it from the project list before exporting.",
    )).toBeVisible();
    expect(exportAgentHistory).toHaveBeenCalledWith(
      projectId,
      sessionId,
      { expected_catalog_revision: 6, expected_history_revision: 8 },
      expect.any(AbortSignal),
    );
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("cancels a pending retained export when another chat is selected and ignores the stale result", async () => {
    const projectId = "6".repeat(32);
    const firstSessionId = "7".repeat(32);
    const secondSessionId = "8".repeat(32);
    const project = catalogProjectFixture(projectId, "Ownership project", 2);
    const first = catalogSessionFixture(firstSessionId, projectId, "First export chat", {
      revision: 2,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 3,
      conversation_available: true,
    });
    const second = catalogSessionFixture(secondSessionId, projectId, "Second export chat", {
      revision: 5,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 9,
      conversation_available: true,
    });
    const firstExport = deferred<AgentHistoryExport>();
    let firstSignal: AbortSignal | undefined;
    const exportAgentHistory = vi.fn((
      _projectId: string,
      selectedSessionId: string,
      _request: { expected_catalog_revision: number; expected_history_revision: number },
      signal?: AbortSignal,
    ): Promise<AgentHistoryExport> => {
      if (selectedSessionId === firstSessionId) {
        firstSignal = signal;
        return firstExport.promise;
      }
      return Promise.resolve(historyExportFixture(second));
    });
    const transport = retainedCatalogTransport(project, [first, second], { exportAgentHistory });
    const createObjectURL = vi.fn(() => "blob:synthetic-second-export");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByRole(
      "button",
      { name: /^First export chat/u },
      { timeout: 5_000 },
    ));
    expect(await screen.findByText("Saved locally · 0 turns")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(exportAgentHistory).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Exporting…" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^Second export chat/u }));
    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "Export JSON" })).toBeEnabled());

    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
      await Promise.resolve();
    });
    expect(exportAgentHistory).toHaveBeenCalledTimes(2);
    expect(exportAgentHistory.mock.calls[1]).toEqual([
      projectId,
      secondSessionId,
      { expected_catalog_revision: 5, expected_history_revision: 9 },
      expect.any(AbortSignal),
    ]);
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(screen.getByText("History export prepared locally.")).toBeVisible();

    await act(async () => { firstExport.resolve(historyExportFixture(first)); });
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(screen.getByText("History export prepared locally.")).toBeVisible();
    act(() => { vi.advanceTimersByTime(1_000); });
    expect(revokeObjectURL).toHaveBeenCalledOnce();
  });

  it("branches at a completed turn and reuses the idempotency key after an ambiguous failure", async () => {
    const projectId = "1".repeat(32);
    const sourceSessionId = "c".repeat(32);
    const childSessionId = "d".repeat(32);
    const turnId = "e".repeat(32);
    const at = "2040-01-01T10:00:00Z";
    const project = {
      contract_version: "agent-catalog.v2" as const,
      project_id: projectId,
      name: "Branch project",
      created_at: at,
      updated_at: at,
      revision: 1,
      pinned: true,
      archived_at: null,
      session_count: 1,
      is_default: true,
    };
    const source: AgentCatalogSession = {
      contract_version: "agent-catalog.v2",
      session_id: sourceSessionId,
      project_id: projectId,
      title: "Branchable synthetic chat",
      workspace: "D:\\example\\branch-project",
      model_alias: MODEL_ALIAS,
      created_at: at,
      updated_at: at,
      last_opened_at: at,
      revision: 2,
      pinned: false,
      archived_at: null,
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 3,
      last_event_seq: 3,
      turn_count: 1,
      conversation_available: true,
      lineage: null,
    };
    const retainedEvents = [
      event(1, "user", { text: "Synthetic branch source.", turn_id: turnId }),
      event(2, "assistant", { text: "Synthetic branch answer.", turn_id: turnId }),
      event(3, "done", {
        turn_id: turnId,
        turn_summary: exampleAgentTurn({ turn_id: turnId }),
      }),
    ];
    const child: AgentCatalogSession = {
      ...source,
      session_id: childSessionId,
      title: "Branchable synthetic chat (branch)",
      revision: 1,
      lineage: {
        contract_version: "agent-session-lineage.v1",
        source_project_id: projectId,
        source_session_id: sourceSessionId,
        source_catalog_revision: 2,
        source_history_revision: 3,
        branch_event_seq: 3,
        copied_event_count: 3,
        copied_turn_count: 1,
        copied_attachment_count: 0,
        created_at: at,
      },
    };
    const fork = vi.fn()
      .mockRejectedValueOnce(new TransportError("Synthetic ambiguous failure", 503))
      .mockResolvedValueOnce({
        contract_version: "agent-session-fork.v1" as const,
        request_id: "unused-by-mock",
        idempotent_replay: true,
        session: child,
        source_tail_omitted: false,
        approvals_copied: false as const,
        mutation_authority_copied: false as const,
        pending_tool_state_copied: false as const,
        staged_attachments_copied: false as const,
        artifacts_copied: false as const,
      });
    const transport = {
      ...sessionTransport(),
      listAgentSessions: vi.fn(async () => []),
      listAgentProjects: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        projects: [project],
      })),
      createAgentProject: vi.fn(async () => project),
      updateAgentProject: vi.fn(async () => project),
      deleteAgentProject: vi.fn(async () => undefined),
      listAgentCatalogSessions: vi.fn(async () => ({
        contract_version: "agent-catalog.v2" as const,
        sessions: [source],
      })),
      updateAgentCatalogSession: vi.fn(async () => source),
      deleteAgentCatalogSession: vi.fn(async () => undefined),
      getAgentPersistedEvents: vi.fn(async (_projectId: string, sessionId: string) => ({
        contract_version: "local-agent.v9" as const,
        session_id: sessionId,
        events: retainedEvents,
        running: false,
        closing: false,
        stopping: false,
        cleanup_unconfirmed: false,
        pending_approval_id: null,
        last_seq: 3,
        first_seq: 1,
      })),
      forkAgentSession: fork,
    };

    render(<AgentPage transport={transport} />);
    fireEvent.click(await screen.findByRole(
      "button",
      { name: /^Branchable synthetic chat/u },
      { timeout: 3_000 },
    ));
    expect(await screen.findByText("Synthetic branch answer.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Branch point"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fork chat" }));
    expect(await screen.findAllByText(/branch could not be created/i)).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Fork chat" }));

    await waitFor(() => expect(fork).toHaveBeenCalledTimes(2));
    const firstRequest = fork.mock.calls[0][2];
    const secondRequest = fork.mock.calls[1][2];
    expect(firstRequest.request_id).toMatch(/^[0-9a-f]{32}$/u);
    expect(secondRequest.request_id).toBe(firstRequest.request_id);
    expect(secondRequest).toMatchObject({
      expected_catalog_revision: 2,
      expected_history_revision: 3,
      through_event_seq: 3,
      destination_project_id: null,
    });
    expect(await screen.findByRole(
      "heading",
      { name: "Branchable synthetic chat (branch)", level: 1 },
      { timeout: 3_000 },
    )).toBeVisible();
    expect(screen.getByText("Branch · 1 copied turn")).toBeVisible();
    expect(screen.queryByLabelText("Message to the agent")).toBeNull();
  });

  it("regenerates the first turn from an exact empty-history branch without rewriting the source", async () => {
    const turnId = "1".repeat(32);
    const retainedEvents = [
      event(1, "user", { text: "Generate a different synthetic answer.", turn_id: turnId }),
      event(2, "assistant", { text: "Original synthetic answer.", turn_id: turnId }),
      event(3, "done", { turn_id: turnId, turn_summary: exampleAgentTurn({ turn_id: turnId }) }),
    ];
    const harness = turnRevisionHarness(retainedEvents);
    render(<AgentPage transport={harness.transport} />);

    fireEvent.click(await screen.findByLabelText("Turn 1 details"));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate in branch" }));

    await waitFor(() => expect(harness.forkAgentSession).toHaveBeenCalledOnce());
    expect(harness.forkAgentSession).toHaveBeenCalledWith(
      harness.project.project_id,
      SESSION,
      expect.objectContaining({
        expected_catalog_revision: harness.sourceRecord.revision,
        expected_history_revision: 3,
        through_event_seq: 0,
      }),
      expect.any(AbortSignal),
    );
    await waitFor(() => expect(harness.resumeAgentSession).toHaveBeenCalledWith(
      harness.project.project_id,
      harness.childSessionId,
      { expected_catalog_revision: 1, expected_history_revision: 0 },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(harness.sendAgentMessage).toHaveBeenCalledWith(
      harness.childSessionId,
      "Generate a different synthetic answer.",
      [],
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/Regeneration started in a new branch before turn 1/u)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Retry live updates" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Revision source (branch)" })).toBeVisible();
  });

  it("retries a failed later turn from the preceding settled receipt", async () => {
    const firstTurn = "2".repeat(32);
    const failedTurn = "3".repeat(32);
    const retainedEvents = [
      event(1, "user", { text: "First synthetic request.", turn_id: firstTurn }),
      event(2, "assistant", { text: "First synthetic answer.", turn_id: firstTurn }),
      event(3, "done", { turn_id: firstTurn, turn_summary: exampleAgentTurn({ turn_id: firstTurn }) }),
      event(4, "user", { text: "Retry this fictional task.", turn_id: failedTurn }),
      event(5, "error", { text: "Synthetic runtime failure.", turn_id: failedTurn }),
      event(6, "done", {
        turn_id: failedTurn,
        turn_summary: exampleAgentTurn({
          turn_id: failedTurn,
          turn_number: 2,
          status: "failed",
          reason: "runtime_unreachable",
        }),
      }),
    ];
    const harness = turnRevisionHarness(retainedEvents);
    render(<AgentPage transport={harness.transport} />);

    fireEvent.click(await screen.findByLabelText("Turn 2 details"));
    fireEvent.click(screen.getByRole("button", { name: "Retry in branch" }));

    await waitFor(() => expect(harness.forkAgentSession).toHaveBeenCalledOnce());
    expect(harness.forkAgentSession.mock.calls[0]?.[2]).toMatchObject({ through_event_seq: 3 });
    await waitFor(() => expect(harness.sendAgentMessage).toHaveBeenCalledWith(
      harness.childSessionId,
      "Retry this fictional task.",
      [],
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/Retry started in a new branch before turn 2/u)).toBeVisible();
  });

  it("keeps the exact branch draft when regeneration cannot start its model", async () => {
    const turnId = "4".repeat(32);
    const retainedEvents = [
      event(1, "user", { text: "Preserve this synthetic retry draft.", turn_id: turnId }),
      event(2, "assistant", { text: "Original answer.", turn_id: turnId }),
      event(3, "done", { turn_id: turnId, turn_summary: exampleAgentTurn({ turn_id: turnId }) }),
    ];
    const harness = turnRevisionHarness(retainedEvents, {
      sendFailure: new TransportError("Synthetic stopped model", 409, "model_not_ready"),
    });
    render(<AgentPage transport={harness.transport} />);

    fireEvent.click(await screen.findByLabelText("Turn 1 details"));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate in branch" }));

    expect(await screen.findByText(/branch is ready and its prompt is kept, but the model is not running/u)).toBeVisible();
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Preserve this synthetic retry draft.");
    expect(harness.resumeAgentSession).toHaveBeenCalledOnce();
    expect(harness.sendAgentMessage).toHaveBeenCalledOnce();
  });

  it("aborts a pending turn revision when the user switches to another chat", async () => {
    const turnId = "5".repeat(32);
    const retainedEvents = [
      event(1, "user", { text: "Do not revise after navigation.", turn_id: turnId }),
      event(2, "assistant", { text: "Original answer.", turn_id: turnId }),
      event(3, "done", { turn_id: turnId, turn_summary: exampleAgentTurn({ turn_id: turnId }) }),
    ];
    const harness = turnRevisionHarness(retainedEvents);
    const otherSessionId = "8".repeat(32);
    const otherView = view({
      session_id: otherSessionId,
      settings: {
        ...view().settings,
        project_id: harness.project.project_id,
        title: "Other live chat",
        model_alias: MODEL_ALIAS,
      },
    });
    const otherRecord = catalogSessionFixture(otherSessionId, harness.project.project_id, "Other live chat");
    harness.transport.listAgentSessions.mockResolvedValue([harness.sourceView, otherView]);
    harness.transport.listAgentCatalogSessions.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      sessions: [harness.sourceRecord, otherRecord],
    });
    const catalogRead = deferred<AgentCatalogSession>();
    let revisionSignal: AbortSignal | undefined;
    harness.transport.getAgentCatalogSession.mockImplementation((_sessionId: string, signal?: AbortSignal) => {
      revisionSignal = signal;
      return catalogRead.promise;
    });
    render(<AgentPage transport={harness.transport} />);

    fireEvent.click(await screen.findByLabelText("Turn 1 details"));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate in branch" }));
    await waitFor(() => expect(harness.transport.getAgentCatalogSession).toHaveBeenCalledOnce());
    fireEvent.click(await screen.findByRole("button", { name: /^Other live chat/u }));
    await waitFor(() => expect(revisionSignal?.aborted).toBe(true));
    await act(async () => { catalogRead.resolve(harness.sourceRecord); });

    expect(harness.forkAgentSession).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: "Other live chat" })).toBeVisible();
  });

  it("checks a draft with conversational context without sending it, then applies the suggested rewrite", async () => {
    const priorEvents = [
      event(1, "user", { text: "Earlier request" }),
      event(2, "tool_result", { text: "private tool output must not become prompt context", tool: "read_file", ok: true }),
      event(3, "assistant", { text: "Earlier response" }),
    ];
    const current = view({ last_seq: 3, turns: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: priorEvents, running: false, pending_approval_id: null, last_seq: 3, first_seq: 1 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      checkPrompt: vi.fn(async (_request: PromptCheckRequest, _signal?: AbortSignal) => promptCheckResult()),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByText("Earlier response");

    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Update example.ts" } });
    const reviewPrompt = screen.getByRole("button", { name: "Review prompt without sending" });
    expect(reviewPrompt).toHaveTextContent("Review prompt");
    expect(reviewPrompt).toHaveTextContent("Optional · no agent send");
    expect(reviewPrompt).toHaveAttribute("title", "Review this draft and suggest a clearer version. This does not send it to the agent.");
    fireEvent.click(reviewPrompt);

    await waitFor(
      () => expect(transport.checkPrompt).toHaveBeenCalledTimes(1),
      { timeout: 5_000 },
    );
    const request = transport.checkPrompt.mock.calls[0][0];
    expect(request).toMatchObject({
      prompt: "Update example.ts",
      prior_messages: [
        { role: "user", content: "Earlier request" },
        { role: "assistant", content: "Earlier response" },
      ],
      session_id: null,
      provider: "other",
      agent_model: "orca27b-iq3m",
      want_commentary: true,
    });
    expect(transport.sendAgentMessage).not.toHaveBeenCalled();
    expect(await screen.findByText("Before the agent acts")).toBeTruthy();
    expect(screen.getByText("a checkable pass condition")).toBeTruthy();
    expect(screen.getByText(/Name the exact test command/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Use suggested prompt" }));
    expect((screen.getByLabelText("Message to the agent") as HTMLTextAreaElement).value).toBe("Update example.ts and run the focused test; report the changed files and result.");
    expect(screen.queryByText("Before the agent acts")).toBeNull();
    expect(screen.getByText(/Check it again to validate/)).toBeTruthy();
  });

  it("aborts a stale prompt check when the draft changes and never renders its late result", async () => {
    let resolveCheck: ((result: PromptCheckResult) => void) | undefined;
    let receivedSignal: AbortSignal | undefined;
    const current = view();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      checkPrompt: vi.fn((_request: unknown, signal?: AbortSignal) => {
        receivedSignal = signal;
        return new Promise<PromptCheckResult>((resolve) => { resolveCheck = resolve; });
      }),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByLabelText("Message to the agent");
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "First draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Review prompt without sending" }));
    await waitFor(() => expect(transport.checkPrompt).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Second draft" } });
    expect(receivedSignal?.aborted).toBe(true);
    resolveCheck?.(promptCheckResult());
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByText("Before the agent acts")).toBeNull();
  });

  it("keeps prompt-check failures content-free", async () => {
    const current = view();
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({ contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: SESSION, events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })),
      decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(),
      checkPrompt: vi.fn(async () => { throw new Error("synthetic-secret-canary"); }),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByLabelText("Message to the agent");
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Review example.ts" } });
    fireEvent.click(screen.getByRole("button", { name: "Review prompt without sending" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The prompt check did not run. Your draft was not changed.");
    expect(document.body.textContent).not.toContain("synthetic-secret-canary");
  });

  it("caps failed live-stream reconnects and requires an explicit retry", async () => {
    vi.useFakeTimers();
    const current = view({ running: true, turns: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(async () => current),
      streamAgentEvents: vi.fn(async () => { throw new Error("synthetic stream failure"); }),
    };
    try {
      render(<AgentPage transport={transport} />);
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(1);

      for (let attempt = 1; attempt < 5; attempt += 1) {
        await act(async () => { await vi.runOnlyPendingTimersAsync(); });
      }
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(5);
      expect(screen.getByText(/Live updates paused after repeated connection failures/)).toBeTruthy();

      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(5);

      fireEvent.click(screen.getByRole("button", { name: "Retry live updates" }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(6);
    } finally {
      vi.useRealTimers();
    }
  });

  it("treats unexpected stream EOF during a running turn as a bounded failure", async () => {
    vi.useFakeTimers();
    const current = view({ running: true, turns: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(async () => current),
      streamAgentEvents: vi.fn(async () => undefined),
    };
    try {
      render(<AgentPage transport={transport} />);
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      for (let attempt = 1; attempt < 5; attempt += 1) {
        await act(async () => { await vi.runOnlyPendingTimersAsync(); });
      }
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(5);
      expect(screen.getByText(/Live updates paused after repeated connection failures/)).toBeTruthy();
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(5);
    } finally {
      vi.useRealTimers();
    }
  });

  it("counts repeated equal-head running snapshots as one stalled reconnect outage", async () => {
    vi.useFakeTimers();
    const current = view({ running: true, turns: 1, last_seq: 1 });
    const transport = {
      ...workspaceMethods(),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(), getAgentSession: vi.fn(), deleteAgentSession: vi.fn(), sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(), decideAgentApproval: vi.fn(), stopAgentSession: vi.fn(async () => current),
      streamAgentEvents: vi.fn(async (_id: string, after: number, onPage: (page: AgentEvents) => void) => {
        onPage({
          contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
          session_id: SESSION,
          events: after === 0 ? [event(1, "status", { text: "Synthetic response is still running." })] : [],
          running: true,
          pending_approval_id: null,
          last_seq: 1,
          first_seq: 1,
        });
        throw new Error("synthetic disconnect after a valid snapshot");
      }),
    };
    try {
      render(<AgentPage transport={transport} />);
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(1);

      for (let attempt = 1; attempt < 5; attempt += 1) {
        await act(async () => { await vi.runOnlyPendingTimersAsync(); });
      }
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(5);
      expect(screen.getByText(/Live updates paused after repeated connection failures/)).toBeTruthy();

      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(transport.streamAgentEvents).toHaveBeenCalledTimes(5);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps tool decisions and new mutation scopes disabled without native presence", async () => {
    const pendingEvent = event(1, "approval_required", {
      tool: "write_file",
      arguments: {
        file_count: 2,
        create_count: 1,
        edit_count: 1,
        paths: ["src/example.py", "src/helper.py"],
        transaction: "failure_atomic_create_edit",
      },
      approval_id: APPROVAL,
      preview: "Transaction file 1/2 [edit]: src/example.py\n--- a/src/example.py\n+++ b/src/example.py\n-old\n+new\n\nTransaction file 2/2 [create]: src/helper.py\n--- a/src/helper.py\n+++ b/src/helper.py\n+new",
    });
    const current = view({ running: true, pending_approval_id: APPROVAL, last_seq: 1 });
    const transport = {
      ...workspaceMethods(),
      getUserPresenceCapability: vi.fn(async () => ({
        contract_version: "native-user-presence-capability-v1" as const,
        confirmation_available: false,
        mode: "unavailable" as const,
      })),
      listAgentSessions: vi.fn(async () => [current]),
      createAgentSession: vi.fn(),
      getAgentSession: vi.fn(async () => current),
      deleteAgentSession: vi.fn(),
      sendAgentMessage: vi.fn(),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false,
        session_id: SESSION,
        events: [pendingEvent],
        running: true,
        pending_approval_id: APPROVAL,
        last_seq: 1,
        first_seq: 1,
      })),
      decideAgentApproval: vi.fn(),
      stopAgentSession: vi.fn(async () => current),
    };
    render(<AgentPage sessionId={SESSION} transport={transport} />);

    const dialog = await screen.findByRole("alertdialog", { name: "Approval needed" });
    expect(dialog).toHaveTextContent(/cannot be decided until the app is opened/i);
    expect(dialog).toHaveTextContent("2 files · 1 create · 1 edit: src/example.py, src/helper.py");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    await waitFor(() => expect(screen.getByLabelText(/May write files/i)).not.toBeChecked());
    expect(screen.getByLabelText(/May write files/i)).toBeDisabled();
    expect(screen.getByLabelText(/May run commands/i)).toBeDisabled();
    expect(screen.getByLabelText(/Web fetch unavailable/i)).toBeDisabled();
    expect(transport.decideAgentApproval).not.toHaveBeenCalled();
  });

  it("sends a verified image-only request by staged identity and clears it only after success", async () => {
    const current = view();
    const runtime = runtimeCoordinator(MODEL_ALIAS);
    runtime.capabilities.vision = true;
    const admitted = stagedImageAttachment();
    const transport = {
      ...sessionTransport(current),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(),
      stopLocalRuntime: vi.fn(),
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(async () => admitted),
      deleteAgentAttachment: vi.fn(),
      getAgentAttachmentContent: vi.fn(),
      sendAgentMessage: vi.fn(async () => view({ turns: 1 })),
    };
    render(<AgentPage transport={transport} />);

    await screen.findByLabelText("Message to the agent");
    const attachMedia = await screen.findByRole("button", { name: "Attach" });
    await waitFor(() => expect(attachMedia).toBeEnabled());
    fireEvent.click(attachMedia);
    const addImage = screen.getByRole("button", { name: "Add image" });
    await waitFor(() => expect(addImage).toBeEnabled());
    const file = new File([new Uint8Array([1, 2, 3])], "example-diagram.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Choose images"), { target: { files: [file] } });
    expect(await screen.findByText("example-diagram.png")).toBeVisible();

    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeEnabled();
    fireEvent.click(send);

    await waitFor(() => expect(transport.sendAgentMessage).toHaveBeenCalledWith(
      SESSION,
      "",
      [admitted.attachment_id],
    ));
    await waitFor(() => expect(screen.queryByText("example-diagram.png")).toBeNull());
  });

  it("preserves text and staged media when a capability recheck rejects the send", async () => {
    const current = view();
    const runtime = runtimeCoordinator(MODEL_ALIAS);
    runtime.capabilities.vision = true;
    const admitted = stagedImageAttachment();
    const transport = {
      ...sessionTransport(current),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(),
      stopLocalRuntime: vi.fn(),
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(async () => admitted),
      deleteAgentAttachment: vi.fn(),
      getAgentAttachmentContent: vi.fn(),
      sendAgentMessage: vi.fn(async () => { throw new TransportError("synthetic model change", 409, "agent_attachment_model_changed"); }),
    };
    render(<AgentPage transport={transport} />);
    await screen.findByLabelText("Message to the agent");
    const attachMedia = await screen.findByRole("button", { name: "Attach" });
    await waitFor(() => expect(attachMedia).toBeEnabled());
    fireEvent.click(attachMedia);
    const addImage = screen.getByRole("button", { name: "Add image" });
    await waitFor(() => expect(addImage).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Choose images"), {
      target: { files: [new File([new Uint8Array([1])], "example-diagram.png", { type: "image/png" })] },
    });
    await screen.findByText("example-diagram.png");
    fireEvent.change(screen.getByLabelText("Message to the agent"), { target: { value: "Inspect this image" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("served model changed");
    expect(screen.getByLabelText("Message to the agent")).toHaveValue("Inspect this image");
    expect(screen.getByText("example-diagram.png")).toBeVisible();
  });

  it("blocks a retained attachment from another model before message admission", async () => {
    const current = view();
    const runtime = runtimeCoordinator(MODEL_ALIAS);
    runtime.capabilities.vision = true;
    const mismatched = { ...stagedImageAttachment(), model_alias: "synthetic-previous-model" };
    const transport = {
      ...sessionTransport(current),
      getLocalRuntime: vi.fn(async () => runtime),
      switchLocalRuntime: vi.fn(),
      stopLocalRuntime: vi.fn(),
      listAgentAttachments: vi.fn(async () => ({
        contract_version: "agent-attachment.v2" as const,
        session_id: SESSION,
        attachments: [mismatched],
      })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
      getAgentAttachmentContent: vi.fn(),
    };
    render(<AgentPage transport={transport} />);

    const composer = await screen.findByLabelText("Message to the agent");
    await waitFor(() => expect(composer).toBeEnabled());
    expect(await screen.findByRole("alert")).toHaveTextContent("belongs to a different model");
    fireEvent.change(composer, { target: { value: "Inspect the retained image" } });

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(transport.sendAgentMessage).not.toHaveBeenCalled();
  });

  it("renders payload-free sent attachment metadata even when a user message has no text", async () => {
    const current = view({ last_seq: 1, turns: 1 });
    const attachment = imageMessageAttachment();
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: [event(1, "user", { text: "", attachments: [attachment] })],
        running: false,
        pending_approval_id: null,
        first_seq: 1,
        last_seq: 1,
      })),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText("example-diagram.png")).toBeVisible();
    expect(screen.getByRole("list", { name: "Message attachments" })).toHaveTextContent(
      "1 × 1 · 1 KB · context cost unknown",
    );
  });

  it("renders truthful projected-document metadata without exposing attachment bytes", async () => {
    const current = view({ last_seq: 1, turns: 1 });
    const attachment = documentMessageAttachment();
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: [event(1, "user", { text: "", attachments: [attachment] })],
        running: false,
        pending_approval_id: null,
        first_seq: 1,
        last_seq: 1,
      })),
    };
    render(<AgentPage transport={transport} />);

    expect(await screen.findByText("example-notes.md")).toBeVisible();
    const list = screen.getByRole("list", { name: "Message attachments" });
    expect(list).toHaveTextContent("Document");
    expect(list).toHaveTextContent("MARKDOWN · 1024 projected characters · truncated");
    expect(list).not.toHaveTextContent("data:");
  });

  it("binds compact MCP status and Store project admission to the exact live-chat project", async () => {
    const projectId = "f".repeat(32);
    const snapshot = syntheticMcpManagedToolSnapshot();
    const probed = syntheticMcpManagedProbeReceipt().server;
    const binding = {
      project_id: projectId,
      project_name: "Synthetic project",
      enabled: true,
      required_permissions: probed.required_permissions,
      granted_permissions: probed.required_permissions,
      admitted_tool_ids: [snapshot.tools[0].tool_id],
      tool_snapshot_id: snapshot.snapshot_id,
      admission_state: "admitted" as const,
      effective_state: "inactive_host_unavailable" as const,
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      revision: 2,
    };
    const managed = syntheticMcpManagedServer({
      ...probed,
      project_bindings: [binding],
      tool_snapshot: snapshot,
      tool_review_state: "reviewable",
    });
    const current = view({
      settings: { ...view().settings, project_id: projectId },
    });
    const listMcpManagedServers = vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed]));
    const getMcpManagedProjectRuntime = vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime({
      project_id: projectId,
    }));
    const transport = {
      ...sessionTransport(current),
      getMcpManagedProjectRuntime,
      getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
      listAgentProjects: vi.fn().mockResolvedValue({
        contract_version: "agent-catalog.v2" as const,
        projects: [catalogProjectFixture(projectId, "Synthetic project", 1)],
      }),
      listMcpManagedServers,
    };
    render(<AgentPage transport={transport} />);

    fireEvent.click(await screen.findByRole("button", { name: "Project tools" }));
    const settings = await screen.findByRole("dialog", { name: "Agent settings" });
    const projectTools = within(settings).getByText("Project tools");
    fireEvent.click(projectTools);
    expect(await within(settings).findByText("1 ready")).toBeVisible();
    expect(getMcpManagedProjectRuntime).toHaveBeenCalledWith(projectId, expect.any(AbortSignal));
    expect(within(settings).getByText("mcp_99999999_synthetic_read")).toBeVisible();
    fireEvent.click(within(settings).getByRole("button", { name: "Manage in MCP Store" }));

    expect(within(settings).getByRole("tab", { name: "MCP Store" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(await within(settings).findByRole("tab", { name: "Managed servers" }));
    const managedRegion = await within(settings).findByRole("region", { name: "Managed MCP servers" });
    fireEvent.click(within(managedRegion).getByRole("button", { name: /Synthetic Files/ }));
    const projectSelector = await within(settings).findByRole("combobox", { name: "Agent project" });
    await waitFor(() => expect(projectSelector).toHaveValue(projectId));
    expect(within(settings).getByText(/Editing the active chat project/)).toBeVisible();
  });

  it("keeps the trusted MCP acceptance receipt when Agent settings unmount the Store", async () => {
    const projectId = "f".repeat(32);
    const planned = syntheticMcpManagedServer({
      option_label: "MCPB release",
      registry_type: "mcpb",
      package_identifier: "https://example.invalid/synthetic.mcpb",
      runtime_hint: "node",
      requirements: [],
      revision: 2,
      install_action: "available_native_confirmation_required",
    });
    const current = view({
      settings: { ...view().settings, project_id: projectId },
    });
    const transport = {
      ...sessionTransport(current),
      listAgentProjects: vi.fn().mockResolvedValue({
        contract_version: "agent-catalog.v2" as const,
        projects: [catalogProjectFixture(projectId, "Synthetic project", 1)],
      }),
      listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([planned])),
    };
    render(<AgentPage transport={transport} />);

    fireEvent.click(await screen.findByRole("button", { name: "Project tools" }));
    let settings = await screen.findByRole("dialog", { name: "Agent settings" });
    fireEvent.click(within(settings).getByRole("tab", { name: "MCP Store" }));
    fireEvent.click(await within(settings).findByRole("tab", { name: "Managed servers" }));
    let managedRegion = await within(settings).findByRole("region", { name: "Managed MCP servers" });
    fireEvent.click(within(managedRegion).getByRole("button", { name: /Synthetic Files/ }));
    const proof = await within(settings).findByRole("region", { name: "Trusted MCP lifecycle acceptance" });
    fireEvent.click(within(proof).getByRole("button", { name: "Begin trusted MCP proof" }));
    expect(within(proof).getByText("In progress")).toBeVisible();

    fireEvent.click(within(settings).getByRole("button", { name: "Close agent settings" }));
    expect(screen.queryByRole("dialog", { name: "Agent settings" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Project tools" }));
    settings = await screen.findByRole("dialog", { name: "Agent settings" });
    fireEvent.click(within(settings).getByRole("tab", { name: "MCP Store" }));
    fireEvent.click(await within(settings).findByRole("tab", { name: "Managed servers" }));
    managedRegion = await within(settings).findByRole("region", { name: "Managed MCP servers" });
    fireEvent.click(within(managedRegion).getByRole("button", { name: /Synthetic Files/ }));
    const restoredProof = await within(settings).findByRole("region", { name: "Trusted MCP lifecycle acceptance" });
    expect(within(restoredProof).getByText("In progress")).toBeVisible();
    expect(within(restoredProof).getByText(/normal Install control/)).toBeVisible();
  });

  it("keeps the external-controller acceptance receipt when Agent settings unmount", async () => {
    const projectId = "6".repeat(32);
    const connectionId = "7".repeat(32);
    const current = view({
      settings: { ...view().settings, project_id: projectId },
    });
    const connection: AgentMcpConnection = {
      contract_version: "agent-mcp-connection.v4",
      connection_id: connectionId,
      label: "Synthetic page-owned controller",
      client_kind: "other",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:00:00Z",
      expires_at: "2040-04-01T10:00:00Z",
      last_used_at: null,
      last_tool_at: null,
      last_tool_name: null,
      last_tool_outcome: null,
      last_tool_source: null,
      last_auth_rejected_at: null,
      revoked_at: null,
      revision: 1,
      credential_revision: 1,
      allow_model_lifecycle: false,
      scope: {
        contract_version: "agent-mcp-scope.v1",
        state: "bound",
        project_id: projectId,
        project_name: "Synthetic page-owned project",
        catalog_access: "project_only",
        chat_access: "project_only",
        workspace_access: "project_only",
        native_approval_inherited: false,
      },
      state: "active",
    };
    const connections: AgentMcpConnectionList = {
      contract_version: "agent-mcp-management.v2",
      activity_epoch: "f".repeat(32),
      connections: [connection],
      active_count: 1,
      controller_ownerships: {
        contract_version: "agent-controller-ownership-list.v1",
        ownerships: [],
        active_count: 0,
      },
      tool_activity_sequences: [{
        contract_version: "agent-mcp-tool-activity-sequence.v1",
        connection_id: connection.connection_id,
        credential_revision: connection.credential_revision,
        sequence: 0,
        tool_name: null,
        tool_source: null,
        started_at: null,
        completed_at: null,
        outcome: null,
      }],
    };
    const transport = {
      ...sessionTransport(current),
      getAgentOrchestration: vi.fn().mockResolvedValue(exampleAgentOrchestrationManifest()),
      listAgentMcpConnections: vi.fn().mockResolvedValue(connections),
      listAgentProjects: vi.fn().mockResolvedValue({
        contract_version: "agent-catalog.v2" as const,
        projects: [catalogProjectFixture(projectId, "Synthetic page-owned project", 1)],
      }),
    };
    render(<AgentPage transport={transport} />);

    fireEvent.click(await screen.findByRole("button", { name: "Project tools" }));
    let settings = await screen.findByRole("dialog", { name: "Agent settings" });
    fireEvent.click(await within(settings).findByRole("button", {
      name: "Begin external lifecycle proof",
    }));
    let proof = within(settings).getByRole("region", {
      name: /External controller lifecycle/,
    });
    expect(within(proof).getByText("In progress")).toBeVisible();
    expect(within(proof).getByText(/call only agent_discover/)).toBeVisible();

    fireEvent.click(within(settings).getByRole("button", { name: "Close agent settings" }));
    expect(screen.queryByRole("dialog", { name: "Agent settings" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Project tools" }));
    settings = await screen.findByRole("dialog", { name: "Agent settings" });
    proof = await within(settings).findByRole("region", {
      name: /External controller lifecycle/,
    });
    expect(within(proof).getByText("In progress")).toBeVisible();
    expect(within(settings).getByRole("button", { name: "Restart lifecycle proof" })).toBeVisible();
    expect(within(proof).getByText(/clears on app reload/)).toBeVisible();
  });
});

describe("Agent managed MCP call timeline", () => {
  const alias = "mcp_99999999_synthetic_read";
  const callId = "synthetic-model-call";
  const approvalId = "d".repeat(32);
  const mcpTool = {
    contract_version: "agent-mcp-tool.v1" as const,
    source: "managed_mcp" as const,
    server_title: "Synthetic Files",
    tool_name: "read_example",
    tool_title: "Read example",
    model_alias: alias,
    every_call_requires_native_approval: true as const,
  };

  it("coalesces pending MCP activity and presents a friendly one-call native review", async () => {
    const activity = [
      event(1, "tool_call", { tool: alias, call_id: callId, arguments: {} }),
      event(2, "approval_required", {
        tool: alias,
        call_id: callId,
        approval_id: approvalId,
        arguments: {},
        preview: "Allow one MCP tool call\nServer: Synthetic Files\nArguments: [redacted]",
        mcp_tool: mcpTool,
      }),
    ];
    const current = view({
      running: true,
      pending_approval_id: approvalId,
      last_seq: 2,
    });
    const decideAgentApproval = vi.fn(async () => view({ last_seq: 3 }));
    const transport = {
      ...sessionTransport(current),
      getUserPresenceCapability: vi.fn(async () => userPresenceCapability(true)),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: activity,
        running: true,
        pending_approval_id: approvalId,
        last_seq: 2,
        first_seq: 1,
      })),
      decideAgentApproval,
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Waiting for approval" })).toBeVisible();
    expect(screen.queryByLabelText(`Agent action: ${alias}`)).not.toBeInTheDocument();
    const dialog = await screen.findByRole("alertdialog", { name: "Approval needed" });
    expect(within(dialog).getByText("Read example")).toBeVisible();
    expect(within(dialog).getAllByText("Synthetic Files")[0]).toBeVisible();
    expect(dialog).toHaveTextContent(/one external project-tool invocation/i);
    expect(within(dialog).getByLabelText("Redacted MCP call preview")).toHaveTextContent("Arguments: [redacted]");
    expect(within(dialog).getByRole("button", { name: "Approve one call" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Deny call" }));
    await waitFor(() => expect(decideAgentApproval).toHaveBeenCalledWith(SESSION, approvalId, false));
  });

  it("renders one terminal MCP card for the full event sequence with content-free facts", async () => {
    const activity = [
      event(1, "tool_call", { tool: alias, call_id: callId, arguments: {} }),
      event(2, "approval_required", { tool: alias, call_id: callId, approval_id: approvalId, arguments: {}, mcp_tool: mcpTool }),
      event(3, "approval_resolved", { tool: alias, call_id: callId, approval_id: approvalId, ok: true, mcp_tool: mcpTool }),
      event(4, "tool_result", {
        tool: alias,
        call_id: callId,
        ok: true,
        tool_state: "succeeded",
        text: "Synthetic bounded result",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: 250,
          timing_source: "server_monotonic.v1",
          approval_state: "approved",
          evidence_state: "untracked_external_effect",
        },
        mcp_tool: mcpTool,
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
      }),
    ];
    const current = view({ last_seq: 4, turns: 1 });
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: false,
        session_id: SESSION,
        events: activity,
        running: false,
        pending_approval_id: null,
        last_seq: 4,
        first_seq: 1,
      })),
    };

    render(<AgentPage transport={transport} />);

    const cards = await screen.findAllByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Completed" });
    expect(cards).toHaveLength(1);
    expect(screen.queryByText(alias)).not.toBeInTheDocument();
    expect(cards[0]).toHaveTextContent("Approved once");
    expect(cards[0]).toHaveTextContent("External effect not verified");
    expect(cards[0]).toHaveTextContent("Cleanup verified");
  });

  it("removes pending MCP authority and shows cancelling after Stop is acknowledged", async () => {
    const activity = [
      event(1, "tool_call", { tool: alias, call_id: callId, arguments: {} }),
      event(2, "approval_required", {
        tool: alias,
        call_id: callId,
        approval_id: approvalId,
        arguments: {},
        mcp_tool: mcpTool,
      }),
    ];
    const current = view({
      running: true,
      stopping: true,
      pending_approval_id: null,
      last_seq: 2,
    });
    const transport = {
      ...sessionTransport(current),
      getAgentEvents: vi.fn(async () => ({
        contract_version: "local-agent.v9" as const,
        cleanup_unconfirmed: false,
        closing: false,
        stopping: true,
        session_id: SESSION,
        events: activity,
        running: true,
        pending_approval_id: null,
        last_seq: 2,
        first_seq: 1,
      })),
    };

    render(<AgentPage transport={transport} />);

    expect(await screen.findByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Cancelling" })).toBeVisible();
    expect(screen.queryByRole("alertdialog", { name: "Approval needed" })).not.toBeInTheDocument();
  });
});
