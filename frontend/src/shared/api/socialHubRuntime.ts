import type { RuntimeDataMode } from "../platform/runtimeMode";
import type { SocialHubPort } from "./socialHubSchema";
import { createSyntheticSocialHubPort } from "./socialHubSynthetic";
import { createUnavailableSocialHubPort } from "./socialHubUnavailable";

interface RegisteredSocialPort {
  mode: RuntimeDataMode;
  origin: SocialHubPort["origin"];
  principalId: SocialHubPort["principalId"];
  getCapabilities: SocialHubPort["getCapabilities"];
  getSnapshot: SocialHubPort["getSnapshot"];
}

// Module-private registration, mirroring the team control-plane runtime: a
// caller cannot earn local-real trust by relabelling fixture methods.
const registeredSocialPorts = new WeakMap<SocialHubPort, RegisteredSocialPort>();

function createRegisteredPort(mode: RuntimeDataMode): SocialHubPort {
  const port = mode === "synthetic_demo"
    ? createSyntheticSocialHubPort()
    : createUnavailableSocialHubPort();
  const frozen = Object.freeze(port);
  registeredSocialPorts.set(frozen, {
    mode,
    origin: frozen.origin,
    principalId: frozen.principalId,
    getCapabilities: frozen.getCapabilities,
    getSnapshot: frozen.getSnapshot,
  });
  return frozen;
}

function isRegisteredForRuntime(port: SocialHubPort, mode: RuntimeDataMode): boolean {
  const registration = registeredSocialPorts.get(port);
  return registration !== undefined
    && registration.mode === mode
    && registration.origin === port.origin
    && registration.principalId === port.principalId
    && registration.getCapabilities === port.getCapabilities
    && registration.getSnapshot === port.getSnapshot;
}

/**
 * Bind the runtime data mode to the only honest social port for it: the
 * fictional fixture in the synthetic preview, the closed adapter in the local
 * loopback runtime. A remote adapter must not be added until one exists with
 * an approval-bound transport.
 */
export function createSocialHubPortForRuntime(mode: RuntimeDataMode): SocialHubPort {
  return createRegisteredPort(mode);
}

/**
 * Compose an injected port with the runtime without letting fixture data cross
 * into local-real mode. An unregistered or mismatched port fails closed to the
 * unavailable adapter; it is never relabelled as local data.
 */
export function composeSocialHubPort(mode: RuntimeDataMode, injected?: SocialHubPort): SocialHubPort {
  if (injected === undefined) return createSocialHubPortForRuntime(mode);
  if (mode === "local_real" && !isRegisteredForRuntime(injected, mode)) {
    return createSocialHubPortForRuntime(mode);
  }
  return injected;
}
