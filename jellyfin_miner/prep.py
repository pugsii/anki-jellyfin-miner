"""Spoiler-free cards to prepare for a show you haven't watched: its most useful unknown words, with example
sentences that don't come from it.

For each word, up to three sentences, in this order:
1. a scene from an episode you've already watched (any show; real audio and screenshot, so no spoilers),
2. the dictionary's example sentence (Jitendex, from Tatoeba),
3. only if neither exists, a short example written by your translation model.
The words come from the "Can I watch this yet?" sample of the show (its next few unwatched episodes).

Watched episodes' subtitles are indexed once (dictionary forms per line) in user_files/watched.json, so finding
scenes is instant after the first time. No Anki imports, so it's tested outside Anki.
"""
import html
import json
import re
from pathlib import Path

if __package__:
    from . import analysis, scores, subtitles
    from .jellyfin import JAPANESE, label
else:  # run directly for the self-check
    import analysis
    import scores
    import subtitles
    JAPANESE = ("jpn", "ja")
    label = None

INDEX = Path(__file__).parent / "user_files" / "watched.json"


def candidates(counts, known, dictionary, max_rank, limit=40):
    """The show's unknown words worth learning, most said first: [(word, times said)]."""
    unknown = [(w, n) for w, n in counts.items() if not scores.is_known(w, known, dictionary)]
    useful = [(w, n) for w, n in unknown if (e := dictionary.entry(w)) and e["rank"] <= max_rank]
    return sorted(useful, key=lambda x: (-x[1], dictionary.entry(x[0])["rank"]))[:limit]


def gain(counts, known, dictionary, words):
    """(share of the show's words known now, share known after learning `words`)."""
    before, _ = scores.score(counts, known, dictionary)
    after, _ = scores.score(counts, set(known) | set(words), dictionary)
    return before, after


def load_index():
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def index_episode(cues):
    """{dictionary form: [cue indexes]} for the content words of an episode's lines."""
    words = {}
    for i, (_, _, text) in enumerate(cues):
        for t in analysis.tokens(text):
            if tuple(t.part_of_speech.split(",")[:2]) in analysis.CONTENT and t.base_form != "*":
                words.setdefault(t.base_form, [])
                if words[t.base_form][-1:] != [i]:
                    words[t.base_form].append(i)
    return words


def update_index(jf, user_id, ignored=(), log=print):
    """Add every watched episode with Japanese subtitles that isn't indexed yet, and return the index:
    {episode id: {"label", "series", "cues", "words"}}."""
    index = load_index()
    played = jf._get("/Items", userId=user_id, IncludeItemTypes="Episode", Recursive="true", IsPlayed="true",
                     Fields="MediaStreams,MediaSources")["Items"]
    new = [ep for ep in played if ep["Id"] not in index and ep.get("SeriesId") not in ignored]
    for n, ep in enumerate(new, 1):
        log(f"indexing watched episodes ({n} of {len(new)})")
        try:
            subs = jf.subtitles(ep, JAPANESE)
        except Exception:
            continue
        cues = subtitles.parse(*subs) if subs else []
        index[ep["Id"]] = {"label": label(ep), "series": ep.get("SeriesName") or "", "cues": cues,
                           "words": index_episode(cues)}
    if new:
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


def watched_scene(index, word, exclude_series=""):
    """(episode id, cue index) of the clearest watched line using the word (closest to a comfortable length),
    optionally leaving out one show; or None."""
    found = [(ep_id, i) for ep_id, ep in index.items() if ep["series"] != exclude_series for i in ep["words"].get(word, [])]
    return min(found, key=lambda f: abs(len(index[f[0]]["cues"][f[1]][2]) - 18), default=None)


def dictionary_example(definitions):
    """(Japanese, English) from the first example sentence in Jitendex's entry, or None."""
    m = re.search(r'data-sc-content="example-sentence-a">(.*?)</div>.*?data-sc-content="example-sentence-b">(.*?)</div>',
                  definitions, re.S)
    if not m:
        return None
    plain = lambda s: re.sub(r"\s*\[\d+\]$", "", html.unescape(re.sub(r"<rt>.*?</rt>|<[^>]+>", "", s)).strip())  # no footnote marks
    return plain(m.group(1)), plain(m.group(2))


def text_scene(sentence, translation, target, source, grammar_html=""):
    """A scene made of just a sentence (no audio or picture), with furigana and the word in bold."""
    return {"sentence": analysis.sentence(analysis.tokens(sentence), target), "translation": translation,
            "audio": None, "picture": None, "source": source, "grammar": grammar_html}


if __name__ == "__main__":  # self-check (uses the bundled dictionary)
    from dictionary import Dictionary
    d = Dictionary()
    counts = {"面接": 5, "今日": 9, "魔法使い": 7, "あああ": 3}
    known = analysis.with_readings({"今日"}, d)
    words = [w for w, _ in candidates(counts, known, d, 24000)]
    assert words[:2] == ["魔法使い", "面接"] and "今日" not in words and "あああ" not in words, words
    before, after = gain(counts, known, d, ["魔法使い"])
    assert after > before
    cues = [(0, 1, "面接は明日だ。"), (1, 2, "今日も面接だったが、見事に落とされたよ。とても長い一日だった。")]
    idx = {"e1": {"label": "A S1E1", "series": "A", "cues": cues, "words": index_episode(cues)}}
    assert idx["e1"]["words"]["面接"] == [0, 1] and watched_scene(idx, "面接") == ("e1", 0)
    assert watched_scene(idx, "面接", exclude_series="A") is None and watched_scene(idx, "魔法使い") is None
    html_ = d.definitions("面接", "めんせつ")
    ja, en = dictionary_example(html_)
    assert "面接" in ja and "<" not in ja and en and "interview" in en.lower() and not en.endswith("]"), (ja, en)
    s = text_scene(ja, en, "面接", "Jitendex")
    assert "<b>" in s["sentence"] and s["audio"] is None and s["source"] == "Jitendex"
    print("selftest ok")
