import { useCallback, useEffect, useRef, useState } from "react";

import type {
  AgentMcpClientKind,
  AgentMcpClientSetup,
  AgentMcpConnection,
  AgentMcpConnectionCredential,
  AgentMcpConnectionList,
  AgentControllerOwnership,
  AgentProject,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import {
  AGENT_MCP_SELF_TEST_TIMEOUT_MS,
  AgentMcpEndpointSelfTestError,
  runAgentMcpEndpointSelfTest,
  type AgentMcpEndpointSelfTestFailure,
  type AgentMcpEndpointSelfTestResult,
} from "../../shared/api/agentMcpEndpointSelfTest";
import {
  beginExternalControllerAcceptance,
  externalControllerAcceptanceBaselineIssue,
  externalControllerAcceptancePassed,
  externalControllerAcceptanceStepPassed,
  type ExternalControllerAcceptanceEvidence,
  type ExternalControllerAcceptanceRun,
  type ExternalControllerAcceptanceStep,
} from "./externalControllerAcceptance";
import "./AgentMcpConnectionsPanel.css";

type ConnectionTransport = Partial<Pick<
  PromptEnhancerTransport,
  | "listAgentMcpConnections"
  | "getAgentMcpClientSetup"
  | "createAgentMcpConnection"
  | "rotateAgentMcpConnection"
  | "revokeAgentMcpConnection"
  | "releaseAgentControllerOwnership"
  | "listAgentProjects"
>>;

type Props = {
  transport: ConnectionTransport;
  userPresenceAvailable: boolean;
  selectedProjectId?: string | null;
  selectedSessionId?: string | null;
  acceptanceRun?: ExternalControllerAcceptanceRun | null;
  onAcceptanceEvidence?: (evidence: ExternalControllerAcceptanceEvidence) => void;
  onAcceptanceObservation?: (catalog: AgentMcpConnectionList) => void;
  onAcceptanceRunChange?: (run: ExternalControllerAcceptanceRun | null) => void;
};

type LoadState = "loading" | "ready" | "unavailable" | "error";
type SetupClient = AgentMcpClientKind;
type ConfiguredSetupClient = Exclude<SetupClient, "other">;
type CopyKind =
  | "codex"
  | "claude"
  | "endpoint"
  | "preview-config"
  | "preview-endpoint"
  | "preview-register"
  | "register"
  | "starter"
  | "token"
  | "verify"
  | null;
type EndpointSelfTestState =
  | { state: "idle" }
  | { state: "running" }
  | { state: "passed"; result: AgentMcpEndpointSelfTestResult }
  | { state: "failed"; code: AgentMcpEndpointSelfTestFailure };

const AGENT_MCP_ENDPOINT_PATH = "/mcp/agent";


export function agentMcpClientVerificationCommand(client: ConfiguredSetupClient): string {
  return client === "codex"
    ? "codex mcp get prompt-enhancer-agent"
    : "claude mcp get prompt-enhancer-agent";
}

export function agentMcpClientRegistrationCommand(
  client: ConfiguredSetupClient,
  endpointUrl: string,
): string {
  if (client === "codex") {
    return `codex mcp add prompt-enhancer-agent --url ${endpointUrl} --bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN`;
  }
  return `claude mcp add --transport http --scope local --header 'Authorization: Bearer \${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' prompt-enhancer-agent ${endpointUrl}`;
}

function setupClientLabel(client: SetupClient): string {
  if (client === "codex") return "Codex";
  if (client === "claude") return "Claude Code";
  return "Other MCP client";
}

function setupConfigDestination(client: ConfiguredSetupClient): string {
  return client === "codex"
    ? "your user config.toml or a trusted project .codex/config.toml"
    : "the project .mcp.json or your user-scoped Claude Code MCP configuration";
}

export const AGENT_ORCHESTRATION_STARTER = [
  "Use the prompt-enhancer-agent MCP server to delegate this task to one local Prompt Enhancer Agent chat.",
  "First call agent_discover, then use agent_open with only the project, workspace, model, and permissions I explicitly provide.",
  "Check readiness with agent_context. Do not load, switch, or stop a model unless I explicitly authorize it and this connection exposes agent_runtime.",
  "Use agent_turn for one bounded request. If native approval is pending, stop and tell me; after I decide in Prompt Enhancer, continue with agent_wait using the returned cursor.",
  "Direct HTTP gives one project-scoped connection durable control of a live chat. Use agent_control to inspect ownership; only that owner may wait or stop. After reconnecting, continue with the same connection and cursor without resending the message. Transfer control only through a revision-bound two-party handoff; native approval never transfers.",
  "If you already authored exact UTF-8 file content, use agent_propose for a create or revision-bound edit; never claim it changed until I approve the diff and agent_wait returns a verified receipt.",
  "For two to eight files that must land together, use agent_propose_transaction: mark new files as create and edits with exact source revisions. It receives one native review and rollback-capable publication.",
  "For folder creation, no-overwrite folder/file moves, or recoverable file removal, use agent_propose_lifecycle with the exact source revision when required. It never applies directly or permanently deletes. In a Save locally chat, a verified file move advances a matching artifact card under the same identity; directory moves do not.",
  "Use agent_workspace and agent_artifacts to inspect exact results. In a Save locally chat, an approved verified create/edit becomes durable artifact lineage, and a verified file move advances a matching artifact card under the same identity; proposal content and approval data do not. Treat verified diffs and artifacts as evidence; never treat model prose as proof of a file change.",
  "Use agent_close only when I ask to close the live runtime; preserve the durable chat and retained history.",
].join(" ");

function requestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function clientLabel(kind: AgentMcpClientKind): string {
  if (kind === "codex") return "Codex";
  if (kind === "claude") return "Claude Code";
  return "Other MCP client";
}

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unknown" : date.toLocaleDateString();
}

function dateTimeLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unknown" : date.toLocaleString();
}

export function agentMcpEndpointSelfTestRecovery(
  code: AgentMcpEndpointSelfTestFailure,
): string {
  if (code === "endpoint_invalid" || code === "endpoint_origin_mismatch") {
    return "Reload this native app and create a fresh connection from its current loopback address.";
  }
  if (code === "credential_invalid") {
    return "The one-time token is malformed; rotate the active connection or create a replacement.";
  }
  if (code === "credential_rejected") {
    return "Refresh status. If the connection is active, rotate it and update the client token; if it is expired or revoked, create a replacement.";
  }
  if (code === "request_failed") {
    return "The bounded request was interrupted or timed out. Confirm this app is still listening, then retry once.";
  }
  if (code === "protocol_invalid") {
    return "The endpoint did not complete the negotiated MCP handshake. Reload the app before changing client settings.";
  }
  if (code === "instructions_invalid" || code === "tool_surface_invalid") {
    return "The running app and its Agent tool contract disagree. Reload the updated app before connecting a client.";
  }
  return "The read-only discovery workflow did not validate. Reload the app and retry before delegating work.";
}

export function agentMcpConnectionGuidance(connection: AgentMcpConnection): string {
  if (connection.state === "scope_missing") {
    return "This legacy or deleted-project connection has no usable scope and is rejected. Revoke it, then prepare a replacement for an active project.";
  }
  if (connection.state === "expired") {
    return "Expired credentials are rejected. Prepare a replacement connection; this record cannot be reactivated.";
  }
  if (connection.state === "revoked") {
    return "Revoked credentials are rejected permanently. Prepare a replacement only if you still trust that client.";
  }
  if (connection.last_used_at === null) {
    return "Waiting for the first authenticated request. Verify the endpoint and token environment variable; rotate if the token was lost.";
  }
  if (connection.last_tool_at === null) {
    return "The endpoint authenticated this credential. Ask the client to call agent_discover before delegating work.";
  }
  if (connection.last_tool_source === "native_self_test") {
    if (connection.last_tool_outcome === "failed") {
      return "The app's local self-test reached the endpoint, but its tool check failed. No external client is proven.";
    }
    return "The app's local self-test reached the endpoint. This does not prove Codex, Claude Code, or another external client connected.";
  }
  if (connection.last_tool_outcome === "failed") {
    return "An external MCP client reached this endpoint, but its last tool call failed. Review that named tool and retry; no task outcome is proven.";
  }
  return "An external MCP client and its last named tool call were observed. This receipt still does not prove a turn or file change succeeded.";
}

function controllerStateLabel(state: AgentControllerOwnership["state"]): string {
  return {
    claimed: "Claimed",
    running: "Running",
    waiting_native_approval: "Waiting for native approval",
    reconnecting: "Reconnect required",
    submission_uncertain: "Submission uncertain",
    stopping: "Stopping",
    stop_uncertain: "Stop uncertain",
    cleanup_unconfirmed: "Cleanup unconfirmed",
    revoked: "Owner revoked",
  }[state];
}

function controllerOperationLabel(
  operation: AgentControllerOwnership["operation"],
): string {
  return {
    turn: "Agent turn",
    write_proposal: "File proposal",
    transaction_proposal: "Multi-file proposal",
    lifecycle_proposal: "Workspace proposal",
  }[operation];
}

function controllerStateGuidance(ownership: AgentControllerOwnership): string {
  if (ownership.state === "waiting_native_approval") {
    return "The external controller is paused. Resolve the exact approval in the native Agent chat, then let this owner continue with agent_wait.";
  }
  if (ownership.state === "reconnecting") {
    return "Reconnect with this same connection and continue from the displayed cursor. Do not resend the original message.";
  }
  if (ownership.state === "submission_uncertain") {
    return "Delivery could not be proven. Reconnect and observe from the saved cursor; never repeat the mutation blindly.";
  }
  if (ownership.state === "stop_uncertain") {
    return "The Stop delivery is uncertain. Reconnect and observe cleanup; do not send another Stop until current state is known.";
  }
  if (ownership.state === "cleanup_unconfirmed") {
    return "The chat is quarantined until backend cleanup is objectively confirmed.";
  }
  if (ownership.state === "revoked") {
    return "The credential is revoked. This ownership record remains visible until the backend proves the live chat settled and native release succeeds.";
  }
  return "This exact connection is the only external controller allowed to continue, wait, or stop this live chat.";
}

function controllerMayAttemptNativeRelease(
  ownership: AgentControllerOwnership,
): boolean {
  return !ownership.approval_pending
    && !["claimed", "running", "stopping"].includes(ownership.state);
}

const EXTERNAL_ACCEPTANCE_STEPS: readonly {
  key: ExternalControllerAcceptanceStep;
  label: string;
}[] = [
  { key: "connect", label: "External client connected" },
  { key: "discovery", label: "Exact project and chat discovered" },
  { key: "ownership", label: "Atomic chat ownership" },
  { key: "stream", label: "Streaming state observed" },
  { key: "stop", label: "External Stop and release" },
  { key: "reconnect", label: "Reconnect without resubmission" },
  { key: "handoff", label: "Revision-bound two-party handoff" },
  { key: "revoke", label: "Current owner revoked" },
  { key: "refusal", label: "Revoked credential refused" },
  { key: "cleanup", label: "Settled ownership cleaned up" },
];

function externalAcceptanceIssueCopy(
  run: ExternalControllerAcceptanceRun,
): string {
  if (run.invalidReason === "connection_missing") {
    return "A bound connection disappeared. The run cannot substitute another credential; clear it and restart from a clean baseline.";
  }
  if (run.invalidReason === "credential_changed") {
    return "A bound credential revision changed. Clear the receipt and restart so every observation belongs to one exact credential revision.";
  }
  if (run.invalidReason === "activity_epoch_changed") {
    return "The local controller service restarted, so its content-free activity epoch changed. Earlier and later calls cannot be combined; restart from a clean baseline.";
  }
  if (run.invalidReason === "activity_gap") {
    return "More than one controller action occurred between observations, so exact ordering cannot be proven. Restart and refresh after each instructed call.";
  }
  if (run.invalidReason === "scope_changed" || run.invalidReason === "cross_scope_ownership") {
    return "Project, chat, or controller ownership no longer matches the bound scope. Evidence is never combined across scopes.";
  }
  if (run.invalidReason === "connection_inactive") {
    return "A required connection became inactive before its ordered revocation step. Prepare a replacement and restart the proof.";
  }
  if (run.invalidReason === "ownership_lost") {
    return "The exact ownership disappeared before the required Stop, handoff, revocation, or native release receipt was observed.";
  }
  if (run.invalidReason === "stream_not_observed") {
    return "The turn settled or became incomplete before the running stream state was observed. Restart with a long enough bounded request.";
  }
  if (run.invalidReason === "handoff_invalid") {
    return "The handoff target, revision, owner, or project did not match the two-party handoff contract.";
  }
  if (run.invalidReason === "release_invalid") {
    return "The native release receipt did not prove this exact revoked owner, settled chat, revision, and authority-free cleanup.";
  }
  if (run.invalidReason === "out_of_order") {
    return "A different external tool call arrived before the expected checkpoint. This ordered receipt cannot skip or reorder activity.";
  }
  return "The observed controller state did not prove the required outcome. This run failed closed; inspect the connection and chat before restarting.";
}

function externalAcceptanceInstruction(run: ExternalControllerAcceptanceRun): string {
  if (run.invalidReason !== null) return externalAcceptanceIssueCopy(run);
  if (externalControllerAcceptancePassed(run)) {
    return "Complete. One exact project/chat lifecycle proved connection, discovery, ownership, streaming, external Stop, reconnect without message resubmission, two-party handoff, revocation, refusal and settled native cleanup.";
  }
  if (run.phase === "connect_discover") {
    return `Connect ${clientLabel(run.primaryClientKind)}, call only agent_discover with this credential, then refresh. The app's local self-test does not count.`;
  }
  if (run.phase === "chat_discovery") {
    return "From the same client, call agent_catalog list_chats for the bound project and locate the exact open chat, then refresh.";
  }
  if (run.phase === "first_claim" || run.phase === "stream") {
    return "Send one long-enough bounded agent_turn to this exact chat, then refresh while it is still streaming. Do not use native Send for this step.";
  }
  if (run.phase === "first_stop") {
    return "From the owning external client, call agent_stop for this chat and cursor. Refresh only after Stop returns and control is released.";
  }
  if (run.phase === "reconnect_claim") {
    return "Send one second long-enough agent_turn to the same chat with a short deadline. Submit this message exactly once, then refresh.";
  }
  if (run.phase === "reconnect_incomplete") {
    return "Let that one call return incomplete so durable ownership enters reconnecting, then refresh. Do not submit the message again.";
  }
  if (run.phase === "reconnect_status") {
    return "Reconnect or reload the same external client and call agent_control status for this chat. Do not call agent_turn again.";
  }
  if (run.phase === "reconnect_wait") {
    return "Call agent_wait from the saved cursor with a short deadline so the same turn remains incomplete, then refresh.";
  }
  if (run.phase === "handoff_offer") {
    return "From the current owner, offer agent_control handoff at the displayed revision to a second active connection bound to this same project, then refresh.";
  }
  if (run.phase === "handoff_accept") {
    return "From that exact target credential, accept the offered ownership revision with agent_control, then refresh.";
  }
  if (run.phase === "revoke") {
    return "Use the target connection's native Revoke button below while it still owns the incomplete turn. The guide never revokes automatically.";
  }
  if (run.phase === "post_revoke_refusal") {
    return "Retry one MCP request with the exact revoked target token. Expect HTTP 401, then refresh proof evidence.";
  }
  return "Settle the exact live turn with native Stop if needed, then use Release settled control. Completion requires the backend's exact native release receipt.";
}

function replacementLabel(value: string): string {
  const suffix = " replacement";
  return `${value.slice(0, 80 - suffix.length).trimEnd()}${suffix}`;
}

export function AgentMcpConnectionsPanel({
  transport,
  userPresenceAvailable,
  selectedProjectId = null,
  selectedSessionId = null,
  acceptanceRun = null,
  onAcceptanceEvidence,
  onAcceptanceObservation,
  onAcceptanceRunChange,
}: Props) {
  const [catalog, setCatalog] = useState<AgentMcpConnectionList | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [clientSetup, setClientSetup] = useState<AgentMcpClientSetup | null>(null);
  const [setupPreviewState, setSetupPreviewState] = useState<LoadState>("loading");
  const [label, setLabel] = useState("My coding agent");
  const [clientKind, setClientKind] = useState<AgentMcpClientKind>("codex");
  const [expiresInDays, setExpiresInDays] = useState(90);
  const [allowLifecycle, setAllowLifecycle] = useState(false);
  const [projects, setProjects] = useState<AgentProject[]>([]);
  const [projectLoadState, setProjectLoadState] = useState<LoadState>("loading");
  const [scopeProjectId, setScopeProjectId] = useState(selectedProjectId ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [privateSetup, setPrivateSetup] = useState<AgentMcpConnectionCredential | null>(null);
  const [setupClient, setSetupClient] = useState<SetupClient>("codex");
  const [copied, setCopied] = useState<CopyKind>(null);
  const [endpointSelfTest, setEndpointSelfTest] = useState<EndpointSelfTestState>({ state: "idle" });
  const labelInput = useRef<HTMLInputElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const selfTestRequest = useRef<AbortController | null>(null);

  const refresh = useCallback(async (
    signal?: AbortSignal,
    background = false,
  ) => {
    if (transport.listAgentMcpConnections === undefined) {
      setCatalog(null);
      setLoadState("unavailable");
      return;
    }
    if (!background) setLoadState("loading");
    try {
      const result = await transport.listAgentMcpConnections(signal);
      if (signal?.aborted) return;
      setCatalog(result);
      onAcceptanceObservation?.(result);
      setLoadState("ready");
    } catch {
      if (signal?.aborted) return;
      if (!background) {
        setCatalog(null);
        setLoadState("error");
      }
    }
  }, [onAcceptanceObservation, transport.listAgentMcpConnections]);

  const loadClientSetup = useCallback(async (signal?: AbortSignal) => {
    if (transport.getAgentMcpClientSetup === undefined) {
      setClientSetup(null);
      setSetupPreviewState("unavailable");
      return;
    }
    setSetupPreviewState("loading");
    try {
      const result = await transport.getAgentMcpClientSetup(signal);
      if (signal?.aborted) return;
      setClientSetup(result);
      setSetupPreviewState("ready");
    } catch {
      if (signal?.aborted) return;
      setClientSetup(null);
      setSetupPreviewState("error");
    }
  }, [transport.getAgentMcpClientSetup]);

  const loadProjects = useCallback(async (signal?: AbortSignal) => {
    if (transport.listAgentProjects === undefined) {
      setProjects([]);
      setScopeProjectId(selectedProjectId ?? "");
      setProjectLoadState("unavailable");
      return;
    }
    setProjectLoadState("loading");
    try {
      const result = await transport.listAgentProjects({
        includeArchived: false,
        limit: 200,
      }, signal);
      if (signal?.aborted) return;
      const activeProjects = result.projects.filter((project) => project.archived_at === null);
      setProjects(activeProjects);
      setScopeProjectId((current) => {
        if (selectedProjectId !== null && activeProjects.some((project) => project.project_id === selectedProjectId)) {
          return selectedProjectId;
        }
        if (activeProjects.some((project) => project.project_id === current)) return current;
        return activeProjects[0]?.project_id ?? "";
      });
      setProjectLoadState("ready");
    } catch {
      if (signal?.aborted) return;
      setProjects([]);
      setScopeProjectId("");
      setProjectLoadState("error");
    }
  }, [selectedProjectId, transport.listAgentProjects]);

  useEffect(() => {
    const controller = new AbortController();
    request.current = controller;
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    void loadClientSetup(controller.signal);
    return () => controller.abort();
  }, [loadClientSetup]);

  useEffect(() => {
    const controller = new AbortController();
    void loadProjects(controller.signal);
    return () => controller.abort();
  }, [loadProjects]);

  useEffect(() => () => selfTestRequest.current?.abort(), []);

  useEffect(() => {
    if (
      loadState !== "ready"
      || (catalog?.controller_ownerships.active_count ?? 0) === 0
    ) return undefined;
    const controller = new AbortController();
    const timer = globalThis.setInterval(() => {
      void refresh(controller.signal, true);
    }, 2_000);
    return () => {
      controller.abort();
      globalThis.clearInterval(timer);
    };
  }, [catalog?.controller_ownerships.active_count, loadState, refresh]);

  const afterMutation = useCallback(async (
    credential: AgentMcpConnectionCredential | null,
    success: string,
  ) => {
    selfTestRequest.current?.abort();
    setPrivateSetup(credential);
    if (credential !== null) setSetupClient(credential.connection.client_kind);
    setCopied(null);
    setEndpointSelfTest({ state: "idle" });
    setMessage(success);
    await refresh();
  }, [refresh]);

  const create = useCallback(async () => {
    if (transport.createAgentMcpConnection === undefined || !userPresenceAvailable) return;
    const normalized = label.trim();
    if (!normalized || normalized.length > 80) {
      setMessage("Use a connection name between 1 and 80 characters.");
      return;
    }
    if (!/^[0-9a-f]{32}$/u.test(scopeProjectId)) {
      setMessage("Choose one active Agent project for this connection.");
      return;
    }
    setBusy("create");
    setMessage(null);
    try {
      const credential = await transport.createAgentMcpConnection({
        request_id: requestId(),
        label: normalized,
        client_kind: clientKind,
        project_id: scopeProjectId,
        allow_model_lifecycle: allowLifecycle,
        expires_in_days: expiresInDays,
      });
      await afterMutation(
        credential,
        "Connection created. Copy one private setup now; the app will not show this credential again.",
      );
    } catch {
      setMessage("The connection could not be created. No provider configuration was changed.");
    } finally {
      setBusy(null);
    }
  }, [
    afterMutation,
    allowLifecycle,
    clientKind,
    expiresInDays,
    label,
    scopeProjectId,
    transport.createAgentMcpConnection,
    userPresenceAvailable,
  ]);

  const rotate = useCallback(async (connection: AgentMcpConnection) => {
    if (transport.rotateAgentMcpConnection === undefined || !userPresenceAvailable) return;
    setBusy(`rotate:${connection.connection_id}`);
    setMessage(null);
    try {
      const credential = await transport.rotateAgentMcpConnection(
        connection.connection_id,
        {
          request_id: requestId(),
          expected_revision: connection.revision,
          expires_in_days: expiresInDays,
        },
      );
      await afterMutation(
        credential,
        "Credential rotated. The previous credential stopped working immediately.",
      );
    } catch {
      setMessage("The credential could not be rotated. Refresh the connection list and try again.");
    } finally {
      setBusy(null);
    }
  }, [
    afterMutation,
    expiresInDays,
    transport.rotateAgentMcpConnection,
    userPresenceAvailable,
  ]);

  const revoke = useCallback(async (connection: AgentMcpConnection) => {
    if (transport.revokeAgentMcpConnection === undefined || !userPresenceAvailable) return;
    setBusy(`revoke:${connection.connection_id}`);
    setMessage(null);
    try {
      await transport.revokeAgentMcpConnection(
        connection.connection_id,
        { expected_revision: connection.revision },
      );
      await afterMutation(null, "Connection revoked. Its credential no longer works.");
    } catch {
      setMessage("The connection could not be revoked. Refresh the connection list and try again.");
    } finally {
      setBusy(null);
    }
  }, [afterMutation, transport.revokeAgentMcpConnection, userPresenceAvailable]);

  const releaseControllerOwnership = useCallback(async (
    ownership: AgentControllerOwnership,
  ) => {
    if (
      transport.releaseAgentControllerOwnership === undefined
      || !userPresenceAvailable
    ) return;
    setBusy(`release-control:${ownership.session_id}`);
    setMessage(null);
    try {
      const receipt = await transport.releaseAgentControllerOwnership({
        session_id: ownership.session_id,
        expected_revision: ownership.revision,
      });
      onAcceptanceEvidence?.({ kind: "native_release", receipt });
      await refresh();
      setMessage(
        `Released settled external control for ${ownership.session_title}. No chat, history, or native authority was deleted.`,
      );
    } catch {
      setMessage(
        "External control was not released. The record remains visible; finish or stop the live chat, resolve any native approval, and confirm cleanup before retrying.",
      );
    } finally {
      setBusy(null);
    }
  }, [onAcceptanceEvidence, refresh, transport.releaseAgentControllerOwnership, userPresenceAvailable]);

  const copyValue = useCallback(async (
    kind: Exclude<CopyKind, null>,
    value: string,
  ) => {
    if (!navigator.clipboard?.writeText) {
      setCopied(null);
      setMessage("Clipboard access was unavailable. No private value was exposed.");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setCopied(kind);
    } catch {
      setCopied(null);
      setMessage("Clipboard access was unavailable. No private value was exposed.");
    }
  }, []);

  const copyPrivate = useCallback(async (kind: "codex" | "claude" | "endpoint" | "token") => {
    if (privateSetup === null) return;
    const value = kind === "codex"
      ? privateSetup.codex_toml
      : kind === "claude"
        ? privateSetup.claude_json
        : kind === "endpoint"
          ? privateSetup.endpoint_url
          : privateSetup.bearer_token;
    await copyValue(kind, value);
  }, [copyValue, privateSetup]);

  const copyStarter = useCallback(async () => {
    await copyValue("starter", AGENT_ORCHESTRATION_STARTER);
  }, [copyValue]);

  const copyVerification = useCallback(async () => {
    if (setupClient === "other") return;
    await copyValue("verify", agentMcpClientVerificationCommand(setupClient));
  }, [copyValue, setupClient]);

  const copyRegistration = useCallback(async () => {
    if (privateSetup === null || setupClient === "other") return;
    await copyValue(
      "register",
      agentMcpClientRegistrationCommand(setupClient, privateSetup.endpoint_url),
    );
  }, [copyValue, privateSetup, setupClient]);

  const copyPreview = useCallback(async (
    kind: "config" | "endpoint" | "register",
  ) => {
    if (clientSetup === null) return;
    const setupClientKind = clientKind === "claude" ? "claude" : "codex";
    const value = kind === "endpoint"
      ? clientSetup.endpoint_url
      : kind === "config"
        ? setupClientKind === "codex" ? clientSetup.codex_toml : clientSetup.claude_json
        : setupClientKind === "codex" ? clientSetup.codex_add_command : clientSetup.claude_add_command;
    await copyValue(`preview-${kind}`, value);
  }, [clientKind, clientSetup, copyValue]);

  const testEndpoint = useCallback(async () => {
    if (privateSetup === null || busy !== null) return;
    selfTestRequest.current?.abort();
    const controller = new AbortController();
    selfTestRequest.current = controller;
    setBusy("endpoint-self-test");
    setEndpointSelfTest({ state: "running" });
    setMessage(null);
    try {
      const result = await runAgentMcpEndpointSelfTest({
        allowModelLifecycle: privateSetup.connection.allow_model_lifecycle,
        bearerToken: privateSetup.bearer_token,
        endpointUrl: privateSetup.endpoint_url,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setEndpointSelfTest({ state: "passed", result });
      await refresh();
      if (controller.signal.aborted) return;
      setMessage(
        "Local endpoint self-test passed. This proves the scoped MCP protocol and Agent tool surface, not that an external Codex or Claude client connected.",
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      const code = error instanceof AgentMcpEndpointSelfTestError
        ? error.code
        : "request_failed";
      setEndpointSelfTest({ state: "failed", code });
      setMessage(
        `Local endpoint self-test failed closed. No model, process, terminal, project, chat, or workspace action was started. ${agentMcpEndpointSelfTestRecovery(code)}`,
      );
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }, [busy, privateSetup, refresh]);

  const scopeReady = /^[0-9a-f]{32}$/u.test(scopeProjectId)
    && (projectLoadState === "ready" || (
      projectLoadState === "unavailable" && selectedProjectId === scopeProjectId
    ));
  const controlsAvailable = userPresenceAvailable
    && transport.createAgentMcpConnection !== undefined
    && scopeReady;
  const beginExternalProof = useCallback((connection: AgentMcpConnection) => {
    if (catalog === null) return;
    const issue = externalControllerAcceptanceBaselineIssue(
      connection,
      catalog,
      selectedProjectId,
      selectedSessionId,
    );
    if (issue !== null || selectedProjectId === null || selectedSessionId === null) {
      setMessage(issue ?? "Open one live Agent chat inside a saved project before beginning this proof.");
      return;
    }
    onAcceptanceRunChange?.(beginExternalControllerAcceptance(
      connection,
      catalog,
      selectedProjectId,
      selectedSessionId,
    ));
    setMessage(
      `External lifecycle proof started for ${connection.label}. Earlier activity is excluded; begin with a new external agent_discover call.`,
    );
  }, [catalog, onAcceptanceRunChange, selectedProjectId, selectedSessionId]);
  const prepareReplacement = useCallback((connection: AgentMcpConnection) => {
    if (!controlsAvailable || connection.state === "active") return;
    setLabel(replacementLabel(connection.label));
    setClientKind(connection.client_kind);
    setAllowLifecycle(connection.allow_model_lifecycle);
    if (connection.scope.project_id !== null) setScopeProjectId(connection.scope.project_id);
    setCopied(null);
    setMessage(
      "Replacement draft prepared. Review its client, expiry, and model-control scope, then create it through native confirmation.",
    );
    labelInput.current?.focus();
    labelInput.current?.scrollIntoView?.({ block: "nearest" });
  }, [controlsAvailable]);
  const setupConnection = privateSetup === null
    ? null
    : catalog?.connections.find(
      (connection) => connection.connection_id === privateSetup.connection.connection_id,
    ) ?? privateSetup.connection;
  const acceptancePrimary = acceptanceRun === null
    ? null
    : catalog?.connections.find(
      (connection) => connection.connection_id === acceptanceRun.primaryConnectionId,
    ) ?? null;
  const acceptanceTarget = acceptanceRun?.targetConnectionId === null
    || acceptanceRun?.targetConnectionId === undefined
    ? null
    : catalog?.connections.find(
      (connection) => connection.connection_id === acceptanceRun.targetConnectionId,
    ) ?? null;
  const acceptanceContextActive = acceptanceRun === null
    || (selectedProjectId === acceptanceRun.projectId && selectedSessionId === acceptanceRun.sessionId);

  return (
    <section aria-labelledby="agent-mcp-connections-title" className="agent-mcp-connections">
      <header>
        <span>
          <small>Recommended · no bridge process</small>
          <strong id="agent-mcp-connections-title">Direct app connections</strong>
        </span>
        {catalog && <span>{catalog.active_count} active</span>}
      </header>
      <p>
        Connect Codex, Claude Code, or another MCP client directly to this already-running
        loopback app. Nineteen project-scoped tools cover the bound project, chats, turns, context,
        workspace, artifact, and media lifecycle; model control appears only when you grant it.
        Creating a connection starts no terminal, subprocess, model, or agent.
      </p>
      <p>
        The normal connected-agent flow is open → turn → stop or wait when needed → live-close.
        Live-close retains the durable chat and its saved history. Permanent deletion and every
        protected file effect remain explicit actions in this Agent UI.
      </p>
      <div className="agent-mcp-connections__endpoint">
        <span>
          <small>Streamable HTTP endpoint</small>
          <code>POST {AGENT_MCP_ENDPOINT_PATH}</code>
        </span>
        <button
          className="button button--ghost"
          onClick={() => void copyStarter()}
          type="button"
        >
          {copied === "starter" ? "Orchestration starter copied" : "Copy orchestration starter"}
        </button>
      </div>
      {setupPreviewState === "loading" && (
        <p role="status">Loading exact client setup…</p>
      )}
      {setupPreviewState === "error" && (
        <p role="alert">The token-free client setup preview could not be validated.</p>
      )}
      {setupPreviewState === "ready" && clientSetup && (
        <section
          aria-labelledby="agent-mcp-setup-preview-title"
          className="agent-mcp-connections__preview"
        >
          <header>
            <span>
              <small>Read-only · safe before authorization</small>
              <strong id="agent-mcp-setup-preview-title">Exact client setup</strong>
            </span>
            <span>Disconnected · no credential</span>
          </header>
          <p>
            Inspect or copy the exact setup for this running app before creating a connection.
            These token-free values cannot authenticate, start a process, open a terminal, or edit
            Codex or Claude settings. Native approval is still required to create a scoped token.
          </p>
          <div
            aria-label="Setup preview client"
            className="agent-mcp-connections__preview-clients"
            role="group"
          >
            {(["codex", "claude", "other"] as const).map((client) => (
              <button
                aria-pressed={clientKind === client}
                className="button button--ghost"
                key={client}
                onClick={() => {
                  setClientKind(client);
                  setCopied(null);
                }}
                type="button"
              >
                {clientLabel(client)}
              </button>
            ))}
          </div>
          <div className="agent-mcp-connections__preview-endpoint">
            <span>Exact Streamable HTTP endpoint</span>
            <code>{clientSetup.endpoint_url}</code>
            <button
              className="button button--ghost"
              onClick={() => void copyPreview("endpoint")}
              type="button"
            >
              {copied === "preview-endpoint" ? "Preview endpoint copied" : "Copy preview endpoint"}
            </button>
          </div>
          {clientKind === "other" ? (
            <p className="agent-mcp-connections__preview-note">
              Configure a Streamable HTTP MCP server at the endpoint above. After native connection
              creation, send its scoped token as <code>Authorization: Bearer …</code>. The preview
              intentionally contains no token.
            </p>
          ) : (
            <>
              <div className="agent-mcp-connections__preview-command">
                <span>Token-free {clientLabel(clientKind)} install command</span>
                <code>{clientKind === "codex" ? clientSetup.codex_add_command : clientSetup.claude_add_command}</code>
              </div>
              <div className="agent-mcp-connections__preview-actions">
                <button
                  className="button button--ghost"
                  onClick={() => void copyPreview("register")}
                  type="button"
                >
                  {copied === "preview-register" ? "Preview command copied" : "Copy preview install command"}
                </button>
                <button
                  className="button button--ghost"
                  onClick={() => void copyPreview("config")}
                  type="button"
                >
                  {copied === "preview-config" ? "Preview config copied" : "Copy preview config"}
                </button>
              </div>
              <details className="agent-mcp-connections__preview-config">
                <summary>Review exact {clientLabel(clientKind)} config</summary>
                <pre><code>{clientKind === "codex" ? clientSetup.codex_toml : clientSetup.claude_json}</code></pre>
              </details>
            </>
          )}
          <footer aria-label="Setup preview guarantees">
            <span>No credential</span>
            <span>No authority</span>
            <span>No process or terminal</span>
            <span>No provider edits</span>
          </footer>
        </section>
      )}
      <details className="agent-mcp-connections__quickstart">
        <summary>Connect an orchestrator and delegate one task</summary>
        <ol>
          <li>Create one scoped connection and copy its one-time token plus the matching client config.</li>
          <li>Put the token in <code>PROMPT_ENHANCER_AGENT_MCP_TOKEN</code> only in the Codex, Claude Code, or other MCP client process.</li>
          <li>Connect to the exact endpoint shown in the private setup and begin with <code>agent_discover</code> → <code>agent_open</code> → <code>agent_context</code>. Delegate with <code>agent_turn</code>, offer exact create/edit work with <code>agent_propose</code> or <code>agent_propose_transaction</code>, and offer folder/move/recoverable-trash work with <code>agent_propose_lifecycle</code>.</li>
          <li>If native review is required, decide it here and let the controller continue with <code>agent_wait</code>. In a Save locally chat, each verified create/edit receipt becomes a durable output card, and a later verified file move advances a matching card under the same identity. Directory moves do not yet advance artifact cards. Proposal content and approval data are not retained. Inspect results through <code>agent_workspace</code> and <code>agent_artifacts</code>; use its <code>preview_capture</code> action to review any other generated file&apos;s path, type, size, and digest before adding it in the native Agent UI.</li>
          <li>Use <code>agent_close</code> only for the live runtime; the project, chat, and retained history remain browsable.</li>
        </ol>
        <p>
          Refresh connection status below after a client request or the optional local self-test. The
          last-request timestamp proves only that the scoped credential reached this endpoint; it does
          not identify an external client. The content-free tool receipt names only the last validated
          tool and success or failure. Neither receipt claims a turn or file change succeeded.
        </p>
      </details>
      <details className="agent-mcp-connections__capabilities">
        <summary>Connected-agent tools · 19 project-scoped</summary>
        <dl>
          <div>
            <dt>Discover &amp; inspect</dt>
            <dd><code>agent_discover</code> <code>agent_context</code></dd>
          </div>
          <div>
            <dt>Projects &amp; chats</dt>
            <dd>
              <code>agent_open</code> <code>agent_catalog</code> <code>agent_history</code>
              <code>agent_resume</code> <code>agent_fork</code> <code>agent_export</code>
              <code>agent_close</code>
            </dd>
          </div>
          <div>
            <dt>Conversation</dt>
            <dd><code>agent_turn</code> <code>agent_stop</code> <code>agent_wait</code></dd>
          </div>
          <div>
            <dt>Controller ownership</dt>
            <dd><code>agent_control</code></dd>
          </div>
          <div>
            <dt>Workspace &amp; output</dt>
            <dd>
              <code>agent_workspace</code> <code>agent_propose</code> <code>agent_propose_transaction</code> <code>agent_propose_lifecycle</code> <code>agent_artifacts</code>
              <code>agent_stage_attachment</code>
            </dd>
          </div>
        </dl>
        <p>
          Resume and fork restore no approval authority. Export is exact-revision and path-free;
          artifacts return lineage or capture-candidate metadata rather than bytes, and only the native Agent UI can complete a capture. Workspace inspection is read-only;
          external create/edit, move, folder, and recoverable-trash proposals remain blocked behind the native review card,
          while Save locally chats retain only verified create/edit receipts to project durable output cards and verified file moves can advance a matching card under the same identity. Directory moves do not yet advance artifact cards;
          and inline PNG, JPEG, or PCM WAV staging never accepts a local path or URL. Review staged
          media in the composer before sending it.
        </p>
        <p>
          Context reports model readiness, placement, verified media capability, and truthful
          session-and-turn-bound usage evidence. New, recovered, or model-switched chats remain
          explicitly unmeasured until preflight; paths, standing instructions, process IDs,
          attachment bytes, token counting, and model loading are excluded.
        </p>
      </details>

      {loadState === "loading" && <p role="status">Loading direct connections…</p>}
      {loadState === "unavailable" && (
        <p role="status">This server does not expose direct Agent connections.</p>
      )}
      {loadState === "error" && (
        <div className="agent-mcp-connections__error" role="alert">
          <p>Connections could not be loaded.</p>
          <button className="button button--ghost" onClick={() => void refresh()} type="button">
            Retry
          </button>
        </div>
      )}

      {loadState === "ready" && (
        <>
          <div className="agent-mcp-connections__form">
            <label>
              Project scope
              <select
                aria-describedby="agent-mcp-project-scope-help"
                disabled={projectLoadState === "loading" || projectLoadState === "error"}
                onChange={(event) => setScopeProjectId(event.target.value)}
                value={scopeProjectId}
              >
                {projects.length === 0 && scopeProjectId !== "" && (
                  <option value={scopeProjectId}>Current Agent project</option>
                )}
                {projects.length === 0 && scopeProjectId === "" && (
                  <option value="">No active project available</option>
                )}
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>{project.name}</option>
                ))}
              </select>
            </label>
            <p id="agent-mcp-project-scope-help">
              This credential can see only this project and its chats and workspace. Native approvals are never inherited.
            </p>
            {projectLoadState === "loading" && <p role="status">Loading active projects…</p>}
            {projectLoadState === "error" && <p role="alert">Active projects could not be loaded. Connection creation is blocked.</p>}
            {projectLoadState === "ready" && projects.length === 0 && <p role="status">Create an Agent project before connecting a controller.</p>}
            <label>
              Connection name
              <input
                maxLength={80}
                onChange={(event) => setLabel(event.target.value)}
                ref={labelInput}
                value={label}
              />
            </label>
            <label>
              Client
              <select
                onChange={(event) => setClientKind(event.target.value as AgentMcpClientKind)}
                value={clientKind}
              >
                <option value="codex">Codex</option>
                <option value="claude">Claude Code</option>
                <option value="other">Other MCP client</option>
              </select>
            </label>
            <label>
              Expires
              <select
                onChange={(event) => setExpiresInDays(Number(event.target.value))}
                value={expiresInDays}
              >
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
                <option value={180}>180 days</option>
              </select>
            </label>
            <label className="agent-mcp-connections__check">
              <input
                checked={allowLifecycle}
                onChange={(event) => setAllowLifecycle(event.target.checked)}
                type="checkbox"
              />
              Permit explicit model load, switch, and stop requests
            </label>
            <button
              className="button button--primary"
              disabled={!controlsAvailable || busy !== null}
              onClick={() => void create()}
              type="button"
            >
              {busy === "create" ? "Creating…" : "Create direct connection"}
            </button>
            {!userPresenceAvailable && (
              <p role="status">Open the owned native app window to create, rotate, or revoke connections.</p>
            )}
          </div>

          {privateSetup && (
            <section
              aria-labelledby="agent-mcp-private-setup-title"
              className="agent-mcp-connections__private"
            >
              <header>
                <span>
                  <small>Secret shown only through explicit copy</small>
                  <strong id="agent-mcp-private-setup-title">One-time private setup</strong>
                </span>
                <span>Schema checked</span>
              </header>
              <p>
                Choose the client you will run, complete the three steps, then clear this box.
                Prompt Enhancer never edits provider settings, runs these commands, or starts a
                terminal. The secret remains hidden and is not stored by the server.
              </p>
              <div aria-label="Client setup" className="agent-mcp-connections__client-tabs" role="tablist">
                {(["codex", "claude", "other"] as const).map((client) => (
                  <button
                    aria-controls="agent-mcp-client-setup-panel"
                    aria-selected={setupClient === client}
                    className="button button--ghost"
                    id={`agent-mcp-client-tab-${client}`}
                    key={client}
                    onClick={() => {
                      setSetupClient(client);
                      setCopied(null);
                    }}
                    role="tab"
                    type="button"
                  >
                    {setupClientLabel(client)}
                  </button>
                ))}
              </div>
              <div
                aria-labelledby={`agent-mcp-client-tab-${setupClient}`}
                className="agent-mcp-connections__client-panel"
                id="agent-mcp-client-setup-panel"
                role="tabpanel"
              >
                <div className="agent-mcp-connections__preflight" role="status">
                  <span data-state="ready"><strong>Endpoint</strong> Exact loopback</span>
                  <span data-state="ready">
                    <strong>Config</strong>
                    {setupClient === "other"
                      ? " Generic HTTP contract ready"
                      : ` ${setupClientLabel(setupClient)} shape valid`}
                  </span>
                  <span data-state={endpointSelfTest.state === "passed" ? "ready" : endpointSelfTest.state === "failed" ? "failed" : "waiting"}>
                    <strong>Local protocol</strong>
                    {endpointSelfTest.state === "passed"
                      ? " Handshake + workflow passed"
                      : endpointSelfTest.state === "running"
                        ? " Checking…"
                        : endpointSelfTest.state === "failed" ? " Check failed" : " Not checked"}
                  </span>
                  <span data-state={setupConnection?.last_used_at == null ? "waiting" : "ready"}>
                    <strong>MCP activity</strong>
                    {setupConnection?.last_used_at == null ? " No request observed" : " Authenticated request observed"}
                  </span>
                </div>
                <ol className="agent-mcp-connections__setup-steps">
                  <li>
                    <span>
                      <strong>Copy the one-time token</strong>
                      <small>
                        Set it as <code>PROMPT_ENHANCER_AGENT_MCP_TOKEN</code> only in the
                        process that launches {setupClientLabel(setupClient)}.
                      </small>
                    </span>
                    <button className="button button--ghost" onClick={() => void copyPrivate("token")} type="button">
                      {copied === "token" ? "Token copied" : "Copy token"}
                    </button>
                  </li>
                  <li>
                    {setupClient === "other" ? (
                      <>
                        <span>
                          <strong>Register the Streamable HTTP server</strong>
                          <small>
                            Add the exact endpoint to your client and send the copied token only as
                            an <code>Authorization: Bearer …</code> header. Do not put the token in
                            the URL. Prompt Enhancer does not edit or launch that client.
                          </small>
                        </span>
                        <button
                          className="button button--ghost"
                          onClick={() => void copyPrivate("endpoint")}
                          type="button"
                        >
                          {copied === "endpoint" ? "Endpoint copied" : "Copy endpoint"}
                        </button>
                      </>
                    ) : (
                      <>
                        <span>
                          <strong>Register the direct server</strong>
                          <small>
                            Run the token-free install command in PowerShell or a POSIX shell, or
                            paste the generated snippet into {setupConfigDestination(setupClient)}.
                            Both reference the environment variable and never embed the token.
                            Prompt Enhancer copies these values but never runs the command.
                          </small>
                        </span>
                        <div>
                          <button
                            className="button button--ghost"
                            onClick={() => void copyRegistration()}
                            type="button"
                          >
                            {copied === "register" ? "Install command copied" : "Copy install command"}
                          </button>
                          <button
                            className="button button--ghost"
                            onClick={() => void copyPrivate(setupClient)}
                            type="button"
                          >
                            {copied === setupClient
                              ? `${setupClientLabel(setupClient)} config copied`
                              : `Copy ${setupClientLabel(setupClient)} config`}
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                  <li>
                    <span>
                      <strong>Verify, then delegate</strong>
                      <small>
                        {setupClient === "other"
                          ? "Reload the client, inspect its MCP server status and tool list, call agent_discover, send the starter, then refresh status here. A server-recorded tool receipt is the external-client check; the local self-test proves only this app endpoint."
                          : "Restart or reload the client, verify the named server, send the starter, then refresh connection status here. The read-only verify command plus a server-recorded tool receipt is the external-client check; the optional local self-test below proves only this app endpoint."}
                      </small>
                    </span>
                    <div>
                      {setupClient !== "other" && (
                        <button className="button button--ghost" onClick={() => void copyVerification()} type="button">
                          {copied === "verify" ? "Verify command copied" : "Copy verify command"}
                        </button>
                      )}
                      <button className="button button--ghost" onClick={() => void copyStarter()} type="button">
                        {copied === "starter" ? "Starter copied" : "Copy orchestration starter"}
                      </button>
                    </div>
                  </li>
                </ol>
                <section
                  aria-busy={endpointSelfTest.state === "running"}
                  aria-label="Local MCP endpoint self-test"
                  className="agent-mcp-connections__self-test"
                  data-state={endpointSelfTest.state}
                >
                  <span>
                    <strong>Test this app before editing client settings</strong>
                    <small>
                      Uses the hidden token from page memory for a bounded {AGENT_MCP_SELF_TEST_TIMEOUT_MS / 1_000}-second read-only MCP initialize,
                      orchestration-guidance check, exact tool-list check, and <code>agent_discover</code>.
                      It starts no model, process, terminal, project, chat, or file operation. A pass
                      does not prove that {setupClientLabel(setupClient)} is configured.
                    </small>
                    {endpointSelfTest.state === "passed" && (
                      <small role="status">
                        Protocol {endpointSelfTest.result.protocolVersion} · {endpointSelfTest.result.coreToolCount} core tools
                        {endpointSelfTest.result.modelLifecycleAdvertised ? " + scoped model control" : " · model control absent"}
                      </small>
                    )}
                    {endpointSelfTest.state === "failed" && (
                      <small role="alert">
                        {agentMcpEndpointSelfTestRecovery(endpointSelfTest.code)}
                      </small>
                    )}
                  </span>
                  <button
                    className="button button--ghost"
                    disabled={busy !== null}
                    onClick={() => void testEndpoint()}
                    type="button"
                  >
                    {endpointSelfTest.state === "running" ? "Testing…" : endpointSelfTest.state === "passed" ? "Test again" : "Run local self-test"}
                  </button>
                </section>
                <div className="agent-mcp-connections__private-endpoint">
                  <span>Exact endpoint for this app</span>
                  <code>{privateSetup.endpoint_url}</code>
                  <button className="button button--ghost" onClick={() => void copyPrivate("endpoint")} type="button">
                    {copied === "endpoint" ? "Endpoint copied" : "Copy endpoint"}
                  </button>
                </div>
              </div>
              <footer>
                <p>
                  Clearing this card removes the secret from page memory. The durable connection
                  remains revocable below; its token cannot be recovered and must be rotated if lost.
                </p>
                <button
                  className="button button--ghost"
                  onClick={() => {
                    selfTestRequest.current?.abort();
                    setPrivateSetup(null);
                    setCopied(null);
                    setEndpointSelfTest({ state: "idle" });
                    if (busy === "endpoint-self-test") setBusy(null);
                  }}
                  type="button"
                >
                  Clear private setup
                </button>
              </footer>
            </section>
          )}

          {message && <p className="agent-mcp-connections__message" role="status">{message}</p>}

          <div className="agent-mcp-connections__list-head">
            <strong>Connection status</strong>
            <button
              className="button button--ghost"
              disabled={busy !== null}
              onClick={() => void refresh()}
              type="button"
            >
              Refresh connection status
            </button>
          </div>
          {acceptanceRun && (
            <section
              aria-labelledby="agent-mcp-external-acceptance-title"
              className="agent-mcp-connections__acceptance"
              data-state={acceptanceRun.invalidReason !== null
                ? "blocked"
                : externalControllerAcceptancePassed(acceptanceRun) ? "passed" : "running"}
            >
              <header>
                <span>
                  <small>Release acceptance · page-owned, never automatic</small>
                  <strong id="agent-mcp-external-acceptance-title">
                    External controller lifecycle · {acceptancePrimary?.label ?? "bound connection"}
                  </strong>
                </span>
                <span>
                  {acceptanceRun.invalidReason !== null
                    ? "Restart required"
                    : externalControllerAcceptancePassed(acceptanceRun) ? "Complete" : "In progress"}
                </span>
              </header>
              <p aria-live="polite" role="status">
                {acceptanceContextActive
                  ? externalAcceptanceInstruction(acceptanceRun)
                  : "Return to the exact live project and chat that began this proof. Evidence remains bound there and is never combined across chats."}
              </p>
              <small>
                This receipt survives closing Settings and clears on app reload. It stores only
                pseudonymous connection, project, chat, process epoch, monotonic sequence,
                revision, cursor, state and timestamp
                evidence—never tokens, prompts, arguments, results, paths or provider configuration.
              </small>
              <ol aria-label="External controller proof checkpoints">
                {EXTERNAL_ACCEPTANCE_STEPS.map((item, index) => {
                  const passed = externalControllerAcceptanceStepPassed(acceptanceRun, item.key);
                  return (
                    <li data-state={passed ? "passed" : "waiting"} key={item.key}>
                      <span>{index + 1}</span>
                      <strong>{item.label}</strong>
                      <small>{passed ? "Passed" : "Waiting"}</small>
                    </li>
                  );
                })}
              </ol>
              <footer>
                <p>
                  Primary: {acceptancePrimary?.label ?? "unavailable"}
                  {acceptanceTarget ? ` · handoff target: ${acceptanceTarget.label}` : ""}.
                  The guide performs no MCP call, message submission, Stop, handoff, revocation,
                  native approval or cleanup itself.
                </p>
                <div>
                  <button
                    className="button button--ghost"
                    disabled={busy !== null}
                    onClick={() => void refresh()}
                    type="button"
                  >
                    Refresh proof evidence
                  </button>
                  <button
                    className="button button--ghost"
                    onClick={() => onAcceptanceRunChange?.(null)}
                    type="button"
                  >
                    Clear page-only receipt
                  </button>
                </div>
              </footer>
            </section>
          )}
          <div aria-label="Direct Agent connections" className="agent-mcp-connections__list" role="list">
            {catalog?.connections.length === 0 && <p>No direct connections yet.</p>}
            {catalog?.connections.map((connection) => (
              <article data-state={connection.state} key={connection.connection_id} role="listitem">
                <header>
                  <span>
                    <strong>{connection.label}</strong>
                    <small>{clientLabel(connection.client_kind)}</small>
                  </span>
                  <span>{connection.state}</span>
                </header>
                <p>
                  Expires {dateLabel(connection.expires_at)} · Model control {connection.allow_model_lifecycle ? "permitted" : "off"}
                </p>
                <p className="agent-mcp-connections__scope">
                  Project scope {connection.scope.project_name ?? "missing"} · Catalog, chats, and workspace {connection.scope.state === "bound" ? "project-only" : "blocked"} · Native approvals never inherited
                </p>
                <p className="agent-mcp-connections__activity">
                  {connection.last_used_at === null
                    ? "Never connected · no authenticated MCP request observed"
                    : `Last MCP request ${dateTimeLabel(connection.last_used_at)}`}
                </p>
                <p
                  className="agent-mcp-connections__tool-activity"
                  data-outcome={connection.last_tool_outcome ?? "unobserved"}
                >
                  {connection.last_tool_at === null
                    ? "No MCP tool call receipt recorded yet"
                    : <>
                        Last tool <code>{connection.last_tool_name}</code> · {connection.last_tool_outcome}
                        {connection.last_tool_source === "native_self_test"
                          ? " · local self-test"
                          : " · external MCP client"}
                        {` · ${dateTimeLabel(connection.last_tool_at)}`}
                      </>}
                </p>
                <p
                  className="agent-mcp-connections__auth-rejection"
                  data-observed={connection.last_auth_rejected_at === null ? "false" : "true"}
                >
                  {connection.last_auth_rejected_at === null
                    ? "No exact inactive-credential rejection recorded"
                    : `Exact inactive credential rejected · ${dateTimeLabel(connection.last_auth_rejected_at)}`}
                </p>
                <p
                  className="agent-mcp-connections__recovery"
                  data-state={connection.state === "active" ? connection.last_tool_outcome ?? "waiting" : connection.state}
                >
                  {agentMcpConnectionGuidance(connection)}
                </p>
                {(catalog?.controller_ownerships.ownerships ?? [])
                  .filter((ownership) => (
                    ownership.owner_connection_id === connection.connection_id
                  ))
                  .map((ownership) => (
                    <section
                      aria-label={`External control for ${ownership.session_title}`}
                      className="agent-mcp-connections__ownership"
                      data-state={ownership.state}
                      key={ownership.session_id}
                    >
                      <header>
                        <span>
                          <small>Durable external controller</small>
                          <strong>{ownership.session_title}</strong>
                        </span>
                        <span>{controllerStateLabel(ownership.state)}</span>
                      </header>
                      <dl>
                        <div>
                          <dt>Project</dt>
                          <dd>{ownership.project_name}</dd>
                        </div>
                        <div>
                          <dt>Operation</dt>
                          <dd>{controllerOperationLabel(ownership.operation)}</dd>
                        </div>
                        <div>
                          <dt>Observed cursor</dt>
                          <dd>{ownership.cursor} / {ownership.last_seq}</dd>
                        </div>
                        <div>
                          <dt>Updated</dt>
                          <dd>{dateTimeLabel(ownership.updated_at)}</dd>
                        </div>
                      </dl>
                      <p>{controllerStateGuidance(ownership)}</p>
                      {ownership.handoff !== null && (
                        <p className="agent-mcp-connections__handoff">
                          Handoff offered to <strong>{ownership.handoff.target_label}</strong> · expires {dateTimeLabel(ownership.handoff.expires_at)}. The target must accept the exact revision through <code>agent_control</code>; native approval never transfers.
                        </p>
                      )}
                      <footer>
                        <small>
                          Revision {ownership.revision} · owner since {dateTimeLabel(ownership.owner_since)}
                        </small>
                        <button
                          className="button button--ghost"
                          disabled={
                            !userPresenceAvailable
                            || transport.releaseAgentControllerOwnership === undefined
                            || !controllerMayAttemptNativeRelease(ownership)
                            || busy !== null
                          }
                          onClick={() => void releaseControllerOwnership(ownership)}
                          title="The backend releases this record only after the live chat is absent or objectively settled."
                          type="button"
                        >
                          {busy === `release-control:${ownership.session_id}`
                            ? "Checking settlement…"
                            : "Release settled control"}
                        </button>
                      </footer>
                    </section>
                  ))}
                {(catalog?.controller_ownerships.ownerships ?? [])
                  .filter((ownership) => (
                    ownership.handoff?.target_connection_id === connection.connection_id
                  ))
                  .map((ownership) => {
                    const handoff = ownership.handoff;
                    if (handoff === null) return null;
                    return (
                      <section
                        aria-label={`Incoming control handoff for ${ownership.session_title}`}
                        className="agent-mcp-connections__incoming-handoff"
                        key={`handoff:${ownership.session_id}`}
                      >
                        <strong>Incoming handoff · {ownership.session_title}</strong>
                        <p>
                          {ownership.owner_label} offered revision {ownership.revision} until {dateTimeLabel(handoff.expires_at)}. Accept it from this exact external client with <code>agent_control</code>. No pending native approval or protected authority transfers.
                        </p>
                      </section>
                    );
                  })}
                <div>
                  {connection.state === "active" && (
                    <button
                      className="button button--ghost"
                      disabled={busy !== null}
                      onClick={() => beginExternalProof(connection)}
                      type="button"
                    >
                      {acceptanceRun?.primaryConnectionId === connection.connection_id
                        ? "Restart lifecycle proof"
                        : "Begin external lifecycle proof"}
                    </button>
                  )}
                  <button
                    className="button button--ghost"
                    disabled={
                      !userPresenceAvailable
                      || connection.state !== "active"
                      || transport.rotateAgentMcpConnection === undefined
                      || busy !== null
                    }
                    onClick={() => void rotate(connection)}
                    type="button"
                  >
                    {busy === `rotate:${connection.connection_id}` ? "Rotating…" : "Rotate"}
                  </button>
                  <button
                    className="button button--ghost"
                    disabled={
                      !userPresenceAvailable
                      || connection.state === "revoked"
                      || transport.revokeAgentMcpConnection === undefined
                      || busy !== null
                    }
                    onClick={() => void revoke(connection)}
                    type="button"
                  >
                    {busy === `revoke:${connection.connection_id}` ? "Revoking…" : "Revoke"}
                  </button>
                  {connection.state !== "active" && (
                    <button
                      className="button button--ghost"
                      disabled={!controlsAvailable || busy !== null}
                      onClick={() => prepareReplacement(connection)}
                      type="button"
                    >
                      Prepare replacement
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
