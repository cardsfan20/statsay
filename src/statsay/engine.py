"""Run the checks.

On the current revision: value_mismatch for numeric claims, enum_term_mismatch
for vocabulary terms, locale_value_divergence for both, and unbound_claim for
numbers in bound strings that can't be tied to a field.

In diff mode (a base revision is given): watched_field_changed for strings
whose watched field changed while the string, in that locale, did not, and
which make no claim about that field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from dataclasses import field as dataclass_field  # `field` is shadowed inside Finding
from pathlib import Path

from statsay import StatsayError
from statsay.adapters import Reader, load_data_strings, load_entities, load_strings
from statsay.binding import Binding, Coverage, resolve
from statsay.config import Config, term_key
from statsay.extract import CONTROL_CODES, HIGH, extract_number_claims, extract_term_claims
from statsay.fields import apply_derived
from statsay.locate import FileCache, format_like, locate

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
    old: object = None      # diff mode: the base value of a changed field
    new: object = None
    text: str | None = None
    span: tuple[int, int] | None = None
    file: str | None = None
    line: int | None = None
    column: int | None = None
    fix: dict | None = None  # suggested replacement: file, line, column, end_line, end_column, old, new
    source: Path | None = dataclass_field(default=None, repr=False)  # absolute path of `file`; not serialized

    def to_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "source"}
        if self.fix:
            out["fix"] = {k: v for k, v in self.fix.items() if k not in ("path", "offset")}
        return {name: value for name, value in out.items() if value is not None}

    def fingerprint(self) -> str:
        """Stable identity for baselines and SARIF: what is claimed where, not line numbers."""
        parts = (self.rule, self.key, self.locale, self.field, self.claimed, self.actual, self.text)
        return "|".join("" if part is None else json.dumps(part, ensure_ascii=False, sort_keys=True)
                        for part in parts)


@dataclass
class Result:
    coverage: list[Coverage]
    findings: list[Finding]
    diagnostics: list[str]
    stats: dict = field(default_factory=dict)
    # diff mode only: key -> {field: (old, new)} for watched fields that changed
    changes: dict[str, dict] = field(default_factory=dict)
    # diff mode only: keys whose entity, watched fields or text changed (or are new)
    changed_keys: set[str] = field(default_factory=set)


def run(config: Config, base: Reader | None = None) -> Result:
    """Check the current files; with `base`, also compare against that revision."""
    entities, strings = _load(config)
    if base is not None:
        base_entities, base_strings = _load(config, base, missing_ok=True)

    bindings, coverage, diagnostics = resolve(config, entities, strings)
    findings: list[Finding] = []
    changes: dict[str, dict] = {}
    changed_keys: set[str] = set()
    checked = 0
    for binding in bindings:
        checked += len(strings[binding.key])
        binding_findings, claimed_fields = _check_binding(config, binding, strings[binding.key])
        findings.extend(binding_findings)
        if base is not None:
            base_entity = base_entities.get(binding.entity.source, {}).get(binding.entity.id)
            base_by_locale = base_strings.get(binding.key, {})
            changed = _field_changes(binding, base_entity)
            if changed:
                changes[binding.key] = changed
            if base_entity is None or changed or any(
                    base_by_locale.get(locale) is None or base_by_locale[locale].text != loc.text
                    for locale, loc in strings[binding.key].items()):
                changed_keys.add(binding.key)
            findings.extend(_check_changes(config, binding, strings[binding.key], claimed_fields,
                                           changed, base_by_locale))
    _attach_locations(findings)

    findings.sort(key=lambda f: (f.file or "", f.line or 0, f.key, f.locale or "", f.rule))
    stats = {
        "entities": sum(len(by_id) for by_id in entities.values()),
        "strings": len(strings),
        "bindings": len(bindings),
        "checked": checked,
    }
    return Result(coverage, findings, diagnostics, stats, changes, changed_keys)


def _attach_locations(findings: list[Finding]) -> None:
    """Fill in line/column from the source file, and a fix for confident numeric mismatches."""
    cache = FileCache()
    for finding in findings:
        if finding.source is None or finding.text is None or finding.span is None:
            continue
        location = locate(cache, finding.source, finding.line, finding.text, finding.span)
        if location is None:
            continue
        finding.line, finding.column = location.line, location.column
        if finding.rule == "value_mismatch" and finding.severity == ERROR and _is_number(finding.actual):
            original = finding.text[finding.span[0]:finding.span[1]]
            finding.fix = {
                "file": finding.file, "line": location.line, "column": location.column,
                "end_line": location.end_line, "end_column": location.end_column,
                "old": cache.text(location.file)[location.start:location.end],
                "new": format_like(original, finding.actual),
                "path": str(location.file), "offset": location.start,
            }


def _field_changes(binding, base_entity) -> dict:
    """Watched fields whose value differs from the base revision: {field: (old, new)}."""
    if base_entity is None:
        return {}
    missing = object()
    out = {}
    for name in binding.watched_fields:
        old, new = base_entity.fields.get(name, missing), binding.entity.fields.get(name, missing)
        if old != new:
            out[name] = (None if old is missing else old, None if new is missing else new)
    return out


def _load(config: Config, read: Reader | None = None, missing_ok: bool = False):
    options = {"missing_ok": missing_ok, **({"read": read} if read else {})}
    entities = {source_id: load_entities(source, **options) for source_id, source in config.data_sources.items()}
    for source_id, by_id in entities.items():
        apply_derived(config, source_id, by_id)
    strings: dict = {}
    for source in config.localization:
        if source.format == "csv":
            loaded = load_strings(source, **options)
        else:
            loaded = load_data_strings(source, entities[source.source], config.data_sources[source.source].path)
        for key, by_locale in loaded.items():
            slot = strings.setdefault(key, {})
            for locale, loc in by_locale.items():
                if locale in slot:
                    raise StatsayError(f"key '{key}' has more than one '{locale}' text")
                slot[locale] = loc
    return entities, strings


def _check_changes(config, binding, by_locale, claimed_fields, changed, base_by_locale) -> list[Finding]:
    """watched_field_changed: data moved, the text didn't, and the text states nothing about it.

    `changed` comes from _field_changes; a new entity has none, since its strings
    were written against the current data.
    """
    findings = []
    for locale, loc in by_locale.items():
        base_loc = base_by_locale.get(locale)
        if base_loc is None or base_loc.text != loc.text:
            continue  # the string is new or was edited in this change
        for name, (old, new) in changed.items():
            if name in claimed_fields.get(locale, set()):
                continue
            findings.append(Finding(
                rule="watched_field_changed", severity=WARNING, key=binding.key, entity=binding.entity.ref,
                locale=locale, field=name, old=old, new=new, text=loc.text,
                file=_display_path(config, loc.file), line=loc.line, source=loc.file,
                message=f"{name} changed {_display(old)} -> {_display(new)}; "
                        f"this text did not change and states no value for it",
            ))
    return findings


def _check_binding(config: Config, binding: Binding, by_locale: dict) -> tuple[list[Finding], dict[str, set]]:
    """Findings for one binding, plus the fields each locale's text makes claims about."""
    entity = binding.entity
    watched = [name for name in binding.watched_fields if name in config.claims]
    numeric = {name: config.claims[name] for name in watched
               if config.claims[name].kind == "number" and _is_number(entity.fields.get(name))}
    enums = {name: config.claims[name] for name in watched
             if config.claims[name].kind == "enum" and name in entity.fields}
    # A stray number only hints at a missing binding if this binding tracks numbers at all.
    tracks_numbers = any(config.claims[name].kind == "number" for name in watched)
    findings = []
    # locale -> [(field, value, confidence)] for single-field claims, used for divergence
    claimed: dict[str, list[tuple]] = {}
    claimed_fields: dict[str, set] = {}  # locale -> every field any claim was tied to

    for locale, loc in by_locale.items():
        base = dict(key=binding.key, entity=entity.ref, locale=locale, text=loc.text,
                    file=_display_path(config, loc.file), line=loc.line, source=loc.file)
        claimed[locale] = []
        claimed_fields[locale] = set()

        anchors = {name: rule.anchors.get(locale, ()) for name, rule in numeric.items()}
        codes = CONTROL_CODES.get(loc.codes)
        for claim in extract_number_claims(loc.text, anchors, codes):
            if not claim.fields:
                if tracks_numbers:
                    findings.append(Finding(
                        rule="unbound_claim", severity=INFO, value=claim.value, span=claim.span,
                        message=f"number {claim.value} is not tied to any watched field", **base,
                    ))
                continue
            claimed_fields[locale].update(claim.fields)
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
        contrast = (config.contrast_cues or {}).get(locale, ((), ()))
        for claim in extract_term_claims(loc.text, vocabularies, codes, contrast):
            claimed_fields[locale].update(claim.values)
            if claim.field:
                claimed[locale].append((claim.field, claim.values[claim.field], claim.confidence))
            if any(enums[name].satisfied_by.get(value, {value}) & _term_set(entity.fields[name])
                   for name, value in claim.values.items()):
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
    return findings, claimed_fields


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
