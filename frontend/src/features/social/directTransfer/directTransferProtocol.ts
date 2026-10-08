/**
 * Content-free contracts and integrity helpers for the browser-only synthetic
 * direct-transfer prototype.
 *
 * The transport factory consuming these contracts accepts only a registered
 * in-memory synthetic source. No File, Blob, name, path, URL, candidate or
 * session description is part of a public contract. The byte-oriented helpers
 * here compute or verify integrity only; they cannot open a channel.
 */

export const DIRECT_TRANSFER_PROTOCOL_VERSION = "browser-direct-file.v1" as const;
export const SYNTHETIC_DIRECT_TRANSFER_OPT_IN = "webrtc-datachannel-synthetic-v0" as const;

export const MANIFEST_CHUNK_BYTES = 256 * 1024;
export const FRAME_PAYLOAD_BYTES = 12 * 1024;
export const MAX_SYNTHETIC_FILE_BYTES = 8 * 1024 * 1024;
export const MAX_TRANSFER_RANGES = 32;
export const MAX_SIGNALING_MILLISECONDS = 15_000;
export const MAX_BACKPRESSURE_MILLISECONDS = 10_000;
export const BUFFERED_AMOUNT_HIGH_WATER = 256 * 1024;
export const BUFFERED_AMOUNT_LOW_WATER = 64 * 1024;

export const MERKLE_LEAF_DOMAIN = "prompt-enhancer/direct-file-leaf/v1";
export const MERKLE_NODE_DOMAIN = "prompt-enhancer/direct-file-node/v1";

const SHARE_ID = /^shr_[0-9a-f]{64}$/u;
const PRINCIPAL_ID = /^[0-9a-f]{64}$/u;
const DIGEST = /^[0-9a-f]{64}$/u;

export type SyntheticPeerRole = "owner" | "recipient";

export interface SyntheticVerifiedPrincipal {
  readonly kind: "synthetic_verified_fixture";
  readonly fictional: true;
  readonly verified: true;
  readonly role: SyntheticPeerRole;
  readonly principalId: string;
  readonly deviceId: string;
}

export interface SyntheticDirectTransferGrant {
  readonly kind: "synthetic_direct_transfer_opt_in";
  readonly fictional: true;
  readonly protocolVersion: typeof DIRECT_TRANSFER_PROTOCOL_VERSION;
  readonly principal: SyntheticVerifiedPrincipal;
}

export interface DirectTransferRange {
  readonly start: number;
  readonly endExclusive: number;
}

export interface DirectTransferChunkCommitment {
  readonly index: number;
  readonly offset: number;
  readonly size: number;
  readonly sha256: string;
}

export interface DirectTransferManifest {
  readonly protocolVersion: typeof DIRECT_TRANSFER_PROTOCOL_VERSION;
  readonly manifestId: string;
  readonly transferId: string;
  readonly ownerPrincipalId: string;
  readonly ownerDeviceId: string;
  readonly recipientPrincipalId: string;
  readonly recipientDeviceId: string;
  readonly byteSize: number;
  readonly chunkSize: typeof MANIFEST_CHUNK_BYTES;
  readonly wholeFileSha256: string;
  readonly merkleRootSha256: string;
  readonly chunks: readonly DirectTransferChunkCommitment[];
  readonly ranges: readonly DirectTransferRange[];
  readonly createdAt: number;
  readonly expiresAt: number;
  readonly directOnly: true;
  readonly relayAllowed: false;
  readonly cloudByteFallbackAllowed: false;
  readonly storesFileName: false;
  readonly storesFilePath: false;
}

export type DirectTransferState =
  | "awaiting_recipient_consent"
  | "awaiting_owner_approval"
  | "negotiating_direct"
  | "direct_ready"
  | "transferring"
  | "paused"
  | "verifying"
  | "completed"
  | "revoked"
  | "expired"
  | "failed";

export type DirectTransferFailureReason =
  | "authorization_unavailable"
  | "consent_required"
  | "owner_approval_required"
  | "expired"
  | "revoked_before_completion"
  | "crypto_unavailable"
  | "browser_webrtc_unavailable"
  | "backpressure_timeout"
  | "invalid_manifest"
  | "invalid_range"
  | "protocol_invalid"
  | "relay_candidate_rejected"
  | "integrity_failed"
  | "unreachable_no_relay"
  | "channel_closed";

export interface DirectTransferStatus {
  readonly protocolVersion: typeof DIRECT_TRANSFER_PROTOCOL_VERSION;
  readonly transferId: string;
  readonly state: DirectTransferState;
  readonly byteSize: number;
  readonly bytesSent: number;
  readonly bytesReceived: number;
  readonly recipientConsented: boolean;
  readonly ownerApproved: boolean;
  readonly failureReason: DirectTransferFailureReason | null;
  /** Honest diagnostic only; the browser cannot prove a NAT topology. */
  readonly reachabilityHint: "symmetric_nat_or_cgnat_or_firewall_possible" | null;
  readonly relayUsed: false;
  readonly cloudBytesUsed: false;
  readonly persistedPayload: false;
  readonly remoteRecallGuaranteed: false;
}

export interface DirectTransferVerificationReceipt {
  readonly protocolVersion: typeof DIRECT_TRANSFER_PROTOCOL_VERSION;
  readonly transferId: string;
  readonly manifestId: string;
  readonly receivedBytes: number;
  readonly wholeFileSha256: string;
  readonly merkleRootSha256: string;
  readonly integrity: "verified";
  readonly relayUsed: false;
  readonly cloudBytesUsed: false;
  readonly persistedPayload: false;
  readonly remoteRecallGuaranteed: false;
}

export class DirectTransferProtocolError extends Error {
  readonly reason: DirectTransferFailureReason;

  constructor(reason: DirectTransferFailureReason) {
    super(reason);
    this.name = "DirectTransferProtocolError";
    this.reason = reason;
  }
}

const principalRegistry = new WeakMap<object, SyntheticVerifiedPrincipal>();
const grantRegistry = new WeakMap<object, SyntheticVerifiedPrincipal>();

const FIXTURE_PRINCIPALS: Readonly<Record<SyntheticPeerRole, { principalId: string; deviceId: string }>> = {
  owner: { principalId: "a0".repeat(32), deviceId: "d0".repeat(32) },
  recipient: { principalId: "a1".repeat(32), deviceId: "d1".repeat(32) },
};

export function issueSyntheticVerifiedPrincipal(role: SyntheticPeerRole): SyntheticVerifiedPrincipal {
  if (role !== "owner" && role !== "recipient") {
    throw new DirectTransferProtocolError("authorization_unavailable");
  }
  const fixture = FIXTURE_PRINCIPALS[role];
  const principal = Object.freeze({
    kind: "synthetic_verified_fixture" as const,
    fictional: true as const,
    verified: true as const,
    role,
    principalId: fixture.principalId,
    deviceId: fixture.deviceId,
  });
  principalRegistry.set(principal, principal);
  return principal;
}

export function grantSyntheticDirectTransfer(
  principal: SyntheticVerifiedPrincipal,
  exactOptIn: string,
): SyntheticDirectTransferGrant {
  requireSyntheticPrincipal(principal);
  if (exactOptIn !== SYNTHETIC_DIRECT_TRANSFER_OPT_IN) {
    throw new DirectTransferProtocolError("authorization_unavailable");
  }
  const grant = Object.freeze({
    kind: "synthetic_direct_transfer_opt_in" as const,
    fictional: true as const,
    protocolVersion: DIRECT_TRANSFER_PROTOCOL_VERSION,
    principal,
  });
  grantRegistry.set(grant, principal);
  return grant;
}

export function requireSyntheticPrincipal(value: SyntheticVerifiedPrincipal): SyntheticVerifiedPrincipal {
  const registered = principalRegistry.get(value);
  if (registered !== value) {
    throw new DirectTransferProtocolError("authorization_unavailable");
  }
  return registered;
}

export function requireSyntheticGrant(
  value: SyntheticDirectTransferGrant,
  expectedRole: SyntheticPeerRole,
): SyntheticVerifiedPrincipal {
  const principal = grantRegistry.get(value);
  if (principal === undefined || principal.role !== expectedRole || value.principal !== principal) {
    throw new DirectTransferProtocolError("authorization_unavailable");
  }
  return principal;
}

function bytesFromHex(value: string): Uint8Array {
  if (!DIGEST.test(value)) throw new DirectTransferProtocolError("invalid_manifest");
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(value.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function hexFromBytes(value: Uint8Array): string {
  return [...value].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function concatenate(parts: readonly Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((sum, part) => sum + part.byteLength, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.byteLength;
  }
  return output;
}

function utf8(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function unsigned64(value: number): Uint8Array {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new DirectTransferProtocolError("invalid_manifest");
  }
  const bytes = new Uint8Array(8);
  new DataView(bytes.buffer).setBigUint64(0, BigInt(value), false);
  return bytes;
}

export async function sha256Hex(value: Uint8Array): Promise<string> {
  if (globalThis.crypto?.subtle === undefined) {
    throw new DirectTransferProtocolError("crypto_unavailable");
  }
  const copy = Uint8Array.from(value);
  try {
    const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", copy.buffer));
    try {
      return hexFromBytes(digest);
    } finally {
      digest.fill(0);
    }
  } finally {
    copy.fill(0);
  }
}

async function merkleLeaf(chunk: DirectTransferChunkCommitment): Promise<Uint8Array> {
  const material = concatenate([
    utf8(MERKLE_LEAF_DOMAIN),
    new Uint8Array([0]),
    unsigned64(chunk.index),
    unsigned64(chunk.offset),
    unsigned64(chunk.size),
    bytesFromHex(chunk.sha256),
  ]);
  return bytesFromHex(await sha256Hex(material));
}

export async function computeMerkleRoot(
  chunks: readonly DirectTransferChunkCommitment[],
): Promise<string> {
  if (chunks.length === 0) throw new DirectTransferProtocolError("invalid_manifest");
  let level = await Promise.all(chunks.map(merkleLeaf));
  while (level.length > 1) {
    const next: Uint8Array[] = [];
    for (let index = 0; index < level.length; index += 2) {
      const left = level[index];
      const right = level[index + 1] ?? left;
      const material = concatenate([
        utf8(MERKLE_NODE_DOMAIN),
        new Uint8Array([0]),
        left,
        right,
      ]);
      next.push(bytesFromHex(await sha256Hex(material)));
    }
    level = next;
  }
  return hexFromBytes(level[0]);
}

export function canonicalFullRanges(byteSize: number): readonly DirectTransferRange[] {
  if (!Number.isSafeInteger(byteSize) || byteSize < 1 || byteSize > MAX_SYNTHETIC_FILE_BYTES) {
    throw new DirectTransferProtocolError("invalid_range");
  }
  const ranges: DirectTransferRange[] = [];
  for (let start = 0; start < byteSize; start += MANIFEST_CHUNK_BYTES) {
    ranges.push(Object.freeze({ start, endExclusive: Math.min(byteSize, start + MANIFEST_CHUNK_BYTES) }));
  }
  return Object.freeze(ranges);
}

export function validateFullCoverageRanges(
  ranges: readonly DirectTransferRange[],
  byteSize: number,
): readonly DirectTransferRange[] {
  if (
    !Array.isArray(ranges)
    || !Number.isSafeInteger(byteSize)
    || byteSize < 1
    || byteSize > MAX_SYNTHETIC_FILE_BYTES
    || ranges.length < 1
    || ranges.length > MAX_TRANSFER_RANGES
  ) {
    throw new DirectTransferProtocolError("invalid_range");
  }
  let expectedStart = 0;
  const canonical = ranges.map((range) => {
    if (
      !Number.isSafeInteger(range.start)
      || !Number.isSafeInteger(range.endExclusive)
      || range.start !== expectedStart
      || range.endExclusive <= range.start
      || range.endExclusive > byteSize
      || range.start % MANIFEST_CHUNK_BYTES !== 0
      || (range.endExclusive !== byteSize && range.endExclusive % MANIFEST_CHUNK_BYTES !== 0)
    ) {
      throw new DirectTransferProtocolError("invalid_range");
    }
    expectedStart = range.endExclusive;
    return Object.freeze({ start: range.start, endExclusive: range.endExclusive });
  });
  if (expectedStart !== byteSize) throw new DirectTransferProtocolError("invalid_range");
  return Object.freeze(canonical);
}

function randomShareId(): string {
  if (globalThis.crypto?.getRandomValues === undefined) {
    throw new DirectTransferProtocolError("crypto_unavailable");
  }
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  return `shr_${hexFromBytes(bytes)}`;
}

export async function buildDirectTransferManifest({
  bytes,
  owner,
  recipient,
  createdAt,
  expiresAt,
  ranges,
}: {
  bytes: Uint8Array;
  owner: SyntheticVerifiedPrincipal;
  recipient: SyntheticVerifiedPrincipal;
  createdAt: number;
  expiresAt: number;
  ranges?: readonly DirectTransferRange[];
}): Promise<DirectTransferManifest> {
  requireSyntheticPrincipal(owner);
  requireSyntheticPrincipal(recipient);
  if (owner.role !== "owner" || recipient.role !== "recipient") {
    throw new DirectTransferProtocolError("authorization_unavailable");
  }
  if (
    !(bytes instanceof Uint8Array)
    || !Number.isSafeInteger(createdAt)
    || !Number.isSafeInteger(expiresAt)
    || expiresAt <= createdAt
    || expiresAt - createdAt > 24 * 60 * 60 * 1_000
    || bytes.byteLength < 1
    || bytes.byteLength > MAX_SYNTHETIC_FILE_BYTES
  ) {
    throw new DirectTransferProtocolError("invalid_manifest");
  }
  const chunks: DirectTransferChunkCommitment[] = [];
  for (let offset = 0, index = 0; offset < bytes.byteLength; offset += MANIFEST_CHUNK_BYTES, index += 1) {
    const part = bytes.subarray(offset, Math.min(bytes.byteLength, offset + MANIFEST_CHUNK_BYTES));
    chunks.push(Object.freeze({ index, offset, size: part.byteLength, sha256: await sha256Hex(part) }));
  }
  const wholeFileSha256 = await sha256Hex(bytes);
  const canonicalRanges = validateFullCoverageRanges(
    ranges ?? canonicalFullRanges(bytes.byteLength),
    bytes.byteLength,
  );
  const manifest = Object.freeze({
    protocolVersion: DIRECT_TRANSFER_PROTOCOL_VERSION,
    manifestId: randomShareId(),
    transferId: randomShareId(),
    ownerPrincipalId: owner.principalId,
    ownerDeviceId: owner.deviceId,
    recipientPrincipalId: recipient.principalId,
    recipientDeviceId: recipient.deviceId,
    byteSize: bytes.byteLength,
    chunkSize: MANIFEST_CHUNK_BYTES,
    wholeFileSha256,
    merkleRootSha256: await computeMerkleRoot(chunks),
    chunks: Object.freeze(chunks),
    ranges: canonicalRanges,
    createdAt,
    expiresAt,
    directOnly: true as const,
    relayAllowed: false as const,
    cloudByteFallbackAllowed: false as const,
    storesFileName: false as const,
    storesFilePath: false as const,
  });
  await validateManifest(manifest);
  return manifest;
}

export async function validateManifest(manifest: DirectTransferManifest): Promise<void> {
  if (
    manifest.protocolVersion !== DIRECT_TRANSFER_PROTOCOL_VERSION
    || !SHARE_ID.test(manifest.manifestId)
    || !SHARE_ID.test(manifest.transferId)
    || !PRINCIPAL_ID.test(manifest.ownerPrincipalId)
    || !PRINCIPAL_ID.test(manifest.ownerDeviceId)
    || !PRINCIPAL_ID.test(manifest.recipientPrincipalId)
    || !PRINCIPAL_ID.test(manifest.recipientDeviceId)
    || manifest.chunkSize !== MANIFEST_CHUNK_BYTES
    || manifest.directOnly !== true
    || manifest.relayAllowed !== false
    || manifest.cloudByteFallbackAllowed !== false
    || manifest.storesFileName !== false
    || manifest.storesFilePath !== false
    || !DIGEST.test(manifest.wholeFileSha256)
    || !DIGEST.test(manifest.merkleRootSha256)
    || !Number.isSafeInteger(manifest.createdAt)
    || !Number.isSafeInteger(manifest.expiresAt)
    || manifest.expiresAt <= manifest.createdAt
    || manifest.expiresAt - manifest.createdAt > 24 * 60 * 60 * 1_000
    || !Number.isSafeInteger(manifest.byteSize)
    || manifest.byteSize < 1
    || manifest.byteSize > MAX_SYNTHETIC_FILE_BYTES
    || !Array.isArray(manifest.chunks)
    || !Array.isArray(manifest.ranges)
  ) {
    throw new DirectTransferProtocolError("invalid_manifest");
  }
  const expectedCount = Math.ceil(manifest.byteSize / MANIFEST_CHUNK_BYTES);
  if (manifest.chunks.length !== expectedCount) {
    throw new DirectTransferProtocolError("invalid_manifest");
  }
  for (let index = 0; index < manifest.chunks.length; index += 1) {
    const chunk = manifest.chunks[index];
    const offset = index * MANIFEST_CHUNK_BYTES;
    const size = Math.min(MANIFEST_CHUNK_BYTES, manifest.byteSize - offset);
    if (chunk.index !== index || chunk.offset !== offset || chunk.size !== size || !DIGEST.test(chunk.sha256)) {
      throw new DirectTransferProtocolError("invalid_manifest");
    }
  }
  validateFullCoverageRanges(manifest.ranges, manifest.byteSize);
  if (await computeMerkleRoot(manifest.chunks) !== manifest.merkleRootSha256) {
    throw new DirectTransferProtocolError("invalid_manifest");
  }
}

export async function verifyReceivedBytes(
  manifest: DirectTransferManifest,
  bytes: Uint8Array,
): Promise<DirectTransferVerificationReceipt> {
  await validateManifest(manifest);
  if (bytes.byteLength !== manifest.byteSize) {
    throw new DirectTransferProtocolError("integrity_failed");
  }
  const chunks: DirectTransferChunkCommitment[] = [];
  for (let offset = 0, index = 0; offset < bytes.byteLength; offset += MANIFEST_CHUNK_BYTES, index += 1) {
    const part = bytes.subarray(offset, Math.min(bytes.byteLength, offset + MANIFEST_CHUNK_BYTES));
    chunks.push({ index, offset, size: part.byteLength, sha256: await sha256Hex(part) });
  }
  const whole = await sha256Hex(bytes);
  const merkle = await computeMerkleRoot(chunks);
  const chunksMatch = chunks.every((chunk, index) => chunk.sha256 === manifest.chunks[index]?.sha256);
  if (!chunksMatch || whole !== manifest.wholeFileSha256 || merkle !== manifest.merkleRootSha256) {
    throw new DirectTransferProtocolError("integrity_failed");
  }
  return Object.freeze({
    protocolVersion: DIRECT_TRANSFER_PROTOCOL_VERSION,
    transferId: manifest.transferId,
    manifestId: manifest.manifestId,
    receivedBytes: bytes.byteLength,
    wholeFileSha256: whole,
    merkleRootSha256: merkle,
    integrity: "verified" as const,
    relayUsed: false as const,
    cloudBytesUsed: false as const,
    persistedPayload: false as const,
    remoteRecallGuaranteed: false as const,
  });
}
