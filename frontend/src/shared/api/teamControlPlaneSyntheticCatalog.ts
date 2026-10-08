import {
  TEAM_REVIEWED_METRIC_CONTRACTS,
  type AnalyticsScope,
  type MetricDirection,
  type TeamControlPlanePort,
} from "./teamControlPlaneSchema";

/**
 * Content-free, frozen catalog used only by the synthetic team preview.
 *
 * Keeping fictional stories separate from the adapter makes it impossible for
 * local-real composition to import fixture cohort data by accident.
 */
export const FIXTURE_NOW = "2040-01-31T09:00:00Z";
export const WINDOW_START = "2040-01-01T00:00:00Z";
export const WINDOW_END = "2040-01-31T00:00:00Z";
export const STALE_AFTER_DAYS = 14;
export const MINIMUM_TEAM_MEMBERS = 3;
export const SYNTHETIC_COHORT_ID = "19".repeat(32);
export const SYNTHETIC_ME_COHORT_ID = "08".repeat(32);
export const SYNTHETIC_TEAM_ID = "2a".repeat(32);
export const SYNTHETIC_ORGANIZATION_ID = "3b".repeat(32);
export const SYNTHETIC_MEMBER_VISIBILITY_GRANT_ID = "4c".repeat(32);
export const SYNTHETIC_ME_QUERY_ID = "5d".repeat(32);
export const SYNTHETIC_TEAM_QUERY_ID = "6e".repeat(32);
export const SYNTHETIC_PRINCIPAL_ID = "7f".repeat(32);

export interface SyntheticMemberRevealAuditEvent {
  event: "member_visibility_revealed";
  occurred_at: string;
  destination: "local_audit_log";
  grant_reason: "granted_with_member_consent";
  principal_id: string;
  grant_id: string;
  scope: Exclude<AnalyticsScope, "me">;
  cohort_id: string;
  team_id: string | null;
  organization_id: string | null;
  returned_member_count: number;
  withheld_member_count: number;
}
export interface SyntheticTeamControlPlanePort extends TeamControlPlanePort {
  /** Content-free in-memory events for proving the fictional reveal is audited. */
  getRevealAuditEvents(): readonly SyntheticMemberRevealAuditEvent[];
}

export const SYNTHETIC_TEAM_COHORT_LABEL = "Synthetic platform guild (fixture cohort)";
export const SYNTHETIC_ME_COHORT_LABEL = "This installation only (fixture)";
export const SYNTHETIC_TEAM_WINDOW_LABEL = "Newest 30 days · fixture window";

/** Pseudonymous member identifiers: 64 lowercase hex characters each. */
export const SYNTHETIC_TEAM_MEMBER_IDS: readonly string[] = [
  "a1".repeat(32),
  "b2".repeat(32),
  "c3".repeat(32),
  "d4".repeat(32),
  "e5".repeat(32),
];

export interface MetricSeed {
  key: string;
  version: number;
  direction: MetricDirection;
}

/** Metric identities mirror the shipped coaching lens definitions (versions included). */
export const SYNTHETIC_TEAM_METRIC_SEEDS: readonly MetricSeed[] = [
  ...TEAM_REVIEWED_METRIC_CONTRACTS.map((contract) => ({
    key: contract.metric_key,
    version: contract.definition_version,
    direction: contract.direction,
  })),
];

export type MeasuredStory =
  | { kind: "known"; numerator: number; denominator: number; membersWithValue: number; staleMembers: number; oldest: string; newest: string }
  | { kind: "suppressed"; membersWithValue: number }
  | { kind: "withheld"; versions: readonly number[] }
  | { kind: "unknown" }
  | { kind: "not_applicable"; sessionsWithoutReceipt: 0 | null }
  | { kind: "abstained"; membersWithValue: number };

export interface ExperimentalStory {
  median: number;
  low: number;
  high: number;
}

/** Hand-authored fictional cohort story per metric key (team scope). */
export const TEAM_STORIES: Readonly<Record<string, MeasuredStory>> = {
  "prompt.task_definition_coverage": { kind: "known", numerator: 41, denominator: 57, membersWithValue: 5, staleMembers: 0, oldest: "2040-01-04T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.problem_evidence_quality": { kind: "known", numerator: 12, denominator: 28, membersWithValue: 3, staleMembers: 1, oldest: "2040-01-03T08:10:00Z", newest: "2040-01-29T11:05:00Z" },
  "prompt.context_sufficiency": { kind: "known", numerator: 33, denominator: 57, membersWithValue: 5, staleMembers: 0, oldest: "2040-01-04T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.constraint_precision": { kind: "suppressed", membersWithValue: 2 },
  "prompt.acceptance_testability": { kind: "known", numerator: 9, denominator: 31, membersWithValue: 4, staleMembers: 0, oldest: "2040-01-05T09:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.deliverable_contract": { kind: "withheld", versions: [1, 3] },
  "collaboration.ambiguity_resolution": { kind: "known", numerator: 14, denominator: 22, membersWithValue: 4, staleMembers: 0, oldest: "2040-01-06T12:00:00Z", newest: "2040-01-28T15:40:00Z" },
  "collaboration.clarification_yield": { kind: "known", numerator: 6, denominator: 9, membersWithValue: 3, staleMembers: 0, oldest: "2040-01-09T12:00:00Z", newest: "2040-01-27T10:15:00Z" },
  "collaboration.exploration_conversion": { kind: "not_applicable", sessionsWithoutReceipt: 0 },
  "collaboration.scope_change_discipline": { kind: "abstained", membersWithValue: 1 },
  "collaboration.rework_candidate_rate": { kind: "known", numerator: 7, denominator: 64, membersWithValue: 5, staleMembers: 0, oldest: "2040-01-04T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "logic.decomposition_coverage": { kind: "known", numerator: 19, denominator: 26, membersWithValue: 4, staleMembers: 0, oldest: "2040-01-05T09:00:00Z", newest: "2040-01-29T11:05:00Z" },
  "logic.decision_rationale_coverage": { kind: "unknown" },
  "logic.open_loop_closure": { kind: "known", numerator: 21, denominator: 30, membersWithValue: 5, staleMembers: 2, oldest: "2040-01-02T08:00:00Z", newest: "2040-01-25T09:30:00Z" },
  "outcome.verification_strategy_adequacy": { kind: "known", numerator: 15, denominator: 26, membersWithValue: 4, staleMembers: 0, oldest: "2040-01-05T09:00:00Z", newest: "2040-01-29T11:05:00Z" },
  "logic.hypothesis_test_linkage": { kind: "unknown" },
  "logic.requirement_action_traceability": { kind: "known", numerator: 24, denominator: 33, membersWithValue: 5, staleMembers: 0, oldest: "2040-01-04T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "outcome.agent_claim_grounding": { kind: "known", numerator: 40, denominator: 118, membersWithValue: 5, staleMembers: 0, oldest: "2040-01-04T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "outcome.first_pass_verification": { kind: "known", numerator: 11, denominator: 17, membersWithValue: 4, staleMembers: 1, oldest: "2040-01-03T08:10:00Z", newest: "2040-01-28T15:40:00Z" },
  "outcome.verified_requirement_coverage": { kind: "known", numerator: 13, denominator: 33, membersWithValue: 4, staleMembers: 0, oldest: "2040-01-05T09:00:00Z", newest: "2040-01-30T16:20:00Z" },
};

/** Experimental model ranges exist only where a fictional model projection ran; they never replace a measured row. */
export const TEAM_EXPERIMENTAL: Readonly<Record<string, ExperimentalStory>> = {
  "prompt.task_definition_coverage": { median: 0.69, low: 0.55, high: 0.81 },
  "logic.decision_rationale_coverage": { median: 0.44, low: 0.31, high: 0.58 },
  "logic.hypothesis_test_linkage": { median: 0.52, low: 0.34, high: 0.69 },
};

/** Personal (single-installation) story; smaller denominators, no suppression floor. */
export const ME_STORIES: Readonly<Record<string, MeasuredStory>> = {
  "prompt.task_definition_coverage": { kind: "known", numerator: 7, denominator: 9, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.problem_evidence_quality": { kind: "known", numerator: 3, denominator: 8, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-29T11:05:00Z" },
  "prompt.context_sufficiency": { kind: "known", numerator: 5, denominator: 9, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.constraint_precision": { kind: "known", numerator: 2, denominator: 5, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.acceptance_testability": { kind: "known", numerator: 1, denominator: 6, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "prompt.deliverable_contract": { kind: "known", numerator: 4, denominator: 7, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "collaboration.ambiguity_resolution": { kind: "known", numerator: 3, denominator: 4, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-12T12:00:00Z", newest: "2040-01-28T15:40:00Z" },
  "collaboration.clarification_yield": { kind: "not_applicable", sessionsWithoutReceipt: null },
  "collaboration.exploration_conversion": { kind: "not_applicable", sessionsWithoutReceipt: null },
  "collaboration.scope_change_discipline": { kind: "abstained", membersWithValue: 0 },
  "collaboration.rework_candidate_rate": { kind: "known", numerator: 2, denominator: 11, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "logic.decomposition_coverage": { kind: "known", numerator: 5, denominator: 5, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-29T11:05:00Z" },
  "logic.decision_rationale_coverage": { kind: "unknown" },
  "logic.open_loop_closure": { kind: "known", numerator: 4, denominator: 6, membersWithValue: 1, staleMembers: 1, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-15T09:30:00Z" },
  "outcome.verification_strategy_adequacy": { kind: "known", numerator: 3, denominator: 5, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-29T11:05:00Z" },
  "logic.hypothesis_test_linkage": { kind: "unknown" },
  "logic.requirement_action_traceability": { kind: "known", numerator: 6, denominator: 7, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "outcome.agent_claim_grounding": { kind: "known", numerator: 9, denominator: 21, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
  "outcome.first_pass_verification": { kind: "known", numerator: 0, denominator: 3, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-28T15:40:00Z" },
  "outcome.verified_requirement_coverage": { kind: "known", numerator: 3, denominator: 7, membersWithValue: 1, staleMembers: 0, oldest: "2040-01-08T10:00:00Z", newest: "2040-01-30T16:20:00Z" },
};

export const ME_EXPERIMENTAL: Readonly<Record<string, ExperimentalStory>> = {
  "logic.decision_rationale_coverage": { median: 0.41, low: 0.22, high: 0.63 },
};

export interface FixtureCohort {
  members: number;
  sessions: number;
  minimum: number;
}
