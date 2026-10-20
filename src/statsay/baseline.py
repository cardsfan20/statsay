"""Baselines: findings a reviewer has seen and accepted, suppressed on later runs.

The first run on a project is an audit: every finding is shown. After review,
`statsay baseline` records the remaining findings by fingerprint (what is
claimed where, not line numbers). Notes written into the file are kept when it
is regenerated, so reviewer dispositions persist across runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from statsay import StatsayError, __version__
from statsay.engine import Finding

DEFAULT_NAME = ".statsay-baseline.json"
SUMMARY_FIELDS = ("rule", "key", "locale", "field", "claimed", "actual")


def load(path: Path) -> dict[str, dict]:
    """Baseline entries by fingerprint."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise StatsayError(f"baseline not found: {path}") from None
    except json.JSONDecodeError as error:
        raise StatsayError(f"{path}: invalid JSON: {error}") from None
    entries = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise StatsayError(f"{path}: expected an object with a 'findings' list")
    return {entry["fingerprint"]: entry for entry in entries if isinstance(entry, dict) and "fingerprint" in entry}


def write(path: Path, findings: list[Finding]) -> int:
    """Write the baseline, keeping notes from an existing file. Returns the entry count."""
    path = Path(path)
    previous = load(path) if path.exists() else {}
    entries = {}
    for finding in findings:
        fingerprint = finding.fingerprint()
        entry = {"fingerprint": fingerprint, **{k: v for k, v in finding.to_dict().items() if k in SUMMARY_FIELDS}}
        entry["note"] = previous.get(fingerprint, {}).get("note", "")
        entries[fingerprint] = entry
    payload = {"tool": "statsay", "version": __version__,
               "findings": sorted(entries.values(), key=lambda e: (e.get("key", ""), e.get("locale") or "", e["rule"]))}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return len(entries)


def split(findings: list[Finding], baseline: dict[str, dict]) -> tuple[list[Finding], list[Finding]]:
    """(new findings, baselined findings)."""
    new, known = [], []
    for finding in findings:
        (known if finding.fingerprint() in baseline else new).append(finding)
    return new, known
