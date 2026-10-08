"""Content-free lifecycle evidence shared with the owned desktop host.

Never retain an exception, traceback, component object, path or provider value
in this report. The names are a closed application vocabulary, not user input.
"""

from dataclasses import dataclass
from enum import StrEnum


class RuntimeComponent(StrEnum):
    ANALYSIS_JOB_WORKER = "analysis_job_worker"
    AUTOMATION_GRANT_WORKER = "automation_grant_worker"
    MODEL_ENSEMBLE_WATCH_WORKER = "model_ensemble_watch_worker"
    LOCAL_SOURCE_REFRESH_WORKER = "local_source_refresh_worker"
    LOCAL_MODEL_SERVICE = "local_model_service"
    LOCAL_AGENT_SERVICE = "local_agent_service"
    MCP_MANAGED_RUNTIME_SERVICE = "mcp_managed_runtime_service"
    MODEL_EVALUATION_SERVICE = "model_evaluation_service"
    APPLICATION_UPDATE_SERVICE = "application_update_service"


@dataclass
class RuntimeLifecycleReport:
    startup_failure: RuntimeComponent | None = None
    shutdown_failures: tuple[RuntimeComponent, ...] = ()
    cleanup_finished: bool = False
