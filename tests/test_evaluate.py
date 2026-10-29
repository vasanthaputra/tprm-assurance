"""Module 4 checks: the scorer gives full marks to the verified fixture and names what is wrong otherwise."""
import json
from pathlib import Path

from tprm_assurance.soc2.evaluate import score, summary

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "data" / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_rules_fixture_scores_full_marks():
    ok, total = summary(score(load("s5_msg91_rules_extraction.json"), load("s5_msg91_ground_truth.json")))
    assert ok == total and total >= 25


def test_scorer_names_the_wrong_field():
    ex = load("s5_msg91_rules_extraction.json")
    ex["cuecs"]["count"] = 11
    ex["categories"]["in_scope"] = ["Security"]
    checks = score(ex, load("s5_msg91_ground_truth.json"))
    bad = {(c.field, c.key) for c in checks if not c.ok}
    assert bad == {("cuecs", "count"), ("categories", "in_scope")}


def test_missing_field_counts_as_wrong_not_crash():
    ex = load("s5_msg91_rules_extraction.json")
    del ex["auditor"]
    checks = score(ex, load("s5_msg91_ground_truth.json"))
    assert all(not c.ok for c in checks if c.field == "auditor")
