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
from collections import namedtuple
from datetime import datetime

from nicegui import run

from core.board import Board
from core.engine import UCIEngine, AnalyzerEngine
from core.opening_book import OpeningBook
from core.elo import (
    compute_elo_by_tc, tally_by_tc, tc_bucket, MIN_RATED_GAMES,
)
from core.review import GameAnalyst
from core.utils import (
    normalize_engine_name, get_tier, build_pgn,
)
from data.database import Database

# Search time per position for grading moves while a game is played. The
# review screen analyses again, deeper; this keeps up with fast games.
LIVE_ANALYSIS_MS = 250

# A review engine nobody has used for this long is shut down
REVIEW_ENGINE_IDLE_S = 60


# Re-exported for the UI modules that import it from here
from core.constants import TIME_CONTROLS  # noqa: E402


# Everything the UI needs about one time control's ratings.
#   ratings  — {engine: elo} for engines with enough games to quote
#   rank_map — {engine: rank} over those, so #n/total means something
#   total    — how many are in that ranking
#   tally    — {engine: {games, wins, draws, losses}} for everyone
#   fitted   — {engine: (elo, margin)} for everyone, provisional included
EloBucket = namedtuple("EloBucket",
                       "ratings rank_map total tally fitted")

# A control nothing has been played at, so callers unpack the same shape
EMPTY_BUCKET = EloBucket({}, {}, 0, {}, {})


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


def sound_for_san(san, near_side=True):
    """
    Sound effect kind for a SAN move. Check wins over everything else.

    Plain moves use chess.com's two distinct sounds: 'move' (move-self) for
    the side the board is oriented to, 'move_opp' for the other — so the two
    sides stay audibly apart. Shared with the tournament window, which has
    no human and treats White as the near side.
    """
    if "+" in san or "#" in san:
        return "check"
    if "=" in san:
        return "promote"
    if san.startswith("O-O"):
        return "castle"
    if "x" in san:
        return "capture"
    return "move" if near_side else "move_opp"


class GameSession:
    """
    Game controller shared by every part of the web UI.

    Events (subscribe with ``session.on(name, callback)``):
      board_changed()                      — position/selection changed, redraw
      status(msg)                          — status line text
      engine_log(text, tag)                — engine output line ('W'/'B'/'E')
      eval(side, ev_str, depth_str)        — per-engine eval display ('w'/'b')
      eval_bar(cp)                         — eval bar centipawns (White POV)
      move_review(review)                  — core.review.MoveReview of the last
                                             graded move, or None to clear
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
    MODE_HVH = "human_vs_human"     # two players at one board, no engine

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
        self.white_player = "White"      # the two names in 2-player mode
        self.black_player = "Black"
        self.movetime_ms  = 1000   # analyzer/tournament fallback only
        self.delay_s      = 0.5
        # Selected TIME_CONTROLS preset; base/inc are derived at start_game.
        # Classic by default because it is where the games are: ratings are
        # kept per control now, and opening on one with a handful of games
        # would show a field of Unranked engines that have played hundreds.
        self.time_control = "classic"
        self.base_min     = TIME_CONTROLS["classic"][1]
        self.inc_s        = TIME_CONTROLS["classic"][2]
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

        # Clock state. base_min is None for Classic, which is clockless —
        # the same "or 0" start_game uses, and required now that Classic
        # is the default preset.
        self.wtime_ms = (self.base_min or 0) * 60000
        self.btime_ms = (self.base_min or 0) * 60000
        self._think_start = None   # time.time() when current search began

        # Takebacks: the clocks after every ply (index = plies played), the
        # preset opening moves (never taken back) and the opening name the
        # game started under
        self._clock_log: list[tuple[float, float]] = []
        self._preset_plies = 0
        self._start_opening_name = None

        # Analysis state. The analyst follows the game being played: it
        # names the opening as positions arrive and grades each move.
        self._analyzer_alock = asyncio.Lock()
        self.analyst = GameAnalyst(self.opening_book, self._analyse_live)
        self.eval_bar_cp = 0
        # The game that just ended, kept for "Game Review" after the colours
        # have been swapped for the rematch
        self.last_game = None

        # Dedicated engine for the review screen, started on demand
        self._review_engine: AnalyzerEngine | None = None
        self._review_users = 0
        self._review_idle: asyncio.TimerHandle | None = None

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

    @property
    def preset_plies(self):
        """How many of the game's first moves came from the chosen opening."""
        return self._preset_plies

    def human_to_move(self):
        """True when a person, not an engine, plays the side to move."""
        if self.play_mode == self.MODE_HVH:
            return True
        if self.play_mode == self.MODE_HVE:
            return (self.player_color == "white") == (self.board.turn == "w")
        return False

    def legal_destinations(self):
        """Squares the selected piece can move to (a person's turn only)."""
        if not self.human_to_move() or not self.selected_square:
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
        if self.play_mode == self.MODE_HVH:
            return ((self.white_player or "White").strip() or "White",
                    (self.black_player or "Black").strip() or "Black")
        if self.play_mode == self.MODE_HVE:
            human = (self.player_name or "Player").strip() or "Player"
            if self.player_color == "white":
                return human, self.e2_name
            return self.e2_name, human
        return self.e2_name, self.e1_name

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

    def clock_ms(self):
        """
        Live (white, black) clock values in ms, counting the search in flight.

        The stored values only move when a search returns, so between moves
        the thinking side's clock is stale by however long it has been
        thinking. Anything that reads a clock wants that subtracted.
        """
        w, b = self.wtime_ms, self.btime_ms
        if self._think_start is not None and self.game_running:
            elapsed = (time.time() - self._think_start) * 1000
            if self.board.turn == "w":
                w -= elapsed
            else:
                b -= elapsed
        return w, b

    # ═══════════════════════════════════════════════════════
    #  Elo / ranking data (cached)
    # ═══════════════════════════════════════════════════════

    def rating_tc(self):
        """
        The rating bucket the banners should read from.

        While a game runs this answers from the control it started under
        rather than the live selection: the Time control dropdown stays
        editable during a game, and a banner that switched buckets
        mid-game would start describing a different set of results.
        """
        if self.game_running:
            label = getattr(self, "_game_tc_label", "")
            if label:
                return tc_bucket(label)
        return tc_bucket(self.time_control)

    def elo_by_tc(self):
        """
        {bucket: EloBucket}, all of them built on one pass over the DB.

        Every bucket is computed together because they come from the same
        read; keeping the other two costs a dictionary and saves reading
        the games table again the moment the time control changes.

        An engine under MIN_RATED_GAMES still has a rating in *fitted* —
        the solver has no reason to skip it — but is left out of
        *ratings*, so it takes no rank and does not inflate the total a
        rank is quoted against. Being 40th of 110 rated engines means
        something; 40th of 147 where a third have played twice does not.
        """
        if self._elo_cache is None:
            rows = self.db.get_all_games_for_elo_tc()
            tallies = tally_by_tc(rows)
            cache = {}
            for key, fitted in compute_elo_by_tc(rows).items():
                tally = tallies.get(key, {})
                rated = {
                    n: elo for n, (elo, _) in fitted.items()
                    if tally.get(n, {}).get("games", 0) >= MIN_RATED_GAMES}
                ordered = sorted(rated.items(), key=lambda x: -x[1])
                rank_map = {n: i + 1 for i, (n, _) in enumerate(ordered)}
                cache[key] = EloBucket(rated, rank_map, len(ordered),
                                       tally, fitted)
            self._elo_cache = cache
        return self._elo_cache

    def bucket_data(self, tc=None):
        """The EloBucket for one control; the one being played by default."""
        bucket = tc_bucket(tc) if tc else self.rating_tc()
        return self.elo_by_tc().get(bucket, EMPTY_BUCKET)

    def elo_data(self, tc=None):
        """(ratings, rank_map, total) for a bucket, the played one default."""
        b = self.bucket_data(tc)
        return b.ratings, b.rank_map, b.total

    def engine_tally(self, raw_name, tc=None):
        """{games, wins, draws, losses} for an engine in one bucket."""
        return self.bucket_data(tc).tally.get(
            normalize_engine_name(raw_name),
            {"games": 0, "wins": 0, "draws": 0, "losses": 0})

    def elo_estimate(self, raw_name, tc=None):
        """
        (elo, margin, is_provisional) for an engine, or None if never played.

        A provisional engine has a rating like any other — it comes out of
        the same fit, off the same games, and it already carries how much
        the beaten opponents were worth. What it does not have is enough
        of them for the number to be worth quoting flatly, and the margin
        says by how much. Showing it marked beats showing nothing: an
        engine that has just beaten three strong opponents is not a blank.
        """
        b = self.bucket_data(tc)
        key = normalize_engine_name(raw_name)
        fitted = b.fitted.get(key)
        if fitted is None:
            return None
        elo, margin = fitted
        return elo, margin, key not in b.ratings

    def rank_line(self, raw_name, tc=None):
        """'#3/110  Club  •  2410 ±74' text + colour for a player banner."""
        b = self.bucket_data(tc)
        key = normalize_engine_name(raw_name)
        est = self.elo_estimate(raw_name, tc)
        if est is None:
            return "Unranked", "#555"
        elo, margin, provisional = est
        if provisional:
            played = self.engine_tally(raw_name, tc)["games"]
            return (f"Provisional {played}/{MIN_RATED_GAMES}  •  "
                    f"{elo}? ±{margin}"), "#777"
        tier_lbl, tier_col = get_tier(elo)
        return (f"#{b.rank_map.get(key, '?')}/{b.total}  {tier_lbl}  •  "
                f"{elo} ±{margin}"), tier_col

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
        self.set_opening_book(book, path)
        self._refresh_opening_display(reset=True)
        return True

    def set_opening_book(self, book, path):
        """Use *book* from now on — including for the game on the board."""
        self.opening_book = book
        self.opening_csv_path = path
        self._restart_analyst()

    def _restart_analyst(self):
        """A fresh analyst for the game on the board, its moves replayed."""
        self.analyst = GameAnalyst(self.opening_book, self._analyse_live)
        for uci in self.board.uci_moves_list():
            self.analyst.record(uci)

    def _analyse_live(self, moves_str):
        """Analysis of one position for live grading (worker thread)."""
        if not self.analyzer or not self.analyzer.alive:
            return None
        return self.analyzer.analyse(moves_str, LIVE_ANALYSIS_MS, 2)

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

    # ── Review engine ─────────────────────────────────────

    def cpu_busy(self):
        """True while a game or tournament is being played on this machine."""
        from tournament.manager import TournamentRunner
        return self.game_running or TournamentRunner.active > 0

    async def acquire_review_engine(self):
        """
        The engine that analyses games for the review screen, or None if
        no analyzer is set up.

        A second Stockfish, apart from the live analyzer, so reviewing an
        old game never holds up the game being played. It runs below
        normal priority and on one thread while a game or tournament is on,
        so engines at play keep their CPU; otherwise on half the cores.
        Release it with release_review_engine() when done.
        """
        self._review_users += 1
        if self._review_idle is not None:
            self._review_idle.cancel()
            self._review_idle = None
        eng = self._review_engine
        if eng is None or not eng.alive:
            if not self.analyzer_path or not os.path.isfile(self.analyzer_path):
                self._review_users -= 1
                return None
            eng = AnalyzerEngine(self.analyzer_path, "Reviewer",
                                 low_priority=True)
            try:
                await run.io_bound(eng.start)
            except Exception as e:
                self._review_users -= 1
                self._emit("error", f"Could not start the review engine:\n{e}")
                return None
            self._review_engine = eng
        threads = 1 if self.cpu_busy() else max(1, (os.cpu_count() or 2) // 2)
        await run.io_bound(eng.configure, threads, 128)
        return eng

    def release_review_engine(self):
        """Done with the review engine; it shuts down once left idle."""
        self._review_users = max(0, self._review_users - 1)
        if self._review_users or self._review_engine is None:
            return
        loop = asyncio.get_running_loop()
        self._review_idle = loop.call_later(
            REVIEW_ENGINE_IDLE_S,
            lambda: asyncio.ensure_future(self._stop_review_engine()))

    async def _stop_review_engine(self):
        self._review_idle = None
        if self._review_users:
            return
        eng, self._review_engine = self._review_engine, None
        if eng:
            await run.io_bound(eng.stop)

    def _refresh_opening_display(self, reset=False):
        """
        Show the opening the game is in. The analyst names it by position,
        so a transposition into another opening is shown as it happens.
        """
        if reset:
            self.current_opening_name = None
            if self.opening_book.loaded:
                self._emit("opening", f"{len(self.opening_book)} openings ready")
            else:
                self._emit("opening", "No openings CSV loaded")
            return
        _, name = self.analyst.opening
        if name:
            self.current_opening_name = name
            self._emit("opening", self.analyst.opening_label)
        elif self.current_opening_name:
            self._emit("opening", self.current_opening_name)

    def _show_opening(self):
        """
        The opening line for a game just started or taken back: the named
        position it stands in, else the opening it was started from, else
        the book's readiness.
        """
        if self.analyst.opening[1]:
            self._refresh_opening_display()
        elif self.current_opening_name:
            self._emit("opening", self.current_opening_name)
        else:
            self._refresh_opening_display(reset=True)

    # ═══════════════════════════════════════════════════════
    #  Game control
    # ═══════════════════════════════════════════════════════

    async def start_game(self):
        if self.game_running:
            self._emit("error", "Stop the current game first.")
            return

        # Validate config
        if self.play_mode == self.MODE_HVH:
            white, black = self.player_names()
            if normalize_engine_name(white) == normalize_engine_name(black):
                # The game is saved under both names, and a "game" between
                # one name and itself is refused as self-play
                self._emit("error", "The two players need different names.")
                return
            paths = []                    # two people, no engine to load
        elif self.play_mode == self.MODE_HVE:
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
        self._restart_analyst()           # preset moves included
        self._preset_plies = len(self.board.move_history)
        self._start_opening_name = self.current_opening_name
        self._clock_log = [(self.wtime_ms, self.btime_ms)] * (self._preset_plies + 1)
        self._show_opening()

        self._emit("eval_bar", 0)
        self._emit("move_review", None)
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
        self._emit("board_changed")       # the player's pieces can move now
        self._emit("sound", "game_start")

        if self.play_mode == self.MODE_HVH:
            self._emit("status", self._turn_prompt())
        elif self.play_mode == self.MODE_HVE:
            base = self.e2_name.split("(")[0].strip()
            color_label = "Black" if self.player_color == "white" else "White"
            self.e2_name = f"{base} ({color_label})"
            self._emit("banners")
            human_to_move = (
                (self.player_color == "white") == (self.board.turn == "w"))
            if human_to_move:
                self._emit("status", self._your_turn_prompt())
            else:
                self._game_task = asyncio.create_task(self._engine_turn())
        else:
            self._game_task = asyncio.create_task(self._game_loop())

    async def _load_engines(self):
        """Start the engine subprocess(es). Returns True on success."""
        if self.play_mode == self.MODE_HVH:
            return True
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
            self._remember_game(result)
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
        self.eval_bar_cp = 0
        self._clock_log = []
        self._preset_plies = 0
        self._start_opening_name = None
        self._restart_analyst()
        self._refresh_opening_display(reset=True)
        self._emit("eval_bar", 0)
        self._emit("move_review", None)
        self._emit("board_changed")
        self._emit("status", "New game — set it up and press Start Game")

    def swap_colors(self):
        """Swap sides for the next game (between games only).

        EvE: engine1/engine2 exchange colors.  HvE: the human's color flips.
        """
        if self.game_running:
            return False
        if self.play_mode == self.MODE_HVH:
            self.white_player, self.black_player = (self.black_player,
                                                    self.white_player)
            self._emit("engine_log",
                       f"⇄ Colors swapped — {self.white_player} now plays "
                       f"White", "E")
            self._emit("banners")
            return True
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
        for attr in ("analyzer", "_review_engine"):
            eng = getattr(self, attr)
            if eng:
                try:
                    await run.io_bound(eng.stop)
                except Exception:
                    pass
                setattr(self, attr, None)

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

    def can_move_now(self):
        """True while a person is to move and the game is taking moves."""
        return (self.game_running and not self._engine_thinking
                and not self.game_paused and self.human_to_move())

    def movable_squares(self):
        """Squares of the pieces the person to move can pick up and play."""
        if not self.can_move_now():
            return set()
        return {(m[0], m[1]) for m in self.board.legal_moves()}

    def pick_up(self, br, bc):
        """A piece on (br, bc) is being dragged: select it, if it may move."""
        if (br, bc) in self.movable_squares() and self.selected_square != (br, bc):
            self.selected_square = (br, bc)
            self._emit("board_changed")

    async def drop_piece(self, fr, fc, br, bc):
        """The piece dragged from (fr, fc) was let go on (br, bc)."""
        self.pick_up(fr, fc)            # in case the drag start went unheard
        if self.selected_square == (fr, fc):
            await self.click_square(br, bc)

    async def click_square(self, br, bc):
        """Handle a click on board square (row, col) in board coordinates."""
        if not self.can_move_now():
            return
        mover_white = (self.board.turn == "w")

        piece = self.board.get(br, bc)
        is_own = (piece and piece != "." and
                  (piece.isupper() if mover_white else piece.islower()))

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
                    "w" if mover_white else "b")) or "q"
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
        if self.play_mode == self.MODE_HVH:
            self._emit("status", self._turn_prompt())
        else:
            self._game_task = asyncio.create_task(self._engine_turn())

    def _turn_prompt(self):
        """Status line for whoever is to move in 2-player mode."""
        white, black = self.player_names()
        side, name = (("White", white) if self.board.turn == "w"
                      else ("Black", black))
        check = " — in CHECK!" if self.board.in_check() else ""
        return f"{name} to move ({side}){check}"

    def _your_turn_prompt(self):
        """Status line when it is the person's move against the engine."""
        if self.board.in_check():
            return "CHECK! Your turn — you must get out of check!"
        return "Your turn — click or drag a piece to move"

    # ═══════════════════════════════════════════════════════
    #  Takebacks
    # ═══════════════════════════════════════════════════════

    def _undo_plies(self):
        """
        How many plies an Undo takes back now: one in 2-player mode; the
        person's last move and the engine's reply against an engine, so it
        is their turn again. 0 when nothing can be taken back — the preset
        opening moves never are.
        """
        if (not self.game_running or self.game_paused
                or self._engine_thinking):
            return 0
        played = len(self.board.move_history) - self._preset_plies
        if self.play_mode == self.MODE_HVH:
            return 1 if played >= 1 else 0
        if self.play_mode == self.MODE_HVE and self.human_to_move():
            return 2 if played >= 2 else 0
        return 0

    def can_undo(self):
        """True when the person at the board may take a move back now."""
        return self._undo_plies() > 0

    def undo(self):
        """
        Take moves back (see _undo_plies). The board is replayed up to the
        position kept, so repetition counts and captured pieces are right,
        and the clocks go back to where they stood. Moves already graded
        keep their grades. Returns True if anything was taken back.
        """
        plies = self._undo_plies()
        if not plies:
            return False
        keep = len(self.board.move_history) - plies
        moves = self.board.uci_moves_list()[:keep]
        self.board.reset()
        for uci in moves:
            self.board.apply_uci(uci)
        self.last_move = moves[-1] if moves else None
        self.selected_square = None
        if len(self._clock_log) > keep:
            self.wtime_ms, self.btime_ms = self._clock_log[keep]
            del self._clock_log[keep + 1:]
        self.analyst = self.analyst.truncated(keep)
        self.current_opening_name = self._start_opening_name
        self._show_opening()

        last = self.analyst.reviews[keep - 1] if keep else None
        self._emit("sound", "move")
        self._emit("board_changed")
        self._emit("move_review", last)
        self._emit("clock")
        self._emit("banners")
        self._emit("status", self._turn_prompt()
                   if self.play_mode == self.MODE_HVH
                   else self._your_turn_prompt())
        if keep > self._preset_plies and last is None:
            # Its grade was still being worked out on the old analyst
            asyncio.create_task(self._grade_move(self.analyst, keep))
        return True

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
            self._emit("status", self._your_turn_prompt())
        except asyncio.CancelledError:
            pass
        finally:
            self._engine_thinking = False
            if self.game_running:
                self._emit("board_changed")   # the player's pieces can move now

    # ═══════════════════════════════════════════════════════
    #  Shared post-move / end-game plumbing
    # ═══════════════════════════════════════════════════════

    def _sound_for_san(self, san, was_white):
        """Sound effect kind for a SAN move played in this session."""
        if self.play_mode == self.MODE_HVE:
            near_side = (self.player_color == "white") == was_white
        else:
            near_side = was_white
        return sound_for_san(san, near_side)

    def _after_move(self, moves_before, was_white, san):
        # The analyst first: the board's listeners read it (move list grades)
        self.analyst.record(self.board.move_history[-1][0])
        self._clock_log.append((self.wtime_ms, self.btime_ms))
        self._emit("sound", self._sound_for_san(san, was_white))
        self._emit("board_changed")
        self._refresh_opening_display()
        asyncio.create_task(self._grade_move(self.analyst, self.analyst.ply))

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
        self._remember_game(result)

        msg = (f"{normalize_engine_name(winner)} wins by {reason}"
               if winner else f"{result} — {reason}")
        self._emit("status", msg)
        self.swap_colors()          # reversed colors for the rematch
        self._emit("banners")
        self._emit("sound", "game_end")
        self._emit("game_over", result, reason, winner)

    async def _save_game(self, result, reason):
        # Every mode is recorded under its players' names — in 2-player mode
        # both are people, who get a rating like any engine
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

    def _remember_game(self, result):
        """
        Keep what the review screen needs about the game that just ended.
        Taken before the colours are swapped for the rematch, which would
        otherwise put the names on the wrong sides.
        """
        white, black = self.player_names()
        self.last_game = {
            "moves": self.board.uci_moves_list(),
            "white": white, "black": black, "result": result,
            "tc": getattr(self, "_game_tc_label", ""),
            "pgn": self.export_pgn_text(),
        }

    # ═══════════════════════════════════════════════════════
    #  Move grading
    # ═══════════════════════════════════════════════════════

    async def _grade_move(self, analyst, ply):
        """
        Grade the move that reached *ply* with the same analyst the review
        screen uses, so a move is classed the same live as in review. The
        analyzer's work runs off the event loop, one position at a time.
        """
        async with self._analyzer_alock:
            # A new game, or a game that has run two moves ahead (bullet),
            # leaves this move ungraded rather than queueing up behind it
            if analyst is not self.analyst or analyst.ply - ply >= 2:
                return
            review = await run.io_bound(analyst.grade, ply)
        if review is None or analyst is not self.analyst:
            return                        # app shutting down / new game
        self._emit("move_review", review)

    def game_summary(self):
        """core.review.GameReview of the game on the board, as graded so far."""
        return self.analyst.summary()
