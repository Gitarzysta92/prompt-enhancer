"""Structural guard for beta gate definitions, not product acceptance."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "beta-acceptance-gates.md"
LEDGER = ROOT / "docs" / "product-readiness-matrix-2026-09-12.md"
FEATURES = ROOT / "docs" / "prompt-enhancer-owner-feature-register-2026-08-31.md"


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}\n"
    if document.count(marker) != 1:
        raise ValueError(f"missing or duplicate section: {heading}")
    remainder = document.split(marker, 1)[1]
    return remainder.split("\n## ", 1)[0]


def _rows(section: str, prefix: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if re.match(rf"^\| {prefix}\d{{2}} \|", line)
    ]


def _validate_contract(document: str, ledger: str, features: str) -> None:
    journey_section = _section(document, "Core user-journey gates (V01–V18)")
    journeys = _rows(journey_section, "V")
    workflows = _rows(_section(document, "Workflow gates (W00–W08)"), "W")
    expected_journeys = [f"V{number:02d}" for number in range(1, 19)]
    expected_workflows = [f"W{number:02d}" for number in range(9)]
    if [row[0] for row in journeys] != expected_journeys:
        raise ValueError("V01–V18 must each appear once, in order")
    if [row[0] for row in workflows] != expected_workflows:
        raise ValueError("W00–W08 must each appear once, in order")

    for row in journeys + workflows:
        expected_columns = 4 if row[0].startswith("V") else 3
        if len(row) != expected_columns or any(not cell for cell in row):
            raise ValueError(f"incomplete gate row: {row[0]}")
        if any(re.search(r"\b(TODO|TBD)\b", cell, re.IGNORECASE) for cell in row):
            raise ValueError(f"placeholder gate row: {row[0]}")
        for candidate in re.findall(r"`((?:tests|scripts|frontend)/[^`]+)`", " ".join(row)):
            if not (ROOT / candidate).is_file():
                raise ValueError(f"missing automated anchor in {row[0]}")

    checkpoint_ids = re.findall(r"^\| (B\d{2}):", ledger, flags=re.MULTILINE)
    if checkpoint_ids != [f"B{number:02d}" for number in range(12)]:
        raise ValueError("authoritative ledger must retain B00–B11 once, in order")
    if not re.search(r"^\| W00–W08:", ledger, flags=re.MULTILINE):
        raise ValueError("authoritative ledger is missing the workflow checkpoint row")
    if not re.search(r"^\| Post-beta:", ledger, flags=re.MULTILINE):
        raise ValueError("deferred features must remain distinguished from beta")

    mapped_families = re.findall(
        r"^\| (APP|AGT|MOD|WSP|ART|MCP|ORC|UX|REL) \| ([^|]+) \|$",
        journey_section,
        flags=re.MULTILINE,
    )
    expected_families = ["APP", "AGT", "MOD", "WSP", "ART", "MCP", "ORC", "UX", "REL"]
    if [family for family, _ in mapped_families] != expected_families:
        raise ValueError("each owner feature family needs one V-gate mapping")
    for family, mapped_gates in mapped_families:
        if not re.search(r"V\d{2}", mapped_gates):
            raise ValueError(f"unmapped feature family: {family}")

    feature_ids = re.findall(
        r"^\| ((?:APP|AGT|MOD|WSP|ART|MCP|ORC|UX|REL)-\d{2}) \|",
        features,
        flags=re.MULTILINE,
    )
    if len(feature_ids) != len(set(feature_ids)) or len(feature_ids) < 67:
        raise ValueError("owner feature register lost or duplicated detailed gates")


def test_current_beta_gate_inventory_is_complete() -> None:
    _validate_contract(
        CONTRACT.read_text(encoding="utf-8"),
        LEDGER.read_text(encoding="utf-8"),
        FEATURES.read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize("missing_id", ["V08", "W03"])
def test_inventory_rejects_a_missing_gate(missing_id: str) -> None:
    document = CONTRACT.read_text(encoding="utf-8")
    document = re.sub(rf"^\| {missing_id} \|.*\n", "", document, count=1, flags=re.MULTILINE)
    with pytest.raises(ValueError, match="must each appear once"):
        _validate_contract(
            document,
            LEDGER.read_text(encoding="utf-8"),
            FEATURES.read_text(encoding="utf-8"),
        )


def test_inventory_rejects_unbacked_automated_anchor() -> None:
    document = CONTRACT.read_text(encoding="utf-8").replace(
        "`tests/test_agent_catalog.py`", "`tests/not_an_existing_gate.py`", 1
    )
    with pytest.raises(ValueError, match="missing automated anchor"):
        _validate_contract(
            document,
            LEDGER.read_text(encoding="utf-8"),
            FEATURES.read_text(encoding="utf-8"),
        )
