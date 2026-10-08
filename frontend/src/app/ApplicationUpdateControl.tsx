import { useEffect, useRef, useState } from "react";
import type {
  ApplicationUpdateMutationRequest,
  ApplicationUpdateStatus,
  PromptEnhancerTransport,
} from "../shared/api/contracts";
import { Icon } from "../shared/ui/Icon";

type LoadState = "loading" | "ready" | "unavailable";
type UpdateAction = "check" | "stage" | "cancel" | "retry" | "verify";
type UpdateTransport = Pick<
  PromptEnhancerTransport,
  | "getApplicationUpdateStatus"
  | "checkApplicationUpdate"
  | "stageApplicationUpdate"
  | "cancelApplicationUpdate"
  | "retryApplicationUpdate"
  | "verifyApplicationUpdate"
>;

function sizeLabel(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "";
  const mebibytes = bytes / (1024 ** 2);
  return `${mebibytes >= 10 ? Math.round(mebibytes) : mebibytes.toFixed(1)} MiB`;
}

function isDownloadFailure(reason: ApplicationUpdateStatus["reason_code"]): boolean {
  return reason === "artifact_download_failed"
    || reason === "artifact_verification_failed"
    || reason === "staging_interrupted";
}

function retryLabel(status: ApplicationUpdateStatus | null): string {
  return status !== null && isDownloadFailure(status.reason_code)
    ? "Retry download"
    : "Retry update";
}

function reviewReason(reason: ApplicationUpdateStatus["package_review"]["reason_code"]): string {
  switch (reason) {
    case "bad_signature":
    case "signature_invalid": return "The release signature was not accepted";
    case "unknown_key":
    case "signer_mismatch": return "The release signer is not recognized";
    case "signature_unverifiable": return "The package signature could not be checked";
    case "expired": return "The downloaded release has expired";
    case "replayed_release": return "This release is older than the trusted release floor";
    case "release_identity_conflict":
    case "release_binding_mismatch":
    case "identity_mismatch": return "The package identity does not match this release";
    case "unsupported_platform":
    case "unsupported_package": return "This package format is not supported here";
    case "package_io_failed": return "The package could not be read";
    case "package_changed": return "The package changed while it was being checked";
    case "archive_invalid":
    case "manifest_invalid": return "The package metadata is invalid";
    case "invalid_encoding":
    case "invalid_schema": return "The package metadata is invalid";
    default: return "The package could not be verified";
  }
}

function copyFor(status: ApplicationUpdateStatus | null, loadState: LoadState, action: UpdateAction | null) {
  if (loadState === "loading") return { headline: "Software updates", detail: "Reading local update status" };
  if (action !== null) {
    const labels: Record<UpdateAction, string> = {
      check: "Checking for updates",
      stage: "Downloading update",
      cancel: "Stopping update download",
      retry: "Retrying update operation",
      verify: "Verifying downloaded package",
    };
    return { headline: labels[action], detail: action === "verify" ? "Local package review only; installation remains disabled" : "Requested release check/download; no automatic installation" };
  }
  if (status === null) return { headline: "Update status unavailable", detail: "Retry the local status check" };
  switch (status.state) {
    case "unconfigured":
      return { headline: "Updates not connected", detail: `Version ${status.installed_version} · ${status.channel}` };
    case "ready_to_check":
      return { headline: "Software updates", detail: `Version ${status.installed_version} · check manually` };
    case "checking":
      return { headline: "Checking for updates", detail: "Signed release manifest only" };
    case "current":
      return { headline: "Software is current", detail: `Version ${status.installed_version} · check again` };
    case "available":
      return {
        headline: `Version ${status.available_version} available`,
        detail: status.can_stage
          ? `${sizeLabel(status.artifact_size_bytes)} · download available`
          : `${sizeLabel(status.artifact_size_bytes)} · download not connected`,
      };
    case "staging":
      return {
        headline: status.can_cancel
          ? `Downloading version ${status.available_version}`
          : `Stopping download for version ${status.available_version}`,
        detail: `${sizeLabel(status.downloaded_bytes)} of ${sizeLabel(status.artifact_size_bytes)}`,
      };
    case "staged":
      if (status.package_review.state === "verified") {
        return { headline: `Version ${status.available_version} reviewed`, detail: "Package checks passed · installation handoff is not connected" };
      }
      if (status.package_review.state === "rejected") {
        return { headline: `Version ${status.available_version} needs review`, detail: reviewReason(status.package_review.reason_code) };
      }
      if (status.package_review.state === "not_checked") {
        return {
          headline: `Version ${status.available_version} downloaded`,
          detail: "Hash verified · publisher verification has not been run · installation handoff is not connected",
        };
      }
      return {
        headline: `Version ${status.available_version} downloaded`,
        detail: "Hash verified · publisher verification and installation handoff are not connected",
      };
    case "verifying":
      return { headline: "Verifying downloaded package", detail: "Checking package identity; installation remains disabled" };
    case "failed":
      if (status.reason_code === "staging_cleanup_unconfirmed") {
        return { headline: "Update cleanup needs review", detail: "Cleanup could not be confirmed · actions remain blocked" };
      }
      if (!status.can_retry) {
        return status.can_check
          ? {
            headline: isDownloadFailure(status.reason_code) ? "Update download needs attention" : "Update check needs attention",
            detail: "A fresh signed-release check is available",
          }
          : {
            headline: isDownloadFailure(status.reason_code) ? "Update download needs review" : "Update check needs review",
            detail: "Recovery needs review · actions remain blocked",
          };
      }
      return isDownloadFailure(status.reason_code)
        ? { headline: "Update download needs attention", detail: "No application changes were made · retry the local download" }
        : { headline: "Update check needs attention", detail: "No application changes were made · retry the local check" };
  }
}

export function ApplicationUpdateControl({
  transport,
  variant,
}: {
  transport: UpdateTransport;
  variant: "sidebar" | "drawer";
}) {
  const [status, setStatus] = useState<ApplicationUpdateStatus | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [activeAction, setActiveAction] = useState<UpdateAction | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const requestRevision = useRef(0);
  const activeController = useRef<AbortController | null>(null);
  const activeActionRef = useRef<UpdateAction | null>(null);
  const statusRef = useRef<ApplicationUpdateStatus | null>(null);
  const transportEpoch = useRef(0);
  const previousTransport = useRef(transport);
  const transportChanged = previousTransport.current !== transport;
  if (transportChanged) {
    previousTransport.current = transport;
    transportEpoch.current += 1;
  }

  statusRef.current = status;
  const acceptStatus = (next: ApplicationUpdateStatus): boolean => {
    const previous = statusRef.current;
    if (previous !== null && (previous.instance_id !== next.instance_id || next.revision < previous.revision)) return false;
    statusRef.current = next;
    return true;
  };

  useEffect(() => {
    const epoch = transportEpoch.current;
    const revision = ++requestRevision.current;
    const controller = new AbortController();
    activeController.current = controller;
    setStatus(null);
    statusRef.current = null;
    setActiveAction(null);
    activeActionRef.current = null;
    setDetailsOpen(false);
    const load = transport.getApplicationUpdateStatus;
    if (load === undefined) {
      setStatus(null);
      setActiveAction(null);
      setLoadState("unavailable");
      return () => {
        controller.abort();
        requestRevision.current += 1;
      };
    }
    setLoadState("loading");
    void load(controller.signal).then(
      (next) => {
        if (!controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          if (acceptStatus(next)) setStatus(next);
          setLoadState("ready");
          activeController.current = null;
        }
      },
      () => {
        if (!controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          statusRef.current = null;
          setStatus(null);
          setLoadState("unavailable");
          activeController.current = null;
        }
      },
    );
    return () => {
      controller.abort();
      activeController.current?.abort();
      requestRevision.current += 1;
    };
  }, [transport]);

  useEffect(() => {
    if (transportChanged || activeAction !== null || status === null || !["checking", "staging", "verifying"].includes(status.state)) return;
    const epoch = transportEpoch.current;
    const load = transport.getApplicationUpdateStatus;
    if (load === undefined) return;
    let disposed = false;
    const revision = ++requestRevision.current;
    const controller = new AbortController();
    activeController.current = controller;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await load(controller.signal);
        if (disposed || controller.signal.aborted || transportEpoch.current !== epoch || requestRevision.current !== revision) return;
        if (!acceptStatus(next)) {
          statusRef.current = null;
          setStatus(null);
          setLoadState("unavailable");
          activeController.current = null;
          return;
        }
        setStatus(next);
        if (next.state === "checking" || next.state === "staging" || next.state === "verifying") {
          timer = window.setTimeout(() => void poll(), 750);
        } else {
          setLoadState("ready");
          activeController.current = null;
        }
      } catch {
        if (!disposed && !controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          statusRef.current = null;
          setStatus(null);
          setLoadState("unavailable");
          activeController.current = null;
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 750);
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
      controller.abort();
      if (requestRevision.current === revision) requestRevision.current += 1;
    };
  }, [activeAction, status?.state, transport, transportChanged]);

  function readStatus(): void {
    const load = transport.getApplicationUpdateStatus;
    if (load === undefined || loadState === "loading") return;
    activeController.current?.abort();
    const revision = ++requestRevision.current;
    const epoch = transportEpoch.current;
    const controller = new AbortController();
    activeController.current = controller;
    setLoadState("loading");
    void load(controller.signal).then(
      (next) => {
        if (!controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          if (acceptStatus(next)) {
            setStatus(next);
            setLoadState("ready");
          } else {
            statusRef.current = null;
            setStatus(null);
            setLoadState("unavailable");
          }
          activeController.current = null;
        }
      },
      () => {
        if (!controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          statusRef.current = null;
          setStatus(null);
          setLoadState("unavailable");
          activeController.current = null;
        }
      },
    );
  }

  function runAction(action: UpdateAction): void {
    const run = transport[`${action}ApplicationUpdate` as keyof UpdateTransport] as
      | ((request: ApplicationUpdateMutationRequest, signal?: AbortSignal) => Promise<ApplicationUpdateStatus>)
      | undefined;
    if (run === undefined || status === null || activeActionRef.current !== null) return;
    if (
      (action === "check" && status.can_check !== true)
      || (action === "stage" && status.can_stage !== true)
      || (action === "cancel" && status.can_cancel !== true)
      || (action === "retry" && status.can_retry !== true)
      || (action === "verify" && (status.can_verify !== true || status.state !== "staged"))
    ) return;
    const revision = ++requestRevision.current;
    const epoch = transportEpoch.current;
    const controller = new AbortController();
    activeController.current?.abort();
    activeController.current = controller;
    activeActionRef.current = action;
    setActiveAction(action);
    setDetailsOpen(true);
    void run({ expected_revision: status.revision, expected_instance_id: status.instance_id }, controller.signal).then(
      (next) => {
        if (!controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          if (acceptStatus(next)) setStatus(next);
          else {
            statusRef.current = null;
            setStatus(null);
            setLoadState("unavailable");
          }
          activeActionRef.current = null;
          setActiveAction(null);
          if (statusRef.current !== null) setLoadState("ready");
          activeController.current = null;
        }
      },
      () => {
        if (!controller.signal.aborted && transportEpoch.current === epoch && requestRevision.current === revision) {
          statusRef.current = null;
          setStatus(null);
          activeActionRef.current = null;
          setActiveAction(null);
          setLoadState("unavailable");
          activeController.current = null;
        }
      },
    );
  }

  const copy = copyFor(status, loadState, activeAction);
  const busy = loadState === "loading" || activeAction !== null;
  const summaryId = `application-update-detail-${variant}`;
  const state = loadState === "ready" && status !== null ? status.state : loadState;
  const canReadStatus = typeof transport.getApplicationUpdateStatus === "function";
  const readRetry = status === null && loadState === "unavailable" && canReadStatus;
  const availableActionButtons: Array<{ action: UpdateAction; label: string; enabled: boolean }> = [
    { action: "check", label: "Check for updates", enabled: status?.can_check === true && typeof transport.checkApplicationUpdate === "function" },
    { action: "stage", label: `Download version ${status?.available_version ?? "update"}`, enabled: status?.can_stage === true && typeof transport.stageApplicationUpdate === "function" },
    { action: "cancel", label: "Cancel download", enabled: status?.can_cancel === true && typeof transport.cancelApplicationUpdate === "function" },
    { action: "retry", label: retryLabel(status), enabled: status?.can_retry === true && typeof transport.retryApplicationUpdate === "function" },
    { action: "verify", label: "Verify downloaded package", enabled: status?.state === "staged" && status.can_verify === true && typeof transport.verifyApplicationUpdate === "function" },
  ];
  const actionButtons = availableActionButtons.filter(({ action, enabled }) => enabled || activeAction === action);

  return (
    <section
      aria-label="Software updates"
      className={`application-update application-update--${variant}`}
      data-update-state={state}
    >
      <button
        aria-busy={busy || undefined}
        aria-controls={summaryId}
        aria-expanded={detailsOpen}
        disabled={(status === null && !readRetry) || (busy && !readRetry)}
        onClick={() => (readRetry ? readStatus() : setDetailsOpen((open) => !open))}
        type="button"
      >
        <span className="application-update__icon"><Icon name="refresh" /></span>
        <span className="application-update__copy">
          <strong>{readRetry ? "Retry update status" : copy.headline}</strong>
          <small>{copy.detail}</small>
        </span>
        {status !== null && (status.state === "available" || status.state === "staged") && (
          <span className="application-update__badge">New</span>
        )}
      </button>
      <div className="application-update__details" hidden={!detailsOpen} id={summaryId}>
        {status?.state === "unconfigured" && (
          <p>Updates are not connected. Checking, downloading, and installation remain off.</p>
        )}
        {status?.state === "staged" && (
          <div className="application-update__review" aria-label="Update review">
            {status.package_review.state === "rejected"
              ? <p>The downloaded release did not pass package review. Installation handoff is not connected.</p>
              : <p>Downloaded bytes match the signed manifest. Installation handoff is not connected.</p>}
            <p>Release {status.available_version} · {sizeLabel(status.downloaded_bytes)} downloaded</p>
            {status.package_review.state === "not_configured" && (
              <p>Publisher verification is not connected.</p>
            )}
            {status.package_review.state === "not_checked" && (
              <p>Publisher verification has not been run.</p>
            )}
            {status.package_review.state === "verified" && (
              <p>Publisher verification passed at {status.package_review.checked_at ?? "an unknown time"}. Installation remains disabled.</p>
            )}
            {status.package_review.state === "rejected" && (
              <p>Package review was not accepted: {reviewReason(status.package_review.reason_code)}.</p>
            )}
          </div>
        )}
        <div className="application-update__actions" aria-label="Update actions">
          {actionButtons.map(({ action, label, enabled }) => (
            <button
              disabled={!enabled || busy}
              key={action}
              onClick={() => runAction(action)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <span aria-live="polite" className="sr-only">
        {copy.headline}. {copy.detail}.
      </span>
    </section>
  );
}
