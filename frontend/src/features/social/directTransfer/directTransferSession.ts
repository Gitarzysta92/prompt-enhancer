/** Browser-standard WebRTC data-channel runtime for generated fixture bytes only. */

import {
  BUFFERED_AMOUNT_HIGH_WATER,
  BUFFERED_AMOUNT_LOW_WATER,
  DIRECT_TRANSFER_PROTOCOL_VERSION,
  FRAME_PAYLOAD_BYTES,
  MAX_BACKPRESSURE_MILLISECONDS,
  MAX_SIGNALING_MILLISECONDS,
  MAX_SYNTHETIC_FILE_BYTES,
  DirectTransferProtocolError,
  buildDirectTransferManifest,
  requireSyntheticGrant,
  verifyReceivedBytes,
  type DirectTransferFailureReason,
  type DirectTransferManifest,
  type DirectTransferState,
  type DirectTransferStatus,
  type DirectTransferVerificationReceipt,
  type SyntheticDirectTransferGrant,
} from "./directTransferProtocol";

const CHANNEL_LABEL = "prompt-enhancer-direct-file-v1";
const FRAME_MAGIC = 0x50454446;
const FRAME_VERSION = 1;
const FRAME_TYPE_DATA = 1;
const FRAME_TYPE_COMPLETE = 2;
const FRAME_HEADER_BYTES = 16;
const MAX_TRANSFER_MILLISECONDS = 60_000;

export interface SyntheticByteSource {
  readonly kind: "generated_synthetic_bytes";
  readonly fictional: true;
  readonly byteLength: number;
}

const sourceRegistry = new WeakMap<object, Uint8Array>();

export function createSyntheticByteSource(byteLength: number, seed = 0x5eed1234): SyntheticByteSource {
  if (!Number.isSafeInteger(byteLength) || byteLength < 1 || byteLength > MAX_SYNTHETIC_FILE_BYTES) {
    throw new RangeError("synthetic byte source is outside the prototype bound");
  }
  if (!Number.isSafeInteger(seed)) throw new TypeError("synthetic seed must be an integer");
  let state = seed >>> 0;
  const bytes = new Uint8Array(byteLength);
  for (let index = 0; index < bytes.length; index += 1) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    bytes[index] = state & 0xff;
  }
  const source = Object.freeze({
    kind: "generated_synthetic_bytes" as const,
    fictional: true as const,
    byteLength,
  });
  sourceRegistry.set(source, bytes);
  return source;
}

/** One-shot ownership transfer. No exported function returns the registered bytes. */
function consumeSyntheticByteSource(source: SyntheticByteSource): Uint8Array {
  const bytes = sourceRegistry.get(source);
  if (bytes === undefined || bytes.byteLength !== source.byteLength) {
    throw new DirectTransferProtocolError("authorization_unavailable");
  }
  sourceRegistry.delete(source);
  return bytes;
}

type SignalKind = "offer" | "answer";

/**
 * Public signaling is content-free and intentionally non-portable. The actual
 * browser description exists only in a module-private WeakMap until the other
 * in-process synthetic peer consumes the one-shot object capability. A cloned
 * or serialized copy is not registered and therefore fails closed.
 */
export interface EphemeralDirectSignalEnvelope {
  readonly protocolVersion: typeof DIRECT_TRANSFER_PROTOCOL_VERSION;
  readonly kind: SignalKind;
  readonly transferId: string;
  readonly fictional: true;
  readonly persisted: false;
  readonly portable: false;
}

interface PrivateSignal {
  readonly kind: SignalKind;
  readonly transferId: string;
  readonly description: RTCSessionDescriptionInit;
}

const privateSignals = new WeakMap<object, PrivateSignal>();

function wrapSignal(
  transferId: string,
  kind: SignalKind,
  description: RTCSessionDescriptionInit,
): EphemeralDirectSignalEnvelope {
  const envelope = Object.freeze({
    protocolVersion: DIRECT_TRANSFER_PROTOCOL_VERSION,
    kind,
    transferId,
    fictional: true as const,
    persisted: false as const,
    portable: false as const,
  });
  privateSignals.set(envelope, { kind, transferId, description });
  return envelope;
}

function consumeSignal(
  envelope: EphemeralDirectSignalEnvelope,
  transferId: string,
  kind: SignalKind,
): RTCSessionDescriptionInit {
  const signal = privateSignals.get(envelope);
  privateSignals.delete(envelope);
  if (
    signal === undefined
    || signal.transferId !== transferId
    || signal.kind !== kind
    || envelope.protocolVersion !== DIRECT_TRANSFER_PROTOCOL_VERSION
    || envelope.transferId !== transferId
    || envelope.kind !== kind
  ) {
    throw new DirectTransferProtocolError("protocol_invalid");
  }
  return signal.description;
}

interface DecodedFrame {
  readonly type: typeof FRAME_TYPE_DATA | typeof FRAME_TYPE_COMPLETE;
  readonly offset: number;
  readonly payload: Uint8Array;
}

function encodeFrame(type: DecodedFrame["type"], offset: number, payload: Uint8Array): ArrayBuffer {
  if (
    !Number.isSafeInteger(offset)
    || offset < 0
    || payload.byteLength > FRAME_PAYLOAD_BYTES
    || (type === FRAME_TYPE_COMPLETE && payload.byteLength !== 0)
  ) {
    throw new DirectTransferProtocolError("protocol_invalid");
  }
  const frame = new Uint8Array(FRAME_HEADER_BYTES + payload.byteLength);
  const view = new DataView(frame.buffer);
  view.setUint32(0, FRAME_MAGIC, false);
  view.setUint8(4, FRAME_VERSION);
  view.setUint8(5, type);
  view.setUint16(6, 0, false);
  view.setUint32(8, offset, false);
  view.setUint32(12, payload.byteLength, false);
  frame.set(payload, FRAME_HEADER_BYTES);
  return frame.buffer;
}

function decodeFrame(buffer: ArrayBuffer): DecodedFrame {
  if (buffer.byteLength < FRAME_HEADER_BYTES || buffer.byteLength > FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES) {
    throw new DirectTransferProtocolError("protocol_invalid");
  }
  const view = new DataView(buffer);
  const type = view.getUint8(5);
  const payloadLength = view.getUint32(12, false);
  if (
    view.getUint32(0, false) !== FRAME_MAGIC
    || view.getUint8(4) !== FRAME_VERSION
    || view.getUint16(6, false) !== 0
    || (type !== FRAME_TYPE_DATA && type !== FRAME_TYPE_COMPLETE)
    || payloadLength !== buffer.byteLength - FRAME_HEADER_BYTES
    || (type === FRAME_TYPE_DATA && payloadLength < 1)
    || (type === FRAME_TYPE_COMPLETE && payloadLength !== 0)
  ) {
    throw new DirectTransferProtocolError("protocol_invalid");
  }
  return {
    type,
    offset: view.getUint32(8, false),
    payload: new Uint8Array(buffer.slice(FRAME_HEADER_BYTES)),
  };
}

function timeout<T>(
  milliseconds: number,
  reason: DirectTransferFailureReason,
  operation: (resolve: (value: T) => void, reject: (error: unknown) => void) => () => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    let operationCleanup: () => void = () => {};
    let cleanup: () => void = () => {};
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      cleanup();
      callback();
    };
    const timer = setTimeout(() => finish(() => reject(new DirectTransferProtocolError(reason))), milliseconds);
    const aborted = () => finish(() => reject(new DirectTransferProtocolError(reason)));
    operationCleanup = operation(
      (value) => finish(() => resolve(value)),
      (error) => finish(() => reject(error)),
    );
    cleanup = () => {
      operationCleanup();
      signal?.removeEventListener("abort", aborted);
    };
    if (signal?.aborted === true) aborted();
    else signal?.addEventListener("abort", aborted, { once: true });
    if (settled) cleanup();
  });
}

function waitForIceGathering(peer: RTCPeerConnection, signal: AbortSignal): Promise<void> {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return timeout<void>(MAX_SIGNALING_MILLISECONDS, "unreachable_no_relay", (resolve) => {
    const changed = () => {
      if (peer.iceGatheringState === "complete") resolve();
    };
    peer.addEventListener("icegatheringstatechange", changed);
    return () => peer.removeEventListener("icegatheringstatechange", changed);
  }, signal);
}

function localDescriptionWithoutRelay(
  peer: RTCPeerConnection,
  kind: SignalKind,
): RTCSessionDescriptionInit {
  const description = peer.localDescription;
  if (description === null || description.type !== kind || /\btyp\s+relay\b/iu.test(description.sdp)) {
    throw new DirectTransferProtocolError("relay_candidate_rejected");
  }
  return { type: description.type, sdp: description.sdp };
}

function waitForRecipientChannel(peer: RTCPeerConnection, signal: AbortSignal): Promise<RTCDataChannel> {
  return timeout<RTCDataChannel>(MAX_SIGNALING_MILLISECONDS, "unreachable_no_relay", (resolve, reject) => {
    const received = (event: RTCDataChannelEvent) => {
      if (
        event.channel.label !== CHANNEL_LABEL
        || event.channel.protocol !== DIRECT_TRANSFER_PROTOCOL_VERSION
        || event.channel.ordered !== true
        || event.channel.maxPacketLifeTime !== null
        || event.channel.maxRetransmits !== null
      ) {
        event.channel.close();
        reject(new DirectTransferProtocolError("protocol_invalid"));
        return;
      }
      resolve(event.channel);
    };
    peer.addEventListener("datachannel", received);
    return () => peer.removeEventListener("datachannel", received);
  }, signal);
}

function waitForOpen(
  channel: RTCDataChannel,
  peers: readonly RTCPeerConnection[],
  signal: AbortSignal,
): Promise<void> {
  if (channel.readyState === "open") return Promise.resolve();
  return timeout<void>(MAX_SIGNALING_MILLISECONDS, "unreachable_no_relay", (resolve, reject) => {
    const opened = () => resolve();
    const closed = () => reject(new DirectTransferProtocolError("unreachable_no_relay"));
    const failed = () => {
      if (peers.some((peer) => peer.connectionState === "failed" || peer.iceConnectionState === "failed")) {
        reject(new DirectTransferProtocolError("unreachable_no_relay"));
      }
    };
    channel.addEventListener("open", opened);
    channel.addEventListener("close", closed);
    channel.addEventListener("error", closed);
    for (const peer of peers) {
      peer.addEventListener("connectionstatechange", failed);
      peer.addEventListener("iceconnectionstatechange", failed);
    }
    failed();
    return () => {
      channel.removeEventListener("open", opened);
      channel.removeEventListener("close", closed);
      channel.removeEventListener("error", closed);
      for (const peer of peers) {
        peer.removeEventListener("connectionstatechange", failed);
        peer.removeEventListener("iceconnectionstatechange", failed);
      }
    };
  }, signal);
}

function waitForBackpressure(channel: RTCDataChannel, signal: AbortSignal): Promise<void> {
  if (channel.bufferedAmount <= BUFFERED_AMOUNT_HIGH_WATER) return Promise.resolve();
  channel.bufferedAmountLowThreshold = BUFFERED_AMOUNT_LOW_WATER;
  return timeout<void>(MAX_BACKPRESSURE_MILLISECONDS, "backpressure_timeout", (resolve, reject) => {
    const low = () => resolve();
    const closed = () => reject(new DirectTransferProtocolError("channel_closed"));
    channel.addEventListener("bufferedamountlow", low);
    channel.addEventListener("close", closed);
    channel.addEventListener("error", closed);
    if (channel.bufferedAmount <= BUFFERED_AMOUNT_LOW_WATER) low();
    return () => {
      channel.removeEventListener("bufferedamountlow", low);
      channel.removeEventListener("close", closed);
      channel.removeEventListener("error", closed);
    };
  }, signal);
}

function nextTask(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function statusFrom(
  manifest: DirectTransferManifest,
  state: DirectTransferState,
  bytesSent: number,
  bytesReceived: number,
  recipientConsented: boolean,
  ownerApproved: boolean,
  failureReason: DirectTransferFailureReason | null,
): DirectTransferStatus {
  return Object.freeze({
    protocolVersion: DIRECT_TRANSFER_PROTOCOL_VERSION,
    transferId: manifest.transferId,
    state,
    byteSize: manifest.byteSize,
    bytesSent,
    bytesReceived,
    recipientConsented,
    ownerApproved,
    failureReason,
    reachabilityHint: failureReason === "unreachable_no_relay"
      ? "symmetric_nat_or_cgnat_or_firewall_possible" as const
      : null,
    relayUsed: false as const,
    cloudBytesUsed: false as const,
    persistedPayload: false as const,
    remoteRecallGuaranteed: false as const,
  });
}

export interface SyntheticDirectTransferSessionPort {
  readonly manifest: DirectTransferManifest;
  getStatus(): DirectTransferStatus;
  getReceipt(): DirectTransferVerificationReceipt | null;
  subscribe(listener: (status: DirectTransferStatus) => void): () => void;
  consent(grant: SyntheticDirectTransferGrant): void;
  approve(grant: SyntheticDirectTransferGrant): void;
  start(
    ownerGrant: SyntheticDirectTransferGrant,
    recipientGrant: SyntheticDirectTransferGrant,
  ): Promise<DirectTransferVerificationReceipt>;
  pause(grant: SyntheticDirectTransferGrant): void;
  resume(grant: SyntheticDirectTransferGrant): void;
  revoke(ownerGrant: SyntheticDirectTransferGrant): boolean;
  close(): void;
}

class SyntheticDirectTransferSession implements SyntheticDirectTransferSessionPort {
  readonly manifest: DirectTransferManifest;

  #source: Uint8Array;
  #received: Uint8Array;
  #state: DirectTransferState = "awaiting_recipient_consent";
  #bytesSent = 0;
  #bytesReceived = 0;
  #recipientConsented = false;
  #ownerApproved = false;
  #failureReason: DirectTransferFailureReason | null = null;
  #receipt: DirectTransferVerificationReceipt | null = null;
  #listeners = new Set<(status: DirectTransferStatus) => void>();
  #ownerPeer: RTCPeerConnection | null = null;
  #recipientPeer: RTCPeerConnection | null = null;
  #ownerChannel: RTCDataChannel | null = null;
  #recipientChannel: RTCDataChannel | null = null;
  #run: Promise<DirectTransferVerificationReceipt> | null = null;
  #resume: (() => void) | null = null;
  #abortController = new AbortController();

  constructor(manifest: DirectTransferManifest, source: Uint8Array) {
    this.manifest = manifest;
    this.#source = source;
    this.#received = new Uint8Array(manifest.byteSize);
  }

  getStatus(): DirectTransferStatus {
    return statusFrom(
      this.manifest,
      this.#state,
      this.#bytesSent,
      this.#bytesReceived,
      this.#recipientConsented,
      this.#ownerApproved,
      this.#failureReason,
    );
  }

  getReceipt(): DirectTransferVerificationReceipt | null {
    return this.#receipt;
  }

  subscribe(listener: (status: DirectTransferStatus) => void): () => void {
    this.#listeners.add(listener);
    listener(this.getStatus());
    return () => this.#listeners.delete(listener);
  }

  consent(grant: SyntheticDirectTransferGrant): void {
    const recipient = requireSyntheticGrant(grant, "recipient");
    this.#requireLive();
    if (
      this.#state !== "awaiting_recipient_consent"
      || recipient.principalId !== this.manifest.recipientPrincipalId
      || recipient.deviceId !== this.manifest.recipientDeviceId
    ) {
      throw new DirectTransferProtocolError("authorization_unavailable");
    }
    this.#recipientConsented = true;
    this.#state = "awaiting_owner_approval";
    this.#emit();
  }

  approve(grant: SyntheticDirectTransferGrant): void {
    const owner = requireSyntheticGrant(grant, "owner");
    this.#requireLive();
    if (!this.#recipientConsented) throw new DirectTransferProtocolError("consent_required");
    if (
      this.#state !== "awaiting_owner_approval"
      || owner.principalId !== this.manifest.ownerPrincipalId
      || owner.deviceId !== this.manifest.ownerDeviceId
    ) {
      throw new DirectTransferProtocolError("authorization_unavailable");
    }
    this.#ownerApproved = true;
    this.#state = "negotiating_direct";
    this.#emit();
  }

  start(
    ownerGrant: SyntheticDirectTransferGrant,
    recipientGrant: SyntheticDirectTransferGrant,
  ): Promise<DirectTransferVerificationReceipt> {
    const owner = requireSyntheticGrant(ownerGrant, "owner");
    const recipient = requireSyntheticGrant(recipientGrant, "recipient");
    this.#requireLive();
    if (!this.#recipientConsented) throw new DirectTransferProtocolError("consent_required");
    if (!this.#ownerApproved || this.#state !== "negotiating_direct") {
      throw new DirectTransferProtocolError("owner_approval_required");
    }
    if (
      owner.principalId !== this.manifest.ownerPrincipalId
      || owner.deviceId !== this.manifest.ownerDeviceId
      || recipient.principalId !== this.manifest.recipientPrincipalId
      || recipient.deviceId !== this.manifest.recipientDeviceId
    ) {
      throw new DirectTransferProtocolError("authorization_unavailable");
    }
    if (this.#run === null) this.#run = this.#runTransfer();
    return this.#run;
  }

  pause(grant: SyntheticDirectTransferGrant): void {
    requireSyntheticGrant(grant, "owner");
    this.#requireLive();
    if (this.#state !== "transferring") return;
    this.#state = "paused";
    this.#emit();
  }

  resume(grant: SyntheticDirectTransferGrant): void {
    requireSyntheticGrant(grant, "owner");
    this.#requireLive();
    if (this.#state !== "paused") return;
    this.#state = "transferring";
    const resume = this.#resume;
    this.#resume = null;
    resume?.();
    this.#emit();
  }

  revoke(ownerGrant: SyntheticDirectTransferGrant): boolean {
    const owner = requireSyntheticGrant(ownerGrant, "owner");
    if (
      owner.principalId !== this.manifest.ownerPrincipalId
      || owner.deviceId !== this.manifest.ownerDeviceId
      || this.#terminal()
    ) return false;
    this.#state = "revoked";
    this.#failureReason = null;
    this.#abortController.abort();
    const resume = this.#resume;
    this.#resume = null;
    resume?.();
    this.#closePeers();
    this.#eraseBytes();
    this.#emit();
    return true;
  }

  close(): void {
    if (!this.#terminal()) {
      this.#state = "failed";
      this.#failureReason = "channel_closed";
      this.#emit();
    }
    this.#abortController.abort();
    const resume = this.#resume;
    this.#resume = null;
    resume?.();
    this.#closePeers();
    this.#eraseBytes();
    this.#listeners.clear();
  }

  async #runTransfer(): Promise<DirectTransferVerificationReceipt> {
    try {
      const { ownerChannel, recipientChannel } = await this.#negotiate();
      this.#requireLive();
      this.#ownerChannel = ownerChannel;
      this.#recipientChannel = recipientChannel;
      this.#state = "direct_ready";
      this.#emit();
      // A subscriber may synchronously revoke while observing direct_ready.
      // Recheck before installing the receiver or advancing the state.
      this.#requireLive();
      const received = this.#receive(recipientChannel);
      this.#state = "transferring";
      this.#emit();
      this.#requireLive();
      const receiptPromise = timeout<DirectTransferVerificationReceipt>(
        MAX_TRANSFER_MILLISECONDS,
        "channel_closed",
        (resolve, reject) => {
          received.then(resolve, reject);
          return () => undefined;
        },
        this.#abortController.signal,
      );
      const [, receipt] = await Promise.all([this.#send(ownerChannel), receiptPromise]);
      this.#requireLive();
      this.#receipt = receipt;
      this.#state = "completed";
      this.#emit();
      this.#closePeers();
      this.#eraseBytes();
      return receipt;
    } catch (error) {
      if (this.#state === "revoked") {
        throw new DirectTransferProtocolError("revoked_before_completion");
      }
      if (this.#state === "expired") {
        throw new DirectTransferProtocolError("expired");
      }
      if (this.#state === "failed") {
        throw new DirectTransferProtocolError(this.#failureReason ?? "channel_closed");
      }
      const reason = error instanceof DirectTransferProtocolError ? error.reason : "protocol_invalid";
      this.#failureReason = reason;
      this.#state = "failed";
      this.#emit();
      this.#abortController.abort();
      this.#closePeers();
      this.#eraseBytes();
      throw error instanceof DirectTransferProtocolError ? error : new DirectTransferProtocolError(reason);
    }
  }

  async #negotiate(): Promise<{ ownerChannel: RTCDataChannel; recipientChannel: RTCDataChannel }> {
    if (typeof RTCPeerConnection !== "function") {
      throw new DirectTransferProtocolError("browser_webrtc_unavailable");
    }
    const configuration: RTCConfiguration = {
      iceServers: [],
      iceCandidatePoolSize: 0,
      bundlePolicy: "max-bundle",
      rtcpMuxPolicy: "require",
    };
    const owner = new RTCPeerConnection(configuration);
    const recipient = new RTCPeerConnection(configuration);
    this.#ownerPeer = owner;
    this.#recipientPeer = recipient;
    let relayCandidateSeen = false;
    let rejectRelayViolation: () => void = () => undefined;
    const relayViolation = new Promise<never>((_resolve, reject) => {
      rejectRelayViolation = () => reject(new DirectTransferProtocolError("relay_candidate_rejected"));
    });
    // The rejection is also raced by each negotiation step. This immediate
    // handler prevents an event between steps from becoming unhandled.
    void relayViolation.catch(() => undefined);
    const awaitDirect = <T>(operation: Promise<T>): Promise<T> => Promise.race([operation, relayViolation]);
    const rejectRelay = (event: RTCPeerConnectionIceEvent) => {
      if (event.candidate?.type === "relay" || /\btyp\s+relay\b/iu.test(event.candidate?.candidate ?? "")) {
        relayCandidateSeen = true;
        rejectRelayViolation();
        owner.close();
        recipient.close();
      }
    };
    owner.addEventListener("icecandidate", rejectRelay);
    recipient.addEventListener("icecandidate", rejectRelay);

    const recipientChannelPromise = waitForRecipientChannel(recipient, this.#abortController.signal);
    // This promise is awaited on the success path below. Attach a rejection
    // handler now so an earlier offer/setup failure cannot leave its later
    // bounded timeout unhandled.
    void recipientChannelPromise.catch(() => undefined);
    const ownerChannel = owner.createDataChannel(CHANNEL_LABEL, {
      ordered: true,
      protocol: DIRECT_TRANSFER_PROTOCOL_VERSION,
    });
    if (
      ownerChannel.protocol !== DIRECT_TRANSFER_PROTOCOL_VERSION
      || ownerChannel.ordered !== true
      || ownerChannel.maxPacketLifeTime !== null
      || ownerChannel.maxRetransmits !== null
    ) {
      throw new DirectTransferProtocolError("protocol_invalid");
    }
    ownerChannel.binaryType = "arraybuffer";
    await awaitDirect(owner.setLocalDescription(await awaitDirect(owner.createOffer())));
    await awaitDirect(waitForIceGathering(owner, this.#abortController.signal));
    if (relayCandidateSeen) throw new DirectTransferProtocolError("relay_candidate_rejected");
    const offer = wrapSignal(
      this.manifest.transferId,
      "offer",
      localDescriptionWithoutRelay(owner, "offer"),
    );
    await awaitDirect(recipient.setRemoteDescription(consumeSignal(offer, this.manifest.transferId, "offer")));
    await awaitDirect(recipient.setLocalDescription(await awaitDirect(recipient.createAnswer())));
    await awaitDirect(waitForIceGathering(recipient, this.#abortController.signal));
    if (relayCandidateSeen) throw new DirectTransferProtocolError("relay_candidate_rejected");
    const answer = wrapSignal(
      this.manifest.transferId,
      "answer",
      localDescriptionWithoutRelay(recipient, "answer"),
    );
    await awaitDirect(owner.setRemoteDescription(consumeSignal(answer, this.manifest.transferId, "answer")));
    const recipientChannel = await awaitDirect(recipientChannelPromise);
    recipientChannel.binaryType = "arraybuffer";
    await awaitDirect(Promise.all([
      waitForOpen(ownerChannel, [owner, recipient], this.#abortController.signal),
      waitForOpen(recipientChannel, [owner, recipient], this.#abortController.signal),
    ]));
    if (relayCandidateSeen) throw new DirectTransferProtocolError("relay_candidate_rejected");
    const negotiatedMessageSizes = [owner.sctp?.maxMessageSize ?? 0, recipient.sctp?.maxMessageSize ?? 0];
    if (negotiatedMessageSizes.some(
      (maxMessageSize) => maxMessageSize !== 0 && maxMessageSize < FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES,
    )) {
      throw new DirectTransferProtocolError("protocol_invalid");
    }
    return { ownerChannel, recipientChannel };
  }

  #receive(channel: RTCDataChannel): Promise<DirectTransferVerificationReceipt> {
    return new Promise((resolve, reject) => {
      let expectedOffset = 0;
      let verifying = false;
      let settled = false;
      let cleanup = () => undefined;
      const fail = (error: unknown) => {
        if (settled) return;
        settled = true;
        cleanup();
        if (channel.readyState !== "closed") channel.close();
        reject(error instanceof DirectTransferProtocolError ? error : new DirectTransferProtocolError("protocol_invalid"));
      };
      const closed = () => fail(new DirectTransferProtocolError(this.#stopReason()));
      const errored = () => fail(new DirectTransferProtocolError("channel_closed"));
      const aborted = () => fail(new DirectTransferProtocolError(this.#stopReason()));
      const message = (event: MessageEvent<unknown>) => {
        void (async () => {
          try {
            this.#requireLive();
            if (verifying) throw new DirectTransferProtocolError("protocol_invalid");
            if (!(event.data instanceof ArrayBuffer)) throw new DirectTransferProtocolError("protocol_invalid");
            const frame = decodeFrame(event.data);
            if (frame.offset !== expectedOffset) throw new DirectTransferProtocolError("protocol_invalid");
            if (frame.type === FRAME_TYPE_DATA) {
              if (expectedOffset + frame.payload.byteLength > this.#received.byteLength) {
                throw new DirectTransferProtocolError("protocol_invalid");
              }
              this.#received.set(frame.payload, expectedOffset);
              expectedOffset += frame.payload.byteLength;
              this.#bytesReceived = expectedOffset;
              this.#emit();
              return;
            }
            if (expectedOffset !== this.manifest.byteSize) {
              throw new DirectTransferProtocolError("protocol_invalid");
            }
            verifying = true;
            this.#state = "verifying";
            this.#emit();
            const verificationCopy = this.#received.slice();
            try {
              const receipt = await verifyReceivedBytes(this.manifest, verificationCopy);
              this.#requireLive();
              if (!settled) {
                settled = true;
                cleanup();
                resolve(receipt);
              }
            } finally {
              verificationCopy.fill(0);
            }
          } catch (error) {
            fail(error);
          }
        })();
      };
      cleanup = () => {
        channel.removeEventListener("close", closed);
        channel.removeEventListener("error", errored);
        channel.removeEventListener("message", message);
        this.#abortController.signal.removeEventListener("abort", aborted);
      };
      channel.addEventListener("close", closed);
      channel.addEventListener("error", errored);
      channel.addEventListener("message", message);
      if (this.#abortController.signal.aborted) aborted();
      else this.#abortController.signal.addEventListener("abort", aborted, { once: true });
    });
  }

  async #send(channel: RTCDataChannel): Promise<void> {
    for (const range of this.manifest.ranges) {
      for (let offset = range.start; offset < range.endExclusive; offset += FRAME_PAYLOAD_BYTES) {
        this.#requireLive();
        await this.#waitWhilePaused();
        this.#requireLive();
        await waitForBackpressure(channel, this.#abortController.signal);
        this.#requireLive();
        if (channel.readyState !== "open") throw new DirectTransferProtocolError("channel_closed");
        const end = Math.min(range.endExclusive, offset + FRAME_PAYLOAD_BYTES);
        channel.send(encodeFrame(FRAME_TYPE_DATA, offset, this.#source.subarray(offset, end)));
        this.#bytesSent = end;
        this.#emit();
        await nextTask();
      }
    }
    this.#requireLive();
    await this.#waitWhilePaused();
    this.#requireLive();
    channel.send(encodeFrame(FRAME_TYPE_COMPLETE, this.manifest.byteSize, new Uint8Array()));
  }

  async #waitWhilePaused(): Promise<void> {
    while (this.#state === "paused") {
      await new Promise<void>((resolve) => {
        this.#resume = resolve;
      });
    }
  }

  #requireLive(): void {
    if (this.#state === "revoked") throw new DirectTransferProtocolError("revoked_before_completion");
    if (this.#state === "failed") {
      throw new DirectTransferProtocolError(this.#failureReason ?? "channel_closed");
    }
    if (Date.now() >= this.manifest.expiresAt) {
      this.#state = "expired";
      this.#failureReason = null;
      this.#abortController.abort();
      const resume = this.#resume;
      this.#resume = null;
      resume?.();
      this.#closePeers();
      this.#eraseBytes();
      this.#emit();
      throw new DirectTransferProtocolError("expired");
    }
  }

  #stopReason(): DirectTransferFailureReason {
    if (this.#state === "revoked") return "revoked_before_completion";
    if (this.#state === "expired") return "expired";
    if (this.#state === "failed") return this.#failureReason ?? "channel_closed";
    return "channel_closed";
  }

  #terminal(): boolean {
    return this.#state === "completed"
      || this.#state === "revoked"
      || this.#state === "expired"
      || this.#state === "failed";
  }

  #closePeers(): void {
    this.#ownerChannel?.close();
    this.#recipientChannel?.close();
    this.#ownerPeer?.close();
    this.#recipientPeer?.close();
    this.#ownerChannel = null;
    this.#recipientChannel = null;
    this.#ownerPeer = null;
    this.#recipientPeer = null;
  }

  #eraseBytes(): void {
    this.#source.fill(0);
    this.#received.fill(0);
  }

  #emit(): void {
    const status = this.getStatus();
    for (const listener of this.#listeners) listener(status);
  }
}

export async function createSyntheticDirectTransferSession({
  ownerGrant,
  recipientGrant,
  source,
  createdAt = Date.now(),
  expiresAt = createdAt + 10 * 60 * 1_000,
}: {
  ownerGrant: SyntheticDirectTransferGrant;
  recipientGrant: SyntheticDirectTransferGrant;
  source: SyntheticByteSource;
  createdAt?: number;
  expiresAt?: number;
}): Promise<SyntheticDirectTransferSessionPort> {
  const owner = requireSyntheticGrant(ownerGrant, "owner");
  const recipient = requireSyntheticGrant(recipientGrant, "recipient");
  const bytes = consumeSyntheticByteSource(source);
  try {
    const manifest = await buildDirectTransferManifest({
      bytes,
      owner,
      recipient,
      createdAt,
      expiresAt,
    });
    return new SyntheticDirectTransferSession(manifest, bytes);
  } catch (error) {
    bytes.fill(0);
    throw error;
  }
}
