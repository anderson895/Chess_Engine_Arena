# ═══════════════════════════════════════════════════════════
#  webui/review.py — Game Review screen
#
#  Laid out like chess.com's Game Review: the board between its player
#  bars on the left; on the right a summary — accuracy and how many moves
#  of each class both players made — and, after "Start Review", a
#  move-by-move walk with a coach's line, the engine's best move as an
#  arrow and the evaluation graph.
#
#  Moves are graded by core.review.GameAnalyst, the same code that grades
#  the live game and tournament games, fed here by a dedicated review
#  engine so a deeper look never holds up a game being played.
#
#  As on chess.com, any move can be tried on the board: it starts a side
#  line from the position shown, graded like the game's own moves, and
#  "Best" plays out the engine's line from there. "Continue from here"
#  makes the position shown the start of the next game on the main board.
# ═══════════════════════════════════════════════════════════

import os
from dataclasses import dataclass
from html import escape

from nicegui import background_tasks, run, ui

from core.constants import QUALITY_COLORS
from core.move_input import MoveInput
from core.pgn import read_game, start_fen_of, start_problem
from core.opening_book import opening_label
from core.review import GameAnalyst, PHASES, TABLE_ORDER
from core.start_position import StartPosition
from core.utils import normalize_engine_name
from data.reviews import ReviewCache
from webui.board import BoardView, EvalBar
from webui.quality import (MOVE_CLICK_JS, NO_BEST_HINT, QUALITY_TIPS,
                           coach_html, icon_svg, line_html, move_list_html)
from webui.theme import piece_src
from webui.widgets import PlayerBar, close_dialogs

# Search per position: label, milliseconds
SPEEDS = {
    "fast":     ("Fast", 200),
    "balanced": ("Balanced", 500),
    "deep":     ("Deep", 1500),
}
DEFAULT_SPEED = "balanced"
BOOK_SHARE = 0.3        # a book position only feeds the graph: search it less
BEST_ARROW = "#81B64C"
BEST_LINE_PLIES = 8     # how much of the engine's line "Best" plays out
GRAPH_MOMENTS = ("Brilliant", "Great", "Miss", "Mistake", "Blunder")
GRAPH_EVERY = 6         # redraw the graph every this many positions analysed


def _rating_text(value):
    value = str(value or "").strip()
    return "" if value in ("", "?", "-", "0") else value


def engine_rating(session, name, tc=None):
    """'2410', '2410?' for a provisional engine, or '' when never rated."""
    est = session.elo_estimate(name, tc)
    if est is None:
        return ""
    elo, _margin, provisional = est
    return f"{elo}?" if provisional else str(elo)


@dataclass
class ReviewSource:
    """
    A game to review: its moves and what the player bars show. The moves
    are played from *start_fen* — None for the standard start.
    """
    moves: list
    white: str
    black: str
    result: str = "*"
    white_rating: str = ""
    black_rating: str = ""
    title: str = ""
    pgn: str = ""
    start_fen: str | None = None
    problem: str = ""                 # why the game cannot be shown, if so

    @classmethod
    def from_pgn(cls, pgn, title="", ratings=None):
        """From PGN text; ratings default to the WhiteElo/BlackElo tags."""
        tags, moves = read_game(pgn)
        white_r, black_r = ratings or (tags.get("WhiteElo"), tags.get("BlackElo"))
        return cls(moves, tags.get("White") or "White", tags.get("Black") or "Black",
                   tags.get("Result") or "*", _rating_text(white_r),
                   _rating_text(black_r), title, pgn, start_fen_of(tags),
                   start_problem(tags) or "")

    @classmethod
    def from_session(cls, session):
        """The game on the main board, or the one that just ended; None if neither."""
        moves = session.board.uci_moves_list()
        # A board that only shows where the next game will start has
        # nothing of its own to review: the game before it is the one
        preview = session.board_is_preview
        last = session.last_game
        if last and (preview or not moves or (
                last["moves"] == moves
                and last.get("start_fen") == session.game_start.fen)):
            # Finished: take the names from before the colours were swapped
            white, black = last["white"], last["black"]
            return cls(last["moves"], white, black, last["result"],
                       engine_rating(session, white, last["tc"]),
                       engine_rating(session, black, last["tc"]),
                       "Last game", last.get("pgn") or "",
                       last.get("start_fen"))
        if not moves or preview:
            return None
        white, black = session.player_names()
        tc = session.rating_tc()
        return cls(moves, white, black, session.game_result or "*",
                   engine_rating(session, white, tc),
                   engine_rating(session, black, tc),
                   "Current game", session.export_pgn_text() or "",
                   session.game_start.fen)


class Variation:
    """
    Moves tried from a position of the game: a side line. It is the game
    up to *base* plus the moves tried, kept as a GameAnalyst so they are
    analysed and graded just as the game's own moves are.
    """

    def __init__(self, game, base, analyse):
        self.base = base                  # the game ply the line leaves from
        self.analyst = game.truncated(base, analyse)
        self.shown = 0                    # how many of its moves are on the board

    @property
    def length(self):
        return self.analyst.ply - self.base

    @property
    def ply(self):
        """The analyst's ply of the position shown."""
        return self.base + self.shown

    def next_move(self):
        """The line's move after the one shown, or None."""
        return (self.analyst.moves[self.ply]
                if self.ply < self.analyst.ply else None)

    def play(self, uci):
        """Play *uci* after the move shown; whatever followed it goes."""
        if self.ply < self.analyst.ply:
            self.analyst = self.analyst.truncated(self.ply)
        self.analyst.record(uci)
        self.shown += 1


class ReviewScreen:
    """One open Game Review dialog."""

    def __init__(self, session, source, nav=None):
        self.session = session
        self.src = source
        self.nav = nav or {}
        self.ply = 0
        self.mode = "summary"
        self.speed = DEFAULT_SPEED
        self.flipped = False
        self.closed = False
        self._run_id = 0
        self._engine = None
        self.summary = None
        self.var = None                   # the side line being tried, if any
        self._grading = set()             # (analyst id, ply) being graded
        self._tried_engine = None
        self._no_engine = False
        # Moves tried on the board, in the walkthrough only
        self.hand = MoveInput(self._hand_board, self._try_move,
                              can_move=lambda: self.mode == "review",
                              promote=session.ask_promotion)
        self._new_analyst()
        self._build()
        self.dialog.open()
        self.goto(0, chart=False)        # the chart starts on ply 0 already
        self._start_analysis()

    # ── State ─────────────────────────────────────────────

    def _new_analyst(self):
        self.analyst = GameAnalyst(self.session.opening_book,
                                   start_fen=self.src.start_fen)
        for uci in self.src.moves:
            try:
                self.analyst.record(uci)
            except ValueError:
                break
        self.moves = self.analyst.moves
        self.n = self.analyst.ply

    def _line(self):
        """(analyst, ply) of the position shown: the game's, or the side line's."""
        if self.var is not None:
            return self.var.analyst, self.var.ply
        return self.analyst, self.ply

    def _hand_board(self):
        analyst, ply = self._line()
        return analyst.boards[ply]

    def _board_state(self):
        analyst, ply = self._line()
        board = analyst.boards[ply]
        rv = analyst.reviews[ply - 1] if ply else None
        arrows = []
        if (rv and rv.best_uci and rv.best_uci != rv.uci
                and rv.cls not in NO_BEST_HINT):
            arrows.append((rv.best_uci, BEST_ARROW))
        return {
            "board": board,
            "last_move": analyst.moves[ply - 1] if ply else None,
            "selected": self.hand.selected,
            "legal_dests": self.hand.dests(),
            "movable": self.hand.movable(),
            "check_sq": board.find_king(board.turn) if board.in_check() else None,
            "move_class": rv.cls if rv else None,
            "arrows": arrows,
        }

    # ── Layout ────────────────────────────────────────────

    def _build(self):
        self.client = ui.context.client
        # Built at the page root rather than inside whatever opened it (the
        # history list, or the previous review on "next game"): a review
        # deletes itself when closed, and would take a review nested in it
        # along
        with self.client.layout, ui.dialog().props("maximized") as self.dialog, \
                ui.card().classes("review-root w-full h-full p-3 no-shadow"):
            with ui.row().classes("w-full h-full no-wrap gap-4 items-stretch"):
                self._build_board_side()
                self._build_panel()
            ui.keyboard(on_key=self._on_key,
                        ignore=["input", "select", "textarea"])
        self.dialog.on_value_change(
            lambda e: None if e.value else self._on_close())

    def _build_board_side(self):
        with ui.column().classes("flex-grow min-w-0 items-center "
                                 "justify-center gap-1"):
            with ui.column().classes("gap-1 w-full items-stretch") \
                    .style("max-width: calc(100vh - 110px)"):
                self.top_bar = PlayerBar()
                with ui.row().classes("w-full no-wrap gap-2 items-stretch"):
                    with ui.column().classes("gap-0 self-stretch"):
                        self.eval_bar = EvalBar()
                    with ui.element("div").classes("flex-grow min-w-0"):
                        # A move made here is tried as a side line
                        self.board = BoardView(self._board_state, overlay=True,
                                               on_click=self._board_click,
                                               on_drag_start=self._board_pick,
                                               on_drop=self._board_drop)
                self.bottom_bar = PlayerBar()

    def _build_panel(self):
        with ui.column().classes("review-panel w-[430px] shrink-0 h-full "
                                 "no-wrap gap-0"):
            self._build_header()
            with ui.element("div").classes("coach review-coach w-full"):
                ui.element("img").props('src="/assets/logo.png"')
                self.bubble = ui.html("", sanitize=False).classes("coach-bubble")
            with ui.row().classes("review-actions w-full items-center "
                                  "no-wrap gap-2") as self.actions:
                ui.label("Move a piece to try your own idea") \
                    .classes("var-head flex-grow")
                self.best_btn = ui.button("Best", icon="star", color=None,
                                          on_click=self._show_best) \
                    .props("dense no-caps unelevated") \
                    .tooltip("Play out the engine's best line from here")
            self.graph = ui.echart(self._graph_options(),
                                   on_point_click=lambda e: self.goto(e.data_index)) \
                .classes("review-graph").style("height: 84px")
            with ui.row().classes("review-progress w-full items-center "
                                  "no-wrap gap-2"):
                self.progress = ui.linear_progress(value=0, show_value=False) \
                    .props("color=positive rounded").classes("flex-grow")
                self.progress_lbl = ui.label("")
                self.speed_sel = ui.select(
                    {k: label for k, (label, _) in SPEEDS.items()},
                    value=self.speed, on_change=lambda e: self._set_speed(e.value)) \
                    .props("dense borderless options-dense dark",
                           remove="filled") \
                    .classes("review-speed ml-auto") \
                    .tooltip("Engine time per position — deeper is slower "
                             "but surer about Brilliant and Great moves")
            with ui.scroll_area().classes("w-full flex-grow min-h-0"):
                self.summary_box = ui.column().classes("w-full gap-0")
                self.walk_box = ui.column().classes("w-full gap-1")
                with self.walk_box.classes("review-walk"):
                    with ui.column().classes("var-box w-full gap-1") \
                            as self.var_box:
                        with ui.row().classes("w-full items-center no-wrap gap-2"):
                            self.var_head = ui.label("").classes("var-head flex-grow")
                            ui.button("Back to game", icon="undo", color=None,
                                      on_click=self._leave_variation) \
                                .props("dense flat no-caps size=sm")
                        self.var_list = ui.html("", sanitize=False) \
                            .classes("var-line w-full")
                        self.var_list.on("click",
                                         lambda e: self._var_goto(int(e.args)),
                                         js_handler=MOVE_CLICK_JS)
                    self.var_box.set_visibility(False)
                    self.opening_lbl = ui.label("").classes("opening-line")
                    self.move_list = ui.html("", sanitize=False) \
                        .classes("move-grid w-full")
                    self.move_list.on("click", lambda e: self.goto(int(e.args)),
                                      js_handler=MOVE_CLICK_JS)
            # Buttons here take no Quasar colour (color=None): the review's
            # own greys and green come from the theme CSS
            with ui.column().classes("review-foot w-full gap-2"):
                self.start_btn = ui.button("Start Review", color=None,
                                           on_click=lambda: self.set_mode("review")) \
                    .props("no-caps unelevated").classes("cta w-full")
                self.continue_btn = ui.button(
                    "Continue from here", icon="play_arrow", color=None,
                    on_click=self._continue_from_here) \
                    .props("no-caps unelevated").classes("continue-btn w-full") \
                    .tooltip("Start the next game from the position on the board")
                with ui.row().classes("nav-row w-full no-wrap gap-2") \
                        as self.nav_row:
                    for icon, step, tip in (("first_page", "start", "Start"),
                                            ("chevron_left", "back", "Previous move"),
                                            ("chevron_right", "forward", "Next move"),
                                            ("last_page", "end", "End")):
                        ui.button(icon=icon, color=None,
                                  on_click=lambda s=step: self.step(s)) \
                            .props("flat dense").classes("flex-grow").tooltip(tip)
                    # Next carries on through the game itself, leaving any
                    # side line tried from the move shown
                    ui.button("Next", color=None,
                              on_click=lambda: self.goto(self.ply + 1)) \
                        .props("no-caps unelevated") \
                        .classes("cta flex-grow").style("font-size: 1rem")
        self.set_mode("summary")

    def step(self, where):
        """
        Move through what is shown: 'start', 'back', 'forward' or 'end'.
        Back and forward step along a side line while one is shown.
        """
        if self.var is not None and where in ("back", "forward"):
            self._var_goto(self.var.shown + (1 if where == "forward" else -1))
            return
        self.goto({"start": 0, "back": self.ply - 1,
                   "forward": self.ply + 1, "end": self.n}[where])

    def _build_header(self):
        def icon_btn(icon, tip, on_click):
            return ui.button(icon=icon, color=None, on_click=on_click) \
                .props("flat round dense").tooltip(tip)

        with ui.row().classes("review-head w-full items-center no-wrap gap-1"):
            ui.html(icon_svg("Best", 26), sanitize=False)
            ui.label("Game Review").classes("review-title")
            ui.space()
            icon_btn("swap_vert", "Flip board", self.flip)
            if self.src.pgn:
                icon_btn("content_copy", "Copy PGN", self._copy_pgn)
                icon_btn("download", "Download PGN", self._download_pgn)
            for key, icon, tip in (("prev", "skip_previous", "Previous game"),
                                   ("next", "skip_next", "Next game")):
                if key in self.nav:
                    btn = icon_btn(icon, tip, lambda k=key: self._switch_game(k))
                    if self.nav[key] is None:
                        btn.disable()
            icon_btn("close", "Close", self.dialog.close)

    # ── Summary view ──────────────────────────────────────

    def _render_summary(self):
        s = self.summary
        self.summary_box.clear()
        with self.summary_box, ui.element("div").classes("review-grid w-full"):
            ui.label("Players").classes("lbl")
            self._summary_avatar("w")
            ui.element("div")
            self._summary_avatar("b")

            ui.label("Accuracy").classes("lbl")
            for side in ("w", "b"):
                acc = s.accuracy.get(side) if s else None
                ui.label(f"{acc:.1f}" if acc is not None else "—") \
                    .classes(f"review-acc {side}")
                if side == "w":
                    ui.element("div")
            ui.element("div").classes("sep")

            for cls in TABLE_ORDER:
                color = QUALITY_COLORS[cls]
                ui.label(cls).classes("lbl").tooltip(QUALITY_TIPS[cls])
                for side in ("w", "b"):
                    n = s.counts[side][cls] if s else 0
                    ui.label(str(n) if s else "–").classes("num") \
                        .style(f"color: {color}")
                    if side == "w":
                        ui.html(icon_svg(cls, 30), sanitize=False) \
                            .classes("mid").tooltip(QUALITY_TIPS[cls])
            ui.element("div").classes("sep")

            for phase in PHASES:
                ui.label(phase).classes("lbl")
                for side in ("w", "b"):
                    grade = s.phases[side][phase] if s else None
                    with ui.element("div").classes("mid"):
                        if grade:
                            ui.html(icon_svg(grade, 26), sanitize=False) \
                                .tooltip(grade)
                        else:
                            ui.label("—").style("color: #6B6966")
                    if side == "w":
                        ui.element("div")

    def _summary_avatar(self, side):
        with ui.column().classes("items-center gap-0 min-w-0"):
            with ui.element("div").classes("pb-avatar"):
                ui.element("img").props(f'src="{piece_src(side + "K")}"')
            name = self.src.white if side == "w" else self.src.black
            ui.label(name).classes("text-xs ellipsis w-full text-center") \
                .style("color: #BDBAB7")

    def _summary_text(self):
        """The coach's opening line about the whole game."""
        src, s = self.src, self.summary
        winner = {"1-0": src.white, "0-1": src.black}.get(src.result)
        head = (f"{escape(winner)} won the game." if winner else
                "The game was drawn." if src.result == "1/2-1/2" else
                "The game is unfinished.")
        if not s:
            return f"<div>{head}</div><div class='line'>Analysing the game…</div>"
        notes = []
        for cls in ("Brilliant", "Great"):
            hits = [m for m in s.moves if m and m.cls == cls]
            if hits:
                names = ", ".join(escape(f"{m.number}{m.san}") for m in hits[:4])
                notes.append(f"{cls}: {names}")
        acc = s.accuracy
        if acc.get("w") is not None and acc.get("b") is not None:
            notes.insert(0, f"Accuracy {acc['w']:.1f} – {acc['b']:.1f}")
        return f"<div>{head}</div><div class='line'>{' · '.join(notes)}</div>"

    # ── Walkthrough view ──────────────────────────────────

    def _render_move_list(self):
        self.move_list.set_content(move_list_html(
            self.analyst.sans, self.analyst.reviews, self.ply,
            ply0=self.analyst.ply0))

    def _bubble_for_move(self):
        analyst, ply = self._line()
        if ply == 0:
            return self._summary_text()
        rv = analyst.reviews[ply - 1]
        if self.var is None:
            waiting = " — analysing…" if self.summary is None else ""
        else:
            waiting = (" — load an analyzer on the main screen to grade it"
                       if self._no_engine else " — analysing…")
        return coach_html(
            rv, f"{analyst.number(ply)} {analyst.sans[ply - 1]}",
            analyst.eval_after(ply),
            analyst.best_line_san(ply) if rv else (), waiting)

    def _render_variation(self):
        """The side line under the coach: its moves, the one shown marked."""
        self.var_box.set_visibility(self.var is not None)
        if self.var is None:
            return
        var, game = self.var, self.analyst
        # The line takes the place of the game's move after its base
        self.var_head.set_text(
            f"Instead of {game.number(var.base + 1)} {game.sans[var.base]}"
            if var.base < self.n else "Played on from the final position")
        self.var_list.set_content(line_html(
            var.analyst.sans[var.base:], var.analyst.reviews[var.base:],
            game.ply0 + var.base + 1, var.shown))

    # ── Navigation ────────────────────────────────────────

    def set_mode(self, mode):
        self.mode = mode
        summary = mode == "summary"
        self.summary_box.set_visibility(summary)
        self.start_btn.set_visibility(summary)
        self.walk_box.set_visibility(not summary)
        self.nav_row.set_visibility(not summary)
        self.continue_btn.set_visibility(not summary)
        self.actions.set_visibility(not summary)
        if not summary:
            self._render_move_list()
            if self.ply == 0 and self.n:
                self.goto(1)
                return
        # Redrawn either way: whether the pieces can be moved depends on it
        self.var = None
        self._show()

    def goto(self, ply, chart=True):
        """Show the game after *ply* moves, leaving any side line."""
        self.var = None
        self.ply = max(0, min(self.n, int(ply)))
        ply = self.ply
        self._show()
        if chart:
            # Only the marker moves: re-sending the series on every step
            # would ship the whole graph again
            self.graph.options["series"][0]["markLine"] = self._marker()
            self.graph.run_chart_method(
                "setOption", {"series": [{"id": "wp", "markLine": self._marker()}]})
        if self.mode == "review":
            # Move the highlight in the browser: re-sending the whole list
            # on every step would be hundreds of moves per key press
            ui.run_javascript(
                f"(() => {{ const el = document.getElementById('{self.move_list.html_id}');"
                f" if (!el) return; el.querySelectorAll('.mv.cur').forEach("
                f"x => x.classList.remove('cur'));"
                f" const t = el.querySelector('[data-ply=\"{ply}\"]');"
                f" if (t) {{ t.classList.add('cur'); t.scrollIntoView({{block: 'nearest'}}); }}"
                f" }})()")

    def _refresh_bars(self, board):
        white_pts, black_pts = board.material()
        lead = white_pts - black_pts
        result = self.src.result
        sides = [("w", self.src.white, self.src.white_rating, lead, result == "1-0"),
                 ("b", self.src.black, self.src.black_rating, -lead, result == "0-1")]
        bottom, top = (sides[1], sides[0]) if self.flipped else (sides[0], sides[1])
        for bar, (side, name, rating, ahead, won) in ((self.bottom_bar, bottom),
                                                     (self.top_bar, top)):
            bar.show(side, name, f"({rating})" if rating else "", winner=won)
            bar.set_material(ahead)

    def _show(self):
        """Draw the position shown — the game's, or the side line's."""
        analyst, ply = self._line()
        self.hand.clear()
        self.board.refresh()
        cp, mate = analyst.eval_after(ply)
        if cp is not None or mate is not None:
            self.eval_bar.set_eval(cp, mate)
        self._refresh_bars(analyst.boards[ply])
        self._refresh_text()
        self._render_variation()
        if self.var is not None and ply and analyst.reviews[ply - 1] is None:
            background_tasks.create(self._grade_tried(analyst, ply),
                                    name="review-tried-move")

    def _refresh_position(self):
        """Redraw after new analysis, staying in a side line if one is shown."""
        if self.var is None:
            self.goto(self.ply)
        else:
            self._show()

    def _refresh_text(self):
        if self.mode == "summary":
            self.bubble.set_content(self._summary_text())
            return
        self.bubble.set_content(self._bubble_for_move())
        analyst, ply = self._line()
        # The opening as it stood at this point — it can change later in
        # the game when the moves transpose
        self.opening_lbl.set_text(opening_label(*analyst.openings[ply]))
        line = self._best_line(analyst, ply)
        self.best_btn.set_visibility(bool(line))
        self.best_btn.set_text(
            "Follow-up" if line and line[0] == analyst.moves[ply - 1] else "Best")

    def flip(self):
        self.flipped = not self.flipped
        self.board.flip()
        self.eval_bar.set_flipped(self.flipped)
        analyst, ply = self._line()
        self._refresh_bars(analyst.boards[ply])

    def _on_key(self, e):
        if not e.action.keydown:
            return
        if e.key.arrow_left:
            self.step("back")
        elif e.key.arrow_right:
            self.step("forward")
        elif e.key.name == "Home":
            self.step("start")
        elif e.key.name == "End":
            self.step("end")

    # ── Trying moves: side lines ──────────────────────────

    async def _board_click(self, r, c):
        if await self.hand.click(r, c) == "select":
            self.board.refresh()

    def _board_pick(self, r, c):
        if self.hand.pick(r, c):
            self.board.refresh()

    async def _board_drop(self, fr, fc, tr, tc):
        if await self.hand.drop(fr, fc, tr, tc) == "select":
            self.board.refresh()

    def _try_move(self, uci):
        """
        A move made on the board. The game's own next move (or the side
        line's) just steps on; anything else is tried from the position
        shown, replacing whatever the side line had after it.
        """
        if self.var is None:
            if self.ply < self.n and self.moves[self.ply] == uci:
                self.goto(self.ply + 1)
                return
            self.var = Variation(self.analyst, self.ply, self._analyse_tried)
        elif self.var.next_move() == uci:
            self._var_goto(self.var.shown + 1)
            return
        self.var.play(uci)
        self._show()

    def _var_goto(self, shown):
        """Show the side line after *shown* of its moves; 0 is back to the game."""
        if self.var is None:
            return
        if shown < 1:
            self._leave_variation()
        elif shown <= self.var.length:
            self.var.shown = shown
            self._show()

    def _leave_variation(self):
        """Back to the game's move the side line was tried from."""
        if self.var is not None:
            self.goto(self.ply)

    # ── Continue from here ────────────────────────────────

    def _continue_from_here(self):
        """
        Make the position on the board — the game's, or a side line's —
        the start of the next game on the main board, as Lichess's
        "Continue from here" does. Only the position goes: the moves that
        led to it were not played by the next game's players.
        """
        analyst, ply = self._line()
        players = (f"{normalize_engine_name(self.src.white)} – "
                   f"{normalize_engine_name(self.src.black)}")
        where = (f"After {analyst.number(ply)} {analyst.sans[ply - 1]}"
                 if ply else "Start")
        start = StartPosition(fen=analyst.boards[ply].to_fen(),
                              label=f"{where} · {players}")
        if start.is_standard:
            start = StartPosition()
        problem = self.session.set_preset(start)
        if problem:
            ui.notify(f"No game can start from this position: {problem}",
                      type="warning")
            return
        ui.notify("Starting position set for the next game"
                  if self.session.game_running else
                  "Starting position set — press Start Game",
                  type="positive")
        # Back to the main screen, where the game will be played — past
        # whatever the review was opened from (History, Masters …)
        close_dialogs()

    def _analyse_tried(self, moves_str, start_fen=None):
        """Analysis of a position off the game's path (worker thread)."""
        engine = self._tried_engine
        if engine is None or not engine.alive:
            return None
        return engine.analyse(moves_str, SPEEDS[self.speed][1], 2, start_fen)

    async def _grade_tried(self, analyst, ply):
        """Grade the tried move that reached *ply*, then redraw if still shown."""
        key = (id(analyst), ply)
        if key in self._grading:
            return
        self._grading.add(key)
        engine = await self.session.acquire_review_engine()
        try:
            self._no_engine = engine is None
            if engine is None:
                self._refresh_text()
                return
            self._tried_engine = engine
            await run.io_bound(analyst.grade, ply)
        finally:
            self._grading.discard(key)
            if engine is not None:
                self.session.release_review_engine()
        if not self.closed and self.var is not None and self.var.analyst is analyst:
            self._show()

    @staticmethod
    def _best_line(analyst, ply):
        """The engine's line (UCI) from the position before move *ply*, or []."""
        if not ply:
            return []
        lines = (analyst.analyses[ply - 1] or {}).get("lines") or []
        return list(lines[0].get("pv") or [])[:BEST_LINE_PLIES] if lines else []

    def _show_best(self):
        """
        Play out the engine's best line in place of the move shown — or,
        when that move was the best, the line that follows it — as a side
        line to step through.
        """
        analyst, ply = self._line()
        line = self._best_line(analyst, ply)
        if not line:
            return
        start = ply - 1
        if line[0] == analyst.moves[ply - 1]:
            start, line = ply, line[1:]
        if not line:
            return
        if self.var is None:
            self.var = Variation(self.analyst, start, self._analyse_tried)
        self.var.shown = start - self.var.base
        first = self.var.shown + 1
        for uci in line:
            try:
                self.var.play(uci)
            except ValueError:
                break
        self._var_goto(first)

    # ── Graph ─────────────────────────────────────────────

    def _marker(self):
        return {"symbol": "none", "silent": True, "animation": False,
                "label": {"show": False},
                "lineStyle": {"color": "#81B64C", "width": 2, "type": "solid"},
                "data": [{"xAxis": self.ply}]}

    def _graph_options(self):
        wins = self.analyst.summary().white_wins if self.n else [50]
        wins = [round(w, 1) if w is not None else None for w in wins]
        moments = []
        for m in self.analyst.reviews:
            if m and m.cls in GRAPH_MOMENTS and wins[m.ply] is not None:
                moments.append({"value": [m.ply, wins[m.ply]],
                                "itemStyle": {"color": QUALITY_COLORS[m.cls]}})
        count = self.n + 1
        return {
            "animation": False,
            "backgroundColor": "#403D39",
            "grid": {"left": 0, "right": 0, "top": 0, "bottom": 0},
            "tooltip": {"show": False},
            "xAxis": {"type": "category", "show": False, "boundaryGap": False,
                      "data": list(range(count))},
            "yAxis": {"type": "value", "show": False, "min": 0, "max": 100},
            "series": [
                {"id": "wp", "type": "line", "data": wins, "showSymbol": False,
                 "connectNulls": True, "lineStyle": {"width": 0},
                 "areaStyle": {"color": "#FFFFFF", "opacity": 1, "origin": "start"},
                 "markLine": self._marker()},
                {"id": "mid", "type": "line", "data": [50] * count,
                 "showSymbol": False, "silent": True,
                 "lineStyle": {"color": "#8B8987", "width": 1, "type": "dashed"}},
                {"id": "moments", "type": "scatter", "data": moments,
                 "symbolSize": 8, "silent": True, "z": 5},
                # Invisible full-height bars: a click anywhere picks the ply
                {"id": "hit", "type": "bar", "data": [100] * count,
                 "barWidth": "100%", "itemStyle": {"color": "rgba(0,0,0,0)"},
                 "z": 10},
            ],
        }

    def _redraw_graph(self):
        self.graph.options.clear()
        self.graph.options.update(self._graph_options())
        self.graph.update()

    # ── Analysis ──────────────────────────────────────────

    def _set_speed(self, speed):
        if speed == self.speed:
            return
        self.speed = speed
        self._new_analyst()
        self.summary = None
        self._redraw_graph()
        self._render_summary()
        if self.mode == "review":
            self._render_move_list()
        self.goto(self.ply)
        self._start_analysis()

    def _start_analysis(self):
        self._run_id += 1
        if self._engine is not None:
            self._engine.stop_search()       # cut short the previous run's search
        self._render_summary()
        # Run from a timer inside the dialog: the work gets the dialog's
        # context for its UI updates, and is cancelled with the dialog
        with self.dialog:
            ui.timer(0.05, lambda rid=self._run_id: self._analyse(rid), once=True)

    def _show_progress(self, done, text):
        # The row stays for the speed selector; only the bar comes and goes
        self.progress.set_visibility(not done)
        self.progress_lbl.set_text(text)

    async def _analyse(self, run_id):
        def stale():
            return self.closed or run_id != self._run_id

        self._show_progress(False, "Starting the engine…")
        engine = await self.session.acquire_review_engine()
        if engine is None:
            self._show_progress(False, "No analyzer loaded — load one on the "
                                       "main screen to review games")
            self.progress.set_value(0)
            return
        self._engine = engine
        start = self.analyst.start_fen
        try:
            movetime = SPEEDS[self.speed][1]
            engine_id = engine.id_name or os.path.basename(engine.path)
            cache = ReviewCache()
            cached = await run.io_bound(cache.get, self.moves, engine_id,
                                        movetime, start)
            if stale():
                return
            if cached and len(cached) == self.n + 1:
                for i, analysis in enumerate(cached):
                    self.analyst.set_analysis(i, analysis)
                await run.io_bound(self._grade_all)
            else:
                for i in range(self.n + 1):
                    if stale():
                        return
                    book = i > 0 and self.analyst.in_book[i]
                    ms = max(50, int(movetime * (BOOK_SHARE if book else 1)))
                    analysis = await run.io_bound(
                        engine.analyse, " ".join(self.moves[:i]), ms, 2, start)
                    if stale():
                        return
                    if analysis is None:
                        self._show_progress(False, "The engine stopped — "
                                                   "review incomplete")
                        break
                    self.analyst.set_analysis(i, analysis)
                    if i:
                        await run.io_bound(self.analyst.grade, i)
                    self.progress.set_value((i + 1) / (self.n + 1))
                    self._show_progress(False, f"Analysing {i}/{self.n}")
                    if i % GRAPH_EVERY == 0:
                        self._redraw_graph()
                    if i == self.ply:
                        self._refresh_position()
                if self.analyst.summary().complete:
                    await run.io_bound(cache.put, self.moves, engine_id,
                                       movetime, list(self.analyst.analyses),
                                       start)
            if stale():
                return
            self.summary = self.analyst.summary()
            self._show_progress(True, "")
            self._redraw_graph()
            self._render_summary()
            if self.mode == "review":
                self._render_move_list()
            self._refresh_position()
        finally:
            if self._engine is engine and (self.closed or run_id == self._run_id):
                self._engine = None
            self.session.release_review_engine()

    def _grade_all(self):
        for ply in range(1, self.n + 1):
            self.analyst.grade(ply)

    # ── PGN / navigation between games / closing ──────────

    def _copy_pgn(self):
        ui.clipboard.write(self.src.pgn)
        ui.notify("PGN copied", type="positive")

    def _download_pgn(self):
        ui.download.content(self.src.pgn, "game.pgn")

    def _switch_game(self, key):
        opener = self.nav.get(key)
        if opener:
            self.dialog.close()
            opener()

    def _on_close(self):
        if self.closed:
            return
        self.closed = True
        if self._engine is not None:
            self._engine.stop_search()
        # Deleting the dialog also removes its keyboard listener; done from
        # the page root, after the closing animation
        with self.client.layout:
            ui.timer(0.4, self.dialog.delete, once=True)


def show_game_review(session, source, nav=None):
    """
    Open the Game Review screen.

    *nav* is an optional {"prev": opener | None, "next": opener | None};
    each opener is a callable that shows the neighbouring game.
    """
    if not source.moves:
        ui.notify(f"This game can't be reviewed: {source.problem}"
                  if source.problem else "This game has no moves to review.",
                  type="info")
        return None
    return ReviewScreen(session, source, nav)
