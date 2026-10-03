"""Pick words worth learning from an episode's subtitles, and write sentences with furigana."""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "vendor"))
from janome.tokenizer import Tokenizer  # noqa: E402  (bundled, pure Python)

KANJI = re.compile(r"[一-鿿々〆ヶ]")
# Parts of speech (IPADIC) that carry meaning; particles, names, numbers and pronouns are skipped
CONTENT = {("名詞", "一般"), ("名詞", "サ変接続"), ("名詞", "形容動詞語幹"), ("名詞", "副詞可能"),
           ("動詞", "自立"), ("形容詞", "自立"), ("副詞", "一般"), ("副詞", "助詞類接続")}
_tokenizer = None


def tokens(text):
    global _tokenizer
    _tokenizer = _tokenizer or Tokenizer()  # loading takes a few seconds, so only once
    return list(_tokenizer.tokenize(text))


def hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s or "")


def segments(word, reading):
    """'取り扱う', 'とりあつかう' -> [('取', 'と'), ('り', None), ('扱', 'あつか'), ('う', None)]"""
    parts = re.findall(r"[一-鿿々〆ヶ]+|[^一-鿿々〆ヶ]+", word)
    if not reading or not KANJI.search(word):
        return [(word, None)]
    m = re.fullmatch("".join("(.+?)" if KANJI.match(p) else re.escape(hira(p)) for p in parts), hira(reading))
    if not m:
        return [(word, reading)]
    groups = iter(m.groups())
    return [(p, next(groups)) if KANJI.match(p) else (p, None) for p in parts]


def with_reading(word, reading):
    """Anki furigana for one word: 見逃す + みのがす -> 見逃[みのが]す"""
    return "".join(f" {t}[{r}]" if r else t for t, r in segments(word, reading)).strip()


def sentence(toks, target):
    """Anki furigana for a whole line, with the first occurrence of `target` (a dictionary form) in <b>."""
    out, bold = "", False
    for t in toks:
        piece = t.surface
        if KANJI.search(t.surface) and t.reading != "*":
            piece = "".join(f" {s}[{r}]" if r else s for s, r in segments(t.surface, hira(t.reading)))
        if not bold and t.base_form == target:
            piece, bold = f"<b>{piece}</b>", True
        out += piece
    return out.strip()


def meaning_key(reading, entry):
    """Spelling-independent identity of a word: 子供 and 子ども share こども + "child"."""
    return f"{reading}|{entry['senses'][0][1] if entry['senses'] else ''}"


def with_readings(known, dictionary):
    """Known words plus their kana readings and meaning keys, so a known 一番 also covers いちばん and a
    known 子供 also covers 子ども."""
    out = set(known)
    for word in known:
        entry = dictionary.entry(word)
        if entry:
            out.add(meaning_key(entry["readings"][0], entry))
            if KANJI.search(word):
                out.update(entry["readings"])
    return out


def candidates(cues, known, dictionary, max_rank):
    """Unknown content words in the episode: {word: {"rank", "count", "lines": [cue index], "reading"}}."""
    found = {}
    lines_unknown = Counter()
    for i, (_, _, text) in enumerate(cues):
        seen = set()
        for t in tokens(text):
            base = t.base_form
            if tuple(t.part_of_speech.split(",")[:2]) not in CONTENT or base == "*" or base in known:
                continue
            if not KANJI.search(base) and len(base) < 3:  # short kana words are mostly fillers
                continue
            if base not in found:
                surface_reading = hira(t.reading)
                entry = dictionary.entry(base)
                # prefer the reading that matches how it was said (今日: きょう, not こんにち)
                reading = next((r for r in (entry or {}).get("readings", []) if r[:1] == surface_reading[:1]), None)
                entry = dictionary.entry(base, reading) if entry else None
                if not entry or entry["rank"] > max_rank or meaning_key(reading or entry["readings"][0], entry) in known:
                    found[base] = None
                    continue
                found[base] = {"rank": entry["rank"], "count": 0, "lines": [],
                               "reading": reading or entry["readings"][0], "entry": entry}
            if found[base] and base not in seen:
                found[base]["count"] += 1
                found[base]["lines"].append(i)
                seen.add(base)
                lines_unknown[i] += 1
    words = {w: v for w, v in found.items() if v}
    for v in words.values():
        v["unknown_in_line"] = {i: lines_unknown[i] for i in v["lines"]}
    return words


def pick(words, n):
    """The n most useful words: common ones first (frequency bands of 2,500), repeated ones within a band."""
    return sorted(words, key=lambda w: (words[w]["rank"] // 2500, -words[w]["count"], words[w]["rank"]))[:n]


def best_line(cues, info):
    """The clearest line for a word: fewest other unknown words (i+1), then closest to a comfortable length."""
    return min(info["lines"], key=lambda i: (info["unknown_in_line"][i], abs(len(cues[i][2]) - 18)))


def known_lines(cues, known_words):
    """Lines using words you already have: {word: [cue index]} (to add as extra sentences)."""
    out = defaultdict(list)
    for i, (_, _, text) in enumerate(cues):
        for t in tokens(text):
            if t.base_form in known_words and i not in out[t.base_form]:
                out[t.base_form].append(i)
    return out


if __name__ == "__main__":  # self-check (uses the bundled dictionary)
    from dictionary import Dictionary
    assert segments("取り扱う", "とりあつかう") == [("取", "と"), ("り", None), ("扱", "あつか"), ("う", None)]
    assert with_reading("見逃す", "みのがす") == "見逃[みのが]す"
    toks = tokens("特別に見逃してあげましょう。")
    assert sentence(toks, "見逃す") == "特別[とくべつ]に<b> 見逃[みのが]し</b>てあげましょう。", sentence(toks, "見逃す")
    cues = [(0, 1, "今日も面接だったが見事に落とされたよ。"), (1, 2, "面接は明日だ。"), (2, 3, "特別に見逃してあげましょう。")]
    d = Dictionary()
    assert "子ども" not in candidates([(0, 1, "子どもがいる。")], with_readings({"子供"}, d), d, 24000)
    assert "いちばん" not in candidates([(0, 1, "それがいちばんだ。")], with_readings({"一番"}, d), d, 24000)
    words = candidates(cues, known={"今日", "明日", "特別", "見事"}, dictionary=d, max_rank=24000)
    assert "面接" in words and words["面接"]["count"] == 2 and "今日" not in words, words.keys()
    assert pick(words, 1) == ["面接"] and best_line(cues, words["面接"]) == 1  # the line with fewer unknowns
    print("selftest ok", sorted(words))
