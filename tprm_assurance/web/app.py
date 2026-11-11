"""Local web app for tprm-assurance: a thin layer over the existing modules, no new decision logic.

Run:  python -m tprm_assurance.web        (serves http://127.0.0.1:8765 on this machine only)

Everything stays in ./workspace/ (git-ignored). Real SOC 2 reports are restricted use: this app
is meant to run locally and is not built to be hosted for other people's uploads.

Safeguards (a localhost app is still reachable from any web page the user has open):
- Host check: only Host 127.0.0.1 / localhost is served (blocks DNS rebinding).
- Synchronizer token (OWASP CSRF cheat sheet): every form carries a per-process secret; a POST
  without it is refused, and a cross-site Origin is refused.
- Uploads: PDF content only (checked by its first bytes), size-limited, stored under a generated name.
- Report ids are matched against a strict pattern and must resolve inside the workspace.
- API keys are read into the process environment only and are never rendered.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse

import yaml
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..register import load_policy
from ..soc2 import conflicts as cq
from ..soc2 import excerpt as xp
from ..soc2 import passes as px
from ..soc2.extract import CATEGORIES as CATEGORIES_ORDER
from ..soc2.reliance import load_context, propose, report_hash
from ..soc2.review import apply_decisions, decide, load_decisions

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
EXTRACTIONS = ["rules", "claude-text", "merged"]
LABELS = {"rules": "Pass 1: pattern code", "jev": "Pass 2: Jev", "claude-text": "Pass 3: Claude",
          "merged": "Merged (after review)"}
RID = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
MAX_UPLOAD = 40 * 1024 * 1024
FACT_ROWS = [("report_type", "value"), ("period", "start"), ("period", "end"), ("report_date", "value"),
             ("opinion", "value"), ("categories", "in_scope"), ("categories", "also_mentioned"),
             ("subservice_orgs", "values"), ("subservice_orgs", "method"), ("cuecs", "count"),
             ("csoc_criteria", "values"), ("auditor", "firm"), ("test_results", "no_exceptions_noted"),
             ("test_results", "exceptions_noted")]


def load_user_keys() -> None:
    """Copy API keys from the Windows user environment into this process if they are not set."""
    try:
        import winreg
    except ImportError:
        return
    for name in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY"):
        if os.environ.get(name):
            continue
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                os.environ[name] = winreg.QueryValueEx(k, name)[0]
        except OSError:
            pass


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "report"


BASE = "/projects/tprm/app"     # where the signed-in app lives on domaskai.com


def create_app(workspace: Path | None = None, *, claude_runner=None, jev_client_factory=None,
               pages_reader=None, allowed_hosts: set[str] | None = None, policy_path: Path | None = None,
               access=None) -> FastAPI:
    ws = Path(workspace or ROOT / "workspace").resolve()
    ws.mkdir(parents=True, exist_ok=True)
    policy = load_policy(policy_path or ROOT / "policy.yaml")
    hosts = allowed_hosts or {"127.0.0.1", "localhost"}
    csrf_secret = secrets.token_urlsafe(32)
    templates = Jinja2Templates(directory=str(HERE / "templates"))

    if claude_runner is None:
        from ..soc2.llm import run_anthropic as claude_runner
    if pages_reader is None:
        from ..soc2.extract import read_pages as pages_reader
    if jev_client_factory is None:
        from ..soc2.jev_check import make_client as jev_client_factory

    app = FastAPI(title="tprm-assurance", docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()
    app.state.workspace = ws
    page_cache: dict = {}                  # pdf path -> (mtime_ns, size, pages); reading a 57-page PDF takes ~3.5 s
    origin_hosts = set(hosts) | (set(access.hosts) if access else set())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        request.state.user = None
        request.state.base = BASE if request.url.path == BASE or request.url.path.startswith(BASE + "/") else ""
        via_cloudflare = "cf-ray" in request.headers or "cf-connecting-ip" in request.headers
        if host in hosts and not via_cloudflare:
            pass                                               # this machine: no sign-in needed
        elif access and host in access.hosts:
            if not request.state.base:
                return PlainTextResponse("Not found.", status_code=404)
            try:
                request.state.user = access.verify(request.headers.get("cf-access-jwt-assertion"))
            except PermissionError:
                return PlainTextResponse("Sign in at domaskai.com to use this app.", status_code=403)
        else:
            return PlainTextResponse("This app only answers on localhost or through its sign-in.", status_code=400)
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and urlparse(origin).hostname not in origin_hosts:
            return PlainTextResponse("Cross-site request refused.", status_code=403)
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        # same-origin, not no-referrer: with no-referrer browsers send "Origin: null" on form posts,
        # which the cross-site check above (rightly) refuses.
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'"
        return resp

    # ---- helpers ------------------------------------------------------------------------
    def who(request: Request, typed: str) -> str:
        """Signed-in requests are recorded under the verified email, whatever was typed."""
        return request.state.user or typed

    def go(request: Request, path: str) -> RedirectResponse:
        return RedirectResponse(request.state.base + path, status_code=303)

    def check_csrf(token: str) -> None:
        if not secrets.compare_digest(token or "", csrf_secret):
            raise HTTPException(403, "Form token missing or wrong. Reload the page and try again.")

    def rdir(rid: str) -> Path:
        if not RID.match(rid or ""):
            raise HTTPException(404, "No such report")
        d = (ws / rid).resolve()
        if d.parent != ws or not d.is_dir():
            raise HTTPException(404, "No such report")
        return d

    def read_ex(d: Path, name: str) -> dict | None:
        p = d / f"{name}.json"
        return json.loads(p.read_text(encoding="utf-8")) if name in EXTRACTIONS + ["jev"] and p.exists() else None

    def context(d: Path) -> dict:
        p = d / "context.yaml"
        if not p.exists():
            base = yaml.safe_load((ROOT / "data" / "sample" / "soc2_context.yaml").read_text(encoding="utf-8")) or {}
            base["as_of"] = date.today().isoformat()
            p.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
        return load_context(p)

    def report_pages(d: Path) -> list[str] | None:
        if (d / "pages.json").exists():
            raw = json.loads((d / "pages.json").read_text(encoding="utf-8"))
            n = max(int(k) for k in raw if k.isdigit())
            return [raw.get(str(i), "") for i in range(1, n + 1)]
        pdf = d / "report.pdf"
        if pdf.exists():
            st = pdf.stat()
            hit = page_cache.get(str(pdf))
            if hit is None or hit[:2] != (st.st_mtime_ns, st.st_size):
                hit = (st.st_mtime_ns, st.st_size, pages_reader(pdf))
                page_cache[str(pdf)] = hit
            return hit[2]
        return None

    def available(d: Path) -> list[str]:
        return [n for n in EXTRACTIONS if (d / f"{n}.json").exists()]

    def has(name: str) -> bool:
        return bool(os.environ.get(name))

    def render(request: Request, tpl: str, status: int = 200, **kw):
        kw.update(csrf=csrf_secret, labels=LABELS, base=request.state.base, user=request.state.user)
        return templates.TemplateResponse(request, tpl, kw, status_code=status)

    def report_page(request: Request, rid: str, ex_name: str | None = None, msg: str = "", err: str = "", status: int = 200):
        d = rdir(rid)
        names = available(d)
        default = next((n for n in ("merged", "rules") if n in names), names[0] if names else None)
        ex_name = ex_name if ex_name in names else default
        ex = read_ex(d, ex_name) if ex_name else None
        ctx = context(d)
        findings = apply_decisions(propose(ex, ctx, policy), d / "decisions.jsonl") if ex else []
        latest = load_decisions(d / "decisions.jsonl")
        decided = {f.id: latest[(f.report_hash, f.id)] for f in findings if (f.report_hash, f.id) in latest}
        pages = report_pages(d) if ex else None
        quotes = {f.id: xp.for_finding(pages, ex, f.rule, f.page) for f in findings} if pages else {}
        facts = [(f"{f}.{k}", (ex.get(f) or {}).get(k), (ex.get(f) or {}).get("page") or (ex.get(f) or {}).get("from_page"))
                 for f, k in FACT_ROWS] if ex else []
        meta_p = d / "claude-text.meta.json"
        return render(request, "report.html", status, rid=rid, names=names, ex_name=ex_name, ex=ex,
                      hash=report_hash(ex) if ex else "", facts=facts, findings=findings, ctx=ctx,
                      decided=decided, quotes=quotes,
                      categories=CATEGORIES_ORDER, has_pdf=(d / "report.pdf").exists(),
                      claude_ok=has("ANTHROPIC_API_KEY"),
                      meta=json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else None,
                      msg=msg, err=err)

    def conflicts_page(request: Request, rid: str, a: str, b: str, msg: str = "", err: str = "", status: int = 200):
        d = rdir(rid)
        A, B = read_ex(d, a), read_ex(d, b)
        if A is None or B is None or a == b:
            raise HTTPException(404, "Pick two different readings of this report")
        gate = cq.gate_severity(policy)
        try:
            found = cq.apply_resolutions(cq.find_conflicts(A, B), d / "conflicts.jsonl")
        except ValueError as e:                    # e.g. the two readings are of different files
            return render(request, "conflicts.html", 400, rid=rid, a=a, b=b, rows=[], gate=gate, blocked=[],
                          names=available(d), has_sug=False, jev_ok=False, msg="", err=str(e))
        from ..soc2.jev_check import describe, load_suggestions
        sug = load_suggestions(d / f"suggestions-{a}-{b}.json", cq.pair_hash(A, B))
        rows = [(c, describe(sug.get(c.id)) if sug else None) for c in found]
        return render(request, "conflicts.html", status, rid=rid, a=a, b=b, rows=rows, gate=gate,
                      blocked=cq.blocking(found, gate), names=available(d), has_sug=bool(sug),
                      jev_ok=(d / "report.pdf").exists() and has("TYPESAFE_API_KEY"), msg=msg, err=err)

    # ---- pages --------------------------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    def home(request: Request):
        reports = []
        for d in sorted(p for p in ws.iterdir() if p.is_dir() and RID.match(p.name)):
            reports.append({"rid": d.name, "names": available(d), "pdf": (d / "report.pdf").exists()})
        return render(request, "home.html", reports=reports,
                      claude=has("ANTHROPIC_API_KEY"), jev=has("TYPESAFE_API_KEY"))

    @router.post("/sample")
    def add_sample(request: Request, csrf: str = Form("")):
        check_csrf(csrf)
        d = ws / "sample-example-vendor"
        d.mkdir(exist_ok=True)
        for src, dst in (("sample_soc2_extraction.json", "rules.json"), ("sample_soc2_extraction_b.json", "claude-text.json"),
                         ("sample_soc2_pages.json", "pages.json")):
            (d / dst).write_text((ROOT / "data" / "sample" / src).read_text(encoding="utf-8"), encoding="utf-8")
        return go(request, f"/r/{d.name}?ex=rules")

    @router.post("/upload")
    async def upload(request: Request, file: UploadFile = File(...), csrf: str = Form("")):
        check_csrf(csrf)
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(400, "File too large (40 MB limit)")
        if not data.startswith(b"%PDF-"):
            raise HTTPException(400, "That file is not a PDF")
        rid = f"{_slug(Path(file.filename or 'report').stem)}-{hashlib.sha256(data).hexdigest()[:8]}"
        d = ws / rid
        d.mkdir(exist_ok=True)
        (d / "report.pdf").write_bytes(data)
        return go(request, f"/r/{rid}")

    @router.get("/r/{rid}", response_class=HTMLResponse)
    def report(request: Request, rid: str, ex: str | None = None, m: str = ""):
        return report_page(request, rid, ex, msg=m[:300])

    @router.post("/r/{rid}/extract", response_class=HTMLResponse)
    def extract(request: Request, rid: str, which: str = Form(...), csrf: str = Form(""), back: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        pdf = d / "report.pdf"
        if not pdf.exists():
            return report_page(request, rid, err="This report has no PDF to read.", status=400)
        try:
            if which == "rules":
                from ..soc2.extract import extract_pdf
                data, msg = extract_pdf(pdf), "Rules extractor finished."
            elif which == "claude-text":
                if not has("ANTHROPIC_API_KEY"):
                    return report_page(request, rid, err="No ANTHROPIC_API_KEY on this machine.", status=400)
                data, meta = claude_runner(pdf, "text")
                (d / "claude-text.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                msg = (f"Claude finished: {meta.get('input_tokens')} input / {meta.get('output_tokens')} output tokens, "
                       f"about ${meta.get('estimated_cost_usd')}.")
            else:
                raise HTTPException(400, "Unknown extractor")
        except HTTPException:
            raise
        except Exception as e:                     # shown to the local user, never swallowed
            return report_page(request, rid, err=f"Extraction failed: {type(e).__name__}: {e}", status=500)
        data["source_file"] = "report.pdf" if data.get("source_file") is None else data["source_file"]
        (d / f"{which}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        if back == "passes":
            return go(request, f"/r/{rid}/passes?m={quote(msg)}")
        return go(request, f"/r/{rid}?ex={which}&m={quote(msg)}")

    @router.post("/r/{rid}/context", response_class=HTMLResponse)
    async def save_context(request: Request, rid: str):
        form = await request.form()
        check_csrf(form.get("csrf", ""))
        d = rdir(rid)
        try:
            as_of = date.fromisoformat(form.get("as_of", "")).isoformat()
        except ValueError:
            return report_page(request, rid, form.get("ex"), err="As-of date must be YYYY-MM-DD.", status=400)
        owners = int(form.get("cuec_owned", "0") or 0)
        ctx = {"as_of": as_of, "expect_type2": form.get("expect_type2") == "on",
               "categories_needed": [c for c in CATEGORIES_ORDER if form.get(f"cat_{c}") == "on"],
               "bridge_letter_on_file": form.get("bridge") == "on",
               "subservice_reports_on_file": [s.strip() for s in form.get("held", "").splitlines() if s.strip()],
               "cuec_owners": {i: "assigned" for i in range(1, max(0, owners) + 1)}}
        (d / "context.yaml").write_text(yaml.safe_dump(ctx, sort_keys=False), encoding="utf-8")
        return go(request, f"/r/{rid}?ex={quote(str(form.get('ex') or ''))}&m={quote('Context saved. Findings recalculated.')}")

    @router.post("/r/{rid}/decide", response_class=HTMLResponse)
    def decide_finding(request: Request, rid: str, ex: str = Form(...), finding_id: str = Form(...),
                       decision: str = Form(...), reviewer: str = Form(""), note: str = Form(""), csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        data = read_ex(d, ex)
        if data is None:
            raise HTTPException(404, "No such reading")
        ids = {f.id for f in propose(data, context(d), policy)}
        if finding_id not in ids:
            return report_page(request, rid, ex, err="That finding is not in this reading.", status=400)
        try:
            decide(d / "decisions.jsonl", finding_id, decision, who(request, reviewer), report_hash(data), note)
        except ValueError as e:
            return report_page(request, rid, ex, err=str(e), status=400)
        done = f"{ {'approve': 'Approved', 'reject': 'Rejected'}.get(decision, decision)} {finding_id}."
        return go(request, f"/r/{rid}?ex={quote(ex)}&m={quote(done)}")

    @router.get("/r/{rid}/conflicts", response_class=HTMLResponse)
    def conflicts(request: Request, rid: str, a: str = "rules", b: str = "claude-text", m: str = ""):
        return conflicts_page(request, rid, a, b, msg=m[:300])

    @router.post("/r/{rid}/resolve", response_class=HTMLResponse)
    def resolve(request: Request, rid: str, a: str = Form(...), b: str = Form(...), conflict_id: str = Form(...),
                choice: str = Form(...), reviewer: str = Form(""), value: str = Form(""), note: str = Form(""),
                csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        A, B = read_ex(d, a), read_ex(d, b)
        if A is None or B is None:
            raise HTTPException(404, "No such reading")
        try:
            v = json.loads(value) if choice == "manual" and value.strip() else None
            cq.resolve(d / "conflicts.jsonl", A, B, conflict_id, choice, who(request, reviewer), v, note)
        except (ValueError, json.JSONDecodeError) as e:
            return conflicts_page(request, rid, a, b, err=f"Not resolved: {e}", status=400)
        return go(request, f"/r/{rid}/conflicts?a={quote(a)}&b={quote(b)}")

    @router.post("/r/{rid}/jev", response_class=HTMLResponse)
    def ask_jev(request: Request, rid: str, a: str = Form(...), b: str = Form(...), csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        A, B = read_ex(d, a), read_ex(d, b)
        if A is None or B is None or not (d / "report.pdf").exists():
            return conflicts_page(request, rid, a, b, err="Jev needs the report PDF to read the cited pages.", status=400)
        from ..soc2.jev_check import check
        found = [c for c in cq.apply_resolutions(cq.find_conflicts(A, B), d / "conflicts.jsonl") if c.status == "OPEN"]
        try:
            sug = check(found, A, B, pages_reader(d / "report.pdf"), jev_client_factory(), policy)
        except Exception as e:
            return conflicts_page(request, rid, a, b, err=f"Jev check failed: {type(e).__name__}: {e}", status=500)
        (d / f"suggestions-{a}-{b}.json").write_text(json.dumps([s.to_record() for s in sug], indent=2), encoding="utf-8")
        asked = sum(1 for s in sug if s.request)
        note = f"Jev checked {len(sug)} open conflicts ({asked} needed a question)."
        return go(request, f"/r/{rid}/conflicts?a={quote(a)}&b={quote(b)}&m={quote(note)}")

    @router.post("/r/{rid}/merge")
    def do_merge(request: Request, rid: str, a: str = Form(...), b: str = Form(...), csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        A, B = read_ex(d, a), read_ex(d, b)
        if A is None or B is None:
            raise HTTPException(404, "No such reading")
        try:
            merged = cq.merge(A, B, d / "conflicts.jsonl", policy)
        except cq.GateBlocked as e:
            return conflicts_page(request, rid, a, b, err=f"Merge refused: {e}", status=409)
        (d / "merged.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
        return go(request, f"/r/{rid}?ex=merged")

    # ---- 3-pass review -----------------------------------------------------------------
    def pass_readings(d: Path) -> dict:
        return {n: read_ex(d, n) for n in px.PASSES if read_ex(d, n) is not None}

    def show(v) -> str:
        if v is px.MISSING:
            return ""
        if isinstance(v, list):
            return ", ".join(map(str, v)) or "(none)"
        return "(none)" if v is None else str(v)

    def majority(r) -> str:
        """Pre-select the pass whose answer most passes share (Claude on a tie). Only a default:
        the reviewer still chooses and submits."""
        present = {n: cq._norm(v) for n, v in r.values.items() if v is not px.MISSING}
        votes = {n: sum(1 for w in present.values() if w == v) for n, v in present.items()}
        return max(present, key=lambda n: (votes[n], n == "claude-text"), default="manual")

    SHORT = {"rules": "pattern code", "jev": "Jev", "claude-text": "Claude"}

    def row_excerpts(r, readings: dict, pages: list[str]) -> list:
        """The report text behind one field: one excerpt per page the passes cited (at most 3)."""
        values = [v for v in r.values.values() if v is not px.MISSING]
        cited: dict[int, list[str]] = {}
        for n in px.PASSES:
            pg = xp.page_of((readings.get(n) or {}).get(r.field), r.key) if n in readings else None
            if pg is not None and r.values.get(n, px.MISSING) is not px.MISSING:
                cited.setdefault(pg, []).append(SHORT[n])
        if not cited:
            e = xp.find(pages, r.field, values, None)
            return [e] if e.found else []
        out = []
        for pg, by in list(cited.items())[:3]:
            e = xp.find(pages, r.field, values, pg)
            e.by = by
            out.append(e)
        return out

    def passes_page(request: Request, rid: str, msg: str = "", err: str = "", status: int = 200):
        d = rdir(rid)
        readings = pass_readings(d)
        gate = cq.gate_severity(policy)
        rows, blocked = [], []
        if readings:
            try:
                found = px.apply_resolutions(px.compare(readings), readings, d / "passes.jsonl")
            except ValueError as e:
                found, err = [], str(e)
            blocked = px.blocking(found, gate)
            pages = report_pages(d)
            for r in found:
                rows.append({"id": r.id, "severity": r.severity, "agree": r.agree, "status": r.status, "note": r.note,
                             "excerpts": row_excerpts(r, readings, pages) if pages else [],
                             "cells": [(n, show(r.values.get(n, px.MISSING)), n in readings) for n in px.PASSES],
                             "choices": [n for n in px.PASSES if r.values.get(n, px.MISSING) is not px.MISSING],
                             "suggest": majority(r), "resolution": r.resolution})
        rows.sort(key=lambda r: (r["agree"], r["severity"] != "HIGH"))
        pages_ok = bool(readings) and report_pages(d) is not None
        return render(request, "passes.html", status, rid=rid, readings=readings, rows=rows, gate=gate,
                      blocked=blocked, passes=px.PASSES, has_pdf=(d / "report.pdf").exists(),
                      claude_ok=has("ANTHROPIC_API_KEY"), jev_ok=has("TYPESAFE_API_KEY") and pages_ok,
                      n_open=sum(1 for r in rows if r["status"] == "OPEN"), msg=msg, err=err)

    @router.get("/r/{rid}/passes", response_class=HTMLResponse)
    def passes_view(request: Request, rid: str, m: str = ""):
        return passes_page(request, rid, msg=m[:300])

    @router.post("/r/{rid}/run-jev", response_class=HTMLResponse)
    def run_jev(request: Request, rid: str, csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        readings = {n: v for n, v in pass_readings(d).items() if n != "jev"}
        pages = report_pages(d)
        if not readings or not pages:
            return passes_page(request, rid, err="Jev needs the report's page text and at least one other pass.", status=400)
        try:
            jev = px.jev_pass(readings, pages, jev_client_factory(), policy)
        except Exception as e:
            return passes_page(request, rid, err=f"Jev pass failed: {type(e).__name__}: {e}", status=500)
        (d / "jev.json").write_text(json.dumps(jev, indent=2), encoding="utf-8")
        answered = sum(1 for f in jev["_jev"]["fields"].values() if f.get("status") == "answered")
        note = f"Jev answered {answered} of {len(px.JEV_FIELDS)} fixed-choice fields."
        return go(request, f"/r/{rid}/passes?m={quote(note)}")

    @router.post("/r/{rid}/passes/resolve", response_class=HTMLResponse)
    def passes_resolve(request: Request, rid: str, row_id: str = Form(...), choice: str = Form(...),
                       reviewer: str = Form(""), value: str = Form(""), note: str = Form(""), csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        try:
            v = json.loads(value) if choice == "manual" and value.strip() else None
            px.resolve(d / "passes.jsonl", pass_readings(d), row_id, choice, who(request, reviewer), v, note)
        except (ValueError, json.JSONDecodeError) as e:
            return passes_page(request, rid, err=f"Not resolved: {e}", status=400)
        return go(request, f"/r/{rid}/passes")

    @router.post("/r/{rid}/passes/merge")
    def passes_merge(request: Request, rid: str, csrf: str = Form("")):
        check_csrf(csrf)
        d = rdir(rid)
        try:
            merged = px.merge(pass_readings(d), d / "passes.jsonl", policy)
        except cq.GateBlocked as e:
            return passes_page(request, rid, err=f"Merge refused: {e}", status=409)
        except ValueError as e:
            return passes_page(request, rid, err=str(e), status=400)
        (d / "merged.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
        return go(request, f"/r/{rid}?ex=merged&m={quote('Merged the three passes. Findings below use the merged reading.')}")

    app.include_router(router)
    app.include_router(router, prefix=BASE)
    return app


def main() -> None:
    import uvicorn
    load_user_keys()
    print("tprm-assurance web app: http://127.0.0.1:8765  (this machine only; Ctrl+C to stop)")
    from .access import load_guard
    access = load_guard(ROOT / "private" / "web_access.json")
    print("sign-in for domaskai.com:", "configured" if access else "not configured (localhost only)")
    uvicorn.run(create_app(access=access), host="127.0.0.1", port=8765, log_level="warning")
