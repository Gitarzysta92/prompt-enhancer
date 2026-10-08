"""Narrow SQLite adapters for local, privacy-sensitive persistence."""

__all__ = (
    "SqliteAnalysisRunRepository",
    "SqliteModelLinkExperimentRepository",
    "SqliteSessionAnalysisRunRepository",
    "SqliteMetricCoverageRepository",
    "SqliteTemporalSyntheticAggregationValidationRepository",
    "SqliteTemporalComparisonStratumRepository",
    "SqliteTemporalHistoryRepository",
    "SqliteTaskRepository",
    "SqliteOnlineBackupError",
    "backup_open_database",
)


def __getattr__(name: str):
    """Load repositories lazily so migration imports cannot form a cycle."""

    if name == "SqliteAnalysisRunRepository":
        from .analysis_runs import SqliteAnalysisRunRepository

        return SqliteAnalysisRunRepository
    if name == "SqliteTaskRepository":
        from .tasks import SqliteTaskRepository

        return SqliteTaskRepository
    if name == "SqliteSessionAnalysisRunRepository":
        from .session_analysis_runs import SqliteSessionAnalysisRunRepository

        return SqliteSessionAnalysisRunRepository
    if name == "SqliteMetricCoverageRepository":
        from .metric_coverage import SqliteMetricCoverageRepository

        return SqliteMetricCoverageRepository
    if name == "SqliteModelLinkExperimentRepository":
        from .model_link_experiments import SqliteModelLinkExperimentRepository

        return SqliteModelLinkExperimentRepository
    if name == "SqliteTemporalHistoryRepository":
        from .temporal_history import SqliteTemporalHistoryRepository

        return SqliteTemporalHistoryRepository
    if name == "SqliteTemporalComparisonStratumRepository":
        from .temporal_comparison_strata import (
            SqliteTemporalComparisonStratumRepository,
        )

        return SqliteTemporalComparisonStratumRepository
    if name == "SqliteTemporalSyntheticAggregationValidationRepository":
        from .temporal_aggregation_validation import (
            SqliteTemporalSyntheticAggregationValidationRepository,
        )

        return SqliteTemporalSyntheticAggregationValidationRepository
    if name in {"SqliteOnlineBackupError", "backup_open_database"}:
        from .online_backup import SqliteOnlineBackupError, backup_open_database

        return {
            "SqliteOnlineBackupError": SqliteOnlineBackupError,
            "backup_open_database": backup_open_database,
        }[name]
    raise AttributeError(name)
