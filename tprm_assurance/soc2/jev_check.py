"""Jev check on the conflict queue: which reading does the cited page support?

For each open conflict between two extractions, Jev (TypeSafe's decision model) reads the
page the extractors cited and answers one yes/no question per disputed value: "does this
page support it?". Code turns those answers into a suggestion. A person still resolves
every conflict with `soc2 resolve`; the suggestion only shows in the queue.

Judgments from Jev, decisions in code (TypeSafe skill). Kept out of Jev, per its own
weak-spot page (docs.typesafe.ai/go/jaggedness.md): counts ("does not count reliably"),
dates ("reads dates as text, not as ordered quantities") and page citations.

Truth table, per disputed value (thresholds in policy.yaml, conflicts.jev_yes / jev_no):
    P >= jev_yes  -> supported           P <= jev_no -> not supported
    in between    -> unsettled: the whole conflict goes to the person
  scalar field: exactly one side supported -> suggest it; both or neither -> person
  list field:   the common items plus every supported differing item; if that equals A or
                B, suggest it, otherwise suggest it as a manual value; nothing supported
                -> person
A reading of UNKNOWN or null is the extractor saying "not found": it is not asked and
counts as not supported. A failed API call is an ERROR, never a "no".
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .conflicts import Conflict

JEV_MODEL = "jev-1.14.0"   # pinned: a new model version is a change to re-test, not a silent upgrade

# ---- All question wording lives here -------------------------------------------------

def _report_type(cand: str, ref: str) -> dict | None:
    t = {"SOC2_TYPE2": ("Type 2", "Type II", "a report on controls over a period of time"),
         "SOC2_TYPE1": ("Type 1", "Type I", "a report on controls as of a single date")}.get(cand)
    if not t:
        return None
    other = "Type 1 or Type I" if cand == "SOC2_TYPE2" else "Type 2 or Type II"
    return {"instructions": f"Does {ref} say that this report is a SOC 2 {t[0]} ({t[1]}) report?",
            "criteria": {"true": f"The report calls itself SOC 2 {t[0]} or {t[1]}, {t[2]}.",
                         "false": f"The report calls itself SOC 2 {other}, or names no type."}}


def _opinion(cand: str, ref: str) -> dict | None:
    return {
        "UNQUALIFIED": {
            "instructions": f"Is the auditor's opinion in {ref} stated without any qualification?",
            "criteria": {"true": "The opinion paragraph says the description is fairly presented and the controls "
                                 "were suitably designed (and, for a Type 2 report, operated effectively), with no "
                                 "'except for' wording.",
                         "false": "The opinion paragraph has 'except for' wording, is called qualified or adverse, "
                                  "or the auditor does not express an opinion."}},
        "QUALIFIED": {
            "instructions": f"Does the auditor's opinion in {ref} contain a qualification, such as 'except for' wording?",
            "criteria": {"true": "The opinion paragraph says the criteria were met except for a described matter.",
                         "false": "The opinion paragraph is clean, or is adverse, or the auditor does not express an opinion."}},
        "ADVERSE_OR_DISCLAIMER": {
            "instructions": f"Does the auditor in {ref} give an adverse opinion or decline to express an opinion?",
            "criteria": {"true": "The auditor says the criteria were not met, or says it does not express an opinion.",
                         "false": "The auditor gives an opinion that the criteria were met, with or without an exception."}},
    }.get(cand)


def _category(cand: str, ref: str) -> dict:
    return {"instructions": f"Does {ref} name {cand} as one of the trust services categories that this examination covers?",
            "criteria": {"true": f"{cand} is in the list of trust services criteria that the report says apply to this examination.",
                         "false": f"{cand} is not in that list. It may still appear in general text that describes what "
                                  f"the trust services categories are."}}


def _subservice(cand: str, ref: str) -> dict:
    return {"instructions": f"Does {ref} name {cand} as a subservice organization that the company uses?",
            "criteria": {"true": f"{cand} is listed as a third party whose services the company uses and that the report "
                                 f"treats as a subservice organization.",
                         "false": f"{cand} is not listed as a subservice organization in {ref}."}}


TEMPLATES = {
    ("report_type", "value"): _report_type,
    ("opinion", "value"): _opinion,
    ("categories", "in_scope"): _category,
    ("subservice_orgs", "values"): _subservice,
}
NOT_ASKED = {
    ("cuecs", "count"): "counting stays in code (Jev does not count reliably)",
    ("test_results", "exceptions_noted"): "counting stays in code (Jev does not count reliably)",
    ("test_results", "no_exceptions_noted"): "counting stays in code (Jev does not count reliably)",
    ("period", "start"): "dates stay with code or a person (Jev reads dates as text)",
    ("period", "end"): "dates stay with code or a person (Jev reads dates as text)",
}

# ---- Plan: the exact request for one conflict ----------------------------------------

def _loose(s: str) -> str:
    """Same name if only spacing, case or punctuation differ: 'Nimbus cloud(NC)'."""
    return re.sub(r"[^a-z0-9]", "", str(s).casefold())


def _as_items(v) -> list:
    if v is None or v == "UNKNOWN":
        return []
    return list(v) if isinstance(v, list) else [v]


@dataclass
class Plan:
    state: dict = field(default_factory=dict)
    questions: dict = field(default_factory=dict)     # qid -> {"instructions", "criteria"}
    asks: dict = field(default_factory=dict)          # qid -> the disputed value it asks about
    common: list = field(default_factory=list)        # values both readings share
    reason: str = ""                                  # why nothing is asked


def plan(c: Conflict, a: dict, b: dict, pages: list[str]) -> Plan:
    key = (c.field, c.key)
    if c.key in ("page", "from_page", "firm_page"):
        return Plan(reason="page citation, not a fact about the report")
    if key in NOT_ASKED:
        return Plan(reason=NOT_ASKED[key])
    if key not in TEMPLATES:
        return Plan(reason="no Jev question defined for this field")
    cited = []
    for ex in (a, b):
        n = (ex.get(c.field) or {}).get("page")
        if isinstance(n, int) and 1 <= n <= len(pages) and n not in cited:
            cited.append(n)
    if not cited:
        return Plan(reason="neither extraction cites a page")
    state = {f"page_{n}": pages[n - 1] for n in cited}
    ref = " or ".join(f"`page_{n}`" for n in cited)

    ia, ib = _as_items(c.a), _as_items(c.b)
    kb = {_loose(x) for x in ib}
    common = [x for x in ia if _loose(x) in kb]
    shared = {_loose(x) for x in common}
    differing = [x for x in ia if _loose(x) not in shared] + [x for x in ib if _loose(x) not in shared]
    p = Plan(state=state, common=common)
    for i, value in enumerate(differing):
        q = TEMPLATES[key](value, ref)
        if q is None:
            continue
        qid = f"candidate_{i}"
        p.questions[qid], p.asks[qid] = q, value
    if not p.questions:
        p.reason = "no askable value"
    return p

# ---- Check: send, read, suggest --------------------------------------------------------

@dataclass
class Suggestion:
    conflict_id: str
    pair_hash: str
    status: str                 # SUGGESTED | PERSON | ERROR | NOT_ASKED
    choice: str | None = None   # a | b | manual, when SUGGESTED
    value: object = None
    reason: str = ""
    request: dict | None = None
    answers: dict = field(default_factory=dict)     # qid -> P(yes)

    def to_record(self) -> dict:
        return asdict(self)


def thresholds(policy: dict | None) -> tuple[float, float]:
    cfg = (policy or {}).get("conflicts") or {}
    yes, no = float(cfg.get("jev_yes", 0.8)), float(cfg.get("jev_no", 0.2))
    if not (0.0 <= no < yes <= 1.0):
        raise ValueError(f"need 0 <= jev_no < jev_yes <= 1 so an unsettled band exists; got no={no}, yes={yes}")
    return yes, no


def _decide(c: Conflict, p: Plan, answers: dict, yes: float, no: float) -> tuple[str, str | None, object, str]:
    supported, unsettled = [], []
    for qid, value in p.asks.items():
        prob = answers[qid]
        if prob >= yes:
            supported.append(value)
        elif prob > no:
            unsettled.append(f"{value!r} ({prob:.2f})")
    if unsettled:
        return "PERSON", None, None, "unsettled: " + ", ".join(unsettled)
    if isinstance(c.a, list) or isinstance(c.b, list):
        value = p.common + supported
        if not value:
            return "PERSON", None, None, "neither reading fits the page"
        k = sorted(_loose(x) for x in value)
        if k == sorted(_loose(x) for x in _as_items(c.a)):
            return "SUGGESTED", "a", c.a, "the page supports A's list"
        if k == sorted(_loose(x) for x in _as_items(c.b)):
            return "SUGGESTED", "b", c.b, "the page supports B's list"
        return "SUGGESTED", "manual", value, "the page supports a list neither extractor gave"
    if len(supported) == 1:
        side = "a" if supported[0] == c.a else "b"
        return "SUGGESTED", side, supported[0], f"the page supports {side.upper()} only"
    if not supported:
        return "PERSON", None, None, "neither reading fits the page"
    return "PERSON", None, None, "both readings fit the page"


def make_client():
    from typesafe_sdk import TypeSafeClient     # optional dependency; reads TYPESAFE_API_KEY
    return TypeSafeClient(model=JEV_MODEL, timeout=60.0)


def _to_sdk(questions: dict) -> dict:
    try:
        from typesafe_sdk import Noul, NoulCriteria
    except ImportError:                          # stand-in clients in tests take plain dicts
        return {k: {"type": "noul", **q} for k, q in questions.items()}
    return {k: Noul(instructions=q["instructions"], criteria=NoulCriteria(**q["criteria"])) for k, q in questions.items()}


def check(conflicts: list[Conflict], a: dict, b: dict, pages: list[str], client, policy: dict | None) -> list[Suggestion]:
    """One request per conflict (each needs its own page). Every conflict gets a Suggestion."""
    yes, no = thresholds(policy)
    out = []
    for c in conflicts:
        p = plan(c, a, b, pages)
        if not p.questions:
            if p.reason == "no askable value" and p.common and isinstance(c.a, list) and \
                    len(p.common) == len(_as_items(c.a)) == len(_as_items(c.b)):
                # every item matched once spacing, case and punctuation are ignored: settled in code
                out.append(Suggestion(c.id, c.pair_hash, "SUGGESTED", "a", c.a,
                                      "same items; only spelling differs (settled in code, Jev not asked)"))
            else:
                out.append(Suggestion(c.id, c.pair_hash, "NOT_ASKED", reason=p.reason))
            continue
        request = {"model": JEV_MODEL, "state": p.state, "questions": p.questions}
        try:
            resp = client.system_one(state=p.state, questions=_to_sdk(p.questions), model=JEV_MODEL)
            answers = {qid: float(resp.nouls[qid].noul) for qid in p.questions}
        except Exception as e:                   # surfaced as an error, never read as "no"
            out.append(Suggestion(c.id, c.pair_hash, "ERROR", reason=f"{type(e).__name__}: {e}", request=request))
            continue
        status, choice, value, reason = _decide(c, p, answers, yes, no)
        out.append(Suggestion(c.id, c.pair_hash, status, choice, value, reason, request, answers))
    return out


def load_suggestions(path: Path, pair_hash: str) -> dict[str, dict]:
    """Suggestions for this exact pair only; ones made on another pair are ignored."""
    import json
    if not path or not Path(path).exists():
        return {}
    return {r["conflict_id"]: r for r in json.loads(Path(path).read_text(encoding="utf-8"))
            if r.get("pair_hash") == pair_hash}


def describe(rec: dict | None) -> str:
    if not rec:
        return "-"
    if rec["status"] == "SUGGESTED":
        v = rec["value"]
        return f"{rec['choice']} ({', '.join(map(str, v)) if isinstance(v, list) else v})"
    if rec["status"] == "NOT_ASKED":
        return f"not asked: {rec['reason']}"
    return f"{rec['status'].lower()}: {rec['reason']}"
