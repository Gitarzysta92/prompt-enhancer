import { describe, expect, it } from "vitest";
import {
  APP_ROUTE_NAMES,
  parseRoute,
  routePath,
  type AppRoute,
} from "../shared/platform/platform";
import { APP_ROUTE_MANIFEST } from "./appRouteManifest";

const PROJECT_ID = "a".repeat(64);
const SESSION_ID = "b".repeat(64);
const TASK_ID = "c".repeat(64);
const CHECK_ID = "d".repeat(64);

const ROUTE_FAMILY_EXAMPLES: readonly AppRoute[] = [
  { name: "discovery" },
  { name: "local_sources" },
  { name: "analysis_jobs" },
  { name: "research" },
  { name: "team" },
  { name: "social" },
  { name: "task_flow" },
  { name: "projects" },
  { name: "sessions" },
  { name: "calibration" },
  { name: "models" },
  { name: "prompt_checks" },
  { name: "overview" },
  { name: "agent" },
  { name: "project_overview", projectId: PROJECT_ID },
  { name: "live", projectId: PROJECT_ID },
  { name: "project_sessions", projectId: PROJECT_ID },
  { name: "project_automation", projectId: PROJECT_ID },
  { name: "project_metrics", projectId: PROJECT_ID, category: "readiness" },
  {
    name: "session_metrics",
    projectId: PROJECT_ID,
    sessionId: SESSION_ID,
    category: "readiness",
  },
  { name: "task", taskId: TASK_ID, revision: 1 },
  { name: "not_found" },
];

describe("application route manifest", () => {
  it("covers every route family exactly once with content-free shell metadata", () => {
    expect(new Set(APP_ROUTE_NAMES).size).toBe(APP_ROUTE_NAMES.length);
    expect(ROUTE_FAMILY_EXAMPLES.map((route) => route.name).sort()).toEqual(
      [...APP_ROUTE_NAMES].sort(),
    );
    expect(Object.keys(APP_ROUTE_MANIFEST).sort()).toEqual([...APP_ROUTE_NAMES].sort());

    for (const metadata of Object.values(APP_ROUTE_MANIFEST)) {
      expect(metadata.title.trim()).not.toBe("");
      expect(metadata.trail).toMatch(/workspace$/);
      expect(JSON.stringify(metadata)).not.toMatch(/[a-f0-9]{64}/);
    }
  });

  it.each(ROUTE_FAMILY_EXAMPLES)("round-trips the $name route family", (route) => {
    expect(parseRoute(routePath(route))).toEqual(route);
  });

  it("accounts for every supported multi-shape direct route", () => {
    const variants: readonly AppRoute[] = [
      { name: "prompt_checks", checkId: CHECK_ID },
      { name: "prompt_checks", sessionId: SESSION_ID },
      { name: "agent", window: true },
      { name: "agent", sessionId: "e".repeat(32), window: true },
      { name: "live", projectId: PROJECT_ID, sessionId: SESSION_ID },
    ];

    for (const route of variants) {
      expect(parseRoute(routePath(route))).toEqual(route);
    }
  });
});
