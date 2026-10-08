"""Loopback HTTP wiring and credential-bound identity tests."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.control_plane import (
    ApiScope,
    MeasurementDefinitionVersion,
    MeasurementUnit,
    OrganizationRole,
    ProducerAdapterVersion,
    ReportingBucket,
    ReportingBucketKind,
    SnapshotEnvelope,
    SnapshotMeasurement,
    SnapshotMetricKey,
    VisibilityScope,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.control_plane import (
    create_development_control_plane,
    sign_development_envelope,
)
from prompt_enhancer.interfaces.http.control_plane_routes import (
    CONTROL_PLANE_CREDENTIAL_HEADER,
)


TOKEN = "example_control_plane_token_123456789"
PERIOD = ReportingBucket(kind=ReportingBucketKind.ISO_WEEK, key="2047-W10")
NOW = PERIOD.end + timedelta(hours=1)
ALL_SCOPES = tuple(sorted(ApiScope, key=lambda scope: scope.value))


class EmptyReadStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self) -> list[dict[str, object]]:
        return []

    def list_sessions(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        return []

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]:
        return []


def _fixture(tmp_path, *, enabled: bool = True, wired: bool = True):  # type: ignore[no-untyped-def]
    plane = create_development_control_plane(lambda: NOW)
    organization = plane.create_organization(now=NOW, sync_enabled=True)
    team = plane.create_team(organization.organization_id, now=NOW)
    owner = plane.provision_seat(
        organization.organization_id,
        now=NOW,
        role=OrganizationRole.OWNER,
        team_ids=(team.team_id,),
        scopes=ALL_SCOPES,
    )
    peer = plane.provision_seat(
        organization.organization_id,
        now=NOW,
        team_ids=(team.team_id,),
        scopes=ALL_SCOPES,
    )
    app = create_app(
        settings=AppSettings(
            home=tmp_path, control_plane_development_api=enabled
        ),
        database=EmptyReadStore(),
        api_token=TOKEN,
        control_plane_service=plane.service if wired else None,
        control_plane_principal_resolver=plane.resolver if wired else None,
    )
    return app, plane, organization, team, owner, peer


def _headers(seat):  # type: ignore[no-untyped-def]
    return {
        API_TOKEN_HEADER: TOKEN,
        CONTROL_PLANE_CREDENTIAL_HEADER: seat.credential.get_secret_value(),
    }


def _signed(plane, organization, seat, envelope_id):  # type: ignore[no-untyped-def]
    envelope = SnapshotEnvelope(
        envelope_id=envelope_id,
        visibility=VisibilityScope.ORGANIZATION,
        period=PERIOD,
        issued_at=NOW,
        measurement_definition_version=(
            MeasurementDefinitionVersion.COACHING_FREE_OPERATIONS_V1
        ),
        producer_adapter_version=ProducerAdapterVersion.DEVELOPMENT_V1,
        measurements=(
            SnapshotMeasurement(
                key=SnapshotMetricKey.SESSIONS_STARTED,
                unit=MeasurementUnit.COUNT,
                value=3.0,
                observed_count=1,
                eligible_count=1,
            ),
        ),
    )
    return sign_development_envelope(seat.device_key, envelope)


def test_routes_are_default_off_and_require_service_plus_resolver(tmp_path) -> None:
    assert AppSettings(home=tmp_path).control_plane_development_api is False
    disabled, *_ = _fixture(tmp_path / "disabled", enabled=False)
    unwired, *_ = _fixture(tmp_path / "unwired", wired=False)

    for app in (disabled, unwired):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            response = client.get(
                "/v1/control-plane/readiness", headers={API_TOKEN_HEADER: TOKEN}
            )
        assert response.status_code == 404


def test_only_exact_opt_in_enables_loopback_development_api(tmp_path) -> None:
    base = {"PROMPT_ENHANCER_HOME": str(tmp_path)}
    for value in ("", "0", "false", "true", "1", "enabled "):
        assert AppSettings.from_env(
            {**base, "PROMPT_ENHANCER_CONTROL_PLANE_DEV_API": value}
        ).control_plane_development_api is False
    assert AppSettings.from_env(
        {**base, "PROMPT_ENHANCER_CONTROL_PLANE_DEV_API": "enabled"}
    ).control_plane_development_api is True


def test_data_routes_require_bound_credential_and_reject_body_identity(tmp_path) -> None:
    app, plane, organization, _team, owner, peer = _fixture(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        no_credential = client.post(
            "/v1/control-plane/envelope-identifiers",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        unknown = client.post(
            "/v1/control-plane/envelope-identifiers",
            headers={
                API_TOKEN_HEADER: TOKEN,
                CONTROL_PLANE_CREDENTIAL_HEADER: "z" * 48,
            },
        )
        identifier = client.post(
            "/v1/control-plane/envelope-identifiers", headers=_headers(owner)
        )
        signed = _signed(
            plane, organization, owner, identifier.json()["envelope_id"]
        )
        body = {"signed_envelope": signed.model_dump(mode="json")}
        accepted = client.post(
            "/v1/control-plane/snapshots", json=body, headers=_headers(owner)
        )
        asserted_actor = client.post(
            "/v1/control-plane/snapshots",
            json={
                **body,
                "actor": {
                    "organization_id": organization.organization_id,
                    "user_id": peer.membership.user_id,
                    "client_id": peer.client.client_id,
                    "device_id": peer.device.device_id,
                },
            },
            headers=_headers(owner),
        )

    assert no_credential.status_code == 401
    assert unknown.status_code == 401
    assert identifier.status_code == 200
    assert accepted.status_code == 200
    assert asserted_actor.status_code == 422
    assert owner.membership.user_id not in accepted.text
    assert peer.membership.user_id not in accepted.text


def test_http_acknowledgement_redelivers_then_advances(tmp_path) -> None:
    app, plane, organization, _team, owner, _peer = _fixture(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        identifier = client.post(
            "/v1/control-plane/envelope-identifiers", headers=_headers(owner)
        ).json()["envelope_id"]
        signed = _signed(plane, organization, owner, identifier)
        pushed = client.post(
            "/v1/control-plane/snapshots",
            json={"signed_envelope": signed.model_dump(mode="json")},
            headers=_headers(owner),
        )
        first = client.post(
            "/v1/control-plane/deltas", json={}, headers=_headers(owner)
        )
        repeated = client.post(
            "/v1/control-plane/deltas", json={}, headers=_headers(owner)
        )
        acknowledged = client.post(
            "/v1/control-plane/deltas",
            json={"acknowledge_through": first.json()["next_cursor"]["sequence"]},
            headers=_headers(owner),
        )
        rewound = client.post(
            "/v1/control-plane/deltas",
            json={"acknowledge_through": 0},
            headers=_headers(owner),
        )

    assert pushed.status_code == 200
    assert first.json()["items"] == repeated.json()["items"]
    assert len(first.json()["items"]) == 1
    assert acknowledged.json()["items"] == []
    assert acknowledged.json()["acknowledged_cursor"]["sequence"] == 1
    assert rewound.status_code == 409
    assert rewound.json()["detail"]["code"] == "cursor_regression"
    assert first.headers["cache-control"] == "no-store, private"


def test_revoked_credential_is_rejected_at_authentication_boundary(tmp_path) -> None:
    app, plane, _organization, _team, owner, peer = _fixture(tmp_path)
    plane.service.revoke_device(owner.identity, peer.device.device_id)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/v1/control-plane/deltas", json={}, headers=_headers(peer)
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "credential_rejected"


def test_manager_grant_revocation_route_uses_authenticated_administrator(
    tmp_path,
) -> None:
    app, plane, organization, team, owner, peer = _fixture(tmp_path)
    manager = plane.provision_seat(
        organization.organization_id,
        now=NOW,
        role=OrganizationRole.MANAGER,
        team_ids=(team.team_id,),
        scopes=ALL_SCOPES,
    )
    grant = plane.grant_manager_access(
        organization.organization_id,
        manager_user_id=manager.membership.user_id,
        subject_user_id=peer.membership.user_id,
        granted_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        denied = client.post(
            "/v1/control-plane/manager-grant-revocations",
            json={"grant_id": grant.grant_id},
            headers=_headers(peer),
        )
        revoked = client.post(
            "/v1/control-plane/manager-grant-revocations",
            json={"grant_id": grant.grant_id},
            headers=_headers(owner),
        )

    assert denied.status_code == 403
    assert revoked.status_code == 200
    assert revoked.json()["grant_id"] == grant.grant_id
    assert revoked.json()["revoked_at"] is not None
