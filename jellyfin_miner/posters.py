"""A grid of show posters, like Jellyfin's library view, shared by the episode picker and the watch scores.

Posters are cached in user_files/covers (named by Jellyfin's image tag, so a changed poster is fetched again) and
loaded in the background; the grid shows placeholders until they arrive. A badge (e.g. "79%") can be drawn on any
poster at any time.
"""
from pathlib import Path

from aqt import mw

from . import titles
from aqt.qt import (QAbstractItemView, QColor, QFont, QIcon, QLineEdit, QListView, QListWidget, QListWidgetItem,
                    QPainter, QPainterPath, QPixmap, QRectF, QSize, Qt)

COVERS = Path(__file__).parent / "user_files" / "covers"
W, H = 150, 225          # poster size on screen (2:3, like Jellyfin)
SORT = Qt.ItemDataRole.UserRole + 1


def cover_bytes(jf, show):
    """The show's poster, from the cache or Jellyfin; None if it has none."""
    tag = (show.get("ImageTags") or {}).get("Primary")
    if not tag:
        return None
    path = COVERS / f"{show['Id']}-{tag}.jpg"
    if path.exists():
        return path.read_bytes()
    data = jf.image(show["Id"], tag, height=H * 2)
    if data:
        COVERS.mkdir(parents=True, exist_ok=True)
        for old in COVERS.glob(f"{show['Id']}-*.jpg"):  # an older version of this poster
            old.unlink()
        path.write_bytes(data)
    return data


class Item(QListWidgetItem):
    """Sorts by its SORT value (lowest first; none yet sorts last), then by name; or by name only."""
    by_name = False

    def __lt__(self, other):
        def key(item):
            rank = item.data(SORT)
            return 0 if Item.by_name else 9e9 if rank is None else rank, item.text().lower()
        return key(self) < key(other)


class ShowGrid(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(W, H))
        self.setGridSize(QSize(W + 22, H + 52))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet("QListView::item { padding: 5px 4px 2px; border-radius: 10px; }"
                           "QListView::item:selected { background: palette(highlight); color: palette(highlighted-text); }")
        self.items, self.posters, self.badges, self.names, self.query = {}, {}, {}, {}, ""

    def updateGeometries(self):
        """Qt sets the scroll step from the cell height, so a wheel notch jumped about three rows of posters; a fixed
        step gives a third of a row per notch."""
        super().updateGeometries()
        self.verticalScrollBar().setSingleStep(30)

    def resizeEvent(self, event):
        """Spread the columns over the full width with equal space on both sides. Qt needs 10-16px free on the
        right before wrapping, so cells fill all but 32px and the left margin takes half of what's left."""
        super().resizeEvent(event)
        width = self.viewport().width() + self.viewportMargins().left()
        cols = max(1, (width - 32) // (W + 22))
        cell = (width - 32) // cols
        margin = (width - cols * cell) // 2
        if margin != self.viewportMargins().left():
            self.setViewportMargins(margin, 0, 0, 0)
        if cell != self.gridSize().width():
            self.setGridSize(QSize(cell, H + 52))

    def add(self, show):
        item = Item(show["Name"])
        item.setData(Qt.ItemDataRole.UserRole, show)
        item.setToolTip(show["Name"])
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.addItem(item)
        self.items[show["Id"]] = item
        self.redraw(show["Id"])

    def show_at(self, item):
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def set_poster(self, show_id, data):
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.posters[show_id] = pixmap
            self.redraw(show_id)

    def set_badge(self, show_id, text, color, sort_key=None):
        self.badges[show_id] = (text, color)
        self.items[show_id].setData(SORT, sort_key)
        self.redraw(show_id)

    def set_names(self, names):
        """{show id: every name it goes by}, for searching; applies the current search again."""
        self.names.update(names)
        self.filter(self.query)

    def filter(self, text):
        self.query = text
        for show_id, item in self.items.items():
            item.setHidden(not titles.matches(text, self.names.get(show_id) or [item.text()]))

    def redraw(self, show_id):
        """Poster (cropped to 2:3, rounded corners) or a placeholder, then the badge, at screen resolution."""
        ratio = self.devicePixelRatioF()
        canvas = QPixmap(int(W * ratio), int(H * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(0, 0, W, H), 8, 8)
        p.setClipPath(shape)
        poster = self.posters.get(show_id)
        if poster:
            scaled = poster.scaled(int(W * ratio), int(H * ratio), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            x = (scaled.width() / ratio - W) / 2
            y = (scaled.height() / ratio - H) / 2
            p.drawPixmap(QRectF(0, 0, W, H), scaled, QRectF(x * ratio, y * ratio, W * ratio, H * ratio))
        else:
            p.fillRect(QRectF(0, 0, W, H), self.palette().mid())
            p.setPen(self.palette().text().color())
            p.setFont(QFont(self.font().family(), 36))
            p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, self.items[show_id].text()[:1])
        badge = self.badges.get(show_id)
        if badge:
            text, color = badge
            font = QFont(self.font().family(), 15, QFont.Weight.Bold)
            p.setFont(font)
            width = p.fontMetrics().horizontalAdvance(text) + 18
            pill = QRectF(8, H - 38, width, 30)
            p.setClipping(False)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(pill, 15, 15)
            p.setPen(QColor("white"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        icon = QIcon(canvas)
        icon.addPixmap(canvas, QIcon.Mode.Selected)  # no highlight tint over the poster; the frame shows selection
        self.items[show_id].setIcon(icon)


def search_box(grid):
    box = QLineEdit()
    box.setPlaceholderText("Search shows: Japanese, romaji or English title…")
    box.setClearButtonEnabled(True)
    box.textChanged.connect(grid.filter)
    return box


def load_posters(jf, shows, grid, stopped):
    """Fetch every show's names (for searching) and posters in the background, putting each on the grid as it
    arrives. `stopped()` ends it early (the dialog was closed)."""
    def work():
        names = titles.all_names(shows)
        mw.taskman.run_on_main(lambda: stopped() or grid.set_names(names))
        for show in shows:
            if stopped():
                return
            try:
                data = cover_bytes(jf, show)
            except Exception:  # a missing poster just keeps its placeholder
                continue
            if data:
                mw.taskman.run_on_main(lambda i=show["Id"], d=data: stopped() or grid.set_poster(i, d))
    mw.taskman.run_in_background(work, lambda future: future.exception())
