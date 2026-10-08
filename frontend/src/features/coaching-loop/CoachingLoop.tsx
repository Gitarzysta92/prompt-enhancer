import { useEffect, useMemo, useRef, useState } from "react";
import { StatusPill, type PillTone } from "../../shared/ui/StatusPill";
import {
  createContentFreeShareSummary,
  type CoachingAvailability,
  type CoachingInsight,
  type CoachingLoopViewModel,
  type CoachingOutcomeStatus,
  type CoachingShareSummary,
  type CoachingSignalCategory,
  type CoachingUnavailableReasonCode,
  type ImprovedPromptTemplateCode,
} from "./coachingLoopModel";
import "./CoachingLoop.css";

const UNASSESSED_OUTCOME_COPY: Record<
  Extract<CoachingOutcomeStatus, "unknown" | "abstained" | "not-applicable">,
  { label: string; tone: PillTone }
> = {
  unknown: { label: "Outcome unknown", tone: "unknown" },
  abstained: { label: "Outcome not assessed", tone: "info" },
  "not-applicable": { label: "Not applicable", tone: "neutral" },
};

const TASK_TYPE_COPY: Record<
  CoachingLoopViewModel["assessment"]["taskType"],
  string
> = {
  implementation: "Implementation",
  diagnosis: "Diagnosis",
  planning: "Planning",
  research: "Research",
  review: "Review",
  other: "Other",
};

const EVIDENCE_TIER_COPY: Record<
  CoachingLoopViewModel["assessment"]["evidenceTier"],
  string
> = {
  objective: "Objective evidence",
  mixed: "Mixed evidence",
  "text-only": "Text evidence only",
  unknown: "Evidence tier unknown",
  abstained: "Evidence tier not assessed",
};

const METHOD_COPY: Record<
  CoachingLoopViewModel["assessment"]["methodCode"],
  string
> = {
  "workflow-comparison-v1": "Workflow comparison v1",
  "deterministic-candidates-v1": "Deterministic candidates v1",
  "human-rubric-v1": "Human rubric v1",
};

const LIMITATION_COPY: Record<
  CoachingLoopViewModel["details"]["limitationCode"],
  string
> = {
  "single-task-candidate":
    "This candidate describes one task and does not estimate personal ability.",
  "partial-evidence":
    "Only available evidence classes were assessed; missing evidence was not scored as zero.",
  "human-review-required":
    "A human review is required before this candidate can be treated as calibrated.",
};

const PROVENANCE_COPY: Record<
  CoachingLoopViewModel["details"]["provenanceCode"],
  string
> = {
  "synthetic-local-v1": "Synthetic local analyzer v1",
  "local-versioned-run": "Versioned local analysis run",
  "human-reviewed-run": "Versioned human-reviewed run",
};

const UNAVAILABLE_REASON_COPY: Record<CoachingUnavailableReasonCode, string> = {
  "evidence-missing": "The required evidence source was not available.",
  "insufficient-coverage": "The available evidence did not meet the minimum coverage rule.",
  "unsupported-task": "The active method does not support this task type.",
  "not-observed": "The required workflow event was not observed in the bounded analysis.",
  "method-abstained": "The method declined to produce this observation.",
  "not-applicable-task": "This observation does not apply to the detected task type.",
};

const AVAILABILITY_COPY: Record<
  Exclude<CoachingAvailability, "available">,
  { label: string; description: string; symbol: string }
> = {
  unknown: {
    label: "Unknown",
    description: "Required evidence is unavailable.",
    symbol: "?",
  },
  abstained: {
    label: "Abstained",
    description: "The analyzer deliberately made no judgment.",
    symbol: "—",
  },
  "not-applicable": {
    label: "Not applicable",
    description: "This observation is outside the task profile.",
    symbol: "×",
  },
};

interface CategoryCopy {
  strengthTitle: string;
  strengthSummary: string;
  frictionTitle: string;
  frictionSummary: string;
  experimentTitle: string;
  experimentAction: string;
  experimentSuccess: string;
  experimentGuardrail: string;
}

const CATEGORY_COPY: Record<CoachingSignalCategory, CategoryCopy> = {
  "task-framing": {
    strengthTitle: "Task-framing signals were present",
    strengthSummary: "The bounded analysis found action, target, or outcome cues before execution.",
    frictionTitle: "Task framing needs review",
    frictionSummary: "The bounded analysis did not connect every expected framing cue to the task start.",
    experimentTitle: "Frame the task before execution",
    experimentAction: "State the action, target, and observable end state before implementation begins.",
    experimentSuccess: "The first plan references the same action, target, and end state.",
    experimentGuardrail: "Do not pad a short follow-up by restating context that is already authoritative and unambiguous.",
  },
  "acceptance-criteria": {
    strengthTitle: "Acceptance signals appeared early",
    strengthSummary: "The bounded analysis found an observable pass condition before implementation.",
    frictionTitle: "Acceptance timing needs review",
    frictionSummary: "The bounded analysis found acceptance evidence only after implementation had started.",
    experimentTitle: "Put one acceptance check first",
    experimentAction: "State one observable pass condition before implementation begins.",
    experimentSuccess: "The first verification attempt uses that same condition.",
    experimentGuardrail: "Do not optimize one easy check while leaving other accepted requirements uncovered.",
  },
  clarification: {
    strengthTitle: "Clarification was observable",
    strengthSummary: "The bounded analysis found a question followed by a related answer before execution.",
    frictionTitle: "An unresolved question needs review",
    frictionSummary: "The bounded analysis found a material question without a related resolution.",
    experimentTitle: "Resolve one material uncertainty",
    experimentAction: "Name the highest-impact uncertainty and resolve or explicitly delegate it before execution.",
    experimentSuccess: "The plan records the resulting decision or delegation.",
    experimentGuardrail: "Ask only when the answer can change the path; reversible, low-risk defaults can proceed when stated.",
  },
  "scope-control": {
    strengthTitle: "Scope acknowledgement was observable",
    strengthSummary: "The bounded analysis found a scope change followed by an acknowledgement.",
    frictionTitle: "A scope change needs review",
    frictionSummary: "The bounded analysis found a scope change without an explicit acknowledgement.",
    experimentTitle: "Acknowledge scope changes",
    experimentAction: "Restate the changed boundary before continuing implementation.",
    experimentSuccess: "The next plan reflects the updated boundary.",
    experimentGuardrail: "Do not classify legitimate discovery or a user-requested change as preventable scope failure.",
  },
  verification: {
    strengthTitle: "Objective verification was observable",
    strengthSummary: "The bounded analysis included an objective check rather than a completion claim alone.",
    frictionTitle: "Verification evidence needs review",
    frictionSummary: "The bounded analysis did not find an objective check for the reported result.",
    experimentTitle: "Choose verification before execution",
    experimentAction: "Name the command, test, or observable check that will verify completion.",
    experimentSuccess: "That check is run before completion is reported.",
    experimentGuardrail: "A green but irrelevant check is not success; the evidence must cover the accepted requirement.",
  },
  rework: {
    strengthTitle: "Correction feedback was incorporated",
    strengthSummary: "The bounded analysis found a correction followed by a related change.",
    frictionTitle: "A repeated correction needs review",
    frictionSummary: "The bounded analysis found the same correction category more than once.",
    experimentTitle: "Convert feedback into a constraint",
    experimentAction: "Restate the correction as a constraint before the next revision.",
    experimentSuccess: "The same correction category does not recur in the next comparable step.",
    experimentGuardrail: "Separate misunderstanding from a new requirement, preference, or external change before calling it rework.",
  },
  "exploration-to-plan": {
    strengthTitle: "Exploration connected to a plan",
    strengthSummary: "The bounded analysis linked a hypothesis marker to a later structured action.",
    frictionTitle: "Exploration-to-plan linkage needs review",
    frictionSummary: "The bounded analysis did not link a hypothesis marker to a later structured action.",
    experimentTitle: "Close exploration with one decision",
    experimentAction: "End exploration by recording one chosen hypothesis and its next check.",
    experimentSuccess: "A later plan references the chosen hypothesis and check.",
    experimentGuardrail: "Do not force closure while material evidence is incomplete; record the uncertainty and a reversible next check.",
  },
};

const TEMPLATE_COPY: Record<ImprovedPromptTemplateCode, string> = {
  "acceptance-first":
    "Change [target] so [observable behavior]. Before implementation, confirm this pass condition: [specific check].",
  "clarify-first":
    "Before implementation, identify the highest-impact uncertainty about [target]. Resolve it or state the assumption, then propose the first check.",
  "context-anchor":
    "Work on [artifact] in [environment]. Current state: [state]. Preserve [boundary]. Verify with [specific check].",
  "deliverable-contract":
    "Produce [artifact] in [format] for [audience or interface]. Deliver it at [location] and verify [acceptance condition].",
  "diagnosis-evidence":
    "Diagnose [observed behavior]. Expected: [expected behavior]. Reproduce with [steps] in [environment]. Verify the fix with [specific check].",
  "exploration-to-plan":
    "Explore [question] briefly. Then choose one hypothesis, explain the deciding evidence, and define the next observable check.",
  "hypothesis-test-loop":
    "Observation: [evidence]. Hypothesis: [cause]. Test: [specific check]. Decide using [pass or fail rule].",
  "preflight-contract":
    "Before execution, confirm the goal, in-scope work, excluded work, acceptance check, and expected deliverable.",
  "requirement-plan-map":
    "List each requirement, map it to one plan item, and name the verification evidence expected for that item.",
  "scope-boundary":
    "Update [target] within [included scope]. Exclude [out-of-scope work]. Acknowledge any scope change before continuing.",
  "task-contract":
    "Do [action] to [target]. Current state: [state]. Desired end state: [observable result]. Verify with [specific check].",
  "verification-first":
    "Implement [requested change]. Use [test or command] as the completion check, and report the observed result rather than a completion claim alone.",
};

const SHARE_BLOCK_COPY: Record<
  Extract<CoachingLoopViewModel["sharing"], { status: "blocked" }>["reasonCode"],
  string
> = {
  uncalibrated: "Sharing is blocked because these coaching candidates are not calibrated.",
  "consent-required": "Sharing is blocked until content-free export consent is confirmed.",
  "incoherent-evidence": "Sharing is blocked because the evidence snapshot is not coherent.",
};

function outcomePresentation(
  outcome: CoachingLoopViewModel["outcome"],
): {
  label: string;
  tone: PillTone;
  eyebrow: string;
  question: string;
  summary?: string;
  evidence?: string;
} {
  if (outcome.basis === "none") {
    return {
      ...UNASSESSED_OUTCOME_COPY[outcome.status],
      eyebrow: "Outcome evidence",
      question: "What can be established?",
    };
  }
  if (outcome.basis === "human-reviewed") {
    return {
      label:
        outcome.status === "verified"
          ? "Accepted by reviewer"
          : outcome.status === "failed"
            ? "Not accepted"
            : "Partially accepted",
      tone:
        outcome.status === "verified"
          ? "positive"
          : outcome.status === "failed"
            ? "danger"
            : "warning",
      eyebrow: "Reviewer decision",
      question: "What did the reviewer accept?",
      summary:
        outcome.status === "verified"
          ? "The reviewer accepted the selected result."
          : outcome.status === "failed"
            ? "The reviewer did not accept the selected result."
            : "The reviewer accepted only part of the selected result.",
      evidence: "Explicit human review decision",
    };
  }
  const evidence =
    outcome.evidenceCode === "automated-checks"
      ? "Automated check evidence"
      : outcome.evidenceCode === "acceptance-checks"
        ? "Acceptance-check evidence"
        : "Automated and acceptance-check evidence";
  return {
    label:
      outcome.status === "verified"
        ? "Verification passed"
        : outcome.status === "failed"
          ? "Verification failed"
          : "Verification mixed",
    tone:
      outcome.status === "verified"
        ? "positive"
        : outcome.status === "failed"
          ? "danger"
          : "warning",
    eyebrow: "Verification result",
    question: "What was verified?",
    summary:
      outcome.status === "verified"
        ? "The selected objective checks passed."
        : outcome.status === "failed"
          ? "One or more selected objective checks failed."
          : "The selected objective checks produced mixed results.",
    evidence,
  };
}

function Unavailable({
  reasonCode,
  state,
}: {
  reasonCode: CoachingUnavailableReasonCode;
  state: "unknown" | "abstained" | "not-applicable";
}) {
  const copy = AVAILABILITY_COPY[state];
  const reason = UNAVAILABLE_REASON_COPY[reasonCode];
  return (
    <div
      aria-label={`${copy.label}. ${copy.description} ${reason}`}
      className={`coaching-loop__unavailable coaching-loop__unavailable--${state}`}
      role="note"
    >
      <span aria-hidden="true" className="coaching-loop__state-symbol">{copy.symbol}</span>
      <div>
        <strong>{copy.label}</strong>
        <span>{copy.description}</span>
        <p>{reason}</p>
      </div>
    </div>
  );
}

function InsightCard({
  boundaryLabel,
  insight,
  kind,
  observationLabel,
}: {
  boundaryLabel: string;
  insight: CoachingInsight;
  kind: "strength" | "friction";
  observationLabel: string;
}) {
  const eyebrow = kind === "strength" ? "Observed practice candidate" : "Review candidate";
  const unavailableHeading =
    kind === "strength" ? "No practice candidate available" : "No review candidate available";
  return (
    <article className={`coaching-loop__card coaching-loop__card--${insight.state}`}>
      <p className="coaching-loop__eyebrow">{eyebrow}</p>
      <span className="coaching-loop__card-boundary">{boundaryLabel}</span>
      <h3>
        {insight.state === "available"
          ? kind === "strength"
            ? CATEGORY_COPY[insight.category].strengthTitle
            : CATEGORY_COPY[insight.category].frictionTitle
          : unavailableHeading}
      </h3>
      {insight.state === "available" ? (
        <>
          <p>
            {kind === "strength"
              ? CATEGORY_COPY[insight.category].strengthSummary
              : CATEGORY_COPY[insight.category].frictionSummary}
          </p>
          <small>
            {observationLabel} · {insight.basis === "objective"
              ? "objective evidence"
              : insight.basis === "human-reviewed"
                ? "human reviewed"
                : insight.basis === "mixed"
                  ? "mixed evidence"
                  : "observed text"}
          </small>
        </>
      ) : (
        <Unavailable reasonCode={insight.reasonCode} state={insight.state} />
      )}
    </article>
  );
}

function coverageCopy(model: CoachingLoopViewModel): string {
  const evidence = model.evidence;
  if ("minimumRatio" in evidence) {
    return `${Math.round(evidence.minimumRatio * 100)}% minimum input coverage across ${evidence.candidateCount} selected candidate${evidence.candidateCount === 1 ? "" : "s"}`;
  }
  if (evidence.state === "unknown") return "Evidence coverage unknown";
  if (evidence.state === "abstained") return "Evidence coverage not assessed";
  return "Evidence coverage not applicable";
}

function evidenceDetail(model: CoachingLoopViewModel): string {
  const evidence = model.evidence;
  if ("minimumRatio" in evidence) {
    return evidence.state === "complete"
      ? "Every selected candidate reports complete input coverage."
      : "At least one selected candidate used a partial input window; missing input was not scored as zero.";
  }
  return UNAVAILABLE_REASON_COPY[evidence.reasonCode];
}

export function CoachingLoop({
  model,
  onCopyImprovedPrompt,
  onShareSummary,
}: {
  model: CoachingLoopViewModel;
  onCopyImprovedPrompt?: (template: string) => void;
  onShareSummary?: (summary: CoachingShareSummary) => void;
}) {
  const [shareReviewOpen, setShareReviewOpen] = useState(false);
  const shareButtonRef = useRef<HTMLButtonElement>(null);
  const sharePanelRef = useRef<HTMLDivElement>(null);
  const returnShareFocusRef = useRef(false);
  const modelFingerprint = JSON.stringify(model);
  const previousModelFingerprintRef = useRef(modelFingerprint);
  const outcomeCopy = outcomePresentation(model.outcome);
  const shareSummary = createContentFreeShareSummary(model);
  const sharePayload = useMemo(
    () => (shareSummary ? JSON.stringify(shareSummary, null, 2) : null),
    [shareSummary],
  );
  const shareBlocked = shareSummary === null || onShareSummary === undefined;
  const taskTypeLabel = TASK_TYPE_COPY[model.assessment.taskType];
  const boundaryLabel = `${model.assessment.calibration === "candidate-unvalidated" ? "Candidate · unvalidated" : "Human calibrated"} · ${taskTypeLabel}`;
  const observationLabel =
    model.assessment.calibration === "candidate-unvalidated"
      ? "Candidate observation"
      : "Calibrated observation";
  const shareStatus =
    model.assessment.calibration === "candidate-unvalidated"
      ? "Sharing is blocked because these coaching candidates are not calibrated."
      : model.sharing.status === "blocked"
        ? SHARE_BLOCK_COPY[model.sharing.reasonCode]
        : onShareSummary
          ? "A content-free payload is available. Review its exact fields before sharing."
          : "Sharing is unavailable in this view.";
  const improvedPrompt = model.improvedPrompt;
  const promptTemplate =
    improvedPrompt.state === "available"
      ? TEMPLATE_COPY[improvedPrompt.templateCode]
      : "";

  const closeShareReview = () => {
    returnShareFocusRef.current = true;
    setShareReviewOpen(false);
  };

  useEffect(() => {
    if (shareReviewOpen) sharePanelRef.current?.focus();
  }, [shareReviewOpen]);

  useEffect(() => {
    if (!shareReviewOpen && returnShareFocusRef.current) {
      returnShareFocusRef.current = false;
      shareButtonRef.current?.focus();
    }
  }, [shareReviewOpen]);

  useEffect(() => {
    if (previousModelFingerprintRef.current !== modelFingerprint) {
      previousModelFingerprintRef.current = modelFingerprint;
      if (shareReviewOpen) closeShareReview();
    }
  }, [modelFingerprint, shareReviewOpen]);

  return (
    <section className="coaching-loop" aria-labelledby="coaching-loop-title">
      <header className="coaching-loop__header">
        <div>
          <p className="coaching-loop__eyebrow">Coaching loop</p>
          <h2 id="coaching-loop-title">Make the next task easier</h2>
          <p>Review one evidence-backed candidate and try one observable change.</p>
        </div>
        <div className="coaching-loop__share-action">
          <button
            aria-controls="coaching-share-review"
            aria-describedby="coaching-share-status"
            aria-disabled={shareBlocked}
            aria-expanded={shareReviewOpen}
            className="coaching-loop__share"
            onClick={() => {
              if (!shareBlocked) setShareReviewOpen(true);
            }}
            ref={shareButtonRef}
            type="button"
          >
            Review safe share
          </button>
          <p id="coaching-share-status" role="status">{shareStatus}</p>
        </div>
      </header>

      {shareReviewOpen && shareSummary && sharePayload && onShareSummary && (
        <div
          aria-labelledby="coaching-share-review-title"
          className="coaching-loop__share-review"
          id="coaching-share-review"
          ref={sharePanelRef}
          tabIndex={-1}
        >
          <div>
            <strong id="coaching-share-review-title">Exact content-free payload</strong>
            <p role="status">Ready for explicit review. No prompt text, evidence, counts, IDs, paths, or provenance are included.</p>
          </div>
          <pre aria-label="Exact content-free share payload">{sharePayload}</pre>
          <div className="coaching-loop__share-review-actions">
            <button onClick={closeShareReview} type="button">Cancel</button>
            <button
              onClick={() => {
                onShareSummary(shareSummary);
                closeShareReview();
              }}
              type="button"
            >
              Share this exact payload
            </button>
          </div>
        </div>
      )}

      <div className="coaching-loop__context" aria-label="Assessment boundary">
        <span>
          {model.assessment.calibration === "candidate-unvalidated"
            ? "Candidate · unvalidated"
            : "Human calibrated"}
        </span>
        <span>Task: {taskTypeLabel}</span>
        <span>{EVIDENCE_TIER_COPY[model.assessment.evidenceTier]}</span>
        <span>Method: {METHOD_COPY[model.assessment.methodCode]}</span>
      </div>

      <section
        className={`coaching-loop__outcome coaching-loop__outcome--${model.outcome.status}`}
        aria-labelledby="coaching-outcome-title"
      >
        <div>
          <p className="coaching-loop__eyebrow">{outcomeCopy.eyebrow}</p>
          <h3 id="coaching-outcome-title">{outcomeCopy.question}</h3>
        </div>
        <StatusPill tone={outcomeCopy.tone}>{outcomeCopy.label}</StatusPill>
        {model.outcome.basis === "none" ? (
          <Unavailable
            reasonCode={model.outcome.reasonCode}
            state={model.outcome.status}
          />
        ) : (
          <div className="coaching-loop__outcome-copy">
            <strong>{outcomeCopy.summary}</strong>
            <span>{outcomeCopy.evidence}</span>
            <small>
              {model.outcome.basis === "objective"
                ? "Based on objective verification"
                : "Confirmed by human review"}
            </small>
          </div>
        )}
      </section>

      <div className="coaching-loop__cards" aria-label="Coaching priorities">
        <InsightCard
          boundaryLabel={boundaryLabel}
          insight={model.strength}
          kind="strength"
          observationLabel={observationLabel}
        />
        <InsightCard
          boundaryLabel={boundaryLabel}
          insight={model.friction}
          kind="friction"
          observationLabel={observationLabel}
        />
        <article className={`coaching-loop__card coaching-loop__card--experiment coaching-loop__card--${model.nextExperiment.state}`}>
          <p className="coaching-loop__eyebrow">Try next</p>
          <span className="coaching-loop__card-boundary">{boundaryLabel}</span>
          <h3>
            {model.nextExperiment.state === "available"
              ? CATEGORY_COPY[model.nextExperiment.category].experimentTitle
              : "No experiment available"}
          </h3>
          {model.nextExperiment.state === "available" ? (
            <>
              <p>{CATEGORY_COPY[model.nextExperiment.category].experimentAction}</p>
              <small>
                <strong>Experiment hypothesis · Success:</strong>{" "}
                {CATEGORY_COPY[model.nextExperiment.category].experimentSuccess}
              </small>
              <small className="coaching-loop__experiment-guardrail">
                <strong>Watch for:</strong>{" "}
                {CATEGORY_COPY[model.nextExperiment.category].experimentGuardrail}
              </small>
            </>
          ) : (
            <Unavailable
              reasonCode={model.nextExperiment.reasonCode}
              state={model.nextExperiment.state}
            />
          )}
        </article>
      </div>

      <section className={`coaching-loop__prompt coaching-loop__prompt--${improvedPrompt.state}`} aria-labelledby="coaching-prompt-title">
        <div>
          <p className="coaching-loop__eyebrow">Use next time</p>
          <h3 id="coaching-prompt-title">Template to try</h3>
        </div>
        {improvedPrompt.state === "available" ? (
          <>
            <pre aria-label="Prompt template text">{promptTemplate}</pre>
            {onCopyImprovedPrompt && (
              <button
                className="coaching-loop__copy"
                onClick={() => onCopyImprovedPrompt(promptTemplate)}
                type="button"
              >
                Copy template
              </button>
            )}
          </>
        ) : (
          <Unavailable
            reasonCode={improvedPrompt.reasonCode}
            state={improvedPrompt.state}
          />
        )}
      </section>

      <details className="coaching-loop__details">
        <summary>
          <span>Evidence &amp; method</span>
          <small>{coverageCopy(model)}</small>
        </summary>
        <div className="coaching-loop__details-grid">
          <div>
            <strong>Coverage</strong>
            <span>{evidenceDetail(model)}</span>
          </div>
          <div>
            <strong>Method</strong>
            <span>{METHOD_COPY[model.assessment.methodCode]}</span>
          </div>
          <div>
            <strong>Limitation</strong>
            <span>{LIMITATION_COPY[model.details.limitationCode]}</span>
          </div>
          <div>
            <strong>Provenance</strong>
            <span>{PROVENANCE_COPY[model.details.provenanceCode]}</span>
          </div>
        </div>
      </details>

      <footer className="coaching-loop__boundary">
        {model.assessment.calibration === "candidate-unvalidated"
          ? "Candidate findings are unvalidated. "
          : ""}
        This reviews observable workflow behavior, not intelligence, personality, or developer rank.
      </footer>
    </section>
  );
}
