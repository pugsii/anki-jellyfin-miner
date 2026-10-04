"""Every name a show goes by, so the poster grids can be searched in Japanese, romaji or English.

Jellyfin gives a show's name and original title; for anime with an AniList id (most anime metadata plugins set
one), AniList's public API adds the romaji, English, native and alternative titles. Those are cached in
user_files/titles.json, so AniList is only asked about shows it hasn't been asked about before.
"""
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

CACHE = Path(__file__).parent / "user_files" / "titles.json"
ANILIST = "https://graphql.anilist.co"
QUERY = "query($ids:[Int]){Page(perPage:50){media(id_in:$ids,type:ANIME){id title{romaji english native}synonyms}}}"


def normalize(text):
    """Comparable form: no case, accents (Sōsō → sousou), spacing or punctuation, katakana as hiragana."""
    text = unicodedata.normalize("NFKD", text or "")
    # drop accents on Latin letters only: kana voicing marks (ボ = ホ + ゛) must stay
    text = "".join(c for i, c in enumerate(text) if not (unicodedata.combining(c) and i and text[i - 1] < "ɐ"))
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"(?<=o)u|(?<=([aiueo]))\1", "", text)  # romaji long vowels: sōsō, sousou, soosoo → soso
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return re.sub(r"[\W_]+", "", text)


def matches(query, names):
    q = normalize(query)
    return not q or any(q in normalize(n) for n in names)


def anilist_id(show):
    value = (show.get("ProviderIds") or {}).get("AniList")
    return int(value) if value and str(value).isdigit() else None


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch_anilist(ids, timeout=20):
    """{AniList id (str): [titles]} for up to 50 ids per request."""
    out = {}
    for i in range(0, len(ids), 50):
        body = json.dumps({"query": QUERY, "variables": {"ids": ids[i:i + 50]}}).encode()
        request = urllib.request.Request(ANILIST, body, {"Content-Type": "application/json", "Accept": "application/json",
                                                         "User-Agent": "JellyfinMiner (Anki add-on)"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for media in json.load(response)["data"]["Page"]["media"]:
                out[str(media["id"])] = [t for t in (*media["title"].values(), *media["synonyms"]) if t]
    return out


def all_names(shows):
    """{show id: [names]} from Jellyfin, plus AniList's titles (cached; looked up for new shows only)."""
    cache = load_cache()
    missing = sorted({anilist_id(s) for s in shows if anilist_id(s) and str(anilist_id(s)) not in cache})
    if missing:
        try:
            cache.update(fetch_anilist(missing))
            for i in missing:  # remember ids AniList didn't know too, so they aren't asked about every time
                cache.setdefault(str(i), [])
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception:  # offline or rate-limited: search still works with Jellyfin's names
            pass
    return {s["Id"]: list(dict.fromkeys([s["Name"], s.get("OriginalTitle") or "", s.get("SortName") or "",
                                         *cache.get(str(anilist_id(s)), [])])) for s in shows}


if __name__ == "__main__":  # self-check
    assert normalize("Sōsō no Frieren!") == normalize("sousou no frieren") == normalize("soosoo") + "nofrieren" and normalize("ボッチ・ザ・ロック") == "ぼっちざろっく"
    names = ["葬送のフリーレン", "Sousou no Frieren", "Frieren: Beyond Journey's End"]
    assert matches("frieren", names) and matches("Sōsō", names) and matches("beyond journey", names)
    assert matches("sousou", names) and matches("SOSO NO", names) and matches("ふりーれん", names) and matches("", names) and not matches("bocchi", names)
    assert anilist_id({"ProviderIds": {"AniList": "154587"}}) == 154587 and anilist_id({}) is None
    print("selftest ok")
