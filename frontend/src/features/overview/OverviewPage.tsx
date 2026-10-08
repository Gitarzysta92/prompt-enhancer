import { useEffect, useMemo, useState } from "react";
import type {
  CalibrationSample,
  CodexSession,
  JudgeAgreementReport,
  LocalModelsOverview,
  PromptCheckHistory,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import type { AppRoute } from "../../shared/platform/platform";
import type { RuntimeDataMode } from "../../shared/platform/runtimeMode";
import { Icon } from "../../shared/ui/Icon";
import {
  safeOnboardingStatus,
  type TruthfulOnboardingStatus,
} from "../onboarding/FirstRunPanel";
import "./OverviewPage.css";

const DAYS = 30;
const SESSION_PAGE = 100;
const MAX_SESSION_PAGES = 5;

type Loaded<T> = { state: "loading" } | { state: "ready"; value: T } | { state: "unavailable" };
type SessionHistory = { rows: CodexSession[]; complete: boolean };

type OverviewTransport = Omit<
  Pick<
    PromptEnhancerTransport,
    "getOnboardingStatus" | "listCodexSessions" | "getCalibrationSample" | "getModelJudgeAgreement" | "getLocalModels" | "getPromptCheckHistory"
  >,
  "getOnboardingStatus"
> & {
  getOnboardingStatus(signal?: AbortSignal): Promise<unknown>;
};

function useLoaded<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[]): Loaded<T> {
  const [value, setValue] = useState<Loaded<T>>({ state: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setValue({ state: "loading" });
    load(controller.signal)
      .then((result) => { if (!controller.signal.aborted) setValue({ state: "ready", value: result }); })
      .catch(() => { if (!controller.signal.aborted) setValue({ state: "unavailable" }); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return value;
}

function localModelHardwareFooter(models: Loaded<LocalModelsOverview>): string {
  if (models.state === "loading") return "checking hardware…";
  if (models.state === "unavailable") return "hardware unavailable";
  const hardware = models.value.hardware;
  if (!hardware.gpu_name) return "no GPU detected";
  const free = hardware.gpu_memory_free_mb;
  return `${hardware.gpu_name}${free !== null && free !== undefined ? ` · ${(free / 1024).toFixed(1)} GB VRAM free` : ""}`;
}

function promptCommentaryFooter(checks: Loaded<PromptCheckHistory>): string {
  if (checks.state === "loading") return "counting model commentary…";
  if (checks.state === "unavailable") return "commentary history unavailable";
  return `${checks.value.checks.filter((row) => row.commentary_state === "ok").length} with model commentary${checks.value.checks.length >= 60 ? " · latest 60 checks only" : ""}`;
}

function promptCheckCoverageSummary(checks: Loaded<PromptCheckHistory>, coverage: readonly number[]): string {
  if (checks.state === "loading") return "checking prompt history…";
  if (checks.state === "unavailable") return "prompt history unavailable";
  if (checks.value.checks.length === 0) return "no check yet";
  if (coverage.length === 0) return "task definition coverage unavailable";
  return `task definition ${Math.round((coverage.reduce((sum, value) => sum + value, 0) / coverage.length) * 100)}% on average`;
}

export function sessionsPerDay(sessions: readonly CodexSession[], days: number, now: Date): number[] {
  const counts = new Array<number>(days).fill(0);
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  for (const session of sessions) {
    const started = Date.parse(String(session.started_at));
    if (!Number.isFinite(started)) continue;
    const day = new Date(started);
    const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime();
    const offset = Math.round((end - dayStart) / 86_400_000);
    if (offset >= 0 && offset < days) counts[days - 1 - offset] += 1;
  }
  return counts;
}

export function Sparkline({ values, label, accent = "var(--chart-1)" }: { values: number[]; label: string; accent?: string }) {
  const width = 220;
  const height = 48;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 4 - (v / max) * (height - 8)).toFixed(1)}`);
  const area = `0,${height} ${points.join(" ")} ${width},${height}`;
  return (
    <svg aria-label={label} className="overview-spark" role="img" viewBox={`0 0 ${width} ${height}`}>
      <title>{label}</title>
      <polygon className="overview-spark__area" points={area} style={{ fill: accent }} />
      <polyline className="overview-spark__line" fill="none" points={points.join(" ")} style={{ stroke: accent }} />
      {values.length > 0 && <circle className="overview-spark__dot" cx={(values.length - 1) * step} cy={height - 4 - (values[values.length - 1] / max) * (height - 8)} r={3} style={{ fill: accent }} />}
    </svg>
  );
}

/**
 * Overview: what the app has done on its own, in one screen - sessions indexed and
 * analysed per provider, the calibration and judge state, the active local
 * model, prompt checks - with the next thing worth doing. Counts and states
 * only; everything links to the page that owns it.
 */
export function OverviewPage({
  navigate,
  transport,
  now = () => new Date(),
  runtimeMode = "synthetic_demo",
}: {
  navigate: (route: AppRoute) => void;
  transport: OverviewTransport;
  now?: () => Date;
  runtimeMode?: RuntimeDataMode;
}) {
  const onboarding = useLoaded<TruthfulOnboardingStatus>(async (signal) => {
    const value = await transport.getOnboardingStatus(signal);
    if (!safeOnboardingStatus(value)) throw new Error("invalid onboarding response");
    return value;
  }, [transport]);
  const sessions = useLoaded<SessionHistory>(async (signal) => {
    const all: CodexSession[] = [];
    let complete = false;
    for (let page = 0; page < MAX_SESSION_PAGES; page += 1) {
      const response = await transport.listCodexSessions(SESSION_PAGE, page * SESSION_PAGE, signal);
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (!Array.isArray(response.sessions) || response.sessions.length > SESSION_PAGE) throw new Error("invalid session page");
      all.push(...response.sessions);
      if (response.sessions.length < SESSION_PAGE) { complete = true; break; }
    }
    return { rows: all, complete };
  }, [transport]);
  const calibration = useLoaded<CalibrationSample>((signal) => transport.getCalibrationSample(null, signal), [transport]);
  const judge = useLoaded<JudgeAgreementReport>((signal) => transport.getModelJudgeAgreement(signal), [transport]);
  const models = useLoaded<LocalModelsOverview>((signal) => transport.getLocalModels(signal), [transport]);
  const checks = useLoaded<PromptCheckHistory>((signal) => transport.getPromptCheckHistory(60, 0, signal), [transport]);

  const perDay = useMemo(() => (sessions.state === "ready" ? sessionsPerDay(sessions.value.rows, DAYS, now()) : []), [sessions, now]);
  const recentCount = perDay.reduce((a, b) => a + b, 0);
  const providers = onboarding.state === "ready" ? onboarding.value.providers : [];
  const indexedCounts = providers.map((provider) => provider.indexed_sessions);
  const summedIndexedTotal = indexedCounts.length > 0
    && indexedCounts.every((count): count is number => count !== null)
    ? indexedCounts.reduce((sum, count) => sum + count, 0)
    : null;
  const indexedTotal = summedIndexedTotal !== null && Number.isSafeInteger(summedIndexedTotal)
    ? summedIndexedTotal
    : null;
  const indexedDetail = onboarding.state === "loading"
    ? "checking source counts…"
    : onboarding.state === "unavailable"
      ? "source counts unavailable"
      : providers
        .filter((p) => p.consent_active)
        .map((p) => {
          const label = p.provider === "claude_code" ? "Claude Code" : p.provider === "codex" ? "Codex" : p.provider;
          return `${label} ${p.indexed_sessions === null ? "count unavailable" : p.indexed_sessions}`;
        })
        .join(" · ") || "no source loaded yet";
  const activeModel = models.state === "ready" ? models.value.models.find((m) => m.runtime.state === "running") ?? null : null;
  const sampleMembers = calibration.state === "ready" ? calibration.value.members : [];
  const metricCount = calibration.state === "ready" ? calibration.value.metric_keys.length : 0;
  const fullyRated = sampleMembers.filter((m) => metricCount > 0 && m.rated_metric_keys.length >= metricCount).length;
  const judgedSessions = judge.state === "ready" ? judge.value.judged_sessions : 0;
  const agreementPairs = judge.state === "ready" ? judge.value.metrics.reduce((s, m) => s + m.pairs, 0) : 0;
  const checkRows = checks.state === "ready" ? checks.value.checks : [];
  const checkCoverage = checkRows
    .map((row) => row.metrics.find((m) => m.key === "prompt.task_definition_coverage"))
    .map((m) => (m && m.state === "known" && typeof m.value === "number" && Number.isFinite(m.value) && m.value >= 0 && m.value <= 1 ? m.value : null))
    .filter((v): v is number => v !== null);
  const checkSpark = [...checkRows].reverse().flatMap((row) => {
    const m = row.metrics.find((x) => x.key === "prompt.task_definition_coverage");
    return m && m.state === "known" && typeof m.value === "number" && Number.isFinite(m.value) && m.value >= 0 && m.value <= 1 ? [m.value] : [];
  });
  const settled = [onboarding, models, calibration, checks].every((item) => item.state !== "loading");

  const nextSteps: { text: string; route: AppRoute }[] = [];
  if (runtimeMode === "local_real" && onboarding.state === "ready" && onboarding.value.providers.some((p) => p.installed && !p.consent_active)) {
    nextSteps.push({ text: "A detected tool is not loaded yet - review local-source access before indexing its history.", route: { name: "local_sources" } });
  }
  if (!activeModel && models.state === "ready") {
    nextSteps.push({ text: "No local model is active: activate one so the judge and prompt commentary run.", route: { name: "models" } });
  }
  if (calibration.state === "ready" && fullyRated < Math.min(30, sampleMembers.length)) {
    nextSteps.push({ text: `Rate sessions blind (${fullyRated} of ${sampleMembers.length} fully rated) - every rating becomes a judge agreement pair.`, route: { name: "calibration" } });
  }
  if (checkRows.length === 0 && checks.state === "ready") {
    nextSteps.push({ text: "Check a prompt before you send it - the same cues the dashboard measures, plus the model's rewrite.", route: { name: "prompt_checks" } });
  }

  return (
    <section aria-labelledby="overview-title" className="overview">
      <header className="overview__head route-header">
        <div>
          <p className="eyebrow">Overview · this machine, today</p>
          <h1 id="overview-title">Overview</h1>
          <p className="overview__lede">
            A snapshot of indexed sessions, local models, calibration and prompt checks. Automatic work depends on your enabled sources and settings;
            nothing here is a score of a person, and unknown stays unknown. Each tile opens the page that owns it.
          </p>
        </div>
        {onboarding.state === "ready" && onboarding.value.last_refresh_at && (
          <p className="overview__refresh">Last refresh {new Date(onboarding.value.last_refresh_at).toLocaleString()}{onboarding.value.last_refresh_error ? " · last refresh reported an error" : ""}</p>
        )}
      </header>

      <div className="overview__tiles">
        <button className="overview-tile" onClick={() => navigate({ name: "sessions" })} type="button">
          <span className="overview-tile__label"><Icon name="layers" /> Sessions indexed</span>
          <strong className="overview-tile__value">
            {onboarding.state === "loading" ? "…" : onboarding.state === "unavailable" ? "—" : indexedTotal === null ? "Unknown" : indexedTotal}
          </strong>
          <span className="overview-tile__sub">
            {indexedDetail}
          </span>
          {sessions.state === "ready" && <Sparkline label={`Sessions per day, last ${DAYS} days (${recentCount}${sessions.value.complete ? "" : "; partial history"})`} values={perDay} />}
          <span className="overview-tile__foot">{sessions.state === "ready" ? `${sessions.value.complete ? "" : "At least "}${recentCount} in the last ${DAYS} days${sessions.value.complete ? "" : ` · first ${sessions.value.rows.length} sessions only`}` : sessions.state === "loading" ? "counting…" : "history unavailable"}</span>
        </button>

        <button className="overview-tile" onClick={() => navigate({ name: "calibration" })} type="button">
          <span className="overview-tile__label"><Icon name="check" /> Calibration</span>
          <strong className="overview-tile__value">{calibration.state === "ready" ? `${fullyRated}/${sampleMembers.length}` : calibration.state === "loading" ? "…" : "—"}</strong>
          <span className="overview-tile__sub">sessions fully rated by you</span>
          <div className="overview-tile__bar" aria-hidden="true"><span style={{ width: `${sampleMembers.length ? (fullyRated / sampleMembers.length) * 100 : 0}%` }} /></div>
          <span className="overview-tile__foot">
            {judge.state === "ready" && judge.value.model_alias
              ? `${judge.value.model_alias} judged ${judgedSessions} sessions · ${agreementPairs} agreement pairs`
              : judge.state === "ready"
                ? `${judgedSessions} sessions judged · no model active`
                : judge.state === "loading"
                  ? "checking judge lane…"
                  : "judge lane unavailable"}
          </span>
        </button>

        <button className="overview-tile" onClick={() => navigate({ name: "models" })} type="button">
          <span className="overview-tile__label"><Icon name="layers" /> Local model</span>
          <strong className="overview-tile__value overview-tile__value--text">{activeModel ? activeModel.record.display_name : models.state === "ready" ? "none active" : models.state === "loading" ? "…" : "unavailable"}</strong>
          <span className="overview-tile__sub">
            {activeModel ? `${activeModel.runtime.device ?? "device"}${activeModel.runtime.gpu_layers !== null && activeModel.runtime.gpu_layers !== undefined ? ` · ${activeModel.runtime.gpu_layers} GPU layers` : ""} · ${models.state === "ready" ? models.value.models.length : 0} installed` : models.state === "ready" ? `${models.value.models.length} installed` : ""}
          </span>
          <span className="overview-tile__foot">{localModelHardwareFooter(models)}</span>
        </button>

        <button className="overview-tile" onClick={() => navigate({ name: "prompt_checks" })} type="button">
          <span className="overview-tile__label"><Icon name="check" /> Prompt checks</span>
          <strong className="overview-tile__value">{checks.state === "ready" ? checkRows.length : checks.state === "loading" ? "…" : "—"}</strong>
          <span className="overview-tile__sub">
            {promptCheckCoverageSummary(checks, checkCoverage)}
          </span>
          {checkSpark.length > 1 && <Sparkline accent="var(--chart-2)" label="Task definition coverage across your checks" values={checkSpark} />}
          <span className="overview-tile__foot">{promptCommentaryFooter(checks)}</span>
        </button>
      </div>

      <section aria-labelledby="overview-next-title" className="overview__next">
        <h2 id="overview-next-title">Worth doing next</h2>
        {!settled ? (
          <p className="overview__note">Checking what is left to do…</p>
        ) : nextSteps.length === 0 ? (
          <p className="overview__note">{[onboarding, models, calibration, checks].some((item) => item.state === "unavailable")
            ? "Some checks are unavailable, so the app cannot confirm that everything is up to date. Open a tile to inspect its status."
            : runtimeMode === "synthetic_demo"
              ? "No suggested actions in this fixture. This preview does not index or judge real sessions."
              : "No suggested actions from the available checks. Automatic work follows your configured sources and settings."}</p>
        ) : (
          <ul>
            {nextSteps.map((step) => (
              <li key={step.text}>
                <button className="link-button" onClick={() => navigate(step.route)} type="button">{step.text}</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
