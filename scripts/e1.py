"""Evaluation E1: run Statsay on a fixture and every mutation, then score it.

Usage:
    python scripts/e1.py fixtures/toy-game

Only M1 rules are scored. Expected findings for later rules (enum_term_mismatch)
and diff-only findings are counted as out of scope. Exits 0 when Gate 1 holds:
every planted in-scope bug is found and fails CI, and the clean fixture and
negative controls produce no unexpected findings.
"""

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture  # noqa: E402  (scripts/fixture.py)

from statsay.config import load_config  # noqa: E402
from statsay.engine import run  # noqa: E402

M1_RULES = {"value_mismatch", "locale_value_divergence", "unbound_claim"}
IDENTITY = ("rule", "severity", "locale", "key", "field", "claimed", "actual", "value", "values")


def identity(finding):
    """The fields a finding is matched on; everything else (text, line) is ignored."""
    parts = []
    for name in IDENTITY:
        value = finding.get(name)
        if isinstance(value, dict):
            value = tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in value.items()))
        parts.append(value)
    return tuple(parts)


def in_scope(expected):
    return expected["rule"] in M1_RULES and not expected.get("diff_only")


def run_on(directory):
    result = run(load_config(directory))
    return [finding.to_dict() for finding in result.findings], result.stats["checked"]


def cases(fixture_dir):
    """Yield one dict per run: the clean fixture, then each mutation.

    `expected` is the clean baseline plus the mutation's in-scope findings;
    `planted` is just the mutation's in-scope findings.
    """
    root = Path(fixture_dir)
    clean = json.loads((root / "expected" / "clean.json").read_text(encoding="utf-8"))["findings"]
    baseline = Counter(identity(f) for f in clean)

    actual, checked = run_on(root)
    yield dict(id="clean", category="clean", expected=baseline, planted=Counter(),
               out_of_scope=0, actual=actual, checked=checked)

    for mutation in fixture.load_mutations(root):
        planted = Counter(identity(f) for f in mutation["expected"] if in_scope(f))
        with tempfile.TemporaryDirectory() as tmp:
            fixture.materialize(root, mutation, Path(tmp) / mutation["id"])
            actual, checked = run_on(Path(tmp) / mutation["id"])
        yield dict(id=mutation["id"], category=mutation["category"], expected=baseline + planted,
                   planted=planted, out_of_scope=sum(1 for f in mutation["expected"] if not in_scope(f)),
                   actual=actual, checked=checked)


def score(case):
    """Compare one run with its expectation."""
    actual_ids = Counter(identity(f) for f in case["actual"])
    expected = case["expected"]
    fails_ci = any(f["severity"] == "error" for f in case["actual"])
    problems = []
    if any(item[1] == "error" for item in case["planted"]) and not fails_ci:
        problems.append("planted bug did not fail CI")
    return dict(found=expected & actual_ids, missed=expected - actual_ids, extra=actual_ids - expected,
                fails_ci=fails_ci, problems=problems)


def evaluate(fixture_dir):
    rows, per_rule = [], {rule: Counter() for rule in sorted(M1_RULES)}
    total_checked, unexpected_alerts, failures = 0, 0, []

    for case in cases(fixture_dir):
        result = score(case)
        # Baseline findings count as true positives once, in the clean run, not again per mutation.
        true_positives = result["found"] if case["id"] == "clean" else result["found"] & case["planted"]
        for counter, name in ((true_positives, "tp"), (result["missed"], "fn"), (result["extra"], "fp")):
            for item, count in counter.items():
                per_rule.setdefault(item[0], Counter())[name] += count
        total_checked += case["checked"]
        unexpected_alerts += sum(n for item, n in result["extra"].items() if item[1] in ("error", "warning"))

        problems = list(result["problems"])
        if result["missed"]:
            problems.append(f"{sum(result['missed'].values())} expected finding(s) missed")
        if result["extra"]:
            problems.append(f"{sum(result['extra'].values())} unexpected finding(s)")
        failures.extend(f"{case['id']}: {problem}" for problem in problems)

        rows.append((case["id"], case["category"], sum(result["found"].values()),
                     sum(result["missed"].values()), sum(result["extra"].values()),
                     case["out_of_scope"], "yes" if result["fails_ci"] else "no"))

    return rows, per_rule, total_checked, unexpected_alerts, failures


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        sys.exit(2)
    fixture_dir = sys.argv[1]
    rows, per_rule, total_checked, alerts, failures = evaluate(fixture_dir)

    print("| Case | Category | Found | Missed | Unexpected | Out of scope | Fails CI |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print("| " + " | ".join(str(cell) for cell in row) + " |")

    print("\n| Rule | TP | FP | FN | Precision | Recall |")
    print("| --- | --- | --- | --- | --- | --- |")
    for rule, counts in per_rule.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = f"{tp / (tp + fp):.2f}" if tp + fp else "n/a"
        recall = f"{tp / (tp + fn):.2f}" if tp + fn else "n/a"
        print(f"| {rule} | {tp} | {fp} | {fn} | {precision} | {recall} |")

    rate = 1000 * alerts / total_checked if total_checked else 0.0
    print(f"\nUnexpected errors/warnings: {alerts} across {total_checked} bound strings checked "
          f"({rate:.1f} per 1,000)")
    if failures:
        print("\nGate 1: NOT MET")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("\nGate 1: met (all planted in-scope bugs fail CI; no unexpected findings)")


if __name__ == "__main__":
    main()
