import { useEffect, useMemo, useState } from "react";
import type {
  MetricOperabilityCatalog,
  MetricOperabilityEntry,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { MetricOperabilityDefinitionsOutOfDateError } from "../../shared/api/metricOperabilityContract";
import "./MetricOperabilityPanel.css";

type CatalogState =
  | { kind: "loading" }
  | { kind: "ready"; catalog: MetricOperabilityCatalog }
  | { kind: "definitions_out_of_date" }
  | { kind: "unavailable" };

type ShippedState = MetricOperabilityEntry["shipped_path_state"];

const GROUPS: ReadonlyArray<{
  state: ShippedState;
  title: string;
  explanation: string;
}> = [
  {
    state: "available_when_evidence_exists",
    title: "Measured path shipped",
    explanation: "These metrics resolve when the analyzed window contains the required reviewed evidence.",
  },
  {
    state: "task_profile_configuration_required",
    title: "Project profile needed",
    explanation: "Declare the expected constraints, outcomes and deliverables before these denominators exist.",
  },
  {
    state: "provider_adapter_required",
    title: "Unavailable pending provider adapter",
    explanation: "These contracts remain in their exact receipt but cannot produce a current value: the provider must expose typed opportunities, links or outcomes. Model prose cannot substitute for them.",
  },
];

const NEXT_STEP_LABELS: Record<MetricOperabilityEntry["next_step_code"], string> = {
  analyze_focus_request: "Analyze the focus request",
  declare_task_profile: "Review and declare the project task profile",
  confirm_lifecycle_evidence: "Review the lifecycle evidence proposal",
  record_documented_decision: "Record an explicit documented decision or strategy",
  link_plan_supersession: "Link the plan item to the action that superseded it",
  record_task_scoped_verification: "Attach a task-scoped verification receipt",
  add_objective_opportunity_link_adapter: "Add typed opportunity, link and outcome capture",
  add_requirement_plan_extractor: "Add a reviewed requirement-to-plan extractor",
  confirm_requirement_plan_evidence: "Confirm reviewed requirement-to-plan evidence",
  compose_requirement_action_evidence: "Compose and confirm reviewed requirement-to-action evidence",
};

function metricLabel(metricKey: string): string {
  const leaf = metricKey.split(".").at(-1) ?? metricKey;
  const label = leaf.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function StateGroup({
  entries,
  explanation,
  title,
}: {
  entries: readonly MetricOperabilityEntry[];
  explanation: string;
  title: string;
}) {
  return (
    <section className="metric-operability__group">
      <header>
        <span aria-hidden="true">{entries.length}</span>
        <div>
          <h3>{title}</h3>
          <p>{explanation}</p>
        </div>
      </header>
      <ul>
        {entries.map((entry) => (
          <li data-operability-state={entry.shipped_path_state} key={entry.metric_key}>
            <div>
              <strong>{metricLabel(entry.metric_key)}</strong>
              <code>{entry.metric_key}</code>
            </div>
            <p>{NEXT_STEP_LABELS[entry.next_step_code]}</p>
            <span>
              {entry.experimental_model_path
                ? "Separate experimental estimate may be available"
                : "No model estimate is used"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function MetricOperabilityPanel({ transport }: { transport: PromptEnhancerTransport }) {
  const [state, setState] = useState<CatalogState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    const load = transport.getMetricOperabilityCatalog;
    if (!load) {
      setState({ kind: "unavailable" });
      return () => controller.abort();
    }
    setState({ kind: "loading" });
    void load(controller.signal)
      .then((catalog) => {
        if (!controller.signal.aborted) setState({ kind: "ready", catalog });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: error instanceof MetricOperabilityDefinitionsOutOfDateError
            ? "definitions_out_of_date"
            : "unavailable",
        });
      });
    return () => controller.abort();
  }, [transport]);

  const grouped = useMemo(() => {
    if (state.kind !== "ready") return [];
    return GROUPS.map((group) => ({
      ...group,
      entries: state.catalog.entries.filter(
        (entry) => entry.shipped_path_state === group.state,
      ),
    })).filter((group) => group.entries.length > 0);
  }, [state]);

  if (state.kind === "loading") {
    return (
      <section className="metric-operability metric-operability--state" role="status">
        Checking all twenty measurement paths…
      </section>
    );
  }
  if (state.kind === "definitions_out_of_date") {
    return (
      <section className="metric-operability metric-operability--state" role="alert">
        <strong>Metric definitions are newer than this app</strong>
        <span>Update Prompt Enhancer before using this operability map. No session was read.</span>
      </section>
    );
  }
  if (state.kind === "unavailable") {
    return (
      <section className="metric-operability metric-operability--state" role="alert">
        <strong>Metric operability is unavailable</strong>
        <span>Restart the local app after updating Prompt Enhancer. No session was read.</span>
      </section>
    );
  }

  const { catalog } = state;
  return (
    <section className="metric-operability" aria-labelledby="metric-operability-title">
      <header className="metric-operability__intro">
        <div>
          <p className="eyebrow">All-20 release gate · {catalog.catalog_version}</p>
          <h2 id="metric-operability-title">What can produce measured evidence today</h2>
          <p>
            Every contract stays visible. {catalog.shipped_path_count} have a current measurement
            path; {catalog.provider_adapter_gap_count} are explicitly unavailable pending a
            provider adapter. A shipped path can still be Unknown, Pending or Not applicable when
            its evidence is absent; missing evidence is never converted to zero.
          </p>
        </div>
        <aside>
          <strong>Models never author measured values</strong>
          <span>
            Experimental estimates remain a separate, uncalibrated lane even when a larger local judge is active.
          </span>
        </aside>
      </header>

      <dl className="metric-operability__summary" aria-label="Metric operability summary">
        <div><dt>Measured paths shipped</dt><dd>{catalog.shipped_path_count}</dd></div>
        <div><dt>Need project profile</dt><dd>{catalog.task_profile_configuration_gap_count}</dd></div>
        <div><dt>Need source adapter</dt><dd>{catalog.provider_adapter_gap_count}</dd></div>
        <div><dt>Model-authored metrics</dt><dd>{catalog.model_authoritative_metric_count}</dd></div>
      </dl>

      <div className="metric-operability__groups">
        {grouped.map((group) => (
          <StateGroup
            entries={group.entries}
            explanation={group.explanation}
            key={group.state}
            title={group.title}
          />
        ))}
      </div>

      <footer>
        <span>{catalog.total_metric_count}/20 contracts bound to the current client</span>
        <span>{catalog.experimental_model_path_count} have a separate experimental model path</span>
      </footer>
    </section>
  );
}
