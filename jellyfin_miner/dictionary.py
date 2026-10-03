"""Bundled dictionary data (built by tools/build_data.py), read straight from disk.

JMdict (EDRDG, CC-BY-SA 4.0): readings, an approximate frequency rank and the first senses.
Kanjium (CC-BY-SA 4.0): pitch accents as downstep numbers, e.g. "0" or "0,2".
Jitendex (CC-BY-SA 4.0, English), Japanese and English Wiktionary (CC-BY-SA 4.0): full entries as Yomitan HTML.
KANJIDIC2 (EDRDG, CC-BY-SA 4.0): each kanji's meanings and readings, for the Kanji tab.

Yomitan dictionaries you put in user_files/dictionaries are converted once into user_files/dictionaries.sqlite
(user_files survives add-on updates) and looked up alongside the bundled ones.
"""
import json
import os
import re
import sqlite3
import zlib
from pathlib import Path

if __package__:
    from . import yomitan
else:  # run directly for the self-check
    import yomitan

PATH = Path(__file__).parent / "data" / "dictionary.sqlite"
USER_DIR = Path(__file__).parent / "user_files" / "dictionaries"
KANJI = "漢字"


def user_dictionaries(bundled, folder=USER_DIR):
    """The converted copy of the Yomitan dictionaries in `folder`, rebuilt when the zips change; None if there
    are none. Only entries for words the miner can pick are kept. Converting a big dictionary takes a minute."""
    zips = sorted(folder.glob("*.zip")) if folder.is_dir() else []
    if not zips:
        return None
    stamp = json.dumps([[z.name, z.stat().st_size, int(z.stat().st_mtime)] for z in zips])
    path = folder.parent / "dictionaries.sqlite"
    if path.exists():
        db = sqlite3.connect(path, check_same_thread=False)
        if db.execute("select stamp from source").fetchone() == (stamp,):
            return db
        db.close()
    wanted = {f for (f,) in bundled.execute("select distinct form from entry")}
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(yomitan.SCHEMA + "create table source (stamp text);")
    for z in zips:  # ponytail: any change reconverts every zip; per-zip caching if people add many
        rows = yomitan.entries(z, yomitan.title(z), wanted)
        if rows:
            yomitan.store(db, yomitan.title(z), rows)
    db.execute("insert into source values (?)", (stamp,))
    db.commit()
    db.close()
    os.replace(tmp, path)
    return sqlite3.connect(path, check_same_thread=False)


class Dictionary:
    def __init__(self, path=PATH, user_dir=USER_DIR):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.sources = [self.db] + [db for db in [user_dictionaries(self.db, user_dir)] if db]
        self.zdicts = {name: data for db in self.sources for name, data in db.execute("select dict, data from zdict")}

    def entry(self, word, reading=None):
        """The best entry for a dictionary form: one with this reading if given, else the most common.
        Returns {"readings", "rank", "senses": [[part of speech, glosses], ...]} or None."""
        rows = [{"readings": json.loads(r), "rank": k, "senses": json.loads(s)}
                for r, k, s in self.db.execute("select readings, rank, senses from entry where form = ?", (word,))]
        if reading:
            rows = [e for e in rows if reading in e["readings"]] or rows
        return min(rows, key=lambda e: e["rank"], default=None)

    def definitions(self, word, reading):
        """Every dictionary's entries for a word, in the format Yomitan gives Anki (Kotoba shows one tab per
        dictionary), then its kanji; or "". Entries with the word's reading are preferred; Wiktionary often has none."""
        by_dict = {}
        for db in self.sources:
            for name, r, packed in db.execute("select dict, reading, html from definition where form = ? order by rowid", (word,)):
                by_dict.setdefault(name, []).append((r, packed))
        html = ""
        for name, rows in by_dict.items():
            rows = [x for x in rows if x[0] == reading] or [x for x in rows if x[0] == word] or rows
            unpack = lambda b: (lambda d: d.decompress(b) + d.flush())(zlib.decompressobj(zdict=self.zdicts[name]))
            html += "".join(unpack(b).decode() for _, b in rows)
        kanji = "".join(row[0] for c in dict.fromkeys(word)
                        for row in self.db.execute("select html from kanji where char = ?", (c,)))
        if html and kanji:  # only alongside a real entry: a word no dictionary knows gets no card details anyway
            html += f'<li data-dictionary="{KANJI}"><i>({KANJI}, KANJIDIC)</i> <span>{kanji}</span></li>'
        return f"<ol>{html}</ol>" if html else ""

    def pitch(self, word, reading):
        row = self.db.execute("select accent from pitch where word = ? and reading = ?", (word, reading)).fetchone()
        return row[0] if row else ""


def gloss(entry):
    """A short English meaning: the first gloss of the first sense, without notes in brackets."""
    first = re.sub(r"\([^)]*\)", "", entry["senses"][0][1]) if entry and entry["senses"] else ""
    return re.split(r"[;,]", first)[0].strip()


def definitions_html(entry):
    """The entry as a JMdict dictionary block (the format Yomitan uses, so Kotoba shows it as a tab)."""
    items = "".join(f"<li><i>{pos}</i> {glosses}</li>" for pos, glosses in entry["senses"])
    return f'<ol><li data-dictionary="JMdict"><ol>{items}</ol></li></ol>'


if __name__ == "__main__":  # self-check against the bundled data
    d = Dictionary()
    e = d.entry("面接", "めんせつ")
    assert e and e["readings"][0] == "めんせつ" and gloss(e) == "interview", (e, gloss(e))
    assert gloss(d.entry("たぶん")) == "probably"  # picks the common adverb, not the rare noun
    assert d.pitch("電車", "でんしゃ") == "0,1" and d.entry("ありえない言葉") is None
    assert definitions_html(e).startswith('<ol><li data-dictionary="JMdict">')
    html = d.definitions("面接", "めんせつ")
    assert 'data-dictionary="Jitendex.org"' in html and "interview" in html, html[:300]
    assert 'data-dictionary="Wiktionary 国語"' in html and "対話" in html, html[:300]
    assert "dangerous" in d.definitions("危ない", "あぶない") and d.definitions("ありえない言葉", "") == ""
    assert 'data-dictionary="Wiktionary EN"' in html and f'data-dictionary="{KANJI}"' in html and "face" in html
    # a user dictionary: converted once, looked up alongside the bundled ones, reconverted when it changes
    import tempfile, zipfile
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "dictionaries"
        folder.mkdir()
        with zipfile.ZipFile(folder / "mine.zip", "w") as z:
            z.writestr("index.json", json.dumps({"title": "My 国語"}))
            z.writestr("term_bank_1.json", json.dumps([["面接", "めんせつ", "", "", 0, ["会って人物を見ること。"], 1, ""]], ensure_ascii=False))
        assert 'data-dictionary="My 国語"' in Dictionary(user_dir=folder).definitions("面接", "めんせつ")
        assert 'data-dictionary="My 国語"' in Dictionary(user_dir=folder).definitions("面接", "めんせつ")  # from the cache
        (folder / "mine.zip").unlink()
        assert "My 国語" not in Dictionary(user_dir=folder).definitions("面接", "めんせつ")
    print("selftest ok")
