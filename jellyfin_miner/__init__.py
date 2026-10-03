"""Jellyfin Miner: Anki cards from the anime you watch on Jellyfin. Settings are explained in config.md.

The pipeline modules don't need Anki, so the package also imports outside it (for tests and scripts);
the Anki side in addon.py only loads inside Anki.
"""
try:
    import aqt  # noqa: F401
except ImportError:
    pass
else:
    from . import addon  # noqa: F401
