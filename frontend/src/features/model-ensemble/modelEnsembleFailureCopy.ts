import type { ModelEnsembleWatch } from "../../shared/api/contracts";
import { useEffect, useState } from "react";

export const MODEL_CLEANUP_UNCONFIRMED = "model_ensemble_cleanup_unconfirmed";
export const MODEL_CLEANUP_RECOVERY = "Model process cleanup was not confirmed. Automatic retries are paused. Check that the local model process has stopped, then restart the app before retrying.";

export function watchPauseCopy(watch: ModelEnsembleWatch | null | undefined): string | null {
  if (watch === null || watch === undefined) return null;
  if (watch.last_error_code === MODEL_CLEANUP_UNCONFIRMED || watch.quarantine_reason_code === MODEL_CLEANUP_UNCONFIRMED) {
    return MODEL_CLEANUP_RECOVERY;
  }
  return watch.quarantined === true
    ? "Automatic retries are paused after a local failure. Check the cause before explicitly retrying; existing snapshots are unchanged."
    : null;
}

export function useModelCleanupWarning(watch: ModelEnsembleWatch | null | undefined, directFailure = false): boolean {
  const [observed, setObserved] = useState(false);
  const reported = directFailure || watch?.last_error_code === MODEL_CLEANUP_UNCONFIRMED
    || watch?.quarantine_reason_code === MODEL_CLEANUP_UNCONFIRMED;
  useEffect(() => {
    if (reported) setObserved(true);
  }, [reported]);
  // Stop/404 and old sealed snapshots cannot confirm process cleanup. Keep
  // this warning for the view lifetime; the advised app restart reloads it.
  return reported || observed;
}
