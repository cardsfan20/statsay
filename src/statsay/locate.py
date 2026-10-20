"""Map a claim's span in a string to its place in the source file, and build fixes.

A string's text appears in its file encoded: CSV may double quotes, JSON
escapes newlines and quotes. `locate` finds the encoded string in the file and
converts the span to file offsets and SARIF-style line/column (UTF-16 columns,
1-based). Suggested fixes replace a high-confidence numeric claim with the
data value, formatted like the original (full-width digits, digit grouping).
"""

from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass
from pathlib import Path

FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


@dataclass(frozen=True)
class Location:
    file: Path
    start: int          # character offsets in the file text
    end: int
    line: int
    column: int
    end_line: int
    end_column: int


class FileCache:
    def __init__(self):
        self._texts: dict[Path, str] = {}

    def text(self, path: Path) -> str:
        if path not in self._texts:
            self._texts[path] = path.read_text(encoding="utf-8")
        return self._texts[path]


def locate(cache: FileCache, file: Path, line: int | None, text: str, span: tuple[int, int]) -> Location | None:
    """Where `text[span[0]:span[1]]` sits in `file`; None if the string can't be found unambiguously."""
    content = cache.text(file)
    for encode in _encoders(file):
        encoded = encode(text)
        starts = _occurrences(content, encoded)
        if line is not None:  # CSV: the row's first line is known
            starts = [s for s in starts if content.count("\n", 0, s) + 1 in range(line, line + encoded.count("\n") + 1)]
        if len(starts) != 1:
            continue
        start = starts[0] + len(encode(text[:span[0]]))
        end = starts[0] + len(encode(text[:span[1]]))
        return Location(file, start, end, *_line_column(content, start), *_line_column(content, end))
    return None


def format_like(original: str, value) -> str:
    """`value` written the way `original` writes numbers (full-width digits, grouping)."""
    value = abs(value)
    separator = next((c for c in original if not c.isdigit() and c not in ".．"), None)
    if separator and isinstance(value, int):
        written = f"{value:,}".replace(",", separator)
    else:
        written = str(value)
    if any("０" <= c <= "９" for c in original):
        written = written.translate(FULLWIDTH)
    return written


def unified_patch(fixes: list[dict], cache: FileCache, root: Path) -> str:
    """One unified diff applying every fix, with paths relative to the working directory."""
    by_file: dict[Path, list[dict]] = {}
    for fix in fixes:
        by_file.setdefault(Path(fix["path"]), []).append(fix)
    chunks = []
    for path, file_fixes in sorted(by_file.items()):
        before = cache.text(path)
        after = before
        for fix in sorted(file_fixes, key=lambda f: f["offset"], reverse=True):
            after = after[:fix["offset"]] + fix["new"] + after[fix["offset"] + len(fix["old"]):]
        shown = _display(path, root)
        chunks.extend(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{shown}", tofile=f"b/{shown}",
        ))
    return "".join(chunks)


def _encoders(file: Path):
    if file.suffix.lower() == ".json":
        return (lambda s: json.dumps(s, ensure_ascii=False)[1:-1], lambda s: json.dumps(s)[1:-1])
    return (lambda s: s, lambda s: s.replace('"', '""'))


def _occurrences(content: str, needle: str) -> list[int]:
    found, start = [], content.find(needle)
    while needle and start != -1:
        found.append(start)
        start = content.find(needle, start + 1)
    return found


def _line_column(content: str, offset: int) -> tuple[int, int]:
    line_start = content.rfind("\n", 0, offset) + 1
    return content.count("\n", 0, offset) + 1, len(content[line_start:offset].encode("utf-16-le")) // 2 + 1


def _display(path: Path, root: Path) -> str:
    relative = os.path.relpath(path, Path.cwd())
    if relative.startswith(".."):
        relative = os.path.relpath(path, root)
    return Path(relative).as_posix()
