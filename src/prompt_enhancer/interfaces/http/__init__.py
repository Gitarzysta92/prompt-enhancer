"""Narrow HTTP query interface for the local dashboard."""

from .task_routes import create_task_query_router
from .task_lifecycle_routes import create_task_lifecycle_router
from .session_analysis_command_routes import create_session_analysis_command_router
from .session_analysis_routes import create_session_analysis_query_router
from .session_quality_aggregation_routes import (
    create_session_quality_aggregation_router,
)
from .project_quality_aggregation_routes import (
    create_project_quality_aggregation_router,
)
from .provider_compatibility_routes import create_provider_compatibility_router
from .metric_readiness_routes import create_metric_readiness_router
from .metric_lifecycle_evidence_routes import (
    create_metric_lifecycle_evidence_router,
)
from .agent_metric_evidence_routes import create_agent_metric_evidence_router
from .metric_coverage_routes import create_metric_coverage_router
from .research_routes import create_research_router
from .model_link_experiment_routes import create_model_link_experiment_router
from .model_ensemble_routes import create_model_ensemble_router
from .model_ensemble_watch_routes import create_model_ensemble_watch_router
from .analysis_job_routes import create_analysis_job_router
from .automation_grant_routes import create_automation_grant_router
from .application_update_routes import create_application_update_router
from .control_plane_routes import create_control_plane_router
from .estimator_routes import create_estimator_router
from .paid_product_routes import create_paid_product_readiness_router
from .social_routes import (
    create_social_mutation_router,
    create_social_readiness_router,
)

__all__ = (
    "create_control_plane_router",
    "create_session_analysis_command_router",
    "create_session_analysis_query_router",
    "create_session_quality_aggregation_router",
    "create_project_quality_aggregation_router",
    "create_provider_compatibility_router",
    "create_metric_readiness_router",
    "create_metric_lifecycle_evidence_router",
    "create_agent_metric_evidence_router",
    "create_metric_coverage_router",
    "create_research_router",
    "create_model_link_experiment_router",
    "create_model_ensemble_router",
    "create_model_ensemble_watch_router",
    "create_analysis_job_router",
    "create_automation_grant_router",
    "create_application_update_router",
    "create_estimator_router",
    "create_paid_product_readiness_router",
    "create_social_mutation_router",
    "create_social_readiness_router",
    "create_task_query_router",
    "create_task_lifecycle_router",
)
