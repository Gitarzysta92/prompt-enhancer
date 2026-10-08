"""Read-only V1 compatibility preview of one persisted, immutable analysis run.

This service is **not** the canonical live all-twenty session snapshot and it does
not participate in the model-ensemble watch, head, or UI pipeline.  It opens a
read transaction over an already persisted V1 run, projects it onto the V2
registry, and returns a preview whose limits are stated in the payload itself:

* at most the reviewed compatible rubric rows carry a number;
* every other behavioural contract is withheld with a fixed reason;
* every objective contract is unknown unless an authorized typed override is
  supplied, which this read path never fabricates.

Nothing is written, no provider is read, no transcript is retained, and no
model-stage output is consumed, so the preview is recomputed on demand and
disappears with the run when a privacy deletion cascades.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import Field

from ...domain import Provider, StrictModel
from ..persistence import (
    AnalysisRunStatus,
    SessionAnalysisRunRepository,
)
from .coaching_baselines import (
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from .metric_publication_v2 import (
    MetricPublicationV2,
    publish_v1_compatibility_preview,
)
from .objective_metric_projection import ObjectiveMetricOverride
from ...domain import Provider


SESSION_METRIC_PUBLICATION_KEY = "metric.contract-v2.v1-compatibility-preview"
SESSION_METRIC_PUBLICATION_VERSION = 2
#: Stated in the payload so no client can mistake the preview for the head.
SESSION_METRIC_PUBLICATION_LIMITS = (
    "read_only_v1_compatibility_preview",
    "reviewed_compatible_rubric_rows_only_numeric",
    "other_behavioral_states_withheld",
    "objective_values_unknown_without_authorized_override",
    "not_canonical_live_snapshot",
    "no_model_stage_output_consumed",
)


class SessionMetricPublication(StrictModel):
    """Current preview identity plus the complete twenty-metric bundle."""

    projection_key: str = SESSION_METRIC_PUBLICATION_KEY
    projection_version: int = Field(
        default=SESSION_METRIC_PUBLICATION_VERSION, ge=1
    )
    run_id: str
    provider: Provider
    source_metric_pack_key: str
    source_metric_pack_version: int = Field(ge=1)
    source_result_count: int = Field(ge=0)
    #: Structural honesty tags; a client must surface these beside any value.
    preview_limits: tuple[str, ...] = SESSION_METRIC_PUBLICATION_LIMITS
    publication: MetricPublicationV2


class SessionMetricPublicationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SessionMetricPublicationService:
    """Project a completed coaching-pack run onto the V2 compatibility preview.

    ``objective_overrides`` (optional) resolves the evidence-lane contracts
    from typed local evidence (decoder 4, ADR 0012) for the run's session, so
    the objective rows read from the same automatic run the rubric came from.
    Without it - or when evidence cannot be projected - those rows stay
    withheld exactly as before; a provider failure never hides the run.
    """

    def __init__(
        self,
        analyses: SessionAnalysisRunRepository,
        *,
        objective_overrides: Callable[[Provider, str], Mapping[str, ObjectiveMetricOverride] | None] | None = None,
    ) -> None:
        self._analyses = analyses
        self._objective_overrides = objective_overrides

    def get(self, run_id: str) -> SessionMetricPublication | None:
        run = self._analyses.get(run_id)
        if run is None:
            return None
        if run.status is not AnalysisRunStatus.COMPLETED:
            raise SessionMetricPublicationError("publication_run_not_completed")
        draft = run.draft
        if (
            draft.metric_pack_key != COACHING_METRIC_PACK_KEY
            or draft.metric_pack_version != COACHING_METRIC_PACK_VERSION
        ):
            raise SessionMetricPublicationError("publication_pack_unsupported")
        results = self._analyses.get_results(run_id)
        overrides: Mapping[str, ObjectiveMetricOverride] | None = None
        if self._objective_overrides is not None:
            try:
                overrides = self._objective_overrides(draft.provider, draft.session_id)
            except Exception:
                overrides = None
        return SessionMetricPublication(
            run_id=draft.run_id,
            provider=draft.provider,
            source_metric_pack_key=draft.metric_pack_key,
            source_metric_pack_version=draft.metric_pack_version,
            source_result_count=len(results),
            publication=publish_v1_compatibility_preview(results, objective_overrides=overrides),
        )


__all__ = [
    "SESSION_METRIC_PUBLICATION_KEY",
    "SESSION_METRIC_PUBLICATION_LIMITS",
    "SESSION_METRIC_PUBLICATION_VERSION",
    "SessionMetricPublication",
    "SessionMetricPublicationError",
    "SessionMetricPublicationService",
]
