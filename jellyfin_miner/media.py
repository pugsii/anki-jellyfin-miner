"""Cut a sentence's audio and a screenshot out of an episode with ffmpeg."""
import os
import shutil
import subprocess


def find_ffmpeg(configured=""):
    path = configured or shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found: install it, or set ffmpeg_path in the add-on's config")
    return path


def _run(ffmpeg, args, timeout=90):
    subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", *args], check=True, timeout=timeout,
                   capture_output=True)


def audio_clip(ffmpeg, url, start, end, out, pad=0.25):
    """MP3 of [start, end] seconds from the Japanese audio track (or the first track if none is tagged)."""
    start = max(0.0, start - pad)
    common = ["-ss", f"{start:.2f}", "-i", url, "-t", f"{end + pad - start:.2f}"]
    encode = ["-vn", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "96k", str(out)]
    try:
        _run(ffmpeg, [*common, "-map", "0:a:m:language:jpn", *encode])
    except subprocess.CalledProcessError:
        _run(ffmpeg, [*common, "-map", "0:a:0", *encode])


def screenshot(ffmpeg, url, start, end, out, width=640):
    """A frame from the middle of the line. A near-blank frame (a fade or flash: tiny as a JPEG) is retried at
    other points of the line, keeping the most detailed."""
    best, attempt = 0, f"{out}.try.jpg"
    for at in ((start + end) / 2, start + (end - start) * 0.2, start + (end - start) * 0.8):
        _run(ffmpeg, ["-ss", f"{at:.2f}", "-i", url, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", attempt])
        if os.path.getsize(attempt) > best:
            best = os.path.getsize(attempt)
            os.replace(attempt, out)
        if best > 10_000:  # detailed enough
            break
    if os.path.exists(attempt):
        os.remove(attempt)
