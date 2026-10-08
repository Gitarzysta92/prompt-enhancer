from __future__ import annotations

import hashlib
import hmac
import os

import pytest
from pydantic import ValidationError

from prompt_enhancer.config import AppSettings, ConfigurationError
from prompt_enhancer.domain import DataTier
from prompt_enhancer.privacy import (
    Pseudonymizer,
    load_or_create_api_token,
    load_or_create_pseudonymizer,
)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "example.invalid"])
def test_phase_one_rejects_non_loopback_hosts(tmp_path, host: str) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        AppSettings(home=tmp_path, host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_phase_one_accepts_loopback_hosts(tmp_path, host: str) -> None:
    settings = AppSettings(home=tmp_path, host=host)
    assert settings.host == host


def test_phase_one_rejects_content_storage_and_non_offline_modes(tmp_path) -> None:
    with pytest.raises(ValidationError, match="metadata"):
        AppSettings(home=tmp_path, data_tier=DataTier.REDACTED_CONTENT)

    with pytest.raises(ValidationError):
        AppSettings(home=tmp_path, cost_mode="remote_allowed")


def test_environment_parser_does_not_consume_provider_keys(tmp_path) -> None:
    environment = {
        "PROMPT_ENHANCER_HOME": os.fspath(tmp_path),
        "PROMPT_ENHANCER_HOST": "127.0.0.1",
        "PROMPT_ENHANCER_PORT": "9876",
        "OPENAI_API_KEY": "example_token_do_not_use",
        "ANTHROPIC_API_KEY": "example_token_do_not_use",
    }
    settings = AppSettings.from_env(environment)

    assert settings.home == tmp_path.resolve()
    assert settings.port == 9876
    assert settings.cost_mode.value == "offline_only"
    assert settings.data_tier.value == "metadata"


def test_invalid_environment_port_is_safe_error(tmp_path) -> None:
    with pytest.raises(ConfigurationError, match="must be an integer"):
        AppSettings.from_env(
            {
                "PROMPT_ENHANCER_HOME": os.fspath(tmp_path),
                "PROMPT_ENHANCER_PORT": "not-a-port",
            }
        )


def test_hmac_pseudonyms_are_stable_and_domain_separated() -> None:
    pseudonymizer = Pseudonymizer(bytes(range(32)))

    session_one = pseudonymizer.pseudonymize("synthetic:session", "example-id")
    session_two = pseudonymizer.pseudonymize("synthetic:session", "example-id")
    event = pseudonymizer.pseudonymize("synthetic:event", "example-id")

    assert hmac.compare_digest(session_one, session_two)
    assert not hmac.compare_digest(session_one, event)
    assert len(session_one) == 64
    assert "example-id" not in session_one


def test_private_key_and_api_token_are_created_once(tmp_path) -> None:
    key_path = tmp_path / "pseudonym.key"
    token_path = tmp_path / "api.token"

    first_pseudonymizer = load_or_create_pseudonymizer(key_path)
    second_pseudonymizer = load_or_create_pseudonymizer(key_path)
    first_digest = first_pseudonymizer.pseudonymize("test", "example-id")
    second_digest = second_pseudonymizer.pseudonymize("test", "example-id")

    first_token = load_or_create_api_token(token_path)
    second_token = load_or_create_api_token(token_path)

    assert hmac.compare_digest(first_digest, second_digest)
    assert hmac.compare_digest(first_token, second_token)
    assert key_path.stat().st_size == 32
    assert token_path.stat().st_size >= 32
    assert hashlib.sha256(key_path.read_bytes()).digest() != hashlib.sha256(
        token_path.read_bytes()
    ).digest()

    if os.name != "nt":
        assert key_path.stat().st_mode & 0o077 == 0
        assert token_path.stat().st_mode & 0o077 == 0
