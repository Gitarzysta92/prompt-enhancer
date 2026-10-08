import { useEffect, useMemo, useState } from "react";

import type {
  McpManagedProjectRuntime,
  McpManagedServer,
  McpManagedServerList,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import "./AgentMcpProjectToolsPanel.css";

type ProjectToolsTransport = Partial<Pick<
  PromptEnhancerTransport,
  "listMcpManagedServers" | "getMcpManagedProjectRuntime"
>>;

type ProjectToolsState = "idle" | "loading" | "ready" | "unavailable";

interface ProjectToolsSnapshot {
  managed: McpManagedServerList;
  runtime: McpManagedProjectRuntime;
}

function bindingForProject(server: McpManagedServer, projectId: string) {
  return server.project_bindings.find((binding) => binding.project_id === projectId);
}

export function AgentMcpProjectToolsPanel({
  onOpenStore,
  projectId,
  refreshKey = 0,
  transport,
}: {
  onOpenStore: () => void;
  projectId: string | null;
  refreshKey?: number;
  transport: ProjectToolsTransport;
}) {
  const [state, setState] = useState<ProjectToolsState>(projectId ? "loading" : "idle");
  const [snapshot, setSnapshot] = useState<ProjectToolsSnapshot | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setSnapshot(null);
    if (projectId === null) {
      setState("idle");
      return;
    }
    const listManaged = transport.listMcpManagedServers;
    const getRuntime = transport.getMcpManagedProjectRuntime;
    if (listManaged === undefined || getRuntime === undefined) {
      setState("unavailable");
      return;
    }
    const controller = new AbortController();
    setState("loading");
    void Promise.all([
      listManaged(controller.signal),
      getRuntime(projectId, controller.signal),
    ]).then(([managed, runtime]) => {
      if (controller.signal.aborted) return;
      if (runtime.project_id !== projectId) {
        setSnapshot(null);
        setState("unavailable");
        return;
      }
      setSnapshot({ managed, runtime });
      setState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setSnapshot(null);
      setState("unavailable");
    });
    return () => controller.abort();
  }, [attempt, projectId, refreshKey, transport.getMcpManagedProjectRuntime, transport.listMcpManagedServers]);

  const projection = useMemo(() => {
    if (snapshot === null || projectId === null) return null;
    const enabled = snapshot.managed.servers.flatMap((server) => {
      const binding = bindingForProject(server, projectId);
      return binding?.enabled ? [{ server, binding }] : [];
    });
    const admitted = enabled.filter(({ binding }) => (
      binding.admission_state === "admitted"
      && binding.tool_snapshot_id !== null
      && binding.admitted_tool_ids.length > 0
    ));
    const admissionByServer = new Map(admitted.map((entry) => [entry.server.management_id, entry]));
    const readyServerIds = new Set(snapshot.runtime.tools.map((tool) => tool.management_id));
    const stale = snapshot.runtime.ready_tool_count !== snapshot.runtime.tools.length
      || snapshot.runtime.ready_host_count > admitted.length
      || snapshot.runtime.tools.some((tool) => {
        const entry = admissionByServer.get(tool.management_id);
        return tool.project_id !== projectId
          || entry === undefined
          || entry.binding.tool_snapshot_id !== entry.server.tool_snapshot?.snapshot_id
          || !entry.binding.admitted_tool_ids.includes(tool.tool_id);
      });
    return {
      admittedCount: admitted.length,
      installRequiredCount: enabled.filter(({ binding }) => binding.effective_state === "inactive_install_required").length,
      readyHostCount: stale ? 0 : snapshot.runtime.ready_host_count,
      readyTools: stale ? [] : snapshot.runtime.tools,
      reviewRequiredCount: enabled.filter(({ binding }) => binding.admission_state === "review_required").length,
      stale,
      stoppedCount: stale ? admitted.length : admitted.filter(({ server }) => !readyServerIds.has(server.management_id)).length,
    };
  }, [projectId, snapshot]);

  const summary = projectId === null
    ? "No project scope"
    : state === "loading"
      ? "Checking exact state"
      : state === "unavailable" || projection === null
        ? "Status unavailable"
        : projection.stale
          ? "Refresh required"
          : projection.readyTools.length > 0
            ? `${projection.readyTools.length} ready`
            : projection.reviewRequiredCount > 0
              ? "Review required"
              : projection.admittedCount > 0
                ? `${projection.admittedCount} admitted · stopped`
                : "No admitted tools";

  return (
    <details className="agent-mcp-project-tools" data-state={projection?.stale ? "stale" : state}>
      <summary>
        <span>
          <small>Project tools</small>
          <strong>{summary}</strong>
        </span>
        <span aria-hidden="true">⌄</span>
      </summary>
      <div className="agent-mcp-project-tools__body">
        <p className="agent-mcp-project-tools__boundary">
          This is last-confirmed local state. Every message and every MCP call revalidates the active project,
          binding revision and exact tool snapshot; no approval is remembered.
        </p>
        {projectId === null && (
          <p role="status">This chat has no durable Agent project, so project-scoped MCP tools remain unavailable.</p>
        )}
        {projectId !== null && state === "loading" && (
          <p aria-busy="true" role="status">Checking durable admissions and current app-run hosts…</p>
        )}
        {projectId !== null && state === "unavailable" && (
          <p role="alert">Project MCP status could not be reconciled. No ready tool authority is being claimed.</p>
        )}
        {projection?.stale && (
          <p role="alert">
            Durable admission and the runtime projection changed while loading. Ready tools are hidden until a fresh read agrees.
          </p>
        )}
        {state === "ready" && projection !== null && !projection.stale && (
          <>
            <dl>
              <div><dt>Admitted plans</dt><dd>{projection.admittedCount}</dd></div>
              <div><dt>Ready hosts</dt><dd>{projection.readyHostCount}</dd></div>
              <div><dt>Ready tools</dt><dd>{projection.readyTools.length}</dd></div>
              <div><dt>Stopped plans</dt><dd>{projection.stoppedCount}</dd></div>
            </dl>
            {projection.reviewRequiredCount > 0 && (
              <p role="status">{projection.reviewRequiredCount} plan{projection.reviewRequiredCount === 1 ? " needs" : "s need"} permission or tool review.</p>
            )}
            {projection.installRequiredCount > 0 && (
              <p role="status">{projection.installRequiredCount} admitted plan{projection.installRequiredCount === 1 ? " requires" : "s require"} installation or activation before host start.</p>
            )}
            {projection.readyTools.length > 0 ? (
              <ul>
                {projection.readyTools.slice(0, 6).map((tool) => (
                  <li key={`${tool.host_instance_id}:${tool.tool_id}`}>
                    <span><strong>{tool.title ?? tool.name}</strong><small>{tool.server_title}</small></span>
                    <code>{tool.model_alias}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No MCP tool is currently routed into this chat project. Stopped hosts never auto-start.</p>
            )}
            {projection.readyTools.length > 6 && <small>{projection.readyTools.length - 6} more ready tools are available in the managed plan.</small>}
          </>
        )}
        <div className="agent-mcp-project-tools__actions">
          <button className="button button--ghost" onClick={onOpenStore} type="button">Manage in MCP Store</button>
          {projectId !== null && transport.listMcpManagedServers && transport.getMcpManagedProjectRuntime && (
            <button className="button button--ghost" disabled={state === "loading"} onClick={() => setAttempt((value) => value + 1)} type="button">
              {state === "loading" ? "Refreshing…" : "Refresh project tools"}
            </button>
          )}
        </div>
      </div>
    </details>
  );
}
