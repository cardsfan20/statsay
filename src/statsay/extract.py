"""Find claims in a string: numbers tied to watched fields, and vocabulary terms.

Number claims follow a fixed, testable confidence rule:

- High: an anchor term of exactly one field is nearest to the number, in the
  same clause, with no other number in between; or the string has exactly one
  number and the entity exactly one numeric watched field, which has no
  anchors configured for this locale.
- Low: the nearest anchors belong to two fields (a tie), or the number is part
  of a range ("10-20") or a multiplier ("x2").
- Unassigned: no anchor qualifies. These become `unbound_claim` findings.

An anchor joined to the number by a label separator ("HP+50", 「攻撃力：15」) counts
as nearer than one separated by a space, so in "STR+5 WIS+5" each number takes
the label before it. A number written as a percentage ("15%", "15 percent") only
matches fields whose unit is percent, and a plain number only the others.

Text is NFKC-normalized first, so full-width digits and signs read as ASCII.
A no-break or thin space between digit groups ("1 500") is read as a thousands
separator. Line breaks are wrapping, not clause breaks. Engine control codes
can be masked out first (see CONTROL_CODES). Values are unsigned; direction
("raises", "-10%") is not interpreted yet.
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
MULTIPLIER_BEFORE_RE = re.compile(r"(?<![A-Za-z])[xX×*]\s?$")
MULTIPLIER_AFTER_RE = re.compile(r"^\s?[xX×*](?![A-Za-z])")
CLAUSE_BREAKS = set("。！？；、!?;")
DIGIT_JOINERS = set(".,")  # clause breaks, except between two digits ("1.5", "1,000")
GROUP_SPACES = "\u00a0\u202f\u2009"  # no-break, narrow no-break and thin space: "1 500"

# Engine control codes, masked with spaces before extraction so offsets stay put.
CONTROL_CODES = {
    # RPG Maker MV/MZ: \C[2], \I[64], \V[5], \N[1], \FS[24], \G, \{, \}, \$, \., \|, \!, \>, \<, \^, \\
    "rpgmaker": re.compile(r"\\[A-Za-z]+\[\d*\]|\\[A-Za-z]+(?![A-Za-z\[])|\\[{}$.|!><^\\]"),
}


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
class TermClaim:
    values: dict[str, str]    # field -> enum value key named by the term
    span: tuple[int, int]     # offsets in the original text
    confidence: str           # HIGH, or LOW when the term belongs to several fields

    @property
    def field(self) -> str | None:
        return next(iter(self.values)) if len(self.values) == 1 else None


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    value: int | float
    low: bool
    percent: bool = False


LABEL_SEPARATOR_RE = re.compile(r"^\s*[+\-:：=＋−]\s*$")
PERCENT_AFTER_RE = re.compile(r"^\s?(?:%|percent\b|パーセント)", re.IGNORECASE)


def normalize(text: str) -> tuple[str, list[int]]:
    """NFKC-normalize character by character, keeping a map to original offsets."""
    chars, origin = [], []
    for index, char in enumerate(text):
        if char in GROUP_SPACES and _between_digits(text, index):
            char = ","  # a digit-group separator; NFKC would turn it into a plain space
        normalized = unicodedata.normalize("NFKC", char)
        chars.append(normalized)
        origin.extend([index] * len(normalized))
    origin.append(len(text))
    return "".join(chars), origin


def mask(text: str, codes: re.Pattern | None) -> str:
    """Blank out control codes with spaces of the same length."""
    return codes.sub(lambda match: " " * len(match.group()), text) if codes else text


def extract_number_claims(text: str, anchors_by_field: dict[str, tuple[str, ...]],
                          codes: re.Pattern | None = None,
                          percent_fields: frozenset[str] | set[str] = frozenset()) -> list[Claim]:
    """Extract number claims from one string.

    `anchors_by_field` holds every numeric watched field of the entity, mapped
    to its anchor terms for this string's locale (possibly none). `codes`
    masks engine control codes first. `percent_fields` are the fields whose
    unit is percent.
    """
    norm, origin = normalize(mask(text, codes))
    tokens = _tokens(norm)
    starts = _clause_starts(norm)

    def clause(position):
        return bisect_right(starts, position) - 1

    found = [
        (field, match.start(), match.end())
        for field, terms in anchors_by_field.items()
        for term in terms
        for match in _anchor_pattern(term).finditer(norm)
    ]
    # An anchor inside a longer anchor of another field doesn't count: "最大HP" beats "HP".
    anchors = [
        (field, start, end) for field, start, end in found
        if not any(other != field and o_start <= start and end <= o_end and (o_end - o_start) > (end - start)
                   for other, o_start, o_end in found)
    ]

    claims = []
    for index, token in enumerate(tokens):
        nearest: dict[str, float] = {}
        compatible = {f for f in anchors_by_field if (f in percent_fields) == token.percent}
        for field, anchor_start, anchor_end in anchors:
            if field not in compatible:
                continue
            if clause(anchor_start) != clause(token.start):
                continue
            if anchor_start >= token.end:
                if any(other.start >= anchor_end and LABEL_SEPARATOR_RE.match(norm[anchor_end:other.start])
                       for other in tokens):
                    continue  # "STR+5 WIS+5": WIS labels the number after it, not this one
                low, high = token.end, anchor_start
            elif anchor_end <= token.start:
                low, high = anchor_end, token.start
            else:
                continue
            if any(low <= other.start and other.end <= high
                   for other_index, other in enumerate(tokens) if other_index != index):
                continue
            gap = high - low
            if anchor_end <= token.start and LABEL_SEPARATOR_RE.match(norm[anchor_end:token.start]):
                gap = -1  # "HP+50", "攻撃力：15": the label owns the number
            nearest[field] = min(nearest.get(field, math.inf), gap)

        if nearest:
            best = min(nearest.values())
            fields = tuple(sorted(field for field, gap in nearest.items() if gap == best))
        elif len(tokens) == 1 and len(compatible) == 1 and len(anchors_by_field) == 1 \
                and not next(iter(anchors_by_field.values())):
            # Only for a field with no anchors in this locale: if anchors are configured
            # and none is near, the number is about something else ("usable up to 2 times").
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


def extract_term_claims(text: str, vocabulary_by_field: dict[str, dict[str, tuple[str, ...]]],
                        codes: re.Pattern | None = None,
                        contrast: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())) -> list[TermClaim]:
    """Find vocabulary terms in one string.

    `vocabulary_by_field` maps each enum watched field to {value key: terms}
    for this string's locale. Where matches overlap, the longest wins, so a
    negated phrase ("cannot target air") beats the phrase it contains.
    `contrast` holds cues that mark a term as a comparison rather than a claim:
    cues that come before it in the same clause ("more than cotton") and cues
    that come after it (「綿より」). Such terms are dropped.
    """
    norm, origin = normalize(mask(text, codes))
    starts = _clause_starts(norm)

    def clause(position):
        return bisect_right(starts, position) - 1

    cues_before = [m.start() for cue in contrast[0] for m in _anchor_pattern(cue).finditer(norm)]
    cues_after = [m.start() for cue in contrast[1] for m in _anchor_pattern(cue).finditer(norm)]

    def contrasted(start, end):
        return any(cue < start and clause(cue) == clause(start) for cue in cues_before) or \
               any(cue >= end and clause(cue) == clause(start) for cue in cues_after)

    by_span: dict[tuple[int, int], dict[str, str]] = {}
    for field, values in vocabulary_by_field.items():
        for value, terms in values.items():
            for term in terms:
                for match in _anchor_pattern(term).finditer(norm):
                    by_span.setdefault(match.span(), {})[field] = value

    chosen: list[tuple[int, int]] = []
    for start, end in sorted(by_span, key=lambda span: (span[0] - span[1], span[0])):
        if not any(start < other_end and other_start < end for other_start, other_end in chosen):
            chosen.append((start, end))
    chosen = [(start, end) for start, end in chosen if not contrasted(start, end)]

    return [
        TermClaim(
            values=dict(sorted(by_span[(start, end)].items())),
            span=(origin[start], origin[end - 1] + 1),
            confidence=HIGH if len(by_span[(start, end)]) == 1 else LOW,
        )
        for start, end in sorted(chosen)
    ]


def _tokens(norm: str) -> list[_Token]:
    tokens = []
    for match in NUMBER_RE.finditer(norm):
        start, end = match.span()
        before, after = norm[:start], norm[end:]
        low = bool(
            RANGE_BEFORE_RE.search(before) or RANGE_AFTER_RE.search(after)
            or MULTIPLIER_BEFORE_RE.search(before) or MULTIPLIER_AFTER_RE.search(after)
        )
        tokens.append(_Token(start, end, _parse_number(match.group()), low, bool(PERCENT_AFTER_RE.match(after))))
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
    """Case-insensitive; ASCII-letter edges must not touch other ASCII letters.

    Spaces and hyphens inside a term are interchangeable: "faux fur" also
    matches "faux-fur" and "faux  fur".
    """
    term = unicodedata.normalize("NFKC", term).strip()
    body = r"[\s\-\u2010\u2011]+".join(re.escape(part) for part in re.split(r"[\s\-\u2010\u2011]+", term))
    prefix = r"(?<![A-Za-z])" if term[:1].isascii() and term[:1].isalpha() else ""
    suffix = r"(?![A-Za-z])" if term[-1:].isascii() and term[-1:].isalpha() else ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)
