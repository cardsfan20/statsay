"""Command line.

    statsay check [PATH] [--base-ref REV | --base DIR] [--changed-only] [--baseline FILE]
                  [--format text|json|summary|sarif|agent|patch] [--sarif FILE] [--summary FILE]
    statsay baseline [PATH] [--output FILE]

`check` exit codes: 0 no new findings at or above --fail-on, 1 such findings
exist, 2 configuration or input error. `baseline` records the current findings
as reviewed (run it after the first audit).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from statsay import StatsayError, __version__
from statsay import baseline as baselines
from statsay.config import load_config
from statsay.engine import SEVERITY_ORDER, run
from statsay.outputs import render_agent, render_patch, render_sarif, render_summary
from statsay.report import render_json, render_text
from statsay.revisions import directory_reader, git_reader

FORMATS = ("text", "json", "summary", "sarif", "agent", "patch")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="statsay", description="Does your text say what your stats say?")
    parser.add_argument("--version", action="version", version=f"statsay {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check localized text against game data")
    _common(check)
    check.add_argument("--format", choices=FORMATS, default="text", help="what to print (default: text)")
    check.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                       help="lowest severity of a new finding that makes the exit code 1 (default: error)")
    check.add_argument("--changed-only", action="store_true",
                       help="diff mode: only report strings whose entity, watched fields or text changed")
    check.add_argument("--baseline", metavar="FILE", help="suppress findings recorded in this baseline")
    check.add_argument("--sarif", metavar="FILE", help="also write SARIF 2.1.0 to FILE")
    check.add_argument("--summary", metavar="FILE", help="also write the Markdown PR summary to FILE")

    record = commands.add_parser("baseline", help="record current findings as reviewed")
    _common(record)
    record.add_argument("--output", metavar="FILE",
                        help=f"baseline file (default: {baselines.DEFAULT_NAME} next to the config)")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # LF on Windows too, so patches apply
    try:
        config = load_config(args.path)
        reader = None
        if args.base_ref:
            reader = git_reader(config, args.base_ref)
        elif args.base:
            reader = directory_reader(config, args.base)
        result = run(config, base=reader)

        if args.command == "baseline":
            output = Path(args.output) if args.output else config.root / baselines.DEFAULT_NAME
            count = baselines.write(output, result.findings)
            print(f"statsay: recorded {count} findings in {output}")
            return

        if args.changed_only:
            if reader is None:
                raise StatsayError("--changed-only needs --base-ref or --base")
            result.findings = [f for f in result.findings if f.key in result.changed_keys]
        if args.baseline:
            result.findings, known = baselines.split(result.findings, baselines.load(Path(args.baseline)))
            result.stats["baselined"] = len(known)
    except StatsayError as error:
        print(f"statsay: error: {error}", file=sys.stderr)
        sys.exit(2)

    renderers = {
        "text": render_text, "json": render_json, "summary": render_summary, "sarif": render_sarif,
        "agent": render_agent, "patch": lambda r: render_patch(r, config.root),
    }
    sys.stdout.write(renderers[args.format](result))
    for path, renderer in ((args.sarif, render_sarif), (args.summary, render_summary)):
        if path:
            Path(path).write_text(renderer(result), encoding="utf-8", newline="\n")

    if args.fail_on != "never":
        threshold = SEVERITY_ORDER[args.fail_on]
        if any(SEVERITY_ORDER[f.severity] >= threshold for f in result.findings):
            sys.exit(1)


def _common(command):
    command.add_argument("path", nargs="?", default=".", help="statsay.yaml or a directory containing it")
    base = command.add_mutually_exclusive_group()
    base.add_argument("--base-ref", metavar="REV", help="diff mode: compare with this Git revision (e.g. origin/main)")
    base.add_argument("--base", metavar="DIR", help="diff mode: compare with a copy of the project in DIR")
