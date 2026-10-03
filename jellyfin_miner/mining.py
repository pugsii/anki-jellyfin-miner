"""The mining pipeline for one episode. No Anki imports, so it runs (and is tested) outside Anki too."""
import os

from . import analysis, cards, grammar, media, subtitles, translate
from .jellyfin import ENGLISH, JAPANESE, japanese_audio, label


def mine_episode(jf, item, cfg, known, extendable, dict_, workdir, log=print):
    """Plan the cards for one episode.

    known: words already in your decks (never picked as new words);
    extendable: words whose note can take another sentence (scenes get added to those).
    Returns (new, appends): [{"word", "word_fields", "scene", "tags"}] and [{"word", "scene"}]; scenes hold
    media as file paths in `workdir`, to be added to Anki's media folder by the caller.
    """
    subs = jf.subtitles(item, JAPANESE)
    if not subs:
        log(f"{label(item)}: no Japanese text subtitles (or none that are really Japanese), skipped")
        return [], []
    cues = subtitles.parse(*subs)
    english = jf.subtitles(item, ENGLISH)
    english_cues = subtitles.parse(*english) if english else []
    url, headers, track = jf.stream_url(item), jf.stream_headers(), japanese_audio(item)
    ffmpeg = media.find_ffmpeg(cfg.get("ffmpeg_path", ""))
    llm = cfg.get("translation") or {}

    def scene(i, target):
        start, end, text = cues[i]
        english_line = translate.from_subtitles(cues[i], english_cues)
        if not english_line and llm.get("base_url") and llm.get("model"):
            try:
                english_line = translate.with_model(text, llm["base_url"], llm["model"], llm.get("api_key", ""),
                                                    llm.get("extra_prompt", ""))
            except Exception as e:  # the model being down shouldn't lose the card
                log(f"translation failed ({e}); left blank")
        base = os.path.join(workdir, f"jfm_{item['Id'][:8]}_{int(start * 10)}")
        audio, picture = base + ".mp3", base + ".jpg"
        try:
            media.audio_clip(ffmpeg, url, headers, start, end, track, audio)
        except Exception as e:
            log(f"audio clip failed at {start:.0f}s ({e})")
            audio = None
        try:
            media.screenshot(ffmpeg, url, headers, start, end, picture)
        except Exception as e:
            log(f"screenshot failed at {start:.0f}s ({e})")
            picture = None
        minutes, seconds = divmod(int(start), 60)
        g = cfg["grammar"]
        notes = grammar.notes_html(grammar.find(text, g["easiest_level"], g["max_per_sentence"])) if g["enabled"] else ""
        return {"sentence": analysis.sentence(analysis.tokens(text), target), "translation": english_line,
                "audio": audio, "picture": picture, "source": f"{label(item)} {minutes}:{seconds:02d}", "grammar": notes}

    tags = ["jellyfin_miner", "src::anime::" + "_".join((item.get("SeriesName") or "unknown").split())]
    words = analysis.candidates(cues, analysis.with_readings(known, dict_), dict_, cfg["words"]["max_rank"], cfg["words"]["skip_names"])
    new = [{"word": w, "word_fields": cards.word_fields(w, words[w], dict_),
            "scene": scene(analysis.best_line(cues, words[w]), w), "tags": tags}
           for w in analysis.pick(words, cfg["words"]["per_episode"])]
    appends = []
    if cfg["cards"]["max_sentences"] > 1 and extendable:
        for w, lines in list(analysis.known_lines(cues, extendable).items())[:cfg["cards"]["extra_sentences_per_episode"]]:
            appends.append({"word": w, "scene": scene(min(lines, key=lambda i: abs(len(cues[i][2]) - 18)), w)})
    log(f"{label(item)}: {len(words)} unknown words found, {len(new)} new cards, {len(appends)} extra sentences")
    return new, appends
