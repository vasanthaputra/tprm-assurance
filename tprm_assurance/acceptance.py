"""Risk acceptance lifecycle: module 2 of tprm-assurance.

An accepted risk is a decision, and decisions need an owner, an approver with enough
authority, and an end date. This module checks open acceptances against policy.yaml and
reports how long they have been running (the aging KRI). Rules cite SOURCES.md.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .register import TIERS, load_policy, months_between, read_csv

RULES = {
    "NOT_APPROVED":            ("Open acceptance with no approver or approval date recorded", "S8 (RA-7)"),
    "APPROVER_BELOW_AUTHORITY": ("Approver's role is below the authority set for this risk rating", "S1, S8 (PM-28)"),
    "NO_OWNER":                ("No accountable owner recorded", "S1, S8 (CA-5)"),
    "NO_EXPIRY":               ("Acceptance has no end date; acceptances must be time-boxed", "S4, S8 (CA-5)"),
    "EXPIRED":                 ("End date has passed and the acceptance is still open", "S8 (CA-5)"),
    "DURATION_OVER_MAX":       ("Runs longer than the maximum allowed for this rating", "ORG POLICY"),
}


@dataclass
class Finding:
    acceptance_id: str
    vendor: str
    rule: str
    detail: str

    @property
    def meaning(self) -> str:
        return RULES[self.rule][0]

    @property
    def source(self) -> str:
        return RULES[self.rule][1]


def _date(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def role_rank(role: str, ladder: list[str]) -> int:
    role = (role or "").strip().upper()
    if role not in ladder:
        raise ValueError(f"unknown approver role '{role}' (expected one of {ladder})")
    return ladder.index(role)


def check_acceptance(row: dict, policy: dict) -> list[Finding]:
    if (row.get("status") or "OPEN").strip().upper() != "OPEN":
        return []  # closed or withdrawn acceptances are history, not exposure
    acc = policy["acceptance"]
    today = policy["as_of"]
    aid, vendor = row["id"], row["vendor"]
    rating = row["risk_rating"].strip().upper()
    if rating not in TIERS:
        raise ValueError(f"{aid}: unknown risk rating '{row['risk_rating']}' (expected one of {TIERS})")
    found: list[Finding] = []

    if not (row.get("owner") or "").strip():
        found.append(Finding(aid, vendor, "NO_OWNER", "owner is blank"))

    approver = (row.get("approver_role") or "").strip().upper()
    approved_on = _date(row.get("approved_on"))
    if not approver or approved_on is None:
        found.append(Finding(aid, vendor, "NOT_APPROVED", "approver or approval date missing"))
    else:
        required = acc["approver_by_rating"][rating]
        if role_rank(approver, acc["role_ladder"]) < role_rank(required, acc["role_ladder"]):
            found.append(Finding(aid, vendor, "APPROVER_BELOW_AUTHORITY",
                                 f"{rating} needs {required}; approved by {approver}"))

    expires_on = _date(row.get("expires_on"))
    if expires_on is None:
        found.append(Finding(aid, vendor, "NO_EXPIRY", "expires_on is blank"))
    else:
        if expires_on < today:
            found.append(Finding(aid, vendor, "EXPIRED", f"expired {expires_on}, still open"))
        if approved_on is not None:
            limit = acc["max_duration_months"][rating]
            run_for = months_between(approved_on, expires_on)
            if run_for > limit:
                found.append(Finding(aid, vendor, "DURATION_OVER_MAX",
                                     f"{approved_on} to {expires_on} is {run_for} months; {rating} max {limit}"))
    return found


def aging(rows: list[dict], policy: dict) -> dict[str, Counter]:
    """For open acceptances: count by rating in each age bucket (days since approval)."""
    edges = policy["acceptance"]["aging_buckets_days"]
    labels = [f"0-{edges[0]}"] + [f"{edges[i] + 1}-{edges[i + 1]}" for i in range(len(edges) - 1)] + [f">{edges[-1]}"]
    table: dict[str, Counter] = {t: Counter() for t in TIERS}
    for r in rows:
        if (r.get("status") or "OPEN").strip().upper() != "OPEN":
            continue
        approved_on = _date(r.get("approved_on"))
        if approved_on is None:
            continue
        days = (policy["as_of"] - approved_on).days
        label = next((labels[i] for i, edge in enumerate(edges) if days <= edge), labels[-1])
        table[r["risk_rating"].strip().upper()][label] += 1
    table["_labels"] = labels  # type: ignore[assignment]
    return table


def run_acceptances(csv_path: Path, policy_path: Path) -> tuple[list[dict], list[Finding], dict]:
    policy = load_policy(policy_path)
    rows = read_csv(csv_path)
    findings: list[Finding] = []
    for row in rows:
        findings.extend(check_acceptance(row, policy))
    return rows, findings, policy


def acceptances_to_markdown(rows: list[dict], findings: list[Finding], policy: dict) -> str:
    lines = [f"# Risk acceptance review, as of {policy['as_of']}", ""]
    table = aging(rows, policy)
    labels = table.pop("_labels")
    lines += ["## Open acceptances by age (days since approval)", "",
              "| Rating | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for tier in TIERS:
        lines.append(f"| {tier} | " + " | ".join(str(table[tier][l]) for l in labels) + " |")

    lines += ["", "## Findings by rule", "", "| Rule | Meaning | Count | Source |", "|---|---|---|---|"]
    by_rule = Counter(f.rule for f in findings)
    for rule, (meaning, source) in RULES.items():
        if by_rule[rule]:
            lines.append(f"| {rule} | {meaning} | {by_rule[rule]} | {source} |")

    lines += ["", "## All findings", "", "| ID | Vendor | Rule | Detail |", "|---|---|---|---|"]
    for f in sorted(findings, key=lambda f: (f.rule, f.acceptance_id)):
        lines.append(f"| {f.acceptance_id} | {f.vendor} | {f.rule} | {f.detail} |")
    lines += ["", "Sources: see SOURCES.md. Approver ladder and maximum durations are ORG POLICY in policy.yaml."]
    return "\n".join(lines) + "\n"
