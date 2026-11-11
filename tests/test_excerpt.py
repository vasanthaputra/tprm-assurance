"""Report text behind a value: the right passage, marked, never invented; and the web pages show it
escaped, with decided rows folded behind "Change"."""
import re

import pytest

from tprm_assurance.soc2 import excerpt as xp

PAGES = [
    "SOC 2 Type 2 report for the period May 1, 2024, to April 30, 2025.",
    "Subservice Organizations\nThe hosting provided by AWS was not included within the scope of this examination.",
    "Testing matrices. Results are noted by the phrase “No exceptions noted.” in the result column.",
    "CC1.1 Inspected the policy. No exceptions noted. CC1.2 Inspected the log. Exception noted: one review was late.",
    "As a result, complementary user entity controls are not required.",
]


def marked(e):
    return [t for t, m in e.segments if m]


def test_marks_the_value_on_the_cited_page():
    e = xp.find(PAGES, "report_type", ["SOC2_TYPE2"], 1)
    assert e.found and e.cited and e.page == 1 and "Type 2" in marked(e)


def test_dates_are_found_in_report_wording():
    e = xp.find(PAGES, "period", ["2024-05-01", "2025-04-30"], 1)
    assert "May 1, 2024" in marked(e) and "April 30, 2025" in marked(e)


def test_plural_heading_and_abbreviation_in_brackets():
    e = xp.find(PAGES, "subservice_orgs", [["Amazon Web Services, Inc. (AWS)"]], 2)
    assert "Subservice Organizations" in marked(e) and "AWS" in marked(e)
    m = xp.find(PAGES, "subservice_orgs", ["carve-out"], 2)
    assert "not included within the scope" in marked(m)


def test_type_1_is_not_found_inside_type_2():
    e = xp.find(["This is a Type II report."], "report_type", ["SOC2_TYPE1"], 1)
    assert not any(t.lower() in ("type i", "type 1") for t in marked(e))
    e = xp.find(["The report type is described here."], "report_type", ["SOC2_TYPE1"], 1)
    assert not e.found


def test_says_not_found_instead_of_showing_an_unrelated_passage():
    e = xp.find(PAGES, "cuecs", [9], 1)
    assert e.page == 1 and not e.found and e.segments == []


def test_no_cited_page_searches_the_report_and_says_so():
    e = xp.find(PAGES, "cuecs", [0], None)
    assert e.found and not e.cited and e.page == 5


def test_first_exception_skips_the_legend_and_clean_results():
    e = xp.first_exception(PAGES, 3)
    assert e.page == 4 and marked(e) == ["Exception noted"] and "page 4" in e.note
    assert xp.first_exception(PAGES[:3], 1) is None


def test_finding_excerpt_uses_the_rule_field():
    ex = {"cuecs": {"count": 0, "page": None}}
    e = xp.for_finding(PAGES, ex, "NO_CUEC_SECTION", None)
    assert e.page == 5 and not e.cited
    assert xp.for_finding(PAGES, ex, "NOT_A_RULE", None) is None


# ---- web pages -------------------------------------------------------------------------------

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tprm_assurance.web.app import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path, pages_reader=lambda p: ["x"], allowed_hosts={"testserver"}))


def sample(client):
    t = re.search(r'name="csrf" value="([^"]+)"', client.get("/").text).group(1)
    r = client.post("/sample", data={"csrf": t}, follow_redirects=False)
    return r.headers["location"].split("/r/")[1].split("?")[0], t


def test_passes_page_shows_report_text_and_folds_resolved_rows(client):
    rid, t = sample(client)
    page = client.get(f"/r/{rid}/passes").text
    assert 'class="src"' in page and "<mark>" in page
    open_forms = page.count('action="/r/' + rid + '/passes/resolve"')
    row_id = re.findall(r'name="row_id" value="([^"]+)"', page)[0]
    client.post(f"/r/{rid}/passes/resolve", data={"row_id": row_id, "choice": "rules", "reviewer": "me", "csrf": t})
    page = client.get(f"/r/{rid}/passes").text
    assert page.count('<details class="change"><summary>Change</summary>') == 1
    assert page.count('action="/r/' + rid + '/passes/resolve"') == open_forms     # still changeable, just folded


def test_report_text_is_escaped(client, tmp_path):
    rid, _ = sample(client)
    pages = tmp_path / rid / "pages.json"
    pages.write_text(pages.read_text(encoding="utf-8").replace("SOC 2 Type 2 Report", "SOC 2 Type 2 Report <script>x</script>"),
                     encoding="utf-8")
    page = client.get(f"/r/{rid}/passes").text
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page


def test_decided_finding_is_folded_and_shows_who(client):
    rid, t = sample(client)
    fid = "example-vendor-soc2:EXCEPTIONS_PRESENT:1"
    client.post(f"/r/{rid}/decide", data={"ex": "rules", "finding_id": fid, "decision": "approve",
                                          "reviewer": "me", "note": "checked page 33", "csrf": t})
    page = client.get(f"/r/{rid}?ex=rules").text
    assert page.count('<details class="change"><summary>Change</summary>') == 1 and "checked page 33" in page
    assert "Report text, page" in page
