import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SessionMetric } from "../../shared/api/contracts";
import { SessionMetricCard } from "./SessionMetricCard";

const UNKNOWN_METRIC: SessionMetric = {
  key: "fictional.future.observation",
  version: 3,
  dimension: "future",
  display_name: "Fictional observation",
  numeric_value: null,
  text_value: null,
  unit: null,
  source: "synthetic_fixture",
  observed_count: 0,
  eligible_count: 2,
  coverage: 0,
  confidence: null,
  metric_pack_key: "example.metadata.session",
  metric_pack_version: 4,
  metric_engine_version: "example-engine-1",
  redactor_version: null,
  model_id: null,
  model_revision: null,
  tokenizer_id: null,
  prompt_version: null,
  rubric_version: null,
  computed_at: "2040-02-01T12:00:00Z",
};

// Same public-record shape returned by /v1/sessions/{id}/metrics, using only
// reserved synthetic values. The backend integration test exercises the
// corresponding persisted unknown token observation.
const UNKNOWN_TOKEN_METRIC: SessionMetric = {
  ...UNKNOWN_METRIC,
  key: "usage.total_tokens",
  dimension: "usage",
  display_name: "Total tokens",
  unit: "tokens",
  eligible_count: 1,
};

const OBSERVED_ZERO_TOKEN_METRIC: SessionMetric = {
  ...UNKNOWN_TOKEN_METRIC,
  numeric_value: 0,
  observed_count: 1,
  eligible_count: 1,
  coverage: 1,
};

describe("SessionMetricCard", () => {
  it("shows missing observations as unknown and preserves provenance", () => {
    render(<SessionMetricCard metric={UNKNOWN_METRIC} />);

    expect(screen.getByText("Unknown", { selector: "strong" })).toBeVisible();
    expect(screen.getByText(/no usable observations/i)).toBeVisible();
    expect(screen.getByRole("meter")).toHaveAccessibleName(
      "0 of 2 observations (0%)",
    );
    expect(screen.getByText("Unknown", { selector: ".status-pill" })).toBeVisible();

    const provenance = screen.getByText("Definition and provenance");
    provenance.click();
    expect(screen.getByText("example-engine-1")).toBeVisible();
    expect(screen.getAllByText("Not reported")).toHaveLength(6);
  });

  it("shows missing token usage as Unknown rather than zero", () => {
    render(<SessionMetricCard metric={UNKNOWN_TOKEN_METRIC} />);

    expect(screen.getByText("Unknown", { selector: "strong" })).toBeVisible();
    expect(screen.getByText(/no usable observations/i)).toBeVisible();
    expect(screen.getByRole("meter")).toHaveAccessibleName(
      "0 of 1 observations (0%)",
    );
  });

  it("keeps a measured zero token count distinct from unknown", () => {
    render(<SessionMetricCard metric={OBSERVED_ZERO_TOKEN_METRIC} />);

    expect(screen.getByText("0 tokens", { selector: "strong" })).toBeVisible();
    expect(screen.getByRole("meter")).toHaveAccessibleName(
      "1 of 1 observations (100%)",
    );
    expect(screen.queryByText("Unknown", { selector: "strong" })).toBeNull();
  });
});
