import json

from statsay import po
from statsay.config import load_config
from statsay.engine import run

PO = '''msgid ""
msgstr ""
"Language: ja\\n"

#. [item]: id=potion
#: data/items.cfg:3
msgid "Restores 50 HP."
msgstr "HPを50回復する。"

#, fuzzy
msgid "Restores 80 HP."
msgstr "HPを80回復する。"

msgctxt "menu"
msgid "Potion"
msgstr "ポーション"

#, c-format
msgid "Restores 30 MP."
msgstr ""
"MPを30"
"回復する。"
'''


def test_parse_reads_fields_flags_and_lines():
    entries = po.parse(PO)
    potion = entries[1]
    assert potion.fields["msgid"] == "Restores 50 HP." and potion.lines["msgstr"] == 7
    assert potion.usable
    assert not entries[2].usable  # fuzzy
    assert not entries[3].usable  # has a context
    assert entries[4].fields["msgstr"] == "MPを30回復する。" and entries[4].flags == {"c-format"}


def test_flag_adds_fuzzy_and_comment_and_nothing_else():
    new, changed = po.flag(PO, {7: "value_mismatch: heal: text says 50, data says 40"})
    assert changed == 1
    old_lines, new_lines = PO.split("\n"), new.split("\n")
    assert len(new_lines) == len(old_lines) + 2
    block = new_lines[4:10]
    assert block[0] == "# statsay: value_mismatch: heal: text says 50, data says 40"  # translator comment first
    assert block[1:3] == ["#. [item]: id=potion", "#: data/items.cfg:3"]
    assert block[3] == "#, fuzzy"
    assert new_lines[:4] + new_lines[5:7] + new_lines[8:] == old_lines  # only the two lines were inserted


def test_flag_extends_existing_flags_and_is_idempotent():
    new, _ = po.flag(PO, {19: "watched_field_changed: mp changed 30 -> 40"})
    assert "#, c-format, fuzzy" in new
    again, changed = po.flag(new, {20: "watched_field_changed: mp changed 30 -> 40"})  # +1 line: the comment
    assert again == new and changed == 0


def test_flag_keeps_crlf_line_endings():
    crlf = PO.replace("\n", "\r\n")
    new, changed = po.flag(crlf, {7: "value_mismatch"})
    assert changed == 1
    assert "\n" not in new.replace("\r\n", "")


def test_po_source_joins_translations_by_msgid(tmp_path):
    (tmp_path / "statsay.yaml").write_text("""
data_sources: [{id: items, path: items.json}]
localization:
  - {path: en.csv, format: csv, key_column: key, locales: [en]}
  - {path: ja.po, format: po, locale: ja, source_locale: en}
bindings: [{convention: "item.{id}.description", source: items, watched_fields: [heal]}]
claims: {heal: {kind: number, anchors: {en: ["HP"], ja: ["HP"]}}}
""", encoding="utf-8")
    (tmp_path / "items.json").write_text(json.dumps([{"id": "potion", "heal": 40}, {"id": "hi", "heal": 80}]),
                                         encoding="utf-8")
    (tmp_path / "en.csv").write_text("key,en\nitem.potion.description,Restores 50 HP.\n"
                                     "item.hi.description,Restores 80 HP.\n", encoding="utf-8")
    (tmp_path / "ja.po").write_text(PO, encoding="utf-8")
    findings = run(load_config(tmp_path)).findings
    # potion: en and ja (from the PO) both stale. hi: its PO entry is fuzzy, so no ja text is checked.
    assert sorted((f.key, f.locale, f.file, f.line) for f in findings) == [
        ("item.potion.description", "en", "en.csv", 2),
        ("item.potion.description", "ja", "ja.po", 8),
    ]
    ja = next(f for f in findings if f.locale == "ja")
    assert ja.fix["new"] == "40" and ja.fix["line"] == 8
