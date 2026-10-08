import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  SessionQualityAnalysisPreview,
  SessionQualityAnalysisPreviewApprovalRequest,
  SessionQualityAnalysisPreviewRequest,
} from "../../shared/api/contracts";
import { nextIdempotencyKey } from "../../shared/api/idempotency";
import {
  COACHING_ANALYSIS_PRESET,
  COACHING_ANALYSIS_PREVIEW_REQUEST,
} from "./standardEngineeringAnalysisPreset";
import { QUALITY_ANALYSIS_DEFINITIONS } from "./qualityProfile";
import "./QualityProfileView.css";

type PendingAction = "preview" | "approval" | "compatibility" | null;

const TERMINAL_SOURCE_LIMIT_REASONS = new Set([
  "source_selection_limit",
  "source_provider_response_limit",
  "source_thread_structure_limit",
  "source_preview_window_limit",
  "source_resource_limit",
]);
const EXPECTED_METRIC_KEYS = new Set(
  QUALITY_ANALYSIS_DEFINITIONS.map((definition) => definition.key),
);
const HEX_64 = /^[a-f0-9]{64}$/iu;
const MAX_PREVIEW_LIFETIME_MS = 600_000;

function isBoundedVersion(value: string): boolean {
  return value.length > 0 && value.length <= 160;
}

function hasExactLocalPreviewContract(
  preview: SessionQualityAnalysisPreview,
  exactSessionId: string,
): boolean {
  const createdAt = Date.parse(preview.created_at);
  const expiresAt = Date.parse(preview.expires_at);
  const metricKeys = preview.binding.metric_keys;
  const characterCount = preview.messages.reduce(
    (total, message) => total + Array.from(message.text).length,
    0,
  );
  return (
    HEX_64.test(preview.preview_id) &&
    HEX_64.test(preview.binding.analysis_window_fingerprint) &&
    preview.binding.session_id === exactSessionId &&
    preview.binding.destination === "local" &&
    preview.binding.exact_model === "none" &&
    preview.binding.retention_class === "local_ephemeral" &&
    preview.binding.cost_state === "not_applicable" &&
    preview.binding.estimated_cost_microunits === null &&
    preview.binding.cost_currency === null &&
    isBoundedVersion(preview.binding.redactor_version) &&
    isBoundedVersion(preview.binding.estimator_plan_version) &&
    Number.isFinite(createdAt) &&
    Number.isFinite(expiresAt) &&
    expiresAt > Date.now() &&
    expiresAt > createdAt &&
    expiresAt - createdAt <= MAX_PREVIEW_LIFETIME_MS &&
    Number.isSafeInteger(preview.binding.message_count) &&
    preview.binding.message_count > 0 &&
    preview.binding.message_count <= COACHING_ANALYSIS_PRESET.maxMessages &&
    preview.binding.message_count === preview.messages.length &&
    Number.isSafeInteger(preview.binding.character_count) &&
    preview.binding.character_count > 0 &&
    preview.binding.character_count <= COACHING_ANALYSIS_PRESET.maxCharacters &&
    preview.binding.character_count === characterCount &&
    metricKeys.length === EXPECTED_METRIC_KEYS.size &&
    new Set(metricKeys).size === metricKeys.length &&
    metricKeys.every((key) => EXPECTED_METRIC_KEYS.has(key))
  );
}

function isTerminalSourceLimit(reasonCode: string | null): boolean {
  return reasonCode !== null && TERMINAL_SOURCE_LIMIT_REASONS.has(reasonCode);
}

function statusOf(error: unknown): number | null {
  if (
    typeof error === "object" && error !== null && "status" in error &&
    typeof error.status === "number"
  ) {
    return error.status;
  }
  return null;
}

function reasonCodeOf(error: unknown): string | null {
  if (
    typeof error === "object" && error !== null && "reasonCode" in error &&
    typeof error.reasonCode === "string"
  ) {
    return error.reasonCode;
  }
  return null;
}

function safeError(error: unknown): string {
  const reasonCode = reasonCodeOf(error);
  if (reasonCode === "redacted_content_consent_required") {
    return "Redacted-text access is not granted. Open Data sources, grant access, then prepare a fresh preview.";
  }
  if (reasonCode === "session_not_in_safe_index") {
    return "This session is no longer in the bounded safe index. Refresh Data sources, then reopen the session.";
  }
  if (reasonCode === "analysis_idempotency_conflict") {
    return "The one-shot request conflicts with an earlier local run. Refresh this session before preparing another preview.";
  }
  if (reasonCode === "redaction_preview_expired") {
    return "The ten-minute in-memory preview expired. Prepare a fresh preview before approving.";
  }
  if (reasonCode === "redaction_preview_consumed") {
    return "That one-shot preview was already consumed. Refresh the stored result before preparing another preview.";
  }
  if (reasonCode === "redaction_preview_binding_mismatch") {
    return "Approval was rejected because the exact preview binding changed. Nothing was approved from this screen; prepare a fresh preview.";
  }
  if (reasonCode === "redaction_preview_not_found") {
    return "The in-memory preview is no longer available. Prepare a fresh preview.";
  }
  if (reasonCode === "redaction_preview_capacity_reached") {
    return "The local preview limit is temporarily full. Wait for an older preview to expire, then retry.";
  }
  if (reasonCode === "invalid_analysis_request" || reasonCode === "confirmation_required") {
    return "The fixed coaching profile was rejected. Update and restart Prompt Enhancer, then retry.";
  }
  if (reasonCode === "source_schema_unsupported") {
    return "This Codex session uses a content schema this app version cannot safely read. Update Prompt Enhancer, restart it, and refresh the safe index.";
  }
  if (reasonCode === "selection_snapshot_miss") {
    return "The indexed session changed before the bounded read. Refresh the safe index, reopen this session, and prepare a new preview.";
  }
  if (reasonCode === "source_selection_limit") {
    return "The current Codex session catalog exceeds the local selection-scan limit. No session text, preview, or metric result was stored.";
  }
  if (reasonCode === "source_provider_response_limit") {
    return "A local Codex response exceeded the transport limit before the smaller preview window could be selected. No preview or metric result was created.";
  }
  if (reasonCode === "source_thread_structure_limit") {
    return "The selected session's full local thread structure exceeds this adapter version's parser limits. No preview or metric result was created.";
  }
  if (reasonCode === "source_preview_window_limit") {
    return "The selected focus message cannot fit in the fixed local preview window. No partial preview or metric result was created.";
  }
  if (reasonCode === "source_resource_limit") {
    return "The local source reached an unclassified safety limit before a preview could be prepared. No preview or metric result was created.";
  }
  if (reasonCode === "source_timeout") {
    return "The bounded local provider read timed out. Retry once; no provider content is included in this message.";
  }
  if (reasonCode === "provider_unavailable") {
    return "The Codex local provider is temporarily unavailable. Keep Codex running, then retry.";
  }
  if (reasonCode === "no_analyzable_text") {
    return "No analyzable prompt or response text was available in this bounded session. No preview or metric score was created.";
  }
  if (reasonCode === "provider_protocol_rejected") {
    return "Codex rejected the bounded session read. Retry once; if it repeats, restart Codex and Prompt Enhancer.";
  }
  if (reasonCode === "provider_compatibility_blocked") {
    return "Installed-schema compatibility changed after this review opened. Refresh the content-free compatibility status first.";
  }
  if (reasonCode === "analysis_persistence_failed") {
    return "The content-free immutable result could not be stored. Check the local database before preparing a fresh preview.";
  }
  if (reasonCode === "metric_execution_failed") {
    return "The local metric engine could not finish after one-shot approval. Refresh stored results before preparing a fresh preview.";
  }
  const status = statusOf(error);
  if (status === 403) {
    return "This local preview was not authorized. Review local-source access and try again.";
  }
  if (status === 404 || status === 410) {
    return "The selected session or its in-memory preview is no longer available. Prepare a fresh preview.";
  }
  if (status === 409) {
    return "The selected session or preview changed. Reopen the session and prepare a fresh preview.";
  }
  if (status === 405 || status === 501) {
    return "Preview-bound local analysis is not available in this running mode. Restart Prompt Enhancer in Local real mode after updating it.";
  }
  if (status === 413 || status === 422) {
    return "The fixed coaching preview was rejected by the local service.";
  }
  if (status === 503 || status === 504) {
    return "The local preview service is temporarily unavailable. Retry once; no provider content is included in this message.";
  }
  return "The private local preview flow could not be completed. Refresh once and retry; no transcript content is shown in this error.";
}

export function AnalyzeLocallyDialog({
  exactSessionId,
  onApprovePreview,
  onCheckCompatibility,
  onClose,
  onPreparePreview,
  sessionDescriptor = "Selected session",
}: {
  exactSessionId: string;
  onPreparePreview: (
    sessionId: string,
    request: SessionQualityAnalysisPreviewRequest,
    signal: AbortSignal,
  ) => Promise<SessionQualityAnalysisPreview>;
  onApprovePreview: (
    sessionId: string,
    previewId: string,
    request: SessionQualityAnalysisPreviewApprovalRequest,
    idempotencyKey: string,
    signal: AbortSignal,
  ) => Promise<void>;
  onCheckCompatibility?: (signal: AbortSignal) => Promise<void>;
  onClose: () => void;
  sessionDescriptor?: string;
}) {
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [preview, setPreview] = useState<SessionQualityAnalysisPreview | null>(null);
  const [completed, setCompleted] = useState(false);
  const [error, setError] = useState("");
  const [failureReason, setFailureReason] = useState<string | null>(null);
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const requestControllerRef = useRef<AbortController | null>(null);
  const approvalKeyRef = useRef("");
  const approvalStartedRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const openRef = useRef(true);
  const closeNotifiedRef = useRef(false);
  const requestEpochRef = useRef(0);
  const previewRef = useRef<SessionQualityAnalysisPreview | null>(preview);
  previewRef.current = preview;
  const initialSessionIdRef = useRef(exactSessionId);
  const initialDescriptorRef = useRef(sessionDescriptor);
  const onCloseRef = useRef(onClose);
  const onPreparePreviewRef = useRef(onPreparePreview);
  const onApprovePreviewRef = useRef(onApprovePreview);
  const onCheckCompatibilityRef = useRef(onCheckCompatibility);
  const id = useId();
  const titleId = `${id}-analyze-locally-title`;
  const summaryId = `${id}-analyze-locally-summary`;
  const completedTitleId = `${id}-analysis-completed-title`;
  const presetTitleId = `${id}-analysis-preset-title`;
  const bindingTitleId = `${id}-preview-binding-title`;
  const metricsTitleId = `${id}-preview-metrics-title`;
  const previewTitleId = `${id}-redacted-preview-title`;
  const ownsContext =
    exactSessionId === initialSessionIdRef.current &&
    onPreparePreview === onPreparePreviewRef.current &&
    onApprovePreview === onApprovePreviewRef.current &&
    onCheckCompatibility === onCheckCompatibilityRef.current;
  const ownsContextRef = useRef(ownsContext);
  ownsContextRef.current = ownsContext;
  const terminalPreparationFailure = isTerminalSourceLimit(failureReason);

  function canInteract(): boolean {
    return mountedRef.current && openRef.current && ownsContextRef.current;
  }

  function clearPreview() {
    previewRef.current = null;
    setPreview(null);
    approvalKeyRef.current = "";
    approvalStartedRef.current = null;
  }

  function close() {
    if (!openRef.current) return;
    openRef.current = false;
    requestEpochRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    clearPreview();
    if (!closeNotifiedRef.current) {
      closeNotifiedRef.current = true;
      onCloseRef.current();
    }
  }

  useLayoutEffect(() => {
    if (!ownsContext) close();
  }, [ownsContext]);

  useLayoutEffect(() => {
    mountedRef.current = true;
    if (!closeNotifiedRef.current) openRef.current = true;
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const appShell = document.querySelector<HTMLElement>(".app-shell");
    const wasInert = appShell?.inert ?? false;
    if (appShell) appShell.inert = true;
    primaryRef.current?.focus();

    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", keydown);
    return () => {
      window.removeEventListener("keydown", keydown);
      mountedRef.current = false;
      openRef.current = false;
      requestEpochRef.current += 1;
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
      if (appShell) appShell.inert = wasInert;
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  useEffect(() => {
    if (!preview || !canInteract()) return;
    primaryRef.current?.focus();
    const remaining = Date.parse(preview.expires_at) - Date.now();
    if (remaining <= 0) {
      clearPreview();
      setError("The ten-minute in-memory preview expired. Prepare a fresh preview before approving.");
      return;
    }
    const timeout = window.setTimeout(() => {
      if (!canInteract() || previewRef.current !== preview) return;
      if (approvalStartedRef.current === preview.preview_id) {
        // Privacy TTL: erase the expired sensitive preview text immediately,
        // but never disown the approval that was already dispatched for this
        // exact preview. Its one-shot receipt (or failure) stays
        // authoritative, and no new approval is possible because the
        // preview is gone.
        previewRef.current = null;
        setPreview(null);
        approvalKeyRef.current = "";
        return;
      }
      clearPreview();
      setError("The ten-minute in-memory preview expired. Prepare a fresh preview before approving.");
    }, remaining);
    return () => window.clearTimeout(timeout);
  }, [preview]);

  useEffect(() => {
    if (terminalPreparationFailure && canInteract()) primaryRef.current?.focus();
  }, [terminalPreparationFailure]);

  useEffect(() => {
    if (completed && canInteract()) primaryRef.current?.focus();
  }, [completed]);

  async function preparePreview() {
    if (!canInteract() || pendingAction !== null || requestControllerRef.current) {
      return;
    }
    const epoch = ++requestEpochRef.current;
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setError("");
    setFailureReason(null);
    setRequiresRefresh(false);
    setCompleted(false);
    clearPreview();
    setPendingAction("preview");
    cancelRef.current?.focus();
    try {
      const nextPreview = await onPreparePreviewRef.current(
        initialSessionIdRef.current,
        COACHING_ANALYSIS_PREVIEW_REQUEST,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        !canInteract() ||
        requestEpochRef.current !== epoch ||
        requestControllerRef.current !== controller
      ) {
        return;
      }
      if (!hasExactLocalPreviewContract(nextPreview, initialSessionIdRef.current)) {
        clearPreview();
        setError(
          "The prepared preview binding could not be verified as the exact local, no-cost, ephemeral Coaching v1 contract. Nothing can be approved; prepare a fresh preview.",
        );
        return;
      }
      approvalKeyRef.current = nextIdempotencyKey("quality-preview-approval");
      previewRef.current = nextPreview;
      setPreview(nextPreview);
    } catch (nextError) {
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch &&
        requestControllerRef.current === controller
      ) {
        setFailureReason(reasonCodeOf(nextError));
        setError(safeError(nextError));
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch
      ) {
        setPendingAction(null);
      }
    }
  }

  async function approvePreview() {
    if (
      !canInteract() ||
      !preview ||
      previewRef.current !== preview ||
      pendingAction !== null ||
      requestControllerRef.current ||
      approvalStartedRef.current === preview.preview_id ||
      approvalKeyRef.current.length === 0
    ) {
      return;
    }
    if (Date.now() >= Date.parse(preview.expires_at)) {
      clearPreview();
      setError("The ten-minute in-memory preview expired. Prepare a fresh preview before approving.");
      return;
    }
    if (!hasExactLocalPreviewContract(preview, initialSessionIdRef.current)) {
      clearPreview();
      setError(
        "The prepared preview binding could not be verified as the exact local, no-cost, ephemeral Coaching v1 contract. Nothing was approved; prepare a fresh preview.",
      );
      return;
    }
    const approvedPreview = preview;
    const epoch = ++requestEpochRef.current;
    const controller = new AbortController();
    requestControllerRef.current = controller;
    approvalStartedRef.current = approvedPreview.preview_id;
    setError("");
    setFailureReason(null);
    setPendingAction("approval");
    cancelRef.current?.focus();
    try {
      await onApprovePreviewRef.current(
        initialSessionIdRef.current,
        approvedPreview.preview_id,
        {
          confirmation: "approve_exact_redacted_preview",
          expected_binding: approvedPreview.binding,
        },
        approvalKeyRef.current,
        controller.signal,
      );
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch &&
        requestControllerRef.current === controller &&
        // The sensitive preview may already have been erased by the privacy
        // TTL while this exact approval was in flight; the dispatched
        // approval id, not the erased preview, owns this receipt.
        approvalStartedRef.current === approvedPreview.preview_id
      ) {
        // Approval resolves only after the immutable completed run has been
        // fetched and validated by the workspace. Drop the sensitive preview
        // immediately, but keep a content-free completion receipt visible so
        // an abstaining result cannot look like a failed or ignored click.
        clearPreview();
        setCompleted(true);
      }
    } catch (nextError) {
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch &&
        requestControllerRef.current === controller
      ) {
        // Approval is atomic and one-shot. Never offer a second click against
        // the same preview after an ambiguous or failed response.
        clearPreview();
        const reasonCode = reasonCodeOf(nextError);
        setFailureReason(reasonCode);
        setRequiresRefresh(![
          "redaction_preview_expired",
          "redaction_preview_binding_mismatch",
          "redaction_preview_not_found",
        ].includes(reasonCode ?? ""));
        setError(safeError(nextError));
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch
      ) {
        setPendingAction(null);
      }
    }
  }

  async function recheckCompatibility() {
    if (
      !canInteract() ||
      !onCheckCompatibilityRef.current ||
      pendingAction !== null ||
      requestControllerRef.current
    ) {
      return;
    }
    const epoch = ++requestEpochRef.current;
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setError("");
    setPendingAction("compatibility");
    cancelRef.current?.focus();
    try {
      await onCheckCompatibilityRef.current(controller.signal);
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch &&
        requestControllerRef.current === controller
      ) {
        setFailureReason(null);
      }
    } catch {
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch &&
        requestControllerRef.current === controller
      ) {
        setError(
          "The content-free compatibility check could not be completed. Retry the check or cancel; no session content was included in this error.",
        );
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (
        !controller.signal.aborted &&
        canInteract() &&
        requestEpochRef.current === epoch
      ) {
        setPendingAction(null);
      }
    }
  }

  const compatibilityBlocked = failureReason === "provider_compatibility_blocked";
  const pending = pendingAction !== null;
  const primaryLabel =
    pendingAction === "preview"
      ? "Preparing private preview…"
      : pendingAction === "approval"
        ? "Approving and analyzing locally…"
        : pendingAction === "compatibility"
          ? "Rechecking compatibility…"
          : compatibilityBlocked
            ? onCheckCompatibility ? "Recheck compatibility" : "Close"
            : terminalPreparationFailure
              ? "Close"
              : requiresRefresh
                ? "Close and refresh session"
                : preview
                  ? "Approve once and analyze"
                  : error
                    ? "Prepare fresh preview"
                    : "Prepare redacted preview";

  if (!ownsContext) return null;

  return createPortal(
    <div
      aria-describedby={summaryId}
      aria-labelledby={titleId}
      aria-modal="true"
      className="analysis-dialog"
      role="dialog"
    >
      <div className="analysis-dialog__scrim" />
      <section className="analysis-dialog__panel" ref={panelRef}>
        <header>
          <div>
            <p className="eyebrow">One session · local only · approval bound</p>
            <h2 id={titleId}>
              {completed ? "Analysis completed" : "Ready to analyze"}
            </h2>
            <p id={summaryId}>
              {completed
                ? "The immutable result was stored locally and loaded into this session view."
                : preview
                ? "Inspect the exact redacted window and binding before one-shot approval."
                : "Prepare an in-memory redacted window first. Preparation does not calculate or store metric results."}
            </p>
          </div>
          <button
            aria-label="Close analysis review"
            className="share-dialog__close"
            disabled={pending}
            onClick={close}
            type="button"
          >
            Close
          </button>
        </header>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (completed) {
              close();
              return;
            }
            void (preview ? approvePreview() : preparePreview());
          }}
        >
          {completed && (
            <section
              aria-labelledby={completedTitleId}
              className="analysis-dialog__success"
              role="status"
            >
              <strong id={completedTitleId}>Analysis completed and stored locally</strong>
              <span>
                The result is now visible behind this dialog. Individual metrics may still be
                Unknown or Abstained when the bounded window lacks their required evidence;
                that is a stored result, not an analysis failure.
              </span>
            </section>
          )}

          {!completed && (
            <>
          <section className="analysis-dialog__preset" aria-labelledby={presetTitleId}>
            <div className="analysis-dialog__preset-heading">
              <span aria-hidden="true">S1</span>
              <div>
                <strong id={presetTitleId}>
                  {COACHING_ANALYSIS_PRESET.label} v{COACHING_ANALYSIS_PRESET.version}
                </strong>
                <small>Fixed local scope; remote destinations remain disabled</small>
              </div>
            </div>
            <dl>
              <div>
                <dt>Selected session</dt>
                <dd>{initialDescriptorRef.current}</dd>
              </div>
              <div>
                <dt>Exact safe session ID</dt>
                <dd><code>{initialSessionIdRef.current}</code></dd>
              </div>
              <div>
                <dt>Coverage</dt>
                <dd>
                  {COACHING_ANALYSIS_PRESET.checkCount} checks · {COACHING_ANALYSIS_PRESET.supportedMeasurementPathCount} supported measurement paths · {COACHING_ANALYSIS_PRESET.sourceEvidenceGapKeys.length} need source evidence
                </dd>
              </div>
              <div>
                <dt>Bounded read</dt>
                <dd>
                  Up to {COACHING_ANALYSIS_PRESET.maxMessages} messages · {COACHING_ANALYSIS_PRESET.maxCharacters.toLocaleString("en")} redacted characters
                </dd>
              </div>
            </dl>
            <p>
              Missing evidence, unsupported capabilities, and unknown task-specific
              denominators stay Unknown or Abstained. They are never converted to zero.
            </p>
          </section>

          {preview && (
            <>
              <section className="analysis-dialog__binding" aria-labelledby={bindingTitleId}>
                <div>
                  <p className="eyebrow">Approval contract</p>
                  <h3 id={bindingTitleId}>Exact preview binding</h3>
                </div>
                <dl>
                  <div><dt>Provider</dt><dd><code>{preview.binding.provider}</code> · local adapter</dd></div>
                  <div><dt>Destination</dt><dd><code>{preview.binding.destination}</code> · this device only</dd></div>
                  <div><dt>Exact model</dt><dd><code>{preview.binding.exact_model}</code> · deterministic rules</dd></div>
                  <div><dt>Retention</dt><dd><code>{preview.binding.retention_class}</code> · service memory for ten minutes</dd></div>
                  <div><dt>API cost</dt><dd><code>{preview.binding.cost_state}</code> · no remote call</dd></div>
                  <div><dt>Size</dt><dd>{preview.binding.message_count} messages · {preview.binding.character_count.toLocaleString("en")} characters</dd></div>
                  <div><dt>Expires at</dt><dd><time dateTime={preview.expires_at}>{preview.expires_at}</time></dd></div>
                  <div><dt>Redactor</dt><dd><code>{preview.binding.redactor_version}</code></dd></div>
                  <div><dt>Estimator plan</dt><dd><code>{preview.binding.estimator_plan_version}</code></dd></div>
                  <div className="analysis-dialog__binding-wide">
                    <dt>Window fingerprint</dt>
                    <dd><code>{preview.binding.analysis_window_fingerprint}</code></dd>
                  </div>
                </dl>
              </section>

              <section className="analysis-dialog__metrics" aria-labelledby={metricsTitleId}>
                <div>
                  <p className="eyebrow">Selected metric set</p>
                  <h3 id={metricsTitleId}>{preview.binding.metric_keys.length} version-bound checks</h3>
                </div>
                <ul>
                  {preview.binding.metric_keys.map((key) => (
                    <li key={key}>
                      <code>{key}</code>
                      {COACHING_ANALYSIS_PRESET.sourceEvidenceGapKeys.includes(
                        key as typeof COACHING_ANALYSIS_PRESET.sourceEvidenceGapKeys[number],
                      ) && (
                        <span>
                          Needs source evidence: unavailable without typed, reviewed provider evidence
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
                <p>
                  This exact attempt records the four source-evidence gaps as unavailable.
                  A future analysis can resolve one only after a compatible typed-evidence
                  adapter produces reviewed evidence. The current provider does not substitute
                  agent prose, a model estimate, or a zero value.
                </p>
              </section>

              <section className="analysis-dialog__preview" aria-labelledby={previewTitleId}>
                <div>
                  <p className="eyebrow">Sensitive · memory only</p>
                  <h3 id={previewTitleId}>Exact redacted text window</h3>
                  <p>Review every item below. Text is not written to browser storage, logs, analytics, or the metrics database.</p>
                </div>
                <ol>
                  {preview.messages.map((message, index) => (
                    <li key={`${index}-${message.role}-${message.kind}`}>
                      <span>{message.role} · {message.kind} · {message.language}</span>
                      <p>{message.text}</p>
                    </li>
                  ))}
                </ol>
              </section>
            </>
          )}

          <div className="analysis-dialog__privacy" role="note">
            <strong>{preview ? "One-shot approval" : "Private preparation"}</strong>
            <span>
              {preview
                ? "Approval is valid only for the exact session, window fingerprint, metric set, model, redactor, destination, retention, size, and cost shown above. Any mismatch fails closed."
                : "Codex returns the selected session to a size-limited local adapter before Prompt Enhancer allowlists, redacts, and selects the bounded preview window in memory. Preparation does not call a remote model or persist preview text."}
            </span>
          </div>
            </>
          )}

          {error && <p className="analysis-dialog__error" role="alert">{error}</p>}
          <p aria-live="polite" className="analysis-dialog__status" role="status">
            {completed
              ? "The approved preview was consumed once and its content-free metric result is stored."
              : pendingAction === "preview"
              ? "Reading locally and preparing the bounded redacted window…"
              : pendingAction === "approval"
                ? "Consuming this exact approval once and calculating local metrics…"
                : pendingAction === "compatibility"
                  ? "Refreshing installed-schema compatibility without reading a session…"
                  : compatibilityBlocked
                    ? onCheckCompatibility
                      ? "Preview preparation is paused until compatibility is refreshed."
                      : "Compatibility rechecking is unavailable here. Close this dialog and review the provider status before trying again."
                    : terminalPreparationFailure
                      ? "This request is finished. Repeating it now would use the same session, adapter, and limits."
                    : requiresRefresh
                      ? "The approval result is uncertain or consumed. Close and refresh stored results before starting another preview."
                    : preview
                      ? "Nothing has been analyzed yet. Approval will consume this exact preview once."
                      : error
                        ? "No preview is active. Review the message, then prepare a fresh one."
                        : "Prepare first; review the exact redacted text and disclosure; then approve once."}
          </p>
          <p className="analysis-dialog__cancel-note">
            {completed
              ? "Choose View stored results to return to the refreshed metric profile."
              : terminalPreparationFailure
              ? "No preview or metric result was created. Close this dialog and choose another session, or update Prompt Enhancer when a more capable bounded adapter is available."
              : preview
                ? "Cancel removes this browser copy immediately; the local service copy expires automatically."
                : "Cancel stops this browser from waiting. A provider read already accepted locally may finish and expire without approval."}
          </p>
          <footer>
            {completed ? (
              <button
                className="button button--primary"
                onClick={close}
                ref={primaryRef}
                type="button"
              >
                View stored results
              </button>
            ) : terminalPreparationFailure ? (
              <button
                className="button button--primary"
                onClick={close}
                ref={primaryRef}
                type="button"
              >
                Close
              </button>
            ) : (
              <>
                <button
                  className="button button--secondary"
                  onClick={close}
                  ref={cancelRef}
                  type="button"
                >
                  {pending ? "Cancel request" : "Cancel"}
                </button>
                <button
                  className="button button--primary"
                  disabled={pending}
                  onClick={
                    compatibilityBlocked
                      ? onCheckCompatibility
                        ? () => void recheckCompatibility()
                        : close
                      : requiresRefresh
                        ? close
                      : undefined
                  }
                  ref={primaryRef}
                  type={compatibilityBlocked || requiresRefresh ? "button" : "submit"}
                >
                  {primaryLabel}
                </button>
              </>
            )}
          </footer>
        </form>
      </section>
    </div>,
    document.body,
  );
}
