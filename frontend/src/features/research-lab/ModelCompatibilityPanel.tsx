import { useEffect, useMemo, useState } from "react";
import type {
  ModelCompatibilityCatalog,
  ModelCompatibilityEntry,
  ModelRuntimeInventory,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";

type EntryLabel = { model: string; configuration: string };

const ENTRY_LABELS: Record<string, EntryLabel> = {
  bge_m3_legacy_pickle_pin_blocked_v1: {
    model: "BGE M3",
    configuration: "Legacy artifact pin",
  },
  bge_m3_unquantized_cuda_screen_v1: {
    model: "BGE M3",
    configuration: "Unquantized CUDA screen",
  },
  bge_reranker_v2_m3_unquantized_cuda_screen_v1: {
    model: "BGE reranker v2 M3",
    configuration: "Unquantized CUDA screen",
  },
  deberta_small_long_nli_unquantized_cuda_screen_v1: {
    model: "DeBERTa small long-context NLI",
    configuration: "Unquantized CUDA screen",
  },
  mdeberta_xnli_unquantized_cuda_screen_v1: {
    model: "Multilingual DeBERTa XNLI",
    configuration: "Unquantized CUDA screen",
  },
  modernbert_base_zeroshot_unquantized_cuda_screen_v1: {
    model: "ModernBERT base zero-shot",
    configuration: "Unquantized CUDA screen",
  },
  multilingual_e5_base_unquantized_cuda_screen_v1: {
    model: "Multilingual E5 base",
    configuration: "Unquantized CUDA screen",
  },
  multilingual_e5_small_unquantized_cuda_screen_v1: {
    model: "Multilingual E5 small",
    configuration: "Unquantized CUDA screen",
  },
  multilingual_minilmv2_l12_nli_unquantized_cuda_screen_v1: {
    model: "Multilingual MiniLM v2 L12 NLI",
    configuration: "Unquantized CUDA screen",
  },
  multilingual_minilmv2_l6_nli_unquantized_cuda_screen_v1: {
    model: "Multilingual MiniLM v2 L6 NLI",
    configuration: "Unquantized CUDA screen",
  },
  qwen3_4b_rubric_bitsandbytes_nf4_child_v1: {
    model: "Qwen3 4B rubric",
    configuration: "NF4 disposable-child diagnostic",
  },
  qwen3_4b_rubric_full_precision_cuda_screen_v1: {
    model: "Qwen3 4B rubric",
    configuration: "Full-precision CUDA screen",
  },
  qwen3_embedding_06b_unquantized_cuda_screen_v1: {
    model: "Qwen3 embedding 0.6B",
    configuration: "Unquantized CUDA screen",
  },
  qwen3_reranker_06b_unquantized_cuda_screen_v1: {
    model: "Qwen3 reranker 0.6B",
    configuration: "Unquantized CUDA screen",
  },
};

const ROLE_LABELS: Record<ModelCompatibilityEntry["role"], string> = {
  retrieval: "Retrieval",
  reranking: "Reranking",
  scoped_nli: "Scoped language inference",
  binary_nli: "Binary language inference",
  structured_rubric: "Structured rubric",
};

const ROLE_ORDER: ModelCompatibilityEntry["role"][] = [
  "retrieval", "reranking", "scoped_nli", "binary_nli", "structured_rubric",
];

const RAM_LABELS: Record<NonNullable<ModelRuntimeInventory["system_ram_bucket"]>, string> = {
  below_16_gib_class: "Below the reviewed 16 GiB class",
  "16_gib_class": "16 GiB class",
  "32_gib_class": "32 GiB class",
  "64_gib_plus_class": "64 GiB+ class",
};

const CUDA_LABELS: Record<NonNullable<ModelRuntimeInventory["cuda_vram_bucket"]>, string> = {
  below_8_gib_class: "Below the reviewed 8 GiB class",
  "8_gib_class": "8 GiB class",
  "12_gib_class": "12 GiB class",
  "16_gib_class": "16 GiB class",
  "24_gib_plus_class": "24 GiB+ class",
};

const REASON_LABELS: Record<ModelCompatibilityEntry["reason_codes"][number], string> = {
  exploratory_resource_fit: "Resource evidence fits the reviewed ceilings; research use only.",
  resource_measurement_missing: "Resource evidence is incomplete, so fit remains a research question.",
  hardware_inventory_unknown: "System memory could not be classified.",
  insufficient_system_ram: "System memory is below the reviewed 16 GiB class.",
  cuda_unavailable: "CUDA is unavailable on this device.",
  cuda_inventory_unknown: "CUDA availability could not be determined.",
  insufficient_cuda_vram: "CUDA memory is below the reviewed 8 GiB class.",
  child_gpu_allocation_ceiling_exceeded: "Observed GPU allocation exceeds the 6 GiB child ceiling.",
  child_rss_ceiling_exceeded: "Observed child memory exceeds the 8 GiB ceiling.",
  unsafe_pickle_only: "The reviewed artifact did not pass the safe-format gate.",
};

function cudaLabel(inventory: ModelRuntimeInventory): string {
  if (inventory.cuda_state === "unknown") return "CUDA status unknown";
  if (inventory.cuda_state === "unavailable") return "CUDA unavailable";
  return inventory.cuda_vram_bucket
    ? CUDA_LABELS[inventory.cuda_vram_bucket]
    : "CUDA status unknown";
}

function ramLabel(inventory: ModelRuntimeInventory): string {
  return inventory.system_ram_bucket
    ? RAM_LABELS[inventory.system_ram_bucket]
    : "System memory class unknown";
}

function configurationEvidence(entry: ModelCompatibilityEntry): string {
  const gpu = entry.observed_peak_gpu_allocation_mib;
  const rss = entry.observed_peak_child_rss_mib;
  if (entry.measurement_method === "documented_approximate_gpu_peak_only" && typeof gpu === "number") {
    return `Documented approximate GPU peak ${(gpu / 1_024).toFixed(2)} GiB; child memory not measured.`;
  }
  if (typeof gpu === "number" && typeof rss === "number") {
    return `Observed GPU peak ${(gpu / 1_024).toFixed(2)} GiB; child memory ${(rss / 1_024).toFixed(2)} GiB.`;
  }
  if (typeof gpu === "number") {
    return `Observed GPU peak ${(gpu / 1_024).toFixed(2)} GiB; child memory not measured.`;
  }
  return "No configuration-specific GPU or child-memory measurement.";
}

function EntryRow({ entry }: { entry: ModelCompatibilityEntry }) {
  const label = ENTRY_LABELS[entry.configuration_key] ?? {
    model: "Reviewed local model",
    configuration: "Reviewed configuration",
  };
  const researchOnly = entry.status === "research_only";
  return (
    <article className="model-compatibility-row">
      <div className="model-compatibility-row__identity">
        <strong>{label.model}</strong>
        <span>{label.configuration}</span>
      </div>
      <div className="model-compatibility-row__status">
        <span className={`research-status research-status--${researchOnly ? "research" : "blocked"}`}>
          {researchOnly ? "Research only" : "Unavailable"}
        </span>
        <small>{REASON_LABELS[entry.reason_codes[0]]}</small>
      </div>
      <dl>
        <div>
          <dt>Resource evidence</dt>
          <dd>{configurationEvidence(entry)}</dd>
        </div>
        <div>
          <dt>Configuration</dt>
          <dd>{entry.quantization === "bitsandbytes_nf4" ? "NF4 quantized" : "Unquantized"}</dd>
        </div>
      </dl>
    </article>
  );
}

export function ModelCompatibilityPanel({ transport }: { transport: PromptEnhancerTransport }) {
  const [catalog, setCatalog] = useState<ModelCompatibilityCatalog | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    const load = transport.getTextModelCompatibility;
    if (!load) {
      setStatus("error");
      return () => controller.abort();
    }
    setStatus("loading");
    void load(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setCatalog(value);
        setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("error");
      });
    return () => controller.abort();
  }, [transport]);

  const groups = useMemo(() => {
    if (catalog === null) return [];
    return ROLE_ORDER.map((role) => ({
      role,
      entries: catalog.models.filter((entry) => entry.role === role),
    })).filter((group) => group.entries.length > 0);
  }, [catalog]);

  return (
    <section className="model-compatibility" aria-labelledby="model-compatibility-title">
      <header>
        <div>
          <p className="eyebrow">Local, content-free inventory</p>
          <h2 id="model-compatibility-title">Model compatibility</h2>
          <p>Read-only resource evidence for fixed model configurations. No session or cache content is inspected.</p>
        </div>
        <span className="model-compatibility__mode">Exploratory only</span>
      </header>
      {status === "loading" && (
        <p className="model-compatibility__state" aria-live="polite">Checking coarse hardware classes…</p>
      )}
      {status === "error" && (
        <p className="model-compatibility__state model-compatibility__state--error" role="alert">
          Model compatibility is unavailable. No local model action was taken.
        </p>
      )}
      {status === "ready" && catalog && (
        <>
          <dl className="model-compatibility__inventory">
            <div><dt>CUDA</dt><dd>{cudaLabel(catalog.inventory)}</dd></div>
            <div><dt>System memory</dt><dd>{ramLabel(catalog.inventory)}</dd></div>
            <div><dt>Child ceilings</dt><dd>6 GiB GPU allocation · 8 GiB memory</dd></div>
            <div><dt>Data handling</dt><dd>Local memory only · not saved or synced</dd></div>
          </dl>
          <div className="model-compatibility__groups">
            {groups.map((group) => (
              <section key={group.role} aria-labelledby={`model-role-${group.role}`}>
                <header>
                  <h3 id={`model-role-${group.role}`}>{ROLE_LABELS[group.role]}</h3>
                  <span>{group.entries.length} {group.entries.length === 1 ? "configuration" : "configurations"}</span>
                </header>
                <div>{group.entries.map((entry) => <EntryRow entry={entry} key={entry.configuration_key} />)}</div>
              </section>
            ))}
          </div>
          <p className="model-compatibility__boundary">
            These rows report resource fit only. They do not establish output quality or enable product use.
          </p>
        </>
      )}
    </section>
  );
}
