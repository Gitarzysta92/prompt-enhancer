import { useEffect, useMemo, useRef } from "react";
import type { ProjectQualityAggregate } from "../../shared/api/contracts";
import { Icon } from "../../shared/ui/Icon";
import {
  createProjectAggregateQualityMetricProfile,
  type QualityMetricProfile,
} from "../quality-profile";
import { QualityRadar } from "../quality-profile/QualityRadar";

type ComparisonLens = "prompt-quality" | "reasoning";

export interface ResolvedProjectComparison {
  aggregate: ProjectQualityAggregate;
  profiles: Readonly<Record<ComparisonLens, QualityMetricProfile>>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => actual.includes(key));
}

function isRenderableProfile(profile: QualityMetricProfile | null): profile is QualityMetricProfile {
  return (
    profile !== null &&
    (profile.latest.integrity === "coherent" ||
      profile.latest.integrity === "unavailable") &&
    profile.latest.scope !== null
  );
}

/**
 * Treat the transport result as hostile. The existing aggregate mapper owns the
 * deep metric/provenance contract; this boundary additionally validates the
 * identifier-free project wrapper and rejects mixed or incompatible profiles.
 */
export function resolveProjectComparison(
  value: unknown,
  expectedProjectCount: number,
): ResolvedProjectComparison | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "aggregation_method",
      "estimand",
      "selected_project_count",
      "selection_mode",
      "session_quality",
    ]) ||
    value.aggregation_method !== "ratio_of_sums" ||
    value.estimand !== "per_eligible_opportunity" ||
    value.selection_mode !== "all_analyzed_work" ||
    !Number.isSafeInteger(value.selected_project_count) ||
    value.selected_project_count !== expectedProjectCount ||
    expectedProjectCount < 1 ||
    expectedProjectCount > 25 ||
    !isRecord(value.session_quality) ||
    value.session_quality.integrity_state === "incompatible"
  ) {
    return null;
  }

  const aggregate = value as unknown as ProjectQualityAggregate;
  const prompt = createProjectAggregateQualityMetricProfile(
    "prompt-quality",
    aggregate.session_quality,
  );
  const reasoning = createProjectAggregateQualityMetricProfile(
    "reasoning",
    aggregate.session_quality,
  );
  if (!isRenderableProfile(prompt) || !isRenderableProfile(reasoning)) {
    return null;
  }
  const promptScope = prompt.latest.scope;
  const reasoningScope = reasoning.latest.scope;
  if (promptScope === null || reasoningScope === null) return null;
  if (
    promptScope.selectedSessions !== aggregate.session_quality.selected_session_count ||
    reasoningScope.selectedSessions !==
      aggregate.session_quality.selected_session_count
  ) {
    return null;
  }

  return {
    aggregate,
    profiles: {
      "prompt-quality": prompt,
      reasoning,
    },
  };
}

export function ProjectComparison({
  comparison,
  onBack,
}: {
  comparison: ResolvedProjectComparison;
  onBack: () => void;
}) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const scope = comparison.aggregate.session_quality;
  const metrics = useMemo(
    () =>
      (Object.values(comparison.profiles) as QualityMetricProfile[])
        .filter((profile) => profile.latest.integrity === "coherent")
        .flatMap((profile) => profile.latest.metrics),
    [comparison],
  );

  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Combined project signals · Prompt Enhancer";
    titleRef.current?.focus();
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <section className="project-comparison" aria-labelledby="project-comparison-title">
      <header className="project-comparison__header">
        <button className="project-comparison__back" onClick={onBack} type="button">
          <Icon name="chevron" />
          Back to projects
        </button>
        <div>
          <p className="eyebrow">Local aggregate</p>
          <h1 id="project-comparison-title" ref={titleRef} tabIndex={-1}>
            Combined project signal profile
          </h1>
          <p>
            Content-free aggregate metrics only. No provider history is read by this
            aggregate.
          </p>
        </div>
      </header>

      <div className="project-comparison__contract" role="note">
        <Icon name="lock" />
        <span>
          <strong>All analyzed work · per eligible opportunity · ratio of sums</strong>
          <small>Percentages are combined by the server; the browser never averages them.</small>
        </span>
      </div>

      <dl className="project-comparison__counts" aria-label="Combined profile coverage">
        <div><dt>Projects</dt><dd>{comparison.aggregate.selected_project_count}</dd></div>
        <div><dt>Sessions</dt><dd>{scope.selected_session_count}</dd></div>
        <div><dt>Completed</dt><dd>{scope.completed_run_count}</dd></div>
        <div><dt>Missing</dt><dd>{scope.missing_run_count}</dd></div>
      </dl>

      {metrics.length === 0 ? (
        <div className="project-comparison__empty" role="note">
          <Icon name="activity" />
          <div>
            <strong>No compatible completed analysis is available</strong>
            <span>Missing work remains unknown and is never converted to zero.</span>
          </div>
        </div>
      ) : (
        <QualityRadar metrics={metrics} />
      )}
    </section>
  );
}
