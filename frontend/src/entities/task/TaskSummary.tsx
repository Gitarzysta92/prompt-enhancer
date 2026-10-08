import type { TaskRevision } from "../../shared/api/contracts";
import { formatTimestamp, shortId, titleFromKey } from "../../shared/lib/format";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";

export function TaskSummary({ task }: { task: TaskRevision }) {
  return (
    <section aria-labelledby="task-summary-heading" className="task-summary">
      <header className="task-summary__identity route-header route-header--task">
        <span className="task-summary__icon"><Icon name="tasks" /></span>
        <div>
          <p className="eyebrow">Reviewed task - revision {task.revision}</p>
          <h1 id="task-summary-heading">{titleFromKey(task.task_type)}</h1>
          <p className="muted mono">{shortId(task.task_id)}</p>
        </div>
      </header>
      <div className="task-summary__facts">
        <div><span>State</span><StatusPill tone="positive">{titleFromKey(task.lifecycle_state)}</StatusPill></div>
        <div><span>Sessions</span><strong>{task.session_ids.length}</strong></div>
        <div><span>Project</span><strong className="mono">{shortId(task.project_id)}</strong></div>
        <div><span>Created</span><strong>{formatTimestamp(task.created_at)}</strong></div>
      </div>
    </section>
  );
}
