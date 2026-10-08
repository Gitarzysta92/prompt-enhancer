import type {
  AgentEvent,
  AgentMcpToolDescriptor,
} from "../../shared/api/contracts";
import { AgentCopyButton } from "./AgentCopyButton";
import "./AgentMcpToolActivity.css";

export type AgentMcpCallActivity = {
  callId: string;
  request: AgentEvent | null;
  approval: AgentEvent | null;
  resolution: AgentEvent | null;
  result: AgentEvent | null;
  descriptor: AgentMcpToolDescriptor | null;
};

export function isManagedMcpAlias(tool: string | null | undefined): boolean {
  return Boolean(tool?.startsWith("mcp_"));
}

export function mcpToolLabel(
  descriptor: AgentMcpToolDescriptor | null | undefined,
): string {
  return descriptor?.tool_title ?? descriptor?.tool_name ?? "Managed MCP tool";
}

export function mcpServerLabel(
  descriptor: AgentMcpToolDescriptor | null | undefined,
): string {
  return descriptor?.server_title ?? "Managed MCP server";
}

function emptyCall(callId: string): AgentMcpCallActivity {
  return {
    callId,
    request: null,
    approval: null,
    resolution: null,
    result: null,
    descriptor: null,
  };
}

/**
 * Coalesce one model request, native review and terminal result into one card.
 * Exact call identity prevents activity from adjacent/repeated tools merging.
 */
export function collectAgentMcpCalls(
  events: readonly AgentEvent[],
): Map<string, AgentMcpCallActivity> {
  const calls = new Map<string, AgentMcpCallActivity>();
  for (const event of events) {
    const callId = event.call_id ?? null;
    const current = callId ? calls.get(callId) : undefined;
    const managed = Boolean(current)
      || Boolean(event.mcp_tool)
      || (event.kind === "tool_call" && isManagedMcpAlias(event.tool));
    if (!callId || !managed) continue;
    const next = current ?? emptyCall(callId);
    if (event.kind === "tool_call") next.request = event;
    else if (event.kind === "approval_required") next.approval = event;
    else if (event.kind === "approval_resolved") next.resolution = event;
    else if (event.kind === "tool_result") next.result = event;
    if (event.mcp_tool) next.descriptor = event.mcp_tool;
    calls.set(callId, next);
  }
  return calls;
}

function statusFor(
  call: AgentMcpCallActivity,
  interrupted: boolean,
  stopping: boolean,
): {
  label: string;
  state: string;
  tone: "neutral" | "attention" | "ready" | "error";
} {
  const result = call.result;
  if (result) {
    if (result.tool_state === "succeeded") {
      return { label: "Completed", state: "completed", tone: "ready" };
    }
    if (result.tool_state === "unverified") {
      return { label: "Cleanup uncertain", state: "unverified", tone: "error" };
    }
    if (result.tool_state === "cancelled") {
      return { label: "Cancelled", state: "cancelled", tone: "attention" };
    }
    if (result.tool_state === "not_approved") {
      const approval = result.execution_receipt?.approval_state;
      if (approval === "timed_out") {
        return { label: "Approval timed out", state: "timed_out", tone: "attention" };
      }
      if (approval === "cancelled_before_decision") {
        return { label: "Cancelled before invocation", state: "cancelled", tone: "attention" };
      }
      return { label: "Not approved", state: "denied", tone: "attention" };
    }
    if (result.mcp_result?.outcome === "tool_error") {
      return { label: "Tool reported an error", state: "tool_error", tone: "error" };
    }
    return { label: "Failed", state: "failed", tone: "error" };
  }
  if (stopping) {
    return { label: "Cancelling", state: "cancelling", tone: "attention" };
  }
  if (call.resolution?.ok === true) {
    return { label: "Running", state: "running", tone: "attention" };
  }
  if (call.resolution?.ok === false) {
    return {
      label: call.resolution.text ? "Approval timed out" : "Not approved",
      state: call.resolution.text ? "timed_out" : "denied",
      tone: "attention",
    };
  }
  if (call.approval) {
    return { label: "Waiting for approval", state: "waiting", tone: "attention" };
  }
  if (interrupted) {
    return { label: "Interrupted", state: "interrupted", tone: "error" };
  }
  return { label: "Preparing review", state: "requested", tone: "neutral" };
}

function readableBytes(value: number): string {
  if (value === 0) return "No result bytes";
  if (value < 1024) return `${value.toLocaleString()} B`;
  return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
}

function contentModeLabel(value: NonNullable<AgentEvent["mcp_result"]>["content_mode"]): string {
  return {
    text: "Text result",
    structured_json: "Structured result",
    text_and_structured_json: "Text + structured result",
    none: "No result content",
  }[value];
}

function approvalLabel(event: AgentEvent): string | null {
  const state = event.execution_receipt?.approval_state;
  if (!state) return null;
  return {
    not_required: "Approval not required",
    not_requested: "Approval not requested",
    approved: "Approved once",
    denied: "Denied",
    timed_out: "Approval timed out",
    cancelled_before_decision: "Cancelled before decision",
  }[state];
}

function evidenceLabel(event: AgentEvent): string | null {
  const state = event.execution_receipt?.evidence_state;
  if (!state) return null;
  return {
    read_only_observation: "Read-only observation",
    verified_workspace_effect: "Verified workspace effect",
    unverified_workspace_effect: "Workspace effect unverified",
    untracked_external_effect: "External effect not verified",
    no_effect: "No invocation effect",
    unknown: "Effect unknown",
  }[state];
}

function elapsedLabel(event: AgentEvent): string | null {
  const value = event.execution_receipt?.elapsed_ms;
  if (value === null || value === undefined) {
    return event.execution_receipt ? "Elapsed unknown" : null;
  }
  return value < 1_000
    ? `${Number(value.toFixed(value < 10 ? 1 : 0))} ms`
    : `${Number((value / 1_000).toFixed(2))} s`;
}

function progressSteps(call: AgentMcpCallActivity, terminalLabel: string): string[] {
  const steps = ["Requested by the model"];
  if (call.approval) steps.push("Fresh native review presented");
  if (call.resolution) {
    steps.push(call.resolution.ok ? "Approved for one invocation" : "Approval not granted");
  }
  if (call.result) steps.push(terminalLabel);
  return steps;
}

function managedFailureGuidance(errorCode: string | null | undefined): string | null {
  if (!errorCode) return null;
  if (errorCode === "mcp_host_cleanup_unconfirmed") {
    return "Cleanup could not be verified. Recover or stop this MCP host before starting it or invoking another tool.";
  }
  if (errorCode === "mcp_tool_receipt_unavailable"
    || errorCode === "mcp_tool_receipt_storage_unavailable"
    || errorCode === "mcp_tool_receipt_storage_corrupt") {
    return "The call may have run, but durable execution evidence could not be saved. Do not retry it until storage and host state are reconciled.";
  }
  if (errorCode === "mcp_tool_result_content_unsupported"
    || errorCode === "mcp_tool_result_incomplete"
    || errorCode === "mcp_tool_result_malformed"
    || errorCode === "mcp_tool_result_schema_mismatch"
    || errorCode === "mcp_tool_result_too_complex"
    || errorCode === "mcp_tool_result_too_large") {
    return "The server result failed a bounded safety check and its host was stopped. Review or update the MCP server before trying again.";
  }
  if (errorCode === "mcp_tool_admission_stale"
    || errorCode === "mcp_tool_arguments_changed"
    || errorCode === "mcp_tool_host_not_ready") {
    return "The reviewed tool, arguments, or host changed before invocation. Refresh the project tools and restart the host from the current plan.";
  }
  return null;
}

export function AgentMcpToolActivity({
  call,
  interrupted = false,
  stopping = false,
}: {
  call: AgentMcpCallActivity;
  interrupted?: boolean;
  stopping?: boolean;
}) {
  const status = statusFor(call, interrupted, stopping);
  const result = call.result;
  const receipt = result?.mcp_result ?? null;
  const failureGuidance = managedFailureGuidance(receipt?.error_code);
  const title = mcpToolLabel(call.descriptor);
  const server = mcpServerLabel(call.descriptor);
  const facts = result
    ? [elapsedLabel(result), approvalLabel(result), evidenceLabel(result)].filter(Boolean) as string[]
    : [];

  if (receipt) {
    facts.push(
      receipt.outcome === "not_invoked" ? "Not invoked" : contentModeLabel(receipt.content_mode),
      readableBytes(receipt.result_bytes),
      receipt.cleanup_verified ? "Cleanup verified" : "Cleanup uncertain",
    );
  }

  return (
    <article
      aria-label={`MCP tool call: ${title} from ${server}. ${status.label}`}
      className="agent-mcp-call"
      data-state={status.state}
      data-tone={status.tone}
    >
      <header className="agent-mcp-call__header">
        <span aria-hidden="true" className="agent-mcp-call__mark">MCP</span>
        <span className="agent-mcp-call__identity">
          <strong>{title}</strong>
          <small>{server}</small>
        </span>
        <span className="agent-mcp-call__status" data-tone={status.tone}>{status.label}</span>
      </header>
      <p className="agent-mcp-call__authority">
        External project tool · fresh native approval for this call only
      </p>
      {facts.length > 0 && (
        <ul aria-label="MCP execution facts" className="agent-mcp-call__facts">
          {facts.map((fact) => <li key={fact}>{fact}</li>)}
        </ul>
      )}
      {failureGuidance && (
        <p className="agent-mcp-call__retention-note">
          <strong>Recovery</strong> · {failureGuidance}
        </p>
      )}
      <details className="agent-mcp-call__details">
        <summary>Call details</summary>
        <dl>
          <div><dt>Server</dt><dd>{server}</dd></div>
          <div><dt>Reviewed tool</dt><dd>{call.descriptor?.tool_name ?? "Unavailable"}</dd></div>
          <div><dt>Approval policy</dt><dd>One native decision; never remembered</dd></div>
          <div><dt>Result retention</dt><dd>Raw result text is not retained in local history</dd></div>
        </dl>
        <ol aria-label="MCP call progress" className="agent-mcp-call__progress">
          {progressSteps(call, status.label).map((step) => <li key={step}>{step}</li>)}
        </ol>
        {result?.text ? (
          <div className="agent-mcp-call__result">
            <span>Bounded result returned to this Agent turn</span>
            <AgentCopyButton label={`Copy ${title} result`} value={result.text} />
            <pre>{result.text}</pre>
          </div>
        ) : result ? (
          <p className="agent-mcp-call__retention-note">
            Result text is unavailable in this view. The content-free execution receipt remains.
          </p>
        ) : (
          <p className="agent-mcp-call__retention-note">
            No invocation has completed.
          </p>
        )}
      </details>
    </article>
  );
}
