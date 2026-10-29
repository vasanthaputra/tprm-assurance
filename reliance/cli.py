"""Command line: python -m reliance.cli register <register.csv> <ap.csv> [--policy policy.yaml] [--out report.md]"""
from __future__ import annotations

import argparse
from pathlib import Path

from .register import run
from .report import to_markdown

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reliance")
    sub = p.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="check a vendor register against policy")
    reg.add_argument("register_csv", type=Path)
    reg.add_argument("ap_csv", type=Path)
    reg.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
    reg.add_argument("--out", type=Path, help="write the Markdown report here instead of printing it")
    args = p.parse_args(argv)

    register, findings, policy = run(args.register_csv, args.ap_csv, args.policy)
    md = to_markdown(register, findings, policy)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"{len(findings)} findings -> {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
