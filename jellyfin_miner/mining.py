"""The mining pipeline for one episode. No Anki imports, so it runs (and is tested) outside Anki too."""
import os

from . import analysis, cards, grammar, media, subtitles, translate
from .jellyfin import ENGLISH, JAPANESE, japanese_audio, label


def cut_scene(jf, item, cues, i, target, english_cues, cfg, workdir, log=print):
    """Cue i of an episode as a scene: the line (furigana, `target` in bold), its English (from the English
    subtitles, else the configured model), an audio clip and a screenshot, the source, and grammar notes."""
    start, end, text = cues[i]
    llm = cfg.get("translation") or {}
    english_line = translate.from_subtitles(cues[i], english_cues)
    if not english_line and llm.get("base_url") and llm.get("model"):
        try:
            english_line = translate.with_model(text, llm["base_url"], llm["model"], llm.get("api_key", ""),
                                                llm.get("extra_prompt", ""))
        except Exception as e:  # the model being down shouldn't lose the card
            log(f"translation failed ({e}); left blank")
    ffmpeg = media.find_ffmpeg(cfg.get("ffmpeg_path", ""))
    url, headers, track = jf.stream_url(item), jf.stream_headers(), japanese_audio(item)
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


def mine_episode(jf, item, cfg, known, extendable, dict_, workdir, log=print, progress=lambda fraction, what: None,
                 prepared=frozenset()):
    """Plan the cards for one episode.

    known: words already in your decks (never picked as new words);
    extendable: words whose note can take another sentence (scenes get added to those);
    prepared: words from prep cards: each gets this episode's scene if it's used, on top of the usual limit.
    Returns (new, appends): [{"word", "word_fields", "scene", "tags"}] and [{"word", "scene"}]; scenes hold
    media as file paths in `workdir`, to be added to Anki's media folder by the caller.
    progress(fraction of this episode done, what's happening) is called as it goes.
    """
    progress(0.0, "reading subtitles")
    subs = jf.subtitles(item, JAPANESE)
    if not subs:
        log(f"{label(item)}: no Japanese text subtitles (or none that are really Japanese), skipped")
        return [], []
    cues = subtitles.parse(*subs)
    progress(0.05, "finding words")
    english = jf.subtitles(item, ENGLISH)
    english_cues = subtitles.parse(*english) if english else []
    scene = lambda i, target: cut_scene(jf, item, cues, i, target, english_cues, cfg, workdir, log)
    tags = ["jellyfin_miner", "src::anime::" + "_".join((item.get("SeriesName") or "unknown").split())]
    words = analysis.candidates(cues, analysis.with_readings(known, dict_), dict_, cfg["words"]["max_rank"], cfg["words"]["skip_names"])
    picked = analysis.pick(words, cfg["words"]["per_episode"])
    lines = analysis.known_lines(cues, extendable) if cfg["cards"]["max_sentences"] > 1 and extendable else {}
    extra = [(w, l) for w, l in lines.items() if w in prepared] + \
        [(w, l) for w, l in lines.items() if w not in prepared][:cfg["cards"]["extra_sentences_per_episode"]]
    total = len(picked) + len(extra)
    new, appends = [], []
    for w in picked:  # each scene is an audio clip and a screenshot: the slow part
        progress(0.1 + 0.9 * len(new) / max(total, 1), f"clip {len(new) + 1} of {total}")
        new.append({"word": w, "word_fields": cards.word_fields(w, words[w], dict_),
                    "scene": scene(analysis.best_line(cues, words[w]), w), "tags": tags})
    for w, lines in extra:
        progress(0.1 + 0.9 * (len(new) + len(appends)) / max(total, 1), f"clip {len(new) + len(appends) + 1} of {total}")
        appends.append({"word": w, "scene": scene(min(lines, key=lambda i: abs(len(cues[i][2]) - 18)), w)})
    log(f"{label(item)}: {len(words)} unknown words found, {len(new)} new cards, {len(appends)} extra sentences")
    return new, appends
