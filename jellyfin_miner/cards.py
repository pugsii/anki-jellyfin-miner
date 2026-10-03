"""Turn a mined word and its scene into note fields, following the configured field mapping.

The mapping (config "fields") says which note field gets each piece; pieces mapped to "" are skipped:
word, gloss, sentence, translation, sentence_audio, picture, source, definitions, pitch, frequency.
"""
import re

if __package__:
    from . import analysis, dictionary
else:  # run directly for the self-check
    import analysis
    import dictionary


def word_fields(word, info, dict_):
    """The word-level pieces of a new note."""
    entry, reading = info["entry"], info["reading"]
    return {"word": analysis.with_reading(word, reading), "gloss": dictionary.gloss(entry),
            "definitions": dict_.definitions(word, reading) or dictionary.definitions_html(entry), "pitch": dict_.pitch(word, reading),
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


def has_room(note, sentence, mapping, max_sentences):
    """Whether a multi-sentence note can take this sentence: not full, and doesn't already have it."""
    field = mapping.get("sentence")
    plain = lambda s: re.sub(r"<[^>]+>|\[[^\]]*\]|\s", "", s)
    return bool(field) and sentence_count(note[field]) < max_sentences and plain(sentence) not in plain(note[field])


def append_scene(note, scene_pieces, mapping):
    """Add a scene as one more sentence on an existing multi-sentence note (entries separated by <hr>).
    Entries line up by position, empty ones included, as the card template reads them. Check has_room first."""
    current = note[mapping["sentence"]]
    count = len(current.split("<hr>")) if current.strip() else 0
    for piece in ("sentence", "translation", "sentence_audio", "picture", "source"):
        field = mapping.get(piece)
        if not field:
            continue
        entries = [e for e in note[field].split("<hr>")] if note[field].strip() else []
        if piece == "picture" and len(entries) == 1 and count > 1:
            continue  # one picture shared by every sentence (a word illustration): leave it
        entries += [""] * (count - len(entries))  # keep entries lined up with sentences
        note[field] = "<hr>".join(entries[:count] + [scene_pieces.get(piece, "")])


if __name__ == "__main__":  # self-check
    mapping = {"sentence": "S", "translation": "T", "sentence_audio": "A", "picture": "P", "source": ""}
    note = {"S": "<hr>二つ目", "T": "<hr>second", "A": "<hr>", "P": "illustration"}  # an empty first entry
    assert has_room(note, "三つ目", mapping, 3) and not has_room(note, "二つ目", mapping, 3)
    append_scene(note, {"sentence": "三つ目", "translation": "third", "sentence_audio": "a3", "picture": "p3"}, mapping)
    assert note == {"S": "<hr>二つ目<hr>三つ目", "T": "<hr>second<hr>third", "A": "<hr><hr>a3", "P": "illustration"}, note
    assert not has_room(note, "四つ目", {"sentence": "S"}, 2)
    print("selftest ok")
