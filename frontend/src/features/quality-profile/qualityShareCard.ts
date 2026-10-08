import { formatPercent } from "../../shared/lib/format";
import type {
  QualityMetricProfile,
  QualityMetricState,
  QualityProfileSnapshot,
  QualitySnapshotKind,
} from "./qualityProfile";

export interface SafeShareMetric {
  label: string;
  polarity: "capability" | "review-load";
  state: QualityMetricState;
  ratio: number | null;
  fractionNumerator: number | null;
  fractionDenominator: number | null;
  observed: number;
  eligible: number;
  notSelectedRuns: number;
  unknownScopeRuns: number;
}

export interface SafeShareSnapshot {
  schema: "prompt-enhancer.share-card.v1";
  title: "Prompt specification" | "Logic & delivery";
  period:
    | "Initial request"
    | "Latest analysis window"
    | "First observed state"
    | "Current observed state";
  metrics: readonly SafeShareMetric[];
  analysisDate: string | null;
  definitionVersions: readonly number[];
  scope: {
    selectedSessions: number;
    completedRuns: number;
    missingRuns: number;
  } | null;
}

export interface ShareCardAsset {
  blob: Blob;
  previewUrl: string;
  filename: "prompt-enhancer-prompt-profile.png" | "prompt-enhancer-logic-profile.png";
}

export interface ShareCardRuntime {
  render(snapshot: SafeShareSnapshot): Promise<ShareCardAsset>;
  revoke(asset: ShareCardAsset): void;
  download(asset: ShareCardAsset): void;
  canCopy(): boolean;
  copy(asset: ShareCardAsset): Promise<void>;
  canShare(asset: ShareCardAsset): boolean;
  share(asset: ShareCardAsset): Promise<void>;
}

function boundedCount(value: number): number {
  return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 999_999) : 0;
}

function safeRatio(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value >= 0 && value <= 1
    ? value
    : null;
}

function safeDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date.toISOString().slice(0, 10);
}

function sourceSnapshot(
  profile: QualityMetricProfile,
  snapshotKind: QualitySnapshotKind,
): QualityProfileSnapshot {
  return snapshotKind === "initial" ? profile.initial : profile.latest;
}

export function createSafeShareSnapshot(
  profile: QualityMetricProfile,
  snapshotKind: QualitySnapshotKind,
): SafeShareSnapshot {
  const snapshot = sourceSnapshot(profile, snapshotKind);
  if (snapshot.integrity !== "coherent") {
    throw new TypeError("Only a coherent immutable profile can be shared.");
  }
  if (snapshot.metrics.some((metric) => metric.state === "incompatible")) {
    throw new TypeError("Incompatible metric provenance cannot be shared.");
  }
  const analysisDates = snapshot.metrics
    .map((metric) => safeDate(metric.computedAt))
    .filter((date): date is string => date !== null)
    .sort();
  const versions = snapshot.metrics
    .map((metric) => metric.definitionVersion)
    .filter(
      (version): version is number =>
        typeof version === "number" && Number.isSafeInteger(version) && version > 0,
    );
  return {
    schema: "prompt-enhancer.share-card.v1",
    title: profile.kind === "prompt" ? "Prompt specification" : "Logic & delivery",
    period: snapshotKind === "initial" ? profile.initialLabel : profile.latestLabel,
    metrics: snapshot.metrics.map((metric) => ({
      label: metric.definition.label,
      polarity: metric.definition.polarity,
      state: metric.state,
      ratio:
        metric.state === "observed" || metric.state === "partial"
          ? safeRatio(metric.ratio)
          : null,
      fractionNumerator:
        (metric.state !== "observed" && metric.state !== "partial") ||
        metric.fractionNumerator === null
          ? null
          : boundedCount(metric.fractionNumerator),
      fractionDenominator:
        (metric.state !== "observed" && metric.state !== "partial") ||
        metric.fractionDenominator === null
          ? null
          : boundedCount(metric.fractionDenominator),
      observed: boundedCount(metric.observed),
      eligible: boundedCount(metric.eligible),
      notSelectedRuns: boundedCount(metric.notSelectedRuns),
      unknownScopeRuns: boundedCount(metric.unknownScopeRuns),
    })),
    analysisDate: analysisDates.at(-1) ?? null,
    definitionVersions: [...new Set(versions)].sort((left, right) => left - right),
    scope: snapshot.scope
      ? {
          selectedSessions: boundedCount(snapshot.scope.selectedSessions),
          completedRuns: boundedCount(snapshot.scope.completedRuns),
          missingRuns: boundedCount(snapshot.scope.missingRuns),
        }
      : null,
  };
}

type ShareContext = Pick<
  CanvasRenderingContext2D,
  | "arc"
  | "beginPath"
  | "closePath"
  | "fill"
  | "fillRect"
  | "fillText"
  | "lineTo"
  | "measureText"
  | "moveTo"
  | "roundRect"
  | "stroke"
> &
  Pick<
    CanvasRenderingContext2D,
    | "fillStyle"
    | "font"
    | "lineCap"
    | "lineJoin"
    | "lineWidth"
    | "strokeStyle"
    | "textAlign"
    | "textBaseline"
  >;

function displayState(state: QualityMetricState): string {
  if (state === "not-selected") return "Not selected";
  if (state === "incompatible") return "Incompatible";
  if (state === "not-applicable") return "Not applicable";
  if (state === "execution-error") return "Execution error";
  return `${state.charAt(0).toUpperCase()}${state.slice(1)}`;
}

function polarPoint(index: number, count: number, radius: number) {
  const angle = -Math.PI / 2 + (index * Math.PI * 2) / count;
  return { x: 238 + Math.cos(angle) * radius, y: 318 + Math.sin(angle) * radius };
}

export function drawSafeShareCard(
  context: ShareContext,
  snapshot: SafeShareSnapshot,
): void {
  context.fillStyle = "#f4f7f6";
  context.fillRect(0, 0, 1200, 630);
  context.fillStyle = "#102d30";
  context.fillRect(0, 0, 1200, 16);
  context.fillStyle = "#ffffff";
  context.beginPath();
  context.roundRect(46, 42, 1108, 542, 28);
  context.fill();

  context.fillStyle = "#14766b";
  context.font = "700 20px system-ui, sans-serif";
  context.fillText("PROMPT ENHANCER · LOCAL PROFILE", 82, 90);
  context.fillStyle = "#102d30";
  context.font = "750 42px system-ui, sans-serif";
  context.fillText(snapshot.title, 82, 142);
  context.fillStyle = "#667b7e";
  context.font = "500 19px system-ui, sans-serif";
  context.fillText(snapshot.period, 82, 177);

  const count = snapshot.metrics.length;
  for (const ring of [0.25, 0.5, 0.75, 1]) {
    context.beginPath();
    snapshot.metrics.forEach((_metric, index) => {
      const coordinate = polarPoint(index, count, 118 * ring);
      if (index === 0) context.moveTo(coordinate.x, coordinate.y);
      else context.lineTo(coordinate.x, coordinate.y);
    });
    context.closePath();
    context.strokeStyle = "#dbe6e4";
    context.lineWidth = 2;
    context.stroke();
  }
  snapshot.metrics.forEach((metric, index) => {
    const end = polarPoint(index, count, 118);
    context.beginPath();
    context.moveTo(238, 318);
    context.lineTo(end.x, end.y);
    context.strokeStyle = "#dbe6e4";
    context.lineWidth = 2;
    context.stroke();
    if (metric.ratio !== null) {
      const value = polarPoint(index, count, 118 * metric.ratio);
      context.beginPath();
      context.moveTo(238, 318);
      context.lineTo(value.x, value.y);
      context.strokeStyle = metric.polarity === "review-load" ? "#d8892d" : "#29a394";
      context.lineWidth = 11;
      context.lineCap = "round";
      context.stroke();
    }
  });

  snapshot.metrics.forEach((metric, index) => {
    const y = 225 + index * 67;
    context.fillStyle = metric.polarity === "review-load" ? "#fff5e8" : "#eaf7f4";
    context.beginPath();
    context.roundRect(430, y - 30, 676, 54, 14);
    context.fill();
    context.fillStyle = "#17383a";
    context.font = "650 19px system-ui, sans-serif";
    context.fillText(metric.label, 452, y - 5);
    if (metric.polarity === "review-load") {
      context.fillStyle = "#a15d16";
      context.font = "650 12px system-ui, sans-serif";
      context.fillText("Review load · lower is better", 452, y + 15);
    }
    context.textAlign = "right";
    context.fillStyle = metric.polarity === "review-load" ? "#a15d16" : "#14766b";
    context.font = "750 22px system-ui, sans-serif";
    context.fillText(
      metric.ratio === null ? displayState(metric.state) : formatPercent(metric.ratio),
      1080,
      y - 5,
    );
    context.fillStyle = "#53666a";
    context.font = "600 13px system-ui, sans-serif";
    const metricFraction =
      metric.fractionDenominator !== null && metric.fractionDenominator > 0
        ? `${metric.fractionNumerator}/${metric.fractionDenominator} metric`
        : "no metric fraction";
    const observationCoverage =
      metric.eligible > 0
        ? `${metric.observed}/${metric.eligible} coverage`
        : "no eligible observations";
    const scopeOmission = metric.notSelectedRuns > 0
      ? ` · ${metric.notSelectedRuns} scope omission${metric.notSelectedRuns === 1 ? "" : "s"}`
      : "";
    const unknownScope = metric.unknownScopeRuns > 0
      ? ` · ${metric.unknownScopeRuns} legacy scope unknown`
      : "";
    context.fillText(
      `${displayState(metric.state)} · ${metricFraction} · ${observationCoverage}${scopeOmission}${unknownScope}`,
      1080,
      y + 15,
    );
    context.textAlign = "left";
  });
  context.fillStyle = "#6f8183";
  context.font = "500 15px system-ui, sans-serif";
  const scopeMetadata = snapshot.scope
    ? `Scope: ${snapshot.scope.selectedSessions} selected · ${snapshot.scope.completedRuns} completed · ${snapshot.scope.missingRuns} missing`
    : null;
  const provenanceMetadata = [
    snapshot.analysisDate ? `Analyzed ${snapshot.analysisDate}` : "Analysis date unavailable",
    snapshot.definitionVersions.length > 0
      ? `Definitions ${snapshot.definitionVersions.map((version) => `v${version}`).join("/")}`
      : "Definition versions unavailable",
    "Independent metrics · no aggregate score",
  ].join("  ·  ");
  if (scopeMetadata) {
    context.fillText(scopeMetadata, 82, 542);
    context.fillText(provenanceMetadata, 82, 566);
  } else {
    context.fillText(provenanceMetadata, 82, 550);
  }
}

function filenameFor(snapshot: SafeShareSnapshot): ShareCardAsset["filename"] {
  return snapshot.title === "Prompt specification"
    ? "prompt-enhancer-prompt-profile.png"
    : "prompt-enhancer-logic-profile.png";
}

export async function renderSafeShareCard(
  snapshot: SafeShareSnapshot,
): Promise<ShareCardAsset> {
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 630;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("PNG preview is not supported by this browser.");
  drawSafeShareCard(context, snapshot);
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((value) => {
      if (value) resolve(value);
      else reject(new Error("The PNG preview could not be created."));
    }, "image/png");
  });
  return {
    blob,
    previewUrl: URL.createObjectURL(blob),
    filename: filenameFor(snapshot),
  };
}

export const browserShareCardRuntime: ShareCardRuntime = {
  render: renderSafeShareCard,
  revoke(asset) {
    if (asset.previewUrl.startsWith("blob:")) URL.revokeObjectURL(asset.previewUrl);
  },
  download(asset) {
    const anchor = document.createElement("a");
    anchor.download = asset.filename;
    anchor.href = asset.previewUrl;
    anchor.rel = "noopener";
    anchor.click();
  },
  canCopy() {
    return Boolean(
      navigator.clipboard &&
        typeof navigator.clipboard.write === "function" &&
        typeof ClipboardItem !== "undefined",
    );
  },
  async copy(asset) {
    if (!this.canCopy()) throw new Error("Copy image is not supported by this browser.");
    await navigator.clipboard.write([
      new ClipboardItem({ "image/png": asset.blob }),
    ]);
  },
  canShare(asset) {
    if (!navigator.share || !navigator.canShare) return false;
    const file = new File([asset.blob], asset.filename, { type: "image/png" });
    return navigator.canShare({ files: [file] });
  },
  async share(asset) {
    if (!this.canShare(asset)) throw new Error("System sharing is not supported by this browser.");
    const file = new File([asset.blob], asset.filename, { type: "image/png" });
    await navigator.share({ files: [file], title: "Prompt Enhancer metric profile" });
  },
};
