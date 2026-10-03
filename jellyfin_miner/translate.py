"""English for a Japanese line: the English subtitle at the same moment, else an optional AI model."""
import json
import re
import urllib.request

PROMPT = "Translate this Japanese subtitle line from an anime into natural English. Reply with the translation only."


def from_subtitles(cue, english_cues):
    """English cues lined up with the Japanese one (most of each overlaps the other), joined.
    Subtitle tracks are often timed differently; a loose match gives the wrong line, which is worse than none."""
    start, end, _ = cue
    overlap = lambda c: min(end, c[1]) - max(start, c[0])
    return " ".join(c[2] for c in english_cues if overlap(c) >= 0.6 * max(end - start, c[1] - c[0]))


def with_model(text, base_url, model, api_key="", extra_prompt="", timeout=60):
    """Any OpenAI-compatible chat endpoint (LocalAI, Ollama, LM Studio, OpenAI...)."""
    body = {"model": model, "temperature": 0.2, "max_tokens": 1500,  # room for reasoning models to think first
            "messages": [{"role": "system", "content": f"{PROMPT} {extra_prompt}".strip()},
                         {"role": "user", "content": text}]}
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})}
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        reply = json.load(response)["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", reply, flags=re.S).strip()  # reasoning models


if __name__ == "__main__":  # self-check
    eng = [(1.0, 2.9, "I had another interview today."), (3.0, 4.0, "Unrelated."), (2.0, 3.2, "Got rejected.")]
    assert from_subtitles((1.2, 3.0, "今日も面接"), eng) == "I had another interview today."  # (2.0, 3.2) is too far off
    assert from_subtitles((10, 11, "x"), eng) == ""
    print("selftest ok")
