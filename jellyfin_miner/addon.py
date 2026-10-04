"""Jellyfin Miner's Anki side: menu, timer, background runs and saving notes. Settings are explained in config.md."""
import datetime
import html
import re
import time
import shutil
import tempfile

from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.qt import (QAbstractItemView, QAction, QComboBox, QDialog, QDialogButtonBox, QFont, QHBoxLayout, QHeaderView,
                    QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QStackedWidget, Qt, QTimer, QTreeWidget,
                    QTreeWidgetItem, QVBoxLayout, QWidget)
from aqt.utils import showInfo, showWarning, tooltip

from . import analysis, cards, grammar, home, mining, posters, prep, scores, subtitles, translate
from .dictionary import Dictionary, gloss
from .jellyfin import ENGLISH, JAPANESE, Jellyfin, label

ADDON = __name__.split(".")[0]  # the add-on's folder name, which Anki keys its config by
STATE = "jellyfin_miner"  # collection config: {"since": ISO time, "done": [episode ids]}
NOTE_TYPE_FIELDS = ["Word", "Meaning", "Sentence", "Translation", "Audio", "Picture", "Source", "Grammar", "Definitions"]
running = False
timer = None
menu = None
warned = False
progress_state = None   # {"label", "fraction"} while mining, for the home screen's progress bar
recent = []             # recently watched shows for the home screen (home.recent_shows), refreshed in the background
recent_at = 0.0
hooked = False


def config():
    """The user's config over the defaults, so settings added in an update have values. Nested settings merge
    too, except the field mapping: that describes the user's note type and is taken as it is."""
    defaults = mw.addonManager.addonConfigDefaults(ADDON) or {}
    user = mw.addonManager.getConfig(ADDON) or {}
    def merge(d, u):
        return {k: merge(d[k], u[k]) if isinstance(d.get(k), dict) and isinstance(u.get(k), dict) and k != "fields"
                else u.get(k, d.get(k)) for k in {*d, *u}}
    return merge(defaults, user)


def configured(c):
    return bool(c["jellyfin"]["url"] and c["jellyfin"]["api_key"] and c["jellyfin"]["user"])


def plain(text):
    return re.sub(r"<[^>]+>|\[[^\]]*\]|\s|&nbsp;", "", text)


def known_words(c):
    """Words in your decks, and {word: note id} for target notes that can take another sentence."""
    known, extendable = set(), {}
    specs = c["words"]["known"] + [{"note_type": c["cards"]["note_type"], "field": c["cards"]["fields"]["word"]}]
    for spec in specs:
        model = mw.col.models.by_name(spec["note_type"])
        names = [f["name"] for f in model["flds"]] if model else []
        if spec["field"] not in names:
            continue
        word_at = names.index(spec["field"])
        sentence = c["cards"]["fields"].get("sentence")
        sentence_at = names.index(sentence) if spec["note_type"] == c["cards"]["note_type"] and sentence in names else None
        for nid, flds in mw.col.db.all("select id, flds from notes where mid = ?", model["id"]):
            fields = flds.split("\x1f")
            word = plain(fields[word_at])
            if not word:
                continue
            known.add(word)
            if sentence_at is not None and cards.sentence_count(fields[sentence_at]) < c["cards"]["max_sentences"]:
                extendable[word] = nid
    return known, extendable


def note_type(c):
    """The configured note type; the simple built-in one is created on first use."""
    models = mw.col.models
    model = models.by_name(c["cards"]["note_type"])
    if model or c["cards"]["note_type"] != "Jellyfin Miner":
        if not model:
            raise ValueError(f'Note type "{c["cards"]["note_type"]}" not found. Check cards → note_type in the add-on config.')
        return model
    model = models.new("Jellyfin Miner")
    for name in NOTE_TYPE_FIELDS:
        models.add_field(model, models.new_field(name))
    template = models.new_template("Recognition")
    template["qfmt"] = '<div class="word">{{kanji:Word}}</div>'
    template["afmt"] = ('{{FrontSide}}<hr id="answer"><div>{{furigana:Word}}</div><div>{{Meaning}}</div>'
                        '<p>{{furigana:Sentence}}</p><p class="small">{{Translation}}</p>{{Audio}}<div>{{Picture}}</div>'
                        '<div class="small">{{Grammar}}</div>'
                        '<p class="small">{{Source}}</p>{{#Definitions}}<details><summary>Dictionary</summary>'
                        '{{Definitions}}</details>{{/Definitions}}')
    models.add_template(model, template)
    model["css"] = (".card { font-family: sans-serif; font-size: 20px; text-align: center; }"
                    ".word { font-size: 48px; } .small { color: gray; font-size: 15px; } img { max-width: 100%; }"
                    "details { text-align: left; font-size: 15px; }")
    models.add_dict(model)
    return models.by_name("Jellyfin Miner")


def add_media(scene):
    """The scene with its media files moved into Anki's media folder (paths -> media file names)."""
    return {**scene, **{k: mw.col.media.add_file(scene[k]) for k in ("audio", "picture") if scene.get(k)}}


def prep_deck(c):
    return c["cards"]["deck"] + "::Prep"


def prep_words(c, extendable):
    """Words whose notes are still prep cards (in the ::Prep subdeck)."""
    did = mw.col.decks.id_for_name(prep_deck(c))
    nids = set(mw.col.find_notes(f"did:{did}")) if did else set()
    return frozenset(w for w, nid in extendable.items() if nid in nids)


def save(results, model, c, extendable, state):
    """Add the planned notes, one episode at a time; each episode is recorded as done once saved, so an error
    part-way never leads to the same episode being mined again (duplicates)."""
    col = mw.col
    deck_id = col.decks.id(c["cards"]["deck"])
    added = extended = 0
    for item, new, appends in results:
        for n in new:
            note = col.new_note(model)
            pieces = {**n["word_fields"], **cards.scene_fields(add_media(n["scene"]), c["cards"]["audio_format"])}
            for field, value in cards.new_note_values(pieces, c["cards"]["fields"]).items():
                if field in note:
                    note[field] = value
            note.tags = n["tags"]
            col.add_note(note, deck_id)
            added += 1
        for a in appends:
            if a["word"] in extendable:
                note = col.get_note(extendable[a["word"]])
                if cards.has_room(note, a["scene"]["sentence"], c["cards"]["fields"], c["cards"]["max_sentences"]):
                    cards.append_scene(note, cards.scene_fields(add_media(a["scene"]), c["cards"]["audio_format"]), c["cards"]["fields"])
                    col.update_note(note)
                    extended += 1
                    # a prep card has met its word in something you watched: it joins your mining deck
                    # (moving keeps its review history)
                    prepped = [cid for cid in note.card_ids() if col.decks.name(col.get_card(cid).did) == prep_deck(c)]
                    if prepped:
                        col.set_deck(prepped, deck_id)
        state["done"] = (state["done"] + [item["Id"]])[-2000:]
        col.set_config(STATE, state)
    return added, extended


def report_error(error, manual):
    """Manual runs show a dialog; automatic ones a tooltip, once per session (Jellyfin may just be unreachable
    from where you are)."""
    global warned
    if manual:
        showWarning(f"Jellyfin Miner: {error}")
    elif not warned:
        warned = True
        tooltip(f"Jellyfin Miner: {error}", period=8000)
    print("jellyfin_miner:", repr(error))


def run(episodes=None, announce=False):
    """Mine `episodes` (manual mode), or newly watched ones (automatic mode). Network, subtitles and ffmpeg
    run in the background; notes are added on the main thread when it's done. `announce` also reports
    when there's nothing new."""
    global running
    manual = episodes is not None
    c = config()
    if running or not mw.col:
        return tooltip("Jellyfin Miner is already running") if manual and running else None
    if not configured(c):
        return showWarning("Set the Jellyfin address, API key and user first: "
                           "Tools → Add-ons → Jellyfin Miner → Config.") if manual else None
    try:
        model = note_type(c)
    except ValueError as e:
        return showWarning(str(e)) if manual else None
    known, extendable = known_words(c)
    prepared = prep_words(c, extendable)  # read here: the collection is only touched on the main thread
    state = mw.col.get_config(STATE, {"since": None, "done": []})
    now = datetime.datetime.now(datetime.timezone.utc)
    utc = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    since = state["since"] or utc(now - datetime.timedelta(days=1))  # first run: only the last day
    workdir, log, failed = tempfile.mkdtemp(prefix="jellyfin_miner_"), [], []
    running = True

    def work():
        jf = Jellyfin(c["jellyfin"]["url"], c["jellyfin"]["api_key"])
        items = episodes
        if not manual:
            user_id = jf.user_id(c["jellyfin"]["user"])
            ignored = jf.ignored_series(user_id, c["jellyfin"]["ignored_libraries"])
            items = [i for i in jf.recently_watched(user_id, since)
                     if i["Id"] not in state["done"] and i.get("SeriesId") not in ignored]
        caught_up = manual or len(items) <= c["auto_mine"]["max_episodes_per_run"]
        dict_, results = Dictionary(), []
        todo = items if manual else items[:c["auto_mine"]["max_episodes_per_run"]]
        for n, item in enumerate(todo):
            def progress(fraction, what, n=n, item=item):
                state_ = {"label": f"Mining {label(item)}: {what}" + (f" (episode {n + 1} of {len(todo)})" if len(todo) > 1 else ""),
                          "fraction": (n + fraction) / len(todo)}
                mw.taskman.run_on_main(lambda: set_progress(state_))
            try:
                new, appends = mining.mine_episode(jf, item, c, known, set(extendable), dict_, workdir, log.append, progress,
                                                   prepared)
            except Exception as e:  # one broken episode shouldn't lose the others; it's retried next time
                log.append(f"{label(item)}: failed ({e})")
                failed.append(label(item))
                continue
            results.append((item, new, appends))
            known.update(n["word"] for n in new)  # never pick the same word twice in one run
        return results, caught_up and not failed

    def done(future):
        global running
        running = False
        set_progress(None)
        if mw.col:
            refresh_recent()  # new cards and newly watched episodes
        try:
            if not mw.col:  # the profile was closed while mining
                return
            results, caught_up = future.result()
            added, extended = save(results, model, c, extendable, state)
        except Exception as e:
            return report_error(e, manual)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if not manual and caught_up:  # with episodes left over (or failed), look from the same point next time
            state["since"] = utc(now)
            mw.col.set_config(STATE, state)
        if failed and not manual:
            report_error(RuntimeError("couldn't mine " + ", ".join(failed) + " (will retry)"), manual)
        shows = ", ".join(dict.fromkeys(label(item) for item, new, appends in results if new or appends))
        if shows:
            summary = f"Jellyfin Miner: {added} new card(s), {extended} extra sentence(s) from {shows}"
            showInfo(summary + "\n\n" + "\n".join(log)) if manual else tooltip(summary, period=6000)
            if mw.state == "deckBrowser":
                mw.deckBrowser.refresh()
        elif manual:
            showWarning(("Jellyfin Miner couldn't mine the selected episodes:" if failed else
                         "Jellyfin Miner found nothing to add:") + "\n\n" + "\n".join(log))
        elif announce:
            tooltip("Jellyfin Miner: no newly watched episodes")

    mw.taskman.run_in_background(work, done)


def shows_for(c):
    """(Jellyfin client, user id, shows outside the ignored libraries), or raises if Jellyfin can't be reached."""
    jf = Jellyfin(c["jellyfin"]["url"], c["jellyfin"]["api_key"])
    user_id = jf.user_id(c["jellyfin"]["user"])
    ignored = jf.ignored_series(user_id, c["jellyfin"]["ignored_libraries"])
    return jf, user_id, [s for s in jf.series(user_id) if s["Id"] not in ignored]


class EpisodePicker(QDialog):
    """Tools → Jellyfin Miner → Mine an episode…: pick a show from its poster, then episodes."""

    def __init__(self, jf, user_id, shows, start=None, parent=None):
        super().__init__(parent or mw)
        self.jf, self.user_id, self.closed = jf, user_id, False
        self.finished.connect(lambda _: setattr(self, "closed", True))
        self.setWindowTitle("Mine an episode")
        self.resize(900, 680)
        self.pages = QStackedWidget()
        # page 1: the shows
        self.grid = posters.ShowGrid()
        for show in shows:
            self.grid.add(show)
        self.grid.itemActivated.connect(lambda item: self.open_show(self.grid.show_at(item)))
        self.grid.itemClicked.connect(lambda item: self.open_show(self.grid.show_at(item)))
        shows_page = QWidget()
        box = QVBoxLayout(shows_page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(posters.search_box(self.grid))
        box.addWidget(self.grid)
        # page 2: its episodes
        back = QPushButton("← All shows")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.episodes = QListWidget()
        self.episodes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.episodes.itemSelectionChanged.connect(self.update_button)
        episodes_page = QWidget()
        box = QVBoxLayout(episodes_page)
        box.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(back)
        top.addWidget(self.title, 1)
        box.addLayout(top)
        box.addWidget(QLabel("Episodes (Ctrl/Shift to pick several)"))
        box.addWidget(self.episodes)
        self.pages.addWidget(shows_page)
        self.pages.addWidget(episodes_page)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Mine selected")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.pages.currentChanged.connect(self.update_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)
        layout.addWidget(self.buttons)
        self.update_button()
        posters.load_posters(jf, shows, self.grid, lambda: self.closed)
        if start:
            self.open_show(start)

    def open_show(self, show):
        if not show:
            return
        self.title.setText(show["Name"])
        self.episodes.clear()
        self.pages.setCurrentIndex(1)
        try:
            episodes = self.jf.episodes(show["Id"], self.user_id)
        except Exception as e:
            return showWarning(f"Couldn't load episodes: {e}", parent=self)
        for ep in episodes:
            streams = ep["MediaSources"][0].get("MediaStreams", []) if ep.get("MediaSources") else []
            has_subs = any(s["Type"] == "Subtitle" and (s.get("Language") or "").lower() in JAPANESE for s in streams)
            watched = "✓ " if ep.get("UserData", {}).get("Played") else ""
            row = QListWidgetItem(f"{watched}S{ep.get('ParentIndexNumber', 0)}E{ep.get('IndexNumber', 0)}  {ep.get('Name', '')}"
                                  + ("" if has_subs else "   (no Japanese subtitles)"))
            row.setData(Qt.ItemDataRole.UserRole, ep)
            if not has_subs:
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.episodes.addItem(row)

    def update_button(self, *_):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.pages.currentIndex() == 1 and bool(self.selected()))

    def selected(self):
        return [row.data(Qt.ItemDataRole.UserRole) for row in self.episodes.selectedItems()]


def pick_episodes(start=None, parent=None):
    c = config()
    if not configured(c):
        return showWarning("Set the Jellyfin address, API key and user first: Tools → Add-ons → Jellyfin Miner → Config.")
    try:
        jf, user_id, shows = shows_for(c)
    except Exception as e:
        return showWarning(f"Couldn't reach Jellyfin: {e}")
    picker = EpisodePicker(jf, user_id, shows, start, parent)
    if picker.exec() and picker.selected():
        run(picker.selected())


def score_badge(share):
    """(text, colour, sort key) for a show's poster: green in the 90%+ sweet spot, amber when watchable with
    effort, grey below; best first when sorted."""
    if share is None:
        return "no subs", "#80000000", 2
    color = "#2e7d32" if share >= 0.9 else "#c77700" if share >= 0.75 else "#5f6368"
    return f"{share:.0%}", color, -share


class ScoreGrid(QDialog):
    """Tools → Jellyfin Miner → Can I watch this yet?: every show's poster with how much of its dialogue you
    know, filled in live as each show is checked."""

    def __init__(self, jf, user_id, shows):
        super().__init__(mw)
        self.jf, self.user_id, self.closed, self.results = jf, user_id, False, {}
        self.finished.connect(lambda _: setattr(self, "closed", True))
        self.setWindowTitle("Can I watch this yet?")
        self.resize(980, 760)
        note = QLabel("How much of each show's dialogue you already know, from up to 3 episodes you haven't seen "
                      "(katakana loanwords and names aside). <b>90–95%</b> is the sweet spot for learning from a show; "
                      "75–90% is watchable with effort, and every word you learn raises the score.")
        note.setWordWrap(True)
        self.grid = posters.ShowGrid()
        for show in shows:
            self.grid.add(show)
            self.grid.set_badge(show["Id"], "…", "#80000000")
        self.grid.currentItemChanged.connect(lambda item, _: self.show_detail(self.grid.show_at(item)))
        self.grid.itemActivated.connect(lambda item: self.mine(self.grid.show_at(item)))
        self.sort = QComboBox()
        self.sort.addItems(["Most known first", "By name"])
        self.sort.currentIndexChanged.connect(lambda _: self.resort())
        self.status = QLabel(f"Checking {len(shows)} shows…")
        top = QHBoxLayout()
        top.addWidget(posters.search_box(self.grid), 1)
        top.addWidget(self.sort)
        self.detail = QLabel("Select a show to see the words to learn first.")
        self.detail.setWordWrap(True)
        self.mine_button = QPushButton("Mine an episode…")
        self.mine_button.setEnabled(False)
        self.mine_button.clicked.connect(lambda: self.mine(self.grid.show_at(self.grid.currentItem())))
        self.prep_button = QPushButton("Prepare for this show…")
        self.prep_button.setToolTip("Spoiler-free cards for this show's most useful unknown words")
        self.prep_button.setEnabled(False)
        self.prep_button.clicked.connect(lambda: prepare(self.grid.show_at(self.grid.currentItem()), self))
        bottom = QHBoxLayout()
        bottom.addWidget(self.detail, 1)
        bottom.addWidget(self.prep_button)
        bottom.addWidget(self.mine_button)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        for part in (note, top, self.grid, self.status, bottom, close):
            layout.addLayout(part) if isinstance(part, QHBoxLayout) else layout.addWidget(part)
        posters.load_posters(jf, shows, self.grid, lambda: self.closed)

    def set_score(self, show_id, share, learn):
        self.results[show_id] = (share, learn)
        text, color, key = score_badge(share)
        self.grid.set_badge(show_id, text, color, key)
        current = self.grid.show_at(self.grid.currentItem())
        if current and current["Id"] == show_id:
            self.show_detail(current)
        self.status.setText(f"Checked {len(self.results)} of {len(self.grid.items)} shows…")

    def finish(self):
        self.status.setText(f"All {len(self.grid.items)} shows checked. Double-click a show to mine an episode.")
        self.resort()

    def resort(self):
        posters.Item.by_name = self.sort.currentIndex() == 1
        self.grid.sortItems()

    def show_detail(self, show):
        self.mine_button.setEnabled(bool(show))
        self.prep_button.setEnabled(bool(show) and (self.results.get(show["Id"]) or (None,))[0] is not None)
        if not show:
            return
        name = html.escape(show["Name"])
        if show["Id"] not in self.results:
            return self.detail.setText(f"<b>{name}</b>: still checking…")
        share, learn = self.results[show["Id"]]
        if share is None:
            return self.detail.setText(f"<b>{name}</b>: no Japanese subtitles to check.")
        self.detail.setText(f"<b>{name}</b>: {share:.0%} known. Learn these first: {html.escape('、'.join(learn)) or '—'}")

    def mine(self, show):
        if show:
            pick_episodes(start=show, parent=self)


class PrepDialog(QDialog):
    """Pick the words to prepare for a show: its most-said unknown words, the top 20 ticked."""

    def __init__(self, show, counts, known, dict_, parent=None):
        super().__init__(parent or mw)
        self.counts, self.known, self.dict_ = counts, known, dict_
        self.setWindowTitle(f"Prepare for {show['Name']}")
        self.resize(640, 660)
        note = QLabel("Spoiler-free cards for the words this show uses most that you don't know yet. Example sentences "
                      "come from anime you've already watched and from the dictionary, never from this show; after you "
                      "watch it, the miner adds its real scenes to these cards.")
        note.setWordWrap(True)
        # one row per word, in columns: tick + word (larger), reading, meaning, times said
        self.words = QTreeWidget()
        self.words.setHeaderLabels(["Word", "Reading", "Meaning", "Said"])
        self.words.setRootIsDecorated(False)
        self.words.setAlternatingRowColors(True)
        self.words.setUniformRowHeights(True)
        word_font = QFont(self.font())
        word_font.setPointSizeF(self.font().pointSizeF() * 1.25)
        for n, (word, said) in enumerate(prep.candidates(counts, known, dict_, config()["words"]["max_rank"])):
            entry = dict_.entry(word)
            row = QTreeWidgetItem([word, entry["readings"][0], gloss(entry), f"{said}×"])
            row.setData(0, Qt.ItemDataRole.UserRole, word)
            row.setFont(0, word_font)
            row.setForeground(1, self.palette().placeholderText())
            row.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked if n < 20 else Qt.CheckState.Unchecked)
            self.words.addTopLevelItem(row)
        header = self.words.header()
        for col, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents,
                                    QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.ResizeToContents)):
            header.setSectionResizeMode(col, mode)
        header.setStretchLastSection(False)
        self.words.itemChanged.connect(lambda *_: self.update_gain())
        self.gain = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        for widget in (note, self.words, self.gain, buttons):
            layout.addWidget(widget)
        self.update_gain()

    def selected(self):
        rows = (self.words.topLevelItem(i) for i in range(self.words.topLevelItemCount()))
        return [row.data(0, Qt.ItemDataRole.UserRole) for row in rows if row.checkState(0) == Qt.CheckState.Checked]

    def update_gain(self):
        words = self.selected()
        before, after = prep.gain(self.counts, self.known, self.dict_, words)
        self.gain.setText(f"You know <b>{before:.0%}</b> of its words now; with these {len(words)}: <b>{after:.0%}</b>.")
        self.ok.setText(f"Create {len(words)} card{'s' if len(words) != 1 else ''}")
        self.ok.setEnabled(bool(words))


def prepare(show, parent=None):
    """Prepare for this show: pick words, then make spoiler-free cards for them in <deck>::Prep."""
    c = config()
    if not show:
        return
    counts = scores.load_cache().get(show["Id"], {}).get("counts")
    if not counts:
        return showInfo("Check this show in Can I watch this yet? first: its words come from that.", parent=parent)
    if running:
        return tooltip("Jellyfin Miner is busy; try again in a minute")
    known, _ = known_words(c)
    dict_ = Dictionary()
    dialog = PrepDialog(show, counts, analysis.with_readings(known, dict_), dict_, parent)
    if dialog.exec() and dialog.selected():
        make_prep_cards(show, dialog.selected())


def make_prep_cards(show, words):
    global running
    c = config()
    try:
        model = note_type(c)
    except ValueError as e:
        return showWarning(str(e))
    workdir, log, running = tempfile.mkdtemp(prefix="jellyfin_miner_"), [], True
    llm = c.get("translation") or {}
    g = c["grammar"]
    notes = lambda text: grammar.notes_html(grammar.find(text, g["easiest_level"], g["max_per_sentence"])) if g["enabled"] else ""

    def progress(fraction, what):
        mw.taskman.run_on_main(lambda: set_progress({"label": f"Preparing {show['Name']}: {what}", "fraction": fraction}))

    def work():
        jf = Jellyfin(c["jellyfin"]["url"], c["jellyfin"]["api_key"])
        user_id = jf.user_id(c["jellyfin"]["user"])
        ignored = jf.ignored_series(user_id, c["jellyfin"]["ignored_libraries"])
        index = prep.update_index(jf, user_id, ignored, log=lambda what: progress(0.0, what))
        dict_, results, episodes = Dictionary(), [], {}
        for n, word in enumerate(words):
            progress(0.1 + 0.9 * n / len(words), f"{word} ({n + 1} of {len(words)})")
            entry = dict_.entry(word)
            fields = cards.word_fields(word, {"entry": entry, "reading": entry["readings"][0]}, dict_)
            scenes, kinds = [], []
            hit = prep.watched_scene(index, word)  # any episode you've watched, this show's included
            if hit:
                ep_id, i = hit
                try:
                    if ep_id not in episodes:
                        item = jf._get("/Items", userId=user_id, Ids=ep_id, Fields="MediaStreams,MediaSources")["Items"][0]
                        try:
                            english = jf.subtitles(item, ENGLISH)
                        except Exception:  # no English line: the translation model fills in
                            english = None
                        episodes[ep_id] = (item, subtitles.parse(*english) if english else [])
                    item, english_cues = episodes[ep_id]
                    cues = [tuple(cue) for cue in index[ep_id]["cues"]]
                    scenes.append(mining.cut_scene(jf, item, cues, i, word, english_cues, c, workdir, log.append))
                    kinds.append("watched")
                except Exception as e:  # the dictionary example still makes a card
                    log.append(f"{word}: couldn't cut the scene ({e})")
            example = prep.dictionary_example(fields["definitions"])
            if example:
                scenes.append(prep.text_scene(*example, word, "Jitendex (Tatoeba)", notes(example[0])))
                kinds.append("dictionary")
            if not scenes and llm.get("base_url") and llm.get("model"):
                made = None
                try:
                    made = translate.example_with_model(word, llm["base_url"], llm["model"], llm.get("api_key", ""),
                                                        llm.get("extra_prompt", ""))
                except Exception as e:
                    log.append(f"{word}: the model couldn't write an example ({e})")
                if made:
                    scenes.append(prep.text_scene(*made, word, "AI example", notes(made[0])))
                    kinds.append("AI")
            results.append((word, fields, scenes, kinds))
        return results

    def done(future):
        global running
        running = False
        set_progress(None)
        try:
            if not mw.col:
                return
            results = future.result()
            deck_id = mw.col.decks.id(prep_deck(c))
            mapping, fmt = c["cards"]["fields"], c["cards"]["audio_format"]
            tag = "prep::" + "_".join(show["Name"].split())
            for word, fields, scenes, kinds in results:
                note = mw.col.new_note(model)
                first = cards.scene_fields(add_media(scenes[0]), fmt) if scenes else {}
                for field, value in cards.new_note_values({**fields, **first}, mapping).items():
                    if field in note:
                        note[field] = value
                for scene in scenes[1:c["cards"]["max_sentences"]]:
                    cards.append_scene(note, cards.scene_fields(add_media(scene), fmt), mapping)
                note.tags = ["jellyfin_miner", tag]
                mw.col.add_note(note, deck_id)
        except Exception as e:
            return report_error(e, True)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        kinds = [k for *_, ks in results for k in ks]
        showInfo(f"Made {len(results)} spoiler-free cards for {show['Name']} in {c['cards']['deck']}::Prep.\n\n"
                 f"{kinds.count('watched')} with a scene from an anime you've watched, {kinds.count('dictionary')} with a "
                 f"dictionary example, {kinds.count('AI')} with an AI-written example."
                 + ("\n\n" + "\n".join(log) if log else ""))
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()

    progress(0.0, "starting")
    mw.taskman.run_in_background(work, done)


score_window = None  # kept open alongside Anki (non-modal), so it isn't garbage-collected


def watch_scores():
    """Open the poster grid at once and score the shows in the background, filling it in live (subtitle
    downloads and posters are cached, so later runs are quick)."""
    global running, score_window
    c = config()
    if not configured(c):
        return showWarning("Set the Jellyfin address, API key and user first: Tools → Add-ons → Jellyfin Miner → Config.")
    if running:
        return tooltip("Jellyfin Miner is busy; try again in a minute")
    try:
        jf, user_id, shows = shows_for(c)
    except Exception as e:
        return showWarning(f"Couldn't reach Jellyfin: {e}")
    known, _ = known_words(c)
    dialog = score_window = ScoreGrid(jf, user_id, shows)
    dialog.show()
    running = True

    def work():
        dict_, cache = Dictionary(), scores.load_cache()
        known_all = analysis.with_readings(known, dict_)
        for show in shows:
            if dialog.closed:
                break
            try:
                counts = scores.series_counts(jf, show, user_id, dict_, cache)
            except Exception:  # one show failing shouldn't lose the rest
                counts = None
            share, learn = scores.score(counts, known_all, dict_) if counts else (None, [])
            mw.taskman.run_on_main(lambda i=show["Id"], s=share, l=learn: dialog.closed or dialog.set_score(i, s, l))
        scores.save_cache(cache)

    def done(future):
        global running
        running = False
        if future.exception() and not dialog.closed:
            return showWarning(f"Couldn't check your shows: {future.exception()}", parent=dialog)
        if not dialog.closed:
            dialog.finish()

    mw.taskman.run_in_background(work, done)


def set_progress(state):
    """Show (or with None, hide) the home screen's progress bar, updating it in place when it's on screen."""
    global progress_state
    progress_state = state
    if mw.state == "deckBrowser":
        mw.deckBrowser.web.eval(home.progress_js(state))


def refresh_recent(force=True):
    """Fetch the recently watched shows (last 60 days) and their posters in the background, then redraw the home
    screen. Without force, only if the list is over 15 minutes old."""
    global recent_at
    c = config()
    if not configured(c) or (not force and time.time() - recent_at < 900):
        return
    recent_at = time.time()

    def work():
        jf = Jellyfin(c["jellyfin"]["url"], c["jellyfin"]["api_key"])
        user_id = jf.user_id(c["jellyfin"]["user"])
        ignored = jf.ignored_series(user_id, c["jellyfin"]["ignored_libraries"])
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        shows = home.recent_shows(jf.recently_watched(user_id, since), ignored)
        for show in shows:
            try:
                posters.cover_bytes(jf, {"Id": show["id"], "ImageTags": {"Primary": show["tag"]}})
            except Exception:  # no poster: a blank tile
                pass
        return shows

    def done(future):
        global recent
        if future.exception():
            return  # Jellyfin unreachable: keep what's shown
        recent = future.result()
        if mw.col and mw.state == "deckBrowser":
            mw.deckBrowser.refresh()

    mw.taskman.run_in_background(work, done)


def cover_url(show):
    path = posters.COVERS / f"{show['id']}-{show['tag']}.jpg"
    return f"/_addons/{ADDON}/user_files/covers/{path.name}" if show["tag"] and path.exists() else None


def cards_from(show):
    """How many notes this show has given you (they're tagged src::anime::<name>)."""
    tag = "src::anime::" + "_".join(show["name"].split())
    return len(mw.col.find_notes('"tag:' + re.sub(r'([\\"*_])', r"\\\1", tag) + '"'))


def on_set_content(web_content, context):
    """Adds the section below the decks. Registered after the other add-ons have loaded, so it adds to a home
    screen the Kotoba Theme has redrawn rather than being replaced by it."""
    if isinstance(context, DeckBrowser) and configured(config()) and mw.col:
        web_content.body += home.section(recent, progress_state, cover_url, cards_from)
        refresh_recent(force=False)


def on_message(handled, message, context):
    if not message.startswith("jfm:show:"):
        return handled
    show = next((s for s in recent if s["id"] == message[9:]), None)
    if show:
        pick_episodes(start={"Id": show["id"], "Name": show["name"]})
    return True, None


def on_profile_open():
    global timer, menu, hooked
    if menu is None:  # profiles can be reopened; add the menu once
        menu = QMenu("Jellyfin Miner", mw)
        for text, action in (("Mine new episodes now", run_now), ("Mine an episode…", pick_episodes),
                             ("Can I watch this yet?", watch_scores)):
            item = QAction(text, mw)
            item.triggered.connect(action)
            menu.addAction(item)
        mw.form.menuTools.addMenu(menu)
    if not hooked:
        mw.addonManager.setWebExports(__name__, r"user_files/covers/.+\.jpg")
        gui_hooks.webview_will_set_content.append(on_set_content)
        gui_hooks.webview_did_receive_js_message.append(on_message)
        hooked = True
    c = config()
    QTimer.singleShot(2000, refresh_recent)
    if c["auto_mine"]["enabled"] and configured(c):
        QTimer.singleShot(15_000, run)
        timer = QTimer(mw)
        timer.timeout.connect(run)
        timer.start(int(max(5, c["auto_mine"]["check_every_minutes"]) * 60_000))


def run_now():
    """Menu: check for newly watched episodes now, and say so if there's nothing new."""
    c = config()
    if not configured(c):
        return showWarning("Set the Jellyfin address, API key and user first: Tools → Add-ons → Jellyfin Miner → Config.")
    tooltip("Jellyfin Miner: checking for newly watched episodes…")
    run(announce=True)


def on_profile_close():
    if timer:
        timer.stop()


gui_hooks.profile_did_open.append(on_profile_open)
gui_hooks.profile_will_close.append(on_profile_close)
