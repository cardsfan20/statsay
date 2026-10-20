"""Validate a mutation fixture and materialize its mutations.

Usage:
    python scripts/fixture.py validate fixtures/toy-game
    python scripts/fixture.py apply fixtures/toy-game D01 out/D01

`apply` writes a copy of the fixture with one mutation applied, so the clean
fixture and the copy can serve as the base and head revisions in diff mode.
"""

import argparse
import csv
import io
import json
import shutil
import sys
from pathlib import Path

COPIED = ["statsay.yaml", "data", "locales"]
CATEGORIES = {"data_only", "text_only", "negative"}
SEVERITIES = {"error", "warning", "info"}


class FixtureError(Exception):
    pass


def dump_json(data, indent=2):
    return json.dumps(data, indent=indent, ensure_ascii=False) + "\n"


def parse_csv(text):
    return list(csv.reader(io.StringIO(text, newline="")))


def dump_csv(rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


class Workspace:
    """In-memory copy of a fixture's data and localization files."""

    def __init__(self, root):
        self.root = Path(root)
        self.json = {}
        self.indent = {}
        self.csv = {}

    def get_json(self, rel):
        if rel not in self.json:
            text = (self.root / rel).read_text(encoding="utf-8")
            self.json[rel] = json.loads(text)
            self.indent[rel] = 2
        return self.json[rel]

    def get_csv(self, rel):
        if rel not in self.csv:
            text = (self.root / rel).read_text(encoding="utf-8")
            self.csv[rel] = parse_csv(text)
        return self.csv[rel]

    def rendered(self):
        """Changed files only, as {relative path: text}."""
        out = {rel: dump_json(data, self.indent[rel]) for rel, data in self.json.items()}
        out.update({rel: dump_csv(rows) for rel, rows in self.csv.items()})
        return out


def find_entity(data, entity_id, rel):
    for index, entity in enumerate(data):
        if entity.get("id") == entity_id:
            return index, entity
    raise FixtureError(f"{rel}: no entity '{entity_id}'")


def find_row(rows, key, rel):
    for index, row in enumerate(rows[1:], start=1):
        if row[0] == key:
            return index, row
    raise FixtureError(f"{rel}: no key '{key}'")


def check_from(actual, expected, where):
    if actual != expected:
        raise FixtureError(f"{where}: expected {expected!r}, found {actual!r}")


def op_set_field(ws, edit):
    rel = edit["file"]
    _, entity = find_entity(ws.get_json(rel), edit["entity"], rel)
    field = edit["field"]
    check_from(entity.get(field), edit["from"], f"{rel}:{edit['entity']}.{field}")
    if edit["to"] is None:
        entity.pop(field, None)
    else:
        entity[field] = edit["to"]


def op_move_entity(ws, edit):
    rel = edit["file"]
    data = ws.get_json(rel)
    index, entity = find_entity(data, edit["entity"], rel)
    data.pop(index)
    to_index = edit["to_index"]
    data.insert(len(data) if to_index == -1 else to_index, entity)


def op_reformat_json(ws, edit):
    ws.get_json(edit["file"])
    ws.indent[edit["file"]] = edit["indent"]


def op_set_text(ws, edit):
    rel = edit["file"]
    rows = ws.get_csv(rel)
    column = rows[0].index(edit["locale"])
    _, row = find_row(rows, edit["key"], rel)
    check_from(row[column], edit["from"], f"{rel}:{edit['key']}[{edit['locale']}]")
    row[column] = edit["to"]


def op_move_row(ws, edit):
    rel = edit["file"]
    rows = ws.get_csv(rel)
    index, row = find_row(rows, edit["key"], rel)
    body = rows[1:]
    body.pop(index - 1)
    to_index = edit["to_index"]
    body.insert(len(body) if to_index == -1 else to_index, row)
    rows[1:] = body


def op_add_row(ws, edit):
    rel = edit["file"]
    rows = ws.get_csv(rel)
    values = edit["values"]
    if any(row[0] == values["key"] for row in rows[1:]):
        raise FixtureError(f"{rel}: key '{values['key']}' already exists")
    rows.append([values.get(column, "") for column in rows[0]])


OPS = {
    "set_field": op_set_field,
    "move_entity": op_move_entity,
    "reformat_json": op_reformat_json,
    "set_text": op_set_text,
    "move_row": op_move_row,
    "add_row": op_add_row,
}


def apply_mutation(root, mutation):
    ws = Workspace(root)
    for edit in mutation["edits"]:
        op = OPS.get(edit["op"])
        if op is None:
            raise FixtureError(f"unknown op '{edit['op']}'")
        op(ws, edit)
    return ws


def load_mutations(root):
    return json.loads((Path(root) / "mutations.json").read_text(encoding="utf-8"))


def check_round_trip(root):
    """Clean files must re-serialize byte for byte, so mutated copies diff cleanly."""
    for path in sorted((Path(root) / "data").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        if dump_json(json.loads(text)) != text:
            raise FixtureError(f"{path}: not in canonical JSON form (indent 2, trailing newline)")
    for path in sorted((Path(root) / "locales").glob("*.csv")):
        text = path.read_text(encoding="utf-8")
        if dump_csv(parse_csv(text)) != text:
            raise FixtureError(f"{path}: not in canonical CSV form")


def check_findings(findings, keys, where):
    for finding in findings:
        if finding.get("severity") not in SEVERITIES:
            raise FixtureError(f"{where}: bad severity in {finding}")
        if finding.get("key") not in keys:
            raise FixtureError(f"{where}: unknown key '{finding.get('key')}'")


def validate(root):
    root = Path(root)
    check_round_trip(root)

    clean = Workspace(root)
    ids = [entity["id"] for entity in clean.get_json("data/items.json")]
    keys = [row[0] for row in clean.get_csv("locales/strings.csv")[1:]]
    for name, values in (("entity id", ids), ("key", keys)):
        duplicates = {value for value in values if values.count(value) > 1}
        if duplicates:
            raise FixtureError(f"duplicate {name}s: {sorted(duplicates)}")

    expected_clean = json.loads((root / "expected" / "clean.json").read_text(encoding="utf-8"))
    check_findings(expected_clean["findings"], set(keys), "expected/clean.json")
    if expected_clean["coverage"]["entities"] != len(ids):
        raise FixtureError("expected/clean.json: entity count does not match data")

    mutations = load_mutations(root)
    mutation_ids = [mutation["id"] for mutation in mutations]
    if len(set(mutation_ids)) != len(mutation_ids):
        raise FixtureError("duplicate mutation ids")

    counts = {category: 0 for category in CATEGORIES}
    for mutation in mutations:
        where = f"mutation {mutation['id']}"
        if mutation["category"] not in CATEGORIES:
            raise FixtureError(f"{where}: unknown category '{mutation['category']}'")
        counts[mutation["category"]] += 1
        if mutation["category"] == "negative" and mutation["expected"]:
            raise FixtureError(f"{where}: negative controls must expect no findings")
        try:
            ws = apply_mutation(root, mutation)
        except FixtureError as error:
            raise FixtureError(f"{where}: {error}") from None
        mutated_keys = {row[0] for row in ws.get_csv("locales/strings.csv")[1:]}
        check_findings(mutation["expected"], mutated_keys, where)

    summary = ", ".join(f"{counts[c]} {c}" for c in sorted(CATEGORIES))
    print(f"OK: {len(ids)} entities, {len(keys)} strings, {len(mutations)} mutations ({summary})")


def materialize(root, mutation, out_dir):
    """Write a copy of the fixture with `mutation` applied to `out_dir`."""
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FixtureError(f"{out_dir} is not empty")
    ws = apply_mutation(root, mutation)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in COPIED:
        source = root / name
        if source.is_dir():
            shutil.copytree(source, out_dir / name)
        else:
            shutil.copy2(source, out_dir / name)
    for rel, text in ws.rendered().items():
        (out_dir / rel).write_text(text, encoding="utf-8", newline="\n")


def apply(root, mutation_id, out_dir):
    mutation = next((m for m in load_mutations(root) if m["id"] == mutation_id), None)
    if mutation is None:
        raise FixtureError(f"no mutation '{mutation_id}'")
    materialize(root, mutation, out_dir)
    print(f"Wrote {mutation_id} to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    validate_parser = commands.add_parser("validate", help="check fixture consistency")
    validate_parser.add_argument("fixture")
    apply_parser = commands.add_parser("apply", help="write a mutated copy of the fixture")
    apply_parser.add_argument("fixture")
    apply_parser.add_argument("mutation")
    apply_parser.add_argument("out_dir")
    args = parser.parse_args()

    try:
        if args.command == "validate":
            validate(args.fixture)
        else:
            apply(args.fixture, args.mutation, args.out_dir)
    except FixtureError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
