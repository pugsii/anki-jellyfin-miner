"""Check the grammar pattern files (jellyfin_miner/grammar/*.json).

    python3 tools/check_grammar.py [corpus.txt]

Every pattern must compile, match each of its "match" sentences and none of its "no_match" ones. With a corpus
(one Japanese sentence per line), patterns matching an unusually large share of it are flagged as too broad.
"""
import json
import re
import sys
from pathlib import Path

LEVELS = ["N5", "N4", "N3", "N2", "N1"]
BROAD = {"N5": 0.25, "N4": 0.12, "N3": 0.05, "N2": 0.03, "N1": 0.02}  # share of corpus sentences
KEYS = {"id", "pattern", "level", "meaning", "regex", "match", "no_match"}


def main():
    folder = Path(__file__).resolve().parent.parent / "jellyfin_miner" / "grammar"
    corpus = Path(sys.argv[1]).read_text().split("\n") if len(sys.argv) > 1 else []
    errors, warnings, ids, total = [], [], {}, 0
    for path in sorted(folder.glob("*.json")):
        try:
            entries = json.loads(path.read_text())
        except ValueError as e:
            errors.append(f"{path.name}: not valid JSON ({e})")
            continue
        for e in entries:
            total += 1
            where = f"{path.name} {e.get('id')}"
            if set(e) - KEYS - {"casual", "note"} or KEYS - set(e):
                errors.append(f"{where}: keys must be {sorted(KEYS)} (+ optional casual, note)")
                continue
            if e["id"] in ids:
                errors.append(f"{where}: id also used in {ids[e['id']]}")
            ids[e["id"]] = path.name
            if e["level"] not in LEVELS:
                errors.append(f"{where}: level must be one of {LEVELS}")
            if len(e["meaning"]) > 80:
                errors.append(f"{where}: meaning longer than 80 characters")
            if not e["match"] or not e["no_match"]:
                errors.append(f"{where}: needs at least one match and one no_match sentence")
            try:
                rx = re.compile(e["regex"])
            except re.error as err:
                errors.append(f"{where}: regex doesn't compile ({err})")
                continue
            errors += [f"{where}: doesn't match {s!r}" for s in e["match"] if not rx.search(s)]
            errors += [f"{where}: wrongly matches {s!r}" for s in e["no_match"] if rx.search(s)]
            if corpus:
                share = sum(1 for s in corpus if rx.search(s)) / len(corpus)
                if share > BROAD.get(e["level"], 1):
                    warnings.append(f"{where}: matches {share:.0%} of the corpus, probably too broad")
    print("\n".join(errors + warnings) or "all good")
    print(f"{total} patterns, {len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
