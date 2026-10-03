"""Parse SRT and ASS subtitles into dialogue cues: (start seconds, end seconds, text)."""
import re

# ASS styles that aren't spoken dialogue: on-screen signs, song lyrics, karaoke, titles
NON_DIALOGUE = re.compile(r"sign|song|lyric|kara|\bop\b|\bed\b|opening|ending|title|insert|note|caption|logo", re.I)
KANA = r"[぀-ヿー]"


def clean(text):
    """Plain dialogue text: no markup, reading aids, speaker labels or music symbols."""
    text = re.sub(r"\{[^}]*\}", "", text)                         # ASS override tags
    text = re.sub(r"\\[Nn]", "", text).replace("\\h", " ")         # ASS line breaks
    text = re.sub(r"<[^>]+>", "", text)                            # SRT/HTML tags
    text = re.sub(rf"[（(]{KANA}+[）)]", "", text)                  # furigana in brackets: 漢字（かんじ）
    text = text.strip()
    if re.fullmatch(r"[（(][^（()）]+[）)]", text):                  # a whole line in brackets is inner monologue:
        text = text[1:-1]                                              # keep the words
    text = re.sub(r"[（(][^（()）]{1,8}[）)]", "", text)             # speaker labels/notes anywhere: （男） （２人）
    text = re.sub(r"[♪♫〜～➡→⇒]+", " ", text)
    text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    return re.sub(r"(?<=[\u3000-\u9fff！？。、…」』])\s+(?=[\u3000-\u9fff「『])", "", text)  # Japanese has no spaces


def _secs(h, m, s, frac):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / 10 ** len(frac)


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if m:
            cues.append((_secs(*m.group(1, 2, 3, 4)), _secs(*m.group(5, 6, 7, 8)), clean(block[m.end():])))
    return [c for c in cues if c[2]]


def parse_ass(text):
    cues, fields = [], None
    for line in text.replace("\r", "").split("\n"):
        if line.startswith("Format:") and fields is None and "Text" in line:
            fields = [f.strip().lower() for f in line[7:].split(",")]
        elif line.startswith("Dialogue:") and fields:
            values = dict(zip(fields, line[9:].split(",", len(fields) - 1)))
            raw = values.get("text", "")
            if NON_DIALOGUE.search(values.get("style", "")) or re.search(r"\\p[1-9]", raw):  # drawings
                continue
            start, end = (_secs(*re.match(r"\s*(\d+):(\d+):(\d+)\.(\d+)", values[k]).groups()) for k in ("start", "end"))
            if clean(raw):
                cues.append((start, end, clean(raw)))
    return sorted(cues)


def parse(text, fmt):
    return parse_ass(text) if fmt in ("ass", "ssa") else parse_srt(text)


if __name__ == "__main__":  # self-check
    srt = "1\n00:00:01,500 --> 00:00:03,000\n<i>（男）今日も 面接（めんせつ）だった</i>\n\n2\n00:01:00,000 --> 00:01:02,250\n♪～\n"
    assert parse_srt(srt) == [(1.5, 3.0, "今日も面接だった")], parse_srt(srt)
    assert clean("ヒトガミを疑い でも 敵対はしない➡") == "ヒトガミを疑いでも敵対はしない" and clean("OK 大丈夫") == "OK 大丈夫"
    assert clean("でも最悪死者が出るんだ。 （２人）んっ…。") == "でも最悪死者が出るんだ。んっ…。"
    assert clean("（どうして俺が…）") == "どうして俺が…"
    ass = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:05.10,0:00:07.00,Default,,0,0,0,,{\\an8}見逃して\\Nあげましょう\n"
           "Dialogue: 0,0:00:06.00,0:00:08.00,Signs,,0,0,0,,看板\n"
           "Dialogue: 0,0:01:00.00,0:01:05.00,OP Romaji,,0,0,0,,kimi no\n")
    assert parse_ass(ass) == [(5.1, 7.0, "見逃してあげましょう")], parse_ass(ass)
    assert not NON_DIALOGUE.search("Main Italicized") and not NON_DIALOGUE.search("Narrated")
    assert NON_DIALOGUE.search("ED-Romaji") and NON_DIALOGUE.search("OP Kanji") and NON_DIALOGUE.search("Signs")
    print("selftest ok")
