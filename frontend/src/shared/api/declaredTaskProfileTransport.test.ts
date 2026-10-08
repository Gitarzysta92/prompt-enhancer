import { describe, expect, it, vi } from "vitest";
import { createHttpTransport } from "./httpTransport";

const SESSION_ID = "a".repeat(64);
const AUTH = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
  user_presence_confirmation_available: true,
  user_presence_confirmation_mode: "native_bridge_bound_token",
} as const;
const USER_PRESENCE_TOKEN = "u".repeat(48);

async function sha256(value: string): Promise<string> {
  const digest = new Uint8Array(
    await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
  );
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function json(body: unknown, privateResponse = false): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      ...(privateResponse ? { "Cache-Control": "no-store, private", Pragma: "no-cache" } : {}),
    },
  });
}

function profile(revision = 1) {
  return {
    profile_id: "b".repeat(64),
    provider: "codex",
    session_id: SESSION_ID,
    revision,
    previous_profile_id: revision === 1 ? null : "c".repeat(64),
    constraint_kinds: ["privacy"],
    expected_outcome_count: 2,
    deliverable_slots: ["artifact"],
    profile_fingerprint: "d".repeat(64),
    confirmed_at: "2040-01-02T10:00:00Z",
    confirmation_authority: "authenticated_local_user",
    schema_version: "declared-task-profile-v1",
    policy_version: "authenticated-local-user-v1",
    local_only: true,
    content_persisted: false,
  };
}

describe("reviewed task profile HTTP transport", () => {
  it("uses same-origin browser auth, private reads, CSRF, idempotency, and the exact command", async () => {
    const current = profile();
    const next = { ...profile(2), previous_profile_id: current.profile_id };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(AUTH))
      .mockResolvedValueOnce(json({ session_id: SESSION_ID, profile: current, confirmation_available: true }, true))
      .mockResolvedValueOnce(json({ profile: next, applied: true }, true));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.getDeclaredTaskProfile!(SESSION_ID)).resolves.toEqual({
      session_id: SESSION_ID,
      profile: current,
      confirmation_available: true,
    });
    const command = {
      expected_revision: 1,
      constraint_kinds: ["privacy"] as const,
      expected_outcome_count: 2,
      deliverable_slots: ["artifact"] as const,
      confirmation: "save_reviewed_declared_task_profile" as const,
    };
    await expect(transport.saveDeclaredTaskProfile!(
      SESSION_ID,
      command,
      "dashboard-declared-task-profile-example",
    )).resolves.toEqual({ profile: next, applied: true });

    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/sessions/${SESSION_ID}/declared-task-profile`);
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: "GET",
      cache: "no-store",
      credentials: "include",
    }));
    expect(fetchMock.mock.calls[2][0]).toBe(`/v1/sessions/${SESSION_ID}/declared-task-profile`);
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
      method: "POST",
      cache: "no-store",
      credentials: "include",
      body: JSON.stringify(command),
      headers: expect.objectContaining({
        "Idempotency-Key": "dashboard-declared-task-profile-example",
        "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
        "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
      }),
    }));
    expect(approveUserPresence).toHaveBeenCalledOnce();
    expect(approveUserPresence).toHaveBeenCalledWith({
      method: "POST",
      path: `/v1/sessions/${SESSION_ID}/declared-task-profile`,
      bodySha256: await sha256(JSON.stringify(command)),
    });
  });

  it("rejects a private response that omits no-store protection", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(AUTH))
      .mockResolvedValueOnce(json({ session_id: SESSION_ID, profile: null, confirmation_available: false }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getDeclaredTaskProfile!(SESSION_ID)).rejects.toMatchObject({ status: 200 });
  });
});
