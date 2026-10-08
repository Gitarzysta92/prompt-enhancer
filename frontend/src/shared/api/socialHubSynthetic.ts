import {
  SOCIAL_HUB_PORT_VERSION,
  socialCapabilityInvariants,
  type Conversation,
  type FileShareOffer,
  type FriendRequest,
  type Friendship,
  type SocialCapabilityReport,
  type SocialHubPort,
  type SocialMessage,
  type SocialPermissionMatrix,
  type SocialPerson,
  type SocialPresenceLevel,
  type SocialPresenceSignal,
  type SocialSnapshot,
} from "./socialHubSchema";

/**
 * Fictional, content-free social fixture for the synthetic development
 * preview. Every person is a reserved-example identity, every message is demo
 * copy about the fixture itself, and every file offer is metadata only. The
 * payloads are stamped `origin: "synthetic_fixture"` and `fictional: true`.
 */
export const SOCIAL_FIXTURE_NOW = "2040-02-03T09:00:00Z";
export const SOCIAL_SYNTHETIC_PRINCIPAL_ID = "8e".repeat(32);

const id = (prefix: string, index: number): string => `${prefix}${index.toString(16).padStart(2, "0")}`.repeat(16);

export const SOCIAL_FIXTURE_PEOPLE_IDS = {
  me: id("a0", 0),
  alex: id("a0", 1),
  blake: id("a0", 2),
  casey: id("a0", 3),
  dana: id("a0", 4),
  emery: id("a0", 5),
  finley: id("a0", 6),
} as const;

export const SOCIAL_FIXTURE_CONVERSATION_IDS = {
  dmAlex: id("c0", 1),
  dmBlake: id("c0", 2),
  guild: id("c0", 3),
  releaseNotes: id("c0", 4),
} as const;

const P = SOCIAL_FIXTURE_PEOPLE_IDS;
const C = SOCIAL_FIXTURE_CONVERSATION_IDS;
const messageId = (index: number) => id("d0", index);
const offerId = (index: number) => id("e0", index);
const requestId = (index: number) => id("b0", index);

const OPEN_PERMISSIONS: SocialPermissionMatrix = {
  post: ["owner", "moderator", "member", "guest"],
  react: ["owner", "moderator", "member", "guest"],
  start_thread: ["owner", "moderator", "member"],
  share_files: ["owner", "moderator", "member"],
  invite: ["owner", "moderator"],
  manage_roles: ["owner"],
};

const ANNOUNCEMENT_PERMISSIONS: SocialPermissionMatrix = {
  post: ["owner", "moderator"],
  react: ["owner", "moderator", "member", "guest"],
  start_thread: ["owner", "moderator"],
  share_files: ["owner"],
  invite: ["owner"],
  manage_roles: ["owner"],
};

const DM_PERMISSIONS: SocialPermissionMatrix = {
  post: ["member"],
  react: ["member"],
  start_thread: ["member"],
  share_files: ["member"],
  invite: [],
  manage_roles: [],
};

const shared = (level: SocialPresenceLevel): SocialPresenceSignal => ({ sharing: "shared", level, source: "self_declared_opt_in" });
const NOT_SHARED: SocialPresenceSignal = { sharing: "not_shared", level: null, source: "self_declared_opt_in" };

const PEOPLE: readonly SocialPerson[] = [
  { id: P.me, display_name: "Local Example (you)", handle: "local@example.invalid", presence: shared("online"), direct_path: "available", is_me: true },
  { id: P.alex, display_name: "Alex Example", handle: "alex@example.invalid", presence: shared("online"), direct_path: "available", is_me: false },
  { id: P.blake, display_name: "Blake Example", handle: "blake@example.invalid", presence: shared("away"), direct_path: "unavailable_cgnat", is_me: false },
  { id: P.casey, display_name: "Casey Example", handle: "casey@example.invalid", presence: shared("offline"), direct_path: "available", is_me: false },
  { id: P.dana, display_name: "Dana Example", handle: "dana@example.invalid", presence: shared("online"), direct_path: "unavailable_symmetric_nat", is_me: false },
  { id: P.emery, display_name: "Emery Example", handle: "emery@example.invalid", presence: shared("do_not_disturb"), direct_path: "unknown", is_me: false },
  // Finley has not opted in: presence is "not shared", which is neither online nor offline.
  { id: P.finley, display_name: "Finley Example", handle: "finley@example.invalid", presence: NOT_SHARED, direct_path: "available", is_me: false },
];

const FRIENDSHIPS: readonly Friendship[] = [
  { person_id: P.alex, state: "friend", since: "2040-01-04T10:00:00Z" },
  { person_id: P.blake, state: "friend", since: "2040-01-09T15:30:00Z" },
  { person_id: P.casey, state: "friend", since: "2040-01-12T08:45:00Z" },
];

const FRIEND_REQUESTS: readonly FriendRequest[] = [
  { id: requestId(1), person_id: P.dana, direction: "incoming", state: "pending", sent_at: "2040-02-02T18:20:00Z", note: "Fixture note: we share the synthetic guild channel." },
  { id: requestId(2), person_id: P.emery, direction: "outgoing", state: "pending", sent_at: "2040-02-01T09:05:00Z", note: "" },
];

const CONVERSATIONS: readonly Conversation[] = [
  {
    id: C.dmAlex,
    kind: "dm",
    name: null,
    topic: null,
    access: "invite_only",
    discoverable: false,
    members: [{ person_id: P.me, role: "member" }, { person_id: P.alex, role: "member" }],
    permissions: DM_PERMISSIONS,
    last_read_message_id: messageId(2),
    muted: false,
  },
  {
    id: C.dmBlake,
    kind: "dm",
    name: null,
    topic: null,
    access: "invite_only",
    discoverable: false,
    members: [{ person_id: P.me, role: "member" }, { person_id: P.blake, role: "member" }],
    permissions: DM_PERMISSIONS,
    last_read_message_id: messageId(5),
    muted: false,
  },
  {
    id: C.guild,
    kind: "group_channel",
    name: "fixture-guild",
    topic: "Synthetic guild channel · fictional demo",
    access: "invite_only",
    discoverable: false,
    members: [
      { person_id: P.me, role: "owner" },
      { person_id: P.alex, role: "moderator" },
      { person_id: P.blake, role: "member" },
      { person_id: P.casey, role: "member" },
      { person_id: P.finley, role: "guest" },
    ],
    permissions: OPEN_PERMISSIONS,
    last_read_message_id: messageId(8),
    muted: false,
  },
  {
    id: C.releaseNotes,
    kind: "group_channel",
    name: "release-notes",
    topic: "Announcement channel · owner and moderators post",
    access: "invite_only",
    discoverable: false,
    members: [
      { person_id: P.finley, role: "owner" },
      { person_id: P.alex, role: "moderator" },
      { person_id: P.me, role: "member" },
    ],
    permissions: ANNOUNCEMENT_PERMISSIONS,
    last_read_message_id: null,
    muted: true,
  },
];

const MESSAGES: readonly SocialMessage[] = [
  { id: messageId(1), conversation_id: C.dmAlex, author_id: P.alex, sent_at: "2040-02-03T08:10:00Z", kind: "text", body: "Fixture message: the synthetic readiness summary is ready for a look.", thread_root_id: null, reactions: [{ emoji: "👍", label: "thumbs up", person_ids: [P.me] }], file_offer_id: null },
  { id: messageId(2), conversation_id: C.dmAlex, author_id: P.me, sent_at: "2040-02-03T08:12:00Z", kind: "text", body: "Fixture reply: reviewing it now in the demo workspace.", thread_root_id: null, reactions: [], file_offer_id: null },
  { id: messageId(3), conversation_id: C.dmAlex, author_id: P.alex, sent_at: "2040-02-03T08:40:00Z", kind: "file_offer", body: "Fixture file offer: synthetic-readiness-notes.md", thread_root_id: null, reactions: [], file_offer_id: offerId(2) },
  { id: messageId(4), conversation_id: C.dmBlake, author_id: P.blake, sent_at: "2040-02-02T16:00:00Z", kind: "text", body: "Fixture message: can you check the demo timeline lane on the flow board?", thread_root_id: null, reactions: [], file_offer_id: null },
  { id: messageId(5), conversation_id: C.dmBlake, author_id: P.me, sent_at: "2040-02-02T16:05:00Z", kind: "text", body: "Fixture reply: yes, both lanes render in the fixture.", thread_root_id: null, reactions: [{ emoji: "✅", label: "check mark", person_ids: [P.blake] }], file_offer_id: null },
  { id: messageId(6), conversation_id: C.guild, author_id: P.me, sent_at: "2040-02-01T09:00:00Z", kind: "system", body: "Fixture channel created. Owner: Local Example (you).", thread_root_id: null, reactions: [], file_offer_id: null },
  { id: messageId(7), conversation_id: C.guild, author_id: P.alex, sent_at: "2040-02-02T11:15:00Z", kind: "text", body: "Fixture message: proposing a synthetic metric review on Thursday.", thread_root_id: null, reactions: [{ emoji: "👍", label: "thumbs up", person_ids: [P.blake, P.casey] }, { emoji: "🎉", label: "party popper", person_ids: [P.finley] }], file_offer_id: null },
  { id: messageId(8), conversation_id: C.guild, author_id: P.blake, sent_at: "2040-02-02T11:20:00Z", kind: "text", body: "Fixture thread reply: Thursday works for the demo.", thread_root_id: messageId(7), reactions: [], file_offer_id: null },
  { id: messageId(9), conversation_id: C.guild, author_id: P.casey, sent_at: "2040-02-02T11:32:00Z", kind: "text", body: "Fixture thread reply: I will bring the synthetic evidence list.", thread_root_id: messageId(7), reactions: [{ emoji: "👍", label: "thumbs up", person_ids: [P.alex] }], file_offer_id: null },
  { id: messageId(10), conversation_id: C.guild, author_id: P.finley, sent_at: "2040-02-03T07:55:00Z", kind: "text", body: "Fixture message: reminder that guests can read but not start threads here.", thread_root_id: null, reactions: [], file_offer_id: null },
  { id: messageId(11), conversation_id: C.guild, author_id: P.casey, sent_at: "2040-02-03T08:02:00Z", kind: "file_offer", body: "Fixture file offer: synthetic-evidence-list.csv", thread_root_id: null, reactions: [], file_offer_id: offerId(3) },
  { id: messageId(12), conversation_id: C.releaseNotes, author_id: P.finley, sent_at: "2040-02-03T06:30:00Z", kind: "text", body: "Fixture announcement: demo build 0.1 fixture notes are pinned.", thread_root_id: null, reactions: [{ emoji: "👀", label: "eyes", person_ids: [P.alex] }], file_offer_id: null },
  { id: messageId(13), conversation_id: C.releaseNotes, author_id: P.alex, sent_at: "2040-02-03T06:45:00Z", kind: "text", body: "Fixture announcement: the next synthetic fixture refresh is scheduled.", thread_root_id: null, reactions: [], file_offer_id: null },
];

const FILE_OFFERS: readonly FileShareOffer[] = [
  {
    id: offerId(1),
    conversation_id: C.dmAlex,
    owner_id: P.me,
    file: { display_name: "synthetic-metric-summary.pdf", size_bytes: 2_621_440, media_type: "application/pdf", digest_hex: "1a".repeat(32) },
    recipients: [{ person_id: P.alex, consent: "pending", bytes_received: null, integrity: "not_started" }],
    state: "awaiting_consent",
    created_at: "2040-02-03T08:30:00Z",
    expires_at: "2040-02-04T08:30:00Z",
    requires_owner_online: true,
    stored_by_coordination_service: false,
    queue_location: "sender_device",
    transport_path: "direct_only",
    revoke_recalls_downloaded_bytes: false,
  },
  {
    id: offerId(2),
    conversation_id: C.dmAlex,
    owner_id: P.alex,
    file: { display_name: "synthetic-readiness-notes.md", size_bytes: 6_815_744, media_type: "text/markdown", digest_hex: "2b".repeat(32) },
    recipients: [{ person_id: P.me, consent: "pending", bytes_received: null, integrity: "not_started" }],
    state: "awaiting_consent",
    created_at: "2040-02-03T08:40:00Z",
    expires_at: "2040-02-03T20:40:00Z",
    requires_owner_online: true,
    stored_by_coordination_service: false,
    queue_location: "sender_device",
    transport_path: "direct_only",
    revoke_recalls_downloaded_bytes: false,
  },
  {
    id: offerId(3),
    conversation_id: C.guild,
    owner_id: P.casey,
    file: { display_name: "synthetic-evidence-list.csv", size_bytes: 731_136, media_type: "text/csv", digest_hex: "3c".repeat(32) },
    recipients: [
      { person_id: P.me, consent: "granted", bytes_received: 262_144, integrity: "not_started" },
      { person_id: P.alex, consent: "granted", bytes_received: 731_136, integrity: "verified" },
    ],
    state: "owner_offline",
    created_at: "2040-02-03T08:02:00Z",
    expires_at: "2040-02-05T08:02:00Z",
    requires_owner_online: true,
    stored_by_coordination_service: false,
    queue_location: "sender_device",
    transport_path: "direct_only",
    revoke_recalls_downloaded_bytes: false,
  },
  {
    id: offerId(4),
    conversation_id: C.guild,
    owner_id: P.me,
    file: { display_name: "synthetic-flow-board.png", size_bytes: 1_310_720, media_type: "image/png", digest_hex: "4d".repeat(32) },
    recipients: [{ person_id: P.blake, consent: "granted", bytes_received: 1_310_720, integrity: "verified" }],
    state: "expired",
    created_at: "2040-01-20T09:00:00Z",
    expires_at: "2040-01-27T09:00:00Z",
    requires_owner_online: true,
    stored_by_coordination_service: false,
    queue_location: "sender_device",
    transport_path: "direct_only",
    revoke_recalls_downloaded_bytes: false,
  },
  {
    // Both sides are online and consent is granted, but Blake's device sits
    // behind CGNAT: with no relay and no TURN there is simply no direct path.
    id: offerId(5),
    conversation_id: C.dmBlake,
    owner_id: P.me,
    file: { display_name: "synthetic-lane-sketch.svg", size_bytes: 204_800, media_type: "image/svg+xml", digest_hex: "5e".repeat(32) },
    recipients: [{ person_id: P.blake, consent: "granted", bytes_received: 0, integrity: "not_started" }],
    state: "direct_path_unavailable",
    created_at: "2040-02-03T08:50:00Z",
    expires_at: "2040-02-04T08:50:00Z",
    requires_owner_online: true,
    stored_by_coordination_service: false,
    queue_location: "sender_device",
    transport_path: "direct_only",
    revoke_recalls_downloaded_bytes: false,
  },
  {
    // A terminal failure fixture proves that integrity verification is not
    // presented as success-only. No real bytes or real digest are involved.
    id: offerId(6),
    conversation_id: C.guild,
    owner_id: P.alex,
    file: { display_name: "synthetic-integrity-mismatch.bin", size_bytes: 65_536, media_type: "application/octet-stream", digest_hex: "6f".repeat(32) },
    recipients: [{ person_id: P.me, consent: "granted", bytes_received: 65_536, integrity: "mismatch" }],
    state: "integrity_mismatch",
    created_at: "2040-02-03T08:45:00Z",
    expires_at: "2040-02-04T08:45:00Z",
    requires_owner_online: true,
    stored_by_coordination_service: false,
    queue_location: "sender_device",
    transport_path: "direct_only",
    revoke_recalls_downloaded_bytes: false,
  },
];


export function createSyntheticSocialSnapshot(): SocialSnapshot {
  return structuredClone({
    port_version: SOCIAL_HUB_PORT_VERSION,
    origin: "synthetic_fixture",
    fictional: true,
    principal_id: SOCIAL_SYNTHETIC_PRINCIPAL_ID,
    me_person_id: P.me,
    generated_at: SOCIAL_FIXTURE_NOW,
    people: PEOPLE,
    friendships: FRIENDSHIPS,
    friend_requests: FRIEND_REQUESTS,
    conversations: CONVERSATIONS,
    messages: MESSAGES,
    file_offers: FILE_OFFERS,
  } satisfies SocialSnapshot);
}

export function createSyntheticSocialHubPort(now: () => string = () => SOCIAL_FIXTURE_NOW): SocialHubPort {
  const capabilities = (): SocialCapabilityReport => ({
    port_version: SOCIAL_HUB_PORT_VERSION,
    origin: "synthetic_fixture",
    principal_id: SOCIAL_SYNTHETIC_PRINCIPAL_ID,
    state: "available",
    reason: "synthetic_fixture",
    fictional: true,
    ...socialCapabilityInvariants(),
    file_sharing: {
      state: "available",
      transport: "direct_device_to_device_simulated",
      path: "direct_only",
      relay: "none",
      turn: "none",
      stored_by_coordination_service: false,
      bytes_on_coordination_plane: "never",
      offline_offer_queue: "sender_device_bounded_expiry",
    },
    checked_at: now(),
  });
  return {
    portVersion: SOCIAL_HUB_PORT_VERSION,
    origin: "synthetic_fixture",
    principalId: SOCIAL_SYNTHETIC_PRINCIPAL_ID,
    async getCapabilities() {
      return capabilities();
    },
    async getSnapshot() {
      return createSyntheticSocialSnapshot();
    },
  };
}
