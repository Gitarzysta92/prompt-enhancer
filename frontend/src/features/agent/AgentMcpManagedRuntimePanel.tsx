import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  McpManagedHostStartPreview,
  McpManagedHostStatus,
  McpManagedProjectBinding,
  McpManagedProjectRuntime,
  McpManagedServer,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { TrustedMcpAcceptanceEvidence } from "./trustedMcpAcceptance";

type RuntimeTransport = Partial<Pick<
  PromptEnhancerTransport,
  | "getMcpManagedHostStatus"
  | "getMcpManagedHostStartPreview"
  | "startMcpManagedHost"
  | "stopMcpManagedHost"
  | "getMcpManagedProjectRuntime"
>>;

const stateLabels: Record<McpManagedHostStatus["state"], string> = {
  not_started: "Stopped",
  starting: "Starting",
  ready: "Ready",
  unhealthy: "Unhealthy",
  stopping: "Stopping",
  cleanup_required: "Cleanup required",
};

const effectLabels: Record<McpManagedHostStartPreview["effects"][number], string> = {
  execute_reviewed_local_package: "Run the exact verified local package",
  run_with_current_user_os_permissions: "Use the current Windows user’s operating-system permissions",
  own_hidden_process_tree: "Own one hidden process tree so it can be stopped and verified",
  open_reviewed_remote_connection: "Open only the reviewed remote MCP connection",
  enumerate_exact_tool_contracts: "Re-enumerate and match the exact reviewed tool contracts",
  retain_connection_for_current_app_run: "Keep the connection only for this app run",
  periodic_contract_health_check: "Periodically verify that the tool contract has not drifted",
  register_admitted_project_tools: "Expose only this project’s admitted tools to its Agent",
  tool_calls_require_fresh_native_approval: "Require a new native confirmation for every tool call",
  no_automatic_restart: "Never restart the host automatically",
};

function requestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function statusMatchesScope(
  status: McpManagedHostStatus,
  managementId: string,
  projectId: string,
): boolean {
  return status.management_id === managementId
    && status.project_id === projectId
    && (status.binding === null
      || (status.binding.management_id === managementId && status.binding.project_id === projectId));
}

function previewMatchesAdmission(
  preview: McpManagedHostStartPreview,
  server: McpManagedServer,
  binding: McpManagedProjectBinding,
  projectId: string,
): boolean {
  return preview.binding.management_id === server.management_id
    && preview.binding.project_id === projectId
    && preview.binding.server_revision === server.revision
    && preview.binding.project_binding_revision === binding.revision
    && preview.binding.tool_snapshot_id === binding.tool_snapshot_id;
}

function runtimeMatchesProject(runtime: McpManagedProjectRuntime, projectId: string): boolean {
  const hostInstances = new Set(runtime.tools.map((tool) => tool.host_instance_id));
  return runtime.project_id === projectId
    && runtime.ready_tool_count === runtime.tools.length
    && runtime.ready_host_count === hostInstances.size
    && runtime.tools.every((tool) => tool.project_id === projectId);
}

function startFailureMessage(error: unknown): string {
  if (error instanceof TransportError) {
    if (error.reasonCode === "mcp_managed_host_start_cancelled") {
      return "Host start was cancelled before it became ready. No tool authority remains; refresh status before retrying.";
    }
    if (error.reasonCode === "mcp_managed_host_start_timeout") {
      return "Host start timed out and was stopped. No tool call was made; refresh status and verify cleanup before retrying.";
    }
    if (error.reasonCode === "mcp_host_process_output_limit") {
      return "The local host exceeded its process-output limit and its owned tree was stopped. No output is retained; review the package before retrying.";
    }
    if (error.reasonCode === "mcp_host_visible_window_detected") {
      return "The local host tried to show a window and its owned tree was stopped. No tool authority remains; review the package before retrying.";
    }
    if (error.reasonCode === "mcp_host_process_visibility_unconfirmed"
      || error.reasonCode === "mcp_host_cleanup_unconfirmed") {
      return "Host cleanup could not be objectively verified. Tool authority is blocked; review the cleanup-required status before retrying.";
    }
  }
  return "The host did not become ready. No tool call was made; refresh the exact plan and review cleanup state before retrying.";
}

function stopFailureMessage(error: unknown): string {
  if (error instanceof TransportError
    && (error.reasonCode === "mcp_host_cleanup_unconfirmed"
      || error.reasonCode === "mcp_managed_host_stop_timeout")) {
    return "The host was removed from tool routing, but process cleanup was not objectively verified. Review its cleanup-required status before any retry.";
  }
  return "The host stop was not verified. Review its status and cleanup state before starting or changing this plan.";
}

function runtimeEvidenceMessage(errorCode: string): string {
  if (errorCode === "mcp_host_cleanup_unconfirmed") {
    return "Cleanup verification failed, so this host remains blocked.";
  }
  if (errorCode === "mcp_managed_host_contract_drift"
    || errorCode.includes("tool_schema")
    || errorCode.includes("tool_identity")
    || errorCode.includes("tool_metadata")) {
    return "The observed tool contract no longer matches the reviewed plan.";
  }
  if (errorCode.includes("process_")
    || errorCode.includes("stdio_")
    || errorCode === "mcp_host_visible_window_detected") {
    return "The local host failed a bounded process-safety check.";
  }
  if (errorCode.includes("endpoint_")
    || errorCode.includes("transport_")
    || errorCode.includes("response_")
    || errorCode.includes("redirect_")
    || errorCode.includes("tls_")) {
    return "The reviewed connection failed a bounded transport-safety check.";
  }
  return "The host failed a bounded runtime check. Private server and process output is not shown.";
}

export function AgentMcpManagedRuntimePanel({
  acceptanceEventHead = 0,
  binding,
  onAcceptanceEvidence,
  onRuntimeChange,
  projectId,
  server,
  transport,
  userPresenceAvailable,
}: {
  acceptanceEventHead?: number;
  binding: McpManagedProjectBinding | undefined;
  onAcceptanceEvidence?: (evidence: TrustedMcpAcceptanceEvidence) => void;
  onRuntimeChange?: () => void;
  projectId: string;
  server: McpManagedServer;
  transport: RuntimeTransport;
  userPresenceAvailable: boolean;
}) {
  const [status, setStatus] = useState<McpManagedHostStatus | null>(null);
  const [statusState, setStatusState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [preview, setPreview] = useState<McpManagedHostStartPreview | null>(null);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [runtime, setRuntime] = useState<McpManagedProjectRuntime | null>(null);
  const [runtimeState, setRuntimeState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const actionIds = useRef(new Map<string, string>());
  const scopeKey = `${server.management_id}:${projectId}:${server.revision}:${binding?.revision ?? "none"}:${binding?.tool_snapshot_id ?? "none"}`;
  const scopeRef = useRef(scopeKey);
  scopeRef.current = scopeKey;

  const admitted = binding?.enabled === true
    && binding.admission_state === "admitted"
    && binding.tool_snapshot_id !== null
    && binding.admitted_tool_ids.length > 0;

  const refresh = useCallback(() => setRefreshRevision((value) => value + 1), []);

  useEffect(() => {
    setBusy(null);
    setMessage(null);
  }, [scopeKey]);

  useEffect(() => {
    setStatus(null);
    setPreview(null);
    setRuntime(null);
    if (!projectId || !admitted || binding?.tool_snapshot_id === null || binding === undefined) {
      setStatusState("idle");
      setPreviewState("idle");
      setRuntimeState("idle");
      return;
    }
    const loadStatus = transport.getMcpManagedHostStatus;
    const loadPreview = transport.getMcpManagedHostStartPreview;
    const loadRuntime = transport.getMcpManagedProjectRuntime;
    if (loadStatus === undefined) {
      setStatusState("unavailable");
      setPreviewState("unavailable");
      setRuntimeState("unavailable");
      return;
    }
    const controller = new AbortController();
    setStatusState("loading");
    setPreviewState(loadPreview === undefined ? "unavailable" : "loading");
    setRuntimeState(loadRuntime === undefined ? "unavailable" : "loading");

    void loadStatus(server.management_id, projectId, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      if (!statusMatchesScope(value, server.management_id, projectId)) {
        setStatus(null);
        setStatusState("unavailable");
        return;
      }
      setStatus(value);
      setStatusState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setStatusState("unavailable");
    });

    if (loadPreview !== undefined) {
      void loadPreview(
        server.management_id,
        projectId,
        server.revision,
        binding.revision,
        binding.tool_snapshot_id,
        controller.signal,
      ).then((value) => {
        if (controller.signal.aborted) return;
        if (!previewMatchesAdmission(value, server, binding, projectId)) {
          setPreview(null);
          setPreviewState("unavailable");
          return;
        }
        setPreview(value);
        setPreviewState("ready");
      }).catch(() => {
        if (controller.signal.aborted) return;
        setPreviewState("unavailable");
      });
    }

    if (loadRuntime !== undefined) {
      void loadRuntime(projectId, controller.signal).then((value) => {
        if (controller.signal.aborted) return;
        if (!runtimeMatchesProject(value, projectId)) {
          setRuntime(null);
          setRuntimeState("unavailable");
          return;
        }
        setRuntime(value);
        setRuntimeState("ready");
      }).catch(() => {
        if (controller.signal.aborted) return;
        setRuntimeState("unavailable");
      });
    }
    return () => controller.abort();
  }, [
    admitted,
    binding,
    projectId,
    refreshRevision,
    server.management_id,
    server.revision,
    transport.getMcpManagedHostStartPreview,
    transport.getMcpManagedHostStatus,
    transport.getMcpManagedProjectRuntime,
  ]);

  const serverTools = useMemo(() => runtime?.tools.filter(
    (tool) => tool.management_id === server.management_id
      && tool.project_id === projectId
      && binding?.admitted_tool_ids.includes(tool.tool_id),
  ) ?? [], [binding?.admitted_tool_ids, projectId, runtime, server.management_id]);
  const staleBinding = status?.binding !== null && status?.binding !== undefined
    && (status.binding.server_revision !== server.revision
      || status.binding.project_binding_revision !== binding?.revision
      || status.binding.tool_snapshot_id !== binding?.tool_snapshot_id);

  const start = useCallback(async () => {
    const apply = transport.startMcpManagedHost;
    if (apply === undefined || preview === null || binding === undefined
      || !previewMatchesAdmission(preview, server, binding, projectId)
      || !userPresenceAvailable || busy !== null || staleBinding) return;
    const actionScope = scopeKey;
    const key = `start:${preview.preview_digest}`;
    const id = actionIds.current.get(key) ?? requestId();
    actionIds.current.set(key, id);
    setBusy("start");
    setMessage(null);
    try {
      const next = await apply(server.management_id, projectId, {
        request_id: id,
        expected_server_revision: preview.binding.server_revision,
        expected_project_binding_revision: preview.binding.project_binding_revision,
        expected_tool_snapshot_id: preview.binding.tool_snapshot_id,
        preview_digest: preview.preview_digest,
      });
      if (!statusMatchesScope(next, server.management_id, projectId)) throw new Error("mcp_host_scope_mismatch");
      actionIds.current.delete(key);
      onAcceptanceEvidence?.({ eventFloor: acceptanceEventHead, kind: "host_started", status: next });
      if (scopeRef.current === actionScope) {
        setStatus(next);
        setMessage("Host ready. Only the admitted project tools are visible, and every call still requires a separate native confirmation.");
        refresh();
      }
    } catch (error) {
      if (scopeRef.current === actionScope) {
        setMessage(startFailureMessage(error));
        refresh();
      }
    } finally {
      if (scopeRef.current === actionScope) setBusy(null);
      onRuntimeChange?.();
    }
  }, [acceptanceEventHead, binding, busy, onAcceptanceEvidence, onRuntimeChange, preview, projectId, refresh, scopeKey, server, staleBinding, transport.startMcpManagedHost, userPresenceAvailable]);

  const stop = useCallback(async () => {
    const apply = transport.stopMcpManagedHost;
    if (apply === undefined || status === null || status.state === "not_started" || busy !== null) return;
    const actionScope = scopeKey;
    const key = `stop:${status.instance_id ?? "none"}`;
    const id = actionIds.current.get(key) ?? requestId();
    actionIds.current.set(key, id);
    setBusy("stop");
    setMessage(null);
    try {
      const next = await apply(server.management_id, projectId, {
        request_id: id,
        expected_instance_id: status.instance_id,
      });
      if (!statusMatchesScope(next, server.management_id, projectId)) throw new Error("mcp_host_scope_mismatch");
      actionIds.current.delete(key);
      onAcceptanceEvidence?.({ kind: "host_stopped", status: next });
      if (scopeRef.current === actionScope) {
        setStatus(next);
        setMessage("Host stopped. Its connection and tool-routing authority were removed.");
        refresh();
      }
    } catch (error) {
      if (scopeRef.current === actionScope) {
        setMessage(stopFailureMessage(error));
        refresh();
      }
    } finally {
      if (scopeRef.current === actionScope) setBusy(null);
      onRuntimeChange?.();
    }
  }, [busy, onAcceptanceEvidence, onRuntimeChange, projectId, refresh, scopeKey, server.management_id, status, transport.stopMcpManagedHost]);

  return (
    <section aria-labelledby="agent-mcp-runtime-title" className="agent-mcp-managed__runtime">
      <header>
        <span>
          <h5 id="agent-mcp-runtime-title">Project tool host</h5>
          <small>Explicit start, current app run only, no automatic restart.</small>
        </span>
        <button
          className="button button--ghost"
          disabled={!admitted || busy !== null || statusState === "loading"}
          onClick={refresh}
          type="button"
        >
          Refresh status
        </button>
      </header>

      {!projectId && <p>Choose an Agent project to inspect its runtime.</p>}
      {projectId && !admitted && <p>Save at least one reviewed tool for this project before starting a host.</p>}
      {admitted && statusState === "loading" && <p role="status">Reading host status… This does not start it.</p>}
      {admitted && statusState === "unavailable" && <p role="alert">Host status is unavailable. No host was started by this read.</p>}
      {statusState === "ready" && status !== null && (
        <>
          <dl className="agent-mcp-managed__status-grid">
            <div><dt>Host</dt><dd>{stateLabels[status.state]}</dd></div>
            <div><dt>Routing</dt><dd>{status.tool_calls_available ? "Project scoped" : "Inactive"}</dd></div>
            <div><dt>Process</dt><dd>{status.process_started ? "Hidden local process" : "No local process"}</dd></div>
            <div><dt>Cleanup</dt><dd>{status.cleanup_state.replaceAll("_", " ")}</dd></div>
          </dl>
          {staleBinding && (
            <p role="alert">The saved plan changed after this host was bound. Stop it before starting the current revision.</p>
          )}
          {status.state === "cleanup_required" && (
            <p role="alert">Cleanup could not be verified. Starting is blocked until the managed-package recovery flow settles it.</p>
          )}
          {status.error_code !== null && (
            <p role="alert">Runtime evidence: {runtimeEvidenceMessage(status.error_code)}</p>
          )}

          {status.state === "not_started" && (
            <div className="agent-mcp-managed__runtime-preview">
              {previewState === "loading" && <p>Preparing the exact start disclosure…</p>}
              {previewState === "unavailable" && <p role="alert">Start is unavailable for this exact plan. Check installation, configuration, permissions, and tool review.</p>}
              {previewState === "ready" && preview !== null && (
                <>
                  <p>
                    {preview.execution_kind === "local_native_process"
                      ? "This starts reviewed native code with your current Windows account authority."
                      : "This opens the reviewed remote endpoint using its configured authority."}
                  </p>
                  <details>
                    <summary>Review {preview.effects.length} exact start effects</summary>
                    <ul>{preview.effects.map((effect) => <li key={effect}>{effectLabels[effect]}</li>)}</ul>
                    <small>Preview · <code>{preview.preview_digest.slice(0, 12)}</code></small>
                  </details>
                  <button
                    className="button button--primary"
                    disabled={staleBinding || !userPresenceAvailable || busy !== null || transport.startMcpManagedHost === undefined}
                    onClick={() => void start()}
                    type="button"
                  >
                    {busy === "start" ? "Confirming and starting…" : "Start for this app run"}
                  </button>
                  {!userPresenceAvailable && <small>Open the native app window to confirm this authority-increasing action.</small>}
                </>
              )}
            </div>
          )}

          {status.state !== "not_started" && status.state !== "cleanup_required" && (
            <button
              className="button button--ghost"
              disabled={busy !== null || transport.stopMcpManagedHost === undefined}
              onClick={() => void stop()}
              type="button"
            >
              {busy === "stop" ? "Stopping and verifying…" : "Stop host"}
            </button>
          )}

          {status.state === "ready" && (
            <div className="agent-mcp-managed__runtime-tools">
              {runtimeState === "loading" && <p>Reading routed tool aliases…</p>}
              {runtimeState === "unavailable" && <p role="alert">The routed-tool projection is unavailable; calls remain blocked unless the Agent can revalidate it.</p>}
              {runtimeState === "ready" && (
                <>
                  <p><strong>{serverTools.length}</strong> tool{serverTools.length === 1 ? "" : "s"} from this server are available to this project.</p>
                  {serverTools.length > 0 && (
                    <ul>
                      {serverTools.map((tool) => (
                        <li key={tool.tool_id}>
                          <span><strong>{tool.title ?? tool.name}</strong><code>{tool.model_alias}</code></span>
                          <small>Fresh confirmation on every call</small>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
