"""Module 1 checks: every planted problem is found, nothing else is flagged, and boundaries hold."""
from datetime import date
from pathlib import Path

import pytest

from vendor_rely.register import check_vendor, load_policy, months_between, read_csv, run

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture
def policy():
    p = load_policy(ROOT / "policy.yaml")
    p["as_of"] = date(2026, 10, 29)  # the date the answer key was written for
    return p


def test_sample_matches_answer_key_exactly(policy, tmp_path):
    pinned = tmp_path / "policy.yaml"
    pinned.write_text((ROOT / "policy.yaml").read_text(encoding="utf-8").replace("as_of: null", "as_of: 2026-10-29"),
                      encoding="utf-8")
    _, findings, _ = run(SAMPLE / "vendor_register.csv", SAMPLE / "ap_vendors.csv", pinned)
    got = {(f.vendor, f.rule) for f in findings}
    expected = {(r["vendor"], r["rule"]) for r in read_csv(SAMPLE / "answer_key.csv")}
    assert got - expected == set(), f"false alarms: {sorted(got - expected)}"
    assert expected - got == set(), f"missed: {sorted(expected - got)}"


@pytest.mark.parametrize("earlier, later, months", [
    (date(2026, 6, 30), date(2026, 10, 29), 3),   # day 29 < 30, so only 3 completed months
    (date(2025, 10, 28), date(2026, 10, 29), 12),
    (date(2025, 6, 30), date(2026, 10, 29), 15),
    (date(2026, 10, 29), date(2026, 10, 29), 0),
])
def test_months_between(earlier, later, months):
    assert months_between(earlier, later) == months


def row(**overrides):
    base = dict(vendor="X", service="s", criticality="HIGH", personal_data="no", dpa_signed="no",
                last_assessed="2026-09-01", report_type="SOC2_TYPE2", report_period_end="2026-09-30",
                bridge_letter="no")
    base.update(overrides)
    return base


def rules(r, policy):
    return {f.rule for f in check_vendor(r, policy)}


def test_clean_vendor_has_no_findings(policy):
    assert rules(row(), policy) == set()


def test_low_tier_needs_no_report(policy):
    assert rules(row(criticality="LOW", report_type="NONE", report_period_end=""), policy) == set()


def test_type1_is_fine_for_medium(policy):
    assert rules(row(criticality="MEDIUM", report_type="SOC2_TYPE1"), policy) == set()


def test_stale_report_does_not_also_ask_for_bridge_letter(policy):
    assert rules(row(report_period_end="2025-01-31"), policy) == {"REPORT_STALE"}


def test_unknown_tier_is_an_error_not_a_silent_pass(policy):
    with pytest.raises(ValueError):
        check_vendor(row(criticality="SEVERE"), policy)
