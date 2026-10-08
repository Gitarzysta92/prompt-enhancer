import { describe, expect, it } from "vitest";
import {
  SOCIAL_FIXTURE_CONVERSATION_IDS as C,
  SOCIAL_FIXTURE_PEOPLE_IDS as P,
  createSyntheticSocialSnapshot,
} from "../../shared/api/socialHub";
import {
  DIRECT_PATH_LABELS,
  PRESENCE_VALUE_LABELS,
  canPerform,
  conversationById,
  createSocialHubState,
  friends,
  offerBytesReceived,
  offerDeclinedByEveryRecipient,
  offerDirectPathBlocked,
  pendingRequests,
  personById,
  personIsOnline,
  personPresence,
  searchSnapshot,
  socialHubReducer,
  threadReplies,
  totalUnread,
  unreadCount,
  type SocialHubState,
} from "./socialHubModel";

const AT = "2040-02-03T09:30:00Z";

function initial(): SocialHubState {
  return createSocialHubState(createSyntheticSocialSnapshot());
}

function conversation(state: SocialHubState, id: string) {
  const found = conversationById(state.snapshot, id);
  if (found === null) throw new Error("fixture conversation missing");
  return found;
}

describe("socialHubReducer", () => {
  it("counts unread messages after the read marker and clears them on select", () => {
    const state = initial();
    const guild = conversation(state, C.guild);
    expect(unreadCount(state.snapshot, guild)).toBe(3);
    expect(unreadCount(state.snapshot, conversation(state, C.releaseNotes))).toBe(2);
    expect(totalUnread(state.snapshot)).toBe(6);
    const next = socialHubReducer(state, { type: "select_conversation", conversationId: C.guild });
    expect(next.activeConversationId).toBe(C.guild);
    expect(unreadCount(next.snapshot, conversation(next, C.guild))).toBe(0);
    expect(totalUnread(next.snapshot)).toBe(3);
  });

  it("enforces role permissions for posting, threads, and reactions", () => {
    const state = initial();
    const releaseNotes = conversation(state, C.releaseNotes);
    expect(canPerform(state.snapshot, releaseNotes, "post")).toBe(false);
    expect(canPerform(state.snapshot, releaseNotes, "react")).toBe(true);
    const blocked = socialHubReducer(state, { type: "send_message", conversationId: C.releaseNotes, body: "not allowed", threadRootId: null, at: AT });
    expect(blocked).toBe(state);
    const guild = conversation(state, C.guild);
    expect(canPerform(state.snapshot, guild, "manage_roles")).toBe(true);
    const sent = socialHubReducer(state, { type: "send_message", conversationId: C.guild, body: "  Fixture local note  ", threadRootId: null, at: AT });
    const added = sent.snapshot.messages.find((message) => message.body === "Fixture local note");
    expect(added?.author_id).toBe(P.me);
    expect(added?.sent_at).toBe(AT);
    expect(sent.notice).toMatch(/Nothing was delivered/);
    expect(unreadCount(sent.snapshot, conversation(sent, C.guild))).toBe(0);
  });

  it("adds thread replies under their root and toggles reactions idempotently", () => {
    const state = initial();
    const root = state.snapshot.messages.find((message) => message.body.includes("proposing a synthetic metric review"));
    if (root === undefined) throw new Error("fixture root missing");
    expect(threadReplies(state.snapshot, root.id)).toHaveLength(2);
    const replied = socialHubReducer(state, { type: "send_message", conversationId: C.guild, body: "Fixture third reply", threadRootId: root.id, at: AT });
    expect(threadReplies(replied.snapshot, root.id)).toHaveLength(3);
    const reacted = socialHubReducer(replied, { type: "toggle_reaction", messageId: root.id, emoji: "👍", label: "thumbs up" });
    const thumbs = reacted.snapshot.messages.find((message) => message.id === root.id)?.reactions.find((reaction) => reaction.emoji === "👍");
    expect(thumbs?.person_ids).toContain(P.me);
    const unreacted = socialHubReducer(reacted, { type: "toggle_reaction", messageId: root.id, emoji: "👍", label: "thumbs up" });
    expect(unreacted.snapshot.messages.find((message) => message.id === root.id)?.reactions.find((reaction) => reaction.emoji === "👍")?.person_ids).not.toContain(P.me);

    const nestedReply = state.snapshot.messages.find((message) => message.thread_root_id === root.id)!;
    const foreignRoot = state.snapshot.messages.find((message) => (
      message.conversation_id !== C.guild && message.thread_root_id === null
    ))!;
    const guildState = socialHubReducer(state, { type: "select_conversation", conversationId: C.guild });
    expect(socialHubReducer(guildState, { type: "open_thread", rootId: nestedReply.id })).toBe(guildState);
    expect(socialHubReducer(guildState, { type: "open_thread", rootId: foreignRoot.id })).toBe(guildState);
    expect(socialHubReducer(state, { type: "send_message", conversationId: C.guild, body: "Nested reply", threadRootId: nestedReply.id, at: AT })).toBe(state);
    expect(socialHubReducer(state, { type: "send_message", conversationId: C.guild, body: "Cross-channel reply", threadRootId: foreignRoot.id, at: AT })).toBe(state);
  });

  it("lets a current member read an existing thread even without permission to start one", () => {
    const state = initial();
    const release = conversation(state, C.releaseNotes);
    expect(canPerform(state.snapshot, release, "start_thread")).toBe(false);
    const root = state.snapshot.messages.find((message) => message.conversation_id === C.releaseNotes)!;
    const reply = {
      ...root,
      id: "aa".repeat(32),
      body: "Fixture reply in an existing announcement thread.",
      thread_root_id: root.id,
    };
    const withReply: SocialHubState = {
      ...state,
      activeConversationId: C.releaseNotes,
      snapshot: { ...state.snapshot, messages: [...state.snapshot.messages, reply] },
    };
    const opened = socialHubReducer(withReply, { type: "open_thread", rootId: root.id });
    expect(opened.activeThreadRootId).toBe(root.id);
    expect(opened.notice).toMatch(/Thread opened · 1 reply/u);
  });

  it("keeps locally generated synthetic identifiers unique and exactly 64 hex characters", () => {
    let state = initial();
    for (let index = 0; index < 260; index += 1) {
      state = socialHubReducer(state, {
        type: "send_message",
        conversationId: C.guild,
        body: `Fixture local message ${index}`,
        threadRootId: null,
        at: AT,
      });
    }
    const localMessages = state.snapshot.messages.filter((message) => message.body.startsWith("Fixture local message "));
    expect(localMessages).toHaveLength(260);
    expect(new Set(localMessages.map((message) => message.id)).size).toBe(260);
    for (const message of localMessages) expect(message.id).toMatch(/^[0-9a-f]{64}$/u);
  });

  it("moves friend requests through accept, decline, withdraw, and send", () => {
    const state = initial();
    const incoming = pendingRequests(state.snapshot, "incoming");
    const outgoing = pendingRequests(state.snapshot, "outgoing");
    expect(incoming).toHaveLength(1);
    expect(outgoing).toHaveLength(1);
    expect(friends(state.snapshot)).toHaveLength(3);
    const accepted = socialHubReducer(state, { type: "accept_request", requestId: incoming[0].id, at: AT });
    expect(friends(accepted.snapshot).map((person) => person.id)).toContain(P.dana);
    expect(pendingRequests(accepted.snapshot, "incoming")).toHaveLength(0);
    const withdrawn = socialHubReducer(accepted, { type: "withdraw_request", requestId: outgoing[0].id });
    expect(pendingRequests(withdrawn.snapshot, "outgoing")).toHaveLength(0);
    const resent = socialHubReducer(withdrawn, { type: "send_request", personId: P.emery, at: AT });
    expect(pendingRequests(resent.snapshot, "outgoing")).toHaveLength(1);
    expect(socialHubReducer(resent, { type: "send_request", personId: P.emery, at: AT })).toBe(resent);
    const removed = socialHubReducer(resent, { type: "remove_friend", personId: P.alex });
    expect(friends(removed.snapshot).map((person) => person.id)).not.toContain(P.alex);
    expect(removed.snapshot.conversations.some((item) => item.id === C.dmAlex)).toBe(false);
    expect(removed.snapshot.messages.some((message) => message.conversation_id === C.dmAlex)).toBe(false);
    expect(removed.snapshot.file_offers.some((offer) => offer.conversation_id === C.dmAlex)).toBe(false);
    expect(removed.notice).toMatch(/direct conversation is no longer available through the social port/);
  });

  it("searches people, conversations, and messages without leaking the local principal", () => {
    const state = initial();
    const results = searchSnapshot(state.snapshot, "fixture");
    expect(results.people).toHaveLength(0);
    expect(results.conversations.length).toBeGreaterThan(0);
    expect(results.messages.length).toBeGreaterThan(5);
    expect(searchSnapshot(state.snapshot, "alex").people.map((person) => person.id)).toEqual([P.alex]);
    expect(searchSnapshot(state.snapshot, "   ")).toEqual({ people: [], conversations: [], messages: [] });
  });

  it("runs the direct-transfer simulation: consent → transferring → verifying → complete, with pause/resume", () => {
    let state = initial();
    const offer = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-readiness-notes.md");
    if (offer === undefined) throw new Error("fixture offer missing");
    expect(offer.state).toBe("awaiting_consent");
    expect(offerBytesReceived(offer)).toBeNull();
    // Ticks never move an offer that has no consent.
    state = socialHubReducer(state, { type: "tick_transfers", at: AT });
    expect(state.snapshot.file_offers.find((candidate) => candidate.id === offer.id)?.state).toBe("awaiting_consent");
    state = socialHubReducer(state, { type: "grant_consent", offerId: offer.id, at: AT });
    let current = state.snapshot.file_offers.find((candidate) => candidate.id === offer.id);
    expect(current?.state).toBe("transferring");
    expect(current?.recipients[0].consent).toBe("granted");
    state = socialHubReducer(state, { type: "tick_transfers", at: AT, bytesPerTick: 20_000 });
    current = state.snapshot.file_offers.find((candidate) => candidate.id === offer.id);
    expect(current?.recipients[0].bytes_received).toBe(20_000);
    state = socialHubReducer(state, { type: "pause_transfer", offerId: offer.id });
    expect(state.snapshot.file_offers.find((candidate) => candidate.id === offer.id)?.state).toBe("paused");
    state = socialHubReducer(state, { type: "tick_transfers", at: AT, bytesPerTick: 20_000 });
    expect(state.snapshot.file_offers.find((candidate) => candidate.id === offer.id)?.recipients[0].bytes_received).toBe(20_000);
    state = socialHubReducer(state, { type: "resume_transfer", offerId: offer.id, at: AT });
    state = socialHubReducer(state, { type: "tick_transfers", at: AT, bytesPerTick: 100_000_000 });
    current = state.snapshot.file_offers.find((candidate) => candidate.id === offer.id);
    expect(current?.state).toBe("verifying");
    expect(current?.recipients[0].bytes_received).toBe(offer.file.size_bytes);
    expect(current?.recipients[0].integrity).toBe("verifying");
    state = socialHubReducer(state, { type: "tick_transfers", at: AT });
    current = state.snapshot.file_offers.find((candidate) => candidate.id === offer.id);
    expect(current?.state).toBe("complete");
    expect(current?.recipients[0].integrity).toBe("verified");
  });

  it("never completes a transferring offer with zero consenting recipients", () => {
    const state = initial();
    const notes = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-readiness-notes.md")!;
    const defensive: SocialHubState = {
      ...state,
      snapshot: {
        ...state.snapshot,
        file_offers: state.snapshot.file_offers.map((offer) => offer.id === notes.id ? {
          ...offer,
          state: "transferring",
          recipients: offer.recipients.map((recipient) => ({ ...recipient, consent: "declined", bytes_received: null })),
        } : offer),
      },
    };
    const ticked = socialHubReducer(defensive, { type: "tick_transfers", at: AT });
    expect(ticked.snapshot.file_offers.find((offer) => offer.id === notes.id)?.state).toBe("awaiting_consent");
  });

  it("reports an offer every recipient declined as unable to transfer, not as awaiting consent", () => {
    let state = initial();
    const notes = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-readiness-notes.md");
    if (notes === undefined) throw new Error("fixture offer missing");
    expect(offerDeclinedByEveryRecipient(notes)).toBe(false);
    state = socialHubReducer(state, { type: "decline_consent", offerId: notes.id });
    const declined = state.snapshot.file_offers.find((candidate) => candidate.id === notes.id);
    if (declined === undefined) throw new Error("declined offer missing");
    expect(declined.recipients.every((recipient) => recipient.consent === "declined")).toBe(true);
    expect(offerDeclinedByEveryRecipient(declined)).toBe(true);
    // The port has no declined state, so the wire state is unchanged; no tick
    // may start a transfer and no byte count is ever implied.
    expect(declined.state).toBe("awaiting_consent");
    expect(offerBytesReceived(declined)).toBeNull();
    expect(socialHubReducer(state, { type: "tick_transfers", at: AT })
      .snapshot.file_offers.find((candidate) => candidate.id === notes.id)?.state).toBe("awaiting_consent");
    // Declining twice is a no-op, and an offer with a consenting recipient is never "declined by all".
    expect(socialHubReducer(state, { type: "decline_consent", offerId: notes.id })).toBe(state);
    const shared = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-evidence-list.csv");
    if (shared === undefined) throw new Error("fixture offer missing");
    expect(offerDeclinedByEveryRecipient(shared)).toBe(false);
  });

  it("keeps offers honest about owner availability, expiry, and revocation", () => {
    let state = initial();
    const offline = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-evidence-list.csv");
    if (offline === undefined) throw new Error("fixture offer missing");
    expect(offline.state).toBe("owner_offline");
    state = socialHubReducer(state, { type: "resume_transfer", offerId: offline.id, at: AT });
    expect(state.snapshot.file_offers.find((candidate) => candidate.id === offline.id)?.state).toBe("owner_offline");
    // A pending consent granted after expiry lands in expired, never transferring.
    const notes = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-readiness-notes.md");
    if (notes === undefined) throw new Error("fixture offer missing");
    const late = socialHubReducer(state, { type: "grant_consent", offerId: notes.id, at: "2041-01-01T00:00:00Z" });
    expect(late.snapshot.file_offers.find((candidate) => candidate.id === notes.id)?.state).toBe("expired");
    // The owner can revoke a live offer; a recipient cannot revoke someone else's.
    const mine = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-metric-summary.pdf");
    if (mine === undefined) throw new Error("fixture offer missing");
    const revoked = socialHubReducer(state, { type: "revoke_offer", offerId: mine.id });
    expect(revoked.snapshot.file_offers.find((candidate) => candidate.id === mine.id)?.state).toBe("revoked");
    expect(socialHubReducer(state, { type: "revoke_offer", offerId: notes.id })).toBe(state);
    // Ticks expire stale live offers instead of moving them.
    const ticked = socialHubReducer(revoked, { type: "tick_transfers", at: "2041-01-01T00:00:00Z" });
    expect(ticked.snapshot.file_offers.find((candidate) => candidate.id === offline.id)?.state).toBe("expired");
  });

  it("creates metadata-only offers scoped to consenting conversation members", () => {
    const state = initial();
    const created = socialHubReducer(state, {
      type: "create_offer",
      conversationId: C.guild,
      displayName: "synthetic-plan.md",
      sizeBytes: 4096,
      mediaType: "text/markdown",
      recipientIds: [P.alex, P.me, P.dana],
      at: AT,
      expiresAt: "2040-02-04T09:30:00Z",
    });
    const offer = created.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-plan.md");
    expect(offer?.owner_id).toBe(P.me);
    expect(offer?.recipients.map((recipient) => recipient.person_id)).toEqual([P.alex]);
    expect(offer?.state).toBe("awaiting_consent");
    expect(offer?.stored_by_coordination_service).toBe(false);
    expect(Object.keys(offer?.file ?? {}).sort()).toEqual(["digest_hex", "display_name", "media_type", "size_bytes"]);
    expect(created.snapshot.messages.some((message) => message.file_offer_id === offer?.id)).toBe(true);
    // Guests cannot offer files in a channel where sharing needs member or above.
    const asMemberOfAnnouncements = socialHubReducer(state, {
      type: "create_offer",
      conversationId: C.releaseNotes,
      displayName: "blocked.md",
      sizeBytes: 10,
      mediaType: "text/plain",
      recipientIds: [P.alex],
      at: AT,
      expiresAt: "2040-02-04T09:30:00Z",
    });
    expect(asMemberOfAnnouncements).toBe(state);
  });

  it("blocks bytes when either side has no direct path (symmetric NAT / CGNAT) and never falls back to a relay", () => {
    let state = initial();
    const sketch = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-lane-sketch.svg");
    if (sketch === undefined) throw new Error("fixture offer missing");
    expect(sketch.state).toBe("direct_path_unavailable");
    expect(offerDirectPathBlocked(state.snapshot, sketch)).toBe("unavailable_cgnat");
    // Resume cannot move it while the path is blocked; ticks never move it either.
    state = socialHubReducer(state, { type: "resume_transfer", offerId: sketch.id, at: AT });
    expect(state.snapshot.file_offers.find((candidate) => candidate.id === sketch.id)?.state).toBe("direct_path_unavailable");
    state = socialHubReducer(state, { type: "tick_transfers", at: AT });
    expect(state.snapshot.file_offers.find((candidate) => candidate.id === sketch.id)?.recipients[0].bytes_received).toBe(0);
    // A transferring offer whose recipient turns out to be behind symmetric NAT stops with the truthful state.
    const notes = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-readiness-notes.md")!;
    let live = socialHubReducer(state, { type: "grant_consent", offerId: notes.id, at: AT });
    expect(live.snapshot.file_offers.find((candidate) => candidate.id === notes.id)?.state).toBe("transferring");
    const nat: SocialHubState = {
      ...live,
      snapshot: {
        ...live.snapshot,
        people: live.snapshot.people.map((person) => person.id === P.me ? { ...person, direct_path: "unavailable_symmetric_nat" } : person),
      },
    };
    live = socialHubReducer(nat, { type: "tick_transfers", at: AT });
    expect(live.snapshot.file_offers.find((candidate) => candidate.id === notes.id)?.state).toBe("direct_path_unavailable");
    expect(offerDirectPathBlocked(live.snapshot, live.snapshot.file_offers.find((candidate) => candidate.id === notes.id)!)).toBe("unavailable_symmetric_nat");
    // Unknown is not blocked: it resolves when probed.
    expect(DIRECT_PATH_LABELS.unknown).toMatch(/not probed/);
  });

  it("queues a sender-offline offer on the sender's device with bounded expiry and releases it when the sender is online", () => {
    let state = initial();
    state = socialHubReducer(state, { type: "set_presence", sharing: "shared", level: "offline", at: AT });
    expect(personPresence(personById(state.snapshot, P.me))).toBe("offline");
    state = socialHubReducer(state, {
      type: "create_offer",
      conversationId: C.dmAlex,
      displayName: "synthetic-offline-notes.md",
      sizeBytes: 2048,
      mediaType: "text/markdown",
      recipientIds: [P.alex],
      at: AT,
      expiresAt: "2040-02-04T09:30:00Z",
    });
    const queued = state.snapshot.file_offers.find((candidate) => candidate.file.display_name === "synthetic-offline-notes.md");
    expect(queued?.state).toBe("queued_on_sender");
    expect(queued?.queue_location).toBe("sender_device");
    expect(queued?.stored_by_coordination_service).toBe(false);
    expect(state.notice).toMatch(/queued on this device because you are not currently shared as online/);
    // Expiry is bounded: a stale queued offer expires on tick, never lingering on a server.
    const stale = socialHubReducer(state, { type: "tick_transfers", at: "2041-01-01T00:00:00Z" });
    expect(stale.snapshot.file_offers.find((candidate) => candidate.id === queued!.id)?.state).toBe("expired");
    // Coming back online releases the queued offer into a live awaiting-consent offer.
    const online = socialHubReducer(state, { type: "set_presence", sharing: "shared", level: "online", at: AT });
    expect(online.snapshot.file_offers.find((candidate) => candidate.id === queued!.id)?.state).toBe("awaiting_consent");
    // A recipient may consent while the sender is offline; bytes still wait for the sender.
    const consentedOffline = socialHubReducer(state, { type: "grant_consent", offerId: queued!.id, at: AT });
    expect(consentedOffline).toBe(state); // I am the owner, not a recipient: nothing to consent to.
  });

  it("treats presence as an explicit coarse opt-in that is separate from analyzer activity and distinct from offline", () => {
    let state = initial();
    const finley = personById(state.snapshot, P.finley);
    expect(finley?.presence).toEqual({ sharing: "not_shared", level: null, source: "self_declared_opt_in" });
    expect(personPresence(finley)).toBe("not_shared");
    expect(personIsOnline(finley)).toBe(false);
    expect(PRESENCE_VALUE_LABELS.not_shared).toBe("Presence not shared");
    expect(PRESENCE_VALUE_LABELS.not_shared).not.toMatch(/offline/i);
    // Opting out clears the level; opting in without a level is rejected.
    state = socialHubReducer(state, { type: "set_presence", sharing: "not_shared", level: null, at: AT });
    expect(personById(state.snapshot, P.me)?.presence).toEqual({ sharing: "not_shared", level: null, source: "self_declared_opt_in" });
    expect(state.notice).toMatch(/not the same as offline/);
    expect(socialHubReducer(state, { type: "set_presence", sharing: "shared", level: null, at: AT })).toBe(state);
    // My live transfer pauses honestly when I stop being online.
    let live = socialHubReducer(initial(), { type: "grant_consent", offerId: initial().snapshot.file_offers[1].id, at: AT });
    live = socialHubReducer(live, { type: "set_presence", sharing: "shared", level: "away", at: AT });
    // The notes offer is owned by Alex, not me, so my presence does not change it; my own offers would.
    expect(live.snapshot.file_offers[1].state).toBe("transferring");
    expect(live.notice).toMatch(/never derived from analyzer activity/);
  });
});
