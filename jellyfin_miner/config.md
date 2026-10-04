**Jellyfin Miner** turns anime you watch on Jellyfin into Anki cards: a few useful words per episode, each with the line it was said in, a translation, an audio clip and a screenshot.

**`jellyfin`**: connecting to your server
- `url`: your server's address, e.g. `http://192.168.1.10:8096`
- `api_key`: create one in Jellyfin under *Dashboard → API Keys*
- `user`: the Jellyfin user whose watching should be mined
- `ignored_libraries`: names of libraries to leave out, e.g. `["Discover"]` for a Jellyseerr/JellyBridge library of shows you haven't chosen to watch

**`auto_mine`**: mining in the background
- `enabled`: check for newly watched episodes when Anki opens and every `check_every_minutes` while it's open. Only episodes you actually played count, not ones marked as watched.
- `max_episodes_per_run`: a cap, so a binge doesn't flood your deck. *Tools → Jellyfin Miner → Mine an episode…* works any time.

**`words`**: what gets picked
- `per_episode`: new cards per episode. Words already in your decks are never picked.
- `max_rank`: only words within roughly this many most common Japanese words (up to 24000).
- `known`: note types and fields that hold words you already know, e.g. `{"note_type": "Kaishi 1.5k", "field": "Word"}`. Your `cards` note type always counts.
- `skip_names`: don't pick words the episode uses as people's names (ミント with 〜ちゃん after it is a name, not mint).

**`cards`**: where and how cards are made
- `deck`, `note_type`: where new cards go and which note type they use. The default "Jellyfin Miner" note type is created for you if it doesn't exist.
- `fields`: which note field gets each piece (`word`, `gloss`, `sentence`, `translation`, `sentence_audio`, `picture`, `source`, `grammar`, `definitions`, `pitch`, `frequency`). Use `""` to leave a piece out.
- `max_sentences`: above 1, words you already have get new scenes added as extra sentences (separated by horizontal lines), up to this many, and `extra_sentences_per_episode` per episode. Only for note types built to show several sentences.
- `audio_format`: `"sound"` (Anki plays it automatically) or `"html"` (a play button only).

**`grammar`**: notes on the grammar each sentence uses
- `enabled`: add a note for each JLPT grammar pattern (N5–N1, plus casual speech like 〜ちゃう and 〜じゃん) found in the sentence: the pattern, its level and a one-line meaning.
- `easiest_level`: skip patterns easier than this, e.g. `"N4"` once N5 grammar is second nature.
- `max_per_sentence`: at most this many notes per sentence, hardest first.

**`translation`**
English subtitles at the same moment are used when the episode has them. Otherwise, optionally, any OpenAI-compatible model:
- `base_url`, e.g. `http://127.0.0.1:11434/v1` (Ollama) or `https://api.openai.com/v1`
- `model`, `api_key`
- `extra_prompt`: added to the instructions. For Qwen3 models, `/no_think` makes them much faster.

**Can I watch this yet?**
*Tools → Jellyfin Miner → Can I watch this yet?* shows your library as posters and scores every show, live, by how much of its dialogue you already know (from up to 3 episodes you haven't seen); select one for the words to learn first, or double-click it to mine an episode. 90–95% is the sweet spot. *Mine an episode…* uses the same poster grid.

**Dictionaries**
New cards get Jitendex, English and Japanese Wiktionary, and a Kanji tab. To add your own Yomitan dictionaries (.zip), click *View Files* and put them in `user_files/dictionaries`; they're converted the next time the add-on mines.

**`ffmpeg_path`**: only needed if ffmpeg isn't on your PATH (Anki's Linux Flatpak includes it).
