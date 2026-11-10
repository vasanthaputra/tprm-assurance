"""Conflict queue: when two extractions of the same report disagree, a person decides.

Neither extractor is the record; the PDF is. So when the rules extractor and an AI
extraction (copy-paste or API) read a field differently, the tool does not pick one. It
lists the disagreement as a conflict. A reviewer resolves each one (take A, take B, or type
the right value), and every resolution is appended to a log, bound to a hash of the exact
pair of extractions it was made on.

`merge` builds one extraction from the pair for `soc2 review`. It refuses while any open
conflict is at or above the gate severity in policy.yaml. The gate has two settings and no
"off": LOW (block on every open conflict) or HIGH (block only where the field decides
whether a reliance rule fires). Below the gate, the field keeps A's value and the conflict
stays listed as open in the merged file and in the review.

Pattern borrowed from a procurement agent's source-of-record rule and compose-time
severity gate (wiki: wilsonhj-repos-review-2026-11).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .reliance import report_hash

# Keys that propose() reads to decide whether a finding fires. A wrong value here changes
# the reliance outcome, so a disagreement is HIGH. Every other key is LOW: it is a page
# citation or appears only in a finding's detail text. tests/test_conflicts.py checks that
# changing any LOW key leaves the set of fired rules unchanged.
HIGH_KEYS = {
    ("report_type", "value"),
    ("period", "start"),
    ("period", "end"),
    ("opinion", "value"),
    ("categories", "in_scope"),
    ("categories", "also_mentioned"),
    ("subservice_orgs", "values"),
    ("cuecs", "count"),
    ("test_results", "exceptions_noted"),
}
NOT_COMPARED_FIELDS = {"source_file", "extractor", "pages", "_merge"}
NOT_COMPARED_KEYS = {("opinion", "basis")}   # the extractor's own explanation, not a fact
SEVERITIES = ("LOW", "HIGH")                  # ordered; there is no setting that disables the gate
CHOICES = ("a", "b", "manual")


def severity(field: str, key: str) -> str:
    return "HIGH" if (field, key) in HIGH_KEYS else "LOW"


def _norm(v):
    """Compare without being fooled by capitalisation, spacing or list order."""
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip().casefold()
    if isinstance(v, list):
        return sorted((_norm(x) for x in v), key=repr)
    return v


def pair_hash(a: dict, b: dict) -> str:
    return hashlib.sha256(f"{report_hash(a)}:{report_hash(b)}".encode("utf-8")).hexdigest()[:16]


@dataclass
class Conflict:
    id: str            # "<field>.<key>", e.g. "cuecs.count"
    field: str
    key: str
    a: object
    b: object
    severity: str
    pair_hash: str
    status: str = "OPEN"          # OPEN -> RESOLVED (by a person)
    resolution: dict | None = None


def find_conflicts(a: dict, b: dict) -> list[Conflict]:
    """Every key both extractions report, where they disagree. A key only one extractor
    reports (its schema lacks the other) is not compared. One saying 'not found' (null)
    while the other found a value IS a conflict."""
    if (a.get("source_file") or "") != (b.get("source_file") or ""):
        raise ValueError(f"extractions are of different files: {a.get('source_file')!r} vs {b.get('source_file')!r}")
    h = pair_hash(a, b)
    out: list[Conflict] = []
    for field in sorted(set(a) & set(b) - NOT_COMPARED_FIELDS):
        fa, fb = a[field], b[field]
        if not (isinstance(fa, dict) and isinstance(fb, dict)):
            continue
        for key in sorted(set(fa) & set(fb)):
            if (field, key) in NOT_COMPARED_KEYS:
                continue
            if _norm(fa[key]) != _norm(fb[key]):
                out.append(Conflict(f"{field}.{key}", field, key, fa[key], fb[key], severity(field, key), h))
    return out


def resolve(log_path: Path, a: dict, b: dict, conflict_id: str, choice: str, reviewer: str,
            value=None, note: str = "") -> dict:
    choice = choice.lower()
    if choice not in CHOICES:
        raise ValueError(f"choice must be one of {CHOICES}")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    current = {c.id: c for c in find_conflicts(a, b)}
    if conflict_id not in current:
        raise ValueError(f"{conflict_id!r} is not an open disagreement between these two extractions; "
                         f"current ones: {sorted(current) or 'none'}")
    if choice == "manual" and value is None:
        raise ValueError("a manual resolution needs the value read from the report")
    c = current[conflict_id]
    chosen = {"a": c.a, "b": c.b}.get(choice, value)
    entry = {"conflict_id": conflict_id, "pair_hash": c.pair_hash, "choice": choice, "value": chosen,
             "reviewer": reviewer.strip(), "note": note,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_resolutions(log_path: Path) -> dict[tuple[str, str], dict]:
    """Latest resolution per (pair_hash, conflict_id)."""
    latest: dict[tuple[str, str], dict] = {}
    if not log_path.exists():
        return latest
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            if "pair_hash" in d and "conflict_id" in d:
                latest[(d["pair_hash"], d["conflict_id"])] = d
    return latest


def apply_resolutions(conflicts: list[Conflict], log_path: Path) -> list[Conflict]:
    latest = load_resolutions(log_path)
    for c in conflicts:
        r = latest.get((c.pair_hash, c.id))
        if r:
            c.status, c.resolution = "RESOLVED", r
    return conflicts


def gate_severity(policy: dict | None) -> str:
    cfg = (policy or {}).get("conflicts") or {}
    g = cfg.get("gate_severity", "HIGH")
    if g not in SEVERITIES:
        raise ValueError(f"conflicts.gate_severity must be one of {SEVERITIES} (the gate cannot be disabled); got {g!r}")
    return g


def blocking(conflicts: list[Conflict], gate: str) -> list[Conflict]:
    floor = SEVERITIES.index(gate)
    return [c for c in conflicts if c.status == "OPEN" and SEVERITIES.index(c.severity) >= floor]


class GateBlocked(Exception):
    def __init__(self, conflicts: list[Conflict], gate: str):
        self.conflicts, self.gate = conflicts, gate
        super().__init__(f"{len(conflicts)} open conflict(s) at or above {gate}: {', '.join(c.id for c in conflicts)}")


def merge(a: dict, b: dict, log_path: Path, policy: dict | None) -> dict:
    gate = gate_severity(policy)
    conflicts = apply_resolutions(find_conflicts(a, b), log_path)
    blocked = blocking(conflicts, gate)
    if blocked:
        raise GateBlocked(blocked, gate)
    out = copy.deepcopy(a)
    for c in conflicts:
        if c.status == "RESOLVED":
            out[c.field][c.key] = copy.deepcopy(c.resolution["value"])
    out["extractor"] = f"merged:{a.get('extractor')}+{b.get('extractor')}"
    out["_merge"] = {"from": [a.get("extractor"), b.get("extractor")], "pair_hash": pair_hash(a, b), "gate": gate,
                     "resolved": [c.id for c in conflicts if c.status == "RESOLVED"],
                     "open": [c.id for c in conflicts if c.status == "OPEN"]}
    return out


def to_markdown(a: dict, b: dict, conflicts: list[Conflict], gate: str, suggestions: dict | None = None) -> str:
    """`suggestions` (from jev_check.load_suggestions) adds a column; it never resolves anything."""
    blocked = blocking(conflicts, gate)
    state = (f"**BLOCKED**: {len(blocked)} open conflict(s) at or above {gate} must be resolved before merge."
             if blocked else f"Merge allowed at gate {gate}.")
    L = [f"# Extractor conflicts: {a.get('source_file')}", "",
         f"A = `{a.get('extractor')}` (hash `{report_hash(a)}`), B = `{b.get('extractor')}` (hash `{report_hash(b)}`), "
         f"pair `{pair_hash(a, b)}`", "",
         "**Neither extractor is the record; the report is.** Check the page and resolve each row "
         "(`soc2 resolve ... a|b|manual`).", "", state, "",
         "| Conflict | Severity | A | B | Status | Resolution |" + (" Jev suggests |" if suggestions is not None else ""),
         "|---|---|---|---|---|---|" + ("---|" if suggestions is not None else "")]
    if suggestions is not None:
        from .jev_check import describe
    for c in conflicts:
        r = c.resolution
        res = f"{r['choice']} = {r['value']!r} by {r['reviewer']}" if r else "-"
        extra = f" {describe(suggestions.get(c.id))} |" if suggestions is not None else ""
        L.append(f"| {c.id} | {c.severity} | {c.a!r} | {c.b!r} | {c.status} | {res} |{extra}")
    if not conflicts:
        L.append("| - | - | - | - | - | the two extractions agree on every key both report |")
    if suggestions is not None:
        L += ["", "Jev suggestions are advice from a decision model reading the cited page; a person still resolves each row."]
    L += ["", "HIGH = the field decides whether a reliance rule fires. LOW = page citation or detail text only."]
    return "\n".join(L) + "\n"
