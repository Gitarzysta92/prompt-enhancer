import type { AppRoute } from "../shared/platform/platform";

export type PrimaryNavigationKey =
  | "overview"
  | "projects"
  | "sessions"
  | "agent"
  | "discovery"
  | "reviewed-tasks"
  | "task-flow"
  | "prompt-checks"
  | "calibration"
  | "team"
  | "social"
  | "models"
  | "local-sources"
  | "analysis-jobs"
  | "research";

export interface AppRouteMetadata {
  navigationKey: PrimaryNavigationKey | null;
  title: string;
  titleOwner: "shell" | "screen";
  trail: "Personal workspace" | "Scoped workspace" | "Social workspace";
}

/**
 * One exhaustive, content-free description for every route family.
 *
 * Identifiers and display data deliberately do not belong here. The manifest
 * drives only shell copy and navigation ownership, so a malformed or private
 * URL can never be echoed by route recovery UI.
 */
export const APP_ROUTE_MANIFEST = {
  discovery: {
    navigationKey: "discovery",
    title: "Discovery",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  local_sources: {
    navigationKey: "local-sources",
    title: "Data sources",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  analysis_jobs: {
    navigationKey: "analysis-jobs",
    title: "Analysis jobs",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  research: {
    navigationKey: "research",
    title: "Methods & models",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  team: {
    navigationKey: "team",
    title: "Team analytics",
    titleOwner: "shell",
    trail: "Scoped workspace",
  },
  social: {
    navigationKey: "social",
    title: "Social hub",
    titleOwner: "shell",
    trail: "Social workspace",
  },
  task_flow: {
    navigationKey: "task-flow",
    title: "Task flow",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  projects: {
    navigationKey: "projects",
    title: "Projects",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  sessions: {
    navigationKey: "sessions",
    title: "Sessions",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  calibration: {
    navigationKey: "calibration",
    title: "Calibration",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  models: {
    navigationKey: "models",
    title: "Models",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  prompt_checks: {
    navigationKey: "prompt-checks",
    title: "Prompt check",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  overview: {
    navigationKey: "overview",
    title: "Overview",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  agent: {
    navigationKey: "agent",
    title: "Agent",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  project_overview: {
    navigationKey: "projects",
    title: "Project workspace",
    titleOwner: "screen",
    trail: "Personal workspace",
  },
  live: {
    navigationKey: null,
    title: "Live",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  project_sessions: {
    navigationKey: "projects",
    title: "Project workspace",
    titleOwner: "screen",
    trail: "Personal workspace",
  },
  project_automation: {
    navigationKey: "projects",
    title: "Project automation",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  project_metrics: {
    navigationKey: "projects",
    title: "Project workspace",
    titleOwner: "screen",
    trail: "Personal workspace",
  },
  session_metrics: {
    navigationKey: "projects",
    title: "Project workspace",
    titleOwner: "screen",
    trail: "Personal workspace",
  },
  task: {
    navigationKey: "reviewed-tasks",
    title: "Task analysis",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
  not_found: {
    navigationKey: null,
    title: "Page not found",
    titleOwner: "shell",
    trail: "Personal workspace",
  },
} as const satisfies Record<AppRoute["name"], AppRouteMetadata>;

export function routeMetadata(route: AppRoute): AppRouteMetadata {
  return APP_ROUTE_MANIFEST[route.name];
}
