# Jellyfin Miner

An Anki add-on that turns the anime you watch on [Jellyfin](https://jellyfin.org) into flashcards. After you watch an episode, it picks a few useful words you don't have yet and makes a card for each one, with:

- the line the word was said in, with furigana and the word in bold
- an English translation (from the episode's English subtitles, or optionally an AI model)
- an audio clip of the line and a screenshot of the scene
- the grammar the sentence uses: JLPT N5–N1 patterns and casual speech (〜ちゃう, 〜じゃん), each with a one-line meaning
- reading, pitch accent, meaning, and full dictionary entries: Jitendex and English Wiktionary, Japanese Wiktionary (国語), KANJIDIC for each kanji, plus any Yomitan dictionaries you add

Words you already have can get the new scene added as an extra example sentence.

## What else it does

- **Home screen:** below your decks, a progress bar while it mines, and a **Recently watched** row with each show's poster and how many cards it has given you. Click a show to mine more of its episodes.
- **Can I watch this yet?** Your library as a poster grid, each show scored live by how much of its dialogue you already know (90–95% is the sweet spot), with the words to learn first.
- **Prepare for this show:** spoiler-free cards for a show you haven't started: its most-said unknown words, with example sentences from anime you've already watched and from the dictionary, never from the show itself. They go in a `::Prep` subdeck; when you watch the show, each card gets its real scene and moves into your deck (review history kept).
- **Mine an episode:** pick any show and episodes yourself.
- **Search** the poster grids by any of a show's names: Japanese, romaji, English or abbreviations.

## How it picks words

It reads the episode's Japanese subtitles, turns every line into dictionary forms, and drops particles, numbers, names (words the episode uses with 〜さん or 〜ちゃん) and anything already in your decks (spelling variants and kana spellings count as known too). Of what's left, it prefers common words, as ranked by JMdict's frequency bands, and words the episode repeats. For each word it chooses the clearest line: the one with the fewest other unknown words.

Only episodes you actually played count, not ones marked as watched (it checks Jellyfin's activity log).

## Requirements

- Anki (tested with 26.09)
- A Jellyfin server and an API key (*Dashboard → API Keys*)
- Episodes with Japanese **text** subtitles (SRT/ASS; image-based PGS subtitles can't be read). Bazarr with the Jimaku provider can fetch these.
- `ffmpeg` on your PATH (Anki's Linux Flatpak already includes it; on Windows and macOS install it, or set `ffmpeg_path`)

## Install

1. Download `jellyfin_miner.ankiaddon` from the [releases](../../releases).
2. In Anki: *Tools → Add-ons → Install from file…*, pick the file, and restart Anki.
3. *Tools → Add-ons → Jellyfin Miner → Config*: under `jellyfin`, set `url`, `api_key` and `user`.
4. Optionally point it at your own note type and deck (`cards`) and list the note types that hold words you already know (`words` → `known`). Every setting is explained in the config screen.

It checks for newly watched episodes when Anki opens and every 30 minutes; *Tools → Jellyfin Miner* has the rest.

Cards use a simple built-in note type by default. For the full design (example sentences you can flip through, grammar notes, dictionary tabs, listening cards and 13 colour themes), install the **Kotoba Theme** add-on, use its *Tools → Kotoba: install or update note type*, and set `cards.note_type` to `Kotoba`.

## Adding your own dictionaries

Any Yomitan dictionary (.zip) can be added, e.g. a monolingual one you own:

1. *Tools → Add-ons → Jellyfin Miner → View Files*, open `user_files/dictionaries`.
2. Copy the .zip files in, without unzipping them.
3. The next time it mines, the add-on converts them (a minute or two for a big dictionary) and new cards get a tab for each, named by the dictionary's title.

Anki keeps `user_files` when the add-on updates. Remove a zip to stop using it.

## What it connects to

- **Your Jellyfin server**, with your API key: watch history, subtitles, posters, and short audio and video reads for the clips (nothing is downloaded whole).
- **AniList's public API** (anilist.co), only to search the poster grids by other titles: it sends the AniList ids Jellyfin has for your shows, once each, and caches the names.
- **The AI model you configure**, if any (`translation`): the subtitle lines it's asked to translate, and words for example sentences.

Caches live in the add-on's `user_files` folder.

## Building from source

The repository doesn't include the bundled analyser and dictionary data (they're large). To build them:

```bash
pip download janome --no-deps --only-binary=:all: -d /tmp/janome
unzip -q /tmp/janome/Janome-*.whl -d jellyfin_miner/vendor
curl -O http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz
curl -O https://raw.githubusercontent.com/mifunetoshiro/kanjium/master/data/source_files/raw/accents.txt
curl -O http://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz
curl -O http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz
curl -LO https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/jitendex-yomitan.zip
curl -Lo kty-ja-ja.zip https://pub-c3d38cca4dc2403b88934c56748f5144.r2.dev/releases/latest/kty-ja-ja.zip
curl -Lo kty-ja-en.zip https://pub-c3d38cca4dc2403b88934c56748f5144.r2.dev/releases/latest/kty-ja-en.zip
python3 tools/build_data.py JMdict_e.gz accents.txt kanjidic2.xml.gz JMnedict.xml.gz jitendex-yomitan.zip "Jitendex.org" \
    kty-ja-ja.zip "Wiktionary 国語" kty-ja-en.zip "Wiktionary EN"
python3 tools/package.py   # → dist/jellyfin_miner.ankiaddon
```

For development, link or copy `jellyfin_miner/` into Anki's `addons21` folder instead.

The pure-Python modules have self-tests (run them from `jellyfin_miner/`; most need the built data):

```bash
for m in subtitles analysis dictionary translate cards jellyfin yomitan grammar scores titles home prep; do python3 $m.py; done
python3 ../tools/check_grammar.py   # every grammar pattern against its test sentences
```

## Licence and credits

The add-on's code is MIT licensed (see [LICENSE](LICENSE)). The bundled data and analyser keep their own licences:

- [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html), [JMnedict](https://www.edrdg.org/enamdict/enamdict_doc.html) and [KANJIDIC2](https://www.edrdg.org/wiki/index.php/KANJIDIC_Project) © the Electronic Dictionary Research and Development Group, CC BY-SA 4.0
- [Kanjium](https://github.com/mifunetoshiro/kanjium) pitch accent data, CC BY-SA 4.0
- [Jitendex](https://jitendex.org) © Stephen Kraus, CC BY-SA 4.0 (built on JMdict, with Tatoeba example sentences)
- [Japanese](https://ja.wiktionary.org) and [English](https://en.wiktionary.org) Wiktionary via [Kaikki](https://kaikki.org) and [kaikki-to-yomitan](https://github.com/yomidevs/kaikki-to-yomitan), CC BY-SA 4.0
- [Janome](https://github.com/mocobeta/janome) (Apache 2.0) with the mecab-ipadic dictionary (NAIST licence)

Not affiliated with Jellyfin, Anki or AniList.
