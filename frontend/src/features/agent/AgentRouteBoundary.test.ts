import { describe, expect, it } from "vitest";

import { parseRoute, routePath } from "../../shared/platform/platform";

const AGENT_SOURCES: Record<string, string> = import.meta.glob(
  "/src/features/agent/*.{ts,tsx}",
  { query: "?raw", import: "default", eager: true },
);
const APP_SOURCE: string = import.meta.glob(
  "/src/app/App.tsx",
  { query: "?raw", import: "default", eager: true },
)["/src/app/App.tsx"];

describe("Agent route ownership boundary", () => {
  it("keeps Agent projects and chats independent from analytics catalog and legacy model-chat screens", () => {
    const productionSources = Object.entries(AGENT_SOURCES).filter(([path]) => !path.includes(".test."));
    expect(productionSources.length).toBeGreaterThan(20);
    for (const [path, source] of productionSources) {
      expect(source, path).not.toMatch(/from\s+["'][^"']*(?:local-models|session-catalog|project-catalog)[^"']*["']/u);
      expect(source, path).not.toMatch(/\b(?:LocalModelChatPanel|SessionsPage|ProjectCatalog)\b/u);
    }
  });

  it("routes both Agent surfaces directly to AgentPage and keeps the analytics routes separate", () => {
    expect(APP_SOURCE).toContain('import("../features/agent/AgentPage")');
    expect(APP_SOURCE).toMatch(/route\.name === "agent"[\s\S]*?<AgentScreen sessionId=\{route\.sessionId\} transport=\{transport\} \/>/u);
    expect(parseRoute("/agent")).toEqual({ name: "agent" });
    expect(parseRoute("/agent/window/11111111111111111111111111111111")).toEqual({
      name: "agent",
      sessionId: "11111111111111111111111111111111",
      window: true,
    });
    expect(routePath({ name: "agent" })).toBe("/agent");
    expect(routePath({ name: "sessions" })).toBe("/sessions");
    expect(routePath({ name: "projects" })).toBe("/projects");
  });
});
