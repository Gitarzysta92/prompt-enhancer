import { useEffect, useRef, useState } from "react";
import type {
  PromptEnhancerTransport,
  TaskLifecycleState,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { nextIdempotencyKey } from "../../shared/api/idempotency";
import { titleFromKey } from "../../shared/lib/format";
import type { TaskFlowItem } from "./taskFlowModel";

type LifecycleMutationTransport = Pick<
  PromptEnhancerTransport,
  "transitionTaskLifecycle" | "correctTaskLifecycle"
>;

interface IntentAuthority {
  taskId: string;
  revision: number;
  expectedHeadEventId: string | null;
  currentState: TaskLifecycleState | null;
  key: string;
}

type Intent =
  | (IntentAuthority & { kind: "transition"; state: TaskLifecycleState })
  | {
    kind: "correction";
    taskId: string;
    revision: number;
    expectedHeadEventId: string;
    currentState: TaskLifecycleState | null;
    priorState: TaskLifecycleState | null;
    resultingState: TaskLifecycleState | null;
    key: string;
  };

function nextState(current: TaskLifecycleState | null): TaskLifecycleState | null {
  if (current === null) return "backlog";
  if (current === "backlog") return "in_progress";
  if (current === "in_progress") return "done";
  return null;
}

function stateLabel(value: TaskLifecycleState | null): string {
  return value === null ? "Unknown" : titleFromKey(value);
}

function safeMutationError(reason: unknown): { message: string; conflict: boolean } {
  if (reason instanceof TransportError && reason.status === 409) {
    return {
      message: "The task revision or lifecycle head changed. Reconcile the board before trying again.",
      conflict: true,
    };
  }
  if (reason instanceof TransportError && reason.status === 422) {
    return {
      message: "That lifecycle transition is no longer legal. Reconcile the board before trying again.",
      conflict: true,
    };
  }
  return {
    message: "The local lifecycle command was not confirmed. Retry uses the same idempotency key.",
    conflict: false,
  };
}

/** Explicit local-user commands only. Model and analysis paths have no mutation prop. */
export function TaskLifecycleControls({
  item,
  transport,
  onLifecycleChanged,
}: {
  item: TaskFlowItem;
  transport: LifecycleMutationTransport;
  onLifecycleChanged: (message: string) => void;
}) {
  const [intent, setIntent] = useState<Intent | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  useEffect(() => () => controllerRef.current?.abort(), []);

  const lifecycle = item.workLifecycle;
  useEffect(() => {
    if (intent === null) return;
    if (
      lifecycle === null
      || item.sourceId !== intent.taskId
      || lifecycle.currentTaskRevision !== intent.revision
      || lifecycle.headEventId !== intent.expectedHeadEventId
      || lifecycle.currentState !== intent.currentState
      || lifecycle.authority !== "authoritative"
    ) {
      controllerRef.current?.abort();
      controllerRef.current = null;
      setPending(false);
      setIntent(null);
      setError("The lifecycle changed before confirmation. Review the reconciled state before issuing a new command.");
    }
  }, [intent, item.sourceId, lifecycle]);

  if (
    item.kind !== "confirmed"
    || lifecycle === null
    || lifecycle.authority !== "authoritative"
    || lifecycle.currentTaskRevision === null
  ) return null;

  const authority = lifecycle;
  const forward = nextState(authority.currentState);
  const head = authority.events.at(-1);
  const canCorrect = authority.eventsComplete
    && authority.headEventId !== null
    && head?.event_id === authority.headEventId
    && head.resulting_state === authority.currentState;

  function proposeTransition(state: TaskLifecycleState) {
    setError(null);
    setIntent({
      kind: "transition",
      taskId: item.sourceId,
      revision: authority.currentTaskRevision!,
      expectedHeadEventId: authority.headEventId,
      currentState: authority.currentState,
      state,
      key: nextIdempotencyKey("task-lifecycle"),
    });
  }

  function proposeCorrection() {
    if (!canCorrect || head === undefined) return;
    setError(null);
    setIntent({
      kind: "correction",
      taskId: item.sourceId,
      revision: authority.currentTaskRevision!,
      expectedHeadEventId: authority.headEventId!,
      currentState: authority.currentState,
      priorState: authority.currentState,
      resultingState: head.prior_state,
      key: nextIdempotencyKey("task-lifecycle"),
    });
  }

  async function confirm() {
    if (intent === null || pending) return;
    if (
      item.sourceId !== intent.taskId
      || authority.currentTaskRevision !== intent.revision
      || authority.headEventId !== intent.expectedHeadEventId
      || authority.currentState !== intent.currentState
    ) {
      setIntent(null);
      setError("The lifecycle changed before confirmation. Review the reconciled state before issuing a new command.");
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPending(true);
    setError(null);
    try {
      if (intent.kind === "transition") {
        await transport.transitionTaskLifecycle(
          intent.taskId,
          intent.revision,
          intent.expectedHeadEventId,
          intent.state,
          intent.key,
          controller.signal,
        );
      } else {
        await transport.correctTaskLifecycle(
          intent.taskId,
          intent.revision,
          intent.expectedHeadEventId,
          intent.priorState,
          intent.resultingState,
          intent.key,
          controller.signal,
        );
      }
      if (!controller.signal.aborted) {
        onLifecycleChanged(
          "Lifecycle command accepted (new receipt or exact safe replay). Reloading all bounded indexes before showing the new board state.",
        );
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        const safe = safeMutationError(reason);
        setError(safe.message);
        if (safe.conflict) {
          onLifecycleChanged(`${safe.message} Reloading all bounded indexes now.`);
        }
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  const proposedState = intent?.kind === "transition"
    ? intent.state
    : intent?.kind === "correction"
      ? intent.resultingState
      : null;

  return (
    <section aria-label={`${item.title} lifecycle commands`} className="task-lifecycle-controls">
      <p className="task-lifecycle-controls__authority">Explicit local-user receipt · analysis cannot invoke these controls</p>
      {intent === null ? (
        <div className="task-lifecycle-controls__actions">
          {forward !== null && (
            <button
              className="button button--primary button--compact"
              onClick={() => proposeTransition(forward)}
              type="button"
            >
              {forward === "backlog" ? "Add to backlog" : forward === "in_progress" ? "Start work" : "Mark done"}
            </button>
          )}
          {canCorrect && (
            <button
              className="button button--secondary button--compact"
              onClick={proposeCorrection}
              type="button"
            >
              Undo last work-state receipt
            </button>
          )}
        </div>
      ) : (
        <div aria-label="Confirm lifecycle command" className="task-lifecycle-controls__confirm" role="group">
          <p>
            Confirm explicit change from <strong>{stateLabel(intent.currentState)}</strong> to <strong>{stateLabel(proposedState)}</strong>?
            This appends a server-timestamped audit receipt; it does not rewrite history.
          </p>
          <div>
            <button className="button button--primary button--compact" disabled={pending} onClick={() => void confirm()} type="button">
              {pending ? "Confirming…" : "Confirm change"}
            </button>
            <button
              className="button button--secondary button--compact"
              disabled={pending}
              onClick={() => { setIntent(null); setError(null); }}
              type="button"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {error !== null && <p className="task-lifecycle-controls__error" role="alert">{error}</p>}
    </section>
  );
}
