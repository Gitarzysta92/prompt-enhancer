import { describe, expect, it } from "vitest";

import * as sessionModule from "./directTransferSession";

const SOURCES: Record<string, string> = import.meta.glob(
  "/src/features/social/directTransfer/*.{ts,tsx}",
  { query: "?raw", import: "default", eager: true },
);

describe("browser direct-transfer privacy boundary", () => {
  it("has no persistence, logging, cloud transport, file picker, URL, or remote signaling primitive", () => {
    const entries = Object.entries(SOURCES).filter(([path]) => !path.endsWith(".test.ts"));
    expect(entries.length).toBeGreaterThanOrEqual(3);
    for (const [path, source] of entries) {
      expect(source, path).not.toMatch(/\b(console\.|localStorage|sessionStorage|indexedDB|fetch\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|createObjectURL|showOpenFilePicker)\b/u);
      expect(source, path).not.toMatch(/iceServers\s*:\s*\[(?!\s*\])/u);
      expect(source, path).not.toMatch(/\b(turn|turns):/iu);
    }
  });

  it("does not import analyzer, metrics, tasks, generated API, or HTTP transport modules", () => {
    for (const [path, source] of Object.entries(SOURCES)) {
      expect(source, path).not.toMatch(/from\s+["'][^"']*(model-ensemble|quality-profile|team-analytics|task-flow|sessions|prompt|transcript|metric|api\/generated|api\/httpTransport)[^"']*["']/iu);
    }
  });

  it("exports only creation factories, never the byte consumer or byte-owning session constructor", () => {
    expect(Object.keys(sessionModule).sort()).toEqual([
      "createSyntheticByteSource",
      "createSyntheticDirectTransferSession",
    ]);
    expect(sessionModule).not.toHaveProperty("consumeSyntheticByteSource");
    expect(sessionModule).not.toHaveProperty("SyntheticDirectTransferSession");
  });
});
