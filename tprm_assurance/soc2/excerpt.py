"""Show the reviewer the report text behind a value, so they can check it without opening the PDF.

Readers cite a page for each field, not a sentence. This finds the passage on the cited page that
best matches the value (its own words first, then the field's usual wording, e.g. "complementary
user entity controls") and returns that window with the matched words marked. It is plain text
search: no AI, nothing leaves the machine, and it never changes a value. When none of the words
appear on the cited page it says so instead of showing an unrelated passage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

# The wording a SOC 2 report normally uses near each field (AICPA SOC 2 guide section headings).
FIELD_TERMS = {
    "report_type": ["type 2", "type ii", "type 1", "type i", "soc 2"],
    "period": ["for the period", "throughout the period", "period"],
    "report_date": ["date of", "report date"],
    "next_report_due": ["next report", "bridge letter"],
    "opinion": ["in our opinion", "opinion", "except for"],
    "categories": ["trust services criteria", "criteria relevant to", "trust services categories"],
    "subservice_orgs": ["subservice organization", "carve-out method", "carved out", "inclusive method"],
    "cuecs": ["complementary user entity controls", "user entity is responsible", "user entities are responsible",
              "user entity controls"],
    "csoc_criteria": ["complementary subservice organization controls", "subservice organization controls"],
    "auditor": ["independent service auditor", "service auditor", "cpa"],
    "test_results": ["no exceptions noted", "exceptions noted", "exception"],
}
VALUE_TERMS = {
    "SOC2_TYPE2": ["type 2", "type ii"], "SOC2_TYPE1": ["type 1", "type i"],
    "UNQUALIFIED": ["in our opinion", "in all material respects"],
    "QUALIFIED": ["except for", "qualified opinion"], "ADVERSE_OR_DISCLAIMER": ["adverse", "disclaim"],
    "carve-out": ["carve-out", "carved out", "carve out", "not included within the scope", "excluded from the scope"], "inclusive": ["inclusive method", "inclusive"],
}
WINDOW = 420          # characters shown around the best match


@dataclass
class Excerpt:
    page: int | None
    segments: list = field(default_factory=list)   # [(text, marked)]; the template escapes the text
    found: bool = False
    cited: bool = True                             # False: no reader cited a page, this is a search hit
    by: list = field(default_factory=list)         # which passes cited this page
    note: str = ""


def date_terms(iso: str) -> list[str]:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return []
    m = MONTHS[d.month - 1]
    return [f"{m} {d.day}, {d.year}", f"{m} {d.day} {d.year}", f"{d.day} {m} {d.year}", f"{m[:3]} {d.day}, {d.year}",
            f"{d.month:02d}/{d.day:02d}/{d.year}", f"{d.month}/{d.day}/{d.year}", iso]


def value_terms(value) -> list[str]:
    """Words a value would appear as in the report. Counts are not searchable, so they give none."""
    if value is None or isinstance(value, (bool, int, float)):
        return []
    if isinstance(value, (list, tuple)):
        return [t for v in value for t in value_terms(v)]
    s = str(value).strip()
    if not s or s.upper() in ("UNKNOWN", "(NONE)"):
        return []
    if s in VALUE_TERMS:
        return VALUE_TERMS[s]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date_terms(s)
    out = [s]
    short = re.split(r"[,(]| & | and ", s)[0].strip()        # "Example Audit & Co., LLP" -> "Example Audit"
    if short and short != s and len(short) >= 4:
        out.append(short)
    out += [a.strip() for a in re.findall(r"\(([^()]{2,20})\)", s)]   # "Amazon Web Services, Inc. (AWS)" -> "AWS"
    return out


def _pattern(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.split()]
    left = r"\b" if term[:1].isalnum() else ""
    last = term.split()[-1] if term.split() else ""
    # "subservice organization" also finds "organizations"; short words do not ("type i" must not match "type is")
    right = (r"s?\b" if last.isalpha() and len(last) >= 4 else r"\b") if term[-1:].isalnum() else ""
    return re.compile(left + r"\s+".join(words) + right, re.IGNORECASE)


def _matches(text: str, terms: list[str]) -> list[tuple[int, int, str]]:
    hits = []
    for t in dict.fromkeys(terms):
        hits += [(m.start(), m.end(), t) for m in _pattern(t).finditer(text)]
    return sorted(hits)


def _window(text: str, strong: list[str], weak: list[str]) -> tuple[int, int, list] | None:
    """The window covering the most distinct value words (worth 3) and field words (worth 1)."""
    hits = _matches(text, strong + weak)
    if not hits:
        return None
    strong_set = set(strong)
    best = None
    for s, _, _ in hits:
        lo = max(0, s - WINDOW // 4)
        hi = min(len(text), lo + WINDOW)
        inside = {t for a, b, t in hits if a >= lo and b <= hi}
        score = sum(3 if t in strong_set else 1 for t in inside)
        if best is None or score > best[0]:
            best = (score, lo, hi)
    _, lo, hi = best
    # snap to word edges so the excerpt does not start or end mid-word
    if lo > 0:
        sp = text.find(" ", lo)
        lo = sp + 1 if 0 <= sp < lo + 30 else lo
    if hi < len(text):
        sp = text.rfind(" ", hi - 30, hi)
        hi = sp if sp > lo else hi
    return lo, hi, [(a, b) for a, b, _ in hits if a >= lo and b <= hi]


def _segments(text: str, lo: int, hi: int, marks: list[tuple[int, int]]) -> list[tuple[str, bool]]:
    segs, pos = [], lo
    if lo > 0:
        segs.append(("… ", False))
    for a, b in marks:
        if a < pos:                         # overlapping terms ("exceptions noted" inside "no exceptions noted")
            continue
        segs += [(text[pos:a], False), (text[a:b], True)]
        pos = b
    segs.append((text[pos:hi], False))
    if hi < len(text):
        segs.append((" …", False))
    return [(t, m) for t, m in segs if t]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def find(pages: list[str], fld: str, values: list, page: int | None) -> Excerpt:
    """The passage on `page` that best supports `values` (a field's values from one or more passes).
    With no cited page, searches the whole report and marks the result as not cited."""
    strong = [t for v in values for t in value_terms(v)]
    weak = FIELD_TERMS.get(fld, [])
    if isinstance(page, int) and 1 <= page <= len(pages):
        text = _clean(pages[page - 1])
        w = _window(text, strong, weak)
        if w is None:
            return Excerpt(page, found=False)
        return Excerpt(page, _segments(text, *w), found=True)
    for i, raw in enumerate(pages, start=1):          # no cited page: first page holding the field's wording
        text = _clean(raw)
        w = _window(text, strong, weak)
        if w is not None:
            return Excerpt(i, _segments(text, *w), found=True, cited=False)
    return Excerpt(None, found=False, cited=False)


def page_of(sub: dict | None, key: str) -> int | None:
    """The page a reading cites for one field (auditor firm has its own page)."""
    if not isinstance(sub, dict):
        return None
    if key == "firm" and isinstance(sub.get("firm_page"), int):
        return sub["firm_page"]
    p = sub.get("page", sub.get("from_page"))
    return p if isinstance(p, int) else None


# Which field a reliance finding is about, so its excerpt can be found.
RULE_FIELDS = {
    "TYPE1_WHERE_TYPE2": ("report_type", "value"), "PERIOD_SHORT": ("period", "end"),
    "BRIDGE_LETTER_NEEDED": ("period", "end"), "REPORT_STALE": ("period", "end"),
    "OPINION_QUALIFIED": ("opinion", "value"), "OPINION_ADVERSE": ("opinion", "value"),
    "OPINION_UNKNOWN": ("opinion", "value"), "CATEGORY_NOT_IN_SCOPE": ("categories", "in_scope"),
    "CATEGORY_WORDING_MIXED": ("categories", "in_scope"), "CARVE_OUT_NO_ASSURANCE": ("subservice_orgs", "values"),
    "CUEC_UNOWNED": ("cuecs", "count"), "NO_CUEC_SECTION": ("cuecs", "count"),
    "EXCEPTIONS_PRESENT": ("test_results", "exceptions_noted"),
}


# Same test as the pattern code's count (extract.py): the legend sentence explaining the phrase
# "No exceptions noted" is not a result; any other "exception(s) noted" is.
_LEGEND = re.compile(r"[“\"]\s*No exceptions noted\.?\s*[”\"]", re.IGNORECASE)
_EXCEPTION_RAW = re.compile(r"(?<!No )exceptions? noted", re.IGNORECASE)
_EXCEPTION = re.compile(r"(?<!No )exceptions?\s+noted", re.IGNORECASE)


def first_exception(pages: list[str], start: int | None) -> Excerpt | None:
    """The first passage the pattern code counts as an exception, with the wording before it, plus
    every page holding one. None if there is none."""
    first = start if isinstance(start, int) and 1 <= start <= len(pages) else 1
    hits = [i for i in range(first, len(pages) + 1) if _EXCEPTION_RAW.search(_LEGEND.sub(" ", pages[i - 1]))]
    if not hits:
        return None
    text = _clean(_LEGEND.sub(" ", pages[hits[0] - 1]))
    m = _EXCEPTION.search(text) or re.search(r"exceptions?\s+noted", text, re.IGNORECASE)
    if m is None:
        return None
    lo, hi = max(0, m.start() - 320), min(len(text), m.end() + 140)
    if lo > 0:
        sp = text.find(" ", lo)
        lo = sp + 1 if 0 <= sp < lo + 30 else lo
    shown = ", ".join(map(str, hits[:12])) + (" …" if len(hits) > 12 else "")
    return Excerpt(hits[0], _segments(text, lo, hi, [(m.start(), m.end())]), found=True, cited=False,
                   note=("first passage pattern code counts as an exception (any 'exception(s) noted' other than "
                         f"'No exceptions noted'); found on page{'s' if len(hits) > 1 else ''} {shown}. "
                         "Check it is a test result, not control wording."))


def for_finding(pages: list[str], ex: dict, rule: str, page: int | None) -> Excerpt | None:
    if rule == "EXCEPTIONS_PRESENT":
        hit = first_exception(pages, page)
        if hit is not None:
            return hit
    if rule not in RULE_FIELDS:
        return None
    fld, key = RULE_FIELDS[rule]
    sub = ex.get(fld) if isinstance(ex.get(fld), dict) else {}
    values = [sub.get("start"), sub.get("end")] if fld == "period" else [sub.get(key)]
    return find(pages, fld, values, page)
