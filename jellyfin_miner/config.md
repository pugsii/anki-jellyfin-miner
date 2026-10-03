**Jellyfin Miner** turns anime you watch on Jellyfin into Anki cards: a few useful words per episode, each with the line it was said in, a translation, an audio clip and a screenshot.

**Connecting to Jellyfin**
- `jellyfin_url`: your server's address, e.g. `http://192.168.1.10:8096`
- `jellyfin_api_key`: create one in Jellyfin under *Dashboard → API Keys*
- `jellyfin_user`: the Jellyfin user whose watching should be mined
- `ignore_libraries`: names of Jellyfin libraries to leave out, e.g. `["Discover"]` for a Jellyseerr/JellyBridge library of shows you haven't chosen to watch

**When it runs**
- `auto_mine`: check for newly watched episodes when Anki opens and every `check_every_minutes` while it's open. Only episodes you actually played count, not ones marked as watched.
- `max_episodes_per_run`: a cap, so a binge doesn't flood your deck. *Tools → Jellyfin Miner → Mine an episode…* works any time.

**What gets picked**
- `words_per_episode`: new cards per episode. Words already in your decks are never picked.
- `max_rank`: only words within roughly this many most common Japanese words (up to 24000).
- `known_words`: note types and fields that hold words you already know, e.g. `{"note_type": "Kaishi 1.5k", "field": "Word"}`.

**Cards**
- `deck`, `note_type`: where new cards go and which note type they use. The default "Jellyfin Miner" note type is created for you if it doesn't exist.
- `fields`: which note field gets each piece (`word`, `gloss`, `sentence`, `translation`, `sentence_audio`, `picture`, `source`, `definitions`, `pitch`, `frequency`). Use `""` to leave a piece out.
- `max_sentences`: above 1, words you already have get new scenes added as extra sentences (separated by horizontal lines), up to this many, and `extra_sentences_per_episode` per episode. Only for note types built to show several sentences.
- `audio_format`: `"sound"` (Anki plays it automatically) or `"html"` (a play button only).

**Translation**
English subtitles at the same moment are used when the episode has them. Otherwise, optionally, any OpenAI-compatible model:
- `translation.base_url`, e.g. `http://127.0.0.1:11434/v1` (Ollama) or `https://api.openai.com/v1`
- `translation.model`, `translation.api_key`
- `translation.extra_prompt`: added to the instructions. For Qwen3 models, `/no_think` makes them much faster.

**Other**
- `ffmpeg_path`: only needed if ffmpeg isn't on your PATH (Anki's Linux Flatpak includes it).
