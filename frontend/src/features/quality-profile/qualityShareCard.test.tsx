import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_SESSION_QUALITY_RUN,
} from "../../shared/api/syntheticFixtures";
import { ProfileShareDialog } from "./ProfileShareDialog";
import { createQualityMetricProfile } from "./qualityProfile";
import {
  browserShareCardRuntime,
  createSafeShareSnapshot,
  drawSafeShareCard,
  type ShareCardAsset,
  type ShareCardRuntime,
} from "./qualityShareCard";

const canary = "PRIVATE-PROJECT-SESSION-PATH-CANARY";

function profileFixture() {
  const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
  detail.results.forEach((result) => {
    result.display_name = canary;
    result.description = canary;
  });
  const modeled = detail.results.find(
    (result) => result.key === "logic.requirement_action_traceability",
  )!;
  modeled.model_id = canary;
  modeled.model_revision = canary;
  modeled.model_license = canary;
  modeled.tokenizer_id = canary;
  return createQualityMetricProfile(
    "prompt-quality",
    detail,
    SYNTHETIC_QUALITY_SESSION_ID,
  )!;
}

function recordingContext() {
  const calls: string[] = [];
  const context = {
    fillStyle: "",
    font: "",
    lineCap: "butt" as CanvasLineCap,
    lineJoin: "miter" as CanvasLineJoin,
    lineWidth: 1,
    strokeStyle: "",
    textAlign: "left" as CanvasTextAlign,
    textBaseline: "alphabetic" as CanvasTextBaseline,
    arc: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn((text: string) => calls.push(text)),
    lineTo: vi.fn(),
    measureText: vi.fn(() => ({ width: 1 } as TextMetrics)),
    moveTo: vi.fn(),
    roundRect: vi.fn(),
    stroke: vi.fn(),
  };
  return { calls, context };
}

function runtimeFixture() {
  const asset: ShareCardAsset = {
    blob: new Blob(["safe-png-bytes"], { type: "image/png" }),
    previewUrl: "blob:http://example.invalid/safe-derived-preview",
    filename: "prompt-enhancer-prompt-profile.png",
  };
  const runtime: ShareCardRuntime = {
    render: vi.fn(async () => asset),
    revoke: vi.fn(),
    download: vi.fn(),
    canCopy: () => true,
    copy: vi.fn(async () => undefined),
    canShare: () => true,
    share: vi.fn(async () => undefined),
  };
  return { asset, runtime };
}

describe("privacy-safe quality share card", () => {
  it("fails closed when share capabilities throw", async () => {
    const { runtime } = runtimeFixture();
    runtime.canCopy = vi.fn(() => {
      throw new Error("PRIVATE-CAPABILITY-CANARY");
    });
    runtime.canShare = vi.fn(() => {
      throw new Error("PRIVATE-CAPABILITY-CANARY");
    });

    render(
      <div className="app-shell">
        <ProfileShareDialog
          onClose={vi.fn()}
          profile={profileFixture()}
          runtime={runtime}
          snapshotKind="latest"
        />
      </div>,
    );

    await screen.findByAltText(/minimized local prompt/i);
    expect(screen.getByRole("button", { name: "Copy image" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Share/ })).toBeDisabled();
    expect(document.body).not.toHaveTextContent("PRIVATE-CAPABILITY-CANARY");
  });

  it("blocks detached share actions after the dialog closes", async () => {
    const { runtime } = runtimeFixture();
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <div className="app-shell">
          {open && (
            <ProfileShareDialog
              onClose={() => setOpen(false)}
              profile={profileFixture()}
              runtime={runtime}
              snapshotKind="latest"
            />
          )}
        </div>
      );
    }
    render(<Harness />);
    const previewImage = await screen.findByAltText(/minimized local prompt/i);
    expect(previewImage).toBeVisible();
    const detachedCopy = screen.getByRole("button", { name: "Copy image" });
    const detachedDownload = screen.getByRole("button", { name: "Download PNG" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(detachedCopy);
    fireEvent.click(detachedDownload);

    expect(runtime.copy).not.toHaveBeenCalled();
    expect(runtime.download).not.toHaveBeenCalled();
  });

  it("fails closed when the share runtime swaps during an open preview", async () => {
    const first = runtimeFixture();
    const second = runtimeFixture();
    const onClose = vi.fn();
    const profile = profileFixture();
    const { rerender } = render(
      <div className="app-shell">
        <ProfileShareDialog
          onClose={onClose}
          profile={profile}
          runtime={first.runtime}
          snapshotKind="latest"
        />
      </div>,
    );
    await screen.findByAltText(/minimized local prompt metric/i);
    const detachedDownload = screen.getByRole("button", { name: "Download PNG" });

    rerender(
      <div className="app-shell">
        <ProfileShareDialog
          onClose={onClose}
          profile={profile}
          runtime={second.runtime}
          snapshotKind="latest"
        />
      </div>,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(first.runtime.revoke).toHaveBeenCalledWith(first.asset);
    expect(second.runtime.render).not.toHaveBeenCalled();
    fireEvent.click(detachedDownload);
    expect(first.runtime.download).not.toHaveBeenCalled();
    expect(second.runtime.download).not.toHaveBeenCalled();
  });

  it("does not publish a delayed share completion after close", async () => {
    let resolveCopy!: () => void;
    const { runtime } = runtimeFixture();
    runtime.copy = vi.fn(() => new Promise<void>((resolve) => {
      resolveCopy = resolve;
    }));
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <div className="app-shell">
          {open && (
            <ProfileShareDialog
              onClose={() => setOpen(false)}
              profile={profileFixture()}
              runtime={runtime}
              snapshotKind="latest"
            />
          )}
        </div>
      );
    }
    render(<Harness />);
    await screen.findByAltText(/minimized local prompt metric/i);
    fireEvent.click(screen.getByRole("button", { name: "Copy image" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    resolveCopy();
    await Promise.resolve();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText(/PNG copied/i)).not.toBeInTheDocument();
    expect(runtime.copy).toHaveBeenCalledTimes(1);
  });

  it("uses only allowlisted derived fields and keeps fraction separate from evidence coverage", () => {
    const profile = profileFixture();
    profile.latest.scope = {
      selectedSessions: 4,
      completedRuns: 3,
      missingRuns: 1,
    };
    const snapshot = createSafeShareSnapshot(profile, "latest");
    const { calls, context } = recordingContext();
    drawSafeShareCard(
      context as unknown as Parameters<typeof drawSafeShareCard>[0],
      snapshot,
    );

    expect(JSON.stringify(snapshot)).not.toContain(canary);
    expect(calls.join(" ")).not.toContain(canary);
    expect(calls).toContain("100%");
    expect(calls).toContain("Partial · 3/3 metric · 8/10 coverage");
    expect(calls).toContain("Review load · lower is better");
    expect(calls).toContain("Scope: 4 selected · 3 completed · 1 missing");
    expect(snapshot.metrics[0]).toMatchObject({
      fractionNumerator: 3,
      fractionDenominator: 3,
      observed: 8,
      eligible: 10,
    });
    expect(snapshot).not.toHaveProperty("projectId");
    expect(snapshot).not.toHaveProperty("sessionId");
    expect(snapshot).not.toHaveProperty("evidence");

    const { asset } = runtimeFixture();
    expect(asset.blob.type).toBe("image/png");
    expect(asset.filename).toBe("prompt-enhancer-prompt-profile.png");
    expect(asset.filename).not.toContain(canary);
  });

  it("exports scope omissions as provenance and never as a measured value", () => {
    const exactSubset = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
    const selectedKey = "prompt.goal_definition";
    exactSubset.results = exactSubset.results.filter(
      (result) => result.key === selectedKey,
    );
    exactSubset.run.selected_metric_keys = [selectedKey];
    const exactProfile = createQualityMetricProfile(
      "prompt-quality",
      exactSubset,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const exactSnapshot = createSafeShareSnapshot(exactProfile, "latest");
    const omitted = exactSnapshot.metrics.find(
      (metric) => metric.label === "Expected constraint cues",
    )!;
    expect(omitted).toMatchObject({
      state: "not-selected",
      ratio: null,
      fractionNumerator: null,
      fractionDenominator: null,
      notSelectedRuns: 1,
      unknownScopeRuns: 0,
    });

    const mixedProfile = profileFixture();
    mixedProfile.latest.metrics[0].notSelectedRuns = 1;
    const mixedSnapshot = createSafeShareSnapshot(mixedProfile, "latest");
    const { calls, context } = recordingContext();
    drawSafeShareCard(
      context as unknown as Parameters<typeof drawSafeShareCard>[0],
      mixedSnapshot,
    );
    expect(mixedSnapshot.metrics[0]).toMatchObject({
      state: "partial",
      ratio: 1,
      notSelectedRuns: 1,
    });
    expect(calls.join(" ")).toContain("1 scope omission");

    const exactRecording = recordingContext();
    drawSafeShareCard(
      exactRecording.context as unknown as Parameters<typeof drawSafeShareCard>[0],
      exactSnapshot,
    );
    expect(exactRecording.calls).toContain("Not selected");
  });

  it("never exports an incompatible observation as measured even if an unsafe caller supplies numbers", () => {
    const profile = profileFixture();
    Object.assign(profile.latest.metrics[0], {
      state: "incompatible" as const,
      ratio: 0.75,
      fractionNumerator: 3,
      fractionDenominator: 4,
      errorCode: "incompatible-provenance" as const,
    });

    expect(() => createSafeShareSnapshot(profile, "latest")).toThrow(
      /Incompatible metric provenance cannot be shared/i,
    );
  });

  it("rejects unavailable and invalid profiles and revokes blob preview URLs", () => {
    const unavailable = createQualityMetricProfile(
      "prompt-quality",
      null,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    expect(() => createSafeShareSnapshot(unavailable, "latest")).toThrow(/coherent/i);

    const invalidDetail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
    invalidDetail.results[0].numeric_value = 0.4;
    const invalid = createQualityMetricProfile(
      "prompt-quality",
      invalidDetail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    expect(() => createSafeShareSnapshot(invalid, "latest")).toThrow(/coherent/i);

    const unknownScope = profileFixture();
    unknownScope.latest.integrity = "mixed-provenance";
    unknownScope.latest.metrics.forEach((metric) => {
      metric.state = "unavailable";
      metric.ratio = null;
      metric.unknownScopeRuns = 1;
      metric.errorCode = "metric-scope-unknown";
    });
    expect(() => createSafeShareSnapshot(unknownScope, "latest")).toThrow(
      /Only a coherent immutable profile can be shared/i,
    );

    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const { asset } = runtimeFixture();
    browserShareCardRuntime.revoke(asset);
    expect(revoke).toHaveBeenCalledWith(asset.previewUrl);
    revoke.mockRestore();
  });

  it("previews before explicit actions and traps focus outside the inert app shell", async () => {
    const { asset, runtime } = runtimeFixture();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <div className="app-shell">
          <button onClick={() => setOpen(true)} type="button">Open share</button>
          {open && (
            <ProfileShareDialog
              onClose={() => setOpen(false)}
              profile={profileFixture()}
              runtime={runtime}
              snapshotKind="latest"
            />
          )}
        </div>
      );
    }

    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open share" });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Share this metric profile" });
    const shell = document.querySelector<HTMLElement>(".app-shell")!;
    expect(shell.inert).toBe(true);
    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();
    expect(screen.getByText(/derived metrics can still be sensitive/i)).toBeVisible();
    expect(runtime.download).not.toHaveBeenCalled();

    await screen.findByAltText(
      /minimized local prompt metric share card preview/i,
    );
    const download = screen.getByRole("button", { name: "Download PNG" });
    download.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(download).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Copy image" }));
    await waitFor(() => expect(runtime.copy).toHaveBeenCalledWith(asset));
    fireEvent.click(screen.getByRole("button", { name: /Share/ }));
    await waitFor(() => expect(runtime.share).toHaveBeenCalledWith(asset));
    fireEvent.click(download);
    expect(runtime.download).toHaveBeenCalledWith(asset);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(shell.inert).toBe(false);
    expect(opener).toHaveFocus();
    expect(runtime.revoke).toHaveBeenCalledWith(asset);
    expect(dialog).not.toBeInTheDocument();
  });
});
