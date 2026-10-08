import { useEffect, useRef, useState } from "react";
import type { OnboardingStatus, PromptEnhancerTransport, ProviderDetection } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { AppRoute } from "../../shared/platform/platform";
import { Icon } from "../../shared/ui/Icon";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import "./FirstRunPanel.css";

const DISMISS_KEY = "prompt-enhancer.first-run.dismissed";
const CLAUDE_ENUMERATION_UNAVAILABLE = "claude_transcript_enumeration_unavailable" as const;
const CLAUDE_TRANSCRIPT_COUNT_CAPPED = "claude_transcript_count_capped" as const;
const RFC3339_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/;

const ONBOARDING_STATUS_KEYS = [
  "any_installed",
  "claude_home_override_supported",
  "contract_version",
  "last_refresh_at",
  "last_refresh_error",
  "needs_onboarding",
  "providers",
  "refresh_interval_seconds",
] as const;
const PROVIDER_DETECTION_KEYS = [
  "consent_active",
  "indexed_sessions",
  "installed",
  "provider",
  "signal",
  "transcript_files",
] as const;
const ONBOARDING_RESULT_KEYS = ["granted", "indexed_sessions", "status"] as const;

export type TruthfulProviderDetection = Omit<
  ProviderDetection,
  "transcript_files"
> & {
  transcript_files: number | null;
};

export type TruthfulOnboardingStatus = Omit<OnboardingStatus, "last_refresh_at" | "providers"> & {
  last_refresh_at: string | null;
  providers: TruthfulProviderDetection[];
};

type TruthfulOnboardingResult = {
  granted: ("claude_code" | "codex")[];
  indexed_sessions: number | null;
  status: TruthfulOnboardingStatus;
};

type FirstRunTransport = {
  getOnboardingStatus(signal?: AbortSignal): Promise<unknown>;
  acceptOnboarding(
    request: Parameters<PromptEnhancerTransport["acceptOnboarding"]>[0],
    signal?: AbortSignal,
  ): Promise<unknown>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length
    && keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

function isSafeCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = RFC3339_DATE_TIME.exec(value);
  if (match === null || !Number.isFinite(Date.parse(value))) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[7] === "Z" ? 0 : Number(match[8]);
  const offsetMinute = match[7] === "Z" ? 0 : Number(match[9]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1
    && month >= 1
    && month <= 12
    && day >= 1
    && day <= daysInMonth[month - 1]
    && hour <= 23
    && minute <= 59
    && second <= 59
    && offsetHour <= 23
    && offsetMinute <= 59;
}

export function safeOnboardingStatus(value: unknown): value is TruthfulOnboardingStatus {
  if (!isRecord(value)
    || !hasExactKeys(value, ONBOARDING_STATUS_KEYS)
    || value.contract_version !== "onboarding.v1") return false;
  if (!Array.isArray(value.providers) || value.providers.length !== 2) return false;
  const providers = new Set<string>();
  const valid = value.providers.every((p) => {
    if (!isRecord(p)
      || !hasExactKeys(p, PROVIDER_DETECTION_KEYS)
      || (p.provider !== "codex" && p.provider !== "claude_code")) return false;
    if (providers.has(p.provider)) return false;
    providers.add(p.provider);
    const indexedSessions = p.indexed_sessions;
    const transcriptFiles = p.transcript_files;
    if (typeof p.installed !== "boolean" || typeof p.consent_active !== "boolean") return false;
    if (indexedSessions !== null && !isSafeCount(indexedSessions)) return false;
    if (transcriptFiles !== null && !isSafeCount(transcriptFiles)) return false;

    if (p.provider === "codex") {
      return transcriptFiles === null
        && (p.installed ? p.signal === "codex_cli_on_path" : p.signal === "not_found");
    }
    if (!p.installed) return p.signal === "not_found" && transcriptFiles === null;
    if (p.signal === "claude_transcript_root") return transcriptFiles !== null;
    return (p.signal === CLAUDE_ENUMERATION_UNAVAILABLE
        || p.signal === CLAUDE_TRANSCRIPT_COUNT_CAPPED)
      && transcriptFiles === null;
  });
  if (!valid
    || typeof value.needs_onboarding !== "boolean"
    || typeof value.any_installed !== "boolean"
    || typeof value.last_refresh_error !== "boolean"
    || typeof value.claude_home_override_supported !== "boolean"
    || !isSafeCount(value.refresh_interval_seconds)
    || value.refresh_interval_seconds < 60
    || (value.last_refresh_at !== null && !isDateTime(value.last_refresh_at))) return false;

  const anyInstalled = value.providers.some((provider) => provider.installed);
  const needsOnboarding = value.providers.some(
    (provider) => provider.installed && !provider.consent_active,
  ) || !anyInstalled;
  return value.any_installed === anyInstalled
    && value.needs_onboarding === needsOnboarding;
}

export function safeOnboardingResult(
  value: unknown,
  requestedProviders: readonly ("claude_code" | "codex")[],
): value is TruthfulOnboardingResult {
  const status = isRecord(value) ? value.status : null;
  if (!isRecord(value)
    || !hasExactKeys(value, ONBOARDING_RESULT_KEYS)
    || !Array.isArray(value.granted)
    || value.granted.length === 0
    || !safeOnboardingStatus(status)
    || (value.indexed_sessions !== null && !isSafeCount(value.indexed_sessions))) return false;
  const granted = new Set<string>();
  if (!value.granted.every((provider) => {
    if ((provider !== "codex" && provider !== "claude_code") || granted.has(provider)) return false;
    granted.add(provider);
    return true;
  })) return false;
  const requested = new Set(requestedProviders);
  if (granted.size !== requested.size
    || ![...requested].every((provider) => granted.has(provider))) return false;
  return value.granted.every((provider) => status.providers.some(
    (statusProvider) => statusProvider.provider === provider && statusProvider.consent_active,
  ));
}

function indexedLine(count: number | null): string {
  return count === null
    ? "loaded count unavailable"
    : `${count} session${count === 1 ? "" : "s"} loaded`;
}

function detectionLine(p: TruthfulProviderDetection): string {
  if (!p.installed) return "Not found on this machine";
  if (p.provider === "claude_code") {
    const disk = p.signal === CLAUDE_TRANSCRIPT_COUNT_CAPPED
      ? "Transcript folder found · session count exceeds the local scan limit"
      : p.transcript_files === null
      ? "Transcript folder found · session count unavailable"
      : `${p.transcript_files} session${p.transcript_files === 1 ? "" : "s"} on disk`;
    return `${disk}${p.consent_active ? ` · ${indexedLine(p.indexed_sessions)}` : ""}`;
  }
  return `CLI found${p.consent_active ? ` · ${indexedLine(p.indexed_sessions)}` : ""}`;
}

/**
 * First run: detect Codex and Claude Code, ask once, load everything.
 * If neither is found, say so and take a folder from the person.
 */
export function FirstRunPanel({
  transport,
  navigate,
}: {
  transport: FirstRunTransport;
  navigate: (route: AppRoute) => void;
}) {
  const [status, setStatus] = useState<TruthfulOnboardingStatus | null>(null);
  const [hidden, setHidden] = useState<boolean>(() => {
    try { return sessionStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [claudeHome, setClaudeHome] = useState("");
  const acceptControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    acceptControllerRef.current?.abort();
    acceptControllerRef.current = null;
    setBusy(false);
    const controller = new AbortController();
    transport.getOnboardingStatus(controller.signal)
      .then((value) => { if (!controller.signal.aborted && safeOnboardingStatus(value)) setStatus(value); })
      .catch(() => { /* no panel when the runtime lacks onboarding */ });
    return () => controller.abort();
  }, [transport]);

  useEffect(() => () => {
    acceptControllerRef.current?.abort();
    acceptControllerRef.current = null;
  }, []);

  if (hidden || status === null || !status.needs_onboarding) return null;

  const installed = status.providers.filter((p) => p.installed && !p.consent_active).map((p) => p.provider);
  const claude = status.providers.find((provider) => provider.provider === "claude_code");
  const claudeHomeOverrideSupported = status.claude_home_override_supported;
  const canLoad = installed.length > 0
    || (claudeHomeOverrideSupported && claudeHome.trim().length > 0);

  async function loadEverything() {
    setBusy(true);
    setError("");
    let requestController: AbortController | null = null;
    try {
      const providers = [...installed];
      if (claudeHome.trim() && !providers.includes("claude_code")) {
        providers.push("claude_code");
      }
      if (providers.length === 0) {
        setError(claudeHomeOverrideSupported
          ? "Nothing to load yet - install Codex or Claude Code, or point at a Claude Code folder below."
          : "Nothing to load yet - install Codex or Claude Code first.");
        return;
      }
      acceptControllerRef.current?.abort();
      requestController = new AbortController();
      acceptControllerRef.current = requestController;
      const result = await transport.acceptOnboarding({
        providers,
        claude_home: claudeHome.trim() ? claudeHome.trim() : null,
      }, requestController.signal);
      if (requestController.signal.aborted || acceptControllerRef.current !== requestController) return;
      if (!safeOnboardingResult(result, providers)) {
        throw new Error("invalid onboarding response");
      }
      if (result.indexed_sessions === null) {
        setError("Access was granted, but the first index result could not be confirmed. Try loading again.");
        return;
      }
      setStatus(result.status);
      navigate({ name: "sessions" });
    } catch (caught) {
      if (requestController?.signal.aborted
        || (requestController !== null && acceptControllerRef.current !== requestController)) return;
      if (caught instanceof TransportError && caught.reasonCode === "claude_home_invalid") {
        setError("That folder does not look like a Claude Code home (it needs a projects/ directory).");
      } else if (caught instanceof TransportError
        && (caught.reasonCode === "claude_code_not_installed" || caught.reasonCode === "codex_not_installed")) {
        setError("That source is not installed here.");
      } else if (caught instanceof TransportError
        && caught.reasonCode === "claude_home_override_unsupported") {
        setError("Choosing a Claude Code folder is not supported by this runtime.");
      } else if (caught instanceof TransportError && caught.status === 422) {
        setError("The loading request was not accepted. Review the source state and try again.");
      } else {
        setError("The loading result could not be confirmed. Review the source state and try again.");
      }
    } finally {
      if (requestController === null || acceptControllerRef.current === requestController) {
        if (requestController !== null) acceptControllerRef.current = null;
        setBusy(false);
      }
    }
  }

  function dismiss() {
    try { sessionStorage.setItem(DISMISS_KEY, "1"); } catch { /* ignore */ }
    setHidden(true);
  }

  return (
    <section aria-labelledby="first-run-title" className="first-run" role="region">
      <div className="first-run__head">
        <span className="first-run__mark"><Icon name="layers" /></span>
        <div>
          <p className="eyebrow">First run</p>
          <h2 id="first-run-title">
            {status.any_installed ? "Load your projects and sessions" : "We could not find Codex or Claude Code"}
          </h2>
          <p className="first-run__lede">
            {status.any_installed
              ? "Everything stays on this machine. After one yes, Prompt Enhancer loads every project and session it can find and keeps them current automatically."
              : status.claude_home_override_supported
                ? "Did you install them? Codex is detected from the CLI on your PATH; Claude Code from its transcript folder. You can point at a Claude Code folder below."
                : "Did you install them? Codex is detected from the CLI on your PATH; Claude Code from its transcript folder."}
          </p>
        </div>
      </div>

      <ul className="first-run__providers">
        {status.providers.map((p) => (
          <li key={p.provider} className={p.installed ? "is-found" : "is-missing"}>
            <ProviderBadge provider={p.provider} />
            <span>{detectionLine(p)}</span>
            <Icon name={p.installed ? "check" : "x"} />
          </li>
        ))}
      </ul>

      {status.claude_home_override_supported && (!status.any_installed || !claude?.installed) && (
        <label className="first-run__path">
          <span>Claude Code folder (contains <code>projects/</code>)</span>
          <input
            aria-label="Claude Code folder"
            disabled={busy}
            onChange={(event) => setClaudeHome(event.currentTarget.value)}
            placeholder="for example C:\\Users\\you\\.claude"
            type="text"
            value={claudeHome}
          />
        </label>
      )}

      {error !== "" && <p className="first-run__error" role="alert">{error}</p>}

      {!canLoad && (
        <p className="first-run__note">
          {claudeHomeOverrideSupported
            ? "Install Codex or Claude Code, or enter a Claude Code folder above, before loading."
            : "Install Codex or Claude Code before loading."}
        </p>
      )}

      <div className="first-run__actions">
        <button className="button button--primary" disabled={busy || !canLoad} onClick={() => void loadEverything()} type="button">
          {busy ? "Loading…" : "Yes, load everything"}
        </button>
        <button className="button button--ghost" disabled={busy} onClick={dismiss} type="button">Not now</button>
      </div>
      <p className="first-run__note">
        This grants local-history access for the sources above. Nothing is sent anywhere; you can revoke it on the Data sources page at any time.
      </p>
    </section>
  );
}
