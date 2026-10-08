import type {
  ControlPlaneReadiness,
  ControlPlaneReadinessGap,
} from "./contracts";

export const CONTROL_PLANE_READINESS_CONTRACT_VERSION = "control-plane-v2" as const;

/** Closed vocabulary copied from the generated backend schema. */
export const CONTROL_PLANE_READINESS_GAPS: readonly ControlPlaneReadinessGap[] = [
  "production_identity_provider_missing",
  "production_signature_algorithm_missing",
  "production_database_adapter_missing",
  "credential_lifecycle_incomplete",
  "out_of_band_provisioning_only",
  "remote_transport_not_implemented",
  "billing_not_implemented",
  "producer_pipeline_not_connected",
  "disclosure_control_unreviewed",
  "durable_recipient_delivery_not_implemented",
  "backup_and_replica_erasure_not_implemented",
  "governance_review_pending",
];

const READINESS_KEYS = [
  "contract_version",
  "delivery_guarantee",
  "gaps",
  "production_ready",
  "profile",
  "remote_listening_enabled",
] as const;

const KNOWN_GAPS = new Set<string>(CONTROL_PLANE_READINESS_GAPS);

export class ControlPlaneReadinessPayloadError extends Error {
  constructor() {
    super("Local control-plane readiness response was invalid");
    this.name = "ControlPlaneReadinessPayloadError";
  }
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

/**
 * Parse only the loopback development profile. A future production profile is
 * a new trust boundary and deliberately fails closed here.
 */
export function parseControlPlaneReadiness(value: unknown): ControlPlaneReadiness {
  if (
    !isRecord(value)
    || !hasExactKeys(value, READINESS_KEYS)
    || value.contract_version !== CONTROL_PLANE_READINESS_CONTRACT_VERSION
    || value.delivery_guarantee !== "at_least_once_with_monotonic_ack"
    || value.production_ready !== false
    || value.profile !== "development"
    || value.remote_listening_enabled !== false
    || !Array.isArray(value.gaps)
    || value.gaps.length === 0
    || value.gaps.length > CONTROL_PLANE_READINESS_GAPS.length
    || value.gaps.some((gap) => typeof gap !== "string" || !KNOWN_GAPS.has(gap))
  ) {
    throw new ControlPlaneReadinessPayloadError();
  }

  const gaps = value.gaps as ControlPlaneReadinessGap[];
  const canonical = [...gaps].sort();
  if (
    new Set(gaps).size !== gaps.length
    || canonical.some((gap, index) => gap !== gaps[index])
  ) {
    throw new ControlPlaneReadinessPayloadError();
  }

  return {
    contract_version: CONTROL_PLANE_READINESS_CONTRACT_VERSION,
    delivery_guarantee: "at_least_once_with_monotonic_ack",
    gaps: [...gaps],
    production_ready: false,
    profile: "development",
    remote_listening_enabled: false,
  };
}

export function controlPlaneReadinessIsValid(
  value: unknown,
): value is ControlPlaneReadiness {
  try {
    parseControlPlaneReadiness(value);
    return true;
  } catch {
    return false;
  }
}
