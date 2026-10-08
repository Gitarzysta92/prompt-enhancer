import { useId, useState } from "react";
import type {
  ModelEnsembleAttemptStage,
  ModelEnsembleRun,
} from "../../shared/api/contracts";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import {
  MODEL_ENSEMBLE_STAGE_GROUPS,
  formatStageResource,
  formatStageUnloadReceipt,
  modelEnsembleStageSummaryLabel,
  modelEnsembleStagesFor,
  shortIdentity,
} from "./modelStages";
import "./MetricHistoryAndStages.css";

interface StageSelection {
  contextIdentity: string;
  modelKey: string;
}

function stageContextIdentity(
  run: ModelEnsembleRun | null,
  attemptStages: readonly ModelEnsembleAttemptStage[],
): string {
  if (attemptStages.length === 0) return `sealed:${run?.run_id ?? "not-exposed"}`;
  const first = attemptStages[0];
  return `attempt:${first.stage_ordinal}:${first.stage_key}:${first.completed_at}`;
}

function readableStageStatus(value: string): string {
  return value.replaceAll("_", " ");
}

/**
 * Content-free model-stage provenance. Selection is synchronously bound to the
 * exact sealed run or the available latest-attempt receipt identity so an
 * inspector chosen in context A cannot silently describe context B.
 */
export function ModelConstellationDrawer({ run, attemptStages, compact: _compact }: {
  run: ModelEnsembleRun | null;
  attemptStages: readonly ModelEnsembleAttemptStage[];
  compact: boolean;
}) {
  const stageSet = modelEnsembleStagesFor(run, attemptStages);
  const { stages } = stageSet;
  const inspectorId = useId();
  const contextIdentity = stageContextIdentity(run, attemptStages);
  const [selection, setSelection] = useState<StageSelection | null>(null);
  const selectedKey = selection?.contextIdentity === contextIdentity
    && stages.some((stage) => stage.modelKey === selection.modelKey)
    ? selection.modelKey
    : stages[0]?.modelKey ?? "";
  const selected = stages.find((stage) => stage.modelKey === selectedKey);
  const select = (modelKey: string) => setSelection({ contextIdentity, modelKey });
  const sourceLabel = stageSet.source === "attempt" ? "Latest durable attempt" : "Sealed snapshot";

  return (
    <details className="metric-workspace__drawer model-constellation">
      <summary>
        <span>Models</span>
        <small>{modelEnsembleStageSummaryLabel(stageSet)}</small>
      </summary>
      <div className="model-constellation__body">
        <p className="model-constellation__authority" role="note">
          Model stages are experimental evidence helpers, not metric authorities. Small
          models estimate factor evidence and the deep judge only resolves selected
          disagreements; the sealed measured publication is computed from deterministic
          or typed receipts and never from model agreement.
        </p>
        <p className="model-constellation__source"><strong>Displayed provenance</strong><span>{sourceLabel}</span></p>
        {stages.length === 0 && <p className="model-constellation__empty">Model stage details are not exposed for this sealed receipt. Missing stage receipts do not imply that a stage ran, failed, or contributed zero cases.</p>}
        {MODEL_ENSEMBLE_STAGE_GROUPS.map((group) => {
          const groupStages = stages.filter((stage) => stage.group === group);
          if (groupStages.length === 0) return null;
          const headingId = `${inspectorId}-${group.replaceAll(" ", "-")}`;
          return (
            <section aria-labelledby={headingId} key={group}>
              <h4 id={headingId}>{group}</h4>
              <div
                aria-label={`${group} stages`}
                className="model-constellation__nodes"
                onKeyDown={(event) => moveRovingFocus(event, (index) => {
                  const stage = groupStages[index];
                  if (stage !== undefined) select(stage.modelKey);
                })}
                role="group"
              >
                {groupStages.map((stage) => (
                  <button
                    aria-controls={inspectorId}
                    aria-label={`${stage.repositoryId} · ${stage.role} · ${readableStageStatus(stage.status)}`}
                    aria-pressed={stage.modelKey === selected?.modelKey}
                    data-status={stage.status}
                    key={stage.modelKey}
                    onClick={() => select(stage.modelKey)}
                    title={`${stage.repositoryId} · ${stage.role}`}
                    type="button"
                  >
                    <i aria-hidden="true" />
                    <span>{stage.repositoryId.split("/").at(-1)}</span>
                    <small>{readableStageStatus(stage.status)}</small>
                  </button>
                ))}
              </div>
            </section>
          );
        })}
        {selected !== undefined && (
          <aside aria-atomic="true" aria-labelledby={`${inspectorId}-heading`} aria-live="polite" className="model-constellation__inspector" id={inspectorId}>
            <header>
              <h4 id={`${inspectorId}-heading`}>{selected.repositoryId}</h4>
              <span>{selected.role}</span>
            </header>
            <dl>
              <div><dt>Receipt source</dt><dd>{sourceLabel}</dd></div>
              <div><dt>Status</dt><dd data-status={selected.status}>{readableStageStatus(selected.status)}</dd></div>
              <div><dt>Device</dt><dd>{selected.device?.toUpperCase() ?? "not recorded"}</dd></div>
              <div><dt>Quantization</dt><dd>{readableStageStatus(selected.quantization)}</dd></div>
              <div><dt>Latency</dt><dd>{selected.latency === null ? "not recorded" : `${selected.latency} ms`}</dd></div>
              <div><dt>Peak VRAM</dt><dd>{formatStageResource(selected.acceleratorMemory)}</dd></div>
              <div><dt>Peak RAM</dt><dd>{formatStageResource(selected.rss)}</dd></div>
              <div><dt>Released</dt><dd>{formatStageUnloadReceipt(selected.unloaded)}</dd></div>
              <div>
                <dt>Revision</dt>
                <dd>{selected.revision === "not-recorded" ? "not recorded" : <code title={selected.revision}>{shortIdentity(selected.revision)}</code>}</dd>
              </div>
              <div><dt>Experimental cases evaluated</dt><dd>{selected.evaluatedCases ?? "unavailable"}</dd></div>
              <div><dt>Experimental cases contributed</dt><dd>{selected.contributedCases ?? "unavailable"}</dd></div>
              <div><dt>Measured-metric authority</dt><dd>none</dd></div>
            </dl>
            {selected.errorCode !== null && <p className="model-constellation__error" role="alert"><strong>Stage report</strong><span>{readableStageStatus(selected.errorCode)}</span></p>}
            {(selected.evaluatedCases === null || selected.contributedCases === null) && <p className="model-constellation__unknown">Case counts are unavailable for this stage receipt; they are not zero. Current v1 receipts identify the stage without trustworthy per-metric contribution counts.</p>}
          </aside>
        )}
      </div>
    </details>
  );
}
