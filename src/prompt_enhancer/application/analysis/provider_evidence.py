"""Project persisted content-free provider events into ephemeral metric evidence.

The safe event index deliberately contains no command arguments, output, paths,
diffs, prompts, or snippets.  This adapter keeps that boundary: it constructs an
ephemeral typed-evidence graph from provider-reported kind/status metadata only.
The graph may guide objective metric contracts during one local run, but it is
never itself a persistence record and it never invents requirement links.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ...domain import (
    PSEUDONYM_PATTERN,
    EventKind,
    Provider,
    SafeEvent,
    SafeSession,
    ToolCategory,
)
from ..providers import CapabilityKey, DecoderDescriptor
from .evidence_contracts import (
    ActionEvidence,
    ActionFamily,
    ActionState,
    DecisionEvidence,
    DecisionState,
    EphemeralTypedEvidenceProjection,
    RationaleState,
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    TypedEvidenceProvenance,
    VerificationEvidence,
    VerificationMethod,
    VerificationOutcome,
    validate_projection_descriptor,
)
from .requirement_action_evidence import (
    MAX_REQUIREMENT_ACTION_CANDIDATES,
    REQUIREMENT_ACTION_CANDIDATE_MANIFEST_VERSION,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    requirement_action_candidate_manifest_fingerprint,
)
from .semantic_units import (
    EXTRACTABLE_SEMANTIC_UNIT_KINDS,
    SemanticUnitKind,
    SemanticUnitLifecycle,
    SemanticUnitReconciliation,
)


SAFE_EVENT_EVIDENCE_DECODER_KEY = "safe-event-evidence"
#: Decoder 2 is frozen.  It minted a verification-*task* identity from a
#: generic ``SafeEvent`` identifier, which made every explicit verification
#: event its own single-outcome task and turned ``outcome.first_pass_verification``
#: into a tautology: one task, one outcome, therefore always resolved.  A safe
#: event stream carries no provider task identity, so decoder 3 emits the same
#: verification *receipts* and declares no task denominator at all.
SAFE_EVENT_EVIDENCE_DECODER_VERSION_2 = "2"
SAFE_EVENT_EVIDENCE_DECODER_VERSION_3 = "3"
#: Decoder 4 is task-scoped.  It keeps decoder 3's receipts exactly and adds
#: the one denominator that *is* observable locally: a reviewed task.  When
#: exactly one current accepted task revision contains the session, that
#: revision is the verification task every receipt in the session links to;
#: when none or more than one does, the decoder declares no task family and
#: ``outcome.first_pass_verification`` stays unknown - never a manufactured
#: 1/1 and never a guessed attribution.
SAFE_EVENT_EVIDENCE_DECODER_VERSION_4 = "4"
#: Frozen alias for readers of the r2 composition root.
SAFE_EVENT_EVIDENCE_DECODER_VERSION = SAFE_EVENT_EVIDENCE_DECODER_VERSION_2
#: What current code composes.
SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION = SAFE_EVENT_EVIDENCE_DECODER_VERSION_4
SUPPORTED_SAFE_EVENT_EVIDENCE_DECODER_VERSIONS = (
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_2,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_3,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
)

#: The exact evidence authority the default local composition grants to the
#: current decoder.  Keep this in the application contract rather than hiding
#: an equivalent tuple in ``bootstrap`` so readiness/operability reporting and
#: the actual composed descriptor cannot drift.  A tool/verification event is
#: still not a requirement, hypothesis, or material-claim registry.
CURRENT_SAFE_EVENT_EVIDENCE_CAPABILITIES = frozenset(
    {
        CapabilityKey.TOOL_EVENTS,
        CapabilityKey.VERIFICATION_EVENTS,
        CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
        CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
    }
)


class RequirementActionCandidateManifestOverflowError(ValueError):
    """The exact safe-action set cannot fit in the bounded review contract."""


def derive_requirement_action_candidate_manifest(
    projection: EphemeralTypedEvidenceProjection,
    *,
    source_run_id: str,
    source_window_fingerprint: str,
    safe_events: tuple[SafeEvent, ...],
) -> RequirementActionCandidateManifest:
    """Derive the exact bounded action-review surface from safe event evidence.

    The adapter copies only application-issued pseudonyms, ordering, coarse
    event/tool categories, timing metadata, action family, and
    provider-reported state. Command arguments, output, paths, transcript text,
    and requirement links have no field in the result. A complete candidate
    enumeration requires both a complete source extraction and an explicit
    action-kind declaration; observing zero actions without either authority
    is not an authoritative empty set.
    """

    if PSEUDONYM_PATTERN.fullmatch(source_run_id) is None:
        raise ValueError("source run must be an installation-local pseudonym")
    if PSEUDONYM_PATTERN.fullmatch(source_window_fingerprint) is None:
        raise ValueError("source window must be an installation-local pseudonym")
    actions = tuple(
        record for record in projection.records if isinstance(record, ActionEvidence)
    )
    if len(actions) > MAX_REQUIREMENT_ACTION_CANDIDATES:
        # Never truncate: an incomplete list could turn an unreviewed action
        # into an apparently confirmed empty link.
        raise RequirementActionCandidateManifestOverflowError(
            "requirement-action candidate manifest exceeds its bound"
        )
    event_by_id: dict[str, SafeEvent] = {}
    for event in safe_events:
        if event.session_id != projection.session_id:
            raise ValueError("safe action candidate belongs to another session")
        if event.event_id in event_by_id:
            raise ValueError("safe action candidate source repeats an event")
        event_by_id[event.event_id] = event
    action_events = tuple(
        event
        for event in safe_events
        if event.kind
        in {EventKind.TOOL_START, EventKind.TOOL_END, EventKind.ARTIFACT}
    )
    if {record.source_reference_id for record in actions} != {
        event.event_id for event in action_events
    } or len(actions) != len(action_events):
        raise ValueError("safe action evidence does not exactly cover its event snapshot")
    candidates = []
    for index, record in enumerate(actions):
        event = event_by_id.get(record.source_reference_id)
        if (
            event is None
            or event.kind
            not in {EventKind.TOOL_START, EventKind.TOOL_END, EventKind.ARTIFACT}
            or record.sequence != event.sequence * 4
            or record.family
            is not requirement_action_family_for_tool_category(
                event.tool_category
            )
            or record.state
            is not requirement_action_state_for_event(
                event.kind,
                event.success,
            )
        ):
            raise ValueError("safe action evidence disagrees with its source event")
        candidates.append(
            RequirementActionCandidate(
                candidate_index=index,
                action_id=record.evidence_id,
                source_reference_id=record.source_reference_id,
                sequence=record.sequence,
                event_kind=event.kind,
                tool_category=event.tool_category,
                occurred_at=event.occurred_at,
                duration_ms=event.duration_ms,
                family=record.family,
                state=record.state,
            )
        )
    candidate_tuple = tuple(candidates)
    extraction_complete = projection.provenance.extraction_complete
    enumeration_complete = (
        extraction_complete
        and TypedEvidenceKind.ACTION in projection.declared_kinds
    )
    provisional = RequirementActionCandidateManifest(
        session_id=projection.session_id,
        source_run_id=source_run_id,
        source_window_fingerprint=source_window_fingerprint,
        provenance=projection.provenance,
        extraction_complete=extraction_complete,
        enumeration_complete=enumeration_complete,
        actions=candidate_tuple,
        manifest_fingerprint="0" * 64,
    )
    return provisional.model_copy(
        update={
            "manifest_fingerprint": (
                requirement_action_candidate_manifest_fingerprint(provisional)
            )
        }
    )


class SafeEventEvidenceSource(Protocol):
    """Read an already-pseudonymized local metadata snapshot."""

    def get_session(self, session_id: str) -> SafeSession | None: ...

    def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]: ...


class SafeEventEvidenceIdFactory(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class ReviewedTaskRevision(Protocol):
    """The two identity fields decoder 4 reads from an accepted task revision."""

    @property
    def task_id(self) -> str: ...

    @property
    def revision(self) -> int: ...


class ReviewedTaskSource(Protocol):
    """Current accepted task revisions that contain a session (read-only)."""

    def list_current_revisions_for_session(
        self, session_id: str
    ) -> tuple[ReviewedTaskRevision, ...]: ...


def requirement_action_family_for_tool_category(
    category: ToolCategory | None,
) -> ActionFamily:
    if category is ToolCategory.FILE_WRITE:
        return ActionFamily.FILE_CHANGE
    if category in {ToolCategory.FILE_READ, ToolCategory.SEARCH}:
        return ActionFamily.REVIEW
    if category in {ToolCategory.COMMAND, ToolCategory.TEST, ToolCategory.BUILD}:
        return ActionFamily.COMMAND
    if category is None or category is ToolCategory.UNKNOWN:
        return ActionFamily.OTHER_DOCUMENTED
    return ActionFamily.TOOL


def requirement_action_state_for_event(
    event_kind: EventKind,
    success: bool | None,
) -> ActionState:
    if event_kind is EventKind.TOOL_START:
        return ActionState.STARTED
    if success is True:
        return ActionState.COMPLETED
    if success is False:
        return ActionState.FAILED
    return ActionState.UNKNOWN


def _verification_method(category: ToolCategory | None) -> VerificationMethod:
    if category is ToolCategory.TEST:
        return VerificationMethod.TEST
    if category is ToolCategory.BUILD:
        return VerificationMethod.BUILD
    if category in {ToolCategory.FILE_READ, ToolCategory.SEARCH}:
        return VerificationMethod.ARTIFACT_INSPECTION
    return VerificationMethod.OTHER_DOCUMENTED


def _verification_outcome(event: SafeEvent) -> VerificationOutcome:
    if event.success is True:
        return VerificationOutcome.PASSED
    if event.success is False:
        return VerificationOutcome.FAILED
    return VerificationOutcome.UNKNOWN


class SafeEventTypedEvidenceProjector:
    """Create one bounded, content-free evidence projection for a local run.

    The decoder version comes from the descriptor the composition root selected,
    and it is the only thing that separates the two behaviours.  Decoder 2 is
    reproduced exactly so an r2 projection stays byte-comparable; decoder 3 is
    what current code composes.
    """

    def __init__(
        self,
        source: SafeEventEvidenceSource,
        identifiers: SafeEventEvidenceIdFactory,
        descriptor: DecoderDescriptor,
        *,
        tasks: ReviewedTaskSource | None = None,
        descriptors: Mapping[Provider, DecoderDescriptor] | None = None,
        source_descriptors: Mapping[
            tuple[Provider, str, str], DecoderDescriptor
        ]
        | None = None,
    ) -> None:
        self._source = source
        self._identifiers = identifiers
        self._tasks = tasks
        if not isinstance(descriptor, DecoderDescriptor):
            raise ValueError("typed evidence requires a trusted decoder descriptor")
        if descriptor.decoder_key != SAFE_EVENT_EVIDENCE_DECODER_KEY:
            raise ValueError("typed evidence descriptor names another decoder")
        if (
            descriptor.decoder_version
            not in SUPPORTED_SAFE_EVENT_EVIDENCE_DECODER_VERSIONS
        ):
            raise ValueError("typed evidence decoder version is unsupported")
        # Optional per-provider descriptors (same decoder key and version,
        # different adapter/schema identities); ``descriptor`` stays the default.
        self._descriptors: dict[Provider, DecoderDescriptor] = {}
        for provider, candidate in (descriptors or {}).items():
            if not isinstance(candidate, DecoderDescriptor):
                raise ValueError("typed evidence requires a trusted decoder descriptor")
            if (
                candidate.decoder_key != SAFE_EVENT_EVIDENCE_DECODER_KEY
                or candidate.decoder_version != descriptor.decoder_version
                or candidate.provider.key != provider.value
            ):
                raise ValueError("typed evidence provider descriptor does not match the decoder")
            self._descriptors[provider] = candidate
        self._source_descriptors: dict[
            tuple[Provider, str, str], DecoderDescriptor
        ] = {}
        for identity, candidate in (source_descriptors or {}).items():
            if (
                not isinstance(identity, tuple)
                or len(identity) != 3
                or not isinstance(identity[0], Provider)
                or not isinstance(identity[1], str)
                or not isinstance(identity[2], str)
                or not isinstance(candidate, DecoderDescriptor)
            ):
                raise ValueError("typed evidence source descriptor identity is invalid")
            provider, adapter_version, source_schema_version = identity
            if (
                candidate.decoder_key != SAFE_EVENT_EVIDENCE_DECODER_KEY
                or candidate.decoder_version != descriptor.decoder_version
                or candidate.provider.key != provider.value
                or candidate.adapter_version != adapter_version
                or candidate.canonical_schema_version != source_schema_version
            ):
                raise ValueError(
                    "typed evidence source descriptor does not match its provenance"
                )
            self._source_descriptors[identity] = candidate
        self._descriptor = descriptor

    def descriptor_for(
        self,
        provider: Provider,
        *,
        adapter_version: str | None = None,
        source_schema_version: str | None = None,
    ) -> DecoderDescriptor:
        """Resolve a provider default or one exact adapter/schema provenance."""

        if (adapter_version is None) != (source_schema_version is None):
            raise ValueError("typed evidence source provenance must be complete")
        if adapter_version is not None and source_schema_version is not None:
            exact = self._source_descriptors.get(
                (provider, adapter_version, source_schema_version)
            )
            if exact is not None:
                return exact
            fallback = self._descriptors.get(provider, self._descriptor)
            if (
                fallback.provider.key == provider.value
                and fallback.adapter_version == adapter_version
                and fallback.canonical_schema_version == source_schema_version
            ):
                return fallback
            raise ValueError("typed evidence source provenance is not registered")
        return self._descriptors.get(provider, self._descriptor)

    def descriptor_for_projection(
        self, projection: EphemeralTypedEvidenceProjection
    ) -> DecoderDescriptor:
        """Resolve only the exact descriptor stamped into a built projection."""

        if not isinstance(projection, EphemeralTypedEvidenceProjection):
            raise ValueError("typed evidence projection contract is invalid")
        provenance = projection.provenance
        descriptor = self.descriptor_for(
            provenance.provider,
            adapter_version=provenance.adapter_version,
            source_schema_version=provenance.source_schema_version,
        )
        validate_projection_descriptor(projection, descriptor)
        return descriptor

    @property
    def _emits_verification_task_identity(self) -> bool:
        """Whether this decoder may turn an event identity into a task identity.

        Only decoder 2 may, and only because its rows already exist.  A generic
        operational event says a check *ran*; it does not say which verification
        task it belonged to, so decoder 3 refuses to enumerate a denominator it
        cannot observe and ``outcome.first_pass_verification`` stays an
        actionable unknown instead of a manufactured 1/1.
        """

        return (
            self._descriptor.decoder_version
            == SAFE_EVENT_EVIDENCE_DECODER_VERSION_2
        )

    @property
    def _task_scoped(self) -> bool:
        """Decoder 4: the denominator is a reviewed task, not an event."""

        return (
            self._descriptor.decoder_version
            == SAFE_EVENT_EVIDENCE_DECODER_VERSION_4
        )

    def _reviewed_task_reference(self, session_id: str) -> str | None:
        """The one current accepted revision containing the session, or None.

        None covers every case the decoder refuses to guess: no task source,
        no accepted revision, more than one current revision claiming the
        session, or a source failure.
        """

        if not self._task_scoped or self._tasks is None:
            return None
        try:
            revisions = self._tasks.list_current_revisions_for_session(session_id)
        except Exception:
            return None
        if len(revisions) != 1:
            return None
        revision = revisions[0]
        return self._identifiers.fingerprint(
            "typed-reviewed-task-evidence-v4",
            (session_id, str(revision.task_id), str(int(revision.revision))),
        )

    @property
    def descriptor(self) -> DecoderDescriptor:
        """The composition-root-selected authority for this projection."""

        return self._descriptor

    def project(
        self,
        *,
        provider: Provider,
        session_id: str,
    ) -> EphemeralTypedEvidenceProjection | None:
        session = self._source.get_session(session_id)
        if session is None or session.provider is not provider:
            return None
        descriptor = self.descriptor_for(
            provider,
            adapter_version=session.adapter_version,
            source_schema_version=session.source_schema_version,
        )
        events = tuple(
            sorted(
                self._source.get_session_events(session_id),
                key=lambda item: (item.sequence, item.event_id),
            )
        )
        records: list[ActionEvidence | DecisionEvidence | VerificationEvidence] = []
        declared_kinds = frozenset(
            kind
            for kind, capability in (
                (TypedEvidenceKind.ACTION, CapabilityKey.TOOL_EVENTS),
                (TypedEvidenceKind.DECISION, CapabilityKey.DECISION_EVENTS),
                (TypedEvidenceKind.VERIFICATION, CapabilityKey.VERIFICATION_EVENTS),
            )
            if capability in descriptor.capabilities
        )
        # A verification *task* denominator needs three separate authorities:
        # the outcome capability, the enumeration capability, and the link
        # capability.  Absent any of them the projector emits verification
        # outcomes with no task identity, which keeps first-pass unknown
        # instead of inventing a denominator.  The other three opportunity
        # families are never declared here: a safe-event stream contains no
        # requirements, hypotheses, or material claims, so this decoder cannot
        # enumerate them.  ``bind_semantic_unit_opportunities`` is the only
        # place a semantic-unit denominator may enter this projection.
        task_capabilities_declared = (
            TypedEvidenceKind.VERIFICATION in declared_kinds
            and CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES
            in descriptor.capabilities
            and CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS
            in descriptor.capabilities
        )
        verification_tasks_authorized = (
            self._emits_verification_task_identity and task_capabilities_declared
        )
        # Decoder 4: one reviewed task, if exactly one current accepted
        # revision contains this session.  Every verification receipt in the
        # session then links to it; otherwise no task family is declared.
        reviewed_task = (
            self._reviewed_task_reference(session_id)
            if task_capabilities_declared
            else None
        )
        declared_opportunity_kinds = (
            frozenset({TypedEvidenceOpportunityKind.VERIFICATION_TASK})
            if verification_tasks_authorized or reviewed_task is not None
            else frozenset()
        )
        verification_tasks: list[str] = [reviewed_task] if reviewed_task else []

        for event in events:
            if event.session_id != session_id:
                raise ValueError("safe event belongs to another session")
            base_sequence = event.sequence * 4
            if event.kind in {
                EventKind.TOOL_START,
                EventKind.TOOL_END,
                EventKind.ARTIFACT,
            }:
                # Every safe-event kind this decoder reads is an action, so a
                # missing tool capability is a composition-root error, not a
                # partial authority: there is no other evidence to preserve.
                if TypedEvidenceKind.ACTION not in declared_kinds:
                    raise ValueError("tool evidence capability is not authorized")
                records.append(
                    ActionEvidence(
                        evidence_id=self._evidence_id(
                            session_id, event.event_id, "action"
                        ),
                        sequence=base_sequence,
                        source_reference_id=event.event_id,
                        family=requirement_action_family_for_tool_category(
                            event.tool_category
                        ),
                        state=requirement_action_state_for_event(
                            event.kind,
                            event.success,
                        ),
                    )
                )
            if event.kind is EventKind.DECISION:
                # An undeclared decision capability withholds this one record.
                # Raising here would destroy the authorized action evidence of
                # the whole session because one event kind was out of scope.
                if TypedEvidenceKind.DECISION in declared_kinds:
                    records.append(
                        DecisionEvidence(
                            evidence_id=self._evidence_id(
                                session_id, event.event_id, "decision"
                            ),
                            sequence=base_sequence + 1,
                            source_reference_id=event.event_id,
                            state=(
                                DecisionState.ACCEPTED
                                if event.success is True
                                else DecisionState.REJECTED
                                if event.success is False
                                else DecisionState.UNKNOWN
                            ),
                            rationale_state=RationaleState.UNKNOWN,
                        )
                    )
            explicit_verification = event.kind is EventKind.VERIFICATION
            if explicit_verification or (
                event.kind is EventKind.TOOL_END
                and event.tool_category in {ToolCategory.TEST, ToolCategory.BUILD}
            ):
                # A documented tool event may be authoritative for ACTION but
                # not for VERIFICATION. Keep the declared action and omit the
                # stronger evidence kind rather than failing the entire local
                # projection or upgrading the decoder's capability.
                if TypedEvidenceKind.VERIFICATION in declared_kinds:
                    # Decoder 2 historically minted a task identity only for
                    # an explicit provider verification event.  Decoder 3
                    # mints none: even an explicit event identifies a receipt,
                    # not the provider-owned verification task denominator.
                    # A TOOL_END categorised as test or build is weaker still.
                    task_ids: tuple[str, ...] = ()
                    if explicit_verification and verification_tasks_authorized:
                        task_id = self._evidence_id(
                            session_id, event.event_id, "verification-task"
                        )
                        verification_tasks.append(task_id)
                        task_ids = (task_id,)
                    elif reviewed_task is not None:
                        task_ids = (reviewed_task,)
                    records.append(
                        VerificationEvidence(
                            evidence_id=self._evidence_id(
                                session_id, event.event_id, "verification"
                            ),
                            sequence=base_sequence + 2,
                            source_reference_id=event.event_id,
                            method=_verification_method(event.tool_category),
                            outcome=_verification_outcome(event),
                            receipt_reference_ids=(event.event_id,),
                            verification_task_reference_ids=task_ids,
                        )
                    )

        projection = EphemeralTypedEvidenceProjection(
            session_id=session_id,
            provenance=TypedEvidenceProvenance(
                provider=provider,
                provider_version=session.provider_version,
                adapter_version=session.adapter_version,
                decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
                decoder_version=descriptor.decoder_version,
                source_schema_version=session.source_schema_version,
                extraction_complete=session.events_complete,
            ),
            declared_kinds=declared_kinds,
            declared_opportunity_kinds=declared_opportunity_kinds,
            eligible_verification_task_reference_ids=tuple(verification_tasks),
            records=tuple(sorted(records, key=lambda item: item.sequence)),
        )
        validate_projection_descriptor(projection, descriptor)
        return projection

    def requirement_action_candidate_manifest(
        self,
        *,
        provider: Provider,
        session_id: str,
        source_run_id: str,
        source_window_fingerprint: str,
        projection: EphemeralTypedEvidenceProjection | None = None,
    ) -> RequirementActionCandidateManifest | None:
        """Issue the complete content-free native-review candidate manifest.

        The typed evidence projection deliberately omits timestamps and other
        event metadata that are unnecessary for metric calculation.  A person
        reviewing several opaque actions still needs to distinguish them, so
        this method cross-binds every action receipt to the exact safe event
        snapshot and copies only its already-persistable metadata.  Any growth
        or mismatch between the two reads fails closed; callers may retry the
        current source run instead of reviewing a mixed snapshot.
        """

        projection = (
            projection
            if projection is not None
            else self.project(provider=provider, session_id=session_id)
        )
        if projection is None:
            return None
        if projection.session_id != session_id:
            raise ValueError("safe action projection belongs to another session")
        if projection.provenance.provider is not provider:
            raise ValueError("safe action projection belongs to another provider")
        events = tuple(
            sorted(
                self._source.get_session_events(session_id),
                key=lambda item: (item.sequence, item.event_id),
            )
        )
        return derive_requirement_action_candidate_manifest(
            projection,
            source_run_id=source_run_id,
            source_window_fingerprint=source_window_fingerprint,
            safe_events=events,
        )

    def _evidence_id(
        self,
        session_id: str,
        event_id: str,
        kind: str,
    ) -> str:
        # The namespace is frozen at v2 on purpose: the evidence identity of a
        # given event must not change because the decoder learned to withhold a
        # denominator.  Only the *set* of emitted records differs.
        return self._identifiers.fingerprint(
            "typed-safe-event-evidence-v2",
            (session_id, event_id, kind),
        )


def _bound_family(
    reconciliation: SemanticUnitReconciliation,
    kind: SemanticUnitKind,
    *,
    lifecycles: frozenset[SemanticUnitLifecycle] | None = None,
    excluded_lifecycles: frozenset[SemanticUnitLifecycle] = frozenset(),
) -> frozenset[str] | None:
    """Return the exact unit set for one family, or ``None`` if unprovable.

    An empty set is only returned when the reconciler can actually own this
    kind.  Otherwise the family stays undeclared: zero heads of a kind that is
    never extracted proves nothing, and declaring it would turn "we cannot see
    this" into a measured "there was no opportunity".
    """

    observed = frozenset(
        item.unit_id
        for item in reconciliation.heads
        if item.kind is kind
        and item.lifecycle not in excluded_lifecycles
        and (lifecycles is None or item.lifecycle in lifecycles)
    )
    if observed:
        return observed
    return frozenset() if kind in EXTRACTABLE_SEMANTIC_UNIT_KINDS else None


def bind_semantic_unit_opportunities(
    projection: EphemeralTypedEvidenceProjection | None,
    reconciliation: SemanticUnitReconciliation | None,
    descriptor: DecoderDescriptor | None = None,
) -> EphemeralTypedEvidenceProjection | None:
    """Bind exact semantic-unit denominators without persisting their links.

    Only a complete reconciliation may enlarge a denominator family, and only
    when ``descriptor`` declares both the enumeration and the link capability
    for that family: the bound set is carried inside a projection stamped with
    that decoder's provenance, so the decoder must be authorized to hold it.
    Active requirement units define the requirement denominator. Hypotheses are
    included only after closure; an open/right-censored episode must remain
    pending rather than become a measured failure.
    """

    if projection is None or reconciliation is None:
        return projection
    if (
        projection.provenance.provider is not reconciliation.provider
        or projection.session_id != reconciliation.session_id
    ):
        raise ValueError("typed evidence and semantic units use different providers")
    if not reconciliation.source_complete:
        return projection

    capabilities = frozenset(() if descriptor is None else descriptor.capabilities)
    declared = set(projection.declared_opportunity_kinds)
    eligible = {
        TypedEvidenceOpportunityKind.REQUIREMENT: frozenset(
            projection.eligible_requirement_reference_ids
        ),
        TypedEvidenceOpportunityKind.HYPOTHESIS: frozenset(
            projection.eligible_hypothesis_reference_ids
        ),
    }
    bindings = (
        (
            TypedEvidenceOpportunityKind.REQUIREMENT,
            CapabilityKey.REQUIREMENT_OPPORTUNITIES,
            CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
            _bound_family(
                reconciliation,
                SemanticUnitKind.REQUIREMENT,
                excluded_lifecycles=frozenset({SemanticUnitLifecycle.SUPERSEDED}),
            ),
        ),
        (
            TypedEvidenceOpportunityKind.HYPOTHESIS,
            CapabilityKey.HYPOTHESIS_OPPORTUNITIES,
            CapabilityKey.HYPOTHESIS_EVIDENCE_LINKS,
            _bound_family(
                reconciliation,
                SemanticUnitKind.HYPOTHESIS,
                lifecycles=frozenset({SemanticUnitLifecycle.CLOSED}),
            ),
        ),
    )
    for opportunity_kind, enumeration, links, bound in bindings:
        if bound is None or not {enumeration, links} <= capabilities:
            continue
        declared.add(opportunity_kind)
        eligible[opportunity_kind] |= bound

    payload = projection.model_dump()
    payload.update(
        {
            "declared_opportunity_kinds": frozenset(declared),
            "eligible_requirement_reference_ids": tuple(
                sorted(eligible[TypedEvidenceOpportunityKind.REQUIREMENT])
            ),
            "eligible_hypothesis_reference_ids": tuple(
                sorted(eligible[TypedEvidenceOpportunityKind.HYPOTHESIS])
            ),
            "records": projection.records,
        }
    )
    return EphemeralTypedEvidenceProjection.model_validate(payload)


__all__ = [
    "CURRENT_SAFE_EVENT_EVIDENCE_CAPABILITIES",
    "REQUIREMENT_ACTION_CANDIDATE_MANIFEST_VERSION",
    "RequirementActionCandidateManifestOverflowError",
    "SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION",
    "SAFE_EVENT_EVIDENCE_DECODER_KEY",
    "SAFE_EVENT_EVIDENCE_DECODER_VERSION",
    "SAFE_EVENT_EVIDENCE_DECODER_VERSION_2",
    "SAFE_EVENT_EVIDENCE_DECODER_VERSION_3",
    "SUPPORTED_SAFE_EVENT_EVIDENCE_DECODER_VERSIONS",
    "SAFE_EVENT_EVIDENCE_DECODER_VERSION_4",
    "ReviewedTaskRevision",
    "ReviewedTaskSource",
    "SafeEventEvidenceIdFactory",
    "SafeEventEvidenceSource",
    "SafeEventTypedEvidenceProjector",
    "bind_semantic_unit_opportunities",
    "derive_requirement_action_candidate_manifest",
    "requirement_action_family_for_tool_category",
    "requirement_action_candidate_manifest_fingerprint",
    "requirement_action_state_for_event",
]
