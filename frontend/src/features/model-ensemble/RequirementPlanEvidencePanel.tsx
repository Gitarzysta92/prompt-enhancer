import { useEffect, useId, useMemo, useRef, useState } from "react";
import type {
  PromptEnhancerTransport,
  RequirementPlanDecisionRequest,
  RequirementPlanEvidenceContract,
  RequirementPlanEvidencePreview,
  RequirementPlanProposal,
  RequirementPlanProposalReview,
  RequirementPlanReviewClause,
} from "../../shared/api/contracts";
import {
  REQUIREMENT_PLAN_DECISION_CONFIRMATION,
  REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
  REQUIREMENT_PLAN_MEDIA_TYPE,
} from "../../shared/api/requirementPlanEvidenceContract";
import "./MetricEvidenceFilePanel.css";
import "./RequirementPlanEvidencePanel.css";

type RequirementPlanTransport = Pick<PromptEnhancerTransport,
  | "getRequirementPlanEvidenceContract"
  | "previewRequirementPlanEvidence"
  | "importRequirementPlanEvidence"
  | "listRequirementPlanProposals"
  | "reviewRequirementPlanProposal"
  | "decideRequirementPlanProposal">
  & Partial<Pick<PromptEnhancerTransport, "getUserPresenceCapability">>;

type PendingDecision = {
  proposalId: string;
  decision: "confirm" | "reject";
  epoch: number;
  proposalIdentity: string;
  proposalMembershipEpoch: number;
  reviewEpoch: number | null;
};
type ErrorKind = "load" | "validation" | "stale" | "action";
type LivePreview = {
  epoch: number;
  preview: RequirementPlanEvidencePreview;
  payload: ArrayBuffer;
};
type LiveReview = {
  epoch: number;
  review: RequirementPlanProposalReview;
  proposalIdentity: string;
  contractIdentity: string;
};

function idempotency(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "")}`;
}

function exactBinding(
  contract: RequirementPlanEvidenceContract,
  sessionId: string,
  sourceRunId: string,
  sourceProjectionVersion: RequirementPlanEvidenceContract["source_projection_version"],
): boolean {
  return contract.session_id === sessionId
    && contract.expected_source_run_id === sourceRunId
    && contract.source_projection_version === sourceProjectionVersion
    && contract.source_manifest.session_id === sessionId
    && contract.source_manifest.source_run_id === sourceRunId
    && contract.source_manifest.source_window_fingerprint === contract.source_window_fingerprint;
}

function contractReviewCurrent(contract: RequirementPlanEvidenceContract): boolean {
  const expiresAt = Date.parse(contract.source_manifest.review_context_expires_at);
  return Number.isFinite(expiresAt) && expiresAt > Date.now();
}

function coordinateKey(value: { message_sequence: number; clause_index: number }): string {
  return `${value.message_sequence}:${value.clause_index}`;
}

function coordinateLabel(value: { message_sequence: number; clause_index: number }): string {
  return `message ${value.message_sequence}, clause ${value.clause_index}`;
}

function proposalSummary(proposal: RequirementPlanProposal): string {
  const linked = proposal.requirements.filter((item) => item.disposition === "linked").length;
  const notLinked = proposal.requirements.filter((item) => item.disposition === "not_linked").length;
  const pending = proposal.requirements.filter((item) => item.disposition === "pending").length;
  return `${proposal.requirements.length} active requirements · ${proposal.excluded_user_clauses.length} excluded user clauses · ${linked} linked · ${notLinked} not linked · ${pending} pending · ${proposal.plan_items.length} included plan clauses`;
}

function proposalMatchesSource(
  proposal: RequirementPlanProposal,
  contract: RequirementPlanEvidenceContract,
): boolean {
  return proposal.session_id === contract.session_id
    && proposal.source_run_id === contract.expected_source_run_id
    && proposal.source_window_fingerprint === contract.source_window_fingerprint;
}

function proposalCurrent(
  proposal: RequirementPlanProposal,
  contract: RequirementPlanEvidenceContract,
): boolean {
  return proposalMatchesSource(proposal, contract)
    && proposal.expected_predecessor_confirmation_id
      === contract.expected_predecessor_confirmation_id;
}

function previewCurrent(
  preview: RequirementPlanEvidencePreview,
  contract: RequirementPlanEvidenceContract,
): boolean {
  const expiresAt = Date.parse(preview.expires_at);
  return preview.session_id === contract.session_id
    && preview.expected_source_run_id === contract.expected_source_run_id
    && preview.source_window_fingerprint === contract.source_window_fingerprint
    && preview.expected_predecessor_confirmation_id
      === contract.expected_predecessor_confirmation_id
    && Number.isFinite(expiresAt)
    && expiresAt > Date.now()
    && preview.reviewed_user_clause_count
      === preview.active_requirement_count + preview.excluded_user_clause_count
    && preview.active_requirement_count
      === preview.linked_active_requirement_count
        + preview.not_linked_active_requirement_count
        + preview.pending_active_requirement_count
    && preview.reviewed_user_clause_count <= contract.max_reviewed_user_clause_count
    && preview.active_requirement_count <= contract.max_active_requirement_count
    && preview.excluded_user_clause_count <= contract.max_excluded_user_clause_count
    && preview.plan_item_count <= contract.max_plan_item_count
    && preview.link_count <= contract.max_link_count
    && preview.creates_unconfirmed_proposal_only === true
    && preview.native_confirmation_required_for_metric_authority === true
    && preview.can_set_numeric_metric_on_import === false
    && preview.raw_payload_persisted === false
    && preview.raw_producer_claim_persisted === false;
}

function importedProposalCurrent(
  proposal: RequirementPlanProposal,
  preview: RequirementPlanEvidencePreview,
  contract: RequirementPlanEvidenceContract,
): boolean {
  const linked = proposal.requirements.filter((item) => item.disposition === "linked").length;
  const notLinked = proposal.requirements.filter((item) => item.disposition === "not_linked").length;
  const pending = proposal.requirements.filter((item) => item.disposition === "pending").length;
  const linkCount = proposal.requirements.reduce(
    (count, requirement) => count + requirement.plan_indexes.length,
    0,
  );
  return proposalCurrent(proposal, contract)
    && proposal.payload_sha256 === preview.payload_sha256
    && proposal.status === "proposed"
    && proposal.decision === null
    && proposal.decision_id === null
    && proposal.decided_at === null
    && proposal.confirmation_authority === null
    && proposal.requirements.length === preview.active_requirement_count
    && proposal.excluded_user_clauses.length === preview.excluded_user_clause_count
    && proposal.plan_items.length === preview.plan_item_count
    && linked === preview.linked_active_requirement_count
    && notLinked === preview.not_linked_active_requirement_count
    && pending === preview.pending_active_requirement_count
    && linkCount === preview.link_count;
}

function coordinatesEqual(
  left: { message_sequence: number; clause_index: number } | null,
  right: { message_sequence: number; clause_index: number } | null,
): boolean {
  return left === null || right === null
    ? left === right
    : coordinateKey(left) === coordinateKey(right);
}

function reviewClausesComplete(
  review: RequirementPlanProposalReview,
  proposal: RequirementPlanProposal,
  contract: RequirementPlanEvidenceContract,
): boolean {
  const expected = contract.source_manifest.messages.flatMap((message) => {
    const reviewable = (
      message.role === "user" && (message.kind === "request" || message.kind === "feedback")
    ) || (message.role === "agent" && message.kind === "plan");
    return reviewable
      ? Array.from({ length: message.clause_count }, (_, clauseIndex) => ({
        coordinate: { message_sequence: message.message_sequence, clause_index: clauseIndex },
        message,
      }))
      : [];
  });
  if (review.candidate_clauses.length !== expected.length) return false;
  const requirementByCoordinate = new Map(
    proposal.requirements.map((item) => [coordinateKey(item.coordinate), item]),
  );
  const excludedByCoordinate = new Map(
    proposal.excluded_user_clauses.map((item) => [coordinateKey(item.coordinate), item]),
  );
  const planByCoordinate = new Map(
    proposal.plan_items.map((item, index) => [coordinateKey(item), index]),
  );
  return review.candidate_clauses.every((clause, index) => {
    const expectedClause = expected[index];
    if (
      expectedClause === undefined
      || coordinateKey(clause) !== coordinateKey(expectedClause.coordinate)
      || clause.role !== expectedClause.message.role
      || clause.kind !== expectedClause.message.kind
    ) return false;
    const key = coordinateKey(clause);
    if (expectedClause.message.role === "agent") {
      return clause.candidate_kind === "plan"
        && clause.included_in_proposal === planByCoordinate.has(key)
        && clause.classification === null
        && clause.exclusion_reason === null
        && clause.basis_coordinate === null
        && clause.disposition === null
        && clause.linked_plan_coordinates.length === 0;
    }
    const requirement = requirementByCoordinate.get(key);
    const excluded = excludedByCoordinate.get(key);
    if (requirement !== undefined) {
      const expectedLinks = requirement.plan_indexes.map((planIndex) => proposal.plan_items[planIndex]);
      return excluded === undefined
        && expectedLinks.every((coordinate) => coordinate !== undefined)
        && clause.candidate_kind === "user_clause"
        && clause.included_in_proposal === true
        && clause.classification === "active_requirement"
        && clause.exclusion_reason === null
        && clause.basis_coordinate === null
        && clause.disposition === requirement.disposition
        && JSON.stringify(clause.linked_plan_coordinates) === JSON.stringify(expectedLinks);
    }
    return excluded !== undefined
      && clause.candidate_kind === "user_clause"
      && clause.included_in_proposal === true
      && clause.classification === "excluded_from_active_requirement_denominator"
      && clause.exclusion_reason === excluded.reason
      && coordinatesEqual(clause.basis_coordinate, excluded.basis_coordinate)
      && clause.disposition === null
      && clause.linked_plan_coordinates.length === 0;
  });
}

function receiptCurrent(
  review: RequirementPlanProposalReview,
  proposal: RequirementPlanProposal,
  contract: RequirementPlanEvidenceContract,
): boolean {
  const expiry = Math.min(
    Date.parse(review.review_context_expires_at),
    Date.parse(review.review_receipt_expires_at),
  );
  return proposalCurrent(proposal, contract)
    && review.proposal_id === proposal.proposal_id
    && review.session_id === contract.session_id
    && review.source_run_id === contract.expected_source_run_id
    && review.source_window_fingerprint === contract.source_window_fingerprint
    && review.payload_sha256 === proposal.payload_sha256
    && review.manifest_fingerprint === contract.source_manifest.manifest_fingerprint
    && review.review_context_expires_at === contract.source_manifest.review_context_expires_at
    && review.candidate_clauses.length === contract.source_manifest.candidate_clause_count
    && reviewClausesComplete(review, proposal, contract)
    && review.all_coordinates_structurally_valid === true
    && review.raw_text_persisted === false
    && review.local_only === true
    && Number.isFinite(expiry)
    && expiry > Date.now();
}

function proposalEvidenceIdentity(proposal: RequirementPlanProposal): string {
  return JSON.stringify([
    proposal.proposal_id,
    proposal.session_id,
    proposal.source_run_id,
    proposal.source_window_fingerprint,
    proposal.expected_predecessor_confirmation_id,
    proposal.payload_sha256,
    proposal.producer_receipt,
    proposal.review_rubric_version,
    proposal.requirements,
    proposal.excluded_user_clauses,
    proposal.plan_items,
    proposal.created_at,
    proposal.schema_version,
    proposal.policy_version,
    proposal.local_only,
    proposal.content_persisted,
  ]);
}

function decisionCurrent(
  result: RequirementPlanProposal,
  expected: RequirementPlanProposal,
  decision: "confirm" | "reject",
): boolean {
  return proposalEvidenceIdentity(result) === proposalEvidenceIdentity(expected)
    && result.status === (decision === "confirm" ? "confirmed" : "rejected")
    && result.decision === decision
    && result.decision_id !== null
    && result.decided_at !== null
    && result.confirmation_authority === "owned_native_user_presence";
}

function contractAuthorityIdentity(contract: RequirementPlanEvidenceContract): string {
  return JSON.stringify(contract);
}

function coherentNativePresence(value: unknown): boolean {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const presence = value as Record<string, unknown>;
  return presence.contract_version === "native-user-presence-capability-v1"
    && presence.confirmation_available === true
    && presence.mode === "native_bridge_bound_token";
}

function isAcceptedFile(file: File): boolean {
  const mediaType = file.type.toLowerCase();
  return file.name.toLowerCase().endsWith(".json")
    && (mediaType === "" || mediaType === "application/json" || mediaType === REQUIREMENT_PLAN_MEDIA_TYPE);
}

function reasonLabel(reason: NonNullable<RequirementPlanReviewClause["exclusion_reason"]>): string {
  return reason.replaceAll("_", " ");
}

export function RequirementPlanEvidencePanel({
  compact,
  sessionId,
  sourceRunId,
  sourceProjectionVersion,
  transport,
  onEvidenceChanged,
}: {
  compact: boolean;
  sessionId: string;
  sourceRunId: string;
  sourceProjectionVersion: RequirementPlanEvidenceContract["source_projection_version"];
  transport: RequirementPlanTransport;
  onEvidenceChanged?: () => void;
}) {
  const headingId = useId();
  const fileHelpId = useId();
  const proposalsHeadingId = useId();
  const decisionsHeadingId = useId();
  const sourceProjectionLabel = sourceProjectionVersion.replace(
    "metric-contract-v2-projection-",
    "r",
  );
  const currentBinding = JSON.stringify([sessionId, sourceRunId, sourceProjectionVersion]);
  const [stateBinding, setStateBinding] = useState(currentBinding);
  const [stateTransport, setStateTransport] = useState(transport);
  const [contract, setContract] = useState<RequirementPlanEvidenceContract | null>(null);
  const [proposals, setProposals] = useState<RequirementPlanProposal[]>([]);
  const [preview, setPreview] = useState<RequirementPlanEvidencePreview | null>(null);
  const [payload, setPayload] = useState<ArrayBuffer | null>(null);
  const [confirmationAvailable, setConfirmationAvailable] = useState(false);
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [review, setReview] = useState<RequirementPlanProposalReview | null>(null);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
  const [notice, setNotice] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const operationRef = useRef<AbortController | null>(null);
  const bindingRef = useRef(currentBinding);
  const transportRef = useRef(transport);
  const contractAuthorityRef = useRef<{ contract: RequirementPlanEvidenceContract; identity: string } | null>(null);
  const proposalsLiveRef = useRef<RequirementPlanProposal[]>([]);
  const proposalMembershipEpochRef = useRef(0);
  const previewEpochRef = useRef(0);
  const livePreviewRef = useRef<LivePreview | null>(null);
  const reviewEpochRef = useRef(0);
  const liveReviewRef = useRef<LiveReview | null>(null);
  const acknowledgementLiveRef = useRef(false);
  const decisionEpochRef = useRef(0);
  const pendingDecisionLiveRef = useRef<PendingDecision | null>(null);
  const confirmationAvailableRef = useRef(false);
  const previewRegionRef = useRef<HTMLDivElement | null>(null);
  const reviewRef = useRef<HTMLElement | null>(null);
  const reviewTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreReviewFocusRef = useRef(false);
  const decisionActionRef = useRef<HTMLButtonElement | null>(null);
  const decisionTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreDecisionFocusRef = useRef(false);
  const noticeRef = useRef<HTMLParagraphElement | null>(null);
  const focusNoticeRef = useRef(false);
  bindingRef.current = currentBinding;
  transportRef.current = transport;

  const capabilities = transport.getRequirementPlanEvidenceContract !== undefined
    && transport.previewRequirementPlanEvidence !== undefined
    && transport.importRequirementPlanEvidence !== undefined
    && transport.listRequirementPlanProposals !== undefined
    && transport.reviewRequirementPlanProposal !== undefined
    && transport.decideRequirementPlanProposal !== undefined;

  function publishContract(next: RequirementPlanEvidenceContract | null): void {
    contractAuthorityRef.current = next === null ? null : {
      contract: next,
      identity: contractAuthorityIdentity(next),
    };
    setContract(next);
  }

  function publishProposals(next: RequirementPlanProposal[]): void {
    proposalMembershipEpochRef.current += 1;
    proposalsLiveRef.current = next;
    const liveReview = liveReviewRef.current;
    if (
      liveReview !== null
      && !next.some((proposal) => (
        proposal.status === "proposed"
        && proposalEvidenceIdentity(proposal) === liveReview.proposalIdentity
      ))
    ) clearReview();
    else invalidatePendingDecision();
    setProposals(next);
  }

  function updateProposals(
    updater: (current: RequirementPlanProposal[]) => RequirementPlanProposal[],
  ): void {
    publishProposals(updater(proposalsLiveRef.current));
  }

  function findLiveProposal(expected: RequirementPlanProposal): RequirementPlanProposal | null {
    const identity = proposalEvidenceIdentity(expected);
    return proposalsLiveRef.current.find((proposal) => (
      proposal.proposal_id === expected.proposal_id
      && proposal.status === "proposed"
      && proposalEvidenceIdentity(proposal) === identity
    )) ?? null;
  }

  function invalidatePreview(): void {
    previewEpochRef.current += 1;
    livePreviewRef.current = null;
    setPreview(null);
    setPayload(null);
  }

  function publishPreview(
    nextPreview: RequirementPlanEvidencePreview,
    nextPayload: ArrayBuffer,
  ): void {
    const epoch = previewEpochRef.current + 1;
    previewEpochRef.current = epoch;
    livePreviewRef.current = { epoch, preview: nextPreview, payload: nextPayload };
    setPayload(nextPayload);
    setPreview(nextPreview);
  }

  function invalidatePendingDecision(): void {
    decisionEpochRef.current += 1;
    pendingDecisionLiveRef.current = null;
    setPendingDecision(null);
  }

  function publishPendingDecision(next: Omit<PendingDecision, "epoch">): void {
    const epoch = decisionEpochRef.current + 1;
    decisionEpochRef.current = epoch;
    const pending = { ...next, epoch };
    pendingDecisionLiveRef.current = pending;
    setPendingDecision(pending);
  }

  function publishReview(
    nextReview: RequirementPlanProposalReview,
    proposalIdentity: string,
    contractIdentity: string,
  ): void {
    const epoch = reviewEpochRef.current + 1;
    reviewEpochRef.current = epoch;
    liveReviewRef.current = {
      epoch,
      review: nextReview,
      proposalIdentity,
      contractIdentity,
    };
    acknowledgementLiveRef.current = false;
    setReviewAcknowledged(false);
    invalidatePendingDecision();
    setReview(nextReview);
  }

  function clearReview(): void {
    reviewEpochRef.current += 1;
    liveReviewRef.current = null;
    acknowledgementLiveRef.current = false;
    setReview(null);
    setReviewAcknowledged(false);
    invalidatePendingDecision();
  }

  function updateAcknowledgement(next: boolean): void {
    if (!admitsCurrentContext() || liveReviewRef.current === null) return;
    if (acknowledgementLiveRef.current !== next) invalidatePendingDecision();
    acknowledgementLiveRef.current = next;
    setReviewAcknowledged(next);
  }

  function publishConfirmationAvailability(next: boolean): void {
    confirmationAvailableRef.current = next;
    setConfirmationAvailable(next);
    if (!next) invalidatePendingDecision();
  }

  useEffect(() => {
    operationRef.current?.abort();
    setStateBinding(currentBinding);
    setStateTransport(transport);
    publishContract(null);
    publishProposals([]);
    invalidatePreview();
    clearReview();
    publishConfirmationAvailability(false);
    setBusy(false);
    setError("");
    setErrorKind(null);
    setNotice("");
    setLoading(capabilities);
    restoreReviewFocusRef.current = false;
    restoreDecisionFocusRef.current = false;
    focusNoticeRef.current = false;
    if (!capabilities) return;
    const controller = new AbortController();
    operationRef.current = controller;
    const binding = currentBinding;
    const presence = transport.getUserPresenceCapability === undefined
      ? Promise.resolve(null)
      : transport.getUserPresenceCapability(controller.signal).catch(() => null);
    Promise.all([
      transport.getRequirementPlanEvidenceContract!(sessionId, controller.signal),
      transport.listRequirementPlanProposals!(sessionId, controller.signal),
      presence,
    ]).then(([loadedContract, collection, presence]) => {
      if (
        controller.signal.aborted
        || bindingRef.current !== binding
        || transportRef.current !== transport
      ) return;
      if (
        !exactBinding(loadedContract, sessionId, sourceRunId, sourceProjectionVersion)
        || !contractReviewCurrent(loadedContract)
      ) {
        setError(`Requirement-plan review is not bound to a current exact sealed ${sourceProjectionLabel} source window.`);
        setErrorKind("stale");
        setLoading(false);
        return;
      }
      if (collection.session_id !== sessionId || collection.complete !== true) {
        setError("The exact requirement-plan proposal collection was incomplete or belonged to another session.");
        setErrorKind("load");
        setLoading(false);
        return;
      }
      publishContract(loadedContract);
      publishProposals(collection.proposals.filter((proposal) => (
        proposalMatchesSource(proposal, loadedContract)
      )));
      publishConfirmationAvailability(coherentNativePresence(presence));
      setLoading(false);
    }).catch(() => {
      if (
        !controller.signal.aborted
        && bindingRef.current === binding
        && transportRef.current === transport
      ) {
        setError("Reviewed requirement-plan evidence is temporarily unavailable.");
        setErrorKind("load");
        setLoading(false);
      }
    });
    return () => controller.abort();
  }, [capabilities, currentBinding, reloadToken, sessionId, sourceProjectionVersion, sourceRunId, transport]);

  useEffect(() => {
    if (contract === null) return;
    const expiresIn = Date.parse(contract.source_manifest.review_context_expires_at) - Date.now();
    const expire = () => {
      if (bindingRef.current !== stateBinding || transportRef.current !== stateTransport) return;
      operationRef.current?.abort();
      publishContract(null);
      publishProposals([]);
      invalidatePreview();
      clearReview();
      publishConfirmationAvailability(false);
      setBusy(false);
      setNotice("");
      setError("The exact sealed source review context expired. Refresh before previewing, reviewing, or deciding.");
      setErrorKind("stale");
    };
    if (expiresIn <= 0) {
      expire();
      return;
    }
    const timer = window.setTimeout(expire, Math.min(expiresIn, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [contract, stateBinding, stateTransport]);

  useEffect(() => {
    if (preview === null) return;
    const expiresIn = Date.parse(preview.expires_at) - Date.now();
    const expire = () => {
      if (bindingRef.current !== stateBinding || transportRef.current !== stateTransport) return;
      invalidatePreview();
      setNotice("");
      setError("The strict local file preview expired. Select the unchanged canonical bytes again before import.");
      setErrorKind("stale");
    };
    if (expiresIn <= 0) {
      expire();
      return;
    }
    const timer = window.setTimeout(expire, Math.min(expiresIn, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [preview, stateBinding, stateTransport]);

  useEffect(() => {
    if (review === null) return;
    const ownerBinding = stateBinding;
    const ownerTransport = stateTransport;
    const expiresIn = Math.min(
      Date.parse(review.review_context_expires_at),
      Date.parse(review.review_receipt_expires_at),
    ) - Date.now();
    const expire = () => {
      if (bindingRef.current !== ownerBinding || transportRef.current !== ownerTransport) return;
      clearReview();
      setNotice("");
      setError("The exact local clause-review receipt expired. Open a fresh review before confirming.");
      setErrorKind("stale");
    };
    if (expiresIn <= 0) {
      expire();
      return;
    }
    const timer = window.setTimeout(expire, Math.min(expiresIn, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [review, stateBinding, stateTransport]);

  useEffect(() => {
    if (preview !== null) previewRegionRef.current?.focus();
  }, [preview]);

  useEffect(() => {
    if (review !== null) reviewRef.current?.focus();
    else if (restoreReviewFocusRef.current) {
      reviewTriggerRef.current?.focus();
      restoreReviewFocusRef.current = false;
    }
  }, [review]);

  useEffect(() => {
    if (pendingDecision !== null) decisionActionRef.current?.focus();
    else if (restoreDecisionFocusRef.current) {
      decisionTriggerRef.current?.focus();
      restoreDecisionFocusRef.current = false;
    }
  }, [pendingDecision]);

  useEffect(() => {
    if (notice !== "" && focusNoticeRef.current) {
      noticeRef.current?.focus();
      focusNoticeRef.current = false;
    }
  }, [notice]);

  const undecided = useMemo(
    () => proposals.filter((proposal) => proposal.status === "proposed"),
    [proposals],
  );
  const decided = useMemo(
    () => proposals.filter((proposal) => proposal.status !== "proposed"),
    [proposals],
  );
  const confirmedCount = useMemo(
    () => decided.filter((proposal) => proposal.status === "confirmed").length,
    [decided],
  );
  const rejectedCount = decided.length - confirmedCount;

  function beginOperation(): { controller: AbortController; binding: string } {
    operationRef.current?.abort();
    const controller = new AbortController();
    operationRef.current = controller;
    return { controller, binding: currentBinding };
  }

  function stillCurrent(controller: AbortController, binding: string): boolean {
    return !controller.signal.aborted
      && bindingRef.current === binding
      && transportRef.current === transport;
  }

  function admitsCurrentContext(): boolean {
    return stateBinding === currentBinding
      && stateTransport === transport
      && bindingRef.current === currentBinding
      && transportRef.current === transport;
  }

  function focusNotice(): void {
    focusNoticeRef.current = true;
  }

  function reloadCurrentContext(): void {
    if (!admitsCurrentContext()) return;
    operationRef.current?.abort();
    publishContract(null);
    publishProposals([]);
    invalidatePreview();
    clearReview();
    publishConfirmationAvailability(false);
    setBusy(false);
    setLoading(true);
    setError("");
    setErrorKind(null);
    setNotice("");
    setReloadToken((value) => value + 1);
  }

  function closeReview(): void {
    if (!admitsCurrentContext()) return;
    restoreReviewFocusRef.current = true;
    clearReview();
  }

  function cancelDecision(): void {
    if (!admitsCurrentContext()) return;
    restoreDecisionFocusRef.current = true;
    invalidatePendingDecision();
  }

  function openDecision(
    proposal: RequirementPlanProposal,
    decision: "confirm" | "reject",
    trigger: HTMLButtonElement,
    expectedDecisionEpoch: number,
    expectedReviewEpoch: number,
    expectedProposalMembershipEpoch: number,
  ): void {
    const liveContract = contractAuthorityRef.current;
    const liveProposal = findLiveProposal(proposal);
    const liveReview = liveReviewRef.current;
    if (
      !admitsCurrentContext()
      || decisionEpochRef.current !== expectedDecisionEpoch
      || reviewEpochRef.current !== expectedReviewEpoch
      || proposalMembershipEpochRef.current !== expectedProposalMembershipEpoch
      || liveContract === null
      || !contractReviewCurrent(liveContract.contract)
      || !confirmationAvailableRef.current
      || liveProposal === null
      || !proposalMatchesSource(liveProposal, liveContract.contract)
      || (decision === "confirm" && (
        !proposalCurrent(liveProposal, liveContract.contract)
        || liveReview === null
        || liveReview.proposalIdentity !== proposalEvidenceIdentity(liveProposal)
        || liveReview.contractIdentity !== liveContract.identity
        || !receiptCurrent(liveReview.review, liveProposal, liveContract.contract)
        || !acknowledgementLiveRef.current
      ))
    ) return;
    decisionTriggerRef.current = trigger;
    setError("");
    setErrorKind(null);
    setNotice("");
    publishPendingDecision({
      proposalId: liveProposal.proposal_id,
      decision,
      proposalIdentity: proposalEvidenceIdentity(liveProposal),
      proposalMembershipEpoch: expectedProposalMembershipEpoch,
      reviewEpoch: decision === "confirm" ? liveReview!.epoch : null,
    });
  }

  async function chooseFile(file: File | undefined) {
    if (!admitsCurrentContext()) return;
    invalidatePreview();
    clearReview();
    setError("");
    setErrorKind(null);
    setNotice("");
    const liveContract = contractAuthorityRef.current;
    if (file === undefined || liveContract === null || transport.previewRequirementPlanEvidence === undefined) return;
    const expectedContract = liveContract.contract;
    const expectedContractIdentity = liveContract.identity;
    if (!contractReviewCurrent(expectedContract)) {
      setError("The exact local source review window expired; refresh before selecting a file.");
      setErrorKind("stale");
      return;
    }
    if (file.size < 1 || file.size > expectedContract.max_file_bytes) {
      setError("Choose one non-empty canonical requirement-plan file no larger than 64 KiB.");
      setErrorKind("validation");
      return;
    }
    if (!isAcceptedFile(file)) {
      setError("Choose a .json file using JSON or the canonical requirement-plan media type.");
      setErrorKind("validation");
      return;
    }
    const { controller, binding } = beginOperation();
    setBusy(true);
    setNotice("Validating the selected canonical bytes locally…");
    try {
      const bytes = await file.arrayBuffer();
      if (
        !stillCurrent(controller, binding)
        || contractAuthorityRef.current?.identity !== expectedContractIdentity
      ) return;
      if (bytes.byteLength !== file.size || bytes.byteLength < 1 || bytes.byteLength > expectedContract.max_file_bytes) {
        setNotice("");
        setError("The selected bytes changed size or exceeded the strict 64 KiB boundary. Nothing was previewed.");
        setErrorKind("validation");
        return;
      }
      const result = await transport.previewRequirementPlanEvidence(sessionId, bytes, controller.signal);
      if (
        !stillCurrent(controller, binding)
        || contractAuthorityRef.current?.identity !== expectedContractIdentity
      ) return;
      if (!contractReviewCurrent(expectedContract) || !previewCurrent(result, expectedContract)) {
        setNotice("");
        setError("The file preview is expired or bound to another exact session, sealed run, projection window, or predecessor.");
        setErrorKind("stale");
        return;
      }
      publishPreview(result, bytes);
      setNotice("Strict preview ready. Importing creates an unconfirmed proposal only.");
    } catch {
      if (stillCurrent(controller, binding)) {
        setError("The file failed strict local schema validation; no proposal was imported.");
        setErrorKind("validation");
        setNotice("");
      }
    } finally {
      if (stillCurrent(controller, binding)) setBusy(false);
    }
  }

  async function importPreview(expectedPreviewEpoch: number) {
    const livePreview = livePreviewRef.current;
    const liveContract = contractAuthorityRef.current;
    if (
      !admitsCurrentContext()
      || livePreview === null
      || livePreview.epoch !== expectedPreviewEpoch
      || liveContract === null
      || transport.importRequirementPlanEvidence === undefined
      || !contractReviewCurrent(liveContract.contract)
      || !previewCurrent(livePreview.preview, liveContract.contract)
    ) {
      if (
        livePreview?.epoch === expectedPreviewEpoch
        && Date.parse(livePreview.preview.expires_at) <= Date.now()
      ) {
        invalidatePreview();
        setError("The strict local file preview expired. Select the unchanged canonical bytes again before import.");
        setErrorKind("stale");
      }
      return;
    }
    const expectedPreview = livePreview.preview;
    const expectedPayload = livePreview.payload;
    const expectedContract = liveContract.contract;
    const expectedContractIdentity = liveContract.identity;
    invalidatePreview();
    clearReview();
    const { controller, binding } = beginOperation();
    setBusy(true);
    setError("");
    setErrorKind(null);
    setNotice("Importing the exact preview as an unconfirmed proposal…");
    try {
      const result = await transport.importRequirementPlanEvidence(
        sessionId,
        expectedPayload,
        expectedPreview,
        REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency("requirement-plan-import"),
        controller.signal,
      );
      if (
        !stillCurrent(controller, binding)
        || contractAuthorityRef.current?.identity !== expectedContractIdentity
      ) return;
      const proposal = result.proposal;
      if (
        result.payload_sha256 !== expectedPreview.payload_sha256
        || result.creates_unconfirmed_proposal_only !== true
        || result.native_confirmation_required_for_metric_authority !== true
        || result.raw_payload_persisted !== false
        || !importedProposalCurrent(proposal, expectedPreview, expectedContract)
      ) {
        setNotice("");
        setError("The imported proposal did not preserve the exact preview, source, projection-window, predecessor, and non-authoritative binding.");
        setErrorKind("stale");
        return;
      }
      updateProposals((current) => [
        proposal,
        ...current.filter((item) => item.proposal_id !== proposal.proposal_id),
      ]);
      setNotice("Unconfirmed proposal imported. Open a separate complete local clause review before any native decision.");
      focusNotice();
    } catch {
      if (stillCurrent(controller, binding)) {
        setError("The preview binding changed or the proposal could not be imported.");
        setErrorKind("action");
        setNotice("");
      }
    } finally {
      if (stillCurrent(controller, binding)) setBusy(false);
    }
  }

  async function openReview(
    proposal: RequirementPlanProposal,
    trigger: HTMLButtonElement,
    expectedDecisionEpoch: number,
    expectedReviewEpoch: number,
    expectedProposalMembershipEpoch: number,
  ) {
    const liveContract = contractAuthorityRef.current;
    const liveProposal = findLiveProposal(proposal);
    if (
      !admitsCurrentContext()
      || decisionEpochRef.current !== expectedDecisionEpoch
      || reviewEpochRef.current !== expectedReviewEpoch
      || proposalMembershipEpochRef.current !== expectedProposalMembershipEpoch
      || liveContract === null
      || !confirmationAvailableRef.current
      || !contractReviewCurrent(liveContract.contract)
      || transport.reviewRequirementPlanProposal === undefined
      || liveProposal === null
      || !proposalCurrent(liveProposal, liveContract.contract)
    ) return;
    const expectedContract = liveContract.contract;
    const expectedContractIdentity = liveContract.identity;
    const expectedProposalIdentity = proposalEvidenceIdentity(liveProposal);
    reviewTriggerRef.current = trigger;
    clearReview();
    const openingReviewEpoch = reviewEpochRef.current;
    const openingDecisionEpoch = decisionEpochRef.current;
    const { controller, binding } = beginOperation();
    setBusy(true);
    setError("");
    setErrorKind(null);
    setNotice("Opening the one-shot complete local clause review…");
    try {
      const loaded = await transport.reviewRequirementPlanProposal(
        sessionId,
        liveProposal,
        expectedContract,
        {
          expected_source_run_id: sourceRunId,
          confirmation: "open_exact_local_requirement_plan_clause_review",
        },
        controller.signal,
      );
      if (
        !stillCurrent(controller, binding)
        || contractAuthorityRef.current?.identity !== expectedContractIdentity
        || proposalMembershipEpochRef.current !== expectedProposalMembershipEpoch
        || reviewEpochRef.current !== openingReviewEpoch
        || decisionEpochRef.current !== openingDecisionEpoch
        || findLiveProposal(liveProposal) === null
      ) return;
      if (!receiptCurrent(loaded, liveProposal, expectedContract)) {
        setNotice("");
        setError("The complete local clause review is incomplete, stale, mismatched, or expired; nothing can be confirmed.");
        setErrorKind("stale");
        return;
      }
      publishReview(loaded, expectedProposalIdentity, expectedContractIdentity);
      setNotice("Complete one-shot review opened. Acknowledgement applies only to this exact receipt.");
    } catch {
      if (stillCurrent(controller, binding)) {
        clearReview();
        setError("The exact local clause review could not be opened; refresh the sealed run before confirming.");
        setErrorKind("action");
        setNotice("");
      }
    } finally {
      if (stillCurrent(controller, binding)) setBusy(false);
    }
  }

  async function applyDecision(proposal: RequirementPlanProposal, pending: PendingDecision) {
    const livePending = pendingDecisionLiveRef.current;
    const liveContract = contractAuthorityRef.current;
    const liveProposal = findLiveProposal(proposal);
    const liveReview = liveReviewRef.current;
    if (
      !admitsCurrentContext()
      || transport.decideRequirementPlanProposal === undefined
      || !confirmationAvailableRef.current
      || livePending === null
      || livePending.epoch !== pending.epoch
      || livePending.proposalId !== pending.proposalId
      || livePending.decision !== pending.decision
      || livePending.proposalIdentity !== pending.proposalIdentity
      || livePending.proposalMembershipEpoch !== pending.proposalMembershipEpoch
      || livePending.reviewEpoch !== pending.reviewEpoch
      || proposalMembershipEpochRef.current !== pending.proposalMembershipEpoch
      || liveContract === null
      || !contractReviewCurrent(liveContract.contract)
      || liveProposal === null
      || proposalEvidenceIdentity(liveProposal) !== pending.proposalIdentity
      || !proposalMatchesSource(liveProposal, liveContract.contract)
      || (pending.decision === "confirm" && (
        !proposalCurrent(liveProposal, liveContract.contract)
        || liveReview === null
        || liveReview.epoch !== pending.reviewEpoch
        || liveReview.proposalIdentity !== pending.proposalIdentity
        || liveReview.contractIdentity !== liveContract.identity
        || !receiptCurrent(liveReview.review, liveProposal, liveContract.contract)
        || !acknowledgementLiveRef.current
      ))
    ) return;
    const decision = pending.decision;
    const expectedContractIdentity = liveContract.identity;
    const currentReview = decision === "confirm" ? liveReview!.review : null;
    const request: RequirementPlanDecisionRequest = decision === "confirm" ? {
      expected_source_run_id: sourceRunId,
      decision: "confirm",
      confirmation: REQUIREMENT_PLAN_DECISION_CONFIRMATION,
      review_receipt_id: currentReview!.review_receipt_id,
      manifest_fingerprint: currentReview!.manifest_fingerprint,
      reviewed_graph_fingerprint: currentReview!.reviewed_graph_fingerprint,
      reviewed_candidate_set_fingerprint: currentReview!.reviewed_candidate_set_fingerprint,
      complete_review_acknowledged: true,
    } : {
      expected_source_run_id: sourceRunId,
      decision: "reject",
      confirmation: REQUIREMENT_PLAN_DECISION_CONFIRMATION,
    };
    invalidatePendingDecision();
    const { controller, binding } = beginOperation();
    setBusy(true);
    setError("");
    setErrorKind(null);
    setNotice(decision === "confirm" ? "Applying exact native confirmation…" : "Applying native rejection…");
    try {
      const result = await transport.decideRequirementPlanProposal(
        sessionId,
        liveProposal.proposal_id,
        request,
        idempotency(`requirement-plan-${decision}`),
        controller.signal,
      );
      if (
        !stillCurrent(controller, binding)
        || contractAuthorityRef.current?.identity !== expectedContractIdentity
        || proposalMembershipEpochRef.current !== pending.proposalMembershipEpoch
        || findLiveProposal(liveProposal) === null
      ) return;
      if (!decisionCurrent(result.proposal, liveProposal, decision)) {
        clearReview();
        setNotice("");
        setError("The native decision response did not preserve the exact proposal, source, graph, and requested decision.");
        setErrorKind("stale");
        return;
      }
      updateProposals((current) => current.map((item) => (
        item.proposal_id === result.proposal.proposal_id ? result.proposal : item
      )));
      clearReview();
      setNotice(decision === "confirm"
        ? "Reviewed requirement-plan evidence confirmed for this sealed source. Run a fresh analysis to publish new metric authority."
        : "Proposal rejected. It remains excluded from metric authority.");
      focusNotice();
      if (decision === "confirm") onEvidenceChanged?.();
    } catch {
      if (stillCurrent(controller, binding)) {
        setError("The source window, review receipt, or native decision authority changed; open a fresh review before deciding.");
        setErrorKind("action");
        setNotice("");
      }
    } finally {
      if (stillCurrent(controller, binding)) {
        clearReview();
        setBusy(false);
      }
    }
  }

  const renderedPreviewEpoch = preview !== null
    && livePreviewRef.current !== null
    && JSON.stringify(livePreviewRef.current.preview) === JSON.stringify(preview)
    ? livePreviewRef.current.epoch
    : null;
  const renderedDecisionEpoch = decisionEpochRef.current;
  const renderedReviewEpoch = reviewEpochRef.current;
  const renderedProposalMembershipEpoch = proposalMembershipEpochRef.current;
  const contextIsCurrent = stateBinding === currentBinding && stateTransport === transport;
  const panelState = !capabilities
    ? "unavailable"
    : !contextIsCurrent || loading
      ? "loading"
      : errorKind === "stale"
        ? "stale"
        : error !== ""
          ? "error"
          : preview !== null
            ? "preview"
            : undecided.length > 0
              ? "ready"
              : confirmedCount > 0
                ? "confirmed"
                : rejectedCount > 0
                  ? "rejected"
                  : "empty";

  if (!contextIsCurrent && capabilities) {
    return compact ? (
      <section aria-label="Reviewed requirement-to-plan evidence" className="metric-evidence-file metric-evidence-file--compact metric-evidence-file--generic requirement-plan-evidence" data-state="loading">
        <h3>Requirement-to-plan evidence</h3>
        <span>Loading exact sealed-source review…</span>
        <small>Context changed. Prior preview, proposals, review text, acknowledgements, and decisions are unavailable.</small>
      </section>
    ) : (
      <section aria-label="Review requirement-to-plan evidence" className="metric-evidence-file metric-evidence-file--generic requirement-plan-evidence" data-state="loading">
        <p role="status">Loading the exact content-free {sourceProjectionLabel} contract for the selected context…</p>
      </section>
    );
  }

  if (compact) {
    return (
      <section aria-label="Reviewed requirement-to-plan evidence" className="metric-evidence-file metric-evidence-file--compact metric-evidence-file--generic requirement-plan-evidence" data-state={panelState}>
        <h3 id={headingId}>Requirement-to-plan evidence</h3>
        <span>{!capabilities
          ? `Exact ${sourceProjectionLabel} review unavailable`
          : loading
            ? "Loading exact sealed-source review…"
            : contract === null
              ? "Exact sealed-source review unavailable"
              : undecided.length === 0
                ? "No proposal awaits native decision"
                : `${undecided.length} proposal${undecided.length === 1 ? "" : "s"} awaiting review`}</span>
        <small>{confirmationAvailable
          ? "Open the full dashboard to inspect every local source clause and natively confirm or reject its proposal."
          : "Review is fail-closed: this server/window composition cannot natively review or confirm proposals."}</small>
        {(confirmedCount > 0 || rejectedCount > 0) && <small>{confirmedCount} confirmed · {rejectedCount} rejected for this exact source window</small>}
        {error !== "" && <span className="metric-evidence-file__error" role="alert">{error}</span>}
      </section>
    );
  }

  return (
    <section aria-label="Review requirement-to-plan evidence" className="metric-evidence-file metric-evidence-file--generic requirement-plan-evidence" data-state={panelState}>
      <header>
        <div>
          <h3 id={headingId}>Reviewed requirement-to-plan evidence</h3>
          <span>Canonical file → strict preview → unconfirmed proposal → exact local clause review → native decision</span>
        </div>
        <small id={fileHelpId}>One non-empty canonical .json file, at most 64 KiB. File names, raw bytes, and caught error details are never rendered or persisted by this card; clause text appears only in the expiring native review.</small>
      </header>
      {!capabilities ? (
        <p className="metric-evidence-file__state" role="status">This local runtime does not expose the complete reviewed requirement-plan boundary. No preview, import, review, or decision controls are available.</p>
      ) : loading ? (
        <p aria-live="polite" className="metric-evidence-file__state" role="status">Loading the fresh exact {sourceProjectionLabel} contract, proposal snapshot, and native-presence capability…</p>
      ) : contract === null ? (
        <div className="metric-evidence-file__state metric-evidence-file__state--error">
          <p className="metric-evidence-file__error" role={error === "" ? "status" : "alert"}>{error === "" ? "Exact requirement-plan review is unavailable." : error}</p>
          <button onClick={reloadCurrentContext} type="button">Retry exact source contract</button>
        </div>
      ) : (
        <>
          <div className="requirement-plan-evidence__authority">
            <p>Bound to sealed run <code className="metric-evidence-file__opaque-id">{sourceRunId}</code> for this exact source window and projection <strong>{sourceProjectionVersion.replace("metric-contract-v2-", "")}</strong>.</p>
            <p>Import never sets a metric. Only a separately reviewed, natively confirmed proposal can become eligible for a fresh analysis; confirmation does not prove plan quality, atomic coverage, or task success.</p>
            <p>Every reviewable user request/feedback clause must be classified as active or excluded. One compound active clause remains one opportunity; excluded clauses never enter the metric.</p>
          </div>
          <label className="metric-evidence-file__picker">
            <span>Choose canonical requirement-plan evidence file</span>
            <input
              accept={`.json,application/json,${REQUIREMENT_PLAN_MEDIA_TYPE}`}
              aria-describedby={fileHelpId}
              disabled={busy}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                void chooseFile(file);
              }}
              type="file"
            />
          </label>
          {preview !== null && (
            <div aria-label="Strict local requirement-plan preview" className="metric-evidence-file__preview requirement-plan-evidence__preview" ref={previewRegionRef} role="region" tabIndex={-1}>
              <div>
                <h4>Strict local preview</h4>
                <span><strong>{preview.active_requirement_count} proposed active requirements</strong> · {preview.excluded_user_clause_count} proposed exclusions · {preview.reviewed_user_clause_count} reviewed user clauses · {preview.plan_item_count} included PLAN clauses · {preview.link_count} links</span>
                <small>{preview.linked_active_requirement_count} linked · {preview.not_linked_active_requirement_count} not linked · {preview.pending_active_requirement_count} pending.</small>
                <small>Producer metadata is an ephemeral untrusted preview claim. Only a content-free opaque commitment can persist.</small>
              </div>
              <button disabled={busy || renderedPreviewEpoch === null} onClick={() => {
                if (renderedPreviewEpoch !== null) void importPreview(renderedPreviewEpoch);
              }} type="button">Import as unconfirmed</button>
            </div>
          )}
          <section aria-labelledby={proposalsHeadingId} className="metric-evidence-file__proposals">
            <div className="metric-evidence-file__section-heading">
              <h4 id={proposalsHeadingId}>Proposals awaiting native decision</h4>
              <span>{undecided.length} loaded</span>
            </div>
            {undecided.length === 0 ? (
              <p className="metric-evidence-file__state" role="status">No unconfirmed requirement-plan proposal is bound to this exact sealed source window.</p>
            ) : (
            <ul aria-label="Requirement-plan proposals awaiting native decision">
              {undecided.map((proposal) => {
                const currentPredecessor = proposalCurrent(proposal, contract);
                const proposalReview = review?.proposal_id === proposal.proposal_id && receiptCurrent(review, proposal, contract)
                  ? review
                  : null;
                const clausesByCoordinate = new Map(
                  proposalReview?.candidate_clauses.map((clause) => [coordinateKey(clause), clause]) ?? [],
                );
                return (
                  <li className="metric-evidence-file__review-proposal requirement-plan-evidence__proposal" key={proposal.proposal_id}>
                    <span>
                      <strong className="metric-evidence-file__opaque-id">Content-free proposal {proposal.proposal_id}</strong>
                      <small>{proposalSummary(proposal)}</small>
                      <small className="metric-evidence-file__opaque-id">Producer provenance uses opaque commitment {proposal.producer_receipt.claim_fingerprint}; no raw producer labels persist.</small>
                      {!currentPredecessor && <small>This proposal targets an older confirmation head. It cannot be reviewed or confirmed; native rejection remains available.</small>}
                    </span>
                    <div className="metric-evidence-file__proposal-actions">
                      <button disabled={busy || !confirmationAvailable} onClick={(event) => openDecision(
                        proposal,
                        "reject",
                        event.currentTarget,
                        renderedDecisionEpoch,
                        renderedReviewEpoch,
                        renderedProposalMembershipEpoch,
                      )} type="button">Reject</button>
                      <button disabled={busy || !confirmationAvailable || !currentPredecessor} onClick={(event) => void openReview(
                        proposal,
                        event.currentTarget,
                        renderedDecisionEpoch,
                        renderedReviewEpoch,
                        renderedProposalMembershipEpoch,
                      )} type="button">Open exact local clause review</button>
                    </div>
                    {proposalReview !== null && (
                      <section
                        aria-label={`Exact clause review for proposal ${proposal.proposal_id}`}
                        className="metric-evidence-file__clause-review requirement-plan-evidence__review"
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            closeReview();
                          }
                        }}
                        ref={reviewRef}
                        tabIndex={-1}
                      >
                        <header>
                          <div>
                            <h4>Complete one-shot local clause review</h4>
                            <small>Receipt <code className="metric-evidence-file__opaque-id">{proposalReview.review_receipt_id}</code></small>
                          </div>
                          <button disabled={busy} onClick={closeReview} type="button">Close review</button>
                        </header>
                        <p><strong>Every eligible source clause is shown below.</strong> User clauses show their active/excluded classification; agent PLAN clauses show whether the proposal included or omitted them.</p>
                        <ol>
                          {proposalReview.candidate_clauses.map((clause) => {
                            const key = coordinateKey(clause);
                            const basis = clause.basis_coordinate === null
                              ? null
                              : clausesByCoordinate.get(coordinateKey(clause.basis_coordinate));
                            return (
                              <li key={key}>
                                <article>
                                  <strong>{clause.candidate_kind === "plan" ? "Agent PLAN clause" : "User request/feedback clause"} — <span className="requirement-plan-evidence__coordinate">{coordinateLabel(clause)}</span></strong>
                                  <blockquote className="metric-evidence-file__exact-review-text">{clause.text}</blockquote>
                                  {clause.candidate_kind === "plan" ? (
                                    <p>Proposal membership: <strong>{clause.included_in_proposal ? "included PLAN clause" : "omitted PLAN clause"}</strong>.</p>
                                  ) : clause.classification === "active_requirement" ? (
                                    <dl>
                                      <div><dt>Classification</dt><dd>active requirement — included in the denominator</dd></div>
                                      <div><dt>Disposition</dt><dd>{clause.disposition?.replaceAll("_", " ")}</dd></div>
                                      <div><dt>PLAN links</dt><dd>{clause.linked_plan_coordinates.length === 0
                                        ? "none — explicit empty link set"
                                        : <span className="requirement-plan-evidence__coordinate-list">{clause.linked_plan_coordinates.map((coordinate) => (
                                          <span className="requirement-plan-evidence__coordinate" key={coordinateKey(coordinate)}>{coordinateLabel(coordinate)}</span>
                                        ))}</span>}</dd></div>
                                    </dl>
                                  ) : (
                                    <dl>
                                      <div><dt>Classification</dt><dd>excluded from active-requirement denominator</dd></div>
                                      <div><dt>Exclusion reason</dt><dd>{reasonLabel(clause.exclusion_reason!)}</dd></div>
                                      <div><dt>Basis source clause</dt><dd>{clause.basis_coordinate === null
                                        ? "none — this reason does not use a basis coordinate"
                                        : <span className="requirement-plan-evidence__basis metric-evidence-file__exact-review-text">{coordinateLabel(clause.basis_coordinate)} — “{basis?.text}”</span>}</dd></div>
                                    </dl>
                                  )}
                                </article>
                              </li>
                            );
                          })}
                        </ol>
                        <p className="metric-evidence-file__footnote">One-shot receipt expires <time dateTime={proposalReview.review_receipt_expires_at}>{proposalReview.review_receipt_expires_at}</time>. Closing, refreshing, changing session/run/projection/transport/proposal, errors, or expiry clears this review and its acknowledgement.</p>
                        <label className="requirement-plan-evidence__acknowledgement">
                          <input checked={reviewAcknowledged} disabled={busy} onChange={(event) => {
                            updateAcknowledgement(event.currentTarget.checked);
                          }} type="checkbox" />
                          <span>I reviewed every displayed user and PLAN clause, every active disposition and exact PLAN link, every exclusion reason and exact basis source clause, and every included or omitted PLAN candidate for this one-shot receipt.</span>
                        </label>
                        <button disabled={busy || !confirmationAvailable || !reviewAcknowledged} onClick={(event) => openDecision(
                          proposal,
                          "confirm",
                          event.currentTarget,
                          renderedDecisionEpoch,
                          renderedReviewEpoch,
                          renderedProposalMembershipEpoch,
                        )} type="button">Confirm evidence</button>
                      </section>
                    )}
                    {pendingDecision?.proposalId === proposal.proposal_id && (
                      <div
                        aria-label={`${pendingDecision.decision === "confirm" ? "Confirm" : "Reject"} requirement-plan proposal`}
                        className="metric-evidence-file__decision-confirmation requirement-plan-evidence__decision"
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            cancelDecision();
                          }
                        }}
                        role="group"
                      >
                        <p>{pendingDecision.decision === "confirm"
                          ? "Native confirmation consumes this exact one-shot review receipt. It makes only the reviewed active-requirement classification and dispositions eligible for a fresh sealed analysis of this selected projection; it does not prove plan quality or atomic requirement coverage."
                          : "Native rejection permanently excludes this proposal from metric authority."}</p>
                        <div>
                          <button disabled={busy} onClick={cancelDecision} type="button">Cancel</button>
                          <button disabled={busy || !confirmationAvailable || (pendingDecision.decision === "confirm" && (proposalReview === null || !reviewAcknowledged))} onClick={() => void applyDecision(proposal, pendingDecision)} ref={decisionActionRef} type="button">{pendingDecision.decision === "confirm" ? "Apply native confirmation" : "Apply native rejection"}</button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
            )}
          </section>
          {!confirmationAvailable && (
            <p className="metric-evidence-file__state" role="status">Owned native user presence is unavailable. Proposals remain unconfirmed; strict preview and inert import stay local, but clause review and every decision are disabled.</p>
          )}
          {decided.length > 0 && (
            <section aria-labelledby={decisionsHeadingId} className="requirement-plan-evidence__decisions">
              <div className="metric-evidence-file__section-heading">
                <h4 id={decisionsHeadingId}>Recorded native decisions</h4>
                <span>{confirmedCount} confirmed · {rejectedCount} rejected</span>
              </div>
              <ul aria-label="Recorded requirement-plan native decisions">
                {decided.map((proposal) => (
                  <li data-decision={proposal.status} key={proposal.proposal_id}>
                    <span>
                      <strong>{proposal.status === "confirmed" ? "Confirmed evidence" : "Rejected proposal"}</strong>
                      <code className="metric-evidence-file__opaque-id">{proposal.proposal_id}</code>
                      <small>{proposal.status === "confirmed"
                        ? "Eligible only for a fresh sealed analysis that binds this confirmation; not proof of plan quality."
                        : "Excluded from metric authority."}</small>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {notice !== "" && (
            <p aria-live="polite" className="metric-evidence-file__notice" ref={noticeRef} role="status" tabIndex={-1}>{notice}</p>
          )}
          {error !== "" && <p className="metric-evidence-file__error" role="alert">{error}</p>}
          <p className="metric-evidence-file__footnote">After native confirmation, run a fresh local analysis and verify that its sealed requirement-plan binding names the confirmed proposal. Missing or stale authority remains unknown, never zero.</p>
        </>
      )}
    </section>
  );
}
