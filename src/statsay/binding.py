"""Link entities to localization keys and report coverage."""

from __future__ import annotations

from dataclasses import dataclass

from statsay import StatsayError
from statsay.adapters import Entity
from statsay.config import Config


@dataclass(frozen=True)
class Binding:
    key: str
    entity: Entity
    watched_fields: tuple[str, ...]
    via: tuple[str, ...]  # the rules that produced it, e.g. "item.{id}.description"


@dataclass(frozen=True)
class Coverage:
    source: str
    rule: str
    entities: int
    unbound: tuple[str, ...]  # entity refs with no string for the convention key

    @property
    def bound(self) -> int:
        return self.entities - len(self.unbound)


def resolve(config: Config, entities: dict[str, dict[str, Entity]], strings: dict) -> tuple[
    list[Binding], list[Coverage], list[str]
]:
    """Return bindings, per-convention coverage, and diagnostics.

    A key bound to the same entity by several rules becomes one binding with
    the union of their watched fields, so its numbers are judged once.
    """
    merged: dict[tuple[str, str], dict] = {}
    coverage, diagnostics = [], []

    def add(key, entity, fields, rule):
        slot = merged.setdefault((key, entity.ref), {"entity": entity, "fields": [], "via": []})
        slot["fields"].extend(field for field in fields if field not in slot["fields"])
        slot["via"].append(rule)

    for convention in config.conventions:
        unbound = []
        for entity in entities[convention.source].values():
            key = convention.pattern.replace("{id}", entity.id)
            if key in strings:
                add(key, entity, convention.watched_fields, convention.pattern)
            else:
                unbound.append(entity.ref)
        coverage.append(Coverage(
            convention.source, convention.pattern, len(entities[convention.source]), tuple(unbound),
        ))

    for explicit in config.explicits:
        entity = entities[explicit.source].get(explicit.entity_id)
        if entity is None:
            raise StatsayError(f"bindings.explicit: no entity '{explicit.source}.{explicit.entity_id}'")
        for key in explicit.keys:
            if key in strings:
                add(key, entity, explicit.watched_fields, f"explicit:{key}")
            else:
                diagnostics.append(f"explicit binding for {entity.ref}: key '{key}' not found")

    bindings = [
        Binding(key, slot["entity"], tuple(slot["fields"]), tuple(slot["via"]))
        for (key, _), slot in merged.items()
    ]
    return bindings, coverage, diagnostics
