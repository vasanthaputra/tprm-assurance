"""Module 2 checks: every planted problem is found, nothing else is flagged, and boundaries hold."""
from datetime import date
from pathlib import Path

import pytest

from tprm_assurance.acceptance import aging, check_acceptance, run_acceptances
from tprm_assurance.register import load_policy, read_csv

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture
def policy():
    p = load_policy(ROOT / "policy.yaml")
    p["as_of"] = date(2026, 10, 29)
    return p


def test_sample_matches_answer_key_exactly(tmp_path):
    pinned = tmp_path / "policy.yaml"
    pinned.write_text((ROOT / "policy.yaml").read_text(encoding="utf-8").replace("as_of: null", "as_of: 2026-10-29"),
                      encoding="utf-8")
    _, findings, _ = run_acceptances(SAMPLE / "risk_acceptances.csv", pinned)
    got = {(f.acceptance_id, f.rule) for f in findings}
    expected = {(r["id"], r["rule"]) for r in read_csv(SAMPLE / "acceptance_answer_key.csv")}
    assert got - expected == set(), f"false alarms: {sorted(got - expected)}"
    assert expected - got == set(), f"missed: {sorted(expected - got)}"


def row(**overrides):
    base = dict(id="T", vendor="X", risk_rating="HIGH", finding="f", owner="o", approver_role="SECURITY_DIRECTOR",
                approved_on="2026-09-01", expires_on="2026-12-31", conditions="", status="OPEN")
    base.update(overrides)
    return base


def rules(r, policy):
    return {f.rule for f in check_acceptance(r, policy)}


def test_clean_acceptance(policy):
    assert rules(row(), policy) == set()


def test_expiring_today_is_not_expired(policy):
    assert rules(row(expires_on="2026-10-29"), policy) == set()


def test_closed_rows_are_ignored(policy):
    assert rules(row(status="CLOSED", expires_on="2020-01-01", owner=""), policy) == set()


def test_higher_authority_is_fine(policy):
    assert rules(row(approver_role="BOARD"), policy) == set()


def test_duration_at_max_is_fine_and_one_month_over_is_not(policy):
    assert rules(row(risk_rating="CRITICAL", approver_role="CISO", approved_on="2026-09-01", expires_on="2026-12-01"),
                 policy) == set()
    assert rules(row(risk_rating="CRITICAL", approver_role="CISO", approved_on="2026-09-01", expires_on="2027-01-02"),
                 policy) == {"DURATION_OVER_MAX"}


def test_unknown_role_is_an_error(policy):
    with pytest.raises(ValueError):
        check_acceptance(row(approver_role="INTERN"), policy)


def test_aging_buckets(policy):
    rows = [row(approved_on="2026-10-01"), row(approved_on="2026-01-01"), row(approved_on="2024-01-01", status="CLOSED")]
    table = aging(rows, policy)
    assert table["HIGH"]["0-90"] == 1
    assert table["HIGH"][">180"] == 0 and table["HIGH"]["181-365"] == 1
    assert sum(table["HIGH"].values()) == 2  # the closed one is not counted
