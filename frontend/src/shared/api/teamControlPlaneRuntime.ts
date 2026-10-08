import type { RuntimeDataMode } from "../platform/runtimeMode";
import type { PromptEnhancerTransport } from "./contracts";
import type { TeamControlPlanePort } from "./teamControlPlane";
import { createSyntheticTeamControlPlanePort } from "./teamControlPlaneSynthetic";
import {
  createLocalLoopbackTeamControlPlanePort,
  createUnavailableTeamControlPlanePort,
} from "./teamControlPlaneUnavailable";

interface RegisteredRuntimePort {
  mode: RuntimeDataMode;
  origin: TeamControlPlanePort["origin"];
  principalId: TeamControlPlanePort["principalId"];
  getCapabilities: TeamControlPlanePort["getCapabilities"];
  getAggregate: TeamControlPlanePort["getAggregate"];
  getMemberVisibility: TeamControlPlanePort["getMemberVisibility"];
}

// Module-private registration is intentionally not represented on the port
// object. A caller cannot earn local-real trust by relabelling fixture methods
// or forging a public symbol/property; only adapters composed here are known.
const registeredRuntimePorts = new WeakMap<TeamControlPlanePort, RegisteredRuntimePort>();

type ReadinessTransport = Pick<PromptEnhancerTransport, "getControlPlaneReadiness">;

function createRegisteredPort(
  mode: RuntimeDataMode,
  transport?: ReadinessTransport,
): TeamControlPlanePort {
  const port = mode === "synthetic_demo"
    ? createSyntheticTeamControlPlanePort()
    : transport === undefined
      ? createUnavailableTeamControlPlanePort()
      : createLocalLoopbackTeamControlPlanePort(transport);
  const frozen = Object.freeze(port);
  registeredRuntimePorts.set(frozen, {
    mode,
    origin: frozen.origin,
    principalId: frozen.principalId,
    getCapabilities: frozen.getCapabilities,
    getAggregate: frozen.getAggregate,
    getMemberVisibility: frozen.getMemberVisibility,
  });
  return frozen;
}

function isRegisteredForRuntime(port: TeamControlPlanePort, mode: RuntimeDataMode): boolean {
  const registration = registeredRuntimePorts.get(port);
  return registration !== undefined
    && registration.mode === mode
    && registration.origin === port.origin
    && registration.principalId === port.principalId
    && registration.getCapabilities === port.getCapabilities
    && registration.getAggregate === port.getAggregate
    && registration.getMemberVisibility === port.getMemberVisibility;
}

/**
 * Bind the runtime data mode to the only honest team port for it. The
 * synthetic preview gets the fictional fixture cohort; the local loopback
 * runtime gets a readiness-only adapter when the transport is supplied and an
 * unavailable fallback otherwise. Neither local adapter can read a cohort or
 * member row.
 * A remote control-plane adapter must not be added here until one exists and
 * carries approval-bound transport.
 */
export function createTeamControlPlanePortForRuntime(
  mode: RuntimeDataMode,
  transport?: ReadinessTransport,
): TeamControlPlanePort {
  return createRegisteredPort(mode, transport);
}

/**
 * Compose an injected port with the runtime without allowing fixture data to
 * cross into local-real mode. A mismatched fixture fails closed to the honest
 * unavailable loopback adapter; it is never merely relabelled as local data.
 */
export function composeTeamControlPlanePort(
  mode: RuntimeDataMode,
  injected?: TeamControlPlanePort,
): TeamControlPlanePort {
  if (injected === undefined) return createTeamControlPlanePortForRuntime(mode);
  if (mode === "local_real" && !isRegisteredForRuntime(injected, mode)) {
    return createTeamControlPlanePortForRuntime(mode);
  }
  return injected;
}

/**
 * The overlay may expose team context only for a privately registered runtime
 * adapter. The local adapter carries readiness only and cannot publish values;
 * arbitrary injected or relabelled ports still resolve to null.
 */
export function teamControlPlanePortForOverlay(
  mode: RuntimeDataMode,
  port: TeamControlPlanePort | null,
): TeamControlPlanePort | null {
  const expectedOrigin = mode === "synthetic_demo" ? "synthetic_fixture" : "local_loopback";
  return port !== null
    && port.origin === expectedOrigin
    && isRegisteredForRuntime(port, mode)
    ? port
    : null;
}
