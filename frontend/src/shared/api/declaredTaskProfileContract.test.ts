import { describe, expect, it } from "vitest";
import {
  DeclaredTaskProfilePayloadError,
  parseDeclaredTaskProfileCurrent,
  parseDeclaredTaskProfileOutcome,
} from "./declaredTaskProfileContract";

const SESSION_ID = "a".repeat(64);

function profileFixture(revision = 2) {
  return {
    profile_id: "b".repeat(64),
    provider: "codex",
    session_id: SESSION_ID,
    revision,
    previous_profile_id: revision === 1 ? null : "c".repeat(64),
    constraint_kinds: ["cost", "privacy"],
    expected_outcome_count: 3,
    deliverable_slots: ["artifact", "format"],
    profile_fingerprint: "d".repeat(64),
    confirmed_at: "2040-01-02T10:00:00Z",
    confirmation_authority: "authenticated_local_user",
    schema_version: "declared-task-profile-v1",
    policy_version: "authenticated-local-user-v1",
    local_only: true,
    content_persisted: false,
  };
}

describe("reviewed task profile contract", () => {
  it("accepts an absent profile and a complete immutable revision", () => {
    expect(parseDeclaredTaskProfileCurrent({ session_id: SESSION_ID, profile: null, confirmation_available: false }, SESSION_ID)).toEqual({
      session_id: SESSION_ID,
      profile: null,
      confirmation_available: false,
    });
    const profile = profileFixture();
    expect(parseDeclaredTaskProfileCurrent({ session_id: SESSION_ID, profile, confirmation_available: true }, SESSION_ID)).toEqual({
      session_id: SESSION_ID,
      profile,
      confirmation_available: true,
    });
    expect(parseDeclaredTaskProfileOutcome({ profile, applied: true }, SESSION_ID)).toEqual({
      profile,
      applied: true,
    });
  });

  it("preserves each unconfigured family as null", () => {
    const profile = {
      ...profileFixture(1),
      constraint_kinds: null,
      expected_outcome_count: null,
      deliverable_slots: null,
    };
    expect(parseDeclaredTaskProfileCurrent({ session_id: SESSION_ID, profile, confirmation_available: true }, SESSION_ID).profile).toEqual(profile);
  });

  it.each([
    ["extra profile field", () => ({ ...profileFixture(), note: "forbidden" })],
    ["empty configured constraints", () => ({ ...profileFixture(), constraint_kinds: [] })],
    ["duplicate configured constraints", () => ({ ...profileFixture(), constraint_kinds: ["cost", "cost"] })],
    ["unsorted configured constraints", () => ({ ...profileFixture(), constraint_kinds: ["privacy", "cost"] })],
    ["empty configured deliverables", () => ({ ...profileFixture(), deliverable_slots: [] })],
    ["invalid outcome count", () => ({ ...profileFixture(), expected_outcome_count: 0 })],
    ["invalid revision chain", () => ({ ...profileFixture(1), previous_profile_id: "c".repeat(64) })],
    ["foreign session", () => ({ ...profileFixture(), session_id: "e".repeat(64) })],
    ["privacy invariant", () => ({ ...profileFixture(), content_persisted: true })],
  ])("rejects %s", (_label, change) => {
    expect(() => parseDeclaredTaskProfileCurrent(
      { session_id: SESSION_ID, profile: change(), confirmation_available: true },
      SESSION_ID,
    )).toThrow(DeclaredTaskProfilePayloadError);
  });

  it("rejects envelope expansion and malformed outcome replay facts", () => {
    expect(() => parseDeclaredTaskProfileCurrent(
      { session_id: SESSION_ID, profile: null, confirmation_available: false, raw_text: "forbidden" },
      SESSION_ID,
    )).toThrow(DeclaredTaskProfilePayloadError);
    expect(() => parseDeclaredTaskProfileOutcome(
      { profile: profileFixture(), applied: "yes" },
      SESSION_ID,
    )).toThrow(DeclaredTaskProfilePayloadError);
  });

  it("rejects a missing or non-boolean user-presence capability", () => {
    expect(() => parseDeclaredTaskProfileCurrent(
      { session_id: SESSION_ID, profile: null },
      SESSION_ID,
    )).toThrow(DeclaredTaskProfilePayloadError);
    expect(() => parseDeclaredTaskProfileCurrent(
      { session_id: SESSION_ID, profile: null, confirmation_available: "yes" },
      SESSION_ID,
    )).toThrow(DeclaredTaskProfilePayloadError);
  });
});
