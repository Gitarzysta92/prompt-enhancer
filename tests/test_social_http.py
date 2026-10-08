"""HTTP boundary tests for the default-off loopback social development API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.social import (
    DEVELOPMENT_SOCIAL_GAPS,
    SocialReadinessGap,
    VerifiedSocialPrincipal,
    development_social_readiness,
    durable_local_social_readiness,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.infrastructure.social import (
    SocialSqliteDatabase,
    create_development_social_foundation,
    create_sqlite_social_foundation,
)
from prompt_enhancer.interfaces.http import (
    create_social_mutation_router,
    create_social_readiness_router,
)
from prompt_enhancer.interfaces.http.browser_session import (
    BROWSER_SESSION_COOKIE,
    CSRF_HEADER,
    BrowserSessionManager,
)
from prompt_enhancer.interfaces.http.social_routes import SOCIAL_CREDENTIAL_HEADER

from test_social_service import (
    ALICE,
    ALICE_DEVICE,
    BOB,
    BOB_DEVICE,
    Clock,
    ORG,
    UNKNOWN,
    provision,
)

TOKEN = "t" * 32
ALICE_CREDENTIAL = "synthetic-social-credential-alice-" + "a" * 32
BOB_CREDENTIAL = "synthetic-social-credential-bob-" + "b" * 32
MUTATION_PATHS = (
    "/v1/social/friend-requests",
    "/v1/social/friend-requests/decisions",
    "/v1/social/friends/removals",
    "/v1/social/blocks",
    "/v1/social/blocks/removals",
    "/v1/social/direct-conversations",
    "/v1/social/account-metadata-deletions",
)


@dataclass
class SyntheticResolver:
    principals: dict[str, VerifiedSocialPrincipal] = field(default_factory=dict)
    seen: list[str] = field(default_factory=list)

    def resolve(self, opaque_credential: str) -> VerifiedSocialPrincipal | None:
        self.seen.append(opaque_credential)
        return self.principals.get(opaque_credential)


def foundation_and_resolver():
    clock = Clock()
    foundation = create_development_social_foundation(clock)
    alice = provision(foundation.state, ALICE, ALICE_DEVICE)
    bob = provision(foundation.state, BOB, BOB_DEVICE)
    resolver = SyntheticResolver({ALICE_CREDENTIAL: alice, BOB_CREDENTIAL: bob})
    return foundation, resolver


def build_client(
    tmp_path: Path,
    *,
    enabled: bool,
    readiness=None,
    service=None,
    resolver=None,
    name: str = "app",
    sessions: BrowserSessionManager | None = None,
) -> TestClient:
    settings = AppSettings(home=tmp_path, social_development_api=enabled)
    return TestClient(
        create_app(
            settings=settings,
            database=Database(tmp_path / f"metrics-{name}.sqlite3"),
            api_token=TOKEN,
            social_readiness=readiness,
            social_service=service,
            social_principal_resolver=resolver,
            browser_session_manager=sessions,
        ),
        base_url="http://127.0.0.1:8765",
    )


def social_paths(client: TestClient) -> set[str]:
    discovered: set[str] = set()

    def visit(routes: object) -> None:
        for route in routes:  # type: ignore[union-attr]
            path = getattr(route, "path", "")
            if path.startswith("/v1/social"):
                discovered.add(path)
            # FastAPI releases may retain included routers lazily rather than
            # flattening their APIRoutes into app.routes. Inspect the retained
            # public router's route list so this test asserts the same mounted
            # surface under both representations.
            included = getattr(route, "original_router", None)
            if included is not None:
                visit(included.routes)

    visit(client.app.routes)
    return discovered


def test_flag_is_exact_default_off_and_loopback_only(tmp_path: Path) -> None:
    assert AppSettings(home=tmp_path).social_development_api is False
    env = {"PROMPT_ENHANCER_HOME": str(tmp_path)}
    for value in ("true", "1", "yes", "ENABLED", " enabled"):
        assert (
            AppSettings.from_env(
                {**env, "PROMPT_ENHANCER_SOCIAL_DEV_API": value}
            ).social_development_api
            is False
        )
    assert (
        AppSettings.from_env(
            {**env, "PROMPT_ENHANCER_SOCIAL_DEV_API": "enabled"}
        ).social_development_api
        is True
    )
    with pytest.raises(ValidationError, match="loopback"):
        AppSettings(home=tmp_path, host="0.0.0.0", social_development_api=True)
    with pytest.raises(ValidationError, match="loopback"):
        AppSettings(home=tmp_path, host="192.0.2.10", social_development_api=True)


def test_durable_local_readiness_removes_only_the_separated_store_gap(
    tmp_path: Path,
) -> None:
    durable = durable_local_social_readiness(enabled=True)
    development = development_social_readiness(enabled=True)
    assert durable.production_ready is False
    assert SocialReadinessGap.SOCIAL_STORE_NOT_SEPARATED not in durable.gaps
    assert set(durable.gaps) == set(DEVELOPMENT_SOCIAL_GAPS) - {
        SocialReadinessGap.SOCIAL_STORE_NOT_SEPARATED
    }
    for gap in (
        SocialReadinessGap.IDENTITY_PROVIDER_UNAVAILABLE,
        SocialReadinessGap.DEVICE_PROOF_OF_POSSESSION_UNAVAILABLE,
        SocialReadinessGap.REVIEWED_E2EE_ADAPTER_UNAVAILABLE,
        SocialReadinessGap.FORWARD_SECRECY_UNAVAILABLE,
        SocialReadinessGap.AUTHENTICATED_SIGNALING_UNAVAILABLE,
        SocialReadinessGap.DIRECT_CONNECTIVITY_UNVERIFIED,
        SocialReadinessGap.DURABLE_MULTI_DEVICE_SYNC_UNAVAILABLE,
        SocialReadinessGap.BACKUP_RECOVERY_UNAVAILABLE,
        SocialReadinessGap.ABUSE_REPORTING_UNAVAILABLE,
        SocialReadinessGap.METADATA_VISIBLE_TO_CONTROL_PLANE,
    ):
        assert gap in durable.gaps
    assert durable.capabilities == development.capabilities
    states = {item.capability: item.state.value for item in durable.capabilities}
    assert states["e2ee"] == "unavailable"
    assert states["multi_device_sync"] == "unavailable"
    assert durable_local_social_readiness(enabled=False) == development_social_readiness(
        enabled=False
    )

    foundation = create_sqlite_social_foundation(
        SocialSqliteDatabase.under(tmp_path), Clock()
    )
    try:
        assert foundation.readiness(enabled=True) == durable
        assert foundation.readiness(enabled=False).enabled is False
    finally:
        foundation.close()


def test_default_flag_mounts_no_social_route_even_with_dependencies(
    tmp_path: Path,
) -> None:
    foundation, resolver = foundation_and_resolver()
    client = build_client(
        tmp_path,
        enabled=False,
        readiness=durable_local_social_readiness(enabled=True),
        service=foundation.service,
        resolver=resolver,
    )
    assert social_paths(client) == set()
    headers = {API_TOKEN_HEADER: TOKEN, SOCIAL_CREDENTIAL_HEADER: ALICE_CREDENTIAL}
    assert client.get("/v1/social/readiness", headers=headers).status_code == 404
    for path in MUTATION_PATHS:
        assert client.post(path, json={}, headers=headers).status_code == 404
    assert resolver.seen == []
    assert not (tmp_path / "social.sqlite3").exists()


def test_readiness_only_mounts_readiness_and_every_mutation_is_404(
    tmp_path: Path,
) -> None:
    client = build_client(
        tmp_path, enabled=True, readiness=durable_local_social_readiness(enabled=True)
    )
    assert social_paths(client) == {"/v1/social/readiness"}
    assert client.get("/v1/social/readiness").status_code == 401
    response = client.get("/v1/social/readiness", headers={API_TOKEN_HEADER: TOKEN})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert body["production_ready"] is False
    assert "social_store_not_separated" not in body["gaps"]
    assert "reviewed_e2ee_adapter_unavailable" in body["gaps"]
    for path in MUTATION_PATHS:
        assert (
            client.post(path, json={}, headers={API_TOKEN_HEADER: TOKEN}).status_code
            == 404
        )


def test_service_without_resolver_or_resolver_without_service_mounts_nothing(
    tmp_path: Path,
) -> None:
    foundation, resolver = foundation_and_resolver()
    only_service = build_client(
        tmp_path, enabled=True, service=foundation.service, name="service"
    )
    only_resolver = build_client(tmp_path, enabled=True, resolver=resolver, name="resolver")
    assert social_paths(only_service) == set()
    assert social_paths(only_resolver) == set()
    with pytest.raises(TypeError):
        create_social_mutation_router(lambda: None, foundation.service, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        create_social_mutation_router(lambda: None, None, resolver)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        create_social_readiness_router(lambda: None, None)  # type: ignore[arg-type]
    assert not (tmp_path / "social.sqlite3").exists()


def test_local_auth_alone_cannot_mutate_and_credential_failures_are_uniform(
    tmp_path: Path,
) -> None:
    foundation, resolver = foundation_and_resolver()
    sessions = BrowserSessionManager()
    client = build_client(
        tmp_path,
        enabled=True,
        service=foundation.service,
        resolver=resolver,
        sessions=sessions,
    )
    assert social_paths(client) == set(MUTATION_PATHS)
    body = {"target_account_id": BOB}

    # Local API token alone: authenticated to the app, but no social principal.
    missing = client.post(
        "/v1/social/friend-requests", json=body, headers={API_TOKEN_HEADER: TOKEN}
    )
    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "credential_rejected"}}
    assert missing.headers["cache-control"] == "no-store, private"

    # Browser session with valid CSRF and origin: still no social principal.
    grant = client.get("/auth/session").json()
    session = client.post(
        "/v1/social/friend-requests",
        json=body,
        headers={CSRF_HEADER: grant["csrf_token"], "Origin": "http://127.0.0.1:8765"},
    )
    assert client.cookies.get(BROWSER_SESSION_COOKIE)
    assert session.status_code == 401
    assert session.json() == {"detail": {"code": "credential_rejected"}}

    short = client.post(
        "/v1/social/friend-requests",
        json=body,
        headers={API_TOKEN_HEADER: TOKEN, SOCIAL_CREDENTIAL_HEADER: "short"},
    )
    rejected = client.post(
        "/v1/social/friend-requests",
        json=body,
        headers={API_TOKEN_HEADER: TOKEN, SOCIAL_CREDENTIAL_HEADER: "x" * 64},
    )
    oversized = client.post(
        "/v1/social/friend-requests",
        json=body,
        headers={API_TOKEN_HEADER: TOKEN, SOCIAL_CREDENTIAL_HEADER: "y" * 257},
    )
    assert short.json() == rejected.json() == oversized.json() == missing.json()
    assert short.status_code == rejected.status_code == oversized.status_code == 401
    assert "short" not in resolver.seen and "y" * 257 not in resolver.seen
    for response in (missing, session, short, rejected, oversized):
        assert "x" * 64 not in response.text
        assert TOKEN not in response.text
    assert len(foundation.state.requests) == 0


def test_valid_credential_derives_caller_and_body_cannot_override_identity(
    tmp_path: Path,
) -> None:
    foundation, resolver = foundation_and_resolver()
    client = build_client(
        tmp_path, enabled=True, service=foundation.service, resolver=resolver
    )
    alice_headers = {API_TOKEN_HEADER: TOKEN, SOCIAL_CREDENTIAL_HEADER: ALICE_CREDENTIAL}
    bob_headers = {API_TOKEN_HEADER: TOKEN, SOCIAL_CREDENTIAL_HEADER: BOB_CREDENTIAL}

    # Caller identity fields in the body are rejected, not honoured.
    for forged in (
        {"target_account_id": BOB, "requester_account_id": BOB},
        {"target_account_id": BOB, "account_id": BOB},
        {"target_account_id": BOB, "device_id": BOB_DEVICE},
        {"target_account_id": BOB, "organization_id": ORG},
        {"target_account_id": BOB, "message_text": "hello"},
        {"target_account_id": "not-a-social-id"},
    ):
        response = client.post(
            "/v1/social/friend-requests", json=forged, headers=alice_headers
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "request validation failed"}

    created = client.post(
        "/v1/social/friend-requests",
        json={"target_account_id": BOB},
        headers=alice_headers,
    )
    assert created.status_code == 201
    request = created.json()
    assert request["requester_account_id"] == ALICE
    assert request["recipient_account_id"] == BOB
    assert created.headers["cache-control"] == "no-store, private"

    # Alice cannot decide her own request; the decision is bound to Bob's credential.
    own = client.post(
        "/v1/social/friend-requests/decisions",
        json={"request_id": request["request_id"], "accept": True},
        headers=alice_headers,
    )
    assert own.status_code in {403, 409}
    accepted = client.post(
        "/v1/social/friend-requests/decisions",
        json={"request_id": request["request_id"], "accept": True},
        headers=bob_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "accepted"

    conversation = client.post(
        "/v1/social/direct-conversations",
        json={"friend_account_id": BOB},
        headers=alice_headers,
    )
    assert conversation.status_code == 201
    assert conversation.json()["member_account_ids"] == sorted([ALICE, BOB])
    assert conversation.json()["kind"] == "direct"

    # Blocked and unknown targets share one 403 class with a closed reason code.
    unknown = client.post(
        "/v1/social/friend-requests",
        json={"target_account_id": UNKNOWN},
        headers=alice_headers,
    )
    blocked = client.post("/v1/social/blocks", json={"target_account_id": BOB}, headers=alice_headers)
    assert blocked.status_code == 201
    assert blocked.json()["blocker_account_id"] == ALICE
    after_block = client.post(
        "/v1/social/direct-conversations",
        json={"friend_account_id": BOB},
        headers=alice_headers,
    )
    assert unknown.status_code == after_block.status_code == 403
    assert unknown.json() == after_block.json() == {
        "detail": {"code": "relationship_unavailable"}
    }
    duplicate_block = client.post(
        "/v1/social/blocks", json={"target_account_id": BOB}, headers=alice_headers
    )
    assert duplicate_block.status_code == 201  # idempotent existing block
    unblocked = client.post(
        "/v1/social/blocks/removals", json={"target_account_id": BOB}, headers=alice_headers
    )
    assert unblocked.status_code == 200 and unblocked.json() == {"removed": True}
    removal = client.post(
        "/v1/social/friends/removals", json={"target_account_id": BOB}, headers=alice_headers
    )
    assert removal.status_code == 403  # block already removed the friendship

    deletion = client.post("/v1/social/account-metadata-deletions", headers=alice_headers)
    assert deletion.status_code == 200
    receipt = deletion.json()
    assert receipt["account_id"] == ALICE
    assert receipt["local_metadata_erased"] is False
    assert receipt["remote_plaintext_recall_guaranteed"] is False
    for response in (created, accepted, conversation, blocked, deletion):
        assert ALICE_CREDENTIAL not in response.text
        assert BOB_CREDENTIAL not in response.text
        assert "Traceback" not in response.text


def test_no_message_or_file_routes_and_openapi_stays_disabled(tmp_path: Path) -> None:
    foundation, resolver = foundation_and_resolver()
    client = build_client(
        tmp_path,
        enabled=True,
        readiness=durable_local_social_readiness(enabled=True),
        service=foundation.service,
        resolver=resolver,
    )
    paths = social_paths(client)
    assert paths == {"/v1/social/readiness", *MUTATION_PATHS}
    for forbidden in ("message", "envelope", "file", "transfer", "manifest", "presence"):
        assert not any(forbidden in path for path in paths)
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
