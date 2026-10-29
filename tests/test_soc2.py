"""Module 3 checks: the rules extractor matches the hand-verified ground truth on the one
public report; the reliance rules propose the expected findings; the human gate works."""
import json
from datetime import date
from pathlib import Path

import pytest

from tprm_assurance.register import load_policy
from tprm_assurance.soc2.extract import extract
from tprm_assurance.soc2.reliance import load_context, propose
from tprm_assurance.soc2.review import apply_decisions, decide, load_decisions

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "data" / "fixtures"


@pytest.fixture
def fixture():
    return json.loads((FIX / "s5_msg91_rules_extraction.json").read_text(encoding="utf-8"))


@pytest.fixture
def truth():
    return json.loads((FIX / "s5_msg91_ground_truth.json").read_text(encoding="utf-8"))


def test_rules_extraction_matches_ground_truth(fixture, truth):
    """Every ground-truth field (value and page) must be reproduced by the rules extractor."""
    misses = []
    for field, expected in truth.items():
        if field.startswith("_"):
            continue
        got = fixture.get(field, {})
        for key, val in expected.items():
            g = got.get(key)
            if isinstance(val, list):
                g, val = sorted(g or []), sorted(val)
            if g != val:
                misses.append(f"{field}.{key}: got {g!r}, expected {val!r}")
    assert not misses, "\n".join(misses)


def test_reliance_findings_on_public_report(fixture):
    ctx = load_context(ROOT / "data" / "sample" / "soc2_context.yaml")
    ctx["as_of"] = date(2026, 10, 29)
    rules = sorted(f.rule for f in propose(fixture, ctx, load_policy(ROOT / "policy.yaml")))
    assert rules == sorted(["PERIOD_SHORT", "REPORT_STALE", "CATEGORY_WORDING_MIXED", "CUEC_UNOWNED"]
                           + ["CARVE_OUT_NO_ASSURANCE"] * 5)


def test_context_changes_the_outcome(fixture):
    ctx = load_context(ROOT / "data" / "sample" / "soc2_context.yaml")
    ctx["as_of"] = date(2024, 6, 15)                      # 1 month after period end
    ctx["subservice_reports_on_file"] = ["AWS", "Github", "MongoDB", "MySQL", "Google"]
    ctx["cuec_owners"] = {i: "it-access" for i in range(1, 13)}
    ctx["categories_needed"] = ["Security", "Privacy"]   # Privacy is NOT in scope
    rules = sorted(f.rule for f in propose(fixture, ctx))
    assert rules == ["CATEGORY_NOT_IN_SCOPE", "CATEGORY_WORDING_MIXED", "PERIOD_SHORT"]


def test_human_gate_is_append_only(fixture, tmp_path):
    log = tmp_path / "decisions.jsonl"
    ctx = load_context(ROOT / "data" / "sample" / "soc2_context.yaml")
    findings = propose(fixture, ctx)
    assert all(f.status == "PROPOSED" for f in findings)
    fid = findings[0].id
    decide(log, fid, "approve", "reviewer-a", "confirmed on page 1")
    decide(log, fid, "REJECTED", "reviewer-b", "changed mind")
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2   # both kept
    assert load_decisions(log)[fid]["decision"] == "REJECTED"         # latest wins
    applied = apply_decisions(propose(fixture, ctx), log)
    assert applied[0].status == "REJECTED" and applied[1].status == "PROPOSED"
    with pytest.raises(ValueError):
        decide(log, fid, "maybe", "reviewer-a")
    with pytest.raises(ValueError):
        decide(log, fid, "approve", "   ")


# Code-path checks on tiny synthetic page strings (not a real report).
def test_extract_type1_as_of_and_qualified_opinion():
    pages = [
        "SOC 2 TYPE 1 REPORT as of 30th November 2024",
        "Opinion In our opinion, except for the matter described above, the description fairly presents. Restricted Use blah",
    ]
    ex = extract(pages, "t1.pdf")
    assert ex["report_type"]["value"] == "SOC2_TYPE1"
    assert ex["period"] == {"start": "2024-11-30", "end": "2024-11-30", "page": 1}
    assert ex["opinion"]["value"] == "QUALIFIED" and ex["opinion"]["page"] == 2
    assert ex["cuecs"]["count"] == 0


def test_qualified_outside_opinion_section_is_ignored():
    pages = ["Opinion In our opinion the description fairly presents. Restricted Use", "uses a qualified third-party service"]
    assert extract(pages)["opinion"]["value"] == "UNQUALIFIED"
