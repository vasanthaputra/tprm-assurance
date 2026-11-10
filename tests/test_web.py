"""Local web app: pages, the human gates, and the safeguards a localhost app needs
(host check, form token, upload checks, path checks, no keys in pages). No network:
Claude and Jev are stand-ins."""
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tprm_assurance.web.app import create_app

FAKE_KEY = "sk-ant-THIS-MUST-NEVER-APPEAR"


def fake_claude(pdf_path, route):
    ex = json.loads(open("data/sample/sample_soc2_extraction_b.json", encoding="utf-8").read())
    ex["source_file"] = pdf_path.name
    return ex, {"input_tokens": 1000, "output_tokens": 100, "estimated_cost_usd": 0.006}


class FakeJev:
    def system_one(self, state, questions, model=None):
        return SimpleNamespace(nouls={q: SimpleNamespace(noul=0.95) for q in questions})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    app = create_app(tmp_path, claude_runner=fake_claude, jev_client_factory=FakeJev,
                     pages_reader=lambda p: ["x"] * 60, allowed_hosts={"testserver"})
    return TestClient(app)


def token(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def add_sample(client):
    t = token(client.get("/").text)
    r = client.post("/sample", data={"csrf": t}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"].split("/r/")[1].split("?")[0], t


def test_home_and_sample_report_findings(client):
    assert client.get("/").status_code == 200
    rid, _ = add_sample(client)
    page = client.get(f"/r/{rid}").text
    assert page.count(">PROPOSED<") == 8 and "EXCEPTIONS_PRESENT" in page
    assert FAKE_KEY not in page


def test_approve_needs_the_form_token(client):
    rid, t = add_sample(client)
    fid = "example-vendor-soc2:EXCEPTIONS_PRESENT:1"
    bad = client.post(f"/r/{rid}/decide", data={"ex": "rules", "finding_id": fid, "decision": "approve",
                                                "reviewer": "me", "csrf": "wrong"})
    assert bad.status_code == 403
    ok = client.post(f"/r/{rid}/decide", data={"ex": "rules", "finding_id": fid, "decision": "approve",
                                               "reviewer": "me", "note": "triaged", "csrf": t})
    assert ok.status_code == 200 and "APPROVED" in ok.text


def test_other_hosts_are_refused(client):
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400


def test_upload_accepts_only_pdfs(client):
    t = token(client.get("/").text)
    bad = client.post("/upload", data={"csrf": t}, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 400
    ok = client.post("/upload", data={"csrf": t}, follow_redirects=False,
                     files={"file": ("Vendor Report.pdf", b"%PDF-1.4\n%fake\n", "application/pdf")})
    assert ok.status_code == 303 and "/r/vendor-report-" in ok.headers["location"]


def test_report_ids_cannot_escape_the_workspace(client):
    assert client.get("/r/..%2F..%2Fetc").status_code == 404
    assert client.get("/r/no-such-report").status_code == 404


def test_conflicts_block_merge_until_resolved(client):
    rid, t = add_sample(client)
    q = client.get(f"/r/{rid}/conflicts?a=rules&b=claude-text").text
    assert "Merge blocked" in q and "cuecs.count" in q and "categories.in_scope" in q
    refused = client.post(f"/r/{rid}/merge", data={"a": "rules", "b": "claude-text", "csrf": t})
    assert "merge refused" in refused.text.lower()
    open_ids = re.findall(r'name="conflict_id" value="([^"]+)"', q)
    assert len(open_ids) >= 2
    for cid in open_ids:
        client.post(f"/r/{rid}/resolve", data={"a": "rules", "b": "claude-text", "conflict_id": cid,
                                               "choice": "a", "reviewer": "me", "csrf": t})
    done = client.post(f"/r/{rid}/merge", data={"a": "rules", "b": "claude-text", "csrf": t}, follow_redirects=False)
    assert done.status_code == 303
    assert "merged" in client.get(f"/r/{rid}").text


def test_claude_and_jev_run_through_injected_clients(client):
    t = token(client.get("/").text)
    loc = client.post("/upload", data={"csrf": t}, follow_redirects=False,
                      files={"file": ("acme.pdf", b"%PDF-1.4\n%fake\n", "application/pdf")}).headers["location"]
    rid = loc.split("/r/")[1]
    # the rules extractor needs real PDF text; seed its output instead
    (client.app.state.workspace / rid / "rules.json").write_text(
        open("data/sample/sample_soc2_extraction.json", encoding="utf-8").read().replace("example_vendor_soc2.pdf", "report.pdf"),
        encoding="utf-8")
    r = client.post(f"/r/{rid}/extract", data={"which": "claude-text", "csrf": t})
    assert r.status_code == 200 and "$0.006" in r.text
    j = client.post(f"/r/{rid}/jev", data={"a": "rules", "b": "claude-text", "csrf": t})
    assert j.status_code == 200 and "Jev suggests" in j.text
    assert FAKE_KEY not in r.text + j.text


def test_readings_of_different_files_show_an_error_not_a_crash(client):
    rid, t = add_sample(client)
    p = client.app.state.workspace / rid / "claude-text.json"
    p.write_text(p.read_text(encoding="utf-8").replace("example_vendor_soc2.pdf", "other.pdf"), encoding="utf-8")
    r = client.get(f"/r/{rid}/conflicts?a=rules&b=claude-text")
    assert r.status_code == 400 and "different files" in r.text


def test_origin_header_as_a_browser_sends_it(client):
    """Found in the browser 2026-11-10: with Referrer-Policy no-referrer, Chrome sent Origin: null on
    the app's own form posts and the cross-site check refused them."""
    t = token(client.get("/").text)
    assert client.get("/").headers["referrer-policy"] == "same-origin"
    same = client.post("/sample", data={"csrf": t}, headers={"origin": "http://testserver"}, follow_redirects=False)
    assert same.status_code == 303
    for evil in ("null", "https://evil.example"):
        r = client.post("/sample", data={"csrf": t}, headers={"origin": evil}, follow_redirects=False)
        assert r.status_code == 403


def test_decisions_redirect_so_a_refresh_does_not_repeat_them(client):
    rid, t = add_sample(client)
    r = client.post(f"/r/{rid}/decide", follow_redirects=False,
                    data={"ex": "rules", "finding_id": "example-vendor-soc2:CUEC_UNOWNED:1", "decision": "reject",
                          "reviewer": "me", "csrf": t})
    assert r.status_code == 303 and r.headers["location"].startswith(f"/r/{rid}?ex=rules&m=Rejected")
    log = (client.app.state.workspace / rid / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    client.get(r.headers["location"])                      # the "refresh"
    assert len((client.app.state.workspace / rid / "decisions.jsonl").read_text(encoding="utf-8").splitlines()) == len(log) == 1


def test_three_pass_review_end_to_end(client):
    rid, t = add_sample(client)
    page = client.get(f"/r/{rid}/passes").text
    assert "Pass 1: pattern code" in page and "Pass 2: Jev" in page and "Pass 3: Claude" in page
    assert "Merge blocked" in page
    r = client.post(f"/r/{rid}/run-jev", data={"csrf": t})          # stand-in Jev, invented sample pages
    assert r.status_code == 200 and (client.app.state.workspace / rid / "jev.json").exists()
    page = client.get(f"/r/{rid}/passes").text
    ids = re.findall(r'name="row_id" value="([^"]+)"', page)
    assert ids
    for row_id in ids:
        choice = re.search(rf'value="{re.escape(row_id)}">\s*<select name="choice"><option value="([^"]+)"', page).group(1)
        client.post(f"/r/{rid}/passes/resolve", data={"row_id": row_id, "choice": choice, "reviewer": "me", "csrf": t})
    done = client.post(f"/r/{rid}/passes/merge", data={"csrf": t}, follow_redirects=False)
    assert done.status_code == 303 and "ex=merged" in done.headers["location"]
    assert FAKE_KEY not in page
