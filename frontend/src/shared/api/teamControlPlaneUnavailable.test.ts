import { describe, expect, it, vi } from "vitest";
import type { ControlPlaneReadiness } from "./contracts";
import {
  CONTROL_PLANE_READINESS_GAPS,
  ControlPlaneReadinessPayloadError,
} from "./controlPlaneReadiness";
import { TransportError } from "./httpTransport";
import {
  isTeamControlPlaneError,
  teamCapabilityReportIsValid,
} from "./teamControlPlane";
import { createLocalLoopbackTeamControlPlanePort } from "./teamControlPlaneUnavailable";

const READINESS: ControlPlaneReadiness = {
  contract_version: "control-plane-v2",
  delivery_guarantee: "at_least_once_with_monotonic_ack",
  gaps: [...CONTROL_PLANE_READINESS_GAPS].sort(),
  production_ready: false,
  profile: "development",
  remote_listening_enabled: false,
};

describe("local loopback team control-plane port", () => {
  it("publishes exact backend readiness while every team/member data path stays closed", async () => {
    const getControlPlaneReadiness = vi.fn(async () => READINESS);
    const port = createLocalLoopbackTeamControlPlanePort(
      { getControlPlaneReadiness },
      () => "2040-03-01T12:00:00Z",
    );

    const report = await port.getCapabilities();

    expect(getControlPlaneReadiness).toHaveBeenCalledTimes(1);
    expect(teamCapabilityReportIsValid(report, port)).toBe(true);
    expect(report.control_plane_readiness).toEqual(READINESS);
    expect(report.scopes.map((access) => [access.scope, access.state, access.reason])).toEqual([
      ["me", "allowed", "personal_scope_served_locally"],
      ["team", "unavailable", "development_control_plane_incomplete"],
      ["organization", "unavailable", "development_control_plane_incomplete"],
    ]);
    expect(report.member_visibility).toMatchObject({
      state: "unavailable",
      reason: "development_control_plane_incomplete",
    });

    await expect(port.getAggregate({} as never)).rejects.toSatisfy(
      (error: unknown) => isTeamControlPlaneError(error)
        && error.code === "scope_not_served_by_this_runtime",
    );
    await expect(port.getMemberVisibility({} as never)).rejects.toSatisfy(
      (error: unknown) => isTeamControlPlaneError(error)
        && error.code === "member_visibility_unavailable",
    );
  });

  it("maps an unmounted optional route to the honest unavailable capability", async () => {
    const port = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => {
        throw new TransportError("not mounted", 404);
      },
    }, () => "2040-03-01T12:00:00Z");

    const report = await port.getCapabilities();

    expect(report.control_plane_readiness).toBeNull();
    expect(report.scopes.find((access) => access.scope === "team")).toMatchObject({
      state: "unavailable",
      reason: "local_runtime_has_no_team_service",
    });
    expect(teamCapabilityReportIsValid(report, port)).toBe(true);
  });

  it("does not launder malformed or insecure readiness into unavailable", async () => {
    const malformed = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => {
        throw new ControlPlaneReadinessPayloadError();
      },
    });
    const unsafeCache = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => {
        throw new TransportError("cache contract missing", 200);
      },
    });

    await expect(malformed.getCapabilities()).rejects.toBeInstanceOf(
      ControlPlaneReadinessPayloadError,
    );
    await expect(unsafeCache.getCapabilities()).rejects.toMatchObject({ status: 200 });
  });

  it("maps a browser network failure to unavailable but rethrows programming errors", async () => {
    const offline = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => {
        throw new TypeError("synthetic network failure");
      },
    });
    const broken = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => {
        throw new Error("synthetic adapter bug");
      },
    });

    await expect(offline.getCapabilities()).resolves.toMatchObject({
      control_plane_readiness: null,
    });
    await expect(broken.getCapabilities()).rejects.toThrow("synthetic adapter bug");
  });
});
