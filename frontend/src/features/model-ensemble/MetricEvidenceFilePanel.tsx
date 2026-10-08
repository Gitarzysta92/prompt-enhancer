import { useEffect, useId, useMemo, useRef, useState } from "react";
import type {
  AgentMetricEvidencePreview,
  MetricLifecycleProposal,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import "./MetricEvidenceFilePanel.css";

const IMPORT_CONFIRMATION = "import_agent_metric_evidence_as_unconfirmed_proposal";
const DECISION_CONFIRMATION = "apply_local_user_metric_lifecycle_decision";
const EVIDENCE_MEDIA_TYPE = "application/vnd.prompt-enhancer.agent-metric-evidence+json";
const MAX_FILE_BYTES = 64 * 1024;
const NO_PROPOSALS: readonly MetricLifecycleProposal[] = [];

type PendingDecision = {
  proposalId: string;
  decision: "confirm" | "reject";
};

type PanelError = {
  kind: "load" | "validation" | "stale" | "action";
  message: string;
};

type EvidenceTransport = Pick<PromptEnhancerTransport,
  | "previewAgentMetricEvidence"
  | "importAgentMetricEvidence"
  | "listMetricLifecycleProposals"
  | "decideMetricLifecycleProposal">
  & Partial<Pick<PromptEnhancerTransport, "getUserPresenceCapability">>;

function idempotency(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "")}`;
}

function proposalLabel(proposal: MetricLifecycleProposal): string {
  return `${proposal.family.replace("collaboration.", "").replaceAll("_", " ")} · ${proposal.proposal_kind}`;
}

function bindingKey(sessionId: string, sourceRunId: string): string {
  return `${sessionId}:${sourceRunId}`;
}

function isExactProposal(
  proposal: MetricLifecycleProposal,
  sessionId: string,
  sourceRunId: string,
): boolean {
  return proposal.session_id === sessionId && proposal.source_run_id === sourceRunId;
}

function isAcceptedFile(file: File): boolean {
  const mediaType = file.type.toLowerCase();
  return file.name.toLowerCase().endsWith(".json")
    && (mediaType === "" || mediaType === "application/json" || mediaType === EVIDENCE_MEDIA_TYPE);
}

export function MetricEvidenceFilePanel({
  compact,
  sessionId,
  sourceRunId,
  transport,
  onEvidenceChanged,
}: {
  compact: boolean;
  sessionId: string;
  sourceRunId: string;
  transport: EvidenceTransport;
  onEvidenceChanged?: () => void;
}) {
  const headingId = useId();
  const fileHelpId = useId();
  const proposalsHeadingId = useId();
  const currentBinding = bindingKey(sessionId, sourceRunId);
  const [stateBinding, setStateBinding] = useState(currentBinding);
  const [stateTransport, setStateTransport] = useState(transport);
  const [proposals, setProposals] = useState<MetricLifecycleProposal[]>([]);
  const [preview, setPreview] = useState<AgentMetricEvidencePreview | null>(null);
  const [payload, setPayload] = useState<ArrayBuffer | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PanelError | null>(null);
  const [notice, setNotice] = useState("");
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [confirmationAvailable, setConfirmationAvailable] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const operationRef = useRef<AbortController | null>(null);
  const bindingRef = useRef(currentBinding);
  const transportRef = useRef(transport);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const noticeRef = useRef<HTMLParagraphElement | null>(null);
  const focusNoticeOnUpdateRef = useRef(false);
  const decisionActionRef = useRef<HTMLButtonElement | null>(null);
  const decisionTriggerRef = useRef<HTMLButtonElement | null>(null);
  const decisionOriginRef = useRef<PendingDecision | null>(null);
  const restoreDecisionFocusRef = useRef(false);
  bindingRef.current = currentBinding;
  transportRef.current = transport;

  const capabilities = transport.previewAgentMetricEvidence !== undefined
    && transport.importAgentMetricEvidence !== undefined
    && transport.listMetricLifecycleProposals !== undefined
    && transport.decideMetricLifecycleProposal !== undefined;

  useEffect(() => {
    const binding = bindingKey(sessionId, sourceRunId);
    operationRef.current?.abort();
    setProposals([]);
    setPreview(null);
    setPayload(null);
    setError(null);
    setNotice("");
    setPendingDecision(null);
    setConfirmationAvailable(false);
    focusNoticeOnUpdateRef.current = false;
    decisionOriginRef.current = null;
    restoreDecisionFocusRef.current = false;
    setBusy(false);
    setLoading(capabilities);
    setStateBinding(binding);
    setStateTransport(transport);
    if (!capabilities) return;

    const controller = new AbortController();
    operationRef.current = controller;
    const presence = transport.getUserPresenceCapability === undefined
      ? Promise.resolve(null)
      : transport.getUserPresenceCapability(controller.signal).catch(() => null);
    Promise.all([
      transport.listMetricLifecycleProposals!(sessionId, controller.signal),
      presence,
    ]).then(([page, userPresence]) => {
      if (
        controller.signal.aborted
        || bindingRef.current !== binding
        || transportRef.current !== transport
      ) return;
      if (page.session_id !== sessionId || page.complete !== true || !Array.isArray(page.proposals)
        || !Number.isSafeInteger(page.total) || page.total !== page.proposals.length
        || page.proposals.some((proposal) => proposal.session_id !== sessionId)
        || new Set(page.proposals.map((proposal) => proposal.proposal_id)).size !== page.proposals.length) {
        setLoading(false);
        setError({ kind: "load", message: "The exact-run proposal list is incomplete or could not be verified. Refresh before reviewing evidence." });
        return;
      }
      setProposals(page.proposals.filter((proposal) => (
        isExactProposal(proposal, sessionId, sourceRunId)
      )));
      setConfirmationAvailable(userPresence?.contract_version === "native-user-presence-capability-v1"
        && userPresence.confirmation_available === true && userPresence.mode === "native_bridge_bound_token");
      setLoading(false);
    }).catch(() => {
      if (
        controller.signal.aborted
        || bindingRef.current !== binding
        || transportRef.current !== transport
      ) return;
      setLoading(false);
      setError({
        kind: "load",
        message: "Exact-run evidence proposals are temporarily unavailable. No file or decision was applied.",
      });
    });
    return () => controller.abort();
  }, [capabilities, reloadToken, sessionId, sourceRunId, transport]);

  useEffect(() => {
    if (pendingDecision !== null) {
      decisionActionRef.current?.focus();
    } else if (restoreDecisionFocusRef.current) {
      decisionTriggerRef.current?.focus();
      restoreDecisionFocusRef.current = false;
    }
  }, [pendingDecision]);

  useEffect(() => {
    if (preview === null || busy) return;
    const ownerBinding = stateBinding;
    const ownerTransport = stateTransport;
    const expiresIn = Date.parse(preview.expires_at) - Date.now();
    const expire = () => {
      if (bindingRef.current !== ownerBinding || transportRef.current !== ownerTransport) return;
      setPreview(null);
      setPayload(null);
      setNotice("");
      setError({
        kind: "stale",
        message: "The strict preview expired. Select the canonical file again before importing.",
      });
    };
    if (!Number.isFinite(expiresIn) || expiresIn <= 0) {
      expire();
      return;
    }
    const timer = window.setTimeout(expire, Math.min(expiresIn, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [busy, preview, stateBinding, stateTransport]);

  useEffect(() => {
    if (preview !== null) previewRef.current?.focus();
  }, [preview]);

  useEffect(() => {
    if (notice !== "" && focusNoticeOnUpdateRef.current) {
      noticeRef.current?.focus();
      focusNoticeOnUpdateRef.current = false;
    }
  }, [notice]);

  const contextIsCurrent = stateBinding === currentBinding && stateTransport === transport;
  const visibleProposals = contextIsCurrent ? proposals : NO_PROPOSALS;
  const visiblePreview = contextIsCurrent
    && preview?.session_id === sessionId
    && preview.expected_source_run_id === sourceRunId
    ? preview
    : null;
  const visibleLoading = capabilities && (!contextIsCurrent || loading);
  const visibleBusy = contextIsCurrent && busy;
  const visibleError = contextIsCurrent ? error : null;
  const visibleNotice = contextIsCurrent ? notice : "";
  const visiblePendingDecision = contextIsCurrent ? pendingDecision : null;
  const visibleConfirmationAvailable = contextIsCurrent && confirmationAvailable;

  const undecided = useMemo(
    () => visibleProposals.filter((proposal) => proposal.status === "proposed"),
    [visibleProposals],
  );
  const confirmedCount = useMemo(
    () => visibleProposals.filter((proposal) => proposal.status === "confirmed").length,
    [visibleProposals],
  );
  const rejectedCount = useMemo(
    () => visibleProposals.filter((proposal) => proposal.status === "rejected").length,
    [visibleProposals],
  );

  function admitsCurrentContext(): boolean {
    return stateBinding === currentBinding
      && stateTransport === transport
      && bindingRef.current === currentBinding
      && transportRef.current === transport;
  }

  function beginOperation(): { controller: AbortController; binding: string } {
    operationRef.current?.abort();
    const controller = new AbortController();
    operationRef.current = controller;
    return { controller, binding: bindingKey(sessionId, sourceRunId) };
  }

  function stillCurrent(controller: AbortController, binding: string): boolean {
    return !controller.signal.aborted
      && bindingRef.current === binding
      && transportRef.current === transport;
  }

  function focusNotice(): void {
    focusNoticeOnUpdateRef.current = true;
  }

  function clearSelection(): void {
    setPreview(null);
    setPayload(null);
    setPendingDecision(null);
  }

  function openDecision(proposalId: string, decision: "confirm" | "reject"): void {
    if (
      !admitsCurrentContext()
      || !proposals.some((proposal) => (
        proposal.proposal_id === proposalId
        && proposal.status === "proposed"
        && isExactProposal(proposal, sessionId, sourceRunId)
      ))
    ) return;
    const origin = { proposalId, decision };
    decisionOriginRef.current = origin;
    setError(null);
    setNotice("");
    setPendingDecision(origin);
  }

  function cancelDecision(): void {
    if (!admitsCurrentContext()) return;
    restoreDecisionFocusRef.current = true;
    setPendingDecision(null);
  }

  function reloadCurrentContext(): void {
    if (!admitsCurrentContext()) return;
    setReloadToken((value) => value + 1);
  }

  async function chooseFile(file: File | undefined) {
    if (file === undefined || !capabilities || loading || !admitsCurrentContext()) return;
    operationRef.current?.abort();
    clearSelection();
    setError(null);
    setNotice("");
    setBusy(false);
    if (file.size < 1 || file.size > MAX_FILE_BYTES) {
      setError({
        kind: "validation",
        message: "Choose one non-empty canonical agent-evidence file no larger than 64 KiB.",
      });
      return;
    }
    if (!isAcceptedFile(file)) {
      setError({
        kind: "validation",
        message: "Choose a .json file using JSON or the canonical agent-evidence media type.",
      });
      return;
    }

    const { controller, binding } = beginOperation();
    setBusy(true);
    setNotice("Validating the selected file locally…");
    try {
      const bytes = await file.arrayBuffer();
      if (!stillCurrent(controller, binding)) return;
      const result = await transport.previewAgentMetricEvidence!(sessionId, bytes, controller.signal);
      if (!stillCurrent(controller, binding)) return;
      if (
        result.session_id !== sessionId
        || result.expected_source_run_id !== sourceRunId
        || !Number.isFinite(Date.parse(result.expires_at))
        || Date.parse(result.expires_at) <= Date.now()
      ) {
        setNotice("");
        setError({
          kind: "stale",
          message: "The file preview is stale or bound to another exact sealed source run.",
        });
        return;
      }
      setPayload(bytes);
      setPreview(result);
      setNotice("Strict preview ready. Importing will create an unconfirmed proposal only.");
    } catch {
      if (stillCurrent(controller, binding)) {
        setNotice("");
        setError({
          kind: "validation",
          message: "The file failed strict local schema validation; no proposal was imported.",
        });
      }
    } finally {
      if (stillCurrent(controller, binding)) setBusy(false);
    }
  }

  async function importPreview() {
    if (
      !admitsCurrentContext()
      || preview === null || payload === null
      || preview.session_id !== sessionId
      || preview.expected_source_run_id !== sourceRunId
      || transport.importAgentMetricEvidence === undefined
      || Date.parse(preview.expires_at) <= Date.now()
    ) {
      if (preview !== null && Date.parse(preview.expires_at) <= Date.now()) {
        clearSelection();
        setError({
          kind: "stale",
          message: "The strict preview expired. Select the canonical file again before importing.",
        });
      }
      return;
    }
    const { controller, binding } = beginOperation();
    const expectedDigest = preview.payload_sha256;
    setBusy(true);
    setError(null);
    setNotice("Importing the exact preview as an unconfirmed proposal…");
    try {
      const result = await transport.importAgentMetricEvidence(
        sessionId,
        payload,
        expectedDigest,
        IMPORT_CONFIRMATION,
        idempotency("agent-evidence-import"),
        controller.signal,
      );
      if (!stillCurrent(controller, binding)) return;
      if (
        result.payload_sha256 !== expectedDigest
        || !isExactProposal(result.proposal, sessionId, sourceRunId)
        || result.proposal.status !== "proposed"
      ) {
        clearSelection();
        setNotice("");
        setError({
          kind: "stale",
          message: "The imported proposal did not preserve the exact preview and sealed-run binding.",
        });
        return;
      }
      setProposals((current) => [
        result.proposal,
        ...current.filter((item) => item.proposal_id !== result.proposal.proposal_id),
      ]);
      setPreview(null);
      setPayload(null);
      setNotice("Unconfirmed proposal imported. Review it separately before making a native decision.");
      focusNotice();
    } catch {
      if (stillCurrent(controller, binding)) {
        setNotice("");
        setError({
          kind: "action",
          message: "The preview binding changed or the unconfirmed proposal could not be imported.",
        });
      }
    } finally {
      if (stillCurrent(controller, binding)) setBusy(false);
    }
  }

  async function applyDecision(proposal: MetricLifecycleProposal, decision: "confirm" | "reject") {
    if (
      !admitsCurrentContext()
      || transport.decideMetricLifecycleProposal === undefined
      || !confirmationAvailable
      || !isExactProposal(proposal, sessionId, sourceRunId)
      || proposal.status !== "proposed"
    ) return;
    const { controller, binding } = beginOperation();
    setBusy(true);
    setError(null);
    setNotice(decision === "confirm" ? "Applying native confirmation…" : "Applying native rejection…");
    try {
      const result = await transport.decideMetricLifecycleProposal(
        sessionId,
        proposal.proposal_id,
        {
          expected_source_run_id: proposal.source_run_id,
          expected_proposal_revision: proposal.proposal_revision,
          decision,
          confirmation: DECISION_CONFIRMATION,
        },
        idempotency(`agent-evidence-${decision}`),
        controller.signal,
      );
      if (!stillCurrent(controller, binding)) return;
      const expectedStatus = decision === "confirm" ? "confirmed" : "rejected";
      if (
        result.proposal.proposal_id !== proposal.proposal_id
        || !isExactProposal(result.proposal, sessionId, sourceRunId)
        || result.proposal.status !== expectedStatus
        || result.proposal.decision !== decision
      ) {
        setPendingDecision(null);
        setNotice("");
        setError({
          kind: "stale",
          message: "The decision response did not preserve the exact proposal and sealed-run binding.",
        });
        return;
      }
      setProposals((current) => current.map((item) => (
        item.proposal_id === result.proposal.proposal_id ? result.proposal : item
      )));
      setPendingDecision(null);
      setNotice(decision === "confirm"
        ? "Evidence confirmed for this sealed run. Re-run local metric analysis to publish a new snapshot."
        : "Proposal revision rejected. No evidence was admitted.");
      if (decision === "confirm") onEvidenceChanged?.();
      focusNotice();
    } catch {
      if (stillCurrent(controller, binding)) {
        setPendingDecision(null);
        setNotice("");
        setError({
          kind: "action",
          message: "The source run, proposal revision, or native decision authority changed. Refresh before deciding.",
        });
      }
    } finally {
      if (stillCurrent(controller, binding)) setBusy(false);
    }
  }

  const panelState = !capabilities
    ? "unavailable"
    : visibleLoading
      ? "loading"
      : visibleError?.kind === "stale"
        ? "stale"
        : visibleError !== null
          ? "error"
          : visiblePreview !== null
            ? "preview"
            : undecided.length > 0
              ? "ready"
              : visibleNotice.startsWith("Evidence confirmed") || confirmedCount > 0
                ? "confirmed"
                : "empty";

  if (compact) {
    return (
      <section
        aria-labelledby={headingId}
        className="metric-evidence-file metric-evidence-file--compact metric-evidence-file--generic"
        data-state={panelState}
      >
        <h3 id={headingId}>Confirmed metric evidence</h3>
        <span>{!capabilities
          ? "Local evidence import unavailable"
          : visibleLoading
            ? "Loading exact-run evidence review…"
            : visibleError?.kind === "load"
              ? "Exact-run evidence review unavailable"
              : `${undecided.length} proposal${undecided.length === 1 ? "" : "s"} awaiting review`}</span>
        <small>{visibleConfirmationAvailable
          ? "Open the full dashboard to review and natively confirm typed agent files; this compact view never auto-approves evidence."
          : "Review is fail-closed: this server/window composition cannot natively confirm evidence decisions."}</small>
        {confirmedCount > 0 && <small>{confirmedCount} confirmed decision{confirmedCount === 1 ? "" : "s"} recorded for this sealed run.</small>}
        {visibleError !== null && <span className="metric-evidence-file__error" role="alert">{visibleError.message}</span>}
      </section>
    );
  }

  return (
    <section
      aria-labelledby={headingId}
      className="metric-evidence-file metric-evidence-file--generic"
      data-state={panelState}
    >
      <header>
        <div>
          <h3 id={headingId}>Import agent metric evidence</h3>
          <span>Local canonical file → strict preview → unconfirmed proposal → your native decision</span>
        </div>
        <small id={fileHelpId}>One non-empty .json file, at most 64 KiB. Files cannot contain scores, prose, transcripts, paths, or objective-proof claims.</small>
      </header>

      {!capabilities ? (
        <p className="metric-evidence-file__state" role="status">This local runtime does not expose the reviewed evidence-file boundary. No import or decision controls are available.</p>
      ) : visibleLoading ? (
        <p aria-live="polite" className="metric-evidence-file__state" role="status">Loading proposals bound to this exact sealed run and checking native decision capability…</p>
      ) : visibleError?.kind === "load" ? (
        <div className="metric-evidence-file__state metric-evidence-file__state--error">
          <p role="alert">{visibleError.message}</p>
          <button onClick={reloadCurrentContext} type="button">Retry exact-run review</button>
        </div>
      ) : (
        <>
          <label className="metric-evidence-file__picker">
            <span>Choose canonical evidence file</span>
            <input
              accept={`.json,application/json,${EVIDENCE_MEDIA_TYPE}`}
              aria-describedby={fileHelpId}
              disabled={visibleBusy}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                void chooseFile(file);
              }}
              type="file"
            />
          </label>

          {visiblePreview !== null && (
            <div
              aria-labelledby={`${headingId}-preview`}
              className="metric-evidence-file__preview"
              ref={previewRef}
              role="region"
              tabIndex={-1}
            >
              <div>
                <h4 id={`${headingId}-preview`}>Strict local preview</h4>
                <span><strong>{visiblePreview.metric_key.replace("collaboration.", "").replaceAll("_", " ")}</strong> · {visiblePreview.proposal_kind}</span>
                <small className="metric-evidence-file__safe-metadata">Producer claim: {visiblePreview.producer.producer_id} / {visiblePreview.producer.model_id} · untrusted provenance, not evidence authority</small>
                <small>Exact sealed source run matched · raw file and producer claim will not become evidence authority</small>
              </div>
              <button disabled={visibleBusy} onClick={() => void importPreview()} type="button">Import as unconfirmed</button>
            </div>
          )}

          <section aria-labelledby={proposalsHeadingId} className="metric-evidence-file__proposals">
            <div className="metric-evidence-file__section-heading">
              <h4 id={proposalsHeadingId}>Proposals awaiting local decision</h4>
              <span>{undecided.length} current</span>
            </div>
            {undecided.length === 0 ? (
              <p className="metric-evidence-file__state" role="status">No unconfirmed proposals are bound to this exact sealed run.</p>
            ) : (
              <ul aria-label="Evidence proposals awaiting local decision">
                {undecided.map((proposal) => (
                  <li key={proposal.proposal_id}>
                    <span>
                      <strong>{proposalLabel(proposal)}</strong>
                      <small>Bound to current sealed run · revision {proposal.proposal_revision}</small>
                    </span>
                    {visiblePendingDecision?.proposalId === proposal.proposal_id ? (
                      <div
                        aria-label={`${visiblePendingDecision.decision === "confirm" ? "Confirm" : "Reject"} ${proposalLabel(proposal)}`}
                        className="metric-evidence-file__decision-confirmation"
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            cancelDecision();
                          }
                        }}
                        role="group"
                      >
                        <p>
                          {visiblePendingDecision.decision === "confirm"
                            ? "A native user-presence decision admits this typed lifecycle receipt into the next sealed metric denominator."
                            : "A native user-presence decision permanently rejects this proposal revision."}
                        </p>
                        <div>
                          <button disabled={visibleBusy} onClick={cancelDecision} type="button">Cancel</button>
                          <button
                            disabled={visibleBusy || !visibleConfirmationAvailable}
                            onClick={() => void applyDecision(proposal, visiblePendingDecision.decision)}
                            ref={decisionActionRef}
                            type="button"
                          >
                            {visiblePendingDecision.decision === "confirm" ? "Apply confirmation" : "Apply rejection"}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="metric-evidence-file__proposal-actions">
                        <button
                          disabled={visibleBusy || !visibleConfirmationAvailable || visibleError?.kind === "stale"}
                          onClick={() => openDecision(proposal.proposal_id, "reject")}
                          ref={decisionOriginRef.current?.proposalId === proposal.proposal_id
                            && decisionOriginRef.current.decision === "reject" ? decisionTriggerRef : undefined}
                          type="button"
                        >Reject</button>
                        <button
                          disabled={visibleBusy || !visibleConfirmationAvailable || visibleError?.kind === "stale"}
                          onClick={() => openDecision(proposal.proposal_id, "confirm")}
                          ref={decisionOriginRef.current?.proposalId === proposal.proposal_id
                            && decisionOriginRef.current.decision === "confirm" ? decisionTriggerRef : undefined}
                          type="button"
                        >Confirm evidence</button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {!visibleConfirmationAvailable && (
            <p className="metric-evidence-file__state" role="status">Native user-presence confirmation is unavailable in this server/window composition. Preview and import remain local; proposals remain unconfirmed.</p>
          )}
          {(confirmedCount > 0 || rejectedCount > 0) && (
            <p className="metric-evidence-file__decision-summary">
              Current sealed run: {confirmedCount} confirmed · {rejectedCount} rejected decision{confirmedCount + rejectedCount === 1 ? "" : "s"} recorded.
            </p>
          )}
          {visibleNotice !== "" && (
            <p aria-live="polite" className="metric-evidence-file__notice" ref={noticeRef} role="status" tabIndex={-1}>{visibleNotice}</p>
          )}
          {visibleError !== null && (
            <div className="metric-evidence-file__state metric-evidence-file__state--error">
              <p className="metric-evidence-file__error" role="alert">{visibleError.message}</p>
              {visibleError.kind === "stale" && (
                <button onClick={reloadCurrentContext} type="button">Refresh exact-run review</button>
              )}
            </div>
          )}
          <p className="metric-evidence-file__footnote">Confirmation records typed evidence only. Re-run local metric analysis to publish an updated sealed snapshot.</p>
        </>
      )}
    </section>
  );
}
