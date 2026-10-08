"""Synthetic HTTP tests for content-free requirement-verification evidence."""

from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    RequirementCoordinate,
)
from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    AppIssuedRequirementVerificationOpportunity,
    AppIssuedRequirementVerificationOpportunitySet,
    AppIssuedRequirementVerificationResult,
    ExplicitRequirementAcceptanceAuthority,
    RequirementAcceptanceOutcome,
    RequirementVerificationEvidenceSet,
    RequirementVerificationMethod,
    RequirementVerificationOutcome,
)
from prompt_enhancer.application.analysis.requirement_verification_persistence import (
    MAX_REQUIREMENT_VERIFICATION_REVISIONS,
    REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    RequirementAcceptanceAppendCommand,
    RequirementVerificationAuthorityHead,
    RequirementVerificationAuthorityRecordKind,
    RequirementVerificationConflictError,
    RequirementVerificationDefinitionsOutOfDateError,
    RequirementVerificationEvidenceSnapshot,
    RequirementVerificationInputError,
    RequirementVerificationNotFoundError,
    RequirementVerificationPersistenceError,
    RequirementVerificationResultAppendCommand,
    RequirementVerificationStaleWindowError,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.browser_session import (
    BROWSER_SESSION_COOKIE,
    CSRF_HEADER,
)
from prompt_enhancer.interfaces.http.requirement_verification_evidence_routes import (
    RequirementVerificationMessageErrorDto,
)
from prompt_enhancer.interfaces.http.user_presence import (
    USER_PRESENCE_HEADER,
    UserPresenceApprovalManager,
)


TOKEN = "example_requirement_verification_token_do_not_use_123456789"


def _id(value: int) -> str:
    return f"{value:064x}"


class _Store:
    def initialize(self) -> None:
        pass


def _opportunity_set() -> AppIssuedRequirementVerificationOpportunitySet:
    return AppIssuedRequirementVerificationOpportunitySet(
        session_id=_id(1),
        source_window_fingerprint=_id(2),
        requirement_plan_confirmation_id=_id(3),
        requirement_plan_proposal_id=_id(4),
        requirement_plan_evidence_fingerprint=_id(5),
        opportunities=(
            AppIssuedRequirementVerificationOpportunity(
                opportunity_id=_id(6),
                requirement_index=0,
                requirement_id=_id(7),
                coordinate=RequirementCoordinate(
                    message_sequence=8,
                    clause_index=0,
                ),
            ),
        ),
        opportunity_set_fingerprint=_id(9),
    )


def _result() -> AppIssuedRequirementVerificationResult:
    return AppIssuedRequirementVerificationResult(
        result_id=_id(10),
        opportunity_set_fingerprint=_id(9),
        opportunity_id=_id(6),
        requirement_id=_id(7),
        observed_sequence=11,
        method=RequirementVerificationMethod.TEST,
        outcome=RequirementVerificationOutcome.PASSED,
        receipt_reference_ids=(_id(12),),
        result_fingerprint=_id(13),
    )


def _acceptance() -> ExplicitRequirementAcceptanceAuthority:
    return ExplicitRequirementAcceptanceAuthority(
        acceptance_id=_id(14),
        opportunity_set_fingerprint=_id(9),
        opportunity_id=_id(6),
        requirement_id=_id(7),
        confirmation_id=_id(15),
        outcome=RequirementAcceptanceOutcome.ACCEPTED,
        acceptance_fingerprint=_id(16),
    )


def _snapshot(kind: str = "empty") -> RequirementVerificationEvidenceSnapshot:
    opportunities = _opportunity_set()
    results = (_result(),) if kind == "result" else ()
    acceptances = (_acceptance(),) if kind == "acceptance" else ()
    if kind == "result":
        heads = (
            RequirementVerificationAuthorityHead(
                opportunity_id=_id(6),
                authority_record_id=_id(10),
                kind=RequirementVerificationAuthorityRecordKind.OBJECTIVE_RESULT,
                revision=1,
            ),
        )
    elif kind == "acceptance":
        heads = (
            RequirementVerificationAuthorityHead(
                opportunity_id=_id(6),
                authority_record_id=_id(14),
                kind=RequirementVerificationAuthorityRecordKind.NATIVE_ACCEPTANCE,
                revision=1,
            ),
        )
    else:
        heads = ()
    return RequirementVerificationEvidenceSnapshot(
        evidence=RequirementVerificationEvidenceSet(
            opportunities=opportunities,
            verification_results=results,
            acceptance_authorities=acceptances,
            evidence_set_fingerprint={
                "empty": _id(17),
                "result": _id(18),
                "acceptance": _id(19),
            }[kind],
        ),
        revision=0 if kind == "empty" else 1,
        authority_heads=heads,
    )


class _Service:
    def __init__(self) -> None:
        self.applied = True
        self.errors: dict[str, Exception] = {}
        self.calls: list[tuple[object, ...]] = []

    def _raise(self, method: str) -> None:
        error = self.errors.get(method)
        if error is not None:
            raise error

    def issue_current_opportunities(
        self, session_id: str
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]:
        self._raise("issue")
        self.calls.append(("issue", session_id))
        return _snapshot(), self.applied

    def snapshot(
        self,
        session_id: str,
        opportunity_set_fingerprint: str,
        *,
        through_revision: int | None = None,
    ) -> RequirementVerificationEvidenceSnapshot:
        self._raise("snapshot")
        self.calls.append(
            (
                "snapshot",
                session_id,
                opportunity_set_fingerprint,
                through_revision,
            )
        )
        return _snapshot()

    def append_objective_result(
        self,
        *,
        session_id: str,
        command: RequirementVerificationResultAppendCommand,
        idempotency_key: str,
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]:
        self._raise("result")
        self.calls.append(("result", session_id, command, idempotency_key))
        return _snapshot("result"), self.applied

    def append_acceptance(
        self,
        *,
        session_id: str,
        command: RequirementAcceptanceAppendCommand,
        idempotency_key: str,
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]:
        self._raise("acceptance")
        self.calls.append(("acceptance", session_id, command, idempotency_key))
        return _snapshot("acceptance"), self.applied


def _app(tmp_path, service: _Service, *, presence=None):  # type: ignore[no-untyped-def]
    return create_app(
        settings=AppSettings(home=tmp_path),
        database=_Store(),  # type: ignore[arg-type]
        api_token=TOKEN,
        requirement_verification_evidence_service=service,  # type: ignore[arg-type]
        user_presence_confirmation=presence,
    )


def _private(response) -> None:  # type: ignore[no-untyped-def]
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"


def test_issue_snapshot_and_preissued_result_are_authenticated_and_content_free(
    tmp_path,
) -> None:
    service = _Service()
    app = _app(tmp_path, service)
    base = f"/v1/sessions/{_id(1)}/requirement-verification-evidence"
    token_headers = {API_TOKEN_HEADER: TOKEN}
    result_command = RequirementVerificationResultAppendCommand(
        result=_result(),
        expected_predecessor_authority_id=None,
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        denied = client.post(f"{base}/opportunity-sets/current")
        issued = client.post(
            f"{base}/opportunity-sets/current",
            headers=token_headers,
        )
        service.applied = False
        replay = client.post(
            f"{base}/opportunity-sets/current",
            headers=token_headers,
        )
        current = client.get(
            f"{base}/opportunity-sets/{_id(9)}",
            params={"through_revision": 0},
            headers=token_headers,
        )
        service.applied = True
        appended = client.post(
            f"{base}/objective-results",
            headers={
                **token_headers,
                "Idempotency-Key": "synthetic-result-append-0001",
            },
            json=result_command.model_dump(mode="json"),
        )

    for response in (denied, issued, replay, current, appended):
        _private(response)
    assert denied.status_code == 401
    assert issued.status_code == 201
    assert issued.json()["applied"] is True
    assert replay.status_code == 200
    assert replay.json()["applied"] is False
    assert current.status_code == 200
    assert current.json()["revision"] == 0
    assert service.calls[2] == ("snapshot", _id(1), _id(9), 0)
    assert appended.status_code == 201
    result_body = appended.json()["snapshot"]
    assert result_body["revision"] == 1
    assert result_body["authority_heads"] == [
        {
            "opportunity_id": _id(6),
            "authority_record_id": _id(10),
            "kind": "objective_result",
            "revision": 1,
        }
    ]
    captured = service.calls[-1]
    assert captured[0:2] == ("result", _id(1))
    assert captured[2] == result_command
    assert captured[3] == "synthetic-result-append-0001"
    serialized = json.dumps(result_body, sort_keys=True).casefold()
    for prohibited in (
        "idempotency_key",
        "idempotency_key_digest",
        "command_fingerprint",
        "prompt",
        "transcript",
        "excerpt",
        "file_path",
        "raw_content",
    ):
        assert prohibited not in serialized


def test_acceptance_requires_body_bound_one_shot_native_presence_and_literal(
    tmp_path,
) -> None:
    service = _Service()
    manager = UserPresenceApprovalManager()

    def verify(request, body: bytes) -> None:  # type: ignore[no-untyped-def]
        if not manager.consume(
            token=request.headers.get(USER_PRESENCE_HEADER),
            method=request.method,
            path=request.url.path,
            body=body,
        ):
            raise HTTPException(
                403,
                detail="native user-presence confirmation required",
            )

    app = _app(tmp_path, service, presence=verify)
    path = (
        f"/v1/sessions/{_id(1)}/requirement-verification-evidence/acceptances"
    )
    command = RequirementAcceptanceAppendCommand(
        opportunity_set_fingerprint=_id(9),
        opportunity_id=_id(6),
        expected_predecessor_authority_id=None,
        outcome=RequirementAcceptanceOutcome.ACCEPTED,
        confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    )
    body = json.dumps(
        command.model_dump(mode="json"),
        separators=(",", ":"),
    ).encode("utf-8")
    presence_token = manager.issue(
        method="POST",
        path=path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    wrong_body = json.dumps(
        {
            **command.model_dump(mode="json"),
            "confirmation": "accept_requirement_without_exact_literal",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    wrong_presence_token = manager.issue(
        method="POST",
        path=path,
        body_sha256=hashlib.sha256(wrong_body).hexdigest(),
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        no_browser = client.post(
            path,
            headers={"Idempotency-Key": "synthetic-acceptance-no-browser-0001"},
            content=body,
        )
        token_only = client.post(
            path,
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "synthetic-acceptance-token-0001",
            },
            content=body,
        )
        bearer_only = client.post(
            path,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Idempotency-Key": "synthetic-acceptance-bearer-0001",
            },
            content=body,
        )
        browser = client.get("/auth/session").json()
        missing_origin = client.post(
            path,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "synthetic-acceptance-no-origin-0001",
                CSRF_HEADER: browser["csrf_token"],
                USER_PRESENCE_HEADER: presence_token,
            },
            content=body,
        )
        missing_csrf = client.post(
            path,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "synthetic-acceptance-no-csrf-0001",
                USER_PRESENCE_HEADER: presence_token,
                "Origin": "http://127.0.0.1",
            },
            content=body,
        )
        native_headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": "synthetic-acceptance-native-0001",
            CSRF_HEADER: browser["csrf_token"],
            USER_PRESENCE_HEADER: presence_token,
            "Origin": "http://127.0.0.1",
        }
        wrong_literal = client.post(
            path,
            headers={
                **native_headers,
                "Idempotency-Key": "synthetic-acceptance-wrong-literal-0001",
                USER_PRESENCE_HEADER: wrong_presence_token,
            },
            content=wrong_body,
        )
        accepted = client.post(path, headers=native_headers, content=body)
        reused_presence = client.post(path, headers=native_headers, content=body)

    for response in (
        no_browser,
        token_only,
        bearer_only,
        missing_origin,
        missing_csrf,
        wrong_literal,
        accepted,
        reused_presence,
    ):
        _private(response)
    assert no_browser.status_code == 401
    assert no_browser.json() == {"detail": "browser session required"}
    assert token_only.status_code == 403
    assert token_only.json() == {"detail": "owned native confirmation required"}
    assert bearer_only.status_code == 403
    assert bearer_only.json() == {"detail": "owned native confirmation required"}
    assert missing_origin.status_code == 403
    assert missing_origin.json() == {
        "detail": "same-origin confirmation required"
    }
    assert missing_csrf.status_code == 403
    assert missing_csrf.json() == {"detail": "CSRF validation failed"}
    assert wrong_literal.status_code == 422
    assert accepted.status_code == 201
    assert accepted.json()["applied"] is True
    acceptance = accepted.json()["snapshot"]["evidence"][
        "acceptance_authorities"
    ][0]
    assert acceptance["authority_kind"] == "native_user_acceptance"
    assert acceptance["owned_native_action"] is True
    assert reused_presence.status_code == 403
    assert len([call for call in service.calls if call[0] == "acceptance"]) == 1


def test_acceptance_fails_closed_when_native_presence_adapter_is_unavailable(
    tmp_path,
) -> None:
    service = _Service()
    app = _app(tmp_path, service, presence=None)
    path = (
        f"/v1/sessions/{_id(1)}/requirement-verification-evidence/acceptances"
    )
    command = RequirementAcceptanceAppendCommand(
        opportunity_set_fingerprint=_id(9),
        opportunity_id=_id(6),
        outcome=RequirementAcceptanceOutcome.ACCEPTED,
        confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session").json()
        unavailable = client.post(
            path,
            headers={
                "Idempotency-Key": "synthetic-acceptance-unavailable-0001",
                CSRF_HEADER: browser["csrf_token"],
                USER_PRESENCE_HEADER: "synthetic-presence-unavailable",
                "Origin": "http://127.0.0.1",
            },
            json=command.model_dump(mode="json"),
        )

    _private(unavailable)
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "detail": "user-presence confirmation is unavailable"
    }
    assert not service.calls


def test_cross_origin_acceptance_returns_its_published_sanitized_error(
    tmp_path,
) -> None:
    service = _Service()
    manager = UserPresenceApprovalManager()

    def verify(request, body: bytes) -> None:  # type: ignore[no-untyped-def]
        if not manager.consume(
            token=request.headers.get(USER_PRESENCE_HEADER),
            method=request.method,
            path=request.url.path,
            body=body,
        ):
            raise HTTPException(
                403,
                detail="native user-presence confirmation required",
            )

    app = _app(tmp_path, service, presence=verify)
    path = (
        f"/v1/sessions/{_id(1)}/requirement-verification-evidence/acceptances"
    )
    command = RequirementAcceptanceAppendCommand(
        opportunity_set_fingerprint=_id(9),
        opportunity_id=_id(6),
        outcome=RequirementAcceptanceOutcome.ACCEPTED,
        confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    )
    body = json.dumps(
        command.model_dump(mode="json"),
        separators=(",", ":"),
    ).encode("utf-8")
    presence_token = manager.issue(
        method="POST",
        path=path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session").json()
        denied = client.post(
            path,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "synthetic-cross-origin-acceptance-0001",
                CSRF_HEADER: browser["csrf_token"],
                USER_PRESENCE_HEADER: presence_token,
                "Origin": "https://cross-origin.example",
            },
            content=body,
        )

    _private(denied)
    assert denied.status_code == 403
    error = RequirementVerificationMessageErrorDto.model_validate(denied.json())
    assert error.model_dump(mode="json") == {"detail": "origin not allowed"}
    published = app.openapi()["components"]["schemas"][
        "RequirementVerificationMessageErrorDto"
    ]
    assert set(denied.json()) == set(published["required"])
    assert denied.json()["detail"] in published["properties"]["detail"]["enum"]
    assert not service.calls


def test_strict_commands_bounds_and_closed_failures_do_not_echo_content(
    tmp_path,
) -> None:
    service = _Service()
    app = _app(tmp_path, service)
    base = f"/v1/sessions/{_id(1)}/requirement-verification-evidence"
    headers = {
        API_TOKEN_HEADER: TOKEN,
        "Idempotency-Key": "synthetic-invalid-result-0001",
    }

    with TestClient(app, base_url="http://127.0.0.1") as client:
        partial_result = client.post(
            f"{base}/objective-results",
            headers=headers,
            json={
                "opportunity_id": _id(6),
                "outcome": "passed",
                "assistant_claim": "PRIVATE-CANARY-MUST-NOT-ECHO",
            },
        )
        extra_result = client.post(
            f"{base}/objective-results",
            headers=headers,
            json={
                **RequirementVerificationResultAppendCommand(
                    result=_result(),
                    expected_predecessor_authority_id=None,
                ).model_dump(mode="json"),
                "note": "PRIVATE-CANARY-MUST-NOT-ECHO",
            },
        )
        revision_overflow = client.get(
            f"{base}/opportunity-sets/{_id(9)}",
            params={"through_revision": MAX_REQUIREMENT_VERIFICATION_REVISIONS + 1},
            headers={API_TOKEN_HEADER: TOKEN},
        )
        service.errors["issue"] = RequirementVerificationDefinitionsOutOfDateError(
            "PRIVATE-DEFINITION-CANARY"
        )
        definitions = client.post(
            f"{base}/opportunity-sets/current",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        service.errors["issue"] = RequirementVerificationInputError(
            "PRIVATE-INPUT-CANARY"
        )
        invalid = client.post(
            f"{base}/opportunity-sets/current",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        service.errors["issue"] = RequirementVerificationPersistenceError(
            "PRIVATE-PERSISTENCE-CANARY"
        )
        unavailable = client.post(
            f"{base}/opportunity-sets/current",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        service.errors.pop("issue")
        service.errors["snapshot"] = RequirementVerificationNotFoundError(
            "PRIVATE-NOT-FOUND-CANARY"
        )
        absent = client.get(
            f"{base}/opportunity-sets/{_id(9)}",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        service.errors["result"] = RequirementVerificationStaleWindowError(
            "PRIVATE-STALE-CANARY"
        )
        stale = client.post(
            f"{base}/objective-results",
            headers=headers,
            json=RequirementVerificationResultAppendCommand(
                result=_result(),
                expected_predecessor_authority_id=None,
            ).model_dump(mode="json"),
        )
        service.errors["result"] = RequirementVerificationConflictError(
            "PRIVATE-CONFLICT-CANARY"
        )
        conflict = client.post(
            f"{base}/objective-results",
            headers=headers,
            json=RequirementVerificationResultAppendCommand(
                result=_result(),
                expected_predecessor_authority_id=None,
            ).model_dump(mode="json"),
        )

    expected = (
        (partial_result, 422, None),
        (extra_result, 422, None),
        (revision_overflow, 422, None),
        (
            definitions,
            409,
            "requirement_verification_evidence_definitions_out_of_date",
        ),
        (invalid, 422, "invalid_requirement_verification_evidence"),
        (
            unavailable,
            503,
            "requirement_verification_evidence_persistence_failed",
        ),
        (absent, 404, "requirement_verification_evidence_not_found"),
        (stale, 409, "requirement_verification_source_window_stale"),
        (conflict, 409, "requirement_verification_evidence_conflict"),
    )
    for response, status, code in expected:
        _private(response)
        assert response.status_code == status
        serialized = response.text.casefold()
        assert "private-" not in serialized
        if code is not None:
            assert response.json()["detail"]["code"] == code


def test_openapi_surface_is_bounded_content_free_and_native_separated(tmp_path) -> None:
    schema = _app(tmp_path, _Service()).openapi()
    base = "/v1/sessions/{session_id}/requirement-verification-evidence"
    assert tuple(path for path in schema["paths"] if base in path) == (
        f"{base}/opportunity-sets/current",
        f"{base}/opportunity-sets/{{opportunity_set_fingerprint}}",
        f"{base}/objective-results",
        f"{base}/acceptances",
    )
    result_request = schema["paths"][f"{base}/objective-results"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    acceptance = schema["paths"][f"{base}/acceptances"]["post"]
    acceptance_request = acceptance["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert result_request == {
        "$ref": "#/components/schemas/RequirementVerificationResultAppendCommand"
    }
    assert acceptance_request == {
        "$ref": "#/components/schemas/RequirementAcceptanceAppendCommand"
    }
    parameters = {item["name"]: item for item in acceptance["parameters"]}
    native_proofs = {
        BROWSER_SESSION_COOKIE,
        "Origin",
        CSRF_HEADER,
        USER_PRESENCE_HEADER,
    }
    assert set(parameters) == {"session_id", "Idempotency-Key", *native_proofs}
    assert all(parameters[name]["required"] is True for name in native_proofs)
    assert parameters[BROWSER_SESSION_COOKIE]["in"] == "cookie"
    assert parameters["Origin"]["in"] == "header"
    assert parameters[CSRF_HEADER]["in"] == "header"
    assert parameters[USER_PRESENCE_HEADER]["in"] == "header"
    assert "request-body sha-256" in parameters[USER_PRESENCE_HEADER][
        "description"
    ].casefold()
    assert API_TOKEN_HEADER not in parameters
    assert "Authorization" not in parameters
    assert acceptance["security"] == []
    assert set(acceptance["responses"]) == {
        "200",
        "201",
        "401",
        "403",
        "404",
        "409",
        "422",
        "503",
    }
    assert set(
        schema["paths"][f"{base}/opportunity-sets/current"]["post"]["responses"]
    ) == {"200", "201", "401", "403", "404", "409", "422", "503"}
    assert set(
        schema["paths"][f"{base}/objective-results"]["post"]["responses"]
    ) == {"200", "201", "401", "403", "404", "409", "422", "503"}
    assert set(
        schema["paths"][
            f"{base}/opportunity-sets/{{opportunity_set_fingerprint}}"
        ]["get"]["responses"]
    ) == {"200", "401", "404", "409", "422", "503"}
    mixed_422 = acceptance["responses"]["422"]["content"]["application/json"][
        "schema"
    ]["anyOf"]
    assert {item["$ref"] for item in mixed_422} == {
        "#/components/schemas/RequirementVerificationMessageErrorDto",
        "#/components/schemas/RequirementVerificationServiceErrorDto",
    }
    confirmation = schema["components"]["schemas"][
        "RequirementAcceptanceAppendCommand"
    ]["properties"]["confirmation"]
    assert confirmation.get("const") == REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION
    serialized = json.dumps(
        {
            name: value
            for name, value in schema["components"]["schemas"].items()
            if "RequirementVerification" in name or "RequirementAcceptance" in name
        },
        sort_keys=True,
    ).casefold()
    for prohibited in (
        "assistant_claim",
        "comment",
        "prompt",
        "transcript",
        "excerpt",
        "workspace",
        "file_path",
        "raw_content",
        "idempotency_key_digest",
        "command_fingerprint",
    ):
        assert prohibited not in serialized
