"""Turn a mined word and its scene into note fields, following the configured field mapping.

The mapping (config "fields") says which note field gets each piece; pieces mapped to "" are skipped:
word, gloss, sentence, translation, sentence_audio, picture, source, definitions, pitch, frequency.
"""
import re

from . import analysis, dictionary


def word_fields(word, info, dict_):
    """The word-level pieces of a new note."""
    entry, reading = info["entry"], info["reading"]
    return {"word": analysis.with_reading(word, reading), "gloss": dictionary.gloss(entry),
            "definitions": dictionary.definitions_html(entry), "pitch": dict_.pitch(word, reading),
            "frequency": str(entry["rank"])}


def scene_fields(scene, audio_format):
    """The sentence-level pieces: sentence, translation, sentence_audio, picture, source."""
    audio = scene.get("audio") or ""
    if audio:
        audio = f'<audio src="{audio}"></audio>' if audio_format == "html" else f"[sound:{audio}]"
    picture = f'<img src="{scene["picture"]}">' if scene.get("picture") else ""
    return {"sentence": scene["sentence"], "translation": scene.get("translation", ""),
            "sentence_audio": audio, "picture": picture, "source": scene["source"]}


def new_note_values(pieces, mapping):
    """{note field: value} for a new note."""
    return {field: pieces.get(piece, "") for piece, field in mapping.items() if field}


def sentence_count(note_value):
    return len([s for s in note_value.split("<hr>") if s.strip()])


def append_scene(note, scene_pieces, mapping, max_sentences):
    """Add a scene as one more sentence on an existing multi-sentence note (entries separated by <hr>).
    Returns False if the note is full or already has this sentence."""
    sentence_field = mapping.get("sentence")
    if not sentence_field:
        return False
    current = note[sentence_field]
    plain = lambda s: re.sub(r"<[^>]+>|\[[^\]]*\]|\s", "", s)
    if sentence_count(current) >= max_sentences or plain(scene_pieces["sentence"]) in plain(current):
        return False
    count = sentence_count(current)
    for piece in ("sentence", "translation", "sentence_audio", "picture", "source"):
        field = mapping.get(piece)
        if not field:
            continue
        entries = [e for e in note[field].split("<hr>")] if note[field].strip() else []
        if piece == "picture" and len(entries) == 1 and count > 1:
            continue  # one picture shared by every sentence (a word illustration): leave it
        entries += [""] * (count - len(entries))  # keep entries lined up with sentences
        note[field] = "<hr>".join(entries[:count] + [scene_pieces.get(piece, "")])
    return True
