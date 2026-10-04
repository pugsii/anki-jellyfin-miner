"""Read Yomitan dictionaries (.zip) into the compact form the add-on looks words up in.

Used by tools/build_data.py for the bundled dictionaries, and inside Anki for dictionaries you add yourself.
Entries are rendered to the HTML Yomitan gives Anki ({glossary}), so Kotoba shows each dictionary as a tab.
"""
import html
import json
import random
import re
import zipfile
import zlib


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
    attrs += [f'{a.lower()}="{html.escape(str(node[a]))}"' for a in ("lang", "colSpan", "rowSpan") if a in node]
    if re.match(r"https?://|\?", str(node.get("href", ""))):  # web links and Yomitan's own ?query links only
        attrs.append(f'href="{html.escape(node["href"])}"')
    if node.get("style"):
        css = "; ".join(f"{re.sub(r'[A-Z]', lambda m: '-' + m.group().lower(), k)}: {v}" for k, v in node["style"].items())
        attrs.append(f'style="{html.escape(css)}"')
    return f"<{tag}{''.join(' ' + a for a in attrs)}>{structured(node.get('content', ''))}</{tag}>"


def glossary(items):
    return "<br>".join(structured(g["content"]) if isinstance(g, dict) and g.get("type") == "structured-content"
                       else structured(g.get("text", "")) if isinstance(g, dict) else structured(g)
                       for g in items if not (isinstance(g, dict) and g.get("type") == "image") and not isinstance(g, list))


def title(path):
    with zipfile.ZipFile(path) as zf:
        return json.load(zf.open("index.json")).get("title") or str(path)


def read_terms(path, forms):
    """{form: [Yomitan term, ...]} for the given forms, in dictionary order."""
    out = {}
    with zipfile.ZipFile(path) as zf:
        for member in sorted(n for n in zf.namelist() if n.startswith("term_bank")):
            for term in json.load(zf.open(member)):
                if term[0] in forms:
                    out.setdefault(term[0], []).append(term)
    return out


def pointers(term):
    """Where an entry that only points elsewhere sends you: a form-of entry (["むし", ["kanji"]] glosses, e.g.
    Wiktionary's 虫) or a stub like 「かみがた」の漢字表記 or たべるの漢字表記. [] for a real entry."""
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


def entries(path, name, wanted):
    """[(form, reading, html)] for the dictionary's entries for `wanted` forms; entries for the same form and
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


SCHEMA = "create table if not exists definition (dict text, form text, reading text, html blob);" \
         "create table if not exists zdict (dict text, data blob);" \
         "create index if not exists definition_form on definition (form);"


def store(db, name, rows):
    """Save entries compressed one by one, with a shared preset dictionary of typical markup (a third the size)."""
    zdict = "".join(h for _, _, h in random.Random(1).sample(rows, min(400, len(rows)))).encode()[-32768:]
    pack = lambda h: (lambda c: c.compress(h.encode()) + c.flush())(zlib.compressobj(9, zdict=zdict))
    db.execute("insert into zdict values (?, ?)", (name, zdict))
    db.executemany("insert into definition values (?, ?, ?, ?)", ((name, f, r, pack(h)) for f, r, h in rows))


if __name__ == "__main__":  # self-check
    term = lambda form, gloss: [form, "", "", "", 0, gloss, 0, ""]
    assert pointers(term("虫", [["むし", ["kanji"]]])) == ["むし"]
    assert pointers(term("食べる", ["たべるの漢字表記。"])) == ["たべる"] and pointers(term("髪型", ["「かみがた」の漢字表記。"])) == ["かみがた"]
    assert pointers(term("面接", ["人柄や能力を調べるため、直接その人に会って対話すること。"])) == []
    assert structured({"tag": "li", "style": {"listStyleType": '"①"'}, "data": {"content": "sense", "x": 1}, "content": ["a<b", {"tag": "br"}]}) \
        == '<li data-sc-content="sense" style="list-style-type: &quot;①&quot;">a&lt;b<br></li>'
    assert 'href' not in structured({"tag": "a", "href": "javascript:alert(1)", "content": "x"})
    assert structured({"tag": "a", "href": "https://jitendex.org", "content": "x"}) == '<a href="https://jitendex.org">x</a>'
    print("selftest ok")
