"""Strict allowlist for browser-history routes served by the local SPA.

The static host must not turn arbitrary or extension-like paths into successful
HTML responses.  Keep these shapes aligned with the frontend platform router;
identifiers are privacy-safe pseudonyms, never display labels.
"""

from __future__ import annotations

import re


_PSEUDONYM = r"[a-f0-9]{64}"
_MAX_SAFE_JAVASCRIPT_INTEGER = 9_007_199_254_740_991
_METRIC_CATEGORIES = frozenset(
    {
        "readiness",
        "execution",
        "tools",
        "model-usage",
        "outcome",
        "prompt-quality",
        "reasoning",
        "other",
    }
)
_PROJECT_VIEW = re.compile(
    rf"projects/({_PSEUDONYM})/(?:overview|sessions|automation)/?"
)
_PROJECT_METRICS = re.compile(
    rf"projects/({_PSEUDONYM})/metrics/([a-z-]+)/?"
)
_SESSION_METRICS = re.compile(
    rf"projects/({_PSEUDONYM})/sessions/({_PSEUDONYM})/metrics/([a-z-]+)/?"
)
_TASK_REVISION = re.compile(rf"tasks/({_PSEUDONYM})/revisions/([0-9]+)/?")
_PROMPT_CHECK = re.compile(rf"prompt-checks/(?:for/)?({_PSEUDONYM})/?")
_AGENT_WINDOW = re.compile(r"agent/window(?:/([0-9a-f]{32}))?/?")
_LIVE_WINDOW = re.compile(rf"live/projects/({_PSEUDONYM})(?:/sessions/({_PSEUDONYM}))?/?")


def is_spa_navigation_path(path: str) -> bool:
    """Return whether a decoded, leading-slash-free path is a known SPA route."""

    if path in {
        "",
        "local-sources",
        "local-sources/",
        "analysis-jobs",
        "analysis-jobs/",
        "projects",
        "projects/",
        "sessions",
        "sessions/",
        "calibration",
        "calibration/",
        "models",
        "models/",
        "prompt-checks",
        "prompt-checks/",
        "overview",
        "overview/",
        "agent",
        "agent/",
        "team",
        "team/",
        "tasks/flow",
        "tasks/flow/",
        "research/methods",
        "research/methods/",
        "social",
        "social/",
        "overlay/model-ensemble",
        "overlay/model-ensemble/",
    }:
        return True

    if _PROJECT_VIEW.fullmatch(path) is not None:
        return True
    if _PROMPT_CHECK.fullmatch(path) is not None:
        return True
    if _AGENT_WINDOW.fullmatch(path) is not None:
        return True
    if _LIVE_WINDOW.fullmatch(path) is not None:
        return True

    project_metrics = _PROJECT_METRICS.fullmatch(path)
    if project_metrics is not None:
        return project_metrics.group(2) in _METRIC_CATEGORIES

    session_metrics = _SESSION_METRICS.fullmatch(path)
    if session_metrics is not None:
        return session_metrics.group(3) in _METRIC_CATEGORIES

    task_revision = _TASK_REVISION.fullmatch(path)
    if task_revision is None:
        return False
    revision_text = task_revision.group(2)
    if len(revision_text) > 16:
        return False
    revision = int(revision_text)
    return 0 < revision <= _MAX_SAFE_JAVASCRIPT_INTEGER
