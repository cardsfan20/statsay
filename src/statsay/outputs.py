"""CI and agent outputs: PR summary (Markdown), SARIF 2.1.0, agent lines, patch."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from statsay import __version__
from statsay.engine import ERROR, INFO, WARNING, Finding, Result
from statsay.locate import FileCache, unified_patch

RULE_HELP = {
    "value_mismatch": "Text states a number that differs from the game data.",
    "enum_term_mismatch": "Text names a value (a term) that the game data does not have.",
    "locale_value_divergence": "Locales state different values for the same field.",
    "watched_field_changed": "A watched field changed, but this text did not and states no value for it.",
    "unbound_claim": "A number in a bound string is not tied to any watched field.",
}
SARIF_LEVEL = {ERROR: "error", WARNING: "warning", INFO: "note"}
ICON = {ERROR: "🛑", WARNING: "⚠️", INFO: "ℹ️"}
MAX_GROUPS = 50
EXCERPT = 110


def render_summary(result: Result) -> str:
    """Markdown for a PR comment: findings grouped by what is claimed, identical texts merged."""
    counts = {s: sum(1 for f in result.findings if f.severity == s) for s in (ERROR, WARNING, INFO)}
    title = "✅ Statsay: no contradictions found" if not counts[ERROR] + counts[WARNING] else (
        f"Statsay: {counts[ERROR]} error{'s' * (counts[ERROR] != 1)}, "
        f"{counts[WARNING]} warning{'s' * (counts[WARNING] != 1)}")
    lines = [f"### {title}", ""]

    groups: dict[tuple, list[Finding]] = defaultdict(list)
    for f in result.findings:
        if f.severity != INFO:
            change = result.changes.get(f.key, {}).get(f.field or "")
            groups[(SEVERITY_RANK[f.severity], f.rule, f.field, _hashable(f.claimed), _hashable(f.actual),
                    _hashable(f.old), _hashable(f.new), _hashable(f.values), _hashable(change))].append(f)
    ordered = sorted(groups.items(), key=lambda item: (item[0][0], item[0][1], item[1][0].key))
    for (_, rule, *_), members in ordered[:MAX_GROUPS]:
        first = members[0]
        lines.append(f"- {ICON[first.severity]} **{rule}** · {_headline(members, result)}")
        by_text: dict[tuple, list[Finding]] = defaultdict(list)
        for f in members:
            by_text[(f.locale, f.text)].append(f)
        for (locale, text), same in by_text.items():
            keys = sorted({f.key for f in same})
            where = f"`{keys[0]}`" if len(keys) == 1 else f"{len(keys)} strings with the same text: " + ", ".join(
                f"`{k}`" for k in keys[:6]) + (" …" if len(keys) > 6 else "")
            excerpt = f" “{_excerpt(text, same[0].span)}”" if text else ""
            fix = f" → suggest `{same[0].fix['new']}`" if same[0].fix else ""
            lines.append(f"  - {locale or 'all locales'} {where}{excerpt}{fix}")
    if len(ordered) > MAX_GROUPS:
        lines.append(f"- … and {len(ordered) - MAX_GROUPS} more groups (see the full report)")

    lines.append("")
    coverage = "; ".join(f"`{c.rule}` {c.bound}/{c.entities} bound" for c in result.coverage)
    lines.append(f"<sub>{result.stats['checked']} bound strings checked · coverage: {coverage}"
                 f"{f' · {counts[INFO]} info notes' if counts[INFO] else ''}</sub>")
    return "\n".join(lines) + "\n"


def render_sarif(result: Result) -> str:
    rules = sorted({f.rule for f in result.findings} | set(RULE_HELP))
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "statsay", "version": __version__,
                "informationUri": "https://github.com/cardsfan20/statsay",
                "rules": [{"id": rule, "shortDescription": {"text": RULE_HELP.get(rule, rule)}} for rule in rules],
            }},
            "columnKind": "utf16CodeUnits",
            "results": [_sarif_result(f) for f in result.findings],
        }],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_agent(result: Result) -> str:
    """Short, machine-readable lines for coding agents, grouped by entity and field."""
    groups: dict[tuple, list[Finding]] = defaultdict(list)
    for f in result.findings:
        if f.severity != INFO:
            groups[(f.entity, f.field or "")].append(f)
    lines = []
    for (entity, field_name), members in sorted(groups.items()):
        change = result.changes.get(members[0].key, {}).get(field_name)
        if change:
            lines.append(f"{entity}.{field_name} {_plain(change[0])} -> {_plain(change[1])}")
        else:
            lines.append(f"{entity}.{field_name}" if field_name else entity)
        for f in members:
            lines.append(f"  {f.severity.upper():<7} {f.rule} {f.locale or '*'} {f.key}"
                         + (f' "{_excerpt(f.text, f.span)}"' if f.text else f" {json.dumps(f.values, ensure_ascii=False)}"))
            if f.fix:
                lines.append(f"  FIX     {f.locale} {f.key} [{f.span[0]},{f.span[1]}] "
                             f'"{f.text[f.span[0]:f.span[1]]}" -> "{f.fix["new"]}"')
    if not lines:
        lines.append("OK no contradictions")
    return "\n".join(lines) + "\n"


def render_patch(result: Result, root: Path) -> str:
    fixes = [f.fix for f in result.findings if f.fix]
    return unified_patch(fixes, FileCache(), root)


SEVERITY_RANK = {ERROR: 0, WARNING: 1, INFO: 2}


def _sarif_result(f: Finding) -> dict:
    out = {
        "ruleId": f.rule,
        "level": SARIF_LEVEL[f.severity],
        "message": {"text": f"{f.key} ({f.locale or 'all locales'}): {f.message}"},
        "partialFingerprints": {"statsay/v1": f.fingerprint()},
        "properties": {k: v for k, v in f.to_dict().items()
                       if k in ("key", "entity", "locale", "field", "claimed", "actual", "old", "new", "values")},
    }
    if f.file:
        region = {"startLine": f.line} if f.line else {}
        if f.line and f.column and f.span:
            region["startColumn"] = f.column
            if f.fix:
                region.update(endLine=f.fix["end_line"], endColumn=f.fix["end_column"])
        location = {"artifactLocation": {"uri": f.file}}
        if region:
            location["region"] = region
        out["locations"] = [{"physicalLocation": location}]
    if f.fix:
        out["fixes"] = [{
            "description": {"text": f"Replace {f.fix['old']} with {f.fix['new']} to match the data"},
            "artifactChanges": [{
                "artifactLocation": {"uri": f.fix["file"]},
                "replacements": [{
                    "deletedRegion": {"startLine": f.fix["line"], "startColumn": f.fix["column"],
                                      "endLine": f.fix["end_line"], "endColumn": f.fix["end_column"]},
                    "insertedContent": {"text": f.fix["new"]},
                }],
            }],
        }]
    return out


def _headline(members: list[Finding], result: Result) -> str:
    """One line for a group: who (one entity, or how many) and what is claimed against what."""
    f = members[0]
    entities = sorted({m.entity for m in members})
    who = f"`{entities[0]}` " if len(entities) == 1 else f"{len(entities)} entities, "
    if f.rule in ("value_mismatch", "enum_term_mismatch"):
        change = result.changes.get(f.key, {}).get(f.field or "")
        data = f"data {_plain(change[0])} → {_plain(change[1])}" if change else f"data says {_plain(f.actual)}"
        return f"{who}**{f.field}**: text says {_plain(f.claimed)}, {data}"
    if f.rule == "watched_field_changed":
        return f"{who}**{f.field}** {_plain(f.old)} → {_plain(f.new)}; text unchanged and states no value"
    if f.rule == "locale_value_divergence":
        listed = ", ".join(f"{locale} {_plain(value)}" for locale, value in (f.values or {}).items())
        return f"{who}**{f.field}**: locales disagree ({listed})"
    return f"{who}{f.message}"


def _excerpt(text: str, span: tuple[int, int] | None = None) -> str:
    """Whitespace-flattened text, cut to EXCERPT characters around `span` when given."""
    if len(text) <= EXCERPT:
        return " ".join(text.split())
    start = max(0, min(span[0] - EXCERPT // 3, len(text) - EXCERPT)) if span else 0
    window = " ".join(text[start:start + EXCERPT].split())
    return ("…" if start else "") + window + ("…" if start + EXCERPT < len(text) else "")


def _plain(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_plain(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "none" if value is None else str(value)


def _hashable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (list, dict)) else value
