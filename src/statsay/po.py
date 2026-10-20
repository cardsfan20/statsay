"""Gettext PO: read entries with line numbers, and flag entries for review.

Reading: entries are joined to keys by their msgid (the source-language text),
since PO files have no keys of their own. Fuzzy, plural and context entries
are not used for claims.

Writing (opt-in): `flag` adds `#, fuzzy` and a `# statsay: ...` translator
comment to chosen entries. It only inserts or replaces comment lines; msgid
and msgstr are never edited, and every other line is kept byte for byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KEYWORD_RE = re.compile(r'^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+"(.*)"\s*$')
CONTINUATION_RE = re.compile(r'^"(.*)"\s*$')
COMMENT_PREFIX = "# statsay: "


@dataclass
class PoEntry:
    start: int                      # 0-based index of the entry's first line
    end: int                        # index after its last line
    flags: set[str] = field(default_factory=set)
    fields: dict[str, str] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)  # keyword -> 0-based line index

    @property
    def usable(self) -> bool:
        """A translated singular entry without context that the game would show."""
        return ("fuzzy" not in self.flags and "msgctxt" not in self.fields and "msgid_plural" not in self.fields
                and bool(self.fields.get("msgid")) and bool(self.fields.get("msgstr")))


def parse(text: str) -> list[PoEntry]:
    lines = text.split("\n")
    entries, current, keyword = [], None, None
    for index, line in enumerate(lines + [""]):
        if not line.strip():
            if current is not None:
                current.end = index
                entries.append(current)
            current, keyword = None, None
            continue
        if current is None:
            current = PoEntry(start=index, end=index)
        if line.startswith("#,"):
            current.flags.update(flag.strip() for flag in line[2:].split(","))
        elif line.startswith("#"):
            continue
        elif match := KEYWORD_RE.match(line):
            keyword = match.group(1)
            current.fields[keyword] = unescape(match.group(2))
            current.lines[keyword] = index
        elif (match := CONTINUATION_RE.match(line)) and keyword:
            current.fields[keyword] += unescape(match.group(1))
    return entries


def unescape(value: str) -> str:
    return re.sub(r'\\(["\\nt])', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), value)


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def flag(text: str, comments: dict[int, str]) -> tuple[str, int]:
    """Mark the entries whose msgstr is on these 0-based lines as fuzzy, with a comment.

    Returns the new text and how many entries changed. Running it twice changes nothing more.
    """
    lines = text.split("\n")
    cr = "\r" if "\r\n" in text else ""  # keep the file's line endings on inserted lines
    targets = {}
    for entry in parse(text):
        line = entry.lines.get("msgstr")
        if line in comments:
            targets[entry.start] = (entry, comments[line])
    changed = 0
    for start in sorted(targets, reverse=True):
        entry, comment = targets[start]
        block = lines[entry.start:entry.end]
        new_block = [l for l in block if not l.startswith(COMMENT_PREFIX)]
        flags_at = next((i for i, l in enumerate(new_block) if l.startswith("#,")), None)
        if flags_at is None:
            insert_at = next((i for i, l in enumerate(new_block) if not l.startswith("#")), len(new_block))
            new_block.insert(insert_at, "#, fuzzy" + cr)
        elif "fuzzy" not in {f.strip() for f in new_block[flags_at][2:].split(",")}:
            new_block[flags_at] = new_block[flags_at].rstrip() + ", fuzzy" + cr
        # Translator comments come first in a PO entry, before #. and #: lines.
        new_block.insert(0, COMMENT_PREFIX + comment.replace("\n", " ") + cr)
        if new_block != block:
            lines[entry.start:entry.end] = new_block
            changed += 1
    return "\n".join(lines), changed
