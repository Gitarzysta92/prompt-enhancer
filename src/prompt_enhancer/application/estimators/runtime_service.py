"""First runnable estimator cascade: objective evidence, then ephemeral BM25.

No model process is started in this vertical.  Every successful run stops as a
partial execution at the local-model boundary, and its receipts can never write
product metric results.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import math
import re
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from ..jobs import (
    AnalysisJobExecutionContext,
    AnalysisJobExecutionResult,
    AnalysisJobRecord,
    AnalysisJobState,
)
from .contracts import (
    EstimatorStageKind,
    ExecutionDestination,
    MetricEstimateState,
    MetricValueKind,
)
from .evidence_packets import (
    EphemeralMetricEvidencePacket,
    PacketSpanRole,
    build_runtime_evidence_packet_receipt,
)
from .runtime_catalog import RuntimeEstimatorCatalog
from .runtime_persistence import (
    DurableRuntimePacketBinding,
    EstimatorRuntimeCheckpointReceipt,
    EstimatorRuntimeLaunch,
    EstimatorRuntimeMetricObservation,
    EstimatorRuntimeRepository,
    EstimatorRuntimeRetrievalHit,
    EstimatorRuntimeRetrievalReceipt,
    EstimatorRuntimeStageAttemptReceipt,
    EstimatorRuntimeStageOutcomeReceipt,
    EstimatorRuntimeStageOutcomeState,
    EstimatorRuntimeState,
    EstimatorRuntimeStateReceipt,
)


_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _id(domain: str, *parts: object) -> str:
    payload = ":".join((domain, *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EstimatorRuntimeSourceIdentity(StrictModel):
    input_fingerprint: str
    provenance_fingerprint: str
    session_revision_id: str
    window_fingerprint: str

    _safe_ids = field_validator(
        "input_fingerprint",
        "provenance_fingerprint",
        "session_revision_id",
        "window_fingerprint",
    )(_digest)


class ObjectiveRuntimeEvidence(StrictModel):
    """Typed scalar objective/readiness input; it contains no evidence text."""

    state: MetricEstimateState
    value_kind: MetricValueKind
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.:-]{0,127}$")
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, gt=0)
    reason_code: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.:-]{0,127}$"
    )
    opaque_evidence_refs: tuple[str, ...] = Field(default=(), max_length=512)

    @field_validator("opaque_evidence_refs")
    @classmethod
    def canonical_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("objective evidence references must be unique and sorted")
        return tuple(_digest(value) for value in values)

    @model_validator(mode="after")
    def truthful_shape(self) -> ObjectiveRuntimeEvidence:
        # Reuse the exact durable observation validator at the service boundary.
        EstimatorRuntimeMetricObservation(
            observation_id=_id("objective-shape", "observation"),
            execution_id=_id("objective-shape", "execution"),
            attempt_id=_id("objective-shape", "attempt"),
            metric_key="objective.shape",
            metric_question_fingerprint=_id("objective-shape", "question"),
            evidence_packet_fingerprint=_id("objective-shape", "packet"),
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            numerator=self.numerator,
            denominator=self.denominator,
            reason_code=self.reason_code,
            opaque_evidence_refs=self.opaque_evidence_refs,
            observed_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
        return self


class EstimatorRuntimePacketSource(Protocol):
    """Reviewed source seam; implementations decide where redacted packets live."""

    def identity(self, binding: DurableRuntimePacketBinding) -> EstimatorRuntimeSourceIdentity: ...

    def load_packet(
        self, binding: DurableRuntimePacketBinding
    ) -> EphemeralMetricEvidencePacket: ...

    def objective_evidence(
        self, packet: EphemeralMetricEvidencePacket
    ) -> ObjectiveRuntimeEvidence: ...


@dataclass(frozen=True, slots=True)
class RuntimeBm25Result:
    candidate_reference_ids: tuple[str, ...]
    hits: tuple[EstimatorRuntimeRetrievalHit, ...]


class ProductionRuntimeBm25:
    """Dependency-free BM25 over the exact in-memory candidate packet."""

    key = "runtime-bm25-v1"

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return _TOKEN.findall(value.casefold())

    def retrieve(self, packet: EphemeralMetricEvidencePacket) -> RuntimeBm25Result:
        query = " ".join(
            (
                packet.question_material.question_text.get_secret_value(),
                packet.question_material.rubric_text.get_secret_value(),
            )
        )
        spans = tuple(
            span
            for span in packet.spans
            if span.role is PacketSpanRole.CANDIDATE_EVIDENCE
        )
        candidates = tuple(sorted(span.reference_id for span in spans))
        if not spans:
            return RuntimeBm25Result(candidate_reference_ids=(), hits=())
        documents = [
            self._tokens(span.redacted_text.get_secret_value()) for span in spans
        ]
        query_terms = set(self._tokens(query))
        average_length = sum(map(len, documents)) / len(documents)
        frequencies = [Counter(document) for document in documents]
        document_frequency = {
            term: sum(1 for frequency in frequencies if frequency[term] > 0)
            for term in query_terms
        }
        scored: list[tuple[float, str]] = []
        for span, document, frequency in zip(
            spans, documents, frequencies, strict=True
        ):
            score = 0.0
            for term in query_terms:
                term_frequency = frequency[term]
                if term_frequency == 0:
                    continue
                frequency_across_documents = document_frequency[term]
                inverse_document_frequency = math.log(
                    1
                    + (
                        len(documents)
                        - frequency_across_documents
                        + 0.5
                    )
                    / (frequency_across_documents + 0.5)
                )
                denominator = term_frequency + 1.2 * (
                    1 - 0.75 + 0.75 * len(document) / max(average_length, 1)
                )
                score += (
                    inverse_document_frequency
                    * (term_frequency * 2.2)
                    / denominator
                )
            scored.append((score, span.reference_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return RuntimeBm25Result(
            candidate_reference_ids=candidates,
            hits=tuple(
                EstimatorRuntimeRetrievalHit(
                    evidence_reference_id=reference,
                    rank=rank,
                    raw_score=score,
                )
                for rank, (score, reference) in enumerate(scored, start=1)
            ),
        )


class EstimatorRuntimeService:
    def __init__(
        self,
        repository: EstimatorRuntimeRepository,
        catalog: RuntimeEstimatorCatalog,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._clock = clock

    def launch(self, launch: EstimatorRuntimeLaunch):  # type: ignore[no-untyped-def]
        launch = EstimatorRuntimeLaunch.model_validate(
            launch.model_dump(mode="python")
        )
        now = self._clock()
        if launch.consumed_at != now:
            # Exact injected clocks are used by deterministic callers/tests; for
            # live callers the receipt is allowed a one-second scheduling skew.
            delta = abs((launch.consumed_at - now).total_seconds())
            if delta > 1:
                raise ValueError("runtime launch consumption time is stale")
        if launch.authorization.destination not in {
            ExecutionDestination.LOCAL_DEVICE,
            ExecutionDestination.SYNTHETIC_TEST,
        }:
            raise ValueError("the first runtime vertical executes locally only")
        registration = self._catalog.plan_for_route(launch.authorization.route)
        if registration.plan_fingerprint != launch.authorization.plan_fingerprint:
            raise ValueError("runtime authorization plan is not registered")
        for receipt in launch.packet_receipts:
            registration.validate_packet_receipt(receipt)
        return self._repository.launch(launch)

    def cancel(self, job_id: str):  # type: ignore[no-untyped-def]
        return self._repository.cancel(job_id, cancelled_at=self._clock())


class EstimatorRuntimeHandler:
    """Lease-aware worker handler that stops before any local model stage."""

    def __init__(
        self,
        repository: EstimatorRuntimeRepository,
        catalog: RuntimeEstimatorCatalog,
        source: EstimatorRuntimePacketSource,
        *,
        bm25: ProductionRuntimeBm25 | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._source = source
        self._bm25 = bm25 or ProductionRuntimeBm25()
        self._clock = clock

    def authorization_check(self, job: AnalysisJobRecord) -> bool:
        return self._repository.authorization_is_valid(job.job_id, now=self._clock())

    def fingerprint_resolver(
        self, job: AnalysisJobRecord
    ) -> tuple[str, str] | None:
        snapshot = self._repository.get_by_job(job.job_id)
        if snapshot is None:
            return None
        binding = snapshot.authorization.packet_bindings[0]
        identity = self._source.identity(binding)
        return identity.input_fingerprint, identity.provenance_fingerprint

    def execution_stop_callback(
        self,
        job: AnalysisJobRecord,
        state: AnalysisJobState,
        reason_code: str,
    ) -> None:
        mapped = {
            AnalysisJobState.CANCELLED: EstimatorRuntimeState.CANCELLED,
            AnalysisJobState.SUPERSEDED: EstimatorRuntimeState.SUPERSEDED,
            AnalysisJobState.FAILED: EstimatorRuntimeState.FAILED,
        }.get(state)
        if mapped is None:
            return
        snapshot = self._repository.get_by_job(job.job_id)
        if snapshot is not None:
            self._append_terminal_state(snapshot, mapped, reason_code)

    def execution_recovery_callback(self, now: datetime) -> None:
        self._repository.reconcile_expired(now=now)
        self._repository.reconcile_invalid_automation_grants(now=now)

    def __call__(
        self,
        job: AnalysisJobRecord,
        context: AnalysisJobExecutionContext,
    ) -> AnalysisJobExecutionResult:
        snapshot = self._repository.get_by_job(job.job_id)
        if snapshot is None:
            return AnalysisJobExecutionResult(
                state=AnalysisJobState.FAILED,
                reason_code="runtime_binding_missing",
                progress_completed=1,
                progress_total=8,
            )
        if snapshot.states[-1].state in {
            EstimatorRuntimeState.PARTIAL,
            EstimatorRuntimeState.FAILED,
            EstimatorRuntimeState.CANCELLED,
            EstimatorRuntimeState.SUPERSEDED,
        }:
            return AnalysisJobExecutionResult(
                state=AnalysisJobState(snapshot.states[-1].state.value),
                reason_code=snapshot.states[-1].reason_code,
                progress_completed=3,
                progress_total=8,
            )
        if not self._repository.authorization_is_valid(job.job_id, now=self._clock()):
            self._append_terminal_state(
                snapshot,
                EstimatorRuntimeState.CANCELLED,
                "authorization_expired_or_revoked",
            )
            return AnalysisJobExecutionResult(
                state=AnalysisJobState.CANCELLED,
                reason_code="authorization_expired_or_revoked",
                progress_completed=1,
                progress_total=8,
            )
        registration = self._catalog.plan_for_route(snapshot.binding.route)
        if registration.plan_fingerprint != snapshot.binding.plan_fingerprint:
            self._append_terminal_state(
                snapshot, EstimatorRuntimeState.FAILED, "runtime_plan_not_registered"
            )
            return AnalysisJobExecutionResult(
                state=AnalysisJobState.FAILED,
                reason_code="runtime_plan_not_registered",
                progress_completed=1,
                progress_total=8,
            )
        if snapshot.states[-1].state is EstimatorRuntimeState.CREATED:
            self._append_state(
                snapshot, EstimatorRuntimeState.RUNNING, "runtime_worker_started"
            )

        packets: dict[str, EphemeralMetricEvidencePacket] = {}
        for binding in snapshot.authorization.packet_bindings:
            current_identity = self._source.identity(binding)
            mismatch = self._identity_mismatch(snapshot, current_identity)
            if mismatch is not None:
                current = self._repository.get_by_job(job.job_id)
                assert current is not None
                self._append_terminal_state(
                    current, EstimatorRuntimeState.SUPERSEDED, mismatch
                )
                return AnalysisJobExecutionResult(
                    state=AnalysisJobState.SUPERSEDED,
                    reason_code=mismatch,
                    progress_completed=1,
                    progress_total=8,
                )
            context.heartbeat()
            packet = self._source.load_packet(binding)
            receipt = build_runtime_evidence_packet_receipt(packet)
            if (
                receipt.packet_fingerprint != binding.evidence_packet_fingerprint
                or receipt.metric_key != binding.metric_key
                or receipt.metric_question_fingerprint
                != binding.metric_question_fingerprint
                or receipt.plan_fingerprint != snapshot.binding.plan_fingerprint
            ):
                current = self._repository.get_by_job(job.job_id)
                assert current is not None
                self._append_terminal_state(
                    current,
                    EstimatorRuntimeState.SUPERSEDED,
                    "packet_fingerprint_changed",
                )
                return AnalysisJobExecutionResult(
                    state=AnalysisJobState.SUPERSEDED,
                    reason_code="packet_fingerprint_changed",
                    progress_completed=1,
                    progress_total=8,
                )
            packets[binding.metric_key] = packet

        context.enter_stage(2, progress_completed=1, progress_total=8)
        for binding in snapshot.authorization.packet_bindings:
            self._run_objective_stage(
                job.job_id,
                binding,
                packets[binding.metric_key],
                registration.stage_registration(1).stage_fingerprint,
            )
            context.heartbeat()

        context.enter_stage(3, progress_completed=2, progress_total=8)
        for binding in snapshot.authorization.packet_bindings:
            self._run_bm25_stage(
                job.job_id,
                binding,
                packets[binding.metric_key],
                registration.stage_registration(2).stage_fingerprint,
            )
            context.heartbeat()

        current = self._repository.get_by_job(job.job_id)
        assert current is not None
        for binding in current.authorization.packet_bindings:
            checkpoints = tuple(
                item for item in current.checkpoints if item.metric_key == binding.metric_key
            )
            previous = checkpoints[-1]
            terminal_checkpoint = EstimatorRuntimeCheckpointReceipt(
                checkpoint_id=_id(
                    "runtime-checkpoint",
                    current.binding.execution_id,
                    binding.metric_key,
                    previous.sequence + 1,
                ),
                execution_id=current.binding.execution_id,
                metric_key=binding.metric_key,
                sequence=previous.sequence + 1,
                previous_checkpoint_fingerprint=previous.canonical_fingerprint,
                last_completed_stage_ordinal=2,
                next_stage_ordinal=None,
                restart_generation=job.attempt_count - 1,
                state=EstimatorRuntimeState.PARTIAL,
                reason_code="local_model_runtime_not_enabled",
                recorded_at=self._clock(),
            )
            self._repository.append_checkpoint(terminal_checkpoint)
        current = self._repository.get_by_job(job.job_id)
        assert current is not None
        self._append_terminal_state(
            current,
            EstimatorRuntimeState.PARTIAL,
            "local_model_runtime_not_enabled",
        )
        return AnalysisJobExecutionResult(
            state=AnalysisJobState.PARTIAL,
            reason_code="local_model_runtime_not_enabled",
            progress_completed=3,
            progress_total=8,
        )

    @staticmethod
    def _identity_mismatch(
        snapshot, identity: EstimatorRuntimeSourceIdentity  # type: ignore[no-untyped-def]
    ) -> str | None:
        expected = snapshot.binding
        if identity.input_fingerprint != expected.input_fingerprint:
            return "input_changed"
        if identity.provenance_fingerprint != expected.provenance_fingerprint:
            return "provenance_changed"
        if identity.session_revision_id != expected.session_revision_id:
            return "session_revision_changed"
        if identity.window_fingerprint != expected.window_fingerprint:
            return "window_changed"
        return None

    def _append_state(
        self,
        snapshot,  # type: ignore[no-untyped-def]
        state: EstimatorRuntimeState,
        reason_code: str,
    ) -> None:
        previous = snapshot.states[-1]
        self._repository.append_state(
            EstimatorRuntimeStateReceipt(
                state_receipt_id=_id(
                    "runtime-state",
                    snapshot.binding.execution_id,
                    previous.sequence + 1,
                ),
                execution_id=snapshot.binding.execution_id,
                sequence=previous.sequence + 1,
                previous_state_receipt_fingerprint=previous.canonical_fingerprint,
                state=state,
                reason_code=reason_code,
                recorded_at=self._clock(),
            )
        )

    def _append_terminal_state(
        self,
        snapshot,  # type: ignore[no-untyped-def]
        state: EstimatorRuntimeState,
        reason_code: str,
    ) -> None:
        if snapshot.states[-1].state in {
            EstimatorRuntimeState.CREATED,
            EstimatorRuntimeState.RUNNING,
        }:
            self._append_state(snapshot, state, reason_code)

    @staticmethod
    def _validate_persisted_stage_output(
        snapshot,  # type: ignore[no-untyped-def]
        binding: DurableRuntimePacketBinding,
        *,
        attempt_id: str,
        stage_ordinal: int,
        output_fingerprint: str,
    ) -> tuple[
        EstimatorRuntimeStageAttemptReceipt,
        EstimatorRuntimeStageOutcomeReceipt | None,
    ]:
        attempt = next(
            (item for item in snapshot.attempts if item.attempt_id == attempt_id),
            None,
        )
        if (
            attempt is None
            or attempt.execution_id != snapshot.binding.execution_id
            or attempt.metric_key != binding.metric_key
            or attempt.metric_question_fingerprint
            != binding.metric_question_fingerprint
            or attempt.evidence_packet_fingerprint
            != binding.evidence_packet_fingerprint
            or attempt.stage_ordinal != stage_ordinal
        ):
            raise RuntimeError("persisted runtime output has inconsistent attempt lineage")
        outcome = next(
            (item for item in snapshot.outcomes if item.attempt_id == attempt_id),
            None,
        )
        if outcome is not None and (
            outcome.state is not EstimatorRuntimeStageOutcomeState.COMPLETED
            or outcome.output_fingerprint != output_fingerprint
        ):
            raise RuntimeError("persisted runtime output has conflicting outcome lineage")
        return attempt, outcome

    def _recover_objective_completion(
        self,
        job_id: str,
        binding: DurableRuntimePacketBinding,
        observation: EstimatorRuntimeMetricObservation,
    ) -> None:
        snapshot = self._repository.get_by_job(job_id)
        assert snapshot is not None
        if (
            observation.execution_id != snapshot.binding.execution_id
            or observation.metric_key != binding.metric_key
            or observation.metric_question_fingerprint
            != binding.metric_question_fingerprint
            or observation.evidence_packet_fingerprint
            != binding.evidence_packet_fingerprint
        ):
            raise RuntimeError("persisted objective output disagrees with its binding")
        attempt, outcome = self._validate_persisted_stage_output(
            snapshot,
            binding,
            attempt_id=observation.attempt_id,
            stage_ordinal=1,
            output_fingerprint=observation.canonical_fingerprint,
        )
        if outcome is None:
            self._repository.append_stage_outcome(
                EstimatorRuntimeStageOutcomeReceipt(
                    outcome_id=_id("runtime-outcome", attempt.attempt_id),
                    attempt_id=attempt.attempt_id,
                    execution_id=attempt.execution_id,
                    state=EstimatorRuntimeStageOutcomeState.COMPLETED,
                    reason_code="objective_observation_recorded",
                    output_fingerprint=observation.canonical_fingerprint,
                    finished_at=max(self._clock(), observation.observed_at),
                )
            )
            snapshot = self._repository.get_by_job(job_id)
            assert snapshot is not None
        checkpoints = tuple(
            item for item in snapshot.checkpoints if item.metric_key == binding.metric_key
        )
        if checkpoints:
            if checkpoints[-1].last_completed_stage_ordinal < 1:
                raise RuntimeError("objective checkpoint lineage is incomplete")
            return
        self._repository.append_checkpoint(
            EstimatorRuntimeCheckpointReceipt(
                checkpoint_id=_id(
                    "runtime-checkpoint",
                    snapshot.binding.execution_id,
                    binding.metric_key,
                    0,
                ),
                execution_id=snapshot.binding.execution_id,
                metric_key=binding.metric_key,
                sequence=0,
                last_completed_stage_ordinal=1,
                next_stage_ordinal=2,
                restart_generation=snapshot.job.attempt_count - 1,
                state=EstimatorRuntimeState.RUNNING,
                reason_code="objective_stage_completed",
                recorded_at=max(self._clock(), observation.observed_at),
            )
        )

    def _recover_bm25_completion(
        self,
        job_id: str,
        binding: DurableRuntimePacketBinding,
        retrieval: EstimatorRuntimeRetrievalReceipt,
    ) -> None:
        snapshot = self._repository.get_by_job(job_id)
        assert snapshot is not None
        if (
            retrieval.execution_id != snapshot.binding.execution_id
            or retrieval.metric_key != binding.metric_key
            or retrieval.metric_question_fingerprint
            != binding.metric_question_fingerprint
            or retrieval.evidence_packet_fingerprint
            != binding.evidence_packet_fingerprint
        ):
            raise RuntimeError("persisted retrieval output disagrees with its binding")
        attempt, outcome = self._validate_persisted_stage_output(
            snapshot,
            binding,
            attempt_id=retrieval.attempt_id,
            stage_ordinal=2,
            output_fingerprint=retrieval.canonical_fingerprint,
        )
        if outcome is None:
            self._repository.append_stage_outcome(
                EstimatorRuntimeStageOutcomeReceipt(
                    outcome_id=_id("runtime-outcome", attempt.attempt_id),
                    attempt_id=attempt.attempt_id,
                    execution_id=attempt.execution_id,
                    state=EstimatorRuntimeStageOutcomeState.COMPLETED,
                    reason_code="bm25_retrieval_recorded",
                    output_fingerprint=retrieval.canonical_fingerprint,
                    finished_at=max(self._clock(), retrieval.created_at),
                )
            )
            snapshot = self._repository.get_by_job(job_id)
            assert snapshot is not None
        checkpoints = tuple(
            item for item in snapshot.checkpoints if item.metric_key == binding.metric_key
        )
        if not checkpoints:
            raise RuntimeError("BM25 completion lacks the objective checkpoint")
        previous = checkpoints[-1]
        if previous.last_completed_stage_ordinal >= 2:
            return
        if previous.last_completed_stage_ordinal != 1 or previous.next_stage_ordinal != 2:
            raise RuntimeError("BM25 checkpoint lineage is inconsistent")
        self._repository.append_checkpoint(
            EstimatorRuntimeCheckpointReceipt(
                checkpoint_id=_id(
                    "runtime-checkpoint",
                    snapshot.binding.execution_id,
                    binding.metric_key,
                    previous.sequence + 1,
                ),
                execution_id=snapshot.binding.execution_id,
                metric_key=binding.metric_key,
                sequence=previous.sequence + 1,
                previous_checkpoint_fingerprint=previous.canonical_fingerprint,
                last_completed_stage_ordinal=2,
                next_stage_ordinal=3,
                restart_generation=snapshot.job.attempt_count - 1,
                state=EstimatorRuntimeState.RUNNING,
                reason_code="bm25_stage_completed",
                recorded_at=max(self._clock(), retrieval.created_at),
            )
        )

    def _run_objective_stage(
        self,
        job_id: str,
        binding: DurableRuntimePacketBinding,
        packet: EphemeralMetricEvidencePacket,
        stage_fingerprint: str,
    ) -> None:
        snapshot = self._repository.get_by_job(job_id)
        assert snapshot is not None
        existing = next(
            (
                item
                for item in snapshot.observations
                if item.metric_key == binding.metric_key
            ),
            None,
        )
        if existing is not None:
            self._recover_objective_completion(job_id, binding, existing)
            return
        stage_attempts = tuple(
            item
            for item in snapshot.attempts
            if item.metric_key == binding.metric_key and item.stage_ordinal == 1
        )
        closed_attempt_ids = {item.attempt_id for item in snapshot.outcomes}
        if any(item.attempt_id not in closed_attempt_ids for item in stage_attempts):
            raise RuntimeError("runtime interrupted attempt was not reconciled")
        attempt_ordinal = len(stage_attempts) + 1
        attempt = EstimatorRuntimeStageAttemptReceipt(
            attempt_id=_id(
                "runtime-attempt",
                snapshot.binding.execution_id,
                binding.metric_key,
                1,
                attempt_ordinal,
            ),
            execution_id=snapshot.binding.execution_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            stage_ordinal=1,
            stage_kind=EstimatorStageKind.OBJECTIVE_EVIDENCE,
            stage_fingerprint=stage_fingerprint,
            attempt_ordinal=attempt_ordinal,
            started_at=self._clock(),
        )
        self._repository.append_stage_attempt(attempt)
        try:
            objective = self._source.objective_evidence(packet)
        except Exception:
            self._repository.append_stage_outcome(
                EstimatorRuntimeStageOutcomeReceipt(
                    outcome_id=_id("runtime-outcome", attempt.attempt_id),
                    attempt_id=attempt.attempt_id,
                    execution_id=attempt.execution_id,
                    state=EstimatorRuntimeStageOutcomeState.INTERRUPTED,
                    reason_code="stage_execution_interrupted",
                    finished_at=self._clock(),
                )
            )
            raise
        observation = EstimatorRuntimeMetricObservation(
            observation_id=_id(
                "runtime-observation", snapshot.binding.execution_id, binding.metric_key
            ),
            execution_id=snapshot.binding.execution_id,
            attempt_id=attempt.attempt_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            state=objective.state,
            value_kind=objective.value_kind,
            numeric_value=objective.numeric_value,
            label_code=objective.label_code,
            numerator=objective.numerator,
            denominator=objective.denominator,
            reason_code=objective.reason_code,
            opaque_evidence_refs=objective.opaque_evidence_refs,
            observed_at=self._clock(),
        )
        self._repository.append_metric_observation(observation)
        self._recover_objective_completion(job_id, binding, observation)

    def _run_bm25_stage(
        self,
        job_id: str,
        binding: DurableRuntimePacketBinding,
        packet: EphemeralMetricEvidencePacket,
        stage_fingerprint: str,
    ) -> None:
        snapshot = self._repository.get_by_job(job_id)
        assert snapshot is not None
        existing = next(
            (
                item
                for item in snapshot.retrievals
                if item.metric_key == binding.metric_key
            ),
            None,
        )
        if existing is not None:
            self._recover_bm25_completion(job_id, binding, existing)
            return
        stage_attempts = tuple(
            item
            for item in snapshot.attempts
            if item.metric_key == binding.metric_key and item.stage_ordinal == 2
        )
        closed_attempt_ids = {item.attempt_id for item in snapshot.outcomes}
        if any(item.attempt_id not in closed_attempt_ids for item in stage_attempts):
            raise RuntimeError("runtime interrupted attempt was not reconciled")
        attempt_ordinal = len(stage_attempts) + 1
        attempt = EstimatorRuntimeStageAttemptReceipt(
            attempt_id=_id(
                "runtime-attempt",
                snapshot.binding.execution_id,
                binding.metric_key,
                2,
                attempt_ordinal,
            ),
            execution_id=snapshot.binding.execution_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            stage_ordinal=2,
            stage_kind=EstimatorStageKind.BM25_RETRIEVAL,
            stage_fingerprint=stage_fingerprint,
            attempt_ordinal=attempt_ordinal,
            started_at=self._clock(),
        )
        self._repository.append_stage_attempt(attempt)
        try:
            result = self._bm25.retrieve(packet)
        except Exception:
            self._repository.append_stage_outcome(
                EstimatorRuntimeStageOutcomeReceipt(
                    outcome_id=_id("runtime-outcome", attempt.attempt_id),
                    attempt_id=attempt.attempt_id,
                    execution_id=attempt.execution_id,
                    state=EstimatorRuntimeStageOutcomeState.INTERRUPTED,
                    reason_code="stage_execution_interrupted",
                    finished_at=self._clock(),
                )
            )
            raise
        receipt = build_runtime_evidence_packet_receipt(packet)
        retrieval = EstimatorRuntimeRetrievalReceipt(
            retrieval_id=_id(
                "runtime-retrieval", snapshot.binding.execution_id, binding.metric_key
            ),
            execution_id=snapshot.binding.execution_id,
            attempt_id=attempt.attempt_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            query_fingerprint=receipt.retrieval_query_fingerprint,
            candidate_index_fingerprint=receipt.retrieval_index_sha256,
            candidate_reference_ids=result.candidate_reference_ids,
            hits=result.hits,
            created_at=self._clock(),
        )
        self._repository.append_retrieval(retrieval)
        self._recover_bm25_completion(job_id, binding, retrieval)


__all__ = [
    "EstimatorRuntimeHandler",
    "EstimatorRuntimePacketSource",
    "EstimatorRuntimeService",
    "EstimatorRuntimeSourceIdentity",
    "ObjectiveRuntimeEvidence",
    "ProductionRuntimeBm25",
    "RuntimeBm25Result",
]
