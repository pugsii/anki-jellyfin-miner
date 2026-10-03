"""Bundled dictionary data (built by tools/build_data.py), read straight from disk.

JMdict (EDRDG, CC-BY-SA 4.0): readings, an approximate frequency rank and the first senses.
Kanjium (CC-BY-SA 4.0): pitch accents as downstep numbers, e.g. "0" or "0,2".
Jitendex (CC-BY-SA 4.0, English) and Japanese Wiktionary (CC-BY-SA 4.0, Japanese): full entries as Yomitan HTML.
"""
import json
import re
import sqlite3
import zlib
from pathlib import Path

PATH = Path(__file__).parent / "data" / "dictionary.sqlite"


class Dictionary:
    def __init__(self, path=PATH):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.zdicts = dict(self.db.execute("select dict, data from zdict"))

    def entry(self, word, reading=None):
        """The best entry for a dictionary form: one with this reading if given, else the most common.
        Returns {"readings", "rank", "senses": [[part of speech, glosses], ...]} or None."""
        rows = [{"readings": json.loads(r), "rank": k, "senses": json.loads(s)}
                for r, k, s in self.db.execute("select readings, rank, senses from entry where form = ?", (word,))]
        if reading:
            rows = [e for e in rows if reading in e["readings"]] or rows
        return min(rows, key=lambda e: e["rank"], default=None)

    def definitions(self, word, reading):
        """The bundled dictionaries' entries for a word, in the format Yomitan gives Anki (Kotoba shows one tab
        per dictionary), or "". Entries with the word's reading are preferred; Wiktionary often has none."""
        by_dict = {}
        for name, r, packed in self.db.execute("select dict, reading, html from definition where form = ? order by rowid", (word,)):
            by_dict.setdefault(name, []).append((r, packed))
        html = ""
        for name, rows in by_dict.items():
            rows = [x for x in rows if x[0] == reading] or [x for x in rows if x[0] == word] or rows
            unpack = lambda b: (lambda d: d.decompress(b) + d.flush())(zlib.decompressobj(zdict=self.zdicts[name]))
            html += "".join(unpack(b).decode() for _, b in rows)
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
    print("selftest ok")
