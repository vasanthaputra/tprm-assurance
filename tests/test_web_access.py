"""Sign-in check for the domaskai.com path: only a valid Cloudflare Access token gets in."""
import json
import time

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("fastapi")
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from tprm_assurance.web.access import AccessGuard, load_guard
from tprm_assurance.web.app import BASE, create_app

TEAM = "example-team.cloudflareaccess.com"
AUD = "test-aud-tag"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(email="reviewer@example.com", aud=AUD, iss=f"https://{TEAM}", exp_in=300, key=KEY):
    now = int(time.time())
    return jwt.encode({"email": email, "aud": [aud], "iss": iss, "iat": now, "exp": now + exp_in}, key, algorithm="RS256")


@pytest.fixture()
def client(tmp_path):
    guard = AccessGuard(TEAM, AUD, {"domaskai.com", "www.domaskai.com"}, key_resolver=lambda t: KEY.public_key())
    return TestClient(create_app(tmp_path, access=guard))


def remote(tok=None, host="domaskai.com"):
    h = {"host": host, "cf-ray": "abc", "cf-connecting-ip": "203.0.113.5"}
    if tok:
        h["cf-access-jwt-assertion"] = tok
    return h


def test_guard_verifies_good_token():
    g = AccessGuard(TEAM, AUD, key_resolver=lambda t: KEY.public_key())
    assert g.verify(token("Reviewer@Example.com")) == "reviewer@example.com"


@pytest.mark.parametrize("bad", [
    None, "", "not-a-jwt",
    token(aud="other-app"), token(iss="https://evil.cloudflareaccess.com"),
    token(exp_in=-60), token(key=OTHER), token(email=""),
])
def test_guard_rejects_bad_tokens(bad):
    g = AccessGuard(TEAM, AUD, key_resolver=lambda t: KEY.public_key())
    with pytest.raises(PermissionError):
        g.verify(bad)


def test_unsigned_token_rejected():
    now = int(time.time())
    t = jwt.encode({"email": "x@example.com", "aud": [AUD], "iss": f"https://{TEAM}", "iat": now, "exp": now + 300},
                   None, algorithm="none")
    with pytest.raises(PermissionError):
        AccessGuard(TEAM, AUD, key_resolver=lambda t: KEY.public_key()).verify(t)


def test_remote_without_token_is_refused(client):
    assert client.get(BASE + "/", headers=remote()).status_code == 403
    assert client.get(BASE + "/", headers=remote(token(exp_in=-60))).status_code == 403


def test_remote_with_token_gets_in_and_links_carry_prefix(client):
    r = client.get(BASE + "/", headers=remote(token()))
    assert r.status_code == 200
    assert "signed in as reviewer@example.com" in r.text
    assert f'action="{BASE}/upload"' in r.text


def test_remote_outside_prefix_is_not_served(client):
    assert client.get("/", headers=remote(token())).status_code == 404


def test_unknown_host_refused(client):
    assert client.get(BASE + "/", headers={"host": "evil.example"}).status_code == 400


def test_localhost_through_cloudflare_needs_sign_in(client):
    """A request that came through the tunnel cannot claim to be this machine."""
    assert client.get("/", headers={"host": "localhost", "cf-ray": "abc"}).status_code == 400


def test_localhost_still_works_without_sign_in(client):
    r = client.get("/", headers={"host": "localhost"})
    assert r.status_code == 200 and 'action="/upload"' in r.text


def test_remote_redirects_keep_prefix_and_reviewer_is_verified_email(client, tmp_path):
    h = remote(token("colleague@example.com"))
    page = client.get(BASE + "/", headers=h).text
    csrf = page.split('name="csrf" value="')[1].split('"')[0]
    h_post = dict(h, origin="https://domaskai.com")
    r = client.post(BASE + "/sample", data={"csrf": csrf}, headers=h_post, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(BASE + "/r/")
    rid = r.headers["location"].split("/r/")[1].split("?")[0].split("/")[0]
    passes = client.get(f"{BASE}/r/{rid}/passes", headers=h).text
    assert "as colleague@example.com" in passes and 'name="reviewer"' not in passes
    conflicts = client.get(f"{BASE}/r/{rid}/conflicts", headers=h).text
    cid = conflicts.split('name="conflict_id" value="')[1].split('"')[0]
    a = conflicts.split('name="a" value="')[1].split('"')[0]
    b = conflicts.split('name="b" value="')[1].split('"')[0]
    r = client.post(f"{BASE}/r/{rid}/resolve", headers=h_post, follow_redirects=False,
                    data={"csrf": csrf, "a": a, "b": b, "conflict_id": cid, "choice": "a", "value": "",
                          "reviewer": "someone-else", "note": ""})
    assert r.status_code == 303 and r.headers["location"].startswith(BASE + "/")
    log = (tmp_path / rid / "conflicts.jsonl").read_text(encoding="utf-8")
    assert "colleague@example.com" in log and "someone-else" not in log


def test_cross_site_post_refused(client):
    h = dict(remote(token()), origin="https://evil.example")
    assert client.post(BASE + "/sample", data={"csrf": "x"}, headers=h).status_code == 403


def test_load_guard(tmp_path):
    assert load_guard(tmp_path / "missing.json") is None
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"team_domain": TEAM, "aud": ""}), encoding="utf-8")
    assert load_guard(p) is None
