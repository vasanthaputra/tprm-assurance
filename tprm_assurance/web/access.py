"""Cloudflare Access check for requests that reach the app through domaskai.com.

Cloudflare Access signs in the person (one-time code to an allowed email) and forwards the request
with a signed JWT in the Cf-Access-Jwt-Assertion header. The app verifies that token itself, as
Cloudflare recommends, so a request that did not pass the sign-in is refused even if it reaches
the server some other way: RS256 signature against the team's published keys, the application's
audience tag, the team issuer, and expiry. The verified email becomes the reviewer name.

Configuration lives in private/web_access.json (git-ignored):
    {"team_domain": "<team>.cloudflareaccess.com", "aud": "<application audience tag>",
     "hosts": ["domaskai.com", "www.domaskai.com"]}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jwt

HEADER = "cf-access-jwt-assertion"


@dataclass
class AccessGuard:
    team_domain: str
    aud: str
    hosts: set[str] = field(default_factory=lambda: {"domaskai.com", "www.domaskai.com"})
    key_resolver: object = None          # token -> public key; tests inject one, production fetches the team's keys

    def __post_init__(self):
        if self.key_resolver is None:
            client = jwt.PyJWKClient(f"https://{self.team_domain}/cdn-cgi/access/certs", cache_keys=True)
            self.key_resolver = lambda token: client.get_signing_key_from_jwt(token).key

    def verify(self, token: str | None) -> str:
        """Return the signed-in email, or raise PermissionError."""
        if not token:
            raise PermissionError("no Cloudflare Access token")
        try:
            claims = jwt.decode(token, self.key_resolver(token), algorithms=["RS256"], audience=self.aud,
                                issuer=f"https://{self.team_domain}", options={"require": ["exp", "iat", "aud", "iss"]})
        except Exception as e:                 # any failure is a refusal, never a pass
            raise PermissionError(f"Cloudflare Access token rejected: {type(e).__name__}") from e
        email = (claims.get("email") or "").strip().lower()
        if not email:
            raise PermissionError("Cloudflare Access token has no email")
        return email


def load_guard(path: Path) -> AccessGuard | None:
    """None when not configured: then only localhost is served."""
    if not path.exists():
        return None
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not cfg.get("team_domain") or not cfg.get("aud"):
        return None
    return AccessGuard(cfg["team_domain"], cfg["aud"], set(cfg.get("hosts") or ["domaskai.com", "www.domaskai.com"]))
