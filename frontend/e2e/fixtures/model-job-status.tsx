import { ModelEnsemblePanel } from "../../src/features/model-ensemble/ModelEnsemblePanel";
import { ModelEnsembleOverlay } from "../../src/features/model-ensemble/ModelEnsembleOverlay";
import type { ModelEnsembleWatchSnapshot, PromptEnhancerTransport, ProviderCompatibilityStatus } from "../../src/shared/api/contracts";
import { parseModelEnsembleWatchSnapshot } from "../../src/shared/api/modelEnsembleWatchContract";
import { TransportError } from "../../src/shared/api/httpTransport";
import { createSyntheticTransport } from "../../src/shared/api/syntheticTransport";
import { SYNTHETIC_QUALITY_PROJECT_ID, SYNTHETIC_QUALITY_SESSION_ID } from "../../src/shared/api/syntheticFixtures";

// In-memory failure receipt only. No provider files, real jobs or model calls.
let snapshot: ModelEnsembleWatchSnapshot = parseModelEnsembleWatchSnapshot({
  watch: {
    watch_id: "d".repeat(64), provider: "codex", project_id: SYNTHETIC_QUALITY_PROJECT_ID,
    session_id: SYNTHETIC_QUALITY_SESSION_ID, max_messages: 100, state: "failed", generation: 1,
    progress_completed: 0, progress_total: 10, has_result: false,
    last_error_code: "model_ensemble_cleanup_unconfirmed", quarantined: true,
    quarantine_reason_code: "model_ensemble_cleanup_unconfirmed",
    next_check_at: "2040-01-01T00:01:00Z", updated_at: "2040-01-01T00:00:00Z",
    serial_model_execution: true, process_isolated_model_release: true, cuda_resource_retry_on_cpu: true,
    content_persisted: false, calibrated_as_truth: false,
  },
  latest_run: null,
});

const transport: PromptEnhancerTransport = {
  ...createSyntheticTransport(),
  async getActiveModelEnsembleWatch() {
    if (snapshot.watch.state === "disabled") throw new TransportError("example watch is stopped", 404);
    return structuredClone(snapshot);
  },
  async startModelEnsemble() {
    throw new TransportError("example cleanup unconfirmed", 503, "model_ensemble_cleanup_unconfirmed");
  },
  async refreshModelEnsembleWatch() {
    return structuredClone(snapshot);
  },
  async disableModelEnsembleWatch() {
    snapshot = { ...snapshot, watch: { ...snapshot.watch, state: "disabled" } };
    return structuredClone(snapshot);
  },
};

const compatible: ProviderCompatibilityStatus = {
  provider: "codex", capability: "session_text_analysis", state: "exact", capability_state: "supported",
  provider_family: "codex_app_server", provider_version: "1.2.3", adapter_family: "codex_app_server",
  adapter_version: "2.0.0", source_schema_family: "codex_thread", source_schema_version: "1",
  content_schema_family: "codex_thread_items", content_schema_version: "1", reason_code: "exact_match",
  checked_at: "2040-01-01T00:00:00Z", update_support: "unsupported", update_target: null,
};

export function ModelJobStatusFixture({ windowMode }: { windowMode: boolean }) {
  return windowMode ? <ModelEnsembleOverlay transport={transport} /> : <ModelEnsemblePanel
    projectId={SYNTHETIC_QUALITY_PROJECT_ID} sessionId={SYNTHETIC_QUALITY_SESSION_ID}
    category="prompt-quality" transport={transport} providerCompatibility={compatible}
    analysisCapability={{ available: true, reason_code: "available", data_tier: "redacted_content",
      content_persistence: false, network_inference: false, raw_transcripts: false }}
  />;
}
