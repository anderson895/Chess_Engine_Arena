# ═══════════════════════════════════════════════════════════
#  webui/position_setup.py — The Set Up Position dialog
#
#  Where the next game starts, set the way chess.com and Lichess do it:
#  arrange the pieces on a board editor, paste a FEN or a PGN, pick a book
#  opening — and play moves on from any of those. The answer is a
#  core.start_position.StartPosition for the Play tab.
# ═══════════════════════════════════════════════════════════

import re

from nicegui import ui

from core.board import Board
from core.move_input import MoveInput
from core.pgn import read_game, start_fen_of, start_problem
from core.review import GameAnalyst
from core.start_position import StartPosition
from webui import dialogs, widgets
from webui.board import BoardView
from webui.quality import move_list_html
from webui.theme import COLOR_GREEN, COLOR_ORANGE

EMPTY_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"
WHITE_PIECES = "KQRBNP"
BLACK_PIECES = "kqrbnp"
PIECE_NAMES = {"k": "king", "q": "queen", "r": "rook", "b": "bishop",
               "n": "knight", "p": "pawn"}
CASTLING = (("K", "White O-O"), ("Q", "White O-O-O"),
            ("k", "Black O-O"), ("q", "Black O-O-O"))


class PositionSetup:
    """
    One open Set Up Position dialog.

    The setup is a position plus moves played from it, both held by a
    GameAnalyst — which also writes the moves' SAN and names the opening,
    as it does for every game. "Place pieces" edits the position on the
    board: an edit after moves were played keeps the position they reached
    and lets the moves go. "Play moves" plays legal moves from it.
    """

    def __init__(self, session, current):
        self.session = session
        self.current = current
        self.mode = "place"
        self.tool = None              # 'K' … 'p', "erase", or None: drag only
        self._dirty = False           # changed since it opened
        self._syncing = False         # controls being set from the position
        # Moves made on the board in "Play moves"
        self.hand = MoveInput(self._play_board, self._play_move,
                              can_move=lambda: self.mode == "play",
                              promote=session.ask_promotion)
        self._load(current.fen, current.moves)
        self._build()

    # ── State ─────────────────────────────────────────────

    def shown(self):
        """The position on the board: the setup's, after its moves."""
        return self.analyst.boards[-1]

    def _load(self, fen, moves=()):
        """Start the setup from *fen* (None: the standard start), *moves* played."""
        self.analyst = GameAnalyst(self.session.opening_book, start_fen=fen)
        for uci in moves:
            try:
                self.analyst.record(uci)
            except ValueError:
                break
        # The castling rights asked for: kept while the pieces are moved
        # around, and granted whenever the king and rook stand at home
        self.wanted_castling = set(self.analyst.boards[0].castling) - {"-"}
        self.hand.clear()

    def _rebase(self, board):
        """The setup now starts from *board*, edited by hand; any moves go."""
        allowed = board.castling_possible()
        board.castling = "".join(f for f in "KQkq" if f in self.wanted_castling
                                 and f in allowed) or "-"
        board.ep = "-"                # no pawn has just moved in an edited position
        wanted = self.wanted_castling
        self._load(board.to_fen())
        self.wanted_castling = wanted
        self._changed()

    def _changed(self):
        self._dirty = True
        self._refresh()

    def _label(self):
        """What the Play tab calls this start."""
        if self.analyst.opening_label:
            return self.analyst.opening_label
        return "Custom position" if self.analyst.start_fen else "Custom line"

    # ── Layout ────────────────────────────────────────────

    def _build(self):
        client = ui.context.client
        # Built at the page root, like the Game Review: wherever it was
        # opened from, it is deleted again once closed
        with client.layout, ui.dialog() as self.dialog, \
                ui.card().classes("arena-panel w-[940px] max-w-full gap-3"):
            widgets.heading("ic_settings", "SET UP POSITION",
                            text_cls="text-lg font-bold arena-title")
            with ui.row().classes("w-full no-wrap gap-5 items-start"):
                with ui.column().classes("gap-1 items-stretch shrink-0"):
                    self.top_palette = ui.row().classes(
                        "setup-palette w-full justify-center gap-1 no-wrap")
                    with ui.element("div").classes("setup-board"):
                        self.board = BoardView(self._state, on_click=self._click,
                                               on_drag_start=self._pick,
                                               on_drop=self._drop)
                    self.bottom_palette = ui.row().classes(
                        "setup-palette w-full justify-center gap-1 no-wrap")
                self._build_panel()
            with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
                ui.button("Cancel", on_click=lambda: self.dialog.submit(None)) \
                    .props("flat color=grey no-caps")
                self.use_btn = ui.button("Use this position", color=None,
                                         on_click=self._use) \
                    .props("no-caps unelevated").classes("cta setup-use")

        def delete_once_closed(e):
            if not e.value:
                # From the page root, after the closing animation
                with client.layout:
                    ui.timer(0.4, self.dialog.delete, once=True)
        self.dialog.on_value_change(delete_once_closed)
        self._build_palettes()
        self._refresh()

    def _build_panel(self):
        with ui.column().classes("flex-grow min-w-0 gap-2"):
            self.mode_toggle = ui.toggle(
                {"place": "Place pieces", "play": "Play moves"},
                value=self.mode, on_change=lambda e: self._set_mode(e.value)) \
                .props("spread no-caps unelevated toggle-color=primary "
                       "color=secondary text-color=white").classes("w-full")

            with ui.column().classes("w-full gap-1"):
                ui.label("SIDE TO MOVE").classes("arena-heading")
                self.side_toggle = ui.toggle(
                    {"w": "White", "b": "Black"}, value="w",
                    on_change=lambda e: self._set_side(e.value)) \
                    .props("no-caps unelevated dense toggle-color=primary "
                           "color=secondary text-color=white")
                ui.label("CASTLING").classes("arena-heading mt-1")
                self.castle_boxes = {}
                with ui.grid(columns=2).classes("w-full gap-0"):
                    for flag, text in CASTLING:
                        self.castle_boxes[flag] = ui.checkbox(
                            text, on_change=lambda e, f=flag:
                            self._set_castling(f, e.value)).props("dense")

            with ui.row().classes("w-full no-wrap items-center gap-1"):
                self.fen_input = ui.input(label="FEN") \
                    .props("dense").classes("flex-grow mono text-xs")
                self.fen_input.on("keydown.enter", lambda: self._load_fen())
                ui.button("Load", on_click=self._load_fen) \
                    .props("dense no-caps color=secondary") \
                    .tooltip("Set the board up from this FEN")
            with ui.row().classes("w-full no-wrap gap-2"):
                ui.button("Starting position", on_click=self._standard) \
                    .props("dense no-caps color=secondary").classes("flex-grow")
                ui.button("Clear board", on_click=self._clear) \
                    .props("dense no-caps color=secondary").classes("flex-grow")
                ui.button(icon="swap_vert", on_click=self._flip) \
                    .props("dense color=secondary").tooltip("Flip board")
            with ui.row().classes("w-full no-wrap gap-2"):
                ui.button("Pick Opening", on_click=self._pick_opening) \
                    .props("dense no-caps color=secondary").classes("flex-grow") \
                    .tooltip("Start from a book opening")
                ui.button("Paste PGN", on_click=self._paste_pgn) \
                    .props("dense no-caps color=secondary").classes("flex-grow") \
                    .tooltip("Set up a game's moves (a FEN tag sets its start)")

            with ui.column().classes("w-full gap-1") as self.moves_box:
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    ui.label("MOVES").classes("arena-heading flex-grow")
                    self.undo_btn = ui.button("Undo", icon="undo",
                                              on_click=self._undo) \
                        .props("dense flat no-caps size=sm color=grey-5") \
                        .tooltip("Take back the last move")
                with ui.scroll_area().classes("setup-moves w-full h-[120px]"):
                    self.moves_html = ui.html("", sanitize=False) \
                        .classes("move-grid w-full px-2")
            self.status = ui.label("").classes("text-sm font-bold")
            widgets.hint("The game goes on from here. You'll be asked "
                         "whether to record its result.")

    def _build_palettes(self):
        """Piece buttons above and below the board, each side's own."""
        top, bottom = ((WHITE_PIECES, BLACK_PIECES) if self.board.flipped
                       else (BLACK_PIECES, WHITE_PIECES))
        self.tool_buttons = {}
        for row, pieces in ((self.top_palette, top),
                            (self.bottom_palette, bottom)):
            row.clear()
            with row:
                for p in pieces:
                    side = "White" if p.isupper() else "Black"
                    btn = ui.button(on_click=lambda t=p: self._set_tool(t)) \
                        .props(f'flat dense data-piece="{p}"') \
                        .classes("setup-tool") \
                        .tooltip(f"Place a {side.lower()} {PIECE_NAMES[p.lower()]}")
                    with btn:
                        widgets.piece(("w" if p.isupper() else "b") + p.upper(), 46)
                    self.tool_buttons[p] = btn
        with self.bottom_palette:
            self.tool_buttons["erase"] = ui.button(
                icon="delete_outline", on_click=lambda: self._set_tool("erase")) \
                .props('flat dense color=grey-5 data-piece="erase"') \
                .classes("setup-tool").tooltip("Remove pieces")
        self._show_tool()

    # ── Board ─────────────────────────────────────────────

    def _state(self):
        board = self.shown()
        king = board.find_king(board.turn)      # None while a king is missing
        check = king if king and board.in_check() else None
        if self.mode == "play":
            return {
                "board": board,
                "last_move": self.analyst.moves[-1] if self.analyst.moves else None,
                "selected": self.hand.selected,
                "legal_dests": self.hand.dests(),
                "movable": self.hand.movable(),
                "check_sq": check,
            }
        # Placing: any piece can be dragged anywhere
        return {
            "board": board,
            "last_move": None,
            "selected": None,
            "legal_dests": set(),
            "movable": {(r, c) for r in range(8) for c in range(8)
                        if board.board[r][c] != "."},
            "check_sq": check,
        }

    async def _click(self, r, c):
        if self.mode == "play":
            if await self.hand.click(r, c) == "select":
                self.board.refresh()
            return
        if self.tool is None:
            return
        board = self.shown().copy()
        here = board.board[r][c]
        if self.tool == "erase" or here == self.tool:
            board.board[r][c] = "."          # the same piece again takes it off
        else:
            if self.tool in ("K", "k"):
                # One king a side: putting it down moves it, as on chess.com
                for row in board.board:
                    for col, p in enumerate(row):
                        if p == self.tool:
                            row[col] = "."
            board.board[r][c] = self.tool
        self._rebase(board)

    def _pick(self, r, c):
        if self.mode == "play" and self.hand.pick(r, c):
            self.board.refresh()

    async def _drop(self, fr, fc, tr, tc):
        if self.mode == "play":
            if await self.hand.drop(fr, fc, tr, tc) == "select":
                self.board.refresh()
            return
        board = self.shown().copy()
        piece = board.board[fr][fc]
        if piece == ".":
            return
        board.board[tr][tc] = piece
        board.board[fr][fc] = "."
        self._rebase(board)

    def _play_board(self):
        """The board moves are played on — while the position can be played."""
        board = self.shown()
        return board if board.position_problem() is None else None

    def _play_move(self, uci):
        self.analyst.record(uci)
        self._changed()

    # ── Controls ──────────────────────────────────────────

    def _set_mode(self, mode):
        if self._syncing or mode == self.mode:
            return
        if mode == "play":
            problem = self.shown().position_problem()
            if problem:
                ui.notify(f"Fix the position first: {problem}", type="warning")
                self._refresh()               # back to "Place pieces"
                return
        self.mode = mode
        self.hand.clear()
        self._refresh()

    def _set_tool(self, tool):
        self.tool = None if tool == self.tool else tool
        if self.mode != "place":
            self.mode = "place"
            self._refresh()
        self._show_tool()

    def _show_tool(self):
        for tool, btn in self.tool_buttons.items():
            if tool == self.tool:
                btn.classes(add="sel")
            else:
                btn.classes(remove="sel")

    def _set_side(self, side):
        if self._syncing or side == self.shown().turn:
            return
        board = self.shown().copy()
        board.turn = side
        self._rebase(board)

    def _set_castling(self, flag, on):
        if self._syncing:
            return
        if on:
            self.wanted_castling.add(flag)
        else:
            self.wanted_castling.discard(flag)
        self._rebase(self.shown().copy())

    def _load_fen(self):
        try:
            board = Board.parse_fen(self.fen_input.value)
        except ValueError as e:
            ui.notify(f"That FEN can't be read: {e}", type="warning")
            return
        self._load(board.to_fen())
        self.mode = "place"
        self._changed()

    def _standard(self):
        self._load(None)
        self._changed()

    def _clear(self):
        self._load(EMPTY_FEN)
        self.mode = "place"
        self._changed()

    def _flip(self):
        self.board.flip()
        self._build_palettes()

    def _undo(self):
        if self.analyst.ply:
            self.analyst = self.analyst.truncated(self.analyst.ply - 1)
            self.hand.clear()
            self._changed()

    async def _pick_opening(self):
        if not self.session.opening_book.loaded:
            ui.notify("Opening book not loaded — load an openings CSV first.",
                      type="warning")
            return
        moves, _name = await dialogs.ask_opening_choice(self.session.opening_book)
        if moves is None:
            return
        self._load(None, moves)
        self.mode = "play" if moves else "place"   # carry on from the line
        self._changed()

    async def _paste_pgn(self):
        with ui.dialog() as dlg, \
                ui.card().classes("arena-panel w-[560px] max-w-full h-[420px]"):
            widgets.heading("ic_book", "PASTE PGN",
                            text_cls="text-lg font-bold arena-title")
            box = ui.textarea(placeholder="1. e4 e5 2. Nf3 Nc6 3. Bb5 …") \
                .classes("w-full flex-grow pgn-box mono text-xs")
            widgets.hint("A [FEN] tag sets where the moves start; "
                         "a FEN on its own works too.")
            with ui.row().classes("w-full justify-end gap-2 dlg-foot"):
                ui.button("Cancel", on_click=lambda: dlg.submit(None)) \
                    .props("flat color=grey no-caps")
                ui.button("Load", on_click=lambda: dlg.submit(box.value)) \
                    .props("no-caps unelevated")
        text = (await dlg or "").strip()
        if not text:
            return
        # Some sites run the tags into the moves on one line: give each tag
        # a line of its own, as the PGN reader expects
        text = re.sub(r'(\[[A-Za-z0-9_]+\s+"[^"]*"\])\s*', r'\1\n', text)
        tags, moves = read_game(text)
        fen = start_fen_of(tags)
        if not moves and not fen:
            try:
                fen = Board.parse_fen(text).to_fen()     # just a FEN
            except ValueError:
                ui.notify(f"That game can't be set up: {start_problem(tags)}"
                          if start_problem(tags) else
                          "No moves found in that PGN", type="warning")
                return
        self._load(fen, moves)
        self.mode = "play" if moves else "place"
        self._changed()

    def _use(self):
        problem = self.shown().position_problem()
        if problem:
            ui.notify(f"No game can start here: {problem}", type="warning")
            return
        if not self._dirty:
            self.dialog.submit(self.current)  # unchanged: keep its name
            return
        start = StartPosition(fen=self.analyst.start_fen,
                              moves=tuple(self.analyst.moves),
                              label=self._label())
        self.dialog.submit(StartPosition() if start.is_standard else start)

    # ── Redraw ────────────────────────────────────────────

    def _refresh(self):
        """Bring the board and every control in line with the setup."""
        board = self.shown()
        placing = self.mode == "place"
        self._syncing = True
        try:
            self.mode_toggle.set_value(self.mode)
            self.side_toggle.set_value(board.turn)
            possible = board.castling_possible()
            for flag, box in self.castle_boxes.items():
                box.set_value(flag in board.castling)
                box.set_enabled(placing and flag in possible)
            self.side_toggle.set_enabled(placing)
            self.fen_input.set_value(board.to_fen())
        finally:
            self._syncing = False
        for row in (self.top_palette, self.bottom_palette):
            if placing:
                row.classes(remove="off")
            else:
                row.classes(add="off")

        self.moves_box.set_visibility(bool(self.analyst.moves) or not placing)
        self.moves_html.set_content(move_list_html(
            self.analyst.sans, [], self.analyst.ply, ply0=self.analyst.ply0))
        self.undo_btn.set_enabled(bool(self.analyst.moves))

        problem = board.position_problem()
        if problem:
            self.status.set_text(problem)
            self.status.style(f"color: {COLOR_ORANGE}")
        else:
            side = "White" if board.turn == "w" else "Black"
            label = self.analyst.opening_label
            self.status.set_text(f"{side} to move" + (f" · {label}" if label else ""))
            self.status.style(f"color: {COLOR_GREEN}")
        self.use_btn.set_enabled(problem is None)
        self.board.refresh()


async def ask_start_position(session, current):
    """
    The Set Up Position dialog, opened on *current* (a StartPosition).
    Returns the StartPosition chosen, or None when cancelled.
    """
    setup = PositionSetup(session, current)
    return await setup.dialog
