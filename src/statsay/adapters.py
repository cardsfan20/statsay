"""Read game data and localization files into a normalized model.

Supported: one data format (a JSON array of objects) and one localization
format (CSV with a key column and one column per locale). Every loader takes a
`read` function, so the same code reads the working tree, another directory or
a Git revision (see revisions.py).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from statsay import StatsayError
from statsay.config import DataSource, LocalizationSource


Reader = Callable[[Path], str]  # raises FileNotFoundError for a missing file


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def load_entities(source: DataSource, read: Reader = read_file, missing_ok: bool = False) -> dict[str, Entity]:
    """Entities by id, in file order. A missing file is empty when `missing_ok`."""
    try:
        data = json.loads(read(source.path))
    except FileNotFoundError:
        if missing_ok:
            return {}
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


def load_strings(source: LocalizationSource, read: Reader = read_file,
                 missing_ok: bool = False) -> dict[str, dict[str, LocString]]:
    """Strings by key, then locale. Empty cells are treated as missing."""
    try:
        text = read(source.path).lstrip("﻿")
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise StatsayError(f"localization file not found: {source.path}") from None

    strings: dict[str, dict[str, LocString]] = {}
    with io.StringIO(text, newline="") as handle:
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
