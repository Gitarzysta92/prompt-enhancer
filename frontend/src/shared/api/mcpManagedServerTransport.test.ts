import { describe, expect, it, vi } from "vitest";

import { createHttpTransport, TransportError } from "./httpTransport";
import {
  syntheticMcpManagedLifecyclePreview,
  syntheticMcpManagedLifecycleReceipt,
  syntheticMcpManagedLocalConfigurationInspectionPreview,
  syntheticMcpManagedLocalConfigurationInspectionReceipt,
  syntheticMcpManagedLocalCleanupPreview,
  syntheticMcpManagedLocalCleanupReceipt,
  syntheticMcpManagedLocalOperationRecoveryPreview,
  syntheticMcpManagedLocalOperationRecoveryReceipt,
  syntheticMcpManagedLocalRollbackCleanupPreview,
  syntheticMcpManagedLocalRollbackCleanupReceipt,
  syntheticMcpManagedLocalRollbackPreview,
  syntheticMcpManagedLocalRollbackReceipt,
  syntheticMcpManagedLocalUpdatePreview,
  syntheticMcpManagedLocalUpdateReceipt,
  syntheticMcpManagedProbeReceipt,
  syntheticMcpManagedServer,
  syntheticMcpManagedServerList,
  syntheticMcpManagedServerReceipt,
  syntheticMcpManagedToolSnapshot,
} from "./mcpManagedServer.test-support";
import {
  syntheticMcpManagedHostStartPreview,
  syntheticMcpManagedHostStatus,
  syntheticMcpManagedProjectRuntime,
  syntheticReadyMcpManagedHostStatus,
} from "./mcpManagedRuntime.test-support";

const AUTH = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
  user_presence_confirmation_available: true,
  user_presence_confirmation_mode: "native_bridge_bound_token",
} as const;
const PRESENCE_TOKEN = "u".repeat(48);

function privateJson(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store, private",
      Pragma: "no-cache",
    },
  });
}

async function sha256(value: string): Promise<string> {
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  ));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("MCP managed-server HTTP transport", () => {
  it("reads an inert project host, starts only with exact native approval, exposes tools, then stops without approval", async () => {
    const preview = syntheticMcpManagedHostStartPreview();
    const stopped = syntheticMcpManagedHostStatus();
    const ready = syntheticReadyMcpManagedHostStatus();
    const settled = syntheticMcpManagedHostStatus({
      reason: "stopped_by_owner",
      stopped_at: "2040-01-01T10:02:00Z",
      last_transition_at: "2040-01-01T10:02:00Z",
      cleanup_state: "verified",
    });
    const runtime = syntheticMcpManagedProjectRuntime();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(stopped))
      .mockResolvedValueOnce(privateJson(preview))
      .mockResolvedValueOnce(privateJson(ready))
      .mockResolvedValueOnce(privateJson(runtime))
      .mockResolvedValueOnce(privateJson(settled));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const binding = preview.binding;
    const base = `/v1/integrations/mcp-store/managed/${binding.management_id}/projects/${binding.project_id}/host`;

    await expect(transport.getMcpManagedHostStatus?.(
      binding.management_id,
      binding.project_id,
    )).resolves.toEqual(stopped);
    await expect(transport.getMcpManagedHostStartPreview?.(
      binding.management_id,
      binding.project_id,
      binding.server_revision,
      binding.project_binding_revision,
      binding.tool_snapshot_id,
    )).resolves.toEqual(preview);
    expect(approve).not.toHaveBeenCalled();

    const start = {
      request_id: "6".repeat(32),
      expected_server_revision: binding.server_revision,
      expected_project_binding_revision: binding.project_binding_revision,
      expected_tool_snapshot_id: binding.tool_snapshot_id,
      preview_digest: preview.preview_digest,
    };
    await expect(transport.startMcpManagedHost?.(
      binding.management_id,
      binding.project_id,
      start,
    )).resolves.toEqual(ready);
    const startBody = JSON.stringify(start);
    expect(approve).toHaveBeenCalledTimes(1);
    expect(approve).toHaveBeenCalledWith({
      method: "POST",
      path: `${base}/start`,
      bodySha256: await sha256(startBody),
    });

    await expect(transport.getMcpManagedProjectRuntime?.(binding.project_id)).resolves.toEqual(runtime);
    const stop = {
      request_id: "7".repeat(32),
      expected_instance_id: ready.instance_id,
    };
    await expect(transport.stopMcpManagedHost?.(
      binding.management_id,
      binding.project_id,
      stop,
    )).resolves.toEqual(settled);
    expect(approve).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[1][0]).toBe(base);
    expect(fetchMock.mock.calls[2][0]).toBe(
      `${base}/start-preview?expected_server_revision=4&expected_project_binding_revision=2&expected_tool_snapshot_id=${"3".repeat(32)}`,
    );
    expect(fetchMock.mock.calls[3]).toEqual([
      `${base}/start`,
      expect.objectContaining({
        method: "POST",
        body: startBody,
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
        }),
      }),
    ]);
    expect(fetchMock.mock.calls[4][0]).toBe(`/v1/agent/mcp/projects/${binding.project_id}/runtime`);
    expect(fetchMock.mock.calls[5][0]).toBe(`${base}/stop`);
    expect((fetchMock.mock.calls[5][1] as RequestInit).headers).not.toHaveProperty("X-Prompt-Enhancer-User-Presence");
  });

  it("loads private durable plans and one exact record without mutation", async () => {
    const record = syntheticMcpManagedServer();
    const snapshot = syntheticMcpManagedToolSnapshot();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerList([record])))
      .mockResolvedValueOnce(privateJson(record))
      .mockResolvedValueOnce(privateJson(snapshot));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });

    await expect(transport.listMcpManagedServers?.()).resolves.toMatchObject({
      total: 1,
      execution_truth: "reviewed_tool_admission_without_persistent_host_or_tool_authority",
    });
    await expect(transport.getMcpManagedServer?.(record.management_id)).resolves.toEqual(record);
    await expect(transport.getMcpManagedToolSnapshot?.(record.management_id)).resolves.toEqual(snapshot);
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/integrations/mcp-store/managed");
    expect(fetchMock.mock.calls[2][0]).toBe(`/v1/integrations/mcp-store/managed/${record.management_id}`);
    expect(fetchMock.mock.calls[3][0]).toBe(`/v1/integrations/mcp-store/managed/${record.management_id}/tools`);
    expect((fetchMock.mock.calls[1][1] as RequestInit).cache).toBe("no-store");
    expect(approve).not.toHaveBeenCalled();
  });

  it("binds every plan mutation to the exact native-confirmed path and body", async () => {
    const base = syntheticMcpManagedServer();
    const projectBase = syntheticMcpManagedProbeReceipt().server;
    const snapshot = syntheticMcpManagedToolSnapshot();
    const admittedToolIds = snapshot.tools.map((tool) => tool.tool_id).sort();
    const projectId = "f".repeat(32);
    const requirementId = "e".repeat(32);
    const projectServer = syntheticMcpManagedServer({
      ...projectBase,
      revision: 3,
      updated_at: "2040-01-01T10:02:00Z",
      project_bindings: [{
        project_id: projectId,
        project_name: "Synthetic project",
        enabled: true,
        required_permissions: projectBase.required_permissions,
        granted_permissions: projectBase.required_permissions,
        admitted_tool_ids: admittedToolIds,
        tool_snapshot_id: snapshot.snapshot_id,
        admission_state: "admitted",
        effective_state: "inactive_install_required",
        created_at: "2040-01-01T10:01:00Z",
        updated_at: "2040-01-01T10:01:00Z",
        revision: 1,
      }],
    });
    const storedServer = syntheticMcpManagedServer({
      revision: 2,
      updated_at: "2040-01-01T10:01:00Z",
      requirements: base.requirements.map((item) => item.requirement_id === requirementId
        ? {
          ...item,
          configuration_state: "secret_stored" as const,
          secret_vault_provider: "windows_credential_manager" as const,
        }
        : item),
    });
    const removedServer = syntheticMcpManagedServer({
      revision: 3,
      updated_at: "2040-01-01T10:02:00Z",
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerReceipt(base)))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerReceipt(projectServer)))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerReceipt(storedServer)))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerReceipt(removedServer)));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });

    const create = {
      request_id: "1".repeat(32),
      catalog_id: base.catalog_id,
      name: base.server_name,
      version: base.server_version,
      option_id: base.option_id,
      plan_revision: base.plan_revision,
    };
    const binding = {
      request_id: "2".repeat(32),
      expected_revision: 2,
      enabled: true,
      granted_permissions: projectBase.required_permissions,
      admitted_tool_ids: admittedToolIds,
    };
    const secret = {
      request_id: "3".repeat(32),
      expected_revision: 1,
      value: "example-vault-value",
    };
    const removal = { request_id: "4".repeat(32), expected_revision: 2 };

    await transport.createMcpManagedServer?.(create);
    await transport.setMcpManagedProjectBinding?.(base.management_id, projectId, binding);
    await transport.storeMcpManagedSecret?.(base.management_id, requirementId, secret);
    await transport.removeMcpManagedSecret?.(base.management_id, requirementId, removal);

    const paths = [
      "/v1/integrations/mcp-store/managed",
      `/v1/integrations/mcp-store/managed/${base.management_id}/projects/${projectId}`,
      `/v1/integrations/mcp-store/managed/${base.management_id}/secrets/${requirementId}`,
      `/v1/integrations/mcp-store/managed/${base.management_id}/secrets/${requirementId}/remove`,
    ];
    const bodies = [create, binding, secret, removal].map((value) => JSON.stringify(value));
    for (let index = 0; index < paths.length; index += 1) {
      expect(approve).toHaveBeenNthCalledWith(index + 1, {
        method: "POST",
        path: paths[index],
        bodySha256: await sha256(bodies[index]),
      });
      const [path, init] = fetchMock.mock.calls[index + 1] as [string, RequestInit];
      expect(path).toBe(paths[index]);
      expect(init).toEqual(expect.objectContaining({
        method: "POST",
        body: bodies[index],
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
          "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
        }),
      }));
    }
    expect(JSON.stringify(approve.mock.calls)).not.toContain(secret.value);
    expect(JSON.stringify(storedServer)).not.toContain(secret.value);
  });

  it("stores and removes ordinary configuration through native-confirmed vault routes", async () => {
    const base = syntheticMcpManagedServer();
    const requirementId = "c".repeat(32);
    const storedServer = syntheticMcpManagedServer({
      revision: 2,
      updated_at: "2040-01-01T10:01:00Z",
      requirements: base.requirements.map((item) => item.requirement_id === requirementId
        ? {
          ...item,
          configuration_state: "value_stored" as const,
          value_vault_provider: "windows_credential_manager" as const,
        }
        : item),
    });
    const removedServer = syntheticMcpManagedServer({
      revision: 3,
      updated_at: "2040-01-01T10:02:00Z",
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerReceipt(storedServer)))
      .mockResolvedValueOnce(privateJson(syntheticMcpManagedServerReceipt(removedServer)));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const configuration = {
      request_id: "5".repeat(32),
      expected_revision: 1,
      value: "X:\\example\\workspace",
    };
    const removal = { request_id: "6".repeat(32), expected_revision: 2 };
    const storePath = `/v1/integrations/mcp-store/managed/${base.management_id}/configuration/${requirementId}`;
    const removePath = `${storePath}/remove`;

    await expect(transport.storeMcpManagedConfiguration?.(
      base.management_id,
      requirementId,
      configuration,
    )).resolves.toEqual(syntheticMcpManagedServerReceipt(storedServer));
    await expect(transport.removeMcpManagedConfiguration?.(
      base.management_id,
      requirementId,
      removal,
    )).resolves.toEqual(syntheticMcpManagedServerReceipt(removedServer));

    expect(approve).toHaveBeenNthCalledWith(1, {
      method: "POST",
      path: storePath,
      bodySha256: await sha256(JSON.stringify(configuration)),
    });
    expect(approve).toHaveBeenNthCalledWith(2, {
      method: "POST",
      path: removePath,
      bodySha256: await sha256(JSON.stringify(removal)),
    });
    expect(fetchMock.mock.calls[1][0]).toBe(storePath);
    expect(fetchMock.mock.calls[2][0]).toBe(removePath);
    expect(JSON.stringify(approve.mock.calls)).not.toContain(configuration.value);
    expect(JSON.stringify(storedServer)).not.toContain(configuration.value);
  });

  it("rejects unsafe requests before browser-session or management-route use", async () => {
    const fetchMock = vi.fn();
    const approve = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });

    await expect(transport.getMcpManagedServer?.("bad-id")).rejects.toBeInstanceOf(TransportError);
    await expect(transport.createMcpManagedServer?.({
      request_id: "1".repeat(32),
      catalog_id: "a".repeat(32),
      name: "com.example/synthetic-files",
      version: "1.2.3",
      option_id: "bad-id",
      plan_revision: "d".repeat(64),
    })).rejects.toBeInstanceOf(TransportError);
    await expect(transport.storeMcpManagedSecret?.(
      "9".repeat(32),
      "e".repeat(32),
      { request_id: "3".repeat(32), expected_revision: 1, value: "x".repeat(2_049) },
    )).rejects.toBeInstanceOf(TransportError);
    await expect(transport.storeMcpManagedConfiguration?.(
      "9".repeat(32),
      "c".repeat(32),
      {
        request_id: "4".repeat(32),
        expected_revision: 1,
        value: "example\r\ninjected-header: value",
      },
    )).rejects.toBeInstanceOf(TransportError);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(approve).not.toHaveBeenCalled();
  });

  it("rejects a valid-looking response that adds raw requirement data", async () => {
    const record = structuredClone(syntheticMcpManagedServer()) as Record<string, any>;
    record.requirements[1].value = "example-leaked-value";
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson({
        ...syntheticMcpManagedServerList(),
        servers: [record],
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.listMcpManagedServers?.()).rejects.toBeInstanceOf(TransportError);
  });

  it("binds a compatibility probe to its exact native-confirmed path and revision", async () => {
    const receipt = syntheticMcpManagedProbeReceipt();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(receipt));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const payload = { request_id: receipt.probe.request_id, expected_revision: 1 };
    const path = `/v1/integrations/mcp-store/managed/${receipt.server.management_id}/probe`;
    const body = JSON.stringify(payload);

    await expect(transport.probeMcpManagedServer?.(
      receipt.server.management_id,
      payload,
    )).resolves.toEqual(receipt);
    expect(approve).toHaveBeenCalledWith({
      method: "POST",
      path,
      bodySha256: await sha256(body),
    });
    expect(fetchMock.mock.calls[1]).toEqual([
      path,
      expect.objectContaining({
        method: "POST",
        body,
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
          "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
        }),
      }),
    ]);
  });

  it.each([
    "mcp_host_content_encoding_unsupported",
    "mcp_host_process_output_limit",
    "mcp_host_visible_window_detected",
    "mcp_host_process_visibility_unconfirmed",
    "mcp_host_cleanup_unconfirmed",
    "mcp_managed_host_start_cancelled",
    "mcp_managed_host_start_timeout",
    "mcp_managed_host_stop_timeout",
  ] as const)("preserves allowlisted content-free MCP refusal reason %s", async (reasonCode) => {
    const receipt = syntheticMcpManagedProbeReceipt();
    const response = new Response(JSON.stringify({
      detail: reasonCode,
    }), {
      status: 503,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, private",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(response);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: vi.fn().mockResolvedValue(PRESENCE_TOKEN),
    });

    await expect(transport.probeMcpManagedServer?.(
      receipt.server.management_id,
      { request_id: receipt.probe.request_id, expected_revision: 1 },
    )).rejects.toMatchObject({
      status: 503,
      reasonCode,
    });
  });

  it.each([
    "mcp_host_protocol_unsupported",
    "mcp_host_transport_mismatch",
    "mcp_host_tool_identity_conflict",
    "mcp_host_tool_metadata_total_exceeded",
    "mcp_host_tool_schema_recursive",
    "mcp_host_tool_schema_ref_invalid",
    "mcp_host_tool_schema_keyword_unsupported",
    "mcp_host_tool_schema_pattern_unsafe",
    "mcp_host_tool_schema_format_unsupported",
    "mcp_host_tool_schema_too_complex",
  ] as const)("preserves only the allowlisted MCP contract refusal reason %s", async (reasonCode) => {
    const receipt = syntheticMcpManagedProbeReceipt();
    const response = new Response(JSON.stringify({
      detail: {
        code: reasonCode,
        message: "EXAMPLE_PRIVATE_MCP_SCHEMA_CANARY",
      },
    }), {
      status: 422,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, private",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(response);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: vi.fn().mockResolvedValue(PRESENCE_TOKEN),
    });

    const request = transport.probeMcpManagedServer?.(
      receipt.server.management_id,
      { request_id: receipt.probe.request_id, expected_revision: 1 },
    );
    expect(request).toBeDefined();
    const error = await request!.catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 422, reasonCode });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_MCP_SCHEMA_CANARY");
  });

  it("loads an exact lifecycle preview then binds activation to that digest", async () => {
    const preview = syntheticMcpManagedLifecyclePreview();
    const receipt = syntheticMcpManagedLifecycleReceipt();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(preview))
      .mockResolvedValueOnce(privateJson(receipt));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const previewPath = `/v1/integrations/mcp-store/managed/${preview.management_id}/install-preview`;

    await expect(transport.getMcpManagedLifecyclePreview?.(
      preview.management_id,
      "install",
    )).resolves.toEqual(preview);
    expect(fetchMock.mock.calls[1][0]).toBe(previewPath);
    expect(approve).not.toHaveBeenCalled();

    const command = {
      request_id: "8".repeat(32),
      expected_revision: preview.expected_revision,
      preview_digest: preview.preview_digest,
    };
    const path = `/v1/integrations/mcp-store/managed/${preview.management_id}/install`;
    const body = JSON.stringify(command);
    await expect(transport.applyMcpManagedLifecycle?.(
      preview.management_id,
      "install",
      command,
    )).resolves.toEqual(receipt);
    expect(approve).toHaveBeenCalledWith({
      method: "POST",
      path,
      bodySha256: await sha256(body),
    });
    expect(fetchMock.mock.calls[2]).toEqual([
      path,
      expect.objectContaining({
        method: "POST",
        body,
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
          "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
        }),
      }),
    ]);
  });

  it("inspects an exact MCPB configuration schema only after native confirmation", async () => {
    const preview = syntheticMcpManagedLocalConfigurationInspectionPreview();
    const receipt = syntheticMcpManagedLocalConfigurationInspectionReceipt({
      preview_digest: preview.preview_digest,
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(preview))
      .mockResolvedValueOnce(privateJson(receipt));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const previewPath = `/v1/integrations/mcp-store/managed/${preview.management_id}/configuration-inspection-preview`;

    await expect(transport.getMcpManagedLocalConfigurationInspectionPreview?.(
      preview.management_id,
    )).resolves.toEqual(preview);
    expect(fetchMock.mock.calls[1][0]).toBe(previewPath);
    expect(approve).not.toHaveBeenCalled();

    const command = {
      request_id: "8".repeat(32),
      expected_revision: preview.expected_revision,
      preview_digest: preview.preview_digest,
    };
    const path = `/v1/integrations/mcp-store/managed/${preview.management_id}/configuration-inspection`;
    const body = JSON.stringify(command);
    await expect(transport.inspectMcpManagedLocalConfiguration?.(
      preview.management_id,
      command,
    )).resolves.toEqual(receipt);
    expect(approve).toHaveBeenCalledWith({
      method: "POST",
      path,
      bodySha256: await sha256(body),
    });
    expect(fetchMock.mock.calls[2]).toEqual([
      path,
      expect.objectContaining({
        method: "POST",
        body,
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
          "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
        }),
      }),
    ]);
    expect(JSON.stringify(receipt)).not.toContain("synthetic-secret");
  });

  it("loads and natively confirms the exact interrupted-uninstall recovery", async () => {
    const preview = syntheticMcpManagedLocalCleanupPreview();
    const receipt = syntheticMcpManagedLocalCleanupReceipt({
      preview_digest: preview.preview_digest,
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(preview))
      .mockResolvedValueOnce(privateJson(receipt));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const previewPath = `/v1/integrations/mcp-store/managed/${preview.management_id}/cleanup-preview`;

    await expect(transport.getMcpManagedLocalCleanupPreview?.(
      preview.management_id,
    )).resolves.toEqual(preview);
    expect(fetchMock.mock.calls[1][0]).toBe(previewPath);
    expect(approve).not.toHaveBeenCalled();

    const command = {
      request_id: "8".repeat(32),
      expected_revision: preview.expected_revision,
      preview_digest: preview.preview_digest,
    };
    const path = `/v1/integrations/mcp-store/managed/${preview.management_id}/cleanup`;
    const body = JSON.stringify(command);
    await expect(transport.completeMcpManagedLocalCleanup?.(
      preview.management_id,
      command,
    )).resolves.toEqual(receipt);
    expect(approve).toHaveBeenCalledWith({
      method: "POST",
      path,
      bodySha256: await sha256(body),
    });
    expect(fetchMock.mock.calls[2]).toEqual([
      path,
      expect.objectContaining({
        method: "POST",
        body,
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
          "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
        }),
      }),
    ]);
  });

  it("loads an authenticated exact update preview without requesting presence", async () => {
    const preview = syntheticMcpManagedLocalUpdatePreview();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(preview));
    const approve = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const path = `/v1/integrations/mcp-store/managed/${preview.management_id}/update-preview`;

    await expect(transport.getMcpManagedLocalUpdatePreview?.(
      preview.management_id,
    )).resolves.toEqual(preview);
    expect(fetchMock.mock.calls[1]).toEqual([
      path,
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        headers: expect.objectContaining({
          Accept: "application/json",
        }),
      }),
    ]);
    expect(approve).not.toHaveBeenCalled();
  });

  it("binds update, rollback, retained-generation cleanup, and recovery to exact native-confirmed previews", async () => {
    const updatePreview = syntheticMcpManagedLocalUpdatePreview();
    const updateReceipt = syntheticMcpManagedLocalUpdateReceipt({
      preview_digest: updatePreview.preview_digest,
    });
    const rollbackPreview = syntheticMcpManagedLocalRollbackPreview();
    const rollbackReceipt = syntheticMcpManagedLocalRollbackReceipt({
      preview_digest: rollbackPreview.preview_digest,
    });
    const cleanupPreview = syntheticMcpManagedLocalRollbackCleanupPreview();
    const cleanupReceipt = syntheticMcpManagedLocalRollbackCleanupReceipt({
      preview_digest: cleanupPreview.preview_digest,
    });
    const recoveryPreview = syntheticMcpManagedLocalOperationRecoveryPreview();
    const recoveryReceipt = syntheticMcpManagedLocalOperationRecoveryReceipt({
      preview_digest: recoveryPreview.preview_digest,
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(privateJson(AUTH))
      .mockResolvedValueOnce(privateJson(updatePreview))
      .mockResolvedValueOnce(privateJson(updateReceipt))
      .mockResolvedValueOnce(privateJson(rollbackPreview))
      .mockResolvedValueOnce(privateJson(rollbackReceipt))
      .mockResolvedValueOnce(privateJson(cleanupPreview))
      .mockResolvedValueOnce(privateJson(cleanupReceipt))
      .mockResolvedValueOnce(privateJson(recoveryPreview))
      .mockResolvedValueOnce(privateJson(recoveryReceipt));
    const approve = vi.fn().mockResolvedValue(PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    const managementId = updatePreview.management_id;
    const operations = [
      {
        previewPath: "update-preview",
        mutationPath: "update",
        preview: updatePreview,
        get: () => transport.getMcpManagedLocalUpdatePreview?.(managementId),
        apply: (command: any) => transport.applyMcpManagedLocalUpdate?.(managementId, command),
      },
      {
        previewPath: "rollback-preview",
        mutationPath: "rollback",
        preview: rollbackPreview,
        get: () => transport.getMcpManagedLocalRollbackPreview?.(managementId),
        apply: (command: any) => transport.applyMcpManagedLocalRollback?.(managementId, command),
      },
      {
        previewPath: "rollback-cleanup-preview",
        mutationPath: "rollback-cleanup",
        preview: cleanupPreview,
        get: () => transport.getMcpManagedLocalRollbackCleanupPreview?.(managementId),
        apply: (command: any) => transport.cleanupMcpManagedLocalRollback?.(managementId, command),
      },
      {
        previewPath: "recovery-preview",
        mutationPath: "recovery",
        preview: recoveryPreview,
        get: () => transport.getMcpManagedLocalOperationRecoveryPreview?.(managementId),
        apply: (command: any) => transport.recoverMcpManagedLocalOperation?.(managementId, command),
      },
    ] as const;

    for (let index = 0; index < operations.length; index += 1) {
      const operation = operations[index];
      await expect(operation.get()).resolves.toEqual(operation.preview);
      const command = {
        request_id: String(index + 5).repeat(32),
        expected_revision: operation.preview.expected_revision,
        preview_digest: operation.preview.preview_digest,
      };
      await operation.apply(command);
      const previewPath = `/v1/integrations/mcp-store/managed/${managementId}/${operation.previewPath}`;
      const mutationPath = `/v1/integrations/mcp-store/managed/${managementId}/${operation.mutationPath}`;
      const body = JSON.stringify(command);
      expect(fetchMock.mock.calls[(index * 2) + 1][0]).toBe(previewPath);
      expect(approve).toHaveBeenNthCalledWith(index + 1, {
        method: "POST",
        path: mutationPath,
        bodySha256: await sha256(body),
      });
      expect(fetchMock.mock.calls[(index * 2) + 2]).toEqual([
        mutationPath,
        expect.objectContaining({
          method: "POST",
          body,
          cache: "no-store",
          headers: expect.objectContaining({
            "X-Prompt-Enhancer-CSRF": AUTH.csrf_token,
            "X-Prompt-Enhancer-User-Presence": PRESENCE_TOKEN,
          }),
        }),
      ]);
    }
  });
});
