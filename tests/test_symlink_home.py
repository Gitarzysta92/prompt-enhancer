from __future__ import annotations

import pytest

from prompt_enhancer.config import AppSettings, ConfigurationError, prepare_app_home


def test_application_home_rejects_symlink_before_resolution(tmp_path) -> None:
    target = tmp_path / "state-target"
    target.mkdir()
    link = tmp_path / "state-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc.__class__.__name__}")

    settings = AppSettings(home=link)
    with pytest.raises(ConfigurationError, match="symlink"):
        prepare_app_home(settings)
