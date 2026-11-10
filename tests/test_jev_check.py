"""Jev check on the conflict queue, with a stand-in client (no network, no key).

These tests cover the code around Jev: which conflicts are asked about, the exact
questions sent, how answers become a suggestion, and that a failed call is an error,
never a "no". They say nothing about how accurate Jev is; that needs the live probe."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tprm_assurance.soc2.conflicts import Conflict, find_conflicts, to_markdown
from tprm_assurance.soc2.jev_check import JEV_MODEL, check, load_suggestions, plan

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "data" / "fixtures"
POLICY = {"conflicts": {"jev_yes": 0.8, "jev_no": 0.2}}
PAGES = ["title page: SOC 2 TYPE 2 REPORT", "p2", "p3", "p4", "p5",
         "scope page text", "p7", "Opinion In our opinion ... Restricted Use"]


class FakeClient:
    """Answers each Noul with a probability looked up by the candidate named in it."""
    def __init__(self, by_candidate: dict[str, float] | None = None, fail: bool = False):
        self.by_candidate, self.fail, self.calls = by_candidate or {}, fail, []

    def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        if self.fail:
            raise ConnectionError("network down")
        nouls = {}
        for qid, q in questions.items():
            text = json.dumps(q, default=lambda o: getattr(o, "__dict__", str(o)))
            p = next((v for k, v in self.by_candidate.items() if k in text), 0.5)
            nouls[qid] = SimpleNamespace(noul=p)
        return SimpleNamespace(nouls=nouls)


def conflict(field, key, a, b, page=8):
    return Conflict(f"{field}.{key}", field, key, a, b, "HIGH", "pairhash")


def ex(**fields):
    base = {"source_file": "r.pdf", "extractor": "x"}
    base.update(fields)
    return base


def test_counts_dates_and_pages_are_not_sent_to_jev():
    for c in (conflict("cuecs", "count", 12, 11), conflict("period", "end", "2025-06-30", "2025-07-01"),
              conflict("report_date", "page", 9, 10)):
        p = plan(c, ex(), ex(), PAGES)
        assert p.questions == {} and p.reason


def test_scalar_opinion_suggests_the_supported_side():
    a, b = ex(opinion={"value": "UNQUALIFIED", "page": 8}), ex(opinion={"value": "QUALIFIED", "page": 8})
    c = conflict("opinion", "value", "UNQUALIFIED", "QUALIFIED")
    client = FakeClient({"without any qualification": 0.95, "contain a qualification": 0.04})
    s = check([c], a, b, PAGES, client, POLICY)[0]
    assert s.status == "SUGGESTED" and s.choice == "a" and s.value == "UNQUALIFIED"
    sent = client.calls[0]
    assert sent["model"] == JEV_MODEL and set(sent["state"]) == {"page_8"}   # only the cited page


def test_unsettled_or_unsupported_goes_to_the_person():
    a, b = ex(opinion={"value": "UNQUALIFIED", "page": 8}), ex(opinion={"value": "QUALIFIED", "page": 8})
    c = conflict("opinion", "value", "UNQUALIFIED", "QUALIFIED")
    mid = check([c], a, b, PAGES, FakeClient({"without": 0.55, "contain a": 0.1}), POLICY)[0]
    assert mid.status == "PERSON" and mid.choice is None and "unsettled" in mid.reason
    neither = check([c], a, b, PAGES, FakeClient({"without": 0.05, "contain a": 0.05}), POLICY)[0]
    assert neither.status == "PERSON" and "neither" in neither.reason
    both = check([c], a, b, PAGES, FakeClient({"without": 0.9, "contain a": 0.9}), POLICY)[0]
    assert both.status == "PERSON"


def test_unknown_reading_is_not_asked_and_counts_as_no_claim():
    a, b = ex(opinion={"value": "UNKNOWN", "page": None}), ex(opinion={"value": "UNQUALIFIED", "page": 8})
    c = conflict("opinion", "value", "UNKNOWN", "UNQUALIFIED")
    client = FakeClient({"without any qualification": 0.92})
    s = check([c], a, b, PAGES, client, POLICY)[0]
    assert len(client.calls[0]["questions"]) == 1
    assert s.status == "SUGGESTED" and s.choice == "b"


def test_list_field_asks_only_about_the_items_that_differ():
    in_a, in_b = ["Security", "Availability"], ["Security", "Availability", "Privacy"]
    a, b = ex(categories={"in_scope": in_a, "page": 6}), ex(categories={"in_scope": in_b, "page": 6})
    c = conflict("categories", "in_scope", in_a, in_b)
    client = FakeClient({"Privacy": 0.03})
    s = check([c], a, b, PAGES, client, POLICY)[0]
    assert len(client.calls[0]["questions"]) == 1 and s.choice == "a" and s.value == in_a
    s = check([c], a, b, PAGES, FakeClient({"Privacy": 0.97}), POLICY)[0]
    assert s.choice == "b"


def test_list_field_can_suggest_a_value_neither_extractor_had():
    in_a, in_b = ["Security", "Confidentiality"], ["Security", "Privacy"]
    a, b = ex(categories={"in_scope": in_a, "page": 6}), ex(categories={"in_scope": in_b, "page": 6})
    c = conflict("categories", "in_scope", in_a, in_b)
    s = check([c], a, b, PAGES, FakeClient({"Confidentiality": 0.95, "Privacy": 0.95}), POLICY)[0]
    assert s.choice == "manual" and sorted(s.value) == ["Confidentiality", "Privacy", "Security"]


def test_wording_only_differences_in_names_are_matched_without_asking():
    in_a = ["Nimbus cloud(NC)", "MongoDB"]
    in_b = ["Amazon Web Services (AWS)", "MongoDB", "Twilio"]
    a, b = ex(subservice_orgs={"values": in_a, "page": 6}), ex(subservice_orgs={"values": in_b, "page": 6})
    c = conflict("subservice_orgs", "values", in_a, in_b)
    client = FakeClient({"Twilio": 0.02})
    s = check([c], a, b, PAGES, client, POLICY)[0]
    asked = json.dumps(client.calls[0]["questions"], default=lambda o: getattr(o, "__dict__", str(o)))
    assert "Twilio" in asked and "Amazon" not in asked
    assert s.choice == "a" and s.value == in_a


def test_spelling_only_list_difference_is_settled_in_code():
    """Seen on the real Report A run: Claude wrote 'Amazon Web Services (AWS)', rules 'Nimbus cloud(NC)'."""
    in_a = ["Nimbus cloud(NC)", "Gitworks(Gitworks Inc)", "MongoDB"]
    in_b = ["Amazon Web Services (AWS)", "GitHub (GitHub Inc)", "MongoDB"]
    a, b = ex(subservice_orgs={"values": in_a, "page": 6}), ex(subservice_orgs={"values": in_b, "page": 6})
    client = FakeClient()
    s = check([conflict("subservice_orgs", "values", in_a, in_b)], a, b, PAGES, client, POLICY)[0]
    assert client.calls == [] and s.status == "SUGGESTED" and s.choice == "a" and "spelling" in s.reason


def test_a_failed_call_is_an_error_not_an_answer():
    a, b = ex(opinion={"value": "UNQUALIFIED", "page": 8}), ex(opinion={"value": "QUALIFIED", "page": 8})
    c = conflict("opinion", "value", "UNQUALIFIED", "QUALIFIED")
    s = check([c], a, b, PAGES, FakeClient(fail=True), POLICY)[0]
    assert s.status == "ERROR" and s.choice is None and "network down" in s.reason


def test_thresholds_must_leave_an_unsettled_band():
    a, b = ex(opinion={"value": "UNQUALIFIED", "page": 8}), ex(opinion={"value": "QUALIFIED", "page": 8})
    c = conflict("opinion", "value", "UNQUALIFIED", "QUALIFIED")
    for bad in ({"jev_yes": 0.5, "jev_no": 0.5}, {"jev_yes": 0.3, "jev_no": 0.7}, {"jev_yes": 1.2, "jev_no": 0.2}):
        with pytest.raises(ValueError):
            check([c], a, b, PAGES, FakeClient(), {"conflicts": bad})


def test_record_keeps_the_exact_payload_and_answers(tmp_path):
    a, b = ex(opinion={"value": "UNQUALIFIED", "page": 8}), ex(opinion={"value": "QUALIFIED", "page": 8})
    c = conflict("opinion", "value", "UNQUALIFIED", "QUALIFIED")
    s = check([c], a, b, PAGES, FakeClient({"without": 0.95, "contain a": 0.04}), POLICY)[0]
    rec = s.to_record()
    assert rec["request"]["model"] == JEV_MODEL and rec["request"]["state"]["page_8"].startswith("Opinion")
    assert set(rec["answers"].values()) == {0.95, 0.04}
    json.dumps(rec)                                        # serialisable, so it can be re-run


def test_queue_shows_suggestion_only_for_the_same_pair(tmp_path):
    fa = json.loads((FIX / "s5_report_a_rules_extraction.json").read_text(encoding="utf-8"))
    fb = json.loads(json.dumps(fa)); fb["extractor"] = "manual"; fb["opinion"]["value"] = "QUALIFIED"
    cs = find_conflicts(fa, fb)
    pages = ["x"] * 52
    sug = check(cs, fa, fb, pages, FakeClient({"without": 0.95, "contain a": 0.04}), POLICY)
    path = tmp_path / "suggestions.json"
    path.write_text(json.dumps([s.to_record() for s in sug]), encoding="utf-8")
    md = to_markdown(fa, fb, cs, "HIGH", load_suggestions(path, cs[0].pair_hash))
    assert "Jev suggests" in md and "a (UNQUALIFIED)" in md
    md_other = to_markdown(fa, fb, cs, "HIGH", load_suggestions(path, "another-pair"))
    assert "a (UNQUALIFIED)" not in md_other
