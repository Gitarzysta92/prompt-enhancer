import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CodexSession, JudgeAgreementReport, LocalModelsOverview, PromptCheckHistory } from "../../shared/api/contracts";
import { OverviewPage, sessionsPerDay } from "./OverviewPage";

const NOW = new Date("2026-08-19T12:00:00Z");

function session(startedAt: string, provider = "codex"): CodexSession {
  return {
    session_id: "a".repeat(64), installation_id: "b".repeat(64), project_id: "c".repeat(64), provider,
    provider_version: "1", adapter_version: "1", source_schema_version: "1", started_at: startedAt, ended_at: null,
    terminal_state: "unknown", events_complete: false, project_display_name: "Example", session_display_name: "Example session",
    project_display_name_origin: "provider", session_display_name_origin: "provider", project_manual_label_revision: 0, session_manual_label_revision: 0,
  } as unknown as CodexSession;
}

function overviewTransport(indexedSessions: [number | null, number | null]) {
  return {
    getOnboardingStatus: vi.fn(async () => ({
      contract_version: "onboarding.v1" as const,
      any_installed: true,
      needs_onboarding: false,
      refresh_interval_seconds: 600,
      last_refresh_at: "2026-08-19T11:00:00Z",
      last_refresh_error: false,
      claude_home_override_supported: true,
      providers: [
        { provider: "codex" as const, installed: true, signal: "codex_cli_on_path" as const, consent_active: true, indexed_sessions: indexedSessions[0], transcript_files: null },
        { provider: "claude_code" as const, installed: true, signal: "claude_transcript_root" as const, consent_active: true, indexed_sessions: indexedSessions[1], transcript_files: 0 },
      ],
    })),
    listCodexSessions: vi.fn(async () => ({ limit: 100, offset: 0, sessions: [] })),
    getCalibrationSample: vi.fn(async () => ({ contract_version: "calibration.v1", frozen_at: "2026-08-19T00:00:00Z", metric_keys: [], members: [] }) as never),
    getModelJudgeAgreement: vi.fn(async () => ({ contract_version: "model-judge.v1" as const, model_alias: "synthetic-local", judged_sessions: 0, metrics: [], caveat: "synthetic" }) as never),
    getLocalModels: vi.fn(async () => ({ contract_version: "local-models.v1" as const, runtime_available: false, storage_root: "D:/synthetic", storage_free_bytes: 64 * 1024 ** 3, download_reserve_bytes: 512 * 1024 ** 2, download_ledger_error_code: null, downloads: [], hardware: { gpu_name: null, gpu_memory_mb: null, gpu_memory_free_mb: null, ram_mb: 8192, llama_server_path: null, llama_server_version: null }, models: [] })),
    getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, limit: 60, offset: 0, checks: [] })),
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

describe("OverviewPage", () => {
  it("buckets sessions per day with today on the right", () => {
    const counts = sessionsPerDay([session("2026-08-19T08:00:00Z"), session("2026-08-19T09:00:00Z"), session("2026-08-18T10:00:00Z"), session("2026-06-01T00:00:00Z")], 30, NOW);
    expect(counts.length).toBe(30);
    expect(counts[29]).toBe(2);
    expect(counts[28]).toBe(1);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(3);
  });

  it("does not sum an unavailable provider count as zero", async () => {
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={overviewTransport([null, 0])} />);
    const tile = screen.getByText("Sessions indexed").closest("button") as HTMLButtonElement;
    expect(await within(tile).findByText("Unknown")).toBeInTheDocument();
    expect(within(tile).getByText("Codex count unavailable · Claude Code 0")).toBeInTheDocument();
    expect(within(tile).queryByText(/^0$/)).toBeNull();
  });

  it("keeps the source detail unknown while onboarding is still loading", () => {
    const transport = overviewTransport([0, 0]);
    transport.getOnboardingStatus = vi.fn(() => new Promise<never>(() => undefined));
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={transport} />);
    const tile = screen.getByText("Sessions indexed").closest("button") as HTMLButtonElement;
    expect(within(tile).getByText("checking source counts…")).toBeInTheDocument();
    expect(within(tile).queryByText("no source loaded yet")).toBeNull();
  });

  it("does not turn pending or failed model and commentary requests into zero-valued facts", async () => {
    const models = deferred<LocalModelsOverview>();
    const checks = deferred<PromptCheckHistory>();
    const transport = {
      ...overviewTransport([0, 0]),
      getLocalModels: vi.fn(() => models.promise),
      getPromptCheckHistory: vi.fn(() => checks.promise),
    };
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={transport} />);

    const modelTile = screen.getByText("Local model").closest("button") as HTMLButtonElement;
    const checkTile = screen.getByText("Prompt checks").closest("button") as HTMLButtonElement;
    expect(within(modelTile).getByText("checking hardware…")).toBeInTheDocument();
    expect(within(modelTile).queryByText("no GPU detected")).toBeNull();
    expect(within(checkTile).getByText("checking prompt history…")).toBeInTheDocument();
    expect(within(checkTile).queryByText("no check yet")).toBeNull();
    expect(within(checkTile).getByText("counting model commentary…")).toBeInTheDocument();
    expect(within(checkTile).queryByText("0 with model commentary")).toBeNull();

    await act(async () => {
      models.reject(new Error("synthetic model lookup failure"));
      checks.reject(new Error("synthetic history lookup failure"));
      await Promise.allSettled([models.promise, checks.promise]);
    });
    expect(within(modelTile).getByText("hardware unavailable")).toBeInTheDocument();
    expect(within(checkTile).getByText("prompt history unavailable")).toBeInTheDocument();
    expect(within(checkTile).queryByText("no check yet")).toBeNull();
    expect(within(checkTile).getByText("commentary history unavailable")).toBeInTheDocument();
  });

  it("reserves no-GPU and zero-commentary copy for verified ready responses", async () => {
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={overviewTransport([0, 0])} />);
    const modelTile = screen.getByText("Local model").closest("button") as HTMLButtonElement;
    const checkTile = screen.getByText("Prompt checks").closest("button") as HTMLButtonElement;
    expect(await within(modelTile).findByText("no GPU detected")).toBeInTheDocument();
    expect(await within(checkTile).findByText("no check yet")).toBeInTheDocument();
    expect(await within(checkTile).findByText("0 with model commentary")).toBeInTheDocument();
  });

  it("distinguishes a pending judge lane from an unavailable one", async () => {
    const judge = deferred<JudgeAgreementReport>();
    const transport = {
      ...overviewTransport([0, 0]),
      getModelJudgeAgreement: vi.fn(() => judge.promise),
    };
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={transport} />);

    const tile = screen.getByText("Calibration").closest("button") as HTMLButtonElement;
    expect(within(tile).getByText("checking judge lane…")).toBeInTheDocument();
    expect(within(tile).queryByText("judge lane unavailable")).toBeNull();

    await act(async () => {
      judge.reject(new Error("synthetic judge interruption"));
      await judge.promise.catch(() => undefined);
    });
    expect(within(tile).getByText("judge lane unavailable")).toBeInTheDocument();
    expect(within(tile).queryByText("checking judge lane…")).toBeNull();
  });

  it("renders an exact zero when every provider count is known zero", async () => {
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={overviewTransport([0, 0])} />);
    const tile = screen.getByText("Sessions indexed").closest("button") as HTMLButtonElement;
    expect(await within(tile).findByText("0")).toBeInTheDocument();
    expect(within(tile).getByText("Codex 0 · Claude Code 0")).toBeInTheDocument();
  });

  it("keeps an unsafe aggregate unknown even when each provider count is safe", async () => {
    render(<OverviewPage
      navigate={vi.fn()}
      now={() => NOW}
      transport={overviewTransport([Number.MAX_SAFE_INTEGER, 2])}
    />);
    const tile = screen.getByText("Sessions indexed").closest("button") as HTMLButtonElement;
    expect(await within(tile).findByText("Unknown")).toBeInTheDocument();
    expect(within(tile).queryByText("9007199254740992")).toBeNull();
  });

  it("makes contradictory onboarding metadata unavailable instead of rendering it", async () => {
    const transport = overviewTransport([0, 0]);
    transport.getOnboardingStatus = vi.fn(async () => ({
      ...(await overviewTransport([0, 0]).getOnboardingStatus()),
      any_installed: false,
    }));
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={transport} />);
    const tile = screen.getByText("Sessions indexed").closest("button") as HTMLButtonElement;
    expect(await within(tile).findByText("—")).toBeInTheDocument();
    expect(within(tile).getByText("source counts unavailable")).toBeInTheDocument();
    expect(within(tile).queryByText("no source loaded yet")).toBeNull();
    expect(within(tile).queryByText(/^0$/)).toBeNull();
  });

  it("shows the four tiles from the app's own endpoints and suggests what to do next", async () => {
    const navigate = vi.fn();
    const transport = {
      getOnboardingStatus: vi.fn(async () => ({
        contract_version: "onboarding.v1" as const, any_installed: true, needs_onboarding: true, refresh_interval_seconds: 600,
        last_refresh_at: "2026-08-19T11:00:00Z", last_refresh_error: false, claude_home_override_supported: true,
        providers: [
          { provider: "codex" as const, installed: true, signal: "codex_cli_on_path" as const, consent_active: true, indexed_sessions: 62, transcript_files: null },
          { provider: "claude_code" as const, installed: true, signal: "claude_transcript_root" as const, consent_active: false, indexed_sessions: 0, transcript_files: 200 },
        ],
      })),
      listCodexSessions: vi.fn(async () => ({ limit: 100, offset: 0, sessions: [session("2026-08-19T08:00:00Z"), session("2026-08-17T08:00:00Z", "claude_code")] })),
      getCalibrationSample: vi.fn(async () => ({ contract_version: "calibration.v1", frozen_at: "2026-08-19T00:00:00Z", metric_keys: ["a", "b", "c"], members: [{ session_id: "d".repeat(64), project_id: "c".repeat(64), provider: "codex", project_display_name: null, session_display_name: null, started_at: "2026-08-01T00:00:00Z", rated_metric_keys: ["a", "b", "c"] }, { session_id: "e".repeat(64), project_id: "c".repeat(64), provider: "codex", project_display_name: null, session_display_name: null, started_at: "2026-08-02T00:00:00Z", rated_metric_keys: [] }] }) as never),
      getModelJudgeAgreement: vi.fn(async () => ({ contract_version: "model-judge.v1" as const, model_alias: "orca27b-iq3m", judged_sessions: 62, metrics: [{ metric_key: "a", pairs: 1, agreement_rate: 1, cohen_kappa: null, state: "insufficient_data", reason: null }], caveat: "c" }) as never),
      getLocalModels: vi.fn(async () => ({ contract_version: "local-models.v1" as const, runtime_available: true, storage_root: "D:/synthetic", storage_free_bytes: 64 * 1024 ** 3, download_reserve_bytes: 512 * 1024 ** 2, download_ledger_error_code: null, downloads: [], hardware: { gpu_name: "Example GPU", gpu_memory_mb: 16384, gpu_memory_free_mb: 4096, ram_mb: 32768, llama_server_path: "synthetic-runtime", llama_server_version: "synthetic-v1" }, models: [] })),
      getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, limit: 60, offset: 0, checks: [] })),
    };
    render(<OverviewPage navigate={navigate} now={() => NOW} runtimeMode="local_real" transport={transport} />);
    await screen.findByText("62");
    expect(screen.getByText(/Codex 62/)).toBeTruthy();
    expect(screen.getByText("1/2")).toBeTruthy();
    expect(screen.getByText(/orca27b-iq3m judged 62 sessions/)).toBeTruthy();
    expect(screen.getByText("none active")).toBeTruthy();
    expect(screen.getByText("Example GPU · 4.0 GB VRAM free")).toBeTruthy();
    expect(screen.getByText(/not loaded yet/)).toBeTruthy();
    expect(screen.getByText(/No local model is active/)).toBeTruthy();
    expect(screen.getByText(/Rate sessions blind/)).toBeTruthy();
    expect(screen.getByRole("img", { name: /Sessions per day/ })).toBeTruthy();
    fireEvent.click(screen.getByText(/No local model is active/));
    expect(navigate).toHaveBeenCalledWith({ name: "models" });
    fireEvent.click(screen.getByText("Prompt checks").closest("button") as HTMLButtonElement);
    expect(navigate).toHaveBeenCalledWith({ name: "prompt_checks" });
  });

  it("labels a capped history as partial instead of claiming a complete 30-day total", async () => {
    const listCodexSessions = vi.fn(async (limit: number, offset: number) => ({ limit, offset, sessions: Array.from({ length: 100 }, (_, index) => ({ ...session("2026-08-19T08:00:00Z"), session_id: (offset + index).toString(16).padStart(64, "0") })) }));
    render(<OverviewPage navigate={vi.fn()} now={() => NOW} transport={{ ...overviewTransport([700, 0]), listCodexSessions }} />);
    expect(await screen.findByText("At least 500 in the last 30 days · first 500 sessions only")).toBeVisible();
    expect(listCodexSessions).toHaveBeenCalledTimes(5);
    expect(screen.getByRole("img", { name: /Sessions per day.*partial history/ })).toBeVisible();
  });

  it("does not offer unavailable local-source navigation in synthetic mode", async () => {
    const base = overviewTransport([0, 0]);
    const getOnboardingStatus = vi.fn(async () => ({ ...await base.getOnboardingStatus(), providers: [{ provider: "codex" as const, installed: true, signal: "codex_cli_on_path" as const, consent_active: false, indexed_sessions: 0, transcript_files: null }] }));
    render(<OverviewPage navigate={vi.fn()} runtimeMode="synthetic_demo" transport={{ ...base, getOnboardingStatus }} />);
    await screen.findByText(/No local model is active/);
    expect(screen.queryByText(/A detected tool is not loaded yet/)).not.toBeInTheDocument();
  });

  it("does not describe missing capability checks as everything being up to date", async () => {
    const failed = vi.fn().mockRejectedValue(new Error("example-unavailable"));
    render(<OverviewPage navigate={vi.fn()} transport={{ getOnboardingStatus: failed, listCodexSessions: failed, getCalibrationSample: failed, getModelJudgeAgreement: failed, getLocalModels: failed, getPromptCheckHistory: failed }} />);
    expect(await screen.findByText(/Some checks are unavailable/)).toBeVisible();
    expect(screen.queryByText(/Nothing is waiting on you/)).not.toBeInTheDocument();
  });
});
