from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from prompt_enhancer import desktop_overlay


KEY_A = "a" * 32
KEY_B = "b" * 32
ORIGIN = "http://127.0.0.1:18765"


class _Event:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def emit(self) -> None:
        for handler in tuple(self.handlers):
            handler()


class _Window:
    def __init__(self, url: str) -> None:
        self.url = url
        self.events = SimpleNamespace(closed=_Event())
        self.confirm_close = True
        self.destroy_calls = 0
        self.destroy_confirm_close: list[bool] = []
        self.restore_calls = 0
        self.show_calls = 0

    def get_current_url(self) -> str:
        return self.url

    def destroy(self) -> None:
        self.destroy_calls += 1
        self.destroy_confirm_close.append(self.confirm_close)
        self.events.closed.emit()

    def restore(self) -> None:
        self.restore_calls += 1

    def show(self) -> None:
        self.show_calls += 1


def _assert_non_spawning_receipt(receipt: dict[str, object]) -> None:
    assert set(receipt) == {
        "listener_started",
        "process_spawned",
        "runtime_owner_created",
        "status",
        "version",
        "window_key",
        "worker_started",
    }
    assert receipt["version"] == "native-agent-window-v1"
    assert receipt["listener_started"] is False
    assert receipt["worker_started"] is False
    assert receipt["process_spawned"] is False
    assert receipt["runtime_owner_created"] is False


def test_coordinator_opens_one_child_then_focuses_it_without_new_ownership() -> None:
    created: list[_Window] = []
    focused: list[_Window] = []

    def create(key: str) -> _Window:
        window = _Window(f"{ORIGIN}/agent/window?window={key}")
        created.append(window)
        return window

    coordinator = desktop_overlay._NativeAgentWindowCoordinator(
        create,
        lambda window: focused.append(window) or True,
    )

    opened = coordinator.open_or_focus(KEY_A)
    duplicate = coordinator.open_or_focus(KEY_B)

    _assert_non_spawning_receipt(opened)
    _assert_non_spawning_receipt(duplicate)
    assert opened["status"] == "opened"
    assert opened["window_key"] == KEY_A
    assert duplicate["status"] == "focused"
    assert duplicate["window_key"] == KEY_A
    assert len(created) == 1
    assert focused == created


def test_concurrent_duplicate_requests_create_exactly_one_child() -> None:
    created: list[_Window] = []

    def create(key: str) -> _Window:
        window = _Window(f"{ORIGIN}/agent/window?window={key}")
        created.append(window)
        return window

    coordinator = desktop_overlay._NativeAgentWindowCoordinator(create, lambda _window: True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _index: coordinator.open_or_focus(KEY_A), range(32)))

    assert len(created) == 1
    assert sum(receipt["status"] == "opened" for receipt in receipts) == 1
    assert sum(receipt["status"] == "focused" for receipt in receipts) == 31
    assert {receipt["window_key"] for receipt in receipts} == {KEY_A}
    for receipt in receipts:
        _assert_non_spawning_receipt(receipt)


def test_child_close_releases_only_the_child_and_owner_shutdown_is_idempotent() -> None:
    created: list[_Window] = []

    def create(key: str) -> _Window:
        window = _Window(f"{ORIGIN}/agent/window?window={key}")
        created.append(window)
        return window

    coordinator = desktop_overlay._NativeAgentWindowCoordinator(create, lambda _window: True)
    assert coordinator.open_or_focus(KEY_A)["status"] == "opened"
    created[0].events.closed.emit()
    assert coordinator.children_closed() is True
    assert coordinator.open_or_focus(KEY_B)["status"] == "opened"

    coordinator.begin_owner_shutdown()
    coordinator.begin_owner_shutdown()

    assert created[1].destroy_calls == 1
    assert created[1].destroy_confirm_close == [False]
    assert coordinator.children_closed() is True
    assert coordinator.open_or_focus(KEY_A)["status"] == "unavailable"
    assert len(created) == 2


@pytest.mark.parametrize(
    "url",
    [
        f"{ORIGIN}/overview",
        f"{ORIGIN}/agent/window/{KEY_A}",
        f"{ORIGIN}/agent/window?window={KEY_A}&extra=1",
        f"{ORIGIN}/agent/window?window=not-a-key",
        f"{ORIGIN}/agent/window?window={KEY_A}#fragment",
    ],
)
def test_native_bridge_refuses_non_agent_or_overbroad_routes(url: str) -> None:
    coordinator = desktop_overlay._NativeAgentWindowCoordinator(
        lambda key: _Window(f"{ORIGIN}/agent/window?window={key}"),
        lambda _window: True,
    )
    api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        ORIGIN,
        None,
        coordinator,
    )
    api._bind(_Window(url))

    receipt = api.open_agent_chat_window(
        {"version": "native-agent-window-v1", "window_key": KEY_A}
    )

    assert receipt["status"] == "unavailable"
    _assert_non_spawning_receipt(receipt)


def test_native_bridge_requires_an_exact_opaque_request() -> None:
    created: list[str] = []
    coordinator = desktop_overlay._NativeAgentWindowCoordinator(
        lambda key: created.append(key) or _Window(f"{ORIGIN}/agent/window?window={key}"),
        lambda _window: True,
    )
    api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        ORIGIN,
        None,
        coordinator,
    )
    api._bind(_Window(f"{ORIGIN}/agent"))

    for request in (
        None,
        {"version": "native-agent-window-v2", "window_key": KEY_A},
        {"version": "native-agent-window-v1", "window_key": "c" * 31},
        {"version": "native-agent-window-v1", "window_key": KEY_A, "session_id": "d" * 32},
    ):
        receipt = api.open_agent_chat_window(request)
        assert receipt["status"] == "invalid_request"
        _assert_non_spawning_receipt(receipt)
    assert created == []


def test_primary_webview_owns_one_server_loop_and_closes_its_child_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Webview:
        FileDialog = SimpleNamespace(FOLDER="synthetic-folder")

        def __init__(self) -> None:
            self.created: list[tuple[tuple[object, ...], dict[str, object], _Window]] = []
            self.starts = 0
            self.receipts: list[dict[str, object]] = []

        def create_window(self, *args: object, **kwargs: object) -> _Window:
            window = _Window(str(kwargs["url"]))
            self.created.append((args, kwargs, window))
            return window

        def start(self, **_kwargs: object) -> None:
            self.starts += 1
            primary = self.created[0]
            api = primary[1]["js_api"]
            self.receipts.append(api.open_agent_chat_window(
                {"version": "native-agent-window-v1", "window_key": KEY_A}
            ))
            self.receipts.append(api.open_agent_chat_window(
                {"version": "native-agent-window-v1", "window_key": KEY_B}
            ))
            primary[2].events.closed.emit()

    webview = Webview()
    focus_calls: list[str] = []
    monkeypatch.setattr(
        desktop_overlay,
        "focus_existing_window",
        lambda title, **_kwargs: focus_calls.append(title) or True,
    )

    desktop_overlay._open_agent_window(
        webview,
        f"{ORIGIN}/agent",
        desktop_overlay.UserPresenceApprovalManager(),
    )

    assert webview.starts == 1
    assert len(webview.created) == 2
    primary, child = webview.created
    assert primary[0] == ("Prompt Enhancer - Agent workspace",)
    assert child[0] == ("Prompt Enhancer - Agent chat",)
    assert child[1]["url"] == f"{ORIGIN}/agent/window?window={KEY_A}"
    assert "session" not in str(child[1]["url"])
    assert child[2].destroy_calls == 1
    assert child[2].destroy_confirm_close == [False]
    assert child[2].restore_calls == 1
    assert child[2].show_calls == 1
    assert focus_calls == ["Prompt Enhancer - Agent chat"]
    assert [receipt["status"] for receipt in webview.receipts] == ["opened", "focused"]
    assert [receipt["window_key"] for receipt in webview.receipts] == [KEY_A, KEY_A]
    for receipt in webview.receipts:
        _assert_non_spawning_receipt(receipt)
