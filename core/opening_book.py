# ═══════════════════════════════════════════════════════════
#  opening_book.py — ECO/opening CSV loader and lookup
# ═══════════════════════════════════════════════════════════

import csv
import json
import os
from core.board import Board


class OpeningBook:
    """
    Load an openings CSV (columns: ECO, name, moves) and match played
    sequences against known openings.

    The ``moves`` column may contain either UCI moves (e.g. ``e2e4``) or
    SAN moves (e.g. ``e4``); both are handled automatically.
    """

    def __init__(self, csv_path=None):
        self._entries = []   # list of (uci_seq_tuple, eco_str, name_str)
        if csv_path and os.path.isfile(csv_path):
            self._load(csv_path)

    # ── Loading ───────────────────────────────────────────

    def _load(self, path):
        # SAN→UCI conversion of thousands of lines is expensive, so the
        # parsed book is cached on disk keyed by the CSV's mtime/size.
        # First load: seconds; every load after that: near-instant.
        if self._load_cache(path):
            return
        try:
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    eco  = (row.get('ECO') or '').strip()
                    name = (row.get('name') or '').strip()
                    raw  = (row.get('moves') or '').strip()
                    if not raw:
                        continue
                    tokens = raw.split()
                    uci_seq = self._tokens_to_uci(tokens)
                    if uci_seq is not None:
                        self._entries.append((tuple(uci_seq), eco, name))
            # Longest sequences first so lookup returns the most specific opening
            self._entries.sort(key=lambda x: len(x[0]), reverse=True)
            self._save_cache(path)
        except Exception as e:
            print(f"[OpeningBook] Failed to load {path}: {e}")

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
            if (data.get('mtime') != st.st_mtime
                    or data.get('size') != st.st_size):
                return False
            self._entries = [(tuple(seq), eco, name)
                             for seq, eco, name in data['entries']]
            return len(self._entries) > 0
        except Exception:
            return False

    def _save_cache(self, path):
        try:
            st = os.stat(path)
            with open(self._cache_path(path), 'w', encoding='utf-8') as f:
                json.dump({
                    'mtime': st.st_mtime,
                    'size': st.st_size,
                    'entries': [[list(seq), eco, name]
                                for seq, eco, name in self._entries],
                }, f)
        except Exception as e:
            print(f"[OpeningBook] Could not write cache: {e}")

    def _tokens_to_uci(self, tokens):
        """Convert a token list (SAN or UCI) to a list of UCI move strings."""
        board = Board()
        uci_list = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            if self._looks_like_uci(tok):
                try:
                    board.apply_uci(tok)
                    uci_list.append(tok)
                    continue
                except Exception:
                    pass
            uci = self._san_to_uci(board, tok)
            if uci is None:
                return None
            board.apply_uci(uci)
            uci_list.append(uci)
        return uci_list

    @staticmethod
    def _looks_like_uci(tok):
        """Quick heuristic: does the token look like a UCI move?"""
        if len(tok) not in (4, 5):
            return False
        return (tok[0] in 'abcdefgh' and tok[1].isdigit() and
                tok[2] in 'abcdefgh' and tok[3].isdigit())

    @staticmethod
    def _san_to_uci(board, san):
        """Translate a SAN string to UCI using the current board's legal moves."""
        san_clean = san.replace('+', '').replace('#', '').replace('x', '')
        legal = board.legal_moves()
        for move in legal:
            fr, fc, tr, tc, promo = move
            test_san = board._build_san(fr, fc, tr, tc, promo, legal)
            test_clean = test_san.replace('+', '').replace('#', '').replace('x', '')
            if test_clean == san_clean or test_san == san:
                uci = f"{chr(ord('a') + fc)}{8 - fr}{chr(ord('a') + tc)}{8 - tr}"
                if promo:
                    uci += promo
                return uci
        return None

    # ── Lookup ────────────────────────────────────────────

    def lookup(self, uci_moves):
        """
        Find the most specific opening that matches the beginning of
        the played move sequence.

        Parameters
        ----------
        uci_moves : list[str]
            The game's move history as UCI strings.

        Returns
        -------
        (eco: str | None, name: str | None)
        """
        played = tuple(uci_moves)
        for seq, eco, name in self._entries:
            n = len(seq)
            if len(played) >= n and played[:n] == seq:
                return eco, name
        return None, None

    def in_book(self, uci_moves):
        """
        Return True while the played sequence is still opening theory,
        i.e. it is a prefix of (or equal to) at least one known book line.

        Parameters
        ----------
        uci_moves : list[str]
            The game's move history as UCI strings.
        """
        played = tuple(uci_moves)
        n = len(played)
        if n == 0:
            return True
        for seq, _, _ in self._entries:
            if len(seq) >= n and seq[:n] == played:
                return True
        return False

    # ── Properties ────────────────────────────────────────

    @property
    def loaded(self):
        """True if at least one opening was loaded from the CSV."""
        return len(self._entries) > 0
