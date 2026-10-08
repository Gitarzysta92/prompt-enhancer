import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ModelLinkAnnotation,
  ModelLinkAnnotationRequest,
  ModelLinkExperiment,
  ModelLinkExperimentOutcome,
  PromptEnhancerTransport,
  ProviderCompatibilityStatus,
  SessionTextAnalysisCapability,
} from "../../shared/api/contracts";
import { nextIdempotencyKey } from "../../shared/api/idempotency";
import { shortId } from "../../shared/lib/format";
import { promptTextCompatibilityBlocker } from "../provider-compatibility";
import {
  parseModelLinkAnnotation,
  parseModelLinkExperiment,
  parseModelLinkOutcome,
} from "./modelLinkContract";

type ReviewLabel = ModelLinkAnnotationRequest["label"];

const TERMINAL_SOURCE_LIMIT_REASONS = new Set([
  "source_selection_limit",
  "source_provider_response_limit",
  "source_thread_structure_limit",
  "source_preview_window_limit",
  "source_resource_limit",
]);

function statusOf(error: unknown): number | null {
  return typeof error === "object" &&
    error !== null &&
    "status" in error &&
    typeof error.status === "number"
    ? error.status
    : null;
}

function reasonOf(error: unknown): string | null {
  return typeof error === "object" &&
    error !== null &&
    "reasonCode" in error &&
    typeof error.reasonCode === "string"
    ? error.reasonCode
    : null;
}

function safeRunError(error: unknown): string {
  const reason = reasonOf(error);
  if (reason === "local_model_execution_failed") {
    return "The pinned Qwen or BGE model is not available in the verified local cache. Open Model Lab, run the cached model screen, then retry.";
  }
  if (reason === "no_model_link_candidates") {
    return "This bounded window has no user-request and later agent-response pair to compare.";
  }
  if (reason === "redacted_content_consent_required") {
    return "Redacted-text access is not active. Grant it in Data sources before running the experiment.";
  }
  if (reason === "session_not_in_safe_index") {
    return "This session is no longer in the safe index. Refresh Data sources and reopen it.";
  }
  if (reason === "provider_compatibility_blocked") {
    return "Installed-schema compatibility changed. Recheck compatibility before retrying.";
  }
  if (reason === "source_selection_limit") {
    return "The current Codex session catalog exceeds the local selection-scan limit. No experiment result was stored.";
  }
  if (reason === "source_provider_response_limit") {
    return "A local Codex response exceeded the transport limit before the experiment window could be selected. No result was stored.";
  }
  if (reason === "source_thread_structure_limit") {
    return "The selected session's full local thread structure exceeds this adapter version's parser limits. No result was stored.";
  }
  if (reason === "source_preview_window_limit") {
    return "The selected focus message cannot fit in the fixed local experiment window. No partial result was stored.";
  }
  if (reason === "source_resource_limit") {
    return "The local source reached an unclassified safety limit before the experiment window could be prepared. No result was stored.";
  }
  if (reason === "source_timeout" || reason === "provider_unavailable") {
    return "The local Codex read was unavailable or timed out. Keep Codex open and retry once.";
  }
  if (reason === "provider_protocol_rejected" || reason === "source_schema_unsupported") {
    return "The selected session could not be safely decoded by this adapter version. Update or restart Prompt Enhancer before retrying.";
  }
  if (reason === "model_link_persistence_failed") {
    return "The content-free experiment result could not be stored in the local database.";
  }
  if (statusOf(error) === 501) {
    return "New model experiments are disabled in the fictional preview.";
  }
  return "The local model experiment did not complete. No session text is included in this error.";
}

function capabilityBlocker(
  capability: SessionTextAnalysisCapability | null,
  compatibility: ProviderCompatibilityStatus | null,
  compatibilityLoading: boolean,
): string | null {
  if (capability === null) return "Checking local redacted-text access.";
  if (!capability.available) {
    if (capability.reason_code === "redacted_content_consent_required") {
      return "Grant redacted-text access in Data sources first.";
    }
    return "This local installation cannot run selected-session text experiments.";
  }
  if (compatibilityLoading) return "Checking installed-schema compatibility.";
  return promptTextCompatibilityBlocker(compatibility) === null
    ? null
    : "The experiment is paused until installed-schema compatibility is ready.";
}

function recommendationLabel(value: "qwen" | "bge" | "both"): string {
  if (value === "both") return "Both models";
  return value === "qwen" ? "Qwen" : "BGE";
}

function latestAnnotations(
  experiment: ModelLinkExperiment | null,
): Map<string, ModelLinkAnnotation> {
  return new Map(
    (experiment?.annotations ?? []).map((annotation) => [
      annotation.link_id,
      annotation,
    ]),
  );
}

function reviewPrecision(
  experiment: ModelLinkExperiment,
  model: "qwen" | "bge",
): { relevant: number; decided: number } {
  const annotations = latestAnnotations(experiment);
  let relevant = 0;
  let decided = 0;
  for (const link of experiment.links) {
    if (link.recommended_by !== model && link.recommended_by !== "both") continue;
    const label = annotations.get(link.link_id)?.label;
    if (label === "relevant") {
      relevant += 1;
      decided += 1;
    } else if (label === "incorrect") {
      decided += 1;
    }
  }
  return { relevant, decided };
}

export function ModelLinkExperimentPanel({
  sessionId,
  transport,
  analysisCapability,
  providerCompatibility,
  compatibilityLoading = false,
}: {
  sessionId: string;
  transport: PromptEnhancerTransport;
  analysisCapability: SessionTextAnalysisCapability | null;
  providerCompatibility: ProviderCompatibilityStatus | null;
  compatibilityLoading?: boolean;
}) {
  const [experiment, setExperiment] = useState<ModelLinkExperiment | null>(null);
  const [outcome, setOutcome] = useState<ModelLinkExperimentOutcome | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [runError, setRunError] = useState("");
  const [terminalRunFailure, setTerminalRunFailure] = useState(false);
  const [annotationError, setAnnotationError] = useState("");
  const [pendingLinkId, setPendingLinkId] = useState<string | null>(null);
  const [cancelledWait, setCancelledWait] = useState(false);
  const requestController = useRef<AbortController | null>(null);
  const loadController = useRef<AbortController | null>(null);
  const annotationController = useRef<AbortController | null>(null);
  const metadataKnown = useRef(false);

  async function readStoredMetadata(controller = new AbortController()) {
    loadController.current?.abort();
    loadController.current = controller;
    setLoading(true);
    setLoadError("");
    try {
      const value = await transport.getLatestModelLinkExperiment(sessionId, controller.signal);
      if (controller.signal.aborted || loadController.current !== controller) return;
      setExperiment(parseModelLinkExperiment(value));
      metadataKnown.current = true;
    } catch (error) {
      if (controller.signal.aborted || loadController.current !== controller) return;
      if (statusOf(error) === 404) {
        setExperiment(null);
        metadataKnown.current = true;
      } else setLoadError("The stored model experiment summary could not be validated or loaded.");
    } finally {
      if (!controller.signal.aborted && loadController.current === controller) {
        setLoading(false);
        loadController.current = null;
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    metadataKnown.current = false;
    requestController.current?.abort();
    requestController.current = null;
    annotationController.current?.abort();
    annotationController.current = null;
    setLoading(true);
    setRunning(false);
    setCancelledWait(false);
    setPendingLinkId(null);
    setAnnotationError("");
    setLoadError("");
    setRunError("");
    setTerminalRunFailure(false);
    setExperiment(null);
    setOutcome(null);
    void readStoredMetadata(controller);
    return () => {
      controller.abort();
      loadController.current?.abort();
      loadController.current = null;
      requestController.current?.abort();
      requestController.current = null;
      annotationController.current?.abort();
      annotationController.current = null;
    };
  }, [sessionId, transport]);

  const blocker = capabilityBlocker(
    analysisCapability,
    providerCompatibility,
    compatibilityLoading,
  );
  const annotations = useMemo(() => latestAnnotations(experiment), [experiment]);
  const qwenReview = experiment ? reviewPrecision(experiment, "qwen") : null;
  const bgeReview = experiment ? reviewPrecision(experiment, "bge") : null;
  const suggestions = outcome?.suggestions ?? [];

  async function runExperiment() {
    if (requestController.current || annotationController.current || blocker !== null || terminalRunFailure) return;
    loadController.current?.abort();
    loadController.current = null;
    setLoading(false);
    const controller = new AbortController();
    requestController.current = controller;
    const owns = () => requestController.current === controller && !controller.signal.aborted;
    setRunning(true);
    setCancelledWait(false);
    setRunError("");
    setTerminalRunFailure(false);
    setAnnotationError("");
    setOutcome(null);
    try {
      const value = await transport.startModelLinkExperiment(
        sessionId,
        {
          confirmation: "compare_selected_redacted_text_with_local_models",
          device: "auto",
        },
        nextIdempotencyKey("model-link-experiment"),
        controller.signal,
      );
      if (!owns()) return;
      const parsed = parseModelLinkOutcome(value);
      setOutcome(parsed);
      setExperiment(parsed.experiment);
      metadataKnown.current = true;
      setLoadError("");
    } catch (error) {
      if (owns()) {
        const reason = reasonOf(error);
        setRunError(safeRunError(error));
        setTerminalRunFailure(
          reason !== null && TERMINAL_SOURCE_LIMIT_REASONS.has(reason),
        );
        if (!metadataKnown.current) void readStoredMetadata();
      }
    } finally {
      if (owns()) {
        setRunning(false);
        requestController.current = null;
      }
    }
  }

  function cancelRun() {
    requestController.current?.abort();
    requestController.current = null;
    setRunning(false);
    setCancelledWait(true);
    if (!metadataKnown.current) void readStoredMetadata();
  }

  async function annotate(linkId: string, label: ReviewLabel) {
    if (!experiment || annotationController.current || requestController.current) return;
    const runId = experiment.run.run_id;
    const controller = new AbortController();
    annotationController.current = controller;
    const owns = () => annotationController.current === controller && !controller.signal.aborted;
    const expectedRevision = annotations.get(linkId)?.revision ?? 0;
    setPendingLinkId(linkId);
    setAnnotationError("");
    try {
      const value = await transport.annotateModelLink(
        runId,
        linkId,
        { label, expected_revision: expectedRevision },
        controller.signal,
      );
      if (!owns()) return;
      const annotation = parseModelLinkAnnotation(value);
      if (annotation.link_id !== linkId) throw new Error("model-link-annotation-owner-mismatch");
      setExperiment((current) =>
        current === null || current.run.run_id !== runId
          ? current
          : {
              ...current,
              annotations: [
                ...current.annotations.filter(
                  (item) => item.link_id !== annotation.link_id,
                ),
                annotation,
              ],
            },
      );
    } catch {
      if (owns()) setAnnotationError(
        "That review label could not be stored. Refresh this session before retrying.",
      );
    } finally {
      if (owns()) {
        annotationController.current = null;
        setPendingLinkId(null);
      }
    }
  }

  return (
    <section
      aria-labelledby="model-link-experiment-title"
      className="model-link-experiment"
    >
      <header className="model-link-experiment__header">
        <div>
          <p className="eyebrow">Optional local experiment</p>
          <h2 id="model-link-experiment-title">Do the models link requests to the right agent work?</h2>
          <p>
            Qwen3 Embedding and BGE Reranker independently suggest which later
            response or plan belongs to each user request. This evaluates the
            retrieval method, not your intelligence, prompt quality, or task success.
          </p>
        </div>
        <div className="model-link-experiment__actions">
          {running ? (
            <button className="button button--secondary" onClick={cancelRun} type="button">
              Cancel wait
            </button>
          ) : (
            <button
              className="button button--primary"
              disabled={blocker !== null || terminalRunFailure || pendingLinkId !== null}
              onClick={() => void runExperiment()}
              title={
                blocker ??
                  (terminalRunFailure
                    ? "This session cannot be prepared within the current local source limits."
                    : undefined)
              }
              type="button"
            >
              Run Qwen + BGE locally
            </button>
          )}
        </div>
      </header>

      <div className="model-link-experiment__privacy" role="note">
        <strong>One explicit local read</strong>
        <span>
          Codex first returns the selected session to a size-limited local adapter;
          oversized responses fail closed before the experiment window is selected.
          Up to 100 redacted messages, 8 requests, and 8 later candidates per request
          enter offline cached models. Review excerpts exist only in this response and
          browser view; they are not
          persisted. Redaction reduces exposure but is not anonymization.
        </span>
      </div>

      <details className="model-link-experiment__workflow">
        <summary>How this experiment works</summary>
        <ol aria-label="How the model experiment works" className="model-link-experiment__steps">
          <li>
            <span>1</span>
            <div><strong>Run locally</strong><small>Load the two pinned models and the bounded redacted window.</small></div>
          </li>
          <li>
            <span>2</span>
            <div><strong>Compare links</strong><small>See which later response or plan each model connects to a request.</small></div>
          </li>
          <li>
            <span>3</span>
            <div><strong>Review suggestions</strong><small>Mark every proposed link Relevant, Incorrect, or Unsure.</small></div>
          </li>
          <li>
            <span>4</span>
            <div><strong>Judge the method</strong><small>Use reviewed precision to decide whether either model is useful enough for future metrics.</small></div>
          </li>
        </ol>
      </details>

      <p aria-live="polite" className="model-link-experiment__status" role="status">
        {running
          ? "Loading the two pinned models one at a time and comparing the selected session locally."
          : cancelledWait ? "Stopped waiting in this view. The local worker may still be running; no worker cancellation was confirmed."
          : loading ? "Checking stored experiment metadata."
          : loadError ? "Stored experiment availability is unknown. Retry the metadata read."
          : blocker ??
            (experiment
              ? "Stored content-free experiment metadata is available below."
              : "No model-link experiment has been stored for this session yet.")}
      </p>
      {loadError && <div className="model-link-experiment__error" role="alert">{loadError}{" "}<button disabled={loading || running || pendingLinkId !== null} onClick={() => void readStoredMetadata()} type="button">Retry stored metadata</button></div>}
      {runError && <p className="model-link-experiment__error" role="alert">{runError}</p>}

      {loading ? (
        <p className="model-link-experiment__empty">Loading stored experiment metadata...</p>
      ) : experiment ? (
        <>
          <dl className="model-link-experiment__facts">
            <div><dt>Requests compared</dt><dd>{experiment.run.query_count}</dd></div>
            <div><dt>Suggestions</dt><dd>{experiment.run.link_count}</dd></div>
            <div>
              <dt>Same top candidate</dt>
              <dd>{experiment.run.agreement_count} / {experiment.run.query_count}</dd>
            </div>
            <div><dt>Device</dt><dd>{experiment.run.resolved_device.toUpperCase()}</dd></div>
          </dl>

          <div className="model-link-experiment__review-summary">
            <strong>Human review of model suggestions</strong>
            <span>
              Qwen: {qwenReview?.decided ? `${qwenReview.relevant}/${qwenReview.decided} relevant` : "not reviewed"}
              {" | "}
              BGE: {bgeReview?.decided ? `${bgeReview.relevant}/${bgeReview.decided} relevant` : "not reviewed"}
              {" | Unsure is excluded"}
            </span>
          </div>

          {suggestions.length === 0 ? (
            <p className="model-link-experiment__empty">
              Only content-free scores and labels survive reload. Run the experiment
              again when you want a fresh transient excerpt review.
            </p>
          ) : (
            <ol className="model-link-experiment__suggestions">
              {suggestions.map((suggestion) => {
                const link = experiment.links.find(
                  (item) => item.link_id === suggestion.link_id,
                )!;
                const annotation = annotations.get(link.link_id);
                const busy = pendingLinkId === link.link_id;
                return (
                  <li key={link.link_id}>
                    <header>
                      <span className="status-pill status-pill--info">
                        {recommendationLabel(link.recommended_by)} suggestion
                      </span>
                      <small>
                        {link.candidate_kind === "plan" ? "Agent plan" : "Agent response"}
                        {" | Link "}{shortId(link.link_id)}
                      </small>
                    </header>
                    <div className="model-link-experiment__pair">
                      <blockquote>
                        <strong>User request</strong>
                        <p>{suggestion.query_excerpt}</p>
                      </blockquote>
                      <blockquote>
                        <strong>{link.candidate_kind === "plan" ? "Later plan" : "Later response"}</strong>
                        <p>{suggestion.candidate_excerpt}</p>
                      </blockquote>
                    </div>
                    <div className="model-link-experiment__ranks">
                      <span>Qwen rank {link.qwen_rank} (similarity {link.qwen_score.toFixed(3)})</span>
                      <span>BGE rank {link.bge_rank} (score {link.bge_score.toFixed(3)})</span>
                      <small>Ranks are comparable within one request; raw scales are not.</small>
                    </div>
                    <fieldset disabled={busy || pendingLinkId !== null}>
                      <legend>Is this request-work link correct?</legend>
                      {(["relevant", "incorrect", "unsure"] as const).map((label) => (
                        <button
                          aria-pressed={annotation?.label === label}
                          className="button button--secondary button--compact"
                          key={label}
                          onClick={() => void annotate(link.link_id, label)}
                          type="button"
                        >
                          {label === "relevant" ? "Relevant" : label === "incorrect" ? "Incorrect" : "Unsure"}
                        </button>
                      ))}
                    </fieldset>
                  </li>
                );
              })}
            </ol>
          )}
          {annotationError && (
            <p className="model-link-experiment__error" role="alert">{annotationError}</p>
          )}
          <details className="model-link-experiment__provenance">
            <summary>Model and run provenance</summary>
            <dl>
              <div><dt>Experiment</dt><dd>{experiment.run.experiment_key} v{experiment.run.experiment_version}</dd></div>
              <div><dt>Qwen</dt><dd>{experiment.run.qwen_model.repository_id} @ {experiment.run.qwen_model.revision.slice(0, 8)}</dd></div>
              <div><dt>BGE</dt><dd>{experiment.run.bge_model.repository_id} @ {experiment.run.bge_model.revision.slice(0, 8)}</dd></div>
              <div><dt>Run</dt><dd className="mono">{shortId(experiment.run.run_id)}</dd></div>
            </dl>
          </details>
        </>
      ) : (
        <p className="model-link-experiment__empty">
          This panel has no score. Run it only when you want to test and label the two
          local model candidates.
        </p>
      )}
    </section>
  );
}
