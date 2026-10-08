import { describe, expect, it } from "vitest";
import { createHttpTransport } from "../api/httpTransport";
import { createSyntheticTransport } from "../api/syntheticTransport";
import {
  createRuntimeComposition,
  resolveRuntimeDataMode,
} from "./runtimeMode";

describe("runtime data mode", () => {
  it("keeps ordinary Vite development synthetic", () => {
    expect(
      resolveRuntimeDataMode({ development: true, viteMode: "development" }),
    ).toBe("synthetic_demo");
  });

  it("allows an explicit local-backend development mode", () => {
    expect(resolveRuntimeDataMode({ development: true, viteMode: "real" })).toBe(
      "local_real",
    );
  });

  it("keeps production builds on the integrated local backend", () => {
    expect(
      resolveRuntimeDataMode({ development: false, viteMode: "production" }),
    ).toBe("local_real");
  });

  it("binds each implemented mode to its matching tagged transport", () => {
    const synthetic = createSyntheticTransport();
    const local = createHttpTransport({
      fetch: (() => Promise.reject(new Error("not called"))) as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    expect(
      createRuntimeComposition("synthetic_demo", synthetic),
    ).toMatchObject({
      mode: "synthetic_demo",
      transport: { runtimeKind: "synthetic_fixture" },
    });
    expect(createRuntimeComposition("local_real", local)).toMatchObject({
      mode: "local_real",
      transport: { runtimeKind: "local_loopback" },
    });
  });

  it("fails closed when local-real mode is paired with fixture transport", () => {
    expect(() =>
      createRuntimeComposition("local_real", createSyntheticTransport()),
    ).toThrow(/do not match/i);
  });

  it("fails closed when synthetic-demo mode is paired with loopback transport", () => {
    const local = createHttpTransport({
      fetch: (() => Promise.reject(new Error("not called"))) as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    expect(() => createRuntimeComposition("synthetic_demo", local)).toThrow(
      /do not match/i,
    );
  });
});
