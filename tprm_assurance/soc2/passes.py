"""3-pass review: the same report text through three independent passes, then a person.

  Pass 1  pattern code   reads every field (extract.py). Free, instant, brittle on new layouts.
  Pass 2  Jev            answers fixed-choice questions on the cited page: report type, opinion,
                         which trust services categories are in scope, and whether each provider
                         named by another pass appears there. It cannot produce names, dates or
                         counts, so those fields show "not applicable" for this pass.
  Pass 3  Claude         reads every field again, each with the page it came from.

Every field the passes disagree on goes to a person, who takes one pass's value or types the
value from the page. Resolutions are appended to a log bound to a hash of all the readings; the
merge is refused while a disagreement that decides a reliance rule is open (gate in policy.yaml).
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .conflicts import GateBlocked, NOT_COMPARED_FIELDS, NOT_COMPARED_KEYS, SEVERITIES, _norm, gate_severity, severity
from .extract import CATEGORIES
from .jev_check import JEV_MODEL, TEMPLATES, _loose, _to_sdk, thresholds
from .reliance import report_hash

PASSES = ["rules", "jev", "claude-text"]
PASS_LABELS = {"rules": "Pass 1: pattern code", "jev": "Pass 2: Jev", "claude-text": "Pass 3: Claude"}
JEV_FIELDS = [("report_type", "value"), ("opinion", "value"), ("categories", "in_scope"), ("subservice_orgs", "values")]
SCALAR_CHOICES = {("report_type", "value"): ["SOC2_TYPE2", "SOC2_TYPE1"],
                  ("opinion", "value"): ["UNQUALIFIED", "QUALIFIED", "ADVERSE_OR_DISCLAIMER"]}


# ---- Pass 2: Jev ------------------------------------------------------------------------

def _cited_page(readings: dict, fld: str, n_pages: int) -> int | None:
    """The page Claude cited, else the page the pattern code cited."""
    for name in ("claude-text", "rules"):
        p = ((readings.get(name) or {}).get(fld) or {}).get("page")
        if isinstance(p, int) and 1 <= p <= n_pages:
            return p
    return None


def jev_pass(readings: dict, pages: list[str], client, policy: dict | None) -> dict:
    """Run Pass 2. Returns an extraction holding only the fields Jev can answer, plus `_jev`
    with every question, probability and status, so the result can be audited and re-run."""
    yes, no = thresholds(policy)
    base = readings.get("rules") or readings.get("claude-text") or {}
    out: dict = {"source_file": base.get("source_file"), "extractor": "jev", "_jev": {"model": JEV_MODEL, "fields": {}}}
    for fld, key in JEV_FIELDS:
        fid = f"{fld}.{key}"
        page = _cited_page(readings, fld, len(pages))
        if page is None:
            out["_jev"]["fields"][fid] = {"status": "no_page", "note": "no pass cited a page for this field"}
            continue
        if (fld, key) in SCALAR_CHOICES:
            cands = SCALAR_CHOICES[(fld, key)]
        elif fld == "categories":
            cands = list(CATEGORIES)
        else:                                   # providers: Jev checks names the other passes found
            seen, cands = set(), []
            for name in ("rules", "claude-text"):
                for v in ((readings.get(name) or {}).get(fld) or {}).get(key) or []:
                    if _loose(v) not in seen:
                        seen.add(_loose(v)); cands.append(v)
            if not cands:
                out["_jev"]["fields"][fid] = {"status": "no_candidates", "note": "no pass named any provider"}
                continue
        ref = f"`page_{page}`"
        questions = {f"q{i}": TEMPLATES[(fld, key)](c, ref) for i, c in enumerate(cands)}
        request = {"state": {f"page_{page}": pages[page - 1]}, "questions": questions}
        try:
            resp = client.system_one(state=request["state"], questions=_to_sdk(questions), model=JEV_MODEL)
            probs = {c: float(resp.nouls[f"q{i}"].noul) for i, c in enumerate(cands)}
        except Exception as e:                 # an error is an error, never a "no"
            out["_jev"]["fields"][fid] = {"status": "error", "note": f"{type(e).__name__}: {e}", "page": page}
            continue
        supported = [c for c in cands if probs[c] >= yes]
        unsure = [c for c in cands if no < probs[c] < yes]
        rec = {"page": page, "probs": probs}
        if unsure:
            rec.update(status="unsure", note="Jev was unsure about: " + ", ".join(unsure))
        elif (fld, key) in SCALAR_CHOICES:
            if len(supported) == 1:
                out[fld] = {key: supported[0], "page": page}; rec["status"] = "answered"
            else:
                rec.update(status="unsure", note=f"{len(supported)} options supported; expected exactly one")
        else:
            out[fld] = {key: supported, "page": page}; rec["status"] = "answered"
        out["_jev"]["fields"][fid] = rec
    return out


# ---- Comparing the passes -----------------------------------------------------------------

MISSING = object()


@dataclass
class Row:
    id: str
    field: str
    key: str
    values: dict                      # pass name -> value (MISSING when that pass has no answer)
    severity: str
    agree: bool
    status: str = "AGREE"             # AGREE | OPEN | RESOLVED
    resolution: dict | None = None
    note: str = ""                    # Jev's status note, if any


def set_hash(readings: dict) -> str:
    joined = "|".join(f"{n}:{report_hash(readings[n])}" for n in sorted(readings))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def compare(readings: dict) -> list[Row]:
    files = {(r.get("source_file") or "") for r in readings.values()}
    if len(files) > 1:
        raise ValueError(f"the passes read different files: {sorted(files)}")
    keys = []
    for r in readings.values():
        for fld, sub in r.items():
            if fld in NOT_COMPARED_FIELDS or fld.startswith("_") or not isinstance(sub, dict):
                continue
            for key in sub:
                if key in ("page", "from_page", "firm_page") or (fld, key) in NOT_COMPARED_KEYS or (fld, key) in keys:
                    continue
                keys.append((fld, key))
    jev_notes = ((readings.get("jev") or {}).get("_jev") or {}).get("fields", {})
    rows = []
    for fld, key in keys:
        vals = {n: (readings[n].get(fld) or {}).get(key, MISSING) if isinstance(readings[n].get(fld), dict) else MISSING
                for n in PASSES if n in readings}
        present = [_norm(v) for v in vals.values() if v is not MISSING]
        agree = all(p == present[0] for p in present)
        fid = f"{fld}.{key}"
        rows.append(Row(fid, fld, key, vals, severity(fld, key), agree, "AGREE" if agree else "OPEN",
                        note=(jev_notes.get(fid) or {}).get("note", "")))
    return rows


def resolve(log_path: Path, readings: dict, row_id: str, choice: str, reviewer: str, value=None, note: str = "") -> dict:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    rows = {r.id: r for r in compare(readings) if not r.agree}
    if row_id not in rows:
        raise ValueError(f"{row_id!r} is not a disagreement between these passes")
    row = rows[row_id]
    if choice == "manual":
        if value is None:
            raise ValueError("a typed value is required")
        chosen = value
    elif choice in row.values and row.values[choice] is not MISSING:
        chosen = row.values[choice]
    else:
        raise ValueError(f"choice must be one of {[n for n, v in row.values.items() if v is not MISSING] + ['manual']}")
    entry = {"row_id": row_id, "set_hash": set_hash(readings), "choice": choice, "value": chosen,
             "reviewer": reviewer.strip(), "note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def apply_resolutions(rows: list[Row], readings: dict, log_path: Path) -> list[Row]:
    h, latest = set_hash(readings), {}
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("set_hash") == h:
                    latest[d["row_id"]] = d
    for r in rows:
        if not r.agree and r.id in latest:
            r.status, r.resolution = "RESOLVED", latest[r.id]
    return rows


def blocking(rows: list[Row], gate: str) -> list[Row]:
    floor = SEVERITIES.index(gate)
    return [r for r in rows if r.status == "OPEN" and SEVERITIES.index(r.severity) >= floor]


def merge(readings: dict, log_path: Path, policy: dict | None) -> dict:
    gate = gate_severity(policy)
    rows = apply_resolutions(compare(readings), readings, log_path)
    blocked = blocking(rows, gate)
    if blocked:
        raise GateBlocked(blocked, gate)
    base_name = "rules" if "rules" in readings else "claude-text"
    out = copy.deepcopy(readings[base_name])
    for r in rows:
        if r.status == "RESOLVED":
            out.setdefault(r.field, {})[r.key] = copy.deepcopy(r.resolution["value"])
        elif r.agree and r.values.get(base_name, MISSING) is MISSING:
            v = next(v for v in r.values.values() if v is not MISSING)
            out.setdefault(r.field, {})[r.key] = copy.deepcopy(v)
    out["extractor"] = "merged:3-pass"
    out["_merge"] = {"passes": sorted(readings), "set_hash": set_hash(readings), "gate": gate,
                     "resolved": [r.id for r in rows if r.status == "RESOLVED"],
                     "open": [r.id for r in rows if r.status == "OPEN"]}
    return out
