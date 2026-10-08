import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SOCIAL_SYNTHETIC_PRINCIPAL_ID,
  createSyntheticSocialSnapshot,
} from "../../../shared/api/socialHub";
import {
  DIRECT_TRANSFER_PROTOCOL_VERSION,
  DirectTransferProtocolError,
  SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
  type DirectTransferStatus,
  type DirectTransferVerificationReceipt,
} from "./directTransferProtocol";
import * as directTransferSession from "./directTransferSession";
import type { SyntheticDirectTransferSessionPort } from "./directTransferSession";
import { DirectTransferPrototypePanel, syntheticDirectTransferPrototypeIsAvailable } from "./DirectTransferPrototypePanel";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

function transferStatus(
  state: DirectTransferStatus["state"],
  overrides: Partial<DirectTransferStatus> = {},
): DirectTransferStatus {
  return {
    protocolVersion: DIRECT_TRANSFER_PROTOCOL_VERSION,
    transferId: "a".repeat(64),
    state,
    byteSize: 1024,
    bytesSent: 0,
    bytesReceived: 0,
    recipientConsented: false,
    ownerApproved: false,
    failureReason: null,
    reachabilityHint: null,
    relayUsed: false,
    cloudBytesUsed: false,
    persistedPayload: false,
    remoteRecallGuaranteed: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("synthetic WebRTC prototype composition gate", () => {
  it("requires development, the exact opt-in, the registered synthetic origin, and fictional principal", () => {
    const snapshot = createSyntheticSocialSnapshot();
    expect(syntheticDirectTransferPrototypeIsAvailable({
      snapshot,
      development: true,
      buildOptIn: SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
    })).toBe(true);
    expect(syntheticDirectTransferPrototypeIsAvailable({
      snapshot,
      development: false,
      buildOptIn: SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
    })).toBe(false);
    expect(syntheticDirectTransferPrototypeIsAvailable({
      snapshot,
      development: true,
      buildOptIn: "enabled",
    })).toBe(false);
    expect(syntheticDirectTransferPrototypeIsAvailable({
      snapshot: { ...snapshot, origin: "local_loopback" },
      development: true,
      buildOptIn: SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
    })).toBe(false);
    expect(syntheticDirectTransferPrototypeIsAvailable({
      snapshot: { ...snapshot, fictional: false },
      development: true,
      buildOptIn: SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
    })).toBe(false);
    expect(syntheticDirectTransferPrototypeIsAvailable({
      snapshot: { ...snapshot, principal_id: "0".repeat(64) },
      development: true,
      buildOptIn: SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
    })).toBe(false);
    expect(snapshot.principal_id).toBe(SOCIAL_SYNTHETIC_PRINCIPAL_ID);
  });

  it("closes a terminal result, releases the session, and permits another run", async () => {
    vi.stubEnv("VITE_SOCIAL_DIRECT_FILE_PROTOTYPE", SYNTHETIC_DIRECT_TRANSFER_OPT_IN);
    render(<DirectTransferPrototypePanel snapshot={createSyntheticSocialSnapshot()} />);

    fireEvent.click(screen.getByRole("checkbox", { name: /generated synthetic bytes only/ }));
    fireEvent.click(screen.getByRole("button", { name: "Prepare synthetic transfer" }));
    await screen.findByText("Awaiting explicit synthetic-recipient consent");
    fireEvent.click(screen.getByRole("button", { name: "Revoke before completion" }));
    await screen.findByText(/Revoked · future bytes stopped/);

    fireEvent.click(screen.getByRole("button", { name: "Close result" }));
    expect(screen.queryByText(/Revoked · future bytes stopped/)).toBeNull();
    expect(screen.getByRole("checkbox", { name: /generated synthetic bytes only/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Prepare synthetic transfer" })).toBeEnabled();
  });

  it("ignores a rejected start after its terminal result has been closed", async () => {
    vi.stubEnv("VITE_SOCIAL_DIRECT_FILE_PROTOTYPE", SYNTHETIC_DIRECT_TRANSFER_OPT_IN);
    const pending = deferred<DirectTransferVerificationReceipt>();
    let current = transferStatus("awaiting_recipient_consent");
    let listener: ((status: DirectTransferStatus) => void) | null = null;
    const emit = (next: DirectTransferStatus) => {
      current = next;
      listener?.(next);
    };
    const unsubscribe = vi.fn();
    const close = vi.fn();
    const session = {
      manifest: {},
      getStatus: () => current,
      getReceipt: () => null,
      subscribe(next: (status: DirectTransferStatus) => void) {
        listener = next;
        next(current);
        return unsubscribe;
      },
      consent() {
        emit(transferStatus("awaiting_owner_approval", { recipientConsented: true }));
      },
      approve() {
        emit(transferStatus("negotiating_direct", { recipientConsented: true, ownerApproved: true }));
      },
      start() {
        emit(transferStatus("failed", {
          recipientConsented: true,
          ownerApproved: true,
          failureReason: "unreachable_no_relay",
          reachabilityHint: "symmetric_nat_or_cgnat_or_firewall_possible",
        }));
        return pending.promise;
      },
      pause: vi.fn(),
      resume: vi.fn(),
      revoke: vi.fn(() => false),
      close,
    } as unknown as SyntheticDirectTransferSessionPort;
    vi.spyOn(directTransferSession, "createSyntheticDirectTransferSession").mockResolvedValueOnce(session);

    render(<DirectTransferPrototypePanel snapshot={createSyntheticSocialSnapshot()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /generated synthetic bytes only/ }));
    fireEvent.click(screen.getByRole("button", { name: "Prepare synthetic transfer" }));
    fireEvent.click(await screen.findByRole("button", { name: "Grant synthetic recipient consent" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve this transfer as synthetic owner" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start direct two-peer transfer" }));
    fireEvent.click(await screen.findByRole("button", { name: "Close result" }));

    await act(async () => {
      pending.reject(new DirectTransferProtocolError("unreachable_no_relay"));
      await pending.promise.catch(() => undefined);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Prepare synthetic transfer" })).toBeEnabled();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalledTimes(1);
  });
});
