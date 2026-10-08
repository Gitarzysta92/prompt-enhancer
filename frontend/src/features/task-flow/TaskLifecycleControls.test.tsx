import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  PromptEnhancerTransport,
  TaskLifecycleMutationResponse,
} from "../../shared/api/contracts";
import {
  SYNTHETIC_CANDIDATES,
  SYNTHETIC_RUN,
  SYNTHETIC_TASK_LIFECYCLES,
  SYNTHETIC_TASKS,
} from "../../shared/api/syntheticFixtures";
import { projectTaskFlow } from "./taskFlowAdapter";
import type { TaskFlowItem } from "./taskFlowModel";
import { TaskLifecycleControls } from "./TaskLifecycleControls";

type LifecycleTransport = Pick<
  PromptEnhancerTransport,
  "transitionTaskLifecycle" | "correctTaskLifecycle"
>;

const completeIndex = { analysisIndexEnded: true, lifecycleIndexEnded: true } as const;

function confirmedItem(): TaskFlowItem {
  const item = projectTaskFlow(
    {
      candidates: SYNTHETIC_CANDIDATES,
      tasks: SYNTHETIC_TASKS,
      lifecycles: SYNTHETIC_TASK_LIFECYCLES,
      runs: [SYNTHETIC_RUN],
    },
    completeIndex,
  ).find((candidate) => candidate.kind === "confirmed");
  if (item === undefined) throw new Error("Synthetic confirmed task is missing");
  return item;
}

function response(): TaskLifecycleMutationResponse {
  const event = SYNTHETIC_TASK_LIFECYCLES[0].events[1];
  return { event, head_event_id: event.event_id, state: event.resulting_state };
}

describe("TaskLifecycleControls authority capture", () => {
  it("dismisses an unconfirmed command when the authoritative head changes", async () => {
    const base = confirmedItem();
    const unknown: TaskFlowItem = {
      ...base,
      workLifecycle: {
        ...base.workLifecycle!,
        currentState: null,
        headEventId: null,
        eventCount: 0,
        events: [],
        eventsComplete: true,
      },
    };
    const transport: LifecycleTransport = {
      transitionTaskLifecycle: vi.fn(async () => response()),
      correctTaskLifecycle: vi.fn(async () => response()),
    };
    const view = render(
      <TaskLifecycleControls item={unknown} onLifecycleChanged={vi.fn()} transport={transport} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add to backlog" }));
    expect(screen.getByRole("group", { name: "Confirm lifecycle command" })).toBeVisible();

    view.rerender(
      <TaskLifecycleControls item={base} onLifecycleChanged={vi.fn()} transport={transport} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "changed before confirmation",
    );
    expect(screen.queryByRole("button", { name: "Confirm change" })).toBeNull();
    expect(transport.transitionTaskLifecycle).not.toHaveBeenCalled();
  });

  it("aborts and ignores a late response if authority changes in flight", async () => {
    const base = confirmedItem();
    let capturedSignal: AbortSignal | undefined;
    let settle: (() => void) | undefined;
    const onLifecycleChanged = vi.fn();
    const transitionTaskLifecycle = vi.fn<LifecycleTransport["transitionTaskLifecycle"]>(
      async (_taskId, _revision, _head, _state, _key, signal) => {
        capturedSignal = signal;
        return new Promise<TaskLifecycleMutationResponse>((resolve) => {
          settle = () => resolve(response());
        });
      },
    );
    const transport: LifecycleTransport = {
      transitionTaskLifecycle,
      correctTaskLifecycle: vi.fn(async () => response()),
    };
    const view = render(
      <TaskLifecycleControls item={base} onLifecycleChanged={onLifecycleChanged} transport={transport} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm change" }));
    await waitFor(() => expect(transitionTaskLifecycle).toHaveBeenCalledOnce());
    expect(capturedSignal?.aborted).toBe(false);

    const changed: TaskFlowItem = {
      ...base,
      workLifecycle: {
        ...base.workLifecycle!,
        currentState: "done",
        headEventId: "a".repeat(64),
      },
    };
    view.rerender(
      <TaskLifecycleControls item={changed} onLifecycleChanged={onLifecycleChanged} transport={transport} />,
    );
    await waitFor(() => expect(capturedSignal?.aborted).toBe(true));
    expect(screen.getByRole("alert")).toHaveTextContent("changed before confirmation");

    await act(async () => { settle?.(); });
    expect(onLifecycleChanged).not.toHaveBeenCalled();
  });

  it("submits correction against the captured head and exact undo states", async () => {
    const item = confirmedItem();
    const correctTaskLifecycle = vi.fn<LifecycleTransport["correctTaskLifecycle"]>(
      async () => response(),
    );
    const transport: LifecycleTransport = {
      transitionTaskLifecycle: vi.fn(async () => response()),
      correctTaskLifecycle,
    };
    render(
      <TaskLifecycleControls item={item} onLifecycleChanged={vi.fn()} transport={transport} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Undo last work-state receipt" }));
    expect(screen.getByRole("group", { name: "Confirm lifecycle command" })).toHaveTextContent(
      "from In Progress to Backlog",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm change" }));

    await waitFor(() => expect(correctTaskLifecycle).toHaveBeenCalledOnce());
    expect(correctTaskLifecycle).toHaveBeenCalledWith(
      item.sourceId,
      item.workLifecycle!.currentTaskRevision,
      item.workLifecycle!.headEventId,
      "in_progress",
      "backlog",
      expect.stringMatching(/^dashboard-task-lifecycle-/u),
      expect.any(AbortSignal),
    );
  });
});
