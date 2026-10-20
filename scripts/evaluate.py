"""Run Statsay on a mutation fixture and every mutation, then score it.

Usage:
    python scripts/evaluate.py fixtures/toy-game

Each case runs twice: on the current revision alone, and in diff mode against
the clean fixture. Findings marked diff_only are expected only in diff mode.
Expected findings for rules not built yet count as out of scope. Exits 0 when
every planted in-scope bug is found (errors fail CI), and the clean fixture and
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
from statsay.revisions import directory_reader  # noqa: E402

RULES = {"value_mismatch", "locale_value_divergence", "unbound_claim", "enum_term_mismatch",
         "watched_field_changed"}
MODES = ("current", "diff")
IDENTITY = ("rule", "severity", "locale", "key", "field", "claimed", "actual", "value", "values", "old", "new")


def identity(finding):
    """The fields a finding is matched on; everything else (text, line) is ignored."""
    parts = []
    for name in IDENTITY:
        parts.append(_hashable(finding.get(name)))
    return tuple(parts)


def _hashable(value):
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    return value


def in_scope(expected, mode):
    return expected["rule"] in RULES and (mode == "diff" or not expected.get("diff_only"))


def run_on(directory, base_dir=None):
    config = load_config(directory)
    result = run(config, base=directory_reader(config, base_dir) if base_dir else None)
    coverage = [{"source": c.source, "rule": c.rule, "entities": c.entities, "bound": c.bound,
                 "unbound": list(c.unbound)} for c in result.coverage]
    return [finding.to_dict() for finding in result.findings], result.stats["checked"], coverage


def cases(fixture_dir):
    """Yield one dict per run: the clean fixture, then each mutation, in both modes.

    `expected` is the clean baseline plus the mutation's in-scope findings;
    `planted` is just the mutation's in-scope findings.
    """
    root = Path(fixture_dir)
    clean = json.loads((root / "expected" / "clean.json").read_text(encoding="utf-8"))
    baseline = Counter(identity(f) for f in clean["findings"])

    for mode in MODES:
        actual, checked, coverage = run_on(root, root if mode == "diff" else None)
        yield dict(id="clean", mode=mode, category="clean", expected=baseline, planted=Counter(),
                   out_of_scope=0, actual=actual, checked=checked,
                   coverage=coverage, expected_coverage=clean["coverage"])

    for mutation in fixture.load_mutations(root):
        with tempfile.TemporaryDirectory() as tmp:
            head = Path(tmp) / mutation["id"]
            fixture.materialize(root, mutation, head)
            for mode in MODES:
                planted = Counter(identity(f) for f in mutation["expected"] if in_scope(f, mode))
                actual, checked, _ = run_on(head, root if mode == "diff" else None)
                yield dict(id=mutation["id"], mode=mode, category=mutation["category"],
                           expected=baseline + planted, planted=planted,
                           out_of_scope=sum(1 for f in mutation["expected"] if not in_scope(f, mode)),
                           actual=actual, checked=checked)


def score(case):
    """Compare one run with its expectation."""
    actual_ids = Counter(identity(f) for f in case["actual"])
    expected = case["expected"]
    fails_ci = any(f["severity"] == "error" for f in case["actual"])
    problems = []
    if any(item[1] == "error" for item in case["planted"]) and not fails_ci:
        problems.append("planted bug did not fail CI")
    if "expected_coverage" in case and case["coverage"] != case["expected_coverage"]:
        problems.append(f"coverage {case['coverage']} != expected {case['expected_coverage']}")
    return dict(found=expected & actual_ids, missed=expected - actual_ids, extra=actual_ids - expected,
                fails_ci=fails_ci, problems=problems)


def evaluate(fixture_dir):
    rows, per_rule = [], {rule: Counter() for rule in sorted(RULES)}
    total_checked, unexpected_alerts, failures = 0, 0, []

    for case in cases(fixture_dir):
        result = score(case)
        # Baseline findings count as true positives once per mode, in the clean run, not per mutation.
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
        failures.extend(f"{case['id']} ({case['mode']}): {problem}" for problem in problems)

        rows.append((case["id"], case["mode"], case["category"], sum(result["found"].values()),
                     sum(result["missed"].values()), sum(result["extra"].values()),
                     case["out_of_scope"], "yes" if result["fails_ci"] else "no"))

    return rows, per_rule, total_checked, unexpected_alerts, failures


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        sys.exit(2)
    fixture_dir = sys.argv[1]
    rows, per_rule, total_checked, alerts, failures = evaluate(fixture_dir)

    print("| Case | Mode | Category | Found | Missed | Unexpected | Out of scope | Fails CI |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
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
        print("\nFAIL")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)
    print("\nPASS: every planted bug found, no unexpected findings")


if __name__ == "__main__":
    main()
