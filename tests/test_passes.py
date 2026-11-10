"""3-pass review: Jev as pass 2, the three-way comparison, resolutions and the merge gate.
Jev is a stand-in client here; the sample data is fictional (data/sample)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tprm_assurance.soc2.conflicts import GateBlocked
from tprm_assurance.soc2.passes import MISSING, apply_resolutions, compare, jev_pass, merge, resolve

S = Path(__file__).resolve().parent.parent / "data" / "sample"
POLICY = {"conflicts": {"gate_severity": "HIGH", "jev_yes": 0.8, "jev_no": 0.2}}


def load(name):
    return json.loads((S / name).read_text(encoding="utf-8"))


def pages():
    raw = load("sample_soc2_pages.json")
    return [raw.get(str(i), "") for i in range(1, 61)]


class Jev:
    """Says yes (0.95) to statements whose candidate is in `yes`, no (0.05) otherwise, unsure for `unsure`."""
    def __init__(self, yes, unsure=()):
        self.yes, self.unsure, self.calls = set(yes), set(unsure), []

    def system_one(self, state, questions, model=None):
        self.calls.append(questions)
        out = {}
        for qid, q in questions.items():
            text = str(getattr(q, "instructions", None) or q["instructions"])   # the question only, not its criteria
            p = 0.5 if any(u in text for u in self.unsure) else 0.95 if any(y in text for y in self.yes) else 0.05
            out[qid] = SimpleNamespace(noul=p)
        return SimpleNamespace(nouls=out)


@pytest.fixture
def readings():
    return {"rules": load("sample_soc2_extraction.json"), "claude-text": load("sample_soc2_extraction_b.json")}


TRUE_ON_PAGES = ["SOC 2 Type 2", "without any qualification", "name Security", "name Availability",
                 "Nimbus", "Gitworks", "Ledgerly"]


def test_jev_pass_answers_only_fixed_choice_fields(readings):
    jev = jev_pass(readings, pages(), Jev(TRUE_ON_PAGES), POLICY)
    assert jev["report_type"]["value"] == "SOC2_TYPE2"
    assert jev["opinion"]["value"] == "UNQUALIFIED"
    assert jev["categories"]["in_scope"] == ["Security", "Availability"]
    assert len(jev["subservice_orgs"]["values"]) == 3           # spelling variants are asked about once
    for not_jev in ("period", "cuecs", "test_results", "auditor"):
        assert not_jev not in jev


def test_unsure_jev_answer_is_not_a_value(readings):
    jev = jev_pass(readings, pages(), Jev(TRUE_ON_PAGES, unsure=["Confidentiality"]), POLICY)
    assert "categories" not in jev
    assert jev["_jev"]["fields"]["categories.in_scope"]["status"] == "unsure"


def test_a_failed_jev_call_is_an_error(readings):
    class Down:
        def system_one(self, **kw):
            raise ConnectionError("down")
    jev = jev_pass(readings, pages(), Down(), POLICY)
    assert all(f["status"] == "error" for f in jev["_jev"]["fields"].values())
    assert "report_type" not in jev


def test_three_way_comparison_flags_every_disagreement(readings):
    readings["jev"] = jev_pass(readings, pages(), Jev(TRUE_ON_PAGES), POLICY)
    rows = {r.id: r for r in compare(readings)}
    assert rows["report_type.value"].agree and rows["opinion.value"].agree
    scope = rows["categories.in_scope"]
    assert not scope.agree and scope.values["jev"] == ["Security", "Availability"]
    assert rows["cuecs.count"].values["jev"] is MISSING and not rows["cuecs.count"].agree


def test_jev_alone_can_raise_a_disagreement(readings):
    readings["claude-text"] = json.loads(json.dumps(readings["rules"]))   # passes 1 and 3 agree
    readings["claude-text"]["extractor"] = "claude-text"
    readings["jev"] = jev_pass(readings, pages(), Jev(["SOC 2 Type 2", "without any qualification", "name Security"]), POLICY)
    row = {r.id: r for r in compare(readings)}["categories.in_scope"]
    assert not row.agree and row.status == "OPEN"                       # Jev says Availability is not on the page


def test_merge_waits_for_every_high_disagreement(readings, tmp_path):
    readings["jev"] = jev_pass(readings, pages(), Jev(TRUE_ON_PAGES), POLICY)
    log = tmp_path / "passes.jsonl"
    with pytest.raises(GateBlocked):
        merge(readings, log, POLICY)
    open_ids = [r.id for r in compare(readings) if not r.agree and r.severity == "HIGH"]
    for rid in open_ids:
        resolve(log, readings, rid, "jev" if rid == "categories.in_scope" else "rules", "me")
    merged = merge(readings, log, POLICY)
    assert merged["categories"]["in_scope"] == ["Security", "Availability"]
    assert merged["extractor"] == "merged:3-pass"


def test_resolutions_are_bound_to_these_exact_readings(readings, tmp_path):
    log = tmp_path / "passes.jsonl"
    resolve(log, readings, "cuecs.count", "rules", "me")
    changed = json.loads(json.dumps(readings)); changed["claude-text"]["cuecs"]["count"] = 7
    row = {r.id: r for r in apply_resolutions(compare(changed), changed, log)}["cuecs.count"]
    assert row.status == "OPEN"


def test_bad_resolutions_are_refused(readings, tmp_path):
    log = tmp_path / "passes.jsonl"
    with pytest.raises(ValueError):
        resolve(log, readings, "opinion.value", "rules", "me")          # they agree; nothing to resolve
    with pytest.raises(ValueError):
        resolve(log, readings, "cuecs.count", "jev", "me")              # Jev gave no count
    with pytest.raises(ValueError):
        resolve(log, readings, "cuecs.count", "manual", "me")           # no typed value
    with pytest.raises(ValueError):
        resolve(log, readings, "cuecs.count", "rules", " ")
    assert not log.exists()
