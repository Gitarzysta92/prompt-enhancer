import { describe, expect, it } from "vitest";

import {
  MAX_SYNTHETIC_FILE_BYTES,
  MANIFEST_CHUNK_BYTES,
  SYNTHETIC_DIRECT_TRANSFER_OPT_IN,
  DirectTransferProtocolError,
  buildDirectTransferManifest,
  canonicalFullRanges,
  computeMerkleRoot,
  grantSyntheticDirectTransfer,
  issueSyntheticVerifiedPrincipal,
  validateFullCoverageRanges,
  validateManifest,
  verifyReceivedBytes,
  type SyntheticVerifiedPrincipal,
  type SyntheticPeerRole,
} from "./directTransferProtocol";

function fixtureBytes(byteLength: number, seed: number): Uint8Array {
  let state = seed >>> 0;
  const bytes = new Uint8Array(byteLength);
  for (let index = 0; index < bytes.length; index += 1) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    bytes[index] = state & 0xff;
  }
  return bytes;
}

describe("synthetic direct-transfer protocol", () => {
  it("requires registered fixture principals and the exact opt-in literal", () => {
    const owner = issueSyntheticVerifiedPrincipal("owner");
    expect(() => grantSyntheticDirectTransfer(owner, "enabled")).toThrowError(
      expect.objectContaining({ reason: "authorization_unavailable" }),
    );
    expect(grantSyntheticDirectTransfer(owner, SYNTHETIC_DIRECT_TRANSFER_OPT_IN).principal).toBe(owner);

    const forged = { ...owner } as SyntheticVerifiedPrincipal;
    expect(() => grantSyntheticDirectTransfer(forged, SYNTHETIC_DIRECT_TRANSFER_OPT_IN)).toThrowError(
      expect.objectContaining({ reason: "authorization_unavailable" }),
    );
    expect(() => issueSyntheticVerifiedPrincipal("intruder" as SyntheticPeerRole)).toThrowError(
      expect.objectContaining({ reason: "authorization_unavailable" }),
    );
  });

  it("matches the Python domain-separated Merkle golden vector exactly", async () => {
    const root = await computeMerkleRoot([
      { index: 0, offset: 0, size: MANIFEST_CHUNK_BYTES, sha256: "00".repeat(32) },
      { index: 1, offset: MANIFEST_CHUNK_BYTES, size: 17, sha256: "11".repeat(32) },
    ]);
    expect(root).toBe("f1493b03d2dfa7f58c834c379899946ea730d6918f53e6d3a9c22b11adcf1634");
  });

  it("builds and verifies an immutable full-coverage manifest without name, path, URL, or payload fields", async () => {
    const owner = issueSyntheticVerifiedPrincipal("owner");
    const recipient = issueSyntheticVerifiedPrincipal("recipient");
    const bytes = fixtureBytes(MANIFEST_CHUNK_BYTES + 17, 19);
    const manifest = await buildDirectTransferManifest({
      bytes,
      owner,
      recipient,
      createdAt: 2_000_000,
      expiresAt: 2_600_000,
    });
    await expect(validateManifest(manifest)).resolves.toBeUndefined();
    const receipt = await verifyReceivedBytes(manifest, bytes);
    expect(receipt).toMatchObject({
      integrity: "verified",
      receivedBytes: MANIFEST_CHUNK_BYTES + 17,
      relayUsed: false,
      cloudBytesUsed: false,
      persistedPayload: false,
      remoteRecallGuaranteed: false,
    });
    const serialized = JSON.stringify(manifest);
    expect(serialized).not.toMatch(/"(fileName|file_name|filePath|file_path|path|name|payload|candidate|sessionDescription|url)"\s*:/u);
    expect(serialized).not.toContain(bytes.slice(0, 32).join(","));
    bytes.fill(0);
  });

  it("rejects gaps, overlap, non-canonical boundaries, excessive ranges, and a forged Merkle root", async () => {
    expect(() => validateFullCoverageRanges([{ start: 1, endExclusive: 10 }], 10)).toThrowError(
      expect.objectContaining({ reason: "invalid_range" }),
    );
    expect(() => validateFullCoverageRanges([
      { start: 0, endExclusive: MANIFEST_CHUNK_BYTES },
      { start: MANIFEST_CHUNK_BYTES - 1, endExclusive: MANIFEST_CHUNK_BYTES + 1 },
    ], MANIFEST_CHUNK_BYTES + 1)).toThrowError(expect.objectContaining({ reason: "invalid_range" }));
    expect(() => validateFullCoverageRanges([
      { start: 0, endExclusive: MANIFEST_CHUNK_BYTES },
      { start: MANIFEST_CHUNK_BYTES * 2, endExclusive: MANIFEST_CHUNK_BYTES * 2 + 1 },
    ], MANIFEST_CHUNK_BYTES * 2 + 1)).toThrowError(expect.objectContaining({ reason: "invalid_range" }));
    expect(canonicalFullRanges(8 * 1024 * 1024)).toHaveLength(32);

    const owner = issueSyntheticVerifiedPrincipal("owner");
    const recipient = issueSyntheticVerifiedPrincipal("recipient");
    const bytes = fixtureBytes(1_024, 23);
    const manifest = await buildDirectTransferManifest({
      bytes,
      owner,
      recipient,
      createdAt: 10,
      expiresAt: 1_000,
    });
    await expect(validateManifest({ ...manifest, merkleRootSha256: "0".repeat(64) })).rejects.toMatchObject({
      reason: "invalid_manifest",
    });
    await expect(validateManifest({ ...manifest, byteSize: MAX_SYNTHETIC_FILE_BYTES + 1 })).rejects.toMatchObject({
      reason: "invalid_manifest",
    });
    await expect(validateManifest({
      ...manifest,
      expiresAt: manifest.createdAt + 24 * 60 * 60 * 1_000 + 1,
    })).rejects.toMatchObject({ reason: "invalid_manifest" });
    await expect(validateManifest({ ...manifest, createdAt: Number.NaN })).rejects.toMatchObject({
      reason: "invalid_manifest",
    });
    await expect(validateManifest({ ...manifest, chunks: null } as unknown as typeof manifest)).rejects.toMatchObject({
      reason: "invalid_manifest",
    });
    await expect(validateManifest({ ...manifest, ranges: null } as unknown as typeof manifest)).rejects.toMatchObject({
      reason: "invalid_manifest",
    });
    bytes.fill(0);
  });

  it("detects received-byte corruption even when manifest metadata remains valid", async () => {
    const owner = issueSyntheticVerifiedPrincipal("owner");
    const recipient = issueSyntheticVerifiedPrincipal("recipient");
    const bytes = fixtureBytes(65_537, 29);
    const manifest = await buildDirectTransferManifest({
      bytes,
      owner,
      recipient,
      createdAt: 100,
      expiresAt: 10_000,
    });
    bytes[32] ^= 0xff;
    await expect(verifyReceivedBytes(manifest, bytes)).rejects.toBeInstanceOf(DirectTransferProtocolError);
    await expect(verifyReceivedBytes(manifest, bytes)).rejects.toMatchObject({ reason: "integrity_failed" });
    bytes.fill(0);
  });
});
