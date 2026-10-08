"""Optional agent hooks that call the local app over loopback (ADR 0015)."""

from .prompt_check_hook import (
    HOOK_COMMENTARY_ENV,
    HOOK_ENABLED_ENV,
    additional_context_from_result,
    post_prompt_check,
    run_prompt_check_hook,
)

__all__ = (
    "HOOK_COMMENTARY_ENV",
    "HOOK_ENABLED_ENV",
    "additional_context_from_result",
    "post_prompt_check",
    "run_prompt_check_hook",
)
