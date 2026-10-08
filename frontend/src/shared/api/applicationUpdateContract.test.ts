import { describe, expect, it } from "vitest";
import type { ApplicationUpdateStatus } from "./contracts";
import {
  ApplicationUpdatePayloadError,
  parseApplicationUpdateStatus,
} from "./applicationUpdateContract";

const CURRENT: ApplicationUpdateStatus = {
  contract_version: "application-update-status.v3",
  instance_id: "a".repeat(32),
  revision: 1,
  contains_private_data: false,
  installed_version: "1.2.3",
  channel: "stable",
  state: "current",
  available_version: null,
  artifact_size_bytes: null,
  downloaded_bytes: null,
  last_checked_at: "2040-01-02T03:04:05Z",
  reason_code: null,
  verification_code: null,
  can_check: true,
  can_stage: false,
  can_cancel: false,
  can_retry: false,
  can_apply: false,
  can_verify: false,
  package_review: { state: "not_staged", reason_code: null, checked_at: null },
};

describe("parseApplicationUpdateStatus", () => {
  it("accepts one exact content-free status", () => {
    expect(parseApplicationUpdateStatus(structuredClone(CURRENT))).toEqual(CURRENT);
  });

  it.each([
    ["unknown field", { ...CURRENT, source_url: "https://example.invalid" }],
    ["private marker", { ...CURRENT, contains_private_data: true }],
    ["boolean byte count", { ...CURRENT, artifact_size_bytes: true }],
    ["bad timestamp", { ...CURRENT, last_checked_at: "tomorrow" }],
    ["invented action", { ...CURRENT, can_apply: true }],
    ["bad instance id", { ...CURRENT, instance_id: "not-an-instance" }],
    ["bad revision", { ...CURRENT, revision: -1 }],
    ["invented release", { ...CURRENT, available_version: "2.0.0" }],
    ["array channel", { ...CURRENT, channel: ["stable"] }],
    ["array state", { ...CURRENT, state: ["current"] }],
    ["array reason", { ...CURRENT, reason_code: ["release_feed_unavailable"] }],
    ["array verification", { ...CURRENT, verification_code: ["bad_signature"] }],
  ])("rejects %s", (_label, value) => {
    expect(() => parseApplicationUpdateStatus(value)).toThrow(ApplicationUpdatePayloadError);
  });

  it("rejects progress beyond the signed artifact size", () => {
    expect(() => parseApplicationUpdateStatus({
      ...CURRENT,
      state: "staging",
      available_version: "2.0.0",
      artifact_size_bytes: 10,
      downloaded_bytes: 11,
      can_check: false,
      can_cancel: true,
      can_retry: false,
    })).toThrow(ApplicationUpdatePayloadError);
  });

  it("accepts the content-free in-flight state", () => {
    expect(parseApplicationUpdateStatus({
      ...CURRENT,
      state: "checking",
      last_checked_at: null,
      can_check: false,
    })).toMatchObject({ state: "checking", verification_code: null });
  });

  it("accepts staging while cancellation cleanup remains authoritative", () => {
    expect(parseApplicationUpdateStatus({
      ...CURRENT,
      state: "staging",
      available_version: "2.0.0",
      artifact_size_bytes: 10,
      downloaded_bytes: 10,
      can_check: false,
      can_cancel: false,
    })).toMatchObject({ state: "staging", can_cancel: false });
  });

  it("accepts staged bytes without a package verifier and verifies the v3 review shape", () => {
    const staged = {
      ...CURRENT,
      state: "staged" as const,
      available_version: "2.0.0",
      artifact_size_bytes: 10,
      downloaded_bytes: 10,
      can_verify: false,
      package_review: { state: "not_configured" as const, reason_code: null, checked_at: null },
    };
    expect(parseApplicationUpdateStatus(staged)).toMatchObject({ state: "staged", can_verify: false });
    expect(parseApplicationUpdateStatus({
      ...staged,
      can_verify: true,
      package_review: { state: "verified", reason_code: null, checked_at: "2040-01-02T03:04:05Z" },
    })).toMatchObject({ package_review: { state: "verified" } });
  });

  it("keeps a verifying snapshot read-only and rejects forged review reasons", () => {
    expect(parseApplicationUpdateStatus({
      ...CURRENT,
      state: "verifying",
      available_version: "2.0.0",
      artifact_size_bytes: 10,
      downloaded_bytes: 10,
      package_review: { state: "checking", reason_code: null, checked_at: null },
      can_check: false,
    })).toMatchObject({ state: "verifying", can_apply: false });
    expect(() => parseApplicationUpdateStatus({
      ...CURRENT,
      state: "verifying",
      available_version: "2.0.0",
      artifact_size_bytes: 10,
      downloaded_bytes: 10,
      package_review: { state: "checking", reason_code: null, checked_at: null },
      can_check: false,
      reason_code: "release_feed_unavailable",
    })).toThrow(ApplicationUpdatePayloadError);
    expect(() => parseApplicationUpdateStatus({
      ...CURRENT,
      state: "staged",
      available_version: "2.0.0",
      artifact_size_bytes: 10,
      downloaded_bytes: 10,
      can_verify: true,
      package_review: { state: "rejected", reason_code: "private_reason", checked_at: "2040-01-02T03:04:05Z" },
    })).toThrow(ApplicationUpdatePayloadError);
  });

  it("requires a bounded verifier code only for a rejected manifest", () => {
    const failed = {
      ...CURRENT,
      state: "failed",
      reason_code: "manifest_rejected",
      verification_code: "bad_signature",
    };
    expect(parseApplicationUpdateStatus(failed)).toMatchObject(failed);
    expect(() => parseApplicationUpdateStatus({
      ...failed,
      reason_code: "release_feed_unavailable",
    })).toThrow(ApplicationUpdatePayloadError);
  });

  it("does not advertise retry after cleanup becomes uncertain", () => {
    expect(() => parseApplicationUpdateStatus({
      ...CURRENT,
      state: "failed",
      reason_code: "staging_cleanup_unconfirmed",
      can_check: true,
      can_retry: true,
    })).toThrow(ApplicationUpdatePayloadError);
  });

  it("does not advertise staging after a download verification failure", () => {
    expect(() => parseApplicationUpdateStatus({
      ...CURRENT,
      state: "failed",
      reason_code: "artifact_verification_failed",
      can_stage: true,
    })).toThrow(ApplicationUpdatePayloadError);
  });

  it("accepts retry only for recoverable release or download failures", () => {
    expect(parseApplicationUpdateStatus({
      ...CURRENT,
      state: "failed",
      reason_code: "release_feed_unavailable",
      can_retry: true,
    })).toMatchObject({ state: "failed", can_retry: true });
    for (const reason_code of ["artifact_verification_failed", "manifest_rejected"] as const) {
      expect(() => parseApplicationUpdateStatus({
        ...CURRENT,
        state: "failed",
        reason_code,
        can_retry: true,
        verification_code: reason_code === "manifest_rejected" ? "bad_signature" : null,
      })).toThrow(ApplicationUpdatePayloadError);
    }
  });
});
