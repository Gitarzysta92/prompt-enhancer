import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApplicationUpdateStatus, PromptEnhancerTransport } from "../shared/api/contracts";
import { ApplicationUpdateControl } from "./ApplicationUpdateControl";

const UNCONFIGURED: ApplicationUpdateStatus = {
  contract_version: "application-update-status.v3",
  instance_id: "a".repeat(32),
  revision: 0,
  contains_private_data: false,
  installed_version: "1.2.3",
  channel: "stable",
  state: "unconfigured",
  available_version: null,
  artifact_size_bytes: null,
  downloaded_bytes: null,
  last_checked_at: null,
  reason_code: "release_feed_unconfigured",
  verification_code: null,
  can_check: false,
  can_stage: false,
  can_cancel: false,
  can_retry: false,
  can_apply: false,
  can_verify: false,
  package_review: { state: "not_configured", reason_code: null, checked_at: null },
};

const CURRENT: ApplicationUpdateStatus = {
  ...UNCONFIGURED,
  state: "current",
  reason_code: null,
  last_checked_at: "2040-01-02T03:04:05Z",
  can_check: true,
  revision: 1,
  package_review: { state: "not_staged", reason_code: null, checked_at: null },
};

function transport(status: ApplicationUpdateStatus) {
  return {
    getApplicationUpdateStatus: vi.fn(async () => status),
    checkApplicationUpdate: vi.fn(async () => status),
    stageApplicationUpdate: vi.fn(async () => status),
    cancelApplicationUpdate: vi.fn(async () => status),
    retryApplicationUpdate: vi.fn(async () => status),
    verifyApplicationUpdate: vi.fn(async () => status),
  } satisfies Pick<PromptEnhancerTransport, "getApplicationUpdateStatus" | "checkApplicationUpdate" | "stageApplicationUpdate" | "cancelApplicationUpdate" | "retryApplicationUpdate" | "verifyApplicationUpdate">;
}

describe("ApplicationUpdateControl", () => {
  it("shows a truthful disabled state when no signed release channel is connected", async () => {
    const api = transport(UNCONFIGURED);
    render(<ApplicationUpdateControl transport={api} variant="sidebar" />);

    const button = await screen.findByRole("button", { name: /updates not connected/i });
    expect(button).toBeEnabled();
    expect(within(button).getByText(/version 1\.2\.3 · stable/i)).toBeVisible();
    expect(api.checkApplicationUpdate).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(screen.getByText(/updates are not connected/i)).toBeVisible();
  });

  it("checks only after an enabled owner action and exposes pending state", async () => {
    let finish!: (value: ApplicationUpdateStatus) => void;
    const pending = new Promise<ApplicationUpdateStatus>((resolve) => { finish = resolve; });
    const api = transport(CURRENT);
    api.checkApplicationUpdate.mockReturnValueOnce(pending);
    render(<ApplicationUpdateControl transport={api} variant="sidebar" />);
    const button = await screen.findByRole("button", { name: /software is current/i });
    fireEvent.click(button);
    const check = screen.getByRole("button", { name: /check for updates/i });

    fireEvent.click(check);

    expect(api.checkApplicationUpdate).toHaveBeenCalledOnce();
    const pendingButton = screen.getByRole("button", { name: /checking for updates/i });
    expect(pendingButton).toBeDisabled();
    expect(within(pendingButton).getByText("Requested release check/download; no automatic installation")).toBeVisible();
    finish(CURRENT);
    await waitFor(() => expect(screen.getByRole("button", { name: /software is current/i })).toBeEnabled());
  });

  it("renders bounded release facts without exposing a URL or path", async () => {
    const available: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "available",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 0,
      can_stage: true,
    };
    render(<ApplicationUpdateControl transport={transport(available)} variant="drawer" />);

    const button = await screen.findByRole("button", { name: /version 2\.0\.0 available/i });
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /download version 2\.0\.0/i })).toBeEnabled();
    expect(within(button).getByText(/25 MiB · download available/i)).toBeVisible();
    expect(document.body.textContent).not.toMatch(/https?:|[A-Z]:\\/u);
  });

  it("fails closed with fixed copy when the local status cannot be read", async () => {
    const api = transport(CURRENT);
    api.getApplicationUpdateStatus.mockRejectedValueOnce(new Error("synthetic private-shaped failure"));
    render(<ApplicationUpdateControl transport={api} variant="sidebar" />);

    expect(await screen.findByRole("button", { name: /retry update status/i })).toBeEnabled();
    expect(document.body).not.toHaveTextContent("synthetic private-shaped failure");
  });

  it("sends the v2 revision and instance fence for explicit staging", async () => {
    const available: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "available",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 0,
      can_stage: true,
    };
    const api = transport(available);
    render(<ApplicationUpdateControl transport={api} variant="sidebar" />);
    fireEvent.click(await screen.findByRole("button", { name: /version 2\.0\.0 available/i }));
    fireEvent.click(screen.getByRole("button", { name: /download version 2\.0\.0/i }));
    await waitFor(() => expect(api.stageApplicationUpdate).toHaveBeenCalledWith(
      { expected_revision: 1, expected_instance_id: "a".repeat(32) },
      expect.any(AbortSignal),
    ));
  });

  it("hides a server-advertised action when the transport cannot perform it", async () => {
    const available: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "available",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 0,
      can_stage: true,
    };
    const api = transport(available);
    Reflect.deleteProperty(api, "stageApplicationUpdate");
    render(<ApplicationUpdateControl transport={api} variant="sidebar" />);
    fireEvent.click(await screen.findByRole("button", { name: /version 2\.0\.0 available/i }));
    expect(screen.queryByRole("button", { name: /download version 2\.0\.0/i })).not.toBeInTheDocument();
  });

  it("keeps staged bytes distinct from publisher verification and apply", async () => {
    const staged: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staged",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 25 * 1024 ** 2,
      can_check: true,
      can_verify: true,
      package_review: { state: "not_checked", reason_code: null, checked_at: null },
    };
    render(<ApplicationUpdateControl transport={transport(staged)} variant="drawer" />);
    fireEvent.click(await screen.findByRole("button", { name: /version 2\.0\.0 downloaded/i }));
    const summary = screen.getByRole("button", { name: /version 2\.0\.0 downloaded/i });
    expect(within(summary).getByText(/publisher verification has not been run/i)).toBeVisible();
    expect(within(summary).queryByText(/publisher verification (?:is )?not connected/i)).not.toBeInTheDocument();
    expect(screen.getByText(
      "Downloaded bytes match the signed manifest. Installation handoff is not connected.",
    )).toBeVisible();
    expect(screen.getByText("Publisher verification has not been run.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Verify downloaded package" })).toBeEnabled();
    expect(within(screen.getByLabelText("Update actions")).queryByRole("button", { name: /apply|install/i })).not.toBeInTheDocument();
  });

  it("verifies only after the explicit review action and never exposes install", async () => {
    const staged: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staged",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 25 * 1024 ** 2,
      can_check: true,
      can_verify: true,
      package_review: { state: "not_checked", reason_code: null, checked_at: null },
    };
    const reviewed = { ...staged, revision: 2, can_verify: true, package_review: { state: "verified" as const, reason_code: null, checked_at: "2040-01-02T03:04:05Z" } };
    const api = transport(staged);
    api.verifyApplicationUpdate.mockResolvedValueOnce(reviewed);
    render(<ApplicationUpdateControl transport={api} variant="drawer" />);
    fireEvent.click(await screen.findByRole("button", { name: /version 2\.0\.0 downloaded/i }));
    expect(api.verifyApplicationUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Verify downloaded package" }));
    await waitFor(() => expect(api.verifyApplicationUpdate).toHaveBeenCalledWith(
      { expected_revision: 1, expected_instance_id: "a".repeat(32) },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(screen.getByRole("button", { name: /version 2\.0\.0 reviewed/i })).toBeVisible());
    expect(screen.getByText(/installation remains disabled/i)).toBeVisible();
    expect(within(screen.getByLabelText("Update actions")).queryByRole("button", { name: /apply|install/i })).not.toBeInTheDocument();
  });

  it("does not claim the current bytes match after package review rejection", async () => {
    const rejected: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staged",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 25 * 1024 ** 2,
      can_check: true,
      can_verify: true,
      package_review: { state: "rejected", reason_code: "package_changed", checked_at: "2040-01-02T03:04:05Z" },
    };
    render(<ApplicationUpdateControl transport={transport(rejected)} variant="drawer" />);
    const summary = await screen.findByRole("button", { name: /version 2\.0\.0 needs review/i });
    fireEvent.click(summary);
    expect(screen.getByText(/downloaded release did not pass package review/i)).toBeVisible();
    expect(screen.queryByText(/downloaded bytes match the signed manifest/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/package checks passed/i)).not.toBeInTheDocument();
  });

  it("ignores a review response from an older revision or coordinator instance", async () => {
    const staged: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staged",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 25 * 1024 ** 2,
      can_check: true,
      can_verify: true,
      package_review: { state: "not_checked", reason_code: null, checked_at: null },
    };
    const api = transport(staged);
    api.verifyApplicationUpdate.mockResolvedValueOnce({
      ...staged,
      revision: 0,
      instance_id: "b".repeat(32),
      can_verify: true,
      package_review: { state: "verified", reason_code: null, checked_at: "2040-01-02T03:04:05Z" },
    });
    render(<ApplicationUpdateControl transport={api} variant="drawer" />);
    fireEvent.click(await screen.findByRole("button", { name: /version 2\.0\.0 downloaded/i }));
    fireEvent.click(screen.getByRole("button", { name: "Verify downloaded package" }));
    await waitFor(() => expect(api.verifyApplicationUpdate).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("button", { name: /retry update status/i })).toBeEnabled());
    expect(screen.queryByRole("button", { name: /version 2\.0\.0 reviewed/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry update status/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /version 2\.0\.0 downloaded/i })).toBeVisible());
  });

  it("fails closed on a stale verifying poll and recovers only after an explicit status retry", async () => {
    const verifying: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "verifying",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 25 * 1024 ** 2,
      can_check: false,
      package_review: { state: "checking", reason_code: null, checked_at: null },
    };
    const stale = { ...verifying, revision: 0, instance_id: "b".repeat(32) };
    const recovered: ApplicationUpdateStatus = {
      ...verifying,
      state: "staged",
      revision: 3,
      can_check: true,
      can_verify: true,
      package_review: { state: "not_checked", reason_code: null, checked_at: null },
    };
    const api = transport(verifying);
    api.getApplicationUpdateStatus.mockResolvedValueOnce(verifying).mockResolvedValueOnce(stale).mockResolvedValueOnce(recovered);
    render(<ApplicationUpdateControl transport={api} variant="drawer" />);
    await screen.findByRole("button", { name: /verifying downloaded package/i });
    await waitFor(() => expect(screen.getByRole("button", { name: /retry update status/i })).toBeEnabled(), { timeout: 2_000 });
    fireEvent.click(screen.getByRole("button", { name: /retry update status/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /version 2\.0\.0 downloaded/i })).toBeVisible());
    expect(api.getApplicationUpdateStatus).toHaveBeenCalledTimes(3);
  });

  it("restarts local progress polling when cancellation returns to staging", async () => {
    const staging: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staging",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 10,
      can_check: false,
      can_stage: false,
      can_cancel: true,
    };
    const failed: ApplicationUpdateStatus = {
      ...staging,
      state: "failed",
      downloaded_bytes: null,
      reason_code: "artifact_download_failed",
      can_cancel: false,
      can_retry: true,
    };
    const cleanupPending = { ...staging, can_cancel: false };
    const api = transport(staging);
    api.getApplicationUpdateStatus
      .mockResolvedValueOnce(staging)
      .mockResolvedValueOnce(failed);
    api.cancelApplicationUpdate.mockResolvedValueOnce(cleanupPending);
    render(<ApplicationUpdateControl transport={api} variant="sidebar" />);
    fireEvent.click(await screen.findByRole("button", { name: /downloading version 2\.0\.0/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel download/i }));
    await waitFor(() => expect(api.cancelApplicationUpdate).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("button", { name: /update download needs attention/i })).toBeInTheDocument());
    expect(api.getApplicationUpdateStatus).toHaveBeenCalledTimes(2);
  });

  it("labels cleanup uncertainty as review-only and keeps update actions blocked", async () => {
    const cleanupUncertain: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "failed",
      reason_code: "staging_cleanup_unconfirmed",
      can_check: false,
      can_retry: false,
    };
    render(<ApplicationUpdateControl transport={transport(cleanupUncertain)} variant="drawer" />);
    const summary = await screen.findByRole("button", { name: /update cleanup needs review/i });
    fireEvent.click(summary);
    expect(within(summary).getByText(/cleanup could not be confirmed · actions remain blocked/i)).toBeVisible();
    expect(screen.getByLabelText("Update actions")).toBeEmptyDOMElement();
  });

  it("classifies artifact verification failure as a download concern", async () => {
    const failed: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "failed",
      reason_code: "artifact_verification_failed",
      can_check: false,
      can_retry: true,
    };
    render(<ApplicationUpdateControl transport={transport(failed)} variant="drawer" />);
    const summary = await screen.findByRole("button", { name: /update download needs attention/i });
    expect(within(summary).getByText(/retry the local download/i)).toBeVisible();
  });

  it("offers a fresh signed-release check without implying a retry when download recovery is unavailable", async () => {
    const failed: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "failed",
      reason_code: "artifact_verification_failed",
      can_check: true,
      can_retry: false,
    };
    render(<ApplicationUpdateControl transport={transport(failed)} variant="drawer" />);
    const summary = await screen.findByRole("button", { name: /update download needs attention/i });
    expect(within(summary).getByText(/fresh signed-release check is available/i)).toBeVisible();
    expect(within(summary).queryByText(/retry/i)).not.toBeInTheDocument();
  });

  it("blocks failed metadata recovery when neither check nor retry is available", async () => {
    const failed: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "failed",
      reason_code: "release_feed_unavailable",
      can_check: false,
      can_retry: false,
    };
    render(<ApplicationUpdateControl transport={transport(failed)} variant="drawer" />);
    const summary = await screen.findByRole("button", { name: /update check needs review/i });
    expect(within(summary).getByText(/recovery needs review · actions remain blocked/i)).toBeVisible();
    expect(within(summary).queryByText(/retry/i)).not.toBeInTheDocument();
  });

  it("labels a cancellation-pending staging state as stopping the download", async () => {
    const stopping: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staging",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 10 * 1024 ** 2,
      can_check: false,
      can_cancel: false,
    };
    render(<ApplicationUpdateControl transport={transport(stopping)} variant="drawer" />);
    expect(await screen.findByRole("button", { name: /stopping download for version 2\.0\.0/i })).toBeVisible();
  });

  it("does not let a replacement transport inherit an old staging snapshot", async () => {
    const oldStaging: ApplicationUpdateStatus = {
      ...CURRENT,
      state: "staging",
      available_version: "2.0.0",
      artifact_size_bytes: 25 * 1024 ** 2,
      downloaded_bytes: 10,
      can_check: false,
      can_cancel: true,
    };
    const nextStaging = { ...oldStaging, revision: 2, downloaded_bytes: 20 * 1024 ** 2 };
    const first = transport(oldStaging);
    const second = transport(nextStaging);
    const view = render(<ApplicationUpdateControl transport={first} variant="drawer" />);
    await screen.findByRole("button", { name: /downloading version 2\.0\.0/i });
    view.rerender(<ApplicationUpdateControl transport={second} variant="drawer" />);
    await waitFor(() => expect(second.getApplicationUpdateStatus).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("button", { name: /20 MiB of 25 MiB/i })).toBeVisible());
  });
});
