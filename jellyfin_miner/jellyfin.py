"""A small Jellyfin API client: watch history, episodes, subtitles and stream URLs (stdlib only)."""
import json
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
        return body.decode("utf-8-sig") if raw else json.loads(body)

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
        return self._get("/Items", userId=user_id, IncludeItemTypes="Series", Recursive="true", SortBy="SortName")["Items"]

    def episodes(self, series_id, user_id):
        return self._get(f"/Shows/{series_id}/Episodes", userId=user_id, Fields="MediaStreams,MediaSources")["Items"]

    def subtitles(self, item, languages):
        """(text, format) of the item's best text subtitle track in one of `languages`, or None."""
        source = item["MediaSources"][0]
        tracks = [s for s in source.get("MediaStreams", []) if s["Type"] == "Subtitle"
                  and (s.get("Language") or "").lower() in languages and (s.get("Codec") or "").lower() in TEXT_SUBS]
        if not tracks:
            return None
        # prefer full dialogue over signs/songs tracks, then non-forced
        title = lambda s: (s.get("Title") or s.get("DisplayTitle") or "").lower()
        track = min(tracks, key=lambda s: ("sign" in title(s) or "song" in title(s), bool(s.get("IsForced"))))
        fmt = TEXT_SUBS[track["Codec"].lower()]
        text = self._get(f"/Videos/{item['Id']}/{source['Id']}/Subtitles/{track['Index']}/0/Stream.{fmt}", raw=True)
        return text, fmt

    def stream_url(self, item):
        """The original file over HTTP, for ffmpeg to seek into (nothing is downloaded whole)."""
        source = item["MediaSources"][0]
        query = urllib.parse.urlencode({"static": "true", "mediaSourceId": source["Id"], "api_key": self.key})
        return f"{self.url}/Videos/{item['Id']}/stream?{query}"


def label(item):
    """'無職転生 S1E3' style label for an episode."""
    return f"{item.get('SeriesName', '')} S{item.get('ParentIndexNumber', 0)}E{item.get('IndexNumber', 0)}"
