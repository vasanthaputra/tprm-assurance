"""Planted-error test for the Jev check: does Jev accept true values and reject planted
wrong ones, on the real report pages, with the production question wording?

Cases come from the answer keys (true) plus planted values (false, SYNTHETIC and labelled
in a cases file kept locally with the answer keys). One request per report and field, the cited page
as state, exactly as `soc2 jev-check` sends it. Failed calls raise: an eval must not turn
an error into an answer.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .extract import CATEGORIES
from .jev_check import JEV_MODEL, TEMPLATES, _loose, _to_sdk


@dataclass
class Case:
    report: str
    field: str          # "<field>.<key>"
    candidate: str
    expected: bool      # True = the page supports it; False = planted wrong value
    page: int
    hard: bool = False
    p: float | None = None


def build_cases(spec: dict, truth: dict, pages: list[str]) -> list[Case]:
    hard = spec.get("hard", {})
    out: list[Case] = []

    def add(field, cand, expected, page):
        out.append(Case(spec["name"], field, cand, expected, page, cand in hard.get(field, [])))

    rt, op = truth["report_type"], truth["opinion"]
    for cand in ("SOC2_TYPE2", "SOC2_TYPE1"):
        add("report_type.value", cand, cand == rt["value"], rt["page"])
    for cand in ("UNQUALIFIED", "QUALIFIED", "ADVERSE_OR_DISCLAIMER"):
        add("opinion.value", cand, cand == op["value"], op["page"])
    cats = truth["categories"]
    for cand in CATEGORIES:
        add("categories.in_scope", cand, cand in cats["in_scope"], cats["page"])
    sub = truth["subservice_orgs"]
    page_text = _loose(pages[sub["page"] - 1])
    for name in sub["values"]:
        add("subservice_orgs.values", name, True, sub["page"])
    for name in spec.get("subservice_decoys", []):
        if _loose(name) in page_text:
            raise ValueError(f"decoy {name!r} appears on page {sub['page']}; it would not be a planted error")
        add("subservice_orgs.values", name, False, sub["page"])
    return out


def run(cases: list[Case], pages_by_report: dict[str, list[str]], client) -> list[Case]:
    groups: dict[tuple[str, str, int], list[Case]] = {}
    for c in cases:
        groups.setdefault((c.report, c.field, c.page), []).append(c)
    for (report, field, page), group in groups.items():
        key = tuple(field.split("."))
        ref = f"`page_{page}`"
        state = {f"page_{page}": pages_by_report[report][page - 1]}
        questions = {f"c{i}": TEMPLATES[key](c.candidate, ref) for i, c in enumerate(group)}
        resp = client.system_one(state=state, questions=_to_sdk(questions), model=JEV_MODEL)
        for i, c in enumerate(group):
            c.p = float(resp.nouls[f"c{i}"].noul)
    return cases


def score(cases: list[Case], yes: float, no: float) -> dict:
    s = {"true": {"accepted": 0, "unsettled": 0, "rejected_WRONG": 0},
         "planted": {"rejected": 0, "unsettled": 0, "accepted_WRONG": 0}}
    for c in cases:
        if c.expected:
            k = "accepted" if c.p >= yes else "rejected_WRONG" if c.p <= no else "unsettled"
            s["true"][k] += 1
        else:
            k = "rejected" if c.p <= no else "accepted_WRONG" if c.p >= yes else "unsettled"
            s["planted"][k] += 1
    s["accuracy_at_0.5"] = sum((c.p >= 0.5) == c.expected for c in cases) / len(cases)
    s["n"] = len(cases)
    return s


def to_markdown(cases: list[Case], thresholds: list[tuple[float, float]]) -> str:
    L = ["# Jev planted-error test", "",
         f"Model `{JEV_MODEL}`. {len(cases)} questions: {sum(c.expected for c in cases)} true values, "
         f"{sum(not c.expected for c in cases)} planted wrong values (synthetic). Production question wording, unchanged.", "",
         "| Thresholds (yes / no) | True accepted | True unsettled | **True rejected (wrong)** | Planted rejected | Planted unsettled | **Planted accepted (wrong)** | Accuracy at 0.5 |",
         "|---|---|---|---|---|---|---|---|"]
    for yes, no in thresholds:
        s = score(cases, yes, no)
        L.append(f"| {yes} / {no} | {s['true']['accepted']} | {s['true']['unsettled']} | {s['true']['rejected_WRONG']} | "
                 f"{s['planted']['rejected']} | {s['planted']['unsettled']} | {s['planted']['accepted_WRONG']} | {s['accuracy_at_0.5']:.0%} |")
    L += ["", "## Every question", "", "| Report | Field | Value | Truth | P(yes) | Hard |", "|---|---|---|---|---|---|"]
    for c in sorted(cases, key=lambda c: (c.report, c.field, not c.expected, c.candidate)):
        L.append(f"| {c.report} | {c.field} | {c.candidate} | {'true' if c.expected else 'planted'} | {c.p:.2f} | {'yes' if c.hard else ''} |")
    return "\n".join(L) + "\n"


def save(cases: list[Case], path: Path) -> None:
    path.write_text(json.dumps([asdict(c) for c in cases], indent=2, ensure_ascii=False), encoding="utf-8")
