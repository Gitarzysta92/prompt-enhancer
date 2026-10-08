from __future__ import annotations

import pytest

from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    RawThread,
    parse_thread_read,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexCompatibilityError,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.limits import CodexReadLimits
from prompt_enhancer.infrastructure.providers.codex_app_server.mapping import CodexThreadMapper


def test_raw_dtos_drop_text_commands_output_and_repository_details() -> None:
    content_canary = "SYNTHETIC-PRIVATE-CONTENT-CANARY"
    parsed = parse_thread_read(
        {
            "thread": {
                "id": "example-session-private",
                "cwd": "/example/project",
                "createdAt": 1_768_473_600,
                "preview": content_canary,
                "gitInfo": {"remote": content_canary},
                "turns": [
                    {
                        "id": "example-turn-private",
                        "items": [
                            {
                                "id": "example-item-private",
                                "type": "commandExecution",
                                "command": content_canary,
                                "arguments": content_canary,
                                "output": content_canary,
                                "content": content_canary,
                                "reasoning": content_canary,
                            }
                        ],
                    }
                ],
            }
        },
        CodexReadLimits(),
    )

    rendered = repr(parsed)
    dumped = parsed.model_dump_json()
    assert content_canary not in rendered
    assert content_canary not in dumped
    item = parsed.thread.turns[0].items[0]
    assert not {
        "command",
        "arguments",
        "output",
        "content",
        "reasoning",
    }.intersection(type(item).model_fields)
    assert "preview" not in type(parsed.thread).model_fields
    assert "gitInfo" not in type(parsed.thread).model_fields


def test_wire_validation_errors_are_sanitized() -> None:
    value_canary = "SYNTHETIC-INVALID-TIMESTAMP-CANARY"

    with pytest.raises(CodexCompatibilityError) as error:
        parse_thread_read(
            {
                "thread": {
                    "id": "example-session-invalid",
                    "cwd": "/example/project",
                    "createdAt": value_canary,
                    "preview": "SYNTHETIC-PREVIEW-CANARY",
                }
            },
            CodexReadLimits(),
        )

    rendered = str(error.value)
    assert value_canary not in rendered
    assert "SYNTHETIC-PREVIEW-CANARY" not in rendered
    assert "example-session-invalid" not in rendered


def test_project_identity_is_lexical_and_equivalent_spellings_group_together() -> None:
    mapper = CodexThreadMapper(provider_version="example-1")
    first = RawThread.model_validate(
        {
            "id": "example-session-a",
            "cwd": "C:\\example\\workspace\\..\\project\\.",
            "createdAt": 1_768_473_600,
        }
    )
    second = RawThread.model_validate(
        {
            "id": "example-session-b",
            "cwd": "c:/example/project",
            "createdAt": 1_768_473_700,
        }
    )

    first_session = mapper.session(first, events_complete=False)
    second_session = mapper.session(second, events_complete=False)

    assert (
        first_session.source_project_id.get_secret_value()
        == second_session.source_project_id.get_secret_value()
        == "c:/example/project"
    )


def test_missing_cwd_creates_a_session_isolated_project_identity() -> None:
    mapper = CodexThreadMapper(provider_version="example-1")
    first = RawThread.model_validate(
        {"id": "example-session-a", "createdAt": 1_768_473_600}
    )
    second = RawThread.model_validate(
        {"id": "example-session-b", "createdAt": 1_768_473_700}
    )

    first_project = mapper.session(
        first, events_complete=False
    ).source_project_id.get_secret_value()
    second_project = mapper.session(
        second, events_complete=False
    ).source_project_id.get_secret_value()

    assert first_project != second_project
    assert first_project.startswith("missing-cwd-")
    assert second_project.startswith("missing-cwd-")
    assert "example-session" not in first_project

def test_thread_read_requires_explicit_turn_and_item_lists() -> None:
    valid_thread = {
        "id": "example-session-shape",
        "cwd": "/example/project",
        "createdAt": 1_768_473_600,
    }

    with pytest.raises(CodexCompatibilityError):
        parse_thread_read({"thread": valid_thread}, CodexReadLimits())

    with pytest.raises(CodexCompatibilityError):
        parse_thread_read(
            {
                "thread": {
                    **valid_thread,
                    "turns": [{"id": "example-turn-shape", "status": "completed"}],
                }
            },
            CodexReadLimits(),
        )


def test_relative_cwd_does_not_group_unrelated_sessions() -> None:
    mapper = CodexThreadMapper(provider_version="example-1")
    first = RawThread.model_validate(
        {
            "id": "example-relative-session-a",
            "cwd": "relative/project",
            "createdAt": 1_768_473_600,
        }
    )
    second = RawThread.model_validate(
        {
            "id": "example-relative-session-b",
            "cwd": "relative/project",
            "createdAt": 1_768_473_700,
        }
    )

    first_project = mapper.session(
        first, events_complete=False
    ).source_project_id.get_secret_value()
    second_project = mapper.session(
        second, events_complete=False
    ).source_project_id.get_secret_value()

    assert first_project != second_project
    assert first_project.startswith("missing-cwd-")
    assert second_project.startswith("missing-cwd-")


def test_event_identity_encoding_prevents_delimiter_collisions() -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-identities",
            "cwd": "/example/project",
            "createdAt": 1_768_473_600,
            "turns": [
                {
                    "id": "a:item:b",
                    "status": "completed",
                    "items": [
                        {"id": "c", "type": "commandExecution"}
                    ],
                },
                {
                    "id": "a",
                    "status": "completed",
                    "items": [
                        {"id": "b:item:c", "type": "commandExecution"}
                    ],
                },
            ],
        }
    )

    events = CodexThreadMapper(provider_version="example-1").snapshot(raw).events
    identities = tuple(
        event.source_event_id.get_secret_value() for event in events
    )

    assert len(identities) == len(set(identities))


def test_finalized_item_without_stable_id_fails_closed() -> None:
    raw = RawThread.model_validate(
        {
            "id": "example-session-missing-item-id",
            "cwd": "/example/project",
            "createdAt": 1_768_473_600,
            "turns": [
                {
                    "id": "example-turn-missing-item-id",
                    "status": "completed",
                    "items": [{"type": "commandExecution"}],
                }
            ],
        }
    )

    with pytest.raises(CodexCompatibilityError):
        CodexThreadMapper(provider_version="example-1").snapshot(raw)
