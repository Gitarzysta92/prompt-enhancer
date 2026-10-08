import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ModelEnsembleAttemptStage, ModelEnsembleRun } from "../../shared/api/contracts";
import { ModelConstellationDrawer } from "./ModelConstellationDrawer";

function sealedRun(runId = "b".repeat(64)): ModelEnsembleRun {
  const stage = (modelKey: string, repositoryId: string, status: "completed" | "failed" = "completed") => ({
    model_key: modelKey,
    repository_id: repositoryId,
    revision: "a".repeat(40),
    status,
    error_code: status === "completed" ? null : "example_stage_failure",
    device: status === "completed" ? "cpu" : null,
    quantization: "none",
    inference_latency_ms: 12,
    peak_accelerator_memory_mb: null,
    process_rss_mb: 256,
    unloaded_after_stage: true,
  });
  return {
    run_id: runId,
    experts: [],
    predictive_model_stages: [
      stage("mdeberta_xnli", "example-org/mdeberta-xnli"),
      stage("multilingual_minilmv2_l6_nli", "example-org/multilingual-minilmv2-l6-nli", "failed"),
      stage("qwen3_4b_rubric", "example-org/qwen3-4b-rubric"),
    ],
  } as unknown as ModelEnsembleRun;
}

function attemptStages(completedAtPrefix = "2040-01-02"): ModelEnsembleAttemptStage[] {
  return [{
    stage_ordinal: 0,
    stage_key: "mdeberta_xnli",
    state: "completed",
    model_key: "mdeberta_xnli",
    repository_id: "example-org/mdeberta-xnli",
    revision: "c".repeat(40),
    error_code: null,
    device: "cuda",
    quantization: "none",
    inference_latency_ms: 0,
    peak_accelerator_memory_mb: 0,
    process_rss_mb: 1536,
    evaluated_case_count: 20,
    contributed_case_count: 0,
    unloaded_after_stage: true,
    completed_at: `${completedAtPrefix}T10:00:01Z`,
  }, {
    stage_ordinal: 1,
    stage_key: "qwen3_4b_rubric",
    state: "cancelled",
    model_key: "qwen3_4b_rubric",
    repository_id: "example-org/qwen3-4b-rubric",
    revision: null,
    error_code: "analysis_cancelled",
    device: null,
    quantization: "bitsandbytes_nf4",
    inference_latency_ms: null,
    peak_accelerator_memory_mb: null,
    process_rss_mb: null,
    evaluated_case_count: null,
    contributed_case_count: null,
    unloaded_after_stage: null,
    completed_at: `${completedAtPrefix}T10:00:02Z`,
  }];
}

function openModels(): void {
  fireEvent.click(screen.getByText("Models"));
}

describe("ModelConstellationDrawer", () => {
  it("states authority and the exact provenance source without promoting model agreement", () => {
    render(<ModelConstellationDrawer attemptStages={[]} compact={false} run={sealedRun()} />);
    openModels();

    expect(screen.getByRole("note")).toHaveTextContent(/experimental evidence helpers, not metric authorities/i);
    expect(screen.getByRole("note")).toHaveTextContent(/sealed measured publication.*never from model agreement/i);
    expect(screen.getByText("Displayed provenance").parentElement).toHaveTextContent("Sealed snapshot");
    expect(screen.getByText("Receipt source").parentElement).toHaveTextContent("Sealed snapshot");
    expect(screen.getByText("Measured-metric authority").nextElementSibling).toHaveTextContent("none");
  });

  it("uses semantic groups, explicit status, one pressed node, and complete sealed provenance without inventing counts", () => {
    render(<ModelConstellationDrawer attemptStages={[]} compact={false} run={sealedRun()} />);
    expect(screen.getByText("Models").parentElement).toHaveTextContent("Sealed snapshot · 2/3 stages completed");
    openModels();

    const factorHeading = screen.getByRole("heading", { level: 4, name: "Factor models" });
    const deepHeading = screen.getByRole("heading", { level: 4, name: "Deep judge" });
    const factorGroup = screen.getByRole("group", { name: "Factor models stages" });
    const deepGroup = screen.getByRole("group", { name: "Deep judge stages" });
    expect(factorHeading.closest("section")).toContainElement(factorGroup);
    expect(deepHeading.closest("section")).toContainElement(deepGroup);
    expect(within(factorGroup).getAllByRole("button")).toHaveLength(2);
    expect(within(deepGroup).getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByText("Challengers")).not.toBeInTheDocument();
    expect(screen.queryByText("Legacy stages")).not.toBeInTheDocument();

    const pressed = document.querySelectorAll('.model-constellation__nodes button[aria-pressed="true"]');
    expect(pressed).toHaveLength(1);
    expect(pressed[0]).toHaveTextContent("mdeberta-xnli");
    expect(document.querySelector('.model-constellation__nodes button[data-status="failed"]')).toHaveTextContent("failed");

    const inspector = document.querySelector(".model-constellation__inspector")!;
    expect(inspector).toHaveAttribute("aria-live", "polite");
    expect(inspector).toHaveAttribute("aria-atomic", "true");
    expect(within(inspector as HTMLElement).getByText("Peak VRAM").parentElement).toHaveTextContent("not recorded");
    expect(within(inspector as HTMLElement).getByText("Peak RAM").parentElement).toHaveTextContent("256 MiB");
    expect(within(inspector as HTMLElement).getByText("Experimental cases evaluated").parentElement).toHaveTextContent("unavailable");
    expect(within(inspector as HTMLElement).getByText("Experimental cases contributed").parentElement).toHaveTextContent("unavailable");
    expect(inspector).toHaveTextContent(/they are not zero/i);

    fireEvent.click(within(deepGroup).getByRole("button"));
    expect(screen.getByRole("heading", { level: 4, name: "example-org/qwen3-4b-rubric" })).toBeInTheDocument();
    expect(inspector).toHaveTextContent("Selective disagreement adjudicator");
    expect(document.querySelectorAll('.model-constellation__nodes button[aria-pressed="true"]')).toHaveLength(1);
  });

  it("prefers latest-attempt rows, preserves recorded zero, distinguishes null, and keeps provenance facts in compact mode", () => {
    render(<ModelConstellationDrawer attemptStages={attemptStages()} compact={true} run={sealedRun()} />);
    expect(screen.getByText("Models").parentElement).toHaveTextContent("Latest attempt · 1/2 stages completed");
    openModels();

    expect(screen.getByText("Displayed provenance").parentElement).toHaveTextContent("Latest durable attempt");
    expect(screen.getByText("Receipt source").parentElement).toHaveTextContent("Latest durable attempt");
    expect(screen.getByText("Latency").parentElement).toHaveTextContent("0 ms");
    expect(screen.getByText("Peak VRAM").parentElement).toHaveTextContent("0 MiB");
    expect(screen.getByText("Peak RAM").parentElement).toHaveTextContent("1536 MiB");
    expect(screen.getByText("Experimental cases evaluated").parentElement).toHaveTextContent("20");
    expect(screen.getByText("Experimental cases contributed").parentElement).toHaveTextContent("0");
    expect(screen.getByText("Released").parentElement).toHaveTextContent("yes · unloaded after stage");
    expect(screen.queryByText(/they are not zero/i)).not.toBeInTheDocument();

    fireEvent.click(document.querySelector('.model-constellation__nodes button[data-status="cancelled"]')!);
    expect(screen.getByRole("alert")).toHaveTextContent("Stage reportanalysis cancelled");
    expect(screen.getByText("Revision").parentElement).toHaveTextContent("not recorded");
    expect(screen.getByText("Latency").parentElement).toHaveTextContent("not recorded");
    expect(screen.getByText("Released").parentElement).toHaveTextContent("not recorded · unload receipt missing");
    expect(screen.getByText("Device").parentElement).toHaveTextContent("not recorded");
    expect(screen.getByText("Quantization").parentElement).toHaveTextContent("bitsandbytes nf4");
    expect(screen.getByText("Experimental cases evaluated").parentElement).toHaveTextContent("unavailable");
    expect(screen.getByText(/they are not zero/i)).toBeInTheDocument();
  });

  it("distinguishes an explicit false unload receipt from an unknown receipt", () => {
    const stages = attemptStages();
    stages[0] = { ...stages[0], unloaded_after_stage: false };
    render(<ModelConstellationDrawer attemptStages={stages} compact={false} run={sealedRun()} />);
    openModels();

    expect(screen.getByText("Released").parentElement).toHaveTextContent("no · not unloaded after stage");
    fireEvent.click(document.querySelector('.model-constellation__nodes button[data-status="cancelled"]')!);
    expect(screen.getByText("Released").parentElement).toHaveTextContent("not recorded · unload receipt missing");
  });

  it("uses Arrow, Home, and End to focus and update the inspected stage", () => {
    render(<ModelConstellationDrawer attemptStages={[]} compact={false} run={sealedRun()} />);
    openModels();
    const factorNodes = screen.getByRole("group", { name: "Factor models stages" });
    const [first, second] = within(factorNodes).getAllByRole("button");
    first.focus();
    fireEvent.keyDown(factorNodes, { key: "ArrowRight" });
    expect(second).toHaveFocus();
    expect(second).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Status").parentElement).toHaveTextContent("failed");
    fireEvent.keyDown(factorNodes, { key: "Home" });
    expect(first).toHaveFocus();
    expect(first).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(factorNodes, { key: "End" });
    expect(second).toHaveFocus();
    expect(second).toHaveAttribute("aria-pressed", "true");
  });

  it("synchronously resets a selected stage when sealed context A changes to B", () => {
    const runA = sealedRun("a".repeat(64));
    const view = render(<ModelConstellationDrawer attemptStages={[]} compact={false} run={runA} />);
    openModels();
    fireEvent.click(screen.getByRole("group", { name: "Deep judge stages" }).querySelector("button")!);
    expect(screen.getByRole("heading", { level: 4, name: /qwen3-4b-rubric/i })).toBeInTheDocument();

    view.rerender(<ModelConstellationDrawer attemptStages={[]} compact={false} run={sealedRun("d".repeat(64))} />);
    expect(document.querySelectorAll('.model-constellation__nodes button[aria-pressed="true"]')).toHaveLength(1);
    expect(document.querySelector('.model-constellation__nodes button[aria-pressed="true"]')).toHaveTextContent("mdeberta-xnli");
    expect(screen.getByRole("heading", { level: 4, name: "example-org/mdeberta-xnli" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("group", { name: "Deep judge stages" }).querySelector("button")!);
    view.rerender(<ModelConstellationDrawer attemptStages={attemptStages("2040-03-04")} compact={false} run={sealedRun("d".repeat(64))} />);
    expect(screen.getByText("Receipt source").parentElement).toHaveTextContent("Latest durable attempt");
    expect(document.querySelector('.model-constellation__nodes button[aria-pressed="true"]')).toHaveTextContent("mdeberta-xnli");
    expect(screen.getByRole("heading", { level: 4, name: "example-org/mdeberta-xnli" })).toBeInTheDocument();
  });

  it("renders resource-exhausted and unavailable attempt states as explicit non-completed receipts", () => {
    const stages = attemptStages();
    stages[0] = { ...stages[0], state: "resource_exhausted", error_code: "example_resource_limit" };
    stages[1] = { ...stages[1], state: "unavailable", error_code: "example_stage_unavailable" };
    render(<ModelConstellationDrawer attemptStages={stages} compact={false} run={sealedRun()} />);
    expect(screen.getByText("Models").parentElement).toHaveTextContent("Latest attempt · 0/2 stages completed");
    openModels();
    expect(document.querySelector('.model-constellation__nodes button[data-status="resource_exhausted"]')).toHaveTextContent("resource exhausted");
    expect(screen.getByText("Status").parentElement).toHaveTextContent("resource exhausted");
    expect(screen.getByRole("alert")).toHaveTextContent("example resource limit");
    fireEvent.click(document.querySelector('.model-constellation__nodes button[data-status="unavailable"]')!);
    expect(screen.getByText("Status").parentElement).toHaveTextContent("unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("example stage unavailable");
  });

  it("exposes long content-free repository and revision identities without changing their facts", () => {
    const run = sealedRun();
    const repository = `example-org/${"long-model-identity-".repeat(8)}fixture`;
    const revision = "abcdef0123456789".repeat(4);
    run.predictive_model_stages[0].repository_id = repository;
    run.predictive_model_stages[0].revision = revision;
    render(<ModelConstellationDrawer attemptStages={[]} compact={false} run={run} />);
    openModels();

    const node = screen.getByRole("button", { name: new RegExp(repository) });
    expect(node).toHaveAttribute("title", `${repository} · Primary multilingual factor model`);
    expect(screen.getByRole("heading", { level: 4, name: repository })).toBeInTheDocument();
    const revisionCode = screen.getByText("abcdef01…6789");
    expect(revisionCode).toHaveAttribute("title", revision);
  });

  it("states when stage receipts are not exposed and does not create an inspector or zero-count fiction", () => {
    render(<ModelConstellationDrawer attemptStages={[]} compact={false} run={null} />);
    expect(screen.getByText("Models").parentElement).toHaveTextContent("Stage receipts not exposed");
    openModels();
    expect(screen.getByText(/not exposed for this sealed receipt/i)).toHaveTextContent(/do not imply.*failed.*zero cases/i);
    expect(document.querySelector(".model-constellation__inspector")).toBeNull();
    expect(screen.queryByRole("group", { name: /stages/i })).not.toBeInTheDocument();
  });
});
