"""Command line.

  python -m tprm_assurance.cli register    <register.csv> <ap.csv>   [--policy policy.yaml] [--out report.md]
  python -m tprm_assurance.cli acceptances <acceptances.csv>         [--policy policy.yaml] [--out report.md]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .acceptance import run_acceptances, acceptances_to_markdown
from .register import run
from .report import to_markdown

ROOT = Path(__file__).resolve().parent.parent


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
        s.add_argument("--out", type=Path, help="write the Markdown report here instead of printing it")

    args = p.parse_args(argv)
    if args.command == "register":
        register, findings, policy = run(args.register_csv, args.ap_csv, args.policy)
        md = to_markdown(register, findings, policy)
    else:
        rows, findings, policy = run_acceptances(args.acceptances_csv, args.policy)
        md = acceptances_to_markdown(rows, findings, policy)

    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"{len(findings)} findings -> {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
