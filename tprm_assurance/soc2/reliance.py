"""Reliance decision: can this SOC 2 report be relied on, for the services we use?

Takes an extraction (from extract.py or an AI extractor) plus the reviewer's context
(what services and categories we need, what we already hold) and proposes findings.
Nothing becomes a finding until a human approves it (see review.py).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from ..register import months_between
from .extract import period_months

RULES = {
    "TYPE1_WHERE_TYPE2":        ("Type 1 (point in time) report where a Type 2 is expected", "S3"),
    "PERIOD_SHORT":             ("Type 2 period shorter than 6 months; ask why", "S3 ('commonly 6 or 12 months')"),
    "BRIDGE_LETTER_NEEDED":     ("Period ended over 3 months ago; obtain a bridge letter from the vendor's management", "S3"),
    "REPORT_STALE":             ("Period ended over 15 months ago; ask for the successor report", "S3"),
    "OPINION_QUALIFIED":        ("Qualified opinion; read the basis and decide whether it touches the services used", "S3"),
    "OPINION_ADVERSE":          ("Adverse opinion or disclaimer; do not rely", "S3"),
    "OPINION_UNKNOWN":          ("Could not read the opinion; review page 1 of the auditor's report by hand", "extractor"),
    "CATEGORY_NOT_IN_SCOPE":    ("A category we need is not in the report's scope", "S3"),
    "CATEGORY_WORDING_MIXED":   ("Scope names more categories in one place than another; confirm what was tested", "S5 observation"),
    "CARVE_OUT_NO_ASSURANCE":   ("Carved-out subservice organisation with no assurance report on file", "S3"),
    "CUEC_UNOWNED":             ("Complementary user entity controls with no internal owner", "S3"),
    "NO_CUEC_SECTION":          ("No CUEC section found (thin report)", "S3"),
    "EXCEPTIONS_PRESENT":       ("Test results other than 'No exceptions noted'; triage each", "S3, S5"),
}


def report_hash(ex: dict) -> str:
    """Content hash of the extraction. Decisions are bound to it, so a decision made on one
    report can never be applied to a different report that happens to share a file name."""
    canon = json.dumps({k: v for k, v in ex.items() if k not in ("source_file", "extractor")}, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


@dataclass
class Finding:
    id: str
    rule: str
    detail: str
    page: int | None
    report_hash: str
    status: str = "PROPOSED"   # PROPOSED -> APPROVED | REJECTED (by a human)

    @property
    def meaning(self) -> str:
        return RULES[self.rule][0]

    @property
    def source(self) -> str:
        return RULES[self.rule][1]


def load_context(path: Path) -> dict:
    ctx = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ctx["as_of"] = date.fromisoformat(str(ctx["as_of"])) if ctx.get("as_of") else date.today()
    ctx.setdefault("expect_type2", True)
    ctx.setdefault("categories_needed", ["Security"])
    ctx.setdefault("subservice_reports_on_file", [])
    ctx.setdefault("cuec_owners", {})
    ctx.setdefault("bridge_letter_on_file", False)
    return ctx


def propose(ex: dict, ctx: dict, policy: dict | None = None) -> list[Finding]:
    """Apply the reliance rules. Thresholds come from policy.yaml (assurance section)."""
    a = (policy or {}).get("assurance", {"bridge_letter_after_months": 3, "stale_after_months": 15})
    today = ctx["as_of"]
    tag = _slug(Path(ex.get("source_file") or "report").stem)
    h = report_hash(ex)
    found: list[Finding] = []
    n = Counter()

    used: set[str] = set()

    def add(rule: str, detail: str, page: int | None, key: str | None = None):
        # The id names what the finding is about (a stable key, not a position), and the
        # hash ties it to this exact extraction. Keys must be unique within the report: if
        # two names reduce to the same slug, the second gets a numeric suffix.
        n[rule] += 1
        base = fid = f"{tag}:{rule}:{key or n[rule]}"
        i = 2
        while fid in used:                 # "~" can never come out of _slug, so suffixed
            fid = f"{base}~{i}"            # ids cannot clash with a natural key
            i += 1
        used.add(fid)
        found.append(Finding(fid, rule, detail, page, h))

    rt = ex.get("report_type", {})
    if rt.get("value") == "SOC2_TYPE1" and ctx["expect_type2"]:
        add("TYPE1_WHERE_TYPE2", "report is a Type 1", rt.get("page"))

    p = ex.get("period", {})
    months = period_months(ex)
    if rt.get("value") == "SOC2_TYPE2" and months is not None and months < 6:
        add("PERIOD_SHORT", f"{p['start']} to {p['end']} is {months} months", p.get("page"))
    if p.get("end"):
        age = months_between(date.fromisoformat(p["end"]), today)
        if age > a["stale_after_months"]:
            add("REPORT_STALE", f"period ended {p['end']} ({age} months ago)", p.get("page"))
        elif age > a["bridge_letter_after_months"] and not ctx["bridge_letter_on_file"]:
            add("BRIDGE_LETTER_NEEDED", f"period ended {p['end']} ({age} months ago)", p.get("page"))

    op = ex.get("opinion", {})
    if op.get("value") == "QUALIFIED":
        add("OPINION_QUALIFIED", op.get("basis", ""), op.get("page"))
    elif op.get("value") == "ADVERSE_OR_DISCLAIMER":
        add("OPINION_ADVERSE", op.get("basis", ""), op.get("page"))
    elif op.get("value") != "UNQUALIFIED":
        add("OPINION_UNKNOWN", op.get("basis", ""), op.get("page"))

    cats = ex.get("categories", {})
    missing = [c for c in ctx["categories_needed"] if c not in cats.get("in_scope", [])]
    if missing:
        add("CATEGORY_NOT_IN_SCOPE", f"need {missing}; in scope {cats.get('in_scope')}", cats.get("page"))
    if cats.get("also_mentioned"):
        add("CATEGORY_WORDING_MIXED", f"in scope {cats.get('in_scope')}; also named {cats['also_mentioned']}", cats.get("page"))

    sub = ex.get("subservice_orgs", {})
    held = {s.lower() for s in ctx["subservice_reports_on_file"]}
    for org in sub.get("values", []):
        if not any(h in org.lower() for h in held):
            add("CARVE_OUT_NO_ASSURANCE", f"{org} ({sub.get('method', 'UNKNOWN')})", sub.get("page"), key=_slug(org))

    cu = ex.get("cuecs", {})
    if cu.get("count", 0) == 0:
        add("NO_CUEC_SECTION", "no 'user entity is responsible' statements found", cu.get("page"))
    else:
        unowned = cu["count"] - len(ctx["cuec_owners"])
        if unowned > 0:
            add("CUEC_UNOWNED", f"{cu['count']} CUECs, {len(ctx['cuec_owners'])} owned", cu.get("page"))

    tr = ex.get("test_results", {})
    if tr.get("exceptions_noted", 0) > 0:
        add("EXCEPTIONS_PRESENT", f"{tr['exceptions_noted']} results say exceptions noted ({tr.get('no_exceptions_noted')} clean)", tr.get("from_page"))
    if len({f.id for f in found}) != len(found):
        raise ValueError("finding ids must be unique within a report")
    return found


def to_markdown(ex: dict, findings: list[Finding], ctx: dict) -> str:
    L = [f"# SOC 2 reliance review: {ex.get('source_file')} (as of {ctx['as_of']})", "",
         "**Nothing below is a finding until a reviewer approves it.** Status shows PROPOSED / APPROVED / REJECTED.", "",
         f"Extraction hash: `{report_hash(ex)}` (decisions are bound to it)", "",
         "## What the extractor read", "", "| Field | Value | Page |", "|---|---|---|"]
    rt, p, op, c, s, cu, tr, au = (ex.get(k, {}) for k in ("report_type", "period", "opinion", "categories", "subservice_orgs", "cuecs", "test_results", "auditor"))
    L += [f"| Report type | {rt.get('value')} | {rt.get('page')} |",
          f"| Period | {p.get('start')} to {p.get('end')} | {p.get('page')} |",
          f"| Report date | {ex.get('report_date', {}).get('value')} | {ex.get('report_date', {}).get('page')} |",
          f"| Opinion | {op.get('value')} | {op.get('page')} |",
          f"| Categories in scope | {', '.join(c.get('in_scope', [])) or '-'} | {c.get('page')} |",
          f"| Subservice orgs ({s.get('method')}) | {', '.join(s.get('values', [])) or '-'} | {s.get('page')} |",
          f"| CUECs | {cu.get('count')} | {cu.get('page')} |",
          f"| CSOC criteria | {', '.join(ex.get('csoc_criteria', {}).get('values', [])) or '-'} | {ex.get('csoc_criteria', {}).get('page')} |",
          f"| Auditor | {au.get('signer')} / {au.get('firm')} | {au.get('page')} |",
          f"| Test results | {tr.get('no_exceptions_noted')} clean, {tr.get('exceptions_noted')} with exceptions | {tr.get('from_page')}+ |",
          "", "## Proposed findings", "", "| ID | Rule | Detail | Page | Source | Status |", "|---|---|---|---|---|---|"]
    for f in findings:
        L.append(f"| {f.id} | {f.rule} | {f.detail} | {f.page} | {f.source} | {f.status} |")
    L += ["", "Sources: SOURCES.md. Context (services used, owners, reports held) is the reviewer's input, not a fact about the vendor."]
    return "\n".join(L) + "\n"
