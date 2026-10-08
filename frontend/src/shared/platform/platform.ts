export type AppRoute =
  | { name: "discovery" }
  | { name: "local_sources" }
  | { name: "analysis_jobs" }
  | { name: "research" }
  | { name: "team" }
  | { name: "social" }
  | { name: "task_flow" }
  | { name: "projects" }
  | { name: "sessions" }
  | { name: "calibration" }
  | { name: "models" }
  | { name: "prompt_checks"; checkId?: string; sessionId?: string }
  | { name: "overview" }
  | { name: "agent"; sessionId?: string; window?: boolean }
  | { name: "project_overview"; projectId: string }
  | { name: "live"; projectId: string; sessionId?: string }
  | { name: "project_sessions"; projectId: string }
  | { name: "project_automation"; projectId: string }
  | { name: "project_metrics"; projectId: string; category: MetricCategory }
  | {
      name: "session_metrics";
      projectId: string;
      sessionId: string;
      category: MetricCategory;
    }
  | { name: "task"; taskId: string; revision: number }
  | { name: "not_found" };

export interface PlatformAdapter {
  currentRoute(): AppRoute;
  navigate(route: AppRoute): void;
  subscribe(listener: (route: AppRoute) => void): () => void;
}

const PSEUDONYM = /^[a-f0-9]{64}$/;

export function isPseudonym(value: string): boolean {
  return PSEUDONYM.test(value);
}

export const METRIC_ROUTE_CATEGORIES = [
  "readiness",
  "execution",
  "tools",
  "model-usage",
  "outcome",
  "prompt-quality",
  "reasoning",
  "other",
] as const;

export type MetricCategory = (typeof METRIC_ROUTE_CATEGORIES)[number];

export const APP_ROUTE_NAMES = [
  "discovery",
  "local_sources",
  "analysis_jobs",
  "research",
  "team",
  "social",
  "task_flow",
  "projects",
  "sessions",
  "calibration",
  "models",
  "prompt_checks",
  "overview",
  "agent",
  "project_overview",
  "live",
  "project_sessions",
  "project_automation",
  "project_metrics",
  "session_metrics",
  "task",
  "not_found",
] as const satisfies readonly AppRoute["name"][];

type MissingAppRouteName = Exclude<AppRoute["name"], (typeof APP_ROUTE_NAMES)[number]>;
const appRouteNamesAreExhaustive: MissingAppRouteName extends never ? true : never = true;
void appRouteNamesAreExhaustive;

const METRIC_CATEGORY = new Set<string>(METRIC_ROUTE_CATEGORIES);

export function isMetricCategory(value: string): value is MetricCategory {
  return METRIC_CATEGORY.has(value);
}

export function parseRoute(pathname: string): AppRoute {
  if (/^\/$/.test(pathname)) return { name: "discovery" };
  if (/^\/local-sources\/?$/.test(pathname)) return { name: "local_sources" };
  if (/^\/analysis-jobs\/?$/.test(pathname)) return { name: "analysis_jobs" };
  if (/^\/research\/methods\/?$/.test(pathname)) return { name: "research" };
  if (/^\/team\/?$/.test(pathname)) return { name: "team" };
  if (/^\/social\/?$/.test(pathname)) return { name: "social" };
  if (/^\/tasks\/flow\/?$/.test(pathname)) return { name: "task_flow" };
  if (/^\/projects\/?$/.test(pathname)) return { name: "projects" };
  if (/^\/sessions\/?$/.test(pathname)) return { name: "sessions" };
  if (/^\/calibration\/?$/.test(pathname)) return { name: "calibration" };
  if (/^\/models\/?$/.test(pathname)) return { name: "models" };
  if (/^\/prompt-checks\/?$/.test(pathname)) return { name: "prompt_checks" };
  if (/^\/overview\/?$/.test(pathname)) return { name: "overview" };
  if (/^\/agent\/?$/.test(pathname)) return { name: "agent" };
  if (/^\/not-found\/?$/.test(pathname)) return { name: "not_found" };
  const agentWindow = pathname.match(/^\/agent\/window(?:\/([0-9a-f]{32}))?\/?$/);
  if (agentWindow) return agentWindow[1] ? { name: "agent", sessionId: agentWindow[1], window: true } : { name: "agent", window: true };
  const promptCheckSessionMatch = pathname.match(/^\/prompt-checks\/for\/([a-f0-9]{64})\/?$/);
  if (promptCheckSessionMatch && isPseudonym(promptCheckSessionMatch[1])) return { name: "prompt_checks", sessionId: promptCheckSessionMatch[1] };
  const promptCheckMatch = pathname.match(/^\/prompt-checks\/([a-f0-9]{64})\/?$/);
  if (promptCheckMatch && isPseudonym(promptCheckMatch[1])) return { name: "prompt_checks", checkId: promptCheckMatch[1] };

  const sessionMetricMatch = pathname.match(
    /^\/projects\/([a-f0-9]{64})\/sessions\/([a-f0-9]{64})\/metrics\/([a-z-]+)\/?$/,
  );
  if (
    sessionMetricMatch &&
    isPseudonym(sessionMetricMatch[1]) &&
    isPseudonym(sessionMetricMatch[2]) &&
    isMetricCategory(sessionMetricMatch[3])
  ) {
    return {
      name: "session_metrics",
      projectId: sessionMetricMatch[1],
      sessionId: sessionMetricMatch[2],
      category: sessionMetricMatch[3],
    };
  }

  const projectMetricMatch = pathname.match(
    /^\/projects\/([a-f0-9]{64})\/metrics\/([a-z-]+)\/?$/,
  );
  if (
    projectMetricMatch &&
    isPseudonym(projectMetricMatch[1]) &&
    isMetricCategory(projectMetricMatch[2])
  ) {
    return {
      name: "project_metrics",
      projectId: projectMetricMatch[1],
      category: projectMetricMatch[2],
    };
  }

  const liveMatch = pathname.match(/^\/live\/projects\/([a-f0-9]{64})(?:\/sessions\/([a-f0-9]{64}))?\/?$/);
  if (liveMatch && isPseudonym(liveMatch[1]) && (liveMatch[2] === undefined || isPseudonym(liveMatch[2]))) {
    return liveMatch[2]
      ? { name: "live", projectId: liveMatch[1], sessionId: liveMatch[2] }
      : { name: "live", projectId: liveMatch[1] };
  }

  const projectViewMatch = pathname.match(
    /^\/projects\/([a-f0-9]{64})\/(overview|sessions|automation)\/?$/,
  );
  if (projectViewMatch && isPseudonym(projectViewMatch[1])) {
    if (projectViewMatch[2] === "overview") {
      return { name: "project_overview", projectId: projectViewMatch[1] };
    }
    if (projectViewMatch[2] === "sessions") {
      return { name: "project_sessions", projectId: projectViewMatch[1] };
    }
    return { name: "project_automation", projectId: projectViewMatch[1] };
  }

  const match = pathname.match(/^\/tasks\/([a-f0-9]{64})\/revisions\/(\d+)\/?$/);
  if (match && isPseudonym(match[1])) {
    const revision = Number(match[2]);
    if (Number.isSafeInteger(revision) && revision > 0) {
      return { name: "task", taskId: match[1], revision };
    }
  }
  return { name: "not_found" };
}

export function routePath(route: AppRoute): string {
  if (route.name === "discovery") return "/";
  if (route.name === "local_sources") return "/local-sources";
  if (route.name === "analysis_jobs") return "/analysis-jobs";
  if (route.name === "research") return "/research/methods";
  if (route.name === "team") return "/team";
  if (route.name === "social") return "/social";
  if (route.name === "task_flow") return "/tasks/flow";
  if (route.name === "projects") return "/projects";
  if (route.name === "sessions") return "/sessions";
  if (route.name === "calibration") return "/calibration";
  if (route.name === "models") return "/models";
  if (route.name === "prompt_checks") return route.checkId ? `/prompt-checks/${route.checkId}` : route.sessionId ? `/prompt-checks/for/${route.sessionId}` : "/prompt-checks";
  if (route.name === "overview") return "/overview";
  if (route.name === "agent") return route.window ? (route.sessionId ? `/agent/window/${route.sessionId}` : "/agent/window") : "/agent";
  if (route.name === "not_found") return "/not-found";
  if (route.name === "project_overview") {
    assertPseudonym(route.projectId);
    return `/projects/${route.projectId}/overview`;
  }
  if (route.name === "live") {
    assertPseudonym(route.projectId);
    if (route.sessionId) {
      assertPseudonym(route.sessionId);
      return `/live/projects/${route.projectId}/sessions/${route.sessionId}`;
    }
    return `/live/projects/${route.projectId}`;
  }
  if (route.name === "project_sessions") {
    assertPseudonym(route.projectId);
    return `/projects/${route.projectId}/sessions`;
  }
  if (route.name === "project_automation") {
    assertPseudonym(route.projectId);
    return `/projects/${route.projectId}/automation`;
  }
  if (route.name === "project_metrics") {
    assertPseudonym(route.projectId);
    assertMetricCategory(route.category);
    return `/projects/${route.projectId}/metrics/${route.category}`;
  }
  if (route.name === "session_metrics") {
    assertPseudonym(route.projectId);
    assertPseudonym(route.sessionId);
    assertMetricCategory(route.category);
    return `/projects/${route.projectId}/sessions/${route.sessionId}/metrics/${route.category}`;
  }
  if (route.name === "task") return `/tasks/${route.taskId}/revisions/${route.revision}`;
  return assertUnreachableRoute(route);
}

function assertPseudonym(value: string): void {
  if (!isPseudonym(value)) {
    throw new TypeError("Route identifiers must be lowercase 64-character pseudonyms.");
  }
}

function assertMetricCategory(value: string): asserts value is MetricCategory {
  if (!isMetricCategory(value)) {
    throw new TypeError("Metric category is not allowlisted.");
  }
}

function assertUnreachableRoute(route: never): never {
  throw new TypeError(`Unsupported route family: ${String(route)}`);
}
