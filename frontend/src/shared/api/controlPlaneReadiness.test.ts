import { describe, expect, it } from "vitest";
import {
  CONTROL_PLANE_READINESS_GAPS,
  ControlPlaneReadinessPayloadError,
  parseControlPlaneReadiness,
} from "./controlPlaneReadiness";

function validPayload(): Record<string, unknown> {
  return {
    contract_version: "control-plane-v2",
    delivery_guarantee: "at_least_once_with_monotonic_ack",
    gaps: [...CONTROL_PLANE_READINESS_GAPS].sort(),
    production_ready: false,
    profile: "development",
    remote_listening_enabled: false,
  };
}

describe("control-plane readiness parser", () => {
  it("accepts the exact closed development contract", () => {
    expect(parseControlPlaneReadiness(validPayload())).toEqual(validPayload());
  });

  it.each([
    ["production claim", { production_ready: true }],
    ["remote listener", { remote_listening_enabled: true }],
    ["production profile", { profile: "production" }],
    ["wrong version", { contract_version: "control-plane-v3" }],
    ["empty gaps", { gaps: [] }],
    ["unknown gap", { gaps: ["unknown_gap"] }],
    ["duplicated gaps", { gaps: [CONTROL_PLANE_READINESS_GAPS[0], CONTROL_PLANE_READINESS_GAPS[0]] }],
    ["unsorted gaps", { gaps: ["billing_not_implemented", "backup_and_replica_erasure_not_implemented"] }],
    ["extra field", { unexpected: "value" }],
  ])("rejects %s", (_label, patch) => {
    expect(() => parseControlPlaneReadiness({ ...validPayload(), ...patch })).toThrow(
      ControlPlaneReadinessPayloadError,
    );
  });
});
