"""Load and validate statsay.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import re

import yaml

from statsay import StatsayError
from statsay.extract import CONTROL_CODES

CONFIG_NAME = "statsay.yaml"
CLAIM_KINDS = {"number", "enum"}
DATA_FORMATS = {"json", "rpgmaker"}
LOCALIZATION_FORMATS = {"csv", "data", "po"}
FIELD_KINDS = {"value", "formula"}
PATH_SEGMENT_RE = re.compile(r"^(\w+)(?:\[(\w+)=([^\]]+)\])?$")


@dataclass(frozen=True)
class DataSource:
    id: str
    path: Path
    entity_id_field: str = "id"
    format: str = "json"  # "rpgmaker": MV/MZ database file (null first entry, unused slots)


@dataclass(frozen=True)
class LocalizationSource:
    format: str                       # "csv"; "data": text in a data source field; "po": gettext
    locales: tuple[str, ...]
    path: Path | None = None          # csv
    key_column: str | None = None     # csv
    source: str | None = None         # data: data source id
    field: str | None = None          # data: entity field holding the text, e.g. description
    key_pattern: str | None = None    # data: key given to each entity's text, e.g. item.{id}.description
    control_codes: str | None = None  # engine whose control codes are masked, e.g. rpgmaker
    source_locale: str | None = None  # po: the locale whose text is the msgid


@dataclass(frozen=True)
class PathSegment:
    key: str
    filter_key: str | None = None     # list elements whose filter_key equals filter_value
    filter_value: object = None


@dataclass(frozen=True)
class DerivedField:
    """A field read from nested data, e.g. effects[code=11].value2, with fixed transforms."""
    name: str
    sources: tuple[str, ...]          # data sources it applies to (`source:` takes one id or a list)
    path: tuple[PathSegment, ...]
    kind: str = "value"               # "formula": never evaluated, only watched for changes
    scale: float = 1
    offset: float = 0
    divide: float = 1


@dataclass(frozen=True)
class ConventionBinding:
    pattern: str
    source: str
    watched_fields: tuple[str, ...]


@dataclass(frozen=True)
class ExplicitBinding:
    source: str
    entity_id: str
    keys: tuple[str, ...]
    watched_fields: tuple[str, ...]


@dataclass(frozen=True)
class ClaimRule:
    field: str
    kind: str
    unit: str | None
    anchors: dict[str, tuple[str, ...]]
    # enum only: value key (see term_key) -> locale -> terms that name that value
    vocabulary: dict[str, dict[str, tuple[str, ...]]] = None
    # enum only: a reviewed vocabulary may fail CI; an unreviewed one only warns
    validated: bool = False
    # enum only: value key -> the data values that satisfy it (itself plus `aliases`)
    satisfied_by: dict[str, frozenset[str]] = None


def term_key(value) -> str:
    """Canonical key for an enum value, so YAML `false:` and data `false` match."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "null" if value is None else str(value)


@dataclass(frozen=True)
class Config:
    root: Path
    data_sources: dict[str, DataSource]
    localization: tuple[LocalizationSource, ...]
    conventions: tuple[ConventionBinding, ...]
    explicits: tuple[ExplicitBinding, ...]
    claims: dict[str, ClaimRule]
    fields: dict[str, DerivedField]
    # locale -> (cues before a term, cues after a term) that mark it as a comparison
    contrast_cues: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = None


def find_config(path: Path) -> Path:
    """Accept a config file or a directory containing statsay.yaml."""
    path = Path(path)
    candidate = path / CONFIG_NAME if path.is_dir() else path
    if not candidate.is_file():
        raise StatsayError(f"no config found at {candidate}")
    return candidate


def load_config(path: Path) -> Config:
    config_path = find_config(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise StatsayError(f"{config_path}: invalid YAML: {error}") from None
    if not isinstance(raw, dict):
        raise StatsayError(f"{config_path}: expected a mapping at the top level")
    return build_config(raw, config_path.parent)


def build_config(raw: dict, root: Path) -> Config:
    """A Config from an already-parsed statsay.yaml mapping; relative paths resolve against `root`."""
    root = Path(root)
    data_sources = {}
    for item in _list(raw, "data_sources", required=True):
        fmt = item.get("format", "json")
        if fmt not in DATA_FORMATS:
            raise StatsayError(f"data_sources: unsupported format '{fmt}' (supported: {sorted(DATA_FORMATS)})")
        source = DataSource(
            id=_str(item, "id", "data_sources"),
            path=root / _str(item, "path", "data_sources"),
            entity_id_field=item.get("entity_id_field") or "id",
            format=fmt,
        )
        if source.id in data_sources:
            raise StatsayError(f"data_sources: duplicate id '{source.id}'")
        data_sources[source.id] = source

    localization = [_localization(item, root, data_sources) for item in _list(raw, "localization", required=True)]

    conventions, explicits = [], []
    for item in _list(raw, "bindings", required=True):
        if "convention" in item:
            pattern = _str(item, "convention", "bindings")
            if "{id}" not in pattern:
                raise StatsayError(f"bindings: convention '{pattern}' must contain {{id}}")
            source = _str(item, "source", "bindings")
            _check_source(source, data_sources)
            conventions.append(ConventionBinding(pattern, source, _fields(item, "bindings")))
        elif "explicit" in item:
            body = item["explicit"]
            if not isinstance(body, dict):
                raise StatsayError("bindings: 'explicit' must be a mapping")
            entity = _str(body, "entity", "bindings.explicit")
            source, _, entity_id = entity.partition(".")
            if not entity_id:
                raise StatsayError(f"bindings.explicit: entity '{entity}' must look like <source>.<id>")
            _check_source(source, data_sources)
            keys = body.get("keys")
            if not isinstance(keys, list) or not keys:
                raise StatsayError(f"bindings.explicit: '{entity}' needs a non-empty 'keys' list")
            explicits.append(ExplicitBinding(
                source, entity_id, tuple(str(key) for key in keys), _fields(body, "bindings.explicit"),
            ))
        else:
            raise StatsayError("bindings: each entry needs 'convention' or 'explicit'")

    claims = {}
    raw_claims = raw.get("claims") or {}
    if not isinstance(raw_claims, dict):
        raise StatsayError("claims: expected a mapping of field names")
    for field, body in raw_claims.items():
        if not isinstance(body, dict):
            raise StatsayError(f"claims.{field}: expected a mapping")
        kind = body.get("kind")
        if kind not in CLAIM_KINDS:
            raise StatsayError(f"claims.{field}: kind must be one of {sorted(CLAIM_KINDS)}")
        anchors = body.get("anchors") or {}
        if not isinstance(anchors, dict):
            raise StatsayError(f"claims.{field}: anchors must map locales to lists")
        vocabulary, satisfied_by = _vocabulary(field, body) if kind == "enum" else (None, None)
        claims[field] = ClaimRule(
            field=field,
            kind=kind,
            unit=body.get("unit"),
            anchors={str(locale): tuple(str(term) for term in terms) for locale, terms in anchors.items()},
            vocabulary=vocabulary,
            validated=bool(body.get("validated", False)),
            satisfied_by=satisfied_by,
        )

    fields = {}
    raw_fields = raw.get("fields") or {}
    if not isinstance(raw_fields, dict):
        raise StatsayError("fields: expected a mapping of field names")
    for name, body in raw_fields.items():
        fields[str(name)] = _derived_field(str(name), body, data_sources)
        if fields[str(name)].kind == "formula" and name in claims:
            raise StatsayError(f"fields.{name}: formula fields are never evaluated, so they can't have claims")

    return Config(
        root=root,
        data_sources=data_sources,
        localization=tuple(localization),
        conventions=tuple(conventions),
        explicits=tuple(explicits),
        claims=claims,
        fields=fields,
        contrast_cues=_contrast_cues(raw.get("contrast_cues")),
    )


def _localization(item, root, data_sources):
    fmt = _str(item, "format", "localization")
    if fmt not in LOCALIZATION_FORMATS:
        raise StatsayError(f"localization: unsupported format '{fmt}' (supported: {sorted(LOCALIZATION_FORMATS)})")
    codes = item.get("control_codes")
    if codes is not None and codes not in CONTROL_CODES:
        raise StatsayError(f"localization: unknown control_codes '{codes}' (known: {sorted(CONTROL_CODES)})")

    if fmt == "csv":
        locales = item.get("locales")
        if not isinstance(locales, list) or not locales:
            raise StatsayError("localization: 'locales' must be a non-empty list")
        return LocalizationSource(
            format=fmt, locales=tuple(str(locale) for locale in locales),
            path=root / _str(item, "path", "localization"),
            key_column=_str(item, "key_column", "localization"), control_codes=codes,
        )

    if fmt == "po":
        return LocalizationSource(
            format=fmt, locales=(_str(item, "locale", "localization"),),
            path=root / _str(item, "path", "localization"),
            source_locale=_str(item, "source_locale", "localization"), control_codes=codes,
        )

    source = _str(item, "source", "localization")
    _check_source(source, data_sources)
    pattern = _str(item, "key", "localization")
    if "{id}" not in pattern:
        raise StatsayError(f"localization: key '{pattern}' must contain {{id}}")
    if codes is None and data_sources[source].format == "rpgmaker":
        codes = "rpgmaker"
    return LocalizationSource(
        format=fmt, locales=(_str(item, "locale", "localization"),), source=source,
        field=_str(item, "field", "localization"), key_pattern=pattern, control_codes=codes,
    )


def _derived_field(name, body, data_sources):
    if not isinstance(body, dict):
        raise StatsayError(f"fields.{name}: expected a mapping")
    raw_sources = body.get("source")
    sources = tuple(raw_sources) if isinstance(raw_sources, list) else (raw_sources,)
    if not sources or not all(isinstance(s, str) and s for s in sources):
        raise StatsayError(f"fields.{name}: 'source' must be a data source id or a list of them")
    for source in sources:
        _check_source(source, data_sources)
    segments = []
    for part in _str(body, "path", f"fields.{name}").split("."):
        match = PATH_SEGMENT_RE.match(part)
        if not match:
            raise StatsayError(f"fields.{name}: bad path segment '{part}' (expected name or name[key=value])")
        key, filter_key, filter_value = match.groups()
        if filter_value is not None and re.fullmatch(r"-?\d+", filter_value):
            filter_value = int(filter_value)
        segments.append(PathSegment(key, filter_key, filter_value))
    kind = body.get("kind", "value")
    if kind not in FIELD_KINDS:
        raise StatsayError(f"fields.{name}: kind must be one of {sorted(FIELD_KINDS)}")
    numbers = {}
    for option, default in (("scale", 1), ("offset", 0), ("divide", 1)):
        value = body.get(option, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or (option == "divide" and value == 0):
            raise StatsayError(f"fields.{name}: '{option}' must be a number" + (", not 0" if option == "divide" else ""))
        numbers[option] = value
    return DerivedField(name, sources, tuple(segments), kind, **numbers)


def _list(raw, name, required=False):
    value = raw.get(name)
    if value is None:
        if required:
            raise StatsayError(f"missing required section '{name}'")
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise StatsayError(f"{name}: expected a list of mappings")
    return value


def _str(item, name, where):
    value = item.get(name)
    if not isinstance(value, str) or not value:
        raise StatsayError(f"{where}: '{name}' must be a non-empty string")
    return value


def _fields(item, where):
    fields = item.get("watched_fields")
    if not isinstance(fields, list) or not fields:
        raise StatsayError(f"{where}: 'watched_fields' must be a non-empty list")
    return tuple(str(field) for field in fields)


def _vocabulary(field, body):
    raw = body.get("vocabulary")
    if not isinstance(raw, dict) or not raw:
        raise StatsayError(f"claims.{field}: kind enum needs a non-empty 'vocabulary' mapping")
    vocabulary, satisfied_by, seen = {}, {}, {}
    for value, by_locale in raw.items():
        if not isinstance(by_locale, dict):
            raise StatsayError(f"claims.{field}.vocabulary.{value}: expected a mapping of locales to lists")
        key = term_key(value)
        vocabulary[key] = {}
        aliases = by_locale.get("aliases", [])
        if not isinstance(aliases, list):
            raise StatsayError(f"claims.{field}.vocabulary.{value}.aliases: expected a list of data values")
        satisfied_by[key] = frozenset([key, *(term_key(alias) for alias in aliases)])
        for locale, terms in by_locale.items():
            if locale == "aliases":
                continue
            if not isinstance(terms, list):
                raise StatsayError(f"claims.{field}.vocabulary.{value}.{locale}: expected a list of terms")
            for term in terms:
                folded = (str(locale), str(term).casefold())
                if folded in seen and seen[folded] != key:
                    raise StatsayError(
                        f"claims.{field}: term '{term}' ({locale}) names both '{seen[folded]}' and '{key}'")
                seen[folded] = key
            vocabulary[key][str(locale)] = tuple(str(term) for term in terms)
    return vocabulary, satisfied_by


def _contrast_cues(raw):
    """contrast_cues: {locale: {before: [...], after: [...]}}"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise StatsayError("contrast_cues: expected a mapping of locales")
    cues = {}
    for locale, body in raw.items():
        if not isinstance(body, dict) or set(body) - {"before", "after"}:
            raise StatsayError(f"contrast_cues.{locale}: expected 'before' and/or 'after' lists")
        sides = []
        for side in ("before", "after"):
            terms = body.get(side, [])
            if not isinstance(terms, list):
                raise StatsayError(f"contrast_cues.{locale}.{side}: expected a list")
            sides.append(tuple(str(term) for term in terms))
        cues[str(locale)] = tuple(sides)
    return cues


def _check_source(source, data_sources):
    if source not in data_sources:
        raise StatsayError(f"bindings: unknown data source '{source}'")
