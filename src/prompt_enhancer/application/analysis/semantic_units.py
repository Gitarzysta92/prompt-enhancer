"""Provider-neutral semantic-unit reconciliation for metric denominators.

The persistence-facing contracts in this module are deliberately content-free.
They contain only closed enums, integers, and installation-local keyed digests.
Redacted message text is available, when explicitly requested, through a
separate ephemeral packet whose secret field is excluded from serialization.

The built-in extractor is intentionally conservative.  It creates units only
when a documented ``P1TextAnalysisInput`` role/kind pair establishes the unit
type.  In particular, words in a message are never used to invent requirements,
constraints, hypotheses, ambiguity episodes, or other semantic subclasses.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    Provider,
    StrictModel,
)
from .text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
)


SEMANTIC_UNIT_SCHEMA_VERSION = 1
SEMANTIC_UNIT_CONTRACT_VERSION = "semantic-units.v1"
SEMANTIC_UNIT_KIND_VERSION = 1
MAX_SEMANTIC_UNIT_RECEIPTS = 20_000
MAX_SEMANTIC_UNIT_SOURCES = 64


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("semantic-unit identities must be HMAC pseudonyms")
    return value


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("semantic-unit versions must use safe identifier characters")
    return value


def _unique_pseudonyms(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(_pseudonym(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("semantic-unit references cannot contain duplicates")
    return normalized


class SemanticUnitKind(StrEnum):
    """Versioned semantic opportunities used by the 20 metric contracts."""

    REQUEST_REVISION = "request_revision"
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    DELIVERABLE = "deliverable"
    AMBIGUITY = "ambiguity"
    CLARIFICATION = "clarification"
    SCOPE_CHANGE = "scope_change"
    FEEDBACK = "feedback"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    OPEN_LOOP = "open_loop"
    ACTION = "action"
    VERIFICATION = "verification"


class SemanticUnitLifecycle(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SUPERSEDED = "superseded"
    RIGHT_CENSORED = "right_censored"


class SemanticUnitExtractionBasis(StrEnum):
    DOCUMENTED_MESSAGE_KIND = "documented_message_kind"
    EXPLICIT_SUPERSESSION = "explicit_supersession"
    TYPED_PROVIDER_EVENT = "typed_provider_event"
    VERSIONED_LOCAL_CLASSIFIER = "versioned_local_classifier"


class FeedbackReworkClass(StrEnum):
    """Mutually exclusive feedback classification; unknown is not a failure."""

    AVOIDABLE_CORRECTION = "avoidable_correction"
    NEW_INFORMATION = "new_information"
    SCOPE_EVOLUTION = "scope_evolution"
    PREFERENCE_CHANGE = "preference_change"
    UNKNOWN = "unknown"


class SemanticUnitIdFactory(Protocol):
    """Installation-local keyed identity boundary."""

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        """Key transient text without returning or persisting plaintext."""
        ...


class SemanticUnitReceipt(StrictModel):
    """One immutable, append-only lifecycle revision for a semantic unit.

    ``owner_source_digest`` is a scalar and must occur exactly once in the
    unique source set.  This is the exactly-one-owner invariant that prevents
    overlapping chunks from creating additional denominator opportunities.
    """

    schema_version: Literal[SEMANTIC_UNIT_SCHEMA_VERSION] = (
        SEMANTIC_UNIT_SCHEMA_VERSION
    )
    contract_version: str = SEMANTIC_UNIT_CONTRACT_VERSION
    unit_kind_version: Literal[SEMANTIC_UNIT_KIND_VERSION] = (
        SEMANTIC_UNIT_KIND_VERSION
    )
    provider: Provider
    session_id: str
    receipt_id: str
    unit_id: str
    unit_digest: str
    revision: int = Field(ge=1)
    previous_receipt_id: str | None = None
    kind: SemanticUnitKind
    lifecycle: SemanticUnitLifecycle
    extraction_basis: SemanticUnitExtractionBasis
    owner_source_digest: str
    source_digests: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_UNIT_SOURCES,
    )
    source_version_digest: str
    first_sequence: int = Field(ge=0)
    closed_at_sequence: int | None = Field(default=None, ge=0)
    superseded_by_source_digest: str | None = None
    superseded_by_unit_id: str | None = None
    owner_role: TextRole | None = None
    owner_message_kind: TextMessageKind | None = None
    rework_class: FeedbackReworkClass | None = None

    _validate_contract_version = field_validator("contract_version")(_safe_version)
    _validate_session_id = field_validator("session_id")(_pseudonym)
    _validate_required_digests = field_validator(
        "receipt_id",
        "unit_id",
        "unit_digest",
        "owner_source_digest",
        "source_version_digest",
    )(_pseudonym)
    _validate_optional_digests = field_validator(
        "previous_receipt_id",
        "superseded_by_source_digest",
        "superseded_by_unit_id",
    )(lambda value: None if value is None else _pseudonym(value))
    _validate_source_digests = field_validator("source_digests")(
        _unique_pseudonyms
    )

    @model_validator(mode="after")
    def validate_receipt(self) -> SemanticUnitReceipt:
        if self.source_digests.count(self.owner_source_digest) != 1:
            raise ValueError("a semantic unit must have exactly one owner")
        if (self.revision == 1) != (self.previous_receipt_id is None):
            raise ValueError("only a first semantic-unit revision omits its predecessor")
        if self.previous_receipt_id == self.receipt_id:
            raise ValueError("a semantic-unit receipt cannot precede itself")

        if self.lifecycle is SemanticUnitLifecycle.SUPERSEDED:
            if (
                self.closed_at_sequence is None
                or self.superseded_by_source_digest is None
            ):
                raise ValueError(
                    "superseded units require a closing sequence and source"
                )
            if self.superseded_by_unit_id == self.unit_id:
                raise ValueError("a semantic unit cannot supersede itself")
        elif self.lifecycle is SemanticUnitLifecycle.CLOSED:
            if self.closed_at_sequence is None:
                raise ValueError("closed units require a closing sequence")
            if (
                self.superseded_by_source_digest is not None
                or self.superseded_by_unit_id is not None
            ):
                raise ValueError("closed units cannot claim supersession")
        else:
            if self.closed_at_sequence is not None:
                raise ValueError("open or censored units cannot claim closure")
            if (
                self.superseded_by_source_digest is not None
                or self.superseded_by_unit_id is not None
            ):
                raise ValueError("open or censored units cannot claim supersession")

        if (
            self.closed_at_sequence is not None
            and self.closed_at_sequence < self.first_sequence
        ):
            raise ValueError("semantic-unit closure cannot precede its owner")
        if self.kind is SemanticUnitKind.FEEDBACK:
            if self.rework_class is None:
                raise ValueError("feedback units require an explicit rework class")
        elif self.rework_class is not None:
            raise ValueError("only feedback units may carry a rework class")
        if (
            self.extraction_basis
            is SemanticUnitExtractionBasis.DOCUMENTED_MESSAGE_KIND
            and (self.owner_role is None or self.owner_message_kind is None)
        ):
            raise ValueError("message-kind extraction requires role and kind provenance")
        return self


class EphemeralSemanticUnitEvidencePacket(StrictModel):
    """Optional local evidence for factor models; never persistence material.

    The secret is excluded even from explicit ``model_dump`` and JSON calls.
    Consumers must deliberately call ``get_secret_value`` inside the bounded
    local analysis lifetime.
    """

    unit_id: str
    owner_source_digest: str
    language: TextLanguage
    text: SecretStr = Field(
        repr=False,
        exclude=True,
        min_length=1,
        max_length=32_000,
    )

    _validate_ids = field_validator("unit_id", "owner_source_digest")(_pseudonym)

    @field_validator("text")
    @classmethod
    def reject_nul(cls, value: SecretStr) -> SecretStr:
        if "\x00" in value.get_secret_value():
            raise ValueError("semantic-unit evidence cannot contain NUL")
        return value


class SemanticUnitReconciliation(StrictModel):
    """Deterministic append set and latest heads for a bounded source view."""

    schema_version: Literal[SEMANTIC_UNIT_SCHEMA_VERSION] = (
        SEMANTIC_UNIT_SCHEMA_VERSION
    )
    contract_version: str = SEMANTIC_UNIT_CONTRACT_VERSION
    provider: Provider
    session_id: str
    analysis_window_fingerprint: str
    source_complete: bool
    reconciliation_id: str
    heads: tuple[SemanticUnitReceipt, ...] = Field(
        max_length=MAX_SEMANTIC_UNIT_RECEIPTS
    )
    appended: tuple[SemanticUnitReceipt, ...] = Field(
        max_length=MAX_SEMANTIC_UNIT_RECEIPTS
    )
    unchanged_receipt_ids: tuple[str, ...]
    retained_unobserved_unit_count: int = Field(ge=0)

    _validate_contract_version = field_validator("contract_version")(_safe_version)
    _validate_ids = field_validator(
        "session_id", "analysis_window_fingerprint", "reconciliation_id"
    )(_pseudonym)
    _validate_unchanged = field_validator("unchanged_receipt_ids")(
        _unique_pseudonyms
    )

    @model_validator(mode="after")
    def validate_reconciliation(self) -> SemanticUnitReconciliation:
        expected_order = tuple(
            sorted(
                self.heads,
                key=lambda item: (item.first_sequence, item.kind.value, item.unit_id),
            )
        )
        if self.heads != expected_order:
            raise ValueError("semantic-unit heads must use deterministic order")
        unit_ids = tuple(item.unit_id for item in self.heads)
        if len(set(unit_ids)) != len(unit_ids):
            raise ValueError("semantic-unit heads cannot repeat a unit")
        receipt_ids = {item.receipt_id for item in self.heads}
        appended_ids = {item.receipt_id for item in self.appended}
        unchanged_ids = set(self.unchanged_receipt_ids)
        if len(appended_ids) != len(self.appended):
            raise ValueError("appended semantic-unit receipts must be unique")
        if not appended_ids.issubset(receipt_ids):
            raise ValueError("every appended receipt must be a current head")
        if appended_ids & unchanged_ids or appended_ids | unchanged_ids != receipt_ids:
            raise ValueError("every head must be exactly appended or unchanged")
        expected_appended = tuple(
            item for item in self.heads if item.receipt_id in appended_ids
        )
        if self.appended != expected_appended:
            raise ValueError("appended semantic-unit receipts must follow head order")
        if self.unchanged_receipt_ids != tuple(sorted(self.unchanged_receipt_ids)):
            raise ValueError("unchanged semantic-unit receipts must use canonical order")
        if self.retained_unobserved_unit_count > len(self.heads):
            raise ValueError("retained unit count exceeds the current heads")
        if any(
            item.provider is not self.provider or item.session_id != self.session_id
            for item in self.heads
        ):
            raise ValueError("semantic-unit heads must belong to one session")
        return self


class SemanticUnitProjection(StrictModel):
    """Persistable reconciliation plus optionally retained ephemeral evidence."""

    reconciliation: SemanticUnitReconciliation
    evidence_packets: tuple[EphemeralSemanticUnitEvidencePacket, ...] = Field(
        default=(),
        repr=False,
        exclude=True,
    )

    @model_validator(mode="after")
    def validate_packets(self) -> SemanticUnitProjection:
        unit_ids = {item.unit_id for item in self.reconciliation.heads}
        packet_ids = tuple(item.unit_id for item in self.evidence_packets)
        if len(set(packet_ids)) != len(packet_ids):
            raise ValueError("ephemeral semantic-unit packets cannot repeat a unit")
        if not set(packet_ids).issubset(unit_ids):
            raise ValueError("ephemeral packets must reference current unit heads")
        return self


class _UnitDraft(StrictModel):
    provider: Provider
    session_id: str
    unit_id: str
    kind: SemanticUnitKind
    lifecycle: SemanticUnitLifecycle
    extraction_basis: SemanticUnitExtractionBasis
    owner_source_digest: str
    source_digests: tuple[str, ...]
    source_version_digest: str
    first_sequence: int
    closed_at_sequence: int | None
    superseded_by_source_digest: str | None
    superseded_by_unit_id: str | None
    owner_role: TextRole | None
    owner_message_kind: TextMessageKind | None
    rework_class: FeedbackReworkClass | None


_DOCUMENTED_UNIT_KIND = {
    (TextRole.USER, TextMessageKind.REQUEST): SemanticUnitKind.REQUEST_REVISION,
    (TextRole.USER, TextMessageKind.FEEDBACK): SemanticUnitKind.FEEDBACK,
    (TextRole.AGENT, TextMessageKind.ACTION): SemanticUnitKind.ACTION,
    (TextRole.AGENT, TextMessageKind.DECISION): SemanticUnitKind.DECISION,
    (TextRole.AGENT, TextMessageKind.VERIFICATION): SemanticUnitKind.VERIFICATION,
}

_OPEN_ENDED_KINDS = {
    SemanticUnitKind.REQUEST_REVISION,
    SemanticUnitKind.AMBIGUITY,
    SemanticUnitKind.HYPOTHESIS,
    SemanticUnitKind.OPEN_LOOP,
}

#: Kinds the conservative built-in extractor can actually own.  A metric whose
#: opportunity family is absent here must abstain: an empty head set proves
#: nothing about a kind that is never extracted, so it can never mean zero or
#: not-applicable.
EXTRACTABLE_SEMANTIC_UNIT_KINDS = frozenset(_DOCUMENTED_UNIT_KIND.values())


def semantic_source_digest(
    id_factory: SemanticUnitIdFactory,
    *,
    provider: Provider,
    session_id: str,
    message_id: str,
) -> str:
    """Recompute the keyed owner digest for one message.

    Consumers need this to join a persisted head back to the ephemeral message
    it owns without the receipt ever carrying a reversible reference.
    """

    return id_factory.fingerprint(
        "semantic-source-v1",
        (provider.value, session_id, message_id),
    )


class SemanticUnitReconciler:
    """Extract conservative units and compute an append-idempotent receipt set."""

    def __init__(self, id_factory: SemanticUnitIdFactory) -> None:
        self._ids = id_factory

    def reconcile(
        self,
        context: P1TextAnalysisInput,
        *,
        prior_receipts: tuple[SemanticUnitReceipt, ...] = (),
        include_ephemeral_evidence: bool = False,
    ) -> SemanticUnitProjection:
        prior_heads = self._prior_heads(context, prior_receipts)
        drafts, evidence_by_unit = self._extract(context)
        desired_by_unit = {draft.unit_id: draft for draft in drafts}

        appended: list[SemanticUnitReceipt] = []
        heads: dict[str, SemanticUnitReceipt] = dict(prior_heads)
        unchanged: set[str] = set()

        for draft in drafts:
            previous = prior_heads.get(draft.unit_id)
            candidate_digest = self._unit_digest(draft)
            if previous is not None and self._matches(
                previous, draft, candidate_digest
            ):
                heads[draft.unit_id] = previous
                unchanged.add(previous.receipt_id)
                continue
            revision = 1 if previous is None else previous.revision + 1
            previous_receipt_id = None if previous is None else previous.receipt_id
            receipt_id = self._ids.fingerprint(
                "semantic-unit-receipt-v1",
                (
                    draft.unit_id,
                    candidate_digest,
                    str(revision),
                    previous_receipt_id or "none",
                ),
            )
            receipt = SemanticUnitReceipt(
                provider=draft.provider,
                session_id=draft.session_id,
                receipt_id=receipt_id,
                unit_id=draft.unit_id,
                unit_digest=candidate_digest,
                revision=revision,
                previous_receipt_id=previous_receipt_id,
                kind=draft.kind,
                lifecycle=draft.lifecycle,
                extraction_basis=draft.extraction_basis,
                owner_source_digest=draft.owner_source_digest,
                source_digests=draft.source_digests,
                source_version_digest=draft.source_version_digest,
                first_sequence=draft.first_sequence,
                closed_at_sequence=draft.closed_at_sequence,
                superseded_by_source_digest=draft.superseded_by_source_digest,
                superseded_by_unit_id=draft.superseded_by_unit_id,
                owner_role=draft.owner_role,
                owner_message_kind=draft.owner_message_kind,
                rework_class=draft.rework_class,
            )
            heads[draft.unit_id] = receipt
            appended.append(receipt)

        retained_unobserved = 0
        for unit_id, receipt in prior_heads.items():
            if unit_id not in desired_by_unit:
                retained_unobserved += 1
                unchanged.add(receipt.receipt_id)

        ordered_heads = tuple(
            sorted(
                heads.values(),
                key=lambda item: (item.first_sequence, item.kind.value, item.unit_id),
            )
        )
        ordered_appended = tuple(
            sorted(
                appended,
                key=lambda item: (item.first_sequence, item.kind.value, item.unit_id),
            )
        )
        reconciliation_id = self._ids.fingerprint(
            "semantic-unit-reconciliation-v1",
            (
                SEMANTIC_UNIT_CONTRACT_VERSION,
                context.provider.value,
                context.session_id,
                context.analysis_window_fingerprint,
                *(item.receipt_id for item in ordered_heads),
            ),
        )
        reconciliation = SemanticUnitReconciliation(
            provider=context.provider,
            session_id=context.session_id,
            analysis_window_fingerprint=context.analysis_window_fingerprint,
            source_complete=(context.window_complete and context.text_extraction_complete),
            reconciliation_id=reconciliation_id,
            heads=ordered_heads,
            appended=ordered_appended,
            unchanged_receipt_ids=tuple(sorted(unchanged)),
            retained_unobserved_unit_count=retained_unobserved,
        )

        packets: tuple[EphemeralSemanticUnitEvidencePacket, ...] = ()
        if include_ephemeral_evidence:
            packets = tuple(
                evidence_by_unit[item.unit_id]
                for item in ordered_heads
                if item.unit_id in evidence_by_unit
            )
        return SemanticUnitProjection(
            reconciliation=reconciliation,
            evidence_packets=packets,
        )

    def _prior_heads(
        self,
        context: P1TextAnalysisInput,
        receipts: tuple[SemanticUnitReceipt, ...],
    ) -> dict[str, SemanticUnitReceipt]:
        by_unit: dict[str, list[SemanticUnitReceipt]] = defaultdict(list)
        seen_receipts: set[str] = set()
        for receipt in receipts:
            if receipt.receipt_id in seen_receipts:
                raise ValueError("prior semantic-unit receipts cannot repeat")
            seen_receipts.add(receipt.receipt_id)
            if (
                receipt.contract_version != SEMANTIC_UNIT_CONTRACT_VERSION
                or receipt.provider is not context.provider
                or receipt.session_id != context.session_id
            ):
                raise ValueError("prior semantic-unit receipt is not comparable")
            by_unit[receipt.unit_id].append(receipt)

        heads: dict[str, SemanticUnitReceipt] = {}
        for unit_id, versions in by_unit.items():
            ordered = sorted(versions, key=lambda item: item.revision)
            for earlier, later in zip(ordered, ordered[1:], strict=False):
                if later.revision <= earlier.revision:
                    raise ValueError("semantic-unit revisions must increase")
                if later.previous_receipt_id != earlier.receipt_id:
                    raise ValueError("semantic-unit revision chain is broken")
                if (
                    earlier.kind is not later.kind
                    or earlier.owner_source_digest != later.owner_source_digest
                ):
                    raise ValueError("semantic-unit identity cannot change by revision")
            heads[unit_id] = ordered[-1]
        return heads

    def _extract(
        self,
        context: P1TextAnalysisInput,
    ) -> tuple[
        tuple[_UnitDraft, ...],
        dict[str, EphemeralSemanticUnitEvidencePacket],
    ]:
        complete = context.window_complete and context.text_extraction_complete
        source_digest_by_message = {
            message.message_id: self._source_digest(context, message.message_id)
            for message in context.messages
        }
        kind_by_message = {
            message.message_id: _DOCUMENTED_UNIT_KIND.get((message.role, message.kind))
            for message in context.messages
        }
        unit_id_by_message = {
            message.message_id: self._unit_id(
                context,
                source_digest_by_message[message.message_id],
                kind,
            )
            for message in context.messages
            if (kind := kind_by_message[message.message_id]) is not None
        }
        replacements: dict[str, list[EphemeralRedactedMessage]] = defaultdict(list)
        for message in context.messages:
            for superseded_id in message.supersedes_message_ids:
                replacements[superseded_id].append(message)

        drafts: list[_UnitDraft] = []
        packets: dict[str, EphemeralSemanticUnitEvidencePacket] = {}
        for message in context.messages:
            kind = kind_by_message[message.message_id]
            if kind is None:
                continue
            owner_digest = source_digest_by_message[message.message_id]
            unit_id = unit_id_by_message[message.message_id]
            replacement_candidates = replacements.get(message.message_id, [])
            replacement = min(
                replacement_candidates,
                key=lambda item: (item.sequence, item.message_id),
                default=None,
            )
            if replacement is not None:
                replacement_source_digest = source_digest_by_message[
                    replacement.message_id
                ]
                lifecycle = SemanticUnitLifecycle.SUPERSEDED
                closed_at_sequence = replacement.sequence
                superseded_by_unit_id = unit_id_by_message.get(replacement.message_id)
            elif kind in _OPEN_ENDED_KINDS:
                replacement_source_digest = None
                lifecycle = (
                    SemanticUnitLifecycle.OPEN
                    if complete
                    else SemanticUnitLifecycle.RIGHT_CENSORED
                )
                closed_at_sequence = None
                superseded_by_unit_id = None
            else:
                replacement_source_digest = None
                lifecycle = SemanticUnitLifecycle.CLOSED
                closed_at_sequence = message.sequence
                superseded_by_unit_id = None

            source_version_digest = self._ids.fingerprint_secret(
                "semantic-source-version-v1",
                (
                    context.provider.value,
                    context.session_id,
                    message.message_id,
                    str(message.sequence),
                    message.role.value,
                    message.kind.value,
                    message.language.value,
                    message.scope_key,
                    *(message.supersedes_message_ids or ("none",)),
                ),
                message.text,
            )
            draft = _UnitDraft(
                provider=context.provider,
                session_id=context.session_id,
                unit_id=unit_id,
                kind=kind,
                lifecycle=lifecycle,
                extraction_basis=SemanticUnitExtractionBasis.DOCUMENTED_MESSAGE_KIND,
                owner_source_digest=owner_digest,
                source_digests=(owner_digest,),
                source_version_digest=source_version_digest,
                first_sequence=message.sequence,
                closed_at_sequence=closed_at_sequence,
                superseded_by_source_digest=replacement_source_digest,
                superseded_by_unit_id=superseded_by_unit_id,
                owner_role=message.role,
                owner_message_kind=message.kind,
                rework_class=(
                    FeedbackReworkClass.UNKNOWN
                    if kind is SemanticUnitKind.FEEDBACK
                    else None
                ),
            )
            drafts.append(draft)
            packets[unit_id] = EphemeralSemanticUnitEvidencePacket(
                unit_id=unit_id,
                owner_source_digest=owner_digest,
                language=message.language,
                text=message.text,
            )
        return (
            tuple(
                sorted(
                    drafts,
                    key=lambda item: (
                        item.first_sequence,
                        item.kind.value,
                        item.unit_id,
                    ),
                )
            ),
            packets,
        )

    def _source_digest(
        self,
        context: P1TextAnalysisInput,
        message_id: str,
    ) -> str:
        return self._ids.fingerprint(
            "semantic-source-v1",
            (context.provider.value, context.session_id, message_id),
        )

    def _unit_id(
        self,
        context: P1TextAnalysisInput,
        owner_source_digest: str,
        kind: SemanticUnitKind,
    ) -> str:
        return self._ids.fingerprint(
            "semantic-unit-id-v1",
            (
                SEMANTIC_UNIT_CONTRACT_VERSION,
                context.provider.value,
                context.session_id,
                kind.value,
                owner_source_digest,
                "0",
            ),
        )

    def _unit_digest(self, draft: _UnitDraft) -> str:
        return self._ids.fingerprint(
            "semantic-unit-version-v1",
            (
                draft.unit_id,
                draft.source_version_digest,
                draft.lifecycle.value,
                str(draft.closed_at_sequence)
                if draft.closed_at_sequence is not None
                else "none",
                draft.superseded_by_source_digest or "none",
                draft.superseded_by_unit_id or "none",
                draft.rework_class.value if draft.rework_class is not None else "none",
                draft.extraction_basis.value,
            ),
        )

    @staticmethod
    def _matches(
        receipt: SemanticUnitReceipt,
        draft: _UnitDraft,
        unit_digest: str,
    ) -> bool:
        return (
            receipt.unit_digest == unit_digest
            and receipt.kind is draft.kind
            and receipt.lifecycle is draft.lifecycle
            and receipt.extraction_basis is draft.extraction_basis
            and receipt.owner_source_digest == draft.owner_source_digest
            and receipt.source_digests == draft.source_digests
            and receipt.source_version_digest == draft.source_version_digest
            and receipt.first_sequence == draft.first_sequence
            and receipt.closed_at_sequence == draft.closed_at_sequence
            and receipt.superseded_by_source_digest
            == draft.superseded_by_source_digest
            and receipt.superseded_by_unit_id == draft.superseded_by_unit_id
            and receipt.owner_role is draft.owner_role
            and receipt.owner_message_kind is draft.owner_message_kind
            and receipt.rework_class is draft.rework_class
        )


__all__ = [
    "EXTRACTABLE_SEMANTIC_UNIT_KINDS",
    "EphemeralSemanticUnitEvidencePacket",
    "FeedbackReworkClass",
    "MAX_SEMANTIC_UNIT_RECEIPTS",
    "MAX_SEMANTIC_UNIT_SOURCES",
    "SEMANTIC_UNIT_CONTRACT_VERSION",
    "SEMANTIC_UNIT_KIND_VERSION",
    "SEMANTIC_UNIT_SCHEMA_VERSION",
    "SemanticUnitExtractionBasis",
    "SemanticUnitIdFactory",
    "SemanticUnitKind",
    "SemanticUnitLifecycle",
    "SemanticUnitProjection",
    "SemanticUnitReceipt",
    "SemanticUnitReconciliation",
    "SemanticUnitReconciler",
    "semantic_source_digest",
]
