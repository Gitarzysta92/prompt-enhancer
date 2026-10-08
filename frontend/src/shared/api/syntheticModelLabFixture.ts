import type { ModelLabInventory } from "./contracts";

/** Fictional persisted evaluation receipts; no session or private evidence exists. */
export const SYNTHETIC_MODEL_LAB_INVENTORY: ModelLabInventory = {
  contract_version: "model-lab-inventory-v1",
  scope: "synthetic_only",
  session_data_read: false,
  private_evidence_returned: false,
  registered_plan_count: 1,
  synthetic_execution_count: 2,
  model_run_count: 8,
  model_vote_count: 4,
  metric_estimate_count: 2,
  activation_outcome: "synthetic_or_insufficient",
  activation_allowed: false,
  plans: [
    {
      plan_fingerprint: "b".repeat(64),
      plan_key: "synthetic-balanced-quality",
      plan_version: "plan-1",
      route: "balanced",
      metric_question_count: 1,
      synthetic_execution_count: 2,
      model_run_count: 8,
      model_vote_count: 4,
      metric_estimate_count: 2,
      activation_outcome: "synthetic_or_insufficient",
      activation_allowed: false,
    },
  ],
};
