import type { MetricPublicationV2 } from "../../shared/api/metricPublicationV2Contract";
import { metricDecisionGuidance, sessionMetricGuidance } from "../quality-profile/metricGuidance";
import { QUALITY_ANALYSIS_DEFINITIONS } from "../quality-profile/qualityProfile";

/**
 * Canonical, versioned presentation registry for the twenty workspace metrics.
 *
 * Two layers are kept visibly separate:
 * - `entry` explains the immutable definition selected by the sealed
 *   projection: frozen candidate copy before each semantic change, explicit
 *   PLAN lifecycle copy from r3, confirmed lifecycle copy from r4, and
 *   reviewed-profile copy for the three r5 contracts inherited by r6, plus
 *   the r6 reviewed requirement-plan denominator.
 * - `measurement` documents the corresponding shipped measurement. Canonical
 *   state and evidence authority still come from the exact V2 receipt; help
 *   copy never overrides those receipt facts.
 *
 * Presentation copy only: it never changes a persisted value, never invents
 * transcript-specific evidence, and keeps measured evidence separate from model
 * judgments. The current UI requests English; exact Polish entries remain
 * available to the resolver for a future locale signal and contract tests.
 */
export const METRIC_HELP_V2_VERSION = "metric-help-v2.5.0";
export const METRIC_HELP_V2_SHIPPED_LOCALES = ["en"] as const;

const DECLARED_TASK_PROFILE_METRIC_KEYS = new Set([
  "prompt.constraint_precision",
  "prompt.acceptance_testability",
  "prompt.deliverable_contract",
]);

export type MetricHelpLocale = "en" | "pl";
export type MetricHelpDirection = "higher_is_better" | "lower_is_better";
export type MetricHelpProjectionVersion = MetricPublicationV2["projection_version"];

export interface MetricHelpEntry {
  /** One sentence: what the projection-selected definition measures. */
  meaning: string;
  question: string;
  observationUnit: string;
  direction: string;
  counts: string;
  doesNotCount: string;
  /** Objective-evidence requirement, or an explicit statement that the value is a candidate, not proof. */
  objectiveEvidence: string;
}

export interface MetricHelpMeasurement {
  /** Version of the shipped coaching definition whose receipts are displayed. */
  definitionVersion: number;
  method: string;
  limitation: string;
  /** True when a typed/objective receipt is required and prose abstains. */
  objective: boolean;
}

interface MetricHelpSeed {
  key: string;
  direction: MetricHelpDirection;
  objective: boolean;
  en: MetricHelpEntry;
  pl: MetricHelpEntry;
}

const TEXT_CANDIDATE_EN = "No objective receipt backs the candidate value; it is a versioned lexical review candidate and never proof of quality or task success.";
const TEXT_CANDIDATE_PL = "Wartości kandydackiej nie potwierdza żadne obiektywne pokwitowanie; to wersjonowany leksykalny kandydat do przeglądu, nigdy dowód jakości ani sukcesu zadania.";
const TYPED_EVIDENCE_EN = "Requires a typed local tool, test, artifact, or verification receipt; without one the metric abstains and assistant prose is never counted.";
const TYPED_EVIDENCE_PL = "Wymaga typowanego lokalnego pokwitowania narzędzia, testu, artefaktu lub weryfikacji; bez niego metryka wstrzymuje ocenę, a proza asystenta nigdy nie jest liczona.";
const VERIFIED_REQUIREMENT_EVIDENCE_EN = "Requires either an app-issued typed passing-verification receipt or separately typed explicit native human acceptance for the requirement; assistant completion claims and other prose never count as either authority.";
const VERIFIED_REQUIREMENT_EVIDENCE_PL = "Wymaga typowanego pokwitowania zaliczonej weryfikacji wystawionego przez aplikację albo osobno typowanej, jawnej natywnej akceptacji człowieka dla wymagania; deklaracje ukończenia i inna proza asystenta nigdy nie stanowią żadnego z tych uprawnień.";
const HIGHER_EN = "Higher is better (radar plots the raw share).";
const HIGHER_PL = "Wyżej znaczy lepiej (radar pokazuje surowy udział).";
const LOWER_EN = "Lower is better (radar plots 100% minus the raw rate; the center is a raw rate of 100%).";
const LOWER_PL = "Niżej znaczy lepiej (radar pokazuje 100% minus surowy wskaźnik; środek oznacza surowy wskaźnik 100%).";
const R3_PROJECTION: MetricHelpProjectionVersion = "metric-contract-v2-projection-3";
const R4_PROJECTION: MetricHelpProjectionVersion = "metric-contract-v2-projection-4";
const R5_PROJECTION: MetricHelpProjectionVersion = "metric-contract-v2-projection-5";
const R6_PROJECTION: MetricHelpProjectionVersion = "metric-contract-v2-projection-6";
const R7_PROJECTION: MetricHelpProjectionVersion = "metric-contract-v2-projection-7";
const R8_PROJECTION: MetricHelpProjectionVersion = "metric-contract-v2-projection-8";
const R3_PLUS_PROJECTIONS = new Set<MetricHelpProjectionVersion>([
  R3_PROJECTION,
  R4_PROJECTION,
  R5_PROJECTION,
  R6_PROJECTION,
  R7_PROJECTION,
  R8_PROJECTION,
]);
const R4_PLUS_PROJECTIONS = new Set<MetricHelpProjectionVersion>([
  R4_PROJECTION,
  R5_PROJECTION,
  R6_PROJECTION,
  R7_PROJECTION,
  R8_PROJECTION,
]);
const R5_PLUS_PROJECTIONS = new Set<MetricHelpProjectionVersion>([
  R5_PROJECTION,
  R6_PROJECTION,
  R7_PROJECTION,
  R8_PROJECTION,
]);
const REVIEWED_PROFILE_EVIDENCE_EN = "The value is a deterministic local, method-only comparison between the immutable reviewed task-profile revision and the canonical active user request; it is neither a model judgment nor objective proof of quality or task success.";
const EXPLICIT_PLAN_EVIDENCE_EN = "The value comes from deterministic provider-declared message kinds and explicit supersedes_message_ids links in the bounded local window; no lexical similarity or model judgment supplies a closure, and the structural receipt is not objective proof that the plan or result was correct.";
const CONFIRMED_LIFECYCLE_EVIDENCE_EN = "Only content-free lifecycle records explicitly confirmed by an authenticated local user can supply the enumeration, opportunity, and family-specific outcome link; proposals, model judgments, and transcript wording alone are not evidence, and the confirmation is not objective test proof of task success.";
const REVIEWED_REQUIREMENT_PLAN_EVIDENCE_EN = "Only a complete native review that classifies every reviewable user request/feedback clause as active or excluded can establish the opportunity set; only active requirement clauses supply this denominator and its dispositions. One active coordinate is one opportunity: a compound active clause remains one opportunity and may coarsen multiple atomic requirements. Exclusions use the closed reason-and-basis rubric and never enter the metric. Coordinates are revalidated against the exact local source window; proposals, model judgments, transcript wording, and owned-native confirmation alone are not objective proof that a plan is adequate.";
const REVIEWED_REQUIREMENT_ACTION_EVIDENCE_EN = "Only a complete native review bound to the exact r6 requirement authority and the complete application-issued safe-action candidate enumeration can establish requirement-to-action links. The review must display every active requirement clause, every candidate and its ephemeral redacted descriptor, every proposed membership, and every explicit empty link. The person must cross-check each safe-event reference in the selected session timeline: coarse metadata, a producer proposal, native confirmation, or an application-issued action state alone is not proof of semantic relevance, objective task success, or quality.";

/**
 * Projection r5 changed the denominator contract for these receipt surfaces.
 * The base registry below remains the frozen r1-r4 presentation; selecting r5
 * or r6 replaces only these three entries and never rewrites a historical receipt.
 */
export const METRIC_HELP_V2_R5_PROFILE_EN: Readonly<Record<string, MetricHelpEntry>> = {
  "prompt.constraint_precision": {
    meaning: "Share of the exact constraint-kind slots declared in the reviewed task profile whose matching versioned cue appears in the canonical active user request.",
    question: "For each expected constraint kind in the reviewed profile, does the canonical active user request contain its matching versioned cue?",
    observationUnit: "one expected constraint-kind slot in the reviewed task profile",
    direction: HIGHER_EN,
    counts: "Numerator: one configured expected constraint kind whose matching versioned cue appears in the canonical active user request; each configured kind counts at most once.",
    doesNotCount: "Denominator: exactly the configured expected_constraint_kinds slots, not detected constraint clauses. Unconfigured kinds, cues outside the canonical active request, superseded requests, and agent prose do not count; no configured slots yields Unknown, never zero.",
    objectiveEvidence: REVIEWED_PROFILE_EVIDENCE_EN,
  },
  "prompt.acceptance_testability": {
    meaning: "Share of the exact expected-outcome slots declared in the reviewed task profile filled by distinct normalized checkable requirement clauses owned by the canonical active user request, capped at the declared count.",
    question: "How many reviewed expected-outcome slots are filled by distinct checkable requirement clauses in the canonical active user request?",
    observationUnit: "one expected-outcome slot in the reviewed task profile",
    direction: HIGHER_EN,
    counts: "Numerator: one slot per distinct normalized, non-question requirement clause in the canonical active user request that has an action-or-requirement cue and a recognized observable-check cue, capped at expected_outcome_count.",
    doesNotCount: "Denominator: exactly expected_outcome_count, not detected requirement clauses. Duplicate normalized clauses, questions, clauses outside the canonical active request, superseded requests, and checks added by the agent do not add slots; no declared count yields Unknown, never zero.",
    objectiveEvidence: REVIEWED_PROFILE_EVIDENCE_EN,
  },
  "prompt.deliverable_contract": {
    meaning: "Share of the exact deliverable slots declared in the reviewed task profile whose matching versioned cue appears in the canonical active user request.",
    question: "For each expected deliverable slot in the reviewed profile, does the canonical active user request contain its matching versioned cue?",
    observationUnit: "one expected deliverable slot in the reviewed task profile",
    direction: HIGHER_EN,
    counts: "Numerator: one configured expected deliverable slot whose matching versioned cue appears in the canonical active user request; each configured slot counts at most once.",
    doesNotCount: "Denominator: exactly the configured expected_deliverable_slots, not detected deliverable clauses. Unconfigured slots, cues outside the canonical active request, superseded requests, and agent prose do not count; no configured slots yields Unknown, never zero.",
    objectiveEvidence: REVIEWED_PROFILE_EVIDENCE_EN,
  },
};

export const METRIC_HELP_V2_R6_REQUIREMENT_PLAN_EN: Readonly<Record<string, MetricHelpEntry>> = {
  "logic.decomposition_coverage": {
    meaning: "Share of the exact active requirement clauses in the native-confirmed complete user-clause classification whose disposition links them to at least one valid later agent PLAN clause.",
    question: "For each native-reviewed active requirement clause, does its reviewed disposition link it to at least one valid later agent PLAN clause?",
    observationUnit: "one native-reviewed active requirement clause",
    direction: HIGHER_EN,
    counts: "Numerator: one native-reviewed active requirement clause with disposition linked and at least one reviewed plan index whose coordinate resolves to an agent PLAN clause at or after that clause.",
    doesNotCount: "Denominator: exactly the active_requirement clauses from the complete native-confirmed classification of every reviewable user request/feedback clause, not every candidate clause, excluded clauses, atomic requirements, or lexically detected requirements. One active coordinate is one opportunity: a compound active clause remains one opportunity and may coarsen multiple atomic requirements. not_linked is resolved not-met; pending stays right-censored. Proposed, rejected, unconfirmed, out-of-window, wrong-role, or invalid coordinates do not count. No confirmed active requirements yields Not applicable; missing or invalid review authority stays Unknown, never zero.",
    objectiveEvidence: REVIEWED_REQUIREMENT_PLAN_EVIDENCE_EN,
  },
};

export const METRIC_HELP_V2_R7_REQUIREMENT_ACTION_EN: Readonly<Record<string, MetricHelpEntry>> = {
  "logic.requirement_action_traceability": {
    meaning: "Share of the exact native-reviewed active r6 requirement clauses linked to at least one application-issued safe action candidate whose application-issued state is completed.",
    question: "For each reviewed active requirement clause, does the complete native-reviewed graph link a semantically relevant application-issued candidate that completed?",
    observationUnit: "one native-reviewed active requirement clause",
    direction: HIGHER_EN,
    counts: "Numerator: one reviewed active requirement with at least one linked candidate in application-issued completed state. With no completed candidate, a linked started or unknown state stays right-censored pending.",
    doesNotCount: "Denominator: exactly the active requirements from the bound r6 review, not detected prose or producer-created requirements. An explicit empty link, or failed/cancelled-only links, is resolved not-met only after complete requirement enumeration, complete safe-candidate enumeration, complete link classification, and exact native review. Missing, stale, incomplete, invalid, or overflowing authority remains Unknown; an exact empty requirement set is Not applicable; neither state is zero.",
    objectiveEvidence: REVIEWED_REQUIREMENT_ACTION_EVIDENCE_EN,
  },
};

export const METRIC_HELP_V2_R8_REQUIREMENT_VERIFICATION_EN: Readonly<Record<string, MetricHelpEntry>> = {
  "outcome.verified_requirement_coverage": {
    meaning: "Share of the exact native-reviewed active r6 requirements resolved as met by app-issued passing verification results or separately typed explicit native human acceptance.",
    question: "For each reviewed active requirement, does exact local authority record a passing app-issued verification result or separately typed native human acceptance?",
    observationUnit: "one native-reviewed active requirement clause",
    direction: HIGHER_EN,
    counts: "Numerator: one reviewed active requirement whose current exact authority is an app-issued passing verification result or separately typed explicit native human acceptance. A failed or rejected result is resolved not-met; unresolved requirements remain unknown and right-censor the value.",
    doesNotCount: "Denominator: exactly the active requirements in the bound complete r6 review. Excluded, stale, superseded, foreign, unreviewed, or producer-invented requirements do not count. Missing or invalid reviewed authority, unavailable or invalid verification authority, and bounded overflow remain Unknown; an exact empty reviewed set is Not applicable; none is converted to zero.",
    objectiveEvidence: VERIFIED_REQUIREMENT_EVIDENCE_EN,
  },
};

export const METRIC_HELP_V2_R8_REQUIREMENT_VERIFICATION_PL: Readonly<Record<string, MetricHelpEntry>> = {
  "outcome.verified_requirement_coverage": {
    meaning: "Udział dokładnych, natywnie przejrzanych aktywnych wymagań r6 rozstrzygniętych jako spełnione przez wystawiony przez aplikację wynik zaliczonej weryfikacji albo osobno typowaną, jawną natywną akceptację człowieka.",
    question: "Czy dla każdego przejrzanego aktywnego wymagania dokładne lokalne uprawnienie zapisuje zaliczony wynik weryfikacji aplikacji albo osobno typowaną natywną akceptację człowieka?",
    observationUnit: "jedna natywnie przejrzana aktywna klauzula wymagania",
    direction: HIGHER_PL,
    counts: "Licznik: jedno przejrzane aktywne wymaganie, którego bieżącym dokładnym uprawnieniem jest wystawiony przez aplikację zaliczony wynik weryfikacji albo osobno typowana jawna natywna akceptacja człowieka. Wynik niezaliczony lub odrzucony jest rozstrzygnięty jako niespełniony; nierozstrzygnięte wymagania pozostają nieznane i prawostronnie cenzurują wartość.",
    doesNotCount: "Mianownik: dokładnie aktywne wymagania z powiązanego kompletnego przeglądu r6. Wykluczone, nieaktualne, zastąpione, obce, nieprzejrzane ani wymyślone przez producenta wymagania nie są liczone. Brakujące lub nieważne uprawnienie przeglądu, niedostępne lub nieważne uprawnienie weryfikacji oraz przekroczenie limitu pozostają Nieznane; dokładny pusty zbiór jest Nie dotyczy; żaden z tych stanów nie staje się zerem.",
    objectiveEvidence: VERIFIED_REQUIREMENT_EVIDENCE_PL,
  },
};

const METRIC_HELP_V2_R3_OPEN_LOOP_EN: Readonly<Record<string, MetricHelpEntry>> = {
  "logic.open_loop_closure": {
    meaning: "Share of documented agent PLAN episodes in the bounded analysis window explicitly closed by a later agent ACTION or VERIFICATION that names that exact PLAN message in supersedes_message_ids.",
    question: "For each documented agent PLAN message, does a later agent ACTION or VERIFICATION explicitly supersede that exact plan?",
    observationUnit: "one documented agent PLAN episode",
    direction: HIGHER_EN,
    counts: "Numerator: one PLAN episode with a later agent ACTION or VERIFICATION whose supersedes_message_ids names that exact PLAN message; the earliest valid closer owns the closure.",
    doesNotCount: "Denominator: exactly the provider-declared agent PLAN messages in the bounded window, not detected questions. Token overlap, topical similarity, adjacency, a shared event identity, unrelated later actions, and plans outside the window do not close an episode. An unclosed plan is right-censored pending, not failed; no PLAN capability or no observed PLAN yields Unknown, never zero or N/A.",
    objectiveEvidence: EXPLICIT_PLAN_EVIDENCE_EN,
  },
};

const METRIC_HELP_V2_R4_LIFECYCLE_EN: Readonly<Record<string, MetricHelpEntry>> = {
  "collaboration.ambiguity_resolution": {
    meaning: "Share of the exact ambiguity opportunities in the authenticated local user's confirmed family enumeration whose confirmed ambiguity-resolution outcome is ambiguity_resolved.",
    question: "For each confirmed enumerated ambiguity opportunity, does its confirmed ambiguity_resolution link record ambiguity_resolved?",
    observationUnit: "one confirmed enumerated ambiguity opportunity",
    direction: HIGHER_EN,
    counts: "Numerator: one enumerated ambiguity opportunity with a confirmed ambiguity_resolution link whose outcome is ambiguity_resolved.",
    doesNotCount: "Denominator: exactly the authenticated local user's confirmed ambiguity enumeration, not detected ambiguity clauses. Proposed, rejected, undecided, or non-enumerated opportunities do not enter it; ambiguity_closed_unresolved is resolved not-met, while an enumerated opportunity without an outcome stays right-censored pending. Without an exact confirmed enumeration the metric is Unknown, never zero.",
    objectiveEvidence: CONFIRMED_LIFECYCLE_EVIDENCE_EN,
  },
  "collaboration.clarification_yield": {
    meaning: "Share of the exact clarification opportunities in the authenticated local user's confirmed family enumeration whose confirmed answer-incorporation outcome is clarification_incorporated.",
    question: "For each confirmed enumerated clarification opportunity, does its confirmed clarification_answer_incorporation link record clarification_incorporated?",
    observationUnit: "one confirmed enumerated clarification opportunity",
    direction: HIGHER_EN,
    counts: "Numerator: one enumerated clarification opportunity with a confirmed clarification_answer_incorporation link whose outcome is clarification_incorporated.",
    doesNotCount: "Denominator: exactly the authenticated local user's confirmed clarification enumeration, not detected agent questions. Proposed, rejected, undecided, or non-enumerated opportunities do not enter it; clarification_not_incorporated is resolved not-met, while an enumerated opportunity without an outcome stays right-censored pending. Without an exact confirmed enumeration the metric is Unknown, never zero.",
    objectiveEvidence: CONFIRMED_LIFECYCLE_EVIDENCE_EN,
  },
  "collaboration.exploration_conversion": {
    meaning: "Share of the exact exploration opportunities in the authenticated local user's confirmed family enumeration whose confirmed support-decision outcome is exploration_converted.",
    question: "For each confirmed enumerated exploration opportunity, does its confirmed exploration_support_decision link record exploration_converted?",
    observationUnit: "one confirmed enumerated exploration opportunity",
    direction: HIGHER_EN,
    counts: "Numerator: one enumerated exploration opportunity with a confirmed exploration_support_decision link whose outcome is exploration_converted.",
    doesNotCount: "Denominator: exactly the authenticated local user's confirmed exploration enumeration, not hypothesis-marker clauses. Proposed, rejected, undecided, or non-enumerated opportunities do not enter it; exploration_not_converted is resolved not-met, while an enumerated opportunity without an outcome stays right-censored pending. Without an exact confirmed enumeration the metric is Unknown, never zero.",
    objectiveEvidence: CONFIRMED_LIFECYCLE_EVIDENCE_EN,
  },
  "collaboration.scope_change_discipline": {
    meaning: "Share of the exact scope-change opportunities in the authenticated local user's confirmed family enumeration whose confirmed impact-disposition outcome is scope_change_disciplined.",
    question: "For each confirmed enumerated scope-change opportunity, does its confirmed scope_change_impact_disposition link record scope_change_disciplined?",
    observationUnit: "one confirmed enumerated scope-change opportunity",
    direction: HIGHER_EN,
    counts: "Numerator: one enumerated scope-change opportunity with a confirmed scope_change_impact_disposition link whose outcome is scope_change_disciplined.",
    doesNotCount: "Denominator: exactly the authenticated local user's confirmed scope-change enumeration, not detected scope-change clauses. Proposed, rejected, undecided, or non-enumerated opportunities do not enter it; scope_change_undisciplined is resolved not-met, while an enumerated opportunity without an outcome stays right-censored pending. Without an exact confirmed enumeration the metric is Unknown, never zero.",
    objectiveEvidence: CONFIRMED_LIFECYCLE_EVIDENCE_EN,
  },
  "collaboration.rework_candidate_rate": {
    meaning: "Share of the exact rework opportunities in the authenticated local user's confirmed family enumeration whose confirmed requirement-assessment outcome is rework_required; this is the raw lower-is-better rate.",
    question: "For each confirmed enumerated rework opportunity, does its confirmed rework_requirement_assessment link record rework_required?",
    observationUnit: "one confirmed enumerated rework opportunity",
    direction: LOWER_EN,
    counts: "Numerator: one enumerated rework opportunity with a confirmed rework_requirement_assessment link whose outcome is rework_required.",
    doesNotCount: "Denominator: exactly the authenticated local user's confirmed rework enumeration, not correction-marker feedback clauses. Proposed, rejected, undecided, or non-enumerated opportunities do not enter it; rework_not_required is resolved not-met, while an enumerated opportunity without an outcome stays right-censored pending. Without an exact confirmed enumeration the metric is Unknown, never zero.",
    objectiveEvidence: CONFIRMED_LIFECYCLE_EVIDENCE_EN,
  },
};

const METRIC_HELP_V2_R5_PROFILE_MEASUREMENTS: Readonly<Record<string, MetricHelpMeasurement>> = {
  "prompt.constraint_precision": {
    definitionVersion: 2,
    method: "Configured expected constraint kinds with a matching versioned cue in the canonical active user request divided by the exact expected_constraint_kinds slots in the reviewed profile.",
    limitation: "This is lexical method-only evidence: an absent slot set stays Unknown, and a cue match does not prove that a constraint is correct or sufficient.",
    objective: false,
  },
  "prompt.acceptance_testability": {
    definitionVersion: 2,
    method: "Distinct normalized checkable requirement clauses owned by the canonical active user request, capped at expected_outcome_count, divided by that exact reviewed count.",
    limitation: "This is lexical method-only evidence: an absent reviewed count stays Unknown, duplicate clauses do not inflate the numerator, and a matched cue does not prove that an acceptance criterion is correct or complete.",
    objective: false,
  },
  "prompt.deliverable_contract": {
    definitionVersion: 3,
    method: "Configured expected deliverable slots with a matching versioned cue in the canonical active user request divided by the exact expected_deliverable_slots in the reviewed profile.",
    limitation: "This is lexical method-only evidence: an absent slot set stays Unknown, and a cue match does not prove that a deliverable contract is correct or sufficient.",
    objective: false,
  },
};

const METRIC_HELP_V2_R6_REQUIREMENT_PLAN_MEASUREMENTS: Readonly<Record<string, MetricHelpMeasurement>> = {
  "logic.decomposition_coverage": {
    definitionVersion: 2,
    method: "Native-reviewed active requirement clauses with disposition linked to one or more revalidated later agent PLAN coordinates divided by the exact active_requirement subset of the complete native-confirmed user-clause classification.",
    limitation: "The opportunity unit is an active clause, not an atomic requirement: a compound active clause remains one opportunity and may coarsen multiple atomic requirements, while closed-rubric exclusions never enter the denominator. A pending disposition is right-censored, not failed. Missing confirmation stays Unknown, no active requirements is Not applicable, invalid coordinates fail closed as Unknown, and a valid structural link does not prove that the plan is sufficient or that the task succeeded.",
    objective: false,
  },
};

const METRIC_HELP_V2_R7_REQUIREMENT_ACTION_MEASUREMENTS: Readonly<Record<string, MetricHelpMeasurement>> = {
  "logic.requirement_action_traceability": {
    definitionVersion: 2,
    method: "Native-reviewed active r6 requirements with at least one semantically reviewed linked application-issued completed safe-action candidate divided by the exact bound active-requirement set; started or unknown-only links remain pending.",
    limitation: "A negative is legal only under complete bounded enumeration and exact review. Redacted descriptors and source references help the person inspect semantic relevance but do not prove it automatically; completed state does not prove task success, correctness, or quality.",
    objective: true,
  },
};

const METRIC_HELP_V2_R8_REQUIREMENT_VERIFICATION_MEASUREMENTS: Readonly<Record<string, MetricHelpMeasurement>> = {
  "outcome.verified_requirement_coverage": {
    definitionVersion: 4,
    method: "Reviewed active r6 requirements resolved as met by current app-issued passing verification results or separately typed explicit native human acceptance divided by the exact bound reviewed active-requirement set.",
    limitation: "Failed or rejected authority is resolved not-met; unresolved authority right-censors the fraction with exact bounds. Missing, invalid, stale, foreign, or overflowing authority fails closed as Unknown, an exact empty reviewed set is Not applicable, and assistant completion claims or other prose never prove a requirement met.",
    objective: true,
  },
};

const METRIC_HELP_V2_R3_OPEN_LOOP_MEASUREMENTS: Readonly<Record<string, MetricHelpMeasurement>> = {
  "logic.open_loop_closure": {
    definitionVersion: 2,
    method: "Documented agent PLAN episodes explicitly superseded by a later agent ACTION or VERIFICATION naming that exact PLAN message divided by the exact documented agent PLAN episodes in the bounded window.",
    limitation: "An unclosed plan is right-censored pending rather than failed; absent PLAN capability or an observed empty PLAN set remains Unknown, and an explicit link does not prove that the plan or result was correct.",
    objective: false,
  },
};

const METRIC_HELP_V2_R4_LIFECYCLE_MEASUREMENTS: Readonly<Record<string, MetricHelpMeasurement>> = {
  "collaboration.ambiguity_resolution": {
    definitionVersion: 2,
    method: "Confirmed enumerated ambiguity opportunities with an ambiguity_resolution link whose outcome is ambiguity_resolved divided by the exact authenticated local-user confirmed ambiguity enumeration.",
    limitation: "A confirmed enumeration is mandatory; an enumerated opportunity without a confirmed outcome is right-censored pending, and local-user confirmation is not objective test proof.",
    objective: false,
  },
  "collaboration.clarification_yield": {
    definitionVersion: 2,
    method: "Confirmed enumerated clarification opportunities with a clarification_answer_incorporation link whose outcome is clarification_incorporated divided by the exact authenticated local-user confirmed clarification enumeration.",
    limitation: "A confirmed enumeration is mandatory; an enumerated opportunity without a confirmed outcome is right-censored pending, and local-user confirmation is not objective test proof.",
    objective: false,
  },
  "collaboration.exploration_conversion": {
    definitionVersion: 2,
    method: "Confirmed enumerated exploration opportunities with an exploration_support_decision link whose outcome is exploration_converted divided by the exact authenticated local-user confirmed exploration enumeration.",
    limitation: "A confirmed enumeration is mandatory; an enumerated opportunity without a confirmed outcome is right-censored pending, and local-user confirmation is not objective test proof.",
    objective: false,
  },
  "collaboration.scope_change_discipline": {
    definitionVersion: 2,
    method: "Confirmed enumerated scope-change opportunities with a scope_change_impact_disposition link whose outcome is scope_change_disciplined divided by the exact authenticated local-user confirmed scope-change enumeration.",
    limitation: "A confirmed enumeration is mandatory; an enumerated opportunity without a confirmed outcome is right-censored pending, and local-user confirmation is not objective test proof.",
    objective: false,
  },
  "collaboration.rework_candidate_rate": {
    definitionVersion: 2,
    method: "Confirmed enumerated rework opportunities with a rework_requirement_assessment link whose outcome is rework_required divided by the exact authenticated local-user confirmed rework enumeration.",
    limitation: "This publishes the raw lower-is-better rework-required rate. A confirmed enumeration is mandatory; an enumerated opportunity without a confirmed outcome is right-censored pending, and local-user confirmation is not objective test proof.",
    objective: false,
  },
};

const SEEDS: readonly MetricHelpSeed[] = [
  {
    key: "prompt.task_definition_coverage", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of the three task-definition cues (action, target, intended outcome) detected in the focus request.", question: "Did the focus request contain separate action, target, and intended-outcome cues?", observationUnit: "one cue check on the focus request (three per request)", direction: HIGHER_EN, counts: "A detected action, target, or intended-outcome cue in the focus request.", doesNotCount: "Cues in later messages, agent restatements, or implied goals.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział trzech sygnałów definicji zadania (działanie, cel, zamierzony rezultat) wykrytych w prośbie głównej.", question: "Czy prośba główna zawierała osobne sygnały działania, celu i zamierzonego rezultatu?", observationUnit: "jedna kontrola sygnału w prośbie głównej (trzy na prośbę)", direction: HIGHER_PL, counts: "Wykryty sygnał działania, celu lub zamierzonego rezultatu w prośbie głównej.", doesNotCount: "Sygnały w późniejszych wiadomościach, parafrazy agenta ani domyślne cele.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "prompt.problem_evidence_quality", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of four legacy diagnostic cue checks (observed/diagnostic wording, expected, reproduction, environment) present when a bug or diagnosis candidate is detected.", question: "For a detected diagnosis request, which of the four legacy cue checks fired?", observationUnit: "one legacy evidence-cue check per detected diagnosis request (four per request)", direction: HIGHER_EN, counts: "Observed wording or any diagnostic keyword satisfies the shipped observed check; expected wording, reproduction wording, and environment details satisfy the other checks.", doesNotCount: "Requests without a detected diagnosis candidate: they stay Unknown, never zero. A fired cue is not proof that the evidence is complete or correct.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział czterech starszych kontroli sygnałów diagnozy (sformułowanie obserwacji lub diagnozy, oczekiwanie, reprodukcja, środowisko), gdy wykryto kandydata diagnozy.", question: "Które z czterech starszych kontroli sygnałów zadziałały dla wykrytej prośby diagnostycznej?", observationUnit: "jedna starsza kontrola sygnału na wykrytą prośbę diagnostyczną (cztery na prośbę)", direction: HIGHER_PL, counts: "Sformułowanie obserwacji lub dowolne słowo diagnostyczne spełnia dostarczaną kontrolę obserwacji; osobne kontrole dotyczą oczekiwań, reprodukcji i środowiska.", doesNotCount: "Prośby bez wykrytego kandydata diagnozy: pozostają Nieznane, nigdy zero. Zadziałanie sygnału nie dowodzi kompletności ani poprawności dowodu.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "prompt.context_sufficiency", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of context cues (current state, environment or version, important boundary) present in the focus request.", question: "Did the focus request identify current state, environment or version, and an important boundary?", observationUnit: "one context cue check on the focus request (three per request)", direction: HIGHER_EN, counts: "A current-state fact, an environment or version fact, or an explicit boundary.", doesNotCount: "Context the agent discovered itself or context added after corrections.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział sygnałów kontekstu (stan bieżący, środowisko lub wersja, istotna granica) obecnych w prośbie głównej.", question: "Czy prośba główna wskazała stan bieżący, środowisko lub wersję oraz istotną granicę?", observationUnit: "jedna kontrola sygnału kontekstu w prośbie głównej (trzy na prośbę)", direction: HIGHER_PL, counts: "Fakt o stanie bieżącym, fakt o środowisku lub wersji albo jawna granica.", doesNotCount: "Kontekst odkryty samodzielnie przez agenta ani dodany po korektach.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "prompt.constraint_precision", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected constraint clauses that also match the shipped concrete-detail vocabulary or a numeric bound.", question: "How many detected constraints include a recognized platform, version, numeric threshold, unit, or concrete environment term?", observationUnit: "one detected constraint clause", direction: HIGHER_EN, counts: "A constraint clause with a recognized numeric limit, threshold, platform, version, unit, or concrete environment term.", doesNotCount: "Absent constraints (they yield Unknown, never zero), vague wording, and a generic prohibition such as 'must not write files' without another recognized concrete detail.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział wykrytych klauzul ograniczeń, które pasują też do dostarczanego słownika konkretów lub granicy liczbowej.", question: "Ile wykrytych ograniczeń zawiera rozpoznaną platformę, wersję, próg liczbowy, jednostkę lub konkretny termin środowiska?", observationUnit: "jedna wykryta klauzula ograniczenia", direction: HIGHER_PL, counts: "Klauzula ograniczenia z rozpoznanym limitem liczbowym, progiem, platformą, wersją, jednostką lub konkretnym terminem środowiska.", doesNotCount: "Brak ograniczeń (daje Nieznane, nigdy zero), ogólniki oraz sam ogólny zakaz bez innego rozpoznanego konkretu.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "prompt.acceptance_testability", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected requirements that carry an observable pass-condition cue.", question: "How many detected requirements include an observable pass condition?", observationUnit: "one detected requirement clause", direction: HIGHER_EN, counts: "A requirement clause with a check, test, threshold, comparison, or explicit pass cue; a bare test word can satisfy the shipped legacy heuristic.", doesNotCount: "The cue is not proof of a complete or correct acceptance criterion; checks the agent added later are not counted.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział wykrytych wymagań niosących sygnał obserwowalnego warunku zaliczenia.", question: "Ile wykrytych wymagań zawiera obserwowalny warunek zaliczenia?", observationUnit: "jedna wykryta klauzula wymagania", direction: HIGHER_PL, counts: "Klauzula wymagania z sygnałem kontroli, testu, progu, porównania lub jawnego zaliczenia; samo słowo „test” może spełnić dostarczaną heurystykę.", doesNotCount: "Sygnał nie dowodzi pełnego ani poprawnego kryterium akceptacji; kontrole dodane później przez agenta nie są liczone.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "prompt.deliverable_contract", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected deliverable clauses that also match the shipped format, interface, audience, compatibility, or platform-detail vocabulary.", question: "How many detected deliverables include a recognized format, interface, audience, compatibility, or platform detail?", observationUnit: "one detected deliverable clause", direction: HIGHER_EN, counts: "A deliverable clause with a recognized format, interface, audience, compatibility, or platform token.", doesNotCount: "A path or location alone is not recognized by the shipped detail heuristic; only detected deliverable clauses form the denominator.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział wykrytych klauzul rezultatu, które pasują też do dostarczanego słownika formatu, interfejsu, odbiorcy, zgodności lub platformy.", question: "Ile wykrytych rezultatów zawiera rozpoznany format, interfejs, odbiorcę, zgodność lub szczegół platformy?", observationUnit: "jedna wykryta klauzula rezultatu", direction: HIGHER_PL, counts: "Klauzula rezultatu z rozpoznanym tokenem formatu, interfejsu, odbiorcy, zgodności lub platformy.", doesNotCount: "Sama ścieżka lub lokalizacja nie jest rozpoznawana przez dostarczaną heurystykę szczegółu; mianownik tworzą tylko wykryte rezultaty.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "collaboration.ambiguity_resolution", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected ambiguity markers that were followed by a related clarification or explicit replacement.", question: "Were detected vague or unresolved references followed by a related clarification?", observationUnit: "one clause with an ambiguity marker", direction: HIGHER_EN, counts: "A later related clarification or explicit replacement of the vague reference.", doesNotCount: "Semantic materiality judgments; markers are review candidates only.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział wykrytych znaczników niejednoznaczności, po których nastąpiło powiązane doprecyzowanie lub jawne zastąpienie.", question: "Czy po wykrytych niejasnych odniesieniach nastąpiło powiązane doprecyzowanie?", observationUnit: "jedna klauzula ze znacznikiem niejednoznaczności", direction: HIGHER_PL, counts: "Późniejsze powiązane doprecyzowanie lub jawne zastąpienie niejasnego odniesienia.", doesNotCount: "Ocena istotności semantycznej; znaczniki są tylko kandydatami do przeglądu.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "collaboration.clarification_yield", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of agent questions that received a later related, substantive user answer.", question: "Did agent questions produce a related, substantive user answer?", observationUnit: "one agent question", direction: HIGHER_EN, counts: "A later related user answer carrying concrete task information.", doesNotCount: "Question frequency itself, or answers unrelated to the question.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział pytań agenta, na które padła późniejsza powiązana, merytoryczna odpowiedź użytkownika.", question: "Czy pytania agenta przyniosły powiązaną, merytoryczną odpowiedź użytkownika?", observationUnit: "jedno pytanie agenta", direction: HIGHER_PL, counts: "Późniejsza powiązana odpowiedź użytkownika z konkretną informacją o zadaniu.", doesNotCount: "Sama liczba pytań ani odpowiedzi niezwiązane z pytaniem.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "collaboration.exploration_conversion", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of hypothesis or theorizing clauses that later converged into a related plan, decision, action, or verification item.", question: "Did observable hypotheses or theorizing converge into a related plan or evidence step?", observationUnit: "one hypothesis-marker clause", direction: HIGHER_EN, counts: "A later related plan, decision, action, or verification item.", doesNotCount: "An ideal amount of exploration; research tasks need task-type context.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział klauzul hipotez lub teoretyzowania, które później przeszły w powiązany plan, decyzję, działanie lub weryfikację.", question: "Czy obserwowalne hipotezy przeszły w powiązany plan lub krok dowodowy?", observationUnit: "jedna klauzula ze znacznikiem hipotezy", direction: HIGHER_PL, counts: "Późniejszy powiązany plan, decyzja, działanie lub element weryfikacji.", doesNotCount: "Idealna ilość eksploracji; zadania badawcze wymagają kontekstu typu zadania.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "collaboration.scope_change_discipline", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of explicit user scope-change clauses that were acknowledged in a related response or revised plan.", question: "Were explicit scope changes acknowledged in a related response or revised plan?", observationUnit: "one explicit user scope-change clause", direction: HIGHER_EN, counts: "A related acknowledgement or revised plan after the change.", doesNotCount: "Intentional iteration as failure; with no change the metric stays Unknown.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział jawnych zmian zakresu przez użytkownika potwierdzonych w powiązanej odpowiedzi lub zrewidowanym planie.", question: "Czy jawne zmiany zakresu zostały potwierdzone w powiązanej odpowiedzi lub zrewidowanym planie?", observationUnit: "jedna jawna klauzula zmiany zakresu", direction: HIGHER_PL, counts: "Powiązane potwierdzenie lub zrewidowany plan po zmianie.", doesNotCount: "Zamierzona iteracja jako porażka; bez zmiany metryka pozostaje Nieznana.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "collaboration.rework_candidate_rate", direction: "lower_is_better", objective: false,
    en: { meaning: "Share of user feedback clauses after an agent response that carry correction or misunderstanding markers.", question: "What share of user feedback contains correction or misunderstanding markers?", observationUnit: "one user feedback clause following an agent response", direction: LOWER_EN, counts: "Any feedback clause with a correction or misunderstanding marker — the shipped heuristic also catches some new-scope, preference, and healthy-iteration clauses.", doesNotCount: "Nothing is proven rework: the rule cannot separate genuine rework from new information, so every hit is a review candidate.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział klauzul opinii użytkownika po odpowiedzi agenta zawierających znaczniki korekty lub nieporozumienia.", question: "Jaki udział opinii użytkownika zawiera znaczniki korekty lub nieporozumienia?", observationUnit: "jedna klauzula opinii użytkownika po odpowiedzi agenta", direction: LOWER_PL, counts: "Każda klauzula opinii ze znacznikiem korekty lub nieporozumienia — dostarczana heurystyka łapie też część klauzul nowego zakresu, preferencji i zdrowej iteracji.", doesNotCount: "Nic nie jest dowiedzioną przeróbką: reguła nie odróżnia prawdziwej przeróbki od nowej informacji, więc każde trafienie to kandydat do przeglądu.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "logic.decomposition_coverage", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected requirements that could be linked to an explicit plan item.", question: "Could each detected requirement be linked to an explicit plan item?", observationUnit: "one detected requirement", direction: HIGHER_EN, counts: "A conservative lexical link from a requirement to an explicit plan item.", doesNotCount: "Plan adequacy; a link is a candidate, not proof the plan is sufficient.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział wykrytych wymagań, które dało się powiązać z jawnym elementem planu.", question: "Czy każde wykryte wymaganie dało się powiązać z jawnym elementem planu?", observationUnit: "jedno wykryte wymaganie", direction: HIGHER_PL, counts: "Ostrożne leksykalne powiązanie wymagania z jawnym elementem planu.", doesNotCount: "Adekwatność planu; powiązanie to kandydat, nie dowód wystarczalności planu.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "logic.hypothesis_test_linkage", direction: "higher_is_better", objective: true,
    en: { meaning: "Share of technical hypotheses followed by a discriminating structured check.", question: "Was each technical hypothesis followed by a discriminating structured check?", observationUnit: "one technical hypothesis", direction: HIGHER_EN, counts: "A typed verification episode that can distinguish the hypothesis from alternatives.", doesNotCount: "Chronological proximity or an agent saying it tested something.", objectiveEvidence: TYPED_EVIDENCE_EN },
    pl: { meaning: "Udział hipotez technicznych, po których nastąpiła rozstrzygająca ustrukturyzowana kontrola.", question: "Czy po każdej hipotezie technicznej nastąpiła rozstrzygająca ustrukturyzowana kontrola?", observationUnit: "jedna hipoteza techniczna", direction: HIGHER_PL, counts: "Typowany epizod weryfikacji zdolny odróżnić hipotezę od alternatyw.", doesNotCount: "Bliskość czasowa ani deklaracja agenta, że coś przetestował.", objectiveEvidence: TYPED_EVIDENCE_PL },
  },
  {
    key: "logic.decision_rationale_coverage", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of structured decisions connected to a rationale, alternative, constraint, or evidence.", question: "Were observable decisions connected to a rationale, alternative, constraint, or evidence?", observationUnit: "one structured decision item", direction: HIGHER_EN, counts: "A rationale-bearing structured decision item.", doesNotCount: "Free-text decisions; when the projection exposes no decision items the metric abstains.", objectiveEvidence: "Requires structured decision items from the local projection; without them the metric abstains rather than scoring prose." },
    pl: { meaning: "Udział ustrukturyzowanych decyzji powiązanych z uzasadnieniem, alternatywą, ograniczeniem lub dowodem.", question: "Czy obserwowalne decyzje powiązano z uzasadnieniem, alternatywą, ograniczeniem lub dowodem?", observationUnit: "jeden ustrukturyzowany element decyzji", direction: HIGHER_PL, counts: "Ustrukturyzowany element decyzji niosący uzasadnienie.", doesNotCount: "Decyzje w luźnym tekście; bez elementów decyzji w projekcji metryka wstrzymuje ocenę.", objectiveEvidence: "Wymaga ustrukturyzowanych elementów decyzji z lokalnej projekcji; bez nich metryka wstrzymuje ocenę zamiast punktować prozę." },
  },
  {
    key: "logic.requirement_action_traceability", direction: "higher_is_better", objective: true,
    en: { meaning: "Share of active requirements linked to structured implementation work.", question: "Could every active requirement be linked to structured implementation work?", observationUnit: "one active requirement", direction: HIGHER_EN, counts: "A structured action link (tool, edit, command, or artifact) for the requirement.", doesNotCount: "Generic agent response text reclassified as an action.", objectiveEvidence: TYPED_EVIDENCE_EN },
    pl: { meaning: "Udział aktywnych wymagań powiązanych z ustrukturyzowaną pracą implementacyjną.", question: "Czy każde aktywne wymaganie dało się powiązać z ustrukturyzowaną pracą implementacyjną?", observationUnit: "jedno aktywne wymaganie", direction: HIGHER_PL, counts: "Ustrukturyzowane powiązanie działania (narzędzie, edycja, polecenie lub artefakt) z wymaganiem.", doesNotCount: "Ogólny tekst odpowiedzi agenta przeklasyfikowany na działanie.", objectiveEvidence: TYPED_EVIDENCE_PL },
  },
  {
    key: "logic.open_loop_closure", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected questions followed by a related opposite-role response and not reopened.", question: "Were detected questions followed by a related opposite-role response and not reopened?", observationUnit: "one detected question", direction: HIGHER_EN, counts: "A related closing response from the other role that is not reopened later.", doesNotCount: "Answer correctness; a linked response is not proof the answer is right.", objectiveEvidence: TEXT_CANDIDATE_EN },
    pl: { meaning: "Udział wykrytych pytań, po których nastąpiła powiązana odpowiedź drugiej strony bez ponownego otwarcia.", question: "Czy po wykrytych pytaniach nastąpiła powiązana odpowiedź drugiej strony bez ponownego otwarcia?", observationUnit: "jedno wykryte pytanie", direction: HIGHER_PL, counts: "Powiązana zamykająca odpowiedź drugiej roli, nieotwarta ponownie później.", doesNotCount: "Poprawność odpowiedzi; powiązana odpowiedź nie dowodzi, że jest właściwa.", objectiveEvidence: TEXT_CANDIDATE_PL },
  },
  {
    key: "outcome.agent_claim_grounding", direction: "higher_is_better", objective: true,
    en: { meaning: "Share of agent response or summary clauses treated by the shipped compatibility calculator as claim candidates and backed by typed objective evidence.", question: "Which agent response or summary clauses have an authorized objective-evidence link?", observationUnit: "one agent response or summary clause (every such clause is a legacy candidate)", direction: HIGHER_EN, counts: "A candidate clause linked to a typed tool, test, source, or artifact receipt.", doesNotCount: "An assistant statement on its own is never proof of delivery; the shipped compatibility calculator does not detect material claims and conservatively treats every response or summary clause as a candidate.", objectiveEvidence: TYPED_EVIDENCE_EN },
    pl: { meaning: "Udział klauzul odpowiedzi lub podsumowania agenta traktowanych przez dostarczany kalkulator zgodności jako kandydaci deklaracji i popartych typowanym obiektywnym dowodem.", question: "Które klauzule odpowiedzi lub podsumowania agenta mają autoryzowane powiązanie z obiektywnym dowodem?", observationUnit: "jedna klauzula odpowiedzi lub podsumowania agenta (każda jest starszym kandydatem)", direction: HIGHER_PL, counts: "Klauzula kandydata powiązana z typowanym pokwitowaniem narzędzia, testu, źródła lub artefaktu.", doesNotCount: "Sama wypowiedź asystenta nigdy nie dowodzi dostarczenia; dostarczany kalkulator zgodności nie wykrywa istotnych deklaracji i ostrożnie traktuje każdą klauzulę odpowiedzi lub podsumowania jako kandydata.", objectiveEvidence: TYPED_EVIDENCE_PL },
  },
  {
    key: "outcome.verification_strategy_adequacy", direction: "higher_is_better", objective: false,
    en: { meaning: "Share of detected requirements that received a related planned check.", question: "Did each detected requirement receive a related planned check?", observationUnit: "one detected requirement", direction: HIGHER_EN, counts: "A later plan or response with a check cue linked to the requirement.", doesNotCount: "Whether the check ran or passed; this is stated strategy only.", objectiveEvidence: "No execution receipt backs the stated strategy; run and pass evidence belongs to first-pass and verified-coverage metrics." },
    pl: { meaning: "Udział wykrytych wymagań, dla których zaplanowano powiązaną kontrolę.", question: "Czy każde wykryte wymaganie otrzymało powiązaną zaplanowaną kontrolę?", observationUnit: "jedno wykryte wymaganie", direction: HIGHER_PL, counts: "Późniejszy plan lub odpowiedź z sygnałem kontroli powiązanym z wymaganiem.", doesNotCount: "Czy kontrola się wykonała lub przeszła; to tylko deklarowana strategia.", objectiveEvidence: "Deklarowanej strategii nie potwierdza pokwitowanie wykonania; dowody uruchomienia i zaliczenia należą do metryk pierwszego przebiegu i pokrycia zweryfikowanego." },
  },
  {
    key: "outcome.first_pass_verification", direction: "higher_is_better", objective: true,
    en: { meaning: "Whether the first meaningful executable verification episode passed.", question: "Did the first meaningful executable verification episode pass?", observationUnit: "one eligible task with an ordered verification episode", direction: HIGHER_EN, counts: "A first meaningful typed verification episode with a passing outcome.", doesNotCount: "Retries (they cannot improve it) and missing checks (they never become failure).", objectiveEvidence: TYPED_EVIDENCE_EN },
    pl: { meaning: "Czy pierwszy istotny wykonywalny epizod weryfikacji zakończył się powodzeniem.", question: "Czy pierwszy istotny wykonywalny epizod weryfikacji przeszedł?", observationUnit: "jedno kwalifikujące się zadanie z uporządkowanym epizodem weryfikacji", direction: HIGHER_PL, counts: "Pierwszy istotny typowany epizod weryfikacji z wynikiem pozytywnym.", doesNotCount: "Ponowienia (nie poprawiają wyniku) ani brak kontroli (nigdy nie staje się porażką).", objectiveEvidence: TYPED_EVIDENCE_PL },
  },
  {
    key: "outcome.verified_requirement_coverage", direction: "higher_is_better", objective: true,
    en: { meaning: "Share of active requirements with objective passing evidence or explicit acceptance.", question: "How many active requirements have objective passing evidence or explicit acceptance?", observationUnit: "one active requirement", direction: HIGHER_EN, counts: "A typed requirement-to-verification link with a pass, or explicit human acceptance.", doesNotCount: "Completion claims, unrelated green checks, or deferred requirements.", objectiveEvidence: VERIFIED_REQUIREMENT_EVIDENCE_EN },
    pl: { meaning: "Udział aktywnych wymagań z obiektywnym dowodem zaliczenia lub jawną akceptacją.", question: "Ile aktywnych wymagań ma obiektywny dowód zaliczenia lub jawną akceptację?", observationUnit: "jedno aktywne wymaganie", direction: HIGHER_PL, counts: "Typowane powiązanie wymagania z weryfikacją zakończoną zaliczeniem lub jawna akceptacja człowieka.", doesNotCount: "Deklaracje ukończenia, niezwiązane zielone kontrole ani odroczone wymagania.", objectiveEvidence: VERIFIED_REQUIREMENT_EVIDENCE_PL },
  },
];

export const METRIC_HELP_V2_KEYS: readonly string[] = SEEDS.map((seed) => seed.key);

export const METRIC_HELP_V2: Readonly<Record<MetricHelpLocale, Readonly<Record<string, MetricHelpEntry>>>> = {
  en: Object.fromEntries(SEEDS.map((seed) => [seed.key, seed.en])),
  pl: Object.fromEntries(SEEDS.map((seed) => [seed.key, seed.pl])),
};

export const METRIC_HELP_V2_DIRECTIONS: Readonly<Record<string, MetricHelpDirection>> =
  Object.fromEntries(SEEDS.map((seed) => [seed.key, seed.direction]));

const OBJECTIVE_KEYS = new Set(SEEDS.filter((seed) => seed.objective).map((seed) => seed.key));

export function metricHelpV2IsObjective(metricKey: string): boolean {
  return OBJECTIVE_KEYS.has(metricKey);
}

/** Shipped measurement binding selected by the exact sealed projection. */
export function metricHelpV2Measurement(
  metricKey: string,
  projectionVersion: MetricHelpProjectionVersion | null = null,
): MetricHelpMeasurement | null {
  if (projectionVersion === R8_PROJECTION) {
    const reviewedRequirementVerification = METRIC_HELP_V2_R8_REQUIREMENT_VERIFICATION_MEASUREMENTS[metricKey];
    if (reviewedRequirementVerification !== undefined) return reviewedRequirementVerification;
  }
  if (projectionVersion === R7_PROJECTION || projectionVersion === R8_PROJECTION) {
    const reviewedRequirementAction = METRIC_HELP_V2_R7_REQUIREMENT_ACTION_MEASUREMENTS[metricKey];
    if (reviewedRequirementAction !== undefined) return reviewedRequirementAction;
  }
  if (
    projectionVersion === R6_PROJECTION
    || projectionVersion === R7_PROJECTION
    || projectionVersion === R8_PROJECTION
  ) {
    const reviewedRequirementPlan = METRIC_HELP_V2_R6_REQUIREMENT_PLAN_MEASUREMENTS[metricKey];
    if (reviewedRequirementPlan !== undefined) return reviewedRequirementPlan;
  }
  if (projectionVersion !== null && R5_PLUS_PROJECTIONS.has(projectionVersion)) {
    const reviewedProfile = METRIC_HELP_V2_R5_PROFILE_MEASUREMENTS[metricKey];
    if (reviewedProfile !== undefined) return reviewedProfile;
  }
  if (projectionVersion !== null && R4_PLUS_PROJECTIONS.has(projectionVersion)) {
    const confirmedLifecycle = METRIC_HELP_V2_R4_LIFECYCLE_MEASUREMENTS[metricKey];
    if (confirmedLifecycle !== undefined) return confirmedLifecycle;
  }
  if (projectionVersion !== null && R3_PLUS_PROJECTIONS.has(projectionVersion)) {
    const explicitPlan = METRIC_HELP_V2_R3_OPEN_LOOP_MEASUREMENTS[metricKey];
    if (explicitPlan !== undefined) return explicitPlan;
  }
  const definition = QUALITY_ANALYSIS_DEFINITIONS.find((candidate) => candidate.key === metricKey);
  if (definition === undefined) return null;
  return {
    definitionVersion: definition.version,
    method: definition.method,
    limitation: definition.limitation,
    objective: OBJECTIVE_KEYS.has(metricKey),
  };
}

export interface ResolvedMetricHelp {
  version: typeof METRIC_HELP_V2_VERSION;
  metricKey: string;
  requestedLocale: MetricHelpLocale;
  locale: MetricHelpLocale;
  fallback: boolean;
  /** Target contract copy. */
  entry: MetricHelpEntry;
  /** Which immutable receipt definition selected this copy. */
  definitionScope:
    | "historical_candidate"
    | "r3_explicit_plan_lifecycle"
    | "r4_confirmed_lifecycle"
    | "r5_reviewed_profile"
    | "r6_reviewed_requirement_plan"
    | "r7_reviewed_requirement_action"
    | "r8_reviewed_requirement_verification";
  projectionVersion: MetricHelpProjectionVersion | null;
  /** Shipped measurement source (English only). */
  measurement: MetricHelpMeasurement | null;
}

/** Human-readable immutable definition identity for headings and receipt sentences. */
export function metricHelpV2DefinitionLabel(
  help: Pick<ResolvedMetricHelp, "definitionScope" | "projectionVersion">,
): string {
  const projection = help.projectionVersion?.replace("metric-contract-v2-projection-", "r") ?? "unbound";
  switch (help.definitionScope) {
    case "r3_explicit_plan_lifecycle": return `sealed ${projection} explicit-plan lifecycle`;
    case "r4_confirmed_lifecycle": return `sealed ${projection} confirmed-lifecycle`;
    case "r5_reviewed_profile": return `sealed ${projection} reviewed-profile`;
    case "r6_reviewed_requirement_plan": return `sealed ${projection} reviewed requirement-plan`;
    case "r7_reviewed_requirement_action": return `sealed ${projection} reviewed requirement-action`;
    case "r8_reviewed_requirement_verification": return `sealed ${projection} reviewed requirement-verification`;
    default: return help.projectionVersion === null
      ? "unbound local candidate"
      : `sealed ${projection} candidate`;
  }
}

/** Resolve help for one metric and sealed projection; unknown or partial locales fall back to English. */
export function metricHelpV2(
  metricKey: string,
  locale: MetricHelpLocale = "en",
  projectionVersion: MetricHelpProjectionVersion | null = null,
): ResolvedMetricHelp | null {
  const requested = METRIC_HELP_V2[locale] as Readonly<Record<string, MetricHelpEntry>> | undefined;
  const english = METRIC_HELP_V2.en[metricKey];
  if (english === undefined) return null;
  const measurement = metricHelpV2Measurement(metricKey, projectionVersion);
  const r8Locale: MetricHelpLocale = locale === "pl" ? "pl" : "en";
  const r8RequirementVerification = projectionVersion === R8_PROJECTION
    ? (r8Locale === "pl"
      ? METRIC_HELP_V2_R8_REQUIREMENT_VERIFICATION_PL[metricKey]
      : METRIC_HELP_V2_R8_REQUIREMENT_VERIFICATION_EN[metricKey])
    : undefined;
  if (r8RequirementVerification !== undefined) {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: r8Locale,
      fallback: locale !== r8Locale,
      entry: r8RequirementVerification,
      definitionScope: "r8_reviewed_requirement_verification",
      projectionVersion,
      measurement,
    };
  }
  const r7RequirementAction = (
    projectionVersion === R7_PROJECTION || projectionVersion === R8_PROJECTION
  )
    ? METRIC_HELP_V2_R7_REQUIREMENT_ACTION_EN[metricKey]
    : undefined;
  if (r7RequirementAction !== undefined) {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: "en",
      fallback: locale !== "en",
      entry: r7RequirementAction,
      definitionScope: "r7_reviewed_requirement_action",
      projectionVersion,
      measurement,
    };
  }
  const r6RequirementPlan = (
    projectionVersion === R6_PROJECTION
    || projectionVersion === R7_PROJECTION
    || projectionVersion === R8_PROJECTION
  )
    ? METRIC_HELP_V2_R6_REQUIREMENT_PLAN_EN[metricKey]
    : undefined;
  if (r6RequirementPlan !== undefined) {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: "en",
      fallback: locale !== "en",
      entry: r6RequirementPlan,
      definitionScope: "r6_reviewed_requirement_plan",
      projectionVersion,
      measurement,
    };
  }
  const r5Profile = projectionVersion !== null && R5_PLUS_PROJECTIONS.has(projectionVersion)
    ? METRIC_HELP_V2_R5_PROFILE_EN[metricKey]
    : undefined;
  if (r5Profile !== undefined) {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: "en",
      fallback: locale !== "en",
      entry: r5Profile,
      definitionScope: "r5_reviewed_profile",
      projectionVersion,
      measurement,
    };
  }
  const r4Lifecycle = projectionVersion !== null && R4_PLUS_PROJECTIONS.has(projectionVersion)
    ? METRIC_HELP_V2_R4_LIFECYCLE_EN[metricKey]
    : undefined;
  if (r4Lifecycle !== undefined) {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: "en",
      fallback: locale !== "en",
      entry: r4Lifecycle,
      definitionScope: "r4_confirmed_lifecycle",
      projectionVersion,
      measurement,
    };
  }
  const r3OpenLoop = projectionVersion !== null && R3_PLUS_PROJECTIONS.has(projectionVersion)
    ? METRIC_HELP_V2_R3_OPEN_LOOP_EN[metricKey]
    : undefined;
  if (r3OpenLoop !== undefined) {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: "en",
      fallback: locale !== "en",
      entry: r3OpenLoop,
      definitionScope: "r3_explicit_plan_lifecycle",
      projectionVersion,
      measurement,
    };
  }
  const entry = requested?.[metricKey];
  if (entry === undefined || locale === "en") {
    return {
      version: METRIC_HELP_V2_VERSION,
      metricKey,
      requestedLocale: locale,
      locale: "en",
      fallback: locale !== "en",
      entry: english,
      definitionScope: "historical_candidate",
      projectionVersion,
      measurement,
    };
  }
  return {
    version: METRIC_HELP_V2_VERSION,
    metricKey,
    requestedLocale: locale,
    locale,
    fallback: false,
    entry,
    definitionScope: "historical_candidate",
    projectionVersion,
    measurement,
  };
}

/**
 * Singular noun phrase of an observation unit for "no eligible … was observed"
 * ("one agent question" → "agent question"); a unit without the leading "one"
 * is returned unchanged.
 */
export function observationUnitSingular(unit: string): string {
  return unit.replace(/^one /u, "");
}

/**
 * Count-friendly phrasing of an observation unit for fractions and counts
 * ("3/4 …", "2 of 4 …"): "one agent question" → "opportunities (one per agent
 * question)". Sentences never read "3/4 one agent question".
 */
export function observationUnitCounted(unit: string): string {
  const singular = observationUnitSingular(unit);
  return singular === unit ? unit : `opportunities (one per ${singular})`;
}

export type MetricInspectorKind =
  | "pending"
  | "suppressed"
  | "withheld"
  | "unavailable"
  | "not_applicable"
  | "unknown"
  | "abstained"
  | "execution_error"
  | "missing"
  | "experimental"
  | "zero"
  | "measured";

export interface MetricInspectorInput {
  metricKey: string;
  label: string;
  /** Projection identity of this exact sealed state; absent means legacy/unbound help. */
  projectionVersion?: MetricHelpProjectionVersion | null;
  state:
    | "known"
    | "unknown"
    | "not_applicable"
    | "abstained"
    | "execution_error"
    | "pending"
    | "missing"
    | "suppressed"
    | "withheld"
    | "unavailable";
  direction: MetricHelpDirection;
  numericValue: number | null;
  numerator: number | null;
  denominator: number | null;
  explanationCode?: string | null;
  /** Authority declared by this exact receipt; never inferred for V2 data. */
  evidenceAuthority?: string | null;
  suppressionReason?: "small_cohort" | "overlap_or_differencing" | "query_identity_mismatch" | null;
  comparabilityState?: "comparable" | "mixed_definition_versions" | "mixed_windows" | "not_comparable" | null;
  /**
   * Factor keys from a loaded PREDICTIVE factor distribution. They are model
   * judgments, never measured evidence. Retained for call compatibility only:
   * presentation never names them as coaching evidence.
   */
  experimentalFactorKeys?: readonly string[];
  /** True when an informative experimental estimate is visible for this metric. */
  experimentalVisible?: boolean;
  /** Radar-quality median of a visible estimate (0..1). */
  experimentalMedian?: number | null;
}

export interface MetricInspectorSentences {
  kind: MetricInspectorKind;
  /** Canonical presentation state (`unknown` legacy pending normalizes to `pending`). */
  state: MetricInspectorInput["state"];
  /** What this state or exact value means for the analyzed window. */
  meaning: string;
  /** The safest next action plus how to verify it. */
  action: string;
  audience: string;
  basis: string;
  evidenceAuthority: string | null;
  explanationCode: string | null;
  suppressionReason: MetricInspectorInput["suppressionReason"];
  comparabilityState: MetricInspectorInput["comparabilityState"];
}

export type MetricExplainerProvenance = "measured" | "experimental" | "not_measured";

export const METRIC_EXPLAINER_PROVENANCE_LABELS: Readonly<Record<MetricExplainerProvenance, string>> = {
  measured: "Measured · typed evidence",
  experimental: "Experimental · model estimate",
  not_measured: "Not measured · state only",
};

export interface MetricExplainerSentences {
  explanation: string;
  improvement: string;
  provenanceLabel: string;
  basis: string;
}

function completeSentence(value: string): string {
  const trimmed = value.trim();
  return /[.!?]$/u.test(trimmed) ? trimmed : `${trimmed}.`;
}

/**
 * Compatibility projection retained for the V2 explainer API. It deliberately
 * delegates action semantics to the same guidance registry as the richer
 * state-aware inspector, so the legacy two-field contract remains equal in
 * meaning while new surfaces preserve typed state and receipt metadata.
 */
export function metricExplainerSentences(
  metricKey: string,
  input: {
    provenance?: MetricExplainerProvenance;
    numericValue?: number | null;
    projectionVersion?: MetricHelpProjectionVersion | null;
  } = {},
): MetricExplainerSentences | null {
  const help = metricHelpV2(metricKey, "en", input.projectionVersion);
  if (help === null) return null;
  const provenance = input.provenance ?? "not_measured";
  const numericValue = input.numericValue ?? null;
  const direction = METRIC_HELP_V2_DIRECTIONS[metricKey] ?? "higher_is_better";
  const guidance = sessionMetricGuidance(metricKey, {
    state: provenance === "measured" && numericValue !== null ? "known" : "missing",
    numericValue,
    direction,
    factorKeys: [],
    experimentalOnly: provenance === "experimental",
  });
  return {
    explanation: completeSentence(help.entry.meaning),
    improvement: completeSentence(guidance.action),
    provenanceLabel: provenance === "measured"
      ? "Measured · typed evidence"
      : provenance === "experimental"
        ? "Experimental model estimate · not measured"
        : "Not measured in this scope",
    basis: guidance.basis,
  };
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function lowerFirst(value: string): string {
  return value.charAt(0).toLowerCase() + value.slice(1);
}

function inspectorKind(input: MetricInspectorInput): MetricInspectorKind {
  if (input.state === "pending") return "pending";
  if (input.state !== "known" && input.explanationCode === "episode_horizon_open") return "pending";
  if (input.state === "suppressed") return "suppressed";
  if (input.state === "withheld") return "withheld";
  if (input.state === "unavailable") return "unavailable";
  if (input.state === "not_applicable") return "not_applicable";
  if (input.state === "execution_error") return "execution_error";
  if (input.state === "abstained") return "abstained";
  if (input.state === "missing") return input.experimentalVisible ? "experimental" : "missing";
  if (input.state === "unknown") return input.experimentalVisible ? "experimental" : "unknown";
  if (input.numericValue === null) return input.experimentalVisible ? "experimental" : "unknown";
  const radarQuality = input.direction === "lower_is_better" ? 1 - input.numericValue : input.numericValue;
  return radarQuality === 0 ? "zero" : "measured";
}

/**
 * Exactly two deterministic sentences for the selected-metric inspector: what
 * the typed state or exact known value means for the analyzed window, and the safest
 * next action with its verification. No validated quality bands are declared,
 * and predictive factor probabilities are never described as measured.
 */
export function metricInspectorSentences(input: MetricInspectorInput): MetricInspectorSentences {
  const resolvedHelp = metricHelpV2(input.metricKey, "en", input.projectionVersion);
  const help = resolvedHelp?.entry;
  const r5ReviewedProfile = resolvedHelp?.definitionScope === "r5_reviewed_profile";
  const reviewedProfileProjection = input.projectionVersion === R8_PROJECTION
    ? "r8"
    : input.projectionVersion === R7_PROJECTION ? "r7"
    : input.projectionVersion === R6_PROJECTION ? "r6" : "r5";
  const reviewedPlanProjection = input.projectionVersion === R8_PROJECTION
    ? "r8"
    : input.projectionVersion === R7_PROJECTION ? "r7" : "r6";
  const reviewedActionProjection = input.projectionVersion === R8_PROJECTION ? "r8" : "r7";
  const r8VerifiedRequirement = input.projectionVersion === R8_PROJECTION
    && input.metricKey === "outcome.verified_requirement_coverage";
  const projectionBoundDefinition = resolvedHelp !== null
    && resolvedHelp.definitionScope !== "historical_candidate";
  const definitionLabel = resolvedHelp === null
    ? "versioned local"
    : metricHelpV2DefinitionLabel(resolvedHelp);
  const unit = help?.observationUnit ?? "observation";
  const unitSingular = observationUnitSingular(unit);
  const objective = metricHelpV2IsObjective(input.metricKey) || (input.explanationCode ?? "").includes("objective_");
  const kind = inspectorKind(input);
  const sessionState = input.state === "suppressed" || input.state === "withheld" || input.state === "unavailable"
    ? "unknown"
    : input.state;
  const guidance = sessionMetricGuidance(input.metricKey, {
    state: sessionState,
    numericValue: input.numericValue,
    direction: input.direction,
    explanationCode: input.explanationCode ?? null,
    factorKeys: [],
    experimentalOnly: kind === "experimental",
  });
  const decision = metricDecisionGuidance(input.metricKey);
  const fraction = input.numerator !== null && input.denominator !== null
    ? `${input.numerator}/${input.denominator} ${observationUnitCounted(unit)}`
    : `an unexposed fraction of ${observationUnitCounted(unit)}`;
  let meaning: string;
  let action = `${guidance.action.replace(/[.\s]+$/u, "")} — verify: ${lowerFirst(guidance.verification)}`;
  switch (kind) {
    case "pending":
      meaning = `Pending: the newest episode is still open, so ${input.label} cannot be judged yet in the analyzed window; this is open evidence, not a zero and not a measurement.`;
      break;
    case "suppressed":
      meaning = input.suppressionReason === "overlap_or_differencing"
        ? `Suppressed: the contributor publication minimum was met, but this exact ${input.label} release could expose a member through overlap or differencing; no value or contributor count is published.`
        : input.suppressionReason === "query_identity_mismatch"
          ? `Suppressed: the immutable query identity for ${input.label} was reused with different inputs, so the release failed closed instead of exposing a value.`
          : `Suppressed: the contributing cohort for ${input.label} is below the publication minimum, so no value or contributor count is published.`;
      action = "No member-level action is justified: this is a privacy publication decision, not an individual performance result — verify: review the cohort release policy without attempting to infer hidden contributors.";
      break;
    case "withheld":
      meaning = input.comparabilityState === "mixed_windows"
        ? `Withheld: ${input.label} mixes analysis windows, so a combined fraction would not describe one comparable population.`
        : `Withheld: ${input.label} mixes metric definition versions, so a combined fraction would be misleading and remains unpublished.`;
      action = "Do not compare or combine these observations until one exact definition and window applies — verify: rerun the same reviewed metric contract over a coherent cohort window.";
      break;
    case "unavailable":
      meaning = `Adapter capability missing: this runtime does not expose the evidence family required to produce ${input.label}; absence of a supported adapter is not a zero or a failed measurement.`;
      action = "No user wording can supply this metric: keep it unmeasured until a supported local adapter exists — verify: that adapter produces a fresh sealed receipt before any value is interpreted.";
      break;
    case "not_applicable":
      if (r8VerifiedRequirement && input.explanationCode === "reviewed_requirement_set_empty") {
        meaning = `Not applicable: the exact native-reviewed active-requirement set is empty, so ${input.label} has no denominator and no value is implied.`;
        action = "No verification action is justified for this empty reviewed set — verify: reassess only after a fresh native review establishes at least one active requirement.";
      } else {
        meaning = `Not applicable: no eligible ${unitSingular} was observed in this window, so ${input.label} has nothing to score and no value is implied.`;
        action = `No action for this window: there was no eligible ${unitSingular} to change — verify: reassess only when a later comparable window contains an eligible opportunity.`;
      }
      break;
    case "unknown":
      if (r8VerifiedRequirement && input.explanationCode === "reviewed_requirement_authority_unavailable") {
        meaning = `Unknown: this sealed r8 receipt has no exact native-reviewed active-requirement authority, so ${input.label} has no defensible denominator and was not converted to zero.`;
        action = "Complete and natively confirm Reviewed requirement-to-plan evidence for the exact source window, then run a fresh analysis — verify: the new sealed r8 receipt binds the complete reviewed active-requirement set before any verification result is interpreted.";
      } else if (r8VerifiedRequirement && input.explanationCode === "reviewed_requirement_authority_invalid") {
        meaning = `Unknown: the reviewed active-requirement authority failed exact source-window or confirmation validation, so ${input.label} rejected the stale denominator rather than scoring it.`;
        action = "Replace the invalid requirement-plan authority through its native review workflow, then run a fresh analysis — verify: the new sealed r8 receipt binds the exact current confirmation, evidence fingerprint, and active-requirement set.";
      } else if (r8VerifiedRequirement && input.explanationCode === "requirement_verification_evidence_unavailable") {
        meaning = `Unknown: an exact reviewed active-requirement denominator exists, but its local verification evidence is unavailable, so every unresolved requirement remains unknown rather than failed or zero.`;
        action = "Restore the local verification-evidence reader or issue exact app-issued verification results or separately typed native human acceptances, then run a fresh analysis — verify: the sealed r8 receipt preserves the reviewed denominator and assistant completion claims never enter the authority.";
      } else if (r8VerifiedRequirement && input.explanationCode === "requirement_verification_authority_invalid") {
        meaning = `Unknown: verification authority was stale, foreign, tampered, or otherwise invalid for this exact reviewed requirement set, so ${input.label} failed closed rather than converting missing proof to failure.`;
        action = "Repair or replace the invalid local verification authority and run a fresh analysis — verify: every app-issued result or separately typed native acceptance matches an exact current reviewed requirement and the new r8 receipt retains no foreign authority.";
      } else if (r8VerifiedRequirement && input.explanationCode === "app_issued_requirement_verification_pending") {
        meaning = `Unknown: exact app-issued verification results or separately typed native human acceptances resolve only part of the reviewed requirement set; the remainder right-censors ${input.label}, and assistant completion claims never close it.`;
        action = "Resolve the remaining reviewed requirements with app-issued verification results or separately typed native human acceptances — verify: a fresh sealed r8 receipt reports zero unresolved requirements before publishing a numeric fraction.";
      } else if (r8VerifiedRequirement && input.explanationCode === "typed_objective_opportunity_count_exceeds_receipt_bound") {
        meaning = `Unknown: the complete reviewed requirement set exceeded the bounded r8 verification receipt, so ${input.label} was withheld rather than truncated, sampled, or converted to zero.`;
        action = "Analyze a smaller coherent sealed window without dropping individual requirements from its complete authority — verify: the next r8 receipt fits the entire reviewed set within its published bound before any value is interpreted.";
      } else if (input.explanationCode === "requirement_action_evidence_unavailable") {
        meaning = `Unknown: this sealed ${reviewedActionProjection} runtime does not expose reviewed requirement-action evidence, so ${input.label} has no defensible link classification and was not converted to zero.`;
        action = `Use a runtime that composes the local ${reviewedActionProjection} requirement-action service, retrieve the exact contract, and create only an inert candidate-index proposal — verify: the app can preview it locally but no value appears until a complete native review is bound to a fresh sealed ${reviewedActionProjection} receipt.`;
      } else if (input.explanationCode === "requirement_action_evidence_confirmation_required") {
        meaning = `Unknown: reviewed requirements and safe action candidates are available for this sealed ${reviewedActionProjection} window, but no complete owned-native review of every clause, redacted candidate descriptor, membership, and explicit empty link is bound; this missing authority is not zero.`;
        action = `Open Reviewed requirement-to-action evidence, cross-check each source_reference_id against its safe event/session timeline, inspect every ephemeral redacted descriptor and proposed membership, acknowledge the exact complete receipt, natively confirm it, then run a fresh analysis — verify: the new sealed ${reviewedActionProjection} receipt reports the exact reviewed measured, right-censored, or no-opportunity state before interpreting it.`;
      } else if (input.explanationCode === "requirement_action_evidence_invalid") {
        meaning = `Unknown: the confirmed requirement-action authority did not revalidate against this exact r6 predecessor, source window, candidate manifest, or complete graph, so ${input.label} failed closed rather than scoring stale links.`;
        action = `Regenerate the inert proposal from the current ${reviewedActionProjection} contract, cross-check every source receipt and descriptor in the session timeline, review every membership and empty link, then natively confirm a replacement — verify: a fresh sealed ${reviewedActionProjection} receipt binds the exact new graph and candidate set.`;
      } else if (input.explanationCode === "requirement_action_evidence_overflow") {
        meaning = `Unknown: the exact requirement, safe-candidate, or link set exceeded the bounded ${reviewedActionProjection} receipt, so ${input.label} was withheld rather than truncated, sampled, or converted to zero.`;
        action = `Analyze a smaller coherent sealed window without dropping individual items from its complete review — verify: the next ${reviewedActionProjection} contract fits every requirement, candidate, and link within its published bounds before any proposal is confirmed.`;
      } else if (input.explanationCode === "requirement_action_candidate_source_incomplete") {
        meaning = `Unknown: the provider adapter could not completely enumerate or decode the safe action candidates for this sealed ${reviewedActionProjection} window, so ${input.label} was withheld rather than treating omitted actions as absent or failed.`;
        action = `Update or enable an adapter that supports the complete typed action-event surface, then analyze a fresh sealed window — verify: the new ${reviewedActionProjection} receipt reports a complete candidate source before creating or reviewing any membership proposal.`;
      } else if (input.explanationCode === "requirement_plan_evidence_unavailable") {
        meaning = `Unknown: this sealed ${reviewedPlanProjection} runtime does not expose the reviewed requirement-plan service, so ${input.label} has no defensible denominator and was not converted to zero.`;
        action = `Enable a runtime that exposes Reviewed requirement-to-plan evidence, then preview a canonical content-free file bound to the exact sealed source run, import it only as an unconfirmed proposal, inspect every local user and PLAN clause, and natively confirm the complete classification — verify: a fresh sealed ${reviewedPlanProjection} receipt binds that confirmed proposal before interpreting a value.`;
      } else if (input.explanationCode === "requirement_plan_evidence_confirmation_required") {
        meaning = `Unknown: the reviewed requirement-plan service is available for this sealed ${reviewedPlanProjection} window, but no owned-native complete classification of every reviewable user request/feedback clause is bound yet, so ${input.label} has no defensible active-requirement denominator and was not converted to zero. One active coordinate is one opportunity; a compound active clause may coarsen multiple atomic requirements, while reviewed exclusions never enter the metric.`;
        action = `Use Reviewed requirement-to-plan evidence below: preview a canonical content-free file bound to this exact source run, import it only as an unconfirmed proposal, open the exact local clause review, inspect every user and PLAN clause including omitted PLAN candidates, check every active disposition/link and every exclusion reason/basis, natively confirm it, then run a fresh analysis — verify: the new sealed ${reviewedPlanProjection} receipt binds that confirmed proposal before interpreting a value.`;
      } else if (input.explanationCode === "requirement_plan_evidence_invalid") {
        meaning = `Unknown: the confirmed requirement-to-plan coordinates did not revalidate against this exact local source window, so ${input.label} failed closed instead of scoring stale or wrong-role links.`;
        action = `Regenerate the content-free proposal from the current contract and source run, review every candidate classification, exclusion reason/basis, disposition, link, and included or omitted PLAN clause, then natively confirm the replacement — verify: a fresh sealed ${reviewedPlanProjection} receipt reports the exact reviewed measured, right-censored, or no-opportunity state before interpreting it.`;
      } else if ((input.explanationCode ?? "").includes("objective_authority") || input.explanationCode === "typed_objective_absent") {
        meaning = `Unknown: the active provider adapter does not expose the authoritative opportunity links and typed receipts ${input.label} requires; prose and model estimates cannot substitute, so this is not a low value.`;
      } else if (input.explanationCode === "opportunity_family_unobservable") {
        meaning = `Unknown: the active provider adapter cannot yet own the typed opportunity family ${input.label} requires; the missing event family is not counted as zero.`;
      } else if (input.explanationCode === "source_reconciliation_incomplete" || input.explanationCode === "semantic_units_unavailable") {
        meaning = `Unknown: semantic-unit reconciliation was not complete for this exact analyzed window, so ${input.label} was withheld instead of scoring a partial source as complete.`;
      } else if (input.explanationCode === "opportunity_set_undetermined") {
        meaning = r5ReviewedProfile
          ? `Unknown: the reviewed task profile exposes no ${unitSingular} denominator, so ${input.label} has no defensible value and was not converted to zero.`
          : `Unknown: the task profile did not declare the expected ${unitSingular} set, so ${input.label} has no defensible denominator and was not converted to zero.`;
        if (r5ReviewedProfile) {
          action = `Use Reviewed metric denominators below: save an immutable profile revision with this metric's exact expected slots or count, run a fresh analysis, and verify that the selected sealed ${reviewedProfileProjection} receipt exactly binds that revision before interpreting a value.`;
        } else if (DECLARED_TASK_PROFILE_METRIC_KEYS.has(input.metricKey)) {
          action = `This analyzed window cannot be repaired with extra wording: the app still needs a separately confirmed task profile declaring its expected ${unitSingular} set — verify: configure that reviewed profile workflow, bind it to a fresh analysis, and confirm the new sealed receipt before interpreting a value.`;
        }
      } else if (input.explanationCode === "diagnostic_task_not_detected") {
        meaning = `Unknown: this window did not establish that the request was diagnostic, so ${input.label} cannot assume that problem-evidence opportunities applied.`;
      } else {
        meaning = objective
          ? `Unknown: no authoritative typed receipt or link is available for ${input.label} in this sealed receipt; prose is not accepted, so this is missing evidence, not a low value.`
          : `Unknown: this receipt exposes no eligible ${unitSingular} or the event family ${input.label} needs, so no value exists; this is missing evidence, not a low value.`;
      }
      break;
    case "abstained":
      meaning = objective
        ? `Needs evidence: authoritative typed links or receipts are missing for ${input.label}, so the local contract abstained instead of scoring prose.`
        : `Needs evidence: the observed clauses did not support a defensible value for ${input.label}, so the analysis abstained instead of guessing.`;
      break;
    case "execution_error":
      meaning = `Error: the local analysis stage for ${input.label} failed before producing a value; the last valid receipt stands and this is not a low score.`;
      break;
    case "missing":
      meaning = `No record: ${input.label} is not present in this sealed receipt, so nothing was measured or estimated for it.`;
      break;
    case "experimental":
      meaning = `Experimental only: ${input.label} has no measured value in the analyzed window; the visible ${input.experimentalMedian == null ? "estimate" : `${percent(input.experimentalMedian)} radar-quality estimate`} is an uncalibrated model range, not a measurement, and its model-factor probabilities are not coaching evidence.`;
      break;
    case "zero":
      meaning = input.direction === "lower_is_better"
        ? projectionBoundDefinition
          ? `Known radar-quality zero: ${fraction} met the ${definitionLabel} contract at a raw rate of ${percent(input.numericValue!)}, so radar quality is 0% and the point sits at the center; a real projection-bound value, not missing data or objective outcome proof.`
          : `Known radar-quality zero: ${fraction} carried the marker (raw ${percent(input.numericValue!)}), so radar quality is 0% and the point sits at the center; a real measured value, not missing data.`
        : r5ReviewedProfile
          ? `Known radar-quality zero: ${fraction} met the sealed ${reviewedProfileProjection} reviewed-profile contract for ${input.label}, so the point sits at the radar center; a real deterministic method-only value, not missing data or objective outcome proof.`
          : projectionBoundDefinition
            ? `Known radar-quality zero: ${fraction} met the ${definitionLabel} contract for ${input.label}, so the point sits at the radar center; a real projection-bound value, not missing data or objective outcome proof.`
            : `Known radar-quality zero: ${fraction} met the versioned local contract for ${input.label}, so the point sits at the radar center; a real measured value, not missing data.`;
      break;
    case "measured":
    default: {
      const radarQuality = input.direction === "lower_is_better" ? 1 - input.numericValue! : input.numericValue!;
      meaning = input.direction === "lower_is_better"
        ? projectionBoundDefinition
          ? `Measured: ${fraction} met the ${definitionLabel} contract, a raw rate of ${percent(input.numericValue!)} (radar quality ${percent(radarQuality)} because lower is better); this projection-bound value is not objective outcome proof, a validated quality band, or a calibrated score.`
          : `Measured: ${fraction} carried the marker, a raw rate of ${percent(input.numericValue!)} (radar quality ${percent(radarQuality)} because lower is better); this exact versioned candidate value is not a validated quality band.`
        : r5ReviewedProfile
          ? `Measured: ${fraction} met the sealed ${reviewedProfileProjection} reviewed-profile contract for ${input.label}, exactly ${percent(radarQuality)}; this deterministic method-only value is not objective outcome proof, a validated quality band, or a calibrated score.`
          : projectionBoundDefinition
            ? `Measured: ${fraction} met the ${definitionLabel} contract for ${input.label}, exactly ${percent(radarQuality)}; this projection-bound value is not objective outcome proof, a validated quality band, or a calibrated score.`
            : `Measured: ${fraction} met the versioned local contract for ${input.label}, exactly ${percent(radarQuality)}; this versioned candidate value is not a validated quality band or calibrated score.`;
      break;
    }
  }
  if (kind === "measured" || kind === "zero") {
    const allMet = input.direction === "lower_is_better"
      ? input.numerator === 0
      : input.numerator !== null && input.numerator === input.denominator;
    action = allMet
      ? `Nothing to change for this window: every observed ${unitSingular} already met the contract, so keep that practice visible — verify: ${lowerFirst(decision.confirmWith)}`
      : `Safest next step: ${lowerFirst(decision.tryNext).replace(/[.\s]+$/u, "")} — verify: ${lowerFirst(decision.confirmWith)}`;
  }
  return {
    kind,
    state: kind === "pending" ? "pending" : input.state,
    meaning,
    action,
    audience: guidance.audience,
    basis: kind === "measured" || kind === "zero" ? "measured" : guidance.basis,
    evidenceAuthority: input.evidenceAuthority ?? null,
    explanationCode: kind === "pending" ? "episode_horizon_open" : input.explanationCode ?? null,
    suppressionReason: input.suppressionReason ?? null,
    comparabilityState: input.comparabilityState ?? null,
  };
}
