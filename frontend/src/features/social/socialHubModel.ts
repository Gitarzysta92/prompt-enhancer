import {
  presenceValue,
  type Conversation,
  type FileOfferState,
  type FileShareOffer,
  type FriendRequest,
  type SocialDirectPathState,
  type SocialMessage,
  type SocialPermissionAction,
  type SocialPerson,
  type SocialPresence,
  type SocialPresenceLevel,
  type SocialRole,
  type SocialSnapshot,
} from "../../shared/api/socialHub";

/**
 * Pure local model for the Social hub. Every action mutates only the React
 * copy of the snapshot on this device: nothing is delivered, synced, stored, or
 * encrypted, and the state carries that in `delivery: "local_state_only"`.
 * Time is always injected (`at`) so the reducer is deterministic in tests.
 */
export interface SocialHubState {
  snapshot: SocialSnapshot;
  activeConversationId: string | null;
  activeThreadRootId: string | null;
  query: string;
  nextLocalSequence: number;
  /** Last announcement for the live region; empty when nothing changed. */
  notice: string;
}

export const SOCIAL_TRANSFER_BYTES_PER_TICK = 262_144;

export type SocialHubAction =
  | { type: "select_conversation"; conversationId: string }
  | { type: "open_thread"; rootId: string }
  | { type: "close_thread" }
  | { type: "set_query"; query: string }
  | { type: "send_message"; conversationId: string; body: string; threadRootId: string | null; at: string }
  | { type: "toggle_reaction"; messageId: string; emoji: string; label: string }
  | { type: "accept_request"; requestId: string; at: string }
  | { type: "decline_request"; requestId: string }
  | { type: "withdraw_request"; requestId: string }
  | { type: "send_request"; personId: string; at: string }
  | { type: "remove_friend"; personId: string }
  | { type: "mark_conversation_read"; conversationId: string }
  | { type: "create_offer"; conversationId: string; displayName: string; sizeBytes: number; mediaType: string; recipientIds: readonly string[]; at: string; expiresAt: string }
  | { type: "grant_consent"; offerId: string; at: string }
  | { type: "decline_consent"; offerId: string }
  | { type: "pause_transfer"; offerId: string }
  | { type: "resume_transfer"; offerId: string; at: string }
  | { type: "revoke_offer"; offerId: string }
  | { type: "tick_transfers"; at: string; bytesPerTick?: number }
  /** Explicit opt-in presence for the local principal: share a coarse level, or share nothing. */
  | { type: "set_presence"; sharing: "shared" | "not_shared"; level: SocialPresenceLevel | null; at: string }
  | { type: "clear_notice" };

export function createSocialHubState(snapshot: SocialSnapshot): SocialHubState {
  return {
    snapshot,
    activeConversationId: snapshot.conversations[0]?.id ?? null,
    activeThreadRootId: null,
    query: "",
    nextLocalSequence: 1,
    notice: "",
  };
}

const localId = (prefix: string, sequence: number): string =>
  `${prefix}${sequence.toString(16).padStart(62, "0").slice(-62)}`;

export function personById(snapshot: SocialSnapshot, personId: string): SocialPerson | null {
  return snapshot.people.find((person) => person.id === personId) ?? null;
}

/** Rendered presence of one person; `not_shared` when they have not opted in (never shown as offline). */
export function personPresence(person: SocialPerson | null | undefined): SocialPresence {
  return person === null || person === undefined ? "not_shared" : presenceValue(person.presence);
}

/** True only for an opted-in person whose coarse level is online. */
export function personIsOnline(person: SocialPerson | null | undefined): boolean {
  return personPresence(person) === "online";
}

export const PRESENCE_VALUE_LABELS: Readonly<Record<SocialPresence, string>> = {
  online: "Online",
  away: "Away",
  do_not_disturb: "Do not disturb",
  offline: "Offline",
  not_shared: "Presence not shared",
};

export const DIRECT_PATH_LABELS: Readonly<Record<SocialDirectPathState, string>> = {
  available: "Direct path available",
  unavailable_symmetric_nat: "No direct path · symmetric NAT (no relay or TURN exists)",
  unavailable_cgnat: "No direct path · CGNAT (no relay or TURN exists)",
  unknown: "Direct path not probed yet",
};

/**
 * Whether a direct device-to-device path exists between the offer's owner and
 * every consenting recipient. Only a direct path counts: there is no relay and
 * no TURN, so a symmetric NAT or CGNAT on either side blocks the transfer.
 * `unknown` is not treated as blocked; it is resolved when the path is probed.
 */
export function offerDirectPathBlocked(snapshot: SocialSnapshot, offer: FileShareOffer): SocialDirectPathState | null {
  const owner = personById(snapshot, offer.owner_id);
  const blockedStates: readonly SocialDirectPathState[] = ["unavailable_symmetric_nat", "unavailable_cgnat"];
  if (owner !== null && blockedStates.includes(owner.direct_path)) return owner.direct_path;
  for (const recipient of offer.recipients) {
    if (recipient.consent !== "granted") continue;
    const person = personById(snapshot, recipient.person_id);
    if (person !== null && blockedStates.includes(person.direct_path)) return person.direct_path;
  }
  return null;
}

export function conversationById(snapshot: SocialSnapshot, conversationId: string): Conversation | null {
  return snapshot.conversations.find((conversation) => conversation.id === conversationId) ?? null;
}

export function conversationTitle(snapshot: SocialSnapshot, conversation: Conversation): string {
  if (conversation.kind === "group_channel") return `#${conversation.name ?? "channel"}`;
  const counterpart = conversation.members.find((member) => member.person_id !== snapshot.me_person_id);
  const person = counterpart === undefined ? null : personById(snapshot, counterpart.person_id);
  return person?.display_name ?? "Direct message";
}

export function myRole(snapshot: SocialSnapshot, conversation: Conversation): SocialRole | null {
  return conversation.members.find((member) => member.person_id === snapshot.me_person_id)?.role ?? null;
}

/** Every DM operation is authorized only while its counterpart is a current friend. */
export function directConversationHasLiveFriendship(snapshot: SocialSnapshot, conversation: Conversation): boolean {
  if (conversation.kind !== "dm") return true;
  const counterpart = conversation.members.find((member) => member.person_id !== snapshot.me_person_id);
  return counterpart !== undefined && snapshot.friendships.some((friendship) => (
    friendship.person_id === counterpart.person_id && friendship.state === "friend"
  ));
}

export function canPerform(snapshot: SocialSnapshot, conversation: Conversation, action: SocialPermissionAction): boolean {
  const role = myRole(snapshot, conversation);
  return directConversationHasLiveFriendship(snapshot, conversation)
    && role !== null
    && conversation.permissions[action].includes(role);
}

/** Messages of one conversation in send order. */
export function conversationMessages(snapshot: SocialSnapshot, conversationId: string): SocialMessage[] {
  return snapshot.messages
    .filter((message) => message.conversation_id === conversationId)
    .sort((left, right) => left.sent_at.localeCompare(right.sent_at) || left.id.localeCompare(right.id));
}

export function threadReplies(snapshot: SocialSnapshot, rootId: string): SocialMessage[] {
  return snapshot.messages
    .filter((message) => message.thread_root_id === rootId)
    .sort((left, right) => left.sent_at.localeCompare(right.sent_at) || left.id.localeCompare(right.id));
}

/** Count of messages after the last-read marker that were not authored by the local principal. */
export function unreadCount(snapshot: SocialSnapshot, conversation: Conversation): number {
  const messages = conversationMessages(snapshot, conversation.id);
  const lastReadIndex = conversation.last_read_message_id === null
    ? -1
    : messages.findIndex((message) => message.id === conversation.last_read_message_id);
  return messages
    .slice(lastReadIndex + 1)
    .filter((message) => message.author_id !== snapshot.me_person_id)
    .length;
}

export function totalUnread(snapshot: SocialSnapshot): number {
  return snapshot.conversations.reduce((sum, conversation) => sum + unreadCount(snapshot, conversation), 0);
}

export function friends(snapshot: SocialSnapshot): SocialPerson[] {
  return snapshot.friendships
    .filter((friendship) => friendship.state === "friend")
    .map((friendship) => personById(snapshot, friendship.person_id))
    .filter((person): person is SocialPerson => person !== null)
    .sort((left, right) => left.display_name.localeCompare(right.display_name));
}

export function pendingRequests(snapshot: SocialSnapshot, direction: FriendRequest["direction"]): FriendRequest[] {
  return snapshot.friend_requests.filter((request) => request.direction === direction && request.state === "pending");
}

export interface SocialSearchResults {
  people: SocialPerson[];
  conversations: Conversation[];
  messages: SocialMessage[];
}

export function searchSnapshot(snapshot: SocialSnapshot, query: string): SocialSearchResults {
  const needle = query.trim().toLowerCase();
  if (needle === "") return { people: [], conversations: [], messages: [] };
  const matches = (value: string | null) => value !== null && value.toLowerCase().includes(needle);
  return {
    people: snapshot.people.filter((person) => !person.is_me && (matches(person.display_name) || matches(person.handle))),
    conversations: snapshot.conversations.filter((conversation) =>
      matches(conversation.name) || matches(conversation.topic) || matches(conversationTitle(snapshot, conversation))),
    messages: snapshot.messages.filter((message) => matches(message.body)),
  };
}

export const OFFER_STATE_LABELS: Readonly<Record<FileOfferState, string>> = {
  awaiting_consent: "Awaiting recipient consent",
  transferring: "Transferring directly",
  paused: "Paused",
  verifying: "Verifying integrity",
  complete: "Complete · integrity verified",
  integrity_mismatch: "Integrity mismatch",
  revoked: "Revoked by owner · future bytes stopped",
  expired: "Expired",
  owner_offline: "Owner offline · waiting on the owner's device",
  queued_on_sender: "Queued on your device · you are not currently shared as online",
  direct_path_unavailable: "No direct path · symmetric NAT/CGNAT",
};

export const TERMINAL_OFFER_STATES: ReadonlySet<FileOfferState> = new Set([
  "complete",
  "integrity_mismatch",
  "revoked",
  "expired",
]);

/** Shown instead of the wire state when nobody is left who could consent (see `offerDeclinedByEveryRecipient`). */
export const OFFER_DECLINED_BY_ALL_LABEL = "Declined by every recipient · no transfer can start";

/**
 * True when every recipient already declined. The port has no `declined` offer
 * state, so such an offer keeps its wire state (`awaiting_consent`,
 * `owner_offline`, `queued_on_sender`, `direct_path_unavailable`) even though no
 * byte can ever move for it. Surfaces must say that instead of claiming the
 * offer is still waiting for a consent that can no longer arrive.
 */
export function offerDeclinedByEveryRecipient(offer: FileShareOffer): boolean {
  return offer.recipients.length > 0
    && offer.recipients.every((recipient) => recipient.consent === "declined");
}

export function offerBytesReceived(offer: FileShareOffer): number | null {
  const granted = offer.recipients.filter((recipient) => recipient.consent === "granted");
  if (granted.length === 0 || granted.some((recipient) => recipient.bytes_received === null)) return null;
  const total = granted.reduce((sum, recipient) => sum + (recipient.bytes_received ?? 0), 0);
  return total / granted.length;
}

export function offerIsExpired(offer: FileShareOffer, at: string): boolean {
  return offer.expires_at.localeCompare(at) <= 0;
}

function withSnapshot(state: SocialHubState, snapshot: Partial<SocialSnapshot>, notice: string): SocialHubState {
  return { ...state, snapshot: { ...state.snapshot, ...snapshot }, notice };
}

function updateOffer(state: SocialHubState, offerId: string, update: (offer: FileShareOffer) => FileShareOffer, notice: string): SocialHubState {
  const offer = state.snapshot.file_offers.find((candidate) => candidate.id === offerId);
  if (offer === undefined) return state;
  const updated = update(offer);
  if (updated === offer) return state;
  return withSnapshot(state, {
    file_offers: state.snapshot.file_offers.map((candidate) => candidate.id === offerId ? updated : candidate),
  }, notice);
}

function newestMessageId(snapshot: SocialSnapshot, conversationId: string): string | null {
  const messages = conversationMessages(snapshot, conversationId);
  return messages.length === 0 ? null : messages[messages.length - 1].id;
}

function markRead(snapshot: SocialSnapshot, conversationId: string): SocialSnapshot {
  const newest = newestMessageId(snapshot, conversationId);
  return {
    ...snapshot,
    conversations: snapshot.conversations.map((conversation) =>
      conversation.id === conversationId ? { ...conversation, last_read_message_id: newest } : conversation),
  };
}

function ownerOnline(snapshot: SocialSnapshot, offer: FileShareOffer): boolean {
  return personIsOnline(personById(snapshot, offer.owner_id));
}

/**
 * The state a consented offer can be in right now: expiry first, then the
 * owner must be online (offers wait on the owner's device, never on a server),
 * then a direct path must exist (no relay, no TURN), and only then do bytes move.
 */
function liveTransferState(snapshot: SocialSnapshot, offer: FileShareOffer, at: string): FileOfferState {
  if (offerIsExpired(offer, at)) return "expired";
  if (!ownerOnline(snapshot, offer)) return "owner_offline";
  if (offerDirectPathBlocked(snapshot, offer) !== null) return "direct_path_unavailable";
  return "transferring";
}

const RESUMABLE_STATES: ReadonlySet<FileOfferState> = new Set(["paused", "owner_offline", "direct_path_unavailable"]);
const CONSENTABLE_STATES: ReadonlySet<FileOfferState> = new Set(["awaiting_consent", "owner_offline", "direct_path_unavailable", "queued_on_sender"]);

export function socialHubReducer(state: SocialHubState, action: SocialHubAction): SocialHubState {
  const { snapshot } = state;
  switch (action.type) {
    case "select_conversation": {
      if (conversationById(snapshot, action.conversationId) === null) return state;
      return {
        ...state,
        snapshot: markRead(snapshot, action.conversationId),
        activeConversationId: action.conversationId,
        activeThreadRootId: null,
        notice: "",
      };
    }
    case "open_thread": {
      const root = snapshot.messages.find((message) => message.id === action.rootId);
      if (
        root === undefined
        || root.thread_root_id !== null
        || root.conversation_id !== state.activeConversationId
      ) return state;
      const conversation = conversationById(snapshot, root.conversation_id);
      // Reading an existing thread needs current conversation membership (and
      // a live friendship for DMs), not the separate permission to start one.
      if (
        conversation === null
        || myRole(snapshot, conversation) === null
        || !directConversationHasLiveFriendship(snapshot, conversation)
      ) return state;
      const replyCount = threadReplies(snapshot, action.rootId).length;
      return {
        ...state,
        activeThreadRootId: action.rootId,
        notice: `Thread opened · ${replyCount} ${replyCount === 1 ? "reply" : "replies"}.`,
      };
    }
    case "close_thread":
      return { ...state, activeThreadRootId: null, notice: "Thread closed." };
    case "set_query":
      return { ...state, query: action.query, notice: "" };
    case "mark_conversation_read":
      return withSnapshot(state, markRead(snapshot, action.conversationId), "Conversation marked as read on this device.");
    case "send_message": {
      const conversation = conversationById(snapshot, action.conversationId);
      const body = action.body.trim();
      if (conversation === null || body === "" || !canPerform(snapshot, conversation, "post")) return state;
      if (action.threadRootId !== null) {
        const root = snapshot.messages.find((message) => message.id === action.threadRootId);
        if (
          root === undefined
          || root.thread_root_id !== null
          || root.conversation_id !== action.conversationId
          || !canPerform(snapshot, conversation, "start_thread")
        ) return state;
      }
      const message: SocialMessage = {
        id: localId("f0", state.nextLocalSequence),
        conversation_id: action.conversationId,
        author_id: snapshot.me_person_id,
        sent_at: action.at,
        kind: "text",
        body,
        thread_root_id: action.threadRootId,
        reactions: [],
        file_offer_id: null,
      };
      const next = markRead({ ...snapshot, messages: [...snapshot.messages, message] }, action.conversationId);
      return {
        ...state,
        snapshot: next,
        nextLocalSequence: state.nextLocalSequence + 1,
        notice: action.threadRootId === null
          ? "Message added to local demo state. Nothing was delivered."
          : "Thread reply added to local demo state. Nothing was delivered.",
      };
    }
    case "toggle_reaction": {
      const message = snapshot.messages.find((candidate) => candidate.id === action.messageId);
      if (message === undefined) return state;
      const conversation = conversationById(snapshot, message.conversation_id);
      if (conversation === null || !canPerform(snapshot, conversation, "react")) return state;
      const me = snapshot.me_person_id;
      const existing = message.reactions.find((reaction) => reaction.emoji === action.emoji);
      const reacted = existing?.person_ids.includes(me) ?? false;
      const reactions = existing === undefined
        ? [...message.reactions, { emoji: action.emoji, label: action.label, person_ids: [me] }]
        : message.reactions
          .map((reaction) => reaction.emoji !== action.emoji
            ? reaction
            : { ...reaction, person_ids: reacted ? reaction.person_ids.filter((id) => id !== me) : [...reaction.person_ids, me] })
          .filter((reaction) => reaction.person_ids.length > 0);
      return withSnapshot(state, {
        messages: snapshot.messages.map((candidate) => candidate.id === action.messageId ? { ...candidate, reactions } : candidate),
      }, reacted ? `Removed your ${action.label} reaction (local only).` : `Added a ${action.label} reaction (local only).`);
    }
    case "accept_request": {
      const request = snapshot.friend_requests.find((candidate) => candidate.id === action.requestId);
      if (request === undefined || request.state !== "pending" || request.direction !== "incoming") return state;
      const person = personById(snapshot, request.person_id);
      return withSnapshot(state, {
        friend_requests: snapshot.friend_requests.map((candidate) => candidate.id === action.requestId ? { ...candidate, state: "accepted" } : candidate),
        friendships: [...snapshot.friendships, { person_id: request.person_id, state: "friend", since: action.at }],
      }, `${person?.display_name ?? "Fixture person"} added as a friend in local demo state.`);
    }
    case "decline_request": {
      const request = snapshot.friend_requests.find((candidate) => candidate.id === action.requestId);
      if (request === undefined || request.state !== "pending" || request.direction !== "incoming") return state;
      return withSnapshot(state, {
        friend_requests: snapshot.friend_requests.map((candidate) => candidate.id === action.requestId ? { ...candidate, state: "declined" } : candidate),
      }, "Friend request declined in local demo state.");
    }
    case "withdraw_request": {
      const request = snapshot.friend_requests.find((candidate) => candidate.id === action.requestId);
      if (request === undefined || request.state !== "pending" || request.direction !== "outgoing") return state;
      return withSnapshot(state, {
        friend_requests: snapshot.friend_requests.map((candidate) => candidate.id === action.requestId ? { ...candidate, state: "withdrawn" } : candidate),
      }, "Friend request withdrawn in local demo state.");
    }
    case "send_request": {
      const person = personById(snapshot, action.personId);
      const alreadyFriend = snapshot.friendships.some((friendship) => friendship.person_id === action.personId && friendship.state === "friend");
      const alreadyPending = snapshot.friend_requests.some((request) => request.person_id === action.personId && request.state === "pending");
      if (person === null || person.is_me || alreadyFriend || alreadyPending) return state;
      return {
        ...state,
        snapshot: {
          ...snapshot,
          friend_requests: [...snapshot.friend_requests, {
            id: localId("b1", state.nextLocalSequence),
            person_id: action.personId,
            direction: "outgoing",
            state: "pending",
            sent_at: action.at,
            note: "",
          }],
        },
        nextLocalSequence: state.nextLocalSequence + 1,
        notice: `Friend request to ${person.display_name} recorded in local demo state. Nothing was sent.`,
      };
    }
    case "remove_friend": {
      const person = personById(snapshot, action.personId);
      if (!snapshot.friendships.some((friendship) => friendship.person_id === action.personId)) return state;
      const removedConversationIds = new Set(snapshot.conversations
        .filter((conversation) => conversation.kind === "dm"
          && conversation.members.some((member) => member.person_id === action.personId))
        .map((conversation) => conversation.id));
      const nextSnapshot: SocialSnapshot = {
        ...snapshot,
        friendships: snapshot.friendships.filter((friendship) => friendship.person_id !== action.personId),
        conversations: snapshot.conversations.filter((conversation) => !removedConversationIds.has(conversation.id)),
        messages: snapshot.messages.filter((message) => !removedConversationIds.has(message.conversation_id)),
        file_offers: snapshot.file_offers.filter((offer) => !removedConversationIds.has(offer.conversation_id)),
      };
      const activeRemoved = state.activeConversationId !== null && removedConversationIds.has(state.activeConversationId);
      return {
        ...state,
        snapshot: nextSnapshot,
        activeConversationId: activeRemoved ? nextSnapshot.conversations[0]?.id ?? null : state.activeConversationId,
        activeThreadRootId: activeRemoved ? null : state.activeThreadRootId,
        notice: `${person?.display_name ?? "Fixture person"} removed from friends in local demo state; their direct conversation is no longer available through the social port.`,
      };
    }
    case "create_offer": {
      const conversation = conversationById(snapshot, action.conversationId);
      const displayName = action.displayName.trim();
      if (conversation === null || displayName === "" || !canPerform(snapshot, conversation, "share_files")) return state;
      const recipientIds = action.recipientIds.filter((personId) =>
        personId !== snapshot.me_person_id && conversation.members.some((member) => member.person_id === personId));
      if (recipientIds.length === 0 || !Number.isFinite(action.sizeBytes) || action.sizeBytes <= 0) return state;
      // A sender who is offline may still create the metadata offer: it waits
      // on this device with bounded expiry and never on the coordination plane.
      const senderOnline = personIsOnline(personById(snapshot, snapshot.me_person_id));
      const offer: FileShareOffer = {
        id: localId("e1", state.nextLocalSequence),
        conversation_id: action.conversationId,
        owner_id: snapshot.me_person_id,
        file: {
          display_name: displayName,
          size_bytes: Math.round(action.sizeBytes),
          media_type: action.mediaType.trim() || "application/octet-stream",
          digest_hex: localId("d1", state.nextLocalSequence).slice(0, 64),
        },
        recipients: recipientIds.map((personId) => ({ person_id: personId, consent: "pending", bytes_received: null, integrity: "not_started" })),
        state: senderOnline ? "awaiting_consent" : "queued_on_sender",
        created_at: action.at,
        expires_at: action.expiresAt,
        requires_owner_online: true,
        stored_by_coordination_service: false,
        queue_location: "sender_device",
        transport_path: "direct_only",
        revoke_recalls_downloaded_bytes: false,
      };
      const message: SocialMessage = {
        id: localId("f1", state.nextLocalSequence),
        conversation_id: action.conversationId,
        author_id: snapshot.me_person_id,
        sent_at: action.at,
        kind: "file_offer",
        body: `Fixture file offer: ${displayName}`,
        thread_root_id: null,
        reactions: [],
        file_offer_id: offer.id,
      };
      return {
        ...state,
        snapshot: markRead({
          ...snapshot,
          file_offers: [...snapshot.file_offers, offer],
          messages: [...snapshot.messages, message],
        }, action.conversationId),
        nextLocalSequence: state.nextLocalSequence + 1,
        notice: senderOnline
          ? `Offer for ${displayName} recorded in local demo state; recipients must consent before any direct transfer.`
          : `Offer for ${displayName} queued on this device because you are not currently shared as online; it expires ${action.expiresAt.slice(0, 16).replace("T", " ")} UTC and never waits on a server.`,
      };
    }
    case "grant_consent":
      return updateOffer(state, action.offerId, (offer) => {
        if (!CONSENTABLE_STATES.has(offer.state)) return offer;
        if (!offer.recipients.some((recipient) => recipient.person_id === snapshot.me_person_id && recipient.consent === "pending")) return offer;
        const recipients = offer.recipients.map((recipient) =>
          recipient.person_id === snapshot.me_person_id && recipient.consent === "pending"
            ? { ...recipient, consent: "granted" as const, bytes_received: 0 }
            : recipient);
        const consented = { ...offer, recipients };
        const anyGranted = recipients.some((recipient) => recipient.consent === "granted");
        const nextState: FileOfferState = offerIsExpired(offer, action.at)
          ? "expired"
          : !anyGranted
            ? "awaiting_consent"
            : liveTransferState(snapshot, consented, action.at);
        return { ...consented, state: nextState };
      }, "Consent granted on this device; the direct transfer simulation can proceed while the owner is online and a direct path exists.");
    case "decline_consent":
      return updateOffer(state, action.offerId, (offer) => {
        if (!offer.recipients.some((recipient) => recipient.person_id === snapshot.me_person_id && recipient.consent === "pending")) return offer;
        const recipients = offer.recipients.map((recipient) =>
          recipient.person_id === snapshot.me_person_id && recipient.consent === "pending"
            ? { ...recipient, consent: "declined" as const }
            : recipient);
        return { ...offer, recipients };
      }, "Consent declined on this device; no bytes will be requested from the owner.");
    case "pause_transfer":
      return updateOffer(state, action.offerId, (offer) => offer.state === "transferring" ? { ...offer, state: "paused" } : offer, "Direct transfer paused on this device.");
    case "resume_transfer":
      return updateOffer(state, action.offerId, (offer) => {
        if (!RESUMABLE_STATES.has(offer.state)) return offer;
        const nextState = liveTransferState(snapshot, offer, action.at);
        return nextState === offer.state ? offer : { ...offer, state: nextState };
      }, "Direct transfer resumed on this device.");
    case "revoke_offer":
      return updateOffer(state, action.offerId, (offer) =>
        offer.owner_id === snapshot.me_person_id && !TERMINAL_OFFER_STATES.has(offer.state)
          ? { ...offer, state: "revoked" }
          : offer, "Offer revoked in local demo state; no further bytes will be sent, but bytes a recipient already downloaded cannot be recalled.");
    case "set_presence": {
      const me = personById(snapshot, snapshot.me_person_id);
      if (me === null) return state;
      const level = action.sharing === "shared" ? action.level : null;
      if (action.sharing === "shared" && level === null) return state;
      const people = snapshot.people.map((person) => person.id === me.id
        ? { ...person, presence: { sharing: action.sharing, level, source: "self_declared_opt_in" as const } }
        : person);
      const nextSnapshot: SocialSnapshot = { ...snapshot, people };
      const nowOnline = level === "online";
      // Offers queued on this (the sender's) device while offline become live
      // offers once the sender is online again; nothing ever waited on a server.
      const file_offers = nextSnapshot.file_offers.map((offer) => {
        if (offer.owner_id !== me.id || TERMINAL_OFFER_STATES.has(offer.state)) return offer;
        if (offerIsExpired(offer, action.at)) return { ...offer, state: "expired" as const };
        if (offer.state === "queued_on_sender" && nowOnline) {
          return {
            ...offer,
            state: offer.recipients.some((recipient) => recipient.consent === "granted")
              ? liveTransferState(nextSnapshot, offer, action.at)
              : "awaiting_consent" as const,
          };
        }
        if ((offer.state === "transferring" || offer.state === "verifying") && !nowOnline) {
          return { ...offer, state: "owner_offline" as const };
        }
        return offer;
      });
      return {
        ...state,
        snapshot: { ...nextSnapshot, file_offers },
        notice: action.sharing === "shared"
          ? `Presence set to ${PRESENCE_VALUE_LABELS[level ?? "not_shared"].toLowerCase()} on this device · self-declared and coarse; never derived from analyzer activity.`
          : "Presence sharing turned off on this device · others see “not shared”, which is not the same as offline.",
      };
    }
    case "tick_transfers": {
      const bytesPerTick = action.bytesPerTick ?? SOCIAL_TRANSFER_BYTES_PER_TICK;
      let changed = false;
      const offers = snapshot.file_offers.map((offer) => {
        if (TERMINAL_OFFER_STATES.has(offer.state)) return offer;
        if (offerIsExpired(offer, action.at)) {
          changed = true;
          return { ...offer, state: "expired" as const };
        }
        if (offer.state === "verifying") {
          changed = true;
          const recipients = offer.recipients.map((recipient) =>
            recipient.consent === "granted" ? { ...recipient, integrity: "verified" as const } : recipient);
          return { ...offer, recipients, state: "complete" as const };
        }
        if (offer.state !== "transferring") return offer;
        const live = liveTransferState(snapshot, offer, action.at);
        if (live !== "transferring") {
          changed = true;
          return { ...offer, state: live };
        }
        changed = true;
        const recipients = offer.recipients.map((recipient) => {
          if (recipient.consent !== "granted") return recipient;
          const received = Math.min(offer.file.size_bytes, (recipient.bytes_received ?? 0) + bytesPerTick);
          return { ...recipient, bytes_received: received };
        });
        const grantedRecipients = recipients.filter((recipient) => recipient.consent === "granted");
        if (grantedRecipients.length === 0) {
          return { ...offer, recipients, state: "awaiting_consent" as const };
        }
        const allReceived = grantedRecipients
          .every((recipient) => recipient.bytes_received === offer.file.size_bytes);
        return allReceived
          ? { ...offer, recipients: recipients.map((recipient) => recipient.consent === "granted" ? { ...recipient, integrity: "verifying" as const } : recipient), state: "verifying" as const }
          : { ...offer, recipients };
      });
      return changed ? { ...state, snapshot: { ...snapshot, file_offers: offers } } : state;
    }
    case "clear_notice":
      return state.notice === "" ? state : { ...state, notice: "" };
    default:
      return state;
  }
}
