"""Run the checks on the current revision.

Rules: value_mismatch for numeric claims, enum_term_mismatch for vocabulary
terms, locale_value_divergence for both, and unbound_claim for numbers in
bound strings that can't be tied to a field.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from statsay import StatsayError
from statsay.adapters import load_entities, load_strings
from statsay.binding import Binding, Coverage, resolve
from statsay.config import Config, term_key
from statsay.extract import HIGH, extract_number_claims, extract_term_claims

ERROR = "error"
WARNING = "warning"
INFO = "info"
SEVERITY_ORDER = {INFO: 0, WARNING: 1, ERROR: 2}


@dataclass
class Finding:
    rule: str
    severity: str
    key: str
    entity: str
    message: str
    locale: str | None = None
    field: str | None = None
    claimed: object = None  # a number, or an enum value key
    actual: object = None   # the data value: number, string, bool or list
    value: int | float | None = None
    values: dict | None = None
    text: str | None = None
    span: tuple[int, int] | None = None
    file: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return {name: value for name, value in asdict(self).items() if value is not None}


@dataclass
class Result:
    coverage: list[Coverage]
    findings: list[Finding]
    diagnostics: list[str]
    stats: dict = field(default_factory=dict)


def run(config: Config) -> Result:
    entities = {source_id: load_entities(source) for source_id, source in config.data_sources.items()}
    strings: dict = {}
    for source in config.localization:
        for key, by_locale in load_strings(source).items():
            if key in strings:
                raise StatsayError(f"key '{key}' appears in more than one localization file")
            strings[key] = by_locale

    bindings, coverage, diagnostics = resolve(config, entities, strings)
    findings: list[Finding] = []
    checked = 0
    for binding in bindings:
        checked += len(strings[binding.key])
        findings.extend(_check_binding(config, binding, strings[binding.key]))

    findings.sort(key=lambda f: (f.file or "", f.line or 0, f.key, f.locale or "", f.rule))
    stats = {
        "entities": sum(len(by_id) for by_id in entities.values()),
        "strings": len(strings),
        "bindings": len(bindings),
        "checked": checked,
    }
    return Result(coverage, findings, diagnostics, stats)


def _check_binding(config: Config, binding: Binding, by_locale: dict) -> list[Finding]:
    entity = binding.entity
    watched = [name for name in binding.watched_fields if name in config.claims]
    numeric = {name: config.claims[name] for name in watched
               if config.claims[name].kind == "number" and _is_number(entity.fields.get(name))}
    enums = {name: config.claims[name] for name in watched
             if config.claims[name].kind == "enum" and name in entity.fields}
    findings = []
    # locale -> [(field, value, confidence)] for single-field claims, used for divergence
    claimed: dict[str, list[tuple]] = {}

    for locale, loc in by_locale.items():
        base = dict(key=binding.key, entity=entity.ref, locale=locale, text=loc.text,
                    file=_display_path(config, loc.file), line=loc.line)
        claimed[locale] = []

        anchors = {name: rule.anchors.get(locale, ()) for name, rule in numeric.items()}
        for claim in extract_number_claims(loc.text, anchors):
            if not claim.fields:
                findings.append(Finding(
                    rule="unbound_claim", severity=INFO, value=claim.value, span=claim.span,
                    message=f"number {claim.value} is not tied to any watched field", **base,
                ))
                continue
            if claim.field:
                claimed[locale].append((claim.field, claim.value, claim.confidence))
            actuals = {name: entity.fields[name] for name in claim.fields}
            if any(_same(claim.value, actual) for actual in actuals.values()):
                continue
            if claim.field:
                actual = actuals[claim.field]
                message = f"{claim.field}: text says {claim.value}, data says {actual}"
            else:
                actual = None
                listed = ", ".join(f"{name} = {value}" for name, value in actuals.items())
                message = f"text says {claim.value}, which matches none of the tied fields ({listed})"
            findings.append(Finding(
                rule="value_mismatch", severity=ERROR if claim.confidence == HIGH else WARNING,
                field="|".join(claim.fields), claimed=claim.value, actual=actual, span=claim.span,
                message=message, **base,
            ))

        vocabularies = {
            name: {value: terms.get(locale, ()) for value, terms in rule.vocabulary.items()}
            for name, rule in enums.items()
        }
        for claim in extract_term_claims(loc.text, vocabularies):
            if claim.field:
                claimed[locale].append((claim.field, claim.values[claim.field], claim.confidence))
            if any(value in _term_set(entity.fields[name]) for name, value in claim.values.items()):
                continue
            term = loc.text[claim.span[0]:claim.span[1]]
            if claim.field:
                actual = entity.fields[claim.field]
                severity = ERROR if enums[claim.field].validated else WARNING
                message = (f'{claim.field}: text says {claim.values[claim.field]} ("{term}"), '
                           f"data says {_display(actual)}")
            else:
                actual, severity = None, WARNING
                message = f'"{term}" matches none of the fields it can name ({", ".join(claim.values)})'
            findings.append(Finding(
                rule="enum_term_mismatch", severity=severity, field="|".join(claim.values),
                claimed="|".join(claim.values.values()), actual=actual, span=claim.span,
                message=message, **base,
            ))

    first = next(iter(by_locale.values()), None)
    for name in [*numeric, *enums]:
        high = _values(claimed, name, high_only=True)
        every = _values(claimed, name, high_only=False)
        hard = name in numeric or enums[name].validated
        if len(high) >= 2 and len(set(high.values())) > 1:
            severity = ERROR if hard else WARNING
        elif len(every) >= 2 and len(set(every.values())) > 1:
            severity, high = WARNING, every
        else:
            continue
        values = {locale: (sorted(found)[0] if len(found) == 1 else sorted(found))
                  for locale, found in high.items()}
        listed = ", ".join(f"{locale} {_display(value)}" for locale, value in values.items())
        findings.append(Finding(
            rule="locale_value_divergence", severity=severity, key=binding.key, entity=entity.ref,
            field=name, values=values, message=f"{name}: locales disagree ({listed})",
            file=_display_path(config, first.file) if first else None, line=first.line if first else None,
        ))
    return findings


def _values(claimed, name, high_only):
    """Per locale, the frozen set of values claimed for one field."""
    out = {}
    for locale, claims in claimed.items():
        found = frozenset(value for field, value, confidence in claims
                          if field == name and (confidence == HIGH or not high_only))
        if found:
            out[locale] = found
    return out


def _term_set(value) -> set[str]:
    """Enum data may be one value or a list (e.g. materials); compare by term_key."""
    values = value if isinstance(value, list) else [value]
    return {term_key(item) for item in values}


def _display(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_display(item) for item in value) + "]"
    return term_key(value) if isinstance(value, bool) or value is None else str(value)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same(claimed, actual) -> bool:
    return abs(float(claimed) - abs(float(actual))) < 1e-9


def _display_path(config: Config, path: Path) -> str:
    try:
        return path.relative_to(config.root).as_posix()
    except ValueError:
        return path.as_posix()
