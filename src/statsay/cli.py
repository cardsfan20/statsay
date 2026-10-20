"""Command line.

    statsay check [PATH] [--base-ref REV | --base DIR] [--changed-only] [--baseline FILE]
                  [--format text|json|summary|sarif|agent|patch] [--sarif FILE] [--summary FILE]
    statsay baseline [PATH] [--output FILE]
    statsay flag [PATH] [--base-ref REV | --base DIR] [--changed-only] [--baseline FILE] [--review-file FILE]
    statsay init [DIR] [--output FILE] [--force]

`check` exit codes: 0 no new findings at or above --fail-on, 1 such findings
exist, 2 configuration or input error. `baseline` records the current findings
as reviewed (run it after the first audit). `flag` is opt-in write-back: it
marks affected PO entries fuzzy with a comment and lists other findings in a
review file; it never edits translated text. `init` looks at a project and
writes a starter statsay.yaml, then runs a first check.
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
from statsay.writeback import REVIEW_NAME, write_back

FORMATS = ("text", "json", "summary", "sarif", "agent", "patch")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="statsay", description="Does your text say what your stats say?")
    parser.add_argument("--version", action="version", version=f"statsay {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check localized text against game data")
    _common(check)
    _filters(check)
    check.add_argument("--format", choices=FORMATS, default="text", help="what to print (default: text)")
    check.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                       help="lowest severity of a new finding that makes the exit code 1 (default: error)")
    check.add_argument("--sarif", metavar="FILE", help="also write SARIF 2.1.0 to FILE")
    check.add_argument("--summary", metavar="FILE", help="also write the Markdown PR summary to FILE")

    record = commands.add_parser("baseline", help="record current findings as reviewed")
    _common(record)
    record.add_argument("--output", metavar="FILE",
                        help=f"baseline file (default: {baselines.DEFAULT_NAME} next to the config)")

    flag = commands.add_parser("flag", help="opt-in write-back: mark affected translations for review")
    _common(flag)
    _filters(flag)
    flag.add_argument("--review-file", metavar="FILE",
                      help=f"sidecar for non-PO findings (default: {REVIEW_NAME} next to the config)")
    start = commands.add_parser("init", help="write a starter statsay.yaml for a project")
    start.add_argument("path", nargs="?", default=".", help="project directory")
    start.add_argument("--output", metavar="FILE", help="where to write (default: statsay.yaml in the project)")
    start.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # LF on Windows too, so patches apply
    if args.command == "init":
        _init(args)
        return

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

        if args.command == "flag":
            review = Path(args.review_file) if args.review_file else config.root / REVIEW_NAME
            flagged, listed = write_back(result.findings, review)
            print(f"statsay: flagged {flagged} PO entries as fuzzy"
                  + (f"; listed {listed} other findings in {review}" if listed else ""))
            return
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


def _init(args) -> None:
    from statsay.init import init, render
    from statsay.report import summary

    try:
        output = Path(args.output) if args.output else Path(args.path) / "statsay.yaml"
        if output.exists() and not args.force:
            raise StatsayError(f"{output} already exists (use --force to overwrite)")
        plan = init(Path(args.path))
        output.write_text(render(plan), encoding="utf-8", newline="\n")
        result = run(load_config(output))
    except StatsayError as error:
        print(f"statsay: error: {error}", file=sys.stderr)
        sys.exit(2)
    print(f"statsay init: {plan.kind}; locales: {', '.join(plan.locales)}")
    for note in plan.notes:
        print(f"  {note}")
    for name, anchors in plan.anchors.items():
        print(f"  field {name}: anchors {', '.join(anchors) if anchors else '(none found)'}")
    for name, claim in plan.raw["claims"].items():
        if claim["kind"] == "enum":
            print(f"  terms {name}: {sum(len(t) for v in claim['vocabulary'].values() for t in v.values())} "
                  f"in the vocabulary")
    counts = summary(result)
    print(f"wrote {output}")
    print(f"first check: {counts['error']} errors, {counts['warning']} warnings, {counts['info']} info "
          f"on {result.stats['checked']} strings. Next: `statsay check --format summary` to review.")


def _filters(command):
    command.add_argument("--changed-only", action="store_true",
                         help="diff mode: only strings whose entity, watched fields or text changed")
    command.add_argument("--baseline", metavar="FILE", help="suppress findings recorded in this baseline")


def _common(command):
    command.add_argument("path", nargs="?", default=".", help="statsay.yaml or a directory containing it")
    base = command.add_mutually_exclusive_group()
    base.add_argument("--base-ref", metavar="REV", help="diff mode: compare with this Git revision (e.g. origin/main)")
    base.add_argument("--base", metavar="DIR", help="diff mode: compare with a copy of the project in DIR")
