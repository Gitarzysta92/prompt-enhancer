import { useEffect, useRef, useState } from "react";
import {
  AnnotationMode,
  getDocument,
  GlobalWorkerOptions,
  RenderingCancelledException,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
  type RenderTask,
} from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import "./AgentPdfPreview.css";

const MIN_ZOOM = 0.75;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.25;
const MAX_OUTPUT_SCALE = 2;
const MAX_PDF_IMAGE_PIXELS = 33_554_432;

type PdfRenderPhase = "loading" | "ready" | "error";

GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export function AgentPdfPreview({
  blob,
  onStateChange,
  title,
  versionNumber,
}: {
  blob: Blob;
  onStateChange: (phase: PdfRenderPhase) => void;
  title: string;
  versionNumber: number;
}) {
  const [documentProxy, setDocumentProxy] = useState<PDFDocumentProxy | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [phase, setPhase] = useState<PdfRenderPhase>("loading");
  const [message, setMessage] = useState("Reading the verified PDF structure…");
  const [stageWidth, setStageWidth] = useState(720);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const stateCallbackRef = useRef(onStateChange);

  useEffect(() => {
    stateCallbackRef.current = onStateChange;
  }, [onStateChange]);

  useEffect(() => {
    const stage = stageRef.current;
    if (stage === null) return;
    const update = () => setStageWidth(Math.max(240, Math.floor(stage.clientWidth || 720)));
    update();
    if (typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(update);
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: PDFDocumentLoadingTask | null = null;
    setDocumentProxy(null);
    setPageCount(0);
    setPageNumber(1);
    setZoom(1);
    setPhase("loading");
    setMessage("Reading the verified PDF structure…");
    stateCallbackRef.current("loading");
    void (async () => {
      const data = new Uint8Array(await blob.arrayBuffer());
      if (cancelled) return;
      loadingTask = getDocument({
        data,
        disableAutoFetch: true,
        disableRange: true,
        disableStream: true,
        enableXfa: false,
        maxImageSize: MAX_PDF_IMAGE_PIXELS,
        stopAtErrors: true,
        useWasm: false,
        useWorkerFetch: false,
      });
      const loaded = await loadingTask.promise;
      if (cancelled) {
        await loadingTask.destroy();
        return;
      }
      if (loaded.numPages < 1 || loaded.numPages > 10_000) {
        await loadingTask.destroy();
        throw new Error("pdf_page_count_invalid");
      }
      setDocumentProxy(loaded);
      setPageCount(loaded.numPages);
      setMessage("Rendering page 1…");
    })().catch(() => {
      if (cancelled) return;
      setPhase("error");
      setMessage("This digest-verified PDF could not be parsed safely. It was not rendered, executed, or sent anywhere.");
      stateCallbackRef.current("error");
    });
    return () => {
      cancelled = true;
      if (loadingTask !== null) void loadingTask.destroy();
    };
  }, [blob]);

  useEffect(() => {
    if (documentProxy === null) return;
    let cancelled = false;
    let renderTask: RenderTask | null = null;
    setPhase("loading");
    setMessage(`Rendering page ${pageNumber} of ${pageCount}…`);
    stateCallbackRef.current("loading");
    void (async () => {
      const page = await documentProxy.getPage(pageNumber);
      if (cancelled) return;
      const baseViewport = page.getViewport({ scale: 1 });
      const fitScale = Math.max(0.1, (stageWidth - 24) / baseViewport.width);
      const viewport = page.getViewport({ scale: fitScale * zoom });
      const canvas = canvasRef.current;
      if (canvas === null || canvas.getContext("2d", { alpha: false }) === null) {
        throw new Error("pdf_canvas_unavailable");
      }
      const outputScale = Math.min(window.devicePixelRatio || 1, MAX_OUTPUT_SCALE);
      canvas.width = Math.max(1, Math.floor(viewport.width * outputScale));
      canvas.height = Math.max(1, Math.floor(viewport.height * outputScale));
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      renderTask = page.render({
        annotationMode: AnnotationMode.DISABLE,
        background: "#ffffff",
        canvas,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        viewport,
      });
      await renderTask.promise;
      if (cancelled) return;
      setPhase("ready");
      setMessage(`Page ${pageNumber} of ${pageCount} ready. Links, forms, scripts, audio, and annotations are not interactive.`);
      stateCallbackRef.current("ready");
    })().catch((error: unknown) => {
      if (cancelled || error instanceof RenderingCancelledException) return;
      setPhase("error");
      setMessage(`Page ${pageNumber} could not be rendered safely. The PDF stayed local and no substitute content was shown.`);
      stateCallbackRef.current("error");
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [documentProxy, pageCount, pageNumber, stageWidth, zoom]);

  return (
    <section
      aria-label={`PDF preview of ${title} v${versionNumber}`}
      className="agent-pdf-preview"
      data-state={phase}
    >
      <header className="agent-pdf-preview__toolbar">
        <span>
          <strong>PDF preview</strong>
          <small>Local canvas renderer · interactive document features omitted</small>
        </span>
        <div aria-label="PDF page controls" role="group">
          <button
            aria-label="Previous PDF page"
            className="button button--ghost"
            disabled={phase === "error" || pageNumber <= 1}
            onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
            type="button"
          >Previous</button>
          <span aria-live="polite">{pageCount > 0 ? `${pageNumber} / ${pageCount}` : "— / —"}</span>
          <button
            aria-label="Next PDF page"
            className="button button--ghost"
            disabled={phase === "error" || pageCount === 0 || pageNumber >= pageCount}
            onClick={() => setPageNumber((current) => Math.min(pageCount, current + 1))}
            type="button"
          >Next</button>
        </div>
        <div aria-label="PDF zoom" role="group">
          <button
            aria-label="Zoom out PDF"
            className="button button--ghost"
            disabled={phase === "error" || zoom <= MIN_ZOOM}
            onClick={() => setZoom((current) => Math.max(MIN_ZOOM, current - ZOOM_STEP))}
            type="button"
          >−</button>
          <button
            aria-label="Fit PDF page to viewer"
            className="button button--ghost"
            disabled={phase === "error" || zoom === 1}
            onClick={() => setZoom(1)}
            type="button"
          >Fit · {Math.round(zoom * 100)}%</button>
          <button
            aria-label="Zoom in PDF"
            className="button button--ghost"
            disabled={phase === "error" || zoom >= MAX_ZOOM}
            onClick={() => setZoom((current) => Math.min(MAX_ZOOM, current + ZOOM_STEP))}
            type="button"
          >+</button>
        </div>
      </header>
      <div className="agent-pdf-preview__stage" ref={stageRef}>
        <p
          className={phase === "error" ? "agent-pdf-preview__state agent-pdf-preview__state--error" : "agent-pdf-preview__state"}
          role={phase === "error" ? "alert" : "status"}
        >{message}</p>
        <canvas
          aria-label={`Rendered PDF page ${pageNumber} of ${Math.max(pageCount, 1)}`}
          className="agent-pdf-preview__canvas"
          data-state={phase}
          ref={canvasRef}
          role="img"
        />
      </div>
    </section>
  );
}
