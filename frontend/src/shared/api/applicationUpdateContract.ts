import type { ApplicationUpdateStatus } from "./contracts";

const EXACT_KEYS = new Set([
  "contract_version",
  "instance_id",
  "revision",
  "contains_private_data",
  "installed_version",
  "channel",
  "state",
  "available_version",
  "artifact_size_bytes",
  "downloaded_bytes",
  "last_checked_at",
  "reason_code",
  "verification_code",
  "can_check",
  "can_stage",
  "can_cancel",
  "can_retry",
  "can_apply",
  "can_verify",
  "package_review",
]);

const STATES = new Set([
  "unconfigured",
  "ready_to_check",
  "checking",
  "current",
  "available",
  "staging",
  "staged",
  "verifying",
  "failed",
]);

const REASONS = new Set([
  "release_feed_unconfigured",
  "release_feed_unavailable",
  "manifest_rejected",
  "artifact_download_failed",
  "artifact_verification_failed",
  "staging_interrupted",
  "staging_cleanup_unconfirmed",
]);

const VERIFICATION_CODES = new Set([
  "bad_signature",
  "channel_mismatch",
  "current_version",
  "downgrade",
  "expired",
  "invalid_encoding",
  "invalid_schema",
  "manifest_too_large",
  "minimum_version_unsupported",
  "not_yet_published",
  "signature_too_large",
  "unknown_key",
  "replayed_release",
  "release_identity_conflict",
]);

const PACKAGE_REVIEW_REASONS = new Set([
  "unsupported_platform",
  "unsupported_package",
  "package_io_failed",
  "package_changed",
  "release_binding_mismatch",
  "archive_invalid",
  "manifest_invalid",
  "identity_mismatch",
  "signature_invalid",
  "signature_unverifiable",
  "signer_mismatch",
]);

const PACKAGE_REVIEW_STATES = new Set([
  "not_configured", "not_staged", "not_checked", "checking", "verified", "rejected",
]);

const SEMVER = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/u;
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u;
const MAX_ARTIFACT_BYTES = 4 * 1024 ** 3;
const INSTANCE_ID = /^[0-9a-f]{32}$/u;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).length === EXACT_KEYS.size
    && Object.keys(value).every((key) => EXACT_KEYS.has(key));
}

function isSemver(value: unknown): value is string {
  return typeof value === "string" && value.length <= 32 && SEMVER.test(value);
}

function isRevision(value: unknown): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= 0;
}

function isNullablePositiveBytes(value: unknown): value is number | null {
  return value === null
    || (typeof value === "number" && Number.isSafeInteger(value) && value > 0 && value <= MAX_ARTIFACT_BYTES);
}

function isNullableDownloadedBytes(value: unknown): value is number | null {
  return value === null
    || (typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= MAX_ARTIFACT_BYTES);
}

function isNullableCheckedAt(value: unknown): value is string | null {
  return value === null
    || (typeof value === "string" && UTC_TIMESTAMP.test(value) && Number.isFinite(Date.parse(value)));
}

function isPackageReview(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value) || Object.keys(value).length !== 3
    || !Object.keys(value).every((key) => ["state", "reason_code", "checked_at"].includes(key))
    || typeof value.state !== "string" || !PACKAGE_REVIEW_STATES.has(value.state)
    || !(value.reason_code === null || (typeof value.reason_code === "string"
      && (VERIFICATION_CODES.has(value.reason_code) || PACKAGE_REVIEW_REASONS.has(value.reason_code))))
    || !isNullableCheckedAt(value.checked_at)) return false;
  const terminal = value.state === "verified" || value.state === "rejected";
  return terminal === (value.checked_at !== null)
    && (value.state !== "rejected" ? value.reason_code === null : value.reason_code !== null);
}

export class ApplicationUpdatePayloadError extends Error {
  constructor() {
    super("Application update status response was invalid");
    this.name = "ApplicationUpdatePayloadError";
  }
}

function fail(): never {
  throw new ApplicationUpdatePayloadError();
}

export function parseApplicationUpdateStatus(value: unknown): ApplicationUpdateStatus {
  if (
    !isRecord(value)
    || !exactKeys(value)
    || value.contract_version !== "application-update-status.v3"
    || value.contains_private_data !== false
    || typeof value.instance_id !== "string"
    || !INSTANCE_ID.test(value.instance_id)
    || !isRevision(value.revision)
    || !isSemver(value.installed_version)
    || typeof value.channel !== "string"
    || !["stable", "beta"].includes(value.channel)
    || typeof value.state !== "string"
    || !STATES.has(value.state)
    || !(value.available_version === null || isSemver(value.available_version))
    || !isNullablePositiveBytes(value.artifact_size_bytes)
    || !isNullableDownloadedBytes(value.downloaded_bytes)
    || !isNullableCheckedAt(value.last_checked_at)
    || !(value.reason_code === null || (typeof value.reason_code === "string" && REASONS.has(value.reason_code)))
    || !(value.verification_code === null || (typeof value.verification_code === "string" && VERIFICATION_CODES.has(value.verification_code)))
    || typeof value.can_check !== "boolean"
    || typeof value.can_stage !== "boolean"
    || typeof value.can_cancel !== "boolean"
    || typeof value.can_retry !== "boolean"
    || typeof value.can_apply !== "boolean"
    || value.can_apply
    || typeof value.can_verify !== "boolean"
    || !isPackageReview(value.package_review)
  ) fail();

  const hasRelease = value.available_version !== null;
  const hasSize = value.artifact_size_bytes !== null;
  const hasCheck = value.last_checked_at !== null;
  const hasVerification = value.verification_code !== null;
  const actions = [value.can_check, value.can_stage, value.can_cancel, value.can_retry, value.can_apply];
  const exactActions = (expected: boolean[]) => actions.every((item, index) => item === expected[index]);
  const noReview = value.package_review.state === "not_configured" || value.package_review.state === "not_staged";

  if (value.state === "verifying") {
    if (value.reason_code !== null || value.verification_code !== null
      || value.can_verify || actions.some(Boolean) || value.package_review.state !== "checking"
      || !hasRelease || !hasSize || !hasCheck || value.downloaded_bytes !== value.artifact_size_bytes) fail();
  } else if (value.state === "unconfigured") {
    if (
      value.reason_code !== "release_feed_unconfigured"
      || hasVerification || hasRelease || hasSize || hasCheck || value.downloaded_bytes !== null
      || !exactActions([false, false, false, false, false])
      || value.can_verify || value.package_review.state !== "not_configured"
    ) fail();
  } else if (value.state === "ready_to_check") {
    if (
      value.reason_code !== null || hasVerification || hasRelease || hasSize || hasCheck
      || value.downloaded_bytes !== null || !exactActions([true, false, false, false, false])
      || value.can_verify || !noReview
    ) fail();
  } else if (value.state === "checking") {
    if (
      value.reason_code !== null || hasVerification || hasRelease || hasSize || hasCheck
      || value.downloaded_bytes !== null || !exactActions([false, false, false, false, false])
      || value.can_verify || !noReview
    ) fail();
  } else if (value.state === "current") {
    if (
      value.reason_code !== null || hasVerification || hasRelease || hasSize || !hasCheck
      || value.downloaded_bytes !== null || !exactActions([true, false, false, false, false])
      || value.can_verify || !noReview
    ) fail();
  } else if (value.state === "available") {
    if (
      value.reason_code !== null || hasVerification || !hasRelease || !hasSize || !hasCheck
      || ![null, 0].includes(value.downloaded_bytes)
      || !value.can_check || value.can_cancel || value.can_retry || value.can_apply
      || value.can_verify || !noReview
    ) fail();
  } else if (value.state === "staging") {
    if (
      value.reason_code !== null || hasVerification || !hasRelease || !hasSize || !hasCheck
      || value.downloaded_bytes === null
      || value.downloaded_bytes > (value.artifact_size_bytes as number)
      || value.can_check || value.can_stage || value.can_retry || value.can_apply
      || value.can_verify || !noReview
    ) fail();
  } else if (value.state === "staged") {
    if (
      value.reason_code !== null || hasVerification || !hasRelease || !hasSize || !hasCheck
      || value.downloaded_bytes !== value.artifact_size_bytes
      || !exactActions([true, false, false, false, false])
      || (value.can_verify
        ? !["not_checked", "verified", "rejected"].includes(value.package_review.state as string)
        : value.package_review.state !== "not_configured")
    ) fail();
  } else {
    if (value.reason_code === null || value.can_stage || value.can_cancel || value.can_apply
      || value.can_verify || !noReview) fail();
    if (value.reason_code === "staging_cleanup_unconfirmed" && (value.can_check || value.can_retry)) fail();
    if (value.can_retry && ![
      "release_feed_unavailable",
      "artifact_download_failed",
      "staging_interrupted",
    ].includes(value.reason_code as string)) fail();
    const rejectedManifest = value.reason_code === "manifest_rejected";
    if (rejectedManifest !== hasVerification) fail();
  }

  return value as unknown as ApplicationUpdateStatus;
}
