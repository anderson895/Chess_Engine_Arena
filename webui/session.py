# ═══════════════════════════════════════════════════════════
#  webui/session.py — GameSession: UI-agnostic game controller
#
#  Owns the board, engines, analyzer and game flow. The UI layer
#  subscribes to events; all blocking engine work runs through
#  nicegui.run.io_bound so the asyncio loop stays responsive.
# ═══════════════════════════════════════════════════════════

import asyncio
import os
import time
from datetime import datetime

from nicegui import run

from core.board import Board
from core.engine import UCIEngine, AnalyzerEngine
from core.opening_book import OpeningBook
from core.elo import compute_elo_ratings
from core.utils import (
    normalize_engine_name, get_tier, classify_move_quality, build_pgn,
)
from data.database import Database


# Re-exported for the UI modules that import it from here
from core.constants import TIME_CONTROLS  # noqa: E402


async def parse_opening_book(path):
    """
    Parse an openings CSV in a separate *process*: the SAN→UCI conversion
    is pure-Python CPU work that would hold the GIL and lag the whole UI
    if run in a thread. Falls back to a thread when cpu_bound fails.
    """
    try:
        book = await run.cpu_bound(OpeningBook, path)
        if book is not None:
            return book
    except Exception as e:
        print(f"[OpeningBook] cpu_bound parse failed ({e}); using a thread")
    return await run.io_bound(OpeningBook, path)


class GameSession:
    """
    Game controller shared by every part of the web UI.

    Events (subscribe with ``session.on(name, callback)``):
      board_changed()                      — position/selection changed, redraw
      status(msg)                          — status line text
      engine_log(text, tag)                — engine output line ('W'/'B'/'E')
      eval(side, ev_str, depth_str)        — per-engine eval display ('w'/'b')
      eval_bar(cp)                         — eval bar centipawns (White POV)
      quality(label)                       — move quality label ('Book', 'Best', …)
      opening(text)                        — opening display line
      game_over(result, reason, winner)    — game finished
      clock()                              — clock values changed (clock mode)
      banners()                            — names/ranks may have changed
      error(msg)                           — user-facing error
      sound(kind)                          — play a sound effect ('move',
                                             'move_opp', 'capture', 'castle',
                                             'promote', 'check', 'game_start',
                                             'game_end', 'illegal')
    """

    MODE_EVE = "engine_vs_engine"
    MODE_HVE = "human_vs_engine"

    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        self.board = Board()

        # Engines / analysis
        self.engine1 = None            # plays Black in EvE mode
        self.engine2 = None            # plays White in EvE mode / opponent in HvE
        self.analyzer: AnalyzerEngine | None = None
        self.analyzer_path: str | None = None
        self.opening_book = OpeningBook()
        self.opening_csv_path: str | None = None

        # Config
        self.play_mode    = self.MODE_EVE
        self.e1_path      = ""
        self.e2_path      = ""
        self.e1_name      = "Engine 1 (Black)"
        self.e2_name      = "Engine 2 (White)"
        self.player_name  = "Player"
        self.player_color = "white"
        self.movetime_ms  = 1000   # analyzer/tournament fallback only
        self.delay_s      = 0.5
        # Selected TIME_CONTROLS preset; base/inc are derived at start_game
        self.time_control = "blitz"
        self.base_min     = TIME_CONTROLS["blitz"][1]
        self.inc_s        = TIME_CONTROLS["blitz"][2]
        self.sound_muted  = False

        # Preset opening
        self.preset_moves: list[str] = []
        self.preset_name: str | None = None

        # Game state
        self.game_running   = False
        self.game_paused    = False
        self.game_result    = ""
        self.game_date      = ""
        self.last_move      = None
        self.selected_square = None
        self.current_opening_name = None
        self._engine_thinking = False
        self._game_task: asyncio.Task | None = None
        self._start_time = 0.0

        # Clock state
        self.wtime_ms = self.base_min * 60000
        self.btime_ms = self.base_min * 60000
        self._think_start = None   # time.time() when current search began

        # Analysis state
        self._analyzer_alock = asyncio.Lock()
        self._eval_chain = None        # (uci_after_str, cp_after)
        self.move_qualities: list[tuple[int, str, str]] = []
        self.last_quality: str | None = None
        self.eval_bar_cp = 0

        # Elo / head-to-head caches
        self._elo_cache = None
        self._h2h_cache = None         # raw (white, black, result) rows

        # Event subscribers
        self._handlers: dict[str, list] = {}
        # Async provider set by the UI: returns 'q'/'r'/'b'/'n'
        self.ask_promotion = None

    # ═══════════════════════════════════════════════════════
    #  Events
    # ═══════════════════════════════════════════════════════

    def on(self, name, callback):
        self._handlers.setdefault(name, []).append(callback)

    def clear_handlers(self):
        """Drop all subscribers (called when the page is rebuilt)."""
        self._handlers.clear()

    def _emit(self, name, *args):
        for cb in self._handlers.get(name, []):
            try:
                cb(*args)
            except Exception as e:
                print(f"[GameSession] {name} handler error: {e}")

    # ═══════════════════════════════════════════════════════
    #  Derived state for the UI
    # ═══════════════════════════════════════════════════════

    def san_pairs(self):
        """Return [(move_num, white_san, black_san|None), …] from history."""
        sans = [m[1] for m in self.board.move_history]
        return [
            (i // 2 + 1, sans[i], sans[i + 1] if i + 1 < len(sans) else None)
            for i in range(0, len(sans), 2)
        ]

    def legal_destinations(self):
        """Squares the selected piece can move to (HvE mode only)."""
        if self.play_mode != self.MODE_HVE or not self.selected_square:
            return set()
        sr, sc = self.selected_square
        return {(m[2], m[3]) for m in self.board.legal_moves()
                if m[0] == sr and m[1] == sc}

    def check_square(self):
        """The king square currently in check, or None."""
        if self.board.in_check():
            return self.board.find_king(self.board.turn)
        return None

    def player_names(self):
        """(white_name, black_name) for the current mode/colors."""
        if self.play_mode == self.MODE_HVE:
            human = (self.player_name or "Player").strip() or "Player"
            if self.player_color == "white":
                return human, self.e2_name
            return self.e2_name, human
        return self.e2_name, self.e1_name

    def material_text(self):
        wm, bm = self.board.material()
        d = wm - bm
        return "Equal" if d == 0 else (f"White +{d}" if d > 0 else f"Black +{-d}")

    def info_text(self):
        t = "Black" if self.board.turn == "b" else "White"
        return (f"Move {self.board.fullmove} | {t} to move | "
                f"50-move: {self.board.halfmove}/100 | "
                f"Plies: {len(self.board.move_history)}")

    def uses_clock(self):
        """
        True unless the preset in force is clockless (Classic).

        While a game runs this answers from the base time captured by
        start_game, not from the live selection. The Time control dropdown
        stays editable during a game, and switching it to a clocked preset
        mid-game used to turn this on against clocks start_game had left at
        zero — max(1, 0) then handed the engine a 1 ms clock and the next
        move flagged, in a game the history still recorded as Classic.
        """
        if self.game_running:
            return self.base_min is not None
        return TIME_CONTROLS.get(
            self.time_control, TIME_CONTROLS["blitz"])[1] is not None

    def clock_strings(self):
        """Formatted (white, black) clock texts, live during a search."""
        w, b = self.wtime_ms, self.btime_ms
        if self._think_start is not None and self.game_running:
            elapsed = (time.time() - self._think_start) * 1000
            if self.board.turn == "w":
                w -= elapsed
            else:
                b -= elapsed

        def fmt(ms):
            s = max(0, int(ms / 1000))
            return f"{s // 60}:{s % 60:02d}"
        return fmt(w), fmt(b)

    # ═══════════════════════════════════════════════════════
    #  Elo / ranking data (cached)
    # ═══════════════════════════════════════════════════════

    def elo_data(self):
        """Return cached (ratings, rank_map, total); recompute after saves."""
        if self._elo_cache is None:
            games = self.db.get_all_games_for_elo()
            ratings = compute_elo_ratings(games)
            ordered = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
            rank_map = {name: i + 1 for i, (name, _) in enumerate(ordered)}
            self._elo_cache = (ratings, rank_map, len(ordered))
        return self._elo_cache

    def rank_line(self, raw_name):
        """'#3/12  🏆 GM  •  2410 Elo' text + color for a player banner."""
        ratings, rank_map, total = self.elo_data()
        key = normalize_engine_name(raw_name)
        elo = ratings.get(key)
        if elo is None:
            return "Unranked", "#555"
        tier_lbl, tier_col = get_tier(elo)
        return f"#{rank_map.get(key, '?')}/{total}  {tier_lbl}  •  {elo} Elo", tier_col

    def invalidate_stats_caches(self):
        """Force Elo and head-to-head recomputation after new games land."""
        self._elo_cache = None
        self._h2h_cache = None

    def head_to_head(self, name_a, name_b):
        """(wins_a, draws, wins_b) across all saved games of this pairing."""
        a = normalize_engine_name(name_a)
        b = normalize_engine_name(name_b)
        if not a or not b or a == b:
            return 0, 0, 0
        if self._h2h_cache is None:
            self._h2h_cache = self.db.get_all_games_for_elo()
        wins_a = wins_b = draws = 0
        for white, black, result in self._h2h_cache:
            white = normalize_engine_name(white)
            black = normalize_engine_name(black)
            if {white, black} != {a, b}:
                continue
            if result == "1/2-1/2":
                draws += 1
            elif result == "1-0":
                wins_a, wins_b = ((wins_a + 1, wins_b) if white == a
                                  else (wins_a, wins_b + 1))
            elif result == "0-1":
                wins_a, wins_b = ((wins_a + 1, wins_b) if black == a
                                  else (wins_a, wins_b + 1))
        return wins_a, draws, wins_b

    # ═══════════════════════════════════════════════════════
    #  Opening book / analyzer management
    # ═══════════════════════════════════════════════════════

    async def load_opening_csv(self, path):
        book = await parse_opening_book(path)
        if not book or not book.loaded:
            self._emit("error", f"No valid openings found in:\n{path}")
            return False
        self.opening_book = book
        self.opening_csv_path = path
        self._refresh_opening_display(reset=True)
        return True

    async def load_analyzer(self, path):
        if self.analyzer:
            old = self.analyzer
            self.analyzer = None
            await run.io_bound(old.stop)
        try:
            eng = AnalyzerEngine(path, "Analyzer")
            await run.io_bound(eng.start)
            ok = await run.io_bound(eng.probe)
            if not ok:
                raise RuntimeError("engine died on first search "
                                   "(missing NNUE network file?)")
            self.analyzer = eng
            self.analyzer_path = path
            return True
        except Exception as e:
            self._emit("error", f"Could not start analyzer:\n{e}")
            return False

    def _refresh_opening_display(self, reset=False):
        if reset:
            self.current_opening_name = None
            if self.opening_book.loaded:
                self._emit("opening",
                           f"{len(self.opening_book._entries)} openings ready")
            else:
                self._emit("opening", "No openings CSV loaded")
            return
        if not self.opening_book.loaded:
            return
        eco, name = self.opening_book.lookup(self.board.uci_moves_list())
        if name:
            self.current_opening_name = name
            self._emit("opening", f"{eco}  ·  {name}" if eco else name)
        elif self.current_opening_name:
            self._emit("opening", self.current_opening_name)

    # ═══════════════════════════════════════════════════════
    #  Game control
    # ═══════════════════════════════════════════════════════

    async def start_game(self):
        if self.game_running:
            self._emit("error", "Stop the current game first.")
            return

        # Validate config
        if self.play_mode == self.MODE_HVE:
            if not (self.player_name or "").strip():
                self._emit("error", "Please enter your name.")
                return
            paths = [(2, self.e2_path.strip())]
        else:
            paths = [(1, self.e1_path.strip()), (2, self.e2_path.strip())]
        for n, path in paths:
            if not path:
                self._emit("error", f"Please select engine {n}.")
                return
            if not os.path.isfile(path):
                self._emit("error", f"Engine {n} not found:\n{path}")
                return

        # Reset state
        self.board.reset()
        self.last_move = None
        self.selected_square = None
        self.game_result = "*"
        self.move_qualities = []
        self.last_quality = None
        self._eval_chain = None
        self.eval_bar_cp = 0
        self._engine_thinking = False
        self._elo_cache = None           # tournaments may have added games
        self.current_opening_name = None

        # Reset clocks from the selected time-control preset
        self._think_start = None
        self._game_tc_label, self.base_min, self.inc_s = TIME_CONTROLS.get(
            self.time_control, TIME_CONTROLS["blitz"])
        self.wtime_ms = self.btime_ms = (self.base_min or 0) * 60000
        self._emit("clock")

        # Apply preset opening
        if self.preset_moves:
            self.current_opening_name = self.preset_name
            for uci in self.preset_moves:
                try:
                    self.board.apply_uci(uci)
                except Exception as e:
                    print(f"[Preset] failed to apply {uci}: {e}")
                    self.board.reset()
                    self.current_opening_name = None
                    break
            if self.board.move_history:
                self.last_move = self.board.move_history[-1][0]
        if self.current_opening_name:
            self._emit("opening", self.current_opening_name)
        else:
            self._refresh_opening_display(reset=True)

        self._emit("eval_bar", 0)
        self._emit("quality", None)
        self._emit("board_changed")
        self.game_date = datetime.now().strftime("%Y.%m.%d")
        self._start_time = time.time()
        self._emit("status", "Loading engine(s)…")

        # Load engines off-loop
        ok = await self._load_engines()
        if not ok:
            return

        self.game_running = True
        self.game_paused = False
        self._emit("banners")
        self._emit("sound", "game_start")

        if self.play_mode == self.MODE_HVE:
            base = self.e2_name.split("(")[0].strip()
            color_label = "Black" if self.player_color == "white" else "White"
            self.e2_name = f"{base} ({color_label})"
            self._emit("banners")
            human_to_move = (
                (self.player_color == "white") == (self.board.turn == "w"))
            if human_to_move:
                self._emit("status", "Your turn — click a piece to move")
            else:
                self._game_task = asyncio.create_task(self._engine_turn())
        else:
            self._game_task = asyncio.create_task(self._game_loop())

    async def _load_engines(self):
        """Start the engine subprocess(es). Returns True on success."""
        wanted = ([(2, self.e2_path, self.e2_name)]
                  if self.play_mode == self.MODE_HVE
                  else [(1, self.e1_path, self.e1_name),
                        (2, self.e2_path, self.e2_name)])
        errs = []
        for n, path, name in wanted:
            try:
                self._emit("status", f"Loading {name}…")
                eng = UCIEngine(path.strip(), name)
                await run.io_bound(eng.start)
                if n == 1:
                    self.engine1 = eng
                else:
                    self.engine2 = eng
                self._emit("engine_log", f"✓ {name} ready",
                           "B" if n == 1 else "W")
            except Exception as e:
                errs.append(f"Engine {n}: {e}")
        if errs:
            await self.kill_engines()
            self._emit("error", "\n".join(errs))
            self._emit("status", "Engine load failed")
            return False
        return True

    def toggle_pause(self):
        if not self.game_running:
            return
        self.game_paused = not self.game_paused
        self._emit("status", "PAUSED" if self.game_paused else "Resuming…")

    async def stop_game(self, result, reason):
        """Finish a game that the user stopped manually."""
        self.game_running = False
        self.game_paused = False
        self._engine_thinking = False
        self._think_start = None
        asyncio.create_task(self.kill_engines())

        if self.board.move_history or result != "*":
            await self._save_game(result, reason)

        if result == "*":
            self._emit("status", "Game aborted — no result recorded")
        else:
            self.game_result = result
            white, black = self.player_names()
            winner = (white if result == "1-0"
                      else (black if result == "0-1" else None))
            clean = normalize_engine_name(winner) if winner else None
            self._emit("status",
                       f"Stopped — {clean} wins ({result})" if clean
                       else f"Stopped — {result}  ({reason})")
            self.swap_colors()      # reversed colors for the rematch
            self._emit("game_over", result, reason, winner)
        self._emit("banners")

    async def new_game(self):
        self.game_running = False
        self.game_paused = False
        self._engine_thinking = False
        self._think_start = None
        asyncio.create_task(self.kill_engines())
        self.board.reset()
        self.last_move = None
        self.selected_square = None
        self.game_result = ""
        self.move_qualities = []
        self.last_quality = None
        self._eval_chain = None
        self.eval_bar_cp = 0
        self._refresh_opening_display(reset=True)
        self._emit("eval_bar", 0)
        self._emit("quality", None)
        self._emit("board_changed")
        self._emit("status", "New game — load engines and press START")

    def swap_colors(self):
        """Swap sides for the next game (between games only).

        EvE: engine1/engine2 exchange colors.  HvE: the human's color flips.
        """
        if self.game_running:
            return False
        if self.play_mode == self.MODE_HVE:
            self.player_color = ("black" if self.player_color == "white"
                                 else "white")
            self._emit("engine_log",
                       f"⇄ Colors swapped — you now play "
                       f"{self.player_color.capitalize()}", "E")
            self._emit("banners")
            return True
        self.e1_path, self.e2_path = self.e2_path, self.e1_path
        old_black = normalize_engine_name(self.e1_name) or "Engine 1"
        old_white = normalize_engine_name(self.e2_name) or "Engine 2"
        self.e1_name = f"{old_white} (Black)"
        self.e2_name = f"{old_black} (White)"
        self._emit("engine_log",
                   f"⇄ Colors swapped — {old_white} is now Black, "
                   f"{old_black} is now White", "E")
        self._emit("banners")
        return True

    async def kill_engines(self):
        for eng in (self.engine1, self.engine2):
            if eng:
                try:
                    await run.io_bound(eng.stop)
                except Exception:
                    pass
        self.engine1 = self.engine2 = None

    async def shutdown(self):
        """Full teardown at app exit."""
        self.game_running = False
        await self.kill_engines()
        if self.analyzer:
            try:
                await run.io_bound(self.analyzer.stop)
            except Exception:
                pass
            self.analyzer = None

    def export_pgn_text(self):
        """Current game as PGN, or None when no moves exist."""
        if not self.board.move_history:
            return None
        white, black = self.player_names()
        return build_pgn(
            white, black, self.board.move_history, self.game_result or "*",
            self.game_date or datetime.now().strftime("%Y.%m.%d"),
            opening_name=self.current_opening_name)

    # ═══════════════════════════════════════════════════════
    #  Game flow — engine vs engine
    # ═══════════════════════════════════════════════════════

    async def _game_loop(self):
        try:
            while self.game_running:
                while self.game_paused and self.game_running:
                    await asyncio.sleep(0.1)
                if not self.game_running:
                    return

                over, result, reason, winner_color = self.board.game_result()
                if over:
                    await self._finish(result, reason, winner_color)
                    return

                is_b = (self.board.turn == "b")
                engine = self.engine1 if is_b else self.engine2
                name = self.e1_name if is_b else self.e2_name
                if not await self._play_engine_move(engine, name, is_b):
                    return
                await asyncio.sleep(max(0.05, self.delay_s))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[GameSession] game loop error: {e}")
            self._emit("status", f"Game loop error: {e}")

    async def _play_engine_move(self, engine, name, is_black):
        """Ask *engine* for one move and apply it. Returns False if the game ended."""
        side = "b" if is_black else "w"
        tag = "B" if is_black else "W"
        self._emit("status", f"{name} thinking…")

        forfeit_result = "0-1" if not is_black else "1-0"

        if not engine or not engine.alive:
            await self._finish(forfeit_result, f"{name}'s engine process died",
                               "black" if not is_black else "white")
            return False

        moves_before = self.board.uci_moves_str()
        was_white = not is_black

        # Real-clock mode: hand the engine both clocks and let it manage
        # its own thinking time; we account for what it actually spent.
        clock = None
        if self.uses_clock():
            inc = int(self.inc_s * 1000)
            clock = {"wtime": max(1, int(self.wtime_ms)),
                     "btime": max(1, int(self.btime_ms)),
                     "winc": inc, "binc": inc}
            self._think_start = time.time()
            self._emit("clock")

        try:
            uci = await run.io_bound(
                engine.get_best_move, moves_before, self.movetime_ms,
                None, clock)
        except Exception as e:
            self._emit("engine_log", f"[ERR] {e}", tag)
            uci = None

        if clock:
            # stop_game/new_game may have nulled _think_start mid-search
            think_start = self._think_start
            elapsed_ms = ((time.time() - think_start) * 1000
                          if think_start is not None else 0.0)
            self._think_start = None

        if not self.game_running:
            return False

        if clock:
            remaining = (self.btime_ms if is_black else self.wtime_ms) \
                - elapsed_ms
            if remaining <= 0:
                self._emit("clock")
                # FIDE 6.9: a flag fall is only a loss if the opponent
                # could still mate. Against a bare king — or a lone
                # bishop or knight — the game is drawn instead.
                rival = "b" if not is_black else "w"
                if self.board.can_mate(rival):
                    await self._finish(forfeit_result,
                                       f"{name} lost on time",
                                       "black" if not is_black else "white")
                else:
                    # Phrased like the other draw reasons, which never name
                    # an engine — the result column already says 1/2-1/2
                    await self._finish(
                        "1/2-1/2",
                        "Draw by timeout vs insufficient material", None)
                return False
            remaining += self.inc_s * 1000
            if is_black:
                self.btime_ms = remaining
            else:
                self.wtime_ms = remaining
            self._emit("clock")
        if not uci:
            await self._finish(forfeit_result, f"{name} returned no move",
                               "black" if not is_black else "white")
            return False

        self._emit("engine_log", f"[{tag}] bestmove {uci}", tag)
        try:
            san, _cap = self.board.apply_uci(uci)
        except ValueError as e:
            self._emit("engine_log", f"[ILLEGAL] {e}", "E")
            await self._finish(forfeit_result, f"Illegal move by {name}: {uci}",
                               "black" if not is_black else "white")
            return False

        self.last_move = uci
        self._show_engine_eval(engine, side)
        self._after_move(moves_before, was_white, san)

        over, result, reason, winner_color = self.board.game_result()
        if over:
            await self._finish(result, reason, winner_color)
            return False
        return True

    # ═══════════════════════════════════════════════════════
    #  Game flow — human vs engine
    # ═══════════════════════════════════════════════════════

    async def click_square(self, br, bc):
        """Handle a click on board square (row, col) in board coordinates."""
        if (self.play_mode != self.MODE_HVE or not self.game_running
                or self._engine_thinking):
            return
        human_white = (self.player_color == "white")
        if human_white != (self.board.turn == "w"):
            return

        piece = self.board.get(br, bc)
        is_own = (piece and piece != "." and
                  (piece.isupper() if human_white else piece.islower()))

        if self.selected_square is None:
            if is_own:
                self.selected_square = (br, bc)
                self._emit("board_changed")
            return

        fr, fc = self.selected_square
        if (br, bc) == (fr, fc):
            self.selected_square = None
            self._emit("board_changed")
            return
        if is_own:
            self.selected_square = (br, bc)
            self._emit("board_changed")
            return

        matching = [m for m in self.board.legal_moves()
                    if m[0] == fr and m[1] == fc and m[2] == br and m[3] == bc]
        self.selected_square = None
        if not matching:
            self._emit("board_changed")
            return

        if any(m[4] for m in matching):
            promo = "q"
            if self.ask_promotion:
                promo = (await self.ask_promotion(
                    "w" if human_white else "b")) or "q"
            uci = (f"{chr(ord('a') + fc)}{8 - fr}"
                   f"{chr(ord('a') + bc)}{8 - br}{promo}")
        else:
            uci = f"{chr(ord('a') + fc)}{8 - fr}{chr(ord('a') + bc)}{8 - br}"

        moves_before = self.board.uci_moves_str()
        was_white = (self.board.turn == "w")
        try:
            san, _cap = self.board.apply_uci(uci)
        except ValueError as e:
            self._emit("board_changed")
            self._emit("sound", "illegal")
            self._emit("error", f"Invalid move: {e}")
            return

        self.last_move = uci
        self._after_move(moves_before, was_white, san)

        over, result, reason, winner_color = self.board.game_result()
        if over:
            await self._finish(result, reason, winner_color)
            return
        self._game_task = asyncio.create_task(self._engine_turn())

    async def _engine_turn(self):
        """The engine's reply in human-vs-engine mode."""
        self._engine_thinking = True
        try:
            while self.game_paused and self.game_running:
                await asyncio.sleep(0.1)
            if not self.game_running:
                return
            # Breathe between the player's move and the reply — a fast engine
            # would otherwise answer in the same UI batch, so both move sounds
            # overlap into one and the board flashes two moves at once.
            await asyncio.sleep(max(0.3, self.delay_s))
            if not self.game_running:
                return
            is_black = (self.player_color == "white")
            if not await self._play_engine_move(self.engine2, self.e2_name, is_black):
                return
            msg = ("CHECK! Your turn — you must get out of check!"
                   if self.board.in_check()
                   else "Your turn — click a piece to move")
            self._emit("status", msg)
        except asyncio.CancelledError:
            pass
        finally:
            self._engine_thinking = False

    # ═══════════════════════════════════════════════════════
    #  Shared post-move / end-game plumbing
    # ═══════════════════════════════════════════════════════

    def _sound_for_san(self, san, was_white):
        """Sound effect kind for a SAN move (priority: check first).

        Plain moves use chess.com's two distinct sounds: 'move' (move-self)
        for White / the human player, 'move_opp' (move-opponent) otherwise —
        so both sides are clearly audible as different sounds.
        """
        if "+" in san or "#" in san:
            return "check"
        if "=" in san:
            return "promote"
        if san.startswith("O-O"):
            return "castle"
        if "x" in san:
            return "capture"
        if self.play_mode == self.MODE_HVE:
            human_moved = (self.player_color == "white") == was_white
            return "move" if human_moved else "move_opp"
        return "move" if was_white else "move_opp"

    def _after_move(self, moves_before, was_white, san):
        self._emit("sound", self._sound_for_san(san, was_white))
        self._emit("board_changed")
        self._refresh_opening_display()
        ply = len(self.board.move_history)
        asyncio.create_task(
            self._analyze_quality(moves_before, self.board.uci_moves_str(),
                                  was_white, san, ply))

    def _show_engine_eval(self, engine, side):
        info = engine.last_info if engine else {}
        sc = info.get("score")
        st = info.get("score_type", "cp")
        dp = info.get("depth")
        if sc is None:
            ev = "—"
        elif st == "mate":
            ev = f"M{sc}"
        else:
            cp = sc if side == "w" else -sc
            ev = f"{cp / 100:+.2f}"
        self._emit("eval", side, ev, str(dp) if dp else "—")
        if sc is not None:
            cp_bar = (30000 if sc > 0 else -30000) if st == "mate" else sc
            if side == "b":
                cp_bar = -cp_bar
            self.eval_bar_cp = cp_bar
            self._emit("eval_bar", cp_bar)

    async def _finish(self, result, reason, winner_color):
        """Game ended on the board — persist and notify."""
        self.game_running = False
        self.game_result = result
        self._engine_thinking = False
        self._think_start = None
        asyncio.create_task(self.kill_engines())

        white, black = self.player_names()
        winner = (white if winner_color == "white"
                  else (black if winner_color == "black" else None))

        await self._save_game(result, reason)

        msg = (f"{normalize_engine_name(winner)} wins by {reason}"
               if winner else f"{result} — {reason}")
        self._emit("status", msg)
        self.swap_colors()          # reversed colors for the rematch
        self._emit("banners")
        self._emit("sound", "game_end")
        self._emit("game_over", result, reason, winner)

    async def _save_game(self, result, reason):
        duration = int(time.time() - self._start_time) if self._start_time else 0
        white, black = self.player_names()
        pgn = build_pgn(
            white, black, self.board.move_history, result,
            self.game_date or datetime.now().strftime("%Y.%m.%d"),
            opening_name=self.current_opening_name)
        await run.io_bound(
            self.db.save_game, white, black, result, reason, pgn,
            len(self.board.move_history), duration, 'regular',
            getattr(self, "_game_tc_label", ""),
            self.current_opening_name or '')
        self.invalidate_stats_caches()

    # ═══════════════════════════════════════════════════════
    #  Move-quality analysis
    # ═══════════════════════════════════════════════════════

    async def _analyze_quality(self, uci_before, uci_after, was_white, san, ply):
        # Opening theory → label as Book, skip engine analysis
        if (self.opening_book.loaded and
                self.opening_book.in_book(uci_after.split())):
            self.last_quality = "Book"
            self.move_qualities.append((ply, san, "Book"))
            self._emit("quality", "Book")
            return

        if not self.analyzer or not self.analyzer.alive:
            return
        async with self._analyzer_alock:
            chain = self._eval_chain
            if chain and chain[0] == uci_before and chain[1] is not None:
                cp_before = chain[1]
            else:
                # io_bound returns None (not a tuple) when the app shuts down
                res = await run.io_bound(
                    self.analyzer.eval_position, uci_before, 200)
                cp_before = res[0] if res else None
            res = await run.io_bound(
                self.analyzer.eval_position, uci_after, 200)
            cp_after = res[0] if res else None
            self._eval_chain = (uci_after, cp_after)
        if cp_before is None or cp_after is None:
            return
        quality = classify_move_quality(cp_before, cp_after, was_white)
        self.last_quality = quality
        self.move_qualities.append((ply, san, quality))
        self.eval_bar_cp = cp_after
        self._emit("eval_bar", cp_after)
        self._emit("quality", quality)
