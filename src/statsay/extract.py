"""Find numbers in a string and tie them to watched fields.

Implements the spec's fixed extraction-confidence rule:

- High: an anchor term of exactly one field is nearest to the number, in the
  same clause, with no other number in between; or the string has exactly one
  number and the entity exactly one numeric watched field.
- Low: the nearest anchors belong to two fields (a tie), or the number is part
  of a range ("10-20") or a multiplier ("x2").
- Unassigned: no anchor qualifies. These become `unbound_claim` findings.

Text is NFKC-normalized first, so full-width digits and signs read as ASCII.
Values are unsigned; direction ("raises", "-10%") is not interpreted yet.
"""

from __future__ import annotations

import math
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache

HIGH = "high"
LOW = "low"

NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
RANGE_BEFORE_RE = re.compile(r"\d\s*[-–—~〜]\s*$")
RANGE_AFTER_RE = re.compile(r"^\s*[-–—~〜]\s*\d")
MULTIPLIER_BEFORE_RE = re.compile(r"(?<![A-Za-z])[xX×]\s?$")
MULTIPLIER_AFTER_RE = re.compile(r"^\s?[xX×](?![A-Za-z])")
CLAUSE_BREAKS = set("。！？；、!?;\n")
DIGIT_JOINERS = set(".,")  # clause breaks, except between two digits ("1.5", "1,000")


@dataclass(frozen=True)
class Claim:
    value: int | float
    span: tuple[int, int]     # offsets in the original, unnormalized text
    fields: tuple[str, ...]   # empty: unassigned; one: assigned; several: tie
    confidence: str | None    # HIGH, LOW, or None when unassigned

    @property
    def field(self) -> str | None:
        return self.fields[0] if len(self.fields) == 1 else None


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    value: int | float
    low: bool


def normalize(text: str) -> tuple[str, list[int]]:
    """NFKC-normalize character by character, keeping a map to original offsets."""
    chars, origin = [], []
    for index, char in enumerate(text):
        normalized = unicodedata.normalize("NFKC", char)
        chars.append(normalized)
        origin.extend([index] * len(normalized))
    origin.append(len(text))
    return "".join(chars), origin


def extract_number_claims(text: str, anchors_by_field: dict[str, tuple[str, ...]]) -> list[Claim]:
    """Extract number claims from one string.

    `anchors_by_field` holds every numeric watched field of the entity, mapped
    to its anchor terms for this string's locale (possibly none).
    """
    norm, origin = normalize(text)
    tokens = _tokens(norm)
    starts = _clause_starts(norm)

    def clause(position):
        return bisect_right(starts, position) - 1

    anchors = [
        (field, match.start(), match.end())
        for field, terms in anchors_by_field.items()
        for term in terms
        for match in _anchor_pattern(term).finditer(norm)
    ]

    claims = []
    for index, token in enumerate(tokens):
        nearest: dict[str, int] = {}
        for field, anchor_start, anchor_end in anchors:
            if clause(anchor_start) != clause(token.start):
                continue
            if anchor_start >= token.end:
                low, high = token.end, anchor_start
            elif anchor_end <= token.start:
                low, high = anchor_end, token.start
            else:
                continue
            if any(low <= other.start and other.end <= high
                   for other_index, other in enumerate(tokens) if other_index != index):
                continue
            nearest[field] = min(nearest.get(field, math.inf), high - low)

        if nearest:
            best = min(nearest.values())
            fields = tuple(sorted(field for field, gap in nearest.items() if gap == best))
        elif len(tokens) == 1 and len(anchors_by_field) == 1:
            fields = tuple(anchors_by_field)
        else:
            fields = ()

        if not fields:
            confidence = None
        elif len(fields) > 1 or token.low:
            confidence = LOW
        else:
            confidence = HIGH
        span = (origin[token.start], origin[token.end - 1] + 1)
        claims.append(Claim(token.value, span, fields, confidence))
    return claims


def _tokens(norm: str) -> list[_Token]:
    tokens = []
    for match in NUMBER_RE.finditer(norm):
        start, end = match.span()
        before, after = norm[:start], norm[end:]
        low = bool(
            RANGE_BEFORE_RE.search(before) or RANGE_AFTER_RE.search(after)
            or MULTIPLIER_BEFORE_RE.search(before) or MULTIPLIER_AFTER_RE.search(after)
        )
        tokens.append(_Token(start, end, _parse_number(match.group()), low))
    return tokens


def _parse_number(raw: str) -> int | float:
    value = float(raw.replace(",", ""))
    return int(value) if value.is_integer() else value


def _clause_starts(norm: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(norm):
        if char in CLAUSE_BREAKS or (char in DIGIT_JOINERS and not _between_digits(norm, index)):
            starts.append(index + 1)
    return starts


def _between_digits(text: str, index: int) -> bool:
    return 0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit()


@lru_cache(maxsize=None)
def _anchor_pattern(term: str) -> re.Pattern:
    """Case-insensitive; ASCII-letter edges must not touch other ASCII letters."""
    term = unicodedata.normalize("NFKC", term)
    prefix = r"(?<![A-Za-z])" if term[:1].isascii() and term[:1].isalpha() else ""
    suffix = r"(?![A-Za-z])" if term[-1:].isascii() and term[-1:].isalpha() else ""
    return re.compile(prefix + re.escape(term) + suffix, re.IGNORECASE)
