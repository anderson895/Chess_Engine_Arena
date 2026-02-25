import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import time
import random
import sqlite3
import os
import math
from datetime import datetime
from itertools import combinations
import copy

# ── Reuse constants from main module if available, else define locally ─────────
try:
    from constants import (BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV,
                            LOG_BG, INFO_BG, LIGHT_SQ, DARK_SQ, LAST_FROM,
                            LAST_TO, CHECK_SQ, UNICODE, QUALITY_COLORS,
                            RANK_TIERS)
    from utils import normalize_engine_name, build_pgn, get_tier
    from board import Board
    from engine import UCIEngine, AnalyzerEngine
    from elo import compute_elo_ratings                     # ← PATCH: import Elo
    from database import Database
except ImportError:
    try:
        from __main__ import (BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV,
                            LOG_BG, INFO_BG, LIGHT_SQ, DARK_SQ, LAST_FROM,
                            LAST_TO, CHECK_SQ, UNICODE, QUALITY_COLORS,
                            normalize_engine_name, Board, UCIEngine,
                            build_pgn, compute_elo_ratings,
                            get_tier, RANK_TIERS)
        try:
            from __main__ import AnalyzerEngine
        except ImportError:
            AnalyzerEngine = None
        try:
            from database import Database
        except ImportError:
            Database = None
    except ImportError:
        BG       = "#1A1A2E"; PANEL_BG = "#16213E"; ACCENT   = "#E94560"
        TEXT     = "#EAEAEA"; BTN_BG   = "#0F3460"; BTN_HOV  = "#E94560"
        LOG_BG   = "#0D0D1A"; INFO_BG  = "#0A0A18"
        LIGHT_SQ = "#F0D9B5"; DARK_SQ  = "#B58863"
        LAST_FROM= "#CDD26A"; LAST_TO  = "#AAB44F"; CHECK_SQ = "#FF4444"
        AnalyzerEngine = None
        Database = None
        UNICODE  = {
            'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙',
            'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟',
        }
        QUALITY_COLORS = {
            "Brilliant":"#1BECA0","Best":"#5BC0EB","Excellent":"#7FFF00",
            "Great":"#A8D8A8","Good":"#FFDD57","Mistake":"#FFA500","Blunder":"#FF4444",
        }
        RANK_TIERS = [
            (2900,"💻 Super Computer","#FF0000"),(2700,"🌟 Super GM","#FFE600"),
            (2400,"🏆 GM","#57FF35"),(2000,"📘 IM","#42FF8A"),
            (1800,"🎯 FM","#4274FF"),(1600,"📝 Candidate","#CF87EB"),
            (1400,"🔰 Beta","#AAAAAA"),(0,"❓ Unrated","#DBDBDB"),
        ]
        def normalize_engine_name(name):
            for s in [' (White)',' (Black)',' (white)',' (black)',
                    '(White)','(Black)','(white)','(black)']:
                if name.endswith(s): name = name[:-len(s)].strip()
            return name.strip()
        def get_tier(r):
            for t,l,c in RANK_TIERS:
                if r>=t: return l,c
            return "❓ Unrated","#DBDBDB"
        def build_pgn(w,b,moves,result,date,opening_name=None):
            op = f'[Opening "{opening_name}"]\n' if opening_name else ''
            h = (f'[Event "Tournament"]\n[White "{w}"]\n[Black "{b}"]\n'
                f'[Result "{result}"]\n[Date "{date}"]\n{op}\n')
            body=''; sans=[m[1] for m in moves]
            for i,s in enumerate(sans):
                if i%2==0: body+=f"{i//2+1}. "
                body+=s+' '
            return h+body+result
        def compute_elo_ratings(games_raw):
            return {}


# ═══════════════════════════════════════════════════════════════════════════════
#  Loading Overlay — non-blocking spinner shown while DB is fetched off-thread
# ═══════════════════════════════════════════════════════════════════════════════

class LoadingOverlay:
    """
    A translucent overlay with an animated spinner and message label that
    sits on top of any tk widget while a background thread is working.

    Usage
    -----
        overlay = LoadingOverlay(parent_widget, message="Loading…")
        overlay.show()
        # … do work on a thread …
        overlay.hide()

    The overlay prevents the user from interacting with the underlying UI
    without freezing the main thread (no .grab_set()).
    """

    _FRAMES   = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    _INTERVAL = 80   # ms per spinner frame

    def __init__(self, parent: tk.Widget, message: str = "Loading…"):
        self._parent  = parent
        self._message = message
        self._frame_i = 0
        self._after_id: str | None = None
        self._visible = False

        # Semi-transparent dark backdrop
        self._backdrop = tk.Frame(parent, bg="#0D0D1A", cursor="watch")

        # Centred card
        card = tk.Frame(self._backdrop, bg=PANEL_BG,
                        highlightthickness=1,
                        highlightbackground=ACCENT)

        self._spin_lbl = tk.Label(card, text=self._FRAMES[0],
                                  bg=PANEL_BG, fg=ACCENT,
                                  font=("Segoe UI", 22))
        self._spin_lbl.pack(pady=(18, 4))

        self._msg_lbl = tk.Label(card, text=message,
                                 bg=PANEL_BG, fg=TEXT,
                                 font=("Segoe UI", 10))
        self._msg_lbl.pack(padx=28, pady=(0, 18))

        # Float the card in the backdrop centre
        card.place(relx=0.5, rely=0.5, anchor="center")
        self._card = card

    # ── Public API ────────────────────────────────────────────────────────────

    def show(self, message: str | None = None):
        if message:
            self._msg_lbl.config(text=message)
        self._visible = True
        self._backdrop.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self._backdrop.lift()
        self._backdrop.update_idletasks()
        self._animate()

    def hide(self):
        self._visible = False
        if self._after_id is not None:
            try:
                self._parent.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._backdrop.place_forget()

    def update_message(self, message: str):
        self._msg_lbl.config(text=message)

    def destroy(self):
        self.hide()
        try:
            self._backdrop.destroy()
        except Exception:
            pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _animate(self):
        if not self._visible:
            return
        self._spin_lbl.config(text=self._FRAMES[self._frame_i % len(self._FRAMES)])
        self._frame_i += 1
        try:
            self._after_id = self._parent.after(self._INTERVAL, self._animate)
        except Exception:
            pass


def fetch_async(parent: tk.Widget,
                work_fn,
                done_fn,
                overlay: "LoadingOverlay | None" = None,
                error_fn=None):
    """
    Run *work_fn()* on a daemon thread, then schedule *done_fn(result)* back
    on the Tk main thread when complete.

    Parameters
    ----------
    parent    : any tk widget used for .after() scheduling
    work_fn   : callable()  → result  (runs off-thread, NO Tk calls allowed)
    done_fn   : callable(result)       (runs on main thread)
    overlay   : optional LoadingOverlay to hide when done
    error_fn  : optional callable(exception) on error (main thread);
                defaults to printing the error
    """
    def _worker():
        try:
            result = work_fn()
            parent.after(0, lambda: _finish(result, None))
        except Exception as exc:
            parent.after(0, lambda: _finish(None, exc))

    def _finish(result, exc):
        if overlay is not None:
            try:
                overlay.hide()
            except Exception:
                pass
        if exc is not None:
            if error_fn:
                error_fn(exc)
            else:
                print(f"[fetch_async] error: {exc}")
        else:
            done_fn(result)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
#  PATCH: Elo helper — fetch live Elo ratings from DB for tournament players
# ═══════════════════════════════════════════════════════════════════════════════

def _get_elo_map(db) -> dict:
    """
    Returns {engine_name: elo_int} for all engines in the database.
    Returns empty dict if DB is unavailable or on any error.
    """
    if db is None:
        return {}
    try:
        games_raw = db.get_all_games_for_elo()
        return compute_elo_ratings(games_raw)
    except Exception as e:
        print(f"[Elo] Could not load ratings: {e}")
        return {}


def _fmt_elo(elo_map: dict, name: str) -> str:
    """
    Return a formatted Elo string like '1742 📝 Candidate' for display,
    or '—' if the engine has no rating yet.
    """
    elo = elo_map.get(name) or elo_map.get(normalize_engine_name(name))
    if elo is None:
        return "—"
    tier_lbl, _ = get_tier(elo)
    return f"{elo}  {tier_lbl}"


def _elo_color(elo_map: dict, name: str) -> str:
    """Return the tier colour for this engine, or #888888 if unrated."""
    elo = elo_map.get(name) or elo_map.get(normalize_engine_name(name))
    if elo is None:
        return "#888888"
    _, col = get_tier(elo)
    return col


# ═══════════════════════════════════════════════════════════════════════════════
#  Off-thread DB reconstruction helper
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_db_rows(tournament_id: str, rows: list):
    """
    Pure function — no Tk calls allowed.
    Parses raw DB rows into a fully-populated Tournament object so the caller
    can hand the result straight back to the main thread via fetch_async.
    """
    import re as _re

    first  = rows[0]
    t_name = first.get("tournament_name", "Unknown Tournament")
    t_fmt  = first.get("format", "Swiss")  # Tournament.FORMAT_SWISS resolved below
    t_id   = first.get("tournament_id", tournament_id)

    # Resolve Board class (needed for PGN replay)
    _Board = None
    try:
        from board import Board as _Board
    except ImportError:
        try:
            from __main__ import Board as _Board
        except ImportError:
            pass

    player_names: dict = {}
    for row in rows:
        for key in ("white_engine", "black_engine"):
            name = row.get(key, "")
            if name and name not in player_names:
                player_names[name] = TournamentPlayer(name, "")

    players     = list(player_names.values())
    max_round   = max((r.get("round_num", 1) for r in rows), default=1)

    t = Tournament(
        name        = t_name,
        fmt         = t_fmt,
        players     = players,
        rounds      = max_round,
        movetime_ms = 1000,
    )
    t.tournament_id = t_id
    t.started       = True
    t.finished      = True
    t.current_round = max_round

    rounds_by_num: dict = {}
    for row in rows:
        rnum = row.get("round_num", 1)
        rounds_by_num.setdefault(rnum, []).append(row)

    for row in rows:
        wname = row.get("white_engine", "")
        bname = row.get("black_engine", "")
        wp    = player_names.get(wname)
        bp    = player_names.get(bname)
        if wp is None or bp is None:
            continue

        rnum = row.get("round_num", 1)
        g    = TournamentGame(rnum, wp, bp)
        g.result     = row.get("result", "*")
        g.reason     = row.get("reason", "")
        g.pgn        = row.get("pgn", "")
        g.move_count = row.get("move_count") or 0
        g.duration   = row.get("duration_sec") or 0
        g.opening    = row.get("opening", "")
        g.status     = "done"

        if g.pgn and _Board is not None:
            try:
                b     = _Board()
                body  = _re.sub(r'\[.*?\]\s*', '', g.pgn, flags=_re.DOTALL)
                body  = _re.sub(r'\d+\.+', '', body)
                body  = _re.sub(r'1-0|0-1|1/2-1/2|\*', '', body)
                for san in body.split():
                    san = san.strip()
                    if not san:
                        continue
                    try:
                        legal   = b.legal_moves()
                        matched = False
                        for move in legal:
                            fr, fc, tr, tc, promo = move
                            csan = b._build_san(fr, fc, tr, tc, promo, legal)
                            if csan.rstrip('+#') == san.rstrip('+#'):
                                uci = (f"{chr(ord('a')+fc)}{8-fr}"
                                       f"{chr(ord('a')+tc)}{8-tr}"
                                       + (promo.lower() if promo else ""))
                                b.apply_uci(uci)
                                matched = True
                                break
                        if not matched:
                            break
                    except Exception:
                        break
                g.move_history = list(b.move_history)
            except Exception:
                g.move_history = []

        ws = g.white_score
        bs = g.black_score
        if ws is not None:
            wp.record(ws, bname, 'w')
            bp.record(bs, wname, 'b')

        t.all_games.append(g)

        if t_fmt == Tournament.FORMAT_KNOCKOUT:
            t._ko_round_games.setdefault(rnum, []).append(g)

    if t_fmt == Tournament.FORMAT_KNOCKOUT:
        eliminated_set: set = set()
        for rnum in sorted(rounds_by_num.keys()):
            for g in t._ko_round_games.get(rnum, []):
                ws = g.white_score
                bs = g.black_score
                if ws is None:
                    continue
                if ws > bs:
                    eliminated_set.add(g.black.name)
                    t._ko_eliminated.append(g.black)
                elif bs > ws:
                    eliminated_set.add(g.white.name)
                    t._ko_eliminated.append(g.white)
                else:
                    eliminated_set.add(g.black.name)
                    t._ko_eliminated.append(g.black)

        t._ko_pending_winners = [p for p in players if p.name not in eliminated_set]

    t.round_games = (
        t._ko_round_games.get(max_round, [])
        if t_fmt == Tournament.FORMAT_KNOCKOUT
        else [g for g in t.all_games if g.round_num == max_round]
    )

    standings = t.get_standings()
    if standings:
        t.winner = standings[0]

    return t


# ═══════════════════════════════════════════════════════════════════════════════
#  Chunked treeview insert — keeps UI responsive when inserting many rows
# ═══════════════════════════════════════════════════════════════════════════════

def _batch_tree_insert(widget: tk.Widget,
                       tree,
                       rows: list,
                       chunk: int = 150,
                       done_fn=None):
    """
    Insert *rows* into *tree* in chunks of *chunk* items, yielding control to
    Tk between each chunk via widget.after(0, …).

    Each element of *rows* must be a dict:
        {"values": [...], "tags": (...,), "parent": "", "index": "end"}

    *done_fn* is called (no args) on the main thread once all rows are inserted.
    """
    if not rows:
        if done_fn:
            done_fn()
        return

    iterator = iter(rows)

    def _insert_chunk():
        count = 0
        try:
            while count < chunk:
                r = next(iterator)
                tree.insert(
                    r.get("parent", ""),
                    r.get("index", "end"),
                    values=r["values"],
                    tags=r.get("tags", ()),
                    iid=r.get("iid"),
                )
                count += 1
        except StopIteration:
            if done_fn:
                done_fn()
            return
        widget.after(0, _insert_chunk)

    widget.after(0, _insert_chunk)


# ═══════════════════════════════════════════════════════════════════════════════
#  Data Classes
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentPlayer:
    def __init__(self, name, engine_path):
        self.name          = normalize_engine_name(name)
        self.engine_path   = engine_path
        self.score         = 0.0
        self.wins          = 0
        self.draws         = 0
        self.losses        = 0
        self.buchholz      = 0.0
        self.sonneborn     = 0.0
        self.color_history = []
        self.opponents     = []
        self.seed          = 0

    def record(self, result, opponent_name, color):
        self.score += result
        if   result == 1.0: self.wins   += 1
        elif result == 0.5: self.draws  += 1
        else:               self.losses += 1
        self.color_history.append(color)
        self.opponents.append(opponent_name)

    @property
    def games_played(self):
        return self.wins + self.draws + self.losses

    def __repr__(self):
        return f"<TPlayer {self.name} {self.score}>"


class TournamentGame:
    def __init__(self, round_num, white: TournamentPlayer, black: TournamentPlayer):
        self.round_num    = round_num
        self.white        = white
        self.black        = black
        self.result       = None
        self.reason       = ""
        self.pgn          = ""
        self.move_count   = 0
        self.duration     = 0
        self.opening      = ""
        self.status       = "pending"
        self.move_history = []
        self.eval_history = []
        self.id           = id(self)

    @property
    def white_score(self):
        if self.result == '1-0':      return 1.0
        if self.result == '1/2-1/2':  return 0.5
        if self.result == '0-1':      return 0.0
        return None

    @property
    def black_score(self):
        ws = self.white_score
        return None if ws is None else (1.0 - ws if ws != 0.5 else 0.5)


# ═══════════════════════════════════════════════════════════════════════════════
#  Pairing Algorithms
# ═══════════════════════════════════════════════════════════════════════════════

class SwissPairing:
    @staticmethod
    def pair(players, round_num, played_pairs):
        available = list(players)
        available.sort(key=lambda p: (-p.score, -p.wins, p.name))
        pairings = []
        bye_player = None

        if len(available) % 2 == 1:
            for p in reversed(available):
                if 'BYE' not in p.opponents:
                    bye_player = p
                    available.remove(p)
                    break
            if bye_player is None:
                bye_player = available.pop()

        paired = SwissPairing._backtrack_pair(available, played_pairs, 0)

        for i in range(0, len(paired), 2):
            p1, p2 = paired[i], paired[i+1]
            w, b = SwissPairing._assign_colors(p1, p2)
            pairings.append((w, b))

        return pairings, bye_player

    @staticmethod
    def _backtrack_pair(players, played_pairs, depth):
        if not players:
            return []
        if len(players) == 2:
            return players[:]
        p1 = players[0]
        rest = players[1:]
        for i, p2 in enumerate(rest):
            pair_key = frozenset({p1.name, p2.name})
            if pair_key not in played_pairs:
                remaining = rest[:i] + rest[i+1:]
                sub = SwissPairing._backtrack_pair(remaining, played_pairs, depth+1)
                if sub is not None:
                    return [p1, p2] + sub
        p2 = rest[0]
        remaining = rest[1:]
        sub = SwissPairing._backtrack_pair(remaining, played_pairs, depth+1)
        return [p1, p2] + (sub or [])

    @staticmethod
    def _assign_colors(p1, p2):
        b1 = p1.color_history.count('b') - p1.color_history.count('w')
        b2 = p2.color_history.count('b') - p2.color_history.count('w')
        if b1 > b2:   return p1, p2
        elif b2 > b1: return p2, p1
        else:
            if p1.color_history and p1.color_history[-1] == 'b': return p1, p2
            if p2.color_history and p2.color_history[-1] == 'b': return p2, p1
            return (p1, p2) if random.random() < 0.5 else (p2, p1)


class RoundRobinPairing:
    @staticmethod
    def generate_all_rounds(players, double=False):
        n = len(players)
        lst = list(players)
        rounds_single = []
        if n % 2 == 1:
            lst.append(None)
            n += 1
        fixed = lst[0]
        rotating = lst[1:]

        for _ in range(n - 1):
            circle = [fixed] + rotating
            pairs = []
            for i in range(n // 2):
                p1 = circle[i]
                p2 = circle[n - 1 - i]
                if p1 is None or p2 is None:
                    continue
                if i % 2 == 0:
                    pairs.append((p1, p2))
                else:
                    pairs.append((p2, p1))
            rounds_single.append(pairs)
            rotating = [rotating[-1]] + rotating[:-1]

        if double:
            rounds_double = []
            for round_pairs in rounds_single:
                rounds_double.append([(b, w) for w, b in round_pairs])
            return rounds_single + rounds_double
        return rounds_single


class KnockoutBracket:
    @staticmethod
    def seed_bracket(players):
        n = len(players)
        size = 1
        while size < n:
            size *= 2
        seeded = list(players) + [None] * (size - n)
        bracket = []
        for i in range(size // 2):
            bracket.append((seeded[i], seeded[size - 1 - i]))
        return bracket

    @staticmethod
    def next_round(winners):
        pairs = []
        lst = list(winners)
        random.shuffle(lst)
        for i in range(0, len(lst) - 1, 2):
            if random.random() < 0.5:
                pairs.append((lst[i], lst[i+1]))
            else:
                pairs.append((lst[i+1], lst[i]))
        return pairs


# ═══════════════════════════════════════════════════════════════════════════════
#  Tournament Controller
# ═══════════════════════════════════════════════════════════════════════════════

class Tournament:
    FORMAT_SWISS       = "Swiss"
    FORMAT_ROUNDROBIN  = "Round Robin"
    FORMAT_KNOCKOUT    = "Knockout"

    def __init__(self, name, fmt, players, rounds, movetime_ms=1000,
                double_rr=False, delay=0.3, analyzer_path=None,
                opening_book=None):
        self.name          = name
        self.format        = fmt
        self.players       = {p.name: p for p in players}
        self.player_list   = list(players)
        self.rounds        = rounds
        self.movetime_ms   = movetime_ms
        self.double_rr     = double_rr
        self.delay         = delay
        self.analyzer_path = analyzer_path
        self.opening_book  = opening_book

        self.current_round = 0
        self.all_games     = []
        self.round_games   = []
        self.played_pairs  = set()
        self.bye_history   = set()
        self.started       = False
        self.finished      = False
        self.winner        = None
        self.status_msg    = "Ready"
        self.created_at    = datetime.now()

        self.tournament_id = str(id(self))

        self._ko_pending_winners = []
        self._ko_eliminated      = []
        self._ko_round_games     = {}
        self._ko_active_players  = list(players)

        if fmt == self.FORMAT_ROUNDROBIN:
            self._rr_schedule = RoundRobinPairing.generate_all_rounds(
                self.player_list, double=double_rr)
            self.rounds = len(self._rr_schedule)
        else:
            self._rr_schedule = None

    def start(self):
        self.started = True
        self._generate_round()
        self.status_msg = f"Round {self.current_round} started"

    def _generate_round(self):
        self.current_round += 1
        self.round_games = []

        if self.format == self.FORMAT_SWISS:
            pairs, bye = SwissPairing.pair(
                self.player_list, self.current_round, self.played_pairs)
            for w, b in pairs:
                g = TournamentGame(self.current_round, w, b)
                self.round_games.append(g)
                self.all_games.append(g)
            if bye:
                bye.record(1.0, 'BYE', 'w')
                self.bye_history.add(bye.name)

        elif self.format == self.FORMAT_ROUNDROBIN:
            idx = self.current_round - 1
            if idx < len(self._rr_schedule):
                for w, b in self._rr_schedule[idx]:
                    g = TournamentGame(self.current_round, w, b)
                    self.round_games.append(g)
                    self.all_games.append(g)

        elif self.format == self.FORMAT_KNOCKOUT:
            if self.current_round == 1:
                bracket = KnockoutBracket.seed_bracket(self._ko_active_players)
                for w, b in bracket:
                    if w is None or b is None:
                        survivor = w or b
                        if survivor:
                            self._ko_pending_winners.append(survivor)
                        continue
                    g = TournamentGame(self.current_round, w, b)
                    self.round_games.append(g)
                    self.all_games.append(g)
                self._ko_round_games[self.current_round] = list(self.round_games)
            else:
                prev_winners = list(self._ko_pending_winners)
                self._ko_pending_winners = []
                if len(prev_winners) <= 1:
                    self.winner = prev_winners[0] if prev_winners else None
                    self._finish()
                    return
                pairs = KnockoutBracket.next_round(prev_winners)
                for w, b in pairs:
                    g = TournamentGame(self.current_round, w, b)
                    self.round_games.append(g)
                    self.all_games.append(g)
                self._ko_round_games[self.current_round] = list(self.round_games)

    def record_game_result(self, game: TournamentGame, result, reason,
                           move_history, pgn, duration, opening=None,
                           eval_history=None):
        game.result       = result
        game.reason       = reason
        game.pgn          = pgn
        game.move_count   = len(move_history)
        game.duration     = duration
        game.opening      = opening or ""
        game.move_history = move_history
        game.eval_history = eval_history or []
        game.status       = "done"

        pair_key = frozenset({game.white.name, game.black.name})
        self.played_pairs.add(pair_key)

        ws = game.white_score
        bs = game.black_score
        if ws is not None:
            game.white.record(ws, game.black.name, 'w')
            game.black.record(bs, game.white.name, 'b')

        if self.format == self.FORMAT_KNOCKOUT and ws is not None:
            if ws > bs:
                self._ko_pending_winners.append(game.white)
                self._ko_eliminated.append(game.black)
            elif bs > ws:
                self._ko_pending_winners.append(game.black)
                self._ko_eliminated.append(game.white)
            else:
                adv  = random.choice([game.white, game.black])
                elim = game.black if adv is game.white else game.white
                self._ko_pending_winners.append(adv)
                self._ko_eliminated.append(elim)

    def round_complete(self):
        return all(g.status == "done" for g in self.round_games)

    def advance_round(self):
        self._update_buchholz()

        if self.format == self.FORMAT_SWISS:
            if self.current_round >= self.rounds:
                self._finish()
                return True
            self._generate_round()
            return False

        elif self.format == self.FORMAT_ROUNDROBIN:
            if self.current_round >= self.rounds:
                self._finish()
                return True
            self._generate_round()
            return False

        elif self.format == self.FORMAT_KNOCKOUT:
            active = self._ko_pending_winners
            if len(active) <= 1:
                self.winner = active[0] if active else None
                self._finish()
                return True
            self._generate_round()
            return False

        return True

    def _finish(self):
        self.finished = True
        standings = self.get_standings()
        if standings and self.winner is None:
            self.winner = standings[0]
        self.status_msg = (
            f"Tournament complete! Winner: {self.winner.name if self.winner else '?'}")

    def _update_buchholz(self):
        if self.format != self.FORMAT_SWISS:
            return
        score_map = {p.name: p.score for p in self.player_list}
        for p in self.player_list:
            p.buchholz  = sum(score_map.get(opp, 0) for opp in p.opponents if opp != 'BYE')
            p.sonneborn = 0.0
            for g in self.all_games:
                if g.status != 'done':
                    continue
                if g.white is p and g.white_score is not None:
                    p.sonneborn += g.white_score * score_map.get(g.black.name, 0)
                elif g.black is p and g.black_score is not None:
                    p.sonneborn += g.black_score * score_map.get(g.white.name, 0)

    def get_standings(self):
        players = list(self.player_list)
        if self.format == self.FORMAT_SWISS:
            players.sort(key=lambda p: (-p.score, -p.buchholz, -p.sonneborn, p.name))
        elif self.format == self.FORMAT_ROUNDROBIN:
            players.sort(key=lambda p: (-p.score, -p.wins, p.name))
        elif self.format == self.FORMAT_KNOCKOUT:
            eliminated_names = [p.name for p in self._ko_eliminated]
            def ko_key(p):
                if p.name not in eliminated_names:
                    return (0, -p.score, p.name)
                idx = eliminated_names.index(p.name)
                return (len(eliminated_names) - idx, -p.score, p.name)
            players.sort(key=ko_key)
        return players

    def get_pending_games(self):
        return [g for g in self.round_games if g.status == "pending"]

    def next_game(self):
        pending = self.get_pending_games()
        return pending[0] if pending else None

    def get_all_completed_games(self):
        return [g for g in self.all_games if g.status == "done"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Eval Bar Widget
# ═══════════════════════════════════════════════════════════════════════════════

class EvalBarWidget(tk.Frame):
    BAR_W  = 22
    BAR_H  = 448

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._eval_cp   = 0.0
        self._eval_text = "0.0"
        self._mate      = None

        self.canvas = tk.Canvas(
            self, width=self.BAR_W, height=self.BAR_H,
            bg="#333", bd=0, highlightthickness=1,
            highlightbackground="#555")
        self.canvas.pack(side='top')

        self.lbl = tk.Label(
            self, text="0.0", bg=BG, fg=TEXT,
            font=('Consolas', 7), width=4, anchor='center')
        self.lbl.pack(side='top', pady=(1, 0))

        self._draw(0)

    def set_eval(self, cp, mate=None):
        self._eval_cp = cp
        self._mate    = mate
        self._draw(cp, mate)

    def reset(self):
        self._eval_cp = 0.0
        self._mate    = None
        self._draw(0)

    def _draw(self, cp, mate=None):
        c  = self.canvas
        c.delete('all')
        w  = self.BAR_W
        h  = self.BAR_H
        c.create_rectangle(0, 0, w, h, fill="#222", outline='')
        MAX_CP = 500
        if mate is not None:
            frac = 1.0 if mate > 0 else 0.0
        else:
            frac = max(0.0, min(1.0, (cp + MAX_CP) / (2 * MAX_CP)))
        white_h = int(frac * h)
        black_h = h - white_h
        c.create_rectangle(0, 0, w, black_h, fill="#2a2a2a", outline='')
        c.create_rectangle(0, black_h, w, h, fill="#e8e8e8", outline='')
        c.create_line(0, h//2, w, h//2, fill="#555", width=1)
        c.create_line(0, black_h, w, black_h, fill=ACCENT, width=2)
        if mate is not None:
            txt = f"M{abs(mate)}"
            col = "#00FF80" if mate > 0 else "#FF4444"
        else:
            pawn_val = cp / 100.0
            txt = f"{pawn_val:+.1f}"
            col = "#FFD700" if cp > 30 else "#4444FF" if cp < -30 else "#AAAAAA"
        self.lbl.config(text=txt, fg=col)


# ═══════════════════════════════════════════════════════════════════════════════
#  Eval Graph Widget
# ═══════════════════════════════════════════════════════════════════════════════

class EvalGraphWidget(tk.Frame):
    def __init__(self, parent, width=580, height=90, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self.W = width
        self.H = height
        self._evals = []
        self.canvas = tk.Canvas(
            self, width=self.W, height=self.H,
            bg="#0a0a18", bd=0,
            highlightthickness=1,
            highlightbackground="#333")
        self.canvas.pack(fill='both', expand=True)
        self._draw([])

    def set_evals(self, eval_list):
        self._evals = list(eval_list)
        self._draw(self._evals)

    def highlight_move(self, idx):
        self._draw(self._evals, highlight=idx)

    def _draw(self, evals, highlight=None):
        c  = self.canvas
        c.delete('all')
        W, H = self.W, self.H
        mid = H // 2
        c.create_rectangle(0, 0, W, mid, fill="#080818", outline='')
        c.create_rectangle(0, mid, W, H, fill="#0d1208", outline='')
        for i in range(1, 5):
            y = int(mid - (i/5) * mid * 0.85)
            c.create_line(0, y, W, y, fill="#1a1a2a", width=1)
            y2 = int(mid + (i/5) * mid * 0.85)
            c.create_line(0, y2, W, y2, fill="#121a12", width=1)
        c.create_line(0, mid, W, mid, fill="#333", width=1, dash=(4,4))
        if not evals:
            c.create_text(W//2, H//2, text="No eval data",
                        fill="#444", font=('Segoe UI', 8))
            return
        MAX_CP = 600
        n = len(evals)
        def cp_to_y(cp):
            frac = max(-1.0, min(1.0, cp / MAX_CP))
            return int(mid - frac * mid * 0.88)
        def idx_to_x(i):
            if n <= 1: return W // 2
            return int(i * (W - 4) / (n - 1)) + 2
        poly_pts = [2, mid]
        for i, cp in enumerate(evals):
            poly_pts += [idx_to_x(i), cp_to_y(cp)]
        poly_pts += [idx_to_x(n-1), mid]
        c.create_polygon(poly_pts, fill="#1a3a1a", outline='', smooth=True)
        pts = []
        for i, cp in enumerate(evals):
            pts += [idx_to_x(i), cp_to_y(cp)]
        if len(pts) >= 4:
            c.create_line(pts, fill="#00CC44", width=2, smooth=True)
        for i in range(1, n):
            delta = evals[i] - evals[i-1]
            if abs(delta) > 150:
                x = idx_to_x(i)
                y = cp_to_y(evals[i])
                col = "#FF4444" if delta < 0 else "#FF8800"
                c.create_oval(x-4, y-4, x+4, y+4, fill=col, outline='')
        if highlight is not None and 0 <= highlight < n:
            x = idx_to_x(highlight)
            y = cp_to_y(evals[highlight])
            c.create_line(x, 0, x, H, fill=ACCENT, width=1, dash=(3,3))
            c.create_oval(x-5, y-5, x+5, y+5,
                        fill=ACCENT, outline='white', width=1)
        for label, cp_val in [("+5", 500), ("+2", 200), ("0", 0), ("-2", -200), ("-5", -500)]:
            y = cp_to_y(cp_val)
            if 4 <= y <= H - 4:
                c.create_text(W-16, y, text=label, fill="#444",
                            font=('Consolas', 6), anchor='e')


# ═══════════════════════════════════════════════════════════════════════════════
#  Mini Board Widget
# ═══════════════════════════════════════════════════════════════════════════════

class MiniBoardWidget(tk.Frame):
    SQ = 56

    def __init__(self, parent, show_eval_bar=True, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._board_state  = None
        self._last_move    = None
        self._in_replay    = False
        self._replay_moves = []
        self._replay_idx   = 0
        self._replay_board = None
        self._replay_evals = []
        self._show_eval    = show_eval_bar
        self._build()

    def _build(self):
        sz = self.SQ
        outer = tk.Frame(self, bg=BG)
        outer.pack(side='top')
        if self._show_eval:
            self.eval_bar = EvalBarWidget(outer)
            self.eval_bar.pack(side='left', padx=(0, 3), anchor='n')
        else:
            self.eval_bar = None
        board_frame = tk.Frame(outer, bg=BG)
        board_frame.pack(side='left')
        self.canvas = tk.Canvas(
            board_frame, width=sz*8, height=sz*8,
            bg=BG, bd=0, highlightthickness=2,
            highlightcolor=ACCENT,
            highlightbackground="#333")
        self.canvas.pack(side='top')
        ctrl = tk.Frame(self, bg=BG)
        ctrl.pack(fill='x', pady=2)
        for sym, cmd in [("⏮","_rep_start"),("◀","_rep_prev"),
                        ("▶","_rep_next"),("⏭","_rep_end")]:
            tk.Button(ctrl, text=sym,
                    command=lambda c=cmd: getattr(self, c)(),
                    bg=BTN_BG, fg=TEXT, font=('Segoe UI',10),
                    width=3, relief='flat', cursor='hand2',
                    padx=2, pady=2).pack(side='left', padx=2)
        self.move_lbl = tk.Label(ctrl, text="", bg=BG, fg="#AAA",
                                font=('Consolas',8), anchor='w')
        self.move_lbl.pack(side='left', padx=4, fill='x', expand=True)

    def update_live(self, board_rows, last_move=None, eval_cp=None, eval_mate=None):
        if hasattr(board_rows, 'board'):
            self._board_state = [row[:] for row in board_rows.board]
        else:
            self._board_state = board_rows
        self._last_move = last_move
        self._in_replay = False
        self._draw(self._board_state, last_move)
        self.move_lbl.config(text="● LIVE")
        if self.eval_bar is not None:
            if eval_cp is not None:
                self.eval_bar.set_eval(eval_cp, eval_mate)

    def set_replay(self, move_history, eval_history=None):
        self._replay_moves = [m[0] for m in move_history]
        self._replay_evals = eval_history or []
        self._replay_idx   = len(self._replay_moves)
        self._in_replay    = True
        self._render_replay()

    def _rep_start(self): self._replay_idx = 0;                        self._render_replay()
    def _rep_end(self):   self._replay_idx = len(self._replay_moves);  self._render_replay()
    def _rep_prev(self):
        if self._replay_idx > 0: self._replay_idx -= 1
        self._render_replay()
    def _rep_next(self):
        if self._replay_idx < len(self._replay_moves): self._replay_idx += 1
        self._render_replay()

    def _render_replay(self):
        try:
            from __main__ import Board as _Board
        except ImportError:
            try:
                from board import Board as _Board
            except ImportError:
                return
        b = _Board()
        moves = self._replay_moves[:self._replay_idx]
        for uci in moves:
            try: b.apply_uci(uci)
            except: break
        last = moves[-1] if moves else None
        self._draw_from_board(b, last)
        if self.eval_bar is not None:
            idx = self._replay_idx - 1
            if 0 <= idx < len(self._replay_evals):
                self.eval_bar.set_eval(self._replay_evals[idx])
            else:
                self.eval_bar.reset()
        n = self._replay_idx
        total = len(self._replay_moves)
        if n > 0:
            san = ""
            try:
                tmp = _Board()
                for uci in self._replay_moves[:n-1]:
                    tmp.apply_uci(uci)
                legal = tmp.legal_moves()
                uci_now = self._replay_moves[n-1]
                fc = ord(uci_now[0])-ord('a'); fr = 8-int(uci_now[1])
                tc = ord(uci_now[2])-ord('a'); tr = 8-int(uci_now[3])
                promo = uci_now[4].lower() if len(uci_now)>4 else None
                san = tmp._build_san(fr,fc,tr,tc,promo,legal)
            except: pass
            side = "White" if n%2==1 else "Black"
            self.move_lbl.config(
                text=f"Move {(n+1)//2} {side}: {san}  [{n}/{total}]")
        else:
            self.move_lbl.config(text=f"Start  [0/{total}]")

    def _draw_from_board(self, board_obj, last_move=None):
        rows = [row[:] for row in board_obj.board]
        self._draw(rows, last_move)

    def _draw(self, rows, last_move=None):
        self.canvas.delete('all')
        sz = self.SQ
        lm_from = lm_to = None
        if last_move and len(last_move) >= 4:
            lm_from = (8-int(last_move[1]), ord(last_move[0])-ord('a'))
            lm_to   = (8-int(last_move[3]), ord(last_move[2])-ord('a'))
        for row in range(8):
            for col in range(8):
                light = (row+col)%2 == 0
                color = LIGHT_SQ if light else DARK_SQ
                if lm_from and (row,col)==lm_from: color=LAST_FROM
                elif lm_to and (row,col)==lm_to:   color=LAST_TO
                x1,y1 = col*sz, row*sz
                x2,y2 = x1+sz, y1+sz
                self.canvas.create_rectangle(x1,y1,x2,y2,fill=color,outline='')
                if rows:
                    try:    pc = rows[row][col]
                    except: pc = '.'
                    if pc and pc != '.':
                        sym = UNICODE.get(pc, pc)
                        fg  = '#F5F5F5' if pc.isupper() else '#1A1A1A'
                        sh  = '#000000' if pc.isupper() else '#888888'
                        fsz = int(sz*0.60)
                        cx, cy = x1+sz//2, y1+sz//2
                        self.canvas.create_text(cx+1,cy+2,text=sym,
                            font=('Segoe UI',fsz),fill=sh)
                        self.canvas.create_text(cx,cy,text=sym,
                            font=('Segoe UI',fsz),fill=fg)
        self.canvas.create_rectangle(0,0,sz*8,sz*8,outline='#555',width=1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Tournament Runner
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentRunner:
    def __init__(self, tournament: Tournament, on_game_start,
                on_board_update, on_game_end, on_round_end,
                on_tournament_end, on_status):
        self.t               = tournament
        self.on_game_start   = on_game_start
        self.on_board_update = on_board_update
        self.on_game_end     = on_game_end
        self.on_round_end    = on_round_end
        self.on_tournament_end = on_tournament_end
        self.on_status       = on_status
        self._stop_flag      = False
        self._pause_flag     = False
        self._thread         = None
        self.current_engines = []
        self._analyzer       = None
        self._analyzer_is_external = False

    def start(self):
        self._stop_flag  = False
        self._pause_flag = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):  self._pause_flag = True
    def resume(self): self._pause_flag = False
    def stop(self):   self._stop_flag = True; self._pause_flag = False

    def _run(self):
        analyzer_ref = self.t.analyzer_path
        if analyzer_ref is not None and AnalyzerEngine is not None:
            if isinstance(analyzer_ref, str):
                if os.path.isfile(analyzer_ref):
                    try:
                        self._analyzer = AnalyzerEngine(analyzer_ref, "Analyzer")
                        self._analyzer.start()
                        self._analyzer_is_external = False
                        self.on_status(
                            f"🔍 Analyzer ready: {os.path.basename(analyzer_ref)}")
                    except Exception as e:
                        self._analyzer = None
                        self.on_status(f"⚠ Analyzer failed to start: {e}")
                else:
                    self.on_status("⚠ Analyzer path not found — running without analysis")
            else:
                if hasattr(analyzer_ref, 'alive') and analyzer_ref.alive:
                    self._analyzer = analyzer_ref
                    self._analyzer_is_external = True
                    name = ""
                    if hasattr(analyzer_ref, 'path') and isinstance(analyzer_ref.path, str):
                        name = os.path.basename(analyzer_ref.path)
                    self.on_status(f"🔍 Using GUI analyzer{': ' + name if name else ''}")
                else:
                    self.on_status("⚠ GUI analyzer not alive — running without analysis")

        if not self.t.started:
            self.t.start()

        while not self._stop_flag and not self.t.finished:
            while self._pause_flag and not self._stop_flag:
                time.sleep(0.1)

            game = self.t.next_game()
            if game is None:
                if self.t.round_complete():
                    self.on_status(f"Round {self.t.current_round} complete!")
                    time.sleep(0.5)
                    done = self.t.advance_round()
                    self.on_round_end(self.t.current_round - (0 if done else 1))
                    if done:
                        break
                else:
                    time.sleep(0.1)
                continue

            self._play_game(game)
            if self._stop_flag:
                break

        if self._analyzer and not self._analyzer_is_external:
            try: self._analyzer.stop()
            except: pass

        if self.t.finished:
            self.on_tournament_end(self.t)
        else:
            self.on_status("Tournament paused / stopped.")

    def _lookup_opening(self, book, board):
        if book is None:
            return None
        if hasattr(book, 'lookup'):
            try:
                uci_str = board.uci_moves_str() if hasattr(board, 'uci_moves_str') else ""
                played  = uci_str.split() if uci_str else []
                result  = book.lookup(played)
                if isinstance(result, (list, tuple)) and len(result) == 2:
                    eco, name = result
                    if name:
                        return str(name)
                elif isinstance(result, str) and result:
                    return result
            except Exception as e:
                print(f"[OpeningBook.lookup] error: {e}")
            return None
        if hasattr(book, 'get_opening_name'):
            try:
                uci_str = board.uci_moves_str() if hasattr(board, 'uci_moves_str') else ""
                name = book.get_opening_name(uci_str)
                if name:
                    return str(name)
            except Exception as e:
                print(f"[book.get_opening_name] error: {e}")
            return None
        return None

    def _play_game(self, game: TournamentGame):
        game.status = "running"
        self.on_game_start(game)
        self.on_status(
            f"Round {game.round_num}: {game.white.name}  vs  {game.black.name}")

        e_white = e_black = None
        try:
            e_white = UCIEngine(game.white.engine_path, game.white.name)
            e_black = UCIEngine(game.black.engine_path, game.black.name)
            e_white.start()
            e_black.start()
            self.current_engines = [e_white, e_black]
        except Exception as ex:
            self._abort_game(game, str(ex))
            self._kill(e_white, e_black)
            return

        try:
            from __main__ import Board as _Board
        except ImportError:
            try:
                from board import Board as _Board
            except ImportError:
                self._abort_game(game, "Board class unavailable")
                self._kill(e_white, e_black)
                return

        board        = _Board()
        last_move    = None
        start_t      = time.time()
        eval_history = []
        opening_name = None
        result       = None
        reason       = ""

        book = self.t.opening_book
        book_moves_used = 0
        MAX_BOOK_MOVES  = 20

        while True:
            if self._stop_flag: break
            while self._pause_flag and not self._stop_flag:
                time.sleep(0.1)

            over, result, reason, winner_color = board.game_result()
            if over: break

            is_white_turn = board.turn == 'w'
            engine        = e_white if is_white_turn else e_black
            player        = game.white if is_white_turn else game.black

            if not engine.alive:
                result = '0-1' if is_white_turn else '1-0'
                reason = f"{player.name} engine died"
                break

            uci = None

            try:
                legal_ucis = set()
                for (fr, fc, tr, tc, promo) in board.legal_moves():
                    base = (f"{chr(ord('a')+fc)}{8-fr}"
                            f"{chr(ord('a')+tc)}{8-tr}")
                    legal_ucis.add(base + promo.lower() if promo else base)
            except Exception:
                legal_ucis = None

            if book is not None and book_moves_used < MAX_BOOK_MOVES:
                raw = self._book_probe(book, board)
                if raw:
                    raw_norm = raw.strip().lower()
                    if legal_ucis is None or raw_norm in legal_ucis:
                        uci = raw_norm
                        book_moves_used += 1

            if not uci:
                mvs = board.uci_moves_str()
                try:
                    engine._drain()
                except Exception:
                    pass
                uci = engine.get_best_move(mvs, self.t.movetime_ms)
                if uci:
                    uci = uci.strip().lower()

            if not uci:
                result = '0-1' if is_white_turn else '1-0'
                reason = f"{player.name} returned no move"
                break

            if legal_ucis is not None and uci not in legal_ucis:
                prefix_match = next(
                    (m for m in legal_ucis if m[:4] == uci[:4]), None)
                if prefix_match and len(uci) == 4 and len(prefix_match) == 5:
                    uci = uci + 'q'
                elif uci not in legal_ucis:
                    result = '0-1' if is_white_turn else '1-0'
                    reason = f"Illegal move by {player.name}: {uci}"
                    break

            try:
                san, _ = board.apply_uci(uci)
            except ValueError as ve:
                result = '0-1' if is_white_turn else '1-0'
                reason = f"Illegal move by {player.name}: {uci} ({ve})"
                break

            last_move = uci

            if book is not None:
                found_name = self._lookup_opening(book, board)
                if found_name:
                    opening_name = found_name

            cp_val   = None
            mate_val = None
            if self._analyzer:
                try:
                    mvs_for_eval = board.uci_moves_str() if hasattr(board, 'uci_moves_str') else ""
                    if hasattr(self._analyzer, 'eval_position'):
                        cp_val, score_type = self._analyzer.eval_position(
                            mvs_for_eval, movetime_ms=150)
                        if cp_val is not None:
                            if score_type == 'mate':
                                mate_val = cp_val // 30000 if cp_val != 0 else 0
                            eval_history.append(cp_val)
                    elif hasattr(self._analyzer, 'get_eval'):
                        cp_val = self._analyzer.get_eval(mvs_for_eval, movetime_ms=150)
                        if cp_val is not None:
                            eval_history.append(cp_val)
                except Exception:
                    pass

            self.on_board_update(game, board, last_move, cp_val, mate_val, opening_name)
            time.sleep(max(0.02, self.t.delay))

        if not result:
            over, result, reason, winner_color = board.game_result()
            if not result:
                result = '*'
                reason = "Unknown"

        duration = int(time.time() - start_t)
        date_str = datetime.now().strftime("%Y.%m.%d")
        pgn = build_pgn(game.white.name, game.black.name,
                        board.move_history, result, date_str,
                        opening_name=opening_name)

        self.t.record_game_result(
            game, result, reason, board.move_history, pgn,
            duration, opening=opening_name, eval_history=eval_history)

        self._kill(e_white, e_black)
        self.on_game_end(game)

    def _book_probe(self, book, board):
        import re
        _UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbnQRBN]?$')

        def _clean(raw):
            if not raw or not isinstance(raw, str):
                return None
            raw = raw.strip().lower().split()[0]
            return raw if _UCI_RE.match(raw) else None

        try:
            if hasattr(book, 'get_move'):
                uci_str = board.uci_moves_str() if hasattr(board, 'uci_moves_str') else ""
                return _clean(book.get_move(uci_str))
            if hasattr(book, 'probe') and hasattr(board, 'to_fen'):
                return _clean(book.probe(board.to_fen()))
            if hasattr(book, 'get'):
                uci_str = board.uci_moves_str() if hasattr(board, 'uci_moves_str') else ""
                moves = uci_str.split() if uci_str else []
                return _clean(book.get(moves))
        except Exception:
            pass
        return None

    def _abort_game(self, game, reason):
        game.result = '*'
        game.reason = reason
        game.status = 'done'
        self.on_game_end(game)

    def _kill(self, *engines):
        for e in engines:
            if e:
                try: e.stop()
                except: pass
        self.current_engines = []


# ═══════════════════════════════════════════════════════════════════════════════
#  Tournament History Window
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentHistoryWindow:
    def __init__(self, parent, tournament: Tournament, db=None):
        self.t   = tournament
        self.db  = db
        self.win = tk.Toplevel(parent)
        self.win.title(f"📜 Tournament History — {tournament.name}")
        self.win.configure(bg=BG)
        self.win.geometry("1100x740")
        self.win.resizable(True, True)
        self.win.minsize(860, 600)
        self._selected_game: TournamentGame = None
        self._game_map = {}
        self._elo_map  = {}           # filled async below
        self._build()
        self._populate_game_list()

        # ── Load Elo off-thread so window opens instantly ─────────────────────
        self._elo_overlay = LoadingOverlay(self.win, "Fetching Elo ratings…")
        self._elo_overlay.show()
        fetch_async(
            parent  = self.win,
            work_fn = lambda: _get_elo_map(self.db),
            done_fn = self._on_elo_loaded,
            overlay = self._elo_overlay,
        )

    def _on_elo_loaded(self, elo_map: dict):
        """Called on main thread once background Elo fetch is done."""
        self._elo_map = elo_map
        # refresh badges on whatever game is currently selected
        if self._selected_game:
            self._load_game(self._selected_game)

    def _build(self):
        tb = tk.Frame(self.win, bg=PANEL_BG, height=44)
        tb.pack(fill='x')
        tk.Label(tb, text="📜  Tournament History",
                bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI', 12, 'bold')).pack(side='left', padx=14, pady=8)
        tk.Label(tb, text=self.t.name, bg=PANEL_BG, fg="#666",
                font=('Segoe UI', 9)).pack(side='left')
        tk.Button(tb, text="💾 Export PGN",
                command=self._export_pgn,
                bg=BTN_BG, fg=TEXT, relief='flat',
                font=('Segoe UI', 9), padx=10, pady=4,
                cursor='hand2').pack(side='right', padx=8, pady=6)
        tk.Frame(self.win, bg=ACCENT, height=2).pack(fill='x')
        paned = tk.PanedWindow(self.win, orient='horizontal',
                                bg=BG, sashwidth=6, sashrelief='flat')
        paned.pack(fill='both', expand=True, padx=6, pady=6)
        left  = tk.Frame(paned, bg=PANEL_BG)
        right = tk.Frame(paned, bg=BG)
        paned.add(left,  minsize=320)
        paned.add(right, minsize=500)
        self._build_game_list(left)
        self._build_viewer(right)

    def _build_game_list(self, p):
        hdr = tk.Frame(p, bg=PANEL_BG)
        hdr.pack(fill='x', padx=8, pady=(8,4))
        tk.Label(hdr, text="Games", bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.game_count_lbl = tk.Label(hdr, text="", bg=PANEL_BG, fg="#555",
                                        font=('Segoe UI', 8))
        self.game_count_lbl.pack(side='left', padx=6)
        flt = tk.Frame(p, bg=PANEL_BG)
        flt.pack(fill='x', padx=8, pady=(0,4))
        tk.Label(flt, text="Filter:", bg=PANEL_BG, fg="#888",
                font=('Segoe UI', 8)).pack(side='left')
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', lambda *_: self._populate_game_list())
        tk.Entry(flt, textvariable=self.filter_var,
                bg=LOG_BG, fg=TEXT, font=('Segoe UI', 8),
                width=18, relief='flat',
                insertbackground=TEXT).pack(side='left', padx=4, ipady=3)
        self.result_filter = tk.StringVar(value="All")
        for val, txt in [("All","All"),("1-0","⬜ W"),("0-1","⬛ B"),("1/2-1/2","= D")]:
            tk.Radiobutton(flt, text=txt, variable=self.result_filter,
                        value=val, bg=PANEL_BG, fg="#AAA",
                        selectcolor=BTN_BG, activebackground=PANEL_BG,
                        font=('Segoe UI', 7), command=self._populate_game_list
                        ).pack(side='left', padx=1)
        tf = tk.Frame(p, bg=PANEL_BG)
        tf.pack(fill='both', expand=True, padx=8, pady=(0,8))
        sb = tk.Scrollbar(tf); sb.pack(side='right', fill='y')
        cols = ['Rnd','White','Black','Res','Opening','Moves']
        self.game_tree = ttk.Treeview(tf, columns=cols, show='headings',
                                    yscrollcommand=sb.set, height=28)
        sb.config(command=self.game_tree.yview)
        wcfg = {'Rnd':36,'White':100,'Black':100,'Res':46,'Opening':120,'Moves':50}
        for c in cols:
            self.game_tree.heading(c, text=c)
            self.game_tree.column(c, width=wcfg.get(c,60),
                                anchor='center' if c not in ('White','Black','Opening') else 'w')
        style = ttk.Style()
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0, rowheight=24)
        style.configure('Treeview.Heading', background=BTN_BG,
                        foreground=TEXT, font=('Segoe UI',8,'bold'))
        style.map('Treeview', background=[('selected',ACCENT)])
        self.game_tree.tag_configure('wwin',  foreground="#FFD700")
        self.game_tree.tag_configure('bwin',  foreground="#C8C8C8")
        self.game_tree.tag_configure('draw',  foreground="#00BFFF")
        self.game_tree.tag_configure('other', foreground="#888")
        self.game_tree.pack(fill='both', expand=True)
        self.game_tree.bind('<<TreeviewSelect>>', self._on_game_select)

    def _build_viewer(self, p):
        self.viewer_hdr = tk.Label(p, text="← Select a game to replay",
                                    bg=BG, fg="#555",
                                    font=('Segoe UI', 10, 'bold'),
                                    anchor='center', pady=6)
        self.viewer_hdr.pack(fill='x', padx=8)

        pl_row = tk.Frame(p, bg=BG)
        pl_row.pack(fill='x', padx=8, pady=(0,2))

        # ── PATCH: white player label + Elo badge ─────────────────────────────
        white_col = tk.Frame(pl_row, bg="#1c2a1c",
                             highlightthickness=1,
                             highlightbackground="#444400")
        white_col.pack(side='left', fill='x', expand=True, padx=(0,4))
        self.vh_white = tk.Label(white_col, text="♔  —",
                                 bg="#1c2a1c", fg="#FFD700",
                                 font=('Segoe UI', 9, 'bold'),
                                 anchor='center', pady=3)
        self.vh_white.pack(fill='x')
        self.vh_white_elo = tk.Label(white_col, text="",
                                     bg="#1c2a1c", fg="#888",
                                     font=('Consolas', 7),
                                     anchor='center', pady=1)
        self.vh_white_elo.pack(fill='x')

        tk.Label(pl_row, text="vs", bg=BG, fg="#444",
                font=('Segoe UI',8)).pack(side='left')

        # ── PATCH: black player label + Elo badge ─────────────────────────────
        black_col = tk.Frame(pl_row, bg="#1a1a2a",
                             highlightthickness=1,
                             highlightbackground="#333344")
        black_col.pack(side='right', fill='x', expand=True, padx=(4,0))
        self.vh_black = tk.Label(black_col, text="♚  —",
                                 bg="#1a1a2a", fg="#C8C8C8",
                                 font=('Segoe UI', 9, 'bold'),
                                 anchor='center', pady=3)
        self.vh_black.pack(fill='x')
        self.vh_black_elo = tk.Label(black_col, text="",
                                     bg="#1a1a2a", fg="#888",
                                     font=('Consolas', 7),
                                     anchor='center', pady=1)
        self.vh_black_elo.pack(fill='x')

        self.vh_opening_lbl = tk.Label(p, text="",
                                       bg=BG, fg="#00BFFF",
                                       font=('Segoe UI', 8, 'italic'),
                                       anchor='center', pady=2)
        self.vh_opening_lbl.pack(fill='x', padx=8)

        board_area = tk.Frame(p, bg=BG)
        board_area.pack(anchor='center', pady=(4,0))
        self.mini_board = MiniBoardWidget(board_area, show_eval_bar=True)
        self.mini_board.pack()
        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=8, pady=(6,2))
        graph_lbl_row = tk.Frame(p, bg=BG)
        graph_lbl_row.pack(fill='x', padx=8)
        tk.Label(graph_lbl_row, text="📈 Eval Graph",
                bg=BG, fg="#AAA", font=('Segoe UI',8,'bold')).pack(side='left')
        self.eval_info_lbl = tk.Label(graph_lbl_row, text="",
                                    bg=BG, fg="#555",
                                    font=('Consolas',7))
        self.eval_info_lbl.pack(side='right')
        graph_frame = tk.Frame(p, bg=BG)
        graph_frame.pack(fill='x', padx=8, pady=(2,4))
        self.eval_graph = EvalGraphWidget(graph_frame, width=560, height=88)
        self.eval_graph.pack(fill='x')
        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=8, pady=(2,2))
        move_lbl_row = tk.Frame(p, bg=BG)
        move_lbl_row.pack(fill='x', padx=8)
        tk.Label(move_lbl_row, text="📋 Move List",
                bg=BG, fg="#AAA", font=('Segoe UI',8,'bold')).pack(side='left')
        mf = tk.Frame(p, bg=LOG_BG, highlightthickness=1,
                    highlightbackground="#333")
        mf.pack(fill='both', expand=True, padx=8, pady=(0,8))
        self.move_box = scrolledtext.ScrolledText(
            mf, bg=LOG_BG, fg="#DDD", font=('Consolas',8),
            state='disabled', relief='flat', padx=4, pady=4,
            wrap='word', height=5)
        self.move_box.pack(fill='both', expand=True)
        self.move_box.tag_config('w',   foreground="#FFD700")
        self.move_box.tag_config('b',   foreground="#CCCCCC")
        self.move_box.tag_config('n',   foreground="#555")
        self.move_box.tag_config('res', foreground=ACCENT,
                                font=('Consolas',9,'bold'))
        self.move_box.tag_config('op',  foreground="#00BFFF",
                                font=('Consolas',8,'italic'))

    def _populate_game_list(self, *_):
        tree = self.game_tree
        for item in tree.get_children():
            tree.delete(item)
        self._game_map = {}

        games  = self.t.get_all_completed_games()
        flt    = self.filter_var.get().strip().lower()
        rflt   = self.result_filter.get()
        total  = len(games)
        rows   = []
        game_order = []   # parallel list to rebuild _game_map after batch insert

        for g in games:
            if rflt != "All" and g.result != rflt:
                continue
            if flt and flt not in g.white.name.lower() \
                    and flt not in g.black.name.lower() \
                    and flt not in (g.opening or '').lower():
                continue
            res_str     = g.result or "—"
            opening_str = (g.opening[:22] if g.opening else "—")
            row = [g.round_num, g.white.name, g.black.name, res_str,
                   opening_str, g.move_count]
            if g.result == '1-0':        tag = 'wwin'
            elif g.result == '0-1':      tag = 'bwin'
            elif g.result == '1/2-1/2':  tag = 'draw'
            else:                        tag = 'other'
            rows.append({"values": row, "tags": (tag,)})
            game_order.append(g)

        shown = len(rows)
        self.game_count_lbl.config(text=f"{shown} / {total} games")

        def _after_insert():
            # Re-map tree iids → game objects once all rows are in
            for iid, g in zip(tree.get_children(), game_order):
                self._game_map[iid] = g

        _batch_tree_insert(self.win, tree, rows, done_fn=_after_insert)

    def _on_game_select(self, event):
        sel = self.game_tree.selection()
        if not sel: return
        game = self._game_map.get(sel[0])
        if game:
            self._load_game(game)

    def _load_game(self, game: TournamentGame):
        self._selected_game = game
        self.viewer_hdr.config(
            text=f"Round {game.round_num}  ·  {game.result or '—'}")
        self.vh_white.config(text=f"♔  {game.white.name}")
        self.vh_black.config(text=f"♚  {game.black.name}")

        # ── PATCH: populate Elo badges ─────────────────────────────────────────
        w_elo_str = _fmt_elo(self._elo_map, game.white.name)
        b_elo_str = _fmt_elo(self._elo_map, game.black.name)
        w_elo_col = _elo_color(self._elo_map, game.white.name)
        b_elo_col = _elo_color(self._elo_map, game.black.name)
        self.vh_white_elo.config(text=w_elo_str, fg=w_elo_col)
        self.vh_black_elo.config(text=b_elo_str, fg=b_elo_col)

        if game.opening:
            self.vh_opening_lbl.config(text=f"📖  {game.opening}")
        else:
            self.vh_opening_lbl.config(text="")

        if game.move_history:
            self.mini_board.set_replay(game.move_history, game.eval_history)
        if game.eval_history:
            self.eval_graph.set_evals(game.eval_history)
            avg     = sum(game.eval_history) / len(game.eval_history)
            max_adv = max(game.eval_history)
            min_adv = min(game.eval_history)
            self.eval_info_lbl.config(
                text=f"avg {avg/100:+.2f}  max {max_adv/100:+.2f}  min {min_adv/100:+.2f}")
        else:
            self.eval_graph.set_evals([])
            self.eval_info_lbl.config(text="No eval data")

        self.move_box.config(state='normal')
        self.move_box.delete('1.0', 'end')

        if game.opening:
            self.move_box.insert('end', f"📖  {game.opening}\n\n", 'op')

        for i, (uci, san, fen) in enumerate(game.move_history):
            ply = i + 1
            if ply % 2 == 1:
                move_num = (ply+1) // 2
                self.move_box.insert('end', f"{move_num}. ", 'n')
                self.move_box.insert('end', san + " ", 'w')
            else:
                self.move_box.insert('end', san + "  ", 'b')
        self.move_box.insert('end', f"\n  ⇒ {game.result}  {game.reason}\n", 'res')
        self.move_box.see('1.0')
        self.move_box.config(state='disabled')

    def _export_pgn(self):
        games = self.t.get_all_completed_games()
        if not games:
            messagebox.showinfo("Export PGN", "No completed games to export.",
                                parent=self.win)
            return
        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="Save PGN",
            defaultextension=".pgn",
            filetypes=[("PGN files","*.pgn"),("All","*.*")],
            initialfile=f"{self.t.name.replace(' ','_')}.pgn")
        if not path: return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for g in games:
                    if g.pgn:
                        f.write(g.pgn + "\n\n")
            messagebox.showinfo("Export PGN",
                f"Exported {len(games)} games to:\n{path}", parent=self.win)
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=self.win)


# ═══════════════════════════════════════════════════════════════════════════════
#  Tournament Setup Dialog
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentSetupDialog:
    def __init__(self, root, attached_analyzer=None, attached_opening_book=None):
        self.root                  = root
        self.result                = None
        self._entries              = []
        self._attached_analyzer    = attached_analyzer
        self._attached_book        = attached_opening_book
        self._build()

    def _get_analyzer_display(self):
        a = self._attached_analyzer
        if a is None:
            return "⚠  None attached — optional override below"
        if isinstance(a, str):
            return f"✓  {os.path.basename(a)}"
        if hasattr(a, 'path') and isinstance(a.path, str):
            return f"✓  {os.path.basename(a.path)}"
        if hasattr(a, 'engine_path') and isinstance(a.engine_path, str):
            return f"✓  {os.path.basename(a.engine_path)}"
        return "✓  Analyzer attached (from GUI)"

    def _get_book_display(self):
        b = self._attached_book
        if b is None:
            return "⚠  None attached"
        if isinstance(b, str):
            return f"✓  {os.path.basename(b)}"
        if hasattr(b, 'path'):
            return f"✓  {os.path.basename(b.path)}"
        if hasattr(b, 'filename'):
            return f"✓  {os.path.basename(b.filename)}"
        if hasattr(b, '_path'):
            return f"✓  {os.path.basename(b._path)}"
        n = getattr(b, '_entries', None)
        count = f" ({len(n)} openings)" if n is not None else ""
        return f"✓  Opening book loaded{count}"

    def _build(self):
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title("🏆 New Tournament Setup")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(True, True)
        self.dialog.transient(self.root)
        self.dialog.grab_set()
        w, h = 820, 800
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        self.dialog.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.dialog.minsize(700, 640)

        hdr = tk.Frame(self.dialog, bg=BG)
        hdr.pack(fill='x', padx=20, pady=(16,0))
        tk.Label(hdr, text="🏆", bg=BG, fg=ACCENT,
                font=('Segoe UI',28)).pack(side='left', padx=(0,10))
        tf = tk.Frame(hdr, bg=BG); tf.pack(side='left')
        tk.Label(tf, text="NEW TOURNAMENT", bg=BG, fg=ACCENT,
                font=('Segoe UI',17,'bold')).pack(anchor='w')
        tk.Label(tf, text="Configure engines, format and rounds",
                bg=BG, fg="#666", font=('Segoe UI',9)).pack(anchor='w')
        tk.Frame(self.dialog, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=(10,6))

        cfg = tk.Frame(self.dialog, bg=BG)
        cfg.pack(fill='x', padx=20, pady=(0,6))

        nf = tk.Frame(cfg, bg=BG); nf.pack(side='left', padx=(0,16))
        tk.Label(nf, text="Tournament Name:", bg=BG, fg=TEXT,
                font=('Segoe UI',9)).pack(anchor='w')
        self.name_var = tk.StringVar(value=f"Tournament {datetime.now().strftime('%H:%M')}")
        tk.Entry(nf, textvariable=self.name_var, bg=LOG_BG, fg=TEXT,
                font=('Segoe UI',9), width=22, relief='flat',
                insertbackground=TEXT).pack(ipady=4)

        ff = tk.Frame(cfg, bg=BG); ff.pack(side='left', padx=(0,16))
        tk.Label(ff, text="Format:", bg=BG, fg=TEXT,
                font=('Segoe UI',9)).pack(anchor='w')
        self.fmt_var = tk.StringVar(value=Tournament.FORMAT_SWISS)
        self.fmt_combo = ttk.Combobox(ff, textvariable=self.fmt_var,
                                    values=[Tournament.FORMAT_SWISS,
                                            Tournament.FORMAT_ROUNDROBIN,
                                            Tournament.FORMAT_KNOCKOUT],
                                    state='readonly', width=14,
                                    font=('Segoe UI',9))
        self.fmt_combo.pack(ipady=3)
        self.fmt_combo.bind('<<ComboboxSelected>>', self._on_fmt_change)

        rf = tk.Frame(cfg, bg=BG); rf.pack(side='left', padx=(0,16))
        tk.Label(rf, text="Rounds (Swiss):", bg=BG, fg=TEXT,
                font=('Segoe UI',9)).pack(anchor='w')
        self.rounds_var = tk.IntVar(value=5)
        self.rounds_spin = tk.Spinbox(rf, from_=1, to=20,
                                    textvariable=self.rounds_var,
                                    width=5, bg=LOG_BG, fg=TEXT,
                                    buttonbackground=BTN_BG,
                                    font=('Consolas',9), relief='flat')
        self.rounds_spin.pack(ipady=3)

        mf = tk.Frame(cfg, bg=BG); mf.pack(side='left', padx=(0,16))
        tk.Label(mf, text="Move time (ms):", bg=BG, fg=TEXT,
                font=('Segoe UI',9)).pack(anchor='w')
        self.movetime_var = tk.IntVar(value=1000)
        tk.Spinbox(mf, from_=100, to=30000, increment=100,
                textvariable=self.movetime_var,
                width=7, bg=LOG_BG, fg=TEXT,
                buttonbackground=BTN_BG,
                font=('Consolas',9), relief='flat').pack(ipady=3)

        df = tk.Frame(cfg, bg=BG); df.pack(side='left')
        tk.Label(df, text="Delay (s):", bg=BG, fg=TEXT,
                font=('Segoe UI',9)).pack(anchor='w')
        self.delay_var = tk.DoubleVar(value=0.5)
        tk.Spinbox(df, from_=0.0, to=5.0, increment=0.1, format='%.1f',
                textvariable=self.delay_var,
                width=5, bg=LOG_BG, fg=TEXT,
                buttonbackground=BTN_BG,
                font=('Consolas',9), relief='flat').pack(ipady=3)

        row2 = tk.Frame(self.dialog, bg=BG)
        row2.pack(fill='x', padx=20, pady=(0,4))
        self.double_rr_var = tk.BooleanVar(value=False)
        self.drr_chk = tk.Checkbutton(
            row2, text="Double Round Robin",
            variable=self.double_rr_var,
            bg=BG, fg=TEXT, selectcolor=BTN_BG,
            activebackground=BG, activeforeground=TEXT,
            font=('Segoe UI',9))
        self.drr_chk.pack(side='left', padx=(0,20))

        res_frame = tk.Frame(self.dialog, bg=PANEL_BG,
                             highlightthickness=1,
                             highlightbackground="#2a3a2a")
        res_frame.pack(fill='x', padx=20, pady=(0,6))

        tk.Label(res_frame, text="🔗  Attached from GUI  (auto-loaded at startup)",
                bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI',9,'bold')).pack(anchor='w', padx=10, pady=(6,2))

        ana_row = tk.Frame(res_frame, bg=PANEL_BG)
        ana_row.pack(fill='x', padx=10, pady=(0,2))
        tk.Label(ana_row, text="🔍 Analyzer:",
                bg=PANEL_BG, fg="#888",
                font=('Segoe UI',8), width=16, anchor='w').pack(side='left')
        ana_val   = self._get_analyzer_display()
        ana_color = "#00FF80" if self._attached_analyzer else "#FF8800"
        self._ana_status_lbl = tk.Label(
            ana_row, text=ana_val,
            bg=PANEL_BG, fg=ana_color,
            font=('Consolas', 8), anchor='w')
        self._ana_status_lbl.pack(side='left', fill='x', expand=True)

        if not self._attached_analyzer:
            self._ana_override_var = tk.StringVar()
            tk.Entry(ana_row, textvariable=self._ana_override_var,
                    bg=LOG_BG, fg="#888", font=('Consolas',8),
                    width=28, relief='flat',
                    insertbackground=TEXT).pack(side='left', padx=4, ipady=2)
            def _browse_ana():
                p = filedialog.askopenfilename(
                    parent=self.dialog, title="Select Analyzer Engine",
                    filetypes=[("Executables","*.exe *.bin *"),("All","*.*")])
                if p:
                    self._ana_override_var.set(p)
                    self._ana_status_lbl.config(
                        text=f"✓  {os.path.basename(p)}", fg="#00FF80")
            tk.Button(ana_row, text="...", command=_browse_ana,
                    bg=BTN_BG, fg=TEXT, relief='flat',
                    font=('Segoe UI',8), padx=5, pady=1,
                    cursor='hand2').pack(side='left', padx=2)
        else:
            self._ana_override_var = None

        book_row = tk.Frame(res_frame, bg=PANEL_BG)
        book_row.pack(fill='x', padx=10, pady=(0,6))
        tk.Label(book_row, text="📖 Opening Book:",
                bg=PANEL_BG, fg="#888",
                font=('Segoe UI',8), width=16, anchor='w').pack(side='left')
        book_val   = self._get_book_display()
        book_color = "#00FF80" if self._attached_book else "#FF8800"
        tk.Label(book_row, text=book_val,
                bg=PANEL_BG, fg=book_color,
                font=('Consolas', 8), anchor='w').pack(side='left')

        tk.Frame(self.dialog, bg='#2a2a4a', height=1).pack(fill='x', padx=20, pady=4)

        tk.Label(self.dialog, text="Engine Participants:",
                bg=BG, fg=ACCENT, font=('Segoe UI',10,'bold')).pack(anchor='w', padx=20)
        tk.Label(self.dialog,
                text="Add at least 2 engines (name + executable path). Seed order = list order.",
                bg=BG, fg="#666", font=('Segoe UI',8)).pack(anchor='w', padx=20, pady=(0,4))

        list_outer = tk.Frame(self.dialog, bg=BG)
        list_outer.pack(fill='both', expand=True, padx=20)
        canvas_scr = tk.Canvas(list_outer, bg=BG, highlightthickness=0)
        scr_sb = tk.Scrollbar(list_outer, orient='vertical',
                            command=canvas_scr.yview)
        canvas_scr.configure(yscrollcommand=scr_sb.set)
        scr_sb.pack(side='right', fill='y')
        canvas_scr.pack(side='left', fill='both', expand=True)
        self.engine_frame = tk.Frame(canvas_scr, bg=BG)
        self._canvas_window = canvas_scr.create_window(
            (0,0), window=self.engine_frame, anchor='nw')
        def _cfg(e):
            canvas_scr.configure(scrollregion=canvas_scr.bbox('all'))
            canvas_scr.itemconfig(self._canvas_window,
                                width=canvas_scr.winfo_width())
        self.engine_frame.bind('<Configure>', _cfg)
        canvas_scr.bind('<Configure>',
            lambda e: canvas_scr.itemconfig(
                self._canvas_window, width=e.width))
        for _ in range(4):
            self._add_engine_row()

        row_btns = tk.Frame(self.dialog, bg=BG)
        row_btns.pack(fill='x', padx=20, pady=(4,0))
        tk.Button(row_btns, text="➕  Add Engine",
                command=self._add_engine_row,
                bg=BTN_BG, fg=TEXT, relief='flat',
                font=('Segoe UI',9), padx=10, pady=5,
                cursor='hand2').pack(side='left', padx=(0,8))
        tk.Button(row_btns, text="➖  Remove Last",
                command=self._remove_last,
                bg=BTN_BG, fg=TEXT, relief='flat',
                font=('Segoe UI',9), padx=10, pady=5,
                cursor='hand2').pack(side='left')

        tk.Frame(self.dialog, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=(8,0))
        foot = tk.Frame(self.dialog, bg=BG)
        foot.pack(fill='x', padx=20, pady=(6,14))
        tk.Button(foot, text="✔  Create Tournament",
                command=self._confirm,
                bg=ACCENT, fg='white', activebackground=BTN_HOV,
                relief='flat', font=('Segoe UI',11,'bold'),
                padx=16, pady=10, cursor='hand2').pack(side='left', fill='x',
                                                        expand=True, padx=(0,8))
        tk.Button(foot, text="✕  Cancel",
                command=self.dialog.destroy,
                bg=BTN_BG, fg=TEXT, relief='flat',
                font=('Segoe UI',11), padx=16, pady=10,
                cursor='hand2').pack(side='left', fill='x', expand=True)

        self._on_fmt_change()
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def _on_fmt_change(self, *_):
        fmt = self.fmt_var.get()
        if fmt == Tournament.FORMAT_SWISS:
            self.rounds_spin.config(state='normal')
            self.drr_chk.config(state='disabled')
        elif fmt == Tournament.FORMAT_ROUNDROBIN:
            self.rounds_spin.config(state='disabled')
            self.drr_chk.config(state='normal')
        else:
            self.rounds_spin.config(state='disabled')
            self.drr_chk.config(state='disabled')

    def _add_engine_row(self):
        idx = len(self._entries) + 1
        row = tk.Frame(self.engine_frame, bg=PANEL_BG,
                        highlightthickness=1, highlightbackground="#2a2a4a")
        row.pack(fill='x', pady=2, ipady=2)
        tk.Label(row, text=f"{idx}.", bg=PANEL_BG, fg="#888",
                font=('Segoe UI',9), width=3).pack(side='left', padx=(8,0))
        name_var = tk.StringVar(value=f"Engine {idx}")
        tk.Entry(row, textvariable=name_var, bg=LOG_BG, fg=TEXT,
                font=('Segoe UI',9), width=18, relief='flat',
                insertbackground=TEXT).pack(side='left', padx=4, ipady=4)
        path_var = tk.StringVar()
        tk.Entry(row, textvariable=path_var, bg=LOG_BG, fg="#AAA",
                font=('Consolas',8), relief='flat',
                insertbackground=TEXT).pack(side='left', fill='x',
                                            expand=True, padx=4, ipady=4)
        def _browse(pv=path_var, nv=name_var):
            p = filedialog.askopenfilename(
                parent=self.dialog, title="Select Engine",
                filetypes=[("Executables","*.exe *.bin *"),("All","*.*")])
            if p:
                pv.set(p)
                base = os.path.splitext(os.path.basename(p))[0]
                if nv.get().startswith("Engine "):
                    nv.set(base)
        tk.Button(row, text="...", command=_browse,
                bg=BTN_BG, fg=TEXT, relief='flat',
                font=('Segoe UI',8), padx=6, pady=2,
                cursor='hand2').pack(side='left', padx=(0,8))
        self._entries.append((name_var, path_var, row))

    def _remove_last(self):
        if len(self._entries) > 2:
            _, _, row = self._entries.pop()
            row.destroy()

    def _resolve_analyzer(self):
        a = self._attached_analyzer
        if a is not None:
            if isinstance(a, str):
                return a if os.path.isfile(a) else None
            if hasattr(a, 'path') and isinstance(a.path, str):
                return a
            return a
        if self._ana_override_var:
            p = self._ana_override_var.get().strip()
            if p and os.path.isfile(p):
                return p
        return None

    def _confirm(self):
        players = []
        seen_names = {}
        for name_var, path_var, _ in self._entries:
            name = name_var.get().strip()
            path = path_var.get().strip()
            if not name or not path: continue
            if not os.path.isfile(path):
                messagebox.showerror("Error",
                    f"Engine file not found:\n{path}", parent=self.dialog)
                return
            norm_name = normalize_engine_name(name).lower()
            if norm_name in seen_names:
                messagebox.showerror("Duplicate Engine Name",
                    f"Duplicate engine name detected:\n\"{name}\"\n\n"
                    f"Each engine must have a unique name.",
                    parent=self.dialog)
                return
            seen_names[norm_name] = True
            players.append(TournamentPlayer(name, path))

        if len(players) < 2:
            messagebox.showerror("Error",
                "Please add at least 2 valid engines.", parent=self.dialog)
            return

        fmt    = self.fmt_var.get()
        rounds = self.rounds_var.get()
        if fmt == Tournament.FORMAT_KNOCKOUT:
            rounds = math.ceil(math.log2(len(players)))

        self.result = Tournament(
            name          = self.name_var.get().strip() or "Tournament",
            fmt           = fmt,
            players       = players,
            rounds        = rounds,
            movetime_ms   = self.movetime_var.get(),
            double_rr     = self.double_rr_var.get(),
            delay         = self.delay_var.get(),
            analyzer_path = self._resolve_analyzer(),
            opening_book  = self._attached_book,
        )
        self.dialog.destroy()

    def show(self):
        self.root.wait_window(self.dialog)
        return self.result


# ═══════════════════════════════════════════════════════════════════════════════
#  Roster Dialog
# ═══════════════════════════════════════════════════════════════════════════════

class RosterDialog:
    def __init__(self, parent, tournament: Tournament, on_change=None):
        self.t         = tournament
        self.on_change = on_change
        self.win       = tk.Toplevel(parent)
        self.win.title(f"👥 Roster — {tournament.name}")
        self.win.configure(bg=BG)
        self.win.geometry("680x580")
        self.win.resizable(True, True)
        self.win.minsize(540, 460)
        self.win.transient(parent)
        self.win.grab_set()
        self._build()
        self._refresh_list()

    def _build(self):
        hdr = tk.Frame(self.win, bg=PANEL_BG,
                       highlightthickness=1, highlightbackground="#333")
        hdr.pack(fill='x')
        tk.Label(hdr, text="👥  Roster Management",
                 bg=PANEL_BG, fg=ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(side='left', padx=12, pady=8)
        tk.Label(hdr, text=self.t.name, bg=PANEL_BG, fg="#666",
                 font=('Segoe UI', 9)).pack(side='left')
        tk.Button(hdr, text="✕ Close", command=self.win.destroy,
                  bg=BTN_BG, fg=TEXT, relief='flat',
                  font=('Segoe UI', 9), padx=8, pady=4,
                  cursor='hand2').pack(side='right', padx=8, pady=6)
        tk.Frame(self.win, bg=ACCENT, height=2).pack(fill='x')

        if self.t.started and not self.t.finished:
            note_color = "#FF8800"
            note_text  = ("⚠  Tournament is in progress. You may add new players "
                          "or remove players who have not yet played any games.")
        elif self.t.finished:
            note_color = "#FF4444"
            note_text  = "🔒  Tournament is finished — roster is locked (read-only)."
        else:
            note_color = "#00FF80"
            note_text  = "✔  Tournament has not started — free to edit the roster."

        tk.Label(self.win, text=note_text,
                 bg=BG, fg=note_color,
                 font=('Segoe UI', 8, 'italic'),
                 wraplength=620, anchor='w').pack(fill='x', padx=12, pady=(6, 2))

        tk.Label(self.win, text="Current Players:",
                 bg=BG, fg=ACCENT,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=12, pady=(6, 2))

        pf = tk.Frame(self.win, bg=LOG_BG, highlightthickness=1,
                      highlightbackground="#333")
        pf.pack(fill='both', expand=True, padx=12, pady=(0, 4))

        sb = tk.Scrollbar(pf); sb.pack(side='right', fill='y')
        cols = ['#', 'Name', 'Engine Path', 'Score', 'W', 'D', 'L', 'Games', 'Status']
        self.tree = ttk.Treeview(pf, columns=cols, show='headings',
                                  yscrollcommand=sb.set, height=10)
        sb.config(command=self.tree.yview)
        wcfg = {'#': 30, 'Name': 150, 'Engine Path': 180,
                'Score': 50, 'W': 36, 'D': 36, 'L': 36, 'Games': 50, 'Status': 90}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=wcfg.get(c, 60),
                             anchor='center' if c not in ('Name', 'Engine Path') else 'w')
        style = ttk.Style()
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0, rowheight=24)
        style.configure('Treeview.Heading', background=BTN_BG,
                        foreground=TEXT, font=('Segoe UI', 8, 'bold'))
        style.map('Treeview', background=[('selected', ACCENT)])
        self.tree.tag_configure('removable', foreground="#FF6B6B")
        self.tree.tag_configure('active',    foreground=TEXT)
        self.tree.tag_configure('locked',    foreground="#555555")
        self.tree.pack(fill='both', expand=True)

        btn_row = tk.Frame(self.win, bg=BG)
        btn_row.pack(fill='x', padx=12, pady=(2, 4))
        self.remove_btn = tk.Button(
            btn_row, text="🗑  Remove Selected Player",
            command=self._remove_selected,
            bg="#5A1A1A", fg="#FF8888", relief='flat',
            font=('Segoe UI', 9), padx=10, pady=5,
            cursor='hand2')
        self.remove_btn.pack(side='left')
        tk.Label(btn_row,
                 text="  (Only players with 0 games played can be removed)",
                 bg=BG, fg="#555", font=('Segoe UI', 7)).pack(side='left', padx=4)

        tk.Frame(self.win, bg='#2a2a4a', height=1).pack(fill='x', padx=12, pady=(2, 4))
        tk.Label(self.win, text="Add New Player:",
                 bg=BG, fg=ACCENT,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=12)

        add_row = tk.Frame(self.win, bg=BG)
        add_row.pack(fill='x', padx=12, pady=(4, 2))

        tk.Label(add_row, text="Name:", bg=BG, fg=TEXT,
                 font=('Segoe UI', 8)).pack(side='left')
        self.new_name_var = tk.StringVar()
        tk.Entry(add_row, textvariable=self.new_name_var,
                 bg=LOG_BG, fg=TEXT, font=('Segoe UI', 8),
                 width=18, relief='flat',
                 insertbackground=TEXT).pack(side='left', padx=(4, 12), ipady=3)

        tk.Label(add_row, text="Engine:", bg=BG, fg=TEXT,
                 font=('Segoe UI', 8)).pack(side='left')
        self.new_path_var = tk.StringVar()
        tk.Entry(add_row, textvariable=self.new_path_var,
                 bg=LOG_BG, fg="#AAA", font=('Consolas', 7),
                 relief='flat', insertbackground=TEXT
                 ).pack(side='left', fill='x', expand=True, padx=4, ipady=3)

        def _browse():
            p = filedialog.askopenfilename(
                parent=self.win, title="Select Engine",
                filetypes=[('Executables', '*.exe *.bin *'), ('All', '*.*')])
            if p:
                self.new_path_var.set(p)
                base = os.path.splitext(os.path.basename(p))[0]
                if not self.new_name_var.get().strip():
                    self.new_name_var.set(base)

        tk.Button(add_row, text="...", command=_browse,
                  bg=BTN_BG, fg=TEXT, relief='flat',
                  font=('Segoe UI', 8), padx=6, pady=2,
                  cursor='hand2').pack(side='left', padx=(0, 8))

        add_btn_row = tk.Frame(self.win, bg=BG)
        add_btn_row.pack(fill='x', padx=12, pady=(2, 10))
        self.add_btn = tk.Button(
            add_btn_row, text="➕  Add Player to Tournament",
            command=self._add_player,
            bg=BTN_BG, fg=TEXT, relief='flat',
            font=('Segoe UI', 9), padx=12, pady=5,
            cursor='hand2')
        self.add_btn.pack(side='left')

        if self.t.finished:
            self.remove_btn.config(state='disabled')
            self.add_btn.config(state='disabled')

    def _refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, p in enumerate(self.t.player_list, 1):
            can_remove = p.games_played == 0
            path_display = p.engine_path if p.engine_path else "—"
            if len(path_display) > 38:
                path_display = "…" + path_display[-36:]
            if self.t.finished:
                tag = 'locked'
            elif can_remove:
                tag = 'removable'
            else:
                tag = 'active'
            status_str = (
                "✓ removable" if can_remove and not self.t.finished
                else "🔒 has games" if not self.t.finished
                else "🔒 locked"
            )
            self.tree.insert('', 'end', values=[
                i, p.name, path_display,
                f"{p.score:.1f}", p.wins, p.draws, p.losses,
                p.games_played, status_str
            ], tags=(tag,))

    def _remove_selected(self):
        if self.t.finished:
            messagebox.showwarning("Locked",
                "Tournament is finished — roster cannot be changed.",
                parent=self.win)
            return

        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection",
                "Please select a player to remove.", parent=self.win)
            return

        vals    = self.tree.item(sel[0])['values']
        p_name  = str(vals[1])
        p_games = int(vals[7])

        if p_games > 0:
            messagebox.showerror("Cannot Remove",
                f'"{p_name}" has already played {p_games} game(s).\n\n'
                "Only players with 0 games played can be removed.",
                parent=self.win)
            return

        confirm = messagebox.askyesno(
            "Confirm Remove",
            f'Remove "{p_name}" from the tournament?\n\n'
            "They will no longer appear in future round pairings.",
            parent=self.win)
        if not confirm:
            return

        player_obj = self.t.players.get(p_name)
        if player_obj:
            self.t.player_list.remove(player_obj)
            del self.t.players[player_obj.name]
            if player_obj in self.t._ko_active_players:
                self.t._ko_active_players.remove(player_obj)
            if player_obj in self.t._ko_pending_winners:
                self.t._ko_pending_winners.remove(player_obj)

        self._refresh_list()
        if self.on_change:
            self.on_change()

        messagebox.showinfo("Removed",
            f'"{p_name}" has been removed from the tournament.',
            parent=self.win)

    def _add_player(self):
        if self.t.finished:
            messagebox.showwarning("Locked",
                "Tournament is finished — roster cannot be changed.",
                parent=self.win)
            return

        name = self.new_name_var.get().strip()
        path = self.new_path_var.get().strip()

        if not name:
            messagebox.showerror("Missing Name",
                "Please enter a name for the engine.", parent=self.win)
            return
        if not path:
            messagebox.showerror("Missing Path",
                "Please select the engine executable.", parent=self.win)
            return
        if not os.path.isfile(path):
            messagebox.showerror("File Not Found",
                f"Engine file not found:\n{path}", parent=self.win)
            return

        norm_name = normalize_engine_name(name).lower()
        for p in self.t.player_list:
            if normalize_engine_name(p.name).lower() == norm_name:
                messagebox.showerror("Duplicate Name",
                    f'A player named "{name}" already exists in this tournament.\n\n'
                    "Each player must have a unique name.",
                    parent=self.win)
                return

        new_player = TournamentPlayer(name, path)
        new_player.seed = len(self.t.player_list) + 1
        self.t.player_list.append(new_player)
        self.t.players[new_player.name] = new_player
        if self.t.format == Tournament.FORMAT_KNOCKOUT:
            self.t._ko_active_players.append(new_player)

        self.new_name_var.set("")
        self.new_path_var.set("")

        self._refresh_list()
        if self.on_change:
            self.on_change()

        messagebox.showinfo("Player Added",
            f'"{new_player.name}" has been added to the tournament.\n\n'
            "They will be included in future round pairings.",
            parent=self.win)


# ═══════════════════════════════════════════════════════════════════════════════
#  Main Tournament Window
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentWindow:
    def __init__(self, root, tournament: Tournament, db=None, db_path=None):
        self.root         = root
        self.t            = tournament
        self.runner       = None
        self.current_game: TournamentGame = None
        self._history_win = None

        if db is not None:
            self.db = db
        elif db_path and Database is not None:
            self.db = Database(db_path)
        else:
            self.db = None

        self.db_path = db_path or (db.db_path if db is not None else None)

        # Elo map starts empty; loaded async after window opens
        self._elo_map: dict = {}

        self.win = tk.Toplevel(root)
        self.win.title(f"🏆 Tournament — {tournament.name}")
        self.win.configure(bg=BG)
        self.win.geometry("1320x880")
        self.win.resizable(True, True)
        self.win.minsize(980, 700)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._refresh_standings()

        # ── Load Elo off-thread so window opens without freezing ─────────────
        self._elo_overlay = LoadingOverlay(self.win, "Fetching Elo ratings…")
        self._elo_overlay.show()
        fetch_async(
            parent  = self.win,
            work_fn = lambda: _get_elo_map(self.db),
            done_fn = self._on_elo_loaded,
            overlay = self._elo_overlay,
        )

        has_book     = tournament.opening_book is not None
        has_analyzer = tournament.analyzer_path is not None
        has_db       = self.db is not None
        extras = []
        if has_book:     extras.append("📖 Book")
        if has_analyzer: extras.append("🔍 Analyzer")
        if has_db:       extras.append("💾 DB")
        extras_str = "  ·  " + "  ·  ".join(extras) if extras else ""
        self._status(
            f"Tournament ready: {tournament.format}  ·  "
            f"{len(tournament.player_list)} players  ·  "
            f"{tournament.rounds} rounds{extras_str}"
        )

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_toolbar()
        paned = tk.PanedWindow(self.win, orient='horizontal',
                                bg=BG, sashwidth=6, sashrelief='flat')
        paned.pack(fill='both', expand=True, padx=6, pady=(0,4))
        left  = tk.Frame(paned, bg=BG)
        right = tk.Frame(paned, bg=PANEL_BG)
        paned.add(left,  minsize=500)
        paned.add(right, minsize=380)
        self._build_left(left)
        self._build_right(right)

    def _build_toolbar(self):
        tb = tk.Frame(self.win, bg=PANEL_BG,
                    highlightthickness=1, highlightbackground="#333")
        tb.pack(fill='x', padx=6, pady=(6,0))
        tk.Label(tb, text="🏆", bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI',18)).pack(side='left', padx=(10,4))
        tk.Label(tb, text=self.t.name, bg=PANEL_BG, fg=TEXT,
                font=('Segoe UI',12,'bold')).pack(side='left')
        fmtcol = {"Swiss":"#00BFFF","Round Robin":"#7FFF00",
                "Knockout":"#FF6B6B"}.get(self.t.format, ACCENT)
        tk.Label(tb, text=f" ·  {self.t.format}",
                bg=PANEL_BG, fg=fmtcol,
                font=('Segoe UI',10,'bold')).pack(side='left')

        if self.t.opening_book:
            tk.Label(tb, text="📖", bg=PANEL_BG, fg="#00FF80",
                    font=('Segoe UI',10)).pack(side='left', padx=(6,0))
        if self.t.analyzer_path:
            tk.Label(tb, text="🔍", bg=PANEL_BG, fg="#00BFFF",
                    font=('Segoe UI',10)).pack(side='left', padx=(2,0))
        if self.db:
            tk.Label(tb, text="💾", bg=PANEL_BG, fg="#AAFFAA",
                    font=('Segoe UI',10)).pack(side='left', padx=(2,0))

        tk.Label(tb, text=f"  {len(self.t.player_list)} players  ·  "
                        f"{self.t.rounds} rounds  ·  "
                        f"{self.t.movetime_ms}ms",
                bg=PANEL_BG, fg="#555",
                font=('Segoe UI',8)).pack(side='left', padx=8)
        self.status_var = tk.StringVar(value="")
        tk.Label(tb, textvariable=self.status_var,
                bg=PANEL_BG, fg="#00FF80",
                font=('Consolas',9)).pack(side='left', padx=8)

        for txt, cmd, acc in [
            ("▶ Start",      self._start,          True),
            ("⏸ Pause",      self._pause,           False),
            ("⏹ Stop",       self._stop,            False),
            ("📜 History",   self._open_history,    False),
            ("👥 Roster",    self._open_roster,     False),
            ("✕ Close",      self._on_close,        False),
        ]:
            bg = ACCENT if acc else BTN_BG
            tk.Button(tb, text=txt, command=cmd,
                    bg=bg, fg=TEXT, activebackground=BTN_HOV,
                    relief='flat',
                    font=('Segoe UI',9,'bold' if acc else 'normal'),
                    padx=10, pady=6, cursor='hand2'
                    ).pack(side='right', padx=3, pady=4)

    def _build_left(self, p):
        self.game_hdr = tk.Label(p, text="No game running",
                                bg=BG, fg=ACCENT,
                                font=('Segoe UI',11,'bold'),
                                anchor='center', pady=6)
        self.game_hdr.pack(fill='x', padx=6, pady=(4,2))

        players_row = tk.Frame(p, bg=BG)
        players_row.pack(fill='x', padx=6, pady=(0,2))

        # ── PATCH: white side with Elo sub-label ─────────────────────────────
        white_col = tk.Frame(players_row, bg="#1c2a1c",
                             highlightthickness=1,
                             highlightbackground="#555500")
        white_col.pack(side='left', fill='x', expand=True, padx=(0,4))
        self.white_lbl = tk.Label(white_col, text="♔ —",
                                  bg="#1c2a1c", fg="#FFD700",
                                  font=('Segoe UI',10,'bold'),
                                  anchor='center', pady=4)
        self.white_lbl.pack(fill='x')
        self.white_elo_lbl = tk.Label(white_col, text="",
                                      bg="#1c2a1c", fg="#888",
                                      font=('Consolas', 7),
                                      anchor='center', pady=1)
        self.white_elo_lbl.pack(fill='x')

        tk.Label(players_row, text="vs", bg=BG, fg="#555",
                font=('Segoe UI',9)).pack(side='left')

        # ── PATCH: black side with Elo sub-label ─────────────────────────────
        black_col = tk.Frame(players_row, bg="#1a1a2a",
                             highlightthickness=1,
                             highlightbackground="#444444")
        black_col.pack(side='right', fill='x', expand=True, padx=(4,0))
        self.black_lbl = tk.Label(black_col, text="♚ —",
                                  bg="#1a1a2a", fg="#C8C8C8",
                                  font=('Segoe UI',10,'bold'),
                                  anchor='center', pady=4)
        self.black_lbl.pack(fill='x')
        self.black_elo_lbl = tk.Label(black_col, text="",
                                      bg="#1a1a2a", fg="#888",
                                      font=('Consolas', 7),
                                      anchor='center', pady=1)
        self.black_elo_lbl.pack(fill='x')

        self.opening_lbl = tk.Label(p, text="",
                                    bg=BG, fg="#00BFFF",
                                    font=('Segoe UI', 8, 'italic'),
                                    anchor='center', pady=2)
        self.opening_lbl.pack(fill='x', padx=6)

        board_outer = tk.Frame(p, bg=BG)
        board_outer.pack(anchor='center', pady=4)
        self.mini_board = MiniBoardWidget(board_outer, show_eval_bar=True)
        self.mini_board.pack()
        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=6, pady=(4,2))
        tk.Label(p, text="📈 Live Eval", bg=BG, fg="#AAA",
                font=('Segoe UI',8,'bold')).pack(anchor='w', padx=8)
        eval_graph_frame = tk.Frame(p, bg=BG)
        eval_graph_frame.pack(fill='x', padx=6, pady=(0,4))
        self.live_eval_graph = EvalGraphWidget(eval_graph_frame, width=440, height=70)
        self.live_eval_graph.pack(fill='x')
        self._live_evals = []
        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=6, pady=2)
        tk.Label(p, text="Move Log:", bg=BG, fg="#AAA",
                font=('Segoe UI',8,'bold')).pack(anchor='w', padx=8)
        mf = tk.Frame(p, bg=LOG_BG, highlightthickness=1,
                    highlightbackground="#333")
        mf.pack(fill='both', expand=True, padx=6, pady=(0,4))
        self.move_log = scrolledtext.ScrolledText(
            mf, bg=LOG_BG, fg="#DDD", font=('Consolas',8),
            state='disabled', relief='flat', padx=4, pady=4,
            wrap='word', height=6)
        self.move_log.pack(fill='both', expand=True)
        self.move_log.tag_config('w',    foreground="#FFD700")
        self.move_log.tag_config('b',    foreground="#CCCCCC")
        self.move_log.tag_config('n',    foreground="#555")
        self.move_log.tag_config('res',  foreground=ACCENT,
                                font=('Consolas',9,'bold'))
        self.move_log.tag_config('book', foreground="#00FF80",
                                font=('Consolas',8,'italic'))

    def _build_right(self, p):
        nb = ttk.Notebook(p)
        nb.pack(fill='both', expand=True, padx=4, pady=4)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background=PANEL_BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=BTN_BG, foreground=TEXT,
                        padding=[10,4], font=('Segoe UI',9))
        style.map('TNotebook.Tab',
                background=[('selected',ACCENT)],
                foreground=[('selected','white')])
        self.tab_standings = tk.Frame(nb, bg=PANEL_BG)
        self.tab_schedule  = tk.Frame(nb, bg=PANEL_BG)
        self.tab_history   = tk.Frame(nb, bg=PANEL_BG)
        self.tab_bracket   = tk.Frame(nb, bg=PANEL_BG)
        nb.add(self.tab_standings, text="🏅 Standings")
        nb.add(self.tab_schedule,  text="📋 Schedule")
        nb.add(self.tab_history,   text="📜 History")
        if self.t.format == Tournament.FORMAT_KNOCKOUT:
            nb.add(self.tab_bracket, text="🎯 Bracket")
        self._build_standings_tab(self.tab_standings)
        self._build_schedule_tab(self.tab_schedule)
        self._build_history_tab(self.tab_history)
        if self.t.format == Tournament.FORMAT_KNOCKOUT:
            self._build_bracket_tab(self.tab_bracket)

    def _build_standings_tab(self, p):
        tk.Label(p, text="📊 Current Standings",
                bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI',10,'bold')).pack(anchor='w', padx=8, pady=(8,4))
        self.round_info_lbl = tk.Label(p, text="", bg=PANEL_BG, fg="#00BFFF",
                                        font=('Segoe UI',9))
        self.round_info_lbl.pack(anchor='w', padx=8, pady=(0,4))
        tf = tk.Frame(p, bg=PANEL_BG)
        tf.pack(fill='both', expand=True, padx=8, pady=(0,8))
        sb = tk.Scrollbar(tf); sb.pack(side='right', fill='y')

        # ── PATCH: add 'Elo' column to standings ─────────────────────────────
        cols = ['#','Engine','Elo','Score','W','D','L','Pts']
        if self.t.format == Tournament.FORMAT_SWISS:
            cols += ['BH','SB']

        self.standings_tree = ttk.Treeview(
            tf, columns=cols, show='headings', yscrollcommand=sb.set)
        sb.config(command=self.standings_tree.yview)

        widths = {'#':30,'Engine':150,'Elo':60,'Score':50,'W':40,'D':40,'L':40,
                  'Pts':45,'BH':50,'SB':50}
        for c in cols:
            self.standings_tree.heading(c, text=c)
            self.standings_tree.column(
                c, width=widths.get(c,50),
                anchor='center' if c!='Engine' else 'w')

        style = ttk.Style()
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0, rowheight=26)
        style.configure('Treeview.Heading', background=BTN_BG,
                        foreground=TEXT, borderwidth=1,
                        font=('Segoe UI',8,'bold'))
        style.map('Treeview', background=[('selected',ACCENT)])
        self.standings_tree.tag_configure('gold',   foreground="#FFD700")
        self.standings_tree.tag_configure('silver', foreground="#C0C0C0")
        self.standings_tree.tag_configure('bronze', foreground="#CD7F32")
        self.standings_tree.tag_configure('normal', foreground=TEXT)
        self.standings_tree.tag_configure('active', background="#1A2A1A")

        # ── PATCH: per-tier colour tags for Elo column ───────────────────────
        for _, _, colour in RANK_TIERS:
            self.standings_tree.tag_configure(f'tier_{colour}', foreground=colour)

        self.standings_tree.pack(fill='both', expand=True)

    def _build_schedule_tab(self, p):
        tk.Label(p, text="📋 Round Schedule",
                bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI',10,'bold')).pack(anchor='w', padx=8, pady=(8,4))
        tf = tk.Frame(p, bg=PANEL_BG)
        tf.pack(fill='both', expand=True, padx=8, pady=(0,8))
        sb = tk.Scrollbar(tf); sb.pack(side='right', fill='y')
        cols = ['Rnd','#','White','Black','Result','Opening','Moves']
        self.schedule_tree = ttk.Treeview(
            tf, columns=cols, show='headings', yscrollcommand=sb.set)
        sb.config(command=self.schedule_tree.yview)
        wcfg = {'Rnd':40,'#':30,'White':130,'Black':130,
                'Result':55,'Opening':130,'Moves':50}
        for c in cols:
            self.schedule_tree.heading(c, text=c)
            self.schedule_tree.column(
                c, width=wcfg.get(c,80),
                anchor='center' if c not in ('White','Black','Opening') else 'w')
        self.schedule_tree.tag_configure('done_w',    foreground="#FFD700")
        self.schedule_tree.tag_configure('done_b',    foreground="#C8C8C8")
        self.schedule_tree.tag_configure('done_draw', foreground="#00BFFF")
        self.schedule_tree.tag_configure('running',   foreground="#00FF80",
                                        background="#001A0A")
        self.schedule_tree.tag_configure('pending',   foreground="#555")
        self.schedule_tree.pack(fill='both', expand=True)
        self.schedule_tree.bind('<Double-1>', self._on_schedule_dbl)

    def _build_history_tab(self, p):
        tk.Label(p, text="📜 Completed Games",
                bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI',10,'bold')).pack(anchor='w', padx=8, pady=(8,4))
        tk.Label(p, text="Double-click to replay  ·  Click '📜 History' for full viewer",
                bg=PANEL_BG, fg="#444",
                font=('Segoe UI',7)).pack(anchor='w', padx=8, pady=(0,4))
        tf = tk.Frame(p, bg=PANEL_BG)
        tf.pack(fill='both', expand=True, padx=8, pady=(0,8))
        sb = tk.Scrollbar(tf); sb.pack(side='right', fill='y')
        cols = ['Rnd','White','Black','Result','Opening','Moves','Time']
        self.history_tree = ttk.Treeview(
            tf, columns=cols, show='headings', yscrollcommand=sb.set)
        sb.config(command=self.history_tree.yview)
        hcfg = {'Rnd':40,'White':110,'Black':110,'Result':55,
                'Opening':130,'Moves':50,'Time':55}
        for c in cols:
            self.history_tree.heading(c, text=c)
            self.history_tree.column(
                c, width=hcfg.get(c,80),
                anchor='center' if c not in ('White','Black','Opening') else 'w')
        self.history_tree.tag_configure('wwin',  foreground="#FFD700")
        self.history_tree.tag_configure('bwin',  foreground="#C8C8C8")
        self.history_tree.tag_configure('draw',  foreground="#00BFFF")
        self.history_tree.pack(fill='both', expand=True)
        self.history_tree.bind('<Double-1>', self._on_history_dbl)

    def _build_bracket_tab(self, p):
        tk.Label(p, text="🎯 Knockout Bracket",
                bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI',10,'bold')).pack(anchor='w', padx=8, pady=(8,4))
        bframe = tk.Frame(p, bg=LOG_BG, highlightthickness=1,
                        highlightbackground="#333")
        bframe.pack(fill='both', expand=True, padx=8, pady=(0,8))
        self.bracket_canvas = tk.Canvas(bframe, bg=LOG_BG, highlightthickness=0)
        sb_x = tk.Scrollbar(bframe, orient='horizontal',
                            command=self.bracket_canvas.xview)
        sb_y = tk.Scrollbar(bframe, command=self.bracket_canvas.yview)
        self.bracket_canvas.configure(xscrollcommand=sb_x.set,
                                    yscrollcommand=sb_y.set)
        sb_x.pack(side='bottom', fill='x')
        sb_y.pack(side='right',  fill='y')
        self.bracket_canvas.pack(fill='both', expand=True)

    def _draw_bracket(self):
        c = self.bracket_canvas
        c.delete('all')
        if self.t.format != Tournament.FORMAT_KNOCKOUT:
            return
        rounds_data = self.t._ko_round_games
        if not rounds_data:
            return

        n_rounds = max(rounds_data.keys())
        col_w = 210
        pad   = 24
        row_h = 64

        for rnd in range(1, n_rounds + 1):
            games = rounds_data.get(rnd, [])
            x = pad + (rnd - 1) * col_w

            c.create_text(x + col_w // 2, pad // 2 + 4,
                          text=f"Round {rnd}  ({len(games)} games)",
                          fill=ACCENT, font=('Segoe UI', 9, 'bold'))

            for i, g in enumerate(games):
                y = pad + 20 + i * row_h * 2
                c.create_rectangle(x + 8, y + 4, x + col_w - 8, y + row_h - 4,
                                   fill=PANEL_BG, outline="#444")
                wname = g.white.name[:20]
                bname = g.black.name[:20]
                wc = "#FFD700"
                bc = "#C8C8C8"
                if g.result == '1-0':
                    wc = "#00FF80"
                elif g.result == '0-1':
                    bc = "#00FF80"
                elif g.result == '1/2-1/2':
                    wc = bc = "#00BFFF"
                c.create_text(x + 14, y + 20, text=f"♔ {wname}",
                              fill=wc, font=('Consolas', 8), anchor='w')
                c.create_text(x + 14, y + 38, text=f"♚ {bname}",
                              fill=bc, font=('Consolas', 8), anchor='w')
                res_txt = g.result or ("▶" if g.status == 'running' else "…")
                c.create_text(x + col_w - 12, y + 29, text=res_txt,
                              fill=ACCENT, font=('Consolas', 8, 'bold'), anchor='e')

                if rnd < n_rounds:
                    mid_y = y + row_h // 2
                    next_x = x + col_w - 8
                    c.create_line(next_x, mid_y, next_x + 16, mid_y,
                                  fill="#444", width=1)

        c.configure(scrollregion=c.bbox('all'))

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_schedule_dbl(self, event):
        sel = self.schedule_tree.selection()
        if not sel: return
        vals = self.schedule_tree.item(sel[0])['values']
        rnd, seq = int(vals[0]), int(vals[1])
        rnd_games = [x for x in self.t.all_games if x.round_num == rnd]
        if 0 <= seq - 1 < len(rnd_games):
            self._replay_game(rnd_games[seq - 1])

    def _on_history_dbl(self, event):
        sel = self.history_tree.selection()
        if not sel: return
        vals = self.history_tree.item(sel[0])['values']
        rnd, wname, bname = int(vals[0]), vals[1], vals[2]
        for g in self.t.get_all_completed_games():
            if g.round_num == rnd and g.white.name == wname and g.black.name == bname:
                self._replay_game(g)
                return

    def _replay_game(self, game: TournamentGame):
        if not game.move_history:
            self._status("No moves recorded for this game.")
            return
        self.game_hdr.config(
            text=f"♟ Replay: {game.white.name} vs {game.black.name}  "
                f"[Rnd {game.round_num}]  {game.result}")
        self.white_lbl.config(text=f"♔  {game.white.name}")
        self.black_lbl.config(text=f"♚  {game.black.name}")

        # ── PATCH: show Elo in replay mode too ───────────────────────────────
        self.white_elo_lbl.config(
            text=_fmt_elo(self._elo_map, game.white.name),
            fg=_elo_color(self._elo_map, game.white.name))
        self.black_elo_lbl.config(
            text=_fmt_elo(self._elo_map, game.black.name),
            fg=_elo_color(self._elo_map, game.black.name))

        if game.opening:
            self.opening_lbl.config(text=f"📖  {game.opening}")
        else:
            self.opening_lbl.config(text="")
        self.mini_board.set_replay(game.move_history, game.eval_history)
        self._live_evals = list(game.eval_history)
        self.live_eval_graph.set_evals(self._live_evals)
        self._log_game_moves(game)
        self._status(f"Replaying: {game.white.name} vs {game.black.name}")

    def _open_history(self):
        if self._history_win and self._history_win.win.winfo_exists():
            self._history_win.win.lift()
            return
        # ── PATCH: pass db so TournamentHistoryWindow can show Elo ───────────
        self._history_win = TournamentHistoryWindow(self.win, self.t, db=self.db)

    def _open_roster(self):
        RosterDialog(self.win, self.t, on_change=self._on_roster_change)

    def _on_roster_change(self):
        self._refresh_standings()
        self._refresh_schedule()
        self._refresh_history()

    # ── Runner callbacks ──────────────────────────────────────────────────────

    def _cb_game_start(self, game):
        self.current_game = game
        self.win.after(0, self._on_game_start_ui, game)

    def _on_game_start_ui(self, game):
        self.game_hdr.config(
            text=f"▶  Round {game.round_num}:  {game.white.name}  vs  {game.black.name}")
        self.white_lbl.config(text=f"♔  {game.white.name}")
        self.black_lbl.config(text=f"♚  {game.black.name}")

        # ── PATCH: show Elo when game starts ─────────────────────────────────
        self.white_elo_lbl.config(
            text=_fmt_elo(self._elo_map, game.white.name),
            fg=_elo_color(self._elo_map, game.white.name))
        self.black_elo_lbl.config(
            text=_fmt_elo(self._elo_map, game.black.name),
            fg=_elo_color(self._elo_map, game.black.name))

        self.opening_lbl.config(text="")
        self._live_evals = []
        self._current_opening_in_log = False
        self._last_opening_in_log    = None
        self.live_eval_graph.set_evals([])
        self.move_log.config(state='normal')
        self.move_log.delete('1.0', 'end')
        self.move_log.config(state='disabled')
        self._refresh_schedule()

    def _cb_board_update(self, game, board, last_move,
                         eval_cp=None, eval_mate=None, opening_name=None):
        self.win.after(0, self._on_board_update_ui, board, last_move,
                       len(board.move_history),
                       board.move_history[-1] if board.move_history else None,
                       eval_cp, eval_mate, opening_name)

    def _on_board_update_ui(self, board, last_move, ply, last_hist,
                            eval_cp, eval_mate, opening_name=None):
        self.mini_board.update_live(board, last_move, eval_cp, eval_mate)
        if last_hist:
            uci, san, fen = last_hist
            self._append_move(ply, san)
        if eval_cp is not None:
            self._live_evals.append(eval_cp)
            self.live_eval_graph.set_evals(self._live_evals)
        if opening_name:
            self.opening_lbl.config(text=f"📖  {opening_name}")
            if not getattr(self, '_current_opening_in_log', False):
                self._current_opening_in_log = True
                self._last_opening_in_log = opening_name
                self._prepend_opening_to_log(opening_name)
            elif getattr(self, '_last_opening_in_log', None) != opening_name:
                self._last_opening_in_log = opening_name
                self._update_opening_in_log(opening_name)

    def _append_move(self, ply, san):
        self.move_log.config(state='normal')
        if ply % 2 == 1:
            move_num = (ply + 1) // 2
            self.move_log.insert('end', f"{move_num}. ", 'n')
            self.move_log.insert('end', san + " ", 'w')
        else:
            self.move_log.insert('end', san + "  ", 'b')
        lines = int(self.move_log.index('end-1c').split('.')[0])
        if lines > 1000:
            self.move_log.delete('1.0', '100.0')
        self.move_log.see('end')
        self.move_log.config(state='disabled')

    def _cb_game_end(self, game):
        self.win.after(0, self._on_game_end_ui, game)

    def _on_game_end_ui(self, game):
        self.move_log.config(state='normal')
        self.move_log.insert('end', f"\n  ⇒ {game.result}  {game.reason}\n", 'res')
        self.move_log.see('end')
        self.move_log.config(state='disabled')

        self._refresh_schedule()
        self._refresh_history()
        if self.t.format == Tournament.FORMAT_KNOCKOUT:
            self.win.after(0, self._draw_bracket)
        self._save_game_db(game)
        if self._history_win and self._history_win.win.winfo_exists():
            self._history_win._populate_game_list()
        # Refresh Elo off-thread (updates standings + badges when done)
        self._refresh_elo_async()

    def _cb_round_end(self, completed_round):
        self.win.after(0, self._on_round_end_ui, completed_round)

    def _on_round_end_ui(self, rnd):
        self._status(f"✓ Round {rnd} complete")
        self._refresh_standings()
        self._refresh_schedule()
        if self.t.format == Tournament.FORMAT_KNOCKOUT:
            self.win.after(0, self._draw_bracket)

    def _cb_tournament_end(self, t):
        self.win.after(0, self._on_tournament_end_ui, t)

    def _on_tournament_end_ui(self, t):
        w = t.winner
        wname = w.name if w else "?"
        self._status(f"🏆 TOURNAMENT COMPLETE!  Winner: {wname}")
        self._refresh_standings()
        self._refresh_history()
        if t.format == Tournament.FORMAT_KNOCKOUT:
            self._draw_bracket()
        # Refresh final Elo off-thread, then show results
        fetch_async(
            parent  = self.win,
            work_fn = lambda: _get_elo_map(self.db),
            done_fn = lambda em: (
                self.__dict__.update(_elo_map=em),
                self._refresh_standings(),
                self._show_final_results(),
            ),
        )

    def _cb_status(self, msg):
        self.win.after(0, self._status, msg)

    def _status(self, msg):
        self.status_var.set(msg)

    # ── Async Elo callback ───────────────────────────────────────────────────

    def _on_elo_loaded(self, elo_map: dict):
        """Called on main thread once the background Elo fetch completes."""
        self._elo_map = elo_map
        self._refresh_standings()
        # Refresh live player badges if a game is running
        if self.current_game:
            g = self.current_game
            self.white_elo_lbl.config(
                text=_fmt_elo(self._elo_map, g.white.name),
                fg=_elo_color(self._elo_map, g.white.name))
            self.black_elo_lbl.config(
                text=_fmt_elo(self._elo_map, g.black.name),
                fg=_elo_color(self._elo_map, g.black.name))

    def _refresh_elo_async(self):
        """Re-fetch Elo ratings in background and refresh standings when done."""
        fetch_async(
            parent  = self.win,
            work_fn = lambda: _get_elo_map(self.db),
            done_fn = self._on_elo_loaded,
        )

    # ── Control buttons ───────────────────────────────────────────────────────

    def _start(self):
        if self.runner and not self.runner._stop_flag:
            self._status("Already running.")
            return
        self.runner = TournamentRunner(
            tournament        = self.t,
            on_game_start     = self._cb_game_start,
            on_board_update   = self._cb_board_update,
            on_game_end       = self._cb_game_end,
            on_round_end      = self._cb_round_end,
            on_tournament_end = self._cb_tournament_end,
            on_status         = self._cb_status,
        )
        self.runner.start()
        self._status(f"▶ Tournament started — {self.t.format}")

    def _pause(self):
        if not self.runner: return
        if self.runner._pause_flag:
            self.runner.resume(); self._status("▶ Resumed")
        else:
            self.runner.pause();  self._status("⏸ Paused")

    def _stop(self):
        if self.runner: self.runner.stop()
        self._status("⏹ Stopped")

    def _on_close(self):
        self._stop()
        self.win.destroy()

    # ── Refresh helpers ───────────────────────────────────────────────────────

    def _refresh_standings(self):
        tree = self.standings_tree
        for item in tree.get_children():
            tree.delete(item)
        standings = self.t.get_standings()
        rnd   = self.t.current_round
        total = self.t.rounds
        self.round_info_lbl.config(
            text=f"Round {rnd} / {total}  ·  "
                f"{len(self.t.get_all_completed_games())} games completed")
        cols = list(tree['columns'])

        rows = []
        for i, p in enumerate(standings, 1):
            elo_val = self._elo_map.get(p.name) or \
                      self._elo_map.get(normalize_engine_name(p.name))
            elo_str = str(elo_val) if elo_val is not None else "—"
            row = [i, p.name, elo_str, f"{p.score:.1f}",
                   p.wins, p.draws, p.losses, p.games_played]
            if 'BH' in cols:
                row += [f"{p.buchholz:.1f}", f"{p.sonneborn:.1f}"]
            if elo_val is not None:
                _, tier_col = get_tier(elo_val)
                tag = f'tier_{tier_col}'
            else:
                tag = ('gold' if i==1 else 'silver' if i==2 else
                       'bronze' if i==3 else 'normal')
            if self.current_game and p.name in (
                    self.current_game.white.name,
                    self.current_game.black.name):
                tag = 'active'
            rows.append({"values": row, "tags": (tag,)})

        _batch_tree_insert(self.win, tree, rows)

    def _refresh_schedule(self):
        tree = self.schedule_tree
        for item in tree.get_children():
            tree.delete(item)

        rows = []
        for rnd in range(1, self.t.current_round + 1):
            for seq, g in enumerate(
                    [g for g in self.t.all_games if g.round_num == rnd], 1):
                result_str  = g.result or "—"
                opening_str = (g.opening[:22] if g.opening else "")
                moves_str   = str(g.move_count) if g.status == 'done' else ""
                row = [rnd, seq, g.white.name, g.black.name,
                       result_str, opening_str, moves_str]
                if g.status == 'running':        tag = 'running'
                elif g.status == 'done':
                    if g.result == '1-0':        tag = 'done_w'
                    elif g.result == '0-1':      tag = 'done_b'
                    elif g.result == '1/2-1/2':  tag = 'done_draw'
                    else:                        tag = 'pending'
                else:                            tag = 'pending'
                rows.append({"values": row, "tags": (tag,)})

        def _after_insert():
            ch = tree.get_children()
            if ch:
                tree.see(ch[-1])

        _batch_tree_insert(self.win, tree, rows, done_fn=_after_insert)

    def _refresh_history(self):
        tree = self.history_tree
        for item in tree.get_children():
            tree.delete(item)

        rows = []
        for g in reversed(self.t.get_all_completed_games()):
            dur_s = f"{g.duration//60}m{g.duration%60}s" if g.duration else "—"
            row = [g.round_num, g.white.name, g.black.name,
                   g.result or "—",
                   (g.opening[:22] if g.opening else "—"),
                   g.move_count, dur_s]
            if g.result == '1-0':      tag = 'wwin'
            elif g.result == '0-1':    tag = 'bwin'
            else:                      tag = 'draw'
            rows.append({"values": row, "tags": (tag,)})

        _batch_tree_insert(self.win, tree, rows)

    def _prepend_opening_to_log(self, opening_name):
        self.move_log.config(state='normal')
        current = self.move_log.get('1.0', 'end-1c')
        self.move_log.delete('1.0', 'end')
        self.move_log.insert('end', f"📖  {opening_name}\n", 'book')
        if current.strip():
            self.move_log.insert('end', current)
        self.move_log.config(state='disabled')

    def _update_opening_in_log(self, opening_name):
        self.move_log.config(state='normal')
        first_line_end = self.move_log.index('1.end')
        self.move_log.delete('1.0', f'{first_line_end}+1c')
        self.move_log.insert('1.0', f"📖  {opening_name}\n", 'book')
        self.move_log.config(state='disabled')

    def _log_game_moves(self, game: TournamentGame):
        self.move_log.config(state='normal')
        self.move_log.delete('1.0', 'end')
        if game.opening:
            self.move_log.insert('end', f"📖 {game.opening}\n\n", 'book')
        for i, (uci, san, fen) in enumerate(game.move_history):
            ply = i + 1
            if ply % 2 == 1:
                move_num = (ply+1) // 2
                self.move_log.insert('end', f"{move_num}. ", 'n')
                self.move_log.insert('end', san + " ", 'w')
            else:
                self.move_log.insert('end', san + "  ", 'b')
        self.move_log.insert('end', f"\n  ⇒ {game.result}  {game.reason}\n", 'res')
        self.move_log.see('end')
        self.move_log.config(state='disabled')

    # ── Final results dialog ──────────────────────────────────────────────────

    def _show_final_results(self):
        d = tk.Toplevel(self.win)
        d.title("🏆 Tournament Results")
        d.configure(bg=BG)
        d.geometry("560x640")
        d.resizable(True, True)
        d.transient(self.win)
        d.grab_set()
        winner = self.t.winner
        tk.Label(d, text="🏆", bg=BG, font=('Segoe UI',48)).pack(pady=(16,4))
        tk.Label(d, text="TOURNAMENT COMPLETE", bg=BG, fg=ACCENT,
                font=('Segoe UI',16,'bold')).pack()
        tk.Label(d, text=self.t.name, bg=BG, fg="#AAA",
                font=('Segoe UI',10)).pack()
        tk.Frame(d, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=10)
        if winner:
            # ── PATCH: show winner's Elo in final results ─────────────────────
            w_elo     = self._elo_map.get(winner.name) or \
                        self._elo_map.get(normalize_engine_name(winner.name))
            w_elo_str = f"  ·  Elo {w_elo}" if w_elo is not None else ""
            w_tier    = ""
            w_col     = "#FFD700"
            if w_elo is not None:
                w_tier, w_col = get_tier(w_elo)
            tk.Label(d, text=f"🥇  {winner.name}", bg=BG, fg=w_col,
                    font=('Segoe UI',18,'bold')).pack(pady=(4,0))
            tk.Label(d, text=f"Score: {winner.score:.1f}  ·  "
                             f"W:{winner.wins}  D:{winner.draws}  L:{winner.losses}"
                             f"{w_elo_str}",
                    bg=BG, fg="#AAA", font=('Segoe UI',10)).pack()
            if w_elo is not None:
                tk.Label(d, text=w_tier, bg=BG, fg=w_col,
                         font=('Segoe UI', 9, 'italic')).pack(pady=(0,4))
        tk.Frame(d, bg='#2a2a4a', height=1).pack(fill='x', padx=20, pady=8)
        tk.Label(d, text="Final Standings:", bg=BG, fg="#AAA",
                font=('Segoe UI',9,'bold')).pack(anchor='w', padx=24)
        tf = tk.Frame(d, bg=LOG_BG)
        tf.pack(fill='both', expand=True, padx=20, pady=4)
        sb = tk.Scrollbar(tf); sb.pack(side='right', fill='y')

        # ── PATCH: add Elo column to final standings table ─────────────────────
        cols = ['#','Engine','Elo','Score','W','D','L']
        tree = ttk.Treeview(tf, columns=cols, show='headings',
                            yscrollcommand=sb.set, height=8)
        sb.config(command=tree.yview)
        for c, w in [('#',30),('Engine',175),('Elo',65),
                     ('Score',55),('W',40),('D',40),('L',40)]:
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor='center' if c != 'Engine' else 'w')
        tree.tag_configure('gold',   foreground="#FFD700")
        tree.tag_configure('silver', foreground="#C0C0C0")
        tree.tag_configure('bronze', foreground="#CD7F32")
        tree.tag_configure('normal', foreground=TEXT)
        for _, _, colour in RANK_TIERS:
            tree.tag_configure(f'tier_{colour}', foreground=colour)

        for i, p in enumerate(self.t.get_standings(), 1):
            p_elo     = self._elo_map.get(p.name) or \
                        self._elo_map.get(normalize_engine_name(p.name))
            elo_str   = str(p_elo) if p_elo is not None else "—"
            if p_elo is not None:
                _, tier_col = get_tier(p_elo)
                tag = f'tier_{tier_col}'
            else:
                tag = ('gold' if i==1 else 'silver' if i==2 else
                       'bronze' if i==3 else 'normal')
            tree.insert('', 'end',
                values=[i, p.name, elo_str, f"{p.score:.1f}",
                        p.wins, p.draws, p.losses],
                tags=(tag,))
        tree.pack(fill='both', expand=True)
        bf = tk.Frame(d, bg=BG)
        bf.pack(fill='x', padx=20, pady=(4,14))
        tk.Button(bf, text="📜 View Full History",
                command=lambda: [d.destroy(), self._open_history()],
                bg=BTN_BG, fg=TEXT, font=('Segoe UI',10),
                padx=16, pady=8, relief='flat', cursor='hand2'
                ).pack(side='left', padx=(0,8))
        tk.Button(bf, text="Close", command=d.destroy,
                bg=BTN_BG, fg=TEXT, font=('Segoe UI',10),
                padx=16, pady=8, relief='flat', cursor='hand2'
                ).pack(side='right')

    # ── DB persistence ────────────────────────────────────────────────────────

    def _save_game_db(self, game: TournamentGame):
        if not game.pgn:
            return

        if self.db is not None:
            game_id, t_game_id = self.db.save_tournament_game(
                tournament_id   = self.t.tournament_id,
                tournament_name = self.t.name,
                fmt             = self.t.format,
                round_num       = game.round_num,
                white_name      = game.white.name,
                black_name      = game.black.name,
                result          = game.result or '*',
                reason          = game.reason,
                pgn             = game.pgn,
                move_count      = game.move_count,
                duration_sec    = game.duration,
                opening         = game.opening or None,
            )
            if game_id:
                print(f"[DB] Saved tournament game #{game_id} "
                      f"(t_game #{t_game_id}): "
                      f"{game.white.name} vs {game.black.name} → {game.result}")
            else:
                print(f"[DB] Failed to save: "
                      f"{game.white.name} vs {game.black.name}")
            return

        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.cursor()

            cur.execute('''
                CREATE TABLE IF NOT EXISTS games (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    white_engine      TEXT    NOT NULL,
                    black_engine      TEXT    NOT NULL,
                    result            TEXT    NOT NULL,
                    reason            TEXT    NOT NULL,
                    date              TEXT    NOT NULL,
                    time              TEXT    NOT NULL,
                    pgn               TEXT    NOT NULL,
                    move_count        INTEGER,
                    duration_seconds  INTEGER,
                    source            TEXT    DEFAULT 'regular'
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS tournament_games (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id         INTEGER REFERENCES games(id) ON DELETE CASCADE,
                    tournament_id   TEXT    NOT NULL,
                    tournament_name TEXT    NOT NULL,
                    format          TEXT    NOT NULL,
                    round_num       INTEGER NOT NULL,
                    white_engine    TEXT    NOT NULL,
                    black_engine    TEXT    NOT NULL,
                    result          TEXT    NOT NULL,
                    reason          TEXT    NOT NULL,
                    pgn             TEXT    NOT NULL,
                    move_count      INTEGER,
                    duration_sec    INTEGER,
                    opening         TEXT,
                    date            TEXT    NOT NULL,
                    time            TEXT    NOT NULL
                )
            ''')
            try:
                cur.execute("ALTER TABLE games ADD COLUMN source TEXT DEFAULT 'regular'")
            except sqlite3.OperationalError:
                pass

            now      = datetime.now()
            date_str = now.strftime("%Y.%m.%d")
            time_str = now.strftime("%H:%M:%S")

            cur.execute('''
                INSERT INTO games
                    (white_engine, black_engine, result, reason,
                     date, time, pgn, move_count, duration_seconds, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                normalize_engine_name(game.white.name),
                normalize_engine_name(game.black.name),
                game.result or '*', game.reason,
                date_str, time_str,
                game.pgn, game.move_count, game.duration,
                'tournament',
            ))
            game_id = cur.lastrowid

            cur.execute('''
                INSERT INTO tournament_games
                    (game_id, tournament_id, tournament_name, format,
                     round_num, white_engine, black_engine, result, reason,
                     pgn, move_count, duration_sec, opening, date, time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                game_id,
                self.t.tournament_id, self.t.name, self.t.format, game.round_num,
                normalize_engine_name(game.white.name),
                normalize_engine_name(game.black.name),
                game.result or '*', game.reason,
                game.pgn, game.move_count, game.duration,
                game.opening or '',
                date_str, time_str,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[TournamentWindow._save_game_db fallback] {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Tournament Manager
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentManager:
    def __init__(self):
        self._entries: list[dict]          = []
        self._windows: dict[str, object]   = {}

    def register(self, tournament: Tournament,
                 win: "TournamentWindow | None" = None) -> None:
        entry = self._make_entry(tournament)
        for i, e in enumerate(self._entries):
            if e["id"] == tournament.tournament_id:
                self._entries[i] = entry
                break
        else:
            self._entries.insert(0, entry)
        if win is not None:
            self._windows[tournament.tournament_id] = win

    def update(self, tournament: Tournament) -> None:
        self.register(tournament)

    def set_window(self, tid: str, win: "TournamentWindow") -> None:
        self._windows[tid] = win

    def get_all(self) -> list[dict]:
        return list(self._entries)

    def get_window(self, tid: str) -> "TournamentWindow | None":
        return self._windows.get(tid)

    @staticmethod
    def _make_entry(t: Tournament) -> dict:
        return {
            "id":      t.tournament_id,
            "name":    t.name,
            "format":  t.format,
            "players": len(t.player_list),
            "rounds":  t.rounds,
            "obj":     t,
            "created": t.created_at.strftime("%Y-%m-%d  %H:%M"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Tournament List Window
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentListWindow:
    _COL_W = {
        '#': 34, 'Name': 200, 'Format': 100, 'Players': 62,
        'Rounds': 58, 'Games': 58, 'Status': 80,
        'Winner': 160, 'Started': 130,
    }

    def __init__(self, root, manager: TournamentManager,
                 db=None, db_path=None,
                 analyzer=None, opening_book=None):
        self.root         = root
        self.manager      = manager
        self.db           = db
        self.db_path      = db_path
        self.analyzer     = analyzer
        self.opening_book = opening_book

        self.win = tk.Toplevel(root)
        self.win.title("🏆 Tournament List")
        self.win.configure(bg=BG)
        self.win.geometry("1020x560")
        self.win.resizable(True, True)
        self.win.minsize(720, 380)

        self._id_map:    dict[str, str] = {}
        self._sort_col:  str | None     = None
        self._sort_rev:  bool           = False

        self._build()
        self._refresh()
        self._poll()

    def _build(self):
        self._build_header()
        self._build_filter_row()
        self._build_tree()
        self._build_status_bar()

    def _build_header(self):
        hdr = tk.Frame(self.win, bg=PANEL_BG,
                       highlightthickness=1, highlightbackground="#333")
        hdr.pack(fill='x')

        lf = tk.Frame(hdr, bg=PANEL_BG)
        lf.pack(side='left', padx=(12, 0), pady=8)
        tk.Label(lf, text="🏆", bg=PANEL_BG, fg=ACCENT,
                 font=('Segoe UI', 22)).pack(side='left', padx=(0, 8))
        tf = tk.Frame(lf, bg=PANEL_BG)
        tf.pack(side='left')
        tk.Label(tf, text="TOURNAMENT LIST", bg=PANEL_BG, fg=ACCENT,
                 font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        tk.Label(tf, text="All tournaments in this session",
                 bg=PANEL_BG, fg="#555",
                 font=('Segoe UI', 8)).pack(anchor='w')

        btn = dict(bg=BTN_BG, fg=TEXT, relief='flat',
                   font=('Segoe UI', 9), padx=10, pady=6, cursor='hand2')
        tk.Button(hdr, text="✕  Close",
                  command=self.win.destroy, **btn
                  ).pack(side='right', padx=(0, 8), pady=8)
        tk.Button(hdr, text="📤  Export All PGN",
                  command=self._export_all_pgn, **btn
                  ).pack(side='right', padx=0, pady=8)
        tk.Button(hdr, text="📜  Game History",
                  command=self._open_history, **btn
                  ).pack(side='right', padx=0, pady=8)
        tk.Button(hdr, text="🔍  Open Selected",
                  command=self._open_selected, **btn
                  ).pack(side='right', padx=0, pady=8)
        tk.Button(hdr, text="➕  New Tournament",
                  command=self._new_tournament,
                  bg=ACCENT, fg='white', activebackground=BTN_HOV,
                  relief='flat', font=('Segoe UI', 9, 'bold'),
                  padx=12, pady=6, cursor='hand2'
                  ).pack(side='right', padx=8, pady=8)

        tk.Frame(self.win, bg=ACCENT, height=2).pack(fill='x')

    def _build_filter_row(self):
        frow = tk.Frame(self.win, bg=BG)
        frow.pack(fill='x', padx=10, pady=(6, 2))

        tk.Label(frow, text="Search:", bg=BG, fg="#888",
                 font=('Segoe UI', 8)).pack(side='left')
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', lambda *_: self._refresh())
        tk.Entry(frow, textvariable=self._filter_var,
                 bg=LOG_BG, fg=TEXT, font=('Segoe UI', 8),
                 width=20, relief='flat',
                 insertbackground=TEXT).pack(side='left', padx=(4, 16), ipady=3)

        tk.Label(frow, text="Format:", bg=BG, fg="#888",
                 font=('Segoe UI', 8)).pack(side='left')
        self._fmt_filter = tk.StringVar(value="All")
        for val in ["All", Tournament.FORMAT_SWISS,
                    Tournament.FORMAT_ROUNDROBIN,
                    Tournament.FORMAT_KNOCKOUT]:
            tk.Radiobutton(frow, text=val, variable=self._fmt_filter,
                           value=val, bg=BG, fg="#AAA",
                           selectcolor=BTN_BG, activebackground=BG,
                           font=('Segoe UI', 8),
                           command=self._refresh
                           ).pack(side='left', padx=2)

        tk.Label(frow, text="  Status:", bg=BG, fg="#888",
                 font=('Segoe UI', 8)).pack(side='left', padx=(10, 0))
        self._status_filter = tk.StringVar(value="All")
        for val in ["All", "Running", "Finished", "Pending"]:
            tk.Radiobutton(frow, text=val, variable=self._status_filter,
                           value=val, bg=BG, fg="#AAA",
                           selectcolor=BTN_BG, activebackground=BG,
                           font=('Segoe UI', 8),
                           command=self._refresh
                           ).pack(side='left', padx=2)

    def _build_tree(self):
        tf = tk.Frame(self.win, bg=BG)
        tf.pack(fill='both', expand=True, padx=10, pady=(2, 0))

        sb = tk.Scrollbar(tf)
        sb.pack(side='right', fill='y')

        cols = list(self._COL_W.keys())
        self.tree = ttk.Treeview(tf, columns=cols, show='headings',
                                  yscrollcommand=sb.set)
        sb.config(command=self.tree.yview)

        for c in cols:
            self.tree.heading(c, text=c,
                              command=lambda _c=c: self._sort_by(_c))
            self.tree.column(c, width=self._COL_W[c],
                             anchor='center' if c not in ('Name', 'Winner') else 'w')

        style = ttk.Style()
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0, rowheight=28)
        style.configure('Treeview.Heading', background=BTN_BG,
                        foreground=TEXT, font=('Segoe UI', 8, 'bold'))
        style.map('Treeview', background=[('selected', ACCENT)])

        self.tree.tag_configure('running',  foreground="#00FF80",
                                background="#001208")
        self.tree.tag_configure('finished', foreground="#FFD700")
        self.tree.tag_configure('pending',  foreground="#555555")

        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda _: self._open_selected())
        self.tree.bind('<Return>',   lambda _: self._open_selected())

    def _build_status_bar(self):
        self._summary_var = tk.StringVar(value="")
        sf = tk.Frame(self.win, bg=PANEL_BG,
                      highlightthickness=1, highlightbackground="#222")
        sf.pack(fill='x', side='bottom')
        tk.Label(sf, textvariable=self._summary_var,
                 bg=PANEL_BG, fg="#555",
                 font=('Consolas', 8), anchor='w',
                 padx=10, pady=4).pack(side='left')

    @staticmethod
    def _t_status(t: Tournament) -> str:
        if t.finished: return "Finished"
        if t.started:  return "Running"
        return "Pending"

    @staticmethod
    def _games_played(t: Tournament) -> int:
        return len(t.get_all_completed_games())

    def _refresh(self, *_):
        """
        Step 1: render in-memory entries immediately (no freeze),
        Step 2: fetch DB rows off-thread and merge them in.
        """
        self._render_display_rows(db_rows=[])   # instant render from memory

        if self.db is not None:
            overlay = LoadingOverlay(self.win, "Loading tournament list…")
            overlay.show()
            fetch_async(
                parent  = self.win,
                work_fn = self.db.get_tournament_list,
                done_fn = lambda rows: (
                    overlay.hide(),
                    self._render_display_rows(db_rows=rows),
                ),
                overlay = overlay,
                error_fn = lambda e: (
                    overlay.hide(),
                    print(f"[TournamentListWindow] DB load error: {e}"),
                ),
            )

    def _render_display_rows(self, db_rows=None):
        """
        Populate the tree from in-memory manager entries + optional db_rows.
        Uses _batch_tree_insert to stay responsive with large history lists.
        """
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._id_map.clear()

        flt     = self._filter_var.get().strip().lower()
        fmt_flt = self._fmt_filter.get()
        st_flt  = self._status_filter.get()

        entries = self.manager.get_all()
        in_memory_ids = {e["id"] for e in entries}

        display_rows = []

        for entry in entries:
            t: Tournament = entry["obj"]
            status   = self._t_status(t)
            games    = self._games_played(t)
            winner   = t.winner.name if t.winner else "—"
            display_rows.append({
                "id":      entry["id"],
                "name":    entry["name"],
                "format":  entry["format"],
                "players": entry["players"],
                "rounds":  entry["rounds"],
                "games":   games,
                "status":  status,
                "winner":  winner,
                "created": entry["created"],
                "obj":     t,
            })

        for row in (db_rows or []):
            tid = row.get("tournament_id", "")
            if tid in in_memory_ids:
                continue
            display_rows.append({
                "id":      tid,
                "name":    row.get("tournament_name", "Unknown"),
                "format":  row.get("format", "—"),
                "players": "—",
                "rounds":  "—",
                "games":   row.get("game_count", 0),
                "status":  "Finished",
                "winner":  "—",
                "created": row.get("date", "—"),
                "obj":     None,
            })

        # Build filtered tree-row list (ids tracked in insertion order)
        tree_rows   = []
        ordered_ids = []

        for i, d in enumerate(display_rows, 1):
            status = d["status"]
            if flt and flt not in d["name"].lower()                     and flt not in d["winner"].lower():
                continue
            if fmt_flt != "All" and d["format"] != fmt_flt:
                continue
            if st_flt != "All" and status != st_flt:
                continue

            row_vals = [
                i, d["name"], d["format"], d["players"],
                d["rounds"], d["games"], status, d["winner"], d["created"],
            ]
            if   status == "Running":  tag = 'running'
            elif status == "Finished": tag = 'finished'
            else:                      tag = 'pending'

            tree_rows.append({"values": row_vals, "tags": (tag,)})
            ordered_ids.append(d["id"])

        total     = len(display_rows)
        shown     = len(tree_rows)
        finished  = sum(1 for d in display_rows if d["status"] == "Finished")
        running   = sum(1 for d in display_rows if d["status"] == "Running")
        all_games = sum(
            d["games"] if isinstance(d["games"], int) else 0
            for d in display_rows
        )

        self._summary_var.set(
            f"  Showing {shown} / {total} tournaments  ·  "
            f"{running} running  ·  {finished} finished  ·  "
            f"{all_games} total games played"
        )

        def _after_insert():
            for iid, tid in zip(self.tree.get_children(), ordered_ids):
                self._id_map[iid] = tid

        _batch_tree_insert(self.win, self.tree, tree_rows, done_fn=_after_insert)

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        rows = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try:
            rows.sort(key=lambda x: int(x[0]), reverse=self._sort_rev)
        except ValueError:
            rows.sort(key=lambda x: x[0].lower(), reverse=self._sort_rev)
        for idx, (_, k) in enumerate(rows):
            self.tree.move(k, '', idx)

    def _selected_tournament(self) -> "Tournament | None":
        sel = self.tree.selection()
        if not sel:
            return None
        tid = self._id_map.get(sel[0])
        if tid is None:
            return None
        for e in self.manager.get_all():
            if e["id"] == tid:
                return e["obj"]
        return None

    def _open_selected(self):
        t = self._selected_tournament()
        if t is None:
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo("No selection",
                                    "Please select a tournament first.",
                                    parent=self.win)
                return
            tid = self._id_map.get(sel[0])
            if tid:
                self._open_db_tournament(tid)
            return

        existing = self.manager.get_window(t.tournament_id)
        if existing is not None:
            try:
                if existing.win.winfo_exists():
                    existing.win.lift()
                    existing.win.focus_force()
                    return
            except Exception:
                pass

        win = TournamentWindow(self.root, t, db=self.db, db_path=self.db_path)
        self.manager.set_window(t.tournament_id, win)

    def _open_db_tournament(self, tournament_id: str):
        if self.db is None:
            messagebox.showinfo("No Database",
                                "No database connected — cannot load past tournament.",
                                parent=self.win)
            return

        overlay = LoadingOverlay(self.win, "Loading tournament from database…")
        overlay.show()

        def _load():
            return self.db.get_tournament_games(tournament_id=tournament_id)

        def _on_loaded(rows):
            if not rows:
                messagebox.showinfo("Empty",
                                    "No games found for this tournament in the database.",
                                    parent=self.win)
                return
            self._build_db_tournament(tournament_id, rows)

        def _on_error(exc):
            messagebox.showerror("Error", f"Failed to load tournament:\n{exc}",
                                 parent=self.win)

        fetch_async(
            parent   = self.win,
            work_fn  = _load,
            done_fn  = _on_loaded,
            overlay  = overlay,
            error_fn = _on_error,
        )
        return   # the rest of the method is extracted to _build_db_tournament

    def _build_db_tournament(self, tournament_id: str, rows: list):
        """
        Reconstruct a finished Tournament from raw DB rows.
        The heavy PGN-parsing loop runs on a background thread so the UI
        never freezes regardless of how many games are in the database.
        """
        overlay = LoadingOverlay(self.win, f"Processing {len(rows)} games…")
        overlay.show()

        def _work():
            return _parse_db_rows(tournament_id, rows)

        def _done(t):
            win = TournamentWindow(self.root, t, db=self.db, db_path=self.db_path)
            self.manager.register(t, win)
            self._refresh()
            if t.format == Tournament.FORMAT_KNOCKOUT:
                win.win.after(100, win._draw_bracket)

        fetch_async(
            parent   = self.win,
            work_fn  = _work,
            done_fn  = _done,
            overlay  = overlay,
            error_fn = lambda e: messagebox.showerror(
                "Error", f"Failed to build tournament:\n{e}", parent=self.win),
        )

    def _open_history(self):
        t = self._selected_tournament()
        if t is None:
            messagebox.showinfo("No selection",
                                "Please select a tournament first.",
                                parent=self.win)
            return
        TournamentHistoryWindow(self.win, t)

    def _new_tournament(self):
        resolved_db = self.db
        if resolved_db is None and self.db_path is not None and Database is not None:
            resolved_db = Database(self.db_path)

        setup = TournamentSetupDialog(
            self.root,
            attached_analyzer    =self.analyzer,
            attached_opening_book=self.opening_book,
        )
        t = setup.show()
        if t is None:
            return

        win = TournamentWindow(self.root, t, db=resolved_db, db_path=self.db_path)

        _orig_start = win._cb_game_start
        _orig_round = win._cb_round_end
        _orig_end   = win._cb_tournament_end

        def _p_start(game):
            self.manager.update(t)
            if self.win.winfo_exists():
                self.win.after(0, self._refresh)
            _orig_start(game)

        def _p_round(rnd):
            self.manager.update(t)
            if self.win.winfo_exists():
                self.win.after(0, self._refresh)
            _orig_round(rnd)

        def _p_end(tournament):
            self.manager.update(t)
            if self.win.winfo_exists():
                self.win.after(0, self._refresh)
            _orig_end(tournament)

        win._cb_game_start     = _p_start
        win._cb_round_end      = _p_round
        win._cb_tournament_end = _p_end

        self.manager.register(t, win)
        self._refresh()

    def _export_all_pgn(self):
        all_games = []
        for entry in self.manager.get_all():
            all_games.extend(entry["obj"].get_all_completed_games())

        if not all_games:
            messagebox.showinfo("Export PGN",
                                "No completed games found across all tournaments.",
                                parent=self.win)
            return

        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="Export All Games",
            defaultextension=".pgn",
            filetypes=[("PGN files", "*.pgn"), ("All", "*.*")],
            initialfile=f"all_tournaments_{datetime.now().strftime('%Y%m%d_%H%M')}.pgn")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for g in all_games:
                    if g.pgn:
                        f.write(g.pgn + "\n\n")
            n_t = len(self.manager.get_all())
            messagebox.showinfo(
                "Export PGN",
                f"Exported {len(all_games)} games from {n_t} tournament(s):\n{path}",
                parent=self.win)
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=self.win)

    def _poll(self):
        if not self.win.winfo_exists():
            return
        self._refresh()
        self.win.after(3000, self._poll)


# ═══════════════════════════════════════════════════════════════════════════════
#  Module-level default manager
# ═══════════════════════════════════════════════════════════════════════════════

_default_manager = TournamentManager()


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry points
# ═══════════════════════════════════════════════════════════════════════════════

def open_tournament(root, db=None, db_path=None, analyzer=None,
                    opening_book=None,
                    manager: TournamentManager = None) -> "TournamentWindow | None":
    if manager is None:
        manager = _default_manager

    resolved_db = db
    if resolved_db is None and db_path is not None and Database is not None:
        resolved_db = Database(db_path)

    setup = TournamentSetupDialog(
        root,
        attached_analyzer    =analyzer,
        attached_opening_book=opening_book,
    )
    t = setup.show()
    if t is None:
        return None

    win = TournamentWindow(root, t, db=resolved_db, db_path=db_path)

    _orig_start = win._cb_game_start
    _orig_round = win._cb_round_end
    _orig_end   = win._cb_tournament_end

    def _p_start(game):
        manager.update(t)
        _orig_start(game)

    def _p_round(rnd):
        manager.update(t)
        _orig_round(rnd)

    def _p_end(tournament):
        manager.update(t)
        _orig_end(tournament)

    win._cb_game_start     = _p_start
    win._cb_round_end      = _p_round
    win._cb_tournament_end = _p_end

    manager.register(t, win)
    return win


def open_tournament_list(root, db=None, db_path=None,
                         analyzer=None, opening_book=None,
                         manager: TournamentManager = None) -> TournamentListWindow:
    if manager is None:
        manager = _default_manager

    return TournamentListWindow(
        root,
        manager      =manager,
        db           =db,
        db_path      =db_path,
        analyzer     =analyzer,
        opening_book =opening_book,
    )