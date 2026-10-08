import { describe, expect, it } from "vitest";
import {
  SOCIAL_HUB_PORT_VERSION,
  composeSocialHubPort,
  createSocialHubPortForRuntime,
  createSyntheticSocialHubPort,
  createSyntheticSocialSnapshot,
  createUnavailableSocialHubPort,
  emptySocialSnapshot,
  isSocialHubError,
  socialCapabilityReportIsValid,
  socialSnapshotIsValid,
} from "./socialHub";

const PSEUDONYM = /^[0-9a-f]{64}$/;
const FORBIDDEN_FIXTURE_TEXT = /@(?!example\.invalid)[a-z0-9.-]+\.[a-z]{2,}|\/home\/|C:\\Users\\(?!Example)|sk-[A-Za-z0-9]{8,}/;

describe("social hub port", () => {
  it("serves a fictional, valid, metadata-only fixture in the synthetic preview", async () => {
    const port = createSyntheticSocialHubPort();
    const capabilities = await port.getCapabilities();
    expect(capabilities.origin).toBe("synthetic_fixture");
    expect(capabilities.fictional).toBe(true);
    expect(capabilities.state).toBe("available");
    expect(capabilities.delivery).toBe("local_state_only");
    expect(capabilities.encryption).toBe("not_implemented");
    expect(capabilities.coordination_plane_observes).toEqual(["relationship", "timing", "availability", "size_class"]);
    expect(capabilities.groups).toEqual({ access: "invite_only", discoverable: false, max_members: 32 });
    expect(capabilities.presence).toEqual({ model: "explicit_opt_in_coarse", derived_from_analyzer_activity: false });
    expect(capabilities.payload_policy.analyzer_content).toBe("never_inserted");
    expect(capabilities.data_controls).toEqual({ export: "not_offered_no_server_data", delete: "not_offered_no_server_data" });
    expect(capabilities.file_sharing).toMatchObject({
      path: "direct_only", relay: "none", turn: "none",
      stored_by_coordination_service: false, bytes_on_coordination_plane: "never",
      offline_offer_queue: "sender_device_bounded_expiry",
    });
    expect(socialCapabilityReportIsValid(capabilities, port)).toBe(true);

    const snapshot = await port.getSnapshot();
    expect(snapshot.port_version).toBe(SOCIAL_HUB_PORT_VERSION);
    expect(snapshot.fictional).toBe(true);
    expect(socialSnapshotIsValid(snapshot, port)).toBe(true);
    expect(snapshot.people.length).toBeGreaterThan(3);
    for (const person of snapshot.people) {
      expect(person.id).toMatch(PSEUDONYM);
      expect(person.display_name).toMatch(/Example/);
      expect(person.handle).toMatch(/@example\.invalid$/);
    }
    for (const offer of snapshot.file_offers) {
      expect(Object.keys(offer.file).sort()).toEqual(["digest_hex", "display_name", "media_type", "size_bytes"]);
      expect(offer.stored_by_coordination_service).toBe(false);
      expect(offer.requires_owner_online).toBe(true);
      expect(offer.queue_location).toBe("sender_device");
      expect(offer.transport_path).toBe("direct_only");
      expect(offer.revoke_recalls_downloaded_bytes).toBe(false);
    }
    for (const conversation of snapshot.conversations) {
      expect(conversation.access).toBe("invite_only");
      expect(conversation.discoverable).toBe(false);
      expect(conversation.members.length).toBeGreaterThan(0);
    }
    // Presence is opt-in: at least one fixture person has not opted in, and no signal claims another source.
    expect(snapshot.people.some((person) => person.presence.sharing === "not_shared" && person.presence.level === null)).toBe(true);
    expect(snapshot.people.every((person) => person.presence.source === "self_declared_opt_in")).toBe(true);
    // No fixture field could carry analyzer content: message bodies and file metadata are the only free text.
    const json = JSON.stringify(snapshot);
    expect(json).not.toMatch(/session_id|prompt_text|metric_key|explanation|transcript/);
    expect(JSON.stringify(snapshot)).not.toMatch(FORBIDDEN_FIXTURE_TEXT);
    // Each read is an independent copy: mutating one never leaks into the next.
    const other = await port.getSnapshot();
    expect(other).not.toBe(snapshot);
    expect(other).toEqual(snapshot);
  });

  it("fails closed in the local loopback runtime with zero people, messages, and offers", async () => {
    const port = createUnavailableSocialHubPort(() => "2040-02-03T09:00:00Z");
    const capabilities = await port.getCapabilities();
    expect(capabilities.state).toBe("unavailable");
    expect(capabilities.reason).toBe("local_runtime_has_no_social_service");
    expect(capabilities.fictional).toBe(false);
    expect(capabilities.file_sharing.state).toBe("unavailable");
    expect(socialCapabilityReportIsValid(capabilities, port)).toBe(true);
    await expect(port.getSnapshot()).rejects.toSatisfy((error: unknown) =>
      isSocialHubError(error) && error.code === "social_not_served_by_this_runtime");
    const empty = emptySocialSnapshot(port.origin, port.principalId, "2040-02-03T09:00:00Z");
    expect(empty.people).toHaveLength(0);
    expect(empty.friendships).toHaveLength(0);
    expect(empty.messages).toHaveLength(0);
    expect(empty.file_offers).toHaveLength(0);
  });

  it("rejects capability reports that over-claim encryption, relay, or fixture provenance", async () => {
    const port = createSyntheticSocialHubPort();
    const report = await port.getCapabilities();
    expect(socialCapabilityReportIsValid({ ...report, fictional: false }, port)).toBe(false);
    expect(socialCapabilityReportIsValid({
      ...report,
      encryption: "available" as unknown as "not_implemented",
    }, port)).toBe(false);
    expect(socialCapabilityReportIsValid({
      ...report,
      file_sharing: { ...report.file_sharing, relay: "available" as unknown as "none" },
    }, port)).toBe(false);
    expect(socialCapabilityReportIsValid({
      ...report,
      coordination_plane_observes: ["timing"],
    }, port)).toBe(false);
  });

  it("never lets a fixture port cross into local-real mode", async () => {
    const fixture = createSyntheticSocialHubPort();
    const composed = composeSocialHubPort("local_real", fixture);
    expect(composed).not.toBe(fixture);
    expect(composed.origin).toBe("local_loopback");
    await expect(composed.getSnapshot()).rejects.toBeInstanceOf(Error);

    const relabelled = { ...fixture, origin: "local_loopback" as const };
    expect(composeSocialHubPort("local_real", relabelled).origin).toBe("local_loopback");
    await expect(composeSocialHubPort("local_real", relabelled).getSnapshot()).rejects.toBeInstanceOf(Error);

    const registered = createSocialHubPortForRuntime("local_real");
    expect(composeSocialHubPort("local_real", registered)).toBe(registered);
    expect(composeSocialHubPort("synthetic_demo", fixture)).toBe(fixture);
    expect(composeSocialHubPort("synthetic_demo").origin).toBe("synthetic_fixture");
  });

  it("rejects relabelled or dangling snapshots", () => {
    const port = createSyntheticSocialHubPort();
    const base = createSyntheticSocialSnapshot();
    expect(socialSnapshotIsValid({ ...base, fictional: false }, port)).toBe(false);
    expect(socialSnapshotIsValid({ ...base, origin: "local_loopback" }, port)).toBe(false);
    expect(socialSnapshotIsValid({ ...base, principal_id: "ff".repeat(32) }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      messages: [...base.messages, { ...base.messages[0], id: "00".repeat(32), thread_root_id: "01".repeat(32) }],
    }, port)).toBe(false);
    expect(socialSnapshotIsValid(null, port)).toBe(false);
    expect(socialSnapshotIsValid({ people: [] }, port)).toBe(false);
    const missingPermission = structuredClone(base) as any;
    delete missingPermission.conversations[0].permissions.post;
    expect(socialSnapshotIsValid(missingPermission, port)).toBe(false);
    const malformedPeople = { ...base, people: "not-an-array" };
    expect(socialSnapshotIsValid(malformedPeople, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      friendships: base.friendships.filter((friendship) => friendship.person_id !== base.conversations[0].members[1].person_id),
    }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      file_offers: base.file_offers.map((offer) => ({ ...offer, stored_by_coordination_service: true as unknown as false })),
    }, port)).toBe(false);
  });

  it("rejects public or discoverable groups, presence that is not opt-in, and recipients outside the group", () => {
    const port = createSyntheticSocialHubPort();
    const base = createSyntheticSocialSnapshot();
    expect(socialSnapshotIsValid({
      ...base,
      conversations: base.conversations.map((conversation) => ({ ...conversation, discoverable: true as unknown as false })),
    }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      conversations: base.conversations.map((conversation) => ({ ...conversation, access: "public" as unknown as "invite_only" })),
    }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      people: base.people.map((person) => ({ ...person, presence: { sharing: "not_shared", level: "offline", source: "self_declared_opt_in" } })),
    }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      people: base.people.map((person) => ({ ...person, presence: { ...person.presence, source: "analyzer_activity" as unknown as "self_declared_opt_in" } })),
    }, port)).toBe(false);
    const [first] = base.file_offers;
    const outsider = base.people.find((person) => !base.conversations.find((conversation) => conversation.id === first.conversation_id)!.members.some((member) => member.person_id === person.id))!;
    expect(socialSnapshotIsValid({
      ...base,
      file_offers: [{ ...first, recipients: [...first.recipients, { person_id: outsider.id, consent: "pending", bytes_received: null, integrity: "not_started" }] }, ...base.file_offers.slice(1)],
    }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      file_offers: base.file_offers.map((offer) => ({ ...offer, queue_location: "server" as unknown as "sender_device" })),
    }, port)).toBe(false);
    expect(socialSnapshotIsValid({
      ...base,
      file_offers: base.file_offers.map((offer) => ({ ...offer, transport_path: "relay" as unknown as "direct_only" })),
    }, port)).toBe(false);
  });

  it("rejects membership and authorization drift inside conversations, threads, and offers", () => {
    const port = createSyntheticSocialHubPort();
    const base = createSyntheticSocialSnapshot();
    const group = base.conversations.find((conversation) => conversation.kind === "group_channel")!;
    const outsider = base.people.find((person) => !group.members.some((member) => member.person_id === person.id))!;
    expect(socialSnapshotIsValid({
      ...base,
      conversations: base.conversations.map((conversation) => conversation.id === group.id
        ? { ...conversation, members: conversation.members.filter((member) => member.person_id !== base.me_person_id) }
        : conversation),
    }, port)).toBe(false);
    const groupMessage = base.messages.find((message) => message.conversation_id === group.id)!;
    expect(socialSnapshotIsValid({
      ...base,
      messages: base.messages.map((message) => message.id === groupMessage.id
        ? { ...message, author_id: outsider.id }
        : message),
    }, port)).toBe(false);
    const foreignRoot = base.messages.find((message) => (
      message.conversation_id !== group.id && message.thread_root_id === null
    ))!;
    expect(socialSnapshotIsValid({
      ...base,
      messages: base.messages.map((message) => message.id === groupMessage.id
        ? { ...message, thread_root_id: foreignRoot.id }
        : message),
    }, port)).toBe(false);
    const offer = base.file_offers[0];
    const nonMemberOwner = base.people.find((person) => (
      !base.conversations.find((conversation) => conversation.id === offer.conversation_id)!
        .members.some((member) => member.person_id === person.id)
    ))!;
    expect(socialSnapshotIsValid({
      ...base,
      file_offers: base.file_offers.map((candidate) => candidate.id === offer.id
        ? { ...candidate, owner_id: nonMemberOwner.id }
        : candidate),
    }, port)).toBe(false);
  });

  it("keeps the local loopback capability report on the same truths with everything closed", async () => {
    const port = createUnavailableSocialHubPort(() => "2040-02-03T09:00:00Z");
    const capabilities = await port.getCapabilities();
    expect(capabilities.encryption).toBe("not_implemented");
    expect(capabilities.groups.discoverable).toBe(false);
    expect(capabilities.presence.derived_from_analyzer_activity).toBe(false);
    expect(capabilities.payload_policy.analyzer_content).toBe("never_inserted");
    expect(capabilities.file_sharing).toMatchObject({ state: "unavailable", path: "direct_only", relay: "none", turn: "none", bytes_on_coordination_plane: "never" });
    expect(capabilities.data_controls.export).toBe("not_offered_no_server_data");
  });
});
