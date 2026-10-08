import {
  SOCIAL_HUB_PORT_VERSION,
  SocialHubError,
  type SocialCapabilityReport,
  type SocialHubPort,
  type SocialSnapshot,
  socialCapabilityInvariants,
} from "./socialHubSchema";

const LOCAL_RUNTIME_PRINCIPAL_ID = "91".repeat(32);

/**
 * The only snapshot the local loopback runtime can ever expose: zero people,
 * zero relationships, zero conversations, zero messages, zero file offers.
 * The page renders these zeros as an explicit "closed" state, never as an
 * empty-but-live inbox.
 */
export function emptySocialSnapshot(origin: SocialSnapshot["origin"], principalId: string, generatedAt: string): SocialSnapshot {
  return {
    port_version: SOCIAL_HUB_PORT_VERSION,
    origin,
    fictional: origin === "synthetic_fixture",
    principal_id: principalId,
    me_person_id: principalId,
    generated_at: generatedAt,
    people: [],
    friendships: [],
    friend_requests: [],
    conversations: [],
    messages: [],
    file_offers: [],
  };
}

/**
 * Honest adapter for runtimes without any social coordination service. It
 * reports the capability closed and rejects every snapshot read, so no
 * relationship, message, presence, or file offer can appear in local-real mode.
 */
export function createUnavailableSocialHubPort(
  now: () => string = () => new Date().toISOString(),
): SocialHubPort {
  const capabilities = (): SocialCapabilityReport => ({
    port_version: SOCIAL_HUB_PORT_VERSION,
    origin: "local_loopback",
    principal_id: LOCAL_RUNTIME_PRINCIPAL_ID,
    state: "unavailable",
    reason: "local_runtime_has_no_social_service",
    fictional: false,
    ...socialCapabilityInvariants(),
    file_sharing: {
      state: "unavailable",
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
    origin: "local_loopback",
    principalId: LOCAL_RUNTIME_PRINCIPAL_ID,
    async getCapabilities() {
      return capabilities();
    },
    async getSnapshot() {
      throw new SocialHubError(
        "social_not_served_by_this_runtime",
        "No social coordination service serves this runtime; zero people, messages, and file offers are exposed.",
      );
    },
  };
}
