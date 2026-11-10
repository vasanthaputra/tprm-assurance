"""Module 4 checks: the scorer gives full marks to the verified fixture and names what is wrong otherwise."""
import json
from pathlib import Path

from tprm_assurance.soc2.evaluate import score, summary

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "data" / "sample"   # SYNTHETIC extraction and answer key


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_rules_fixture_scores_full_marks():
    ok, total = summary(score(load("sample_soc2_extraction.json"), load("sample_soc2_truth.json")))
    assert ok == total == 27


def test_scorer_names_the_wrong_field():
    ex = load("sample_soc2_extraction.json")
    ex["cuecs"]["count"] = 8
    ex["categories"]["in_scope"] = ["Security"]
    checks = score(ex, load("sample_soc2_truth.json"))
    bad = {(c.field, c.key) for c in checks if not c.ok}
    assert bad == {("cuecs", "count"), ("categories", "in_scope")}


def test_missing_field_counts_as_wrong_not_crash():
    ex = load("sample_soc2_extraction.json")
    del ex["auditor"]
    checks = score(ex, load("sample_soc2_truth.json"))
    assert all(not c.ok for c in checks if c.field == "auditor")
