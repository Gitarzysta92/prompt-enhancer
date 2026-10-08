from __future__ import annotations

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators import ModelLabInventory
from prompt_enhancer.database import Database, DatabaseInvariantError
from prompt_enhancer.infrastructure.sqlite import estimators as estimator_storage

from test_estimator_contracts import synthetic_plan
from test_estimator_persistence import _bundle


def test_empty_model_lab_inventory_is_a_truthful_zero(tmp_path) -> None:
    inventory = Database(tmp_path / "empty.sqlite3").estimator_repository().model_lab_inventory()

    assert inventory.scope == "synthetic_only"
    assert inventory.session_data_read is False
    assert inventory.private_evidence_returned is False
    assert inventory.registered_plan_count == 0
    assert inventory.synthetic_execution_count == 0
    assert inventory.model_run_count == 0
    assert inventory.model_vote_count == 0
    assert inventory.metric_estimate_count == 0
    assert inventory.plans == ()
    assert inventory.activation_outcome == "synthetic_or_insufficient"
    assert inventory.activation_allowed is False


def test_inventory_is_canonical_and_uses_execution_receipt_totals(tmp_path) -> None:
    repository = Database(tmp_path / "inventory.sqlite3").estimator_repository()
    bundle = _bundle()
    alpha = synthetic_plan(plan_key="alpha-quality", plan_version="plan-2")
    repository.register_plan(bundle.plan)
    repository.register_plan(alpha)
    repository.save_completed_synthetic_bundle(bundle)

    inventory = repository.model_lab_inventory()

    assert [plan.plan_key for plan in inventory.plans] == [
        "alpha-quality",
        "balanced-quality",
    ]
    assert inventory.registered_plan_count == 2
    assert inventory.synthetic_execution_count == 1
    assert inventory.model_run_count == len(bundle.model_runs)
    assert inventory.model_vote_count == len(bundle.model_votes)
    assert inventory.metric_estimate_count == len(bundle.metric_estimates)
    populated = inventory.plans[1]
    assert populated.metric_question_count == len(bundle.plan.question_specs)
    assert populated.synthetic_execution_count == 1
    assert populated.activation_allowed is False


def test_privacy_delete_immediately_removes_inventory_execution_totals(tmp_path) -> None:
    repository = Database(tmp_path / "privacy.sqlite3").estimator_repository()
    bundle = _bundle()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    repository.delete_synthetic_case_for_privacy(bundle.test_case.case_id)
    inventory = repository.model_lab_inventory()

    assert inventory.registered_plan_count == 1
    assert inventory.synthetic_execution_count == 0
    assert inventory.model_run_count == 0
    assert inventory.model_vote_count == 0
    assert inventory.metric_estimate_count == 0


def test_inventory_fails_instead_of_truncating_when_plan_bound_is_exceeded(
    tmp_path, monkeypatch
) -> None:
    repository = Database(tmp_path / "bounded.sqlite3").estimator_repository()
    repository.register_plan(synthetic_plan(plan_key="alpha-quality"))
    repository.register_plan(synthetic_plan(plan_key="beta-quality"))
    monkeypatch.setattr(estimator_storage, "MAX_MODEL_LAB_PLANS", 1)

    with pytest.raises(DatabaseInvariantError, match="exceeds its safe bound"):
        repository.model_lab_inventory()


def test_inventory_contract_rejects_false_totals_and_path_versions(tmp_path) -> None:
    repository = Database(tmp_path / "contract.sqlite3").estimator_repository()
    repository.register_plan(synthetic_plan())
    inventory = repository.model_lab_inventory()

    with pytest.raises(ValidationError, match="aggregate counts"):
        ModelLabInventory(
            **{
                **inventory.model_dump(),
                "registered_plan_count": 0,
            }
        )
    with pytest.raises(ValidationError, match="content-free version"):
        inventory.plans[0].__class__(
            **{
                **inventory.plans[0].model_dump(),
                "plan_version": "https://invalid.example",
            }
        )
