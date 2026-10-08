import type { AnalyticsScope } from "../../shared/api/teamControlPlaneSchema";

/**
 * Per-metric context shown inside every knowledge/explainer card, in full and
 * compact modes alike: which analytics scope the number belongs to, who
 * contributed to it, whether a model estimate is involved, and what evidence
 * authority backs it. Each fact is a complete sentence fragment; `null` renders
 * as "Not reported" rather than disappearing, so absent context can never be
 * mistaken for "nothing to say". Pure types and constants only; the React
 * renderer lives in `MetricContextFactList.tsx`.
 */
export interface MetricScopeContext {
  scope: AnalyticsScope;
  /** e.g. "Me · this installation" or "Team · Synthetic platform guild (fixture cohort)". */
  label: string;
  description: string;
}

export interface MetricContextFacts extends MetricScopeContext {
  contributors: string | null;
  model: string | null;
  evidence: string | null;
}

export const ME_SCOPE_CONTEXT: MetricScopeContext = {
  scope: "me",
  label: "Me · this installation",
  description: "Your own sessions on this installation; no cohort, no member rows, nothing synced.",
};

export const SCOPE_CONTEXT_LABELS: Readonly<Record<AnalyticsScope, string>> = {
  me: "Me",
  team: "Team",
  organization: "Organization",
};
