"""Derived fields: values read from nested data by path, with fixed transforms.

A path like `effects[code=11].value2` walks into `effects`, keeps the list
elements whose `code` is 11, and reads `value2`. A number segment indexes a
list (`params.2`). No match leaves the field absent; several matches give a list. Numeric values are transformed as
(value * scale + offset) / divide. Formula fields are copied, never evaluated.
"""

from __future__ import annotations

from statsay.adapters import Entity
from statsay.config import Config, DerivedField

_ABSENT = object()


def apply_derived(config: Config, source_id: str, entities: dict[str, Entity]) -> None:
    """Set each derived field on the source's entities, in place."""
    derived = [field for field in config.fields.values() if source_id in field.sources]
    for entity in entities.values():
        for field in derived:
            value = derive(entity.fields, field)
            if value is _ABSENT:
                entity.fields.pop(field.name, None)
            else:
                entity.fields[field.name] = value


def derive(obj: dict, field: DerivedField):
    current = [obj]
    for segment in field.path:
        found = []
        for item in current:
            if isinstance(item, list) and segment.key.isdigit() and segment.filter_key is None:
                if int(segment.key) < len(item):
                    found.append(item[int(segment.key)])
                continue
            if not isinstance(item, dict) or segment.key not in item:
                continue
            value = item[segment.key]
            if segment.filter_key is None:
                found.append(value)
            elif isinstance(value, list):
                found.extend(element for element in value
                             if isinstance(element, dict) and element.get(segment.filter_key) == segment.filter_value)
        current = found
    if not current:
        return _ABSENT
    if field.kind == "value":
        current = [_transform(value, field) for value in current]
    return current[0] if len(current) == 1 else current


def _transform(value, field: DerivedField):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    result = round((value * field.scale + field.offset) / field.divide, 6)
    return int(result) if float(result).is_integer() else result
