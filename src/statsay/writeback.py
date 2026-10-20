"""Opt-in translator write-back: flag affected translations, never edit them.

- PO files: the entry gets `#, fuzzy` and a `# statsay: ...` comment naming the
  rule and values, so translators see it in their usual tools.
- Everything else (CSV, JSON data): a review sidecar file listing the findings.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from statsay import __version__, po
from statsay.engine import INFO, Finding

REVIEW_NAME = "statsay-review.json"


def write_back(findings: list[Finding], review_path: Path) -> tuple[int, int]:
    """Flag PO entries and write the sidecar. Returns (PO entries flagged, sidecar entries)."""
    by_po: dict[Path, dict[int, str]] = defaultdict(dict)
    sidecar = []
    for f in findings:
        if f.severity == INFO:
            continue
        if f.source is not None and f.source.suffix.lower() == ".po" and f.locale and f.line:
            by_po[f.source][f.line - 1] = f"{f.rule}: {f.message}"
        else:
            sidecar.append({k: v for k, v in f.to_dict().items()
                            if k in ("rule", "severity", "key", "locale", "field", "claimed", "actual",
                                     "old", "new", "values", "file", "line", "message", "text")})
    flagged = 0
    for path, comments in by_po.items():
        text = path.read_text(encoding="utf-8")
        new_text, changed = po.flag(text, comments)
        if changed:
            path.write_text(new_text, encoding="utf-8", newline="\n")
            flagged += changed
    if sidecar:
        payload = {"tool": "statsay", "version": __version__, "review": sidecar}
        Path(review_path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8", newline="\n")
    return flagged, len(sidecar)
