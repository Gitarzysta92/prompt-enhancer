/**
 * Stable public façade for the social hub port contract. Consumers import
 * from here; the schema, synthetic fixture, unavailable adapter, and runtime
 * composition remain independently testable layers.
 */
export * from "./socialHubSchema";
export {
  SOCIAL_FIXTURE_CONVERSATION_IDS,
  SOCIAL_FIXTURE_NOW,
  SOCIAL_FIXTURE_PEOPLE_IDS,
  SOCIAL_SYNTHETIC_PRINCIPAL_ID,
  createSyntheticSocialHubPort,
  createSyntheticSocialSnapshot,
} from "./socialHubSynthetic";
export { createUnavailableSocialHubPort, emptySocialSnapshot } from "./socialHubUnavailable";
export { composeSocialHubPort, createSocialHubPortForRuntime } from "./socialHubRuntime";
