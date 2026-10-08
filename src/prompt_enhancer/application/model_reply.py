"""Fail-closed, content-free validation for whole structured model replies.

A generation receipt is necessary for accepting commentary or labels. It is
not evidence that a task succeeded, or that a model's claims are correct.
"""

from __future__ import annotations

import json
import math
import re


MAX_MODEL_REPLY_BYTES = 2_000_000
MAX_MODEL_CONTENT_CHARACTERS = 64_000
MAX_MODEL_JSON_DEPTH = 32
_OUTER_FENCE = re.compile(r"```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```", re.I | re.S)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("model_reply_invalid")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> object:
    raise ValueError("model_reply_invalid")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("model_reply_invalid")
    return parsed


def _json_value(text: str) -> object:
    """Reject ambiguous keys, non-JSON numbers, invalid Unicode and deep trees."""

    value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant, parse_float=_finite_float)
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_MODEL_JSON_DEPTH:
            raise ValueError("model_reply_invalid")
        if isinstance(item, str):
            item.encode("utf-8", errors="strict")
        elif isinstance(item, dict):
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def completed_chat_content(payload: object) -> str | None:
    """Read exactly one completed assistant text reply, never a tool request.

    Runtime metadata may contain additional fields, but cannot contradict the
    receipt. Missing completion information stays unknown, not successful.
    No raw response or parser exception escapes this boundary.
    """

    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_MODEL_REPLY_BYTES:
        return None
    try:
        reply = _json_value(payload.decode("utf-8", errors="strict"))
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(reply, dict) or reply.get("error") is not None:
        return None
    choices = reply.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return None
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        return None
    if "index" in choice and (type(choice["index"]) is not int or choice["index"] != 0):
        return None
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    tool_calls = message.get("tool_calls")
    if tool_calls is not None and (not isinstance(tool_calls, list) or tool_calls):
        return None
    if message.get("function_call") is not None or message.get("refusal") not in (None, ""):
        return None
    content = message.get("content")
    if not isinstance(content, str) or not 0 < len(content) <= MAX_MODEL_CONTENT_CHARACTERS or not content.strip():
        return None
    return content


def model_json_object(text: object, *, max_characters: int = MAX_MODEL_CONTENT_CHARACTERS) -> dict[str, object] | None:
    """Decode one bounded JSON object, optionally in one exact outer code fence.

    Do not search for braces inside prose or salvage a partial/trailing reply.
    A harmless outer fence is compatible with older local model templates.
    """

    if not isinstance(text, str) or not 0 < len(text) <= max_characters:
        return None
    candidate = text.strip()
    fenced = _OUTER_FENCE.fullmatch(candidate)
    if fenced:
        candidate = fenced.group("body").strip()
    try:
        value = _json_value(candidate)
    except (ValueError, TypeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


__all__ = ("MAX_MODEL_CONTENT_CHARACTERS", "MAX_MODEL_JSON_DEPTH", "MAX_MODEL_REPLY_BYTES", "completed_chat_content", "model_json_object")
