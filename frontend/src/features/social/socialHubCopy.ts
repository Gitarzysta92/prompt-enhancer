import type {
  FileConsentState,
  FileIntegrityState,
  SocialCapabilityReason,
  SocialOrigin,
  SocialPermissionAction,
  SocialRole,
} from "../../shared/api/socialHub";

/**
 * Exhaustive copy catalogs over the social port unions, so a new code fails
 * type-checking instead of rendering an empty label. Every sentence describes
 * what is true on this device; none promises delivery, storage, or encryption.
 */
export const SOCIAL_ORIGIN_LABELS: Readonly<Record<SocialOrigin, string>> = {
  synthetic_fixture: "Fictional fixture · nothing is delivered",
  local_loopback: "Local runtime · no social service",
};

export const SOCIAL_REASON_COPY: Readonly<Record<SocialCapabilityReason, string>> = {
  synthetic_fixture: "Every person, message, reaction, and file offer here is invented fixture data. Actions change only this browser's memory.",
  local_runtime_has_no_social_service: "This runtime has no social coordination service, so no friends, conversations, presence, or file offers exist here. Nothing is hidden behind this notice; the counts are exactly zero.",
};

export const ROLE_LABELS: Readonly<Record<SocialRole, string>> = {
  owner: "Owner",
  moderator: "Moderator",
  member: "Member",
  guest: "Guest",
};

export const PERMISSION_LABELS: Readonly<Record<SocialPermissionAction, string>> = {
  post: "Post messages",
  react: "React",
  start_thread: "Start or reply in threads",
  share_files: "Offer files",
  invite: "Invite people",
  manage_roles: "Manage roles",
};

export const CONSENT_LABELS: Readonly<Record<FileConsentState, string>> = {
  pending: "Consent pending",
  granted: "Consent granted",
  declined: "Consent declined",
};

export const INTEGRITY_LABELS: Readonly<Record<FileIntegrityState, string>> = {
  not_started: "Integrity not checked yet",
  verifying: "Verifying integrity",
  verified: "Integrity verified (fixture digest)",
  mismatch: "Integrity mismatch",
};

export const SOCIAL_BOUNDARY_COPY =
  "Messages, reactions, requests, and offers live only in this browser's memory: nothing is delivered to another device, stored durably, synced, or encrypted. File bytes would travel directly between the two devices; the coordination service holds only metadata and never a copy.";

export const FILE_SHARING_BOUNDARY_COPY =
  "Direct file sharing is a UI simulation with metadata only. No file is read from disk, no path is exposed, and no bytes exist; the progress, integrity, expiry, and revoke states show how a device-to-device exchange would be brokered without the coordination service storing anything. Direct path only: there is no relay and no TURN, so a symmetric NAT or CGNAT on either side is shown as “no direct path” rather than silently routed elsewhere.";

export const ENCRYPTION_COPY =
  "End-to-end encryption is not implemented in this demo. Even in a future encrypted service, the central coordination plane would still observe relationship (who talks to whom), timing, availability, and size-class metadata; it would never see file bytes, which do not traverse or rest on it.";

export const GROUP_ACCESS_COPY =
  "Every group is invite-only with a finite recipient list. There is no public directory, no discoverable channel, and no join link.";

export const PRESENCE_POLICY_COPY =
  "Presence is an explicit opt-in: you choose whether to share a coarse, self-declared level (online, away, do not disturb, offline). It is never derived from analyzer activity — sessions, prompts, and metrics do not set it — and “not shared” means a person has not opted in, which is not the same as offline.";

export const PAYLOAD_POLICY_COPY =
  "The application never auto-inserts analyzer sessions, prompts, metrics, or explanations into a chat message or file-share payload; there is no share-to-chat control. This is an application boundary, not inspection of text a person types.";

export const DATA_CONTROLS_COPY =
  "No export or delete-my-data control is offered because nothing lives on a server to export or delete; every message, reaction, request, and offer here exists only in this browser's memory.";

export const OFFLINE_OFFER_QUEUE_COPY =
  "If you offer a file while offline, the metadata offer waits on your device with a bounded expiry and never on the coordination plane; recipients can consent, but bytes move only while you are online and a direct path exists.";

export const REVOKE_COPY =
  "Revoke stops any further bytes; it cannot recall bytes a recipient already downloaded.";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function shortUtcTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  return `${date.toISOString().slice(0, 10)} ${date.toISOString().slice(11, 16)} UTC`;
}
