"""Turn findings into a plain Markdown report: KRI summary first, then every finding."""
from __future__ import annotations

from collections import Counter

from .register import RULES, TIERS, Finding


def kri_summary(register: list[dict], findings: list[Finding]) -> list[tuple[str, int, int, int]]:
    """Per tier: vendors, vendors with at least one finding, total findings."""
    tier_of = {r["vendor"]: r["criticality"].strip().upper() for r in register}
    flagged = {t: set() for t in TIERS}
    count = Counter()
    for f in findings:
        tier = tier_of.get(f.vendor)
        if tier:
            flagged[tier].add(f.vendor)
            count[tier] += 1
    totals = Counter(tier_of.values())
    return [(t, totals[t], len(flagged[t]), count[t]) for t in TIERS]


def to_markdown(register: list[dict], findings: list[Finding], policy: dict) -> str:
    lines = [f"# Vendor register review, as of {policy['as_of']}", ""]

    lines += ["## Exposure by tier", "", "| Tier | Vendors | Vendors with findings | Findings |", "|---|---|---|---|"]
    for tier, n, flagged, total in kri_summary(register, findings):
        lines.append(f"| {tier} | {n} | {flagged} | {total} |")

    missing = [f for f in findings if f.rule == "NOT_IN_REGISTER"]
    lines += ["", f"**Paid but not in the register:** {len(missing)}", ""]

    lines += ["## Findings by rule", "", "| Rule | Meaning | Count | Source |", "|---|---|---|---|"]
    by_rule = Counter(f.rule for f in findings)
    for rule, (meaning, source) in RULES.items():
        if by_rule[rule]:
            lines.append(f"| {rule} | {meaning} | {by_rule[rule]} | {source} |")

    lines += ["", "## All findings", "", "| Vendor | Rule | Detail |", "|---|---|---|"]
    for f in sorted(findings, key=lambda f: (f.rule, f.vendor)):
        lines.append(f"| {f.vendor} | {f.rule} | {f.detail} |")
    lines += ["", "Sources: see SOURCES.md. Review intervals marked ORG POLICY in policy.yaml."]
    return "\n".join(lines) + "\n"
