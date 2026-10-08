import { useEffect, useRef, useState } from "react";
import type {
  ProviderCompatibilityState,
  ProviderCompatibilityStatus,
} from "../../shared/api/contracts";
import { StatusPill, type PillTone } from "../../shared/ui/StatusPill";

const STATE_COPY: Record<
  ProviderCompatibilityState,
  { label: string; tone: PillTone }
> = {
  exact: { label: "Exact match", tone: "positive" },
  compatible: { label: "Compatible", tone: "positive" },
  degraded: { label: "Degraded", tone: "warning" },
  untested: { label: "Not checked", tone: "neutral" },
  incompatible: { label: "Incompatible", tone: "danger" },
  unavailable: { label: "Unavailable", tone: "warning" },
};

const REASON_COPY: Record<ProviderCompatibilityStatus["reason_code"], string> = {
  exact_match: "Installed provider schemas exactly match this adapter. This content-free check does not test an individual session read.",
  compatible_version: "Installed provider schemas are within the tested compatibility range. This content-free check does not test an individual session read.",
  degraded_extraction: "Only partial extraction is supported, so prompt-text analysis stays disabled.",
  not_checked: "Run an explicit compatibility check before prompt-text analysis.",
  provider_unavailable: "The local provider could not be reached during the last check.",
  provider_version_unsupported: "This provider version is outside the tested compatibility range.",
  adapter_outdated: "The local Prompt Enhancer adapter needs an update.",
  source_schema_unsupported: "The provider session schema is not supported by this adapter.",
  content_schema_unsupported: "The provider content schema is not supported by this adapter.",
  check_failed: "The local compatibility check did not complete.",
};

function familyVersion(family: string, version: string | null): string {
  return version === null ? `${family} · version unknown` : `${family} · ${version}`;
}

function capabilityLabel(
  capability: ProviderCompatibilityStatus["capability"],
): string {
  return capability === "session_text_analysis"
    ? "Session text analysis"
    : "Operational events";
}

export function isPromptTextCompatible(
  status: ProviderCompatibilityStatus | null,
): boolean {
  return (
    status !== null &&
    status.capability === "session_text_analysis" &&
    status.capability_state === "supported" &&
    (status.state === "exact" || status.state === "compatible")
  );
}

export function promptTextCompatibilityBlocker(
  status: ProviderCompatibilityStatus | null,
): string | null {
  if (isPromptTextCompatible(status)) return null;
  if (status?.capability === "operational_events") {
    return "This compatibility result covers operational events, not session-text analysis, so prompt-text analysis stays disabled.";
  }
  if (status === null || status.state === "untested") {
    return "Provider compatibility has not been checked, so prompt-text analysis stays disabled.";
  }
  if (status.state === "degraded") {
    return "Provider extraction is degraded, so prompt-text analysis stays disabled.";
  }
  if (status.state === "incompatible") {
    return "This provider is incompatible with prompt-text analysis.";
  }
  if (status.state === "unavailable") {
    return "Provider compatibility is unavailable, so prompt-text analysis stays disabled.";
  }
  return "Prompt-text capability is not supported by this compatibility result.";
}

export function ProviderCompatibilityCard({
  status,
  loading = false,
  onCheck,
  onUpdate,
}: {
  status: ProviderCompatibilityStatus | null;
  loading?: boolean;
  onCheck?: (signal: AbortSignal) => Promise<void>;
  onUpdate?: () => void;
}) {
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  async function check() {
    if (!onCheck || checking) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setChecking(true);
    setError("");
    try {
      await onCheck(controller.signal);
    } catch {
      if (!controller.signal.aborted) {
        setError("The local compatibility check could not be completed.");
      }
    } finally {
      if (!controller.signal.aborted) setChecking(false);
      controllerRef.current = null;
    }
  }

  const state = status ? STATE_COPY[status.state] : STATE_COPY.untested;
  const canUpdate =
    status?.update_support === "supported" &&
    status.update_target !== null &&
    onUpdate !== undefined;

  return (
    <section
      aria-labelledby="provider-compatibility-title"
      className="provider-compatibility"
    >
      <div className="provider-compatibility__heading">
        <div>
          <p className="eyebrow">Provider readiness</p>
          <h3 id="provider-compatibility-title">Installed schema compatibility</h3>
        </div>
        <div aria-atomic="true" aria-live="polite" role="status">
          <span aria-hidden="true">
            <StatusPill tone={state.tone}>{loading ? "Loading" : state.label}</StatusPill>
          </span>
          <span className="sr-only">
            {loading
              ? "Loading provider compatibility status."
              : `${state.label}. ${status
                ? `${capabilityLabel(status.capability)}: ${status.capability_state}. ${REASON_COPY[status.reason_code]}`
                : "No verified compatibility result is available."}`}
          </span>
        </div>
      </div>

      {status ? (
        <>
          <p className="provider-compatibility__reason">
            {REASON_COPY[status.reason_code]}
          </p>
          <dl className="provider-compatibility__versions">
            <div>
              <dt>Provider</dt>
              <dd>{familyVersion(status.provider_family, status.provider_version)}</dd>
            </div>
            <div>
              <dt>Adapter</dt>
              <dd>{familyVersion(status.adapter_family, status.adapter_version)}</dd>
            </div>
            <div>
              <dt>Session schema</dt>
              <dd>{familyVersion(status.source_schema_family, status.source_schema_version)}</dd>
            </div>
            <div>
              <dt>Content schema</dt>
              <dd>{familyVersion(status.content_schema_family, status.content_schema_version)}</dd>
            </div>
          </dl>
          <p className="provider-compatibility__capability">
            {capabilityLabel(status.capability)}: <strong>{status.capability_state}</strong>
          </p>
        </>
      ) : (
        <p className="provider-compatibility__reason">
          {loading
            ? "Loading the last content-free compatibility result."
            : "No verified compatibility result is available for this provider."}
        </p>
      )}

      {error && <p className="provider-compatibility__error" role="alert">{error}</p>}
      <div className="provider-compatibility__actions">
        {onCheck && (
          <button
            className="button button--secondary button--compact"
            disabled={checking || loading}
            onClick={() => void check()}
            type="button"
          >
            {checking ? "Checking…" : "Check compatibility"}
          </button>
        )}
        {canUpdate && (
          <button
            className="button button--secondary button--compact"
            onClick={onUpdate}
            type="button"
          >
            {status.update_target === "prompt_enhancer"
              ? "Update Prompt Enhancer"
              : "Update provider"}
          </button>
        )}
      </div>
    </section>
  );
}
