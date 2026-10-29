"""Optional AI extractor. Used only when `--extractor anthropic` is passed and the
`anthropic` package plus credentials are available. The rules extractor is the default
and the tests never call this.

Status: written against the Anthropic Python SDK documentation but NOT yet run (no API
key in the development environment). Module 4 will measure its accuracy against the
hand-verified fixture once it has been run.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

MODEL = "claude-opus-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "report_type": {"type": "object", "properties": {"value": {"type": "string", "enum": ["SOC2_TYPE1", "SOC2_TYPE2", "UNKNOWN"]}, "page": {"type": ["integer", "null"]}}, "required": ["value", "page"], "additionalProperties": False},
        "period": {"type": "object", "properties": {"start": {"type": ["string", "null"]}, "end": {"type": ["string", "null"]}, "page": {"type": ["integer", "null"]}}, "required": ["start", "end", "page"], "additionalProperties": False},
        "report_date": {"type": "object", "properties": {"value": {"type": ["string", "null"]}, "page": {"type": ["integer", "null"]}}, "required": ["value", "page"], "additionalProperties": False},
        "opinion": {"type": "object", "properties": {"value": {"type": "string", "enum": ["UNQUALIFIED", "QUALIFIED", "ADVERSE_OR_DISCLAIMER", "UNKNOWN"]}, "page": {"type": ["integer", "null"]}, "basis": {"type": "string"}}, "required": ["value", "page", "basis"], "additionalProperties": False},
        "categories": {"type": "object", "properties": {"in_scope": {"type": "array", "items": {"type": "string"}}, "also_mentioned": {"type": "array", "items": {"type": "string"}}, "page": {"type": ["integer", "null"]}}, "required": ["in_scope", "also_mentioned", "page"], "additionalProperties": False},
        "subservice_orgs": {"type": "object", "properties": {"values": {"type": "array", "items": {"type": "string"}}, "method": {"type": "string", "enum": ["carve-out", "inclusive", "UNKNOWN"]}, "page": {"type": ["integer", "null"]}}, "required": ["values", "method", "page"], "additionalProperties": False},
        "cuecs": {"type": "object", "properties": {"count": {"type": "integer"}, "page": {"type": ["integer", "null"]}}, "required": ["count", "page"], "additionalProperties": False},
        "csoc_criteria": {"type": "object", "properties": {"values": {"type": "array", "items": {"type": "string"}}, "page": {"type": ["integer", "null"]}}, "required": ["values", "page"], "additionalProperties": False},
        "auditor": {"type": "object", "properties": {"signer": {"type": ["string", "null"]}, "firm": {"type": ["string", "null"]}, "page": {"type": ["integer", "null"]}}, "required": ["signer", "firm", "page"], "additionalProperties": False},
        "test_results": {"type": "object", "properties": {"no_exceptions_noted": {"type": "integer"}, "exceptions_noted": {"type": "integer"}, "from_page": {"type": ["integer", "null"]}}, "required": ["no_exceptions_noted", "exceptions_noted", "from_page"], "additionalProperties": False},
    },
    "required": ["report_type", "period", "report_date", "opinion", "categories", "subservice_orgs", "cuecs", "csoc_criteria", "auditor", "test_results"],
    "additionalProperties": False,
}

PROMPT = (
    "You are extracting facts from a SOC 2 report for a third-party risk reviewer. "
    "Report only what the document says; use null or UNKNOWN when a field is not present. "
    "Every page number must be the 1-based page where you read the value. "
    "Dates are ISO (YYYY-MM-DD). Categories are from: Security, Availability, Processing Integrity, "
    "Confidentiality, Privacy. 'in_scope' are the categories the auditor's scope names as the applicable "
    "trust services criteria; 'also_mentioned' are other categories named on the same scope page. "
    "'cuecs.count' is the number of complementary user entity controls listed. 'test_results' counts the "
    "results column: 'No exceptions noted' versus any other wording."
)


def extract_with_anthropic(pdf_path: Path) -> dict:
    import anthropic  # optional dependency

    client = anthropic.Anthropic()
    data = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {getattr(response.stop_details, 'explanation', '')}")
    text = next(b.text for b in response.content if b.type == "text")
    out = json.loads(text)
    out.update({"source_file": pdf_path.name, "extractor": f"anthropic:{MODEL}"})
    return out


def manual_prompt(pages: list[str], source_name: str) -> str:
    """Build a prompt to paste into the Claude desktop app (or any assistant) by hand.

    No API key needed. Paste the whole text, save the JSON reply as a file, and run
    `soc2 review` on it. Page markers let the assistant cite pages.
    """
    head = [
        PROMPT,
        "",
        "Reply with ONLY a JSON object that matches this schema (no prose, no code fences):",
        json.dumps(SCHEMA, indent=1),
        "",
        f'Set "source_file" to "{source_name}" and "extractor" to "manual".',
        "",
        "=" * 60, f"DOCUMENT: {source_name} ({len(pages)} pages)", "=" * 60,
    ]
    body = [f"\n=== PAGE {i} ===\n{text}" for i, text in enumerate(pages, start=1)]
    return "\n".join(head) + "\n" + "\n".join(body) + "\n"
