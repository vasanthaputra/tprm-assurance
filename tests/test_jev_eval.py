"""Planted-error test harness: case building, decoy guard, grouping and scoring (stand-in client)."""
from types import SimpleNamespace

import pytest

from tprm_assurance.soc2.jev_eval import build_cases, run, score

TRUTH = {"report_type": {"value": "SOC2_TYPE2", "page": 1},
         "opinion": {"value": "UNQUALIFIED", "page": 2},
         "categories": {"in_scope": ["Security"], "page": 3},
         "subservice_orgs": {"values": ["Amazon Web Services (AWS)"], "page": 3}}
PAGES = ["SOC 2 Type 2", "Opinion In our opinion ...", "scope: Security. Uses Amazon Web Services (AWS)."]
SPEC = {"name": "r", "subservice_decoys": ["Twilio"], "hard": {"categories.in_scope": ["Privacy"]}}


def test_cases_cover_true_and_planted_values():
    cases = build_cases(SPEC, TRUTH, PAGES)
    by = {(c.field, c.candidate): c for c in cases}
    assert by[("report_type.value", "SOC2_TYPE2")].expected is True
    assert by[("report_type.value", "SOC2_TYPE1")].expected is False
    assert sum(c.field == "opinion.value" for c in cases) == 3
    assert sum(c.field == "categories.in_scope" for c in cases) == 5
    assert by[("categories.in_scope", "Privacy")].hard and not by[("categories.in_scope", "Availability")].hard
    assert by[("subservice_orgs.values", "Twilio")].expected is False
    assert all(c.page in (1, 2, 3) for c in cases)


def test_a_decoy_that_is_on_the_page_is_refused():
    spec = dict(SPEC, subservice_decoys=["Amazon Web Services"])
    with pytest.raises(ValueError):
        build_cases(spec, TRUTH, PAGES)


class Fake:
    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, model=None):
        self.calls.append((state, questions))
        return SimpleNamespace(nouls={q: SimpleNamespace(noul=0.9) for q in questions})


def test_one_request_per_report_and_field():
    cases = build_cases(SPEC, TRUTH, PAGES)
    client = Fake()
    run(cases, {"r": PAGES}, client)
    assert len(client.calls) == 4 and all(c.p == 0.9 for c in cases)


def test_scoring_counts_wrong_and_unsettled_separately():
    cases = build_cases(SPEC, TRUTH, PAGES)
    for c in cases:                       # true -> 0.95; planted -> 0.05, except one wrong and one unsettled
        c.p = 0.95 if c.expected else 0.05
    planted = [c for c in cases if not c.expected]
    planted[0].p, planted[1].p = 0.9, 0.5
    s = score(cases, 0.8, 0.2)
    assert s["planted"]["accepted_WRONG"] == 1 and s["planted"]["unsettled"] == 1
    assert s["true"]["accepted"] == sum(c.expected for c in cases) and s["true"]["rejected_WRONG"] == 0
    assert s["accuracy_at_0.5"] == (len(cases) - 2) / len(cases)   # 0.9 and 0.5 both read as "yes" at 0.5
