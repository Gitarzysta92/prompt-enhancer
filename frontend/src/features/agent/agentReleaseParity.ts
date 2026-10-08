export type AgentParityImplementation = "complete" | "partial" | "missing";
export type AgentParityOwnerGate = "not_required" | "pending" | "blocked";

export type AgentParityItem = Readonly<{
  key: string;
  label: string;
  implementation: AgentParityImplementation;
  automatedEvidence: boolean;
  ownerGate: AgentParityOwnerGate;
}>;

export type AgentRequestedCapability = Readonly<{
  key: string;
  label: string;
  evidenceBoundary: "contract" | "loopback";
  parityKeys: readonly AgentParityItem["key"][];
}>;

/**
 * The retirement ledger is deliberately explicit. A legacy surface cannot be
 * removed by silently dropping one of these entries or treating owner evidence
 * as an automated pass.
 */
export const AGENT_LEGACY_PARITY: readonly AgentParityItem[] = [
  { key: "project_catalog", label: "Create, browse, search, rename, pin, archive, restore, and delete projects", implementation: "complete", automatedEvidence: true, ownerGate: "not_required" },
  { key: "chat_catalog", label: "Create, browse, switch, move, close, archive, restore, and delete chats", implementation: "complete", automatedEvidence: true, ownerGate: "not_required" },
  { key: "retained_history", label: "Retained chat history survives restart without restoring mutation authority", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "streaming_stop", label: "Streaming text chat and bounded Stop", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "reasoning_tools", label: "Model-provided reasoning, progress, tool activity, and turn receipts", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "workspace_review", label: "Workspace files, reviewed edits, transactions, changes, and diffs", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "protected_approvals", label: "Revision-bound native approvals and cleanup quarantine", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "artifacts", label: "Typed artifact cards, immutable versions, viewers, and download", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "multimodal", label: "Capability-gated images, audio files, and local recording", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "runtime", label: "One shared runtime, model switching, CPU/GPU placement, and cleanup evidence", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "context", label: "Exact-or-unknown context usage without invented estimates", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
  { key: "controller", label: "Provider-neutral controller discovery and finite turn orchestration", implementation: "complete", automatedEvidence: true, ownerGate: "not_required" },
  { key: "retention_export", label: "Retention choice, deletion cascades, and bounded history export", implementation: "complete", automatedEvidence: true, ownerGate: "not_required" },
  { key: "responsive_accessibility", label: "Desktop, 320 px, keyboard, focus, and forced-colors behavior", implementation: "complete", automatedEvidence: true, ownerGate: "not_required" },
  { key: "session_branching", label: "Session branching and forking", implementation: "complete", automatedEvidence: true, ownerGate: "not_required" },
  { key: "separate_native_window", label: "Separate native chat window without lifecycle duplication", implementation: "complete", automatedEvidence: true, ownerGate: "pending" },
] as const;

export const AGENT_PARITY_SUMMARY = Object.freeze({
  total: AGENT_LEGACY_PARITY.length,
  complete: AGENT_LEGACY_PARITY.filter((item) => item.implementation === "complete").length,
  missing: AGENT_LEGACY_PARITY.filter((item) => item.implementation === "missing").length,
  ownerPending: AGENT_LEGACY_PARITY.filter((item) => item.ownerGate === "pending").length,
  platformBlocked: AGENT_LEGACY_PARITY.filter((item) => item.ownerGate === "blocked").length,
});

/**
 * User-facing reconciliation of the original Agent capability checklist. It is
 * deliberately separate from the finer retirement ledger: one requested row
 * may depend on several independently verified safety capabilities.
 */
export const AGENT_REQUESTED_CAPABILITIES: readonly AgentRequestedCapability[] = [
  { key: "chat_lifecycle", label: "Create, browse, switch, close, rename, search, pin, archive, and restore chats", evidenceBoundary: "loopback", parityKeys: ["chat_catalog"] },
  { key: "streaming", label: "Text chat, streaming responses, and Stop", evidenceBoundary: "loopback", parityKeys: ["streaming_stop"] },
  { key: "reasoning", label: "Model-provided reasoning, progress, tool activity, and exact turn receipts", evidenceBoundary: "loopback", parityKeys: ["reasoning_tools"] },
  { key: "workspace", label: "Create, view, edit, move, trash, diff, and review workspace files with protected approvals", evidenceBoundary: "loopback", parityKeys: ["workspace_review", "protected_approvals"] },
  { key: "window", label: "Separate native chat window with one shared session lifecycle", evidenceBoundary: "contract", parityKeys: ["separate_native_window"] },
  { key: "projects", label: "Durable Agent projects and project/session database hierarchy", evidenceBoundary: "loopback", parityKeys: ["project_catalog", "chat_catalog"] },
  { key: "restart", label: "Retained chats survive app restart without restoring mutation authority", evidenceBoundary: "loopback", parityKeys: ["retained_history"] },
  { key: "markdown", label: "Safe rich Markdown, tables, workspace links, and fenced code rendering", evidenceBoundary: "contract", parityKeys: ["reasoning_tools", "responsive_accessibility"] },
  { key: "artifacts", label: "Versioned artifact/document cards, viewers, review, reveal, and download", evidenceBoundary: "loopback", parityKeys: ["artifacts"] },
  { key: "media", label: "Capability-gated image, audio-file, and local recording input", evidenceBoundary: "loopback", parityKeys: ["multimodal"] },
  { key: "runtime", label: "Reliable model switching, CPU/GPU placement, unload, and cleanup evidence", evidenceBoundary: "loopback", parityKeys: ["runtime"] },
  { key: "context", label: "Exact-or-unknown context usage without invented estimates", evidenceBoundary: "loopback", parityKeys: ["context"] },
  { key: "branching", label: "Session branching, forking, bounded export, and deletion cascades", evidenceBoundary: "loopback", parityKeys: ["session_branching", "retention_export"] },
  { key: "controller", label: "Provider-neutral controller and MCP endpoint for Codex, Claude, and other local orchestrators", evidenceBoundary: "loopback", parityKeys: ["controller"] },
  { key: "responsive", label: "Desktop, 320 px, keyboard, focus, forced-colors, and reduced-motion behavior", evidenceBoundary: "contract", parityKeys: ["responsive_accessibility"] },
] as const;
