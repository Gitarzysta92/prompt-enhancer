"""Label-blind routing from objective scope and temporal metadata."""

from __future__ import annotations

from prompt_enhancer.application.analysis.scope_router_contracts import (
    EvidenceCoverageState,
    MetricApplicability,
    ScopeCompatibilityState,
    ScopeEvidenceAvailability,
    ScopeEvidenceCoverage,
    ScopeExtractionState,
    ScopeRouterInput,
    ScopeRouterOutput,
    ScopeRouterReason,
)


DETERMINISTIC_SCOPE_ROUTER_VERSION = "deterministic-scope-router-v1"


class DeterministicScopeRouter:
    """Apply a reviewed precedence table without inspecting authored labels."""

    version = DETERMINISTIC_SCOPE_ROUTER_VERSION

    def route(self, item: ScopeRouterInput) -> ScopeRouterOutput:
        if not isinstance(item, ScopeRouterInput):
            raise TypeError("scope router accepts ScopeRouterInput only")

        required_count = len(item.required_evidence_kinds)

        if item.metric_applicability is MetricApplicability.NOT_APPLICABLE:
            return self._output(
                ScopeCompatibilityState.NOT_APPLICABLE,
                ScopeRouterReason.METRIC_NOT_APPLICABLE,
                self._non_known_coverage(
                    EvidenceCoverageState.NOT_APPLICABLE,
                    required_count,
                ),
            )

        if item.superseding_revision_id is not None:
            return self._output(
                ScopeCompatibilityState.SUPERSEDED,
                ScopeRouterReason.TARGET_REVISION_SUPERSEDED,
                self._non_known_coverage(
                    EvidenceCoverageState.NOT_APPLICABLE,
                    required_count,
                ),
            )

        if item.metric_applicability is MetricApplicability.UNKNOWN:
            return self._insufficient(
                ScopeRouterReason.APPLICABILITY_UNKNOWN,
                required_count,
            )

        comparison_values = (
            item.comparison_project_id,
            item.comparison_session_id,
            item.comparison_revision_id,
            item.comparison_revision_ordinal,
            item.evidence_observed_sequence,
        )
        if any(value is None for value in comparison_values):
            return self._insufficient(
                ScopeRouterReason.COMPARISON_SCOPE_MISSING,
                required_count,
            )

        if item.comparison_project_id != item.target_project_id:
            return self._different_scope(
                ScopeRouterReason.PROJECT_MISMATCH,
                required_count,
            )
        if item.comparison_session_id != item.target_session_id:
            return self._different_scope(
                ScopeRouterReason.SESSION_MISMATCH,
                required_count,
            )

        assert item.comparison_revision_ordinal is not None
        assert item.comparison_revision_id is not None
        assert item.evidence_observed_sequence is not None
        if item.comparison_revision_ordinal > item.target_revision_ordinal:
            return self._different_scope(
                ScopeRouterReason.FUTURE_REVISION_EVIDENCE,
                required_count,
            )
        if (
            item.comparison_revision_ordinal == item.target_revision_ordinal
            and item.comparison_revision_id != item.target_revision_id
        ):
            return self._different_scope(
                ScopeRouterReason.REVISION_IDENTITY_MISMATCH,
                required_count,
            )

        if not item.evidence_requirement_links:
            return self._insufficient(
                ScopeRouterReason.REQUIREMENT_LINK_MISSING,
                required_count,
            )
        requirement_versions = {
            link.requirement_id: link.requirement_version_id
            for link in item.evidence_requirement_links
        }
        if item.target_requirement_id not in requirement_versions:
            return self._different_scope(
                ScopeRouterReason.REQUIREMENT_MISMATCH,
                required_count,
            )
        evidence_requirement_version = requirement_versions[item.target_requirement_id]
        if evidence_requirement_version is None:
            return self._insufficient(
                ScopeRouterReason.REQUIREMENT_VERSION_LINK_MISSING,
                required_count,
            )
        if evidence_requirement_version != item.target_requirement_version_id:
            return self._different_scope(
                ScopeRouterReason.REQUIREMENT_VERSION_MISMATCH,
                required_count,
            )
        if item.evidence_observed_sequence < item.requirement_observed_sequence:
            return self._different_scope(
                ScopeRouterReason.EVIDENCE_PRECEDES_REQUIREMENT,
                required_count,
            )

        if item.extraction_state is not ScopeExtractionState.COMPLETE:
            return self._insufficient(
                ScopeRouterReason.EXTRACTION_INCOMPLETE,
                required_count,
            )

        receipts = {receipt.kind: receipt for receipt in item.evidence_receipts}
        availabilities = tuple(
            receipts[kind].availability for kind in item.required_evidence_kinds
        )
        available_count = sum(
            availability is ScopeEvidenceAvailability.AVAILABLE
            for availability in availabilities
        )

        if ScopeEvidenceAvailability.FAILED in availabilities:
            return self._insufficient(
                ScopeRouterReason.EVIDENCE_EXTRACTION_FAILED,
                required_count,
            )
        if ScopeEvidenceAvailability.UNSUPPORTED in availabilities:
            return self._insufficient(
                ScopeRouterReason.REQUIRED_EVIDENCE_UNSUPPORTED,
                required_count,
            )
        if ScopeEvidenceAvailability.UNKNOWN in availabilities:
            return self._insufficient(
                ScopeRouterReason.EVIDENCE_AVAILABILITY_UNKNOWN,
                required_count,
            )

        coverage = ScopeEvidenceCoverage(
            state=EvidenceCoverageState.KNOWN,
            required_kind_count=required_count,
            available_kind_count=available_count,
            ratio=available_count / required_count,
        )
        if ScopeEvidenceAvailability.ABSENT in availabilities:
            return self._output(
                ScopeCompatibilityState.INSUFFICIENT_EVIDENCE,
                ScopeRouterReason.REQUIRED_EVIDENCE_ABSENT,
                coverage,
            )
        return self._output(
            ScopeCompatibilityState.COMPATIBLE,
            ScopeRouterReason.EXACT_SCOPE_EVIDENCE_READY,
            coverage,
        )

    def _insufficient(
        self,
        reason: ScopeRouterReason,
        required_count: int,
    ) -> ScopeRouterOutput:
        return self._output(
            ScopeCompatibilityState.INSUFFICIENT_EVIDENCE,
            reason,
            self._non_known_coverage(EvidenceCoverageState.UNKNOWN, required_count),
        )

    def _different_scope(
        self,
        reason: ScopeRouterReason,
        required_count: int,
    ) -> ScopeRouterOutput:
        return self._output(
            ScopeCompatibilityState.DIFFERENT_SCOPE,
            reason,
            self._non_known_coverage(
                EvidenceCoverageState.INCOMPATIBLE,
                required_count,
            ),
        )

    @staticmethod
    def _non_known_coverage(
        state: EvidenceCoverageState,
        required_count: int,
    ) -> ScopeEvidenceCoverage:
        return ScopeEvidenceCoverage(
            state=state,
            required_kind_count=required_count,
        )

    def _output(
        self,
        state: ScopeCompatibilityState,
        reason: ScopeRouterReason,
        coverage: ScopeEvidenceCoverage,
    ) -> ScopeRouterOutput:
        return ScopeRouterOutput(
            router_version=self.version,
            state=state,
            reason=reason,
            evidence_coverage=coverage,
        )


__all__ = [
    "DETERMINISTIC_SCOPE_ROUTER_VERSION",
    "DeterministicScopeRouter",
]
