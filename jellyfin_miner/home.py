"""The Jellyfin Miner section on Anki's home screen (below the decks): a progress bar while mining, and a row of
recently watched shows. No Anki imports, so it's tested outside Anki; addon.py feeds it data and puts it on the page.

Fits in with the Kotoba Theme when it's installed (its --kt-* colours, placed above its footer) and with plain
Anki otherwise.
"""
import datetime
import html
import json
import re

CSS = """
.jfm-home { max-width: 720px; margin: 0 auto; padding: 0 24px 24px; text-align: left; box-sizing: border-box;
  color: var(--kt-fg, var(--fg)); font-family: inherit; }
.kt-home .jfm-home { padding: 0; margin-top: 22px; }
.jfm-home h2 { font-size: 13px; font-weight: 600; letter-spacing: 0.04em; color: var(--kt-muted, var(--fg-subtle));
  margin: 0 0 8px; text-transform: uppercase; }
.jfm-progress { background: var(--kt-panel, var(--canvas-elevated)); border-radius: 14px; padding: 12px 16px; margin-bottom: 18px; }
.jfm-progress[hidden] { display: none; }
.jfm-progress .jfm-label { font-size: 13px; margin-bottom: 8px; display: flex; justify-content: space-between; gap: 12px; }
.jfm-progress .jfm-label span:last-child { color: var(--kt-muted, var(--fg-subtle)); font-variant-numeric: tabular-nums; }
.jfm-bar { height: 6px; border-radius: 3px; background: color-mix(in srgb, var(--kt-fg, var(--fg)) 10%, transparent); overflow: hidden; }
.jfm-bar i { display: block; height: 100%; border-radius: 3px; background: var(--kt-accent, var(--button-primary-bg, #4a8fe7));
  transition: width 0.4s ease; }
.jfm-row { display: flex; gap: 14px; overflow-x: auto; padding-bottom: 6px; scrollbar-width: thin; }
.jfm-show { flex: none; width: 112px; cursor: pointer; text-decoration: none; color: inherit; }
.jfm-poster { width: 112px; height: 168px; border-radius: 10px; object-fit: cover; display: block;
  background: var(--kt-panel, var(--canvas-elevated)); transition: transform 0.15s; }
.jfm-show:hover .jfm-poster { transform: translateY(-2px); }
.jfm-name { font-size: 13px; font-weight: 600; margin-top: 6px; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.jfm-meta { font-size: 12px; color: var(--kt-muted, var(--fg-subtle)); line-height: 1.4; }
"""

# Moves the section above the Kotoba Theme's footer (if it's there), and updates the progress bar in place.
SCRIPT = """
(function () {
  var home = document.getElementById("jfm-home"), foot = document.querySelector(".kt-home .kt-foot");
  if (home && foot) foot.parentNode.insertBefore(home, foot);
})();
function jfmProgress(p) {
  var box = document.getElementById("jfm-progress");
  if (!box) return;
  box.hidden = !p;
  if (!p) return;
  box.querySelector(".jfm-what").textContent = p.label;
  box.querySelector(".jfm-pct").textContent = Math.round(p.fraction * 100) + "%";
  box.querySelector(".jfm-bar i").style.width = (p.fraction * 100).toFixed(1) + "%";
}
"""


def recent_shows(episodes, ignored=(), limit=10):
    """The shows of recently watched episodes (newest first, as recently_watched gives them), one per show:
    [{"id", "name", "tag", "episode": "S1E3", "title", "watched": ISO time}]."""
    out = {}
    for ep in episodes:
        sid = ep.get("SeriesId")
        if not sid or sid in out or sid in ignored:
            continue
        out[sid] = {"id": sid, "name": ep.get("SeriesName") or "", "tag": ep.get("SeriesPrimaryImageTag"),
                    "episode": f"S{ep.get('ParentIndexNumber', 0)}E{ep.get('IndexNumber', 0)}", "title": ep.get("Name") or "",
                    "watched": (ep.get("UserData") or {}).get("LastPlayedDate") or ""}
    return list(out.values())[:limit]


def ago(iso, now=None):
    """'today', 'yesterday', '3 days ago', '2 weeks ago' for an ISO time (Jellyfin's, in UTC)."""
    try:  # Jellyfin writes 7 fraction digits; Python reads up to 6
        when = datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    days = (now.astimezone().date() - when.astimezone().date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago" if days < 14 else f"{days // 7} weeks ago"


def section(shows, progress, cover_url, cards, now=None):
    """The section's HTML. cover_url(show) -> URL or None; cards(show) -> how many cards it has given you;
    progress: None, or {"label", "fraction"} while mining."""
    tiles = []
    for s in shows:
        url = cover_url(s)
        poster = f'<img class="jfm-poster" src="{html.escape(url)}" alt="">' if url else '<div class="jfm-poster"></div>'
        n = cards(s)
        meta = [f'{html.escape(s["episode"])} · {ago(s["watched"], now)}'.rstrip(" ·"),
                f'{n} card{"s" if n != 1 else ""}' if n else "no cards yet"]
        tiles.append(f'<a class="jfm-show" title="{html.escape(s["name"])}: {html.escape(s["title"])}" '
                     f'onclick="pycmd(\'jfm:show:{html.escape(s["id"])}\');return false;" href="#">{poster}'
                     f'<div class="jfm-name">{html.escape(s["name"])}</div>'
                     + "".join(f'<div class="jfm-meta">{m}</div>' for m in meta) + "</a>")
    bar = (f'<div id="jfm-progress" class="jfm-progress"{"" if progress else " hidden"}>'
           f'<div class="jfm-label"><span class="jfm-what">{html.escape(progress["label"]) if progress else ""}</span>'
           f'<span class="jfm-pct">{round(progress["fraction"] * 100) if progress else 0}%</span></div>'
           f'<div class="jfm-bar"><i style="width:{progress["fraction"] * 100 if progress else 0:.1f}%"></i></div></div>')
    row = f'<h2>Recently watched</h2><div class="jfm-row">{"".join(tiles)}</div>' if tiles else ""
    return f'<style>{CSS}</style><div id="jfm-home" class="jfm-home">{bar}{row}</div><script>{SCRIPT}</script>'


def progress_js(progress):
    return f"typeof jfmProgress === 'function' && jfmProgress({json.dumps(progress)})"


if __name__ == "__main__":  # self-check
    eps = [{"SeriesId": "a", "SeriesName": "葬送のフリーレン", "SeriesPrimaryImageTag": "t1", "ParentIndexNumber": 1, "IndexNumber": 3,
            "Name": "人を殺す魔法", "UserData": {"LastPlayedDate": "2026-10-03T12:00:00.0000000Z"}},
           {"SeriesId": "a", "SeriesName": "葬送のフリーレン", "IndexNumber": 2, "UserData": {}},
           {"SeriesId": "b", "SeriesName": "Arcane", "IndexNumber": 1, "UserData": {"LastPlayedDate": "2026-09-01T00:00:00Z"}},
           {"SeriesId": "x", "SeriesName": "Ignored", "UserData": {}}]
    shows = recent_shows(eps, ignored={"x"})
    assert [s["id"] for s in shows] == ["a", "b"] and shows[0]["episode"] == "S1E3" and shows[0]["tag"] == "t1"
    now = datetime.datetime(2026, 10, 4, 12, tzinfo=datetime.timezone.utc)
    assert ago(shows[0]["watched"], now) == "yesterday" and ago(shows[1]["watched"], now) == "4 weeks ago" and ago("", now) == ""
    page = section(shows, {"label": "Mining <S1E3>", "fraction": 0.25}, lambda s: "/c.jpg" if s["tag"] else None,
                   lambda s: 5 if s["id"] == "a" else 0, now)
    assert "jfm:show:a" in page and "5 cards" in page and "no cards yet" in page and "Mining &lt;S1E3&gt;" in page
    assert 'width:25.0%' in page and 'src="/c.jpg"' in page and page.count("jfm-poster") >= 3
    assert 'id="jfm-progress" class="jfm-progress" hidden' in section([], None, lambda s: None, lambda s: 0)
    assert "Recently watched" not in section([], None, lambda s: None, lambda s: 0)
    print("selftest ok")
