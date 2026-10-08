from __future__ import annotations

import pytest

import prompt_enhancer.interfaces.http.browser_session as browser_session
from prompt_enhancer.interfaces.http.browser_session import BrowserSessionManager


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"lifetime_seconds": 59}, "lifetime"),
        ({"lifetime_seconds": 86_401}, "lifetime"),
        ({"max_sessions": 0}, "session count"),
        ({"max_sessions": 1_025}, "session count"),
        ({"max_csrf_tokens_per_session": 0}, "CSRF token count"),
        ({"max_csrf_tokens_per_session": 33}, "CSRF token count"),
    ],
)
def test_browser_session_configuration_is_bounded(
    arguments: dict[str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        BrowserSessionManager(**arguments)


def test_multiple_tabs_share_a_cookie_but_keep_bounded_csrf_tokens() -> None:
    manager = BrowserSessionManager(
        lifetime_seconds=60,
        max_sessions=2,
        max_csrf_tokens_per_session=2,
    )

    first_tab = manager.issue()
    second_tab = manager.issue(first_tab.cookie_value)
    third_tab = manager.issue(first_tab.cookie_value)

    assert second_tab.cookie_value == first_tab.cookie_value
    assert third_tab.cookie_value == first_tab.cookie_value
    assert manager.authenticate(first_tab.cookie_value) is True
    assert manager.verify_csrf(first_tab.cookie_value, first_tab.csrf_token) is False
    assert manager.verify_csrf(first_tab.cookie_value, second_tab.csrf_token) is True
    assert manager.verify_csrf(first_tab.cookie_value, third_tab.csrf_token) is True
    assert manager.verify_csrf(first_tab.cookie_value, "synthetic-invalid-token") is False


def test_capacity_evicts_oldest_session_and_expiry_invalidates_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"value": 1_000.0}
    monkeypatch.setattr(
        browser_session.time,
        "monotonic",
        lambda: clock["value"],
    )
    manager = BrowserSessionManager(lifetime_seconds=60, max_sessions=2)

    first = manager.issue()
    clock["value"] += 1
    second = manager.issue()
    clock["value"] += 1
    third = manager.issue()

    assert manager.authenticate(first.cookie_value) is False
    assert manager.authenticate(second.cookie_value) is True
    assert manager.authenticate(third.cookie_value) is True

    clock["value"] += 61
    assert manager.authenticate(second.cookie_value) is False
    assert manager.verify_csrf(third.cookie_value, third.csrf_token) is False


def test_attacker_controlled_secret_shapes_are_rejected_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BrowserSessionManager(lifetime_seconds=60)
    grant = manager.issue()

    def fail_if_hashed(_value: bytes):
        raise AssertionError("an implausible credential must not be hashed")

    monkeypatch.setattr(browser_session.hashlib, "sha256", fail_if_hashed)

    assert manager.authenticate("short") is False
    assert manager.authenticate("x" * 257) is False
    assert manager.verify_csrf("short", grant.csrf_token) is False
    assert manager.verify_csrf("x" * 257, grant.csrf_token) is False
    assert manager.verify_csrf(grant.cookie_value, "short") is False
    assert manager.verify_csrf(grant.cookie_value, "x" * 257) is False
