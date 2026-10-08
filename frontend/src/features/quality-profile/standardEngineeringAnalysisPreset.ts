import type {
  SessionQualityAnalysisPreviewRequest,
  SessionQualityAnalysisRequest,
} from "../../shared/api/contracts";
import { METRIC_V2_PROVIDER_ADAPTER_GAP_KEYS } from "../../shared/api/metricOperabilityContract";
import { METRIC_V2_KEYS } from "../../shared/api/metricPublicationV2Contract";

/**
 * The default UI deliberately exposes one stable server-owned preset instead
 * of asking people to configure metric semantics before every run.
 */
export const COACHING_ANALYSIS_PRESET = Object.freeze({
  key: "coaching_profile_v1" as const,
  label: "Coaching profile",
  version: 1,
  checkCount: METRIC_V2_KEYS.length,
  supportedMeasurementPathCount: METRIC_V2_KEYS.length - METRIC_V2_PROVIDER_ADAPTER_GAP_KEYS.length,
  sourceEvidenceGapKeys: METRIC_V2_PROVIDER_ADAPTER_GAP_KEYS,
  maxMessages: 100,
  maxCharacters: 100_000,
});

export const COACHING_ANALYSIS_REQUEST = Object.freeze({
  preset_id: COACHING_ANALYSIS_PRESET.key,
  confirmation: "analyze_selected_redacted_text" as const,
}) satisfies Readonly<SessionQualityAnalysisRequest>;

export const COACHING_ANALYSIS_PREVIEW_REQUEST = Object.freeze({
  preset_id: COACHING_ANALYSIS_PRESET.key,
}) satisfies Readonly<SessionQualityAnalysisPreviewRequest>;
