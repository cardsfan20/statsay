"""Command line: `statsay check [PATH] [--base DIR | --base-ref REV]`.

Exit codes: 0 no findings at or above --fail-on, 1 such findings exist,
2 configuration or input error.
"""

from __future__ import annotations

import argparse
import sys

from statsay import StatsayError, __version__
from statsay.config import load_config
from statsay.engine import SEVERITY_ORDER, run
from statsay.report import render_json, render_text
from statsay.revisions import directory_reader, git_reader


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="statsay", description="Does your text say what your stats say?")
    parser.add_argument("--version", action="version", version=f"statsay {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check localized text against game data")
    check.add_argument("path", nargs="?", default=".", help="statsay.yaml or a directory containing it")
    check.add_argument("--format", choices=["text", "json"], default="text")
    check.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                       help="lowest severity that makes the exit code 1 (default: error)")
    base = check.add_mutually_exclusive_group()
    base.add_argument("--base-ref", metavar="REV",
                      help="diff mode: compare with this Git revision (e.g. origin/main)")
    base.add_argument("--base", metavar="DIR",
                      help="diff mode: compare with a copy of the project in DIR")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.path)
        reader = None
        if args.base_ref:
            reader = git_reader(config, args.base_ref)
        elif args.base:
            reader = directory_reader(config, args.base)
        result = run(config, base=reader)
    except StatsayError as error:
        print(f"statsay: error: {error}", file=sys.stderr)
        sys.exit(2)

    output = render_json(result) if args.format == "json" else render_text(result)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(output)

    if args.fail_on != "never":
        threshold = SEVERITY_ORDER[args.fail_on]
        if any(SEVERITY_ORDER[f.severity] >= threshold for f in result.findings):
            sys.exit(1)
