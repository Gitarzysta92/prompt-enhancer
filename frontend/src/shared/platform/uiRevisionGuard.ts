const UI_REVISION_PATH = "/app-revision.json";
const UI_REVISION_INTERVAL_MS = 5_000;
const HASHED_JAVASCRIPT_REVISION =
  /^assets\/[A-Za-z0-9][A-Za-z0-9._-]*-[A-Za-z0-9_-]{8,}\.js$/;

type RevisionResponse = {
  readonly ok: boolean;
  json(): Promise<unknown>;
};

type RevisionFetch = (
  input: string,
  init: RequestInit,
) => Promise<RevisionResponse>;

type RevisionWindow = Pick<
  Window,
  | "addEventListener"
  | "removeEventListener"
  | "setInterval"
  | "clearInterval"
  | "fetch"
>;

type RevisionDocument = Pick<
  Document,
  "addEventListener" | "removeEventListener" | "visibilityState"
>;

export interface UiRevisionGuardOptions {
  /** Keep synthetic and development previews completely inert. */
  readonly enabled: boolean;
  /** Pass the caller's `import.meta.url`; no build-time global is inspected here. */
  readonly moduleUrl: string;
  readonly fetchImpl?: RevisionFetch;
  readonly reload?: () => void;
  readonly browserWindow?: RevisionWindow;
  readonly browserDocument?: RevisionDocument;
}

export interface DisposableUiRevisionGuard {
  dispose(): void;
}

/**
 * Return the exact revision shape emitted by the production asset build.
 *
 * The parser intentionally rejects query strings, fragments, traversal, source
 * module names, and unhashed files. An unknown build layout disables the guard
 * instead of guessing and creating a reload loop.
 */
export function deriveLoadedUiRevision(moduleUrl: string): string | null {
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(moduleUrl);
  } catch {
    return null;
  }

  if (parsedUrl.search !== "" || parsedUrl.hash !== "") {
    return null;
  }

  const match = parsedUrl.pathname.match(/(?:^|\/)(assets\/[^/]+\.js)$/);
  const revision = match?.[1] ?? null;
  return revision !== null && HASHED_JAVASCRIPT_REVISION.test(revision)
    ? revision
    : null;
}

function revisionFromPayload(payload: unknown): string | null {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const keys = Object.keys(payload);
  if (keys.length !== 1 || keys[0] !== "revision") {
    return null;
  }

  const revision = (payload as Record<string, unknown>).revision;
  return typeof revision === "string" &&
    HASHED_JAVASCRIPT_REVISION.test(revision)
    ? revision
    : null;
}

const INERT_GUARD: DisposableUiRevisionGuard = Object.freeze({
  dispose() {},
});

/**
 * Reload a production SPA once when its loaded JS asset no longer matches the
 * revision served by the same local origin. Network and schema failures are
 * deliberately ignored: this guard never calls a provider or application API.
 */
export function startUiRevisionGuard(
  options: UiRevisionGuardOptions,
): DisposableUiRevisionGuard {
  if (!options.enabled) {
    return INERT_GUARD;
  }

  const loadedRevision = deriveLoadedUiRevision(options.moduleUrl);
  if (loadedRevision === null) {
    return INERT_GUARD;
  }

  const browserWindow = options.browserWindow ?? window;
  const browserDocument = options.browserDocument ?? document;
  const fetchImpl =
    options.fetchImpl ?? browserWindow.fetch.bind(browserWindow);
  const reload = options.reload ?? (() => window.location.reload());

  let disposed = false;
  let reloadRequested = false;
  let checkInFlight = false;

  const checkRevision = async () => {
    if (disposed || reloadRequested || checkInFlight) {
      return;
    }

    checkInFlight = true;
    try {
      const response = await fetchImpl(UI_REVISION_PATH, {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (disposed || !response.ok) {
        return;
      }

      const currentRevision = revisionFromPayload(await response.json());
      if (
        disposed ||
        currentRevision === null ||
        currentRevision === loadedRevision
      ) {
        return;
      }

      reloadRequested = true;
      dispose();
      try {
        reload();
      } catch {
        // A reload failure must not trigger repeated attempts or leak listeners.
      }
    } catch {
      // Offline, malformed, and transient local-server responses fail closed.
    } finally {
      checkInFlight = false;
    }
  };

  const onFocus = () => {
    void checkRevision();
  };
  const onVisibilityChange = () => {
    if (browserDocument.visibilityState === "visible") {
      void checkRevision();
    }
  };
  const intervalId = browserWindow.setInterval(() => {
    if (browserDocument.visibilityState === "visible") {
      void checkRevision();
    }
  }, UI_REVISION_INTERVAL_MS);

  browserWindow.addEventListener("focus", onFocus);
  browserDocument.addEventListener("visibilitychange", onVisibilityChange);

  function dispose() {
    if (disposed) {
      return;
    }
    disposed = true;
    browserWindow.clearInterval(intervalId);
    browserWindow.removeEventListener("focus", onFocus);
    browserDocument.removeEventListener("visibilitychange", onVisibilityChange);
  }

  void checkRevision();

  return { dispose };
}
