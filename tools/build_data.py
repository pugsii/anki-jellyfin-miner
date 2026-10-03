"""Build the compact dictionary data shipped with the add-on (not shipped itself).

    python3 tools/build_data.py JMdict_e.gz accents.txt

Sources: JMdict (EDRDG, CC-BY-SA 4.0) http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz
         Kanjium pitch accents (CC-BY-SA 4.0) https://github.com/mifunetoshiro/kanjium
Writes jellyfin_miner/data/dictionary.sqlite (looked up from disk, so it costs Anki no memory).
"""
import gzip
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_RANK = 24000  # keep words with JMdict frequency markers; the miner's max_rank setting tops out here
OUT = Path(__file__).resolve().parent.parent / "jellyfin_miner" / "data"


def rank(priorities):
    """Approximate frequency rank from JMdict priority tags (nfXX = XXth band of 500 newspaper words)."""
    nf = [int(p[2:]) for p in priorities if p.startswith("nf")]
    if nf:
        return min(nf) * 500
    if any(p.endswith("1") for p in priorities):   # news1 / ichi1 / spec1 / gai1
        return 12000
    if priorities:                                   # news2 / ichi2 / spec2 / gai2
        return 24000
    return 60000


def build_jmdict(path):
    """{form: [[reading, ...], rank, [[pos, gloss; gloss], ...]]}, entries for a form in JMdict order."""
    out = {}
    for _, e in ET.iterparse(gzip.open(path), events=("end",)):
        if e.tag != "entry":
            continue
        kebs = [(k.findtext("keb"), [p.text for p in k.iterfind("ke_pri")]) for k in e.iterfind("k_ele")]
        rebs = [(r.findtext("reb"), [p.text for p in r.iterfind("re_pri")]) for r in e.iterfind("r_ele")]
        senses, pos = [], []
        for s in e.iterfind("sense"):
            pos = [p.text for p in s.iterfind("pos")] or pos
            short = ", ".join(dict.fromkeys(re.sub(r"\s*\([^)]*\)", "", p).strip() for p in pos))
            senses.append([short, "; ".join(g.text for g in s.iterfind("gloss"))])
        entry_rank = rank([p for _, ps in kebs + rebs for p in ps])
        if entry_rank > MAX_RANK:  # unmarked rare words: never picked, and furigana comes from the analyser
            e.clear()
            continue
        readings = [r for r, _ in rebs]
        for form, _ in kebs or rebs:
            out.setdefault(form, []).append([readings, entry_rank, senses[:5]])
        if kebs:  # kana spellings of kanji words, for words usually written in kana
            for form, _ in rebs:
                out.setdefault(form, []).append([[form], entry_rank, senses[:5]])
        e.clear()
    return out


def build_pitch(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        word, reading, accents = (line.rstrip("\n").split("\t") + ["", ""])[:3]
        nums = list(dict.fromkeys(re.findall(r"\d+", accents)))
        if nums:
            out[f"{word}\t{reading or word}"] = ",".join(nums)
    return out


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "dictionary.sqlite"
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript("create table entry (form text, readings text, rank int, senses text);"
                     "create table pitch (word text, reading text, accent text);")
    db.executemany("insert into entry values (?, ?, ?, ?)",
                   ((form, json.dumps(r, ensure_ascii=False), rank_, json.dumps(s, ensure_ascii=False))
                    for form, entries in build_jmdict(sys.argv[1]).items() for r, rank_, s in entries))
    db.executemany("insert into pitch values (?, ?, ?)",
                   (key.split("\t") + [acc] for key, acc in build_pitch(sys.argv[2]).items()))
    db.executescript("create index entry_form on entry (form); create index pitch_word on pitch (word, reading); vacuum;")
    db.close()
    print("dictionary.sqlite", round(path.stat().st_size / 1e6, 1), "MB")
