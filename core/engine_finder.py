# ═══════════════════════════════════════════════════════════
#  core/engine_finder.py — Finding engine files by name
#
#  A tournament player is named after its engine file, so an engine whose
#  path was never kept — an event that finished before tournaments kept
#  their state — can be found again by looking for a file of that name.
# ═══════════════════════════════════════════════════════════

import os

from core.utils import normalize_engine_name

ENGINE_EXTENSIONS = (".exe", ".bin")

# A scan of something as big as a whole drive gives up rather than hangs
MAX_FILES_SCANNED = 300_000


def engine_name(path):
    """The name an engine file is entered under."""
    return normalize_engine_name(os.path.splitext(os.path.basename(path))[0])


class EngineFinder:
    """Engine files indexed by name, from known paths and scanned folders."""

    def __init__(self):
        self._by_name = {}

    def _index(self, path):
        # The first file seen for a name wins, so known paths added first
        # are not displaced by a same-named file found in a scan
        self._by_name.setdefault(engine_name(path).lower(), path)

    def add(self, path):
        """Index one engine file, if it exists."""
        if path and os.path.isfile(path):
            self._index(path)

    def add_all(self, paths):
        for path in paths:
            self.add(path)

    def scan(self, folder):
        """Index every executable under *folder*. Returns how many."""
        found = seen = 0
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(ENGINE_EXTENSIONS):
                    self._index(os.path.join(root, name))
                    found += 1
            seen += len(files)
            if seen >= MAX_FILES_SCANNED:
                break
        return found

    def find(self, name):
        """The engine file for *name*, or None."""
        return self._by_name.get((name or "").strip().lower())
