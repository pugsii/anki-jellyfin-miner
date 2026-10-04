"""Build dist/jellyfin_miner.ankiaddon: the add-on folder as Anki installs it (Tools → Add-ons → Install from file).

    python3 tools/package.py

Needs the analyser and dictionary data built first (see "Building from source" in README.md). Leaves out your
settings (meta.json), caches and compiled files.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "jellyfin_miner"
OUT = ROOT / "dist" / "jellyfin_miner.ankiaddon"
NEEDED = [ADDON / "vendor" / "janome", ADDON / "data" / "dictionary.sqlite"]


def included(path):
    rel = path.relative_to(ADDON)
    if path.is_dir() or "__pycache__" in rel.parts or path.suffix == ".pyc" or rel.name == "meta.json":
        return False
    return rel.parts[0] != "user_files" or rel.name == "README.txt"  # the folder ships empty but for its notes


def main():
    missing = [str(p.relative_to(ROOT)) for p in NEEDED if not p.exists()]
    if missing:
        sys.exit(f"Build these first (see README.md, Building from source): {', '.join(missing)}")
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(ADDON.rglob("*")):
            if included(path):
                z.write(path, path.relative_to(ADDON).as_posix())  # Anki wants the add-on's files at the top
        z.write(ROOT / "LICENSE", "LICENSE.txt")
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
