import {
  METRIC_CONTRACT_V2_REGISTRY_VERSION,
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  type MetricDefinitionMismatch,
} from "../../shared/api/metricPublicationV2Contract";

export const METRIC_DEFINITIONS_OUT_OF_DATE_TITLE = "Metric definitions are out of date · update this client";

const MISMATCH_COPY: Readonly<Record<MetricDefinitionMismatch, string>> = {
  registry_version: "a different metric registry version",
  contract_set_fingerprint: "a different contract-set fingerprint",
  metric_contract_fingerprint: "a per-metric contract fingerprint this client does not know",
  guidance_contract_version: "a different guidance contract version",
  guidance_template_catalog_version: "a different guidance template catalog",
  guidance_template_identity: "a guidance template identity outside this client's reviewed catalog",
  projection_version: "a newer metric projection identity this client has not reviewed",
  metric_profile_binding: "a newer reviewed-profile binding identity this client has not reviewed",
  requirement_plan_evidence_binding: "a newer requirement-plan evidence binding this client has not reviewed",
  requirement_action_evidence_binding: "a newer requirement-action evidence binding this client has not reviewed",
  requirement_verification_evidence_binding: "a newer requirement-verification evidence binding this client has not reviewed",
};

/** Pure copy for the distinct definitions-out-of-date state (no reconnect wording, no stale values). */
export function metricDefinitionsOutOfDateCopy(mismatch: MetricDefinitionMismatch): {
  title: string;
  detail: string;
  binding: string;
} {
  return {
    title: METRIC_DEFINITIONS_OUT_OF_DATE_TITLE,
    detail: `The local service published canonical V2 metrics under ${MISMATCH_COPY[mismatch]}, so this client's metric meanings and next-action wording cannot be trusted for it. All twenty values and their guidance are withheld until you update the client; no earlier receipt is shown beside the new one. This is a version mismatch, not a connection problem.`,
    binding: `This client is bound to registry ${METRIC_CONTRACT_V2_REGISTRY_VERSION} · contract set ${METRIC_CONTRACT_V2_SET_FINGERPRINT.slice(0, 12)}…`,
  };
}

/**
 * Distinct alert shown INSTEAD of the metric workspace when the compatibility
 * gate refuses a publication. It never renders beside values: callers clear the
 * retained run before mounting it.
 */
export function MetricDefinitionsOutOfDateAlert({
  mismatch,
  compact = false,
}: {
  mismatch: MetricDefinitionMismatch;
  compact?: boolean;
}) {
  const copy = metricDefinitionsOutOfDateCopy(mismatch);
  return (
    <section
      aria-label="Metric definitions out of date"
      className={`metric-definitions-alert${compact ? " metric-definitions-alert--compact" : ""}`}
      data-mismatch={mismatch}
      data-state="definitions_out_of_date"
      role="alert"
    >
      <strong>{copy.title}</strong>
      <p>{copy.detail}</p>
      <small>{copy.binding} · 0/20 values shown · 0/20 guidance receipts shown</small>
    </section>
  );
}
