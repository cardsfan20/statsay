"""Render a run's result as text or JSON."""

from __future__ import annotations

import json

from statsay import __version__
from statsay.engine import ERROR, INFO, WARNING, Result


def summary(result: Result) -> dict[str, int]:
    counts = {ERROR: 0, WARNING: 0, INFO: 0}
    for finding in result.findings:
        counts[finding.severity] += 1
    return counts


def render_json(result: Result) -> str:
    payload = {
        "tool": "statsay",
        "version": __version__,
        "stats": result.stats,
        "coverage": [
            {"source": c.source, "rule": c.rule, "entities": c.entities, "bound": c.bound,
             "unbound": list(c.unbound)}
            for c in result.coverage
        ],
        "findings": [finding.to_dict() for finding in result.findings],
        "diagnostics": result.diagnostics,
        "summary": summary(result),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_text(result: Result) -> str:
    lines = []
    for c in result.coverage:
        line = f"coverage  {c.rule}: {c.bound} of {c.entities} {c.source} bound"
        if c.unbound:
            line += f"; unbound: {', '.join(ref.split('.', 1)[1] for ref in c.unbound)}"
        lines.append(line)
    for diagnostic in result.diagnostics:
        lines.append(f"note      {diagnostic}")
    if lines:
        lines.append("")

    for f in result.findings:
        where = (f"{f.file}:{f.line}" if f.line else f.file) if f.file else f.key
        locale = f.locale or "*"
        lines.append(f"{where}  {f.severity.upper():<7} {f.rule}  {locale}  {f.key}")
        lines.append(f"    {f.message}")
        if f.text:
            lines.append(f"    \"{f.text}\"")

    counts = summary(result)
    if result.findings:
        lines.append("")
    lines.append(
        f"{counts[ERROR]} errors, {counts[WARNING]} warnings, {counts[INFO]} info "
        f"({result.stats['checked']} bound strings checked)"
    )
    return "\n".join(lines) + "\n"
