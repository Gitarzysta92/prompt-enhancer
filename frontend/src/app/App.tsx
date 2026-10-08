import { FirstRunPanel } from "../features/onboarding/FirstRunPanel";
import {
  Component,
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
  type ReactNode,
} from "react";
import type { PromptEnhancerTransport, Provider } from "../shared/api/contracts";
import type { TeamControlPlanePort } from "../shared/api/teamControlPlane";
import { composeTeamControlPlanePort } from "../shared/api/teamControlPlaneRuntime";
import type { SocialHubPort } from "../shared/api/socialHubSchema";
import { composeSocialHubPort } from "../shared/api/socialHubRuntime";
import type { AppRoute, PlatformAdapter } from "../shared/platform/platform";
import { routePath } from "../shared/platform/platform";
import type {
  RuntimeComposition,
  RuntimeDataMode,
  RuntimeServiceState,
} from "../shared/platform/runtimeMode";
import { DiscoveryInbox } from "../features/discovery-inbox/DiscoveryInbox";
import type { ProjectWorkspaceRoute } from "../features/project-workspace";
import { Icon, type IconName } from "../shared/ui/Icon";
import { ThemeToggle } from "../shared/ui/ThemeToggle";
import { LoadingState } from "../shared/ui/AsyncState";
import { EmptyState } from "../shared/ui/EmptyState";
import { Dialog } from "../shared/ui/Dialog";
import { retryableLazy as lazy, RouteLoadAttempt } from "../shared/ui/retryableLazy";
import { routeMetadata } from "./appRouteManifest";
import { ApplicationUpdateControl } from "./ApplicationUpdateControl";

const AnalysisJobCentreScreen = lazy(() =>
  import("../features/analysis-job-centre").then((module) => ({
    default: module.AnalysisJobCentre,
  })),
);
const LocalSourcesScreen = lazy(() =>
  import("../features/local-sources/LocalSources").then((module) => ({
    default: module.LocalSources,
  })),
);
const SessionsScreen = lazy(() =>
  import("../features/session-catalog/SessionsPage").then((module) => ({ default: module.SessionsPage })),
);
const CalibrationScreen = lazy(() =>
  import("../features/calibration/CalibrationPage").then((module) => ({ default: module.CalibrationPage })),
);
const LocalModelsScreen = lazy(() =>
  import("../features/local-models/LocalModelsPage").then((module) => ({ default: module.LocalModelsPage })),
);
const AgentScreen = lazy(() =>
  import("../features/agent/AgentPage").then((module) => ({ default: module.AgentPage })),
);
const OverviewScreen = lazy(() =>
  import("../features/overview/OverviewPage").then((module) => ({ default: module.OverviewPage })),
);
const PromptChecksScreen = lazy(() =>
  import("../features/prompt-check/PromptCheckPage").then((module) => ({ default: module.PromptCheckPage })),
);
const LiveMiniWindowScreen = lazy(() =>
  import("../features/live-window/LiveMiniWindow").then((module) => ({ default: module.LiveMiniWindow })),
);
const ProjectCatalogScreen = lazy(() =>
  import("../features/project-catalog").then((module) => ({
    default: module.ProjectCatalog,
  })),
);
const ProjectAutomationScreen = lazy(() =>
  import("../features/project-automation").then((module) => ({
    default: module.ProjectAutomationSettings,
  })),
);
const ProjectWorkspaceScreen = lazy(() =>
  import("../features/project-workspace").then((module) => ({
    default: module.ProjectWorkspace,
  })),
);
const ResearchLabScreen = lazy(() =>
  import("../features/research-lab").then((module) => ({
    default: module.ResearchLab,
  })),
);
const TaskDetailScreen = lazy(() =>
  import("../features/task-detail/TaskDetail").then((module) => ({
    default: module.TaskDetail,
  })),
);
const TeamAnalyticsScreen = lazy(() =>
  import("../features/team-analytics").then((module) => ({
    default: module.TeamAnalyticsPage,
  })),
);
const TaskFlowScreen = lazy(() =>
  import("../features/task-flow").then((module) => ({
    default: module.TaskFlowPage,
  })),
);
const SocialHubScreen = lazy(() =>
  import("../features/social").then((module) => ({
    default: module.SocialHubPage,
  })),
);

const PRIMARY_NAV_ICONS = {
  overview: "dashboard",
  projects: "folder",
  sessions: "clock",
  calibration: "sliders",
  models: "cpu",
  agent: "bot",
  promptChecks: "check",
  discovery: "branch",
  reviewedTasks: "tasks",
  taskFlow: "board",
  team: "users",
  social: "chat",
  localSources: "database",
  analysisJobs: "activity",
  research: "flask",
} as const satisfies Record<string, IconName>;

interface RouteErrorBoundaryProps {
  children: ReactNode;
  exitLabel?: string;
  onExit?: () => void;
  resetKey: string;
}

interface RouteErrorBoundaryState {
  failed: boolean;
  resetKey: string;
  attempt: object;
}

/** Keep a failed route bundle from taking down the runtime/privacy shell. */
export class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  constructor(props: RouteErrorBoundaryProps) {
    super(props);
    this.state = { failed: false, resetKey: props.resetKey, attempt: {} };
  }

  static getDerivedStateFromError(): Partial<RouteErrorBoundaryState> {
    return { failed: true };
  }

  static getDerivedStateFromProps(
    props: RouteErrorBoundaryProps,
    state: RouteErrorBoundaryState,
  ): Partial<RouteErrorBoundaryState> | null {
    if (props.resetKey !== state.resetKey) {
      return { failed: false, resetKey: props.resetKey, attempt: state.failed ? {} : state.attempt };
    }
    return null;
  }

  componentDidUpdate(
    _previousProps: RouteErrorBoundaryProps,
    previousState: RouteErrorBoundaryState,
  ) {
    if (previousState.failed && !this.state.failed) {
      document.getElementById("main-content")?.focus();
    }
  }

  private retry = () => {
    this.setState({ failed: false, attempt: {} });
  };

  render() {
    if (!this.state.failed) return <RouteLoadAttempt.Provider value={this.state.attempt}>{this.props.children}</RouteLoadAttempt.Provider>;
    return (
      <div className="async-state async-state--error route-error" role="alert">
        <span className="async-state__icon"><Icon name="x" /></span>
        <div className="route-error__message">
          <strong>This screen could not be loaded</strong>
          <p>The local screen failed safely. No provider error or session content is shown.</p>
        </div>
        <div className="route-error__actions">
          <button className="button button--primary" onClick={this.retry} type="button">
            Retry screen
          </button>
          <button className="button button--secondary" onClick={() => window.location.reload()} type="button">
            Reload app
          </button>
          {this.props.onExit !== undefined && (
            <button className="button button--secondary" onClick={this.props.onExit} type="button">
              {this.props.exitLabel ?? "Leave this screen"}
            </button>
          )}
        </div>
      </div>
    );
  }
}

interface PrimaryNavigationItem {
  active: boolean;
  busy?: boolean;
  icon: IconName;
  indicator?: { label: string; value: number };
  key: string;
  label: string;
  onSelect: () => void;
}

interface PrimaryNavigationSection {
  collapsible?: boolean;
  description?: string;
  key: string;
  label: string;
  items: readonly PrimaryNavigationItem[];
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
}

function BrandMark() {
  return (
    <span className="brand__mark brand__mark--glyph" aria-hidden="true">
      <svg viewBox="0 0 36 36" focusable="false">
        <path className="brand__caret" d="M11 10 L19 18 L11 26" />
        <path className="brand__caret brand__caret--lift" d="M17 25.5 L25 25.5" />
        <path className="brand__spark" d="M26.5 7.5 L27.6 11 L31 12.1 L27.6 13.2 L26.5 16.7 L25.4 13.2 L22 12.1 L25.4 11 Z" />
      </svg>
    </span>
  );
}

function PrimaryNavigation({
  activeItemRef,
  activeDisclosureRef,
  ariaLabel,
  idPrefix,
  onSelectItem,
  sections,
  variant,
}: {
  activeItemRef?: RefObject<HTMLButtonElement | null>;
  activeDisclosureRef?: RefObject<HTMLElement | null>;
  ariaLabel: string;
  idPrefix: string;
  onSelectItem?: (item: PrimaryNavigationItem) => void;
  sections: readonly PrimaryNavigationSection[];
  variant: "drawer" | "sidebar";
}) {
  return (
    <nav aria-label={ariaLabel} className={`primary-nav primary-nav--${variant}`}>
      {sections.map((section) => {
        const labelId = `${idPrefix}-${section.key}`;
        const itemsId = `${idPrefix}-${section.key}-items`;
        const items = (
          <div className="primary-nav__items" id={itemsId}>
            {section.items.map((item) => (
              <button
                aria-busy={item.busy || undefined}
                aria-current={item.active ? "page" : undefined}
                className={item.active ? "primary-nav__item--active" : ""}
                disabled={item.busy}
                key={item.key}
                onClick={() => (onSelectItem === undefined ? item.onSelect() : onSelectItem(item))}
                ref={item.active ? activeItemRef : undefined}
                type="button"
              >
                <Icon name={item.icon} />
                <span>{item.label}</span>
                {item.indicator !== undefined && (
                  <span className="nav-indicator" aria-label={item.indicator.label}>
                    {item.indicator.value}
                  </span>
                )}
              </button>
            ))}
          </div>
        );
        return (
          <div
            aria-labelledby={labelId}
            className="primary-nav__section"
            key={section.key}
            role={section.collapsible ? undefined : "group"}
          >
            {section.collapsible ? (
              <details
                aria-labelledby={labelId}
                open={section.open}
                onToggle={(event) => {
                  const nextOpen = event.currentTarget.open;
                  if (nextOpen !== section.open) section.onOpenChange?.(nextOpen);
                }}
              >
                <summary aria-controls={itemsId} ref={section.items.some((item) => item.active) ? activeDisclosureRef : undefined}>
                  <span id={labelId}>{section.label}</span>
                  <Icon name="chevron" />
                </summary>
                {section.description !== undefined && (
                  <p className="primary-nav__section-copy">{section.description}</p>
                )}
                {items}
              </details>
            ) : (
              <>
                <p id={labelId}>{section.label}</p>
                {section.description !== undefined && (
                  <p className="primary-nav__section-copy">{section.description}</p>
                )}
                {items}
              </>
            )}
          </div>
        );
      })}
    </nav>
  );
}

function isProjectWorkspaceRoute(route: AppRoute): route is ProjectWorkspaceRoute {
  return (
    route.name === "project_overview" ||
    route.name === "project_sessions" ||
    route.name === "project_metrics" ||
    route.name === "session_metrics"
  );
}

function routeTitle(route: AppRoute): string {
  return routeMetadata(route).title;
}

function workspaceTrail(route: AppRoute): string {
  return routeMetadata(route).trail;
}

function RouteLoading({ route }: { route: AppRoute }) {
  return <LoadingState label={`Loading ${routeTitle(route)}…`} />;
}

function runtimeStatusCopy(
  mode: RuntimeDataMode,
  serviceState: RuntimeServiceState,
): {
  chip: string;
  detail: string;
  indicator: string;
} {
  if (mode === "synthetic_demo") {
    return {
      chip: "Synthetic demo · Fixture ready",
      detail: "Fictional in-memory fixtures",
      indicator: "Synthetic demo fixture ready",
    };
  }
  if (serviceState === "checking") {
    return {
      chip: "Local real · Checking service",
      detail: "Checking loopback service",
      indicator: "Local loopback service is being checked",
    };
  }
  if (serviceState === "available") {
    return {
      chip: "Local real · Service available",
      detail: "Loopback service available",
      indicator: "Local loopback service available",
    };
  }
  return {
    chip: "Local real · Service unavailable",
    detail: "Loopback service unavailable",
    indicator: "Local loopback service unavailable",
  };
}

function useCompactShellViewport(routeName: AppRoute["name"]): boolean {
  const query = routeName === "agent"
    ? "(max-width: 1180px)"
    : "(max-width: 860px)";
  const [compact, setCompact] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia(query);
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return compact;
}

export function App({
  platform,
  runtime,
  teamControlPlane,
  socialHub,
}: {
  platform: PlatformAdapter;
  runtime: RuntimeComposition;
  /** Defaults to the honest port for the runtime: fixture in synthetic demo, unavailable in local real. */
  teamControlPlane?: TeamControlPlanePort;
  /** Defaults to the honest social port for the runtime; a fixture can never cross into local real. */
  socialHub?: SocialHubPort;
}) {
  const transport: PromptEnhancerTransport = runtime.transport;
  const [route, setRoute] = useState<AppRoute>(() => platform.currentRoute());
  const compactShell = useCompactShellViewport(route.name);
  const teamPort = useMemo(
    () => composeTeamControlPlanePort(runtime.mode, teamControlPlane),
    [runtime.mode, teamControlPlane],
  );
  const socialPort = useMemo(
    () => composeSocialHubPort(runtime.mode, socialHub),
    [runtime.mode, socialHub],
  );
  const routeIdentity = routePath(route);
  const routeContextRef = useRef({
    identity: routeIdentity,
    projectWorkspace: isProjectWorkspaceRoute(route),
  });
  const latestTaskControllerRef = useRef<AbortController | null>(null);
  const desktopActiveItemRef = useRef<HTMLButtonElement>(null);
  const desktopActiveDisclosureRef = useRef<HTMLElement>(null);
  const mobileActiveItemRef = useRef<HTMLButtonElement>(null);
  const mobileActiveDisclosureRef = useRef<HTMLElement>(null);
  const mobileNavigationActionRef = useRef<(() => void) | null>(null);
  const focusDesktopNavigationAfterDrawerCloseRef = useRef(false);
  const focusMainAfterDrawerCloseRef = useRef(false);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [navigationNotice, setNavigationNotice] = useState("");
  const [latestTaskPending, setLatestTaskPending] = useState(false);
  const [undecidedCount, setUndecidedCount] = useState<number | null>(null);
  const [serviceRetry, setServiceRetry] = useState(0);
  const activeNavigationKey = routeMetadata(route).navigationKey;
  const isLabsRoute = activeNavigationKey === "prompt-checks"
    || activeNavigationKey === "calibration"
    || activeNavigationKey === "research"
    || activeNavigationKey === "team"
    || activeNavigationKey === "social";
  const [labsOpen, setLabsOpen] = useState(isLabsRoute);
  const previousLabsRouteRef = useRef(routeIdentity);
  const [serviceState, setServiceState] = useState<RuntimeServiceState>(() =>
    runtime.mode === "synthetic_demo" ? "available" : "checking",
  );
  const runtimeCopy = runtimeStatusCopy(runtime.mode, serviceState);
  const coverageProvider: Provider =
    runtime.mode === "synthetic_demo" ? "synthetic" : "codex";

  useEffect(() => platform.subscribe(setRoute), [platform]);

  useEffect(() => {
    const enteredLabs = isLabsRoute && previousLabsRouteRef.current !== routeIdentity;
    previousLabsRouteRef.current = routeIdentity;
    if (!isLabsRoute) {
      setLabsOpen(false);
    } else if (enteredLabs) {
      setLabsOpen(true);
    }
  }, [isLabsRoute, routeIdentity]);

  useEffect(() => {
    setNavigationNotice("");
    setLatestTaskPending(false);
    return () => {
      latestTaskControllerRef.current?.abort();
      latestTaskControllerRef.current = null;
    };
  }, [routeIdentity, transport]);

  useEffect(() => {
    if (mobileNavigationOpen || mobileNavigationActionRef.current === null) return;
    const action = mobileNavigationActionRef.current;
    mobileNavigationActionRef.current = null;
    action();
  }, [mobileNavigationOpen]);

  useLayoutEffect(() => {
    if (compactShell) return;
    if (mobileNavigationOpen) {
      focusDesktopNavigationAfterDrawerCloseRef.current = true;
      // A mobile Labs disclosure can be the only mounted open copy while the
      // breakpoint changes. Preserve that user-visible state before the
      // drawer unmounts so the desktop active destination remains reachable.
      if (isLabsRoute && mobileActiveItemRef.current !== null) setLabsOpen(true);
    }
    mobileNavigationActionRef.current = null;
    setMobileNavigationOpen(false);
  }, [compactShell]);

  useLayoutEffect(() => {
    if (!mobileNavigationOpen) return;
    mobileNavigationActionRef.current = null;
    focusMainAfterDrawerCloseRef.current = true;
    setMobileNavigationOpen(false);
  }, [routeIdentity]);

  useLayoutEffect(() => {
    if (mobileNavigationOpen) return;
    if (focusMainAfterDrawerCloseRef.current) {
      focusMainAfterDrawerCloseRef.current = false;
      focusDesktopNavigationAfterDrawerCloseRef.current = false;
      document.getElementById("main-content")?.focus();
      return;
    }
    if (!compactShell && focusDesktopNavigationAfterDrawerCloseRef.current) {
      focusDesktopNavigationAfterDrawerCloseRef.current = false;
      const activeTarget = isLabsRoute && !labsOpen
        ? desktopActiveDisclosureRef.current
        : desktopActiveItemRef.current;
      if (activeTarget !== null && activeTarget !== undefined) {
        const frame = window.requestAnimationFrame(() => {
          if (activeTarget.isConnected) activeTarget.focus();
        });
        return () => window.cancelAnimationFrame(frame);
      }
    }
    return undefined;
  }, [compactShell, isLabsRoute, labsOpen, mobileNavigationOpen, routeIdentity]);

  useLayoutEffect(() => {
    if (compactShell) return undefined;
    const scrollActiveItem = () => {
      const activeItem = desktopActiveItemRef.current;
      const navigation = activeItem?.closest<HTMLElement>(".primary-nav--sidebar");
      if (activeItem === null || navigation === null || navigation === undefined) return;
      if (activeItem.closest("details:not([open])") !== null) return;
      const itemBounds = activeItem.getBoundingClientRect();
      const navigationBounds = navigation.getBoundingClientRect();
      if (itemBounds.top < navigationBounds.top) {
        navigation.scrollTop += itemBounds.top - navigationBounds.top;
      } else if (itemBounds.bottom > navigationBounds.bottom) {
        navigation.scrollTop += itemBounds.bottom - navigationBounds.bottom;
      }
    };
    scrollActiveItem();
    const frame = window.requestAnimationFrame(scrollActiveItem);
    const navigation = desktopActiveItemRef.current?.closest<HTMLElement>(".primary-nav--sidebar");
    const observer = typeof ResizeObserver === "function"
      && navigation !== null && navigation !== undefined
      ? new ResizeObserver(scrollActiveItem)
      : null;
    observer?.observe(navigation!);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [compactShell, labsOpen, routeIdentity]);

  useLayoutEffect(() => {
    document.title = `${routeTitle(route)} · Prompt Enhancer`;
    const previous = routeContextRef.current;
    const projectWorkspace = isProjectWorkspaceRoute(route);
    routeContextRef.current = { identity: routeIdentity, projectWorkspace };

    // Initial routes retain the browser's natural focus start for the skip link.
    if (previous.identity === routeIdentity) return;
    // ProjectWorkspace owns precise heading focus between its own subroutes.
    if (previous.projectWorkspace && projectWorkspace) return;
    document.getElementById("main-content")?.focus();
  }, [routeIdentity]);

  useEffect(() => {
    if (runtime.mode === "synthetic_demo") {
      setServiceState("available");
      return;
    }
    const controller = new AbortController();
    setServiceState("checking");
    void runtime.transport
      .getRuntimeHealth(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setServiceState("available");
      })
      .catch(() => {
        if (!controller.signal.aborted) setServiceState("unavailable");
      });
    return () => controller.abort();
  }, [runtime, serviceRetry]);

  function navigate(next: AppRoute) {
    latestTaskControllerRef.current?.abort();
    latestTaskControllerRef.current = null;
    setLatestTaskPending(false);
    setNavigationNotice("");
    platform.navigate(next);
  }

  function selectFromMobileNavigation(item: PrimaryNavigationItem) {
    mobileNavigationActionRef.current = item.onSelect;
    setMobileNavigationOpen(false);
  }

  async function openLatestTask() {
    latestTaskControllerRef.current?.abort();
    const controller = new AbortController();
    latestTaskControllerRef.current = controller;
    setLatestTaskPending(true);
    setNavigationNotice("Opening reviewed task…");
    try {
      const response = await transport.listTaskRevisions(undefined, controller.signal);
      if (controller.signal.aborted || latestTaskControllerRef.current !== controller) return;
      const latest = response.tasks[0];
      if (!latest) {
        setNavigationNotice("No reviewed task is available yet.");
        return;
      }
      navigate({ name: "task", taskId: latest.task_id, revision: latest.revision });
    } catch {
      if (controller.signal.aborted || latestTaskControllerRef.current !== controller) return;
      setNavigationNotice("The task index could not be loaded.");
    } finally {
      if (latestTaskControllerRef.current === controller) {
        latestTaskControllerRef.current = null;
        setLatestTaskPending(false);
      }
    }
  }

  const discoveryIndicator = undecidedCount === null
    ? undefined
    : {
        label: `${undecidedCount} ${undecidedCount === 1 ? "candidate needs" : "candidates need"} review`,
        value: undecidedCount,
      };
  const navigationSections: readonly PrimaryNavigationSection[] = [
    {
      key: "core",
      label: "Core",
      items: [
        {
          active: activeNavigationKey === "agent",
          icon: PRIMARY_NAV_ICONS.agent,
          key: "agent",
          label: "Agent",
          onSelect: () => navigate({ name: "agent" }),
        },
        {
          active: activeNavigationKey === "overview",
          icon: PRIMARY_NAV_ICONS.overview,
          key: "overview",
          label: "Overview",
          onSelect: () => navigate({ name: "overview" }),
        },
        {
          active: activeNavigationKey === "models",
          icon: PRIMARY_NAV_ICONS.models,
          key: "models",
          label: "Models",
          onSelect: () => navigate({ name: "models" }),
        },
      ],
    },
    {
      key: "review",
      label: "Review",
      items: [
        {
          active: activeNavigationKey === "projects",
          icon: PRIMARY_NAV_ICONS.projects,
          key: "projects",
          label: "Projects",
          onSelect: () => navigate({ name: "projects" }),
        },
        {
          active: activeNavigationKey === "sessions",
          icon: PRIMARY_NAV_ICONS.sessions,
          key: "sessions",
          label: "Sessions",
          onSelect: () => navigate({ name: "sessions" }),
        },
        ...(runtime.mode === "local_real"
          ? [{
              active: activeNavigationKey === "local-sources",
              icon: PRIMARY_NAV_ICONS.localSources,
              key: "local-sources",
              label: "Data sources",
              onSelect: () => navigate({ name: "local_sources" }),
            } satisfies PrimaryNavigationItem]
          : []),
        {
          active: activeNavigationKey === "discovery",
          icon: PRIMARY_NAV_ICONS.discovery,
          indicator: discoveryIndicator,
          key: "discovery",
          label: "Discovery",
          onSelect: () => navigate({ name: "discovery" }),
        },
        {
          active: activeNavigationKey === "reviewed-tasks",
          busy: latestTaskPending,
          icon: PRIMARY_NAV_ICONS.reviewedTasks,
          key: "reviewed-tasks",
          label: latestTaskPending ? "Opening reviewed task…" : "Reviewed tasks",
          onSelect: () => void openLatestTask(),
        },
        {
          active: activeNavigationKey === "task-flow",
          icon: PRIMARY_NAV_ICONS.taskFlow,
          key: "task-flow",
          label: "Task flow",
          onSelect: () => navigate({ name: "task_flow" }),
        },
        {
          active: activeNavigationKey === "analysis-jobs",
          icon: PRIMARY_NAV_ICONS.analysisJobs,
          key: "analysis-jobs",
          label: "Analysis jobs",
          onSelect: () => navigate({ name: "analysis_jobs" }),
        },
      ],
    },
    {
      collapsible: true,
      description: "Experimental analysis · Team and Social previews (not released backends).",
      key: "labs",
      label: "Labs",
      onOpenChange: setLabsOpen,
      open: labsOpen,
      items: [
        {
          active: activeNavigationKey === "prompt-checks",
          icon: PRIMARY_NAV_ICONS.promptChecks,
          key: "prompt-checks",
          label: "Prompt check",
          onSelect: () => navigate({ name: "prompt_checks" }),
        },
        {
          active: activeNavigationKey === "calibration",
          icon: PRIMARY_NAV_ICONS.calibration,
          key: "calibration",
          label: "Calibration",
          onSelect: () => navigate({ name: "calibration" }),
        },
        {
          active: activeNavigationKey === "research",
          icon: PRIMARY_NAV_ICONS.research,
          key: "research",
          label: "Methods & models",
          onSelect: () => navigate({ name: "research" }),
        },
        {
          active: activeNavigationKey === "team",
          icon: PRIMARY_NAV_ICONS.team,
          key: "team",
          label: "Team analytics (preview)",
          onSelect: () => navigate({ name: "team" }),
        },
        {
          active: activeNavigationKey === "social",
          icon: PRIMARY_NAV_ICONS.social,
          key: "social",
          label: "Social hub (demo)",
          onSelect: () => navigate({ name: "social" }),
        },
      ],
    },
  ];
  const mobileRuntimeText = runtime.mode === "synthetic_demo"
    ? "Synthetic fixture ready"
    : serviceState === "checking"
      ? "Local service checking"
      : serviceState === "available"
        ? "Local service available"
        : "Local service unavailable";

  if (route.name === "agent" && route.window) {
    // Chrome-less agent window: the workspace chat alone, like a second editor pane.
    return (
      <div className="app-shell app-shell--live app-shell--agent-window" data-layout="agent-window">
        <main id="main-content" tabIndex={-1}>
          <RouteErrorBoundary
            exitLabel="Return to Agent"
            onExit={() => navigate({ name: "agent" })}
            resetKey={routeIdentity}
          >
            <Suspense fallback={<RouteLoading route={route} />}>
              <AgentScreen sessionId={route.sessionId} transport={transport} windowMode />
            </Suspense>
          </RouteErrorBoundary>
        </main>
      </div>
    );
  }

  if (route.name === "live") {
    // Chrome-less mini window: no sidebar, no header - just the live view.
    return (
      <div className="app-shell app-shell--live" data-layout="live-window">
        <main id="main-content" tabIndex={-1}>
          <RouteErrorBoundary
            exitLabel="Return to Discovery"
            onExit={() => navigate({ name: "discovery" })}
            resetKey={routeIdentity}
          >
            <Suspense fallback={<RouteLoading route={route} />}>
              <LiveMiniWindowScreen projectId={route.projectId} sessionId={route.sessionId} transport={transport} />
            </Suspense>
          </RouteErrorBoundary>
        </main>
      </div>
    );
  }

  return (
    <div
      className={`app-shell${route.name === "agent" ? " app-shell--agent-focus" : ""}`}
      data-layout="responsive-shell"
    >
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="mobile-shell-header">
        <div aria-label="Prompt Enhancer" className="mobile-shell-header__identity">
          <BrandMark />
          <span>
            <strong>Prompt Enhancer</strong>
            <small>{routeTitle(route)}</small>
          </span>
        </div>
        <div className="mobile-shell-header__actions">
          {compactShell && <ThemeToggle />}
          <button
            aria-busy={latestTaskPending || undefined}
            aria-expanded={mobileNavigationOpen}
            aria-haspopup="dialog"
            aria-label={latestTaskPending ? "Opening reviewed task" : "Open navigation"}
            className="mobile-shell-header__menu"
            onClick={() => setMobileNavigationOpen(true)}
            type="button"
          >
            <Icon name="menu" />
            <span>{latestTaskPending ? "Opening…" : "Menu"}</span>
          </button>
        </div>
        <span
          aria-label={`Private by default. Mobile runtime status: ${runtimeCopy.indicator}`}
          aria-live="polite"
          className="mobile-runtime-marker"
          data-service-state={serviceState}
        >
          <span className="mobile-runtime-marker__icon"><Icon name="lock" /></span>
          <span>
            <strong>Private by default</strong>
            <small>{mobileRuntimeText}</small>
          </span>
          <span aria-hidden="true" className={`online-dot online-dot--${serviceState}`} />
        </span>
      </header>
      <aside aria-label="Application" className="sidebar">
        <div aria-label="Prompt Enhancer" className="brand">
          <BrandMark />
          <span>
            <strong>Prompt</strong>
            <small>Enhancer</small>
          </span>
        </div>

        <PrimaryNavigation
          activeDisclosureRef={desktopActiveDisclosureRef}
          activeItemRef={desktopActiveItemRef}
          ariaLabel="Primary"
          idPrefix="sidebar-navigation"
          sections={navigationSections}
          variant="sidebar"
        />

        <div className="sidebar__footer">
          <ApplicationUpdateControl transport={transport} variant="sidebar" />
          <div className="privacy-status">
            <span className="privacy-status__icon"><Icon name="lock" /></span>
            <div>
              <strong>Private by default</strong>
              <span>{runtimeCopy.detail}</span>
            </div>
            <span
              aria-label={runtimeCopy.indicator}
              className={`online-dot online-dot--${serviceState}`}
            />
          </div>
          <p>No remote analytics - no content export</p>
        </div>
      </aside>

      <div className="workspace" data-route={route.name}>
        {serviceState === "unavailable" && runtime.mode === "local_real" && (
          <div className="async-state async-state--error" role="status">
            <span>The local service could not be reached. Your screen is still open.</span>
            <button className="button button--secondary" onClick={() => setServiceRetry((value) => value + 1)} type="button">
              Recheck local service
            </button>
          </div>
        )}
        <header className="topbar">
          <div aria-label="Current location" className="topbar__trail">
            <span>{workspaceTrail(route)}</span>
            <Icon name="chevron" />
            <strong>{routeTitle(route)}</strong>
          </div>
          <div className="topbar__right">
            {!compactShell && <ThemeToggle />}
            <span
              aria-label={`Runtime status: ${runtimeCopy.indicator}`}
              aria-live="polite"
              className="mode-chip"
              data-service-state={serviceState}
            >
              <span /> {runtimeCopy.chip}
            </span>
            <span className="avatar" aria-label="Local profile">L</span>
          </div>
        </header>
        {navigationNotice && <div className="navigation-notice" role="status">{navigationNotice}</div>}
        <main id="main-content" tabIndex={-1}>
          <RouteErrorBoundary
            exitLabel="Return to Discovery"
            onExit={route.name === "discovery" ? undefined : () => navigate({ name: "discovery" })}
            resetKey={routeIdentity}
          >
            <Suspense fallback={<RouteLoading route={route} />}>
              {route.name === "discovery" ? (
                <>
                  <FirstRunPanel navigate={navigate} transport={transport} />
                  <DiscoveryInbox
                    navigate={navigate}
                    onUndecidedCountChange={setUndecidedCount}
                    transport={transport}
                  />
                </>
              ) : route.name === "sessions" ? (
                <SessionsScreen navigate={navigate} runtimeMode={runtime.mode} transport={transport} />
              ) : route.name === "calibration" ? (
                <CalibrationScreen transport={transport} />
              ) : route.name === "models" ? (
                <LocalModelsScreen transport={transport} />
              ) : route.name === "prompt_checks" ? (
                <PromptChecksScreen checkId={route.checkId} navigate={navigate} sessionId={route.sessionId} transport={transport} />
              ) : route.name === "overview" ? (
                <OverviewScreen navigate={navigate} runtimeMode={runtime.mode} transport={transport} />
              ) : route.name === "agent" ? (
                <AgentScreen sessionId={route.sessionId} transport={transport} />
              ) : route.name === "not_found" ? (
                <section className="not-found-page" aria-labelledby="not-found-title">
                  <header className="page-header route-header">
                    <div>
                      <p className="eyebrow">Navigation</p>
                      <h1 id="not-found-title">Page not found</h1>
                      <p>The requested address is not a Prompt Enhancer screen.</p>
                    </div>
                  </header>
                  <EmptyState
                    action={(
                      <div className="route-error__actions">
                        <button
                          className="button button--primary"
                          onClick={() => navigate({ name: "overview" })}
                          type="button"
                        >
                          Open Overview
                        </button>
                        <button
                          className="button button--secondary"
                          onClick={() => navigate({ name: "discovery" })}
                          type="button"
                        >
                          Open Discovery
                        </button>
                      </div>
                    )}
                    description="This address is not a Prompt Enhancer screen. The invalid path is not retained or displayed."
                    icon="search"
                    title="Choose a destination"
                    tone="closed"
                  />
                </section>
              ) : route.name === "projects" ? (
                <ProjectCatalogScreen
                  coverageProvider={coverageProvider}
                  navigate={navigate}
                  transport={transport}
                />
              ) : route.name === "project_automation" ? (
                <ProjectAutomationScreen
                  navigate={navigate}
                  projectId={route.projectId}
                  runtimeMode={runtime.mode}
                  serviceState={serviceState}
                  transport={transport}
                />
              ) : isProjectWorkspaceRoute(route) ? (
                <ProjectWorkspaceScreen
                  coverageProvider={coverageProvider}
                  navigate={navigate}
                  route={route}
                  transport={transport}
                />
              ) : route.name === "local_sources" ? (
                runtime.mode === "local_real" ? (
                  <LocalSourcesScreen navigate={navigate} transport={transport} />
                ) : (
                  <section aria-labelledby="local-sources-title" className="local-sources-page">
                    <header className="page-header route-header">
                      <div>
                        <p className="eyebrow">Private local workflow</p>
                        <h1 id="local-sources-title">Data sources</h1>
                        <p>Choose which local providers and projects may contribute bounded metadata.</p>
                      </div>
                    </header>
                    <EmptyState
                      action={(
                        <button
                          className="button button--secondary"
                          onClick={() => navigate({ name: "discovery" })}
                          type="button"
                        >
                          Return to Discovery
                        </button>
                      )}
                      description="Run the integrated loopback build to grant and inspect local-source access."
                      title="Data sources are disabled in synthetic preview"
                      tone="closed"
                    />
                  </section>
                )
              ) : route.name === "analysis_jobs" ? (
                <AnalysisJobCentreScreen
                  runtimeMode={runtime.mode}
                  serviceState={serviceState}
                  transport={transport}
                />
              ) : route.name === "research" ? (
                <ResearchLabScreen transport={transport} />
              ) : route.name === "team" ? (
                <TeamAnalyticsScreen
                  navigate={navigate}
                  port={teamPort}
                  runtimeMode={runtime.mode}
                  serviceState={serviceState}
                />
              ) : route.name === "social" ? (
                <SocialHubScreen port={socialPort} runtimeMode={runtime.mode} />
              ) : route.name === "task_flow" ? (
                <TaskFlowScreen
                  navigate={navigate}
                  runtimeMode={runtime.mode}
                  transport={transport}
                />
              ) : (
                <TaskDetailScreen
                  navigate={navigate}
                  revision={route.revision}
                  taskId={route.taskId}
                  transport={transport}
                />
              )}
            </Suspense>
          </RouteErrorBoundary>
        </main>
      </div>
      <Dialog
        closeLabel="Close navigation"
        description="Choose a destination. The current screen receives focus first."
        initialFocusRef={isLabsRoute && !labsOpen ? mobileActiveDisclosureRef : mobileActiveItemRef}
        onClose={() => setMobileNavigationOpen(false)}
        open={mobileNavigationOpen}
        title="Navigate Prompt Enhancer"
      >
        <PrimaryNavigation
          activeDisclosureRef={mobileActiveDisclosureRef}
          activeItemRef={mobileActiveItemRef}
          ariaLabel="Mobile primary"
          idPrefix="mobile-navigation"
          onSelectItem={selectFromMobileNavigation}
          sections={navigationSections}
          variant="drawer"
        />
        <div className="mobile-navigation__footer">
          <ApplicationUpdateControl transport={transport} variant="drawer" />
          <p>Private local status · no automatic update traffic</p>
        </div>
      </Dialog>
    </div>
  );
}
