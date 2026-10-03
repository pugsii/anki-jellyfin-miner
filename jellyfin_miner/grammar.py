"""Grammar notes for a sentence: which JLPT grammar patterns it uses (grammar/*.json, checked by
tools/check_grammar.py), hardest first, as short HTML notes for the card."""
import html
import json
import re
from pathlib import Path

LEVELS = ["N5", "N4", "N3", "N2", "N1"]
_patterns = None


def patterns():
    global _patterns
    if _patterns is None:
        _patterns = [dict(p, rx=re.compile(p["regex"])) for f in sorted((Path(__file__).parent / "grammar").glob("*.json"))
                     for p in json.loads(f.read_text(encoding="utf-8"))]
    return _patterns


def plain(sentence):
    """The sentence as the patterns expect it: no HTML, furigana or spaces."""
    return re.sub(r"<[^>]+>|&nbsp;|\[[^\]]*\]|\s", "", sentence)


def find(sentence, easiest="N5", limit=3):
    """Patterns used in the sentence at `easiest` level or harder, at most `limit`, hardest first. Where two
    overlap, the longer (more specific) one wins, so 〜なければならない isn't reported as 〜ば, nor 〜てしまう as 〜て."""
    text, floor = plain(sentence), LEVELS.index(easiest)
    hits = [(p, m) for p in patterns() for m in [p["rx"].search(text)] if m]
    hits.sort(key=lambda h: (-(h[1].end() - h[1].start()), -LEVELS.index(h[0]["level"]), h[1].start()))
    chosen = []
    for p, m in hits:
        if all(m.end() <= n.start() or m.start() >= n.end() for _, n in chosen) and p["pattern"] not in {q["pattern"] for q, _ in chosen}:
            chosen.append((p, m))
    # the level filter comes after overlaps are settled: an easy pattern still hides the harder fragment inside it
    chosen = [(p, m) for p, m in chosen if LEVELS.index(p["level"]) >= floor]
    chosen.sort(key=lambda h: (-LEVELS.index(h[0]["level"]), h[1].start()))
    return [p for p, _ in chosen[:limit]]


def notes_html(found):
    """One line per pattern: pattern, level, meaning."""
    return "".join(f'<div class="gp"><b>{html.escape(p["pattern"])}</b> <small>{p["level"]}{" · casual" if p.get("casual") else ""}</small> '
                   f'{html.escape(re.sub(r"^casual[ :,]*", "", p["meaning"]) if p.get("casual") else p["meaning"])}</div>' for p in found)


if __name__ == "__main__":  # self-check with stand-in patterns (the real ones are checked by tools/check_grammar.py)
    _patterns = [dict(p, rx=re.compile(p["regex"])) for p in [
        {"pattern": "〜て", "level": "N5", "meaning": "and then", "regex": "(て|で)"},
        {"pattern": "〜てしまう", "level": "N4", "meaning": "do completely / regret", "regex": "(て|で)しま(う|った)"},
        {"pattern": "〜わけじゃない", "level": "N3", "meaning": "it's not that", "regex": "わけ(じゃ|では)ない", "casual": True}]]
    found = find("嫌いな<b> 訳[わけ]</b>じゃない。全部 食[た]べてしまった", "N5")
    assert [p["pattern"] for p in found] == ["〜てしまう"], found  # 訳 has furigana, so the plain text says 訳: no match
    found = find("嫌いなわけじゃない。全部食べてしまった", "N5")
    assert [p["pattern"] for p in found] == ["〜わけじゃない", "〜てしまう"], found  # 〜て overlaps 〜てしまう
    assert find("全部食べてしまった", "N3") == [] and find("食べて", "N5", limit=0) == []
    _patterns.append(dict({"pattern": "〜ば", "level": "N4", "meaning": "if", "regex": "ば"}, rx=re.compile("ば")))
    _patterns.append(dict({"pattern": "〜なければならない", "level": "N5", "meaning": "must", "regex": "なければなら"}, rx=re.compile("なければなら")))
    assert [p["pattern"] for p in find("行かなければならない")] == ["〜なければならない"]
    assert find("行かなければならない", "N4") == []  # 〜ば is part of the N5 pattern, not a note of its own
    assert notes_html(found[:1]) == '<div class="gp"><b>〜わけじゃない</b> <small>N3 · casual</small> it&#x27;s not that</div>'
    assert "casual 〜てしまう" not in notes_html([{"pattern": "〜ちゃう", "level": "N4", "casual": True, "meaning": "casual 〜てしまう"}])
    print("selftest ok")
