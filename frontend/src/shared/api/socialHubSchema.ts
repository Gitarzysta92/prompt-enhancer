/**
 * Typed frontend port for a FUTURE social coordination service.
 *
 * Nothing in the shipped backend implements it. The dashboard consumes the
 * contract only through honest runtime adapters:
 *
 * - a synthetic in-memory fixture (development preview, fictional people,
 *   fictional conversations, metadata-only fictional file offers);
 * - an unavailable adapter for the local loopback runtime that reports the
 *   capability closed and exposes zero people, relationships, messages, and
 *   file offers.
 *
 * Design rules carried by the types themselves:
 * - Every payload states its origin and whether it is fictional, so a fixture
 *   can never be mistaken for a live account, delivery, or storage service.
 * - Delivery is `local_state_only`: UI actions mutate React state on this
 *   device and nothing else. No durability, sync, or encryption is claimed.
 * - File sharing is metadata only. The port never carries file bytes or a
 *   filesystem path; it carries a display name, a size, a media type, and a
 *   fictional digest string. Transfer state is a UI simulation of a direct
 *   device-to-device exchange that a coordination service would only broker:
 *   direct path only, no relay and no TURN, so a symmetric NAT or CGNAT on
 *   either side is an explicit "no direct path" state rather than a fallback.
 * - Presence is an explicit opt-in, coarse, self-declared signal. It is never
 *   derived from analyzer activity (sessions, prompts, metrics), and a person
 *   who has not opted in is "not shared" — which is neither online nor offline.
 * - Groups are invite-only with a finite recipient list. There is no public
 *   directory and nothing is discoverable.
 * - The analyzer never inserts sessions, prompts, metrics, or explanations
 *   into chat or file-share payloads. A person can still type ordinary text;
 *   this is an application boundary, not content inspection.
 */
export const SOCIAL_HUB_PORT_VERSION = "social-hub-port.v0" as const;

export type SocialOrigin = "synthetic_fixture" | "local_loopback";

export type SocialCapabilityState = "available" | "unavailable";

export type SocialCapabilityReason =
  | "synthetic_fixture"
  | "local_runtime_has_no_social_service";

export type SocialDeliveryMode = "local_state_only";

export type SocialEncryptionState = "not_implemented";

/**
 * What a central coordination plane observes even in a future end-to-end
 * encrypted service: who talks to whom, when, whether they are reachable, and
 * roughly how large a transfer is. Stated so the UI never implies "the server
 * sees nothing".
 */
export const COORDINATION_PLANE_METADATA = [
  "relationship",
  "timing",
  "availability",
  "size_class",
] as const;
export type CoordinationPlaneMetadata = typeof COORDINATION_PLANE_METADATA[number];

/** Direct-path reachability of one device: only a direct path exists (no relay, no TURN). */
export type SocialDirectPathState =
  | "available"
  | "unavailable_symmetric_nat"
  | "unavailable_cgnat"
  | "unknown";

export interface SocialCapabilityReport {
  port_version: typeof SOCIAL_HUB_PORT_VERSION;
  origin: SocialOrigin;
  /** Opaque pseudonymous principal; never a username, email, or account id. */
  principal_id: string;
  state: SocialCapabilityState;
  reason: SocialCapabilityReason;
  /** True whenever every identity, message, and file below is invented. */
  fictional: boolean;
  delivery: SocialDeliveryMode;
  encryption: SocialEncryptionState;
  /** Metadata a coordination plane observes regardless of payload encryption. */
  coordination_plane_observes: readonly CoordinationPlaneMetadata[];
  groups: {
    /** Invite-only, finite recipient list; never public and never discoverable. */
    access: "invite_only";
    discoverable: false;
    max_members: number;
  };
  presence: {
    /** Explicit opt-in, coarse, self-declared. */
    model: "explicit_opt_in_coarse";
    /** Presence is never derived from analyzer sessions, prompts, or metrics. */
    derived_from_analyzer_activity: false;
  };
  payload_policy: {
    /** The application never auto-inserts analyzer content into a social payload. */
    analyzer_content: "never_inserted";
  };
  file_sharing: {
    state: SocialCapabilityState;
    /** File bytes are exchanged directly between devices; nothing is stored by the coordination service. */
    transport: "direct_device_to_device_simulated";
    /** Direct path only: no relay, no TURN. */
    path: "direct_only";
    relay: "none";
    turn: "none";
    stored_by_coordination_service: false;
    /** File bytes never traverse or rest on the coordination plane. */
    bytes_on_coordination_plane: "never";
    /** Sender-offline offers wait on the sender's device with bounded expiry, never on the server. */
    offline_offer_queue: "sender_device_bounded_expiry";
  };
  /** There is nothing server-side to export or delete, so no such control is offered. */
  data_controls: {
    export: "not_offered_no_server_data";
    delete: "not_offered_no_server_data";
  };
  checked_at: string;
}

/** Shared capability facts every honest adapter publishes; only origin/state/reason/file-sharing state differ. */
export function socialCapabilityInvariants(): Pick<
  SocialCapabilityReport,
  "delivery" | "encryption" | "coordination_plane_observes" | "groups" | "presence" | "payload_policy" | "data_controls"
> {
  return {
    delivery: "local_state_only",
    encryption: "not_implemented",
    coordination_plane_observes: [...COORDINATION_PLANE_METADATA],
    groups: { access: "invite_only", discoverable: false, max_members: SOCIAL_GROUP_MAX_MEMBERS },
    presence: { model: "explicit_opt_in_coarse", derived_from_analyzer_activity: false },
    payload_policy: { analyzer_content: "never_inserted" },
    data_controls: { export: "not_offered_no_server_data", delete: "not_offered_no_server_data" },
  };
}

/** Coarse, self-declared availability level shared by an opted-in person. */
export type SocialPresenceLevel = "online" | "away" | "do_not_disturb" | "offline";

/**
 * Explicit opt-in presence. `not_shared` means the person has not opted in:
 * it is neither online nor offline and must never be rendered as offline.
 * The signal is coarse and self-declared, and never derived from analyzer
 * activity (sessions, prompts, metrics).
 */
export interface SocialPresenceSignal {
  sharing: "shared" | "not_shared";
  /** Coarse level; null whenever sharing is `not_shared`. */
  level: SocialPresenceLevel | null;
  source: "self_declared_opt_in";
}

/** Rendered presence value: a coarse level, or `not_shared` (which is not offline). */
export type SocialPresence = SocialPresenceLevel | "not_shared";

export type SocialRole = "owner" | "moderator" | "member" | "guest";

export const SOCIAL_ROLES: readonly SocialRole[] = ["owner", "moderator", "member", "guest"];

export interface SocialPerson {
  id: string;
  /** Fictional reserved-example display name; never a real person. */
  display_name: string;
  /** Fictional handle in the reserved example namespace. */
  handle: string;
  presence: SocialPresenceSignal;
  /** Direct-path reachability of this person's device (no relay/TURN exists). */
  direct_path: SocialDirectPathState;
  /** True for the local principal ("me") in the fixture. */
  is_me: boolean;
}

/** Collapse a presence signal to one rendered value; `not_shared` is distinct from `offline`. */
export function presenceValue(signal: SocialPresenceSignal): SocialPresence {
  return signal.sharing === "shared" && signal.level !== null ? signal.level : "not_shared";
}

export type FriendshipState = "friend";

export interface Friendship {
  person_id: string;
  state: FriendshipState;
  since: string;
}

export type FriendRequestDirection = "incoming" | "outgoing";

export type FriendRequestState = "pending" | "accepted" | "declined" | "withdrawn";

export interface FriendRequest {
  id: string;
  person_id: string;
  direction: FriendRequestDirection;
  state: FriendRequestState;
  sent_at: string;
  /** Short fictional note; may be empty. */
  note: string;
}

export type ConversationKind = "dm" | "group_channel";

export type SocialPermissionAction = "post" | "react" | "start_thread" | "share_files" | "invite" | "manage_roles";

export const SOCIAL_PERMISSION_ACTIONS: readonly SocialPermissionAction[] = [
  "post",
  "react",
  "start_thread",
  "share_files",
  "invite",
  "manage_roles",
];

/** Roles allowed to perform each action inside one conversation. */
export type SocialPermissionMatrix = Readonly<Record<SocialPermissionAction, readonly SocialRole[]>>;

export interface ConversationMember {
  person_id: string;
  role: SocialRole;
}

export interface Conversation {
  id: string;
  kind: ConversationKind;
  /** Channel name for group channels; null for DMs (the UI names a DM after its counterpart). */
  name: string | null;
  topic: string | null;
  /** Invite-only with a finite recipient list; there is no public or discoverable channel. */
  access: "invite_only";
  discoverable: false;
  members: readonly ConversationMember[];
  permissions: SocialPermissionMatrix;
  /** Newest message id the local principal has read; null when nothing was read. */
  last_read_message_id: string | null;
  muted: boolean;
}

/** Bounded, finite recipient list for any group; never a public room. */
export const SOCIAL_GROUP_MAX_MEMBERS = 32;

export type MessageKind = "text" | "file_offer" | "system";

export interface MessageReaction {
  emoji: string;
  /** Short accessible name for the emoji, e.g. "thumbs up". */
  label: string;
  person_ids: readonly string[];
}

export interface SocialMessage {
  id: string;
  conversation_id: string;
  author_id: string;
  sent_at: string;
  kind: MessageKind;
  /** Fictional, content-free demo text; never transcript content. */
  body: string;
  /** Root message id when this message belongs to a thread; null for top-level messages. */
  thread_root_id: string | null;
  reactions: readonly MessageReaction[];
  /** For `file_offer` messages, the referenced offer id. */
  file_offer_id: string | null;
}

export type FileOfferState =
  | "awaiting_consent"
  | "transferring"
  | "paused"
  | "verifying"
  | "complete"
  | "integrity_mismatch"
  | "revoked"
  | "expired"
  | "owner_offline"
  /** Created while the sender was offline: waits on the sender's device with bounded expiry, never on a server. */
  | "queued_on_sender"
  /** Owner and recipient are online, but no direct path exists (symmetric NAT / CGNAT) and there is no relay or TURN. */
  | "direct_path_unavailable";

export type FileConsentState = "pending" | "granted" | "declined";

export type FileIntegrityState = "not_started" | "verifying" | "verified" | "mismatch";

export interface FileOfferRecipient {
  person_id: string;
  consent: FileConsentState;
  /** Bytes the recipient has received in the simulation; null until a transfer starts. */
  bytes_received: number | null;
  integrity: FileIntegrityState;
}

/**
 * Metadata-only description of a shared file. It never carries bytes, a
 * filesystem path, or a URL; the digest is a fictional hex string used only
 * to render an integrity-verification state.
 */
export interface FileOfferMetadata {
  display_name: string;
  size_bytes: number;
  media_type: string;
  /** Fictional digest for the demo integrity check; not a real hash of real bytes. */
  digest_hex: string;
}

export interface FileShareOffer {
  id: string;
  conversation_id: string;
  owner_id: string;
  file: FileOfferMetadata;
  recipients: readonly FileOfferRecipient[];
  state: FileOfferState;
  created_at: string;
  expires_at: string;
  /** Owner must be online for a direct transfer; the coordination service holds no copy. */
  requires_owner_online: true;
  stored_by_coordination_service: false;
  /** Where the offer waits while the sender is offline: on the sender's device, never on the server. */
  queue_location: "sender_device";
  /** Direct path only; no relay and no TURN can substitute. */
  transport_path: "direct_only";
  /** Revoke stops future bytes; it cannot recall bytes a recipient already downloaded. */
  revoke_recalls_downloaded_bytes: false;
}

export interface SocialSnapshot {
  port_version: typeof SOCIAL_HUB_PORT_VERSION;
  origin: SocialOrigin;
  fictional: boolean;
  principal_id: string;
  me_person_id: string;
  generated_at: string;
  people: readonly SocialPerson[];
  friendships: readonly Friendship[];
  friend_requests: readonly FriendRequest[];
  conversations: readonly Conversation[];
  messages: readonly SocialMessage[];
  file_offers: readonly FileShareOffer[];
}

export type SocialHubErrorCode =
  | "social_not_served_by_this_runtime"
  | "snapshot_invalid";

export class SocialHubError extends Error {
  readonly code: SocialHubErrorCode;
  constructor(code: SocialHubErrorCode, message: string) {
    super(message);
    this.name = "SocialHubError";
    this.code = code;
  }
}

export function isSocialHubError(value: unknown): value is SocialHubError {
  return value instanceof SocialHubError;
}

export interface SocialHubPort {
  readonly portVersion: typeof SOCIAL_HUB_PORT_VERSION;
  readonly origin: SocialOrigin;
  readonly principalId: string;
  getCapabilities(signal?: AbortSignal): Promise<SocialCapabilityReport>;
  /** Rejects with `social_not_served_by_this_runtime` when the capability is closed. */
  getSnapshot(signal?: AbortSignal): Promise<SocialSnapshot>;
}

const PSEUDONYM = /^[0-9a-f]{64}$/;
const HEX_64 = /^[0-9a-f]{64}$/;
type UnknownRow = Record<string, unknown>;

function unknownRow(value: unknown): UnknownRow | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as UnknownRow
    : null;
}

function exactKeys(value: UnknownRow, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function rowArray(value: unknown): UnknownRow[] | null {
  if (!Array.isArray(value)) return null;
  const rows = value.map(unknownRow);
  return rows.every((row) => row !== null) ? rows as UnknownRow[] : null;
}

function stringArray(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function oneOf(value: unknown, choices: readonly string[]): boolean {
  return typeof value === "string" && choices.includes(value);
}

/** A pseudonymous id must be a string of 64 hex characters; no coercion of arrays or numbers. */
function pseudonym(value: unknown): value is string {
  return typeof value === "string" && PSEUDONYM.test(value);
}

/** A parseable timestamp string; ordering and expiry are compared numerically on it. */
function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function uniqueStrings(values: readonly unknown[]): boolean {
  return values.every((value) => typeof value === "string") && new Set(values).size === values.length;
}

/** File-offer states that imply at least one recipient consented (bytes could only move after consent). */
const OFFER_STATES_REQUIRING_CONSENT: ReadonlySet<string> = new Set([
  "transferring", "paused", "verifying", "complete", "integrity_mismatch",
]);

/** Exact capability validation: malformed or over-claiming adapters fail closed before any snapshot read. */
export function socialCapabilityReportIsValid(
  value: unknown,
  port: Pick<SocialHubPort, "origin" | "principalId" | "portVersion">,
): value is SocialCapabilityReport {
  const root = unknownRow(value);
  if (root === null || !exactKeys(root, [
    "port_version", "origin", "principal_id", "state", "reason", "fictional",
    "delivery", "encryption", "coordination_plane_observes", "groups", "presence",
    "payload_policy", "file_sharing", "data_controls", "checked_at",
  ])) return false;
  const groups = unknownRow(root.groups);
  const presence = unknownRow(root.presence);
  const payloadPolicy = unknownRow(root.payload_policy);
  const fileSharing = unknownRow(root.file_sharing);
  const dataControls = unknownRow(root.data_controls);
  const observes = stringArray(root.coordination_plane_observes);
  if (
    groups === null || presence === null || payloadPolicy === null
    || fileSharing === null || dataControls === null || observes === null
    || !exactKeys(groups, ["access", "discoverable", "max_members"])
    || !exactKeys(presence, ["model", "derived_from_analyzer_activity"])
    || !exactKeys(payloadPolicy, ["analyzer_content"])
    || !exactKeys(fileSharing, [
      "state", "transport", "path", "relay", "turn", "stored_by_coordination_service",
      "bytes_on_coordination_plane", "offline_offer_queue",
    ])
    || !exactKeys(dataControls, ["export", "delete"])
  ) return false;
  const report = value as SocialCapabilityReport;
  if (
    report.port_version !== SOCIAL_HUB_PORT_VERSION
    || port.portVersion !== SOCIAL_HUB_PORT_VERSION
    || report.origin !== port.origin
    || report.principal_id !== port.principalId
    || !PSEUDONYM.test(report.principal_id)
    || report.delivery !== "local_state_only"
    || report.encryption !== "not_implemented"
  ) return false;
  if (
    observes.length !== COORDINATION_PLANE_METADATA.length
    || COORDINATION_PLANE_METADATA.some((item) => !observes.includes(item))
    || report.groups.access !== "invite_only"
    || report.groups.discoverable !== false
    || report.groups.max_members !== SOCIAL_GROUP_MAX_MEMBERS
    || report.presence.model !== "explicit_opt_in_coarse"
    || report.presence.derived_from_analyzer_activity !== false
    || report.payload_policy.analyzer_content !== "never_inserted"
  ) return false;
  if (
    report.file_sharing.transport !== "direct_device_to_device_simulated"
    || report.file_sharing.path !== "direct_only"
    || report.file_sharing.relay !== "none"
    || report.file_sharing.turn !== "none"
    || report.file_sharing.stored_by_coordination_service !== false
    || report.file_sharing.bytes_on_coordination_plane !== "never"
    || report.file_sharing.offline_offer_queue !== "sender_device_bounded_expiry"
    || report.data_controls.export !== "not_offered_no_server_data"
    || report.data_controls.delete !== "not_offered_no_server_data"
  ) return false;
  if (report.origin === "synthetic_fixture") {
    return report.fictional === true
      && report.state === "available"
      && report.reason === "synthetic_fixture"
      && report.file_sharing.state === "available";
  }
  return report.fictional === false
    && report.state === "unavailable"
    && report.reason === "local_runtime_has_no_social_service"
    && report.file_sharing.state === "unavailable";
}

const DIRECT_PATH_STATES = ["available", "unavailable_symmetric_nat", "unavailable_cgnat", "unknown"] as const;
const PRESENCE_LEVELS = ["online", "away", "do_not_disturb", "offline"] as const;
const FILE_OFFER_STATES: readonly FileOfferState[] = [
  "awaiting_consent", "transferring", "paused", "verifying", "complete",
  "integrity_mismatch", "revoked", "expired", "owner_offline", "queued_on_sender",
  "direct_path_unavailable",
];

/** Strict unknown-input parser so a malformed or relabelled snapshot fails closed. */
export function socialSnapshotIsValid(
  value: unknown,
  port: Pick<SocialHubPort, "origin" | "principalId">,
): value is SocialSnapshot {
  const root = unknownRow(value);
  if (root === null || !exactKeys(root, [
    "port_version", "origin", "fictional", "principal_id", "me_person_id", "generated_at",
    "people", "friendships", "friend_requests", "conversations", "messages", "file_offers",
  ])) return false;
  const peopleRows = rowArray(root.people);
  const friendshipRows = rowArray(root.friendships);
  const requestRows = rowArray(root.friend_requests);
  const conversationRows = rowArray(root.conversations);
  const messageRows = rowArray(root.messages);
  const offerRows = rowArray(root.file_offers);
  if (
    peopleRows === null || friendshipRows === null || requestRows === null
    || conversationRows === null || messageRows === null || offerRows === null
  ) return false;
  const snapshot = value as SocialSnapshot;
  if (snapshot.port_version !== SOCIAL_HUB_PORT_VERSION) return false;
  if (snapshot.origin !== port.origin || snapshot.principal_id !== port.principalId) return false;
  if (!oneOf(snapshot.origin, ["synthetic_fixture", "local_loopback"])) return false;
  if (typeof snapshot.fictional !== "boolean") return false;
  if ((snapshot.origin === "synthetic_fixture") !== snapshot.fictional) return false;
  if (
    !pseudonym(snapshot.principal_id) || !pseudonym(snapshot.me_person_id)
    || !timestamp(snapshot.generated_at)
  ) return false;
  if (peopleRows.some((person) => {
    const presence = unknownRow(person.presence);
    return !exactKeys(person, ["id", "display_name", "handle", "presence", "direct_path", "is_me"])
      || !pseudonym(person.id)
      || typeof person.display_name !== "string" || typeof person.handle !== "string"
      || typeof person.is_me !== "boolean" || !oneOf(person.direct_path, DIRECT_PATH_STATES)
      || presence === null || !exactKeys(presence, ["sharing", "level", "source"])
      || !oneOf(presence.sharing, ["shared", "not_shared"])
      || presence.source !== "self_declared_opt_in"
      || (presence.sharing === "not_shared"
        ? presence.level !== null
        : !oneOf(presence.level, PRESENCE_LEVELS));
  })) return false;
  const people = new Set(snapshot.people.map((person) => person.id));
  if (
    people.size !== snapshot.people.length
    || !people.has(snapshot.me_person_id)
    || snapshot.people.filter((person) => person.is_me).length !== 1
    || !snapshot.people.some((person) => person.id === snapshot.me_person_id && person.is_me)
  ) return false;
  // Friendships: one row per other person, never with the local principal.
  if (friendshipRows.some((friendship) => (
    !exactKeys(friendship, ["person_id", "state", "since"])
    || !pseudonym(friendship.person_id) || !people.has(friendship.person_id)
    || friendship.person_id === snapshot.me_person_id
    || friendship.state !== "friend"
    || !timestamp(friendship.since)
  ))) return false;
  if (!uniqueStrings(snapshot.friendships.map((friendship) => friendship.person_id))) return false;
  const liveFriends = new Set(snapshot.friendships.map((friendship) => friendship.person_id));
  if (requestRows.some((request) => (
    !exactKeys(request, ["id", "person_id", "direction", "state", "sent_at", "note"])
    || !pseudonym(request.id) || !pseudonym(request.person_id) || !people.has(request.person_id)
    || request.person_id === snapshot.me_person_id
    || !oneOf(request.direction, ["incoming", "outgoing"])
    || !oneOf(request.state, ["pending", "accepted", "declined", "withdrawn"])
    || !timestamp(request.sent_at) || typeof request.note !== "string"
  ))) return false;
  if (!uniqueStrings(snapshot.friend_requests.map((request) => request.id))) return false;
  if (conversationRows.some((conversation) => {
    const members = rowArray(conversation.members);
    const permissions = unknownRow(conversation.permissions);
    if (
      !exactKeys(conversation, ["id", "kind", "name", "topic", "access", "discoverable", "members", "permissions", "last_read_message_id", "muted"])
      || !pseudonym(conversation.id)
      || !oneOf(conversation.kind, ["dm", "group_channel"])
      || !nullableString(conversation.name) || !nullableString(conversation.topic)
      || conversation.access !== "invite_only" || conversation.discoverable !== false
      || !nullableString(conversation.last_read_message_id) || typeof conversation.muted !== "boolean"
      || members === null || permissions === null
      || members.length === 0 || members.length > SOCIAL_GROUP_MAX_MEMBERS
      || !exactKeys(permissions, SOCIAL_PERMISSION_ACTIONS)
    ) return true;
    if (members.some((member) => (
      !exactKeys(member, ["person_id", "role"])
      || !pseudonym(member.person_id) || !people.has(member.person_id)
      || !oneOf(member.role, SOCIAL_ROLES)
    ))) return true;
    const memberIds = members.map((member) => member.person_id as string);
    if (
      new Set(memberIds).size !== memberIds.length
      || !memberIds.includes(snapshot.me_person_id)
    ) return true;
    if (conversation.kind === "dm") {
      const counterpart = members.find((member) => member.person_id !== snapshot.me_person_id);
      if (
        members.length !== 2
        || !members.some((member) => member.person_id === snapshot.me_person_id)
        || counterpart === undefined
        || !liveFriends.has(counterpart.person_id as string)
      ) return true;
    }
    return SOCIAL_PERMISSION_ACTIONS.some((action) => {
      const roles = stringArray(permissions[action]);
      return roles === null
        || new Set(roles).size !== roles.length
        || roles.some((role) => !SOCIAL_ROLES.includes(role as SocialRole));
    });
  })) return false;
  const conversations = new Set(snapshot.conversations.map((conversation) => conversation.id));
  if (conversations.size !== snapshot.conversations.length) return false;
  const membersByConversation = new Map(snapshot.conversations.map((conversation) => [
    conversation.id,
    new Set(conversation.members.map((member) => member.person_id)),
  ]));
  const isMember = (conversationId: unknown, personId: unknown): boolean => (
    typeof conversationId === "string" && typeof personId === "string"
    && (membersByConversation.get(conversationId)?.has(personId) ?? false)
  );
  if (messageRows.some((message) => {
    const reactions = rowArray(message.reactions);
    return !exactKeys(message, ["id", "conversation_id", "author_id", "sent_at", "kind", "body", "thread_root_id", "reactions", "file_offer_id"])
      || !pseudonym(message.id)
      || !pseudonym(message.conversation_id) || !conversations.has(message.conversation_id)
      || !pseudonym(message.author_id) || !isMember(message.conversation_id, message.author_id)
      || !timestamp(message.sent_at) || !oneOf(message.kind, ["text", "file_offer", "system"])
      || typeof message.body !== "string" || !nullableString(message.thread_root_id)
      || !nullableString(message.file_offer_id)
      // A file-offer message references exactly one offer; other kinds none.
      || (message.kind === "file_offer") !== (message.file_offer_id !== null)
      || reactions === null
      || !uniqueStrings(reactions.map((reaction) => reaction.emoji))
      || reactions.some((reaction) => {
        const ids = stringArray(reaction.person_ids);
        return !exactKeys(reaction, ["emoji", "label", "person_ids"])
          || typeof reaction.emoji !== "string" || typeof reaction.label !== "string"
          || ids === null || ids.length === 0 || !uniqueStrings(ids)
          // Only members of the conversation can react in it.
          || ids.some((id) => !isMember(message.conversation_id, id));
      });
  })) return false;
  const messages = new Set(snapshot.messages.map((message) => message.id));
  if (messages.size !== snapshot.messages.length) return false;
  const messagesById = new Map(snapshot.messages.map((message) => [message.id, message]));
  if (snapshot.messages.some((message) => {
    if (message.thread_root_id === null) return false;
    const root = messagesById.get(message.thread_root_id);
    return root === undefined
      || root.conversation_id !== message.conversation_id
      || root.thread_root_id !== null;
  })) return false;
  // The read marker of a conversation names one of its own messages, or nothing.
  if (snapshot.conversations.some((conversation) => (
    conversation.last_read_message_id !== null
    && messagesById.get(conversation.last_read_message_id)?.conversation_id !== conversation.id
  ))) return false;
  if (offerRows.some((offer) => {
    const file = unknownRow(offer.file);
    const recipients = rowArray(offer.recipients);
    if (
      !exactKeys(offer, [
        "id", "conversation_id", "owner_id", "file", "recipients", "state", "created_at", "expires_at",
        "requires_owner_online", "stored_by_coordination_service", "queue_location", "transport_path",
        "revoke_recalls_downloaded_bytes",
      ])
      || !pseudonym(offer.id)
      || !pseudonym(offer.conversation_id) || !conversations.has(offer.conversation_id)
      || !pseudonym(offer.owner_id) || !isMember(offer.conversation_id, offer.owner_id)
      || !oneOf(offer.state, FILE_OFFER_STATES)
      || !timestamp(offer.created_at) || !timestamp(offer.expires_at)
      || offer.stored_by_coordination_service !== false || offer.requires_owner_online !== true
      || offer.queue_location !== "sender_device" || offer.transport_path !== "direct_only"
      || offer.revoke_recalls_downloaded_bytes !== false
      || file === null || !exactKeys(file, ["display_name", "size_bytes", "media_type", "digest_hex"])
      || typeof file.display_name !== "string" || typeof file.media_type !== "string"
      || typeof file.size_bytes !== "number" || !Number.isFinite(file.size_bytes) || file.size_bytes <= 0
      || typeof file.digest_hex !== "string" || !HEX_64.test(file.digest_hex)
      || recipients === null || recipients.length === 0
      || !uniqueStrings(recipients.map((recipient) => recipient.person_id))
    ) return true;
    const sizeBytes = file.size_bytes;
    if (recipients.some((recipient) => (
      !exactKeys(recipient, ["person_id", "consent", "bytes_received", "integrity"])
      || !pseudonym(recipient.person_id) || !isMember(offer.conversation_id, recipient.person_id)
      || recipient.person_id === offer.owner_id
      || !oneOf(recipient.consent, ["pending", "granted", "declined"])
      || !(recipient.bytes_received === null || (
        typeof recipient.bytes_received === "number" && Number.isInteger(recipient.bytes_received)
        && recipient.bytes_received >= 0 && recipient.bytes_received <= sizeBytes
      ))
      || !oneOf(recipient.integrity, ["not_started", "verifying", "verified", "mismatch"])
      // Bytes and integrity exist only after consent was granted.
      || (recipient.consent !== "granted" && (recipient.bytes_received !== null || recipient.integrity !== "not_started"))
    ))) return true;
    // A transferring, paused, verifying, complete, or mismatched offer implies consent by someone.
    return OFFER_STATES_REQUIRING_CONSENT.has(offer.state as string)
      && !recipients.some((recipient) => recipient.consent === "granted");
  })) return false;
  const offers = new Set(snapshot.file_offers.map((offer) => offer.id));
  if (offers.size !== snapshot.file_offers.length) return false;
  const offersById = new Map(snapshot.file_offers.map((offer) => [offer.id, offer]));
  // A file-offer message points at an offer of its own conversation.
  if (snapshot.messages.some((message) => (
    message.file_offer_id !== null
    && offersById.get(message.file_offer_id)?.conversation_id !== message.conversation_id
  ))) return false;
  return true;
}
