import { useCallback, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  QualityProfileView,
  createQualityMetricProfile,
  type AnalyzeLocallyHandler,
} from "../../src/features/quality-profile";
import type {
  PromptEnhancerTransport,
  ProviderCompatibilityStatus,
  SessionQualityAnalysisPreview,
  SessionQualityAnalysisPreviewApprovalRequest,
  SessionQualityAnalysisPreviewRequest,
} from "../../src/shared/api/contracts";
import { parseProviderCompatibilityStatus } from "../../src/shared/api/httpTransport";
import { createSyntheticTransport } from "../../src/shared/api/syntheticTransport";
import {
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_SESSION_QUALITY_RUN,
} from "../../src/shared/api/syntheticFixtures";
import "../../src/styles.css";
import "../../src/app/theme.css";
import "../../src/app/palette.generated.css";

const SESSION_ID = SYNTHETIC_QUALITY_SESSION_ID;

type Mode = "operational-exact" | "operational-compatible" | "text" | "recovery";
type Counter = "compatibilityRead" | "compatibilityCheck" | "preview" | "approval";
type Counters = Record<Counter, number>;
type FixtureTransport = PromptEnhancerTransport & Required<Pick<
  PromptEnhancerTransport,
  "getProviderCompatibility" | "checkProviderCompatibility"
>>;

const TEXT_EXACT = parseProviderCompatibilityStatus({
  provider: "synthetic",
  capability: "session_text_analysis",
  state: "exact",
  capability_state: "supported",
  provider_family: "synthetic_provider",
  provider_version: "preview-1",
  adapter_family: "synthetic_adapter",
  adapter_version: "preview-1",
  source_schema_family: "synthetic_session",
  source_schema_version: "preview-1",
  content_schema_family: "synthetic_content",
  content_schema_version: "preview-1",
  reason_code: "exact_match",
  checked_at: "2040-01-03T09:12:30Z",
  update_support: "unsupported",
  update_target: null,
}, "synthetic");

function operationalStatus(
  state: "exact" | "compatible" | "degraded",
): ProviderCompatibilityStatus {
  return parseProviderCompatibilityStatus({
    ...TEXT_EXACT,
    capability: "operational_events",
    state,
    reason_code:
      state === "compatible"
        ? "compatible_version"
        : state === "degraded"
          ? "degraded_extraction"
          : "exact_match",
  }, "synthetic");
}

function initialStatus(mode: Mode): ProviderCompatibilityStatus {
  if (mode === "text") return TEXT_EXACT;
  if (mode === "operational-compatible") return operationalStatus("compatible");
  if (mode === "recovery") return operationalStatus("degraded");
  return operationalStatus("exact");
}

function readMode(): Mode {
  const mode = new URLSearchParams(location.search).get("mode");
  return mode === "operational-compatible" || mode === "text" || mode === "recovery"
    ? mode
    : "operational-exact";
}

function Fixture() {
  const mode = readMode();
  const [status, setStatus] = useState<ProviderCompatibilityStatus>(() => initialStatus(mode));
  const statusRef = useRef(status);
  statusRef.current = status;
  const [compatibilityLoading, setCompatibilityLoading] = useState(false);
  const [counters, setCounters] = useState<Counters>({
    compatibilityRead: 0,
    compatibilityCheck: 0,
    preview: 0,
    approval: 0,
  });
  const resolveDeferredCheck = useRef<(() => void) | null>(null);
  const base = useMemo(() => createSyntheticTransport(), []);
  const profile = useMemo(
    () => createQualityMetricProfile(
      "prompt-quality",
      structuredClone(SYNTHETIC_SESSION_QUALITY_RUN),
      SESSION_ID,
    )!,
    [],
  );
  const increment = useCallback((counter: Counter) => {
    setCounters((current) => ({ ...current, [counter]: current[counter] + 1 }));
  }, []);

  const transport = useMemo<FixtureTransport>(() => ({
    ...base,
    getProviderCompatibility: async () => {
      increment("compatibilityRead");
      return structuredClone(statusRef.current);
    },
    checkProviderCompatibility: async () => {
      increment("compatibilityCheck");
      return structuredClone(TEXT_EXACT);
    },
    prepareSessionQualityAnalysisPreview: async (
      sessionId: string,
      request: SessionQualityAnalysisPreviewRequest,
      _signal?: AbortSignal,
    ) => {
      increment("preview");
      return base.prepareSessionQualityAnalysisPreview(sessionId, request);
    },
    approveSessionQualityAnalysisPreview: async (
      previewId: string,
      request: SessionQualityAnalysisPreviewApprovalRequest,
      idempotencyKey: string,
      _signal?: AbortSignal,
    ) => {
      increment("approval");
      return base.approveSessionQualityAnalysisPreview(
        previewId,
        request,
        idempotencyKey,
      );
    },
  }), [base, increment]);

  const onCheckProviderCompatibility = useCallback(async (signal: AbortSignal) => {
    setCompatibilityLoading(true);
    try {
      await transport.checkProviderCompatibility("synthetic", signal);
      if (mode !== "recovery") return;
      await new Promise<void>((resolve) => {
        const finish = () => {
          resolveDeferredCheck.current = null;
          resolve();
        };
        resolveDeferredCheck.current = () => {
          setStatus(TEXT_EXACT);
          finish();
        };
        signal.addEventListener("abort", finish, { once: true });
      });
    } finally {
      setCompatibilityLoading(false);
    }
  }, [mode, transport]);

  const analysisHandler = useMemo<AnalyzeLocallyHandler>(() => ({
    exactSessionId: SESSION_ID,
    preparePreview: (
      sessionId: string,
      request: SessionQualityAnalysisPreviewRequest,
      signal: AbortSignal,
    ): Promise<SessionQualityAnalysisPreview> =>
      transport.prepareSessionQualityAnalysisPreview(sessionId, request, signal),
    approvePreview: (
      _sessionId: string,
      previewId: string,
      request: SessionQualityAnalysisPreviewApprovalRequest,
      idempotencyKey: string,
      signal: AbortSignal,
    ): Promise<void> => transport.approveSessionQualityAnalysisPreview(
      previewId,
      request,
      idempotencyKey,
      signal,
    ).then(() => undefined),
  }), [transport]);

  return (
    <main>
      <p className="eyebrow">Synthetic capability gate · content-free counters only</p>
      {mode === "recovery" && (
        <button
          onClick={() => resolveDeferredCheck.current?.()}
          type="button"
        >
          Resolve synthetic provider check
        </button>
      )}
      <output data-testid="compatibility-read-count">Compatibility reads: {counters.compatibilityRead}</output>
      <output data-testid="compatibility-check-count">Compatibility checks: {counters.compatibilityCheck}</output>
      <output data-testid="preview-count">Preview preparations: {counters.preview}</output>
      <output data-testid="approval-count">Preview approvals: {counters.approval}</output>
      <QualityProfileView
        analysisCapability={{
          available: true,
          reason_code: "available",
          data_tier: "redacted_content",
          content_persistence: false,
          network_inference: false,
          raw_transcripts: false,
        }}
        compatibilityLoading={compatibilityLoading}
        onAnalyzeLocally={analysisHandler}
        onCheckProviderCompatibility={onCheckProviderCompatibility}
        profile={profile}
        providerCompatibility={status}
      />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
