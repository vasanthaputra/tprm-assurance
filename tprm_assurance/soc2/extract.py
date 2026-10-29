"""Rules-based SOC 2 report extractor: module 3 of tprm-assurance.

Reads a SOC 2 PDF page by page (pypdf) and pulls out the facts a reviewer needs, each
with the page it came from. No AI. The patterns follow the report anatomy in
docs/soc2_report_anatomy.md (S3, S5). Where a field cannot be found, it is reported as
UNKNOWN rather than guessed, so the reviewer looks at it.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

CATEGORIES = ("Security", "Availability", "Processing Integrity", "Confidentiality", "Privacy")
CRITERIA_RE = re.compile(r"\b(CC\d\.\d|A\d\.\d|C\d\.\d|PI\d\.\d|P\d\.\d)\b")
LONG_DATE = r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})"


def _norm(text: str) -> str:
    """Collapse pypdf's irregular spacing so phrases match."""
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_long_date(day: str, month: str, year: str) -> str | None:
    try:
        return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def read_pages(pdf_path: Path) -> list[str]:
    import pypdf  # imported here so the rest of the package works without it

    reader = pypdf.PdfReader(str(pdf_path))
    return [_norm(p.extract_text() or "") for p in reader.pages]


def _find_page(pages: list[str], pattern: str, start: int = 0) -> int | None:
    rx = re.compile(pattern, re.I)
    for i in range(start, len(pages)):
        if rx.search(pages[i]):
            return i
    return None


def extract(pages: list[str], source_name: str = "") -> dict:
    """Return a JSON-serialisable dict. Page numbers are 1-based."""
    out: dict = {"source_file": source_name, "pages": len(pages), "extractor": "rules"}

    # Report type (title page first, then anywhere).
    i = _find_page(pages, r"SOC\s*2\s*TYPE\s*(?:2|II)\b")
    j = _find_page(pages, r"SOC\s*2\s*TYPE\s*(?:1|I)\b")
    if i is not None and (j is None or i <= j):
        out["report_type"] = {"value": "SOC2_TYPE2", "page": i + 1}
    elif j is not None:
        out["report_type"] = {"value": "SOC2_TYPE1", "page": j + 1}
    else:
        out["report_type"] = {"value": "UNKNOWN", "page": None}

    # Period: "26th January 2024 - 26th April 2024". Type 1 reports say "as of <date>".
    period_rx = re.compile(LONG_DATE + r"\s*[-–]\s*" + LONG_DATE)
    out["period"] = {"start": None, "end": None, "page": None}
    for idx, text in enumerate(pages):
        m = period_rx.search(text)
        if m:
            out["period"] = {"start": _parse_long_date(*m.group(1, 2, 3)),
                             "end": _parse_long_date(*m.group(4, 5, 6)), "page": idx + 1}
            break
    if out["period"]["end"] is None:
        for idx, text in enumerate(pages):
            m = re.search(r"as of\s+" + LONG_DATE, text, re.I)
            if m:
                d = _parse_long_date(*m.group(1, 2, 3))
                out["period"] = {"start": d, "end": d, "page": idx + 1}
                break

    # Report date: "Date: 15th May 2024" in the signature block. The cover's
    # "Next Report Issue Date" is a different field and must not be mistaken for it.
    out["report_date"] = {"value": None, "page": None}
    out["next_report_due"] = {"value": None, "page": None}
    for idx, text in enumerate(pages):
        m = re.search(r"Next Report Issue Date:\s*" + LONG_DATE, text, re.I)
        if m and out["next_report_due"]["value"] is None:
            out["next_report_due"] = {"value": _parse_long_date(*m.group(1, 2, 3)), "page": idx + 1}
        m = re.search(r"(?<!Issue )Date:\s*" + LONG_DATE, text)
        if m and out["report_date"]["value"] is None:
            out["report_date"] = {"value": _parse_long_date(*m.group(1, 2, 3)), "page": idx + 1}

    # Opinion: read only the opinion section (from the "Opinion" heading to "Restricted Use"),
    # because the word "qualified" appears elsewhere in ordinary prose.
    out["opinion"] = {"value": "UNKNOWN", "page": None, "basis": "no opinion section found"}
    op = _find_page(pages, r"\bOpinion\b\s+In our opinion")
    if op is not None:
        window = " ".join(pages[op:op + 2])
        window = window[window.lower().index("in our opinion"):]
        cut = re.search(r"Restricted Use", window)
        window = window[:cut.start()] if cut else window
        if re.search(r"\bqualified\b|except for", window, re.I):
            out["opinion"] = {"value": "QUALIFIED", "page": op + 1, "basis": "'qualified' or 'except for' in the opinion section"}
        elif re.search(r"\badverse\b|do not express", window, re.I):
            out["opinion"] = {"value": "ADVERSE_OR_DISCLAIMER", "page": op + 1, "basis": "'adverse' or 'do not express' in the opinion section"}
        else:
            out["opinion"] = {"value": "UNQUALIFIED", "page": op + 1, "basis": "no qualifying language in the opinion section"}

    # Categories in scope: the list right before "(applicable trust services criteria)".
    # Also record every category named on the scope page, to catch inconsistent wording.
    out["categories"] = {"in_scope": [], "also_mentioned": [], "page": None}
    sc = _find_page(pages, r"applicable trust services criteria")
    if sc is not None:
        text = pages[sc]
        low = text.lower()
        before = text[:low.index("(applicable trust services criteria)")] if "(applicable trust services criteria)" in low else text
        # The in-scope list is the one that directly precedes the parenthetical:
        # "... Criteria for Security, Confidentiality and Availability (applicable ...)".
        k = before.lower().rfind("criteria for")
        tail = before[k:] if k >= 0 else before[-120:]
        in_scope = [c for c in CATEGORIES if re.search(re.escape(c), tail, re.I)]
        mentioned = [c for c in CATEGORIES if re.search(re.escape(c), text, re.I)]
        out["categories"] = {"in_scope": in_scope, "also_mentioned": [c for c in mentioned if c not in in_scope], "page": sc + 1}

    # Subservice organisations: bullets after "uses" on the scope page; carve-out if the
    # auditor says the subservice organisations' services were not included.
    out["subservice_orgs"] = {"values": [], "method": "UNKNOWN", "page": None}
    if sc is not None:
        text = pages[sc]
        m = re.search(r"\buses\s*,?\s*(●.*?)(?=The description presents|$)", text, re.S)
        if m:
            names = []
            for bullet in m.group(1).split("●")[1:]:
                head = re.split(r",| is | are ", bullet.strip(), maxsplit=1)[0].strip()
                if head:
                    names.append(head)
            method = "carve-out" if re.search(r"did not include the services provided by the subservice", text, re.I) else "UNKNOWN"
            if re.search(r"inclusive method", text, re.I):
                method = "inclusive"
            out["subservice_orgs"] = {"values": names, "method": method, "page": sc + 1}

    # CUECs: count "user entity is responsible" from the CUEC heading up to the CSOC heading.
    # The section heading is at the top of its page; a mention mid-page (scope page, table
    # of contents) is not the section, so anchor at the start of the page text.
    out["cuecs"] = {"count": 0, "page": None}
    cu = _find_page(pages, r"^Complementary User Entity Controls\b")
    if cu is not None:
        text = pages[cu]
        nxt = cu + 1
        while nxt < len(pages) and not re.search(r"^Complementary Subservice Organization Controls\b", pages[nxt], re.I):
            text += " " + pages[nxt]
            nxt += 1
            if nxt - cu > 3:
                break
        if nxt < len(pages):
            stop = re.search(r"Complementary Subservice Organization Controls", text, re.I)
            text = text[:stop.start()] if stop else text
        out["cuecs"] = {"count": len(re.findall(r"user entity is responsible", text, re.I)), "page": cu + 1}

    # CSOC criteria the carved-out providers are expected to cover.
    out["csoc_criteria"] = {"values": [], "page": None}
    cs = _find_page(pages, r"^Complementary Subservice Organization Controls\b")
    if cs is not None:
        text = pages[cs] + " " + (pages[cs + 1] if cs + 1 < len(pages) else "")
        out["csoc_criteria"] = {"values": sorted(set(CRITERIA_RE.findall(text))), "page": cs + 1}

    # Auditor: signer line near "License No." and the firm named in the sampling section.
    out["auditor"] = {"signer": None, "firm": None, "page": None}
    for idx, text in enumerate(pages):
        m = re.search(r"([A-Z][\w.'-]+(?: [A-Z][\w.'-]+){0,4}), Certified Public Accountant", text)
        if m:
            out["auditor"].update({"signer": m.group(1), "page": idx + 1})
            break
    for idx, text in enumerate(pages):
        m = re.search(r"([A-Z][\w&]+(?: [A-Z][\w&]+){0,3}) utilizes professional judgment", text)
        if m:
            out["auditor"]["firm"] = m.group(1)
            out["auditor"].setdefault("firm_page", idx + 1)
            out["auditor"]["firm_page"] = idx + 1
            break

    # Test results: count clean results vs anything else that says "exception(s) noted".
    tr = _find_page(pages, r"Test Results")
    clean = other = 0
    if tr is not None:
        for text in pages[tr:]:
            clean += len(re.findall(r"No exceptions noted", text, re.I))
            other += len(re.findall(r"(?<!No )exceptions? noted", text, re.I))
    out["test_results"] = {"no_exceptions_noted": clean, "exceptions_noted": other, "from_page": (tr + 1) if tr is not None else None}
    return out


def extract_pdf(pdf_path: Path) -> dict:
    return extract(read_pages(pdf_path), pdf_path.name)


def period_months(ex: dict) -> int | None:
    p = ex.get("period") or {}
    if not p.get("start") or not p.get("end"):
        return None
    from ..register import months_between
    return months_between(date.fromisoformat(p["start"]), date.fromisoformat(p["end"]))
