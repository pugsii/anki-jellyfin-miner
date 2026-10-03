# Jellyfin Miner

An Anki add-on that turns the anime you watch on [Jellyfin](https://jellyfin.org) into flashcards. After you watch an episode, it picks a few useful words you don't have yet and makes a card for each one, with:

- the line the word was said in, with furigana and the word in bold
- an English translation (from the episode's English subtitles, or optionally an AI model)
- an audio clip of the line and a screenshot of the scene
- reading, pitch accent, meaning and a dictionary entry

Words you already have can also get the new scene added as an extra example sentence.

## How it picks words

It reads the episode's Japanese subtitles, turns every line into dictionary forms, and drops particles, names, numbers and anything already in your decks (spelling variants and kana spellings count as known too). Of what's left, it prefers common words, as ranked by JMdict's frequency bands, and words the episode repeats. For each word it chooses the clearest line: the one with the fewest other unknown words.

Only episodes you actually played count, not ones marked as watched (it checks Jellyfin's activity log).

## Requirements

- Anki 25.02 or newer
- A Jellyfin server and an API key (*Dashboard → API Keys*)
- Episodes with Japanese **text** subtitles (SRT/ASS; image-based PGS subtitles can't be read). Bazarr with the Jimaku provider can fetch these.
- `ffmpeg` on your PATH (Anki's Linux Flatpak already includes it; on Windows and macOS install it, or set `ffmpeg_path`)

## Setup

1. Install the add-on, then open *Tools → Add-ons → Jellyfin Miner → Config*.
2. Under `jellyfin`, set `url`, `api_key` and `user`.
3. Optionally point it at your own note type and deck (`cards`) and list the note types that hold words you already know (`words` → `known`). Every setting is explained in the config screen.

It checks for newly watched episodes when Anki opens and every 30 minutes. *Tools → Jellyfin Miner → Mine an episode…* mines any episode on demand.

## Building from source

The repository doesn't include the bundled analyser and dictionary (they're large). To build them:

```bash
pip download janome --no-deps --only-binary=:all: -d /tmp/janome
unzip -q /tmp/janome/Janome-*.whl -d jellyfin_miner/vendor
curl -O http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz
curl -O https://raw.githubusercontent.com/mifunetoshiro/kanjium/master/data/source_files/raw/accents.txt
python3 tools/build_data.py JMdict_e.gz accents.txt
```

The pure-Python modules have self-tests: `cd jellyfin_miner && python3 subtitles.py && python3 analysis.py && python3 dictionary.py && python3 translate.py && python3 cards.py && python3 jellyfin.py`.

## Credits and licences

- [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html) © the Electronic Dictionary Research and Development Group, CC BY-SA 4.0
- [Kanjium](https://github.com/mifunetoshiro/kanjium) pitch accent data, CC BY-SA 4.0
- [Janome](https://github.com/mocobeta/janome) (Apache 2.0) with the mecab-ipadic dictionary (NAIST licence)
