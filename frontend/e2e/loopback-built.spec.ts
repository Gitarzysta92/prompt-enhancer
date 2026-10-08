import { expect, test, type Locator, type Page } from "@playwright/test";

const BASE_URL = process.env.PE_CONVERGENCE_BASE_URL!;
const WORKSPACE = process.env.PE_CONVERGENCE_WORKSPACE!;
const RECOVERY_PROJECT = "Recovery example project";
const RECOVERY_CHAT = "Recovered example chat";
const PROJECT = "Loopback example project";
const CHAT = "example-workspace";
const RENAMED_CHAT = "Loopback verified chat";
const DISPOSABLE_PROJECT = "Disposable example project";

interface Diagnostics {
  consoleErrors: number;
  externalRequests: number;
  pageErrors: number;
  serverFailures: string[];
}

const diagnosticsByPage = new WeakMap<Page, Diagnostics>();

function endpointFamily(rawUrl: string): string {
  const path = new URL(rawUrl).pathname;
  return path
    .replace(/[a-f0-9]{64}/giu, ":digest")
    .replace(/[a-f0-9]{32}/giu, ":id")
    .replace(/[0-9a-f]{8}-[0-9a-f-]{27,36}/giu, ":uuid");
}

test.beforeEach(async ({ page }) => {
  const diagnostics: Diagnostics = {
    consoleErrors: 0,
    externalRequests: 0,
    pageErrors: 0,
    serverFailures: [],
  };
  diagnosticsByPage.set(page, diagnostics);
  page.on("console", (message) => {
    if (message.type() === "error") diagnostics.consoleErrors += 1;
  });
  page.on("pageerror", () => {
    diagnostics.pageErrors += 1;
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && url.origin !== BASE_URL) {
      diagnostics.externalRequests += 1;
    }
  });
  page.on("requestfailed", (request) => {
    const reason = request.failure()?.errorText ?? "network";
    if (/ERR_ABORTED|NS_BINDING_ABORTED|cancelled/iu.test(reason)) return;
    if (new URL(request.url()).origin === BASE_URL) {
      diagnostics.serverFailures.push(`${request.method()} ${endpointFamily(request.url())} network`);
    }
  });
  page.on("response", (response) => {
    if (new URL(response.url()).origin === BASE_URL && response.status() >= 500) {
      diagnostics.serverFailures.push(`${response.request().method()} ${endpointFamily(response.url())} ${response.status()}`);
    }
  });
});

test.afterEach(async ({ page }) => {
  const diagnostics = diagnosticsByPage.get(page);
  expect(diagnostics, "diagnostics were installed before navigation").toBeDefined();
  expect(diagnostics!.externalRequests, "the disposable gate made no off-origin request").toBe(0);
  expect(diagnostics!.pageErrors, "the built dashboard raised no page exception").toBe(0);
  expect(diagnostics!.consoleErrors, "the built dashboard raised no console error").toBe(0);
  expect(diagnostics!.serverFailures, "the real API returned no network/5xx failure").toEqual([]);
});

async function openAgent(page: Page): Promise<Locator> {
  await page.goto("/agent");
  const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
  await expect(rail).toBeVisible();
  return rail;
}

async function selectProject(page: Page, name: string): Promise<void> {
  const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
  const project = rail.locator(".agent-rail__project-pick").filter({ hasText: name });
  await expect(project).toBeVisible();
  await project.click();
}

async function selectChat(page: Page, title: string): Promise<void> {
  const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
  const chat = rail.locator(".agent-rail__session-pick").filter({ hasText: title });
  await expect(chat).toBeVisible();
  await chat.click();
}

async function openLoopbackChat(page: Page): Promise<void> {
  await openAgent(page);
  await selectProject(page, PROJECT);
  await selectChat(page, RENAMED_CHAT);
  await expect(page.getByRole("heading", { level: 1, name: RENAMED_CHAT })).toBeVisible();
}

test.describe.serial("built frontend with the disposable real loopback backend", () => {
  test("boots the production SPA, issues browser auth, and reports live workers", async ({ page }) => {
    const navigation = await page.goto("/overview");
    expect(navigation?.status()).toBe(200);
    expect(navigation?.headers()["content-security-policy"]).toContain("default-src 'self'");
    expect(navigation?.headers()["x-frame-options"]).toBe("DENY");
    expect(navigation?.headers()["cache-control"]).toContain("no-store");
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await expect(page.locator("script[type='module'][src^='/assets/']")).toHaveCount(1);
    await expect(page.locator("script[src*='@vite/client']")).toHaveCount(0);
    await expect(page.getByLabel("Runtime status: Local loopback service available", { exact: true }))
      .toHaveAttribute("data-service-state", "available");

    const auth = await page.request.get("/auth/session", {
      headers: { "Sec-Fetch-Site": "same-origin" },
    });
    expect(auth.status()).toBe(200);
    const authBody = await auth.json() as Record<string, unknown>;
    expect(authBody.user_presence_confirmation_available).toBe(false);
    expect(typeof authBody.csrf_token).toBe("string");

    const liveness = await page.request.get("/v1/runtime-liveness");
    expect(liveness.status()).toBe(200);
    const livenessBody = await liveness.json() as {
      status: string;
      components: Array<{ configured: boolean; alive: boolean | null }>;
    };
    expect(livenessBody.status).toBe("ok");
    expect(livenessBody.components).toHaveLength(4);
    expect(livenessBody.components.every((item) => !item.configured || item.alive === true)).toBe(true);
  });

  test("renders the truthful disconnected updater state from the real API", async ({ page }) => {
    await page.goto("/overview");
    const updates = page.getByRole("region", { name: "Software updates", exact: true });
    await expect(updates).toHaveAttribute("data-update-state", "unconfigured");
    const control = updates.getByRole("button");
    await expect(control).toContainText("Updates not connected");
    await expect(control).toBeEnabled();
    await control.click();
    await expect(updates.getByText("Updates are not connected. Checking, downloading, and installation remain off.", { exact: true })).toBeVisible();
    await expect(updates.getByLabel("Update actions").locator("button")).toHaveCount(0);
  });

  test("publishes the canonical twenty-metric operability inventory", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 900 });
    await page.goto("/research/methods");
    await expect(page.getByRole("heading", { name: "What can produce measured evidence today" })).toBeVisible();
    const summary = page.getByLabel("Metric operability summary");
    await expect(summary.getByText("Measured paths shipped").locator("..")).toContainText("16");
    await expect(summary.getByText("Need project profile").locator("..")).toContainText("0");
    await expect(summary.getByText("Need source adapter").locator("..")).toContainText("4");
    await expect(page.locator("[data-operability-state]")).toHaveCount(20);

    const response = await page.request.get("/v1/metric-contracts/v2/operability-catalog");
    expect(response.status()).toBe(200);
    const body = await response.json() as Record<string, unknown>;
    expect(body).toMatchObject({
      total_metric_count: 20,
      shipped_path_count: 16,
      task_profile_configuration_gap_count: 0,
      provider_adapter_gap_count: 4,
      model_authoritative_metric_count: 0,
    });
  });

  test("keeps the model registry empty and the shared runtime stopped", async ({ page }) => {
    await page.goto("/models");
    await expect(page.getByRole("heading", { level: 1, name: "Models" })).toBeVisible();
    await expect(page.getByText("No model yet. Add one below.", { exact: true })).toBeVisible();
    const response = await page.request.get("/v1/local-models");
    expect(response.status()).toBe(200);
    const body = await response.json() as { runtime_available: boolean; models: unknown[] };
    expect(body.runtime_available).toBe(false);
    expect(body.models).toEqual([]);
  });

  test("reopens retained synthetic history through real catalog and event routes", async ({ page }) => {
    await openAgent(page);
    await selectProject(page, RECOVERY_PROJECT);
    await selectChat(page, RECOVERY_CHAT);
    await expect(page.getByRole("heading", { level: 2, name: RECOVERY_CHAT })).toBeVisible();
    await expect(page.getByText("Synthetic retained request from the disposable gate.", { exact: true })).toBeVisible();
    await expect(page.getByText("Synthetic retained answer from the disposable gate.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Resume chat", exact: true })).toBeEnabled();
  });

  test("creates a durable Agent project and preserves it across reload", async ({ page }) => {
    const rail = await openAgent(page);
    await rail.getByRole("button", { name: "Create project", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Create project", exact: true });
    await dialog.getByLabel("Project name", { exact: true }).fill(PROJECT);
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(rail.getByText(PROJECT, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("navigation", { name: "Agent projects and chats", exact: true })
      .getByText(PROJECT, { exact: true })).toBeVisible();
  });

  test("opens model-neutral setup before any model exists", async ({ page }) => {
    const rail = await openAgent(page);
    await selectProject(page, PROJECT);
    await rail.getByRole("button", { name: "New chat", exact: true }).click();
    const setup = page.getByRole("dialog", { name: "New session", exact: true });
    await expect(setup.getByLabel("Agent model", { exact: true })).toHaveValue("");
    await expect(setup.getByLabel("Agent model", { exact: true }).locator("option")).toHaveCount(1);
    await expect(setup).toContainText("no model or session is required");
    await expect(setup.getByRole("button", { name: "Choose workspace to open chat", exact: true })).toBeDisabled();
    await setup.getByLabel("Workspace folder", { exact: true }).fill(WORKSPACE);
    await expect(setup.getByRole("button", { name: "Open read-only chat without model", exact: true })).toBeEnabled();
    await setup.getByRole("button", { name: "Close new chat setup", exact: true }).click();
  });

  test("creates a saved read-only chat without loading a model", async ({ page }) => {
    const rail = await openAgent(page);
    await selectProject(page, PROJECT);
    await rail.getByRole("button", { name: "New chat", exact: true }).click();
    const setup = page.getByRole("dialog", { name: "New session", exact: true });
    await setup.getByLabel("Workspace folder", { exact: true }).fill(WORKSPACE);
    await expect(setup.getByRole("radio", { name: /^Save locally/u })).toBeChecked();
    const protectedActions = setup.getByRole("group", { name: "Protected actions", exact: true });
    await expect(protectedActions).toHaveAttribute("disabled", "");
    await expect(protectedActions.getByRole("checkbox", { name: /^May write files/u })).toBeDisabled();
    await setup.getByRole("button", { name: "Open read-only chat without model", exact: true }).click();

    await expect(page.getByRole("heading", { level: 1, name: CHAT })).toBeVisible();
    await expect(page.getByRole("region", { name: "Agent conversation", exact: true }))
      .toContainText("Session created without a model");
    await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toBeDisabled();
    await page.reload();
    await selectProject(page, PROJECT);
    await expect(page.getByRole("navigation", { name: "Agent projects and chats", exact: true })
      .getByText(CHAT, { exact: true })).toBeVisible();
  });

  test("reads the selected real workspace file without mutation authority", async ({ page }) => {
    await openAgent(page);
    await selectProject(page, PROJECT);
    await selectChat(page, CHAT);
    await page.getByRole("button", { name: "Files & review", exact: true }).click();
    const workspace = page.getByRole("region", { name: "Files and reviewed changes", exact: true });
    await workspace.getByRole("button", { name: "example.txt", exact: true }).click();
    const editor = workspace.getByRole("textbox", { name: "Workspace file editor", exact: true });
    await expect(editor).toHaveValue("EXAMPLE_WORKSPACE_OK\n");
    await editor.fill("EXAMPLE_WORKSPACE_OK\nUNAPPLIED_REVIEW_ONLY\n");
    await workspace.getByRole("button", { name: "Review diff", exact: true }).click();
    await expect(workspace.getByRole("button", { name: "Apply reviewed edit", exact: true })).toBeDisabled();

    await page.reload();
    await selectProject(page, PROJECT);
    await selectChat(page, CHAT);
    await page.getByRole("button", { name: "Files & review", exact: true }).click();
    const reopened = page.getByRole("region", { name: "Files and reviewed changes", exact: true });
    await reopened.getByRole("button", { name: "example.txt", exact: true }).click();
    await expect(reopened.getByRole("textbox", { name: "Workspace file editor", exact: true }))
      .toHaveValue("EXAMPLE_WORKSPACE_OK\n");
  });

  test("keeps model selection, context, review, and send controls truthful", async ({ page }) => {
    await openAgent(page);
    await selectProject(page, PROJECT);
    await selectChat(page, CHAT);
    const composer = page.getByRole("form", { name: "Message composer", exact: true });
    await expect(composer.getByRole("textbox", { name: "Message to the agent", exact: true })).toBeDisabled();
    await expect(composer.getByRole("button", { name: "Review prompt without sending", exact: true })).toBeDisabled();
    await expect(composer.getByRole("button", { name: "Send", exact: true })).toBeDisabled();

    await composer.getByLabel(/Model and context settings\. Choose a model\./u).click();
    const runtime = composer.getByRole("dialog", { name: "Choose model and runtime settings", exact: true });
    await expect(runtime.getByLabel("Model", { exact: true })).toHaveValue("");
    await expect(runtime.getByRole("button", { name: "Start model", exact: true })).toBeDisabled();
    await expect(runtime.getByRole("button", { name: "Stop runtime", exact: true })).toBeDisabled();
    await expect(runtime).toContainText("Nothing is loaded until you apply the selection");
  });

  test("renames and pins the chat with durable revision checks", async ({ page }) => {
    await openAgent(page);
    await selectProject(page, PROJECT);
    await selectChat(page, CHAT);
    await page.getByRole("button", { name: `Chat actions for ${CHAT}`, exact: true }).click();
    await page.getByRole("dialog", { name: `Chat actions for ${CHAT}`, exact: true })
      .getByRole("button", { name: "Rename", exact: true }).click();
    const rename = page.getByRole("dialog", { name: "Rename chat", exact: true });
    await rename.getByLabel("Chat name", { exact: true }).fill(RENAMED_CHAT);
    await rename.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: `Chat actions for ${RENAMED_CHAT}`, exact: true }).click();
    await page.getByRole("dialog", { name: `Chat actions for ${RENAMED_CHAT}`, exact: true })
      .getByRole("button", { name: "Pin", exact: true }).click();
    await page.getByRole("button", { name: `Chat actions for ${RENAMED_CHAT}`, exact: true }).click();
    await expect(page.getByRole("dialog", { name: `Chat actions for ${RENAMED_CHAT}`, exact: true })
      .getByRole("button", { name: "Unpin", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close actions", exact: true }).click();

    await page.reload();
    await selectProject(page, PROJECT);
    await page.getByRole("button", { name: `Chat actions for ${RENAMED_CHAT}`, exact: true }).click();
    await expect(page.getByRole("dialog", { name: `Chat actions for ${RENAMED_CHAT}`, exact: true })
      .getByRole("button", { name: "Unpin", exact: true })).toBeVisible();
  });

  test("archives and restores an inactive retained chat", async ({ page }) => {
    await openAgent(page);
    await selectProject(page, RECOVERY_PROJECT);
    await page.getByRole("button", { name: `Chat actions for ${RECOVERY_CHAT}`, exact: true }).click();
    await page.getByRole("dialog", { name: `Chat actions for ${RECOVERY_CHAT}`, exact: true })
      .getByRole("button", { name: "Archive", exact: true }).click();
    await expect(page.getByRole("button", { name: `Chat actions for ${RECOVERY_CHAT}`, exact: true })).toHaveCount(0);

    await page.getByLabel("Show archived", { exact: true }).check();
    await page.getByRole("button", { name: `Chat actions for ${RECOVERY_CHAT}`, exact: true }).click();
    await page.getByRole("dialog", { name: `Chat actions for ${RECOVERY_CHAT}`, exact: true })
      .getByRole("button", { name: "Restore", exact: true }).click();
    await page.getByLabel("Show archived", { exact: true }).uncheck();
    await expect(page.getByRole("button", { name: `Chat actions for ${RECOVERY_CHAT}`, exact: true })).toBeVisible();
  });

  test("shows artifact truth from the real empty artifact repository", async ({ page }) => {
    await openAgent(page);
    await selectProject(page, RECOVERY_PROJECT);
    await selectChat(page, RECOVERY_CHAT);
    const artifacts = page.getByRole("region", { name: "Artifacts", exact: true });
    await expect(artifacts).toBeVisible();
    await expect(artifacts).toContainText("No verified workspace output is recorded in Active");
    await expect(artifacts.getByRole("tab", { name: "Active 0", exact: true })).toBeVisible();
  });

  test("reports exact project MCP state without contacting a registry", async ({ page }) => {
    await openLoopbackChat(page);
    await page.getByRole("button", { name: "Project tools", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "Agent settings", exact: true });
    const projectTools = settings.locator("details.agent-mcp-project-tools");
    await expect(projectTools).toContainText("No admitted tools");
    await projectTools.locator("summary").click();
    await expect(projectTools).toContainText("Admitted plans0");
    await expect(projectTools).toContainText("Ready hosts0");
    await expect(projectTools).toContainText("Ready tools0");
    await expect(projectTools).toContainText("No MCP tool is currently routed into this chat project");
  });

  test("deletes an empty disposable project and leaves other projects intact", async ({ page }) => {
    const rail = await openAgent(page);
    await rail.getByRole("button", { name: "Create project", exact: true }).click();
    const create = page.getByRole("dialog", { name: "Create project", exact: true });
    await create.getByLabel("Project name", { exact: true }).fill(DISPOSABLE_PROJECT);
    await create.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: `Project actions for ${DISPOSABLE_PROJECT}`, exact: true }).click();
    await page.getByRole("dialog", { name: `Project actions for ${DISPOSABLE_PROJECT}`, exact: true })
      .getByRole("button", { name: "Delete", exact: true }).click();
    await page.getByRole("dialog", { name: "Delete project", exact: true })
      .getByRole("button", { name: "Delete", exact: true }).click();
    await expect(rail.getByText(DISPOSABLE_PROJECT, { exact: true })).toHaveCount(0);
    await expect(rail.getByText(PROJECT, { exact: true })).toBeVisible();
  });

  test("keeps one authenticated SPA session across core deep links", async ({ page }) => {
    for (const [path, title] of [
      ["/projects", "Projects"],
      ["/sessions", "Sessions"],
      ["/analysis-jobs", "Analysis jobs"],
    ] as const) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      await expect(page.getByLabel("Runtime status: Local loopback service available", { exact: true }))
        .toHaveAttribute("data-service-state", "available");
    }
  });
});
