import { useCallback, useEffect, useMemo, useState } from "react";

import type { PromptEnhancerTransport } from "../../shared/api/contracts";
import {
  AGENT_LEGACY_PARITY,
  AGENT_PARITY_SUMMARY,
  AGENT_REQUESTED_CAPABILITIES,
  type AgentParityItem,
  type AgentRequestedCapability,
} from "./agentReleaseParity";

import "./AgentReadinessPanel.css";

type RequestedCapabilityState = Readonly<{
  automated: boolean;
  implementation: AgentParityItem["implementation"];
  ownerGate: AgentParityItem["ownerGate"];
}>;

type ReadinessTransport = Partial<Pick<PromptEnhancerTransport, "getAgentOrchestration">>;
type LoopbackState = "checking" | "integrated" | "blocked";

function requestedCapabilityState(capability: AgentRequestedCapability): RequestedCapabilityState {
  const items = capability.parityKeys.map((key) => AGENT_LEGACY_PARITY.find((item) => item.key === key));
  if (items.some((item) => item === undefined)) {
    return { automated: false, implementation: "missing", ownerGate: "blocked" };
  }
  const evidence = items as AgentParityItem[];
  const implementation = evidence.some((item) => item.implementation === "missing")
    ? "missing"
    : evidence.some((item) => item.implementation === "partial")
      ? "partial"
      : "complete";
  const ownerGate = evidence.some((item) => item.ownerGate === "blocked")
    ? "blocked"
    : evidence.some((item) => item.ownerGate === "pending")
      ? "pending"
      : "not_required";
  return {
    automated: evidence.every((item) => item.automatedEvidence),
    implementation,
    ownerGate,
  };
}

function stateLabel(
  capability: AgentRequestedCapability,
  state: RequestedCapabilityState,
  loopbackState: LoopbackState,
  userPresenceAvailable: boolean,
): string {
  if (state.implementation === "missing") return "Missing";
  if (state.implementation === "partial") return "Partial";
  if (!state.automated) return "Tests missing";
  if (state.ownerGate === "blocked") return "Platform blocked";
  if (capability.evidenceBoundary === "loopback" && loopbackState === "checking") {
    return "Checking loopback integration";
  }
  if (capability.evidenceBoundary === "loopback" && loopbackState === "blocked") {
    return "Blocked · loopback contract unavailable";
  }
  if (state.ownerGate === "pending" && !userPresenceAvailable) {
    return "Blocked here · native owner check unavailable";
  }
  if (state.ownerGate === "pending") {
    return capability.evidenceBoundary === "loopback"
      ? "Loopback integrated · owner check pending"
      : "Contract verified · owner check pending";
  }
  return capability.evidenceBoundary === "loopback" ? "Loopback integrated" : "Contract verified";
}

export function AgentReadinessPanel({
  onOpenConnections,
  onOpenOwnerChecks,
  transport,
  userPresenceAvailable,
}: {
  onOpenConnections: () => void;
  onOpenOwnerChecks: () => void;
  transport: ReadinessTransport;
  userPresenceAvailable: boolean;
}) {
  const [loopbackState, setLoopbackState] = useState<LoopbackState>("checking");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const inspect = transport.getAgentOrchestration;
    if (inspect === undefined) {
      setLoopbackState("blocked");
      return;
    }
    const controller = new AbortController();
    setLoopbackState("checking");
    void inspect(controller.signal).then(() => {
      if (!controller.signal.aborted) setLoopbackState("integrated");
    }).catch(() => {
      if (!controller.signal.aborted) setLoopbackState("blocked");
    });
    return () => controller.abort();
  }, [attempt, transport.getAgentOrchestration]);

  const ownerLabel = userPresenceAvailable
    ? `${AGENT_PARITY_SUMMARY.ownerPending} pending`
    : `${AGENT_PARITY_SUMMARY.ownerPending} blocked here`;
  const loopbackLabel = loopbackState === "integrated"
    ? "Integrated"
    : loopbackState === "checking"
      ? "Checking…"
      : "Unavailable";
  const visibleState = useMemo(() => {
    if (loopbackState !== "integrated") return loopbackState;
    return userPresenceAvailable || AGENT_PARITY_SUMMARY.ownerPending === 0 ? "integrated" : "blocked";
  }, [loopbackState, userPresenceAvailable]);

  return (
    <section aria-labelledby="agent-readiness-title" className="agent-readiness">
      <header>
        <span>
          <small>Current implementation snapshot</small>
          <h3 id="agent-readiness-title">Agent capability readiness</h3>
        </span>
        <span aria-live="polite" className="agent-readiness__state" data-state={visibleState}>
          {loopbackState === "checking"
            ? "Checking live evidence"
            : loopbackState === "blocked"
              ? "Loopback unavailable"
              : userPresenceAvailable
                ? "Loopback integrated"
                : "Owner checks blocked here"}
        </span>
      </header>

      <p className="agent-readiness__truth">
        Contract tests, this running loopback app, and owner-only checks are reported separately. A verified contract
        is not a claim that a real model, microphone, separate window, or GPU cleanup was exercised today.
      </p>

      <dl aria-label="Agent readiness summary" className="agent-readiness__facts">
        <div><dt>Contract evidence</dt><dd>{AGENT_PARITY_SUMMARY.missing === 0 ? "Verified" : "Incomplete"}</dd></div>
        <div><dt>Running loopback</dt><dd>{loopbackLabel}</dd></div>
        <div><dt>Owner checks</dt><dd>{ownerLabel}</dd></div>
        <div><dt>Platform blockers</dt><dd>{AGENT_PARITY_SUMMARY.platformBlocked}</dd></div>
      </dl>

      {loopbackState === "blocked" && (
        <div className="agent-readiness__live-failure" role="status">
          <span>The running Agent contract could not be verified. Static test evidence remains visible, but it is not a live pass.</span>
          {transport.getAgentOrchestration !== undefined && (
            <button className="button button--ghost" onClick={retry} type="button">Retry live check</button>
          )}
        </div>
      )}

      <div className="agent-readiness__section-head">
        <span>
          <small>Reconciled checklist</small>
          <strong>Requested Codex/Claude-style capabilities</strong>
        </span>
        <small>Automated and owner evidence stay separate.</small>
      </div>
      <ul aria-label="Requested Agent capabilities" className="agent-readiness__capabilities">
        {AGENT_REQUESTED_CAPABILITIES.map((capability) => {
          const state = requestedCapabilityState(capability);
          return (
            <li
              data-automated={state.automated ? "true" : "false"}
              data-evidence-state={
                capability.evidenceBoundary === "loopback" && loopbackState !== "integrated"
                  ? loopbackState
                  : state.ownerGate === "pending" && !userPresenceAvailable
                    ? "blocked"
                    : state.ownerGate === "pending"
                      ? "owner-pending"
                      : capability.evidenceBoundary === "loopback"
                        ? "integrated"
                        : "contract"
              }
              data-implementation={state.implementation}
              data-owner-gate={state.ownerGate}
              key={capability.key}
            >
              <span>{capability.label}</span>
              <strong>{stateLabel(capability, state, loopbackState, userPresenceAvailable)}</strong>
            </li>
          );
        })}
      </ul>

      <div className="agent-readiness__notes">
        <p>
          <strong>External orchestration:</strong> the loopback controller and MCP workflow are implemented and
          contract-tested. Creating a real one-time connection remains an explicit native-confirmed action in
          Connections; Prompt Enhancer never edits Codex or Claude configuration itself.
        </p>
        <p>
          <strong>Projects:</strong> the left rail contains editable Agent projects and chats. The application’s
          separate global Projects and Sessions pages remain read-only analytics catalogues for imported provider data.
        </p>
      </div>

      <div className="agent-readiness__actions">
        <button className="button button--ghost" onClick={onOpenConnections} type="button">Open connections</button>
        <button className="button button--primary" onClick={onOpenOwnerChecks} type="button">Open owner checks</button>
      </div>
    </section>
  );
}
