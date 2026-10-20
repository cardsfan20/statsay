"""Load and validate statsay.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from statsay import StatsayError

CONFIG_NAME = "statsay.yaml"
CLAIM_KINDS = {"number", "enum"}
LOCALIZATION_FORMATS = {"csv"}


@dataclass(frozen=True)
class DataSource:
    id: str
    path: Path
    entity_id_field: str


@dataclass(frozen=True)
class LocalizationSource:
    path: Path
    format: str
    key_column: str
    locales: tuple[str, ...]


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


@dataclass(frozen=True)
class Config:
    root: Path
    data_sources: dict[str, DataSource]
    localization: tuple[LocalizationSource, ...]
    conventions: tuple[ConventionBinding, ...]
    explicits: tuple[ExplicitBinding, ...]
    claims: dict[str, ClaimRule]


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
    root = config_path.parent

    data_sources = {}
    for item in _list(raw, "data_sources", required=True):
        source = DataSource(
            id=_str(item, "id", "data_sources"),
            path=root / _str(item, "path", "data_sources"),
            entity_id_field=_str(item, "entity_id_field", "data_sources"),
        )
        if source.id in data_sources:
            raise StatsayError(f"data_sources: duplicate id '{source.id}'")
        data_sources[source.id] = source

    localization = []
    for item in _list(raw, "localization", required=True):
        fmt = _str(item, "format", "localization")
        if fmt not in LOCALIZATION_FORMATS:
            raise StatsayError(f"localization: unsupported format '{fmt}' (supported: csv)")
        locales = item.get("locales")
        if not isinstance(locales, list) or not locales:
            raise StatsayError("localization: 'locales' must be a non-empty list")
        localization.append(LocalizationSource(
            path=root / _str(item, "path", "localization"),
            format=fmt,
            key_column=_str(item, "key_column", "localization"),
            locales=tuple(str(locale) for locale in locales),
        ))

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
        claims[field] = ClaimRule(
            field=field,
            kind=kind,
            unit=body.get("unit"),
            anchors={str(locale): tuple(str(term) for term in terms) for locale, terms in anchors.items()},
        )

    return Config(
        root=root,
        data_sources=data_sources,
        localization=tuple(localization),
        conventions=tuple(conventions),
        explicits=tuple(explicits),
        claims=claims,
    )


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


def _check_source(source, data_sources):
    if source not in data_sources:
        raise StatsayError(f"bindings: unknown data source '{source}'")
