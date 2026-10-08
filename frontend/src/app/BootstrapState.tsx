import { ErrorState, LoadingState } from "../shared/ui/AsyncState";

/**
 * Privacy-safe bootstrap states live outside the routed application because a
 * transport or route-overlay import can fail before `App` exists. Never render
 * the caught exception here: it may contain a local path or provider detail.
 */
export function BootstrapLoading() {
  return (
    <div className="app-shell app-shell--live" data-layout="bootstrap-loading">
      <main id="main-content" tabIndex={-1}>
        <LoadingState label="Starting Prompt Enhancer…" />
      </main>
    </div>
  );
}

export function BootstrapFailure({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="app-shell app-shell--live" data-layout="bootstrap-failure">
      <main id="main-content" tabIndex={-1}>
        <ErrorState
          actionLabel="Reload app"
          message="The local interface did not finish loading. No provider error, local path, or session content is shown."
          onRetry={onRetry}
          title="Prompt Enhancer could not start"
        />
      </main>
    </div>
  );
}
