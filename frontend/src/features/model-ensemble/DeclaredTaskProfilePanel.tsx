import { useEffect, useMemo, useRef, useState } from "react";
import type {
  DeclaredTaskProfile,
  DeclaredTaskProfileCommand,
  DeclaredTaskProfileConstraintKind,
  DeclaredTaskProfileDeliverableSlot,
  ModelEnsembleRun,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import {
  DECLARED_TASK_PROFILE_CONFIRMATION,
  DECLARED_TASK_PROFILE_CONSTRAINT_KINDS,
  DECLARED_TASK_PROFILE_DELIVERABLE_SLOTS,
} from "../../shared/api/declaredTaskProfileContract";
import { nextIdempotencyKey } from "../../shared/api/idempotency";

const CONSTRAINT_LABELS: Record<DeclaredTaskProfileConstraintKind, string> = {
  cost: "Cost",
  delivery: "Delivery",
  performance: "Performance",
  platform: "Platform",
  privacy: "Privacy",
  safety: "Safety",
  scope: "Scope",
  version: "Version",
};
const DELIVERABLE_LABELS: Record<DeclaredTaskProfileDeliverableSlot, string> = {
  artifact: "Artifact",
  audience: "Audience",
  compatibility: "Compatibility",
  format: "Format",
  interface: "Interface",
  location: "Location",
};

interface Draft {
  constraintsConfigured: boolean;
  constraintKinds: DeclaredTaskProfileConstraintKind[];
  outcomeConfigured: boolean;
  expectedOutcomeCount: string;
  deliverablesConfigured: boolean;
  deliverableSlots: DeclaredTaskProfileDeliverableSlot[];
}

function draftFrom(profile: DeclaredTaskProfile | null): Draft {
  return {
    constraintsConfigured: profile?.constraint_kinds !== null && profile?.constraint_kinds !== undefined,
    constraintKinds: profile?.constraint_kinds === null || profile?.constraint_kinds === undefined
      ? []
      : [...profile.constraint_kinds],
    outcomeConfigured: profile?.expected_outcome_count !== null && profile?.expected_outcome_count !== undefined,
    expectedOutcomeCount: String(profile?.expected_outcome_count ?? 1),
    deliverablesConfigured: profile?.deliverable_slots !== null && profile?.deliverable_slots !== undefined,
    deliverableSlots: profile?.deliverable_slots === null || profile?.deliverable_slots === undefined
      ? []
      : [...profile.deliverable_slots],
  };
}

function commandFrom(
  draft: Draft,
  expectedRevision: number | null,
): { command: DeclaredTaskProfileCommand | null; error: string } {
  if (draft.constraintsConfigured && draft.constraintKinds.length === 0) {
    return { command: null, error: "Choose at least one constraint kind, or leave constraints unconfigured." };
  }
  if (draft.deliverablesConfigured && draft.deliverableSlots.length === 0) {
    return { command: null, error: "Choose at least one deliverable slot, or leave deliverables unconfigured." };
  }
  const outcomeCount = Number(draft.expectedOutcomeCount);
  if (
    draft.outcomeConfigured
    && (!Number.isInteger(outcomeCount) || outcomeCount < 1 || outcomeCount > 100)
  ) {
    return { command: null, error: "Expected outcomes must be a whole number from 1 to 100." };
  }
  return {
    command: {
      expected_revision: expectedRevision,
      constraint_kinds: draft.constraintsConfigured ? [...draft.constraintKinds].sort() : null,
      expected_outcome_count: draft.outcomeConfigured ? outcomeCount : null,
      deliverable_slots: draft.deliverablesConfigured ? [...draft.deliverableSlots].sort() : null,
      confirmation: DECLARED_TASK_PROFILE_CONFIRMATION,
    },
    error: "",
  };
}

function sameValues(profile: DeclaredTaskProfile | null, command: DeclaredTaskProfileCommand): boolean {
  return JSON.stringify(profile?.constraint_kinds ?? null) === JSON.stringify(command.constraint_kinds)
    && (profile?.expected_outcome_count ?? null) === command.expected_outcome_count
    && JSON.stringify(profile?.deliverable_slots ?? null) === JSON.stringify(command.deliverable_slots);
}

function statusOf(error: unknown): number | null {
  return typeof error === "object" && error !== null && "status" in error
    && typeof error.status === "number" ? error.status : null;
}

function sealedBindingMatchesProfile(
  binding: ModelEnsembleRun["metric_profile_binding"],
  profile: DeclaredTaskProfile | null,
): boolean {
  return profile !== null
    && binding !== null
    && binding.profile_source === "declared_task_profile"
    && binding.profile_id === profile.profile_id
    && binding.profile_revision === profile.revision
    && binding.profile_fingerprint === profile.profile_fingerprint
    && binding.profile_schema_version === profile.schema_version
    && binding.profile_policy_version === profile.policy_version;
}

type SealedRunContext = "latest_head" | "historical_selection";

function sealedRunLabel(context: SealedRunContext, runId: string): string {
  const shortId = `${runId.slice(0, 8)}…${runId.slice(-4)}`;
  return context === "latest_head"
    ? `latest sealed head ${shortId}`
    : `selected historical seal ${shortId}`;
}

export function DeclaredTaskProfilePanel({
  sessionId,
  sealedRunId,
  sealedRunContext,
  sealedMetricProfileBinding,
  sealedMetricProjectionVersion,
  transport,
}: {
  sessionId: string;
  sealedRunId: string | null;
  sealedRunContext: SealedRunContext;
  sealedMetricProfileBinding: ModelEnsembleRun["metric_profile_binding"];
  sealedMetricProjectionVersion: NonNullable<ModelEnsembleRun["metric_publication_v2"]>["projection_version"] | null;
  transport: PromptEnhancerTransport;
}) {
  const [profile, setProfile] = useState<DeclaredTaskProfile | null>(null);
  const [confirmationAvailable, setConfirmationAvailable] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(null));
  const [loading, setLoading] = useState(true);
  const [loadReady, setLoadReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<DeclaredTaskProfileCommand | null>(null);
  const [savedRevision, setSavedRevision] = useState<number | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const saveController = useRef<AbortController | null>(null);
  const currentSession = useRef(sessionId);
  const conflictReload = useRef(false);

  useEffect(() => {
    if (currentSession.current !== sessionId) conflictReload.current = false;
    currentSession.current = sessionId;
    saveController.current?.abort();
    saveController.current = null;
    setSaving(false);
    setPending(null);
    setSavedRevision(null);
    setProfile(null);
    setConfirmationAvailable(false);
    setDraft(draftFrom(null));
    setLoadReady(false);
    if (!conflictReload.current) setError("");
    const getProfile = transport.getDeclaredTaskProfile;
    if (getProfile === undefined) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    getProfile(sessionId, controller.signal)
      .then((current) => {
        if (controller.signal.aborted || currentSession.current !== sessionId) return;
        setProfile(current.profile);
        setConfirmationAvailable(current.confirmation_available);
        setDraft(draftFrom(current.profile));
        setLoadReady(true);
        if (conflictReload.current) {
          conflictReload.current = false;
          setError("A newer profile revision was saved elsewhere. Review the reloaded values before trying again.");
        }
      })
      .catch((loadError: unknown) => {
        if (controller.signal.aborted || currentSession.current !== sessionId) return;
        setError(statusOf(loadError) === 404
          ? "Reviewed task profiles are not available in this local server version."
          : "The reviewed task profile could not be loaded or validated.");
      })
      .finally(() => {
        if (!controller.signal.aborted && currentSession.current === sessionId) setLoading(false);
      });
    return () => controller.abort();
  }, [reloadToken, sessionId, transport]);

  const candidate = useMemo(
    () => commandFrom(draft, profile?.revision ?? null),
    [draft, profile?.revision],
  );
  const unchanged = candidate.command !== null && sameValues(profile, candidate.command);

  function updateDraft(update: (current: Draft) => Draft) {
    setDraft((current) => update(current));
    setPending(null);
    setSavedRevision(null);
    setError("");
  }

  function toggleConstraint(kind: DeclaredTaskProfileConstraintKind) {
    updateDraft((current) => ({
      ...current,
      constraintKinds: current.constraintKinds.includes(kind)
        ? current.constraintKinds.filter((item) => item !== kind)
        : [...current.constraintKinds, kind].sort(),
    }));
  }

  function toggleDeliverable(slot: DeclaredTaskProfileDeliverableSlot) {
    updateDraft((current) => ({
      ...current,
      deliverableSlots: current.deliverableSlots.includes(slot)
        ? current.deliverableSlots.filter((item) => item !== slot)
        : [...current.deliverableSlots, slot].sort(),
    }));
  }

  function reviewSave() {
    if (!loadReady) return;
    if (candidate.command === null) {
      setError(candidate.error);
      return;
    }
    setError("");
    setPending(candidate.command);
  }

  async function confirmSave() {
    const saveProfile = transport.saveDeclaredTaskProfile;
    if (pending === null || saveProfile === undefined || saving) return;
    const controller = new AbortController();
    const requestedSession = sessionId;
    saveController.current = controller;
    setSaving(true);
    setError("");
    try {
      const outcome = await saveProfile(
        sessionId,
        pending,
        nextIdempotencyKey("declared-task-profile"),
        controller.signal,
      );
      if (controller.signal.aborted || currentSession.current !== requestedSession) return;
      setProfile(outcome.profile);
      setDraft(draftFrom(outcome.profile));
      setPending(null);
      setSavedRevision(outcome.profile.revision);
    } catch (saveError: unknown) {
      if (controller.signal.aborted || currentSession.current !== requestedSession) return;
      if (statusOf(saveError) === 409) {
        setPending(null);
        conflictReload.current = true;
        setReloadToken((current) => current + 1);
      } else {
        setError("The reviewed profile was not saved. No metric authority changed.");
      }
    } finally {
      if (!controller.signal.aborted && currentSession.current === requestedSession) setSaving(false);
      if (saveController.current === controller) saveController.current = null;
    }
  }

  const reviewedProfileProjection = sealedMetricProjectionVersion === "metric-contract-v2-projection-5"
    || sealedMetricProjectionVersion === "metric-contract-v2-projection-6";
  const verifiedCurrent = loadReady
    && sealedRunId !== null
    && reviewedProfileProjection
    && sealedBindingMatchesProfile(sealedMetricProfileBinding, profile);
  const sealedReceipt = sealedRunId === null ? null : sealedRunLabel(sealedRunContext, sealedRunId);

  return (
    <section aria-labelledby="declared-task-profile-title" className="declared-task-profile">
      <header>
        <div>
          <p className="eyebrow">Declared metric denominators</p>
          <h3 id="declared-task-profile-title">Task profile for future sealed analysis</h3>
          <p>
            Configure only facts you can review. Unconfigured families stay unknown;
            this form never turns missing information into a value or applicability claim.
          </p>
          {!confirmationAvailable && loadReady && (
            <p className="declared-task-profile__notice" role="status">
              Saving is disabled: this server has no non-self-issuable user-presence
              adapter. A browser cookie and CSRF token alone cannot authorize metric changes.
            </p>
          )}
        </div>
        <span className="declared-task-profile__revision">
          {profile === null ? "No revision" : `Revision ${profile.revision}`}
        </span>
      </header>

      {loading ? (
        <p className="declared-task-profile__notice" role="status">Loading reviewed task profile…</p>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); reviewSave(); }}>
          <fieldset disabled={saving || !loadReady}>
            <legend>Constraint kinds</legend>
            <label className="declared-task-profile__configure">
              <input
                checked={draft.constraintsConfigured}
                onChange={(event) => updateDraft((current) => ({
                  ...current,
                  constraintsConfigured: event.target.checked,
                }))}
                type="checkbox"
              />
              Configure expected constraint kinds
            </label>
            {draft.constraintsConfigured && (
              <div className="declared-task-profile__choices">
                {DECLARED_TASK_PROFILE_CONSTRAINT_KINDS.map((kind) => (
                  <label key={kind}>
                    <input
                      checked={draft.constraintKinds.includes(kind)}
                      onChange={() => toggleConstraint(kind)}
                      type="checkbox"
                    />
                    {CONSTRAINT_LABELS[kind]}
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          <fieldset disabled={saving || !loadReady}>
            <legend>Acceptance outcomes</legend>
            <label className="declared-task-profile__configure">
              <input
                checked={draft.outcomeConfigured}
                onChange={(event) => updateDraft((current) => ({
                  ...current,
                  outcomeConfigured: event.target.checked,
                }))}
                type="checkbox"
              />
              Configure expected outcome count
            </label>
            {draft.outcomeConfigured && (
              <label className="declared-task-profile__number">
                Expected checkable outcomes
                <input
                  inputMode="numeric"
                  max={100}
                  min={1}
                  onChange={(event) => updateDraft((current) => ({
                    ...current,
                    expectedOutcomeCount: event.target.value,
                  }))}
                  required
                  type="number"
                  value={draft.expectedOutcomeCount}
                />
              </label>
            )}
          </fieldset>

          <fieldset disabled={saving || !loadReady}>
            <legend>Deliverable slots</legend>
            <label className="declared-task-profile__configure">
              <input
                checked={draft.deliverablesConfigured}
                onChange={(event) => updateDraft((current) => ({
                  ...current,
                  deliverablesConfigured: event.target.checked,
                }))}
                type="checkbox"
              />
              Configure expected deliverable slots
            </label>
            {draft.deliverablesConfigured && (
              <div className="declared-task-profile__choices">
                {DECLARED_TASK_PROFILE_DELIVERABLE_SLOTS.map((slot) => (
                  <label key={slot}>
                    <input
                      checked={draft.deliverableSlots.includes(slot)}
                      onChange={() => toggleDeliverable(slot)}
                      type="checkbox"
                    />
                    {DELIVERABLE_LABELS[slot]}
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          {candidate.error && !error && (
            <p className="declared-task-profile__hint">{candidate.error}</p>
          )}
          {error && <p className="declared-task-profile__error" role="alert">{error}</p>}

          {pending === null ? (
            <button
              className="button button--secondary"
              disabled={!loadReady || !confirmationAvailable || loading || saving || unchanged || transport.saveDeclaredTaskProfile === undefined}
              type="submit"
            >
              Review profile change
            </button>
          ) : (
            <div aria-label="Confirm reviewed task profile" className="declared-task-profile__confirmation" role="group">
              <p>
                Save an immutable revision using the exact current revision {pending.expected_revision ?? "none"}?
                This changes measurement authority for future analysis only.
              </p>
              <div>
                <button className="button button--secondary" disabled={saving} onClick={() => setPending(null)} type="button">
                  Keep editing
                </button>
                <button className="button button--primary" disabled={saving} onClick={() => void confirmSave()} type="button">
                  {saving ? "Saving…" : "Confirm reviewed profile"}
                </button>
              </div>
            </div>
          )}
        </form>
      )}

      <p aria-live="polite" className="declared-task-profile__notice" data-profile-publication-status={verifiedCurrent ? "verified_current" : "unverified"} role="status">
        {verifiedCurrent
          ? sealedRunContext === "latest_head"
            ? `Reviewed revision ${profile!.revision} is exactly bound to ${sealedReceipt}. Its three profile-backed metrics are verified current for this profile.`
            : `Reviewed revision ${profile!.revision} is exactly bound to ${sealedReceipt}. Its three profile-backed metrics are verified for this exact profile identity.`
          : savedRevision !== null
          ? sealedRunId === null
            ? `Revision ${savedRevision} is saved. No sealed analysis exists yet; run analysis to create a profile-bound r5/r6 snapshot.`
            : !reviewedProfileProjection
              ? `Revision ${savedRevision} is saved. ${sealedReceipt} has no exact reviewed-profile binding for this profile; run analysis again and wait for a current profile-bound seal.`
              : `Revision ${savedRevision} is saved, but ${sealedReceipt} does not exactly bind its source, schema, revision, and fingerprint. Its three profile-backed metrics remain unverified.`
          : !loadReady
            ? "Profile authority is not loaded. No configuration or metric state is inferred."
          : !confirmationAvailable
            ? "Profile values are read-only. No trusted user-presence adapter is composed, so this browser cannot change metric authority."
          : profile === null
            ? "No profile is configured. Constraint, acceptance, and deliverable denominators remain unknown."
            : sealedRunId === null
              ? `Reviewed revision ${profile.revision} is loaded. No sealed analysis exists yet, so its three profile-backed metrics remain unverified.`
              : !reviewedProfileProjection
                ? `Reviewed revision ${profile.revision} is loaded. ${sealedReceipt} has no exact reviewed-profile binding for this profile, so its three profile-backed metrics remain unverified.`
                : `Reviewed revision ${profile.revision} is loaded, but ${sealedReceipt} does not exactly bind its source, schema, revision, and fingerprint. Its three profile-backed metrics remain unverified.`}
      </p>
    </section>
  );
}
