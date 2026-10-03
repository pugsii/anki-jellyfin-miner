"""Jellyfin Miner: Anki cards from the anime you watch on Jellyfin. Settings are explained in config.md."""
import datetime
import re
import shutil
import tempfile

from aqt import gui_hooks, mw
from aqt.qt import (QAbstractItemView, QAction, QComboBox, QDialog, QDialogButtonBox, QLabel, QListWidget,
                    QListWidgetItem, QMenu, Qt, QTimer, QVBoxLayout)
from aqt.utils import showInfo, showWarning, tooltip

from . import cards, mining
from .dictionary import Dictionary
from .jellyfin import JAPANESE, Jellyfin, label

STATE = "jellyfin_miner"  # collection config: {"since": ISO time, "done": [episode ids]}
NOTE_TYPE_FIELDS = ["Word", "Meaning", "Sentence", "Translation", "Audio", "Picture", "Source", "Definitions"]
running = False
timer = None
menu = None


def config():
    return mw.addonManager.getConfig(__name__)


def configured(c):
    return bool(c["jellyfin_url"] and c["jellyfin_api_key"] and c["jellyfin_user"])


def plain(text):
    return re.sub(r"<[^>]+>|\[[^\]]*\]|\s|&nbsp;", "", text)


def known_words(c):
    """Words in your decks, and {word: note id} for target notes that can take another sentence."""
    known, extendable = set(), {}
    specs = c["known_words"] + [{"note_type": c["note_type"], "field": c["fields"]["word"]}]
    for spec in specs:
        model = mw.col.models.by_name(spec["note_type"])
        names = [f["name"] for f in model["flds"]] if model else []
        if spec["field"] not in names:
            continue
        word_at = names.index(spec["field"])
        sentence = c["fields"].get("sentence")
        sentence_at = names.index(sentence) if spec["note_type"] == c["note_type"] and sentence in names else None
        for nid, flds in mw.col.db.all("select id, flds from notes where mid = ?", model["id"]):
            fields = flds.split("\x1f")
            word = plain(fields[word_at])
            if not word:
                continue
            known.add(word)
            if sentence_at is not None and cards.sentence_count(fields[sentence_at]) < c["max_sentences"]:
                extendable[word] = nid
    return known, extendable


def note_type(c):
    """The configured note type; the simple built-in one is created on first use."""
    models = mw.col.models
    model = models.by_name(c["note_type"])
    if model or c["note_type"] != "Jellyfin Miner":
        if not model:
            raise ValueError(f'Note type "{c["note_type"]}" not found. Check note_type in the add-on config.')
        return model
    model = models.new("Jellyfin Miner")
    for name in NOTE_TYPE_FIELDS:
        models.add_field(model, models.new_field(name))
    template = models.new_template("Recognition")
    template["qfmt"] = '<div class="word">{{kanji:Word}}</div>'
    template["afmt"] = ('{{FrontSide}}<hr id="answer"><div>{{furigana:Word}}</div><div>{{Meaning}}</div>'
                        '<p>{{furigana:Sentence}}</p><p class="small">{{Translation}}</p>{{Audio}}<div>{{Picture}}</div>'
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


def save(results, model, c, extendable):
    col = mw.col
    deck_id = col.decks.id(c["deck"])
    added = extended = 0
    for _item, new, appends in results:
        for n in new:
            note = col.new_note(model)
            pieces = {**n["word_fields"], **cards.scene_fields(add_media(n["scene"]), c["audio_format"])}
            for field, value in cards.new_note_values(pieces, c["fields"]).items():
                if field in note:
                    note[field] = value
            note.tags = n["tags"]
            col.add_note(note, deck_id)
            added += 1
        for a in appends:
            if a["word"] in extendable:
                note = col.get_note(extendable[a["word"]])
                scene = cards.scene_fields(add_media(a["scene"]), c["audio_format"])
                if cards.append_scene(note, scene, c["fields"], c["max_sentences"]):
                    col.update_note(note)
                    extended += 1
    return added, extended


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
    state = mw.col.get_config(STATE, {"since": None, "done": []})
    now = datetime.datetime.now(datetime.timezone.utc)
    since = state["since"] or (now - datetime.timedelta(days=1)).isoformat()  # first run: only the last day
    workdir, log = tempfile.mkdtemp(prefix="jellyfin_miner_"), []
    running = True

    def work():
        jf = Jellyfin(c["jellyfin_url"], c["jellyfin_api_key"])
        items = episodes
        if not manual:
            items = [i for i in jf.recently_watched(jf.user_id(c["jellyfin_user"]), since) if i["Id"] not in state["done"]]
        caught_up = manual or len(items) <= c["max_episodes_per_run"]
        dict_, results = Dictionary(), []
        for item in (items if manual else items[:c["max_episodes_per_run"]]):
            new, appends = mining.mine_episode(jf, item, c, known, set(extendable), dict_, workdir, log.append)
            results.append((item, new, appends))
            known.update(n["word"] for n in new)  # never pick the same word twice in one run
        return results, caught_up

    def done(future):
        global running
        running = False
        try:
            results, caught_up = future.result()
            added, extended = save(results, model, c, extendable)
        except Exception as e:
            shutil.rmtree(workdir, ignore_errors=True)
            return showWarning(f"Jellyfin Miner: {e}") if manual else print("jellyfin_miner:", repr(e))
        shutil.rmtree(workdir, ignore_errors=True)
        if not manual and caught_up:  # with episodes left over, look from the same point again next time
            state["since"] = now.isoformat()
        state["done"] = (state["done"] + [item["Id"] for item, _, _ in results])[-2000:]
        mw.col.set_config(STATE, state)
        if results:
            shows = ", ".join(dict.fromkeys(label(item) for item, _, _ in results))
            summary = f"Jellyfin Miner: {added} new card(s), {extended} extra sentence(s) from {shows}"
            showInfo(summary + "\n\n" + "\n".join(log)) if manual else tooltip(summary, period=6000)
            if mw.state == "deckBrowser":
                mw.deckBrowser.refresh()
        elif announce:
            tooltip("Jellyfin Miner: no newly watched episodes")

    mw.taskman.run_in_background(work, done)


class EpisodePicker(QDialog):
    """Tools → Jellyfin Miner → Mine an episode…: pick a series and episodes."""

    def __init__(self, jf, user_id):
        super().__init__(mw)
        self.jf, self.user_id = jf, user_id
        self.setWindowTitle("Mine an episode")
        self.resize(480, 520)
        self.series = QComboBox()
        self.series_items = jf.series(user_id)
        self.series.addItems([s["Name"] for s in self.series_items])
        self.episodes = QListWidget()
        self.episodes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Mine selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        for widget in (QLabel("Series"), self.series, QLabel("Episodes (Ctrl/Shift to pick several)"), self.episodes, buttons):
            layout.addWidget(widget)
        self.series.currentIndexChanged.connect(self.load_episodes)
        self.load_episodes(0)

    def load_episodes(self, index):
        self.episodes.clear()
        for ep in self.jf.episodes(self.series_items[index]["Id"], self.user_id):
            streams = ep["MediaSources"][0].get("MediaStreams", []) if ep.get("MediaSources") else []
            has_subs = any(s["Type"] == "Subtitle" and (s.get("Language") or "").lower() in JAPANESE for s in streams)
            row = QListWidgetItem(f"S{ep.get('ParentIndexNumber', 0)}E{ep.get('IndexNumber', 0)}  {ep.get('Name', '')}"
                                  + ("" if has_subs else "   (no Japanese subtitles)"))
            row.setData(Qt.ItemDataRole.UserRole, ep)
            if not has_subs:
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.episodes.addItem(row)

    def selected(self):
        return [row.data(Qt.ItemDataRole.UserRole) for row in self.episodes.selectedItems()]


def pick_episodes():
    c = config()
    if not configured(c):
        return showWarning("Set the Jellyfin address, API key and user first: Tools → Add-ons → Jellyfin Miner → Config.")
    try:
        jf = Jellyfin(c["jellyfin_url"], c["jellyfin_api_key"])
        picker = EpisodePicker(jf, jf.user_id(c["jellyfin_user"]))
    except Exception as e:
        return showWarning(f"Couldn't reach Jellyfin: {e}")
    if picker.exec() and picker.selected():
        run(picker.selected())


def on_profile_open():
    global timer, menu
    if menu is None:  # profiles can be reopened; add the menu once
        menu = QMenu("Jellyfin Miner", mw)
        for text, action in (("Mine new episodes now", run_now), ("Mine an episode…", pick_episodes)):
            item = QAction(text, mw)
            item.triggered.connect(action)
            menu.addAction(item)
        mw.form.menuTools.addMenu(menu)
    c = config()
    if c["auto_mine"] and configured(c):
        QTimer.singleShot(15_000, run)
        timer = QTimer(mw)
        timer.timeout.connect(run)
        timer.start(max(5, c["check_every_minutes"]) * 60_000)


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
