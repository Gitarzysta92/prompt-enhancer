import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  MODULE_INPUT_INVENTORY_CONTRACT,
  MODULE_INPUT_INVENTORY_FILE,
  moduleInputInventoryPlugin,
  parseLock,
  parsePackageBindings,
  releaseInventoryEnabled,
} from "./viteModuleInputInventory";

const ROOT = "C:/example/frontend";
const SRI = `sha512-${Buffer.alloc(64).toString("base64")}`;

function digest(value: string | Uint8Array): string {
  const content = typeof value === "string" ? new TextEncoder().encode(value) : value;
  let total = 0;
  for (const byte of content) total = (total * 33 + byte) >>> 0;
  return total.toString(16).padStart(64, "0");
}

function lockText(): string {
  return JSON.stringify({
    name: "synthetic-dashboard",
    lockfileVersion: 3,
    packages: {
      "": { name: "synthetic-dashboard", version: "0.0.0" },
      "node_modules/alpha": {
        version: "1.2.3", integrity: SRI,
      },
      "node_modules/alpha/node_modules/shared": {
        version: "2.0.0", integrity: SRI, dev: true, optional: true,
      },
    },
  });
}

const lockBytes = (value: string) => new TextEncoder().encode(value);
// Assemble package-manager syntax without email-shaped source literals.
const storeName = (name: string, version: string) => [name, version].join("@");

type Captured = { type: string; fileName: string; source: string };

function execute({ reverse = false, sourcePin = "a".repeat(64),
  toolingPin = "b".repeat(64), physical = false, upperCase = false } = {}): { report: any; encoded: string } {
  const lock = lockText();
  const alpha = physical ? `${ROOT}/node_modules/.pnpm/${storeName("alpha", "1.2.3")}(peer@1)/node_modules/alpha` : `${ROOT}/node_modules/alpha`;
  const shared = physical ? `${ROOT}/node_modules/.pnpm/${storeName("shared", "2.0.0")}/node_modules/shared` : `${ROOT}/node_modules/alpha/node_modules/shared`;
  const mapping = lockBytes(JSON.stringify({ contract: "frontend-package-physical-bindings.v1", entries: [
    { lock_key: "node_modules/alpha", physical_root: alpha },
    { lock_key: "node_modules/alpha/node_modules/shared", physical_root: shared },
  ], package_lock_sha256: digest(lockBytes(lock)) }) + "\n");
  const plugin = moduleInputInventoryPlugin({
    frontendRoot: ROOT,
    packageLockBytes: lockBytes(lock),
    packageLockSha256: digest(lockBytes(lock)),
    sourceManifestSha256: sourcePin,
    toolingManifestSha256: toolingPin,
    viteVersion: "8.1.5",
    hash: digest,
    ...(physical ? { packageBindingsBytes: mapping, packageBindingsSha256: digest(mapping) } : {}),
  }) as any;
  plugin.buildStart.call({});
  const ids = [
    `${ROOT}/src/main.tsx`,
    `${upperCase ? alpha.toUpperCase() : alpha}/index.js`,
    `${upperCase ? shared.toUpperCase() : shared}/worker.js?url`,
    "\0vite/preload-helper.js",
  ];
  for (const id of reverse ? [...ids].reverse() : ids) {
    plugin.transform.call({}, `observed:${id.length}`, id);
  }
  const modules = Object.fromEntries((reverse ? [...ids].reverse() : ids).map((id) => [id, {}]));
  const entries: [string, any][] = [
    ["assets/main.js", { type: "chunk", fileName: "assets/main.js", code: "final chunk", modules }],
    ["assets/site.css", { type: "asset", fileName: "assets/site.css", source: "body{}" }],
    [".vite/manifest.json", { type: "asset", fileName: ".vite/manifest.json", source: "{}" }],
  ];
  const bundle = Object.fromEntries(reverse ? entries.reverse() : entries);
  let captured: Captured | null = null;
  plugin.generateBundle.handler.call({
    meta: { rolldownVersion: "1.1.5", rollupVersion: "4.0.0" },
    emitFile(value: Captured) { captured = value; },
  }, {}, bundle);
  expect(captured).not.toBeNull();
  const result = captured as unknown as Captured;
  return { report: JSON.parse(result.source), encoded: result.source };
}

describe("Vite/Rolldown module input inventory", () => {
  it("maps pnpm physical roots before public logical grammar, including Windows case", () => {
    const ordinary = execute();
    for (const upperCase of [false, true]) {
      const physical = execute({ physical: true, upperCase });
      expect(physical.report.modules.map((item: any) => item.canonical_id))
        .toEqual(ordinary.report.modules.map((item: any) => item.canonical_id));
      expect(physical.encoded).not.toContain(".pnpm");
      expect(physical.encoded).not.toContain(ROOT);
    }
  });

  it("gates ordinary builds without accepting partial release settings", () => {
    expect(releaseInventoryEnabled(undefined, undefined, undefined, undefined)).toBe(false);
    const all = ["a".repeat(64), "b".repeat(64), "C:/example/private.json", "c".repeat(64)];
    expect(releaseInventoryEnabled(all[0], all[1], all[2], all[3])).toBe(true);
    for (let mask = 1; mask < 15; mask++) {
      const values = all.map((value, index) => mask & (1 << index) ? value : undefined);
      expect(() => releaseInventoryEnabled(values[0], values[1], values[2], values[3])).toThrow("module_input_binding_invalid");
    }
  });

  it("accepts missing bindings as missing and refuses ambiguity, outside roots and malformed mapping", () => {
    const text = lockText(), lock = parseLock(lockBytes(text), digest(lockBytes(text)), digest);
    const value = { contract: "frontend-package-physical-bindings.v1", entries: [
      { lock_key: "node_modules/alpha", physical_root: `${ROOT}/node_modules/.pnpm/${storeName("@example+alpha", "1.2.3")}(peer@1)/node_modules/alpha` as string | null },
      { lock_key: "node_modules/alpha/node_modules/shared", physical_root: null as string | null },
    ], package_lock_sha256: digest(lockBytes(text)) };
    const parse = (candidate: typeof value) => {
      const raw = lockBytes(JSON.stringify(candidate) + "\n");
      return parsePackageBindings(raw, digest(raw), ROOT, lock, digest(lockBytes(text)), digest);
    };
    expect(parse(value).filter(item => item.root === null)).toHaveLength(1);
    for (const root of ["C:/outside/alpha", `${ROOT}/node_modules/../outside`, "//example/share/alpha", `${ROOT}/node_modules/alpha:stream`]) {
      expect(() => parse({ ...value, entries: [{ ...value.entries[0], physical_root: root }, value.entries[1]] }))
        .toThrow("module_input_binding_invalid");
    }
    expect(() => parse({ ...value, entries: [value.entries[0], { ...value.entries[1], physical_root: value.entries[0].physical_root!.toUpperCase() }] }))
      .toThrow("module_input_binding_invalid");
    const duplicate = lockBytes((JSON.stringify(value) + "\n").replace('"contract":', '"contract":"duplicate","contract":'));
    expect(() => parsePackageBindings(duplicate, digest(duplicate), ROOT, lock, digest(lockBytes(text)), digest))
      .toThrow("module_input_binding_invalid");
  });
  it("emits a stable, path-free graph tied to exact chunks and lock instances", () => {
    const first = execute();
    const second = execute({ reverse: true });
    expect(second.encoded).toBe(first.encoded);
    expect(first.report.contract).toBe(MODULE_INPUT_INVENTORY_CONTRACT);
    expect(first.encoded).not.toContain(ROOT);
    expect(first.encoded).not.toContain("rollupVersion");
    expect(first.report.modules.map((item: any) => item.canonical_id)).toEqual([
      "package:node_modules/alpha/node_modules/shared:worker.js:url",
      "package:node_modules/alpha:index.js:",
      "source:src/main.tsx:",
      "virtual:vite_preload_helper:",
    ]);
    const nested = first.report.modules[0];
    expect(nested).toMatchObject({
      package_instance_lock_key: "node_modules/alpha/node_modules/shared",
      package_name: "shared", version: "2.0.0", integrity: SRI,
      dev: true, optional: true, query_kinds: ["url"],
    });
    expect(first.report.chunks).toEqual([{
      file_name: "assets/main.js", final_chunk_sha256: digest("final chunk"),
      size_bytes: 11, module_count: 4,
    }]);
    expect(first.report.assets.map((item: any) => item.kind)).toEqual(["vite_manifest", "css"]);
    expect(first.report.unresolved_gaps).toEqual([
      "opaque_asset_dependency_license_mapping_unverified",
    ]);
    expect(first.report.actual_bundled_modules_only).toBe(true);
    expect(first.report.whole_production_lock_closure_claimed).toBe(false);
    expect(first.report.complete).toBe(false);
  });

  it("keeps ordinary unbound builds explicitly incomplete", () => {
    const { report } = execute({ sourcePin: null as any, toolingPin: null as any });
    expect(report.source_manifest_sha256).toBeNull();
    expect(report.tooling_manifest_sha256).toBeNull();
    expect(report.unresolved_gaps).toEqual([
      "opaque_asset_dependency_license_mapping_unverified",
      "source_manifest_binding_missing",
      "tooling_manifest_binding_missing",
    ]);
  });

  it.each([
    ["unknown virtual", "\0synthetic-private-virtual", "module_input_virtual_unknown"],
    ["query with a value", `${ROOT}/src/main.tsx?html-proxy&index=1`, "module_input_query_unknown"],
    ["unknown query", `${ROOT}/src/main.tsx?private-query`, "module_input_query_unknown"],
    ["outside root", "C:/outside/private.ts", "module_input_path_unsafe"],
    ["unmapped package", `${ROOT}/node_modules/missing/index.js`, "module_input_logical_binding_missing"],
  ])("fails closed for %s without echoing the raw ID", (_name, id, code) => {
    const lock = lockText();
    const plugin = moduleInputInventoryPlugin({
      frontendRoot: ROOT, packageLockBytes: lockBytes(lock), packageLockSha256: digest(lockBytes(lock)),
      sourceManifestSha256: "a".repeat(64), toolingManifestSha256: "b".repeat(64),
      viteVersion: "8.1.5", hash: digest,
    }) as any;
    plugin.buildStart.call({});
    plugin.transform.call({}, "observed", id);
    let message = "";
    try {
      plugin.generateBundle.handler.call({
        meta: { rolldownVersion: "1.1.5" }, emitFile() {},
      }, {}, { "assets/main.js": {
        type: "chunk", fileName: "assets/main.js", code: "final", modules: { [id]: {} },
      } });
    } catch (error) {
      message = (error as Error).message;
    }
    expect(message).toBe(code);
    expect(message).not.toContain(id);
  });

  it.each([
    ["physical", `${ROOT}/node_modules/.pnpm/missing@1/node_modules/missing/index.js`, "module_input_physical_binding_missing"],
    ["owner", `${ROOT}/node_modules/.pnpm/alpha@1/node_modules/alpha/node_modules/shared/index.js`, "module_input_logical_owner_mismatch"],
  ])("distinguishes mapped %s refusal without echoing IDs", (_kind, id, expected) => {
    const lock = lockText();
    const mapping = lockBytes(JSON.stringify({ contract: "frontend-package-physical-bindings.v1", entries: [
      { lock_key: "node_modules/alpha", physical_root: `${ROOT}/node_modules/.pnpm/alpha@1/node_modules/alpha` },
      { lock_key: "node_modules/alpha/node_modules/shared", physical_root: null },
    ], package_lock_sha256: digest(lockBytes(lock)) }) + "\n");
    const plugin = moduleInputInventoryPlugin({
      frontendRoot: ROOT, packageLockBytes: lockBytes(lock), packageLockSha256: digest(lockBytes(lock)),
      sourceManifestSha256: "a".repeat(64), toolingManifestSha256: "b".repeat(64),
      packageBindingsBytes: mapping, packageBindingsSha256: digest(mapping), viteVersion: "8.1.5", hash: digest,
    }) as any;
    plugin.buildStart.call({}); plugin.transform.call({}, "observed", id);
    let message = "";
    try {
      plugin.generateBundle.handler.call({ meta: { rolldownVersion: "1.1.5" }, emitFile() {} }, {}, {
        "assets/main.js": { type: "chunk", fileName: "assets/main.js", code: "final", modules: { [id]: {} } },
      });
    } catch (error) { message = (error as Error).message; }
    expect(message).toBe(expected); expect(message).not.toContain(id);
  });

  it("records missing hook observations as an explicit gap and rejects canonical collisions", () => {
    const lock = lockText();
    const options = {
      frontendRoot: ROOT, packageLockBytes: lockBytes(lock), packageLockSha256: digest(lockBytes(lock)),
      sourceManifestSha256: "a".repeat(64), toolingManifestSha256: "b".repeat(64),
      viteVersion: "8.1.5", hash: digest,
    };
    const missing = moduleInputInventoryPlugin(options) as any;
    missing.buildStart.call({});
    let missingSource = "";
    missing.generateBundle.handler.call({
      meta: { rolldownVersion: "1.1.5" },
      emitFile(value: Captured) { missingSource = value.source; },
    }, {}, { "main.js": { type: "chunk", fileName: "main.js", code: "x",
      modules: { [`${ROOT}/src/main.tsx`]: {} } } });
    const missingReport = JSON.parse(missingSource);
    expect(missingReport.modules[0].transform_hook_code_sha256).toBeNull();
    expect(missingReport.unresolved_gaps).toContain("transform_hook_observation_missing");

    const collision = moduleInputInventoryPlugin(options) as any;
    collision.buildStart.call({});
    const forward = `${ROOT}/src/main.tsx`;
    const backward = `${ROOT}\\src\\main.tsx`;
    collision.transform.call({}, "same", forward);
    collision.transform.call({}, "same", backward);
    expect(() => collision.generateBundle.handler.call({
      meta: { rolldownVersion: "1.1.5" }, emitFile() {},
    }, {}, { "main.js": { type: "chunk", fileName: "main.js", code: "x",
      modules: { [forward]: {}, [backward]: {} } } })).toThrow("module_input_identity_duplicate");
  });

  it("rejects malformed lock metadata and invalid runtime metadata", () => {
    const malformed = JSON.stringify({ lockfileVersion: 3, packages: {
      "node_modules/alpha": { version: "bad\nversion", integrity: SRI },
    } });
    expect(() => moduleInputInventoryPlugin({
      frontendRoot: ROOT, packageLockBytes: lockBytes(malformed), packageLockSha256: digest(lockBytes(malformed)),
      sourceManifestSha256: null, toolingManifestSha256: null,
      viteVersion: "8.1.5", hash: digest,
    })).toThrow("module_input_lock_invalid");
    expect(MODULE_INPUT_INVENTORY_FILE).toBe("module-input-inventory.json");
  });

  it("accepts scoped lock instances and rejects Windows-invalid path components", () => {
    const scoped = JSON.stringify({ lockfileVersion: 3, packages: {
      "node_modules/@scope/pkg": { version: "1.0.0", integrity: SRI },
    } });
    expect(Array.from(parseLock(lockBytes(scoped), digest(lockBytes(scoped)), digest).keys()))
      .toEqual(["node_modules/@scope/pkg"]);
    const plugin = moduleInputInventoryPlugin({
      frontendRoot: ROOT, packageLockBytes: lockBytes(scoped),
      packageLockSha256: digest(lockBytes(scoped)), sourceManifestSha256: null,
      toolingManifestSha256: null, viteVersion: "8.1.5", hash: digest,
    }) as any;
    plugin.buildStart.call({});
    const scopedId = `${ROOT}/node_modules/@scope/pkg/index.js`;
    plugin.transform.call({}, "scoped", scopedId);
    let source = "";
    plugin.generateBundle.handler.call({
      meta: { rolldownVersion: "1.1.5" }, emitFile(value: Captured) { source = value.source; },
    }, {}, { "main.js": { type: "chunk", fileName: "main.js", code: "x",
      modules: { [scopedId]: {} } } });
    expect(JSON.parse(source).modules[0]).toMatchObject({
      package_instance_lock_key: "node_modules/@scope/pkg", package_name: "@scope/pkg",
    });
    for (const name of ["node_modules/CON/file", "node_modules/trailing./file", "node_modules/bad|name/file"]) {
      const invalid = JSON.stringify({ lockfileVersion: 3, packages: {
        [name]: { version: "1.0.0", integrity: SRI },
      } });
      expect(() => parseLock(lockBytes(invalid), digest(lockBytes(invalid)), digest))
        .toThrow("module_input_path_unsafe");
    }
  });

  it("rejects duplicate keys, null roots or entries, malformed SRI, and non-boolean flags", () => {
    const duplicate = `{"lockfileVersion":3,"packages":{"node_modules/alpha":{"version":"1.0.0","integrity":"${SRI}"},"node_modules/alpha":{"version":"2.0.0","integrity":"${SRI}"}}}`;
    const nullEntry = JSON.stringify({ lockfileVersion: 3, packages: { "node_modules/alpha": null } });
    const shortSri = JSON.stringify({ lockfileVersion: 3, packages: {
      "node_modules/alpha": { version: "1.0.0", integrity: "sha512-AAAAAAAAAAAAAAAA" },
    } });
    const noncanonicalSri = JSON.stringify({ lockfileVersion: 3, packages: {
      "node_modules/alpha": { version: "1.0.0", integrity: `sha512-${"A".repeat(85)}B==` },
    } });
    const badFlags = JSON.stringify({ lockfileVersion: 3, packages: {
      "node_modules/alpha": { version: "1.0.0", integrity: SRI, dev: 1, optional: "false" },
    } });
    for (const value of [duplicate, "null", nullEntry, shortSri, noncanonicalSri, badFlags]) {
      expect(() => parseLock(lockBytes(value), digest(lockBytes(value)), digest))
        .toThrow("module_input_lock_invalid");
    }
  });

  it("accepts the pinned local lockfile with its raw-byte digest", () => {
    const raw = readFileSync(resolve(process.cwd(), "package-lock.json"));
    const sha256 = createHash("sha256").update(raw).digest("hex");
    expect(parseLock(raw, sha256, (value) => createHash("sha256").update(value).digest("hex")).size)
      .toBe(289);
  });
});
