from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    DEFAULT_COACHING_METRIC_ENGINE,
)
from prompt_enhancer.application.analysis.text_analysis_presets import COACHING_PROFILE_V1
from prompt_enhancer.application.analysis.text_contracts import (
    P1LocalAnalysisGrant,
    TextAnalysisScopeKind,
    TextAnalysisScopeReason,
    TextAnalysisScopeState,
    TextAnalysisPrivacyError,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
)
from prompt_enhancer.application.analysis.text_source import (
    EphemeralTextAnalysisSource,
    TextSourceFailureReason,
    TextSourceReadError,
)
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.language import (
    DETERMINISTIC_LANGUAGE_DETECTOR_VERSION,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    CodexAppServerClient,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.content_contracts import (
    TEXT_CONTENT_ADAPTER_VERSION,
    TEXT_CONTENT_SCHEMA_VERSION,
    CodexTextContentLimits,
    RawCodexTextThread,
    parse_text_thread_read,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.content_source import (
    CODEX_LOCAL_INSTALLATION_ID,
    CodexContentAccessPurpose,
    CodexTextAccessGrant,
    CodexTextAnalysisSelection,
    CodexTextAnalysisSource,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexCompatibilityError,
    CodexLimitError,
    CodexNoAnalyzableTextError,
    CodexPreviewWindowLimitError,
    CodexProtocolViolation,
    CodexResponseLimitError,
    CodexRequestRejected,
    CodexSelectionLimitError,
    CodexScopeError,
    CodexThreadStructureLimitError,
    CodexTransportError,
    CodexTransportTimeout,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.transports.stdio_jsonl import (
    StdioJsonRpcTransport,
    ThreadReadPolicy,
)
from prompt_enhancer.privacy import Pseudonymizer


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.notifications: list[tuple[str, dict[str, object] | None]] = []
        self.closed = False

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        self.notifications.append((method, params))

    def close(self) -> None:
        self.closed = True


def _pseudonymizer() -> Pseudonymizer:
    return Pseudonymizer(bytes(range(32)))


def _safe_session_id(pseudonymizer: Pseudonymizer, raw_id: str) -> str:
    installation_id = pseudonymizer.pseudonymize(
        "codex:installation", CODEX_LOCAL_INSTALLATION_ID
    )
    return pseudonymizer.pseudonymize(
        f"codex:session:{installation_id}", raw_id
    )


def _selection(raw_id: str = "example-thread-alpha", **changes: int) -> CodexTextAnalysisSelection:
    return CodexTextAnalysisSelection(
        provider=Provider.CODEX,
        session_id=_safe_session_id(_pseudonymizer(), raw_id),
        **changes,
    )


def _grant(selection: CodexTextAnalysisSelection) -> CodexTextAccessGrant:
    return CodexTextAccessGrant(
        purpose=CodexContentAccessPurpose.TEXT_ANALYSIS,
        provider=selection.provider,
        session_id=selection.session_id,
        data_tier=DataTier.REDACTED_CONTENT,
        per_run_confirmation_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )


def _profile() -> TextTaskProfile:
    return TextTaskProfile(applicability=())


def _listed(raw_id: str = "example-thread-alpha") -> dict[str, object]:
    return {
        "data": [
            {
                "id": raw_id,
                "createdAt": 1_768_473_600,
                "status": {"type": "notLoaded"},
                "preview": "PRIVATE-LIST-PREVIEW-CANARY",
            }
        ],
        "nextCursor": None,
    }


def _content_read(raw_id: str = "example-thread-alpha") -> dict[str, object]:
    return {
        "thread": {
            "id": raw_id,
            "turns": [
                {
                    "id": "example-turn-one",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-user-item",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Build the local report for analyst@example.com "
                                        "with api_key=EXAMPLE_SECRET_VALUE_123456789."
                                    ),
                                },
                                {
                                    "type": "localImage",
                                    "path": "PRIVATE-IMAGE-PATH-CANARY",
                                },
                            ],
                        },
                        {
                            "type": "reasoning",
                            "id": "excluded-reasoning",
                            "summary": ["PRIVATE-REASONING-SUMMARY-CANARY"],
                            "content": ["PRIVATE-RAW-REASONING-CANARY"],
                        },
                        {
                            "type": "commandExecution",
                            "id": "excluded-command",
                            "command": "PRIVATE-COMMAND-CANARY",
                            "cwd": "PRIVATE-COMMAND-PATH-CANARY",
                            "aggregatedOutput": "PRIVATE-COMMAND-OUTPUT-CANARY",
                        },
                        {
                            "type": "fileChange",
                            "id": "excluded-diff",
                            "changes": [
                                {
                                    "path": "PRIVATE-DIFF-PATH-CANARY",
                                    "kind": "update",
                                    "diff": "PRIVATE-DIFF-CANARY",
                                }
                            ],
                        },
                        {
                            "type": "mcpToolCall",
                            "id": "excluded-tool",
                            "server": "example",
                            "tool": "example",
                            "arguments": {"canary": "PRIVATE-TOOL-ARGUMENT-CANARY"},
                            "result": {"canary": "PRIVATE-TOOL-RESULT-CANARY"},
                        },
                        {
                            "type": "futurePrivateItem",
                            "id": "excluded-future",
                            "text": "PRIVATE-FUTURE-ITEM-CANARY",
                        },
                        {
                            "type": "agentMessage",
                            "id": "example-agent-item",
                            "phase": "final_answer",
                            "text": "The local report is ready.",
                        },
                        {
                            "type": "plan",
                            "id": "example-plan-item",
                            "text": "Verify the report locally.",
                        },
                    ],
                }
            ],
        }
    }


def _factory(
    transport: RecordingTransport,
    calls: list[str],
    *,
    text_limits: CodexTextContentLimits | None = None,
) -> Callable[[], CodexAppServerClient]:
    def create() -> CodexAppServerClient:
        calls.append("constructed")
        return CodexAppServerClient(transport, text_limits=text_limits)

    return create


def test_text_source_is_explicit_read_only_allowlisted_and_repr_safe() -> None:
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(),
            _content_read(),
        ]
    )
    calls: list[str] = []
    selection = _selection()
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, calls),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert source.purpose is CodexContentAccessPurpose.TEXT_ANALYSIS
    assert isinstance(source, EphemeralTextAnalysisSource)
    assert source.read_only is True
    assert source.requires_explicit_selection is True
    assert calls == ["constructed"]
    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
        "thread/read",
    ]
    assert transport.requests[-1][1] == {
        "threadId": "example-thread-alpha",
        "includeTurns": True,
    }
    assert transport.notifications == [("initialized", {})]
    assert transport.closed is True

    assert context.provider is Provider.CODEX
    assert context.session_id == selection.session_id
    assert context.adapter_version == TEXT_CONTENT_ADAPTER_VERSION
    assert context.content_schema_version == (
        TEXT_CONTENT_SCHEMA_VERSION
        + "+"
        + DETERMINISTIC_LANGUAGE_DETECTOR_VERSION
    )
    assert context.observed_message_count == 3
    assert context.eligible_message_count == 3
    assert tuple(message.role for message in context.messages) == (
        TextRole.USER,
        TextRole.AGENT,
        TextRole.AGENT,
    )
    assert tuple(message.kind for message in context.messages) == (
        TextMessageKind.REQUEST,
        TextMessageKind.RESPONSE,
        TextMessageKind.PLAN,
    )
    assert context.available_message_kinds == frozenset(
        {
            TextMessageKind.REQUEST,
            TextMessageKind.RESPONSE,
            TextMessageKind.PLAN,
            TextMessageKind.FEEDBACK,
        }
    )
    assert context.text_extraction_complete is False
    assert all(message.language is TextLanguage.ENGLISH for message in context.messages)
    assert TextMessageKind.ACTION not in {message.kind for message in context.messages}
    assert TextMessageKind.DECISION not in {message.kind for message in context.messages}
    values = tuple(message.text.get_secret_value() for message in context.messages)
    assert "[EMAIL]" in values[0]
    assert "api_" + "key=[SECRET]" in values[0]
    assert values[1:] == (
        "The local report is ready.",
        "Verify the report locally.",
    )
    rendered = repr(context) + context.model_dump_json()
    for canary in (
        "PRIVATE-LIST-PREVIEW-CANARY",
        "PRIVATE-IMAGE-PATH-CANARY",
        "PRIVATE-REASONING-SUMMARY-CANARY",
        "PRIVATE-RAW-REASONING-CANARY",
        "PRIVATE-COMMAND-CANARY",
        "PRIVATE-COMMAND-OUTPUT-CANARY",
        "PRIVATE-DIFF-CANARY",
        "PRIVATE-TOOL-ARGUMENT-CANARY",
        "PRIVATE-TOOL-RESULT-CANARY",
        "PRIVATE-FUTURE-ITEM-CANARY",
        "EXAMPLE_SECRET_VALUE",
    ):
        assert canary not in rendered
        assert all(canary not in value for value in values)

    # The post-ingress capability is bound to this exact redacted window.
    analysis_grant = P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )
    assert analysis_grant.analysis_window_fingerprint == context.analysis_window_fingerprint
    results = DEFAULT_TEXT_METRIC_ENGINE.compute(context, analysis_grant)
    assert len(results) == 10
    assert all(
        result.provenance.adapter_version == TEXT_CONTENT_ADAPTER_VERSION
        and result.provenance.content_schema_version == context.content_schema_version
        for result in results
    )


def test_text_source_classifies_only_closed_user_follow_up_as_feedback() -> None:
    content = _content_read()
    content["thread"]["turns"][0]["items"] = [  # type: ignore[index]
        item
        for item in content["thread"]["turns"][0]["items"]  # type: ignore[index]
        if item["type"] != "futurePrivateItem"
    ]
    content["thread"]["turns"].append(  # type: ignore[index]
        {
            "id": "example-turn-follow-up",
            "items": [
                {
                    "type": "userMessage",
                    "id": "example-follow-up",
                    "content": [
                        {
                            "type": "text",
                            "text": "Please redo the fictional report; it is wrong.",
                        }
                    ],
                }
            ],
        }
    )
    content["thread"]["turns"].append(  # type: ignore[index]
        {
            "id": "example-turn-current-request",
            "items": [
                {
                    "type": "userMessage",
                    "id": "example-current-request",
                    "content": [
                        {
                            "type": "text",
                            "text": "Add a fictional appendix with one table.",
                        }
                    ],
                }
            ],
        }
    )
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(),
            content,
        ]
    )
    selection = _selection()
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, []),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=COACHING_PROFILE_V1.task_profile,
    )

    assert context.messages[-2].role is TextRole.USER
    assert context.messages[-2].kind is TextMessageKind.FEEDBACK
    assert context.messages[-1].role is TextRole.USER
    assert context.messages[-1].kind is TextMessageKind.REQUEST
    assert context.focus_message_id == context.messages[-1].message_id
    assert TextMessageKind.FEEDBACK in context.available_message_kinds
    grant = P1LocalAnalysisGrant(
        provider=context.provider,
        session_id=context.session_id,
        analysis_window_fingerprint=context.analysis_window_fingerprint,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )
    results = DEFAULT_COACHING_METRIC_ENGINE.compute(
        context,
        grant,
        pack_key=COACHING_METRIC_PACK_KEY,
        pack_version=COACHING_METRIC_PACK_VERSION,
    )
    rework = next(
        result
        for result in results
        if result.observation.key == "collaboration.rework_candidate_rate"
    )
    assert rework.value_state.value == "known"
    assert rework.fraction is not None
    assert rework.fraction.denominator >= 1
    assert rework.fraction.numerator == rework.fraction.denominator


def test_text_source_analyzes_the_newest_safe_suffix_of_a_large_thread() -> None:
    raw_thread_id = "example-thread-alpha"
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(raw_thread_id),
            {
                "thread": {
                    "id": raw_thread_id,
                    "turns": [
                        {
                            "id": "old-turn",
                            "items": [
                                {
                                    "type": "userMessage",
                                    "id": "old-user",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "PRIVATE-OMITTED-HISTORY-CANARY",
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "new-turn",
                            "items": [
                                {
                                    "type": "userMessage",
                                    "id": "new-user",
                                    "content": [
                                        {"type": "text", "text": "Keep newest request."}
                                    ],
                                },
                                {
                                    "type": "agentMessage",
                                    "id": "new-agent",
                                    "phase": "final_answer",
                                    "text": "Keep newest reply.",
                                },
                            ],
                        },
                    ],
                }
            },
        ]
    )
    text_limits = CodexTextContentLimits(
        max_turns_per_session=1,
        max_items_per_turn=2,
        max_total_items=2,
        max_user_content_parts_per_item=1,
        max_text_fragments_per_session=2,
        max_characters_per_fragment=64,
        max_total_text_characters=128,
    )
    selection = _selection(raw_thread_id)
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, [], text_limits=text_limits),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.text_extraction_complete is False
    assert context.eligible_message_count == 2
    assert tuple(
        message.text.get_secret_value() for message in context.messages
    ) == ("Keep newest request.", "Keep newest reply.")
    assert "PRIVATE-OMITTED-HISTORY-CANARY" not in (
        repr(context) + context.model_dump_json()
    )


def test_access_grant_mismatch_prevents_client_construction() -> None:
    calls: list[str] = []
    selection = _selection()
    other = _selection("example-thread-other")
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=lambda: calls.append("constructed"),  # type: ignore[arg-type,return-value]
    )

    with pytest.raises(TextAnalysisPrivacyError, match="selected session"):
        source.read(
            selection=selection,
            grant=_grant(other),
            task_profile=_profile(),
        )

    assert calls == []


@pytest.mark.parametrize(
    "grant_change",
    (
        {"per_run_confirmation_active": False},
        {"local_only": False},
        {"content_persistence_allowed": True},
        {"data_tier": DataTier.METADATA},
    ),
)
def test_access_grant_rejects_nonlocal_or_standing_only_authority(
    grant_change: dict[str, object],
) -> None:
    selection = _selection()
    values: dict[str, object] = {
        "purpose": CodexContentAccessPurpose.TEXT_ANALYSIS,
        "provider": Provider.CODEX,
        "session_id": selection.session_id,
        "data_tier": DataTier.REDACTED_CONTENT,
        "per_run_confirmation_active": True,
        "local_only": True,
        "content_persistence_allowed": False,
    }
    values.update(grant_change)

    with pytest.raises(ValidationError):
        CodexTextAccessGrant.model_validate(values)


@pytest.mark.parametrize(
    "grant_change",
    (
        {"per_run_confirmation_active": False},
        {"local_only": False},
        {"content_persistence_allowed": True},
        {"data_tier": DataTier.METADATA},
    ),
)
def test_source_revalidates_grant_boundary_at_point_of_use(
    grant_change: dict[str, object],
) -> None:
    calls: list[str] = []
    selection = _selection()
    # ``model_copy(update=...)`` deliberately represents a grant supplied by a
    # non-validating boundary. The adapter must not rely only on construction-
    # time validation before it touches the provider process.
    grant = _grant(selection).model_copy(update=grant_change)
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=lambda: calls.append("constructed"),  # type: ignore[arg-type,return-value]
    )

    with pytest.raises(TextAnalysisPrivacyError, match="selected session"):
        source.read(
            selection=selection,
            grant=grant,
            task_profile=_profile(),
        )

    assert calls == []


def test_codex_source_rejects_another_provider_before_client_construction() -> None:
    calls: list[str] = []
    safe_id = _safe_session_id(_pseudonymizer(), "example-thread-alpha")
    selection = CodexTextAnalysisSelection(
        provider=Provider.CLAUDE_CODE,
        session_id=safe_id,
    )
    grant = CodexTextAccessGrant(
        purpose=selection.purpose,
        provider=selection.provider,
        session_id=selection.session_id,
        data_tier=DataTier.REDACTED_CONTENT,
        per_run_confirmation_active=True,
        local_only=True,
        content_persistence_allowed=False,
    )
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=lambda: calls.append("constructed"),  # type: ignore[arg-type,return-value]
    )

    with pytest.raises(TextAnalysisPrivacyError, match="selected session"):
        source.read(
            selection=selection,
            grant=grant,
            task_profile=_profile(),
        )

    assert calls == []


def test_selected_pseudonym_must_match_current_list_snapshot() -> None:
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            _listed("example-thread-different"),
        ]
    )
    selection = _selection()
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, []),
    )

    with pytest.raises(TextSourceReadError) as raised:
        source.read(
            selection=selection,
            grant=_grant(selection),
            task_profile=_profile(),
        )

    assert raised.value.reason is TextSourceFailureReason.SELECTION_SNAPSHOT_MISS
    assert str(raised.value) == "selection_snapshot_miss"
    assert raised.value.__cause__ is None
    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
    ]


def test_valid_thread_without_user_text_is_not_misreported_as_schema_drift() -> None:
    selection = _selection()
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            _listed(),
            {
                "thread": {
                    "id": "example-thread-alpha",
                    "turns": [
                        {
                            "id": "example-turn",
                            "items": [
                                {
                                    "type": "agentMessage",
                                    "id": "example-agent",
                                    "phase": "final_answer",
                                    "text": "Synthetic response only.",
                                }
                            ],
                        }
                    ],
                }
            },
        ]
    )
    source = CodexTextAnalysisSource(
        _pseudonymizer(), client_factory=_factory(transport, [])
    )

    with pytest.raises(TextSourceReadError) as raised:
        source.read(
            selection=selection,
            grant=_grant(selection),
            task_profile=_profile(),
        )

    assert raised.value.reason is TextSourceFailureReason.NO_ANALYZABLE_TEXT
    assert str(raised.value) == "no_analyzable_text"


def test_oversized_catalog_response_is_reported_as_selection_limit() -> None:
    selection = _selection()
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            CodexResponseLimitError("PRIVATE-CATALOG-LIMIT-CANARY"),
        ]
    )
    source = CodexTextAnalysisSource(
        _pseudonymizer(), client_factory=_factory(transport, [])
    )

    with pytest.raises(TextSourceReadError) as raised:
        source.read(
            selection=selection,
            grant=_grant(selection),
            task_profile=_profile(),
        )

    assert raised.value.reason is TextSourceFailureReason.SELECTION_LIMIT
    assert str(raised.value) == "source_selection_limit"
    assert "PRIVATE" not in repr(raised.value)
    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
    ]


@pytest.mark.parametrize(
    ("provider_error", "reason"),
    (
        (
            CodexCompatibilityError("PRIVATE-SCHEMA-CANARY"),
            TextSourceFailureReason.SCHEMA_UNSUPPORTED,
        ),
        (
            CodexNoAnalyzableTextError("PRIVATE-EMPTY-CANARY"),
            TextSourceFailureReason.NO_ANALYZABLE_TEXT,
        ),
        (
            CodexRequestRejected("PRIVATE-REJECTED-CANARY"),
            TextSourceFailureReason.PROTOCOL_REJECTED,
        ),
        (
            CodexProtocolViolation("PRIVATE-PROTOCOL-CANARY"),
            TextSourceFailureReason.PROTOCOL_REJECTED,
        ),
        (
            CodexLimitError("PRIVATE-LIMIT-CANARY"),
            TextSourceFailureReason.RESOURCE_LIMIT,
        ),
        (
            CodexSelectionLimitError("PRIVATE-SELECTION-LIMIT-CANARY"),
            TextSourceFailureReason.SELECTION_LIMIT,
        ),
        (
            CodexResponseLimitError("PRIVATE-RESPONSE-LIMIT-CANARY"),
            TextSourceFailureReason.PROVIDER_RESPONSE_LIMIT,
        ),
        (
            CodexThreadStructureLimitError("PRIVATE-STRUCTURE-LIMIT-CANARY"),
            TextSourceFailureReason.THREAD_STRUCTURE_LIMIT,
        ),
        (
            CodexPreviewWindowLimitError("PRIVATE-WINDOW-LIMIT-CANARY"),
            TextSourceFailureReason.PREVIEW_WINDOW_LIMIT,
        ),
        (
            CodexTransportTimeout("PRIVATE-TIMEOUT-CANARY"),
            TextSourceFailureReason.TIMEOUT,
        ),
        (
            CodexTransportError("PRIVATE-PROVIDER-CANARY"),
            TextSourceFailureReason.PROVIDER_UNAVAILABLE,
        ),
    ),
)
def test_source_translates_provider_failures_to_bounded_content_free_reasons(
    provider_error: Exception,
    reason: TextSourceFailureReason,
) -> None:
    selection = _selection()

    def fail_before_read() -> CodexAppServerClient:
        raise provider_error

    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=fail_before_read,
    )

    with pytest.raises(TextSourceReadError) as raised:
        source.read(
            selection=selection,
            grant=_grant(selection),
            task_profile=_profile(),
        )

    assert raised.value.reason is reason
    assert str(raised.value) == reason.value
    assert "PRIVATE" not in repr(raised.value)
    assert raised.value.__cause__ is None


def test_bounded_window_prioritizes_latest_user_request_and_following_reply() -> None:
    read = _content_read()
    items = read["thread"]["turns"][0]["items"]  # type: ignore[index]
    items.insert(0, {
        "type": "userMessage",
        "id": "older-user",
        "content": [{"type": "text", "text": "Older request."}],
    })
    selection = _selection(max_messages=2, max_characters=100)
    transport = RecordingTransport(
        [{"version": "example-1"}, _listed(), read]
    )
    source = CodexTextAnalysisSource(
        _pseudonymizer(), client_factory=_factory(transport, [])
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.eligible_message_count == 4
    assert context.observed_message_count == 2
    assert tuple(message.text.get_secret_value() for message in context.messages) == (
        "Build the local report for [EMAIL] with api_" + "key=[SECRET]",
        "The local report is ready.",
    )
    assert context.focus_message_id == context.messages[0].message_id


def test_extraction_completeness_participates_in_window_fingerprint() -> None:
    incomplete_read = _content_read()
    complete_read = deepcopy(incomplete_read)
    items = complete_read["thread"]["turns"][0]["items"]  # type: ignore[index]
    complete_read["thread"]["turns"][0]["items"] = [  # type: ignore[index]
        item for item in items if item.get("type") != "futurePrivateItem"
    ]
    selection = _selection()

    incomplete = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(
            RecordingTransport(
                [{"version": "example-1"}, _listed(), incomplete_read]
            ),
            [],
        ),
    ).read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )
    complete = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(
            RecordingTransport(
                [{"version": "example-1"}, _listed(), complete_read]
            ),
            [],
        ),
    ).read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert incomplete.text_extraction_complete is False
    assert complete.text_extraction_complete is True
    assert tuple(message.text for message in incomplete.messages) == tuple(
        message.text for message in complete.messages
    )
    assert incomplete.analysis_window_fingerprint != complete.analysis_window_fingerprint


def test_parser_masks_dto_and_rejects_malformed_allowlisted_shapes_safely() -> None:
    parsed = parse_text_thread_read(_content_read())
    private_canary = "PRIVATE-SHAPE-CANARY"

    assert private_canary not in repr(parsed)
    assert "Build the local report" not in parsed.model_dump_json()

    malformed = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "example-turn",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-item",
                            "content": {"type": "text", "text": private_canary},
                        }
                    ],
                }
            ],
        }
    }
    with pytest.raises(CodexCompatibilityError) as error:
        parse_text_thread_read(malformed)
    assert private_canary not in str(error.value)


def test_parser_discards_skill_and_mention_metadata_without_reading_text_fields() -> None:
    private_canaries = (
        "PRIVATE-SKILL-NAME-CANARY",
        "PRIVATE-SKILL-PATH-CANARY",
        "PRIVATE-SKILL-TEXT-CANARY",
        "PRIVATE-MENTION-NAME-CANARY",
        "PRIVATE-MENTION-PATH-CANARY",
        "PRIVATE-MENTION-TEXT-CANARY",
    )
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "example-turn",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-item",
                            "content": [
                                {"type": "text", "text": "Keep this request."},
                                {
                                    "type": "skill",
                                    "name": private_canaries[0],
                                    "path": private_canaries[1],
                                    "text": private_canaries[2],
                                },
                                {
                                    "type": "mention",
                                    "name": private_canaries[3],
                                    "path": private_canaries[4],
                                    "text": private_canaries[5],
                                },
                                {"type": "text", "text": "Keep this constraint."},
                            ],
                        }
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(result)

    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("Keep this request.", "Keep this constraint.")
    rendered = repr(parsed) + parsed.model_dump_json()
    assert all(canary not in rendered for canary in private_canaries)
    assert parsed.extraction_complete is True


def test_current_non_text_item_variants_are_explicitly_discarded_as_complete() -> None:
    discarded_types = (
        "reasoning",
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabToolCall",
        "collabAgentToolCall",
        "hookPrompt",
        "subAgentActivity",
        "webSearch",
        "imageView",
        "sleep",
        "imageGeneration",
        "enteredReviewMode",
        "exitedReviewMode",
        "contextCompaction",
    )
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "example-turn",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-user",
                            "content": [{"type": "text", "text": "Keep this."}],
                        },
                        *({"type": item_type} for item_type in discarded_types),
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(result)

    assert parsed.extraction_complete is True
    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("Keep this.",)


@pytest.mark.parametrize(
    "item",
    (
        {
            "type": "agentMessage",
            "id": "example-item",
            "phase": "future_phase",
            "text": "PRIVATE-CANARY",
        },
        {
            "type": "plan",
            "id": "example-item",
        },
    ),
)
def test_parser_fails_closed_for_unsupported_allowlisted_variants(
    item: dict[str, object],
) -> None:
    private_canary = "PRIVATE-CANARY"
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [{"id": "example-turn", "items": [item]}],
        }
    }

    with pytest.raises(CodexCompatibilityError) as error:
        parse_text_thread_read(result)
    assert private_canary not in str(error.value)


@pytest.mark.parametrize("invalid_type", (None, "", 7, False))
def test_parser_fails_closed_for_malformed_user_input_type(
    invalid_type: object,
) -> None:
    private_canary = "PRIVATE-MALFORMED-INPUT-CANARY"
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "example-turn",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-item",
                            "content": [
                                {"type": invalid_type, "text": private_canary}
                            ],
                        }
                    ],
                }
            ],
        }
    }

    with pytest.raises(CodexCompatibilityError) as raised:
        parse_text_thread_read(result)
    assert private_canary not in str(raised.value)


def test_parser_discards_unknown_future_tagged_user_input() -> None:
    private_canary = "PRIVATE-FUTURE-INPUT-CANARY"
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "example-turn",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-item",
                            "content": [
                                {"type": "text", "text": "Keep this request."},
                                {
                                    "type": "futureInput",
                                    "text": private_canary,
                                    "path": private_canary,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(result)

    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("Keep this request.",)
    assert parsed.extraction_complete is False
    assert parsed.older_history_truncated is False
    assert parsed.unclassified_omission is True
    assert private_canary not in repr(parsed) + parsed.model_dump_json()


def test_unknown_future_thread_item_marks_extraction_incomplete_without_payload_read() -> None:
    private_canary = "PRIVATE-FUTURE-ITEM-CANARY"
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "example-turn",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "example-user",
                            "content": [{"type": "text", "text": "Keep this."}],
                        },
                        {
                            "type": "futureItem",
                            "text": private_canary,
                            "content": private_canary,
                        },
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(result)

    assert parsed.extraction_complete is False
    assert parsed.older_history_truncated is False
    assert parsed.unclassified_omission is True
    assert private_canary not in repr(parsed) + parsed.model_dump_json()


def test_parser_projects_the_newest_bounded_turn_and_item_suffix() -> None:
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "turn-old",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "user-old",
                            "content": [
                                {"type": "text", "text": "PRIVATE-OLD-CANARY"}
                            ],
                        }
                    ],
                },
                {
                    "id": "turn-middle",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "user-middle",
                            "content": [
                                {"type": "text", "text": "Keep middle."}
                            ],
                        }
                    ],
                },
                {
                    "id": "turn-new",
                    "items": [
                        {
                            "type": "plan",
                            "id": "plan-omitted",
                            "text": "PRIVATE-SAME-TURN-CANARY",
                        },
                        {
                            "type": "userMessage",
                            "id": "user-new",
                            "content": [
                                {"type": "text", "text": "Keep newest."}
                            ],
                        },
                        {
                            "type": "agentMessage",
                            "id": "agent-new",
                            "phase": "final_answer",
                            "text": "Keep reply.",
                        },
                    ],
                },
            ],
        }
    }

    parsed = parse_text_thread_read(
        result,
        CodexTextContentLimits(
            max_turns_per_session=2,
            max_items_per_turn=2,
            max_total_items=3,
            max_user_content_parts_per_item=1,
            max_text_fragments_per_session=3,
            max_characters_per_fragment=32,
            max_total_text_characters=64,
        ),
    )

    assert parsed.extraction_complete is False
    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("Keep middle.", "Keep newest.", "Keep reply.")
    rendered = repr(parsed) + parsed.model_dump_json()
    assert "PRIVATE-OLD-CANARY" not in rendered
    assert "PRIVATE-SAME-TURN-CANARY" not in rendered


def test_parser_applies_text_budgets_at_whole_item_boundaries() -> None:
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "turn-one",
                    "items": [
                        {"type": "plan", "id": "old", "text": "Old text"},
                        {
                            "type": "userMessage",
                            "id": "new-user",
                            "content": [{"type": "text", "text": "New user"}],
                        },
                        {
                            "type": "agentMessage",
                            "id": "new-agent",
                            "phase": "final_answer",
                            "text": "New reply",
                        },
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(
        result,
        CodexTextContentLimits(
            max_turns_per_session=1,
            max_items_per_turn=3,
            max_total_items=3,
            max_user_content_parts_per_item=1,
            max_text_fragments_per_session=2,
            max_characters_per_fragment=16,
            max_total_text_characters=17,
        ),
    )

    assert parsed.extraction_complete is False
    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("New user", "New reply")


def test_default_parser_projects_a_session_beyond_the_old_turn_ceiling() -> None:
    turns = [
        {
            "id": f"turn-{index}",
            "items": [
                {
                    "type": "userMessage",
                    "id": f"user-{index}",
                    "content": [
                        {"type": "text", "text": f"Fictional request {index}."}
                    ],
                }
            ],
        }
        for index in range(501)
    ]

    parsed = parse_text_thread_read(
        {"thread": {"id": "example-thread", "turns": turns}}
    )

    assert parsed.extraction_complete is False
    assert parsed.older_history_truncated is True
    assert parsed.unclassified_omission is False
    assert len(parsed.fragments) == 500
    assert parsed.fragments[0].text.get_secret_value() == "Fictional request 1."
    assert parsed.fragments[-1].text.get_secret_value() == "Fictional request 500."
    inconsistent = parsed.model_dump(mode="python")
    inconsistent["extraction_complete"] = True
    with pytest.raises(ValidationError, match="completeness is inconsistent"):
        RawCodexTextThread.model_validate(inconsistent)


def test_bounded_analysis_window_is_complete_inside_a_truncated_history_suffix() -> None:
    raw_id = "example-thread-large"
    turns = [
        {
            "id": f"turn-{index}",
            "items": [
                {
                    "type": "userMessage",
                    "id": f"user-{index}",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Implement fictional local report {index} and verify it."
                            ),
                        }
                    ],
                }
            ],
        }
        for index in range(501)
    ]
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(raw_id),
            {"thread": {"id": raw_id, "turns": turns}},
        ]
    )
    selection = _selection(raw_id, max_messages=100, max_characters=100_000)
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, []),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.observed_message_count == selection.max_messages == 100
    assert context.eligible_message_count == 500
    assert context.text_extraction_complete is True
    assert context.analysis_scope is not None
    assert context.analysis_scope.kind is TextAnalysisScopeKind.BOUNDED_RECENT
    assert context.analysis_scope.state is TextAnalysisScopeState.COMPLETE
    assert context.messages[0].text.get_secret_value().startswith(
        "Implement fictional local report 401"
    )
    assert context.messages[-1].text.get_secret_value().startswith(
        "Implement fictional local report 500"
    )


def test_full_available_session_scope_reports_incomplete_when_history_is_bounded() -> None:
    raw_id = "example-thread-full-bounded"
    turns = [
        {
            "id": f"turn-{index}",
            "items": [
                {
                    "type": "userMessage",
                    "id": f"user-{index}",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Implement reserved example report {index}.",
                        }
                    ],
                }
            ],
        }
        for index in range(501)
    ]
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(raw_id),
            {"thread": {"id": raw_id, "turns": turns}},
        ]
    )
    selection = CodexTextAnalysisSelection.full_available_session(
        provider=Provider.CODEX,
        session_id=_safe_session_id(_pseudonymizer(), raw_id),
        max_messages=100,
        max_characters=100_000,
    )
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, []),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.text_extraction_complete is False
    assert context.requested_scope_complete is False
    assert context.analysis_scope is not None
    assert context.analysis_scope.kind is TextAnalysisScopeKind.FULL_AVAILABLE_SESSION
    assert context.analysis_scope.state is TextAnalysisScopeState.INCOMPLETE_SOURCE
    assert set(context.analysis_scope.reason_codes) == {
        TextAnalysisScopeReason.SOURCE_HISTORY_LIMIT,
        TextAnalysisScopeReason.MESSAGE_LIMIT,
    }


def test_full_available_session_scope_is_complete_when_every_message_is_proven() -> None:
    raw_id = "example-thread-full-complete"
    read = _content_read(raw_id)
    read["thread"]["turns"][0]["items"] = [  # type: ignore[index]
        item
        for item in read["thread"]["turns"][0]["items"]  # type: ignore[index]
        if item.get("type") != "futurePrivateItem"
    ]
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(raw_id),
            read,
        ]
    )
    selection = CodexTextAnalysisSelection.full_available_session(
        provider=Provider.CODEX,
        session_id=_safe_session_id(_pseudonymizer(), raw_id),
        max_messages=100,
        max_characters=100_000,
    )

    context = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, []),
    ).read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.text_extraction_complete is True
    assert context.requested_scope_complete is True
    assert context.analysis_scope is not None
    assert context.analysis_scope.state is TextAnalysisScopeState.COMPLETE
    assert context.analysis_scope.source_history_complete is True
    assert context.analysis_scope.reason_codes == ()


def test_truncated_history_stays_incomplete_when_the_window_reaches_its_left_edge() -> None:
    raw_id = "example-thread-short-suffix"
    turns = [
        {
            "id": f"turn-{index}",
            "items": [
                {
                    "type": "userMessage",
                    "id": f"user-{index}",
                    "content": [{"type": "text", "text": f"Fictional request {index}."}],
                }
            ],
        }
        for index in range(3)
    ]
    limits = CodexTextContentLimits(max_turns_per_session=2)
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(raw_id),
            {"thread": {"id": raw_id, "turns": turns}},
        ]
    )
    selection = _selection(raw_id, max_messages=100, max_characters=100_000)
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, [], text_limits=limits),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.observed_message_count == context.eligible_message_count == 2
    assert context.text_extraction_complete is False


def test_unclassified_omission_keeps_a_saturated_window_incomplete() -> None:
    raw_id = "example-thread-unclassified"
    turns = [
        {
            "id": "turn-unknown",
            "items": [
                {
                    "type": "futurePrivateItem",
                    "text": "PRIVATE-FUTURE-PAYLOAD-CANARY",
                }
            ],
        },
        *(
            {
                "id": f"turn-{index}",
                "items": [
                    {
                        "type": "userMessage",
                        "id": f"user-{index}",
                        "content": [
                            {"type": "text", "text": f"Fictional request {index}."}
                        ],
                    }
                ],
            }
            for index in range(100)
        ),
    ]
    transport = RecordingTransport(
        [
            {"serverInfo": {"version": "example-1.0"}},
            _listed(raw_id),
            {"thread": {"id": raw_id, "turns": turns}},
        ]
    )
    selection = _selection(raw_id, max_messages=100, max_characters=100_000)
    source = CodexTextAnalysisSource(
        _pseudonymizer(),
        client_factory=_factory(transport, []),
    )

    context = source.read(
        selection=selection,
        grant=_grant(selection),
        task_profile=_profile(),
    )

    assert context.observed_message_count == selection.max_messages == 100
    assert context.text_extraction_complete is False
    assert "PRIVATE-FUTURE-PAYLOAD-CANARY" not in (
        repr(context) + context.model_dump_json()
    )


def test_parser_does_not_inspect_older_turns_outside_the_bounded_suffix() -> None:
    parsed = parse_text_thread_read(
        {
            "thread": {
                "id": "example-thread",
                "turns": [
                    object(),
                    {
                        "id": "selected-turn",
                        "items": [
                            {
                                "type": "userMessage",
                                "id": "selected-user",
                                "content": [
                                    {"type": "text", "text": "Keep selected request."}
                                ],
                            }
                        ],
                    },
                ],
            }
        },
        CodexTextContentLimits(max_turns_per_session=1),
    )

    assert parsed.extraction_complete is False
    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("Keep selected request.",)


def test_parser_splits_and_bounds_one_oversized_selected_fragment() -> None:
    private_canary = "PRIVATE-CHARACTER-BOUND-CANARY"
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "turn-one",
                    "items": [
                        {
                            "type": "plan",
                            "id": "plan-one",
                            "text": private_canary,
                        }
                    ],
                }
            ],
        }
    }
    limits = CodexTextContentLimits(
        max_turns_per_session=1,
        max_items_per_turn=1,
        max_total_items=1,
        max_user_content_parts_per_item=1,
        max_text_fragments_per_session=1,
        max_characters_per_fragment=8,
        max_total_text_characters=8,
    )

    parsed = parse_text_thread_read(result, limits)

    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == (private_canary[-8:],)
    assert parsed.older_history_truncated is True
    assert parsed.extraction_complete is False


def test_parser_keeps_a_bounded_newest_suffix_of_user_content_parts() -> None:
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "turn-one",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "user-one",
                            "content": [
                                {"type": "text", "text": "Part one."},
                                {"type": "text", "text": "Part two."},
                            ],
                        }
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(
        result,
        CodexTextContentLimits(max_user_content_parts_per_item=1),
    )

    assert tuple(
        fragment.text.get_secret_value() for fragment in parsed.fragments
    ) == ("Part two.",)
    assert parsed.older_history_truncated is True
    assert parsed.extraction_complete is False


def test_parser_splits_a_large_message_into_ordered_contract_fragments() -> None:
    result = {
        "thread": {
            "id": "example-thread",
            "turns": [
                {
                    "id": "turn-one",
                    "items": [
                        {
                            "type": "agentMessage",
                            "id": "agent-one",
                            "text": "abcdefghij",
                        }
                    ],
                }
            ],
        }
    }

    parsed = parse_text_thread_read(
        result,
        CodexTextContentLimits(
            max_characters_per_fragment=4,
            max_total_text_characters=12,
        ),
    )

    assert tuple(
        (fragment.segment_index, fragment.text.get_secret_value())
        for fragment in parsed.fragments
    ) == ((0, "abcd"), (1, "efgh"), (2, "ij"))
    assert parsed.extraction_complete is True


def test_text_transport_policy_allows_only_include_turns_read() -> None:
    transport = StdioJsonRpcTransport(
        thread_read_policy=ThreadReadPolicy.TEXT_ANALYSIS
    )

    transport._validate_request(
        "thread/read",
        {"threadId": "example-thread", "includeTurns": True},
    )
    with pytest.raises(CodexProtocolViolation, match="text analysis"):
        transport._validate_request(
            "thread/read",
            {"threadId": "example-thread", "includeTurns": False},
        )
    with pytest.raises(CodexProtocolViolation, match="not allowed"):
        transport._validate_request("thread/delete", {"threadId": "example-thread"})
