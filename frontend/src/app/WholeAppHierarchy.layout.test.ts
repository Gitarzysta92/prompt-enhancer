import { describe, expect, it } from "vitest";
import appCss from "../styles.css?raw";
import primitivesCss from "../shared/ui/primitives.css?raw";
import themeCss from "./theme.css?raw";
import appSource from "./App.tsx?raw";
import { APP_ROUTE_MANIFEST } from "./appRouteManifest";
import discoverySource from "../features/discovery-inbox/DiscoveryInbox.tsx?raw";
import overviewSource from "../features/overview/OverviewPage.tsx?raw";
import projectCatalogSource from "../features/project-catalog/ProjectCatalog.tsx?raw";
import sessionsSource from "../features/session-catalog/SessionsPage.tsx?raw";
import taskFlowSource from "../features/task-flow/TaskFlowPage.tsx?raw";
import promptCheckSource from "../features/prompt-check/PromptCheckPage.tsx?raw";
import calibrationSource from "../features/calibration/CalibrationPage.tsx?raw";
import localModelsSource from "../features/local-models/LocalModelsPage.tsx?raw";
import localSourcesSource from "../features/local-sources/LocalSources.tsx?raw";
import analysisJobsSource from "../features/analysis-job-centre/AnalysisJobCentre.tsx?raw";
import researchSource from "../features/research-lab/ResearchLab.tsx?raw";
import teamSource from "../features/team-analytics/TeamAnalyticsPage.tsx?raw";
import socialSource from "../features/social/SocialHubPage.tsx?raw";
import automationSource from "../features/project-automation/ProjectAutomationSettings.tsx?raw";
import projectWorkspaceSource from "../features/project-workspace/ProjectWorkspace.tsx?raw";
import liveWindowSource from "../features/live-window/LiveMiniWindow.tsx?raw";
import taskSummarySource from "../entities/task/TaskSummary.tsx?raw";
import taskDetailSource from "../features/task-detail/TaskDetail.tsx?raw";
import overviewCss from "../features/overview/OverviewPage.css?raw";
import promptCheckCss from "../features/prompt-check/PromptCheckPage.css?raw";
import calibrationCss from "../features/calibration/CalibrationPage.css?raw";
import localModelsCss from "../features/local-models/LocalModelsPage.css?raw";
import sessionsCss from "../features/session-catalog/Sessions.css?raw";
import taskFlowCss from "../features/task-flow/TaskFlow.css?raw";
import teamCss from "../features/team-analytics/TeamAnalytics.css?raw";
import socialCss from "../features/social/SocialHub.css?raw";
import metricOperabilityCss from "../features/research-lab/MetricOperabilityPanel.css?raw";

const ROUTE_HEADER_SOURCES = {
  appSource,
  discoverySource,
  overviewSource,
  projectCatalogSource,
  sessionsSource,
  taskFlowSource,
  promptCheckSource,
  calibrationSource,
  localModelsSource,
  localSourcesSource,
  analysisJobsSource,
  researchSource,
  teamSource,
  socialSource,
  automationSource,
  projectWorkspaceSource,
  liveWindowSource,
  taskSummarySource,
  taskDetailSource,
} as const;

const STANDALONE_ROUTE_CSS = [
  overviewCss,
  promptCheckCss,
  calibrationCss,
  localModelsCss,
  sessionsCss,
  taskFlowCss,
  teamCss,
  socialCss,
];

const UI_SOURCE_TEXT = Object.values(import.meta.glob("../**/*.tsx", {
  eager: true,
  import: "default",
  query: "?raw",
}) as Record<string, string>).join("\n");

describe("whole-application hierarchy contract", () => {
  it("keeps every top-level non-Agent h1 inside the shared route header", () => {
    for (const [name, source] of Object.entries(ROUTE_HEADER_SOURCES)) {
      const h1Count = source.match(/<h1\b/g)?.length ?? 0;
      const routeHeaderBlocks = [...source.matchAll(
        /<header className="[^"]*\broute-header\b[^"]*"[\s\S]*?<\/header>/g,
      )];
      const ownedH1Count = routeHeaderBlocks.reduce(
        (count, match) => count + (match[0].match(/<h1\b/g)?.length ?? 0),
        0,
      );

      expect(ownedH1Count, name).toBe(h1Count);
    }
  });

  it("gives standalone routes the same bounded gutter and section rhythm", () => {
    expect(appCss).toMatch(/--route-content-max:\s*97\.5rem;/);
    expect(appCss).toMatch(/--route-inline:\s*clamp\(1rem,\s*3vw,\s*2\.5rem\);/);
    expect(appCss).toMatch(/--route-section-gap:\s*clamp\(1rem,\s*2vw,\s*1\.5rem\);/);

    for (const css of STANDALONE_ROUTE_CSS) {
      expect(css).toContain("max-width: var(--route-content-max)");
      expect(css).toContain("padding: var(--route-block-start) var(--route-inline) var(--route-block-end)");
    }
  });

  it("uses one readable metadata and action floor outside the Agent", () => {
    expect(appCss).toMatch(/--type-caption:\s*0\.75rem;/);
    expect(appCss).toMatch(/--touch-target:\s*2\.75rem;/);
    expect(appCss).toMatch(/\.workspace:not\(\[data-route="agent"\]\):not\(\[data-route="team"\]\):not\(\[data-route="task_flow"\]\):not\(\[data-route="social"\]\) main :where\([\s\S]*?small,[\s\S]*?font-size:\s*max\(var\(--type-caption\),\s*0\.85em\) !important;/);
    expect(appCss).toMatch(/\.workspace:not\(\[data-route="agent"\]\) main :where\([\s\S]*?button,[\s\S]*?min-height:\s*var\(--touch-target\);/);
    expect(appCss).toMatch(/main :where\(button, a\[href\], summary, \[role="button"\], \[role="tab"\]\)\s*\{[^}]*min-width:\s*var\(--touch-target\);/);
    expect(appCss).toMatch(/\.analysis-job-card__topline time,[\s\S]*?font-size:\s*var\(--type-caption\) !important;/);
    expect(appCss).toMatch(/\.status-pill\s*\{[^}]*font-size:\s*var\(--type-caption\);/);
    expect(appCss).toMatch(/\.button\s*\{[^}]*min-height:\s*var\(--touch-target\);[^}]*font-size:\s*var\(--type-label\);/);
    expect(primitivesCss).toMatch(/\.ui-tabs__tab\s*\{[^}]*min-height:\s*var\(--touch-target\);[^}]*font-size:\s*var\(--type-label\);/);
    expect(primitivesCss).toMatch(/\.ui-disclosure__trigger\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
  });

  it("keeps audited legacy metadata and shell actions on the shared accessibility floors", () => {
    for (const selector of [
      "candidate-card__open",
      "coverage__label",
      "coverage__caption",
      "count-badge",
      "evidence-item__code",
      "evidence-item__meta",
      "project-catalog-card__select",
      "project-catalog__boundary",
      "snapshot-boundary p",
      "metric-card__eyebrow",
      "metric-card__question",
      "metric-card__detail",
    ]) {
      expect(appCss, selector).toMatch(new RegExp(`\\.${selector.replace(" ", "\\s+")}[^}]*font-size:\\s*var\\(--type-caption\\);`));
    }

    expect(sessionsCss).toMatch(/\.sessions-count\s*\{[^}]*font-size:\s*var\(--type-caption\);/);
    expect(sessionsCss).toMatch(/\.session-row__meta\s*\{[^}]*font-size:\s*var\(--type-caption\);/);
    expect(metricOperabilityCss).toMatch(/\.metric-operability__group li > span\s*\{[^}]*font-size:\s*var\(--type-caption\);/);
    expect(taskFlowCss).toMatch(/\.task-flow-card footer \.button\s*\{[^}]*min-width:\s*var\(--touch-target\);[^}]*min-height:\s*var\(--touch-target\);/);
    expect(themeCss).toMatch(/\.theme-toggle\s*\{[^}]*min-width:\s*var\(--touch-target\);[^}]*height:\s*var\(--touch-target\);[^}]*font-size:\s*var\(--type-caption\);/);
  });

  it("keeps shell, navigation, and route headings on one vocabulary", () => {
    expect(APP_ROUTE_MANIFEST.local_sources.title).toBe("Data sources");
    expect(APP_ROUTE_MANIFEST.analysis_jobs.title).toBe("Analysis jobs");
    expect(APP_ROUTE_MANIFEST.research.title).toBe("Methods & models");
    expect(APP_ROUTE_MANIFEST.team.title).toBe("Team analytics");
    expect(appSource).toContain('label: "Data sources"');
    expect(appSource).toContain('label: "Analysis jobs"');
    expect(localSourcesSource).toContain("<h1>Data sources</h1>");
    expect(analysisJobsSource.match(/>Analysis jobs<\/h1>/g)).toHaveLength(3);
    expect(researchSource).toContain("<h1 tabIndex={-1}>Methods &amp; models</h1>");
    expect(teamSource).toContain('<h1 id="team-analytics-title">Team analytics</h1>');
    expect(UI_SOURCE_TEXT).not.toMatch(/\b(?:Local sources|Data source|Job centre|Analysis Job Centre)\b/);
  });

  it("assigns one distinct icon to every primary navigation destination", () => {
    const iconBlock = appSource.match(
      /const PRIMARY_NAV_ICONS = \{([\s\S]*?)\} as const satisfies/,
    )?.[1];
    expect(iconBlock).toBeDefined();

    const iconNames = [...(iconBlock ?? "").matchAll(/\w+:\s*"([^"]+)"/g)]
      .map((match) => match[1]);
    expect(iconNames).toHaveLength(15);
    expect(new Set(iconNames).size).toBe(iconNames.length);
  });
});
