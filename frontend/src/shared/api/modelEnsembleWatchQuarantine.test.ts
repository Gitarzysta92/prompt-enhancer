import { describe, expect, it } from "vitest";
import { parseModelEnsembleWatch, ModelEnsembleWatchPayloadError } from "./modelEnsembleWatchContract";

function watch() {
  return {
    watch_id: "a".repeat(64), provider: "codex", project_id: "b".repeat(64), session_id: "c".repeat(64),
    max_messages: 100, state: "failed", generation: 1, progress_completed: 0, progress_total: 10,
    has_result: false, last_error_code: "model_ensemble_cleanup_unconfirmed",
    next_check_at: "2040-01-01T00:01:00Z", updated_at: "2040-01-01T00:00:00Z",
    serial_model_execution: true, process_isolated_model_release: true, cuda_resource_retry_on_cpu: true,
    content_persisted: false, calibrated_as_truth: false,
  };
}

describe("authoritative model job quarantine", () => {
  it.each(["codex", "claude_code"])("accepts a minimized %s watch with authoritative quarantine", (provider) => {
    const payload = { ...watch(), provider, quarantined: true, quarantine_reason_code: "model_ensemble_cleanup_unconfirmed" };
    expect(parseModelEnsembleWatch(payload)).toEqual(payload);
  });

  it("leaves absent legacy quarantine metadata unknown", () => {
    const parsed = parseModelEnsembleWatch(watch());
    expect(parsed.quarantined).toBeUndefined();
    expect(parsed.quarantine_reason_code).toBeUndefined();
  });

  it.each([
    { quarantined: true },
    { quarantine_reason_code: "example_failure" },
    { quarantined: true, quarantine_reason_code: null },
    { quarantined: false, quarantine_reason_code: "example_failure" },
    { quarantined: null, quarantine_reason_code: "example_failure" },
    { quarantined: "true", quarantine_reason_code: "example_failure" },
    { quarantined: true, quarantine_reason_code: "SYNTHETIC_PRIVATE_CANARY" },
    { quarantined: true, quarantine_reason_code: "example_failure", state: "running" },
  ])("rejects incomplete or contradictory quarantine metadata %#", (changes) => {
    expect(() => parseModelEnsembleWatch({ ...watch(), ...changes })).toThrow(ModelEnsembleWatchPayloadError);
  });

  it.each([false, null])("accepts explicit non-quarantined or unknown state: %s", (quarantined) => {
    expect(parseModelEnsembleWatch({ ...watch(), quarantined, quarantine_reason_code: null }).quarantined).toBe(quarantined);
  });
});
