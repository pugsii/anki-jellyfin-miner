# Jellyfin Miner

An Anki add-on that turns the anime you watch on [Jellyfin](https://jellyfin.org) into flashcards. After you watch an episode, it picks a few useful words you don't have yet and makes a card for each one, with:

- the line the word was said in, with furigana and the word in bold
- an English translation (from the episode's English subtitles, or optionally an AI model)
- an audio clip of the line and a screenshot of the scene
- the grammar the sentence uses: JLPT N5–N1 patterns and casual speech (〜ちゃう, 〜じゃん), with a one-line meaning
- reading, pitch accent, meaning, and full dictionary entries: Jitendex and English Wiktionary (English), Japanese Wiktionary (国語), KANJIDIC (each kanji), plus any Yomitan dictionaries you add

Words you already have can also get the new scene added as an extra example sentence.

On Anki's home screen, below your decks, a progress bar shows mining as it happens, and a **Recently watched** row shows the shows you've watched lately with how many cards each has given you (click one to mine more episodes).

Also in *Tools → Jellyfin Miner*: **Can I watch this yet?** shows your library as a poster grid and scores each show, live, by how much of its dialogue you already know, with the words to learn first. **Mine an episode…** picks shows from the same grid. **Prepare for this show…** makes spoiler-free cards for a show you haven't started: its most-said unknown words, with example sentences from anime you've already watched (real scenes) and from the dictionary, never from the show itself. They go in a `::Prep` subdeck, and once you watch the show the miner adds its real scenes to them. Posters are cached in `user_files/covers`. Search by any of a show's names (Japanese, romaji, English, abbreviations): for anime with an AniList id in Jellyfin, the add-on asks [AniList](https://anilist.co)'s public API for its titles once and caches them in `user_files/titles.json`.

## How it picks words

It reads the episode's Japanese subtitles, turns every line into dictionary forms, and drops particles, names, numbers names (a word used with 〜さん or 〜ちゃん in the episode), and anything already in your decks (spelling variants and kana spellings count as known too). Of what's left, it prefers common words, as ranked by JMdict's frequency bands, and words the episode repeats. For each word it chooses the clearest line: the one with the fewest other unknown words.

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

## Adding your own dictionaries

Any Yomitan dictionary (.zip) can be added, e.g. a monolingual one you own:

1. *Tools → Add-ons → Jellyfin Miner → View Files*, open `user_files/dictionaries`.
2. Copy the .zip files in, without unzipping them.
3. The next time it mines, the add-on converts them (a minute or two for a big dictionary) and new cards get a tab for each, named by the dictionary's title.

Anki keeps `user_files` when the add-on updates. Remove a zip to stop using it.

## Building from source

The repository doesn't include the bundled analyser and dictionary (they're large). To build them:

```bash
pip download janome --no-deps --only-binary=:all: -d /tmp/janome
unzip -q /tmp/janome/Janome-*.whl -d jellyfin_miner/vendor
curl -O http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz
curl -O https://raw.githubusercontent.com/mifunetoshiro/kanjium/master/data/source_files/raw/accents.txt
curl -O http://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz
curl -LO https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/jitendex-yomitan.zip
curl -Lo kty-ja-ja.zip https://pub-c3d38cca4dc2403b88934c56748f5144.r2.dev/releases/latest/kty-ja-ja.zip
curl -Lo kty-ja-en.zip https://pub-c3d38cca4dc2403b88934c56748f5144.r2.dev/releases/latest/kty-ja-en.zip
curl -O http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz
python3 tools/build_data.py JMdict_e.gz accents.txt kanjidic2.xml.gz JMnedict.xml.gz jitendex-yomitan.zip "Jitendex.org" \
    kty-ja-ja.zip "Wiktionary 国語" kty-ja-en.zip "Wiktionary EN"
```

The pure-Python modules have self-tests: `cd jellyfin_miner && python3 subtitles.py && python3 analysis.py && python3 dictionary.py && python3 translate.py && python3 cards.py && python3 jellyfin.py && python3 yomitan.py && python3 grammar.py && python3 scores.py && python3 titles.py && python3 home.py && python3 prep.py`, and `python3 tools/check_grammar.py` checks the grammar patterns.

## Credits and licences

- [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html) © the Electronic Dictionary Research and Development Group, CC BY-SA 4.0
- [Kanjium](https://github.com/mifunetoshiro/kanjium) pitch accent data, CC BY-SA 4.0
- [Jitendex](https://jitendex.org) © Stephen Kraus, CC BY-SA 4.0 (English definitions; built on JMdict with Tatoeba example sentences)
- [Japanese](https://ja.wiktionary.org) and [English](https://en.wiktionary.org) Wiktionary via [Kaikki](https://kaikki.org) and [kaikki-to-yomitan](https://github.com/yomidevs/kaikki-to-yomitan), CC BY-SA 4.0
- [JMnedict](https://www.edrdg.org/enamdict/enamdict_doc.html) © the Electronic Dictionary Research and Development Group, CC BY-SA 4.0 (names filter)
- [KANJIDIC2](https://www.edrdg.org/wiki/index.php/KANJIDIC_Project) © the Electronic Dictionary Research and Development Group, CC BY-SA 4.0
- [Janome](https://github.com/mocobeta/janome) (Apache 2.0) with the mecab-ipadic dictionary (NAIST licence)
