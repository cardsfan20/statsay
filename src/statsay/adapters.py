"""Read game data and localization files into a normalized model.

M1 supports one data format (a JSON array of objects) and one localization
format (CSV with a key column and one column per locale).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from statsay import StatsayError
from statsay.config import DataSource, LocalizationSource


@dataclass(frozen=True)
class Entity:
    source: str
    id: str
    fields: dict = field(hash=False, compare=False)

    @property
    def ref(self) -> str:
        return f"{self.source}.{self.id}"


@dataclass(frozen=True)
class LocString:
    key: str
    locale: str
    text: str
    file: Path
    line: int


def load_entities(source: DataSource) -> dict[str, Entity]:
    """Entities by id, in file order."""
    try:
        data = json.loads(source.path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise StatsayError(f"data source '{source.id}': file not found: {source.path}") from None
    except json.JSONDecodeError as error:
        raise StatsayError(f"{source.path}: invalid JSON: {error}") from None
    if not isinstance(data, list):
        raise StatsayError(f"{source.path}: expected a JSON array of objects")

    entities = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise StatsayError(f"{source.path}: item {index} is not an object")
        entity_id = item.get(source.entity_id_field)
        if entity_id is None:
            raise StatsayError(f"{source.path}: item {index} has no '{source.entity_id_field}'")
        entity_id = str(entity_id)
        if entity_id in entities:
            raise StatsayError(f"{source.path}: duplicate entity id '{entity_id}'")
        entities[entity_id] = Entity(source.id, entity_id, item)
    return entities


def load_strings(source: LocalizationSource) -> dict[str, dict[str, LocString]]:
    """Strings by key, then locale. Empty cells are treated as missing."""
    try:
        handle = source.path.open(encoding="utf-8-sig", newline="")
    except FileNotFoundError:
        raise StatsayError(f"localization file not found: {source.path}") from None

    strings: dict[str, dict[str, LocString]] = {}
    with handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [column for column in (source.key_column, *source.locales) if column not in header]
        if missing:
            raise StatsayError(f"{source.path}: missing columns {missing}")
        for row in reader:
            key = (row.get(source.key_column) or "").strip()
            if not key:
                continue
            if key in strings:
                raise StatsayError(f"{source.path}:{reader.line_num}: duplicate key '{key}'")
            strings[key] = {
                locale: LocString(key, locale, row[locale], source.path, reader.line_num)
                for locale in source.locales
                if row.get(locale)
            }
    return strings
