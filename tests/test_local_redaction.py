from __future__ import annotations

import pytest
from pydantic import SecretStr

from prompt_enhancer.infrastructure.redaction import (
    DETERMINISTIC_REDACTOR_VERSION,
    DeterministicLocalRedactor,
    LocalRedactionError,
    LocalRedactionLimitError,
    RedactionCategory,
)


def test_local_redactor_masks_structured_identifiers_without_exposing_repr() -> None:
    private = (
        "Contact analyst@example.com from 203.0.113.10 or +1 202-555-0123. "
        "Open https://example.com/private?ref=EXAMPLE_VALUE and "
        "X:\\EXAMPLE_WORKSPACE\\private\\notes.txt. "
        "api_key=EXAMPLE_SECRET_VALUE_123456789."
    )

    result = DeterministicLocalRedactor().redact(SecretStr(private))
    value = result.text.get_secret_value()

    assert DETERMINISTIC_REDACTOR_VERSION == "deterministic-local-redactor-v2"
    assert "[EMAIL]" in value
    assert "[IP_ADDRESS]" in value
    assert "[PHONE]" in value
    assert "[URL]" in value
    assert "[PATH]" in value
    assert "api_" + "key=[SECRET]" in value
    assert "example.com/private" not in value
    assert "EXAMPLE_SECRET_VALUE" not in value
    assert private not in repr(result)
    assert private not in result.model_dump_json()
    assert set(item.category for item in result.replacements) >= {
        RedactionCategory.EMAIL,
        RedactionCategory.IP_ADDRESS,
        RedactionCategory.PHONE,
        RedactionCategory.URL,
        RedactionCategory.PATH,
        RedactionCategory.SECRET,
    }


def test_local_redactor_is_deterministic_and_normalizes_controls() -> None:
    redactor = DeterministicLocalRedactor()
    private = SecretStr("Plan\r\nnext\x07 step for analyst@example.com")

    first = redactor.redact(private)
    second = redactor.redact(private)

    assert first == second
    assert first.text.get_secret_value() == "Plan\nnext  step for [EMAIL]"
    assert first.replacements[0].category is RedactionCategory.CONTROL


def test_local_redactor_rejects_nul_and_over_bound_input_safely() -> None:
    redactor = DeterministicLocalRedactor(max_input_characters=16)
    private_canary = "PRIVATE-REDACTION-CANARY"

    with pytest.raises(LocalRedactionError) as nul_error:
        redactor.redact(SecretStr(private_canary + "\x00"))
    with pytest.raises(LocalRedactionLimitError) as bound_error:
        redactor.redact(SecretStr(private_canary))

    assert private_canary not in str(nul_error.value)
    assert private_canary not in str(bound_error.value)


def test_local_redactor_requires_repr_safe_secret_input() -> None:
    with pytest.raises(TypeError, match="SecretStr"):
        DeterministicLocalRedactor().redact("plain text")  # type: ignore[arg-type]


@pytest.mark.parametrize("suffix", [".", ",", ";", ")", "!", "?", "..."])
def test_email_at_sentence_boundary_is_redacted(suffix):
    value = DeterministicLocalRedactor().redact(SecretStr("Contact person@example.test" + suffix))
    assert value.text.get_secret_value() == "Contact [EMAIL]" + suffix
