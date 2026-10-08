import type { PromptEnhancerTransport } from "../api/contracts";

/**
 * Runtime data modes that are implemented today.
 *
 * A remote-approved mode is intentionally absent. It must not be added until
 * the runtime can carry and validate an approval-bound remote transport.
 */
export type RuntimeDataMode = "synthetic_demo" | "local_real";

export type RuntimeServiceState = "checking" | "available" | "unavailable";

export interface RuntimeHealth {
  status: "ok";
  costMode: "offline_only";
  dataTier: "metadata";
}

export interface SyntheticRuntimeTransport extends PromptEnhancerTransport {
  readonly runtimeKind: "synthetic_fixture";
}

export interface LocalRuntimeTransport extends PromptEnhancerTransport {
  readonly runtimeKind: "local_loopback";
  getRuntimeHealth(signal?: AbortSignal): Promise<RuntimeHealth>;
}

export type RuntimeTransport =
  | SyntheticRuntimeTransport
  | LocalRuntimeTransport;

export type RuntimeComposition =
  | {
      mode: "synthetic_demo";
      transport: SyntheticRuntimeTransport;
    }
  | {
      mode: "local_real";
      transport: LocalRuntimeTransport;
    };

export function resolveRuntimeDataMode({
  development,
  viteMode,
}: {
  development: boolean;
  viteMode: string;
}): RuntimeDataMode {
  if (development && viteMode !== "real") return "synthetic_demo";
  return "local_real";
}

/**
 * Bind the chosen data mode to the only transport kind allowed to serve it.
 * A mismatch throws before React mounts, so a local-real shell cannot silently
 * render fictional fixture data.
 */
export function createRuntimeComposition(
  mode: RuntimeDataMode,
  transport: RuntimeTransport,
): RuntimeComposition {
  if (mode === "synthetic_demo" && transport.runtimeKind === "synthetic_fixture") {
    return { mode, transport };
  }
  if (mode === "local_real" && transport.runtimeKind === "local_loopback") {
    return { mode, transport };
  }
  throw new Error("Runtime data mode and transport kind do not match.");
}
