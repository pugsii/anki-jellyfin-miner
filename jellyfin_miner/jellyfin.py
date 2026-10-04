"""A small Jellyfin API client: watch history, episodes, subtitles and stream URLs (stdlib only)."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

JAPANESE = ("jpn", "ja")
ENGLISH = ("eng", "en")
TEXT_SUBS = {"ass": "ass", "ssa": "ass", "subrip": "srt", "srt": "srt", "webvtt": "srt", "vtt": "srt"}


class Jellyfin:
    def __init__(self, url, api_key, timeout=20):
        self.url, self.key, self.timeout = url.rstrip("/"), api_key, timeout

    def _get(self, path, raw=False, **params):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        request = urllib.request.Request(f"{self.url}{path}{'?' + query if query else ''}",
                                         headers={"Authorization": f'MediaBrowser Token="{self.key}"'})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read()
        if raw is None:  # bytes as they are (images)
            return body
        return body.decode("utf-8-sig") if raw else json.loads(body)

    def image(self, item_id, tag=None, height=450):
        """An item's poster (Primary image) as JPEG bytes, or None if it has none."""
        try:
            return self._get(f"/Items/{item_id}/Images/Primary", raw=None, tag=tag, fillHeight=height, quality=90)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def user_id(self, name):
        for user in self._get("/Users"):
            if user["Name"].lower() == name.lower():
                return user["Id"]
        raise ValueError(f'Jellyfin has no user called "{name}"')

    def recently_watched(self, user_id, since, limit=50):
        """Episodes the user played and finished after `since` (ISO time), newest first.

        "Mark as watched" also sets an episode's played flag, so a binge of marking would look like a binge of
        watching. Real playback is in the activity log, so use that; keys without access to it fall back to
        the played flag, skipping batches of 3+ episodes marked within the same minute."""
        fields = dict(userId=user_id, Fields="MediaStreams,MediaSources")
        try:
            log = self._get("/System/ActivityLog/Entries", minDate=since, limit=500)["Items"]
            ids = list(dict.fromkeys(e["ItemId"] for e in log if e.get("Type") == "VideoPlaybackStopped"
                                     and e.get("UserId") == user_id and e.get("ItemId")))
            items = self._get("/Items", Ids=",".join(ids), **fields)["Items"] if ids else []
            items.sort(key=lambda i: ids.index(i["Id"]))
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403):
                raise
            items = self._get("/Items", IncludeItemTypes="Episode", Recursive="true", SortBy="DatePlayed",
                              SortOrder="Descending", Limit=limit, **fields)["Items"]
            minute = lambda i: i["UserData"].get("LastPlayedDate", "")[:16]
            batches = Counter(minute(i) for i in items)
            items = [i for i in items if batches[minute(i)] < 3 and i["UserData"].get("LastPlayedDate", "") > since]
        return [i for i in items if i.get("Type") == "Episode" and i["UserData"].get("Played")]

    def series(self, user_id):
        return self._get("/Items", userId=user_id, IncludeItemTypes="Series", Recursive="true", SortBy="SortName",
                         Fields="OriginalTitle,SortName,ProviderIds")["Items"]

    def ignored_series(self, user_id, libraries):
        """Ids of the series in the libraries named (any case), e.g. a Jellyseerr/JellyBridge "Discover" library
        full of shows you haven't watched."""
        names = {n.lower() for n in libraries}
        views = [v["Id"] for v in self._get(f"/Users/{user_id}/Views")["Items"] if v["Name"].lower() in names]
        return {s["Id"] for v in views for s in self._get("/Items", userId=user_id, ParentId=v, IncludeItemTypes="Series",
                                                           Recursive="true", Fields="")["Items"]}

    def episodes(self, series_id, user_id):
        return self._get(f"/Shows/{series_id}/Episodes", userId=user_id, Fields="MediaStreams,MediaSources")["Items"]

    def subtitles(self, item, languages):
        """(text, format) of the item's best text subtitle track in one of `languages`, or None.
        Downloaded subtitles are sometimes mislabelled (a Chinese file saved as .ja.srt), so Japanese tracks
        must actually read as Japanese."""
        source = item["MediaSources"][0]
        tracks = [s for s in source.get("MediaStreams", []) if s["Type"] == "Subtitle"
                  and (s.get("Language") or "").lower() in languages and (s.get("Codec") or "").lower() in TEXT_SUBS]
        if not tracks:
            return None
        # prefer full dialogue over signs/songs tracks, then non-forced
        title = lambda s: (s.get("Title") or s.get("DisplayTitle") or "").lower()
        for track in sorted(tracks, key=lambda s: ("sign" in title(s) or "song" in title(s), bool(s.get("IsForced")))):
            fmt = TEXT_SUBS[track["Codec"].lower()]
            text = self._get(f"/Videos/{item['Id']}/{source['Id']}/Subtitles/{track['Index']}/0/Stream.{fmt}", raw=True)
            if languages != JAPANESE or looks_japanese(text):
                return text, fmt
        return None

    def stream_url(self, item):
        """The original file over HTTP, for ffmpeg to seek into (nothing is downloaded whole).
        Authenticate with stream_headers(), so the key never appears in a process list."""
        query = urllib.parse.urlencode({"static": "true", "mediaSourceId": item["MediaSources"][0]["Id"]})
        return f"{self.url}/Videos/{item['Id']}/stream?{query}"

    def stream_headers(self):
        return f"X-Emby-Token: {self.key}\r\n"


def looks_japanese(text):
    """Japanese is mostly kana; Chinese, which shares the kanji, has next to none."""
    kana, han = len(re.findall(r"[ぁ-ゖァ-ヺー]", text)), len(re.findall(r"[一-鿿]", text))
    return kana > 0.25 * (kana + han)


def japanese_audio(item):
    """Position of the first Japanese track among the file's audio tracks (ffmpeg's 0:a:N), else 0.
    By position rather than by language tag: a file can have two Japanese tracks (e.g. commentary)."""
    audio = [s for s in item["MediaSources"][0].get("MediaStreams", []) if s["Type"] == "Audio" and not s.get("IsExternal")]
    return next((n for n, s in enumerate(audio) if (s.get("Language") or "").lower() in JAPANESE), 0)


def label(item):
    """'無職転生 S1E3' style label for an episode."""
    return f"{item.get('SeriesName', '')} S{item.get('ParentIndexNumber', 0)}E{item.get('IndexNumber', 0)}"


if __name__ == "__main__":  # self-check
    assert looks_japanese("もしかしてなんだけど、あなた魔物に襲われたの？") and looks_japanese("魔物討伐だ！行くぞ")
    assert not looks_japanese("遭到了魔物的蹂躪\n我們必須馬上離開這裡") and not looks_japanese("Hello")
    print("selftest ok")
