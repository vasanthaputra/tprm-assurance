"""Conflict queue checks: two extractions of the same report are compared field by field,
every disagreement waits for a person, and the merge gate cannot be switched off.

Extraction B below is SYNTHETIC: a copy of the verified rules fixture with planted
differences shaped like a copy-paste AI reply (missing keys the AI schema lacks, different
wording in the opinion basis, different capitalisation, one wrong count, one wrong page)."""
import json
from datetime import date
from pathlib import Path

import pytest

from tprm_assurance.soc2.conflicts import (
    HIGH_KEYS,
    GateBlocked,
    apply_resolutions,
    blocking,
    find_conflicts,
    gate_severity,
    merge,
    resolve,
    severity,
    to_markdown,
)
from tprm_assurance.soc2.reliance import load_context, propose, report_hash

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "data" / "fixtures"
HIGH_GATE = {"conflicts": {"gate_severity": "HIGH"}}
LOW_GATE = {"conflicts": {"gate_severity": "LOW"}}


@pytest.fixture
def a():
    return json.loads((FIX / "s5_report_a_rules_extraction.json").read_text(encoding="utf-8"))


@pytest.fixture
def b(a):
    ex = json.loads(json.dumps(a))
    ex["extractor"] = "manual"
    for k in ("next_report_due", "pages"):
        ex.pop(k, None)
    ex["auditor"].pop("firm_page", None)
    ex["opinion"]["basis"] = "The auditor's opinion has no qualification."       # wording only
    ex["subservice_orgs"]["values"][0] = ex["subservice_orgs"]["values"][0].upper()  # case only
    ex["cuecs"]["count"] = 11                                                    # wrong: HIGH
    ex["report_date"]["page"] = 10                                               # wrong page: LOW
    ex["test_results"]["no_exceptions_noted"] += 3                               # not rule-driving: LOW
    return ex


def by_id(conflicts):
    return {c.id: c for c in conflicts}


def test_identical_extractions_have_no_conflicts(a):
    assert find_conflicts(a, json.loads(json.dumps(a))) == []


def test_planted_differences_become_conflicts_and_nothing_else(a, b):
    got = {c.id: c.severity for c in find_conflicts(a, b)}
    assert got == {"cuecs.count": "HIGH", "report_date.page": "LOW",
                   "test_results.no_exceptions_noted": "LOW"}


def test_not_found_versus_found_is_a_conflict(a, b):
    a["period"]["end"] = None
    c = by_id(find_conflicts(a, b))["period.end"]
    assert c.severity == "HIGH" and c.a is None and c.b == "2025-06-30"


def test_different_files_are_refused(a, b):
    b["source_file"] = "another_vendor.pdf"
    with pytest.raises(ValueError):
        find_conflicts(a, b)


def test_gate_cannot_be_disabled():
    assert gate_severity({}) == "HIGH"                       # default
    assert gate_severity(LOW_GATE) == "LOW"
    for bad in ("NONE", "OFF", "", None, "CRITICAL"):
        with pytest.raises(ValueError):
            gate_severity({"conflicts": {"gate_severity": bad}})


def test_merge_blocks_on_open_high_conflict_only_at_high_gate(a, b, tmp_path):
    log = tmp_path / "conflicts.jsonl"
    with pytest.raises(GateBlocked) as e:
        merge(a, b, log, HIGH_GATE)
    assert [c.id for c in e.value.conflicts] == ["cuecs.count"]

    resolve(log, a, b, "cuecs.count", "a", "reviewer-a", note="12 bullets on page 30")
    merged = merge(a, b, log, HIGH_GATE)                       # LOW ones still open: allowed
    assert merged["cuecs"]["count"] == 12
    assert sorted(merged["_merge"]["open"]) == ["report_date.page", "test_results.no_exceptions_noted"]

    with pytest.raises(GateBlocked) as e:                       # LOW gate blocks on every open one
        merge(a, b, log, LOW_GATE)
    assert sorted(c.id for c in e.value.conflicts) == ["report_date.page", "test_results.no_exceptions_noted"]


def test_resolutions_are_append_only_latest_wins(a, b, tmp_path):
    log = tmp_path / "conflicts.jsonl"
    resolve(log, a, b, "cuecs.count", "b", "reviewer-a")
    resolve(log, a, b, "cuecs.count", "a", "reviewer-b", note="recounted")
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
    c = by_id(apply_resolutions(find_conflicts(a, b), log))["cuecs.count"]
    assert c.status == "RESOLVED" and c.resolution["choice"] == "a" and c.resolution["reviewer"] == "reviewer-b"


def test_choice_b_and_manual_value(a, b, tmp_path):
    log = tmp_path / "conflicts.jsonl"
    resolve(log, a, b, "report_date.page", "b", "reviewer-a")
    resolve(log, a, b, "cuecs.count", "manual", "reviewer-a", value=13, note="both readers missed one")
    merged = merge(a, b, log, HIGH_GATE)
    assert merged["report_date"]["page"] == 10
    assert merged["cuecs"]["count"] == 13


def test_bad_resolutions_are_refused(a, b, tmp_path):
    log = tmp_path / "conflicts.jsonl"
    with pytest.raises(ValueError):
        resolve(log, a, b, "cuecs.count", "manual", "reviewer-a")          # no value
    with pytest.raises(ValueError):
        resolve(log, a, b, "opinion.value", "a", "reviewer-a")             # not a conflict
    with pytest.raises(ValueError):
        resolve(log, a, b, "cuecs.count", "maybe", "reviewer-a")
    with pytest.raises(ValueError):
        resolve(log, a, b, "cuecs.count", "a", "  ")
    assert not log.exists()


def test_resolution_does_not_leak_to_a_different_pair(a, b, tmp_path):
    """Same conflict id, but B's content changed: the old resolution must not apply."""
    log = tmp_path / "conflicts.jsonl"
    resolve(log, a, b, "cuecs.count", "a", "reviewer-a")
    b2 = json.loads(json.dumps(b))
    b2["cuecs"]["count"] = 10
    c = by_id(apply_resolutions(find_conflicts(a, b2), log))["cuecs.count"]
    assert c.status == "OPEN"
    with pytest.raises(GateBlocked):
        merge(a, b2, log, HIGH_GATE)


def test_merged_extraction_is_a_new_report_for_the_review_gate(a, b, tmp_path):
    log = tmp_path / "conflicts.jsonl"
    resolve(log, a, b, "cuecs.count", "a", "reviewer-a")
    merged = merge(a, b, log, HIGH_GATE)
    assert merged["extractor"] == "merged:rules+manual"
    assert report_hash(merged) != report_hash(a)       # decisions on A do not carry over
    ctx = load_context(ROOT / "data" / "sample" / "soc2_context.yaml")
    assert len(propose(merged, ctx)) == len(propose(a, ctx))


def _mutate(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return 0 if v else 1          # to zero, so count-based rules (CUEC section) notice
    if isinstance(v, str):
        return v + "x"
    if isinstance(v, list):
        return []
    return 1


def test_low_keys_do_not_drive_any_reliance_rule(a):
    """Guard on the severity table: changing a LOW key must not change which rules fire."""
    ctx = load_context(ROOT / "data" / "sample" / "soc2_context.yaml")
    ctx["as_of"] = date(2026, 10, 29)
    baseline = sorted(f.rule for f in propose(a, ctx))
    for field, val in a.items():
        if not isinstance(val, dict):
            continue
        for key in val:
            if severity(field, key) == "LOW":
                ex = json.loads(json.dumps(a))
                ex[field][key] = _mutate(ex[field][key])
                assert sorted(f.rule for f in propose(ex, ctx)) == baseline, f"{field}.{key} drives a rule"


def test_high_keys_exist_in_the_fixture(a):
    for field, key in HIGH_KEYS:
        assert key in a[field], f"{field}.{key} is not an extraction key"


def test_queue_markdown_shows_gate_state(a, b, tmp_path):
    log = tmp_path / "conflicts.jsonl"
    cs = apply_resolutions(find_conflicts(a, b), log)
    md = to_markdown(a, b, cs, "HIGH")
    assert "BLOCKED" in md and "cuecs.count" in md and "report_date.page" in md
    assert blocking(cs, "HIGH")[0].id == "cuecs.count"
    resolve(log, a, b, "cuecs.count", "a", "reviewer-a")
    md = to_markdown(a, b, apply_resolutions(find_conflicts(a, b), log), "HIGH")
    assert "BLOCKED" not in md and "OPEN" in md
