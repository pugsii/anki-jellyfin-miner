"""Cut a sentence's audio and a screenshot (or a short animated clip) out of an episode with ffmpeg."""
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
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console on Windows


def audio_clip(ffmpeg, url, headers, start, end, track, out, pad=0.25):
    """MP3 of [start, end] seconds from audio track number `track` (see jellyfin.japanese_audio)."""
    start = max(0.0, start - pad)
    _run(ffmpeg, ["-headers", headers, "-ss", f"{start:.2f}", "-i", url, "-t", f"{end + pad - start:.2f}",
                  "-map", f"0:a:{track}", "-vn", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "96k", str(out)])


def screenshot(ffmpeg, url, headers, start, end, out, width=640):
    """A frame from the middle of the line. A near-blank frame (a fade or flash: tiny as a JPEG) is retried at
    other points of the line, keeping the most detailed."""
    best, attempt = 0, f"{out}.try.jpg"
    for at in ((start + end) / 2, start + (end - start) * 0.2, start + (end - start) * 0.8):
        _run(ffmpeg, ["-headers", headers, "-ss", f"{at:.2f}", "-i", url, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", attempt])
        if os.path.getsize(attempt) > best:
            best = os.path.getsize(attempt)
            os.replace(attempt, out)
        if best > 10_000:  # detailed enough
            break
    if os.path.exists(attempt):
        os.remove(attempt)


def animated_clip(ffmpeg, url, headers, start, end, out, width=480, fps=12, longest=6.0):
    """A silent, looping animated WebP of the line (its first `longest` seconds). Anki, AnkiDroid and AnkiMobile
    play these in an ordinary <img>."""
    _run(ffmpeg, ["-headers", headers, "-ss", f"{start:.2f}", "-i", url, "-t", f"{min(end - start, longest):.2f}", "-an",
                  "-vf", f"fps={fps},scale={width}:-2:flags=lanczos", "-c:v", "libwebp_anim", "-quality", "60",
                  "-compression_level", "5", "-loop", "0", str(out)], timeout=180)


if __name__ == "__main__":  # self-check on a generated test video, served over HTTP as Jellyfin serves episodes
    import functools, http.server, tempfile, threading
    from PIL import Image
    ffmpeg = find_ffmpeg()
    with tempfile.TemporaryDirectory() as d:
        _run(ffmpeg, ["-f", "lavfi", "-i", "testsrc=duration=10:size=640x360:rate=24", "-pix_fmt", "yuv420p", f"{d}/test.mp4"])
        quiet = type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(quiet, directory=d))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url, headers = f"http://127.0.0.1:{server.server_port}/test.mp4", "X-Test: 1\r\n"
        screenshot(ffmpeg, url, headers, 2, 4, f"{d}/still.jpg")
        animated_clip(ffmpeg, url, headers, 2, 9.5, f"{d}/clip.webp")
        server.shutdown()
        clip = Image.open(f"{d}/clip.webp")
        assert Image.open(f"{d}/still.jpg").size == (640, 360)
        # 6 seconds at most (the line is 7.5), at 12 frames a second; it loops
        assert clip.size == (480, 270) and 60 <= clip.n_frames <= 73 and clip.info.get("loop") == 0, (clip.size, clip.n_frames)
    print("selftest ok")
