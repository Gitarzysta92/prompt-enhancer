import type { TeamMetricSuppressionReason } from "./teamControlPlaneSchema";

/**
 * Framework-free, in-memory disclosure guard used by synthetic fixtures.
 *
 * This is a deterministic test policy, not a production privacy mechanism.
 */
export type ContributionDisclosureState = "released" | "suppressed";

export interface ContributionDisclosureDecision {
  state: ContributionDisclosureState;
  suppressionReason: TeamMetricSuppressionReason | null;
}
export interface ContributionDisclosureQuery {
  /** Same metric/definition/window family whose overlapping releases can be differenced. */
  family: string;
  /** Immutable scope/window identity. Reusing it with different members fails closed. */
  queryId: string;
  contributorIds: readonly string[];
  minimumContributorCount: number;
}

interface ContributionDisclosureRecord {
  family: string;
  state: ContributionDisclosureState;
  suppressionReason: TeamMetricSuppressionReason | null;
  blockedByIdentityReuse: boolean;
  signature: string;
  contributors: ReadonlySet<string>;
  minimum: number;
}

/**
 * In-memory synthetic disclosure guard. Decisions are sticky by immutable
 * query identity, and a new overlapping release is suppressed whenever
 * subtracting either released set would expose a non-empty sub-k remainder.
 */
export class StickyContributionDisclosurePolicy {
  private readonly records = new Map<string, ContributionDisclosureRecord>();

  decide(query: ContributionDisclosureQuery): ContributionDisclosureDecision {
    const contributors = new Set(query.contributorIds);
    const signature = JSON.stringify([...contributors].sort());
    const key = JSON.stringify({ family: query.family, queryId: query.queryId });
    const existing = this.records.get(key);
    if (existing !== undefined) {
      if (existing.signature !== signature || existing.minimum !== query.minimumContributorCount) {
        existing.blockedByIdentityReuse = true;
      }
      return existing.blockedByIdentityReuse
        ? { state: "suppressed", suppressionReason: "query_identity_mismatch" }
        : { state: existing.state, suppressionReason: existing.suppressionReason };
    }
    let state: ContributionDisclosureState = contributors.size < query.minimumContributorCount
      ? "suppressed"
      : "released";
    let suppressionReason: TeamMetricSuppressionReason | null = state === "suppressed"
      ? "small_cohort"
      : null;
    if (state === "released") {
      for (const prior of this.records.values()) {
        if (prior.family !== query.family || prior.state !== "released") continue;
        const overlaps = [...contributors].some((id) => prior.contributors.has(id));
        if (!overlaps) continue;
        const currentOnly = [...contributors].filter((id) => !prior.contributors.has(id)).length;
        const priorOnly = [...prior.contributors].filter((id) => !contributors.has(id)).length;
        if (
          (currentOnly > 0 && currentOnly < query.minimumContributorCount)
          || (priorOnly > 0 && priorOnly < prior.minimum)
        ) {
          state = "suppressed";
          suppressionReason = "overlap_or_differencing";
          break;
        }
      }
    }
    this.records.set(key, {
      family: query.family,
      state,
      suppressionReason,
      blockedByIdentityReuse: false,
      signature,
      contributors,
      minimum: query.minimumContributorCount,
    });
    return { state, suppressionReason };
  }
}
