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
    return ask(PROMPT, text, base_url, model, api_key, extra_prompt, timeout)


EXAMPLE_PROMPT = ("Write one short, natural Japanese example sentence that a JLPT N4 learner could read, using the given "
                  "word. Reply with exactly two lines: the Japanese sentence, then its English translation. No romaji, "
                  "no notes.")


def example_with_model(word, base_url, model, api_key="", extra_prompt="", timeout=60):
    """(Japanese, English) example sentence for a word, written by the model, or None if the reply doesn't fit."""
    lines = [l.strip() for l in ask(EXAMPLE_PROMPT, word, base_url, model, api_key, extra_prompt, timeout).split("\n") if l.strip()]
    ja = next((l for l in lines if re.search(r"[ぁ-んァ-ン一-鿿]", l)), None)
    en = next((l for l in lines if l != ja and not re.search(r"[ぁ-んァ-ン一-鿿]", l)), "")
    return (ja, en) if ja and word in ja else None


def ask(system, text, base_url, model, api_key="", extra_prompt="", timeout=60):
    body = {"model": model, "temperature": 0.2, "max_tokens": 1500,  # room for reasoning models to think first
            "messages": [{"role": "system", "content": f"{system} {extra_prompt}".strip()},
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
