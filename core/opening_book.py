# ═══════════════════════════════════════════════════════════
#  opening_book.py — ECO/opening CSV loader and position lookup
#
#  Opening names belong to positions, not to move orders. A game that
#  goes 1.e4 Nc6 2.Nf3 e5 3.Bb5 is a Ruy Lopez, even though no book line
#  starts 1.e4 Nc6 and ends in one. So every line in the CSV is replayed
#  once and its positions indexed: the line's final position carries its
#  name, and every position along it counts as theory ("Book").
# ═══════════════════════════════════════════════════════════

import csv
import json
import os

from core.board import Board
from core.pgn import tokens_to_uci


def opening_label(eco, name):
    """'C60 · Ruy Lopez', just the name, or '' before any is known."""
    if eco and name:
        return f"{eco} · {name}"
    return name or ""


class OpeningBook:
    """
    Load an openings CSV (columns: ECO, name, moves) and name positions.

    The ``moves`` column may hold SAN (``e4 e5 Nf3``) or UCI (``e2e4``),
    with or without move numbers.
    """

    # Bump when the cached index changes shape; older caches are rebuilt
    CACHE_VERSION = 2

    def __init__(self, csv_path=None):
        self._lines = []          # (uci_seq_tuple, eco, name), in file order
        self._named = {}          # epd → (eco, name) of the line ending there
        self._book = set()        # epd of every position along every line
        self.scan_limit = 0       # plies after which no named position exists
        if csv_path and os.path.isfile(csv_path):
            self._load(csv_path)

    # ── Public API ────────────────────────────────────────

    @property
    def loaded(self):
        """True if at least one opening was loaded from the CSV."""
        return bool(self._lines)

    def __len__(self):
        return len(self._lines)

    @property
    def lines(self):
        """Every book line as (uci_moves_tuple, eco, name), in file order."""
        return list(self._lines)

    def named(self, epd):
        """(eco, name) of the opening named at this position, or None."""
        return self._named.get(epd)

    def is_book_position(self, epd):
        """True if the position occurs in some book line."""
        return epd in self._book

    def tracker(self, start=None):
        """
        A fresh OpeningTracker following one game against this book — from
        *start*, the Board of a game set up from some other position than
        the standard one.
        """
        return OpeningTracker(self, start)

    def scan(self, uci_moves, start_fen=None):
        """
        Follow a game from its start position — the standard one, or
        *start_fen* for a game set up from a position.

        Returns one (in_book, eco, name) per ply: whether the position
        reached is theory, and the opening name as it stands after it.
        """
        board = Board.from_fen(start_fen) if start_fen else Board()
        tracker = self.tracker(board if start_fen else None)
        out = []
        for uci in uci_moves:
            board = board.play_raw(uci)
            tracker.update(board)
            out.append((tracker.in_book, tracker.eco, tracker.name))
        return out

    def lookup(self, uci_moves, start_fen=None):
        """
        Name the opening of a game: the last named position it reached
        (transpositions included). Returns (eco, name) or (None, None).
        """
        moves = list(uci_moves)[:self.scan_limit]
        if not moves:
            # A game set up from a position is named by that position
            hit = (self.named(Board.from_fen(start_fen).epd())
                   if start_fen else None)
            return hit or (None, None)
        _, eco, name = self.scan(moves, start_fen)[-1]
        return eco, name

    def in_book(self, uci_moves, start_fen=None):
        """True while the position after *uci_moves* is opening theory."""
        moves = list(uci_moves)
        if not moves:
            return (not start_fen
                    or self.is_book_position(Board.from_fen(start_fen).epd()))
        if len(moves) > self.scan_limit:
            return False
        return self.scan(moves, start_fen)[-1][0]

    # ── Loading ───────────────────────────────────────────

    def _load(self, path):
        # Replaying thousands of lines is slow in pure Python, so the parsed
        # book and its position index are cached on disk, keyed by the
        # CSV's mtime/size. First load: seconds; every load after: instant.
        if self._load_cache(path):
            return
        try:
            with open(path, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    eco  = (row.get('ECO') or '').strip()
                    name = (row.get('name') or '').strip()
                    raw  = (row.get('moves') or '').strip()
                    if not raw:
                        continue
                    uci_seq = tokens_to_uci(raw.split(), strict=True)
                    if uci_seq:
                        self._lines.append((tuple(uci_seq), eco, name))
            self._build_index()
            self._save_cache(path)
        except Exception as e:
            print(f"[OpeningBook] Failed to load {path}: {e}")

    def _build_index(self):
        """Index every line's positions. Where two lines end on the same
        position, the shorter line names it (then the earlier one)."""
        named = {}
        book = set()
        longest = 0
        for order, (seq, eco, name) in enumerate(self._lines):
            board = Board()
            epd = None
            for uci in seq:
                board = board.play_raw(uci)
                epd = board.epd()
                book.add(epd)
            longest = max(longest, len(seq))
            rank = (len(seq), order)
            if epd and (epd not in named or rank < named[epd][0]):
                named[epd] = (rank, eco, name)
        self._named = {epd: (eco, name) for epd, (_, eco, name) in named.items()}
        self._book = book
        self.scan_limit = longest

    @staticmethod
    def _cache_path(csv_path):
        return csv_path + ".cache.json"

    def _load_cache(self, path):
        """Load the pre-parsed book if the cache matches the CSV. → bool"""
        try:
            st = os.stat(path)
            cache = self._cache_path(path)
            if not os.path.isfile(cache):
                return False
            with open(cache, encoding='utf-8') as f:
                data = json.load(f)
            if (data.get('version') != self.CACHE_VERSION
                    or data.get('mtime') != st.st_mtime
                    or data.get('size') != st.st_size):
                return False
            self._lines = [(tuple(seq), eco, name)
                           for seq, eco, name in data['lines']]
            self._named = {epd: tuple(v) for epd, v in data['named'].items()}
            self._book = set(data['book'])
            self.scan_limit = data['scan_limit']
            return bool(self._lines)
        except Exception:
            return False

    def _save_cache(self, path):
        try:
            st = os.stat(path)
            with open(self._cache_path(path), 'w', encoding='utf-8') as f:
                json.dump({
                    'version': self.CACHE_VERSION,
                    'mtime': st.st_mtime,
                    'size': st.st_size,
                    'lines': [[list(seq), eco, name]
                              for seq, eco, name in self._lines],
                    'named': {epd: list(v) for epd, v in self._named.items()},
                    'book': sorted(self._book),
                    'scan_limit': self.scan_limit,
                }, f)
        except Exception as e:
            print(f"[OpeningBook] Could not write cache: {e}")


class OpeningTracker:
    """
    Names one game's opening while it is being played.

    Feed it the board after every move. Because names are looked up by
    position, a transposition is picked up the moment it happens — 1.e4
    Nc6 starts as the Nimzowitsch Defense and becomes a Ruy Lopez once
    2.Nf3 e5 3.Bb5 reaches that position. Between named positions the
    last name stands, so the game keeps the name of the last opening it
    passed through.
    """

    def __init__(self, book, start=None):
        self.book = book
        self.reset(start)

    def reset(self, start=None):
        """
        Back to the start of a game: the standard position, which is
        theory, or *start* — the Board of a game set up from a position,
        named and judged like any position reached in play.
        """
        self.eco = None
        self.name = None
        self.in_book = True       # the standard start position is theory
        self.plies = 0
        if start is not None and self.book is not None:
            epd = start.epd()
            self.in_book = self.book.is_book_position(epd)
            hit = self.book.named(epd)
            if hit:
                self.eco, self.name = hit

    def update(self, board):
        """Note the position after a move. Returns True if the name changed."""
        self.plies += 1
        if self.book is None or self.plies > self.book.scan_limit:
            self.in_book = False
            return False
        epd = board.epd()
        self.in_book = self.book.is_book_position(epd)
        hit = self.book.named(epd)
        if hit and hit != (self.eco, self.name):
            self.eco, self.name = hit
            return True
        return False

    @property
    def label(self):
        """'C60 · Ruy Lopez', just the name, or '' before any is known."""
        return opening_label(self.eco, self.name)
