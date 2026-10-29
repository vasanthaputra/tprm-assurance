"""Vendor register check: module 1 of reliance.

Reads a vendor register and an accounts-payable vendor list, then applies the rules in
policy.yaml. Each finding names the rule and the source it comes from (see SOURCES.md).
No AI is used here; every result can be traced to a rule.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

TIERS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# rule id -> (plain-English meaning, source id from SOURCES.md)
RULES = {
    "NOT_IN_REGISTER":     ("Paid through accounts payable but missing from the vendor register", "S1"),
    "NEVER_ASSESSED":      ("In the register but never assessed", "S1, S4"),
    "REVIEW_OVERDUE":      ("Reassessment is past due for this tier", "S1, S4"),
    "NO_DPA":              ("Processes personal data with no signed data processing agreement", "S2, S4"),
    "NO_ASSURANCE_REPORT": ("Critical/high vendor with no SOC 2 or ISO report on file", "S3"),
    "TYPE1_WHERE_TYPE2":   ("Only a SOC 2 Type 1 (point in time) where a Type 2 is expected", "S3"),
    "REPORT_STALE":        ("Report period ended too long ago to rely on", "S3"),
    "BRIDGE_LETTER_NEEDED": ("Report period ended over 3 months ago and no bridge letter is on file", "S3"),
}


@dataclass
class Finding:
    vendor: str
    rule: str
    detail: str

    @property
    def meaning(self) -> str:
        return RULES[self.rule][0]

    @property
    def source(self) -> str:
        return RULES[self.rule][1]


def load_policy(path: Path) -> dict:
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    if policy.get("as_of"):
        policy["as_of"] = date.fromisoformat(str(policy["as_of"]))
    else:
        policy["as_of"] = date.today()
    return policy


def read_csv(path: Path) -> list[dict]:
    # Lines starting with '#' are comments (used to label sample data as synthetic).
    with path.open(encoding="utf-8", newline="") as f:
        lines = [line for line in f if not line.startswith("#")]
    return list(csv.DictReader(lines))


def months_between(earlier: date, later: date) -> int:
    """Whole calendar months from `earlier` to `later` (counts only completed months)."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def _date(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def _yes(value: str) -> bool:
    return (value or "").strip().lower() in ("yes", "y", "true", "1")


def check_vendor(row: dict, policy: dict) -> list[Finding]:
    name = row["vendor"]
    tier = row["criticality"].strip().upper()
    if tier not in TIERS:
        raise ValueError(f"{name}: unknown criticality '{row['criticality']}' (expected one of {TIERS})")
    today = policy["as_of"]
    found: list[Finding] = []

    # Assessment cadence (S1 periodic reassessment; interval is ORG POLICY).
    last = _date(row["last_assessed"])
    if last is None:
        found.append(Finding(name, "NEVER_ASSESSED", "no assessment date recorded"))
    else:
        limit = policy["review_cadence_months"][tier]
        age = months_between(last, today)
        if age > limit:
            found.append(Finding(name, "REVIEW_OVERDUE",
                                 f"{tier} vendors every {limit} months; last assessed {last} ({age} months ago)"))

    # Personal data needs a contract binding the processor (S2).
    if _yes(row["personal_data"]) and not _yes(row["dpa_signed"]):
        found.append(Finding(name, "NO_DPA", "personal data = yes, DPA signed = no"))

    # Assurance evidence (S3).
    a = policy["assurance"]
    report = (row["report_type"] or "").strip().upper()
    period_end = _date(row["report_period_end"])
    needs_type2 = tier in a["type2_required_for"]

    if report in ("", "NONE"):
        if needs_type2:
            found.append(Finding(name, "NO_ASSURANCE_REPORT", f"{tier} vendor with no report on file"))
        return found

    if report == "SOC2_TYPE1" and needs_type2:
        found.append(Finding(name, "TYPE1_WHERE_TYPE2", f"{tier} vendor relies on a Type 1 report"))

    if period_end is not None:
        age = months_between(period_end, today)
        if age > a["stale_after_months"]:
            found.append(Finding(name, "REPORT_STALE",
                                 f"period ended {period_end} ({age} months ago; limit {a['stale_after_months']})"))
        elif age > a["bridge_letter_after_months"] and not _yes(row["bridge_letter"]):
            found.append(Finding(name, "BRIDGE_LETTER_NEEDED",
                                 f"period ended {period_end} ({age} months ago), no bridge letter"))
    return found


def check_completeness(register: list[dict], ap_vendors: list[dict]) -> list[Finding]:
    """S1: a complete inventory. Anyone being paid should be in the register."""
    known = {r["vendor"].strip().lower() for r in register}
    return [Finding(p["vendor"], "NOT_IN_REGISTER", f"paid {p['last_payment']}, not in register")
            for p in ap_vendors if p["vendor"].strip().lower() not in known]


def run(register_csv: Path, ap_csv: Path, policy_path: Path) -> tuple[list[dict], list[Finding], dict]:
    policy = load_policy(policy_path)
    register = read_csv(register_csv)
    findings = check_completeness(register, read_csv(ap_csv))
    for row in register:
        findings.extend(check_vendor(row, policy))
    return register, findings, policy
