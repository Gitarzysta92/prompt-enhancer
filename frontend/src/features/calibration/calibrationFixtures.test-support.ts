import type { CalibrationReview } from "../../shared/api/contracts";

/** Fictional evidence and receipt only; never reads a local provider. */
export function exampleCalibrationReview(sessionId = "a".repeat(64), overrides: Partial<CalibrationReview> = {}): CalibrationReview {
  return {
    contract_version: "calibration-case.v1", case_version: "calibration-case.v1",
    window_schema_version: "model-judge-window.v2", session_id: sessionId,
    provider: sessionId === "b".repeat(64) ? "codex" : "claude_code",
    case_fingerprint: "d".repeat(64), window_fingerprint: "e".repeat(64), review_id: "f".repeat(32),
    expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    records: [{ sequence: 0, role: "user", content: "Review the example module and report the checks performed." }],
    earlier_records_omitted: false, persisted: false, local_only: true,
    note: "Fictional bounded evidence for reviewed-case tests.", ...overrides,
  };
}
