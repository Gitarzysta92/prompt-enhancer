import { useMemo, useState, type ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { ApplicationUpdateControl } from "../../src/app/ApplicationUpdateControl";
import type {
  ApplicationUpdateMutationRequest,
  ApplicationUpdateStatus,
  PromptEnhancerTransport,
} from "../../src/shared/api/contracts";
import { bootstrapTheme } from "../../src/shared/platform/theme";
import "../../src/styles.css";
import "../../src/app/theme.css";
import "../../src/app/palette.generated.css";

bootstrapTheme();

const parameters = new URLSearchParams(window.location.search);
const mode = parameters.get("mode") ?? "flow";
const INSTANCE_ID = "a".repeat(32);
const ARTIFACT_SIZE = 25 * 1024 ** 2;
const timestamp = "2040-01-01T00:00:00Z";

function status(overrides: Partial<ApplicationUpdateStatus>): ApplicationUpdateStatus {
  return {
    contract_version: "application-update-status.v3",
    instance_id: INSTANCE_ID,
    revision: 1,
    contains_private_data: false,
    installed_version: "1.2.3",
    channel: "stable",
    state: "current",
    available_version: null,
    artifact_size_bytes: null,
    downloaded_bytes: null,
    last_checked_at: timestamp,
    reason_code: null,
    verification_code: null,
    can_check: true,
    can_stage: false,
    can_cancel: false,
    can_retry: false,
    can_apply: false,
    can_verify: false,
    package_review: { state: "not_staged", reason_code: null, checked_at: null },
    ...overrides,
  };
}

const UNCONFIGURED = status({
  state: "unconfigured",
  last_checked_at: null,
  reason_code: "release_feed_unconfigured",
  can_check: false,
  package_review: { state: "not_configured", reason_code: null, checked_at: null },
});

type Action = "check" | "stage" | "cancel" | "retry" | "verify";
type UpdateTransport = Pick<
  PromptEnhancerTransport,
  | "getApplicationUpdateStatus"
  | "checkApplicationUpdate"
  | "stageApplicationUpdate"
  | "cancelApplicationUpdate"
  | "retryApplicationUpdate"
  | "verifyApplicationUpdate"
>;

function createTransport(
  onReceipt: (value: string) => void,
  onRead: () => void,
  onAbort: () => void,
  onSnapshot: (value: ApplicationUpdateStatus) => void,
): UpdateTransport {
  let current = mode === "unconfigured"
    ? UNCONFIGURED
    : mode === "rejected"
      ? status({
        state: "staged",
        available_version: "2.0.0",
        artifact_size_bytes: ARTIFACT_SIZE,
        downloaded_bytes: ARTIFACT_SIZE,
        can_check: true,
        can_verify: true,
        package_review: { state: "rejected", reason_code: "unsupported_package", checked_at: timestamp },
      })
      : status({ revision: 1 });
  let failedFirstRead = mode === "status-retry";
  let completeOnNextRead: "failed" | "staged" | "verified" | null = null;

  const mutation = (action: Action, request: ApplicationUpdateMutationRequest): void => {
    if (request.expected_instance_id !== INSTANCE_ID || request.expected_revision !== current.revision) {
      throw new Error("synthetic stale update fence");
    }
    onReceipt(JSON.stringify({ action, request }));
  };

  const getApplicationUpdateStatus = async (signal?: AbortSignal): Promise<ApplicationUpdateStatus> => {
    if (mode === "unmount") {
      await new Promise<never>((_resolve, reject) => {
        const abort = () => {
          onAbort();
          reject(new DOMException("synthetic status read aborted", "AbortError"));
        };
        if (signal?.aborted) abort();
        else signal?.addEventListener("abort", abort, { once: true });
      });
    }
    onRead();
    if (failedFirstRead) {
      failedFirstRead = false;
      throw new Error("synthetic local status read failed");
    }
    if (completeOnNextRead === "failed") {
      completeOnNextRead = null;
      current = status({
        state: "failed",
        revision: current.revision + 1,
        available_version: "2.0.0",
        artifact_size_bytes: ARTIFACT_SIZE,
        downloaded_bytes: 8 * 1024 ** 2,
        reason_code: "staging_interrupted",
        can_check: false,
        can_retry: true,
      });
    } else if (completeOnNextRead === "staged") {
      completeOnNextRead = null;
      current = status({
        state: "staged",
        revision: current.revision + 1,
        available_version: "2.0.0",
        artifact_size_bytes: ARTIFACT_SIZE,
        downloaded_bytes: ARTIFACT_SIZE,
        can_check: true,
        can_verify: true,
        package_review: { state: "not_checked", reason_code: null, checked_at: null },
      });
    } else if (completeOnNextRead === "verified") {
      completeOnNextRead = null;
      current = status({
        state: "staged",
        revision: current.revision + 1,
        available_version: "2.0.0",
        artifact_size_bytes: ARTIFACT_SIZE,
        downloaded_bytes: ARTIFACT_SIZE,
        can_check: true,
        can_verify: true,
        package_review: { state: "verified", reason_code: null, checked_at: timestamp },
      });
    }
    onSnapshot(current);
    return current;
  };

  const checkApplicationUpdate = async (request: ApplicationUpdateMutationRequest): Promise<ApplicationUpdateStatus> => {
    mutation("check", request);
    current = status({
      state: "available",
      revision: current.revision + 1,
      available_version: "2.0.0",
      artifact_size_bytes: ARTIFACT_SIZE,
      downloaded_bytes: 0,
      can_stage: true,
    });
    onSnapshot(current);
    return current;
  };

  const stageApplicationUpdate = async (request: ApplicationUpdateMutationRequest): Promise<ApplicationUpdateStatus> => {
    mutation("stage", request);
    current = status({
      state: "staging",
      revision: current.revision + 1,
      available_version: "2.0.0",
      artifact_size_bytes: ARTIFACT_SIZE,
      downloaded_bytes: 8 * 1024 ** 2,
      can_check: false,
      can_cancel: true,
    });
    onSnapshot(current);
    return current;
  };

  const cancelApplicationUpdate = async (request: ApplicationUpdateMutationRequest): Promise<ApplicationUpdateStatus> => {
    mutation("cancel", request);
    current = status({
      state: "staging",
      revision: current.revision + 1,
      available_version: "2.0.0",
      artifact_size_bytes: ARTIFACT_SIZE,
      downloaded_bytes: 8 * 1024 ** 2,
      can_check: false,
      can_cancel: false,
    });
    completeOnNextRead = "failed";
    onSnapshot(current);
    return current;
  };

  const retryApplicationUpdate = async (request: ApplicationUpdateMutationRequest): Promise<ApplicationUpdateStatus> => {
    mutation("retry", request);
    current = status({
      state: "staging",
      revision: current.revision + 1,
      available_version: "2.0.0",
      artifact_size_bytes: ARTIFACT_SIZE,
      downloaded_bytes: 20 * 1024 ** 2,
      can_check: false,
      can_cancel: true,
    });
    completeOnNextRead = "staged";
    onSnapshot(current);
    return current;
  };

  const verifyApplicationUpdate = async (request: ApplicationUpdateMutationRequest): Promise<ApplicationUpdateStatus> => {
    mutation("verify", request);
    current = status({
      state: "verifying",
      revision: current.revision + 1,
      available_version: "2.0.0",
      artifact_size_bytes: ARTIFACT_SIZE,
      downloaded_bytes: ARTIFACT_SIZE,
      can_check: false,
      can_stage: false,
      can_cancel: false,
      can_retry: false,
      can_verify: false,
      package_review: { state: "checking", reason_code: null, checked_at: null },
    });
    completeOnNextRead = "verified";
    onSnapshot(current);
    return current;
  };

  return {
    getApplicationUpdateStatus,
    checkApplicationUpdate,
    stageApplicationUpdate,
    cancelApplicationUpdate,
    retryApplicationUpdate,
    verifyApplicationUpdate,
  };
}

function Fixture(): ReactElement {
  const [receipt, setReceipt] = useState("none");
  const [reads, setReads] = useState(0);
  const [aborted, setAborted] = useState(false);
  const [snapshot, setSnapshot] = useState("pending");
  const [mounted, setMounted] = useState(true);
  const transport = useMemo(() => createTransport(
    setReceipt,
    () => setReads((value) => value + 1),
    () => setAborted(true),
    (value) => setSnapshot(`state=${value.state}; can_cancel=${String(value.can_cancel)}; can_retry=${String(value.can_retry)}`),
  ), []);

  return (
    <main style={{ boxSizing: "border-box", maxWidth: 560, minHeight: "100vh", padding: 16, width: "100%" }}>
      <h1>Synthetic application updates</h1>
      <p data-testid="fixture-source">Synthetic in-memory transport · no network, provider, model, or installer.</p>
      <output data-testid="status-reads">Local status reads: {reads}</output>
      <output data-testid="synthetic-state">Synthetic status: {snapshot}</output>
      {mode === "unmount" && <output data-testid="status-aborted">Status read aborted: {String(aborted)}</output>}
      {mode === "unmount" && (
        <button onClick={() => setMounted(false)} type="button">Unmount update control</button>
      )}
      {mounted && <ApplicationUpdateControl transport={transport} variant="drawer" />}
      <p data-testid="update-receipt" style={{ overflowWrap: "anywhere", wordBreak: "break-word" }}>
        Last synthetic mutation: {receipt}
      </p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
