"""Claude Code ``UserPromptSubmit`` hook: ask the local app to check the prompt, hand the advice back.

Claude Code runs the configured command with the hook payload on stdin; what
the command prints as ``hookSpecificOutput.additionalContext`` is added to the
model's context for that turn. This hook posts the prompt to the app's own
loopback API (``POST /v1/prompt-checks``), which analyses it locally, stores
metrics only, and returns the deterministic cues plus - when a local model is
active - commentary and a reformulated prompt. The hook never blocks: on any
failure it prints nothing and exits 0. It is opt-in: the person adds it to
their settings (``prompt-enhancer claude-prompt-check-config`` prints the
snippet) and can switch it off with ``PROMPT_ENHANCER_PROMPT_CHECK_HOOK=0``.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import sys
from typing import Any, TextIO
import urllib.error
import urllib.request

from ...config import AppSettings


HOOK_ENABLED_ENV = "PROMPT_ENHANCER_PROMPT_CHECK_HOOK"
HOOK_COMMENTARY_ENV = "PROMPT_ENHANCER_PROMPT_CHECK_COMMENTARY"
HOOK_TIMEOUT_ENV = "PROMPT_ENHANCER_PROMPT_CHECK_TIMEOUT_SECONDS"
MIN_PROMPT_WORDS = 4
MAX_ADDITIONAL_CONTEXT_CHARS = 3_000
DEFAULT_TIMEOUT_SECONDS = 45.0
_OFF = {"0", "false", "off", "no"}


def _enabled(env: Mapping[str, str]) -> bool:
    return env.get(HOOK_ENABLED_ENV, "1").strip().casefold() not in _OFF


def _want_commentary(env: Mapping[str, str]) -> bool:
    return env.get(HOOK_COMMENTARY_ENV, "1").strip().casefold() not in _OFF


def _timeout(env: Mapping[str, str]) -> float:
    try:
        value = float(env.get(HOOK_TIMEOUT_ENV, str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return min(max(value, 2.0), 300.0)


def additional_context_from_result(result: Mapping[str, Any]) -> str:
    """Render the app's answer as compact advice for the model (bounded)."""

    lines = ["Prompt Enhancer checked the user's latest prompt (local analysis; advice, not a verdict)."]
    summary = result.get("summary")
    if isinstance(summary, str) and summary:
        lines.append(summary)
    commentary = result.get("commentary") if isinstance(result.get("commentary"), Mapping) else {}
    findings = commentary.get("findings") if isinstance(commentary, Mapping) else None
    if isinstance(findings, list) and findings:
        lines.append("Suggestions from the local model (check them against the user's intent):")
        for item in findings[:5]:
            if isinstance(item, Mapping):
                lines.append(f"- [{item.get('severity', 'medium')}] {item.get('aspect', 'other')}: {item.get('suggestion', '')}".rstrip())
    reformulated = commentary.get("reformulated_prompt") if isinstance(commentary, Mapping) else None
    if isinstance(reformulated, str) and reformulated.strip():
        lines.append("A reformulated version of the prompt (keep only what matches the user's intent; placeholders in <...> are things to ask about):")
        lines.append(reformulated.strip())
    context = result.get("context") if isinstance(result.get("context"), Mapping) else {}
    if isinstance(context, Mapping) and context.get("depends_on_prior_context") and not context.get("prior_context_supplied"):
        lines.append("The prompt seems to rely on earlier conversation the checker did not see; resolve references from your own context before acting.")
    lines.append("If something essential is missing, ask the user one short clarifying question before doing work; otherwise proceed.")
    text = "\n".join(lines)
    if len(text) > MAX_ADDITIONAL_CONTEXT_CHARS:
        text = text[: MAX_ADDITIONAL_CONTEXT_CHARS - 1].rstrip() + "…"
    return text


def post_prompt_check(settings: AppSettings, payload: Mapping[str, Any], *, timeout: float = 60.0, opener=None) -> dict[str, Any] | None:
    """POST a prompt check to the running local app; None when it is not running or refuses.

    Used by the MCP server process, which has no model runtime of its own, so
    that ``check_prompt`` gets the same commentary as the dashboard when the app
    is up and falls back to deterministic cues when it is not.
    """

    token_path = settings.api_token_path
    try:
        if not token_path.is_file():
            return None
        token = token_path.read_text(encoding="utf-8").strip()
        request = urllib.request.Request(
            f"http://{settings.host}:{settings.port}/v1/prompt-checks",
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Prompt-Enhancer-Token": token},
            method="POST",
        )
        open_url = opener or urllib.request.urlopen
        with open_url(request, timeout=timeout) as response:  # noqa: S310 - loopback only
            if response.status != 200:
                return None
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def run_prompt_check_hook(
    settings: AppSettings,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    env: Mapping[str, str] | None = None,
    opener=None,
) -> int:
    """Read one hook payload, post the prompt to the loopback API, print the advice. Always exits 0."""

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    env = env if env is not None else os.environ
    try:
        if not _enabled(env):
            return 0
        raw = stdin.read()
        if not raw or len(raw) > 400_000:
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            return 0
        if payload.get("hook_event_name") not in (None, "UserPromptSubmit"):
            return 0
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return 0
        prompt = prompt.strip()
        if not prompt or prompt.startswith("/") or (len(prompt.split()) < MIN_PROMPT_WORDS and "?" not in prompt):
            return 0
        token_path = settings.api_token_path
        if not token_path.is_file():
            return 0
        token = token_path.read_text(encoding="utf-8").strip()
        body = json.dumps(
            {
                "prompt": prompt[:20_000],
                "provider": "claude_code",
                "want_commentary": _want_commentary(env),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://{settings.host}:{settings.port}/v1/prompt-checks",
            data=body,
            headers={"Content-Type": "application/json", "X-Prompt-Enhancer-Token": token},
            method="POST",
        )
        open_url = opener or urllib.request.urlopen
        try:
            with open_url(request, timeout=_timeout(env)) as response:  # noqa: S310 - loopback only
                if response.status != 200:
                    return 0
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return 0
        if not isinstance(result, Mapping):
            return 0
        advice = additional_context_from_result(result)
        stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": advice}}) + "\n")
        stdout.flush()
        return 0
    except Exception:  # noqa: BLE001 - a hook must never block the person's prompt
        return 0


__all__ = (
    "HOOK_COMMENTARY_ENV",
    "HOOK_ENABLED_ENV",
    "HOOK_TIMEOUT_ENV",
    "additional_context_from_result",
    "post_prompt_check",
    "run_prompt_check_hook",
)
