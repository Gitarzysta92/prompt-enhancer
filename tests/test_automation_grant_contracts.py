from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantState,
    AutomationResourcePolicy,
    AutomationRoute,
)
from prompt_enhancer.domain import Provider


NOW = datetime(2044, 1, 2, 3, 4, tzinfo=UTC)
GRANT = "a" * 64
PROJECT = "b" * 64


def _scope() -> AutomationGrantScope:
    return AutomationGrantScope(
        provider=Provider.CODEX,
        project_id=PROJECT,
        metric_keys=("logic.decomposition_coverage", "prompt.context_sufficiency"),
    )


def test_locked_automation_defaults_are_local_and_bounded() -> None:
    scope = _scope()
    assert scope.newest_session_limit == 20
    assert scope.check_interval_seconds == 15 * 60
    assert scope.resource_policy == AutomationResourcePolicy(
        route=AutomationRoute.BALANCED
    )
    assert scope.resource_policy.max_gpu_workers == 1
    assert scope.local_only is True
    assert scope.remote_requires_fresh_approval is True


def test_grant_requires_exact_thirty_day_lifetime() -> None:
    draft = AutomationGrantDraft(
        grant_id=GRANT,
        scope=_scope(),
        created_at=NOW,
        expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
    )
    assert draft.expires_at - draft.created_at == timedelta(days=30)

    with pytest.raises(ValidationError):
        AutomationGrantDraft(
            grant_id=GRANT,
            scope=_scope(),
            created_at=NOW,
            expires_at=NOW + timedelta(days=31),
        )


def test_effective_expiry_never_extends_itself() -> None:
    record = AutomationGrantRecord(
        grant_id=GRANT,
        revision=1,
        scope=_scope(),
        state=AutomationGrantState.ACTIVE,
        created_at=NOW,
        renewed_at=NOW,
        expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        next_check_at=NOW,
    )
    assert record.is_due(NOW)
    assert record.effective_state(record.expires_at) is AutomationGrantState.EXPIRED
    assert not record.is_due(record.expires_at)


def test_revocation_is_explicit_and_remote_cannot_be_preapproved() -> None:
    revoked = AutomationGrantRecord(
        grant_id=GRANT,
        revision=2,
        scope=_scope(),
        state=AutomationGrantState.REVOKED,
        created_at=NOW,
        renewed_at=NOW,
        expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        next_check_at=NOW,
        revoked_at=NOW + timedelta(hours=1),
    )
    assert not revoked.is_due(NOW + timedelta(hours=2))

    with pytest.raises(ValidationError):
        AutomationGrantScope(
            provider=Provider.CODEX,
            project_id=PROJECT,
            metric_keys=("prompt.context_sufficiency",),
            remote_requires_fresh_approval=False,
        )
