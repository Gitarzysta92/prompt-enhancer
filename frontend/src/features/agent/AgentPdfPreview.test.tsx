import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pdfMocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  workerOptions: { workerSrc: "" },
}));

vi.mock("pdfjs-dist", () => ({
  AnnotationMode: { DISABLE: 0 },
  getDocument: pdfMocks.getDocument,
  GlobalWorkerOptions: pdfMocks.workerOptions,
  RenderingCancelledException: class RenderingCancelledException extends Error {},
}));

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({
  default: "/assets/synthetic-pdf-worker.mjs",
}));

import { AgentPdfPreview } from "./AgentPdfPreview";

const originalCanvasContext = Object.getOwnPropertyDescriptor(
  HTMLCanvasElement.prototype,
  "getContext",
);

function pdfDocument(pageCount = 3) {
  const renderTasks: Array<{ cancel: ReturnType<typeof vi.fn>; promise: Promise<void> }> = [];
  const render = vi.fn(() => {
    const task = { cancel: vi.fn(), promise: Promise.resolve() };
    renderTasks.push(task);
    return task;
  });
  const getViewport = vi.fn(({ scale }: { scale: number }) => ({
    height: 800 * scale,
    width: 600 * scale,
  }));
  const getPage = vi.fn(async () => ({ getViewport, render }));
  return {
    document: { getPage, numPages: pageCount },
    getPage,
    getViewport,
    render,
    renderTasks,
  };
}

beforeEach(() => {
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    value: vi.fn(() => ({})),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  pdfMocks.getDocument.mockReset();
  if (originalCanvasContext) {
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", originalCanvasContext);
  } else {
    Reflect.deleteProperty(HTMLCanvasElement.prototype, "getContext");
  }
});

describe("AgentPdfPreview", () => {
  it("renders verified in-memory bytes page by page with annotations disabled and no URL fetch", async () => {
    const fixture = pdfDocument();
    const destroy = vi.fn().mockResolvedValue(undefined);
    pdfMocks.getDocument.mockReturnValue({
      destroy,
      promise: Promise.resolve(fixture.document),
    });
    const onStateChange = vi.fn();
    const { unmount } = render(<AgentPdfPreview
      blob={new Blob(["%PDF-1.4\n%%EOF\n"], { type: "application/pdf" })}
      onStateChange={onStateChange}
      title="synthetic-report.pdf"
      versionNumber={2}
    />);

    const canvas = await screen.findByRole("img", { name: "Rendered PDF page 1 of 3" });
    await waitFor(() => expect(canvas).toHaveAttribute("data-state", "ready"));
    expect(pdfMocks.workerOptions.workerSrc).toBe("/assets/synthetic-pdf-worker.mjs");
    expect(pdfMocks.getDocument).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.any(Uint8Array),
      disableAutoFetch: true,
      disableRange: true,
      disableStream: true,
      enableXfa: false,
      maxImageSize: 33_554_432,
      stopAtErrors: true,
      useWasm: false,
      useWorkerFetch: false,
    }));
    expect(fixture.render).toHaveBeenCalledWith(expect.objectContaining({
      annotationMode: 0,
      background: "#ffffff",
      canvas,
    }));
    expect(onStateChange).toHaveBeenCalledWith("loading");
    expect(onStateChange).toHaveBeenLastCalledWith("ready");
    expect(screen.getByText(/Links, forms, scripts, audio, and annotations are not interactive/u)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Next PDF page" }));
    await waitFor(() => expect(fixture.getPage).toHaveBeenLastCalledWith(2));
    expect(await screen.findByRole("img", { name: "Rendered PDF page 2 of 3" })).toHaveAttribute("data-state", "ready");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in PDF" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Fit PDF page to viewer" })).toHaveTextContent("125%"));

    unmount();
    expect(destroy).toHaveBeenCalled();
    expect(fixture.renderTasks.at(-1)?.cancel).toHaveBeenCalled();
  });

  it("fails closed when the local parser rejects the verified bytes", async () => {
    const destroy = vi.fn().mockResolvedValue(undefined);
    pdfMocks.getDocument.mockReturnValue({
      destroy,
      promise: Promise.reject(new Error("synthetic parse failure")),
    });
    const onStateChange = vi.fn();
    render(<AgentPdfPreview
      blob={new Blob(["%PDF-synthetic-invalid"], { type: "application/pdf" })}
      onStateChange={onStateChange}
      title="synthetic-invalid.pdf"
      versionNumber={1}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be parsed safely");
    expect(onStateChange).toHaveBeenLastCalledWith("error");
    expect(screen.getByRole("img", { name: "Rendered PDF page 1 of 1" })).toHaveAttribute("data-state", "error");
    expect(screen.getByRole("button", { name: "Next PDF page" })).toBeDisabled();
  });
});
