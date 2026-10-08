from __future__ import annotations

from prompt_enhancer.application.analysis import TASK_METRIC_ENGINE_VERSION
from prompt_enhancer.database import Database


def test_task_metric_definitions_record_the_task_calculator_family(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    definitions = {
        (item["key"], item["version"]): item
        for item in database.list_metric_definitions()
    }

    task_definition = definitions[("task.workflow.session_count", 2)]
    session_definition = definitions[("workflow.event_count", 2)]
    assert task_definition["algorithm_version"] == TASK_METRIC_ENGINE_VERSION
    assert session_definition["algorithm_version"] == "deterministic-2"
