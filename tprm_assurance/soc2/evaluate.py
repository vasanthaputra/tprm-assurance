"""Module 4: score an extraction against hand-verified ground truth, field by field.

Any extractor (rules, copy-paste, API) produces the same JSON shape, so any of them can
be scored here. The result is a table a reader can check, not a single percentage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    field: str
    key: str
    expected: object
    got: object

    @property
    def ok(self) -> bool:
        return self.expected == self.got


def _norm(v):
    return sorted(v) if isinstance(v, list) else v


def score(extraction: dict, truth: dict) -> list[Check]:
    checks: list[Check] = []
    for field, expected in truth.items():
        if field.startswith("_"):
            continue
        got = extraction.get(field) or {}
        for key, val in expected.items():
            checks.append(Check(field, key, _norm(val), _norm(got.get(key))))
    return checks


def summary(checks: list[Check]) -> tuple[int, int]:
    return sum(c.ok for c in checks), len(checks)


def to_markdown(checks: list[Check], extraction: dict, truth_path: Path) -> str:
    ok, total = summary(checks)
    pct = 100.0 * ok / total if total else 0.0
    L = [f"# Extraction accuracy: {extraction.get('source_file')} via `{extraction.get('extractor')}`", "",
         f"**{ok} / {total} fields correct ({pct:.0f}%)** against `{truth_path.name}`.", "",
         "| Field | Key | Expected | Got | OK |", "|---|---|---|---|---|"]
    for c in checks:
        L.append(f"| {c.field} | {c.key} | {c.expected} | {c.got} | {'yes' if c.ok else '**NO**'} |")
    L += ["", "Ground truth was read by hand from the document; see SOURCES.md."]
    return "\n".join(L) + "\n"


def run(extraction_path: Path, truth_path: Path) -> tuple[list[Check], dict]:
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    return score(extraction, truth), extraction
