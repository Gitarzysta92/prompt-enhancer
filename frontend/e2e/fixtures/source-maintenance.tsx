import { createRoot } from "react-dom/client";
import { useMemo, useState } from "react";
import { LocalSources } from "../../src/features/local-sources/LocalSources";
import type { CodexIngestionReport, CodexLocalSourceStatus, CodexSession, PromptEnhancerTransport } from "../../src/shared/api/contracts";
import { createSyntheticTransport } from "../../src/shared/api/syntheticTransport";
import { bootstrapTheme } from "../../src/shared/platform/theme";
import "../../src/styles.css";

const HEX_SEED = "0123456789abcdef";

function hexId(value: number): string {
  const encoded = value.toString(16);
  return `${HEX_SEED[0].repeat(64 - encoded.length)}${encoded}`;
}

function syntheticSessions(): CodexSession[] {
  const rows: CodexSession[] = [];
  for (let projectIndex = 0; projectIndex < 25; projectIndex += 1) {
    const count = projectIndex === 0 ? 45 : 1;
    for (let sessionIndex = 0; sessionIndex < count; sessionIndex += 1) {
      rows.push({
        session_id: hexId(projectIndex * 100 + sessionIndex + 1),
        installation_id: hexId(9000),
        project_id: hexId(1000 + projectIndex),
        project_display_name: `Synthetic Project ${projectIndex}`,
        project_display_name_origin: "provider",
        project_manual_label_revision: 0,
        session_display_name: `Synthetic Session ${projectIndex}-${sessionIndex}`,
        session_display_name_origin: "provider",
        session_manual_label_revision: 0,
        provider: "codex",
        provider_version: "synthetic-provider-v1",
        adapter_version: "synthetic-adapter-v1",
        source_schema_version: "synthetic-schema-v1",
        started_at: `2040-01-${String((sessionIndex % 9) + 1).padStart(2, "0")}T10:00:00Z`,
        ended_at: "2040-01-09T10:05:00Z",
        terminal_state: "completed",
        events_complete: true,
      });
    }
  }
  return rows;
}

function SourceMaintenanceFixture() {
  const [lastAnalyze, setLastAnalyze] = useState("No analyze request yet");
  const transport = useMemo(() => {
    const sessions = syntheticSessions();
    const base = createSyntheticTransport();
    const sourceStatus: CodexLocalSourceStatus = {
      consent_active: true,
      indexed_sessions: sessions.length,
      indexed_projects: 25,
      verification_capability: {
        state: "validation_only" as const,
        live_classification_enabled: false,
        classifier_version: "synthetic-classifier-v1",
        normalizer_version: "synthetic-normalizer-v1",
        candidate_schema_version: "synthetic-candidate-v1",
        supported_kinds: ["test" as const],
        reason_code: "provider_adapter_and_holdout_required" as const,
      },
    };
    const fixtureTransport: PromptEnhancerTransport = {
      ...base,
      getCodexLocalSourceStatus: async () => sourceStatus,
      listCodexSessions: async (limit = 100, offset = 0) => ({
        sessions: sessions.slice(offset, offset + limit),
        limit,
        offset,
      }),
      analyzeCodexLocalSessions: async (payload): Promise<CodexIngestionReport> => {
        setLastAnalyze(JSON.stringify(payload));
        const selectedCount = sessions.filter((session) =>
          payload.project_ids.includes(session.project_id)
          || payload.session_ids.includes(session.session_id),
        ).length;
        return {
          provider: "codex",
          sessions_seen: sessions.length,
          sessions_selected: Math.min(selectedCount, payload.max_sessions),
          sessions_inserted: 0,
          sessions_updated: 0,
          events_seen: 0,
          events_inserted: 0,
          events_updated: 0,
          metrics_written: 0,
          truncated: selectedCount > payload.max_sessions,
        };
      },
    };
    return fixtureTransport;
  }, []);

  return (
    <main>
      <p className="eyebrow">Synthetic source maintenance fixture — no provider, network, or model reads</p>
      <LocalSources navigate={() => undefined} transport={transport} />
      <section aria-label="Last synthetic analyze request" className="source-safety-note">
        <strong>Last synthetic analyze request</strong>
        <output
          data-testid="analyze-receipt"
          style={{ display: "block", maxWidth: "100%", overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
        >
          {lastAnalyze}
        </output>
      </section>
    </main>
  );
}

bootstrapTheme();
createRoot(document.getElementById("root")!).render(<SourceMaintenanceFixture />);
