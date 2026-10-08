import type { AgentEvent, PromptCheckRequest, PromptCheckResult } from "../../shared/api/contracts";

const MAX_CONTEXT_MESSAGES = 24;
const MAX_CONTEXT_MESSAGE_CHARS = 8_000;
const MAX_CONTEXT_TOTAL_CHARS = 40_000;

/**
 * Build the same bounded, text-only context accepted by Prompt Check. Tool
 * arguments and results are deliberately excluded: they can be large and are
 * not conversational evidence.
 */
export function agentPromptContext(events: AgentEvent[]): PromptCheckRequest["prior_messages"] {
  const messages: PromptCheckRequest["prior_messages"] = [];
  let remaining = MAX_CONTEXT_TOTAL_CHARS;

  for (let index = events.length - 1; index >= 0 && messages.length < MAX_CONTEXT_MESSAGES && remaining > 0; index -= 1) {
    const event = events[index];
    if ((event.kind !== "user" && event.kind !== "assistant") || !event.text?.trim()) continue;
    const trimmed = event.text.trim();
    const bounded = trimmed.slice(-Math.min(MAX_CONTEXT_MESSAGE_CHARS, remaining));
    if (!bounded) continue;
    messages.unshift({ role: event.kind, content: bounded });
    remaining -= bounded.length;
  }

  return messages;
}

function metricValue(metric: PromptCheckResult["metrics"][number]): string {
  if (metric.state !== "known") return metric.state.replace(/_/g, " ");
  if (metric.numerator !== null && metric.numerator !== undefined && metric.denominator !== null && metric.denominator !== undefined) {
    return `${metric.numerator}/${metric.denominator}`;
  }
  return metric.value === null || metric.value === undefined ? "unknown" : `${Math.round(metric.value * 100)}%`;
}

export function AgentPromptCheckResult({
  onUseRewrite,
  result,
}: {
  onUseRewrite: (prompt: string) => void;
  result: PromptCheckResult;
}) {
  return (
    <section aria-labelledby="agent-prompt-check-title" className="agent-prompt-check">
      <div className="agent-prompt-check__head">
        <div>
          <p className="eyebrow">Prompt Check · local preflight</p>
          <h2 id="agent-prompt-check-title">Before the agent acts</h2>
        </div>
        <span>{result.context.prior_context_supplied} prior turn{result.context.prior_context_supplied === 1 ? "" : "s"} used</span>
      </div>

      <p className="agent-prompt-check__summary">{result.summary}</p>

      <div className="agent-prompt-check__grid">
        <div>
          <h3>Deterministic prompt cues</h3>
          <ul className="agent-prompt-check__metrics">
            {result.metrics.map((metric) => (
              <li data-state={metric.state} key={metric.key}>
                <span>{metric.display_name}</span>
                <strong>{metricValue(metric)}</strong>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Highest-value additions</h3>
          {result.context.missing_elements.length > 0 ? (
            <ul className="agent-prompt-check__missing">
              {result.context.missing_elements.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : (
            <p className="agent-prompt-check__note">No prompt-level element is currently flagged as missing.</p>
          )}
        </div>
      </div>

      <div className="agent-prompt-check__commentary" data-state={result.commentary.state}>
        <h3>Local-model suggestions <small>· model output, not measured evidence</small></h3>
        {result.commentary.state === "ok" ? (
          <>
            {result.commentary.findings.length > 0 && (
              <ul className="agent-prompt-check__findings">
                {result.commentary.findings.map((finding, index) => (
                  <li key={`${finding.aspect}-${index}`}>
                    <strong>{finding.aspect}</strong>: {finding.suggestion}
                  </li>
                ))}
              </ul>
            )}
            {result.commentary.reformulated_prompt && (
              <div className="agent-prompt-check__rewrite">
                <pre>{result.commentary.reformulated_prompt}</pre>
                <button className="button button--ghost" onClick={() => onUseRewrite(result.commentary.reformulated_prompt ?? "")} type="button">
                  Use suggested prompt
                </button>
              </div>
            )}
            <p className="agent-prompt-check__note">{result.commentary.caveat}</p>
          </>
        ) : result.commentary.state === "no_active_model" ? (
          <p className="agent-prompt-check__note">No local model is active. The deterministic cues above are still complete.</p>
        ) : result.commentary.state === "skipped" ? (
          <p className="agent-prompt-check__note">Model commentary was not requested.</p>
        ) : (
          <p className="agent-prompt-check__note">The model did not return usable suggestions. The deterministic cues above still stand.</p>
        )}
      </div>

      <p className="agent-prompt-check__scope">{result.other_metric_families_note}</p>
    </section>
  );
}
