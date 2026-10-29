"""Command line.

  python -m tprm_assurance.cli register    <register.csv> <ap.csv>        [--policy P] [--out F]
  python -m tprm_assurance.cli acceptances <acceptances.csv>              [--policy P] [--out F]
  python -m tprm_assurance.cli soc2 extract <report.pdf> --out extraction.json [--extractor rules|anthropic]
  python -m tprm_assurance.cli soc2 prompt  <report.pdf> --out prompt.txt       (copy-paste path, no API key)
  python -m tprm_assurance.cli soc2 review  <extraction.json> --context ctx.yaml [--decisions log.jsonl] [--out F]
  python -m tprm_assurance.cli soc2 decide  <extraction.json> <finding_id> approve|reject --reviewer NAME [--note ...] [--decisions log.jsonl]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .acceptance import acceptances_to_markdown, run_acceptances
from .register import load_policy, run
from .report import to_markdown

ROOT = Path(__file__).resolve().parent.parent


def _emit(md: str, out: Path | None, count: int) -> None:
    if out:
        out.write_text(md, encoding="utf-8")
        print(f"{count} findings -> {out}")
    else:
        print(md)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tprm-assurance")
    sub = p.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("register", help="check a vendor register against policy")
    reg.add_argument("register_csv", type=Path)
    reg.add_argument("ap_csv", type=Path)

    acc = sub.add_parser("acceptances", help="check open risk acceptances against policy")
    acc.add_argument("acceptances_csv", type=Path)

    for s in (reg, acc):
        s.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
        s.add_argument("--out", type=Path)

    soc = sub.add_parser("soc2", help="SOC 2 reliance review").add_subparsers(dest="soc2_cmd", required=True)
    ex = soc.add_parser("extract")
    ex.add_argument("pdf", type=Path)
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--extractor", choices=["rules", "anthropic"], default="rules")
    pr = soc.add_parser("prompt", help="write a prompt to paste into the Claude app by hand (no API key)")
    pr.add_argument("pdf", type=Path)
    pr.add_argument("--out", type=Path, required=True)
    rv = soc.add_parser("review")
    rv.add_argument("extraction_json", type=Path)
    rv.add_argument("--context", type=Path, required=True)
    rv.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
    rv.add_argument("--decisions", type=Path, default=Path("decisions.jsonl"))
    rv.add_argument("--out", type=Path)
    dc = soc.add_parser("decide")
    dc.add_argument("extraction_json", type=Path, help="the extraction the finding came from (binds the decision to it)")
    dc.add_argument("finding_id")
    dc.add_argument("decision", choices=["approve", "reject"])
    dc.add_argument("--reviewer", required=True)
    dc.add_argument("--note", default="")
    dc.add_argument("--decisions", type=Path, default=Path("decisions.jsonl"))

    args = p.parse_args(argv)

    if args.command == "register":
        register, findings, policy = run(args.register_csv, args.ap_csv, args.policy)
        _emit(to_markdown(register, findings, policy), args.out, len(findings))
    elif args.command == "acceptances":
        rows, findings, policy = run_acceptances(args.acceptances_csv, args.policy)
        _emit(acceptances_to_markdown(rows, findings, policy), args.out, len(findings))
    elif args.soc2_cmd == "extract":
        if args.extractor == "anthropic":
            from .soc2.llm import extract_with_anthropic
            data = extract_with_anthropic(args.pdf)
        else:
            from .soc2.extract import extract_pdf
            data = extract_pdf(args.pdf)
        args.out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"extracted {len(data)} fields -> {args.out}")
    elif args.soc2_cmd == "prompt":
        from .soc2.extract import read_pages
        from .soc2.llm import manual_prompt
        pages = read_pages(args.pdf)
        args.out.write_text(manual_prompt(pages, args.pdf.name), encoding="utf-8")
        print(f"prompt for {len(pages)} pages -> {args.out}  (paste into the Claude app, save the JSON reply, then run: soc2 review <that.json> --context ...)")
    elif args.soc2_cmd == "review":
        from .soc2.reliance import load_context, propose, to_markdown as soc2_md
        from .soc2.review import apply_decisions
        ex_data = json.loads(args.extraction_json.read_text(encoding="utf-8"))
        ctx = load_context(args.context)
        findings = apply_decisions(propose(ex_data, ctx, load_policy(args.policy)), args.decisions)
        _emit(soc2_md(ex_data, findings, ctx), args.out, len(findings))
    elif args.soc2_cmd == "decide":
        from .soc2.reliance import report_hash
        from .soc2.review import decide
        h = report_hash(json.loads(args.extraction_json.read_text(encoding="utf-8")))
        entry = decide(args.decisions, args.finding_id, args.decision, args.reviewer, h, args.note)
        print(json.dumps(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
