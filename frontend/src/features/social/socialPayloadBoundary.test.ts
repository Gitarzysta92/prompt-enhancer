import { describe, expect, it } from "vitest";

/**
 * Structural guard for requirement "analyzer sessions, prompts, metrics, and
 * explanations can never be inserted into chat or file-share payloads": the
 * social feature and its port must not import any analyzer module, and no
 * analyzer surface may offer a share-to-chat control. The only free-text
 * fields on the wire are a user-typed demo message body and file metadata.
 */
const SOCIAL_SOURCES: Record<string, string> = {
  ...import.meta.glob("/src/features/social/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }),
  ...import.meta.glob("/src/shared/api/socialHub*.ts", { query: "?raw", import: "default", eager: true }),
};
const ANALYZER_SOURCES: Record<string, string> = import.meta.glob(
  ["/src/features/**/*.{ts,tsx}", "!/src/features/social/**"],
  { query: "?raw", import: "default", eager: true },
);

const FORBIDDEN_IMPORT = /from\s+["'][^"']*(model-ensemble|quality-profile|team-analytics|task-flow|sessions|prompt|transcript|metricHelp|metricGuidance|metricAxisModel|api\/contracts|api\/httpTransport|api\/generated)[^"']*["']/u;

describe("social payload boundary", () => {
  it("never imports an analyzer, metric, session, or transcript module into the social feature or its port", () => {
    const entries = Object.entries(SOCIAL_SOURCES).filter(([file]) => !/\.test\.tsx?$/u.test(file));
    expect(entries.length).toBeGreaterThan(10);
    for (const [file, source] of entries) {
      expect(source, file).not.toMatch(FORBIDDEN_IMPORT);
    }
  });

  it("offers no share-to-chat or send-to-social control anywhere in the analyzer surfaces", () => {
    const entries = Object.entries(ANALYZER_SOURCES).filter(([file]) => !/\.test\.tsx?$/u.test(file));
    expect(entries.length).toBeGreaterThan(20);
    for (const [file, source] of entries) {
      expect(source, file).not.toMatch(/share[ _-]?to[ _-]?chat|send[ _-]?to[ _-]?social|socialHub|SocialHub|social-hub/iu);
    }
  });

  it("carries only user-typed demo text and file metadata as free-text payload fields", async () => {
    const { createSyntheticSocialSnapshot } = await import("../../shared/api/socialHub");
    const snapshot = createSyntheticSocialSnapshot();
    const messageKeys = new Set(snapshot.messages.flatMap((message) => Object.keys(message)));
    expect([...messageKeys].sort()).toEqual([
      "author_id", "body", "conversation_id", "file_offer_id", "id", "kind", "reactions", "sent_at", "thread_root_id",
    ]);
    for (const offer of snapshot.file_offers) {
      expect(Object.keys(offer.file).sort()).toEqual(["digest_hex", "display_name", "media_type", "size_bytes"]);
    }
  });
});
