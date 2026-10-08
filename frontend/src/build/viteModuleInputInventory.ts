import type { Plugin } from "vite";
import { Buffer } from "node:buffer";

export const MODULE_INPUT_INVENTORY_FILE = "module-input-inventory.json";
export const MODULE_INPUT_INVENTORY_CONTRACT = "vite-rolldown-module-input-inventory.v1";

const HEX = /^[0-9a-f]{64}$/;
const SAFE_OUTPUT = /^[A-Za-z0-9._/-]+$/;
const SAFE_RELATIVE = /^[A-Za-z0-9._@/-]+$/;
const MAX_MODULES = 4096;
const MAX_CODE_BYTES = 16 * 1024 * 1024;
const MAX_CODE_TOTAL = 128 * 1024 * 1024;
const MAX_GRAPH_BYTES = 2 * 1024 * 1024;
const VIRTUALS = new Map([
  ["\0rolldown/runtime.js", "rolldown_runtime"],
  ["\0vite/dynamic-import-helper.js", "vite_dynamic_import_helper"],
  ["\0vite/modulepreload-polyfill.js", "vite_modulepreload_polyfill"],
  ["\0vite/preload-helper.js", "vite_preload_helper"],
  ["\0vite/wasm-helper.js", "vite_wasm_helper"],
]);
const QUERY_KEYS = new Set([
  "commonjs-proxy", "commonjs-es-import", "url", "raw", "worker", "sharedworker",
  "inline", "used", "import", "direct", "inline-css", "style-attr",
  "transform-only", "html-proxy",
]);

type Hash = (value: string | Uint8Array) => string;
type LockEntry = {
  version: string;
  integrity: string;
  dev: boolean;
  optional: boolean;
};
type Observed = { hash: string; size: number };
type PhysicalBinding = { lockKey: string; root: string | null };

export type ModuleInventoryOptions = {
  frontendRoot: string;
  packageLockBytes: Uint8Array;
  packageLockSha256: string;
  sourceManifestSha256: string | null;
  toolingManifestSha256: string | null;
  viteVersion: string;
  hash: Hash;
  packageBindingsBytes?: Uint8Array;
  packageBindingsSha256?: string;
};

function fail(code: string): never {
  throw new Error(code);
}

export function releaseInventoryEnabled(source: string | undefined, tooling: string | undefined,
  mapping: string | undefined, mappingHash: string | undefined): boolean {
  const present = [source, tooling, mapping, mappingHash].map(value => value !== undefined);
  if (present.every(value => !value)) return false;
  if (!present.every(Boolean) || !safeDigest(source) || !safeDigest(tooling) || !safeDigest(mappingHash) || !mapping) {
    fail("module_input_binding_invalid");
  }
  return true;
}

function bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function normalizePath(value: string): string {
  return value.replace(/\\/g, "/").replace(/\/$/, "");
}

function lexical(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function segmentsUnsafe(normalized: string): boolean {
  return normalized.startsWith("/") || normalized.includes("//") || normalized.includes(":")
    || normalized.split("/").some((part) => !part || part === "." || part === ".."
      || /[<>"|?*\u0000-\u001f]/.test(part) || /[. ]$/.test(part)
      || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part));
}

function safeDigest(value: unknown): value is string {
  return typeof value === "string" && HEX.test(value);
}

function safeVersion(value: unknown): value is string {
  return typeof value === "string" && /^[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}$/.test(value);
}

function safeSha512Integrity(value: unknown): value is string {
  if (typeof value !== "string" || !/^sha512-[A-Za-z0-9+/]+={0,2}$/.test(value)) return false;
  const encoded = value.slice(7);
  try {
    const decoded = Buffer.from(encoded, "base64");
    return decoded.byteLength === 64 && decoded.toString("base64") === encoded;
  } catch {
    return false;
  }
}

function safeOutput(value: string): string {
  const normalized = normalizePath(value);
  if (!SAFE_OUTPUT.test(normalized) || segmentsUnsafe(normalized)) {
    fail("module_input_output_invalid");
  }
  return normalized;
}

function safeRelative(value: string): string {
  const normalized = normalizePath(value);
  if (!SAFE_RELATIVE.test(normalized) || segmentsUnsafe(normalized)) {
    fail("module_input_path_unsafe");
  }
  return normalized;
}

function packageName(instanceKey: string): string {
  const tail = instanceKey.slice(instanceKey.lastIndexOf("node_modules/") + 13);
  const parts = tail.split("/");
  const name = parts[0]?.startsWith("@") ? `${parts[0]}/${parts[1] ?? ""}` : parts[0];
  if (!name || !/^(@[A-Za-z0-9._-]+\/)?[A-Za-z0-9._-]+$/.test(name)) {
    fail("module_input_lock_invalid");
  }
  return name;
}

function rejectDuplicateJsonKeys(text: string): void {
  const stack: Array<{ kind: "object" | "array"; keys?: Set<string>; expectKey?: boolean }> = [];
  const whitespace = /\s/;
  for (let index = 0; index < text.length;) {
    const character = text[index];
    if (whitespace.test(character)) { index += 1; continue; }
    if (character === "{") {
      stack.push({ kind: "object", keys: new Set(), expectKey: true }); index += 1; continue;
    }
    if (character === "[") { stack.push({ kind: "array" }); index += 1; continue; }
    if (character === "}" || character === "]") { stack.pop(); index += 1; continue; }
    if (character === ",") {
      const current = stack[stack.length - 1];
      if (current?.kind === "object") current.expectKey = true;
      index += 1; continue;
    }
    if (character !== "\"") { index += 1; continue; }
    const start = index;
    index += 1;
    while (index < text.length) {
      if (text[index] === "\\") { index += 2; continue; }
      if (text[index] === "\"") { index += 1; break; }
      index += 1;
    }
    const current = stack[stack.length - 1];
    let lookahead = index;
    while (lookahead < text.length && whitespace.test(text[lookahead])) lookahead += 1;
    if (current?.kind === "object" && current.expectKey && text[lookahead] === ":") {
      const key = JSON.parse(text.slice(start, index)) as string;
      if (current.keys!.has(key)) fail("module_input_lock_invalid");
      current.keys!.add(key);
      current.expectKey = false;
    }
  }
}

export function parseLock(raw: Uint8Array, expectedSha256: string, hash: Hash): Map<string, LockEntry> {
  if (raw.byteLength > 2 * 1024 * 1024 || !safeDigest(expectedSha256) || hash(raw) !== expectedSha256) {
    fail("module_input_lock_invalid");
  }
  let text: string;
  let value: unknown;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    rejectDuplicateJsonKeys(text);
    value = JSON.parse(text);
  } catch {
    fail("module_input_lock_invalid");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail("module_input_lock_invalid");
  }
  const root = value as { lockfileVersion?: unknown; packages?: unknown };
  if (root.lockfileVersion !== 3 || !root.packages || typeof root.packages !== "object"
    || Array.isArray(root.packages)) {
    fail("module_input_lock_invalid");
  }
  const result = new Map<string, LockEntry>();
  for (const [rawKey, rawEntry] of Object.entries(root.packages as Record<string, unknown>)) {
    if (!rawKey) continue;
    const key = safeRelative(rawKey);
    if (!rawEntry || typeof rawEntry !== "object" || Array.isArray(rawEntry)) {
      fail("module_input_lock_invalid");
    }
    const entry = rawEntry as Record<string, unknown>;
    if (!key.startsWith("node_modules/") || !safeVersion(entry.version)
      || !safeSha512Integrity(entry.integrity)
      || ("dev" in entry && typeof entry.dev !== "boolean")
      || ("optional" in entry && typeof entry.optional !== "boolean")) {
      fail("module_input_lock_invalid");
    }
    result.set(key, {
      version: entry.version as string,
      integrity: entry.integrity,
      dev: entry.dev === true,
      optional: entry.optional === true,
    });
  }
  if (!result.size || result.size > 4096) fail("module_input_lock_invalid");
  return result;
}

function splitId(rawId: string): { base: string; queryKinds: string[] } {
  const index = rawId.indexOf("?");
  const base = index < 0 ? rawId : rawId.slice(0, index);
  const query = index < 0 ? "" : rawId.slice(index + 1);
  const queryKinds = query ? query.split("&").map((part) => {
    if (!part || part.includes("=") || !QUERY_KEYS.has(part)) fail("module_input_query_unknown");
    return part;
  }) : [];
  return { base, queryKinds: Array.from(new Set(queryKinds)).sort(lexical) };
}

function under(root: string, value: string): string | null {
  const windows = /^[A-Za-z]:\//.test(root);
  const left = windows ? root.toLowerCase() : root;
  const right = windows ? value.toLowerCase() : value;
  if (right === left) return "";
  return right.startsWith(`${left}/`) ? value.slice(root.length + 1) : null;
}

export function parsePackageBindings(raw: Uint8Array, expectedHash: string, frontendRoot: string,
  lock: Map<string, LockEntry>, lockHash: string, hash: Hash): PhysicalBinding[] {
  if (raw.byteLength > MAX_GRAPH_BYTES || !safeDigest(expectedHash) || hash(raw) !== expectedHash) {
    fail("module_input_binding_invalid");
  }
  if (raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) fail("module_input_binding_invalid");
  let text: string, value: any;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(raw); value = JSON.parse(text); }
  catch { fail("module_input_binding_invalid"); }
  if (!value || Array.isArray(value) || typeof value !== "object"
    || Object.keys(value).sort().join(",") !== "contract,entries,package_lock_sha256"
    || value.contract !== "frontend-package-physical-bindings.v1" || value.package_lock_sha256 !== lockHash
    || !Array.isArray(value.entries) || value.entries.length !== lock.size) fail("module_input_binding_invalid");
  const seen = new Set<string>(), keys: string[] = [], result: PhysicalBinding[] = [];
  const windows = /^[A-Za-z]:\//.test(frontendRoot);
  for (const entry of value.entries) {
    if (!entry || Array.isArray(entry) || typeof entry !== "object"
      || Object.keys(entry).sort().join(",") !== "lock_key,physical_root"
      || typeof entry.lock_key !== "string" || !lock.has(entry.lock_key)) fail("module_input_binding_invalid");
    keys.push(entry.lock_key);
    let root: string | null = null;
    if (entry.physical_root !== null) {
      const rawRoot = entry.physical_root;
      if (typeof rawRoot !== "string" || rawRoot.length > 4096 || /[\\\u0000-\u001f<>"|?*]/.test(rawRoot)
        || rawRoot.replace(/^[A-Za-z]:/, "").includes(":")
        || rawRoot.endsWith("/") || rawRoot.includes("//")
        || rawRoot.split("/").some((part: string) => part === "." || part === ".." || /[. ]$/.test(part))) {
        fail("module_input_binding_invalid");
      }
      const relative = under(`${frontendRoot}/node_modules`, rawRoot);
      if (relative === null || !relative) fail("module_input_binding_invalid");
      const identity = windows ? rawRoot.toLowerCase() : rawRoot;
      if (seen.has(identity)) fail("module_input_binding_invalid");
      seen.add(identity); root = rawRoot;
    }
    result.push({ lockKey: entry.lock_key, root });
  }
  if (keys.join("\n") !== Array.from(lock.keys()).sort(lexical).join("\n")) fail("module_input_binding_invalid");
  // This internal file is emitted canonically by Python. Exact reserialization
  // refuses duplicate keys and alternate encodings without a second JSON parser.
  const canonical = { contract: value.contract, entries: result.map(item => ({ lock_key: item.lockKey,
    physical_root: item.root })), package_lock_sha256: value.package_lock_sha256 };
  if (text! !== `${JSON.stringify(canonical)}\n`) fail("module_input_binding_invalid");
  return result.sort((a, b) => (b.root?.length ?? 0) - (a.root?.length ?? 0) || lexical(a.lockKey, b.lockKey));
}

function canonicalModule(rawId: string, frontendRoot: string, lock: Map<string, LockEntry>, bindings?: PhysicalBinding[]) {
  const { base: rawBase, queryKinds } = splitId(rawId);
  const virtualKind = VIRTUALS.get(rawBase);
  if (rawBase.startsWith("\0")) {
    if (!virtualKind) fail("module_input_virtual_unknown");
    return { canonicalId: `virtual:${virtualKind}:${queryKinds.join(",")}`, kind: "virtual" as const,
      queryKinds, virtualKind };
  }
  const base = normalizePath(rawBase);
  if (base.split("/").includes("..")) fail("module_input_path_unsafe");
  const relative = under(frontendRoot, base);
  if (relative === null || !relative) fail("module_input_path_unsafe");
  if (under(`${frontendRoot}/node_modules`, base) === null) {
    const safe = safeRelative(relative);
    return { canonicalId: `source:${safe}:${queryKinds.join(",")}`, kind: "source" as const,
      queryKinds, sourceRelativePath: safe };
  }
  // Physical pnpm store syntax is private and need not satisfy public logical
  // path grammar. Translate through the reviewed map before validating the tail.
  if (bindings) {
    const binding = bindings.find(item => item.root !== null && under(item.root, base) !== null);
    if (!binding || binding.root === null) fail("module_input_physical_binding_missing");
    const tail = under(binding.root, base)!;
    const relativePath = safeRelative(tail || "package-root");
    const logical = `${binding.lockKey}/${relativePath}`;
    const owner = Array.from(lock.keys()).sort((a, b) => b.length - a.length || lexical(a, b))
      .find(key => logical === key || logical.startsWith(`${key}/`));
    if (owner !== binding.lockKey) fail("module_input_logical_owner_mismatch");
    const entry = lock.get(binding.lockKey)!;
    return { canonicalId: `package:${binding.lockKey}:${relativePath}:${queryKinds.join(",")}`,
      kind: "package" as const, queryKinds, packageInstanceLockKey: binding.lockKey,
      packageName: packageName(binding.lockKey), version: entry.version, integrity: entry.integrity,
      dev: entry.dev, optional: entry.optional, packageRelativePath: relativePath };
  }
  const safe = safeRelative(relative);
  const keys = Array.from(lock.keys()).sort((a, b) => b.length - a.length || lexical(a, b));
  const instanceKey = keys.find((key) => safe === key || safe.startsWith(`${key}/`));
  if (!instanceKey) fail("module_input_logical_binding_missing");
  const entry = lock.get(instanceKey)!;
  const relativePath = safe === instanceKey ? "package-root" : safe.slice(instanceKey.length + 1);
  const name = packageName(instanceKey);
  return {
    canonicalId: `package:${instanceKey}:${relativePath}:${queryKinds.join(",")}`,
    kind: "package" as const, queryKinds, packageInstanceLockKey: instanceKey,
    packageName: name, version: entry.version, integrity: entry.integrity,
    dev: entry.dev, optional: entry.optional, packageRelativePath: relativePath,
  };
}

export function moduleInputInventoryPlugin(options: ModuleInventoryOptions): Plugin {
  const frontendRoot = normalizePath(options.frontendRoot);
  const lock = parseLock(options.packageLockBytes, options.packageLockSha256, options.hash);
  if ((options.packageBindingsBytes === undefined) !== (options.packageBindingsSha256 === undefined)) {
    fail("module_input_binding_invalid");
  }
  const bindings = options.packageBindingsBytes === undefined ? undefined
    : parsePackageBindings(options.packageBindingsBytes, options.packageBindingsSha256!, frontendRoot,
      lock, options.packageLockSha256, options.hash);
  if (!safeVersion(options.viteVersion)
    || (options.sourceManifestSha256 !== null && !safeDigest(options.sourceManifestSha256))
    || (options.toolingManifestSha256 !== null && !safeDigest(options.toolingManifestSha256))) {
    fail("module_input_binding_invalid");
  }
  const observed = new Map<string, Observed>();
  let total = 0;
  return {
    name: "prompt-enhancer:module-input-inventory",
    apply: "build",
    enforce: "post",
    buildStart() {
      observed.clear();
      total = 0;
    },
    transform(code, id) {
      const size = bytes(code);
      if (size > MAX_CODE_BYTES || total + size > MAX_CODE_TOTAL) fail("module_input_code_oversize");
      const next = { hash: options.hash(code), size };
      const prior = observed.get(id);
      if (prior && (prior.hash !== next.hash || prior.size !== next.size)) fail("module_input_transform_conflict");
      if (!prior) total += size;
      observed.set(id, next);
      return null;
    },
    generateBundle: {
      order: "post",
      handler(_outputOptions, bundle) {
        const chunks = Object.values(bundle).filter((item) => item.type === "chunk");
        const membership = new Map<string, string[]>();
        for (const chunk of chunks) {
          for (const id of Object.keys(chunk.modules)) {
            const names = membership.get(id) ?? [];
            names.push(safeOutput(chunk.fileName));
            membership.set(id, names);
          }
        }
        if (!membership.size || membership.size > MAX_MODULES
          || Object.keys(bundle).length > MAX_MODULES) fail("module_input_count_invalid");
        const canonicalSeen = new Set<string>();
        const modules = Array.from(membership).map(([id, chunkNames]) => {
          const code = observed.get(id);
          const item = canonicalModule(id, frontendRoot, lock, bindings);
          if (canonicalSeen.has(item.canonicalId)) fail("module_input_identity_duplicate");
          canonicalSeen.add(item.canonicalId);
          const common = {
            canonical_id: item.canonicalId, kind: item.kind, query_kinds: item.queryKinds,
            transform_hook_code_sha256: code?.hash ?? null,
            transform_hook_code_size_bytes: code?.size ?? null,
            chunks: Array.from(new Set(chunkNames)).sort(lexical),
          };
          if (item.kind === "source") return { ...common, source_relative_path: item.sourceRelativePath };
          if (item.kind === "virtual") return { ...common, virtual_kind: item.virtualKind };
          return { ...common, package_instance_lock_key: item.packageInstanceLockKey,
            package_name: item.packageName, version: item.version, integrity: item.integrity,
            dev: item.dev, optional: item.optional, package_relative_path: item.packageRelativePath };
        }).sort((a, b) => lexical(a.canonical_id, b.canonical_id));
        let outputBytes = 0;
        const chunkRecords = chunks.map((chunk) => {
          const size = bytes(chunk.code);
          outputBytes += size;
          const hash = options.hash(chunk.code);
          if (size > MAX_CODE_BYTES || !safeDigest(hash)) fail("module_input_output_oversize");
          return { file_name: safeOutput(chunk.fileName), final_chunk_sha256: hash,
            size_bytes: size, module_count: Object.keys(chunk.modules).length };
        }).sort((a, b) => lexical(a.file_name, b.file_name));
        const assets = Object.values(bundle).filter((item) => item.type === "asset").map((asset) => {
          const fileName = safeOutput(asset.fileName);
          const source = typeof asset.source === "string" ? asset.source : new Uint8Array(asset.source);
          const suffix = fileName.toLowerCase();
          const kind = suffix === ".vite/manifest.json" ? "vite_manifest"
            : suffix.endsWith(".html") ? "html" : suffix.endsWith(".css") ? "css"
              : /\.(png|jpe?g|webp|svg|woff2?)$/.test(suffix) ? "static_asset"
                : /\.(m?js|wasm)$/.test(suffix) ? "opaque_worker_or_dependency_asset" : "opaque_asset";
          const size = typeof source === "string" ? bytes(source) : source.byteLength;
          outputBytes += size;
          const hash = options.hash(source);
          if (size > MAX_CODE_BYTES || !safeDigest(hash)) fail("module_input_output_oversize");
          return { file_name: fileName, sha256: hash, size_bytes: size, kind };
        }).sort((a, b) => lexical(a.file_name, b.file_name));
        if (outputBytes > MAX_CODE_TOTAL) fail("module_input_output_oversize");
        const gaps = new Set<string>();
        if (options.sourceManifestSha256 === null) gaps.add("source_manifest_binding_missing");
        if (options.toolingManifestSha256 === null) gaps.add("tooling_manifest_binding_missing");
        if (modules.some((item) => item.transform_hook_code_sha256 === null)) {
          gaps.add("transform_hook_observation_missing");
        }
        if (modules.some((item) => item.query_kinds.some((query) => ["url", "worker", "sharedworker"].includes(query)))
          || assets.some((item) => item.kind !== "vite_manifest")) {
          gaps.add("opaque_asset_dependency_license_mapping_unverified");
        }
        const rolldownVersion = (this.meta as { rolldownVersion?: unknown }).rolldownVersion;
        if (!safeVersion(rolldownVersion)) fail("module_input_runtime_invalid");
        const report = {
          contract: MODULE_INPUT_INVENTORY_CONTRACT, vite_version: options.viteVersion,
          rolldown_version: rolldownVersion, package_lock_sha256: options.packageLockSha256,
          package_lock_size_bytes: options.packageLockBytes.byteLength,
          source_manifest_sha256: options.sourceManifestSha256,
          tooling_manifest_sha256: options.toolingManifestSha256,
          modules, chunks: chunkRecords, assets,
          actual_bundled_modules_only: true, whole_production_lock_closure_claimed: false,
          complete: false, unresolved_gaps: Array.from(gaps).sort(lexical),
        };
        const source = `${JSON.stringify(report)}\n`;
        if (bytes(source) > MAX_GRAPH_BYTES) fail("module_input_graph_oversize");
        this.emitFile({ type: "asset", fileName: MODULE_INPUT_INVENTORY_FILE,
          source });
      },
    },
  };
}
