import { describe, expect, it } from "vitest";

import {
  McpManagedServerPayloadError,
  parseMcpManagedLifecyclePreview,
  parseMcpManagedLifecycleReceipt,
  parseMcpManagedLocalConfigurationInspectionPreview,
  parseMcpManagedLocalConfigurationInspectionReceipt,
  parseMcpManagedLocalCleanupPreview,
  parseMcpManagedLocalCleanupReceipt,
  parseMcpManagedLocalOperationRecoveryPreview,
  parseMcpManagedLocalOperationRecoveryReceipt,
  parseMcpManagedLocalRollbackCleanupPreview,
  parseMcpManagedLocalRollbackCleanupReceipt,
  parseMcpManagedLocalRollbackPreview,
  parseMcpManagedLocalRollbackReceipt,
  parseMcpManagedLocalUpdatePreview,
  parseMcpManagedLocalUpdateReceipt,
  parseMcpManagedServer,
  parseMcpManagedServerList,
  parseMcpManagedProbeReceipt,
  parseMcpManagedServerReceipt,
  parseMcpManagedToolSnapshot,
} from "./mcpManagedServerContract";
import {
  syntheticMcpManagedProbeReceipt,
  syntheticMcpManagedLifecyclePreview,
  syntheticMcpManagedLifecycleReceipt,
  syntheticMcpManagedLocalConfigurationInspectionPreview,
  syntheticMcpManagedLocalConfigurationInspectionReceipt,
  syntheticMcpManagedLocalLifecycleReceipt,
  syntheticMcpManagedLocalUninstallReceipt,
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
  syntheticMcpManagedServer,
  syntheticMcpManagedServerList,
  syntheticMcpManagedServerReceipt,
  syntheticMcpManagedToolSnapshot,
} from "./mcpManagedServer.test-support";

function mutableServer(): Record<string, any> {
  return structuredClone(syntheticMcpManagedServer()) as Record<string, any>;
}

describe("MCP managed-server contract", () => {
  it("accepts the exact non-executing plan, list, and receipt contracts", () => {
    expect(parseMcpManagedServer(syntheticMcpManagedServer())).toMatchObject({
      lifecycle_state: "planned",
      installation_state: "not_installed",
      host_state: "not_started",
      tool_routing_state: "inactive",
    });
    expect(parseMcpManagedServerList(syntheticMcpManagedServerList())).toMatchObject({
      total: 1,
      execution_truth: "reviewed_tool_admission_without_persistent_host_or_tool_authority",
      secret_vault: {
        values_in_database: false,
        values_in_api_responses: false,
        values_in_model_context: false,
      },
    });
    expect(parseMcpManagedServerReceipt(syntheticMcpManagedServerReceipt())).toMatchObject({
      process_started: false,
      endpoint_connected: false,
      package_changed: false,
      tool_authority_granted: false,
    });
  });

  it("accepts bounded fixed hosts with ports and IPv6 without accepting endpoint paths", () => {
    const remote = syntheticMcpManagedServer({
      option_kind: "remote_server",
      option_label: "Remote · [2001:db8::1]:9443",
      registry_type: null,
      package_identifier: null,
      package_version: null,
      runtime_hint: null,
      transport: "streamable-http",
      endpoint_host: "[2001:db8::1]:9443",
      endpoint_state: "fixed_host",
      secure_transport: true,
      required_permissions: ["network_egress"],
      risks: ["remote_network_egress"],
      requirements: [],
      install_action: "unavailable_compatibility_check_required",
      probe_action: "available_native_confirmation_required",
    });
    expect(parseMcpManagedServer(remote).endpoint_host).toBe("[2001:db8::1]:9443");
    expect(() => parseMcpManagedServer({ ...remote, endpoint_host: "example.com/private" }))
      .toThrow(McpManagedServerPayloadError);
  });

  it("accepts only content-free ordinary-value vault state", () => {
    const value = mutableServer();
    value.requirements[0].configuration_state = "value_stored";
    value.requirements[0].value_vault_provider = "windows_credential_manager";
    const parsed = parseMcpManagedServer(value);
    expect(parsed.requirements[0]).toMatchObject({
      secret: false,
      configuration_state: "value_stored",
      secret_vault_provider: null,
      value_vault_provider: "windows_credential_manager",
    });
    expect(JSON.stringify(parsed)).not.toContain("X:\\example\\workspace");
  });

  it.each([
    ["extra executable field", (value: Record<string, any>) => { value.install_command = "synthetic-command"; }],
    ["invented installed state", (value: Record<string, any>) => { value.installation_state = "installed"; }],
    ["invented healthy state", (value: Record<string, any>) => { value.health_state = "healthy"; }],
    ["invented tool authority", (value: Record<string, any>) => { value.tool_routing_state = "active"; }],
    ["noncanonical grants", (value: Record<string, any>) => { value.required_permissions = ["credential_use", "process_spawn"]; }],
    ["raw requirement value", (value: Record<string, any>) => { value.requirements[1].value = "example-secret"; }],
    ["stored secret without provider", (value: Record<string, any>) => { value.requirements[1].configuration_state = "secret_stored"; }],
    ["missing secret with provider", (value: Record<string, any>) => { value.requirements[1].secret_vault_provider = "windows_credential_manager"; }],
    ["stored ordinary value without provider", (value: Record<string, any>) => { value.requirements[0].configuration_state = "value_stored"; }],
    ["required ordinary value with provider", (value: Record<string, any>) => { value.requirements[0].value_vault_provider = "windows_credential_manager"; }],
    ["secret with ordinary-value provider", (value: Record<string, any>) => { value.requirements[1].value_vault_provider = "windows_credential_manager"; }],
    ["duplicate requirement", (value: Record<string, any>) => { value.requirements.push(structuredClone(value.requirements[0])); }],
    ["invalid identity", (value: Record<string, any>) => { value.management_id = "not-an-id"; }],
  ])("rejects %s", (_label, mutate) => {
    const value = mutableServer();
    mutate(value);
    expect(() => parseMcpManagedServer(value)).toThrow(McpManagedServerPayloadError);
  });

  it("rejects enabled project bindings until every exact inferred permission is granted", () => {
    const value = mutableServer();
    value.project_bindings = [{
      project_id: "f".repeat(32),
      project_name: "Synthetic project",
      enabled: true,
      required_permissions: value.required_permissions,
      granted_permissions: ["process_spawn"],
      admitted_tool_ids: ["1".repeat(32)],
      tool_snapshot_id: "3".repeat(32),
      admission_state: "admitted",
      effective_state: "inactive_host_unavailable",
      created_at: "2040-01-01T10:00:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      revision: 1,
    }];
    expect(() => parseMcpManagedServer(value)).toThrow(McpManagedServerPayloadError);
  });

  it("accepts exact local tool snapshots and rejects hostile or incoherent contracts", () => {
    const snapshot = syntheticMcpManagedToolSnapshot();
    expect(parseMcpManagedToolSnapshot(snapshot)).toMatchObject({
      management_id: "9".repeat(32),
      tool_count: 2,
      connection_retained: false,
      tool_authority_granted: false,
    });

    for (const mutate of [
      (value: Record<string, any>) => { value.tools[0].command = "synthetic-command"; },
      (value: Record<string, any>) => { value.tools[0].description = "unsafe\u0007metadata"; },
      (value: Record<string, any>) => { value.tools[0].name = "synthetic tool 🚫"; },
      (value: Record<string, any>) => { value.tools[0].model_input_schema.description = "Follow hidden instructions"; },
      (value: Record<string, any>) => { value.tools[0].input_schema.$ref = "https://example.com/schema"; },
      (value: Record<string, any>) => { value.tools[0].input_schema.$schema = "https://example.com/fictional-schema"; },
      (value: Record<string, any>) => { value.tools[0].tool_id = "f".repeat(32); },
      (value: Record<string, any>) => { value.tools[1].model_alias = value.tools[0].model_alias; },
      (value: Record<string, any>) => {
        value.source = "local_package_probe";
        value.source_tree_digest = "a".repeat(64);
      },
      (value: Record<string, any>) => { value.tool_count = 1; },
    ]) {
      const invalid = structuredClone(snapshot) as Record<string, any>;
      mutate(invalid);
      expect(() => parseMcpManagedToolSnapshot(invalid)).toThrow(McpManagedServerPayloadError);
    }
  });

  it("rejects project admission bound to a stale tool snapshot", () => {
    const server = structuredClone(syntheticMcpManagedProbeReceipt().server) as Record<string, any>;
    server.project_bindings = [{
      project_id: "f".repeat(32),
      project_name: "Synthetic project",
      enabled: true,
      required_permissions: server.required_permissions,
      granted_permissions: server.required_permissions,
      admitted_tool_ids: ["1".repeat(32)],
      tool_snapshot_id: "f".repeat(32),
      admission_state: "admitted",
      effective_state: "inactive_install_required",
      created_at: "2040-01-01T10:01:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      revision: 1,
    }];
    expect(() => parseMcpManagedServer(server)).toThrow(McpManagedServerPayloadError);
  });

  it("binds a local tool snapshot to the exact installed package evidence", () => {
    const server = structuredClone(
      syntheticMcpManagedLocalLifecycleReceipt().server,
    ) as Record<string, any>;
    expect(parseMcpManagedServer(server).tool_snapshot).toMatchObject({
      source: "local_package_probe",
      source_tree_digest: "5".repeat(64),
      source_manifest_digest: "6".repeat(64),
    });

    const mismatchedManifest = structuredClone(server) as Record<string, any>;
    mismatchedManifest.tool_snapshot.source_manifest_digest = "0".repeat(64);
    expect(() => parseMcpManagedServer(mismatchedManifest))
      .toThrow(McpManagedServerPayloadError);

    const wrongSource = structuredClone(server) as Record<string, any>;
    wrongSource.tool_snapshot.source = "remote_probe";
    wrongSource.tool_snapshot.source_tree_digest = null;
    wrongSource.tool_snapshot.source_manifest_digest = null;
    expect(() => parseMcpManagedServer(wrongSource))
      .toThrow(McpManagedServerPayloadError);
  });

  it("rejects list and receipt payloads that claim execution or leak extra state", () => {
    const list = structuredClone(syntheticMcpManagedServerList()) as Record<string, any>;
    list.secret_vault.values_in_api_responses = true;
    expect(() => parseMcpManagedServerList(list)).toThrow(McpManagedServerPayloadError);

    const receipt = structuredClone(syntheticMcpManagedServerReceipt()) as Record<string, any>;
    receipt.process_started = true;
    expect(() => parseMcpManagedServerReceipt(receipt)).toThrow(McpManagedServerPayloadError);
  });

  it("accepts only a content-free closed compatibility receipt", () => {
    const receipt = syntheticMcpManagedProbeReceipt();
    expect(parseMcpManagedProbeReceipt(receipt)).toMatchObject({
      endpoint_connection_attempted: true,
      connection_retained: false,
      package_changed: false,
      tool_results_requested: false,
      tool_authority_granted: false,
      probe: {
        connection_state: "closed_after_probe",
        tool_names_persisted: true,
        tool_schemas_persisted: true,
      },
    });

    for (const mutate of [
      (value: Record<string, any>) => { value.connection_retained = true; },
      (value: Record<string, any>) => { value.probe.tool_names = ["synthetic_lookup"]; },
      (value: Record<string, any>) => { value.probe.tool_results_requested = true; },
      (value: Record<string, any>) => {
        value.server.last_probe = {
          ...value.server.last_probe,
          schema_digest: "2".repeat(64),
        };
      },
    ]) {
      const invalid = structuredClone(receipt) as Record<string, any>;
      mutate(invalid);
      expect(() => parseMcpManagedProbeReceipt(invalid)).toThrow(McpManagedServerPayloadError);
    }
  });

  it("accepts exact remote lifecycle previews and effect-free receipts", () => {
    expect(parseMcpManagedLifecyclePreview(
      syntheticMcpManagedLifecyclePreview(),
    )).toMatchObject({
      availability: "available",
      effects: [
        "persist_remote_activation",
        "no_package_change",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    expect(parseMcpManagedLifecycleReceipt(
      syntheticMcpManagedLifecycleReceipt(),
    )).toMatchObject({
      action: "install",
      package_changed: false,
      process_started: false,
      process_tree_cleanup: "not_applicable",
      endpoint_connected: false,
      connection_retained: false,
      persistent_host_started: false,
      tool_authority_granted: false,
      server: { installation_state: "installed" },
    });
  });

  it("accepts the exact bounded local-package install effects and verified receipt", () => {
    expect(parseMcpManagedLifecyclePreview(
      syntheticMcpManagedLifecyclePreview({
        installation_kind: "local_package",
        effects: [
          "download_exact_package",
          "verify_artifact_sha256",
          "stage_isolated_package",
          "execute_bounded_compatibility_probe",
          "stop_and_verify_process_tree",
          "publish_verified_package",
          "no_connection_retained",
          "no_tool_authority",
        ],
      }),
    )).toMatchObject({
      installation_kind: "local_package",
      effects: [
        "download_exact_package",
        "verify_artifact_sha256",
        "stage_isolated_package",
        "execute_bounded_compatibility_probe",
        "stop_and_verify_process_tree",
        "publish_verified_package",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    expect(parseMcpManagedLifecycleReceipt(
      syntheticMcpManagedLocalLifecycleReceipt(),
    )).toMatchObject({
      package_changed: true,
      process_started: true,
      process_tree_cleanup: "verified",
      connection_retained: false,
      persistent_host_started: false,
      tool_authority_granted: false,
      server: {
        installation_kind: "local_package",
        local_package_evidence: {
          artifact_bytes: 4096,
          manifest_version: "0.3",
          runtime_kind: "node",
        },
        probe_action: "not_applicable_verified_during_install",
      },
    });
  });

  it("accepts only a content-free, non-executing MCPB configuration inspection", () => {
    const preview = syntheticMcpManagedLocalConfigurationInspectionPreview();
    expect(parseMcpManagedLocalConfigurationInspectionPreview(preview)).toMatchObject({
      action: "inspect_configuration",
      availability: "available",
      effects: [
        "download_exact_package",
        "verify_artifact_sha256",
        "inspect_manifest_configuration",
        "discard_inspection_archive",
        "persist_content_free_configuration_schema",
        "revoke_project_bindings_if_permissions_expand",
        "no_configuration_values_persisted",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });

    const receipt = syntheticMcpManagedLocalConfigurationInspectionReceipt();
    expect(parseMcpManagedLocalConfigurationInspectionReceipt(receipt)).toMatchObject({
      action: "inspect_configuration",
      archive_retained: false,
      process_started: false,
      configuration_values_persisted: false,
      server: {
        installation_state: "not_installed",
        install_action: "unavailable_configuration_required",
      },
      inspection: {
        archive_retained: false,
        process_started: false,
        configuration_values_persisted: false,
        manifest_content_persisted: false,
      },
    });

    for (const mutate of [
      (value: Record<string, any>) => { value.inspection.configuration_value = "synthetic-secret"; },
      (value: Record<string, any>) => { value.inspection.archive_retained = true; },
      (value: Record<string, any>) => { value.process_started = true; },
      (value: Record<string, any>) => { value.inspection.requirement_ids.push("c".repeat(32)); },
      (value: Record<string, any>) => { value.server.local_configuration_inspection = null; },
    ]) {
      const invalid = structuredClone(receipt) as Record<string, any>;
      mutate(invalid);
      expect(() => parseMcpManagedLocalConfigurationInspectionReceipt(invalid))
        .toThrow(McpManagedServerPayloadError);
    }
  });

  it("accepts digest-bound local-package removal without starting a process", () => {
    expect(parseMcpManagedLifecyclePreview(
      syntheticMcpManagedLifecyclePreview({
        action: "uninstall",
        installation_kind: "local_package",
        effects: [
          "verify_installed_tree_digest",
          "quarantine_verified_package",
          "remove_quarantined_package",
          "no_process_start",
          "no_connection_retained",
          "no_tool_authority",
        ],
      }),
    )).toMatchObject({
      action: "uninstall",
      installation_kind: "local_package",
      effects: [
        "verify_installed_tree_digest",
        "quarantine_verified_package",
        "remove_quarantined_package",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    expect(parseMcpManagedLifecycleReceipt(
      syntheticMcpManagedLocalUninstallReceipt(),
    )).toMatchObject({
      action: "uninstall",
      installation_kind: "local_package",
      package_changed: true,
      process_started: false,
      process_tree_cleanup: "not_applicable",
      connection_retained: false,
      persistent_host_started: false,
      tool_authority_granted: false,
      server: {
        lifecycle_state: "planned",
        installation_state: "not_installed",
        installation_kind: "none",
        local_package_evidence: null,
      },
    });

    for (const mutate of [
      (value: Record<string, any>) => { value.package_changed = false; },
      (value: Record<string, any>) => { value.process_started = true; },
      (value: Record<string, any>) => { value.server.local_package_evidence = {
        artifact_sha256: "4".repeat(64),
      }; },
    ]) {
      const invalid = structuredClone(
        syntheticMcpManagedLocalUninstallReceipt(),
      ) as Record<string, any>;
      mutate(invalid);
      expect(() => parseMcpManagedLifecycleReceipt(invalid))
        .toThrow(McpManagedServerPayloadError);
    }
  });

  it("accepts exact interrupted-uninstall recovery and rejects false effects", () => {
    expect(parseMcpManagedLocalCleanupPreview(
      syntheticMcpManagedLocalCleanupPreview(),
    )).toMatchObject({
      availability: "available",
      effects: [
        "verify_operation_journal",
        "verify_installed_or_quarantined_tree_digest",
        "finish_quarantined_removal",
        "clear_cleanup_state",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    expect(parseMcpManagedLocalCleanupReceipt(
      syntheticMcpManagedLocalCleanupReceipt(),
    )).toMatchObject({
      package_presence: "absent",
      filesystem_changed: true,
      process_started: false,
      connection_retained: false,
      persistent_host_started: false,
      tool_authority_granted: false,
      server: { installation_state: "not_installed", operation_state: "idle" },
    });

    for (const mutate of [
      (value: Record<string, any>) => { value.effects.reverse(); },
      (value: Record<string, any>) => { value.effects.push("execute_tool"); },
    ]) {
      const invalid = structuredClone(
        syntheticMcpManagedLocalCleanupPreview(),
      ) as Record<string, any>;
      mutate(invalid);
      expect(() => parseMcpManagedLocalCleanupPreview(invalid))
        .toThrow(McpManagedServerPayloadError);
    }
    const replay = structuredClone(
      syntheticMcpManagedLocalCleanupReceipt(),
    ) as Record<string, any>;
    replay.idempotent_replay = true;
    replay.filesystem_changed = true;
    expect(() => parseMcpManagedLocalCleanupReceipt(replay))
      .toThrow(McpManagedServerPayloadError);
  });

  it("accepts only a coherent exact local-package update preview", () => {
    expect(parseMcpManagedLocalUpdatePreview(
      syntheticMcpManagedLocalUpdatePreview(),
    )).toMatchObject({
      action: "update",
      current_version: "1.2.3",
      target_version: "2.0.0",
      availability: "available",
      effects: [
        "resolve_official_latest_exact_version",
        "download_exact_target_package",
        "verify_target_artifact_sha256",
        "stage_target_in_isolation",
        "execute_bounded_target_probe",
        "stop_and_verify_target_process_tree",
        "retain_verified_rollback_generation",
        "publish_verified_target_package",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });

    const alreadyLatest = syntheticMcpManagedLocalUpdatePreview({
      target_version: "1.2.3",
      target_catalog_id: null,
      target_option_id: null,
      target_plan_revision: null,
      availability: "unavailable",
      reason: "already_latest",
    });
    expect(parseMcpManagedLocalUpdatePreview(alreadyLatest).reason)
      .toBe("already_latest");

    for (const mutate of [
      (value: Record<string, any>) => { value.effects.reverse(); },
      (value: Record<string, any>) => { value.target_option_id = null; },
      (value: Record<string, any>) => { value.target_version = value.current_version; },
      (value: Record<string, any>) => { value.install_command = "synthetic"; },
    ]) {
      const invalid = structuredClone(
        syntheticMcpManagedLocalUpdatePreview(),
      ) as Record<string, any>;
      mutate(invalid);
      expect(() => parseMcpManagedLocalUpdatePreview(invalid))
        .toThrow(McpManagedServerPayloadError);
    }
  });

  it("accepts only a verified atomic update receipt with one rollback generation", () => {
    expect(parseMcpManagedLocalUpdateReceipt(
      syntheticMcpManagedLocalUpdateReceipt(),
    )).toMatchObject({
      action: "update",
      package_changed: true,
      process_started: true,
      process_tree_cleanup: "verified",
      rollback_generation_retained: true,
      server: {
        installation_state: "installed",
        operation_state: "idle",
        server_version: "2.0.0",
        rollback_generation: { server_version: "1.2.3" },
      },
    });

    const invalid = structuredClone(
      syntheticMcpManagedLocalUpdateReceipt(),
    ) as Record<string, any>;
    invalid.process_tree_cleanup = "unconfirmed";
    expect(() => parseMcpManagedLocalUpdateReceipt(invalid))
      .toThrow(McpManagedServerPayloadError);
  });

  it("accepts reversible rollback and rejects a receipt without its superseded generation", () => {
    expect(parseMcpManagedLocalRollbackPreview(
      syntheticMcpManagedLocalRollbackPreview(),
    )).toMatchObject({
      availability: "available",
      current_version: "2.0.0",
      target_version: "1.2.3",
      effects: [
        "verify_current_tree_digest",
        "verify_rollback_tree_digest",
        "atomically_swap_verified_generations",
        "retain_superseded_current_generation",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    expect(parseMcpManagedLocalRollbackReceipt(
      syntheticMcpManagedLocalRollbackReceipt(),
    )).toMatchObject({
      package_changed: true,
      process_started: false,
      rollback_generation_retained: true,
      server: {
        server_version: "1.2.3",
        rollback_generation: { server_version: "2.0.0" },
      },
    });

    const invalid = structuredClone(
      syntheticMcpManagedLocalRollbackReceipt(),
    ) as Record<string, any>;
    invalid.server.rollback_generation = null;
    expect(() => parseMcpManagedLocalRollbackReceipt(invalid))
      .toThrow(McpManagedServerPayloadError);
  });

  it("accepts verified rollback-generation cleanup and fail-closes on replay contradictions", () => {
    expect(parseMcpManagedLocalRollbackCleanupPreview(
      syntheticMcpManagedLocalRollbackCleanupPreview(),
    )).toMatchObject({
      action: "cleanup_rollback_generation",
      rollback_version: "1.2.3",
      availability: "available",
    });
    expect(parseMcpManagedLocalRollbackCleanupReceipt(
      syntheticMcpManagedLocalRollbackCleanupReceipt(),
    )).toMatchObject({
      filesystem_changed: true,
      rollback_generation_retained: false,
      process_started: false,
      server: { rollback_generation: null },
    });

    const invalid = structuredClone(
      syntheticMcpManagedLocalRollbackCleanupReceipt(),
    ) as Record<string, any>;
    invalid.idempotent_replay = true;
    expect(() => parseMcpManagedLocalRollbackCleanupReceipt(invalid))
      .toThrow(McpManagedServerPayloadError);
  });

  it("binds interrupted-operation recovery effects to the exact journal action", () => {
    expect(parseMcpManagedLocalOperationRecoveryPreview(
      syntheticMcpManagedLocalOperationRecoveryPreview(),
    )).toMatchObject({
      interrupted_action: "update",
      effects: [
        "verify_operation_journal",
        "restore_durable_current_generation",
        "discard_verified_staged_target",
        "clear_cleanup_state",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    expect(parseMcpManagedLocalOperationRecoveryReceipt(
      syntheticMcpManagedLocalOperationRecoveryReceipt(),
    )).toMatchObject({
      recovered_action: "update",
      filesystem_state_verified: true,
      process_started: false,
      server: { installation_state: "installed", rollback_generation: null },
    });

    const wrongEffects = structuredClone(
      syntheticMcpManagedLocalOperationRecoveryPreview(),
    ) as Record<string, any>;
    wrongEffects.interrupted_action = "rollback";
    expect(() => parseMcpManagedLocalOperationRecoveryPreview(wrongEffects))
      .toThrow(McpManagedServerPayloadError);

    const wrongResult = structuredClone(
      syntheticMcpManagedLocalOperationRecoveryReceipt(),
    ) as Record<string, any>;
    wrongResult.recovered_action = "rollback";
    expect(() => parseMcpManagedLocalOperationRecoveryReceipt(wrongResult))
      .toThrow(McpManagedServerPayloadError);
  });

  it("rejects lifecycle claims with stale shapes or hidden authority", () => {
    const preview = structuredClone(
      syntheticMcpManagedLifecyclePreview(),
    ) as Record<string, any>;
    preview.effects.push("execute_tool");
    expect(() => parseMcpManagedLifecyclePreview(preview))
      .toThrow(McpManagedServerPayloadError);

    const receipt = structuredClone(
      syntheticMcpManagedLifecycleReceipt(),
    ) as Record<string, any>;
    receipt.connection_retained = true;
    expect(() => parseMcpManagedLifecycleReceipt(receipt))
      .toThrow(McpManagedServerPayloadError);

    const localReceipt = structuredClone(
      syntheticMcpManagedLocalLifecycleReceipt(),
    ) as Record<string, any>;
    localReceipt.process_tree_cleanup = "not_applicable";
    expect(() => parseMcpManagedLifecycleReceipt(localReceipt))
      .toThrow(McpManagedServerPayloadError);

    const incoherentRuntime = structuredClone(
      syntheticMcpManagedLocalLifecycleReceipt(),
    ) as Record<string, any>;
    incoherentRuntime.server.local_package_evidence.runtime_version = null;
    expect(() => parseMcpManagedLifecycleReceipt(incoherentRuntime))
      .toThrow(McpManagedServerPayloadError);
  });
});
