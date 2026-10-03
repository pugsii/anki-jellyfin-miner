"""Build the compact dictionary data shipped with the add-on (not shipped itself).

    python3 tools/build_data.py JMdict_e.gz accents.txt [yomitan.zip "Tab name" ...]

Sources: JMdict (EDRDG, CC-BY-SA 4.0) http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz
         Kanjium pitch accents (CC-BY-SA 4.0) https://github.com/mifunetoshiro/kanjium
         Then any Yomitan dictionaries, each followed by the name its tab gets on cards, e.g.
         Jitendex (CC-BY-SA 4.0) https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/jitendex-yomitan.zip
         Japanese Wiktionary via kaikki-to-yomitan (CC-BY-SA 4.0) https://huggingface.co/datasets/daxida/wty-release (ja/ja)
Writes jellyfin_miner/data/dictionary.sqlite (looked up from disk, so it costs Anki no memory).
Yomitan entries are kept only for words the miner can pick, rendered to the HTML Yomitan gives Anki.
"""
import gzip
import html
import json
import random
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
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


def structured(node):
    """Yomitan structured content as HTML, the way Yomitan renders it for Anki (data → data-sc-*), slimmed."""
    if isinstance(node, str):
        return html.escape(node, quote=False).replace("\n", "<br>")
    if isinstance(node, list):
        return "".join(structured(n) for n in node)
    if not isinstance(node, dict):
        return ""
    tag = node.get("tag")
    if tag == "br":
        return "<br>"
    if tag in (None, "img"):  # images would need media files
        return ""
    # Of the data attributes, only "content" (the part: sense, glossary, example...) is kept for styling
    attrs = [f'data-sc-content="{html.escape(str(node["data"]["content"]))}"'] if "content" in (node.get("data") or {}) else []
    attrs += [f'{a.lower()}="{html.escape(str(node[a]))}"' for a in ("lang", "href", "colSpan", "rowSpan") if a in node]
    if node.get("style"):
        css = "; ".join(f"{re.sub(r'[A-Z]', lambda m: '-' + m.group().lower(), k)}: {v}" for k, v in node["style"].items())
        attrs.append(f'style="{html.escape(css)}"')
    return f"<{tag}{''.join(' ' + a for a in attrs)}>{structured(node.get('content', ''))}</{tag}>"


def glossary(items):
    return "<br>".join(structured(g["content"]) if isinstance(g, dict) and g.get("type") == "structured-content"
                       else structured(g.get("text", "")) if isinstance(g, dict) else structured(g)
                       for g in items if not (isinstance(g, dict) and g.get("type") == "image") and not isinstance(g, list))


def read_terms(path, forms):
    """{form: [Yomitan term, ...]} for the given forms, in dictionary order."""
    zf, out = zipfile.ZipFile(path), {}
    for member in sorted(n for n in zf.namelist() if n.startswith("term_bank")):
        for term in json.load(zf.open(member)):
            if term[0] in forms:
                out.setdefault(term[0], []).append(term)
    return out


def pointers(term):
    """Where an entry that only points elsewhere sends you: a form-of entry (["むし", ["kanji"]] glosses, e.g.
    Wiktionary's 虫) or a stub like 「かみがた」の漢字表記. [] for a real entry."""
    targets = [g[0] for g in term[5] if isinstance(g, list) and g]
    text = re.sub(r"<[^>]+>|Wiktionary", "", glossary(term[5])).strip()
    stub = re.fullmatch(r"(?:1\.\s*)?「?([^「」。]+?)」?の\S{0,4}表記。?", text)
    return targets + ([stub.group(1)] if stub else [])


def lookup(path, forms, hops=2):
    """{form: [term, ...]} with pointer-only entries replaced by the entries they point to, following up to
    `hops` pointers (仕舞った → 仕舞う → しまう)."""
    terms = read_terms(path, forms)
    real = lambda ts: [t for t in ts if not pointers(t)]
    follow = {f: list(dict.fromkeys(p for t in ts for p in pointers(t))) for f, ts in terms.items() if not real(ts)}
    more = lookup(path, {p for ps in follow.values() for p in ps}, hops - 1) if hops and follow else {}
    return {f: real(ts) or [t for p in follow[f] for t in more.get(p, [])] for f, ts in terms.items()}


def build_yomitan(path, name, wanted):
    """[(form, reading, html)] for Yomitan terms whose form the miner can pick; entries for the same form and
    reading are joined as separate <li> blocks, like Yomitan does."""
    out = {}
    for form, terms in lookup(path, wanted).items():
        for term in terms:
            reading, tags = term[1] or term[0], term[2]
            label = ", ".join(t for t in [tags, name] if t)
            body = glossary(term[5])
            if body:
                out.setdefault((form, reading), []).append(f'<li data-dictionary="{html.escape(name)}"><i>({html.escape(label)})</i> <span>{body}</span></li>')
    return [(f, r, "".join(items)) for (f, r), items in out.items()]


def selftest():
    term = lambda form, gloss: [form, "", "", "", 0, gloss, 0, ""]
    assert pointers(term("虫", [["むし", ["kanji"]]])) == ["むし"]
    assert pointers(term("食べる", ["たべるの漢字表記。"])) == ["たべる"] and pointers(term("髪型", ["「かみがた」の漢字表記。"])) == ["かみがた"]
    assert pointers(term("面接", ["人柄や能力を調べるため、直接その人に会って対話すること。"])) == []
    assert structured({"tag": "li", "style": {"listStyleType": '"①"'}, "data": {"content": "sense", "x": 1}, "content": ["a<b", {"tag": "br"}]}) \
        == '<li data-sc-content="sense" style="list-style-type: &quot;①&quot;">a&lt;b<br></li>'
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "dictionary.sqlite"
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript("create table entry (form text, readings text, rank int, senses text);"
                     "create table pitch (word text, reading text, accent text);"
                     "create table definition (dict text, form text, reading text, html blob);")
    jmdict = build_jmdict(sys.argv[1])
    db.executemany("insert into entry values (?, ?, ?, ?)",
                   ((form, json.dumps(r, ensure_ascii=False), rank_, json.dumps(s, ensure_ascii=False))
                    for form, entries in jmdict.items() for r, rank_, s in entries))
    db.execute("create table zdict (dict text, data blob)")
    for zip_path, name in zip(sys.argv[3::2], sys.argv[4::2]):
        rows = build_yomitan(zip_path, name, set(jmdict))
        # Entries are compressed one by one with a shared preset dictionary of typical markup (a third the size)
        zdict = "".join(h for _, _, h in random.Random(1).sample(rows, min(400, len(rows)))).encode()[-32768:]
        pack = lambda h: (lambda c: c.compress(h.encode()) + c.flush())(zlib.compressobj(9, zdict=zdict))
        db.execute("insert into zdict values (?, ?)", (name, zdict))
        db.executemany("insert into definition values (?, ?, ?, ?)", ((name, f, r, pack(h)) for f, r, h in rows))
        print(name, len(rows), "entries")
    db.executemany("insert into pitch values (?, ?, ?)",
                   (key.split("\t") + [acc] for key, acc in build_pitch(sys.argv[2]).items()))
    db.executescript("create index entry_form on entry (form); create index pitch_word on pitch (word, reading);"
                     "create index definition_form on definition (form); vacuum;")
    db.close()
    print("dictionary.sqlite", round(path.stat().st_size / 1e6, 1), "MB")
