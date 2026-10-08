import type {
  ModelEnsembleCanonicalHead,
  ModelEnsembleWatchSnapshot,
} from "../../shared/api/contracts";

/** Poll cadence while a durable attempt is running or the lane is queued. */
export const CANONICAL_POLL_ACTIVE_MS = 2_000;
/** Poll cadence while the watch is idle, failed, or absent. */
export const CANONICAL_POLL_IDLE_MS = 15_000;
/** Poll cadence after a transport failure that is not a definitive 404. */
export const CANONICAL_POLL_RETRY_MS = 5_000;
/** Poll cadence after a parser-valid snapshot that does not carry the head run id. */
export const CANONICAL_POLL_WRONG_RUN_MS = 2_000;
/** Consecutive poll failures before the surface reports a disconnection. */
export const CANONICAL_DISCONNECT_FAILURE_COUNT = 3;
/** Elapsed failure window before the surface reports a disconnection. */
export const CANONICAL_DISCONNECT_WINDOW_MS = 10_000;
/** Retry cadence when the trajectory page lags or leads the exact head. */
export const TRAJECTORY_RETRY_MS = 2_000;
/** Bounded retries for a trajectory publication race before waiting for the next head. */
export const TRAJECTORY_RETRY_LIMIT = 5;

export function canonicalHeadPollDelay(head: ModelEnsembleCanonicalHead): number {
  return head.latest_attempt?.state === "running" || head.watch.state === "queued" || head.watch.state === "running"
    ? CANONICAL_POLL_ACTIVE_MS
    : CANONICAL_POLL_IDLE_MS;
}

export function watchSnapshotPollDelay(snapshot: ModelEnsembleWatchSnapshot): number {
  return snapshot.watch.state === "running" || snapshot.watch.state === "queued"
    ? CANONICAL_POLL_ACTIVE_MS
    : CANONICAL_POLL_IDLE_MS;
}

export interface WatchHeadIdentity {
  watch_id: string;
  generation: number;
  head_generation: number | null;
}

export function canonicalHeadIdentity(head: ModelEnsembleCanonicalHead): WatchHeadIdentity {
  return {
    watch_id: head.watch.watch_id,
    generation: head.watch.generation,
    head_generation: head.head_generation,
  };
}

export function watchSnapshotIdentity(snapshot: ModelEnsembleWatchSnapshot): WatchHeadIdentity {
  return {
    watch_id: snapshot.watch.watch_id,
    generation: snapshot.watch.generation,
    head_generation: null,
  };
}

/**
 * A poll result is stale when it describes the same durable watch at an older
 * attempt generation or an older published head than what is already shown.
 * Different watches are never compared; a command result is authoritative and
 * bypasses this guard entirely.
 */
export function isStaleWatchHead(
  current: WatchHeadIdentity | null,
  incoming: WatchHeadIdentity,
): boolean {
  if (current === null || current.watch_id !== incoming.watch_id) return false;
  if (incoming.generation < current.generation) return true;
  return current.head_generation !== null
    && incoming.head_generation !== null
    && incoming.head_generation < current.head_generation;
}

export class PollFailureTracker {
  private failures = 0;
  private firstFailureAt: number | null = null;

  constructor(
    private readonly now: () => number = () => Date.now(),
    private readonly failureCount = CANONICAL_DISCONNECT_FAILURE_COUNT,
    private readonly windowMs = CANONICAL_DISCONNECT_WINDOW_MS,
  ) {}

  /** Records one failed poll and reports whether the disconnection threshold is met. */
  recordFailure(): boolean {
    this.failures += 1;
    this.firstFailureAt ??= this.now();
    return this.failures >= this.failureCount || this.now() - this.firstFailureAt >= this.windowMs;
  }

  reset(): void {
    this.failures = 0;
    this.firstFailureAt = null;
  }

  get consecutiveFailures(): number {
    return this.failures;
  }
}

export interface PollTicket {
  readonly signal: AbortSignal;
  /** False once a newer poll, a command, or unmount superseded this poll. */
  isCurrent(): boolean;
}

interface TimerHost {
  setTimeout(handler: () => void, delay: number): number;
  clearTimeout(handle: number): void;
}

/**
 * Serialises polling against user commands.
 *
 * - Every poll receives a ticket; results are applied only while the ticket is
 *   current, so a response that arrives after a command or a newer poll cannot
 *   overwrite the command's result.
 * - `beginCommand` aborts the in-flight poll and suspends the timer. Polls
 *   requested during the command are deferred, not dropped.
 * - `endCommand` either polls immediately (a failed command must resync with the
 *   server) or schedules the next poll at the cadence implied by the result.
 */
export class PollCoordinator {
  private epoch = 0;
  private controller: AbortController | null = null;
  private timer: number | undefined;
  private stopped = false;
  private commands = 0;
  private pollRequestedDuringCommand = false;

  constructor(
    private readonly poll: (ticket: PollTicket) => Promise<void>,
    private readonly host: TimerHost = {
      setTimeout: (handler, delay) => window.setTimeout(handler, delay),
      clearTimeout: (handle) => window.clearTimeout(handle),
    },
  ) {}

  get commandInFlight(): boolean {
    return this.commands > 0;
  }

  get inFlight(): boolean {
    return this.controller !== null && !this.controller.signal.aborted;
  }

  pollNow(): void {
    if (this.stopped) return;
    this.clearTimer();
    if (this.commands > 0) {
      this.pollRequestedDuringCommand = true;
      return;
    }
    this.invalidate();
    const controller = new AbortController();
    this.controller = controller;
    const epoch = this.epoch;
    const ticket: PollTicket = {
      signal: controller.signal,
      isCurrent: () => !this.stopped && this.epoch === epoch && !controller.signal.aborted,
    };
    void this.poll(ticket).catch(() => undefined).finally(() => {
      if (this.controller === controller) this.controller = null;
    });
  }

  schedule(delayMs: number): void {
    if (this.stopped) return;
    this.clearTimer();
    if (this.commands > 0) {
      this.pollRequestedDuringCommand = true;
      return;
    }
    this.timer = this.host.setTimeout(() => {
      this.timer = undefined;
      this.pollNow();
    }, delayMs);
  }

  beginCommand(): void {
    if (this.stopped) return;
    this.commands += 1;
    this.clearTimer();
    this.invalidate();
  }

  /**
   * Finishes a command. Without a delay the next poll runs immediately so a
   * failed or unconfirmed command resyncs with the server; with a delay the
   * command response is treated as the freshest head and the timer resumes.
   */
  endCommand(delayMs?: number): void {
    if (this.stopped) return;
    this.commands = Math.max(0, this.commands - 1);
    this.invalidate();
    if (this.commands > 0) return;
    const requested = this.pollRequestedDuringCommand;
    this.pollRequestedDuringCommand = false;
    if (requested || delayMs === undefined) {
      this.pollNow();
    } else {
      this.schedule(delayMs);
    }
  }

  stop(): void {
    this.stopped = true;
    this.clearTimer();
    this.invalidate();
  }

  private invalidate(): void {
    this.epoch += 1;
    this.controller?.abort();
    this.controller = null;
  }

  private clearTimer(): void {
    if (this.timer !== undefined) {
      this.host.clearTimeout(this.timer);
      this.timer = undefined;
    }
  }
}

export function httpStatusOf(error: unknown): number | null {
  return typeof error === "object" && error !== null && "status" in error
    && typeof error.status === "number"
    ? error.status
    : null;
}
