"""Human review gate. Decisions are appended to a JSON-lines log, never overwritten.

A proposed finding becomes APPROVED or REJECTED only through `decide`. Each entry records
who decided, when, why, and the hash of the extraction it was decided on. A decision is
applied only to findings from an extraction with the same hash, so a decision made on one
report can never leak onto another report that shares a file name or a finding id.
This is the audit trail a reviewer needs (S8, CA-5: findings and their disposition are
documented and updated).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .reliance import Finding

DECISIONS = ("APPROVED", "REJECTED")


def decide(log_path: Path, finding_id: str, decision: str, reviewer: str, report_hash: str, note: str = "") -> dict:
    decision = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}.get(decision.upper(), decision.upper())
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if not report_hash.strip():
        raise ValueError("report_hash is required (from the extraction being reviewed)")
    entry = {"finding_id": finding_id, "report_hash": report_hash, "decision": decision,
             "reviewer": reviewer.strip(), "note": note,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_decisions(log_path: Path) -> dict[tuple[str, str], dict]:
    """Latest decision per (report_hash, finding_id)."""
    latest: dict[tuple[str, str], dict] = {}
    if not log_path.exists():
        return latest
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            if "report_hash" in d and "finding_id" in d:   # entries without a hash are ignored
                latest[(d["report_hash"], d["finding_id"])] = d
    return latest


def apply_decisions(findings: list[Finding], log_path: Path) -> list[Finding]:
    latest = load_decisions(log_path)
    for f in findings:
        d = latest.get((f.report_hash, f.id))
        if d:
            f.status = d["decision"]
    return findings
