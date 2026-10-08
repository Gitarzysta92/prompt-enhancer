from __future__ import annotations

from prompt_enhancer.adapters.base import ProviderAdapter
from prompt_enhancer.adapters.synthetic import SyntheticAdapter


def test_provider_contract_exposes_read_only_operations_only() -> None:
    public_names = {name for name in dir(ProviderAdapter) if not name.startswith("_")}

    assert {"provider", "probe", "list_sessions", "read_events", "health"} <= public_names
    assert not {
        "archive",
        "delete",
        "rename",
        "resume",
        "run_sql",
        "send_prompt",
        "update",
        "write",
    }.intersection(public_names)


def test_synthetic_adapter_contains_metadata_but_no_message_text() -> None:
    adapter = SyntheticAdapter()
    page = adapter.list_sessions()

    assert len(page.sessions) == 2
    assert page.next_cursor is None
    assert adapter.probe().supports_metadata is True
    assert adapter.probe().supports_content is False

    for session in page.sessions:
        for event in adapter.read_events(session):
            assert "message" not in event.model_fields_set
            assert "content" not in event.model_fields_set
            assert "prompt" not in event.model_fields_set
