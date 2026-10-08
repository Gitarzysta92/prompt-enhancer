import { useEffect, useState } from "react";
import type {
  ModelLabInventory,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";

type InventoryState =
  | { status: "loading" }
  | { status: "ready"; inventory: ModelLabInventory }
  | { status: "error" };

function displayCode(value: string): string {
  return value.replaceAll("-", " ").replaceAll("_", " ");
}

export function ModelLabInventoryPanel({
  transport,
}: {
  transport: PromptEnhancerTransport;
}) {
  const [state, setState] = useState<InventoryState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    const load = transport.getModelLabInventory;
    if (!load) {
      setState({ status: "error" });
      return () => controller.abort();
    }
    setState({ status: "loading" });
    void load(controller.signal)
      .then((inventory) => {
        if (!controller.signal.aborted) setState({ status: "ready", inventory });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    return () => controller.abort();
  }, [transport]);

  if (state.status === "error") {
    return (
      <section className="model-lab-inventory model-lab-inventory--unknown">
        <div role="alert">
          <p className="eyebrow">Persisted estimator receipts</p>
          <h2>Model Lab inventory: Unknown</h2>
          <p>
            The local inventory could not be verified. No missing count is shown as zero,
            no session was read, and product activation remains off.
          </p>
        </div>
      </section>
    );
  }

  if (state.status === "loading") {
    return (
      <section className="model-lab-inventory" aria-busy="true">
        <div role="status">
          <p className="eyebrow">Persisted estimator receipts</p>
          <h2>Checking Model Lab inventory...</h2>
          <p>
            This read is content-free, does not open projects or sessions, and cannot
            activate a model.
          </p>
        </div>
      </section>
    );
  }

  const { inventory } = state;
  return (
    <section className="model-lab-inventory" aria-labelledby="model-lab-inventory-title">
      <header>
        <div>
          <p className="eyebrow">Persisted estimator receipts</p>
          <h2 id="model-lab-inventory-title">Synthetic evaluation inventory</h2>
          <p>
            Exact counts from the local synthetic-only store. Reading this inventory opened
            no session and returned no private evidence.
          </p>
        </div>
        <span className="research-status research-status--blocked">
          Product activation off
        </span>
      </header>
      <dl className="model-lab-inventory__totals">
        <div><dt>Registered plans</dt><dd>{inventory.registered_plan_count}</dd></div>
        <div><dt>Synthetic executions</dt><dd>{inventory.synthetic_execution_count}</dd></div>
        <div><dt>Model runs</dt><dd>{inventory.model_run_count}</dd></div>
        <div><dt>Model votes</dt><dd>{inventory.model_vote_count}</dd></div>
        <div><dt>Metric estimates</dt><dd>{inventory.metric_estimate_count}</dd></div>
      </dl>
      {inventory.plans.length === 0 ? (
        <p className="model-lab-inventory__empty">
          Zero synthetic estimator plans are registered. This is a verified empty result,
          not an unavailable measurement.
        </p>
      ) : (
        <div className="model-lab-inventory__plans" aria-label="Registered synthetic plans">
          {inventory.plans.map((plan) => (
            <article key={plan.plan_fingerprint}>
              <div>
                <strong>{displayCode(plan.plan_key)}</strong>
                <span>{plan.plan_version} / {displayCode(plan.route)}</span>
              </div>
              <dl>
                <div><dt>Questions</dt><dd>{plan.metric_question_count}</dd></div>
                <div><dt>Executions</dt><dd>{plan.synthetic_execution_count}</dd></div>
                <div><dt>Runs</dt><dd>{plan.model_run_count}</dd></div>
                <div><dt>Votes</dt><dd>{plan.model_vote_count}</dd></div>
                <div><dt>Estimates</dt><dd>{plan.metric_estimate_count}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      )}
      <p className="model-lab-inventory__boundary">
        Synthetic success is insufficient for activation. A representative private holdout,
        calibration, stability, privacy and latency gates are still required.
      </p>
    </section>
  );
}
