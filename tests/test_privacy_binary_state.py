from __future__ import annotations

import prompt_enhancer.privacy as privacy


def test_random_key_bytes_are_written_without_text_translation(
    tmp_path,
    monkeypatch,
) -> None:
    key = b"\n" + (b"x" * (privacy.PSEUDONYM_KEY_BYTES - 1))
    monkeypatch.setattr(privacy.secrets, "token_bytes", lambda count: key)
    path = tmp_path / "pseudonym.key"

    privacy.load_or_create_pseudonymizer(path)

    assert path.read_bytes() == key
