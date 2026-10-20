"""Build a Statsay input from Wesnoth's Descent into Darkness AMLAs.

Usage:
    python scripts/wesnoth_did.py build <ref> <out_dir>
    python scripts/wesnoth_did.py check <ref>

`build` downloads utils/amlas.cfg and po/wesnoth-did/ja.po at a pinned Wesnoth
commit and converts them into data/amlas.json, locales/strings.csv and a copy
of fixtures/wesnoth-did/statsay.yaml. Wesnoth is GPL-licensed, so its text is
fetched at run time and never committed here.

`check` builds into a temporary directory, runs Statsay, and compares the
findings with fixtures/wesnoth-did/expected.json for that ref.
"""

import csv
import json
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "wesnoth-did"
RAW = "https://raw.githubusercontent.com/wesnoth/wesnoth/{ref}/{path}"
AMLAS = "data/campaigns/Descent_Into_Darkness/utils/amlas.cfg"
JA_PO = "po/wesnoth-did/ja.po"


def fetch(ref, path):
    with urllib.request.urlopen(RAW.format(ref=ref, path=path), timeout=60) as response:
        return response.read().decode("utf-8")


def parse_amlas(cfg):
    """Each [advancement] as {id, description, fields}, plus notes on skipped effects.

    Field naming: one attack damage bonus becomes `damage`; several become
    `<attack>_damage`. Movement bonuses become `movement`. Resistance becomes
    `resistance` when all damage types share one value, else `resistance_<type>`.
    max_experience and hitpoints effects are not described in the text, so
    they are not extracted.
    """
    advancements, notes = [], []
    for block in re.findall(r"\[advancement\](.*?)\[/advancement\]", cfg, re.S):
        ident = re.search(r"^\s*id=(\S+)", block, re.M)
        description = re.search(r'^\s*description\s*=\s*_\s*"([^"]*)"', block, re.M)
        if not ident or not description:
            continue
        damage, fields = {}, {}
        for effect in re.findall(r"\[effect\](.*?)\[/effect\]", block, re.S):
            keys = dict(re.findall(r"^\s*(\w+)=(.*?)\s*$", effect, re.M))
            target = keys.get("apply_to")
            if target == "attack" and "increase_damage" in keys:
                name = keys.get("name") or keys.get("range") or "attack"
                damage[name] = _int(keys["increase_damage"], ident.group(1), notes)
            elif target == "movement" and "increase" in keys:
                fields["movement"] = _int(keys["increase"], ident.group(1), notes)
            elif target == "resistance":
                inner = re.search(r"\[resistance\](.*?)\[/resistance\]", effect, re.S)
                values = {k: _int(v, ident.group(1), notes)
                          for k, v in re.findall(r"^\s*(\w+)=(\S+)\s*$", inner.group(1), re.M)} if inner else {}
                if len(set(values.values())) == 1:
                    fields["resistance"] = next(iter(values.values()))
                else:
                    fields.update({f"resistance_{k}": v for k, v in values.items()})
        if len(damage) == 1:
            fields["damage"] = next(iter(damage.values()))
        else:
            fields.update({f"{name.replace(' ', '_')}_damage": v for name, v in damage.items()})
        advancements.append({
            "id": ident.group(1),
            "description": description.group(1),
            "fields": {k: v for k, v in fields.items() if v is not None},
        })
    return advancements, notes


def _int(raw, ident, notes):
    try:
        return int(raw)
    except ValueError:
        notes.append(f"{ident}: skipped non-integer value {raw!r}")
        return None


def parse_po(text):
    """msgid -> msgstr for translated, non-fuzzy entries without a context."""
    translations = {}
    for entry in re.split(r"\n\s*\n", text):
        lines = entry.strip().splitlines()
        if any(line.startswith("#,") and "fuzzy" in line for line in lines):
            continue
        fields, current = {}, None
        for line in lines:
            match = re.match(r'^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+"(.*)"$', line)
            if match:
                current = match.group(1)
                fields[current] = match.group(2)
            elif current and re.match(r'^"(.*)"$', line):
                fields[current] += line[1:-1]
        if "msgctxt" in fields or "msgid_plural" in fields:
            continue
        msgid, msgstr = fields.get("msgid"), fields.get("msgstr")
        if msgid and msgstr:
            translations[_unescape(msgid)] = _unescape(msgstr)
    return translations


def _unescape(value):
    return value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def build(ref, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"error: {out_dir} is not empty")
    advancements, notes = parse_amlas(fetch(ref, AMLAS))
    translations = parse_po(fetch(ref, JA_PO))

    ids = [a["id"] for a in advancements]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SystemExit(f"error: duplicate advancement ids {duplicates}")

    (out_dir / "data").mkdir(parents=True)
    (out_dir / "locales").mkdir()
    data = [{"id": a["id"], **a["fields"]} for a in advancements]
    (out_dir / "data" / "amlas.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    with (out_dir / "locales" / "strings.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["key", "en", "ja"])
        for a in advancements:
            writer.writerow([f"amla.{a['id']}.description", a["description"],
                             translations.get(a["description"], "")])
    shutil.copy2(FIXTURE / "statsay.yaml", out_dir / "statsay.yaml")

    translated = sum(1 for a in advancements if a["description"] in translations)
    print(f"{ref}: {len(advancements)} advancements, {translated} with Japanese text -> {out_dir}")
    for note in notes:
        print(f"note: {note}")


def check(ref):
    sys.path.insert(0, str(ROOT / "scripts"))
    import e1
    from statsay.config import load_config
    from statsay.engine import run

    expected_all = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
    if ref not in expected_all:
        raise SystemExit(f"error: no expectation for ref {ref} in expected.json")
    expected = {e1.identity(f) for f in expected_all[ref]["findings"]}

    with tempfile.TemporaryDirectory() as tmp:
        build(ref, Path(tmp) / "input")
        result = run(load_config(Path(tmp) / "input"))
    actual = {e1.identity(f.to_dict()) for f in result.findings}
    for c in result.coverage:
        print(f"coverage: {c.bound} of {c.entities} bound")
    for f in result.findings:
        print(f"{f.severity.upper():<7} {f.rule} {f.locale or '*'} {f.key}: {f.message}  \"{f.text}\"")

    missed, extra = expected - actual, actual - expected
    for item in sorted(missed, key=str):
        print(f"MISSED     {item}")
    for item in sorted(extra, key=str):
        print(f"UNEXPECTED {item}")
    if missed or extra:
        sys.exit(1)
    print(f"OK: findings match expected.json for {ref}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 2 and sys.argv[1] == "build" and len(sys.argv) == 4:
        build(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "check" and len(sys.argv) == 3:
        check(sys.argv[2])
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
