# ═══════════════════════════════════════════════════════════════════════════════
#  reviews.py — Cache of the engine analyses behind the Game Review screen
#
#  Only the raw analysis of each position is stored, never the move classes
#  drawn from it: retuning the classifier must not mean analysing every game
#  again. The file is a cache — deleting it only costs re-analysis — so it
#  lives apart from chess_arena.db and is never published with it.
# ═══════════════════════════════════════════════════════════════════════════════

import hashlib
import json
import sqlite3
from datetime import datetime

from core.utils import custom_start, get_reviews_db_path

FORMAT = 1          # bump when the stored analysis changes shape
KEEP = 500          # most recent games kept
PV_KEEP = 8         # moves of each line worth storing


class ReviewCache:
    """Analyses of whole games, keyed by their moves and the search used."""

    def __init__(self, db_path=None):
        self.db_path = db_path or get_reviews_db_path()
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS analyses (
                    moves_key TEXT    NOT NULL,
                    engine    TEXT    NOT NULL,
                    movetime  INTEGER NOT NULL,
                    format    INTEGER NOT NULL,
                    created   TEXT    NOT NULL,
                    data      TEXT    NOT NULL,
                    PRIMARY KEY (moves_key, engine, movetime)
                )
            ''')

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5)

    @staticmethod
    def key_for(moves, start_fen=None):
        """
        A game's key: its moves — and, for a game set up from a position,
        that position too, so the same moves from two different starts
        never share an analysis. Games from the standard start keep the
        keys they always had.
        """
        text = " ".join(moves)
        start_fen = custom_start(start_fen)
        if start_fen:
            text = f"{start_fen}|{text}"
        return hashlib.sha1(text.encode("ascii")).hexdigest()

    def get(self, moves, engine, movetime, start_fen=None):
        """
        The cached analyses of a game (one per position), from a search at
        least *movetime* ms long by the same engine — or None.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT data FROM analyses WHERE moves_key = ? AND engine = ? "
                    "AND movetime >= ? AND format = ? "
                    "ORDER BY movetime DESC LIMIT 1",
                    (self.key_for(moves, start_fen), engine, int(movetime), FORMAT)
                ).fetchone()
            return json.loads(row[0]) if row else None
        except Exception as e:
            print(f"[ReviewCache] get error: {e}")
            return None

    def put(self, moves, engine, movetime, analyses, start_fen=None):
        """Store a fully analysed game, dropping the oldest beyond KEEP."""
        slim = [self._slim(a) for a in analyses]
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO analyses "
                    "(moves_key, engine, movetime, format, created, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (self.key_for(moves, start_fen), engine, int(movetime), FORMAT,
                     datetime.now().isoformat(timespec="seconds"),
                     json.dumps(slim, separators=(",", ":"))))
                conn.execute(
                    "DELETE FROM analyses WHERE rowid NOT IN ("
                    "SELECT rowid FROM analyses ORDER BY created DESC LIMIT ?)",
                    (KEEP,))
        except Exception as e:
            print(f"[ReviewCache] put error: {e}")

    @staticmethod
    def _slim(analysis):
        if not analysis:
            return analysis
        lines = [dict(line, pv=list(line.get("pv") or [])[:PV_KEEP])
                 for line in analysis.get("lines") or []]
        return {"lines": lines, "bestmove": analysis.get("bestmove")}
