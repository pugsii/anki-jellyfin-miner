""""Can I watch this yet?": how much of a show's dialogue you already know, from a few episodes' subtitles.

Word counts per show are cached (user_files/scores.json), so only new shows cost subtitle downloads; the score
itself is recomputed from your current cards each time. 90-95% known is the usual sweet spot for learning.
"""
import json
import re
from collections import Counter
from pathlib import Path

if __package__:
    from . import analysis, subtitles
    from .jellyfin import JAPANESE
else:  # run directly for the self-check
    import analysis
    import subtitles
    JAPANESE = ("jpn", "ja")

CACHE = Path(__file__).parent / "user_files" / "scores.json"
# Casual contractions the analyser reads as verbs (食べちゃう → ちゃう): grammar, not words to learn
CONTRACTIONS = {"ちゃう", "じゃう", "ちまう", "じまう", "とく", "どく", "てる", "でる", "やがる", "ちゃる"}
SAMPLE = 3  # episodes per show


def word_counts(cues, dictionary):
    """How often each content word is said (dictionary forms), leaving out names and short kana fillers, the
    same words the miner would consider, and katakana words: loanwords (バンド, ギター) are easy for English
    speakers, and the rest are mostly made-up names, so either way they'd skew the score."""
    names = analysis.names_used(cues, dictionary)
    counts = Counter()
    for _, _, text in cues:
        for t in analysis.tokens(text):
            base = t.base_form
            if tuple(t.part_of_speech.split(",")[:2]) not in analysis.CONTENT or base in ("*", *CONTRACTIONS) or base in names:
                continue
            if (analysis.KANJI.search(base) or len(base) >= 3) and not re.fullmatch(r"[ァ-ヺー・]+", base):
                counts[base] += 1
    return counts


def is_known(word, known, dictionary):
    """Known as written, or as another spelling of a known word (子ども for 子供, いちばん for 一番)."""
    if word in known:
        return True
    entry = dictionary.entry(word)
    return bool(entry) and analysis.meaning_key(entry["readings"][0], entry) in known


def score(counts, known, dictionary, top=6):
    """(share of the words said that you know, the unknown words said most often that are worth learning)."""
    total = sum(counts.values())
    unknown = Counter({w: n for w, n in counts.items() if not is_known(w, known, dictionary)})
    learnable = [w for w, _ in unknown.most_common() if dictionary.entry(w)][:top]
    return (1 - sum(unknown.values()) / total if total else 0.0), learnable


def sample(episodes):
    """Up to SAMPLE episodes with Japanese text subtitles: the next ones you haven't watched, else the first."""
    def has_subs(ep):
        streams = ep["MediaSources"][0].get("MediaStreams", []) if ep.get("MediaSources") else []
        return any(s["Type"] == "Subtitle" and (s.get("Language") or "").lower() in JAPANESE for s in streams)
    usable = [ep for ep in episodes if has_subs(ep)]
    unwatched = [ep for ep in usable if not ep.get("UserData", {}).get("Played")]
    return (unwatched or usable)[:SAMPLE]


def series_counts(jf, series, user_id, dictionary, cache):
    """Word counts for a show, from the cache when the sampled episodes haven't changed. None without subtitles."""
    episodes = sample(jf.episodes(series["Id"], user_id))
    ids = [ep["Id"] for ep in episodes]
    hit = cache.get(series["Id"])
    if hit and hit["episodes"] == ids:
        return Counter(hit["counts"])
    counts = Counter()
    for ep in episodes:
        subs = jf.subtitles(ep, JAPANESE)
        if subs:
            counts += word_counts(subtitles.parse(*subs), dictionary)
    cache[series["Id"]] = {"name": series["Name"], "episodes": ids, "counts": dict(counts)}
    return counts if counts else None


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":  # self-check (uses the bundled dictionary)
    from dictionary import Dictionary
    d = Dictionary()
    cues = [(0, 1, "今日も面接だった。"), (1, 2, "面接は明日だ。"), (2, 3, "ミントちゃん、面接に行こう。ギターも。忘れちゃう。")]
    counts = word_counts(cues, d)
    assert counts["面接"] == 3 and "ミント" not in counts and "ギター" not in counts and "ちゃう" not in counts, counts
    share, learn = score(counts, analysis.with_readings({"今日", "明日", "行く", "忘れる"}, d), d)
    assert learn == ["面接"] and abs(share - 4 / 7) < 1e-9, (share, learn)
    assert is_known("子ども", analysis.with_readings({"子供"}, d), d)
    eps = [{"Id": "1", "UserData": {"Played": True}, "MediaSources": [{"MediaStreams": [{"Type": "Subtitle", "Language": "jpn"}]}]},
           {"Id": "2", "UserData": {}, "MediaSources": [{"MediaStreams": [{"Type": "Subtitle", "Language": "jpn"}]}]},
           {"Id": "3", "UserData": {}, "MediaSources": [{"MediaStreams": [{"Type": "Subtitle", "Language": "eng"}]}]}]
    assert [e["Id"] for e in sample(eps)] == ["2"] and [e["Id"] for e in sample(eps[:1])] == ["1"]
    print("selftest ok")
