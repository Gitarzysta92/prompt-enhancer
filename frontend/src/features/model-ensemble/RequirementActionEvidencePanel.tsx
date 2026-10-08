import { useEffect, useMemo, useRef, useState } from "react";
import type {
  PromptEnhancerTransport,
  ModelRequirementActionEvidenceBinding,
  RequirementActionDecisionRequest,
  RequirementActionEvidenceContract,
  RequirementActionEvidencePreview,
  RequirementActionProposal,
  RequirementActionProposalReview,
  UserPresenceCapability,
} from "../../shared/api/contracts";
import {
  MAX_REQUIREMENT_ACTION_FILE_BYTES,
  REQUIREMENT_ACTION_DECISION_CONFIRMATION,
  REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
  REQUIREMENT_ACTION_MEDIA_TYPE,
  REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
  requirementActionProposalMatchesContract,
} from "../../shared/api/requirementActionEvidenceContract";
import "./MetricEvidenceFilePanel.css";
import "./RequirementActionEvidencePanel.css";

type RequirementActionTransport = Pick<PromptEnhancerTransport,
  | "getRequirementActionEvidenceContract"
  | "previewRequirementActionEvidence"
  | "importRequirementActionEvidence"
  | "listRequirementActionProposals"
  | "reviewRequirementActionProposal"
  | "decideRequirementActionProposal">
  & Partial<Pick<PromptEnhancerTransport, "getUserPresenceCapability">>;

type AuthorityOwner = {
  binding: string;
  transport: RequirementActionTransport;
};

type PendingDecision = {
  owner: AuthorityOwner;
  proposalId: string;
  decision: "confirm" | "reject";
};

type Operation = {
  controller: AbortController;
  owner: AuthorityOwner;
};

const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_CODE = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const FORBIDDEN_VISIBLE_TEXT = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069]/;

function sameOwner(left: AuthorityOwner | null, right: AuthorityOwner): boolean {
  return left !== null && left.binding === right.binding && left.transport === right.transport;
}

function sameValue(left: unknown, right: unknown): boolean {
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

function safeVisibleText(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= maxLength
    && !FORBIDDEN_VISIBLE_TEXT.test(value);
}

function idempotency(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "")}`;
}

function exactContractBinding(
  contract: RequirementActionEvidenceContract,
  sessionId: string,
  sourceRunId: string,
  sourceProjectionVersion: RequirementActionEvidenceContract["source_projection_version"],
): boolean {
  return contract.session_id === sessionId
    && contract.expected_source_run_id === sourceRunId
    && contract.source_projection_version === sourceProjectionVersion
    && contract.candidate_manifest.session_id === sessionId
    && contract.candidate_manifest.source_run_id === sourceRunId
    && contract.candidate_manifest.source_window_fingerprint === contract.source_window_fingerprint
    && contract.candidate_manifest.extraction_complete === true
    && contract.candidate_manifest.enumeration_complete === true
    && contract.candidate_manifest.provenance.extraction_complete === true
    && contract.requirements.every((requirement, index) => requirement.requirement_index === index)
    && contract.candidate_manifest.actions.every((candidate, index) => candidate.candidate_index === index);
}

function publicBindingInputCurrent(
  binding: ModelRequirementActionEvidenceBinding | undefined,
  source: ModelRequirementActionEvidenceBinding["evidence_source"],
  sourceRunId: string,
): boolean {
  if (binding === undefined) return true;
  const expectedSchema: Record<
    ModelRequirementActionEvidenceBinding["evidence_source"],
    ModelRequirementActionEvidenceBinding["evidence_schema_version"]
  > = {
    unavailable: "requirement-action-unavailable-v1",
    awaiting_review: "requirement-action-awaiting-review-v1",
    candidate_manifest_overflow: "requirement-action-candidate-manifest-overflow-v1",
    candidate_source_incomplete: "requirement-action-candidate-source-incomplete-v1",
    binding_invalid: "requirement-action-binding-invalid-v1",
    reviewed_requirement_action: "requirement-action-evidence-v1",
  };
  return binding.evidence_source === source
    && binding.evidence_schema_version === expectedSchema[source]
    && binding.evidence_policy_version === "reviewed-requirement-action-v1"
    && binding.local_only === true
    && binding.content_persisted === false
    && HEX_64.test(binding.evidence_fingerprint)
    && (binding.source_run_id === null || binding.source_run_id === sourceRunId)
    && (source !== "reviewed_requirement_action" || (
      binding.source_run_id === sourceRunId
      && binding.requirement_plan_confirmation_id !== null
      && HEX_64.test(binding.requirement_plan_confirmation_id)
      && binding.requirement_plan_evidence_fingerprint !== null
      && HEX_64.test(binding.requirement_plan_evidence_fingerprint)
      && binding.candidate_manifest_fingerprint !== null
      && HEX_64.test(binding.candidate_manifest_fingerprint)
      && binding.confirmation_id !== null
      && HEX_64.test(binding.confirmation_id)
      && binding.proposal_id !== null
      && HEX_64.test(binding.proposal_id)
      && binding.reviewed_descriptor_set_fingerprint !== null
      && HEX_64.test(binding.reviewed_descriptor_set_fingerprint)
    ));
}

function publicBindingMatchesContract(
  binding: ModelRequirementActionEvidenceBinding | undefined,
  contract: RequirementActionEvidenceContract,
): boolean {
  return binding === undefined || (
    (binding.source_run_id === null || binding.source_run_id === contract.expected_source_run_id)
    && (binding.requirement_plan_confirmation_id === null
      || binding.requirement_plan_confirmation_id === contract.requirement_plan_confirmation_id)
    && (binding.requirement_plan_evidence_fingerprint === null
      || binding.requirement_plan_evidence_fingerprint === contract.requirement_plan_evidence_fingerprint)
    && (binding.candidate_manifest_fingerprint === null
      || binding.candidate_manifest_fingerprint === contract.candidate_manifest.manifest_fingerprint)
  );
}

function proposalCurrent(
  proposal: RequirementActionProposal,
  contract: RequirementActionEvidenceContract,
): boolean {
  const candidateIds = new Set(proposal.candidates.map((candidate) => candidate.action_id));
  return requirementActionProposalMatchesContract(proposal, contract)
    && proposal.links.length === proposal.requirements.length
    && proposal.links.every((link, index) => (
      link.requirement_id === proposal.requirements[index].requirement_id
      && new Set(link.action_ids).size === link.action_ids.length
      && link.action_ids.every((actionId) => candidateIds.has(actionId))
    ));
}

function reviewCurrent(
  review: RequirementActionProposalReview,
  proposal: RequirementActionProposal,
  contract: RequirementActionEvidenceContract,
): boolean {
  const expiry = Math.min(
    Date.parse(review.review_context_expires_at),
    Date.parse(review.review_receipt_expires_at),
  );
  if (
    !proposalCurrent(proposal, contract)
    || proposal.status !== "proposed"
    || review.proposal_id !== proposal.proposal_id
    || review.session_id !== proposal.session_id
    || review.source_run_id !== proposal.source_run_id
    || review.source_window_fingerprint !== proposal.source_window_fingerprint
    || review.payload_sha256 !== proposal.payload_sha256
    || review.requirement_plan_evidence_fingerprint !== proposal.requirement_plan_evidence_fingerprint
    || review.candidate_manifest_fingerprint !== proposal.candidate_manifest_fingerprint
    || !HEX_64.test(review.review_receipt_id)
    || !HEX_64.test(review.reviewed_graph_fingerprint)
    || !HEX_64.test(review.reviewed_candidate_set_fingerprint)
    || !HEX_64.test(review.reviewed_descriptor_set_fingerprint)
    || review.review_visible_display_algorithm_version !== contract.review_visible_display_algorithm_version
    || review.all_requirements_and_candidates_displayed !== true
    || review.raw_text_persisted !== false
    || review.local_only !== true
    || !Number.isFinite(expiry)
    || expiry <= Date.now()
    || !sameValue(review.candidates, proposal.candidates)
    || review.requirements.length !== proposal.requirements.length
    || review.candidate_memberships.length !== proposal.candidates.length
  ) return false;

  const expectedMemberships = new Map(
    proposal.candidates.map((candidate) => [candidate.action_id, [] as string[]]),
  );
  for (const link of proposal.links) {
    for (const actionId of link.action_ids) expectedMemberships.get(actionId)?.push(link.requirement_id);
  }
  const requirementsCurrent = review.requirements.every((requirement, index) => {
    const expectedRequirement = proposal.requirements[index];
    const expectedLink = proposal.links[index];
    return requirement.requirement_id === expectedRequirement.requirement_id
      && sameValue(requirement.coordinate, expectedRequirement.coordinate)
      && safeVisibleText(requirement.text, 32_000)
      && sameValue(requirement.linked_action_ids, expectedLink.action_ids);
  });
  const membershipsCurrent = review.candidate_memberships.every((membership, index) => {
    const expectedCandidate = proposal.candidates[index];
    return sameValue(membership.candidate, expectedCandidate)
      && membership.candidate_metadata_fingerprint_version === contract.candidate_metadata_fingerprint_version
      && HEX_64.test(membership.candidate_metadata_fingerprint)
      && membership.descriptor_algorithm_version === contract.action_descriptor_algorithm_version
      && safeVisibleText(membership.tool_name, 120)
      && safeVisibleText(membership.invocation_preview, 4_096)
      && (membership.result_or_effect_preview === null
        ? expectedCandidate.event_kind === "tool_start"
        : safeVisibleText(membership.result_or_effect_preview, 4_096))
      && membership.invocation_truncated === false
      && membership.result_or_effect_truncated === false
      && SAFE_CODE.test(membership.redactor_version)
      && sameValue(membership.linked_requirement_ids, expectedMemberships.get(expectedCandidate.action_id));
  });
  return requirementsCurrent && membershipsCurrent;
}

function proposalSummary(proposal: RequirementActionProposal): string {
  const linked = proposal.links.filter((link) => link.action_ids.length > 0).length;
  const empty = proposal.links.length - linked;
  const links = proposal.links.reduce((sum, link) => sum + link.action_ids.length, 0);
  return `${proposal.requirements.length} requirements · ${proposal.candidates.length} action candidates · ${linked} linked · ${empty} explicit empty · ${links} memberships`;
}

function humanCode(value: string): string {
  return value.replaceAll("_", " ");
}

function durationLabel(value: number | null): string {
  return value === null ? "duration unknown" : `${value} ms`;
}

function presenceCurrent(value: UserPresenceCapability | null): boolean {
  return value === null || (
    value.contract_version === "native-user-presence-capability-v1"
    && value.confirmation_available === (value.mode === "native_bridge_bound_token")
  );
}

function previewCurrent(
  preview: RequirementActionEvidencePreview,
  contract: RequirementActionEvidenceContract,
): boolean {
  return preview.session_id === contract.session_id
    && preview.expected_source_run_id === contract.expected_source_run_id
    && preview.source_window_fingerprint === contract.source_window_fingerprint
    && preview.requirement_plan_confirmation_id === contract.requirement_plan_confirmation_id
    && preview.requirement_plan_evidence_fingerprint === contract.requirement_plan_evidence_fingerprint
    && preview.candidate_manifest_fingerprint === contract.candidate_manifest.manifest_fingerprint
    && preview.expected_predecessor_confirmation_id === contract.expected_predecessor_confirmation_id
    && preview.requirement_count === contract.requirements.length
    && preview.candidate_count === contract.candidate_manifest.actions.length
    && preview.requirement_count === preview.linked_requirement_count + preview.unlinked_requirement_count
    && preview.linked_requirement_count <= preview.link_count
    && preview.link_count <= contract.max_link_count
    && HEX_64.test(preview.payload_sha256)
    && Number.isFinite(Date.parse(preview.expires_at))
    && Date.parse(preview.expires_at) > Date.now()
    && preview.creates_unconfirmed_proposal_only === true
    && preview.native_confirmation_required_for_metric_authority === true
    && preview.can_set_numeric_metric_on_import === false
    && preview.raw_payload_persisted === false
    && preview.raw_producer_claim_persisted === false;
}

function decisionOutcomeCurrent(
  result: { proposal: RequirementActionProposal; applied: boolean },
  proposal: RequirementActionProposal,
  decision: "confirm" | "reject",
): boolean {
  const decided = result.proposal;
  return typeof result.applied === "boolean"
    && decided.proposal_id === proposal.proposal_id
    && decided.session_id === proposal.session_id
    && decided.source_run_id === proposal.source_run_id
    && decided.source_window_fingerprint === proposal.source_window_fingerprint
    && decided.payload_sha256 === proposal.payload_sha256
    && decided.requirement_plan_confirmation_id === proposal.requirement_plan_confirmation_id
    && decided.requirement_plan_evidence_fingerprint === proposal.requirement_plan_evidence_fingerprint
    && decided.candidate_manifest_fingerprint === proposal.candidate_manifest_fingerprint
    && decided.expected_predecessor_confirmation_id === proposal.expected_predecessor_confirmation_id
    && sameValue(decided.candidate_provenance, proposal.candidate_provenance)
    && sameValue(decided.requirements, proposal.requirements)
    && sameValue(decided.candidates, proposal.candidates)
    && sameValue(decided.links, proposal.links)
    && decided.status === (decision === "confirm" ? "confirmed" : "rejected")
    && decided.decision === decision
    && decided.confirmation_authority === "owned_native_user_presence"
    && decided.decision_id !== null
    && HEX_64.test(decided.decision_id)
    && decided.decided_at !== null
    && Number.isFinite(Date.parse(decided.decided_at));
}

function publicEvidenceStateLabel(
  source: ModelRequirementActionEvidenceBinding["evidence_source"],
): string {
  switch (source) {
    case "reviewed_requirement_action":
      return "Public projection state: confirmed reviewed requirement-to-action binding.";
    case "awaiting_review":
      return "Public projection state: awaiting an owned native review and decision.";
    case "binding_invalid":
      return "Public projection state: prior binding invalid; only an exact current recovery can replace it.";
    case "candidate_manifest_overflow":
      return "Public projection state: unavailable because the bounded action-candidate manifest overflowed.";
    case "candidate_source_incomplete":
      return "Public projection state: unavailable because safe action-candidate extraction is incomplete.";
    case "unavailable":
      return "Public projection state: reviewed requirement-to-action evidence is unavailable.";
  }
}

function publicBindingIdentity(binding: ModelRequirementActionEvidenceBinding): string {
  return JSON.stringify([
    binding.evidence_source,
    binding.source_run_id,
    binding.requirement_plan_confirmation_id,
    binding.requirement_plan_evidence_fingerprint,
    binding.candidate_manifest_fingerprint,
    binding.confirmation_id,
    binding.proposal_id,
    binding.reviewed_descriptor_set_fingerprint,
    binding.evidence_fingerprint,
    binding.evidence_schema_version,
    binding.evidence_policy_version,
    binding.local_only,
    binding.content_persisted,
  ]);
}

export function RequirementActionEvidencePanel({
  compact,
  sessionId,
  sourceRunId,
  sourceProjectionVersion,
  publicEvidenceBinding,
  publicEvidenceSource,
  transport,
  onEvidenceChanged,
}: {
  compact: boolean;
  sessionId: string;
  sourceRunId: string;
  sourceProjectionVersion: RequirementActionEvidenceContract["source_projection_version"];
  /** Strictly parsed public DTO; production supplies it so same-source A→B authority resets are exact. */
  publicEvidenceBinding?: ModelRequirementActionEvidenceBinding;
  publicEvidenceSource: ModelRequirementActionEvidenceBinding["evidence_source"];
  transport: RequirementActionTransport;
  onEvidenceChanged?: () => void;
}) {
  const [contract, setContract] = useState<RequirementActionEvidenceContract | null>(null);
  const [proposals, setProposals] = useState<RequirementActionProposal[]>([]);
  const [preview, setPreview] = useState<RequirementActionEvidencePreview | null>(null);
  const [payload, setPayload] = useState<ArrayBuffer | null>(null);
  const [confirmationAvailable, setConfirmationAvailable] = useState(false);
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [review, setReview] = useState<RequirementActionProposalReview | null>(null);
  const [allItemsAcknowledged, setAllItemsAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const sourceProjectionLabel = sourceProjectionVersion.replace(
    "metric-contract-v2-projection-",
    "r",
  );
  const operationRef = useRef<AbortController | null>(null);
  const reviewRegionRef = useRef<HTMLElement | null>(null);
  const reviewInitiatorRef = useRef<HTMLButtonElement | null>(null);
  const decisionActionRef = useRef<HTMLButtonElement | null>(null);
  const decisionInitiatorRef = useRef<HTMLButtonElement | null>(null);
  const resolvedPublicEvidenceSource = publicEvidenceBinding?.evidence_source ?? publicEvidenceSource;
  const selectedBinding = JSON.stringify([
    sessionId,
    sourceRunId,
    sourceProjectionVersion,
    publicEvidenceSource,
    publicEvidenceBinding === undefined ? null : publicBindingIdentity(publicEvidenceBinding),
  ]);
  const currentOwner: AuthorityOwner = { binding: selectedBinding, transport };
  const ownerRef = useRef<AuthorityOwner>(currentOwner);
  const [loadedOwner, setLoadedOwner] = useState<AuthorityOwner | null>(null);
  ownerRef.current = currentOwner;
  const bindingInvalid = resolvedPublicEvidenceSource === "binding_invalid";
  const reviewedMetadataBinding = useMemo(() => (
    review === null ? "" : review.candidate_memberships
      .map((membership) => (
        `${membership.candidate.action_id}:${membership.candidate_metadata_fingerprint_version}:${membership.candidate_metadata_fingerprint}`
      )).join("|")
  ), [review]);
  const capabilities = transport.getRequirementActionEvidenceContract !== undefined
    && transport.previewRequirementActionEvidence !== undefined
    && transport.importRequirementActionEvidence !== undefined
    && transport.listRequirementActionProposals !== undefined
    && transport.reviewRequirementActionProposal !== undefined
    && transport.decideRequirementActionProposal !== undefined;

  useEffect(() => {
    operationRef.current?.abort();
    const owner: AuthorityOwner = { binding: selectedBinding, transport };
    setLoadedOwner(owner);
    setContract(null);
    setProposals([]);
    setPreview(null);
    setPayload(null);
    setPendingDecision(null);
    setReview(null);
    setAllItemsAcknowledged(false);
    setConfirmationAvailable(false);
    setBusy(false);
    setError("");
    setCopyStatus("");
    setLoadFailed(false);
    if (!capabilities) return;
    if (!publicBindingInputCurrent(publicEvidenceBinding, publicEvidenceSource, sourceRunId)) {
      setError("The public requirement-action source marker and binding do not describe this exact selected run.");
      return;
    }
    const controller = new AbortController();
    operationRef.current = controller;
    Promise.all([
      transport.getRequirementActionEvidenceContract!(sessionId, controller.signal),
      transport.listRequirementActionProposals!(sessionId, controller.signal),
      transport.getUserPresenceCapability === undefined
        ? Promise.resolve(null)
        // A rejected presence probe means the native capability is unknown. Unknown is caught to
        // null so the inert preview/import workflow stays available, while presenceCurrent(null)
        // and every approval/review gate keep decisions fail-closed (approvals are never enabled).
        : transport.getUserPresenceCapability(controller.signal).catch(() => null),
    ]).then(([loadedContract, collection, presence]) => {
      if (controller.signal.aborted || !sameOwner(owner, ownerRef.current)) return;
      if (
        !exactContractBinding(loadedContract, sessionId, sourceRunId, sourceProjectionVersion)
        || !publicBindingMatchesContract(publicEvidenceBinding, loadedContract)
        || collection.session_id !== sessionId
        || collection.complete !== true
        || collection.total !== collection.proposals.length
        || collection.proposals.some((proposal) => proposal.session_id !== sessionId)
        || !presenceCurrent(presence)
      ) {
        setError(`Requirement-action review is not bound to this exact sealed ${sourceProjectionLabel} run and source window.`);
        // Still strictly fail closed (no contract, no proposals, no approvals), but a resolved
        // wrong verification/list/presence binding is retryable exactly like a rejected load.
        setLoadFailed(true);
        return;
      }
      setContract(loadedContract);
      setProposals(collection.proposals);
      setConfirmationAvailable(presence?.confirmation_available === true);
    }).catch(() => {
      if (!controller.signal.aborted && sameOwner(owner, ownerRef.current)) {
        setError("Reviewed requirement-action evidence is temporarily unavailable.");
        setLoadFailed(true);
      }
    });
    return () => controller.abort();
  }, [capabilities, publicEvidenceBinding, publicEvidenceSource, retryToken, selectedBinding, sessionId, sourceProjectionVersion, sourceRunId, transport]);

  useEffect(() => {
    if (review === null) return;
    const owner = loadedOwner;
    if (!sameOwner(owner, ownerRef.current)) return;
    const expiresIn = Math.min(
      Date.parse(review.review_context_expires_at),
      Date.parse(review.review_receipt_expires_at),
    ) - Date.now();
    const expire = () => {
      if (!sameOwner(owner, ownerRef.current)) return;
      setReview(null);
      setAllItemsAcknowledged(false);
      setPendingDecision(null);
      setError("The exact local requirement/action review receipt expired. Open a fresh review before confirming.");
    };
    if (expiresIn <= 0) {
      expire();
      return;
    }
    const timer = window.setTimeout(expire, Math.min(expiresIn, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [loadedOwner, review]);

  useEffect(() => {
    if (preview === null) return;
    const owner = loadedOwner;
    if (!sameOwner(owner, ownerRef.current)) return;
    const expiresIn = Date.parse(preview.expires_at) - Date.now();
    const expire = () => {
      if (!sameOwner(owner, ownerRef.current)) return;
      setPreview(null);
      setPayload(null);
      setError("The exact local file preview expired. Preview the unchanged canonical bytes again before import.");
    };
    if (expiresIn <= 0) {
      expire();
      return;
    }
    const timer = window.setTimeout(expire, Math.min(expiresIn, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [loadedOwner, preview]);

  useEffect(() => {
    setAllItemsAcknowledged(false);
    setPendingDecision(null);
  }, [reviewedMetadataBinding]);

  const contextCurrent = sameOwner(loadedOwner, currentOwner);
  const currentContract = contextCurrent ? contract : null;
  const currentProposals = contextCurrent ? proposals : [];
  const currentPreview = contextCurrent ? preview : null;
  const currentPayload = contextCurrent ? payload : null;
  const currentReview = contextCurrent ? review : null;
  const currentPendingDecision = contextCurrent
    && pendingDecision !== null
    && sameOwner(pendingDecision.owner, currentOwner)
    ? pendingDecision
    : null;
  const currentConfirmationAvailable = contextCurrent && confirmationAvailable;
  const currentBusy = contextCurrent && busy;
  const currentError = contextCurrent ? error : "";
  const currentCopyStatus = contextCurrent ? copyStatus : "";
  const currentLoadFailed = contextCurrent && loadFailed;
  const authorityStateRef = useRef({
    owner: currentOwner,
    contract: currentContract,
    proposals: currentProposals,
    preview: currentPreview,
    payload: currentPayload,
    review: currentReview,
    pendingDecision: currentPendingDecision,
    allItemsAcknowledged: contextCurrent && allItemsAcknowledged,
    confirmationAvailable: currentConfirmationAvailable,
  });
  authorityStateRef.current = {
    owner: currentOwner,
    contract: currentContract,
    proposals: currentProposals,
    preview: currentPreview,
    payload: currentPayload,
    review: currentReview,
    pendingDecision: currentPendingDecision,
    allItemsAcknowledged: contextCurrent && allItemsAcknowledged,
    confirmationAvailable: currentConfirmationAvailable,
  };
  const undecided = useMemo(
    () => currentProposals.filter((proposal) => proposal.status === "proposed"),
    [currentProposals],
  );
  const confirmedCount = currentProposals.filter((proposal) => proposal.status === "confirmed").length;
  const rejectedCount = currentProposals.filter((proposal) => proposal.status === "rejected").length;
  const localAgentMetaprompt = useMemo(() => [
    "Prompt Enhancer local requirement-action proposal workflow (no metric authority)",
    "",
    `1. GET /v1/sessions/${sessionId}/requirement-action-evidence/contract using this app's local authenticated API.`,
    "2. Treat requirements and candidate_manifest.actions as the only authoritative set. Build one canonical JSON file matching file_json_schema exactly and preserve every returned source, r6-plan, candidate-manifest, and predecessor binding.",
    "3. Include every requirement_index exactly once, densely and in order. For each link, choose only action_candidate_indexes already issued by the contract, sorted and unique, or use [] as an explicit empty link. Do not invent or infer another candidate.",
    "4. Treat every proposed membership as a hypothesis. The person must cross-check each source_reference_id against the referenced safe event/session timeline before adopting a semantic link; coarse content-free metadata is not proof of relation or task success.",
    "5. Do not include action state claims, objective proof claims, metric values, commentary/prose, source text, file paths, commands, tool arguments, or tool output. Producer identity is an untrusted preview claim and never metric authority.",
    `6. POST the bytes to /v1/sessions/${sessionId}/requirement-action-evidence/preview with Content-Type: ${REQUIREMENT_ACTION_MEDIA_TYPE}. Inspect the returned counts, digest, expiry, and exact bindings.`,
    `7. Only after the person explicitly chooses import, POST the identical bytes to /v1/sessions/${sessionId}/requirement-action-evidence/import with the vendor Content-Type, a fresh Idempotency-Key, X-Requirement-Action-Payload-SHA256 from preview, and X-Requirement-Action-Confirmation: ${REQUIREMENT_ACTION_IMPORT_CONFIRMATION}.`,
    "8. Stop after import. The proposal is inert. Never call review or decision endpoints on the person's behalf; only the app's owned native window may display every item and establish authority.",
  ].join("\n"), [sessionId]);

  useEffect(() => {
    if (currentPendingDecision !== null) decisionActionRef.current?.focus();
  }, [currentPendingDecision]);

  useEffect(() => {
    if (currentReview !== null) reviewRegionRef.current?.focus();
  }, [currentReview]);

  function beginOperation(owner: AuthorityOwner): Operation | null {
    if (!sameOwner(owner, ownerRef.current)) return null;
    operationRef.current?.abort();
    const controller = new AbortController();
    operationRef.current = controller;
    return { controller, owner };
  }

  function stillCurrent(operation: Operation): boolean {
    return !operation.controller.signal.aborted && sameOwner(operation.owner, ownerRef.current);
  }

  /** Explicit person-initiated reload only: aborts the scoped operation and re-runs the exact owner-scoped load. */
  function retryLoad(owner: AuthorityOwner): void {
    if (!sameOwner(owner, ownerRef.current)) return;
    operationRef.current?.abort();
    setRetryToken((token) => token + 1);
  }

  function clearReview(): void {
    setReview(null);
    setAllItemsAcknowledged(false);
    setPendingDecision(null);
  }

  function exactLiveSurface(
    owner: AuthorityOwner,
    selectedContract: RequirementActionEvidenceContract,
  ): boolean {
    const state = authorityStateRef.current;
    return sameOwner(owner, state.owner) && state.contract === selectedContract;
  }

  function exactLiveProposal(proposal: RequirementActionProposal): boolean {
    const live = authorityStateRef.current.proposals.find((item) => item.proposal_id === proposal.proposal_id);
    return live !== undefined && live.status === "proposed" && sameValue(live, proposal);
  }

  async function copyLocalAgentWorkflow(owner: AuthorityOwner, workflow: string): Promise<void> {
    if (!sameOwner(owner, ownerRef.current)) return;
    try {
      await navigator.clipboard.writeText(workflow);
      if (!sameOwner(owner, ownerRef.current)) return;
      setCopyStatus("Local-agent workflow copied. It grants proposal creation only, never metric authority.");
    } catch {
      if (!sameOwner(owner, ownerRef.current)) return;
      setCopyStatus("Copy was unavailable. Select the workflow text manually.");
    }
  }

  async function chooseFile(
    owner: AuthorityOwner,
    selectedContract: RequirementActionEvidenceContract,
    file: File | undefined,
  ) {
    if (!sameOwner(owner, ownerRef.current) || !exactLiveSurface(owner, selectedContract)) return;
    setPreview(null);
    setPayload(null);
    clearReview();
    setError("");
    if (file === undefined || owner.transport.previewRequirementActionEvidence === undefined) return;
    if (!["", "application/json", REQUIREMENT_ACTION_MEDIA_TYPE].includes(file.type)) {
      setError("Choose one canonical JSON requirement-action evidence file with the supported local media type.");
      return;
    }
    if (file.size < 1 || file.size > MAX_REQUIREMENT_ACTION_FILE_BYTES) {
      setError("Choose one canonical requirement-action file no larger than 64 KiB.");
      return;
    }
    const operation = beginOperation(owner);
    if (operation === null) return;
    setBusy(true);
    try {
      const bytes = await file.arrayBuffer();
      if (!stillCurrent(operation)) return;
      if (bytes.byteLength !== file.size || bytes.byteLength < 1 || bytes.byteLength > MAX_REQUIREMENT_ACTION_FILE_BYTES) {
        setError("The selected file changed while it was read; no preview authority was created.");
        return;
      }
      const result = await owner.transport.previewRequirementActionEvidence(
        selectedContract.session_id,
        bytes,
        operation.controller.signal,
      );
      if (!stillCurrent(operation)) return;
      if (!previewCurrent(result, selectedContract)) {
        setError("The file preview is expired or bound to another sealed source, plan, candidate set, or predecessor.");
        return;
      }
      setPayload(bytes);
      setPreview(result);
    } catch {
      if (stillCurrent(operation)) {
        setError("The file failed strict local validation; no proposal was imported.");
      }
    } finally {
      if (stillCurrent(operation)) setBusy(false);
    }
  }

  async function importPreview(
    owner: AuthorityOwner,
    selectedContract: RequirementActionEvidenceContract,
    selectedPreview: RequirementActionEvidencePreview,
    selectedPayload: ArrayBuffer,
  ) {
    const liveState = authorityStateRef.current;
    if (
      !sameOwner(owner, ownerRef.current)
      || !exactLiveSurface(owner, selectedContract)
      || liveState.preview !== selectedPreview
      || liveState.payload !== selectedPayload
      || owner.transport.importRequirementActionEvidence === undefined
    ) return;
    if (!previewCurrent(selectedPreview, selectedContract)) {
      setPreview(null);
      setPayload(null);
      setError("The exact local file preview expired. Preview the unchanged canonical bytes again before import.");
      return;
    }
    if (selectedPayload.byteLength < 1 || selectedPayload.byteLength > MAX_REQUIREMENT_ACTION_FILE_BYTES) return;
    const operation = beginOperation(owner);
    if (operation === null) return;
    setBusy(true);
    setError("");
    clearReview();
    try {
      const result = await owner.transport.importRequirementActionEvidence(
        selectedContract.session_id,
        selectedPayload,
        selectedPreview,
        REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
        idempotency("requirement-action-import"),
        operation.controller.signal,
      );
      if (!stillCurrent(operation)) return;
      if (
        result.payload_sha256 !== selectedPreview.payload_sha256
        || result.proposal.payload_sha256 !== selectedPreview.payload_sha256
        || !proposalCurrent(result.proposal, selectedContract)
        || result.proposal.status !== "proposed"
        || result.creates_unconfirmed_proposal_only !== true
        || result.native_confirmation_required_for_metric_authority !== true
        || result.raw_payload_persisted !== false
        || result.raw_producer_claim_persisted !== false
      ) {
        setError("The imported proposal did not preserve the exact preview authority.");
        return;
      }
      setProposals((current) => [
        result.proposal,
        ...current.filter((item) => item.proposal_id !== result.proposal.proposal_id),
      ]);
      setPreview(null);
      setPayload(null);
    } catch {
      if (stillCurrent(operation)) {
        setError("The preview binding changed or the proposal could not be imported.");
      }
    } finally {
      if (stillCurrent(operation)) setBusy(false);
    }
  }

  async function openReview(
    owner: AuthorityOwner,
    selectedContract: RequirementActionEvidenceContract,
    proposal: RequirementActionProposal,
    initiator: HTMLButtonElement,
  ) {
    if (
      !sameOwner(owner, ownerRef.current) || !exactLiveSurface(owner, selectedContract)
      || !authorityStateRef.current.confirmationAvailable
      || owner.transport.reviewRequirementActionProposal === undefined
      || !proposalCurrent(proposal, selectedContract)
      || !exactLiveProposal(proposal)
      || proposal.status !== "proposed"
    ) return;
    const operation = beginOperation(owner);
    if (operation === null) return;
    reviewInitiatorRef.current = initiator;
    setBusy(true);
    setError("");
    clearReview();
    try {
      const loaded = await owner.transport.reviewRequirementActionProposal(
        selectedContract.session_id,
        proposal,
        selectedContract,
        {
          expected_source_run_id: selectedContract.expected_source_run_id,
          confirmation: REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
        },
        operation.controller.signal,
      );
      if (!stillCurrent(operation)) return;
      if (!reviewCurrent(loaded, proposal, selectedContract)) {
        setError("The complete local requirement/action review is stale or expired; nothing can be confirmed.");
        return;
      }
      setReview(loaded);
    } catch {
      if (stillCurrent(operation)) {
        clearReview();
        setError("The exact local review could not be opened; refresh the sealed run before confirming.");
      }
    } finally {
      if (stillCurrent(operation)) setBusy(false);
    }
  }

  function requestDecision(
    owner: AuthorityOwner,
    selectedContract: RequirementActionEvidenceContract,
    proposal: RequirementActionProposal,
    decision: "confirm" | "reject",
    initiator: HTMLButtonElement,
  ): void {
    const liveState = authorityStateRef.current;
    if (
      !sameOwner(owner, ownerRef.current)
      || !exactLiveSurface(owner, selectedContract)
      || !liveState.confirmationAvailable
      || !exactLiveProposal(proposal)
      || proposal.status !== "proposed"
    ) return;
    if (decision === "confirm" && (
      liveState.review === null
      || !reviewCurrent(liveState.review, proposal, selectedContract)
      || !liveState.allItemsAcknowledged
    )) return;
    decisionInitiatorRef.current = initiator;
    setPendingDecision({ owner, proposalId: proposal.proposal_id, decision });
  }

  function closeDecision(owner: AuthorityOwner, expected: PendingDecision): void {
    if (
      !sameOwner(owner, ownerRef.current)
      || authorityStateRef.current.pendingDecision !== expected
    ) return;
    setPendingDecision(null);
    queueMicrotask(() => decisionInitiatorRef.current?.focus());
  }

  function closeReview(owner: AuthorityOwner, expected: RequirementActionProposalReview): void {
    if (!sameOwner(owner, ownerRef.current) || authorityStateRef.current.review !== expected) return;
    clearReview();
    queueMicrotask(() => reviewInitiatorRef.current?.focus());
  }

  async function applyDecision(
    owner: AuthorityOwner,
    selectedContract: RequirementActionEvidenceContract,
    proposal: RequirementActionProposal,
    decision: "confirm" | "reject",
  ) {
    const liveState = authorityStateRef.current;
    if (
      !sameOwner(owner, ownerRef.current)
      || !exactLiveSurface(owner, selectedContract)
      || owner.transport.decideRequirementActionProposal === undefined
      || !liveState.confirmationAvailable
      || !exactLiveProposal(proposal)
      || proposal.status !== "proposed"
      || liveState.pendingDecision === null
      || !sameOwner(liveState.pendingDecision.owner, owner)
      || liveState.pendingDecision.proposalId !== proposal.proposal_id
      || liveState.pendingDecision.decision !== decision
    ) return;
    const exactReview = liveState.review !== null && reviewCurrent(liveState.review, proposal, selectedContract)
      ? liveState.review
      : null;
    if (decision === "confirm" && (exactReview === null || !liveState.allItemsAcknowledged || !proposalCurrent(proposal, selectedContract))) return;
    const request: RequirementActionDecisionRequest = decision === "confirm" ? {
      expected_source_run_id: proposal.source_run_id,
      decision: "confirm",
      confirmation: REQUIREMENT_ACTION_DECISION_CONFIRMATION,
      review_receipt_id: exactReview!.review_receipt_id,
      reviewed_graph_fingerprint: exactReview!.reviewed_graph_fingerprint,
      candidate_manifest_fingerprint: exactReview!.candidate_manifest_fingerprint,
      reviewed_candidate_set_fingerprint: exactReview!.reviewed_candidate_set_fingerprint,
      reviewed_descriptor_set_fingerprint: exactReview!.reviewed_descriptor_set_fingerprint,
      complete_review_acknowledged: true,
      all_requirements_and_candidates_acknowledged: true,
      all_linked_action_semantics_reviewed: true,
    } : {
      expected_source_run_id: proposal.source_run_id,
      decision: "reject",
      confirmation: REQUIREMENT_ACTION_DECISION_CONFIRMATION,
    };
    const operation = beginOperation(owner);
    if (operation === null) return;
    setBusy(true);
    setError("");
    try {
      const result = await owner.transport.decideRequirementActionProposal(
        selectedContract.session_id,
        proposal.proposal_id,
        request,
        idempotency(`requirement-action-${decision}`),
        operation.controller.signal,
      );
      if (!stillCurrent(operation)) return;
      if (!decisionOutcomeCurrent(result, proposal, decision)) {
        setError("The native decision receipt did not preserve the exact proposal and reviewed authority.");
        return;
      }
      setProposals((current) => current.map((item) => (
        item.proposal_id === result.proposal.proposal_id ? result.proposal : item
      )));
      if (decision === "confirm") onEvidenceChanged?.();
    } catch {
      if (stillCurrent(operation)) {
        setError(decision === "reject"
          ? "The native rejection could not be recorded. The stale proposal remains inert."
          : "The source, predecessor, candidate set, or one-shot review receipt changed; open a fresh review.");
      }
    } finally {
      if (stillCurrent(operation)) {
        clearReview();
        setBusy(false);
      }
    }
  }

  if (compact) {
    return (
      <section aria-label="Reviewed requirement-to-action evidence" className="metric-evidence-file metric-evidence-file--generic metric-evidence-file--compact requirement-action-evidence">
        <strong>Requirement-to-action evidence</strong>
        <span>{capabilities && currentContract !== null
          ? bindingInvalid
            ? `${undecided.filter((proposal) => proposalCurrent(proposal, currentContract)).length} current recovery proposal${undecided.filter((proposal) => proposalCurrent(proposal, currentContract)).length === 1 ? "" : "s"} · prior binding invalid`
            : `${undecided.length} proposal${undecided.length === 1 ? "" : "s"} awaiting native decision${confirmedCount > 0 ? ` · ${confirmedCount} confirmed` : ""}${rejectedCount > 0 ? ` · ${rejectedCount} rejected` : ""}`
          : `Exact ${sourceProjectionLabel} review unavailable`}</span>
        <small>{publicEvidenceStateLabel(publicEvidenceSource)}</small>
        <small>{currentConfirmationAvailable
          ? "Open the full dashboard to inspect every requirement, content-free action receipt, and proposed membership."
          : "Review is fail-closed: this runtime cannot natively review or decide proposals."}</small>
        {currentError !== "" && <span role="alert">{currentError}</span>}
      </section>
    );
  }

  return (
    <section aria-label="Review requirement-to-action evidence" className="metric-evidence-file metric-evidence-file--generic requirement-action-evidence">
      <header>
        <div>
          <h3>Reviewed requirement-to-action evidence</h3>
          <span>Canonical file → strict preview → inert proposal → complete local review → native decision</span>
        </div>
        <small>This review appears only when the selected provider and sealed window expose complete safe-event plus ephemeral redacted-descriptor authority. It does not imply Codex support or shipped metric operability. Import can propose memberships; it cannot author state, proof, prose, paths, or a metric value.</small>
      </header>
      <p className="requirement-action-evidence__public-state">{publicEvidenceStateLabel(publicEvidenceSource)}</p>
      {!capabilities ? (
        <p className="metric-evidence-file__state" role="status">This local runtime does not expose the complete {sourceProjectionLabel} requirement-action boundary. Preview, import, review, and decisions are unavailable.</p>
      ) : currentContract === null ? (
        <>
          <p className={`metric-evidence-file__state${currentError === "" ? "" : " metric-evidence-file__state--error"}`} role={currentError === "" ? "status" : "alert"}>{currentError === ""
            ? `Loading the exact content-free ${sourceProjectionLabel} contract…`
            : currentError}</p>
          {currentLoadFailed && (
            <button disabled={currentBusy} onClick={() => retryLoad(currentOwner)} type="button">Retry exact source contract</button>
          )}
        </>
      ) : (
        <>
          <p>Bound to sealed run <code className="metric-evidence-file__opaque-id">{sourceRunId}</code>, projection <code>{sourceProjectionVersion}</code>, reviewed r6 requirements, and {currentContract.candidate_manifest.actions.length} application-issued safe action candidate{currentContract.candidate_manifest.actions.length === 1 ? "" : "s"}. Unknown is never rendered as zero.</p>
          {bindingInvalid && (
            <p className="metric-evidence-file__notice">The prior sealed {sourceProjectionLabel} requirement-action binding is invalid, not merely awaiting review. An exact current replacement proposal may be reviewed and confirmed as the recovery path; non-current proposals remain stale and rejection-only.</p>
          )}
          {publicEvidenceBinding !== undefined && (
            <details className="requirement-action-evidence__receipts">
              <summary>Exact public evidence binding receipts</summary>
              <dl>
                <div><dt>Source run</dt><dd>{publicEvidenceBinding.source_run_id === null ? "not recorded" : <code>{publicEvidenceBinding.source_run_id}</code>}</dd></div>
                <div><dt>Requirement-plan confirmation</dt><dd>{publicEvidenceBinding.requirement_plan_confirmation_id === null ? "not recorded" : <code>{publicEvidenceBinding.requirement_plan_confirmation_id}</code>}</dd></div>
                <div><dt>Requirement-plan evidence</dt><dd>{publicEvidenceBinding.requirement_plan_evidence_fingerprint === null ? "not recorded" : <code>{publicEvidenceBinding.requirement_plan_evidence_fingerprint}</code>}</dd></div>
                <div><dt>Candidate manifest</dt><dd>{publicEvidenceBinding.candidate_manifest_fingerprint === null ? "not recorded" : <code>{publicEvidenceBinding.candidate_manifest_fingerprint}</code>}</dd></div>
                <div><dt>Native confirmation</dt><dd>{publicEvidenceBinding.confirmation_id === null ? "not recorded" : <code>{publicEvidenceBinding.confirmation_id}</code>}</dd></div>
                <div><dt>Proposal</dt><dd>{publicEvidenceBinding.proposal_id === null ? "not recorded" : <code>{publicEvidenceBinding.proposal_id}</code>}</dd></div>
                <div><dt>Reviewed descriptor set</dt><dd>{publicEvidenceBinding.reviewed_descriptor_set_fingerprint === null ? "not recorded" : <code>{publicEvidenceBinding.reviewed_descriptor_set_fingerprint}</code>}</dd></div>
                <div><dt>Evidence fingerprint</dt><dd><code>{publicEvidenceBinding.evidence_fingerprint}</code></dd></div>
                <div><dt>Schema / policy</dt><dd>{publicEvidenceBinding.evidence_schema_version} · {publicEvidenceBinding.evidence_policy_version}</dd></div>
                <div><dt>Persistence</dt><dd>local only · content not persisted</dd></div>
              </dl>
            </details>
          )}
          <details>
            <summary>Local coding-agent file workflow</summary>
            <p>This metaprompt lets a local agent propose only requirement-to-candidate-index memberships. Preview and import remain local and import remains non-authoritative.</p>
            <textarea aria-label="Requirement-action local-agent metaprompt" readOnly rows={10} value={localAgentMetaprompt} />
            <button onClick={() => void copyLocalAgentWorkflow(currentOwner, localAgentMetaprompt)} type="button">Copy local-agent workflow</button>
            {currentCopyStatus !== "" && <small role="status">{currentCopyStatus}</small>}
          </details>
          <label className="metric-evidence-file__picker">
            <span>Choose canonical requirement-action evidence file</span>
            <input
              accept={`.json,${REQUIREMENT_ACTION_MEDIA_TYPE}`}
              aria-label="Choose canonical requirement-action evidence file"
              disabled={currentBusy}
              onChange={(event) => {
                const input = event.currentTarget;
                const file = input.files?.[0];
                input.value = "";
                void chooseFile(currentOwner, currentContract, file);
              }}
              type="file"
            />
            <small>One local canonical JSON file, 1–65,536 bytes. File names and raw bytes are never displayed.</small>
          </label>
          {currentPreview !== null && currentPayload !== null && (
            <div className="metric-evidence-file__preview" role="status">
              <div>
                <span><strong>{currentPreview.requirement_count} requirements</strong> · {currentPreview.candidate_count} candidates · {currentPreview.linked_requirement_count} linked · {currentPreview.unlinked_requirement_count} explicit empty · {currentPreview.link_count} memberships</span>
                <small>Payload receipt <code>{currentPreview.payload_sha256}</code> · expires <time dateTime={currentPreview.expires_at}>{currentPreview.expires_at}</time>.</small>
                <small>Producer {currentPreview.producer.producer_id} / {currentPreview.producer.model_id} is an ephemeral, untrusted preview claim. Only an opaque keyed receipt persists.</small>
              </div>
              <button disabled={currentBusy} onClick={() => void importPreview(currentOwner, currentContract, currentPreview, currentPayload)} type="button">Import as unconfirmed</button>
            </div>
          )}
          {currentProposals.length === 0 ? (
            <p className="metric-evidence-file__state">No requirement-action proposals are recorded for this exact session and sealed source.</p>
          ) : (
            <ul aria-label="Requirement-action proposal history">
              {currentProposals.map((proposal) => {
                const current = proposalCurrent(proposal, currentContract);
                const proposalReview = currentReview?.proposal_id === proposal.proposal_id
                  && reviewCurrent(currentReview, proposal, currentContract) ? currentReview : null;
                return (
                  <li className="metric-evidence-file__review-proposal" key={proposal.proposal_id}>
                    <div>
                      <strong>Proposal <code className="metric-evidence-file__opaque-id">{proposal.proposal_id}</code></strong>
                      <span className={`requirement-action-evidence__status requirement-action-evidence__status--${proposal.status}`}>{proposal.status === "proposed" ? "Awaiting native decision" : proposal.status === "confirmed" ? "Confirmed" : "Rejected"}</span>
                      <span>{proposalSummary(proposal)}</span>
                      {proposal.status === "proposed" ? (
                        <small>{current
                          ? "Exact current source, r6 predecessor, candidate manifest, and predecessor decision."
                          : bindingInvalid
                            ? "Stale proposal: it does not match the fresh recovery contract, so only native rejection is available."
                            : "Stale proposal: it cannot be confirmed, but native rejection remains available and does not require a fresh source window."}</small>
                      ) : (
                        <small>{proposal.status === "confirmed" ? "Confirmed" : "Rejected"} by {proposal.confirmation_authority === "owned_native_user_presence" ? "owned native user presence" : "unknown authority"} · decision <code>{proposal.decision_id ?? "not recorded"}</code> · <time dateTime={proposal.decided_at ?? undefined}>{proposal.decided_at ?? "time not recorded"}</time>.</small>
                      )}
                    </div>
                    {proposal.status === "proposed" && <div className="metric-evidence-file__proposal-actions">
                      {current && (
                        <button disabled={currentBusy || !currentConfirmationAvailable} onClick={(event) => void openReview(currentOwner, currentContract, proposal, event.currentTarget)} type="button">
                          Inspect every item
                        </button>
                      )}
                      <button
                        disabled={currentBusy || !currentConfirmationAvailable}
                        onClick={(event) => requestDecision(currentOwner, currentContract, proposal, "reject", event.currentTarget)}
                        type="button"
                      >Reject</button>
                    </div>}
                    <details className="requirement-action-evidence__proposal-metadata">
                      <summary>Complete durable proposal metadata</summary>
                      <dl>
                        <div><dt>Session</dt><dd><code>{proposal.session_id}</code></dd></div>
                        <div><dt>Source run</dt><dd><code>{proposal.source_run_id}</code></dd></div>
                        <div><dt>Source window</dt><dd><code>{proposal.source_window_fingerprint}</code></dd></div>
                        <div><dt>Requirement-plan confirmation</dt><dd><code>{proposal.requirement_plan_confirmation_id}</code></dd></div>
                        <div><dt>Requirement-plan evidence</dt><dd><code>{proposal.requirement_plan_evidence_fingerprint}</code></dd></div>
                        <div><dt>Candidate manifest</dt><dd><code>{proposal.candidate_manifest_fingerprint}</code></dd></div>
                        <div><dt>Expected predecessor</dt><dd>{proposal.expected_predecessor_confirmation_id === null ? "not recorded" : <code>{proposal.expected_predecessor_confirmation_id}</code>}</dd></div>
                        <div><dt>Payload receipt</dt><dd><code>{proposal.payload_sha256}</code></dd></div>
                        <div><dt>Producer commitment</dt><dd><code>{proposal.producer_receipt.claim_fingerprint}</code> · {proposal.producer_receipt.authority} · raw claim not persisted</dd></div>
                        <div><dt>Candidate provenance</dt><dd>{proposal.candidate_provenance.provider} {proposal.candidate_provenance.provider_version} · adapter {proposal.candidate_provenance.adapter_version} · decoder {proposal.candidate_provenance.decoder_key} {proposal.candidate_provenance.decoder_version} · source schema {proposal.candidate_provenance.source_schema_version} · evidence schema {proposal.candidate_provenance.evidence_schema_version} · extraction complete</dd></div>
                        <div><dt>Enumeration receipts</dt><dd>candidate extraction complete · candidate enumeration complete</dd></div>
                        <div><dt>Review contract</dt><dd>{proposal.review_rubric_version} · {proposal.schema_version} · {proposal.policy_version}</dd></div>
                        <div><dt>Created</dt><dd><time dateTime={proposal.created_at}>{proposal.created_at}</time></dd></div>
                        <div><dt>Persistence</dt><dd>local only · content not persisted</dd></div>
                      </dl>
                    </details>
                    {proposalReview !== null && (
                      <section
                        aria-label={`Complete review for proposal ${proposal.proposal_id}`}
                        className="metric-evidence-file__clause-review"
                        onKeyDown={(event) => {
                          if (event.key !== "Escape") return;
                          event.preventDefault();
                          closeReview(currentOwner, proposalReview);
                        }}
                        ref={reviewRegionRef}
                        tabIndex={-1}
                      >
                        <header>
                          <strong>Complete local review</strong>
                          <small>All receipts below are complete opaque identifiers; none are visually shortened.</small>
                          <button
                            disabled={currentBusy}
                            onClick={() => closeReview(currentOwner, proposalReview)}
                            type="button"
                          >Close review</button>
                        </header>
                        <dl className="requirement-action-evidence__review-receipts">
                          <div><dt>Review receipt</dt><dd><code>{proposalReview.review_receipt_id}</code></dd></div>
                          <div><dt>Reviewed graph</dt><dd><code>{proposalReview.reviewed_graph_fingerprint}</code></dd></div>
                          <div><dt>Reviewed candidate set</dt><dd><code>{proposalReview.reviewed_candidate_set_fingerprint}</code></dd></div>
                          <div><dt>Reviewed descriptor set</dt><dd><code>{proposalReview.reviewed_descriptor_set_fingerprint}</code></dd></div>
                          <div><dt>Review context expiry</dt><dd><time dateTime={proposalReview.review_context_expires_at}>{proposalReview.review_context_expires_at}</time></dd></div>
                          <div><dt>One-shot receipt expiry</dt><dd><time dateTime={proposalReview.review_receipt_expires_at}>{proposalReview.review_receipt_expires_at}</time></dd></div>
                        </dl>
                        <p>Requirement and descriptor text below is the exact one-pass, injective visible form. Backslash escapes are literal review characters—not instructions to decode—and no displayed value is truncated.</p>
                        <h4>Every active requirement clause</h4>
                        <ol>
                          {proposalReview.requirements.map((requirement, requirementIndex) => (
                            <li key={requirement.requirement_id}>
                              <p><strong>Requirement #{requirementIndex} · message {requirement.coordinate.message_sequence}, clause {requirement.coordinate.clause_index}</strong> · <code className="metric-evidence-file__opaque-id">{requirement.requirement_id}</code> — <span className="metric-evidence-file__exact-review-text">{requirement.text}</span></p>
                              {requirement.linked_action_ids.length === 0
                                ? <small>Explicit empty link: reviewed negative only after this complete native review.</small>
                                : (
                                  <small className="metric-evidence-file__membership-list">
                                    <span>Proposed action memberships:</span>
                                    {requirement.linked_action_ids.map((id) => {
                                      const linkedCandidate = proposalReview.candidates.find((candidate) => candidate.action_id === id)!;
                                      return <span key={id}>candidate #{linkedCandidate.candidate_index} · <code className="metric-evidence-file__opaque-id">{id}</code></span>;
                                    })}
                                  </small>
                                )}
                            </li>
                          ))}
                        </ol>
                        <h4>Every action candidate and ephemeral redacted descriptor</h4>
                        <p>Cross-check each source receipt and its redacted invocation/effect against the safe event in the selected session timeline before accepting a membership. The coarse receipt, descriptor, and application-issued state are review aids—not proof of semantic relevance or task success. Descriptors stay local to this native review and are not persisted.</p>
                        <ol>
                          {proposalReview.candidate_memberships.map((membership) => {
                            const { candidate, linked_requirement_ids } = membership;
                            return (
                            <li key={candidate.action_id}>
                              <article>
                                <p><strong>Candidate #{candidate.candidate_index}</strong> · action <code className="metric-evidence-file__opaque-id">{candidate.action_id}</code> · {humanCode(candidate.event_kind)} · {candidate.tool_category === null ? "no tool category" : humanCode(candidate.tool_category)} · {humanCode(candidate.family)} · state {humanCode(candidate.state)}</p>
                                <small className="metric-evidence-file__membership-list"><span>source receipt <code className="metric-evidence-file__opaque-id">{candidate.source_reference_id}</code> · <time dateTime={candidate.occurred_at}>{candidate.occurred_at}</time> · {durationLabel(candidate.duration_ms)} · sequence {candidate.sequence}</span>{linked_requirement_ids.length === 0
                                  ? <span>no proposed requirement membership</span>
                                  : linked_requirement_ids.map((id) => {
                                    const requirementIndex = proposalReview.requirements.findIndex((requirement) => requirement.requirement_id === id);
                                    return <span key={id}>requirement #{requirementIndex} · <code className="metric-evidence-file__opaque-id">{id}</code></span>;
                                  })}</small>
                                <dl>
                                  <div><dt>Tool name</dt><dd><span className="metric-evidence-file__exact-review-text">{membership.tool_name}</span></dd></div>
                                  <div><dt>Invocation preview</dt><dd><blockquote className="metric-evidence-file__exact-review-text">{membership.invocation_preview}</blockquote></dd></div>
                                  <div><dt>Result or effect preview</dt><dd>{membership.result_or_effect_preview === null
                                    ? "No result/effect preview: this is a started action, not a completed outcome."
                                    : <blockquote className="metric-evidence-file__exact-review-text">{membership.result_or_effect_preview}</blockquote>}</dd></div>
                                  <div><dt>Candidate metadata receipt</dt><dd><code aria-label={`Full candidate metadata fingerprint ${membership.candidate_metadata_fingerprint}`} title={membership.candidate_metadata_fingerprint}>{membership.candidate_metadata_fingerprint}</code> · {membership.candidate_metadata_fingerprint_version}</dd></div>
                                  <div><dt>Descriptor receipt</dt><dd>{membership.descriptor_algorithm_version} · redactor {membership.redactor_version} · invocation complete · {membership.result_or_effect_preview === null ? "effect not applicable for started action" : "effect complete"}</dd></div>
                                </dl>
                              </article>
                            </li>
                            );
                          })}
                        </ol>
                        <label>
                            <input
                              checked={allItemsAcknowledged}
                            disabled={currentBusy}
                            onChange={(event) => {
                              if (
                                !sameOwner(currentOwner, ownerRef.current)
                                || authorityStateRef.current.review !== proposalReview
                                || !reviewCurrent(proposalReview, proposal, currentContract)
                              ) return;
                              setAllItemsAcknowledged(event.currentTarget.checked);
                            }}
                              type="checkbox"
                          />
                          <span>I cross-checked and reviewed every displayed requirement, every action candidate, every ephemeral redacted invocation and effect, every proposed semantic membership, and every explicit empty link in this exact receipt.</span>
                        </label>
                        <button
                          disabled={currentBusy || !allItemsAcknowledged}
                          onClick={(event) => requestDecision(currentOwner, currentContract, proposal, "confirm", event.currentTarget)}
                          type="button"
                        >Confirm exact reviewed graph</button>
                      </section>
                    )}
                    {currentPendingDecision?.proposalId === proposal.proposal_id && (
                      <div
                        aria-label={`${currentPendingDecision.decision === "confirm" ? "Confirm" : "Reject"} requirement-action proposal`}
                        className="metric-evidence-file__decision-confirmation"
                        onKeyDown={(event) => {
                          if (event.key !== "Escape") return;
                          event.preventDefault();
                          event.stopPropagation();
                          closeDecision(currentOwner, currentPendingDecision);
                        }}
                        role="group"
                      >
                        <p>{currentPendingDecision.decision === "confirm"
                          ? "Apply this one-shot receipt and the exact graph, candidate-manifest, candidate-set, and reviewed-descriptor-set fingerprints as metric authority?"
                          : "Reject this inert proposal? Rejection is independent of current source or predecessor authority."}</p>
                        <div>
                          <button disabled={currentBusy} onClick={() => closeDecision(currentOwner, currentPendingDecision)} type="button">Cancel</button>
                          <button disabled={currentBusy} onClick={() => void applyDecision(currentOwner, currentContract, proposal, currentPendingDecision.decision)} ref={decisionActionRef} type="button">
                            {currentPendingDecision.decision === "confirm" ? "Apply exact confirmation" : "Apply rejection"}
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {!currentConfirmationAvailable && (
            <p role="status">Owned native user presence is unavailable. Files may be previewed and imported as inert proposals, but review and decisions are disabled.</p>
          )}
          {currentError !== "" && <p className="metric-evidence-file__error" role="alert">{currentError}</p>}
        </>
      )}
    </section>
  );
}
