import { useEffect, useMemo, useState } from "react";
import type {
  CandidateListItem,
  PromptEnhancerTransport,
  RejectionReason,
  ReviewCommand,
  TaskCategory,
  TaskReviewResponse,
} from "../../shared/api/contracts";
import { candidateTitle } from "../../entities/discovery/model";
import { EvidenceList } from "../../entities/discovery/EvidenceList";
import { formatPercent, shortId, titleFromKey } from "../../shared/lib/format";
import { CoverageBar } from "../../shared/ui/CoverageBar";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";
import { nextIdempotencyKey } from "../../shared/api/idempotency";
import {
  acceptCommand,
  rejectCommand,
  splitCommand,
} from "./reviewCommands";

const taskCategories: TaskCategory[] = [
  "unknown",
  "bug_fix",
  "feature_implementation",
  "research_design",
];
const rejectionReasons: RejectionReason[] = [
  "wrong_grouping",
  "not_a_task",
  "duplicate",
  "other",
];

export function CandidateReviewPanel({
  item,
  transport,
  onReviewed,
}: {
  item: CandidateListItem;
  transport: PromptEnhancerTransport;
  onReviewed: (result: TaskReviewResponse) => Promise<void> | void;
}) {
  const [category, setCategory] = useState<TaskCategory>("unknown");
  const [rejectionReason, setRejectionReason] = useState<RejectionReason>("wrong_grouping");
  const [splitOpen, setSplitOpen] = useState(false);
  const [assignments, setAssignments] = useState<Record<string, "a" | "b">>({});
  const [pendingAction, setPendingAction] = useState<ReviewCommand["action"] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCategory("unknown");
    setRejectionReason("wrong_grouping");
    setSplitOpen(false);
    setError(null);
    setAssignments(
      Object.fromEntries(
        item.candidate.session_ids.map((sessionId, index) => [sessionId, index === 0 ? "a" : "b"]),
      ),
    );
  }, [item.candidate.candidate_id, item.candidate.session_ids]);

  const partitionCounts = useMemo(
    () => ({
      a: Object.values(assignments).filter((group) => group === "a").length,
      b: Object.values(assignments).filter((group) => group === "b").length,
    }),
    [assignments],
  );

  async function submit(command: ReviewCommand) {
    setError(null);
    setPendingAction(command.action);
    try {
      const result = await transport.review(command, nextIdempotencyKey(command.action));
      await onReviewed(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Review could not be saved");
    } finally {
      setPendingAction(null);
    }
  }

  const disabled = item.decision_status === "decided" || pendingAction !== null;
  const confidence = item.candidate.confidence;

  return (
    <aside aria-labelledby="review-panel-heading" className="review-panel">
      <div className="review-panel__header">
        <div>
          <p className="eyebrow">Discovery evidence</p>
          <h2 id="review-panel-heading">{candidateTitle(item.candidate)}</h2>
        </div>
        <StatusPill tone={item.decision_status === "decided" ? "positive" : "warning"}>
          {item.decision_status !== "decided"
            ? "Decision needed"
            : item.decision_source === "automation"
              ? "Auto-accepted (single session)"
              : "Reviewed"}
        </StatusPill>
      </div>

      <p className="review-panel__intro">
        The algorithm proposes a grouping; it does not declare task success or infer task quality.
      </p>

      <dl className="review-facts">
        <div><dt>Sessions</dt><dd>{item.candidate.session_ids.length}</dd></div>
        <div><dt>Confidence</dt><dd>{confidence == null ? "Unknown" : formatPercent(confidence)}</dd></div>
        <div><dt>Project</dt><dd className="mono">{shortId(item.candidate.project_id)}</dd></div>
        <div><dt>Method</dt><dd>{item.candidate.discovery_version}</dd></div>
      </dl>
      <CoverageBar
        coverage={item.candidate.coverage}
        eligible={item.candidate.eligible_count}
        observed={item.candidate.observed_count}
      />

      <section aria-labelledby="signals-heading" className="review-panel__section">
        <div className="section-heading section-heading--small">
          <div>
            <p className="eyebrow">Why this grouping?</p>
            <h3 id="signals-heading">Signals</h3>
          </div>
          <span className="count-badge">{item.candidate.signals.length}</span>
        </div>
        <EvidenceList signals={item.candidate.signals} />
      </section>

      <section aria-labelledby="sessions-heading" className="review-panel__section">
        <div className="section-heading section-heading--small">
          <h3 id="sessions-heading">Pseudonymous sessions</h3>
          <StatusPill><Icon name="lock" /> Content hidden</StatusPill>
        </div>
        <ul className="session-list">
          {item.candidate.session_ids.map((sessionId, index) => (
            <li key={sessionId}>
              <span className="session-index">{index + 1}</span>
              <code>{shortId(sessionId)}</code>
              <span>Metadata only</span>
            </li>
          ))}
        </ul>
      </section>

      {item.decision_status === "undecided" ? (
        <section aria-labelledby="decision-heading" className="decision-panel">
          <div className="section-heading section-heading--small">
            <div>
              <p className="eyebrow">Human label</p>
              <h3 id="decision-heading">Review decision</h3>
            </div>
          </div>
          <label className="field">
            <span>Task category</span>
            <select
              disabled={disabled}
              onChange={(event) => setCategory(event.target.value as TaskCategory)}
              value={category}
            >
              {taskCategories.map((value) => <option key={value} value={value}>{titleFromKey(value)}</option>)}
            </select>
          </label>
          <button
            className="button button--primary button--full"
            disabled={disabled}
            onClick={() => submit(acceptCommand(item, category))}
            type="button"
          >
            <Icon name="check" />
            {pendingAction === "accept" ? "Saving..." : "Accept as one task"}
          </button>

          <div className="decision-panel__secondary">
            <label className="field field--compact">
              <span>Rejection reason</span>
              <select
                disabled={disabled}
                onChange={(event) => setRejectionReason(event.target.value as RejectionReason)}
                value={rejectionReason}
              >
                {rejectionReasons.map((value) => <option key={value} value={value}>{titleFromKey(value)}</option>)}
              </select>
            </label>
            <button
              className="button button--danger-ghost"
              disabled={disabled}
              onClick={() => submit(rejectCommand(item, rejectionReason))}
              type="button"
            >
              <Icon name="x" /> {pendingAction === "reject" ? "Saving..." : "Reject"}
            </button>
          </div>

          {item.candidate.session_ids.length > 1 && (
            <div className="split-panel">
              <button
                aria-expanded={splitOpen}
                className="button button--secondary button--full"
                disabled={disabled}
                onClick={() => setSplitOpen((value) => !value)}
                type="button"
              >
                <Icon name="split" /> Split into two tasks
              </button>
              {splitOpen && (
                <div className="split-panel__body">
                  <p>Assign every session to task A or task B.</p>
                  {item.candidate.session_ids.map((sessionId) => (
                    <label className="split-row" key={sessionId}>
                      <code>{shortId(sessionId)}</code>
                      <select
                        aria-label={`Task group for session ${shortId(sessionId)}`}
                        onChange={(event) =>
                          setAssignments((current) => ({
                            ...current,
                            [sessionId]: event.target.value as "a" | "b",
                          }))
                        }
                        value={assignments[sessionId] ?? "b"}
                      >
                        <option value="a">Task A</option>
                        <option value="b">Task B</option>
                      </select>
                    </label>
                  ))}
                  <button
                    className="button button--primary button--full"
                    disabled={disabled || partitionCounts.a === 0 || partitionCounts.b === 0}
                    onClick={() => {
                      try {
                        void submit(splitCommand(item, assignments));
                      } catch (reason) {
                        setError(reason instanceof Error ? reason.message : "Split is invalid");
                      }
                    }}
                    type="button"
                  >
                    Confirm split ({partitionCounts.a} + {partitionCounts.b})
                  </button>
                </div>
              )}
            </div>
          )}
          {error && <p className="inline-error" role="alert">{error}</p>}
        </section>
      ) : (
        <div className="reviewed-callout">
          <Icon name="check" />
          <div>
            <strong>Decision recorded</strong>
            <p>{titleFromKey(item.decision_action ?? "reviewed")}</p>
          </div>
        </div>
      )}
    </aside>
  );
}
