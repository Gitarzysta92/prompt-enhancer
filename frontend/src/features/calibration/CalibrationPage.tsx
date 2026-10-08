import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CalibrationProgress,
  CalibrationRating,
  CalibrationReview,
  CalibrationSample,
  CalibrationSampleMember,
  AnnotationAllowance,
  JudgeAgreementReport,
  RemoteAnnotationDisclosure,
  RemoteAnnotationResult,
  JudgeSweepStatus,
  PromptEnhancerTransport,
  RatingLabel,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon } from "../../shared/ui/Icon";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import { CalibrationCasePane } from "./CalibrationCasePane";
import "./CalibrationPage.css";

const RATER_KEY = "prompt-enhancer.calibration.rater";
const LABELS: readonly { value: RatingLabel; title: string; hint: string }[] = [
  { value: "low", title: "Low", hint: "Clearly weak" },
  { value: "medium", title: "Medium", hint: "Mixed or partial" },
  { value: "high", title: "High", hint: "Clearly strong" },
  { value: "cannot_judge", title: "Can't judge", hint: "Not enough to tell" },
];

const METRIC_COPY: Record<string, { title: string; question: string }> = {
  "prompt.task_definition_coverage": {
    title: "Task definition",
    question: "Did the person say clearly what they wanted done - scope, deliverable, done-when?",
  },
  "prompt.context_sufficiency": {
    title: "Context given",
    question: "Did the prompts carry the context the agent needed (files, constraints, prior decisions) instead of leaving it to guess?",
  },
  "outcome.verification_strategy_adequacy": {
    title: "Verification strategy",
    question: "Was the work checked in a way that fits the change - tests, builds, inspection - before it was called done?",
  },
};

const PSEUDONYM = /^[a-f0-9]{64}$/;
const PROVIDERS = new Set(["codex", "claude_code", "synthetic"]);
const ISO_DATETIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/;
const MAX_SAMPLE_SIZE = 1_000;
const REMOTE_MODEL_ALIAS = /^[A-Za-z0-9][A-Za-z0-9 ._:/+-]{0,119}$/;

type OwnedRequestKind = "load" | "command";
type OwnedRequest = {
  controller: AbortController;
  kind: OwnedRequestKind;
  pending: boolean;
};
type OwnedRequestRef = { current: OwnedRequest | null };

function beginOwnedRequest(ref: OwnedRequestRef, kind: OwnedRequestKind): OwnedRequest | null {
  if (ref.current?.kind === "command" && ref.current.pending) return null;
  ref.current?.controller.abort();
  const request = { controller: new AbortController(), kind, pending: true };
  ref.current = request;
  return request;
}

function ownsRequest(ref: OwnedRequestRef, request: OwnedRequest): boolean {
  return ref.current === request && !request.controller.signal.aborted;
}

function finishOwnedRequest(ref: OwnedRequestRef, request: OwnedRequest): void {
  if (ref.current === request) request.pending = false;
}

function cancelOwnedRequest(ref: OwnedRequestRef): void {
  ref.current?.controller.abort();
  ref.current = null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBoundedString(value: unknown, maximumLength: number, allowEmpty = false): value is string {
  return typeof value === "string"
    && Array.from(value).length <= maximumLength
    && (allowEmpty || value.trim().length > 0);
}

function isOptionalBoundedString(value: unknown, maximumLength: number): value is string | null | undefined {
  return value === undefined || value === null || isBoundedString(value, maximumLength, true);
}

function isDateTime(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 64) return false;
  const match = ISO_DATETIME.exec(value);
  if (!match) return false;
  const [year, month, day, hour, minute, second, offsetHour, offsetMinute] = match.slice(1).map(Number);
  if (hour > 23 || minute > 59 || second > 59) return false;
  if ((offsetHour !== undefined && offsetHour > 23) || (offsetMinute !== undefined && offsetMinute > 59)) return false;
  const calendarDate = new Date(0);
  calendarDate.setUTCHours(0, 0, 0, 0);
  calendarDate.setUTCFullYear(year, month - 1, day);
  if (
    calendarDate.getUTCFullYear() !== year
    || calendarDate.getUTCMonth() !== month - 1
    || calendarDate.getUTCDate() !== day
  ) return false;
  return Number.isFinite(Date.parse(value));
}

export function safeRemoteAnnotationDisclosure(value: unknown): value is RemoteAnnotationDisclosure {
  if (!isRecord(value)) return false;
  const activeModel = value.active_model_alias;
  return value.contract_version === "annotation.v1"
    && isBoundedString(value.destination, 2_048)
    && value.redacted_windows_retained === true
    && value.pseudonymous_session_ids_retained === true
    && value.pseudonymous_project_ids_retained === true
    && value.raw_transcripts_sent === false
    && value.model_policy === "configured_active_model_at_submission"
    && (activeModel === null || (typeof activeModel === "string" && REMOTE_MODEL_ALIAS.test(activeModel)));
}

export function safeCalibrationSample(value: unknown): value is CalibrationSample {
  if (!isRecord(value) || value.contract_version !== "calibration-ratings.v1") return false;
  if (
    typeof value.sample_id !== "string" || !PSEUDONYM.test(value.sample_id)
    || !isBoundedString(value.sample_version, 120)
    || !isDateTime(value.created_at)
    || typeof value.target_size !== "number" || !Number.isInteger(value.target_size) || value.target_size < 1 || value.target_size > MAX_SAMPLE_SIZE
    || !Array.isArray(value.metric_keys)
    || !Array.isArray(value.members)
  ) return false;

  const metricKeys = value.metric_keys;
  if (
    metricKeys.length === 0
    || !metricKeys.every((key) => isBoundedString(key, 120) && Object.hasOwn(METRIC_COPY, key))
  ) return false;
  const metricKeySet = new Set(metricKeys);
  if (metricKeySet.size !== metricKeys.length) return false;
  if (value.members.length > value.target_size) return false;

  const positions = new Set<number>();
  const sessionIds = new Set<string>();
  for (const member of value.members) {
    if (!isRecord(member)) return false;
    if (typeof member.position !== "number" || !Number.isInteger(member.position) || member.position < 0) return false;
    if (positions.has(member.position)) return false;
    positions.add(member.position);
    if (typeof member.session_id !== "string" || !PSEUDONYM.test(member.session_id) || sessionIds.has(member.session_id)) return false;
    sessionIds.add(member.session_id);
    if (typeof member.provider !== "string" || !PROVIDERS.has(member.provider)) return false;
    if (typeof member.project_id !== "string" || !PSEUDONYM.test(member.project_id)) return false;
    if (!isOptionalBoundedString(member.project_display_name, 120)) return false;
    if (!isOptionalBoundedString(member.session_display_name, 160)) return false;
    if (member.started_at !== undefined && member.started_at !== null && !isDateTime(member.started_at)) return false;
    if (!Array.isArray(member.rated_metric_keys)) return false;
    if (!member.rated_metric_keys.every((key) => typeof key === "string" && metricKeySet.has(key))) return false;
    if (new Set(member.rated_metric_keys).size !== member.rated_metric_keys.length) return false;
  }
  return true;
}

function memberTitle(member: CalibrationSampleMember): string {
  return member.session_display_name?.trim() || `Session ${member.session_id.slice(0, 8)}`;
}

function memberSubtitle(member: CalibrationSampleMember): string {
  const project = member.project_display_name?.trim() || `Project ${member.project_id.slice(0, 8)}`;
  const when = member.started_at ? new Date(member.started_at).toLocaleString() : "";
  return when ? `${project} · ${when}` : project;
}

/**
 * Blind ratings over a frozen sample of your own sessions. The page never
 * shows model values for the session being rated; ratings are stored locally
 * under a rater pseudonym and export with case provenance, never evidence text.
 */
export function CalibrationPage({
  transport,
}: {
  transport: Pick<
    PromptEnhancerTransport,
    "getCalibrationSample" | "submitCalibrationRatings" | "getCalibrationRatings" | "getCalibrationProgress" | "getCalibrationExport" | "getSessionTranscript" | "reviewCalibrationCase"
  > & Partial<Pick<PromptEnhancerTransport, "judgeSessionWithModel" | "startModelJudgeSweep" | "getModelJudgeSweep" | "getModelJudgeAgreement" | "getAnnotationAllowance" | "setAnnotationAllowance" | "getAnnotationMetaprompt" | "getRemoteAnnotationDisclosure" | "annotateRemotely">>;
}) {
  const [agreement, setAgreement] = useState<JudgeAgreementReport | null>(null);
  const [sweep, setSweep] = useState<JudgeSweepStatus | null>(null);
  const [judgeMessage, setJudgeMessage] = useState("");
  const [allowance, setAllowance] = useState<AnnotationAllowance | null>(null);
  const [annotationMessage, setAnnotationMessage] = useState("");
  const [remoteConfirm, setRemoteConfirm] = useState(false);
  const [remoteBusy, setRemoteBusy] = useState(false);
  const [remoteUncertain, setRemoteUncertain] = useState(false);
  const [remoteDisclosure, setRemoteDisclosure] = useState<RemoteAnnotationDisclosure | null>(null);
  const [remoteDisclosureState, setRemoteDisclosureState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [remoteResult, setRemoteResult] = useState<RemoteAnnotationResult | null>(null);
  const [rater, setRater] = useState<string>(() => {
    try { return localStorage.getItem(RATER_KEY) ?? ""; } catch { return ""; }
  });
  const [draftRater, setDraftRater] = useState(rater);
  const [sample, setSample] = useState<CalibrationSample | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "empty" | "unavailable" | "error">("idle");
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, RatingLabel>>({});
  const [existing, setExisting] = useState<CalibrationRating[]>([]);
  const [progress, setProgress] = useState<CalibrationProgress | null>(null);
  const [saving, setSaving] = useState(false);
  const [sampleRetry, setSampleRetry] = useState(0);
  const [sampleNeedsRefresh, setSampleNeedsRefresh] = useState(false);
  const [judgeBusy, setJudgeBusy] = useState(false);
  const [allowanceBusy, setAllowanceBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [exportText, setExportText] = useState("");
  const [review, setReview] = useState<{ transport: typeof transport; value: CalibrationReview } | null>(null);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  const handleReviewChange = useCallback((value: CalibrationReview | null) => {
    setReview(value ? { transport, value } : null);
    setReviewAcknowledged(false);
  }, [transport]);
  const judgeRequestRef = useRef<OwnedRequest | null>(null);
  const allowanceRequestRef = useRef<OwnedRequest | null>(null);
  const disclosureRequestRef = useRef<OwnedRequest | null>(null);
  const remoteRequestRef = useRef<OwnedRequest | null>(null);
  const remoteCancelRef = useRef<HTMLButtonElement>(null);
  const saveRequestRef = useRef<OwnedRequest | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setState("loading");
    try {
      const value = await transport.getCalibrationSample(rater || null, signal);
      if (signal?.aborted) return;
      if (!safeCalibrationSample(value)) { setState("error"); return; }
      const [ratings, current] = await Promise.all([
        rater ? transport.getCalibrationRatings(rater, signal) : Promise.resolve([] as CalibrationRating[]),
        transport.getCalibrationProgress(signal),
      ]);
      if (signal?.aborted) return;
      setSample(value);
      setExisting(Array.isArray(ratings) ? ratings : []);
      setProgress(current);
      setState(value.members.length === 0 ? "empty" : "ready");
    } catch (caught) {
      if (signal?.aborted) return;
      if (caught instanceof TransportError && caught.status === 409) { setState("empty"); return; }
      if (caught instanceof TransportError && caught.status === 404) { setState("unavailable"); return; }
      setState("error");
    }
  }, [rater, transport]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, sampleRetry]);

  useEffect(() => {
    setSaving(false);
    setMessage("");
    setSampleNeedsRefresh(false);
    setReviewAcknowledged(false);
    return () => cancelOwnedRequest(saveRequestRef);
  }, [rater, transport]);

  const loadJudge = useCallback(async () => {
    if (!transport.getModelJudgeAgreement || !transport.getModelJudgeSweep) return;
    const request = beginOwnedRequest(judgeRequestRef, "load");
    if (!request) return;
    try {
      const [report, status] = await Promise.all([
        transport.getModelJudgeAgreement(request.controller.signal),
        transport.getModelJudgeSweep(request.controller.signal),
      ]);
      if (!ownsRequest(judgeRequestRef, request)) return;
      setAgreement(report);
      setSweep(status);
    } catch {
      /* judge lane absent in this runtime */
    } finally {
      finishOwnedRequest(judgeRequestRef, request);
    }
  }, [transport]);

  const loadAllowance = useCallback(async () => {
    if (!transport.getAnnotationAllowance) return;
    const request = beginOwnedRequest(allowanceRequestRef, "load");
    if (!request) return;
    try {
      const current = await transport.getAnnotationAllowance(request.controller.signal);
      if (ownsRequest(allowanceRequestRef, request)) setAllowance(current);
    } catch {
      if (ownsRequest(allowanceRequestRef, request)) setAllowance(null);
    } finally {
      finishOwnedRequest(allowanceRequestRef, request);
    }
  }, [transport]);

  const loadRemoteDisclosure = useCallback(async () => {
    setRemoteDisclosure(null);
    if (!transport.getRemoteAnnotationDisclosure) {
      setRemoteDisclosureState("unavailable");
      return;
    }
    const request = beginOwnedRequest(disclosureRequestRef, "load");
    if (!request) return;
    setRemoteDisclosureState("loading");
    try {
      const value = await transport.getRemoteAnnotationDisclosure(request.controller.signal);
      if (!ownsRequest(disclosureRequestRef, request)) return;
      if (!safeRemoteAnnotationDisclosure(value)) {
        setRemoteDisclosure(null);
        setRemoteDisclosureState("unavailable");
        return;
      }
      setRemoteDisclosure(value);
      setRemoteDisclosureState("ready");
    } catch {
      if (ownsRequest(disclosureRequestRef, request)) {
        setRemoteDisclosure(null);
        setRemoteDisclosureState("unavailable");
      }
    } finally {
      finishOwnedRequest(disclosureRequestRef, request);
    }
  }, [transport]);

  useEffect(() => {
    void loadJudge();
    void loadAllowance();
    const handle = window.setInterval(() => {
      void loadJudge();
      void loadAllowance();
    }, 15000);
    return () => {
      window.clearInterval(handle);
      cancelOwnedRequest(judgeRequestRef);
      cancelOwnedRequest(allowanceRequestRef);
    };
  }, [loadAllowance, loadJudge]);

  useEffect(() => {
    void loadRemoteDisclosure();
    return () => cancelOwnedRequest(disclosureRequestRef);
  }, [loadRemoteDisclosure]);

  useEffect(() => {
    setAgreement(null);
    setSweep(null);
    setJudgeMessage("");
    setAllowance(null);
    setAnnotationMessage("");
    setRemoteBusy(false);
    setRemoteUncertain(false);
    setRemoteConfirm(false);
    setRemoteResult(null);
    setJudgeBusy(false);
    setAllowanceBusy(false);
    return () => cancelOwnedRequest(remoteRequestRef);
  }, [transport]);

  async function judgeCurrent() {
    if (!current || !transport.judgeSessionWithModel) return;
    const request = beginOwnedRequest(judgeRequestRef, "command");
    if (!request) return;
    setJudgeBusy(true);
    setJudgeMessage("");
    try {
      const outcome = await transport.judgeSessionWithModel(current.session_id, request.controller.signal);
      if (!ownsRequest(judgeRequestRef, request)) return;
      setJudgeMessage(outcome.raw_valid ? `Model judged this session (${outcome.model_alias}); your own rating stays blind to it.` : "The model did not answer in the required format.");
      setJudgeBusy(false);
      finishOwnedRequest(judgeRequestRef, request);
      await loadJudge();
    } catch (caught) {
      if (ownsRequest(judgeRequestRef, request)) {
        setJudgeMessage(caught instanceof TransportError && (caught.reasonCode === "no_active_model" || caught.reasonCode === "model_not_active")
          ? "No local model is active - activate one on the Models page."
          : caught instanceof TransportError && caught.reasonCode === "model_reply_invalid"
          ? "The model returned an incomplete or invalid reply. Existing judgments were kept. Try again."
          : "The model judge is not available right now.");
      }
    } finally {
      if (ownsRequest(judgeRequestRef, request)) setJudgeBusy(false);
      finishOwnedRequest(judgeRequestRef, request);
    }
  }

  async function judgeSample(scope: "sample" | "all" = "sample") {
    if (!transport.startModelJudgeSweep) return;
    const request = beginOwnedRequest(judgeRequestRef, "command");
    if (!request) return;
    setJudgeBusy(true);
    setJudgeMessage("");
    try {
      const status = await transport.startModelJudgeSweep(request.controller.signal, scope);
      if (!ownsRequest(judgeRequestRef, request)) return;
      setSweep(status);
      setJudgeMessage(status.total === 0 ? (scope === "all" ? "Every indexed session is already judged by this model." : "Every sampled session is already judged by this model.") : `Judging ${status.total} sessions in the background.`);
    } catch (caught) {
      if (ownsRequest(judgeRequestRef, request)) {
        setJudgeMessage(caught instanceof TransportError && (caught.reasonCode === "no_active_model" || caught.reasonCode === "model_not_active") ? "No local model is active - activate one on the Models page." : "The model judge is not available right now.");
      }
    } finally {
      if (ownsRequest(judgeRequestRef, request)) setJudgeBusy(false);
      finishOwnedRequest(judgeRequestRef, request);
    }
  }

  const members = sample?.members ?? [];
  const metricKeys = sample?.metric_keys ?? [];
  const current = useMemo(() => members.find((member) => member.session_id === selected) ?? null, [members, selected]);
  const currentReview = review?.transport === transport && review.value.session_id === current?.session_id ? review.value : null;
  const nextUnrated = useMemo(
    () => members.find((member) => member.rated_metric_keys.length < metricKeys.length) ?? null,
    [members, metricKeys.length],
  );

  useEffect(() => {
    if (!current) { setDraft({}); return; }
    const mine: Record<string, RatingLabel> = {};
    for (const rating of existing) {
      if (rating.session_id === current.session_id) mine[rating.metric_key] = rating.label;
    }
    setDraft(mine);
  }, [current, existing]);

  function commitRater() {
    const value = draftRater.trim();
    try { localStorage.setItem(RATER_KEY, value); } catch { /* ignore */ }
    setRater(value);
  }

  async function save(advance: boolean) {
    if (!current || !rater || !currentReview || !reviewAcknowledged || Object.keys(draft).length === 0) return;
    const request = beginOwnedRequest(saveRequestRef, "command");
    if (!request) return;
    setSaving(true);
    setMessage("");
    setSampleNeedsRefresh(false);
    let saved = false;
    try {
      const result = await transport.submitCalibrationRatings({ rater_label: rater, session_id: current.session_id, ratings: draft, review_id: currentReview.review_id }, request.controller.signal);
      if (!ownsRequest(saveRequestRef, request)) return;
      saved = true;
      setProgress(result);
      const [refreshed, ratings] = await Promise.all([
        transport.getCalibrationSample(rater, request.controller.signal),
        transport.getCalibrationRatings(rater, request.controller.signal),
      ]);
      if (!ownsRequest(saveRequestRef, request)) return;
      if (!safeCalibrationSample(refreshed) || !Array.isArray(ratings)) throw new Error("invalid calibration refresh");
      setSample(refreshed);
      setExisting(ratings);
      setMessage("Saved.");
      if (advance) {
        const after = refreshed.members
          .find((member) => member.session_id !== current.session_id && member.rated_metric_keys.length < metricKeys.length);
        setSelected(after ? after.session_id : null);
      }
    } catch (error) {
      if (ownsRequest(saveRequestRef, request)) {
        if (!saved && error instanceof TransportError && error.reasonCode?.startsWith("calibration_review_")) {
          handleReviewChange(null);
          setMessage("The review receipt could not be confirmed. Your draft is still here. Refresh and review the case again before saving.");
          return;
        }
        setSampleNeedsRefresh(true);
        setMessage(saved
          ? "Saved, but the updated sample could not be loaded. Retry the sample to see the saved ratings."
          : "Could not confirm the save. Retry the sample to check the stored ratings before saving again.");
      }
    } finally {
      if (ownsRequest(saveRequestRef, request)) setSaving(false);
      finishOwnedRequest(saveRequestRef, request);
    }
  }

  async function exportRatings() {
    try {
      const value = await transport.getCalibrationExport();
      setExportText(JSON.stringify(value, null, 2));
    } catch {
      setExportText("");
      setMessage("Export is unavailable right now.");
    }
  }

  const ratedCount = members.filter((member) => member.rated_metric_keys.length >= metricKeys.length && metricKeys.length > 0).length;

  const toggleAllowance = async () => {
    if (!transport.setAnnotationAllowance || !allowance) return;
    const request = beginOwnedRequest(allowanceRequestRef, "command");
    if (!request) return;
    setAllowanceBusy(true);
    try {
      const current = await transport.setAnnotationAllowance(!allowance.agent_allowed, request.controller.signal);
      if (ownsRequest(allowanceRequestRef, request)) {
        setAllowance(current);
        setAnnotationMessage("");
      }
    } catch (error) {
      if (ownsRequest(allowanceRequestRef, request)) {
        setAnnotationMessage("Could not update the allowance. The last confirmed setting is still shown.");
      }
    } finally {
      if (ownsRequest(allowanceRequestRef, request)) setAllowanceBusy(false);
      finishOwnedRequest(allowanceRequestRef, request);
    }
  };

  const copyAgentInstructions = async () => {
    if (!transport.getAnnotationMetaprompt) return;
    try {
      const meta = await transport.getAnnotationMetaprompt();
      const base = window.location.origin;
      const text = [
        "Annotate my coding-agent sessions through the Prompt Enhancer API.",
        `Base URL: ${base} - send the app token from api.token (in the Prompt Enhancer home folder) as the X-Prompt-Enhancer-Token header on every request.`,
        "",
        "1. GET /v1/annotation/metaprompt - read the system prompt, the questions and the allowed labels.",
        "2. GET /v1/annotation/work?model=<your-model-name> - session ids you have not annotated yet.",
        "3. For each id: GET /v1/annotation/work/{session_id} - the redacted transcript window plus window_fingerprint, case_fingerprint and case_version.",
        "4. Judge only what the window shows, then POST /v1/annotation/annotations with",
        '   {"session_id": "<id>", "model_name": "<your-model-name>", "window_fingerprint": "<from step 3>", "case_fingerprint": "<from step 3>", "case_version": "<from step 3>", "labels": {"<metric_key>": "<label>"}}.',
        "   Echo the fingerprint unchanged; if the session has grown since you read it the submission is refused, so re-read the window and judge it again.",
        "",
        `System prompt to follow:\n${meta.system_prompt}`,
        "",
        "Questions:",
        ...Object.entries(meta.questions).map(([key, question]) => `- ${key}: ${question}`),
        "",
        `Allowed labels: ${meta.labels.join(", ")}. ${meta.reply_format}`,
      ].join("\n");
      await navigator.clipboard.writeText(text);
      setAnnotationMessage("Agent instructions copied - paste them into Codex, Claude Code, or any agent you drive.");
    } catch {
      setAnnotationMessage("Could not copy the instructions. Check clipboard access and try again.");
    }
  };

  const annotateRemotely = async () => {
    if (!transport.annotateRemotely || !remoteDisclosure?.active_model_alias || remoteUncertain) return;
    const request = beginOwnedRequest(remoteRequestRef, "command");
    if (!request) return;
    setRemoteBusy(true);
    setAnnotationMessage("");
    try {
      const result = await transport.annotateRemotely(5, request.controller.signal);
      if (!ownsRequest(remoteRequestRef, request)) return;
      setRemoteResult(result);
      setRemoteConfirm(false);
      setAnnotationMessage(
        result.submitted === 0
          ? "Nothing left to submit - every session already has a central annotation."
          : `Sent ${result.submitted} session${result.submitted === 1 ? "" : "s"} to ${result.destination}; ${result.annotated} annotated by ${result.model_identity ?? "the central model"}.`,
      );
      void loadJudge();
    } catch {
      if (ownsRequest(remoteRequestRef, request)) {
        setRemoteUncertain(true);
        setAnnotationMessage("Remote annotation could not be confirmed. Check the annotation status before submitting again.");
      }
    } finally {
      if (ownsRequest(remoteRequestRef, request)) setRemoteBusy(false);
      finishOwnedRequest(remoteRequestRef, request);
    }
  };

  const closeRemoteConfirm = () => {
    if (!remoteBusy) setRemoteConfirm(false);
  };

  return (
    <section aria-labelledby="calibration-title" className="calibration">
      <header className="calibration__head route-header">
        <div>
          <p className="eyebrow">Calibration · your own sessions, rated blind</p>
          <h1 id="calibration-title">Rate sessions</h1>
          <p className="calibration__lede">
            Review the bounded case, answer three questions, move on. Model values are hidden here on purpose; your
            answers are the human reference the metrics are later checked against. Ratings and exports stay on this
            machine; only the separate, explicit remote annotation action below crosses the disclosed boundary.
          </p>
        </div>
        <div className="calibration__rater">
          <label>
            <span>Rater name (kept local; stored as a pseudonym)</span>
            <input
              aria-label="Rater name"
              disabled={saving}
              onBlur={commitRater}
              onChange={(event) => setDraftRater(event.currentTarget.value)}
              onKeyDown={(event) => { if (event.key === "Enter") commitRater(); }}
              placeholder="for example Alex"
              type="text"
              value={draftRater}
            />
          </label>
          {progress && (
            <p className="calibration__progress" aria-live="polite">
              {ratedCount} of {members.length} sessions fully rated · {progress.rater_count} rater{progress.rater_count === 1 ? "" : "s"}
            </p>
          )}
        </div>
      </header>

      {state === "loading" && <p className="calibration__note">Drawing the sample…</p>}
      {state === "empty" && (
        <p className="calibration__note">No sessions are indexed yet. Load your projects first (Discovery → first run), then come back.</p>
      )}
      {state === "unavailable" && <p className="calibration__note">Calibration is not available in this runtime.</p>}
      {state === "error" && <p className="calibration__note" role="alert">The sample could not be verified.</p>}
      {(state === "error" || sampleNeedsRefresh) && <button className="button button--ghost" disabled={saving} onClick={() => { setMessage(""); setSampleNeedsRefresh(false); setSampleRetry((value) => value + 1); }} type="button">Retry sample</button>}
      {message && <p className="calibration__message" role="status">{message}</p>}

      {state === "ready" && (
        <div className="calibration__body">
          <aside className="calibration__list" aria-label="Calibration sample">
            <div className="calibration__list-head">
              <span>{members.length} sessions · frozen sample</span>
              {nextUnrated && (
                <button className="button button--ghost" disabled={saving} onClick={() => { setMessage(""); setSelected(nextUnrated.session_id); }} type="button">
                  Next unrated
                </button>
              )}
            </div>
            <ol>
              {members.map((member) => {
                const done = metricKeys.length > 0 && member.rated_metric_keys.length >= metricKeys.length;
                const partial = !done && member.rated_metric_keys.length > 0;
                return (
                  <li key={member.session_id}>
                    <button
                      aria-current={member.session_id === selected ? "true" : undefined}
                      className={member.session_id === selected ? "is-selected" : ""}
                      data-state={done ? "done" : partial ? "partial" : "todo"}
                      disabled={saving}
                      onClick={() => { setMessage(""); setSelected(member.session_id); }}
                      type="button"
                    >
                      <span className="calibration__item-title">{memberTitle(member)}</span>
                      <span className="calibration__item-sub">
                        <ProviderBadge provider={member.provider} />
                        {memberSubtitle(member)}
                      </span>
                      <span className="calibration__item-state">
                        {done ? <Icon name="check" /> : partial ? `${member.rated_metric_keys.length}/${metricKeys.length}` : ""}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </aside>

          <div className="calibration__main">
            {!current && (
              <p className="calibration__note">Pick a session on the left{nextUnrated ? " or use “Next unrated”" : ""}.</p>
            )}
            {current && (
              <>
                <h2 className="calibration__session-title">{memberTitle(current)}</h2>
                <CalibrationCasePane sessionId={current.session_id} provider={current.provider} transport={transport} disabled={saving} onReviewChange={handleReviewChange} />
                <form
                  className="calibration__form"
                  onSubmit={(event) => { event.preventDefault(); void save(true); }}
                >
                  {!rater && (
                    <p className="calibration__note" role="alert">Enter a rater name above before saving; it is stored only as a pseudonym.</p>
                  )}
                  {metricKeys.map((metricKey) => {
                    const copy = METRIC_COPY[metricKey] ?? { title: metricKey, question: metricKey };
                    return (
                      <fieldset key={metricKey} className="calibration__metric" disabled={saving}>
                        <legend>
                          <strong>{copy.title}</strong>
                          <span>{copy.question}</span>
                        </legend>
                        <div className="calibration__choices" role="radiogroup" aria-label={copy.title}>
                          {LABELS.map((label) => (
                            <label key={label.value} className={draft[metricKey] === label.value ? "is-chosen" : ""}>
                              <input
                                checked={draft[metricKey] === label.value}
                                name={metricKey}
                                onChange={() => setDraft((previous) => ({ ...previous, [metricKey]: label.value }))}
                                type="radio"
                                value={label.value}
                              />
                              <span>{label.title}</span>
                              <small>{label.hint}</small>
                            </label>
                          ))}
                        </div>
                      </fieldset>
                    );
                  })}
                  <label className="calibration__review-ack">
                    <input type="checkbox" checked={reviewAcknowledged} disabled={saving || !currentReview} onChange={(event) => setReviewAcknowledged(event.currentTarget.checked)} />
                    I reviewed this case; my ratings describe only the evidence shown.
                  </label>
                  {existing.some((rating) => rating.session_id === current.session_id && rating.case_fingerprint !== currentReview?.case_fingerprint) && <p className="calibration__note">Previously saved labels may describe different or unverified evidence. Confirm each answer against this case before saving a new revision.</p>}
                  <div className="calibration__actions">
                    <button className="button button--primary" disabled={saving || sampleNeedsRefresh || !rater || !currentReview || !reviewAcknowledged || Object.keys(draft).length === 0} type="submit">
                      {saving ? "Saving…" : "Save and next"}
                    </button>
                    <button className="button button--ghost" disabled={saving || sampleNeedsRefresh || !rater || !currentReview || !reviewAcknowledged || Object.keys(draft).length === 0} onClick={() => void save(false)} type="button">
                      Save
                    </button>
                  </div>
                </form>
              </>
            )}
          </div>
        </div>
      )}

      {state === "ready" && agreement && (
        <section aria-labelledby="model-judge-title" className="calibration__judge">
          <div className="calibration__judge-head">
            <div>
              <p className="eyebrow">Model judge · experimental, never a product metric</p>
              <h2 id="model-judge-title">How often does the local model agree with you?</h2>
              <p className="calibration__note">
                {agreement.model_alias ? `Active model: ${agreement.model_alias} · ${agreement.judged_sessions} session${agreement.judged_sessions === 1 ? "" : "s"} judged.` : "No local model is active. Activate one on the Models page to compare."}
                {sweep?.running ? ` Sweep running: ${sweep.done}/${sweep.total}${sweep.failed ? ` (${sweep.failed} failed)` : ""}.` : ""}
              </p>
            </div>
            <div className="calibration__actions">
              <button className="button button--ghost" disabled={judgeBusy || !transport.judgeSessionWithModel || !current || !agreement.model_alias || Boolean(sweep?.running)} onClick={() => void judgeCurrent()} type="button">Judge this session</button>
              <button className="button button--ghost" disabled={judgeBusy || !transport.startModelJudgeSweep || !agreement.model_alias || Boolean(sweep?.running)} onClick={() => void judgeSample()} type="button">Judge the whole sample</button>
              <button className="button button--ghost" disabled={judgeBusy || !transport.startModelJudgeSweep || !agreement.model_alias || Boolean(sweep?.running)} onClick={() => void judgeSample("all")} type="button">Judge every session</button>
            </div>
          </div>
          {judgeBusy && <p role="status">Waiting for the local judge…</p>}
          {(agreement.excluded_judgments ?? 0) > 0 && <p className="calibration__note">
            {agreement.excluded_judgments} stored judgment{agreement.excluded_judgments === 1 ? "" : "s"} excluded from current agreement because the protocol, model identity, or reviewed-case identity is not eligible. The labels remain available in the session view; judge again for current-protocol results.
          </p>}
          {(!transport.judgeSessionWithModel || !transport.startModelJudgeSweep) && <p className="calibration__note">Some judge actions are unavailable in this runtime.</p>}
          {agreement.model_identity_ambiguous && <p className="calibration__note">This alias has different recorded model identities. They are not pooled into one agreement result.</p>}
          <div className="calibration__agreement-scroll" tabIndex={0} role="region" aria-label="Calibration agreement table"><table className="calibration__agreement">
            <thead><tr><th>Metric</th><th>Pairs</th><th>Agreement</th><th>Cohen's κ</th><th>State</th></tr></thead>
            <tbody>
              {agreement.metrics.map((m) => (
                <tr key={m.metric_key}>
                  <td>{METRIC_COPY[m.metric_key]?.title ?? m.metric_key}</td>
                  <td>{m.pairs}{Boolean(m.unmatched_ratings || m.abstained_pairs) && <small className="calibration__pair-note">{m.unmatched_ratings ?? 0} unmatched · {m.abstained_pairs ?? 0} abstained</small>}</td>
                  <td>{m.agreement_rate === null || m.agreement_rate === undefined ? "—" : `${Math.round(m.agreement_rate * 100)}%`}</td>
                  <td>{m.cohen_kappa === null || m.cohen_kappa === undefined ? "—" : m.cohen_kappa.toFixed(2)}</td>
                  <td>{m.state.replace(/_/g, " ")}{m.reason ? ` · ${m.reason.replace(/_/g, " ")}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <p className="calibration__note">{agreement.caveat}</p>
          {judgeMessage && <p className="calibration__message" aria-live="polite">{judgeMessage}</p>}
        </section>
      )}

      {state === "ready" && allowance && (
        <section aria-labelledby="annotation-paths-title" className="calibration__judge calibration__annotation">
          <div className="calibration__judge-head">
            <div>
              <p className="eyebrow">More ways to annotate</p>
              <h2 id="annotation-paths-title">Let a model you drive - or the central server - annotate for you</h2>
            </div>
          </div>
          <div className="calibration__annotation-paths">
            <div className="calibration__annotation-path">
              <h3>Your own agents, through this app&apos;s endpoint</h3>
              <p className="calibration__note">{allowance.note}</p>
              <div className="calibration__actions">
                <button className={allowance.agent_allowed ? "button" : "button button--ghost"} disabled={allowanceBusy || !transport.setAnnotationAllowance} onClick={() => void toggleAllowance()} type="button">
                  {allowance.agent_allowed ? "Agent annotation is ON - click to stop" : "Allow agent annotation"}
                </button>
                {allowance.agent_allowed && (
                  <button className="button button--ghost" disabled={!transport.getAnnotationMetaprompt} onClick={() => void copyAgentInstructions()} type="button">
                    Copy agent instructions
                  </button>
                )}
              </div>
              {allowance.agent_allowed && (
                <p className="calibration__note">
                  Paste the instructions into Codex, Claude Code, or a local model chat. Labels come back as <code>agent:&lt;name&gt;</code> judgments in the table above.
                </p>
              )}
            </div>
            <div className="calibration__annotation-path">
              <h3>Annotate remotely on the central server</h3>
              <p className="calibration__note">
                This optional action can send up to 5 not-yet-submitted sessions only after its destination, retained data, and configured active model are disclosed below.
              </p>
              {remoteDisclosureState === "loading" && (
                <p className="calibration__note" role="status">Verifying the remote annotation destination and policy…</p>
              )}
              {remoteDisclosureState === "unavailable" && (
                <div role="alert">
                  <p className="calibration__note">Remote annotation is disabled because its pre-send disclosure could not be verified. Nothing can be sent.</p>
                  <button className="button button--ghost" onClick={() => void loadRemoteDisclosure()} type="button">Retry disclosure</button>
                </div>
              )}
              {remoteDisclosureState === "ready" && remoteDisclosure && (
                <div className="calibration__remote-disclosure">
                  <p className="calibration__note">Destination: <code>{remoteDisclosure.destination}</code>.</p>
                  <p className="calibration__note">
                    It retains redacted windows plus pseudonymous session and project ids as its annotation training dataset. Raw transcripts are not sent.
                  </p>
                  <p className="calibration__note">
                    Model policy: use the model configured and active at submission time.
                    {remoteDisclosure.active_model_alias
                      ? <> Active now: <code>{remoteDisclosure.active_model_alias}</code>.</>
                      : " No model is active there now, so sending is disabled."}
                  </p>
                  {!remoteDisclosure.active_model_alias && (
                    <button className="button button--ghost" onClick={() => void loadRemoteDisclosure()} type="button">
                      Check for an active model
                    </button>
                  )}
                </div>
              )}
              <div className="calibration__actions">
                <button className="button button--ghost" disabled={remoteBusy || remoteUncertain || !transport.annotateRemotely || !remoteDisclosure?.active_model_alias} onClick={() => setRemoteConfirm(true)} type="button">
                  Annotate remotely…
                </button>
              </div>
              <Dialog
                closeLabel="Cancel remote annotation"
                description="Nothing is sent until you explicitly choose Send."
                footer={(
                  <>
                    <button className="button button--ghost" disabled={remoteBusy} onClick={closeRemoteConfirm} ref={remoteCancelRef} type="button">
                      Cancel
                    </button>
                    <button className="button" disabled={remoteBusy || remoteUncertain || !transport.annotateRemotely || !remoteDisclosure?.active_model_alias} onClick={() => void annotateRemotely()} type="button">
                      {remoteBusy ? "Sending…" : "Send"}
                    </button>
                  </>
                )}
                initialFocusRef={remoteCancelRef}
                onClose={closeRemoteConfirm}
                open={remoteConfirm}
                title="Send sessions for remote annotation?"
                tone="danger"
              >
                <div className="calibration__remote-confirmation">
                  {remoteUncertain && <p className="calibration__message" role="alert">{annotationMessage} This view cannot verify whether that batch was accepted. Close this dialog and check the central annotation records before reloading this page for another submission.</p>}
                  <p className="calibration__note">
                    Destination: <code>{remoteDisclosure?.destination}</code>.
                  </p>
                  <p className="calibration__note">
                    Up to 5 not-yet-submitted redacted windows and their pseudonymous session and project ids will be retained as the central annotation training dataset. Raw transcripts are never sent.
                  </p>
                  <p className="calibration__note">
                    The destination uses its configured active model at submission time. Active now: <code>{remoteDisclosure?.active_model_alias}</code>.
                  </p>
                </div>
              </Dialog>
              {remoteResult && remoteResult.stored_locally_as && (
                <p className="calibration__note">Central labels stored locally as <code>{remoteResult.stored_locally_as}</code>.</p>
              )}
            </div>
          </div>
          {annotationMessage && <p className="calibration__message" aria-live="polite">{annotationMessage}</p>}
        </section>
      )}

      {state === "ready" && (
        <footer className="calibration__export">
          <button className="button button--ghost" onClick={() => void exportRatings()} type="button">
            Show export (ratings and case metadata)
          </button>
          <p className="calibration__note">Exports include sensitive pseudonyms and evidence fingerprints, but no evidence text.</p>
          {exportText && (
            <textarea aria-label="Calibration export" readOnly rows={8} value={exportText} />
          )}
        </footer>
      )}
    </section>
  );
}
