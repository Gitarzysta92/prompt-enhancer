"""Fitness checks for the deliberately unimplemented PostgreSQL design."""

from __future__ import annotations

from pathlib import Path


DESIGN = (
    Path(__file__).resolve().parents[1] / "docs" / "control-plane-postgres-rls.md"
)


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def _section(design: str, start: str, end: str) -> str:
    return design.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def test_sensitive_select_uses_one_combined_policy_not_permissive_or() -> None:
    design = _design()
    assert "Status: design only" in design
    assert "CREATE POLICY snapshots_tenant_isolation" not in design
    assert design.count("CREATE POLICY snapshots_select_combined") == 1
    select_policy = design.split(
        "CREATE POLICY snapshots_select_combined", maxsplit=1
    )[1].split("CREATE POLICY snapshots_insert_combined", maxsplit=1)[0]
    for required_gate in (
        "app.organization_id",
        "remote_sync_enabled",
        "snapshots:pull",
        "JOIN devices d",
        "d.state = 'active'",
        "tm.state = 'active'",
        "visibility = 'team'",
        "manager_access_grants",
        "statement_timestamp() < g.expires_at",
        "statement_timestamp() < g.revoked_at",
    ):
        assert required_gate in select_policy
    assert "every additional policy\nmust be declared `AS RESTRICTIVE`" in design


def test_reserve_without_consumption_is_bounded_and_never_enters_audit() -> None:
    design = _design()
    reservation = _section(
        design,
        "CREATE TABLE envelope_reservations",
        "CREATE TABLE measurement_definition_versions",
    )
    normalized_reservation = " ".join(reservation.split())
    for bound in (
        "expires_at timestamptz NOT NULL",
        "UNIQUE (organization_id, subject_user_id, client_id, device_id)",
        "expires_at <= issued_at + interval '5 minutes'",
    ):
        assert bound in normalized_reservation

    audit = _section(
        design,
        "CREATE TABLE audit_events",
        "A grant names exactly one target",
    )
    assert "envelope_id" not in audit
    audit_rules = _section(
        design,
        "Audit has no free-text detail column",
        "## 6. RLS without permissive-OR bypass",
    )
    normalized_design = " ".join(design.split()).lower()
    for invariant in (
        "no reservation or envelope identifier",
        "inaccessible before that event",
        "accepted, rejected, expired, wrong-owner",
        "successful push consumes the slot and permits a fresh reservation",
        "development adapter's recipient payload can carry accepted envelope IDs",
    ):
        assert invariant.lower() in normalized_design
    assert "caller-visible reservation ID is never persisted" in audit_rules


def test_snapshot_insert_requires_active_team_membership_for_any_team_id() -> None:
    design = _design()
    team_membership = _section(
        design,
        "CREATE TABLE team_memberships",
        "CREATE TABLE devices",
    )
    assert "state text NOT NULL CHECK (state IN ('active','revoked'))" in (
        team_membership
    )
    assert "CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))" in (
        team_membership
    )

    insert_policy = _section(
        design,
        "CREATE POLICY snapshots_insert_combined",
        "ALTER TABLE recipient_stream_items",
    )
    normalized = " ".join(insert_policy.split())
    for gate in (
        "snapshots.team_id IS NULL OR EXISTS",
        "FROM team_memberships tm",
        "(tm.organization_id, tm.team_id, tm.user_id) = ( snapshots.organization_id, snapshots.team_id, snapshots.subject_user_id )",
        "current_setting('app.user_id', true)",
        "tm.state = 'active'",
    ):
        assert gate in normalized


def test_recipient_retry_is_a_durable_projection_not_a_source_join() -> None:
    design = _design()
    stream = _section(
        design,
        "CREATE TABLE recipient_stream_items",
        "CREATE TABLE recipient_snapshot_payloads",
    )
    assert "source_snapshot_id" not in stream
    assert "REFERENCES snapshots" not in stream

    payload = _section(
        design,
        "CREATE TABLE recipient_snapshot_payloads",
        "CREATE TABLE recipient_snapshot_measurements",
    )
    for forbidden in (
        "source_snapshot_id",
        "content_digest",
        "envelope_id",
        "REFERENCES snapshots",
    ):
        assert forbidden not in payload
    assert "recipient_subject_handle opaque_id NOT NULL" in payload
    assert "REFERENCES recipient_stream_items" in payload

    accessor = _section(
        design,
        "### Exact recipient retry accessor",
        "Other tenant tables receive one combined tenant policy",
    )
    for recipient_table in (
        "recipient_stream_items",
        "recipient_snapshot_payloads",
        "recipient_snapshot_measurements",
        "sync_checkpoints",
    ):
        assert recipient_table in accessor
    assert "FROM snapshots" not in accessor
    assert "JOIN snapshots" not in accessor
    assert "manager_access_grants" not in accessor
    assert "Current snapshot visibility and manager grants" in design
    assert "already-offered, unacknowledged projection remains retryable" in (
        " ".join(accessor.split())
    )


def test_recipient_and_checkpoint_rls_require_the_full_live_session() -> None:
    design = _design()
    policy_ranges = (
        (
            "CREATE POLICY recipient_stream_select_combined",
            "ALTER TABLE recipient_snapshot_payloads",
        ),
        (
            "CREATE POLICY recipient_payload_select_combined",
            "ALTER TABLE recipient_snapshot_measurements",
        ),
        (
            "CREATE POLICY recipient_measurement_select_combined",
            "ALTER TABLE sync_checkpoints",
        ),
    )
    required_gates = (
        "app.organization_id",
        "app.user_id",
        "app.client_id",
        "app.device_id",
        "remote_sync_enabled",
        "JOIN devices d",
        "c.state = 'active'",
        "d.state = 'active'",
        "m.state = 'active'",
        "s.scope = 'snapshots:pull'",
    )
    for start, end in policy_ranges:
        policy = _section(design, start, end)
        for gate in required_gates:
            assert gate in policy
        assert "manager_access_grants" not in policy

    checkpoint = _section(
        design,
        "CREATE POLICY sync_checkpoint_owner_combined",
        "### Exact recipient retry accessor",
    )
    assert "USING (" in checkpoint
    assert "WITH CHECK (" in checkpoint
    for gate in required_gates:
        assert checkpoint.count(gate) >= 2
    assert "manager_access_grants" not in checkpoint


def test_schema_design_requires_composite_tenant_bindings_and_epoch_fence() -> None:
    design = _design()
    for invariant in (
        "FOREIGN KEY (organization_id, user_id, device_id)",
        "FOREIGN KEY (organization_id, subject_user_id, client_id, device_id)",
        "subject_epoch bigint NOT NULL",
        "snapshot_delivery_ledger",
        "recipient_stream_items",
        "recipient-specific tombstone",
        "increment it, and delete **all** unconsumed",
    ):
        assert invariant in design


def test_design_keeps_aggregate_release_closed_pending_composition_controls() -> None:
    design = _design()
    aggregate_section = design.split("## 8. Aggregates fail closed", maxsplit=1)[1]
    normalized = " ".join(aggregate_section.split())
    for blocker in (
        "stable privacy-cohort membership",
        "overlap rules",
        "longitudinal composition",
        "persisted per-principal query budget",
        "budget consumption atomicity",
    ):
        assert blocker in normalized
    assert "No production aggregate table or release policy may be added" in (
        normalized
    )
