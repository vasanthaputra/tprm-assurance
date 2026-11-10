"""Command line.

  python -m tprm_assurance.cli register    <register.csv> <ap.csv>        [--policy P] [--out F]
  python -m tprm_assurance.cli acceptances <acceptances.csv>              [--policy P] [--out F]
  python -m tprm_assurance.cli soc2 extract <report.pdf> --out extraction.json [--extractor rules|anthropic]
  python -m tprm_assurance.cli soc2 prompt  <report.pdf> --out prompt.txt       (copy-paste path, no API key)
  python -m tprm_assurance.cli soc2 review  <extraction.json> --context ctx.yaml [--decisions log.jsonl] [--out F]
  python -m tprm_assurance.cli soc2 score   <extraction.json> --truth answer_key.json [--out F]
  python -m tprm_assurance.cli demo [--out-dir out]
  python -m tprm_assurance.cli soc2 decide  <extraction.json> <finding_id> approve|reject --reviewer NAME [--note ...] [--decisions log.jsonl]
  python -m tprm_assurance.cli soc2 conflicts <a.json> <b.json> [--resolutions log.jsonl] [--out F]   (two extractions of one report)
  python -m tprm_assurance.cli soc2 resolve   <a.json> <b.json> <conflict_id> a|b|manual --reviewer NAME [--value JSON] [--note ...]
  python -m tprm_assurance.cli soc2 merge     <a.json> <b.json> --out merged.json   (refused while the gate is blocked)
  python -m tprm_assurance.cli soc2 jev-check <a.json> <b.json> --pdf report.pdf [--out suggestions.json]   (needs TYPESAFE_API_KEY)
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

    demo = sub.add_parser("demo", help="run every check on the sample data and write reports to out/")
    demo.add_argument("--out-dir", type=Path, default=Path("out"))

    soc = sub.add_parser("soc2", help="SOC 2 reliance review").add_subparsers(dest="soc2_cmd", required=True)
    sc = soc.add_parser("score", help="score an extraction against hand-verified ground truth (module 4)")
    sc.add_argument("extraction_json", type=Path)
    sc.add_argument("--truth", type=Path, required=True, help="answer key for this report (data/sample/sample_soc2_truth.json for the sample)")
    sc.add_argument("--out", type=Path)
    ex = soc.add_parser("extract")
    ex.add_argument("pdf", type=Path)
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--extractor", choices=["rules", "anthropic", "anthropic-text"], default="rules",
                    help="anthropic = send the PDF to Claude; anthropic-text = send the extracted page text")
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
    cf = soc.add_parser("conflicts", help="list where two extractions of the same report disagree")
    rs = soc.add_parser("resolve", help="resolve one conflict: take A, take B, or type the value from the report")
    mg = soc.add_parser("merge", help="build one extraction from the pair; refused while the gate is blocked")
    jc = soc.add_parser("jev-check", help="ask Jev which reading the cited page supports (advice only)")
    jc.add_argument("--pdf", type=Path, required=True, help="the report both extractions were read from")
    jc.add_argument("--out", type=Path, default=Path("suggestions.json"))
    jc.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
    cf.add_argument("--suggestions", type=Path, help="suggestions.json from soc2 jev-check, shown as a column")
    for s in (cf, rs, mg, jc):
        s.add_argument("a_json", type=Path, help="extraction A (usually the rules extractor)")
        s.add_argument("b_json", type=Path, help="extraction B (e.g. the copy-paste AI reply)")
        s.add_argument("--resolutions", type=Path, default=Path("conflicts.jsonl"))
    rs.add_argument("conflict_id")
    rs.add_argument("choice", choices=["a", "b", "manual"])
    rs.add_argument("--reviewer", required=True)
    rs.add_argument("--value", help="JSON value for a manual resolution, e.g. 12 or '[\"Security\"]'")
    rs.add_argument("--note", default="")
    for s in (cf, mg):
        s.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
    cf.add_argument("--out", type=Path)
    mg.add_argument("--out", type=Path, required=True)

    args = p.parse_args(argv)

    if args.command == "register":
        register, findings, policy = run(args.register_csv, args.ap_csv, args.policy)
        _emit(to_markdown(register, findings, policy), args.out, len(findings))
    elif args.command == "acceptances":
        rows, findings, policy = run_acceptances(args.acceptances_csv, args.policy)
        _emit(acceptances_to_markdown(rows, findings, policy), args.out, len(findings))
    elif args.command == "demo":
        from .soc2.reliance import load_context, propose, to_markdown as soc2_md
        from .soc2.review import apply_decisions
        d = args.out_dir; d.mkdir(parents=True, exist_ok=True)
        s = ROOT / "data" / "sample"; pol = ROOT / "policy.yaml"
        register, f1, policy = run(s / "vendor_register.csv", s / "ap_vendors.csv", pol)
        (d / "register_review.md").write_text(to_markdown(register, f1, policy), encoding="utf-8")
        rows, f2, policy = run_acceptances(s / "risk_acceptances.csv", pol)
        (d / "acceptance_review.md").write_text(acceptances_to_markdown(rows, f2, policy), encoding="utf-8")
        ex_data = json.loads((ROOT / "data" / "sample" / "sample_soc2_extraction.json").read_text(encoding="utf-8"))
        ctx = load_context(s / "soc2_context.yaml")
        f3 = apply_decisions(propose(ex_data, ctx, load_policy(pol)), d / "decisions.jsonl")
        (d / "soc2_review.md").write_text(soc2_md(ex_data, f3, ctx), encoding="utf-8")
        print(f"register: {len(f1)} findings, acceptances: {len(f2)}, soc2: {len(f3)} proposed -> {d}/")
    elif args.soc2_cmd == "score":
        from .soc2.evaluate import run as score_run, summary, to_markdown as score_md
        checks, ex_data = score_run(args.extraction_json, args.truth)
        ok, total = summary(checks)
        md = score_md(checks, ex_data, args.truth)
        if args.out:
            args.out.write_text(md, encoding="utf-8")
            print(f"{ok}/{total} fields correct -> {args.out}")
        else:
            print(md)
    elif args.soc2_cmd == "extract":
        if args.extractor.startswith("anthropic"):
            from .soc2.llm import run_anthropic
            data, meta = run_anthropic(args.pdf, "text" if args.extractor == "anthropic-text" else "pdf")
            meta_path = args.out.with_suffix(".meta.json")
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            print(f"{meta['input_tokens']} in / {meta['output_tokens']} out tokens, ~${meta['estimated_cost_usd']} -> {meta_path}")
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
    elif args.soc2_cmd in ("conflicts", "resolve", "merge", "jev-check"):
        from .soc2 import conflicts as cq
        a = json.loads(args.a_json.read_text(encoding="utf-8"))
        b = json.loads(args.b_json.read_text(encoding="utf-8"))
        if args.soc2_cmd == "conflicts":
            gate = cq.gate_severity(load_policy(args.policy))
            found = cq.apply_resolutions(cq.find_conflicts(a, b), args.resolutions)
            sug = None
            if args.suggestions:
                from .soc2.jev_check import load_suggestions
                sug = load_suggestions(args.suggestions, cq.pair_hash(a, b))
            _emit(cq.to_markdown(a, b, found, gate, sug), args.out, len(found))
        elif args.soc2_cmd == "jev-check":
            from .soc2.extract import read_pages
            from .soc2.jev_check import check, describe, make_client
            found = [c for c in cq.apply_resolutions(cq.find_conflicts(a, b), args.resolutions) if c.status == "OPEN"]
            sug = check(found, a, b, read_pages(args.pdf), make_client(), load_policy(args.policy))
            args.out.write_text(json.dumps([s.to_record() for s in sug], indent=2), encoding="utf-8")
            for s in sug:
                print(f"{s.conflict_id}: {describe(s.to_record())}")
            print(f"{len(sug)} open conflicts checked -> {args.out}  (show them: soc2 conflicts ... --suggestions {args.out})")
        elif args.soc2_cmd == "resolve":
            value = json.loads(args.value) if args.value is not None else None
            print(json.dumps(cq.resolve(args.resolutions, a, b, args.conflict_id, args.choice,
                                        args.reviewer, value, args.note)))
        else:
            try:
                merged = cq.merge(a, b, args.resolutions, load_policy(args.policy))
            except cq.GateBlocked as e:
                print(f"merge refused: {e}")
                return 2
            args.out.write_text(json.dumps(merged, indent=2), encoding="utf-8")
            print(f"merged ({len(merged['_merge']['resolved'])} resolved, {len(merged['_merge']['open'])} open below "
                  f"gate {merged['_merge']['gate']}) -> {args.out}  (next: soc2 review {args.out} --context ...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
