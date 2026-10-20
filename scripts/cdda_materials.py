"""Build Statsay input from Cataclysm-DDA armor items to test material term claims.

Usage:
    python scripts/cdda_materials.py build <ref> <out_dir>
    python scripts/cdda_materials.py check <ref>

`build` downloads data/json/items/tool_armor.json, every file under
data/json/items/armor/ and data/json/materials.json at a pinned commit, resolves
`copy-from` inheritance for `description` and `material`, and writes:

- data/items.json: per item, `material` (ids sharing a display name merged)
  and `material_family` (variants folded into a base family, see FAMILY)
- locales/strings.csv: English descriptions
- statsay.yaml: vocabulary B v1, copied from fixtures/cdda-materials/ (blind test)
- statsay-v2.yaml: vocabulary B v2 with aliases and contrast cues (written after v1)
- statsay-auto.yaml: vocabulary A, generated: every material id -> its display name

Cataclysm-DDA is CC-BY-SA, so its data is fetched at run time and never committed.

`check` builds into a temporary directory, runs all three vocabularies,
compares B v1 and v2 with fixtures/cdda-materials/expected.json, and prints
every finding so it can be classified by hand.
"""

import csv
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "cdda-materials"
REPO = "CleverRaven/Cataclysm-DDA"
RAW = f"https://raw.githubusercontent.com/{REPO}/{{ref}}/{{path}}"
API = f"https://api.github.com/repos/{REPO}/contents/{{path}}?ref={{ref}}"
FAMILY = {
    "nylon_2": "nylon", "nylon_quilted": "nylon", "nylon_quilted_2": "nylon",
    "cotton_quilted": "cotton", "wool_quilted": "wool", "wool_quilted_2": "wool",
    "leather_treated": "leather",
}


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def item_files(ref, path="data/json/items/armor"):
    files = []
    for entry in json.loads(fetch(API.format(path=path, ref=ref))):
        if entry["type"] == "dir":
            files.extend(item_files(ref, entry["path"]))
        elif entry["name"].endswith(".json"):
            files.append(entry["path"])
    return files


def text(value):
    return value.get("str") if isinstance(value, dict) else value


def material_ids(value):
    return [m.get("type") if isinstance(m, dict) else m for m in value or []]


def resolve(obj, templates, key, seen=()):
    """A field's value after copy-from, extend and delete; None if never set."""
    if key in obj:
        value = obj[key]
    elif "copy-from" in obj and obj["copy-from"] in templates and obj["copy-from"] not in seen:
        value = resolve(templates[obj["copy-from"]], templates, key, (*seen, obj["copy-from"]))
    else:
        value = None
    if key == "material":
        ids = material_ids(value)
        ids += material_ids((obj.get("extend") or {}).get("material"))
        removed = set(material_ids((obj.get("delete") or {}).get("material")))
        return [m for m in ids if m not in removed] or None
    return text(value)


def dedupe(values):
    return list(dict.fromkeys(values))


def build(ref, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"error: {out_dir} is not empty")

    materials = [m for m in json.loads(fetch(RAW.format(ref=ref, path="data/json/materials.json")))
                 if m.get("type") == "material" and "id" in m]
    canonical, names = {}, {}
    for material in materials:
        name = text(material["name"]).lower()
        names.setdefault(name, material["id"])
        canonical[material["id"]] = names[name]

    paths = ["data/json/items/tool_armor.json", *item_files(ref)]
    objects = []
    for path in paths:
        loaded = json.loads(fetch(RAW.format(ref=ref, path=path)))
        objects.extend(o for o in (loaded if isinstance(loaded, list) else [loaded]) if isinstance(o, dict))
    templates = {o.get("id") or o.get("abstract"): o for o in objects
                 if isinstance(o.get("id") or o.get("abstract"), str)}

    data, rows = [], []
    for obj in objects:
        ident = obj.get("id")
        if not isinstance(ident, str):
            continue
        material = resolve(obj, templates, "material")
        description = resolve(obj, templates, "description")
        if not material or not description:
            continue
        data.append({"id": ident,
                     "material": dedupe(canonical.get(m, m) for m in material),
                     "material_family": dedupe(FAMILY.get(m, m) for m in material)})
        rows.append([f"item.{ident}.description", description])
    ids = [d["id"] for d in data]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:  # keep the first definition, as the game loads one per id
        seen = set()
        keep = [i for i, d in enumerate(data) if not (d["id"] in seen or seen.add(d["id"]))]
        data, rows = [data[i] for i in keep], [rows[i] for i in keep]

    (out_dir / "data").mkdir(parents=True)
    (out_dir / "locales").mkdir()
    (out_dir / "data" / "items.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    with (out_dir / "locales" / "strings.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["key", "en"])
        writer.writerows(rows)
    shutil.copy2(FIXTURE / "statsay.yaml", out_dir / "statsay.yaml")
    shutil.copy2(FIXTURE / "statsay-v2.yaml", out_dir / "statsay-v2.yaml")

    auto = yaml.safe_load((FIXTURE / "statsay.yaml").read_text(encoding="utf-8"))
    auto["bindings"][0]["watched_fields"] = ["material"]
    auto["claims"] = {"material": {"kind": "enum", "vocabulary": {
        names[name]: {"en": [name]} for name in sorted(names)}}}
    (out_dir / "statsay-auto.yaml").write_text(
        "# Vocabulary A, generated: every material id -> its display name.\n"
        + yaml.safe_dump(auto, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    print(f"{ref[:9]}: {len(paths)} files, {len(data)} items with a description and materials"
          f"{f'; {len(duplicates)} duplicate ids kept once' if duplicates else ''}")


def check(ref):
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate
    from statsay.config import load_config
    from statsay.engine import run

    expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))[ref]
    with tempfile.TemporaryDirectory() as tmp:
        build(ref, Path(tmp) / "input")
        materials = {d["id"]: d for d in json.loads((Path(tmp) / "input/data/items.json").read_text("utf-8"))}
        results = {name: run(load_config(Path(tmp) / "input" / name))
                   for name in ("statsay.yaml", "statsay-v2.yaml", "statsay-auto.yaml")}

    failed = False
    for name, label in (("statsay.yaml", "B v1 (hand-written, blind)"), ("statsay-v2.yaml", "B v2 (aliases, cues)"),
                        ("statsay-auto.yaml", "A (generated)")):
        result = results[name]
        flagged = sorted({f.key for f in result.findings})
        print(f"\n== Vocabulary {label}: {result.stats['checked']} strings checked, "
              f"{len(result.findings)} findings on {len(flagged)} items")
        for f in result.findings:
            item = materials[f.entity.split(".", 1)[1]]
            shown = item["material_family"] if name == "statsay.yaml" else item["material"]
            print(f"  {f.entity:42} text names {f.claimed!r:14} data {shown}")
            print(f"      \"{f.text[:150]}\"")

    for name in ("statsay.yaml", "statsay-v2.yaml"):
        actual = {evaluate.identity(f.to_dict()) for f in results[name].findings}
        for item in expected[name]["required"]:
            if evaluate.identity(item) not in actual:
                print(f"MISSED     {name}: {item}")
                failed = True
        for key in expected[name]["forbidden_keys"]:
            if any(f.key == key for f in results[name].findings):
                print(f"UNEXPECTED {name}: finding on {key}")
                failed = True
    if failed:
        sys.exit(1)
    print(f"\nOK: vocabularies B v1 and v2 match expected.json for {ref[:9]}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) == 4 and sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
