"""Known-answer bounds and framing for untrusted structured model responses."""

import json

import pytest

from prompt_enhancer.application.model_reply import (
    MAX_MODEL_CONTENT_CHARACTERS,
    MAX_MODEL_JSON_DEPTH,
    MAX_MODEL_REPLY_BYTES,
    completed_chat_content,
    model_json_object,
)


def _reply(content="example"):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


@pytest.mark.parametrize("payload", (None, "{}", b"", b"\xff", b"[]", b"null", b'{"choices": null}', b'{"choices": []}', b'{"choices": [true]}'))
def test_invalid_whole_response_fails_without_a_parser_exception(payload):
    assert completed_chat_content(payload) is None


def test_whole_response_byte_limit_is_inclusive():
    reply = _reply()
    reply["padding"] = ""
    reply["padding"] = "x" * (MAX_MODEL_REPLY_BYTES - len(json.dumps(reply).encode()))
    encoded = json.dumps(reply).encode()
    assert len(encoded) == MAX_MODEL_REPLY_BYTES
    assert completed_chat_content(encoded) == "example"
    assert completed_chat_content(encoded + b" ") is None


@pytest.mark.parametrize("character", ("x", "ż", "😀"))
def test_content_character_limit_is_inclusive_and_not_a_byte_guess(character):
    text = character * MAX_MODEL_CONTENT_CHARACTERS
    assert completed_chat_content(json.dumps(_reply(text), ensure_ascii=False).encode()) == text
    assert completed_chat_content(json.dumps(_reply(text + character), ensure_ascii=False).encode()) is None


@pytest.mark.parametrize("content", (None, "", " \n\t", [], {}, 12, True, "\ud800"))
def test_content_is_nonempty_unicode_text_not_coerced_data(content):
    assert completed_chat_content(json.dumps(_reply(content)).encode()) is None


def test_optional_runtime_metadata_does_not_turn_a_valid_text_reply_into_a_failure():
    reply = _reply("Synthetic example.")
    reply["usage"] = {"completion_tokens": 7, "prompt_tokens": 20}
    reply["choices"][0]["message"].update({"tool_calls": [], "refusal": None, "reasoning_content": "Synthetic model reasoning."})
    assert completed_chat_content(json.dumps(reply).encode()) == "Synthetic example."


@pytest.mark.parametrize("text", (
    '{"value": 1, "value": 2}', '{"nested": {"key": 1, "key": 2}}',
    '{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}', '{"value": 1e999}',
    '{"value": "\\ud800"}', '{"\\ud800": "example"}', '{"value": ["\\ud800"]}',
    '{"ok": true} {"other": true}', 'prefix {"ok": true}', '{"ok": true} suffix',
    '```json\n{"ok": true}\n```\nextra', '```text\n{"ok": true}\n```',
), ids=("duplicate", "nested-duplicate", "nan", "infinity", "negative-infinity", "overflow", "surrogate-value", "surrogate-key", "surrogate-list", "multiple-values", "prefix", "suffix", "fence-suffix", "wrong-fence"))
def test_inner_json_has_no_ambiguous_or_salvaged_reading(text):
    assert model_json_object(text) is None


@pytest.mark.parametrize("fence", ("", "```json\n{}\n```", "```JSON\r\n{}\r\n```", "```\n{}\n```"))
def test_exact_outer_fence_and_unicode_remain_compatible(fence):
    text = '{"note": "Przykład 😀"}'
    wrapped = fence.format(text) if fence else text
    assert model_json_object(" \n" + wrapped + "\n ") == {"note": "Przykład 😀"}


def test_inner_json_character_limit_and_depth_are_bounded():
    text = '{"example": "bounded"}'
    assert model_json_object(text, max_characters=len(text)) == {"example": "bounded"}
    assert model_json_object(text, max_characters=len(text) - 1) is None
    allowed = '{"value":' + '[' * (MAX_MODEL_JSON_DEPTH - 1) + '0' + ']' * (MAX_MODEL_JSON_DEPTH - 1) + '}'
    excessive = '{"value":' + '[' * MAX_MODEL_JSON_DEPTH + '0' + ']' * MAX_MODEL_JSON_DEPTH + '}'
    assert model_json_object(allowed) is not None
    assert model_json_object(excessive) is None
    # Excessive parser recursion is a closed invalid result too.
    assert model_json_object('{"value":' + '[' * 2_000 + '0' + ']' * 2_000 + '}') is None


@pytest.mark.parametrize("value", ("NaN", "Infinity", "1e999"))
def test_nonfinite_envelope_metadata_cannot_hide_behind_valid_content(value):
    encoded = json.dumps(_reply())[:-1] + ', "usage": ' + value + '}'
    assert completed_chat_content(encoded.encode()) is None
