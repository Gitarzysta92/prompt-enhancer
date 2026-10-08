import type {
  ModelCompatibilityCatalog,
  ModelCompatibilityEntry,
  ModelRuntimeInventory,
} from "./contracts";

export class ModelCompatibilityPayloadError extends Error {
  constructor() {
    super("Model compatibility response was invalid");
    this.name = "ModelCompatibilityPayloadError";
  }
}

type Row = Record<string, unknown>;

export type FrozenModelCompatibilityConfiguration = Readonly<
  Required<Omit<ModelCompatibilityEntry, "status" | "reason_codes">>
>;

function frozenConfiguration(
  value: Required<Omit<ModelCompatibilityEntry, "status" | "reason_codes">>,
): FrozenModelCompatibilityConfiguration {
  return Object.freeze(value);
}

/**
 * Browser-side copy of the versioned backend registry.
 *
 * Every field here is immutable provenance. Hardware-dependent status and
 * reason codes are deliberately absent and are derived separately below.
 */
export const FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS = Object.freeze([
  frozenConfiguration({
    configuration_key: "bge_m3_legacy_pickle_pin_blocked_v1",
    model_key: "bge_m3_legacy_pickle_pin",
    repository_id: "BAAI/bge-m3",
    revision: "5617a9f61b028005a4858fdac845db406aefb181",
    task: "requirement_action_retrieval",
    role: "retrieval",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "unknown",
    runtime: "not_runnable",
    measurement_method: "not_measured",
    measurement_precision: "not_measured",
    measurement_source: "reviewed_artifact_gate_v1",
    resource_measurement_state: "missing",
    observed_peak_gpu_allocation_mib: null,
    observed_peak_child_rss_mib: null,
    benchmark_key: null,
    synthetic_case_count: null,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "bge_m3_unquantized_cuda_screen_v1",
    model_key: "bge_m3",
    repository_id: "BAAI/bge-m3",
    revision: "142964af7e05de16511657561de8e8750fc153a0",
    task: "requirement_action_retrieval",
    role: "retrieval",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 2_179.602,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 12,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "bge_reranker_v2_m3_unquantized_cuda_screen_v1",
    model_key: "bge_reranker_v2_m3",
    repository_id: "BAAI/bge-reranker-v2-m3",
    revision: "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    task: "pair_reranking",
    role: "reranking",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 2_194.156,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 12,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "deberta_small_long_nli_unquantized_cuda_screen_v1",
    model_key: "deberta_small_long_nli",
    repository_id: "tasksource/deberta-small-long-nli",
    revision: "9a77395d4d3751be9e2a69c4ae318491d9b3fffb",
    task: "scoped_nli",
    role: "scoped_nli",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "not_measured",
    measurement_precision: "not_measured",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "missing",
    observed_peak_gpu_allocation_mib: null,
    observed_peak_child_rss_mib: null,
    benchmark_key: null,
    synthetic_case_count: null,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "mdeberta_xnli_unquantized_cuda_screen_v1",
    model_key: "mdeberta_xnli",
    repository_id: "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
    revision: "b5113eb38ab63efdd7f280f8c144ea8b13f978ce",
    task: "scoped_nli",
    role: "scoped_nli",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 1_121.56,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 18,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "modernbert_base_zeroshot_unquantized_cuda_screen_v1",
    model_key: "modernbert_base_zeroshot",
    repository_id: "MoritzLaurer/ModernBERT-base-zeroshot-v2.0",
    revision: "d421c4545a438fd006fb43f8b981c5d908faa1e1",
    task: "binary_nli",
    role: "binary_nli",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "not_measured",
    measurement_precision: "not_measured",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "missing",
    observed_peak_gpu_allocation_mib: null,
    observed_peak_child_rss_mib: null,
    benchmark_key: null,
    synthetic_case_count: null,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "multilingual_e5_base_unquantized_cuda_screen_v1",
    model_key: "multilingual_e5_base",
    repository_id: "intfloat/multilingual-e5-base",
    revision: "d128750597153bb5987e10b1c3493a34e5a4502a",
    task: "requirement_action_retrieval",
    role: "retrieval",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 1_078.121,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 12,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "multilingual_e5_small_unquantized_cuda_screen_v1",
    model_key: "multilingual_e5_small",
    repository_id: "intfloat/multilingual-e5-small",
    revision: "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    task: "requirement_action_retrieval",
    role: "retrieval",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 462.436,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 12,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "multilingual_minilmv2_l12_nli_unquantized_cuda_screen_v1",
    model_key: "multilingual_minilmv2_l12_nli",
    repository_id: "MoritzLaurer/multilingual-MiniLMv2-L12-mnli-xnli",
    revision: "0d55db361c5f291640208c51ff8c181146aa8eff",
    task: "scoped_nli",
    role: "scoped_nli",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "p1_specialist_screen_v2",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 463.791,
    observed_peak_child_rss_mib: null,
    benchmark_key: "specialist-foundation-metrics-v2",
    synthetic_case_count: 24,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "multilingual_minilmv2_l6_nli_unquantized_cuda_screen_v1",
    model_key: "multilingual_minilmv2_l6_nli",
    repository_id: "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    revision: "0a71e92a985b6e1ad1828cf67ce9c459639c1dca",
    task: "scoped_nli",
    role: "scoped_nli",
    language_scope: "english_polish",
    license_spdx: "MIT",
    quantization: "none",
    dtype: "float32",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "p1_specialist_screen_v2",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 423.177,
    observed_peak_child_rss_mib: null,
    benchmark_key: "specialist-foundation-metrics-v2",
    synthetic_case_count: 24,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "qwen3_4b_rubric_bitsandbytes_nf4_child_v1",
    model_key: "qwen3_4b_rubric",
    repository_id: "Qwen/Qwen3-4B-Instruct-2507",
    revision: "cdbee75f17c01a7cc42f958dc650907174af0554",
    task: "structured_rubric",
    role: "structured_rubric",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "bitsandbytes_nf4",
    dtype: "nf4_runtime_float16_or_bfloat16_compute",
    runtime: "disposable_pytorch_cuda_child",
    measurement_method: "documented_approximate_gpu_peak_only",
    measurement_precision: "documented_approximate_0_01_gib",
    measurement_source: "real_metrics_campaign_diagnostic_2026_08_17",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 3_932.16,
    observed_peak_child_rss_mib: null,
    benchmark_key: null,
    synthetic_case_count: null,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "qwen3_4b_rubric_full_precision_cuda_screen_v1",
    model_key: "qwen3_4b_rubric",
    repository_id: "Qwen/Qwen3-4B-Instruct-2507",
    revision: "cdbee75f17c01a7cc42f958dc650907174af0554",
    task: "structured_rubric",
    role: "structured_rubric",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "none",
    dtype: "runtime_float16_or_bfloat16",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 7_769.893,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_rubric_screen_v1",
    synthetic_case_count: 24,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "qwen3_embedding_06b_unquantized_cuda_screen_v1",
    model_key: "qwen3_embedding_06b",
    repository_id: "Qwen/Qwen3-Embedding-0.6B",
    revision: "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    task: "requirement_action_retrieval",
    role: "retrieval",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "none",
    dtype: "runtime_float16_or_bfloat16",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 1_197.371,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 12,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
  frozenConfiguration({
    configuration_key: "qwen3_reranker_06b_unquantized_cuda_screen_v1",
    model_key: "qwen3_reranker_06b",
    repository_id: "Qwen/Qwen3-Reranker-0.6B",
    revision: "e61197ed45024b0ed8a2d74b80b4d909f1255473",
    task: "pair_reranking",
    role: "reranking",
    language_scope: "english_polish",
    license_spdx: "Apache-2.0",
    quantization: "none",
    dtype: "runtime_float16_or_bfloat16",
    runtime: "pytorch_2_8_cuda_12_6_synthetic_screen",
    measurement_method: "torch_cuda_max_memory_allocated",
    measurement_precision: "observed_to_0_001_mib",
    measurement_source: "wp_11_local_candidates_v1",
    resource_measurement_state: "partial",
    observed_peak_gpu_allocation_mib: 1_488.585,
    observed_peak_child_rss_mib: null,
    benchmark_key: "bilingual_model_screen_v1",
    synthetic_case_count: 12,
    trust_remote_code: false,
    product_enabled: false,
    activation_allowed: false,
    download_allowed: false,
  }),
]);

const IMMUTABLE_ENTRY_KEY_GUARD = {
  configuration_key: true,
  model_key: true,
  repository_id: true,
  revision: true,
  task: true,
  role: true,
  language_scope: true,
  license_spdx: true,
  quantization: true,
  dtype: true,
  runtime: true,
  measurement_method: true,
  measurement_precision: true,
  measurement_source: true,
  resource_measurement_state: true,
  observed_peak_gpu_allocation_mib: true,
  observed_peak_child_rss_mib: true,
  benchmark_key: true,
  synthetic_case_count: true,
  trust_remote_code: true,
  product_enabled: true,
  activation_allowed: true,
  download_allowed: true,
} as const satisfies Record<keyof FrozenModelCompatibilityConfiguration, true>;

const IMMUTABLE_ENTRY_KEYS = Object.freeze(
  Object.keys(IMMUTABLE_ENTRY_KEY_GUARD) as Array<
    keyof FrozenModelCompatibilityConfiguration
  >,
);

const INVENTORY_KEYS = [
  "preferred_device", "cuda_state", "cuda_available", "mps_available",
  "cpu_available", "cpu_architecture_bucket", "logical_core_bucket",
  "system_ram_bucket", "cuda_vram_bucket", "cuda_capability_bucket",
  "model_cache_free_disk_bucket", "discovery_reason_codes", "inventory_version",
  "one_model_at_a_time", "subprocess_isolation", "raw_session_data_accepted",
  "model_child_gpu_allocation_ceiling_mib", "model_child_rss_ceiling_mib",
  "model_downloads_started", "model_activation_allowed", "sensitivity",
  "local_only", "persisted", "synced",
] as const;

const ENTRY_KEYS = [
  "configuration_key", "model_key", "repository_id", "revision", "task", "role",
  "language_scope", "license_spdx", "status", "reason_codes", "quantization",
  "dtype", "runtime", "measurement_method", "measurement_precision",
  "measurement_source", "resource_measurement_state",
  "observed_peak_gpu_allocation_mib", "observed_peak_child_rss_mib",
  "benchmark_key", "synthetic_case_count", "trust_remote_code", "product_enabled",
  "activation_allowed", "download_allowed",
] as const;

const CATALOG_KEYS = [
  "catalog_version", "measurement_version", "catalog_policy", "content_free",
  "session_data_read", "cache_contents_read", "downloads_started",
  "activation_allowed", "local_only", "persisted", "synced", "inventory", "models",
] as const;

const HARDWARE_REASONS = [
  "cpu_architecture_unknown", "logical_core_bucket_unknown",
  "system_ram_bucket_unknown", "cuda_inventory_unknown",
  "model_cache_free_disk_bucket_unknown",
] as const;
const RESOURCE_REASONS = [
  "exploratory_resource_fit", "resource_measurement_missing",
  "hardware_inventory_unknown", "insufficient_system_ram", "cuda_unavailable",
  "cuda_inventory_unknown", "insufficient_cuda_vram",
  "child_gpu_allocation_ceiling_exceeded", "child_rss_ceiling_exceeded",
  "unsafe_pickle_only",
] as const;

function invalid(): never {
  throw new ModelCompatibilityPayloadError();
}

function row(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  return value as Row;
}

function exact(value: Row, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  if (actual.length !== keys.length || actual.some((key, index) => key !== keys[index])) invalid();
}

function oneOf<T extends string>(value: unknown, values: readonly T[]): T {
  if (typeof value !== "string" || !values.includes(value as T)) invalid();
  return value as T;
}

function safeToken(value: unknown, maximum: number): string {
  if (
    typeof value !== "string" || value.length < 1 || value.length > maximum
    || !/^[a-z][a-z0-9_]*$/.test(value)
  ) invalid();
  return value;
}

function safeBenchmarkKey(value: unknown): string {
  if (
    typeof value !== "string" || value.length < 1 || value.length > 64
    || !/^[a-z][a-z0-9_-]*$/.test(value)
  ) invalid();
  return value;
}

function nullableFinite(value: unknown): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1_048_576) invalid();
  return value;
}

function nullableInteger(value: unknown): number | null {
  if (value === null) return null;
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > 100_000) invalid();
  return value as number;
}

function stringArray<T extends string>(
  value: unknown,
  vocabulary: readonly T[],
  maximum: number,
): T[] {
  if (!Array.isArray(value) || value.length > maximum) invalid();
  const result = value.map((item) => oneOf(item, vocabulary));
  if (new Set(result).size !== result.length) invalid();
  return result;
}

function parseInventory(value: unknown): ModelRuntimeInventory {
  const inventory = row(value);
  exact(inventory, INVENTORY_KEYS);
  const preferred = oneOf(inventory.preferred_device, ["cpu", "cuda", "mps"] as const);
  const cudaState = oneOf(inventory.cuda_state, ["available", "unavailable", "unknown"] as const);
  const cpuArchitecture = inventory.cpu_architecture_bucket === null ? null : oneOf(
    inventory.cpu_architecture_bucket, ["x86_64", "arm64", "x86", "arm32"] as const,
  );
  const logicalCores = inventory.logical_core_bucket === null ? null : oneOf(
    inventory.logical_core_bucket,
    ["1_to_4", "5_to_8", "9_to_16", "17_to_32", "33_to_64", "65_plus"] as const,
  );
  const systemRam = inventory.system_ram_bucket === null ? null : oneOf(
    inventory.system_ram_bucket,
    ["below_16_gib_class", "16_gib_class", "32_gib_class", "64_gib_plus_class"] as const,
  );
  const cudaVram = inventory.cuda_vram_bucket === null ? null : oneOf(
    inventory.cuda_vram_bucket,
    ["below_8_gib_class", "8_gib_class", "12_gib_class", "16_gib_class", "24_gib_plus_class"] as const,
  );
  const cudaCapability = inventory.cuda_capability_bucket === null ? null : oneOf(
    inventory.cuda_capability_bucket, ["pre_7", "7_x", "8_x", "9_plus"] as const,
  );
  const cacheDisk = inventory.model_cache_free_disk_bucket === null ? null : oneOf(
    inventory.model_cache_free_disk_bucket,
    ["under_10240_mib", "10240_to_51199_mib", "51200_to_102399_mib", "102400_plus_mib"] as const,
  );
  const reasons = stringArray(inventory.discovery_reason_codes, HARDWARE_REASONS, 5);
  const expectedReasons = [
    ...(cpuArchitecture === null ? ["cpu_architecture_unknown"] : []),
    ...(logicalCores === null ? ["logical_core_bucket_unknown"] : []),
    ...(systemRam === null ? ["system_ram_bucket_unknown"] : []),
    ...(cudaState === "unknown" ? ["cuda_inventory_unknown"] : []),
    ...(cacheDisk === null ? ["model_cache_free_disk_bucket_unknown"] : []),
  ].sort();

  if (
    typeof inventory.mps_available !== "boolean" || inventory.cpu_available !== true
    || inventory.inventory_version !== "bucketed-sensitive-hardware-inventory-v3"
    || inventory.one_model_at_a_time !== true || inventory.subprocess_isolation !== true
    || inventory.raw_session_data_accepted !== false
    || inventory.model_child_gpu_allocation_ceiling_mib !== 6_144
    || inventory.model_child_rss_ceiling_mib !== 8_192
    || inventory.model_downloads_started !== false
    || inventory.model_activation_allowed !== false
    || inventory.sensitivity !== "sensitive_derived" || inventory.local_only !== true
    || inventory.persisted !== false || inventory.synced !== false
    || reasons.join("\0") !== expectedReasons.join("\0")
  ) invalid();

  if (cudaState === "available") {
    if (inventory.cuda_available !== true || cudaVram === null || cudaCapability === null || preferred !== "cuda") invalid();
  } else if (cudaState === "unavailable") {
    if (
      inventory.cuda_available !== false || cudaVram !== null || cudaCapability !== null
      || preferred !== (inventory.mps_available ? "mps" : "cpu")
    ) invalid();
  } else if (
    inventory.cuda_available !== null || cudaVram !== null || cudaCapability !== null
    || preferred !== "cpu" || inventory.mps_available !== false
  ) invalid();
  if (preferred === "mps" && inventory.mps_available !== true) invalid();
  return value as ModelRuntimeInventory;
}

function expectedResourceReason(
  inventory: ModelRuntimeInventory,
  entry: FrozenModelCompatibilityConfiguration,
): ModelCompatibilityEntry["reason_codes"][number] {
  if (entry.configuration_key === "bge_m3_legacy_pickle_pin_blocked_v1") return "unsafe_pickle_only";
  if (inventory.system_ram_bucket === null) return "hardware_inventory_unknown";
  if (inventory.system_ram_bucket === "below_16_gib_class") return "insufficient_system_ram";
  if (inventory.cuda_state === "unknown") return "cuda_inventory_unknown";
  if (inventory.cuda_state === "unavailable") return "cuda_unavailable";
  if (inventory.cuda_vram_bucket === null) return "cuda_inventory_unknown";
  if (inventory.cuda_vram_bucket === "below_8_gib_class") return "insufficient_cuda_vram";
  if ((entry.observed_peak_gpu_allocation_mib ?? 0) > 6_144) return "child_gpu_allocation_ceiling_exceeded";
  if ((entry.observed_peak_child_rss_mib ?? 0) > 8_192) return "child_rss_ceiling_exceeded";
  return entry.resource_measurement_state === "complete"
    ? "exploratory_resource_fit"
    : "resource_measurement_missing";
}

export function deriveModelCompatibilityDisposition(
  inventory: ModelRuntimeInventory,
  entry: FrozenModelCompatibilityConfiguration,
): Pick<ModelCompatibilityEntry, "status" | "reason_codes"> {
  const reason = expectedResourceReason(inventory, entry);
  return {
    status: reason === "exploratory_resource_fit" || reason === "resource_measurement_missing"
      ? "research_only"
      : "unavailable",
    reason_codes: [reason],
  };
}

function parseEntry(
  value: unknown,
  inventory: ModelRuntimeInventory,
  expected: FrozenModelCompatibilityConfiguration,
): ModelCompatibilityEntry {
  const entry = row(value);
  exact(entry, ENTRY_KEYS);
  const configurationKey = safeToken(entry.configuration_key, 96);
  const modelKey = safeToken(entry.model_key, 64);
  if (
    typeof entry.repository_id !== "string" || entry.repository_id.length > 192
    || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(entry.repository_id)
    || entry.repository_id.includes("..")
    || typeof entry.revision !== "string" || !/^[a-f0-9]{40}$/.test(entry.revision)
  ) invalid();
  oneOf(entry.task, ["requirement_action_retrieval", "scoped_nli", "binary_nli", "pair_reranking", "structured_rubric"] as const);
  oneOf(entry.role, ["retrieval", "reranking", "scoped_nli", "binary_nli", "structured_rubric"] as const);
  if (entry.language_scope !== "english_polish") invalid();
  oneOf(entry.license_spdx, ["MIT", "Apache-2.0"] as const);
  const status = oneOf(entry.status, ["research_only", "unavailable"] as const);
  const reasons = stringArray(entry.reason_codes, RESOURCE_REASONS, 2);
  if (reasons.length < 1) invalid();
  const quantization = oneOf(entry.quantization, ["none", "bitsandbytes_nf4"] as const);
  safeToken(entry.dtype, 64);
  safeToken(entry.runtime, 96);
  const method = oneOf(entry.measurement_method, [
    "torch_cuda_max_memory_allocated", "documented_approximate_gpu_peak_only", "not_measured",
  ] as const);
  const precision = oneOf(entry.measurement_precision, [
    "observed_to_0_001_mib", "documented_approximate_0_01_gib", "not_measured",
  ] as const);
  const source = safeToken(entry.measurement_source, 96);
  const measurementState = oneOf(entry.resource_measurement_state, ["complete", "partial", "missing"] as const);
  const gpuPeak = nullableFinite(entry.observed_peak_gpu_allocation_mib);
  const rssPeak = nullableFinite(entry.observed_peak_child_rss_mib);
  if (entry.benchmark_key !== null) safeBenchmarkKey(entry.benchmark_key);
  nullableInteger(entry.synthetic_case_count);
  if (
    entry.trust_remote_code !== false || entry.product_enabled !== false
    || entry.activation_allowed !== false || entry.download_allowed !== false
  ) invalid();

  const present = Number(gpuPeak !== null) + Number(rssPeak !== null);
  const expectedState = present === 2 ? "complete" : present === 1 ? "partial" : "missing";
  if (measurementState !== expectedState) invalid();
  if (method === "torch_cuda_max_memory_allocated" && (precision !== "observed_to_0_001_mib" || gpuPeak === null)) invalid();
  if (method === "documented_approximate_gpu_peak_only" && (
    configurationKey !== "qwen3_4b_rubric_bitsandbytes_nf4_child_v1"
    || modelKey !== "qwen3_4b_rubric" || quantization !== "bitsandbytes_nf4"
    || precision !== "documented_approximate_0_01_gib"
    || source !== "real_metrics_campaign_diagnostic_2026_08_17"
    || gpuPeak !== 3_932.16 || rssPeak !== null || measurementState !== "partial"
  )) invalid();
  if (method === "not_measured" && (precision !== "not_measured" || gpuPeak !== null)) invalid();
  if (quantization === "bitsandbytes_nf4" && method !== "documented_approximate_gpu_peak_only") invalid();

  for (const key of IMMUTABLE_ENTRY_KEYS) {
    if (!Object.is(entry[key], expected[key])) invalid();
  }

  const typed = value as ModelCompatibilityEntry;
  const disposition = deriveModelCompatibilityDisposition(inventory, expected);
  if (
    reasons.length !== 1 || reasons[0] !== disposition.reason_codes[0]
    || status !== disposition.status
  ) invalid();
  return typed;
}

/** Validate the complete versioned, content-free compatibility projection. */
export function parseModelCompatibilityCatalog(value: unknown): ModelCompatibilityCatalog {
  const catalog = row(value);
  exact(catalog, CATALOG_KEYS);
  if (
    catalog.catalog_version !== "reviewed-model-resource-fit-v3"
    || catalog.measurement_version !== "reviewed-runtime-configurations-2026-08-v3"
    || catalog.catalog_policy !== "exploratory_resource_fit_only"
    || catalog.content_free !== true || catalog.session_data_read !== false
    || catalog.cache_contents_read !== false || catalog.downloads_started !== false
    || catalog.activation_allowed !== false || catalog.local_only !== true
    || catalog.persisted !== false || catalog.synced !== false
    || !Array.isArray(catalog.models)
  ) invalid();
  const inventory = parseInventory(catalog.inventory);
  if (catalog.models.length !== FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS.length) invalid();
  const models = catalog.models.map((item, index) => parseEntry(
    item,
    inventory,
    FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS[index],
  ));
  return { ...catalog, inventory, models } as ModelCompatibilityCatalog;
}
