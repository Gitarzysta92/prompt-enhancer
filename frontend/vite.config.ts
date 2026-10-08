import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { closeSync, fstatSync, lstatSync, openSync, readFileSync, readSync } from "node:fs";
import { isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { version as viteVersion, type ProxyOptions } from "vite";
import { moduleInputInventoryPlugin, releaseInventoryEnabled } from "./src/build/viteModuleInputInventory";

const LOCAL_API_ORIGIN = "http://127.0.0.1:8766";
const FRONTEND_ROOT = fileURLToPath(new URL(".", import.meta.url));
const PACKAGE_LOCK = readFileSync(new URL("./package-lock.json", import.meta.url));
const digest = (value: string | Uint8Array) => createHash("sha256").update(value).digest("hex");
const optionalDigest = (value: string | undefined) => value === undefined ? null : value;
const INVENTORY_ENABLED = releaseInventoryEnabled(process.env.PROMPT_ENHANCER_FRONTEND_SOURCE_MANIFEST_SHA256,
  process.env.PROMPT_ENHANCER_FRONTEND_TOOLING_MANIFEST_SHA256, process.env.PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS,
  process.env.PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS_SHA256);
function packageBindings() {
  const file = process.env.PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS;
  const expected = process.env.PROMPT_ENHANCER_FRONTEND_PACKAGE_BINDINGS_SHA256;
  if (file === undefined && expected === undefined) return {};
  const refused = () => { throw new Error("module_input_binding_invalid"); };
  if (!file || !expected || !/^[0-9a-f]{64}$/.test(expected) || !isAbsolute(file)
    || file.startsWith("\\\\") || file.startsWith("//")) return refused();
  try {
    const before = lstatSync(file);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > 2 * 1024 * 1024) return refused();
    const fd = openSync(file, "r");
    try {
      const opened = fstatSync(fd);
      if (!opened.isFile() || opened.ino !== before.ino || opened.dev !== before.dev || opened.size !== before.size) return refused();
      const bytes = Buffer.alloc(before.size + 1);
      let offset = 0;
      while (offset < bytes.length) {
        const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
        if (!count) break;
        offset += count;
      }
      const after = fstatSync(fd), pathAfter = lstatSync(file);
      if (offset !== before.size || after.ino !== opened.ino || after.size !== opened.size
        || after.mtimeMs !== opened.mtimeMs || after.ctimeMs !== opened.ctimeMs
        || pathAfter.ino !== before.ino || pathAfter.mtimeMs !== before.mtimeMs || pathAfter.ctimeMs !== before.ctimeMs) return refused();
      const value = bytes.subarray(0, offset);
      if (digest(value) !== expected) return refused();
      return { packageBindingsBytes: value, packageBindingsSha256: expected };
    } finally { closeSync(fd); }
  } catch { return refused(); }
}

function localApiProxy(): ProxyOptions {
  return {
    target: LOCAL_API_ORIGIN,
    changeOrigin: true,
    configure(proxy) {
      proxy.on("proxyReq", (request) => {
        // The browser and Vite are same-origin. Re-establish that invariant at
        // the loopback backend after the development proxy changes the Host.
        request.setHeader("Origin", LOCAL_API_ORIGIN);
      });
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    ...(INVENTORY_ENABLED ? [moduleInputInventoryPlugin({
      frontendRoot: FRONTEND_ROOT,
      packageLockBytes: PACKAGE_LOCK,
      packageLockSha256: digest(PACKAGE_LOCK),
      sourceManifestSha256: optionalDigest(process.env.PROMPT_ENHANCER_FRONTEND_SOURCE_MANIFEST_SHA256),
      toolingManifestSha256: optionalDigest(process.env.PROMPT_ENHANCER_FRONTEND_TOOLING_MANIFEST_SHA256),
      viteVersion,
      hash: digest,
      ...packageBindings(),
    })] : []),
  ],
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy:
      mode === "real"
        ? {
            "/auth": localApiProxy(),
            "/health": localApiProxy(),
            "/v1": localApiProxy(),
          }
        : undefined,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
  build: {
    // Keep the emitted graph inspectable for the release bundle budget check.
    manifest: true,
    // Runtime resource discovery is package-owned. This generated directory is
    // ignored and rebuilt from the committed lockfile before staging.
    outDir: "../src/prompt_enhancer/_resources/dashboard",
    emptyOutDir: true,
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    // Keep the locked quality gate stable on high-core hosts: each JSDOM file
    // worker is memory- and transform-heavy, and unbounded fan-out can make
    // otherwise deterministic five-second interaction tests starve.
    maxWorkers: 2,
    // The Agent workspace is intentionally exercised as one large integration
    // surface. A bounded 15-second ceiling preserves hang detection while
    // avoiding false failures when Windows schedules its JSDOM worker behind
    // another transform-heavy file.
    testTimeout: 15_000,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    coverage: {
      reporter: ["text", "html"],
    },
  },
}));
