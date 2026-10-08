"""Pure deterministic construction of a local-only diagnostic bundle."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import SecretBytes

from .contracts import (
    BundleBudget,
    BundlePreview,
    DiagnosticBundle,
    DiagnosticObservation,
    DiagnosticSection,
    DiagnosticValueKind,
)
from .ports import DiagnosticRedactor


_REDACTION_MARKER = re.compile(r"^\[[A-Z_]{1,32}\]$")
_COUNT_VALUE = re.compile(r"^(?:0|[1-9][0-9]{0,19})$")
_VERSION_VALUE = re.compile(
    r"^[0-9]{1,6}(?:\.[0-9]{1,6}){1,2}(?:[-+][A-Za-z0-9.]{1,32})?$"
)
_SAFE_REDACTOR_VERSION = re.compile(r"^[A-Za-z0-9_.\-]{1,96}$")
_STATE_VALUES = frozenset(
    {
        "available",
        "degraded",
        "disabled",
        "enabled",
        "failed",
        "hardened",
        "missing",
        "ready",
        "rejected",
        "unavailable",
        "unknown",
        "unverified",
    }
)


def _safe_structured_value(value: str, kind: DiagnosticValueKind) -> bool:
    if _REDACTION_MARKER.fullmatch(value):
        return True
    if kind is DiagnosticValueKind.BOOLEAN:
        return value in {"true", "false"}
    if kind is DiagnosticValueKind.COUNT:
        return _COUNT_VALUE.fullmatch(value) is not None
    if kind is DiagnosticValueKind.VERSION:
        return _VERSION_VALUE.fullmatch(value) is not None
    return value in _STATE_VALUES


def _encode_payload(
    facts: list[dict[str, str]], *, redactor_version: str, truncated: bool
) -> bytes:
    return (
        json.dumps(
            {
                "facts": facts,
                "redactor_version": redactor_version,
                "schema_version": 1,
                "truncated": truncated,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )


def build_diagnostic_bundle(
    observations: tuple[DiagnosticObservation, ...],
    *,
    budget: BundleBudget,
    redactor: DiagnosticRedactor,
) -> DiagnosticBundle:
    """Redact bounded structured facts; omit any unstructured or failed value."""

    if not _SAFE_REDACTOR_VERSION.fullmatch(redactor.version):
        raise ValueError("diagnostic_redactor_version_invalid")
    accepted: list[dict[str, str]] = []
    omitted = max(0, len(observations) - budget.max_observations)
    section_bytes: dict[DiagnosticSection, int] = {}
    truncated = len(observations) > budget.max_observations
    ordered = sorted(
        observations[: budget.max_observations],
        key=lambda item: (item.section.value, item.event_code, item.fact_key),
    )
    for observation in ordered:
        try:
            redacted = redactor.redact_value(observation.value).get_secret_value()
        except Exception:
            omitted += 1
            continue
        # Diagnostics accept codes/versions/counts only.  Human prose,
        # transcripts, exception strings, and source content are excluded even
        # after best-effort redaction.
        if not _safe_structured_value(redacted, observation.value_kind):
            omitted += 1
            continue
        fact = {
            "event_code": observation.event_code,
            "fact_key": observation.fact_key,
            "section": observation.section.value,
            "value_kind": observation.value_kind.value,
            "value": redacted,
        }
        fact_size = len(
            json.dumps(fact, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        )
        current_section_size = section_bytes.get(observation.section, 0)
        if current_section_size + fact_size > budget.max_section_bytes:
            omitted += 1
            truncated = True
            continue
        candidate = [*accepted, fact]
        candidate_payload = _encode_payload(
            candidate,
            redactor_version=redactor.version,
            truncated=truncated or omitted > 0,
        )
        if len(candidate_payload) > budget.max_total_bytes:
            omitted += 1
            truncated = True
            continue
        accepted.append(fact)
        section_bytes[observation.section] = current_section_size + fact_size
    truncated = truncated or omitted > 0
    payload = _encode_payload(
        accepted,
        redactor_version=redactor.version,
        truncated=truncated,
    )
    # The fixed envelope alone fits the minimum budget.  Keep a defensive
    # branch so no caller can receive bytes that disagree with the preview.
    if len(payload) > budget.max_total_bytes:
        accepted = []
        omitted = len(observations)
        truncated = True
        payload = _encode_payload(
            accepted,
            redactor_version=redactor.version,
            truncated=True,
        )
    sections = tuple(
        DiagnosticSection(value)
        for value in sorted({fact["section"] for fact in accepted})
    )
    preview = BundlePreview(
        byte_count=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        included_sections=sections,
        included_observations=len(accepted),
        omitted_observations=omitted,
        truncated=truncated,
        redactor_version=redactor.version,
    )
    return DiagnosticBundle(preview=preview, payload=SecretBytes(payload))
