import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  McpManagedServer,
  McpManagedServerList,
  McpRegistryCatalog,
  McpRegistryInputRequirement,
  McpRegistryInstallOption,
  McpRegistryServer,
  McpRegistryServerReview,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import { TabList, tabId, tabPanelId, type TabDescriptor } from "../../shared/ui/Tabs";
import { AgentMcpManagedPlanView } from "./AgentMcpManagedPlanView";
import type {
  TrustedMcpAcceptanceEvidence,
  TrustedMcpAcceptanceRun,
} from "./trustedMcpAcceptance";
import "./AgentMcpStorePanel.css";

type StoreTransport = Partial<Pick<
  PromptEnhancerTransport,
  | "listMcpRegistryCatalog"
  | "getMcpRegistryServerReview"
  | "listMcpManagedServers"
  | "getMcpManagedServer"
  | "getMcpManagedToolSnapshot"
  | "getMcpManagedHostStatus"
  | "getMcpManagedHostStartPreview"
  | "startMcpManagedHost"
  | "stopMcpManagedHost"
  | "getMcpManagedProjectRuntime"
  | "createMcpManagedServer"
  | "probeMcpManagedServer"
  | "getMcpManagedLifecyclePreview"
  | "getMcpManagedLocalConfigurationInspectionPreview"
  | "inspectMcpManagedLocalConfiguration"
  | "applyMcpManagedLifecycle"
  | "getMcpManagedLocalCleanupPreview"
  | "getMcpManagedLocalUpdatePreview"
  | "applyMcpManagedLocalUpdate"
  | "getMcpManagedLocalRollbackPreview"
  | "applyMcpManagedLocalRollback"
  | "getMcpManagedLocalRollbackCleanupPreview"
  | "cleanupMcpManagedLocalRollback"
  | "getMcpManagedLocalOperationRecoveryPreview"
  | "recoverMcpManagedLocalOperation"
  | "completeMcpManagedLocalCleanup"
  | "listAgentProjects"
  | "setMcpManagedProjectBinding"
  | "storeMcpManagedSecret"
  | "removeMcpManagedSecret"
  | "storeMcpManagedConfiguration"
  | "removeMcpManagedConfiguration"
>>;
type StoreState = "loading" | "ready" | "unavailable";
type ReviewState = "idle" | "loading" | "ready" | "unavailable";
type DistributionFilter = "all" | "local" | "remote";
type CatalogSort = "registry" | "title" | "updated" | "managed";
type StoreView = "browse" | "managed";
type StoreFailure =
  | "missing_route"
  | "registry_unavailable"
  | "authentication"
  | "invalid_contract"
  | "not_found"
  | "source_conflict"
  | "pagination_cycle"
  | "pagination_replay"
  | "page_limit"
  | "request_failed";

const MAX_CATALOG_PAGES = 32;
const CATALOG_RENDER_PAGE_SIZE = 48;

const MCP_STORE_VIEWS: readonly TabDescriptor<StoreView>[] = [
  { id: "browse", label: "Browse servers" },
  { id: "managed", label: "Managed servers" },
] as const;

function storeFailure(error: unknown): StoreFailure {
  if (!(error instanceof TransportError)) return "request_failed";
  if (
    error.reasonCode === "mcp_registry_identity_conflict"
    || error.reasonCode === "mcp_registry_source_disagreement"
  ) return "source_conflict";
  if (error.reasonCode === "mcp_registry_pagination_cycle") return "pagination_cycle";
  if (error.reasonCode === "mcp_registry_response_invalid") return "invalid_contract";
  if (error.status === 401 || error.status === 403) return "authentication";
  if (error.status === 404) return "not_found";
  if (error.status === 503) return "registry_unavailable";
  if (error.status === 200) return "invalid_contract";
  return "request_failed";
}

function storeFailureMessage(failure: StoreFailure): string {
  if (failure === "missing_route") return "This build does not expose the local catalog route.";
  if (failure === "authentication") return "The local browser session could not authenticate the catalog request.";
  if (failure === "invalid_contract") return "The local API rejected an invalid Registry response instead of rendering untrusted metadata.";
  if (failure === "registry_unavailable") return "The official Registry and an exact cached result were unavailable.";
  if (failure === "not_found") return "That exact server version is no longer available in the official Registry.";
  if (failure === "source_conflict") return "The Registry disagreed about this exact server identity. Existing trusted results were preserved.";
  if (failure === "pagination_cycle") return "The Registry repeated an earlier page cursor. Loading stopped before a loop could begin.";
  if (failure === "pagination_replay") return "The Registry replayed a page without adding a new server. Loading stopped before repeated requests could continue.";
  if (failure === "page_limit") return "This catalog journey reached its 32-page safety limit. Start a narrower search to continue.";
  return "The catalog request did not complete. Agent chat remains usable.";
}

function sameRegistryServer(left: McpRegistryServer, right: McpRegistryServer): boolean {
  return left.presentation_revision === right.presentation_revision
    && JSON.stringify(left) === JSON.stringify(right);
}

function catalogPageFingerprint(catalog: McpRegistryCatalog): string {
  return catalog.servers
    .map((server) => `${server.catalog_id}:${server.presentation_revision}`)
    .join("|");
}

function paginationCanRetry(failure: StoreFailure): boolean {
  return failure === "authentication"
    || failure === "registry_unavailable"
    || failure === "request_failed";
}

function serverInitials(server: McpRegistryServer): string {
  const words = server.title.split(/\s+/u).filter(Boolean);
  return (words.length > 1 ? `${words[0][0]}${words[1][0]}` : words[0]?.slice(0, 2) ?? "MC")
    .toLocaleUpperCase();
}

function registryDate(value: string | null): string {
  if (value === null) return "Not reported";
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function McpServerMark({ server }: { server: McpRegistryServer }) {
  const [failed, setFailed] = useState(false);
  if (server.icon === null || failed) {
    return (
      <span
        aria-label={server.icon === null
          ? "Generated initials; no Registry logo was declared"
          : "Generated initials; the Registry logo could not be displayed"}
        className="agent-mcp-store__fallback-mark"
        role="img"
      >
        {serverInitials(server)}
      </span>
    );
  }
  return (
    <img
      alt="Logo supplied through the local Official Registry image proxy"
      className="agent-mcp-store__icon"
      decoding="async"
      height="40"
      loading="lazy"
      onError={() => setFailed(true)}
      src={server.icon.path}
      width="40"
    />
  );
}

function transportLabel(value: string): string {
  if (value === "streamable-http") return "HTTP";
  if (value === "stdio") return "stdio";
  if (value === "sse") return "SSE";
  return "Unknown transport";
}

function McpServerCard({
  managed,
  onReview,
  reviewAvailable,
  server,
}: {
  managed: McpManagedServer | null;
  onReview: (server: McpRegistryServer) => void;
  reviewAvailable: boolean;
  server: McpRegistryServer;
}) {
  const distributions = [
    ...new Set([
      ...server.packages.map((item) => item.registry_type.toLocaleUpperCase()),
      ...server.remotes.map((item) => transportLabel(item.transport)),
    ]),
  ];
  return (
    <article
      className="agent-mcp-store__card"
      data-managed={managed === null ? "false" : "true"}
      data-status={server.status}
    >
      <header>
        <McpServerMark server={server} />
        <span className="agent-mcp-store__identity">
          <strong>{server.title}</strong>
          <small title={server.name}>{server.name}</small>
        </span>
        <span className="agent-mcp-store__status">{server.status}</span>
      </header>
      <div className="agent-mcp-store__source-line">
        <span>Official Registry</span>
        <span>{server.icon ? "Registry logo declared" : "Initials fallback"}</span>
      </div>
      <p>{server.description}</p>
      <div aria-label="Distribution options" className="agent-mcp-store__pills">
        {distributions.length > 0 ? distributions.slice(0, 4).map((item) => (
          <span key={item}>{item}</span>
        )) : <span>Metadata only</span>}
      </div>
      <dl className="agent-mcp-store__facts">
        <div><dt>Version</dt><dd>{server.version}</dd></div>
        <div><dt>Publisher</dt><dd>{server.publisher}</dd></div>
        <div><dt>Updated</dt><dd>{registryDate(server.updated_at)}</dd></div>
        <div><dt>Lifecycle</dt><dd>{managed ? managedStateLabel(managed) : "Not managed"}</dd></div>
      </dl>
      <footer>
        <button
          aria-label={reviewAvailable ? `Review ${server.title}` : `Review unavailable for ${server.title}`}
          className="button button--ghost"
          disabled={!reviewAvailable}
          onClick={() => onReview(server)}
          type="button"
        >
          {reviewAvailable ? "View details" : "Review unavailable"}
        </button>
      </footer>
    </article>
  );
}

const riskLabels: Record<string, string> = {
  downloads_package: "Downloads package content",
  executes_local_code: "Executes code on this machine",
  package_integrity_not_declared: "No package checksum declared",
  command_arguments_declared: "Constructs command arguments",
  filesystem_input_declared: "Requests a filesystem path",
  credential_input_declared: "Requests secret or credential input",
  remote_network_egress: "Connects to a remote network service",
  insecure_remote_transport: "Declares an insecure HTTP endpoint",
};

const compatibilityReasonLabels: Record<string, string> = {
  known_package_registry: "Package registry is recognized by the reviewed installer",
  unknown_package_registry: "Package registry is not supported by the reviewed installer",
  supported_transport: "Transport metadata is supported",
  unknown_transport: "Transport metadata is unknown",
  runtime_hint_missing: "Required runtime was not declared",
  configuration_required: "Configuration must be completed before a live check",
  endpoint_template_requires_configuration: "Endpoint template needs configuration",
  endpoint_invalid: "Endpoint metadata is invalid",
  machine_runtime_not_probed: "This machine's runtime has not been probed",
  platform_not_declared: "The publisher did not declare platform compatibility",
  mcp_handshake_not_performed: "An MCP handshake has not been performed",
};

function compatibilityLabel(option: McpRegistryInstallOption): string {
  if (option.compatibility.status === "reviewable") return "Metadata reviewable";
  if (option.compatibility.status === "requires_configuration") return "Configuration required";
  return "Unsupported";
}

function compatibilitySummary(option: McpRegistryInstallOption): string {
  if (option.compatibility.status === "reviewable") {
    return "The declared option can enter a guarded setup plan. Runtime, platform and handshake evidence remain unverified until the exact compatibility flow runs.";
  }
  if (option.compatibility.status === "requires_configuration") {
    return "The option can be reviewed, but required configuration or runtime evidence must be completed before activation or installation can be admitted.";
  }
  return "This metadata cannot enter the guarded lifecycle. No setup plan, package, connection or tool authority will be created for this option.";
}

const requirementLocationLabels: Record<McpRegistryInputRequirement["location"], string> = {
  runtime_argument: "Runtime argument",
  package_argument: "Package argument",
  environment_variable: "Environment variable",
  transport_header: "Transport header",
  remote_variable: "Endpoint variable",
};

function requirementFacts(requirement: McpRegistryInputRequirement): string[] {
  const facts = [requirementLocationLabels[requirement.location]];
  if (requirement.required) facts.push("required");
  if (requirement.secret) facts.push("secret");
  if (requirement.format !== "unknown") facts.push(requirement.format);
  if (requirement.fixed_value_declared) facts.push("publisher-fixed value");
  else if (requirement.default_declared) facts.push("default declared");
  if (requirement.choices_count > 0) facts.push(`${requirement.choices_count} choices`);
  if (requirement.repeated) facts.push("repeatable");
  return facts;
}

function optionIdentity(option: McpRegistryInstallOption): string {
  if (option.package_identifier) return option.package_identifier;
  if (option.endpoint_host) return option.endpoint_host;
  if (option.endpoint_state === "template_requires_configuration") return "Endpoint template requires configuration";
  if (option.endpoint_state === "invalid") return "Endpoint metadata is invalid";
  return "No endpoint declared";
}

function managedStateLabel(server: McpManagedServer): string {
  if (server.operation_state !== "idle") {
    return ({
      installing: "Installing",
      updating: "Updating",
      uninstalling: "Removing",
      rolling_back: "Rolling back",
      cleaning_up: "Cleaning up",
      cleanup_required: "Cleanup required",
    } as const)[server.operation_state];
  }
  if (server.lifecycle_state === "cleanup_required") return "Cleanup required";
  if (server.installation_state === "installed") {
    return server.installation_kind === "remote_activation" ? "Remote plan active" : "Installed";
  }
  return "Plan saved";
}

function managedEvidenceLabel(server: McpManagedServer): string {
  if (server.lifecycle_state === "cleanup_required" || server.operation_state === "cleanup_required") {
    return "Recovery blocks new lifecycle actions";
  }
  if (server.health_state === "compatible") return "Compatibility verified";
  return "Compatibility not checked";
}

function McpCatalogSkeleton() {
  return (
    <div aria-hidden="true" className="agent-mcp-store__grid agent-mcp-store__skeleton-grid">
      {[0, 1, 2, 3].map((item) => (
        <div className="agent-mcp-store__skeleton" key={item}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

function McpReviewOption({
  busy,
  canPrepare,
  managed,
  onOpenManaged,
  onPrepare,
  option,
  reviewPlanRevision,
}: {
  busy: boolean;
  canPrepare: boolean;
  managed: McpManagedServer | null;
  onOpenManaged: (server: McpManagedServer) => void;
  onPrepare: (option: McpRegistryInstallOption) => void;
  option: McpRegistryInstallOption;
  reviewPlanRevision: string;
}) {
  const managedPlanCurrent = managed?.plan_revision === reviewPlanRevision;
  return (
    <article
      className="agent-mcp-store__review-option"
      data-compatibility={option.compatibility.status}
      data-plan-state={managed ? (managedPlanCurrent ? "current" : "changed") : "not-saved"}
    >
      <header>
        <span>
          <small>{option.kind === "local_package" ? "Local package" : "Remote server"}</small>
          <strong>{option.label}</strong>
        </span>
        <span>{compatibilityLabel(option)}</span>
      </header>
      <code>{optionIdentity(option)}</code>
      <dl className="agent-mcp-store__review-facts">
        <div><dt>Transport</dt><dd>{transportLabel(option.transport)}</dd></div>
        <div><dt>Runtime</dt><dd>{option.runtime_hint ?? "Not declared"}</dd></div>
        <div><dt>Checksum</dt><dd>{option.checksum_state.replaceAll("_", " ")}</dd></div>
        <div><dt>Platform</dt><dd>Unverified</dd></div>
        <div><dt>Runtime found</dt><dd>Not probed</dd></div>
        <div><dt>MCP handshake</dt><dd>Not performed</dd></div>
      </dl>
      <section
        aria-label={`${option.label} compatibility evidence`}
        className="agent-mcp-store__compatibility"
      >
        <strong>Compatibility evidence</strong>
        <p>{compatibilitySummary(option)}</p>
        <ul>
          {option.compatibility.reasons.map((reason) => (
            <li key={reason}>{compatibilityReasonLabels[reason] ?? reason.replaceAll("_", " ")}</li>
          ))}
        </ul>
      </section>
      <section aria-label={`${option.label} risk disclosures`}>
        <strong>What this option could do</strong>
        {option.risks.length > 0 ? (
          <ul className="agent-mcp-store__risk-list">
            {option.risks.map((risk) => <li key={risk}>{riskLabels[risk] ?? risk}</li>)}
          </ul>
        ) : <p>No capability risks were inferred from the bounded Registry fields.</p>}
      </section>
      <section aria-label={`${option.label} configuration requirements`}>
        <strong>Declared configuration</strong>
        {option.requirements.length > 0 ? (
          <ul className="agent-mcp-store__requirements">
            {option.requirements.map((requirement) => (
              <li key={requirement.requirement_id}>
                <span>
                  <code>{requirement.name}</code>
                  {requirement.user_value_needed && <b>Input needed</b>}
                </span>
                <small>{requirementFacts(requirement).join(" · ")}</small>
                {requirement.description && <p>{requirement.description}</p>}
              </li>
            ))}
          </ul>
        ) : <p>No configuration inputs are declared for this option.</p>}
      </section>
      <footer>
        {managed ? (
          <button className="button button--ghost" onClick={() => onOpenManaged(managed)} type="button">
            {managedPlanCurrent ? "Open prepared plan" : "Open previous plan"}
          </button>
        ) : (
          <button
            className="button button--ghost"
            disabled={!canPrepare || busy}
            onClick={() => onPrepare(option)}
            type="button"
          >
            {busy ? "Confirming…" : "Save setup plan"}
          </button>
        )}
        <small>
          {managed
            ? managedPlanCurrent
              ? "Lifecycle actions live in this exact managed plan, with compatibility evidence and native confirmation before every protected change."
              : "Registry evidence changed since this plan was prepared. Open the previous plan to review it; this newer review is not silently applied."
            : "Saving creates durable reviewed metadata only. Installation or activation happens later inside the exact managed plan and remains native-confirmed."}
        </small>
      </footer>
    </article>
  );
}

function reviewFailureMessage(failure: StoreFailure): string {
  if (failure === "registry_unavailable") return "The official Registry could not provide this exact review.";
  return storeFailureMessage(failure);
}

function McpServerReviewView({
  busyOption,
  canPrepare,
  failure,
  managedServers,
  onBack,
  onOpenManaged,
  onPrepare,
  onRetry,
  review,
  server,
  state,
}: {
  busyOption: string | null;
  canPrepare: boolean;
  failure: StoreFailure | null;
  managedServers: McpManagedServer[];
  onBack: () => void;
  onOpenManaged: (server: McpManagedServer) => void;
  onPrepare: (option: McpRegistryInstallOption) => void;
  onRetry: () => void;
  review: McpRegistryServerReview | null;
  server: McpRegistryServer;
  state: ReviewState;
}) {
  return (
    <section aria-labelledby="agent-mcp-store-review-title" className="agent-mcp-store__review">
      <button className="button button--ghost agent-mcp-store__back" onClick={onBack} type="button">
        Back to catalog
      </button>
      <header className="agent-mcp-store__review-head">
        <McpServerMark server={server} />
        <span>
          <small>Read-only server review</small>
          <h3 id="agent-mcp-store-review-title">{server.title}</h3>
          <code>{server.name} · {server.version}</code>
        </span>
      </header>
      <p className="agent-mcp-store__review-boundary">
        Preview only. This review cannot install or run code, connect an endpoint, collect a credential,
        or edit an MCP client configuration.
      </p>
      {state === "loading" && (
        <p className="agent-mcp-store__state" role="status">Loading the exact version and safety plan…</p>
      )}
      {state === "unavailable" && (
        <div className="agent-mcp-store__state" role="status">
          <p>{reviewFailureMessage(failure ?? "request_failed")}</p>
          <button className="button button--ghost" onClick={onRetry} type="button">
            {failure === "source_conflict" || failure === "invalid_contract" ? "Reload catalog" : "Retry review"}
          </button>
        </div>
      )}
      {state === "ready" && review && (
        <>
          <div className="agent-mcp-store__review-meta">
            <span>Official Registry · {review.source.delivery}</span>
            <span>Fetched {registryDate(review.source.fetched_at)}</span>
            <span>Registry record · not a security approval</span>
            <span>License · not declared by Registry contract</span>
            <span>Plan {review.plan_revision.slice(0, 12)}</span>
            {review.partial && <span>Partial metadata disclosed</span>}
          </div>
          <section className="agent-mcp-store__provenance" aria-labelledby="agent-mcp-store-provenance-title">
            <header>
              <h4 id="agent-mcp-store-provenance-title">Publisher and source provenance</h4>
              <span>{review.provenance.publisher_namespace}</span>
            </header>
            <dl>
              <div><dt>Repository identity</dt><dd>{review.provenance.repository_identity_declared ? "Declared" : "Not declared"}</dd></div>
              <div><dt>Repository subfolder</dt><dd>{review.provenance.repository_subfolder_declared ? "Declared" : "Not declared"}</dd></div>
              <div><dt>Repository source</dt><dd>{review.provenance.repository_source ?? "Not declared"}</dd></div>
              <div><dt>License</dt><dd>Not declared by Registry contract</dd></div>
              <div><dt>Registry security review</dt><dd>Not claimed</dd></div>
              <div><dt>Version history</dt><dd>{review.version_history_state}</dd></div>
            </dl>
            <nav aria-label="Server provenance links">
              {review.provenance.repository_url && <a href={review.provenance.repository_url} rel="noreferrer noopener" target="_blank">Source repository</a>}
              {review.provenance.website_url && <a href={review.provenance.website_url} rel="noreferrer noopener" target="_blank">Project website</a>}
              {review.provenance.schema_url && <a href={review.provenance.schema_url} rel="noreferrer noopener" target="_blank">Registry schema</a>}
            </nav>
          </section>
          <section className="agent-mcp-store__versions" aria-labelledby="agent-mcp-store-versions-title">
            <header>
              <h4 id="agent-mcp-store-versions-title">Versions</h4>
              <small>{review.version_history_state === "live" ? "Exact live history" : "History is incomplete"}</small>
            </header>
            <div>
              {review.versions.map((item) => (
                <span data-selected={item.selected || undefined} key={item.version}>
                  {item.version}{item.selected ? " · selected" : ""} · {item.status}
                </span>
              ))}
            </div>
          </section>
          <section className="agent-mcp-store__options" aria-labelledby="agent-mcp-store-options-title">
            <header>
              <span>
                <h4 id="agent-mcp-store-options-title">Declared setup options</h4>
                <small>Compatibility here means the metadata can be reviewed—not that this PC can run it.</small>
              </span>
              <b>{review.options.length}</b>
            </header>
            {review.options.length > 0 ? review.options.map((option) => (
              <McpReviewOption
                busy={busyOption === option.option_id}
                canPrepare={canPrepare && review.server.status === "active" && option.compatibility.status !== "unsupported"}
                key={option.option_id}
                managed={managedServers.find((item) => item.catalog_id === review.server.catalog_id && item.option_id === option.option_id) ?? null}
                onOpenManaged={onOpenManaged}
                onPrepare={onPrepare}
                option={option}
                reviewPlanRevision={review.plan_revision}
              />
            )) : (
              <p className="agent-mcp-store__state">This version declares no reviewable package or remote endpoint.</p>
            )}
          </section>
          <aside className="agent-mcp-store__next-gate">
            <strong>Protected lifecycle continues in a managed plan</strong>
            <p>
              Save one exact supported option first. The managed plan then exposes configuration inspection,
              compatibility checks, install or remote activation, update, rollback, removal and interrupted-operation
              recovery only when their current revision-bound preview is available. Every protected change still
              requires native confirmation; saving a plan alone starts nothing.
            </p>
          </aside>
        </>
      )}
    </section>
  );
}

export function AgentMcpStorePanel({
  acceptanceRun = null,
  activeEventHead = 0,
  activeProjectId = null,
  activeSessionId = null,
  onAcceptanceEvidence,
  onAcceptanceRunChange,
  onManagedStateChange,
  transport,
  userPresenceAvailable = false,
}: {
  acceptanceRun?: TrustedMcpAcceptanceRun | null;
  activeEventHead?: number;
  activeProjectId?: string | null;
  activeSessionId?: string | null;
  onAcceptanceEvidence?: (evidence: TrustedMcpAcceptanceEvidence) => void;
  onAcceptanceRunChange?: (run: TrustedMcpAcceptanceRun | null) => void;
  onManagedStateChange?: () => void;
  transport: StoreTransport;
  userPresenceAvailable?: boolean;
}) {
  const [state, setState] = useState<StoreState>("loading");
  const [failure, setFailure] = useState<StoreFailure | null>(null);
  const [catalog, setCatalog] = useState<McpRegistryCatalog | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [filter, setFilter] = useState<DistributionFilter>("all");
  const [sort, setSort] = useState<CatalogSort>("registry");
  const [storeView, setStoreView] = useState<StoreView>("browse");
  const [loadingMore, setLoadingMore] = useState(false);
  const [paginationFailure, setPaginationFailure] = useState<StoreFailure | null>(null);
  const [failedCursor, setFailedCursor] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selectedServer, setSelectedServer] = useState<McpRegistryServer | null>(null);
  const [review, setReview] = useState<McpRegistryServerReview | null>(null);
  const [reviewState, setReviewState] = useState<ReviewState>("idle");
  const [reviewFailure, setReviewFailure] = useState<StoreFailure | null>(null);
  const [managed, setManaged] = useState<McpManagedServerList | null>(null);
  const [managedState, setManagedState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [selectedManaged, setSelectedManaged] = useState<McpManagedServer | null>(null);
  const [busyOption, setBusyOption] = useState<string | null>(null);
  const [managementMessage, setManagementMessage] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const catalogRef = useRef<McpRegistryCatalog | null>(null);
  const successfulCatalogPages = useRef(0);
  const seenCatalogCursors = useRef(new Set<string>());
  const seenCatalogPages = useRef(new Set<string>());
  const reviewRequest = useRef<AbortController | null>(null);
  const managedRequest = useRef<AbortController | null>(null);
  const planRequestIds = useRef(new Map<string, string>());

  const load = useCallback((search: string, cursor?: string) => {
    const listCatalog = transport.listMcpRegistryCatalog;
    if (listCatalog === undefined) {
      setCatalog(null);
      setFailure("missing_route");
      setState("unavailable");
      return;
    }
    if (cursor && successfulCatalogPages.current >= MAX_CATALOG_PAGES) {
      setPaginationFailure("page_limit");
      setFailedCursor(cursor);
      setLoadingMore(false);
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    if (cursor) {
      setLoadingMore(true);
      setPaginationFailure(null);
      setFailedCursor(null);
    }
    else {
      setState("loading");
      catalogRef.current = null;
      successfulCatalogPages.current = 0;
      seenCatalogCursors.current = new Set();
      seenCatalogPages.current = new Set();
      setCatalog(null);
      setFailure(null);
      setPaginationFailure(null);
      setFailedCursor(null);
    }
    void listCatalog({ search, cursor, limit: 24 }, controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      if (!cursor) {
        catalogRef.current = next;
        successfulCatalogPages.current = 1;
        seenCatalogPages.current = new Set([catalogPageFingerprint(next)]);
        setCatalog(next);
      } else {
        const current = catalogRef.current;
        if (current === null || current.search !== next.search) {
          setPaginationFailure("invalid_contract");
          setFailedCursor(cursor);
          setLoadingMore(false);
          return;
        }
        const nextSeenCursors = new Set(seenCatalogCursors.current);
        nextSeenCursors.add(cursor);
        const pageFingerprint = catalogPageFingerprint(next);
        if (next.next_cursor !== null && nextSeenCursors.has(next.next_cursor)) {
          setPaginationFailure("pagination_cycle");
          setFailedCursor(cursor);
          setLoadingMore(false);
          return;
        }
        if (seenCatalogPages.current.has(pageFingerprint)) {
          setPaginationFailure("pagination_replay");
          setFailedCursor(cursor);
          setLoadingMore(false);
          return;
        }
        const existing = new Map(current.servers.map((item) => [item.catalog_id, item]));
        let added = 0;
        for (const item of next.servers) {
          const prior = existing.get(item.catalog_id);
          if (prior !== undefined && !sameRegistryServer(prior, item)) {
            setPaginationFailure("source_conflict");
            setFailedCursor(cursor);
            setLoadingMore(false);
            return;
          }
          if (prior === undefined) {
            existing.set(item.catalog_id, item);
            added += 1;
          }
        }
        if (next.next_cursor !== null && added === 0) {
          setPaginationFailure("pagination_replay");
          setFailedCursor(cursor);
          setLoadingMore(false);
          return;
        }
        const merged = {
          ...next,
          servers: [...existing.values()],
          partial: current.partial || next.partial,
        };
        seenCatalogCursors.current = nextSeenCursors;
        seenCatalogPages.current = new Set(seenCatalogPages.current).add(pageFingerprint);
        successfulCatalogPages.current += 1;
        catalogRef.current = merged;
        setCatalog(merged);
      }
      setState("ready");
      setFailure(null);
      setLoadingMore(false);
      setPaginationFailure(null);
      setFailedCursor(null);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (!cursor) {
        setCatalog(null);
        setFailure(storeFailure(error));
        setState("unavailable");
      } else {
        setPaginationFailure(storeFailure(error));
        setFailedCursor(cursor);
      }
      setLoadingMore(false);
    });
  }, [transport.listMcpRegistryCatalog]);

  useEffect(() => {
    load(appliedSearch);
    return () => request.current?.abort();
  }, [appliedSearch, attempt, load]);

  useEffect(() => () => reviewRequest.current?.abort(), []);

  const loadManaged = useCallback(() => {
    const listManaged = transport.listMcpManagedServers;
    if (listManaged === undefined) {
      setManaged(null);
      setManagedState("unavailable");
      return;
    }
    managedRequest.current?.abort();
    const controller = new AbortController();
    managedRequest.current = controller;
    setManagedState("loading");
    void listManaged(controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setManaged(value);
      setSelectedManaged((current) => current === null
        ? null
        : value.servers.find((item) => item.management_id === current.management_id) ?? null);
      setManagedState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setManaged(null);
      setManagedState("unavailable");
    });
  }, [transport.listMcpManagedServers]);

  useEffect(() => {
    loadManaged();
    return () => managedRequest.current?.abort();
  }, [loadManaged]);

  const openReview = useCallback((server: McpRegistryServer) => {
    const getReview = transport.getMcpRegistryServerReview;
    setStoreView("browse");
    setSelectedServer(server);
    setReview(null);
    setReviewFailure(null);
    if (getReview === undefined) {
      setReviewState("unavailable");
      setReviewFailure("missing_route");
      return;
    }
    reviewRequest.current?.abort();
    const controller = new AbortController();
    reviewRequest.current = controller;
    setReviewState("loading");
    void getReview({
      catalog_id: server.catalog_id,
      name: server.name,
      presentation_revision: server.presentation_revision,
      version: server.version,
    }, controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      setReview(next);
      setReviewState("ready");
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setReviewFailure(storeFailure(error));
      setReviewState("unavailable");
    });
  }, [transport.getMcpRegistryServerReview]);

  const closeReview = () => {
    reviewRequest.current?.abort();
    setSelectedServer(null);
    setReview(null);
    setReviewFailure(null);
    setReviewState("idle");
  };

  const upsertManaged = useCallback((server: McpManagedServer) => {
    setStoreView("managed");
    setSelectedManaged(server);
    setManaged((current) => {
      if (current === null) return current;
      const next = current.servers.filter((item) => item.management_id !== server.management_id);
      next.unshift(server);
      return { ...current, servers: next, total: next.length };
    });
    onManagedStateChange?.();
  }, [onManagedStateChange]);

  const preparePlan = useCallback(async (option: McpRegistryInstallOption) => {
    if (!review || !transport.createMcpManagedServer || !userPresenceAvailable) return;
    const retryKey = [
      review.server.catalog_id,
      review.server.version,
      option.option_id,
      review.plan_revision,
    ].join(":");
    let requestId = planRequestIds.current.get(retryKey);
    if (requestId === undefined) {
      const bytes = new Uint8Array(16);
      globalThis.crypto.getRandomValues(bytes);
      requestId = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      planRequestIds.current.set(retryKey, requestId);
    }
    setBusyOption(option.option_id);
    setManagementMessage(null);
    try {
      const receipt = await transport.createMcpManagedServer({
        request_id: requestId,
        catalog_id: review.server.catalog_id,
        name: review.server.name,
        version: review.server.version,
        option_id: option.option_id,
        plan_revision: review.plan_revision,
      });
      planRequestIds.current.delete(retryKey);
      upsertManaged(receipt.server);
      setManagementMessage("Setup plan saved. No package, endpoint, process, or tool was activated.");
    } catch {
      setManagementMessage("The setup plan was not saved. No executable state was changed.");
    } finally {
      setBusyOption(null);
    }
  }, [review, transport.createMcpManagedServer, upsertManaged, userPresenceAvailable]);

  const managedByCatalog = useMemo(() => new Map(
    (managed?.servers ?? []).map((item) => [item.catalog_id, item]),
  ), [managed]);

  const visible = useMemo(() => {
    if (catalog === null) return [];
    const filtered = filter === "local"
      ? catalog.servers.filter((item) => item.supports_local)
      : filter === "remote"
        ? catalog.servers.filter((item) => item.supports_remote)
        : [...catalog.servers];
    if (sort === "registry") return filtered;
    return filtered.sort((left, right) => {
      if (sort === "title") {
        return left.title.localeCompare(right.title, "en", { sensitivity: "base" })
          || left.name.localeCompare(right.name, "en", { sensitivity: "base" });
      }
      if (sort === "updated") {
        const leftTime = left.updated_at === null ? Number.NEGATIVE_INFINITY : Date.parse(left.updated_at);
        const rightTime = right.updated_at === null ? Number.NEGATIVE_INFINITY : Date.parse(right.updated_at);
        return rightTime - leftTime
          || left.title.localeCompare(right.title, "en", { sensitivity: "base" });
      }
      const leftManaged = managedByCatalog.has(left.catalog_id) ? 1 : 0;
      const rightManaged = managedByCatalog.has(right.catalog_id) ? 1 : 0;
      return rightManaged - leftManaged
        || left.title.localeCompare(right.title, "en", { sensitivity: "base" });
    });
  }, [catalog, filter, managedByCatalog, sort]);
  const visiblePage = useBoundedListPage({
    itemCount: visible.length,
    pageSize: CATALOG_RENDER_PAGE_SIZE,
    resetKey: `${appliedSearch}\u0000${filter}\u0000${sort}\u0000${attempt}`,
  });
  const renderedServers = visible.slice(visiblePage.start, visiblePage.end);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = searchDraft.trim().replace(/\s+/gu, " ");
    if (normalized === appliedSearch) {
      setAttempt((value) => value + 1);
      return;
    }
    setAppliedSearch(normalized);
  };

  const selectStoreView = (next: StoreView) => {
    setStoreView(next);
    if (next === "browse") {
      setSelectedManaged(null);
      return;
    }
    closeReview();
  };

  const announcement = selectedServer && reviewState === "loading"
    ? `Loading the safety review for ${selectedServer.title}.`
    : selectedServer && reviewState === "ready"
      ? `Safety review loaded for ${selectedServer.title}. Any supported setup remains review-gated and requires native confirmation.`
      : state === "loading"
    ? "Loading MCP Registry catalog."
    : state === "unavailable"
      ? "The MCP Registry catalog is unavailable. No installation was attempted."
      : `${visible.length} MCP ${visible.length === 1 ? "server" : "servers"} shown. ${catalog?.source.delivery === "cached" ? "Cached metadata is in use." : "Live registry metadata is in use."}`;

  return (
    <section aria-labelledby="agent-mcp-store-title" className="agent-mcp-store" data-view={storeView}>
      <header className="agent-mcp-store__head">
        <span>
          <small>Official Registry · reviewed local management</small>
          <h3 id="agent-mcp-store-title">MCP Store</h3>
        </span>
        {catalog && <span data-delivery={catalog.source.delivery}>{catalog.source.delivery === "live" ? "Live" : "Cached"}</span>}
      </header>
      <p className="agent-mcp-store__summary">
        Discover servers or manage reviewed plans without leaving the Agent. Browsing never installs, connects, starts a process, or grants a tool permission.
      </p>
      <details className="agent-mcp-store__boundary">
        <summary>How review, installation and tool authority work</summary>
        <p>
          Reviewed remote plans can run a closed compatibility check and save an exact native-confirmed activation. Exact checksum-pinned MCPB stdio packages can be installed only after review. An admitted project host starts only on explicit confirmation for the current app run, and every routed tool call requires its own fresh native confirmation.
        </p>
        <p>Registry presence is discovery metadata—not a security verdict or permission to execute.</p>
      </details>
      {managementMessage && <p className="agent-mcp-managed__message" role="status">{managementMessage}</p>}
      <p aria-atomic="true" aria-live="polite" className="sr-only" role="status">{announcement}</p>
      <TabList
        className="agent-mcp-store__tabs"
        idPrefix="agent-mcp-store-view"
        label="MCP Store views"
        onChange={selectStoreView}
        tabs={MCP_STORE_VIEWS}
        value={storeView}
      />
      <div className="agent-mcp-store__workspace">
        {storeView === "browse" && (
          <div
            aria-labelledby={tabId("agent-mcp-store-view", "browse")}
            className="agent-mcp-store__panel"
            id={tabPanelId("agent-mcp-store-view", "browse")}
            role="tabpanel"
          >
            {selectedServer ? (
              <McpServerReviewView
                failure={reviewFailure}
                busyOption={busyOption}
                canPrepare={managedState === "ready" && transport.createMcpManagedServer !== undefined && userPresenceAvailable}
                managedServers={managed?.servers ?? []}
                onBack={closeReview}
                onOpenManaged={(server) => {
                  setStoreView("managed");
                  setSelectedManaged(server);
                }}
                onPrepare={(option) => void preparePlan(option)}
                onRetry={() => {
                  if (reviewFailure === "source_conflict" || reviewFailure === "invalid_contract") {
                    closeReview();
                    setAttempt((value) => value + 1);
                  } else {
                    openReview(selectedServer);
                  }
                }}
                review={review}
                server={selectedServer}
                state={reviewState}
              />
            ) : (
              <>
                <div className="agent-mcp-store__toolbar">
                  <form className="agent-mcp-store__search" onSubmit={submitSearch} role="search">
                    <label htmlFor="agent-mcp-store-search">Search MCP servers</label>
                    <div>
                      <input
                        autoComplete="off"
                        id="agent-mcp-store-search"
                        maxLength={100}
                        onChange={(event) => setSearchDraft(event.target.value)}
                        placeholder="Files, browser, database…"
                        type="search"
                        value={searchDraft}
                      />
                      <button className="button button--ghost" type="submit">Search</button>
                    </div>
                  </form>
                  <fieldset className="agent-mcp-store__filters">
                    <legend>Distribution</legend>
                    {(["all", "local", "remote"] as const).map((value) => (
                      <label key={value}>
                        <input
                          checked={filter === value}
                          name="mcp-store-distribution"
                          onChange={() => setFilter(value)}
                          type="radio"
                          value={value}
                        />
                        <span>{value === "all" ? "All" : value === "local" ? "Local packages" : "Remote servers"}</span>
                      </label>
                    ))}
                  </fieldset>
                  <label className="agent-mcp-store__sort" htmlFor="agent-mcp-store-sort">
                    <span>Sort loaded results</span>
                    <select
                      id="agent-mcp-store-sort"
                      onChange={(event) => setSort(event.target.value as CatalogSort)}
                      value={sort}
                    >
                      <option value="registry">Registry order</option>
                      <option value="title">Name A–Z</option>
                      <option value="updated">Recently updated</option>
                      <option value="managed">Managed first</option>
                    </select>
                  </label>
                </div>
                {state === "loading" && (
                  <div aria-busy="true" className="agent-mcp-store__loading" role="status">
                    <p>Loading the official MCP Registry…</p>
                    <McpCatalogSkeleton />
                  </div>
                )}
                {state === "unavailable" && (
                  <div className="agent-mcp-store__state" role="status">
                    <p>{storeFailureMessage(failure ?? "request_failed")}</p>
                    {transport.listMcpRegistryCatalog && (
                      <button className="button button--ghost" onClick={() => setAttempt((value) => value + 1)} type="button">Retry catalog</button>
                    )}
                  </div>
                )}
                {state === "ready" && catalog && (
                  <>
                    <div className="agent-mcp-store__result-meta">
                      <span>{visible.length} shown · {catalog.servers.length} loaded</span>
                      {catalog.search && <span>Search: “{catalog.search}”</span>}
                      {sort !== "registry" && <span>Sorted loaded results only</span>}
                      {catalog.partial && <span>Some malformed or excess entries were omitted</span>}
                      {catalog.source.delivery === "cached" && <span>Offline fallback · {catalog.source.cache_age_seconds}s old · exact review may need the Registry</span>}
                    </div>
                    {visible.length > 0 ? (
                      <>
                        <div className="agent-mcp-store__grid">
                          {renderedServers.map((server) => (
                            <McpServerCard
                              key={server.catalog_id}
                              managed={managedByCatalog.get(server.catalog_id) ?? null}
                              onReview={openReview}
                              reviewAvailable={transport.getMcpRegistryServerReview !== undefined}
                              server={server}
                            />
                          ))}
                        </div>
                        <BoundedListPager label="Loaded MCP server pages" page={visiblePage} />
                      </>
                    ) : catalog.servers.length === 0 ? (
                      <div className="agent-mcp-store__state">
                        <strong>{appliedSearch ? `No Registry servers matched “${appliedSearch}”.` : "The Registry returned no servers for this page."}</strong>
                        <p>{appliedSearch ? "Try a broader server name, publisher or capability." : "Retry the catalog in case the Registry page changed."}</p>
                        <button
                          className="button button--ghost"
                          onClick={() => {
                            if (appliedSearch) {
                              setSearchDraft("");
                              setAppliedSearch("");
                            } else setAttempt((value) => value + 1);
                          }}
                          type="button"
                        >
                          {appliedSearch ? "Clear search" : "Retry catalog"}
                        </button>
                      </div>
                    ) : (
                      <div className="agent-mcp-store__state">
                        <strong>No loaded servers match this distribution filter.</strong>
                        <p>Other catalog pages may still contain matches. Show all loaded results or continue loading pages.</p>
                        <button className="button button--ghost" onClick={() => setFilter("all")} type="button">Show all distributions</button>
                      </div>
                    )}
                    {paginationFailure && failedCursor && (
                      <div className="agent-mcp-store__state agent-mcp-store__page-error" role="status">
                        <strong>The next Registry page could not be loaded.</strong>
                        <p>{storeFailureMessage(paginationFailure)} Existing results were kept and no lifecycle action was attempted.</p>
                        <button
                          className="button button--ghost"
                          onClick={() => {
                            if (paginationCanRetry(paginationFailure)) {
                              load(appliedSearch, failedCursor);
                            } else {
                              setAttempt((value) => value + 1);
                            }
                          }}
                          type="button"
                        >
                          {paginationCanRetry(paginationFailure) ? "Retry next page" : "Restart catalog"}
                        </button>
                      </div>
                    )}
                    {catalog.next_cursor && !paginationFailure && (
                      <button
                        className="button button--ghost agent-mcp-store__more"
                        disabled={loadingMore}
                        onClick={() => load(appliedSearch, catalog.next_cursor ?? undefined)}
                        type="button"
                      >
                        {loadingMore ? "Loading…" : "Load more"}
                      </button>
                    )}
                  </>
                )}
                <p className="agent-mcp-store__source">
                  Metadata source: <a href="https://registry.modelcontextprotocol.io" rel="noreferrer noopener" target="_blank">Official MCP Registry</a>.
                  Registry presence is not a security verdict.
                </p>
              </>
            )}
          </div>
        )}
        {storeView === "managed" && (
          <div
            aria-labelledby={tabId("agent-mcp-store-view", "managed")}
            className="agent-mcp-store__panel"
            id={tabPanelId("agent-mcp-store-view", "managed")}
            role="tabpanel"
          >
            {selectedManaged && managed ? (
              <AgentMcpManagedPlanView
                acceptanceRun={acceptanceRun}
                activeEventHead={activeEventHead}
                activeSessionId={activeSessionId}
                onBack={() => setSelectedManaged(null)}
                onAcceptanceEvidence={onAcceptanceEvidence}
                onAcceptanceRunChange={onAcceptanceRunChange}
                onRuntimeChange={onManagedStateChange}
                onServer={upsertManaged}
                preferredProjectId={activeProjectId}
                secretVault={managed.secret_vault}
                server={selectedManaged}
                transport={transport}
                userPresenceAvailable={userPresenceAvailable}
              />
            ) : (
              <section className="agent-mcp-store__managed-summary" aria-labelledby="agent-mcp-store-managed-title">
                <header>
                  <span>
                    <h4 id="agent-mcp-store-managed-title">Managed MCP servers</h4>
                    <small>Prepared plans and exact lifecycle state; nothing starts automatically</small>
                  </span>
                  <b aria-label={`${managed?.total ?? 0} managed servers`}>{managed?.total ?? 0}</b>
                </header>
                {managedState === "loading" && <p>Loading managed servers…</p>}
                {managedState === "unavailable" && (
                  <div className="agent-mcp-store__managed-empty" role="status">
                    <p>Managed lifecycle state could not be loaded. Catalog browsing remains read-only and no plan was changed.</p>
                    {transport.listMcpManagedServers && (
                      <button className="button button--ghost" onClick={loadManaged} type="button">Retry managed servers</button>
                    )}
                  </div>
                )}
                {managedState === "ready" && managed?.servers.length === 0 && (
                  <div className="agent-mcp-store__managed-empty">
                    <p>No setup plan has been saved yet. Review a server option to prepare one.</p>
                    <button className="button button--ghost" onClick={() => selectStoreView("browse")} type="button">Browse servers</button>
                  </div>
                )}
                {managedState === "ready" && managed && managed.servers.length > 0 && (
                  <div className="agent-mcp-store__managed-list">
                    {managed.servers.map((item) => (
                      <button
                        aria-label={`Open ${item.server_title} managed plan — ${managedStateLabel(item)}`}
                        data-lifecycle={item.lifecycle_state}
                        key={item.management_id}
                        onClick={() => setSelectedManaged(item)}
                        type="button"
                      >
                        <span>
                          <strong>{item.server_title}</strong>
                          <small>{item.option_label} · {item.server_version} · {managedEvidenceLabel(item)}</small>
                        </span>
                        <span className="agent-mcp-store__managed-state">
                          <strong>{managedStateLabel(item)}</strong>
                          <small>{item.project_bindings.filter((binding) => binding.enabled).length} {item.project_bindings.filter((binding) => binding.enabled).length === 1 ? "project" : "projects"}</small>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
