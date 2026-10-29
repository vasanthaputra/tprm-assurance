"""Human review gate. Decisions are appended to a JSON-lines log, never overwritten.

A proposed finding becomes APPROVED or REJECTED only through `decide`. The log records
who decided, when, and why, which is the audit trail a reviewer needs (S8, CA-5: findings
and their disposition are documented and updated).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .reliance import Finding

DECISIONS = ("APPROVED", "REJECTED")


def decide(log_path: Path, finding_id: str, decision: str, reviewer: str, note: str = "") -> dict:
    decision = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}.get(decision.upper(), decision.upper())
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    entry = {"finding_id": finding_id, "decision": decision, "reviewer": reviewer.strip(),
             "note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_decisions(log_path: Path) -> dict[str, dict]:
    """Latest decision per finding id."""
    latest: dict[str, dict] = {}
    if not log_path.exists():
        return latest
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            latest[d["finding_id"]] = d
    return latest


def apply_decisions(findings: list[Finding], log_path: Path) -> list[Finding]:
    latest = load_decisions(log_path)
    for f in findings:
        if f.id in latest:
            f.status = latest[f.id]["decision"]
    return findings
